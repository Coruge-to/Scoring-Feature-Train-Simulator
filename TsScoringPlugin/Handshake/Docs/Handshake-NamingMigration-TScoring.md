# TScoring public naming migration

The user-facing product name is **TScoring** (formerly "TS Scoring"). Author / provider: Coruge-to.

## The five public DLLs

| Role | New file name (= AssemblyName) | Old file name | Placement |
|---|---|---|---|
| BVE input device (Caller, host independent) | `TScoring.InputDevice.dll` | `TSScoringPlugin.Caller.InputDevice.dll` | BVE 6 / BVE 5 `Input Devices` folder |
| Bridge, DLL suffix B (current extension path) | `TScoring.BridgeB.dll` | `TSScoringPlugin.BveEx.Bridge.Prototype.dll` | `...\BveEx\2.0\Extensions` |
| Telemetry, DLL suffix B (current extension path) | `TScoring.TelemetryB.dll` | `TsScoringPlugin.dll` | `...\BveEx\2.0\Extensions` |
| Bridge, DLL suffix A (legacy compatibility path) | `TScoring.BridgeA.dll` | `TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll` | `...\BveEx\Legacy\Extensions` |
| Telemetry, DLL suffix A (legacy compatibility path) | `TScoring.TelemetryA.dll` | `TSScoringPlugin.AtsExLegacy.Telemetry.dll` | `...\BveEx\Legacy\Extensions` |

Metadata of every DLL: AssemblyProduct `TScoring`, AssemblyTitle `TScoring Input Device` / `Bridge B` / `Telemetry B` / `Bridge A` / `Telemetry A`,
Company `Coruge-to`, one shared release version. The suffix letters A and B are not turnback pair A / B.

## What is NOT renamed (internal identifiers, kept on purpose)

Namespaces, class names, csproj / solution file names, protocol identifiers (`Local\TSScoringPlugin.v1.*` Events, mutexes, shared memory), UDP / JSON contracts,
the storage folder `%LOCALAPPDATA%\Coruge-to\TS Scoring`, `TS_SCORING_DESKTOP_LOG`, the initial-defaults identifiers, and the Git history.

## Notes for users and installers

- BVE stores the enabled state of an input device under a key derived from the DLL file name. After the rename BVE lists the new `TScoring.InputDevice.dll` as a new device that is
  OFF at first; the old key is left untouched. Switch TScoring ON once in the BVE input-device settings.
- `AtsEx.Caller.InputDevice.txt` belongs to the AtsEX Project and is never changed. `AtsEx\1.0\Extensions` is not a TScoring placement folder.
- A migration replaces the five old DLLs with the five new ones as ONE operation (old = 0, new = 1 per role, other products' DLLs untouched) and keeps a rollback copy outside the live folders.
