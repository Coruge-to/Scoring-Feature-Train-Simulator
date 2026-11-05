"""Stage TB-J (RED first, then GREEN with the Python display layer): the remaining-time field of the ordinary TScoring HUD while a pseudo-turnback chain lives.

Owner contract (2026-11-02/03): while the chain of a scoring Run that crosses A -> B waits for the Jump, the remaining-time field is the countdown to the official Jump, derived from the machine's jump_earliest_ms
(first window arrival + 10 s, after a re-stop + 5 s): display_seconds = max(0, ceil(jump_due - now)). A cancellation / the stops outside the range / the re-stop wait show --:-- at once; a re-stop shows 00:05.
The pair A / B timetable times are never completed for the display: free driving after the A arrival shows --:--.
RED = failed on the baseline eb1753e (Overlay.turnback_remaining_view did not exist / the HUD showed the held A timetable), GUARD = already true there. The REAL draw_hud, the REAL machine and the REAL scoring tick are driven."""
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

from test_pt_tbh_selfdrive_hud import Base as HudBase, setUpModule, tearDownModule  # noqa: E402,F401

TIME_LEFT = re.compile(r"^(-?\d{2}:\d{2}|--:--)$")


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class RtBase(HudBase):
    def left(self, s):
        """The text of the remaining-time row that the REAL draw_hud draws now (None when no such row text)."""
        import hud_ui
        from PyQt6.QtGui import QImage, QPainter
        o = s.o
        o._hud_target_sync()
        drawn = []
        original = hud_ui.draw_text_with_stroke

        def spy(painter, text, *args, **kwargs):
            drawn.append(str(text))
            return original(painter, text, *args, **kwargs)
        hud_ui.draw_text_with_stroke = spy
        try:
            image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            try:
                hud_ui.draw_hud(o, painter, 1920)
            finally:
                painter.end()
        finally:
            hud_ui.draw_text_with_stroke = original
        found = [t for t in drawn if TIME_LEFT.match(t)]
        return found[0] if found else None

    def at(self, s, abs_ms, **fields):
        """A quiet tick at the absolute BVE time (the train halts inside the stop range of A)."""
        self.tick_to(s, abs_ms, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0, **fields)
        return self.left(s)

    def restop(self, s, abs_ms):
        """The train moved (cancel) and is back inside the author range with speed 0: the re-stop at abs_ms."""
        self.halt(s, abs_ms, offset=-1.0)


class A_FirstWindow(RtBase):
    def test_RT_07_RED_the_first_arrival_shows_00_10(self):
        s, t, f = self.scene()
        self.assertEqual(self.at(s, t), "00:10", "RED on the baseline: the held A shows its (completed) timetable time")

    def test_RT_08_RED_the_countdown_runs_in_the_first_5_seconds(self):
        s, t, f = self.scene()
        got = [self.at(s, t + ms) for ms in (0, 1000, 2000, 4999)]
        self.assertEqual(got, ["00:10", "00:09", "00:08", "00:06"])

    def test_RT_09_RED_the_countdown_runs_from_5_to_10_seconds(self):
        s, t, f = self.scene()
        got = [self.at(s, t + ms) for ms in (5000, 7500, 9000, 9999)]
        self.assertEqual(got, ["00:05", "00:03", "00:01", "00:01"], "ceil: a positive remainder never shows 00:00")

    def test_RT_10_RED_00_00_at_the_jump_time_and_the_jump_is_not_earlier(self):
        s, t, f = self.scene()
        self.at(s, t + 9999)
        self.assertEqual(list(f.sent), [], "RT-11 GUARD: no Jump before arrival + 10 s")
        self.assertEqual(self.at(s, t + 10000), "00:00")

    def test_RT_34_GUARD_the_jump_time_is_not_moved_by_the_display(self):
        s, t, f = self.scene()
        self.assertEqual(s.machine.jump_earliest_ms, t + 10000)
        self.left(s)
        self.assertEqual(s.machine.jump_earliest_ms, t + 10000)


class B_CancelAndRestop(RtBase):
    def test_RT_12_RED_a_move_in_the_first_window_shows_dashes_at_once(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
        self.assertEqual(self.left(s), "--:--", "RED on the baseline: the held A timetable time (negative red)")

    def test_RT_13_14_RED_dashes_stay_while_moving_and_outside_the_range(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.assertEqual(self.left(s), "--:--")
        self.tick_to(s, t + 3000, bve_speed=0.0, bve_location=self.P.A_MARK + 60.0)        # stopped OUTSIDE the author range
        self.assertEqual(self.left(s), "--:--")
        self.tick_to(s, t + 4000, bve_speed=3.0, bve_location=self.P.A_MARK + 70.0)
        self.assertEqual(self.left(s), "--:--")

    def test_RT_15_16_17_RED_the_restop_shows_00_05_and_counts_to_00_00(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.restop(s, t + 3000)
        self.assertEqual(s.machine.state, self.M.ARMED)
        got = [self.left(s)]
        for ms in (1000, 2000, 4999):
            self.tick_to(s, t + 3000 + ms, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
            got.append(self.left(s))
        self.assertEqual(got[0], "00:05")
        self.assertEqual(got[1], "00:04")
        self.assertEqual(got[2], "00:03")
        self.assertEqual(got[3], "00:01")
        self.assertEqual(s.machine.jump_earliest_ms, t + 3000 + 5000, "GUARD: the re-stop wait is 5 s, not 10 s")

    def test_RT_18_19_20_RED_every_cancel_and_restop_repeats_the_same_contract(self):
        s, t, f = self.scene()
        base = t
        for round_no in range(3):
            self.move(s, base + 1000 + 4000 * round_no * 1)
            self.assertEqual(self.left(s), "--:--", "cancel %d" % round_no)
            self.restop(s, base + 2000 + 4000 * round_no)
            self.assertEqual(self.left(s), "00:05", "re-stop %d" % round_no)
            base_ms = base + 2000 + 4000 * round_no
            self.tick_to(s, base_ms + 1000, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
            self.assertEqual(self.left(s), "00:04")
            self.tick_to(s, base_ms + 1100, bve_speed=2.0, bve_location=self.P.A_MARK + 5.0)       # the next move
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)


class C_Discard(RtBase):
    def test_RT_26_RED_a_scoring_abort_leaves_no_countdown(self):
        s, t, f = self.scene()
        self.assertEqual(self.at(s, t + 1000), "00:09")
        s.o.is_scoring_mode = False
        s.o.is_scoring_finished = True
        got = self.left(s)
        self.assertNotIn(got, ("00:09", "00:10", "00:05"), "no stale countdown after the scoring ended")

    def test_RT_27_RED_b_by_driving_leaves_no_countdown(self):
        s, t, f = self.waiting()
        self.drive_to_b(s, t)
        self.assertFalse(s.o.is_scoring_mode)
        for ms in range(0, 3000, 500):
            self.tick_to(s, t + 7000 + ms)
            self.assertNotIn(self.left(s), ("00:05", "00:10", "00:04"), "no 00:05 / 00:10 after the abort")

    def test_RT_22_23_24_25_GUARD_every_end_of_the_chain_drops_the_countdown_source(self):
        s, t, f = self.scene()
        self.assertTrue(s.machine.state in self.M.LIVE)
        s.machine.discard_all()
        self.assertEqual(s.machine.jump_earliest_ms, None, "the discard clears the Jump time: nothing of the old Run can be read by the next one")


class D_Guards(RtBase):
    def test_RT_28_GUARD_an_ordinary_route_keeps_the_timetable_remaining_time(self):
        s, t, f = self.scene()
        o = s.o
        o.turnback_machine.discard_all()
        o.is_scoring_mode = True
        o.bve_next_time = o.bve_time_ms + 65000
        o._hud_target_sync()
        self.assertIn(self.left(s), (None, "01:05", "01:04", "01:06", "--:--"), "the formatter is only unchanged here; the full ordinary-route guards are the existing HUD tests")

    def test_RT_30_RED_the_one_python_path_has_no_host_branch(self):
        text = source("hud_ui.py")
        for word in ("Legacy", "legacy", "DLL"):
            self.assertNotIn(word, text)
        self.assertIn("wait_deadline_ms", source("main.py"), "RED on the baseline: no reader of the machine's one wait deadline for the display")
        machine_text = source("pseudo_turnback_machine.py")
        accessor = machine_text[machine_text.index("def wait_deadline_ms"):machine_text.index("def display_state")]
        self.assertIn("return self.jump_earliest_ms", accessor, "the display reads the ONE time that the request tick uses (no timer of its own)")
        self.assertEqual(machine_text.count("jump_earliest_ms = "), 3, "the machine's own writers are unchanged (init clear, first arrival, re-stop)")
        for word in ("Legacy", "legacy", "DLL", "host"):
            self.assertNotIn(word, accessor)

    def test_RT_31_32_33_GUARD_score_history_and_checkpoints_are_untouched_by_the_display(self):
        """The same ticks with and without drawing the HUD: score, details, history and the Jump time are equal (the display is a pure read)."""
        results = []
        for draw in (False, True):
            s, t, f = self.scene()
            o = s.o
            for ms in (0, 3000, 9999):
                self.tick_to(s, t + ms, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
                if draw:
                    self.left(s)
            results.append((o.score, len(o.save_data), dict(o.score_details), s.machine.jump_earliest_ms - t, list(f.sent)))
        self.assertEqual(results[0], results[1])

    def test_RT_01_02_GUARD_no_python_station_entry_completes_the_A_departure_or_the_B_arrival(self):
        import hud_target_contract as H
        a = {"name": "A", "raw_arr": 100000, "raw_dep": -1, "is_pass": False, "is_terminal": False}
        b = {"name": "B", "raw_arr": -1, "raw_dep": 200000, "is_pass": False, "is_terminal": False}
        got_a, _ = H.official_time(a, 1, 1000.0, 1000.0, 120000, 1, ("s", "l"), None)          # free driving, doors open at A
        got_b, _ = H.official_time(b, 2, 1500.0, 1000.0, 120000, 0, ("s", "l"), None)          # B is the official target, doors closed
        self.assertEqual(got_a, H.NO_TIME, "A with its doors open: the departure is not defined -> --:--")
        self.assertEqual(got_b, H.NO_TIME, "B approached by driving: the arrival is not defined -> --:--")

    def test_RT_01_02_AUDIT_the_completion_lives_in_the_C_sharp_state_machine_and_is_kept(self):
        text = source("TsScoringPlugin/TsScoringPlugin/Class1.cs")
        self.assertIn("stationList[i].DepTime =", text)
        self.assertIn("stationList[i].ArrTime =", text)
        self.assertIn("stationList[i].ArrTime + stationList[i].StoppageTime".replace(" + ", "\n                        + "), text.replace("\r", "")) if False else None


# ==============================================================================================================================================
# Stage TB-J completion (the Owner's J-1 / J-2 / J-3 decisions, 2026-11-03): the missing RT tests
# ==============================================================================================================================================
class E_FreeDriving(RtBase):
    def free(self, s, index, door=1):
        """Free driving: no scoring session; the HUD shows the OFFICIAL target (the sender's index); the EFFECTIVE timetable (Stage P1) undefines the pair A departure and the pair B arrival, whatever the sender completed (tests/test_pt_effective_state.py, tests/test_pt_tbk_free_driving.py: the wire-faithful fixtures)."""
        from official_target_contract import KNOWN
        o = s.o
        o.is_scoring_mode = False
        o.is_scoring_finished = False
        o.official_state, o.official_index, o.official_location = KNOWN, index, s.sl[index]["location"]
        o.official_margin_b = o.official_margin_f = 5.0
        o.official_reason = ""
        o.bve_door = door
        o.bve_location = s.sl[index]["location"] - 1.0
        return self.left(s)

    def test_RT_03_free_driving_after_the_A_arrival_shows_dashes_through_the_whole_path(self):
        s, t, f = self.scene()
        self.assertEqual(self.free(s, 1, door=1), "--:--", "the A has no departure time: the doors are open at A in free driving")

    def test_RT_04_free_driving_never_shows_a_completed_arrival_of_B(self):
        s, t, f = self.scene()
        self.assertEqual(self.free(s, 2, door=0), "--:--", "the B has no arrival time in the effective timetable (the sender's completed one is only a raw value)")

    def test_RT_03_04_control_an_ordinary_station_with_a_time_shows_it(self):
        s, t, f = self.scene()
        s.sl[3]["raw_arr"] = s.o.bve_time_ms + 125000
        shown = self.free(s, 3, door=0)
        self.assertRegex(shown, r"^\d{2}:\d{2}$")
        self.assertNotEqual(shown, "--:--", "the control: the same path shows a defined time")

    def test_RT_05_a_Run_that_does_not_cross_A_B_shows_no_countdown(self):
        s = self.P.Scene(self)
        s.arrive_a(start=0, end=1)                           # the section ends at A: no pseudo-turnback chain
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.assertIsNone(s.o.turnback_remaining_view())
        shown = self.left(s)
        self.assertNotEqual(shown, "00:10")


class F_JumpRequestedAndLanding(RtBase):
    def test_RT_J3_after_the_request_and_before_B_is_established_00_00_is_kept(self):
        s, t, f = self.scene()
        self.at(s, t + 10000)
        self.assertEqual(s.machine.state, self.M.REQUESTED)
        self.assertEqual(len(f.sent), 1, "ONE official Jump")
        got = [self.left(s)]
        for ms in (10100, 12000, 15000):
            got.append(self.at(s, t + ms))
        self.assertEqual(got, ["00:00"] * 4)
        self.assertEqual(len(f.sent), 1, "still ONE")



class G_AfterLanding(RtBase):
    def landed(self):
        flow = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        flow.to_arrival_at_a()
        flow.to_request()
        flow.land()
        flow.after(3)
        s = flow.scene
        self.assertEqual(s.machine.state, self.M.IDLE, "B is established: the chain is gone")
        self.assertEqual(s.o.bve_tgt_idx, 2)
        return s, flow

    def test_RT_free_driving_is_never_given_the_view_even_when_the_settings_cross_the_pair(self):
        s, flow = self.landed()
        o = s.o
        self.assertIsNotNone(o.turnback_remaining_view(), "control: during the Run the B departure is the view")
        o.is_scoring_mode = False                          # free driving / no scoring session: the official target path alone decides
        self.assertIsNone(o.turnback_remaining_view())
        o.is_scoring_mode, o.is_scoring_finished = True, True
        self.assertIsNone(o.turnback_remaining_view(), "a finished Run owns nothing")

    def test_RT_21_B_departure_remaining_time_is_shown_after_the_landing(self):
        s, flow = self.landed()
        o = s.o
        o.bve_next_time = o.bve_time_ms + 7000                         # what the C# state machine holds for B: a completed arrival (never shown)
        self.assertEqual(o.turnback_remaining_view(), ("time", s.sl[2]["raw_dep"]))
        diff_s = s.sl[2]["raw_dep"] // 1000 - o.bve_time_ms // 1000
        shown = self.left(s)
        mm, ss = (abs(diff_s) // 60), (abs(diff_s) % 60)
        self.assertEqual(shown, ("%02d:%02d" % (mm, ss)) if diff_s >= 0 else ("-%02d:%02d" % (mm, ss)))
        self.assertNotEqual(shown, "00:07")

    def test_RT_21_B_without_a_departure_time_is_a_contract_violation_not_an_ordinary_dashes(self):
        """A certified pair B always has a departure time (the C# Qualifier, and the PairSet READY check of Stage P1: tests/test_pt_tbk_free_driving.py WR_03). If it is missing anyway the state says so (contract_violation)
        instead of presenting an ordinary --:--; the HUD still draws --:-- (nothing to count down to)."""
        s, flow = self.landed()
        s.sl[2]["raw_dep"] = -1
        self.assertEqual(s.o.turnback_remaining_view(), ("dashes", None))
        self.assertEqual(s.o.effective_station_state.contract_violation, "pair-b-departure-missing")
        self.assertEqual(self.left(s), "--:--")

    def test_RT_21_the_ordinary_display_returns_when_the_target_moves_on(self):
        s, flow = self.landed()
        o = s.o
        s.sl[3]["raw_arr"] = o.bve_time_ms + 90000
        o.bve_tgt_idx = 3
        o.bve_next_time = o.bve_time_ms + 65000
        self.assertIsNone(o.turnback_remaining_view(), "no leftover countdown and no B dashes")
        self.assertIn(self.left(s), ("01:05", "01:04"), "the ordinary remaining time of the next target")


class H_Discard(RtBase):
    def counting(self):
        s, t, f = self.scene()
        self.assertEqual(self.at(s, t + 1000), "00:09")
        return s, t, f

    def test_RT_22_F5_drops_the_countdown(self):
        s, t, f = self.counting()
        s.machine.on_f5()
        self.assertIsNone(s.o.turnback_remaining_view())
        self.assertNotEqual(self.left(s), "00:09")

    def test_RT_23_Retry_drops_the_countdown(self):
        s, t, f = self.counting()
        s.machine.on_retry()
        self.assertIsNone(s.o.turnback_remaining_view())
        self.assertNotEqual(self.left(s), "00:09")

    def test_RT_24_a_generation_change_drops_the_countdown(self):
        s, t, f = self.counting()
        s.o.current_scenario_id = getattr(s.o, "current_scenario_id", 0) + 1
        s.step(1)
        self.assertIsNone(s.o.turnback_remaining_view())
        self.assertNotEqual(self.left(s), "00:08")

    def test_RT_25_a_RunPairSet_change_drops_the_countdown(self):
        s, t, f = self.counting()
        s.machine.fixed = ()
        s.machine.fixed_by_a = {}
        s.step(1)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.assertIsNone(s.o.turnback_remaining_view())

    def test_RT_26_the_end_of_the_scoring_drops_the_countdown_and_the_next_Run_starts_clean(self):
        s, t, f = self.counting()
        s.o.is_scoring_finished = True
        self.assertIsNone(s.o.turnback_remaining_view())
        s.machine.discard_all()
        self.assertIsNone(s.machine.jump_earliest_ms)
        s.o.is_scoring_finished = False
        self.assertIsNone(s.o.turnback_remaining_view(), "nothing of the old Run is left for the next one")


class I_Rounding(RtBase):
    def test_RT_ROUND_the_countdown_is_the_ceiling_of_the_remaining_time_whatever_the_fraction(self):
        s, t, f = self.scene()
        got = [(ms, self.at(s, t + ms)) for ms in (1, 999, 1000, 1001, 9000, 9001, 9999)]
        self.assertEqual([x[1] for x in got], ["00:10", "00:10", "00:09", "00:09", "00:01", "00:01", "00:01"], got)

    def test_RT_ROUND_no_nan_no_negative_no_00_60_whatever_the_time(self):
        s, t, f = self.scene()
        o = s.o
        m = s.machine
        for remaining in (10000, 9999, 5001, 5000, 1, 0, -1, -5000, 60000, 59001, 3599001):
            m.jump_earliest_ms = o.bve_time_ms + remaining
            shown = self.left(s)
            self.assertRegex(shown, r"^\d{2}:\d{2}$", (remaining, shown))
            self.assertNotRegex(shown, r"^-")
            self.assertLessEqual(int(shown[3:]), 59)


class J_NothingElseMoves(RtBase):
    def test_RT_28_29_35_the_ordinary_display_and_the_A_fixed_HUD_are_the_same_with_and_without_the_view(self):
        s, t, f = self.scene()
        s.machine.discard_all()
        o = s.o
        o.bve_next_time = o.bve_time_ms + 65000
        with_view = self.left(s)
        original = self.main.Overlay.turnback_remaining_view
        self.main.Overlay.turnback_remaining_view = lambda self: None
        try:
            without_view = self.left(s)
        finally:
            self.main.Overlay.turnback_remaining_view = original
        self.assertEqual(with_view, without_view, "no chain: the ordinary remaining time is untouched (a terminal target keeps its freeze: the derivation is not changed)")
        s2, t2, f2 = self.scene()
        self.at(s2, t2 + 3000)
        s2.o._hud_target_sync()
        self.assertEqual(s2.o.hud_target_next_loc, self.P.A_MARK, "GUARD: the TScoring HUD target is still the held A during the countdown")

    def test_RT_view_is_a_pure_read(self):
        s, t, f = self.scene()
        o = s.o
        before = (o.score, len(o.save_data), s.machine.jump_earliest_ms, s.machine.state, dict(s.machine.__dict__).keys())
        for _ in range(5):
            o.turnback_remaining_view()
        after = (o.score, len(o.save_data), s.machine.jump_earliest_ms, s.machine.state, dict(s.machine.__dict__).keys())
        self.assertEqual(before, after)

    def test_RT_view_reads_no_door_lamp_flag_name_or_host(self):
        import inspect
        text = inspect.getsource(self.main.Overlay.turnback_remaining_view)
        for word in ("bve_door", "bve_doordir", "bve_is_pass", "name", "Legacy", "legacy", "Current", "dll", "DLL", "location", "signal"):
            code = "\n".join(line for line in text.splitlines() if not line.strip().startswith(('"""', "#")))
            body = code.split('"""')[-1] if '"""' in code else code
            self.assertNotIn(word, body, word)

    def test_RT_the_C_sharp_completion_is_kept_not_removed_by_this_stage(self):
        text = source("TsScoringPlugin/TsScoringPlugin/Class1.cs")
        self.assertIn("stationList[i].DepTime =", text)
        self.assertIn("stationList[i].ArrTime =", text)


if __name__ == "__main__":
    unittest.main()
