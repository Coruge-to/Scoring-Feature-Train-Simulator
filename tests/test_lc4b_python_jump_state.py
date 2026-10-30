"""Phase LC-4b (Legacy scoring integration) - the Python state contract of the Jump plane, as an executable contract (LC-A14, LC-A15 and LC-A16 of the LC-1 ledger).

THE THREE CONTRACTS (the same code path for the Current and for the Legacy shape of the feed; the sender is told only by its AVAIL and by the keys of its lines)
  A14 / C-LJ-3 (i)   A Retry is refused with the existing word `jump-unavailable` while the latest accepted AVAIL names no `jump` group (the jump plane is closed or its breaker is open).
                     Nothing is built, sent, counted or changed (no RequestId, no pending retry, no outstanding jump, no history change, no score, no screen). The refusal keeps no state of
                     its own: it is derived from the latest AVAIL, so the same Retry is accepted again as soon as the sender announces `jump` again. No AVAIL at all means every group
                     is available (the Current sender): its answer is unchanged. The ST-2 words, and the order of the refusals (finish, checkpoint, jump client, jump group), are unchanged.
  A15 / C-LJ-3 (ii) An outstanding jump request ends at the client's timeout (10.0 s) although the sender is silent: the poll of the request runs on the HUD tick, not only when a
                     datagram arrives. It ends exactly as the datagram driven poll ended it (the scoring session is aborted once: scoring off, jump lock, the request cancelled so that a late
                     completion is stale). Before the deadline nothing happens; a completion in time settles the request normally; without an outstanding request the poll changes nothing.
  A16 / C-LJ-5       The reference of the sender's JUMP counter (taken again for every ScenarioGeneration) is the first accepted line that CARRIES the JUMP key. A line without the key is not
                     a reference: a counter that appears later (JUMP:3) is the baseline - no jump lock, no abort. A line with the key (the Current sender: every line) is the reference as before.
Needs PyQt6 (skipped otherwise). The Overlay is the real one against the recorders of tests/d6_rig.py: no socket, no real clock.
"""
import ast
import copy
import importlib.util
import os
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

import lc_legacy_feed as F  # noqa: E402

UNAVAILABLE = "jump-unavailable"
NO_JUMP_AVAIL = [a for a in F.LEGACY_AVAIL if a != "jump"]

_SIMPLE = (bool, int, float, str, type(None))


def _plain(v):
    if isinstance(v, _SIMPLE):
        return True
    if isinstance(v, (list, tuple)):
        return all(_plain(x) for x in v)
    if isinstance(v, dict):
        return all(_plain(k) and _plain(x) for k, x in v.items())
    return False


def scoring_snapshot(o):
    """Every plain attribute of the Overlay (numbers, strings, flags, lists of those): the whole scoring state without the Qt / socket / hook objects. A deep copy."""
    return copy.deepcopy({k: v for k, v in sorted(o.__dict__.items()) if _plain(v)})


def changed_keys(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def without_jump_key(text):
    """The line of a sender that does not write the JUMP key."""
    return ",".join(p for p in text.split(",") if not p.startswith("JUMP:"))


class Managed(unittest.TestCase):
    """The managed rig of the D6 tests (strict data plane, jump client) on the feed of one shape. The input controller keeps its own event sink (the [MANAGED] lines are read from the rig log)."""

    shape = "legacy"

    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-lc4b-")
        cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
        os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc4b"])
        import d6_rig
        import main
        import scoring_logic
        import sia_managed_rig
        import station_identity
        cls.main, cls.D, cls.MR, cls.S, cls.SI = main, d6_rig, sia_managed_rig, scoring_logic, station_identity

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls._profile_dir.cleanup()

    def setUp(self):
        self.r = self.D.D6Rig(self.main)
        self.o = self.r.o
        self.addCleanup(self.r.close)

    # -- the drive (the helpers of tests/test_lc4_retry_after_finish.py) ---------------------------------------------------------------------------------------
    def avail(self):
        return {"avail": F.LEGACY_AVAIL} if self.shape == "legacy" else {}

    def start(self, end_idx=2, generation=1):
        r, o = self.r, self.o
        r.go_active(generation=generation, **self.avail())
        o.setting_end_idx = end_idx
        r.start_scoring_via_menu()
        return r.last_command()

    def commands(self):
        return [c for c in self.r.jump_commands() if not c.get("other")]

    def land(self, cmd, t=36000000, jump=1):
        r = self.r
        r.send(F.line(self.shape, 1, t, 0.0, 0.0, jump=jump, discontinuity=True, NEXTLOC=1000.0))
        r.tick(2)
        r.complete(cmd["request_id"], location=0.0, time_ms=t, count=jump)
        r.tick(2)
        return t

    def leg(self, t, loc0, loc1, nextloc, tgt, arr, seq, jump=1, prev=(-1, 0)):
        shape, r, MR = self.shape, self.r, self.MR
        loc, v, a = loc0, 20.0, 0.5
        stop_at = loc1 - 0.4
        steps = 0
        while loc + v * v / (2 * a) < stop_at and steps < 300:
            t += 1000
            loc += v
            r.send(F.line(shape, 1, t, v * 3.6, loc, jump=jump, calcg=0.0, NEXTLOC=nextloc, STIDX=MR.stidx(MR.STALIST, tgt, prev[0], prev[1])))
            r.tick(1, 0.1)
            steps += 1
        d = stop_at - loc
        v = (2 * a * d) ** 0.5
        while v > 0.0:
            t += 1000
            nv = max(v - a, 0.0)
            loc = loc + (v + nv) / 2
            v = nv
            if v == 0.0:
                loc = stop_at
            r.send(F.line(shape, 1, t, v * 3.6, loc, jump=jump, calcg=-0.051 if v > 0.0 else 0.0, NEXTLOC=nextloc, BRK="N:4:8", STIDX=MR.stidx(MR.STALIST, tgt, prev[0], prev[1])))
            r.tick(1, 0.1)
        t += 1000
        r.send(F.line(shape, 1, t, 0.0, stop_at, jump=jump, calcg=0.0, NEXTLOC=nextloc, BRK="N:8:8", STIDX=MR.stidx(MR.STALIST, tgt, prev[0], prev[1])))
        r.tick(3, 0.1)
        t += 1000
        r.send(F.line(shape, 1, t, 0.0, stop_at, jump=jump, calcg=0.0, NEXTLOC=nextloc, DOOR=1, BRK="N:8:8", STIDX=MR.stidx(MR.STALIST, tgt, arr, seq)))
        r.tick(3, 0.1)
        return t

    def to_b(self):
        """start -> Jump(STA, idx 0) -> A to B (arrival: the first check point after the start). Returns the BVE time of the last line."""
        cmd = self.start()
        t = self.land(cmd)
        return self.leg(t, 100.0, 1000.0, 1000.0, 1, 1, 1)

    def line_at_b(self, t, avail=None, with_jump=True):
        """A stopped line at B (the check point 0 is the arrival there) of the sender whose AVAIL is `avail` (None: the shape's own)."""
        text = self.MR.tele(1, time_ms=t, speed=0.0, loc=999.6, CALCG="0.00000", DOOR=1, STIDX=self.MR.stidx(self.MR.STALIST, 1, 1, 1), **({"avail": avail} if avail is not None else self.avail()))
        return text if with_jump else without_jump_key(text)

    def outstanding(self):
        return "outstanding=1" in self.o.jump_client.summary()

    def aborts(self):
        return self.r.events("scoring-abort")


# ===================================================================================================================================================
# A14  C-LJ-3 (i): no Retry while the jump is unavailable
# ===================================================================================================================================================
class A14_RetryWhileUnavailable(Managed):
    def breaker_open(self, t):
        self.r.send(self.line_at_b(t + 1000, avail=NO_JUMP_AVAIL, with_jump=False))
        self.r.tick(2, 0.1)
        return t + 1000

    def test_JS01_a_retry_is_refused_while_the_jump_group_is_missing_and_nothing_is_sent(self):
        t = self.to_b()
        o = self.o
        self.breaker_open(t)
        self.assertFalse(o.telemetry_gate.availability.has("jump"), "PREMISE the latest AVAIL names no jump group")
        n_cmd, before, history = len(self.commands()), scoring_snapshot(o), copy.deepcopy(o.save_data)
        for position in (0, 1):
            res = self.main.execute_retry(o, position, False)
            self.assertIsInstance(res, self.SI.RetryResult)
            self.assertFalse(res.accepted, "position %r accepted while the jump is unavailable" % position)
            self.assertEqual(res.reason, UNAVAILABLE)
        self.assertEqual(len(self.commands()), n_cmd, "a Jump command was sent")
        self.assertEqual(o.save_data, history)
        self.assertEqual(changed_keys(before, scoring_snapshot(o)), [], "state changed by the refusal")
        self.assertIsNone(o.retry_pending)
        self.assertIsNone(o.jump_expectation)
        self.assertFalse(o.is_official_jumping)
        self.assertFalse(self.outstanding())

    def test_JS02_the_refusal_keeps_no_state_the_same_retry_is_accepted_when_the_group_is_back(self):
        t = self.to_b()
        o = self.o
        t = self.breaker_open(t)
        self.assertEqual(self.main.execute_retry(o, 0, False).reason, UNAVAILABLE)
        n_cmd = len(self.commands())
        self.r.send(self.line_at_b(t + 1000))                         # the sender announces `jump` again (the breaker is closed)
        self.r.tick(2, 0.1)
        self.assertTrue(o.telemetry_gate.availability.has("jump"))
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, "the refusal outlived the AVAIL (reason=%r)" % (res.reason,))
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertTrue(o.is_official_jumping)

    def test_JS03_from_the_menu_the_refusal_is_one_line_and_the_menu_stays(self):
        t = self.to_b()
        o = self.o
        self.breaker_open(t)
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        o.__dict__.pop("was_advancing_before_menu", None)
        before, n_cmd, count = scoring_snapshot(o), len(self.commands()), o.total_retry_count
        o.handle_menu_enter(True)
        lines = self.r.events("retry-rejected")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("why=%s" % UNAVAILABLE, lines[0])
        self.assertEqual((o.menu_state, o.menu_cursor), (3, 0), "the menu moved")
        self.assertNotIn("was_advancing_before_menu", o.__dict__, "the BVE resume flag was touched")
        self.assertEqual((len(self.commands()), o.total_retry_count), (n_cmd, count))
        self.assertEqual(changed_keys(before, scoring_snapshot(o)), [])

    def test_JS07_the_avail_rule_belongs_to_the_managed_mode_only(self):
        """The normal (manual) mode has no jump client and no strict data plane: its Retry is the plain one, whatever the AVAIL says."""
        t = self.to_b()
        o = self.o
        self.breaker_open(t)
        saved = (o.dataplane_strict, o.jump_client)
        o.dataplane_strict, o.jump_client = False, None
        try:
            res = self.main.execute_retry(o, 0, False)
        finally:
            o.dataplane_strict, o.jump_client = saved
        self.assertTrue(res.accepted, "the normal mode Retry was refused by the AVAIL rule (reason=%r)" % (res.reason,))
    def test_JS04_a_retry_with_the_jump_group_is_accepted_as_before(self):
        self.to_b()
        o = self.o
        self.assertTrue(o.telemetry_gate.availability.has("jump"))
        n_cmd = len(self.commands())
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertIsNotNone(o.retry_pending)

    def test_JS05_the_order_of_the_refusals_is_unchanged(self):
        t = self.to_b()
        o = self.o
        self.breaker_open(t)
        res = self.main.execute_retry(o, 99, False)                   # a position that does not exist is judged by the checkpoint rule first
        self.assertEqual((res.accepted, res.reason), (False, "no-checkpoint"))
        o.is_scoring_finished = True                                  # the finish is the first statement of all
        res = self.main.execute_retry(o, 0, False)
        self.assertEqual((res.accepted, res.reason), (False, "scoring-finished"))

    def test_JS06_the_refusal_does_not_end_the_scoring(self):
        t = self.to_b()
        o = self.o
        t = self.breaker_open(t)
        self.main.execute_retry(o, 0, False)
        self.r.tick(20, 1.0)
        self.assertTrue(o.is_scoring_mode)
        self.assertFalse(self.aborts(), self.aborts())
        self.assertEqual(len(self.commands()), 1, "the only Jump command of the run is the scoring start")


class A14_Current(A14_RetryWhileUnavailable):
    """The Current sender writes no AVAIL (every group is available): a Retry is accepted and the refusal word is never produced by the AVAIL rule."""
    shape = "current"

    def breaker_open(self, t):
        return t                                                      # the Current sender has no breaker: there is no line to send

    def test_JS01_a_retry_is_refused_while_the_jump_group_is_missing_and_nothing_is_sent(self):
        self.to_b()
        self.assertFalse(self.o.telemetry_gate.availability.explicit, "PREMISE the Current sender writes no AVAIL")
        res = self.main.execute_retry(self.o, 0, False)
        self.assertTrue(res.accepted, "a Current Retry was refused (reason=%r)" % (res.reason,))

    test_JS02_the_refusal_keeps_no_state_the_same_retry_is_accepted_when_the_group_is_back = None
    test_JS03_from_the_menu_the_refusal_is_one_line_and_the_menu_stays = None
    test_JS05_the_order_of_the_refusals_is_unchanged = None
    test_JS06_the_refusal_does_not_end_the_scoring = None
    test_JS07_the_avail_rule_belongs_to_the_managed_mode_only = None


# ===================================================================================================================================================
# A15  C-LJ-3 (ii): a silent sender does not keep an outstanding jump forever
# ===================================================================================================================================================
class A15_SilentSender(Managed):
    def assert_aborted_once(self):
        o = self.o
        self.assertFalse(o.is_official_jumping, "the jump was not ended")
        self.assertFalse(o.is_scoring_mode, "the scoring session was not aborted")
        self.assertTrue(o.jump_lock)
        self.assertIsNone(o.jump_expectation)
        self.assertFalse(self.outstanding(), "the request is still outstanding at the client")
        self.assertEqual(len(self.aborts()), 1, self.aborts())
        self.assertIn("reason=jump", self.aborts()[0])

    def test_JS10_a_silent_sender_aborts_the_session_at_the_timeout(self):
        self.start()
        self.assertTrue(self.o.is_official_jumping and self.outstanding())
        self.r.tick(3, 3.5)                                           # 10.5 s without one datagram
        self.assert_aborted_once()
        self.assertEqual(len(self.commands()), 1)
        self.r.tick(10, 3.0)                                          # and it ends once
        self.assertEqual(len(self.aborts()), 1)

    def test_JS11_nothing_happens_before_the_deadline(self):
        self.start()
        self.r.tick(1, 9.0)
        o = self.o
        self.assertTrue(o.is_official_jumping and o.is_scoring_mode and self.outstanding() and not self.aborts())
        self.r.tick(1, 0.9)                                            # 9.9 s
        self.assertTrue(o.is_official_jumping and o.is_scoring_mode and self.outstanding() and not self.aborts())
        self.r.tick(1, 0.2)                                            # 10.1 s
        self.assert_aborted_once()

    def test_JS12_a_completion_in_time_settles_the_request_and_nothing_aborts_later(self):
        cmd = self.start()
        self.r.tick(1, 3.0)
        self.r.send(F.line(self.shape, 1, 36000000, 0.0, 0.0, jump=1, discontinuity=True, NEXTLOC=1000.0))
        self.r.tick(2)
        self.r.complete(cmd["request_id"], location=0.0, time_ms=36000000, count=1)
        self.r.tick(2)
        o = self.o
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.is_scoring_mode)
        self.assertFalse(self.outstanding())
        self.r.tick(10, 3.0)                                          # the sender is silent from here on: nothing is outstanding, so nothing ends
        self.assertTrue(o.is_scoring_mode and not self.aborts())
        before, n_cmd = scoring_snapshot(o), len(self.commands())
        self.r.complete(cmd["request_id"], location=0.0, time_ms=36000000, count=1)        # the same completion a second time changes nothing and starts nothing
        self.r.tick(3, 1.0)
        self.assertEqual(len(self.commands()), n_cmd)
        self.assertTrue(o.is_scoring_mode and not o.is_official_jumping and not self.aborts())
        self.assertEqual([k for k in changed_keys(before, scoring_snapshot(o)) if "time" not in k], [])

    def test_JS13_a_late_completion_after_the_abort_is_stale_and_changes_nothing(self):
        cmd = self.start()
        self.r.tick(3, 3.5)
        self.assert_aborted_once()
        o, n_cmd = self.o, len(self.commands())
        before = scoring_snapshot(o)
        self.r.complete(cmd["request_id"], location=0.0, time_ms=36000000, count=1)
        self.r.tick(3, 1.0)
        self.assertFalse(o.is_official_jumping)
        self.assertFalse(o.is_scoring_mode, "a late completion restarted the scoring")
        self.assertTrue(o.jump_lock)
        self.assertEqual(len(self.commands()), n_cmd)
        self.assertEqual(len(self.aborts()), 1)
        self.assertEqual([k for k in changed_keys(before, scoring_snapshot(o)) if "time" not in k], [])

    def test_JS14_a_silent_retry_ends_as_a_failed_settlement_history_kept(self):
        self.to_b()
        o = self.o
        n_hist, n_cmd, count = len(o.save_data), len(self.commands()), o.total_retry_count
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertTrue(o.is_official_jumping)
        self.r.tick(3, 3.5)
        self.assert_aborted_once()
        self.assertIsNone(o.retry_pending)
        self.assertEqual(len(o.save_data), n_hist, "the history was cut by a Retry that never completed")
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertEqual(o.total_retry_count, count, "the count of a Retry that never completed")

    def test_JS15_without_an_outstanding_request_the_poll_changes_nothing(self):
        self.to_b()
        o = self.o
        self.assertFalse(o.is_official_jumping)
        before = scoring_snapshot(o)
        self.r.tick(40, 3.0)                                          # two minutes of a silent sender while driving: no request, no abort
        self.assertTrue(o.is_scoring_mode and not self.aborts())
        self.assertEqual([k for k in changed_keys(before, scoring_snapshot(o)) if "time" not in k], [])

    def test_JS16_a_new_generation_ends_the_outstanding_request_without_an_abort_line_later(self):
        self.start()
        self.r.publish(True, True, 2)                                 # F5
        self.r.tick(4)
        o = self.o
        self.assertFalse(o.is_official_jumping or o.is_scoring_mode)
        n = len(self.aborts())
        self.r.tick(10, 3.0)
        self.assertEqual(len(self.aborts()), n, "a second end of the same request")
        self.assertFalse(self.outstanding())

    def test_JS17_the_poll_runs_while_the_hud_waits_for_telemetry_too(self):
        """A generation that has no telemetry yet has no request either (the discard ended it): the poll of the tick has nothing to end and does not raise."""
        self.r.publish(True, True, 1)
        self.r.tick(40, 1.0)
        self.assertFalse(self.aborts())


class A15_Current(A15_SilentSender):
    shape = "current"


# ===================================================================================================================================================
# A16  C-LJ-5: the JUMP baseline is the first line that carries the key
# ===================================================================================================================================================
class A16_JumpBaseline(Managed):
    def keyless(self, t):
        """A line of the shape's sender WITHOUT the JUMP key (Legacy: its AVAIL then names no jump group either - the breaker is open)."""
        return without_jump_key(self.MR.tele(1, time_ms=t, **({"avail": NO_JUMP_AVAIL} if self.shape == "legacy" else {})))

    def keyed(self, t, count):
        return F.line(self.shape, 1, t, 0.0, 0.0, jump=count, NEXTLOC=1000.0)

    def first_lines(self, no_key_lines=1, count=3):
        """A generation start: the station list with `no_key_lines` lines WITHOUT the JUMP key, then one line with JUMP:`count`."""
        r, o, MR = self.r, self.o, self.MR
        r.publish(True, True, 1)
        r.tick(2)
        r.send(MR.STALIST, self.keyless(36000000))
        r.tick(2)
        for i in range(1, no_key_lines):
            r.send(self.keyless(36000000 + 1000 * i))
            r.tick(2)
        r.send(self.keyed(36000000 + 1000 * no_key_lines, count))
        r.tick(2)
        return o
    def test_JS20_a_counter_that_appears_after_a_line_without_the_key_is_the_baseline(self):
        o = self.first_lines(1, 3)
        self.assertEqual((o.last_jump_count, o.jump_lock, o.is_official_jumping), (3, False, False), "baseline: last_jump_count=%r jump_lock=%r" % (o.last_jump_count, o.jump_lock))
        self.assertFalse(o.jump_baseline_pending)
        self.assertFalse(self.aborts())

    def test_JS21_a_line_without_the_key_keeps_the_reference_open(self):
        o = self.first_lines(3, 5)
        self.assertEqual((o.last_jump_count, o.jump_lock), (5, False))
        self.assertFalse(o.jump_baseline_pending)

    def test_JS22_the_flag_stays_open_while_no_line_has_the_key(self):
        r, o, MR = self.r, self.o, self.MR
        r.publish(True, True, 1)
        r.tick(2)
        r.send(MR.STALIST, self.keyless(36000000))
        r.tick(2)
        self.assertTrue(o.jump_baseline_pending, "a line without the key closed the reference")
        self.assertEqual((o.last_jump_count, o.jump_lock), (0, False))

    def test_JS23_the_reference_is_taken_once_a_later_counter_is_a_jump(self):
        o = self.first_lines(1, 3)
        self.r.send(F.line(self.shape, 1, 36005000, 0.0, 0.0, jump=4, NEXTLOC=1000.0))        # the user jumps in BVE: the counter moves on
        self.r.tick(2)
        self.assertFalse(o.jump_baseline_pending)
        self.assertEqual(o.last_jump_count, 4, "the existing jump rule did not see the later counter")

    def test_JS24_a_new_generation_takes_the_reference_again(self):
        o = self.first_lines(1, 3)
        self.assertEqual(o.last_jump_count, 3)
        self.r.publish(True, True, 2)
        self.r.tick(4)
        self.assertTrue(o.jump_baseline_pending, "the reference of the new generation is not open")
        self.r.send(self.MR.STALIST, F.line(self.shape, 2, 36020000, 0.0, 0.0, jump=7, NEXTLOC=1000.0))        # a new scenario instance names a new SCENARIO_ID
        self.r.tick(2)
        self.assertEqual((o.last_jump_count, o.jump_lock, o.jump_baseline_pending), (7, False, False))

    def test_JS25_a_first_line_that_has_the_key_is_the_reference_as_before(self):
        r, o, MR = self.r, self.o, self.MR
        r.publish(True, True, 1)
        r.tick(2)
        r.send(MR.STALIST, F.line(self.shape, 1, 36000000, 0.0, 0.0, jump=5, NEXTLOC=1000.0))
        r.tick(2)
        self.assertEqual((o.last_jump_count, o.jump_lock, o.jump_baseline_pending), (5, False, False))

    def test_JS26_a_fresh_application_holds_no_jump_state(self):
        o = self.o
        self.assertEqual((o.last_jump_count, o.jump_lock, o.is_official_jumping, o.jump_expectation, o.retry_pending), (0, False, False, None, None))
        self.assertFalse(self.outstanding())


class A16_Current(A16_JumpBaseline):
    shape = "current"


# ===================================================================================================================================================
# static: nothing but the three statements, no new word
# ===================================================================================================================================================
class StaticContract(unittest.TestCase):
    def test_JS30_the_retry_words_of_st2_are_unchanged_and_the_refusal_uses_one_of_them(self):
        import station_identity as SI
        self.assertEqual(SI.RETRY_REASONS, ("no-checkpoint", "old-form", "retry-pending", "jump-unavailable", "time-invalid"))
        self.assertEqual(SI.JUMP_UNAVAILABLE, UNAVAILABLE)
        self.assertNotIn("telemetry_gate", read("station_identity.py"), "station_identity.py reads the AVAIL of the gate")

    def test_JS31_the_jump_group_check_follows_the_jump_client_check_in_execute_retry(self):
        tree = ast.parse(read("scoring_logic.py"))
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"][0]
        ifs = [s for s in fn.body if isinstance(s, ast.If)]
        texts = [ast.dump(s.test) for s in ifs]
        jc = [i for i, t in enumerate(texts) if "jump_client" in t]
        has = [i for i, t in enumerate(texts) if "jump_group_available" in t]
        self.assertTrue(jc and has, "the two checks are not statements of execute_retry")
        self.assertLess(jc[0], has[0])
        builder = [i for i, s in enumerate(fn.body) if "build_jump_request" in ast.dump(s) or "send_jump_command" in ast.dump(s)]
        self.assertTrue(builder)
        self.assertLess(fn.body.index(ifs[has[0]]), builder[0], "the refusal does not come before the request is built")

    def test_JS33_the_scoring_module_does_not_read_the_sender_capability_the_overlay_does(self):
        """LC-2 (test_E08): scoring_logic.py names neither the telemetry gate nor an availability. The question is the Overlay's: jump_group_available()."""
        import re
        code = read("scoring_logic.py")
        for pat in (r"telemetry_gate", r"\.availability\b", r"(?i)\bavail(able)?_groups\b"):
            self.assertIsNone(re.search(pat, code), "scoring_logic.py names the sender capability: %s" % pat)
        tree = ast.parse(read("main.py"))
        cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay"][0]
        fn = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "jump_group_available"]
        self.assertEqual(len(fn), 1)
        self.assertIn("telemetry_gate", ast.dump(fn[0]))
    def test_JS32_the_hud_tick_polls_the_jump_request_first(self):
        tree = ast.parse(read("managed_hud.py"))
        cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ManagedHudController"][0]
        fn = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_tick_active"][0]
        first = ast.dump(fn.body[1]) + ast.dump(fn.body[2])
        self.assertIn("_poll_jump_client", first)


if __name__ == "__main__":
    unittest.main()
