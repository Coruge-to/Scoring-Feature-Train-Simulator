"""Stage TB-H Stage 3 (RED / GUARD): the A RE-STOP WAIT of the pseudo-turnback (Owner ruling R7 = plan 3, C-01 retest Close 2026-11-01; contract text in stage3-a-restop-contract.md).

  1  first A arrival: jump_earliest_time = arrival + 5.0 s, the guidance 'hassha-ichi e ido shimasu.' for 5.0 s; speed == 0 for the whole time -> ONE official Jump at +5.0 s
  2  speed != 0 while waiting (first or later wait): the guidance is removed AT ONCE, the Jump is cancelled, the RE-STOP WAIT state begins, a RED two-line warning is shown for 5.0 s;
     the warning going out does NOT end the state (no Jump in it)
  3  re-stop = speed == 0 AND inside the author-defined stop range of the SAME A (-margin_f .. margin_b of the arrival; never the 330 m scoring range): the warning is removed at once,
     the two-line guidance is shown and a NEW 5.0 s starts; speed == 0 for all of it -> ONE Jump (the 5.0 s is never skipped after a re-stop)
  4  moving again: the same cancellation, any number of times
  5  speed == 0 outside the range: nothing (no guidance, no timer, no Jump); the wait goes on
  6  A is never scored again (time / stop position / basic braking / history / checkpoint / score / arrival time)
  7  the state is dropped by: Jump success, scoring end / abort, Retry, F5, generation, RunPairSet, another station's arrival, arrival at B by driving, chain expiry
  8  arrival at B by driving: no Jump to B afterwards, the chain is closed as a FAILURE, B is not scored as an ordinary arrival, the scoring is aborted (fail-closed, reason pseudo-turnback-self-drive-b)

Door state, the indicator lamp and signalFlag are NOT inputs of any decision (A open and A closed decide the same). RED = fails on the baseline c66445e; GUARD = already true on the baseline and must stay true.
The product is driven through the REAL update_physics_and_scoring (tests/pt_scene.py, tests/tbg_c01_rig.py); only the seams of the rig are replaced."""
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
OLD_G1 = "次の発車位置へ移動します。"
SELF_DRIVE_B_REASON = "pseudo-turnback-self-drive-b"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbh-arestop-")
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
        cls.app = QApplication.instance() or QApplication(["tbh-arestop"])
        import config
        import main
        import scoring_logic
        import tbg_c01_rig
        import pt_scene
        import pseudo_turnback_machine
        cls.cfg, cls.main, cls.S, cls.R, cls.P, cls.M = config, main, scoring_logic, tbg_c01_rig, pt_scene, pseudo_turnback_machine

    # ---- scenes ----------------------------------------------------------------------------------------------------------------------------------
    def flow(self, operational=False):
        f = self.R.Flow(self, operational=operational, advance_arr=True, order="complete_first")
        f.to_arrival_at_a()
        f.scene.sent = f.sent
        return f

    def scene(self, **kw):
        """A scene with the arrival at A done (door-edge arrival) and the sends recorded."""
        f = self.flow(**kw)
        return f.scene, f.scene.machine.arrival_ms, f

    # ---- scripted motion (every tick is BVE time; the brake is released while moving: a held notch 8 would be an emergency-brake penalty) ---------------
    def tick_to(self, s, abs_ms, **fields):
        s.tick(advance_ms=abs_ms - s.o.bve_time_ms, **fields)

    def move(self, s, abs_ms, dist=10.0, speed=2.0, **extra):
        # the door of the moving train is closed unless a test says otherwise: moving with an OPEN door is the existing roll penalty (-100000, unrelated to this contract)
        extra.setdefault("bve_door", 0)
        self.tick_to(s, abs_ms, bve_speed=speed, bve_location=self.P.A_MARK - 0.3 + dist, bve_brk_notch=0, **extra)

    def halt(self, s, abs_ms, offset=-1.0, **extra):
        """Speed 0 at `offset` metres from the mark (the train head - mark; inside the range for |offset| <= 5 with the rig margins 5 m)."""
        self.tick_to(s, abs_ms, bve_speed=0.0, bve_location=self.P.A_MARK + offset, **extra)

    # ---- observations ----------------------------------------------------------------------------------------------------------------------------
    def popup_rows(self, s, texts):
        return [p for p in s.o.popups if p["text"] in texts]

    def guide_texts(self, s):
        return [p["text"] for p in s.o.popups if p["text"] in (G1, G2, OLD_G1)]

    def warn_rows(self, s):
        return self.popup_rows(s, (W1, W2))

    def jumps(self, f):
        return list(f.sent)

    def state(self, s):
        return s.machine.state


# ==============================================================================================================================================
# AR-01 .. AR-12  the wait, the cancellation, the re-stop
# ==============================================================================================================================================
class A_WaitAndCancel(Base):
    def test_AR_01_first_arrival_five_seconds_of_stopped_train_one_jump_and_the_exact_guidance_line(self):
        s, t, f = self.scene()
        self.assertEqual([p["text"] for p in self.popup_rows(s, (G1, OLD_G1))], [G1], "RED on the baseline: the guidance line is still the old 'next departure position' text")
        row = self.popup_rows(s, (G1,))[0]
        self.assertEqual((row["color"], row["type"], row["expire_time"]), (self.cfg.COLOR_WHITE, "big", t / 1000.0 + 5.0))
        self.assertEqual(self.guide_texts(s), [G1], "exactly ONE line (no second line at the first arrival)")
        self.tick_to(s, t + 4999)
        self.assertEqual(self.jumps(f), [])
        self.tick_to(s, t + 5000)
        self.assertEqual(len(self.jumps(f)), 1)
        self.assertEqual(self.state(s), self.M.REQUESTED)
        for k in range(1, 200):
            self.tick_to(s, t + 5000 + 16 * k)
        self.assertEqual(len(self.jumps(f)), 1, "one Jump however long the train stands")

    def test_AR_02_speed_not_zero_inside_the_first_wait_cancels_the_jump(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        for k in range(1, 40):
            self.tick_to(s, t + 2000 + 500 * k, bve_speed=0.0 if k % 2 else 1.5, bve_location=self.P.A_MARK + (50.0 if k % 2 else 40.0), bve_brk_notch=0)
        self.assertEqual(self.jumps(f), [], "RED on the baseline: the Jump is requested at arrival + 5.0 s whatever the train does")
        self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))

    def test_AR_03_the_first_guidance_is_removed_at_the_tick_that_sees_the_movement(self):
        s, t, f = self.scene()
        self.assertEqual(len(self.guide_texts(s)), 1, "the guidance is on before the movement")
        self.move(s, t + 2000)
        self.assertEqual(self.guide_texts(s), [], "RED on the baseline: the guidance stays on until arrival + 5.0 s")

    def test_AR_04_a_red_two_line_warning_for_five_seconds_in_the_colour_of_the_illegal_jump_warning(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        rows = self.warn_rows(s)
        self.assertEqual([p["text"] for p in rows], [W1, W2], "RED on the baseline: no warning")
        for p in rows:
            self.assertEqual((p["color"], p["type"], p["expire_time"]), (self.cfg.COLOR_B_EMG, "big", (t + 2000) / 1000.0 + 5.0))
        self.tick_to(s, t + 2000 + 4999, bve_speed=2.0)
        self.assertEqual(len(self.warn_rows(s)), 2)
        self.tick_to(s, t + 2000 + 5000, bve_speed=2.0)
        self.assertEqual(self.warn_rows(s), [], "the warning ends after 5.0 s")

    def test_AR_05_the_warning_going_out_does_not_end_the_wait_state_and_nothing_is_sent_in_it(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.tick_to(s, t + 2000 + 6000, bve_speed=0.0, bve_location=self.P.A_MARK + 40.0)
        self.assertEqual(self.warn_rows(s), [])
        self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"), "RED on the baseline: the chain does not stay in a wait state")
        for k in range(1, 60):
            self.tick_to(s, t + 8000 + 1000 * k, bve_speed=0.0, bve_location=self.P.A_MARK + 40.0)
        self.assertEqual(self.jumps(f), [])
        self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))

    def test_AR_06_speed_zero_outside_the_author_range_is_no_re_stop(self):
        for off in (-20.0, 20.0, -5.5, 5.5):
            with self.subTest(offset=off):
                s, t, f = self.scene()
                self.move(s, t + 2000)
                self.tick_to(s, t + 3000, bve_speed=0.0, bve_location=self.P.A_MARK + off)
                for k in range(1, 40):
                    self.tick_to(s, t + 3000 + 500 * k, bve_speed=0.0, bve_location=self.P.A_MARK + off)
                self.assertEqual(self.guide_texts(s), [], "no guidance outside the range")
                self.assertEqual(self.jumps(f), [], "no Jump outside the range, however long the train stands")
                self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"), "RED on the baseline: no wait state")

    def test_AR_07_a_re_stop_inside_the_range_removes_the_warning_at_once(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.assertEqual(len(self.warn_rows(s)), 2)
        self.halt(s, t + 3000, offset=-1.0)
        self.assertEqual(self.warn_rows(s), [], "RED on the baseline: the warning is not part of the product")
        self.assertNotEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))

    def test_AR_08_after_a_re_stop_the_two_line_white_guidance(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.halt(s, t + 3000, offset=-1.0)
        rows = self.popup_rows(s, (G1, G2))
        self.assertEqual([p["text"] for p in rows], [G1, G2], "RED on the baseline")
        for p in rows:
            self.assertEqual((p["color"], p["type"], p["expire_time"]), (self.cfg.COLOR_WHITE, "big", (t + 3000) / 1000.0 + 5.0))

    def test_AR_09_a_re_stop_starts_a_new_five_second_timer(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.halt(s, t + 3000, offset=-1.0)
        m = s.machine
        self.assertEqual(getattr(m, "jump_earliest_ms", None), t + 3000 + 5000, "RED on the baseline: no such time is kept")
        self.assertEqual(m.arrival_ms, t, "the arrival time is never overwritten")
        self.tick_to(s, t + 3000 + 4999)
        self.assertEqual(self.jumps(f), [])
        self.tick_to(s, t + 5000 + 100)          # the OLD request time has passed: still nothing
        self.assertEqual(self.jumps(f), [])

    def test_AR_10_speed_zero_for_five_seconds_after_the_re_stop_one_jump(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.halt(s, t + 3000, offset=-1.0)
        self.tick_to(s, t + 3000 + 4999)
        self.assertEqual(self.jumps(f), [], "RED on the baseline: the Jump left at the OLD time (arrival + 5.0 s), before the new five seconds were over")
        self.tick_to(s, t + 3000 + 5000)
        self.assertEqual(len(self.jumps(f)), 1)
        self.assertEqual(self.state(s), self.M.REQUESTED)

    def test_AR_11_moving_again_during_the_second_wait_cancels_again(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.halt(s, t + 3000, offset=-1.0)
        self.move(s, t + 5000, dist=2.0)
        self.assertEqual(self.guide_texts(s), [], "the second guidance is removed at once")
        self.assertEqual([p["text"] for p in self.warn_rows(s)], [W1, W2], "RED on the baseline")
        self.tick_to(s, t + 3000 + 5000 + 100, bve_speed=0.0, bve_location=self.P.A_MARK + 30.0)
        self.assertEqual(self.jumps(f), [], "the old timer of the second wait was cancelled too")

    def test_AR_12_any_number_of_cancellations_end_in_exactly_one_jump(self):
        s, t, f = self.scene()
        now = t
        for cycle in range(5):
            now += 1500
            self.move(s, now, dist=3.0 + cycle)
            now += 1000
            self.halt(s, now, offset=-1.0)
        self.assertEqual(self.jumps(f), [], "RED on the baseline")
        self.tick_to(s, now + 5000)
        self.assertEqual(len(self.jumps(f)), 1)
        for k in range(1, 100):
            self.tick_to(s, now + 5000 + 100 * k)
        self.assertEqual(len(self.jumps(f)), 1)


# ==============================================================================================================================================
# AR-13 .. AR-15  A is never scored again
# ==============================================================================================================================================
class B_NoRescore(Base):
    def spies(self, f):
        S = self.S
        calls = {"time": 0, "stop": 0, "save": 0, "arrival": 0}
        for key, name in (("time", "apply_time_score"), ("stop", "apply_stop_score"), ("save", "create_save_data"), ("arrival", "evaluate_arrival")):
            original = getattr(S, name)

            def make(original=original, key=key):
                def wrapper(*a, **k):
                    calls[key] += 1
                    return original(*a, **k)
                return wrapper
            setattr(S, name, make())
            self.addCleanup(setattr, S, name, original)
        return calls

    A_KEYS = ("time", "stop", "base_brake", "bonus")

    def a_part(self, s):
        """The score components that the ARRIVAL at A produces (movement penalties such as the roll of an open-door move are not part of the A arrival)."""
        return tuple(s.o.score_details[k] for k in self.A_KEYS)

    def cycle(self, s, t, cycles=3, door_reopen=False):
        now = t
        for c in range(cycles):
            now += 1500
            if door_reopen:
                self.tick_to(s, now - 200, bve_door=0)
            self.move(s, now, dist=4.0 + c)
            now += 1000
            self.halt(s, now, offset=-1.0)
            if door_reopen:
                now += 300
                self.tick_to(s, now, bve_door=1)
        return now

    def test_AR_13_the_arrival_is_scored_once_for_any_cancel_and_re_stop_cycle(self):
        s, t, f = self.scene()
        before = (self.a_part(s), len(s.o.save_data))
        calls = self.spies(f)
        now = self.cycle(s, t)
        self.assertEqual(self.jumps(f), [], "RED on the baseline: the Jump fired during the first movement (no cycle happened)")
        self.tick_to(s, now + 5000)
        self.assertEqual(len(self.jumps(f)), 1)
        self.assertEqual((self.a_part(s), len(s.o.save_data)), before, "the A components of the score and the history are those of the one arrival")
        self.assertEqual(calls["arrival"], 0, "evaluate_arrival is not run again (nothing re-judged without a door edge)")

    def test_AR_13b_the_door_edges_of_the_cycle_do_not_score_a_again(self):
        s, t, f = self.scene()
        before = (self.a_part(s), len(s.o.save_data))
        self.cycle(s, t, door_reopen=True)
        self.assertEqual(len(self.jumps(f)), 0, "RED on the baseline (the Jump left earlier)")
        self.assertEqual(self.state(s), self.M.ARMED)
        self.assertEqual((self.a_part(s), len(s.o.save_data)), before, "a re-opened door at A is no new arrival score")

    def test_AR_43_the_operational_stop_flow_of_the_c01_run_follows_the_same_contract_without_a_second_a_score(self):
        """The C-01 run had an OPERATIONAL stop at A (the arrival is the stop itself, no door edge): the same cancellation, the same re-stop wait, the same ONE Jump, and A is not scored again."""
        s, t, f = self.scene(operational=True)
        before = (self.a_part(s), len(s.o.save_data), s.o.score_details["time"])
        self.assertEqual(s.machine.state, self.M.ARMED)
        calls = self.spies(f)
        self.move(s, t + 2000)
        self.assertEqual(self.jumps(f), [], "RED on the baseline")
        self.halt(s, t + 3000, offset=-1.0)
        self.tick_to(s, t + 3000 + 4999)
        self.assertEqual(self.jumps(f), [])
        self.tick_to(s, t + 3000 + 5000)
        self.assertEqual(len(self.jumps(f)), 1)
        self.assertEqual((self.a_part(s), len(s.o.save_data), s.o.score_details["time"]), before)
        self.assertEqual((calls["time"], calls["stop"], calls["save"]), (0, 0, 0))

    def test_AR_14_the_operating_time_of_a_is_scored_once(self):
        s, t, f = self.scene()
        details = s.o.score_details["time"]
        self.assertNotEqual(details, 0, "the scene's A is a timing station: the arrival time was scored")
        calls = self.spies(f)
        now = self.cycle(s, t, door_reopen=True)
        self.assertEqual(self.state(s), self.M.ARMED, "RED on the baseline")
        self.assertEqual(calls["time"], 0)
        self.assertEqual(s.o.score_details["time"], details)

    def test_AR_15_stop_position_basic_braking_history_and_checkpoint_are_not_made_again(self):
        s, t, f = self.scene()
        before = dict(s.o.score_details)
        calls = self.spies(f)
        now = self.cycle(s, t, door_reopen=True)
        self.assertEqual(self.jumps(f), [], "RED on the baseline (the Jump left earlier, no cycle happened)")
        self.tick_to(s, now + 5000)
        self.assertEqual(self.state(s), self.M.REQUESTED)
        self.assertEqual(calls["stop"], 0)
        self.assertEqual(calls["save"], 0, "a pair A never has a checkpoint")
        after = dict(s.o.score_details)
        for key in ("stop", "base_brake", "bonus", "time"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(len(s.o.save_data), 1, "the history still holds the start checkpoint only")


# ==============================================================================================================================================
# AR-16 .. AR-21  the state is dropped (lifecycle)
# ==============================================================================================================================================
class C_Lifecycle(Base):
    def waiting(self):
        s, t, f = self.scene()
        self.move(s, t + 2000)
        self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"), "RED on the baseline: no wait state to drop")
        return s, t, f

    def settled_quiet(self, s, f, since, n=1200):
        """After the drop nothing is sent, however the train stands at A afterwards (the conditions of a re-stop and of the old five seconds both hold)."""
        for k in range(1, 40):
            self.tick_to(s, since + 500 * k, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
        self.assertEqual(self.jumps(f), [])

    def test_AR_16_F5_drops_the_wait_state_completely_and_a_new_run_builds_a_new_one(self):
        s, t, f = self.waiting()
        o = s.o
        o.is_scoring_mode = False
        o.current_scenario_id = o.current_scenario_id + 1
        s.step(2)                  # tick 1: the guard drops the chain; tick 2: the display ticks see no chain and take its popups
        m = s.machine
        self.assertEqual((m.state, m.pair, m.fixed, m.landing_watch), (self.M.IDLE, None, None, None))
        self.assertEqual(self.warn_rows(s) + self.popup_rows(s, (G1, G2)), [], "no popup of the old run")
        self.assertEqual(getattr(m, "restop_count", 0), 0)
        # the new run: scoring on again, the section fixed by the start button, a new arrival
        o.is_scoring_mode = True
        o.save_data = [self.P.checkpoint0(s.sl)]
        o.setting_start_idx, o.setting_end_idx = 0, 4
        s.auto_fix = True
        s._fix_key = None
        self.assertEqual(self.jumps(f), [])
        # the old state does not come back: the machine is IDLE until a NEW arrival is judged
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)

    def test_AR_16b_the_pure_machine_f5_drops_every_wait_field(self):
        s, t, f = self.waiting()
        m = s.machine
        acts = m.on_f5()
        self.assertEqual((m.state, m.pair, m.key, m.arrival_ms, getattr(m, "jump_earliest_ms", None), getattr(m, "cancel_count", 0), getattr(m, "restop_count", 0)), (self.M.IDLE, None, None, None, None, 0, 0))
        self.assertEqual(m.issued, set())

    def test_AR_17_retry_start_drops_the_wait_state(self):
        s, t, f = self.waiting()
        res = self.main.execute_retry(s.o, 0, False)
        self.assertTrue(res.accepted, res)
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.assertEqual(self.warn_rows(s), [])
        sent_by_retry = len(self.jumps(f))
        self.assertEqual(sent_by_retry, 1, "the Retry's own Jump only")
        o = s.o
        o.is_official_jumping = False
        o.jump_expectation = None
        for k in range(1, 40):
            self.tick_to(s, o.bve_time_ms + 500, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0)
        self.assertEqual(len(self.jumps(f)), sent_by_retry, "no turnback Jump from a dropped chain")

    def test_AR_18_a_generation_change_drops_the_wait_state(self):
        s, t, f = self.waiting()
        s.o.current_scenario_id = s.o.current_scenario_id + 1
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.settled_quiet(s, f, s.o.bve_time_ms)

    def test_AR_19_a_changed_run_pair_set_drops_the_wait_state(self):
        s, t, f = self.waiting()
        s.machine.fix_section((), s.o.current_scenario_id)       # the fixed section of the Run no longer holds the pair of this chain
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)
        self.settled_quiet(s, f, s.o.bve_time_ms)

    def test_AR_19b_a_new_start_fixes_a_new_section_and_the_old_wait_state_is_gone(self):
        s, t, f = self.waiting()
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 4          # a section that does not cross the pair
        s.fix()
        s.tick(16)
        self.assertEqual(s.machine.state, self.M.IDLE)

    def test_AR_20_the_formal_arrival_at_another_station_drops_the_wait_state_and_the_scoring_goes_on(self):
        s, t, f = self.waiting()
        o = s.o
        c = s.sl[3]
        # the train is driven on to C (index 3): target C, arrival at C by the door edge
        self.tick_to(s, t + 4000, bve_next_loc=c["location"], bve_tgt_idx=3, bve_speed=2.0, bve_location=c["location"] - 100.0, bve_brk_notch=0)
        self.tick_to(s, t + 5000, bve_speed=0.0, bve_location=c["location"] - 0.3, bve_brk_notch=8)
        self.tick_to(s, t + 6000, bve_door=1, bve_arr_idx=3, bve_arr_seq=o.bve_arr_seq + 1)
        self.assertEqual(s.machine.state, self.M.IDLE, "the wait state of A is gone")
        self.assertEqual(self.jumps(f), [])
        self.assertTrue(o.is_scoring_mode, "another station's arrival is no failure: the scoring goes on")

    def test_AR_44_the_arrival_hook_reports_an_abort_only_for_b_and_never_for_a_landing(self):
        """The caller (evaluate_arrival) stops judging the arrival only when the hook answers True: B reached by driving. A itself, another station, a Jump landing (jump_lock / is_official_jumping) and a host without a machine answer False."""
        s, t, f = self.waiting()
        o = s.o
        wait = getattr(self.M, "RESTOP_WAIT", "restop-wait")
        hook = self.S.turnback_other_arrival
        self.assertIs(hook(o, 1), False)                              # A itself
        self.assertEqual(s.machine.state, wait)
        for field in ("jump_lock", "is_official_jumping"):             # the landing of a Jump is no formal arrival (PU-6)
            with self.subTest(field=field):
                setattr(o, field, True)
                self.assertIs(hook(o, 2), False)
                self.assertEqual(s.machine.state, wait)
                setattr(o, field, False)
        import types
        self.assertIs(hook(types.SimpleNamespace(), 2), False)         # no machine at all
        self.assertIs(hook(o, 2), True)                                # B reached by driving
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(s.machine.state, self.M.IDLE)

    def test_AR_21_arrival_at_b_by_driving_no_jump_chain_failed_b_not_scored_scoring_aborted(self):
        s, t, f = self.waiting()
        o = s.o
        b = s.sl[2]
        score_before = o.score
        history_before = len(o.save_data)
        self.tick_to(s, t + 4000, bve_next_loc=b["location"], bve_tgt_idx=2, bve_speed=2.0, bve_location=b["location"] - 100.0, bve_brk_notch=0)
        self.tick_to(s, t + 5000, bve_speed=0.0, bve_location=b["location"] - 0.3, bve_brk_notch=8)
        self.tick_to(s, t + 6000, bve_door=1, bve_arr_idx=2, bve_arr_seq=o.bve_arr_seq + 1)
        for k in range(1, 30):
            self.tick_to(s, t + 6000 + 500 * k)
        self.assertEqual(self.jumps(f), [], "no Jump to B after the train reached B by itself")
        self.assertEqual(s.machine.state, self.M.IDLE, "the wait state is dropped")
        self.assertFalse(o.is_scoring_mode, "scoring aborted (the same fail-closed stop as the other internal failures)")
        self.assertTrue(o.jump_lock)
        self.assertEqual(o.score, score_before, "B is not scored as an ordinary arrival (no stop position, no basic braking, no bonus)")
        self.assertEqual(len(o.save_data), history_before, "no B checkpoint")
        reasons = [e[1].get("reason") for e in f.events if e[0] == "diag:turnback-fail"]
        self.assertEqual(reasons, [SELF_DRIVE_B_REASON], "a clear reason is left in the product diagnostics (no popup)")
        self.assertEqual([p for p in o.popups if p.get("category") == "警告"], [], "an internal failure is diagnostics only (OD-TB-30)")


# ==============================================================================================================================================
# AR-22 .. AR-25  what the decision does NOT depend on
# ==============================================================================================================================================
class D_Independence(Base):
    def trace(self, door_during):
        s, t, f = self.scene()
        rows = []

        def snap(tag):
            rows.append((tag, s.machine.state, len(f.sent), tuple(sorted((p["text"], p["color"]) for p in s.o.popups if p["text"] in (G1, G2, W1, W2, OLD_G1)))))
        self.tick_to(s, t + 1500, bve_door=door_during)
        snap("quiet")
        self.move(s, t + 2000, bve_door=door_during)
        snap("moved")
        self.tick_to(s, t + 3000, bve_speed=0.0, bve_location=self.P.A_MARK - 20.0, bve_door=door_during)
        snap("out")
        self.tick_to(s, t + 4000, bve_speed=0.0, bve_location=self.P.A_MARK - 1.0, bve_door=door_during)
        snap("restop")
        self.tick_to(s, t + 9000, bve_door=door_during)
        snap("jump")
        return rows

    def test_AR_22_a_open_and_a_closed_make_the_same_product_decisions(self):
        opened, closed = self.trace(1), self.trace(0)
        self.assertEqual([r[1:] for r in opened], [r[1:] for r in closed])
        self.assertEqual([r[1] for r in opened], [self.M.ARMED, getattr(self.M, "RESTOP_WAIT", "restop-wait"), getattr(self.M, "RESTOP_WAIT", "restop-wait"), self.M.ARMED, self.M.REQUESTED],
                         "RED on the baseline: the cycle itself does not exist (the Jump left during the first movement)")

    def test_AR_23_no_door_indicator_or_signal_flag_is_read_by_the_decision(self):
        S, M = self.S, self.M
        for module, names in ((M, ("TurnbackMachine.tick", "TurnbackMachine.on_arrival", "TurnbackMachine.on_other_arrival")), (S, ("turnback_drive", "turnback_cancel_show", "turnback_restop_show", "turnback_other_arrival", "turnback_stop_range_capture", "turnback_train_state"))):
            for name in names:
                with self.subTest(function=name):
                    target = module
                    for part in name.split("."):
                        target = getattr(target, part)       # RED on the baseline for the new ones: the function does not exist
                    tree = ast.parse(inspect.getsource(target).lstrip() if "." not in name else "class _C:\n" + inspect.getsource(target))
                    words = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Name):
                            words.add(node.id)
                        elif isinstance(node, ast.Attribute):
                            words.add(node.attr)
                        elif isinstance(node, ast.arg):
                            words.add(node.arg)
                    bad = sorted(w for w in words if any(k in w.lower() for k in ("door", "lamp", "indicator", "signal", "flag")))
                    self.assertEqual(bad, [], bad)

    def test_AR_24_the_stop_range_is_the_author_range_never_the_scoring_range_of_330_m(self):
        s, t, f = self.scene()
        o = s.o
        self.assertEqual((o.bve_margin_f, o.bve_margin_b), (5.0, 5.0))
        self.move(s, t + 2000)
        # 100 m short of A: inside the 330 m scoring range (train length 300 + 30), far outside the author range
        for k in range(1, 40):
            self.tick_to(s, t + 3000 + 500 * k, bve_speed=0.0, bve_location=self.P.A_MARK - 100.0)
        self.assertEqual(self.jumps(f), [], "RED on the baseline (no cancellation at all): speed 0 inside 330 m is no re-stop")
        self.assertEqual(self.guide_texts(s), [])
        import re
        src = "".join(inspect.getsource(getattr(self.S, n)) for n in ("turnback_drive", "turnback_stop_range_capture", "turnback_train_state") if hasattr(self.S, n))
        self.assertIsNotNone(src and re.search(r"def turnback_stop_range_capture", src), "RED on the baseline: the capture of the author range does not exist")
        self.assertNotRegex(src, r"setting_stop_distance|STATION_MARGIN|bve_train_length")

    def test_AR_24b_the_range_is_the_one_captured_at_the_arrival_not_the_next_target(self):
        s, t, f = self.scene()
        o = s.o
        b = s.sl[2]
        self.move(s, t + 2000)
        # the sender has switched to B; B's margins are huge: they must not widen A's range
        self.tick_to(s, t + 3000, bve_next_loc=b["location"], bve_tgt_idx=2, bve_margin_f=400.0, bve_margin_b=400.0, bve_speed=0.0, bve_location=self.P.A_MARK + 50.0, bve_brk_notch=0)
        for k in range(1, 20):
            self.tick_to(s, t + 3000 + 500 * k)
        self.assertEqual(self.jumps(f), [], "RED on the baseline")
        self.assertEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"))
        self.tick_to(s, t + 14000, bve_speed=0.0, bve_location=self.P.A_MARK - 2.0)
        self.assertNotEqual(self.state(s), getattr(self.M, "RESTOP_WAIT", "restop-wait"), "A's own range (5 m) holds: the train is back inside it")

    def test_AR_25_the_same_python_path_serves_current_and_legacy(self):
        def run(managed):
            s, t, f = self.scene()
            if managed:
                s.o.jump_client = object()
                s.o.jump_group_available = lambda: True
            self.move(s, t + 2000)
            self.halt(s, t + 3000, offset=-1.0)
            self.tick_to(s, t + 8000)
            return (s.machine.state, len(f.sent), tuple(sorted((p["text"], p["color"]) for p in s.o.popups)))
        self.assertEqual(run(False), run(True))
        self.assertEqual(run(False)[:2], (self.M.REQUESTED, 1), "RED on the baseline")
        src = inspect.getsource(self.S)
        for name in ("turnback_cancel_show", "turnback_restop_show", "turnback_other_arrival", "turnback_stop_range_capture", "turnback_train_state"):
            self.assertTrue(hasattr(self.S, name), "RED on the baseline: %s does not exist" % name)
            body = inspect.getsource(getattr(self.S, name))
            self.assertNotRegex(body, r"jump_client|dataplane_strict|managed|legacy|current", "no host-specific branch in " + name)


# ==============================================================================================================================================
# AR-26 .. AR-29  what must stay true
# ==============================================================================================================================================
class E_ContractsKept(Base):
    def run_to_b(self, cycle):
        f = self.flow()
        s, o = f.scene, f.o
        t = s.machine.arrival_ms
        if cycle:
            self.move(s, t + 1500)
            self.halt(s, t + 2500, offset=-1.0)
            self.tick_to(s, t + 2500 + 4999)
            self.assertIsNone(o.jump_expectation, "the Jump left before the new five seconds were over (RED on the baseline)")
            f.restop_ms = t + 2500
        while o.jump_expectation is None:
            self.tick_to(s, o.bve_time_ms + 100)
            assert o.bve_time_ms < t + 30000, "no request"
        f.exp = o.jump_expectation
        f.t_a = t
        f.land()
        f.after(6)
        return f

    def test_AR_26_the_ordinary_a_to_b_jump_contract_is_kept(self):
        f = self.run_to_b(cycle=False)
        o = f.o
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(f.exp.station_index, 2)
        self.assertEqual([cp.get("origin") for cp in o.save_data][1:], ["turnback"])
        self.assertEqual(len(o.save_data), 2, "the start checkpoint + ONE B checkpoint")
        self.assertEqual(f.scene.machine.state, self.M.IDLE)

    def test_AR_27_the_c01_root_fix_is_kept_after_a_cancel_cycle(self):
        keys = ("time", "stop", "base_brake", "bonus")
        landing = lambda f: tuple(f.o.score_details[k] for k in keys)
        plain = self.run_to_b(cycle=False)
        plain_landing = landing(plain)          # read before the next flow replaces the scene (Scene closes its predecessor)
        cycled = self.run_to_b(cycle=True)
        self.assertEqual(landing(cycled), plain_landing, "the landing at B adds no stop position / braking / bonus / time after a cycle either")
        self.assertEqual(len(cycled.o.save_data), 2)
        self.assertEqual([cp.get("origin") for cp in cycled.o.save_data][1:], ["turnback"])
        self.assertEqual(sum(1 for e in cycled.events if e[0] == "create_save_data"), 0, "no generic B arrival checkpoint")

    def test_AR_28_pair_b_stays_untimed_and_scores_no_operating_time_at_the_departure(self):
        f = self.run_to_b(cycle=True)
        o = f.o
        self.assertFalse(o.is_station_timing(2))
        self.assertEqual(f.scene.machine.state, self.M.IDLE, "RED on the baseline: the chain state of a cycled run")
        before = o.score
        f.depart_b_only("close_then_go")
        f.after(10)
        self.assertEqual(o.score, before, "B departure +0")

    def test_AR_29_the_retry_state_restoration_is_kept_after_a_cancel_cycle(self):
        f = self.run_to_b(cycle=True)
        o = f.o
        f.depart_b_only("close_then_go")
        f.after(3)
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        before = o.score
        f.after(10)
        self.assertEqual(o.score, before)
        self.assertTrue(o.jump_lock)
        self.assertEqual(len(f.sent), 2, "RED on the baseline: one turnback Jump (after the cycle) and the Retry's own")


# ==============================================================================================================================================
# the pure machine: constants and derived state
# ==============================================================================================================================================
class F_Machine(Base):
    def machine(self, **kw):
        import pseudo_turnback_contract as C
        m = self.M.TurnbackMachine()
        ps, why = C.decode_ptpair("PTPAIR:1:A1B2C3D4:20:1:5-6-0", 20)
        assert why is None
        m.set_pairset(ps)
        return m

    RANGE = (1000.0, 5.0, 5.0)           # (position of A, margin_f, margin_b) as the arrival tick saw them

    def arm(self, m, now=100000, with_range=True, **kw):
        if with_range:
            kw.setdefault("stop_range", self.RANGE)
        m.on_arrival(now, 5, 1, 7, "A1B2C3D4", 20, 0, 19, -1, True, **kw)
        m.a_scoring_complete(now, False)
        return now

    def host_state(self, speed, location, kept=RANGE):
        """The host's strict judgement of the two facts, on a stub with exactly the attributes it reads."""
        import types
        machine = types.SimpleNamespace(stop_range=kept)
        stub = types.SimpleNamespace(bve_speed=speed, bve_location=location, turnback_machine=machine)
        return self.S.turnback_train_state(stub)

    def test_AR_30_jump_earliest_time_is_fixed_at_the_arrival(self):
        m = self.machine()
        self.arm(m)
        self.assertEqual(getattr(m, "jump_earliest_ms", None), 105000, "RED on the baseline: derived on the fly, never kept")

    def test_AR_31_strict_zero_a_tiny_or_negative_speed_is_movement_and_an_unknown_speed_is_unknown(self):
        for v in (0.001, -0.001, 0.5, -3.0, 120):
            with self.subTest(speed=v):
                self.assertIs(self.host_state(v, 1000.0)[0], True)
        for v in (0.0, -0.0, 0):
            with self.subTest(speed=v):
                self.assertIs(self.host_state(v, 1000.0)[0], False)
        for v in (None, float("nan"), float("inf"), "0", True):
            with self.subTest(speed=v):
                self.assertIsNone(self.host_state(v, 1000.0)[0], "not a finite real number: not observed")

    def test_AR_32_the_range_boundaries_are_inside_and_unknown_numbers_are_outside(self):
        for loc, inside in ((995.0, True), (1005.0, True), (1000.0, True), (994.999, False), (1005.001, False), (None, False), (float("nan"), False), (True, False)):
            with self.subTest(location=loc):
                self.assertIs(self.host_state(0.0, loc)[1], inside)
        self.assertIs(self.host_state(0.0, 1000.0, kept=None)[1], False, "no range kept: never a re-stop")
        self.assertIs(self.host_state(0.0, 1000.0, kept=(1000.0, float("nan"), 5.0))[1], False)
        self.assertIs(self.host_state(0.0, 1000.0, kept=(1000.0, 5.0))[1], False)
        asym = (1000.0, 2.0, 8.0)         # margin_f in front of the mark (-2 m), margin_b behind it (+8 m): d = A - train
        self.assertEqual([self.host_state(0.0, x, kept=asym)[1] for x in (1002.0, 1002.1, 992.0, 991.9)], [True, False, True, False])

    def test_AR_33_the_cancellation_does_not_consume_the_issued_key_and_the_arrival_time_is_kept(self):
        m = self.machine()
        self.arm(m)
        m.tick(101000, 7, True, moving=True, in_stop_range=False)
        self.assertEqual(m.issued, set())
        m.tick(102000, 7, True, moving=False, in_stop_range=True)
        self.assertEqual(m.arrival_ms, 100000)
        acts = m.tick(107000, 7, True, moving=False, in_stop_range=True)
        self.assertEqual([a[0] for a in acts], ["request_jump"])
        self.assertEqual(len(m.issued), 1)

    def test_AR_33b_a_re_stop_needs_both_facts_known_and_true(self):
        for moving, in_range in ((True, True), (None, True), (False, False), (False, None), (None, None), (False, 1), (0, True)):
            with self.subTest(moving=moving, in_range=in_range):
                m = self.machine()
                self.arm(m)
                m.tick(101000, 7, True, moving=True, in_stop_range=False)
                self.assertEqual(m.tick(102000, 7, True, moving=moving, in_stop_range=in_range), [])
                self.assertEqual(m.state, getattr(self.M, "RESTOP_WAIT", "restop-wait"))
        m = self.machine()
        self.arm(m)
        for moving in (None, 0, False, "yes", 1):
            self.assertEqual(m.tick(101000, 7, True, moving=moving, in_stop_range=False), [], "only the value True cancels")
        self.assertEqual(m.state, self.M.ARMED)

    def test_AR_34_derived_display_states_of_the_wait(self):
        m = self.machine()
        self.arm(m)
        m.tick(101000, 7, True, moving=True, in_stop_range=False)
        self.assertEqual(m.display_state(101000), getattr(self.M, "DISPLAY_CANCEL_WARNING", "CANCEL_WARNING"))
        self.assertEqual(m.display_state(106001), getattr(self.M, "DISPLAY_RESTOP_WAIT", "RESTOP_WAIT"))

    def test_AR_35_the_driver_feeds_the_strict_facts_and_the_helper_reads_the_speed_and_the_position_of_the_train(self):
        drive = inspect.getsource(self.S.turnback_drive)
        self.assertRegex(drive, r"moving\s*,\s*in_range\s*=\s*turnback_train_state\(self\)", "RED on the baseline: the driver does not feed the facts")
        self.assertRegex(drive, r"moving\s*=\s*moving", "RED on the baseline")
        helper = inspect.getsource(self.S.turnback_train_state)
        self.assertIn("bve_speed", helper)
        self.assertIn("bve_location", helper)
        self.assertRegex(helper, r"speed != 0", "strictly != 0")
    def test_AR_36_a_special_popup_arrival_cancelled_inside_its_three_seconds(self):
        f = self.R.Flow(self, operational=False)
        s = f.scene
        s.approach("stepwise")
        s.stop_at(0.0)
        t = s.open_door()
        sp = [p for p in s.o.popups if self.S.is_arrival_special_popup(p)]
        self.assertTrue(sp, "a special popup is on (0 cm stop + basic braking)")
        self.move(s, t + 1000)
        self.assertEqual(self.guide_texts(s), [], "the guidance was never shown (3.0 s special window) and is not shown after a cancellation")
        self.assertEqual([p["text"] for p in self.warn_rows(s)], [W1, W2], "RED on the baseline")
        self.halt(s, t + 2000, offset=-1.0)
        rows = self.popup_rows(s, (G1, G2))
        self.assertEqual([p["text"] for p in rows], [G1, G2])
        self.assertEqual({p["expire_time"] for p in rows}, {(t + 2000) / 1000.0 + 5.0}, "no special window after a re-stop: the whole 5.0 s is guidance")

    def test_AR_37_a_jump_that_cannot_be_sent_after_the_re_stop_still_ends_fail_closed(self):
        s, t, f = self.scene()
        o = s.o
        o.jump_client = None
        o.dataplane_strict = True        # managed host without a sender
        self.move(s, t + 2000)
        self.halt(s, t + 3000, offset=-1.0)
        self.tick_to(s, t + 3000 + 4999)
        self.assertTrue(o.is_scoring_mode, "RED on the baseline: the unavailable stop happened at the OLD request time (arrival + 5.0 s)")
        self.tick_to(s, t + 3000 + 5000)
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(f.sent, [])

    def test_AR_39_GUARD_a_train_that_stands_still_never_cancels_and_never_shows_a_warning(self):
        s, t, f = self.scene()
        for k in range(1, 100):
            self.tick_to(s, t + 40 * k)
            self.assertNotEqual(s.machine.state, getattr(self.M, "RESTOP_WAIT", "restop-wait"))
        self.assertEqual(self.warn_rows(s), [])
        self.assertEqual(getattr(s.machine, "cancel_count", 0), 0)
        self.assertEqual(len(f.sent), 0, "still inside the first 5.0 s")

    def test_AR_42_GUARD_a_machine_that_is_given_no_speed_and_no_position_requests_at_the_old_time(self):
        m = self.machine()
        self.arm(m, with_range=False)          # the machine of the baseline API: no range, no facts
        self.assertEqual(m.tick(104999, 7, True), [])
        acts = m.tick(105000, 7, True)
        self.assertEqual([a[0] for a in acts], ["request_jump"], "speed / position unknown = nothing observed = nothing cancelled")

    def test_AR_38_the_wait_field_set_is_minimal_and_new_state_is_one_name(self):
        names = [n for n in dir(self.M) if n.isupper() and isinstance(getattr(self.M, n), str)]
        self.assertIn("RESTOP_WAIT", names, "RED on the baseline: the one new chain state")
        self.assertEqual(getattr(self.M, "RESTOP_WAIT", None), "restop-wait")


if __name__ == "__main__":
    unittest.main()
