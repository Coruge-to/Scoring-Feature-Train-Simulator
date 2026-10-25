"""Time Fix B3 - ONE zero-speed contract for "stopped" and "moving", and a clean Retry / Jump boundary for the operational stop state.

THE CONTRACT (owner decision of Time Fix B3). BVE supplies exactly 0.0 km/h while the train stands, so no noise band is needed:
  speed == 0.0 (+0.0 and -0.0)  -> stopped
  speed != 0.0 (either sign)    -> moving / departing; 0.0001, -0.0001, 0.1 and -0.1 are all moving; there is no intermediate state between 0.0 and 0.1 km/h.
The author-defined stop range only answers "was the operational stop made once"; after it was made the position is not judged again.

WHAT THIS FILE PINS (the Python half; the sender half is TsScoringPlugin/Handshake/Tests/Test-TimeFixB3.ps1):
  A  the scoring side already treats exactly 0.0 as the stop of an operational stop (guards: they pass before and after B3)
  B  the completion of a latched operational stop by its record (guards; the sign and size of the speed on the switch Tick do not matter)
  C  F7 / F8 / P and the fast-forward release: the "is the train moving" test of the key suppression is speed != 0.0 (RED before B3 for the 0.1 band and for the negative sign);
     F7 and P do not look at the speed at all (guards)
  D  the speed limit guidance blinks while the train is moving (speed != 0.0), not only above +0.1 km/h
  E  the Retry / Jump boundary: while an official jump is outstanding the telemetry describes the world the jump is about to replace, so the operational stop state (latch, margins,
     the scored-stop mark) is neither formed nor consumed; it is formed again from the first stop AFTER the landing; nothing stale survives a retry, a scoring start, a scoring
     finish, a session end or a scenario generation
  F  source pins and the inventory of the remaining speed thresholds (classification B: other concepts, kept on purpose)

Cases tagged [RED-B3] fail on the code of Time Fix B2 and pass after B3; every other case is a guard that passes before and after. Without PyQt6 (python -I) the behaviour tests are
SKIPPED; the source pins always run.
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

import jump_wire  # noqa: E402
import sia_rig as R  # noqa: E402

NEG_ZERO = -0.0
MIN_POS = 5e-324                 # the smallest positive non-zero speed a double can carry
MIN_NEG = -5e-324
STOPPED = (0.0, NEG_ZERO)
MOVING = (MIN_POS, MIN_NEG, 0.0001, -0.0001, 0.05, -0.05, 0.09, -0.09, 0.1, -0.1, 0.1001, -0.1001, 5.0, -5.0, 30.0)

T0 = 36000000
DEP = T0 + 60000            # the scheduled departure of the operational stop B (a whole second)
B_LOC = 1000.0
C_LOC = 1100.0              # the next (customer) station is NEAR the operational stop
ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-timefix-b3-")
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
        raise AssertionError("the Time Fix B3 module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def stations_abcd():
    """A idx0 @0, B idx1 @1000 (the operational stop), C idx2 @1100 (a customer station right behind it), D idx3 @3000 (terminal)."""
    return [sta("A", 0.0), sta("B", B_LOC, is_timing=True, raw_dep=DEP), sta("C", C_LOC, is_timing=True), sta("D", 3000.0, terminal=True)]


def cp(loc, t, name="X", details=None):
    return {"loc": loc, "time_ms": t, "score": 0, "target_loc": loc, "station_name": name, "stop_error": 0.0, "score_details": dict(ZERO if details is None else details)}


def with_identity(checkpoint, index, location, count=4, role="arrived_station"):
    checkpoint.update(station_index=index, scope=(R.SCOPE_SID, R.SCOPE_LIST_ID, count), station_location=location, role=role)
    return checkpoint


def read(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read().decode("utf-8-sig")


def f8_posts(api):
    return [p for p in api.posted if p[2] == R.KEY_F8]


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["timefix-b3"])
        import main
        import managed_input
        import scoring_logic
        cls.main, cls.S, cls.MI = main, scoring_logic, managed_input

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.kb, self.api, self.clock = self.rig.kb, self.rig.api, self.rig.clock
        self.t = 100.0

    def fresh(self):
        """A new Overlay for the next subTest (the previous one is closed)."""
        self.rig.close()
        self.setUp()

    def tick(self, n=1):
        for _ in range(n):
            self.t += 0.016
            self.S.update_physics_and_scoring(self.o, self.t, 0.016)

    def scene(self, d=1.0, t_ms=DEP - 30000, margins=(5.0, 5.0), end_idx=3, doordir=0, is_pass=0, speed=0.0):
        """The vehicle `d` m SHORT of the target B, doors closed, after a departure, scoring on, `t_ms` on the BVE clock. NEXTLOC == prev_next_loc."""
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = stations_abcd()
        o.setting_end_idx = end_idx
        o.save_data = [with_identity(cp(0.0, T0, "A"), 0, 0.0, role="scoring_start")]
        o.bve_next_loc = o.prev_next_loc = B_LOC
        o.bve_location = B_LOC - d
        o.bve_speed = speed
        o.bve_is_pass = is_pass
        o.bve_doordir = doordir
        o.bve_door = o.prev_door = 0
        o.bve_margin_f, o.bve_margin_b = margins
        o.has_departed = True
        o.is_first_station = False
        o.is_first_udp = False
        o.bve_time_ms = t_ms
        o.bve_next_time = DEP
        o.bve_current_station_name = "B"
        o.jump_lock = False
        o.is_official_jumping = False
        o.prev_is_pass = is_pass
        o.prev_is_timing = 1
        o.prev_doordir = doordir
        o.is_official_retry = False
        if not getattr(o, "bve_list_id", ""):
            R.bind_identity(o)
        return o

    def arrive(self, d=1.0, t_ms=DEP - 30000, margins=(5.0, 5.0)):
        """The operational stop B is arrived at: one Tick at speed 0.0 inside the range."""
        o = self.scene(d=d, t_ms=t_ms, margins=margins)
        self.tick()
        return o

    def switch(self, t_ms, speed=0.0, location=None, next_margins=(5.0, 5.0)):
        """The Tick on which the sender switches the target to C: NEXTLOC / MARGIN* / DOORDIR of C, the BVE clock and the vehicle as given."""
        o = self.o
        o.bve_time_ms = t_ms
        o.bve_speed = speed
        if location is not None:
            o.bve_location = location
        o.bve_next_loc = C_LOC
        o.bve_margin_f, o.bve_margin_b = next_margins
        o.bve_doordir = 1
        o.bve_next_time = DEP + 120000
        self.tick()
        return o

    def latch(self):
        return getattr(self.o, "operational_stop_latch", "ABSENT")

    def time_points(self):
        return self.o.score_details["time"]


# =====================================================================================================================================================================================
class A_TheStopIsExactlyZero(Base):
    """Z-T01 .. Z-T08 on the scoring side: the operational stop is made at speed == 0.0 (+0.0 and -0.0) inside the author-defined range and at no other speed."""

    def test_Z_T01_Z_T02_Z_T08_speed_0_and_minus_0_inside_the_range_make_the_operational_stop(self):
        """[guard] +0.0 and -0.0 are the same stop: the latch is formed, the stop is marked, the range of the arrived station is kept."""
        for speed in STOPPED:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                o = self.scene(d=1.0, speed=speed)
                self.tick()
                self.assertTrue(o.has_scored_stop_this_station)
                self.assertEqual(self.latch(), (1, DEP - 30000, DEP))
                self.assertEqual(o.operational_stop_margins, (5.0, 5.0))

    def test_Z_T03_to_Z_T06_no_non_zero_speed_makes_the_operational_stop(self):
        """[guard] +0.0001, -0.0001, +0.1, -0.1, the smallest positive / negative double and the rest of MOVING stand for no stop: nothing is latched, marked or scored."""
        for speed in MOVING:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                o = self.scene(d=1.0, speed=speed)
                self.tick(3)
                self.assertFalse(o.has_scored_stop_this_station)
                self.assertIn(self.latch(), (None, "ABSENT"))
                self.assertIsNone(getattr(o, "operational_stop_margins", None))
                self.assertEqual(self.time_points(), 0)

    def test_Z_T07_moving_before_the_stop_was_made_starts_nothing_and_keeps_the_target(self):
        """[guard] the vehicle passes through the range at a non-zero speed without ever standing: no latch, no departure processing, the target (NEXTLOC) stays."""
        for speed in (MIN_POS, 0.0001, -0.0001, 0.1, -0.1, 30.0):
            with self.subTest(speed=repr(speed)):
                self.fresh()
                o = self.scene(d=20.0, speed=speed)
                for loc in (985.0, 995.0, 1005.0, 1015.0, 1030.0):
                    o.bve_location = loc
                    o.bve_time_ms += 500
                    self.tick()
                self.assertFalse(o.has_scored_stop_this_station)
                self.assertIn(self.latch(), (None, "ABSENT"))
                self.assertEqual(o.bve_next_loc, B_LOC)
                self.assertEqual(self.time_points(), 0)

    def test_Z_T08_a_stop_outside_the_author_defined_range_is_no_operational_stop(self):
        """[guard] speed 0.0 but 7 m short of B (range +-5): out of range -> no arrival, no latch."""
        o = self.scene(d=7.0, speed=0.0)
        self.tick(3)
        self.assertTrue(o.is_stopped_out_of_range)
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertIn(self.latch(), (None, "ABSENT"))


# =====================================================================================================================================================================================
class B_TheCompletionDoesNotLookAtTheSpeed(Base):
    """Z-T09 .. Z-T15: on the Tick on which the sender switches the target the stop is completed by its RECORD; the sign and the size of the speed on that Tick, and the position, do not matter."""

    def test_Z_T09_Z_T10_leaving_in_either_direction_by_any_non_zero_speed_scores_the_early_departure_once(self):
        """[guard] +0.0001 / -0.0001 / +-0.1 / the smallest double: the Tick of the switch scores the existing 100 (29 s early) once and the stop is complete."""
        for speed in (MIN_POS, MIN_NEG, 0.0001, -0.0001, 0.1, -0.1, 12.0, -12.0):
            with self.subTest(speed=repr(speed)):
                self.fresh()
                self.arrive(d=1.0, t_ms=DEP - 60000)
                o = self.switch(DEP - 29000, speed=speed)
                self.assertEqual(self.time_points(), 100)
                self.assertEqual(len([p for p in o.popups if p.get("category") == "運転時分"]), 1)
                self.assertIn(self.latch(), (None, "ABSENT"))
                self.assertFalse(o.has_scored_stop_this_station)

    def test_Z_T11_standing_until_the_scheduled_time_is_error_0_300_points(self):
        """[guard] the stop was made 30 s before the departure; the sender switches at the departure time (+ its 300 ms hold) at speed 0.0 / -0.0: error 0 -> 300, once."""
        for speed in STOPPED:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                self.arrive(d=1.0, t_ms=DEP - 30000)
                o = self.switch(DEP + 300, speed=speed)
                self.assertEqual(self.time_points(), 300)
                self.assertEqual(len([p for p in o.popups if p.get("category") == "運転時分"]), 1)

    def test_Z_T12_the_position_at_the_departure_is_not_judged_again(self):
        """[guard] the stop was made inside the range; the vehicle is 30 m past B (far outside +-5) when it leaves: scored, not zeroed by the position."""
        for location in (B_LOC + 30.0, B_LOC - 30.0, B_LOC + 5.0001, B_LOC - 5.0001):
            with self.subTest(location=location):
                self.fresh()
                self.arrive(d=1.0, t_ms=DEP - 60000)
                self.switch(DEP - 15000, speed=0.0001, location=location)
                self.assertEqual(self.time_points(), 200)

    def test_Z_T13_a_pass_through_without_a_stop_keeps_the_target_and_gives_no_driving_time(self):
        """[guard] fail-closed: no stop in the range -> no latch; even if the target moved on nothing is scored for the operational stop."""
        o = self.scene(d=20.0, t_ms=DEP - 20000, speed=30.0)
        self.tick()
        self.assertEqual(o.bve_next_loc, B_LOC)
        o = self.switch(DEP - 19000, speed=30.0, location=B_LOC + 1.0)
        self.assertEqual(self.time_points(), 0)
        self.assertIn(self.latch(), (None, "ABSENT"))

    def test_Z_T14_the_first_stop_after_the_scheduled_departure_is_scored_at_the_time_of_that_stop(self):
        """[guard] the first stop inside the range comes 29.9 s after the departure time: floor 29 s -> 100; the switch 300 ms later (30.2 s) must not be the actual time."""
        self.arrive(d=1.0, t_ms=DEP + 29900)
        self.assertEqual(self.latch()[1], DEP + 29900)
        self.switch(DEP + 30200, speed=0.0)
        self.assertEqual(self.time_points(), 100)

    def test_Z_T15_the_scheduled_time_and_a_non_zero_speed_on_the_same_tick_are_error_0_and_complete_once(self):
        """[guard] the Tick is the departure time itself and the vehicle moves: scheduled-time-reached has the priority -> error 0 -> 300, one popup, no second scoring later."""
        for speed in (0.0001, -0.0001, 0.1, 12.0):
            with self.subTest(speed=repr(speed)):
                self.fresh()
                self.arrive(d=1.0, t_ms=DEP - 30000)
                o = self.switch(DEP, speed=speed)
                self.assertEqual(self.time_points(), 300)
                self.assertEqual(len([p for p in o.popups if p.get("category") == "運転時分"]), 1)
                for _ in range(4):
                    o.bve_time_ms += 1000
                    o.bve_location += 5.0
                    self.tick()
                self.assertEqual(self.time_points(), 300)

    def test_Z_T15b_without_a_target_switch_the_scoring_side_scores_nothing_whatever_the_speed(self):
        """[guard] the switch is the sender's: any speed (0.0001, 0.1, -0.1, 30) on a Tick without a NEXTLOC change scores and switches nothing here."""
        for speed in MOVING:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                o = self.arrive(d=1.0, t_ms=DEP - 60000)
                o.bve_speed = speed
                o.bve_time_ms += 100
                self.tick()
                self.assertEqual(self.time_points(), 0)
                self.assertEqual(o.bve_next_loc, B_LOC)
                self.assertNotEqual(self.latch(), None)


# =====================================================================================================================================================================================
class C_KeysAndFastForward(Base):
    """F7 / F8 / P and the fast-forward release. The "is the train moving" test of F8 and of the release is speed != 0.0 (either sign); F7 and P are suppressed whatever the speed."""

    def scoring(self, speed, finished=False):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = finished
        o.bve_speed = speed

    def fast_forward(self, bve_ms=1000, real=0.06):
        self.rig.tick()
        self.clock.now += real
        self.o.bve_time_ms += bve_ms
        self.rig.tick()

    def test_Z_F8_hook_follows_speed_not_zero_for_every_speed_and_both_signs(self):
        """[RED-B3] the F8 hook is registered iff speed != 0.0: 0.0 / -0.0 not; the smallest double, +-0.0001, 0.09, 0.1, 5 and every NEGATIVE speed yes (before B3: only >= +0.1)."""
        for speed in STOPPED + MOVING:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                self.scoring(speed)
                self.rig.tick()
                expected = ["f7", "f8", "p"] if speed != 0.0 else ["f7", "p"]
                self.assertEqual(self.kb.active(), expected)

    def test_Z_F8_hook_boundary_0_1_is_no_longer_a_boundary(self):
        """[RED-B3] 0.09 -> 0.1 changed the hook before B3; now 0.0 -> 0.0001 does, and 0.0001 -> 0.1 does not."""
        self.scoring(0.0)
        self.rig.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])
        self.o.bve_speed = 0.0001
        self.rig.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        self.o.bve_speed = 0.1
        self.rig.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        self.o.bve_speed = NEG_ZERO
        self.rig.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])

    def test_Z_F7_and_P_do_not_look_at_the_speed(self):
        """[guard] F7 and P are suppressed in a running scoring whatever the speed; before the scoring and after its end nothing is suppressed."""
        for speed in STOPPED + MOVING:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                self.scoring(speed)
                self.rig.tick()
                self.assertIn("f7", self.kb.active())
                self.assertIn("p", self.kb.active())
                self.fresh()
                self.o.bve_speed = speed
                self.rig.tick()
                self.assertEqual(self.kb.active(), [])
                self.fresh()
                self.scoring(speed, finished=True)
                self.rig.tick()
                self.assertEqual(self.kb.active(), [])

    def test_Z_FF_release_follows_speed_not_zero_for_every_speed_and_both_signs(self):
        """[RED-B3] a fast forward during a running scoring is released (F8 down + up posted) iff speed != 0.0: 0.0 / -0.0 not; +-0.0001, 0.09, 0.1, the smallest double and 5 yes."""
        for speed in STOPPED + MOVING:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                self.scoring(speed)
                self.fast_forward()
                posts = f8_posts(self.api)
                if speed != 0.0:
                    self.assertEqual(len(posts), 2)
                else:
                    self.assertEqual(posts, [])

    def test_Z_FF_release_keeps_its_other_conditions_at_any_speed(self):
        """[guard] a finished scoring, an official jump and F8_disable == False still stop the release at a non-zero speed."""
        for speed in (0.0001, -0.1, 5.0):
            for finished, jumping, f8_disable in ((True, False, True), (False, True, True), (False, False, False)):
                with self.subTest(speed=repr(speed), finished=finished, jumping=jumping, f8_disable=f8_disable):
                    self.fresh()
                    self.scoring(speed, finished=finished)
                    self.o.is_official_jumping = jumping
                    self.o.F8_disable = f8_disable
                    self.fast_forward()
                    self.assertEqual(f8_posts(self.api), [])


# =====================================================================================================================================================================================
class D_SpeedLimitGuidance(Base):
    """The limit guidance (the upcoming restriction blinks) is shown while the train is moving: speed != 0.0, either sign. A standing train shows the plain limit."""

    def guidance(self, speed):
        o = self.o
        o.is_scoring_mode = False
        o.station_list = [R.station("A", 0.0), R.station("B", 5000.0, terminal=True)]
        o.bve_location = 1000.0
        o.bve_speed = speed
        o.map_tail_limit = 120.0
        o.map_head_limit = 120.0
        o.bve_signal_limit = 120.0
        o.bve_fwd_sig_limit = 1000.0
        o.bve_map_limits = [(1400.0, 40.0)]
        o.bve_clear_dist = 0.0
        o.bve_train_length = 100.0
        o.bve_time_ms = T0
        self.tick(3)
        return o

    def test_Z_blink_follows_speed_not_zero_for_every_speed_and_both_signs(self):
        """[RED-B3] before B3 the guidance needed speed > +0.1: 0.0001 / 0.05 / 0.1 and every negative speed showed no warning."""
        for speed in STOPPED + MOVING:
            with self.subTest(speed=repr(speed)):
                self.fresh()
                o = self.guidance(speed)
                moving = speed != 0.0
                self.assertEqual(o.blink_active, moving)
                self.assertEqual(o.disp_limit, 40.0 if moving else 120.0)

    def test_Z_blink_dbg_red_is_computed_at_every_speed(self):
        """[guard] the guidance candidates themselves do not depend on the gate: the warning for the 40 km/h section is found at a standstill too."""
        for speed in (0.0, 5.0):
            with self.subTest(speed=repr(speed)):
                self.fresh()
                o = self.guidance(speed)
                self.assertEqual(o.dbg_red, "40.0")


# =====================================================================================================================================================================================
class E_RetryAndJumpBoundary(Base):
    """The operational stop state at the Retry / Jump boundary (Current and Legacy share this Python side)."""

    def retry_to_b(self):
        o = self.o
        o.toggle_menu = lambda adv: None
        o.send_jump_command = lambda cmd: None
        o.save_data = [with_identity(cp(0.0, T0, "A"), 0, 0.0, role="scoring_start"),
                       with_identity(cp(B_LOC - 1.0, DEP - 30000, "B"), 1, B_LOC)]
        self.S.execute_retry(o, 1, True)
        self.assertTrue(o.is_official_jumping)
        return o

    def complete_jump(self, t=DEP - 30000):
        o = self.o
        exp = o.jump_expectation
        text, why = jump_wire.format_completion_v2("STA", 1, B_LOC, t, 1, tuple(exp.scope))
        self.assertIsNone(why)
        o._note_jump_complete(text)
        o._settle_jump_complete()
        self.assertFalse(o.is_official_jumping)

    def test_Z_T16_a_retry_request_clears_the_latch_with_the_other_per_station_state(self):
        """[guard] execute_retry resets the per-station evaluation state: nothing of the old stop is kept."""
        o = self.arrive(d=1.0, t_ms=DEP - 30000)
        self.assertNotEqual(self.latch(), None)
        self.retry_to_b()
        self.assertIsNone(o.operational_stop_latch)
        self.assertIsNone(o.operational_stop_margins)
        self.assertFalse(o.has_scored_stop_this_station)

    def test_Z_T16b_while_the_jump_is_outstanding_a_vehicle_still_standing_in_the_range_forms_no_latch(self):
        """[RED-B3] the telemetry before the landing is the OLD world (old position, old clock): it must not form the latch, the margins or the scored-stop mark (before B3 the stale time
        of the old clock became the stop time of the retried attempt)."""
        o = self.arrive(d=1.0, t_ms=DEP - 30000)
        self.retry_to_b()
        o.bve_time_ms = DEP + 20000                                                            # the old attempt stood on until 20 s after the departure time
        self.tick(3)
        self.assertIn(self.latch(), (None, "ABSENT"))
        self.assertIsNone(getattr(o, "operational_stop_margins", None))
        self.assertFalse(o.has_scored_stop_this_station)

    def test_Z_T17_a_target_switch_while_the_jump_is_outstanding_scores_no_driving_time(self):
        """[RED-B3] the sender switches the target (the old attempt leaves B) after the retry was requested and before the landing: nothing is scored for it (the retry flag must not turn
        the old world's departure into the points of the new attempt)."""
        self.arrive(d=1.0, t_ms=DEP - 60000)
        o = self.retry_to_b()
        self.tick()                                                                            # (the first Tick after a retry takes the NEXTLOC it sees as the reference: is_first_udp)
        before = o.score
        self.switch(DEP - 25000, speed=0.2)
        self.assertEqual(self.time_points(), 0)
        self.assertEqual(o.score, before)

    def test_Z_T17b_a_target_switch_while_the_jump_is_outstanding_does_not_use_a_latch_either(self):
        """[RED-B3] even a latch that is (artificially) present is not used for the completion while the jump is outstanding."""
        self.arrive(d=1.0, t_ms=DEP - 60000)
        o = self.retry_to_b()
        self.tick()
        o.operational_stop_latch = (1, DEP - 60000, DEP)
        self.switch(DEP - 25000, speed=0.2)
        self.assertEqual(self.time_points(), 0)

    def test_Z_T18_after_the_landing_the_latch_is_formed_again_from_the_first_new_stop(self):
        """[RED-B3] the retried attempt waits at B from the checkpoint time: the latch holds the NEW stop time and the scoring reads it, not the stale time of the old clock."""
        self.arrive(d=1.0, t_ms=DEP - 30000)
        o = self.retry_to_b()
        o.bve_time_ms = DEP + 20000                                                            # stale telemetry of the old world during the outstanding jump
        self.tick(2)
        o.bve_time_ms = DEP - 30000                                                            # the landing: the checkpoint time
        o.jump_lock = True
        self.complete_jump(t=DEP - 30000)
        self.tick()
        self.assertEqual(self.latch(), (1, DEP - 30000, DEP))
        o.jump_lock = True
        self.switch(DEP + 300, speed=0.0)
        self.assertEqual(self.time_points(), 300)                                              # error 0 (the old clock would have said: late by 20 s)

    def test_Z_T18b_a_retry_to_the_standing_station_works_end_to_end_with_an_early_departure(self):
        """[guard] the whole chain: stop, retry, landing, new stop, early departure: the new attempt scores its own early departure once."""
        self.arrive(d=1.0, t_ms=DEP - 60000)
        o = self.retry_to_b()
        o.bve_time_ms = DEP - 60000
        o.jump_lock = True
        self.complete_jump(t=DEP - 60000)
        self.tick()
        self.assertEqual(self.latch()[0], 1)
        self.switch(DEP - 25000, speed=-0.0001)
        self.assertEqual(self.time_points(), 100)

    def test_Z_T19_a_failed_jump_leaves_no_latch_and_scores_nothing(self):
        """[RED-B3] the jump is never completed (the deadline passes): the scoring is aborted, no latch is left (before B3 the telemetry of the outstanding jump had formed one), nothing is
        scored twice."""
        self.arrive(d=1.0, t_ms=DEP - 30000)
        o = self.retry_to_b()
        o.bve_time_ms = DEP + 20000
        self.tick(2)
        self.rig.advance(11.0)
        o._poll_jump_client()
        self.assertFalse(o.is_official_jumping)
        self.assertFalse(o.is_scoring_mode)
        self.assertIn(self.latch(), (None, "ABSENT"))
        before = (o.score, self.time_points())
        self.switch(DEP + 300, speed=0.0)
        self.assertEqual((o.score, self.time_points()), before)

    def test_Z_T20_the_scoring_finish_at_an_operational_stop_leaves_no_latch(self):
        """[RED-B3] the end station is an operational stop: the arrival scores its time and finishes the scoring; no stop record is kept after the finish."""
        o = self.scene(d=0.0, end_idx=1, speed=0.0)
        o.bve_next_time = o.bve_time_ms
        self.tick()
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(self.time_points(), 300)
        self.assertIn(self.latch(), (None, "ABSENT"))
        self.assertIsNone(getattr(o, "operational_stop_margins", None))

    def test_Z_T20b_the_session_end_leaves_no_latch(self):
        """[guard] discard_scoring_session (Session OFF / soft OFF) resets the per-station state."""
        o = self.arrive(d=1.0)
        self.assertNotEqual(self.latch(), None)
        self.MI.discard_scoring_session(o)
        self.assertIn(self.latch(), (None, "ABSENT"))
        self.assertIsNone(getattr(o, "operational_stop_margins", None))

    def test_Z_T20c_a_new_scenario_generation_leaves_no_latch(self):
        """[guard] discard_generation_state drops the attribute (a getattr default of 'never set')."""
        o = self.arrive(d=1.0)
        self.assertNotEqual(self.latch(), None)
        self.MI.discard_generation_state(o)
        self.assertEqual(self.latch(), "ABSENT")
        self.assertIsNone(getattr(o, "operational_stop_margins", None))

    def test_Z_T20d_a_scoring_start_leaves_no_stale_latch(self):
        """[guard] the scoring start resets the per-station state before its own jump: a latch of an earlier run is gone."""
        o = self.o
        o.station_list = [R.station("A", 0.0), R.station("B", 1000.0, terminal=True)]
        R.bind_identity(o)
        o.bve_time_ms = T0
        o.bve_actual_state = "RUNNING"
        o.operational_stop_latch = (1, T0 + 5, T0 + 9)
        o.operational_stop_margins = (5.0, 5.0)
        for key in ("f1", "down", "enter"):
            self.rig.tap(key)
        for _ in range(5):
            self.rig.tap("down")
        self.rig.tap("enter")
        for _ in range(6):
            self.rig.tap("down")
        self.rig.tap("enter")
        self.rig.tap("down")
        self.rig.tap("enter")
        self.assertTrue(o.is_scoring_mode)
        self.assertIsNone(o.operational_stop_latch)
        self.assertIsNone(o.operational_stop_margins)

    def test_Z_T20e_a_changed_scenario_in_the_plain_mode_leaves_no_latch(self):
        """[RED-B3] the plain (non managed) mode: a telemetry line of a NEW scenario id ends the scoring run; its stop record must not outlive the run."""
        o = self.arrive(d=1.0)
        self.assertNotEqual(self.latch(), None)
        o.current_scenario_id = 7
        o.apply_telemetry_text("SCENARIO_ID:8,SPEED:0")
        self.assertFalse(o.is_scoring_mode)
        self.assertIn(self.latch(), (None, "ABSENT"))


# =====================================================================================================================================================================================
class F_SourcePinsAndInventory(unittest.TestCase):
    """Source pins. They run without Qt."""

    @classmethod
    def setUpClass(cls):
        cls.main = read("main.py")
        cls.scoring = read("scoring_logic.py")
        cls.network = read("network.py")
        cls.current = read(os.path.join("TsScoringPlugin", "TsScoringPlugin", "Class1.cs"))
        cls.legacy = read(os.path.join("TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "src", "LegacyStationTimeline.cs"))
        cls.scoring_ast = ast.parse(cls.scoring)

    def function(self, name):
        return next(n for n in ast.walk(self.scoring_ast) if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_Z_pin_the_sender_stop_and_leaving_tests_are_the_zero_speed_contract(self):
        for text, speed, label in ((self.current, "speed", "Current"), (self.legacy, "speedKmh", "Legacy")):
            with self.subTest(sender=label):
                self.assertEqual(len(re.findall(r"bool isStopped = %s == 0\.0;" % speed, text)), 1)
                self.assertEqual(len(re.findall(r"&& !isTerminal && %s != 0\.0\)" % speed, text)), 1)
                self.assertNotRegex(text, r"Math\.Abs\(%s\) [<>] 0\.1" % speed)
                self.assertNotRegex(text, r"\b0\.1\b(?!\d)[^\n]*%s|%s[^\n]*\b0\.1\b(?!\d)" % (speed, speed))

    def test_Z_pin_main_py_moving_means_speed_not_zero(self):
        self.assertIn("if self.bve_speed != 0.0 and self.is_fast_forwarding:", self.main)
        self.assertIn("and self.bve_speed != 0.0 and is_bve_active and self.menu_state == 0", self.main)
        self.assertNotIn("abs(self.bve_speed) >= 0.1", self.main)
        self.assertNotIn("self.bve_speed >= 0.1", self.main)

    def test_Z_pin_scoring_logic_has_no_0_1_speed_test_left(self):
        self.assertNotIn("self.bve_speed > 0.1", self.scoring)
        self.assertIn("    if self.bve_speed != 0.0:\n        if active_red:", self.scoring.replace("\r\n", "\n"))

    def test_Z_pin_the_speed_is_read_without_any_rounding_or_normalisation(self):
        for text in (self.main, self.network):
            self.assertIn('elif part.startswith("SPEED:"): self.bve_speed = float(part.split(\':\')[1])', text)
        for text in (self.main, self.network, self.scoring):
            self.assertNotRegex(text, r"round\(\s*(self\.)?bve_speed")

    def test_Z_pin_inventory_of_the_remaining_speed_thresholds_other_than_zero(self):
        """Classification B (another concept, kept on purpose): the only comparisons of the speed with a non-zero number are the 1.0 km/h departure latch of a customer stop, the speed limit
        excess (limit + 1.0) and the warning distance arguments. Any new one must be classified, not slipped in."""
        found = []
        pattern = re.compile(r"bve_speed\s*(?:>=|<=|>|<|==|!=)\s*(?:[1-9]|0\.\d*[1-9])|abs_speed\s*(?:>=|<=|>|<)\s*[^\s]+\s*\+|max\(\s*self\.bve_speed")
        for name in ("main.py", "scoring_logic.py", "managed_input.py", "managed_hud.py", "hud_ui.py", "pause_recovery.py", "network.py", "utils.py", "telemetry_gate.py"):
            for number, line in enumerate(read(name).replace("\r\n", "\n").split("\n"), 1):
                if pattern.search(line):
                    found.append((name, line.strip()))
        self.assertEqual(found, [
            ("scoring_logic.py", "if current_limit < 999.0 and abs_speed >= current_limit + 1.0:"),
            ("scoring_logic.py", "and self.bve_speed >= 1.0"),
            ("scoring_logic.py", "calc_v = max(self.bve_speed, val + 1.0)"),
        ])

    def test_Z_pin_the_arrival_of_an_operational_stop_is_not_formed_while_a_jump_is_outstanding(self):
        arrival = next(line for line in self.scoring.replace("\r\n", "\n").split("\n") if "is_operational_stop and getattr(self, 'is_approaching', False)" in line)
        self.assertIn("self.bve_speed == 0.0", arrival)
        self.assertIn("not getattr(self, 'is_official_jumping', False)", arrival)

    def test_Z_pin_python_has_no_departure_speed_literal_in_the_operational_stop_code(self):
        for name in ("operational_stop_station", "resolve_operational_stop_completion"):
            self.assertNotRegex(ast.get_source_segment(self.scoring, self.function(name)), r"bve_speed|0\.1\b")


if __name__ == "__main__":
    unittest.main()
