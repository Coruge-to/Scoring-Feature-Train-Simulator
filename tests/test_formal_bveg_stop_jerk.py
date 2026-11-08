"""Formal stop-jerk scoring = LastStop BveG (the official AccelerationZ), as an executable contract (RED / GUARD).

THE CONTRACT (Owner, 2026-11-08)
  * Input: the official Vehicle.Vibration.AccelerationZ (m/s^2, exactly as the sender wrote it). Metric: LastStop BveG = |signed mean of the samples of the last 0.5 s| / 9.80665.
  * Deduction on the UNROUNDED value, no tolerance: >= 0.100 G -> -200, >= 0.065 G -> -100, otherwise 0. One step only.
  * No sample in the window -> nothing is judged (no deduction, LastStop BveG = None, F2 "--"); never a fake 0, never another value.
  * CalcG, the n values and the sway path are retired from the product: no symbol, no wire token (CALCG, ACCELX, SWAY, SWAYR), no F2 text, no log field.
  * F2 shows ONE line: "BveG: +0.000 G    LastStop BveG: 0.000 G" ("BveG: ---    LastStop BveG: ---" when unavailable); no graph, no MaxG.
  * The user text of the stop-jerk row names 0.5 s, 0.065G, 2.3km/h/s, 0.100G, 3.5km/h/s; the two boundary spans are coloured (white outline), the rest is normal.
RED rows fail on the baseline 86b7b6e for a declared reason (the first word of the failure message); GUARD rows pass on both. PyQt6 is needed for the executable rows.
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PyQt6") is not None
G = 9.80665


def read(rel):
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), "r", encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


def exists(rel):
    return os.path.exists(os.path.join(ROOT, rel.replace("/", os.sep)))


def code_cs(rel):
    return "\n".join(re.sub(r"//.*$", "", line) for line in read(rel).split("\n"))


def code_py(rel):
    return "\n".join(line for line in read(rel).split("\n") if not line.strip().startswith("#"))


PRODUCT_PY = ("main.py", "scoring_logic.py", "hud_ui.py", "menu_ui.py", "managed_input.py", "managed_hud.py", "network.py", "telemetry_contract.py", "telemetry_gate.py",
              "telemetry_dataplane_receiver.py", "dataplane_contract.py", "managed_state.py", "utils.py", "config.py", "stop_jerk_text.py")
PRODUCT_CS = ("TsScoringPlugin/TsScoringPlugin/Class1.cs", "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs",
              "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs", "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs",
              "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs")
CLASS1 = PRODUCT_CS[0]
LEG_SES, LEG_EXT, LEG_API, CONTRACT_CS = PRODUCT_CS[1:]


def _profile_guard(cls):
    cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-bveg-")
    cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "TS_SCORING_DESKTOP_LOG")}
    os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name


def _profile_release(cls):
    for k, v in cls._saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    cls._profile_dir.cleanup()


# ===================================================================================================================================================
# A. the sources (no Qt)
# ===================================================================================================================================================
class A_Sources(unittest.TestCase):
    RETIRED = re.compile(r"calcg|calc_g|g_history|last_stop_g\b|hb_cushion_max_g|decel_g|sway|accelx|accel_x|FrontAcceleration|lateral_effect|currentG|lastSpeedMps|haveLastSample", re.I)

    def test_FB01_RED_the_product_python_has_no_calcg_sway_or_accelx_symbol(self):
        for rel in PRODUCT_PY:
            hit = [l.strip()[:120] for l in code_py(rel).split("\n") if self.RETIRED.search(l)]
            if hit:
                self.fail("RETIRED-SYMBOL: %s still has %d line(s), e.g. %r" % (rel, len(hit), hit[0]))

    def test_FB02_RED_the_product_csharp_has_no_calcg_sway_or_accelx_symbol(self):
        for rel in PRODUCT_CS:
            hit = [l.strip()[:120] for l in code_cs(rel).split("\n") if self.RETIRED.search(l)]
            if hit:
                self.fail("RETIRED-SYMBOL: %s still has %d line(s), e.g. %r" % (rel, len(hit), hit[0]))

    def test_FB03_RED_the_sway_modules_are_gone(self):
        for rel in ("sway_shadow.py", "TsScoringPlugin/Handshake/Telemetry/Shared/SwayStateReader.cs", "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacySwaySource.cs"):
            if exists(rel):
                self.fail("RETIRED-FILE: %s still exists" % rel)

    def test_FB04_RED_the_wire_has_no_retired_token(self):
        import telemetry_contract as T
        for token in ("calcg", "accelx", "sway"):
            if token in T.TOKEN_KEYS:
                self.fail("RETIRED-TOKEN: TOKEN_KEYS still has %r" % token)
        for name in ("accelx_capture", "sway_capture", "swayr_capture"):
            if hasattr(T, name):
                self.fail("RETIRED-TOKEN: telemetry_contract.%s still exists" % name)
        wire = "\n".join(code_cs(rel) for rel in PRODUCT_CS)
        for key in ('"CALCG', '",CALCG', '"ACCELX', '",ACCELX', '"SWAY"', '"SWAYR"', ',SWAY:', ',SWAYR:'):
            if key in wire:
                self.fail("RETIRED-TOKEN: a C# sender still writes %s" % key)

    def test_FB05_GUARD_the_official_accelerationz_is_still_read_and_written_by_both_senders(self):
        self.assertIn("vehicle.Vibration.AccelerationZ", code_cs(CLASS1))
        self.assertIn('",ACCELZ:"', code_cs(CLASS1))
        self.assertIn("current.Vehicle.VibrationManager.AccelerationZ", code_cs(LEG_EXT))
        self.assertIn('TokAccelZ', code_cs(LEG_SES))
        self.assertIn('"ACCELZ"', code_cs(LEG_SES))
        self.assertIn('TokAccelZ = "accelz"', code_cs(CONTRACT_CS))
        import telemetry_contract as T
        self.assertEqual(T.TOKEN_KEYS.get("accelz"), ("ACCELZ",))

    def test_FB06_GUARD_both_senders_write_accelz_raw_and_independent_of_any_previous_sample(self):
        for name, text, anchor in (("current", code_cs(CLASS1), '",ACCELZ:"'), ("legacy", code_cs(LEG_SES), '"ACCELZ"')):
            i = text.index(anchor)
            around = text[max(0, i - 700):i + 300]
            for banned in ("9.80665", "GravityMps2", "Math.Abs", "Math.Min", "Math.Max", "Clamp"):
                self.assertNotIn(banned, around, "%s ACCELZ must be the raw m/s2 value" % name)
            self.assertIn("F6", around)
            self.assertIn("IsNaN", around)
            self.assertIn("IsInfinity", around)

    def test_FB07_GUARD_the_constants_are_the_ones_of_the_contract(self):
        import config
        self.assertEqual(config.STANDARD_GRAVITY_MPS2, 9.80665)
        self.assertEqual(config.STOP_JERK_WINDOW_SECONDS, 0.5)
        self.assertEqual(config.STOP_JERK_FIRST_BOUNDARY_G, 0.065)
        self.assertEqual(config.STOP_JERK_SECOND_BOUNDARY_G, 0.100)

    def test_FB08_GUARD_the_scoring_function_reads_only_the_accelerationz_samples(self):
        text = code_py("scoring_logic.py")
        body = text[text.index("def update_stop_jerk_penalty"):]
        body = body[:body.index("\ndef ")]
        self.assertIn("judge_stop_jerk", body)
        for banned in ("g_history", "decel_g", "bve_calc_g", "last_stop_g\n"):
            self.assertNotIn(banned, body)
        judge = text[text.index("def judge_stop_jerk"):]
        judge = judge[:judge.index("\ndef ")]
        self.assertIn("accel_z_history", judge)

    def test_FB09_GUARD_the_package_manifest_matches_the_tree(self):
        manifest = json.loads(read("package/source-package-manifest.json"))
        paths = {entry["path"] for entry in manifest["files"]}
        for rel in ("sway_shadow.py", "TsScoringPlugin/Handshake/Telemetry/Shared/SwayStateReader.cs"):
            self.assertNotIn(rel, paths, "%s is retired: it must not be in the manifest" % rel)
        for rel in ("scoring_logic.py", "hud_ui.py", "menu_ui.py", "config.py", "telemetry_contract.py", CLASS1, LEG_SES, CONTRACT_CS):
            self.assertIn(rel, paths)
        for compile_set in manifest["compile_inputs"].values():
            for rel in compile_set:
                self.assertNotIn("Sway", rel)


# ===================================================================================================================================================
# B. pure functions
# ===================================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_Pure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _profile_guard(cls)
        import scoring_logic
        cls.S = scoring_logic

    @classmethod
    def tearDownClass(cls):
        _profile_release(cls)

    def test_FB10_the_window_includes_both_ends(self):
        mean, count = self.S.stop_jerk_window_mean([(9.49, 100.0), (9.50, 1.0), (9.75, 2.0), (10.0, 3.0), (10.01, 100.0)], 10.0)
        self.assertEqual(count, 3)
        self.assertAlmostEqual(mean, 2.0, places=9)

    def test_FB11_samples_outside_the_window_are_not_used_and_an_empty_window_judges_nothing(self):
        self.assertEqual(self.S.stop_jerk_window_mean([(8.0, 5.0), (9.0, 5.0)], 10.0), (None, 0))
        self.assertEqual(self.S.stop_jerk_window_mean([], 10.0), (None, 0))

    def test_FB12_signed_samples_are_averaged_before_the_abs(self):
        mean, _ = self.S.stop_jerk_window_mean([(9.6, 2.0), (9.8, -2.0), (10.0, 2.0), (9.7, -2.0)], 10.0)
        self.assertAlmostEqual(self.S.stop_jerk_g_from_accel_z(mean), 0.0, places=9)
        mean, _ = self.S.stop_jerk_window_mean([(9.7, 2.0), (10.0, -0.5)], 10.0)
        self.assertAlmostEqual(self.S.stop_jerk_g_from_accel_z(mean), 0.75 / G, places=9)

    def test_FB13_the_conversion_is_value_mps2_over_9_80665(self):
        self.assertEqual(self.S.stop_jerk_g_from_accel_z(G), 1.0)
        self.assertEqual(self.S.stop_jerk_g_from_accel_z(-G), 1.0)
        self.assertEqual(self.S.stop_jerk_g_from_accel_z(0.063743225), 0.063743225 / 9.80665)

    def test_FB14_RED_thresholds_on_the_unrounded_value_with_no_tolerance(self):
        P = self.S.stop_jerk_points
        self.assertEqual(P(0.064999999), 0, "TOLERANCE: 0.064999999 G is below the first boundary")
        self.assertEqual(P(0.0649999999), 0, "TOLERANCE: 1e-10 below the first boundary is still 0")
        self.assertEqual(P(0.065), -100)
        self.assertEqual(P(0.065 + 1e-12), -100)
        self.assertEqual(P(0.099999999), -100, "TOLERANCE: 0.099999999 G is below the second boundary")
        self.assertEqual(P(0.0999999999), -100)
        self.assertEqual(P(0.100), -200)
        self.assertEqual(P(0.0), 0)
        for g in (0.065, 0.1, 0.5, 5.0):
            self.assertIn(P(g), (0, -100, -200))

    def test_FB15_RED_the_displayed_rounding_never_decides(self):
        P = self.S.stop_jerk_points
        self.assertEqual(P(0.0645), 0)
        self.assertEqual("%.3f" % 0.06499, "0.065")           # the display would say 0.065 ...
        self.assertEqual(P(0.06499), 0, "ROUNDED-VALUE: ... the judgement must still be 0")
        self.assertEqual("%.3f" % 0.09999, "0.100")
        self.assertEqual(P(0.09999), -100, "ROUNDED-VALUE: the display says 0.100 but the value is below the second boundary")

    def test_FB16_the_exact_boundary_survives_the_float_path(self):
        for g, expect in ((0.065, -100), (0.100, -200)):
            mean, _ = self.S.stop_jerk_window_mean([(10.0 - 0.0161290322580645 * i, g * G) for i in range(1)], 10.0)
            self.assertEqual(self.S.stop_jerk_points(self.S.stop_jerk_g_from_accel_z(mean)), expect)

    def test_FB17_bad_wire_values_are_none(self):
        import telemetry_contract as T
        for text in ("ACCELZ:nan", "ACCELZ:inf", "ACCELZ:-inf", "ACCELZ:abc", "ACCELZ:", "SPEED:1"):
            self.assertIsNone(T.accelz_capture([text]), text)
        self.assertEqual(T.accelz_capture(["SPEED:1", "ACCELZ:-0.512300"]), -0.5123)


# ===================================================================================================================================================
# C. the real overlay
# ===================================================================================================================================================
class Direct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        _profile_guard(cls)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["bveg"])
        import main
        import scoring_logic
        import sia_rig as R
        import managed_input
        import lc_legacy_feed as F
        cls.main, cls.S, cls.R, cls.MI, cls.F = main, scoring_logic, R, managed_input, F

    @classmethod
    def tearDownClass(cls):
        _profile_release(cls)

    def setUp(self):
        self.new_rig()

    def new_rig(self):
        if getattr(self, "rig", None) is not None:
            self.rig.close()
        self.rig = self.R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0
        return self.o

    def scene(self):
        R, o = self.R, self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        stations = []
        for name, loc, term in (("A", 0.0, False), ("B", 1000.0, False), ("C", 2500.0, True)):
            d = R.station(name, loc, terminal=term)
            d.update(def_time=-1, raw_dep=-1, stop_time=15000)
            stations.append(d)
        o.station_list = stations
        o.setting_end_idx = 2
        o.bve_next_loc = o.prev_next_loc = 1000.0
        o.bve_margin_b = o.bve_margin_f = 5.0
        o.has_departed = True
        o.is_first_station = False
        o.is_first_udp = False
        o.bve_time_ms = 36000000
        R.bind_identity(o)
        return o

    def step(self, dt=0.1, speed=None, az=None, loc=None, jump=None, official=None, same_time=False):
        o = self.o
        if not same_time:
            self.t += dt
            o.bve_time_ms += int(round(dt * 1000))
        if speed is not None:
            o.bve_speed = speed
        o.bve_accel_z = az                    # None = the line carried no ACCELZ
        if loc is not None:
            o.bve_location = loc
        if jump is not None:
            o.bve_jump_count = jump
        if official is not None:
            o.is_official_jumping = official
        self.S.update_physics_and_scoring(o, self.t, dt)

    def jerk(self):
        return [p["text"] for p in self.o.popups if p.get("category") == "停車時衝動"]

    def accelerate(self, n=20, az=0.8):
        for i in range(n):
            self.step(speed=5.0 + 0.3 * i, az=az, loc=100.0 + 0.6 * i)

    def brake(self, az, n=8, stop=True):
        """braking, then the stop tick; every tick carries the same AccelerationZ sample (m/s^2)."""
        for i in range(n):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), az=az)
        if stop:
            self.step(speed=0.0, az=az)

    def stop_with_bveg(self, g):
        """a whole stop whose 0.5 s window mean is exactly g (G): the samples are -g*9.80665 (braking = negative)."""
        self.new_rig()
        self.scene()
        self.accelerate(az=0.8)
        self.brake(az=-g * G)
        return self.o


class C_Judgement(Direct):
    def test_FB20_a_stop_is_judged_from_the_accelerationz_window_mean_not_the_last_sample(self):
        self.scene()
        self.accelerate()
        self.brake(az=-0.4, stop=False)
        self.step(speed=0.0, az=-2.0)                         # the instant value at the stop tick is 2.0 m/s2 = 0.204 G
        got = self.o.last_stop_g_bve
        self.assertLess(got, 1.5 / G)
        self.assertGreater(got, 0.3 / G)

    def test_FB21_RED_the_boundaries_decide_the_official_deduction_through_the_overlay(self):
        for g, expect in ((0.0649, 0), (0.065, -100), (0.0999, -100), (0.100, -200), (0.2, -200), (0.03, 0)):
            with self.subTest(bveg=g):
                o = self.stop_with_bveg(g)
                got = [int(re.search(r"-?\d+", t.split(" ")[-1]).group()) for t in self.jerk()]
                self.assertEqual(got, [expect] if expect else [], "OFFICIAL-DEDUCTION: BveG %s -> %r" % (g, self.jerk()))
                self.assertEqual(o.score_details.get("jerk", 0), expect)

    def test_FB22_RED_a_big_calcg_with_a_small_bveg_deducts_nothing(self):
        """CalcG (an old sender's CALCG part, speed difference) is above the first boundary, BveG is below: the official deduction is 0."""
        self.new_rig()
        self.scene()
        F = self.F
        self.o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, old_sender_calcg=-0.09, ACCELZ="-0.2"))
        self.assertFalse(hasattr(self.o, "bve_calc_g"), "RETIRED-SYMBOL: the CALCG part still feeds a value")
        self.accelerate(az=0.8)
        self.brake(az=-0.02 * G)
        self.assertEqual(self.jerk(), [], "OFFICIAL-DEDUCTION: BveG 0.02 G must not be deducted whatever a CALCG part says")

    def test_FB23_RED_a_small_calcg_with_a_big_bveg_follows_bveg(self):
        o = self.stop_with_bveg(0.12)
        self.assertEqual(len(self.jerk()), 1)
        self.assertIn("-200", self.jerk()[0])

    def test_FB24_no_double_deduction_and_the_score_detail_has_the_jerk_only(self):
        o = self.stop_with_bveg(0.15)
        self.assertEqual(len(self.jerk()), 1)
        self.assertEqual(o.score_details.get("jerk"), -200)

    def test_FB25_RED_no_sample_judges_nothing_and_nothing_is_substituted(self):
        self.scene()
        self.accelerate(az=None)
        self.brake(az=None)                                   # the line never carried ACCELZ
        self.assertIsNone(self.o.last_stop_g_bve, "FAKE-VALUE: LastStop BveG must be None, not 0.0 and not another value")
        self.assertEqual(self.jerk(), [], "UNAVAILABLE-CONTRACT: nothing is judged, so nothing is deducted")
        self.assertEqual(self.o.score_details.get("jerk", 0), 0)

    def test_FB26_one_sample_is_enough(self):
        self.scene()
        self.accelerate(az=None)
        self.brake(az=None, stop=False)
        self.step(speed=0.0, az=-1.2)
        self.assertAlmostEqual(self.o.last_stop_g_bve, 1.2 / G, places=6)

    def test_FB27_the_estimated_value_is_not_in_the_mean_a_missing_tick_adds_nothing(self):
        self.scene()
        self.accelerate(az=None)
        for i in range(4):
            self.step(speed=2.0 - 0.3 * i, az=-0.9 if i % 2 == 0 else None)       # every second tick has no sample: it must not enter the mean as a 0
        self.step(speed=0.0, az=-0.9)
        self.assertAlmostEqual(self.o.last_stop_g_bve, 0.9 / G, places=6)

    def test_FB28_backward_and_forward_stops_are_judged_by_the_absolute_value(self):
        for az in (-0.8, 0.8):
            with self.subTest(az=az):
                o = self.stop_with_bveg(0.0)
                self.new_rig()
                self.scene()
                self.accelerate(az=0.8)
                self.brake(az=az)
                self.assertAlmostEqual(self.o.last_stop_g_bve, 0.8 / G, places=6)

    def test_FB29_the_samples_of_a_judged_stop_are_not_reused(self):
        self.scene()
        self.accelerate()
        self.brake(az=-1.5)
        self.assertEqual(list(self.o.accel_z_history), [])

    def test_FB30_the_same_host_time_keeps_the_newest_sample(self):
        self.scene()
        self.step(speed=3.0, az=-0.2)
        self.step(speed=3.0, az=-0.9, same_time=True)
        self.assertEqual(len(self.o.accel_z_history), 1)
        self.assertEqual(self.o.accel_z_history[0][1], -0.9)

    def test_FB31_no_judgement_while_an_official_jump_is_pending(self):
        self.scene()
        self.accelerate()
        self.step(speed=0.0, az=-2.0, official=True)
        self.assertIsNone(self.o.last_stop_g_bve)
        self.assertEqual(self.jerk(), [])

    def test_FB32_a_discontinuity_of_the_speed_does_not_move_bveg(self):
        self.scene()
        self.accelerate()
        for _ in range(7):
            self.step(speed=29.0, az=0.0)
        self.step(speed=0.0, az=-0.0095)                      # a one-tick stop from 29 m/s: only the official value says what the body felt
        self.assertLess(self.o.last_stop_g_bve, 0.01)
        self.assertEqual(self.jerk(), [])

    def test_FB33_jump_then_a_new_stop_uses_only_the_new_samples(self):
        self.scene()
        self.accelerate()
        self.brake(az=-3.0, stop=False)
        self.step(speed=1.0, az=0.0, jump=1, official=True)
        self.step(speed=1.0, az=-0.05, official=False)
        self.step(speed=0.0, az=-0.05)
        self.assertIsNotNone(self.o.last_stop_g_bve)
        self.assertLess(self.o.last_stop_g_bve, 0.01)


class D_Boundaries(Direct):
    STATE_START = (False, "IDLE")

    def fill(self):
        self.scene()
        self.accelerate(5, az=0.8)
        self.assertGreater(len(self.o.accel_z_history), 0)

    def assertDiscarded(self, label):
        self.assertEqual(list(self.o.accel_z_history), [], "the buffer survived %s" % label)
        self.assertIsNone(self.o.last_stop_g_bve, "LastStop BveG survived %s" % label)
        self.assertEqual((self.o.is_stopping_zone, self.o.stop_notch_state), self.STATE_START)

    def test_FB40_a_new_generation_discards_the_buffer_and_the_last_value(self):
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.MI.discard_generation_state(self.o)
        self.assertDiscarded("a new generation")

    def test_FB41_f5_or_the_end_of_the_session_discards_it(self):
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.MI.discard_scoring_session(self.o)
        self.assertEqual(list(self.o.accel_z_history), [])
        self.assertIsNone(self.o.last_stop_g_bve)

    def test_FB42_a_jump_and_the_formal_discard_clear_everything(self):
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.step(speed=1.0, az=0.0, jump=1, official=True)
        self.assertDiscarded("a Jump")
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.S.reset_transient_scoring_state(self.o)
        self.assertDiscarded("the formal discard")

    def test_FB43_retry_and_the_scoring_start_use_the_formal_discard(self):
        self.assertGreaterEqual(code_py("scoring_logic.py").count("reset_transient_scoring_state(self)"), 4)
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.S.reset_transient_scoring_state(self.o)
        self.assertDiscarded("the Retry / start discard")

    def test_FB44_a_retry_does_not_bring_an_old_laststop_back(self):
        o = self.stop_with_bveg(0.12)
        self.assertIsNotNone(o.last_stop_g_bve)
        self.S.begin_official_jump(o, 100.0, 36000000)
        self.assertIsNone(o.last_stop_g_bve, "RETRY-RESTORE: the old LastStop BveG came back")
        self.assertEqual(list(o.accel_z_history), [])

    def test_FB45_the_checkpoint_and_the_result_keep_the_deduction_only(self):
        o = self.stop_with_bveg(0.08)
        self.assertEqual(o.score_details.get("jerk"), -100)
        text = json.dumps({"score": o.score, "details": o.score_details, "save": getattr(o, "save_data", [])}, ensure_ascii=False, default=str)
        for banned in ("calcg", "CalcG", "calc_g", "last_stop_g\"", "n_peak", "sway"):
            self.assertNotIn(banned, text)


class E_Wire(Direct):
    def test_FB50_current_and_legacy_lines_give_the_same_sample_and_the_same_deduction(self):
        F = self.F
        cur = F.line("current", 1, 36000000, 10.0, 100.0, ACCELZ="-0.51230")
        import sia_managed_rig as MR
        leg = MR.tele(1, time_ms=36000000, speed=10.0, loc=100.0, avail=F.LEGACY_AVAIL, ACCELZ="-0.51230")
        values = []
        for text in (cur, leg):
            self.new_rig()
            self.o.apply_telemetry_text(text)
            values.append(self.o.bve_accel_z)
        self.assertEqual(values, [-0.5123, -0.5123])

    def test_FB51_a_line_without_accelz_resets_the_value_and_a_bad_part_is_ignored(self):
        F = self.F
        self.o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, ACCELZ="-0.5"))
        self.assertEqual(self.o.bve_accel_z, -0.5)
        self.o.apply_telemetry_text(F.line("current", 1, 36000100, 10.0, 101.0, ACCELZ=None))
        self.assertIsNone(self.o.bve_accel_z)
        for bad in ("nan", "inf", "-inf", "abc", ""):
            self.o.apply_telemetry_text(F.line("current", 1, 36000200, 10.0, 102.0, ACCELZ=bad))
            self.assertIsNone(self.o.bve_accel_z, bad)

    def test_FB52_RED_a_retired_part_on_the_wire_is_ignored_and_feeds_nothing(self):
        F = self.F
        self.o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, old_sender_calcg=0.123, ACCELZ="-0.5"))
        for name in ("bve_calc_g", "bve_accel_x", "bve_sway", "bve_sway_res"):
            self.assertFalse(hasattr(self.o, name), "RETIRED-SYMBOL: %s still exists" % name)
        self.assertAlmostEqual(self.o.bve_accel_z, -0.5, places=9)


# ===================================================================================================================================================
# F. measured stops (SHD-L-03 and SHD-L-02): the expected deduction follows BveG only
# ===================================================================================================================================================
class F_MeasuredStops(Direct):
    CASES = (
        ("S03", 0.06871, 0.05589, 0),       # CalcG over the first boundary, BveG under it
        ("S06", 0.06701, 0.05501, 0),
        ("S10", 0.07460, 0.06209, 0),
        ("S02", 0.11087, 0.10774, -200),
        ("S08", 0.08650, 0.07409, -100),
        ("S16", 0.06878, 0.06875, -100),
        ("920T-Asakusa", 0.070, 0.057, 0),  # SHD-L-02 screen values (CalcG, BveG)
    )

    def test_FB60_the_measured_bveg_decides_the_deduction_and_the_measured_calcg_does_not(self):
        for name, calcg, bveg, expect in self.CASES:
            with self.subTest(stop=name):
                o = self.stop_with_bveg(bveg)
                got = [int(re.search(r"-?\d+", t.split(" ")[-1]).group()) for t in self.jerk()]
                self.assertEqual(got, [expect] if expect else [], "%s: CalcG %.5f BveG %.5f expected %d, got %r" % (name, calcg, bveg, expect, self.jerk()))

    def test_FB61_current_and_legacy_with_the_same_value_deduct_the_same(self):
        """both senders write the same ACCELZ part: the same scene through both wire shapes gives the same deduction."""
        F = self.F
        import sia_managed_rig as MR
        for g in (0.05589, 0.07409, 0.10774):
            results = []
            for shape in ("current", "legacy"):
                self.new_rig()
                self.scene()
                value = "%.6f" % (-g * G)
                if shape == "current":
                    text = F.line("current", 1, 36000000, 10.0, 100.0, ACCELZ=value)
                else:
                    text = MR.tele(1, time_ms=36000000, speed=10.0, loc=100.0, avail=F.LEGACY_AVAIL, ACCELZ=value)
                self.o.apply_telemetry_text(text)
                self.accelerate(az=0.8)
                self.brake(az=float(value))
                results.append((self.jerk(), round(self.o.last_stop_g_bve, 6)))
            self.assertEqual(results[0], results[1], "CURRENT-LEGACY: %r" % (results,))


# ===================================================================================================================================================
# G. F2 and the user text
# ===================================================================================================================================================
class G_Display(Direct):
    def f2(self):
        """the F2 texts drawn by draw_hud and the height of the background box"""
        from PyQt6.QtGui import QImage, QPainter
        import hud_ui
        texts, rects = [], []

        class Spy(QPainter):
            def drawText(self, *args):
                for a in args:
                    if isinstance(a, str):
                        texts.append(a)
                return super().drawText(*args)

            def drawRect(self, *args):
                rects.append(args)
                return super().drawRect(*args)

        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = Spy(image)
        try:
            self.o.show_graph = True
            hud_ui.draw_hud(self.o, painter, 1920)
        finally:
            painter.end()
        return texts, rects

    def test_FB70_RED_f2_shows_bveg_and_laststop_bveg_on_one_line(self):
        self.scene()
        self.o.bve_accel_z = 0.081 * G
        self.o.last_stop_g_bve = 0.070
        texts, _ = self.f2()
        self.assertIn("BveG: +0.081 G    LastStop BveG: 0.070 G", texts, "TWO-LINES-OR-OLD: the single F2 line is missing: %r" % [t for t in texts if "BveG" in t])
        self.assertEqual(len([t for t in texts if "BveG" in t]), 1, "TWO-LINES-OR-OLD: BveG and LastStop BveG must share ONE line")

    def test_FB71_unavailable_values_are_dashes_never_zero(self):
        self.scene()
        self.o.bve_accel_z = None
        self.o.last_stop_g_bve = None
        texts, _ = self.f2()
        self.assertIn("BveG: ---    LastStop BveG: ---", texts)
        joined = "\n".join(texts)
        self.assertNotIn("BveG: +0.000", joined)
        self.assertNotIn("LastStop BveG: 0.000", joined)

    def test_FB72_an_announced_gap_of_accelz_shows_dashes_even_when_a_value_is_there(self):
        self.scene()
        self.o.bve_accel_z = 0.5
        self.o.last_stop_g_bve = 0.07

        class Avail(object):
            def has(self, token):
                return token != "accelz"

            def item(self, key):
                return True

        class Gate(object):
            availability = Avail()

        self.o.telemetry_gate = Gate()
        texts, _ = self.f2()
        self.assertIn("BveG: ---    LastStop BveG: ---", texts)

    def test_FB73_RED_no_calcg_no_n_no_graph_no_maxg_no_reference_text(self):
        self.scene()
        self.o.bve_accel_z = 0.5
        self.o.last_stop_g_bve = 0.07
        texts, _ = self.f2()
        joined = "\n".join(texts)
        for banned in ("CalcG", "前後", "合成", "[参考]", "MaxG", "Decel G", "TELEMETRY", "ZONE1", "sway", "Sway"):
            self.assertNotIn(banned, joined, "OLD-F2: %r is still drawn" % banned)
        for line in texts:
            self.assertNotEqual(line.strip(), "", "EMPTY-LINE: an empty F2 line is drawn")

    def test_FB74_RED_the_box_is_two_lines_shorter_than_the_shadow_version(self):
        self.scene()
        self.o.bve_accel_z = 0.5
        texts, rects = self.f2()
        box = [r for r in rects if len(r) == 4 and r[2] == 950]
        self.assertEqual(len(box), 1, "the F2 background box")
        height = box[0][3]
        lines = len([t for t in texts if t])                   # only F2 text lines are drawn when no popup exists in this scene
        self.assertEqual(height, lines * 20 + 10, "the box height follows the real line count")
        self.assertEqual(lines, F2_LINES_IN_THIS_SCENE, "SHADOW-HEIGHT: the F2 line count of this scene is baseline - 2")

    def test_FB75_GUARD_the_right_edge_is_not_cut(self):
        from PyQt6.QtGui import QFont, QFontMetrics
        font = QFont("sans-serif", 14, QFont.Weight.Bold)
        fm = QFontMetrics(font)
        self.assertLess(20 + fm.horizontalAdvance("BveG: +0.000 G    LastStop BveG: 0.000 G"), 950)

    def test_FB76_GUARD_the_scoring_rules_text_coexists(self):
        self.scene()
        self.o.active_next_sta_name = "B"
        self.o.bve_accel_z = 0.5
        texts, _ = self.f2()
        self.assertTrue(any(t.startswith("[SCORING RULES]") for t in texts))
        self.assertIn("BveG: +0.051 G    LastStop BveG: ---", texts)


F2_LINES_IN_THIS_SCENE = 15  # measured in this scene; the baseline 86b7b6e draws 17 (CalcG/BveG row, LastStop row and the n row became ONE row)


class H_Text(Direct):
    def draw_row(self):
        from PyQt6.QtGui import QImage, QPainter
        import menu_ui
        plain = []
        orig_plain = menu_ui.draw_text_with_outline

        def rec_plain(painter, text, font, color, outline, x, y, *a, **k):
            plain.append((text, color, outline, x, y, font))
            return orig_plain(painter, text, font, color, outline, x, y, *a, **k)

        menu_ui.draw_text_with_outline = rec_plain
        self.addCleanup(setattr, menu_ui, "draw_text_with_outline", orig_plain)
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        o = self.o
        o.menu_state = 6
        o.menu_cursor = 3
        o.menu_cursor_x = -1
        o.menu_click_zones = []
        try:
            menu_ui.draw_menu(o, painter, 1920)
        finally:
            painter.end()
            menu_ui.draw_text_with_outline = orig_plain
        return plain

    def test_FB80_RED_the_user_text_is_the_formal_wording(self):
        import stop_jerk_text
        text = stop_jerk_text.stop_jerk_description_text()
        self.assertEqual(text, "【 停車時衝動 】\n"
                               "列車が完全に停止する際のショックの大きさを、停止直前の0.5秒におけるGの平均値により採点します。\n"
                               "（※0.065G≒2.3km/h/s以上で-100点、0.100G≒3.5km/h/s以上で-200点）")
        for needle in ("0.5秒", "0.065G", "2.3km/h/s", "0.100G", "3.5km/h/s"):
            self.assertIn(needle, text)

    def test_FB81_the_conversion_basis_is_the_one_of_the_contract(self):
        self.assertEqual(round(0.065 * 9.80665 * 3.6, 7), 2.2947561)
        self.assertEqual(round(0.100 * 9.80665 * 3.6, 6), 3.530394)
        self.assertEqual("%.1f" % (0.065 * 9.80665 * 3.6), "2.3")
        self.assertEqual("%.1f" % (0.100 * 9.80665 * 3.6), "3.5")

    def test_FB82_RED_the_description_is_plain_text_again_without_coloured_ranges(self):
        # 2026-11-08 Owner ruling: the coloured boundary ranges were hard to read; the description is the original white text with a black outline
        import stop_jerk_text, config
        lines = stop_jerk_text.STOP_JERK_DESCRIPTION_LINES
        self.assertEqual(len(lines), 3, "the number of lines is unchanged (title + 2)")
        self.assertTrue(all(isinstance(line, str) for line in lines), "plain lines, no (text, kind) spans")
        self.assertFalse(hasattr(stop_jerk_text, "span_colors"), "COLOUR: no span colour function")
        self.assertFalse(hasattr(config, "STOP_JERK_FIRST_BOUNDARY_COLOR") or hasattr(config, "STOP_JERK_SECOND_BOUNDARY_COLOR"), "COLOUR: no boundary colour constant")
        src = open(os.path.join(ROOT, "utils.py"), encoding="utf-8").read()
        self.assertNotIn("draw_text_spans_with_outline", src)

    def test_FB84_RED_the_menu_draws_the_three_lines_as_white_text_with_a_black_outline_and_keeps_the_line_pitch(self):
        import config, stop_jerk_text
        plain = self.draw_row()
        rows = [p for p in plain if p[0] in stop_jerk_text.STOP_JERK_DESCRIPTION_LINES]
        self.assertEqual([r[0] for r in rows], list(stop_jerk_text.STOP_JERK_DESCRIPTION_LINES), "the three lines are drawn, each as ONE plain line")
        for r in rows:
            self.assertEqual((r[1], r[2]), (config.COLOR_WHITE, config.COLOR_OUTLINE_BLACK), "white text, black outline")
        pitch = [rows[j][4] - rows[j - 1][4] for j in (1, 2)]
        self.assertEqual(pitch, [40, 40], "the line pitch of the description is unchanged")
        self.assertEqual(len({id(r[5]) for r in rows}), 1, "one font for the three lines")

    def test_FB85_GUARD_the_other_rows_are_still_drawn_as_plain_lines(self):
        import menu_ui
        self.assertIn("【 転動 】", "".join(open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8").read().split("\n")))


if __name__ == "__main__":
    unittest.main()
