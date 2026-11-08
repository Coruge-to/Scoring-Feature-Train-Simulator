"""Stage UI-D4 (Owner contract 2026-11-08 after the live Run CUI-C-02). This FILE REPLACES tests/test_ui_single_dim.py (the single-dim contract of af46056, which the Owner withdrew).

Contract (menu_ui.draw_menu), the dims of the F1 screens are LAYERED, one layer per step of the operation hierarchy:
  * F1 common layer alpha 220 (always, first), pop-up panel layer alpha 180, drop-down layer alpha 180, operation help layer alpha 180 - the two alphas are NOT unified, their effects multiply (the Owner's specification).
  * every layer is ONE rectangle that covers the whole window and is drawn at most ONCE per frame; what stays bright on a layer is drawn AFTER that layer's dim. No dim is built from touching rectangles or a hole: the shared edges fall on
    fractional pixels under Antialiasing and left the thin light line of the live Run CUI-C-02 (row 190, 436, 461 of the 918x627 window).
  * the page behind a pop-up panel is drawn (basic brake and operating time: scoring page 1/3, initial / relaxation: 2/3); no row outside a list frame is drawn (the preview rows are a later commit); the panel background stays (30,30,30,240).
  * input (the help does not stop input), Cursor-Q3 and the rest of main.py / managed_input.py are unchanged.
The REAL screen (menu_ui.draw_menu on an offscreen QImage, a flat background, Antialiasing ON as in Overlay.paintEvent, windows of non-integer menu_scale) is driven.
RED = fails on the baseline af46056; GUARD = passes there. Names: test_red_* / test_guard_*; every RED assertion message starts with 'UI-RED'."""
import ast
import hashlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbh_bulk_timing_button import Base, setUpModule, tearDownModule  # noqa: E402,F401

BG = 200
K220 = 1.0 - 220 / 255.0
K180 = 1.0 - 180 / 255.0
SIZES = ((1920, 1080), (918, 627), (919, 627), (1280, 720), (1366, 768), (1280, 1440))
LIVE = (918, 627)                                      # the BVE window of the live Run CUI-C-02: menu_scale 0.478125, a letter box above and below
PAGE_STATES = (1, 2, 3, 4, 5, 6, 10, 12)
PANELS = (7, 8, 9)


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class Layered(Base):
    # ------------------------------------------------------------------ the scene
    def build(self, stations=12, rules=8):
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

    def drop(self, o, n=12, scroll=0, cursor=0):
        o.dropdown_active = True
        o.dropdown_options = [{"idx": i, "name": "Opt%02d" % i} for i in range(n)]
        o.dropdown_scroll, o.dropdown_cursor = scroll, cursor

    def setup(self, o, name):
        """-> (menu_state, layers) : the alphas of the dim layers the contract wants, bottom to top"""
        o.show_help = False
        o.dropdown_active = False
        o.dropdown_options = []
        if name.startswith("page"):
            return int(name[4:]), [220]
        if name.startswith("panel"):
            return int(name[5:]), [220, 180]
        if name == "dd_page":
            self.drop(o, 12, 0, 0)
            return 5, [220, 180]
        if name == "dd_panel":
            self.drop(o, 5, 0, 0)
            return 7, [220, 180, 180]
        if name == "help_page":
            o.show_help = True
            return 5, [220, 180]
        if name == "help_panel":
            o.show_help = True
            return 7, [220, 180, 180]
        if name == "help_dd_panel":
            self.drop(o, 5, 0, 0)
            o.show_help = True
            return 7, [220, 180, 180, 180]
        raise KeyError(name)

    SCENARIOS = ["page%d" % s for s in PAGE_STATES] + ["panel7", "panel8", "panel9", "dd_page", "dd_panel", "help_page", "help_panel", "help_dd_panel"]

    # ------------------------------------------------------------------ the rendering
    def render(self, o, state, width=1920, height=1080, painter_cls=None):
        from PyQt6.QtGui import QImage, QPainter, QColor
        import menu_ui
        o.menu_state = state
        o.width = lambda: width
        o.height = lambda: height
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(BG, BG, BG))
        painter = (painter_cls or QPainter)(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)          # exactly what Overlay.paintEvent does
        o.menu_click_zones = []
        try:
            menu_ui.draw_menu(o, painter, width / (height / 1080.0))
            aa_after = painter.testRenderHint(QPainter.RenderHint.Antialiasing)
        finally:
            painter.end()
        self.aa_after = aa_after
        return image

    def channel(self, image, x, y):
        from PyQt6.QtGui import QColor
        c = QColor(image.pixel(int(x), int(y)))
        return c.red()

    def no_dims(self):
        """context: every dim function does nothing (the same picture without the dim)"""
        import menu_ui
        names = [n for n in ("_draw_menu_layer_dim", "_draw_menu_dim") if hasattr(menu_ui, n)]
        saved = {n: getattr(menu_ui, n) for n in names}

        class Ctx:
            def __enter__(s):
                for n in names:
                    setattr(menu_ui, n, lambda *a, **k: None)

            def __exit__(s, *e):
                for n, f in saved.items():
                    setattr(menu_ui, n, f)
        return Ctx()

    def layer_calls(self, o, state, width=1920, height=1080):
        """the dim layers drawn by one frame: [(rgba, view)] in drawing order"""
        import menu_ui
        fn = getattr(menu_ui, "_draw_menu_layer_dim", None)
        self.assertIsNotNone(fn, "UI-RED: the layer dim function (_draw_menu_layer_dim) does not exist")
        calls = []

        def spy(painter, view, rgba):
            calls.append((tuple(rgba), tuple(view)))
            return fn(painter, view, rgba)
        menu_ui._draw_menu_layer_dim = spy
        try:
            self.render(o, state, width, height)
        finally:
            menu_ui._draw_menu_layer_dim = fn
        return calls

    def dim_rects(self, o, state, width, height):
        """every filled rectangle of alpha 220 or 180 with no pen: the window-space rectangle (a QPainter subclass sees the real drawRect calls)"""
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QPainter
        out = []

        class Spy(QPainter):
            def drawRect(self, *args):
                a = self.brush().color().alpha()
                if a in (220, 180) and self.pen().style() == Qt.PenStyle.NoPen and self.brush().color().red() == 0 and self.brush().color().green() == 0:
                    r = args[0] if len(args) == 1 else QRectF(*args)
                    m = self.worldTransform().mapRect(QRectF(r))
                    out.append((a, m.left(), m.top(), m.right(), m.bottom()))
                return super().drawRect(*args)
        self.render(o, state, width, height, painter_cls=Spy)
        return out

    def expect(self, layers):
        v = BG
        for a in layers:
            v *= (K220 if a == 220 else K180)
        return v

    def edge_bad_rows(self, o, state, layers, width, height):
        """the rows where the left / right window edge (outside every frame) is not exactly 'dimmed once per layer'"""
        image = self.render(o, state, width, height)
        want = self.expect(layers)
        bad = set()
        for x in (3, width - 4):
            for y in range(height):
                if abs(self.channel(image, x, y) - want) > 2.5:
                    bad.add(y)
        return sorted(bad)

    # ================================================================== RED
    def test_red_01_constants_220_and_180_are_not_unified(self):
        import menu_ui
        self.assertEqual(getattr(menu_ui, "MENU_BASE_DIM_RGBA", None), (0, 0, 0, 220), "UI-RED: the F1 common layer is alpha 220")
        self.assertEqual(getattr(menu_ui, "MENU_CHILD_DIM_RGBA", None), (0, 0, 0, 180), "UI-RED: the panel / drop-down / help layers are alpha 180")

    def test_red_02_layer_alphas_per_picture(self):
        o = self.build()
        for name in self.SCENARIOS:
            state, layers = self.setup(o, name)
            calls = self.layer_calls(o, state)
            self.assertEqual([c[0][3] for c in calls], layers, "UI-RED: %s: the layers (alpha, bottom to top) are %s, once each" % (name, layers))

    def test_red_03_every_layer_is_one_rectangle_over_the_whole_window(self):
        o = self.build()
        for name in self.SCENARIOS:
            for w, h in (LIVE, (1920, 1080), (1366, 768)):
                state, layers = self.setup(o, name)
                rects = self.dim_rects(o, state, w, h)
                self.assertEqual([r[0] for r in rects], layers, "UI-RED: %s %dx%d: exactly one filled dim rectangle per layer (no splitting, no hole): %s" % (name, w, h, rects))
                for a, x0, y0, x1, y1 in rects:
                    self.assertTrue(x0 <= 0 and y0 <= 0 and x1 >= w and y1 >= h, "UI-RED: %s %dx%d: the dim rectangle covers the whole window: %s" % (name, w, h, (x0, y0, x1, y1)))

    def test_red_04_the_dim_function_has_no_interior_edge_and_leaves_antialiasing_alone(self):
        text = source("menu_ui.py")
        tree = ast.parse(text)
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("_draw_menu_layer_dim", fns, "UI-RED: the layer dim function exists")
        for gone in ("menu_dim_rects", "_subtract", "_draw_menu_dim", "dropdown_preview_slots"):
            self.assertNotIn(gone, fns, "UI-RED: %s (touching rectangles / a hole / preview rows) is gone" % gone)
        body = ast.get_source_segment(text, fns["_draw_menu_layer_dim"])
        self.assertEqual(body.count("drawRect("), 1, "UI-RED: one rectangle")
        for bad in ("setRenderHint", "QPainterPath", "drawPath", "setClip", "for "):
            self.assertNotIn(bad, body, "UI-RED: the dim function has no '%s'" % bad)
        self.assertNotIn("front_rects", text)
        self.assertNotIn("MENU_DIM_RGBA", text.replace("MENU_BASE_DIM_RGBA", "").replace("MENU_CHILD_DIM_RGBA", ""))

    def test_guard_05_antialiasing_is_still_on_after_the_frame(self):
        o = self.build()
        for name in ("panel7", "dd_page", "help_panel"):
            state, _ = self.setup(o, name)
            self.render(o, state, *LIVE)
            self.assertTrue(self.aa_after, "%s: the frame leaves the Antialiasing of the painter as it was" % name)

    def test_red_06_the_window_edge_has_exactly_the_layers_of_the_picture(self):
        o = self.build()
        for name in self.SCENARIOS:
            state, layers = self.setup(o, name)
            bad = self.edge_bad_rows(o, state, layers, *LIVE)
            self.assertEqual(bad, [], "UI-RED: %s %dx%d: the window edge is dimmed by the layers %s (rows that differ: %s)" % (name, LIVE[0], LIVE[1], layers, bad[:12]))

    def test_red_07_no_light_seam_in_a_non_integer_menu_scale_window(self):
        o = self.build()
        for w, h in SIZES:
            for name in self.SCENARIOS:
                state, layers = self.setup(o, name)
                bad = self.edge_bad_rows(o, state, layers, w, h)
                self.assertEqual(bad, [], "UI-RED: %s %dx%d: no row of the window edge is lighter than 'dimmed by %s' (a seam): %s" % (name, w, h, layers, bad[:12]))

    def test_red_08_the_seam_rows_of_the_live_run_are_gone(self):
        # CUI-C-02 screenshot 182836: station drop-down over the scoring page 1/3, 918x627: the line at y=190 (the top of the frame), y=436 (its bottom), y=461 (the bottom of the arrow tile)
        o = self.build()
        for w in (918, 919):
            self.setup(o, "dd_page")
            image = self.render(o, 5, w, 627)
            want = self.expect([220, 180])
            for y in (190, 436, 461):
                for x in (3, w - 4):
                    self.assertLess(abs(self.channel(image, x, y) - want), 2.5, "UI-RED: row %d at x=%d of the %dx627 window is dimmed like its neighbours (seam)" % (y, x, w))

    def test_red_09_bright_content_is_drawn_after_its_layer(self):
        # a panel / a drop-down frame / the help window sits OVER the dimmed picture: its interior is its own colour over the dimmed picture below (the layers below only), never dimmed itself
        o = self.build()
        # (scenario, logical x, y of a text-free spot inside the bright content, its RGB gray, alpha 240, the layers below it)
        checks = (("panel7", 130, 140, 30, [220, 180]), ("panel8", 330, 90, 30, [220, 180]), ("panel9", 130, 90, 30, [220, 180]),
                  ("dd_page", 842, 289, 20, [220, 180]), ("dd_panel", 842, 359, 20, [220, 180, 180]), ("help_page", 730, 395, 30, [220, 180]))
        for name, lx, ly, gray, below in checks:
            state, _ = self.setup(o, name)
            w, h = 1920, 1080
            image = self.render(o, state, w, h)
            under = BG
            for a in below:
                under *= (K220 if a == 220 else K180)
            want = gray * (240 / 255.0) + under * (15 / 255.0)
            got = self.channel(image, lx, ly)
            self.assertLess(abs(got - want), 3.5, "UI-RED: %s: the bright content at (%d,%d) is %d, expected %.1f (its colour over the layers below %s)" % (name, lx, ly, got, want, below))

    def test_guard_10_the_parent_page_is_drawn_behind_the_panels(self):
        o = self.build()
        for state, behind, other in ((7, "=== 採点設定 (1/3) ===", "=== 採点設定 (2/3) ==="), (8, "=== 採点設定 (1/3) ===", "=== 採点設定 (2/3) ==="), (9, "=== 採点設定 (2/3) ===", "=== 採点設定 (1/3) ===")):
            self.setup(o, "panel%d" % state)
            texts = self.texts(o, state)
            self.assertIn(behind, texts, "menu_state %d: the parent page is drawn" % state)
            self.assertNotIn(other, texts, "menu_state %d" % state)

    def test_red_11_the_layer_of_a_drop_down_covers_the_arrows_of_the_screen_behind_it(self):
        # the arrows of the panel behind a drop-down are drawn BEFORE the drop-down layer (so they are dimmed), the arrows of the drop-down itself are bright
        import menu_ui
        o = self.build(rules=8)
        o.sub_scroll = 1                                                # the basic brake panel scrolls: its up and down arrows exist
        self.drop(o, 12, 3, 4)
        events = []
        original_text, fn = menu_ui.draw_text_with_outline, getattr(menu_ui, "_draw_menu_layer_dim", None)
        self.assertIsNotNone(fn, "UI-RED: the layer dim function does not exist")

        def text(painter, t, *a, **k):
            events.append(t)
            return original_text(painter, t, *a, **k)

        def spy(painter, view, rgba):
            events.append(("DIM", rgba[3]))
            return fn(painter, view, rgba)
        menu_ui.draw_text_with_outline, menu_ui._draw_menu_layer_dim = text, spy
        try:
            self.render(o, 7, 1920, 1080)
        finally:
            menu_ui.draw_text_with_outline, menu_ui._draw_menu_layer_dim = original_text, fn
        dims = [i for i, e in enumerate(events) if isinstance(e, tuple)]
        self.assertEqual([events[i][1] for i in dims], [220, 180, 180], "UI-RED: the layers of a drop-down over a panel")
        last_dim = dims[-1]
        arrows_before = [i for i, e in enumerate(events) if e in ("▲", "▼") and i < last_dim]
        arrows_after = [i for i, e in enumerate(events) if e in ("▲", "▼") and i > last_dim]
        self.assertTrue(arrows_before, "UI-RED: the arrows of the panel behind the drop-down are drawn before its layer (dimmed)")
        self.assertEqual(len(arrows_after), 2, "UI-RED: the drop-down draws its own two arrows after its layer (bright)")

    def test_red_12_the_help_layer_is_the_last_dim_and_the_help_is_drawn_after_it(self):
        import menu_ui
        o = self.build()
        self.setup(o, "help_panel")
        events = []
        original_text, fn = menu_ui.draw_text_with_outline, getattr(menu_ui, "_draw_menu_layer_dim", None)
        self.assertIsNotNone(fn, "UI-RED: the layer dim function does not exist")

        def text(painter, t, *a, **k):
            events.append(t)
            return original_text(painter, t, *a, **k)

        def spy(painter, view, rgba):
            events.append(("DIM", rgba[3]))
            return fn(painter, view, rgba)
        menu_ui.draw_text_with_outline, menu_ui._draw_menu_layer_dim = text, spy
        try:
            self.render(o, 7, 1920, 1080)
        finally:
            menu_ui.draw_text_with_outline, menu_ui._draw_menu_layer_dim = original_text, fn
        last_dim = max(i for i, e in enumerate(events) if isinstance(e, tuple))
        self.assertEqual([e[1] for e in events if isinstance(e, tuple)], [220, 180, 180], "UI-RED: help over a panel: 220, panel 180, help 180")
        self.assertIn("=== 操作説明 ===", events[last_dim + 1:], "UI-RED: the help window is drawn after the help layer")
        self.assertNotIn("=== 操作説明 ===", events[:last_dim])

    def test_red_13_the_panel_texts_and_the_rest_of_the_source_keep_the_layer_calls_once_per_step(self):
        text = source("menu_ui.py")
        self.assertEqual(text.count("_draw_menu_layer_dim(painter, (0, 0, self.width(), self.height()), MENU_BASE_DIM_RGBA)"), 1, "UI-RED: the common layer is drawn in one place")
        self.assertEqual(text.count("_draw_menu_layer_dim(painter, view, MENU_CHILD_DIM_RGBA)"), 5, "UI-RED: the child layers: three panels, the drop-down, the help")

    # ================================================================== GUARD
    def texts(self, o, state):
        import menu_ui
        out = []
        original = menu_ui.draw_text_with_outline

        def record(painter, t, *a, **k):
            out.append(t)
            return original(painter, t, *a, **k)
        menu_ui.draw_text_with_outline = record
        try:
            self.render(o, state, 1920, 1080)
        finally:
            menu_ui.draw_text_with_outline = original
        return out

    def test_guard_14_no_row_outside_the_frame_of_a_drop_down_is_drawn(self):
        o = self.build()
        for n, scroll in ((12, 0), (12, 3), (12, 5), (5, 0)):
            self.drop(o, n, scroll, scroll)
            texts = self.texts(o, 5)
            drawn = sorted(t for t in texts if t.startswith("Opt"))
            want = sorted("Opt%02d" % i for i in range(scroll, min(n, scroll + 7)))
            self.assertEqual(drawn, want, "drop-down %d options, scroll %d: only the rows inside the frame (no ghost, no leak)" % (n, scroll))

    def test_guard_15_no_ghost_row_in_the_panel_lists(self):
        o = self.build(stations=14, rules=9)
        o.sub_scroll = o.init_sub_scroll = 2
        o.timing_scroll = 2
        for state, marker, count in ((7, "制動 /", 5), (9, "制動 /", None)):
            self.setup(o, "panel%d" % state)
            texts = self.texts(o, state)
            panel = texts[texts.index({7: "=== 基本制動 設定 ===", 9: "=== 初動・緩和ブレーキ 設定 ==="}[state]):]
            if count is not None:
                self.assertEqual(panel.count(marker), count, "menu_state %d: the five rows of the list, no ghost row" % state)
        self.setup(o, "panel8")
        panel = self.texts(o, 8)
        panel = panel[panel.index("=== 運転時分 設定 ==="):]
        self.assertLessEqual(len([t for t in panel if t.startswith("Stn")]), 6 * 3, "menu_state 8: at most the six rows of the list")

    def test_guard_16_the_panel_and_drop_down_backgrounds_keep_their_alpha(self):
        text = source("menu_ui.py")
        self.assertEqual(text.count("painter.setBrush(QColor(30, 30, 30, 240))"), 4, "panels 7, 8, 9 and the help window: (30,30,30,240)")
        self.assertIn(text.count("painter.setBrush(QColor(20, 20, 20, 240))"), (2, 3), "the drop-down frame and its arrow tiles (and, on the baseline, the preview rows): (20,20,20,240)")

    def test_guard_17_input_and_cursor_q3_code_is_unchanged(self):
        """the functions of main.py / managed_input.py that handle the help key, the input ownership and the override cursor, as AST hashes of af46056"""
        pinned = {
            "main.py": {}, "managed_input.py": {},
        }
        got = {}
        for name in pinned:
            tree = ast.parse(source(name))
            h = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seg = ast.dump(node)
                    if any(k in seg for k in ("show_help", "set_input_ownership", "setOverrideCursor", "restoreOverrideCursor", "dropdown_active", "menu_click_zones")):
                        h[node.name] = hashlib.sha256(seg.encode("utf-8")).hexdigest()[:16]
            got[name] = h
        self.assertEqual(got, INPUT_PINS, "the input / Cursor-Q3 functions differ from af46056")

    def test_guard_18_click_zones_are_unchanged(self):
        o = self.build()
        got = {}
        for name in ("page5", "panel7", "panel8", "panel9", "dd_page", "dd_panel", "help_page"):
            state, _ = self.setup(o, name)
            self.render(o, state, 1920, 1080)
            got[name] = hashlib.sha256(repr(sorted((tuple(round(float(v), 1) if isinstance(v, float) else v for v in z) for z in o.menu_click_zones), key=repr)).encode("utf-8")).hexdigest()[:16]
        self.assertEqual(got, ZONE_PINS, "the input zones (menu_click_zones) differ from af46056")

    def test_guard_19_the_hint_button_and_the_selected_row_stay_in_the_frame(self):
        o = self.build()
        self.drop(o, 12, 3, 5)
        self.render(o, 5, 1920, 1080)
        x0, y0, x1, y1 = o.active_dropdown_rect
        rows = [z for z in o.menu_click_zones if len(z) >= 6 and z[4] == 997]
        self.assertTrue(rows and all(y0 <= z[1] and z[3] <= y1 for z in rows), "every row of the drop-down is inside its frame")
        self.assertIn(5, [z[5] for z in rows], "the selected row is in the frame")


INPUT_PINS = {
    "main.py": {
        "__init__": "438104e491aeff0d",
        "_handle_keys": "2fdff247b333c919",
        "_handle_mouse": "7afa380eb3c20e77",
        "_sync_operation_cursor": "b50358a62b2ca451",
        "handle_dropdown_enter": "7df61f96a2374b59",
        "handle_menu_backspace": "7dd171b8554bc6a4",
        "handle_menu_enter": "6bf88a0d7d915c5a",
        "set_input_ownership": "1c828c7be1ba3a8f",
        "toggle_menu": "7a8d5f39518d3d06"
    },
    "managed_input.py": {
        "discard_scoring_session": "fef03618beb61dc4",
        "generation_defaults": "3b4ea39fce0952b9",
        "release": "81e8d68bb5e4324d"
    }
}
ZONE_PINS = {
    "dd_page": "aafe4fea0f64988f",
    "dd_panel": "efbb18464ade415a",
    "help_page": "d1f782996452e99e",
    "page5": "d1f782996452e99e",
    "panel7": "36e70d7a7d7f60dc",
    "panel8": "b39425ce1700be17",
    "panel9": "4467c833ef6b6930"
}

if __name__ == "__main__":
    unittest.main()
