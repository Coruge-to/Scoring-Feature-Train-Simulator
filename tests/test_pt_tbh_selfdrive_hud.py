"""Stage TB-H 6: (1) the user-facing warning of the unrecoverable failure (B reached by driving) and the one wording of the illegal-movement warning; (2) the ORDINARY TScoring HUD display target is the pair A for the whole life of the chain (until the official Jump succeeded AND B is established); the rule overlay (debug / diagnostic) stays on the raw scoring target.

Owner decisions (2026-11-02):
  * B reached by driving from the pending A (not recovered by a re-stop): fail-closed as before (no Jump, B is not scored, no B checkpoint, no turnback checkpoint, scoring aborted, internal reason
    pseudo-turnback-self-drive-b), and now a RED two-line user warning:  不正な移動が検知されました。 / 採点を中止します。
  * the existing illegal-Jump warning gets the SAME user wording (it was 不正なジャンプを検知しました。 / 採点を中断します。); the internal diagnostics stay distinguishable (illegal Jump: no [TURNBACK] line; B by
    driving: [TURNBACK] turnback-fail reason=pseudo-turnback-self-drive-b).
  * moving away from A alone is recoverable (red cancellation lines, the scoring goes on); the TScoring HUD display target is the pair A (display layer only) from the arrival until the official Jump succeeded AND B is
    established - NOT released by a re-stop, a re-cancellation or the 5 s after a re-stop. The raw target, the scoring target, the C# StationIndex, the score, the history and the checkpoints are never changed. The BVE's own
    station display (the bar '次 ... 停車 あと ... m') is not the application's and is out of scope.
RED = fails on the baseline (373ecd5..f1288f4), GUARD = already true there."""
import ast
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

_TMP = {}

U1 = "不正な移動が検知されました。"
U2 = "採点を中止します。"
OLD_J1 = "不正なジャンプを検知しました。"
OLD_J2 = "採点を中断します。"
W1 = "発車位置への移動がキャンセルされました。"
W2 = "許容範囲内に再度列車を停止させてください。"
G1 = "発車位置へ移動します。"
G2 = "列車を動かさないでください。"
SELF_DRIVE_B_REASON = "pseudo-turnback-self-drive-b"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbh-sdhud-")
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
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbh-sdhud"])
        import config
        import main
        import scoring_logic
        import tbg_c01_rig
        import pt_scene
        import pseudo_turnback_machine
        cls.cfg, cls.main, cls.S, cls.R, cls.P, cls.M = config, main, scoring_logic, tbg_c01_rig, pt_scene, pseudo_turnback_machine

    def scene(self):
        f = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        f.to_arrival_at_a()
        f.scene.sent = f.sent
        return f.scene, f.scene.machine.arrival_ms, f

    def tick_to(self, s, abs_ms, **fields):
        s.tick(advance_ms=abs_ms - s.o.bve_time_ms, **fields)

    def move(self, s, abs_ms, dist=10.0, speed=2.0, **extra):
        extra.setdefault("bve_door", 0)
        self.tick_to(s, abs_ms, bve_speed=speed, bve_location=self.P.A_MARK - 0.3 + dist, bve_brk_notch=0, **extra)

    def halt(self, s, abs_ms, offset=-1.0, **extra):
        self.tick_to(s, abs_ms, bve_speed=0.0, bve_location=self.P.A_MARK + offset, **extra)

    def b_target(self, s, abs_ms, **extra):
        """The C# state machine advanced its target to B while the train moves away from A (what the Owner saw on the HUD)."""
        b = s.sl[2]
        self.tick_to(s, abs_ms, bve_next_loc=b["location"], bve_tgt_idx=2, **extra)

    def waiting(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.b_target(s, t + 2100, bve_speed=2.0, bve_location=self.P.A_MARK + 9.7, bve_brk_notch=0)
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
        return s, t, f

    def drive_to_b(self, s, t):
        o = s.o
        b = s.sl[2]
        self.tick_to(s, t + 4000, bve_next_loc=b["location"], bve_tgt_idx=2, bve_speed=2.0, bve_location=b["location"] - 100.0, bve_brk_notch=0)
        self.tick_to(s, t + 5000, bve_speed=0.0, bve_location=b["location"] - 0.3, bve_brk_notch=8)
        self.tick_to(s, t + 6000, bve_door=1, bve_arr_idx=2, bve_arr_seq=o.bve_arr_seq + 1)

    def warn_texts(self, s):
        return [p["text"] for p in s.o.popups if p["category"] == "警告"]

    def hud(self, s):
        s.o._hud_target_sync()
        return s.o._hud_target


# ==============================================================================================================================================
# SD  B reached by driving: the red user warning, the unchanged fail-closed contract, the distinguishable diagnostics
# ==============================================================================================================================================
class A_SelfDriveB(Base):
    def test_SD_01_b_by_driving_shows_the_red_two_line_warning_with_the_exact_wording(self):
        s, t, f = self.waiting()
        self.drive_to_b(s, t)
        rows = [p for p in s.o.popups if p["category"] == "警告"]
        self.assertEqual([p["text"] for p in rows], [U1, U2], "RED on the baseline: no user-facing warning at all (diagnostics only)")
        for p in rows:
            self.assertEqual((p["color"], p["type"]), (self.cfg.COLOR_B_EMG, "big"))
        for p in rows:
            self.assertAlmostEqual(p["expire_time"], s.o.bve_time_ms / 1000.0 + 5.0, places=3, msg="the same 5.0 s as the other warnings")

    def test_SD_02_the_fail_closed_contract_is_unchanged(self):
        s, t, f = self.waiting()
        o = s.o
        score_before, history_before = o.score, len(o.save_data)
        self.drive_to_b(s, t)
        for k in range(1, 30):
            self.tick_to(s, t + 6000 + 100 * k)
        self.assertEqual(list(f.sent), [], "no official Jump")
        self.assertEqual(s.machine.state, self.M.IDLE, "the wait state is discarded")
        self.assertFalse(o.is_scoring_mode, "scoring abort")
        self.assertTrue(o.jump_lock)
        self.assertEqual(o.score, score_before, "no B stop position, no B basic braking, no B timing score")
        self.assertEqual(len(o.save_data), history_before, "no ordinary B checkpoint and no pseudo-turnback checkpoint")
        self.assertIsNone(o.jump_expectation)

    def test_SD_03_the_internal_reason_of_b_by_driving_is_kept_and_is_the_only_turnback_fail_line(self):
        s, t, f = self.waiting()
        self.drive_to_b(s, t)
        self.assertEqual([e[1].get("reason") for e in self.events_of(f)], [SELF_DRIVE_B_REASON])

    def events_of(self, f):
        return [e for e in f.events if e[0] == "diag:turnback-fail"]

    def test_SD_04_the_illegal_jump_warning_has_the_same_user_wording_and_a_different_internal_trace(self):
        s, t, f = self.scene()
        o = s.o
        o.is_official_jumping = False
        o.bve_jump_count = getattr(o, "bve_jump_count", 0) + 1                       # a jump BVE reports that no official Jump explains
        s.step(2)
        rows = [p for p in o.popups if p["category"] == "警告"]
        self.assertEqual([p["text"] for p in rows], [U1, U2], "RED on the baseline: the old wording 不正なジャンプを検知しました。／採点を中断します。")
        for p in rows:
            self.assertEqual((p["color"], p["type"]), (self.cfg.COLOR_B_EMG, "big"))
        self.assertEqual(self.events_of(f), [], "an illegal Jump leaves NO pseudo-turnback failure line: the two causes stay distinguishable in the log")
        self.assertFalse(o.is_scoring_mode)

    def test_SD_05_the_old_wording_is_gone_from_every_user_facing_place(self):
        import scoring_logic
        source = inspect.getsource(scoring_logic)
        self.assertNotIn(OLD_J1, source, "RED on the baseline")
        self.assertNotIn(OLD_J2, source, "RED on the baseline")
        self.assertEqual(source.count(U1), 1, "the wording lives in ONE constant")
        self.assertEqual(self.S.ILLEGAL_MOVE_TEXTS, (U1, U2))

    def test_SD_06_moving_away_from_a_is_recoverable_no_abort_no_illegal_move_warning(self):
        s, t, f = self.waiting()
        o = s.o
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual([p["text"] for p in o.popups if p["text"] in (W1, W2)], [W1, W2])
        self.assertEqual(self.warn_texts(s), [], "the red cancellation lines are their own category; no illegal-move wording")
        for k in range(1, 40):
            self.tick_to(s, t + 2100 + 100 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 20.0)
        self.assertTrue(o.is_scoring_mode, "a stop outside the range is not a failure")
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
        self.assertEqual([p["text"] for p in o.popups if p["text"] in (U1, U2)], [])

    def test_SD_07_going_back_to_a_continues_the_scoring_and_the_jump_comes_five_seconds_later(self):
        s, t, f = self.waiting()
        o = s.o
        self.halt(s, t + 4000, offset=-1.0)
        self.assertEqual(s.machine.state, self.M.ARMED)
        self.tick_to(s, t + 9000)
        self.assertEqual(len(f.sent), 1)
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual([p["text"] for p in o.popups if p["text"] in (U1, U2)], [])

    def test_SD_08_a_formal_arrival_at_another_station_or_a_landing_shows_no_illegal_move_warning(self):
        s, t, f = self.waiting()
        o = s.o
        hook = self.S.turnback_other_arrival
        self.assertIs(hook(o, 1), False)                                     # A itself
        for field in ("jump_lock", "is_official_jumping"):                   # the landing of a Jump
            setattr(o, field, True)
            self.assertIs(hook(o, 2), False)
            setattr(o, field, False)
        self.assertEqual(self.warn_texts(s), [])
        self.assertIs(hook(o, 3), False)                                     # another station only drops the wait state
        self.assertEqual(self.warn_texts(s), [])

    def test_SD_09_nothing_is_left_after_the_abort(self):
        s, t, f = self.waiting()
        o = s.o
        self.drive_to_b(s, t)
        m = s.machine
        self.assertEqual((m.state, m.pair, m.fixed, m.landing_watch), (self.M.IDLE, None, None, None))
        self.assertEqual([p["text"] for p in o.popups if p["text"] in (G1, G2, W1, W2)], [], "no guidance and no cancellation line of the dead chain")
        self.assertIsNone(self.S.turnback_held_a_target(o), "no held HUD target")
        self.assertFalse(o.is_official_jumping)
        for k in range(1, 50):                                               # the warning lives 5 s, then it is gone
            self.tick_to(s, t + 6000 + 200 * k)
        self.assertEqual(self.warn_texts(s), [])

    def test_SD_10_the_warning_is_added_after_the_abort_and_nothing_else_in_the_hook_adds_popups(self):
        source = inspect.getsource(self.S.turnback_other_arrival)
        calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)]
        names = {getattr(c.func, "id", getattr(c.func, "attr", "")) for c in calls}
        self.assertIn("turnback_stop_scoring", names)
        self.assertIn("turnback_illegal_move_show", names, "RED on the baseline")
        self.assertNotIn("add_score_popup", names)


# ==============================================================================================================================================
# HD  the HUD target is the pair A while the re-stop wait lasts (display layer only)
# ==============================================================================================================================================
class B_HudTarget(Base):
    def test_HD_01_while_the_restop_is_needed_the_hud_target_is_a_not_the_advanced_target_b(self):
        s, t, f = self.waiting()
        o = s.o
        b = s.sl[2]
        self.assertEqual(o.bve_next_loc, b["location"], "the sender's (C#) target is B: the raw target is NOT changed")
        h = self.hud(s)
        self.assertEqual(h.next_loc, self.P.A_MARK, "RED on the baseline: the HUD shows B")
        self.assertEqual(h.is_pass, 0)
        self.assertEqual((h.margin_b, h.margin_f), (5.0, 5.0))
        self.assertEqual(o.hud_target_next_loc, self.P.A_MARK)
        self.assertEqual(h.owner, "TS")

    def test_HD_02_the_raw_target_the_scoring_target_and_the_station_index_are_never_touched(self):
        s, t, f = self.waiting()
        o = s.o
        names = ("bve_next_loc", "bve_next_time", "bve_is_pass", "bve_margin_b", "bve_margin_f", "bve_tgt_idx", "bve_arr_idx", "bve_arr_seq", "bve_list_id", "score")
        before = {n: getattr(o, n) for n in names}
        self.hud(s)
        self.hud(s)
        self.assertEqual({n: getattr(o, n) for n in names}, before)
        self.assertEqual(o.bve_tgt_idx, 2)

    def test_HD_03_the_distance_row_is_measured_to_a(self):
        s, t, f = self.waiting()
        o = s.o
        h = self.hud(s)
        d = h.next_loc - o.bve_location
        self.assertLess(d, 0, "the train is past A: the distance to A is negative (the HUD draws it red: go back)")
        self.assertAlmostEqual(d, -9.7, delta=0.01)

    def test_HD_04_during_the_first_ten_seconds_the_target_is_a(self):
        s, t, f = self.scene()
        o = s.o
        samples = []
        for ms in (100, 2000, 4900, 5000, 6500, 8000, 9900):                          # the quiet seconds, the guidance, up to the Jump request
            self.tick_to(s, t + ms)
            samples.append((self.hud(s).next_loc, o.bve_next_loc))
        self.assertEqual(samples, [(self.P.A_MARK, self.P.A_MARK)] * 7)
        self.assertIsNotNone(self.S.turnback_held_a_target(o), "the hold exists from the arrival (it equals the raw target while the sender still holds A)")

    def test_HD_05_the_restop_does_not_release_the_hold_the_five_seconds_after_it_are_a_too(self):
        s, t, f = self.waiting()
        o = s.o
        self.halt(s, t + 4000, offset=-1.0)
        self.assertEqual(s.machine.state, self.M.ARMED)
        seen = []
        for ms in (4000, 4016, 5000, 6500, 8000, 8900):                                # the whole new 5.0 s (the Jump is requested at 9000)
            self.tick_to(s, t + ms) if ms > 4000 else None
            seen.append(self.hud(s).next_loc)
        self.assertEqual(seen, [self.P.A_MARK] * 6, "RED if the display went back to B at the re-stop")
        self.assertEqual(o.bve_next_loc, s.sl[2]["location"], "the raw target is B all the time")
        self.assertEqual(len(f.sent), 0)

    def test_HD_06_the_hold_is_released_when_b_is_reached_by_driving_and_by_every_other_end_of_the_chain(self):
        s, t, f = self.waiting()
        self.drive_to_b(s, t)
        self.assertIsNone(self.S.turnback_held_a_target(s.o))
        for how in ("f5", "generation", "scoring_off", "retry", "pairset"):
            with self.subTest(how=how):
                s2, t2, f2 = self.waiting()
                o = s2.o
                if how == "f5":
                    o.is_scoring_mode = False
                    o.current_scenario_id = o.current_scenario_id + 1
                elif how == "generation":
                    o.reset_generation_state()
                elif how == "retry":
                    s2.machine.on_retry()
                elif how == "pairset":
                    s2.machine.discard_all()
                else:
                    o.is_scoring_mode = False
                s2.step(3)
                self.assertIsNone(self.S.turnback_held_a_target(o))

    def test_HD_07_a_capture_of_an_older_arrival_is_never_used(self):
        s, t, f = self.waiting()
        o = s.o
        capture = o.__dict__.get("_turnback_a_view")
        self.assertIsNotNone(capture)
        o._turnback_a_view = (capture[0] + 1, capture[1])
        self.assertIsNone(self.S.turnback_held_a_target(o))
        o._turnback_a_view = None
        self.assertIsNone(self.S.turnback_held_a_target(o))

    def test_HD_08_a_station_that_is_not_a_pair_a_never_gets_a_held_target(self):
        s = self.P.Scene(self, with_pairs=False, drive=True)
        s.arrive_a()
        s.tick(advance_ms=2000, bve_speed=2.0, bve_location=self.P.A_MARK + 10.0, bve_brk_notch=0, bve_door=0)
        self.assertIsNone(self.S.turnback_held_a_target(s.o))

    def test_HD_09_the_held_values_are_those_of_a_at_its_arrival(self):
        s, t, f = self.scene()
        o = s.o
        expected = o._hud_machine_target()
        self.move(s, t + 2000)
        self.b_target(s, t + 2100, bve_speed=2.0, bve_location=self.P.A_MARK + 9.7, bve_brk_notch=0)
        self.assertEqual(self.S.turnback_held_a_target(o), expected)
        self.assertNotEqual(o.bve_next_loc, expected.next_loc, "the raw target is B, the held one is A")

    def test_HD_12_judging_the_same_arrival_again_after_the_target_advanced_keeps_the_target_of_the_arrival(self):
        s, t, f = self.waiting()
        o = s.o
        held = self.S.turnback_held_a_target(o)
        self.assertEqual(held.next_loc, self.P.A_MARK)
        self.S.turnback_arrival_begin(o, t / 1000.0, 1, self.P.A_MARK)                  # the arrival of A is judged once more (the raw target is B by now)
        self.assertEqual(self.S.turnback_held_a_target(o), held, "judging the arrival again while the chain lives does not change the held target")
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK)
    def test_HD_13_a_second_cancellation_holds_a_again_even_if_the_arrival_was_judged_again_in_between(self):
        s, t, f = self.waiting()
        o = s.o
        self.halt(s, t + 4000, offset=-1.0)                                              # the re-stop: the hold ends, the raw target (B) is drawn
        self.assertEqual(s.machine.state, self.M.ARMED)
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK, "the re-stop does not release the hold")
        self.S.turnback_arrival_begin(o, t / 1000.0, 1, self.P.A_MARK)                  # the arrival of A is judged once more while the raw target is B
        self.move(s, t + 5000)                                                          # the second cancellation
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK, "the second wait holds A as well")

    def test_HD_14_the_hold_is_the_same_a_in_every_state_of_the_same_arrival(self):
        s, t, f = self.waiting()
        seen = [self.hud(s).next_loc]
        self.halt(s, t + 4000, offset=-1.0)
        seen.append(self.hud(s).next_loc)
        self.move(s, t + 5000)
        seen.append(self.hud(s).next_loc)
        self.assertEqual(seen, [self.P.A_MARK, self.P.A_MARK, self.P.A_MARK], "RED if the re-stop released the hold")
    def test_HD_15_cancelled_and_red_warning_and_out_of_range_all_show_a(self):
        s, t, f = self.waiting()
        o = s.o
        self.assertEqual([p["text"] for p in o.popups if p["text"] in (W1, W2)], [W1, W2], "the red cancellation warning is on the screen")
        rows = [self.hud(s).next_loc]
        for k in range(1, 130):                                                       # out of the range for 13 s (the warning is gone after 5 s)
            self.tick_to(s, t + 2100 + 100 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 20.0)
            rows.append(self.hud(s).next_loc)
        self.assertEqual(set(rows), {self.P.A_MARK})
        self.assertEqual([p["text"] for p in o.popups if p["text"] in (W1, W2)], [], "the warning ended, the display target is still A")

    def test_HD_16_however_many_times_the_train_is_cancelled_and_stopped_again_the_target_stays_a(self):
        s, t, f = self.waiting()
        o = s.o
        now = t + 2100
        rows = [self.hud(s).next_loc]
        for cycle in range(4):                                                        # re-stop, 5 s wait is NOT completed, moves again, re-cancel ...
            now += 1000
            self.halt(s, now, offset=-1.0)
            self.assertEqual(s.machine.state, self.M.ARMED)
            rows.append(self.hud(s).next_loc)
            now += 2000
            self.tick_to(s, now)
            rows.append(self.hud(s).next_loc)
            now += 500
            self.move(s, now)
            self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
            rows.append(self.hud(s).next_loc)
        self.assertEqual(set(rows), {self.P.A_MARK})
        self.assertEqual(len(f.sent), 0)
        self.assertEqual(s.machine.cancel_count, 5)

    def test_HD_17_the_hold_lasts_through_the_request_and_the_jump_until_b_is_established(self):
        f = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        f.to_arrival_at_a()
        s = f.scene
        s.sent = f.sent
        o = s.o
        t = s.machine.arrival_ms
        self.move(s, t + 2000)
        self.b_target(s, t + 2100, bve_speed=2.0, bve_location=self.P.A_MARK + 9.7, bve_brk_notch=0)
        self.halt(s, t + 4000, offset=-1.0)
        self.tick_to(s, t + 9000)                                                      # the Jump is requested 5.0 s after the re-stop
        self.assertEqual(s.machine.state, self.M.REQUESTED)
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK, "the Jump is in flight: still A")
        m = s.machine
        # the completion of the official Jump is reported, B is not established yet: still A (the unit-level read model; the rig establishes B inside the same settlement)
        m.on_jump_complete(True, 2, m.generation)
        self.assertTrue(m.awaiting_b)
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK, "the Jump succeeded but B is not established: A")
        m.on_b_established(o.bve_time_ms)
        self.assertEqual(m.state, self.M.IDLE)
        self.assertIsNone(self.S.turnback_held_a_target(o))
        self.assertEqual(self.hud(s).next_loc, o.bve_next_loc, "B is established: the normal target")

    def test_HD_17b_the_real_landing_returns_the_display_to_the_normal_target(self):
        f = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        f.to_arrival_at_a()
        s = f.scene
        s.sent = f.sent
        o = s.o
        t = s.machine.arrival_ms
        self.move(s, t + 2000)
        self.b_target(s, t + 2100, bve_speed=2.0, bve_location=self.P.A_MARK + 9.7, bve_brk_notch=0)
        self.halt(s, t + 4000, offset=-1.0)
        self.tick_to(s, t + 9000)
        self.assertEqual(s.machine.state, self.M.REQUESTED)
        f.land()
        f.after(3)
        self.assertEqual(s.machine.state, self.M.IDLE)
        h = self.hud(s)
        self.assertEqual(h.next_loc, o.bve_next_loc)
        self.assertNotEqual(h.next_loc, self.P.A_MARK)
        self.assertEqual(len(f.sent), 1)
    def test_HD_18_score_history_checkpoints_and_every_raw_value_are_unchanged_by_the_hold(self):
        s, t, f = self.waiting()
        o = s.o
        names = ("score", "bve_next_loc", "bve_next_time", "bve_is_pass", "bve_margin_b", "bve_margin_f", "bve_tgt_idx", "bve_arr_idx", "bve_arr_seq", "bve_list_id")
        before = ({n: getattr(o, n) for n in names}, len(o.save_data), [dict(c) for c in o.save_data])
        for k in range(20):
            self.tick_to(s, t + 2200 + 100 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 20.0)
            self.hud(s)
        after = ({n: getattr(o, n) for n in names}, len(o.save_data), [dict(c) for c in o.save_data])
        self.assertEqual(after, before)

    def test_HD_19_the_hold_has_no_current_or_legacy_branch(self):
        for fn in (self.S.turnback_held_a_target,):
            words = {n.id for n in ast.walk(ast.parse(inspect.getsource(fn))) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(ast.parse(inspect.getsource(fn))) if isinstance(n, ast.Attribute)}
            for banned in ("managed", "legacy", "Legacy", "current_host", "host_mode", "is_legacy", "AtsEx"):
                self.assertNotIn(banned, words)

    def test_HD_20_the_bve_own_station_bar_is_not_drawn_by_this_application(self):
        """The bar '次 ... 停車 あと ... m' on top of the BVE window is the BVE's / the scenario's own display; this application draws neither the word nor the bar, so the hold cannot and does not touch it."""
        import hud_ui
        for module in (hud_ui, self.main):
            self.assertNotIn("あと", inspect.getsource(module), "the application draws no 'あと NN m' bar")

    def test_HD_23_a_failed_chain_holds_nothing(self):
        s, t, f = self.waiting()
        o = s.o
        s.machine.on_other_arrival(2)                                                   # B reached by driving: the chain is FAILED (the pair and the arrival time are still there)
        self.assertEqual(s.machine.state, self.M.FAILED)
        self.assertIsNone(self.S.turnback_held_a_target(o))
        self.assertEqual(self.hud(s).next_loc, o.bve_next_loc)

    def test_HD_24_the_whole_five_seconds_after_the_second_restop_are_a_and_so_is_the_request(self):
        s, t, f = self.waiting()
        o = s.o
        self.halt(s, t + 3000, offset=-1.0)                                           # the first re-stop
        self.move(s, t + 3500)                                                        # the re-cancellation
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
        self.halt(s, t + 4000, offset=-0.5)                                           # the second re-stop: the new 5.0 s start here
        self.assertEqual(s.machine.state, self.M.ARMED)
        rows = []
        for ms in range(4000, 8990, 250):
            self.tick_to(s, t + ms) if ms > 4000 else None
            rows.append(self.hud(s).next_loc)
        self.assertEqual(set(rows), {self.P.A_MARK}, "RED if the display went back to B at the second re-stop")
        self.tick_to(s, t + 9000)
        self.assertEqual(s.machine.state, self.M.REQUESTED)
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK, "the request itself: still A")
        self.assertEqual(len(f.sent), 1)
    def test_HD_10_the_override_reads_no_door_indicator_or_signal_and_writes_nothing_of_the_target(self):
        fn = self.S.turnback_held_a_target
        tree = ast.parse(inspect.getsource(fn))
        words = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                words.add(node.attr)
            elif isinstance(node, ast.Name):
                words.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                words.add(node.value)
        for banned in ("bve_door", "bve_doordir", "bve_indicator", "signalFlag", "signal_flag", "bve_signal", "bve_speed", "bve_location"):
            self.assertNotIn(banned, words)
        assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AugAssign)) and any(isinstance(t, ast.Attribute) for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
        self.assertEqual(assigns, [], "a read model: it assigns no attribute")

    def test_HD_11_the_machine_and_the_hud_derivation_are_not_changed(self):
        import hud_target_contract
        src = inspect.getsource(hud_target_contract.derive)
        self.assertIn("machine = machine_of()", src)
        self.assertNotIn("turnback", src)


# ==============================================================================================================================================
# OV  the rule overlay (debug / diagnostic) is on the RAW scoring target and consistent with itself; only the ordinary HUD holds A
# ==============================================================================================================================================
class RecordingPainter(object):
    """A real QPainter on an image whose drawText calls are recorded (the overlay lines are the strings of drawText)."""

    def __init__(self, painter):
        self._p = painter
        self.texts = []

    def drawText(self, *args):
        self.texts.append(args[-1])
        return self._p.drawText(*args)

    def __getattr__(self, name):
        return getattr(self._p, name)


class C_RuleOverlay(Base):
    def waiting_with_rules(self):
        s, t, f = self.scene()
        o = s.o
        # the rule sections are different for A (index 1) and B (index 2): the section of A is '2段', the section of B is '3段'
        o.brake_rules = [{"end_idx": 1, "apply": "2段", "release": "2段"}, {"end_idx": -1, "apply": "3段", "release": "3段"}]
        o.penalty_init_rules = [{"apply": "ON②", "release": "ON②"}, {"apply": "ON①", "release": "ON①"}]
        self.move(s, t + 2000)
        self.b_target(s, t + 2100, bve_speed=2.0, bve_location=self.P.A_MARK + 9.7, bve_brk_notch=0)
        s.step(2, bve_speed=2.0)
        self.assertEqual(s.machine.state, self.M.RESTOP_WAIT)
        return s, t, f

    def overlay_lines(self, s):
        from PyQt6.QtGui import QImage, QPainter
        o = s.o
        o.show_graph = True
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        recorder = RecordingPainter(painter)
        try:
            import hud_ui
            hud_ui.draw_hud(o, recorder, 1920)
        finally:
            painter.end()
        return recorder.texts

    def test_OV_01_the_overlay_names_the_raw_scoring_target_not_the_held_a(self):
        s, t, f = self.waiting_with_rules()
        o = s.o
        lines = self.overlay_lines(s)
        rule_line = [x for x in lines if x.startswith("[SCORING RULES]")]
        self.assertEqual(len(rule_line), 1, lines)
        raw_name = s.sl[o.bve_tgt_idx]["name"]
        a_name = s.sl[1]["name"]
        self.assertNotEqual(raw_name, a_name)
        self.assertIn(raw_name, rule_line[0], "RED on the Stage 6 commit: the overlay named the held A")
        self.assertNotIn(a_name, rule_line[0].replace(raw_name, ""))
        self.assertEqual(self.hud(s).next_loc, self.P.A_MARK, "while the ORDINARY HUD draws A")

    def test_OV_02_the_overlay_timing_label_is_the_raw_scoring_targets(self):
        s, t, f = self.waiting_with_rules()
        o = s.o
        expect = "採時" if o.is_station_timing(o.bve_tgt_idx) else "非採時"
        rule_line = [x for x in self.overlay_lines(s) if x.startswith("[SCORING RULES]")][0]
        self.assertTrue(rule_line.endswith("(%s)" % expect), rule_line)

    def test_OV_03_the_station_name_and_the_rule_values_of_the_overlay_are_the_same_station(self):
        s, t, f = self.waiting_with_rules()
        o = s.o
        lines = self.overlay_lines(s)
        rule_line = [x for x in lines if x.startswith("[SCORING RULES]")][0]
        basic = [x for x in lines if x.startswith("基本制動:")][0]
        self.assertIn(s.sl[o.bve_tgt_idx]["name"], rule_line)
        self.assertIn("3段 / 3段", basic, "the basic-braking rule is the one of the section of B (the raw target), not the '2段' section of A")
        self.assertIn("初動: ON①", basic)
        self.assertEqual((o.active_next_sta_name, o.active_rule_basic_apply, o.active_rule_init_apply), (s.sl[o.bve_tgt_idx]["name"], "3段", "ON①"))

    def test_OV_04_the_overlay_does_not_change_with_the_hold_it_is_the_same_before_and_during(self):
        s, t, f = self.waiting_with_rules()
        o = s.o
        during = [x for x in self.overlay_lines(s) if x.startswith(("[SCORING RULES]", "基本制動:"))]
        o.turnback_machine.discard_all()                                                 # the hold is gone (the chain is dropped); the raw target and the rule values are the same
        s.step(2, bve_speed=2.0)
        after = [x for x in self.overlay_lines(s) if x.startswith(("[SCORING RULES]", "基本制動:"))]
        self.assertEqual(during, after)

    def test_OV_05_the_overlay_code_reads_only_the_scoring_state(self):
        import hud_ui
        source = inspect.getsource(hud_ui.draw_hud)
        for banned in ("hud_target", "_hud_rules_station_held", "turnback", "held_station", "_hud_machine_target"):
            self.assertNotIn(banned, source.split("# ★ F8デバッグ情報の生成")[0], banned)
        self.assertIn("getattr(self, 'active_next_sta_name', '---')", source)
        self.assertIn("getattr(self, 'active_next_sta_timing', False)", source)

    def test_OV_06_the_ordinary_hud_rows_are_a_while_the_overlay_is_raw(self):
        s, t, f = self.waiting_with_rules()
        o = s.o
        h = self.hud(s)
        self.assertEqual((h.next_loc, h.is_pass), (self.P.A_MARK, 0))
        self.assertEqual(o.bve_next_loc, s.sl[2]["location"])
        self.assertEqual(o.hud_target_next_loc, self.P.A_MARK)
        self.assertIn(s.sl[2]["name"], [x for x in self.overlay_lines(s) if x.startswith("[SCORING RULES]")][0])


if __name__ == "__main__":
    unittest.main()
