"""Phase LC-3B (Legacy scoring integration, C-LOOP-2) - the g_history while the BVE clock is frozen, as an executable contract.

THE PROBLEM (C-LOOP-2)
  update_physics_and_scoring appends one (time, decel_g, notch, brk_max) entry to g_history on EVERY step and prunes only by the BVE time (10 s back from the newest entry).
  The Overlay steps on its own 16 ms timer, independent of the BVE clock. While the BVE time is frozen (Pause, the F1 menu, a duplicate datagram of the same millisecond) the steps keep
  coming with the SAME time: nothing is pruned, the list grows without a bound (and is rebuilt on every step), and the 0.5 s mean of the stop-jerk (update_stop_jerk_penalty) is
  dominated by copies of one frozen sample. Legacy shows it most (the host has no Tick while paused, only the Python timer runs).

THE CONTRACT
  1. an entry whose time equals the time of the newest entry REPLACES it (the newest sample of that instant wins; older entries are untouched): one entry per BVE time;
  2. a time that moves keeps one entry per step - a low frame rate (large dt) is not "duplicate"; the retention (10 s, the boundary excluded) and the 0.5 s window are unchanged;
  3. a frozen clock changes nothing else: N frozen steps leave the scoring state exactly as ONE frozen step does; when the clock resumes the next step appends as usual;
  4. the LC-3A contract is kept: every formal boundary (reset_transient_scoring_state) empties the history first, a stale entry is never replaced; the stop-jerk rule itself
     (0.5 s mean, 0.065 / 0.10, -100 / -200, once per stop) is unchanged;
  5. the one Python path serves both hosts: the same samples give the same history on the Current and the Legacy shape.
Only an EQUAL time replaces: a smaller time (the clock going backwards is the reset boundary of the clock, not of this function) still appends.
Needs PyQt6 (skipped otherwise). The Overlay is the real one against the recorders of tests/sia_rig.py / d6_rig.py: no socket, no real clock.
"""
import contextlib
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
PATHS = ("direct", "main-clock", "hud-clock")    # update_physics_and_scoring itself / Overlay._advance_scoring_clock_and_score / managed_hud.hud_update_step
T0_MS = 36000000

# the state that the scoring step owns; compared between "1 frozen step" and "N frozen steps"
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
    """Every plain attribute of the Overlay (numbers, strings, flags, lists of those): the whole scoring state without the Qt / socket / hook objects."""
    return {k: v for k, v in sorted(o.__dict__.items()) if _plain(v)}


def _profile_guard(cls):
    cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-lc3b-")
    cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name


def _profile_release(cls):
    for k, v in cls._saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    cls._profile_dir.cleanup()


class Direct(unittest.TestCase):
    """The real Overlay, one scoring step at a time through any of the three clock paths."""

    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        _profile_guard(cls)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc3b"])
        import main
        import managed_hud
        import scoring_logic
        import sia_rig as R
        cls.main, cls.S, cls.R, cls.H = main, scoring_logic, R, managed_hud

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
        self.path = "direct"
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
        o.bve_time_ms = T0_MS
        R.bind_identity(o)
        if self.path != "direct":
            self.step(dt=0.1, speed=0.0, calc_g=0.0)          # the first update of the clock is a reset boundary: take it before the scene is measured
        return o

    def now(self):
        return self.o.bve_time_ms / 1000.0

    def step(self, dt=0.1, speed=None, calc_g=None, loc=None, jump=None, official=None, brk=None):
        """One scoring step: the BVE clock moves by `dt` seconds (0 = frozen), the latest telemetry values are set, then the step runs through self.path."""
        o = self.o
        o.bve_time_ms += int(round(dt * 1000))
        if speed is not None:
            o.bve_speed = speed
        if calc_g is not None:
            o.bve_calc_g = calc_g
        if loc is not None:
            o.bve_location = loc
        if jump is not None:
            o.bve_jump_count = jump
        if official is not None:
            o.is_official_jumping = official
        if brk is not None:
            o.bve_brk_notch, o.bve_brk_max = brk
        if self.path == "direct":
            dt_used = dt if dt > 0 else 0.0
            self.S.update_physics_and_scoring(o, self.now(), dt_used)
        elif self.path == "main-clock":
            o._advance_scoring_clock_and_score(self.now())
        else:
            self.H.hud_update_step(o)

    def freeze(self, n, **values):
        for _ in range(n):
            self.step(dt=0.0, **values)

    def jerk(self):
        return [p["text"] for p in self.o.popups if p.get("category") == "停車時衝動"]

    def accelerate(self, n=20, g=0.08):
        for i in range(n):
            self.step(speed=5.0 + 0.3 * i, calc_g=g, loc=100.0 + 0.6 * i)

    def history(self):
        return [(h[0], round(h[1], 4)) for h in self.o.g_history]

    @contextlib.contextmanager
    def on(self, path):
        with self.subTest(path=path):
            self.new_rig()
            self.path = path
            yield


# =====================================================================================================================================================
# 1. the frozen clock: Pause / F1 menu / duplicate datagrams (CF-R1 .. CF-R5)
# =====================================================================================================================================================
class A_FrozenClock(Direct):
    def test_CF_R1_pause_does_not_grow_the_history(self):
        """CF-R1: Pause = the same sample again and again at the same time (16 ms steps, dt 0): the history holds one entry per BVE time."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                n0 = len(self.o.g_history)
                self.assertEqual(n0, 6 if self.path != "direct" else 5)
                self.freeze(1000)
                self.assertEqual(len(self.o.g_history), n0, "history grows while the time is frozen: %d (was %d)" % (len(self.o.g_history), n0))

    def test_CF_R2_a_long_freeze_leaves_the_scoring_state_as_one_step_does(self):
        """CF-R2: every plain attribute of the Overlay after 500 frozen steps equals the one after 1 frozen step (score, popups, brake / stop-jerk state, timers, history)."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                self.step(dt=0.0)
                once = scoring_snapshot(self.o)
                self.freeze(499)
                many = scoring_snapshot(self.o)
                diff = sorted(k for k in set(once) | set(many) if once.get(k, "<absent>") != many.get(k, "<absent>"))
                self.assertEqual(diff, [], "state differs between 1 and 500 frozen steps: %r" % ([(k, once.get(k), many.get(k)) for k in diff][:6],))

    def test_CF_R3_the_f1_menu_does_not_grow_the_history(self):
        """CF-R3: the F1 menu open (menu_state 1) does not stop the Python timer: the same frozen clock, the same single entry per time."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                n0 = len(self.o.g_history)
                self.o.menu_state = 1
                self.freeze(400)
                self.o.menu_state = 0
                self.assertEqual(len(self.o.g_history), n0, "history grows with the F1 menu open: %d (was %d)" % (len(self.o.g_history), n0))

    def test_CF_R4_the_newest_sample_of_an_instant_replaces_the_entry_of_that_time_only(self):
        """CF-R4: same-time duplicates with DIFFERENT values (two datagrams of one millisecond): the newest wins, the older entries are untouched, the entry carries the newest brake fields."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.step(dt=0.1, speed=5.0, calc_g=0.01, brk=(0, 8))
                self.step(dt=0.1, speed=5.0, calc_g=0.02, brk=(1, 8))
                before = self.history()
                for g, brk in ((0.03, (2, 8)), (0.04, (3, 7))):
                    self.step(dt=0.0, calc_g=g, brk=brk)
                after = self.history()
                self.assertEqual(len(after), len(before), "history keeps %r" % (after,))
                self.assertEqual(after[:-1], before[:-1], "an older entry was touched")
                self.assertEqual(after[-1], (before[-1][0], -0.04), "the newest value did not win: %r" % (after[-1],))
                self.assertEqual(tuple(self.o.g_history[-1][2:]), (3, 7), "the entry does not carry the newest brake fields")

    def test_CF_R5_a_frozen_value_does_not_dominate_the_stop_value(self):
        """CF-R5: 600 copies of a frozen hard value do not outweigh the distinct samples of the 0.5 s mean (no false -100 / -200 at the soft stop after the freeze)."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(3, g=0.0)
                for _i in range(10):
                    self.step(dt=0.04, speed=2.0, calc_g=-0.01)
                self.freeze(600, speed=2.0, calc_g=-0.20)             # the value of the frozen menu moment, repeated by the 16 ms step
                self.step(dt=0.1, speed=0.0, calc_g=-0.01)
                self.assertLess(abs(self.o.last_stop_g), 0.1, "duplicates dominate the stop value: %r" % (self.o.last_stop_g,))
                self.assertEqual(self.jerk(), [], "false stop-jerk penalty after the freeze: %r" % (self.jerk(),))

    def test_CF_R6_the_freeze_before_a_real_hard_stop_does_not_hide_it(self):
        """CF-R6: a real hard stop (g -0.15 all along, a Pause on the way) is still deducted exactly once: -200."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                for i in range(12):                               # 0.6 s of hard braking: the whole 0.5 s window of the stop is the braking
                    self.step(dt=0.05, speed=max(4.0 - 0.3 * i, 0.5), calc_g=-0.15)
                self.freeze(300, speed=0.5, calc_g=-0.15)
                self.step(dt=0.05, speed=0.0, calc_g=-0.15)
                self.assertEqual(self.jerk(), ["停車時衝動 -200"], "the hard stop after the freeze: %r" % (self.jerk(),))
                self.freeze(300, speed=0.0, calc_g=-0.15)             # the stopped train keeps being re-stepped while the clock is frozen: not judged again
                self.step(dt=0.1, speed=0.0, calc_g=-0.15)
                self.assertEqual(self.jerk(), ["停車時衝動 -200"], "judged again: %r" % (self.jerk(),))

    def test_CF_R7_a_frozen_sample_at_the_stop_instant_is_judged_once(self):
        """CF-R7: the stop sample itself is repeated while the clock is frozen (menu opened at the stop): one deduction."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                for i in range(8):
                    self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.12)
                self.step(speed=0.0, calc_g=-0.12)
                self.freeze(200, speed=0.0, calc_g=-0.12)
                self.assertEqual(self.jerk(), ["停車時衝動 -200"], "%r" % (self.jerk(),))


# =====================================================================================================================================================
# 2. the clock that moves: low frame rate, retention, resume (CF-R8 .. CF-R11)
# =====================================================================================================================================================
class B_MovingClock(Direct):
    def test_CF_R8_a_low_frame_rate_keeps_one_entry_per_step(self):
        """CF-R8: large dt (a slow frame: 0.25 s, 1 s, 2.5 s) is not a duplicate: every step appends and nothing is replaced."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                n0 = len(self.o.g_history)
                gs = (0.01, 0.02, 0.03, 0.04, 0.05)
                for dt, g in zip((0.25, 1.0, 2.5, 0.016, 0.5), gs):
                    self.step(dt=dt, speed=5.0, calc_g=g)
                hist = self.history()
                self.assertEqual(len(hist), n0 + 5 if n0 else 5, "a slow frame was replaced: %r" % (hist,))
                self.assertEqual([h[1] for h in hist[-5:]], [-g for g in gs])
                self.assertEqual(sorted(set(h[0] for h in hist)), [h[0] for h in hist], "times are not strictly increasing: %r" % (hist,))

    def test_CF_R9_the_retention_is_ten_seconds_with_the_boundary_excluded(self):
        """CF-R9: 12 steps one second apart: the entries newer than (newest - 10 s) remain - exactly 10; an entry exactly 10 s back is dropped."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.o.g_history.clear()
                for _i in range(12):
                    self.step(dt=1.0, speed=5.0, calc_g=0.01)
                hist = self.history()
                newest = hist[-1][0]
                self.assertEqual(len(hist), 10, hist)
                self.assertTrue(all(h[0] > newest - 10.0 for h in hist))

    def test_CF_R10_the_clock_resuming_after_a_freeze_appends_as_usual(self):
        """CF-R10: after a long freeze the next step with a later time appends (the history is one entry longer) and the scoring goes on normally."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                self.freeze(800)
                n0 = len(self.o.g_history)
                for i in range(5):
                    self.step(dt=0.1, speed=6.0 + 0.2 * i, calc_g=0.05)
                self.assertEqual(len(self.o.g_history), n0 + 5)
                times = [h[0] for h in self.o.g_history]
                self.assertEqual(times, sorted(set(times)))
                self.assertAlmostEqual(self.o.last_update_time if self.path != "direct" else self.now(), self.now(), places=6)

    def test_CF_R11_a_freeze_between_two_stops_keeps_the_stop_judgement_working(self):
        """CF-R11: stop (soft) -> move -> freeze -> move -> stop (hard): exactly the hard one is deducted, once (-200)."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                for i in range(8):
                    self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.01)
                self.step(speed=0.0, calc_g=-0.01)
                self.assertEqual(self.jerk(), [])
                self.accelerate(5)
                self.freeze(300, speed=4.0, calc_g=0.08)
                for i in range(8):
                    self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.12)
                self.step(speed=0.0, calc_g=-0.12)
                self.assertEqual(self.jerk(), ["停車時衝動 -200"], "%r" % (self.jerk(),))

    def test_CF_R12_only_an_equal_time_replaces(self):
        """CF-R12: a smaller time (without a reset boundary in between) does NOT overwrite the newer entry - it appends as before; the replace is by equality only."""
        self.scene()
        self.step(dt=0.1, speed=5.0, calc_g=0.01)
        self.step(dt=0.1, speed=5.0, calc_g=0.02)
        n0 = len(self.o.g_history)
        newest = self.o.g_history[-1][0]
        self.S.update_physics_and_scoring(self.o, newest - 0.05, 0.0)
        self.assertEqual(len(self.o.g_history), n0 + 1, "an older time overwrote the newer entry")
        self.assertEqual(self.o.g_history[-2][0], newest)

    def test_CF_R13_the_cost_is_bounded(self):
        """CF-R13: 3000 frozen steps leave ONE entry for the frozen time (the list is not rebuilt from thousands of copies)."""
        self.scene()
        self.o.g_history.clear()
        self.step(dt=0.1, speed=5.0, calc_g=0.01)
        self.freeze(3000)
        self.assertEqual(len(self.o.g_history), 1)


# =====================================================================================================================================================
# 3. LC-3A is kept: the formal boundaries and the pending official jump (CF-R14 .. CF-R17)
# =====================================================================================================================================================
class C_Boundaries(Direct):
    def test_CF_R14_a_jump_at_a_frozen_instant_empties_the_history_and_starts_clean(self):
        """CF-R14: the BVE jump counter moves at a frozen time: the history is emptied (LC-3A), the next frozen step appends ONE entry (a stale entry is never replaced)."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(5)
                self.freeze(20)
                self.step(dt=0.0, speed=0.0, calc_g=0.0, jump=1, official=True)
                self.assertEqual(list(self.o.g_history), [], "the history of the old trajectory survived the Jump")
                self.assertEqual((self.o.is_stopping_zone, self.o.last_stop_g, self.o.stop_notch_state), (False, 0.0, "IDLE"))
                self.step(dt=0.0, speed=0.0, calc_g=0.0)
                self.step(dt=0.0, speed=0.0, calc_g=0.0)
                self.assertEqual(len(self.o.g_history), 1)
                self.assertEqual(self.jerk(), [])

    def test_CF_R15_the_clock_going_backwards_resets_before_the_replace(self):
        """CF-R15: the clock goes back to EXACTLY the time of a stale entry: the reset empties the history first, so the stale entry is not 'replaced' - there is one new entry."""
        for path in ("main-clock", "hud-clock"):
            with self.subTest(path=path):
                self.new_rig()
                self.path = path
                self.scene()
                self.accelerate(5)
                stale = self.o.g_history[-3]
                self.o.bve_time_ms = int(round(stale[0] * 1000))
                self.o.bve_speed, self.o.bve_calc_g = 1.0, 0.0
                self.step(dt=0.0)
                hist = self.history()
                self.assertEqual(hist, [(stale[0], -0.0)], "a stale entry survived the reset: %r" % (hist,))

    def test_CF_R16_the_stop_state_of_the_jump_boundary_is_not_reintroduced_by_the_freeze(self):
        """CF-R16: LC-3A: a Jump landing at speed 0.0 while the clock is frozen (menu -> Retry): no stop-jerk, neither at the landing nor in the frozen steps that follow."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(10)
                self.o.menu_state = 1
                self.freeze(100, speed=5.0, calc_g=0.08)
                self.step(dt=0.0, speed=0.0, jump=1, official=True)
                self.freeze(100, speed=0.0, calc_g=0.08)
                self.assertEqual(self.jerk(), [], "false stop-jerk penalty in the Jump window: %r" % (self.jerk(),))

    def test_CF_R17_a_pending_official_jump_with_a_frozen_clock_judges_nothing_and_stays_small(self):
        """CF-R17: is_official_jumping with the clock frozen (waiting for the C# completion): not a stop (LC-3A), one entry for the frozen time."""
        for path_ in PATHS:
            with self.on(path_):
                self.scene()
                self.accelerate(10)
                self.step(dt=0.0, speed=0.0, calc_g=0.08, official=True)
                n0 = len(self.o.g_history)
                self.freeze(300, speed=0.0, calc_g=0.08)
                self.assertEqual(len(self.o.g_history), n0)
                self.assertEqual(self.jerk(), [])


# =====================================================================================================================================================
# 4. the managed pipeline end to end and the two hosts (CF-R18 .. CF-R20)
# =====================================================================================================================================================
class D_ManagedPipeline(unittest.TestCase):
    """The strict data plane of the managed mode (d6_rig): the sender's lines in the shape of Current / Legacy, the Overlay's 16 ms timer as `tick`."""

    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        _profile_guard(cls)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc3b-m"])
        import main
        import d6_rig
        import sia_managed_rig
        cls.main, cls.D, cls.MR = main, d6_rig, sia_managed_rig

    @classmethod
    def tearDownClass(cls):
        _profile_release(cls)

    def drive(self, shape, freeze):
        """5 moving samples, then `freeze(r, shape, t)` at the last sample's time, then 5 more moving samples. Returns the history and its length at each stage.
        The rig is built and closed here (one rig of the module at a time)."""
        r = self.D.D6Rig(self.main)
        try:
            r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
            o = r.o
            t = T0_MS
            for i in range(5):
                t += 100
                r.send(F.line(shape, 1, t, 18.0, 100.0 + 0.5 * i, calcg=0.01, NEXTLOC=1000.0))
                r.tick(1, 0.016)
            n_moving = len(o.g_history)
            freeze(r, shape, t)
            n_frozen = len(o.g_history)
            for i in range(5):
                t += 100
                r.send(F.line(shape, 1, t, 18.0, 103.0 + 0.5 * i, calcg=0.02, NEXTLOC=1000.0))
                r.tick(1, 0.016)
            return {"moving": n_moving, "frozen": n_frozen, "final": len(o.g_history), "history": [(h[0], round(h[1], 4)) for h in o.g_history]}
        finally:
            r.close()

    @staticmethod
    def pause(r, shape, t):
        r.tick(400, 0.016)                                     # no datagram: Legacy's Tick is gone while paused, the Overlay's timer runs on

    @staticmethod
    def f1_menu(r, shape, t):
        r.tap("f1")
        r.tick(400, 0.016)
        r.tap("f1")

    @staticmethod
    def duplicates(r, shape, t):
        for _ in range(50):                                    # the same datagram again (same millisecond)
            r.send(F.line(shape, 1, t, 18.0, 102.0, calcg=0.01, NEXTLOC=1000.0))
            r.tick(2, 0.016)

    def test_CF_R18_pause_and_f1_menu_and_duplicate_datagrams_in_the_managed_pipeline(self):
        """CF-R18: through the managed pipeline (telemetry parse -> HUD timer -> scoring step): the history stays at the size of the moving samples while paused / in the F1 menu / fed duplicates."""
        for shape in SHAPES:
            for name, fn in (("pause", self.pause), ("f1", self.f1_menu), ("duplicates", self.duplicates)):
                with self.subTest(shape=shape, freeze=name):
                    res = self.drive(shape, fn)
                    self.assertEqual(res["frozen"], res["moving"], "history grows while the time is frozen (%s/%s): %r" % (shape, name, {k: v for k, v in res.items() if k != "history"}))
                    self.assertEqual(res["final"], res["frozen"] + 5, "the resumed clock did not append once per sample (%s/%s): %r" % (shape, name, {k: v for k, v in res.items() if k != "history"}))

    def test_CF_R19_current_and_legacy_give_the_same_history(self):
        """CF-R19: the same samples on the Current shape and on the Legacy shape give the same history (one Python path; no host branch)."""
        for name, fn in (("pause", self.pause), ("f1", self.f1_menu)):
            with self.subTest(freeze=name):
                cur, leg = self.drive("current", fn), self.drive("legacy", fn)
                self.assertEqual(cur["history"], leg["history"])
                self.assertEqual((cur["moving"], cur["frozen"], cur["final"]), (leg["moving"], leg["frozen"], leg["final"]))

    def test_CF_R20_the_resumed_history_has_the_moving_samples_only(self):
        """CF-R20: after the freeze the history is exactly the distinct samples of the clock (10 entries for 10 moving samples, strictly increasing times), whatever the freeze was."""
        for shape in SHAPES:
            for name, fn in (("pause", self.pause), ("f1", self.f1_menu)):
                with self.subTest(shape=shape, freeze=name):
                    res = self.drive(shape, fn)
                    times = [h[0] for h in res["history"]]
                    self.assertEqual(times, sorted(set(times)), "duplicate times in the history: %r" % (times,))
                    self.assertTrue(len(times) >= 10, times)


if __name__ == "__main__":
    unittest.main()
