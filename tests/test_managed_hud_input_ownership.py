"""Phase UI-ALT-F4: the input ownership of the Overlay - HUD (click-through, never in front, every key and click reaches BVE) and operation screens (the SAME window
takes the mouse, the keyboard and the foreground; nothing reaches BVE behind it).

    C:\\Python314\\python.exe -B -m unittest discover -s tests -p "test_managed_hud_input_ownership.py" -v

Layers: (A) the controller's switch against fakes (every sequence of the specification); (B) the Overlay's own operations (the extended style, the foreground), real
Overlay with a fake Win32 module; (C) the step of the Overlay follows the Overlay as the "game side" in front. The real window facts (hit test, foreground, handle) are in
tests/overlay_input_ownership_real_check.py and are asserted by test_overlay_user_close_altf4.py (C_RealWindows, D_RealForeground).
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import managed_hud as mh  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402
import test_overlay_user_close_altf4 as uc  # noqa: E402

HAS_QT = e4.HAS_QT


class A_Switch(uc.UserCase):
    def test_hud_stays_click_through_and_never_takes_or_returns_the_foreground(self):
        self.pump(50)
        self.assertEqual((self.overlay.ownership_calls, self.overlay.foreground_calls), ([], []))
        self.assertFalse(self.overlay.ownership)
        self.assertEqual(self.lines("hud-input-mode"), [])

    def test_an_operation_screen_gives_the_overlay_the_input_and_the_foreground(self):
        self.overlay.menu_state = 1
        self.pump(1)
        self.assertEqual(self.overlay.ownership_calls, [True])
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd])
        self.assertEqual(self.api.front, self.overlay.hwnd)
        self.assertEqual(self.hud.input_modes, 1)
        self.assertIn("mode=operation", self.lines("hud-input-mode")[0])
        self.assertIn("result=taken", self.lines("hud-input-focus")[0])

    def test_every_operation_screen_state_is_an_operation_screen(self):
        for state in range(1, 13):
            self.setUp()
            self.overlay.menu_state = state
            self.pump(1)
            self.assertTrue(self.overlay.ownership, state)
            self.assertEqual(self.api.front, self.overlay.hwnd, state)

    def test_the_same_window_is_used_the_handle_never_changes(self):
        window = self.overlay.winId()
        self.overlay.menu_state = 11
        self.pump(5)
        self.overlay.menu_state = 0
        self.pump(5)
        self.assertEqual(self.overlay.winId(), window)
        self.assertEqual((self.overlay.shows, self.overlay.hides), (1, 0))             # no hide / show to switch the mode
        self.assertEqual(self.api.owner_calls.count((window, self.api.hwnd)), 1)       # the owner is set once (the show), not again by the switch

    def test_the_foreground_is_not_taken_from_another_window(self):
        self.api.front = 777777                                                       # the save dialog or another application
        self.overlay.menu_state = 1
        self.pump(10)
        self.assertEqual(self.overlay.foreground_calls, [])
        self.assertEqual(self.api.front, 777777)
        self.assertTrue(self.overlay.ownership)                                       # the Overlay still owns the input: a click on it brings it forward
        self.assertIn("result=other-window", self.lines("hud-input-focus")[0])

    def test_the_foreground_is_not_taken_from_the_result_save_dialog_and_comes_back_to_the_overlay_with_it(self):
        self.overlay.menu_state = 11
        self.pump(1)
        self.assertEqual(self.api.front, self.overlay.hwnd)
        self.api.front = 888888                                                       # the dialog (owner = Overlay) is in front
        self.pump(5)
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd])           # the one take of the screen opening, none for the dialog
        self.api.front = self.overlay.hwnd                                            # Windows returns the activation to the owner when the dialog closes
        self.pump(5)
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd])
        self.assertTrue(self.overlay.ownership)

    def test_a_refused_foreground_is_tried_a_bounded_number_of_times_and_reported_once(self):
        self.overlay.foreground_works = False
        self.overlay.menu_state = 1
        self.pump(mh.FOREGROUND_TRIES + 20)
        self.assertEqual(len(self.overlay.foreground_calls), mh.FOREGROUND_TRIES)
        self.assertEqual(len(self.lines("hud-input-focus")), 1)
        self.assertIn("result=refused", self.lines("hud-input-focus")[0])
        self.assertTrue(self.overlay.ownership)

    def test_closing_the_operation_screen_hands_the_foreground_back_to_bve(self):
        self.overlay.menu_state = 1
        self.pump(2)
        self.overlay.menu_state = 0
        self.pump(1)
        self.assertEqual(self.overlay.ownership_calls, [True, False])
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd, self.api.hwnd])
        self.assertEqual(self.api.front, self.api.hwnd)
        self.assertIn("returned=yes", self.lines("hud-input-mode")[1])

    def test_closing_the_operation_screen_leaves_another_application_in_front(self):
        self.overlay.menu_state = 1
        self.pump(2)
        self.api.front = 555555                                                       # the user went to another application
        self.overlay.menu_state = 0
        self.pump(2)
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd])
        self.assertEqual(self.api.front, 555555)
        self.assertFalse(self.overlay.ownership)
        self.assertIn("returned=no", self.lines("hud-input-mode")[1])

    def test_a_hidden_overlay_is_click_through_again(self):
        self.overlay.menu_state = 1
        self.pump(2)
        self.publish(True, False, 1)                                                  # Driving OFF (a pause): the HUD is hidden
        self.pump(2)
        self.assertFalse(self.overlay.visible)
        self.assertFalse(self.overlay.ownership)
        self.assertEqual(self.overlay.ownership_calls, [True, False])

    def test_a_window_that_qt_created_again_starts_click_through_and_is_corrected(self):
        self.overlay.menu_state = 1
        self.pump(2)
        self.overlay.ownership = False                                                # the native window was re-created: click-through again
        self.pump(1)
        self.assertTrue(self.overlay.ownership)
        self.assertEqual(self.overlay.ownership_calls, [True, True])

    def test_a_failing_foreground_hand_back_still_leaves_the_hud_click_through(self):
        def broken(hwnd):
            raise OSError("access denied")

        self.overlay.menu_state = 1
        self.pump(2)
        self.overlay.bring_to_foreground = broken
        self.overlay.menu_state = 0
        self.pump(1)
        self.assertFalse(self.overlay.ownership)                                      # the style went back before the hand-back failed
        self.assertEqual(self.hud.input_errors, 1)
        self.pump(30)
        self.assertFalse(self.overlay.ownership)
        self.assertLessEqual(self.hud.input_errors, 1 + mh.HUD_FOREGROUND_RETRIES)          # the hand-back is retried a bounded number of times

    def test_an_overlay_that_still_owns_the_input_in_hud_mode_is_made_click_through_again(self):
        self.overlay.ownership = True                                                 # e.g. a switch that failed half way
        self.pump(1)
        self.assertFalse(self.overlay.ownership)
        self.assertEqual(self.overlay.ownership_calls, [False])

    def test_a_hidden_overlay_in_front_hands_the_foreground_to_bve(self):
        self.overlay.menu_state = 11
        self.pump(2)
        self.assertEqual(self.api.front, self.overlay.hwnd)
        self.publish(True, False, 1)                                                  # Driving OFF: the Overlay is hidden while it is in front
        self.pump(2)
        self.assertFalse(self.overlay.visible)
        self.assertEqual(self.api.front, self.api.hwnd)

    def test_a_hidden_overlay_does_not_take_the_foreground_from_another_application(self):
        self.overlay.menu_state = 11
        self.pump(2)
        self.api.front = 424242
        self.publish(True, False, 1)
        self.pump(2)
        self.assertEqual(self.api.front, 424242)

    def test_no_foreground_window_at_all_does_not_use_up_the_tries(self):
        self.api.front = 0
        self.overlay.foreground_works = False
        self.overlay.menu_state = 1
        self.pump(mh.FOREGROUND_TRIES + 10)
        self.assertEqual(self.hud._foreground_tries, mh.FOREGROUND_TRIES)
        self.assertGreater(len(self.overlay.foreground_calls), mh.FOREGROUND_TRIES)           # it keeps trying while nobody is in front

    def test_the_hud_never_keeps_the_foreground(self):
        self.api.front = self.overlay.hwnd                                            # e.g. the owner got the activation back from a closed dialog
        self.pump(1)
        self.assertEqual(self.overlay.foreground_calls, [self.api.hwnd])
        self.assertEqual(self.api.front, self.api.hwnd)

    def test_a_failing_hand_back_is_bounded(self):
        self.overlay.foreground_works = False
        self.api.front = self.overlay.hwnd
        self.pump(40)
        self.assertEqual(len(self.overlay.foreground_calls), mh.HUD_FOREGROUND_RETRIES)
        self.api.front = self.api.hwnd                                                # in front elsewhere: the counter starts afresh
        self.pump(2)
        self.api.front = self.overlay.hwnd
        self.pump(2)
        self.assertEqual(len(self.overlay.foreground_calls), mh.HUD_FOREGROUND_RETRIES + 2)

    def test_errors_of_the_window_operations_are_counted_and_never_hide_the_hud(self):
        def broken(operation):
            raise OSError("invalid window handle")

        self.overlay.set_input_ownership = broken
        self.overlay.menu_state = 1
        self.pump(5)
        self.assertGreaterEqual(self.hud.input_errors, 1)
        self.assertTrue(self.overlay.visible)
        self.assertLessEqual(len(self.lines("hud-input-mode")), mh.INPUT_LINE_CAPS["hud-input-mode"])

    def test_the_log_lines_are_bounded(self):
        for _ in range(30):
            self.overlay.menu_state = 1
            self.pump(1)
            self.overlay.menu_state = 0
            self.pump(1)
        for event, cap in mh.INPUT_LINE_CAPS.items():
            self.assertLessEqual(len(self.lines(event)), cap, event)

    def test_the_summary_line_appears_only_when_the_input_ownership_was_used(self):
        self.hud.shutdown()
        self.assertEqual(self.lines("input-mode-summary"), [])
        self.setUp()
        self.overlay.menu_state = 1
        self.pump(2)
        self.overlay.menu_state = 0
        self.pump(2)
        self.hud.shutdown()
        self.assertEqual(len(self.lines("input-mode-summary")), 1)
        self.assertIn("operations=1", self.lines("input-mode-summary")[0])
        self.assertIn("returns=1", self.lines("input-mode-summary")[0])


class A2_Capability(e4.ControllerCase):
    """An Overlay or a window API without the new operations (the fakes of the older suites) behaves exactly as Phase E4: the switch does not exist."""

    def test_without_the_operations_nothing_is_called_and_nothing_fails(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.overlay.menu_state = 1                                                   # a fake that merely carries the attribute
        self.pump(20)
        self.assertEqual(self.hud.errors, 0)
        self.assertEqual(self.hud.input_modes, 0)
        self.assertTrue(self.overlay.visible)


# =====================================================================================================================================================
class FakeGui(object):
    """The win32gui / win32con / win32api functions of the Overlay's operations."""

    def __init__(self):
        self.exstyle = 0x000800A0
        self.front = 1
        self.sets = []
        self.set_foreground_ok = True
        self.attach_needed = False
        self.attached = []
        self.posts = []
        self.post_raises = False

    def GetWindowLong(self, hwnd, index):
        return self.exstyle

    def SetWindowLong(self, hwnd, index, value):
        self.sets.append(value)
        self.exstyle = value

    def GetForegroundWindow(self):
        return self.front

    def SetForegroundWindow(self, hwnd):
        if self.set_foreground_ok and (not self.attach_needed or self.attached and self.attached[-1][2]):
            self.front = hwnd
        else:
            raise OSError("access denied")

    def PostMessage(self, hwnd, message, wparam, lparam):
        if self.post_raises:
            raise OSError("invalid window handle")
        self.posts.append((hwnd, message, wparam, lparam))

    def GetWindowThreadProcessId(self, hwnd):
        return (4242, 4343)

    def AttachThreadInput(self, own, other, attach):
        self.attached.append((own, other, attach))
        return 1

    def GetCurrentThreadId(self):
        return 17


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_OverlayOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        uc.qt_app()
        import main
        import win32con
        cls.main, cls.con = main, win32con

    def setUp(self):
        self.overlay = self.main.Overlay(0)
        self.overlay.timer.stop()
        self.gui = FakeGui()
        self._saved = (self.main.win32gui, self.main.win32api)
        self.main.win32gui = self.gui
        self.main.win32api = self.gui
        import win32process
        self._process = win32process
        self._saved_process = (win32process.GetWindowThreadProcessId, win32process.AttachThreadInput)
        win32process.GetWindowThreadProcessId = self.gui.GetWindowThreadProcessId
        win32process.AttachThreadInput = self.gui.AttachThreadInput

    def tearDown(self):
        self.main.win32gui, self.main.win32api = self._saved
        self._process.GetWindowThreadProcessId, self._process.AttachThreadInput = self._saved_process
        self.overlay.user_close_handler = None
        self.overlay.close()

    def test_the_input_ownership_changes_only_the_click_through_style(self):
        base = self.gui.exstyle
        self.assertFalse(self.overlay.has_input_ownership())
        self.assertTrue(self.overlay.set_input_ownership(True))
        self.assertEqual(self.gui.exstyle, base & ~self.con.WS_EX_TRANSPARENT)
        self.assertTrue(self.overlay.has_input_ownership())
        self.assertFalse(self.overlay.set_input_ownership(True))                       # nothing to change
        self.assertTrue(self.overlay.set_input_ownership(False))
        self.assertEqual(self.gui.exstyle, base)
        self.assertEqual(len(self.gui.sets), 2)

    def test_the_foreground_is_taken_with_one_plain_call_when_that_is_allowed(self):
        self.assertTrue(self.overlay.bring_to_foreground(99))
        self.assertEqual(self.gui.front, 99)
        self.assertEqual(self.gui.attached, [])

    def test_a_window_that_is_in_front_is_left_alone(self):
        self.gui.front = 99
        self.gui.set_foreground_ok = False
        self.assertTrue(self.overlay.bring_to_foreground(99))
        self.assertEqual(self.gui.attached, [])

    def test_a_refused_call_joins_the_input_queue_of_the_front_thread_for_that_one_call(self):
        self.gui.attach_needed = True
        self.assertTrue(self.overlay.bring_to_foreground(99))
        self.assertEqual(self.gui.attached, [(17, 4242, True), (17, 4242, False)])      # joined and always detached again

    def test_a_refusal_that_stays_is_reported_and_the_queue_is_detached(self):
        self.gui.set_foreground_ok = False
        self.assertFalse(self.overlay.bring_to_foreground(99))
        self.assertEqual([a[2] for a in self.gui.attached], [True, False])

    def test_a_refused_queue_join_is_not_an_error(self):
        """A front window of a higher integrity level (e.g. an elevated application) refuses AttachThreadInput: the answer is simply "not in front"."""
        self.gui.set_foreground_ok = False

        def refuse(own, other, attach):
            raise OSError("access denied")

        self._process.AttachThreadInput = refuse
        self.assertFalse(self.overlay.bring_to_foreground(99))

    def test_the_close_request_is_one_wm_close_to_the_bve_window(self):
        self.assertTrue(self.overlay.post_close_to_bve(123))
        self.assertEqual(self.gui.posts, [(123, self.con.WM_CLOSE, 0, 0)])

    def test_a_failed_post_is_reported_not_raised(self):
        self.gui.post_raises = True
        self.assertFalse(self.overlay.post_close_to_bve(123))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class C_StepFollowsTheOverlayInFront(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        uc.qt_app()
        import main
        cls.main = main

    def test_the_game_side_is_in_front_when_bve_or_the_overlay_is(self):
        overlay = self.main.Overlay(0)
        overlay.timer.stop()
        seen = []
        overlay.adopt_bve_window = lambda hwnd: None
        overlay._run_input_and_scoring_step = lambda active: seen.append(active)
        gui = FakeGui()
        saved = self.main.win32gui
        self.main.win32gui = gui
        try:
            for front, expected in ((500, True), (int(overlay.winId()), True), (0, False), (321, False)):
                gui.front = front
                overlay.managed_window_step(500)
                self.assertEqual(seen[-1], expected, front)
        finally:
            self.main.win32gui = saved
            overlay.close()

    def test_normal_mode_still_means_bve_only(self):
        src = uc.read("main.py")
        update = uc.code_only(uc.method_source(src, "Overlay", "update_logic"))
        self.assertIn("is_bve_active = (win32gui.GetForegroundWindow() == self.bve_hwnd)", update)
        self.assertNotIn("set_input_ownership", update)
        self.assertNotIn("bring_to_foreground", update)


class D_StaticGuards(unittest.TestCase):
    def test_the_hud_module_activates_nothing_itself(self):
        hud = uc.code_only(uc.read("managed_hud.py"))
        for token in ("SetForegroundWindow", "SetFocus", "SetActiveWindow", "activateWindow", "raise_", "PostMessage", "SendMessage", "AttachThreadInput", "WS_EX_TRANSPARENT"):
            self.assertNotIn(token, hud, token)                                       # the window operations live in the Overlay (main.py): the older E4 guards stay

    def test_the_set_of_overlay_operations(self):
        import ast
        tree = ast.parse(uc.read("main.py"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
        names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue({"closeEvent", "set_input_ownership", "has_input_ownership", "bring_to_foreground", "post_close_to_bve"} <= names)

    def test_the_flags_of_the_window_are_the_same_so_the_handle_is_the_same(self):
        main_src = uc.code_only(uc.read("main.py"))
        self.assertEqual(len(re.findall(r"setWindowFlags\(", main_src)), 1)
        self.assertEqual(len(re.findall(r"setWindowFlag\(", main_src)), 0)             # the input mode never re-creates the native window through Qt flags


if __name__ == "__main__":
    unittest.main(verbosity=2)
