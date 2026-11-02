"""Stage TB-I Stage 9: the basic brake rule chain with the pseudo-turnback A as an OPTIONAL boundary (Owner contract 3, 2026-11-02).

Contract:
  * no boundary chosen -> ONE rule (start .. end). The existence of a pair never splits the chain and never forbids a rule that spans A -> B.
  * ordinary boundary X: next_start = X (unchanged).
  * pair A chosen as a boundary: it ends the previous rule and the NEXT rule starts at the corresponding pair B (W..A, B..Z; never A..Z).
  * boundary candidates: pair A stays (selectable), pair B is out, ordinary stations are unchanged.
  * the effective ranges are what the screens draw (basic brake, summary, initial / relaxation); the stored data is the boundary list (end_idx) only; the initial / relaxation rules mirror it.
On the baseline 02515c9 the RED ones failed for the contract reason (RED-API: Overlay.brake_rule_ranges did not exist); GUARD = passed there and must keep passing.
The REAL handlers (menu_state 5 / 6 / 7 / 9, handle_dropdown_enter) and the REAL menu_ui.draw_menu are driven."""
import copy
import inspect
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbd_snapshot import setUpModule, tearDownModule  # noqa: E402,F401
from test_pt_tbd_candidates import Base as CandBase  # noqa: E402


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class ChainBase(CandBase):
    # ---- routes (names are unique so the drawn texts identify the stations) -------------------------------------------------------------------------
    def route(self, names, pairs, start=0, end=-1):
        P = self.P
        sl = [P.station(n, 500.0 * i, raw_dep=P.T0 + 1000 * i, raw_arr=P.T0 + 1000 * i) for i, n in enumerate(names)]
        sl[-1]["is_terminal"] = True
        ptpair = "PTPAIR:1:%%s:%d:%d:%s" % (len(names), len(pairs), ";".join("%d-%d-0" % p for p in pairs))
        return self.scene(ptpair, stations=sl, start=start, end=end)

    def one(self, **kw):          # W X A B Y Z : W0 X1 A2 B3 Y4 Z5
        return self.route(["W", "X", "A", "B", "Y", "Z"], [(2, 3)], **kw)

    def two(self, **kw):          # W X A1 B1 A2 B2 Y Z : W0 X1 A1_2 B1_3 A2_4 B2_5 Y6 Z7
        return self.route(["W", "X", "A1", "B1", "A2", "B2", "Y", "Z"], [(2, 3), (4, 5)], **kw)

    def four(self, **kw):         # the C-01 shape: W X A1 B1 A2 B2 A3 B3 A4 B4 Y Z
        return self.route(["W", "X", "A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4", "Y", "Z"], [(2, 3), (4, 5), (6, 7), (8, 9)], **kw)

    def nopair(self, **kw):
        P = self.P
        names = ["W", "X", "A", "B", "Y", "Z"]
        sl = [P.station(n, 500.0 * i, raw_dep=P.T0 + 1000 * i, raw_arr=P.T0 + 1000 * i) for i, n in enumerate(names)]
        sl[-1]["is_terminal"] = True
        return self.scene(None, stations=sl, **kw)

    # ---- the REAL screens ---------------------------------------------------------------------------------------------------------------------
    def candidates(self, s):
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.sub_cursor, o.sub_cursor_x = 7, len(o.brake_rules) - 1, 0
        o.handle_menu_enter(False)
        return [opt["idx"] for opt in o.dropdown_options]

    def pick(self, s, idx):
        ids = self.candidates(s)
        self.assertIn(idx, ids, "the station %d is no boundary candidate %s" % (idx, ids))
        o = s.o
        o.dropdown_cursor = ids.index(idx)
        o.handle_dropdown_enter()
        o.dropdown_active = False
        return ids

    def names(self, s, state):
        """The station-name texts that the REAL draw_menu draws on screen `state` (5 setting 1/3, 6 setting 2/3, 7 basic brake, 9 initial / relaxation), in drawing order."""
        import menu_ui
        from PyQt6.QtGui import QImage, QPainter
        o = s.o
        known = {st["name"] for st in s.sl}
        drawn = []
        original = menu_ui.draw_text_with_outline

        def spy(painter, text, *args, **kwargs):
            drawn.append(str(text))
            return original(painter, text, *args, **kwargs)
        menu_ui.draw_text_with_outline = spy
        try:
            o.is_scoring_mode = False
            o.dropdown_active = False
            o.menu_state, o.menu_cursor, o.menu_cursor_x = state, 0, -1
            if state in (7, 9):
                o.sub_cursor = o.init_sub_cursor = 0
                o.sub_cursor_x = o.init_sub_cursor_x = 0
                o.sub_scroll = o.init_sub_scroll = 0
            o.summary_scroll = o.init_summary_scroll = 0
            image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            try:
                menu_ui.draw_menu(o, painter, 1920)
            finally:
                painter.end()
        finally:
            menu_ui.draw_text_with_outline = original
        return [t for t in drawn if t in known]

    def sync_init_rules(self, s):
        """The REAL entry of the initial / relaxation screen (menu_state 6 = setting 2/3, cursor 5): it makes penalty_init_rules as long as brake_rules."""
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 5, 0          # "next" of setting 1/3: the init rules are made as long as brake_rules
        o.handle_menu_enter(False)
        self.assertEqual(o.menu_state, 6)
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 5, 0          # the initial / relaxation "change"
        o.handle_menu_enter(False)
        self.assertEqual(o.menu_state, 9)

    @staticmethod
    def flat(pairs, s):
        out = []
        for a, b in pairs:
            out += [s.sl[a]["name"], s.sl[b]["name"]]
        return out

    @staticmethod
    def has_run(seq, run):
        return any(seq[i:i + len(run)] == run for i in range(len(seq) - len(run) + 1))

    def ranges(self, s):
        return s.o.brake_rule_ranges()


class A_Candidates(ChainBase):
    def test_RB_01_GUARD_no_boundary_chosen_keeps_one_through_rule(self):
        s = self.one()
        self.assertEqual(len(s.o.brake_rules), 1)
        for state in (5, 7):
            self.assertTrue(self.has_run(self.names(s, state), ["W", "Z"]), "the default rule is W .. Z on screen %d" % state)

    def test_RB_02_GUARD_the_pair_alone_never_splits_the_chain_and_a_through_rule_over_A_B_is_allowed(self):
        s = self.one()
        self.candidates(s)
        self.assertEqual(len(s.o.brake_rules), 1, "opening the candidate list changes nothing")
        s2 = self.one()
        self.pick(s2, 4)                                  # the ordinary Y: W .. Y spans the pair A -> B (a through rule), Y .. Z
        self.assertEqual([r["end_idx"] for r in s2.o.brake_rules], [4, -1])
        s3 = self.four()                                  # four pairs: still one rule until the user chooses a boundary
        self.assertEqual(len(s3.o.brake_rules), 1)

    def test_RB_03_RED_the_pair_A_is_a_boundary_candidate(self):
        self.assertEqual(self.candidates(self.one()), [1, 2, 4, 5], "RED on the baseline: [1, 4, 5]")

    def test_RB_05_GUARD_the_pair_B_is_no_boundary_candidate(self):
        self.assertNotIn(3, self.candidates(self.one()))
        self.assertNotIn(3, self.candidates(self.two()))
        self.assertNotIn(5, self.candidates(self.two()))

    def test_RB_06_GUARD_the_ordinary_stations_stay_candidates(self):
        got = self.candidates(self.one())
        for idx in (1, 4, 5):
            self.assertIn(idx, got)
        self.assertEqual(self.candidates(self.nopair()), [1, 2, 3, 4, 5], "no PairSet: unchanged")

    def test_RB_04_RED_the_pair_A_can_be_selected_and_ends_the_previous_rule(self):
        s = self.one()
        self.pick(s, 2)
        self.assertEqual([r["end_idx"] for r in s.o.brake_rules], [2, -1], "RED on the baseline: A is not offered")

    def test_RB_21_GUARD_the_stored_data_is_the_boundary_list_only(self):
        s = self.one()
        self.pick(s, 1)
        self.assertEqual(sorted(s.o.brake_rules[0].keys()), ["apply", "end_idx", "release"], "no stored start: the start of a rule is derived from the previous boundary")
        text = source("managed_input.py")
        self.assertIn('{"end_idx": -1, "apply": "階段", "release": "階段"}', text)

    def test_RB_22_GUARD_a_PairSet_free_route_and_a_terminal_A_are_not_mapped(self):
        s = self.nopair()
        self.pick(s, 2)                                   # no PairSet: A (2) is an ordinary station
        self.assertEqual(self.ranges(s), [(0, 2), (2, 5)], "RED-API on the baseline (the helper does not exist)")
        s2 = self.one(end=2)                              # the section ends at A: A is the terminal, no next rule
        self.assertEqual(self.ranges(s2), [(0, 2)], "RED-API on the baseline")


class B_EffectiveRanges(ChainBase):
    def test_RB_07_GUARD_an_ordinary_boundary_starts_the_next_rule_at_the_boundary(self):
        s = self.one()
        self.pick(s, 1)
        self.assertEqual(self.ranges(s), [(0, 1), (1, 5)], "RED-API on the baseline (the helper does not exist)")
        self.assertTrue(self.has_run(self.names(s, 7), self.flat([(0, 1), (1, 5)], s)), "GUARD: W~X, X~Z on screen")

    def test_RB_08_RED_after_A_the_next_rule_starts_at_the_corresponding_B(self):
        s = self.one()
        self.pick(s, 2)
        self.assertEqual(self.ranges(s), [(0, 2), (3, 5)], "RED: W~A, B~Z")

    def test_RB_09_RED_the_screens_draw_W_A_and_B_Z(self):
        s = self.one()
        self.pick(s, 2)
        self.sync_init_rules(s)
        want = ["W", "A", "B", "Z"]
        for state in (5, 6, 7, 9):
            self.assertTrue(self.has_run(self.names(s, state), want), "screen %d draws %s, got %s" % (state, want, self.names(s, state)))

    def test_RB_10_RED_no_screen_draws_A_Z(self):
        s = self.one()
        self.pick(s, 2)
        self.sync_init_rules(s)
        for state in (5, 6, 7, 9):
            self.assertFalse(self.has_run(self.names(s, state), ["A", "Z"]), "screen %d must not show A~Z" % state)

    def test_RB_11_RED_with_several_pairs_the_first_A_maps_to_the_first_B(self):
        s = self.two()
        self.pick(s, 2)
        self.assertEqual(self.ranges(s), [(0, 2), (3, 7)], "W~A1, B1~Z; the pair 2 (A2 B2) is inside the rule: no automatic split")

    def test_RB_12_RED_B1_to_A2_can_be_set_and_A2_maps_to_B2(self):
        s = self.two()
        self.pick(s, 2)
        got = self.candidates(s)
        self.assertEqual(got, [4, 6, 7], "after A1: candidates are after B1 (A2, Y, Z); A1 and both B are out; RED on the baseline: [6, 7]")
        self.pick(s, 4)
        self.assertEqual(self.ranges(s), [(0, 2), (3, 4), (5, 7)], "W~A1, B1~A2, B2~Z")
        self.assertEqual([r["end_idx"] for r in s.o.brake_rules], [2, 4, -1])

    def test_RB_13_RED_A2_alone_maps_to_B2_and_leaves_pair_1_unsplit(self):
        s = self.two()
        self.pick(s, 4)
        self.assertEqual(self.ranges(s), [(0, 4), (5, 7)], "W~A2 spans the pair 1 (A1 B1) as a through rule; B2~Z")

    def test_RB_14_GUARD_a_pair_that_the_user_did_not_choose_is_not_split(self):
        s = self.two()
        self.pick(s, 1)                                   # the ordinary X
        self.assertEqual(self.ranges(s), [(0, 1), (1, 7)], "RED-API on the baseline: both pairs stay inside the second rule")
        self.assertEqual(len(s.o.brake_rules), 2)

    def test_RB_15_RED_the_initial_relaxation_screen_mirrors_the_effective_ranges(self):
        s = self.two()
        self.pick(s, 2)
        self.pick(s, 4)
        self.sync_init_rules(s)
        self.assertEqual(len(s.o.penalty_init_rules), len(s.o.brake_rules))
        self.assertTrue(self.has_run(self.names(s, 9), self.flat([(0, 2), (3, 4), (5, 7)], s)), self.names(s, 9))
        self.assertTrue(self.has_run(self.names(s, 6), self.flat([(0, 2), (3, 4), (5, 7)], s)), self.names(s, 6))
        text = source("main.py")
        self.assertEqual(text.count("def _brake_end_candidates"), 1, "GUARD: still one generator; the initial / relaxation screen has no candidates of its own")
        self.assertNotIn('"init_sub_end_sta"; ', text)

    def test_RB_16_RED_the_effective_ranges_survive_the_start_button_a_copy_and_a_new_generation_resets_them(self):
        s = self.one()
        self.pick(s, 2)
        before = self.ranges(s)
        self.assertEqual(before, [(0, 2), (3, 5)])
        data = copy.deepcopy(s.o.brake_rules)
        s2 = self.one()                                   # a fresh Overlay with the same stored data (the stored form is the boundary list)
        s2.o.brake_rules = data
        self.assertEqual(self.ranges(s2), before, "the stored boundary list alone reproduces W~A, B~Z")
        s3 = self.one()
        s3.o.brake_rules = copy.deepcopy(data)
        self.press_start_like(s3)
        self.assertEqual(self.ranges(s3), before, "the Run snapshot does not change the effective ranges")
        import managed_input
        managed_input.discard_generation_state(s.o)
        self.assertEqual(s.o.brake_rules, [{"end_idx": -1, "apply": "階段", "release": "階段"}], "GUARD: a new scenario generation returns to one rule")

    def test_RB_25_a_station_called_A_that_is_no_pair_A_is_not_mapped(self):
        """The mapping reads StationIndex and the PairSet only: the station called A at index 2 is ordinary, the pair is (4, 5)."""
        s = self.route(["W", "X", "A", "P", "Q", "R", "Z"], [(4, 5)])
        self.pick(s, 2)
        self.assertEqual(self.ranges(s), [(0, 2), (2, 6)], "an ordinary station named A starts the next rule itself")

    def test_RB_26_the_Run_snapshot_fixes_the_pairs_of_the_chain(self):
        """While a Run is active the pairs of the chain are the snapshot's: a later change of the settings does not change the effective start."""
        s = self.one()
        self.pick(s, 2)
        self.press_start_like(s)
        self.assertEqual(self.ranges(s)[1][0], 3)
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 1          # the settings no longer cross the pair; the Run does
        self.assertEqual(s.o.brake_rule_start(1), 3, "the Run snapshot still maps the A to its B")

    def press_start_like(self, s):
        o = s.o
        s.auto_fix = False
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor = 10, 1
        o.scoring_start_gate = None
        o.was_advancing_before_menu = False
        self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
        o.bve_location, o.bve_speed = 0.0, 0.0
        o.handle_menu_enter(False)
        self.assertTrue(o.is_scoring_mode, "the start button was refused")

    def test_RB_23_RED_the_helper_reads_StationIndex_and_the_PairSet_only(self):
        s = self.one()
        for st in s.sl:
            st["name"] = "same"
        self.pick(s, 2)
        self.assertEqual(self.ranges(s), [(0, 2), (3, 5)], "names are no input")
        s.o.bve_door, s.o.bve_doordir, s.o.bve_is_pass = 1, 0, 1
        self.assertEqual(self.ranges(s), [(0, 2), (3, 5)], "doors / indicator lamp / signal flag are no input")


class C_RuntimeAndScore(ChainBase):
    def tick_target(self, s, tgt):
        o = s.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.bve_next_loc = o.prev_next_loc = s.sl[tgt]["location"]
        self.P.R.bind_identity(o, arr_idx=max(0, tgt - 1), tgt_idx=tgt)
        o.active_rule_basic_apply = "SENTINEL"
        s.tick(16)
        return o.active_rule_basic_apply

    def test_RB_17_GUARD_the_runtime_rule_is_chosen_by_the_target_and_B_belongs_to_the_second_rule(self):
        s = self.one(end=5)
        s.auto_fix = False
        o = s.o
        o.brake_rules = [{"end_idx": 2, "apply": "1段", "release": "1段"}, {"end_idx": -1, "apply": "3段", "release": "3段"}]
        o.penalty_init_rules = [{"apply": "ON①", "release": "ON①"}, {"apply": "ON①", "release": "ON①"}]
        self.assertEqual(self.tick_target(s, 1), "1段", "X before A")
        self.assertEqual(self.tick_target(s, 2), "1段", "A itself belongs to the first rule")
        self.assertEqual(self.tick_target(s, 3), "3段", "B (the A -> B movement) is the second rule, never the first")
        self.assertEqual(self.tick_target(s, 4), "3段", "Y")

    def test_RB_17b_GUARD_get_current_brake_rule_reads_the_position_in_the_same_order(self):
        s = self.one(end=5)
        o = s.o
        o.is_scoring_mode = True
        o.bve_next_loc = s.sl[5]["location"]
        o.brake_rules = [{"end_idx": 2, "apply": "1段", "release": "1段"}, {"end_idx": -1, "apply": "3段", "release": "3段"}]
        o.bve_location = s.sl[2]["location"]
        self.assertIn("1段", o.get_current_brake_rule(), "at A: the first rule")
        o.bve_location = s.sl[3]["location"]
        self.assertIn("3段", o.get_current_brake_rule(), "at B (A -> B is no ordinary run of the first rule): the second rule")

    def test_RB_18_GUARD_the_theoretical_score_stays_9100_with_a_boundary_at_A(self):
        s = self.four()
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 11
        self.pick(s, 1)
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 6, 0
        o.handle_menu_enter(False)
        self.assertEqual(o.theoretical_score, 9100, "an ordinary boundary: unchanged")
        s2 = self.four()
        s2.o.setting_start_idx, s2.o.setting_end_idx = 0, 11
        try:
            self.pick(s2, 2)
        except AssertionError:
            self.skipTest("RED-API: the A boundary is not offered on the baseline (RB-03)")
        s2.o.menu_state, s2.o.menu_cursor, s2.o.menu_cursor_x = 6, 6, 0
        s2.o.handle_menu_enter(False)
        self.assertEqual(s2.o.theoretical_score, 9100)

    def test_RB_18b_RED_the_theoretical_score_stays_9100_for_every_A_chain(self):
        s = self.four()
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 11
        for a in (2, 4, 6, 8):
            self.pick(s, a)
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 6, 0
        o.handle_menu_enter(False)
        self.assertEqual(o.theoretical_score, 9100, "RED on the baseline: A is not offered")
        self.assertEqual(self.ranges(s), [(0, 2), (3, 4), (5, 6), (7, 8), (9, 11)])

    def test_RB_19_GUARD_the_pair_B_stays_untimed_with_a_boundary_at_A(self):
        s = self.four()
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 11
        self.assertEqual(self.S.untimed_reason(o, 3), "UNTIMED_TURNBACK_B")
        self.assertFalse(o.is_station_timing(3))
        try:
            self.pick(s, 2)
        except AssertionError:
            pass
        self.assertEqual(self.S.untimed_reason(o, 3), "UNTIMED_TURNBACK_B")
        self.assertFalse(o.is_station_timing(3))
        self.assertIsNone(self.S.untimed_reason(o, 2), "the A stays an ordinary changeable station")

    def test_RB_20_RED_the_one_python_path_has_no_host_branch(self):
        helper = inspect.getsource(self.main.Overlay.brake_rule_ranges)            # RED-API on the baseline
        for word in ("legacy", "Legacy", "current", "Current", "dll", "DLL", "host"):
            self.assertNotIn(word, helper)
        main_text = source("main.py")
        block = main_text[main_text.index("def _brake_end_candidates"):main_text.index("def _scoring_start_candidates")]
        for word in ("legacy", "Legacy", "dll", "DLL"):
            self.assertNotIn(word, block)

    def test_RB_24_GUARD_the_mouse_and_the_keyboard_share_the_one_sink(self):
        self.assertEqual(len(re.findall(r"self\.handle_menu_enter\(is_bve_advancing\)", source("main.py"))), 2)


if __name__ == "__main__":
    unittest.main()
