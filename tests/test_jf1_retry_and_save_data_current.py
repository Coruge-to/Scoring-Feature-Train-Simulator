"""Phase JF-1 (file F1) - CHARACTERIZATION of execute_retry / create_save_data / the first checkpoint of the scoring start / the retry-to-arrival chains
(JF-0 v2 groups R, S and X01-X05). It pins what the production Python does TODAY, and nothing else.

THE NAMES MEAN (JF-0 v2 test specification, section 0.2 and section 1 rule 7):
    test_CURRENT_...          today's neutral behaviour
    test_CURRENT_DANGER_...   a behaviour that exists today and is KNOWN to be dangerous. Passing it does NOT mean the behaviour is safe or approved as a
                              contract. Every one of them carries four facts in its metadata (see jf0()): the JF-0 v2 id, what is dangerous, the phase that
                              turns it into its TARGET, and the condition under which this assertion is reversed or deleted.
    test_REACH_...            "can the product reach this state at all"; if it cannot, THAT is what is pinned (it is never deleted)
    test_TARGET_A_... / _B_   the future contract (TARGET-A = achievable with the Current DLL unchanged (J3), TARGET-B = needs the J3 limited release).
                              ALL of them are skipped in JF-1 (the skip reason names the contract id) and their expectations are written as the
                              contract states them, never weakened. A skip is never counted as a pass.

ISOLATION (the same seams as tests/sia_rig.py, which this file only uses): the REAL Overlay is built offscreen; the keyboard, the Win32 calls, the clock, the
QApplication, the timers, the dialog and write_desktop_log are recorders; the UDP socket is the stub of the rig, so UDP 54321 / 54322 are never bound or sent
to. In addition USERPROFILE / HOME point to an empty temporary folder for the whole module (a Desktop log can not reach the real Desktop even if a recorder
were missing) and the module asserts at its end that nothing was written there. Nothing is written anywhere else; no process is started.

Classification note: JF-0 v2 names these ids as dangerous: R08, R10, R23, S04, S09, S17, S19, X01, X04. This file ALSO labels R06, R07, R18 and R24 as
CURRENT_DANGER, because the TARGET text of JF-0 v2 for them (OD-4 "no automatic choice among several candidates", "state is changed before a refusable send")
is the reverse of what they do today. That is a JF-1 labelling decision, reported as such; it changes no expectation.
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

import jump_wire  # noqa: E402
import sia_rig as R  # noqa: E402

THIS_FILE = "F1"
# the JF-0 v2 ids this file is responsible for, and the ids that another JF-1 file (or an existing test) carries
OWN_IDS = (["R%02d" % n for n in range(1, 30) if n not in (5, 22, 27)] + ["R05a", "R05b", "R05c"] + ["S%02d" % n for n in range(1, 20)] + ["X%02d" % n for n in range(1, 6)])
DELEGATED = {"R22": "F2", "R27": "F2"}


# ----------------------------------------------------------------------------------------------------------------------------------------------
# metadata
def jf0(case_id, kind, danger=None, phase=None, flip=None):
    """Attach the JF-0 v2 metadata to a test method. kind: CURRENT | CURRENT_DANGER | REACH | TARGET."""
    def deco(fn):
        fn.jf0 = {"id": case_id, "kind": kind, "danger": danger, "phase": phase, "flip": flip}
        return fn
    return deco


def danger(case_id, what, phase, flip):
    return jf0(case_id, "CURRENT_DANGER", danger=what, phase=phase, flip=flip)


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-jf1-f1-")
    _TMP_HOME["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP_HOME["dir"].name        # no Desktop folder inside: even the real write_desktop_log could not write anything
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
        raise AssertionError("the JF-1 F1 module wrote into the redirected profile: %r" % (left,))


# ----------------------------------------------------------------------------------------------------------------------------------------------
# fixtures
def st(name, loc, def_time=-1, raw_dep=-1, stop_time=15000, terminal=False):
    d = R.station(name, loc, terminal=terminal)
    d.update(def_time=def_time, raw_dep=raw_dep, stop_time=stop_time)
    return d


def st0():
    """ST-0 of JF-0 v2 section 3: A idx0 @0, B idx1 @1000, C idx2 @2000, D idx3 @3000 (terminal); def_time -1, raw_dep -1, stop_time 15000."""
    return [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]


def cp(loc, t, score=0, details=None, name="X", target_loc=None, stop_error=0.0):
    d = {"loc": loc, "time_ms": t, "score": score, "target_loc": loc if target_loc is None else target_loc, "station_name": name, "stop_error": stop_error}
    if details is not None:
        d["score_details"] = dict(details)
    return d


ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
T0 = 36000000


def with_identity(checkpoint, index, location, count=4, role="arrived_station"):
    """Phase ST-2a: the four identity items a checkpoint carries now (station_index, scope, station_location, role), on top of the seven it always had."""
    checkpoint.update(station_index=index, scope=(R.SCOPE_SID, R.SCOPE_LIST_ID, count), station_location=location, role=role)
    return checkpoint


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["jf1-f1"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.log = self.rig.log
        self.events = []
        self.send_result = None
        self.send_exc = None
        o = self.o
        o.bve_time_ms = T0
        o.station_list = st0()
        o.toggle_menu = lambda adv: self.events.append(("toggle", adv, self.snap()))
        o.send_jump_command = self._send

    # recorders ------------------------------------------------------------------------------------------------------------------------------
    def snap(self):
        o = self.o
        return {"jumping": o.is_official_jumping, "exp_loc": o.expected_target_loc, "exp_time": o.expected_target_time, "pending": o.pending_jump_complete,
                "saves": len(o.save_data), "score": o.score}

    def _send(self, cmd):
        self.events.append(("send", cmd, self.snap()))
        if self.send_exc is not None:
            raise self.send_exc
        return self.send_result

    def sent(self):
        return [e[1] for e in self.events if e[0] == "send"]

    def v2(self, kind, index, time_ms):
        """Phase ST-3d: the Jump wire v2 text that the application writes for station `index` of the station list it holds NOW (its scope: scenario, list id, count; its position),
        written by the shared codec - the request that used to be the three-field 'JUMP_STA_TIME:<index>:<time>' / 'JUMP_LOC_TIME:<position>:<time>' text."""
        o = self.o
        text, why = jump_wire.format_request_v2(kind, index, time_ms, (o.current_scenario_id, o.bve_list_id, len(o.station_list)), o.station_list[index]["location"])
        self.assertIsNone(why)
        return text

    def retry(self, index, saves, stations=None, adv=True, identity=True):
        o = self.o
        o.save_data = saves
        if stations is not None:
            o.station_list = stations
        if identity:
            self.complete_identity(saves)
        self.S.execute_retry(o, index, adv)
        return self.sent()

    def complete_identity(self, saves):
        """Phase ST-2b FIXTURE (no expectation of any test depends on it): every checkpoint of ST-2a carries its identity (station_index, scope, station_location, role) and the
        retry verifies it, but the checkpoints these characterization tests write by hand (cp()) do not. A checkpoint without the identity gets it from the list: the ONE
        station at the position of the checkpoint (several stations there, or none: the old form is kept - the test supplies its own identity or is about a refusal), the role of
        its place, the scope of the list. The scope of the application is bound the way a sender would (scenario and list id only; the arrival / target indexes are left to
        arrive()). A test that needs the old form, or a refusal, passes identity=False."""
        o = self.o
        stations = list(getattr(o, "station_list", None) or [])
        if not getattr(o, "bve_list_id", ""):
            o.current_scenario_id = R.SCOPE_SID
            o.bve_list_id = R.SCOPE_LIST_ID
            self._scope_only = True
        for position, c in enumerate(saves):
            if not isinstance(c, dict) or "station_index" in c:
                continue
            here = [i for i, s in enumerate(stations) if abs(s["location"] - c["loc"]) <= 0.01]
            if len(here) == 1:
                with_identity(c, here[0], stations[here[0]]["location"], count=len(stations), role="scoring_start" if position == 0 else "arrived_station")

    def door_logs(self):
        return [m for m in self.log if m.startswith("[SAVE] 開扉時間を反映")]

    def arrive(self, next_loc, loc, prev_next_loc=None, t=T0 + 60000, name="B", is_pass=0, doordir=1, score=0, saves=None):
        """A scoring run with `saves` as check points, then one create_save_data call at an arrival."""
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.save_data = saves if saves is not None else [cp(0.0, T0, name="A")]
        o.bve_next_loc = next_loc
        o.prev_next_loc = next_loc if prev_next_loc is None else prev_next_loc
        o.bve_location = loc
        o.bve_time_ms = t
        o.bve_current_station_name = name
        o.bve_is_pass = is_pass
        o.bve_doordir = doordir
        o.score = score
        if not getattr(o, "bve_list_id", "") or getattr(self, "_scope_only", False):   # Phase ST-2a: a sender that names the station (a test that binds its own identity is left alone)
            R.bind_identity(o)                                                         # (Phase ST-2b: retry() binds the scope alone - the sender's indexes still follow here)
            self._scope_only = False
        self.S.create_save_data(o)
        return o.save_data


# ==============================================================================================================================================
# R - execute_retry
# ==============================================================================================================================================
class R_ExecuteRetry(Base):
    # -- R01 -----------------------------------------------------------------------------------------------------------------------------------
    @jf0("R01", "CURRENT")
    def test_CURRENT_R01_a_negative_index_returns_at_once_and_changes_nothing(self):
        o = self.o
        before = (o.is_official_retry, o.is_first_station, o.total_retry_count, o.has_departed, o.is_first_udp)
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 1000)]
        self.S.execute_retry(o, -1, True)
        self.assertEqual((o.is_official_retry, o.is_first_station, o.total_retry_count, o.has_departed, o.is_first_udp), before)
        self.assertEqual(len(o.save_data), 2)
        self.assertEqual(self.events, [])
        self.assertFalse(o.is_official_jumping)

    @jf0("R01", "CURRENT")
    def test_CURRENT_R01_an_index_equal_to_the_length_returns_at_once_and_changes_nothing(self):
        o = self.o
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 1000)]
        self.S.execute_retry(o, 2, True)
        self.assertEqual(len(o.save_data), 2)
        self.assertEqual(self.events, [])
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(o.rollback_msg, "")

    # -- R02 / R03 -----------------------------------------------------------------------------------------------------------------------------
    @jf0("R02", "CURRENT")
    def test_CURRENT_R02_retry_to_index_0_resets_the_retry_count_and_jumps_to_station_0(self):
        o = self.o
        o.total_retry_count = 5
        o.score = 123
        cmds = self.retry(0, [cp(0.0, T0, score=0, details=None, name="A"), cp(1000.0, T0 + 1000, score=50, details=ZERO, name="B")])
        self.assertFalse(o.is_official_retry)
        self.assertTrue(o.is_first_station)
        self.assertEqual(o.total_retry_count, 0)
        self.assertEqual(len(o.save_data), 2)                 # Phase ST-2b: the request does not cut the history (was 1: ST-3 cuts it after the matching completion)
        self.assertEqual(o.retry_pending.selected_save_position, 0)
        self.assertEqual(o.score, 0)
        self.assertEqual(cmds, [self.v2("STA", 0, T0)])
        self.assertEqual((o.expected_target_loc, o.expected_target_time), (0.0, T0))
        self.assertTrue(o.is_official_jumping)
        self.assertIsNone(o.pending_jump_complete)

    @jf0("R03", "CURRENT")
    def test_CURRENT_R03_retry_to_a_later_index_marks_a_retry_and_does_not_touch_the_retry_count_here(self):
        o = self.o
        o.total_retry_count = 3
        self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, score=10, details=ZERO, name="B")])
        self.assertTrue(o.is_official_retry)
        self.assertFalse(o.is_first_station)
        self.assertEqual(o.total_retry_count, 3)             # the +1 is the caller's (handle_menu_enter), see R26

    # -- R04 - R06 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("R04", "CURRENT")
    def test_CURRENT_R04_the_target_is_the_saved_station_index_and_its_own_location_is_expected_not_the_check_point_position(self):
        # Phase ST-2b: was "the station within 100 m of the check point position"; the output is the same, the reason is the saved StationIndex (no search at all)
        o = self.o
        cmds = self.retry(1, [cp(0.0, T0), with_identity(cp(1004.2, T0 + 60000, score=10, details=ZERO, name="B"), 1, 1000.0)])
        self.assertEqual(cmds, [self.v2("STA", 1, T0 + 60000)])
        self.assertEqual(o.expected_target_loc, 1000.0)       # the STATION position, not cp["loc"]

    @jf0("R05a", "CURRENT")
    def test_CURRENT_R05a_a_distance_of_99_999_m_between_the_check_point_and_its_station_decides_nothing(self):
        # Phase ST-2b: was "99.999 m is a candidate" (the 100 m search). The saved StationIndex is the station whatever the stop position was.
        o = self.o
        cmds = self.retry(1, [cp(0.0, T0), with_identity(cp(900.001, T0 + 60000, details=ZERO), 1, 1000.0)])
        self.assertEqual(cmds, [self.v2("STA", 1, T0 + 60000)])
        self.assertEqual(o.expected_target_loc, 1000.0)

    @jf0("R05b", "CURRENT")
    def test_CURRENT_R05b_a_distance_of_exactly_100_m_between_the_check_point_and_its_station_decides_nothing_either(self):
        # Phase ST-2b: was "exactly 100 m is no candidate on either side and lands in the station-0 fallback"; there is no boundary and no fallback now
        for loc in (900.0, 1100.0):
            with self.subTest(loc=loc):
                self.events.clear()
                cmds = self.retry(1, [cp(0.0, T0), with_identity(cp(loc, T0 + 60000, details=ZERO), 1, 1000.0)])
                self.assertEqual(cmds, [self.v2("STA", 1, T0 + 60000)])
                self.assertEqual(self.o.expected_target_loc, 1000.0)

    @jf0("R05c", "CURRENT")
    def test_CURRENT_R05c_a_distance_of_100_001_m_between_the_check_point_and_its_station_decides_nothing(self):
        # Phase ST-2b: was "100.001 m is no candidate" (station-0 fallback)
        o = self.o
        cmds = self.retry(1, [cp(0.0, T0), with_identity(cp(899.999, T0 + 60000, details=ZERO), 1, 1000.0)])
        self.assertEqual(cmds, [self.v2("STA", 1, T0 + 60000)])
        self.assertEqual(o.expected_target_loc, 1000.0)

    @jf0("R06", "CURRENT")
    def test_CURRENT_R06_the_saved_index_is_taken_not_the_lowest_index_and_not_the_nearest_station(self):
        # Phase ST-2b: was CURRENT_DANGER ("among several candidates the lowest index is taken": the jump went to B although C was meant); the danger is gone
        o = self.o
        stations = [st("A", 0.0), st("B", 1000.0), st("C", 1060.0), st("D", 3000.0, terminal=True)]
        cmds = self.retry(2, [cp(0.0, T0), cp(500.0, T0 + 1000), with_identity(cp(1050.0, T0 + 60000, details=ZERO, name="C"), 2, 1060.0)], stations)
        self.assertEqual(cmds, [self.v2("STA", 2, T0 + 60000)])                    # C was meant and C is used
        self.assertEqual(o.expected_target_loc, 1060.0)

    @jf0("R07", "CURRENT")
    def test_CURRENT_R07_a_retry_to_the_second_station_at_the_same_position_goes_to_the_second(self):
        # Phase ST-2b: was CURRENT_DANGER (B2 always went to B1); the saved StationIndex tells them apart
        o = self.o
        stations = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        cmds = self.retry(2, [cp(0.0, T0), cp(500.0, T0 + 1000), with_identity(cp(1000.0, T0 + 60000, details=ZERO, name="B2"), 2, 1000.0)], stations)
        self.assertEqual(cmds, [self.v2("STA", 2, T0 + 60000)])
        self.assertEqual(o.expected_target_loc, 1000.0)

    @jf0("R08", "CURRENT")
    def test_CURRENT_R08_a_check_point_whose_position_is_not_the_position_of_its_index_is_refused_and_never_sent_to_station_0(self):
        # Phase ST-2b: was CURRENT_DANGER ("no station within 100 m: the retry silently jumps to station 0"); there is no fallback now: a refusal that changes nothing
        o = self.o
        o.save_data = [cp(0.0, T0), with_identity(cp(1500.0, T0 + 60000, details=ZERO), 1, 1500.0)]      # the position of the check point is 500 m from the position of index 1
        self.complete_identity(o.save_data)
        result = self.S.execute_retry(o, 1, True)
        self.assertEqual((result.accepted, result.reason), (False, "location-mismatch"))
        self.assertEqual(self.sent(), [])
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len(o.save_data), 2)

    # -- R09 -------------------------------------------------------------------------------------------------------------------------------------
    @jf0("R09", "CURRENT")
    def test_CURRENT_R09_an_empty_station_list_is_refused_and_nothing_is_sent(self):
        # Phase ST-2b: was CURRENT_DANGER (the retry jumped to station 0 and expected the check point position)
        o = self.o
        cmds = self.retry(1, [cp(0.0, T0), cp(700.0, T0 + 60000, details=ZERO)], stations=[])
        self.assertEqual(cmds, [])
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len(o.save_data), 2)

    @jf0("R09", "CURRENT")
    def test_CURRENT_R09_a_missing_station_list_attribute_is_refused_like_an_empty_one(self):
        # Phase ST-2b: was CURRENT_DANGER (a jump to station 0 was sent)
        o = self.o
        del o.station_list
        self.assertFalse(hasattr(o, "station_list"))
        cmds = self.retry(1, [cp(0.0, T0), cp(700.0, T0 + 60000, details=ZERO)])
        self.assertEqual(cmds, [])
        self.assertFalse(o.is_official_jumping)

    # -- R10 -------------------------------------------------------------------------------------------------------------------------------------
    @jf0("R10", "CURRENT")
    def test_CURRENT_R10_the_initial_checkpoint_retry_uses_the_start_station_it_was_saved_with(self):
        # Phase ST-2b: was CURRENT_DANGER (the retry ignored the chosen start station and jumped to the nearer earlier station P); the first checkpoint carries the start index
        o = self.o
        o.setting_start_idx = 2
        stations = [st("A", 0.0), st("P", 950.0), st("Q", 1000.0), st("D", 3000.0, terminal=True)]
        cmds = self.retry(0, [with_identity(cp(1000.0, T0, name="Q"), 2, 1000.0, role="scoring_start")], stations)
        self.assertEqual(cmds, [self.v2("STA", 2, T0)])
        self.assertEqual(o.expected_target_loc, 1000.0)
        self.assertEqual(o.setting_start_idx, 2)

    # -- R11 - R14 : STA / LOC -----------------------------------------------------------------------------------------------------------------
    def _loc_station_list(self, def_time=40000000, raw_dep=39015000, **extra):
        b = st("B", 1000.0, def_time=def_time, raw_dep=raw_dep)
        b.update(extra)
        return [st("A", 0.0), b, st("C", 2000.0), st("D", 3000.0, terminal=True)]

    @jf0("R11", "CURRENT")
    def test_CURRENT_R11_index_0_is_never_a_LOC_jump_even_when_every_other_condition_holds(self):
        stations = [st("A", 0.0, def_time=40000000, raw_dep=39015000), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        self.assertEqual(self.retry(0, [cp(0.0, T0, name="A")], stations), [self.v2("STA", 0, T0)])

    @jf0("R12", "CURRENT")
    def test_CURRENT_R12_all_five_conditions_true_gives_a_LOC_jump_with_the_station_location(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO, name="B")], self._loc_station_list())
        self.assertEqual(cmds, [self.v2("LOC", 1, T0)])
        self.assertEqual(self.o.expected_target_loc, 1000.0)

    @jf0("R12", "CURRENT")
    def test_CURRENT_R12_def_time_below_zero_gives_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], self._loc_station_list(def_time=-1))
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R12", "CURRENT")
    def test_CURRENT_R12_calc_time_below_zero_because_raw_dep_is_missing_gives_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], self._loc_station_list(raw_dep=-1))
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R12", "CURRENT")
    def test_CURRENT_R12_def_time_not_later_than_calc_time_gives_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], self._loc_station_list(def_time=38000000))
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R12", "CURRENT")
    def test_CURRENT_R12_check_point_time_not_earlier_than_def_time_gives_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, 40000001, details=ZERO)], self._loc_station_list())
        self.assertEqual(cmds, [self.v2("STA", 1, 40000001)])

    @jf0("R12", "CURRENT")
    def test_CURRENT_R12_the_LOC_text_uses_the_float_string_of_the_station_location(self):
        stations = self._loc_station_list()
        stations[1]["location"] = 1000.5
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.5, T0, details=ZERO)], stations)
        self.assertEqual(cmds, [self.v2("LOC", 1, T0)])

    @jf0("R13", "CURRENT")
    def test_CURRENT_R13_check_point_time_equal_to_def_time_gives_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, 40000000, details=ZERO)], self._loc_station_list())
        self.assertEqual(cmds, [self.v2("STA", 1, 40000000)])

    @jf0("R13", "CURRENT")
    def test_CURRENT_R13_def_time_equal_to_calc_time_gives_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], self._loc_station_list(def_time=39000000))
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R13", "CURRENT")
    def test_CURRENT_R13_raw_dep_minus_1_gives_calc_time_minus_1_and_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], self._loc_station_list(raw_dep=-1))
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R13", "CURRENT")
    def test_CURRENT_R13_a_raw_dep_below_the_stop_time_gives_a_negative_calc_time_and_STA(self):
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], self._loc_station_list(raw_dep=10000))
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R13", "CURRENT")
    def test_CURRENT_R13_a_missing_stop_time_key_means_15000(self):
        stations = self._loc_station_list(def_time=39010000)         # calc 39000000 with 15000; with a different default it would not be earlier than def_time
        del stations[1]["stop_time"]
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], stations)
        self.assertEqual(cmds, [self.v2("LOC", 1, T0)])

    @jf0("R13", "CURRENT")
    def test_CURRENT_R13_a_missing_raw_dep_key_means_minus_1(self):
        stations = self._loc_station_list()
        del stations[1]["raw_dep"]
        cmds = self.retry(1, [cp(0.0, T0), cp(1000.0, T0, details=ZERO)], stations)
        self.assertEqual(cmds, [self.v2("STA", 1, T0)])

    @jf0("R14", "CURRENT")
    def test_CURRENT_R14_one_millisecond_before_def_time_is_LOC_and_def_time_itself_is_STA(self):
        stations = self._loc_station_list()
        self.assertEqual(self.retry(1, [cp(0.0, T0), cp(1000.0, 39999999, details=ZERO)], stations), [self.v2("LOC", 1, 39999999)])
        self.events.clear()
        self.assertEqual(self.retry(1, [cp(0.0, T0), cp(1000.0, 40000000, details=ZERO)], stations), [self.v2("STA", 1, 40000000)])

    # -- R15 - R17 : state restoration ---------------------------------------------------------------------------------------------------------
    @jf0("R15", "CURRENT")
    def test_CURRENT_R15_the_save_data_is_not_cut_by_the_request_it_is_the_same_list_with_all_its_items(self):
        # Phase ST-2b: was "the save_data is cut to a NEW list [A,B]"; the request keeps [A,B,C,D] (the cut is ST-3's, see station_identity.resolve_retry_history)
        o = self.o
        old = [cp(0.0, T0), cp(1000.0, T0 + 1, details=ZERO), cp(2000.0, T0 + 2, details=ZERO), cp(3000.0, T0 + 3, details=ZERO)]
        o.save_data = old
        self.complete_identity(old)
        self.S.execute_retry(o, 1, True)
        self.assertIs(o.save_data, old)
        self.assertEqual([c["time_ms"] for c in o.save_data], [T0, T0 + 1, T0 + 2, T0 + 3])
        self.assertIs(o.retry_pending.checkpoint, old[1])

    @jf0("R16", "CURRENT")
    def test_CURRENT_R16_score_and_a_COPY_of_the_details_are_restored(self):
        o = self.o
        details = dict(ZERO, eb=-300, time=1000)
        saved = cp(1000.0, T0 + 60000, score=700, details=details, name="B")
        self.retry(1, [cp(0.0, T0), saved])
        self.assertEqual(o.score, 700)
        self.assertEqual(o.score_details, details)
        self.assertIsNot(o.score_details, saved["score_details"])
        o.score_details["eb"] = -999
        self.assertEqual(saved["score_details"]["eb"], -300)

    @jf0("R17", "CURRENT")
    def test_CURRENT_R17_a_check_point_without_score_details_zeroes_the_current_details_in_place(self):
        """The initial check point never has score_details, so this is the ordinary path of every retry to index 0, not an old-data safeguard."""
        o = self.o
        o.score_details["eb"] = -500
        o.score_details["time"] = 100
        same_dict = o.score_details
        self.retry(0, [cp(0.0, T0, name="A")])
        self.assertIs(o.score_details, same_dict)
        self.assertEqual(o.score_details, ZERO)

    @danger("R18", "the ATS detail is forced to 0 on every retry (the ATS ignore penalty is unavailable) but the total score is NOT adjusted: score and details disagree",
            "JF-2 (TARGET-A: same behaviour plus a check that the details add up to the score)", "a consistency check is added; this assertion is replaced by it")
    def test_CURRENT_DANGER_R18_ats_is_zeroed_in_the_details_but_the_score_is_not_adjusted(self):
        import config
        o = self.o
        self.assertFalse(config.ATS_SIGNAL_IGNORE_AVAILABLE)           # the penalty is unavailable today: pen_ats can not make it effective
        o.pen_ats = True
        details = dict(ZERO, ats=-300, time=1000)
        self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, score=700, details=details, name="B")])
        self.assertEqual(o.score_details["ats"], 0)
        self.assertEqual(o.score, 700)
        self.assertNotEqual(sum(o.score_details.values()), o.score)

    # -- R19 - R21 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("R19", "CURRENT")
    def test_CURRENT_R19_the_order_is_toggle_menu_then_begin_official_jump_then_send(self):
        o = self.o
        o.is_official_jumping = False
        self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO, name="B")])
        self.assertEqual([e[0] for e in self.events], ["toggle", "send"])
        toggle, send = self.events
        self.assertFalse(toggle[2]["jumping"])                       # the menu closes BEFORE the official jump state is begun ...
        self.assertTrue(send[2]["jumping"])                          # ... and the state is complete BEFORE the command leaves
        self.assertEqual((send[2]["exp_loc"], send[2]["exp_time"]), (1000.0, T0 + 60000))
        self.assertIsNone(send[2]["pending"])

    @jf0("R20", "CURRENT")
    def test_CURRENT_R20_begin_official_jump_clears_transient_state_but_keeps_warning_popups_and_the_restored_score(self):
        o = self.o
        o.popups = [{"text": "w", "category": "警告"}, {"text": "r", "category": "転動"}]
        o.g_history.append((0.0, 1.0))
        o.pending_jump_complete = {"type": "STA"}
        self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, score=420, details=ZERO, name="B")])
        self.assertEqual([p["category"] for p in o.popups], ["警告"])
        self.assertEqual(list(o.g_history), [])
        self.assertIsNone(o.pending_jump_complete)
        self.assertEqual(o.score, 420)

    @jf0("R21", "CURRENT")
    def test_CURRENT_R21_rollback_message_flags_and_timer(self):
        o = self.o
        o.has_departed = True
        o.is_first_udp = False
        o.bve_time_ms = 36123000
        self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO, name="B")])
        self.assertEqual(o.rollback_msg, ">>> B へロールバック完了 <<<")
        self.assertEqual(o.rollback_msg_timer, 36123.0 + 5.0)
        self.assertFalse(o.has_departed)
        self.assertTrue(o.is_first_udp)

    # -- R23 / R24 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("R23", "CURRENT")
    def test_CURRENT_R23_normal_mode_send_failure_is_released_at_the_deadline(self):
        """Phase ST-3d: was CURRENT_DANGER (a failed UDP write (-1) is ignored and the normal mode has no client and no timeout, so the scoring waited for ever). The open transaction of
        the normal mode has the same 10 s deadline as the managed one: nothing is sent, nothing completes, and the jump is released with the scoring abort."""
        o = self.o
        del o.send_jump_command                                      # the REAL send_jump_command (the class method) with the rig's stub socket
        attempts = []
        o.udp_socket.writeDatagram = lambda data, address, port: attempts.append((bytes(data), port)) or -1
        self.assertFalse(o.dataplane_strict)
        self.assertIsNone(o.jump_client)
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO, name="B")]
        self.complete_identity(o.save_data)
        self.S.execute_retry(o, 1, True)                              # no exception although the write failed
        self.assertEqual(attempts, [(self.v2("STA", 1, T0 + 60000).encode("ascii"), 54322)])
        self.assertTrue(o.is_official_jumping)
        self.rig.advance(3600.0)                                      # an hour later ...
        o._poll_jump_client()
        self.assertFalse(o.is_official_jumping)                       # ... the deadline has ended it
        self.assertIsNone(o.retry_pending)

    @danger("R24", "when the send raises, the state is ALREADY changed (score restored, official jump begun; Phase ST-2b: the check points are no longer cut) and nothing is rolled back; the exception reaches the caller",
            "JF-2 (TARGET-A FC-1 / RT-1: validate first, an explicit abort on a send exception)", "this assertion is replaced by TARGET_A_R24")
    def test_CURRENT_DANGER_R24_a_raising_send_leaves_the_changed_state_and_the_caller_does_not_count_the_retry(self):
        o = self.o
        self.send_exc = RuntimeError("socket gone")
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, score=300, details=ZERO, name="B"), cp(2000.0, T0 + 120000, score=450, details=ZERO, name="C")]
        self.complete_identity(o.save_data)
        o.menu_state = 3
        o.menu_cursor = 0
        o.target_retry_idx = 1
        o.total_retry_count = 2
        with self.assertRaises(RuntimeError):
            o.handle_menu_enter(True)
        self.assertEqual(len(o.save_data), 3)                         # Phase ST-2b: NOT cut (was 2)
        self.assertEqual(o.score, 300)                                # restored
        self.assertTrue(o.is_official_jumping)                        # begun and never released
        self.assertEqual(o.total_retry_count, 2)                      # the caller's +1 was skipped by the exception

    @jf0("R25", "CURRENT")
    def test_CURRENT_R25_toggle_menu_receives_the_is_bve_advancing_value_unchanged(self):
        for adv in (True, False):
            with self.subTest(adv=adv):
                self.events.clear()
                self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO)], adv=adv)
                self.assertEqual([e[1] for e in self.events if e[0] == "toggle"], [adv])

    @jf0("R26", "CURRENT")
    def test_CURRENT_R26_the_menu_route_adds_one_retry_for_a_later_index_and_none_for_index_0(self):
        o = self.o
        o.menu_state = 3
        o.menu_cursor = 0
        o.target_retry_idx = 2
        o.total_retry_count = 1
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO), cp(2000.0, T0 + 120000, details=ZERO)]
        self.complete_identity(o.save_data)
        o.handle_menu_enter(True)
        self.assertEqual(o.total_retry_count, 2)
        self.assertTrue(o.was_advancing_before_menu)
        self.assertEqual(self.sent(), [self.v2("STA", 2, T0 + 120000)])
        o.menu_state = 3
        o.menu_cursor = 0
        o.target_retry_idx = 0
        o.total_retry_count = 4
        o.is_official_jumping = False                                 # (Phase ST-2b: the first jump is over; a retry that is pending refuses a second one)
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO)]
        self.complete_identity(o.save_data)
        o.handle_menu_enter(True)
        self.assertEqual(o.total_retry_count, 0)                      # reset inside execute_retry, not incremented

    # -- TARGET (skipped) ------------------------------------------------------------------------------------------------------------------------
    @unittest.skip("TARGET-A RT-3 / CP-2 (JF-2): the retry uses the saved station_index and no 100 m search")
    @jf0("R04", "TARGET")
    def test_TARGET_A_R04_the_saved_station_index_is_used_and_not_a_search_from_the_check_point_position(self):
        o = self.o
        saved = cp(1004.2, T0 + 60000, details=ZERO, name="B")
        saved.update(station_index=1, station_location=1000.0)
        cmds = self.retry(1, [cp(0.0, T0), saved])
        self.assertEqual(cmds, [self.v2("STA", 1, T0 + 60000)])
        self.assertEqual(o.expected_target_loc, 1000.0)

    @unittest.skip("TARGET-A RT-3 / CP-2 (JF-2) and TARGET-B B2 (JF-3): a retry to B2 uses the saved index 2, not B1")
    @jf0("R07", "TARGET")
    def test_TARGET_A_R07_the_saved_index_2_is_used_for_the_second_of_two_stations_at_the_same_position(self):
        stations = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        saved = cp(1000.0, T0 + 60000, details=ZERO, name="B2")
        saved.update(station_index=2, station_location=1000.0)
        self.assertEqual(self.retry(2, [cp(0.0, T0), cp(500.0, T0 + 1000), saved], stations), [self.v2("STA", 2, T0 + 60000)])

    @unittest.skip("TARGET-A V-R3 (JF-2): a check point position with no station is refused, no command, no state change")
    @jf0("R08", "TARGET")
    def test_TARGET_A_R08_the_zero_candidate_case_is_refused_without_a_command_or_a_state_change(self):
        o = self.o
        saves = [cp(0.0, T0), cp(1500.0, T0 + 60000, score=77, details=ZERO)]
        self.assertEqual(self.retry(1, saves), [])
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len(o.save_data), 2)
        self.assertEqual(o.score, 0)

    @unittest.skip("TARGET-A V-R2 (JF-2): an empty or missing station list is refused, no command, no state change")
    @jf0("R09", "TARGET")
    def test_TARGET_A_R09_an_empty_station_list_is_refused_without_a_command_or_a_state_change(self):
        o = self.o
        self.assertEqual(self.retry(1, [cp(0.0, T0), cp(700.0, T0 + 60000, details=ZERO)], stations=[]), [])
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len(o.save_data), 2)

    @unittest.skip("TARGET-A CP-1 (JF-2): the initial check point stores station_index = setting_start_idx and the retry jumps there")
    @jf0("R10", "TARGET")
    def test_TARGET_A_R10_the_initial_checkpoint_retry_jumps_to_the_chosen_start_station(self):
        o = self.o
        o.setting_start_idx = 2
        stations = [st("A", 0.0), st("P", 950.0), st("Q", 1000.0), st("D", 3000.0, terminal=True)]
        initial = cp(1000.0, T0, name="Q")
        initial.update(station_index=2, station_location=1000.0)
        self.assertEqual(self.retry(0, [initial], stations), [self.v2("STA", 2, T0)])
        self.assertEqual(o.expected_target_loc, 1000.0)

    @unittest.skip("TARGET-A FC-1 / RT-1 (JF-2): a send exception is not propagated; the official jump is aborted explicitly")
    @jf0("R24", "TARGET")
    def test_TARGET_A_R24_a_send_exception_aborts_the_official_jump_explicitly_and_does_not_propagate(self):
        o = self.o
        self.send_exc = RuntimeError("socket gone")
        o.is_scoring_mode = True
        self.retry(1, [cp(0.0, T0), cp(1000.0, T0 + 60000, score=300, details=ZERO, name="B")])      # must not raise
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        self.assertFalse(o.is_scoring_mode)

    @unittest.skip("TARGET-A V-4 (JF-2): a target with a same-position earlier station is refused in advance (reason ambiguous-target); TARGET-B: not refused")
    @jf0("R28", "TARGET")
    def test_TARGET_A_R28_a_retry_to_a_target_with_a_same_position_earlier_station_is_refused_without_a_state_change(self):
        o = self.o
        stations = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        saved = cp(1000.0, T0 + 60000, score=55, details=ZERO, name="B2")
        saved.update(station_index=2, station_location=1000.0)
        self.assertEqual(self.retry(2, [cp(0.0, T0), cp(500.0, T0 + 1000), saved], stations), [])
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len(o.save_data), 3)
        self.assertEqual(o.score, 0)

    @unittest.skip("TARGET-A V-4 extended (JF-2): a target with an earlier station within 50 m behind it is refused in advance (boundary 950.0 included, 949.99 not)")
    @jf0("R29", "TARGET")
    def test_TARGET_A_R29_a_retry_to_a_target_with_an_earlier_station_within_50_m_is_refused_boundary_included(self):
        o = self.o
        for j_loc, refused in ((960.0, True), (950.0, True), (949.99, False)):
            with self.subTest(j_loc=j_loc):
                self.events.clear()
                o.is_official_jumping = False
                stations = [st("A", 0.0), st("J", j_loc), st("T", 1000.0), st("D", 3000.0, terminal=True)]
                saved = cp(1000.0, T0 + 60000, details=ZERO, name="T")
                saved.update(station_index=2, station_location=1000.0)
                cmds = self.retry(2, [cp(0.0, T0), cp(500.0, T0 + 1000), saved], stations)
                self.assertEqual(cmds == [], refused)


# ==============================================================================================================================================
# S - create_save_data and the initial check point
# ==============================================================================================================================================
class S_SaveData(Base):
    def _start_through_the_menu(self, start_idx):
        o = self.o
        if not getattr(o, "bve_list_id", ""):                                   # Phase ST-2a: a sender that supplies the identity (the start is refused without it)
            R.bind_identity(o)
        o.setting_start_idx = start_idx
        o.menu_state = 10
        o.menu_cursor = 1
        order = []
        original = self.main.begin_official_jump

        def spy(overlay, loc, t):
            order.append(("begin", len(overlay.save_data)))
            return original(overlay, loc, t)
        self.main.begin_official_jump = spy
        self.addCleanup(setattr, self.main, "begin_official_jump", original)
        o.handle_menu_enter(True)
        return order

    # -- S01 -------------------------------------------------------------------------------------------------------------------------------------
    @jf0("S01", "CURRENT")
    def test_CURRENT_S01_the_initial_checkpoint_for_the_first_station(self):
        o = self.o
        order = self._start_through_the_menu(0)
        # Phase ST-2a (inverted: was the seven fields without a station_index): the first checkpoint carries the verified identity of the start station on top of them
        self.assertEqual(o.save_data, [{"loc": 0.0, "time_ms": T0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0,
                                        "station_index": 0, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, 4), "station_location": 0.0, "role": "scoring_start"}])
        self.assertNotIn("score_details", o.save_data[0])
        self.assertNotIn("scenario_generation", o.save_data[0])
        self.assertEqual(order, [("begin", 0)])                       # begin_official_jump runs BEFORE the check point is appended ...
        self.assertEqual(self.sent(), [self.v2("STA", 0, T0)])
        self.assertEqual(self.events[-1][2]["saves"], 1)              # ... and the command leaves AFTER it
        self.assertTrue(self.events[-1][2]["jumping"])

    @jf0("S01", "CURRENT")
    def test_CURRENT_S01_the_initial_checkpoint_for_a_later_start_station_carries_its_station_index(self):
        o = self.o
        self._start_through_the_menu(2)
        # Phase ST-2a (inverted: was "has no station_index either")
        self.assertEqual(o.save_data, [{"loc": 2000.0, "time_ms": T0, "score": 0, "target_loc": 2000.0, "station_name": "C", "stop_error": 0.0,
                                        "station_index": 2, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, 4), "station_location": 2000.0, "role": "scoring_start"}])
        self.assertEqual(self.sent(), [self.v2("STA", 2, T0)])

    # -- S02 / S03 / S04 -------------------------------------------------------------------------------------------------------------------------
    @jf0("S02", "CURRENT")
    def test_CURRENT_S02_a_normal_checkpoint_has_exactly_these_eleven_fields(self):
        o = self.o
        o.score_details["eb"] = -100
        saves = self.arrive(1000.0, 996.5, t=T0 + 60000, name="B", is_pass=1, score=300)
        self.assertEqual(len(saves), 2)
        new = saves[-1]
        # Phase ST-2a (inverted: was exactly the seven fields): the seven keep their meaning, the four of the identity are added
        self.assertEqual(set(new), {"loc", "time_ms", "score", "score_details", "target_loc", "station_name", "stop_error", "station_index", "scope", "station_location", "role"})
        self.assertEqual((new["station_index"], new["scope"], new["station_location"], new["role"]), (1, (R.SCOPE_SID, R.SCOPE_LIST_ID, 4), 1000.0, "arrived_station"))
        self.assertEqual((new["loc"], new["time_ms"], new["score"], new["target_loc"], new["station_name"], new["stop_error"]), (996.5, T0 + 60000, 300, 1000.0, "B", 3.5))
        self.assertEqual(new["score_details"], o.score_details)
        self.assertIsNot(new["score_details"], o.score_details)

    @jf0("S03", "CURRENT")
    def test_CURRENT_S03_the_same_next_location_twice_gives_one_checkpoint(self):
        self.arrive(1000.0, 999.0, is_pass=1)
        saves = self.arrive(1000.0, 999.0, is_pass=1, saves=self.o.save_data)
        self.assertEqual(len(saves), 2)

    @jf0("S03", "CURRENT")
    def test_CURRENT_S03_the_comparison_is_by_scope_and_station_index_not_a_float(self):
        self.arrive(1000.0, 999.0, is_pass=1)
        saves = self.arrive(1000.0000001, 999.0, is_pass=1, saves=self.o.save_data)
        self.assertEqual(len(saves), 2)                                # Phase ST-2a (inverted: was 3, the float position decided): the same StationIndex is the same checkpoint

    @danger("S04", "the second of two stations at the SAME position is silently dropped: no checkpoint, no log line, no counter",
            "JF-2 (TARGET-A S6: refused with a reason log) / JF-3 (TARGET-B: a separate checkpoint per station_index)", "this assertion is replaced by TARGET_A_S04 / TARGET_B_S04")
    def test_CURRENT_DANGER_S04_same_position_second_station_gets_its_own_checkpoint(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        self.arrive(1000.0, 999.0, name="B1", is_pass=1)
        o.bve_arr_idx = o.bve_tgt_idx = 2                             # Phase ST-2a (inverted: was "silently dropped"): the sender names the second station of the pair
        saves = self.arrive(1000.0, 999.0, name="B2", is_pass=1, saves=o.save_data)           # the arrival at B2: NEXTLOC did not change
        self.assertEqual([c["station_name"] for c in saves], ["A", "B1", "B2"])
        self.assertEqual([c.get("station_index") for c in saves[1:]], [1, 2])

    # -- S05 / S06 : the 1.0 m station search -----------------------------------------------------------------------------------------------------
    @jf0("S05", "CURRENT")
    def test_CURRENT_S05_no_named_station_creates_no_checkpoint_and_adds_no_door_time(self):
        saves = self.arrive(500.0, 499.0)                                   # no station at 500: the sender names none (arrival index -1)
        self.assertEqual(len(saves), 1)                                     # Phase ST-2a (inverted: was a checkpoint with the plain time): no identity, no checkpoint
        self.assertEqual(self.door_logs(), [])

    @jf0("S05", "CURRENT")
    def test_CURRENT_S05_one_candidate_uses_that_station_and_its_name_is_logged(self):
        self.o.bve_door_close_time_ms = 4630
        saves = self.arrive(1000.0, 999.0)
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000 + 4630)
        self.assertEqual(len(self.door_logs()), 1)
        self.assertIn("Bにて 4630ms", self.door_logs()[0])

    @jf0("S05", "CURRENT")
    def test_CURRENT_S05_several_candidates_use_the_attributes_of_the_station_the_checkpoint_names(self):
        o = self.o
        o.bve_door_close_time_ms = 4630
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0, def_time=99999999), st("D", 3000.0, terminal=True)]
        R.bind_identity(o, arr_idx=2)                                       # Phase ST-2a (inverted: the lowest index of a position search decided): the sender names B2
        o.bve_next_loc = 1000.0
        saves = self.arrive(1000.0, 999.0, name="B2")                       # B2 does NOT add (def_time later than now)
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000)
        self.assertEqual(self.door_logs(), [])
        self.assertEqual((saves[-1]["station_name"], saves[-1]["station_index"]), ("B2", 2))

    @jf0("S06", "CURRENT")
    def test_CURRENT_S06_the_position_must_agree_with_the_named_station_within_0_01_m(self):
        for p_loc, found in ((1000.009, True), (1000.011, False), (1001.0, False)):
            with self.subTest(p_loc=p_loc):
                self.log.clear()
                self.o.bve_door_close_time_ms = 4630
                self.o.save_data = [cp(0.0, T0, name="A")]
                R.bind_identity(self.o, arr_idx=1)                          # Phase ST-2a (inverted: the 1.0 m search of the door-time station): the sender names station B
                self.arrive(p_loc, 999.0, prev_next_loc=p_loc)
                self.assertEqual(len(self.door_logs()), 1 if found else 0)
                self.assertEqual(len(self.o.save_data), 2 if found else 1)

    # -- S07 / S08 -------------------------------------------------------------------------------------------------------------------------------
    def _door_station(self, raw_dep=-1, def_time=-1):
        self.o.station_list = [st("A", 0.0), st("B", 1000.0, def_time=def_time, raw_dep=raw_dep), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        self.o.bve_door_close_time_ms = 4630

    @jf0("S07", "CURRENT")
    def test_CURRENT_S07_with_all_preconditions_the_door_time_is_added(self):
        self._door_station()
        self.assertEqual(self.arrive(1000.0, 999.0)[-1]["time_ms"], T0 + 60000 + 4630)

    @jf0("S07", "CURRENT")
    def test_CURRENT_S07_the_very_first_checkpoint_of_an_empty_save_data_gets_no_door_time(self):
        self._door_station()
        saves = self.arrive(1000.0, 999.0, saves=[])
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["time_ms"], T0 + 60000)
        self.assertEqual(self.door_logs(), [])

    @jf0("S07", "CURRENT")
    def test_CURRENT_S07_a_passing_station_gets_no_door_time(self):
        self._door_station()
        self.assertEqual(self.arrive(1000.0, 999.0, is_pass=1)[-1]["time_ms"], T0 + 60000)

    @jf0("S07", "CURRENT")
    def test_CURRENT_S07_an_operating_stop_with_doordir_0_gets_no_door_time(self):
        self._door_station()
        self.assertEqual(self.arrive(1000.0, 999.0, doordir=0)[-1]["time_ms"], T0 + 60000)

    @jf0("S08", "CURRENT")
    def test_CURRENT_S08_late_by_calc_time_and_no_def_time_adds_and_logs_the_text(self):
        self._door_station(raw_dep=T0 + 15000)                              # calc_t = T0; now = T0 + 60000 > calc_t
        saves = self.arrive(1000.0, 999.0)
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000 + 4630)
        self.assertEqual(self.door_logs(), ["[SAVE] 開扉時間を反映: Bにて 4630ms をセーブデータ時刻に加算"])

    @jf0("S08", "CURRENT")
    def test_CURRENT_S08_not_late_because_now_is_before_calc_time_adds_nothing(self):
        self._door_station(raw_dep=T0 + 200000 + 15000)
        self.assertEqual(self.arrive(1000.0, 999.0)[-1]["time_ms"], T0 + 60000)

    @jf0("S08", "CURRENT")
    def test_CURRENT_S08_now_equal_to_calc_time_is_not_late(self):
        self._door_station(raw_dep=T0 + 60000 + 15000)
        self.assertEqual(self.arrive(1000.0, 999.0)[-1]["time_ms"], T0 + 60000)

    @jf0("S08", "CURRENT")
    def test_CURRENT_S08_a_missing_calc_time_counts_as_late(self):
        self._door_station(raw_dep=-1)
        self.assertEqual(self.arrive(1000.0, 999.0)[-1]["time_ms"], T0 + 60000 + 4630)

    @jf0("S08", "CURRENT")
    def test_CURRENT_S08_now_equal_to_def_time_predicts_STA_and_adds(self):
        self._door_station(def_time=T0 + 60000)
        self.assertEqual(self.arrive(1000.0, 999.0)[-1]["time_ms"], T0 + 60000 + 4630)

    @jf0("S08", "CURRENT")
    def test_CURRENT_S08_now_before_def_time_predicts_LOC_and_adds_nothing(self):
        self._door_station(raw_dep=T0 + 15000, def_time=T0 + 100000)
        self.assertEqual(self.arrive(1000.0, 999.0)[-1]["time_ms"], T0 + 60000)

    @danger("S09", "on the Legacy host DOORTIME is never sent: the door time is 0, the time-gain protection does not work, and the log still says that 0 ms were added",
            "JF-2/JF-3 (U-7: show 'unknown' instead of 0) - a decision of the owner", "the missing value is shown as unknown; this assertion is replaced")
    def test_CURRENT_DANGER_S09_legacy_door_time_missing_gives_zero_correction(self):
        o = self.o
        self.assertFalse(hasattr(o, "bve_door_close_time_ms"))
        self._door_station()
        del o.bve_door_close_time_ms
        saves = self.arrive(1000.0, 999.0)
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000)
        self.assertEqual(self.door_logs(), ["[SAVE] 開扉時間を反映: Bにて 0ms をセーブデータ時刻に加算"])

    # -- S10 - S14 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("S10", "CURRENT")
    def test_CURRENT_S10_after_a_retry_the_same_station_is_not_saved_again_but_the_next_one_is(self):
        o = self.o
        self.retry(1, [with_identity(cp(0.0, T0, name="A"), 0, 0.0, role="scoring_start"),
                       with_identity(cp(996.0, T0 + 60000, details=ZERO, name="B", target_loc=1000.0), 1, 1000.0),
                       with_identity(cp(1996.0, T0 + 120000, details=ZERO, name="C", target_loc=2000.0), 2, 2000.0)])
        import station_identity
        self.assertEqual(len(o.save_data), 3)                              # Phase ST-2b: the request does not cut (was 2) ...
        # ... ST-3 cuts after the matching completion, before any arrival is judged. Phase ST-3d: the real cut is the success branch of the MANAGED settlement (tests/test_stationindex_python_st3d.py,
        # N-39 / N-45 / N-73: the history is cut when the RequestId-proven completion arrives and before the first arrival); this normal-mode characterization applies the same pure rule by hand
        # (the normal mode is not a formal transaction and never cuts)
        o.save_data = station_identity.resolve_retry_history(o.save_data, o.retry_pending, R.SCOPE_SID, R.SCOPE_LIST_ID, o.station_list)
        self.assertEqual(len(o.save_data), 2)
        o.is_scoring_mode = True
        o.bve_next_loc, o.prev_next_loc, o.bve_location, o.bve_is_pass = 1000.0, 1000.0, 996.0, 1
        R.bind_identity(o)                                                  # (Phase ST-2a: the sender names station B)
        self.S.create_save_data(o)
        self.assertEqual(len(o.save_data), 2)                              # the retry station: not saved again
        o.bve_next_loc, o.prev_next_loc, o.bve_location = 2000.0, 2000.0, 1996.0
        R.bind_identity(o)                                                  # (... and then station C)
        self.S.create_save_data(o)
        self.assertEqual(len(o.save_data), 3)

    @jf0("S11", "CURRENT")
    def test_CURRENT_S11_nothing_is_saved_when_not_scoring_or_when_finished(self):
        o = self.o
        o.is_scoring_mode = False
        o.save_data = [cp(0.0, T0)]
        o.bve_next_loc = 1000.0
        self.S.create_save_data(o)
        self.assertEqual(len(o.save_data), 1)
        o.is_scoring_mode, o.is_scoring_finished = True, True
        self.S.create_save_data(o)
        self.assertEqual(len(o.save_data), 1)

    @jf0("S12", "CURRENT")
    def test_CURRENT_S12_the_end_station_arrival_creates_no_checkpoint_and_finishes_the_scoring(self):
        o = self.o
        o.is_scoring_mode = True
        o.is_first_station = True
        o.setting_end_idx = 1
        o.save_data = [cp(0.0, T0)]
        o.prev_next_loc = o.bve_next_loc = 1000.0
        o.bve_location = 1000.0
        o.bve_tgt_idx = 1                                   # Phase SI-R5.2-B: the end station is the one the sender names as the target (no 1 m search from the position)
        self.S.evaluate_arrival(o, 50.0)
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(len(o.save_data), 1)

    @jf0("S12", "CURRENT")
    def test_CURRENT_S12_a_jump_lock_blocks_the_checkpoint(self):
        o = self.o
        o.is_scoring_mode = True
        o.is_first_station = True
        o.jump_lock = True
        o.setting_end_idx = 3
        o.save_data = [cp(0.0, T0)]
        o.prev_next_loc = o.bve_next_loc = 1000.0
        o.bve_location = 999.0
        self.S.evaluate_arrival(o, 50.0)
        self.assertEqual(len(o.save_data), 1)

    @jf0("S12", "CURRENT")
    def test_CURRENT_S12_without_end_station_and_lock_the_arrival_creates_the_checkpoint(self):
        o = self.o
        o.is_scoring_mode = True
        o.is_first_station = True
        o.setting_end_idx = 3
        o.save_data = [cp(0.0, T0)]
        o.prev_next_loc = o.bve_next_loc = 1000.0
        o.bve_location = 999.0
        o.bve_is_pass = 1
        R.bind_identity(o)                                                  # (Phase ST-2a: the sender names station B)
        self.S.evaluate_arrival(o, 50.0)
        self.assertEqual(len(o.save_data), 2)

    @jf0("S13", "CURRENT")
    def test_CURRENT_S13_the_saved_target_and_the_door_time_station_are_the_checkpoints_station(self):
        """JF-0 v2 section 4, S13: in a frame where bve_next_loc and prev_next_loc differ, the saved checkpoint and the door time referred to different stations.
        Phase ST-2a (inverted): both refer to the station the checkpoint names (the StationIndex), whatever prev_next_loc is."""
        o = self.o
        o.bve_door_close_time_ms = 4630
        saves = self.arrive(2000.0, 1999.0, prev_next_loc=1000.0, name="C")
        self.assertEqual(saves[-1]["target_loc"], 2000.0)
        self.assertEqual(saves[-1]["station_name"], "C")
        self.assertEqual(len(self.door_logs()), 1)
        self.assertIn("Cにて", self.door_logs()[0])                        # the door time is taken from station C (2000), the checkpoint's own station

    @jf0("S14", "CURRENT")
    def test_CURRENT_S14_score_details_are_a_copy_and_a_missing_name_is_the_default_name(self):
        o = self.o
        saves = self.arrive(1000.0, 999.0, is_pass=1)
        o.score_details["eb"] = -777
        self.assertEqual(saves[-1]["score_details"]["eb"], 0)
        del o.bve_current_station_name
        o.bve_next_loc = 2000.0
        R.bind_identity(o)                                                  # (Phase ST-2a: the sender names station C now)
        self.S.create_save_data(o)
        self.assertEqual(o.save_data[-1]["station_name"], "不明な駅")

    # -- S15 (REACH) -----------------------------------------------------------------------------------------------------------------------------
    @jf0("S15", "REACH")
    def test_REACH_S15_the_only_product_assignment_of_is_scoring_mode_true_is_the_scoring_start_in_main_py(self):
        """Pins that the empty-save_data branch can not be reached through a second assignment. NOT a proof of reachability by itself (see the next two)."""
        hits = {}
        for name in sorted(n for n in os.listdir(ROOT) if n.endswith(".py")):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                code = re.sub(r"#.*", "", f.read())
            n = len(re.findall(r"\bis_scoring_mode\s*=\s*True\b", code))
            if n:
                hits[name] = n
        self.assertEqual(hits, {"main.py": 1})

    @jf0("S15", "REACH")
    def test_REACH_S15_after_a_generation_discard_scoring_is_off_and_create_save_data_returns_at_once(self):
        import managed_input
        o = self.o
        o.is_scoring_mode = True
        o.save_data = [cp(0.0, T0)]
        managed_input.discard_generation_state(o)
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(o.save_data, [])
        o.bve_next_loc = 1000.0
        self.S.create_save_data(o)
        self.assertEqual(o.save_data, [])

    @jf0("S15", "REACH")
    def test_REACH_S15_called_directly_with_an_empty_list_while_scoring_the_function_creates_a_first_checkpoint_without_door_time(self):
        """Function-level behaviour only: it proves the branch exists, NOT that the product can get there (the two tests above are the reachability evidence)."""
        saves = self.arrive(1000.0, 999.0, saves=[])
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0]["time_ms"], T0 + 60000)

    @jf0("S16", "CURRENT")
    def test_CURRENT_S16_the_station_name_is_what_the_sender_says_and_nothing_checks_it_against_the_index(self):
        """The name of a checkpoint is bve_current_station_name (STATNAME) as it is; no code compares it with the station list."""
        o = self.o
        saves = self.arrive(1000.0, 999.0, name="NOT-A-STATION-NAME", is_pass=1)
        self.assertEqual(saves[-1]["station_name"], "NOT-A-STATION-NAME")

    # -- S17 -------------------------------------------------------------------------------------------------------------------------------------
    @danger("S17", "a start station index outside the list is not refused: the official jump state is begun, no command is sent, so nothing can ever end it",
            "JF-2 (TARGET-A V-3: refuse the start, do not call begin_official_jump)", "this assertion is replaced by TARGET_A_S17")
    def test_CURRENT_DANGER_S17_start_with_out_of_range_start_index_is_refused_without_a_command(self):
        for idx in (9, -1):
            with self.subTest(idx=idx):
                self.events.clear()
                o = self.o
                o.is_official_jumping = False
                self._start_through_the_menu(idx)
                # Phase ST-2a (inverted: the official jump was begun with position 0.0 and nothing could end it): the start is refused, nothing is begun or sent
                self.assertEqual(self.sent(), [])
                self.assertFalse(o.is_official_jumping)
                self.assertFalse(o.is_scoring_mode)
                self.assertEqual((o.expected_target_loc, o.expected_target_time), (-1.0, -1))
                self.assertEqual(o.save_data, [])

    # -- S19 -------------------------------------------------------------------------------------------------------------------------------------
    @danger("S19", "a checkpoint is made WITHOUT the door time while its retry takes the STA route (calc_t < 0, def_t >= 0, time < def_t): the time gain the door time prevents is possible",
            "decision U-13 of the owner (no TARGET is placed)", "only if the owner decides to change it")
    def test_CURRENT_DANGER_S19_checkpoint_skips_door_time_but_retry_uses_station_jump(self):
        o = self.o
        self._door_station(raw_dep=-1, def_time=36100000)
        saves = self.arrive(1000.0, 999.0, t=36090000)
        self.assertEqual(saves[-1]["time_ms"], 36090000)                        # not added: will_use_sta is False
        self.assertEqual(self.door_logs(), [])
        cmds = self.retry(1, saves)
        self.assertEqual(cmds, [self.v2("STA", 1, 36090000)])                    # STA, because calc_t < 0 (retry rule R13)

    # -- TARGET (skipped) ------------------------------------------------------------------------------------------------------------------------
    @unittest.skip("TARGET-A CP-1 (JF-2): the initial check point carries station_index = setting_start_idx, a zero score_details and the scenario generation")
    @jf0("S01", "TARGET")
    def test_TARGET_A_S01_the_initial_checkpoint_carries_the_start_index_zero_details_and_the_generation(self):
        o = self.o
        self._start_through_the_menu(2)
        first = o.save_data[0]
        self.assertEqual(first["station_index"], 2)
        self.assertEqual(first["score_details"], ZERO)
        self.assertIn("scenario_generation", first)
        self.assertEqual(first["station_name"], "C")                          # the existing seven fields keep their meaning (CP-1)

    @unittest.skip("TARGET-A CP-4 (JF-2, candidate): the duplicate key is (scenario_generation, station_index)")
    @jf0("S03", "TARGET")
    def test_TARGET_A_S03_S10_the_duplicate_key_is_generation_and_station_index_not_the_float_location(self):
        o = self.o
        first = self.arrive(1000.0, 999.0, is_pass=1)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(self.arrive(1000.0000001, 999.0, is_pass=1, saves=o.save_data)), 2)       # same station: still one checkpoint

    @unittest.skip("TARGET-A S6 / S18 (JF-2): a position with several candidates creates no checkpoint (a reason is logged)")
    @jf0("S04", "TARGET")
    def test_TARGET_A_S04_a_same_position_pair_creates_no_checkpoint_and_a_reason_is_logged(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        before = len(self.log)
        self.assertEqual(len(self.arrive(1000.0, 999.0, name="B1", is_pass=1)), 1)
        self.assertGreater(len(self.log), before)

    @unittest.skip("TARGET-B S3 / CP-4 (JF-3): with an authoritative index the second station at the same position gets its own checkpoint")
    @jf0("S04", "TARGET")
    def test_TARGET_B_S04_the_second_station_at_the_same_position_gets_its_own_checkpoint(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        o.bve_next_idx = 1
        self.arrive(1000.0, 999.0, name="B1", is_pass=1)
        o.bve_next_idx = 2
        saves = self.arrive(1000.0, 999.0, name="B2", is_pass=1, saves=o.save_data)
        self.assertEqual([c["station_index"] for c in saves[1:]], [1, 2])

    @unittest.skip("TARGET-A V-3 / JR-5 (JF-2): a start index outside the list is refused and begin_official_jump is not called")
    @jf0("S17", "TARGET")
    def test_TARGET_A_S17_a_start_index_outside_the_list_is_refused_without_beginning_an_official_jump(self):
        o = self.o
        o.save_data = []
        self._start_through_the_menu(9)
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(o.save_data, [])

    @unittest.skip("TARGET-A S6 (JF-2): the provisional station_index is taken only when exactly ONE station is within 1.0 m; 0 and several create nothing; names do not decide")
    @jf0("S18", "TARGET")
    def test_TARGET_A_S18_the_provisional_supply_needs_exactly_one_candidate_and_does_not_look_at_names(self):
        o = self.o
        one = self.arrive(1000.0, 999.0, is_pass=1)
        self.assertEqual(one[-1].get("station_index"), 1)
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        self.assertEqual(len(self.arrive(1000.0, 999.0, name="B1", is_pass=1)), 1)             # two candidates, different names: nothing created
        o.station_list = [st("A", 0.0), st("X", 1000.0), st("X", 1000.0), st("D", 3000.0, terminal=True)]
        self.assertEqual(len(self.arrive(1000.0, 999.0, name="X", is_pass=1)), 1)              # two candidates, the same name: nothing created
        self.assertEqual(len(self.arrive(500.0, 499.0, is_pass=1)), 1)                         # zero candidates: nothing created


# ==============================================================================================================================================
# X01 - X05 : chains
# ==============================================================================================================================================
class X_Chains(Base):
    def _complete(self, location, kind="STA", index=0, t=T0, count=1):
        """Phase ST-3d: the plain (normal mode) completion v2 of the open request: the transport takes it (_note_jump_complete), the settlement judges it."""
        exp = self.o.jump_expectation
        text, why = jump_wire.format_completion_v2(kind, index, location, t, count, tuple(exp.scope))
        self.assertIsNone(why)
        self.o._note_jump_complete(text)
        self.o._settle_jump_complete()

    @jf0("X01", "CURRENT")
    def test_CURRENT_X01_checkpoint_creation_and_retry_use_the_same_station(self):
        # Phase ST-2b: was CURRENT_DANGER (created for Q by a 1.0 m search, retried to P by a 100 m search); both use the saved index now
        o = self.o
        o.station_list = [st("A", 0.0), st("P", 960.0), st("Q", 1000.0), st("D", 3000.0, terminal=True)]
        o.bve_door_close_time_ms = 4630
        saves = self.arrive(1000.0, 999.0, name="Q")
        self.assertEqual(len(self.door_logs()), 1)
        self.assertIn("Qにて", self.door_logs()[0])                            # creation: station Q (index 2)
        cmds = self.retry(1, saves)
        self.assertEqual(cmds, [self.v2("STA", 2, T0 + 60000 + 4630)])  # retry: station Q (index 2), the same station

    @jf0("X01", "CURRENT")
    def test_CURRENT_X01_a_consistent_late_arrival_is_saved_with_the_door_time_and_retried_by_STA(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B", 1000.0, def_time=T0 + 50000, raw_dep=T0 + 15000), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        o.bve_door_close_time_ms = 4630
        saves = self.arrive(1000.0, 999.0, t=T0 + 60000)                       # now >= def_time and late: the door time is added
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000 + 4630)
        self.assertEqual(self.retry(1, saves), [self.v2("STA", 1, T0 + 60000 + 4630)])

    @jf0("X01", "CURRENT")
    def test_CURRENT_X01_a_consistent_early_arrival_is_saved_without_the_door_time_and_retried_by_LOC(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B", 1000.0, def_time=T0 + 100000, raw_dep=T0 + 15000), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        o.bve_door_close_time_ms = 4630
        saves = self.arrive(1000.0, 999.0, t=T0 + 60000)                       # before def_time: STA would be too early, LOC is predicted: no door time
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000)
        self.assertEqual(self.retry(1, saves), [self.v2("LOC", 1, T0 + 60000)])

    @jf0("X02", "CURRENT")
    def test_CURRENT_X02_retry_to_the_first_station_then_completion_then_departure_then_the_next_arrival_adds_a_checkpoint(self):
        o = self.o
        o.is_scoring_mode = True
        o.setting_end_idx = 3
        o.jump_lock = True
        cmds = self.retry(0, [cp(0.0, T0, name="A"), cp(1000.0, T0 + 60000, details=ZERO, name="B")])
        self.assertEqual(cmds, [self.v2("STA", 0, T0)])
        self.assertTrue(o.is_first_station and o.is_official_jumping)
        self._complete(0.0)
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.jump_lock)                                           # the completion does not release the lock ...
        o.bve_speed, o.bve_door, o.bve_next_loc, o.bve_location = 30.0, 0, 1000.0, 100.0
        o.prev_next_loc = 1000.0
        self.S.update_physics_and_scoring(o, 100.0, 0.016)
        self.assertFalse(o.jump_lock)                                          # ... the departure does
        self.assertTrue(o.has_departed)
        self.assertFalse(o.is_first_station)
        o.bve_current_station_name, o.bve_is_pass, o.bve_location, o.bve_speed = "B", 1, 999.0, 0.0
        R.bind_identity(o)                                                     # (Phase ST-2a: the sender names station B)
        self.S.evaluate_arrival(o, 101.0)
        self.assertEqual(len(o.save_data), 2)                                  # the arrival at B adds one checkpoint

    @jf0("X03", "CURRENT")
    def test_CURRENT_X03_after_a_retry_to_a_later_station_the_same_station_is_not_saved_again_and_the_retry_flag_stays(self):
        o = self.o
        o.is_scoring_mode = True
        o.setting_end_idx = 3
        self.retry(1, [with_identity(cp(0.0, T0, name="A"), 0, 0.0, role="scoring_start"),
                       with_identity(cp(996.0, T0 + 60000, details=ZERO, name="B", target_loc=1000.0), 1, 1000.0)])
        self._complete(1000.0, index=1, t=T0 + 60000)
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.is_official_retry)
        o.bve_next_loc = o.prev_next_loc = 1000.0
        o.bve_location, o.bve_is_pass = 996.0, 1
        R.bind_identity(o)                                                     # (Phase ST-2a: the sender names station B, which the retry checkpoint already holds)
        self.S.create_save_data(o)
        self.assertEqual(len(o.save_data), 2)
        self.assertTrue(o.is_official_retry)

    @jf0("X04", "CURRENT")
    def test_CURRENT_X04_a_check_point_that_matches_no_station_is_refused_so_the_official_jump_can_not_get_stuck(self):
        # Phase ST-2b: was CURRENT_DANGER (the zero-candidate fallback expected the check point position, the completion at station 0 never matched and the jump stuck)
        o = self.o
        saves = [cp(0.0, T0), with_identity(cp(1500.0, T0 + 60000, details=ZERO), 1, 1500.0)]
        cmds = self.retry(1, saves)
        self.assertEqual(cmds, [])
        self.assertFalse(o.is_official_jumping)                                # no official jump was begun: nothing can wait for ever
        self.assertEqual(o.expected_target_loc, -1.0)

    @jf0("X05", "CURRENT")
    def test_CURRENT_X05_normal_mode_a_plain_completion_at_the_expected_location_releases(self):
        o = self.o
        del o.send_jump_command
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO, name="B")]
        self.complete_identity(o.save_data)
        self.S.execute_retry(o, 1, True)
        o.udp_socket.incoming = [self.completion_v2("STA", 1, 1000.0, T0 + 60000, 2)]
        o.read_udp_data()
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(len(o.save_data), 2)                                  # (the normal mode is not a formal transaction: it releases the jump, it never cuts the history)

    @jf0("X05", "CURRENT")
    def test_CURRENT_X05_normal_mode_a_plain_completion_at_another_location_aborts_the_scoring_instead_of_sticking(self):
        """Phase ST-3d: was CURRENT_DANGER ("a plain completion at another location is rejected and the official jump stays on for ever": no RequestId, no timeout). The settlement judges
        every completion that arrives and releases the jump with the scoring abort; a completion that never arrives is released at the same 10 s deadline as in the managed mode."""
        o = self.o
        del o.send_jump_command
        o.is_scoring_mode = True
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO, name="B")]
        self.complete_identity(o.save_data)
        self.S.execute_retry(o, 1, True)
        o.udp_socket.incoming = [self.completion_v2("STA", 1, 900.0, T0 + 60000, 2)]
        o.read_udp_data()
        self.assertFalse(o.is_official_jumping)
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)
        self.assertIsNone(o.retry_pending)
        self.assertEqual(len(o.save_data), 2)

    @jf0("X05", "CURRENT")
    def test_CURRENT_X05_normal_mode_without_any_completion_the_deadline_releases_the_jump(self):
        o = self.o
        del o.send_jump_command
        o.is_scoring_mode = True
        o.save_data = [cp(0.0, T0), cp(1000.0, T0 + 60000, details=ZERO, name="B")]
        self.complete_identity(o.save_data)
        self.S.execute_retry(o, 1, True)
        self.rig.advance(5.0)
        o._poll_jump_client()
        self.assertTrue(o.is_official_jumping)
        self.rig.advance(6.0)
        o._poll_jump_client()
        self.assertFalse(o.is_official_jumping)
        self.assertIsNone(o.retry_pending)

    def completion_v2(self, kind, index, location, t, count):
        text, why = jump_wire.format_completion_v2(kind, index, location, t, count, tuple(self.o.jump_expectation.scope))
        self.assertIsNone(why)
        return text.encode("ascii")


# ==============================================================================================================================================
# the file's own consistency (meta tests)
# ==============================================================================================================================================
class Z_Meta(unittest.TestCase):
    KINDS = {"test_CURRENT_DANGER_": "CURRENT_DANGER", "test_CURRENT_": "CURRENT", "test_REACH_": "REACH", "test_TARGET_A_": "TARGET", "test_TARGET_B_": "TARGET"}

    @staticmethod
    def case_methods():
        for cls in (R_ExecuteRetry, S_SaveData, X_Chains):
            for name in sorted(n for n in dir(cls) if n.startswith("test_")):
                yield cls, name, getattr(cls, name)

    @classmethod
    def kind_of(cls, name):
        for prefix in ("test_CURRENT_DANGER_", "test_CURRENT_", "test_REACH_", "test_TARGET_A_", "test_TARGET_B_"):
            if name.startswith(prefix):
                return cls.KINDS[prefix]
        return None

    def test_META_every_test_has_a_known_prefix_and_jf0_metadata_of_the_same_kind(self):
        count = 0
        for cls, name, fn in self.case_methods():
            count += 1
            kind = self.kind_of(name)
            self.assertIsNotNone(kind, name)
            meta = getattr(fn, "jf0", None)
            self.assertIsNotNone(meta, name)
            self.assertEqual(meta["kind"], kind, name)
            self.assertIn(meta["id"], OWN_IDS, name)
            self.assertIn(meta["id"], name)
        self.assertGreater(count, 80)

    def test_META_every_CURRENT_DANGER_carries_its_four_facts(self):
        seen = 0
        for cls, name, fn in self.case_methods():
            if self.kind_of(name) != "CURRENT_DANGER":
                continue
            seen += 1
            meta = fn.jf0
            self.assertTrue(name.startswith("test_CURRENT_DANGER_" + meta["id"]) or name.startswith("test_CURRENT_DANGER_%s_" % meta["id"]), name)
            for key, shortest in (("danger", 21), ("phase", 8), ("flip", 21)):
                self.assertTrue(meta[key] and len(meta[key]) >= shortest, (name, key))
        self.assertEqual(seen, 6)                                       # Phase ST-2b: 16 before; R06 R07 R08 R09 x2 R10 X01 X04 are no longer dangerous (CURRENT); Phase ST-3d: R23 and X05 (a normal mode that waits for ever) are gone

    def test_META_every_TARGET_is_skipped_with_a_contract_id_in_the_reason(self):
        seen = 0
        for cls, name, fn in self.case_methods():
            if self.kind_of(name) != "TARGET":
                continue
            seen += 1
            self.assertTrue(getattr(fn, "__unittest_skip__", False), name)
            reason = getattr(fn, "__unittest_skip_why__", "")
            self.assertRegex(reason, r"TARGET-[AB] ", name)
            self.assertRegex(reason, r"(V-R?\d|CP-\d|RT-\d|FC-\d|S6|S3|B2|S18|U-\d+)", name)
        self.assertGreaterEqual(seen, 12)

    def test_META_every_own_id_has_at_least_one_test_and_the_delegated_ones_are_named(self):
        have = {fn.jf0["id"] for _c, _n, fn in self.case_methods() if hasattr(fn, "jf0")}
        self.assertEqual(sorted(set(OWN_IDS) - have), [])
        self.assertEqual(DELEGATED, {"R22": "F2", "R27": "F2"})
        self.assertEqual(sorted(have - set(OWN_IDS)), [])

    def test_META_no_test_reads_the_real_desktop_or_the_network(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", f.read(), flags=re.S))
        # (the words are written in two pieces so that this list does not match itself)
        for word in ("sock" "et.sock" "et", "QUdp" "Socket(", "sub" "process", "Po" "pen", "os." "system", "expand" "user", "\\" "Desk" "top", "/" "Desk" "top", "Down" "loads"):
            self.assertNotIn(word, code, word)


if __name__ == "__main__":
    unittest.main()
