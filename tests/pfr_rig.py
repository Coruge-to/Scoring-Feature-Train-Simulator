"""Post-Finish Retry Recovery (PFR) - the shared managed rig of the PFR tests: the Overlay is the real one against the recorders of tests/d6_rig.py (no socket, no real clock),
driven on the Current or the Legacy shape of the feed to a mid-run check point (to_b) or to the scoring finish (to_finish, terminal arrival).
Needs PyQt6 (the tests that use it skip otherwise).
"""
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


class PfrManaged(unittest.TestCase):
    """The managed rig of the D6 tests (strict data plane, jump client) on the feed of one shape. capture_sink=True replaces the input controller's sink by a recorder
    (self.events); False keeps the real sink (the managed log of the rig, r.log, and the line budgets of the controller are in effect)."""

    shape = "legacy"
    capture_sink = False
    __test__ = True

    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-pfr-")
        cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
        os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pfr"])
        import d6_rig
        import hud_target_contract
        import main
        import managed_input
        import scoring_logic
        import sia_managed_rig
        import station_identity
        cls.main, cls.D, cls.MR, cls.S, cls.SI, cls.HT, cls.MI = main, d6_rig, sia_managed_rig, scoring_logic, station_identity, hud_target_contract, managed_input

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
        if self.capture_sink:
            self.o.input_event_sink = lambda event, **fields: self.events.append((event, fields))

    # -- the drive (the helpers of the LC-1 ledger, red_lc_legacy_scoring.py; the same as tests/test_lc4_retry_after_finish.py) -------------------------------
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

    def lines_of(self, name):
        """The managed log lines of one event name (the real sink of the controller)."""
        return [l for l in self.r.log.lines if (" event=%s " % name) in l or l.endswith(" event=%s" % name)]
