# Phase PID-D4 / Legacy Jump 2A-alpha - the Legacy Jump Directory plane (receive and keep only; nothing is executed)

Status (2026-10-19): implemented, tested offline, installed (Legacy telemetry DLL 0.5.0.0) and accepted on the real machine (BVE5 / AtsEX Legacy, plus one Current regression case).
The real-machine acceptance gate G-3b (cases LJB-1, LJB-2, LJB-3a, LJB-3b, LJB-3c, LJB-4, LJB-5, LJB-6) is formally passed with no product failure, and the owner declared it accepted.
This slice builds the Legacy side of the per-PID Jump Directory. It does not make the Legacy jump work: the Legacy host still announces no `jump`, so the scoring start in Legacy is still
refused with `missing-jump`. The items that are not implemented are listed in section 9 and must not be read as done.

## 1. What changed

| area | change |
|---|---|
| Legacy telemetry DLL (`Telemetry\Legacy`) | three new host-independent sources `src\LegacyJumpEndpoint.cs`, `src\LegacyJumpCommandQueue.cs`, `src\LegacyJumpControlPlane.cs`; version 0.4.2.0 -> 0.5.0.0 (`src\AssemblyInfo.cs`); the project links the Current source `TsScoringPlugin\CurrentJumpEndpoint.cs` UNCHANGED (a `Link` item, never copied or edited) and uses only four of its types: `JumpDirectoryPublisher`, `JumpCommandValidator`, `CurrentJumpCommand`, `JumpCapabilities.RequestId` |
| `src\LegacyTelemetryExtension.cs` | wiring only: build the plane in the constructor, `OnHostTick` in `Tick`, `NoteScenarioBoundary` in the three scenario events, `Dispose` of the plane before the telemetry part shuts down; each call is inside its own `try` |
| `src\LegacyTelemetrySession.cs` | a diagnostic only: one `TEL_DISCONTINUITY` line per discontinuity the session already counted (see section 7); the counter, the 300 ms judgement and `TEL_DISPOSE` are unchanged |
| Python | `current_jump_client.py` reads the Jump Directory with open -> read -> close on every attempt and resolves the Directory name when a command is sent; `dataplane_contract.py` gains `legacy_jump_name(pid)` and `jump_directory_names(pid)` |
| tests | new tests and the simultaneous update of the pins that the change had to move (section 8) |

Not touched: `TsScoringPlugin\TsScoringPlugin\` (the Current product and DLL), the other shared sources (`DataPlaneProtocol.cs`, `TelemetryDirectoryReader.cs`, `GenericHandleTextContract.cs`,
`TelemetryContract.cs`), `LegacyDataPlaneSink.cs`, `LegacyApi.cs`, `main.py`, `scoring_logic.py`, `managed_input.py`, the Directory layout, the 96-byte Envelope and the message types.

## 2. Current and Legacy stay separate

The Legacy plane never references a host type (no AtsEX, no BveTypes, no Handshake). The Current jump endpoint is not created in the Legacy DLL: the linked `CurrentJumpEndpoint.cs` is used only for
the four shared types above, and an IL scan of the built DLL requires that no method calls `CurrentJumpEndpoint::Create` or its constructor. A Current process has no `LegacyJump` Directory and a
Legacy process has no `CurrentJump` Directory (one name per host). The Python side asks the generic name list of `dataplane_contract` (Current name first, Legacy name second); `current_jump_client.py`
itself names no host (the existing "no `legacy` word in the client" pin is kept and satisfied).

## 3. The Directory and the endpoint

* Name: `Local\TSScoringPlugin.v1.<BVE PID>.LegacyJump` (STDJ v1, the same 128-byte Jump Directory layout as the Current one; PID-D0B-1 is not changed).
* Created with `CreateNew` only. A failure at any step rolls the partial endpoint back (port closed, mapping released) and the plane waits to try again. There is no attach to an existing
  mapping, no overwrite and no fixed-port fallback.
* The endpoint owns one **dynamic loopback UDP port**. After the bind the port is compared with `TelemetryContract.Port` (54321) and `Port + 1` (54322); on a match the socket is closed and a new
  one is made. The fixed ports are never bound and never written to. The ports are expressed through the contract constants, not as literals (the existing "no `54322` in Legacy code" pin is unchanged).
* Every publication gets a **new generation and a new token**. READY is published only when the mapping, the port and the writer are all in place, with the capability `REQUEST_ID` (0x4) and
  nothing else: no station-time, location-time or published bit ever appears.
* The owner (the managed application that sent a datagram) is checked against the Telemetry Directory of the same BVE process through the shared reader; the accepted command records the owner.

## 4. Receiving and keeping a command (no execution)

* Datagrams are judged by the shared `JumpCommandValidator` (envelope, BVE PID, owner, generation, token, message type, text grammar). The plane does not interpret the text: it is kept opaque in the
  receipt. There is no field for a station index, a position or a distance.
* States of a command: `Rejected` (failed validation, nothing queued), `Queued`, `Discarded`. There is no further state: nothing is claimed, executed or completed.
* The queue is **depth 1, newest first**. A newer valid command replaces the queued one (the older one is `Discarded`). A queued command is discarded when the owner changes or is lost, the
  endpoint is re-created, the scenario boundary counter moves, or the plane is disposed. The time limit exists as a mechanism only; the product runs with **no TTL** (decision D-2), so nothing expires by time.
* Receipts are kept in a bounded list (512) for the diagnostics; at most 32 datagrams are read per step.
* The plane calls no Legacy API (`Initialize`, `InitializeTimeAndLocation`, `SetTime` and the others), publishes no `jump` in AVAIL, and a managed application therefore refuses to send
  (`command-unsupported`, and the scoring start is refused earlier with `missing-jump`).

## 5. Worker, gate and lifetime

* **One dedicated worker thread**, not the host Tick. The host Tick stops while BVE is paused or loading, and the Directory has to stay serviceable then. The Tick only starts the worker (once) and
  checks that it is alive; a dead worker is restarted unless a stop was requested.
* **Start condition** (facts only, no time): the extension exists, the sender mode latch says Managed, the scenario events were subscribed, the plane is not disposed, the BVE PID is known and the
  plane has not started. In normal mode, while undetermined, or after a failed subscription nothing is created (no Directory, no socket, no thread).
* **One gate** guards the endpoint, the queue and the books; the log callback is called after the gate is released. Every wait that `Dispose` makes on the gate or on the worker is bounded
  (Join 1000 ms, gate 1000 ms; abnormal cases only). Polling interval 20 ms; Directory creation retry back-off 250 ms up to 2000 ms (provisional, decision D-3; a retry interval, not a command lifetime).
* The worker ends only on a stop request; an exception in one iteration is caught and the endpoint goes to retry. Failures in the plane switch only the plane off: the telemetry is unaffected.

## 6. Shutdown order (decision D-5)

The relative order of PID-D0B-1 section 15.3 is unchanged: WITHDRAWING before the socket close, CLOSED after it, release last. The plane is shut down completely before the telemetry part:

1. stop receiving, 2. expire the queued command, 3. request the worker to stop, 4. bounded Join outside the gate, 5. WITHDRAWING, 6. close the socket, 7. CLOSED, 8. release the mapping and the plane's
resources, 9. telemetry shutdown, 10. release of the rest of the extension and `TEL_FINAL`. If the gate cannot be taken, the worker finishes the same teardown when it leaves. After the BVE process
has ended, the same name can be created again (new generation, new token, new socket) and a second writer for the same name is refused.

## 7. Diagnostics

* `TEL_JUMP` lines (state changes and a summary at the end; no periodic line) go to the per-process Legacy log. Command lines are capped at 32 per plane lifetime (then one "capped" line); the token is never logged.
* `TEL_DISCONTINUITY`: one line per discontinuity that `LegacyTelemetrySession` already counts (14 keys in a fixed order, invariant culture), at most 64 per process, then one
  `TEL_DISCONTINUITY_LIMIT` line; never per Tick. It carries no heartbeat key, so it is identical with and without the SI-0 order recorder. The counter, the 300 ms threshold, the judgement and
  `TEL_DISPOSE` are unchanged (the session differs from the baseline by added lines only).

## 8. Tests

* `Tests\Test-LegacyJumpPlane2A.ps1` (+ `Tests\LegacyJumpPlaneTestFixture.cs`, `Tests\LegacyJumpPlaneTestKit.cs`, `Tests\LegacyIlCallScan.cs`, `Tests\Serve-LegacyJumpPlane2A.ps1`): modes Static, Self, Product,
  Python, Mutation, Regress and All. Product mode compiles the tests against the built DLL and runs 33 cases (ITR-01..16, EX-01..03, WIN-01..04, PT-01..09, WIN-99): the state machine and the queue,
  the failure and stop injections, real named mappings and loopback sockets on synthetic BVE PIDs, the shutdown order, the capability set, the fixed ports never bound, and the IL scan. No BVE and no AtsEX
  runtime is needed; the fixed ports 54321 / 54322 are never touched.
* `tests\test_jump_directory_reader_2a.py` and `tests\test_legacy_jump_plane_interop_2a.py`: the Python Reader (open / read / close every time, name resolution at send time, `jump-host-ambiguous`,
  an outstanding request reading only its recorded name, no handle held) against the real plane.
* `Tests\Test-LegacyDiscontinuityDiag.ps1`: the `TEL_DISCONTINUITY` diagnostic. Its differential check PD-20 against an earlier reference DLL runs only when `-ReferenceDll` is given (together with
  `-ReferenceSha256`); otherwise PD-20 is reported as SKIP, which is not counted as a pass.
* Pins that moved with this change (the assertions were replaced by the exact new contract, never loosened): F32 (`tests\test_jf1_current_csharp_source_pins.py`), B05 / B06 (`Test-CurrentJumpD6.ps1`),
  F06 / F09 / F10 / F18 (`Test-LegacyDataPlaneD4.ps1`), L06 (`Test-GroundLimitsSI1.ps1`), the built-DLL pin of `Test-StationTimelineJF1.ps1`, X13 (`Test-TelemetryL3.ps1`: `Receive(` is allowed in
  `LegacyJumpEndpoint.cs` only), the allow-lists / source-scan sets of `Tools\Verify-PhaseL3.ps1` and `Tools\Verify-PhaseC3.ps1`, the fake Directory sources `tests\d6_rig.py` and `tests\test_jump_complete_d6.py` (a fake now
  knows only its own name), `tests\test_dataplane_contract_pid_d1.py`, and the version / source pins of the earlier Legacy tests.

## 9. Real-machine acceptance (G-3b) and what is not implemented

Results (each case is one BVE start; a run that was judged invalid for a procedure reason was repeated and is not a product failure):

| case | what it showed | result |
|---|---|---|
| LJB-1 | Legacy start -> managed -> LegacyJump Directory READY with REQUEST_ID only; an idle Reader holds no handle; normal exit | PASS |
| LJB-2 | endpoint unchanged (generation, token, port) across F5 while running, F5 while paused, scenario end and re-selection | PASS |
| LJB-3a / 3b / 3c | normal exit while paused / while loading / after an explicit scenario end: shutdown order kept, Directory gone | PASS |
| LJB-4 | Current regression: the official jump and its completion as before; no `LegacyJump` Directory in a Current process | PASS |
| LJB-5 | Legacy scoring start refused with `missing-jump`, nothing sent, train position and time unchanged | PASS |
| LJB-6 | after BVE exit, a same-name `CreateNew` succeeds first time with a new generation / token / socket; a duplicate writer is refused | PASS |

The raw logs, judge output and closure records of these runs are kept outside this repository and are not part of it.

**Not implemented in this slice (do not read any of these as done):** executing a command or any call into the Legacy API; the `jump` item in AVAIL and any command capability bit; `JUMP_COMPLETE`
for Legacy; sending a Legacy jump from Python; claim / execution / completion notice and the exclusion of Queued -> Executing against Queued -> Discarded under one gate (2A-beta entry); a command TTL, an
age gate and watchdog values (to be decided after the timing measurements); cancel; making `StationIndex` the authoritative jump target, the pseudo turn-back, P-to-P and the stop-time impulse;
the correction of the F5 target selection and the removal of the 50 m search. The Python files `main.py`, `scoring_logic.py` and `managed_input.py` are unchanged.
