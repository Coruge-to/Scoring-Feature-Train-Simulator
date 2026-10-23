"""Phase PID-D4JA StationIndex ST-0 (file C1) - CHARACTERIZATION of the stop / door / operational-stop / pass / departure / first-station paths of the Python
scoring (scoring_logic.update_physics_and_scoring, evaluate_arrival, evaluate_departure, apply_stop_score and the telemetry parse of main.py).
It pins what the production Python does TODAY. It is NOT a list of approved requirements: every test carries ONE of these meanings (see st0()):

    REQUIREMENT-BACKED       rests on BVE-internal information or on an author-defined value (Vehicle.Doors.AreAllClosed, Station.Pass, Station.DoorSide,
                             Station.MarginMin / MarginMax)
    CURRENT-BEHAVIOR-ONLY    today's behaviour; no requirement document backs it (thresholds, hold times, order of conditions)
    KNOWN-DEFECT-BEHAVIOR    a behaviour that exists today and that the formal StationIndex contract is meant to CHANGE; passing it does NOT approve it
    CROSS-LAYER-DIFFERENCE   Current and Legacy (or C# and Python) do not mean the same
    FUTURE-REPLACEMENT-TARGET the physical result that must stay identical when the station identity is later taken from the StationIndex instead of a distance search

The ids T13 ... T20 are the ids of 11-Red-Test-Plan.md of the contract-gap audit (pid-stationindex-contract-gap-audit-v1); "item n" (items=...) is the number of the
owner's CHARACTERIZATION list (items 1-20) of the request of this session (the RED list, items 1-13, is numbered separately in red_st0_stationindex_contract.py). The companion files are test_char_stop_door_source_pins_st0.py (C# / Python source shape) and
Test-StationStopCharST0.ps1 (Legacy state machine), the target-contract RED suite is tests/red_st0_stationindex_contract.py.

ISOLATION: the same seams as tests/sia_rig.py (real Overlay offscreen, keyboard / Win32 / clock / timers / dialog / write_desktop_log are recorders, the UDP
socket is a stub: UDP 54321 / 54322 are never bound or sent to). USERPROFILE / HOME point to an empty temporary folder for the whole module and the module
asserts at its end that nothing was written there. Nothing is written outside that temporary folder.
Without PyQt6 (for example python -I when PyQt6 is a user-site package) every test of this file is SKIPPED, never passed.
"""
import inspect
import os
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

LABELS = ("REQUIREMENT-BACKED", "CURRENT-BEHAVIOR-ONLY", "KNOWN-DEFECT-BEHAVIOR", "CROSS-LAYER-DIFFERENCE", "FUTURE-REPLACEMENT-TARGET")
T0 = 36000000


def st0(tid, label, items=(), note=""):
    """Attach the ST-0 metadata: tid = the id of 11-Red-Test-Plan.md, label = the meaning (LABELS), items = the numbers of the owner's list, note = one line."""
    assert label in LABELS, label

    def deco(fn):
        fn.st0 = {"id": tid, "label": label, "items": tuple(items), "note": note}
        return fn
    return deco


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-st0-c1-")
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
        raise AssertionError("the ST-0 C1 module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def stations_abcd():
    """A idx0 @0, B idx1 @1000, C idx2 @2000, D idx3 @3000 (terminal)."""
    return [sta("A", 0.0), sta("B", 1000.0), sta("C", 2000.0), sta("D", 3000.0, terminal=True)]


def cp(loc, t, name="X", target_loc=None):
    return {"loc": loc, "time_ms": t, "score": 0, "target_loc": loc if target_loc is None else target_loc, "station_name": name, "stop_error": 0.0, "score_details": {}}


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["st0-c1"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.log = self.rig.log
        self.t = 100.0

    # -- the scene -------------------------------------------------------------------------------------------------------------------------------
    def scene(self, d=0.0, doordir=1, is_pass=0, speed=0.0, end_idx=3, next_loc=1000.0, stations=None):
        """The vehicle `d` m SHORT of the target (d = NEXTLOC - location; d < 0 is past it), stopped, doors closed, after a departure, scoring on, scoring start
        long done. NEXTLOC == prev_next_loc, so no station transition happens in the next tick."""
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = stations if stations is not None else stations_abcd()
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
        o.bve_current_station_name = "B"
        o.jump_lock = False
        o.is_official_jumping = False
        if not getattr(o, "bve_list_id", ""):                                   # Phase ST-2a: a sender that names the station of the target (a scene that binds its own identity is left alone)
            R.bind_identity(o)
        return o

    def tick(self, n=1):
        for _ in range(n):
            self.t += 0.016
            self.S.update_physics_and_scoring(self.o, self.t, 0.016)

    def open_doors(self):
        self.o.bve_door = 1
        self.tick()

    def arrivals(self):
        """The number of check points added after the initial one (an arrival creates one) and the stop-position popups."""
        return len(self.o.save_data) - 1

    def stop_popups(self):
        return [p["text"] for p in self.o.popups if p["category"] == "停止位置"]


# ==============================================================================================================================================
# T13 : a normal (commercial) stop - the arrival is the door rising edge, inside the author-defined range
# ==============================================================================================================================================
class A_NormalStop(Base):
    @st0("T13", "REQUIREMENT-BACKED", items=(3, 4, 7), note="the arrival of a normal stop is the DOOR 0 -> 1 rising edge of the BVE-internal door state, inside the range")
    def test_CHAR_T13_a_door_rising_edge_inside_the_range_is_exactly_one_arrival(self):
        o = self.scene(d=0.0)
        self.tick()
        self.assertEqual((o.has_scored_stop_this_station, self.arrivals()), (False, 0))          # stopped in the range with the doors closed: not an arrival yet
        self.open_doors()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(self.arrivals(), 1)
        self.assertEqual(o.save_data[-1]["target_loc"], 1000.0)
        self.assertEqual(self.stop_popups(), ["停止位置 +500"])

    @st0("T13", "CURRENT-BEHAVIOR-ONLY", items=(4,), note="doors that stay open do not arrive again, and a second rising edge at the same station adds no check point and no stop score")
    def test_CHAR_T13_the_arrival_is_once_per_station_a_second_edge_changes_nothing(self):
        o = self.scene(d=0.0)
        self.tick()
        self.open_doors()
        self.tick(3)                                                                              # the doors stay open
        self.assertEqual((self.arrivals(), len(self.stop_popups())), (1, 1))
        o.bve_door = 0
        self.tick()
        o.bve_door = 1
        self.tick()                                                                               # a new rising edge at the same station
        self.assertEqual((self.arrivals(), len(self.stop_popups())), (1, 1))

    @st0("T13", "CURRENT-BEHAVIOR-ONLY", items=(4,), note="doors that are already open at the first tick are not a rising edge")
    def test_CHAR_T13_doors_already_open_when_the_state_starts_are_not_an_arrival(self):
        o = self.scene(d=0.0)
        o.bve_door = o.prev_door = 1
        self.tick(3)
        self.assertEqual((o.has_scored_stop_this_station, self.arrivals()), (False, 0))

    @st0("T13", "CURRENT-BEHAVIOR-ONLY", items=(4,), note="a stop inside the range with the doors never opened is no arrival of a normal stop (it is NOT read as an operational stop)")
    def test_CHAR_T13_a_normal_stop_whose_doors_never_open_does_not_arrive_and_is_not_reinterpreted(self):
        o = self.scene(d=0.0, doordir=1)
        self.tick(5)
        self.assertEqual((o.has_scored_stop_this_station, self.arrivals()), (False, 0))
        self.assertEqual(o.bve_doordir, 1)                                                        # nothing turned the normal stop into an operational one

    @st0("T13", "CURRENT-BEHAVIOR-ONLY", items=(4,), note="while the official jump is on, a door edge is not an arrival")
    def test_CHAR_T13_a_door_edge_during_the_official_jump_is_not_an_arrival(self):
        o = self.scene(d=0.0)
        o.is_official_jumping = True
        self.tick()
        self.open_doors()
        self.assertEqual((o.has_scored_stop_this_station, self.arrivals()), (False, 0))

    @st0("T13", "KNOWN-DEFECT-BEHAVIOR", items=(7, 18), note="the arrival needs a station within 1.0 m of NEXTLOC: the identity of the arrival is decided by a position search")
    def test_CHAR_T13_the_arrival_station_is_found_by_a_1_0_m_search_from_NEXTLOC(self):
        for next_loc, found in ((1000.9, True), (1001.0, False), (999.1, True), (999.0, False)):
            with self.subTest(next_loc=next_loc):
                self.rig.close()
                self.setUp()
                o = self.scene(d=0.0, next_loc=next_loc)
                self.tick()
                self.open_doors()
                self.assertEqual(o.has_scored_stop_this_station, found)
                # Phase ST-2a (inverted for the checkpoint only; the 1.0 m search that decides the arrival SCORE is unchanged until ST-4): the checkpoint is created
                # for the station the sender names, and only when NEXTLOC is that station's position within 0.01 m - none of these four is
                self.assertEqual(self.arrivals(), 0)


# ==============================================================================================================================================
# T17 : the author-defined stop range gates the arrival
# ==============================================================================================================================================
class B_Tolerance(Base):
    @st0("T17", "REQUIREMENT-BACKED", items=(10, 11), note="the arrival needs -MARGINF <= (NEXTLOC - location) <= MARGINB; both bounds belong to the range")
    def test_CHAR_T17_the_range_bounds_are_inclusive_and_a_stop_outside_makes_no_arrival(self):
        for d, inside in ((5.0, True), (-5.0, True), (5.01, False), (-5.01, False)):
            with self.subTest(d=d):
                self.rig.close()
                self.setUp()
                o = self.scene(d=d)
                self.tick()
                self.open_doors()
                self.assertEqual(o.has_scored_stop_this_station, inside)
                self.assertEqual(self.arrivals(), 1 if inside else 0)

    @st0("T17", "REQUIREMENT-BACKED", items=(10, 11), note="the two sides use different values: MARGINB is the short side (d > 0), MARGINF the past side (d < 0)")
    def test_CHAR_T17_marginb_is_the_short_side_and_marginf_the_past_side(self):
        for d, mb, mf, inside in ((3.0, 2.0, 9.0, False), (3.0, 4.0, 1.0, True), (-3.0, 9.0, 2.0, False), (-3.0, 1.0, 4.0, True)):
            with self.subTest(d=d, mb=mb, mf=mf):
                self.rig.close()
                self.setUp()
                o = self.scene(d=d)
                o.bve_margin_b, o.bve_margin_f = mb, mf
                self.tick()
                self.open_doors()
                self.assertEqual(o.has_scored_stop_this_station, inside)

    @st0("T17", "REQUIREMENT-BACKED", items=(10,), note="a stop (speed 0.0) inside the approach zone but outside the range is remembered as out of range")
    def test_CHAR_T17_a_stop_outside_the_range_is_flagged_out_of_range(self):
        o = self.scene(d=5.01)
        self.tick()
        self.assertTrue(o.is_stopped_out_of_range)
        o2 = self.scene(d=5.0)
        o2.is_stopped_out_of_range = False
        self.tick()
        self.assertFalse(o2.is_stopped_out_of_range)

    @st0("T17", "CURRENT-BEHAVIOR-ONLY", note="the approach zone (is_approaching) is the application's own train-length based distance, not the author-defined range")
    def test_CHAR_T17_the_approach_zone_is_not_the_author_defined_range(self):
        o = self.scene(d=30.0)
        o.bve_train_length = 100
        o.setting_stop_distance = -1
        self.tick()
        self.assertTrue(o.is_approaching)                                                        # 30 m is inside the train length based zone ...
        self.assertTrue(abs(o.bve_next_loc - o.bve_location) > o.bve_margin_b)                   # ... and far outside the author-defined 5 m


# ==============================================================================================================================================
# T14 : an operational stop (not Pass, DoorSide == 0) - no door is required
# ==============================================================================================================================================
class C_OperationalStop(Base):
    @st0("T14", "REQUIREMENT-BACKED", items=(5, 6, 8), note="an operational stop is Pass == 0 and DoorSide == 0 (author-defined); it arrives with the doors never opened")
    def test_CHAR_T14_an_operational_stop_arrives_without_any_door_change(self):
        o = self.scene(d=0.0, doordir=0)
        self.tick()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(self.arrivals(), 1)
        self.assertEqual(o.bve_door, 0)
        self.assertEqual(self.stop_popups(), ["停止位置 +500"])

    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(6, 14), note="Python's stop is bve_speed == 0.0 exactly: 0.05 km/h is no operational arrival (the C# senders call < 0.1 km/h stopped)")
    def test_CHAR_T14_an_operational_stop_needs_the_speed_to_be_exactly_zero_in_python(self):
        for speed, arrives in ((0.0, True), (0.05, False), (0.09, False)):
            with self.subTest(speed=speed):
                self.rig.close()
                self.setUp()
                o = self.scene(d=0.0, doordir=0, speed=speed)
                self.tick()
                self.assertEqual(o.has_scored_stop_this_station, arrives)

    @st0("T14", "REQUIREMENT-BACKED", items=(6, 10), note="an operational stop is also gated by the author-defined range")
    def test_CHAR_T14_an_operational_stop_outside_the_range_makes_no_arrival(self):
        o = self.scene(d=5.01, doordir=0)
        self.tick(2)
        self.assertEqual((o.has_scored_stop_this_station, self.arrivals(), o.is_stopped_out_of_range), (False, 0, True))

    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(8,), note="at an operational stop a later door edge is not a second arrival (the door-edge path is closed for operational stops)")
    def test_CHAR_T14_a_door_edge_at_an_operational_stop_does_not_arrive_twice(self):
        o = self.scene(d=0.0, doordir=0)
        o.bve_door = 1
        self.tick()
        self.tick()
        o.bve_door = 0
        self.tick()
        o.bve_door = 1
        self.tick()
        self.assertEqual((self.arrivals(), len(self.stop_popups())), (1, 1))

    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(6,), note="no arrival of an operational stop while the scoring start is not finished (is_first_station) or the jump lock is on")
    def test_CHAR_T14_the_first_station_and_the_jump_lock_hold_back_the_operational_arrival(self):
        o = self.scene(d=0.0, doordir=0)
        o.is_first_station = True
        self.tick()
        self.assertEqual(self.arrivals(), 0)
        o = self.scene(d=0.0, doordir=0)
        o.jump_lock = True
        o.has_scored_stop_this_station = False
        self.tick()
        self.assertEqual(self.arrivals(), 0)

    @st0("T14", "KNOWN-DEFECT-BEHAVIOR", items=(6,), note="a missing / failed DOORDIR leaves the default 1, which makes an operational stop a normal stop that never arrives")
    def test_CHAR_T14_the_default_doordir_is_1_so_a_lost_value_turns_an_operational_stop_into_a_normal_one(self):
        o = self.rig.o
        self.assertEqual(o.bve_doordir, 1)
        o = self.scene(d=0.0, doordir=1)                                                         # what the Overlay holds when DOORDIR was never received
        self.tick(5)
        self.assertEqual((o.has_scored_stop_this_station, self.arrivals()), (False, 0))


# ==============================================================================================================================================
# T15 : a pass station
# ==============================================================================================================================================
class D_PassStation(Base):
    @st0("T15", "REQUIREMENT-BACKED", items=(5, 9), note="a pass station (Station.Pass) with the doors closed is no arrival, no check point and no stop score, stopped or not")
    def test_CHAR_T15_a_pass_station_with_closed_doors_is_never_an_arrival(self):
        for speed, doordir in ((0.0, 1), (0.0, 0), (60.0, 1)):
            with self.subTest(speed=speed, doordir=doordir):
                self.rig.close()
                self.setUp()
                o = self.scene(d=0.0, is_pass=1, doordir=doordir, speed=speed)
                self.tick(4)
                self.assertEqual((o.has_scored_stop_this_station, self.arrivals(), self.stop_popups()), (False, 0, []))

    @st0("T15", "CURRENT-BEHAVIOR-ONLY", items=(9,), note="Python has no Pass guard on the door-edge path: a door rising edge at a pass station inside the range IS an arrival; the protection is the sender's")
    def test_CHAR_T15_python_does_not_exclude_a_pass_station_from_the_door_edge_path(self):
        o = self.scene(d=0.0, is_pass=1, doordir=1)
        self.tick()
        self.open_doors()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(self.arrivals(), 1)


# ==============================================================================================================================================
# the telemetry that reaches Python: DOOR, DOORDIR, ISPASS, MARGINB, MARGINF
# ==============================================================================================================================================
class E_TelemetryInputs(Base):
    @st0("T16", "REQUIREMENT-BACKED", items=(3, 5, 11), note="DOOR:0/1, DOORDIR:n, ISPASS:n, MARGINB:x and MARGINF:x become bve_door, bve_doordir, bve_is_pass, bve_margin_b, bve_margin_f")
    def test_CHAR_T16_the_door_stop_kind_and_margin_tokens_are_taken_over_as_they_are(self):
        o = self.o
        o.apply_telemetry_text("DOOR:1,DOORDIR:0,ISPASS:1,MARGINB:3.5,MARGINF:4.25")
        self.assertEqual((o.bve_door, o.bve_doordir, o.bve_is_pass, o.bve_margin_b, o.bve_margin_f), (1, 0, 1, 3.5, 4.25))
        o.apply_telemetry_text("DOOR:0,DOORDIR:-1,ISPASS:0,MARGINB:5.0,MARGINF:5.0")
        self.assertEqual((o.bve_door, o.bve_doordir, o.bve_is_pass, o.bve_margin_b, o.bve_margin_f), (0, -1, 0, 5.0, 5.0))

    @st0("T16", "CURRENT-BEHAVIOR-ONLY", items=(3, 11), note="an unparsable token is skipped and keeps the previous value (no reset, no error)")
    def test_CHAR_T16_an_unparsable_token_keeps_the_previous_value(self):
        o = self.o
        o.apply_telemetry_text("DOOR:1,MARGINB:2.5")
        o.apply_telemetry_text("DOOR:x,MARGINB:")
        self.assertEqual((o.bve_door, o.bve_margin_b), (1, 2.5))

    @st0("T17", "KNOWN-DEFECT-BEHAVIOR", items=(12,), note="the Python defaults are MARGINB = MARGINF = 5.0, DOORDIR = 1, DOOR = 0: a sender that never sends them looks like a normal stop with the 5 m range")
    def test_CHAR_T17_the_python_defaults_when_a_value_is_never_received(self):
        o = self.o
        self.assertEqual((o.bve_margin_b, o.bve_margin_f, o.bve_doordir, o.bve_door, o.bve_is_pass), (5.0, 5.0, 1, 0, 0))


# ==============================================================================================================================================
# T19 : the departure is judged with the margin of the NEW target
# ==============================================================================================================================================
class F_Departure(Base):
    def departure_scene(self, origin_margin, new_margin, d=10.0):
        """B @1000 (origin) -> C @2000 (new target). The vehicle is `d` m short of B. The previous tick still had B as NEXTLOC and B's margin; the tick of the
        transition carries C as NEXTLOC and C's margin (the C# senders derive every station value from the NEW target on the transition tick)."""
        o = self.scene(d=d)
        stations = [sta("A", 0.0), sta("B", 1000.0, is_timing=True, raw_dep=T0 + 60000), sta("C", 2000.0, is_timing=True), sta("D", 3000.0, terminal=True)]
        o.station_list = stations
        o.bve_margin_b = o.bve_margin_f = origin_margin
        o.prev_is_pass = 0
        o.prev_is_timing = 1
        o.has_scored_stop_this_station = True                                                    # B was arrived at and its stop scored
        o.has_scored_time_this_station = False
        o.bve_speed = 30.0
        o.bve_door = 0
        o.bve_time_ms = T0 + 60000
        o.bve_next_time = o.bve_time_ms
        self.tick()                                                                              # the last tick before the transition (B still the target)
        o.bve_next_loc = 2000.0                                                                  # the transition tick: NEXTLOC / MARGIN* of the new target
        o.bve_margin_b = o.bve_margin_f = new_margin
        self.tick()
        return o

    @st0("T19", "KNOWN-DEFECT-BEHAVIOR", items=(16,), note="F-ST-1: the departure range check of station B uses the margin of the NEW target C: 10 m short of B is out of B's 2 m range but inside C's 20 m")
    def test_CHAR_T19_the_departure_is_judged_with_the_new_targets_margin(self):
        o = self.departure_scene(origin_margin=2.0, new_margin=20.0)
        self.assertEqual(o.score_details["time"], 300)                                           # judged IN range although B's own range (2 m) says out

    @st0("T19", "KNOWN-DEFECT-BEHAVIOR", items=(16,), note="the same departure with the margins the other way round (B wide, C narrow) is judged OUT of range by the narrow new margin")
    def test_CHAR_T19_the_same_defect_in_the_other_direction(self):
        o = self.departure_scene(origin_margin=20.0, new_margin=2.0)
        self.assertEqual(o.score_details["time"], 0)                                             # judged out although B's own range (20 m) says in

    @st0("T19", "CURRENT-BEHAVIOR-ONLY", items=(16,), note="with equal margins the defect is invisible: the departure inside the range scores the time")
    def test_CHAR_T19_equal_margins_hide_the_difference(self):
        o = self.departure_scene(origin_margin=5.0, new_margin=5.0, d=3.0)
        self.assertEqual(o.score_details["time"], 300)

    @st0("T19", "CURRENT-BEHAVIOR-ONLY", items=(16,), note="the departure time score needs a stop that was scored (or an official retry)")
    def test_CHAR_T19_no_time_score_without_a_scored_stop(self):
        o = self.departure_scene(origin_margin=5.0, new_margin=5.0, d=3.0)
        self.assertEqual(o.score_details["time"], 300)                                           # the control: with a scored stop the same departure scores
        self.rig.close()
        self.setUp()
        o2 = self.scene(d=3.0)
        o2.station_list = [sta("A", 0.0), sta("B", 1000.0, is_timing=True, raw_dep=T0 + 60000), sta("C", 2000.0, is_timing=True), sta("D", 3000.0, terminal=True)]
        o2.prev_is_pass = 0
        o2.prev_is_timing = 1
        o2.has_scored_stop_this_station = False
        o2.is_official_retry = False
        o2.bve_speed = 30.0
        self.tick()
        o2.bve_next_loc = 2000.0
        self.tick()
        self.assertEqual(o2.score_details["time"], 0)


# ==============================================================================================================================================
# T20 : the first-station decision of the first UDP line (Phase ST-2c: it was a 100 m distance test; now the first line clears nothing)
# ==============================================================================================================================================
class G_FirstStation(Base):
    def first_udp_scene(self, d):
        o = self.o
        o.is_scoring_mode = True
        o.station_list = stations_abcd()
        o.bve_next_loc = o.prev_next_loc = 1000.0
        o.bve_location = 1000.0 - d
        o.bve_speed = 0.0
        o.is_first_udp = True
        o.is_first_station = True
        return o

    @st0("T20", "KNOWN-DEFECT-BEHAVIOR", items=(20,), note="DS02 (Phase ST-2c: inverted - it was: 'start station' is decided by 'NEXTLOC more than 100 m away', 100.001 m and -100.001 m cleared it): the first line clears nothing, whatever the distance")
    def test_CHAR_T20_is_first_station_is_not_cleared_by_the_distance_of_the_first_line(self):
        # (d, stays_first): before Phase ST-2c the last two rows of the old table, 100.001 and -100.001, were False; the contract tests are in test_stationindex_first_station_st2c.py
        for d, stays_first in ((99.999, True), (100.0, True), (100.001, True), (-100.001, True), (5000.0, True)):
            with self.subTest(d=d):
                self.rig.close()
                self.setUp()
                o = self.first_udp_scene(d)
                self.tick()
                self.assertEqual(o.is_first_station, stays_first)
                self.assertFalse(o.is_first_udp)

    @st0("T20", "CURRENT-BEHAVIOR-ONLY", items=(20,), note="without a NEXTLOC (-1.0) the first-line decision is postponed: is_first_udp stays set")
    def test_CHAR_T20_the_decision_waits_for_a_NEXTLOC(self):
        o = self.first_udp_scene(0.0)
        o.bve_next_loc = -1.0
        o.prev_next_loc = -1.0
        self.tick()
        self.assertTrue(o.is_first_udp)
        self.assertTrue(o.is_first_station)


# ==============================================================================================================================================
# T18 : the physical stop-error evaluation does not know a station identity
# ==============================================================================================================================================
class H_PhysicalEvaluation(Base):
    # (d in m, expected return value, expected score change): the score table and the range gate of apply_stop_score
    TABLE = ((0.0, True, 500), (0.004, True, 500), (0.01, False, 495), (0.5, False, 250), (1.0, False, 0), (1.01, False, 0), (5.0, False, 0), (5.01, False, 0), (-0.5, False, 250))

    def run_table(self, stations):
        out = []
        for d, _r, _s in self.TABLE:
            self.rig.close()
            self.setUp()
            o = self.o
            o.is_scoring_mode = True
            o.is_stopped_out_of_range = False
            o.bve_margin_b = o.bve_margin_f = 5.0
            o.station_list = stations
            o.score = 0
            ret = self.S.apply_stop_score(o, d, 100.0)
            out.append((d, ret, o.score))
        return out

    @st0("T18", "FUTURE-REPLACEMENT-TARGET", items=(10,), note="apply_stop_score(d) is a pure function of d, the margins and the scoring flags: this table must be identical after the identity is taken from the StationIndex")
    def test_CHAR_T18_the_stop_position_score_table(self):
        got = self.run_table(stations_abcd())
        self.assertEqual(got, [(d, r, s) for d, r, s in self.TABLE])

    @st0("T18", "FUTURE-REPLACEMENT-TARGET", items=(10,), note="the result does not depend on the station list at all (an empty list and the four-station list give the same table)")
    def test_CHAR_T18_the_result_does_not_depend_on_the_station_list(self):
        self.assertEqual(self.run_table([]), self.run_table(stations_abcd()))

    @st0("T18", "FUTURE-REPLACEMENT-TARGET", items=(10,), note="the signatures of the physical functions take no station identity: apply_stop_score(self, d_m, current_time)")
    def test_CHAR_T18_the_physical_functions_take_no_station_identity(self):
        self.assertEqual(list(inspect.signature(self.S.apply_stop_score).parameters), ["self", "d_m", "current_time"])
        self.assertEqual(list(inspect.signature(self.S.evaluate_arrival).parameters), ["self", "current_time", "arrival_target_loc"])
        self.assertEqual(list(inspect.signature(self.S.evaluate_departure).parameters), ["self", "current_time"])


# ==============================================================================================================================================
# item 18 : the identity of the target / arrival is a 1.0 m reverse lookup from NEXTLOC (lowest index wins)
# ==============================================================================================================================================
class I_IdentityByPosition(Base):
    def pair(self):
        return [sta("A", 0.0), sta("B1", 1000.0, is_timing=True), sta("B2", 1000.0, is_timing=False), sta("D", 3000.0, terminal=True)]

    @st0("T13", "KNOWN-DEFECT-BEHAVIOR", items=(18,), note="C-ID-6: for two stations at the same position the HUD next-station name and timing flag come from the LOWEST index, whichever is the real target")
    def test_CHAR_ITEM18_the_next_station_of_the_hud_is_the_lowest_index_at_that_position(self):
        o = self.scene(d=500.0, stations=self.pair(), end_idx=3)
        self.tick()
        self.assertEqual(o.active_next_sta_name, "B1")
        self.assertTrue(o.active_next_sta_timing)

    @st0("T13", "KNOWN-DEFECT-BEHAVIOR", items=(18,), note="C-ID-6: an arrival at the SECOND of two same-position stations is recognised as the first; the end-station test (setting_end_idx) cannot see B2")
    def test_CHAR_ITEM18_an_arrival_at_the_second_same_position_station_is_taken_for_the_first(self):
        o = self.scene(d=0.0, stations=self.pair(), end_idx=2)                                   # the scoring ends at B2 (idx 2)
        o.bve_current_station_name = "B2"
        self.tick()
        self.open_doors()
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertFalse(o.is_scoring_finished)                                                   # the lookup found B1 (idx 1): B2 is never recognised as the end
        self.assertEqual(self.arrivals(), 1)

    @st0("T13", "KNOWN-DEFECT-BEHAVIOR", items=(18,), note="the same arrival does end the scoring when the end station is the FIRST of the pair (idx 1)")
    def test_CHAR_ITEM18_the_first_of_the_pair_is_recognised_as_the_end_station(self):
        o = self.scene(d=0.0, stations=self.pair(), end_idx=1)
        self.tick()
        self.open_doors()
        self.assertTrue(o.is_scoring_finished)


# ==============================================================================================================================================
class Z_Meta(unittest.TestCase):
    """Every test of this file carries its ST-0 metadata."""

    @staticmethod
    def case_methods():
        for cls in (A_NormalStop, B_Tolerance, C_OperationalStop, D_PassStation, E_TelemetryInputs, F_Departure, G_FirstStation, H_PhysicalEvaluation, I_IdentityByPosition):
            for name in sorted(n for n in dir(cls) if n.startswith("test_")):
                yield cls, name, getattr(cls, name)

    def test_META_every_test_has_an_id_a_label_and_a_plan_id_of_the_audit(self):
        plan_ids = {"T13", "T14", "T15", "T16", "T17", "T18", "T19", "T20"}
        seen = 0
        for cls, name, fn in self.case_methods():
            meta = getattr(fn, "st0", None)
            self.assertIsNotNone(meta, "%s.%s has no st0 metadata" % (cls.__name__, name))
            self.assertIn(meta["label"], LABELS, name)
            self.assertIn(meta["id"], plan_ids, name)
            self.assertTrue(name.startswith("test_CHAR_"), name)
            self.assertGreaterEqual(len(meta["note"]), 20, name)
            seen += 1
        self.assertGreaterEqual(seen, 30)

    def test_META_the_labels_meant_to_change_are_never_called_requirements(self):
        for _cls, name, fn in self.case_methods():
            if "100_m_distance" in name or "lowest_index" in name:
                self.assertEqual(fn.st0["label"], "KNOWN-DEFECT-BEHAVIOR", name)


if __name__ == "__main__":
    unittest.main()
