"""Phase SI-A4 - the three corrections that the real-machine acceptance of SI-A (sessions SA / SB) asked for.

    A  Pause (Driving OFF with the Session ON) does not end the scoring session; the input is released, the scoring goes on after the pause and the time of the
       pause is never counted as a step
    B  P to P (the kick start) is reachable while Driving is OFF (a scenario loaded PAUSED never ticks): only that, once per generation, with no HUD
    C  the holding speed texts (4th group of ALLTXT) are candidates for the width of the power column

The real Overlay and the real controllers are used (tests/sia_managed_rig.py); the keyboard, the windows, the clock and UDP are recorders.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sia_rig as R  # noqa: E402
from test_managed_input_sia3 import ManagedCase  # noqa: E402


def scoring_run(case, score=-200):
    """A managed rig with a scoring run in progress (speed 5 km/h), the 'time and position' window present."""
    r, o = case.r, case.o
    case.gui.diag = 777
    r.go_active(speed=5.0)
    o.is_scoring_mode = True
    o.score = score
    o.setting_end_idx = 2
    r.tick(3)
    return r, o


class A_PauseKeepsTheScoring(ManagedCase):
    def test_a_pause_keeps_the_whole_scoring_session(self):
        r, o = scoring_run(self)
        kept = (o.score, o.setting_end_idx, o.last_update_time, len(o.station_list), o.current_scenario_id)
        r.publish(True, False)
        r.tick(40, seconds=0.1)                                              # a long pause
        self.assertEqual(r.hud.mode, "waiting")
        self.assertEqual((o.is_scoring_mode, o.is_scoring_finished), (True, False))
        self.assertEqual((o.score, o.setting_end_idx, o.last_update_time, len(o.station_list), o.current_scenario_id), kept)
        self.assertEqual(r.events("scoring-abort"), [])
        self.assertEqual(r.input.aborts, 0)
        self.assertEqual(r.events("hud-error"), [])

    def test_the_input_is_released_at_once_and_stays_released_during_the_pause(self):
        r, o = scoring_run(self)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        self.assertFalse(self.gui.enabled)                                     # the "time and position" window is locked by the scoring
        r.publish(True, False)
        r.tick()                                                             # ONE tick later
        self.assertEqual(self.held(), [])
        self.assertTrue(self.gui.enabled)
        self.kb.pressed.update({"f7", "p", "f8", "f1", "f11", "f12"})
        posted = list(self.api.posted)
        calls = len(self.gui.calls)
        r.tick(20, seconds=0.1)
        self.assertEqual((self.held(), o.menu_state, r.hud.shown), ([], 0, False))
        self.assertEqual(self.api.posted, posted)                              # F8 / P are not injected, F1 opens nothing, F11 / F12 do nothing
        self.assertEqual(self.gui.calls[calls:], [])
        self.assertEqual(len(r.events("input-pause")), 1)

    def test_after_the_pause_the_same_scoring_goes_on_and_the_input_is_taken_again(self):
        r, o = scoring_run(self)
        r.publish(True, False)
        r.tick(10, seconds=0.1)
        r.publish(True, True)
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score, o.setting_end_idx), (True, -200, 2))
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        self.assertFalse(self.gui.enabled)                                     # locked again
        self.assertTrue(r.hud.shown)
        self.assertEqual(r.events("scoring-abort"), [])
        self.assertEqual(len(r.events("scoring-start")), 1)                    # no second start: it is the SAME scoring
        self.assertEqual(len(r.events("input-resume")), 1)

    def test_the_time_of_the_pause_is_never_a_step_of_the_scoring_clock(self):
        r, o = scoring_run(self)
        steps = []
        original = self.main.update_physics_and_scoring
        self.main.update_physics_and_scoring = lambda overlay, now, dt: (steps.append(round(dt, 6)), original(overlay, now, dt))[1]
        try:
            before = o.bve_time_ms
            r.publish(True, False)
            r.tick(5, seconds=0.1)
            r.send(self.MR.tele(1, time_ms=before + 600000, speed=0.0))      # BVE's time moved on while the steps did not run (10 minutes)
            r.tick(2, seconds=0.1)
            r.publish(True, True)
            r.tick(3)
        finally:
            self.main.update_physics_and_scoring = original
        self.assertTrue(steps)
        self.assertLess(max(steps), 1.0, steps)                                # without the resync the first step after the pause would be 600 s
        self.assertEqual(steps[0], 0.0)
        self.assertEqual(r.events("input-resume")[0].count("clock=synced"), 1)

    def test_a_time_that_went_back_during_the_pause_keeps_to_the_existing_rule(self):
        r, o = scoring_run(self)
        before = o.bve_time_ms
        r.publish(True, False)
        r.tick(3, seconds=0.1)
        r.send(self.MR.tele(1, time_ms=before - 30000, speed=0.0))
        r.publish(True, True)
        r.tick(3)
        self.assertEqual(r.events("input-resume")[0].count("clock=kept"), 1)
        self.assertEqual(r.events("hud-error"), [])
        self.assertTrue(o.is_scoring_mode)

    def test_the_fast_forward_measurement_starts_afresh_after_a_pause(self):
        r, o = scoring_run(self)
        r.publish(True, False)
        r.tick(5, seconds=0.1)
        r.send(self.MR.tele(1, time_ms=o.bve_time_ms + 600000, speed=5.0))
        before = len(self.posted_keys(R.KEY_F8))
        r.publish(True, True)
        r.tick(4, seconds=0.06)
        self.assertEqual(len(self.posted_keys(R.KEY_F8)), before)              # the pause is not read as a fast-forward
        self.assertEqual(r.events("ff-release"), [])

    def test_a_pause_with_the_menu_open_closes_it_quietly_and_keeps_the_scoring(self):
        r, o = scoring_run(self)
        r.tap("f1")
        self.assertEqual(o.menu_state, 1)
        posted = len(self.api.posted)
        r.publish(True, False)
        r.tick(3)
        self.assertEqual((o.menu_state, o.is_scoring_mode, self.held(), len(self.api.posted)), (0, True, [], posted))

    def test_a_finished_scoring_with_its_result_is_kept_by_a_pause_too(self):
        r, o = scoring_run(self)
        o.is_scoring_mode, o.is_scoring_finished = True, True
        r.tick(2)
        r.publish(True, False)
        r.tick(4)
        r.publish(True, True)
        r.tick(4)
        self.assertEqual((o.is_scoring_mode, o.is_scoring_finished, o.score), (True, True, -200))

    def test_pause_repeated_many_times_stays_within_the_log_budget(self):
        r, o = scoring_run(self)
        for _ in range(30):
            r.publish(True, False)
            r.tick(2)
            r.publish(True, True)
            r.tick(2)
        self.assertEqual(len(r.events("input-pause")), 6)
        self.assertEqual(len(r.events("input-resume")), 6)
        self.assertTrue(o.is_scoring_mode)
        for line in r.log.lines:
            if " event=input-pause" in line or " event=input-resume" in line:
                self.assertLessEqual(len(line), 160)

    # -- what still ends the scoring session ---------------------------------------------------------------------------------------------------
    def test_session_off_after_a_pause_discards_the_scoring(self):
        r, o = scoring_run(self)
        r.publish(True, False)
        r.tick(5)
        self.assertTrue(o.is_scoring_mode)
        r.publish(False, False)
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score, self.held(), o.station_list), (False, 0, [], []))
        r.publish(True, True)
        r.tick(3)
        self.assertFalse(o.is_scoring_mode)                                    # coming back does not resume it

    def test_a_new_generation_after_a_pause_discards_the_scoring(self):
        r, o = scoring_run(self)
        r.publish(True, False)
        r.tick(5)
        r.publish(True, False, 2)
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score, o.station_list), (False, 0, []))
        r.publish(True, True)
        r.tick(3)
        self.assertFalse(o.is_scoring_mode)

    def test_a_new_generation_while_driving_goes_off_discards_the_scoring(self):
        r, o = scoring_run(self)
        r.publish(True, False, 2)                                              # the generation and the Driving flag change in ONE reading
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score, o.station_list, self.held()), (False, 0, [], []))

    def test_the_loss_of_the_state_block_discards_the_scoring(self):
        r, o = scoring_run(self)
        r.publish(True, False)
        r.tick(3)
        r.source.data = None
        r.tick(3)
        self.assertEqual((r.hud.failsafe is not None, o.is_scoring_mode, self.held()), (True, False, []))

    def test_the_stop_request_after_a_pause_discards_the_scoring_and_restores(self):
        r, o = scoring_run(self)
        r.publish(True, False)
        r.tick(3)
        r.hud.shutdown()
        self.assertEqual((o.is_scoring_mode, self.held()), (False, []))
        self.assertTrue(self.gui.enabled)

    def test_the_users_own_abort_is_still_an_abort(self):
        r, o = scoring_run(self)
        o.is_scoring_mode = False
        r.tick(2)
        self.assertEqual(len(r.events("scoring-abort")), 1)
        self.assertEqual(self.held(), [])

    def test_a_pause_without_a_scoring_run_changes_nothing_but_the_release(self):
        r, o = self.r, self.o
        r.go_active(speed=5.0)
        r.tap("f1")
        r.publish(True, False)
        r.tick(3)
        r.publish(True, True)
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score), (False, 0))
        self.assertTrue(any("scoring=no" in e for e in r.events("input-pause")))
        r.tap("f1")
        self.assertEqual(o.menu_state, 1)


class B_PtoPWhileDrivingIsOff(ManagedCase):
    """Phase SI-A6 re-pinned this class. Phase SI-A4 pressed P-to-P when "Session ON, Driving OFF, STATUS PAUSED, no station list" held, on the belief that a
    scenario loaded PAUSED never ticks. The SR session showed the cost: every ORDINARY load shows exactly that for a few hundred milliseconds (P fired in three
    loads out of three). The situations below are kept and must now send NO P; the real recovery is token based (tests/test_pause_recovery_sia6.py)."""

    def paused_load(self, generation=1, driving=False):
        r = self.r
        r.publish(True, driving, generation)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(2)

    def test_the_first_half_presses_nothing_with_driving_off(self):
        r, o = self.r, self.o
        self.paused_load()
        self.assertEqual(r.hud.mode, "waiting")
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertEqual((o.initial_kickstart_done, o.auto_pause_pending), (False, False))
        self.assertEqual(r.events("kickstart"), [])
        self.assertFalse(r.hud.shown)
        r.tick(10)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)

    def test_the_second_half_does_not_exist_without_the_first(self):
        r, o = self.r, self.o
        self.paused_load()
        r.send("STATUS:LOADED:RUNNING", self.MR.STALIST, self.MR.tele(1, time_ms=36000500))
        r.tick(3)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertEqual((o.auto_pause_pending, len(o.station_list)), (False, 3))
        r.tick(10)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(10)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertFalse(r.hud.shown)

    def test_driving_turning_on_in_between_changes_nothing(self):
        r, o = self.r, self.o
        self.paused_load()
        r.publish(True, True)
        r.tick(2)
        r.send("STATUS:LOADED:RUNNING", self.MR.STALIST, self.MR.tele(1, time_ms=36000500))
        r.tick(4)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertEqual(r.events("kickstart"), [])

    def test_every_generation_presses_nothing_and_the_previous_one_leaves_nothing_behind(self):
        r, o = self.r, self.o
        for generation in (1, 2, 3):
            self.paused_load(generation)
            self.assertEqual(len(self.posted_keys(R.KEY_P)), 0, generation)
            r.send("STATUS:LOADED:RUNNING", self.MR.STALIST, self.MR.tele(generation, time_ms=36000500 + generation))
            r.tick(3)
            r.tick(5)
            self.assertEqual(len(self.posted_keys(R.KEY_P)), 0, generation)
            r.publish(True, False, generation + 1)                                # the next scenario instance
            r.tick(2)
            self.assertEqual((o.station_list, o.initial_kickstart_done, o.auto_pause_pending, o.is_bve_loaded, o.bve_actual_state),
                             ([], False, False, False, ""))                       # the station list, the STATUS and the kick start state of the previous one are gone
            self.assertNotIn("kick_bve_time", vars(o))

    def test_nothing_else_of_the_input_acts_while_driving_is_off(self):
        r, o = self.r, self.o
        self.paused_load()
        calls = len(self.gui.calls)
        self.kb.pressed.update({"f1", "f7", "p", "f8", "f11", "f12", "enter", "down"})
        r.tick(20, seconds=0.1)
        self.assertEqual((self.held(), o.menu_state, r.input.steps, r.hud.shown, o.is_scoring_mode), ([], 0, 0, False, False))
        self.assertEqual(self.gui.calls[calls:], [])
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertEqual(self.posted_keys(R.KEY_F8), [])
        self.assertEqual(r.events("input-hold"), [])

    def test_no_window_search_is_made_for_a_waiting_state(self):
        r = self.r
        r.publish(True, False, 1)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        searches = self.win.searches
        r.tick(20, seconds=0.6)
        self.assertEqual(self.posted_keys(R.KEY_P), [])
        self.assertEqual(self.win.searches, searches)

    def test_the_hud_is_never_shown_and_no_f8_is_posted(self):
        r = self.r
        self.paused_load()
        r.send("STATUS:LOADED:RUNNING", self.MR.STALIST, self.MR.tele(1, time_ms=36000500))
        r.tick(3)
        self.assertEqual(self.posted_keys(R.KEY_F8), [])
        self.assertEqual(r.events("hud-show"), [])

    def test_a_session_off_between_what_used_to_be_the_halves_changes_nothing(self):
        r, o = self.r, self.o
        self.paused_load()
        r.publish(False, False)
        r.tick(3)
        r.send("STATUS:LOADED:RUNNING", self.MR.STALIST, self.MR.tele(1, time_ms=36000500))
        r.tick(5)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)

class C_HoldingSpeedTextsInThePowerWidth(ManagedCase):
    """ALLTXT:<rev>:<power>:<brake>[:<holding speed>] - the POW column shows a holding speed text while powNotch < 0, so its width is decided in advance
    from the power texts AND the holding speed texts. The brake column is not touched."""
    BRK2 = "N_B1_B2_B3_B4_B5_B6_B7_EB"
    BRK1 = "N_B1_B2_B3_EB"
    HOLD = "抑速1_抑速2_抑速3"

    def widths(self, texts, offset=False):
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.o.font_ui)
        out = []
        for s in texts:
            w = fm.horizontalAdvance(s)
            if offset:
                for suffix, off in self.main.KERNING_OFFSETS.items():
                    if s.endswith(suffix):
                        w -= off
                        break
            out.append(w)
        return out

    def apply(self, htype, rev, pow_, brk, hold=None, pow_text="N", pow_notch=0):
        alltxt = "ALLTXT:%s:%s:%s" % (rev, pow_, brk) + ("" if hold is None else ":" + hold)
        self.o.apply_telemetry_text("SCENARIO_ID:1,REV:前:1,POW:%s:%d,BRK:N:0:8,HTYPE:%d,%s" % (pow_text, pow_notch, htype, alltxt))
        return self.o

    def test_the_display_text_that_was_cut_is_now_inside_the_width(self):
        o = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, self.HOLD)
        needed = self.widths(["抑速3"])[0]
        self.assertGreaterEqual(o.max_pow_w, needed)
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3"] + ["抑速1", "抑速2", "抑速3"])))
        self.assertGreater(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3"])))        # the old width (power texts only) was too narrow

    def test_two_handles_without_holding_speed(self):
        o = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, "")
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3"])))

    def test_one_handle_with_and_without_holding_speed(self):
        o = self.apply(1, "切_前_後", "N_P1_P2_P3", self.BRK1, self.HOLD)
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3", "抑速1", "抑速2", "抑速3"])))
        self.assertTrue(o.is_single_handle)
        o = self.apply(1, "切_前_後", "N_P1_P2_P3", self.BRK1, "")
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3"])))

    def test_holding_speed_longer_than_the_power_texts(self):
        o = self.apply(2, "前", "N_P1_P2", self.BRK2, "抑速ノッチ１_抑速ノッチ２")
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "抑速ノッチ１", "抑速ノッチ２"])))

    def test_power_longer_than_the_holding_speed_texts(self):
        o = self.apply(2, "前", "ニュートラル_力行１_力行２", self.BRK2, "H1_H2")
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["ニュートラル", "力行１", "力行２", "H1", "H2"])))

    def test_an_old_message_without_the_fourth_group_keeps_the_old_width(self):
        o = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, None)
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3"])))
        self.assertEqual(o.max_rev_w, max([40] + self.widths(["切", "前", "後"])))

    def test_a_fourth_group_of_blanks_adds_nothing(self):
        o = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, "_ _")
        self.assertEqual(o.max_pow_w, max([40] + self.widths(["N", "P1", "P2", "P3"])))

    def test_the_brake_column_and_the_reverser_column_never_take_the_holding_speed_texts(self):
        with_hold = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, "とても長い抑速の表示文字列")
        brk, rev, brk_list = with_hold.max_brk_w, with_hold.max_rev_w, list(with_hold.all_brk_texts)
        without = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, None)
        self.assertEqual((brk, rev, brk_list), (without.max_brk_w, without.max_rev_w, list(without.all_brk_texts)))
        self.assertEqual(brk, max([40] + self.widths(self.BRK2.split("_"), offset=True)))

    def test_the_single_handle_brake_evaluation_still_skips_its_first_text(self):
        o = self.apply(1, "前", "N_P1", "非常に長い先頭要素_B1_B2_EB", self.HOLD)
        self.assertEqual(o.max_brk_w, max([40] + self.widths(["B1", "B2", "EB"], offset=True)))

    def test_switching_between_power_and_holding_speed_does_not_move_the_width(self):
        o = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, self.HOLD)
        fixed = o.max_pow_w
        for text, notch in (("P3", 3), ("抑速3", -3), ("N", 0), ("抑速1", -1), ("P1", 1)):
            o.apply_telemetry_text("POW:%s:%d" % (text, notch))
            self.assertEqual(o.max_pow_w, fixed, text)
            o.apply_telemetry_text("SCENARIO_ID:1,REV:前:1,POW:%s:%d,BRK:N:0:8,HTYPE:2,ALLTXT:切_前_後:N_P1_P2_P3:%s:%s" % (text, notch, self.BRK2, self.HOLD))
            self.assertEqual(o.max_pow_w, fixed, text)

    def test_the_new_width_reaches_the_hud_layout(self):
        """hud_ui reads max_pow_w for the two-handle layout: the right edge of the brake column and the power column follow it."""
        o = self.apply(2, "切_前_後", "N_P1_P2_P3", self.BRK2, self.HOLD)
        with open(os.path.join(R.ROOT, "hud_ui.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("self.max_pow_w", text)
        self.assertGreater(o.max_pow_w, 40)


class D_Scope(unittest.TestCase):
    """What SI-A4 may and may not touch (the unchanged side is audited with hashes in the package audit; this is the static part)."""

    def read(self, name):
        with open(os.path.join(R.ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_driving_off_is_reported_to_on_pause_and_not_to_on_inactive(self):
        text = self.read("managed_hud.py")
        self.assertIn('self._input.on_pause("driving-off")', text)
        self.assertNotIn('on_inactive("driving-off")', text)
        self.assertIn('self._input.on_inactive("session-off")', text)
        self.assertIn('self._input.on_inactive("state-lost")', text)

    def test_the_waiting_branch_calls_nothing_of_the_kick_start_any_more(self):
        """Phase SI-A6: `_tick_waiting_kickstart` is gone; the WAITING branch of the controller's tick does nothing but let the recovery watch (attach_recovery)."""
        import ast
        tree = ast.parse(self.read("managed_hud.py"))
        self.assertEqual([n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and "kick" in n.name], [])
        tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "tick")
        called = sorted({n.func.attr for n in ast.walk(tick) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)})
        self.assertNotIn("kick_start_wanted", called)
        self.assertNotIn("tick_waiting_kickstart", called)

    def test_the_overlay_has_no_kick_start_for_driving_off_any_more(self):
        import ast
        tree = ast.parse(self.read("main.py"))
        names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        self.assertNotIn("kick_start_managed_waiting", names)
        self.assertNotIn("kick_start_wanted", names)

if __name__ == "__main__":
    unittest.main()
