# Phase PID-D6 (necessary minimum slice) - the managed JUMP_COMPLETE with a RequestId

Status: implemented, offline-tested, NOT deployed, NOT committed, NOT pushed. Live re-test (BVE6 alone, one run) is pending.
Contract: PID-D0B-1 (Shared DataPlane Contract v1) sections 4.2, 8, 9, 10, 11, 13.2, 13.3, 14, 15.3. **No contract change was needed**: the binary layouts (Telemetry
Receiver Directory, Current Jump Receiver Directory, Envelope v1), the AppDirectory ownership source, the shutdown order, the managed lifecycle and the Current / Legacy
separation are those of D0B-1. The `STDJ` directory, the type 5 / 0x100 / 0x101 message types and the capability bits 0x4 existed in the shared codecs since PID-D1
(`DataPlaneProtocol.cs`, `dataplane_contract.py`); D6 only connects them.

## Why

PID-D3 moved the managed Telemetry to the per-PID DataPlane and, by owner decision DEC-2, did not carry the JUMP_COMPLETE (it had no RequestId yet). The scoring start
calls `begin_official_jump`, which sets `is_official_jumping` (then `jump_lock` when BVE jumps); the only normal release is the JUMP_COMPLETE. Without it every scoring
feature behind the flag stayed dead (basic brake, running time, stop position, departure, door-open arrival, scoring end, result display, A->B shortening) and the F8
auto release (skipped while `is_official_jumping`) did not fire. Audit: the Stage A CTEL log showed `jump-complete-excluded` 29 ms after the Caller `scoring-start`.

## What changed

| Side | File | Change |
| --- | --- | --- |
| Current | `TsScoringPlugin\CurrentJumpEndpoint.cs` (new) | `CurrentJumpEndpoint` (loopback UDP socket on port 0 + the Current Jump Receiver Directory `Local\TSScoringPlugin.v1.<BVE_PID>.CurrentJump`, PUBLISHED then READY, capabilities STATION_TIME \| LOCATION_TIME \| REQUEST_ID, random generation and 128-bit token; Dispose = WITHDRAWING, close socket, CLOSED), `JumpDirectoryPublisher`, `JumpCommandValidator` (contract 10 / 13.3) |
| Current | `CurrentDataPlane.cs` | `SendBatch.SendJumpComplete(payload, requestId)`: a type 5 envelope with the SAME RequestId to the Telemetry endpoint (needs capability 0x4); message type constants |
| Current | `Class1.cs` | creates / disposes the endpoint in its own try block; `CollectJumpCommands()`; the fixed 54322 receiver stays for the NORMAL mode only (in managed mode and during the hold-off its datagrams are drained and NOT executed - no plain fallback); the pending jump carries the RequestId to the completion |
| Python | `current_jump_client.py` (new) | RequestId generation, command envelope, match / duplicate / stale / unknown / invalid answers, cancel rules, timeout |
| Python | `telemetry_dataplane_receiver.py`, `dataplane_contract.py`, `telemetry_receiver_directory.py` | type 5 accepted (payload prefix `JUMP_COMPLETE:`), `last_request_id`; the Telemetry directory advertises JUMP_COMPLETE_V1 (0x4); jump constants |
| Python | `main.py`, `scoring_logic.py` | `Overlay.send_jump_command` (managed: envelope + RequestId, normal: plain 54322 as before), `_jump_complete_acceptable`, `_poll_jump_client`; the two transport call sites (scoring start, retry) call `send_jump_command`; `run_managed` creates the client for the Caller owner and closes it before the receiver stops |
| Python | `managed_input.py`, `managed_app_directory.py` | the outstanding request is cancelled at a generation boundary / session end; `jump_client` classified as infrastructure; `Win32DirectorySource(size)` (the jump directory is 128 bytes) |

## The RequestId contract

* Generation: `secrets.token_bytes(16)`, nonzero, never one of the recently finished ids. One request is outstanding at a time.
* Transport: the command (unchanged legacy text `JUMP_STA_TIME:<i>:<ms>` / `JUMP_LOC_TIME:<loc>:<ms>`) goes in an Envelope v1, type 0x100 / 0x101, SenderPid = the application's PID, BvePid / AppInstance / generation / token of the published jump endpoint, to the port in the directory.
* Current accepts it only if: BvePid, the current usable AppDirectory instance, endpoint generation and token, the message type, SenderPid = AppPid, the payload grammar and a not-yet-seen RequestId (bounded recent-request cache, 64). Otherwise it is dropped, counted, and logged once per reason.
* The echo: when the jump is done Current sends a type 5 envelope (SenderPid = BvePid, generation + token of the TELEMETRY endpoint) whose RequestId is byte-for-byte the command's.
* Python releases the official jump only if the echoed id equals the outstanding request ("ok"). Duplicate (already completed), stale (superseded / cancelled / timed out), unknown (never issued) and invalid (zero / wrong length) completions change nothing.
* Cancel (no retry, a later completion is stale): endpoint withdrawn / closed / generation or token changed, generation boundary, scoring session end, shutdown, timeout (10 s).
* A lost completion is DETECTED (log `[JUMP] event=timeout`, `client.last_failure`) and never guessed from the telemetry.

## The timeout contract (final: fail closed, the scoring session is ABORTED, not left stuck)

An official jump that can no longer be completed ends THAT scoring session. It does not stay "scoring on" with a silently dead run, and `is_official_jumping` is never released on its own (that would resume scoring after a jump that did not happen).

* Three events leave an official jump unreleased, and the client reports each of them once through `take_unreleased()`: a REFUSED send (no request exists, so no timeout would ever fire: this was a permanent stuck), the TIMEOUT (10 s), and an ENDPOINT withdrawn / closed / re-published while the request is outstanding. A cancel the application asks for itself (session end, generation boundary, shutdown, scoring abort) is never reported that way.
* `Overlay._poll_jump_client` takes the report and calls `_abort_unreleased_official_jump`, which reuses the shape of the existing illegal-jump abort of `scoring_logic.update_physics_and_scoring`: scoring off, the two warning popups ("公式ジャンプが完了しませんでした。" / "採点を中断します。"), `is_official_jumping` cleared together with the scoring mode, `jump_lock` set (released by the existing departure rule), the transient state reset. No result is fixed (`is_scoring_finished` stays False) and none is shown; the input controller reports `[MANAGED] event=scoring-abort reason=jump` and releases the input holds by its existing observation.
* The request is cancelled with the abort, so a late JUMP_COMPLETE (even one carrying the right id) is stale and revives nothing. The command is never resent and never sent to another endpoint.
* The next scoring start is a normal start (new official jump, new RequestId). Normal mode has no client and is unchanged.
* The timeout is wall-clock (`time.monotonic`) and is polled with the sender's datagrams; it is not extended for a BVE pause. Nothing new is added to the state machine and no new fixed port is used.
* Not covered (existing behaviour, unchanged): a completion that arrives with the matching RequestId but a location that does not match `expected_target_loc` is logged as `[JUMP COMPLETE REJECTED]` and leaves the flag set.

## Diagnostics of the live run

The Caller copies only `[MANAGED] ` lines of the application's stderr into its log (200 lines, 160 characters each). `main._managed_jump_log` therefore re-issues the jump client's `[JUMP] event=...` lines as `[MANAGED] event=jump-<name> inst=... owner=caller pid=... <fields>` (at most 24 event lines, the closing `jump-summary` always). The client itself, the contract and the scoring are unchanged. Together with Current's `jump-command-first-accept` / `jump-complete-sent` (the first one is a line, the rest is counted in the summary) the RequestId can be followed end to end: command-sent -> first-accept -> complete-sent -> complete-accepted (judge: live-d6\Judge-PidD6-Live-v1.ps1).

## Tests (all offline)

`Tests\Test-CurrentJumpD6.ps1` (54 compiled checks + 15 static), `tests\test_jump_complete_d6.py` (77), `tests\test_current_jump_interop_d6.py` (real C# validator + router <-> real Python client / receiver),
`tests\test_current_jump_endpoint_live_d6.py` (real C# endpoint: named mapping + loopback socket, real Python client). `tests\d6_rig.py` runs the real Overlay with the production wiring
and reproduces the audited failure (without the completion the run is dead), the timeout abort (lost completion, refused send, withdrawn endpoint) and the recovery (start, jump, completion, A->B, scoring end, result display, F8 auto release).
