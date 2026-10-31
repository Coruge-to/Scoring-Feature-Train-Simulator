"""Stage TB-D, slice D4 (OD-TD-5, entry E33): the REAL flow A arrival -> 5.0 s -> request -> completion -> B established -> B departure -> arrival at the next station C, driven by the product only
(update_physics_and_scoring, _note_jump_complete, _settle_jump_complete, the turnback driver), for a CLOSE pair B -> C (inside the stop distance: the O1 protection) and a FAR pair, in the EARLY and the LATE
target order, compared with the reference that O1 closed: a scoring START at the same B in the same placement. E33 DEVELOPMENT FLOW PASS needs all of: (1) product-driven flow, (2) close / far x early / late, (3) results
equal to the START-at-B reference (checkpoint content, anchor), (4) the pending state of the close-range departure reset follows the O1 rule and the arrival at C is scored in the ordinary way,
(5) the mutations are detected (mutation run), (6) the existing O1 / TB-C tests stay green (full regression). It is a DEVELOPMENT flow: nothing here is a BVE acceptance."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbd-flow-")
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
    CLOSE, FAR = 49.4, 800.0

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbd-flow"])
        import main
        import scoring_logic
        import pt_scene
        cls.main, cls.S, cls.P = main, scoring_logic, pt_scene

    def spy_time(self):
        calls = []
        original = self.S.apply_time_score

        def spy(owner, diff_s, current_time):
            calls.append(round(current_time, 3))
            return original(owner, diff_s, current_time)
        self.S.apply_time_score = spy
        self.addCleanup(lambda: setattr(self.S, "apply_time_score", original))
        return calls

    # ---- the two landings at B -----------------------------------------------------------------------------------------------------------------
    def land(self, purpose, c_dist, late):
        P = self.P
        s = P.Scene(self)
        o = s.o
        s.sl[3]["location"] = s.sl[2]["location"] + c_dist
        s.sl[3]["raw_dep"] = P.T0 + 400000
        if purpose == "turnback":
            t_a = s.arrive_a()
            s.run_to_request(t_a)
            self.assertEqual(s.machine.state, M.REQUESTED)
        else:
            s.arrive_a(start=2)
            s.auto_fix = False
            o.is_scoring_mode = False
            o.menu_state, o.menu_cursor = 10, 1
            o.scoring_start_gate = None
            o.was_advancing_before_menu = False
            P.R.bind_identity(o, arr_idx=1, tgt_idx=2)
            o.handle_menu_enter(False)
        exp = o.jump_expectation
        self.assertIsNotNone(exp)
        jump_time = exp.time_ms
        s.jump_tick(late)
        s.complete()
        if late:
            s.target_to_b()
        o.bve_arr_idx = 2
        s.step(10)
        landed = {"score": o.score, "details": dict(o.score_details), "popups": [(p["category"], p["text"]) for p in o.popups],
                  "anchor": o.prev_actual_stop_loc, "jump_time": jump_time}
        return s, landed

    def tail(self, s, c_dist):
        """B departure (close_then_go) -> the arrival at C. Returns what happened after the landing."""
        o = s.o
        b, c = s.sl[2], s.sl[3]
        trace = {}
        o.bve_time_ms = b["raw_dep"] - 100
        o.bve_next_time = b["raw_dep"]
        s.step(2, bve_door=0, bve_speed=0.0)
        s.step(1, advance_ms=100, bve_next_loc=c["location"], bve_tgt_idx=3, bve_speed=0.0)
        trace["pending_at_switch"] = bool(o.close_range_departure_reset_pending)
        s.step(3, bve_speed=1.5, bve_location=b["location"] + 3.0)
        trace["pending_after_first_move"] = bool(o.close_range_departure_reset_pending)
        cl = c["location"]
        o.bve_is_pass = 0
        s.step(1, bve_speed=5.0, bve_location=cl - 30.0, bve_brk_notch=4)
        s.step(1, bve_speed=2.0, bve_location=cl - 10.0, bve_brk_notch=4)
        s.step(3, bve_speed=0.0, bve_location=cl - 0.3, bve_brk_notch=8)
        s.step(1, bve_door=1, bve_arr_idx=3, bve_arr_seq=3)
        s.step(10)
        trace["stations_of_the_history"] = [cp.get("station_index") for cp in o.save_data]
        return trace


class A_TheFlowEqualsTheStartAtB(Base):
    def run_both(self, c_dist, late):
        out = {}
        for purpose in ("start", "turnback"):
            calls = self.spy_time()
            s, landed = self.land(purpose, c_dist, late)
            before_calls = len(calls)
            trace = self.tail(s, c_dist)
            o = s.o
            out[purpose] = {
                "landed": landed, "trace": trace,
                "score_delta": o.score - landed["score"],
                "details_delta": {k: o.score_details[k] - landed["details"][k] for k in o.score_details},
                "new_popups": sorted((p["category"], p["text"]) for p in o.popups if (p["category"], p["text"]) not in landed["popups"]),
                "time_calls_after_landing": len(calls) - before_calls,
                "history_tail": [(cp.get("station_index"), cp.get("origin")) for cp in o.save_data][-2:],
            }
        return out

    def test_RF_1_RF_2_the_close_and_the_far_pair_in_both_target_orders_end_as_the_start_at_B_does(self):
        for c_dist, close in ((self.CLOSE, True), (self.FAR, False)):
            for late in (False, True):
                with self.subTest(close=close, late=late):
                    r = self.run_both(c_dist, late)
                    t, s = r["turnback"], r["start"]
                    self.assertEqual(t["trace"]["pending_at_switch"], close, "the O1 protection is raised at the B -> C switch only for a close pair")
                    self.assertFalse(t["trace"]["pending_after_first_move"], "released by the first positive movement")
                    self.assertEqual(t["trace"]["pending_at_switch"], s["trace"]["pending_at_switch"])
                    self.assertEqual(t["trace"]["pending_after_first_move"], s["trace"]["pending_after_first_move"])
                    self.assertTrue(t["new_popups"], "the arrival at C was scored (not vacuous)")
                    self.assertEqual(t["new_popups"], s["new_popups"], "the arrival at C is scored in the ordinary way, once")
                    self.assertEqual(t["score_delta"], s["score_delta"])
                    self.assertEqual(t["details_delta"], s["details_delta"])
                    self.assertEqual(t["time_calls_after_landing"], s["time_calls_after_landing"])
                    self.assertEqual(t["trace"]["stations_of_the_history"][-1], s["trace"]["stations_of_the_history"][-1], "the checkpoint of C is made as ever")

    def test_RF_3_the_B_checkpoint_has_the_content_of_the_start_at_B_checkpoint(self):
        for late in (False, True):
            with self.subTest(late=late):
                st, st_landed = self.land("start", self.FAR, late)
                tb, tb_landed = self.land("turnback", self.FAR, late)
                cp_start = st.o.save_data[0]
                cp_turn = [cp for cp in tb.o.save_data if cp.get("origin") == "turnback"]
                self.assertEqual(len(cp_turn), 1, "one B checkpoint")
                cp_turn = cp_turn[0]
                for key in ("station_index", "scope", "station_location", "stop_error"):
                    self.assertEqual(cp_turn[key], cp_start[key], key)
                self.assertEqual(cp_turn["time_ms"], tb_landed["jump_time"], "the time of the Jump to B")
                self.assertEqual(cp_turn["time_ms"], st_landed["jump_time"], "= the time of a start at B")
                self.assertEqual(cp_turn["score"], tb_landed["score"], "the latest score at the landing")
                self.assertEqual(cp_turn["role"], "arrived_station")
                self.assertEqual([cp.get("station_index") for cp in tb.o.save_data if cp.get("station_index") == 1], [], "the A has no checkpoint")

    def test_RF_4_the_anchor_after_the_landing_is_the_actual_landing_position_in_both_flows(self):
        for late in (False, True):
            with self.subTest(late=late):
                st, a = self.land("start", self.CLOSE, late)
                tb, b = self.land("turnback", self.CLOSE, late)
                self.assertEqual(a["anchor"], st.sl[2]["location"])
                self.assertEqual(b["anchor"], a["anchor"])
                self.assertEqual(tb.o.bve_tgt_idx, 2)
                self.assertFalse(tb.o.is_official_jumping)

    def test_RF_5_the_target_moves_to_the_next_station_and_the_B_departure_scores_no_operating_time(self):
        for late in (False, True):
            with self.subTest(late=late):
                calls = self.spy_time()
                s, landed = self.land("turnback", self.FAR, late)
                n = len(calls)
                o = s.o
                b, c = s.sl[2], s.sl[3]
                o.bve_time_ms = b["raw_dep"] - 100
                o.bve_next_time = b["raw_dep"]
                s.step(2, bve_door=0, bve_speed=0.0)
                s.step(1, advance_ms=100, bve_next_loc=c["location"], bve_tgt_idx=3, bve_speed=0.0)
                s.step(3, bve_speed=1.5, bve_location=b["location"] + 3.0)
                self.assertEqual((o.bve_tgt_idx, o.bve_next_loc), (3, c["location"]), "the NEXTLOC switch to the next station")
                self.assertEqual(len(calls), n, "the departure from B scores no operating time")
                self.assertEqual(o.score, landed["score"])

    def test_RF_6_a_door_edge_at_B_after_the_landing_scores_no_arrival_again(self):
        calls = self.spy_time()
        s, landed = self.land("turnback", self.FAR, False)
        o = s.o
        n = len(calls)
        popups = [(p["category"], p["text"]) for p in o.popups]
        s.step(1, bve_door=1, bve_arr_idx=2, bve_arr_seq=2)
        s.step(20)
        self.assertEqual(len(calls), n)
        self.assertEqual(o.score, landed["score"])
        self.assertEqual([(p["category"], p["text"]) for p in o.popups if (p["category"], p["text"]) not in popups], [])


if __name__ == "__main__":
    unittest.main()
