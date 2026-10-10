"""Phase SI-A1 - CHARACTERIZATION of what the production Python of the NORMAL (manual) mode does today, fixed BEFORE anything is split or connected.

This file pins the CURRENT behaviour, dangerous or inconsistent or not. It never asserts what the behaviour SHOULD be: where today's behaviour is a
known problem the test name starts with CURRENT_ and its docstring names the expected contract that a later step (SI-A3 / SI-B) changes; the change then
updates that one assertion on purpose and the diff says so. Nothing is "fixed" here silently.

The real Overlay is driven offscreen with the Win32 / keyboard / time / dialog / UDP seams replaced by recorders (tests/sia_rig.py). UDP 54321 is never
bound, the real keyboard and windows are never touched, nothing is written to the Desktop.

    A  scoring state: F1 menu, start, interrupt, finish, result screen, result save / cancel
    B  manual emergency brake and Smee virtual EB (scoring_logic.update_physics_and_scoring), including the missing-input behaviour
    C  keys: F7 / P / F8 suppression, the fast-forward release, the F8 injection
    D  windows: the "time and position" window, window search by title, F11, F12, F11/F12 sequences, invalid window handles
    E  P to P (the kick start)
    F  JUMP: detection, official jump, abort, the reference of last_jump_count
    G  telemetry intake that scoring depends on (BPP, STALIST, generation)
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sia_rig as R  # noqa: E402

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

P_KEY = R.KEY_P
F8_KEY = R.KEY_F8


def popup_texts(o):
    return [p["text"] for p in o.popups]


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["sia1"])
        import main
        cls.main = main

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.o = self.rig.o
        self.kb, self.gui, self.api, self.clock, self.log = self.rig.kb, self.rig.gui, self.rig.api, self.rig.clock, self.rig.log
        self.HWND = self.rig.hwnd

    def tearDown(self):
        self.rig.close()

    # helpers ---------------------------------------------------------------------------------------------------------------------------
    def tick(self, n=1):
        self.rig.tick(n)

    def tap(self, key):
        self.rig.tap(key)

    def posted_p(self):
        """The P key presses posted to the BVE window (key-down messages; every press is a down and an up message)."""
        return [p for p in self.api.posted if p[2] == P_KEY and p[1] == R.WM_KEYDOWN]

    def start_scoring_through_the_menu(self, advancing=True):
        """The path of a user: F1, 採点設定, the penalty page, the evaluation page, 採点を開始する. Returns nothing; the Overlay is scoring afterwards."""
        o = self.o
        o.station_list = [R.station("A", 0.0), R.station("B", 1000.0, terminal=True)]
        o.bve_time_ms = 36000000
        o.bve_actual_state = "RUNNING" if advancing else "PAUSED"
        self.tap("f1")
        self.assertEqual(o.menu_state, 1)
        self.tap("down")
        self.tap("enter")
        self.assertEqual(o.menu_state, 5)
        for _ in range(5):
            self.tap("down")
        self.tap("enter")
        self.assertEqual(o.menu_state, 6)
        for _ in range(6):
            self.tap("down")
        self.tap("enter")
        self.assertEqual(o.menu_state, 10)
        self.tap("down")
        self.assertEqual(o.menu_cursor, 1)
        self.tap("enter")


# ----------------------------------------------------------------------------------------------------------------------------------------------
class A_ScoringState(Base):
    def test_F1_opens_the_menu_and_pauses_a_running_BVE_with_one_P(self):
        self.tap("f1")
        self.assertEqual(self.o.menu_state, 1)
        self.assertEqual(self.o.menu_cursor, 0)
        self.assertEqual(self.o.current_menu_items, ["運転を再開する", "採点設定", "環境設定"])
        self.assertEqual(self.posted_p(), [(self.HWND, R.WM_KEYDOWN, P_KEY, 0)])
        self.assertTrue(self.o.was_advancing_before_menu)

    def test_F1_again_closes_the_menu_and_resumes_with_one_P(self):
        self.tap("f1")
        self.api.posted.clear()
        self.tap("f1")
        self.assertEqual(self.o.menu_state, 0)
        self.assertEqual(len(self.posted_p()), 1)

    def test_F1_with_a_paused_BVE_posts_no_P(self):
        self.o.bve_actual_state = "PAUSED"
        self.tap("f1")
        self.assertEqual(self.o.menu_state, 1)
        self.assertEqual(self.posted_p(), [])
        self.tap("f1")
        self.assertEqual(self.posted_p(), [])

    def test_F1_is_ignored_while_the_BVE_window_is_not_in_front(self):
        self.gui.foreground = 1
        self.tap("f1")
        self.assertEqual(self.o.menu_state, 0)

    def test_the_menu_offers_the_result_entry_only_after_the_scoring_finished(self):
        self.o.is_scoring_mode = True
        self.o.is_scoring_finished = True
        self.tap("f1")
        self.assertEqual(self.o.current_menu_items, ["運転を再開する", "採点結果を表示する", "採点を中断する", "選択した駅からやり直す", "環境設定"])

    def test_the_menu_of_a_scoring_run_replaces_the_settings_by_interrupt_and_retry(self):
        self.o.is_scoring_mode = True
        self.tap("f1")
        self.assertEqual(self.o.current_menu_items, ["運転を再開する", "採点を中断する", "選択した駅からやり直す", "環境設定"])

    def test_starting_the_scoring_from_the_menu(self):
        o = self.o
        self.start_scoring_through_the_menu()
        self.assertTrue(o.is_scoring_mode)
        self.assertFalse(o.is_scoring_finished)
        self.assertTrue(o.is_official_jumping)                              # until JUMP_COMPLETE arrives
        self.assertEqual(o.expected_target_loc, 0.0)
        self.assertEqual(o.menu_state, 0)                                   # the menu closed ...
        self.assertEqual(len(self.posted_p()), 2)                           # ... F1 paused the running BVE, the closing resume pressed P again
        self.assertEqual(o.save_data[0]["station_name"], "A")
        self.assertEqual(o.score, 0)
        self.assertEqual(o.total_retry_count, 0)
        self.assertFalse(o.is_bve_loaded)                                   # the STATUS must be seen again
        self.assertFalse(o.initial_kickstart_done)

    def test_starting_the_scoring_sends_one_jump_command_to_port_54322(self):
        self.start_scoring_through_the_menu()
        written = self.o.udp_socket.written
        self.assertEqual(len(written), 1)
        data, port = written[0]
        self.assertEqual(port, 54322)
        self.assertEqual(data, b"JUMP_STA_TIME:0:36000000")
        self.assertTrue(any(line.startswith("[MENU 6] 送信コマンド: JUMP_STA_TIME:0:36000000") for line in self.log))

    def test_the_scoring_start_does_not_check_session_driving_or_telemetry_state(self):
        """CURRENT: the start only needs the menu to be open. There is no gate (SI-A3 puts the managed gate in FRONT of this path, the manual path is unchanged)."""
        self.o.station_list = []
        self.o.menu_state = 10
        self.o.menu_cursor = 1
        self.o.handle_menu_enter(True)
        self.assertTrue(self.o.is_scoring_mode)
        self.assertEqual(self.o.udp_socket.written, [])                     # no station to jump to: no command at all

    def test_interrupting_the_scoring_asks_first_and_the_default_is_no(self):
        o = self.o
        o.is_scoring_mode = True
        self.tap("f1")
        self.tap("down")
        self.tap("enter")
        self.assertEqual(o.menu_state, 12)
        self.assertEqual(o.menu_cursor, 1)                                  # "いいえ"
        self.tap("enter")
        self.assertEqual(o.menu_state, 1)
        self.assertTrue(o.is_scoring_mode)

    def test_interrupting_the_scoring_with_yes_ends_it_and_closes_the_menu(self):
        o = self.o
        o.is_scoring_mode = True
        o.popups.append({"text": "x", "color": None, "expire_time": 1e9, "type": "neg", "category": "転動"})
        self.tap("f1")
        self.tap("down")
        self.tap("enter")
        self.tap("up")
        self.assertEqual(o.menu_cursor, 0)
        self.tap("enter")
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(o.menu_state, 0)
        self.assertEqual(o.popups, [])

    def test_interrupting_the_scoring_keeps_the_score_and_the_save_data(self):
        """CURRENT: the user's interrupt is NOT a discard of the scoring state: the score, the details and the check points stay in the Overlay."""
        o = self.o
        o.is_scoring_mode = True
        o.score = 700
        o.score_details["eb"] = -500
        o.save_data.append({"loc": 0.0, "time_ms": 0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0})
        self.tap("f1")
        self.tap("down")
        self.tap("enter")
        self.tap("up")
        self.tap("enter")
        self.assertEqual((o.score, o.score_details["eb"], len(o.save_data)), (700, -500, 1))

    def test_arrival_at_the_end_station_finishes_the_scoring_but_leaves_the_scoring_flag_on(self):
        o = self.o
        S = self.rig.scoring_logic
        o.is_scoring_mode = True
        o.station_list = [R.station("A", 0.0), R.station("B", 1000.0)]
        o.setting_end_idx = 1
        o.prev_next_loc = 1000.0
        o.bve_next_loc = 1000.0
        o.bve_location = 1000.0
        S.evaluate_arrival(o, 50.0, 1000.0)
        self.assertTrue(o.is_scoring_finished)
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual((o.end_message_time, o.result_screen_time), (55.0, 60.0))

    def test_the_result_screen_opens_ten_seconds_after_the_finish_and_closes_the_popups(self):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = True
        o.result_screen_time = 60.0
        o.end_message_time = 55.0
        o.bve_time_ms = 54000
        self.tick()
        self.assertEqual(o.menu_state, 0)
        o.bve_time_ms = 55000
        self.tick()
        self.assertIn("運転お疲れ様でした。", popup_texts(o))
        o.bve_time_ms = 60000
        self.tick()
        self.assertEqual((o.menu_state, o.menu_cursor), (11, 0))
        self.assertEqual(o.popups, [])

    def test_the_suppression_is_released_when_the_scoring_is_finished(self):
        o = self.o
        o.is_scoring_mode = True
        o.bve_speed = 5.0
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        o.is_scoring_finished = True
        self.tick()
        self.assertEqual(self.kb.active(), [])

    def test_the_suppression_is_released_when_the_scoring_is_interrupted(self):
        o = self.o
        o.is_scoring_mode = True
        o.bve_speed = 5.0
        self.tick()
        o.is_scoring_mode = False
        self.tick()
        self.assertEqual(self.kb.active(), [])

    def test_Esc_quits_the_application_without_touching_the_scoring_state(self):
        o = self.o
        o.is_scoring_mode = True
        self.kb.pressed.add("esc")
        self.tick()
        self.assertEqual(R.FakeApp.quits, 1)
        self.assertTrue(o.is_scoring_mode)                                  # CURRENT: nothing is cleaned up by the quit itself; the process just ends

    # -- the result screen and the save dialog -----------------------------------------------------------------------------------------------
    def result_screen(self):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = True
        o.menu_state = 11
        o.menu_cursor = 0
        o.station_list = [R.station("A", 0.0)]
        os.environ["USERPROFILE"] = self.tmp.name

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_profile = os.environ.get("USERPROFILE")

    def tearDown(self):
        if self.saved_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self.saved_profile
        self.tmp.cleanup()
        super().tearDown()

    def test_saving_the_result_writes_the_image_and_marks_it_saved(self):
        self.result_screen()
        target = os.path.join(self.tmp.name, "out.jpg")
        R.FakeFileDialog.answer = target
        self.tap("enter")
        self.assertTrue(self.o.is_result_saved)
        self.assertEqual(self.o.saved_file_path, target)
        self.assertTrue(os.path.isfile(target))
        self.assertEqual(len(R.FakeFileDialog.calls), 1)
        self.assertEqual(R.FakeFileDialog.calls[0][0], "採点結果を保存")
        self.assertFalse(self.o.is_capturing_screenshot)

    def test_cancelling_the_save_dialog_leaves_the_result_unsaved_and_the_screen_open(self):
        self.result_screen()
        R.FakeFileDialog.answer = ""
        self.tap("enter")
        self.assertFalse(self.o.is_result_saved)
        self.assertEqual(self.o.menu_state, 11)
        self.assertFalse(self.o.is_capturing_screenshot)

    def test_a_saved_result_is_closed_by_the_second_Enter(self):
        self.result_screen()
        self.o.is_result_saved = True
        self.tap("enter")
        self.assertEqual(self.o.menu_state, 0)
        self.assertEqual(R.FakeFileDialog.calls, [])

    def test_F1_and_Backspace_do_nothing_on_an_unsaved_result_screen(self):
        self.result_screen()
        self.tap("f1")
        self.assertEqual(self.o.menu_state, 11)
        self.tap("backspace")
        self.assertEqual(self.o.menu_state, 11)

    def test_Backspace_closes_a_saved_result_screen(self):
        self.result_screen()
        self.o.is_result_saved = True
        self.tap("backspace")
        self.assertEqual(self.o.menu_state, 0)

    def test_before_the_save_dialog_the_menu_and_system_hooks_are_released_but_not_the_router_or_f8(self):
        self.result_screen()
        self.tick()                                                         # the open result screen registers the menu hooks and the router
        self.assertIn("<all>", self.kb.active())
        seen = {}

        def at_dialog():
            seen["active"] = self.kb.active()
            seen["capturing"] = self.o.is_capturing_screenshot
        R.FakeFileDialog.on_call = at_dialog
        self.tap("enter")
        self.assertTrue(seen["capturing"])
        self.assertEqual(seen["active"], ["<all>"])                         # the numeric router (a pass-through global hook) is still there
        self.assertFalse(self.o.keys_blocked)
        self.assertFalse(self.o.sys_keys_blocked)

    def test_the_update_logic_timer_is_not_stopped_while_the_dialog_is_open(self):
        """CURRENT: the dialog's nested event loop keeps delivering the timer; nothing in the code guards update_logic against re-entry (the flag
        is_capturing_screenshot is only read by the painting)."""
        self.result_screen()
        ticks = []

        def at_dialog():
            ticks.append(self.o.is_capturing_screenshot)
            self.kb.pressed.discard("enter")                                # (a held key would retrigger the dialog inside the nested tick)
            self.tick()
        R.FakeFileDialog.on_call = at_dialog
        self.tap("enter")
        self.assertEqual(ticks, [True])

    def test_CURRENT_a_nested_tick_with_the_Enter_key_still_down_opens_the_dialog_again(self):
        """CURRENT: key_states is updated AFTER the key handlers, so a tick that runs inside the dialog (the timer keeps firing) sees the same Enter
        as a new press and calls the dialog again; it ends only because every nested call also cancels. SI-A3 does not let the managed step re-enter."""
        self.result_screen()
        depth = []

        def at_dialog():
            depth.append(1)
            if len(depth) < 3:
                self.tick()
        R.FakeFileDialog.on_call = at_dialog
        self.kb.pressed.add("enter")
        self.tick()
        self.assertEqual(len(depth), 3)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class B_EmergencyBrake(Base):
    def setUp(self):
        super().setUp()
        o = self.o
        o.is_scoring_mode = True
        o.station_list = [R.station("S1", 5000.0)]
        o.bve_next_loc = 5000.0
        o.bve_speed = 10.0
        o.bve_brk_max = 8
        o.bve_brk_notch = 0
        o.bve_btype = "Ecb"
        self.t = 100.0

    def step(self, dt, notch, bp=None):
        o = self.o
        self.t += dt
        o.bve_brk_notch = notch
        if bp is not None:
            o.bpPressure = bp
        self.rig.scoring_logic.update_physics_and_scoring(o, self.t, dt)

    def eb_popups(self):
        return [t for t in popup_texts(self.o) if t.startswith("非常ブレーキ")]

    def run_steps(self, steps):
        for s in steps:
            self.step(*s)

    # -- Ecb / Smee manual EB --------------------------------------------------------------------------------------------------------------
    def test_Ecb_an_eb_handle_for_less_than_0_3_seconds_is_not_an_eb(self):
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 2 + [(0.1, 0)] * 3)
        self.assertEqual(self.eb_popups(), [])
        self.assertFalse(self.o.manual_eb_penalty_applied)

    def test_Ecb_an_eb_handle_for_0_3_seconds_costs_500_exactly_once(self):
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 6)
        self.assertEqual(self.eb_popups(), ["非常ブレーキ使用 -500"])
        self.assertEqual(self.o.score_details["eb"], -500)
        self.assertTrue(self.o.manual_eb_penalty_applied)
        self.assertEqual(self.o.manual_eb_accum_time, 0.3)                  # clamped at the threshold

    def test_Ecb_the_same_event_is_not_charged_again_after_a_release_shorter_than_one_second(self):
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 4 + [(0.1, 0)] * 5 + [(0.1, 8)] * 4)
        self.assertEqual(self.eb_popups(), ["非常ブレーキ使用 -500"])
        self.assertEqual(self.o.score_details["eb"], -500)

    def test_Ecb_a_release_of_one_second_rearms_the_event(self):
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 4 + [(0.1, 0)] * 12)
        self.assertEqual((self.o.manual_eb_accum_time, self.o.manual_eb_cooling_time, self.o.manual_eb_penalty_applied), (0.0, 0.0, False))
        self.run_steps([(0.1, 8)] * 4)
        self.assertEqual(self.o.score_details["eb"], -1000)

    def test_Ecb_the_eb_is_not_charged_at_a_standstill(self):
        self.o.bve_speed = 0.0
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 6)
        self.assertEqual(self.eb_popups(), [])
        self.assertTrue(self.o.manual_eb_penalty_applied)                   # the event is consumed without a penalty

    def test_Ecb_the_eb_is_not_charged_when_the_user_switched_the_eb_penalty_off(self):
        self.o.pen_eb = False
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 6)
        self.assertEqual(self.eb_popups(), [])

    def test_the_eb_handle_is_recognised_by_the_notch_number_or_by_the_word(self):
        self.o.bve_brk_notch = 3
        self.o.bve_brk_text = "非常"
        self.assertEqual(self.rig.scoring_logic.update_manual_emergency_brake_state(self.o, 0.1)[0], True)
        self.o.bve_brk_text = "EB"
        self.assertEqual(self.rig.scoring_logic.update_manual_emergency_brake_state(self.o, 0.1)[0], True)
        self.o.bve_brk_text = "B7"
        self.assertEqual(self.rig.scoring_logic.update_manual_emergency_brake_state(self.o, 0.1)[0], False)

    def test_Ecb_a_time_jump_back_discards_the_accumulation_but_not_the_applied_flag(self):
        """The reset of reset_transient_scoring_state (time went backwards) clears the accumulator and the cooling time, and keeps manual_eb_penalty_applied
        so that an EB that was already charged is not charged again right after a jump."""
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 4)
        self.assertTrue(self.o.manual_eb_penalty_applied)
        self.rig.scoring_logic.reset_transient_scoring_state(self.o)
        self.assertEqual((self.o.manual_eb_accum_time, self.o.manual_eb_cooling_time), (0.0, 0.0))
        self.assertTrue(self.o.manual_eb_penalty_applied)

    def test_Ecb_a_paused_bve_with_dt_zero_accumulates_nothing(self):
        self.run_steps([(0.1, 0)] + [(0.0, 8)] * 50)
        self.assertEqual(self.o.manual_eb_accum_time, 0.0)
        self.assertEqual(self.eb_popups(), [])

    # -- Cl ----------------------------------------------------------------------------------------------------------------------------------
    def test_Cl_the_eb_handle_position_itself_is_the_eb_without_the_0_3_second_accumulation(self):
        self.o.bve_btype = "Cl"
        self.run_steps([(0.1, 0), (0.1, 8)])
        self.assertEqual(self.eb_popups(), ["非常ブレーキ使用 -500"])
        self.assertEqual(self.o.manual_eb_accum_time, 0.0)

    def test_Cl_each_new_handle_event_is_charged_again(self):
        self.o.bve_btype = "Cl"
        self.run_steps([(0.1, 0), (0.1, 8), (0.1, 8), (0.1, 0), (0.1, 8)])
        self.assertEqual(self.o.score_details["eb"], -1000)

    def test_Cl_never_has_a_virtual_eb(self):
        self.o.bve_btype = "Cl"
        self.run_steps([(0.1, 0, 0.0), (0.1, 8, 0.0), (0.1, 8, 0.0)])
        self.assertFalse(self.o.smee_virtual_eb_active)

    # -- Smee virtual EB -----------------------------------------------------------------------------------------------------------------------
    def smee(self):
        self.o.bve_btype = "Smee"
        self.o.bve_bp_initial = 490.0

    def test_Smee_the_virtual_eb_starts_with_an_accumulated_eb_and_a_low_brake_pipe(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0), (0.1, 8, 400.0), (0.1, 8, 400.0), (0.1, 8, 400.0)])
        self.assertTrue(self.o.smee_virtual_eb_active)
        self.assertEqual(self.eb_popups(), ["非常ブレーキ使用 -500"])

    def test_Smee_a_full_brake_pipe_never_starts_the_virtual_eb(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 490.0)] * 5)
        self.assertFalse(self.o.smee_virtual_eb_active)
        self.assertEqual(self.eb_popups(), ["非常ブレーキ使用 -500"])

    def test_Smee_the_start_threshold_is_95_percent_of_the_initial_pressure(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 465.5)] * 4)           # exactly 0.95 x 490: NOT below
        self.assertFalse(self.o.smee_virtual_eb_active)
        self.run_steps([(0.1, 8, 465.0)])
        self.assertTrue(self.o.smee_virtual_eb_active)

    def test_Smee_the_virtual_eb_holds_after_the_handle_is_released_until_the_pipe_recovers(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 400.0)] * 4 + [(0.1, 0, 400.0)] * 5)
        self.assertTrue(self.o.smee_virtual_eb_active)
        self.run_steps([(0.1, 0, 480.0)])
        self.assertFalse(self.o.smee_virtual_eb_active)

    def test_Smee_the_release_charges_one_relaxation_penalty_when_the_notch_is_idle(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 400.0)] * 4 + [(0.1, 0, 400.0)] * 3 + [(0.1, 0, 480.0)] * 3)
        self.assertEqual(popup_texts(self.o).count("緩和ブレーキ -100"), 1)
        self.assertEqual(self.o.score_details["rel_brake"], -100)

    def test_Smee_while_the_virtual_eb_is_active_the_initial_and_relaxation_penalties_are_waived(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 400.0)] * 4)
        self.assertEqual(popup_texts(self.o).count("初動ブレーキ -100"), 1)   # the first STRONG tick came BEFORE the virtual EB existed
        self.assertTrue(self.o.smee_virtual_eb_active)

    def test_Smee_there_is_no_virtual_eb_in_other_brake_types_even_with_a_low_pipe(self):
        for btype in ("Ecb", "Cl"):
            self.o.bve_btype = btype
            self.o.smee_virtual_eb_active = True
            self.run_steps([(0.1, 0, 0.0)])
            self.assertFalse(self.o.smee_virtual_eb_active, btype)

    def test_Smee_pause_does_not_advance_or_release_the_virtual_eb(self):
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 400.0)] * 4)
        self.run_steps([(0.0, 8, 400.0)] * 30)
        self.assertTrue(self.o.smee_virtual_eb_active)
        self.assertEqual(self.o.score_details["eb"], -500)

    def test_Smee_a_new_scenario_id_does_not_reset_the_eb_state_today(self):
        """CURRENT (the starting point of SI-A3, see the SI-0 list): manual_eb_* and smee_virtual_eb_active survive a SCENARIO_ID change."""
        self.smee()
        self.run_steps([(0.1, 0, 490.0)] + [(0.1, 8, 400.0)] * 4)
        self.o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        self.o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.assertTrue(self.o.smee_virtual_eb_active)
        self.assertTrue(self.o.manual_eb_penalty_applied)
        self.assertEqual(self.o.manual_eb_accum_time, 0.3)

    # -- missing inputs: the CURRENT behaviour ---------------------------------------------------------------------------------------------
    def test_CURRENT_Smee_without_any_BPP_the_brake_pipe_reads_zero_and_the_virtual_eb_never_ends(self):
        """CURRENT (fail-open): when BPP never arrived bpPressure stays 0.0, so 'the pipe is low' is permanently true. Once an EB was accumulated the
        virtual EB starts and is never released, and the initial / relaxation penalties stay waived. EXPECTED contract (SI-A3, managed scoring start
        gate): a Smee run is not started without BPP and a received bp_initial; the scoring_logic rule itself is NOT changed."""
        self.smee()
        self.o.bve_bp_initial = 490.0
        self.assertEqual(self.o.bpPressure, 0.0)
        self.run_steps([(0.1, 0)] + [(0.1, 8)] * 4 + [(0.1, 0)] * 20)
        self.assertTrue(self.o.smee_virtual_eb_active)

    def test_CURRENT_Smee_without_a_received_bp_initial_the_default_490_is_used_silently(self):
        """CURRENT: a 2-element BPP line leaves bve_bp_initial at its construction default 490.0 and nothing records that it was never received."""
        self.assertEqual(self.o.bve_bp_initial, 490.0)
        self.o.apply_telemetry_text("SCENARIO_ID:1,BPP:350.0")
        self.assertEqual((self.o.bpPressure, self.o.bve_bp_initial), (350.0, 490.0))
        self.assertFalse(hasattr(self.o, "bve_bp_initial_received"))

    def test_BPP_with_three_elements_sets_the_initial_pressure(self):
        self.o.apply_telemetry_text("SCENARIO_ID:1,BPP:350.0:500.0")
        self.assertEqual((self.o.bpPressure, self.o.bve_bp_initial), (350.0, 500.0))

    def test_CURRENT_missing_handle_and_brake_type_data_run_on_the_construction_defaults(self):
        """CURRENT: with no handle data (bve_brk_notch 0, text 'N') and the default brake type 'Ecb' scoring simply runs; nothing marks the data as missing."""
        o = self.o
        self.assertEqual((o.bve_btype, o.bve_brk_notch, o.bve_brk_text, o.bve_brk_max), ("Ecb", 0, "N", 8))


# ----------------------------------------------------------------------------------------------------------------------------------------------
class C_Keys(Base):
    def scoring(self, speed=0.0, finished=False):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = finished
        o.bve_speed = speed

    def test_F7_and_P_are_suppressed_with_suppress_true(self):
        self.scoring()
        self.tick()
        self.assertEqual([(h[1], h[2]) for h in self.kb.hooks], [("f7", True), ("p", True)])

    def test_the_suppress_hooks_swallow_the_event_by_a_callback_that_does_nothing(self):
        self.scoring(speed=5.0)
        self.tick()
        for handle in self.kb.active_handles():
            self.assertIsNone(self.kb.callbacks[handle](object()))

    def test_F8_is_suppressed_from_0_1_kmh_upwards_only(self):
        self.scoring(speed=0.09)
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])
        self.o.bve_speed = 0.1
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])

    def test_CURRENT_a_negative_speed_does_not_suppress_F8_but_the_fast_forward_release_uses_the_absolute_value(self):
        """CURRENT inconsistency: the F8 hook needs speed >= 0.1 (signed), the fast-forward release needs abs(speed) >= 0.1."""
        self.scoring(speed=-5.0)
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])
        self.tick()
        self.clock.now += 0.06
        self.o.bve_time_ms += 1000
        self.tick()
        self.assertEqual(len([p for p in self.api.posted if p[2] == F8_KEY]), 2)

    def test_the_F8_hook_is_not_registered_while_a_menu_is_open_because_the_menu_hooks_own_F8(self):
        self.scoring(speed=5.0)
        self.o.menu_state = 1
        self.tick()
        f8_hooks = [h for h in self.kb.active_handles() if h[1] == "f8"]
        self.assertEqual(len(f8_hooks), 1)                                  # the menu's own hook; no second one from the scoring
        self.assertFalse(getattr(self.o, "f8_physically_blocked", False))

    def test_closing_the_menu_in_a_scoring_run_hands_F8_to_the_scoring_hook_one_tick_later(self):
        """CURRENT: in the tick that closes the menu the F8 decision runs BEFORE the menu hooks are released, so the scoring hook follows one tick later."""
        self.scoring(speed=5.0)
        self.o.menu_state = 1
        self.tick()
        self.o.menu_state = 0
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])
        self.assertFalse(self.o.keys_blocked)
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        self.assertTrue(self.o.f8_physically_blocked)

    def test_before_the_scoring_and_after_the_end_no_key_is_suppressed(self):
        self.o.bve_speed = 5.0
        self.tick()
        self.assertEqual(self.kb.active(), [])
        self.scoring(speed=5.0, finished=True)
        self.tick()
        self.assertEqual(self.kb.active(), [])

    def test_the_suppression_follows_the_foreground_window_both_ways(self):
        self.scoring(speed=5.0)
        self.gui.foreground = 1
        self.tick()
        self.assertEqual(self.kb.active(), [])
        self.gui.foreground = self.HWND
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])

    def test_a_hook_is_registered_once_and_not_every_tick(self):
        self.scoring(speed=5.0)
        self.tick(5)
        self.assertEqual(len(self.kb.hooks), 3)

    def test_the_official_jump_does_not_stop_the_F7_P_F8_suppression(self):
        self.scoring(speed=5.0)
        self.o.is_official_jumping = True
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])

    # -- fast forward ---------------------------------------------------------------------------------------------------------------------
    def fast_forward(self, bve_ms=1000, real=0.06):
        self.tick()
        self.clock.now += real
        self.o.bve_time_ms += bve_ms
        self.tick()

    def test_the_fast_forward_ratio_below_ten_is_not_a_fast_forward(self):
        self.scoring(speed=5.0)
        self.tick()
        self.clock.now += 0.125                                             # (binary fractions: the ratios are exact)
        self.o.bve_time_ms += 1249                                          # 9.992 x real time
        self.tick()
        self.assertFalse(self.o.is_fast_forwarding)
        self.assertEqual([p for p in self.api.posted if p[2] == F8_KEY], [])

    def test_the_fast_forward_ratio_of_exactly_ten_is_one(self):
        self.scoring(speed=5.0)
        self.tick()
        self.clock.now += 0.125
        self.o.bve_time_ms += 1250                                          # exactly 10 x
        self.tick()
        self.assertEqual(len([p for p in self.api.posted if p[2] == F8_KEY]), 2)

    def test_the_release_posts_F8_down_and_up_to_the_bve_window_and_returns_to_normal_speed(self):
        self.scoring(speed=5.0)
        self.fast_forward()
        self.assertEqual([p for p in self.api.posted if p[2] == F8_KEY],
                         [(self.HWND, R.WM_KEYDOWN, F8_KEY, 0), (self.HWND, R.WM_KEYUP, F8_KEY, 0)])
        self.assertFalse(self.o.is_fast_forwarding)

    def test_the_release_does_not_happen_below_0_1_kmh_or_for_a_finished_scoring_or_during_an_official_jump(self):
        for speed, finished, jumping in ((0.09, False, False), (5.0, True, False), (5.0, False, True)):
            self.api.posted.clear()
            self.o.is_fast_forwarding = False
            self.o.ff_check_real_time = 0.0
            self.scoring(speed=speed, finished=finished)
            self.o.is_official_jumping = jumping
            self.fast_forward()
            self.assertEqual([p for p in self.api.posted if p[2] == F8_KEY], [], (speed, finished, jumping))

    def test_the_release_needs_the_F8_disable_flag(self):
        self.scoring(speed=5.0)
        self.o.F8_disable = False
        self.fast_forward()
        self.assertEqual([p for p in self.api.posted if p[2] == F8_KEY], [])

    def test_the_release_does_not_need_the_BVE_window_in_front(self):
        """CURRENT: the injection goes to the window handle and is independent of the foreground."""
        self.scoring(speed=5.0)
        self.gui.foreground = 1
        self.fast_forward()
        self.assertEqual(len([p for p in self.api.posted if p[2] == F8_KEY]), 2)

    def test_the_fast_forward_flag_is_tracked_without_scoring_but_nothing_is_injected(self):
        self.o.bve_speed = 5.0
        self.fast_forward()
        self.assertEqual([p for p in self.api.posted if p[2] == F8_KEY], [])

    def test_key_repeat_only_for_the_arrow_keys_after_400_ms(self):
        self.o.menu_state = 1
        self.o.current_menu_items = ["a", "b", "c", "d", "e"]
        self.kb.pressed.add("down")
        self.tick()
        self.assertEqual(self.o.menu_cursor, 1)
        self.clock.now += 0.3
        self.tick()
        self.assertEqual(self.o.menu_cursor, 1)
        self.clock.now += 0.2
        self.tick()
        self.assertEqual(self.o.menu_cursor, 2)

    def test_the_menu_keys_work_only_with_the_BVE_window_in_front(self):
        self.o.menu_state = 1
        self.o.current_menu_items = ["a", "b", "c"]
        self.gui.foreground = 1
        self.tap("down")
        self.assertEqual(self.o.menu_cursor, 0)

    def test_F2_toggles_the_diagnostic_display_and_the_graph_together(self):
        self.tap("f2")
        self.assertEqual((self.o.debug_all_penalties, self.o.show_graph), (True, True))
        self.tap("f2")
        self.assertEqual((self.o.debug_all_penalties, self.o.show_graph), (False, False))

    def test_the_numeric_router_is_registered_with_an_open_menu_and_removed_when_it_closes(self):
        self.o.menu_state = 1
        self.tick()
        self.assertIsNotNone(self.o.numeric_router_hook)
        self.assertIn("<all>", self.kb.active())
        self.o.menu_state = 0
        self.tick()
        self.assertIsNone(self.o.numeric_router_hook)
        self.assertEqual(self.kb.active(), [])


# ----------------------------------------------------------------------------------------------------------------------------------------------
class D_Windows(Base):
    def scoring(self, speed=0.0, finished=False):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = finished
        o.bve_speed = speed

    # -- the "time and position" window ------------------------------------------------------------------------------------------------------
    def test_diag_before_the_scoring_it_is_left_alone(self):
        self.gui.diag = 777
        self.tick(3)
        self.assertEqual(self.gui.mutating(), [])

    def test_diag_during_the_scoring_it_is_disabled_once(self):
        self.gui.diag = 777
        self.scoring()
        self.tick(3)
        self.assertEqual(self.gui.mutating(), [("EnableWindow", 777, False)])

    def test_diag_with_the_menu_open_it_is_disabled_and_enabled_again_when_the_menu_closes(self):
        self.gui.diag = 777
        self.o.menu_state = 1
        self.tick()
        self.assertEqual(self.gui.enabled, False)
        self.o.menu_state = 0
        self.tick()
        self.assertEqual(self.gui.enabled, True)

    def test_diag_after_the_scoring_ended_it_is_enabled_again(self):
        self.gui.diag = 777
        self.scoring()
        self.tick()
        self.o.is_scoring_finished = True
        self.tick()
        self.assertEqual(self.gui.enabled, True)

    def test_diag_it_does_not_need_the_BVE_window_in_front(self):
        """CURRENT: unlike the key suppression the window lock ignores the foreground window."""
        self.gui.diag = 777
        self.gui.foreground = 1
        self.scoring()
        self.tick()
        self.assertEqual(self.gui.enabled, False)

    def test_diag_a_window_that_appears_during_the_scoring_is_disabled_when_it_is_found(self):
        self.scoring()
        self.tick(2)
        self.assertEqual(self.gui.mutating(), [])
        self.gui.diag = 777
        self.tick()
        self.assertEqual(self.gui.mutating(), [("EnableWindow", 777, False)])

    def test_CURRENT_diag_interrupting_the_scoring_re_enables_it_but_Python_exit_does_not(self):
        """CURRENT: only the tick logic re-enables the window; the manual mode has no clean-up at exit (Esc quits the application with the window
        disabled; the user closes the BVE window). EXPECTED contract (SI-A3, managed): the exit path restores it."""
        self.gui.diag = 777
        self.scoring()
        self.tick()
        self.assertEqual(self.gui.enabled, False)
        self.kb.pressed.add("esc")
        self.tick()
        self.assertEqual(R.FakeApp.quits, 1)
        self.assertEqual(self.gui.enabled, False)

    def test_diag_lookup_errors_are_swallowed(self):
        self.gui.FindWindow = lambda cls, title: (_ for _ in ()).throw(RuntimeError("no"))
        self.scoring()
        self.tick()
        self.assertEqual(self.gui.mutating(), [])

    # -- finding the BVE window ----------------------------------------------------------------------------------------------------------------
    def test_the_BVE6_window_is_found_by_its_title_case_insensitively(self):
        self.gui.titles = {5: "Notepad", 6: "BVE Trainsim 6", 7: "bve trainsim 5"}
        self.assertEqual(self.o.find_bve_window(), 7)                       # the LAST match wins
        self.gui.titles = {6: "BVE Trainsim 6"}
        self.assertEqual(self.o.find_bve_window(), 6)

    def test_a_window_with_another_title_or_an_invisible_one_is_not_a_BVE_window(self):
        self.gui.titles = {5: "Notepad", 6: "BVE"}
        self.assertIsNone(self.o.find_bve_window())

    def test_CURRENT_the_search_is_over_all_processes_and_takes_any_matching_title(self):
        """CURRENT: no process-id filter (managed mode's HUD controller filters by the BVE PID; SI-A3 hands THAT handle to the shared step)."""
        self.gui.titles = {11: "BVE Trainsim 5 (other process)", 12: "BVE Trainsim 6"}
        self.assertEqual(self.o.find_bve_window(), 12)

    def test_an_invalid_handle_is_searched_again_and_the_link_state_and_the_kick_start_state_are_reset(self):
        o = self.o
        self.gui.valid = {9001}
        self.gui.titles = {9001: "BVE Trainsim 6"}
        o.is_bve_loaded = True
        o.initial_kickstart_done = True
        self.tick()
        self.assertEqual(o.bve_hwnd, 9001)
        self.assertIn(("SetWindowLong", None, None, None)[0], [c[0] for c in self.gui.calls])
        link = [c for c in self.gui.calls if c[0] == "SetWindowLong" and c[2] == -8]            # GWL_HWNDPARENT
        self.assertEqual([c[3] for c in link], [9001])
        self.assertTrue(o.is_linked)
        self.assertFalse(o.is_bve_loaded)
        self.assertFalse(o.initial_kickstart_done)

    def test_when_the_window_vanishes_after_it_was_found_the_application_quits(self):
        self.gui.valid = set()
        self.gui.titles = {}
        self.tick()
        self.assertEqual(R.FakeApp.quits, 1)

    def test_an_invalid_handle_makes_F11_and_the_toggle_do_nothing(self):
        self.o.bve_hwnd = 9999
        self.o.toggle_borderless_fullscreen()
        self.assertEqual(self.gui.mutating(), [])
        self.assertFalse(self.o.is_borderless_fullscreen)

    def test_the_overlay_follows_the_client_area_of_the_BVE_window(self):
        self.gui.client = (0, 0, 1280, 720)
        self.gui.client_origin = (50, 60)
        self.tick()
        g = self.o.geometry()
        self.assertEqual((g.x(), g.y(), g.width(), g.height()), (50, 60, 1280, 720))

    def test_a_minimized_BVE_window_hides_the_overlay(self):
        self.o.show()
        self.gui.iconic = True
        self.tick()
        self.assertFalse(self.o.isVisible())

    # -- F11 -----------------------------------------------------------------------------------------------------------------------------------
    def test_F11_first_press_maximizes_then_removes_the_frame_when_the_OS_has_finished(self):
        con = self.main.win32con
        self.tap("f11")
        self.assertEqual(self.o.bve_original_style, 0x14CF0000)
        self.assertEqual(self.o.bve_original_placement, self.gui.placement)
        self.assertIn(("SendMessage", self.HWND, con.WM_SYSCOMMAND, con.SC_MAXIMIZE, 0), self.gui.calls)
        self.assertFalse(self.o.is_borderless_fullscreen)                   # not yet: the frame comes off in the deferred call
        self.assertEqual(len(R.FakeQTimer.pending), 1)
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)
        stripped = 0x14CF0000 & ~(con.WS_CAPTION | con.WS_THICKFRAME | con.WS_MINIMIZEBOX | con.WS_MAXIMIZEBOX | con.WS_SYSMENU)
        self.assertIn(("SetWindowLong", self.HWND, con.GWL_STYLE, stripped), self.gui.calls)
        self.assertIn(("SetWindowPos", self.HWND, con.HWND_TOP, 0, 0, 1920, 1080, con.SWP_NOZORDER | con.SWP_FRAMECHANGED | con.SWP_SHOWWINDOW), self.gui.calls)

    def test_F11_on_an_already_maximized_window_acts_at_once_without_the_maximize_message(self):
        con = self.main.win32con
        self.gui.placement = (0, con.SW_SHOWMAXIMIZED, (0, 0), (0, 0), (0, 0, 1920, 1080))
        self.tap("f11")
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.assertNotIn("SendMessage", [c[0] for c in self.gui.calls])
        self.assertEqual(R.FakeQTimer.pending, [])

    def test_F11_second_press_restores_style_and_placement(self):
        con = self.main.win32con
        self.tap("f11")
        R.FakeQTimer.flush()
        self.gui.calls.clear()
        self.tap("f11")
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertEqual([c[0] for c in self.gui.calls], ["SetWindowLong", "SetWindowPos", "SetWindowPlacement"])
        self.assertEqual(self.gui.calls[0], ("SetWindowLong", self.HWND, con.GWL_STYLE, 0x14CF0000))
        self.assertEqual(self.gui.calls[2], ("SetWindowPlacement", self.HWND, self.gui.placement))

    def test_F11_three_presses_alternate(self):
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.tap("f11")
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)

    def test_CURRENT_F11_twice_before_the_OS_finished_maximizing_queues_two_fullscreen_requests_and_never_restores(self):
        """CURRENT: the toggle looks at is_borderless_fullscreen, which only the deferred call sets. A second press inside that window repeats the
        maximize request instead of undoing it. The user ends up fullscreen after two presses."""
        self.tap("f11")
        self.tap("f11")
        self.assertEqual(len(R.FakeQTimer.pending), 2)
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)

    def test_F11_works_with_any_scoring_state_and_with_a_menu_open(self):
        self.scoring()
        self.o.menu_state = 1
        self.o.current_menu_items = ["a"]
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)

    def test_F11_the_deferred_frame_removal_is_skipped_when_the_window_is_gone_by_then(self):
        self.tap("f11")
        self.gui.valid = set()
        R.FakeQTimer.flush()
        self.assertFalse(self.o.is_borderless_fullscreen)

    def test_F11_a_failure_in_the_deferred_part_is_logged_and_does_not_set_the_state(self):
        self.tap("f11")
        self.gui.SetWindowPos = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        R.FakeQTimer.flush()
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertTrue(any(line.startswith("[WINDOW] フルスクリーン化エラー") for line in self.log))

    # -- F12 and the sequences ---------------------------------------------------------------------------------------------------------------
    def test_F12_sets_the_standard_style_and_a_1280_by_720_window_whatever_the_original_was(self):
        con = self.main.win32con
        self.tap("f12")
        self.assertIn(("SetWindowLong", self.HWND, con.GWL_STYLE, con.WS_OVERLAPPEDWINDOW | con.WS_VISIBLE), self.gui.calls)
        self.assertIn(("SetWindowPos", self.HWND, 0, 100, 100, 1280, 720, con.SWP_NOZORDER | con.SWP_FRAMECHANGED | con.SWP_SHOWWINDOW), self.gui.calls)
        self.assertFalse(self.o.is_borderless_fullscreen)

    def test_F12_works_without_F11_before_and_keeps_the_saved_original_untouched(self):
        self.o.bve_original_style = 123
        self.tap("f12")
        self.assertEqual(self.o.bve_original_style, 123)

    def test_F11_then_F12_returns_to_the_standard_window_and_clears_only_the_fullscreen_flag(self):
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.tap("f12")
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertEqual(self.o.bve_original_style, 0x14CF0000)            # F12 does not forget the original
        self.assertEqual(self.gui.style, self.main.win32con.WS_OVERLAPPEDWINDOW | self.main.win32con.WS_VISIBLE)

    def test_CURRENT_F12_then_F11_takes_the_F12_window_as_the_new_original(self):
        """CURRENT: after F12 the window style is the standard one, so the following F11 saves THAT as 'original': the user's original size and
        position are gone for good after an F12 (F12 is a rescue, not a restore). The F12 question is a separate decision after SI-A."""
        self.tap("f11")
        R.FakeQTimer.flush()
        self.tap("f12")
        self.tap("f11")
        R.FakeQTimer.flush()
        self.assertEqual(self.o.bve_original_style, self.main.win32con.WS_OVERLAPPEDWINDOW | self.main.win32con.WS_VISIBLE)
        self.assertTrue(self.o.is_borderless_fullscreen)

    def test_F12_F11_F12_sequence_ends_standard(self):
        self.tap("f12")
        self.tap("f11")
        R.FakeQTimer.flush()
        self.tap("f12")
        self.assertFalse(self.o.is_borderless_fullscreen)

    def test_F12_logs_one_line_and_needs_the_BVE_window_in_front(self):
        self.tap("f12")
        self.assertEqual(len([l for l in self.log if l.startswith("[WINDOW] F12")]), 1)

    def test_F12_with_an_invalid_handle_searches_the_window_first_then_acts_on_the_found_one(self):
        self.gui.valid = {9001}
        self.gui.titles = {9001: "BVE Trainsim 6"}
        self.gui.foreground = 9001
        self.o.bve_hwnd = self.HWND
        self.tap("f12")
        self.assertEqual(self.o.bve_hwnd, 9001)
        self.assertEqual([c for c in self.gui.mutating() if c[1] == self.HWND], [])                 # nothing for the stale handle
        self.assertTrue(any(c[0] == "SetWindowPos" and c[1] == 9001 and c[5:7] == (1280, 720) for c in self.gui.calls))

    def test_a_generation_change_does_not_touch_the_window_state_today(self):
        self.tap("f11")
        R.FakeQTimer.flush()
        self.o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        self.o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.assertEqual(self.o.bve_hwnd, self.HWND)
        self.assertEqual(self.o.bve_original_style, 0x14CF0000)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class E_PtoP(Base):
    def prepare(self, state="PAUSED"):
        o = self.o
        o.is_bve_loaded = True
        o.station_list = []
        o.bve_actual_state = state
        o.initial_kickstart_done = False
        o.bve_time_ms = 36000000

    def test_the_first_P_needs_loaded_paused_and_no_station_list(self):
        for loaded, state, stations in ((False, "PAUSED", []), (True, "RUNNING", []), (True, "PAUSED", [R.station("S")])):
            self.api.posted.clear()
            self.prepare(state)
            self.o.is_bve_loaded = loaded
            self.o.station_list = list(stations)
            self.o.auto_pause_pending = False
            self.tick()
            self.assertEqual(self.posted_p(), [], (loaded, state, len(stations)))

    def test_the_first_P_is_posted_once_per_pause_even_when_the_state_stays_paused(self):
        self.prepare()
        self.tick()
        self.assertEqual(len(self.posted_p()), 1)
        self.o.bve_actual_state = "PAUSED"                                  # a stale heartbeat
        self.tick(3)
        self.assertEqual(len(self.posted_p()), 1)

    def test_the_second_P_waits_for_the_station_list_the_advancing_time_and_the_running_state(self):
        self.prepare()
        self.tick()
        self.api.posted.clear()
        self.o.station_list = [R.station("S")]
        self.tick()                                                         # the list is there but the time did not advance
        self.assertEqual(self.posted_p(), [])
        self.o.bve_time_ms += 1
        self.tick()                                                         # advancing (the kick start set RUNNING) and the time moved: the pausing P
        self.assertEqual(len(self.posted_p()), 1)
        self.assertFalse(self.o.auto_pause_pending)

    def test_CURRENT_the_pending_second_P_is_dropped_even_when_the_BVE_does_not_report_running(self):
        """CURRENT: auto_pause_pending is cleared when the time moved even if no P was posted (the state was not RUNNING), so a BVE that stays
        running afterwards is never paused again."""
        self.prepare()
        self.tick()
        self.api.posted.clear()
        self.o.station_list = [R.station("S")]
        self.o.bve_time_ms += 1
        self.o.bve_actual_state = "PAUSED"
        self.tick()
        self.assertEqual(self.posted_p(), [])
        self.assertFalse(self.o.auto_pause_pending)

    def test_the_second_P_is_posted_only_once(self):
        self.prepare()
        self.tick()
        self.o.station_list = [R.station("S")]
        self.o.bve_time_ms += 500
        self.api.posted.clear()
        self.tick(4)
        self.assertEqual(len(self.posted_p()), 1)

    def test_CURRENT_a_station_list_of_an_earlier_scenario_blocks_the_kick_start_of_the_next_one(self):
        """CURRENT: station_list is not discarded at a scenario change, and the kick start needs 'not station_list'. EXPECTED (SI-A3, managed): the
        list is discarded at the generation boundary, so a reused process can kick the next scenario."""
        self.prepare()
        self.o.station_list = [R.station("old")]
        self.tick()
        self.assertEqual(self.posted_p(), [])
        self.o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        self.o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.tick()
        self.assertEqual(self.posted_p(), [])
        self.assertEqual(len(self.o.station_list), 1)

    def test_the_kick_start_state_is_reset_by_a_lost_window_only(self):
        self.prepare()
        self.o.initial_kickstart_done = True
        self.tick()
        self.assertEqual(self.posted_p(), [])
        self.assertTrue(self.o.initial_kickstart_done)

    def test_the_BVE_status_datagram_sets_the_state_and_the_loaded_flag(self):
        self.o.udp_socket.incoming = [b"STATUS:LOADED:PAUSED"]
        self.o.read_udp_data()
        self.assertEqual((self.o.bve_actual_state, self.o.is_bve_loaded), ("PAUSED", True))
        self.o.udp_socket.incoming = [b"STATUS:LOADED:RUNNING"]
        self.o.read_udp_data()
        self.assertEqual(self.o.bve_actual_state, "RUNNING")

    def test_without_any_status_the_advancing_state_is_guessed_from_the_clock(self):
        self.o.bve_actual_state = ""
        self.o.toggle_menu(False)
        self.assertEqual(self.o.menu_state, 1)
        self.o.menu_state = 0
        self.o.last_time_change_real = self.clock.now
        self.o.last_bve_time_ms = 0
        self.o.bve_time_ms = 5
        self.tick()
        self.assertGreaterEqual(self.o.last_time_change_real, 0)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class F_Jump(Base):
    def scoring(self):
        self.o.is_scoring_mode = True
        self.o.station_list = [R.station("A", 0.0), R.station("B", 1000.0)]

    def jump(self, n):
        self.o.bve_jump_count = n
        self.rig.scoring_logic.update_physics_and_scoring(self.o, 100.0, 0.016)

    def test_a_jump_before_the_scoring_is_recorded_and_locks_but_aborts_nothing(self):
        self.jump(1)
        self.assertEqual(self.o.last_jump_count, 1)
        self.assertTrue(self.o.jump_lock)
        self.assertFalse(self.o.is_scoring_mode)
        self.assertEqual(self.o.popups, [])
        self.assertTrue(any(l.startswith("[JUMP DETECT]") for l in self.log))

    def test_an_unofficial_jump_during_the_scoring_aborts_it_with_two_warnings(self):
        self.scoring()
        self.jump(1)
        self.assertFalse(self.o.is_scoring_mode)
        self.assertEqual(popup_texts(self.o), ["不正なジャンプを検知しました。", "採点を中断します。"])
        self.assertFalse(self.o.is_official_jumping)
        self.assertTrue(self.o.jump_lock)

    def test_the_abort_by_a_jump_keeps_the_score_and_the_save_data(self):
        """CURRENT: like the user's interrupt, the jump abort keeps score / details / check points; it only turns the scoring flag off."""
        self.scoring()
        self.o.score = 400
        self.o.save_data.append({"loc": 0.0, "time_ms": 0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0})
        self.jump(1)
        self.assertEqual((self.o.score, len(self.o.save_data)), (400, 1))

    def test_a_jump_notification_during_an_official_jump_is_held_back(self):
        self.scoring()
        self.o.is_official_jumping = True
        self.jump(1)
        self.assertTrue(self.o.is_scoring_mode)
        self.assertTrue(self.o.is_official_jumping)
        self.assertEqual(self.o.popups, [])
        self.assertEqual(self.o.last_jump_count, 1)

    def test_a_jump_after_the_scoring_finished_does_not_abort(self):
        self.scoring()
        self.o.is_scoring_finished = True
        self.jump(1)
        self.assertTrue(self.o.is_scoring_mode)
        self.assertEqual(self.o.popups, [])

    def test_a_further_jump_removes_the_previous_warning_first(self):
        self.scoring()
        self.jump(1)
        self.assertEqual(len(self.o.popups), 2)
        self.jump(2)
        self.assertEqual(self.o.popups, [])                                 # not scoring any more: no new warning, the old ones are gone

    def test_a_forward_jump_of_more_than_10_m_makes_the_next_pass_unscored(self):
        self.o.bve_location = 100.0
        self.o.prev_frame_loc = 0.0
        self.jump(1)
        self.assertTrue(self.o.ignore_next_pass_score)
        self.o.bve_location = 105.0
        self.o.prev_frame_loc = 100.0
        self.jump(2)
        self.assertFalse(self.o.ignore_next_pass_score)

    def test_the_same_count_is_no_jump(self):
        self.scoring()
        self.jump(0)
        self.assertTrue(self.o.is_scoring_mode)
        self.assertFalse(self.o.jump_lock)

    def test_the_official_jump_completion_with_the_expected_location_ends_the_protection(self):
        o = self.o
        self.scoring()
        self.rig.scoring_logic.begin_official_jump(o, 1000.0, 36000000)
        self.assertTrue(o.is_official_jumping)
        o.udp_socket.incoming = [b"JUMP_COMPLETE:STA:1:1000.0:36000000:3"]
        o.read_udp_data()
        self.assertFalse(o.is_official_jumping)
        self.assertEqual((o.bve_jump_count, o.last_jump_count), (3, 3))
        self.assertEqual(o.door_open_loc, 1000.0)

    def test_the_completion_with_another_location_is_rejected_and_logged(self):
        o = self.o
        self.scoring()
        self.rig.scoring_logic.begin_official_jump(o, 1000.0, 36000000)
        o.udp_socket.incoming = [b"JUMP_COMPLETE:STA:1:900.0:36000000:3"]
        o.read_udp_data()
        self.assertTrue(o.is_official_jumping)
        self.assertTrue(any(l.startswith("[JUMP COMPLETE REJECTED]") for l in self.log))

    def test_a_completion_without_an_official_jump_is_rejected(self):
        o = self.o
        o.udp_socket.incoming = [b"JUMP_COMPLETE:STA:1:900.0:36000000:3"]
        o.read_udp_data()
        self.assertTrue(any(l.startswith("[JUMP COMPLETE REJECTED]") for l in self.log))

    def test_the_official_jump_blocks_the_roll_penalty(self):
        o = self.o
        self.scoring()
        o.is_official_jumping = True
        o.bve_door = 1
        o.bve_speed = 5.0
        o.bve_location = 50.0
        self.jump(0)
        self.assertEqual(o.roll_penalty_count, 0)

    def test_CURRENT_a_process_that_starts_late_takes_the_first_JUMP_count_as_a_jump(self):
        """CURRENT: last_jump_count starts at 0 and is not synchronised with the sender (Current's counter is a sender lifetime counter). A reused
        process that was scoring when the first telemetry of a scenario carries JUMP:3 aborts the scoring. EXPECTED (SI-A3): the reference is
        synchronised to the first accepted telemetry of a generation."""
        self.scoring()
        self.o.apply_telemetry_text("SCENARIO_ID:1,JUMP:3,SPEED:0")
        self.rig.scoring_logic.update_physics_and_scoring(self.o, 100.0, 0.016)
        self.assertFalse(self.o.is_scoring_mode)

    def test_the_last_jump_count_survives_a_scenario_id_change_today(self):
        self.o.last_jump_count = 5
        self.o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        self.o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.assertEqual(self.o.last_jump_count, 5)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class G_TelemetryScoringDependsOn(Base):
    def test_STALIST_replaces_the_station_list_and_an_empty_list_keeps_the_old_one(self):
        self.o.udp_socket.incoming = [b"STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=0=1000.0=-1=-1=-1=15000=0=1"]
        self.o.read_udp_data()
        self.assertEqual([s["name"] for s in self.o.station_list], ["A", "B"])
        self.assertEqual(self.o.station_list[1]["is_terminal"], True)
        self.o.udp_socket.incoming = [b"STALIST:"]
        self.o.read_udp_data()
        self.assertEqual([s["name"] for s in self.o.station_list], ["A", "B"])

    def test_a_new_scenario_id_discards_the_scoring_and_the_menu_and_the_settings_but_not_the_station_list(self):
        o = self.o
        o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        o.is_scoring_mode = True
        o.menu_state = 1
        o.station_list = [R.station("old")]
        o.setting_start_idx = 3
        o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual((o.menu_state, o.setting_start_idx), (0, 0))
        self.assertEqual(len(o.station_list), 1)

    def test_the_train_length_sets_the_default_stop_distance_once(self):
        o = self.o
        o.apply_telemetry_text("SCENARIO_ID:1,TRAINLEN:100")
        self.assertEqual(o.setting_stop_distance, 110)
        o.setting_stop_distance = 150
        o.apply_telemetry_text("SCENARIO_ID:1,TRAINLEN:200")
        self.assertEqual(o.setting_stop_distance, 150)

    def test_the_same_scenario_id_keeps_everything(self):
        o = self.o
        o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        o.is_scoring_mode = True
        o.apply_telemetry_text("SCENARIO_ID:1,SPEED:3")
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(o.bve_speed, 3.0)


if __name__ == "__main__":
    unittest.main()
