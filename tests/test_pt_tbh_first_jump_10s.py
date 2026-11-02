"""Stage TB-H Stage 5b: the FIRST Jump of a pseudo-turnback A is requested 10.0 s after the arrival (Owner contract after the C-06 live run, 2026-11-02). JM-01 .. JM-26.

  first window (an arrival):  0-5 s   with arrival result popups (basic braking achieved / 0 cm stop): they are shown for their normal 5.0 s (the old exception of 3.0 s is gone) and NO guidance;
                                        without them: NO pseudo-turnback display at all
                              5-10 s  the guidance (white, black outline) the guidance line;  at 10.0 s: ONE official Jump
  cancellation:               speed != 0 from the arrival tick on (0-5 s and 5-10 s alike): the Jump is cancelled, the guidance is removed at once, the arrival result popups end (the existing popup list is
                              filtered), the red two-line warning (5.0 s), the RESTOP_WAIT state
  after a re-stop (UNCHANGED, Stage 4): two-line white guidance at once, ONE Jump 5.0 s after the re-stop - never 10.0 s
RED = fails on the baseline fe8c26d (the old contract: 5.0 s, special popups 3.0 s); GUARD = already true and must stay true.
The product is driven through the REAL update_physics_and_scoring (tests/pt_scene.py, tests/tbg_c01_rig.py)."""
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

G1 = "発車位置へ移動します。"
G2 = "列車を動かさないでください。"
W1 = "発車位置への移動がキャンセルされました。"
W2 = "許容範囲内に再度列車を停止させてください。"
FIRST_MS = 10000


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbh-jm-")
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
        cls.app = QApplication.instance() or QApplication(["tbh-jm"])
        import config
        import main
        import scoring_logic
        import tbg_c01_rig
        import pt_scene
        import pseudo_turnback_machine
        cls.cfg, cls.main, cls.S, cls.R, cls.P, cls.M = config, main, scoring_logic, tbg_c01_rig, pt_scene, pseudo_turnback_machine

    # ---- scenes ----------------------------------------------------------------------------------------------------------------------------------
    def arrived(self, braking="plain", error=0.3):
        """The arrival at A by the door-open edge (the real evaluate_arrival path). braking 'stepwise' = the basic braking succeeds (a special popup), error 0.0 = the 0 cm stop (a special popup)."""
        s = self.P.Scene(self)
        s.sent = []
        s.o.send_jump_command = s.sent.append
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 4
        o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        o.bve_next_time = self.P.T0 + 90000
        s.approach(braking)
        s.stop_at(error)
        t = s.open_door()
        return s, t

    def flow(self):
        f = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        f.to_arrival_at_a()
        f.scene.sent = f.sent
        return f

    # ---- scripted motion (BVE time; the brake is released while moving) --------------------------------------------------------------------------------
    def tick_to(self, s, abs_ms, **fields):
        s.tick(advance_ms=abs_ms - s.o.bve_time_ms, **fields)

    def move(self, s, abs_ms, dist=10.0, speed=2.0, **extra):
        extra.setdefault("bve_door", 0)
        self.tick_to(s, abs_ms, bve_speed=speed, bve_location=self.P.A_MARK - 0.3 + dist, bve_brk_notch=0, **extra)

    def halt(self, s, abs_ms, offset=-1.0, **extra):
        self.tick_to(s, abs_ms, bve_speed=0.0, bve_location=self.P.A_MARK + offset, **extra)

    # ---- observations ----------------------------------------------------------------------------------------------------------------------------
    def texts(self, s, texts):
        return [p for p in s.o.popups if p["text"] in texts]

    def guide(self, s):
        return self.texts(s, (G1, G2))

    def warn(self, s):
        return self.texts(s, (W1, W2))

    def specials(self, s):
        return [p for p in s.o.popups if self.S.is_arrival_special_popup(p)]

    def sent(self, s):
        return list(s.sent)

    def state(self, s):
        return s.machine.state


# ==============================================================================================================================================
# JM-01 .. JM-08  the first window
# ==============================================================================================================================================
class A_FirstWindow(Base):
    def test_JM_01_RED_with_an_arrival_result_the_result_popups_are_shown_for_their_normal_five_seconds(self):
        s, t = self.arrived("stepwise", 0.3)
        sp = self.specials(s)
        self.assertEqual([p["category"] for p in sp], ["基本制動"], "the basic braking achievement is the arrival result")
        self.assertEqual(sp[0]["expire_time"], t / 1000.0 + 5.0, "RED on the baseline: the special popup is cut to 3.0 s")
        self.tick_to(s, t + 4999)
        self.assertEqual(len(self.specials(s)), 1, "still shown 0.001 s before 5.0 s")
        self.tick_to(s, t + 5000)
        self.assertEqual(self.specials(s), [], "gone at 5.0 s, like every other popup")

    def test_JM_02_RED_the_result_popups_are_not_shortened_to_three_seconds(self):
        for braking, error, category in (("stepwise", 0.3, "基本制動"), ("plain", 0.0, "ボーナス"), ("stepwise", 0.0, None)):
            with self.subTest(braking=braking, error=error):
                s, t = self.arrived(braking, error)
                sp = self.specials(s)
                self.assertTrue(sp, "a result popup exists")
                for p in sp:
                    self.assertEqual(p["expire_time"], t / 1000.0 + 5.0, "RED on the baseline: 3.0 s (two result popups share ONE 3.0 s there)")
                self.tick_to(s, t + 3000)
                self.assertEqual(len(self.specials(s)), len(sp), "RED on the baseline: they are gone at 3.0 s")
                self.assertFalse(hasattr(self.S, "TURNBACK_SPECIAL_SECONDS"), "RED on the baseline: the exceptional 3.0 s is a named contract of the display")

    def test_JM_03_RED_with_an_arrival_result_no_guidance_in_the_first_five_seconds(self):
        s, t = self.arrived("stepwise", 0.3)
        for off in (0, 1, 1000, 2999, 3000, 3001, 4000, 4999):
            if off:
                self.tick_to(s, t + off)
            self.assertEqual(self.guide(s), [], "RED on the baseline at +%d ms: the guidance runs from 3.0 s" % off)
        self.assertEqual(len(self.specials(s)), 1, "the result popup owns 0-5 s")

    def test_JM_04_RED_with_an_arrival_result_the_guidance_is_shown_from_five_to_ten_seconds(self):
        s, t = self.arrived("stepwise", 0.3)
        self.tick_to(s, t + 5000)
        rows = self.guide(s)
        self.assertEqual([p["text"] for p in rows], [G1], "ONE line at the first window")
        self.assertEqual((rows[0]["color"], rows[0]["type"], rows[0]["expire_time"]), (self.cfg.COLOR_WHITE, "big", t / 1000.0 + 10.0))
        self.assertEqual(self.specials(s), [], "the result popup is over: only the guidance")
        self.tick_to(s, t + 9999)
        self.assertEqual([p["text"] for p in self.guide(s)], [G1])
        self.assertEqual(self.sent(s), [], "the Jump is not before 10.0 s")
        self.tick_to(s, t + 10000)
        self.assertEqual(self.guide(s), [], "the guidance ends where the Jump is requested")

    def test_JM_05_RED_without_an_arrival_result_nothing_of_the_pseudo_turnback_is_shown_in_the_first_five_seconds(self):
        s, t = self.arrived("plain", 0.3)
        self.assertEqual(self.specials(s), [], "no arrival result popup (no basic braking achieved, no 0 cm stop)")
        for off in (0, 1, 1000, 2500, 4999):
            if off:
                self.tick_to(s, t + off)
            self.assertEqual(self.guide(s), [], "RED on the baseline at +%d ms: the guidance fills the first five seconds" % off)
            self.assertEqual(self.warn(s), [])
        self.assertIsNone(s.machine.display_state(t + 2500), "no display state: the quiet five seconds")

    def test_JM_06_RED_without_an_arrival_result_the_guidance_is_shown_from_five_to_ten_seconds(self):
        s, t = self.arrived("plain", 0.3)
        self.tick_to(s, t + 4999)
        self.assertEqual(self.guide(s), [])
        self.tick_to(s, t + 5000)
        rows = self.guide(s)
        self.assertEqual([p["text"] for p in rows], [G1])
        self.assertEqual(rows[0]["expire_time"], t / 1000.0 + 10.0, "RED on the baseline: it would have ended at +5.0 s")
        self.tick_to(s, t + 9999)
        self.assertEqual(len(self.guide(s)), 1)
        self.assertEqual(s.machine.display_state(t + 7000), self.M.DISPLAY_GUIDANCE)

    def test_JM_07_RED_no_jump_before_ten_seconds(self):
        for braking, error in (("plain", 0.3), ("stepwise", 0.3)):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, error)
                for off in (1000, 4999, 5000, 5001, 7000, 9000, 9999):
                    self.tick_to(s, t + off)
                    self.assertEqual(self.sent(s), [], "RED on the baseline at +%d ms: the Jump left at +5.0 s" % off)
                self.assertEqual(self.state(s), self.M.ARMED)

    def test_JM_08_RED_exactly_one_jump_at_ten_seconds(self):
        for braking, error in (("plain", 0.3), ("stepwise", 0.3), ("plain", 0.0)):
            with self.subTest(braking=braking, error=error):
                s, t = self.arrived(braking, error)
                self.tick_to(s, t + 9999)
                self.assertEqual(self.sent(s), [])
                self.tick_to(s, t + 10000)
                self.assertEqual(len(self.sent(s)), 1)
                self.assertEqual(self.state(s), self.M.REQUESTED)
                for k in range(1, 200):
                    self.tick_to(s, t + 10000 + 16 * k)
                self.assertEqual(len(self.sent(s)), 1, "one Jump however long the train stands")


# ==============================================================================================================================================
# JM-09 .. JM-13  the cancellation from the arrival tick on
# ==============================================================================================================================================
class B_Cancellation(Base):
    def test_JM_09_speed_not_zero_in_the_first_five_seconds_cancels_the_jump(self):
        for braking in ("plain", "stepwise"):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, 0.3)
                self.move(s, t + 2000)
                self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))
                for k in range(1, 60):
                    self.tick_to(s, t + 2000 + 500 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 40.0)
                self.assertEqual(self.sent(s), [], "no Jump, however long the train stands outside the author range")
                self.assertEqual(self.guide(s), [], "the guidance never appeared")

    def test_JM_10_speed_not_zero_between_five_and_ten_seconds_cancels_the_jump_and_removes_the_guidance_at_once(self):
        for braking in ("plain", "stepwise"):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, 0.3)
                self.tick_to(s, t + 6000)
                self.assertEqual(len(self.guide(s)), 1, "the guidance is on")
                self.move(s, t + 7000)
                self.assertEqual(self.guide(s), [], "removed at the tick that sees the movement")
                self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))
                for k in range(1, 60):
                    self.tick_to(s, t + 7000 + 500 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 40.0)
                self.assertEqual(self.sent(s), [])

    def test_JM_10b_speed_not_zero_exactly_at_the_request_tick_cancels_instead_of_requesting(self):
        s, t = self.arrived("plain", 0.3)
        self.tick_to(s, t + 9999)
        self.move(s, t + 10000)
        self.assertEqual(self.sent(s), [], "the movement is judged before the time")
        self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))

    def test_JM_11_a_cancellation_in_the_first_five_seconds_shows_the_red_two_line_warning(self):
        s, t = self.arrived("plain", 0.3)
        self.move(s, t + 2000)
        rows = self.warn(s)
        self.assertEqual([p["text"] for p in rows], [W1, W2])
        for p in rows:
            self.assertEqual((p["color"], p["type"], p["expire_time"]), (self.cfg.COLOR_B_EMG, "big", (t + 2000) / 1000.0 + 5.0))

    def test_JM_12_a_cancellation_between_five_and_ten_seconds_shows_the_red_two_line_warning(self):
        s, t = self.arrived("plain", 0.3)
        self.tick_to(s, t + 6000)
        self.move(s, t + 7000)
        rows = self.warn(s)
        self.assertEqual([p["text"] for p in rows], [W1, W2])
        for p in rows:
            self.assertEqual((p["color"], p["type"], p["expire_time"]), (self.cfg.COLOR_B_EMG, "big", (t + 7000) / 1000.0 + 5.0))
        self.tick_to(s, t + 7000 + 5000, bve_speed=2.0)
        self.assertEqual(self.warn(s), [], "the warning ends after 5.0 s")

    def test_JM_13_RED_a_cancellation_while_the_arrival_result_popups_are_shown_ends_them_through_the_existing_list_and_keeps_the_ownership_whole(self):
        s, t = self.arrived("stepwise", 0.0)
        o = s.o
        self.assertEqual(len(self.specials(s)), 2, "the 0 cm stop and the basic braking achievement")
        pos_before = [(p["text"], p["expire_time"]) for p in o.popups if p["type"] == "pos"]
        score_before, details_before = o.score, dict(o.score_details)
        self.move(s, t + 1000)
        self.assertEqual(self.specials(s), [], "RED on the baseline: the result popups would run on beside the red warning")
        self.assertEqual([p["text"] for p in self.warn(s)], [W1, W2])
        self.assertEqual(self.guide(s), [])
        self.assertEqual([(p["text"], p["expire_time"]) for p in o.popups if p["type"] == "pos"], pos_before, "the score lines ('+500' ...) are not touched")
        self.assertEqual((o.score, dict(o.score_details)), (score_before, details_before), "no point is gained or lost by the removal")
        for p in o.popups:
            self.assertTrue({"text", "color", "expire_time", "type", "category"} <= set(p), "every popup is whole: %r" % (p,))
        for k in range(1, 30):
            self.tick_to(s, t + 1000 + 400 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 40.0)
        self.assertEqual((self.guide(s), self.sent(s)), ([], []))
        self.assertEqual(len([p for p in o.popups if p["category"] == self.S.TURNBACK_CANCEL_CATEGORY]), 0, "the warning ended after its own 5.0 s")


# ==============================================================================================================================================
# JM-14 .. JM-18  after a re-stop (unchanged) and the single Jump
# ==============================================================================================================================================
class C_AfterReStop(Base):
    def test_JM_14_after_a_re_stop_the_two_line_guidance_is_shown_at_once_for_five_seconds(self):
        for braking in ("plain", "stepwise"):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, 0.3)
                self.move(s, t + 2000)
                self.halt(s, t + 3000, offset=-1.0)
                rows = self.guide(s)
                self.assertEqual([p["text"] for p in rows], [G1, G2])
                for p in rows:
                    self.assertEqual((p["color"], p["type"], p["expire_time"]), (self.cfg.COLOR_WHITE, "big", (t + 3000) / 1000.0 + 5.0), "the guidance of a re-stop window lasts 5.0 s from the re-stop")
                self.assertEqual(self.warn(s), [])

    def test_JM_15_the_jump_after_a_re_stop_is_five_seconds_after_the_re_stop_never_ten(self):
        for braking in ("plain", "stepwise"):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, 0.3)
                self.move(s, t + 2000)
                self.halt(s, t + 3000, offset=-1.0)
                self.tick_to(s, t + 3000 + 4999)
                self.assertEqual(self.sent(s), [])
                self.tick_to(s, t + 3000 + 5000)
                self.assertEqual(len(self.sent(s)), 1, "ONE Jump 5.0 s after the re-stop")
                self.assertEqual(self.state(s), self.M.REQUESTED)

    def test_JM_15b_a_re_stop_after_a_late_cancellation_is_also_five_seconds(self):
        s, t = self.arrived("plain", 0.3)
        self.tick_to(s, t + 6000)
        self.move(s, t + 7000)
        self.halt(s, t + 8000, offset=-1.0)
        self.tick_to(s, t + 8000 + 4999)
        self.assertEqual(self.sent(s), [])
        self.tick_to(s, t + 8000 + 5000)
        self.assertEqual(len(self.sent(s)), 1)

    def test_JM_16_the_re_cancellation_contract_is_kept(self):
        s, t = self.arrived("plain", 0.3)
        self.move(s, t + 2000)
        self.halt(s, t + 3000, offset=-1.0)
        self.move(s, t + 5000)
        self.assertEqual(self.guide(s), [], "removed at once")
        self.assertEqual([p["text"] for p in self.warn(s)], [W1, W2])
        self.assertEqual((s.machine.cancel_count, s.machine.restop_count), (2, 1))
        self.assertEqual(self.sent(s), [])
        self.halt(s, t + 6000, offset=-2.0)
        self.assertEqual(s.machine.restop_count, 2)
        self.tick_to(s, t + 6000 + 4999)
        self.assertEqual(self.sent(s), [])
        self.tick_to(s, t + 6000 + 5000)
        self.assertEqual(len(self.sent(s)), 1, "exactly ONE Jump after two cancellations")

    def test_JM_17_a_is_never_scored_again(self):
        s, t = self.arrived("stepwise", 0.3)
        o = s.o
        keys = ("score", "score_details", "has_scored_stop_this_station", "has_scored_time_this_station")
        def snap():
            return {k: (dict(getattr(o, k)) if isinstance(getattr(o, k), dict) else getattr(o, k)) for k in keys}, len(o.save_data), s.machine.arrival_ms
        before = snap()
        self.move(s, t + 1500)
        self.halt(s, t + 2500, offset=-1.0)
        self.move(s, t + 4000)
        self.halt(s, t + 5000, offset=-1.5)
        self.tick_to(s, t + 5000 + 5000)
        self.assertEqual(len(self.sent(s)), 1)
        after = snap()
        self.assertEqual(after[0]["score"], before[0]["score"])
        self.assertEqual(after[0]["score_details"], before[0]["score_details"])
        self.assertEqual(after[1:], before[1:], "no checkpoint, the arrival time is the first one")

    def test_JM_18_no_jump_is_ever_sent_twice(self):
        s, t = self.arrived("plain", 0.3)
        self.tick_to(s, t + 10000)
        self.assertEqual(len(self.sent(s)), 1)
        for k in range(1, 600):
            self.tick_to(s, t + 10000 + 20 * k, bve_speed=0.0)
        self.assertEqual(len(self.sent(s)), 1)
        self.assertEqual(len(s.machine.issued), 1)


# ==============================================================================================================================================
# JM-19 .. JM-22  contracts that must stay true
# ==============================================================================================================================================
class D_ContractsKept(Base):
    def test_JM_19_the_c01_root_fix_holds_with_the_ten_second_jump_the_landing_at_b_is_no_ordinary_stop(self):
        f = self.flow()
        s, o = f.scene, f.o
        f.to_request()
        self.assertEqual(len(f.sent), 1, "the Jump of the helper is the 10.0 s Jump")
        score_before = o.score
        f.land()
        f.after(3)
        self.assertEqual(o.score, score_before, "RED/GUARD (C-01 Root Fix 161c037): the landing at B scores nothing")
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(f.fail_reasons(), [])
        self.assertEqual([cp.get("origin") for cp in o.save_data if cp.get("station_index") == 2], ["turnback"], "ONE pseudo-turnback B checkpoint")

    def test_JM_20_pair_b_stays_untimed_and_out_of_the_theoretical_score(self):
        f = self.flow()
        o = f.o
        f.to_request()
        f.land()
        f.after(3)
        self.assertEqual(o.untimed_reason(2), "UNTIMED_TURNBACK_B")
        self.assertFalse(o.is_station_timing(2))

    def test_JM_21_RETRY_AND_22_NEXT_STATION_ARE_COVERED_BY_THE_EXISTING_MODULES_WHICH_THE_NEW_HELPER_FEEDS(self):
        """JM-21 (Retry to B: no +300 after the Retry, RB_3 / RB_5 / RB_7 / RB_9) and JM-22 (B -> next station is ordinary scoring, RB_6 / RL_6) are the tests of test_pt_tbh_pairb_contract.C_RetryToB and
        test_pt_tbh_retry_state. They run on the same helper (pt_scene.run_to_request, now arrival + 10.0 s); this test only proves that the helper IS the 10.0 s helper."""
        import inspect as _i
        body = _i.getsource(self.P.Scene.run_to_request)
        self.assertIn("10000", body, "RED on the baseline: the helper still ticks to arrival + 5000")
        self.assertNotIn("t_a + 5000", body)


# ==============================================================================================================================================
# JM-23 .. JM-26  lifecycle and the common path
# ==============================================================================================================================================
class E_Lifecycle(Base):
    def waiting(self, offset=7000):
        s, t = self.arrived("plain", 0.3)
        self.tick_to(s, t + offset)
        self.assertEqual(len(self.guide(s)), 1, "the first window's guidance is on")
        return s, t

    def quiet(self, s, since):
        for k in range(1, 40):
            self.tick_to(s, since + 500 * k, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
        self.assertEqual(self.sent(s), [])

    def test_JM_23_f5_drops_the_first_window_state_and_its_guidance(self):
        s, t = self.waiting()
        o = s.o
        o.is_scoring_mode = False
        o.current_scenario_id = o.current_scenario_id + 1
        s.step(2)
        m = s.machine
        self.assertEqual((m.state, m.pair, m.fixed), (self.M.IDLE, None, None))
        self.assertEqual(self.guide(s) + self.warn(s), [], "no popup of the old run")
        self.assertEqual(self.sent(s), [])
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE, "the old state does not come back")

    def test_JM_24_retry_start_drops_the_first_window_state(self):
        s, t = self.waiting()
        res = self.main.execute_retry(s.o, 0, False)
        self.assertTrue(res.accepted, res)
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.assertEqual(len(self.sent(s)), 1, "the Retry's own Jump only")
        o = s.o
        o.is_official_jumping = False
        o.jump_expectation = None
        for k in range(1, 60):
            self.tick_to(s, o.bve_time_ms + 500, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
        self.assertEqual(len(self.sent(s)), 1, "no turnback Jump from a dropped chain")

    def test_JM_25_a_generation_change_drops_the_first_window_state(self):
        s, t = self.waiting()
        s.o.current_scenario_id = s.o.current_scenario_id + 1
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.quiet(s, s.o.bve_time_ms)

    def test_JM_25b_the_wait_after_a_cancellation_is_dropped_the_same_way(self):
        s, t = self.arrived("plain", 0.3)
        self.move(s, t + 2000)
        s.o.current_scenario_id = s.o.current_scenario_id + 1
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.quiet(s, s.o.bve_time_ms)

    def test_JM_26_current_and_legacy_share_the_python_path_and_no_decision_reads_a_door_lamp_or_signal(self):
        def run(managed, door):
            s, t = self.arrived("stepwise", 0.3)
            if managed:
                s.o.jump_client = object()
                s.o.jump_group_available = lambda: True
            self.tick_to(s, t + 6000, bve_door=door)
            self.move(s, t + 7000, bve_door=door)
            self.halt(s, t + 8000, offset=-1.0, bve_door=door)
            self.tick_to(s, t + 13000, bve_door=door)
            return (s.machine.state, len(s.sent), tuple(sorted((p["text"], p["color"]) for p in s.o.popups)))
        self.assertEqual(run(False, 0), run(True, 0), "Current (managed) and Legacy: the same decisions and the same popups")
        self.assertEqual(run(False, 0), run(False, 1), "A closed and A open: the same decisions (the door is no input)")
        self.assertEqual(run(False, 0)[:2], (self.M.REQUESTED, 1))
        for module, names in ((self.M, ("TurnbackMachine.tick", "TurnbackMachine.on_arrival", "TurnbackMachine.display_phase", "TurnbackMachine.display_state")), (self.S, ("turnback_display_update", "turnback_arrival_scored", "turnback_cancel_show", "turnback_drive"))):
            for name in names:
                with self.subTest(function=name):
                    target = module
                    for part in name.split("."):
                        target = getattr(target, part)
                    tree = ast.parse(inspect.getsource(target).lstrip() if "." not in name else "class _C:\n" + inspect.getsource(target))
                    words = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Name):
                            words.add(node.id)
                        elif isinstance(node, ast.Attribute):
                            words.add(node.attr)
                        elif isinstance(node, ast.arg):
                            words.add(node.arg)
                    bad = sorted(w for w in words if any(k in w.lower() for k in ("door", "lamp", "indicator", "signal")))
                    self.assertEqual(bad, [], bad)
                    body = inspect.getsource(target)
                    self.assertNotRegex(body, r"jump_client|dataplane_strict|managed|legacy", "no host-specific branch in " + name)


# ==============================================================================================================================================
# the machine (pure)
# ==============================================================================================================================================
class F_Machine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pseudo_turnback_machine as M
        cls.M = M

    def test_JM_27_the_two_constants_are_separate_ten_for_the_first_window_five_for_a_re_stop(self):
        M = self.M
        self.assertEqual(getattr(M, "FIRST_REQUEST_AFTER_MS", None), 10000, "RED on the baseline: no such constant")
        self.assertEqual(M.REQUEST_AFTER_MS, 5000, "the re-stop window stays 5.0 s")
        self.assertEqual(getattr(M, "FIRST_GUIDE_FROM_MS", None), 5000, "RED on the baseline: no such constant")
        self.assertFalse(hasattr(M, "SPECIAL_DISPLAY_MS"), "RED on the baseline: the exceptional 3.0 s is gone")


# ==============================================================================================================================================
# the popup ownership audit (reachability): the 'big' popups are a CLOSED set
# ==============================================================================================================================================
class G_PopupOwnership(Base):
    def test_JM_28_the_big_popup_categories_are_a_closed_set_so_no_other_popup_can_share_the_guidance_of_the_first_window(self):
        """The guidance and the cancellation warning are 'big' popups. The 'big' popups that the product can add are exactly: the arrival results (basic braking achieved / 0 cm stop, written by evaluate_arrival at the arrival tick and
        shown for their normal 5.0 s), the illegal-Jump warning (force, an abort: the chain is dropped), the end message (the scoring is over) and the two chain categories. Every score line of the other rules is a 'neg' or a 'pos' popup (another stack).
        A new 'big' category would show up here and need an Owner decision about the display ownership."""
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "add_score_popup" and len(node.args) >= 6:
                ptype, category = node.args[4], node.args[5]
                if isinstance(ptype, ast.Constant) and ptype.value == "big":
                    found.add(category.value if isinstance(category, ast.Constant) else getattr(self.S, category.id))
        self.assertEqual(found, {"基本制動", "ボーナス", "警告", "終了", self.S.TURNBACK_GUIDANCE_CATEGORY, self.S.TURNBACK_CANCEL_CATEGORY})

    def test_JM_29_the_arrival_results_are_over_when_the_guidance_starts_so_the_two_never_share_the_big_stack(self):
        for braking, error in (("stepwise", 0.0), ("stepwise", 0.3), ("plain", 0.0)):
            with self.subTest(braking=braking, error=error):
                s, t = self.arrived(braking, error)
                self.assertTrue(self.specials(s))
                last_result = None
                first_guide = None
                for off in range(0, 10001, 100):
                    self.tick_to(s, t + off)
                    if self.specials(s):
                        last_result = off
                    if self.guide(s) and first_guide is None:
                        first_guide = off
                    self.assertFalse(self.specials(s) and self.guide(s), "never both at +%d ms" % off)
                self.assertLess(last_result, 5000)
                self.assertEqual(first_guide, 5000)

if __name__ == "__main__":
    unittest.main()
