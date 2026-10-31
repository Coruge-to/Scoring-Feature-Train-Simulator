"""Pseudo-turnback STATIC pins (no Qt, no scene): what must stay true of the source however the feature grows.
  * the pair is recognised from the StationIndex and the PairSet only: no door, signal, distance, name or position identifier in the product functions of the feature;
  * ONE call of the qualification in the scoring; no wall clock; no search loop over the stations;
  * O1 is not duplicated: no anchor / pending / close-range code of the feature's own;
  * the start-station rule: the A of a pair and the B of the final pair are not selectable (pure rule; the menu wiring is Stage TB-D)."""
import ast
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pseudo_turnback_contract as C  # noqa: E402
import pseudo_turnback_machine as M  # noqa: E402

FEATURE_FUNCTIONS = ("is_arrival_special_popup", "turnback_machine_of", "turnback_pair_a_of", "turnback_arrival_begin", "turnback_arrival_scored", "turnback_display_update", "create_turnback_b_checkpoint")
FORBIDDEN_WORDS = ("door", "signal", "distance", "nearest", "closest", "proximity", "monotonic", "wall", "perf_counter", "datetime")
NO_LOOP_FUNCTIONS = ("turnback_machine_of", "turnback_pair_a_of", "turnback_arrival_begin", "create_turnback_b_checkpoint")


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def feature_nodes():
    src = source("scoring_logic.py")
    tree = ast.parse(src)
    found = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in FEATURE_FUNCTIONS}
    return src, found


class A_ProductFunctions(unittest.TestCase):
    def test_every_feature_function_exists(self):
        _src, found = feature_nodes()
        self.assertEqual(sorted(found), sorted(FEATURE_FUNCTIONS))

    def test_no_door_signal_distance_nearest_or_clock_identifier(self):
        _src, found = feature_nodes()
        for name, fn in found.items():
            idents = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            called = {getattr(n.func, "id", getattr(n.func, "attr", None)) for n in ast.walk(fn) if isinstance(n, ast.Call)}
            for word in FORBIDDEN_WORDS:
                for ident in idents | called:
                    self.assertNotIn(word, str(ident).lower(), "%s uses %s" % (name, ident))

    def test_no_search_loop_over_the_stations(self):
        _src, found = feature_nodes()
        for name in NO_LOOP_FUNCTIONS:
            fn = found[name]
            self.assertEqual([n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp))], [], name)
            called = {getattr(n.func, "id", getattr(n.func, "attr", None)) for n in ast.walk(fn) if isinstance(n, ast.Call)}
            self.assertFalse(called & {"abs", "min", "max", "sorted", "enumerate", "next", "any", "all", "find", "index"}, (name, called))

    def test_the_qualification_has_one_call_in_the_scoring_and_the_machine_uses_the_same_function(self):
        src = source("scoring_logic.py")
        self.assertEqual(len(re.findall(r"pseudo_turnback_machine\.qualifying_pair\(", src)), 1)
        msrc = source("pseudo_turnback_machine.py")
        self.assertEqual(len(re.findall(r"\bqualifying_pair\(", msrc)), 2, "its definition and the one call of on_arrival")

    def test_o1_is_not_duplicated_no_anchor_pending_or_close_range_code_of_the_feature(self):
        src, found = feature_nodes()
        for name, fn in found.items():
            text = ast.get_source_segment(src, fn)
            for word in ("prev_actual_stop_loc", "close_range", "departure_reset_pending"):
                self.assertNotIn(word, text, (name, word))

    def test_the_feature_does_not_touch_the_jump_or_the_checkpoint_history_of_others(self):
        src, found = feature_nodes()
        for name, fn in found.items():
            text = ast.get_source_segment(src, fn)
            for word in ("send_jump_command", "begin_official_jump", "_open_jump_transaction", "save_data.clear", "save_data.pop", "del self.save_data"):
                self.assertNotIn(word, text, (name, word))

    def test_the_pure_modules_have_no_qt_win32_socket_file_or_clock(self):
        for name in ("pseudo_turnback_machine.py", "pseudo_turnback_contract.py"):
            tree = ast.parse(source(name))
            imported = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    imported |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom):
                    imported.add((n.module or "").split(".")[0])
            self.assertFalse(imported & {"PyQt6", "win32gui", "win32api", "socket", "time", "datetime", "os", "sys", "threading"}, (name, imported))


class B_SelectionContract(unittest.TestCase):
    """TB-SELECT-R1 .. R8 (Owner contract 2026-10-31): the START / END candidate rule. Pure rule here; the generation of the real candidate lists is Stage TB-D (no disabled row, no refusal dialog: the
    excluded station is simply not generated). R9 / R10 / R5 (product scoring and the existing terminal contract) are in tests/test_pt_scoring_continuity.py."""
    PS = C.PairSet("A1B2C3D4", 20, (C.Pair(3, 4, C.CONTINUE), C.Pair(9, 10, C.CONTINUE), C.Pair(18, 19, C.COMPLETE_AFTER_JUMP)))
    A = (3, 9, 18)
    B = (4, 10, 19)

    def test_TB_SELECT_R1_pair_A_is_not_a_start_candidate(self):
        for idx in self.A:
            self.assertFalse(M.start_station_allowed(self.PS, idx), idx)

    def test_TB_SELECT_R2_pair_A_is_an_end_candidate(self):
        for idx in self.A:
            self.assertTrue(M.end_station_allowed(self.PS, idx), idx)

    def test_TB_SELECT_R3_pair_B_is_a_start_candidate(self):
        for idx in self.B:
            self.assertTrue(M.start_station_allowed(self.PS, idx), idx)

    def test_TB_SELECT_R4_pair_B_is_not_an_end_candidate(self):
        for idx in self.B:
            self.assertFalse(M.end_station_allowed(self.PS, idx), idx)

    def test_TB_SELECT_R5_no_special_final_pair_concept_in_the_rule(self):
        """A B with no scoring station after it (the last station) is not special to the pseudo-turnback: the rule says 'allowed' like for any other B and the EXISTING terminal / section contract decides
        (the real candidate generation is exercised in test_pt_scoring_continuity.TB_SELECT_Existing)."""
        self.assertTrue(M.start_station_allowed(self.PS, 19))
        self.assertTrue(M.start_station_allowed(self.PS, 4))
        tree = ast.parse(source("pseudo_turnback_machine.py"))
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("start_station_allowed", "end_station_allowed")):
            idents = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            self.assertFalse({"COMPLETE_AFTER_JUMP", "mode", "station_count"} & idents, (fn.name, idents))

    def test_TB_SELECT_R6_the_rule_uses_no_station_name(self):
        import inspect
        tree = ast.parse(source("pseudo_turnback_machine.py"))
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("start_station_allowed", "end_station_allowed")):
            self.assertEqual([a.arg for a in fn.args.args], ["pairset", "station_index"], fn.name)
            idents = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            for ident in idents:
                self.assertNotRegex(ident, r"(?i)name|title|label", (fn.name, ident))
        for rule in (M.start_station_allowed, M.end_station_allowed):
            self.assertEqual(list(inspect.signature(rule).parameters), ["pairset", "station_index"])

    def test_TB_SELECT_R7_the_rule_uses_no_position_distance_or_search(self):
        tree = ast.parse(source("pseudo_turnback_machine.py"))
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("start_station_allowed", "end_station_allowed")):
            idents = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            called = {getattr(n.func, "id", getattr(n.func, "attr", None)) for n in ast.walk(fn) if isinstance(n, ast.Call)}
            for ident in idents | called:
                self.assertNotRegex(str(ident), r"(?i)loc|pos|dist|nearest|closest|abs|min|max|sorted|find", (fn.name, ident))
            self.assertEqual([n for n in ast.walk(fn) if isinstance(n, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp))], [], fn.name)

    def test_TB_SELECT_R8_every_ordinary_station_and_the_no_pair_cases_are_unchanged(self):
        pair_stations = set(self.A) | set(self.B)
        for idx in range(20):
            if idx not in pair_stations:
                self.assertTrue(M.start_station_allowed(self.PS, idx), idx)
                self.assertTrue(M.end_station_allowed(self.PS, idx), idx)
        for ps in (None, C.PairSet("A1B2C3D4", 20, ())):
            for idx in range(20):
                self.assertTrue(M.start_station_allowed(ps, idx))
                self.assertTrue(M.end_station_allowed(ps, idx))

    def test_the_rule_is_defined_once_and_nothing_in_the_product_files_applies_it_yet(self):
        """Stage TB-D wires the candidate generation; TB-A / TB-B contain the pure rule only (main.py is unchanged by design)."""
        self.assertEqual(len(re.findall(r"\bdef start_station_allowed\(", source("pseudo_turnback_machine.py"))), 1)
        self.assertEqual(len(re.findall(r"\bdef end_station_allowed\(", source("pseudo_turnback_machine.py"))), 1)
        for name in ("main.py", "menu_ui.py", "scoring_logic.py"):
            self.assertNotIn("start_station_allowed", source(name), name)
            self.assertNotIn("end_station_allowed", source(name), name)

if __name__ == "__main__":
    unittest.main()
