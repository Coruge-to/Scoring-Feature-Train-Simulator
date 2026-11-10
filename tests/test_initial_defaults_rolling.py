"""INITIAL-DEFAULTS Commit 4 (Owner contract 2026-11-10): rolling (転動) becomes a setting, and the display name 'ATS信号無視' becomes 保安装置介入 (still OFF fixed in the beta). RED = fails on 2c5095f; messages start with 'ID4-RED'.

Contract
  * rolling: builtin ON; F1 (the scoring settings page, row 0) switches ON / OFF BEFORE the scoring start only; the start freezes it in the running snapshot; after the start F1 can not change it and the scoring reads ONLY the snapshot;
    a new scenario / F5 regenerates it from the saved defaults; an F1 change never writes the saved defaults. OFF stops ONLY the rolling penalty (no other deduction is disabled); ON keeps the existing arithmetic (4 x 5 cm = -2000).
  * the HUD feature text lists [転動] exactly when rolling is on (built from the scoring settings); the result screen shows the rolling row OFF when it is off.
  * the user-visible name is 保安装置介入 (F1 page, its help, the result screen); the old name is gone from every user-visible string; the internal identifiers (ats, ATS_SIGNAL_IGNORE_AVAILABLE, CATEGORY_ORDER keys, protocol keys) are NOT renamed.
    The beta keeps it OFF: F1 can not turn it ON, the snapshot is always False."""
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

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-initdef-roll-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "USERPROFILE", "HOME")}
    for k in _TMP["saved"]:
        os.environ[k] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-roll"])
        import main
        import scoring_logic
        import scoring_settings
        import initial_defaults
        cls.main, cls.S, cls.SS, cls.D = main, scoring_logic, scoring_settings, initial_defaults

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.defaults = self.D.builtin_defaults()
        self.o.initial_defaults_loader = lambda: self.D.LoadResult(self.defaults, "file", ())

    def scenario(self, sid):
        self.o.apply_telemetry_text("SCENARIO_ID:%d,SPEED:0" % sid)

    def f1_row0(self, x=0):
        o = self.o
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 0, x
        o.handle_menu_enter(False)

    def run_with(self, rolling_live):
        """a running scoring at an open door; returns (score, roll detail) after the train moved 0.2 m (4 x 5 cm)."""
        o = self.o
        self.scenario(5)
        o.pen_roll = rolling_live
        o.is_scoring_mode, o.is_scoring_finished, o.is_first_udp = True, False, False
        o._scoring_settings = self.SS.build(o)
        o.score, o.score_details, o.popups = 0, dict(getattr(o, 'score_details', {}), roll=0), []
        o.bve_door, o.prev_door, o.bve_speed, o.bve_location, o.door_open_loc, o.roll_penalty_count = 1, 1, 0.0, 100.0, 100.0, 0
        self.S.update_physics_and_scoring(o, 10.0, 0.1)
        return o

    def move(self, o, loc=100.2):
        o.bve_location, o.bve_speed = loc, 0.1
        self.S.update_physics_and_scoring(o, 10.1, 0.1)
        return o.score, o.score_details.get("roll", 0)


class Setting(Base):
    def test_the_builtin_rolling_is_on_and_a_new_scenario_regenerates_it(self):
        self.scenario(5)
        self.assertIs(self.o.pen_roll, True)
        self.o.pen_roll = False
        self.scenario(6)
        self.assertIs(self.o.pen_roll, True, "ID4-RED: the next scenario kept the F1 value")
        b = self.D.builtin_defaults()
        self.defaults = b._replace(penalties=b.penalties._replace(rolling=False))
        self.scenario(7)
        self.assertIs(self.o.pen_roll, False)
        self.scenario(8)                                                      # F5: the saved value again
        self.o.pen_roll = True
        self.scenario(9)
        self.assertIs(self.o.pen_roll, False)

    def test_f1_switches_rolling_on_and_off_before_the_start_and_never_writes_the_defaults(self):
        self.scenario(5)
        saved = self.D.save
        self.D.save = lambda *a, **k: self.fail("ID4-RED: an F1 change wrote the saved defaults")
        try:
            self.assertIs(self.o.pen_roll, True)
            self.f1_row0()
            self.assertIs(self.o.pen_roll, False, "ID4-RED: Enter on the rolling value did not switch it OFF")
            self.f1_row0()
            self.assertIs(self.o.pen_roll, True, "ID4-RED: Enter did not switch it ON again")
        finally:
            self.D.save = saved

    def test_the_cursor_reaches_the_rolling_value(self):
        o = self.o
        self.scenario(5)
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 0, -1
        o.handle_menu_right(False) if "is_bve_advancing" in o.handle_menu_right.__code__.co_varnames else o.handle_menu_right()
        self.assertEqual(o.menu_cursor_x, 0, "ID4-RED: the Right key does not reach the rolling ON / OFF value")

    def test_after_the_start_f1_can_not_change_rolling(self):
        o = self.run_with(True)
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 0, 0
        o.handle_menu_enter(False)
        self.assertIs(o.pen_roll, True, "ID4-RED: F1 changed rolling while a Run is active")
        self.assertIs(self.SS.value(o, "rolling"), True)

    def test_the_start_is_the_only_writer_of_the_snapshot(self):
        src = source("main.py")
        self.assertEqual(src.count("self._scoring_settings = build_scoring_settings(self)"), 1, "ID4-RED: more than one place builds the snapshot (a retry must keep the one of the Run)")
        import re
        assigns = re.findall(r"\b_scoring_settings\s*=\s*(?!None\b)\S", src + source("scoring_logic.py"))
        self.assertEqual(len(assigns), 1, "no other writer of the snapshot in main.py / scoring_logic.py (the construction default None is the only other assignment)")


class Scoring(Base):
    def test_rolling_on_keeps_the_existing_arithmetic(self):
        o = self.run_with(True)
        self.assertEqual(self.move(o), (-2000, -2000), "ID4-RED: the ON arithmetic changed")
        self.assertTrue(any(p.get("category") == "転動" for p in o.popups))

    def test_rolling_off_in_the_snapshot_stops_only_the_rolling_penalty(self):
        o = self.run_with(False)
        self.assertEqual(self.move(o), (0, 0), "ID4-RED: rolling OFF still deducted")
        self.assertFalse(any(p.get("category") == "転動" for p in o.popups))
        self.assertIs(self.SS.value(o, "speed_limit_exceeded"), True, "the other deductions stay as they were")
        self.assertIs(self.SS.value(o, "stop_shock"), True)
        self.assertIs(self.SS.value(o, "emergency_brake"), True)

    def test_rolling_off_does_not_disable_the_other_deductions(self):
        deltas = {}
        for rolling in (True, False):
            o = self.run_with(rolling)
            o.bve_door, o.prev_door, o.effective_limit, o.bve_speed = 0, 0, 50.0, 60.0
            o.is_official_jumping, o.is_speed_limit_exceeded, o.accumulated_speed_penalty = False, False, 0
            before = o.score
            self.S.update_speed_limit_penalty(o, 100.0)
            self.S.update_speed_limit_penalty(o, 101.5)
            deltas[rolling] = o.score - before
        self.assertLess(deltas[True], 0, "the fixture: the speed limit penalty runs")
        self.assertEqual(deltas[False], deltas[True], "ID4-RED: rolling OFF changed the speed limit deduction")

    def test_only_the_rolling_block_and_the_feature_text_know_the_rolling_setting(self):
        import ast
        tree = ast.parse(source("scoring_logic.py"))
        users = sorted(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and "'rolling'" not in ast.dump(n) and '"rolling"' not in ast.dump(n) and False)
        names = sorted(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and "Constant(value='rolling')" in ast.dump(n))
        self.assertEqual(names, ["scoring_feature_string", "update_physics_and_scoring"], "ID4-RED: another deduction reads the rolling setting (rolling OFF must stop only the rolling penalty)")
        self.assertEqual(users, [])

    def test_the_result_row_flag_of_rolling_is_the_inverse_of_the_setting(self):
        self.assertIn("is_roll_off  = not getattr(self, 'pen_roll', True)", source("menu_ui.py"), "ID4-RED: the result row flag is not the inverse of the rolling setting")

    def test_the_scoring_reads_the_snapshot_not_the_live_attribute(self):
        o = self.run_with(True)
        o.pen_roll = False                                                    # the scenario settings change in the middle of the Run
        self.assertEqual(self.move(o), (-2000, -2000), "ID4-RED: a live change reached the running scoring")
        o2 = self.run_with(False)
        o2.pen_roll = True
        self.assertEqual(self.move(o2), (0, 0), "ID4-RED: the live ON reached a Run that started OFF")

    def test_the_rolling_gate_does_not_leak_into_the_next_run(self):
        o = self.run_with(False)
        self.assertEqual(self.move(o), (0, 0))
        o.is_scoring_mode = False
        o = self.run_with(True)
        o.score, o.score_details["roll"] = 0, 0
        o.roll_penalty_count, o.door_open_loc, o.bve_location = 0, 100.0, 100.0
        self.assertEqual(self.move(o), (-2000, -2000), "ID4-RED: the previous Run's OFF was inherited")


class Display(Base):
    def test_the_hud_feature_text_lists_rolling_exactly_when_it_is_on(self):
        o = self.run_with(True)
        self.assertEqual(self.S.scoring_feature_string(o), "[転動] [制限超] [衝動] [EB]", "ID4-RED: the HUD text of the default settings changed")
        o2 = self.run_with(False)
        self.assertEqual(self.S.scoring_feature_string(o2), "[制限超] [衝動] [EB]", "ID4-RED: the HUD text still lists rolling")
        o2.is_scoring_mode = False
        o2.pen_roll = False
        o2.pen_limit = o2.pen_jerk = o2.pen_eb = False
        self.assertEqual(self.S.scoring_feature_string(o2), "すべてOFF")

    def test_the_hud_line_does_not_hard_code_rolling(self):
        src = source("hud_ui.py")
        self.assertNotIn("[転動]", src, "ID4-RED: hud_ui still prints [転動] unconditionally")
        self.assertIn("f_str", src)

    def test_the_result_screen_shows_the_rolling_row_off_when_it_is_off(self):
        src = source("menu_ui.py")
        self.assertIn('draw_score_row("転動", "roll", "緩和ブレーキ", "rel_brake", table_y + row_h * 3, is_roll_off, is_rel_off)', src, "ID4-RED: the result row of rolling is not switchable")
        self.assertIn("is_roll_off", src)

    def test_the_f1_page_draws_the_rolling_value_from_the_setting(self):
        src = source("menu_ui.py")
        self.assertIn('draw_toggle_row(0, "転動", getattr(self, \'pen_roll\', True), list_y_start)', src, "ID4-RED: the rolling row is still ON fixed")
        self.assertNotIn("if cursor_idx != 0:", src, "ID4-RED: the rolling value has no cursor")


class SafetyIntervention(Base):
    def test_the_old_name_is_gone_from_every_user_visible_string(self):
        for name in ("menu_ui.py", "hud_ui.py", "initial_defaults_ui.py"):
            self.assertNotIn("ATS信号無視", source(name), "ID4-RED: %s still shows the old name" % name)
        self.assertGreaterEqual(source("menu_ui.py").count("保安装置介入"), 3, "ID4-RED: the F1 page / help / result screen do not show the new name")

    def test_the_internal_identifiers_are_not_renamed(self):
        cfg = source("config.py")
        self.assertIn('"ATS信号無視": 5', cfg, "the internal category key stays (no refactor mixed into the display change)")
        self.assertIn("ATS_SIGNAL_IGNORE_AVAILABLE = False", cfg)
        self.assertIn('"ats"', source("menu_ui.py"))

    def test_f1_can_not_turn_the_safety_intervention_on(self):
        o = self.o
        self.scenario(5)
        o.is_scoring_mode = False
        for x in (0, -1):
            o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 1, x
            o.handle_menu_enter(False)
        self.assertIs(o.pen_ats, False)
        self.assertIs(self.S.is_ats_signal_ignore_effective(o.pen_ats), False)

    def test_the_snapshot_and_the_scenario_settings_are_always_off(self):
        b = self.D.builtin_defaults()
        self.defaults = b._replace(penalties=b.penalties._replace(safety_intervention=True))
        o = self.run_with(True)
        self.assertIs(o.pen_ats, False)
        self.assertIs(o._scoring_settings.safety_intervention, False)
        self.assertNotIn("[ATS]", self.S.scoring_feature_string(o))

    def test_the_presets_keep_it_off(self):
        for name in self.D.PRESET_NAMES:
            self.assertIs(self.D.apply_preset(self.D.builtin_defaults(), name).penalties.safety_intervention, False)


class Shared(Base):
    def test_there_is_no_current_or_legacy_branch_in_the_rolling_path(self):
        for name in ("scoring_settings.py", "initial_defaults.py"):
            low = source(name).lower()
            for word in ("legacy", "bve5", "bve6"):
                self.assertNotIn(word, low, "%s must not branch on the host" % name)
        src = source("scoring_logic.py")
        block = src[src.index("elif getattr(self, 'bve_door', 0) == 1:"):src.index("update_close_range_departure_reset(self, current_time)")]
        for word in ("legacy", "current_dll", "caller"):
            self.assertNotIn(word, block.lower())


if __name__ == "__main__":
    unittest.main()
