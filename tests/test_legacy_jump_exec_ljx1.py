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
    "telemetry_contract.py": "792B5C6E1D6BE9181088B0020120B2A22A98AABD322A0154B44E9F6FCDBE6C71",
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
        "whole": ["Overlay._jump_complete_acceptable", "Overlay._poll_jump_client", "Overlay._abort_unreleased_official_jump", "Overlay._send_jump_datagram",
                  "Overlay._settle_jump_complete", "Overlay.send_jump_command", "_managed_jump_log"],
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
        "sliced": ["evaluate_arrival", "evaluate_departure", "update_physics_and_scoring", "update_basic_braking_first_stop", "update_speed_limit_penalty"],
        "order": [],
    },
}

# digests of the regions: computed from the LJX-1 commit ca58586 and found IDENTICAL at 69077aa and in the ST-2a working tree (kind, SHA-256, number of jump records)
REGION_PINS = {
    "main.py": {
        "Overlay._jump_complete_acceptable": ("whole", "FEFB3BD73C666438BB4A159B5DC1FF95A966AB9BE0D31904B528DCF78429A58B", 1),
        "Overlay._poll_jump_client": ("whole", "5C7202FFAA49F134AE375EFFCF050227FB852EFFEBB1A49F33DC7D9810A9480C", 1),
        "Overlay._abort_unreleased_official_jump": ("whole", "D011C7748AF1E6B91BFD039EDD4F995A7E409AD3AE91E0B1A388221C97404CE2", 1),
        "Overlay._send_jump_datagram": ("whole", "28F6535FFD17481537E586D5F61A5D0BB2824E6CB309EF9F2D1F7D63A4DFF281", 1),
        "Overlay._settle_jump_complete": ("whole", "1709CFC14771A488F3521D0F445172A5EE145A1723102C1520F9FCF46ECF4379", 1),
        "Overlay.send_jump_command": ("whole", "64A500353BD0B85B9E834D1F229191288688FAC19AFFC56C79C013F16526191C", 1),
        "_managed_jump_log": ("whole", "79C052E4112C613AE67EEE787BA19E15A2164441D18BA383057CE08F47133689", 1),
        "<module>": ("slice", "24D36E4E27FAA4BE0FD9DDCC9B61FFD2498C1273325194B51BD906220EE0A41B", 3),
        "Overlay.__init__": ("slice", "AF89937BD6344F881A817489A79B4E0C5EF5189C68ED4A3C41C701BCC61E854F", 10),
        "Overlay.read_udp_data": ("slice", "741D5BA4388B552DB6ACB4FCCF5B906CA26985EAED004AAA4A7FD183AEF6F5AF", 5),
        "Overlay.apply_telemetry_text": ("slice", "8DF014098D3DBC5016935829C152E25E2B897B128195751B39A02C503CD977DB", 5),
        # Phase ST-2b (an INTENDED change of the jump contract, owner decision OD-B6): the retry call site became `result = execute_retry(...)` followed by the count of an accepted retry only
        # and the restore of the BVE resume flag of a refused one (was 73F4E0A3... : `execute_retry(...)` followed by the unconditional `+= 1`); still 8 jump records
        "Overlay.handle_menu_enter": ("slice", "84E656C2C28CECB0D1DA14F55C8FAB94C79372BC43AD4327050B0697BF0C4405", 8),
        "Overlay._detect_and_release_fast_forward": ("slice", "6E15C0D15405AC3D2025E2EBD501EF36EC8D1D916D56CDA25E9E1D5E7B9092E7", 1),
        "Overlay._advance_scoring_clock_and_score": ("slice", "781559CFFF388EE116614B528F018826B5A1FB0A2280C3D3CA72700C5F23779C", 2),
        "run_managed": ("slice", "CC1590768A62BA11C05F021909315D103B5DC2A4C47AA8F4ECC36EA4F7B6D4B7", 6),
    },
    "managed_input.py": {
        "_cancel_outstanding_jump": ("whole", "A6BBA9887F4AE34FC40975FB1506710883D6FC5E355EF289CF785699D9F2E1B1", 1),
        "scoring_input_blockers": ("whole", "DE0DDABD18416E1B8EBA119DBD79A07D7B3AFEC879513541DDF5F64738516664", 1),
        "<module>": ("slice", "8A72CB7864A02D5E368C839D20EA55846BBB8072975E619BB01BD82FF0729698", 3),
        "generation_defaults": ("slice", "EA70319D1221C33861F074C2DCB20B4735F774FF0C3C4DF70B48CA43CB7A329D", 9),
        "discard_scoring_session": ("slice", "35BF78F12127D75E2FC7A20206133FAAA3069B9E92B463192A5148ECD489AE3E", 2),
        "discard_generation_state": ("slice", "2E51777AEEE6233FA907BBD73C25D0BD02D060A766149F6C2188CF5BA7133950", 2),
        "ManagedInputController._observe": ("slice", "8275B1616287102B6C0054FF447B9A3F4216F1D74EEB652ED56168FC57093781", 1),
    },
}

# Phase ST-2b (an INTENDED change of the jump contract, owner decision OD-B6): execute_retry takes the station from the saved StationIndex (verified by station_identity), refuses what does not
# verify, keeps the history whole and leaves a pending retry. It is the one region of scoring_logic.py that is no longer compared with the blob of the formal LJX-1 commit; its new
# canonical AST is pinned here (begin_official_jump, the other WHOLE region, and every SLICE region are still compared with the blob).
ST2B_EXECUTE_RETRY_PIN = ("whole", "9226392088B12DEF33099036F18948D627FDEA0F6F03BBB61D0B8820A44359EA", 1)

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
        self.assertEqual(now.pop("execute_retry"), ST2B_EXECUTE_RETRY_PIN)           # Phase ST-2b: the intended change, pinned on its own
        then.pop("execute_retry")
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
