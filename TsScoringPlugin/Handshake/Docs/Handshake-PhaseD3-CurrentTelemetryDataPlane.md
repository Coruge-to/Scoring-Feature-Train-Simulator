# Phase PID-D3 - Current Telemetry on the per-PID DataPlane

Status: implemented, offline-tested, NOT deployed, NOT committed. Live acceptance (stages L-0, A, B, C) is pending.
Contract: PID-D0B-1 (Shared DataPlane Contract v1). The binary layouts, the AppDirectory ownership source, the shutdown order, the Current / Legacy
separation, the managed lifecycle, the parent-process watch and the final App Lock release are unchanged.

## What changed

Current sender (`TsScoringPlugin\CurrentDataPlane.cs`, Current project only; `Class1.cs` calls it):

| Mode | When | What is sent |
| --- | --- | --- |
| Undetermined | from the first send attempt until the hold-off (provisional 2000 ms) ends without `Enabled` / `Ready` | nothing |
| Managed | the existing per-PID control plane event `Enabled` OR `Ready` was observed once (latched for the life of the plugin) | Envelope v1 to the Directory-published loopback port of THIS BVE's managed application, only while the Directory is usable and advertises ENVELOPE_V1. Anything else = nothing is sent (fail closed). Never fixed 54321. |
| Normal | hold-off ended and neither was ever observed (a later sighting still upgrades to Managed; the reverse never happens) | the pre-migration plain UTF-8 text to the fixed legacy destination, byte for byte |

The Directory (AppDirectory / Telemetry Directory) is never used to choose the mode. One routing snapshot is taken per Tick / heartbeat, so a STALIST / META / Telemetry group
cannot be split across two endpoints. A STALIST / META that could not be sent stays pending.

`Class1.cs`: the constructor is split into independent blocks (diagnostics, sender, heartbeat, 54322 jump receiver); the 54322 port, protocol and jump handling are unchanged and a
bind failure only disables jump commands (one diagnostic line). `Dispose` is idempotent and safe after any partial initialisation.

Managed Python (`main.py`, `telemetry_dataplane_receiver.py`, `dataplane_contract.py`, `telemetry_receiver_directory.py`): the Directory advertises
ENVELOPE_V1 | LEGACY_TEXT_PAYLOAD (composed from named constants); a Caller-owned application (`--owner caller`) accepts ONLY Envelope v1 datagrams of its own BVE PID, AppInstance,
endpoint generation and token, for MessageType 1-4, and hands the unchanged UTF-8 payload to the existing STALIST / META / STATUS / Telemetry handling. Everything else is dropped and
counted (stable reasons, one line per reason, one summary at the end). Normal mode (`python main.py`) and non-Caller managed runs (`--owner test|manual-test`, test seams) keep the plain
fixed-port socket and are not changed.

## Overlay attribute classification (`managed_input.py`, `KEPT_ACROSS_GENERATIONS`)

Three names were added to the "infrastructure" group. They are kept across scenario generations; the edit changes no runtime behaviour (no product code reads the set; an unlisted name is
left untouched by `discard_generation_state`, i.e. also kept) and only completes the attribute classification contract (`managed_input.py` header comment, enforced by
`tests/test_managed_input_sia3.py`). Provenance, owner decision (a):

- `dataplane_receiver`, `dataplane_strict`: attributes NEW in PID-D3.
- `udp_port`: NOT a PID-D3 attribute. It was introduced by PID-D2 (commit 830b5a8) and left unclassified there; the gap was found during PID-D3 and is completed here. It is the
  generation-independent port of the Overlay's own socket used to publish the Telemetry Directory, so "kept" is its correct meaning. Record it as a PID-D2 residual fix.

## Known constraints (owner decisions)

- (Closed by Phase PID-D6, see Handshake-PhaseD6-JumpCompleteRequestId.md: the managed JUMP_COMPLETE now travels with a RequestId.) JUMP_COMPLETE is NOT part of this slice (DEC-2). In managed mode the completion notice is not transmitted and the managed application does not receive it; the official-jump /
  checkpoint-resume handshake is therefore still unavailable in managed mode (as since PID-D2) until PID-D6 adds the RequestId. Port 54322, the jump commands and the retry flow are unchanged.
- Out of scope for this beta: Caller active + invalid / missing launcher.json + a hand-started `main.py` listening on 54321. It is treated as managed (fail closed); no fallback and no new
  mode marker keeps it alive.
- The Legacy sender still sends plain text to the fixed legacy port. A Legacy -> managed live chain does not exist until PID-D4 (`Test-TelemetryIntegrationL3.ps1` reports it as SKIP).
- The hold-off value is provisional; live item L-0 measures first Tick, Enabled, Ready, app start and Directory PUBLISHED / READY and decides the final value.

## Diagnostics

Current: `%USERPROFILE%\Downloads\TSScoring-CurrentTelemetry-P<BVE PID>.log` (own file per BVE process, bounded to 400 lines): first-evaluate, enabled-seen, ready-seen (offsets in ms),
mode, endpoint-adopted / endpoint-changed (port, generation, change count, 8-hex instance prefix), disconnected (reason, once per change), send-failed (once per episode), payload-too-large (once),
jump-complete-excluded (once), summary at Dispose. No token, no payload text.
Python: `[DATAPLANE] event=first-accept|reject|summary` on the managed stderr (first reject per reason, one summary).

## Tests

- `Tests\Test-CurrentDataPlaneD3.ps1` (+ `CurrentDataPlaneTestFixture.cs`): 73 compiled checks (mode latch, fail closed, envelope content, capabilities, rediscovery, oversize, JUMP_COMPLETE, lifecycle,
  parity, the shared reader against real named mappings, diagnostics file) + 15 static checks. `-GoldenRoot <folder>` also writes C# -> Python interop datagrams.
- `tests\test_telemetry_dataplane_receiver_d3.py`, `tests\test_current_dataplane_d3_interop.py` (set `CURRENT_DATAPLANE_D3_GOLDEN`), `tests\test_managed_dataplane_chain_d3.py` (real `main.py`).
- Migrated live chains (managed success path = Directory port + Envelope v1): `Test-HudLinkE4.ps1` I-section, `Test-AppProcessE3.ps1` I10-I11, `tests\test_parent_exit_p1.py` (Caller-owned half).
  Helpers: `Tests\DataPlaneFeedFixture.cs`, `tests\dataplane_feed.py`.
