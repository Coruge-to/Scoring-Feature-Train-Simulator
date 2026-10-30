"""Phase LC-4 (Legacy scoring integration) - a Retry after the scoring finished is refused, as an executable contract (LC-A13 of the LC-1 ledger).

THE PROBLEM (C-SIDX-4)
  After the formal scoring-finish (arrival at the end station: is_scoring_finished) the check points of the run are still in the history, so execute_retry accepted a Retry: it sent a
  Jump request, put the score back to the check point, cleared the result state (reset_result_display_state sets is_scoring_finished False) and let the scoring run again.

THE CONTRACT
  1. a Retry requested while is_scoring_finished is REFUSED with the reason `scoring-finished`: accepted False, no RequestId, no StationIndex;
  2. the refusal is the FIRST thing execute_retry does: nothing is read or changed - no Jump command, no pending retry, no count, no score, no history, no check point, no result state,
     no screen text; the scoring does not restart and the HUD does not go back to the scoring target. The refusal holds for every position (also one that does not exist);
  3. from the menu the refusal is ONE structured line (retry-rejected, why=scoring-finished), the menu stays where it is, the BVE resume flag is not touched;
  4. the refusal keeps no state of its own: it is derived from is_scoring_finished, which a new scoring session (a new generation / F5, a new start) resets; the next session can Retry;
  5. a Retry before the finish is untouched (accepted as before); the whole contract is run on the Current AND on the Legacy shape of the feed (the same code path, the same expectations);
  6. the word is a literal of execute_retry (scoring_logic.py): the ST-2 words of station_identity (RETRY_REASONS, REASONS) are unchanged, so is station_identity.py.
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

SHAPES = ("current", "legacy")
WORD = "scoring-finished"

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


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class Managed(unittest.TestCase):
    """The managed rig of the D6 tests (strict data plane, jump client) driven to the scoring-finish on the feed of one shape."""

    shape = "legacy"

    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-lc4-")
        cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
        os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc4"])
        import d6_rig
        import hud_target_contract
        import main
        import scoring_logic
        import sia_managed_rig
        import station_identity
        cls.main, cls.D, cls.MR, cls.S, cls.SI, cls.HT = main, d6_rig, sia_managed_rig, scoring_logic, station_identity, hud_target_contract

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
        self.events = []
        self.o.input_event_sink = lambda event, **fields: self.events.append((event, fields))

    # -- the drive (the helpers of the LC-1 ledger, red_lc_legacy_scoring.py) -----------------------------------------------------------------------------
    def start(self, shape=None, end_idx=2, generation=1):
        shape = shape or self.shape
        r, o = self.r, self.o
        r.go_active(generation=generation, **({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
        o.setting_end_idx = end_idx
        r.start_scoring_via_menu()
        return r.last_command()

    def commands(self):
        return [c for c in self.r.jump_commands() if not c.get("other")]

    def land(self, cmd, shape=None, t=36000000, jump=1):
        shape = shape or self.shape
        r = self.r
        r.send(F.line(shape, 1, t, 0.0, 0.0, jump=jump, discontinuity=True, NEXTLOC=1000.0))
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
        """start -> Jump(STA, idx 0) -> A to B (arrival: the first check point after the start)."""
        cmd = self.start()
        t = self.land(cmd)
        return self.leg(t, 100.0, 1000.0, 1000.0, 1, 1, 1)

    def to_finish(self):
        """... -> doors close, B to C (terminal arrival): the scoring-finish."""
        r, MR = self.r, self.MR
        t = self.to_b()
        t += 3000
        r.send(F.line(self.shape, 1, t, 0.0, 999.6, jump=1, NEXTLOC=1000.0, DOOR=0, STIDX=MR.stidx(MR.STALIST, 1, 1, 1)))
        r.tick(2, 0.1)
        t += 2000
        r.send(F.line(self.shape, 1, t, 18.0, 1010.0, jump=1, calcg=0.05, NEXTLOC=2500.0, STIDX=MR.stidx(MR.STALIST, 2, 1, 1)))
        r.tick(2, 0.1)
        t = self.leg(t, 1010.0, 2500.0, 2500.0, 2, 2, 2, prev=(1, 1))
        self.assertTrue(self.o.is_scoring_finished, "PREMISE the scoring finished")
        self.assertGreaterEqual(len(self.o.save_data), 2, "PREMISE the check points of the run are still in the history")
        return t

    def retry_lines(self):
        return [(e, f) for e, f in self.events if e.startswith("retry-")]


class RetryAfterFinish(Managed):
    def test_RF01_a_retry_after_the_finish_is_refused_with_its_reason(self):
        self.to_finish()
        for position in (0, 1, len(self.o.save_data) - 1, 99, -1):
            res = self.main.execute_retry(self.o, position, False)
            self.assertIsInstance(res, self.SI.RetryResult)
            self.assertFalse(res.accepted, "position %r: accepted after the finish (reason=%r)" % (position, res.reason))
            self.assertEqual(res.reason, WORD, "position %r" % position)
            self.assertIsNone(res.request_id)
            self.assertEqual(res.selected_station_index, self.SI.NO_INDEX)

    def test_RF02_the_refusal_changes_and_sends_nothing(self):
        self.to_finish()
        o = self.o
        before, n_cmd, history = scoring_snapshot(o), len(self.commands()), copy.deepcopy(o.save_data)
        for position in (0, 1, 99):
            self.main.execute_retry(o, position, True)
            self.assertEqual(len(self.commands()), n_cmd, "a Jump command was sent")
            self.assertEqual(o.save_data, history, "the history / a check point changed")
            after = scoring_snapshot(o)
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            self.assertEqual(changed, [], "state changed by the refusal: %s" % changed)
        self.assertIsNone(o.retry_pending)
        self.assertTrue(o.is_scoring_finished and o.is_scoring_mode)
        self.assertFalse(o.is_official_jumping)

    def test_RF03_the_scoring_does_not_restart_and_the_hud_keeps_the_result_state(self):
        self.to_finish()
        o = self.o
        self.assertFalse(self.HT.owner_is_scoring(o.is_scoring_mode, o.is_scoring_finished), "PREMISE the scoring does not own the HUD target after the finish")
        score, details, popups = o.score, dict(o.score_details), list(o.popups)
        self.main.execute_retry(o, 0, True)
        self.r.tick(5, 0.1)
        self.assertTrue(o.is_scoring_finished, "the scoring was restarted")
        self.assertFalse(self.HT.owner_is_scoring(o.is_scoring_mode, o.is_scoring_finished), "the HUD went back to the scoring target")
        self.assertEqual((o.score, dict(o.score_details), list(o.popups)), (score, details, popups))
        self.assertEqual(len(self.commands()), 1, "the only Jump command of the run is the scoring start")

    def test_RF04_from_the_menu_the_refusal_is_one_line_and_the_menu_stays(self):
        self.to_finish()
        o = self.o
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        o.__dict__.pop("was_advancing_before_menu", None)
        before, n_cmd, count = scoring_snapshot(o), len(self.commands()), o.total_retry_count
        o.handle_menu_enter(True)
        lines = self.retry_lines()
        self.assertEqual([e for e, _ in lines], ["retry-rejected"], lines)
        self.assertEqual(lines[0][1].get("why"), WORD)
        self.assertEqual((o.menu_state, o.menu_cursor), (3, 0), "the menu moved")
        self.assertNotIn("was_advancing_before_menu", o.__dict__, "the BVE resume flag was touched")
        self.assertEqual((len(self.commands()), o.total_retry_count), (n_cmd, count))
        after = scoring_snapshot(o)
        self.assertEqual(sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), [])
        o.handle_menu_enter(True)                                    # a second operation is a second line, never a repeated one
        self.assertEqual([e for e, _ in self.retry_lines()], ["retry-rejected", "retry-rejected"])

    def test_RF05_the_refusal_keeps_no_state_a_new_session_can_retry(self):
        self.to_finish()
        o, r = self.o, self.r
        self.main.execute_retry(o, 0, True)                           # refused
        r.tap("f1")                                                   # the user gives the finished session up from the menu ...
        self.assertEqual(o.menu_state, 1)
        o.menu_cursor = o.current_menu_items.index("採点を中断する")
        r.tap("enter")
        self.assertEqual(o.menu_state, 12)
        o.menu_cursor = 0
        r.tap("enter")
        self.assertEqual((o.is_scoring_mode, o.is_scoring_finished, o.menu_state), (False, False, 0))
        n_cmd = len(self.commands())
        r.start_scoring_via_menu()                                    # ... and starts a new one
        cmd = r.last_command()
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertTrue(o.is_scoring_mode and not o.is_scoring_finished)
        t = self.land(cmd, jump=2)
        t = self.leg(t, 100.0, 1000.0, 1000.0, 1, 1, 1, jump=2)
        self.assertFalse(o.is_scoring_finished)
        n_cmd = len(self.commands())
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, "the old refusal was carried into the new session: %r" % (res.reason,))
        self.assertEqual(len(self.commands()), n_cmd + 1)

    def test_RF05b_after_a_new_generation_there_is_nothing_to_retry_and_no_stale_refusal(self):
        self.to_finish()
        self.r.publish(True, True, 2)                                 # F5: a new generation discards the session
        self.r.tick(4)
        o = self.o
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(len(o.save_data), 0)
        res = self.main.execute_retry(o, 0, False)
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "no-checkpoint", "a stale refusal outlived the session")
    def test_RF06_a_retry_before_the_finish_is_untouched(self):
        t = self.to_b()
        o = self.o
        self.assertFalse(o.is_scoring_finished)
        n_cmd, n_hist = len(self.commands()), len(o.save_data)
        res = self.main.execute_retry(o, 99, False)
        self.assertFalse(res.accepted)
        self.assertNotEqual(res.reason, WORD)
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual((len(self.commands()), len(o.save_data), o.is_official_jumping), (n_cmd + 1, n_hist, True))
        self.assertIsNotNone(o.retry_pending)

    def test_RF07_pause_and_a_session_off_do_not_change_the_answer(self):
        self.to_finish()
        self.r.publish(True, False)                                   # Pause
        self.r.tick(5, 1.0)
        res = self.main.execute_retry(self.o, 0, False)
        self.assertEqual((res.accepted, res.reason), (False, WORD))
        self.assertEqual(len(self.commands()), 1)


class RetryAfterFinishCurrent(RetryAfterFinish):
    shape = "current"


class StaticContract(unittest.TestCase):
    def test_RF08_the_word_is_local_and_the_st2_words_are_untouched(self):
        import station_identity as SI
        self.assertEqual(SI.RETRY_REASONS, ("no-checkpoint", "old-form", "retry-pending", "jump-unavailable", "time-invalid"))
        self.assertNotIn(WORD, SI.RETRY_REASONS)
        self.assertNotIn(WORD, SI.REASONS)
        self.assertNotIn(WORD, read("station_identity.py"))
        self.assertIn(WORD, read("scoring_logic.py"))

    def test_RF09_the_refusal_is_the_first_statement_of_execute_retry(self):
        tree = ast.parse(read("scoring_logic.py"))
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"][0]
        body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]       # (without the docstring)
        first = body[0]
        self.assertIsInstance(first, ast.If, "the first statement is not the finish check")
        names = {n.value for n in ast.walk(first.test) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertIn("is_scoring_finished", names)
        self.assertEqual(len(first.body), 1)
        ret = first.body[0]
        self.assertIsInstance(ret, ast.Return)
        self.assertIn(WORD, {n.value for n in ast.walk(ret) if isinstance(n, ast.Constant)}, "the refusal does not return the word")
        self.assertFalse(first.orelse)


if __name__ == "__main__":
    unittest.main()
