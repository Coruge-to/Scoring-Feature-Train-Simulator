"""Stage TB-H Stage 5a: the bulk button ('A') of the timing-setting screen. The BEHAVIOUR is the existing one (audited 2026-11-02: it already satisfies the Owner contract) and is fixed here as permanent GUARDs; only the LABEL changes.

Owner contract (after the TB-G / TB-H C-06 live run):
  * the bulk button is shown only when a CHANGEABLE untimed station exists; the fixed untimed stations (the start of the Run, the crossed pair B, any other fixed one) are never counted
  * its label is ONE text for every route (no case split on the pseudo-turnback): 変更可能な非採時駅を全て採時駅にする : A  (the old text 始発駅以外を採時駅にする : A must not remain)
  * the A key makes only the changeable untimed stations timed; it never writes an override for a fixed station and never changes a fixed reason (UNTIMED_SCORING_START / UNTIMED_TURNBACK_B), the Run snapshot or the theoretical score (9100 on the C-01 shape)
  * the one key keeps its two roles: after a user change it is the reset ('初期設定に戻す : A', the existing text, behaviour and priority); without a user change it makes the changeable untimed stations timed; with no changeable untimed station and no user change the button is hidden
The REAL handlers and the REAL screen (menu_ui.draw_menu on an offscreen QImage) are driven. RED = fails on the baseline fe8c26d (only the LABEL assertions); GUARD = passes on the baseline and must keep passing."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbd_snapshot import Base as SnapshotBase, setUpModule, tearDownModule  # noqa: E402,F401

UNTIMED_B = "UNTIMED_TURNBACK_B"
UNTIMED_START = "UNTIMED_SCORING_START"
NEW_LABEL = "変更可能な非採時駅を全て採時駅にする : A"
OLD_LABEL = "始発駅以外を採時駅にする : A"
RESET_LABEL = "初期設定に戻す : A"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class Base(SnapshotBase):
    def draw(self, s):
        from PyQt6.QtGui import QImage, QPainter
        import menu_ui
        o = s.o
        calls = []
        original = menu_ui.draw_text_with_outline

        def record(painter, text, *args, **kwargs):
            calls.append(text)
            return original(painter, text, *args, **kwargs)
        menu_ui.draw_text_with_outline = record
        self.addCleanup(setattr, menu_ui, "draw_text_with_outline", original)
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
        # Stage UI-D3 (on purpose): the scoring page 1/3 is drawn behind the panel (dimmed): the texts of the TIMING PANEL are the ones after its title
        calls = calls[calls.index("=== 運転時分 設定 ==="):]
        return calls, list(o.menu_click_zones)

    @staticmethod
    def status_of(calls, name):
        return calls[calls.index(name) + 1]

    def press_a(self, s):
        """the sink of the A key (main.py: key == 'a' and menu_state == 8) and of the click zone 998"""
        s.o.menu_state = 8
        s.o.toggle_all_timing()

    def changeable_untimed(self, o):
        return [i for i in o.get_timing_target_stas() if o.untimed_reason(i) is None and not o.is_station_timing(i)]

    def fixed_untimed(self, o):
        return {i: o.untimed_reason(i) for i in o.get_timing_target_stas() if o.untimed_reason(i) is not None}

    def c01_scene(self):
        s = self.P.Scene(self, with_pairs=False)
        names = ["W", "X", "A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4", "Y", "Z"]
        sl = [self.P.station(n, 500.0 * i, raw_dep=self.P.T0 + 1000 * i, raw_arr=self.P.T0 + 1000 * i) for i, n in enumerate(names)]
        sl[-1]["is_terminal"] = True
        s.o.station_list = s.sl = sl
        ps, why = self.PC.decode_ptpair("PTPAIR:1:%s:12:4:2-3-0;4-5-0;6-7-0;8-9-0" % self.P.R.SCOPE_LIST_ID, 12)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 11
        return s

    def theory(self, o, start, end):
        o.setting_start_idx, o.setting_end_idx = start, end
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 6, 0
        o.handle_menu_enter(False)
        o.menu_state = 8
        return o.theoretical_score


class A_Label(Base):
    def test_BB_03_RED_the_label_is_exactly_the_Owner_text_and_has_one_branch(self):
        text = read("menu_ui.py")
        self.assertEqual(text.count('btn_a_text = "' + NEW_LABEL + '"'), 1, "RED on the baseline: the label is still the old text")
        self.assertEqual(text.count(RESET_LABEL), 1, "the reset label keeps its text")
        i = text.index('btn_a_text = "' + NEW_LABEL + '"')
        block = text[max(0, i - 400):i + 200].lower()
        for word in ("pairset", "turnback", "machine", "pseudo"):
            self.assertNotIn(word, block, "the label branch does not look at the pseudo-turnback (no case split)")

    def test_BB_04_RED_the_old_label_does_not_remain_anywhere_in_the_screen_source_or_the_drawn_texts(self):
        self.assertNotIn(OLD_LABEL, read("menu_ui.py"), "RED on the baseline")
        self.assertNotIn("始発駅以外", read("menu_ui.py").split("# 採点設定2ページ目の減点項目を描画する")[0].split("TIMING_SUB_H")[-1], "the word 始発駅 is gone from the button branch")
        s = self.scene(start=0, end=4)
        s.sl[3]["is_timing"] = False
        calls, _ = self.draw(s)
        self.assertNotIn(OLD_LABEL, calls)
        self.assertNotIn("始発駅以外を採時駅にする", "".join(calls))

    def test_BB_17_RED_without_a_PairSet_the_same_single_label_is_drawn(self):
        s = self.P.Scene(self, with_pairs=False)
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 4
        s.sl[3]["is_timing"] = False
        calls, _ = self.draw(s)
        self.assertIn(NEW_LABEL, calls, "no pseudo-turnback: the same label (no case split)")
        s2 = self.scene(start=0, end=4)
        s2.sl[3]["is_timing"] = False
        calls2, _ = self.draw(s2)
        self.assertIn(NEW_LABEL, calls2, "with a PairSet: the same label")


class B_NoChangeableUntimed(Base):
    """fixed untimed stations only (the C-06 route): the start and the crossed pair B untimed, every other station timed"""

    def test_BB_01_GUARD_hidden_and_A_changes_nothing(self):
        s = self.scene(start=0, end=4)
        o = s.o
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B})
        self.assertEqual(self.changeable_untimed(o), [])
        calls, zones = self.draw(s)
        self.assertNotIn(NEW_LABEL, calls)
        self.assertNotIn(OLD_LABEL, calls)
        self.assertNotIn(RESET_LABEL, calls)
        self.assertNotIn(998, [z[4] for z in zones if len(z) == 5], "no click zone for the button either")
        before = {i: o.is_station_timing(i) for i in range(5)}
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {}, "the key changes nothing: no override written")
        self.assertEqual({i: o.is_station_timing(i) for i in range(5)}, before)
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B})

    def test_BB_01b_GUARD_fixed_stations_whose_station_data_is_untimed_are_not_counted_either(self):
        s = self.scene(start=0, end=4)
        o = s.o
        s.sl[0]["is_timing"] = False
        s.sl[2]["is_timing"] = False
        self.assertEqual(self.changeable_untimed(o), [])
        calls, _ = self.draw(s)
        self.assertNotIn(NEW_LABEL, calls)
        self.assertNotIn(RESET_LABEL, calls)
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {})
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B})

    def test_BB_11_GUARD_stale_overrides_on_the_fixed_stations_never_make_them_timed(self):
        s = self.scene(start=0, end=4)
        o = s.o
        o.user_timing_overrides[0] = True                  # direct writes by another route
        o.user_timing_overrides[2] = True
        calls, _ = self.draw(s)
        self.assertNotIn(NEW_LABEL, calls)
        self.assertNotIn(RESET_LABEL, calls, "the stale overrides on fixed stations are not a user change")
        self.assertEqual(self.status_of(calls, "S0"), "非採時")
        self.assertEqual(self.status_of(calls, "B"), "非採時")
        self.press_a(s)
        self.assertFalse(o.is_station_timing(0))
        self.assertFalse(o.is_station_timing(2))
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B})

    def test_BB_08_GUARD_B_as_the_start_of_the_Run_is_fixed_untimed_too_and_never_switched_on(self):
        s = self.scene(start=2, end=4)                     # B (2) is the START: UNTIMED_SCORING_START, the section does not cross the pair
        o = s.o
        self.assertEqual(self.fixed_untimed(o), {2: UNTIMED_START})
        s.sl[3]["is_timing"] = False
        s.sl[4]["is_timing"] = False
        self.press_a(s)
        self.assertEqual(sorted(o.user_timing_overrides), [3, 4])
        self.assertNotIn(2, o.user_timing_overrides)
        self.assertFalse(o.is_station_timing(2))
        self.assertEqual(self.fixed_untimed(o), {2: UNTIMED_START})

    def test_BB_08b_GUARD_the_station_outside_the_pair_crossing_is_ordinary_and_changeable(self):
        s = self.scene(start=1, end=4)                     # the start is A (1): B (2) is NOT crossed (qualifying_pair), so B is an ordinary station here
        o = s.o
        self.assertEqual(self.fixed_untimed(o), {1: UNTIMED_START})
        s.sl[2]["is_timing"] = False
        self.assertEqual(self.changeable_untimed(o), [2])


class C_OneChangeableUntimed(Base):
    """control: ONE ordinary changeable station is untimed by the station data; the start and pair B are fixed untimed"""

    def fixture(self):
        s = self.scene(start=0, end=4)
        s.sl[3]["is_timing"] = False                       # C
        return s

    def test_BB_02_RED_the_button_is_shown_when_a_changeable_untimed_station_exists(self):
        s = self.fixture()
        o = s.o
        self.assertEqual(self.changeable_untimed(o), [3])
        calls, zones = self.draw(s)
        self.assertIn(NEW_LABEL, calls, "RED on the baseline: the label is still the old text")
        self.assertNotIn(RESET_LABEL, calls)
        self.assertIn(998, [z[4] for z in zones if len(z) == 5], "and its click zone")
        self.assertEqual(self.status_of(calls, "C"), "非採時")

    def test_BB_05_GUARD_A_makes_only_the_changeable_untimed_station_timed(self):
        s = self.fixture()
        o = s.o
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {3: True}, "only the changeable station gets an override")
        self.assertTrue(o.is_station_timing(3))
        self.assertFalse(o.is_station_timing(0))
        self.assertFalse(o.is_station_timing(2))
        calls2, _ = self.draw(s)
        self.assertEqual(self.status_of(calls2, "C"), "採時")
        self.assertEqual(self.status_of(calls2, "S0"), "非採時")
        self.assertEqual(self.status_of(calls2, "B"), "非採時")
        self.assertEqual(self.changeable_untimed(o), [])

    def test_BB_06_07_09_10_GUARD_no_override_for_the_start_or_B_and_the_two_reasons_are_kept(self):
        s = self.fixture()
        o = s.o
        self.press_a(s)
        self.assertNotIn(0, o.user_timing_overrides, "the start")
        self.assertNotIn(2, o.user_timing_overrides, "pair B")
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B}, "UNTIMED_SCORING_START and UNTIMED_TURNBACK_B are kept")

    def test_BB_18_GUARD_the_screen_and_the_internal_value_agree_for_every_station_before_and_after(self):
        s = self.fixture()
        o = s.o
        for phase in ("before", "after"):
            calls, _ = self.draw(s)
            for idx in o.get_timing_target_stas():
                self.assertEqual(self.status_of(calls, s.sl[idx]["name"]), "採時" if o.is_station_timing(idx) else "非採時", "%s %s" % (phase, s.sl[idx]["name"]))
            if phase == "before":
                self.press_a(s)

    def test_BB_12_GUARD_the_Run_snapshot_keeps_the_start_and_B_untimed_after_A(self):
        s = self.fixture()
        o = s.o
        self.press_a(s)
        self.press_start(s)
        snapshot = self.snap(s)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.pairs, s.machine.fixed)
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B}, "in the Run: reasons from the snapshot")
        self.assertFalse(o.is_station_timing(0))
        self.assertFalse(o.is_station_timing(2))
        self.assertTrue(o.is_station_timing(3), "the changeable station that A made timed stays timed in the Run")
        self.assertNotIn(0, o.user_timing_overrides)
        self.assertNotIn(2, o.user_timing_overrides)

    def test_BB_16_RED_the_second_press_is_the_reset_with_its_existing_text_behaviour_and_priority(self):
        s = self.fixture()
        o = s.o
        self.press_a(s)
        calls, _ = self.draw(s)
        self.assertIn(RESET_LABEL, calls, "after A the screen differs from the data default: the same key now offers the reset")
        self.assertNotIn(NEW_LABEL, calls)
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {}, "reset")
        self.assertFalse(o.is_station_timing(3), "back to the data default (untimed)")
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B})
        calls2, _ = self.draw(s)
        self.assertIn(NEW_LABEL, calls2, "RED on the baseline (new label): the bulk label is back")

    def test_BB_16b_GUARD_a_user_change_to_untimed_shows_the_reset_label_not_the_bulk_label(self):
        s = self.scene(start=0, end=4)
        o = s.o
        o.menu_state, o.timing_cursor = 8, o.get_timing_target_stas().index(1)
        o.handle_menu_enter(False)                         # A (ordinary) timed -> untimed by the user
        self.assertEqual(self.changeable_untimed(o), [1])
        calls, _ = self.draw(s)
        self.assertIn(RESET_LABEL, calls)
        self.assertNotIn(NEW_LABEL, calls, "the reset has the priority while the screen differs from the data default (existing design)")
        self.assertNotIn(OLD_LABEL, calls)
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {}, "the key resets to the data default: A is timed again")
        self.assertTrue(o.is_station_timing(1))
        self.assertEqual(self.fixed_untimed(o), {0: UNTIMED_START, 2: UNTIMED_B})

    def test_BB_15_GUARD_A_acts_only_on_the_stations_of_the_screen_not_on_stations_outside_the_chosen_section(self):
        s = self.scene(start=0, end=1)                     # the screen lists S0 and A only
        o = s.o
        s.sl[3]["is_timing"] = False                       # C and D are outside the section and untimed in the data
        s.sl[4]["is_timing"] = False
        self.assertEqual(o.get_timing_target_stas(), [0, 1])
        self.assertEqual(self.changeable_untimed(o), [], "nothing on the screen is changeable-untimed")
        calls, _ = self.draw(s)
        self.assertNotIn(NEW_LABEL, calls)
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {}, "stations outside the screen get no override")


class D_TheoreticalScoreAndC01Shape(Base):
    FIXED = {0: UNTIMED_START, 3: UNTIMED_B, 5: UNTIMED_B, 7: UNTIMED_B, 9: UNTIMED_B}

    def test_BB_14_GUARD_C01_shape_9100_is_kept_when_A_makes_an_untimed_ordinary_station_timed(self):
        s = self.c01_scene()
        o = s.o
        self.assertEqual(self.theory(o, 0, 11), 9100)
        s.sl[10]["is_timing"] = False                      # Y: ordinary, untimed in the data
        self.assertEqual(self.changeable_untimed(o), [10])
        self.assertEqual(self.fixed_untimed(o), self.FIXED)
        self.assertEqual(self.theory(o, 0, 11), 9100 - 300, "before A: Y is not an operating-time station")
        self.press_a(s)
        self.assertEqual(dict(o.user_timing_overrides), {10: True})
        self.assertEqual(self.theory(o, 0, 11), 9100, "after A: 9100 (X, A1..A4, Y, Z are the seven scored stations)")
        self.assertEqual(self.fixed_untimed(o), self.FIXED)

    def test_BB_13_GUARD_B_never_re_enters_the_theoretical_score_whatever_A_does(self):
        s = self.c01_scene()
        o = s.o
        for st in s.sl:
            st["is_timing"] = False
        self.assertEqual(sorted(self.changeable_untimed(o)), [1, 2, 4, 6, 8, 10, 11])
        self.press_a(s)
        self.assertEqual(sorted(o.user_timing_overrides), [1, 2, 4, 6, 8, 10, 11], "exactly the seven scored stations; B1..B4 and the start get nothing")
        self.assertEqual(self.theory(o, 0, 11), 9100)
        self.assertEqual(self.fixed_untimed(o), self.FIXED)
        for fixed in self.FIXED:
            self.assertFalse(o.is_station_timing(fixed))
            self.assertNotIn(fixed, o.user_timing_overrides)

    def test_BB_08c_GUARD_the_Run_snapshot_of_the_C01_shape_after_A_still_has_the_four_B_untimed(self):
        s = self.c01_scene()
        o = s.o
        s.sl[10]["is_timing"] = False
        self.press_a(s)
        self.press_start(s)
        snapshot = self.snap(s)
        self.assertEqual(frozenset(p.departure for p in snapshot.pairs), frozenset({3, 5, 7, 9}))
        for b in (3, 5, 7, 9):
            self.assertEqual(o.untimed_reason(b), UNTIMED_B)
            self.assertFalse(o.is_station_timing(b))
        self.assertEqual(o.untimed_reason(0), UNTIMED_START)


class E_Dispatch(Base):
    def test_BB_19_GUARD_the_A_key_and_the_click_zone_998_reach_the_same_sink_and_no_third_route_exists(self):
        main_src = read("main.py")
        self.assertIn("elif key == 'a' and self.menu_state == 8:", main_src)
        i = main_src.index("elif key == 'a' and self.menu_state == 8:")
        self.assertIn("self.toggle_all_timing()", main_src[i:i + 200])
        j = main_src.index("elif action_idx == 998:")
        self.assertIn("self.toggle_all_timing()", main_src[j:j + 120])
        self.assertEqual(main_src.count("self.toggle_all_timing()"), 2, "no third route")


if __name__ == "__main__":
    unittest.main()
