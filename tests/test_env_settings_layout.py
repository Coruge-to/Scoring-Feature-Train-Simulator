"""Stage ENV-1 (Owner contract 2026-11-08, commit 2; cursor structure refined 2026-11-09 after UIENV-C-01): the environment settings screen (menu_state 4) is a fixed list of 8 rows x 1 selectable column: only the VALUE
(ON / OFF) of a row can be selected, the label is display only; the row 'limit_advance' (制限速度予告) switches ONLY the red / blue blink warnings of the HUD speed-limit row.

Contract
  * rows (in this order): 現在時刻, 残り時間, 現在速度, 制限速度, 制限速度予告, 残距離, ハンドル・レバーサ位置, 勾配; selected_row = menu_cursor (0..7) is the ONLY selection state (no column state: menu_cursor_x is neither read nor written by the screen); entry = row 0.
  * the cursor encloses ONLY the value text (ON / OFF) and is the value cursor of the penalty page rows (padding 10, height font + 12, radius 6, HIGHLIGHT_COLOR): no label cursor, no whole-row cursor, no new design.
  * ON / OFF are left aligned: ON and OFF start at the X of the 'O' of the former right aligned OFF (1248); every row has the same value X.
  * the whole block (heading + 8 rows + the cursor ranges) is centred in the 1920 x 1080 menu screen: vertically on the box that includes the cursor ranges, horizontally on the TEXT box (heading, labels, the widest value 'OFF'; the cursor padding is not included);
    one offset for the heading, the texts, the cursors and the click zones; the order is: 8th row -> left aligned values -> text boxes -> centre -> offset.
  * keys: Left and Right do nothing at all; Up / Down move to the previous / next row and stop at the first / last row (no wrap); Enter toggles ON/OFF of the selected row and the row stays selected.
  * mouse: ONE click zone per row (from the label to the value); a click on the row that is already selected is the Enter, a click on any other row only selects it (the label click selects the row's VALUE; no double click timing, the decision is the equality with the selected row).
  * limit_advance (default ON, no persistence): OFF hides the red and the blue blink (the current limit stays), ON is the behaviour until now; nothing but the drawing entry of the HUD knows it (guidance state, scoring, F2, logs, telemetry unchanged).
  * dependency (set by ONE state function for keyboard, mouse and the normalisation): 制限速度 OFF => 制限速度予告 OFF; 制限速度予告 ON => 制限速度 ON; 制限速度 ON does not turn the advance ON; the advance OFF keeps the limit ON; the cursor never moves by itself; (limit OFF, advance ON) cannot exist.
The REAL menu_ui.draw_menu, hud_ui.draw_hud, scoring_logic guidance and the key / mouse handlers of main.py are driven (sia_rig Overlay). RED = fails on the baseline a202653 (commit 1); GUARD = passes there. RED messages start with 'ENV-RED'."""
import ast
import hashlib
import itertools
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

LABEL, VALUE = -1, 0
LEFTOVER = 7                         # a value of menu_cursor_x that no page uses: the screen must neither read nor write it
TITLE = "=== 環境設定 ==="
NAMES = ["現在時刻", "残り時間", "現在速度", "制限速度", "制限速度予告", "残距離", "ハンドル・レバーサ位置", "勾配"]
KEYS = ["time", "time_left", "speed", "limit", "limit_advance", "dist", "handle", "grad"]
SIZES = ((1920, 1080), (918, 627), (1280, 720))
HIGHLIGHT = (30, 80, 150, 200)
HINT = (50, 50, 50, 200)
GLOBAL_BOX_X_OFFSET = -3
_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-env-settings-")
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
        raise AssertionError("the environment settings module wrote into the redirected profile: %r" % (left,))


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def colour(c):
    return tuple(c) if isinstance(c, (tuple, list)) else (c.red(), c.green(), c.blue(), c.alpha())


class Env(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["env-settings"])
        import main
        import managed_input
        import scoring_logic
        cls.main, cls.MI, cls.S = main, managed_input, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0

    # ------------------------------------------------------------------ the screen
    def at(self, row, column=None, state=4):
        """state 4: the screen has no column; menu_cursor_x gets the LEFTOVER value (a page without a column must leave it alone). Other states (the penalty page of a guard) take the column."""
        o = self.o
        o.menu_state, o.menu_cursor = state, row
        o.menu_cursor_x = LEFTOVER if state == 4 else column
        o.show_help = False
        o.dropdown_active = False

    def render(self, width=1920, height=1080, state=None):
        """one frame of the REAL screen -> dict(texts, shapes): texts in menu coordinates (x, y baseline, align, font, colour); shapes = rounded rectangles / rectangles in menu coordinates"""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QImage, QPainter
        import menu_ui
        o = self.o
        if state is not None:
            o.menu_state = state
        texts, shapes = [], []

        class Spy(QPainter):
            def drawRoundedRect(self, *args):
                b = self.brush().color()
                shapes.append({"kind": "rr", "rect": tuple(float(v) for v in args[:4]), "radius": (float(args[4]), float(args[5])) if len(args) >= 6 else None, "brush": (b.red(), b.green(), b.blue(), b.alpha()), "pen": self.pen().style() != Qt.PenStyle.NoPen})
                return super().drawRoundedRect(*args)

            def drawRect(self, *args):
                b = self.brush().color()
                shapes.append({"kind": "r", "rect": tuple(float(v) for v in args[:4]) if len(args) >= 4 else None, "brush": (b.red(), b.green(), b.blue(), b.alpha()), "pen": self.pen().style() != Qt.PenStyle.NoPen})
                return super().drawRect(*args)

        original = menu_ui.draw_text_with_outline

        def record(painter, t, font, text_color, outline_color, x, y, align="left", passes=8):
            texts.append({"text": t, "font": font, "color": colour(text_color), "outline": colour(outline_color), "x": x, "y": y, "align": align})
            return original(painter, t, font, text_color, outline_color, x, y, align, passes)
        menu_ui.draw_text_with_outline = record
        o.width, o.height = (lambda: width), (lambda: height)
        o.menu_click_zones = []
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(200, 200, 200))
        painter = Spy(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            menu_ui.draw_menu(o, painter, width / (height / 1080.0))
        finally:
            painter.end()
            menu_ui.draw_text_with_outline = original
        return {"texts": texts, "shapes": shapes}

    def metrics(self):
        from PyQt6.QtGui import QFontMetrics
        return QFontMetrics(self.o.font_normal), QFontMetrics(self.o.font_big)

    def grid(self, frame):
        """-> (title, labels, values): the title text event, the 8 label events, the 8 value events (in drawing order)"""
        texts = frame["texts"]
        title = [t for t in texts if t["text"] == TITLE]
        labels = [t for t in texts if t["text"] in NAMES]
        values = [t for t in texts if t["text"] in ("ON", "OFF")]
        return (title[0] if title else None), labels, values

    def cursors(self, frame):
        return [s for s in frame["shapes"] if s["kind"] == "rr" and s["brush"] == HIGHLIGHT and not s["pen"]]

    def set_all(self, value):
        for k in KEYS:
            self.o.disp_settings[k] = value
        if not value:
            self.o.disp_settings["limit_advance"] = False

    def values(self):
        return tuple(self.o.disp_settings.get(k, True) for k in KEYS)

    # ------------------------------------------------------------------ the input
    def press(self, key):
        """the REAL _handle_keys with the key pressed (edge)"""
        o = self.o
        o.key_states[key] = False
        self.rig.kb.pressed = {key}
        try:
            o._handle_keys(True, False)
        finally:
            self.rig.kb.pressed = set()
            o.key_states[key] = False

    def click_at(self, x, y, width=1920, height=1080):
        """the REAL _handle_mouse with a left click at the window point (x, y)"""
        import main
        from PyQt6.QtCore import QRect
        o = self.o
        o.geometry = lambda: QRect(0, 0, width, height)
        o.last_left_click = False
        saved = (getattr(main.win32api, "GetAsyncKeyState", None), getattr(main.win32gui, "GetCursorPos", None))
        main.win32api.GetAsyncKeyState = lambda vk: 0x8000
        main.win32gui.GetCursorPos = lambda: (int(x), int(y))
        try:
            o._handle_mouse(True, False)
        finally:
            for obj, name, old in ((main.win32api, "GetAsyncKeyState", saved[0]), (main.win32gui, "GetCursorPos", saved[1])):
                if old is None:
                    try:
                        delattr(obj, name)
                    except AttributeError:
                        pass
                else:
                    setattr(obj, name, old)
            o.last_left_click = False

    def row_zones(self):
        return [z for z in self.o.menu_click_zones if len(z) == 5 and 0 <= z[4] < 8]

    def click_row(self, row, part="value"):
        """a click on the label text, on the value text or in the middle of the row zone of a row (the REAL _handle_mouse)"""
        frame = self.render()
        zones = [z for z in self.row_zones() if z[4] == row]
        self.assertEqual(len(zones), 1, "ENV1-RED: the screen has exactly one click zone for row %d, got %r" % (row, self.o.menu_click_zones))
        z = zones[0]
        title, labels, values = self.grid(frame)
        fm, _ = self.metrics()
        if part == "label":
            x = labels[row]["x"] + fm.horizontalAdvance(labels[row]["text"]) / 2.0
        elif part == "value":
            x = values[row]["x"] + fm.horizontalAdvance(values[row]["text"]) / 2.0
        else:
            x = (z[0] + z[2]) / 2.0
        self.assertTrue(z[0] <= x <= z[2], "the %s of row %d is inside the row zone" % (part, row))
        self.click_at(x, (z[1] + z[3]) / 2.0)

    def state(self):
        o = self.o
        return (o.menu_state, o.menu_cursor, o.menu_cursor_x, self.values())

    # ================================================================== the 8 x 2 grid and the layout
    def test_red_01_eight_rows_in_the_order_of_the_owner(self):
        o = self.o
        self.assertEqual(list(o.settings_keys), KEYS, "ENV-RED: the keys of the environment settings (the order is the order of the screen)")
        self.assertEqual(list(o.settings_names), NAMES, "ENV-RED: the names of the rows (制限速度予告 between 制限速度 and 残距離)")
        self.at(0, LABEL)
        title, labels, values = self.grid(self.render())
        self.assertEqual([t["text"] for t in labels], NAMES, "ENV-RED: eight labels, in this order, each one text (not shortened, not wrapped)")
        self.assertEqual(len(values), 8, "ENV-RED: eight values")
        ys = [t["y"] for t in labels]
        self.assertEqual(ys, sorted(ys), "the rows go down")
        self.assertEqual([t["y"] for t in values], ys, "every value is on the baseline of its label")

    def test_red_02_the_cursor_encloses_the_value_text_only(self):
        fm, _ = self.metrics()
        for row in range(8):
            for on in (True, False):
                for leftover in (LABEL, VALUE, 1, LEFTOVER):
                    self.at(row)
                    self.o.menu_cursor_x = leftover                       # (a leftover of another page: it must not change what is drawn)
                    self.set_all(on)
                    title, labels, values = self.grid(frame := self.render())
                    cur = self.cursors(frame)
                    where = "row %d, values %s, menu_cursor_x %s" % (row, "ON" if on else "OFF", leftover)
                    self.assertEqual(len(cur), 1, "ENV1-RED: %s: exactly one cursor (no label cursor, no whole-row cursor)" % where)
                    x, y, w, h = cur[0]["rect"]
                    cell = values[row]
                    cell_w = fm.horizontalAdvance(cell["text"])
                    self.assertEqual((x, y, w, h), (cell["x"] - 10 + GLOBAL_BOX_X_OFFSET, cell["y"] - fm.ascent() - 6 - 4, cell_w + 20, fm.height() + 12), "ENV1-RED: %s: the cursor encloses the ON / OFF text only (padding 10, the penalty page value cursor)" % where)
                    self.assertEqual(cur[0]["radius"], (6.0, 6.0), "ENV1-RED: %s: radius 6" % where)
                    label = labels[row]
                    self.assertTrue(x >= label["x"] + fm.horizontalAdvance(label["text"]), "ENV1-RED: %s: the cursor does not reach the label text" % where)
                    self.assertEqual(self.o.menu_cursor_x, leftover, "drawing never writes menu_cursor_x")

    def test_red_02b_the_width_follows_the_text_and_the_left_edge_is_the_common_value_x(self):
        fm, _ = self.metrics()
        lefts, widths = set(), {}
        for on in (True, False):
            self.at(4)
            self.set_all(on)
            frame = self.render()
            x, y, w, h = self.cursors(frame)[0]["rect"]
            lefts.add(x)
            widths["ON" if on else "OFF"] = w
        self.assertEqual(len(lefts), 1, "ENV1-RED: the cursor left edge is the common VALUE start X for ON and OFF")
        self.assertEqual(widths["OFF"] - widths["ON"], fm.horizontalAdvance("OFF") - fm.horizontalAdvance("ON"), "OFF may be wider than ON, by the text width only")

    def test_guard_03_the_cursor_geometry_is_the_one_of_the_penalty_page_rows(self):
        """measured on the REAL penalty page (menu_state 6, row 2 速度制限超過): label cursor -15 / +30 wide, value cursor -10 / +20, both fm.height()+12 high, radius 6, top = baseline - ascent - 6 - 4"""
        fm, _ = self.metrics()
        label = "速度制限超過"
        for column in (LABEL, VALUE):
            self.at(2, column, state=6)
            frame = self.render()
            label_ev = [t for t in frame["texts"] if t["text"] == label][0]
            ev = label_ev if column == LABEL else [t for t in frame["texts"] if t["text"] in ("ON", "OFF") and t["y"] == label_ev["y"]][0]
            cur = self.cursors(frame)
            self.assertEqual(len(cur), 1, "the penalty page draws one cursor")
            x, y, w, h = cur[0]["rect"]
            pad = 15 if column == LABEL else 10
            self.assertEqual((x - ev["x"], y - ev["y"], w - fm.horizontalAdvance(ev["text"]), h), (-pad + GLOBAL_BOX_X_OFFSET, -fm.ascent() - 6 - 4, 2 * pad, fm.height() + 12), "the penalty cursor relations (%s)" % ev["text"])
            self.assertEqual(cur[0]["radius"], (6.0, 6.0))

    def test_red_04_on_and_off_are_left_aligned_at_the_o_of_the_former_off(self):
        fm, _ = self.metrics()
        former_off_x = 1320 - fm.horizontalAdvance("OFF")
        for on in (True, False):
            self.at(0, LABEL)
            self.set_all(on)
            title, labels, values = self.grid(self.render())
            self.assertEqual({t["align"] for t in values}, {"left"}, "ENV-RED: left aligned values")
            self.assertEqual({t["x"] for t in values}, {values[0]["x"]}, "ENV-RED: every row of the 8, with the 制限速度予告 row, has the same value X (%s)" % ("ON" if on else "OFF"))
            self.assertEqual(values[0]["x"] - former_off_x, title["x"] - 960, "ENV-RED: the values start at the X of the 'O' of the former OFF (plus the offset of the block)")

    def test_red_05_label_column_and_column_gap_are_kept(self):
        self.at(0, LABEL)
        title, labels, values = self.grid(self.render())
        dx = title["x"] - 960
        self.assertEqual({t["x"] for t in labels}, {600 + dx}, "ENV-RED: every label at the label X (600 + offset)")
        self.assertEqual({t["align"] for t in labels}, {"left"})
        self.assertEqual(values[0]["x"] - labels[0]["x"], 648, "the distance of the two columns is kept (1248 - 600)")

    def test_red_06_fonts_colours_pitch_and_heading_gap_are_kept(self):
        o = self.o
        self.at(0, LABEL)
        title, labels, values = self.grid(self.render())
        self.assertIs(title["font"], o.font_big)
        self.assertTrue(all(t["font"] is o.font_normal for t in labels + values), "no font change of a row")
        ys = [t["y"] for t in labels]
        self.assertEqual([b - a for a, b in zip(ys, ys[1:])], [70] * 7, "ENV-RED: the line pitch is 70 for all 8 rows")
        self.assertEqual(ys[0] - title["y"], 100, "the heading to the first row is 100, as before")
        from config import COLOR_OUTLINE_BLACK, COLOR_WHITE
        self.assertEqual({(t["color"], t["outline"]) for t in labels}, {(colour(COLOR_WHITE), colour(COLOR_OUTLINE_BLACK))}, "label colours and outline are kept (white, black outline)")
        self.assertEqual({(t["text"], t["color"], t["outline"]) for t in values if t["text"] == "ON"}, {("ON", (0, 120, 220), (255, 255, 255))})

    def block(self, frame):
        """-> (text box (left, top, right, bottom) with the widest value, cursor box vertical range (top, bottom)) in menu coordinates of one frame (all values OFF)"""
        fm, fm_big = self.metrics()
        title, labels, values = self.grid(frame)
        tw = fm_big.horizontalAdvance(TITLE)
        left = min([title["x"] - tw / 2.0] + [t["x"] for t in labels])
        right = max([title["x"] + tw / 2.0] + [t["x"] + fm.horizontalAdvance(t["text"]) for t in labels] + [t["x"] + fm.horizontalAdvance("OFF") for t in values])
        zones = self.row_zones()
        top = min([title["y"] - fm_big.ascent()] + [z[1] for z in zones])
        bottom = max([title["y"] + fm_big.descent()] + [z[3] for z in zones])
        return (left, top, right, bottom)

    def test_red_07_the_block_is_centred_vertically_on_the_box_with_the_cursor_ranges_and_horizontally_on_the_text_box(self):
        for width, height in SIZES:
            for column in (LABEL, VALUE):
                self.at(7, column)
                self.set_all(False)
                left, top, right, bottom = self.block(self.render(width, height))
                self.assertLessEqual(abs((top + bottom) / 2.0 - 540.0), 0.5 + 1e-9, "ENV-RED: %dx%d: vertical centre of the block (cursor ranges included) = %.2f, must be 540" % (width, height, (top + bottom) / 2.0))
                self.assertLessEqual(abs((left + right) / 2.0 - 960.0), 0.5 + 1e-9, "ENV-RED: %dx%d: horizontal centre of the text box = %.2f, must be 960 (the cursor padding is not part of it)" % (width, height, (left + right) / 2.0))

    def test_red_08_the_numbers_of_the_centred_block(self):
        self.at(0, LABEL)
        title, labels, values = self.grid(self.render())
        self.assertEqual((title["x"], title["y"]), (960, 270), "ENV-RED: heading")
        self.assertEqual([t["y"] for t in labels], [370 + 70 * i for i in range(8)], "ENV-RED: the 8 baselines")
        self.assertEqual((labels[0]["x"], values[0]["x"]), (600, 1248), "ENV-RED: label X / value X")

    def test_red_09_the_block_does_not_move_with_the_values_or_the_cursor(self):
        self.at(0, LABEL)
        self.set_all(True)
        a = self.grid(self.render())
        self.set_all(False)
        self.at(7, VALUE)
        b = self.grid(self.render())
        key = lambda g: ([(t["x"], t["y"]) for t in [g[0]] + g[1]], [(t["x"], t["y"]) for t in g[2]])
        self.assertEqual(key(a), key(b), "ENV-RED: nothing moves when the values change (the block is centred with the widest value)")

    def test_red_10_one_offset_for_texts_cursors_and_zones_and_the_screen_has_room(self):
        fm, _ = self.metrics()
        self.at(7, VALUE)
        frame = self.render()
        title, labels, values = self.grid(frame)
        zones = self.row_zones()
        self.assertEqual(len(zones), 8, "ENV1-RED: ONE click zone per row")
        self.assertFalse([z for z in self.o.menu_click_zones if len(z) == 6], "ENV1-RED: no LABEL / VALUE cell zones (no column)")
        for row in range(8):
            z = [z for z in zones if z[4] == row][0]
            lw, vw = fm.horizontalAdvance(labels[row]["text"]), fm.horizontalAdvance(values[row]["text"])
            top = labels[row]["y"] - fm.ascent() - 6 - 4
            self.assertEqual((z[0], z[1], z[2], z[3]), (labels[row]["x"] - 15 + GLOBAL_BOX_X_OFFSET, top, values[row]["x"] - 10 + GLOBAL_BOX_X_OFFSET + vw + 20, top + fm.height() + 12), "ENV1-RED: row %d: the zone runs from the label cursor range to the value cursor range (same offset as the text)" % row)
        hint = [s for s in frame["shapes"] if s["kind"] == "rr" and s["brush"] == HINT]
        self.assertTrue(all(0 <= z[0] and z[2] <= 1920 and 0 <= z[1] and z[3] <= 1080 for z in zones), "inside the screen")
        self.assertLess(max(z[3] for z in zones), 1022, "the block does not reach the operation hint (it starts at 1022 in the menu screen)")

    def test_guard_11_the_layout_is_the_same_in_every_window_size(self):
        self.at(3, VALUE)
        ref = None
        for width, height in SIZES:
            frame = self.render(width, height)
            got = ([(t["text"], t["x"], t["y"]) for t in frame["texts"] if t["text"] in NAMES + ["ON", "OFF", TITLE]], self.row_zones())
            ref = ref or got
            self.assertEqual(got, ref, "%dx%d: menu coordinates do not depend on the window" % (width, height))

    # ================================================================== keys
    def enter_screen(self):
        o = self.o
        o.menu_state = 1
        items = list(getattr(o, "current_menu_items", None) or getattr(o, "menu_items_off", []))
        o.current_menu_items = items
        o.menu_cursor = [i for i, t in enumerate(items) if "環境設定" in t][0]
        o.handle_menu_enter(False)

    def test_red_20_entering_the_screen_selects_the_first_row_value_and_touches_no_column(self):
        self.o.menu_cursor_x = LEFTOVER                                  # (a leftover of another page)
        self.enter_screen()
        self.assertEqual((self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x), (4, 0, LEFTOVER), "ENV1-RED: entry = row 0; menu_cursor_x is not written (no LABEL state is created)")
        frame = self.render()
        title, labels, values = self.grid(frame)
        cur = self.cursors(frame)
        self.assertEqual(len(cur), 1, "ENV1-RED: right after opening the screen the cursor is on the ON / OFF of the first row")
        self.assertTrue(abs(cur[0]["rect"][1] - (values[0]["y"] - self.metrics()[0].ascent() - 10)) < 1e-9)

    def test_red_21_left_and_right_do_nothing(self):
        for row in range(8):
            self.at(row)
            before = self.state()
            for key in ("right", "right", "left", "left", "right", "left"):
                self.press(key)
                self.assertEqual(self.state(), before, "ENV1-RED: %s on row %d changes nothing (no row, no value, no screen, no hidden column)" % (key, row))
            self.assertEqual(len(self.cursors(self.render())), 1, "still one cursor, on the value of the row")

    def test_red_22_up_and_down_move_row_by_row(self):
        self.at(0)
        for row in range(1, 8):
            self.press("down")
            self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x), (row, LEFTOVER), "ENV1-RED: Down -> the VALUE of row %d" % row)
        for row in range(6, -1, -1):
            self.press("up")
            self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x), (row, LEFTOVER), "ENV1-RED: Up -> the VALUE of row %d" % row)

    def test_red_23_the_owner_example_sequence(self):
        self.at(0)
        seq = [("down", 1), ("down", 2), ("down", 3), ("down", 4), ("right", 4), ("left", 4), ("up", 3), ("down", 4)]
        for key, want in seq:
            self.press(key)
            self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x), (want, LEFTOVER), "ENV1-RED: after %s" % key)

    def test_guard_24_the_ends_stop(self):
        self.at(0)
        self.press("up")
        self.assertEqual(self.o.menu_cursor, 0, "the first row stays (no wrap)")
        self.at(7)
        self.press("down")
        self.assertEqual(self.o.menu_cursor, 7, "ENV1-RED: the last row (7) stays (no wrap)")

    def test_red_25_enter_toggles_the_selected_row_and_the_row_stays(self):
        for row in range(8):
            for first in (True, False):
                self.at(row)
                self.set_all(True)
                self.o.disp_settings[KEYS[row]] = first
                if KEYS[row] == "limit_advance" and not first:
                    self.o.disp_settings["limit_advance"] = False
                self.press("enter")
                want = (not first) if KEYS[row] != "limit_advance" or first else True
                self.assertEqual(self.o.disp_settings[KEYS[row]], want, "ENV1-RED: Enter on row %d switches its ON / OFF" % row)
                self.assertEqual((self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x), (4, row, LEFTOVER), "ENV1-RED: Enter keeps the row (and creates no column state)")
        for row in (0, 1, 2, 5, 6, 7):
            self.at(row)
            self.set_all(True)
            self.press("enter")
            self.assertEqual([self.o.disp_settings[k] for k in KEYS if k != KEYS[row]], [True] * 7, "no other row changed (row %d)" % row)

    def test_red_26_a_leftover_column_of_another_page_decides_nothing(self):
        for leftover in (LABEL, VALUE, 1, LEFTOVER):
            for row in (0, 2, 5, 7):
                self.at(row)
                self.o.menu_cursor_x = leftover
                before = self.values()
                self.press("enter")
                self.assertNotEqual(self.values(), before, "ENV1-RED: Enter toggles the row whatever menu_cursor_x was (leftover %s, row %d): no hidden LABEL state" % (leftover, row))
                self.assertEqual(self.o.menu_cursor_x, leftover)
                self.press("enter")
                self.assertEqual(self.values(), before)

    # ================================================================== mouse
    def test_red_30_a_click_selects_a_row_the_click_on_the_selected_row_is_the_enter(self):
        self.at(0)
        before = self.values()
        self.click_row(2, "label")
        self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x, self.values()), (2, LEFTOVER, before), "ENV1-RED: the first click (on the LABEL text of another row) only selects its VALUE: no value change, no column state")
        self.assertEqual(len(self.cursors(self.render())), 1, "the cursor is on the VALUE of row 2 only")
        self.click_row(2, "label")
        self.assertEqual(self.o.menu_cursor, 2)
        self.assertEqual(self.o.disp_settings["speed"], False, "ENV1-RED: a click on the already selected row (even on its label) is the Enter")
        self.click_row(2, "value")
        self.assertEqual(self.o.disp_settings["speed"], True, "the click on the selected VALUE toggles again")
        self.click_row(5, "value")
        self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x, self.o.disp_settings["dist"], self.o.disp_settings["speed"]), (5, LEFTOVER, True, True), "ENV1-RED: a click on the VALUE of another row only moves")
        self.click_row(5, "value")
        self.assertEqual(self.o.disp_settings["dist"], False)
        self.assertEqual(self.o.menu_cursor_x, LEFTOVER, "the mouse writes no column")

    def test_red_31_the_label_click_selects_the_value_of_the_row_never_a_label(self):
        for row in range(8):
            self.at((row + 3) % 8)
            before = self.values()
            self.click_row(row, "label")
            self.assertEqual(self.o.menu_cursor, row, "ENV1-RED: the label click selects the row %d" % row)
            self.assertEqual(self.values(), before)
            cur = self.cursors(self.render())
            self.assertEqual(len(cur), 1)
            title, labels, values = self.grid(self.render())
            fm, _ = self.metrics()
            self.assertGreaterEqual(cur[0]["rect"][0], labels[row]["x"] + fm.horizontalAdvance(labels[row]["text"]), "the cursor is on the value, not on the label")

    def test_red_32_the_decision_is_the_selected_row_not_the_click_timing(self):
        import time
        real = time.time
        for gap in (0.0, 0.05, 0.4, 5.0, 3600.0):
            clock = [1000.0]
            time.time = lambda: clock[0]
            try:
                self.at(1)
                before = self.values()
                self.click_row(6, "value")
                clock[0] += gap
                self.assertEqual(self.values(), before, "gap %s: a click on an unselected row never changes a value" % gap)
                self.click_row(6, "value")
                clock[0] += gap
                self.assertEqual(self.o.disp_settings["handle"], False, "ENV1-RED: gap %s: the click on the selected row toggles whatever the time between the clicks was" % gap)
                self.click_row(6, "value")
                self.assertEqual(self.o.disp_settings["handle"], True)
            finally:
                time.time = real

    def test_red_33_one_state_for_keyboard_and_mouse(self):
        self.at(0)
        self.press("down")
        self.press("down")
        self.assertEqual(self.o.menu_cursor, 2)
        self.click_row(2, "value")                                        # (the keyboard selected row 2: this click is the Enter)
        self.assertEqual(self.o.disp_settings["speed"], False, "ENV1-RED: the keyboard and the mouse share one selected row")
        self.click_row(4, "label")
        self.press("down")
        self.assertEqual(self.o.menu_cursor, 5, "the key continues from the row the mouse selected")

    def test_guard_34_no_hidden_label_state_in_the_code_of_the_screen(self):
        import re
        ui = source("menu_ui.py")
        start = ui.index("    elif self.menu_state == 4:\n        # Stage ENV-1 (8 rows x 1 column")
        body = ui[start:ui.index("    elif self.menu_state in [5, 7]:", start)]
        self.assertNotIn("menu_cursor_x", body, "ENV1-RED: the drawing of the screen reads no column")
        self.assertNotIn("sel_col", body)
        self.assertEqual(body.count("drawRoundedRect"), 1, "ENV1-RED: ONE cursor shape (the value cursor)")
        main_src = source("main.py")
        e0 = main_src.index("        elif self.menu_state == 4:\n            # Stage ENV-1: Enter switches")
        enter = main_src[e0:main_src.index("        elif self.menu_state == 5:\n            if self.menu_cursor == 0 and getattr(self, 'menu_cursor_x', 0) >= 0:", e0)]
        self.assertNotIn("menu_cursor_x", enter, "ENV1-RED: Enter reads no column")
        n0 = main_src.index('            elif "環境設定" in selected:')
        entry = main_src[n0:main_src.index("        elif self.menu_state == 2:\n            if len(getattr(self, 'save_data', [])) > 0:", n0)]
        self.assertNotIn("menu_cursor_x", entry, "ENV1-RED: entering the screen creates no column state")

    # ================================================================== limit_advance in the HUD
    def guidance(self, kind, advance=True, limit=True):
        o = self.o
        o.disp_settings["limit"] = limit
        o.disp_settings["limit_advance"] = advance
        o.is_scoring_mode = False
        o.station_list = [R.station("A", 0.0), R.station("B", 5000.0, terminal=True)]
        o.bve_location, o.bve_speed = 1000.0, 60.0
        if kind in ("red", "red_far"):
            o.map_tail_limit = o.map_head_limit = o.bve_signal_limit = 120.0
            o.bve_map_limits = [(1600.0 if kind == "red_far" else 1400.0, 40.0)]
            o.bve_clear_dist = 0.0
        else:
            o.bve_speed = 30.0
            o.map_tail_limit, o.map_head_limit, o.bve_signal_limit = 40.0, 120.0, 120.0
            o.bve_map_limits = []
            o.bve_clear_dist = 60.0
        o.bve_fwd_sig_limit = 1000.0
        o.bve_train_length, o.bve_time_ms = 100.0, 36000000
        self.ticks(3)
        return o

    def ticks(self, n):
        for _ in range(n):
            self.t += 0.016
            self.S.update_physics_and_scoring(self.o, self.t, 0.016)

    def hud_limit_texts(self, phase):
        import hud_ui
        from PyQt6.QtGui import QImage, QPainter
        import re
        o = self.o
        o.blink_phase = phase
        out = []
        original = hud_ui.draw_text_with_stroke

        def spy(painter, text, font, text_color, outline, *a, **k):
            out.append((str(text), colour(text_color)))
            return original(painter, text, font, text_color, outline, *a, **k)
        hud_ui.draw_text_with_stroke = spy
        try:
            image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            try:
                hud_ui.draw_hud(o, painter, 1920)
            finally:
                painter.end()
        finally:
            hud_ui.draw_text_with_stroke = original
        return [t for t in out if re.match(r"^(\d+|---) km/h$", t[0])]

    def test_red_40_the_default_is_on_and_the_baseline_blink_numbers(self):
        self.assertIn("limit_advance", self.o.disp_settings, "ENV-RED: the key limit_advance exists in disp_settings")
        self.assertTrue(self.o.disp_settings["limit_advance"] is True, "ENV-RED: initial value ON")
        o = self.guidance("red")
        self.assertAlmostEqual(o.blink_phase, 0.03443946188340807, places=12, msg="red: period unchanged")
        self.assertEqual((o.blink_active, o.disp_limit, o.limit_color), (True, 40.0, (200, 20, 20)))

    def test_red_41_on_shows_the_red_and_the_blue_blink(self):
        o = self.guidance("red")
        self.assertEqual(self.hud_limit_texts(0.2), [("40 km/h", (200, 20, 20))], "red blink: the warning value in red (first half)")
        self.assertEqual(self.hud_limit_texts(0.7), [("120 km/h", (255, 255, 255))], "second half: the current limit")
        self.fresh()
        o = self.guidance("blue")
        self.assertEqual(self.hud_limit_texts(0.2), [("120 km/h", (0, 120, 220))], "blue blink")
        self.assertEqual(self.hud_limit_texts(0.7), [("40 km/h", (255, 255, 255))])

    def fresh(self):
        self.rig.close()
        self.setUp()

    def test_red_42_off_shows_the_current_limit_only_never_a_blink(self):
        self.guidance("red", advance=False)
        self.assertTrue(self.o.blink_active, "the guidance itself still runs")
        for phase in (0.2, 0.7):
            self.assertEqual(self.hud_limit_texts(phase), [("120 km/h", (255, 255, 255))], "ENV-RED: red blink hidden, the current limit (white) is shown, phase %s" % phase)
        self.fresh()
        self.guidance("blue", advance=False)
        for phase in (0.2, 0.7):
            self.assertEqual(self.hud_limit_texts(phase), [("40 km/h", (255, 255, 255))], "ENV-RED: blue blink hidden, the current limit is shown, phase %s" % phase)

    def test_red_43_off_and_on_again_brings_the_blink_back_at_once(self):
        self.guidance("red", advance=True)
        self.o.disp_settings["limit_advance"] = False
        self.assertEqual(self.hud_limit_texts(0.2), [("120 km/h", (255, 255, 255))], "ENV-RED: OFF")
        self.o.disp_settings["limit_advance"] = True
        self.assertEqual(self.hud_limit_texts(0.2), [("40 km/h", (200, 20, 20))], "ON again: the blink is back")

    def test_red_44_the_limit_off_hides_the_whole_row_as_before(self):
        self.guidance("red", advance=False, limit=False)
        self.assertEqual(self.hud_limit_texts(0.2), [], "the row of the limit is not drawn when 制限速度 is OFF")

    def snapshot(self):
        o = self.o
        keys = ("blink_active", "blink_phase", "disp_limit", "limit_color", "effective_limit", "target_type", "base_limit_type", "dbg_red", "dbg_blue", "dbg_target_cap", "dbg_active_reds", "score", "current_flashing_key", "strictest_flashed_val")
        snap = {k: getattr(o, k, None) for k in keys}
        snap["flash"] = dict(getattr(o, "limit_flash_counts", {}))
        snap["details"] = dict(o.score_details)
        snap["popups"] = [dict(p) for p in o.popups]
        return snap

    def test_guard_45_the_setting_changes_no_internal_value_no_score_and_no_period(self):
        runs = {}
        for advance in (True, False):
            self.fresh()
            self.guidance("red", advance=advance)
            seen = []
            for i in range(240):                                          # 3.8 s: several blink cycles
                self.ticks(1)
                if i % 20 == 0:
                    seen.append(self.snapshot())
            runs[advance] = seen
        self.assertEqual(runs[True], runs[False], "ENV-RED: the guidance state, the blink phase / period, the flash counters, F2 values and the score do not depend on 制限速度予告")
        self.assertTrue(any(s["blink_active"] for s in runs[False]))

    def test_guard_49_the_blink_period_far_from_the_limit_is_one_and_a_half_seconds(self):
        o = self.guidance("red_far")
        self.assertTrue(o.blink_active)
        self.assertAlmostEqual(o.blink_phase, 3 * 0.016 / 1.5, places=12, msg="a red warning outside the braking distance blinks with a 1.5 s period (unchanged)")
        o = self.guidance("red")
        self.assertAlmostEqual(o.blink_phase, 0.03443946188340807 + 0.032, places=9, msg="inside the braking distance the period shortens (unchanged); 3 more ticks")

    def test_guard_65_the_layout_function_applies_one_offset_to_every_element(self):
        """a stub of the font metrics with a wide label: the block centre is far from the screen centre, so a missing offset on the heading, the labels, the values or the baselines shows"""
        import math
        import menu_ui

        class Metrics(object):
            def __init__(self, unit, ascent, descent):
                self.unit, self._a, self._d = unit, ascent, descent

            def horizontalAdvance(self, text):
                return len(text) * self.unit

            def ascent(self):
                return self._a

            def descent(self):
                return self._d

            def height(self):
                return self._a + self._d
        fm, big = Metrics(20, 41, 13), Metrics(40, 64, 20)
        labels = ["x" * 5] * 7 + ["y" * 100]
        got = menu_ui.env_settings_layout(fm, big, labels, 960.0, 540.0, -4)
        title_w = len(menu_ui.ENV_TITLE) * 40
        value_x = 1320 - 3 * 20
        left = min(600, 960 - title_w / 2.0)
        right = max(960 + title_w / 2.0, 1320, 600 + 100 * 20)
        top = min(200 - 64, 300 - 41 - 6 - 4)
        bottom = max(200 + 20, 300 + 70 * 7 - 41 - 6 - 4 + 54 + 12)
        dx = int(math.floor(960 - (left + right) / 2.0 + 0.5))
        dy = int(math.floor(540 - (top + bottom) / 2.0 + 0.5))
        self.assertNotEqual(dx, 0)
        self.assertNotEqual(dy, 0)
        self.assertEqual((got["dx"], got["dy"]), (dx, dy))
        self.assertEqual(got["title_x"], 960 + dx, "ENV-RED: the heading carries the horizontal offset")
        self.assertEqual(got["title_y"], 200 + dy, "the heading carries the vertical offset")
        self.assertEqual(got["label_x"], 600 + dx, "the labels carry the horizontal offset")
        self.assertEqual(got["value_x"], value_x + dx, "the values carry the horizontal offset")
        self.assertEqual(got["ys"], [300 + 70 * i + dy for i in range(8)], "every baseline carries the vertical offset")

    def test_guard_46_a_missing_key_means_on(self):
        self.guidance("red")
        del self.o.disp_settings["limit_advance"]
        self.assertEqual(self.hud_limit_texts(0.2), [("40 km/h", (200, 20, 20))], "an old state without the key shows the blink (default ON)")

    def test_guard_47_current_and_legacy_senders_get_the_same_blink_contract(self):
        import types
        import telemetry_contract as tc
        import test_telemetry_l3 as L3
        for label, tokens in (("Current (every token)", frozenset(tc.KNOWN_TOKENS)), ("Legacy", frozenset(L3.LEGACY_TOKENS))):
            for kind, shown in (("red", ("40 km/h", (200, 20, 20))), ("blue", ("120 km/h", (0, 120, 220)))):
                for advance, want in ((True, [shown]), (False, [("120 km/h" if kind == "red" else "40 km/h", (255, 255, 255))])):
                    self.fresh()
                    self.guidance(kind, advance=advance)
                    self.o.telemetry_gate = types.SimpleNamespace(availability=tc.Availability(tokens))
                    self.assertEqual(self.hud_limit_texts(0.2), want, "%s sender, %s blink, advance %s: the same Python display" % (label, kind, "ON" if advance else "OFF"))

    def test_guard_48_the_scoring_of_the_speed_limit_does_not_depend_on_the_advance(self):
        runs = {}
        for advance in (True, False):
            self.fresh()
            o = self.o
            o.disp_settings["limit_advance"] = advance
            o.is_scoring_mode, o.is_scoring_finished, o.is_official_jumping, o.is_first_udp, o.pen_limit = True, False, False, False, True
            o.effective_limit, o.bve_speed = 60.0, 80.0
            for k in range(5):
                self.S.update_speed_limit_penalty(o, 100.0 + k * 1.1)
            runs[advance] = (o.score, dict(o.score_details), [dict(p) for p in o.popups], getattr(o, "accumulated_speed_penalty", None))
        self.assertLess(runs[True][0], 0, "the over-speed is penalised (the comparison is not empty)")
        self.assertEqual(runs[True], runs[False], "the over-speed judgement, score, breakdown and popups do not depend on 制限速度予告")

    # ================================================================== the dependency
    def pair(self):
        return (self.o.disp_settings["limit"], self.o.disp_settings["limit_advance"])

    def test_red_50_dependency_by_keyboard_and_mouse(self):
        cases = [
            (3, (True, True), (False, False)),            # limit OFF turns the advance OFF
            (3, (True, False), (False, False)),
            (3, (False, False), (True, False)),            # limit ON does not turn the advance ON
            (4, (False, False), (True, True)),             # advance ON turns the limit ON
            (4, (True, False), (True, True)),
            (4, (True, True), (True, False)),              # advance OFF keeps the limit ON
        ]
        for mode in ("key", "mouse"):
            for row, start, want in cases:
                self.o.disp_settings["limit"], self.o.disp_settings["limit_advance"] = start
                self.at(row, VALUE)
                if mode == "key":
                    self.press("enter")
                else:
                    self.click_row(row, "value")                       # (the row is selected: this click is the Enter)
                where = "%s, row %d, %s" % (mode, row, start)
                self.assertEqual(self.pair(), want, "ENV-RED: %s -> %s" % (where, want))
                self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x), (row, LEFTOVER), "ENV1-RED: %s: the cursor stays on the row" % where)

    def test_red_51_the_forbidden_state_cannot_be_reached_by_any_sequence(self):
        for mode in ("key", "mouse"):
            for start in itertools.product((True, False), repeat=2):
                if start == (False, True):
                    continue
                for seq in itertools.product((3, 4), repeat=5):
                    self.o.disp_settings["limit"], self.o.disp_settings["limit_advance"] = start
                    for row in seq:
                        self.at(row, VALUE)
                        if mode == "key":
                            self.press("enter")
                        else:
                            self.click_row(row, "value")
                        self.assertNotEqual(self.pair(), (False, True), "ENV-RED: %s: (limit OFF, advance ON) after row %d from %s via %r" % (mode, row, start, seq))
                if mode == "mouse":
                    break

    def test_red_52_one_function_for_keyboard_mouse_and_the_normalisation(self):
        o = self.o
        for name in ("set_speed_limit_visible", "set_speed_limit_advance_visible", "normalize_speed_limit_settings"):
            self.assertTrue(callable(getattr(o, name, None)), "ENV-RED: Overlay.%s exists" % name)
        o.set_speed_limit_visible(False)
        self.assertEqual(self.pair(), (False, False))
        o.set_speed_limit_visible(True)
        self.assertEqual(self.pair(), (True, False), "the limit ON does not bring the advance back")
        o.set_speed_limit_advance_visible(True)
        self.assertEqual(self.pair(), (True, True))
        o.set_speed_limit_advance_visible(False)
        self.assertEqual(self.pair(), (True, False))
        o.set_speed_limit_visible(False)
        o.set_speed_limit_advance_visible(True)
        self.assertEqual(self.pair(), (True, True), "the advance ON turns the limit ON")
        source_main = source("main.py")
        tree = ast.parse(source_main)
        users = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and any(isinstance(c, ast.Attribute) and c.attr in ("set_speed_limit_visible", "set_speed_limit_advance_visible", "set_disp_setting", "toggle_disp_setting") for c in ast.walk(n))}
        self.assertIn("handle_menu_enter", users, "the Enter (keyboard and the mouse, which calls it) goes through the state functions")

    def test_red_53_an_invalid_state_is_normalised_in_the_state_not_in_the_hud(self):
        o = self.o
        o.disp_settings["limit"], o.disp_settings["limit_advance"] = False, True
        o.normalize_speed_limit_settings()
        self.assertEqual(self.pair(), (False, False), "ENV-RED: (OFF, ON) -> (OFF, OFF) in the stored state")
        o.disp_settings["limit"], o.disp_settings["limit_advance"] = False, True
        self.enter_screen()
        self.assertEqual(self.pair(), (False, False), "ENV-RED: opening the screen normalises the stored state too")
        hud = source("hud_ui.py")
        self.assertNotIn("normalize_speed_limit_settings", hud, "the HUD does not repair the state")

    # ================================================================== the rest stays
    def test_guard_60_no_persistence_and_the_state_survives_a_generation(self):
        o = self.o
        o.disp_settings["limit_advance"] = False
        self.MI.discard_generation_state(o)
        self.assertFalse(o.disp_settings.get("limit_advance", True), "F5 / scenario reload keep the environment settings")
        self.assertIn("disp_settings", self.MI.KEPT_ACROSS_GENERATIONS)
        self.fresh()
        self.assertTrue(self.o.disp_settings.get("limit_advance", True), "ENV-RED: a new Overlay (restart) starts with 制限速度予告 ON; nothing is stored")
        self.assertEqual(self.values(), (True,) * 8)

    def test_red_61_only_the_hud_entry_and_the_settings_know_the_advance(self):
        for name in ("scoring_logic.py", "network.py", "managed_input.py", "utils.py", "config.py", "score_calc.py", "popups.py"):
            path = os.path.join(ROOT, name)
            if os.path.exists(path):
                self.assertNotIn("limit_advance", source(name), "%s does not know the advance setting (guidance, scoring, telemetry, logs are independent of it)" % name)
        import telemetry_contract as tc
        self.assertEqual(source("telemetry_contract.py").count("limit_advance"), 1, "ENV-RED: the contract knows the switch in exactly one place: its availability entry")
        self.assertEqual(tc.HUD_ITEM_REQUIRES["limit_advance"], tc.HUD_ITEM_REQUIRES["limit"], "ENV-RED: the advance needs the same limit data as the limit row (no new token, no wire change)")
        hud = source("hud_ui.py")
        head = hud[:hud.index("def draw_hud")]
        self.assertNotIn("limit_advance", head)
        f2 = hud[hud.index("dbg_texts = []"):hud.index("painter.drawText(20, dbg_y, text)")]
        self.assertNotIn("limit_advance", f2, "F2 is unchanged")
        self.assertEqual(hud.count("limit_advance"), 1, "ENV-RED: exactly one entry in the HUD: the blink drawing")
        self.assertIn('if self.blink_active and hud_item_visible(self, "limit_advance"):', hud, "ENV-RED: the blink branch is entered only when the advance is shown (no transparent colour)")

    def test_guard_62_input_ownership_and_cursor_q3_functions_are_unchanged(self):
        """the functions of main.py around the input ownership, Alt+F4, the Input Device switch and the Cursor-Q3 arrow are the ones of commit 1 (their AST hashes). ON PURPOSE (8 x 1 cursor, 2026-11-09): only _handle_mouse differs - its menu_state 4 branch (the selected row decides, no column); every other function is the one of 12998d3"""
        pinned = {"_handle_keys": "2fdff247b333c919", "_handle_mouse": "94ae4a8abbd9d38d", "_sync_operation_cursor": "b50358a62b2ca451", "handle_dropdown_enter": "7df61f96a2374b59",
                  "handle_menu_backspace": "7dd171b8554bc6a4", "set_input_ownership": "1c828c7be1ba3a8f", "toggle_menu": "7a8d5f39518d3d06"}
        tree = ast.parse(source("main.py"))
        got = {n.name: hashlib.sha256(ast.dump(n).encode("utf-8")).hexdigest()[:16] for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in pinned}
        self.assertEqual(got, pinned)

    def test_guard_63_the_other_hud_rows_and_the_other_screens_are_unchanged(self):
        hud = source("hud_ui.py")
        for needle in ('hud_item_visible(self, "time")', 'hud_item_visible(self, "time_left")', 'hud_item_visible(self, "speed")', 'hud_item_visible(self, "limit")', 'hud_item_visible(self, "dist")', 'hud_item_visible(self, "handle")', 'hud_item_visible(self, "grad")'):
            self.assertEqual(hud.count(needle), 1, needle)
        self.assertEqual([k for k in KEYS if k != "limit_advance"], ["time", "time_left", "speed", "limit", "dist", "handle", "grad"])
        self.assertEqual([k for k in self.o.settings_keys if k != "limit_advance"], ["time", "time_left", "speed", "limit", "dist", "handle", "grad"], "the seven settings keep their keys and order")

    def test_red_64_the_screen_is_one_python_implementation_for_current_and_legacy(self):
        tree = ast.parse(source("menu_ui.py"))
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "env_settings_layout"]
        self.assertEqual(len(fn), 1, "ENV-RED: the pure layout function env_settings_layout exists")
        words = set()
        for n in ast.walk(fn[0]):
            if isinstance(n, ast.Name):
                words.add(n.id.lower())
            elif isinstance(n, ast.Attribute):
                words.add(n.attr.lower())
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                words.add(n.value.lower())
        self.assertFalse({"legacy", "current", "dll", "caller"} & words, "the layout knows no DLL kind")


if __name__ == "__main__":
    unittest.main()
