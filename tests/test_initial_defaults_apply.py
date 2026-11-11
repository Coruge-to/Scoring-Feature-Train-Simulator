"""INITIAL-DEFAULTS Commit 3 (Owner contract 2026-11-10): the saved_defaults -> scenario_settings -> running_snapshot flow. RED = fails on the Commit 2 tree; messages start with 'ID3-RED'.

Contract
  * scenario_settings (the F1 attributes of the Overlay) are REGENERATED from the saved defaults (read from the file at every scenario load; no file = the builtin values) at: the first scenario of a BVE session (current_scenario_id == -1),
    another scenario, a re-selection after the scenario ended, and F5 (a new SCENARIO_ID). The values are copied (no dict / list is shared with the defaults or between two loads).
  * a change of the saved file in the middle of a scenario changes nothing; an F1 change never writes the saved defaults; the safety intervention is always OFF (pen_ats False, whatever the file says).
  * the all-timing setting (変更可能な非採時駅を全て採時駅にする) is applied ONCE per scenario generation, after the station list is known, by an IDEMPOTENT function (never the F1 toggle); OFF keeps the route's own timing; the fixed
    contracts (the scoring start, the pseudo-turnback B) always win.
  * running_snapshot: the scoring start freezes the six scoring settings, the A boundary and the timing overrides in an immutable ScoringSettings; while the Run is active the scoring reads ONLY the snapshot (the live attributes are
    never read), before the start it reads the live attributes; the snapshot is dropped when the Run ends or another scenario loads; nothing is shared with the live values."""
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
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-initdef-apply-")
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
        cls.app = QApplication.instance() or QApplication(["initdef-apply"])
        import main
        import scoring_logic
        import initial_defaults
        cls.main, cls.S, cls.D = main, scoring_logic, initial_defaults
        try:
            import scoring_settings
        except ImportError as exc:
            raise AssertionError("ID3-RED: the module scoring_settings does not exist (%s)" % exc)
        cls.SS = scoring_settings

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.defaults = self.D.builtin_defaults()
        self.loads = []
        self.o.initial_defaults_loader = self.loader

    def loader(self):
        self.loads.append(self.defaults)
        return self.D.LoadResult(self.defaults, "file", ())

    def scenario(self, sid):
        self.o.apply_telemetry_text("SCENARIO_ID:%d,SPEED:0" % sid)

    def custom(self):
        b = self.D.builtin_defaults()
        return b._replace(a_rank_percent=80, all_changeable_non_timed_to_timed=False,
                          penalties=b.penalties._replace(rolling=False, speed_limit_exceeded=False, stop_shock=False, emergency_brake=False, initial_release_brake="on1"),
                          environment=type(b.environment)(True, True, True, True, False, True, False, True))


class Regenerate(Base):
    def test_the_first_scenario_of_a_session_applies_the_defaults(self):
        self.defaults = self.custom()
        self.assertEqual(self.o.current_scenario_id, -1)
        self.scenario(5)
        o = self.o
        self.assertEqual(len(self.loads), 1, "ID3-RED: the first scenario did not read the saved defaults")
        self.assertEqual((o.disp_settings["limit_advance"], o.disp_settings["handle"], o.disp_settings["limit"]), (False, False, True))
        self.assertEqual((o.pen_roll, o.pen_limit, o.pen_jerk, o.pen_eb, o.pen_ats), (False, False, False, False, False))
        self.assertEqual(o.rank_a_ratio, 0.8)
        self.assertEqual([(r["apply"], r["release"]) for r in o.penalty_init_rules], [("ON①", "ON①")])

    def test_no_file_gives_the_builtin_values_at_every_load(self):
        self.scenario(5)
        o = self.o
        o.pen_limit = False
        o.rank_a_ratio = 0.9
        o.disp_settings["limit"] = False
        o.penalty_init_rules = [{"end_idx": -1, "apply": "ON②", "release": "ON②"}]
        self.scenario(6)
        self.assertEqual((o.pen_roll, o.pen_limit, o.pen_jerk, o.pen_eb, o.pen_ats, o.rank_a_ratio), (True, True, True, True, False, 0.6))
        self.assertEqual(set(o.disp_settings.values()), {True})
        self.assertEqual([(r["apply"], r["release"]) for r in o.penalty_init_rules], [("OFF", "OFF")], "ID3-RED: the builtin initial / release brake is OFF")

    def test_another_scenario_regenerates_and_a_f1_change_is_current_scenario_only(self):
        self.defaults = self.custom()
        self.scenario(5)
        o = self.o
        o.pen_roll = True
        o.rank_a_ratio = 0.9
        o.penalty_init_rules = [{"end_idx": -1, "apply": "ON②", "release": "ON②"}]
        self.assertEqual((o.pen_roll, o.rank_a_ratio), (True, 0.9), "the F1 change is valid in the current scenario")
        self.scenario(6)
        self.assertEqual((o.pen_roll, o.rank_a_ratio), (False, 0.8), "ID3-RED: another scenario kept the F1 values")
        self.assertEqual([(r["apply"], r["release"]) for r in o.penalty_init_rules], [("ON①", "ON①")], "ID3-RED: ON② survived the next scenario")

    def test_f5_is_a_new_scenario_load(self):
        self.defaults = self.custom()
        self.scenario(5)
        o = self.o
        o.pen_roll = True
        o.rank_a_ratio = 0.9
        self.scenario(6)                                             # F5: the same route, a new SCENARIO_ID
        self.assertEqual((o.pen_roll, o.rank_a_ratio), (False, 0.8))
        self.assertEqual(len(self.loads), 2)

    def test_the_same_scenario_id_does_not_reapply(self):
        self.scenario(5)
        o = self.o
        o.pen_limit = False
        self.scenario(5)
        self.assertFalse(o.pen_limit)
        self.assertEqual(len(self.loads), 1)

    def test_a_change_of_the_saved_file_does_not_touch_the_current_scenario(self):
        self.scenario(5)
        o = self.o
        before = (dict(o.disp_settings), o.pen_roll, o.pen_limit, o.rank_a_ratio, [dict(r) for r in o.penalty_init_rules])
        self.defaults = self.custom()                                # the Properties window saved something
        o.apply_telemetry_text("SCENARIO_ID:5,SPEED:3")
        self.assertEqual((dict(o.disp_settings), o.pen_roll, o.pen_limit, o.rank_a_ratio, [dict(r) for r in o.penalty_init_rules]), before, "ID3-RED: the Properties change reached the current scenario")
        self.scenario(6)
        self.assertEqual(o.rank_a_ratio, 0.8, "the next scenario uses it")

    def test_the_safety_intervention_is_always_off(self):
        b = self.D.builtin_defaults()
        self.defaults = b._replace(penalties=b.penalties._replace(safety_intervention=True))
        self.scenario(5)
        self.assertIs(self.o.pen_ats, False, "ID3-RED: a saved true reached pen_ats")
        self.assertIs(self.S.is_ats_signal_ignore_effective(self.o.pen_ats), False)

    def test_a_forbidden_environment_state_is_normalised_when_the_settings_are_regenerated(self):
        b = self.D.builtin_defaults()
        env = list(b.environment)
        env[3], env[4] = False, True                                   # (limit OFF, advance ON) cannot exist
        self.defaults = b._replace(environment=type(b.environment)(*env))
        self.scenario(5)
        self.assertEqual((self.o.disp_settings["limit"], self.o.disp_settings["limit_advance"]), (False, False), "ID3-RED: (limit OFF, advance ON) reached the F1 settings")

    def test_a_failing_loader_gives_the_builtin_values_and_raises_nothing(self):
        def boom():
            raise OSError("the file system is gone")
        self.o.initial_defaults_loader = boom
        self.o.apply_telemetry_text("SCENARIO_ID:5,SPEED:0")
        self.assertEqual((self.o.rank_a_ratio, self.o.pen_roll, self.o.pen_ats), (0.6, True, False), "ID3-RED: a failing loader leaked or left the old values")

    def test_the_timing_sync_is_wired_after_the_station_list_is_adopted(self):
        src = source("main.py")
        body = src[src.index("    def read_udp_data(self):"):src.index("    def _note_jump_complete(self, text):")]
        self.assertLess(body.index("self._route_pairset_sync()"), body.index("self._initial_defaults_timing_sync()"), "ID3-RED: the all-timing sync is not run after the station list is adopted")

    def test_the_scoring_housekeeping_drops_the_settings_snapshot_too(self):
        self.scenario(5)
        o = self.o
        o.is_scoring_mode = True
        o._scoring_settings = self.SS.build(o)
        self.scenario(6)
        self.S.scoring_section_housekeeping(o)
        self.assertIsNone(o.__dict__.get("_scoring_settings"), "ID3-RED: scoring_section_housekeeping left the old snapshot")

    def test_nothing_is_shared_between_the_defaults_and_the_scenario_settings(self):
        self.scenario(5)
        o = self.o
        first_disp, first_rules = o.disp_settings, o.penalty_init_rules
        o.disp_settings["time"] = False
        o.penalty_init_rules[0]["apply"] = "ON②"
        self.assertEqual(tuple(self.defaults.environment), (True,) * 8, "ID3-RED: the saved defaults were changed through the scenario settings")
        self.scenario(6)
        self.assertIsNot(o.disp_settings, first_disp, "ID3-RED: the same dict was reused")
        self.assertIsNot(o.penalty_init_rules, first_rules)
        self.assertTrue(o.disp_settings["time"])
        self.assertEqual(o.penalty_init_rules[0]["apply"], "OFF")

    def test_a_damaged_file_gives_the_builtin_values_through_the_real_loader(self):
        import initial_defaults as D
        path = os.path.join(_TMP["dir"].name, "Coruge-to", "TS Scoring", "initial-defaults.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(b"{broken")
        self.o.initial_defaults_loader = D.load                       # the real loader, reading %LOCALAPPDATA%
        self.scenario(5)
        self.assertEqual((self.o.rank_a_ratio, self.o.pen_roll), (0.6, True))
        self.assertEqual(open(path, "rb").read(), b"{broken", "ID3-RED: a load rewrote the damaged file")
        D.save(self.custom(), path)
        self.scenario(6)
        self.assertEqual(self.o.rank_a_ratio, 0.8, "the real saved file is read at the next load")

    def test_the_overlay_never_writes_the_saved_defaults(self):
        for name in ("main.py", "menu_ui.py", "scoring_logic.py", "hud_ui.py"):
            src = source(name)
            for bad in ("initial_defaults.save", "D.save(", "initial_defaults import save"):
                self.assertNotIn(bad, src, "ID3-RED: %s writes the saved defaults (%s)" % (name, bad))

    def test_the_limit_dependency_function_of_f1_is_the_shared_one(self):
        o = self.o
        for limit in (True, False):
            for adv in (True, False):
                for enabled in (True, False):
                    a = dict(o.disp_settings)
                    o.disp_settings.update({"limit": limit, "limit_advance": adv})
                    o.set_speed_limit_visible(enabled)
                    got_a = (o.disp_settings["limit"], o.disp_settings["limit_advance"])
                    s = {"limit": limit, "limit_advance": adv}
                    self.D.set_speed_limit(s, enabled)
                    self.assertEqual(got_a, (s["limit"], s["limit_advance"]))
                    o.disp_settings.update({"limit": limit, "limit_advance": adv})
                    o.set_speed_limit_advance_visible(enabled)
                    s = {"limit": limit, "limit_advance": adv}
                    self.D.set_speed_limit_advance(s, enabled)
                    self.assertEqual((o.disp_settings["limit"], o.disp_settings["limit_advance"]), (s["limit"], s["limit_advance"]))
        src = source("main.py")
        self.assertIn("initial_defaults.set_speed_limit_advance(", src, "ID3-RED: F1 does not use the shared state function")

    def test_the_a_rank_clamp_is_one_function(self):
        src = source("main.py")
        self.assertNotIn("max(0.50, round(self.rank_a_ratio", src, "ID3-RED: a clamp is still written inline")
        self.assertNotIn("min(0.9, round(self.rank_a_ratio", src)
        self.assertIn("clamp_a_rank_ratio", src)


class AllTiming(Base):
    def stations(self, timing):
        names = ["W", "X", "Y", "Z", "V"]
        self.o.station_list = [{"name": n, "is_timing": t} for n, t in zip(names, timing)]

    def settle(self, sid):
        self.scenario(sid)
        self.o.bve_list_id = "ABCD1234"                                # the station list identity of this scenario is known

    def test_all_timing_is_applied_once_after_the_station_list_is_known(self):
        b = self.D.builtin_defaults()
        self.defaults = b._replace(all_changeable_non_timed_to_timed=True)
        self.scenario(5)
        self.stations([False, False, True, False, False])
        self.assertEqual(self.o.user_timing_overrides, {}, "nothing is applied before the station list is known")
        self.o.bve_list_id = "ABCD1234"
        self.o.setting_start_idx = 0
        self.o.setting_end_idx = -1
        self.o._initial_defaults_timing_sync()
        applied = dict(self.o.user_timing_overrides)
        self.assertTrue(applied, "ID3-RED: the all-timing setting was not applied")
        for idx, value in applied.items():
            self.assertTrue(value)
            self.assertFalse(self.o.station_list[idx]["is_timing"])
            self.assertIsNone(self.S.untimed_reason(self.o, idx), "ID3-RED: a fixed untimed station was changed")
        self.o.user_timing_overrides.clear()                           # the user reset it in F1: the sync of the same generation must not re-apply
        self.o._initial_defaults_timing_sync()
        self.assertEqual(self.o.user_timing_overrides, {}, "ID3-RED: it was applied twice in one generation")
        self.scenario(6)                                               # a new generation applies again
        self.o.bve_list_id = "ABCD1234"
        self.o._initial_defaults_timing_sync()
        self.assertTrue(self.o.user_timing_overrides)

    def test_the_sync_waits_for_the_station_list_and_ignores_another_generation(self):
        b = self.D.builtin_defaults()
        self.defaults = b._replace(all_changeable_non_timed_to_timed=True)
        self.scenario(5)
        self.o._initial_defaults_timing_sync()                         # no station list yet: nothing is applied and the setting is kept for later
        self.assertEqual(self.o.user_timing_overrides, {})
        self.assertIsNotNone(self.o._pending_all_timing, "ID3-RED: the pending all-timing was dropped before the station list was known")
        self.stations([False, False, True, False, False])
        self.o.setting_start_idx = 0
        self.o.setting_end_idx = -1
        self.o.bve_list_id = "ABCD1234"
        self.o._initial_defaults_timing_sync()
        self.assertTrue(self.o.user_timing_overrides, "applied once the list is known")
        self.o.user_timing_overrides.clear()
        self.o._pending_all_timing = (4, True)                         # a setting of an older generation
        self.o._initial_defaults_timing_sync()
        self.assertEqual(self.o.user_timing_overrides, {}, "ID3-RED: a setting of another generation was applied")
        self.assertIsNone(self.o._pending_all_timing)

    def test_off_keeps_the_route_timing_and_flips_nothing(self):
        self.scenario(5)
        self.stations([True, False, True, False, True])
        before = [self.o.is_station_timing(i) for i in range(5)]       # (the route's own timing, with the fixed contracts as they are)
        self.o.bve_list_id = "ABCD1234"
        self.o._initial_defaults_timing_sync()
        self.assertEqual(self.o.user_timing_overrides, {}, "ID3-RED: OFF changed a station")
        self.assertEqual([self.o.is_station_timing(i) for i in range(5)], before)
        self.assertTrue(before[2] and before[4], "an already timed station is not turned off")

    def test_the_function_is_idempotent_and_not_the_f1_toggle(self):
        self.scenario(5)
        self.stations([False, False, True, False, False])
        self.o.setting_start_idx = 0
        self.o.setting_end_idx = -1
        self.o.apply_all_changeable_non_timed_as_timed(True)
        first = dict(self.o.user_timing_overrides)
        self.o.apply_all_changeable_non_timed_as_timed(True)
        self.assertEqual(self.o.user_timing_overrides, first, "ID3-RED: applying twice changed the state (a toggle)")
        self.o.apply_all_changeable_non_timed_as_timed(False)
        self.assertEqual(self.o.user_timing_overrides, first, "ID3-RED: enabled=False changed the state")
        self.assertTrue(all(self.o.is_station_timing(i) for i in first))
        self.assertTrue(self.o.is_station_timing(2), "an already timed station stays timed")

    def test_disabled_changes_nothing_on_a_fresh_state(self):
        self.scenario(5)
        self.stations([False, False, True, False, False])
        self.o.setting_start_idx = 0
        self.o.setting_end_idx = -1
        self.o.apply_all_changeable_non_timed_as_timed(False)
        self.assertEqual(self.o.user_timing_overrides, {}, "ID3-RED: enabled=False changed a station")

    def test_the_f1_all_timing_toggle_is_unchanged(self):
        self.scenario(5)
        self.stations([False, False, True, False, False])
        self.o.setting_start_idx = 0
        self.o.setting_end_idx = -1
        self.o.toggle_all_timing()
        self.assertTrue(self.o.user_timing_overrides)
        self.o.toggle_all_timing()
        self.assertEqual(self.o.user_timing_overrides, {})


class RunningSnapshot(Base):
    def start(self):
        self.scenario(5)
        o = self.o
        o.is_scoring_mode = True
        o._scoring_settings = self.SS.build(o)
        return o

    def test_the_snapshot_is_immutable_and_independent(self):
        o = self.start()
        snap = o._scoring_settings
        self.assertIsInstance(snap, tuple)
        with self.assertRaises(AttributeError):
            snap.rolling = False
        o.penalty_init_rules[0]["apply"] = "ON②"
        o.user_timing_overrides[1] = True
        self.assertEqual(snap.init_rules, ((-1, "OFF", "OFF"),), "ID3-RED: the snapshot shares the live rule list")
        self.assertEqual(snap.timing_overrides, (), "ID3-RED: the snapshot shares the live overrides")

    def test_the_snapshot_holds_each_live_value_in_its_own_field(self):
        self.scenario(5)
        o = self.o
        o.pen_roll, o.pen_limit, o.pen_jerk, o.pen_eb, o.rank_a_ratio = False, True, False, True, 0.77
        o.penalty_init_rules = [{"end_idx": 3, "apply": "ON②", "release": "OFF"}, {"end_idx": -1, "apply": "OFF", "release": "ON①"}]
        o.user_timing_overrides = {2: True, 1: False}
        s = self.SS.build(o)
        self.assertEqual((s.rolling, s.speed_limit_exceeded, s.stop_shock, s.emergency_brake, s.safety_intervention, s.a_rank_ratio), (False, True, False, True, False, 0.77), "ID3-RED: a field holds another setting")
        self.assertEqual(s.init_rules, ((3, "ON②", "OFF"), (-1, "OFF", "ON①")))
        self.assertEqual(s.timing_overrides, ((1, False), (2, True)))
        self.assertEqual(s.generation, 5)
        import itertools
        for roll, limit, jerk, eb in itertools.product((True, False), repeat=4):          # every combination: no field can hold another field's setting
            o.pen_roll, o.pen_limit, o.pen_jerk, o.pen_eb = roll, limit, jerk, eb
            s = self.SS.build(o)
            self.assertEqual((s.rolling, s.speed_limit_exceeded, s.stop_shock, s.emergency_brake), (roll, limit, jerk, eb))
            o.is_scoring_mode = False
            V = self.SS.value
            self.assertEqual((V(o, "rolling"), V(o, "speed_limit_exceeded"), V(o, "stop_shock"), V(o, "emergency_brake")), (roll, limit, jerk, eb))

    def test_the_live_mapping_and_the_defaults_of_the_accessor(self):
        import types
        bare = types.SimpleNamespace()
        V = self.SS.value
        self.assertEqual((V(bare, "rolling"), V(bare, "speed_limit_exceeded"), V(bare, "stop_shock"), V(bare, "emergency_brake"), V(bare, "a_rank_ratio")), (True, True, True, True, 0.6))           # INITIAL-DEFAULTS Stage F2 (Owner 2026-11-11): the default A boundary is 60
        live = types.SimpleNamespace(pen_roll=False, pen_limit=True, pen_jerk=False, pen_eb=True, rank_a_ratio=0.81)
        self.assertEqual((V(live, "rolling"), V(live, "speed_limit_exceeded"), V(live, "stop_shock"), V(live, "emergency_brake"), V(live, "a_rank_ratio")), (False, True, False, True, 0.81))

    def test_an_active_run_reads_only_the_snapshot(self):
        o = self.start()
        o.pen_ats = True                                                  # (a live true is never read as the safety intervention)
        o.pen_limit, o.pen_jerk, o.pen_eb, o.pen_roll, o.rank_a_ratio = False, False, False, False, 0.9
        o.penalty_init_rules = [{"end_idx": -1, "apply": "ON②", "release": "ON②"}]
        o.user_timing_overrides[3] = True
        V = self.SS.value
        self.assertEqual((V(o, "speed_limit_exceeded"), V(o, "stop_shock"), V(o, "emergency_brake"), V(o, "rolling"), V(o, "safety_intervention"), V(o, "a_rank_ratio")), (True, True, True, True, False, 0.6),
                         "ID3-RED: the active run read a live attribute")
        self.assertEqual(V(o, "init_rules"), [{"end_idx": -1, "apply": "OFF", "release": "OFF"}])
        self.assertFalse(self.SS.timing_override(o, 3)[0], "the live override is not read while the run is active")

    def test_before_the_start_the_live_attributes_are_read(self):
        self.scenario(5)
        o = self.o
        o.pen_limit = False
        o.rank_a_ratio = 0.9
        V = self.SS.value
        self.assertEqual((V(o, "speed_limit_exceeded"), V(o, "a_rank_ratio")), (False, 0.9))
        self.assertIsNone(self.SS.active(o))

    def test_the_snapshot_ends_with_the_run_and_with_the_scenario(self):
        o = self.start()
        self.assertIsNotNone(self.SS.active(o))
        o.is_scoring_finished = True
        self.assertIsNone(self.SS.active(o))
        o.is_scoring_finished = False
        self.scenario(6)
        self.assertIsNone(self.SS.active(o), "ID3-RED: the snapshot of the old scenario is still active")
        self.SS.housekeeping(o)
        self.assertIsNone(o.__dict__.get("_scoring_settings"))

    def test_a_snapshot_of_another_generation_is_never_used(self):
        o = self.start()
        o.current_scenario_id = 99
        self.assertIsNone(self.SS.active(o))

    def test_the_timing_of_the_scoring_comes_from_the_snapshot(self):
        o = self.start()
        o.station_list = [{"name": "W", "is_timing": False}, {"name": "X", "is_timing": False}]
        o.user_timing_overrides[1] = True
        self.assertFalse(o.is_station_timing(1), "ID3-RED: a live override changed the timing of an active run")

    def test_the_start_wires_the_snapshot_before_the_scoring_mode(self):
        src = source("main.py")
        a = src.index("self._scoring_settings = build_scoring_settings(self)")
        b = src.index("self.is_scoring_mode = True", a)
        self.assertLess(a, b, "ID3-RED: the snapshot is not built before the scoring mode is switched on")

    def test_the_scoring_logic_reads_no_live_setting(self):
        src = source("scoring_logic.py")
        for bad in ("getattr(self, 'pen_limit'", "getattr(self, 'pen_jerk'", "getattr(self, 'pen_eb'", "getattr(self, 'pen_ats'", "getattr(self, 'penalty_init_rules'"):
            self.assertNotIn(bad, src, "ID3-RED: scoring_logic still reads %s" % bad)
        self.assertIn("scoring_settings", src)

    def test_the_hud_feature_string_follows_the_snapshot(self):
        o = self.start()
        o.pen_limit = False
        o.pen_jerk = False
        o.pen_eb = False
        o.station_list = [{"name": "W", "is_timing": True}, {"name": "X", "is_timing": True}]
        o.is_scoring_finished = False
        o.bve_next_loc = 100.0
        o.bve_location = 0.0
        o.bve_next_time = 1000
        self.S.update_logic_features(o, 0.0) if hasattr(self.S, "update_logic_features") else None
        self.assertTrue(hasattr(self.S, "scoring_feature_string"), "ID3-RED: scoring_logic has no scoring_feature_string (the HUD feature text built from the settings)")
        text = self.S.scoring_feature_string(o)
        self.assertIn("[制限超]", text)
        self.assertIn("[衝動]", text)
        self.assertIn("[EB]", text)
        self.assertNotIn("[ATS]", text)


if __name__ == "__main__":
    unittest.main()
