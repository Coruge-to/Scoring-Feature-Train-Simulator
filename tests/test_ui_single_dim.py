"""Stage UI-D3 (Owner clarification 2026-11-08 after the live Run CUI-C-01). This FILE REPLACES the contract tests of the first single-dim commit (14e2de6), which still allowed rows outside the lists, drew no parent page and
left the F1 layer (alpha 220) under the single dim (two steps of darkness on the BVE screen).

Contract (menu_ui.draw_menu):
  * ONE dim per picture, MENU_DIM_RGBA = (0, 0, 0, 180), no pixel is dimmed twice. The F1 page in front IS the dim of the BVE screen (drawn first, under the page UI); with a pop-up panel, a drop-down or the help in front the whole content
    is drawn and the dim is applied ONCE at the end to the window minus the bright region.
  * bright region: a panel (7 / 8 / 9) = its rectangle; a drop-down = its frame + the up arrow tile + the down arrow tile (a union of rectangles); the help = the help window.
  * the parent page is drawn behind a panel (7, 8 -> the scoring page 1/3; 9 -> the page 2/3 where its button lives), outside the panel only, dimmed once like the BVE screen.
  * no row outside the frame of a list is drawn (the Owner has not defined a preview region: DROPDOWN_PREVIEW_ROWS = 0); a positive value draws that many COMPLETE rows beyond the arrow tiles, under the dim, without input.
The REAL screen (menu_ui.draw_menu on an offscreen QImage, a flat light background) is driven; the dimmed picture is compared pixel by pixel with the same picture without the dim.
RED = fails on the baseline 14e2de6; GUARD = passes there. Names: test_red_* / test_guard_*; every RED assertion message starts with 'UI-RED'."""
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbh_bulk_timing_button import Base, setUpModule, tearDownModule  # noqa: E402,F401

BACKGROUND = 200
ONE = 1.0 - 180 / 255.0                    # what ONE dim leaves of a pixel
BACKDROP = (5, 300)                        # left of every frame of every screen
PAGE_STATES = (1, 2, 3, 4, 5, 6, 10, 12)   # menu states with a page in front (11, the result screen, paints its own full-window fill)
PANEL_STATES = (7, 8, 9)


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class Dim(Base):
    def build(self, stations=14, rules=8):
        s = self.scene(start=0, end=4)
        o = s.o
        o.station_list = s.sl = [self.P.station("Stn%02d" % i, 500.0 * i, raw_dep=self.P.T0 + 1000 * i, raw_arr=self.P.T0 + 1000 * i) for i in range(stations)]
        o.station_list[-1]["is_terminal"] = True
        o.setting_start_idx, o.setting_end_idx = 0, stations - 1
        o.brake_rules = [{"end_idx": 2 * k + 1, "apply": "階段", "release": "階段"} for k in range(rules - 1)] + [{"end_idx": -1, "apply": "階段", "release": "階段"}]
        o.penalty_init_rules = [{"apply": "ON①", "release": "ON①"} for _ in o.brake_rules]
        o.menu_cursor, o.menu_cursor_x = 0, 0
        o.show_help = False
        o.dropdown_active = False
        o.dropdown_options = []
        o.dropdown_scroll = o.dropdown_cursor = 0
        o.timing_scroll = o.timing_cursor = 0
        o.sub_scroll, o.sub_cursor, o.sub_cursor_x = 0, 0, 0
        o.init_sub_scroll, o.init_sub_cursor, o.init_sub_cursor_x = 0, 0, 0
        o.target_retry_idx = 0
        return o

    def lum(self, image, x, y):
        from PyQt6.QtGui import QColor
        c = QColor(image.pixel(int(x), int(y)))
        return int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())

    def channels(self, image, x, y):
        from PyQt6.QtGui import QColor
        c = QColor(image.pixel(int(x), int(y)))
        return c.red(), c.green(), c.blue()

    def render(self, o, state, width=1920, height=1080, **flags):
        from PyQt6.QtGui import QImage, QPainter, QColor
        import menu_ui
        for k, v in flags.items():
            setattr(o, k, v)
        o.menu_state = state
        o.width = lambda: width
        o.height = lambda: height
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(BACKGROUND, BACKGROUND, BACKGROUND))
        painter = QPainter(image)
        o.menu_click_zones = []
        try:
            menu_ui.draw_menu(o, painter, width / (height / 1080.0))
        finally:
            painter.end()
        return image

    def events(self, o, state, **flags):
        """the texts and the dim calls of one picture in drawing order: strings and ('DIM', bright)"""
        import menu_ui
        out = []
        original_text = menu_ui.draw_text_with_outline
        original_dim = getattr(menu_ui, "_draw_menu_dim", None)
        self.assertIsNotNone(original_dim, "UI-RED: the one dim function (_draw_menu_dim) does not exist")

        def text(painter, t, *a, **k):
            out.append(t)
            return original_text(painter, t, *a, **k)

        def dim(painter, view, *rest):
            bright = rest[0] if rest else None
            if bright is not None and bright and not isinstance(bright[0], (tuple, list)):
                bright = [bright]                                # (the first draft passed ONE rectangle)
            out.append(("DIM", None if bright is None else [tuple(b) for b in bright]))
            return original_dim(painter, view, *rest)
        menu_ui.draw_text_with_outline, menu_ui._draw_menu_dim = text, dim
        try:
            self.render(o, state, **flags)
        finally:
            menu_ui.draw_text_with_outline, menu_ui._draw_menu_dim = original_text, original_dim
        return out

    def texts(self, o, state, **flags):
        return [e for e in self.events(o, state, **flags) if isinstance(e, str)]

    TITLES = {7: "=== 基本制動 設定 ===", 8: "=== 運転時分 設定 ===", 9: "=== 初動・緩和ブレーキ 設定 ==="}

    def panel_texts(self, o, state, **flags):
        """the texts the PANEL draws (after its title): the parent page behind it is not part of the list contract"""
        texts = self.texts(o, state, **flags)
        return texts[texts.index(self.TITLES[state]):]

    def dims(self, o, state, **flags):
        return [e for e in self.events(o, state, **flags) if not isinstance(e, str)]

    def undimmed(self, o, state, **flags):
        import menu_ui
        original = menu_ui._draw_menu_dim
        menu_ui._draw_menu_dim = lambda *a, **k: None
        try:
            return self.render(o, state, **flags)
        finally:
            menu_ui._draw_menu_dim = original

    def drop(self, o, n=14, scroll=4, cursor=6):
        o.dropdown_active = True
        o.dropdown_options = [{"idx": i, "name": "Opt%02d" % i} for i in range(n)]
        o.dropdown_scroll, o.dropdown_cursor = scroll, cursor

    def red(self, ok, message):
        self.assertTrue(ok, "UI-RED: " + message)

    def bright_rects(self, o, state, show_help=False):
        """the bright region the contract wants for the picture just drawn (from the rectangles the screen publishes)"""
        if show_help:
            r = o.active_help_rect
            return [(r[0], r[1], r[2], r[3])]
        if o.dropdown_active and o.dropdown_options:
            x0, y0, x1, y1 = o.active_dropdown_rect
            cx = 1920 / 2
            rects = [(x0, y0, x1, y1)]
            if o.dropdown_scroll > 0:
                rects.append((cx - 30, y0 - 48, cx + 30, y0 + 2))
            if o.dropdown_scroll + 7 < len(o.dropdown_options):
                rects.append((cx - 30, y1 - 2, cx + 30, y1 + 54))
            return rects
        r = o.active_panel_rect
        return [(r[0], r[1], r[2], r[3])]

    def check_one_dim(self, o, state, **flags):
        """dimmed picture A vs the same picture without the dim B: inside the bright region A == B, everywhere else A == B x (75/255) - ONE layer, no gap, no second layer.
        The help hint button and the scroll arrows are drawn after the dim on purpose and are left out."""
        b = self.undimmed(o, state, **flags)
        a = self.render(o, state, **flags)
        bright = self.bright_rects(o, state, flags.get("show_help", False))
        exempt = [(z[0] - 12, z[1] - 12, z[2] + 12, z[3] + 12) for z in o.menu_click_zones if z[4] in (999, 995, 996)]
        pts = [(x, y) for x in range(3, 1920, 13) for y in range(3, 1080, 13)]
        for x0, y0, x1, y1 in bright:
            pts += [(int(x0) + dx, int(y0) + dy) for dx in (-6, -3, 3, 6) for dy in range(0, int(y1 - y0), 17)]
            pts += [(int(x0) + dx, int(y0) + dy) for dy in (-6, -3, 3, 6) for dx in range(0, int(x1 - x0), 17)]
        bad_in, bad_out, seen_out = [], [], 0
        for x, y in pts:
            if not (0 <= x < 1920 and 0 <= y < 1080) or any(e[0] <= x <= e[2] and e[1] <= y <= e[3] for e in exempt):
                continue
            ca, cb = self.channels(a, x, y), self.channels(b, x, y)
            inside = any(x0 + 4 <= x <= x1 - 4 and y0 + 4 <= y <= y1 - 4 for x0, y0, x1, y1 in bright)
            outside = all(x < x0 - 4 or x > x1 + 4 or y < y0 - 4 or y > y1 + 4 for x0, y0, x1, y1 in bright)
            if inside:
                if ca != cb:
                    bad_in.append((x, y, ca, cb))
            elif outside:
                seen_out += 1
                if any(abs(ca[i] - cb[i] * ONE) > 2.0 for i in range(3)):
                    bad_out.append((x, y, ca, cb))
        self.assertGreater(seen_out, 500, "the dim region was sampled")
        return bad_in, bad_out

    # ---- ONE dim per picture, the same darkness everywhere ---------------------------------------------------------------------------------------------------------------------------
    def test_red_01_one_dim_call_in_every_picture_the_page_dim_included(self):
        o = self.build()
        for state in PAGE_STATES + (11,) + PANEL_STATES:
            self.red(len(self.dims(o, state)) == 1, "menu_state %d: %d dim calls (the F1 page dim is one of them)" % (state, len(self.dims(o, state))))
        for state in (5, 7, 9):
            o.dropdown_active = False
            self.drop(o)
            self.red(len(self.dims(o, state)) == 1, "menu_state %d with a drop-down" % state)
        for state, drop in ((1, False), (5, False), (8, False), (7, True)):
            o.dropdown_active = False
            if drop:
                self.drop(o, n=3, scroll=0, cursor=0)
            self.red(len(self.dims(o, state, show_help=True)) == 1, "menu_state %d with the help" % state)
            o.show_help = False

    def test_red_02_the_bve_backdrop_is_dimmed_exactly_once_in_every_state(self):
        o = self.build()
        want = BACKGROUND * ONE
        seen = {}
        for state in PAGE_STATES + PANEL_STATES:
            o.dropdown_active = False
            seen[state] = self.lum(self.render(o, state), *BACKDROP)
        for state in (5, 7, 9):
            o.dropdown_active = False
            self.drop(o, n=3, scroll=0, cursor=0)
            seen["%d+dropdown" % state] = self.lum(self.render(o, state), *BACKDROP)
        o.dropdown_active = False
        for state in (1, 5, 8):
            seen["%d+help" % state] = self.lum(self.render(o, state, show_help=True), *BACKDROP)
            o.show_help = False
        self.red(all(abs(v - want) <= 1.6 for v in seen.values()), "the backdrop must be %.1f (one dim) in every state; got %s" % (want, seen))

    def test_red_03_no_pixel_is_dimmed_twice_panel_dropdown_and_help(self):
        o = self.build()
        for state in PANEL_STATES:
            o.dropdown_active = False
            self.render(o, state)
            bad_in, bad_out = self.check_one_dim(o, state)
            self.red(bad_in == [], "menu_state %d: the panel is not dimmed" % state)
            self.red(bad_out == [], "menu_state %d: everything outside the panel is dimmed exactly once: %s" % (state, bad_out[:3]))
        for state in (5, 7, 9):
            o.dropdown_active = False
            self.drop(o, n=14, scroll=4, cursor=6)
            self.render(o, state)
            bad_in, bad_out = self.check_one_dim(o, state)
            self.red(bad_in == [], "menu_state %d: frame and arrow tiles are not dimmed" % state)
            self.red(bad_out == [], "menu_state %d with a drop-down: everything outside the frame and the two arrow tiles is dimmed once: %s" % (state, bad_out[:3]))
        for state, drop in ((1, False), (5, True), (8, False), (7, True)):
            o.dropdown_active = False
            if drop:
                self.drop(o, n=3, scroll=0, cursor=0)
            self.render(o, state, show_help=True)
            bad_in, bad_out = self.check_one_dim(o, state, show_help=True)
            self.red(bad_in == [], "menu_state %d: the help window is not dimmed" % state)
            self.red(bad_out == [], "menu_state %d with the help: everything but the help window is dimmed once: %s" % (state, bad_out[:3]))
            o.show_help = False

    def test_guard_04_the_help_opens_and_closes_without_a_change_of_darkness(self):
        o = self.build()
        self.drop(o, n=5, scroll=0, cursor=1)
        before = self.render(o, 7)
        during = self.render(o, 7, show_help=True)
        after = self.render(o, 7, show_help=False)
        self.red(before == after, "the picture after the help is the picture before it")
        self.red(self.lum(during, *BACKDROP) == self.lum(before, *BACKDROP), "the backdrop is equally dark with and without the help")
        o.dropdown_active = False
        for state in (1, 8):
            hole_before = self.dims(o, state)
            hole_during = self.dims(o, state, show_help=True)
            hole_after = self.dims(o, state, show_help=False)
            self.red(hole_after == hole_before, "menu_state %d: the bright region is back where it was after the help closes: %r vs %r" % (state, hole_before, hole_after))
            self.red(hole_during and hole_during[0][1] is not None and len(hole_during[0][1]) == 1 and hole_during[0][1] != (hole_before[0][1] if hole_before else None), "the bright region moved to the help window")

    # ---- the parent page --------------------------------------------------------------------------------------------------------------------------------------------------------------
    def test_red_05_the_scoring_page_is_drawn_behind_the_timing_and_basic_brake_panels(self):
        o = self.build()
        for state in (7, 8):
            names = self.texts(o, state)
            for want in ("=== 採点設定 (1/3) ===", "採点区間", "停車駅採点範囲", "運転時分", "停止位置", "基本制動"):
                self.red(want in names, "menu_state %d: the page 1/3 behind the panel lacks %r" % (state, want))
        self.red("=== 採点設定 (2/3) ===" in self.texts(o, 9), "menu_state 9: the page 2/3 (the page of its button) is drawn behind the panel")
        self.red("初動ブレーキ" in self.texts(o, 9), "menu_state 9: the labels of the page 2/3")

    def test_red_06_the_parent_is_drawn_before_the_panel_and_before_the_one_dim(self):
        o = self.build()
        for state, title in ((7, "=== 基本制動 設定 ==="), (8, "=== 運転時分 設定 ==="), (9, "=== 初動・緩和ブレーキ 設定 ===")):
            events = self.events(o, state)
            parent_title = "=== 採点設定 (2/3) ===" if state == 9 else "=== 採点設定 (1/3) ==="
            self.red(parent_title in events, "menu_state %d: no parent page" % state)
            dim_at = [i for i, e in enumerate(events) if not isinstance(e, str)]
            self.assertEqual(len(dim_at), 1)
            self.assertLess(events.index(parent_title), events.index(title), "the parent page comes before the panel")
            self.assertLess(events.index(title), dim_at[0], "the panel is drawn before the one dim")

    def test_red_07_the_parent_does_not_show_through_the_panel_and_leaves_no_click_zone(self):
        import menu_ui
        self.red(hasattr(menu_ui, "MENU_PARENT_PAGE"), "there is no parent page table")
        o = self.build()
        for state in PANEL_STATES:
            with_parent = self.undimmed(o, state)
            zones_with = [z for z in o.menu_click_zones]
            original = dict(menu_ui.MENU_PARENT_PAGE)
            menu_ui.MENU_PARENT_PAGE.clear()
            try:
                without = self.undimmed(o, state)
                zones_without = [z for z in o.menu_click_zones]
            finally:
                menu_ui.MENU_PARENT_PAGE.update(original)
            x0, y0, x1, y1 = o.active_panel_rect
            diff_in = [(x, y) for x in range(int(x0) + 6, int(x1) - 6, 11) for y in range(int(y0) + 6, int(y1) - 6, 11) if with_parent.pixel(x, y) != without.pixel(x, y)]
            self.red(diff_in == [], "menu_state %d: the parent page shows through the panel at %s" % (state, diff_in[:3]))
            diff_out = [(x, y) for x in range(5, 1920, 17) for y in range(5, 1080, 17) if not (x0 - 4 <= x <= x1 + 4 and y0 - 4 <= y <= y1 + 4) and with_parent.pixel(x, y) != without.pixel(x, y)]
            if state in (7, 8):                                  # (the panel 9 covers the whole content of its parent page, only margins are left)
                self.red(len(diff_out) > 0, "menu_state %d: the parent page is visible outside the panel" % state)
            self.assertEqual(zones_with, zones_without, "menu_state %d: the parent page adds no click zone" % state)

    def test_red_08_the_parent_pass_gives_every_attribute_back_even_when_it_fails(self):
        import menu_ui
        from PyQt6.QtGui import QImage, QPainter
        self.red(hasattr(menu_ui, "MENU_PARENT_PAGE"), "there is no parent pass")
        o = self.build()
        o.menu_state = 8
        o.dropdown_active = True
        o.dropdown_options = [{"idx": 0, "name": "A"}]
        o.show_help = True
        zones = []
        o.menu_click_zones = zones
        original = menu_ui.draw_text_with_outline

        def boom(painter, text, *a, **k):
            if text == "=== 採点設定 (1/3) ===":
                raise RuntimeError("the parent failed")
            return original(painter, text, *a, **k)
        menu_ui.draw_text_with_outline = boom
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            with self.assertRaises(RuntimeError):
                menu_ui.draw_menu(o, painter, 1920.0)
        finally:
            menu_ui.draw_text_with_outline = original
            painter.end()
        self.red((o.menu_state, o.dropdown_active, o.show_help) == (8, True, True) and o.menu_click_zones is zones, "state, drop-down, help and the click zone list are back after the failure")
        o.dropdown_active = False
        o.show_help = False
        a, b = self.render(o, 8), self.render(o, 8)
        self.assertEqual(a, b)

    # ---- the drop-down: the bright union, no row outside ----------------------------------------------------------------------------------------------------------------------------
    def test_red_09_the_dropdown_frame_and_both_arrows_are_bright_the_rest_is_dim(self):
        o = self.build()
        self.drop(o, n=14, scroll=4, cursor=6)
        image = self.render(o, 5)
        undimmed = self.undimmed(o, 5)
        x0, y0, x1, y1 = o.active_dropdown_rect
        cx = 960
        for label, (x, y) in (("frame", (x0 + 8, y0 + 4)), ("up arrow tile", (cx - 24, y0 - 20)), ("down arrow tile", (cx - 24, y1 + 20))):
            self.red(image.pixel(int(x), int(y)) == undimmed.pixel(int(x), int(y)), "%s is not dimmed" % label)
        for label, (x, y) in (("left of the frame", (x0 - 40, y0 + 100)), ("right of the frame", (x1 + 40, y0 + 100)), ("beside the arrow tile", (cx + 60, y0 - 20)), ("below the down tile", (cx, y1 + 80))):
            was, now = self.lum(undimmed, x, y), self.lum(image, x, y)
            self.red(abs(now - was * ONE) <= 1.6, "%s is dimmed once (%d -> %d)" % (label, was, now))
        o.dropdown_scroll = 0                                    # at the top: no up arrow, so no up tile
        self.render(o, 5)
        self.assertEqual(len(self.bright_rects(o, 5)), 2)
        bad_in, bad_out = self.check_one_dim(o, 5)
        self.assertEqual((bad_in, bad_out), ([], []))

    def test_red_10_no_row_outside_the_frame_is_drawn_anywhere(self):
        o = self.build()
        self.drop(o, n=14, scroll=4, cursor=6)
        names = [n for n in self.texts(o, 5) if n.startswith("Opt")]
        self.red(sorted(names) == ["Opt%02d" % k for k in range(4, 11)], "only the 7 rows of the frame are drawn: %s" % names)
        o.dropdown_scroll = 0
        names = [n for n in self.texts(o, 5) if n.startswith("Opt")]
        self.red(sorted(names) == ["Opt%02d" % k for k in range(0, 7)], "at the top too: %s" % names)
        o.dropdown_active = False
        o.timing_scroll, o.timing_cursor = 3, 5
        targets = o.get_timing_target_stas()
        shown_texts = self.panel_texts(o, 8)
        shown = [o.station_list[t]["name"] for t in targets if o.station_list[t]["name"] in shown_texts]
        self.red(shown == [o.station_list[targets[k]]["name"] for k in range(3, 9)], "the timing panel draws its 6 rows only (no row above or below): %s" % shown)
        o.sub_scroll, o.sub_cursor = 1, 4
        self.red(self.panel_texts(o, 7).count("制動 /") == 5, "the basic brake panel draws its 5 rows only")
        o.init_sub_scroll, o.init_sub_cursor = 1, 4
        self.red(self.panel_texts(o, 9).count("初動") == 5, "the initial / relaxation panel draws its 5 rows only")

    def test_red_11_a_positive_preview_row_count_draws_complete_rows_beyond_the_tiles(self):
        import menu_ui
        o = self.build()
        self.drop(o, n=20, scroll=8, cursor=10)
        original = getattr(menu_ui, "DROPDOWN_PREVIEW_ROWS", None)
        self.red(original == 0, "the preview row count is a constant, 0 by the Owner's contract")
        menu_ui.DROPDOWN_PREVIEW_ROWS = 1
        try:
            names = [n for n in self.texts(o, 5) if n.startswith("Opt")]
        finally:
            menu_ui.DROPDOWN_PREVIEW_ROWS = original
        self.assertEqual(len(names), 7 + 2, "one complete row on each side: %s" % names)
        for i in menu_ui.dropdown_preview_slots(8, 20, 7, 300, 56, (800, 1100), [(900, 252, 1000, 302)], 1080, 3):
            y = 300 + 10 + i * 56
            self.assertTrue(0 <= y and y + 56 <= 1080 and not (y < 302 and y + 56 > 252), "a complete row inside the screen that does not touch the tile: %d" % i)
        self.assertEqual(menu_ui.dropdown_preview_slots(0, 20, 7, 300, 56, (800, 1100), [], 1080, 0), [])
        self.assertEqual([i for i in menu_ui.dropdown_preview_slots(0, 20, 7, 300, 56, (800, 1100), [], 1080, 2) if i < 0], [], "nothing above the first option")
        # a row that would be cut by the top or the bottom of the screen is never a preview row, and rows are never taken from behind a bright rectangle
        for start_y in (100, 700):
            for i in menu_ui.dropdown_preview_slots(8, 20, 7, start_y, 56, (800, 1100), [(900, start_y - 48, 1000, start_y + 2)], 1080, 6):
                y = start_y + 10 + i * 56
                self.assertTrue(y >= 0 and y + 56 <= 1080, "UI-RED: a partial row (start_y %d, slot %d, y %d)" % (start_y, i, y))
                self.assertFalse(y < start_y + 2 and y + 56 > start_y - 48, "UI-RED: a row over the arrow tile (slot %d)" % i)
        near_tile = menu_ui.dropdown_preview_slots(8, 20, 7, 300, 56, (800, 1100), [(900, 252, 1000, 302)], 1080, 1)
        self.assertIn(-3, near_tile, "the first COMPLETE row that does not touch the arrow tile is the preview row")
        self.assertNotIn(-1, near_tile)
        self.assertNotIn(-2, near_tile)

    def test_guard_12_rows_outside_the_frame_take_no_input(self):
        o = self.build()
        self.drop(o, n=14, scroll=4, cursor=6)
        self.render(o, 5)
        x0, y0, x1, y1 = o.active_dropdown_rect
        for zone in o.menu_click_zones:
            if zone[4] in (995, 996, 999):
                continue
            self.assertGreaterEqual(zone[1], y0 - 1)
            self.assertLessEqual(zone[3], y1 + 1)
            if zone[4] == 997:
                self.assertTrue(4 <= zone[5] <= 10, repr(zone))
        o.dropdown_active = False
        o.timing_scroll, o.timing_cursor = 3, 5
        self.render(o, 8)
        indexes = {z[4] for z in o.menu_click_zones if len(z) == 6 and z[5] == -1 and z[4] < 100}
        self.assertTrue(indexes <= set(range(3, 10)) | {len(o.get_timing_target_stas())}, sorted(indexes))

    def test_guard_13_the_selected_row_is_always_inside_the_frame(self):
        o = self.build(stations=24, rules=9)
        o.menu_state = 8
        o.timing_scroll = 0
        o.timing_cursor = o._timing_cursor_stops()[0]
        for _ in range(40):
            o.handle_menu_down()
            self.assertTrue(o.timing_scroll <= o.timing_cursor < o.timing_scroll + 6 or o.timing_cursor >= len(o.get_timing_target_stas()))
        for _ in range(40):
            o.handle_menu_up()
            self.assertTrue(o.timing_scroll <= o.timing_cursor < o.timing_scroll + 6 or o.timing_cursor >= len(o.get_timing_target_stas()))
        o.menu_state, o.sub_scroll, o.sub_cursor, o.sub_cursor_x = 7, 0, 0, 0
        for _ in range(30):
            o.handle_menu_down()
            if o.sub_cursor < len(o.brake_rules):
                self.assertTrue(o.sub_scroll <= o.sub_cursor < o.sub_scroll + 5)

    def test_guard_14_the_same_state_draws_the_same_picture(self):
        o = self.build()
        o.sub_scroll, o.sub_cursor, o.sub_cursor_x = 1, 4, 0
        self.assertEqual(self.render(o, 7), self.render(o, 7))
        self.drop(o)
        self.assertEqual(self.render(o, 5), self.render(o, 5))

    # ---- the geometry ------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def test_red_15_the_dim_region_is_the_view_minus_the_union_without_gap_or_overlap(self):
        import menu_ui
        import inspect
        rects_of = getattr(menu_ui, "menu_dim_rects", None)
        self.red(rects_of is not None and "bright" in inspect.signature(rects_of).parameters, "menu_dim_rects takes a list of bright rectangles")
        rng = random.Random(11)
        for _ in range(200):
            view = (rng.choice((0, -40, 13.5)), rng.choice((0, -25, 7.25)), rng.choice((1920, 837, 2561.5)), rng.choice((1080, 668, 1441.5)))
            bright = []
            for _k in range(rng.choice((1, 2, 3))):
                ax0, ay0 = view[0] + rng.uniform(-50, view[2] - 5), view[1] + rng.uniform(-50, view[3] - 5)
                bright.append((ax0, ay0, ax0 + rng.uniform(1, view[2] / 2), ay0 + rng.uniform(1, view[3] / 2)))
            rects = rects_of(view, bright)
            vx0, vy0, vx1, vy1 = int(view[0] // 1), int(view[1] // 1), -int(-(view[0] + view[2]) // 1), -int(-(view[1] + view[3]) // 1)
            for x, y, w, h in rects:
                self.assertTrue(w > 0 and h > 0 and x >= vx0 and y >= vy0 and x + w <= vx1 and y + h <= vy1, repr((x, y, w, h)))
            for gx in range(vx0, vx1, max(1, (vx1 - vx0) // 40)):
                for gy in range(vy0, vy1, max(1, (vy1 - vy0) // 40)):
                    n = sum(1 for x, y, w, h in rects if x <= gx < x + w and y <= gy < y + h)
                    inside = any(int(b[0] // 1) <= gx < -int(-b[2] // 1) and int(b[1] // 1) <= gy < -int(-b[3] // 1) for b in bright)
                    self.assertEqual(n, 0 if inside else 1, "pixel (%d, %d): dimmed %d times" % (gx, gy, n))

    def test_red_16_no_bright_region_dims_the_whole_view_and_a_covering_one_dims_nothing(self):
        import menu_ui
        import inspect
        rects_of = getattr(menu_ui, "menu_dim_rects", None)
        self.red(rects_of is not None and "bright" in inspect.signature(rects_of).parameters, "menu_dim_rects takes a list of bright rectangles")
        self.assertEqual(rects_of((0, 0, 100, 50), None), [(0, 0, 100, 50)])
        self.assertEqual(rects_of((0, 0, 100, 50), []), [(0, 0, 100, 50)])
        self.assertEqual(rects_of((0, 0, 100, 50), [(-10, -10, 200, 200)]), [])
        two = rects_of((0, 0, 100, 50), [(10, 10, 20, 20), (60, 30, 80, 45)])
        self.assertEqual(sum(w * h for _, _, w, h in two), 100 * 50 - 100 - 300)

    def test_red_17_the_panel_rectangle_is_one_definition(self):
        import menu_ui
        fn = getattr(menu_ui, "menu_panel_rect", None)
        self.red(fn is not None, "menu_panel_rect does not exist")
        o = self.build()
        for state in PANEL_STATES:
            self.render(o, state)
            self.assertEqual(tuple(round(v, 3) for v in o.active_panel_rect), tuple(round(v, 3) for v in fn(state)), "menu_state %d" % state)

    # ---- untouched contracts / independence --------------------------------------------------------------------------------------------------------------------------------------
    def test_red_18_the_colour_is_the_help_colour_the_f1_layer_is_the_one_dim_and_cursor_input_code_is_not_touched(self):
        text = source("menu_ui.py")
        self.assertIn("MENU_DIM_RGBA = (0, 0, 0, 180)", text)
        self.assertEqual(text.count("QColor(*MENU_DIM_RGBA)"), 1)
        self.assertEqual(text.count("QColor(0, 0, 0, 180)"), 0)
        self.red(text.count("QColor(0, 0, 0, 220)") == 0, "the F1 layer is the one dim now (no second colour, no alpha 220)")
        for word in ("OverrideCursor", "QCursor", "setCursor", "_operation_cursor", "Legacy", "Current", "BVE5", "BVE6", "legacy", "bve5", "bve6"):
            self.assertNotIn(word, text, "menu_ui.py: " + word)
        main_text = source("main.py")
        for word in ("MENU_DIM_RGBA", "_draw_menu_dim", "menu_dim_rects", "MENU_PARENT_PAGE", "menu_panel_rect", "dropdown_preview_slots"):
            self.assertNotIn(word, main_text, "main.py does not know the dim: " + word)
        for name in ("hud_ui.py", "managed_hud.py", "managed_input.py", "managed_state.py", "managed_mode.py"):
            for word in ("MENU_DIM_RGBA", "_draw_menu_dim", "menu_dim_rects", "MENU_PARENT_PAGE"):
                self.assertNotIn(word, source(name), name)

    def test_red_19_the_cumulative_and_the_ghost_row_machinery_is_gone(self):
        text = source("menu_ui.py")
        for word in ("menu_hierarchy_level", "MENU_HIERARCHY", "_draw_menu_dim_layer", "_list_row_slots", "dim_inner", "front_rect "):
            self.red(word not in text, "the superseded machinery is still in the source: " + word)
        calls = [l for l in text.splitlines() if "_draw_menu_dim(painter" in l and "def " not in l]
        self.red(len(calls) == 3, "the dim is drawn at three places only (the page dim first, the one dim at the end, the help) and never twice in a picture: %d" % len(calls))

    def test_guard_20_the_dim_is_no_input_target_and_the_hint_button_stays(self):
        text = source("menu_ui.py")
        if "def _draw_menu_dim(painter, view, bright=None):" not in text:
            return
        block = text[text.index("def _draw_menu_dim(painter"):text.index("def dropdown_preview_slots")]
        self.assertNotIn("menu_click_zones", block)
        self.assertNotIn("show_help", block)
        o = self.build()
        self.drop(o)
        calls = self.texts(o, 5)
        self.assertLess(calls.index("Opt05"), calls.index("操作説明 : H"))
        self.assertIn("=== 採点設定 (1/3) ===", self.texts(self.build(), 5))

    def test_guard_21_the_stage_ui4_comments_stay(self):
        self.assertEqual(source("menu_ui.py").count("# Stage UI-4: no second dim layer here"), 3)


if __name__ == "__main__":
    unittest.main()
