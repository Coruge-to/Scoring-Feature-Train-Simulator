"""PID-D4 Legacy Jump LJX-1 (the minimal execution slice): the managed application against the Legacy jump execution (tests first, RED before the product).

What this file pins from the Python side:
  A  the Python application is NOT changed by LJX-1 (hash pins of the modules that carry the jump contract, and the 10.0 s outstanding timeout);
  A2 the Legacy Jump contract REGIONS of main.py / managed_input.py / scoring_logic.py (Phase ST-2a Commit Prep, owner decision O-1: these three files are not pinned as whole files
     any more - later phases change them for other reasons; the contract is pinned as AST regions, scoring_logic.py additionally against its blob in the formal LJX-1 commit);
  A3 the region check itself: a changed / removed / renamed / re-signatured jump region, a new undeclared jump function, a changed shutdown order and a wrong historical blob are
     detected, an unrelated change is not;
  B  the scoring start gate: an AVAIL part without `jump` refuses the start (missing-jump), an AVAIL part with `jump` does not;
  C  the command capability: a Legacy Jump Directory with REQUEST_ID only refuses both commands (command-unsupported), one with STA|LOC|REQUEST_ID (0x7) lets both pass;
  D  the real round trip on Windows: a served product plane (real named mapping, real loopback UDP port, the dedicated worker, a fake Legacy host) with the execution
     enabled; the PRODUCT client of this repository reads the real Directory and sends a real datagram; the plane executes on a Tick and sends the type 5 JUMP_COMPLETE to a
     real loopback socket of this test; the product receiver and client accept it. No BVE, no fixed port (54321 / 54322 are never bound or written to).

While the product does not exist (Stage S1) the D tests fail with [contract:serve-script-absent] (an EXPECTED RED).
"""
import ast
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import current_jump_client as cjc  # noqa: E402
import d6_rig  # noqa: E402
import dataplane_contract as contract  # noqa: E402
import ljx1_contract_regions as regions  # noqa: E402
import managed_app_directory  # noqa: E402
import managed_input  # noqa: E402
import telemetry_contract as tc  # noqa: E402
import telemetry_dataplane_receiver as receiver_module  # noqa: E402

SERVE = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Tests", "Serve-LegacyJumpExecLJX1.ps1")
DEFAULT_DLL = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "out", "TSScoringPlugin.AtsExLegacy.Telemetry.dll")
PRODUCT_DLL = os.environ.get("LEGACYJUMP_LJX1_PRODUCT_DLL") or DEFAULT_DLL
FIXED_PORTS = (54321, 54322)

PYTHON_PINS = {
    "current_jump_client.py": "C2E41A1DFA47274E527A41926D7FEBC52D070A380124BCC05C2536CA0C1F10EC",
    # Phase ST-1A (the pin moved, was 114DAC75...): telemetry_contract.py gained the word STIDX in TOKEN_KEYS["station"] (+ a comment). It does not touch the jump contract;
    # tests\test_stationindex_supply_st1a.py (class D) pins the hooks.
    # Phase SI-R2.2-S2a (the pin moved, was 792B5C6E...): telemetry_contract.py gained the word OFFTGT in TOKEN_KEYS["station"] and the six published values of the OFFTGT part in
    # telemetry_state_defaults() (+ comments). It does not touch the jump contract; the regions of main.py that name the jump contract are unchanged (tests\test_official_target_supply_s2a.py, class F).
    "telemetry_contract.py": "87A3CAA65FA9E34BACAC9E2A4FBA9425AB57BA5264BCB1F112EA202D9CCC8F32",
    "dataplane_contract.py": "53D23EA683DE8C6344932DEF5D550C0646B3B95ECC5561A3CDAF66F46D9EF27D",
    "telemetry_dataplane_receiver.py": "7E651F9E2523F035C9A15ED1AF7A23EC8D373BDAB99B7085A8E9BA26521A44E9",
    "managed_app_directory.py": "7B77DA8C4D04B32603AE7BFFAA1A74FCE07253B1BE2084ECB11EBBE5B46DCA8A",
}

# Phase ST-2a Commit Prep (owner decision O-1, 2026-10-22): main.py / managed_input.py / scoring_logic.py are no longer pinned as whole files (every phase that touched them for another
# reason - StationIndex, identity, checkpoint - broke the pin; two of the three had already moved from the LJX-1 value to "the last accepted commit"). The old values are KEPT here as
# history; the jump contract is pinned by regions (class A2) instead.
SUPERSEDED_WHOLE_FILE_PINS = {
    # was F1C9457A... at the LJX-1 commit ca58586; moved to 4D077792... by ST-1A / ST-1B (the STIDX intake, _station_index_finish)
    "main.py": {"ljx1": "F1C9457A9366084D2D53D41F46D5A2AF1A8A8BB5C0F7C72B4A9588EAFAC81B68", "last": "4D077792FDD5084C35A8253EE4E8FCA383E4CAEC7DB1ACA83F8559B1F99FB813"},
    # was 6A7B6594... at ca58586; moved to 060A958C... by ST-1B Prep (EVENT_LINE_CAPS "stidx": 24)
    "managed_input.py": {"ljx1": "6A7B6594FE626C78863ED73E09517A74839D4A0DF3DA7340E583F9E358163851", "last": "060A958CA831382282C282A17D6C38BF72EFC27D8766A325F5A57A7C2A6234A9"},
    # never moved: the CRLF form of the blob that the LJX-1 commit holds (see SCORING_LOGIC_AT_LJX1)
    "scoring_logic.py": {"ljx1": "3A790E478C0A2F10DDC9E28E905A399D736E4DF8AA3D9C646AD76B76D1611945", "last": "3A790E478C0A2F10DDC9E28E905A399D736E4DF8AA3D9C646AD76B76D1611945"},
}

# the formal LJX-1 commit and scoring_logic.py in it (read from git, never from a copy): the historical evidence
LJX1_COMMIT = "ca585868b99bedce0917ae0bb42dc1d2b6e6d3e5"
SCORING_LOGIC_AT_LJX1 = {
    "blob": "3c4731183d3b08aee8497a405d1d4f88e58c708c",
    "lf_sha256": "640CA3FB04E05C76B214A082DFFE4AEDB18956EA0ABAAD91CD4AF0C7C81E0E22",
    "crlf_sha256": "3A790E478C0A2F10DDC9E28E905A399D736E4DF8AA3D9C646AD76B76D1611945",
}

# The Legacy Jump contract of the Python side (the PID-D6 official jump path that LJX-1 relies on and does not change): which units, and how each is pinned.
#   whole   a function that is the contract as a whole (canonical AST without docstring);
#   sliced  a function (or "<module>") in which only the statements that name the contract are pinned;
#   order   the order of call names inside one function.
# TTL (5.0 s), claim and breaker (N = 3) are C# contracts of the Legacy plane (Test-LegacyJumpExecLJX1.ps1 and the DLL pin); their Python counterparts are the 10.0 s outstanding
# timeout (class A, current_jump_client.py), the cancel reasons and the shutdown order below.
JUMP_UNITS = {
    "main.py": {
        # Phase ST-3d (an INTENDED change of the jump contract): the completion is taken by the transport (_note_jump_complete) and judged by the settlement, the transaction is opened / closed in
        # three small units, the start request is planned in one; _jump_complete_acceptable is gone. Every unit that names the contract is declared (nothing is undeclared).
        "whole": ["Overlay._note_jump_complete", "Overlay._poll_jump_client", "Overlay._open_jump_transaction",
                  "Overlay._emit_jump_settled", "Overlay._finish_jump_transaction", "Overlay._jump_transaction_finish",
                  "Overlay._abort_unreleased_official_jump", "Overlay._send_jump_datagram", "Overlay._log_rejected_completion",
                  "Overlay._settle_jump_complete", "Overlay._scoring_start_plan", "Overlay.send_jump_command",
                  "_managed_jump_log",
                  # Legacy scoring LC-4b (A14, an INTENDED change of the jump contract): the Overlay answers whether the Jump group is available (the retry is refused while it is not, the HUD tick polls it)
                  "Overlay.jump_group_available"],
        "sliced": [regions.MODULE, "Overlay.__init__", "Overlay.read_udp_data", "Overlay.apply_telemetry_text", "Overlay.handle_menu_enter",
                   "Overlay._detect_and_release_fast_forward", "Overlay._advance_scoring_clock_and_score", "run_managed"],
        # contract 13.2 step 7 (the jump client is closed, its outstanding request cancelled) before 15.2 step 3 (the data plane receiver stops)
        "order": [("run_managed", ["jump_client.close", "dataplane_receiver.stop"])],
    },
    "managed_input.py": {
        "whole": ["_cancel_outstanding_jump", "scoring_input_blockers"],
        "sliced": [regions.MODULE, "generation_defaults", "discard_scoring_session", "discard_generation_state", "ManagedInputController._observe"],
        "order": [],
    },
    # scoring_logic.py is compared with its blob in the formal LJX-1 commit, not with a digest of today
    "scoring_logic.py": {
        "whole": ["begin_official_jump", "execute_retry"],
        # Legacy scoring LC-3A (an INTENDED change of the stop jerk judgement): update_stop_jerk_penalty does not judge a sample while an official jump is outstanding (it names `is_official_jumping`), so it is a declared region
        "sliced": ["evaluate_arrival", "evaluate_departure", "update_physics_and_scoring", "update_basic_braking_first_stop", "update_speed_limit_penalty", "update_stop_jerk_penalty"],
        "order": [],
    },
}

# digests of the regions (kind, SHA-256, number of jump records). Computed from the LJX-1 commit ca58586 and found IDENTICAL at 69077aa, in the ST-2a working tree and (main.py, managed_input.py)
# at ea0a3fb - except the units named in the Phase ST-3d notes below, which ST-3d changed on purpose and re-pinned in the SAME change (old value -> new value, with the purpose).
REGION_PINS = {
    "main.py": {
        "Overlay._note_jump_complete": ("whole", "4E0813095DE0203C269FE5F2A3DC1E85235DA836D53BFC63FA615E73716C91D9", 1),
        # Phase ST-3d (was 5C7202FF...): the normal mode has no client; its open transaction is released at the same 10 s deadline (current_jump_client.OUTSTANDING_TIMEOUT_S)
        "Overlay._poll_jump_client": ("whole", "752D31B04E7EA5B6BD6DA7D13D239D7444660CD754A2C70913F9996C1403EEA6", 1),
        "Overlay._open_jump_transaction": ("whole", "EB4E49E48B214801C9C8A0CE9663FD98B52FC23F55F3B61548C2E1FF77828406", 1),
        "Overlay._emit_jump_settled": ("whole", "7AB4809B8049C5D970490B897DEB34B51FEE7279A89273776D0E6C2270FF22F7", 1),
        "Overlay._finish_jump_transaction": ("whole", "B6E82E3A2C9365893598E57E3AB54606A6A227C4C37C4F6FF512AADFEA79DAA7", 1),
        "Overlay._jump_transaction_finish": ("whole", "3CFF60626FCE391D84E1A19483AE04BC144035FDCD3A4E16A9924B573003DF0E", 1),
        # Phase ST-3d (was D011C774...): also the one exit of every FAILED settlement (a verdict), closes the books of the transaction (jump-settled) and releases the pending retry
        "Overlay._abort_unreleased_official_jump": ("whole", "2FDDD061237B01664F661F22B1B8ED019E8324EB52176AE064040B43E5C0C487", 1),
        "Overlay._send_jump_datagram": ("whole", "28F6535FFD17481537E586D5F61A5D0BB2824E6CB309EF9F2D1F7D63A4DFF281", 1),
        "Overlay._log_rejected_completion": ("whole", "C5B2E6C61374F8CD15019919490069ADF03F0C8137168CAF51DAD397C1D54C83", 1),
        # Phase ST-3d (was 1709CFC1...): the settlement itself - judge_completion, the cut of the history (the ONE call of resolve_retry_history), the release, then the unchanged success body
        "Overlay._settle_jump_complete": ("whole", "7995AA5F27B35E3FDABB9FCF85F2AC6EA20D6C854475133CD8FF4919B1C9E4CC", 1),
        "Overlay._scoring_start_plan": ("whole", "1CAC50AE7FBF10311002294F0A9EE83929BA82770561AA79AA230E7DE777E74C", 1),
        "Overlay.send_jump_command": ("whole", "64A500353BD0B85B9E834D1F229191288688FAC19AFFC56C79C013F16526191C", 1),
        "_managed_jump_log": ("whole", "79C052E4112C613AE67EEE787BA19E15A2164441D18BA383057CE08F47133689", 1),
        # Legacy scoring LC-4b (A14, a NEW declared region): the Jump group availability of the Overlay (tests/test_lc4b_python_jump_state.py)
        "Overlay.jump_group_available": ("whole", "B5BDCEF607F1E6E5D7047993FFBD821311999DE954691582E0252359D6B6FCD6", 1),
        # Phase ST-3d (was 24D36E4E..., 3 records): + import jump_transaction, import jump_wire
        "<module>": ("slice", "EDC95B2B14DA2329CBCB0F76C6C34119AB82D46AB8AD4D4C18679B39719BB8BD", 5),
        # Phase ST-3d (was AF89937B..., 10 records): + self.jump_expectation = None
        "Overlay.__init__": ("slice", "7240852E3BE539E9A0B5493057188075368BFDEB189D816B33E2BB3EFE661146", 11),
        # Phase ST-3d (was 741D5BA4...): the JUMP_COMPLETE branch hands the body to _note_jump_complete; the settlement call is guarded (an exception releases the open jump)
        "Overlay.read_udp_data": ("slice", "D227ABC32AAD5F93FF1011ADC97BB444EBE7C1501D8D21F8282C1C78A9825B1C", 5),
        # Phase ST-3d (was 8DF01409..., 5 records): a scenario change closes the open transaction and releases is_official_jumping
        # Legacy scoring LC-4b (A16, was 064FF5BE...): the condition of the baseline block looks at the JUMP key of the line (a JUMP-only line is not a baseline), the 7 jump records stay (tests/test_lc4b_python_jump_state.py)
        "Overlay.apply_telemetry_text": ("slice", "F63313F69BEE4F1B1A0E719917F6F0B7BB83714036E4265DE60125AFFFE209C9", 7),
        # Phase ST-3d (was 84E656C2..., 8 records): the start request comes from _scoring_start_plan (refused before anything changes) and the start opens its transaction
        "Overlay.handle_menu_enter": ("slice", "5943298E8353AA2DEED72DEAC4BD898BADCAF87D828F8A1313DDB6DAA7559022", 3),
        "Overlay._detect_and_release_fast_forward": ("slice", "6E15C0D15405AC3D2025E2EBD501EF36EC8D1D916D56CDA25E9E1D5E7B9092E7", 1),
        "Overlay._advance_scoring_clock_and_score": ("slice", "781559CFFF388EE116614B528F018826B5A1FB0A2280C3D3CA72700C5F23779C", 2),
        # Phase ST-3d (was CC159076..., 6 records): the shutdown closes an open transaction (before the client is closed)
        "run_managed": ("slice", "7C861C443A860D2869DA2D944AC8CA542422988E0AB2E761607AE985950C5674", 7),
    },
    "managed_input.py": {
        # Phase ST-3d (was A6BBA988...): the open transaction ends with the discarded session / generation, before the client's request is cancelled
        "_cancel_outstanding_jump": ("whole", "3D6C7F18C90C8B6A9820107F1705C69DB615CC4C9A9973EADA0A1C0756E30F8B", 1),
        "scoring_input_blockers": ("whole", "DE0DDABD18416E1B8EBA119DBD79A07D7B3AFEC879513541DDF5F64738516664", 1),
        # Phase ST-3d (was 8A72CB78..., 3 records): + the cap of the final line jump-settled in EVENT_LINE_CAPS
        "<module>": ("slice", "4F5100EFED10D7262A62F471F4D3B0E0FCAA53318719AA7963CD834F7FC47B7C", 4),
        # Phase ST-3d (was EA70319D..., 9 records): + jump_expectation: None
        "generation_defaults": ("slice", "30BDFEF6909510B1AEA0AF833832BBB61E72E30D484777E81BD2C3527D2B35A6", 10),
        # Phase ST-3d (was 35BF78F1..., 2 records): + overlay.jump_expectation reset
        "discard_scoring_session": ("slice", "D8C47223B603D0E6BB275C4637729784D8DE14865988DF0B6DA8E306F8A180DE", 3),
        "discard_generation_state": ("slice", "2E51777AEEE6233FA907BBD73C25D0BD02D060A766149F6C2188CF5BA7133950", 2),
        "ManagedInputController._observe": ("slice", "8275B1616287102B6C0054FF447B9A3F4216F1D74EEB652ED56168FC57093781", 1),
    },
}

# Phase ST-2b (an INTENDED change of the jump contract, owner decision OD-B6): execute_retry takes the station from the saved StationIndex (verified by station_identity), refuses what does not
# verify, keeps the history whole and leaves a pending retry. It is the one region of scoring_logic.py that is no longer compared with the blob of the formal LJX-1 commit; its new
# canonical AST is pinned here (begin_official_jump, the other WHOLE region, and every SLICE region are still compared with the blob).
ST2B_EXECUTE_RETRY_PIN = ("whole", "9226392088B12DEF33099036F18948D627FDEA0F6F03BBB61D0B8820A44359EA", 1)          # (history: the value of ST-2b)

# Phase ST-3d (an INTENDED change of the jump contract): execute_retry builds its request BEFORE it changes anything, by the one builder of the Jump wire v2 (jump_transaction.build_jump_request),
# refuses a request the wire can not carry, and opens the transaction after the send. Its new canonical AST is pinned here; begin_official_jump, the other WHOLE region and every SLICE region are
# still compared with the blob of the formal LJX-1 commit (they are identical).
ST3D_EXECUTE_RETRY_PIN = ("whole", "E5DB2D56A0FC1A4894DD4FBDA7D7CFF63BEB4EB78E74D30FE70A860325890105", 1)          # (history: the value of ST-3d)

# Legacy scoring LC-4 / LC-4b (an INTENDED change of the jump contract): execute_retry refuses once the scoring has finished (LC-4, 'scoring-finished') and while the Jump group is unavailable (LC-4b, A14); both refusals
# come BEFORE the request is built, so no request is made and none is sent (4 + 4 added lines, no deleted line). Its new canonical AST is pinned here (it was E5DB2D56...); begin_official_jump, the other WHOLE region and
# every SLICE region are still compared with the blob of the formal LJX-1 commit (identical), except the pinned ones.
LC4B_EXECUTE_RETRY_PIN = ("whole", "9CEEFF77BE70F07889ECD1D30EA0889C155BB3CA1F97C0CE611DEC86CA523894", 1)

# Legacy scoring LC-3A (an INTENDED change of the stop jerk judgement, not of the jump contract): update_stop_jerk_penalty returns without judging while `is_official_jumping` is set (a sample taken while the world is about to be
# replaced is not a stop). At the LJX-1 commit the function names no jump word (an EMPTY slice, 0 records: the SHA-256 of the empty text); now it names `is_official_jumping` once (1 record) and is declared.
EMPTY_SLICE_PIN = ("slice", "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855", 0)
LC3A_UPDATE_STOP_JERK_PIN = ("slice", "D43FFB9C0D190C9E0574CD41C08754A1AFCA7C3EC830742C4B14CFFAD9FA8387", 1)

# Time Fix B (an INTENDED change of a scoring region, not of the jump contract): the departure range check of evaluate_departure names `is_official_retry` in its condition, and that one condition
# now reads the local margin_f / margin_b (the range kept at the arrival of an operational stop; the telemetry margin of the new target for every other stop) instead of self.bve_margin_f / _b.
# The region keeps its 6 jump records; its new digest is pinned on its own (it was C07D9550...). Every other SLICE region is still compared with the blob of the formal LJX-1 commit (identical).
TIMEFIX_B_EVALUATE_DEPARTURE_PIN = ("slice", "2D7A28AD96FF44159A25F37EC4CEAF572BB6015F8F2AFD78B5F414E4C24A45F0", 6)

# Time Fix B2 (an INTENDED change of the same scoring region, not of the jump contract): a LATCHED operational stop (written at its stop, tests/test_timefix_b2_operational_stop_contract.py) is completed by its record
# before the range check is reached, and consumes the retry flag like the range path does: ONE more statement that names `is_official_retry` (6 -> 7 jump records). The new digest is pinned on its own (it was
# 2D7A28AD...); every other SLICE region is still compared with the blob of the formal LJX-1 commit (identical).
TIMEFIX_B2_EVALUATE_DEPARTURE_PIN = ("slice", "CEA6E1FA983E7E338A5EF4638B945C9EE1A357F5F483624D7FFF39416F43384E", 7)

# Time Fix B3 (an INTENDED change of the same scoring region, not of the jump contract): the departure scoring of a timed non-pass stop is not run for an operational stop whose departure is seen while an official
# jump is outstanding (the telemetry then describes the world the jump is about to replace: tests/test_timefix_b3_zero_speed_contract.py Z-T17). ONE more statement names `is_official_jumping` (7 -> 8 jump records). The new
# digest is pinned on its own (it was CEA6E1FA...); every other SLICE region is still compared with the blob of the formal LJX-1 commit (identical).
TIMEFIX_B3_EVALUATE_DEPARTURE_PIN = ("slice", "E2F27FF844D94A4D24756620B2F1379505F9DF5453F7DF560943653B9BA0EFAF", 8)

# Time Fix B3 (an INTENDED change of the same kind): the arrival of an operational stop (update_physics_and_scoring) is not formed while an official jump is outstanding - the telemetry then describes the world the jump
# is about to replace (old position, old clock), so it must not become the stop of the retried attempt (tests/test_timefix_b3_zero_speed_contract.py Z-T16b / Z-T18 / Z-T19). ONE more statement names `is_official_jumping`
# (24 -> 25 jump records). The new digest is pinned on its own (it was 4843D2F5...); every other SLICE region is still compared with the blob of the formal LJX-1 commit (identical).
# Close-range departure reset (a scoring region, not a change of the jump contract): the target switch evaluates the close pair only when no official jump is outstanding (ONE more statement names
# `is_official_jumping`, 25 -> 26 jump records; the new functions of the close-range reset name no jump word), and the operational-arrival condition (which already names it) gains the pending gate.
# The new digest is pinned on its own (it was 5EBC117E...).
TIMEFIX_B3_UPDATE_PHYSICS_PIN = ("slice", "76263B7C83BB397626D63F1678A78EC0A52A482CA1D63631CA7C8F2D7B615D79", 26)

STATIONS = [0.0, 1000.0, 2000.0, 3000.0]
SCORING_TOKENS = ["time", "speed", "loc", "station", "door", "handle", "brake_type", "brake_cab", "prates"]


def row(tokens):
    return "SCENARIO_ID:7,%s,SPEED:0.0,TIME:36000000,LOCATION:100.0" % tc.format_avail(tokens)


class A_ThePythonSideIsUnchanged(unittest.TestCase):
    def test_the_modules_that_carry_the_jump_contract_are_byte_identical_to_the_start_of_ljx1(self):
        # (Phase ST-2a Commit Prep: the five modules of PYTHON_PINS that no later phase touched. main.py / managed_input.py / scoring_logic.py are pinned by REGION in class A2.)
        self.assertEqual(sorted(PYTHON_PINS), ["current_jump_client.py", "dataplane_contract.py", "managed_app_directory.py", "telemetry_contract.py", "telemetry_dataplane_receiver.py"])
        for name, expected in sorted(PYTHON_PINS.items()):
            with open(os.path.join(REPO, name), "rb") as stream:
                actual = hashlib.sha256(stream.read()).hexdigest().upper()
            self.assertEqual(actual, expected, name)

    def test_the_outstanding_timeout_is_ten_seconds_and_the_legacy_ttl_is_below_it(self):
        self.assertEqual(cjc.OUTSTANDING_TIMEOUT_S, 10.0)
        self.assertLess(5.0, cjc.OUTSTANDING_TIMEOUT_S)


def read_source(name):
    with open(os.path.join(REPO, name), "rb") as stream:
        return stream.read()


def unit_problems(name, source):
    """What differs from the pinned regions of main.py / managed_input.py in `source` (bytes, text or ast.Module): [] = the Legacy Jump contract is as it was at LJX-1."""
    spec = JUMP_UNITS[name]
    actual, undeclared = regions.region_digests(source, spec["whole"], spec["sliced"])
    problems = []
    for unit in spec["whole"] + spec["sliced"]:
        if actual[unit] is None:
            problems.append("%s: %s is missing" % (name, unit))
        elif actual[unit] != REGION_PINS[name][unit]:
            problems.append("%s: %s differs from the LJX-1 pin (%s %s, %d records; pinned %s %s, %d)" % ((name, unit) + actual[unit] + REGION_PINS[name][unit]))
    for unit in undeclared:
        problems.append("%s: %s names the jump contract but is not a declared region" % (name, unit))
    for unit, wanted in spec["order"]:
        if regions.sequence_holds(source, unit, wanted) is not True:
            problems.append("%s: %s does not call %s in that order" % (name, unit, " -> ".join(wanted)))
    return problems


class A2_TheLegacyJumpContractRegionsOfThePythonSide(unittest.TestCase):
    """Phase ST-2a Commit Prep (owner decision O-1): the contract regions of main.py / managed_input.py are those of LJX-1 (identical at ca58586, 69077aa and in the ST-2a
    tree), and scoring_logic.py is compared with its blob in the formal LJX-1 commit. A change for another reason (StationIndex, identity, checkpoint) does not touch them."""

    def test_the_jump_regions_of_main_py_are_those_of_ljx1(self):
        self.assertEqual(unit_problems("main.py", read_source("main.py")), [])

    def test_the_jump_regions_of_managed_input_py_are_those_of_ljx1(self):
        self.assertEqual(unit_problems("managed_input.py", read_source("managed_input.py")), [])

    def test_no_function_of_scoring_logic_py_names_the_jump_contract_outside_the_declared_regions(self):
        spec = JUMP_UNITS["scoring_logic.py"]
        _, undeclared = regions.region_digests(read_source("scoring_logic.py"), spec["whole"], spec["sliced"])
        self.assertEqual(undeclared, [])

    def test_scoring_logic_py_in_the_formal_ljx1_commit_is_the_pinned_history(self):
        problems = regions.historical_blob_problems(REPO, LJX1_COMMIT, "scoring_logic.py", SCORING_LOGIC_AT_LJX1["blob"], SCORING_LOGIC_AT_LJX1["lf_sha256"],
                                                    SCORING_LOGIC_AT_LJX1["crlf_sha256"])
        if problems is None:
            self.skipTest("the LJX-1 commit / git is not available (INCONCLUSIVE)")
        self.assertEqual(problems, [])

    def test_the_jump_regions_of_scoring_logic_py_are_those_of_the_ljx1_blob(self):
        blob = regions.git_blob(REPO, LJX1_COMMIT, "scoring_logic.py")
        if blob is None:
            self.skipTest("the LJX-1 commit / git is not available (INCONCLUSIVE)")
        spec = JUMP_UNITS["scoring_logic.py"]
        then, then_undeclared = regions.region_digests(blob, spec["whole"], spec["sliced"])
        now, now_undeclared = regions.region_digests(read_source("scoring_logic.py"), spec["whole"], spec["sliced"])
        self.assertEqual(then_undeclared, [])
        self.assertTrue(all(value is not None for value in then.values()), then)
        self.assertEqual(now.pop("execute_retry"), LC4B_EXECUTE_RETRY_PIN)           # Phase ST-2b / ST-3d / LC-4 / LC-4b: the intended changes, pinned on their own (the ST-2b and ST-3d values stay above as history)
        then.pop("execute_retry")
        self.assertEqual(then.pop("update_stop_jerk_penalty"), EMPTY_SLICE_PIN)      # Legacy scoring LC-3A: at LJX-1 the function names no jump word ...
        self.assertEqual(now.pop("update_stop_jerk_penalty"), LC3A_UPDATE_STOP_JERK_PIN)   # ... now it names `is_official_jumping` once: the intended change, pinned on its own
        self.assertEqual(now.pop("evaluate_departure"), TIMEFIX_B3_EVALUATE_DEPARTURE_PIN)     # Time Fix B / B2 / B3: the intended changes, pinned on their own (the Time Fix B and B2 values stay above as history)
        then.pop("evaluate_departure")
        self.assertEqual(now.pop("update_physics_and_scoring"), TIMEFIX_B3_UPDATE_PHYSICS_PIN)   # Time Fix B3: the intended change, pinned on its own
        then.pop("update_physics_and_scoring")
        self.assertEqual(now, then)
        self.assertEqual(now_undeclared, [])

    def test_the_superseded_whole_file_pins_stay_history_and_are_not_active(self):
        self.assertEqual(sorted(SUPERSEDED_WHOLE_FILE_PINS), ["main.py", "managed_input.py", "scoring_logic.py"])
        for name in SUPERSEDED_WHOLE_FILE_PINS:
            self.assertNotIn(name, PYTHON_PINS)
        self.assertEqual(SUPERSEDED_WHOLE_FILE_PINS["scoring_logic.py"]["ljx1"], SCORING_LOGIC_AT_LJX1["crlf_sha256"])
        self.assertEqual(set(REGION_PINS), {"main.py", "managed_input.py"})
        for name, pins in REGION_PINS.items():
            self.assertEqual(set(pins), set(JUMP_UNITS[name]["whole"]) | set(JUMP_UNITS[name]["sliced"]))


class A3_TheRegionCheckDetectsAJumpChange(unittest.TestCase):
    """The check of class A2 itself, on the real sources changed in memory: a change of the Legacy Jump contract is detected, an unrelated change is not."""
    NAMES = ("main.py", "managed_input.py")
    sources = {}

    @classmethod
    def setUpClass(cls):
        for name in cls.NAMES:
            cls.sources[name] = read_source(name).decode("utf-8-sig")
            assert unit_problems(name, cls.sources[name]) == [], name

    # -- mutation helpers (each works on a freshly parsed tree) ----------------------------------------------------------------------------------------------
    def tree(self, name):
        return ast.parse(self.sources[name])

    @staticmethod
    def owners(tree, unit):
        """The nodes whose statement lists make up a unit: the module and its classes (not the functions) for the module level, else the function and everything nested in it."""
        if unit == regions.MODULE:
            return [tree] + [n for n in tree.body if isinstance(n, ast.ClassDef)]
        return list(ast.walk(regions.find_units(tree)[unit]))

    @classmethod
    def jump_statements(cls, tree, unit):
        found = []
        for owner in cls.owners(tree, unit):
            for field in ("body", "orelse", "finalbody"):
                statements = getattr(owner, field, None)
                if isinstance(statements, list):
                    for statement in statements:
                        head = regions._compound(statement)
                        if head is None and regions._simple_atoms(statement, ()):
                            found.append((statements, statement))
                        elif head is not None and head[0] in ("if", "while") and regions.JUMP_WORDS.search(head[1]):
                            found.append((statements, statement))          # a condition that names the contract (its header is a record of its own)
        return found

    @classmethod
    def jump_target(cls, statement):
        """The part of a jump statement that the mutation changes: the condition of an if / while, else the statement."""
        return statement.test if isinstance(statement, (ast.If, ast.While)) else statement

    @staticmethod
    def rename_first_jump_word(statement, any_word=False):
        """Appends "_x" to the first identifier / attribute / string / import name that names the jump contract (any_word: the first one at all)."""
        def hit(text):
            return any_word or regions.JUMP_WORDS.search(text)
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and hit(node.id):
                node.id += "_x"
                return True
            if isinstance(node, ast.Attribute) and hit(node.attr):
                node.attr += "_x"
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and hit(node.value):
                node.value += "_x"
                return True
            if isinstance(node, ast.alias) and hit(node.name):
                node.name += "_x"
                return True
        return False

    def problems(self, name, tree):
        return unit_problems(name, tree)

    @staticmethod
    def spec_units(name):
        return JUMP_UNITS[name]["whole"], JUMP_UNITS[name]["sliced"]

    # -- the contract changes that must be detected ------------------------------------------------------------------------------------------------------------
    def test_a_removed_or_renamed_region_function_is_detected(self):
        for name in self.NAMES:
            whole, sliced = self.spec_units(name)
            for unit in [u for u in whole + sliced if u != regions.MODULE]:
                tree = self.tree(name)
                node = regions.find_units(tree)[unit]
                node.name += "_renamed"
                self.assertTrue(any(unit + " is missing" in p for p in self.problems(name, tree)), (name, unit, "renamed"))
                tree = self.tree(name)
                node = regions.find_units(tree)[unit]
                for owner in ast.walk(tree):
                    if isinstance(owner, (ast.Module, ast.ClassDef)) and node in owner.body:
                        owner.body.remove(node)
                        break
                self.assertTrue(any(unit + " is missing" in p for p in self.problems(name, tree)), (name, unit, "removed"))

    def test_a_changed_signature_of_a_whole_region_function_is_detected(self):
        for name in self.NAMES:
            for unit in self.spec_units(name)[0]:
                tree = self.tree(name)
                regions.find_units(tree)[unit].args.args.append(ast.arg(arg="extra_argument"))
                self.assertTrue(any(unit + " differs" in p for p in self.problems(name, tree)), (name, unit))

    def test_a_removed_or_changed_jump_statement_of_a_region_is_detected(self):
        for name in self.NAMES:
            for unit in self.spec_units(name)[1]:
                tree = self.tree(name)
                statements, statement = self.jump_statements(tree, unit)[0]
                statements.remove(statement)
                if not statements:
                    statements.append(ast.Pass())
                self.assertTrue(any(unit + " differs" in p for p in self.problems(name, tree)), (name, unit, "removed"))
                tree = self.tree(name)
                self.assertTrue(self.rename_first_jump_word(self.jump_target(self.jump_statements(tree, unit)[0][1])), (name, unit))
                self.assertTrue(any(unit + " differs" in p for p in self.problems(name, tree)), (name, unit, "changed"))

    def test_a_changed_or_emptied_whole_region_function_is_detected(self):
        for name in self.NAMES:
            for unit in self.spec_units(name)[0]:
                tree = self.tree(name)
                node = regions.find_units(tree)[unit]
                real = [s for s in node.body if not regions._is_docstring(s)]
                node.body = [ast.Pass()] + real[1:]
                self.assertTrue(any(unit + " differs" in p for p in self.problems(name, tree)), (name, unit))
                tree = self.tree(name)
                node = regions.find_units(tree)[unit]
                self.assertTrue(any(self.rename_first_jump_word(s, any_word=True) for s in node.body if not regions._is_docstring(s)), (name, unit))
                self.assertTrue(any(unit + " differs" in p for p in self.problems(name, tree)), (name, unit, "word"))

    def test_a_new_function_that_names_the_jump_contract_is_detected(self):
        for name in self.NAMES:
            tree = self.tree(name)
            tree.body.append(ast.parse("def brand_new_helper(self):\n    self.is_official_jumping = True\n").body[0])
            self.assertTrue(any("brand_new_helper names the jump contract" in p for p in self.problems(name, tree)), name)

    def test_a_changed_shutdown_order_is_detected(self):
        tree = self.tree("main.py")
        unit = regions.find_units(tree)["run_managed"]
        removed = False
        for owner in ast.walk(unit):
            for field in ("body", "orelse", "finalbody"):
                statements = getattr(owner, field, None)
                if isinstance(statements, list):
                    for statement in statements:
                        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and regions.call_names(statement) == ["jump_client.close"]:
                            statements.remove(statement)
                            removed = True
                            break
        self.assertTrue(removed)
        self.assertTrue(any("does not call jump_client.close -> dataplane_receiver.stop" in p for p in self.problems("main.py", tree)))
        reversed_order = "def run_managed():\n    dataplane_receiver.stop()\n    jump_client.close()\n"
        self.assertFalse(regions.sequence_holds(reversed_order, "run_managed", ["jump_client.close", "dataplane_receiver.stop"]))
        self.assertTrue(regions.sequence_holds(reversed_order, "run_managed", ["dataplane_receiver.stop", "jump_client.close"]))

    def test_a_wrong_historical_blob_is_detected(self):
        flipped = SCORING_LOGIC_AT_LJX1["blob"][:-1] + ("0" if SCORING_LOGIC_AT_LJX1["blob"][-1] != "0" else "1")
        problems = regions.historical_blob_problems(REPO, LJX1_COMMIT, "scoring_logic.py", flipped, SCORING_LOGIC_AT_LJX1["lf_sha256"], SCORING_LOGIC_AT_LJX1["crlf_sha256"])
        if problems is None:
            self.skipTest("the LJX-1 commit / git is not available (INCONCLUSIVE)")
        self.assertEqual(len(problems), 1)
        self.assertIn("blob id", problems[0])
        other = SCORING_LOGIC_AT_LJX1["lf_sha256"][:-1] + ("0" if SCORING_LOGIC_AT_LJX1["lf_sha256"][-1] != "0" else "1")
        problems = regions.historical_blob_problems(REPO, LJX1_COMMIT, "scoring_logic.py", SCORING_LOGIC_AT_LJX1["blob"], other, SCORING_LOGIC_AT_LJX1["crlf_sha256"])
        self.assertEqual(len(problems), 1)
        self.assertIsNone(regions.historical_blob_problems(REPO, "0" * 40, "scoring_logic.py", flipped, other, other))

    # -- the changes that must NOT be detected -----------------------------------------------------------------------------------------------------------------
    def test_an_unrelated_statement_in_any_sliced_unit_is_not_detected(self):
        # (a WHOLE region is the contract as a whole: any statement in it is a change, see the tests above)
        for name in self.NAMES:
            whole, sliced = self.spec_units(name)
            for unit in sliced:
                tree = self.tree(name)
                marker = ast.parse("unrelated_station_identity_marker = 1").body[0]
                if unit == regions.MODULE:
                    tree.body.insert(0, marker)
                else:
                    node = regions.find_units(tree)[unit]
                    node.body.insert(1 if node.body and regions._is_docstring(node.body[0]) else 0, marker)
                self.assertEqual(self.problems(name, tree), [], (name, unit))

    def test_a_new_unrelated_function_and_a_changed_docstring_are_not_detected(self):
        for name in self.NAMES:
            tree = self.tree(name)
            tree.body.append(ast.parse("def brand_new_station_helper(self):\n    return 1\n").body[0])
            for node in regions.find_units(tree).values():
                if node.body and regions._is_docstring(node.body[0]):
                    node.body[0].value.value += " (edited documentation)"
            self.assertEqual(self.problems(name, tree), [], name)

    def test_an_unrelated_key_in_generation_defaults_and_the_kept_set_is_not_detected(self):
        tree = self.tree("managed_input.py")
        edited = 0
        for node in ast.walk(regions.find_units(tree)["generation_defaults"]):
            if isinstance(node, ast.Dict):
                node.keys.append(ast.Constant("station_extra_key"))
                node.values.append(ast.Constant(-1))
                edited += 1
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "KEPT_ACROSS_GENERATIONS" for t in node.targets):
                for inner in ast.walk(node.value):
                    if isinstance(inner, ast.Set):
                        inner.elts.append(ast.Constant("station_extra_kept"))
                        edited += 1
        self.assertGreaterEqual(edited, 2)
        self.assertEqual(self.problems("managed_input.py", tree), [])


class B_TheScoringStartGate(unittest.TestCase):
    def test_a_row_without_jump_refuses_the_start_with_missing_jump(self):
        line = tc.parse_telemetry(row(SCORING_TOKENS))
        self.assertTrue(line.valid)
        self.assertEqual(managed_input.scoring_input_blockers(line.availability, "Ecb", True), ["missing-jump"])

    def test_a_row_with_jump_does_not(self):
        line = tc.parse_telemetry(row(SCORING_TOKENS + ["jump"]))
        self.assertTrue(line.valid)
        self.assertEqual(managed_input.scoring_input_blockers(line.availability, "Ecb", True), [])

    def test_jump_is_a_known_token_with_its_key_and_its_completion(self):
        self.assertIn("jump", tc.KNOWN_TOKENS)
        self.assertEqual(tc.TOKEN_KEYS["jump"], ("JUMP", "JUMP_COMPLETE"))


class C_TheCommandCapability(unittest.TestCase):
    PID = 4242

    def client(self, caps):
        directory = d6_rig.FakeJumpDirectory(self.PID, name=contract.legacy_jump_name(self.PID), caps=caps)
        sent = []
        client = cjc.CurrentJumpClient(self.PID, "0123456789abcdef0123456789abcdef", 777, lambda data, port: sent.append(data) or len(data), source=directory)
        return client, sent

    def test_request_id_only_refuses_both_commands(self):
        client, sent = self.client(contract.JUMP_CAP_REQUEST_ID)
        self.assertIsNone(client.send("JUMP_STA_TIME:1:36000000"))
        self.assertEqual(client.last_failure, "send-refused:command-unsupported")
        self.assertIsNone(client.send("JUMP_LOC_TIME:1.5:36000000"))
        self.assertEqual(client.last_failure, "send-refused:command-unsupported")
        self.assertEqual(sent, [])

    def test_the_full_capability_set_lets_both_commands_through(self):
        client, sent = self.client(contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME | contract.JUMP_CAP_REQUEST_ID)
        self.assertEqual(contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME | contract.JUMP_CAP_REQUEST_ID, 7)
        self.assertIsNotNone(client.send("JUMP_STA_TIME:1:36000000"))
        self.assertIsNotNone(client.send("JUMP_LOC_TIME:1.5:36000000"))
        self.assertEqual(len(sent), 2)


class CountingWin32Source(object):
    def __init__(self):
        self.real = managed_app_directory.Win32DirectorySource(contract.DIRECTORY_SIZE)

    @property
    def is_open(self):
        return self.real.is_open

    def open(self, name):
        return self.real.open(name)

    def read(self):
        return self.real.read()

    def close(self):
        self.real.close()


class ServedPlane(object):
    """One PowerShell process that serves a product plane (execution enabled or not) on a synthetic BVE PID; commands and replies are files of a control directory."""

    def __init__(self, execution, instance, app_pid, telemetry_port, telemetry_generation, telemetry_token):
        self.dir = tempfile.mkdtemp(prefix="tssl1-")
        self.n = 0
        self.error = None
        self.ready = None
        if not os.path.isfile(SERVE):
            self.error = {"kind": "serve-script-absent", "code": "serve-script-absent", "text": "Serve-LegacyJumpExecLJX1.ps1 does not exist yet"}
            return
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SERVE, "-ControlDir", self.dir, "-ProductDll", PRODUCT_DLL, "-TimeoutSec", "240",
                "-Instance", instance, "-AppPid", str(app_pid), "-TelemetryPort", str(telemetry_port), "-TelemetryGeneration", str(telemetry_generation),
                "-TelemetryTokenHex", telemetry_token.hex()]
        if execution:
            args.append("-Exec")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.time() + 150
        ready = os.path.join(self.dir, "ready.json")
        err = os.path.join(self.dir, "error.json")
        while time.time() < deadline:
            loaded = self._load(ready)
            if loaded is not None:
                self.ready = loaded
                return
            loaded = self._load(err)
            if loaded is not None:
                self.error = loaded
                return
            if self.proc.poll() is not None and not os.path.exists(ready) and not os.path.exists(err):
                self.error = {"kind": "script", "code": "", "text": "the serve script ended with exit code %s without a word" % self.proc.returncode}
                return
            time.sleep(0.1)
        self.error = {"kind": "script", "code": "", "text": "the serve script did not become ready in time"}

    @staticmethod
    def _load(path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def command(self, word, timeout=30.0):
        self.n += 1
        name = "%04d" % self.n
        path = os.path.join(self.dir, "cmd-%s.txt" % name)
        with open(path + ".tmp", "w", encoding="ascii") as handle:
            handle.write(word)
        os.replace(path + ".tmp", path)
        reply = os.path.join(self.dir, "reply-%s.json" % name)
        deadline = time.time() + timeout
        while time.time() < deadline:
            loaded = self._load(reply)
            if loaded is not None:
                return loaded
            time.sleep(0.02)
        raise AssertionError("no reply to %r" % word)

    def close(self):
        try:
            if self.error is None and self.proc.poll() is None:
                try:
                    self.command("finish", 20.0)
                except Exception:
                    pass
            if self.error is None and self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=20)
                except Exception:
                    self.proc.kill()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


@unittest.skipUnless(os.name == "nt", "needs Windows named mappings")
class D_TheServedPlane(unittest.TestCase):
    INSTANCE = "0123456789abcdef0123456789abcdef"
    APP_PID = 8888
    TEL_GEN = 5
    TEL_TOKEN = bytes(range(50, 66))

    def setUp(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(5.0)
        self.port = self.sock.getsockname()[1]
        self.assertNotIn(self.port, FIXED_PORTS)
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        self.sock.close()

    def serve(self, execution):
        server = ServedPlane(execution, self.INSTANCE, self.APP_PID, self.port, self.TEL_GEN, self.TEL_TOKEN)
        self.servers.append(server)
        if server.error is not None:
            self.fail("[contract:%s] %s" % (server.error.get("code") or server.error.get("kind"), server.error.get("text")))
        return server

    def client_for(self, server):
        pid = server.ready["bve_pid"]
        sent = []

        def send(data, port):
            self.assertNotIn(port, FIXED_PORTS)
            sent.append(data)
            out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                return out.sendto(data, ("127.0.0.1", port))
            finally:
                out.close()

        client = cjc.CurrentJumpClient(pid, self.INSTANCE, self.APP_PID, send, source=CountingWin32Source())
        return client, pid

    def completion(self, pid):
        datagram, _addr = self.sock.recvfrom(65535)
        receiver = receiver_module.TelemetryDataPlaneReceiver(pid, self.INSTANCE, self.TEL_GEN, self.TEL_TOKEN)
        payload = receiver.accept(datagram)
        self.assertIsNotNone(payload, receiver.reasons)
        return receiver, payload.decode("utf-8")

    def test_the_execution_build_publishes_the_full_capability_set(self):
        server = self.serve(True)
        self.assertEqual(server.ready["caps"], 7)
        client, pid = self.client_for(server)
        snapshot, reason = client._read_directory()
        self.assertIsNone(reason)
        self.assertEqual(snapshot["capabilities"], 7)
        self.assertEqual(snapshot["state"] & (contract.PUBLISHED | contract.READY), contract.PUBLISHED | contract.READY)

    def test_the_default_build_still_refuses_the_command(self):
        server = self.serve(False)
        self.assertEqual(server.ready["caps"], 4)
        client, _pid = self.client_for(server)
        self.assertIsNone(client.send("JUMP_STA_TIME:1:36000000"))
        self.assertEqual(client.last_failure, "send-refused:command-unsupported")

    def test_a_station_jump_round_trip_with_the_product_client_and_receiver(self):
        server = self.serve(True)
        client, pid = self.client_for(server)
        rid = client.send("JUMP_STA_TIME:2:36100000")
        self.assertIsNotNone(rid, client.last_failure)
        reply = server.command("tick")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["host"], ["MoveToStation(2)", "SetClockMs(36100000)"])
        receiver, text = self.completion(pid)
        parts = text.split(":")
        self.assertEqual(parts[0:2], ["JUMP_COMPLETE", "STA"])
        self.assertEqual(int(parts[2]), 2)
        self.assertLess(abs(float(parts[3]) - STATIONS[2]), 0.01)
        self.assertEqual(int(parts[4]), 36100000)
        self.assertEqual(int(parts[5]), reply["jump_count"])
        self.assertEqual(receiver.last_request_id, rid)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_OK)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_DUPLICATE)

    def test_a_location_jump_round_trip_with_the_product_client_and_receiver(self):
        server = self.serve(True)
        client, pid = self.client_for(server)
        rid = client.send("JUMP_LOC_TIME:1234.5:36200000")
        self.assertIsNotNone(rid, client.last_failure)
        reply = server.command("tick")
        self.assertEqual(reply["host"], ["MoveToLocation(1234.5,36200000)", "SetClockMs(36200000)"])
        receiver, text = self.completion(pid)
        parts = text.split(":")
        self.assertEqual(parts[0:2], ["JUMP_COMPLETE", "LOC"])
        self.assertEqual(int(parts[2]), -1)
        self.assertLess(abs(float(parts[3]) - 1234.5), 0.01)
        self.assertEqual(receiver.last_request_id, rid)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_OK)

    def test_a_completion_after_the_client_cancelled_is_stale(self):
        server = self.serve(True)
        client, pid = self.client_for(server)
        rid = client.send("JUMP_STA_TIME:1:36000000")
        self.assertIsNotNone(rid, client.last_failure)
        client.cancel("scoring-aborted")
        server.command("tick")
        receiver, _text = self.completion(pid)
        self.assertEqual(receiver.last_request_id, rid)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_STALE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
