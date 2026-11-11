"""INITIAL-DEFAULTS Stage F1 (additional Owner contract 2026-11-11): the user-visible name 保安装置介入 and its OFF-fixed state in F1. RED-only: the product code is not changed.

  name        F1 shows 保安装置介入 (list row, row help, result screen); the old name ATS信号無視 is shown nowhere (F1 drawing, the 初期値設定 window, the user-readable Desktop log); the window and F1 use the SAME name
  state       F1: OFF fixed and not operable (Enter, Left / Right, click zone, Space is not a F1 key); scenario_settings and running_snapshot always False; the presets never turn it on; saved_defaults never hold True
  scope       internal identifiers (pen_ats, ATS_SIGNAL_IGNORE_AVAILABLE, the category key 'ATS信号無視', the score_details key 'ats', JSON key safety_intervention, protocol ids) are NOT renamed in the beta

AUDIT FINDING (reported): at HEAD 467be52 the F1 drawing already shows 保安装置介入 (INITIAL-DEFAULTS Commit 4). Most of this contract therefore already holds and is pinned as GUARD; the only user-visible leftover of the old name
is the Desktop-log line of the scoring breakdown (scoring_logic.py), which is the PRODUCT-RED of this file. The detector itself is proven by the self-tests at the end (an injected old name MUST be detected)."""
import os
import re
import sys
import json
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import idf1_red_support as X  # noqa: E402
import sia_rig as R  # noqa: E402

OLD, NEW = X.OLD_SAFETY_NAME, X.SAFETY_NAME


def setUpModule():
    X.redirect_profile("ts-idf1-safety-")


def tearDownModule():
    X.restore_profile()


SHOWING_CALLS = ("draw_", "setText(", "QLabel(", "write_desktop_log(", "add_score_popup(", "PENALTY_LABELS", "desc_dict")


def old_name_hits(strings):
    """The detector: every drawn / shown string that contains the old name."""
    return [s for s in strings if OLD in s]


def assert_no_old_name(case, strings, where):
    hits = old_name_hits(strings)
    case.assertEqual(hits, [], "IDF1-GUARD: %s shows the old name: %r" % (where, hits))


def user_visible_literals(source_text):
    """The string literals of the lines that SHOW text to the user (draw_* / setText / QLabel / write_desktop_log / add_score_popup calls, the label and help tables). Comments are not user-visible and are cut first.
    (A coarse source scan: the dynamic F1 rendering tests above are the precise check of what is drawn.)"""
    found = []
    for line in source_text.splitlines():
        code = line.split("#", 1)[0]
        if any(call in code for call in SHOWING_CALLS):
            found.extend(re.findall(r'f?"([^"\n]*)"', code))
    return found


class Name(X.LinkBase):
    PAGES = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12)

    def setUp(self):
        super().setUp()
        o = self.o
        o.width, o.height = (lambda: 1920), (lambda: 1080)
        o.show_help = False
        o.dropdown_active = False
        o.station_list = [R.station("Stn%02d" % i, 500.0 * i, terminal=(i == 11)) for i in range(12)]
        o.setting_start_idx, o.setting_end_idx = 0, 11
        o.theoretical_score = 10000
        self.scenario(5)

    def all_drawn(self, help_on=False):
        out = {}
        for page in self.PAGES:
            try:
                texts, _ = X.render_f1(self.o, page, menu_cursor=0, menu_cursor_x=-1, show_help=help_on)
            except Exception as exc:                                       # a page that needs more state than the rig gives is skipped, never guessed
                out[page] = None
                continue
            out[page] = X.drawn(texts)
        self.o.show_help = False
        return out

    # ---- 1 / 2: the F1 drawing
    def test_01_f1_shows_the_new_name_on_the_deduction_page(self):
        drawn = X.drawn(X.render_f1(self.o, 6, menu_cursor=1, menu_cursor_x=-1)[0])
        self.assertIn(NEW, drawn, "IDF1-GUARD: F1 page 2/3 does not show 保安装置介入")

    def test_01_f1_shows_the_new_name_in_the_row_help(self):
        drawn = X.drawn(X.render_f1(self.o, 6, menu_cursor=1, menu_cursor_x=-1)[0])
        self.assertTrue(any(NEW in s for s in drawn if s != NEW), "IDF1-GUARD: the row help does not use 保安装置介入")

    def test_01_f1_shows_the_new_name_on_the_result_screen(self):
        self.assertIn(NEW, X.drawn(X.render_f1(self.o, 11, menu_cursor=0)[0]), "IDF1-GUARD: the result screen does not show 保安装置介入")

    def test_02_the_old_name_is_drawn_on_no_f1_page(self):
        pages = self.all_drawn()
        for must in (6, 10, 11):
            self.assertIsNotNone(pages.get(must), "IDF1-HARNESS: F1 page %s could not be rendered" % must)
        for page, strings in pages.items():
            if strings is not None:
                assert_no_old_name(self, strings, "F1 page %s" % page)

    def test_02_the_old_name_is_drawn_on_no_f1_help_overlay(self):
        pages = self.all_drawn(help_on=True)
        for must in (6, 11):
            self.assertIsNotNone(pages.get(must), "IDF1-HARNESS: the help overlay of F1 page %s could not be rendered" % must)
        for page, strings in pages.items():
            if strings is not None:
                assert_no_old_name(self, strings, "the help overlay of F1 page %s" % page)

    def test_02_the_old_name_is_in_no_user_visible_literal_of_the_ui_modules(self):
        for name in ("menu_ui.py", "hud_ui.py", "initial_defaults_ui.py", "managed_hud.py", "main.py", "config.py"):
            hits = old_name_hits(user_visible_literals(X.source(name)))
            self.assertEqual(hits, [], "IDF1-GUARD: %s shows the old name in a user-visible literal: %r" % (name, hits))

    def test_02_the_old_name_is_not_in_the_user_readable_desktop_log(self):
        """The scoring breakdown the Desktop log prints (a user-readable file) still says ATS信号無視 (the label of the 'ats' score row)."""
        hits = old_name_hits(user_visible_literals(X.source("scoring_logic.py")))
        self.assertEqual(hits, [], "IDF1-RED: the user-readable Desktop log still shows the old name: %r (the internal category key is not a log text and is not part of this check)" % hits)

    def test_02_the_desktop_log_row_uses_the_new_name_and_the_internal_key(self):
        """The breakdown row of the safety intervention exists, says 保安装置介入 and still reads the internal score key 'ats' (the key is not renamed in the beta)."""
        rows = [s for s in user_visible_literals(X.source("scoring_logic.py")) if s.strip().startswith(NEW + ":")]
        self.assertEqual(len(rows), 1, "IDF1-RED: the Desktop log has %d row(s) named 保安装置介入 (expected exactly 1)" % len(rows))
        self.assertIn("score_details.get('ats', 0)", rows[0], "IDF1-RED: the Desktop log row does not read the internal 'ats' key")

    def test_03_the_window_and_f1_use_the_same_name(self):
        import initial_defaults_ui as U
        window_label = dict(U.PENALTY_LABELS)["pen_safety"]
        row = [t for t in X.render_f1(self.o, 6, menu_cursor=1, menu_cursor_x=-1)[0] if t[0] == window_label]
        self.assertEqual(window_label, NEW, "IDF1-GUARD: the window label is not 保安装置介入")
        self.assertTrue(row, "IDF1-GUARD: F1 does not draw the label the window uses (%r)" % window_label)

    # ---- 4 / 5: OFF fixed, not operable
    def test_04_the_f1_value_is_off_even_if_the_live_attribute_were_true(self):
        self.o.pen_ats = True                                              # a corrupted live value
        texts, _ = X.render_f1(self.o, 6, menu_cursor=0, menu_cursor_x=0)
        row_y = [t[2] for t in texts if t[0] == NEW][0]
        values = [t[0] for t in texts if t[2] == row_y and t[0] in ("ON", "OFF")]
        self.assertEqual(values, ["OFF"], "IDF1-GUARD: F1 draws %r for the safety intervention row" % values)

    def test_05_enter_does_not_change_it_on_the_label_or_the_value_cell(self):
        for x in (-1, 0):
            self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x = 6, 1, x
            self.o.handle_menu_enter(False)
            self.assertIs(self.o.pen_ats, False, "IDF1-GUARD: Enter at column %d turned it on" % x)

    def test_05_left_and_right_do_not_reach_the_value_cell_or_change_it(self):
        self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x = 6, 1, -1
        for key in (self.o.handle_menu_right, self.o.handle_menu_left, self.o.handle_menu_right):
            key()
            self.assertEqual(self.o.menu_cursor_x, -1, "IDF1-GUARD: the cursor entered the value cell of the locked row")
            self.assertIs(self.o.pen_ats, False)

    def test_05_the_cursor_never_lands_on_the_value_cell_when_moving_onto_the_row(self):
        self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x = 6, 0, 0
        self.o.handle_menu_down()
        self.assertEqual((self.o.menu_cursor, self.o.menu_cursor_x), (1, -1), "IDF1-GUARD: moving down onto the locked row put the cursor on its value cell")

    def test_05_the_row_has_no_value_click_zone(self):
        _, zones = X.render_f1(self.o, 6, menu_cursor=1, menu_cursor_x=-1)
        value_zones = [z for z in zones if len(z) == 6 and z[4] == 1 and z[5] == 0]
        self.assertEqual(value_zones, [], "IDF1-GUARD: the safety intervention value cell is clickable")

    def test_05_space_is_not_an_f1_key(self):
        tracked = re.search(r"keys_to_track = \[([^\]]*)\]", X.source("main.py")).group(1)
        keys = [k.strip().strip("'\"").lower() for k in tracked.split(",")]
        self.assertIn("backspace", keys, "IDF1-HARNESS: the key list was not parsed")
        self.assertNotIn("space", keys, "IDF1-GUARD: Space became an F1 key: the safety intervention row must not react to it")

    def test_05_a_click_on_the_row_label_selects_it_without_changing_it(self):
        _, zones = X.render_f1(self.o, 6, menu_cursor=0, menu_cursor_x=0)
        label_zone = [z for z in zones if len(z) == 6 and z[4] == 1 and z[5] == -1]
        self.assertEqual(len(label_zone), 1, "IDF1-HARNESS: the row label has no click zone")
        self.o.menu_cursor, self.o.menu_cursor_x = label_zone[0][4], label_zone[0][5]
        self.o.handle_menu_enter(False)                                    # the zone click path ends in handle_menu_enter
        self.assertIs(self.o.pen_ats, False, "IDF1-GUARD: a click on the safety intervention row turned it on")

    # ---- 6 / 7 / 8 / 9: presets, scenario settings, snapshot, saved defaults
    def test_06_every_preset_leaves_it_off_in_the_window_and_in_the_saved_file(self):
        import initial_defaults_ui as U
        for index, key in enumerate(self.D.PRESET_NAMES):
            defaults = self.D.apply_preset(self.base(a=60), key)
            self.assertIs(defaults.penalties.safety_intervention, False, "IDF1-GUARD: preset %s sets the safety intervention" % key)
            self.write_saved(defaults)
            self.scenario(30 + index)
            self.assertIs(self.o.pen_ats, False, "IDF1-GUARD: after preset %s the scenario settings hold True" % key)
            self.assertIs(self.SS.build(self.o).safety_intervention, False, "IDF1-GUARD: after preset %s the snapshot holds True" % key)

    def test_07_the_scenario_settings_are_false_whatever_the_file_says(self):
        self.write_saved(self.base(a=60))
        with open(self.path, encoding="utf-8") as f:
            document = json.load(f)
        document["penalties"]["safety_intervention"] = True                # a hand-edited / future file
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(document, f)
        self.scenario(21)
        self.assertIs(self.o.pen_ats, False, "IDF1-GUARD: a True in the file reached the scenario settings")

    def test_08_the_running_snapshot_is_false_before_and_during_a_run(self):
        self.o.pen_ats = True
        self.assertIs(self.SS.value(self.o, "safety_intervention"), False, "IDF1-GUARD: the live value is read as the safety intervention before the start")
        self.o.is_scoring_mode = True
        self.o._scoring_settings = self.SS.build(self.o)
        self.assertIs(self.o._scoring_settings.safety_intervention, False, "IDF1-GUARD: the snapshot holds True")
        self.o.pen_ats = True
        self.assertIs(self.SS.value(self.o, "safety_intervention"), False, "IDF1-GUARD: the running value is True")

    def test_09_true_is_never_saved(self):
        defaults = self.base(a=60)
        defaults = defaults._replace(penalties=defaults.penalties._replace(safety_intervention=True))
        try:
            self._real_save(defaults, self.path)
        except (ValueError, self.D.SaveError):
            return                                                          # refused: nothing true is saved either
        with open(self.path, encoding="utf-8") as f:
            self.assertIs(json.load(f)["penalties"]["safety_intervention"], False, "IDF1-GUARD: a True was written to the saved file")

    def test_09_the_window_always_collects_false(self):
        import initial_defaults_ui as U
        from PyQt6.QtWidgets import QWidget
        d = U.build_dialog(self.D.builtin_defaults(), save=lambda v: None)
        try:
            d.findChild(QWidget, "pen_safety").setChecked(True)
            self.assertIs(U.collect(d).penalties.safety_intervention, False, "IDF1-GUARD: the window collected True")
        finally:
            d.close()
            d.deleteLater()


# ================================================================================================================ the detector must FAIL when the old name is left (instruction item 10)
class DetectorSelfTest(unittest.TestCase):
    def test_an_old_name_in_a_drawn_string_is_detected(self):
        self.assertEqual(old_name_hits(["転動", "  " + OLD + ": 0", NEW]), ["  " + OLD + ": 0"], "IDF1-HARNESS: the detector does not see the old name in a drawn string")

    def test_an_old_name_in_a_source_literal_is_detected(self):
        src = 'draw_toggle_row(1, "%s", x)\nwrite_desktop_log(f"  %s: {n}")\n# %s in a comment is not user-visible\n' % (OLD, OLD, OLD)
        self.assertEqual(len(old_name_hits(user_visible_literals(src))), 2, "IDF1-HARNESS: the source detector missed a literal or counted a comment")

    def test_the_new_name_alone_is_not_flagged(self):
        self.assertEqual(old_name_hits([NEW, "【 %s 】" % NEW]), [])
        self.assertEqual(old_name_hits(user_visible_literals('draw_toggle_row(1, "%s", x)' % NEW)), [])

    def test_the_page_level_assertion_fails_on_a_really_rendered_page_whose_label_is_swapped_to_the_old_name(self):
        """Mutation of the DRAWN text of a REAL page: the label of the rendered F1 page 2/3 is swapped to the old name AFTER the render; the very assertion the F1 tests use must fail on it (instruction item 10)."""
        import main
        X.qt_app()
        rig = R.Rig(main)
        try:
            o = rig.o
            o.width, o.height = (lambda: 1920), (lambda: 1080)
            o.show_help = False
            o.dropdown_active = False
            strings = X.drawn(X.render_f1(o, 6, menu_cursor=1, menu_cursor_x=-1)[0])
        finally:
            rig.close()
        self.assertIn(NEW, strings, "IDF1-HARNESS: the real page does not contain the new name")
        assert_no_old_name(self, strings, "the real page")                                               # passes on the real page ...
        mutated = [OLD if s == NEW else s for s in strings]
        with self.assertRaises(AssertionError):                                                          # ... and MUST fail once the old name is left
            assert_no_old_name(self, mutated, "the mutated page")


if __name__ == "__main__":
    unittest.main()
