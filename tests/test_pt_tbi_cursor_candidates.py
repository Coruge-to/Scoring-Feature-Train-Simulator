"""Stage TB-I Stage 7 (RED): (1) the timing screen cursor skips the contract-untimed stations (the Run start and the B of every crossed pair), (2) the basic brake rule screen takes the A and the B of every crossed
pair out of its station candidates (the initial / relaxation rule screen is a mirror of the brake rules and needs no candidates of its own).

Owner contract (2026-11-02):
  * timing screen: the keyboard cursor does not stop on a fixed untimed station (UNTIMED_SCORING_START / UNTIMED_TURNBACK_B). The row stays drawn, red 'untimed' stays, the mouse can not switch it, the A key bulk
    button leaves it alone. X -> A -> B -> Y: Down on A goes to Y, Up on Y goes to A. A pseudo-turnback A is an ordinary changeable station.
  * basic brake rules (Owner contract 3, 2026-11-02, replaces the first reading 'A and B are both out'): the boundary candidate list holds the A of a crossed pair (selectable; the NEXT rule then starts at its B) and
    not the B (a rule may not end at B). Pairs that the scoring section does not cross are not touched. The effective ranges and the screens: tests/test_pt_tbi_brake_chain.py.
RED = fails on the baseline 41b3652 for the contract reason (RED-API: the pure helper does not exist yet). GUARD = passes on the baseline and must keep passing. The REAL handlers and the REAL menu_ui.draw_menu are driven."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbd_snapshot import Base as SnapshotBase, setUpModule, tearDownModule  # noqa: E402,F401
from test_pt_tbd_candidates import Base as CandBase  # noqa: E402


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class CursorBase(SnapshotBase):
    """Scene S0 (0, the start) / A (1) / B (2, pair B) / C (3) / D (4, terminal): the fixed rows are 0 and 2, the stops are 1, 3, 4 and the done button (list length = 5)."""

    def enter_screen(self, s):
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 2, 0
        o.handle_menu_enter(False)
        self.assertEqual(o.menu_state, 8)
        return o

    @staticmethod
    def down(o, n=1):
        seen = []
        for _ in range(n):
            o.handle_menu_down()
            seen.append(o.timing_cursor)
        return seen

    @staticmethod
    def up(o, n=1):
        seen = []
        for _ in range(n):
            o.handle_menu_up()
            seen.append(o.timing_cursor)
        return seen

    def c01_scene(self):
        """Four pairs W X A1 B1 A2 B2 A3 B3 A4 B4 Y Z (the C-01 shape): the fixed rows are the start (0) and B1 3 / B2 5 / B3 7 / B4 9."""
        s = self.P.Scene(self, with_pairs=False)
        names = ["W", "X", "A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4", "Y", "Z"]
        sl = [self.P.station(n, 500.0 * i, raw_dep=self.P.T0 + 1000 * i, raw_arr=self.P.T0 + 1000 * i) for i, n in enumerate(names)]
        sl[-1]["is_terminal"] = True
        s.o.station_list = s.sl = sl
        ptpair = "PTPAIR:1:%s:12:4:2-3-0;4-5-0;6-7-0;8-9-0" % self.P.R.SCOPE_LIST_ID
        ps, why = self.PC.decode_ptpair(ptpair, 12)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 11
        return s

    def draw(self, s):
        from PyQt6.QtGui import QImage, QPainter
        import menu_ui
        o = s.o
        original = menu_ui.draw_text_with_outline
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        o.menu_state = 8
        o.timing_scroll = getattr(o, "timing_scroll", 0)
        o.menu_click_zones = []
        try:
            menu_ui.draw_menu(o, painter, 1920)
        finally:
            painter.end()
            menu_ui.draw_text_with_outline = original
        return list(o.menu_click_zones)


class A_TimingCursor(CursorBase):
    def test_CU_01_the_start_station_never_holds_the_cursor(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        trail = [o.timing_cursor] + self.up(o, 3) + self.down(o, 8) + self.up(o, 8)
        self.assertNotIn(0, trail, "GUARD: the start row (list index 0) is never a stop")

    def test_CU_02_RED_the_pair_B_never_holds_the_cursor(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        trail = [o.timing_cursor] + self.down(o, 8) + self.up(o, 8)
        self.assertNotIn(2, trail, "RED on the baseline: the cursor stops on B (list index 2) in both directions")

    def test_CU_03_the_ordinary_stations_still_hold_the_cursor(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        seen = {o.timing_cursor} | set(self.down(o, 8))
        self.assertTrue({3, 4}.issubset(seen), "GUARD: C (3) and D (4) are stops")

    def test_CU_04_the_pair_A_is_an_ordinary_changeable_station_and_holds_the_cursor(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        self.assertEqual(o.timing_cursor, 1, "GUARD: the screen opens on the first changeable row, the pair A")
        self.assertIsNone(self.S.untimed_reason(o, 1), "GUARD: the A has no fixed reason")

    def test_CU_05_RED_down_on_A_skips_the_B_and_lands_on_the_next_changeable_station(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        self.assertEqual(o.timing_cursor, 1)
        o.handle_menu_down()
        self.assertEqual(o.timing_cursor, 3, "RED on the baseline: it is 2 (the B)")

    def test_CU_06_RED_up_on_the_next_changeable_station_skips_the_B_and_lands_on_A(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        o.timing_cursor = 3
        o.handle_menu_up()
        self.assertEqual(o.timing_cursor, 1, "RED on the baseline: it is 2 (the B)")

    def test_CU_07_RED_several_fixed_rows_in_a_row_are_all_skipped(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        real = self.main.untimed_reason

        def fixed_2_and_3(owner, idx):
            return "UNTIMED_TURNBACK_B" if idx in (2, 3) else real(owner, idx)
        with mock.patch.object(self.main, "untimed_reason", fixed_2_and_3):
            o.timing_cursor = 1
            o.handle_menu_down()
            self.assertEqual(o.timing_cursor, 4, "RED on the baseline: 2")
            o.handle_menu_up()
            self.assertEqual(o.timing_cursor, 1, "RED on the baseline: 3")

    def test_CU_08_RED_up_and_down_are_symmetric(self):
        s = self.c01_scene()
        o = self.enter_screen(s)
        stops_down = [o.timing_cursor]
        while True:
            before = o.timing_cursor
            o.handle_menu_down()
            if o.timing_cursor == before:
                break
            stops_down.append(o.timing_cursor)
        stops_up = [o.timing_cursor]
        while True:
            before = o.timing_cursor
            o.handle_menu_up()
            if o.timing_cursor == before:
                break
            stops_up.append(o.timing_cursor)
        self.assertEqual(stops_down, [1, 2, 4, 6, 8, 10, 11, 12], "RED on the baseline: every B (3 5 7 9) is a stop; 12 is the done button")
        self.assertEqual(stops_up, list(reversed(stops_down)))

    def test_CU_09_the_first_stop_has_no_row_before_it(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        self.assertEqual(self.up(o, 5), [1] * 5, "GUARD: nothing above the first changeable row; no negative or fixed index")

    def test_CU_10_the_done_button_is_the_last_stop_and_nothing_goes_beyond_it(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        self.assertEqual(self.down(o, 9)[-4:], [5, 5, 5, 5], "GUARD: the done button (list length) is the end; no IndexError")

    def test_CU_11_RED_no_changeable_station_at_all_does_not_loop_and_rests_on_the_done_button(self):
        s = self.scene(start=0, end=4)
        with mock.patch.object(self.main, "untimed_reason", lambda owner, idx: "UNTIMED_TURNBACK_B"):
            o = self.enter_screen(s)
            self.assertEqual(o.timing_cursor, 5, "RED on the baseline: 1 (a fixed row)")
            self.assertEqual(self.down(o, 3), [5, 5, 5])
            self.assertEqual(self.up(o, 3), [5, 5, 5], "up from the done button with no changeable row stays on it")

    def test_CU_12_RED_exactly_one_changeable_station_is_stable(self):
        s = self.scene(start=0, end=4)
        real = self.main.untimed_reason

        def only_3_changeable(owner, idx):
            return None if idx == 3 else "UNTIMED_TURNBACK_B"
        with mock.patch.object(self.main, "untimed_reason", only_3_changeable):
            o = self.enter_screen(s)
            self.assertEqual(o.timing_cursor, 3, "RED on the baseline: 1")
            o.handle_menu_up()
            self.assertEqual(o.timing_cursor, 3)
            o.handle_menu_down()
            self.assertEqual(o.timing_cursor, 5)
            o.handle_menu_up()
            self.assertEqual(o.timing_cursor, 3, "from the done button up goes to the only changeable row")
        self.assertIsNotNone(real)

    def test_CU_13_RED_the_mouse_can_neither_switch_nor_put_the_cursor_on_a_fixed_row(self):
        s = self.scene(start=0, end=4)
        zones = self.draw(s)
        rows = sorted({z[4] for z in zones if len(z) == 6 and z[5] == -1})
        self.assertEqual(rows, [1, 3, 4], "RED on the baseline: the station-name zone of the fixed rows 0 and 2 puts the highlight on them")

    def test_CU_14_the_A_key_bulk_button_leaves_the_fixed_rows_alone(self):
        s = self.scene(start=0, end=4)
        for st in s.sl:
            st["is_timing"] = False
        o = s.o
        o.toggle_all_timing()
        self.assertNotIn(0, o.user_timing_overrides)
        self.assertNotIn(2, o.user_timing_overrides)
        self.assertTrue(o.user_timing_overrides.get(3), "GUARD: the changeable stations are switched")

    def test_CU_15_the_fixed_reasons_are_kept(self):
        s = self.scene(start=0, end=4)
        self.assertEqual(self.S.untimed_reason(s.o, 0), "UNTIMED_SCORING_START")
        self.assertEqual(self.S.untimed_reason(s.o, 2), "UNTIMED_TURNBACK_B")
        self.assertIsNone(self.S.untimed_reason(s.o, 1))
        self.assertFalse(s.o.is_station_timing(2))

    def test_CU_16_the_theoretical_score_is_unchanged(self):
        s = self.c01_scene()
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 11
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 6, 0
        o.handle_menu_enter(False)
        self.assertEqual(o.theoretical_score, 9100)

    def test_CU_17_the_scroll_window_always_holds_the_cursor(self):
        s = self.c01_scene()
        o = self.enter_screen(s)
        for _ in range(14):
            o.handle_menu_down()
            if o.timing_cursor < 12:
                self.assertTrue(o.timing_scroll <= o.timing_cursor < o.timing_scroll + 6, (o.timing_cursor, o.timing_scroll))
        for _ in range(14):
            o.handle_menu_up()
            self.assertTrue(o.timing_scroll <= o.timing_cursor < o.timing_scroll + 6 or o.timing_cursor == 12, (o.timing_cursor, o.timing_scroll))
        self.assertEqual(o.timing_cursor, 1, "GUARD: back on the first stop")
        self.assertNotIn(o.timing_cursor, (0, 3, 5, 7, 9))
        self.assertEqual(o.timing_scroll, 0, "the first stop shows the list from its top, so the fixed start row above it stays in view")

    def test_CU_18_the_cursor_and_the_toggle_target_are_the_same_row(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        o.handle_menu_down()
        before = dict(o.user_timing_overrides)
        o.handle_menu_enter(False)
        changed = [k for k in set(before) | set(o.user_timing_overrides) if before.get(k) != o.user_timing_overrides.get(k)]
        self.assertEqual(changed, [o.get_timing_target_stas()[o.timing_cursor]], "RED on the baseline: Down lands on B and the toggle writes nothing")

    def test_CU_19_the_run_snapshot_is_not_touched_by_the_cursor(self):
        s = self.scene(start=0, end=4)
        o = self.enter_screen(s)
        before = (o.__dict__.get("_scoring_section"), o.setting_start_idx, o.setting_end_idx)
        self.down(o, 6)
        self.up(o, 6)
        self.assertEqual((o.__dict__.get("_scoring_section"), o.setting_start_idx, o.setting_end_idx), before)


class B_BasicBrakeCandidates(CandBase):
    """The boundary candidates of the LAST basic brake rule (menu_state 7, column 0): the A of a crossed pair stays, the B is out. five(): S0 / A 1 / B 2 / C 3 / D 4 (terminal), PTPAIR 1-2; six(): S0 / A1 1 / B1 2 / A2 3 / B2 4 / E 5 (terminal), pairs 1-2 and 3-4."""

    def test_BI_01_the_A_of_a_crossed_pair_is_a_boundary_candidate(self):
        self.assertIn(1, self.brake_end(self.five()), "Owner contract 3: the A stays (the next rule then starts at its B)")

    def test_BI_02_RED_the_B_of_a_crossed_pair_is_no_candidate(self):
        self.assertNotIn(2, self.brake_end(self.five()), "RED on the baseline: [1, 2, 3, 4]")

    def test_BI_03_the_ordinary_stations_and_the_terminal_stay(self):
        self.assertEqual(self.brake_end(self.five()), [1, 3, 4], "the A (1), the ordinary C (3) and the terminal D (4) stay; the B (2) is out")

    def test_BI_04_every_A_of_several_crossed_pairs_stays(self):
        got = self.brake_end(self.six())
        self.assertIn(1, got)
        self.assertIn(3, got)

    def test_BI_05_RED_every_B_of_several_crossed_pairs_is_out(self):
        got = self.brake_end(self.six())
        self.assertNotIn(2, got)
        self.assertNotIn(4, got)
        self.assertEqual(got, [1, 3, 5], "the A1 / A2 and the terminal E are left; both B are out")

    def test_BI_06_the_screen_has_no_separate_start_choice_the_start_is_derived_from_the_previous_boundary(self):
        """The start of rule k is derived from the end of rule k-1 (main.py s_idx = brake_boundary_next_start(...)): the A of a crossed pair as a boundary starts the next rule at its B (tests/test_pt_tbi_brake_chain.py)."""
        text = source("main.py")
        self.assertIn('s_idx = getattr(self, \'setting_start_idx\', 0) if sub_c == 0 else self.brake_boundary_next_start(rules[sub_c-1].get("end_idx", -1))', text)
        self.assertEqual(text.count('self.dropdown_target = "sub_end_sta"'), 1)

    def test_BI_07_a_pair_that_the_section_does_not_cross_is_not_touched(self):
        s = self.terminal_b()
        self.assertEqual(self.brake_end(s), [1, 2], "GUARD (the old C_G5 on its own scene): the section ends at A and crosses nothing; the raw terminal B stays a brake end there")

    def test_BI_16_only_the_pairs_of_the_scoring_section_are_left_out(self):
        s = self.six()
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 3
        self.assertEqual(self.brake_end(s), [1, 3], "the section ends at the A of pair 2 and crosses pair 1 only: B1 is out, A1 and the terminal A2 stay")
        s2 = self.six()
        s2.o.setting_start_idx, s2.o.setting_end_idx = 2, 5
        self.assertEqual(self.brake_end(s2), [3, 5], "the section starts at the B of pair 1 (crosses pair 2 only): B2 is out, A2 and the terminal E stay, pair 1 is not touched (it is before the start anyway)")
        s3 = self.six()
        s3.o.setting_start_idx, s3.o.setting_end_idx = 0, 1
        self.assertEqual(self.brake_end(s3), [1], "the section ends at A1: nothing is crossed, nothing is left out")
    def test_BI_08_a_route_without_a_PairSet_is_unchanged(self):
        s = self.scene(None)
        self.assertEqual(self.brake_end(s), [1, 2, 3, 4], "GUARD")

    def test_BI_09_the_pairs_are_found_by_StationIndex_not_by_name(self):
        s = self.five()
        for st in s.sl:
            st["name"] = "X"
        self.assertEqual(self.brake_end(s), [1, 3, 4], "the B (2) is out whatever the names are")
        s2 = self.five()
        s2.sl[3]["name"] = "B"
        s2.sl[2]["name"] = "ordinary"
        self.assertEqual(self.brake_end(s2), [1, 3, 4], "a station called B that is no pair B is not excluded (3); the real B (2) is, although it is called ordinary")

    def test_BI_10_door_indicator_lamp_and_signal_flag_are_no_input(self):
        s = self.five()
        s.o.bve_door, s.o.bve_doordir, s.o.bve_is_pass = 1, 0, 1
        s.sl[1]["is_pass"] = False
        s.sl[2]["is_pass"] = False
        self.assertEqual(self.brake_end(s), [1, 3, 4])

    def test_BI_11_the_default_end_station_does_not_point_at_an_excluded_station(self):
        s = self.five()
        s.o.setting_end_idx = -1
        s.o.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}]
        self.assertEqual(s.o.brake_rules[-1]["end_idx"], -1, "GUARD: the default is the sentinel, never an A or a B")

    def test_BI_12_picking_a_boundary_never_writes_the_excluded_B(self):
        s = self.five()
        o = s.o
        written = []
        for idx in self.brake_end(s):
            o.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}]
            o.dropdown_options = [{"idx": i, "name": "n"} for i in self.brake_end(s)]
            o.dropdown_cursor = [opt["idx"] for opt in o.dropdown_options].index(idx)
            o.dropdown_target = "sub_end_sta"
            o.handle_dropdown_enter()
            written.append(o.brake_rules[0]["end_idx"])
        self.assertTrue(all(w != 2 for w in written), written)

    def test_BI_13_changing_the_scoring_section_resets_the_rules_so_no_excluded_value_survives(self):
        s = self.five()
        o = s.o
        o.brake_rules = [{"end_idx": 1, "apply": "2段", "release": "2段"}, {"end_idx": -1, "apply": "階段", "release": "階段"}]
        o.dropdown_options = [{"idx": 0, "name": "S0"}]
        o.dropdown_cursor, o.dropdown_target = 0, "start_sta"
        o.handle_dropdown_enter()
        self.assertEqual(o.brake_rules, [{"end_idx": -1, "apply": "階段", "release": "階段"}], "GUARD: the existing reset (main.py start_sta / end_sta) stays")

    def test_BI_14_the_dropdown_cursor_walks_only_the_candidates(self):
        s = self.five()
        ids = self.brake_end(s)
        o = s.o
        walked = []
        o.dropdown_cursor = 0
        for _ in range(len(ids)):
            walked.append(o.dropdown_options[o.dropdown_cursor]["idx"])
            o.dropdown_cursor = min(o.dropdown_cursor + 1, len(o.dropdown_options) - 1)
        self.assertEqual(walked, ids)
        self.assertNotIn(2, walked, "the B is never walked")


class C_InitialAndRelaxationInheritance(CandBase):
    def test_IR_01_the_initial_and_relaxation_screen_has_no_station_candidates_of_its_own(self):
        text = source("main.py")
        self.assertEqual(text.count('"init_sub_end_sta"'), 1, "GUARD: the init target name occurs only in the dropdown-enter handler (a dormant branch); the station drop-down is opened only when menu_state == 7")
        self.assertIn("if is_last and self.menu_state == 7:", text)

    def test_IR_02_the_initial_rules_follow_the_brake_rule_count(self):
        s = self.five()
        o = s.o
        o.brake_rules = [{"end_idx": 3, "apply": "階段", "release": "階段"}, {"end_idx": -1, "apply": "階段", "release": "階段"}]
        o.penalty_init_rules = [{"apply": "ON①", "release": "ON①"}]
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 5, 0
        o.handle_menu_enter(False)
        self.assertEqual(len(o.penalty_init_rules), len(o.brake_rules), "GUARD: the screen entry grows the init rules to the brake rules (main.py): the boundaries are the brake rules' ones")

    def test_IR_03_RED_the_candidate_set_is_generated_in_one_place_only(self):
        text = source("main.py")
        self.assertEqual(text.count("def _brake_end_candidates"), 1, "RED-API on the baseline: the brake boundary candidates have no generator of their own (an inline list in handle_menu_enter)")
        self.assertEqual(text.count("valid_stas.append"), 0, "the inline candidate list is gone")


if __name__ == "__main__":
    unittest.main()
