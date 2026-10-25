"""Time Fix B (CHAR_T19) - the operational stop (運転停車) is judged for its time score with the stop range of the station it ARRIVED AT, not with the range of the next target.

THE DEFECT (ST-0 characterization T19, F-ST-1): evaluate_departure() (scoring_logic.py) runs on the tick on which NEXTLOC changes forward (the target switches to the next station, for an
operational stop 300 ms after the departure time). On that tick MARGINB / MARGINF already belong to the NEW target, so the range check of the station that was left (-MARGINF <= p_loc -
location <= MARGINB) was made with the margins of the next station. Run C could not show it: the arrived station and the next station both had +-5 m.

THE CONTRACT (this file): when the operational stop is arrived at (has_scored_stop_this_station is set by the operational arrival block), the margins of that station are kept
(Overlay.operational_stop_margins = (MARGINF, MARGINB)); the departure range check of an operational stop uses them; the state is cleared with the other per-station evaluation state.
tgt / arr / arrseq are NOT touched (this module never writes bve_tgt_idx / bve_arr_idx / bve_arr_seq), the 300 ms switch of the C# senders is unchanged, and a normal (customer)
stop, a pass station and the scoring-finish station keep their behaviour (the normal stop keeps the ST-0 T19 KNOWN-DEFECT behaviour pinned in test_char_stop_door_arrival_st0.py).

Cases tagged [RED-B] fail on the code before Time Fix B. Without PyQt6 (python -I) the behaviour tests are SKIPPED; the source pins always run.

TIME FIX B2 NOTE (the contract of tests/test_timefix_b2_operational_stop_contract.py): the operational stop is judged ONCE, at the stop, with the range of the station that is arrived at; the position of the vehicle on the Tick of
the target switch is no longer judged. The four cases that asserted "left outside the arrival range -> no time score" (B_T2, B_T4, B_T5b, B_T6b) are SUPERSEDED: they now assert the same intent at the stop - a stop
outside the range of the arrived station is no operational stop, whatever the range of the next station is. The superseded situations (stopped inside, then outside the range at the switch) score 300 under B2
(test_C_T01b in the B2 file).
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
_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-timefix-b-")
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
        raise AssertionError("the Time Fix B module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def stations_abcd():
    """A idx0 @0, B idx1 @1000 (the station that is left), C idx2 @2000 (the new target), D idx3 @3000 (terminal)."""
    return [sta("A", 0.0), sta("B", 1000.0, is_timing=True, raw_dep=T0 + 60000), sta("C", 2000.0, is_timing=True), sta("D", 3000.0, terminal=True)]


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
        cls.app = QApplication.instance() or QApplication(["timefix-b"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0

    def scene(self, d=0.0, doordir=0, is_pass=0, speed=0.0, end_idx=3, next_loc=1000.0):
        """The vehicle `d` m SHORT of the target B, stopped, doors closed, after a departure, scoring on. NEXTLOC == prev_next_loc: no station transition in the next tick."""
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = stations_abcd()
        o.setting_end_idx = end_idx
        o.save_data = [cp(0.0, T0, "A")]
        o.bve_next_loc = o.prev_next_loc = next_loc
        o.bve_location = next_loc - d
        o.bve_speed = speed
        o.bve_is_pass = is_pass
        o.bve_doordir = doordir
        o.bve_door = o.prev_door = 0
        o.bve_margin_b = o.bve_margin_f = 5.0
        o.has_departed = True
        o.is_first_station = False
        o.is_first_udp = False
        o.bve_time_ms = T0 + 60000
        o.bve_next_time = o.bve_time_ms
        o.bve_current_station_name = "B"
        o.jump_lock = False
        o.is_official_jumping = False
        if not getattr(o, "bve_list_id", ""):
            R.bind_identity(o)
        return o

    def tick(self, n=1):
        for _ in range(n):
            self.t += 0.016
            self.S.update_physics_and_scoring(self.o, self.t, 0.016)

    def departure(self, arr_f, arr_b, next_f, next_b, d_arrive, d_depart, doordir=0, is_pass=0, retry=False, end_idx=3):
        """B @1000 is arrived at `d_arrive` m short of it with its OWN margins (arr_f / arr_b), then the vehicle leaves (it is `d_depart` m short of B on the last tick) and the tick of the
        target switch carries C @2000 and C's margins (next_f / next_b) - exactly what the C# senders publish on the switch tick."""
        o = self.scene(d=d_arrive, doordir=doordir, is_pass=is_pass, end_idx=end_idx)
        o.bve_margin_f, o.bve_margin_b = arr_f, arr_b
        o.prev_is_pass = is_pass
        o.prev_is_timing = 1
        o.prev_doordir = doordir
        o.is_official_retry = retry
        self.tick()                                                                              # the arrival tick (an operational stop arrives without any door change)
        before = getattr(o, "operational_stop_margins", "ABSENT")
        o.bve_location = 1000.0 - d_depart
        o.bve_speed = 10.0
        self.tick()                                                                              # B is still the target while the vehicle leaves
        o.bve_next_loc = 2000.0
        o.bve_margin_f, o.bve_margin_b = next_f, next_b
        o.bve_doordir = 1
        self.tick()                                                                              # the switch tick: NEXTLOC / MARGIN* of the new target
        return o, before


class A_OperationalStop(Base):
    def test_B_T1_arrival_range_inside_next_range_outside_scores_the_time(self):
        """[RED-B] left 3 m short of B: inside B's +-5 m, outside C's +-2 m -> the time is scored with B's range."""
        o, _ = self.departure(5.0, 5.0, 2.0, 2.0, d_arrive=1.0, d_depart=3.0)
        self.assertEqual(o.score_details["time"], 300)

    def test_B_T2_arrival_range_outside_next_range_inside_does_not_score_the_time(self):
        """[RED-B] [SUPERSEDED-BY-B2: judged at the stop] stopped 3 m short of B: outside B's +-2 m, inside C's +-5 m -> no operational stop, no time score (the range of the next station must not grant it)."""
        o, _ = self.departure(2.0, 2.0, 5.0, 5.0, d_arrive=3.0, d_depart=3.0)
        self.assertEqual(o.score_details["time"], 0)

    def test_B_T3_both_ranges_inside_scores_the_time_as_before(self):
        o, _ = self.departure(4.0, 4.0, 6.0, 6.0, d_arrive=1.0, d_depart=3.0)
        self.assertEqual(o.score_details["time"], 300)

    def test_B_T4_both_ranges_outside_does_not_score_the_time(self):
        """[SUPERSEDED-BY-B2: judged at the stop] stopped 3 m short of B: outside both ranges -> no operational stop, no time score."""
        o, _ = self.departure(2.0, 2.0, 2.5, 2.5, d_arrive=3.0, d_depart=3.0)
        self.assertEqual(o.score_details["time"], 0)

    def test_B_T5_equal_ranges_keep_the_run_c_result(self):
        """Run C had +-5 m at the arrived station and at the next one: the result is the same before and after the fix."""
        o, _ = self.departure(5.0, 5.0, 5.0, 5.0, d_arrive=1.0, d_depart=3.0)
        self.assertEqual(o.score_details["time"], 300)

    def test_B_T5b_equal_ranges_outside_still_do_not_score(self):
        """[SUPERSEDED-BY-B2: judged at the stop] stopped 5.5 m short of B with equal +-5 m ranges: outside -> no operational stop, no time score."""
        self.rig.close()
        self.setUp()
        o, _ = self.departure(5.0, 5.0, 5.0, 5.0, d_arrive=5.5, d_depart=5.5)
        self.assertEqual(o.score_details["time"], 0)

    def test_B_T6_the_reference_range_does_not_change_across_the_target_switch(self):
        """[RED-B] the margins of the arrived station are kept from the arrival until the switch tick has been judged, then they go with the other per-station state; MARGINF is the
        past side and MARGINB the short side (asymmetric ranges: B 3 m / 8 m, C 1 m / 1 m; the vehicle left 2.5 m PAST B)."""
        o, before = self.departure(3.0, 8.0, 1.0, 1.0, d_arrive=1.0, d_depart=-2.5)
        self.assertEqual(before, (3.0, 8.0))                                                     # kept at the arrival (before the switch)
        self.assertEqual(o.score_details["time"], 300)                                           # judged with B's MARGINF = 3 (past side), not C's 1
        self.assertIsNone(getattr(o, "operational_stop_margins", "ABSENT"))                      # cleared with the other per-station state after the switch
        self.assertFalse(o.has_scored_stop_this_station)

    def test_B_T6b_the_past_side_uses_the_arrived_stations_marginf(self):
        """[RED-B] [SUPERSEDED-BY-B2: judged at the stop] stopped 4 m past B: outside B's MARGINF = 3, inside C's MARGINF = 5 -> no operational stop, no time score."""
        o, _ = self.departure(3.0, 8.0, 5.0, 5.0, d_arrive=-4.0, d_depart=-4.0)
        self.assertEqual(o.score_details["time"], 0)

    def test_B_T9_a_retry_before_an_operational_stop_is_judged_with_the_arrived_stations_range(self):
        """[RED-B] after an official retry the operational stop is arrived at again (jump lock on, no time score at the arrival) and its range is kept for the departure."""
        o = self.scene(d=1.0, doordir=0)
        o.bve_margin_f, o.bve_margin_b = 5.0, 5.0
        o.prev_is_pass = 0
        o.prev_is_timing = 1
        o.prev_doordir = 0
        o.is_official_retry = True
        o.jump_lock = True
        self.tick()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(getattr(o, "operational_stop_margins", "ABSENT"), (5.0, 5.0))
        o.jump_lock = False
        o.bve_location = 1000.0 - 3.0
        o.bve_speed = 10.0
        self.tick()
        o.bve_next_loc = 2000.0
        o.bve_margin_f, o.bve_margin_b = 2.0, 2.0
        o.bve_doordir = 1
        self.tick()
        self.assertEqual(o.score_details["time"], 300)

    def test_B_T9b_without_an_arrival_there_is_nothing_to_keep_and_the_old_rule_stays(self):
        """Corner (documented risk R-B1): a retry flag without any arrival tick at the station keeps no range; the departure then falls back to the margins the sender publishes."""
        o = self.scene(d=3.0, doordir=0)
        o.station_list = stations_abcd()
        o.prev_is_pass = 0
        o.prev_is_timing = 1
        o.prev_doordir = 0
        o.is_official_retry = True
        o.bve_speed = 10.0                                                                       # the vehicle never stopped in the range at B
        o.has_scored_stop_this_station = False
        self.tick()
        self.assertEqual(getattr(o, "operational_stop_margins", None), None)
        o.bve_next_loc = 2000.0
        o.bve_margin_f, o.bve_margin_b = 2.0, 2.0
        self.tick()
        self.assertEqual(o.score_details["time"], 0)                                             # (the fallback is the sender's published margins: out of C's 2 m)


class B_OtherStops(Base):
    def test_B_T7_a_normal_stop_keeps_the_t19_behaviour(self):
        """The customer stop is NOT part of Time Fix B: its departure range check still uses the margin of the NEW target (ST-0 T19 KNOWN-DEFECT, pinned in
        test_char_stop_door_arrival_st0.py): 10 m short of B is outside B's 2 m and inside C's 20 m -> scored; the other way round -> not scored."""
        for origin, new, expect in ((2.0, 20.0, 300), (20.0, 2.0, 0)):
            with self.subTest(origin=origin, new=new):
                self.rig.close()
                self.setUp()
                o = self.scene(d=10.0, doordir=1)
                o.bve_margin_b = o.bve_margin_f = origin
                o.prev_is_pass = 0
                o.prev_is_timing = 1
                o.has_scored_stop_this_station = True
                o.has_scored_time_this_station = False
                o.bve_speed = 30.0
                self.tick()
                o.bve_next_loc = 2000.0
                o.bve_margin_b = o.bve_margin_f = new
                self.tick()
                self.assertEqual(o.score_details["time"], expect)
                self.assertIsNone(getattr(o, "operational_stop_margins", None))

    def test_B_T7b_a_normal_stop_arrival_keeps_no_operational_range(self):
        o = self.scene(d=0.0, doordir=1)
        self.tick()
        o.bve_door = 1
        self.tick()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertIsNone(getattr(o, "operational_stop_margins", None))

    def test_B_T8_a_pass_station_has_no_arrival_and_keeps_no_range(self):
        o = self.scene(d=0.0, doordir=0, is_pass=1)
        o.prev_is_pass = 1
        self.tick(3)
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertEqual(len(o.save_data) - 1, 0)
        self.assertIsNone(getattr(o, "operational_stop_margins", None))
        self.assertEqual(o.score_details["time"], 0)

    def test_B_T10_the_scoring_finish_operational_stop_is_unchanged(self):
        """CURRENT-BEHAVIOR-ONLY (the finish station contract is not in the canon, so nothing is inferred): an operational stop that is the END station scores the arrival time at the
        arrival and finishes the scoring there; the departure judgement is never reached. Pinned as it is; to be re-checked in the final regression."""
        o = self.scene(d=0.0, doordir=0, end_idx=1)
        o.station_list = stations_abcd()
        o.prev_is_timing = 1
        self.tick()
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(o.score_details["time"], 300)

    def test_B_reset_station_evaluation_state_clears_the_range(self):
        o = self.o
        o.operational_stop_margins = (3.0, 8.0)
        self.S.reset_station_evaluation_state(o)
        self.assertIsNone(o.operational_stop_margins)


class C_SourcePins(unittest.TestCase):
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

    def test_B_pin_the_range_is_kept_in_exactly_one_place_the_operational_arrival(self):
        self.assertEqual(len(re.findall(r"self\.operational_stop_margins\s*=\s*\(", self.src)), 1)
        self.assertEqual(len(re.findall(r"self\.operational_stop_margins\s*=\s*None", self.src)), 1)
        reset = ast.get_source_segment(self.src, self.function("reset_station_evaluation_state"))
        self.assertIn("self.operational_stop_margins = None", reset)
        physics = ast.get_source_segment(self.src, self.function("update_physics_and_scoring"))
        block = physics[physics.index("if is_operational_stop and getattr(self, 'is_approaching', False)"):]
        block = block[:block.index("# 通常停車駅の開扉時は")]
        self.assertIn("self.operational_stop_margins = (self.bve_margin_f, self.bve_margin_b)", block)
        self.assertLess(block.index("self.operational_stop_margins ="), block.index("self.has_scored_stop_this_station = True"))

    def test_B_pin_the_departure_uses_the_kept_range_only_for_an_operational_stop(self):
        dep = ast.get_source_segment(self.src, self.function("evaluate_departure"))
        self.assertIn("getattr(self, 'prev_doordir', 1) == 0", dep)
        self.assertIn("getattr(self, 'operational_stop_margins', None)", dep)
        self.assertEqual(dep.count("self.bve_margin_f"), 1)                      # only the fallback / default assignment names the telemetry margin
        self.assertEqual(dep.count("self.bve_margin_b"), 1)

    def test_B_pin_tgt_arr_and_arrseq_are_never_written_by_the_scoring(self):
        self.assertEqual(re.findall(r"self\.bve_(?:tgt_idx|arr_idx|arr_seq)\s*(?:=|\+=)(?!=)", self.src), [])

    def test_B_pin_the_new_state_is_classified_as_a_getattr_default_attribute(self):
        self.assertIn('"operational_stop_margins"', self.managed)


if __name__ == "__main__":
    unittest.main()
