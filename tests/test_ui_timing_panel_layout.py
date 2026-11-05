"""Stage UI-1: the timing-setting screen (menu_state 8). The bulk button label of the Owner ('変更可能な非採時駅を全て採時駅にする : A', right-aligned at the bottom of the frame) was so long that it reached the centre of the
frame and touched the centred done button ('設定完了'), found on the live run S-01b (2026-11-05, photo 094213). The frame is now TIMING_EXTRA_H (80) logical pixels taller, split top and bottom, so that

  * the frame stays centred on the 1920 x 1080 base screen (UI-C),
  * every other element - the title, the arrows, the rows and their click zones, the done button, the 'Esc'-like corner button - keeps EXACTLY its screen position (UI-P, the zones are pinned to the values measured on the baseline 81b4f41),
  * the bulk / reset button no longer touches the done button (UI-G: a gap of at least 16 px, also between the click zones) and stays inside the frame (UI-I).
The REAL screen (menu_ui.draw_menu on an offscreen QImage) is driven. RED = fails on the baseline 81b4f41 (the overlap, the panel size); GUARD = passes on the baseline and must keep passing."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbh_bulk_timing_button import Base, setUpModule, tearDownModule  # noqa: E402,F401

NEW_LABEL = "変更可能な非採時駅を全て採時駅にする : A"
RESET_LABEL = "初期設定に戻す : A"
ACTION_BULK = 998
ACTION_CLOSE = 999
GAP_MIN = 16.0

# the baseline 81b4f41 (measured on the real screen, the scene of test_pt_tbh_bulk_timing_button: start 0, end 4): every click zone except the bulk button (998)
BASELINE_ZONES_EXCEPT_BULK = [
    (410.0, 403.0, 1510.0, 473.0, 1, -1),
    (425.0, 403.0, 469.0, 473.0, 1, -1),
    (410.0, 553.0, 1510.0, 623.0, 3, -1),
    (425.0, 553.0, 469.0, 623.0, 3, -1),
    (410.0, 628.0, 1510.0, 698.0, 4, -1),
    (425.0, 628.0, 469.0, 698.0, 4, -1),
    (846.0, 868.0, 1059.0, 938.0, 5),
    (1680.0, 1022.0, 1910.0, 1070.0, 999),
]


def zone_of(zones, action):
    found = [z for z in zones if len(z) == 5 and z[4] == action]
    return found[0] if found else None


class Layout(Base):
    def drawn(self, bulk):
        s = self.scene(start=0, end=4)
        if bulk:
            s.sl[3]["is_timing"] = False                       # one changeable untimed station: the bulk label is drawn
        calls, zones = self.draw(s)
        return s, calls, zones

    def targets_len(self, s):
        return len(s.o.get_timing_target_stas())

    def test_UI_G1_RED_the_long_bulk_label_does_not_touch_the_done_button(self):
        s, calls, zones = self.drawn(True)
        self.assertIn(NEW_LABEL, calls)
        bulk, done = zone_of(zones, ACTION_BULK), zone_of(zones, self.targets_len(s))
        self.assertIsNotNone(bulk)
        self.assertIsNotNone(done)
        gap = bulk[1] - done[3]                               # the bulk button lies below the done button
        self.assertGreaterEqual(gap, GAP_MIN, "RED on the baseline (the zones overlap by 16 px): gap=%s" % gap)

    def test_UI_G2_RED_the_reset_label_has_a_gap_too(self):
        s = self.scene(start=0, end=4)
        s.o.menu_state, s.o.timing_cursor = 8, s.o.get_timing_target_stas().index(1)
        s.o.handle_menu_enter(False)                           # a user change: the reset label
        calls, zones = self.draw(s)
        self.assertIn(RESET_LABEL, calls)
        bulk, done = zone_of(zones, ACTION_BULK), zone_of(zones, self.targets_len(s))
        self.assertGreaterEqual(bulk[1] - done[3], GAP_MIN)

    def test_UI_I1_GUARD_the_button_stays_inside_the_frame_with_a_margin(self):
        for bulk in (True, False):
            s, calls, zones = self.drawn(bulk)
            if not bulk:
                s.o.menu_state, s.o.timing_cursor = 8, s.o.get_timing_target_stas().index(1)
                s.o.handle_menu_enter(False)
                calls, zones = self.draw(s)
            z = zone_of(zones, ACTION_BULK)
            self.assertIsNotNone(z)
            x0, y0, x1, y1 = s.o.active_panel_rect
            self.assertGreaterEqual(z[0], x0 + 10)
            self.assertLessEqual(z[2], x1 - 10)
            self.assertGreaterEqual(z[1], y0 + 10)
            self.assertLessEqual(z[3], y1 - 10, "inside the frame, 10 px from the bottom edge at least")

    def test_UI_C1_RED_the_frame_is_taller_and_stays_centred_on_the_base_screen(self):
        s, _, _ = self.drawn(True)
        x0, y0, x1, y1 = s.o.active_panel_rect
        self.assertEqual((x1 - x0), 1300.0)
        self.assertEqual((y1 - y0), 980.0, "RED on the baseline: 900")
        self.assertEqual((x0 + x1) / 2.0, 960.0, "centred horizontally")
        self.assertEqual((y0 + y1) / 2.0, 540.0, "centred vertically")
        self.assertGreaterEqual(y0, 20.0)
        self.assertLessEqual(y1, 1060.0, "the taller frame fits the 1080 high base screen")

    def test_UI_P1_GUARD_every_other_click_zone_keeps_its_screen_position(self):
        for bulk in (True, False):
            _, _, zones = self.drawn(bulk)
            others = [tuple(z) for z in zones if not (len(z) == 5 and z[4] == ACTION_BULK)]
            self.assertEqual(others, BASELINE_ZONES_EXCEPT_BULK, "the rows, the done button and the corner button do not move (bulk=%s)" % bulk)

    def test_UI_P2_RED_the_content_offsets_are_measured_in_the_base_frame_and_the_extra_height_is_split(self):
        text = open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8").read()
        self.assertIn("TIMING_BASE_H = 900", text)
        self.assertIn("TIMING_EXTRA_H = 80", text)
        self.assertIn("TIMING_SUB_H = TIMING_BASE_H + TIMING_EXTRA_H", text)
        self.assertIn("CONTENT_Y = SUB_Y + TIMING_EXTRA_H / 2", text)
        for line in ("TITLE_Y = CONTENT_Y + TIMING_TITLE_Y_OFFSET", "ARROW_UP_Y = CONTENT_Y + TIMING_ARROW_UP_Y_OFFSET", "LIST_Y = CONTENT_Y + TIMING_LIST_Y_OFFSET", "BTN_Y = CONTENT_Y + TIMING_BASE_H - TIMING_BTN_Y_OFFSET"):
            self.assertIn(line, text, line)

    def test_UI_P3_GUARD_the_label_texts_and_the_branch_are_unchanged(self):
        text = open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8").read()
        self.assertEqual(text.count('btn_a_text = "' + NEW_LABEL + '"'), 1)
        self.assertEqual(text.count('btn_a_text = "' + RESET_LABEL + '"'), 1)
        s, calls, zones = self.drawn(False)
        self.assertNotIn(NEW_LABEL, calls)
        self.assertIsNone(zone_of(zones, ACTION_BULK), "no changeable untimed station and no user change: no button")


if __name__ == "__main__":
    unittest.main()
