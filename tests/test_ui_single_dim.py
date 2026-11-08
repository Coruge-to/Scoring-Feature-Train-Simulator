"""Stage UI-D2 (Owner ruling 2026-11-08; three screenshots 124603 / 124659 / 124725; this REPLACES the cumulative per-hierarchy layers of the first draft): the F1 screens have exactly ONE dim.

  active region : the ONE bright region - the front operating region (a pop-up panel 7 / 8 / 9, a drop-down opened on a page or a panel, or the operation help while it is shown)
  dim region    : the whole window minus the active region, covered ONCE by the dim of the operation help (MENU_DIM_RGBA = (0, 0, 0, 180), the existing constant)

The depth of the screens changes nothing: no second layer, no per-depth alpha, no accumulated alpha, no extra dim while the help is shown. The F1 top and the scoring pages (nothing in front of them) have no dim.
The REAL screen (menu_ui.draw_menu on an offscreen QImage, a flat light background) is driven. The dimmed picture is compared pixel by pixel with the same picture drawn with the dim switched off: every pixel of the active region is identical,
every pixel of the dim region is darker by exactly ONE layer (x 75/255). The rows of the lists that are outside the frame are drawn too, take no input and are inside the dim region.
RED = fails on the baseline (commit 1, Cursor-Q3); GUARD = passes there and must keep passing. Names: test_red_* / test_guard_*; every RED assertion message starts with 'UI-RED'."""
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


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class SingleDim(Base):
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

    def texts(self, o, state, **flags):
        import menu_ui
        calls = []
        original = menu_ui.draw_text_with_outline

        def record(painter, text, *args, **kwargs):
            calls.append(text)
            return original(painter, text, *args, **kwargs)
        menu_ui.draw_text_with_outline = record
        try:
            self.render(o, state, **flags)
        finally:
            menu_ui.draw_text_with_outline = original
        return calls

    def dim_calls(self, o, state, **flags):
        """the calls of the one dim function during one picture: [(active, inner)] - an AttributeError becomes a RED"""
        import menu_ui
        original = getattr(menu_ui, "_draw_menu_dim", None)
        self.assertIsNotNone(original, "UI-RED: the one dim function (_draw_menu_dim) does not exist")
        calls = []

        def record(painter, view, active, inner=()):
            calls.append((active, list(inner)))
            return original(painter, view, active, inner)
        menu_ui._draw_menu_dim = record
        try:
            self.render(o, state, **flags)
        finally:
            menu_ui._draw_menu_dim = original
        return calls

    def undimmed(self, o, state, **flags):
        import menu_ui
        original = getattr(menu_ui, "_draw_menu_dim", None)
        if original is None:
            return self.render(o, state, **flags)
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

    def channels(self, image, x, y):
        from PyQt6.QtGui import QColor
        c = QColor(image.pixel(int(x), int(y)))
        return c.red(), c.green(), c.blue()

    def check_one_dim(self, o, state, hole, **flags):
        """dimmed picture A vs the same picture without the dim B: inside the hole A == B, everywhere else A == B x (75/255) - ONE layer, no gap, no second layer.
        (The help hint button and the scroll arrows are drawn after the dim on purpose and are left out.)"""
        b = self.undimmed(o, state, **flags)
        calls = self.dim_calls(o, state, **flags)
        inner = calls[0][1] if calls else []                            # the rows outside the frame of a list inside a panel: dimmed on purpose, checked by red_18
        a = self.render(o, state, **flags)
        exempt = []
        for z in o.menu_click_zones:
            if z[4] in (999, 995, 996):
                exempt.append((z[0] - 12, z[1] - 12, z[2] + 12, z[3] + 12))
        x0, y0, x1, y1 = hole
        bad_in, bad_out, seen_out = [], [], 0
        pts = [(x, y) for x in range(3, 1920, 13) for y in range(3, 1080, 13)]
        pts += [(int(x0) + dx, int(y0) + dy) for dx in (-6, -3, 3, 6) for dy in range(0, int(y1 - y0), 17)]
        pts += [(int(x0) + dx, int(y0) + dy) for dy in (-6, -3, 3, 6) for dx in range(0, int(x1 - x0), 17)]
        pts += [(int(x1) + dx, int(y0) + dy) for dx in (-6, -3, 3, 6) for dy in range(0, int(y1 - y0), 17)]
        pts += [(int(x0) + dx, int(y1) + dy) for dy in (-6, -3, 3, 6) for dx in range(0, int(x1 - x0), 17)]
        for x, y in pts:
            if not (0 <= x < 1920 and 0 <= y < 1080) or any(e[0] <= x <= e[2] and e[1] <= y <= e[3] for e in exempt):
                continue
            ca, cb = self.channels(a, x, y), self.channels(b, x, y)
            if x0 + 4 <= x <= x1 - 4 and y0 + 4 <= y <= y1 - 4:
                if any(r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3] for r in inner):
                    continue
                if ca != cb:
                    bad_in.append((x, y, ca, cb))
            elif x < x0 - 4 or x > x1 + 4 or y < y0 - 4 or y > y1 + 4:
                seen_out += 1
                if any(abs(ca[i] - cb[i] * ONE) > 2.0 for i in range(3)):
                    bad_out.append((x, y, ca, cb))
        self.assertGreater(seen_out, 500, "the dim region was sampled")
        return bad_in, bad_out

    # ---- the dim is drawn ONCE at every depth -----------------------------------------------------------------------------------------------------------------------------------
    def test_red_01_a_pop_up_panel_is_covered_by_one_dim(self):
        o = self.build()
        for state in (7, 8, 9):
            calls = self.dim_calls(o, state)
            self.red(len(calls) == 1, "menu_state %d: %d dims in one picture (want 1)" % (state, len(calls)))

    def test_red_02_a_drop_down_is_covered_by_one_dim_not_two(self):
        o = self.build()
        for state in (5, 7, 9):
            o.dropdown_active = False
            self.drop(o)
            calls = self.dim_calls(o, state)
            self.red(len(calls) == 1, "menu_state %d with a drop-down: %d dims in one picture (want 1)" % (state, len(calls)))

    def test_red_03_the_help_is_covered_by_one_dim_not_one_more(self):
        o = self.build()
        got = {}
        for label, state, drop in (("top", 1, False), ("timing", 8, False), ("brake", 7, False), ("page", 5, False), ("brake+dropdown", 7, True)):
            o.dropdown_active = False
            if drop:
                self.drop(o)
            got[label] = len(self.dim_calls(o, state, show_help=True))
            o.show_help = False
        self.red(set(got.values()) == {1}, "dims in one picture while the help is shown: %s (want 1 each)" % got)

    def test_guard_04_nothing_in_front_nothing_dimmed(self):
        o = self.build()
        import menu_ui
        if getattr(menu_ui, "_draw_menu_dim", None) is None:
            return                                                       # (no dim function before this stage)
        for state in (1, 2, 3, 4, 5, 6, 10, 11, 12):
            self.assertEqual(self.dim_calls(o, state), [], "menu_state %d has no front region: no dim" % state)

    def test_red_05_the_darkness_does_not_depend_on_the_depth(self):
        o = self.build()
        base = self.lum(self.undimmed(o, 1), *BACKDROP)
        help_only = self.lum(self.render(o, 1, show_help=True), *BACKDROP)
        o.show_help = False
        self.assertAlmostEqual(help_only, base * ONE, delta=1.6, msg="the help: one dim")
        seen = {}
        for label, state, drop, helped in (("timing", 8, False, False), ("brake", 7, False, False), ("init", 9, False, False), ("brake+dd", 7, True, False), ("page+dd", 5, True, False),
                                           ("init+dd", 9, True, False), ("brake+dd+help", 7, True, True), ("timing+help", 8, False, True), ("page+dd+help", 5, True, True)):
            o.dropdown_active = False
            if drop:
                self.drop(o, n=3, scroll=0, cursor=0)
            seen[label] = self.lum(self.render(o, state, show_help=helped), *BACKDROP)
            o.show_help = False
        self.red(all(abs(v - base * ONE) <= 1.6 for v in seen.values()), "backdrop %d -> one dim = %.1f; got %s" % (base, base * ONE, seen))

    # ---- the three screenshots: the pixels ----------------------------------------------------------------------------------------------------------------------------------------------
    def test_red_06_screenshot_124659_the_timing_window_is_bright_and_everything_around_it_is_dim_once(self):
        o = self.build()
        o.timing_scroll, o.timing_cursor = 0, 0
        self.render(o, 8)
        bad_in, bad_out = self.check_one_dim(o, 8, o.active_panel_rect)
        self.assertEqual(bad_in, [], "UI-RED: inside the window nothing is dimmed (the window, its title, rows, selected row, done button)")
        self.red(bad_out == [], "UI-RED: outside the window every pixel is dimmed exactly once, no gap: %s" % bad_out[:4])

    def test_red_07_screenshot_124725_only_the_small_window_is_bright_the_parent_panel_is_dim_once_like_the_backdrop(self):
        o = self.build()
        self.drop(o, n=3, scroll=0, cursor=0)
        self.render(o, 7)
        bad_in, bad_out = self.check_one_dim(o, 7, o.active_dropdown_rect)
        self.assertEqual(bad_in, [], "UI-RED: the small window is not dimmed")
        self.red(bad_out == [], "UI-RED: the parent panel and the backdrop are both dimmed exactly once: %s" % bad_out[:4])
        # the parent panel is NOT darker than the backdrop: its pixel keeps the ratio of one layer to what it was
        px, py = o.active_panel_rect[0] + 30, o.active_panel_rect[1] + 30
        was = self.lum(self.undimmed(o, 7), px, py)
        now = self.lum(self.render(o, 7), px, py)
        self.red(abs(now - was * ONE) <= 1.6, "the parent panel pixel: undimmed %d, now %d (one layer: %.1f)" % (was, now, was * ONE))

    def test_red_08_screenshot_124603_only_the_station_window_is_bright_the_whole_page_is_dim_once(self):
        o = self.build()
        self.drop(o, n=3, scroll=0, cursor=0)
        self.render(o, 5)
        bad_in, bad_out = self.check_one_dim(o, 5, o.active_dropdown_rect)
        self.assertEqual(bad_in, [], "UI-RED: the station window is not dimmed")
        self.red(bad_out == [], "UI-RED: the page (items, next, explanation box, title, rules), the F1 background and the BVE screen are dimmed exactly once: %s" % bad_out[:4])

    def test_red_09_the_help_window_is_the_only_bright_region_while_it_is_shown(self):
        o = self.build()
        for state, drop in ((1, False), (8, False), (7, True), (5, True)):
            o.dropdown_active = False
            if drop:
                self.drop(o, n=3, scroll=0, cursor=0)
            self.render(o, state, show_help=True)
            bad_in, bad_out = self.check_one_dim(o, state, o.active_help_rect, show_help=True)
            self.assertEqual(bad_in, [], "menu_state %d: the help window is not dimmed" % state)
            self.red(bad_out == [], "menu_state %d: everything else is dimmed exactly once (no second dim over the screen that was there): %s" % (state, bad_out[:3]))
            o.show_help = False

    def test_red_10_opening_and_closing_the_help_neither_accumulates_nor_leaves_a_dim(self):
        o = self.build()
        self.drop(o, n=5, scroll=0, cursor=1)
        before = self.render(o, 7)
        during = self.render(o, 7, show_help=True)
        after = self.render(o, 7, show_help=False)
        self.assertEqual(before, after, "the picture after the help is the picture before it")
        self.red(self.lum(during, *BACKDROP) == self.lum(before, *BACKDROP), "the backdrop is equally dark with and without the help (%d / %d)" % (self.lum(during, *BACKDROP), self.lum(before, *BACKDROP)))
        o.dropdown_active = False
        top_before = self.render(o, 8)
        self.render(o, 8, show_help=True)
        self.assertEqual(top_before, self.render(o, 8, show_help=False))

    def test_red_10b_opening_the_help_only_moves_the_hole_of_the_dim_and_closing_moves_it_back(self):
        o = self.build()
        for state, drop in ((1, False), (8, False), (7, True)):
            o.dropdown_active = False
            if drop:
                self.drop(o, n=3, scroll=0, cursor=0)
            before = self.dim_calls(o, state)
            during = self.dim_calls(o, state, show_help=True)
            after = self.dim_calls(o, state, show_help=False)
            help_rect = o.active_help_rect
            self.red(len(during) == 1 and during[0][0][0] == help_rect[0] - 2 and during[0][0][2] == help_rect[2] + 2, "menu_state %d: the hole of the dim is the help window (%r)" % (state, during[0][0] if during else None))
            self.red(after == before, "menu_state %d: after the help is closed the hole is where it was (%r / %r)" % (state, before, after))
            if before:
                self.assertNotEqual(before[0][0], during[0][0], "the hole moved")
            o.show_help = False

    def test_guard_10c_only_the_panels_and_the_help_have_a_panel_boundary_the_pages_are_whole_screen(self):
        text = source("menu_ui.py")
        self.assertEqual(text.count("QColor(30, 30, 30, 240)"), 4, "the basic brake, timing and initial panels and the help window are the only framed operating regions")
        o = self.build()
        for state in (5, 6, 10):
            img = self.render(o, state)
            xs = [x for x in range(0, 1920, 6) for y in range(60, 1020, 6) if self.lum(img, x, y) != self.lum(img, 5, 5)]
            self.assertGreater(max(xs) - min(xs), 1400, "menu_state %d: the page spans the window (no independent panel boundary)" % state)

    # ---- the geometry of the dim region ----------------------------------------------------------------------------------------------------------------------------------------------
    def test_red_11_the_dim_region_is_the_view_minus_the_active_region_without_gap_or_overlap(self):
        import menu_ui
        rects_of = getattr(menu_ui, "menu_dim_rects", None)
        self.red(rects_of is not None, "menu_dim_rects does not exist")
        rng = random.Random(7)
        for _ in range(300):
            view = (rng.choice((0, -40, 13.5)), rng.choice((0, -25, 7.25)), rng.choice((1920, 837, 2561.5)), rng.choice((1080, 668, 1441.5)))
            ax0, ay0 = view[0] + rng.uniform(-50, view[2] - 5), view[1] + rng.uniform(-50, view[3] - 5)
            active = (ax0, ay0, ax0 + rng.uniform(1, view[2]), ay0 + rng.uniform(1, view[3]))
            rects = rects_of(view, active)
            vx0, vy0, vx1, vy1 = int(view[0] // 1), int(view[1] // 1), -int(-(view[0] + view[2]) // 1), -int(-(view[1] + view[3]) // 1)
            cells = {}
            for x, y, w, h in rects:
                self.assertTrue(w > 0 and h > 0, "no empty rectangle: %r" % ((x, y, w, h),))
                self.assertTrue(x >= vx0 and y >= vy0 and x + w <= vx1 and y + h <= vy1, "clamped to the view: %r" % ((x, y, w, h),))
            for gx in range(vx0, vx1, max(1, (vx1 - vx0) // 40)):
                for gy in range(vy0, vy1, max(1, (vy1 - vy0) // 40)):
                    n = sum(1 for x, y, w, h in rects if x <= gx < x + w and y <= gy < y + h)
                    inside = int(active[0] // 1) <= gx < -int(-active[2] // 1) and int(active[1] // 1) <= gy < -int(-active[3] // 1)
                    self.assertEqual(n, 0 if inside else 1, "pixel (%d, %d): dimmed %d times (active region %r)" % (gx, gy, n, active))

    def test_red_12_no_active_region_or_an_empty_one_dims_the_whole_view_once(self):
        import menu_ui
        rects_of = getattr(menu_ui, "menu_dim_rects", None)
        self.red(rects_of is not None, "menu_dim_rects does not exist")
        self.assertEqual(rects_of((0, 0, 100, 50), None), [(0, 0, 100, 50)])
        self.assertEqual(rects_of((0, 0, 100, 50), (30, 30, 30, 40)), [(0, 0, 100, 50)])
        self.assertEqual(rects_of((0, 0, 100, 50), (-10, -10, 200, 200)), [], "an active region that covers the view dims nothing")

    # ---- the state ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def test_red_13_going_back_moves_the_active_region_and_leaving_removes_the_dim(self):
        o = self.build()
        self.drop(o, n=14, scroll=0, cursor=0)
        first = self.dim_calls(o, 7)
        self.assertEqual(len(first), 1)
        drop_rect = o.active_dropdown_rect
        o.dropdown_active = False                                         # the Backspace of the drop-down (main._handle_keys)
        second = self.dim_calls(o, 7)
        self.red(len(second) == 1 and second[0][0][0] < drop_rect[0] and second[0][0][2] > drop_rect[2], "back from the drop-down: the active region is the panel again: %r vs %r" % (second, drop_rect))
        o.menu_state = 7
        o.handle_menu_backspace(False)                                    # the panel -> the page 1/3: nothing in front, nothing dimmed
        self.assertEqual(o.menu_state, 5)
        self.assertEqual(self.dim_calls(o, 5), [])
        o.handle_menu_backspace(False)                                    # the page -> the F1 top
        self.assertEqual(o.menu_state, 1)
        self.assertEqual(self.dim_calls(o, 1), [])
        self.assertIn("self.menu_state != 0", source("menu_ui.py"))      # (the closed menu draws no help hint; main draws no menu at all: menu_state 0)

    def test_guard_14_a_picture_that_fails_leaves_no_dim_state_and_gives_the_click_zones_back(self):
        import menu_ui
        o = self.build()
        o.timing_scroll, o.timing_cursor = 3, 5
        names = self.texts(o, 8)
        ghost = [n for n in names if n.startswith("Stn")][0]
        original = menu_ui.draw_text_with_outline

        def boom(painter, text, *a, **k):
            if text == ghost:
                raise RuntimeError("the row failed")
            return original(painter, text, *a, **k)
        menu_ui.draw_text_with_outline = boom
        zones = []
        try:
            o.menu_click_zones = zones
            from PyQt6.QtGui import QImage, QPainter
            image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            try:
                with self.assertRaises(RuntimeError):
                    menu_ui.draw_menu(o, painter, 1920.0)
            finally:
                painter.end()
        finally:
            menu_ui.draw_text_with_outline = original
        self.red(o.menu_click_zones is zones, "the click zone list is the real one again after the failure")
        a, b = self.render(o, 8), self.render(o, 8)
        self.assertEqual(a, b, "the next picture is the same as the one before: the dim keeps no state")

    # ---- the rows outside the frame ---------------------------------------------------------------------------------------------------------------------------------------------------
    def test_red_15_timing_rows_next_to_the_frame_are_drawn(self):
        o = self.build()
        targets = o.get_timing_target_stas()
        self.assertGreaterEqual(len(targets), 10)
        o.timing_scroll, o.timing_cursor = 3, 5
        names = self.texts(o, 8)
        name = lambda k: o.station_list[targets[k]]["name"]
        for k in range(3, 9):
            self.assertIn(name(k), names, "a row inside the frame is drawn as before")
        self.red(name(2) in names and name(9) in names, "the rows just outside the frame (above %s, below %s) are drawn" % (name(2), name(9)))
        self.assertNotIn(name(1), names, "a row that does not fit whole in the free band is not drawn (no cut text)")
        self.assertNotIn(name(10), names)

    def test_red_16_basic_brake_and_initial_rows_outside_the_frame_are_drawn(self):
        o = self.build()
        o.sub_scroll, o.sub_cursor = 1, 4
        self.red(self.texts(o, 7).count("制動 /") == 5 + 2, "basic brake: 5 rows inside the frame + 1 above + 1 below")
        o.init_sub_scroll, o.init_sub_cursor = 1, 4
        self.red(self.texts(o, 9).count("初動") == 5 + 1, "initial / relaxation: 5 rows inside the frame + 1 below (the title is too close for a whole row above)")

    def test_red_17_station_dropdown_rows_outside_the_frame_are_drawn_whole_inside_the_screen(self):
        o = self.build()
        self.drop(o, n=14, scroll=4, cursor=6)
        names = self.texts(o, 5)
        for k in range(4, 11):
            self.assertIn("Opt%02d" % k, names, "the rows inside the frame")
        self.red(all(("Opt%02d" % k) in names for k in (3, 2, 1, 0, 11, 12, 13)), "every row that fits whole on the screen above and below the frame is drawn: %s" % [n for n in names if n.startswith("Opt")])

    def test_red_18_rows_outside_the_frame_are_under_the_one_dim_the_rows_inside_are_not(self):
        o = self.build()
        o.timing_scroll, o.timing_cursor = 3, 5
        un = self.undimmed(o, 8)
        di = self.render(o, 8)
        for label, (x, y), dimmed in (("inside", (415, 347), False), ("above", (415, 272), True), ("below", (415, 797), True)):
            was, now = self.lum(un, x, y), self.lum(di, x, y)
            self.assertGreater(was, 20, label)
            self.red((abs(now - was * ONE) <= 1.6) if dimmed else (now == was), "timing row %s the frame: undimmed %d, now %d" % (label, was, now))
        o.sub_scroll, o.sub_cursor = 1, 4
        un, di = self.undimmed(o, 7), self.render(o, 7)
        for label, (x, y), dimmed in (("inside", (135, 375), False), ("above", (135, 305), True), ("below", (135, 725), True)):
            was, now = self.lum(un, x, y), self.lum(di, x, y)
            self.assertGreater(was, 20, label)
            self.red((abs(now - was * ONE) <= 1.6) if dimmed else (now == was), "basic brake row %s the frame: undimmed %d, now %d" % (label, was, now))
        o.dropdown_active = False
        self.drop(o, n=14, scroll=4, cursor=6)
        un, di = self.undimmed(o, 5), self.render(o, 5)
        x0, y0, x1, y1 = o.active_dropdown_rect
        row_h = (y1 - y0 - 20) / 7.0
        for label, (x, y), dimmed in (("inside", (x0 + 8, y0 + 4), False), ("above", (x0 + 8, y0 + 10 - row_h + 2), True), ("below", (x0 + 8, y1 + 4), True)):
            was, now = self.lum(un, x, y), self.lum(di, x, y)
            self.assertGreater(was, 12, label)
            self.red((abs(now - was * ONE) <= 1.6) if dimmed else (now == was), "drop-down row %s the frame: undimmed %d, now %d" % (label, was, now))

    def test_guard_19_rows_outside_the_frame_take_no_input(self):
        o = self.build()
        self.drop(o, n=14, scroll=4, cursor=6)
        self.render(o, 5)
        x0, y0, x1, y1 = o.active_dropdown_rect
        for zone in o.menu_click_zones:
            if zone[4] in (995, 996, 999):                  # the scroll arrows and the help button are not rows
                continue
            self.assertGreaterEqual(zone[1], y0 - 1, "no zone above the frame: %r" % (zone,))
            self.assertLessEqual(zone[3], y1 + 1, "no zone below the frame: %r" % (zone,))
            if zone[4] == 997:
                self.assertTrue(4 <= zone[5] <= 10, "only options inside the frame are clickable: %r" % (zone,))
        o.dropdown_active = False
        o.timing_scroll, o.timing_cursor = 3, 5
        self.render(o, 8)
        indexes = {z[4] for z in o.menu_click_zones if len(z) == 6 and z[5] == -1}
        self.assertTrue(indexes and indexes <= set(range(3, 10)) | {len(o.get_timing_target_stas())}, "timing zones only inside the frame (plus the done button): %s" % sorted(indexes))
        o.sub_scroll, o.sub_cursor = 1, 4
        self.render(o, 7)
        rows = {z[4] for z in o.menu_click_zones if len(z) == 6 and z[5] in (0, 1, 2) and z[4] < 100}
        self.assertTrue(rows <= set(range(1, 6)) | {0, 6} and not ({0, 6} & rows), "the rows 0 and 6 are outside the frame (rows 1..5) and take no click: %s" % sorted(rows))

    def test_guard_20_the_selected_row_is_always_inside_the_bright_frame(self):
        o = self.build(stations=24, rules=9)
        o.menu_state = 8
        o.timing_scroll = 0
        o.timing_cursor = o._timing_cursor_stops()[0]
        for _ in range(40):
            o.handle_menu_down()
            self.assertTrue(o.timing_scroll <= o.timing_cursor < o.timing_scroll + 6 or o.timing_cursor >= len(o.get_timing_target_stas()), "timing cursor %d scroll %d" % (o.timing_cursor, o.timing_scroll))
        for _ in range(40):
            o.handle_menu_up()
            self.assertTrue(o.timing_scroll <= o.timing_cursor < o.timing_scroll + 6 or o.timing_cursor >= len(o.get_timing_target_stas()), "timing cursor %d scroll %d" % (o.timing_cursor, o.timing_scroll))
        o.menu_state, o.sub_scroll, o.sub_cursor, o.sub_cursor_x = 7, 0, 0, 0
        for _ in range(30):
            o.handle_menu_down()
            if o.sub_cursor < len(o.brake_rules):
                self.assertTrue(o.sub_scroll <= o.sub_cursor < o.sub_scroll + 5, "sub cursor %d scroll %d" % (o.sub_cursor, o.sub_scroll))

    def test_guard_21_the_same_state_draws_the_same_picture(self):
        o = self.build()
        o.sub_scroll, o.sub_cursor, o.sub_cursor_x = 1, 4, 0
        self.assertEqual(self.render(o, 7), self.render(o, 7), "no flicker")
        o.timing_scroll, o.timing_cursor = 3, 5
        self.assertEqual(self.render(o, 8), self.render(o, 8))

    def test_red_22_a_row_that_fails_to_draw_gives_the_click_zones_back_and_reports_its_rectangle(self):
        import menu_ui
        from PyQt6.QtGui import QImage, QPainter
        o = self.build()
        o.menu_click_zones = ["keep"]
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        slots = getattr(menu_ui, "_list_row_slots", None)
        self.red(slots is not None, "the slot helper does not exist")
        try:
            rects = []
            gen = slots(o, painter, 3, 12, 6, lambda i: (0, 10 + 5 * i, 10, 4), (-100, 1000), rects)
            outside_seen = False
            with self.assertRaises(RuntimeError):
                for i in gen:
                    if i < 0:
                        outside_seen = True
                        self.assertEqual(o.menu_click_zones, [], "a row outside the frame writes its zones to a scratch list")
                        raise RuntimeError("the row failed")
            gen.close()
            self.assertTrue(outside_seen)
            self.assertEqual(o.menu_click_zones, ["keep"], "the zones are back after a failure")
            self.assertEqual(rects, [(0, 10 + 5 * -3, 10, 4)], "the rectangle of the (first) row outside the frame is reported for the dim")
        finally:
            painter.end()

    # ---- independence / untouched contracts / the old contract is gone -----------------------------------------------------------------------------------------------------
    def test_red_23_the_cumulative_contract_is_gone_from_the_source(self):
        text = source("menu_ui.py")
        for word in ("menu_hierarchy_level", "MENU_HIERARCHY", "_draw_menu_dim_layer", "hierarchy"):
            self.assertNotIn(word, text, "UI-RED: the superseded cumulative layers: " + word)
        self.red("MENU_DIM_RGBA = (0, 0, 0, 180)" in text, "the one constant of the dim colour does not exist")
        self.assertEqual(text.count("QColor(*MENU_DIM_RGBA)"), 1, "the colour is read from the one constant in exactly one place")
        self.assertEqual(text.count("QColor(0, 0, 0, 180)"), 0, "no second spelling of the colour")
        calls = [l for l in text.splitlines() if "_draw_menu_dim(painter" in l and "def " not in l]
        self.red(len(calls) == 2, "the dim is drawn at two places only - the normal screens and the help, never both in one picture: %d" % len(calls))
        self.assertEqual(text.count("painter.setBrush(QColor(0, 0, 0, 220))"), 1, "the common F1 background layer (alpha 220) stays as it is")

    def test_guard_the_dim_is_independent_of_the_cursor_override_and_of_the_hosts(self):
        text = source("menu_ui.py")
        for word in ("OverrideCursor", "QCursor", "setCursor", "_operation_cursor", "Legacy", "Current", "BVE5", "BVE6", "legacy", "bve5", "bve6"):
            self.assertNotIn(word, text, "menu_ui.py: " + word)
        main_text = source("main.py")
        for word in ("MENU_DIM_RGBA", "_draw_menu_dim", "menu_dim_rects", "_list_row_slots"):
            self.assertNotIn(word, main_text, "main.py does not know the dim: " + word)
        for name in ("hud_ui.py", "managed_hud.py", "managed_input.py", "managed_state.py", "managed_mode.py"):
            other = source(name)
            for word in ("MENU_DIM_RGBA", "_draw_menu_dim", "menu_dim_rects"):
                self.assertNotIn(word, other, name)

    def test_guard_the_dim_is_no_input_target_and_the_pages_keep_their_titles(self):
        text = source("menu_ui.py")
        if "def _draw_menu_dim(painter, view, active, inner=()):" not in text:
            return                                                        # (no dim function before this stage)
        block = text[text.index("def _draw_menu_dim(painter"):text.index("def _list_row_slots")]
        self.assertNotIn("menu_click_zones", block, "the dim registers no click zone")
        self.assertNotIn("show_help", block)
        o = self.build()
        self.assertIn("=== 採点設定 (1/3) ===", self.texts(o, 5))
        self.assertIn("=== 運転時分 設定 ===", self.texts(self.build(), 8))
        o.dropdown_active = False
        self.drop(o)
        calls = self.texts(o, 5)
        self.assertLess(calls.index("Opt05"), calls.index("操作説明 : H"), "the help hint button stays after the drop-down")

    def test_guard_the_common_f1_layer_and_the_stage_ui4_contract_stay(self):
        text = source("menu_ui.py")
        self.assertEqual(text.count("drawRect(0, 0, int(logical_width), int(BASE_SCREEN_H))"), 1)
        self.assertEqual(text.count("# Stage UI-4: no second dim layer here"), 3)


if __name__ == "__main__":
    unittest.main()
