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


if __name__ == "__main__":
    unittest.main()
