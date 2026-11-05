"""Stage UI-4: the dim layer behind the F1 pop-up screens. draw_menu darkens the WHOLE window once (the common layer at its top). The basic brake (menu_state 7), the timing (8) and the initial / relaxation (9) screens used to draw a SECOND
dim layer inside the 16:9 area (since 2026-03-25 / 03-27 / 04-19). In a BVE window that is not 16:9 the second layer left a darker band between two lighter strips (found on the live run C-12, 2026-11-05, screenshot 215327: the window was
837 x 668). The Owner decided to remove the second layer (the common layer stays: the background behind the pop-ups keeps its darkness, the band is gone).

The REAL screen (menu_ui.draw_menu on an offscreen QImage of the window size 837 x 668, a flat light background) is driven. A pixel far to the left of every frame is read in the top strip, in the 16:9 area and in the bottom strip:
all three must be equally dark for EVERY menu state. RED = fails on the baseline 569843c (states 7, 8, 9); GUARD = passes on the baseline."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbh_bulk_timing_button import Base, setUpModule, tearDownModule  # noqa: E402,F401

WINDOW_W, WINDOW_H = 837, 668          # the BVE window of the live run (not 16:9)
BACKGROUND = 200                        # a flat light grey behind the menu
STATES = list(range(1, 13))
X_LEFT = 5                              # left of every frame
Y_TOP, Y_MIDDLE, Y_BOTTOM = 40, 300, 640   # the 16:9 area of the window is y 98 .. 570


class PopupDim(Base):
    def lum(self, image, x, y):
        from PyQt6.QtGui import QColor
        c = QColor(image.pixel(x, y))
        return int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())

    def render(self, state, width=WINDOW_W, height=WINDOW_H):
        from PyQt6.QtGui import QImage, QPainter, QColor
        import menu_ui
        s = self.scene(start=0, end=4)
        o = s.o
        o.width = lambda: width
        o.height = lambda: height
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(BACKGROUND, BACKGROUND, BACKGROUND))
        painter = QPainter(image)
        o.menu_state = state
        o.menu_click_zones = []
        try:
            menu_ui.draw_menu(o, painter, width / (height / 1080.0))
        finally:
            painter.end()
        return image

    def test_UD1_RED_every_menu_state_is_equally_dark_in_the_top_strip_the_16_9_area_and_the_bottom_strip(self):
        bad = []
        for state in STATES:
            image = self.render(state)
            top, middle, bottom = self.lum(image, X_LEFT, Y_TOP), self.lum(image, X_LEFT, Y_MIDDLE), self.lum(image, X_LEFT, Y_BOTTOM)
            if not (top == middle == bottom):
                bad.append("menu_state %d: top=%d middle=%d bottom=%d" % (state, top, middle, bottom))
        self.assertEqual(bad, [], "RED on the baseline (states 7, 8, 9 draw a second dim layer inside the 16:9 area)")

    def test_UD2_GUARD_the_common_dim_layer_stays_the_background_is_dark_behind_every_pop_up(self):
        for state in STATES:
            image = self.render(state)
            for y in (Y_TOP, Y_MIDDLE, Y_BOTTOM):
                self.assertLess(self.lum(image, X_LEFT, y), 60, "menu_state %d keeps a dark background behind it (y=%d)" % (state, y))

    def test_UD3_GUARD_a_16_9_window_has_no_band_either(self):
        for state in (7, 8, 9):
            image = self.render(state, 1920, 1080)
            values = {self.lum(image, X_LEFT, y) for y in (20, 300, 540, 800, 1060)}
            self.assertEqual(len(values), 1, "menu_state %d in a 16:9 window: %s" % (state, sorted(values)))

    def test_UD4_RED_the_three_screens_have_no_dim_rectangle_of_their_own(self):
        with open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("drawRect(0, 0, int(logical_width), int(BASE_SCREEN_H))"), 1, "the common layer")
        self.assertNotIn("drawRect(0,0, int(BASE_SCREEN_W), int(BASE_SCREEN_H))", text)
        self.assertNotIn("drawRect(0, 0, int(BASE_SCREEN_W), int(BASE_SCREEN_H))", text)
        self.assertEqual(text.count("# Stage UI-4: no second dim layer here"), 3)

class PopupBackground(PopupDim):
    """Stage UI-5 (Owner, 2026-11-05, screenshot 221512): the initial / relaxation screen's explanation box was darker than the panel, the title of the page behind the pop-up (1/3, 2/3) showed through / above the panel of the basic brake and the
    initial / relaxation screens (the timing screen never drew it): all three pop-ups are now alike (nothing of the page behind them)."""

    def texts(self, state, width=1920, height=1080):
        import menu_ui
        calls = []
        original = menu_ui.draw_text_with_outline

        def record(painter, text, *args, **kwargs):
            calls.append(text)
            return original(painter, text, *args, **kwargs)
        menu_ui.draw_text_with_outline = record
        try:
            self.render(state, width, height)
        finally:
            menu_ui.draw_text_with_outline = original
        return calls

    def test_UB1_RED_the_title_of_the_page_behind_is_not_drawn_in_the_three_pop_ups(self):
        for state in (7, 8, 9):
            calls = self.texts(state)
            self.assertNotIn("=== 採点設定 (1/3) ===", calls, "menu_state %d" % state)
            self.assertNotIn("=== 採点設定 (2/3) ===", calls, "menu_state %d" % state)

    def test_UB2_GUARD_the_pages_themselves_and_each_pop_up_keep_their_own_title(self):
        self.assertIn("=== 採点設定 (1/3) ===", self.texts(5))
        self.assertIn("=== 採点設定 (2/3) ===", self.texts(6))
        self.assertIn("=== 採点設定 (3/3) ===", self.texts(10))
        self.assertIn("=== 基本制動 設定 ===", self.texts(7))
        self.assertIn("=== 運転時分 設定 ===", self.texts(8))
        self.assertIn("=== 初動・緩和ブレーキ 設定 ===", self.texts(9))

    def test_UB3_RED_the_explanation_box_of_the_initial_relaxation_screen_is_not_darker_than_the_panel(self):
        image = self.render(9, 1920, 1080)
        ref = self.lum(image, 160, 220)                   # inside the panel, left of every row, no text
        dark = [y for y in range(330, 1005) if self.lum(image, 160, y) < ref - 4]
        self.assertEqual(dark, [], "RED on the baseline (the box was filled with a darker colour): reference %d" % ref)

    def test_UB4_RED_no_explanation_box_has_a_fill(self):
        with open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("painter.setBrush(Qt.BrushStyle.NoBrush)     # Stage UI-5: the explanation box has an outline only", text)
        self.assertEqual(text.count("QColor(20, 20, 20, 220)"), 0, "no explanation box has the dark fill any more (Stage UI-6: the pages 1/3, 2/3, 3/3 too)")
        self.assertEqual(text.count("# Stage UI-6: the explanation box has an outline only"), 3)
    def test_UB5_RED_the_explanation_box_of_every_page_is_as_dark_as_its_surroundings(self):
        """Stage UI-6: pages 1/3 (state 5), 2/3 (6) and 3/3 (10): a pixel inside the box (right margin, no text) is as dark as the pixel just outside it."""
        boxes = {5: (870, 135), 6: (870, 135), 10: (693, 312)}
        for state, (desc_y, desc_h) in boxes.items():
            image = self.render(state, 1920, 1080)
            y = int(desc_y + desc_h / 2)
            inside, outside = self.lum(image, 1750, y), self.lum(image, 1790, y)
            self.assertEqual(inside, outside, "menu_state %d: inside=%d outside=%d (RED on the baseline: the box had a darker fill)" % (state, inside, outside))

if __name__ == "__main__":
    unittest.main()
