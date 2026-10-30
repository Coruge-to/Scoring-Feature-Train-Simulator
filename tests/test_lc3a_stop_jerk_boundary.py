"""Phase LC-3A (Legacy scoring integration, Slice A) - the stop-jerk state at the formal boundaries of the scoring, as an executable contract.

THE PROBLEM (Slice A)
  update_stop_jerk_penalty judges a stop (speed 0.0) from two pieces of state that live across ticks: `is_stopping_zone` ("the train was moving") and the mean of the
  g_history of the last 0.5 s. `reset_transient_scoring_state` (the one formal discard of the frame-to-frame state: begin_official_jump / BVE jump count / time going backwards /
  aborted jump) cleared g_history but NOT the judged state of the stop-jerk. So a Jump that lands with speed 0.0 was connected to the old trajectory: the "was moving" flag was
  still set and (Legacy: no CALCG on the first sample after a discontinuity, the previous value is held) the old acceleration became the "stop value" -> a false -100 / -200.
  A pending official jump kept the old telemetry flowing as a moving train, and a speed 0.0 sample without a counter movement yet was judged as a stop too.

THE CONTRACT
  1. every formal boundary leaves the stop-jerk state at its start values (is_stopping_zone False, last_stop_g 0.0, stop_notch_state "IDLE", g_history empty);
  2. the stop-jerk is not judged while an official jump is pending (is_official_jumping): the vehicle state in that window is not a stop;
  3. the rule itself is unchanged: window mean of the last 0.5 s, |g| >= 0.065 -> -100, |g| >= 0.10 -> -200, once per stop, judged again after the next movement.
  Current (CALCG:0.00000 on the Jump line) and Legacy (the previous CALCG held) must give the same result.

Boundaries: A scoring start, B start-station Jump, C normal Jump (BVE jump count), D Retry Jump, E F5 / generation, F scenario change, G scoring finished, H session off,
I normal stop and re-movement (must NOT reset).  G and H change nothing by themselves: add_score_popup refuses every deduction when scoring is off or finished, and the next start is a
boundary (A/B/D) - the contract rows below pin exactly that (no reason word is added in this phase).
Needs PyQt6 (skipped otherwise). The Overlay is the real one against the recorders of tests/sia_rig.py / d6_rig.py: no socket, no real clock.
"""
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
START = (False, 0.0, "IDLE")         # (is_stopping_zone, last_stop_g, stop_notch_state) at the start


def _profile_guard(cls):
    cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-lc3a-")
    cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name


def _profile_release(cls):
    for k, v in cls._saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    cls._profile_dir.cleanup()


def jerk_state(o):
    return (o.is_stopping_zone, o.last_stop_g, o.stop_notch_state)


class Direct(unittest.TestCase):
    """The direct scene of tests/red_lc_legacy_scoring.py (the real Overlay, update_physics_and_scoring called step by step)."""

    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        _profile_guard(cls)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc3a"])
        import main
        import scoring_logic
        import sia_rig as R
        import managed_input
        cls.main, cls.S, cls.R, cls.MI = main, scoring_logic, R, managed_input

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

    def step(self, dt=0.1, speed=None, calc_g=None, loc=None, jump=None, official=None):
        o = self.o
        self.t += dt
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
        self.S.update_physics_and_scoring(o, self.t, dt)

    def jerk(self):
        return [p["text"] for p in self.o.popups if p.get("category") == "停車時衝動"]

    def accelerate(self, n=20, g=0.08):
        for i in range(n):
            self.step(speed=5.0 + 0.3 * i, calc_g=g, loc=100.0 + 0.6 * i)

    def brake_to_stop(self, g, n=8, stop=True):
        """n braking ticks (calc_g = g: the sender writes a deceleration as a negative CALCG), then the stop tick when `stop`."""
        for i in range(n):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=g)
        if stop:
            self.step(speed=0.0, calc_g=g)

    def land(self, shape, speed=0.0, jump=1, official=True):
        """The first sample after a Jump: Current writes CALCG:0.00000 on the Jump line, Legacy writes no CALCG (the previous value is held)."""
        if shape == "current":
            self.step(speed=speed, calc_g=0.0, jump=jump, official=official)
        else:
            self.step(speed=speed, jump=jump, official=official)


# =====================================================================================================================================================
# the Jump boundary (B / C): SA-R1 .. SA-R5
# =====================================================================================================================================================
class A_JumpBoundary(Direct):
    def test_SA_R1_the_history_before_the_jump_does_not_cross_it(self):
        """SA-R1 (both shapes): a hard braking window before the Jump, landing at a small speed, a stop within 0.5 s: the old window is not part of the stop value."""
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.new_rig()
                self.scene()
                self.accelerate(5)
                for _ in range(5):
                    self.step(speed=3.0, calc_g=-0.15)                 # a hard braking window right before the Jump
                self.land(shape, speed=1.0)
                t_land = self.t
                self.assertEqual(list(self.o.g_history), [], "the history of the old trajectory survived the Jump")
                self.step(speed=0.0, calc_g=0.0)                       # the new trajectory stops softly
                self.assertEqual(self.jerk(), [], "the old braking window is judged as the stop of the new trajectory (%s)" % shape)
                self.assertTrue(all(h[0] > t_land for h in self.o.g_history), "an entry older than the Jump is in the history")

    def test_SA_R4_current_jump_landing_at_speed_zero_is_not_a_stop(self):
        """SA-R4 (Current Jump, also SA-R2): CALCG:0.00000 on the Jump line."""
        self.scene()
        self.accelerate()
        self.assertTrue(self.o.is_stopping_zone)
        self.land("current")
        self.assertEqual(self.jerk(), [], "false stop-jerk penalty")
        self.assertEqual(jerk_state(self.o), START, "stop-jerk state survives the boundary")

    def test_SA_R5_legacy_jump_landing_at_speed_zero_is_not_a_stop(self):
        """SA-R5 (Legacy Jump, also SA-R2): no CALCG on the first sample after the discontinuity, the acceleration of the old trajectory is held."""
        self.scene()
        self.accelerate()
        self.assertTrue(self.o.is_stopping_zone)
        self.land("legacy")
        self.assertEqual(self.jerk(), [], "false stop-jerk penalty")
        self.assertEqual(jerk_state(self.o), START, "stop-jerk state survives the boundary")

    def test_SA_R2_the_second_sample_of_the_landing_is_not_a_stop_either(self):
        """The sender keeps the speed 0.0 for several samples (the train stands at the landing): neither the completion of the jump nor the next samples are judged."""
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.new_rig()
                self.scene()
                self.accelerate()
                self.land(shape)
                self.step(speed=0.0, calc_g=0.0, official=False)       # the C# completion arrived
                for _ in range(10):
                    self.step(speed=0.0, calc_g=0.0)
                self.assertEqual(self.jerk(), [], "a stop-jerk penalty after the landing (%s)" % shape)
                self.assertEqual(jerk_state(self.o), START)

    def test_SA_R3_the_next_stop_is_judged_by_the_new_samples_only(self):
        """SA-R3 (both shapes): after the landing the train departs again; a soft stop is free, a hard stop is -200 once; the old trajectory plays no part."""
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.new_rig()
                self.scene()
                self.brake_to_stop(-0.20, stop=False)                  # the old trajectory was braking hard
                self.land(shape)
                self.step(speed=0.0, calc_g=0.0, official=False)
                base = len(self.jerk())
                self.accelerate(5, g=0.03)
                self.brake_to_stop(-0.03)                              # a soft stop
                self.assertEqual(self.jerk()[base:], [], "a soft stop is penalised (%s)" % shape)
                self.accelerate(5, g=0.03)
                self.brake_to_stop(-0.12)                              # a hard stop
                self.assertEqual(self.jerk()[base:], ["停車時衝動 -200"], "the hard stop is not penalised exactly once (%s)" % shape)

    def test_SA_R4_R5_current_and_legacy_give_the_same_result(self):
        """SA-R4 / SA-R5: the state, the popups and the score after the same Jump are the same on the two shapes."""
        result = {}
        for shape in SHAPES:
            self.new_rig()
            self.scene()
            self.accelerate()
            self.land(shape)
            self.step(speed=0.0, calc_g=0.0, official=False)
            result[shape] = (jerk_state(self.o), self.jerk(), self.o.score, len(self.o.g_history))
        self.assertEqual(result["current"], result["legacy"], "Current / Legacy differ after a Jump: %r" % (result,))

    def test_SA_R2b_nothing_is_judged_while_the_official_jump_is_pending(self):
        """SA-R2b: the pending window (begin_official_jump .. the BVE jump counter moves): the old telemetry keeps flowing; a speed 0.0 sample there is not a stop."""
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.new_rig()
                self.scene()
                self.accelerate()
                self.step(speed=0.0, official=True)
                self.assertEqual(self.jerk(), [], "evaluated while the jump is pending: %r" % (self.jerk(),))

    def test_SA_R2c_a_moving_train_in_the_pending_window_does_not_arm_the_judgement(self):
        """SA-R2c: begin_official_jump clears the state, the moving samples of the pending window must not set it again: a zero sample right after the landing is free."""
        self.scene()
        self.accelerate()
        self.S.begin_official_jump(self.o, 1000.0, 36218000)
        for _ in range(3):
            self.step(speed=12.0, calc_g=0.08)                         # the old world is still reported
        self.land("legacy")
        self.assertEqual(self.jerk(), [], "false stop-jerk penalty")
        self.assertEqual(jerk_state(self.o), START)


# =====================================================================================================================================================
# the other formal boundaries: SA-R6 .. SA-R11
# =====================================================================================================================================================
class B_OtherBoundaries(Direct):
    def test_SA_R8_the_start_of_the_scoring_takes_no_sample_from_outside_the_scoring(self):
        """SA-R8 (boundary A/B): the samples seen before the start (the scoring is off) are not part of the scoring: begin_official_jump leaves the start state."""
        self.scene()
        self.o.is_scoring_mode = False
        self.accelerate()
        self.step(speed=2.0, calc_g=-0.12)
        self.assertTrue(self.o.is_stopping_zone)
        self.assertTrue(len(self.o.g_history) > 0)
        self.o.is_scoring_mode = True
        self.S.begin_official_jump(self.o, 1000.0, 36218000)
        self.assertEqual(jerk_state(self.o), START, "stop-jerk state survives the start")
        self.assertEqual(list(self.o.g_history), [])

    def test_SA_R6_retry_jump_starts_from_the_start_state(self):
        """SA-R6 (boundary D): execute_retry ends in begin_official_jump; the score of the check point is restored by the request, the stop-jerk state is the start state."""
        self.scene()
        self.accelerate()
        self.o.last_stop_g = -0.08
        self.o.stop_notch_state = "EMERGENCY"
        self.S.begin_official_jump(self.o, 1000.0, 36218000)           # the call execute_retry makes (the order is pinned by tests/test_jf1_retry_and_save_data_current.py R19)
        self.assertEqual(jerk_state(self.o), START)

    def test_SA_RX_the_time_going_backwards_and_the_aborted_jump_are_boundaries(self):
        """SA-RX: the other two callers of reset_transient_scoring_state keep the same meaning: after them there is no old stop-jerk state."""
        for label in ("time-backwards", "aborted-jump"):
            with self.subTest(boundary=label):
                self.new_rig()
                self.scene()
                self.accelerate()
                self.o.last_stop_g = -0.08
                self.o.stop_notch_state = "EMERGENCY"
                self.S.reset_transient_scoring_state(self.o)
                self.assertEqual(jerk_state(self.o), START, "stop-jerk state survives %s" % label)
                self.assertEqual(list(self.o.g_history), [])

    def test_SA_R7_a_new_generation_drops_the_stop_jerk_state(self):
        """SA-R7 (boundary E, F): F5 / a new scenario instance already discards everything (generation_defaults); this must keep holding."""
        o = self.scene()
        self.accelerate()
        o.last_stop_g = -0.08
        o.stop_notch_state = "EMERGENCY"
        self.MI.discard_generation_state(o)
        self.assertEqual(jerk_state(o), START)
        self.assertEqual(list(o.g_history), [])

    def test_SA_R9_the_finished_scoring_judges_nothing_and_the_next_start_is_clean(self):
        """SA-R9 (boundary G): after the finish add_score_popup refuses every deduction, so a stale state is never a deduction; the next start is a boundary and leaves the start state."""
        o = self.scene()
        o.is_scoring_finished = True
        score = o.score
        self.accelerate()
        self.brake_to_stop(-0.20)
        self.assertEqual((self.jerk(), o.score), ([], score), "a deduction after the finish")
        o.is_scoring_finished = False
        self.S.begin_official_jump(o, 1000.0, 36218000)
        self.assertEqual(jerk_state(o), START)

    def test_SA_R10_the_session_off_judges_nothing_and_the_next_start_is_clean(self):
        """SA-R10 (boundary H): discard_scoring_session turns the scoring off; a stale state is never a deduction; the next start leaves the start state."""
        o = self.scene()
        self.accelerate()
        self.MI.discard_scoring_session(o)
        self.assertFalse(o.is_scoring_mode)
        self.brake_to_stop(-0.20)
        self.assertEqual(self.jerk(), [], "a deduction after the session ended")
        o.is_scoring_mode = True
        self.S.begin_official_jump(o, 1000.0, 36218000)
        self.assertEqual(jerk_state(o), START)

    def test_SA_R10_the_first_update_after_the_session_ended_is_a_boundary(self):
        """SA-R10: discard_scoring_session sets last_update_time to 0.0; the first update of both clock paths (Overlay._advance_scoring_clock_and_score and managed_hud.hud_update_step)
        runs the formal reset BEFORE the sample is judged: a train that stands there, with the acceleration of the old trajectory still in the line, is not judged as a stop."""
        import managed_hud
        for label in ("normal-mode clock", "managed hud clock"):
            with self.subTest(clock=label):
                o = self.new_rig()
                self.scene()
                self.accelerate()
                self.assertTrue(o.is_stopping_zone)
                self.MI.discard_scoring_session(o)
                self.assertEqual(o.last_update_time, 0.0)
                o.bve_speed = 0.0
                o.bve_calc_g = 0.08
                o.bve_time_ms += 100
                if label == "normal-mode clock":
                    o._advance_scoring_clock_and_score(o.bve_time_ms / 1000.0)
                else:
                    managed_hud.hud_update_step(o)
                self.assertEqual(jerk_state(o), START, "the first update after the session ended judged the old trajectory (%s)" % label)

    def test_SA_R11_the_state_of_the_previous_station_does_not_reach_the_next_one(self):
        """SA-R11: a hard stop at one station (-200 once) does not make the soft stop at the next one a deduction."""
        self.scene()
        self.accelerate(5)
        self.brake_to_stop(-0.12)
        self.assertEqual(self.jerk(), ["停車時衝動 -200"])
        for _ in range(20):
            self.step(speed=0.0, calc_g=0.0)                           # the doors are open, the train stands
        self.accelerate(5, g=0.03)
        self.brake_to_stop(-0.02)
        self.assertEqual(self.jerk(), ["停車時衝動 -200"], "the first station's value reached the next stop")


# =====================================================================================================================================================
# the rule itself and the normal running: SA-R12 .. SA-R15 (GUARD)
# =====================================================================================================================================================
class C_RuleGuard(Direct):
    def test_SA_R12_a_stop_and_a_re_movement_at_the_same_station_are_judged_each_time(self):
        """SA-R12: stop -> move -> stop: no reset by the normal movement; every stop is judged (state: boundary I)."""
        self.scene()
        for _ in range(3):
            self.accelerate(5)
            self.brake_to_stop(-0.12)
        self.assertEqual(self.jerk(), ["停車時衝動 -200"] * 3)

    def test_SA_R13_R14_the_thresholds_and_the_amounts_are_unchanged(self):
        """SA-R13 / SA-R14 (and the mutation SA-M15): |g| < 0.065 free, [0.065, 0.10) -> -100, >= 0.10 -> -200 (the mean of the last 0.5 s)."""
        for g, expect, points in ((0.0649, [], 0), (0.0651, ["停車時衝動 -100"], -100), (0.0999, ["停車時衝動 -100"], -100), (0.1001, ["停車時衝動 -200"], -200),
                                  (-0.0651, ["停車時衝動 -100"], -100), (-0.1001, ["停車時衝動 -200"], -200)):
            with self.subTest(g=g):
                self.new_rig()
                o = self.scene()
                self.accelerate(5)
                before = o.score
                for _ in range(8):
                    self.step(speed=2.0, calc_g=g)
                self.step(speed=0.0, calc_g=g)
                self.assertEqual((self.jerk(), o.score - before), (expect, points))

    def test_SA_R15_one_stop_is_one_deduction(self):
        """SA-R15 (and the mutation SA-M13): the standing train is not judged again tick after tick; the score changes once."""
        o = self.scene()
        self.accelerate(5)
        before = o.score
        self.brake_to_stop(-0.12)
        after = o.score
        for _ in range(50):
            self.step(speed=0.0, calc_g=-0.12)
        self.assertEqual((self.jerk(), o.score - before, o.score), (["停車時衝動 -200"], -200, after))

    def test_SA_RX_the_stop_jerk_switch_off_is_respected(self):
        self.scene()
        self.o.pen_jerk = False
        self.accelerate(5)
        self.brake_to_stop(-0.12)
        self.assertEqual(self.jerk(), [])


# =====================================================================================================================================================
# the real flow: start scoring -> Jump -> Retry -> F5 / session off, on both shapes (managed Overlay, Envelope v1)
# =====================================================================================================================================================
class D_ManagedFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        _profile_guard(cls)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc3a-managed"])
        import main
        import d6_rig
        import sia_managed_rig
        cls.main, cls.D, cls.MR = main, d6_rig, sia_managed_rig

    @classmethod
    def tearDownClass(cls):
        _profile_release(cls)

    def fresh(self, shape):
        if getattr(self, "r", None) is not None:
            self.r.close()
        self.r = self.D.D6Rig(self.main)
        self.o = self.r.o
        self.addCleanup(self.r.close)
        self.r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
        self.o.setting_end_idx = 2
        return self.r

    def run_up(self, shape, t, n=6, speed=54.0, g=0.08, jump=0):
        """n lines of a moving, accelerating train (the scoring is off or the jump is pending: the old world is still reported)."""
        r = self.r
        for i in range(n):
            t += 1000
            r.send(F.line(shape, 1, t, speed + i, 100.0 + 15.0 * i, jump=jump, calcg=g, NEXTLOC=1000.0))
            r.tick(1, 0.1)
        return t

    def land(self, cmd, shape, t, jump=1):
        r = self.r
        r.send(F.line(shape, 1, t, 0.0, 0.0, jump=jump, discontinuity=True, NEXTLOC=1000.0))
        r.tick(2)
        r.complete(cmd["request_id"], location=0.0, time_ms=t, count=jump)
        r.tick(2)

    def jerk(self):
        return [p["text"] for p in self.o.popups if p.get("category") == "停車時衝動"]

    def test_SA_R8_managed_start_with_a_moving_train_does_not_punish_the_landing(self):
        """SA-R8 (+R2/R4/R5) boundary A + B on both shapes: a train that moves before the start, the pending window, the landing at speed 0.0 and the completion: no stop-jerk deduction, start state."""
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.fresh(shape)
                t = self.run_up(shape, 36000000 - 6000)
                self.assertTrue(self.o.is_stopping_zone)
                self.r.start_scoring_via_menu()
                cmd = self.r.last_command()
                self.assertTrue(self.o.is_official_jumping)
                self.assertEqual(jerk_state(self.o)[1:], START[1:], "last_stop_g / stop_notch_state survive the start")
                t = self.run_up(shape, t, n=3, jump=0)                  # the pending window: the old telemetry still flows
                self.land(cmd, shape, 36000000)
                self.assertEqual(self.jerk(), [], "a false stop-jerk deduction after the landing (%s)" % shape)
                self.assertFalse(self.o.is_official_jumping)
                self.assertEqual(jerk_state(self.o), START)
                self.assertEqual(self.o.score, 0)

    def test_SA_R6_R16_managed_retry_jump_does_not_punish_the_landing_and_restores_the_score(self):
        """SA-R6 / SA-R16 boundary D on both shapes: the Retry request rolls the score back to the check point, the pending window and the landing make no deduction."""
        for shape in SHAPES:
            with self.subTest(shape=shape):
                self.fresh(shape)
                self.r.start_scoring_via_menu()
                cmd = self.r.last_command()
                self.land(cmd, shape, 36000000)
                o = self.o
                o.score = 300                                             # a score earned before the check point of the Retry
                o.save_data[0]["score"] = 300
                t = self.run_up(shape, 36000000, jump=1)
                self.assertTrue(o.is_stopping_zone)
                n_cmd = len([c for c in self.r.jump_commands() if not c.get("other")])
                o.score = 150                                             # points lost after that check point
                res = self.main.execute_retry(o, 0, False)
                self.assertTrue(res.accepted, res.reason)
                self.assertEqual(o.score, 300, "the Retry request does not restore the score of the check point")
                self.assertEqual(jerk_state(o), START, "stop-jerk state survives the Retry request")
                sent = [c for c in self.r.jump_commands() if not c.get("other")][n_cmd:]
                self.assertEqual(len(sent), 1)
                t = self.run_up(shape, t, n=3, jump=1)
                t += 5000
                self.r.send(F.line(shape, 1, t, 0.0, 0.0, jump=2, discontinuity=True, NEXTLOC=1000.0))
                self.r.tick(2)
                self.r.complete(sent[0]["request_id"], location=0.0, time_ms=t, count=2, kind="STA", index=0)
                self.r.tick(3)
                self.assertEqual(self.jerk(), [], "a false stop-jerk deduction after the Retry landing (%s)" % shape)
                self.assertEqual((o.score, o.is_official_jumping), (300, False))
                self.assertEqual(jerk_state(o), START)

    def test_SA_R7_R10_managed_f5_and_the_session_off_leave_no_old_judgement(self):
        """SA-R7 / SA-R10 boundary E (F5 = a new generation) and H (session off) in the real flow: moving train, then the boundary, then the train stands: no deduction, start state."""
        for label, publish in (("f5", dict(session=True, driving=True, generation=2)), ("session-off", dict(session=False, driving=False))):
            for shape in SHAPES:
                with self.subTest(boundary=label, shape=shape):
                    self.fresh(shape)
                    self.r.start_scoring_via_menu()
                    cmd = self.r.last_command()
                    self.land(cmd, shape, 36000000)
                    t = self.run_up(shape, 36000000, jump=1)
                    self.assertTrue(self.o.is_stopping_zone)
                    self.r.publish(**publish)
                    self.r.tick(4)
                    self.assertFalse(self.o.is_scoring_mode)
                    if label == "session-off":
                        self.r.publish(session=True, driving=True)
                        self.r.tick(2)
                    self.r.send(F.line(shape, 1, t + 1000, 0.0, 400.0, jump=1, calcg=0.08, NEXTLOC=1000.0))     # the train stands; the held acceleration of the old trajectory is still in the line
                    self.r.tick(3, 0.1)
                    self.assertEqual(self.jerk(), [], "a deduction after %s (%s)" % (label, shape))
                    self.assertEqual(self.o.score, 0)
                    if label == "f5":
                        self.assertEqual(jerk_state(self.o), START, "stop-jerk state survives %s" % label)
                    # (session off: the latest telemetry of a moving train arms the judgement again by itself - the state is legitimately not the start state; the first update is pinned in B_OtherBoundaries)


if __name__ == "__main__":
    unittest.main()
