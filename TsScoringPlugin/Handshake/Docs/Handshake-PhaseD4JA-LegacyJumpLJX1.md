# Phase PID-D4 / Legacy Jump LJX-1 - the minimal execution slice (behind a build flag; accepted on the real machine with documented residual risk)

Status (2026-10-21, overall close): LJX-1 OVERALL ACCEPTED WITH DOCUMENTED RESIDUAL RISK. The acceptance build (flag ON, Legacy telemetry DLL 0.6.0.0, SHA-256
A060272CD4AC7D74400055AB6304A01AE8AE340957EF64679D950EA5105730F0) was run on BVE5 / AtsEX Legacy across the cases L-01 .. L-14 (section 11). The DEFAULT build (flag OFF, SHA-256 43E7B9D3...F691)
is behaviourally the 2A-alpha build, was never deployed and is NOT promoted: whether the acceptance build or the flag default becomes the general default is a separate decision (OD-X11, still open).

Status at implementation time (2026-10-20, kept as history): implemented and tested offline (the isolated fixtures, the real plane with a real named mapping and real loopback sockets, and the
managed application's own jump client and receiver). The DEFAULT build (flag OFF) is behaviourally the 2A-alpha build and is not what the live acceptance runs. The ACCEPTANCE build (flag ON) had NOT
been deployed and NOT been run in BVE at that time.

## 1. What this slice is, and what it is not

It adds the smallest execution path to the Legacy Jump Directory plane of 2A-alpha: the host Tick claims ONE accepted command, runs the station jump or the location jump through a
host seam, writes the telemetry row with the JUMP counter and then sends the JUMP_COMPLETE (the existing type 5 envelope, RequestId echoed). The Directory then carries
`STA | LOC | REQUEST_ID` (0x7) and the telemetry announces `jump` in AVAIL, so the managed application stops refusing with `command-unsupported` and `missing-jump`. The Python half is NOT changed.

Not in this slice (unchanged, do not read as done): a cancel on the wire, a new message type, any change of the Directory / Envelope / layout (D0B-1), any change of the Current product or of
the five shared sources, StationIndex as the source of truth (M3L), checkpoint / retry / Save, the pseudo turn-back, PTO-9, P to P, the stop-time impulse, the three remaining PID gaps, a
product fix of the BveTs exit-time crash (a known baseline, see section 10), a second observation run (O-1), a new harness.

## 2. The build flag (decision OD-X16, option A)

* **Where it lives:** a compile symbol, `LEGACY_JUMP_EXEC`. `src\LegacyJumpExecutor.cs` defines `LegacyJumpBuild.ExecutionCompiledIn` as `true` under `#if LEGACY_JUMP_EXEC`, else `false`.
* **How it is set:** only by `/p:LegacyJumpExec=true` on the build of `TSScoringPlugin.AtsExLegacy.Telemetry.csproj`. The project's own `DefineConstants` is `TRACE`: the default build has no symbol.
* **Default:** OFF. The committed state is OFF. Nothing in the user's configuration, no file and no environment variable switches it on: a DLL either was built with the symbol or was not.
* **OFF means:** the Directory carries `REQUEST_ID` (0x4) only, no command is claimed or executed, no completion is sent, AVAIL has no `jump`, the rows have no `JUMP` key, the TTL stays 0 (decision D-2),
  and the final summary line is the 2A-alpha one. The scripted output of the earlier phases (the golden OFF run of `Test-LegacyJumpExecLJX1.ps1`) is byte for byte the same as before this slice.
* **How a test switches it on:** the environment object (`LegacyJumpEnvironment.ExecutionEnabled` / `FeatureBits`) is set by the fixture; the shipped DLL of the default build can therefore be tested in both
  states, and the acceptance build is tested with `-CompiledIn`.
* **Not exposed to users.** The acceptance build is a separate, hash-pinned DLL that the owner installs on purpose (see the deployment plan of the stage folder) and that is never the default.

## 3. States of a command

`Rejected` and `Queued` and `Discarded` are the 2A-alpha states. LJX-1 adds `Executing`, `CompletionPending`, `Completed`, `Failed`, `Abandoned`.

| from | to | by |
|---|---|---|
| Queued | Executing | `TryClaimForTick` (the one claim entry, host Tick thread, never blocks; the transition is written BEFORE the host call) |
| Queued | Discarded(reason) | the worker's sweep or the claim itself: `replaced`, `scenario-epoch`, `ttl`, `owner-lost`, `owner-changed`, `endpoint-recreated`, `breaker-open`, `dispose` |
| Executing | CompletionPending / Failed | `ReportExecution` after the host sequence |
| Executing / CompletionPending | Abandoned(reason) | `dispose`, `endpoint-recreated`, `superseded` (a newer command), the completion fact checks, `completion-excluded` |
| CompletionPending | Completed | the sender consumed a datagram (`Sent`) |

`Discarded` still means "the host API was never called for this command". At most one command is in flight. Every other pair is an illegal transition (counted; the tests require 0).

## 4. Claim, facts and the TTL

The claim takes the gate with a zero wait (a busy gate is counted as `claim-contended` and the Tick goes on). Under the gate, in this order: scenario boundary (`scenario-epoch`), breaker, age (`ttl`),
receiver generation (`endpoint-recreated`), owner (`owner-lost` / `owner-changed`). A command whose facts are void is Discarded without any host call. The scenario must be created and the telemetry
session must have an active instance, otherwise the command simply waits (it is still subject to the TTL).

* **TTL: 5.0 s** (`LegacyJumpTimings.ExecutionTtlMs`), measured from the moment the worker read the datagram, checked by the worker's sweep (so a command that waited through a Pause is
  `Discarded(ttl)` while the Tick is silent) and again by the claim. `now - received > 5000` expires; exactly 5000 ms does not. The managed application's own wait stays 10.0 s (pinned on both sides).
* **ageAtClaim:** every claimed command writes `jump-exec-claimed ... ageAtClaimMs=<n>`; the receipt carries it; the final summary line carries `ageAtClaimMax`. The acceptance criterion is a maximum of 1.0 s or less.
* **Executing watchdog:** a diagnostic only. The elapsed milliseconds of the host sequence are written (`jump-exec-end ... elapsedMs`, `execElapsedMax`). A synchronous host call is never interrupted
  and the gate is not held while it runs, so the worker and `Dispose` are not stopped by it.

## 5. The host sequence (STA and LOC in the same slice)

Arguments are checked BEFORE the first host call (index and time ranges, a finite location; the station must exist; the scenario must be readable). Then:

| command | host sequence | expected after |
|---|---|---|
| `JUMP_STA_TIME:<index>:<ms>` | `Scenario.Initialize(index)`, then `TimeManager.SetTime(ms)` | time == ms exactly, location within 0.01 m of the station's location read before |
| `JUMP_LOC_TIME:<loc>:<ms>` | `Scenario.InitializeTimeAndLocation(loc, ms)`, then `TimeManager.SetTime(ms)` | time == ms exactly, location within 0.01 m of `loc` |

Any exception, a mismatch, a partial execution, a scenario boundary during the call or a re-entrant call is `Failed` (reason recorded): no completion is sent, nothing is repeated, nothing is repaired.
The only type that names the host jump API is `AtsExLegacyJumpHost` in `LegacyTelemetryExtension.cs` (one call instruction per API, 3 in total, shared by the two sequences); an IL scan and a call graph
over the built DLL pin that and require that only `Tick` reaches it.

## 6. The row and the completion

Order inside one host Tick: `TickPre` (claim, host calls, read back) -> `session.OnTick` (the row) -> `TickPost` (the completion). The session announces the jump group only while the plane says its
contract is open: execution ON, every feature present (STA, LOC, completion and the runner), the plane READY, not stopping, the breaker closed. The group is `AVAIL ... jump` together with the
`JUMP:<Discontinuities>` key (the 300 ms rule is unchanged); `NoteOfficialJump` makes the station state restart on the execution Tick whatever the time step was.

The completion is `JUMP_COMPLETE:<STA|LOC>:<index or -1>:<location>:<time>:<jump_count>` (invariant culture) as a type 5 envelope with the RequestId of the command, sent by
`LegacyDataPlaneSink.SendJumpComplete` through the Current routing core to the Directory-published Telemetry endpoint of this BVE process (no fixed port, no Current fallback). `jump_count` is the
`JUMP` value of the row of the same Tick. The sender answers `Sent` (Completed), `Excluded` (consumed without a datagram: Abandoned `completion-excluded`) or `Held` (the same completion is tried
again on the next Tick while the facts hold; the facts recorded at the acceptance are compared with those of now - scenario boundary, receiver generation, owner - and a difference ends the
command Abandoned). `Completed` is never assumed.

## 7. The breaker (decision OD-X6 option B; N = 3 approved by the owner on 2026-10-21)

Three execution failures in a row close AVAIL `jump` (so the managed application refuses a new scoring start with `missing-jump` instead of sending commands nobody executes) and make the claim
discard with `breaker-open`. A success resets the count; a new scenario boundary reopens. **Decision (owner, 2026-10-21): the number 3 and the reset rule are approved (OD-X6).** Basis: the first live acceptance (case L-14)
showed the whole chain in one run - reset by a success, three failures in a row, the breaker opening exactly once right after the third failure, the next request discarded as `breaker-open` without a claim or a host call,
AVAIL `jump` leaving the application availability and the scoring start refused with `missing-jump` - with no early and no late opening, a maximum ageAtClaim of 14 ms, and no product failure.

## 8. Shutdown

Unchanged order (D-5). In addition `Dispose` ends the command in flight as `Abandoned(dispose)` (an Executing host call, if one is running, finishes; the report then finds the receipt ended and changes
nothing, and no completion is sent), and no claim, host call or completion can start after `Dispose` began.

## 9. Tests

`Tests\Test-LegacyJumpExecLJX1.ps1` (Static pins S01..S14, the 33 product cases LJX-01..32 and LJX-99, the golden OFF comparison), `tests\test_legacy_jump_exec_ljx1.py` (the managed application's
own client and receiver against a served product plane), and the moved pins of the earlier suites (each moved pin is marked "Phase LJX-1 (pin moved)" in its test). The cases bind the product by
reflection, so a missing element is an expected RED; the RED evidence, the mutation results and the full list are in the stage folder of the session.

## 10. Known baseline that this slice does not touch

BveTs (5.8.7554.391) has crashed at exit with `ntdll.dll` 0xc0000005 (offset 0x60d99) on many earlier runs, 0.4 s after `TEL_FINAL`, before the Jump plane existed. It is a recorded baseline; a
crash that matches it exactly and happens after the shutdown completed is recorded, not counted as a product failure. Any other crash signature, a crash before the shutdown, or a leftover
worker / socket / mapping is PRODUCT-SUSPECT and stops the acceptance.

## 11. Real-machine acceptance and overall close (2026-10-21)

The evidence (runs, saved copies, re-judgements, closure records) lives in the acceptance evidence root outside the repository; this section records only the formal result.

**Overall disposition: LJX-1 OVERALL ACCEPTED WITH DOCUMENTED RESIDUAL RISK.** Product failures: 0 in every adopted case. Procedure-invalid and inconclusive verdicts in the adopted cases: 0.

| Case | What the real machine showed | Formal state |
|---|---|---|
| L-01 | application-driven station jump on BVE5 Legacy: accepted, claimed (ageAtClaim 12 ms), executed, JUMP_COMPLETE, completed by the application | PASS |
| L-02 | location jump (type 0x101) by the probe: executed (3 ms), JUMP_COMPLETE sent | PASS |
| L-03 | request held through a Pause: `Discarded(ttl)` after 5008 ms, the Legacy API was never called, no delayed jump after the resume | PASS |
| L-04 | request over a scenario reload: `Discarded(scenario-epoch)` in the same millisecond as the boundary, no Legacy API call | PASS |
| L-05 | seven invalid requests: all rejected, none accepted | PASS |
| L-06 | duplicate RequestId: one accepted, one rejected; the accepted one `Discarded(ttl)` after 5014 ms | PASS |
| L-07 | four malformed datagrams: all rejected (`payload-grammar`) | PASS |
| L-08 | SPLIT-CLOSE: L-08a PASS (existing direct evidence), L-08b PASS (offline joined fixture), L-08c BLOCKED-ACCEPTED-RISK | SPLIT-CLOSE |
| L-09 | request queued over a Pause, then a normal BVE exit: `Discarded(scenario-epoch)`, no claim, no API call, no residue | PASS |
| L-10 | TS Scoring turned OFF during a Pause: `Discarded(owner-lost)` 1.1 s after the send | PASS |
| L-11 | flag OFF behaviour (2A-alpha build 0.5.0.0, evidence reused): scoring start refused with `missing-jump`, nothing accepted | PASS |
| L-12 | Current regression with the acceptance DLL deployed: the Current jump path is normal | PASS |
| L-13 | Legacy / Current boundary: Directory, mapping and publisher_pid separated per PID, no overlap, no fixed-port fallback | PASS |
| L-14 | breaker N = 3: reset by a success, three failures in a row, exactly one `jump-breaker-open`, the next request discarded `breaker-open`, scoring start refused `missing-jump` | PASS |

**L-08 is not a plain real-machine PASS.** It was split by the owner (CONTRACT-SPLIT). L-08c - the real-machine joining of an application-driven request held through a Pause until the TTL, the Python
`jump-timeout` and `scoring-abort` on a real machine, the real process boundary, and the V2 visual check - is BLOCKED-ACCEPTED-RISK: the scoring start of the managed application sends a `P` key to BVE (it
releases the Pause), so the premise "Pause held" cannot be established by the application. It is neither a product failure nor inconclusive; it is an accepted residual risk. Release conditions: (1) the automatic
`P` of the scoring start is changed, (2) a formal entry that starts scoring while keeping the Pause, or (3) a verified real-machine fixture that blocks the first Legacy Tick without breaking the product contract.

**Judge history (kept, not rewritten).** L-09: the original judge (v2.2) said FAIL because it accepted only `Discarded(dispose)`; on a normal exit the scenario is closed before the extension is disposed, so the correct
terminal reason is `Discarded(scenario-epoch)`. The owner classed it as a tool false FAIL (product failure 0); Judge v2.3 accepts `scenario-epoch` or `dispose` and re-judged the saved case PASS; the original FAIL stays in the saved run.
L-01: the first judge (v1) said INVALID because of an unclassified short-lived Current process; later judges classify it as a known external Current-host crash transient (v2.1 PASS). L-11 was observed with the 2A-alpha build (flag OFF, 0.5.0.0) and judged by v1; it is adopted from the existing
evidence after a final re-judgement by Judge v2.3 (PASS), so the flag-OFF behaviour is proven live on 0.5.0.0 and offline (golden output) for the 0.6.0.0 default build. L-13: a first run was a procedure error (the real Current process was started about 2 s after the Legacy exit) and is not adopted.

**Known baselines (not product failures when the signature matches exactly):** the BveTs exit-time crash (`ntdll.dll` 0xc0000005, offset 0x60d99, about 0.4 s after the final telemetry line; it pre-dates the jump plane and did not occur in any adopted run),
and the Current-host `clr.dll` crash (0x80131506, offset 0x2b7e58) during the Current-to-Legacy switch (seen in L-01 and L-06; the Legacy side was unaffected). Any other signature, a crash before the shutdown, or a leftover worker / socket / mapping remains PRODUCT-SUSPECT.

**Deployment and defaults.** The Legacy DLL 0.6.0.0 acceptance build (SHA-256 A060272C...730F0) is the formally adopted LJX-1 acceptance artifact and stays deployed. Nothing here changes the feature-flag default (OFF in the committed state), merges the
two build configurations, or promotes the acceptance build to a general default; that is OD-X11 and belongs to a later phase.

**Still not done (deferred):** StationIndex as the source of truth, checkpoint / retry / Save, the pseudo turn-back, P to P, the stop-time impulse, the three remaining PID gaps, a product fix of the exit-time crash, the 2A-alpha document (its "not implemented" statement is stale), and the real-machine L-08c.
