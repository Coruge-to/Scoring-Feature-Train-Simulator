"""Close-range (adjacent stop) departure protection - the ENTRY PATHS of the current station B (Phase CR-ENT, fix O1).

Contract (Owner, revised OD-CR-2(a)): the departure protection of a close pair B -> C does not depend on HOW the train came to B:
  BASE   A -> real stop at B                      the anchor is fixed by evaluate_arrival (unchanged)
  START  the scoring-start Jump landed at B       the anchor is fixed when the official Jump SETTLES (Overlay._settle_jump_complete)
  RETRY  the Retry Jump landed at B               the same, with the position of THIS landing (never a stored past stop)
The pair formula, the pending state and the positive-speed release are the existing ones (scoring_logic.close_range_pair_is_close / update_close_range_departure_reset); only the supply of the
anchor (prev_actual_stop_loc) is new: scoring_logic.close_range_fix_landing_stop, called from the success branch of _settle_jump_complete with the verdict of jump_transaction.judge_completion.

Meanings: BASE (unchanged behaviour), CONTRACT (the revised contract), GUARD (a fail-closed or no-regression boundary).
The scenes drive the REAL update_physics_and_scoring and the REAL begin_official_jump / execute_retry / _note_jump_complete / _settle_jump_complete of main.Overlay through the offscreen rig.
ISOLATION: USERPROFILE / HOME point to an empty temporary folder. Without PyQt6 every scene test is SKIPPED, never passed.
"""
import ast
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

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
ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
B_MARK = 1000.0
GAP = 49.4                         # a close pair: C's near edge is 44.4 m ahead of B, inside the 300 m + margin stop window
TRAIN_LEN = 300.0
RID = bytes(range(1, 17))          # the RequestId of a managed (formal) transaction
_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-close-range-entry-")
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
        raise AssertionError("the entry-path module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False), is_pass=kw.pop("is_pass", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def stations(gap):
    return [sta("A", 0.0), sta("B", B_MARK), sta("C", B_MARK + gap), sta("D", 6000.0, terminal=True)]


def checkpoint0(sl, idx):
    s = sl[idx]
    return {"loc": s["location"], "time_ms": T0, "score": 0, "target_loc": s["location"], "station_name": s["name"], "stop_error": 0.0, "score_details": dict(ZERO),
            "station_index": idx, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, len(sl)), "station_location": s["location"], "role": "scoring_start"}


class Flow(object):
    """One scene: the helpers that put the Overlay at B by one of the three paths and drive the tail B -> C. Pure test code; the product is only called."""

    def __init__(self, test, gap=GAP, formal=False):
        self.main, self.S = test.main, test.S
        self.jump_transaction, self.jump_wire = test.jump_transaction, test.jump_wire
        previous = getattr(test, '_flow', None)
        if previous is not None:
            previous.close()                                    # one Rig at a time: two installed rigs would restore each other's fakes
        test._flow = self
        self.rig = R.Rig(self.main)
        self.closed = False
        test.addCleanup(self.close)
        self.o = self.rig.o
        self.gap = gap
        self.formal = formal
        self.t = 100.0
        self.n = 0
        self.rows = []
        self.sl = stations(gap)
        self.c_loc = B_MARK + gap
        o = self.o
        o.station_list = self.sl
        o.toggle_menu = lambda adv: None
        o.send_jump_command = (lambda cmd: RID) if formal else (lambda cmd: None)
        self.sent = []

    def close(self):
        if not self.closed:
            self.closed = True
            self.rig.close()

    # -- the tick ----------------------------------------------------------------------------------------------------------------------------------
    def tick(self, label="", **fields):
        o = self.o
        pre = {"pending": bool(o.close_range_departure_reset_pending), "anchor": o.prev_actual_stop_loc, "flag": bool(o.is_stopped_out_of_range), "next_loc": o.bve_next_loc,
               "prev_next": getattr(o, "prev_next_loc", None), "stop": o.score_details.get("stop"), "bb": o.score_details.get("base_brake")}
        for k, v in fields.items():
            setattr(o, k, v)
        o.bve_time_ms += 16
        self.t += 0.016
        self.n += 1
        self.main.update_physics_and_scoring(o, self.t, 0.016)
        ev = set()
        if pre["prev_next"] not in (None, -1.0) and o.bve_next_loc != pre["prev_next"]:
            ev.add("switch")
        if not pre["pending"] and o.close_range_departure_reset_pending:
            ev.add("arm")
        if pre["pending"] and not o.close_range_departure_reset_pending:
            ev.add("release")
        if not pre["flag"] and o.is_stopped_out_of_range:
            ev.add("flag")
        self.rows.append({"n": self.n, "label": label, "ev": ev, "anchor_pre": pre["anchor"], "anchor": o.prev_actual_stop_loc, "speed": o.bve_speed, "next_loc": o.bve_next_loc,
                          "stop_pre": pre["stop"], "bb_pre": pre["bb"]})

    def step(self, n=1, label="", **fields):
        for i in range(n):
            self.tick(label, **(fields if i == 0 else {}))

    def common(self, end_idx=3):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.setting_end_idx = end_idx
        o.bve_train_length = TRAIN_LEN
        o.bve_is_pass = 0
        o.bve_doordir = 1
        o.bve_margin_f = o.bve_margin_b = 5.0
        o.bve_time_ms = T0
        o.bve_next_time = T0 + 60000
        o.is_official_jumping = False
        o.prev_is_pass = 0
        o.prev_is_timing = 1
        o.prev_doordir = 1
        o.is_official_retry = False
        o.bve_brk_notch = 8
        o.bve_calc_g = 0.0
        o.is_first_udp = False

    # -- the three paths to B ----------------------------------------------------------------------------------------------------------------------
    def base(self):
        """BASE: A (start, idx 0) -> a real stop at B (idx 1): the REAL arrival path creates the checkpoint and the anchor."""
        o, S = self.o, self.S
        self.common()
        o.save_data = [checkpoint0(self.sl, 0)]
        o.bve_next_loc = o.prev_next_loc = B_MARK
        o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq = 1, 0, 0
        o.bve_location, o.bve_speed = B_MARK - 400.0, 30.0
        o.bve_door = o.prev_door = 0
        o.has_departed, o.is_first_station, o.jump_lock = True, False, False
        o.bve_current_station_name = "B"
        o.bve_brk_notch = 0
        R.bind_identity(o, arr_idx=0, tgt_idx=1)
        S.reset_station_evaluation_state(o)
        self.tick("build")
        self.step(1, "approach", bve_speed=5.0, bve_location=B_MARK - 100.0, bve_brk_notch=3)
        self.step(1, "approach", bve_speed=2.0, bve_location=B_MARK - 10.0, bve_brk_notch=3)
        self.step(3, "stop-B", bve_speed=0.0, bve_location=B_MARK - 0.3, bve_brk_notch=4)
        self.step(1, "door-open-B", bve_door=1, bve_arr_idx=1, bve_arr_seq=1)
        self.step(3, "dwell-B")
        return B_MARK - 0.3

    def begin_start(self, door=0):
        """START up to the OPEN transaction: the menu sequence of main.py (the real planner, reset, begin_official_jump, the first checkpoint, the transaction). Nothing has settled."""
        o, main = self.o, self.main
        self.common()
        o.is_scoring_mode = False
        o.setting_start_idx = 1
        o.save_data = []
        o.bve_next_loc = o.prev_next_loc = 0.0
        o.bve_location, o.bve_speed = 0.0, 0.0
        o.bve_door = o.prev_door = door
        R.bind_identity(o, arr_idx=-1, tgt_idx=0)
        snap = o._scoring_start_snapshot()
        start_loc, name, t_ms, req, refusal = o._scoring_start_plan(snap)
        assert req is not None, refusal
        o.is_scoring_mode = True
        main.reset_result_display_state(o)
        main.reset_score_accumulation(o)
        main.reset_speed_penalty_state(o)
        main.reset_roll_state(o)
        o.total_retry_count = 0
        o.retry_pending = None
        o.save_data.clear()
        o.is_first_udp = True
        o.is_first_station = True
        o.has_departed = False
        main.reset_station_evaluation_state(o)
        main.begin_official_jump(o, start_loc, t_ms)
        first = {"loc": start_loc, "time_ms": t_ms, "score": 0, "target_loc": start_loc, "station_name": name, "stop_error": 0.0}
        first.update(main.station_identity.checkpoint_fields(snap))
        o.save_data.append(first)
        o._open_jump_transaction(self.jump_transaction.JUMP_START, req, o.send_jump_command(req.text))
        return B_MARK

    def jump_count_tick(self):
        o = self.o
        self.step(3, "jumping(old world)")
        self.step(1, "jump-count+1", bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=B_MARK, bve_speed=0.0, bve_next_loc=B_MARK, bve_tgt_idx=1)

    def start(self, door=0):
        """START: begin_start, the JUMP count of the telemetry, the REAL completion settlement, then the landing ticks."""
        self.begin_start(door)
        self.jump_count_tick()
        self.complete()
        self.land(door_open_at_landing=bool(door))
        return B_MARK
    def retry(self):
        """RETRY: BASE up to the real checkpoint of B, run on toward C, then the REAL execute_retry to the checkpoint of B and the completion settlement."""
        self.base()
        o = self.o
        self.step(5, "leave-B", bve_door=0, bve_speed=8.0, bve_location=B_MARK + 5.0, bve_brk_notch=0)
        assert len(o.save_data) >= 2, "no real checkpoint of B was created by the real arrival"
        result = self.main.execute_retry(o, 1, False)
        assert result.accepted, result
        self.jump_ticks()
        return B_MARK

    def jump_ticks(self):
        self.jump_count_tick()
        self.complete()
        self.land(retry=bool(self.o.is_official_retry))
    def completion_text(self, **over):
        exp = self.o.jump_expectation
        text, why = self.jump_wire.format_completion_v2(over.get("command", exp.command), over.get("idx", exp.station_index), over.get("loc", exp.location), exp.time_ms, 1,
                                                        tuple(over.get("scope", exp.scope)))
        assert why is None, why
        return text

    def deliver(self, text):
        """The transport side of a completion (formal: the event carries the RequestId of the transaction; plain: it does not), then the settlement."""
        o = self.o
        jt = self.jump_transaction
        if self.formal:
            o.pending_jump_complete = jt.CompletionEvent(RID, text)
            o.jump_expectation = jt.with_completion_seen(o.jump_expectation, jt.LAST_OK)
        else:
            o._note_jump_complete(text)
        o._settle_jump_complete()

    def complete(self, **over):
        self.deliver(self.completion_text(**over))
        assert not self.o.is_official_jumping, "the jump did not settle"

    def land(self, retry=False, door_open_at_landing=False):
        """The ticks after the Jump landed at B (idx 1): the arrival candidate door edge of the landing, then the dwell."""
        o = self.o
        o.bve_next_loc = o.prev_next_loc = B_MARK
        o.bve_location, o.bve_speed = B_MARK, 0.0
        o.bve_door = o.prev_door = 1 if door_open_at_landing else 0
        o.bve_tgt_idx, o.bve_arr_idx = 1, 1
        self.step(2, "land")
        if not door_open_at_landing:
            self.step(1, "door-open-B(landing)", bve_door=1, bve_arr_idx=1, bve_arr_seq=(2 if retry else 1))
        self.step(10, "dwell-B")

    # -- the tail B -> C ---------------------------------------------------------------------------------------------------------------------------
    def switch_and_depart(self, sw_speed, next_speed, loc_a):
        sw = dict(bve_next_loc=self.c_loc, bve_tgt_idx=2, bve_margin_f=5.0, bve_margin_b=5.0, bve_next_time=T0 + 300000)
        self.step(3, "brake-release", bve_brk_notch=0)
        self.step(1, "switch+door-close", bve_door=0, bve_speed=sw_speed, bve_location=loc_a, **sw)
        self.step(1, "after-switch", bve_speed=next_speed, bve_location=loc_a + 0.02, bve_brk_notch=0)

    def run_to_c_and_stop(self, loc_a):
        c = self.c_loc
        span = c - loc_a
        self.step(25, "depart", bve_brk_notch=0, bve_speed=0.5, bve_location=loc_a + 0.1)
        self.step(3, "run", bve_speed=10.0, bve_location=loc_a + min(5.0, span * 0.1))
        self.step(3, "run", bve_speed=20.0, bve_location=loc_a + min(15.0, span * 0.3))
        self.step(25, "brake3", bve_brk_notch=3, bve_speed=15.0, bve_location=c - min(25.0, span * 0.5))
        self.step(25, "brake2", bve_brk_notch=2, bve_speed=8.0, bve_location=c - min(8.0, span * 0.2))
        self.step(3, "stop-C", bve_brk_notch=1, bve_speed=0.0, bve_location=c - 0.03)
        self.step(1, "door-open-C", bve_door=1, bve_arr_idx=2, bve_arr_seq=3)
        self.step(3, "dwell-C")

    def tail(self, mode, sw_speed, loc_a):
        c = self.c_loc
        if mode == "reverse":
            self.switch_and_depart(-0.2, -0.4, loc_a)
            for i in range(6):
                self.step(1, "reversing", bve_speed=-1.0 - i, bve_location=loc_a - 0.5 * (i + 1))
            self.step(3, "stop-after-reverse", bve_speed=0.0, bve_location=loc_a - 3.5)
            self.run_to_c_and_stop(loc_a - 3.5)
            return
        self.switch_and_depart(sw_speed, 1.0 if sw_speed > 0.0 else 0.5, loc_a)
        if mode == "short":
            self.step(25, "depart", bve_brk_notch=0, bve_speed=0.5, bve_location=loc_a + 0.1)
            self.step(3, "run", bve_speed=10.0, bve_location=loc_a + 5.0)
            self.step(25, "brake", bve_brk_notch=3, bve_speed=8.0, bve_location=c - 29.4)
            self.step(3, "stop-short(outside C range)", bve_brk_notch=1, bve_speed=0.0, bve_location=c - 29.4)
            self.step(3, "creep", bve_speed=0.5, bve_location=c - 10.0)
            self.step(3, "stop-C(in range)", bve_speed=0.0, bve_location=c - 0.03)
            self.step(1, "door-open-C", bve_door=1, bve_arr_idx=2, bve_arr_seq=3)
            self.step(3, "dwell-C")
            return
        self.run_to_c_and_stop(loc_a)

    # -- the observations --------------------------------------------------------------------------------------------------------------------------
    def tick_of(self, event, after=0):
        return next((r["n"] for r in self.rows if event in r["ev"] and r["n"] > after), None)

    def tick_of_label(self, label):
        return next((r["n"] for r in self.rows if r["label"] == label), None)

    def switch_row(self):
        """The tick of the target switch B -> C (the earlier switches of a Jump landing are not it)."""
        return next((r for r in self.rows if "switch" in r["ev"] and r["next_loc"] == self.c_loc), None)

    def c_points(self):
        """The points that C itself earned: the final stop / basic-braking points minus what was carried into the switch tick (a Retry restores the score of B, a START carries none)."""
        sw, o = self.switch_row(), self.o
        return o.score_details.get("stop") - sw["stop_pre"], o.score_details.get("base_brake") - sw["bb_pre"]


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["close-range-entry"])
        import jump_transaction
        import jump_wire
        import main
        import scoring_logic
        cls.main, cls.S, cls.jump_transaction, cls.jump_wire = main, scoring_logic, jump_transaction, jump_wire

    def flow(self, path, gap=GAP, formal=False):
        f = Flow(self, gap, formal)
        loc_a = getattr(f, path)()
        return f, loc_a

    def run_path(self, path, mode, sw_speed, gap=GAP, formal=False):
        f, loc_a = self.flow(path, gap, formal)
        f.tail(mode, sw_speed, loc_a)
        return f

    def points(self, o):
        return o.score_details.get("stop"), o.score_details.get("base_brake")


PATHS = ("base", "start", "retry")


# ==============================================================================================================================================
# A. THE ANCHOR OF EACH ENTRY PATH
# ==============================================================================================================================================
class A_Anchor(Base):
    def test_ENT_R1_base_path_keeps_the_arrival_anchor_and_arms(self):
        """BASE: unchanged. The anchor is the real stop position (0.3 m short of the mark), the pending is armed at the switch tick, released by the first positive speed."""
        f = self.run_path("base", "fwd_in", 0.0)
        sw = f.switch_row()
        self.assertEqual(sw["anchor_pre"], B_MARK - 0.3)
        self.assertIsNotNone(f.tick_of("arm"))
        self.assertIsNotNone(f.tick_of("release", f.tick_of("arm")))
        self.assertFalse(f.o.is_stopped_out_of_range)

    def test_ENT_R2_start_path_supplies_the_anchor_and_arms(self):
        for formal in (False, True):
            with self.subTest(formal=formal):
                f = self.run_path("start", "fwd_in", 0.0, formal=formal)
                sw = f.switch_row()
                self.assertEqual(sw["anchor_pre"], B_MARK)
                self.assertIsNotNone(f.tick_of("arm"), "the START path must arm the close-range pending like the BASE path")
                self.assertIsNotNone(f.tick_of("release", f.tick_of("arm")))

    def test_ENT_R3_start_anchor_is_the_actual_landing_position_at_the_settlement(self):
        """Set at the SETTLEMENT itself (before any later tick, before any door edge), from the completion's actual landing position."""
        for formal in (False, True):
            with self.subTest(formal=formal):
                f = Flow(self, formal=formal)
                o = f.o
                f.begin_start()
                self.assertEqual(o.prev_actual_stop_loc, -1.0, "no anchor while the Jump is outstanding")
                f.jump_count_tick()
                self.assertEqual(o.prev_actual_stop_loc, -1.0, "the JUMP count of the telemetry supplies nothing")
                f.complete()
                self.assertEqual(o.prev_actual_stop_loc, B_MARK)
                self.assertTrue(o.jump_lock, "the formal flow keeps jump_lock: the anchor does not come from evaluate_arrival's not-jump_lock branch")
    def test_ENT_R4_retry_anchor_is_the_retry_landing_not_the_past_stop(self):
        for formal in (False, True):
            with self.subTest(formal=formal):
                f, _ = self.flow("base", formal=formal)
                o = f.o
                self.assertEqual(o.prev_actual_stop_loc, B_MARK - 0.3, "BASE past stop (the stale value the Retry must NOT restore)")
                f.step(5, "leave-B", bve_door=0, bve_speed=8.0, bve_location=B_MARK + 5.0, bve_brk_notch=0)
                self.assertTrue(f.main.execute_retry(o, 1, False).accepted)
                self.assertEqual(o.prev_actual_stop_loc, -1.0, "the Retry reset clears the anchor; nothing of the past is restored")
                f.step(3, "jumping(old world)")
                f.step(1, "jump-count+1", bve_jump_count=1, bve_location=B_MARK, bve_next_loc=B_MARK, bve_tgt_idx=1)
                self.assertEqual(o.prev_actual_stop_loc, -1.0)
                f.complete()
                self.assertEqual(o.prev_actual_stop_loc, B_MARK, "the anchor of THIS landing (HUD 0.00 m), not 999.7")

    def test_ENT_R27c_the_landing_anchor_is_consumed_at_the_first_switch(self):
        """R27b for the new entries: the landing position of B is the anchor of the pair B -> C ONLY; the switch tick clears it, so C -> D never sees it."""
        for path in ("start", "retry"):
            with self.subTest(path=path):
                f = self.run_path(path, "fwd_in", 0.5)
                sw = f.switch_row()
                self.assertEqual((sw["anchor_pre"], sw["anchor"]), (B_MARK, -1.0))
                until_arrival = [r for r in f.rows if r["n"] > sw["n"] and r["label"] != "door-open-C" and r["n"] < f.tick_of_label("door-open-C")]
                self.assertTrue(until_arrival)
                self.assertEqual({r["anchor"] for r in until_arrival}, {-1.0})

    def test_ENT_R2b_anchor_does_not_depend_on_the_landing_door_edge(self):
        """The doors are already open at the landing: there is no new door-open edge, the anchor is there anyway, and it survives the dwell."""
        g = Flow(self)
        o = g.o
        g.begin_start(door=1)
        g.jump_count_tick()
        g.complete()
        self.assertEqual(o.prev_actual_stop_loc, B_MARK)
        g.land(door_open_at_landing=True)
        self.assertEqual(o.prev_actual_stop_loc, B_MARK, "no door edge happened and the anchor is still the landing position")
        g.tail("fwd_in", 0.0, B_MARK)
        self.assertIsNotNone(g.tick_of("arm"))
        self.assertFalse(o.is_stopped_out_of_range)
    def test_ENT_R19_the_actual_landing_is_used_not_the_requested_location(self):
        """Today judge_completion demands actual == requested == listed, so they cannot differ in an accepted completion; the supply still takes the ACTUAL position of the verdict
        (the source of truth): a verdict whose actual position differs from the request must give the actual one."""
        g = Flow(self)
        o = g.o
        g.begin_start()
        g.jump_count_tick()
        real = g.jump_transaction.judge_completion

        def widened(*a, **k):
            v = real(*a, **k)
            return v._replace(actual_location=B_MARK + 0.25) if v.ok else v
        with mock.patch.object(g.jump_transaction, "judge_completion", widened):
            g.complete()
        self.assertEqual(o.prev_actual_stop_loc, B_MARK + 0.25)
        self.assertNotEqual(o.prev_actual_stop_loc, o.expected_target_loc)
    def test_ENT_G_the_helper_itself_is_fail_closed(self):
        """Unit boundary of scoring_logic.close_range_fix_landing_stop: only a listed index and a finite non-negative position give an anchor; anything else leaves -1.0."""
        sl = stations(GAP)
        helper = getattr(self.S, "close_range_fix_landing_stop", None)
        self.assertIsNotNone(helper, "close_range_fix_landing_stop is the O1 helper")
        cases = [((1, 1000.0), 1000.0), ((0, 0.0), 0.0), ((2, 1049.4), 1049.4),
                 ((-1, 1000.0), -1.0), ((4, 1000.0), -1.0), ((1, None), -1.0), ((1, float("nan")), -1.0), ((1, float("inf")), -1.0), ((1, -5.0), -1.0), ((True, 1000.0), -1.0),
                 (("1", 1000.0), -1.0), ((1.0, 1000.0), -1.0), ((1, "1000"), -1.0), ((1, True), -1.0)]
        for (idx, loc), want in cases:
            o = type("O", (), {})()
            o.station_list = sl
            o.prev_actual_stop_loc = 123.0
            helper(o, idx, loc)
            self.assertEqual(o.prev_actual_stop_loc, want, (idx, loc))
        o = type("O", (), {})()
        o.station_list = None
        o.prev_actual_stop_loc = 123.0
        helper(o, 1, 1000.0)
        self.assertEqual(o.prev_actual_stop_loc, -1.0, "no adopted station list")


# ==============================================================================================================================================
# B. THE PROTECTION BEHAVES LIKE THE BASE PATH ON EVERY ENTRY
# ==============================================================================================================================================
class B_Protection(Base):
    def test_ENT_R5_R6_false_zero_on_the_switch_tick_is_not_an_out_of_range_stop(self):
        for path in ("start", "retry"):
            for sw in (0.0, -0.0):
                for formal in (False, True):
                    with self.subTest(path=path, sw=repr(sw), formal=formal):
                        f = self.run_path(path, "fwd_in", sw, formal=formal)
                        self.assertIsNone(f.tick_of("flag"), "B's initial stop must not count as a stop outside C's range")
                        self.assertIsNotNone(f.tick_of("arm"))

    def test_ENT_R7_R8_reverse_then_stop_before_the_forward_departure_does_not_flag(self):
        for path in ("start", "retry"):
            with self.subTest(path=path):
                f = self.run_path(path, "reverse", -0.2)
                self.assertIsNone(f.tick_of("flag"))
                self.assertIsNotNone(f.tick_of("arm"))

    def test_ENT_R9_a_real_stop_outside_c_after_the_forward_departure_still_flags(self):
        for path in PATHS:
            for sw in (0.5, 0.0):
                with self.subTest(path=path, sw=sw):
                    f = self.run_path(path, "short", sw)
                    flag, release = f.tick_of("flag"), f.tick_of("release")
                    self.assertIsNotNone(flag, "the flag is the intended one: a real stop outside C's range after a forward departure")
                    if sw == 0.0:
                        self.assertIsNotNone(release)
                        self.assertGreater(flag, release, "the flag comes AFTER the forward departure released the pending state")
    def test_ENT_R10_a_normal_stop_inside_c_is_scored_on_every_path(self):
        results = {}
        for path in PATHS:
            for sw in (0.0, 0.5):
                f = self.run_path(path, "fwd_in", sw)
                results[(path, sw)] = f.c_points()
                self.assertFalse(f.o.is_stopped_out_of_range, (path, sw))
                self.assertGreater(results[(path, sw)][0], 0, "the stop position of C is credited: %s" % ((path, sw),))
        self.assertEqual(len({v for v in results.values()}), 1, "the three entry paths give the same stop / basic-braking points")

    def test_ENT_R11_a_non_close_pair_is_unchanged(self):
        for path in PATHS:
            with self.subTest(path=path):
                f = self.run_path(path, "fwd_in", 0.0, gap=800.0)
                self.assertIsNone(f.tick_of("arm"), "a pair 800 m apart is not a close pair: no pending")

    def test_ENT_R18_the_fix_changes_nothing_else_in_the_overlay_state(self):
        """Run the START and the RETRY flows with the helper replaced by a no-op (the old behaviour) and with the real one: every plain attribute is the same
        except prev_actual_stop_loc (and the pending / flag results that follow from it in the tail, compared separately)."""
        for path in ("start", "retry"):
            for formal in (False, True):
                with self.subTest(path=path, formal=formal):
                    digests = []
                    for patched in (True, False):
                        f = Flow(self, formal=formal)
                        if patched:
                            with mock.patch.object(self.main, "close_range_fix_landing_stop", lambda *a, **k: None), \
                                    mock.patch.object(self.S, "close_range_fix_landing_stop", lambda *a, **k: None):       # the settlement's supply and (Stage TB-C) the landing watch's re-supply
                                loc_a = getattr(f, path)()
                        else:
                            loc_a = getattr(f, path)()
                        o = f.o
                        keep = (int, float, str, bool, type(None), tuple, list, dict)
                        digests.append({k: repr(v) for k, v in vars(o).items() if isinstance(v, keep) and not re.search(r"0x[0-9a-f]+", repr(v))})
                        f.close()
                    a, b = digests
                    self.assertEqual({k for k in set(a) | set(b) if a.get(k) != b.get(k)}, {"prev_actual_stop_loc"})
                    self.assertIn("prev_actual_stop_loc", a)

    def test_ENT_R18b_retry_keeps_history_and_the_retry_count_as_before(self):
        for formal in (False, True):
            with self.subTest(formal=formal):
                f, _ = self.flow("base", formal=formal)
                o = f.o
                f.step(5, "leave-B", bve_door=0, bve_speed=8.0, bve_location=B_MARK + 5.0, bve_brk_notch=0)
                self.assertEqual(len(o.save_data), 2)
                self.assertTrue(f.main.execute_retry(o, 1, False).accepted)
                f.jump_ticks()
                self.assertEqual(len(o.save_data), 2, "the checkpoint of B is the last one of the history: nothing more is cut")
                self.assertEqual(o.prev_actual_stop_loc, B_MARK)


# ==============================================================================================================================================
# C. NOTHING IS SUPPLIED WHEN THE JUMP DID NOT SUCCEED
# ==============================================================================================================================================
class C_Fail(Base):
    def open_start(self, formal=False):
        f = Flow(self, formal=formal)
        f.begin_start()
        f.jump_count_tick()
        return f
    def test_ENT_R12_a_failed_jump_gives_no_anchor(self):
        for formal in (False, True):
            for name, over in (("wrong-location", {"loc": B_MARK + 3.0}), ("wrong-index", {"idx": 2}), ("wrong-scope", {"scope": (R.SCOPE_SID + 1, R.SCOPE_LIST_ID, 4)}),
                               ("wrong-kind", {"command": "LOC" if True else "STA"})):
                with self.subTest(case=name, formal=formal):
                    f = self.open_start(formal)
                    exp_command = f.o.jump_expectation.command
                    if name == "wrong-kind":
                        over = {"command": "LOC" if exp_command == "STA" else "STA"}
                    try:
                        text = f.completion_text(**over)
                    except AssertionError:
                        self.skipTest("the wire refuses to format this completion (%s)" % name)
                    f.deliver(text)
                    self.assertEqual(f.o.prev_actual_stop_loc, -1.0)
                    self.assertFalse(f.o.is_scoring_mode, "a failed settlement ends the scoring session: nothing to protect")

    def test_ENT_R12b_malformed_and_missing_completion_text_gives_no_anchor(self):
        f = self.open_start()
        f.deliver("garbage")
        self.assertEqual(f.o.prev_actual_stop_loc, -1.0)

    def test_ENT_R12c_timeout_gives_no_anchor_and_a_late_completion_is_stale(self):
        f = self.open_start()
        text = f.completion_text()
        f.o._abort_unreleased_official_jump(f.jump_transaction.SETTLE_TIMEOUT)
        self.assertEqual(f.o.prev_actual_stop_loc, -1.0)
        f.deliver(text)
        self.assertEqual(f.o.prev_actual_stop_loc, -1.0, "the late completion finds no expectation (unsolicited)")

    def test_ENT_R14_a_completion_of_an_old_generation_or_scenario_gives_no_anchor(self):
        import managed_input
        f = self.open_start()
        text = f.completion_text()
        managed_input.discard_generation_state(f.o)                              # a new scenario generation: the transaction and the pending event are discarded
        f.deliver(text)
        self.assertEqual(f.o.prev_actual_stop_loc, -1.0)
        g = self.open_start()
        text = g.completion_text()
        g.o.current_scenario_id = R.SCOPE_SID + 5                                # the scenario is not the one of the request any more
        g.deliver(text)
        self.assertEqual(g.o.prev_actual_stop_loc, -1.0)

    def test_ENT_R13_a_rejected_retry_gives_no_anchor_and_opens_nothing(self):
        f, _ = self.flow("base")
        o = f.o
        o.prev_actual_stop_loc = -1.0
        o.is_scoring_finished = True
        res = f.main.execute_retry(o, 1, False)
        self.assertFalse(res.accepted)
        self.assertIsNone(o.jump_expectation)
        self.assertEqual(o.prev_actual_stop_loc, -1.0)
        o.is_scoring_finished = False
        res = f.main.execute_retry(o, 99, False)
        self.assertFalse(res.accepted)
        self.assertEqual(o.prev_actual_stop_loc, -1.0)
        self.assertIsNone(o.jump_expectation)

    def test_ENT_R15_a_second_completion_does_not_supply_the_anchor_again(self):
        for formal in (False, True):
            with self.subTest(formal=formal):
                f = self.open_start(formal)
                text = f.completion_text()
                calls = []
                real = f.main.close_range_fix_landing_stop
                with mock.patch.object(f.main, "close_range_fix_landing_stop", lambda *a, **k: (calls.append(a[1:]), real(*a, **k))[1]):
                    f.deliver(text)
                    self.assertEqual(f.o.prev_actual_stop_loc, B_MARK)
                    f.o.prev_actual_stop_loc = 555.0
                    f.deliver(text)                                              # the same completion again (a duplicate)
                self.assertEqual(len(calls), 1, "exactly one supply per accepted completion")
                self.assertEqual(f.o.prev_actual_stop_loc, 555.0, "the duplicate was not settled again")


# ==============================================================================================================================================
# E. CURRENT / LEGACY: the same Python path on both sender shapes, through the managed pipeline (Envelope, DataPlane receiver, jump client, real completion)
# ==============================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class E_CurrentLegacy(unittest.TestCase):
    """The Python scoring is ONE code path for both hosts (tests/test_lc2_current_legacy_equivalence.py): the START completion supplies the same anchor on both sender shapes."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["close-range-entry-managed"])
        import main
        import d6_rig
        import lc_legacy_feed
        import sia_managed_rig
        cls.main, cls.D, cls.F, cls.MR = main, d6_rig, lc_legacy_feed, sia_managed_rig

    def start_and_land(self, shape):
        if getattr(self, '_rig', None) is not None:
            self._rig.close()                                   # one rig at a time
        r = self._rig = self.D.D6Rig(self.main)
        self.addCleanup(r.close)
        o = r.o
        r.go_active(**({"avail": self.F.LEGACY_AVAIL} if shape == "legacy" else {}))
        o.setting_end_idx = 2
        r.start_scoring_via_menu()
        cmd = r.last_command()
        anchors = [o.prev_actual_stop_loc]
        r.send(self.F.line(shape, 1, 36000000, 0.0, 0.0, jump=1, discontinuity=True, NEXTLOC=1000.0))
        r.tick(2)
        anchors.append(o.prev_actual_stop_loc)
        r.complete(cmd["request_id"], location=0.0, time_ms=36000000, count=1)
        r.tick(1)
        anchors.append(o.prev_actual_stop_loc)
        r.tick(3)
        anchors.append(o.prev_actual_stop_loc)
        return anchors, bool(o.is_scoring_mode), bool(o.jump_lock)

    def test_ENT_R16_the_start_anchor_is_the_same_on_the_current_and_the_legacy_shape(self):
        res = {}
        for shape in ("current", "legacy"):
            with self.subTest(shape=shape):
                res[shape] = self.start_and_land(shape)
                anchors, scoring, jump_lock = res[shape]
                self.assertTrue(scoring)
                self.assertEqual(anchors[0], -1.0, "the START reset leaves no anchor")
                self.assertEqual(anchors[1], -1.0, "the JUMP line of the telemetry supplies nothing")
                self.assertEqual(anchors[2:], [0.0, 0.0], "the completion supplies the landing position (the start station at 0.0), and it stays")
        self.assertEqual(res.get("current"), res.get("legacy"))

    def test_ENT_R16b_current_and_legacy_share_one_python_source(self):
        """No host-specific branch in the supply: the helper and its call read nothing of the sender shape."""
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "close_range_fix_landing_stop")
        texts = " ".join(n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(helper) if isinstance(n, (ast.Name, ast.Attribute)))
        for word in ("legacy", "Legacy", "current", "Current", "shape", "host", "AVAIL", "avail"):
            self.assertNotIn(word, texts)

# ==============================================================================================================================================
# D. THE ENTRY COVERAGE GATE (static) - a new entry that reaches B without the supply fails here
# ==============================================================================================================================================
class D_Coverage(unittest.TestCase):
    def source(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_ENT_R20_every_official_entry_to_a_scoring_station_goes_through_the_settlement(self):
        """There is no scoring start without a Jump in the product: the ONLY writer of is_scoring_mode = True is the menu start, and the ONLY callers of begin_official_jump are the menu
        start, execute_retry and (Stage TB-C) the pseudo-turnback request; each opens a jump transaction that only _settle_jump_complete can settle, and that settlement supplies the anchor. A new entry fails this test."""
        main_src, sl_src = self.source("main.py"), self.source("scoring_logic.py")
        self.assertEqual(len(re.findall(r"\bis_scoring_mode\s*=\s*True\b", main_src)) + len(re.findall(r"\bis_scoring_mode\s*=\s*True\b", sl_src)), 1)
        self.assertEqual(len(re.findall(r"(?<!def )\bbegin_official_jump\(self,", main_src)), 1)
        self.assertEqual(len(re.findall(r"(?<!def )\bbegin_official_jump\(self,", sl_src)), 2, "execute_retry and (Stage TB-C) the pseudo-turnback request")
        self.assertEqual(len(re.findall(r"_open_jump_transaction\(jump_transaction\.JUMP_START,", main_src)), 1)
        self.assertEqual(len(re.findall(r"_open_jump_transaction\(jump_transaction\.JUMP_RETRY,", sl_src)), 1)
        self.assertEqual(len(re.findall(r"_open_jump_transaction\(jump_transaction\.JUMP_TURNBACK,", sl_src)), 1)
        for other in ("managed_input.py", "managed_mode.py", "pause_recovery.py"):
            self.assertNotIn("begin_official_jump", self.source(other), other)
            self.assertIsNone(re.search(r"\bis_scoring_mode\s*=\s*True\b", self.source(other)), other)

    def test_ENT_R17_the_supply_is_in_the_settlement_branch_and_searches_nothing(self):
        main_tree, sl_tree = ast.parse(self.source("main.py")), ast.parse(self.source("scoring_logic.py"))
        settle = next(n for n in ast.walk(main_tree) if isinstance(n, ast.FunctionDef) and n.name == "_settle_jump_complete")
        calls = [n for n in ast.walk(settle) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "close_range_fix_landing_stop"]
        self.assertEqual(len(calls), 1, "one supply in the settlement")
        helper = next(n for n in sl_tree.body if isinstance(n, ast.FunctionDef) and n.name == "close_range_fix_landing_stop")
        for n in ast.walk(helper):
            self.assertNotIsInstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp), "the helper searches nothing")
        names = {getattr(n.func, "id", getattr(n.func, "attr", None)) for n in ast.walk(helper) if isinstance(n, ast.Call)}
        self.assertFalse(names & {"abs", "min", "max", "sorted", "enumerate", "next", "any", "all", "find", "index"}, names)

    def test_ENT_R17b_the_supply_comes_after_the_success_judgement_and_never_in_a_failed_branch(self):
        src = self.source("main.py")
        body = src[src.index("def _settle_jump_complete"):src.index("def is_station_timing")]
        pos = body.index("close_range_fix_landing_stop")
        self.assertGreater(pos, body.index("if not verdict.ok:"))
        self.assertGreater(pos, body.index("_finish_jump_transaction(verdict.reason"))
        self.assertEqual(body.count("close_range_fix_landing_stop"), 1)
        self.assertIn("verdict.actual_location", body[pos:pos + 160], "the ACTUAL landing position of the verdict is the source of truth")
        self.assertIn("verdict.selected_idx", body[pos:pos + 160])
        self.assertNotIn("expectation.location", body[pos:pos + 160])


if __name__ == "__main__":
    unittest.main()
