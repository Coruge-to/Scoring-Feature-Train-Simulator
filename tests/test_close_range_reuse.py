"""Close-range departure reset (pending flag + previous actual stop anchor) - the tests earlier scene tests re-expressed for the final contract.

Contract (Owner, OD-CR-1/5/9/13/14): a directly adjacent stop -> stop pair whose near edge is within the stop distance of the previous ACTUAL stop position sets
close_range_departure_reset_pending at the target switch; while pending nothing of the next station is formed; the first bve_speed > 0.0 (NOT a negative or zero speed) resets the
early-stop state and the basic-braking state in the same tick, once. has_departed is NOT used and NOT changed.

Meanings: GUARD (unchanged behaviour), CONTRACT (the final contract), CONSEQUENCE (what the existing rules do after the reset).
ISOLATION: the same seams as tests/sia_rig.py; USERPROFILE / HOME point to an empty temporary folder. Without PyQt6 (python -I) every scene test is SKIPPED, never passed.
"""
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

MEANINGS = ("GUARD", "CONTRACT", "CONSEQUENCE")
T0 = 36000000
ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
_TMP_HOME = {}


def meaning(kind, note=""):
    assert kind in MEANINGS, kind

    def deco(fn):
        fn.close_range = {"meaning": kind, "note": note}
        return fn
    return deco


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-close-range-reuse-")
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
        raise AssertionError("the close-range module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def stations(gap):
    """S idx0 @0, A idx1 @1000 (customer stop), B idx2 @1000+gap, T idx3 @6000 (terminal). gap 3000 = far, 150 = a close pair (inside 220 m)."""
    return [sta("S", 0.0), sta("A", 1000.0), sta("B", 1000.0 + gap), sta("T", 6000.0, terminal=True)]


LOC_A = 999.7          # where the train stands at A (0.3 m short of the stop mark: inside the +-5 m range, +350 stop points)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["close-range-reuse"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0

    # -- the scene: the train arrives at A on a mid-run scoring (has_departed already True), target A -----------------------------------------------------
    def build(self, gap, end_idx=3):
        o = self.o
        sl = stations(gap)
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = sl
        o.setting_end_idx = end_idx
        s0, a = sl[0], sl[1]
        o.save_data = [{"loc": s0["location"], "time_ms": T0, "score": 0, "target_loc": s0["location"], "station_name": s0["name"], "stop_error": 0.0,
                        "score_details": dict(ZERO), "station_index": 0, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, len(sl)), "station_location": s0["location"],
                        "role": "scoring_start"}]
        o.bve_next_loc = o.prev_next_loc = a["location"]
        o.bve_tgt_idx = 1
        o.bve_arr_idx = 0
        o.bve_arr_seq = 0
        o.bve_location = a["location"] - 400.0
        o.bve_speed = 30.0
        o.bve_is_pass = 0
        o.bve_doordir = 1
        o.bve_door = o.prev_door = 0
        o.bve_margin_f = o.bve_margin_b = 5.0
        o.has_departed = True
        o.is_first_station = False
        o.is_first_udp = False
        o.bve_time_ms = T0
        o.bve_next_time = T0 + 60000
        o.bve_current_station_name = a["name"]
        o.jump_lock = False
        o.is_official_jumping = False
        o.prev_is_pass = 0
        o.prev_is_timing = 1
        o.prev_doordir = 1
        o.is_official_retry = False
        o.bve_brk_notch = 0
        o.bve_calc_g = 0.0
        R.bind_identity(o, arr_idx=0, tgt_idx=1)
        self.S.reset_station_evaluation_state(o)
        self.tick()
        return o

    def tick(self, **fields):
        o = self.o
        for k, v in fields.items():
            setattr(o, k, v)
        o.bve_time_ms += 16
        self.t += 0.016
        self.S.update_physics_and_scoring(o, self.t, 0.016)

    def step(self, n=1, **fields):
        for i in range(n):
            self.tick(**(fields if i == 0 else {}))

    def stop_at_a_and_switch(self, gap, **switch):
        """Customer stop at A (notch 4), door open (arrival), door closed, then the sender switches to B while the train still stands (speed 0.0)."""
        self.step(bve_speed=5.0, bve_location=900.0, bve_brk_notch=3)
        self.step(bve_speed=2.0, bve_location=990.0, bve_brk_notch=3)
        self.step(n=3, bve_speed=0.0, bve_location=LOC_A, bve_brk_notch=4)
        self.step(bve_door=1, bve_arr_idx=1, bve_arr_seq=1)
        self.step(n=3)
        self.step(bve_door=0)
        fields = dict(bve_next_loc=1000.0 + gap, bve_tgt_idx=2, bve_margin_f=5.0, bve_margin_b=5.0, bve_next_time=T0 + 300000)
        fields.update(switch)
        self.step(**fields)
        self.step(n=4)

    def depart_and_stop_at_b(self, gap):
        """A releases to notch 0 and starts, accelerates, brakes 3 -> 2 for B, stops 0.3 m short with the cushion notch 1 (a STRONG notch at the stop would forfeit the basic brake by the existing rule), the door opens (the arrival of B)."""
        nb = 1000.0 + gap
        self.step(n=25, bve_brk_notch=0, bve_speed=0.5, bve_location=999.9)
        self.step(n=3, bve_speed=20.0, bve_location=1040.0)
        self.step(n=3, bve_speed=40.0, bve_location=1100.0 if gap > 200 else 1060.0)
        self.step(n=25, bve_brk_notch=3, bve_speed=20.0, bve_location=nb - 60.0)
        self.step(n=25, bve_brk_notch=2, bve_speed=8.0, bve_location=nb - 20.0)
        self.step(n=3, bve_brk_notch=1, bve_speed=0.0, bve_location=nb - 0.3)
        self.step(bve_door=1, bve_arr_idx=2, bve_arr_seq=2)

    def waiting(self):
        """True while the departure reset is pending. Reads the state by name so that the product without it fails the assertion, not the lookup."""
        return bool(getattr(self.o, "close_range_departure_reset_pending", False))

    def stop_points(self):
        return self.o.score_details["stop"]


# ==============================================================================================================================================
# A. GUARDS - what must not change
# ==============================================================================================================================================
class A_Guards(Base):
    @meaning("GUARD", "far pair: B is scored normally (stop +350, basic brake +500) after A")
    def test_G01_far_pair_scores_B_normally(self):
        self.build(3000.0)
        self.stop_at_a_and_switch(3000.0)
        a_points, a_brake = self.stop_points(), self.o.score_details["base_brake"]
        self.assertEqual(a_points, 350)                                     # A itself
        self.depart_and_stop_at_b(3000.0)
        self.assertEqual(self.stop_points() - a_points, 350)               # B
        self.assertEqual(self.o.score_details["base_brake"] - a_brake, 500)
        self.assertNotEqual(self.o.bb_state, "FAILED")

    @meaning("GUARD", "far pair: the approach and the verdicts of B are not formed while the train stands at A")
    def test_G02_far_pair_nothing_formed_at_A(self):
        o = self.build(3000.0)
        self.stop_at_a_and_switch(3000.0)
        self.assertEqual((o.is_approaching, o.is_stopped_out_of_range, o.bb_is_in_zone, o.has_scored_stop_this_station), (False, False, False, False))

    @meaning("GUARD", "an operational stop that the train leaves MOVING switches the target with a positive speed: B is monitored at once (no change to B2/B3)")
    def test_G03_switch_with_speed_nonzero_is_never_gated(self):
        o = self.build(150.0)
        self.step(n=3, bve_speed=0.0, bve_location=LOC_A, bve_brk_notch=4)
        self.step(bve_door=1, bve_arr_idx=1, bve_arr_seq=1)
        self.step(bve_door=0)
        self.step(bve_speed=0.3, bve_location=LOC_A + 0.1, bve_next_loc=1150.0, bve_tgt_idx=2, bve_next_time=T0 + 300000)
        self.step(n=2, bve_speed=3.0, bve_location=LOC_A + 1.0)
        self.assertFalse(self.waiting())
        self.assertTrue(o.bb_is_in_zone)                                    # the zone of the close pair is entered right after the departure

    @meaning("GUARD", "has_departed stays H-C: forward, doors closed, >= 1.0 km/h, not jumping; the target switch does not touch it")
    def test_G04_has_departed_is_unchanged(self):
        o = self.build(3000.0)
        o.has_departed = False
        for speed, door, expect in ((0.9999, 0, False), (-1.0, 0, False), (-5.0, 0, False), (30.0, 1, False), (1.0, 0, True)):
            with self.subTest(speed=speed, door=door):
                o.has_departed = False
                self.step(bve_speed=speed, bve_door=door, bve_location=900.0)
                self.assertEqual(o.has_departed, expect)
        o.bve_door = 0
        o.has_departed = True
        self.stop_at_a_and_switch(3000.0)
        self.assertTrue(o.has_departed)                                     # a target switch keeps it
        o.has_departed = False
        self.step(bve_next_loc=6000.0, bve_tgt_idx=3, bve_speed=0.0)       # another switch while it is False
        self.assertFalse(o.has_departed)                                    # ... and does not set it

    @meaning("GUARD", "the official jump blocks the has_departed latch")
    def test_G05_official_jump_blocks_the_latch(self):
        o = self.build(3000.0)
        o.has_departed = False
        o.is_official_jumping = True
        self.step(bve_speed=30.0, bve_door=0)
        self.assertFalse(o.has_departed)
        o.is_official_jumping = False
        self.step(bve_speed=30.0)
        self.assertTrue(o.has_departed)


# ==============================================================================================================================================
# B. THE CONTRACT - close pair
# ==============================================================================================================================================
class B_ClosePair(Base):
    @meaning("CONTRACT", "the switch while standing opens the gate: B's verdicts and basic-brake zone are not formed at A (A1)")
    def test_K01_close_pair_nothing_of_B_is_formed_while_standing_at_A(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        self.assertTrue(self.waiting())
        self.assertFalse(o.is_stopped_out_of_range)
        self.assertFalse(o.bb_is_in_zone)
        self.assertFalse(getattr(o, "bb_first_valid_stop_detected", False))
        self.step(n=30)
        self.assertTrue(self.waiting())
        self.assertEqual((o.is_stopped_out_of_range, o.bb_is_in_zone), (False, False))

    @meaning("CONTRACT", "A1 end to end: the release at A is not B's; B is scored (stop +350) and its basic brake succeeds (+500) in a close pair")
    def test_K02_close_pair_B_is_scored_after_departing_A(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        a_points, a_brake = self.stop_points(), o.score_details["base_brake"]
        self.depart_and_stop_at_b(150.0)
        self.assertNotEqual(o.bb_state, "FAILED")
        self.assertEqual(self.stop_points() - a_points, 350)
        self.assertEqual(o.score_details["base_brake"] - a_brake, 500)

    @meaning("CONTRACT", "only a POSITIVE speed releases the pending state (any positive value, no threshold); a negative speed never does")
    def test_K03_only_a_positive_speed_releases(self):
        for speed, releases in ((0.0001, True), (1e-9, True), (0.9999, True), (5.0, True), (-0.0001, False), (-1e-9, False), (-0.9999, False)):
            with self.subTest(speed=speed):
                self.rig.close()
                self.setUp()
                self.build(150.0)
                self.stop_at_a_and_switch(150.0)
                self.assertTrue(self.waiting())
                self.step(bve_speed=speed)
                self.assertEqual(self.waiting(), not releases)

    @meaning("CONTRACT", "+0.0 and -0.0 are standing: they do not release")
    def test_K04_zero_and_negative_zero_do_not_release(self):
        self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        self.step(n=3, bve_speed=-0.0)
        self.step(n=3, bve_speed=0.0)
        self.assertTrue(self.waiting())

    @meaning("CONTRACT", "the release is not coupled to leaving A's range or to a distance: 0.5 m of rolling releases")
    def test_K05_release_needs_no_departure_distance(self):
        self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        self.assertTrue(self.waiting())
        self.step(bve_speed=0.2, bve_location=LOC_A + 0.01)
        self.assertFalse(self.waiting())

    @meaning("CONTRACT", "a switch with a positive speed releases in the SAME tick, and the basic-brake state starts from the handle of that tick")
    def test_K06_same_tick_release_starts_from_the_handle_of_the_switch_tick(self):
        o = self.build(150.0)
        self.step(n=3, bve_speed=0.0, bve_location=LOC_A, bve_brk_notch=4)
        self.step(bve_door=1, bve_arr_idx=1, bve_arr_seq=1)
        self.step(bve_door=0)
        o.bb_apply_count, o.bb_release_count, o.bb_state, o.bb_prev_stable_notch = 2, 1, "RELEASING", 4        # stale history of A
        self.step(bve_speed=0.5, bve_brk_notch=2, bve_next_loc=1150.0, bve_tgt_idx=2, bve_next_time=T0 + 300000)
        self.assertFalse(self.waiting())
        self.assertEqual((o.bb_apply_count, o.bb_release_count, o.bb_state), (0, 0, "IDLE"))
        self.assertEqual((o.bb_prev_stable_notch, o.bb_current_notch), (2, 2))

    @meaning("CONTRACT", "at the release after a standing switch the basic-brake state of B is initialised: A's history is gone, the handle of that tick is the start")
    def test_K07_release_initialises_the_basic_brake_state_and_drops_the_history_of_A(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        o.bb_apply_count, o.bb_release_count, o.bb_state, o.bb_prev_stable_notch = 2, 1, "RELEASING", 4        # stale history of A
        self.step(bve_speed=0.5, bve_brk_notch=3)
        self.assertFalse(self.waiting())
        self.assertEqual((o.bb_apply_count, o.bb_release_count, o.bb_state), (0, 0, "IDLE"))
        self.assertEqual((o.bb_prev_stable_notch, o.bb_current_notch), (3, 3))
        self.step(n=25, bve_speed=0.5, bve_brk_notch=0)                     # then a release after the reset counts as ONE release (1 -> 0), no apply
        self.assertEqual((o.bb_apply_count, o.bb_release_count), (0, 1))

    @meaning("CONTRACT", "while pending the handle moves at A are not counted and nothing fails")
    def test_K08_handle_moves_while_standing_are_not_monitored(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        for notch in (0, 3, 0, 5, 0):
            self.step(n=25, bve_brk_notch=notch)
        self.assertEqual((o.bb_apply_count, o.bb_release_count, o.bb_state, o.bb_is_in_zone), (0, 0, "IDLE", False))

    @meaning("CONTRACT", "A re-stop near A AFTER having moved is B's short stop: out of B's range, so B is not scorable (the owner's re-stop rule)")
    def test_K09_re_stop_after_moving_counts_for_B(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        self.step(n=2, bve_speed=0.5, bve_location=LOC_A + 0.2)
        self.assertFalse(o.is_stopped_out_of_range)                         # moving: nothing yet
        self.step(n=2, bve_speed=0.0, bve_location=LOC_A + 0.5)
        self.assertTrue(o.is_stopped_out_of_range)                          # standing again, 150 m short of B

    @meaning("CONTRACT", "a reverse creep does not release (no reset, the pending state stays); the reset comes with the later FORWARD movement")
    def test_K10_reverse_creep_does_not_release(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        self.assertTrue(self.waiting())
        self.step(n=2, bve_speed=-0.0001, bve_location=LOC_A - 0.001)
        self.assertTrue(self.waiting())
        self.assertNotEqual(o.bb_state, "FAILED")                            # the zone of B is not entered while pending, so the reverse rule has nothing to fail
        self.step(n=2, bve_speed=0.0, bve_location=LOC_A - 0.001)
        self.assertTrue(self.waiting())
        self.step(bve_speed=0.5, bve_location=LOC_A + 0.1)
        self.assertFalse(self.waiting())

    @meaning("CONTRACT", "a customer pair 2 m apart (B inside the range at A): the first valid stop of B is not detected at A's standing position")
    def test_K11_co_located_pair_no_first_valid_stop_at_A(self):
        o = self.build(2.0)
        self.stop_at_a_and_switch(2.0, bve_margin_f=5.0, bve_margin_b=5.0)
        self.step(n=5)
        self.assertFalse(getattr(o, "bb_first_valid_stop_detected", False))
        self.assertFalse(o.bb_is_in_zone)

    @meaning("CONTRACT", "an operational stop B 2 m ahead of A: its arrival (latch, scored flag) is not made at A's standing position, and A is not scored a second time")
    def test_K12_operational_B_does_not_arrive_at_the_stop_of_A(self):
        o = self.build(2.0)
        self.stop_at_a_and_switch(2.0, bve_doordir=0)
        a_points = self.stop_points()
        self.step(n=5)
        self.assertEqual(a_points, 350)
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertIsNone(getattr(o, "operational_stop_latch", None))
        self.assertEqual(self.stop_points(), 350)
        # after the train has moved and stands again inside B's range, the arrival is B's
        self.step(n=2, bve_speed=0.4, bve_location=LOC_A + 0.5)
        self.step(n=3, bve_speed=0.0, bve_location=LOC_A + 1.5)
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertIsNotNone(getattr(o, "operational_stop_latch", None))

    @meaning("CONTRACT", "only a FORWARD target switch is evaluated: a backward switch (NEXTLOC decreases) never pends, whatever the anchor says")
    def test_K13_backward_switch_never_pends(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0, bve_next_loc=500.0, bve_tgt_idx=0, bve_next_time=T0 + 300000)
        self.assertFalse(self.waiting())
        self.assertEqual((o.is_stopped_out_of_range, getattr(o, "prev_actual_stop_loc", None)), (False, -1.0))


# ==============================================================================================================================================
# C. THE STATE - defaults, reset sites, the official jump
# ==============================================================================================================================================
class C_State(Base):
    @meaning("CONTRACT", "the construction default and the generation default are 'no gate' (False)")
    def test_S01_defaults_are_no_gate(self):
        import managed_input
        self.assertIs(getattr(self.o, "close_range_departure_reset_pending", "missing"), False)
        self.assertIs(managed_input.generation_defaults().get("close_range_departure_reset_pending", "missing"), False)

    @meaning("CONTRACT", "reset_station_evaluation_state clears the gate (scoring start, Retry and the session discard all call it)")
    def test_S02_reset_station_evaluation_state_clears_the_gate(self):
        self.o.close_range_departure_reset_pending = True
        self.S.reset_station_evaluation_state(self.o)
        self.assertFalse(self.waiting())

    @meaning("CONTRACT", "discard_scoring_session and discard_generation_state clear the gate")
    def test_S03_discards_clear_the_gate(self):
        import managed_input
        self.o.close_range_departure_reset_pending = True
        managed_input.discard_scoring_session(self.o)
        self.assertFalse(self.waiting())
        self.o.close_range_departure_reset_pending = True
        managed_input.discard_generation_state(self.o)
        self.assertFalse(self.waiting())

    @meaning("CONTRACT", "a target switch during an outstanding official jump does not open the gate (the telemetry is the world the jump replaces)")
    def test_S04_switch_during_an_official_jump_does_not_open_the_gate(self):
        o = self.build(150.0)
        self.stop_at_a_and_switch(150.0)
        self.assertTrue(self.waiting())
        self.S.reset_station_evaluation_state(o)
        o.is_official_jumping = True
        self.step(bve_next_loc=6000.0, bve_tgt_idx=3, bve_speed=0.0)
        self.assertFalse(self.waiting())

    @meaning("CONTRACT", "a scoring start and a Retry clear the pending state through reset_station_evaluation_state, and nothing else sets it")
    def test_S05_start_and_retry_clear_the_gate_and_nothing_sets_it_during_their_jump(self):
        import inspect
        self.assertIn("reset_station_evaluation_state(self)", inspect.getsource(self.S.execute_retry))
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            src = f.read()
        start_block = src[src.index("self.is_first_udp = True\n                self.is_first_station = True\n                self.has_departed = False"):]
        self.assertTrue(start_block.startswith("self.is_first_udp = True\n                self.is_first_station = True\n                self.has_departed = False\n                reset_station_evaluation_state(self)"))
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8", newline="") as f:
            sl = f.read().replace("\r\n", "\n")
        self.assertEqual(sl.count("self.close_range_departure_reset_pending = close_pair"), 1)          # the ONE setter: the target switch branch (the evaluation refuses a switch during an official jump)
        self.assertEqual(sl.count("self.close_range_departure_reset_pending = True"), 0)

    @meaning("CONTRACT", "the gate is classified: GENERATION_DEFAULTS and the construction default of the Overlay agree")
    def test_S06_classification(self):
        import managed_input
        self.assertIn("close_range_departure_reset_pending", managed_input.generation_defaults())
        self.assertNotIn("close_range_departure_reset_pending", managed_input.GENERATION_DROP)
        self.assertNotIn("close_range_departure_reset_pending", managed_input.KEPT_ACROSS_GENERATIONS)


# ==============================================================================================================================================
# D. SOURCE SHAPE - the reset is the only new speed comparison, and has_departed is untouched
# ==============================================================================================================================================
class D_SourceShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8", newline="") as f:
            cls.src = f.read().replace("\r\n", "\n")

    @meaning("GUARD", "the has_departed predicate is exactly the H-C one")
    def test_P01_has_departed_predicate_is_unchanged(self):
        self.assertIn("        not getattr(self, 'is_official_jumping', False)\n        and self.bve_speed >= 1.0\n        and getattr(self, 'bve_door', 0) == 0\n", self.src)
        self.assertEqual(self.src.count("self.has_departed = True"), 1)

    @meaning("CONTRACT", "the reset compares the speed with 0.0 as a POSITIVE test only (> 0.0), never with a threshold or the other sign")
    def test_P02_the_reset_uses_positive_zero_test(self):
        m = re.search(r"def update_close_range_departure_reset\(self[^\n]*\):\n(.*?)\n\ndef ", self.src, re.S)
        self.assertIsNotNone(m, "update_close_range_departure_reset is missing")
        body = m.group(1)
        self.assertIn("self.bve_speed > 0.0", body)
        self.assertNotIn("!= 0.0", body)
        self.assertIsNone(re.search(r"abs\(|>= *0\.|> *0\.[1-9]|< *0\.[1-9]|1\.0", body))

    @meaning("CONTRACT", "the pending state is read by the three formation points (zone entry, out-of-range stop, operational arrival) and the reset function, and nowhere else")
    def test_P03_the_gate_is_read_at_the_formation_points(self):
        reads = [m.start() for m in re.finditer(r"close_range_departure_reset_pending", self.src)]
        self.assertGreaterEqual(len(reads), 5)
        self.assertEqual(self.src.count("not getattr(self, 'close_range_departure_reset_pending', False)"), 4)       # 3 formation points + the reset function itself


if __name__ == "__main__":
    unittest.main()
