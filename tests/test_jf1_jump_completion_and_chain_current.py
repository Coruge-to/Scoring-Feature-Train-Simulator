"""Phase JF-1 (file F2) - CHARACTERIZATION of how the application accepts or ignores a JUMP_COMPLETE, and of the retry/start chains that depend on it
(JF-0 v2 groups J, R22, R27 and the Python half of X06). It pins what the production Python does TODAY, and nothing else.

What is NOT repeated here: the 81 tests of tests/test_jump_complete_d6.py already pin RequestId match / duplicate / stale / unknown / invalid (J01, J02, J13),
the timeout (J08), the endpoint withdrawal (J09), the generation boundary (J10), the shutdown (J11) and the supersede rule. This file adds the cases they do not
cover: a completion that matches the RequestId but not the request, a malformed or short completion, the order of a batch, the normal mode, and a few static
guards.

THE NAMES MEAN (JF-0 v2 test specification, section 0.2 and section 1 rule 7):
    test_CURRENT_...          today's neutral behaviour
    test_CURRENT_DANGER_...   a behaviour that exists today and is KNOWN to be dangerous. Passing it does NOT mean it is safe or an approved contract. Every
                              one carries (see jf0()): the JF-0 v2 id, what is dangerous, the phase that turns it into its TARGET, and the condition under
                              which the assertion is reversed or deleted.
    test_REACH_...            whether the product can reach a state at all
    test_TARGET_A_... / _B_   the future contract (A = with the Current DLL unchanged, B = needs the J3 limited release). ALL are skipped in JF-1 (the skip
                              reason names the contract id), their expectations are the contract's, never weakened. A skip is never counted as a pass.

ISOLATION: the real Overlay in the managed wiring of tests/d6_rig.py (a byte-buffer jump directory, a fake clock, the stub UDP socket: UDP 54321 / 54322 are never
bound or sent to, nothing leaves the process). JF1Rig below only SUBCLASSES D6Rig (d6_rig.py is not touched) to inject RequestIds deterministically: the n-th
request is sixteen bytes of the value n. USERPROFILE / HOME point to an empty temporary folder for the whole module and the module asserts at its end that
nothing was written there. No process is started.

Classification note: JF-0 v2 names J03, J06, J15, J19 and J20 (and X04/X06) as dangerous; this file labels exactly those as CURRENT_DANGER.
"""
import ast
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

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

import dataplane_contract as contract  # noqa: E402
import sia_rig as R  # noqa: E402

OWN_IDS = ["J03", "J04", "J05", "J06", "J07", "J12", "J14", "J15", "J16", "J17", "J18", "J19", "J20", "J21", "R22", "R27", "X06"]
DELEGATED = {"J01": "tests/test_jump_complete_d6.py", "J02": "tests/test_jump_complete_d6.py", "J08": "tests/test_jump_complete_d6.py",
             "J09": "tests/test_jump_complete_d6.py", "J10": "tests/test_jump_complete_d6.py", "J11": "tests/test_jump_complete_d6.py",
             "J13": "tests/test_jump_complete_d6.py"}
T0 = 36000000


def jf0(case_id, kind, danger=None, phase=None, flip=None):
    """Attach the JF-0 v2 metadata to a test method. kind: CURRENT | CURRENT_DANGER | REACH | TARGET."""
    def deco(fn):
        fn.jf0 = {"id": case_id, "kind": kind, "danger": danger, "phase": phase, "flip": flip}
        return fn
    return deco


def danger(case_id, what, phase, flip):
    return jf0(case_id, "CURRENT_DANGER", danger=what, phase=phase, flip=flip)


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-jf1-f2-")
    _TMP_HOME["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP_HOME["dir"].name
    os.environ["HOME"] = _TMP_HOME["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP_HOME["dir"].name)
    finally:
        for k, v in _TMP_HOME["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP_HOME["dir"].cleanup()
    if left:
        raise AssertionError("the JF-1 F2 module wrote into the redirected profile: %r" % (left,))


def read_source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def code_only(text):
    """Source without docstrings and comments (so a word in the prose of a module does not count as code)."""
    return re.sub(r"#.*", "", re.sub(r'""".*?"""', "", text, flags=re.S))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["jf1-f2"])
        import current_jump_client
        import d6_rig
        import main
        import scoring_logic
        import sia_managed_rig

        class JF1Rig(d6_rig.D6Rig):
            """D6Rig with deterministic RequestIds: request n is sixteen bytes of the value n (never all zero)."""

            def __init__(self, m, **kw):
                super().__init__(m, **kw)
                self._ids = [bytes([n]) * 16 for n in range(1, 60)]
                self.client = current_jump_client.CurrentJumpClient(
                    self.pid, self.instance, d6_rig.APP_PID, lambda data, port: self.o._send_jump_datagram(data, port), source=self.jump_dir,
                    log=self.jump_lines.append, clock=self.clock32.monotonic, id_factory=lambda: self._ids.pop(0))
                self.o.jump_client = self.client

        cls.main, cls.S, cls.D, cls.MR, cls.Rig = main, scoring_logic, d6_rig, sia_managed_rig, JF1Rig

    def setUp(self):
        self.r = self.Rig(self.main)
        self.addCleanup(self.r.close)
        self.o = self.r.o

    # helpers ---------------------------------------------------------------------------------------------------------------------------------
    def start(self, end_idx=1):
        r, o = self.r, self.o
        r.go_active()
        o.setting_end_idx = end_idx
        r.start_scoring_via_menu()
        return r.last_command()

    def telemetry(self, t, **kw):
        kw.setdefault("JUMP", 1)
        self.r.send(self.MR.tele(1, time_ms=t, **kw))
        self.r.tick(2)

    def bve_jumped(self):
        self.telemetry(T0, speed=0.0, loc=0.0)

    def rejected_logs(self):
        return [m for m in self.r.rig.log if m.startswith("[JUMP COMPLETE REJECTED]")]

    def raw_completion(self, rid, text):
        self.r.send_raw(self.r.wrap(text, request_id=rid))
        self.r.tick(2)

    def started_and_jumped(self):
        cmd = self.start()
        self.bve_jumped()
        return cmd["request_id"]


# ==============================================================================================================================================
class J_Completion(Base):
    # -- J03 -------------------------------------------------------------------------------------------------------------------------------------
    @danger("J03", "a completion with the right RequestId but another location is only logged: the official jump stays on, the request is finished (no timeout, nothing is reported), "
                   "so the scoring is dead while it looks on",
            "JF-2 (TARGET-A K4 / FC-2 / FC-5: a mismatch aborts the scoring, no silent stuck state)", "the mismatch aborts; this assertion is replaced by TARGET_A_J03")
    def test_CURRENT_DANGER_J03_location_mismatch_leaves_official_jump_stuck_silently(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        self.assertTrue(o.jump_lock)
        r.complete(rid, location=500.0, time_ms=T0, count=1)
        r.tick(2)
        self.assertTrue(o.is_official_jumping)
        self.assertIsNone(o.pending_jump_complete)
        self.assertTrue(o.is_scoring_mode)                              # the scoring looks on ...
        self.assertTrue(o.jump_lock)                                    # ... but every scoring feature behind the lock is dead
        self.assertEqual(len(self.rejected_logs()), 1)
        self.assertFalse(r.client.has_outstanding)                      # the request counts as completed ...
        self.assertEqual(r.client.counts["completed"], 1)
        r.clock32.now += 3600.0                                         # ... so an hour later there is still no timeout and no report
        self.telemetry(T0 + 1000, speed=0.0, loc=0.0)
        self.assertIsNone(r.client.take_unreleased())
        self.assertIsNone(r.client.last_failure)
        self.assertTrue(o.is_official_jumping)
        self.assertTrue(o.is_scoring_mode)

    # -- J04 -------------------------------------------------------------------------------------------------------------------------------------
    @jf0("J04", "CURRENT")
    def test_CURRENT_J04_a_location_error_of_0_0099_is_accepted(self):
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=0.0099, time_ms=T0)
        self.assertFalse(o.is_official_jumping)

    @jf0("J04", "CURRENT")
    def test_CURRENT_J04_a_location_error_of_exactly_0_01_is_rejected(self):
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=0.01, time_ms=T0)
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(len(self.rejected_logs()), 1)

    @jf0("J04", "CURRENT")
    def test_CURRENT_J04_an_unset_expected_location_never_matches(self):
        r, o = self.r, self.o
        cmd = self.start()
        o.expected_target_loc = -1.0
        r.complete(cmd["request_id"], location=-1.0, time_ms=T0)
        self.assertTrue(o.is_official_jumping)

    # -- J05 - J07 : what is NOT checked -------------------------------------------------------------------------------------------------------
    @jf0("J05", "CURRENT")
    def test_CURRENT_J05_the_completion_time_is_not_compared_with_the_expected_time(self):
        """CURRENT: only the location decides. The tolerance of a time check is an open decision (U-1) and no expectation of it is placed here."""
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=0.0, time_ms=12345)
        self.assertFalse(o.is_official_jumping)

    @danger("J06", "the station index of the completion is not compared with the requested one: a completion that names another station releases the jump",
            "JF-2 (TARGET-A K3 / FC-2: a different index aborts) and JF-3 (TARGET-B K7 with NEXTIDX)", "this assertion is replaced by TARGET_A_J06")
    def test_CURRENT_DANGER_J06_station_index_is_not_checked_on_completion(self):
        r, o = self.r, self.o
        cmd = self.start()
        self.assertEqual(cmd["text"], "JUMP_STA_TIME:0:%d" % T0)
        r.complete(cmd["request_id"], location=0.0, time_ms=T0, index=2)
        self.assertFalse(o.is_official_jumping)

    @jf0("J07", "CURRENT")
    def test_CURRENT_J07_the_jump_kind_of_the_completion_is_not_compared_with_the_request(self):
        r, o = self.r, self.o
        cmd = self.start()
        self.assertTrue(cmd["text"].startswith("JUMP_STA_TIME:"))
        r.complete(cmd["request_id"], location=0.0, time_ms=T0, kind="LOC", index=-1)
        self.assertFalse(o.is_official_jumping)

    # -- J12 : a second request while one is outstanding ---------------------------------------------------------------------------------------
    @jf0("J12", "CURRENT")
    def test_CURRENT_J12_the_application_does_not_refuse_a_new_request_while_one_is_outstanding(self):
        """CURRENT: the second request is sent and the client supersedes the first. The old RequestId can only answer 'stale' (d6 tests); the refusal at the
        application layer is the TARGET (V-8)."""
        r, o = self.r, self.o
        first = self.start()
        second_id = o.send_jump_command("JUMP_STA_TIME:0:%d" % T0)
        self.assertIsNotNone(second_id)
        self.assertNotEqual(second_id, first["request_id"])
        self.assertEqual(len([c for c in r.jump_commands() if not c.get("other")]), 2)
        self.assertEqual(r.client.outstanding_id, second_id)
        r.complete(first["request_id"], location=0.0, time_ms=T0)             # the superseded request answers 'stale' and releases nothing
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(r.client.reasons.get("complete-stale"), 1)

    # -- J14 : the normal mode has no identification -----------------------------------------------------------------------------------------
    # (see class N_NormalMode below)

    # -- J15 / J19 : malformed and short completions -----------------------------------------------------------------------------------------
    @danger("J15", "a completion with a non-numeric field is accepted by the RequestId check FIRST (the request is consumed) and then dies in the parser: nothing is set, nothing is logged, "
                   "the official jump stays on with no timeout",
            "JF-2 (TARGET-A K0: validate the syntax BEFORE consuming the RequestId, then abort on a mismatch)", "this assertion is replaced by TARGET_A_J15")
    def test_CURRENT_DANGER_J15_malformed_completion_consumes_request_then_sticks(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        self.raw_completion(rid, "JUMP_COMPLETE:STA:x:0.0:%d:1" % T0)
        self.assertEqual(r.client.counts["completed"], 1)                # the request was consumed ...
        self.assertFalse(r.client.has_outstanding)
        self.assertIsNone(o.pending_jump_complete)                       # ... but nothing was understood
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(self.rejected_logs(), [])                       # and nothing was said about it
        r.clock32.now += 3600.0
        self.telemetry(T0 + 1000, speed=0.0, loc=0.0)
        self.assertTrue(o.is_official_jumping)
        self.assertIsNone(r.client.take_unreleased())

    @danger("J19", "a completion with fewer than six parts is not even looked at (the request is NOT consumed): the jump stays unreleased until the 10 s timeout aborts the scoring",
            "JF-2 (TARGET-A K0: a short payload is an immediate mismatch, field=payload)", "this assertion is replaced by TARGET_A_J19")
    def test_CURRENT_DANGER_J19_short_completion_payload_waits_for_the_timeout(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        self.raw_completion(rid, "JUMP_COMPLETE:STA:0:0.0")
        self.assertEqual(r.client.counts["completed"], 0)                # NOT consumed
        self.assertTrue(r.client.has_outstanding)
        self.assertTrue(o.is_official_jumping)
        self.assertTrue(o.is_scoring_mode)
        r.clock32.now += 11.0                                            # the only way out: the 10 s timeout (the J08 path)
        self.telemetry(T0 + 1000, speed=0.0, loc=0.0)
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        self.assertEqual(r.client.last_failure, "timeout")

    # -- J16 - J18 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("J16", "CURRENT")
    def test_CURRENT_J16_two_completions_of_the_same_request_in_one_batch_release_once_and_the_second_is_a_duplicate(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        text = "JUMP_COMPLETE:STA:0:0.0:%d:1" % T0
        r.send_raw(r.wrap(text, request_id=rid), r.wrap(text, request_id=rid))
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(r.client.counts["completed"], 1)
        self.assertEqual(r.client.reasons.get("complete-duplicate"), 1)

    @jf0("J17", "CURRENT")
    def test_CURRENT_J17_the_completion_is_applied_after_the_telemetry_of_the_same_batch(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        r.send_raw(r.wrap(self.MR.tele(1, time_ms=T0 + 500, speed=0.0, loc=0.0, NEXTLOC=1500.0, JUMP=1)), r.wrap("JUMP_COMPLETE:STA:0:0.0:%d:1" % T0, request_id=rid))
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(o.bve_next_loc, 1500.0)
        self.assertEqual(o.prev_next_loc, 1500.0)                        # synchronised to the NEW telemetry of the same batch
        self.assertEqual(o.door_open_loc, 0.0)

    @jf0("J18", "CURRENT")
    def test_CURRENT_J18_after_a_rejected_completion_the_next_JUMP_count_is_treated_as_the_official_jump_and_raises_no_warning(self):
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=500.0, time_ms=T0)           # rejected: is_official_jumping stays on
        self.assertTrue(o.is_official_jumping)
        self.telemetry(T0, speed=0.0, loc=0.0, JUMP=1)                      # the sender's JUMP counter now arrives
        self.assertEqual([p for p in o.popups if p.get("category") == "警告"], [])
        self.assertTrue(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)

    # -- J20 : static --------------------------------------------------------------------------------------------------------------------------
    @danger("J20", "no failure response exists anywhere in the Python side: a jump that the sender can not run is only ever noticed by the 10 s timeout",
            "JF-3 (TARGET-B B7 / FC-7 JUMP_FAILED, needs the J3 limited release and a wire change)", "a failure message exists; this assertion is replaced by TARGET_B_J20")
    def test_CURRENT_DANGER_J20_no_failure_response_exists_in_the_python_side(self):
        for name in sorted(n for n in os.listdir(ROOT) if n.endswith(".py")):
            self.assertNotIn("JUMP_FAILED", read_source(name), name)
        self.assertFalse(hasattr(contract, "MSG_JUMP_FAILED"))
        self.assertEqual(sorted(n for n in dir(contract) if n.startswith("MSG_JUMP")), ["MSG_JUMP_COMPLETE", "MSG_JUMP_LOCATION_TIME", "MSG_JUMP_STATION_TIME"])

    # -- J21 : the four kinds of generation are not mixed ---------------------------------------------------------------------------------------
    @jf0("J21", "CURRENT")
    def test_CURRENT_J21_the_telemetry_receiver_never_compares_a_scenario_generation_or_a_scenario_id(self):
        source = read_source("telemetry_dataplane_receiver.py")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                names = [ast.dump(n) for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Attribute, ast.Constant))]
                if any(("scenario" in d.lower()) for d in names):
                    offenders.append(ast.get_source_segment(source, node))
        self.assertEqual(offenders, [])
        self.assertNotRegex(code_only(source), r"(?i)scenario_?generation")

    @jf0("J21", "CURRENT")
    def test_CURRENT_J21_the_jump_client_knows_only_the_endpoint_generation_and_no_scenario_value(self):
        code = code_only(read_source("current_jump_client.py"))
        self.assertNotRegex(code, r"(?i)scenario")
        self.assertRegex(code, r"generation")                                # the endpoint generation of the directory

    @jf0("J21", "CURRENT")
    def test_CURRENT_J21_the_endpoint_generation_and_the_scenario_generation_of_the_rig_are_different_values(self):
        r = self.r
        r.go_active(generation=1)
        self.assertEqual(r.generation, 1)                                   # the Caller's ScenarioGeneration
        self.assertEqual(r.jump_dir.generation, self.D.JUMP_GEN)            # the jump endpoint's published generation
        self.assertNotEqual(r.jump_dir.generation, r.generation)
        self.assertEqual(self.D.TELEMETRY_GEN, 7)                           # the telemetry endpoint's generation (a third value)

    # -- TARGET (skipped) ------------------------------------------------------------------------------------------------------------------------
    @unittest.skip("TARGET-A K4 / FC-2 / FC-5 (JF-2): a location mismatch aborts the scoring explicitly and nothing stays stuck")
    @jf0("J03", "TARGET")
    def test_TARGET_A_J03_a_location_mismatch_aborts_the_scoring_and_releases_the_stuck_state(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        r.complete(rid, location=500.0, time_ms=T0)
        r.tick(2)
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(len([p for p in o.popups if p.get("category") == "警告"]), 2)

    @unittest.skip("TARGET-A K3 / FC-2 (JF-2): a station index that differs from the request aborts the scoring")
    @jf0("J06", "TARGET")
    def test_TARGET_A_J06_a_station_index_mismatch_aborts_the_scoring(self):
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=0.0, time_ms=T0, index=2)
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)

    @unittest.skip("TARGET-A K2 / FC-2 (JF-2): a jump kind that differs from the request aborts the scoring")
    @jf0("J07", "TARGET")
    def test_TARGET_A_J07_a_kind_mismatch_aborts_the_scoring(self):
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=0.0, time_ms=T0, kind="LOC", index=-1)
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)

    @unittest.skip("TARGET-A V-8 (JF-2): while a request is outstanding a new one is refused at the application layer (reason jump-in-flight) and the first stays")
    @jf0("J12", "TARGET")
    def test_TARGET_A_J12_a_second_request_is_refused_while_one_is_outstanding(self):
        r, o = self.r, self.o
        first = self.start()
        self.assertIsNone(o.send_jump_command("JUMP_STA_TIME:0:%d" % T0))
        self.assertEqual(r.client.outstanding_id, first["request_id"])
        self.assertEqual(len([c for c in r.jump_commands() if not c.get("other")]), 1)

    @unittest.skip("TARGET-A K0 (JF-2): the syntax is validated BEFORE the RequestId is consumed, and a malformed completion aborts the scoring")
    @jf0("J15", "TARGET")
    def test_TARGET_A_J15_a_malformed_completion_aborts_the_scoring_and_does_not_leave_it_stuck(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        self.raw_completion(rid, "JUMP_COMPLETE:STA:x:0.0:%d:1" % T0)
        self.assertFalse(o.is_official_jumping)
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)

    @unittest.skip("TARGET-A K0 (JF-2): a payload with fewer than six parts is an immediate mismatch (field=payload) and aborts without waiting for the timeout")
    @jf0("J19", "TARGET")
    def test_TARGET_A_J19_a_short_payload_aborts_at_once(self):
        r, o = self.r, self.o
        rid = self.started_and_jumped()
        self.raw_completion(rid, "JUMP_COMPLETE:STA:0:0.0")
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)
        self.assertNotEqual(r.client.last_failure, "timeout")                    # decided by the payload check, not by the timeout

    @unittest.skip("TARGET-B B7 / FC-7 / U-12 (JF-3): a JUMP_FAILED response ends the jump at once; its format is undecided, so no wire expectation is written")
    @jf0("J20", "TARGET")
    def test_TARGET_B_J20_a_failure_response_exists(self):
        self.fail("TARGET-B B7: a failure response (JUMP_FAILED) must exist; the format is open (U-12), so this test can state no further expectation")

    @unittest.skip("TARGET-A JR-2 / JR-11 (JF-2): the request keeps the scenario generation and the endpoint generation as two separate fields")
    @jf0("J21", "TARGET")
    def test_TARGET_A_J21_the_request_has_two_separate_generation_fields(self):
        self.fail("TARGET-A JR-2 / JR-11: a JumpRequest with scenario_generation and endpoint_generation does not exist yet; nothing in today's API can state this")


# ==============================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class N_NormalMode(unittest.TestCase):
    """J14: the normal mode (no DataPlane receiver, no client): the completion carries no identification at all."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["jf1-f2-normal"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o

    def begin(self):
        o = self.o
        o.is_scoring_mode = True
        o.station_list = [R.station("A", 0.0), R.station("B", 1000.0)]
        self.S.begin_official_jump(o, 1000.0, T0)

    @jf0("J14", "CURRENT")
    def test_CURRENT_J14_a_plain_completion_is_always_acceptable_in_the_normal_mode(self):
        o = self.o
        self.assertIsNone(o.dataplane_receiver)
        self.assertFalse(o.dataplane_strict)
        self.assertTrue(o._jump_complete_acceptable())

    @jf0("J14", "CURRENT")
    def test_CURRENT_J14_an_unsolicited_completion_without_any_request_is_only_logged(self):
        o = self.o
        o.udp_socket.incoming = [b"JUMP_COMPLETE:STA:1:1000.0:%d:1" % T0]
        o.read_udp_data()
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(any(m.startswith("[JUMP COMPLETE REJECTED]") for m in self.rig.log))

    @jf0("J14", "CURRENT")
    def test_CURRENT_J14_after_the_release_a_second_plain_completion_is_rejected_and_changes_nothing(self):
        o = self.o
        self.begin()
        o.udp_socket.incoming = [b"JUMP_COMPLETE:STA:1:1000.0:%d:1" % T0]
        o.read_udp_data()
        self.assertFalse(o.is_official_jumping)
        self.rig.log.clear()
        o.udp_socket.incoming = [b"JUMP_COMPLETE:STA:1:1000.0:%d:2" % T0]
        o.read_udp_data()
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len([m for m in self.rig.log if m.startswith("[JUMP COMPLETE REJECTED]")]), 1)


# ==============================================================================================================================================
class RX_RetryAndStartChains(Base):
    # -- R22 -------------------------------------------------------------------------------------------------------------------------------------
    @jf0("R22", "CURRENT")
    def test_CURRENT_R22_a_refused_managed_send_of_a_retry_is_turned_into_a_scoring_abort_by_the_next_poll(self):
        """A retry whose send the client refuses (no jump endpoint): execute_retry returns normally with the official jump begun, and the NEXT datagram of the
        sender makes the application abort the scoring session (the same path as for the scoring start, tests/test_jump_complete_d6.py)."""
        r, o = self.r, self.o
        r.go_active()
        o.is_scoring_mode = True
        o.save_data = [{"loc": 0.0, "time_ms": T0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0},
                       {"loc": 1000.0, "time_ms": T0 + 60000, "score": 10, "score_details": dict(o.score_details), "target_loc": 1000.0, "station_name": "B", "stop_error": 0.0}]
        r.jump_dir.present = False
        self.S.execute_retry(o, 1, True)                                      # no exception
        self.assertEqual(o.udp_socket.written, [])                            # nothing was written anywhere: no fixed-port fallback
        self.assertEqual(r.client.last_failure, "send-refused:jump-directory-missing")
        self.assertTrue(o.is_official_jumping)                                # until the next datagram drives the poll
        r.send("STATUS:LOADED:RUNNING")
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        self.assertEqual(o.udp_socket.written, [])

    # -- R27 -------------------------------------------------------------------------------------------------------------------------------------
    @jf0("R27", "CURRENT")
    def test_CURRENT_R27_after_a_generation_boundary_the_save_data_is_gone_and_a_retry_does_nothing(self):
        r, o = self.r, self.o
        cmd = self.start()
        r.complete(cmd["request_id"], location=0.0, time_ms=T0)
        self.assertGreaterEqual(len(o.save_data), 1)
        r.publish(True, True, generation=2)                                     # a new ScenarioGeneration
        r.tick(3)
        self.assertEqual(o.save_data, [])
        before = len(r.jump_commands())
        self.S.execute_retry(o, 1, True)                                        # the R01 path: index >= len(save_data)
        self.S.execute_retry(o, 0, True)
        self.assertEqual(len(r.jump_commands()), before)
        self.assertFalse(o.is_official_jumping)

    # -- X06 (Python half) -----------------------------------------------------------------------------------------------------------------------
    CLOSE_STALIST = "STALIST:A=1=0.0=-1=-1=-1=15000=0=0,P=1=960.0=-1=-1=-1=15000=0=0,Q=1=1000.0=-1=-1=-1=15000=0=0,E=0=2500.0=-1=-1=-1=15000=0=1"

    def _go_with_close_stations(self):
        r = self.r
        r.go_active(with_stations=False)
        r.send(self.CLOSE_STALIST, self.MR.tele(1, time_ms=T0, STIDX=self.MR.stidx(self.CLOSE_STALIST, 2)))       # (Phase ST-2a: the sender names Q, index 2, at NEXTLOC 1000.0)
        r.tick(2)
        self.assertEqual([s["name"] for s in self.o.station_list], ["A", "P", "Q", "E"])

    @danger("X06", "starting at a station (Q, index 2) that has an earlier station (P, 40 m behind) within 50 m: Python requests index 2 and expects Q's position, the completion at "
                   "that position passes the check - while the sender re-selects P as its target after the jump. Nothing on the Python side can notice.",
            "JF-2 (TARGET-A V-4 extended: refused in advance) / JF-3 (TARGET-B B2: the sender keeps the requested index)", "refused or fixed; this assertion is replaced")
    def test_CURRENT_DANGER_X06_a_start_at_a_station_with_a_close_previous_station_passes_the_completion_check_with_the_wrong_target(self):
        """JF-0 v2 X06 describes this chain through a RETRY. In the code as it is, a retry can not produce it: the 100 m search of execute_retry picks the earlier
        station itself (see the next test). The dangerous chain exists on the SCORING START route, where setting_start_idx names the later station directly.
        The sender's re-selection (idx 1) is pinned by the C# source pins (file F3) and the LegacyStationTimeline run (file F4); it is not observable here."""
        r, o = self.r, self.o
        self._go_with_close_stations()
        o.setting_start_idx = 2
        o.setting_end_idx = 3
        r.start_scoring_via_menu()
        cmd = r.last_command()
        self.assertEqual(cmd["text"], "JUMP_STA_TIME:2:%d" % T0)
        self.assertEqual(o.expected_target_loc, 1000.0)                          # Python expects Q's position
        r.complete(cmd["request_id"], location=1000.0, time_ms=T0, index=2)       # the sender really moved to 1000.0 ...
        self.assertFalse(o.is_official_jumping)                                  # ... the completion check is satisfied; nothing is reported

    @jf0("X06", "CURRENT")
    def test_CURRENT_X06_a_retry_with_a_close_previous_station_selects_the_earlier_station_itself_so_python_and_the_sender_agree(self):
        r, o = self.r, self.o
        self._go_with_close_stations()
        o.is_scoring_mode = True
        o.save_data = [{"loc": 0.0, "time_ms": T0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0},
                       {"loc": 999.0, "time_ms": T0 + 60000, "score": 10, "score_details": dict(o.score_details), "target_loc": 1000.0, "station_name": "Q", "stop_error": 1.0}]
        self.S.execute_retry(o, 1, True)
        cmd = r.last_command()
        self.assertEqual(cmd["text"], "JUMP_STA_TIME:1:%d" % (T0 + 60000))        # P (index 1), not Q (index 2)
        self.assertEqual(o.expected_target_loc, 960.0)


# ==============================================================================================================================================
class Z_Meta(unittest.TestCase):
    KINDS = {"test_CURRENT_DANGER_": "CURRENT_DANGER", "test_CURRENT_": "CURRENT", "test_REACH_": "REACH", "test_TARGET_A_": "TARGET", "test_TARGET_B_": "TARGET"}

    @staticmethod
    def case_methods():
        for cls in (J_Completion, N_NormalMode, RX_RetryAndStartChains):
            for name in sorted(n for n in dir(cls) if n.startswith("test_")):
                yield cls, name, getattr(cls, name)

    @classmethod
    def kind_of(cls, name):
        for prefix in ("test_CURRENT_DANGER_", "test_CURRENT_", "test_REACH_", "test_TARGET_A_", "test_TARGET_B_"):
            if name.startswith(prefix):
                return cls.KINDS[prefix]
        return None

    def test_META_every_test_has_a_known_prefix_and_jf0_metadata_of_the_same_kind(self):
        count = 0
        for cls, name, fn in self.case_methods():
            count += 1
            kind = self.kind_of(name)
            self.assertIsNotNone(kind, name)
            meta = getattr(fn, "jf0", None)
            self.assertIsNotNone(meta, name)
            self.assertEqual(meta["kind"], kind, name)
            self.assertIn(meta["id"], OWN_IDS, name)
            self.assertIn(meta["id"], name)
        self.assertGreater(count, 30)

    def test_META_every_CURRENT_DANGER_carries_its_four_facts(self):
        seen = 0
        for cls, name, fn in self.case_methods():
            if self.kind_of(name) != "CURRENT_DANGER":
                continue
            seen += 1
            meta = fn.jf0
            self.assertTrue(name.startswith("test_CURRENT_DANGER_" + meta["id"]), name)
            for key, shortest in (("danger", 21), ("phase", 8), ("flip", 21)):
                self.assertTrue(meta[key] and len(meta[key]) >= shortest, (name, key))
        self.assertEqual(seen, 6)

    def test_META_every_TARGET_is_skipped_with_a_contract_id_in_the_reason(self):
        seen = 0
        for cls, name, fn in self.case_methods():
            if self.kind_of(name) != "TARGET":
                continue
            seen += 1
            self.assertTrue(getattr(fn, "__unittest_skip__", False), name)
            reason = getattr(fn, "__unittest_skip_why__", "")
            self.assertRegex(reason, r"TARGET-[AB] ", name)
            self.assertRegex(reason, r"(V-\d|K\d|FC-\d|B7|JR-\d)", name)
        self.assertGreaterEqual(seen, 8)

    def test_META_every_own_id_has_a_test_and_the_delegated_ones_name_the_existing_file(self):
        have = {fn.jf0["id"] for _c, _n, fn in self.case_methods() if hasattr(fn, "jf0")}
        self.assertEqual(sorted(set(OWN_IDS) - have), [])
        self.assertEqual(sorted(have - set(OWN_IDS)), [])
        existing = read_source(os.path.join("tests", "test_jump_complete_d6.py"))
        self.assertGreaterEqual(len(re.findall(r"^\s+def test_", existing, flags=re.M)), 81)           # the file the delegated ids rely on is still there
        self.assertEqual(set(DELEGATED.values()), {"tests/test_jump_complete_d6.py"})

    def test_META_no_test_reads_the_real_desktop_or_the_network(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            code = code_only(f.read())
        # (the words are written in two pieces so that this list does not match itself)
        for word in ("sock" "et.sock" "et", "QUdp" "Socket(", "sub" "process", "Po" "pen", "os." "system", "expand" "user", "\\" "Desk" "top", "/" "Desk" "top", "Down" "loads"):
            self.assertNotIn(word, code, word)


if __name__ == "__main__":
    unittest.main()
