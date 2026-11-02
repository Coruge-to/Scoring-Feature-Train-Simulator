"""Stage TB-K: the remaining-time field in FREE DRIVING after the stop at a pseudo-turnback pair A (Owner decision 2026-11-03, plan P).

Contract: no scoring session. The display latch (Overlay._free_turnback_a_latch, read through free_turnback_a_time_suppressed) is set only when THREE facts hold at once: the host target is the A of a static
PairSet pair, the speed is exactly 0.0, and the train stands inside the stop range the author defined for that target (the target's margins and position). A open / A closed are not told apart; the door, the
indicator lamp, the signal flag and the station name are no input. From then on the field is --:-- (also after the train moves and the target goes to B): never A's completed departure, B's completed arrival,
a Jump countdown, a negative remaining time against A's arrival time. Before the stop (approach, outside the range, a pass without a stop, a speed that is not 0) the ordinary display.
The latch is NOT an arrival, scoring, history, checkpoint, StationIndex or target source. It ends with a scoring session, F5 / a new scenario, a ScenarioGeneration change, a changed or missing PairSet, a vanished pair,
and a target beyond the pair (no speed or position ever ends it: the free driving has no safe arrival source for the B). Ordinary stops, the terminal and the scoring contract (TB-J) are untouched.
The REAL draw_hud and the REAL Overlay are driven; the inputs are the ones the application has in free driving (the host target with its margins, speed, position, BVE time)."""
import ast
import inspect
import os
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbj_remaining_time import RtBase, setUpModule, tearDownModule, source  # noqa: E402,F401

A, B, C_IDX, TERM = 1, 2, 3, 4
DASH = "--:--"


class FdBase(RtBase):
    def fscene(self):
        s, t, f = self.scene()
        o = s.o
        s.machine.discard_all()
        o.is_scoring_mode = False
        o.is_scoring_finished = False
        o.bve_arr_idx, o.bve_arr_seq = -1, -1
        return s

    def fd(self, s, index, speed=0.0, dist=-1.0, dt=0, door=0, margin_b=5.0, margin_f=5.0):
        """One free-driving observation: the host target = station `index`; the train stands `dist` m before it (negative = past it) at `speed`; BVE time = the station's arrival time + dt."""
        from official_target_contract import KNOWN
        o = s.o
        st = s.sl[index]
        o.is_scoring_mode, o.is_scoring_finished = False, False
        o.official_state, o.official_index, o.official_location = KNOWN, index, st["location"]
        o.official_margin_b, o.official_margin_f = margin_b, margin_f
        o.official_reason = ""
        o.bve_door = door
        o.bve_speed = speed
        o.bve_location = st["location"] - dist
        base = st["raw_arr"] if st.get("raw_arr", -1) > 0 else (st["raw_dep"] if st.get("raw_dep", -1) > 0 else self.P.T0 + 90000)
        o.bve_time_ms = base + dt
        return self.left(s)

    def latched(self, s):
        return s.o.free_turnback_a_time_suppressed()


class A_Arrival(FdBase):
    def test_FD_01_GUARD_before_the_stop_the_ordinary_display(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=20.0, dist=300.0, dt=-30000), "00:30")
        self.assertEqual(self.fd(s, A, speed=5.0, dist=20.0, dt=-5000), "00:05")
        self.assertFalse(self.latched(s))

    def test_FD_02_A_open_after_the_stop_shows_dashes(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000, door=1), DASH)
        self.assertTrue(self.latched(s))

    def test_FD_03_A_closed_after_the_stop_shows_dashes(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000, door=0), DASH)
        self.assertTrue(self.latched(s))

    def test_FD_04_05_06_A_closed_never_the_arrival_time_remaining_zero_or_negative(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-30000), DASH, "no 00:30")
        for dt in (-1000, 0, 1000, 20000, 90000):
            self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=dt), DASH, "dt=%d: no 00:00, no negative" % dt)

    def test_FD_07_08_no_completed_A_departure_or_B_arrival_is_shown(self):
        s = self.fscene()
        self.assertEqual(s.sl[A]["raw_dep"], -1)
        self.assertEqual(s.sl[B]["raw_arr"], -1)
        s.sl[A]["def_time"] = s.sl[A]["raw_arr"] + 15000                    # whatever completion a sender could add: never a Python input
        s.sl[B]["def_time"] = s.sl[B]["raw_dep"] - 15000
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=5000), DASH)
        self.assertEqual(self.fd(s, B, speed=0.0, dist=1.0, dt=0, door=0), DASH, "the B shows no arrival time")

    def test_FD_09_free_driving_never_shows_a_Jump_countdown(self):
        s = self.fscene()
        self.fd(s, A, speed=0.0, dist=1.0, dt=-3000)
        self.assertNotIn(s.o.turnback_remaining_view(), (("count", 10000), ("count", 5000), ("count", 0)))
        self.assertEqual(s.o.turnback_remaining_view(), ("dashes", None))

    def test_FD_10_the_approach_alone_does_not_latch(self):
        s = self.fscene()
        for dist in (500.0, 100.0, 30.0, 6.0):
            self.assertNotEqual(self.fd(s, A, speed=3.0, dist=dist, dt=-20000), DASH, dist)
        self.assertFalse(self.latched(s))

    def test_FD_11_a_stop_outside_the_author_range_does_not_latch(self):
        s = self.fscene()
        self.assertNotEqual(self.fd(s, A, speed=0.0, dist=20.0, dt=-3000), DASH, "20 m before the A: outside the +-5 m range")
        self.assertNotEqual(self.fd(s, A, speed=0.0, dist=-20.0, dt=-3000), DASH, "20 m past the A")
        self.assertFalse(self.latched(s))

    def test_FD_11b_the_author_margins_decide_not_a_fixed_range_and_the_front_back_sides_are_the_authors(self):
        s = self.fscene()
        self.assertNotEqual(self.fd(s, A, speed=0.0, dist=3.0, dt=-3000, margin_b=2.0, margin_f=8.0), DASH, "3 m before the A, the back margin is 2 m")
        self.assertEqual(self.fd(s, A, speed=0.0, dist=-6.0, dt=-3000, margin_b=2.0, margin_f=8.0), DASH, "6 m past the A, the front margin is 8 m")

    def test_FD_12_passing_the_A_without_a_stop_does_not_latch(self):
        s = self.fscene()
        for dist in (10.0, 3.0, 0.0, -3.0, -10.0):
            self.assertNotEqual(self.fd(s, A, speed=15.0, dist=dist, dt=-2000), DASH, "passing at 15 km/h, dist=%s" % dist)
        self.assertFalse(self.latched(s))

    def test_FD_12b_a_speed_that_is_not_zero_does_not_latch_even_inside_the_range(self):
        s = self.fscene()
        for speed in (0.001, 0.1, 1.0, -0.5):
            self.assertNotEqual(self.fd(s, A, speed=speed, dist=1.0, dt=-3000), DASH, speed)
        self.assertFalse(self.latched(s))

    def test_FD_12c_neither_the_position_nor_the_time_alone_latches(self):
        s = self.fscene()
        self.assertNotEqual(self.fd(s, A, speed=2.0, dist=0.0, dt=60000), DASH, "in the range, moving, long after the arrival time")
        self.assertNotEqual(self.fd(s, A, speed=0.0, dist=50.0, dt=60000), DASH, "stopped, far from the A, long after the arrival time")

    def test_FD_12d_a_stop_at_the_B_or_at_an_ordinary_station_alone_never_latches(self):
        s = self.fscene()
        s.sl[B]["raw_dep"] = self.P.T0 + 150000
        self.fd(s, B, speed=0.0, dist=1.0, dt=-3000, door=1)
        self.assertFalse(self.latched(s), "only the A of a pair latches")
        s.sl[C_IDX]["raw_arr"] = self.P.T0 + 200000
        self.fd(s, C_IDX, speed=0.0, dist=1.0, dt=-3000)
        self.assertFalse(self.latched(s))


class B_AfterTheStop(FdBase):
    def test_FD_13_the_dashes_stay_when_the_train_moves_and_the_target_goes_to_B(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        self.assertEqual(self.fd(s, A, speed=2.0, dist=0.0, dt=-2000), DASH, "moving again, the target is still A")
        self.assertEqual(self.fd(s, A, speed=8.0, dist=-30.0, dt=-1000), DASH, "left the range, the target is still A")
        self.assertEqual(self.fd(s, B, speed=8.0, dist=40.0, dt=0), DASH, "the target is B now")
        self.assertTrue(self.latched(s))

    def test_FD_14_the_latch_is_kept_at_the_B_and_ends_with_the_target_beyond_the_pair(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.sl[B]["raw_dep"] = s.o.bve_time_ms + 40000
        self.assertEqual(self.fd(s, B, speed=0.0, dist=1.0, dt=-40000, door=1), DASH, "at the B: no speed / position ever ends the latch (no safe B arrival source in free driving)")
        s.sl[C_IDX]["raw_arr"] = s.o.bve_time_ms + 60000
        self.assertEqual(self.fd(s, C_IDX, speed=10.0, dist=200.0, dt=-60000), "01:00", "the target is the ordinary station after the B: the ordinary display")
        self.assertFalse(self.latched(s))
        self.assertNotEqual(self.fd(s, A, speed=10.0, dist=100.0, dt=-60000), DASH, "an old A state is not left: the A approached again without a stop")

    def test_FD_14c_a_target_before_the_pair_ends_the_latch(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.sl[0]["raw_arr"] = s.o.bve_time_ms + 30000
        self.fd(s, 0, speed=10.0, dist=100.0, dt=-30000)
        self.assertFalse(self.latched(s))

    def test_FD_15_F5_drops_the_latch(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.o.apply_telemetry_text("SCENARIO_ID:%d" % (getattr(s.o, "current_scenario_id", 0) + 7))
        self.assertFalse(self.latched(s), "reset_telemetry_state / the scenario change drop it at once")
        self.assertNotEqual(self.fd(s, A, speed=15.0, dist=100.0, dt=-20000), DASH)

    def test_FD_15b_the_epoch_reset_of_a_new_scenario_instance_drops_the_latch(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.o.reset_telemetry_state()
        self.assertFalse(self.latched(s))

    def test_FD_16_a_ScenarioGeneration_change_drops_the_latch(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.o.current_scenario_id = getattr(s.o, "current_scenario_id", 0) + 1
        self.assertNotEqual(self.fd(s, A, speed=15.0, dist=100.0, dt=-20000), DASH)
        self.assertFalse(self.latched(s))

    def test_FD_17_a_PairSet_change_drops_the_latch(self):
        import pseudo_turnback_contract
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        ps, why = pseudo_turnback_contract.decode_ptpair("PTPAIR:1:%s:5:1:3-4-0" % self.P.R.SCOPE_LIST_ID, 5)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        self.assertNotEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH, "A is no pair A of the new set")
        self.assertFalse(self.latched(s))

    def test_FD_17b_a_missing_PairSet_drops_the_latch_and_the_station_is_ordinary(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.machine.pairset = None
        self.assertNotEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        self.assertFalse(self.latched(s))

    def test_FD_17c_a_vanished_pair_drops_the_latch(self):
        import pseudo_turnback_contract
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        ps, why = pseudo_turnback_contract.decode_ptpair("PTPAIR:1:%s:5:1:2-3-0" % self.P.R.SCOPE_LIST_ID, 5)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        self.fd(s, B, speed=5.0, dist=40.0, dt=0)
        self.assertFalse(self.latched(s), "the pair of the latch (A = 1) is gone from the set")

    def test_FD_17d_a_transient_unavailable_target_keeps_the_latch(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        s.o.official_state = "UNAVAILABLE"
        self.left(s)
        self.assertTrue(self.latched(s), "a missing target is no boundary of the pair")
        self.assertEqual(self.fd(s, B, speed=8.0, dist=40.0, dt=0), DASH)


class C_Scoring(FdBase):
    def scope_latched_scene(self):
        s = self.fscene()
        self.assertEqual(self.fd(s, A, speed=0.0, dist=1.0, dt=-3000), DASH)
        return s

    def test_FD_18_a_scoring_start_drops_the_latch_and_the_scoring_view_is_the_TB_J_one(self):
        s = self.scope_latched_scene()
        o = s.o
        o.is_scoring_mode, o.is_scoring_finished = True, False
        o._hud_target_sync()
        self.assertFalse(self.latched(s), "the scoring session owns the field: the latch is dropped at once")
        self.assertIsNone(o.turnback_remaining_view(), "no chain: the ordinary scoring display (the machine target)")

    def test_FD_19_a_preset_latch_never_reaches_a_scoring_display(self):
        s, t, f = self.scene()
        o = s.o
        station_list = o.station_list
        o._free_turnback_a_latch = ((getattr(o, "current_scenario_id", None), getattr(station_list, "list_id", None)), A)
        self.assertEqual((o.turnback_remaining_view(), self.left(s)), (("count", 10000), "00:10"), "first window of a scoring Run: 00:10, whatever the latch says")
        self.assertFalse(self.latched(s))
        self.move(s, t + 2000)
        self.assertEqual((o.turnback_remaining_view(), self.left(s)), (("dashes", None), "--:--"), "cancel: --:-- from the machine, not from the latch")
        self.restop(s, t + 3000)
        self.assertEqual(self.left(s), "00:05")

    def test_FD_20_21_22_23_24_the_TB_J_contract_is_the_existing_one(self):
        """The 37 + 9 tests of tests/test_pt_tbj_remaining_time.py and tests/test_pt_tbj_discard_gate.py are the evidence (00:10 / --:-- / 00:05 / 00:00 / B raw_dep); they run unchanged with this stage."""
        s, t, f = self.scene()
        self.assertEqual((s.o.turnback_remaining_view(), self.left(s)), (("count", 10000), "00:10"))

    def test_FD_26_a_scoring_end_starts_clean(self):
        s = self.scope_latched_scene()
        o = s.o
        o.is_scoring_mode, o.is_scoring_finished = True, False
        o._hud_target_sync()
        o.bve_speed = 5.0                                                  # the train is moving again when the Run ends
        o.is_scoring_mode, o.is_scoring_finished = False, True
        o._hud_target_sync()
        self.assertFalse(self.latched(s), "nothing of the old free driving is left for the time after the Run")


class D_Untouched(FdBase):
    def test_FD_27_an_ordinary_stop_station_keeps_its_remaining_time(self):
        s = self.fscene()
        s.sl[C_IDX]["raw_arr"] = self.P.T0 + 200000
        s.sl[C_IDX]["raw_dep"] = self.P.T0 + 230000
        self.assertEqual(self.fd(s, C_IDX, speed=0.0, dist=1.0, dt=-3000, door=0), "00:03")
        self.assertEqual(self.fd(s, C_IDX, speed=0.0, dist=1.0, dt=5000, door=0), "-00:05")
        self.assertEqual(self.fd(s, C_IDX, speed=0.0, dist=1.0, dt=-20000, door=1), "00:50")
        self.assertFalse(self.latched(s))

    def test_FD_28_the_terminal_keeps_its_arrival_and_the_freeze(self):
        import hud_target_contract as H
        entry = {"raw_arr": 100000, "raw_dep": -1, "is_pass": False, "is_terminal": True}
        t1, f1 = H.official_time(entry, 4, 5000.0, 4990.0, 90000, 0, ("s", "l"), None)
        self.assertEqual(t1, 100000)
        t2, f2 = H.official_time(entry, 4, 5000.0, 4999.0, 90000, 1, ("s", "l"), None)
        self.assertIsNotNone(f2)
        self.assertEqual(t2, 90000 + f2.diff_s * 1000)
        s = self.fscene()
        self.fd(s, TERM, speed=0.0, dist=1.0, dt=-3000)
        self.assertFalse(self.latched(s), "the terminal is no pair A / B")

    def test_FD_29_30_31_score_history_checkpoint_and_the_machine_are_untouched(self):
        results = []
        for latch_on in (False, True):
            s = self.fscene()
            o = s.o
            for dt in (-3000, 0, 5000):
                self.fd(s, A, speed=0.0, dist=1.0, dt=dt)
            if not latch_on:
                o._free_turnback_a_latch = None
            results.append((o.score, len(o.save_data), dict(o.score_details), s.machine.state, s.machine.jump_earliest_ms, o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq, list(o.brake_rules)))
        self.assertEqual(results[0], results[1], "the latch writes nothing of the scoring, the history, the checkpoints, the target or the arrival values")

    def test_FD_32_the_latch_is_read_only_by_the_display_view(self):
        text = source("main.py")
        for name in ("scoring_logic.py", "pseudo_turnback_machine.py", "hud_ui.py", "hud_target_contract.py", "station_identity.py"):
            self.assertNotIn("_free_turnback_a_latch", source(name), name)
        readers = [line for line in text.splitlines() if "free_turnback_a_time_suppressed" in line]
        self.assertEqual(len(readers), 3, readers)                       # the def, its docstring-free call in the view, and the update's own doc mention

    def test_FD_33_the_one_python_path_has_no_host_branch_and_no_door_lamp_flag_or_name_input(self):
        for fn in (self.main.Overlay._free_turnback_a_latch_update, self.main.Overlay.free_turnback_a_time_suppressed):
            node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
            node.body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant) and isinstance(n.value.value, str))]
            body = ast.unparse(node)                                       # the code only: no docstring, no comment
            for word in ("bve_door", "bve_doordir", "bve_is_pass", "signal", "['name']", '["name"]', ".get('name'", "Legacy", "legacy", "DLL", "host"):
                self.assertNotIn(word, body, word)


if __name__ == "__main__":
    unittest.main()
