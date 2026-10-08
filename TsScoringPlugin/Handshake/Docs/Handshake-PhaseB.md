# TS Scoring – Phase B handshake (independent ON/OFF foundation, version 0.4.1.0)

Not a release. Nothing here has been deployed automatically; BVE has never been started with it.
Human-facing product name: **TS Scoring**. Provider: **Coruge-to**.
(Technical identifiers keep the old internal spelling for Phase B: the DLL file names, namespaces, class names and the named kernel
objects `Local\TSScoringPlugin.v1.<PID>.*`. They are protocol/code identifiers, not product names.)

## Building (Windows PowerShell, Visual Studio MSBuild)
Run MSBuild <project>.csproj /t:Rebuild /p:Configuration=Release in Bridge\ and in Caller\, then copy Bridge\out\*.dll and Caller\out\*.dll into a new dist\ folder. The projects take BveEX from %PUBLIC%\Documents\BveEx\2.0\ and the BVE input-device interface from %ProgramW6432%\mackoy\BveTs6\ (read-only references, never copied or shipped). They are deliberately not part of the main solution. The DLL file names are a deployed contract and must not change.

## What is built
| Part | File (in `dist\`) | Where it goes |
|---|---|---|
| Input-device Caller | `TSScoringPlugin.Caller.InputDevice.dll` | `Input Devices` folder of BVE5 and/or BVE6 (administrator rights) |
| BveEX Bridge (minimal BveEX extension) | `TSScoringPlugin.BveEx.Bridge.Prototype.dll` | BveEX `Extensions` folder: `%PUBLIC%\Documents\BveEx\2.0\Extensions` |

The BVE list shows "TS Scoring Input Device Caller" (version 0.4.1.0, provider Coruge-to). No PDB, no BveEX/BVE DLLs are shipped.
Only `dist\` is a distribution candidate; `Caller\`, `Bridge\`, `Shared\`, `Tests\`, `Tools\` and `Docs\` are the source material (the folders `out\`, `obj\`, `dist\`, `logs\` are build products and are not committed).
No Python, HUD, scoring, UDP, hooks, files, registry, or BVE/BveEX settings are touched by either DLL.

## Four separate facts (only the first three exist in Phase B)
| Fact | Meaning | Created by |
|---|---|---|
| **Enabled** | the user switched TS Scoring ON in BVE's input-device settings | Caller |
| **BridgeAvailable** | BveEX loaded the Bridge; the Bridge exists in the BVE process (proves BveEX is installed, on and the Bridge DLL is present) | Bridge, when BveEX loads it |
| **Ready** | the Bridge recognised Enabled: the Caller<->Bridge handshake is up | Bridge, from Tick |
| ScenarioReady | the scenario is loaded and BVE data can be read safely (future; **not implemented**, Ready is not ScenarioReady) | future Bridge |
| (AppReady) | the scoring app runs and its link is up (future, Phase D) | future |

**Why**: BveEX calls an extension's `Tick` only *while a scenario is being driven* (BveEX public documentation). So Ready can legitimately be
missing for minutes (start-up, menus, scenario selection). **A missing Ready never means "BveEX is missing"; only a missing BridgeAvailable does.**

## Named objects (all per logon session, per BVE process ID)
- `Local\TSScoringPlugin.v1.<PID>.Enabled` – Caller: created and set on Load, withdrawn on Dispose.
- `Local\TSScoringPlugin.v1.<PID>.Stop` – Caller: created before Enabled, set on Dispose.
- `Local\TSScoringPlugin.v1.<PID>.BridgeAvailable` – Bridge: created and set when BveEX loads the Bridge (constructor, nothing else); reset and released on Bridge Dispose.
- `Local\TSScoringPlugin.v1.<PID>.Ready` – Bridge: created and set while Enabled is set and Stop is not.
- `Local\TSScoringPlugin.v1.<PID>.BridgeInfo` – fixed 128-byte memory-only block (version 3) with Bridge-side measurements.
  **Phase B measurement only, removal candidate after Phase B, not for production.** Missing, short, corrupt or old-version content only shows "BridgeInfo: Unavailable".

## Timing (single source of truth: `Shared\HandshakeProtocol.cs`, class `HandshakeTiming`)
- BridgeAvailable target: **500 ms** after the Caller was enabled (measured and shown in Configure, never an error).
- BveEX-dependency notice timeout: **500 ms** of BridgeAvailable being absent in a row (BVE6 field result: BridgeAvailable is normally seen after about 310-320 ms).
- Ready and ScenarioReady have **no** timeout and never trigger the BveEX notice.
- Caller monitor interval 20 ms (own background thread); Bridge check spacing 100 ms (from Tick). Nothing sleeps on BVE's or BveEX's thread.

## Caller states (one monitor thread for the whole enabled cycle)
`Disabled`, `WaitingForBridge`, `BridgeAvailable` (transient), `WaitingForHandshake`, `Connected`, `BridgeMissingTimedOut`, `Disposed`.
- Load -> WaitingForBridge. BridgeAvailable seen -> WaitingForHandshake; Ready seen -> Connected.
- Connected and Ready lost but BridgeAvailable still there -> WaitingForHandshake (no notice).
- BridgeAvailable lost (from any state) -> WaitingForBridge = a **new absence stretch**.
- Absent for 500 ms in a row -> BridgeMissingTimedOut and the notice **once** for that stretch.
- BridgeAvailable back -> WaitingForHandshake and the notice is re-armed (no notice at return).
- Dispose ends monitoring, publishes Stop, withdraws Enabled, releases everything; no notice afterwards.
- The dialog is shown from a separate short-lived thread, one at a time, and the conditions (not disposed, still TimedOut, BridgeAvailable still absent)
  are re-checked just before it is shown.

Notice text (title "TS Scoring"):

    TS ScoringにはBveEXが必要です。
    設定 → 入力デバイス でBveEXを有効にし、BVEを再起動してください。

The only explicit line break is between the two lines; the second line is one sentence and the standard Windows MessageBox is kept
(no custom dialog). Check on the real BVE that line 2 is not wrapped by the dialog.

## Configure dialog ("TS Scoring - handshake status")
Product, Provider, Phase, assembly file name, Caller Enabled/Disabled, Dependency state, BridgeAvailable Present/Missing, Ready Present/Missing,
Combined state (Waiting for Bridge / Bridge loaded, waiting for handshake / Connected / Bridge missing, timed out / Disposed),
ScenarioReady ("Not implemented in Phase B"), BVE PID and bitness, the four object names, Enabled-created time, BridgeAvailable first-seen / lost times,
Ready last-confirmed / lost times, time to BridgeAvailable (first / latest), latest handshake time, 500 ms target flag, 500 ms notice-timeout flag,
notice count, Bridge seen/lost and Ready connected/lost counts, and BridgeInfo (or "Unavailable"). File names only – no drive paths.

## Before deploying (manual, nothing is automatic)
1. Run `Tools\Verify-PhaseB.ps1` and `Tests\Test-HandshakeLogic.ps1` (read-only; the logic test uses fake process ids and never shows a dialog) and compare the SHA-256 values with the report.
2. Close BVE5/BVE6. Back up by COPYING (not moving): `BveTs6.Preferences.xml` (BVE6) and `Preferences.xml` (BVE5) from `%USERPROFILE%\Documents\BveTs\Settings`,
   and note the checked devices (screenshot of Settings > Input devices).
3. Remove the previous Phase B Caller/Bridge DLLs (same file names) before copying these. Close BVE first – a loaded DLL cannot be replaced.
4. The production-style `TsScoringPlugin.dll` in the BveEX Extensions folder keeps working next to the Bridge; for clean measurements you may temporarily set it aside yourself.
5. Copy the Caller into ONE BVE's Input Devices folder and the Bridge into the BveEX Extensions folder. Do not touch any other device or plugin.
6. In BVE: Settings > Input devices: "TS Scoring Input Device Caller". The property button opens the single status dialog.

## Manual test matrix (BVE6 x64 as B6-n, BVE5 x86 as B5-n)
Record per run: BVE PID, bit width, time to BridgeAvailable, Ready time, notice count, Configure text (states and counters), BridgeInfo state,
objects left after OFF and after exit, exceptions, warnings, effects on other devices.
| Test | Setup | Expected |
|---|---|---|
| B*-1 | start BVE with BveEX ON and TS Scoring ON (both already checked at start-up); stay in the scenario list | record the BridgeAvailable detection time and whether the 500 ms target was exceeded; **no notice** (none for a missing Ready while no scenario is loaded); Configure: "Bridge loaded, waiting for handshake"; after a scenario starts Ready is established (Connected) |
| B*-2 | BveEX ON, TS Scoring OFF | no Caller; BridgeAvailable may exist; no message; complete dormancy |
| B*-3 | BveEX OFF, TS Scoring ON | BridgeAvailable absent; about 500 ms later exactly one notice with the two-line text; not repeated in the same absence stretch; line 2 is NOT wrapped unnaturally by the dialog |
| B*-4 | Connected, then switch BveEX OFF | Ready and BridgeAvailable vanish; about 500 ms later exactly one notice, no duplicate in the same stretch; Configure "Bridge missing, timed out" |
| B*-5 | then switch BveEX ON again | BridgeAvailable back, Ready back (after Tick), Connected; no false notice |
| B*-6 | BridgeAvailable present, Ready absent (for example before any scenario ran); wait 2 s or more | no notice; Configure "Bridge loaded, waiting for handshake" |
| B*-7 | TS Scoring OFF | Caller disposed, Enabled released, Stop signalled, Ready withdrawn, no late notice |
| B*-8 | both OFF | nothing happens |
| B*-9 | BveEX ON, TS Scoring switched ON later (BveEX already loaded) | BridgeAvailable seen at once; Ready after a scenario runs |
| B*-10 | start a scenario, return to the title/scenario list, start another | Ready may vanish and return with Tick; **no notice at any point** while BridgeAvailable exists |
Optional later: two BVE instances at once (each PID has its own objects). Leftovers can be seen with a handle viewer (handle search `TSScoringPlugin.v1`), read-only.

## Cleanup
1. Close BVE. 2. Delete the Caller from the Input Devices folder(s) used (administrator rights) and the Bridge from the Extensions folder.
3. If BVE complains about a leftover entry (`tsscoringplugin.caller.inputdevice` in `<InputPlugins>`), restore the backed-up Preferences XML with BVE closed.
4. Put anything you set aside back.
