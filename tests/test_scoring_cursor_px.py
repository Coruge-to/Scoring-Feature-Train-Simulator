"""Owner's visual adjustments of the scoring setting cursors (2026-11-09, after the live smoke; baseline = f8d1f11 + the environment settings padding). Owner convention: "+" increases, "-" cuts:
LEFT "-n" = n px cut from the left side (the left edge moves to the right), RIGHT "+n" = the right side extended by n px, RIGHT "-n" = n px cut from the right side. Only the drawn cursor rectangles change (no text, no zone, no state).
  (cumulative totals vs f8d1f11)
  1/3: scoring section stations A: left -3 / right +3, B: left -3 / right +3 | stop distance (XXX m): left -2 / right +2 | "変更": right +3 | summary after the basic brake setting: left -6 / right +3
  basic brake setting: station name left -2 / right +4, the "n段 制動" cell left -2 / right +2, the "m段 緩め" cell left -2 / right +2
  2/3: ON right +4, OFF right +3 | "変更": right +3 | summary after the initial / release setting: left -6 / right -13 | initial / release setting: the initial value right +2, the release value left -1 / right +3
  the item name cursors of the scoring items (1/3: 採点区間 .. 基本制動, 2/3: 転動 .. 非常ブレーキ, 初動・緩和ブレーキ): right +1
  3/3 A boundary input: a red underscore in front of the % until a digit is typed (as at the stop distance), 2 digits at most (the stop distance keeps 3).
The REAL menu_ui.draw_menu (sia_rig Overlay) is driven. The environment settings screen keeps its own +4 / +2 (tests/test_env_settings_layout.py)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sia_rig as R  # noqa: E402

GLOBAL_BOX_X_OFFSET = -3
SUMMARY_X0 = 550 + 50 - 20 + GLOBAL_BOX_X_OFFSET
_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-scoring-cursor-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP["dir"].name)
    finally:
        for k, v in _TMP["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP["dir"].cleanup()
    if left:
        raise AssertionError("the scoring cursor module wrote into the redirected profile: %r" % (left,))


class Cursors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["scoring-cursor"])
        import main
        cls.main = main

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        o = self.o = self.rig.o
        o.station_list = [R.station("Stn%02d" % i, 500.0 * i, terminal=(i == 11)) for i in range(12)]
        o.setting_start_idx, o.setting_end_idx = 0, 11
        o.brake_rules = [{"end_idx": 3, "apply": "2段", "release": "3段"}, {"end_idx": 7, "apply": "OFF", "release": "OFF"}, {"end_idx": -1, "apply": "2段", "release": "3段"}]
        o.penalty_init_rules = [{"apply": "ON①", "release": "ON②"}, {"apply": "OFF", "release": "ON①"}, {"apply": "ON②", "release": "OFF"}]
        o.show_help = False
        o.dropdown_active = False
        o.dropdown_options = []
        o.dropdown_scroll = o.dropdown_cursor = 0
        o.timing_scroll = o.timing_cursor = 0
        o.sub_scroll = o.init_sub_scroll = o.summary_scroll = o.init_summary_scroll = 0
        o.setting_stop_distance = 50
        o.width, o.height = (lambda: 1920), (lambda: 1080)

    def render(self, state, **attrs):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QImage, QPainter
        import menu_ui
        o = self.o
        o.menu_cursor, o.menu_cursor_x = 3, 0
        o.input_mode_active = False
        for k, v in attrs.items():
            setattr(o, k, v)
        o.menu_state = state
        rects, texts = [], []
        kinds = {(30, 80, 150, 200): "cursor", (30, 80, 150, 150): "summary", (150, 50, 50, 200): "input"}
        original = menu_ui.draw_text_with_outline

        def col(c):
            return tuple(c) if isinstance(c, (tuple, list)) else (c.red(), c.green(), c.blue(), c.alpha())

        class Spy(QPainter):
            def drawRoundedRect(self, *a):
                b = self.brush().color()
                kind = kinds.get((b.red(), b.green(), b.blue(), b.alpha()))
                if kind and self.pen().style() == Qt.PenStyle.NoPen:
                    rects.append((kind, tuple(float(v) for v in a[:4])))
                return super().drawRoundedRect(*a)

        def record(painter, t, font, tc, oc, x, y, align="left", passes=8):
            texts.append((str(t), float(x), float(y), align, col(tc), col(oc)))
            return original(painter, t, font, tc, oc, x, y, align, passes)
        menu_ui.draw_text_with_outline = record
        o.menu_click_zones = []
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        image.fill(QColor(58, 66, 78))
        painter = Spy(image)
        try:
            menu_ui.draw_menu(o, painter, 1920.0)
        finally:
            painter.end()
            menu_ui.draw_text_with_outline = original
        return rects, texts

    def fm(self):
        from PyQt6.QtGui import QFontMetrics
        return QFontMetrics(self.o.font_menu)

    def one(self, rects):
        self.assertEqual(len(rects), 1, rects)
        return rects[0][1]

    def xs(self, texts, s):
        return [t[1] for t in texts if t[0] == s]

    # ------------------------------------------------------------------ 1/3
    def test_01_the_scoring_section_stations(self):
        fm = self.fm()
        for idx, cut in ((0, 3), (1, 3)):
            rects, texts = self.render(5, menu_cursor=0, menu_cursor_x=idx)
            x, y, w, h = self.one(rects)
            name = "Stn00" if idx == 0 else "Stn11"
            self.assertIn(x - (-10 + GLOBAL_BOX_X_OFFSET + cut), self.xs(texts, name), "%s side: the left side is cut by %d px (the text did not move)" % ("A" if idx == 0 else "B", cut))
            self.assertEqual(w, fm.horizontalAdvance(name) + 20, "left -%d and right +%d: the width is the old one, the whole cursor is %d px to the right" % (cut, cut, cut))

    def test_02_the_stop_distance_gets_two_pixels_and_keeps_its_input_colour(self):
        fm = self.fm()
        rects, texts = self.render(5, menu_cursor=1, menu_cursor_x=0)
        x, y, w, h = self.one(rects)
        self.assertIn(x, [t - 10 + GLOBAL_BOX_X_OFFSET + 2 for t in self.xs(texts, "50")], "left -2: the left edge moves 2 px inward")
        self.assertEqual(w, fm.horizontalAdvance("50") + 20, "left -2 / right +2: the width is the old one")
        rects, texts = self.render(5, menu_cursor=1, menu_cursor_x=0, input_mode_active=True, input_buffer="12", input_fresh=False)
        kind, (x, y, w, h) = rects[0]
        self.assertEqual((kind, w), ("input", fm.horizontalAdvance("12") + 20), "the input cursor keeps its red and follows")
        rects, texts = self.render(5, menu_cursor=1, menu_cursor_x=0, input_mode_active=True, input_buffer="", input_fresh=True)
        self.assertIn("_", [t[0] for t in texts], "the stop distance shows the underscore while empty")

    def test_03_the_change_cursors_get_two_pixels_on_the_right(self):
        fm = self.fm()
        w0 = fm.horizontalAdvance("変更")
        for state, cur, name in ((5, 2, "1/3 運転時分"), (5, 4, "1/3 基本制動"), (6, 5, "2/3 初動・緩和")):
            rects, texts = self.render(state, menu_cursor=cur, menu_cursor_x=0)
            x, y, w, h = self.one(rects)
            self.assertIn(x, [t - 10 + GLOBAL_BOX_X_OFFSET for t in self.xs(texts, "変更")], "%s: the left edge is the old one" % name)
            self.assertEqual(w, w0 + 20 + 3, "%s: right +3" % name)

    def test_04_the_summary_after_the_basic_brake_setting(self):
        rects, texts = self.render(5, menu_cursor=4, menu_cursor_x=1)
        kind, (x, y, w, h) = rects[0]
        self.assertEqual((kind, x, w), ("summary", SUMMARY_X0 + 6, 1210 - 3), "left -6 (the left edge moves 6 px to the right), right +3")
        self.assertEqual(x + w, SUMMARY_X0 + 1210 + 3, "the right edge is 3 px beyond the old one")

    def test_05_the_basic_brake_setting_station_and_the_two_n_step_cells(self):
        fm = self.fm()
        rects, texts = self.render(7, sub_cursor=2, sub_cursor_x=0)
        x, y, w, h = self.one(rects)
        self.assertIn(x, [t - 10 + GLOBAL_BOX_X_OFFSET + 2 for t in self.xs(texts, "Stn11")], "the station name: left -2")
        self.assertEqual(w, fm.horizontalAdvance("Stn11") + 20 + 2, "left -2 / right +4: the width grows by 2")
        for row, idx, s, cut in ((2, 1, "2段", 2), (0, 0, "2段", 2), (2, 2, "3段", 2), (0, 1, "3段", 2)):
            rects, texts = self.render(7, sub_cursor=row, sub_cursor_x=idx)
            x, y, w, h = self.one(rects)
            self.assertIn(x, [t - 10 + GLOBAL_BOX_X_OFFSET + cut for t in self.xs(texts, s)], "row %d cell %d (%s): left -%d; the text did not move" % (row, idx, s, cut))
            self.assertEqual(w, fm.horizontalAdvance(s) + 20, "row %d cell %d: left -%d / right +%d: the width is the old one (both cells 2)" % (row, idx, cut, cut))
        rects, texts = self.render(7, sub_cursor=1, sub_cursor_x=0)                                   # the OFF cell is not part of the request
        x, y, w, h = self.one(rects)
        self.assertEqual(w, fm.horizontalAdvance("OFF") + 20)
        self.assertIn(x, [t - 10 + GLOBAL_BOX_X_OFFSET for t in self.xs(texts, "OFF")])

    # ------------------------------------------------------------------ 2/3
    def test_06_on_gets_two_pixels_and_off_one(self):
        fm = self.fm()
        for row in (2, 3, 4):
            for on in (True, False):
                rects, texts = self.render(6, menu_cursor=row, menu_cursor_x=0, pen_limit=on, pen_jerk=on, pen_eb=on)
                x, y, w, h = self.one(rects)
                s = "ON" if on else "OFF"
                self.assertEqual(w, fm.horizontalAdvance(s) + 20 + (4 if on else 3), "row %d %s" % (row, s))

    def test_07_the_summary_after_the_initial_release_setting(self):
        rects, texts = self.render(6, menu_cursor=5, menu_cursor_x=1)
        kind, (x, y, w, h) = rects[0]
        self.assertEqual((kind, x, w), ("summary", SUMMARY_X0 + 6, 1210 - 19), "left -6, right -13")
        self.assertEqual(x + w, SUMMARY_X0 + 1210 - 13, "the right edge is 13 px short of the old one")

    def test_08_the_initial_value_gets_two_pixels_the_release_value_left_1_right_3(self):
        fm = self.fm()
        for row, idx, s in ((0, 0, "ON①"), (0, 1, "ON②"), (1, 0, "OFF"), (1, 1, "ON①"), (2, 0, "ON②"), (2, 1, "OFF")):
            rects, texts = self.render(9, menu_cursor=6, menu_cursor_x=0, init_sub_cursor=row, init_sub_cursor_x=idx)      # INITIAL-DEFAULTS Commit 4 (on purpose; INITIAL-DEFAULTS Commit 4): the parent page of the initial / release pop-up keeps its cursor on the button row 6 (no value cursor); row 0, rolling, now has a value cursor like the other rows
            x, y, w, h = self.one(rects)
            cut = 0 if idx == 0 else 1
            self.assertIn(x, [t - 10 + GLOBAL_BOX_X_OFFSET + cut for t in self.xs(texts, s)], "row %d cell %d %s: left edge +%d" % (row, idx, s, cut))
            self.assertEqual(w, fm.horizontalAdvance(s) + 20 + 2, "row %d cell %d %s: initial right +2 / release left -1 right +3" % (row, idx, s))

    # ------------------------------------------------------------------ the item names
    def test_09_the_item_name_cursors_get_one_pixel_on_the_right(self):
        fm = self.fm()
        for row, name in ((0, "採点区間"), (1, "停車駅採点範囲"), (2, "運転時分"), (3, "停止位置"), (4, "基本制動")):
            rects, texts = self.render(5, menu_cursor=row, menu_cursor_x=-1)
            x, y, w, h = self.one(rects)
            self.assertIn(x, [t - 15 + GLOBAL_BOX_X_OFFSET for t in self.xs(texts, name)], "1/3 %s: the left edge is the old one" % name)
            self.assertEqual(w, fm.horizontalAdvance(name) + 30 + 1, "1/3 %s: right +1" % name)
        for row, name in ((0, "転動"), (1, "保安装置介入"), (2, "速度制限超過"), (3, "停車時衝動"), (4, "非常ブレーキ")):
            rects, texts = self.render(6, menu_cursor=row, menu_cursor_x=-1)
            x, y, w, h = self.one(rects)
            self.assertEqual(w, fm.horizontalAdvance(name) + 30 + 1, "2/3 %s: right +1" % name)
        rects, texts = self.render(6, menu_cursor=5, menu_cursor_x=-1)
        x, y, w, h = self.one(rects)
        self.assertEqual(w, fm.horizontalAdvance("初動ブレーキ") + 30 + 1, "2/3 the initial / release brake label: right +1")

    # ------------------------------------------------------------------ 3/3
    def pct_texts(self, texts):
        return [t for t in texts if t[0].endswith("%") and len(t[0]) <= 4 and t[3] == "center"]

    def test_10_the_a_boundary_shows_a_red_underscore_until_a_digit_is_typed(self):
        rects, texts = self.render(10, menu_cursor=0, input_mode_active=False, rank_a_ratio=0.70)
        idle = self.pct_texts(texts)
        self.assertIn("70%", [t[0] for t in idle])
        rects, texts = self.render(10, menu_cursor=0, input_mode_active=True, input_buffer="", input_fresh=True, rank_a_ratio=0.70)
        empty = self.pct_texts(texts)
        red = [t for t in idle if t[0] == "70%"][0]
        self.assertEqual([t[0] for t in empty if "_" in t[0]], ["_%"], "the underscore stands in front of the %")
        self.assertEqual([t[4:] for t in empty if t[0] == "_%"], [red[4:]], "the same colour and outline as the red %")
        for buf in ("7", "70"):
            rects, texts = self.render(10, menu_cursor=0, input_mode_active=True, input_buffer=buf, input_fresh=False, rank_a_ratio=0.70)
            shown = [t[0] for t in self.pct_texts(texts)]
            self.assertIn(buf + "%", shown)
            self.assertFalse([s for s in shown if "_" in s], "the underscore is gone as soon as a digit is typed")
        rects, texts = self.render(10, menu_cursor=0, input_mode_active=False, rank_a_ratio=0.70)
        self.assertEqual(self.pct_texts(texts), idle, "not typing: as before")

    def test_11_the_a_boundary_takes_two_digits_the_stop_distance_three(self):
        o = self.o
        o.menu_state = 10
        o.menu_cursor = 0
        o.input_mode_active, o.input_fresh, o.input_buffer = True, True, ""
        for ch in "123":
            o.apply_numeric_char(ch)
        self.assertEqual(o.input_buffer, "12", "A boundary: 2 digits at most")
        o.menu_state = 5
        o.menu_cursor = 1
        o.input_mode_active, o.input_fresh, o.input_buffer = True, True, ""
        for ch in "1234":
            o.apply_numeric_char(ch)
        self.assertEqual(o.input_buffer, "123", "the stop distance keeps 3 digits")

    def test_12_the_a_boundary_range_and_commit_are_unchanged(self):
        o = self.o
        o.menu_state = 10
        o.menu_cursor = 0
        o.input_mode_active, o.input_buffer = True, "85"
        o.handle_menu_enter(False)
        self.assertEqual(round(o.rank_a_ratio, 2), 0.85)
        self.assertFalse(o.input_mode_active)
        o.input_mode_active, o.input_buffer = True, "40"
        o.handle_menu_enter(False)
        self.assertEqual(round(o.rank_a_ratio, 2), 0.70, "outside 50..90: the default 70 as before")


if __name__ == "__main__":
    unittest.main()
