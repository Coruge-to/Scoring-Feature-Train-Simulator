# Phase PID-D4 / Slice 1 - the AtsEX Legacy telemetry on the per-PID DataPlane

Status (2026-10-15): implemented, tested offline, installed (Legacy telemetry DLL 0.4.2.0) and accepted on the real machine (BVE5 / AtsEX Legacy). Both live acceptance cases passed formally:
L-1 (Caller ON, launcher.json disabled: fail closed, nothing sent, no application) and L-A (launcher.json valid: managed run to a dynamic Directory-published port, HUD with real values, scoring
start refused with `missing-jump`, normal exit, both Directories gone). Owner decisions J2, J3, J4 of the Legacy contract-gap audit apply; J1 (the Legacy Jump Directory name) belongs to Slice 2
and is not used here. The Legacy jump, JUMP_COMPLETE, the pseudo turnback and scoring success are outside this slice (the other exclusions are listed in section 4).

## 1. What changed

The Legacy telemetry DLL (`TSScoringPlugin.AtsExLegacy.Telemetry.dll`, 0.4.2.0) no longer sends its texts through the plain UDP sink to the fixed port 54321 unconditionally.
`LegacyTelemetrySession` is unchanged (it still produces the same texts in the same order); its sink is now `LegacyDataPlaneSink` (`Telemetry\Legacy\src\LegacyDataPlaneSink.cs`, host
independent), which hands every text to the verified routing core of the Current sender, `TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs`, **linked unchanged** into the Legacy
project (a `Link` item; never copied, never edited): `CurrentModeLatch` + `CurrentTelemetryRouter` + `CallerControlPlaneProbe`. The Current jump endpoint source is not linked.

| text of the session | envelope MessageType |
|---|---|
| `SCENARIO_ID:...` (the telemetry line) | 1 |
| `STATUS:LOADED:RUNNING / PAUSED` (heartbeat) | 2 |
| `STALIST:...` | 3 |
| `META:...` | 4 |

A text of no known kind has no message type: dropped in managed mode (counted, reported once), plain as before in normal mode.

## 2. Managed and normal mode (never mixed; decided by the router, not by a Directory)

* **MANAGED** - the control plane event `Enabled` or `Ready` of this BVE process was observed at least once (latched; a later loss never returns to normal). Every text goes ONLY to the
  loopback endpoint that the managed application publishes in the Telemetry Directory of THIS BVE process, inside an Envelope v1 (`BvePid` = `SenderPid` = the BVE process id, the
  Directory's generation, AppInstance and token, zero RequestId). The shared reader (`TelemetryDirectoryReader`, unchanged) resolves AppDirectory -> Telemetry Directory and checks
  READY, BVE PID, AppInstance and AppPid. Anything unresolved, not READY, withdrawn, closed or mismatching = **nothing is sent (fail closed)**. There is no fallback to 54321 or 54322.
  The endpoint is resolved for every datagram; after a change (port, instance, generation, token) the old destination is never used again.
* **NORMAL** - neither event was observed during the 2 s hold-off after the first send attempt: the plain UTF-8 text to `127.0.0.1:54321`, byte for byte and in the same order as before.
  The managed Directory is never consulted. (New in timing only: the first send attempt starts the hold-off, as in the Current sender, so the first <= 2 s after it are held; STALIST / META are
  re-sent every second and are not lost for good.)
* **UNDETERMINED** - the hold-off: nothing is sent.

Shutdown: `Dispose` stops the heartbeat timer, ends the session, `LegacyDataPlaneSink.Close()` marks the sink closed, closes the router (summary line) and then the socket. A heartbeat
that races the close finds a closed sink or a closed socket and sends nothing; no datagram leaves after `Close()` has returned (tested with a real socket, 25 rounds).

## 3. Diagnostic log

`TSScoring-LegacyTelemetry-P<pid>-T<start>.log` in the Downloads folder: `pid` = the BVE process id, `start` = its start time (UTC, `yyyyMMddHHmmss`). One file per BVE process; a new
process never truncates the file of another. The fixed name `TSScoring-L3-Telemetry.log` is no longer created. The routing core's events appear as `TEL_DP event=...` lines
(`mode=managed`, `endpoint-adopted`, `first-send-managed type=.. port=.. gen=..`, `disconnected reason=..`, `summary ... plain=0 wrapped=.. types=1:..,2:..,3:..,4:..`); `TEL_INIT` names
`sink=dataplane bvepid=<pid>`.

## 4. Not in this slice

Legacy jump (endpoint, `0x100/0x101`, `JUMP_COMPLETE`, RequestId, the `LegacyJump` Directory), Smee `bp_initial`, `DOORTIME`, the stop-time impulse, any Python product change, any Current
change. The scoring start is therefore still refused with `missing-jump`, and no workaround exists. Version 0.5.0.0 stays reserved for the Slice 2 (jump) build.

## 5. Tests

`Tests\Test-LegacyDataPlaneD4.ps1` (+ `Tests\LegacyDataPlaneTestFixture.cs`, `tests\legacy_dataplane_chain_check.py`, `tests\test_legacy_dataplane_interop_d4.py`): the real DLL driven through the
fake Legacy API - the four kinds, Envelope v1 fields, zero fixed-port sends, every fail-closed reason (also against real named events / mappings of a synthetic BVE process and real loopback
sockets), endpoint changes, normal mode byte equivalence with the old sink, the hold-off, the heartbeat, thread races, the per-process log name, the real Python receiver + strict gate + Overlay
(HUD values in the normalised state), and the invariants (Current DLL, Current sources, the three shared files, Python product code, 54322, no Legacy jump).
`Tests\Test-TelemetryIntegrationL3.ps1` now runs the Legacy -> managed chain for real (it was SKIP until this slice).
