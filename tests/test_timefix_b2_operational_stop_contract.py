"""Time Fix B2 - the operational stop (運転停車) CONTRACT of the scoring side: the stop must be established once inside the author-defined range; after that the time is scored at the moment the
sender switches the target (the scheduled departure time reached, or the vehicle leaving at |speed| > 0.1 km/h), and the position of the vehicle at that moment is NOT judged again.

WHAT THE SENDER DOES (Class1.cs for Current, LegacyStationTimeline.cs for Legacy; tested by Test-TimeFixB2.ps1): for a station with DoorDir == 0 the target is switched to the next station
  * at the scheduled departure time (+ the existing 300 ms hold), or
  * at once (the same Tick) when the stop was established in the range and |speed| > 0.1 km/h (either direction); exactly 0.1 km/h is not leaving.
  A vehicle that never stopped inside the range keeps the target (fail-closed: the scoring does not go on past an operational stop that was not made).
WHAT THIS FILE PINS (the Python side): on the Tick on which NEXTLOC changes forward, the operational stop that was LATCHED at its arrival (scoring_logic.update_physics_and_scoring) is scored by
the cause it can be told from its own record - never by a range test of the position at the switch:
  late-arrival            the first stop inside the range happened AFTER the scheduled departure: the time of that stop is the actual time
  scheduled-time-reached  the switch Tick is at or after the scheduled departure: error 0
  early-movement          the switch Tick is before the scheduled departure: the time of the switch Tick is the actual time
  The points are the existing ones (apply_time_score: |error| in whole seconds <= 9: 300, <= 19: 200, <= 29: 100, else 0; both times floored to the second as everywhere in this module).
tgt / arr / arrseq are never written here (the sender owns them).

Cases tagged [RED-B2] fail on the code before Time Fix B2 and pass after it; every other case is a guard that passes before and after. Without PyQt6 (python -I) the behaviour tests are SKIPPED;
the source pins always run.
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

import sia_rig as R  # noqa: E402

T0 = 36000000
DEP = T0 + 60000            # the scheduled departure of the operational stop B (a whole second)
B_LOC = 1000.0
C_LOC = 1100.0              # the next (customer) station is NEAR the operational stop
_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-timefix-b2-")
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
        raise AssertionError("the Time Fix B2 module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def stations_abcd():
    """A idx0 @0, B idx1 @1000 (the operational stop), C idx2 @1100 (a customer station right behind it), D idx3 @3000 (terminal)."""
    return [sta("A", 0.0), sta("B", B_LOC, is_timing=True, raw_dep=DEP), sta("C", C_LOC, is_timing=True), sta("D", 3000.0, terminal=True)]


def cp(loc, t, name="X"):
    return {"loc": loc, "time_ms": t, "score": 0, "target_loc": loc, "station_name": name, "stop_error": 0.0, "score_details": {}}


def read(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read().decode("utf-8-sig")


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["timefix-b2"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0

    def tick(self, n=1):
        for _ in range(n):
            self.t += 0.016
            self.S.update_physics_and_scoring(self.o, self.t, 0.016)

    def scene(self, d=1.0, t_ms=DEP - 30000, margins=(5.0, 5.0), retry=False, end_idx=3, doordir=0, is_pass=0):
        """The vehicle `d` m SHORT of the target B, stopped (speed 0.0), doors closed, after a departure, scoring on, `t_ms` on the BVE clock. NEXTLOC == prev_next_loc."""
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = stations_abcd()
        o.setting_end_idx = end_idx
        o.save_data = [cp(0.0, T0, "A")]
        o.bve_next_loc = o.prev_next_loc = B_LOC
        o.bve_location = B_LOC - d
        o.bve_speed = 0.0
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
        o.is_official_retry = retry
        if not getattr(o, "bve_list_id", ""):
            R.bind_identity(o)
        return o

    def arrive(self, d=1.0, t_ms=DEP - 30000, margins=(5.0, 5.0), retry=False, end_idx=3):
        """The operational stop B is arrived at: one Tick at speed 0.0 inside the range."""
        o = self.scene(d=d, t_ms=t_ms, margins=margins, retry=retry, end_idx=end_idx)
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


# =====================================================================================================================================================================================
class A_TheLatchAtTheArrival(Base):
    def test_C_T01a_the_stop_inside_the_range_latches_the_operational_stop_with_the_arrived_station_values(self):
        """[RED-B2] operationalStopLatched / Index / Margins / scheduledDepartureTime / arrival time are kept at the arrival."""
        o = self.arrive(d=1.0, t_ms=DEP - 30000, margins=(3.0, 8.0))
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(o.operational_stop_margins, (3.0, 8.0))
        self.assertEqual(self.latch(), (1, DEP - 30000, DEP))                                  # (station index of B, time of the stop, scheduled departure of B)

    def test_C_T09a_no_stop_inside_the_range_means_no_latch(self):
        """[guard] the vehicle passes B without ever standing inside its range: nothing is latched, nothing is scored, the target stays."""
        o = self.scene(d=20.0)
        o.bve_speed = 30.0
        for loc in (985.0, 995.0, 1005.0, 1015.0, 1030.0):
            o.bve_location = loc
            o.bve_time_ms += 500
            self.tick()
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertEqual(self.latch(), None if hasattr(o, "operational_stop_latch") else "ABSENT")
        self.assertEqual(o.bve_next_loc, B_LOC)
        self.assertEqual(o.score_details["time"], 0)
        self.assertEqual(o.save_data[-1]["station_name"], "A")                                 # no checkpoint for B

    def test_C_T10_an_overrun_stop_outside_the_range_means_no_latch_and_no_switch_is_made_by_the_scoring(self):
        """[guard] stopped 12 m past B (range +-5): outside the author-defined range -> no arrival, no latch, no time; passing the far boundary decides nothing."""
        o = self.scene(d=-12.0, t_ms=DEP + 5000)
        self.tick(3)
        self.assertTrue(o.is_stopped_out_of_range)
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertIn(getattr(o, "operational_stop_latch", None), (None,))
        self.assertEqual(o.bve_next_loc, B_LOC)
        self.assertEqual(o.score_details["time"], 0)

    def test_C_T20_the_range_of_the_arrived_station_decides_the_stop_not_the_range_of_the_next_one(self):
        """[guard] 4 m short of B whose range is +-2 (C's would be +-5): outside the range of B -> no operational stop."""
        o = self.arrive(d=4.0, margins=(2.0, 2.0))
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertIn(getattr(o, "operational_stop_latch", None), (None,))
        self.switch(DEP + 300, speed=0.0, next_margins=(5.0, 5.0))
        self.assertEqual(o.score_details["time"], 0)

    def test_C_T19_the_range_of_the_arrived_station_decides_the_stop_even_when_the_next_range_is_smaller(self):
        """[RED-B2] 4 m short of B whose range is +-5 (C's is +-2): the stop is made with B's range, and the departure is not judged with C's."""
        self.arrive(d=4.0, margins=(5.0, 5.0))
        self.assertEqual(self.latch()[0], 1)
        o = self.switch(DEP + 300, speed=0.0, next_margins=(2.0, 2.0))
        self.assertEqual(o.score_details["time"], 300)


# =====================================================================================================================================================================================
class B_TheCompletion(Base):
    def test_C_T01_the_scheduled_time_reached_while_standing_scores_error_0_and_clears_the_latch(self):
        """The stop was made 30 s before the departure; the sender switches at the departure time (+ its 300 ms hold): error 0 -> 300."""
        o = self.arrive(d=1.0, t_ms=DEP - 30000)
        self.assertTrue(o.has_scored_stop_this_station)
        o = self.switch(DEP + 300, speed=0.0)
        self.assertEqual(o.score_details["time"], 300)
        self.assertTrue(any(p.get("category") == "運転時分" for p in o.popups))
        self.assertEqual(len([p for p in o.popups if p.get("category") == "運転時分"]), 1)    # once
        self.assertFalse(o.has_scored_stop_this_station)                                       # per-station state is cleared with the switch
        self.assertIn(getattr(o, "operational_stop_latch", None), (None,))

    def test_C_T01b_the_vehicle_creeping_out_of_the_range_while_waiting_does_not_cost_the_time(self):
        """[RED-B2] the range is judged ONCE, at the stop. Waiting at 0.09 km/h the vehicle drifts 7 m past B (range +-5) before the departure time; the departure time still scores 300."""
        o = self.arrive(d=1.0, t_ms=DEP - 30000)
        o = self.switch(DEP + 300, speed=0.0, location=B_LOC + 7.0)
        self.assertEqual(o.score_details["time"], 300)

    def test_C_T02_leaving_29_seconds_early_scores_the_existing_points_at_that_moment(self):
        """The vehicle leaves (the sender switches on the first Tick above 0.1 km/h) 29 s before the departure: error -29 s -> 100."""
        self.arrive(d=1.0, t_ms=DEP - 60000)
        o = self.switch(DEP - 29000, speed=0.2)
        self.assertEqual(o.score_details["time"], 100)
        self.assertEqual(o.bve_next_loc, C_LOC)                                                # (the switch itself is the sender's; the scoring moved with it)

    def test_C_T02b_the_early_boundaries_are_the_existing_ones(self):
        """whole seconds, both times floored: 9 s -> 300, 10 s -> 200, 19 s -> 200, 20 s -> 100, 29 s -> 100, 30 s -> 0."""
        for early_ms, expect in ((9000, 300), (10000, 200), (19000, 200), (20000, 100), (29000, 100), (30000, 0), (45000, 0)):
            with self.subTest(early_ms=early_ms):
                self.rig.close()
                self.setUp()
                self.arrive(d=1.0, t_ms=DEP - 60000)
                o = self.switch(DEP - early_ms, speed=0.2)
                self.assertEqual(o.score_details["time"], expect)

    def test_C_T03_leaving_exactly_at_the_scheduled_time_is_error_0(self):
        """the switch Tick is the departure time itself and the vehicle is moving: scheduled-time-reached has the priority -> error 0 -> 300, once."""
        self.arrive(d=1.0, t_ms=DEP - 30000)
        o = self.switch(DEP, speed=0.2)
        self.assertEqual(o.score_details["time"], 300)
        self.assertEqual(len([p for p in o.popups if p.get("category") == "運転時分"]), 1)

    def test_C_T04_T05_the_sign_of_the_speed_does_not_matter_to_the_scoring(self):
        """forward or backward leaving: the same switch Tick, the same score (the sender decides leaving by |speed|)."""
        scores = []
        for speed in (0.2, -0.2, 12.0, -12.0):
            self.rig.close()
            self.setUp()
            self.arrive(d=1.0, t_ms=DEP - 60000)
            scores.append(self.switch(DEP - 25000, speed=speed).score_details["time"])
        self.assertEqual(scores, [100, 100, 100, 100])

    def test_C_T06_the_scoring_does_not_switch_or_score_by_itself_at_0_1_kmh_or_below(self):
        """the target switch is the sender's: without a NEXTLOC change nothing is scored or switched, whatever the speed (0.1 km/h exactly is not leaving)."""
        o = self.arrive(d=1.0, t_ms=DEP - 60000)
        for speed in (0.1, -0.1, 0.05, 0.0):
            o.bve_speed = speed
            o.bve_time_ms += 100
            self.tick()
        self.assertEqual(o.score_details["time"], 0)
        self.assertEqual(o.bve_next_loc, B_LOC)
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertNotEqual(self.latch(), None)

    def test_C_T07_the_scoring_does_not_decide_leaving_either(self):
        """> 0.1 km/h without a NEXTLOC change: the Python side scores nothing (no second owner of the switch)."""
        o = self.arrive(d=1.0, t_ms=DEP - 60000)
        for speed in (0.2, -0.2, 5.0):
            o.bve_speed = speed
            o.bve_time_ms += 100
            self.tick()
        self.assertEqual(o.score_details["time"], 0)
        self.assertEqual(o.bve_next_loc, B_LOC)

    def test_C_T08_the_first_stop_after_the_scheduled_departure_is_scored_at_the_time_of_that_stop(self):
        """[RED-B2] the vehicle stops inside the range 29.9 s after the departure time (floor: 29 s -> 100); the sender switches 300 ms later (30.2 s: 0 points if THAT time were used)."""
        self.arrive(d=1.0, t_ms=DEP + 29900)
        self.assertEqual(self.latch()[1], DEP + 29900)
        o = self.switch(DEP + 30200, speed=0.0)
        self.assertEqual(o.score_details["time"], 100)

    def test_C_T08b_a_late_stop_far_beyond_the_departure_scores_nothing(self):
        self.arrive(d=1.0, t_ms=DEP + 45000)
        o = self.switch(DEP + 45300, speed=0.0)
        self.assertEqual(o.score_details["time"], 0)
        self.assertEqual(o.bve_next_loc, C_LOC)

    def test_C_T08c_a_late_stop_within_9_seconds_scores_300(self):
        self.arrive(d=1.0, t_ms=DEP + 4000)
        o = self.switch(DEP + 4300, speed=0.0)
        self.assertEqual(o.score_details["time"], 300)

    def test_C_T09_a_switch_without_any_stop_inside_the_range_scores_nothing(self):
        """fail-closed: if the target nevertheless moves on (it never does with the senders of B2), a stop that was never made earns no time."""
        o = self.scene(d=20.0, t_ms=DEP - 20000)
        o.bve_speed = 30.0
        self.tick()
        o = self.switch(DEP - 19000, speed=30.0, location=B_LOC + 1.0)
        self.assertEqual(o.score_details["time"], 0)

    def test_C_T13_a_retry_before_the_operational_stop_follows_the_same_contract(self):
        """[RED-B2] after an official retry (jump lock on) the stop is made again and latched; leaving early scores; the retry flag is consumed by the scoring."""
        o = self.scene(d=1.0, t_ms=DEP - 40000, retry=True)
        o.jump_lock = True
        self.tick()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(self.latch()[0], 1)
        o = self.switch(DEP - 15000, speed=0.2)
        self.assertEqual(o.score_details["time"], 200)
        self.assertFalse(o.is_official_retry)

    def test_C_T13b_the_retry_clears_the_latch_with_the_other_per_station_state(self):
        """[RED-B2] execute_retry / the session end call reset_station_evaluation_state: nothing of the old stop may survive into the new attempt."""
        o = self.arrive(d=1.0)
        self.S.reset_station_evaluation_state(o)
        self.assertIsNone(o.operational_stop_margins)
        self.assertIsNone(getattr(o, "operational_stop_latch", "ABSENT"))

    def test_C_T14_a_stop_is_scored_once(self):
        """[RED-B2] more ticks after the switch score nothing more, and the latch is gone; the pure resolver gives the same answer however often it is asked."""
        self.arrive(d=1.0, t_ms=DEP - 30000)
        latch = self.latch()
        o = self.switch(DEP - 25000, speed=0.2)
        self.assertEqual(o.score_details["time"], 100)                                         # 25 s early
        scored = o.score_details["time"]
        for k in range(1, 6):
            o.bve_time_ms += 1000
            o.bve_location += 5.0
            self.tick()
        self.assertEqual(o.score_details["time"], scored)
        a = self.S.resolve_operational_stop_completion(latch, DEP - 25000)
        b = self.S.resolve_operational_stop_completion(latch, DEP - 25000)
        self.assertEqual(a, b)

    def test_C_T11_after_an_early_leaving_the_next_customer_station_is_arrived_at_normally(self):
        """the target is C before the departure time of B: C's stop and door-open arrival are scored and a checkpoint is made for it."""
        self.arrive(d=1.0, t_ms=DEP - 60000)
        o = self.switch(DEP - 50000, speed=0.2, location=B_LOC - 0.9)
        before = len(o.save_data)
        R.bind_identity(o, arr_idx=2, tgt_idx=2)
        o.bve_current_station_name = "C"
        o.bve_time_ms = DEP - 20000
        o.bve_speed = 0.0
        o.bve_location = C_LOC - 0.4
        o.prev_is_pass = 0
        self.tick(2)
        o.bve_door = 1
        self.tick(2)
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(len(o.save_data), before + 1)
        self.assertTrue(o.score_details["stop"] > 0)

    def test_C_T12_the_switch_does_not_touch_arr_or_arrseq(self):
        """tgt / arr / arrseq are the sender's published values: the scoring neither writes nor resets them on the switch."""
        o = self.arrive(d=1.0, t_ms=DEP - 60000)
        o.bve_arr_idx, o.bve_arr_seq = 1, 5
        o = self.switch(DEP - 50000, speed=0.2)
        self.assertEqual((o.bve_arr_idx, o.bve_arr_seq), (1, 5))

    def test_C_T15_a_customer_stop_keeps_its_contract(self):
        """a door-opening stop is not an operational stop: no latch, and its departure keeps the (ST-0 T19) behaviour of the new target's range."""
        o = self.scene(d=0.0, doordir=1)
        self.tick()
        o.bve_door = 1
        self.tick()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertIn(getattr(o, "operational_stop_latch", None), (None,))
        self.assertIsNone(getattr(o, "operational_stop_margins", None))

    def test_C_T16_a_pass_station_keeps_its_contract(self):
        o = self.scene(d=0.0, doordir=0, is_pass=1)
        self.tick(3)
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertIn(getattr(o, "operational_stop_latch", None), (None,))
        self.assertEqual(o.score_details["time"], 0)

    def test_C_T17_the_scoring_finish_operational_stop_is_unchanged(self):
        """CURRENT-BEHAVIOR-ONLY: the END station that is an operational stop scores its arrival time at the arrival and finishes the scoring there."""
        o = self.scene(d=0.0, end_idx=1)
        o.station_list = stations_abcd()
        o.bve_next_time = o.bve_time_ms                                                        # the arrival time of the end station is what NEXTTIME shows before the arrival
        self.tick()
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(o.score_details["time"], 300)

    def test_C_T18_equal_ranges_give_the_run_c_result(self):
        self.arrive(d=1.0, t_ms=DEP - 30000, margins=(5.0, 5.0))
        o = self.switch(DEP + 300, speed=0.0, next_margins=(5.0, 5.0))
        self.assertEqual(o.score_details["time"], 300)


# =====================================================================================================================================================================================
class C_TheResolver(Base):
    """The pure part: (latch, the time of the switch Tick) -> reason, errors, the diagnostic fields. A fixture-side diagnostic: nothing is logged by the product."""

    def resolve(self, arrival_ms, now_ms, dep=DEP):
        return self.S.resolve_operational_stop_completion((1, arrival_ms, dep), now_ms)

    def test_scheduled_time_reached(self):
        r = self.resolve(DEP - 30000, DEP + 300)
        self.assertEqual((r["reason"], r["signed_error_ms"], r["absolute_error_ms"], r["diff_s"]), ("scheduled-time-reached", 0, 0, 0))
        self.assertEqual((r["station_index"], r["scheduled_ms"], r["actual_ms"]), (1, DEP, DEP))

    def test_early_movement(self):
        r = self.resolve(DEP - 60000, DEP - 29000)
        self.assertEqual((r["reason"], r["signed_error_ms"], r["absolute_error_ms"], r["diff_s"]), ("early-movement", -29000, 29000, 29))
        self.assertEqual((r["station_index"], r["scheduled_ms"], r["actual_ms"]), (1, DEP, DEP - 29000))

    def test_late_arrival(self):
        r = self.resolve(DEP + 29900, DEP + 30200)
        self.assertEqual((r["reason"], r["signed_error_ms"], r["absolute_error_ms"], r["diff_s"]), ("late-arrival", 29900, 29900, -29))
        self.assertEqual((r["station_index"], r["scheduled_ms"], r["actual_ms"]), (1, DEP, DEP + 29900))

    def test_the_priority_at_the_same_tick_is_the_scheduled_time(self):
        self.assertEqual(self.resolve(DEP - 5000, DEP)["reason"], "scheduled-time-reached")
        self.assertEqual(self.resolve(DEP, DEP)["reason"], "scheduled-time-reached")              # a stop made AT the departure time is not late

    def test_no_usable_scheduled_time_gives_no_score(self):
        self.assertIsNone(self.S.resolve_operational_stop_completion((1, DEP - 1000, -1), DEP))
        self.assertIsNone(self.S.resolve_operational_stop_completion((1, DEP - 1000, 0), DEP))


# =====================================================================================================================================================================================
class D_SourcePins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = read("scoring_logic.py")
        cls.tree = ast.parse(cls.src)
        cls.managed = read("managed_input.py")

    def function(self, name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError("no function " + name)

    def test_B2_pin_the_latch_is_written_in_exactly_one_place_the_operational_arrival(self):
        self.assertEqual(len(re.findall(r"self\.operational_stop_latch\s*=\s*\(", self.src)), 1)
        self.assertEqual(len(re.findall(r"self\.operational_stop_latch\s*=\s*None", self.src)), 1)
        reset = ast.get_source_segment(self.src, self.function("reset_station_evaluation_state"))
        self.assertIn("self.operational_stop_latch = None", reset)
        physics = ast.get_source_segment(self.src, self.function("update_physics_and_scoring"))
        block = physics[physics.index("if is_operational_stop and getattr(self, 'is_approaching', False)"):]
        block = block[:block.index("# 通常停車駅の開扉時は")]
        self.assertLess(block.index("self.operational_stop_latch ="), block.index("self.has_scored_stop_this_station = True"))

    def test_B2_pin_the_departure_resolves_the_latched_stop_without_a_range_test(self):
        dep = ast.get_source_segment(self.src, self.function("evaluate_departure"))
        self.assertIn("resolve_operational_stop_completion(", dep)
        self.assertIn("getattr(self, 'operational_stop_latch', None)", dep)
        resolver = ast.get_source_segment(self.src, self.function("resolve_operational_stop_completion"))
        self.assertNotIn("bve_location", resolver)                                                # the position of the vehicle is not an input of the completion
        self.assertNotIn("margin", resolver)

    def test_B2_pin_the_speed_threshold_is_not_decided_by_the_scoring(self):
        """the target switch is the sender's: no 0.1 km/h leaving test in the scoring side's operational stop code."""
        for name in ("resolve_operational_stop_completion", "evaluate_departure"):
            self.assertNotRegex(ast.get_source_segment(self.src, self.function(name)), r"bve_speed|0\.1\b")

    def test_B2_pin_tgt_arr_and_arrseq_are_never_written_by_the_scoring(self):
        self.assertEqual(re.findall(r"self\.bve_(?:tgt_idx|arr_idx|arr_seq)\s*(?:=|\+=)(?!=)", self.src), [])

    def test_B2_pin_the_new_state_is_classified_as_a_getattr_default_attribute(self):
        self.assertIn('"operational_stop_latch"', self.managed)

    def test_B2_pin_the_senders_leave_an_operational_stop_when_the_vehicle_moves_once_the_stop_was_made(self):
        """Time Fix B3 (an owner-approved supersession): the 0.1 km/h band of B2 (leaving = |speed| > 0.1, stopped = |speed| < 0.1) is replaced by the exact zero-speed contract (leaving = speed != 0.0, stopped = speed == 0.0)."""
        current = read("TsScoringPlugin/TsScoringPlugin/Class1.cs")
        legacy = read("TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs")
        self.assertEqual(len(re.findall(r"hasDoorOpenedAtTarget && opStopMadeIndex == targetStationIndex && !isTerminal && speed != 0\.0\)", current)), 1)
        self.assertEqual(len(re.findall(r"hasDoorOpenedAtTarget && opStopMadeIndex == target && !isTerminal && speedKmh != 0\.0\)", legacy)), 1)
        self.assertEqual(len(re.findall(r"bool isStopped = speed == 0\.0;", current)), 1)
        self.assertEqual(len(re.findall(r"bool isStopped = speedKmh == 0\.0;", legacy)), 1)


if __name__ == "__main__":
    unittest.main()
