"""TB-RUNTIME-R1 .. R9 (Owner supplement 2026-10-31; promoted at Stage TB-C, OD-TB-25): the OPERATING TIME of a pseudo-turnback section is scored EXACTLY ONCE, at the A arrival, from the A arrival time.
  A arrival: once / the official Jump to B: never / the B departure: never / A and B together: never twice / a late A arrival is scored from the A arrival time and not recomputed with the time of the Jump /
  the next station is scored in the ordinary way / no old state is carried over.
The whole chain runs with the PRODUCT wiring (Stage TB-C): the Jump is requested by the driver of update_physics_and_scoring, completed by the real settlement, B is established and its checkpoint created
by the product. R10 / R11 / R12 of the contract are mutations (tests/mutation, see the TB-C results). The door state is never an input: the matrix of the four door cases is in TheFourDoorCases."""
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

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-pt-runtime-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pt-runtime"])
        import main
        import scoring_logic
        import jump_transaction
        import jump_wire
        import station_identity
        import pt_scene
        cls.main, cls.S, cls.JT, cls.JW, cls.SI, cls.P = main, scoring_logic, jump_transaction, jump_wire, station_identity, pt_scene

    def setUp(self):
        self.calls = []
        self._orig = self.S.apply_time_score

        def spy(owner, diff_s, current_time):
            self.calls.append((diff_s, round(current_time, 3)))
            return self._orig(owner, diff_s, current_time)
        self.S.apply_time_score = spy
        self.addCleanup(lambda: setattr(self.S, "apply_time_score", self._orig))

    def chain(self, late_ms=5000, b_offset=500.0, b_door=False, order="close_then_go", jump_time=None, start=0, end=4, with_pairs=True, until=None, late_target=False):
        """A arrival -> the 5.0 s -> the Jump (PRODUCT request) -> completion -> B established (PRODUCT) -> optional door at B -> the B departure. `snap` holds (time score, spy calls) at each stage."""
        s = self.P.Scene(self, with_pairs=with_pairs)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + b_offset
        if jump_time is not None:
            s.sl[2]["raw_dep"] = jump_time + s.sl[2]["stop_time"]
        t_a = s.arrive_a(late_ms, start, end)
        snap = {"arrival": (o.score_details["time"], len(self.calls))}
        if s.machine.state != M.ARMED:
            return s, snap
        exp = s.run_to_request(t_a)
        self.assertIsNotNone(exp, "the product made the request")
        snap["request"] = (o.score_details["time"], len(self.calls))
        s.jump_tick(late_target)
        s.complete()
        self.assertFalse(o.is_official_jumping)
        snap["jump"] = (o.score_details["time"], len(self.calls))
        if late_target:
            s.target_to_b()
        o.bve_arr_idx = 2
        s.step(10)
        snap["landed"] = (o.score_details["time"], len(self.calls))
        if until == "landed":
            return s, snap
        if b_door:
            s.step(1, bve_door=1, bve_arr_idx=2, bve_arr_seq=2)
            s.step(20)
        snap["landed_door"] = (o.score_details["time"], len(self.calls))
        s.depart_b(order)
        snap["departed"] = (o.score_details["time"], len(self.calls))
        return s, snap

    # ---- the Owner's list -------------------------------------------------------------------------------------------------------------------------
    def test_TB_RUNTIME_R1_the_operating_time_is_scored_once_at_the_A_arrival(self):
        s, snap = self.chain()
        self.assertEqual(snap["arrival"], (300, 1))
        self.assertEqual(len(self.calls), 1)

    def test_TB_RUNTIME_R1_an_operational_stop_A_arrival_also_scores_the_operating_time_once(self):
        s = self.P.Scene(self)
        o = s.o
        o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        o.bve_next_time = self.P.T0 + 90000
        s.approach("plain")
        o.bve_doordir = 0
        o.is_approaching = True
        s.step(4, bve_speed=0.0, bve_location=self.P.A_MARK - 0.3, bve_brk_notch=8, bve_doordir=0)
        self.assertEqual(s.machine.state, M.ARMED)
        self.assertEqual((o.score_details["time"], len(self.calls)), (300, 1))
        for _ in range(300):
            s.tick(16)
        self.assertEqual(len(self.calls), 1)

    def test_TB_RUNTIME_R2_the_official_Jump_to_B_scores_no_operating_time(self):
        for b_offset in (500.0, 5.0, 0.0):
            for late_target in (False, True):
                with self.subTest(b_offset=b_offset, late_target=late_target):
                    self.calls.clear()
                    s, snap = self.chain(b_offset=b_offset, late_target=late_target)
                    self.assertEqual((snap["request"], snap["jump"]), ((300, 1), (300, 1)))

    def test_TB_RUNTIME_R3_the_B_departure_scores_no_operating_time_in_every_order_and_door_state(self):
        for b_offset in (500.0, 5.0, 0.0):
            for b_door in (False, True):
                for order in ("close_then_go", "moving_switch"):
                    for late_target in (False, True):
                        with self.subTest(b_offset=b_offset, b_door=b_door, order=order, late_target=late_target):
                            self.calls.clear()
                            s, snap = self.chain(b_offset=b_offset, b_door=b_door, order=order, late_target=late_target)
                            self.assertEqual(snap["landed"], (300, 1))
                            self.assertEqual(snap["departed"], (300, 1), "OD-TB-25: the same result in every telemetry order")

    def test_TB_RUNTIME_R4_no_double_scoring_between_the_A_arrival_and_the_B_departure(self):
        for late_ms in (5000, 25000):
            for order in ("close_then_go", "moving_switch"):
                with self.subTest(late_ms=late_ms, order=order):
                    self.calls.clear()
                    s, snap = self.chain(late_ms=late_ms, b_door=True, order=order)
                    self.assertEqual(len(self.calls), 1)
                    self.assertEqual(snap["departed"][0], snap["arrival"][0])

    def test_TB_RUNTIME_R5_a_late_A_arrival_is_scored_from_the_A_arrival_time(self):
        s, snap = self.chain(late_ms=25000)
        self.assertEqual(snap["arrival"], (100, 1), "25 s late -> the 100 point band, from the A arrival")
        self.assertEqual(len(self.calls), 1)
        self.assertIn(abs(self.calls[0][0]), (25, 26), "the difference is the one of the A arrival (floored seconds), not one derived from the Jump")
        self.assertEqual(snap["departed"][0], 100)

    def test_TB_RUNTIME_R6_the_time_of_the_Jump_to_B_never_recomputes_the_time_up_to_A(self):
        results = []
        for jump_time in (self.P.T0 + 60000, self.P.T0 + 200000):                 # a Jump time before and after the scheduled arrival of A
            self.calls.clear()
            s, snap = self.chain(late_ms=25000, jump_time=jump_time)
            results.append((snap["arrival"], snap["jump"], len(self.calls)))
        self.assertEqual(results[0], ((100, 1), (100, 1), 1))
        self.assertEqual(results[0], results[1])

    def test_TB_RUNTIME_R7_an_A_that_is_the_end_station_scores_at_the_arrival_and_ends(self):
        s, snap = self.chain(start=0, end=1)
        self.assertEqual(snap["arrival"], (300, 1))
        self.assertTrue(s.o.is_scoring_finished)
        self.assertEqual(s.machine.state, M.IDLE)
        self.assertEqual(len(self.calls), 1)

    def test_TB_RUNTIME_R8_a_start_at_B_generates_no_operating_time_of_A(self):
        s, snap = self.chain(start=2, end=4)
        self.assertEqual((snap["arrival"], len(self.calls)), ((0, 0), 0))
        self.assertEqual(s.machine.state, M.IDLE)

    def test_TB_RUNTIME_R9_a_section_that_does_not_cross_A_to_B_equals_the_result_without_the_feature(self):
        def result(with_pairs, start, end, swap):
            self.calls.clear()
            s = self.P.Scene(self, with_pairs=with_pairs)
            o = s.o
            if swap:
                s.sl[1], s.sl[3] = s.sl[3], s.sl[1]
                o.bve_tgt_idx = 3
            o.setting_start_idx, o.setting_end_idx = start, end
            o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
            o.bve_next_time = self.P.T0 + 90000
            s.approach("stepwise")
            s.stop_at(0.0)
            s.open_door()
            for _ in range(400):
                s.tick(16)
            return (o.score, dict(o.score_details), sorted(p["text"] for p in o.popups), [c["station_index"] for c in o.save_data], bool(o.is_scoring_finished), list(self.calls))
        for start, end, swap in ((0, 1, False), (2, 3, True)):
            self.assertEqual(result(True, start, end, swap), result(False, start, end, swap), (start, end))

    # ---- OD-TB-25 additions -------------------------------------------------------------------------------------------------------------------------
    def test_OD25_1_to_4_the_B_operating_time_is_marked_at_the_establishment_whatever_the_door_and_the_order_do(self):
        for late_target in (False, True):
            with self.subTest(late_target=late_target):
                s, snap = self.chain(b_offset=500.0, until="landed", late_target=late_target)
                self.assertTrue(s.o.has_scored_time_this_station, "marked when B was established")
                self.assertEqual(len([c for c in s.o.save_data if c.get("origin") == "turnback"]), 1)

    def test_OD25_6_A_scores_once_B_zero_the_total_is_once(self):
        for order in ("close_then_go", "moving_switch"):
            self.calls.clear()
            s, snap = self.chain(b_door=True, order=order)
            self.assertEqual(len(self.calls), 1)

    def test_OD25_7_after_the_chain_the_next_station_is_scored_in_the_ordinary_way(self):
        for order in ("close_then_go", "moving_switch"):
            for b_door in (False, True):
                with self.subTest(order=order, b_door=b_door):
                    self.calls.clear()
                    s, snap = self.chain(b_offset=500.0, b_door=b_door, order=order)
                    n_before = len(self.calls)
                    o, P = s.o, self.P
                    c = s.sl[3]
                    c["raw_dep"] = P.T0 + 400000
                    o.bve_is_pass = 0
                    o.bve_margin_f = o.bve_margin_b = 5.0
                    s.step(1, bve_speed=5.0, bve_location=c["location"] - 100.0, bve_brk_notch=4)
                    s.step(1, bve_speed=2.0, bve_location=c["location"] - 10.0, bve_brk_notch=4)
                    s.step(3, bve_speed=0.0, bve_location=c["location"] - 0.3, bve_brk_notch=8)
                    s.step(1, bve_door=1, bve_arr_idx=3, bve_arr_seq=3)
                    s.step(10)
                    o.bve_time_ms = c["raw_dep"] - 100
                    o.bve_next_time = c["raw_dep"]
                    s.step(2, bve_door=0, bve_speed=0.0)
                    s.step(1, advance_ms=100, bve_next_loc=s.sl[4]["location"], bve_tgt_idx=4, bve_speed=0.0)
                    s.step(3, bve_speed=1.5, bve_location=c["location"] + 3.0)
                    self.assertEqual(len(self.calls) - n_before, 1, "the departure from the next station scores its operating time once, whatever happened at B")

    def test_OD25_8_no_old_state_is_carried_over(self):
        import managed_input
        for event in ("generation", "session-off", "new-start"):
            with self.subTest(event=event):
                s, snap = self.chain(b_offset=500.0, until="landed")
                o = s.o
                self.assertTrue(o.has_scored_time_this_station)
                if event == "generation":
                    managed_input.discard_generation_state(o)
                    self.assertNotIn("turnback_machine", o.__dict__)
                elif event == "session-off":
                    managed_input.discard_scoring_session(o)
                else:
                    o.is_scoring_mode = False
                    o.menu_state, o.menu_cursor = 10, 1
                    o.scoring_start_gate = None
                    o.was_advancing_before_menu = False
                    s.auto_fix = False
                    self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
                    o.handle_menu_enter(False)
                    self.assertTrue(o.is_scoring_mode)
                self.assertFalse(o.has_scored_time_this_station)

    def retry_to_b(self, origin, late_target=False):
        s = self.P.Scene(self)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + 500.0
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.jump_tick()
        s.complete()
        o.bve_arr_idx = 2
        s.step(10)
        self.assertEqual(o.save_data[-1].get("origin"), "turnback")
        if origin is None:
            o.save_data[-1].pop("origin", None)                       # an ordinary checkpoint of the same StationIndex
        if late_target:
            s.depart_b("close_then_go")                       # the train went on toward C: the target of the Retry landing really is a LATER switch (C -> B)
            self.assertEqual(o.bve_tgt_idx, 3)
        result = self.main.execute_retry(o, len(o.save_data) - 1, False)
        self.assertTrue(result.accepted, result)
        s.jump_tick(late_target)
        s.complete()
        if late_target:
            s.tick(16)
            self.assertFalse(o.has_scored_time_this_station, "not before the B target of the Retry landing is there")
            s.target_to_b()
        o.bve_arr_idx = 2
        s.step(10)
        before = o.score_details["time"]
        mark = o.has_scored_time_this_station
        s.depart_b("close_then_go")
        return mark, before, o.score_details["time"]

    def test_OD25_5_a_retry_to_the_turnback_checkpoint_marks_B_and_the_departure_scores_nothing(self):
        mark, before, after = self.retry_to_b("turnback")
        self.assertTrue(mark)
        self.assertEqual(after, before)

    def test_OD25_5b_the_Retry_mark_also_survives_a_late_target_switch(self):
        mark, before, after = self.retry_to_b("turnback", late_target=True)
        self.assertTrue(mark)
        self.assertEqual(after, before)

    def test_OD25_9_a_retry_to_an_ordinary_checkpoint_of_the_same_station_keeps_the_ordinary_rule(self):
        mark, before, after = self.retry_to_b(None)
        self.assertFalse(mark, "no origin=turnback: no mark")
        self.assertEqual(after - before, 300, "the ordinary Retry rule (is_official_retry) scores the departure")

    def test_OD25_11_the_retry_mark_waits_for_the_successful_settlement(self):
        s = self.P.Scene(self)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + 500.0
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.jump_tick()
        s.complete()
        o.bve_arr_idx = 2
        s.step(10)
        self.assertTrue(self.main.execute_retry(o, len(o.save_data) - 1, False).accepted)
        s.jump_tick()
        self.assertTrue(o.is_official_jumping, "the transaction is still open here")
        self.assertFalse(o.has_scored_time_this_station, "no B mark before the completion proved the Jump")


class TheFourDoorCases(Base):
    """E54 (fixtures only, no live PASS): A closed / open x B closed / open. The expectation is the same in all four: the arrival at A is judged, A's operating time once, one Jump, B's checkpoint once,
    nothing at the B departure, the next station in the ordinary way."""
    def case(self, a_open, b_open):
        s = self.P.Scene(self)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + 500.0
        o.setting_start_idx, o.setting_end_idx = 0, 4
        o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        o.bve_next_time = self.P.T0 + 90000
        s.approach("plain")
        if a_open:
            s.stop_at(0.3)
            t_a = s.open_door()
        else:
            o.bve_doordir = 0
            o.is_approaching = True
            s.step(4, bve_speed=0.0, bve_location=self.P.A_MARK - 0.3, bve_brk_notch=8, bve_doordir=0)
            t_a = o.bve_time_ms
        self.assertEqual(s.machine.state, M.ARMED, "the arrival is judged")
        s.run_to_request(t_a)
        s.jump_tick()
        s.complete()
        o.bve_arr_idx = 2
        s.step(10)
        if b_open:
            s.step(1, bve_door=1, bve_arr_idx=2, bve_arr_seq=2)
            s.step(20)
        s.depart_b("moving_switch")
        return s

    def test_the_four_door_cases_have_the_same_result(self):
        results = []
        for a_open in (False, True):
            for b_open in (False, True):
                with self.subTest(a_open=a_open, b_open=b_open):
                    self.calls.clear()
                    s = self.case(a_open, b_open)
                    o = s.o
                    results.append((len(self.calls), o.score_details["time"], len([c for c in o.save_data if c.get("origin") == "turnback"]), s.machine.state))
        self.assertEqual(results, [(1, 300, 1, M.IDLE)] * 4)


if __name__ == "__main__":
    unittest.main()
