"""Post-Finish Retry Recovery, Stage PFR-R - a Retry after the scoring finished is accepted again (Owner ruling of 2026-11-12; REQUIREMENT REGRESSION of LC-4 0957634 undone).

THE ORIGINAL CONTRACT (restored)
  After the scoring finished - the result may be shown and SAVED - F1 > "選択した駅からやり直す" > a station > 「はい」 keeps the state of the check point (its ARRIVAL at the chosen station, itself included), discards
  what happened after the departure from it (points, history, the finish, the result state), Jumps to the station and lets the scoring run on from there.
  The refusal LC-A13 / RF01..RF09 fixed ("is_scoring_finished refuses every Retry, nothing changes, the confirmation page stays") was WRONG and is withdrawn.

THE RUN CONTEXT (OD-PF-3, R1, and the Owner's addenda of 2026-11-12)
  A Retry after the finish is NOT a new Run: it rewinds the SAME Run, which is still alive (the finish is not the end of a Run). The settings frozen at its start - _scoring_settings and _scoring_section - are
  KEPT until the Run ends; there is no copy, no second attribute, no restore, and the live F1 values are never read again for that Run. active() keeps its meaning (a finished Run is not served to the scoring),
  the Retry makes the same objects active again.
  The Run ends - and the frozen settings are cleared - at: the user's abort of the scoring, F5 / a scenario change, a session or ScenarioGeneration change, a new scoring Run, the end of TS Scoring, Input Device OFF,
  an unrecoverable Jump failure that ends the scoring session. The identity tag _run_identity (BVE PID, session, ScenarioGeneration, scenario scope) recorded at the start must equal the current one for a Retry after the
  finish; otherwise it is REFUSED with a reason (run-context-missing / run-context-mismatch), nothing changes, and the live values are never a fall back.

THE RESULT FILE (OD-PF-1, B0)
  The old result file is never deleted, overwritten, renamed or marked. The Retry resets the in-application state only (is_result_saved False, saved_file_path ""). A completion that follows saves a NEW
  file (a new name); both exist. A Retry that is not followed by a completion leaves the old file alone and creates none.

A FAILED JUMP (OD-PF-4, F1): the same as a Retry in the middle of a run - the scoring session ends, no half-resumed state, the old result file untouched.
Needs PyQt6 (skipped otherwise).
"""
import hashlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lc_legacy_feed as F  # noqa: E402
from pfr_rig import PfrManaged, read, scoring_snapshot  # noqa: E402

ST = {0: (0.0, 1000.0), 1: (1000.0, 2500.0), 2: (2500.0, 2500.0)}        # station index -> (location, next station location) of the rig's station list


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class PostFinishRetry(PfrManaged):
    shape = "legacy"
    capture_sink = False

    def fresh(self):
        """A new rig for the next subtest (the cleanups of the old one first: two rigs of the module can not be installed at once)."""
        self.doCleanups()
        self.setUp()

    # -- drive helpers ------------------------------------------------------------------------------------------------------------------------------------------
    def finish_the_run(self):
        t = self.to_finish()
        return t

    def fake_result_file(self, name="Result_old.jpg", payload=b"old-result"):
        d = tempfile.mkdtemp(prefix="ts-pfr-res-")
        self.addCleanup(lambda: [os.remove(os.path.join(d, n)) for n in os.listdir(d)] and None)
        path = os.path.join(d, name)
        with open(path, "wb") as f:
            f.write(payload)
        return d, path

    def save_the_result(self, path):
        o = self.o
        o.is_result_saved, o.saved_file_path = True, path

    def retry(self, position, via="menu", expect_accepted=True):
        """The user's 「はい」 on the confirmation page of check point `position`. A test that needs the Retry accepted fails here (not later, vacuously) when it was not."""
        o = self.o
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, position
        n_cmd = len(self.commands())
        if via == "key":
            self.r.tap("enter")
        else:
            o.handle_menu_enter(True)
        if expect_accepted:
            self.assertEqual(len(self.commands()), n_cmd + 1, "PREMISE the Retry was accepted (no Jump request was sent)")
            self.assertIsNotNone(o.retry_pending, "PREMISE the Retry was accepted (no pending retry)")

    def land_retry(self, cmd, position, jump=2):
        """The sender executes the Retry Jump to check point `position` and reports it."""
        r, o = self.r, self.o
        cp = o.save_data[position]
        index = cp["station_index"]
        loc, nextloc = ST[index]
        t = int(cp["time_ms"])
        r.send(F.line(self.shape, 1, t, 0.0, loc, jump=jump, discontinuity=True, NEXTLOC=nextloc))
        r.tick(2)
        r.complete(cmd["request_id"], kind="STA", index=index, location=loc, time_ms=t, count=jump)
        r.tick(2)
        return t

    def run_to_finish_again(self, t, jump):
        """From the landing at the station 0 on: A to B, doors, B to C (terminal arrival) - the same drive as to_finish, on the Jump count `jump`."""
        r, MR, shape = self.r, self.MR, self.shape
        t = self.leg(t, 100.0, 1000.0, 1000.0, 1, 1, 1, jump=jump)
        t += 3000
        r.send(F.line(shape, 1, t, 0.0, 999.6, jump=jump, NEXTLOC=1000.0, DOOR=0, STIDX=MR.stidx(MR.STALIST, 1, 1, 1)))
        r.tick(2, 0.1)
        t += 2000
        r.send(F.line(shape, 1, t, 18.0, 1010.0, jump=jump, calcg=0.05, NEXTLOC=2500.0, STIDX=MR.stidx(MR.STALIST, 2, 1, 1)))
        r.tick(2, 0.1)
        return self.leg(t, 1010.0, 2500.0, 2500.0, 2, 2, 2, jump=jump, prev=(1, 1))

    # -- PR-1 .. PR-3: the menu, the acceptance, the finish state ----------------------------------------------------------------------------------------------------
    def test_PR01_the_retry_item_is_shown_after_the_finish_next_to_the_result(self):
        self.finish_the_run()
        o, r = self.o, self.r
        r.tap("f1")
        self.assertEqual(o.menu_state, 1)
        self.assertIn("選択した駅からやり直す", o.current_menu_items)
        self.assertIn("採点結果を表示する", o.current_menu_items)
        o.menu_cursor = o.current_menu_items.index("選択した駅からやり直す")
        r.tap("enter")
        self.assertEqual(o.menu_state, 2, "the list of the check points was not opened")
        self.assertEqual(len(o.save_data), 2)

    def test_PR02_the_yes_of_the_confirmation_page_is_accepted_by_enter_and_by_the_click_path(self):
        for via in ("menu", "key"):
            with self.subTest(via=via):
                self.fresh()
                self.finish_the_run()
                o = self.o
                n_cmd = len(self.commands())
                self.retry(0, via)
                self.assertEqual(len(self.commands()), n_cmd + 1, "no Retry request was sent (%s)" % via)
                self.assertEqual(o.menu_state, 0, "the confirmation page stayed (%s)" % via)
                self.assertTrue(o.is_official_jumping)
                self.assertIsNotNone(o.retry_pending)

    def test_PR03_the_finish_state_is_released_and_the_scoring_owns_the_hud_target_again(self):
        self.finish_the_run()
        o = self.o
        self.assertTrue(o.is_scoring_finished)
        self.retry(0)
        self.assertFalse(o.is_scoring_finished)
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual((o.end_message_time, o.result_screen_time), (0.0, 0.0))
        self.assertTrue(self.HT.owner_is_scoring(o.is_scoring_mode, o.is_scoring_finished))

    # -- PR-4 .. PR-7: the result state and the old result file (B0) ---------------------------------------------------------------------------------------------------
    def test_PR04_the_result_display_state_is_released(self):
        self.finish_the_run()
        o = self.o
        o.menu_state = 11                                                      # the result screen is open
        o.result_screen_time = 5.0
        o.end_message_time = 3.0
        self.retry(0)
        self.assertEqual((o.menu_state, o.result_screen_time, o.end_message_time), (0, 0.0, 0.0))

    def test_PR05_the_result_saved_flag_is_false_after_the_retry(self):
        self.finish_the_run()
        d, old = self.fake_result_file()
        self.save_the_result(old)
        self.retry(0)
        self.assertFalse(self.o.is_result_saved)

    def test_PR06_the_saved_file_path_of_the_run_is_released(self):
        self.finish_the_run()
        d, old = self.fake_result_file()
        self.save_the_result(old)
        self.retry(0)
        self.assertEqual(self.o.saved_file_path, "")

    def test_PR07_the_old_result_file_is_not_touched_by_the_retry(self):
        self.finish_the_run()
        d, old = self.fake_result_file()
        self.save_the_result(old)
        before = (sha(old), os.listdir(d), os.path.getmtime(old), os.path.getsize(old))
        self.retry(0)
        self.assertEqual((sha(old), os.listdir(d), os.path.getmtime(old), os.path.getsize(old)), before, "the old result file was changed, renamed or removed")

    # -- PR-8 / PR-9 / PR-28: the Run context (R1) ---------------------------------------------------------------------------------------------------------------------
    def test_PR08_the_frozen_settings_and_the_section_of_the_run_are_kept_through_the_finish(self):
        import scoring_settings
        self.finish_the_run()
        o = self.o
        settings, section = o.__dict__.get("_scoring_settings"), o.__dict__.get("_scoring_section")
        self.assertIsNotNone(settings, "the finish dropped the Run's frozen settings")
        self.assertIsNotNone(section, "the finish dropped the Run's frozen section")
        self.assertIsNone(scoring_settings.active(o), "a finished Run is not served to the scoring (active keeps its meaning)")
        self.assertIsNone(self.S.active_scoring_section(o))
        self.r.tick(8, 0.1)                                                   # the ticks (housekeeping) do not drop it
        self.assertIs(o.__dict__.get("_scoring_settings"), settings)
        self.assertIs(o.__dict__.get("_scoring_section"), section)
        self.retry(0)
        self.assertIs(o.__dict__.get("_scoring_settings"), settings, "the settings of the Run were replaced")
        self.assertIs(o.__dict__.get("_scoring_section"), section)
        self.assertIs(scoring_settings.active(o), settings, "the same object serves the resumed Run")
        self.assertIs(self.S.active_scoring_section(o), section)

    def test_PR09_the_live_f1_values_are_never_read_again_for_the_run(self):
        self.finish_the_run()
        o = self.o
        import scoring_settings
        run = o.__dict__["_scoring_settings"]
        o.rank_a_ratio, o.pen_jerk, o.pen_limit, o.pen_eb, o.pen_roll = 0.9, not run.stop_shock, not run.speed_limit_exceeded, not run.emergency_brake, not run.rolling      # the user changes F1 after the finish
        o.user_timing_overrides = {1: True, 2: False}
        self.assertIs(o.__dict__.get("_scoring_settings"), run, "the retained settings changed with the live values")
        self.retry(0)
        self.assertTrue(o.is_scoring_mode and not o.is_scoring_finished)
        self.assertEqual(scoring_settings.value(o, "a_rank_ratio"), run.a_rank_ratio)
        self.assertEqual(scoring_settings.value(o, "stop_shock"), run.stop_shock)
        self.assertEqual(scoring_settings.value(o, "speed_limit_exceeded"), run.speed_limit_exceeded)
        self.assertEqual(scoring_settings.value(o, "emergency_brake"), run.emergency_brake)
        self.assertEqual(scoring_settings.value(o, "rolling"), run.rolling)
        self.assertNotEqual(o.rank_a_ratio, run.a_rank_ratio, "PREMISE the live value differs")

    def test_PR09b_the_ticks_after_the_finish_never_make_a_new_snapshot(self):
        self.finish_the_run()
        o = self.o
        settings = o.__dict__["_scoring_settings"]
        o.rank_a_ratio = 0.91
        self.r.tick(10, 0.1)
        self.assertIs(o.__dict__.get("_scoring_settings"), settings)

    def test_PR28a_the_run_is_bound_to_its_identity(self):
        self.finish_the_run()
        o = self.o
        pid, session, generation, scenario_id, list_id, count = o.__dict__["_run_identity"]
        self.assertEqual(pid, self.r.args.bve_pid)
        self.assertEqual(generation, self.r.input._generation)
        self.assertEqual(scenario_id, o.current_scenario_id)
        self.assertEqual(count, len(o.station_list))
        self.assertTrue(list_id)

    def test_PR28b_an_explicit_abort_clears_the_frozen_settings_and_a_new_run_makes_new_ones(self):
        self.finish_the_run()
        o, r = self.o, self.r
        old = o.__dict__["_scoring_settings"]
        r.tap("f1")
        o.menu_cursor = o.current_menu_items.index("採点を中断する")
        r.tap("enter")
        o.menu_cursor = 0
        r.tap("enter")                                                         # the explicit abort of the scoring
        self.assertIsNone(o.__dict__.get("_scoring_settings"))
        self.assertIsNone(o.__dict__.get("_scoring_section"))
        self.assertIsNone(o.__dict__.get("_run_identity"))
        r.start_scoring_via_menu()
        self.assertTrue(o.is_scoring_mode)
        self.assertIsNotNone(o.__dict__.get("_scoring_settings"))
        self.assertIsNot(o.__dict__.get("_scoring_settings"), old, "a new Run reused the old frozen settings")

    def test_PR28c_a_new_generation_and_a_session_change_clear_the_frozen_settings(self):
        for what in ("generation", "session-off"):
            with self.subTest(what=what):
                self.fresh()
                self.finish_the_run()
                o, r = self.o, self.r
                self.assertIsNotNone(o.__dict__.get("_scoring_settings"))
                if what == "generation":
                    r.publish(True, True, 2)
                else:
                    r.publish(False, False)
                r.tick(4)
                for name in ("_scoring_settings", "_scoring_section", "_run_identity"):
                    self.assertIsNone(o.__dict__.get(name), "%s: %s was carried on" % (what, name))

    def test_PR28h_the_end_of_the_scoring_session_and_of_ts_scoring_clear_the_frozen_settings(self):
        for how in ("state-lost", "shutdown"):
            with self.subTest(how=how):
                self.fresh()
                self.finish_the_run()
                o, c = self.o, self.r.input
                self.assertIsNotNone(o.__dict__.get("_scoring_settings"))
                if how == "state-lost":
                    c.on_inactive("state-lost")              # Input Device OFF / the state block is gone
                else:
                    c.on_shutdown()                          # the Stop request: the end of TS Scoring
                for name in ("_scoring_settings", "_scoring_section", "_run_identity"):
                    self.assertIsNone(o.__dict__.get(name), "%s: %s was carried on" % (how, name))

    def test_PR28i_the_session_is_part_of_the_identity_of_the_run(self):
        self.finish_the_run()
        c = self.r.input
        before = c.run_identity()
        c.on_inactive("state-lost")
        after = c.run_identity()
        self.assertEqual(after[0], before[0], "the BVE PID is the same")
        self.assertEqual(after[1], before[1] + 1, "an ended session must change the identity (a Run of an earlier session can never be resumed)")
        self.assertEqual(after[2], before[2])
    def test_PR28d_a_scenario_change_clears_the_frozen_settings(self):
        self.finish_the_run()
        o, r = self.o, self.r
        self.assertIsNotNone(o.__dict__.get("_scoring_settings"))
        o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")                        # another scenario: another SCENARIO_ID (the line the sender writes)
        for name in ("_scoring_settings", "_scoring_section", "_run_identity"):
            self.assertIsNone(o.__dict__.get(name), "%s was carried to the next scenario" % name)

    def test_PR28e_a_retry_with_a_different_identity_is_refused_and_never_falls_back_to_the_live_values(self):
        for what in ("pid", "session", "generation", "scenario", "list", "count"):
            with self.subTest(what=what):
                self.fresh()
                self.finish_the_run()
                o = self.o
                run = o.__dict__["_scoring_settings"]
                pid, session, generation, scenario_id, list_id, count = o.__dict__["_run_identity"]
                changed = {"pid": (pid + 1, session, generation, scenario_id, list_id, count), "session": (pid, (session or 0) + 1, generation, scenario_id, list_id, count),
                           "generation": (pid, session, (generation or 0) + 1, scenario_id, list_id, count), "scenario": (pid, session, generation, scenario_id + 1, list_id, count),
                           "list": (pid, session, generation, scenario_id, "XXXXXXXX", count), "count": (pid, session, generation, scenario_id, list_id, count + 1)}[what]
                o._run_identity = changed
                before, n_cmd = scoring_snapshot(o), len(self.commands())
                res = self.main.execute_retry(o, 0, True)
                self.assertFalse(res.accepted)
                self.assertEqual(res.reason, "run-context-mismatch")
                self.assertEqual(len(self.commands()), n_cmd, "a Jump request was sent")
                after = scoring_snapshot(o)
                self.assertEqual(sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), [], "state changed by the refusal")
                self.assertIs(o.__dict__.get("_scoring_settings"), run, "the refusal touched the frozen settings")
                self.assertTrue(o.is_scoring_finished)

    def test_PR28f_a_retry_without_the_frozen_settings_is_refused(self):
        for which in ("_scoring_settings", "_scoring_section", "_run_identity"):
            with self.subTest(which=which):
                self.fresh()
                self.finish_the_run()
                o = self.o
                o.__dict__.pop(which, None)
                res = self.main.execute_retry(o, 0, True)
                self.assertEqual((res.accepted, res.reason), (False, "run-context-missing"))
                self.assertTrue(o.is_scoring_finished)

    def test_PR28g_the_refusal_is_one_important_line_with_its_reason_even_after_the_70_lines(self):
        self.finish_the_run()
        o, c = self.o, self.r.input
        for name in ("stidx", "input-hold", "stidx-sum", "stidx-identity", "routepairset", "window-fullscreen", "input-pause", "input-resume"):
            for _ in range(30):
                c.note(name, n=1)
        o.__dict__.pop("_run_identity", None)
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        o.handle_menu_enter(True)
        lines = self.lines_of("retry-rejected")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("why=run-context-missing", lines[0])
        self.assertEqual((o.menu_state, o.menu_cursor), (3, 0))

    # -- PR-10 .. PR-13: the boundary and the score ----------------------------------------------------------------------------------------------------------------------
    def test_PR10_the_history_up_to_the_chosen_station_is_kept_itself_included(self):
        self.finish_the_run()
        o = self.o
        self.assertEqual(len(o.save_data), 2)
        first, second = o.save_data[0], o.save_data[1]
        self.retry(1)
        cmd = self.r.last_command()
        self.land_retry(cmd, 1)
        self.assertEqual(len(o.save_data), 2, "the chosen check point and the ones before it must stay")
        self.assertIs(o.save_data[0], first)
        self.assertIs(o.save_data[1], second)

    def test_PR11_what_follows_the_chosen_station_is_discarded_when_the_jump_completed(self):
        self.finish_the_run()
        o = self.o
        first = o.save_data[0]
        self.retry(0)
        self.assertEqual(len(o.save_data), 2, "the history is cut by the COMPLETED Jump only (ST-3)")
        self.land_retry(self.r.last_command(), 0)
        self.assertEqual(len(o.save_data), 1)
        self.assertIs(o.save_data[0], first)
        self.assertIsNone(o.retry_pending)
        self.assertFalse(o.is_official_jumping)

    def test_PR12_the_score_goes_back_to_the_chosen_station(self):
        self.finish_the_run()
        o = self.o
        final = o.score
        cp = o.save_data[1]
        self.retry(1)
        self.assertEqual(o.score, cp["score"])
        self.assertEqual(o.expected_target_time, cp["time_ms"])
        self.assertNotEqual(final, cp["score"], "PREMISE the run gained or lost points after the chosen station")

    def test_PR13_the_score_details_of_the_chosen_station_are_kept(self):
        self.finish_the_run()
        o = self.o
        cp = o.save_data[1]
        self.retry(1)
        self.assertEqual(o.score_details, cp["score_details"])
        self.assertIsNot(o.score_details, cp["score_details"], "the details of the check point must be a copy")
        self.assertEqual(sum(o.score_details.values()), o.score)

    # -- PR-14 .. PR-17: the request and the resumption ------------------------------------------------------------------------------------------------------------------
    def test_PR14_one_retry_request_only(self):
        self.finish_the_run()
        o = self.o
        n_cmd = len(self.commands())
        self.retry(0)
        self.assertEqual(len(self.lines_of("retry-request-created")), 1)
        self.assertEqual(len(self.lines_of("retry-accepted")), 1)
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertEqual(o.retry_pending.state, "sent")

    def test_PR15_PR16_one_jump_request_of_the_retry_in_the_shape_of_the_feed(self):
        self.finish_the_run()
        n_cmd = len(self.commands())
        self.retry(1)
        cmds = self.commands()
        self.assertEqual(len(cmds), n_cmd + 1)
        cmd = self.r.last_command()
        self.assertTrue(cmd["request_id"])
        self.assertIn("1", str(cmd.get("text", cmd)), cmd)                      # the station index of the chosen check point is in the request

    def test_PR17_after_the_jump_completed_the_scoring_runs_again_and_finishes_again(self):
        self.finish_the_run()
        o = self.o
        self.retry(0)
        t = self.land_retry(self.r.last_command(), 0, jump=2)
        self.assertTrue(o.is_scoring_mode and not o.is_scoring_finished and not o.is_official_jumping)
        t = self.run_to_finish_again(t, jump=2)
        self.assertTrue(o.is_scoring_finished, "the scoring did not run to the end station again")
        self.assertGreaterEqual(len(o.save_data), 2)

    # -- PR-18 .. PR-20: the new result and the old one coexist (B0) ----------------------------------------------------------------------------------------------------
    def test_PR18_PR19_the_new_completion_saves_a_new_result_file_next_to_the_old_one(self):
        self.finish_the_run()
        o = self.o
        d, old = self.fake_result_file()
        self.save_the_result(old)
        before = sha(old)
        self.retry(0)
        t = self.land_retry(self.r.last_command(), 0, jump=2)
        self.run_to_finish_again(t, jump=2)
        self.assertTrue(o.is_scoring_finished)
        new = os.path.join(d, "Result_new.jpg")
        o.ask_result_save_path = lambda default: new
        o.menu_state = 11
        o.take_result_screenshot()
        self.assertTrue(o.is_result_saved)
        self.assertEqual(o.saved_file_path, new)
        self.assertTrue(os.path.exists(new) and os.path.getsize(new) > 0, "the new result file was not created")
        self.assertTrue(os.path.exists(old))
        self.assertEqual(sha(old), before, "the old result file changed")
        self.assertEqual(sorted(os.listdir(d)), ["Result_new.jpg", "Result_old.jpg"])

    def test_PR20_a_retry_that_does_not_finish_leaves_only_the_old_result(self):
        self.finish_the_run()
        o = self.o
        d, old = self.fake_result_file()
        self.save_the_result(old)
        self.retry(0)
        self.land_retry(self.r.last_command(), 0, jump=2)
        self.r.tick(5, 0.1)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(os.listdir(d), ["Result_old.jpg"])
        self.assertFalse(o.is_result_saved)

    # -- PR-21 / PR-22: a failed jump, a double Retry ---------------------------------------------------------------------------------------------------------------------
    def test_PR21_a_failed_jump_ends_the_scoring_session_safely_and_the_old_result_stays(self):
        self.finish_the_run()
        o = self.o
        d, old = self.fake_result_file()
        self.save_the_result(old)
        before = sha(old)
        self.retry(0)
        self.assertTrue(o.is_official_jumping)
        o._abort_unreleased_official_jump("timeout")
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_scoring_finished)
        self.assertIsNone(o.retry_pending)
        self.assertIsNone(o.jump_expectation)
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        for name in ("_scoring_settings", "_scoring_section", "_run_identity"):
            self.assertIsNone(o.__dict__.get(name), "%s of the Run that was given up" % name)
        self.assertEqual((sha(old), os.listdir(d)), (before, ["Result_old.jpg"]))

    def test_PR22_a_second_retry_is_refused_while_the_first_one_waits_for_its_jump(self):
        self.finish_the_run()
        o = self.o
        self.retry(0)
        n_cmd = len(self.commands())
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        o.handle_menu_enter(True)
        self.assertEqual(len(self.commands()), n_cmd, "a second request was sent")
        res = self.main.execute_retry(o, 0, True)
        self.assertEqual((res.accepted, res.reason), (False, "retry-pending"))

    # -- PR-25: the jump timeout of the Python side stays ---------------------------------------------------------------------------------------------------------------------
    def test_PR25_a_silent_sender_is_given_up_after_10_seconds_also_for_a_retry_after_the_finish(self):
        self.finish_the_run()
        o, r = self.o, self.r
        self.retry(0)
        self.assertTrue(o.is_official_jumping)
        for _ in range(60):
            r.tick(1, 0.5)
            if not o.is_official_jumping:
                break
        self.assertFalse(o.is_official_jumping, "the unanswered Retry Jump was never given up")
        self.assertFalse(o.is_scoring_mode)

    def test_PR27_the_short_run_of_three_stations_has_the_same_contract(self):
        """A short dedicated scenario (2-3 stations) is the live acceptance scenario: the expectation is the check point's OWN stored values (expected_score = selected_checkpoint.score), no fixed number."""
        self.finish_the_run()
        o = self.o
        self.assertEqual(len(o.station_list), 3)
        position = len(o.save_data) - 1                                         # the last check point before the terminal
        cp = o.save_data[position]
        expected_score, expected_details, expected_len = cp["score"], dict(cp["score_details"]), len(o.save_data)
        self.retry(position)
        self.assertEqual((o.score, o.score_details), (expected_score, expected_details))
        self.assertFalse(o.is_scoring_finished)
        self.land_retry(self.r.last_command(), position)
        self.assertEqual(len(o.save_data), expected_len)
        self.assertIs(o.save_data[position], cp)
        self.assertEqual(o.score, expected_score)
    # -- PR-30: before the finish nothing changed ------------------------------------------------------------------------------------------------------------------------
    def test_PR30_a_retry_before_the_finish_keeps_its_contract(self):
        self.to_b()
        o = self.o
        self.assertFalse(o.is_scoring_finished)
        n_cmd, n_hist = len(self.commands()), len(o.save_data)
        res = self.main.execute_retry(o, 99, False)
        self.assertEqual((res.accepted, res.reason), (False, "no-checkpoint"))
        before = scoring_snapshot(o)
        self.main.execute_retry(o, 99, False)
        after = scoring_snapshot(o)
        self.assertEqual(sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), [])
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual((len(self.commands()), len(o.save_data), o.is_official_jumping), (n_cmd + 1, n_hist, True))
        self.assertIsNotNone(o.__dict__.get("_scoring_settings"), "a retry in the middle of the run uses the running snapshot as it always did")

    def test_PR30b_a_refused_retry_still_changes_nothing_and_the_screen_stays(self):
        self.to_b()
        o = self.o
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 99
        before = scoring_snapshot(o)
        o.handle_menu_enter(True)
        after = scoring_snapshot(o)
        self.assertEqual((o.menu_state, o.menu_cursor), (3, 0))
        self.assertEqual(sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)), [])


class PostFinishRetryCurrent(PostFinishRetry):
    shape = "current"


class Boundary24(PfrManaged):
    """PR-19/26 of the Owner's list: the field run of 2026-11-12 - 24 stations, the scoring finished at the terminal (index 23, 18,664 points), the Retry to 新津田沼 (position 22, StationIndex 22,
    25,338.0 m, 67,586,232 ms, 18,865 points). The state of the field run is rebuilt on the real Overlay; the Jump of the Retry is the real request."""

    shape = "current"
    FIELD = {"scenario": 6180992, "list": "BE6488BB", "count": 24, "position": 22, "loc": 25338.0, "time_ms": 67586232, "cp_score": 18865, "final": 18664}

    def rebuild(self):
        import scoring_settings
        from scoring_logic import build_scoring_section
        r, o, SI, F_ = self.r, self.o, self.SI, self.FIELD
        r.go_active()
        stations = [{"name": "S%d" % i, "location": 1.0 + i * 1100.0, "def_time": -1, "raw_dep": -1, "stop_time": 15000} for i in range(F_["count"])]
        stations[F_["position"]]["location"] = F_["loc"]
        stations[F_["position"] + 1]["location"] = 26550.113
        o.station_list = SI_station_list(stations, F_["list"])
        o.bve_list_id, o.current_scenario_id = F_["list"], F_["scenario"]
        scope = (F_["scenario"], F_["list"], F_["count"])
        o.save_data = []
        for pos in range(F_["position"] + 1):
            loc = stations[pos]["location"]
            o.save_data.append({"loc": loc, "time_ms": F_["time_ms"] - (F_["position"] - pos) * 100000, "score": 0 if pos == 0 else 700 * pos, "target_loc": loc,
                                "station_name": "S%d" % pos, "stop_error": 0.0, "station_index": pos, "scope": scope, "station_location": loc,
                                "role": "scoring_start" if pos == 0 else "arrived_station", "score_details": {k: 0 for k in o.score_details}})
        cp = o.save_data[F_["position"]]
        cp["score"], cp["time_ms"] = F_["cp_score"], F_["time_ms"]
        cp["score_details"] = dict(o.score_details, time=F_["cp_score"])
        o.score = F_["final"]
        o.score_details = dict(o.score_details, time=F_["final"])
        o.is_scoring_mode = True
        o.setting_end_idx = -1
        o._scoring_settings = scoring_settings.build(o)
        o._scoring_section = build_scoring_section(o)
        from scoring_logic import run_identity
        o._run_identity = run_identity(o)
        o.is_scoring_finished = True                    # the Run is finished; its frozen settings stay
        return stations

    def test_PR26_the_field_run_of_24_stations_goes_back_from_the_terminal_to_22(self):
        self.rebuild()
        o, F_ = self.o, self.FIELD
        self.assertEqual((o.score, o.is_scoring_finished, len(o.save_data)), (F_["final"], True, 23))
        res = self.main.execute_retry(o, F_["position"], True)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(res.selected_station_index, 22)
        self.assertEqual(o.score, F_["cp_score"])
        self.assertEqual(o.score - F_["final"], 201, "the terminal leg of the field run was -201 points")
        import scoring_settings
        self.assertIs(scoring_settings.active(o), o.__dict__["_scoring_settings"], "the Run's own frozen settings serve the resumed Run")
        self.assertFalse(o.is_scoring_finished)
        cmd = self.r.last_command()
        self.assertTrue(cmd["request_id"])
        self.assertEqual(o.retry_pending.selected_save_position, 22)
        self.assertEqual(o.retry_pending.selected_station_index, 22)
        history = self.SI.resolve_retry_history(o.save_data, o.retry_pending, F_["scenario"], F_["list"], o.station_list)
        self.assertEqual(len(history), 23, "the history 0..22 (23 check points) is kept, the chosen one included")
        self.assertEqual(history[-1]["station_index"], 22)


def SI_station_list(stations, list_id):
    import station_identity
    return station_identity.StationList(stations, list_id=list_id)


class StaticContract(unittest.TestCase):
    def test_PR_static_the_scoring_finished_refusal_is_gone_and_the_context_words_are_local(self):
        import ast
        text = read("scoring_logic.py")
        self.assertNotIn("'scoring-finished'", text, "the LC-A13 refusal is back")
        for word in ("run-context-missing", "run-context-mismatch"):
            self.assertIn(word, text)
            self.assertNotIn(word, read("station_identity.py"), "the ST-2 words of station_identity stay as they are")
        tree = ast.parse(text)
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"][0]
        first = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))][0]
        self.assertFalse(isinstance(first, ast.If) and "is_scoring_finished" in ast.unparse(first.test) and isinstance(first.body[0], ast.Return), "the first statement of execute_retry is a finish refusal")

    def test_PR_static_the_state_authority_is_the_run_itself_no_second_copy(self):
        for name in ("scoring_logic.py", "main.py", "managed_input.py"):
            text = read(name)
            for word in ("_last_finished_scoring", "_finished_run", "FinishedRun", "keep_finished_run", "restore_finished_run"):
                self.assertNotIn(word, text, "%s: %s - a second copy of the Run's frozen settings" % (name, word))

    def test_PR_static_the_legacy_and_current_jump_code_is_not_part_of_the_change(self):
        """PR-23 / PR-24 / PR-25 (static part): the Legacy executor keeps its TTL and scenario epoch text; its bytes are pinned by tests/test_legacy_jump_exec_ljx1.py (a change would fail there)."""
        path = os.path.join(os.path.dirname(HERE), "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "src", "LegacyJumpExecutor.cs")
        self.assertTrue(os.path.exists(path), "the Legacy executor source is missing")
        with open(path, encoding="utf-8") as f:
            legacy = f.read().lower()
        for word in ("ttl", "epoch"):
            self.assertIn(word, legacy, "the Legacy executor lost its %s contract text" % word)


if __name__ == "__main__":
    unittest.main()
