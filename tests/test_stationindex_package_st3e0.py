"""Phase PID-D4JA StationIndex ST-3e0 - the CONTRACT tests of the package: the TSJUMP2 tag, the source sets, the deterministic source package manifest, the N-12 package guard and
the return of U13 to a GUARD. Python only; the repository files are only READ; nothing here compiles, builds, starts a process (git is never started: the blob id is computed here) or opens a
socket. The one test that writes (E0-26) writes a copy of the sources into a temporary folder and removes it. The behaviour of the product is not touched: ST-3e0 adds a package
contract and a guard, never product logic.

What ST-3e0 IS (recovered from the canon: ST-3d Push Close 05 / 08, ST-3 Start Audit 12, U10 Push Close 07 and the owner's instruction of this stage)
  * TSJUMP2 is ONE capability bundle: a tag with the wire versions it stands for. It has ONE definition per language (package_contract.py; Shared/PackageContract.cs compiled by BOTH
    the Current and the Legacy project) and is kept out of the codec (JumpWire.cs / jump_wire.py are not touched).
  * The Git-managed source package manifest (package/source-package-manifest.json) names the runtime source of the package (Python import closure of main.py, Current, Legacy, Shared)
    by the SHA-256 of the Git BLOB, with a fingerprint of those entries. It has no timestamp, no absolute path, no DLL SHA, no future commit; build status = not-built,
    deployment status = not-deployed. It is not an entry of itself.
  * N-12 (package/source_package.py, TsScoringPlugin/Handshake/Tests/Test-PackageGuardST3.ps1) accepts the one official combination and rejects every other (fail-closed).
  * U13 returns from a declared RED to a GUARD whose meaning is "code and package consistency", not a build, a deployment or a live acceptance.

Each RED fails with ContractViolation whose .code is the declared one against the tree of 0b8e511 (the preconditions are plain assertions that come first, so a moved source is
RED-INVALID and never a RED) and passes against the tree of this phase. A GUARD passes before and after.
"""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
TOOL_PATH = os.path.join(ROOT, "package", "source_package.py")
MANIFEST_FILE = os.path.join(ROOT, "package", "source-package-manifest.json")
WRAPPER = os.path.join(PLUGIN, "Handshake", "Tests", "Test-PackageGuardST3.ps1")
PY_CONTRACT = os.path.join(ROOT, "package_contract.py")
CS_CONTRACT = os.path.join(PLUGIN, "Handshake", "Telemetry", "Shared", "PackageContract.cs")
CURRENT_PROJECT = "TsScoringPlugin/TsScoringPlugin/TsScoringPlugin.csproj"
LEGACY_PROJECT = "TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.csproj"
SHARED_DIR = "TsScoringPlugin/Handshake/Telemetry/Shared"
BASE_COMMIT = "0b8e51137af2bf3c888dc77182981a89bf64090a"
BRANCH = "refactor/state-transitions"
TAG = "TSJUMP2"
THIS_FILE = "tests/test_stationindex_package_st3e0.py"
SET_RANK = {"python": 0, "current": 1, "legacy": 2, "shared": 3}

REQUIRED_PYTHON = ("main.py", "scoring_logic.py", "managed_input.py", "station_identity.py", "jump_wire.py", "jump_transaction.py")
# SI-R2.2-S2a added official_target_contract.py (the receiver of the OFFTGT part, imported by main.py): the closure is the 22 modules of 0b8e511 plus this one (plus package_contract)
# SI-R2.3 (C4b) added hud_target_contract.py (the display target of the HUD, imported by main.py): the closure is those 23 modules plus this one (plus package_contract)
PYTHON_24 = ("config", "current_jump_client", "dataplane_contract", "hud_target_contract", "hud_ui", "jump_transaction", "jump_wire", "main", "managed_app_directory", "managed_hud", "managed_input",
             "managed_mode", "managed_state", "menu_ui", "official_target_contract", "pause_recovery", "pseudo_turnback_machine", "scoring_logic", "station_identity", "station_index_contract", "telemetry_contract",
             "telemetry_dataplane_receiver", "telemetry_gate", "telemetry_receiver_directory", "utils")
CAPABILITIES = ("jump-request-v2", "jump-completion-v2", "current-selected-idx", "legacy-selected-idx", "python-completion-settlement", "stationindex-transaction",
                "target-reinitialization", "retry-history-settlement", "legacy-r1b", "current-station-range-fail-closed", "whole-list-reject", "partial-list-not-published")

# the git blob ids of commit 0b8e511 of every runtime source that ST-3e0 must not change (main.py and the two projects are handled apart: one line is added to each)
BASE_BLOBS = {
    "config.py": "9572d1b70bfd13459665f07b6c0c30205f9aec8e",
    "current_jump_client.py": "bfcee44c0a0f79a76a8a6e950c738084523f1cf9",
    "dataplane_contract.py": "56da8579207ae7f6d866f17ce4aafe6d0553c23f",
    # SI-R2.3 (C4b) changed hud_ui.py on purpose (the distance row, the time-left row and the timing label read the display target of the main.py sync - hud_target_* - and no longer the machine target; tests/test_hud_target_wiring_r23.py): the blob moved from a581b87c... (0b8e511)
    "hud_ui.py": "15ebccbbd2aed44fe36047998551aa5b548b307e",
    "jump_transaction.py": "81996db3fa243cc0bc5412142c6035f8a6fb9648",
    "jump_wire.py": "00579f8031221333f2f6e471d7e30ab3f8b1a365",
    "managed_app_directory.py": "77bf8671ef364b05fb6a6524858ce2ffc2930060",
    # UI-ALT-F4 changed managed_hud.py on purpose (the Overlay's input ownership for the operation screens, the one close request to BVE for a close the user asked for, the shown flag re-aligned with the real Overlay, tests/test_managed_hud_input_ownership.py / tests/test_overlay_user_close_altf4.py / tests/test_managed_hud_shown_reconcile.py): the blob moved from 38a2e4b9... (0b8e511); the package manifest is regenerated for it
    # Legacy scoring LC-4b (A15) changed managed_hud.py on purpose (+3 lines: the HUD tick polls the Jump availability of the Overlay, tests/test_lc4b_python_jump_state.py; the P18 lines of the pin ledger): the blob moved from b8f04304... (UI-ALT-F4)
    "managed_hud.py": "9d5d604d2b02cd153745d28b87f2d25056e66552",
    # Time Fix B changed managed_input.py (one name added to GENERATION_DROP) and scoring_logic.py (the operational stop keeps its arrival range, tests/test_timefix_b_operational_stop_margin.py) on purpose: the blobs moved from 73aff45b... / 140d8471... (0b8e511); the package manifest is regenerated for them
    # Time Fix B2 changed managed_input.py (one more name in GENERATION_DROP) and scoring_logic.py (the operational stop is latched at its stop and completed by that record, tests/test_timefix_b2_operational_stop_contract.py): the blobs moved from 293b4a21... / 5be7a006... (Time Fix B)
    # UI-Q1-B changed managed_input.py on purpose (the Qt translation of the locale is installed for the result save dialog, the file filters are named in Japanese, tests/test_ui_q1b_result_dialog_localization.py): the blob moved from 7933e16d... (Time Fix B2)
    # Close-range departure reset added the two generation defaults (close_range_departure_reset_pending, prev_actual_stop_loc) to managed_input.py on purpose (tests/test_close_range_contract.py): the blob moved from 6b0bda0b... (UI-Q1-B)
    # Pseudo-turnback (Stage TB-B) added turnback_machine to GENERATION_DROP in managed_input.py on purpose (the chain machine of the Overlay is dropped with the generation; tests/test_pt_scoring_continuity.py): the blob moved from 3ca69888... (SI-R5.2-C)
    "managed_input.py": "580b651b9ef65e6bab2a0bec4c746c028daf5a1b",       # SI-R5.2-C: the generation default prev_tgt_idx and its clear in discard_scoring_session (was e1b79288... after the close-range departure reset)
    "managed_mode.py": "60413e37938808b1f15c52c3b81db9353fd7a84a",
    "managed_state.py": "d8b75db1e870f3f01f825961ec37e7471244d2bc",
    "menu_ui.py": "412e722fb533e1627fa9c4a348e242144c6866df",
    "pause_recovery.py": "6c01fd0ebe2ca6fae3c501129381046b5e645a95",
    # Time Fix B3 changed scoring_logic.py on purpose (the speed limit guidance gate is speed != 0.0; the operational stop is neither formed nor completed on the telemetry of an outstanding official jump and leaves no record at the scoring finish, tests/test_timefix_b3_zero_speed_contract.py): the blob moved from db5145a0... (Time Fix B2)
    # Close-range departure reset changed scoring_logic.py on purpose (the previous actual stop position and the pending state, the departure reset of the early-stop and basic-braking state, the waiting gate, tests/test_close_range_contract.py): the blob moved from e8d1a3d0... (Time Fix B3)
    # SI-R5.2-A changed scoring_logic.py on purpose (P03, the HUD next station / rule section, takes the scoring target index bve_tgt_idx instead of the 1 m lookup at NEXTLOC; tests/test_si_r5_2a_stage_a.py / tests/red_si_r5_station_identity.py): the blob moved from 449e0c94... (Close-range departure reset)
    # Legacy scoring LC-3A (c12339a, the stop jerk state is reset at a Jump boundary and not judged while a Jump is outstanding), LC-3B (5aad2f1, a repeated clock time replaces the last g_history entry), LC-4 (0957634, execute_retry refuses after the scoring finished)
    # and LC-4b (cbebfd3, A14: execute_retry refuses while the Jump group is unavailable) changed scoring_logic.py on purpose (tests/test_lc3a_stop_jerk_boundary.py / tests/test_lc3b_clock_freeze.py / tests/test_lc4_retry_after_finish.py / tests/test_lc4b_python_jump_state.py): the blob moved from 88f61d75... (SI-R5.2-C)
    # Close-range entry paths (fix O1) added scoring_logic.close_range_fix_landing_stop on purpose (+17: the anchor of the close-range departure protection for a train PLACED at B by an official Jump; tests/test_close_range_entry_paths.py): the blob moved from 78e53ad3... (LC-4b)
    # Pseudo-turnback (Stage TB-B) added the A-side seam to scoring_logic.py on purpose (+126: the PairSet qualification at the arrival, the A time score once, no checkpoint for the A of a pair, the 3.0 s special popup window and the guidance, the B checkpoint; the module pseudo_turnback_machine joins the runtime set; tests/test_pt_display_contract.py / test_pt_scoring_continuity.py / test_pt_static_pins.py): the blob moved from debb31c8... (close-range entry paths)
    "scoring_logic.py": "bd54fc8bbea510b9fc669decd1ad6bb33aee899c",       # was debb31c8... after the close-range entry paths; 78e53ad3... after the LC-4b state; after the LC-4b state; 88f61d75... after SI-R5.2-C: P02 takes prev_tgt_idx, the last distance lookup is gone (9c683795... after SI-R5.2-B: P01, P04, P05 take bve_tgt_idx; c4981e27... after SI-R5.2-A)
    # SI-R5.2-A changed station_identity.py on purpose (the pure missing-index classifier, the run tracker and the managed diagnostic glue; tests/test_si_r5_2a_stage_a.py): the blob moved from 93ce7abc... (ST-3b)
    "station_identity.py": "2c971098059a6b8948cd842ed84af8ece9a054b9",
    "station_index_contract.py": "73c9ec9a75ca6dca450637f47d15d0ebdbdda423",
    # SI-R2.2-S2a changed telemetry_contract.py on purpose (OFFTGT is a token of the station group; telemetry_state_defaults() carries the six published values of the OFFTGT part, tests/test_official_target_supply_s2a.py): the blob moved from 6eab0e7e... (0b8e511)
    "telemetry_contract.py": "0cc2ef6a9e412e189ab34c84f435c59bdca061e4",
    "telemetry_dataplane_receiver.py": "87240b408cef4e70d3d31fccbc63292cb5f03ace",
    "telemetry_gate.py": "2e0c8b70041a1e9339c2fdf116edb7e57fce8219",
    "telemetry_receiver_directory.py": "5219d2940ca8b714fb999cae51341fc3881067d1",
    "utils.py": "4605f16133442d0e5542281190ace8f32de67a9b",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/AssemblyInfo.cs": "d601dec6a3a0feff0e7e6ed54c610ecb0d53bd51",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs": "890208dd6a69d9e2b1fd2f3a8a4d3a4907f0bbb7",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyDataPlaneSink.cs": "f5e11a9579ea5ba12544b9f00c0a48693f638819",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyGroundLimits.cs": "b6cf818399ca8ed83499f2cbf1f40669b40c487f",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyHandleContract.cs": "86596694a6dfd14124acc61514f8f70ff018dca9",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputProbe.cs": "30b23a457376cfd67c4bdd1ea98ddb863e1b438c",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputTelemetry.cs": "dd128ed0fe90bcd4082602cf291e5c9f60294ed7",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpCommandQueue.cs": "c9517db9074f45ef447991cd52280ef512047070",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpControlPlane.cs": "04d3104d1005fca4a8fe4a9c3da835bd79d61309",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpEndpoint.cs": "eb3a0233d799e8abbeea47e7d01b46034ee68584",
    # Legacy scoring LC-4 (89b234a, C-LJ-1: the completion payload is bound to the claimed request; C-LJ-2: a failure after the jump moved carries a note without an adopted station) changed LegacyJumpExecutor.cs on purpose (Handshake\Tests\LegacyJumpLcTestCases.cs / Test-LegacyJumpLC1b.ps1): the blob moved from b9575414... (ST-3c)
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpExecutor.cs": "40caa2f24ea1c2ddf21af65112babdce6ba9b768",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyScoringProbe.cs": "1f0be23bc1c911e4bf83933a22016613834c2f48",
    # Time Fix A changed LegacyStationTimeline.cs and Class1.cs on purpose (the arrival fill-in, tests/test_timefix_a_terminal_arrival.py): the blobs moved from 1bae94a1... / a9b420a0... (0b8e511); the package manifest is regenerated for them
    # Time Fix B2 changed LegacyStationTimeline.cs on purpose (the same branch, tests\test_timefix_b2_operational_stop_contract.py / Handshake\Tests\Test-TimeFixB2.ps1): the blob moved from 4bb9c312... (Time Fix A)
    # Time Fix B3 changed LegacyStationTimeline.cs on purpose (the same two comparisons, tests\test_timefix_b3_zero_speed_contract.py / Handshake\Tests\Test-TimeFixB3.ps1): the blob moved from 4554795a... (Time Fix B2)
    # SI-R2.4 (C5b) changed LegacyStationTimeline.cs on purpose (SelectTarget: the loop of the position search is gone, a re-initialisation that carries no StationIndex leaves target = list.Count; Handshake\Tests\LegacyJumpST3CTestCases.cs N-35 / N-63 / Handshake\Tests\Test-TimeFixB3.ps1): the blob moved from d33ecdba... (Time Fix B3)
"TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs": "83db89f99a32cd8f2df52c585000d79c7bdccbd0",
    # SI-R2.2-S2b (C3a) changed LegacyTelemetryExtension.cs on purpose (the read only adapter ILegacyOfficialTargetApi.ReadOfficialTarget and the E-9 rule text of the header; tests/test_official_target_wire_s2b.py / Handshake\Tests\Test-OfficialTargetWireS2B.ps1): the blob moved from 12a0f84a... (the commit before S2b)
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs": "ad89eb30b5b4f16fb36bef4824adbd734565bd7b",
    # SI-R2.2-S2b (C3a) changed LegacyTelemetrySession.cs on purpose (the ILegacyOfficialTargetApi port, the official field, the ten-argument constructor and the OFFTGT key after STIDX; tests/test_official_target_wire_s2b.py / Handshake\Tests\Test-OfficialTargetWireS2B.ps1): the blob moved from 5dd33902... (the commit before S2b)
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs": "c5bc298a7b4cc901f6fe5aa64492082e16071b1f",
    "TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs": "bed2ed8585b502578d4d4e17f64307206d0920fc",
    "TsScoringPlugin/Handshake/Telemetry/Shared/GenericHandleTextContract.cs": "94746abf0d4395b0ddbfa351df3adadb1aa70132",
    "TsScoringPlugin/Handshake/Telemetry/Shared/JumpWire.cs": "dff2a85a25ff22f76892b3d19209b1da9c089387",
    # SI-R2.2-S2b (C3a) changed StationListIdentity.cs on purpose (the official next-station target: OfficialTargetReading / Station / Host / Reader / Wire, the shared reader core and wire helper of both senders; tests/test_official_target_wire_s2b.py / Handshake\Tests\Test-OfficialTargetWireS2B.ps1): the blob moved from bfa15b21... (the commit before S2b)
    "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs": "b670065e031b77fe2fa2c820548a04bdc020f1ea",
    "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs": "c7be611e9b1d704a17014b9294a532cf82abc0b9",
    "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs": "cde81d8f5411df680cb17b10288a3c8d9b01f561",
    "TsScoringPlugin/TsScoringPlugin/AtsLoggerPlugin.cs": "22209df3e50762dd17c68c9bb788af6f8faf98b7",
    # Time Fix B2 changed Class1.cs on purpose (the operational stop leaves the target at once when the vehicle leaves, tests\test_timefix_b2_operational_stop_contract.py / Handshake\Tests\Test-TimeFixB2.ps1): the blob moved from b703adb0... (Time Fix A)
    # Time Fix B3 changed Class1.cs on purpose (BVE supplies exactly 0.0 while the train stands: speed == 0.0 is stopped, speed != 0.0 is moving; the 0.1 km/h band is gone, tests\test_timefix_b3_zero_speed_contract.py / Handshake\Tests\Test-TimeFixB3.ps1): the blob moved from 04a12011... (Time Fix B2)
    # SI-R2.2-S2b (C3b) changed Class1.cs on purpose (the OFFTGT part after STIDX in its own try / catch and the read only CreateOfficialTargetHost; tests/test_official_target_wire_s2b.py / Handshake\Tests\Test-OfficialTargetWireS2B.ps1): the blob moved from 4aa4aac5... (the commit before S2b)
    # SI-R2.4 (C5b) changed Class1.cs on purpose (a re-initialisation that carries no StationIndex leaves the target UNSET: SelectTargetByPosition became SelectUnsetTarget and its one call site, no position is searched; tests/test_stationindex_current_st3b.py / tests/test_jf1_current_csharp_source_pins.py / Handshake\Tests\Test-TimeFixB3.ps1): the blob moved from e3f55d15... (SI-R2.2-S2b C3b)
    "TsScoringPlugin/TsScoringPlugin/Class1.cs": "afc404e7898248dc2e3680ba4dca19cd89730ad6",
    "TsScoringPlugin/TsScoringPlugin/CurrentDataPlane.cs": "71b0ebaa6f52871ceb2a59456a2b527041241c46",
    "TsScoringPlugin/TsScoringPlugin/CurrentJumpEndpoint.cs": "3e0d3bffbb74e4a2ecc6d10d378a8b6e2788ae6f",
    "TsScoringPlugin/TsScoringPlugin/CurrentJumpExecution.cs": "8a54d6a14100e0021ca248d28369c335f965fafe",
    "TsScoringPlugin/TsScoringPlugin/Properties/AssemblyInfo.cs": "e704abd24867f658d3a0391e231395dff85ad5d2",
}
# Time Fix B3 changed main.py on purpose (the F8 hook and the fast-forward release test speed != 0.0 instead of >= 0.1 km/h / abs >= 0.1; a new scenario in the plain mode leaves no operational stop record): the blob (without its contract import)
# moved from f2031b37... (Time Fix B2; main.py had been unchanged since 0b8e511 apart from the contract import)
# UI-ALT-F4 changed main.py on purpose (Overlay.closeEvent / set_input_ownership / has_input_ownership / bring_to_foreground / post_close_to_bve, the "in front" of the managed step follows the Overlay, the wiring of the user close handler and the stop probe, the shutdown disarms the handler; tests/test_overlay_user_close_altf4.py / tests/test_managed_hud_input_ownership.py): the blob (without its contract import) moved from af943ef0... (Time Fix B3)
# SI-R2.2-S2a changed main.py on purpose (the OFFTGT intake: the import of the receiver module, the six published values and their private judgement state, the capture of the part outside the key loop and the judgement at three moments; tests/test_official_target_supply_s2a.py): the blob (without its contract import) moved from bd8c31c9... (UI-ALT-F4)
# SI-R2.3 (C4b) changed main.py on purpose (the display target: the import of hud_target_contract, the read-only hud_target_* views, the display state _hud_target / _hud_freeze, the sync after every judged line and before the HUD is drawn; tests/test_hud_target_wiring_r23.py): the blob (without its contract import) moved from 5da4fb7f... (SI-R2.2-S2a)
# Close-range departure reset changed main.py on purpose (the two construction defaults close_range_departure_reset_pending / prev_actual_stop_loc; tests/test_close_range_contract.py): the blob (without its contract import) moved from 86e6929a... (SI-R2.3 C4b)
# SI-R5.2-C changed main.py on purpose (the construction default prev_tgt_idx = -1 beside prev_next_loc; tests/red_si_r5_station_identity.py): the blob (without its contract import) moved from 2a0b103b... (Close-range departure reset)
# Legacy scoring LC-4b (cbebfd3) changed main.py on purpose (A14: Overlay.jump_group_available, the Retry menu entry refuses while the Jump group is unavailable; A16: the baseline block of apply_telemetry_text looks at the JUMP key; tests/test_lc4b_python_jump_state.py): the blob (without its contract import) moved from 07043c51... (SI-R5.2-C)
# Close-range entry paths (fix O1) changed main.py on purpose (+4: the import of scoring_logic.close_range_fix_landing_stop and its one call in the success branch of Overlay._settle_jump_complete; tests/test_close_range_entry_paths.py): the blob (without its contract import) moved from c8be5715... (LC-4b)
BASE_MAIN = "8d613d1bf5ca8655229712d6cbada7f5f99aa5ad"       # Stage TB-C changed main.py on purpose (the scoring start button fixes the section, the end-of-transaction record, the F1 hold, OD-TB-30 no popup); was da5d5b2c...
BASE_PROJECTS = {CURRENT_PROJECT: "61092229f34e5e4ceb52a4fb6e52280824ec2578", LEGACY_PROJECT: "defbe148ff815741c6b627cadaf8d024f649f804"}
CODEC_FILES = ("jump_wire.py", "station_index_contract.py", "dataplane_contract.py", "telemetry_contract.py", "station_identity.py",
               SHARED_DIR + "/JumpWire.cs", SHARED_DIR + "/StationListIdentity.cs", SHARED_DIR + "/DataPlaneProtocol.cs", SHARED_DIR + "/TelemetryDirectoryReader.cs",
               SHARED_DIR + "/GenericHandleTextContract.cs", SHARED_DIR + "/TelemetryContract.cs")


class ContractViolation(AssertionError):
    """The tree does not meet the contract; `code` names the violated clause (a RED run compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("E0-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def e0(tid, kind, code="", note=""):
    """Declare a test of ST-3e0: its id, its kind ("RED": fails against 0b8e511 with `code`; "GUARD": green before and after) and one line."""
    assert kind in ("RED", "GUARD"), kind

    def deco(fn):
        fn.e0 = {"id": tid, "kind": kind, "code": code, "note": note}
        return fn
    return deco


def contract(ok, tid, code, detail=""):
    if not ok:
        raise ContractViolation(tid, code, detail)


# ---- plain readers and the independent reference computations (the tool is checked against these, never against itself) ----------------------------------------------------

def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_text(path):
    return read_bytes(path).decode("utf-8-sig")


def clean(data):
    """What the Git clean filter (core.autocrlf) stores: CRLF -> LF, unless the bytes are binary or hold a lone CR."""
    if b"\x00" in data or re.search(rb"\r(?!\n)", data):
        return data
    return data.replace(b"\r\n", b"\n")


def blob_id(data):
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def sha256_upper(data):
    return hashlib.sha256(data).hexdigest().upper()


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def ref_closure(files):
    """The static import closure of main.py over the root modules (independent of the tool). Returns (sorted names, dynamic import count)."""
    import ast
    mods = {n[:-3] for n in files if "/" not in n and n.endswith(".py")}
    seen, dyn = set(), 0
    stack = ["main"]
    while stack:
        m = stack.pop()
        if m in seen or m not in mods:
            continue
        seen.add(m)
        tree = ast.parse(files[m + ".py"])
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                stack.extend(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                stack.append(n.module.split(".")[0])
            elif isinstance(n, ast.Call):
                f = n.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
                if name in ("__import__", "import_module"):
                    dyn += 1
    return sorted(seen), dyn


def ref_compile(project_rel, text):
    """The Compile Include items of a project, resolved to repository relative paths (regular expression, like the audit of the U10 Push Close)."""
    base = os.path.dirname(project_rel)
    out = []
    for m in re.finditer(r'<Compile Include="([^"]+)"', text):
        out.append(os.path.normpath(os.path.join(base, m.group(1).replace("\\", "/"))).replace("\\", "/"))
    return out


def ref_fingerprint(m):
    lines = ["ts-source-package-fingerprint/1", "contract_tag\t" + m["contract_tag"], "request_wire_version\t%d" % m["request_wire_version"],
             "completion_wire_version\t%d" % m["completion_wire_version"], "stationindex_wire_version\t%d" % m["stationindex_wire_version"],
             "capabilities\t" + ",".join(m["capabilities"])]
    for e in sorted(m["files"], key=lambda e: (SET_RANK[e["set"]], e["path"].encode("utf-8"))):
        lines.append("%s\t%s\t%s" % (e["set"], e["path"], e["blob_sha256"]))
    return sha256_upper("\n".join(lines).encode("utf-8"))


def load_tool():
    """The package tool, loaded by path (it is not on any import path), or None while it does not exist."""
    if not os.path.isfile(TOOL_PATH):
        return None
    spec = importlib.util.spec_from_file_location("source_package_under_test", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["source_package_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def require_tool(tid, code):
    tool = load_tool()
    contract(tool is not None, tid, code, "package/source_package.py does not exist")
    return tool


_BASE_FILES = {}


def base_files():
    """Every file the package looks at, as the repository holds it (the bytes of the work tree): the root python modules and the sources of the three C# folders."""
    if _BASE_FILES:
        return _BASE_FILES
    for name in sorted(os.listdir(ROOT)):
        if name.endswith(".py") and os.path.isfile(os.path.join(ROOT, name)):
            _BASE_FILES[name] = read_bytes(os.path.join(ROOT, name))
    for folder in ("TsScoringPlugin/TsScoringPlugin", SHARED_DIR, "TsScoringPlugin/Handshake/Telemetry/Legacy"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, folder.replace("/", os.sep))):
            dirnames[:] = [d for d in dirnames if d.lower() not in ("bin", "obj", "packages")]
            for fn in filenames:
                if fn.endswith((".cs", ".csproj")):
                    p = os.path.join(dirpath, fn)
                    _BASE_FILES[rel(p)] = read_bytes(p)
    return _BASE_FILES


# ---- A: TSJUMP2 -----------------------------------------------------------------------------------------------------------------------------------------------------------------

def py_constants():
    """The constants of package_contract.py read as a syntax tree (never imported); None while the file is missing."""
    import ast
    if not os.path.isfile(PY_CONTRACT):
        return None
    tree = ast.parse(read_bytes(PY_CONTRACT))
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            out[n.targets[0].id] = ast.literal_eval(n.value)
    return out


def cs_constants():
    """The constants of Shared/PackageContract.cs; None while the file is missing."""
    if not os.path.isfile(CS_CONTRACT):
        return None
    text = read_text(CS_CONTRACT)
    out = {}
    for m in re.finditer(r'internal const string (\w+) = "([^"]*)";', text):
        out[m.group(1)] = m.group(2)
    for m in re.finditer(r"internal const int (\w+) = (-?\d+);", text):
        out[m.group(1)] = int(m.group(2))
    return out


class A_Tsjump2(unittest.TestCase):
    @e0("E0-01", "RED", "TSJUMP2-PYTHON-ABSENT", "package_contract.py exists, holds TSJUMP2 and the bundle as plain constants, imports nothing, does no I/O")
    def test_RED_E0_01_the_python_package_contract_is_constants_only(self):
        import ast
        contract(os.path.isfile(PY_CONTRACT), "E0-01", "TSJUMP2-PYTHON-ABSENT", "package_contract.py does not exist")
        consts = py_constants()
        contract(consts.get("CONTRACT_TAG") == TAG, "E0-01", "TSJUMP2-PYTHON-ABSENT", "CONTRACT_TAG is %r" % consts.get("CONTRACT_TAG"))
        self.assertEqual((consts.get("REQUEST_WIRE_VERSION"), consts.get("COMPLETION_WIRE_VERSION"), consts.get("STATIONINDEX_WIRE_VERSION")), (2, 2, 1))
        self.assertEqual(tuple(consts.get("CAPABILITIES")), CAPABILITIES)
        self.assertEqual(set(consts), {"CONTRACT_TAG", "REQUEST_WIRE_VERSION", "COMPLETION_WIRE_VERSION", "STATIONINDEX_WIRE_VERSION", "CAPABILITIES"}, "no other name: a bundle, not a set of switches")
        tree = ast.parse(read_bytes(PY_CONTRACT))
        for n in tree.body:
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                continue                                                                            # the docstring
            self.assertIsInstance(n, ast.Assign, "only constant assignments (no import, no function, no class, no statement)")
        forbidden = [type(n).__name__ for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom, ast.Call, ast.FunctionDef, ast.ClassDef, ast.With, ast.Global))]
        self.assertEqual(forbidden, [], "no import, no call, no function, no class: no side effect, no I/O")
        self.assertNotIn(b"open(", read_bytes(PY_CONTRACT))

    @e0("E0-02", "RED", "TSJUMP2-CURRENT-NOT-COMPILED", "the Current project compiles Shared\\PackageContract.cs once, with a unique link; the C# file holds only constants")
    def test_RED_E0_02_the_current_project_compiles_the_contract(self):
        contract(os.path.isfile(CS_CONTRACT), "E0-02", "TSJUMP2-CURRENT-NOT-COMPILED", "Shared/PackageContract.cs does not exist")
        proj = read_text(os.path.join(ROOT, CURRENT_PROJECT.replace("/", os.sep)))
        hits = re.findall(r'<Compile Include="\.\.\\Handshake\\Telemetry\\Shared\\PackageContract\.cs"><Link>Shared\\PackageContract\.cs</Link></Compile>', proj)
        contract(len(hits) == 1, "E0-02", "TSJUMP2-CURRENT-NOT-COMPILED", "the Current project has %d compile items of PackageContract.cs" % len(hits))
        links = re.findall(r"<Link>([^<]+)</Link>", proj)
        self.assertEqual(len(links), len(set(links)), "the link paths of the Current project are unique")
        text = read_text(CS_CONTRACT)
        self.assertIn("namespace TSScoringPlugin.Package", text)
        self.assertEqual(len(re.findall(r"\bclass\b", text)), 1)
        code = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
        self.assertIsNone(re.search(r"\busing\b|\bnew\b|\bThread\b|\bSocket\b|\bFile\b|\bProcess\b|\bstatic readonly\b|\(", code), "constants only: no using, no call, no I/O, no thread, no process")

    @e0("E0-03", "RED", "TSJUMP2-LEGACY-NOT-COMPILED", "the Legacy project compiles the SAME file once, with a unique link")
    def test_RED_E0_03_the_legacy_project_compiles_the_same_contract(self):
        contract(os.path.isfile(CS_CONTRACT), "E0-03", "TSJUMP2-LEGACY-NOT-COMPILED", "Shared/PackageContract.cs does not exist")
        proj = read_text(os.path.join(ROOT, LEGACY_PROJECT.replace("/", os.sep)))
        hits = re.findall(r'<Compile Include="\.\.\\Shared\\PackageContract\.cs">\s*<Link>Shared\\PackageContract\.cs</Link>\s*</Compile>', proj)
        contract(len(hits) == 1, "E0-03", "TSJUMP2-LEGACY-NOT-COMPILED", "the Legacy project has %d compile items of PackageContract.cs" % len(hits))
        links = re.findall(r"<Link>([^<]+)</Link>", proj)
        self.assertEqual(len(links), len(set(links)), "the link paths of the Legacy project are unique")
        self.assertEqual(len(re.findall(r"PackageContract\.cs", proj)), 2, "one Include and one Link, nothing else mentions the file")

    @e0("E0-04", "RED", "TSJUMP2-NOT-A-SINGLE-DEFINITION", "the tag text is defined once per language and never in a codec")
    def test_RED_E0_04_one_definition_per_language_and_not_in_the_codec(self):
        contract(os.path.isfile(PY_CONTRACT) and os.path.isfile(CS_CONTRACT), "E0-04", "TSJUMP2-NOT-A-SINGLE-DEFINITION", "a definition is missing")
        py_hits = sorted(n for n, data in base_files().items() if n.endswith(".py") and TAG.encode() in data)
        contract(py_hits == ["package_contract.py"], "E0-04", "TSJUMP2-NOT-A-SINGLE-DEFINITION", "python files with the tag text: %s" % py_hits)
        cs_hits = sorted(n for n, data in base_files().items() if n.endswith(".cs") and TAG.encode() in data)
        contract(cs_hits == [SHARED_DIR + "/PackageContract.cs"], "E0-04", "TSJUMP2-NOT-A-SINGLE-DEFINITION", "C# files with the tag text: %s" % cs_hits)
        for codec in ("jump_wire.py", SHARED_DIR + "/JumpWire.cs", "station_index_contract.py", SHARED_DIR + "/StationListIdentity.cs"):
            self.assertNotIn(TAG.encode(), base_files()[codec], codec)
        text = read_text(CS_CONTRACT)
        self.assertEqual(len(re.findall(r'"TSJUMP2"', text)), 1, "the C# tag text appears once")

    @e0("E0-05", "RED", "TSJUMP2-VALUES-NOT-EQUAL", "Python, Current, Legacy (the one shared file), the manifest and the guard hold the same tag, versions and capability bundle")
    def test_RED_E0_05_all_five_values_are_equal(self):
        contract(os.path.isfile(PY_CONTRACT) and os.path.isfile(CS_CONTRACT) and os.path.isfile(MANIFEST_FILE) and os.path.isfile(TOOL_PATH), "E0-05", "TSJUMP2-VALUES-NOT-EQUAL",
                 "the contract, the manifest or the guard does not exist")
        py, cs, tool = py_constants(), cs_constants(), load_tool()
        manifest = json.loads(read_text(MANIFEST_FILE))
        py_values = (py["CONTRACT_TAG"], py["REQUEST_WIRE_VERSION"], py["COMPLETION_WIRE_VERSION"], py["STATIONINDEX_WIRE_VERSION"], ",".join(py["CAPABILITIES"]))
        cs_values = (cs["Tag"], cs["RequestWireVersion"], cs["CompletionWireVersion"], cs["StationIndexWireVersion"], cs["Capabilities"])
        mf_values = (manifest["contract_tag"], manifest["request_wire_version"], manifest["completion_wire_version"], manifest["stationindex_wire_version"], ",".join(manifest["capabilities"]))
        gd_values = (tool.EXPECTED_TAG, tool.EXPECTED_REQUEST_WIRE, tool.EXPECTED_COMPLETION_WIRE, tool.EXPECTED_STATIONINDEX_WIRE, ",".join(tool.EXPECTED_CAPABILITIES))
        want = (TAG, 2, 2, 1, ",".join(CAPABILITIES))
        for name, values in (("python", py_values), ("csharp", cs_values), ("manifest", mf_values), ("guard", gd_values)):
            contract(values == want, "E0-05", "TSJUMP2-VALUES-NOT-EQUAL", "%s holds %r" % (name, values))
        self.assertEqual(len(CAPABILITIES), len(set(CAPABILITIES)))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", c) for c in CAPABILITIES), "capability names: lower case words joined by '-'")

    @e0("E0-06", "GUARD", note="the wire versions and every codec / contract source of 0b8e511 are unchanged (the codec is not the place of TSJUMP2)")
    def test_GUARD_E0_06_the_codec_and_the_wire_versions_are_unchanged(self):
        for path in CODEC_FILES:
            data = clean(base_files()[path])
            self.assertEqual(blob_id(data), BASE_BLOBS[path], path)
        wire = read_text(os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "Shared", "JumpWire.cs"))
        self.assertIn("internal const int V1 = 1;", wire)
        self.assertIn("internal const int V2 = 2;", wire)
        self.assertRegex(read_text(os.path.join(ROOT, "station_index_contract.py")), r"(?m)^VERSION = 1$")


# ---- B: the source sets ----------------------------------------------------------------------------------------------------------------------------------------------------------

class B_SourceSets(unittest.TestCase):
    # (the code word PYTHON-RUNTIME-SET-NOT-23-MODULES keeps its name: it identifies E0-07 in the handoff records; the closure is now 25 modules = 22 + official_target_contract + hud_target_contract + package_contract)
    @e0("E0-07", "RED", "PYTHON-RUNTIME-SET-NOT-23-MODULES", "the import closure of main.py is the 22 modules of 0b8e511 plus official_target_contract (SI-R2.2-S2a) plus hud_target_contract (SI-R2.3) plus package_contract: missing 0, duplicate 0, dynamic import 0, network.py outside")
    def test_RED_E0_07_the_python_runtime_set(self):
        files = base_files()
        modules, dyn = ref_closure(files)
        without = [m for m in modules if m != "package_contract"]
        self.assertEqual(without, sorted(PYTHON_24), "the 22 modules of the U10 Push Close plus official_target_contract of SI-R2.2-S2a plus hud_target_contract of SI-R2.3 (a moved closure is RED-INVALID, not a RED)")
        self.assertEqual(dyn, 0)
        self.assertNotIn("network", modules)
        for name in REQUIRED_PYTHON:
            self.assertIn(name[:-3], modules)
        contract("package_contract" in modules, "E0-07", "PYTHON-RUNTIME-SET-NOT-23-MODULES", "package_contract.py is not in the closure of main.py (%d modules)" % len(modules))
        contract(len(modules) == 26, "E0-07", "PYTHON-RUNTIME-SET-NOT-23-MODULES", "%d modules" % len(modules))
        main_lines = [l for l in read_text(os.path.join(ROOT, "main.py")).splitlines() if l.strip() == "import package_contract"]
        self.assertEqual(len(main_lines), 1, "main.py imports the contract once, at the top level")

    @e0("E0-08", "RED", "CURRENT-SOURCE-SET-NOT-FIXED", "Current: the project + 6 own files + 6 shared = 12 compile inputs (11 before), unique, none outside the three folders")
    def test_RED_E0_08_the_current_source_set(self):
        items = ref_compile(CURRENT_PROJECT, read_text(os.path.join(ROOT, CURRENT_PROJECT.replace("/", os.sep))))
        before = [i for i in items if not i.endswith("PackageContract.cs")]
        self.assertEqual(len(before), 11, "the 11 compile inputs of 0b8e511")
        contract(len(items) == 12, "E0-08", "CURRENT-SOURCE-SET-NOT-FIXED", "%d compile inputs" % len(items))
        self.assertEqual(len(items), len(set(items)))
        for i in items:
            self.assertTrue(i.startswith("TsScoringPlugin/TsScoringPlugin/") or i.startswith(SHARED_DIR + "/"), i)
            self.assertIn(i, base_files(), i)

    @e0("E0-09", "RED", "LEGACY-SOURCE-SET-NOT-FIXED", "Legacy: the project + 15 own + 2 linked from Current + 7 shared = 24 compile inputs (23 before), TelemetryContract.cs stays Legacy only")
    def test_RED_E0_09_the_legacy_source_set(self):
        items = ref_compile(LEGACY_PROJECT, read_text(os.path.join(ROOT, LEGACY_PROJECT.replace("/", os.sep))))
        before = [i for i in items if not i.endswith("PackageContract.cs")]
        self.assertEqual(len(before), 23, "the 23 compile inputs of 0b8e511")
        contract(len(items) == 24, "E0-09", "LEGACY-SOURCE-SET-NOT-FIXED", "%d compile inputs" % len(items))
        self.assertEqual(len(items), len(set(items)))
        current = ref_compile(CURRENT_PROJECT, read_text(os.path.join(ROOT, CURRENT_PROJECT.replace("/", os.sep))))
        self.assertIn(SHARED_DIR + "/TelemetryContract.cs", items)
        self.assertNotIn(SHARED_DIR + "/TelemetryContract.cs", current, "TelemetryContract.cs is Legacy only")
        self.assertEqual(sorted(set(items) & set(current) - {i for i in items if i.startswith(SHARED_DIR)}),
                         ["TsScoringPlugin/TsScoringPlugin/CurrentDataPlane.cs", "TsScoringPlugin/TsScoringPlugin/CurrentJumpEndpoint.cs"], "the two files Legacy links from Current")

    @e0("E0-10", "RED", "SHARED-SOURCE-SET-NOT-FIXED", "Shared: 6 files of 0b8e511 + PackageContract.cs; both projects compile the one new blob; every shared file is compiled by at least one project")
    def test_RED_E0_10_the_shared_source_set(self):
        shared = sorted(n for n in base_files() if n.startswith(SHARED_DIR + "/"))
        self.assertEqual(len([s for s in shared if not s.endswith("PackageContract.cs")]), 6)
        contract(len(shared) == 7 and SHARED_DIR + "/PackageContract.cs" in shared, "E0-10", "SHARED-SOURCE-SET-NOT-FIXED", "shared files: %s" % shared)
        cur = ref_compile(CURRENT_PROJECT, read_text(os.path.join(ROOT, CURRENT_PROJECT.replace("/", os.sep))))
        leg = ref_compile(LEGACY_PROJECT, read_text(os.path.join(ROOT, LEGACY_PROJECT.replace("/", os.sep))))
        for s in shared:
            self.assertTrue(s in cur or s in leg, s + " is compiled by neither project")
        self.assertIn(SHARED_DIR + "/PackageContract.cs", cur)
        self.assertIn(SHARED_DIR + "/PackageContract.cs", leg)


# ---- C: the manifest -------------------------------------------------------------------------------------------------------------------------------------------------------------

MANIFEST_KEYS = ["schema", "package_contract", "contract_tag", "source_base_commit", "source_branch", "request_wire_version", "completion_wire_version", "stationindex_wire_version",
                 "capabilities", "launcher_contract", "build_status", "deployment_status", "python_entry", "compile_inputs", "files", "fingerprint"]


def load_manifest(tid, code):
    contract(os.path.isfile(MANIFEST_FILE), tid, code, "package/source-package-manifest.json does not exist")
    data = read_bytes(MANIFEST_FILE)
    return data, json.loads(data.decode("utf-8"))


class C_Manifest(unittest.TestCase):
    @e0("E0-11", "RED", "SOURCE-MANIFEST-ABSENT-OR-WRONG-SHAPE", "the Git-managed manifest exists with exactly the contract's keys, in the contract's order")
    def test_RED_E0_11_the_manifest_has_the_contract_shape(self):
        data, m = load_manifest("E0-11", "SOURCE-MANIFEST-ABSENT-OR-WRONG-SHAPE")
        contract(list(m) == MANIFEST_KEYS, "E0-11", "SOURCE-MANIFEST-ABSENT-OR-WRONG-SHAPE", "keys: %s" % list(m))
        self.assertEqual((m["schema"], m["package_contract"]), ("ts-source-package-manifest/1", "ts-package-contract/1"))
        self.assertEqual(m["launcher_contract"], {"file_name": "launcher.json", "schema_version": 1, "mode": "development"})
        self.assertEqual(m["source_base_commit"], BASE_COMMIT)
        self.assertEqual(m["source_branch"], BRANCH)
        self.assertEqual(m["python_entry"], "main.py")
        self.assertEqual(list(m["compile_inputs"]), ["current", "legacy"])
        for e in m["files"]:
            self.assertEqual(list(e), ["set", "path", "blob_sha256", "blob_size", "blob_eol"])

    @e0("E0-12", "RED", "MANIFEST-ENTRIES-NOT-THE-RUNTIME-SETS", "the entries are exactly the python closure (25), the Current files (7), the Legacy files (16) and the shared files (7): no test, no pycache, no temp")
    def test_RED_E0_12_the_entries_are_the_runtime_sets(self):
        data, m = load_manifest("E0-12", "MANIFEST-ENTRIES-NOT-THE-RUNTIME-SETS")
        files = base_files()
        modules, _ = ref_closure(files)
        cur = ref_compile(CURRENT_PROJECT, files[CURRENT_PROJECT].decode("utf-8-sig"))
        leg = ref_compile(LEGACY_PROJECT, files[LEGACY_PROJECT].decode("utf-8-sig"))
        want = {"python": sorted(m_ + ".py" for m_ in modules),
                "current": sorted([CURRENT_PROJECT] + [i for i in cur if i.startswith("TsScoringPlugin/TsScoringPlugin/")]),
                "legacy": sorted([LEGACY_PROJECT] + [i for i in leg if i.startswith("TsScoringPlugin/Handshake/Telemetry/Legacy/")]),
                "shared": sorted(n for n in files if n.startswith(SHARED_DIR + "/"))}
        got = {s: sorted(e["path"] for e in m["files"] if e["set"] == s) for s in want}
        for s in want:
            contract(got[s] == want[s], "E0-12", "MANIFEST-ENTRIES-NOT-THE-RUNTIME-SETS", "%s: %s" % (s, sorted(set(got[s]) ^ set(want[s]))))
        self.assertEqual({s: len(v) for s, v in got.items()}, {"python": 26, "current": 7, "legacy": 16, "shared": 7})
        paths = [e["path"] for e in m["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(len(paths), len({p.lower() for p in paths}), "no path collision")
        self.assertFalse([p for p in paths if p.startswith(("tests/", "package/")) or "__pycache__" in p or "/obj/" in p or "/bin/" in p or p.endswith((".pyc", ".dll", ".tmp", ".log"))])
        self.assertEqual(m["compile_inputs"]["current"], sorted(cur))
        self.assertEqual(m["compile_inputs"]["legacy"], sorted(leg))

    @e0("E0-13", "RED", "MANIFEST-BLOB-IDENTITY-WRONG", "every entry is the SHA-256 / size / line ending of the Git BLOB (the clean-filtered bytes), recomputed here")
    def test_RED_E0_13_the_entries_are_the_blob_identities(self):
        data, m = load_manifest("E0-13", "MANIFEST-BLOB-IDENTITY-WRONG")
        files = base_files()
        for e in m["files"]:
            raw = files.get(e["path"])
            contract(raw is not None, "E0-13", "MANIFEST-BLOB-IDENTITY-WRONG", "%s is not a source file" % e["path"])
            blob = clean(raw)
            contract(sha256_upper(blob) == e["blob_sha256"], "E0-13", "MANIFEST-BLOB-IDENTITY-WRONG", "%s: SHA-256 differs" % e["path"])
            self.assertEqual(e["blob_size"], len(blob), e["path"])
            crlf, lf = blob.count(b"\r\n"), blob.count(b"\n") - blob.count(b"\r\n")
            self.assertEqual(e["blob_eol"], "none" if not (crlf or lf) else ("lf" if lf and not crlf else ("crlf" if crlf and not lf else "mixed")), e["path"])
            self.assertEqual(e["blob_sha256"], e["blob_sha256"].upper())
            self.assertRegex(e["blob_sha256"], r"^[0-9A-F]{64}$")
        # the files of 0b8e511 keep the identity the U10 Push Close recorded (git blob id equal)
        for e in m["files"]:
            if e["path"] in BASE_BLOBS:
                self.assertEqual(blob_id(clean(files[e["path"]])), BASE_BLOBS[e["path"]], e["path"])

    @e0("E0-14", "RED", "MANIFEST-FINGERPRINT-WRONG", "the fingerprint is recomputed here from the contract header and the sorted entry lines (LF joined, no trailing LF), not from the manifest as a whole")
    def test_RED_E0_14_the_fingerprint(self):
        data, m = load_manifest("E0-14", "MANIFEST-FINGERPRINT-WRONG")
        contract(ref_fingerprint(m) == m["fingerprint"], "E0-14", "MANIFEST-FINGERPRINT-WRONG", "recomputed %s, recorded %s" % (ref_fingerprint(m), m["fingerprint"]))
        self.assertRegex(m["fingerprint"], r"^[0-9A-F]{64}$")
        # no self hash: neither the manifest nor any name of the package folder is an input
        m2 = copy.deepcopy(m)
        m2["source_branch"] = "other"
        m2["source_base_commit"] = "0" * 40
        self.assertEqual(ref_fingerprint(m2), m["fingerprint"], "the fingerprint is the identity of the SOURCE, not of the commit or the branch it was computed on")
        m3 = copy.deepcopy(m)
        m3["files"][0]["blob_sha256"] = "0" * 64
        self.assertNotEqual(ref_fingerprint(m3), m["fingerprint"])

    @e0("E0-15", "RED", "MANIFEST-NOT-DETERMINISTIC", "generating twice gives the same bytes, equal to the committed file; UTF-8 without BOM, LF only, one trailing LF, ASCII, no tab")
    def test_RED_E0_15_the_manifest_is_deterministic(self):
        tool = require_tool("E0-15", "MANIFEST-NOT-DETERMINISTIC")
        data, m = load_manifest("E0-15", "MANIFEST-NOT-DETERMINISTIC")
        tree = tool.MemoryTree(dict(base_files()))
        first = tool.serialize(tool.build_manifest(tree, BASE_COMMIT, BRANCH))
        second = tool.serialize(tool.build_manifest(tool.MemoryTree(dict(reversed(list(base_files().items())))), BASE_COMMIT, BRANCH))
        contract(first == second, "E0-15", "MANIFEST-NOT-DETERMINISTIC", "the order the files are given in changes the bytes")
        contract(first == data, "E0-15", "MANIFEST-NOT-DETERMINISTIC", "the committed manifest is not what the generator makes of this tree")
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"\n") and not data.endswith(b"\n\n"))
        data.decode("ascii")
        self.assertNotIn(b"\t", data)
        # CRLF checkout of every source gives the same manifest (the identity is the blob, not the work tree)
        crlf = {k: (v.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") if not b"\x00" in v else v) for k, v in base_files().items()}
        self.assertEqual(tool.serialize(tool.build_manifest(tool.MemoryTree(crlf), BASE_COMMIT, BRANCH)), data)

    @e0("E0-16", "RED", "MANIFEST-SELF-REFERENCE-OR-VOLATILE-FIELD", "no self reference, no future commit, no time, no machine / user / absolute path / process id, no DLL SHA")
    def test_RED_E0_16_no_volatile_field(self):
        data, m = load_manifest("E0-16", "MANIFEST-SELF-REFERENCE-OR-VOLATILE-FIELD")
        text = data.decode("ascii")
        self.assertFalse([e for e in m["files"] if e["path"].startswith("package/")], "the manifest is not an entry of itself")
        self.assertEqual(m["source_base_commit"], BASE_COMMIT, "the base commit only: ST-3e0's own commit is recorded after the commit, outside this file")
        contract(not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|timestamp|generated_at|created|\bpid\b", text, re.I), "E0-16", "MANIFEST-SELF-REFERENCE-OR-VOLATILE-FIELD", "a time or process field")
        contract(not re.search(r"[A-Za-z]:[\\/]|\\\\|/Users/|\bUsers\b|computername|username|\.dll\b|\.pdb\b", text, re.I), "E0-16", "MANIFEST-SELF-REFERENCE-OR-VOLATILE-FIELD",
                 "an absolute path, a user or machine name, or a DLL")
        self.assertNotIn("\\", text.replace("\\n", ""), "forward slashes only")
        self.assertEqual(len(re.findall(r"[0-9a-f]{40}", text)), 1, "exactly one commit id (the base)")

    @e0("E0-17", "RED", "MANIFEST-BUILD-STATUS-NOT-NOT-BUILT", "build status = not-built, deployment status = not-deployed, no DLL identity")
    def test_RED_E0_17_the_status_is_not_built_not_deployed(self):
        data, m = load_manifest("E0-17", "MANIFEST-BUILD-STATUS-NOT-NOT-BUILT")
        contract((m["build_status"], m["deployment_status"]) == ("not-built", "not-deployed"), "E0-17", "MANIFEST-BUILD-STATUS-NOT-NOT-BUILT", "%r / %r" % (m["build_status"], m["deployment_status"]))
        self.assertFalse([k for k in m if "dll" in k.lower() or "deploy" in k.lower() and k != "deployment_status"])


# ---- D: the N-12 guard ------------------------------------------------------------------------------------------------------------------------------------------------------------

class Case(object):
    def __init__(self, cid, title, mutate, expect, accept=False, mode="worktree"):
        self.cid, self.title, self.mutate, self.expect, self.accept, self.mode = cid, title, mutate, tuple(expect), accept, mode


class Ctx(object):
    """One package under test: the files, the manifest object, and how the manifest bytes are produced."""

    def __init__(self, tool):
        self.tool = tool
        self.files = dict(base_files())
        self.manifest = None                    # the manifest object (set from the tree below, then mutated)
        self.refinger = False                   # recompute the fingerprint after the mutation (so the ONLY fault is the intended one)
        self.regen = False                      # rebuild the manifest from the mutated tree (a self-consistent but wrong package)
        self.raw = None                         # manifest bytes used instead of the serialized object
        self.committed = None                   # the committed view for the commit mode (files); None = same as the work tree
        self.drop_manifest = False

    def prepare(self):
        base = self.tool.build_manifest(self.tool.MemoryTree(dict(base_files())), BASE_COMMIT, BRANCH)
        self.manifest = copy.deepcopy(base)

    def finish(self):
        tool = self.tool
        tree = tool.MemoryTree(self.files)
        if self.regen:
            m = tool.build_manifest(tree, BASE_COMMIT, BRANCH)
        else:
            m = self.manifest
            if self.refinger:
                try:
                    m["fingerprint"] = ref_fingerprint(m)
                except (TypeError, KeyError, ValueError):
                    pass                                # a manifest of the wrong shape has no fingerprint to recompute: it is left as it is
        data = None if self.drop_manifest else (self.raw if self.raw is not None else tool.serialize(m))
        committed = None if self.committed is None else tool.MemoryTree(self.committed)
        return tree, data, committed


def entry(ctx, path):
    return [e for e in ctx.manifest["files"] if e["path"] == path][0]


def set_text(ctx, path, fn):
    ctx.files[path] = fn(ctx.files[path].decode("utf-8")).encode("utf-8")


def drop_file(ctx, path):
    del ctx.files[path]


def old_python(ctx, regen=True):
    """A Python without the contract: no module, no import (the state of 0b8e511). regen: the manifest is rebuilt for it (a self consistent old package)."""
    del ctx.files["package_contract.py"]
    set_text(ctx, "main.py", lambda t: t.replace("import package_contract\n", ""))
    ctx.regen = ctx.regen or regen


def old_current(ctx, regen=True):
    set_text(ctx, CURRENT_PROJECT, lambda t: re.sub(r'[^\n]*PackageContract\.cs[^\n]*\n', "", t))
    ctx.regen = ctx.regen or regen


def old_legacy(ctx, regen=True):
    set_text(ctx, LEGACY_PROJECT, lambda t: re.sub(r'\s*<Compile Include="\.\.\\Shared\\PackageContract\.cs">\s*<Link>[^<]*</Link>\s*</Compile>', "", t))
    ctx.regen = ctx.regen or regen


def cs_replace(old, new):
    return lambda ctx: set_text(ctx, SHARED_DIR + "/PackageContract.cs", lambda t: t.replace(old, new))


def py_replace(old, new):
    return lambda ctx: set_text(ctx, "package_contract.py", lambda t: t.replace(old, new))


def seq(*fns):
    def run(ctx):
        for f in fns:
            f(ctx)
    return run


def mf(key, value, refinger=True):
    def run(ctx):
        ctx.manifest[key] = value
        ctx.refinger = refinger
    return run


def mf_entry(path, key, value, refinger=False):
    def run(ctx):
        entry(ctx, path)[key] = value
        ctx.refinger = refinger
    return run


def raw_bytes(fn):
    def run(ctx):
        ctx.raw = fn(ctx.tool.serialize(ctx.manifest))
    return run


def mutate_manifest(fn, refinger=True):
    def run(ctx):
        fn(ctx.manifest)
        ctx.refinger = refinger
    return run


def build_cases():
    P = "package_contract.py"
    CS = SHARED_DIR + "/PackageContract.cs"
    cases = [
        Case("N12-00", "the official package (the work tree of this phase) is accepted", lambda c: None, [], accept=True),
        Case("N12-00b", "the same package checked out with CRLF line endings is accepted (the identity is the blob)", lambda c: c.files.update(
            {k: v.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") for k, v in c.files.items() if b"\x00" not in v}), [], accept=True),
        # --- old / new combinations (U10 Push Close 07, the 13 refusals) ---
        Case("N12-01", "new Python + old Current (against the official manifest)", lambda c: old_current(c, False), ["tag-missing:current", "tag-partial", "compile-set-mismatch:current"]),
        Case("N12-01b", "new Python + old Current (a manifest rebuilt for the old Current is still refused)", old_current, ["tag-missing:current", "tag-partial"]),
        Case("N12-02", "new Python + old Legacy (against the official manifest)", lambda c: old_legacy(c, False), ["tag-missing:legacy", "tag-partial", "compile-set-mismatch:legacy"]),
        Case("N12-02b", "new Python + old Legacy (a manifest rebuilt for the old Legacy is still refused)", old_legacy, ["tag-missing:legacy", "tag-partial"]),
        Case("N12-03", "new Current + new Legacy + old Python (against the official manifest)", lambda c: old_python(c, False), ["tag-missing:python", "tag-partial", "python-set-mismatch"]),
        Case("N12-03b", "new Current + new Legacy + old Python (a manifest rebuilt for the old Python is still refused)", old_python, ["tag-missing:python", "tag-partial"]),
        Case("N12-05", "only Current has TSJUMP2", seq(old_python, old_legacy), ["tag-missing:python", "tag-missing:legacy", "tag-partial"]),
        Case("N12-06", "only Legacy has TSJUMP2 (new Legacy + old Python, Current old)", seq(old_python, old_current), ["tag-missing:python", "tag-missing:current", "tag-partial"]),
        Case("N12-07", "only Python has TSJUMP2", seq(old_current, old_legacy), ["tag-missing:current", "tag-missing:legacy", "tag-partial"]),
        Case("N12-08", "none has TSJUMP2 (the package of 0b8e511)", seq(old_python, old_current, old_legacy), ["tag-missing:python", "tag-missing:current", "tag-missing:legacy"]),
        # --- the tag text ---
        Case("N12-09", "Python tag differs (TSJUMP1)", py_replace('"TSJUMP2"', '"TSJUMP1"'), ["tag-mismatch:python"]),
        Case("N12-10", "C# tag differs (both projects)", cs_replace('"TSJUMP2"', '"TSJUMP1"'), ["tag-mismatch:current", "tag-mismatch:legacy"]),
        Case("N12-11", "manifest tag differs", mf("contract_tag", "TSJUMP1"), ["tag-mismatch:manifest"]),
        Case("N12-12", "Python tag in lower case", py_replace('"TSJUMP2"', '"tsjump2"'), ["tag-mismatch:python"]),
        Case("N12-13", "C# tag with a trailing space", cs_replace('"TSJUMP2"', '"TSJUMP2 "'), ["tag-mismatch:current", "tag-mismatch:legacy"]),
        Case("N12-14", "manifest tag with a leading space", mf("contract_tag", " TSJUMP2"), ["tag-mismatch:manifest"]),
        Case("N12-15", "Python contract without the tag", py_replace('CONTRACT_TAG = "TSJUMP2"', 'CONTRACT_TAG_X = "TSJUMP2"'), ["tag-missing:python"]),
        # --- the other values of the bundle ---
        Case("N12-16", "request wire version differs in Python", py_replace("REQUEST_WIRE_VERSION = 2", "REQUEST_WIRE_VERSION = 3"), ["request-wire-mismatch:python"]),
        Case("N12-17", "request wire version differs in C#", cs_replace("RequestWireVersion = 2", "RequestWireVersion = 1"), ["request-wire-mismatch:current", "request-wire-mismatch:legacy"]),
        Case("N12-18", "request wire version differs in the manifest", mf("request_wire_version", 1), ["request-wire-mismatch:manifest"]),
        Case("N12-19", "completion version differs in Python", py_replace("COMPLETION_WIRE_VERSION = 2", "COMPLETION_WIRE_VERSION = 1"), ["completion-wire-mismatch:python"]),
        Case("N12-20", "completion version differs in C#", cs_replace("CompletionWireVersion = 2", "CompletionWireVersion = 3"), ["completion-wire-mismatch:current", "completion-wire-mismatch:legacy"]),
        Case("N12-21", "completion version differs in the manifest", mf("completion_wire_version", 1), ["completion-wire-mismatch:manifest"]),
        Case("N12-22", "StationIndex contract differs in Python", py_replace("STATIONINDEX_WIRE_VERSION = 1", "STATIONINDEX_WIRE_VERSION = 2"), ["stationindex-wire-mismatch:python"]),
        Case("N12-23", "StationIndex contract differs in C#", cs_replace("StationIndexWireVersion = 1", "StationIndexWireVersion = 2"), ["stationindex-wire-mismatch:current", "stationindex-wire-mismatch:legacy"]),
        Case("N12-24", "StationIndex contract differs in the manifest", mf("stationindex_wire_version", 2), ["stationindex-wire-mismatch:manifest"]),
        Case("N12-25", "a capability is missing in Python", py_replace('    "whole-list-reject",\n', ""), ["capabilities-mismatch:python"]),
        Case("N12-26", "the capabilities of C# are in another order", cs_replace("jump-request-v2,jump-completion-v2", "jump-completion-v2,jump-request-v2"), ["capabilities-mismatch:current", "capabilities-mismatch:legacy"]),
        Case("N12-27", "a capability is added in the manifest", mutate_manifest(lambda m: m["capabilities"].append("extra-switch")), ["capabilities-mismatch:manifest"]),
        # --- required python files and the runtime set ---
        Case("N12-28", "jump_transaction.py is missing", drop_file_case("jump_transaction.py"), ["python-required-missing:jump_transaction.py"]),
        Case("N12-29", "jump_wire.py is missing", drop_file_case("jump_wire.py"), ["python-required-missing:jump_wire.py"]),
        Case("N12-30", "scoring_logic.py is missing", drop_file_case("scoring_logic.py"), ["python-required-missing:scoring_logic.py"]),
        Case("N12-31", "managed_input.py is missing", drop_file_case("managed_input.py"), ["python-required-missing:managed_input.py"]),
        Case("N12-32", "station_identity.py is missing", drop_file_case("station_identity.py"), ["python-required-missing:station_identity.py"]),
        Case("N12-33", "main.py is missing", drop_file_case("main.py"), ["python-entry-missing"]),
        Case("N12-34", "package_contract.py is missing but main.py still imports it", drop_file_case(P), ["source-missing:package_contract.py", "tag-missing:python"]),
        Case("N12-35", "another runtime module (hud_ui.py) is missing", drop_file_case("hud_ui.py"), ["source-missing:hud_ui.py"]),
        Case("N12-36", "a new runtime module is imported but not in the manifest", lambda c: (c.files.update({"extra_mod.py": b"X = 1\n"}),
                                                                                               set_text(c, "main.py", lambda t: t.replace("import package_contract\n", "import package_contract\nimport extra_mod\n"))),
             ["python-set-mismatch", "source-unlisted:extra_mod.py"]),
        Case("N12-37", "a dynamic import appears in a runtime module", lambda c: set_text(c, "utils.py", lambda t: t + "\n__import__('x')\n"), ["python-dynamic-import", "source-identity-mismatch:utils.py"]),
        Case("N12-38", "main.py does not import the contract any more", lambda c: set_text(c, "main.py", lambda t: t.replace("import package_contract\n", "")), ["python-set-mismatch", "source-identity-mismatch:main.py"]),
        # --- source identity ---
        Case("N12-39", "a Python runtime source changed (scoring_logic.py)", lambda c: set_text(c, "scoring_logic.py", lambda t: t + "\n# changed\n"), ["source-identity-mismatch:scoring_logic.py"]),
        Case("N12-40", "a Current source changed (Class1.cs)", lambda c: set_text(c, "TsScoringPlugin/TsScoringPlugin/Class1.cs", lambda t: t + "\n// changed\n"),
             ["source-identity-mismatch:TsScoringPlugin/TsScoringPlugin/Class1.cs"]),
        Case("N12-41", "a Legacy source changed (LegacyJumpExecutor.cs)", lambda c: set_text(c, "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpExecutor.cs", lambda t: t + "\n// changed\n"),
             ["source-identity-mismatch:TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpExecutor.cs"]),
        Case("N12-42", "a Shared source changed (JumpWire.cs)", lambda c: set_text(c, SHARED_DIR + "/JumpWire.cs", lambda t: t + "\n// changed\n"), ["source-identity-mismatch:" + SHARED_DIR + "/JumpWire.cs"]),
        Case("N12-43", "a project file changed outside its compile list", lambda c: set_text(c, CURRENT_PROJECT, lambda t: t.replace("</Project>", "  <!-- changed -->\n</Project>")),
             ["source-identity-mismatch:" + CURRENT_PROJECT]),
        Case("N12-44", "an entry's SHA-256 differs in the manifest", mf_entry("jump_wire.py", "blob_sha256", "0" * 64), ["source-identity-mismatch:jump_wire.py", "manifest-fingerprint-mismatch"]),
        Case("N12-45", "an entry's size differs in the manifest", mf_entry("jump_wire.py", "blob_size", 1, refinger=True), ["source-identity-mismatch:jump_wire.py"]),
        Case("N12-46", "the fingerprint differs", mf("fingerprint", "0" * 64, refinger=False), ["manifest-fingerprint-mismatch"]),
        Case("N12-47", "the fingerprint is in lower case", lambda c: c.manifest.update({"fingerprint": ref_fingerprint(c.manifest).lower()}), ["manifest-fingerprint-mismatch"]),
        # --- compile sets ---
        Case("N12-48", "a Current compile input is removed", lambda c: set_text(c, CURRENT_PROJECT, lambda t: re.sub(r'[^\n]*CurrentJumpExecution\.cs[^\n]*\n', "", t)), ["compile-set-mismatch:current"]),
        Case("N12-49", "a Legacy compile input is removed", lambda c: set_text(c, LEGACY_PROJECT, lambda t: re.sub(r'\s*<Compile Include="src\\LegacyJumpExecutor\.cs" />', "", t)), ["compile-set-mismatch:legacy"]),
        Case("N12-50", "a Shared link is removed from Legacy (JumpWire.cs)", lambda c: set_text(c, LEGACY_PROJECT, lambda t: re.sub(r'\s*<Compile Include="\.\.\\Shared\\JumpWire\.cs">\s*<Link>[^<]*</Link>\s*</Compile>', "", t)),
             ["compile-set-mismatch:legacy"]),
        Case("N12-51", "a Shared link is removed from Current (JumpWire.cs)", lambda c: set_text(c, CURRENT_PROJECT, lambda t: re.sub(r'[^\n]*Shared\\JumpWire\.cs</Link></Compile>\r?\n', "", t)), ["compile-set-mismatch:current"]),
        Case("N12-52", "a compile input is duplicated in Current", lambda c: set_text(c, CURRENT_PROJECT, lambda t: t.replace('<Compile Include="Class1.cs" />', '<Compile Include="Class1.cs" />\n    <Compile Include="Class1.cs" />')),
             ["compile-duplicate:current"]),
        Case("N12-53", "two Legacy compile items share a link path", lambda c: set_text(c, LEGACY_PROJECT, lambda t: t.replace("<Link>Shared\\JumpWire.cs</Link>", "<Link>Shared\\StationListIdentity.cs</Link>")), ["compile-link-collision:legacy"]),
        Case("N12-54", "a wildcard compile item", lambda c: set_text(c, CURRENT_PROJECT, lambda t: t.replace('<Compile Include="Class1.cs" />', '<Compile Include="*.cs" />')), ["compile-wildcard:current"]),
        Case("N12-55", "a compile input outside the three folders", lambda c: set_text(c, CURRENT_PROJECT, lambda t: t.replace('<Compile Include="Class1.cs" />', '<Compile Include="..\\..\\tests\\X.cs" />')),
             ["compile-input-out-of-set:current"]),
        Case("N12-56", "a shared file nobody compiles", lambda c: c.files.update({SHARED_DIR + "/Orphan.cs": b"// x\n"}), ["source-unlisted:" + SHARED_DIR + "/Orphan.cs", "shared-unreferenced:" + SHARED_DIR + "/Orphan.cs"]),
        Case("N12-57", "a project file that is not XML", lambda c: c.files.update({CURRENT_PROJECT: b"not xml"}), ["project-unparseable:current"]),
        Case("N12-57b", "a compile item with a Condition (it may not be compiled at all)", lambda c: set_text(c, CURRENT_PROJECT, lambda t: t.replace('<Compile Include="Class1.cs" />', '<Compile Include="Class1.cs" Condition="false" />')),
             ["compile-conditional:current"]),
        Case("N12-57c", "a group of compile items with a Condition", lambda c: set_text(c, LEGACY_PROJECT, lambda t: re.sub(r'<ItemGroup>(\s*<Compile Include="src\\AssemblyInfo\.cs")', r'<ItemGroup Condition="false">\1', t, count=1)),
             ["compile-conditional:legacy"]),
        Case("N12-57d", "a Compile Remove next to the include list", lambda c: set_text(c, LEGACY_PROJECT, lambda t: t.replace('<Compile Include="src\\LegacyApi.cs" />', '<Compile Include="src\\LegacyApi.cs" />\r\n    <Compile Remove="src\\LegacyApi.cs" />')),
             ["compile-modified:legacy"]),
        Case("N12-57e", "the contract file holds a preprocessor directive (#if)", lambda c: set_text(c, SHARED_DIR + "/PackageContract.cs", lambda t: t + "#if FALSE\n#endif\n"),
             ["contract-source-conditional:current", "contract-source-conditional:legacy", "source-identity-mismatch:" + SHARED_DIR + "/PackageContract.cs"]),
        # --- the manifest ---
        Case("N12-58", "the manifest is missing", lambda c: setattr(c, "drop_manifest", True), ["manifest-missing"]),
        Case("N12-59", "the manifest is empty", lambda c: setattr(c, "raw", b""), ["manifest-unparseable"]),
        Case("N12-60", "the manifest is a JSON list", lambda c: setattr(c, "raw", b"[]\n"), ["manifest-schema-mismatch"]),
        Case("N12-61", "the manifest is JSON null", lambda c: setattr(c, "raw", b"null\n"), ["manifest-schema-mismatch"]),
        Case("N12-62", "the manifest has a BOM", raw_bytes(lambda b: b"\xef\xbb\xbf" + b), ["manifest-not-canonical"]),
        Case("N12-63", "the manifest has CRLF", raw_bytes(lambda b: b.replace(b"\n", b"\r\n")), ["manifest-not-canonical"]),
        Case("N12-64", "the manifest has no trailing LF", raw_bytes(lambda b: b.rstrip(b"\n")), ["manifest-not-canonical"]),
        Case("N12-65", "the manifest has a duplicate key", raw_bytes(lambda b: b.replace(b'"build_status": "not-built",', b'"build_status": "not-built",\n  "build_status": "not-built",')), ["manifest-duplicate-key"]),
        Case("N12-66", "the schema id differs", mf("schema", "ts-source-package-manifest/2"), ["manifest-schema-mismatch"]),
        Case("N12-67", "a key is missing", mutate_manifest(lambda m: m.pop("launcher_contract")), ["manifest-schema-mismatch"]),
        Case("N12-68", "an unknown key (a timestamp) is present", mutate_manifest(lambda m: m.update({"generated_at": "2026-10-23T00:00:00Z"})), ["manifest-schema-mismatch"]),
        Case("N12-69", "an unknown key (a DLL SHA) is present", mutate_manifest(lambda m: m.update({"current_dll_sha256": "0" * 64})), ["manifest-schema-mismatch"]),
        Case("N12-70", "a wrong type (the request version as text)", mf("request_wire_version", "2"), ["manifest-schema-mismatch"]),
        Case("N12-71", "the package contract id differs", mf("package_contract", "ts-package-contract/2"), ["manifest-contract-mismatch"]),
        Case("N12-72", "build status says built (forged)", mf("build_status", "built"), ["manifest-status-invalid"]),
        Case("N12-73", "deployment status says deployed (forged)", mf("deployment_status", "deployed"), ["manifest-status-invalid"]),
        Case("N12-74", "build status is unknown", mf("build_status", "weird"), ["manifest-status-invalid"]),
        Case("N12-75", "build status in another case", mf("build_status", "Not-Built"), ["manifest-status-invalid"]),
        Case("N12-76", "the base commit is not a 40 digit id", mf("source_base_commit", "0b8e511", refinger=False), ["manifest-base-commit-invalid"]),
        Case("N12-77", "an entry path is absolute", lambda c: (entry(c, "utils.py").update({"path": "C:/x/utils.py"}), setattr(c, "refinger", True)), ["manifest-path-invalid"]),
        Case("N12-78", "an entry path has a backslash", lambda c: (entry(c, "utils.py").update({"path": "sub\\utils.py"}), setattr(c, "refinger", True)), ["manifest-path-invalid"]),
        Case("N12-79", "an entry path climbs out", lambda c: (entry(c, "utils.py").update({"path": "../utils.py"}), setattr(c, "refinger", True)), ["manifest-path-invalid"]),
        Case("N12-80", "a path is listed twice", lambda c: (c.manifest["files"].append(copy.deepcopy(entry(c, "utils.py"))), setattr(c, "refinger", True)), ["manifest-duplicate-path"]),
        Case("N12-81", "two paths differ only by case", lambda c: (c.manifest["files"].append(dict(copy.deepcopy(entry(c, "utils.py")), path="Utils.py")), setattr(c, "refinger", True)), ["manifest-path-collision"]),
        Case("N12-82", "the entries are not in the canonical order", lambda c: (c.manifest["files"].reverse(), setattr(c, "refinger", True)), ["manifest-not-canonical"]),
        Case("N12-83", "an entry is in the wrong set", mf_entry("utils.py", "set", "current", refinger=True), ["manifest-set-mismatch"]),
        Case("N12-84", "an entry is missing from the manifest", lambda c: (c.manifest["files"].remove(entry(c, "utils.py")), setattr(c, "refinger", True)), ["source-unlisted:utils.py", "python-set-mismatch"]),
        Case("N12-85", "an entry names a file that does not exist", lambda c: (c.manifest["files"].append({"set": "python", "path": "ghost.py", "blob_sha256": "0" * 64, "blob_size": 1, "blob_eol": "lf"}), setattr(c, "refinger", True)),
             ["source-missing:ghost.py"]),
        Case("N12-86", "the launcher contract differs", mf("launcher_contract", {"file_name": "launcher.json", "schema_version": 1, "mode": "release"}), ["launcher-contract-mismatch"]),
        Case("N12-87", "a manifest field names a DLL", mutate_manifest(lambda m: m["files"].append({"set": "current", "path": "bin/Release/TsScoringPlugin.dll", "blob_sha256": "0" * 64, "blob_size": 1, "blob_eol": "none"})),
             ["source-missing:bin/Release/TsScoringPlugin.dll"]),
        # --- the commit mode: the work tree must be what is committed ---
        Case("N12-88", "commit mode: a work tree source differs from the committed blob", lambda c: setattr(c, "committed", dict(c.files, **{"utils.py": c.files["utils.py"] + b"# drift\n"})),
             ["working-tree-drift:utils.py"], mode="commit"),
        Case("N12-89", "commit mode: a source is not committed at all", lambda c: setattr(c, "committed", {k: v for k, v in c.files.items() if k != P}), ["source-not-committed:package_contract.py"], mode="commit"),
        Case("N12-90", "commit mode: the committed package is the work tree (accepted)", lambda c: setattr(c, "committed", dict(c.files)), [], accept=True, mode="commit"),
    ]
    return cases


def drop_file_case(path):
    def run(ctx):
        ctx.files.pop(path)
    return run


class D_Guard(unittest.TestCase):
    @e0("E0-18", "RED", "N12-GUARD-ABSENT", "the tool and the PowerShell entry exist; the tool is offline, read-only and standard library only; the entry takes explicit mandatory parameters")
    def test_RED_E0_18_the_guard_exists_and_is_read_only(self):
        import ast
        contract(os.path.isfile(TOOL_PATH), "E0-18", "N12-GUARD-ABSENT", "package/source_package.py does not exist")
        contract(os.path.isfile(WRAPPER), "E0-18", "N12-GUARD-ABSENT", "Handshake/Tests/Test-PackageGuardST3.ps1 does not exist")
        tree = ast.parse(read_bytes(TOOL_PATH))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(imported <= {"argparse", "ast", "collections", "copy", "hashlib", "json", "os", "re", "subprocess", "sys", "xml", "typing"}, imported)
        write_apis = {"write_bytes", "write_text", "remove", "unlink", "rmdir", "rename", "makedirs", "mkdir", "rmtree", "copyfile", "move", "chmod", "truncate"}
        writers = set()
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                name = n.func.attr if isinstance(n.func, ast.Attribute) else (n.func.id if isinstance(n.func, ast.Name) else "")
                mode = ""
                if name == "open":
                    mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                    for kw in n.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            mode = kw.value.value
                if name in write_apis or re.search(r"[wax+]", str(mode)):
                    writers.add(fn.name)
        self.assertLessEqual(writers - {"cmd_generate"}, set(), "only the generator command writes (to the --out path it is given); evaluate / check / describe never write: %s" % sorted(writers))
        verbs, runners = set(), set()
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    name = n.func.attr if isinstance(n.func, ast.Attribute) else (n.func.id if isinstance(n.func, ast.Name) else "")
                    if name == "_git" and len(n.args) > 1 and isinstance(n.args[1], ast.List) and n.args[1].elts and isinstance(n.args[1].elts[0], ast.Constant):
                        verbs.add(n.args[1].elts[0].value)
                    if name in ("run", "Popen", "call", "check_call", "check_output", "system", "popen", "startfile") and fn.name != "_git":
                        runners.add(fn.name)
        self.assertTrue(verbs and verbs <= {"cat-file", "ls-tree", "hash-object", "rev-parse", "merge-base"}, "git is only asked to read: %s" % sorted(verbs))
        self.assertEqual(sorted(runners), [], "the only place a process is started is _git")
        text = read_text(WRAPPER)
        self.assertRegex(text, r"\[Parameter\(Mandatory\s*=\s*\$true\)\]\s*\[string\]\$RepoRoot")
        self.assertRegex(text, r"\[Parameter\(Mandatory\s*=\s*\$true\)\]\s*\[string\]\$PythonExe")
        self.assertNotRegex(text, r"(?i)\b(Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Copy-Item|Move-Item|Rename-Item|Invoke-WebRequest|Start-Process|Install|Restore)\b",
                            "the entry writes nothing, installs nothing, restores nothing")
        self.assertNotIn("$PSScriptRoot", text, "no default value: every path is passed explicitly")

    @e0("E0-19", "RED", "N12-REAL-PACKAGE-NOT-ACCEPTED", "the work tree of this phase, with the committed manifest, is accepted; the verdict allows the build and not the deployment")
    def test_RED_E0_19_the_official_package_is_accepted(self):
        tool = require_tool("E0-19", "N12-REAL-PACKAGE-NOT-ACCEPTED")
        contract(os.path.isfile(MANIFEST_FILE), "E0-19", "N12-REAL-PACKAGE-NOT-ACCEPTED", "no manifest")
        verdict = tool.evaluate(tool.DiskTree(ROOT), read_bytes(MANIFEST_FILE))
        contract(verdict.accepted and not verdict.findings, "E0-19", "N12-REAL-PACKAGE-NOT-ACCEPTED", "findings: %s" % list(verdict.findings))
        self.assertTrue(verdict.build_allowed)
        self.assertFalse(verdict.deployment_allowed, "no deployment before the ST-3e1 build manifest exists")

    @e0("E0-20", "RED", "N12-MISMATCH-MATRIX-NOT-REJECTED", "every case of the matrix gets its verdict and its reasons (the accepted ones are accepted)")
    def test_RED_E0_20_the_mismatch_matrix(self):
        tool = require_tool("E0-20", "N12-MISMATCH-MATRIX-NOT-REJECTED")
        cases = build_cases()
        self.assertEqual(len(cases), len({c.cid for c in cases}))
        for case in cases:
            with self.subTest(case=case.cid, title=case.title):
                ctx = Ctx(tool)
                ctx.prepare()
                case.mutate(ctx)
                tree, data, committed = ctx.finish()
                verdict = tool.evaluate(tree, data, mode=case.mode, committed=committed)
                kinds = list(verdict.findings)
                if case.accept:
                    contract(verdict.accepted and not kinds, "E0-20", "N12-MISMATCH-MATRIX-NOT-REJECTED", "%s should be accepted: %s" % (case.cid, kinds))
                    continue
                contract(not verdict.accepted and not verdict.build_allowed and not verdict.deployment_allowed, "E0-20", "N12-MISMATCH-MATRIX-NOT-REJECTED", "%s was not refused" % case.cid)
                missing = [e for e in case.expect if e not in kinds]
                contract(not missing, "E0-20", "N12-MISMATCH-MATRIX-NOT-REJECTED", "%s lacks %s (findings %s)" % (case.cid, missing, kinds))

    @e0("E0-21", "RED", "N12-UNKNOWN-STATE-NOT-FAIL-CLOSED", "an unreadable tree, an empty tree, a manifest of the wrong kind or a reader that raises is refused, never accepted and never an uncaught exception")
    def test_RED_E0_21_unknown_state_is_refused(self):
        tool = require_tool("E0-21", "N12-UNKNOWN-STATE-NOT-FAIL-CLOSED")
        good = tool.serialize(tool.build_manifest(tool.MemoryTree(dict(base_files())), BASE_COMMIT, BRANCH))

        class Exploding(object):
            def read(self, path):
                raise OSError("unreadable")

            def listdir(self, path):
                raise OSError("unreadable")

        for label, tree, data in (("empty tree", tool.MemoryTree({}), good), ("exploding tree", Exploding(), good), ("no manifest", tool.MemoryTree(dict(base_files())), None),
                                  ("manifest is a number", tool.MemoryTree(dict(base_files())), b"7\n"), ("manifest is garbage", tool.MemoryTree(dict(base_files())), b"\xff\xfe\x00"),
                                  ("manifest is huge nesting", tool.MemoryTree(dict(base_files())), b"[" * 5000)):
            with self.subTest(case=label):
                verdict = tool.evaluate(tree, data)
                contract(not verdict.accepted and verdict.findings, "E0-21", "N12-UNKNOWN-STATE-NOT-FAIL-CLOSED", "%s: %s" % (label, verdict))

    @e0("E0-27", "RED", "N12-LINK-NOT-REFUSED", "a source that runs through a symbolic link or a reparse point is never read: the guard refuses it by name")
    def test_RED_E0_27_a_linked_source_is_refused(self):
        import tempfile
        from unittest import mock
        tool = require_tool("E0-27", "N12-LINK-NOT-REFUSED")
        contract(hasattr(tool, "LinkError"), "E0-27", "N12-LINK-NOT-REFUSED", "the tool has no LinkError")
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.py"), "wb") as handle:
                handle.write(b"X = 1\n")
            tree = tool.DiskTree(tmp)
            self.assertEqual(tree.read("a.py"), b"X = 1\n")
            real_islink = os.path.islink
            with mock.patch("os.path.islink", lambda p: True if str(p).endswith("a.py") else real_islink(p)):
                with self.assertRaises(tool.LinkError):
                    tree.read("a.py")
                with self.assertRaises(tool.LinkError):
                    tree.listdir("a.py")

        class Linked(tool.MemoryTree):
            def read(self, path):
                if path == "utils.py":
                    raise tool.LinkError("utils.py")
                return tool.MemoryTree.read(self, path)

        data = tool.serialize(tool.build_manifest(tool.MemoryTree(dict(base_files())), BASE_COMMIT, BRANCH))
        verdict = tool.evaluate(Linked(dict(base_files())), data)
        contract(not verdict.accepted and "source-link:utils.py" in verdict.findings, "E0-27", "N12-LINK-NOT-REFUSED", "findings: %s" % list(verdict.findings)[:6])
    @e0("E0-22", "RED", "N12-COMMIT-MODE-DRIFT-NOT-DETECTED", "the commit mode compares the work tree with the committed blobs and refuses a drift, an uncommitted source and a missing view")
    def test_RED_E0_22_the_commit_mode(self):
        tool = require_tool("E0-22", "N12-COMMIT-MODE-DRIFT-NOT-DETECTED")
        tree = tool.MemoryTree(dict(base_files()))
        data = tool.serialize(tool.build_manifest(tree, BASE_COMMIT, BRANCH))
        self.assertTrue(tool.evaluate(tree, data, mode="commit", committed=tool.MemoryTree(dict(base_files()))).accepted)
        verdict = tool.evaluate(tree, data, mode="commit", committed=None)
        contract(not verdict.accepted, "E0-22", "N12-COMMIT-MODE-DRIFT-NOT-DETECTED", "the commit mode accepted without a committed view")
        verdict = tool.evaluate(tree, data, mode="nonsense")
        contract(not verdict.accepted, "E0-22", "N12-COMMIT-MODE-DRIFT-NOT-DETECTED", "an unknown mode was accepted")


# ---- E: U13 ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

GUARD_NAME = "test_GUARD_U13_the_python_saved_index_and_the_csharp_fixed_request_land_together"
RED_NAME = "test_RED_U13_the_python_saved_index_and_the_csharp_fixed_request_land_together"


def red_module():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    return importlib.import_module("red_st0_stationindex_contract")


class E_U13(unittest.TestCase):
    @e0("E0-23", "RED", "U13-NOT-RETURNED-TO-GUARD", "U13 is a GUARD (never deleted, never skipped, no RED twin); its condition runs the package guard on this tree")
    def test_RED_E0_23_u13_is_a_guard(self):
        import inspect
        red = red_module()
        cls = red.Guards
        contract(hasattr(cls, GUARD_NAME) and not hasattr(cls, RED_NAME), "E0-23", "U13-NOT-RETURNED-TO-GUARD", "U13 is still the declared RED")
        fn = getattr(cls, GUARD_NAME)
        meta = fn.st0red
        self.assertEqual((meta["kind"], meta["id"]), ("GUARD", "U13"))
        self.assertFalse(getattr(fn, "__unittest_skip__", False), "never skipped")
        source = inspect.getsource(fn)
        self.assertIn("source_package", source, "the condition runs the package guard")
        self.assertIn("evaluate(", source)

    @e0("E0-24", "RED", "U13-GUARD-MEANING-UNSTATED", "the GUARD says what it means (code and package consistency) and what it does not (build, deployment, live acceptance)")
    def test_RED_E0_24_the_guard_meaning_is_stated(self):
        red = red_module()
        contract(hasattr(red.Guards, GUARD_NAME), "E0-24", "U13-GUARD-MEANING-UNSTATED", "U13 is not a GUARD yet")
        meta = getattr(red.Guards, GUARD_NAME).st0red
        text = meta["note"] + " " + meta["artifact"]
        contract("code and package consistency" in text, "E0-24", "U13-GUARD-MEANING-UNSTATED", "the note does not say 'code and package consistency'")
        contract("not a build, deployment or live-acceptance result" in text, "E0-24", "U13-GUARD-MEANING-UNSTATED", "the note does not say what the GUARD does not mean")


    @e0("E0-26", "RED", "U13-GUARD-DOES-NOT-JUDGE-THE-PACKAGE", "the U13 GUARD runs the package guard: it passes on the intact tree and FAILS when the package is inconsistent (a copy in a temporary folder)")
    def test_RED_E0_26_u13_fails_on_an_inconsistent_package(self):
        import shutil
        import tempfile
        red = red_module()
        contract(hasattr(red.Guards, GUARD_NAME), "E0-26", "U13-GUARD-DOES-NOT-JUDGE-THE-PACKAGE", "U13 is not a GUARD yet")
        require_tool("E0-26", "U13-GUARD-DOES-NOT-JUDGE-THE-PACKAGE")
        real_root = red.ROOT

        def run_guard(root):
            red.ROOT = root
            try:
                case = red.Guards(GUARD_NAME)
                result = unittest.TestResult()
                case.run(result)
                return result
            finally:
                red.ROOT = real_root

        with tempfile.TemporaryDirectory() as tmp:
            for name, data in base_files().items():
                dest = os.path.join(tmp, *name.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as handle:
                    handle.write(data)
            os.makedirs(os.path.join(tmp, "package"), exist_ok=True)
            shutil.copyfile(TOOL_PATH, os.path.join(tmp, "package", "source_package.py"))
            shutil.copyfile(MANIFEST_FILE, os.path.join(tmp, "package", "source-package-manifest.json"))
            intact = run_guard(tmp)
            self.assertTrue(intact.wasSuccessful(), "the GUARD passes on an intact copy: %s" % (intact.failures + intact.errors))
            victim = os.path.join(tmp, "package_contract.py")
            with open(victim, "ab") as handle:
                handle.write(b"# a runtime source that no longer matches its manifest\n")
            broken = run_guard(tmp)
            contract(not broken.wasSuccessful() and any("ContractViolation" in tb or "U13" in tb for _t, tb in broken.failures + broken.errors), "E0-26",
                     "U13-GUARD-DOES-NOT-JUDGE-THE-PACKAGE", "U13 passed on a package whose runtime source differs from its manifest")


# ---- F: nothing of the product changed --------------------------------------------------------------------------------------------------------------------------------------------

class F_NonRegression(unittest.TestCase):
    @e0("E0-25", "GUARD", note="every runtime source of 0b8e511 keeps its blob id; main.py and the two projects differ from 0b8e511 only by the one added contract line")
    def test_GUARD_E0_25_no_runtime_source_changed(self):
        files = base_files()
        for path, want in sorted(BASE_BLOBS.items()):
            self.assertEqual(blob_id(clean(files[path])), want, path)
        main = clean(files["main.py"])
        self.assertEqual(blob_id(main.replace(b"import package_contract\n", b"")), BASE_MAIN, "main.py differs from 0b8e511 by the contract import only")
        self.assertLessEqual(main.count(b"import package_contract\n"), 1)
        for proj, want in BASE_PROJECTS.items():
            text = clean(files[proj]).decode("utf-8")
            stripped = re.sub(r'[ \t]*<Compile Include="[^"]*PackageContract\.cs">\s*<Link>[^<]*</Link>\s*</Compile>[ \t]*\n', "", text)
            stripped = re.sub(r'[ \t]*<Compile Include="[^"]*PackageContract\.cs"><Link>[^<]*</Link></Compile>[ \t]*\n', "", stripped)
            self.assertEqual(blob_id(stripped.encode("utf-8")), want, proj + " differs from 0b8e511 by the contract compile item only")
        self.assertEqual(len(re.findall(r"^import (?!package_contract)", main.decode("utf-8"), re.M)) >= 1, True)


if __name__ == "__main__":
    unittest.main()
