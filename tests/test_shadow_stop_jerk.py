"""Shadow comparison (Stage 1) - the stop-jerk value of the OFFICIAL AccelerationZ (BveG) evaluated NEXT TO the CalcG value, as an executable contract (RED / GUARD).

THE CONTRACT (Owner, 2026-11-07)
  * The score, the history, the result and the checkpoints still follow the CalcG path ONLY. BveG changes nothing of them (RS38).
  * BveG = the official AccelerationZ (m/s^2, exactly as the sender wrote it) / 9.80665; LastStop(BveG) = |signed mean of the samples of the last 0.5 s| / 9.80665
    (both ends included, tolerance 1e-9, the same host time keeps the newest sample). No sample -> not evaluated; CalcG is never a substitute.
  * Its own buffer, discarded at every formal boundary together with the stop state. F2 shows four values and no MaxG.
Names: RS01..RS25 and RS30..RS43 are RED (they fail before the implementation, each for a declared reason code: the first word of the failure message);
       GS.. are GUARD (they pass before and after). Needs PyQt6 for the executable rows (skipped otherwise); the source rows need nothing.
"""
import importlib.util
import math
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
STOP_STATE_START = (False, 0.0, "IDLE")


def read(rel):
    with open(os.path.join(ROOT, rel.replace("/", os.sep)), "r", encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


def code_cs(rel):
    """C# source without the // comments (a name that only appears in a comment does not count)."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in read(rel).split("\n"))


def code_py(rel):
    return "\n".join(line for line in read(rel).split("\n") if not line.strip().startswith("#"))


def need(module, name, code):
    obj = getattr(module, name, None)
    if obj is None:
        raise AssertionError("%s: %s.%s does not exist yet" % (code, module.__name__, name))
    return obj


CLASS1 = "TsScoringPlugin/TsScoringPlugin/Class1.cs"
LEG_EXT = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs"
LEG_SES = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs"
LEG_API = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs"
CONTRACT_CS = "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs"


def _profile_guard(cls):
    cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-shadow-")
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
# source rows (no Qt)
# ===================================================================================================================================================
class A_Sources(unittest.TestCase):
    def test_RS01_current_reads_Vehicle_Vibration_AccelerationZ(self):
        if "vehicle.Vibration.AccelerationZ" not in code_cs(CLASS1):
            self.fail("CURRENT-NOT-OFFICIAL: Class1.cs does not read vehicle.Vibration.AccelerationZ in code")

    def test_RS02_legacy_reads_Vehicle_VibrationManager_AccelerationZ(self):
        if "current.Vehicle.VibrationManager.AccelerationZ" not in code_cs(LEG_EXT):
            self.fail("LEGACY-NOT-OFFICIAL: the Legacy extension does not read current.Vehicle.VibrationManager.AccelerationZ in code")

    def test_RS03_both_senders_write_the_same_key_in_the_same_unit(self):
        cur, ses = code_cs(CLASS1), code_cs(LEG_SES)
        if '",ACCELZ:"' not in cur or '"ACCELZ"' not in ses or 'TokAccelZ' not in ses:
            self.fail("SHARED-NO-TOKEN: both senders must write ACCELZ")
        for name, text, anchor in (("current", cur, '",ACCELZ:"'), ("legacy", ses, '"ACCELZ"')):
            i = text.index(anchor)
            around = text[max(0, i - 700):i + 300]
            for banned in ("9.80665", "GravityMps2", "Math.Abs", "Math.Min", "Math.Max", "Clamp", "currentG", "TokCalcG"):
                if banned in around:
                    self.fail("SENDER-CONVERTS: %s ACCELZ is not the raw m/s2 value (%s near it)" % (name, banned))
            if "F6" not in around:
                self.fail("SHARED-NO-TOKEN: %s ACCELZ is not written with F6" % name)

    def test_RS03b_legacy_accelz_needs_no_previous_sample(self):
        ses = code_cs(LEG_SES)
        if "ILegacyVibrationApi vibration" not in ses or "TokAccelZ" not in ses:
            self.fail("SHARED-NO-TOKEN: the Legacy session does not write ACCELZ")
        block = ses[ses.index("ILegacyVibrationApi vibration"):ses.index("TokAccelZ") + 120]
        if "haveLastSample" in block:
            self.fail("SHARED-NO-TOKEN: the Legacy ACCELZ must not wait for a previous sample (CALCG does, ACCELZ does not)")
        if "IsNaN" not in block or "IsInfinity" not in block:
            self.fail("SHARED-NO-TOKEN: the Legacy ACCELZ must be written only for a finite value")

    def test_RS40_max_stop_g_is_gone_from_the_state_and_the_hud(self):
        for rel in ("main.py", "managed_input.py", "hud_ui.py", "scoring_logic.py"):
            if "max_stop_g" in code_py(rel) or "MaxG" in code_py(rel):
                self.fail("OLD-F2: %s still carries max_stop_g / MaxG" % rel)

    def test_RS42_wire_contract_has_the_accelz_token(self):
        import telemetry_contract as T
        if T.TOKEN_KEYS.get("accelz") != ("ACCELZ",):
            self.fail("NO-WIRE-TOKEN: TOKEN_KEYS['accelz'] != ('ACCELZ',)")
        if 'TokAccelZ = "accelz"' not in code_cs(CONTRACT_CS):
            self.fail("NO-WIRE-TOKEN: TelemetryContract.cs has no TokAccelZ")
        if "interface ILegacyVibrationApi" not in code_cs(LEG_API) or "TryAccelerationZ" not in code_cs(LEG_EXT):
            self.fail("NO-WIRE-TOKEN: the Legacy vibration api is not there")

    def test_GS_legacy_api_interface_is_unchanged(self):
        """GUARD: ILegacyApi keeps its members (the new reading is a separate interface)."""
        text = code_cs(LEG_API)
        body = text[text.index("interface ILegacyApi"):]
        body = body[:body.index("}")]
        self.assertNotIn("AccelerationZ", body)
        self.assertIn("TryScenarioMeta", body)


# ===================================================================================================================================================
# pure functions and the wire (needs scoring_logic / telemetry_contract; Qt is only needed to import the overlay)
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

    def mean(self, history, t, window=None):
        f = need(self.S, "stop_jerk_window_mean", "NO-PURE-FUNCTION")
        return f(history, t) if window is None else f(history, t, window)

    def gof(self, mps2):
        return need(self.S, "stop_jerk_g_from_accel_z", "NO-PURE-FUNCTION")(mps2)

    def pts(self, g):
        return need(self.S, "stop_jerk_points", "NO-PURE-FUNCTION")(g)

    def test_RS04_the_window_includes_both_ends(self):
        history = [(9.49, 100.0), (9.50, 1.0), (9.75, 2.0), (10.0, 3.0), (10.01, 100.0)]
        mean, count = self.mean(history, 10.0)
        self.assertEqual(count, 3, "NO-PURE-FUNCTION: the ends T-0.5 and T must be included, 9.49 and 10.01 must not")
        self.assertAlmostEqual(mean, 2.0, places=9)

    def test_RS05_samples_outside_the_window_are_not_used(self):
        mean, count = self.mean([(8.0, 5.0), (9.0, 5.0)], 10.0)
        self.assertEqual((mean, count), (None, 0), "NO-PURE-FUNCTION: only outside samples -> not evaluated")

    def test_RS06_signed_samples_are_averaged_before_the_abs(self):
        mean, _ = self.mean([(9.6, 2.0), (9.8, -2.0), (10.0, 2.0), (9.7, -2.0)], 10.0)
        self.assertAlmostEqual(self.gof(mean), 0.0, places=9, msg="NO-PURE-FUNCTION: +2 and -2 must cancel before abs")

    def test_RS07_a_per_sample_abs_is_detected(self):
        mean, _ = self.mean([(9.7, 2.0), (10.0, -0.5)], 10.0)
        self.assertAlmostEqual(self.gof(mean), 0.75 / G, places=9, msg="NO-PURE-FUNCTION: |mean| = 0.75 m/s2, not mean(|x|) = 1.25")

    def test_RS08_g_conversion_uses_9_80665(self):
        self.assertAlmostEqual(self.gof(G), 1.0, places=12, msg="NO-PURE-FUNCTION: 9.80665 m/s2 must be 1 G")
        self.assertAlmostEqual(self.gof(-G), 1.0, places=12, msg="NO-PURE-FUNCTION: the absolute value is taken")

    def test_RS09_to_RS13_threshold_boundaries(self):
        self.assertEqual(self.pts(0.065), -100, "NO-PURE-FUNCTION: 0.065 G is -100")
        self.assertEqual(self.pts(0.065 - 5e-10), -100, "NO-PURE-FUNCTION: tolerance 1e-9 below 0.065")
        self.assertEqual(self.pts(0.065 - 2e-9), 0, "NO-PURE-FUNCTION: 2e-9 below 0.065 is 0")
        self.assertEqual(self.pts(0.100), -200, "NO-PURE-FUNCTION: 0.100 G is -200")
        self.assertEqual(self.pts(0.100 - 5e-10), -200)
        self.assertEqual(self.pts(0.100 - 2e-9), -100)
        self.assertEqual(self.pts(0.0), 0)

    def test_RS13b_the_exact_boundary_survives_the_float_path(self):
        """A window mean of 31 float samples that is exactly 0.065 G must still be -100 (and 0.100 G -200)."""
        for g, expect in ((0.065, -100), (0.100, -200)):
            values = [g * G] * 31
            mean, _ = self.mean([(10.0 - 0.0161290322580645 * i, v) for i, v in enumerate(values)], 10.0)
            self.assertEqual(self.pts(self.gof(mean)), expect, "NO-PURE-FUNCTION: float path lost the boundary %s" % g)

    def test_RS14_there_is_no_minus_300(self):
        for g in (0.065, 0.1, 0.5, 5.0):
            self.assertIn(self.pts(g), (0, -100, -200), "NO-PURE-FUNCTION: a single step only")

    def test_RS14b_bad_wire_values_are_none(self):
        import telemetry_contract as T
        capture = need(T, "accelz_capture", "NO-WIRE-TOKEN")
        for text in ("ACCELZ:nan", "ACCELZ:inf", "ACCELZ:-inf", "ACCELZ:abc", "ACCELZ:", "SPEED:1"):
            self.assertIsNone(capture([text]), "NO-WIRE-TOKEN: %r must be None" % text)
        self.assertEqual(capture(["SPEED:1", "ACCELZ:-0.512300"]), -0.5123)


# ===================================================================================================================================================
# the real Overlay (needs PyQt6)
# ===================================================================================================================================================
class Direct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        _profile_guard(cls)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["shadow"])
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

    def step(self, dt=0.1, speed=None, calc_g=None, az=None, loc=None, jump=None, official=None, same_time=False):
        o = self.o
        if not same_time:
            self.t += dt
            o.bve_time_ms += int(round(dt * 1000))
        if speed is not None:
            o.bve_speed = speed
        if calc_g is not None:
            o.bve_calc_g = calc_g
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

    def accelerate(self, n=20, g=0.08, az=0.8):
        for i in range(n):
            self.step(speed=5.0 + 0.3 * i, calc_g=g, az=az, loc=100.0 + 0.6 * i)

    def brake(self, calc_g, az, n=8, stop=True):
        for i in range(n):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=calc_g, az=az)
        if stop:
            self.step(speed=0.0, calc_g=calc_g, az=az)

    def history(self):
        return getattr(self.o, "accel_z_history", None)

    def need_state(self):
        if not hasattr(self.o, "accel_z_history") or not hasattr(self.o, "last_stop_g_bve"):
            self.fail("NO-SAMPLE-STATE: the overlay has no accel_z_history / last_stop_g_bve")

    def want(self, lines, text):
        if text not in lines:
            self.fail("OLD-F2: %r is not in the F2 text %r" % (text, [l for l in lines if "CalcG" in l or "BveG" in l or "LastStop" in l]))


class C_Shadow(Direct):
    # ---- the judgement ------------------------------------------------------------------------------------------------------------------------
    def test_RS06b_the_stop_is_judged_from_the_window_mean_not_the_last_sample(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.02, az=-0.4, stop=False)
        self.step(speed=0.0, calc_g=-0.02, az=-2.0)            # the instant value at the stop tick is 2.0 m/s2 = 0.204 G
        self.need_state()
        got = self.o.last_stop_g_bve
        self.assertLess(got, 1.5 / G, "NO-SHADOW: the judgement used the instant value of the stop tick, not the 0.5 s window mean")
        self.assertGreater(got, 0.3 / G, "NO-SHADOW: the window mean must contain the earlier samples and the stop sample")

    def test_RS09b_a_stop_is_judged_from_the_accelerationz_window(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.02, az=-0.9)          # CalcG is calm, the official value brakes at 0.9 m/s2 = 0.0918 G
        self.need_state()
        if self.o.last_stop_g_bve is None:
            self.fail("NO-SHADOW: the stop was not evaluated for BveG")
        self.assertAlmostEqual(self.o.last_stop_g_bve, 0.9 / G, places=6, msg="NO-SHADOW: LastStop(BveG) = |mean|/9.80665")
        self.assertEqual(self.jerk(), [], "the official score follows CalcG (0.02 G): no deduction")

    def test_RS14c_no_double_deduction_through_the_overlay(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.15, az=-1.5)
        self.need_state()
        self.assertEqual(len(self.jerk()), 1, "one deduction only")
        self.assertIn("-200", self.jerk()[0])
        self.assertEqual(self.o.score_details.get("jerk"), -200)

    def test_RS15_no_sample_means_not_evaluated_and_no_calcg_fallback(self):
        self.scene()
        self.accelerate(az=None)
        self.brake(calc_g=-0.30, az=None)            # CalcG says 0.30 G, the line never carried ACCELZ
        self.need_state()
        self.assertIsNone(self.o.last_stop_g_bve, "NO-SAMPLE-STATE: BveG must be unavailable, not the CalcG value")
        self.assertEqual(len(self.jerk()), 1, "the official CalcG score is unchanged")

    def test_RS16_one_sample_is_enough(self):
        self.scene()
        self.accelerate(az=None)
        self.brake(calc_g=-0.02, az=None, stop=False)
        self.step(speed=0.0, calc_g=-0.02, az=-1.2)
        self.need_state()
        self.assertAlmostEqual(self.o.last_stop_g_bve, 1.2 / G, places=6, msg="NO-SAMPLE-STATE: one sample judges")

    # ---- the buffer boundaries ------------------------------------------------------------------------------------------------------------------
    def fill(self):
        self.scene()
        self.accelerate(5, az=0.8)
        self.need_state()
        self.assertGreater(len(self.history()), 0, "NO-SAMPLE-STATE: the samples must be kept")

    def assertDiscarded(self, label):
        self.assertEqual(list(self.history()), [], "NO-SAMPLE-STATE: the BveG buffer survived %s" % label)
        self.assertIsNone(self.o.last_stop_g_bve, "NO-SAMPLE-STATE: the last BveG value survived %s" % label)
        self.assertEqual((self.o.is_stopping_zone, self.o.last_stop_g, self.o.stop_notch_state), STOP_STATE_START, "the stop state survived %s" % label)

    def test_RS17_a_new_scenario_generation_discards_the_buffer(self):
        self.fill()
        self.MI.discard_generation_state(self.o)
        self.assertDiscarded("a new generation")

    def test_RS18_f5_or_the_end_of_the_session_discards_the_buffer(self):
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.MI.discard_scoring_session(self.o)
        self.assertEqual(list(self.history()), [], "NO-SAMPLE-STATE: the buffer survived the session end")
        self.assertIsNone(self.o.last_stop_g_bve)

    def test_RS19_a_jump_and_time_going_backwards_discard_the_buffer(self):
        self.fill()
        self.step(speed=1.0, calc_g=0.0, az=0.0, jump=1, official=True)       # a Jump: the BVE jump counter moved
        self.assertDiscarded("a Jump")
        self.fill()
        self.o.last_stop_g_bve = 0.07
        self.S.reset_transient_scoring_state(self.o)                           # the formal discard used by every boundary
        self.assertDiscarded("the formal discard")

    def test_RS20_retry_and_scoring_start_use_the_formal_discard(self):
        """Retry (begin_official_jump) and the scoring start go through reset_transient_scoring_state: every call site still exists."""
        sites = code_py("scoring_logic.py").count("reset_transient_scoring_state(self)")
        self.assertGreaterEqual(sites, 4, "the definition and the three formal call sites")
        self.fill()
        self.S.reset_transient_scoring_state(self.o)
        self.assertDiscarded("the Retry / start discard")

    def test_RS21_samples_before_the_scoring_started_are_not_kept(self):
        self.new_rig()
        o = self.scene()
        o.is_scoring_mode = False
        self.accelerate(5, az=0.8)
        self.need_state()
        self.S.reset_transient_scoring_state(o)
        self.assertDiscarded("the scoring start")

    def test_RS22_the_samples_of_a_judged_stop_are_not_reused(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.02, az=-1.5)
        self.need_state()
        self.assertEqual(list(self.history()), [], "NO-SAMPLE-STATE: a judged stop must consume its samples (no reuse at the next stop)")

    def test_RS23_the_same_host_time_keeps_the_newest_sample(self):
        self.scene()
        self.step(speed=3.0, calc_g=0.0, az=-0.2)
        self.step(speed=3.0, calc_g=0.0, az=-0.9, same_time=True)
        self.need_state()
        history = self.history()
        self.assertEqual(len(history), 1, "NO-SAMPLE-STATE: the same host time must not accumulate")
        self.assertEqual(history[0][1], -0.9, "NO-SAMPLE-STATE: the newest value replaces the older one")

    def test_RS23b_a_sample_after_the_stop_instant_is_not_in_the_window(self):
        f = need(self.S, "stop_jerk_window_mean", "NO-PURE-FUNCTION")
        mean, count = f([(9.9, -1.0), (10.0, -1.0), (10.1, 9.0)], 10.0)
        self.assertEqual(count, 2, "NO-PURE-FUNCTION: a sample after T is not part of the window")

    def test_RS25_a_discontinuity_moves_calcg_but_not_bveg(self):
        self.scene()
        self.accelerate()
        for _ in range(7):
            self.step(speed=29.0, calc_g=0.0, az=0.0)
        self.step(speed=0.0, calc_g=-52.0, az=-0.0095)              # a 1-tick stop from 29 m/s: the speed difference says -52 G, the official value does not
        self.need_state()
        self.assertLess(self.o.last_stop_g_bve, 0.01, "NO-SHADOW: the official value must not follow the speed jump")
        self.assertGreater(abs(self.o.last_stop_g), 1.0, "CalcG keeps its (old) behaviour")

    def test_RS36_no_judgement_while_an_official_jump_is_pending(self):
        self.scene()
        self.accelerate()
        self.need_state()
        self.step(speed=0.0, calc_g=-0.2, az=-2.0, official=True)
        self.assertIsNone(self.o.last_stop_g_bve, "NO-SHADOW: is_official_jumping must also stop the BveG judgement")
        self.assertEqual(self.jerk(), [])

    def test_RS37_the_boundary_discard_clears_the_shadow_value_with_the_stop_state(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.02, az=-1.5)
        self.need_state()
        self.assertIsNotNone(self.o.last_stop_g_bve)
        self.S.reset_transient_scoring_state(self.o)
        self.assertIsNone(self.o.last_stop_g_bve, "NO-SAMPLE-STATE")
        self.assertEqual((self.o.is_stopping_zone, self.o.last_stop_g, self.o.stop_notch_state), STOP_STATE_START)

    # ---- the score is not touched (RS38 / MS03) -------------------------------------------------------------------------------------------------
    def run_scene(self, az_accel, az_brake, calc_brake=-0.09):
        self.new_rig()
        self.scene()
        self.accelerate(az=az_accel)
        self.brake(calc_g=calc_brake, az=az_brake)
        for _ in range(5):
            self.step(speed=0.0, calc_g=0.0, az=az_brake)
        o = self.o
        state = self.F.snapshot(o)
        state["g_history"] = [h[:2] for h in o.g_history]
        state["hb"] = o.hb_cushion_max_g
        return state

    def test_RS38_the_score_does_not_change_when_only_bveg_changes(self):
        self.need_state() if hasattr(self.o, "accel_z_history") else None
        reference = self.run_scene(None, None)
        for label, a, b in (("calm", 0.5, -0.1), ("hard", 0.8, -3.0), ("opposite sign", -2.0, 2.5), ("zero", 0.0, 0.0)):
            with self.subTest(bveg=label):
                state = self.run_scene(a, b)
                if not hasattr(self.o, "accel_z_history"):
                    self.fail("NO-SAMPLE-STATE: nothing to compare yet")
                self.assertEqual(self.F.differences(reference, state), [], "SHADOW-LEAKS: BveG changed %s" % self.F.differences(reference, state))
                self.assertEqual(reference["g_history"], state["g_history"], "SHADOW-LEAKS: g_history")
                self.assertEqual(reference["hb"], state["hb"], "SHADOW-LEAKS: hb_cushion_max_g")

    def test_RS38b_calcg_decides_the_official_score_and_bveg_the_shadow_only(self):
        self.need_state()
        a = self.run_scene(0.8, -0.2, calc_brake=-0.09)     # CalcG 0.09 G (-100), BveG 0.02 G (shadow 0)
        shadow_a = self.o.last_stop_g_bve
        b = self.run_scene(0.8, -2.0, calc_brake=-0.02)     # CalcG 0.02 G (0),    BveG 0.2 G (shadow -200)
        shadow_b = self.o.last_stop_g_bve
        if shadow_a is None or shadow_b is None:
            self.fail("NO-SHADOW: the shadow value is missing")
        self.assertEqual(len([p for p in a["popups"] if p[0] == "停車時衝動"]), 1, "CalcG 0.09 G is deducted")
        self.assertEqual(len([p for p in b["popups"] if p[0] == "停車時衝動"]), 0, "CalcG 0.02 G is not deducted although BveG is 0.2 G")
        self.assertLess(shadow_a, 0.065)
        self.assertGreaterEqual(shadow_b, 0.1)

    # ---- the wire into the overlay ---------------------------------------------------------------------------------------------------------------
    def test_RS24_current_and_legacy_lines_give_the_same_sample(self):
        F = self.F
        cur = F.line("current", 1, 36000000, 10.0, 100.0, ACCELZ="-0.51230")
        import sia_managed_rig as MR
        leg = MR.tele(1, time_ms=36000000, speed=10.0, loc=100.0, avail=F.LEGACY_AVAIL + ["accelz"], ACCELZ="-0.51230")
        values = []
        for text in (cur, leg):
            self.new_rig()
            self.o.apply_telemetry_text(text)
            values.append(getattr(self.o, "bve_accel_z", "missing"))
        if values[0] == "missing":
            self.fail("NO-SAMPLE-STATE: bve_accel_z does not exist yet")
        self.assertEqual(values, [-0.5123, -0.5123], "NO-SAMPLE-STATE: both shapes must give the same sample")

    def test_RS24b_a_line_without_accelz_resets_the_value(self):
        F = self.F
        self.o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, ACCELZ="-0.5"))
        if not hasattr(self.o, "bve_accel_z") or self.o.bve_accel_z is None:
            self.fail("NO-SAMPLE-STATE: ACCELZ was not taken")
        self.o.apply_telemetry_text(F.line("current", 1, 36000100, 10.0, 101.0))
        self.assertIsNone(self.o.bve_accel_z, "NO-SAMPLE-STATE: an old value must not stay")

    def test_RS14d_a_bad_accelz_part_on_the_wire_is_ignored(self):
        F = self.F
        for bad in ("nan", "inf", "-inf", "abc", ""):
            self.o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, ACCELZ=bad))
            self.assertIsNone(getattr(self.o, "bve_accel_z", "missing") if hasattr(self.o, "bve_accel_z") else None, "NO-SAMPLE-STATE: %r" % bad)
        if not hasattr(self.o, "bve_accel_z"):
            self.fail("NO-SAMPLE-STATE: bve_accel_z does not exist yet")

    def test_RS32_calcg_and_bveg_have_separate_owners(self):
        F = self.F
        self.o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, calcg=0.123, ACCELZ="-0.5"))
        if not hasattr(self.o, "bve_accel_z"):
            self.fail("NO-SAMPLE-STATE: bve_accel_z does not exist yet")
        self.assertAlmostEqual(self.o.bve_calc_g, 0.123, places=6, msg="CALCG feeds bve_calc_g only")
        self.assertAlmostEqual(self.o.bve_accel_z, -0.5, places=9, msg="ACCELZ feeds bve_accel_z only")
        self.o.apply_telemetry_text(F.line("current", 1, 36000100, 10.0, 101.0, calcg=-0.2))
        self.assertAlmostEqual(self.o.bve_calc_g, -0.2, places=6)
        self.assertIsNone(self.o.bve_accel_z)
        self.o.apply_telemetry_text(F.line("legacy", 1, 36000200, 10.0, 102.0, discontinuity=True, ACCELZ="-0.7"))      # a Legacy line without CALCG
        self.assertNotAlmostEqual(self.o.bve_calc_g, -0.7, places=6, msg="SHADOW-LEAKS: a line with ACCELZ and without CALCG must not feed bve_calc_g from the official value")
        self.assertAlmostEqual(self.o.bve_accel_z, -0.7, places=9)

    # ---- the F2 text ---------------------------------------------------------------------------------------------------------------------------------
    def f2_texts(self):
        from PyQt6.QtGui import QImage, QPainter
        import hud_ui
        texts = []

        class Spy(QPainter):
            def drawText(self, *args):
                for a in args:
                    if isinstance(a, str):
                        texts.append(a)
                return super().drawText(*args)

        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = Spy(image)
        try:
            self.o.show_graph = True
            hud_ui.draw_hud(self.o, painter, 1920)
        finally:
            painter.end()
        return texts

    def test_RS35_an_announced_gap_of_accelz_shows_dashes_even_when_a_value_is_there(self):
        self.scene()
        self.o.bve_calc_g = 0.086
        self.o.bve_accel_z = 0.5
        class Avail(object):                                                           # the sender announced that it cannot provide the group "accelz"
            def has(self, token):
                return token != "accelz"

            def item(self, key):
                return True

        class Gate(object):
            availability = Avail()

        self.o.telemetry_gate = Gate()
        lines = self.f2_texts()
        self.want(lines, "CalcG: +0.086 G    BveG: --")

    def test_RS30_f2_has_no_maxg(self):
        self.scene()
        joined = "\n".join(self.f2_texts())
        if "MaxG" in joined:
            self.fail("OLD-F2: the F2 text still shows MaxG")
        self.assertIn("CalcG", joined, "the F2 text is drawn")

    def test_RS31_f2_shows_the_four_values_in_two_lines(self):
        self.scene()
        self.o.bve_calc_g = 0.086
        self.o.bve_accel_z = 0.081 * G
        self.o.last_stop_g = -0.074               # signed (braking positive in the old path may be negative): shown as an absolute value
        self.o.last_stop_g_bve = 0.070
        lines = self.f2_texts()
        if not any("BveG" in t for t in lines):
            self.fail("OLD-F2: no BveG in the F2 text")
        self.want(lines, "CalcG: +0.086 G    BveG: +0.081 G")
        self.want(lines, "LastStop CalcG: 0.074 G    LastStop BveG: 0.070 G")

    def test_RS31b_unavailable_bveg_is_shown_as_dashes_never_as_calcg(self):
        self.scene()
        self.o.bve_calc_g = 0.086
        self.o.bve_accel_z = None
        self.o.last_stop_g = 0.074
        self.o.last_stop_g_bve = None
        lines = self.f2_texts()
        self.want(lines, "CalcG: +0.086 G    BveG: --")
        self.want(lines, "LastStop CalcG: 0.074 G    LastStop BveG: --")

    def test_RS33_the_two_laststop_values_are_independent(self):
        self.scene()
        self.o.bve_calc_g = 0.0
        self.o.last_stop_g = 0.0
        self.o.last_stop_g_bve = 0.123
        lines = self.f2_texts()
        self.want(lines, "LastStop CalcG: 0.000 G    LastStop BveG: 0.123 G")

    def test_RS34_laststop_is_shown_as_an_absolute_value(self):
        self.scene()
        self.o.last_stop_g = -0.2
        self.o.last_stop_g_bve = 0.1
        lines = self.f2_texts()
        self.want(lines, "LastStop CalcG: 0.200 G    LastStop BveG: 0.100 G")
        self.assertNotIn("LastStop CalcG: -", "\n".join(lines), "OLD-F2: LastStop must be shown as an absolute value")

    # ---- the diagnostic log ----------------------------------------------------------------------------------------------------------------------------
    def capture_log(self, enabled):
        import scoring_logic
        lines = []
        saved = (scoring_logic.write_desktop_log, scoring_logic.desktop_log_enabled)
        scoring_logic.write_desktop_log = lambda msg: lines.append(msg)
        scoring_logic.desktop_log_enabled = lambda: enabled
        self.addCleanup(lambda: setattr(scoring_logic, "write_desktop_log", saved[0]))
        self.addCleanup(lambda: setattr(scoring_logic, "desktop_log_enabled", saved[1]))
        return lines

    def test_RS39_one_log_line_per_judged_stop(self):
        lines = self.capture_log(True)
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.09, az=-0.9)
        for _ in range(4):
            self.step(speed=0.0, calc_g=0.0, az=0.0)
        shadow = [l for l in lines if "[SHADOW STOP]" in l]
        if not shadow:
            self.fail("NO-SHADOW: no diagnostic line for the judged stop")
        self.assertEqual(len(shadow), 1)
        for key in ("station_index=", "target_station_index=", "host_time=", "window_start=", "window_end=", "calcg_samples=", "bveg_samples=", "last_stop_calcg=",
                    "last_stop_bveg=", "calcg_penalty=", "bveg_shadow_penalty=", "is_official_jumping=", "scenario_generation="):
            self.assertIn(key, shadow[0])

    def test_RS39b_no_sample_logs_unavailable_and_not_evaluated(self):
        lines = self.capture_log(True)
        self.scene()
        self.accelerate(az=None)
        self.brake(calc_g=-0.09, az=None)
        shadow = [l for l in lines if "[SHADOW STOP]" in l]
        if not shadow:
            self.fail("NO-SHADOW: no diagnostic line")
        self.assertIn("last_stop_bveg=unavailable", shadow[0])
        self.assertIn("bveg_shadow_penalty=not-evaluated", shadow[0])
        self.assertIn("bveg_samples=0", shadow[0])

    def test_RS39c_nothing_is_written_when_the_desktop_log_is_off(self):
        lines_on = self.capture_log(True)
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.09, az=-0.9)
        if not [l for l in lines_on if "[SHADOW STOP]" in l]:
            self.fail("NO-SHADOW: the enabled log has no line (the switch cannot be judged)")
        self.new_rig()
        lines_off = self.capture_log(False)
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.09, az=-0.9)
        self.assertEqual([l for l in lines_off if "[SHADOW STOP]" in l], [])

    # ---- integration -------------------------------------------------------------------------------------------------------------------------------------
    def test_RS41_jump_then_a_new_stop_uses_only_the_new_samples(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.02, az=-3.0, stop=False)                 # a hard window right before the Jump
        self.step(speed=1.0, calc_g=0.0, az=0.0, jump=1, official=True)
        self.step(speed=1.0, calc_g=0.0, az=-0.05, official=False)
        self.step(speed=0.0, calc_g=0.0, az=-0.05)
        self.need_state()
        self.assertIsNotNone(self.o.last_stop_g_bve)
        self.assertLess(self.o.last_stop_g_bve, 0.01, "NO-SAMPLE-STATE: the hard window before the Jump leaked across it")

    def test_GS43_package_manifest_lists_the_changed_files(self):
        """RS43 by number; a GUARD by nature (the manifest lists these files before and after the change). The package guard itself is run by the regression (source_package.py)."""
        import json
        manifest = json.loads(read("package/source-package-manifest.json"))
        paths = {entry["path"] for entry in manifest["files"]}
        for rel in ("telemetry_contract.py", "main.py", "scoring_logic.py", "managed_input.py", "hud_ui.py", CLASS1, LEG_API, LEG_EXT, LEG_SES, CONTRACT_CS):
            self.assertIn(rel, paths)


# ===================================================================================================================================================
# GUARD (pass before and after)
# ===================================================================================================================================================
class G_Guards(Direct):
    def test_GS01_the_official_score_follows_calcg(self):
        self.scene()
        self.accelerate()
        self.brake(calc_g=-0.09, az=None)
        self.assertEqual(len(self.jerk()), 1)
        self.assertIn("-100", self.jerk()[0])

    def test_GS01b_the_scoring_function_reads_the_calcg_history(self):
        text = code_py("scoring_logic.py")
        body = text[text.index("def update_stop_jerk_penalty"):]
        body = body[:body.index("\ndef ")]
        self.assertIn("self.g_history", body)
        self.assertIn("decel_g", body)

    def test_GS02_the_graph_stays_off_and_hb_cushion_follows_calcg(self):
        import hud_ui
        self.assertFalse(hud_ui.G_GRAPH_ENABLED)
        self.assertIn("hb_cushion_max_g", code_py("scoring_logic.py"))
        self.assertIn("decel_g > self.hb_cushion_max_g", code_py("scoring_logic.py"))

    def test_GS03_p95_does_not_exist(self):
        for rel in ("hud_ui.py", "scoring_logic.py", "main.py", "managed_input.py", "telemetry_contract.py"):
            self.assertNotRegex(code_py(rel), r"(?i)\bp95\b")

    def test_GS_the_calcg_path_is_still_parsed(self):
        self.assertIn('part.startswith("CALCG:")', code_py("main.py"))
        self.assertIn('"calcg": ("CALCG",)', code_py("telemetry_contract.py"))

    def test_GS_ljx1_part_chain_is_not_touched(self):
        """The ACCELZ capture is a statement of its own (outside the elif chain of the other parts)."""
        text = code_py("main.py")
        self.assertNotIn('elif part.startswith("ACCELZ:")', text)

    def test_GS_the_retry_jump_f5_sites_still_exist(self):
        self.assertGreaterEqual(code_py("scoring_logic.py").count("reset_transient_scoring_state(self)"), 4)
        self.assertIn("def discard_scoring_session", code_py("managed_input.py"))
        self.assertIn("def discard_generation_state", code_py("managed_input.py"))


if __name__ == "__main__":
    unittest.main()
