"""Phase SI-R5.0 Stage 0 - the RED / GUARD fixation of the close-range contract (the Owner's final contract, OD-CR-1 / 5 / 9 / 13 / 14).

NOT a discovery test (the name starts with red_): run it as   python -B tests/red_close_range_contract.py [result.tsv]
Every test carries a kind:
    RED    must FAIL on the product that has no close-range handling (aa03924), and must fail by a CONTRACT assertion (the reason is the missing feature)
    GUARD  must PASS on aa03924 and keep passing after the implementation (non-regression, or a trap that is only live once the feature exists)
Outcome classes the runner prints:
    RED-VALID        RED that failed by a CONTRACT assertion               GUARD-OK       GUARD that passed
    RED-INVALID      RED that passed (not red)                              GUARD-BROKEN   GUARD that failed
    FIXTURE-INVALID  a PREMISE of the scene did not hold (fixture defect)  OLD-EXPECTATION  a plain assertion failed that is not a CONTRACT one
    ERROR            any other exception (import / product error)

THE CONTRACT UNDER TEST (names are the proposed ones; change the two constants below if the Owner names them otherwise):
    PENDING  close_range_departure_reset_pending   False by default; True = the directly adjacent next stop is close and the first POSITIVE movement is awaited
    ANCHOR   prev_actual_stop_loc                  the actual stop position of the previous stop, fixed at the establishment of that stop; -1.0 = none
    close  <=>  bve_next_loc - bve_margin_b - ANCHOR <= setting_stop_distance      (bve_margin_b = abs(Put margin1); margin2 = bve_margin_f is never used; <= includes the boundary)
    the switch is evaluated ONCE, only for a stop -> stop switch (neither the previous nor the new target is a pass station) and only with a valid ANCHOR
    pending and bve_speed > 0.0  ->  basic-braking state AND early-stop state are reset in the SAME tick, pending = False, once per section; speed < 0 / speed == 0 never reset
Nothing here is imported from, or copied out of, the Night A worktree; the scenes follow the same rig (tests/sia_rig.py) as the Night A fixture.
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

PENDING = "close_range_departure_reset_pending"
ANCHOR = "prev_actual_stop_loc"
ANCHOR_NONE = -1.0
T0 = 36000000
ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
_TMP = {}


class PremiseBroken(Exception):
    """A premise of the scene did not hold: the fixture, not the contract, is at fault."""


def premise(cond, why):
    if not cond:
        raise PremiseBroken(why)


def contract(cond, why):
    if not cond:
        raise AssertionError("CONTRACT: " + why)


def case(kind, req, group="CORE", note=""):
    assert kind in ("RED", "GUARD")

    def deco(fn):
        fn.rc = {"kind": kind, "req": req, "group": group, "note": note}
        return fn
    return deco


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-close-range-red-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP["dir"].name)
    finally:
        for k, v in _TMP["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP["dir"].cleanup()
    if left:
        raise AssertionError("the module wrote into the redirected profile: %r" % (left,))


def read_src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------------------------------------------------------------------------------
def sta(R, name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False), is_pass=kw.pop("is_pass", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["close-range-red"])
        import main
        import scoring_logic
        import sia_rig
        cls.main, cls.S, cls.R = main, scoring_logic, sia_rig

    def setUp(self):
        self.rig = self.R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0

    # -- stations -----------------------------------------------------------------------------------------------------------------------------------
    def st(self, *spec):
        R = self.R
        return [sta(R, n, l, **k) for (n, l, k) in spec]

    def adj(self, c=1150.0):
        return self.st(("S", 0.0, {}), ("A", 1000.0, {}), ("C", c, {}), ("T", 6000.0, {"terminal": True}))

    # -- the scene ----------------------------------------------------------------------------------------------------------------------------------
    def build(self, sl, end_idx, rng=300.0):
        o, R = self.o, self.R
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = sl
        o.setting_end_idx = end_idx
        o.setting_stop_distance = rng
        s0, a = sl[0], sl[1]
        o.save_data = [{"loc": s0["location"], "time_ms": T0, "score": 0, "target_loc": s0["location"], "station_name": s0["name"], "stop_error": 0.0,
                        "score_details": dict(ZERO), "station_index": 0, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, len(sl)), "station_location": s0["location"],
                        "role": "scoring_start"}]
        o.bve_next_loc = o.prev_next_loc = a["location"]
        o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq = 1, 0, 0
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

    # -- flows ----------------------------------------------------------------------------------------------------------------------------------------
    def arrive_a(self, a_pos=999.5, mark=1000.0, operational=False, arr_idx=1, door=True):
        """The train brakes into A and stops at a_pos. Normal stop: the doors open (the arrival) and close. Operational stop: the arrival is the stop itself."""
        o = self.o
        extra = {"bve_doordir": 0} if operational else {}
        self.step(bve_speed=5.0, bve_location=mark - 100.0, bve_brk_notch=3, **extra)
        self.step(bve_speed=2.0, bve_location=mark - 10.0, bve_brk_notch=3)
        # an operational stop is the arrival itself: the sender names the arrival of A on the tick on which the stop is made (a normal stop names it at the door opening)
        stop_fields = {"bve_arr_idx": arr_idx, "bve_arr_seq": 1} if operational else {}
        self.step(n=3, bve_speed=0.0, bve_location=a_pos, bve_brk_notch=4, **stop_fields)
        if operational:
            premise(o.has_scored_stop_this_station and getattr(o, "operational_stop_latch", None) is not None, "the operational stop of A was not established")
            return
        if door:
            self.step(bve_door=1, bve_arr_idx=arr_idx, bve_arr_seq=1)
            self.step(n=3)
            self.step(bve_door=0)

    def switch(self, c_loc=1150.0, tgt=2, mb=5.0, mf=5.0, is_pass=0, settle=4, **more):
        fields = dict(bve_next_loc=c_loc, bve_tgt_idx=tgt, bve_margin_b=mb, bve_margin_f=mf, bve_is_pass=is_pass, bve_next_time=T0 + 300000)
        fields.update(more)
        self.step(**fields)
        if settle:
            self.step(n=settle)

    def pending(self):
        return bool(getattr(self.o, PENDING, False))

    def anchor(self):
        return getattr(self.o, ANCHOR, None)

    def inject_stale(self):
        o = self.o
        o.bb_apply_count, o.bb_release_count, o.bb_state = 2, 1, "RELEASING"
        o.bb_prev_stable_notch = o.bb_current_notch = 4
        o.is_stopped_out_of_range = True

    def stale_present(self):
        o = self.o
        return (o.bb_apply_count, o.bb_release_count) == (2, 1) and o.is_stopped_out_of_range

    def stale_gone(self):
        o = self.o
        return (o.bb_apply_count, o.bb_release_count, o.bb_state) == (0, 0, "IDLE") and not o.is_stopped_out_of_range

    def close_scene(self, rng=300.0, a_pos=999.5, mb=5.0, mf=5.0, operational=False, arr_idx=1, c=1150.0, settle=4):
        o = self.build(self.adj(c), 3, rng)
        self.arrive_a(a_pos=a_pos, operational=operational, arr_idx=arr_idx)
        self.anchor_at_a = self.anchor()                                    # as fixed by the establishment of A, BEFORE the switch (the switch may consume it)
        if operational:
            self.switch(c, mb=mb, mf=mf, settle=0, bve_speed=0.0)      # the sender switches only on a movement; a test passes the movement itself in a later step
        else:
            self.switch(c, mb=mb, mf=mf, settle=settle)
        premise(o.bve_next_loc == c and o.bve_tgt_idx == 2, "the target did not switch to C")
        return o

    def depart_and_arrive_c(self, a_pos=999.5, c_mark=1150.0, c_idx=2):
        self.step(n=25, bve_brk_notch=0, bve_speed=0.5, bve_location=a_pos + 0.1)
        self.step(n=3, bve_speed=20.0, bve_location=a_pos + 40.0)
        self.step(n=3, bve_speed=40.0, bve_location=a_pos + 60.0)
        self.step(n=25, bve_brk_notch=3, bve_speed=20.0, bve_location=c_mark - 60.0)
        self.step(n=25, bve_brk_notch=2, bve_speed=8.0, bve_location=c_mark - 20.0)
        self.step(n=3, bve_brk_notch=1, bve_speed=0.0, bve_location=c_mark - 0.3)
        self.step(bve_door=1, bve_arr_idx=c_idx, bve_arr_seq=2)


# ===================================================================================================================================================
# A. THE CLOSE-RANGE DECISION (1-9, 25, 26, 27 of the Owner's list): one evaluation at the stop -> stop switch
# ===================================================================================================================================================
class A_Decision(Base):
    # geometry: C mark 1150, margin1 = 5 (bve_margin_b = 5): near edge 1145; anchor 999.5 -> distance 145.5
    @case("GUARD", "R01 distance > range: conventional logic, no pending, no reset at the first positive movement")
    def test_R01_distance_greater_than_range_is_conventional(self):
        o = self.close_scene(rng=145.25)                                   # 145.5 > 145.25
        self.assertFalse(self.pending())
        self.inject_stale()
        self.step(n=3, bve_speed=0.5, bve_location=999.6, bve_brk_notch=4)
        premise(o.bve_speed > 0.0, "the train does not move")
        self.assertFalse(self.pending())
        self.assertTrue(self.stale_present(), "a switch that is not close must not reset anything at the first movement")

    @case("RED", "R02 distance == range: close (the boundary is included, <=)")
    def test_R02_distance_equal_to_range_is_close(self):
        self.close_scene(rng=145.5)                                        # 145.5 == 145.5 (exact in binary)
        contract(self.pending(), "pending must be True at the boundary")

    @case("RED", "R03 distance < range: close")
    def test_R03_distance_less_than_range_is_close(self):
        self.close_scene(rng=145.75)
        contract(self.pending(), "pending must be True inside the range")

    @case("RED", "R04 margin1 / margin2 asymmetric: only margin1 (bve_margin_b) moves the near edge")
    def test_R04_asymmetric_margins(self):
        o = self.close_scene(rng=145.5, mb=2.0, mf=9.0)                    # near edge 1148 -> 148.5 > 145.5 : not close
        self.assertFalse(self.pending())
        self.rig.close()
        self.setUp()
        self.close_scene(rng=145.5, mb=9.0, mf=2.0)                        # near edge 1141 -> 141.5 <= 145.5 : close
        contract(self.pending(), "margin1 = 9 (bve_margin_b) must bring the near edge inside the range")

    @case("RED", "R05 margin2 (bve_margin_f) is not used by the close-range expression")
    def test_R05_margin2_not_used(self):
        for mf in (0.0, 5.0, 100.0):
            with self.subTest(margin_f=mf):
                self.rig.close()
                self.setUp()
                self.close_scene(rng=145.5, mb=5.0, mf=mf)
                contract(self.pending(), "the decision at the boundary must not depend on margin2 (mf=%r)" % mf)

    @case("RED", "R06 previous stop SHORT of the mark (inside the range): its own position is the anchor")
    def test_R06_previous_stop_short(self):
        o = self.close_scene(rng=145.5, a_pos=996.0)                       # anchor 996.0 -> 149.0 > 145.5 : not close, but the anchor is recorded
        contract(self.anchor_at_a == 996.0, "the anchor must be the actual stop position 996.0, got %r" % (self.anchor_at_a,))
        self.assertFalse(self.pending())

    @case("RED", "R07 previous stop ON the mark")
    def test_R07_previous_stop_on_the_mark(self):
        self.close_scene(rng=145.5, a_pos=1000.0)                          # 145.0 <= 145.5
        contract(self.anchor_at_a == 1000.0, "the anchor must be 1000.0, got %r" % (self.anchor_at_a,))
        contract(self.pending(), "145.0 <= 145.5 is close")

    @case("RED", "R08 previous stop OVERRUN (inside margin2)")
    def test_R08_previous_stop_overrun(self):
        self.close_scene(rng=145.5, a_pos=1002.0)                          # 143.0 <= 145.5
        contract(self.anchor_at_a == 1002.0, "the anchor must be 1002.0, got %r" % (self.anchor_at_a,))
        contract(self.pending(), "143.0 <= 145.5 is close")

    @case("RED", "R09 the HUD / official target values are not product inputs: a different official target changes nothing")
    def test_R09_hud_and_official_values_are_not_used(self):
        o = self.build(self.adj(), 3, 145.5)
        o.official_state, o.official_index, o.official_location, o.official_margin_b, o.official_margin_f = "KNOWN", 2, 1400.0, 1.0, 1.0
        self.arrive_a()
        self.switch()
        contract(self.pending(), "the decision must come from the machine target (NEXTLOC 1150, margin_b 5), not from the official / HUD values")

    @case("GUARD", "R25 no anchor (A was not a valid stop: 8 m short, doors open, no arrival) -> no close-range handling, no distance / history estimate")
    def test_R25_anchor_missing_no_processing(self):
        o = self.build(self.adj(), 3, 300.0)
        self.step(bve_speed=5.0, bve_location=900.0, bve_brk_notch=3)
        self.step(bve_speed=2.0, bve_location=985.0, bve_brk_notch=3)
        self.step(n=3, bve_speed=0.0, bve_location=992.0, bve_brk_notch=4)
        self.step(bve_door=1, bve_arr_idx=1, bve_arr_seq=1)
        premise(not o.has_scored_stop_this_station and len(o.save_data) == 1, "A must NOT be established (8 m short of a 5 m margin)")
        self.step(n=3)
        self.step(bve_door=0)
        self.switch()
        self.assertFalse(self.pending())
        self.assertIn(self.anchor(), (None, ANCHOR_NONE))

    @case("GUARD", "R26 identity not verified at A's arrival -> no anchor -> no close-range handling")
    def test_R26_identity_not_verified_no_processing(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a(arr_idx=-1)
        premise(len(o.save_data) == 1, "with an unverified arrival identity no checkpoint is created (the fixture has to produce that)")
        self.switch()
        self.assertFalse(self.pending())
        self.assertIn(self.anchor(), (None, ANCHOR_NONE))

    @case("GUARD", "R27 terminal: the arrival at the end station finishes the scoring, no pending and no anchor survive")
    def test_R27_terminal(self):
        sl = self.st(("S", 0.0, {}), ("A", 1000.0, {}), ("C", 1150.0, {"terminal": True}))
        o = self.build(sl, 2, 300.0)
        self.arrive_a()
        self.switch()
        self.depart_and_arrive_c()
        premise(o.is_scoring_finished, "the arrival at the end station must finish the scoring")
        self.assertFalse(self.pending())
        self.assertIn(self.anchor(), (None, ANCHOR_NONE), "no section follows the end station: no anchor is kept for it")

    @case("GUARD", "R27b the anchor of an earlier stop is never used for a later pair (S, A, C all inside the range; A is NOT established: 8 m short)")
    def test_R27b_stale_anchor_not_used(self):
        sl = self.st(("S0", 0.0, {}), ("S", 850.0, {}), ("A", 1000.0, {}), ("C", 1150.0, {}), ("T", 6000.0, {"terminal": True}))
        o = self.build(sl, 4, 400.0)
        self.arrive_a(a_pos=849.5, mark=850.0, arr_idx=1)                  # S is established (anchor 849.5)
        self.switch(c_loc=1000.0, tgt=2, settle=2)                         # S -> A
        self.step(n=3, bve_speed=0.5, bve_location=849.6)                  # departs
        self.step(bve_speed=2.0, bve_location=985.0, bve_brk_notch=3)
        self.step(n=3, bve_speed=0.0, bve_location=992.0, bve_brk_notch=4)
        self.step(bve_door=1, bve_arr_idx=2, bve_arr_seq=2)                # doors open 8 m short of A: not an arrival
        premise(not o.has_scored_stop_this_station, "A must NOT be established (8 m short of a 5 m margin)")
        self.step(n=3)
        self.step(bve_door=0)
        self.switch(c_loc=1150.0, tgt=3)                                   # A -> C : 1145 - 849.5 = 295.5 <= 400, but 849.5 is S's stop
        self.assertFalse(self.pending(), "S's stop position must not be taken for A's")

    @case("RED", "R10a anchor is fixed at the establishment of the previous stop (normal stop)")
    def test_R10a_anchor_set_at_normal_stop(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a()
        contract(self.anchor() == 999.5, "anchor must be 999.5 after A's doors closed, got %r" % (self.anchor(),))

    @case("RED", "R10b anchor is fixed at the establishment of the previous stop (operational stop)")
    def test_R10b_anchor_set_at_operational_stop(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a(operational=True)
        contract(self.anchor() == 999.5, "anchor must be 999.5 at the operational stop, got %r" % (self.anchor(),))


# ===================================================================================================================================================
# B. THE DEPARTURE RESET (10-21): stopping / switching / reversing never reset, the first positive movement resets once
# ===================================================================================================================================================
class B_Departure(Base):
    @case("RED", "R11 standing at A (many ticks, handle constant): pending stays True and nothing is reset")
    def test_R11_standing_does_not_reset(self):
        o = self.close_scene()
        contract(self.pending(), "pending must be True while the train stands after the switch")
        self.inject_stale()
        self.step(n=40)
        contract(self.pending() and self.stale_present(), "standing must neither clear pending nor reset")

    @case("RED", "R12 the target switch alone does not reset (pending is already True on the switch tick and the tick after)")
    def test_R12_switch_alone_does_not_reset(self):
        o = self.close_scene(settle=0)
        contract(self.pending(), "pending must be True on the switch tick")
        self.step()
        contract(self.pending(), "pending must be True one tick later")

    @case("RED", "R13 reverse start (speed < 0) does not reset and keeps pending")
    def test_R13_reverse_start(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.inject_stale()
        self.step(bve_speed=-0.0001, bve_location=999.499)
        contract(self.pending() and self.stale_present(), "a reverse movement must not release the pending state nor reset")

    @case("RED", "R14 reversing (many ticks) does not reset")
    def test_R14_reversing(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.inject_stale()
        self.step(n=15, bve_speed=-0.5, bve_location=999.0)
        contract(self.pending() and self.stale_present(), "reversing must not reset")

    @case("RED", "R15 stop after reversing does not reset")
    def test_R15_stop_after_reverse(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.inject_stale()
        self.step(n=5, bve_speed=-0.5, bve_location=999.0)
        self.step(n=10, bve_speed=0.0)
        contract(self.pending() and self.stale_present(), "a stop after reversing must not reset")

    @case("RED", "R16 forward movement after a reverse: reset exactly then")
    def test_R16_forward_after_reverse(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.inject_stale()
        self.step(n=3, bve_speed=-0.3, bve_location=999.0)
        self.step(n=3, bve_speed=0.0)
        contract(self.pending() and self.stale_present(), "no reset before the forward movement")
        self.step(bve_speed=0.3, bve_location=999.1)
        contract((not self.pending()) and self.stale_gone(), "the first positive speed must reset and release pending")

    @case("RED", "R16b reverse straight to forward (no exact 0.0 sample, zero CROSSING): the reset tick does not flag an early stop from the crossing")
    def test_R16b_zero_crossing_on_the_reset_tick(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.step(n=3, bve_speed=-0.3, bve_location=999.0)
        self.step(bve_speed=0.3, bve_location=999.1)                        # prev_stop_detection_speed -0.3 -> +0.3 : crossed_zero would be a stop detection
        contract(not self.pending(), "the positive tick resets")
        contract(not o.is_stopped_out_of_range, "the crossing of the reset tick is the start of the movement, not a stop of C 150 m short")

    @case("RED", "R17 forward movement from the start: reset at the first positive speed")
    def test_R17_forward_from_start(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.inject_stale()
        self.step(bve_speed=0.5, bve_location=999.6)
        contract((not self.pending()) and self.stale_gone(), "reset expected on the first positive tick")

    @case("RED", "R18 basic braking AND early stop are reset in the SAME tick (all eleven basic-braking variables return to the new-section state)")
    def test_R18_same_tick_complete_reset(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        o.bb_state, o.bb_apply_count, o.bb_release_count, o.bb_evaluated = "FAILED", 3, 2, True
        o.bb_current_notch, o.bb_prev_stable_notch, o.bb_notch_change_time, o.bb_is_stable = 7, 7, -5.0, False
        o.bb_first_valid_stop_detected, o.bb_moved_after_first_valid_stop = True, True
        o.is_stopped_out_of_range = True
        o.bve_brk_notch = 2
        self.step(bve_speed=0.5, bve_location=999.6)
        self.assertTrue(o.bb_is_in_zone, "the zone of C stays entered")
        contract((o.bb_state, o.bb_apply_count, o.bb_release_count, o.bb_evaluated) == ("IDLE", 0, 0, False), "state / counts / evaluated")
        contract((o.bb_current_notch, o.bb_prev_stable_notch, o.bb_is_stable) == (2, 2, True), "the new start is the handle of THIS tick")
        contract(abs(o.bb_notch_change_time - self.t) < 1e-9, "the notch timer restarts at this tick")
        contract((o.bb_first_valid_stop_detected, o.bb_moved_after_first_valid_stop, o.is_stopped_out_of_range) == (False, False, False), "first-valid-stop / moved / early stop")

    @case("RED", "R19 once per section: positive movement over many ticks does not reset again")
    def test_R19_many_positive_ticks(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.step(bve_speed=0.5, bve_location=999.6)
        self.inject_stale()
        self.step(n=40, bve_speed=2.0, bve_location=1005.0)
        contract(self.stale_present() and not self.pending(), "no reset on later positive ticks")

    @case("RED", "R20 stop and restart in the same section: no second reset")
    def test_R20_stop_and_restart(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.step(bve_speed=0.5, bve_location=999.6)
        self.step(n=3, bve_speed=0.0)
        self.inject_stale()
        self.step(n=3, bve_speed=-0.2, bve_location=999.5)
        self.step(n=3, bve_speed=0.0)
        self.step(n=3, bve_speed=0.4, bve_location=999.7)
        contract(self.stale_present() and not self.pending(), "a stop, a reverse and a restart after the reset must not reset again")

    @case("RED", "R21 next section: a new stop and a new switch are evaluated again")
    def test_R21_next_section(self):
        sl = self.st(("S", 0.0, {}), ("A", 1000.0, {}), ("C", 1150.0, {}), ("D", 1300.0, {}), ("T", 6000.0, {"terminal": True}))
        o = self.build(sl, 4, 300.0)
        self.arrive_a()
        self.switch()
        contract(self.pending(), "first section: pending")
        self.depart_and_arrive_c()
        self.step(n=3)
        self.step(bve_door=0)
        premise(not o.is_scoring_finished, "C is not the end station")
        anchor_at_c = self.anchor()                                        # as fixed by the establishment of C, BEFORE the switch (the switch may consume it)
        self.switch(c_loc=1300.0, tgt=3)
        contract(anchor_at_c is not None and abs(anchor_at_c - 1149.7) < 1e-9 and self.pending(),
                 "second section: anchor = C's stop (1149.7), pending True; got anchor %r pending %r" % (anchor_at_c, self.pending()))

    @case("RED", "R22 the anchor is not overwritten by later movement / stops / reverse of the same section (kept as A's, or consumed; never a later position)")
    def test_R22_anchor_not_overwritten(self):
        o = self.close_scene()
        contract(self.anchor_at_a == 999.5, "premise of the contract: the anchor of A, got %r" % (self.anchor_at_a,))
        for speed, loc in ((-0.4, 999.0), (0.0, 999.0), (0.5, 999.4), (0.0, 1010.0), (3.0, 1030.0), (0.0, 1031.0)):
            self.step(n=3, bve_speed=speed, bve_location=loc)
            self.assertIn(self.anchor(), (999.5, ANCHOR_NONE), "the anchor took a later position at speed %r" % (speed,))

    @case("RED", "R28 operational stop at A: the sender switches on a NEGATIVE first movement -> pending, no reset")
    def test_R28_operational_negative_first_movement(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a(operational=True)
        self.switch(settle=0, bve_speed=-0.3, bve_location=999.4)
        contract(self.pending(), "a reverse first movement must wait: pending True at the switch")
        self.inject_stale()
        self.step(n=3, bve_speed=-0.3, bve_location=999.3)
        contract(self.pending() and self.stale_present(), "the reverse movement must not reset")
        self.step(n=3, bve_speed=0.3, bve_location=999.6)
        contract((not self.pending()) and self.stale_gone(), "the forward movement then resets")

    @case("GUARD", "R29 operational stop at A, first movement positive: nothing stays pending, no early-stop flag left")
    def test_R29_operational_positive_first_movement(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a(operational=True)
        self.switch(settle=0, bve_speed=0.3, bve_location=999.6)
        self.step(n=2)
        self.assertFalse(self.pending())
        self.assertFalse(o.is_stopped_out_of_range)

    @case("RED", "R30 a switch during an outstanding official jump never opens the pending state")
    def test_R30_official_jump_never_pends(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a()
        contract(self.anchor() == 999.5, "premise of the contract: the anchor exists")
        o.is_official_jumping = True
        self.switch()
        self.assertFalse(self.pending())


# ===================================================================================================================================================
# C. PASS STATION BETWEEN (22-24): Case 2, no special handling; the trap is live once an anchor exists
# ===================================================================================================================================================
class C_PassBetween(Base):
    def run_pass(self, passes, c_loc):
        sl = self.st(("S", 0.0, {}), ("A", 1000.0, {}), *[("P%d" % i, p, {"is_pass": True}) for i, p in enumerate(passes)], ("C", c_loc, {}), ("T", 6000.0, {"terminal": True}))
        o = self.build(sl, len(sl) - 1, 300.0)                              # range 300: A -> C is inside it, so a misfire at B -> C WOULD be live
        self.arrive_a()
        idx = 2
        seen = [self.pending()]
        for p in passes:
            self.switch(c_loc=p, tgt=idx, is_pass=1, mb=5.0, mf=5.0, settle=2)
            seen.append(self.pending())
            self.step(n=25, bve_speed=0.5, bve_location=999.9, bve_brk_notch=0) if idx == 2 else None
            self.step(n=3, bve_speed=30.0, bve_location=p - 10.0)
            idx += 1
        self.switch(c_loc=c_loc, tgt=idx, is_pass=0, settle=0, bve_speed=30.0, bve_location=passes[-1] + 0.5)
        seen.append(self.pending())
        self.step(n=2)
        seen.append(self.pending())
        return o, seen, idx

    @case("GUARD", "R31 one pass station between: no pending at any time (the anchor of A is not used at B -> C); C scores normally")
    def test_R31_one_pass_between(self):
        o, seen, idx = self.run_pass([1100.0], 1250.0)
        self.assertFalse(any(seen), "pending seen: %r" % (seen,))
        self.assertFalse(o.is_stopped_out_of_range, "B -> C initialises the early-stop state")
        self.step(n=25, bve_brk_notch=3, bve_speed=20.0, bve_location=1190.0)
        self.step(n=25, bve_brk_notch=2, bve_speed=8.0, bve_location=1230.0)
        self.step(n=3, bve_brk_notch=1, bve_speed=0.0, bve_location=1249.7)
        self.step(bve_door=1, bve_arr_idx=idx, bve_arr_seq=2)
        self.assertEqual(o.score_details["stop"] - 250, 350, "C's stop (0.3 m short) after A's 250")
        self.assertEqual(o.score_details["base_brake"], 500)

    @case("GUARD", "R32 two pass stations between: no pending at any time")
    def test_R32_two_pass_between(self):
        o, seen, idx = self.run_pass([1090.0, 1180.0], 1270.0)
        self.assertFalse(any(seen), "pending seen: %r" % (seen,))
        self.assertFalse(o.is_stopped_out_of_range)

    @case("GUARD", "R33 B -> C keeps the existing initialisation: stale values injected before the switch are gone after it")
    def test_R33_existing_initialisation_kept(self):
        sl = self.st(("S", 0.0, {}), ("A", 1000.0, {}), ("B", 1100.0, {"is_pass": True}), ("C", 1250.0, {}), ("T", 6000.0, {"terminal": True}))
        o = self.build(sl, 4, 300.0)
        self.arrive_a()
        self.switch(c_loc=1100.0, tgt=2, is_pass=1, settle=2)
        self.step(n=3, bve_speed=30.0, bve_location=1090.0)
        self.inject_stale()
        self.switch(c_loc=1250.0, tgt=3, is_pass=0, settle=3, bve_speed=30.0, bve_location=1100.5)
        self.assertTrue(self.stale_gone(), "bb %r/%r %r oor %r" % (o.bb_apply_count, o.bb_release_count, o.bb_state, o.is_stopped_out_of_range))


# ===================================================================================================================================================
# D. WHAT THE DEPARTURE RESET MAY AND MAY NOT TOUCH (reset-semantics)
# ===================================================================================================================================================
class D_ResetSemantics(Base):
    PRESERVED = ("score", "score_details", "station_list", "save_data", "bve_next_loc", "bve_tgt_idx", "bve_arr_idx", "prev_next_loc", "has_departed", "is_first_station",
                 "brake_rules", "total_retry_count", "setting_stop_distance", "setting_end_idx", "popups", "bb_state", "bb_apply_count", "bb_release_count", "bb_evaluated",
                 "bb_is_in_zone", "is_scoring_mode", "is_scoring_finished", "jump_lock")
    CLEARED = ("is_approaching", "is_stopped_out_of_range", "has_scored_time_this_station", "has_scored_stop_this_station", "operational_stop_margins", "operational_stop_latch",
               "bb_first_valid_stop_detected", "bb_moved_after_first_valid_stop")

    @case("GUARD", "R40 reset_station_evaluation_state clears exactly the station-evaluation state and not the identity / target / score / history")
    def test_R40_helper_does_not_erase_unneeded_state(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a()
        o.bb_state, o.bb_apply_count, o.bb_release_count, o.bb_evaluated, o.bb_is_in_zone = "RELEASING", 1, 1, True, True
        o.is_approaching = o.is_stopped_out_of_range = o.has_scored_time_this_station = o.has_scored_stop_this_station = True
        o.operational_stop_margins, o.operational_stop_latch = (5.0, 5.0), (1, 1, 1)
        o.bb_first_valid_stop_detected = o.bb_moved_after_first_valid_stop = True
        before = {n: repr(getattr(o, n)) for n in self.PRESERVED}
        self.S.reset_station_evaluation_state(o)
        for n in self.PRESERVED:
            self.assertEqual(repr(getattr(o, n)), before[n], "%s was touched by reset_station_evaluation_state" % n)
        self.assertEqual([bool(getattr(o, n, None)) for n in self.CLEARED], [False] * len(self.CLEARED))

    @case("RED", "R41 the helper (and so scoring start / Retry / session discard / every switch) also clears pending and the anchor")
    def test_R41_helper_clears_pending_and_anchor(self):
        o = self.build(self.adj(), 3, 300.0)
        setattr(o, PENDING, True)
        setattr(o, ANCHOR, 999.5)
        self.S.reset_station_evaluation_state(o)
        contract(getattr(o, PENDING, None) is False and getattr(o, ANCHOR, None) == ANCHOR_NONE, "pending %r anchor %r" % (getattr(o, PENDING, None), getattr(o, ANCHOR, None)))


# ===================================================================================================================================================
# E. LIFECYCLE: F5 / Retry / checkpoint / generation (28-31) and the state classification
# ===================================================================================================================================================
class E_Lifecycle(Base):
    def dirty(self):
        o = self.build(self.adj(), 3, 300.0)
        setattr(o, PENDING, True)
        setattr(o, ANCHOR, 999.5)
        return o

    def clean(self, o):
        return getattr(o, PENDING, None) is False and getattr(o, ANCHOR, None) == ANCHOR_NONE

    @case("RED", "R50 F5 / scoring session end (discard_scoring_session) leaves neither pending nor anchor")
    def test_R50_f5_session_discard(self):
        import managed_input
        o = self.dirty()
        managed_input.discard_scoring_session(o)
        contract(self.clean(o), "pending %r anchor %r" % (getattr(o, PENDING, None), getattr(o, ANCHOR, None)))

    @case("RED", "R51 Retry leaves neither (execute_retry goes through reset_station_evaluation_state)")
    def test_R51_retry(self):
        import inspect
        self.assertIn("reset_station_evaluation_state(self)", inspect.getsource(self.S.execute_retry))         # the existing clear point (premise of the design)
        o = self.dirty()
        self.S.reset_station_evaluation_state(o)
        contract(self.clean(o), "the clear point of Retry does not know pending / anchor")

    @case("GUARD", "R52 a checkpoint neither stores nor supplies the anchor (OD-CR-1: no checkpoint reuse)")
    def test_R52_checkpoint_not_used(self):
        src = read_src("scoring_logic.py")
        m = re.search(r"def create_save_data\(.*?\n(?=def )", src, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn(ANCHOR, m.group(0))
        for line in src.split("\n"):
            if ANCHOR in line:
                self.assertNotIn("save_data", line, "the anchor must not be read from / written to save_data: " + line.strip())

    @case("RED", "R53 generation change leaves neither (generation_defaults carry both, discard_generation_state applies them)")
    def test_R53_generation(self):
        import managed_input
        o = self.dirty()
        managed_input.discard_generation_state(o)
        contract(self.clean(o), "pending %r anchor %r" % (getattr(o, PENDING, None), getattr(o, ANCHOR, None)))

    @case("RED", "R54 classification: constructed defaults == generation defaults, neither dropped nor kept across generations")
    def test_R54_classification(self):
        import managed_input
        d = managed_input.generation_defaults()
        contract(PENDING in d and ANCHOR in d, "both must be in generation_defaults()")
        self.assertNotIn(PENDING, managed_input.GENERATION_DROP | managed_input.KEPT_ACROSS_GENERATIONS)
        self.assertNotIn(ANCHOR, managed_input.GENERATION_DROP | managed_input.KEPT_ACROSS_GENERATIONS)
        self.assertEqual((getattr(self.o, PENDING, "missing"), getattr(self.o, ANCHOR, "missing")), (d[PENDING], d[ANCHOR]))
        self.assertEqual((d[PENDING], d[ANCHOR]), (False, ANCHOR_NONE))

    @case("RED", "R55 scoring off (is_scoring_mode False): nothing is armed outside a scoring session")
    def test_R55_not_scoring(self):
        o = self.build(self.adj(), 3, 300.0)
        self.arrive_a()
        contract(self.anchor() == 999.5, "premise of the contract: the anchor exists while scoring")
        o.is_scoring_mode = False
        self.switch()
        self.assertFalse(self.pending())


# ===================================================================================================================================================
# F. END TO END and the re-expressed Night A contracts (K02 / K09 / K11 / K12 / G01 / P01)
# ===================================================================================================================================================
class F_EndToEnd(Base):
    @case("RED", "R60 (K02) adjacent close pair end to end: the release at A is not C's; C scores stop and basic brake")
    def test_R60_close_pair_end_to_end(self):
        o = self.close_scene()
        a_stop, a_brake = o.score_details["stop"], o.score_details["base_brake"]
        self.depart_and_arrive_c()
        contract(o.bb_state != "FAILED", "basic braking of C must not be FAILED (bb_state %r)" % (o.bb_state,))
        contract(o.score_details["stop"] - a_stop == 350, "C's stop points: %r" % (o.score_details["stop"] - a_stop,))
        contract(o.score_details["base_brake"] - a_brake == 500, "C's basic brake points: %r" % (o.score_details["base_brake"] - a_brake,))

    @case("GUARD", "R61 (G01) a far pair scores normally (no pending, +350 / +500)")
    def test_R61_far_pair(self):
        o = self.build(self.adj(c=4000.0), 3, 300.0)
        self.arrive_a()
        self.switch(c_loc=4000.0)
        self.assertFalse(self.pending())
        a_stop, a_brake = o.score_details["stop"], o.score_details["base_brake"]
        self.step(n=25, bve_brk_notch=0, bve_speed=0.5, bve_location=999.6)
        self.step(n=3, bve_speed=40.0, bve_location=1500.0)
        self.step(n=25, bve_brk_notch=3, bve_speed=20.0, bve_location=3940.0)
        self.step(n=25, bve_brk_notch=2, bve_speed=8.0, bve_location=3980.0)
        self.step(n=3, bve_brk_notch=1, bve_speed=0.0, bve_location=3999.7)
        self.step(bve_door=1, bve_arr_idx=2, bve_arr_seq=2)
        self.assertEqual(o.score_details["stop"] - a_stop, 350)
        self.assertEqual(o.score_details["base_brake"] - a_brake, 500)

    @case("RED", "R62 (K09) after the positive departure a stop near A is C's short stop, out of C's range")
    def test_R62_restop_after_departure(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        self.step(n=2, bve_speed=0.5, bve_location=999.7)
        self.assertFalse(o.is_stopped_out_of_range)
        self.step(n=2, bve_speed=0.0, bve_location=1000.0)
        self.assertTrue(o.is_stopped_out_of_range)

    @case("RED", "R63 (K11 / OD-CR-7) co-located pair, 2 m apart: no first valid stop of C at A's standing position", group="OD7-GATING")
    def test_R63_colocated_pair(self):
        o = self.close_scene(c=1002.0)
        contract(self.pending(), "premise of the contract: pending")
        self.step(n=5)
        contract(not getattr(o, "bb_first_valid_stop_detected", False), "C's first valid stop must not be detected at A's standing position")

    @case("RED", "R64 (K12 / OD-CR-7) operational C 2 m ahead of A: its arrival is not made at A's standing position", group="OD7-GATING")
    def test_R64_operational_c_not_arrived_at_a(self):
        o = self.build(self.adj(c=1002.0), 3, 300.0)
        self.arrive_a()
        a_points = o.score_details["stop"]
        self.switch(c_loc=1002.0, bve_doordir=0)
        self.step(n=5)
        contract(o.score_details["stop"] == a_points and not o.has_scored_stop_this_station and getattr(o, "operational_stop_latch", None) is None,
                 "C's arrival must not be made at A's standing position (stop points %r -> %r)" % (a_points, o.score_details["stop"]))

    @case("RED", "R65 (K01 / OD-CR-7) while pending no early-stop verdict of C is formed at A's standing position", group="OD7-GATING")
    def test_R65_no_verdict_while_pending(self):
        o = self.close_scene()
        contract(self.pending() and not o.is_stopped_out_of_range, "pending must hold and C's early-stop verdict must not be formed while standing at A (oor %r)" % (o.is_stopped_out_of_range,))

    @case("RED", "R66 (K08 / OD-CR-7) handle moves while pending are not counted for C", group="OD7-GATING")
    def test_R66_handle_moves_not_counted_while_pending(self):
        o = self.close_scene()
        contract(self.pending(), "premise of the contract: pending")
        for notch in (0, 3, 0, 5, 0):
            self.step(n=25, bve_brk_notch=notch)
        contract((o.bb_apply_count, o.bb_release_count, o.bb_state) == (0, 0, "IDLE"), "counts %r/%r %r" % (o.bb_apply_count, o.bb_release_count, o.bb_state))

    @case("GUARD", "R67 (P01) has_departed is not touched by a target switch and is not the departure predicate (forward, doors closed, >= 1.0 km/h, not jumping)")
    def test_R67_has_departed_unchanged(self):
        src = read_src("scoring_logic.py")
        self.assertIn("        not getattr(self, 'is_official_jumping', False)\n        and self.bve_speed >= 1.0\n        and getattr(self, 'bve_door', 0) == 0\n", src)
        self.assertEqual(src.count("self.has_departed = True"), 1)


# ===================================================================================================================================================
# G. STATIC GUARDS (9, 32-36 and the shape of the implementation)
# ===================================================================================================================================================
class G_Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sl = read_src("scoring_logic.py")
        cls.mi = read_src("managed_input.py")
        cls.mn = read_src("main.py")
        tree = ast.parse(cls.sl)
        cls.funcs = {n.name: ast.get_source_segment(cls.sl, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
        nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and "close_range" in n.name}
        cls.cr_funcs = {}
        spans = []
        for name, node in nodes.items():
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) and isinstance(node.body[0].value.value, str):
                node.body = node.body[1:] or [ast.Pass()]                   # the docstring is prose, not code
            cls.cr_funcs[name] = ast.unparse(node)
            spans.append((nodes[name].lineno, nodes[name].end_lineno))
        lines = cls.sl.split("\n")
        # the other places that touch the feature: the lines of the big functions that name it (outside the close-range functions)
        cls.cr_lines = [ln for i, ln in enumerate(lines, 1)
                        if (PENDING in ln or ANCHOR in ln or "close_range" in ln) and not any(a <= i <= b for a, b in spans) and not ln.lstrip().startswith(("#", "def "))]

    def cr_text(self):
        return "\n".join(list(self.cr_funcs.values()) + self.cr_lines)

    @case("RED", "S01 the feature exists: the pending flag and the anchor are written and read in scoring_logic.py", group="STATIC")
    def test_S01_feature_exists(self):
        contract(PENDING in self.sl and ANCHOR in self.sl, "scoring_logic.py does not know %s / %s" % (PENDING, ANCHOR))

    @case("RED", "S02 the expression: bve_next_loc - bve_margin_b - anchor <= setting_stop_distance (margin1 SUBTRACTED, <=, no margin2)", group="STATIC")
    def test_S02_expression(self):
        t = self.cr_text()
        contract(bool(t.strip()), "no close-range code")
        contract(re.search(r"bve_next_loc\s*-\s*(self\.)?bve_margin_b", t) is not None and ANCHOR in t, "near edge = bve_next_loc - bve_margin_b, then minus the anchor")
        contract("<=" in t and "setting_stop_distance" in t, "the comparison is <= against setting_stop_distance")

    @case("RED", "S03 the departure reset is conditioned on bve_speed > 0.0 and on the pending flag, and runs before the stop detection", group="STATIC")
    def test_S03_departure_condition_and_order(self):
        body = self.funcs.get("update_physics_and_scoring", "")
        i_reset = body.find("update_close_range_departure_reset(self")
        contract(i_reset >= 0, "update_physics_and_scoring does not call update_close_range_departure_reset")
        for marker in ("update_basic_braking_first_stop(self)", "stop_detected = is_exact_stop or crossed_zero", "evaluate_arrival(self, current_time)", "if in_station_zone and"):
            j = body.find(marker)
            contract(j < 0 or i_reset < j, "the departure reset must come before: " + marker)
        fn = self.cr_funcs.get("update_close_range_departure_reset", "")
        contract(re.search(r"bve_speed\s*>\s*0\.0", fn) is not None and PENDING in fn, "positive = bve_speed > 0.0, conditioned on the pending flag")

    @case("GUARD", "S10 (9) no HUD / official-target value is read by the close-range code", group="STATIC")
    def test_S10_no_hud_no_official(self):
        t = self.cr_text()
        self.assertIsNone(re.search(r"hud_|official_(state|index|location|margin|reason|target)|OfficialTarget|hud_target", t))

    @case("GUARD", "S11 margin2 (bve_margin_f), has_departed, door_open_loc, save_data are not read by the close-range code (OD-CR-1 / OD-CR-5)", group="STATIC")
    def test_S11_forbidden_inputs(self):
        t = self.cr_text()
        for word in ("bve_margin_f", "has_departed", "door_open_loc", "save_data", "target_arm_wait"):
            self.assertNotIn(word, t, word)

    @case("GUARD", "S32 (32) no distance search of a station identity in the close-range code", group="STATIC")
    def test_S32_no_identity_search(self):
        t = self.cr_text()
        self.assertIsNone(re.search(r"enumerate\(.*station_list|for\s+\w+\s*,\s*\w+\s+in\s+enumerate|\[.location.\]\s*-", t))

    @case("GUARD", "S33 (33) scoring_logic.py never assigns the target / arrival index (no target chosen by a distance); the one mirror prev_tgt_idx = bve_tgt_idx (SI-R5.2-C) is the only copy", group="STATIC")
    def test_S33_no_target_assignment(self):
        self.assertIsNone(re.search(r"self\.(bve_tgt_idx|bve_arr_idx|bve_arr_seq)\s*=[^=]", self.sl))
        self.assertEqual(re.findall(r"self\.prev_tgt_idx\s*=\s*([^\n#]+?)\s*(?:#|\n)", self.sl), ["self.bve_tgt_idx"])

    @case("GUARD", "S34 (34) scoring_logic.py never assigns NEXTLOC (prev_next_loc keeps its two existing copies of bve_next_loc)", group="STATIC")
    def test_S34_no_nextloc_assignment(self):
        self.assertIsNone(re.search(r"self\.bve_next_loc\s*=[^=]", self.sl))
        copies = re.findall(r"self\.prev_next_loc\s*=\s*([^\n]+)", self.sl)
        self.assertEqual(sorted(copies), ["self.bve_next_loc", "self.bve_next_loc"])

    @case("GUARD", "S35 (35) no 1 m reverse lookup is left (none is added; SI-R5.2-A removed P03, SI-R5.2-B removed P01, P04, P05, SI-R5.2-C removed P02)", group="STATIC")
    def test_S35_no_new_one_metre_lookup(self):
        n = len(re.findall(r"abs\(st\[\"location\"\]\s*-\s*[\w\.]+\)\s*<\s*1\.0", self.sl))
        self.assertLessEqual(n, 0, "found %d" % n)

    @case("GUARD", "S36 (36) no 50 m window (the G01 old expectation, the A0 files) in the product or in this fixture", group="STATIC")
    def test_S36_no_50m_window(self):
        for text in (self.sl, self.mn):
            self.assertIsNone(re.search(r"location\s*-\s*50\.0|>=\s*location\s*-\s*50", text))
        me = read_src(os.path.join("tests", os.path.basename(__file__)))
        pat = re.compile("location" + r"\s*-\s*50" + r"\.0")
        self.assertIsNone(pat.search(me))
        for name in ("red_a0_external_jump_target.py", "test_char_close_range_a0_external_jump.py", "test_close_range_target_arm_a2.py"):
            self.assertFalse(os.path.exists(os.path.join(HERE, name)), name + " must not be brought in unmodified")

    @case("GUARD", "S37 Night A's names are not carried over (target_arm_wait, init_basic_braking_for_target, update_target_arm)", group="STATIC")
    def test_S37_no_night_a_names(self):
        for word in ("target_arm_wait", "update_target_arm"):
            self.assertNotIn(word, self.sl + self.mi + self.mn, word)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------------------------------------------------------------------------------
class _Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []

    def _row(self, test, outcome, detail):
        fn = getattr(test, test._testMethodName, None)
        rc = getattr(fn, "rc", {"kind": "?", "req": "", "group": "", "note": ""})
        kind = rc["kind"]
        if outcome == "pass":
            cls = "GUARD-OK" if kind == "GUARD" else "RED-INVALID"
        elif outcome == "fail":
            if detail.startswith("CONTRACT:"):
                cls = "RED-VALID" if kind == "RED" else "GUARD-BROKEN"
            else:
                cls = "OLD-EXPECTATION" if kind == "RED" else "GUARD-BROKEN"
        elif outcome == "premise":
            cls = "FIXTURE-INVALID"
        elif outcome == "skip":
            cls = "SKIPPED"
        else:
            cls = "ERROR"
        self.rows.append((test._testMethodName, kind, rc["group"], rc["req"], outcome, cls, detail.replace("\t", " ").replace("\n", " | ")[:300]))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._row(test, "pass", "")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._row(test, "fail", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        if isinstance(err[1], PremiseBroken):
            self._row(test, "premise", str(err[1]))
        else:
            self._row(test, "error", "%s: %s" % (err[0].__name__, err[1]))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._row(test, "skip", reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            if isinstance(err[1], AssertionError):
                self._row(test, "fail", str(err[1]))
            else:
                self.addError(test, err)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else None
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = _Result()
    suite.run(res)
    rows = sorted(res.rows, key=lambda r: r[0])
    header = "test\tkind\tgroup\trequirement\toutcome\tclassification\tdetail"
    lines = [header] + ["\t".join(r) for r in rows]
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    counts = {}
    for r in rows:
        counts[r[5]] = counts.get(r[5], 0) + 1
    for r in rows:
        print("%-16s %-6s %-12s %s" % (r[5], r[1], r[2], r[0]))
    print("SUMMARY " + ", ".join("%s=%d" % kv for kv in sorted(counts.items())) + " total=%d" % len(rows))
    bad = [r for r in rows if r[5] not in ("RED-VALID", "GUARD-OK")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
