"""Shadow sway diagnostics (S1) - the BVE passenger-sway figure ("乗客の揺れ") as DIAGNOSTIC-ONLY Shadow values, as an executable contract (RED / GUARD).

THE CONTRACT (Owner rulings CI-6..CI-12 and DR-1..DR-10, 2026-11-07)
  * The official score, the history, the checkpoints and the result still follow the CalcG path ONLY. Nothing here changes them (SG01, SW_T20).
  * The main Shadow value is the BVE internal LONGITUDINAL state (x + 0.315 v of the spring the figure keeps; read by reflection in C#, delivered raw as SWAY).
    nZ = int(12.5 * abs(state) * 64.0)  (the same order of operations as the figure's colour code). The combined value (longitudinal + lateral) is REFERENCE ONLY.
  * The stop window starts at the stop instant T and ends at the earliest of T+1.0 s / restart / target change / StationIndex change / Jump / Retry / F5 /
    generation / scoring end / session end. The main value is the absolute value of the MINIMUM (negative) state from T on.
  * The public-API replica (ACCELZ + ACCELX through the same spring model) is kept SEPARATE from the reflection value and only compared.
Names: test_SW* are RED (they fail on the pristine isolated HEAD for a declared reason code: the first word of the failure message);
       test_SG* are GUARD (they pass before and after). Needs PyQt6 for the executable rows (skipped otherwise); the source rows need nothing.
"""
import importlib.util
import math
import os
import re
import subprocess
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


def need(module, name, code):
    obj = getattr(module, name, None)
    if obj is None:
        raise AssertionError("%s: %s.%s does not exist yet" % (code, module.__name__, name))
    return obj


def import_sway(code="NO-PURE"):
    try:
        import sway_shadow
    except ImportError:
        raise AssertionError("%s: the module sway_shadow does not exist yet" % code)
    return sway_shadow


CLASS1 = "TsScoringPlugin/TsScoringPlugin/Class1.cs"
CUR_CSPROJ = "TsScoringPlugin/TsScoringPlugin/TsScoringPlugin.csproj"
LEG_CSPROJ = "TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.csproj"
LEG_EXT = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs"
LEG_SES = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs"
LEG_API = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs"
CONTRACT_CS = "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs"
READER = "TsScoringPlugin/Handshake/Telemetry/Shared/SwayStateReader.cs"


def _profile_guard(cls):
    cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-sway-")
    cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "TS_SCORING_DESKTOP_LOG")}
    os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name


def _profile_release(cls):
    for k, v in cls._saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    cls._profile_dir.cleanup()


# ---- the reference model (BVE b4 / u / t / c as decompiled; written here independently of the product module, to pin the replica) -------------------------------
OMEGA = 1.9792033717615696


def reference_series(a, lead_ms=3000, post_ms=3000, dt=17, az_before=None):
    """The (x, v) of the longitudinal spring for an input that is -a (steady) until T and 0 from T on. Returns [(t_ms, x, v)] for t = 0, dt, 2 dt ... after T.
    Independent re-implementation: 15-sample delay line, critical damping, RK4 with ceil(dt*60/1000) steps."""
    buf = [0.0] * 15
    idx = 0
    acc = 0.0
    x = v = 0.0

    def push(dt_s, value):
        nonlocal idx, acc
        before = math.floor(acc * 60.0)
        acc += dt_s
        k = math.floor(acc * 60.0) - before
        for _ in range(k):
            buf[idx] = value
            idx = (idx + 1) % 15
        acc = math.fmod(acc, 1.0 / 60.0)

    def frame(u):
        nonlocal x, v
        push(dt * 0.001, u)
        n = max(int(math.ceil(dt * 60 * 0.001)), 1)
        h = dt * 0.001 / n

        def e(px, pv):
            return -2.0 * OMEGA * pv - OMEGA * OMEGA * px + buf[idx] - u
        for _ in range(n):
            k1 = h * v
            k2 = h * e(x, v)
            k3 = h * (v + k2 / 2.0)
            k4 = h * e(x + k1 / 2.0, v + k2 / 2.0)
            k5 = h * (v + k4 / 2.0)
            k6 = h * e(x + k3 / 2.0, v + k4 / 2.0)
            k7 = h * (v + k6)
            k8 = h * e(x + k5, v + k6)
            x += (k1 + 2 * k3 + 2 * k5 + k7) / 6.0
            v += (k2 + 2 * k4 + 2 * k6 + k8) / 6.0

    for _ in range(lead_ms // dt):
        frame(-a)
    out = []
    for j in range(post_ms // dt + 1):
        frame(0.0)
        out.append((j * dt, x, v))
    return out


def ref_n(value):
    return int(12.5 * abs(value) * 64.0)


# ===================================================================================================================================================
# source rows (no Qt)
# ===================================================================================================================================================
class A_Sources(unittest.TestCase):
    def reader(self):
        if not exists(READER):
            self.fail("NO-READER-SRC: %s does not exist yet" % READER)
        return code_cs(READER)

    def test_SW_S01_the_reader_exists_and_is_shared(self):
        text = self.reader()
        self.assertIn("class SwayStateReader", text, "NO-READER-SRC: no SwayStateReader class")
        for csproj in (CUR_CSPROJ, LEG_CSPROJ):
            if "SwayStateReader.cs" not in read(csproj):
                self.fail("NO-READER-SRC: %s does not link SwayStateReader.cs" % csproj)

    def test_SW_S02_the_reader_has_no_compile_time_dependency_on_the_host_types(self):
        text = self.reader()
        for banned in ("BveTypes", "BveEx", "AtsEx", "TypeWrapping", "FastMember"):
            if banned in text:
                self.fail("NO-READER-SRC: the reader names %s (it must work on an object and System.Reflection only)" % banned)

    def test_SW_S03_the_declaring_type_t_is_named_and_the_base_u_is_not_confused_with_it(self):
        text = self.reader()
        if "DeclaredOnly" not in text:
            self.fail("NO-READER-SRC: no BindingFlags.DeclaredOnly (x and v must come from the declaring type t, not from a same-named field of u)")
        if text.count("BaseType") < 2:
            self.fail("NO-READER-SRC: the reader must walk two BaseType steps (spring -> u -> t)")
        for name in ("b", "c"):
            if not re.search(r'GetField\(\s*"%s"' % name, text):
                self.fail("NO-READER-SRC: no GetField(\"%s\") (x = t::b, v = t::c)" % name)

    def test_SW_S04_the_structure_signature_checks_omega_and_zeta(self):
        text = self.reader()
        if "1.9792033717615696" not in text:
            self.fail("NO-READER-SRC: omega 1.9792033717615696 is not checked")
        if not re.search(r"1e-12|0\.000000000001|1E-12", text):
            self.fail("NO-READER-SRC: no tolerance for the signature check")
        if not re.search(r"\b1\.0\b", text):
            self.fail("NO-READER-SRC: zeta 1.0 is not checked")

    def test_SW_S05_only_the_two_audited_versions_are_allowed(self):
        text = self.reader()
        for version in ("5.8.7554.391", "6.0.7554.619"):
            if version not in text:
                self.fail("NO-READER-SRC: the version %s is not in the allow list" % version)
        if "FileVersion" not in text and "GetVersionInfo" not in text:
            self.fail("NO-READER-SRC: the BVE file version is not read")

    def test_SW_S06_the_reader_only_reads(self):
        text = self.reader()
        for banned in (r"\.SetValue\(", r"\.Invoke\(", r"InvokeMember", r"SetMethod", r"\.CreateInstance", r"Activator\.", r"Interlocked", r"Volatile\.Write"):
            if re.search(banned, text):
                self.fail("NO-READER-SRC: the reader writes or calls (%s)" % banned)
        if ".GetValue(" not in text:
            self.fail("NO-READER-SRC: no FieldInfo.GetValue")

    def test_SW_S07_no_popup_no_jump_no_shared_state_no_exploration(self):
        text = self.reader()
        for banned in (r"MessageBox", r"ShowDialog", r"System\.Windows\.Forms", r"\bJump", r"File\.", r"StreamWriter", r"UdpClient", r"Registry",
                       r"Process\.Start", r"SetEnvironmentVariable", r"GetFields\(", r"GetMembers\(", r"GetProperties\(", r"GetMethods\(", r"FindMembers\(", r"GetNestedTypes\("):
            if re.search(banned, text):
                self.fail("NO-READER-SRC: forbidden in the reader: %s" % banned)

    def test_SW_S08_the_failure_is_a_state_and_is_not_repeated_every_tick(self):
        text = self.reader()
        for word in ("VersionUnsupported", "StructureMismatch", "catch"):
            if word not in text:
                self.fail("NO-READER-SRC: no %s" % word)
        if not re.search(r"(failed|Failed|resolved|Resolved|status|Status)", text):
            self.fail("NO-READER-SRC: no cached resolution state (a failure must not be retried every Tick)")

    def test_SW_S09_the_contract_has_the_tokens(self):
        text = code_cs(CONTRACT_CS)
        if 'TokSway = "sway"' not in text or 'TokAccelX = "accelx"' not in text:
            self.fail("NO-WIRE: TelemetryContract.cs has no TokSway / TokAccelX")
        if "SWAYR" not in text and (not exists(READER) or "SWAYR" not in code_cs(READER)):
            self.fail("NO-WIRE: the SWAYR wire key is not defined")

    def test_SW_S10_current_reads_the_public_input_and_the_reflection_and_writes_the_parts(self):
        text = code_cs(CLASS1)
        if "vehicle.Vibration.FrontAccelerationX" not in text:
            self.fail("NO-WIRE: Class1.cs does not read vehicle.Vibration.FrontAccelerationX")
        for needle in (",ACCELX:", ",SWAY:", ",SWAYR:", "SwayStateReader"):
            if needle not in text:
                self.fail("NO-WIRE: Class1.cs does not contain %s" % needle)
        i = text.index(",SWAY:")
        around = text[max(0, i - 600):i + 300]
        for banned in ("9.80665", "Math.Abs", "Math.Min", "Math.Max", "Clamp", "0.315", "12.5"):
            if banned in around:
                self.fail("NO-WIRE: the Current SWAY part converts or derives (%s near it): C# sends the raw states only" % banned)
        if "F6" not in around:
            self.fail("NO-WIRE: the Current SWAY part is not written with F6")
        j = text.index("FrontAccelerationX")
        near = text[max(0, j - 200):j + 400]
        for banned in ("9.80665", "Math.Abs", "Math.Min", "Math.Max", "Clamp"):
            if banned in near:
                self.fail("NO-WIRE: the Current ACCELX converts (%s near it): it is the raw m/s2 value" % banned)
        if "MainForm.Assistants" not in text:
            self.fail("NO-WIRE: the Current entry is MainForm.Assistants.Items")

    def test_SW_S11_legacy_has_its_own_interface_and_the_same_wire(self):
        api, ext, ses = code_cs(LEG_API), code_cs(LEG_EXT), code_cs(LEG_SES)
        if "interface ILegacySwayApi" not in api:
            self.fail("NO-WIRE: no separate ILegacySwayApi interface")
        if "current.Vehicle.VibrationManager.FrontAccelerationX" not in ext:
            self.fail("NO-WIRE: the Legacy extension does not read VibrationManager.FrontAccelerationX")
        # Legacy sway source lookup (an intended change): the entry is still hacker.MainForm -> AssistantDrawer -> Items, now in AtsExSwayHostAccess and read by LegacySwayProvider
        if "hacker.MainForm" not in ext or ".AssistantDrawer" not in ext or "LegacySwayProvider" not in ext:
            self.fail("NO-WIRE: the Legacy entry is MainForm.AssistantDrawer.Items")
        for needle in ("TokSway", "TokAccelX", '"SWAY"', '"ACCELX"', "KeySwayR"):
            if needle not in ses:
                self.fail("NO-WIRE: the Legacy session does not contain %s" % needle)
        block = ses[ses.index('"SWAY"') - 400:ses.index('"SWAY"') + 300]
        if "F6" not in block:
            self.fail("NO-WIRE: the Legacy SWAY part is not written with F6")
        if "IsNaN" not in ses[ses.index('"ACCELX"') - 500:ses.index('"ACCELX"') + 200]:
            self.fail("NO-WIRE: the Legacy ACCELX is not written only for a finite value")

    def test_SG_legacy_api_interface_is_unchanged(self):
        body = code_cs(LEG_API)
        body = body[body.index("interface ILegacyApi"):]
        body = body[:body.index("}")]
        for banned in ("AccelerationZ", "Sway", "FrontAcceleration"):
            self.assertNotIn(banned, body)
        self.assertIn("TryScenarioMeta", body)

    def test_SG_the_shadow_stage1_wire_is_still_there(self):
        self.assertIn('TokAccelZ = "accelz"', code_cs(CONTRACT_CS))
        self.assertIn("vehicle.Vibration.AccelerationZ", code_cs(CLASS1))
        self.assertIn("current.Vehicle.VibrationManager.AccelerationZ", code_cs(LEG_EXT))

    def test_SG_the_reader_cannot_write_scoring_or_shared_state(self):
        """GUARD (vacuous before the reader exists): no scoring, jump or shared-state names in the reader or the new Python module."""
        if exists(READER):
            text = code_cs(READER)
            for banned in ("jump", "Jump", "score", "Score", "retry", "Retry", "turnback", "Turnback"):
                self.assertNotIn(banned, text)
        if exists("sway_shadow.py"):
            text = code_py("sway_shadow.py")
            for banned in ("jump_lock", "retry_pending", "turnback", "key_states", "hook_dict", "numeric_router", "keys_blocked", "udp_socket", "jump_client",
                           "add_score_popup", "score_details", "save_data", "popups", "theoretical_score", "hb_cushion"):
                self.assertNotIn(banned, text)


# ===================================================================================================================================================
# pure functions (no Qt needed for sway_shadow itself)
# ===================================================================================================================================================
class B_Pure(unittest.TestCase):
    def setUp(self):
        self.W = import_sway("NO-PURE")

    def f(self, name, code="NO-PURE"):
        return need(self.W, name, code)

    def test_SW_P01_the_longitudinal_value_is_x_plus_0_315_v(self):
        self.assertAlmostEqual(self.f("sway_value")(0.1, 0.2), 0.1 + 0.315 * 0.2, places=12, msg="NO-PURE: value = x + 0.315 v")

    def test_SW_P02_the_combined_value_is_the_signed_sum_so_opposite_signs_cancel(self):
        c = self.f("sway_combined")
        self.assertAlmostEqual(c(0.05, 0.0, -0.05, 0.0), 0.0, places=12, msg="NO-PURE: the combined value is the signed sum")
        self.assertAlmostEqual(c(0.02, 0.1, 0.01, -0.2), (0.02 + 0.315 * 0.1) + (0.01 + 0.315 * -0.2), places=12, msg="NO-PURE: both springs, both x and v")

    def test_SW_P03_n_uses_the_figures_order_of_operations(self):
        n = self.f("sway_n")
        for value in (0.0, 0.001, 0.0425, 0.043, 0.054, 0.0653, 0.066, 0.08, 0.11, -0.043, -0.066):
            self.assertEqual(n(value), ref_n(value), "NO-PURE: n(%r) must be int(12.5*abs(x)*64.0)" % value)

    def test_SW_P04_that_order_equals_int_800_abs_at_every_label_boundary(self):
        """The proof the Owner asked for: the BVE order and the simplified int(800*abs(x)) agree at and next to every k/800 (k = 0..200) - or the module keeps the BVE order."""
        n = self.f("sway_n")
        for k in range(0, 201):
            base = k / 800.0
            for x in (base, math.nextafter(base, 0.0), math.nextafter(base, 1.0), -base):
                self.assertEqual(n(x), ref_n(x), "NO-PURE: n differs from the BVE order at %r" % x)
        source = code_py("sway_shadow.py")
        if "12.5" not in source or "64.0" not in source:
            self.fail("NO-PURE: the first candidate keeps the BVE order (12.5 and 64.0 in the source)")

    def test_SW_P05_n_is_not_clamped(self):
        self.assertEqual(self.f("sway_n")(0.11), 88, "NO-PURE: n is not clamped (the figure clamps only the red and green components)")
        self.assertGreater(self.f("sway_n")(1.0), 700)

    def test_SW_P06_a_bad_value_has_no_n_and_no_colour(self):
        n, label = self.f("sway_n"), self.f("sway_label")
        for bad in (None, float("nan"), float("inf"), float("-inf"), "x"):
            self.assertIsNone(n(bad), "NO-PURE: %r has no n" % (bad,))
        for bad in (None, -1, 1.5):
            self.assertIsNone(label(bad), "NO-PURE: %r has no colour label" % (bad,))

    def test_SW_P07_to_P13_the_seven_levels_at_every_boundary(self):
        label = self.f("sway_label")
        table = ((0, "緑"), (5, "緑"), (6, "黄緑"), (15, "黄緑"), (16, "黄"), (26, "黄"), (27, "黄橙"), (37, "黄橙"), (38, "橙"), (48, "橙"),
                 (49, "赤橙"), (58, "赤橙"), (59, "赤"), (63, "赤"), (64, "赤"), (100, "赤"), (700, "赤"))
        for n, want in table:
            self.assertEqual(label(n), want, "NO-PURE: n=%d must be %s" % (n, want))

    def test_SW_P14_red_display_and_full_saturation_are_different_boundaries(self):
        red, sat = self.f("sway_red_display"), self.f("sway_saturated")
        self.assertEqual((red(58), red(59), red(63), red(64)), (False, True, True, True), "NO-PURE: the displayed red starts at n=59")
        self.assertEqual((sat(58), sat(59), sat(63), sat(64), sat(88)), (False, False, False, True, True), "NO-PURE: the material colour saturates at n=64")

    def test_SW_P15_the_shadow_candidates_are_34_and_52(self):
        pen = self.f("sway_penalty_candidate")
        for n, want in ((0, 0), (33, 0), (34, -100), (51, -100), (52, -200), (53, -200), (100, -200), (700, -200)):
            self.assertEqual(pen(n), want, "NO-PURE: n=%d must be %d (n>=34 -100, n>=52 -200, never n>=53 and never -300)" % (n, want))
        self.assertIsNone(pen(None), "NO-PURE: no n, no candidate")

    def test_SW_P16_the_note_about_the_approximation_is_kept(self):
        W = self.W
        note = getattr(W, "SEVEN_LEVEL_NOTE", None)
        if not note or "7段階" not in note or "診断用" not in note:
            self.fail("NO-PURE: SEVEN_LEVEL_NOTE (BVEの連続的な材質色計算を、TScoringが診断用に7段階へ近似した表示である。) is missing")

    # ---- the replica (public API) -------------------------------------------------------------------------------------------------------------------
    def replica_step_series(self, a=1.0, dt=17, lead_ms=3000, post_ms=3000):
        R = self.f("SwayReplica", "NO-REPLICA")
        r = R()
        for _ in range(lead_ms // dt):
            r.step(dt, -a, 0.0)
        out = []
        for j in range(post_ms // dt + 1):
            r.step(dt, 0.0, 0.0)
            out.append((j * dt, r.longitudinal_value))
        return r, out

    def test_SW_R01_the_replica_peak_is_the_figures_step_response(self):
        _, out = self.replica_step_series()
        t, peak = min(out, key=lambda p: p[1])
        self.assertAlmostEqual(peak, -0.06687, delta=3e-4, msg="NO-REPLICA: the stop pulse peak is -0.0669 per m/s2 of the last deceleration")
        self.assertTrue(204 <= t <= 238, "NO-REPLICA: the peak comes about 221 ms after the step (got %d)" % t)

    def test_SW_R02_the_replica_equals_the_independent_reference_series(self):
        _, out = self.replica_step_series()
        ref = reference_series(1.0)
        for (t, value), (rt, x, v) in zip(out, ref):
            self.assertAlmostEqual(value, x + 0.315 * v, places=9, msg="NO-REPLICA: differs from the reference at +%d ms" % t)

    def test_SW_R03_the_decay_is_slow(self):
        _, out = self.replica_step_series()
        peak = min(p[1] for p in out)
        at = lambda ms: min(out, key=lambda p: abs(p[0] - ms))[1] / peak
        for ms, want in ((500, 0.753), (1000, 0.390), (2000, 0.085)):
            self.assertAlmostEqual(at(ms), want, delta=0.025, msg="NO-REPLICA: decay ratio at +%d ms" % ms)

    def test_SW_R04_a_constant_input_decays_to_nothing(self):
        R = self.f("SwayReplica", "NO-REPLICA")
        r = R()
        for _ in range(1500):
            r.step(17, -1.0, 0.7)
        self.assertAlmostEqual(r.longitudinal_value, 0.0, places=9, msg="NO-REPLICA: the figure reacts to the CHANGE of the input, a constant input returns to zero")
        self.assertAlmostEqual(r.lateral_value, 0.0, places=9)

    def test_SW_R05_longitudinal_and_lateral_are_separate_states(self):
        R = self.f("SwayReplica", "NO-REPLICA")
        r = R()
        for _ in range(180):
            r.step(17, 0.0, -1.0)
        for _ in range(14):
            r.step(17, 0.0, 0.0)
        self.assertEqual(r.longitudinal_value, 0.0, "NO-REPLICA: a lateral input must not move the longitudinal state")
        self.assertLess(r.lateral_value, -0.02, "NO-REPLICA: the lateral state follows the lateral input")
        self.assertAlmostEqual(r.combined_value, r.longitudinal_value + r.lateral_value, places=12, msg="NO-REPLICA: combined = longitudinal + lateral")

    def test_SW_R06_the_warm_up_is_three_seconds(self):
        R = self.f("SwayReplica", "NO-REPLICA")
        r = R()
        self.assertFalse(r.warm, "NO-REPLICA: a fresh replica is cold")
        for _ in range(176):
            r.step(17, 0.0, 0.0)               # 2992 ms
        self.assertFalse(r.warm, "NO-REPLICA: 2.992 s is still warm-up")
        r.step(17, 0.0, 0.0)                   # 3009 ms
        self.assertTrue(r.warm, "NO-REPLICA: 3.0 s ends the warm-up")
        r.reset()
        self.assertFalse(r.warm, "NO-REPLICA: reset starts a new warm-up")
        self.assertEqual((r.longitudinal_value, r.lateral_value), (0.0, 0.0), "NO-REPLICA: reset clears the states")

    def test_SW_R07_the_frame_time_is_clamped_like_the_host_and_a_bad_one_is_ignored(self):
        R = self.f("SwayReplica", "NO-REPLICA")
        a, b = R(), R()
        for _ in range(40):
            a.step(17, -1.0, 0.0)
            b.step(17, -1.0, 0.0)
        a.step(1000, 0.0, 0.0)
        b.step(500, 0.0, 0.0)
        self.assertAlmostEqual(a.longitudinal_value, b.longitudinal_value, places=12, msg="NO-REPLICA: dt is clamped to 500 ms")
        before = a.longitudinal_value
        a.step(0, 5.0, 5.0)
        a.step(-17, 5.0, 5.0)
        self.assertEqual(a.longitudinal_value, before, "NO-REPLICA: dt <= 0 is ignored")

    def test_SW_R09_a_missing_input_resets_its_channel_and_is_not_a_zero(self):
        R = self.f("SwayReplica", "NO-REPLICA")
        r = R()
        for _ in range(200):
            r.step(17, -1.0, 0.5)
        self.assertTrue(r.valid_long and r.valid_lat, "NO-REPLICA: both channels have an input")
        r.step(17, None, 0.5)
        self.assertFalse(r.valid_long, "NO-REPLICA: a missing AccelerationZ is not a 0.0: the channel is invalid")
        self.assertTrue(r.valid_lat, "NO-REPLICA: the other channel goes on")
        self.assertEqual(r.longitudinal_value, 0.0, "NO-REPLICA: the invalid channel starts again from rest")
        self.assertFalse(r.warm, "NO-REPLICA: the invalid channel is cold again")
        r.step(17, float("nan"), None)
        self.assertFalse(r.valid_long or r.valid_lat, "NO-REPLICA: a non-finite input is a missing input")

    def test_SW_R08_the_delay_line_is_fifteen_samples(self):
        """A step shorter than the delay: the forcing u(t-0.25)-u(t) is the pulse; a single 17 ms frame of input -1 followed by zeros ends 15 samples later."""
        R = self.f("SwayReplica", "NO-REPLICA")
        r = R()
        for _ in range(200):
            r.step(17, 0.0, 0.0)
        r.step(17, -1.0, 0.0)
        values = []
        for _ in range(40):
            r.step(17, 0.0, 0.0)
            values.append(r.longitudinal_value)
        self.assertGreater(max(abs(v) for v in values), 1e-4, "NO-REPLICA: a one-frame input leaves a trace")


# ===================================================================================================================================================
# the wire into the overlay and the contract module
# ===================================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class W_Wire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _profile_guard(cls)
        import telemetry_contract
        cls.T = telemetry_contract

    @classmethod
    def tearDownClass(cls):
        _profile_release(cls)

    def test_SW_W01_the_tokens_are_in_the_vocabulary_and_swayr_is_not_a_token(self):
        T = self.T
        if T.TOKEN_KEYS.get("sway") != ("SWAY",) or T.TOKEN_KEYS.get("accelx") != ("ACCELX",):
            self.fail("NO-WIRE: TOKEN_KEYS needs sway=(SWAY,) and accelx=(ACCELX,)")
        for keys in T.TOKEN_KEYS.values():
            self.assertNotIn("SWAYR", keys, "NO-WIRE: SWAYR is a diagnostic part, not a token (a token would lengthen every missing list)")

    def test_SW_W02_sway_capture_takes_four_finite_values_and_nothing_else(self):
        capture = need(self.T, "sway_capture", "NO-WIRE")
        self.assertEqual(capture(["SPEED:1", "SWAY:0.010000:-0.020000:0.030000:0.040000"]), (0.01, -0.02, 0.03, 0.04))
        for bad in ("SWAY:", "SWAY:1:2:3", "SWAY:1:2:3:4:5", "SWAY:nan:0:0:0", "SWAY:0:inf:0:0", "SWAY:0:0:-inf:0", "SWAY:a:b:c:d", "SWAY:0.1::0.2:0.3"):
            self.assertIsNone(capture([bad]), "NO-WIRE: %r must be None (no 0.0 is invented)" % bad)
        self.assertIsNone(capture(["SPEED:1"]), "NO-WIRE: no SWAY part -> None")

    def test_SW_W03_accelx_capture_is_like_accelz_capture(self):
        capture = need(self.T, "accelx_capture", "NO-WIRE")
        for text in ("ACCELX:nan", "ACCELX:inf", "ACCELX:-inf", "ACCELX:abc", "ACCELX:", "SPEED:1"):
            self.assertIsNone(capture([text]), "NO-WIRE: %r must be None" % text)
        self.assertEqual(capture(["SPEED:1", "ACCELX:-0.512300"]), -0.5123)

    def test_SW_W04_swayr_capture_reads_the_resolution_diagnostic(self):
        capture = need(self.T, "swayr_capture", "NO-WIRE")
        got = capture(["SWAYR:ok:5.8.7554.391:current"])
        self.assertEqual((got["result"], got["version"], got["entry"]), ("ok", "5.8.7554.391", "current"), "NO-WIRE")
        got = capture(["SWAYR:structure-mismatch:6.0.7554.619:legacy:member-absent"])
        self.assertEqual((got["result"], got["detail"]), ("structure-mismatch", "member-absent"), "NO-WIRE")
        for bad in ("SWAYR:", "SWAYR:ok", "SWAYR:ok:5.8:legacy:x:y:z"):
            self.assertIsNone(capture([bad]), "NO-WIRE: %r is not a diagnostic" % bad)

    def test_SW_W05_the_budget_is_80_and_only_the_diagnostic_text_uses_it(self):
        if self.T.DIAGNOSTIC_LIST_BUDGET != 80:
            self.fail("NO-BUDGET: DIAGNOSTIC_LIST_BUDGET is %r, not 80" % self.T.DIAGNOSTIC_LIST_BUDGET)
        for rel in ("main.py", "managed_input.py", "scoring_logic.py", "hud_ui.py"):
            self.assertNotIn("DIAGNOSTIC_LIST_BUDGET", code_py(rel), "the budget must not leak into %s" % rel)
        self.assertNotIn("DIAGNOSTIC_LIST_BUDGET", code_cs(CONTRACT_CS), "NO-BUDGET: the wire contract (C#) knows no diagnostic budget")

    def _missing_set_of_length(self, length):
        """A set of known tokens whose '+'-joined, sorted list is exactly `length` characters (subset-sum over the token lengths)."""
        tokens = sorted(self.T.KNOWN_TOKENS)
        best = {(0, 0): ()}                 # (characters without the separators, number of tokens) -> chosen tokens
        for t in tokens:
            for (total, count), chosen in list(best.items()):
                key = (total + len(t), count + 1)
                if key not in best:
                    best[key] = chosen + (t,)
        for (total, count), chosen in best.items():
            if chosen and total + count - 1 == length:
                return frozenset(chosen)
        return None

    def test_SW_W06_the_missing_list_at_the_budget_boundaries(self):
        T = self.T
        if T.DIAGNOSTIC_LIST_BUDGET != 80:
            self.fail("NO-BUDGET: DIAGNOSTIC_LIST_BUDGET is %r, not 80" % T.DIAGNOSTIC_LIST_BUDGET)
        for length, shown in ((70, True), (71, True), (75, True), (80, True), (81, False), (85, False)):
            missing = self._missing_set_of_length(length)
            self.assertIsNotNone(missing, "the test needs a token set of %d characters" % length)
            fields = T.compact_groups(T.Availability(T.KNOWN_TOKENS - missing))
            text = "+".join(sorted(missing))
            self.assertEqual(len(text), length)
            if shown:
                self.assertEqual(fields.get("missing"), text, "NO-BUDGET: a %d character list must be written" % length)
            else:
                self.assertNotIn("missing", fields, "NO-BUDGET: a %d character list is over the budget (default behaviour: no list)" % length)

    def test_SW_W07_the_legacy_worst_case_with_accelz_accelx_and_sway_missing_is_still_written(self):
        T = self.T
        import test_telemetry_l3 as L3
        worst = T.Availability(frozenset(L3.LEGACY_TOKENS))                # the V02 list of the Legacy sender: no accelz, no accelx, no sway
        fields = T.compact_groups(worst)
        missing = "+".join(sorted(T.KNOWN_TOKENS - worst.tokens))
        self.assertIn("sway", missing, "NO-BUDGET: sway must be a known token that can be missing")
        self.assertIn("accelx", missing, "NO-BUDGET: accelx must be a known token that can be missing")
        self.assertIn("accelz", missing)
        self.assertGreater(len(missing), 70, "NO-BUDGET: with accelz, accelx and sway all missing the Legacy list is longer than the OLD budget of 70 (measured 71): without the new budget it would vanish")
        self.assertLessEqual(len(missing), 80)
        self.assertEqual(fields.get("missing"), missing, "NO-BUDGET: the Legacy worst case (%d characters) must not silently disappear" % len(missing))

    def test_SW_W09_a_line_without_sway_or_accelx_resets_the_values(self):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication(["sway"])            # a reference is kept: an application object that is collected at once crashes Qt when this test runs alone
        import lc_legacy_feed as F
        import sia_rig as R
        import main
        rig = R.Rig(main)
        self.addCleanup(rig.close)
        o = rig.o
        o.apply_telemetry_text(F.line("current", 1, 36000000, 10.0, 100.0, SWAY="0.010000:0.020000:0.030000:0.040000", ACCELX="0.250000", SWAYR="ok:5.8.7554.391:current"))
        if getattr(o, "bve_sway", None) != (0.01, 0.02, 0.03, 0.04) or getattr(o, "bve_accel_x", None) != 0.25:
            self.fail("NO-WIRE: the SWAY / ACCELX parts of the line were not taken (bve_sway=%r bve_accel_x=%r)" % (getattr(o, "bve_sway", "missing"), getattr(o, "bve_accel_x", "missing")))
        o.apply_telemetry_text(F.line("current", 1, 36000100, 10.0, 101.0))
        self.assertIsNone(o.bve_sway, "NO-WIRE: an old SWAY value must not stay on a line without it")
        self.assertIsNone(o.bve_accel_x, "NO-WIRE: an old ACCELX value must not stay")
        self.assertIsNone(o.bve_sway_res, "NO-WIRE: an old diagnostic must not stay")
        o.apply_telemetry_text(F.line("current", 1, 36000200, 10.0, 102.0, SWAY="0.1:0.2:nan:0.4"))
        self.assertIsNone(o.bve_sway, "NO-WIRE: a SWAY part with a bad state is not a sample")

    def test_SG10_changing_the_budget_does_not_change_the_telemetry_content(self):
        T = self.T
        line = "SCENARIO_ID:1,TIME:1000,LOCATION:1.0,SPEED:2.0,ACCELZ:-0.5,SWAY:0.0:0.0:0.0:0.0,AVAIL:1:accelz+sway+time+speed+loc"
        a = T.parse_telemetry(line)
        saved = T.DIAGNOSTIC_LIST_BUDGET
        try:
            T.DIAGNOSTIC_LIST_BUDGET = 10
            b = T.parse_telemetry(line)
        finally:
            T.DIAGNOSTIC_LIST_BUDGET = saved
        self.assertEqual((a.valid, a.tokens, a.scenario_id), (b.valid, b.tokens, b.scenario_id), "NO-BUDGET: the parsed content must not depend on the diagnostic budget")
        self.assertEqual(T.format_avail(["sway", "accelz"]), "AVAIL:1:accelz+sway")


# ===================================================================================================================================================
# SWY-D1 (Owner, 2026-11-07): the Caller keeps 192 characters of an application log line (it was 160). Diagnostic path only.
# The lines are built with the REAL writer (managed_hud.emit_event) and the REAL compact_groups; the cap is READ from the Caller source.
# ===================================================================================================================================================
CALLER_APM = "TsScoringPlugin/Handshake/Caller/src/AppProcessManager.cs"
CALLER_APM_BASE_SHA256 = "93A64C90D1103D0AA4C0C6766DF9A4DA38CBB764C2D5B149CED573A905336E08"    # the normalised (LF) text of b4f2266 / 7406c8f with the cap of 160
WORST_PID, WORST_GEN, WORST_CHANGES = 4294967295, 9999, 9999                                        # the widest numbers the fields can take


def caller_cap():
    m = re.search(r"public const int MaxStderrLineChars = (\d+);", read(CALLER_APM))
    return int(m.group(1)) if m else None


def real_line(event, availability, **extra):
    """The text the application writes for a telemetry diagnostic event: the real writer, the real compact fields."""
    import managed_hud
    import telemetry_contract as T

    class Args(object):
        bve_pid = WORST_PID
    hud = object.__new__(managed_hud.ManagedHudController)
    hud._args = Args()
    out = []
    hud._log = out.append
    fields = dict(gen=WORST_GEN, avail="explicit", **T.compact_groups(availability))
    if event == "telemetry-avail":
        fields["changes"] = WORST_CHANGES
    fields.update(extra)
    hud.emit_event(event, **fields)
    return out[0]


def missing_set_of_length(length):
    import telemetry_contract as T
    best = {(0, 0): ()}
    for t in sorted(T.KNOWN_TOKENS):
        for (total, count), chosen in list(best.items()):
            key = (total + len(t), count + 1)
            if key not in best:
                best[key] = chosen + (t,)
    for (total, count), chosen in best.items():
        if chosen and total + count - 1 == length:
            return frozenset(chosen)
    return None


class C_Caller(unittest.TestCase):
    def cap(self):
        cap = caller_cap()
        self.assertIsNotNone(cap, "NO-CALLER-CAP: MaxStderrLineChars was not found in the Caller source")
        return cap

    def test_SW_D01_the_caller_keeps_192_characters_of_a_line(self):
        self.assertEqual(caller_cap(), 192, "NO-CALLER-CAP: AppProcessTiming.MaxStderrLineChars is %r, not 192" % caller_cap())

    def _full_line(self, length):
        import telemetry_contract as T
        missing = missing_set_of_length(length)
        self.assertIsNotNone(missing, "the test needs a token set of %d characters" % length)
        text = "+".join(sorted(missing))
        line = real_line("telemetry-avail", T.Availability(T.KNOWN_TOKENS - missing))
        if ("missing=" + text) not in line:
            self.fail("NO-BUDGET: the %d character list is not in the line (budget %d, the list is written up to 80)" % (length, T.DIAGNOSTIC_LIST_BUDGET))
        return line

    def test_SW_D02_a_71_character_list_is_shown_whole_in_telemetry_avail(self):
        line = self._full_line(71)
        self.assertLessEqual(len(line), self.cap(), "NO-CALLER-CAP: the telemetry-avail line with a 71 character list is %d characters, the Caller keeps %d" % (len(line), self.cap()))

    def test_SW_D03_an_80_character_list_is_shown_whole_in_telemetry_avail(self):
        line = self._full_line(80)
        self.assertLessEqual(len(line), self.cap(), "NO-CALLER-CAP: the telemetry-avail line with an 80 character list is %d characters, the Caller keeps %d" % (len(line), self.cap()))

    def test_SW_D04_the_legacy_worst_case_with_accelz_accelx_and_sway_missing_is_shown_whole(self):
        import telemetry_contract as T
        import test_telemetry_l3 as L3
        worst = T.Availability(frozenset(L3.LEGACY_TOKENS))
        missing = "+".join(sorted(T.KNOWN_TOKENS - worst.tokens))
        for event in ("telemetry-avail", "telemetry-first"):
            line = real_line(event, worst)
            if ("missing=" + missing) not in line:
                self.fail("NO-BUDGET: the list of the Legacy worst case (%d characters) is not in the %s line (budget %d)" % (len(missing), event, T.DIAGNOSTIC_LIST_BUDGET))
            self.assertLessEqual(len(line), self.cap(), "NO-CALLER-CAP: the %s line of the Legacy worst case is %d characters, the Caller keeps %d" % (event, len(line), self.cap()))
        self.assertIn("accelz", missing)
        self.assertIn("sway", missing)

    def test_SW_D05_no_telemetry_line_of_any_availability_is_cut(self):
        import random
        import telemetry_contract as T
        rnd = random.Random(20261107)
        toks = sorted(T.KNOWN_TOKENS)
        cases = [frozenset(), frozenset(toks)] + [frozenset(rnd.sample(toks, rnd.randint(0, len(toks)))) for _ in range(3000)]
        cap = self.cap()
        widest = 0
        for have in cases:
            for event in ("telemetry-avail", "telemetry-first"):
                line = real_line(event, T.Availability(have))
                widest = max(widest, len(line))
                self.assertLessEqual(len(line), cap, "NO-CALLER-CAP: a %s line is %d characters (%s), the Caller keeps %d" % (event, len(line), line[-60:], cap))
        self.assertLessEqual(widest, 192, "NO-CALLER-CAP: the widest telemetry line is %d characters, over 192" % widest)

    def test_SG11_the_list_never_vanishes_silently(self):
        import random
        import telemetry_contract as T
        rnd = random.Random(7)
        toks = sorted(T.KNOWN_TOKENS)
        for _ in range(3000):
            have = frozenset(rnd.sample(toks, rnd.randint(0, len(toks))))
            fields = T.compact_groups(T.Availability(have))
            missing = "+".join(sorted(T.KNOWN_TOKENS - have)) or "none"
            holding = "+".join(sorted(have)) or "none"
            self.assertIn("groups", fields)
            budget = T.DIAGNOSTIC_LIST_BUDGET
            if len(missing) <= budget:
                self.assertEqual(fields.get("missing"), missing, "a list within the budget must be written")
            elif len(holding) <= budget:
                self.assertEqual(fields.get("have"), holding, "the other list is written when the missing list is over the budget")
            else:
                self.assertNotIn("missing", fields)
                self.assertNotIn("have", fields)

    def test_SW_D06_the_budget_is_80(self):
        import telemetry_contract as T
        if T.DIAGNOSTIC_LIST_BUDGET != 80:
            self.fail("NO-BUDGET: DIAGNOSTIC_LIST_BUDGET is %r, not 80 (SWY-D1 keeps the budget of 80)" % T.DIAGNOSTIC_LIST_BUDGET)

    def test_SG13_the_telemetry_first_line_is_what_it_was(self):
        import telemetry_contract as T
        line = real_line("telemetry-first", T.Availability(T.KNOWN_TOKENS - {"speed"}))
        self.assertEqual(line, "[MANAGED] event=telemetry-first pid=%d avail=explicit gen=%d groups=%d missing=speed" % (WORST_PID, WORST_GEN, len(T.KNOWN_TOKENS) - 1))
        self.assertNotIn("changes=", line)

    def test_SG14_the_caller_source_differs_from_the_baseline_only_in_the_cap_number(self):
        import hashlib
        text = read(CALLER_APM)
        self.assertEqual(text.count("MaxStderrLineChars = "), 1)
        restored = re.sub(r"(public const int MaxStderrLineChars = )\d+;", r"\g<1>160;", text)
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest().upper(), CALLER_APM_BASE_SHA256,
                         "the Caller source must differ from the baseline in the cap NUMBER only (the way a line is cut, Printable, is untouched)")

    def test_SG15_the_cap_is_not_known_to_the_scoring_history_checkpoint_or_result_code(self):
        for rel in ("scoring_logic.py", "managed_input.py", "sway_shadow.py", "jump_transaction.py", "managed_state.py", "telemetry_contract.py"):
            if exists(rel):
                self.assertNotIn("MaxStderrLineChars", code_py(rel), "the Caller's diagnostic cap must not leak into %s" % rel)
        self.assertNotIn("MaxStderrLineChars", code_cs(CONTRACT_CS), "the wire contract knows no Caller cap")

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
        cls.app = QApplication.instance() or QApplication(["sway"])
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

    def step(self, dt=0.1, speed=None, calc_g=None, az=None, ax=None, sway=None, loc=None, jump=None, official=None, same_time=False):
        o = self.o
        if not same_time:
            self.t += dt
            o.bve_time_ms += int(round(dt * 1000))
        if speed is not None:
            o.bve_speed = speed
        if calc_g is not None:
            o.bve_calc_g = calc_g
        o.bve_accel_z = az
        o.bve_accel_x = ax
        o.bve_sway = sway
        if loc is not None:
            o.bve_location = loc
        if jump is not None:
            o.bve_jump_count = jump
        if official is not None:
            o.is_official_jumping = official
        self.S.update_physics_and_scoring(o, self.t, dt)

    def accelerate(self, n=20, g=0.08, az=0.8):
        for i in range(n):
            self.step(speed=5.0 + 0.3 * i, calc_g=g, az=az, loc=100.0 + 0.6 * i)

    def run_in(self, calc_g=-0.02, az=-0.9, n=8):
        """Accelerate, then brake with speed > 0 (no stop yet)."""
        self.accelerate()
        for i in range(n):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=calc_g, az=az)

    def stop_at(self, sway0, az=-0.9, calc_g=-0.02):
        """The stop tick T (speed 0.0). Its own SWAY sample is sway0."""
        self.step(speed=0.0, calc_g=calc_g, az=az, sway=sway0)

    def after(self, samples, dt=0.017, speed=0.0, az=0.0):
        for s in samples:
            self.step(dt=dt, speed=speed, calc_g=0.0, az=az, sway=s)

    def W(self):
        return import_sway("NO-TRACKER")

    def sh(self):
        W = self.W()
        return need(W, "state_of", "NO-TRACKER")(self.o)

    def last(self):
        last = getattr(self.sh(), "last", None)
        if last is None:
            self.fail("NO-TRACKER: no closed stop window yet")
        return last

    def capture_log(self, enabled=True):
        import scoring_logic
        lines = []
        saved = (scoring_logic.write_desktop_log, scoring_logic.desktop_log_enabled)
        scoring_logic.write_desktop_log = lambda msg: lines.append(msg)
        scoring_logic.desktop_log_enabled = lambda: enabled
        self.addCleanup(lambda: setattr(scoring_logic, "write_desktop_log", saved[0]))
        self.addCleanup(lambda: setattr(scoring_logic, "desktop_log_enabled", saved[1]))
        return lines

    @staticmethod
    def pulse(a=1.0, ms=1500, dt=17):
        """Reflection-like (xc, vc, xd, vd) tuples for a stop pulse of the last deceleration a (T at index 0)."""
        return [(x, v, 0.0, 0.0) for (_, x, v) in reference_series(a, post_ms=ms, dt=dt)]

    def jerk(self):
        return [p["text"] for p in self.o.popups if p.get("category") == "停車時衝動"]


class T_Tracker(Direct):
    def test_SW_T01_samples_before_the_stop_are_not_in_the_window(self):
        self.scene()
        self.run_in()
        self.step(speed=1.0, calc_g=-0.02, az=-0.9, sway=(-0.3, 0.0, 0.0, 0.0))          # a huge state right before the stop
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        self.after([(-0.02, 0.0, 0.0, 0.0)] * 4)
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-0.01, 0.0, 0.0, 0.0))     # T + 1.0 closes it
        last = self.last()
        self.assertAlmostEqual(last["state_peak"], 0.02, places=9, msg="NO-TRACKER: the 0.5 s before the stop must not be searched (0.3 is not in the window)")

    def test_SW_T02_the_main_value_is_the_absolute_value_of_the_minimum_state(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.03, 0.0, 0.0, 0.0))
        self.after([(-0.07, 0.0, 0.0, 0.0), (-0.05, 0.0, 0.0, 0.0), (0.02, 0.0, 0.0, 0.0)])
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
        last = self.last()
        self.assertAlmostEqual(last["state_peak"], 0.07, places=9, msg="NO-TRACKER: stop_sway_longitudinal_state_peak = |min state|")
        self.assertEqual(last["n_peak"], ref_n(0.07), "NO-TRACKER: stop_sway_longitudinal_n_peak = int(12.5*0.07*64.0)")
        self.assertEqual(last["n_peak"], 56)

    def test_SW_T03_the_main_value_is_the_absolute_maximum_of_either_sign(self):      # intended change (Owner ruling 2026-11-08, SHD-L-02 backward stop): was "the simple absolute maximum is recorded beside it"
        self.scene()
        self.run_in()
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        self.after([(-0.04, 0.0, 0.0, 0.0), (0.09, 0.0, 0.0, 0.0)])
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
        last = self.last()
        self.assertAlmostEqual(last["state_peak"], 0.09, places=9, msg="NO-TRACKER: the main value is the largest |state| of either sign (a backward stop answers on the positive side)")
        self.assertAlmostEqual(last["abs_peak"], 0.09, places=9, msg="NO-TRACKER: stop_sway_longitudinal_abs_peak = max |state|")
        self.assertEqual(last["n_peak"], ref_n(0.09), "NO-TRACKER: the main n comes from the largest |state| (0.09 -> 72)")

    def test_SW_T04_the_221_ms_pulse_fixture(self):
        self.scene()
        self.run_in()
        series = self.pulse(1.0)
        self.stop_at(series[0])
        self.after(series[1:80])                                                       # 1.36 s of 17 ms frames
        last = self.last()
        self.assertTrue(204 <= last["delay_ms"] <= 238, "NO-TRACKER: stop_sway_peak_delay_ms ~ 221 (got %r)" % last["delay_ms"])
        self.assertAlmostEqual(last["state_peak"], 0.06687, delta=3e-4)
        self.assertEqual(last["n_peak"], 53, "NO-TRACKER: a 1 m/s2 stop is n=53")
        self.assertEqual(last["end_reason"], "t-plus-1s")

    def test_SW_T05_the_window_ends_at_one_second_and_later_samples_are_ignored(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        for k in range(1, 62):                                                         # 17 ms frames: T + 0.017 .. T + 1.037
            self.step(dt=0.017, speed=0.0, calc_g=0.0, az=0.0, sway=((-0.5 if k == 61 else -0.02), 0.0, 0.0, 0.0))
        last = self.last()
        self.assertEqual(last["end_reason"], "t-plus-1s", "NO-TRACKER")
        self.assertAlmostEqual(last["state_peak"], 0.02, places=9, msg="NO-TRACKER: a sample after T+1.0 s must not be searched")

    def test_SW_T06_a_restart_ends_the_window_and_its_own_sample_is_not_in_it(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        self.after([(-0.04, 0.0, 0.0, 0.0)] * 3)
        self.step(dt=0.017, speed=0.5, calc_g=0.05, az=0.5, sway=(-0.4, 0.0, 0.0, 0.0))      # the train starts again
        last = self.last()
        self.assertEqual(last["end_reason"], "restart", "NO-TRACKER")
        self.assertAlmostEqual(last["state_peak"], 0.04, places=9, msg="NO-TRACKER: the sample of the restart tick is not part of the window")
        self.assertTrue(last["valid"])

    def test_SW_T07_a_target_change_ends_the_window(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        self.after([(-0.04, 0.0, 0.0, 0.0)] * 2)
        self.o.bve_tgt_idx = self.o.bve_tgt_idx + 1
        self.after([(-0.4, 0.0, 0.0, 0.0)])
        self.assertEqual(self.last()["end_reason"], "target-change", "NO-TRACKER")
        self.assertAlmostEqual(self.last()["state_peak"], 0.04, places=9)

    def test_SW_T08_a_station_index_change_ends_the_window(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        self.after([(-0.04, 0.0, 0.0, 0.0)] * 2)
        self.o.bve_arr_idx = self.o.bve_arr_idx + 1
        self.after([(-0.4, 0.0, 0.0, 0.0)])
        self.assertEqual(self.last()["end_reason"], "station-index-change", "NO-TRACKER")

    def _open_window(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.02, 0.0, 0.0, 0.0))
        self.after([(-0.05, 0.0, 0.0, 0.0)] * 2)
        st = self.sh()
        if getattr(st, "window", None) is None:
            self.fail("NO-TRACKER: no open window after the stop")
        return st

    def assertCut(self, label, reason):
        last = self.last()
        self.assertEqual(last["end_reason"], reason, "NO-TRACKER: %s must end the window with %r (got %r)" % (label, reason, last["end_reason"]))
        self.assertFalse(last["valid"], "NO-TRACKER: a window cut by %s belongs to the discarded world: not valid" % label)
        self.assertIsNone(self.sh().window, "NO-TRACKER: the window is closed after %s" % label)

    def test_SW_T09_a_jump_ends_the_window(self):
        self._open_window()
        self.step(dt=0.017, speed=1.0, calc_g=0.0, az=0.0, sway=(-0.3, 0.0, 0.0, 0.0), jump=1, official=True)
        self.assertCut("a Jump", "jump")

    def test_SW_T10_the_retry_and_scoring_start_discard_ends_the_window(self):
        self._open_window()
        self.S.reset_transient_scoring_state(self.o)                                    # the formal discard of the Retry / scoring start / time going backwards
        self.assertCut("the Retry discard", "discard")

    def test_SW_T11_f5_and_the_session_end_end_the_window(self):
        self._open_window()
        self.MI.discard_scoring_session(self.o)
        self.assertCut("F5 / the session end", "session-end")

    def test_SW_T12_a_new_scenario_generation_ends_the_window(self):
        self._open_window()
        self.MI.discard_generation_state(self.o)
        self.assertCut("a new generation", "generation")

    def test_SW_T13_the_end_of_the_scoring_ends_the_window(self):
        self._open_window()
        self.o.is_scoring_finished = True
        self.after([(-0.4, 0.0, 0.0, 0.0)])
        self.assertEqual(self.last()["end_reason"], "scoring-end", "NO-TRACKER: is_scoring_finished ends the window")
        self.new_rig()
        self._open_window()
        self.o.is_scoring_mode = False
        self.after([(-0.4, 0.0, 0.0, 0.0)])
        self.assertEqual(self.last()["end_reason"], "scoring-end", "NO-TRACKER: switching the scoring off ends the window")

    def test_SW_T23_a_boundary_clears_the_peak_that_a_closed_valid_window_left_on_the_display(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.0653, 0.0, 0.0, 0.0))
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-0.0653, 0.0, 0.0, 0.0))             # the window closes by itself, valid
        st = self.sh()
        self.assertTrue(self.last()["valid"] and st.display_peak_n() == 52, "NO-TRACKER: the closed valid window shows its peak")
        self.MI.discard_scoring_session(self.o)                                                     # no window is open now, but the old world must not stay on the display
        self.assertIsNone(self.sh().display_peak_n(), "NO-TRACKER: a formal boundary clears the display value (nothing of the old world is carried over)")

    def test_SW_T22_the_sample_of_the_stop_instant_itself_is_in_the_window(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.09, 0.0, 0.0, 0.0))                                           # the largest state is the one of T itself
        self.after([(-0.02, 0.0, 0.0, 0.0)] * 3)
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
        last = self.last()
        self.assertAlmostEqual(last["state_peak"], 0.09, places=9, msg="NO-TRACKER: the sample of T belongs to the window")
        self.assertEqual(last["delay_ms"], 0.0, "NO-TRACKER: a peak at T has no delay")

    def test_SW_N01_the_pseudo_turnback_stop_closes_the_window_and_changes_nothing_else(self):
        """Non-interference: the safe stop of an internal pseudo-turnback failure goes through the formal discard; with an open sway window the visible result is the same."""
        stop = getattr(self.S, "turnback_stop_scoring", None)
        if stop is None:
            self.skipTest("the pseudo-turnback stop does not exist in this tree")
        self._open_window()
        stop(self.o, "sway-non-interference")
        with_window = self.F.snapshot(self.o)
        self.assertCut("the pseudo-turnback stop", "discard")
        self.new_rig()
        self.scene()
        self.run_in()
        self.stop_at(None)
        self.after([None] * 2)
        stop(self.o, "sway-non-interference")
        self.assertEqual(self.F.differences(with_window, self.F.snapshot(self.o)), [], "SWAY-LEAKS: the open sway window changed the pseudo-turnback stop")

    def test_SW_T14_a_stop_during_an_official_jump_opens_no_window(self):
        self.scene()
        self.run_in()
        self.step(speed=0.0, calc_g=-0.2, az=-2.0, sway=(-0.3, 0.0, 0.0, 0.0), official=True)
        st = self.sh()
        self.assertIsNone(getattr(st, "window", None), "NO-TRACKER: is_official_jumping must also stop the sway window")

    def test_SW_T15_no_sample_in_the_window_is_unavailable_never_zero(self):
        self.scene()
        self.run_in()
        self.stop_at(None)
        for _ in range(70):
            self.step(dt=0.017, speed=0.0, calc_g=0.0, az=0.0, sway=None)
        last = self.last()
        self.assertTrue(last.get("unavailable"), "NO-TRACKER: no SWAY sample at all -> unavailable")
        self.assertIsNone(last["n_peak"], "NO-TRACKER: unavailable is not 0")
        self.assertIsNone(last["state_peak"])

    def test_SW_T16_the_samples_of_a_closed_window_are_not_reused_by_the_next_stop(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.02, 0.0, 0.0, 0.0))
        self.after([(-0.3, 0.0, 0.0, 0.0)])
        self.step(dt=0.017, speed=0.5, calc_g=0.05, az=0.5, sway=None)                  # restart: the first window is closed with -0.3
        self.accelerate(8, az=0.8)
        for i in range(6):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.02, az=-0.9)
        self.stop_at((-0.01, 0.0, 0.0, 0.0))
        self.after([(-0.03, 0.0, 0.0, 0.0)] * 2)
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-0.02, 0.0, 0.0, 0.0))
        self.assertAlmostEqual(self.last()["state_peak"], 0.03, places=9, msg="NO-TRACKER: the second stop must not see the -0.3 of the first window")

    def test_SW_T17_the_shadow_sway_candidates_follow_the_stop_peak_n(self):
        for state, n, pen in ((0.0425, 34, -100), (0.0645, 51, -100), (0.065, 52, -200), (0.0, 0, 0)):
            self.new_rig()
            self.scene()
            self.run_in()
            self.stop_at((-state, 0.0, 0.0, 0.0))
            self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-state, 0.0, 0.0, 0.0))
            last = self.last()
            self.assertEqual((last["n_peak"], last["penalty_sway"]), (n, pen), "NO-TRACKER: state %r -> n %d -> shadow_penalty_sway %d" % (state, n, pen))

    def test_SW_T18_the_combined_peak_is_reference_only_and_is_recorded_beside(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.03, 0.0, -0.02, 0.0))
        self.after([(-0.05, 0.0, -0.04, 0.0), (-0.04, 0.0, 0.03, 0.0)])
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
        last = self.last()
        self.assertEqual(last["n_peak"], ref_n(0.05), "NO-TRACKER: the main n comes from the longitudinal state only")
        self.assertEqual(last["combined_n_peak"], ref_n(0.09), "NO-TRACKER: stop_sway_combined_n_peak = the largest combined n in the window (reference only)")
        self.assertNotEqual(last["n_peak"], last["combined_n_peak"])
        self.assertEqual(last["penalty_sway"], -200 if ref_n(0.05) >= 52 else (-100 if ref_n(0.05) >= 34 else 0), "NO-TRACKER: the Shadow candidate follows the longitudinal n_peak (40 -> -100), not the larger combined one")
        self.assertEqual(last["penalty_sway"], -100)

    def test_SW_T19_the_reflection_can_be_unavailable_while_the_replica_goes_on(self):
        lines = self.capture_log(True)
        self.scene()
        self.accelerate(az=-0.9)
        for i in range(8):
            self.step(dt=0.017, speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.02, az=-0.9, ax=0.0, sway=None)
        self.step(dt=0.017, speed=0.0, calc_g=-0.02, az=-0.9, ax=0.0, sway=None)
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, ax=0.0, sway=None)
        text = [l for l in lines if "[SHADOW SWAY]" in l]
        if not text:
            self.fail("NO-LOG: no [SHADOW SWAY] line for the window")
        self.assertIn("sway_reflection_available=0", text[0])
        self.assertIn("stop_sway_longitudinal_n_peak=unavailable", text[0], "NO-TRACKER: unavailable is not 0")
        self.assertIn("shadow_penalty_sway=not-evaluated", text[0])
        self.assertNotIn("reconstructed_longitudinal_state=unavailable", text[0], "NO-REPLICA: the replica goes on when the reflection is not there")

    def test_SW_T20_the_version_unsupported_diagnostic_is_a_reason_and_not_a_value(self):
        W = self.W()
        lines = self.capture_log(True)
        self.o.apply_telemetry_text(self.F.line("current", 1, 36000100, 10.0, 101.0, SWAYR="version-unsupported:5.9.0.1:current"))
        self.o.apply_telemetry_text(self.F.line("current", 1, 36000200, 10.0, 102.0, SWAYR="version-unsupported:5.9.0.1:current"))
        res = getattr(self.o, "bve_sway_res", None)
        self.assertEqual((res or {}).get("result"), "version-unsupported", "NO-WIRE: the resolution diagnostic is kept")
        self.assertIsNone(getattr(self.o, "bve_sway", "missing"), "NO-WIRE: no SWAY and no stale value")
        reasons = [l for l in lines if "[SHADOW SWAY RESOLVE]" in l]
        self.assertEqual(len(reasons), 1, "NO-LOG: the reason is logged once (and only for a change), not for every line")
        self.assertIn("version-unsupported", reasons[0])

    def test_SW_T21_the_warm_up_is_reported_and_not_compared(self):
        lines = self.capture_log(True)
        self.scene()
        self.run_in()
        series = self.pulse(1.0, 1500)
        self.step(dt=0.017, speed=1.0, calc_g=0.0, az=0.0, sway=None, jump=1, official=True)       # a Jump: the replica starts cold
        self.step(dt=0.017, speed=1.0, calc_g=0.0, az=0.0, sway=series[0], official=False)
        self.step(dt=0.017, speed=0.0, calc_g=0.0, az=-0.9, sway=series[0])
        self.after(series[1:70])
        text = [l for l in lines if "[SHADOW SWAY]" in l]
        if not text:
            self.fail("NO-LOG: no [SHADOW SWAY] line")
        self.assertIn("reflection_reconstruction_delta=warmup", text[-1], "NO-REPLICA: within 3.0 s of the reset the comparison is 'warmup'")


class L_Log(Direct):
    FIELDS = ("bve_version", "sway_reflection_available", "sway_reflection_reason", "sway_longitudinal_state", "sway_longitudinal_velocity", "sway_lateral_state",
              "sway_lateral_velocity", "sway_longitudinal_n", "sway_longitudinal_color", "sway_combined_state", "sway_combined_n", "sway_combined_color", "lateral_effect_n",
              "reconstructed_longitudinal_state", "reconstructed_longitudinal_n", "reflection_reconstruction_delta", "stop_sway_longitudinal_n_peak",
              "stop_sway_longitudinal_state_peak", "stop_sway_combined_n_peak", "stop_sway_peak_delay_ms", "shadow_penalty_calcg", "shadow_penalty_bveg",
              "shadow_penalty_sway", "official_jumping", "scenario_generation", "station_index", "target_station_index")

    def one_window(self, lines, a=1.0, ax=0.0):
        self.scene()
        self.accelerate(az=-a)
        for i in range(8):                                                                  # 8 x 70 ms: the whole 0.5 s window of the CalcG judgement is braking (0.09 G)
            self.step(dt=0.07, speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.09, az=-a, ax=ax)
        series = self.pulse(a, 1200)
        self.o.bve_sway_res = {"result": "ok", "version": "5.8.7554.391", "entry": "current", "detail": ""}
        self.step(dt=0.017, speed=0.0, calc_g=-0.09, az=-a, ax=ax, sway=series[0])
        for s in series[1:70]:
            self.step(dt=0.017, speed=0.0, calc_g=0.0, az=0.0, ax=ax, sway=s)
        return [l for l in lines if "[SHADOW SWAY]" in l]

    def test_SW_L01_one_line_per_closed_window_with_every_field(self):
        lines = self.capture_log(True)
        text = self.one_window(lines)
        if not text:
            self.fail("NO-LOG: no [SHADOW SWAY] line")
        self.assertEqual(len(text), 1, "NO-LOG: one line per closed window")
        for key in self.FIELDS:
            self.assertRegex(text[0], r"(^|\s)%s=" % re.escape(key), "NO-LOG: %s= is missing" % key)

    def test_SW_L02_the_values_in_the_line(self):
        lines = self.capture_log(True)
        text = self.one_window(lines)
        if not text:
            self.fail("NO-LOG: no [SHADOW SWAY] line")
        self.assertIn("sway_reflection_available=1", text[0])
        self.assertIn("bve_version=5.8.7554.391", text[0])
        self.assertIn("stop_sway_longitudinal_n_peak=53", text[0])
        self.assertIn("shadow_penalty_sway=-200", text[0])
        self.assertIn("shadow_penalty_calcg=-100", text[0], "the CalcG candidate of the same stop (0.09 G)")
        self.assertRegex(text[0], r"lateral_effect_n=0\b", "NO-LOG: lateral_effect_n = sway_combined_n - sway_longitudinal_n")

    def test_SW_L03_the_lateral_effect_is_the_combined_n_minus_the_longitudinal_n(self):
        lines = self.capture_log(True)
        self.scene()
        self.accelerate(az=-0.9)
        self.step(dt=0.017, speed=2.0, calc_g=-0.02, az=-0.9)
        self.step(dt=0.017, speed=0.0, calc_g=-0.02, az=-0.9, sway=(-0.0500, 0.0, -0.0300, 0.0))
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-0.0500, 0.0, -0.0300, 0.0))
        text = [l for l in lines if "[SHADOW SWAY]" in l]
        if not text:
            self.fail("NO-LOG: no line")
        self.assertIn("lateral_effect_n=%d" % (ref_n(0.08) - ref_n(0.05)), text[0], "NO-LOG: lateral_effect_n")

    def test_SW_L04_the_reference_only_nature_of_the_combined_value_is_in_the_line(self):
        lines = self.capture_log(True)
        text = self.one_window(lines)
        if not text:
            self.fail("NO-LOG: no line")
        self.assertIn("combined=reference-only", text[0], "NO-LOG: the combined value is marked as reference only")

    def test_SW_L05_nothing_is_written_when_the_desktop_log_is_off(self):
        lines_on = self.capture_log(True)
        if not self.one_window(lines_on):
            self.fail("NO-LOG: the enabled log has no line (the switch cannot be judged)")
        self.new_rig()
        lines_off = self.capture_log(False)
        self.assertEqual(self.one_window(lines_off), [])


class H_Hud(Direct):
    def f2(self):
        from PyQt6.QtGui import QImage, QPainter
        import hud_ui
        texts, rects = [], []

        class Spy(QPainter):
            def drawText(self, *args):
                if len(args) == 3 and isinstance(args[2], str):
                    texts.append((args[0], args[1], args[2]))
                return super().drawText(*args)

            def drawRect(self, *args):
                if len(args) == 4:
                    rects.append(args)
                return super().drawRect(*args)

        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = Spy(image)
        try:
            self.o.show_graph = True
            hud_ui.draw_hud(self.o, painter, 1920)
        finally:
            painter.end()
        box = [t for t in texts if t[0] == 20 and t[1] >= 500]
        return [t[2] for t in box], rects, box

    def want(self, lines, text):
        if text not in lines:
            self.fail("NO-HUD: %r is not in the F2 text %r" % (text, [l for l in lines if "CalcG" in l or "前後" in l or "合成" in l]))

    def prime(self, n_z_state=0.043, lateral=-0.0025, peak_state=0.0653):
        """Current tick: longitudinal 0.043 (n=34), combined 0.0405 (n=32); the last window peak 0.0653 (n=52)."""
        self.scene()
        self.run_in()
        self.stop_at((-peak_state, 0.0, 0.0, 0.0))
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-peak_state, 0.0, 0.0, 0.0))     # closes the window
        self.step(dt=0.017, speed=0.0, calc_g=0.0, az=0.0, sway=(n_z_state, 0.0, lateral, 0.0))

    def test_SW_H01_f2_has_three_lines_and_the_third_is_the_short_form(self):
        self.prime()
        lines, _, _ = self.f2()
        self.want(lines, "前後34[黄橙]    前後最大52[赤橙]    合成32[参考]")

    def test_SW_H02_the_existing_two_lines_are_unchanged(self):
        self.prime()
        self.o.bve_calc_g = 0.086
        self.o.bve_accel_z = 0.081 * G
        self.o.last_stop_g = -0.074
        self.o.last_stop_g_bve = 0.070
        lines, _, _ = self.f2()
        self.want(lines, "CalcG: +0.086 G    BveG: +0.081 G")
        self.want(lines, "LastStop CalcG: 0.074 G    LastStop BveG: 0.070 G")
        sway = [i for i, l in enumerate(lines) if l.startswith("前後")]
        self.assertEqual(len(sway), 1, "NO-HUD: exactly one sway line")
        self.assertEqual(sway[0], lines.index("LastStop CalcG: 0.074 G    LastStop BveG: 0.070 G") + 1, "NO-HUD: the sway line is the third Shadow line, right below the two existing ones")

    def test_SW_H03_unavailable_values_are_dashes_never_zero_and_never_a_colour(self):
        self.scene()
        self.o.bve_sway = None
        lines, _, _ = self.f2()
        self.want(lines, "前後--    前後最大--    合成--[参考]")
        joined = "\n".join(lines)
        for banned in ("前後0[", "前後0 ", "合成0["):
            self.assertNotIn(banned, joined, "NO-HUD: an unavailable value is not 0")

    def test_SW_H04_the_combined_value_is_labelled_as_reference_and_never_gets_a_colour(self):
        self.prime()
        lines, _, _ = self.f2()
        row = [l for l in lines if l.startswith("前後")][0] if any(l.startswith("前後") for l in lines) else self.fail("NO-HUD: no sway line")
        combined = row[row.index("合成"):]
        self.assertTrue(combined.endswith("[参考]"), "NO-HUD: 合成 is shown as 合成32[参考]")
        for name in ("緑", "黄", "橙", "赤"):
            self.assertNotIn(name, combined, "NO-HUD: the combined value shows no colour name")

    def test_SW_H05_the_longest_third_line_fits_inside_the_box(self):
        worst = ("前後100[赤]    前後最大100[赤橙]    合成100[参考]", "前後58[赤橙]    前後最大58[赤橙]    合成58[参考]", "前後27[黄橙]    前後最大27[黄橙]    合成27[参考]")
        script = ("import os,sys\nos.environ['QT_QPA_PLATFORM']='offscreen'\nfrom PyQt6.QtWidgets import QApplication\nfrom PyQt6.QtGui import QFont, QFontMetrics\n"
                  "app=QApplication([])\nm=QFontMetrics(QFont('sans-serif',14,QFont.Weight.Bold))\nfor t in sys.argv[1:]:\n    print(m.horizontalAdvance(t))\n")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        out = subprocess.run([sys.executable, "-B", "-c", script] + list(worst), capture_output=True, text=True, env=env, timeout=120)
        widths = [int(x) for x in out.stdout.split()]
        if len(widths) != len(worst):
            self.fail("NO-HUD: the width could not be measured: %s" % out.stderr[-200:])
        for text, width in zip(worst, widths):
            self.assertLessEqual(width, 930, "NO-HUD: %r is %d px (the box is 950 px wide, the text starts at x=20)" % (text, width))
        if not exists("sway_shadow.py"):
            self.fail("NO-HUD: the sway line is not implemented yet")

    def test_SW_H06_at_most_eighteen_lines_and_the_box_bottom_is_near_850(self):
        self.prime()
        self.o.rollback_msg = "x"
        self.o.rollback_msg_timer = 1e9
        lines, rects, box = self.f2()
        if not any(l.startswith("前後") for l in lines):
            self.fail("NO-HUD: no sway line")
        self.assertLessEqual(len(box), 18, "NO-HUD: at most 18 lines (the scoring rules take 4 of them)")
        sized = [r for r in rects if r[0] == 5 and r[2] == 950]
        self.assertTrue(sized, "NO-HUD: the box is drawn")
        x, y, w, h = sized[-1]
        self.assertEqual(h, 20 * len(box) + 10, "the box height follows the line count")
        self.assertLessEqual(y + h, 850, "NO-HUD: the box bottom stays at or above y=850")

    def test_SW_H07_no_automatic_switch_between_a_long_and_a_short_form(self):
        text = code_py("hud_ui.py")
        if "前後最大" not in text:
            self.fail("NO-HUD: the third line is not in hud_ui.py yet")
        rows = text.split("\n")
        at = [i for i, row in enumerate(rows) if "前後最大" in row]
        around = "\n".join(rows[max(0, at[0] - 25):at[-1] + 12])
        for banned in ("horizontalAdvance", "fontMetrics", "boundingRect", "QFontMetrics"):
            self.assertNotIn(banned, around, "NO-HUD: the Owner asked for one short form, not a width-dependent switch (%s near the sway line)" % banned)

    def test_SW_H09_the_peak_shown_is_the_longitudinal_one_not_the_combined_one(self):
        self.scene()
        self.run_in()
        self.stop_at((-0.0653, 0.0, -0.05, 0.0))                                       # combined 0.1153 (n=73), longitudinal 0.0653 (n=52)
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(-0.0653, 0.0, -0.05, 0.0))
        self.step(dt=0.017, speed=0.0, calc_g=0.0, az=0.0, sway=None)
        lines, _, _ = self.f2()
        self.want(lines, "前後--    前後最大52[赤橙]    合成--[参考]")

    def test_SW_H10_an_announced_gap_of_sway_shows_dashes_even_when_a_value_is_there(self):
        self.scene()
        self.o.bve_sway = (-0.05, 0.0, 0.0, 0.0)

        class Avail(object):
            def has(self, token):
                return token != "sway"

            def item(self, key):
                return True

        class Gate(object):
            availability = Avail()

        self.o.telemetry_gate = Gate()
        lines, _, _ = self.f2()
        self.want(lines, "前後--    前後最大--    合成--[参考]")

    def test_SW_H08_no_maxg_and_no_graph(self):
        self.prime()
        lines, _, _ = self.f2()
        joined = "\n".join(lines)
        self.assertNotIn("MaxG", joined)
        import hud_ui
        self.assertFalse(hud_ui.G_GRAPH_ENABLED)
        if "前後最大" not in joined:
            self.fail("NO-HUD: no sway line")


class X_Score(Direct):
    """The most important GUARD (SG01) and its RED twin (SW_T20 by number): changing every Shadow sway value changes nothing the score, the history, the checkpoints or the result show."""
    def run_scene(self, sway_scale, az_scale, ax_scale, withres):
        self.new_rig()
        self.scene()
        self.accelerate(az=0.8 * az_scale)
        for i in range(8):
            self.step(dt=0.017, speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.09, az=-0.9 * az_scale, ax=0.3 * ax_scale, sway=((-0.02 * sway_scale, 0.0, 0.0, 0.0) if sway_scale else None))
        if withres:
            self.o.bve_sway_res = {"result": "ok", "version": "5.8.7554.391", "entry": "current", "detail": ""}
        self.step(dt=0.017, speed=0.0, calc_g=-0.09, az=-0.9 * az_scale, ax=0.3 * ax_scale, sway=((-0.2 * sway_scale, 0.0, 0.0, 0.0) if sway_scale else None))
        for _ in range(70):
            self.step(dt=0.017, speed=0.0, calc_g=0.0, az=0.0, ax=0.0, sway=((-0.3 * sway_scale, 0.1 * sway_scale, 0.2, 0.0) if sway_scale else None))
        o = self.o
        state = self.F.snapshot(o)
        state["g_history"] = [h[:2] for h in o.g_history]
        state["hb"] = o.hb_cushion_max_g
        return state

    def test_SG01_the_score_the_history_the_checkpoints_and_the_result_do_not_change_with_any_sway_value(self):
        ref = self.run_scene(0, 1.0, 1.0, False)
        for label, args in (("small", (1.0, 1.0, 1.0, True)), ("huge", (50.0, 5.0, 5.0, True)), ("reflection only", (1.0, 0.0, 0.0, True)), ("no resolution", (3.0, 1.0, 1.0, False)),
                            ("opposite sign", (-2.0, -1.0, -1.0, True))):
            with self.subTest(sway=label):
                state = self.run_scene(*args)
                self.assertEqual(self.F.differences(ref, state), [], "SWAY-LEAKS: a sway value changed %s" % self.F.differences(ref, state))
                self.assertEqual(ref["g_history"], state["g_history"], "SWAY-LEAKS: g_history")
                self.assertEqual(ref["hb"], state["hb"], "SWAY-LEAKS: hb_cushion_max_g")

    def test_SW_X01_with_the_sway_machinery_present_the_score_is_still_unchanged(self):
        """RED twin of SG01: it needs the machinery to exist (the guard above is vacuous before it does) and then repeats the comparison with the tracker really running."""
        W = import_sway("SWAY-LEAKS")
        need(W, "state_of", "SWAY-LEAKS")
        ref = self.run_scene(0, 1.0, 1.0, False)
        state = self.run_scene(50.0, 5.0, 5.0, True)
        self.assertEqual(self.F.differences(ref, state), [], "SWAY-LEAKS: a sway value changed %s" % self.F.differences(ref, state))
        st = W.state_of(self.o)
        if getattr(st, "last", None) is None:
            self.fail("SWAY-LEAKS: the tracker did not run in the comparison (no closed window)")

    def test_SG02_the_official_score_is_calcg_and_the_bveg_shadow_is_not_the_score(self):
        self.scene()
        self.accelerate()
        for i in range(8):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.09, az=-0.1)
        self.step(speed=0.0, calc_g=-0.09, az=-0.1)
        self.assertEqual(len(self.jerk()), 1)
        self.assertIn("-100", self.jerk()[0])

    def test_SG03_sway_values_are_not_written_to_the_score_surfaces(self):
        for rel in ("scoring_logic.py", "main.py", "managed_input.py"):
            text = code_py(rel)
            for line in text.split("\n"):
                if "sway" in line.lower() and any(k in line for k in ("score_details", "add_score_popup", "save_data", "theoretical_score", "total_retry_count", "result_screen")):
                    self.fail("%s: a sway name meets a score surface: %s" % ("SWAY-LEAKS", line.strip()))

    def test_SG04_the_retry_f5_and_formal_discard_sites_still_exist(self):
        self.assertGreaterEqual(code_py("scoring_logic.py").count("reset_transient_scoring_state(self)"), 4)
        self.assertIn("def discard_scoring_session", code_py("managed_input.py"))
        self.assertIn("def discard_generation_state", code_py("managed_input.py"))

    def test_SG05_the_graph_p95_and_maxg_stay_gone(self):
        import hud_ui
        self.assertFalse(hud_ui.G_GRAPH_ENABLED)
        for rel in ("hud_ui.py", "scoring_logic.py", "main.py", "managed_input.py", "telemetry_contract.py"):
            self.assertNotRegex(code_py(rel), r"(?i)\bp95\b")
        for rel in ("main.py", "managed_input.py", "hud_ui.py", "scoring_logic.py"):
            self.assertNotIn("max_stop_g", code_py(rel))

    def test_SG06_the_shadow_stage1_values_still_work(self):
        self.scene()
        self.accelerate()
        for i in range(8):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.02, az=-0.9)
        self.step(speed=0.0, calc_g=-0.02, az=-0.9)
        self.assertAlmostEqual(self.o.last_stop_g_bve, 0.9 / G, places=6)

    def test_SG07_without_a_sample_there_is_no_fallback_to_calcg(self):
        self.scene()
        self.accelerate(az=None)
        for i in range(8):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.30, az=None)
        self.step(speed=0.0, calc_g=-0.30, az=None)
        self.assertIsNone(self.o.last_stop_g_bve)
        self.assertEqual(len(self.jerk()), 1)

    def test_SG08_the_ljx1_part_chain_is_not_touched(self):
        text = code_py("main.py")
        for key in ("SWAY:", "SWAYR:", "ACCELX:", "ACCELZ:"):
            self.assertNotIn('elif part.startswith("%s")' % key, text)

    def test_SG09_the_package_manifest_lists_the_shared_files(self):
        import json
        manifest = json.loads(read("package/source-package-manifest.json"))
        paths = {entry["path"] for entry in manifest["files"]}
        for rel in ("telemetry_contract.py", "main.py", "scoring_logic.py", "managed_input.py", "hud_ui.py", CLASS1, LEG_API, LEG_EXT, LEG_SES, CONTRACT_CS):
            self.assertIn(rel, paths)


if __name__ == "__main__":
    unittest.main()
