"""Stage TB-D, slice D1 (OD-TD-1 / OD-TD-2): the START / END candidate lists are generated WITHOUT the A of a certified pair (start) and WITHOUT the B of a certified pair (end, even when it is the raw
terminal), the end candidates also exclude the start's own StationIndex, and the initial end station (the sentinel setting_end_idx == -1, as the menu draws it) is the LAST of the filtered end candidates.
The certified STATIC pair set is the PairSet of the machine (turnback_machine.pairset, injected by the test: the formal supply is Stage TB-E); the Run-specific set (machine.fixed) is never used here.
The REAL handle_menu_enter (menu_state 5 / 7) and the REAL menu_ui.draw_menu are driven; nothing of the product is replaced."""
import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbd-cand-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbd-cand"])
        import main
        import scoring_logic
        import pt_scene
        import pseudo_turnback_contract
        cls.main, cls.S, cls.P, cls.PC = main, scoring_logic, pt_scene, pseudo_turnback_contract

    # ---- scenes -------------------------------------------------------------------------------------------------------------------------------
    def inject(self, s, text):
        """The certified static pair set, injected (never fixed by a start button)."""
        ps, why = self.PC.decode_ptpair(text, len(s.sl))
        self.assertIsNone(why, why)
        self.S.turnback_machine_of(s.o).set_pairset(ps)

    def scene(self, ptpair, stations=None, start=0, end=-1):
        s = self.P.Scene(self, drive=False, with_pairs=False)
        if stations is not None:
            s.sl = stations
            s.o.station_list = s.sl
        if ptpair is not None:
            self.inject(s, ptpair % self.P.R.SCOPE_LIST_ID if "%s" in ptpair else ptpair)
        s.o.setting_start_idx, s.o.setting_end_idx = start, end
        return s

    def five(self, ptpair="PTPAIR:1:%s:5:1:1-2-0"):
        return self.scene(ptpair)

    def terminal_b(self, ptpair="PTPAIR:1:%s:3:1:1-2-0"):
        P = self.P
        sl = [P.station("S0", 0.0, raw_dep=P.T0), P.station("NA", P.A_MARK, raw_arr=P.T0 + 90000), P.station("NB", P.B_MARK, raw_dep=P.T0 + 150000, terminal=True)]
        return self.scene(ptpair, stations=sl)

    def six(self):
        P = self.P
        sl = [P.station("S0", 0.0, raw_dep=P.T0), P.station("A1", 200.0, raw_arr=P.T0 + 20000), P.station("B1", 300.0, raw_dep=P.T0 + 40000),
              P.station("A2", P.A_MARK, raw_arr=P.T0 + 90000), P.station("B2", 1500.0, raw_dep=P.T0 + 150000), P.station("E", 3000.0, terminal=True)]
        return self.scene("PTPAIR:1:%s:6:2:1-2-0;3-4-0", stations=sl)

    def cands(self, s, x):
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 0, x
        o.handle_menu_enter(False)
        return [opt["idx"] for opt in o.dropdown_options]

    def starts(self, s):
        return self.cands(s, 0)

    def ends(self, s):
        return self.cands(s, 1)

    def brake_end(self, s):
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}]
        o.menu_state, o.sub_cursor, o.sub_cursor_x = 7, 0, 0
        o.handle_menu_enter(False)
        return [opt["idx"] for opt in o.dropdown_options]

    def drawn_texts(self, s):
        """The texts that the REAL menu_ui.draw_menu draws on the scoring setting screen (menu_state 5)."""
        import menu_ui
        from PyQt6.QtGui import QImage, QPainter
        o = s.o
        drawn = []
        original = menu_ui.draw_text_with_outline

        def spy(painter, text, *args, **kwargs):
            drawn.append(str(text))
            return original(painter, text, *args, **kwargs)
        menu_ui.draw_text_with_outline = spy
        try:
            o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 0, -1
            o.dropdown_active = False
            image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            try:
                menu_ui.draw_menu(o, painter, 1920)
            finally:
                painter.end()
        finally:
            menu_ui.draw_text_with_outline = original
        return drawn


class A_OD_TD_1_Red(Base):
    def test_C_R1_the_A_of_a_single_pair_is_not_a_start_candidate(self):
        self.assertEqual(self.starts(self.five()), [0, 2, 3])

    def test_C_R2_the_B_of_a_single_pair_is_not_an_end_candidate(self):
        self.assertEqual(self.ends(self.five()), [1, 3, 4])

    def test_C_R3_with_a_terminal_B_the_last_filtered_candidate_A_is_the_initial_end_station(self):
        s = self.terminal_b()
        self.assertEqual(self.ends(s), [1], "B (the raw terminal) is excluded, A stays")
        self.assertEqual(s.o.setting_end_idx, -1, "the sentinel is not rewritten")
        self.assertEqual(s.o.get_actual_terminal_idx(), 1, "the sentinel resolves to the LAST filtered end candidate")

    def test_C_R4_with_a_terminal_B_the_menu_draws_the_name_of_A(self):
        s = self.terminal_b()
        texts = self.drawn_texts(s)
        self.assertTrue(any("NA" in t for t in texts), texts)
        self.assertFalse(any("NB" in t for t in texts), "the screen must not draw B first and correct it later: %s" % texts)

    def test_C_R5_with_a_terminal_B_the_end_StationIndex_of_the_start_snapshot_is_A(self):
        s = self.terminal_b()
        s.auto_fix = False
        o = s.o
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor = 10, 1
        o.scoring_start_gate = None
        o.was_advancing_before_menu = False
        self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
        o.bve_location, o.bve_speed = 0.0, 0.0
        o.handle_menu_enter(False)
        self.assertTrue(o.is_scoring_mode, "the start button was refused")
        snapshot = o.__dict__.get("_scoring_section")
        self.assertIsNotNone(snapshot, "no scoring section snapshot")
        self.assertEqual((snapshot.start, snapshot.end), (0, 1))

    def test_C_R6_every_A_of_several_pairs_is_excluded_from_the_start_candidates(self):
        s = self.six()
        starts = self.starts(s)
        self.assertEqual(starts, [0, 2, 4], "A1=1 and A2=3 are gone, B1=2 and B2=4 stay")

    def test_C_R7_every_B_of_several_pairs_is_excluded_from_the_end_candidates(self):
        s = self.six()
        ends = self.ends(s)
        self.assertEqual(ends, [1, 3, 5], "B1=2 and B2=4 are gone, A1=1 and A2=3 stay")

    def test_C_R7b_a_raw_terminal_that_is_a_B_is_excluded_even_in_a_longer_route(self):
        P = self.P
        sl = [P.station("S0", 0.0), P.station("X1", 100.0), P.station("X2", 200.0), P.station("A", 300.0), P.station("B", 400.0, terminal=True)]
        s = self.scene("PTPAIR:1:%s:5:1:3-4-0", stations=sl)
        self.assertEqual(self.ends(s), [1, 2, 3])
        self.assertEqual(s.o.get_actual_terminal_idx(), 3)

    def test_C_R8_the_exclusion_is_by_StationIndex_even_when_names_repeat(self):
        P = self.P
        names = ("X", "Y", "Z", "Z", "Y")                       # A (index 1) is named Y like index 4; B (index 2) is named Z like index 3
        sl = [P.station(n, 1000.0 * i) for i, n in enumerate(names)]
        sl[4]["is_terminal"] = True
        s = self.scene("PTPAIR:1:%s:5:1:1-2-0", stations=sl)
        self.assertEqual(self.starts(s), [0, 2, 3])
        self.assertEqual(self.ends(s), [1, 3, 4])
        swapped = [P.station(n, 1000.0 * i) for i, n in enumerate(("Q", "Q", "Q", "Q", "Q"))]
        swapped[4]["is_terminal"] = True
        s2 = self.scene("PTPAIR:1:%s:5:1:1-2-0", stations=swapped)
        self.assertEqual((self.starts(s2), self.ends(s2)), ([0, 2, 3], [1, 3, 4]), "the same station names give the same lists")


class B_OD_TD_1_Guard(Base):
    def test_C_G1_an_ordinary_route_keeps_the_raw_terminal_as_the_initial_end_station(self):
        for text in (None, "PTPAIR:1:%s:5:1:1-2-0"):
            s = self.five(text) if text else self.scene(None)
            self.assertEqual(s.o.get_actual_terminal_idx(), 4, text)
            self.assertEqual(s.o.setting_end_idx, -1)

    def test_C_G2_an_empty_absent_or_foreign_pair_set_changes_nothing(self):
        plain = self.scene(None)
        want = (self.starts(plain), self.ends(plain), plain.o.get_actual_terminal_idx())
        self.assertEqual(want, ([0, 1, 2, 3], [1, 2, 3, 4], 4))
        empty = self.scene("PTPAIR:1:%s:5:0:")
        self.assertEqual((self.starts(empty), self.ends(empty), empty.o.get_actual_terminal_idx()), want)
        foreign = self.scene("PTPAIR:1:FFFFFFFF:5:1:1-2-0")
        self.assertEqual((self.starts(foreign), self.ends(foreign), foreign.o.get_actual_terminal_idx()), want, "a pair set of ANOTHER station list excludes nothing (PU-5)")

    def test_C_G3_the_B_stays_a_start_candidate(self):
        self.assertIn(2, self.starts(self.five()))

    def test_C_G4_the_A_stays_an_end_candidate(self):
        self.assertIn(1, self.ends(self.five()))

    def test_C_G5_the_brake_rule_end_candidates_leave_out_only_the_A_and_the_B_of_a_crossed_pair(self):
        # Stage TB-I (on purpose, Owner contract): the old guard said the brake rule end candidates are unchanged by the pair set. A boundary of the brake rules is the end of one rule and the start of the next,
        # so the A and the B of every pair that the scoring section crosses are no boundary now (tests/test_pt_tbi_cursor_candidates.py). A pair that the section does not cross is still not touched.
        with_pairs, without = self.terminal_b(), self.terminal_b(None)
        self.assertEqual(self.brake_end(with_pairs), self.brake_end(without))
        self.assertEqual(self.brake_end(with_pairs), [1, 2], "the section ends at A and crosses nothing: the brake rule section may end at the raw terminal even when it is a B")
        five_with, five_without = self.five(), self.scene(None)
        self.assertEqual(self.brake_end(five_without), [1, 2, 3, 4])
        self.assertEqual(self.brake_end(five_with), [3, 4], "the crossed pair (A 1, B 2) is out")

    def test_C_G6_the_default_sentinel_and_its_general_meaning_are_unchanged(self):
        self.assertEqual(len(re.findall(r"self\.setting_end_idx = -1\b", source("main.py"))), 2, "the default (init) and the scenario-change reset")
        s = self.terminal_b()
        self.starts(s)
        self.ends(s)
        s.o.get_actual_terminal_idx()
        self.assertEqual(s.o.setting_end_idx, -1, "generating candidates / resolving the initial end writes nothing")
        self.assertEqual(s.o.setting_start_idx, 0)

    def test_C_G7_menu_ui_network_managed_input_and_station_identity_are_byte_unchanged(self):
        try:
            out = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "menu_ui.py", "network.py", "managed_input.py", "station_identity.py"], cwd=ROOT,
                                 capture_output=True, text=True, timeout=60)
        except Exception:
            self.skipTest("git not available (INCONCLUSIVE)")
        if out.returncode != 0:
            self.skipTest("git not available (INCONCLUSIVE)")
        self.assertEqual(out.stdout.strip(), "")

    def test_C_G8_an_ordinary_neighbour_is_not_a_B_and_the_station_before_a_B_is_not_assumed_to_be_A(self):
        s = self.five()
        self.assertEqual([i for i in (3, 4) if i in self.ends(s)], [3, 4], "neighbours of the pair are ordinary stations")
        s2 = self.scene("PTPAIR:1:%s:5:1:3-4-0")
        self.assertEqual(self.ends(s2), [1, 2, 3], "only the B (4) is gone; 1 and 2 are ordinary")
        self.assertEqual(self.starts(s2), [0, 1, 2], "A (3) is gone; the terminal (4, a B) is no start by the existing contract")

    def test_C_X1_the_last_filtered_candidate_is_used_not_the_index_before_the_B(self):
        P = self.P
        sl = [P.station("S0", 0.0), P.station("N1", 100.0), P.station("N2", 200.0), P.station("NB", 300.0, terminal=True)]
        sl[2]["is_pass"] = True                                 # the index before the B is a pass station: it is no candidate at all
        s = self.scene("PTPAIR:1:%s:4:1:2-3-0", stations=sl)
        self.assertEqual(self.ends(s), [1], "valid_stas has no pass station; the B is gone")
        self.assertEqual(s.o.get_actual_terminal_idx(), 1, "the last filtered candidate (1), never 'B - 1' (2)")

    def test_C_G9_a_raw_terminal_that_is_no_candidate_but_no_B_is_returned_as_it_is(self):
        P = self.P
        sl = [P.station("S0", 0.0), P.station("A", 100.0), P.station("B", 200.0), P.station("N3", 300.0), P.station("N4", 400.0, terminal=True)]
        sl[4]["is_pass"] = True                                  # the raw terminal is a pass station: no end candidate, and no B either
        s = self.scene("PTPAIR:1:%s:5:1:1-2-0", stations=sl)
        self.assertEqual(self.ends(s), [1, 3])
        self.assertEqual(s.o.get_actual_terminal_idx(), 4, "the raw terminal stays what it was: only a B terminal is replaced by the last filtered candidate")

    def test_C_X2_candidates_create_no_machine_and_use_the_static_set_not_the_fixed_one(self):
        s = self.scene(None)
        self.starts(s)
        self.ends(s)
        self.assertNotIn("turnback_machine", s.o.__dict__)
        s2 = self.five()
        m = self.S.turnback_machine_of(s2.o)
        m.fix_section((self.PC.Pair(3, 4, 0),), s2.o.current_scenario_id)         # a Run-specific fixed set that differs from the static one
        self.assertEqual((self.starts(s2), self.ends(s2)), ([0, 2, 3], [1, 3, 4]))

    def test_C_X3_doors_and_signals_change_no_candidate(self):
        s = self.terminal_b()
        base = (self.starts(s), self.ends(s), s.o.get_actual_terminal_idx())
        for field, value in (("bve_door", 1), ("bve_door", 0), ("bve_doordir", 0), ("bve_doordir", -1), ("bve_signal_limit", 0.0), ("bve_signal_limit", 120.0), ("bve_term", 1), ("bve_is_pass", 1)):
            setattr(s.o, field, value)
            self.assertEqual((self.starts(s), self.ends(s), s.o.get_actual_terminal_idx()), base, (field, value))

    def test_C_X4_the_wiring_uses_the_pure_rules_once_each_with_a_StationIndex_only(self):
        src = source("main.py")
        tree = ast.parse(src)
        calls = {"start_station_allowed": [], "end_station_allowed": []}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name in calls:
                    calls[name].append(node)
        self.assertEqual({k: len(v) for k, v in calls.items()}, {"start_station_allowed": 1, "end_station_allowed": 1})
        for name, nodes in calls.items():
            args = nodes[0].args
            self.assertEqual(len(args), 2, name)
            self.assertIn("idx", ast.dump(args[1]), "the station argument is the StationIndex")
            self.assertNotIn("name", ast.dump(args[1]).replace("'idx'", ""), name)
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name in ("_static_pairset", "_scoring_start_candidates", "_scoring_end_candidates"):
                text = ast.dump(fn)
                for token in ("'location'", "'distance'", "nearest", "bve_door", "bve_doordir", "signal", "abs"):
                    self.assertNotIn(token, text, (fn.name, token))


if __name__ == "__main__":
    unittest.main()
