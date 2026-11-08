"""Phase Cursor-Q3: the cursor of the operation screens (managed mode).

    C:\\Python314\\python.exe -B -m unittest discover -s tests -p "test_operation_cursor_q3.py" -v

Root cause (Cursor-Q2, ROOT CAUSE CONFIRMED): the Overlay keeps Qt's WindowTransparentForInput, only the native WS_EX_TRANSPARENT is dropped while an operation screen
owns the input. Qt therefore never tracks the cursor over the Overlay and the cursor that BVE set last (its resize border: left-right arrows) stays. QWidget.setCursor does
not help. The contract of this phase: while an operation screen owns the input the application override cursor is the arrow, pushed ONCE when the first operation screen
opens, kept across the operation screens, popped ONCE when the HUD is complete again (never earlier, never twice, never more than this one push), and nothing outlives
the HUD / the close / the shutdown. The HUD (click-through) never holds an override: the cursor over it is BVE's.

Naming: test_red_* fail on the code before this phase (the declared reason is in the message: "Q3-RED"), test_guard_* hold before and after.
Layers: (A) the real ManagedHudController with an Overlay stand-in that carries the REAL set_input_ownership / has_input_ownership of main.Overlay (Qt offscreen, a fake
win32gui); (B) the real Overlay (close, shutdown, the save dialog); (C) static guards.
Nothing is started: no BVE, no Caller, no real window handle, no mouse or key event.
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
import managed_state as ms  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402
import test_managed_hud_input_ownership as own  # noqa: E402
import test_overlay_user_close_altf4 as uc  # noqa: E402

HAS_QT = e4.HAS_QT

F1_TOP, RETRY_LIST, RETRY_CONFIRM, ENVIRONMENT, SCORING_SETTINGS = 1, 2, 3, 4, 5
SETTING_PAGES = (6, 7, 8, 9, 10)
RESULT, ABORT_CONFIRM = 11, 12
ALL_OPERATION_STATES = tuple(range(1, 13))


def read(name):
    return uc.read(name)


class SpyApp(object):
    """Stands in for main.QApplication: counts the override-cursor calls and forwards every one to the real Qt stack."""

    def __init__(self, real):
        self._real = real
        self.sets = []            # the shape of every pushed override cursor
        self.restores = 0
        self.changes = 0

    def setOverrideCursor(self, cursor):
        self.sets.append(cursor.shape())
        self._real.setOverrideCursor(cursor)

    def restoreOverrideCursor(self):
        self.restores += 1
        self._real.restoreOverrideCursor()

    def changeOverrideCursor(self, cursor):
        self.changes += 1
        self._real.changeOverrideCursor(cursor)

    def overrideCursor(self):
        return self._real.overrideCursor()

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def balance(self):
        return len(self.sets) - self.restores


class FailingGui(own.FakeGui):
    def __init__(self):
        super().__init__()
        self.set_raises = False

    def SetWindowLong(self, hwnd, index, value):
        if self.set_raises:
            raise OSError("SetWindowLong failed")
        super().SetWindowLong(hwnd, index, value)


def drain_real_stack(app):
    """Pops everything that is on the REAL Qt override stack (test hygiene); returns how many entries there were."""
    count = 0
    while app.overrideCursor() is not None and count < 64:
        app.restoreOverrideCursor()
        count += 1
    return count


class QtCase(unittest.TestCase):
    """Qt offscreen + the spy + a fake win32gui for main.py; the real override stack is empty before and after every test."""

    @classmethod
    def setUpClass(cls):
        uc.qt_app()
        import main
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QApplication
        cls.main, cls.Qt, cls.QCursor, cls.RealApp = main, Qt, QCursor, QApplication

    def setUp(self):
        drain_real_stack(self.RealApp)
        self.spy = SpyApp(self.RealApp)
        self.gui = FailingGui()
        self._saved = (self.main.QApplication, self.main.win32gui, self.main.win32api)
        self.main.QApplication = self.spy
        self.main.win32gui = self.gui
        self.main.win32api = self.gui
        self.arrow = self.Qt.CursorShape.ArrowCursor

    def tearDown(self):
        self.main.QApplication, self.main.win32gui, self.main.win32api = self._saved
        leftover = drain_real_stack(self.RealApp)
        self.leftover = leftover

    # -- assertions ----------------------------------------------------------------------------------------------------------------------
    def assert_no_override(self, why=""):
        self.assertIsNone(self.RealApp.overrideCursor(), "Q3-RED: an override cursor is on the stack %s" % why)

    def assert_arrow_override(self, why=""):
        top = self.RealApp.overrideCursor()
        self.assertIsNotNone(top, "Q3-RED: no override cursor while an operation screen owns the input %s" % why)
        self.assertEqual(top.shape(), self.arrow, "Q3-RED: the override cursor is not the arrow %s" % why)

    def assert_stack(self, pushes, restores, why=""):
        self.assertEqual((len(self.spy.sets), self.spy.restores), (pushes, restores), "Q3-RED: override pushes/restores %s" % why)


def borrowed(name):
    return getattr(sys.modules["main"].Overlay, name, None) if "main" in sys.modules else None


class CursorOverlay(uc.UserOverlay):
    """The Overlay stand-in of the controller tests that carries the REAL input-ownership operations (and, when the phase exists, the real cursor operations) of
    main.Overlay, running on a fake win32gui. It is the production code of the switch, driven by the production controller."""

    def __init__(self, main):
        super().__init__()
        self.bound = []
        for name in ("set_input_ownership", "has_input_ownership", "release_operation_cursor", "suspend_operation_cursor", "resume_operation_cursor",
                     "_sync_operation_cursor"):
            fn = getattr(main.Overlay, name, None)
            if fn is not None:
                setattr(self, name, fn.__get__(self))
                self.bound.append(name)
        for name in ("_operation_cursor_override_active", "_operation_cursor_owned", "_operation_cursor_suspended"):
            if hasattr(main.Overlay, name):
                setattr(self, name, getattr(main.Overlay, name))
        self.ownership_calls = []
        real_set = self.set_input_ownership

        def recording_set(operation):
            self.ownership_calls.append(bool(operation))
            return real_set(operation)

        self.set_input_ownership = recording_set


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class A_Controller(QtCase):
    """The production controller driving the production switch: the operation screens are the states of menu_state."""

    def setUp(self):
        super().setUp()
        e4.FakeOverlay.created = 0
        self.args = e4.args_for()
        self.log = e4.Log()
        self.source = e4.FakeSource(e4.make_block(self.args.bve_pid, self.args.instance))
        self.reader = ms.StateReader(self.args, self.source, self.log)
        self.overlay = CursorOverlay(self.main)
        self.timer = e4.FakeTimer()
        self.api = uc.UserApi()
        self.overlay.z_api = self.api
        self.overlay.api = self.api
        self.clock = e4.Clock()
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: None, timer=self.timer, clock=self.clock)
        self.count = 0
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.assertTrue(self.hud.shown)
        self.api.front = self.api.hwnd

    def publish(self, session=False, driving=False, generation=0, closed=False):
        self.count += 1
        self.source.data = e4.make_block(self.args.bve_pid, self.args.instance, session, driving, closed, generation, self.count)

    def pump(self, ticks=1):
        for _ in range(ticks):
            self.clock.t += 0.02
            self.hud.tick()

    def show_state(self, state, ticks=2):
        self.overlay.menu_state = state
        self.pump(ticks)

    # -- 1, 18 the normal HUD -------------------------------------------------------------------------------------------------------------
    def test_guard_01_the_normal_hud_holds_no_override_cursor(self):
        self.pump(60)
        self.assert_stack(0, 0, "on the normal HUD")
        self.assertIsNone(self.RealApp.overrideCursor())

    def test_guard_18_the_normal_hud_never_forces_a_cursor_over_what_bve_set(self):
        self.pump(10)
        self.show_state(F1_TOP)
        self.show_state(0)
        self.pump(60)                                                                  # the HUD again: whatever BVE sets is what the user sees
        self.assertIsNone(self.RealApp.overrideCursor())
        self.assertEqual(self.spy.changes, 0)

    # -- 2, 3 entering --------------------------------------------------------------------------------------------------------------------
    def test_red_02_an_operation_screen_forces_the_arrow(self):
        self.show_state(F1_TOP)
        self.assert_arrow_override("after the F1 top screen opened")
        self.assert_stack(1, 0, "after the F1 top screen opened")

    def test_red_03_redrawing_the_same_screen_does_not_stack_overrides(self):
        self.show_state(F1_TOP, ticks=1)
        self.pump(200)
        self.assert_stack(1, 0, "after 200 ticks of the same screen")
        self.overlay.menu_state = F1_TOP
        for _ in range(20):
            self.overlay.set_input_ownership(True)                                    # what a re-created window makes _enter_operation do
        self.assert_stack(1, 0, "after repeated set_input_ownership(True)")

    # -- 4, 5, 6, 7, 8, 17 the operation screens among themselves -------------------------------------------------------------------------
    def test_red_04_f1_top_to_the_scoring_settings_keeps_the_override(self):
        self.show_state(F1_TOP)
        self.show_state(SCORING_SETTINGS)
        self.assert_arrow_override("in the scoring settings")
        self.assert_stack(1, 0, "F1 top -> scoring settings")

    def test_red_05_every_page_of_the_scoring_settings_keeps_the_override(self):
        self.show_state(F1_TOP)
        self.show_state(SCORING_SETTINGS)
        for page in (6, 9, 6, SCORING_SETTINGS, 8, SCORING_SETTINGS, 7, SCORING_SETTINGS, 10, SCORING_SETTINGS):
            self.show_state(page)
            self.assert_arrow_override("on page %d" % page)
        self.assert_stack(1, 0, "page changes of the scoring settings")

    def test_red_06_the_retry_list_shows_the_arrow(self):
        self.show_state(F1_TOP)
        self.show_state(RETRY_LIST)
        self.assert_arrow_override("in the retry list")
        self.assert_stack(1, 0, "retry list")

    def test_red_07_the_confirmation_screens_show_the_arrow(self):
        self.show_state(F1_TOP)
        for state in (RETRY_LIST, RETRY_CONFIRM, RETRY_LIST, ABORT_CONFIRM, ENVIRONMENT):
            self.show_state(state)
            self.assert_arrow_override("in state %d" % state)
        self.assert_stack(1, 0, "confirmation screens")

    def test_red_08_the_result_screen_shows_the_arrow(self):
        self.show_state(F1_TOP)
        self.show_state(RESULT)
        self.assert_arrow_override("on the result screen")
        self.assert_stack(1, 0, "result screen")

    def test_red_17_no_restore_happens_between_operation_screens(self):
        self.show_state(F1_TOP)
        for state in ALL_OPERATION_STATES:
            self.show_state(state)
        self.assert_stack(1, 0, "after visiting every operation state")
        self.assert_arrow_override("after visiting every operation state")

    # -- 9, 10 back to the HUD ------------------------------------------------------------------------------------------------------------
    def test_red_09_backspace_back_to_the_hud_restores_once(self):
        self.show_state(F1_TOP)
        self.show_state(SCORING_SETTINGS)
        self.show_state(0, ticks=5)                                                    # Bksp / close of the top screen
        self.assert_stack(1, 1, "after the HUD is complete again")
        self.assert_no_override("after the HUD is complete again")
        self.pump(50)
        self.assert_stack(1, 1, "50 HUD ticks later")

    def test_red_10_scoring_start_and_retry_completion_return_to_the_hud_with_one_restore(self):
        for path in ((F1_TOP, SCORING_SETTINGS, 6, 9, 6, SCORING_SETTINGS), (F1_TOP, RETRY_LIST, RETRY_CONFIRM)):
            self.setUp()
            for state in path:
                self.show_state(state)
            self.show_state(0, ticks=5)                                               # the scoring start / the accepted retry closes the menu (menu_state = 0)
            self.assert_stack(1, 1, "path %s" % (path,))
            self.assert_no_override("after path %s" % (path,))

    def test_red_10b_a_hundred_round_trips_neither_pile_up_nor_leak(self):
        for _ in range(100):
            self.show_state(F1_TOP, ticks=1)
            self.show_state(SCORING_SETTINGS, ticks=1)
            self.show_state(0, ticks=2)
        self.assert_stack(100, 100, "100 round trips")
        self.assert_no_override("after 100 round trips")

    # -- 12 the HUD goes away while an operation screen is open ----------------------------------------------------------------------------
    def test_red_12_input_device_off_session_end_and_pause_leave_no_override(self):
        for session, driving in ((True, False), (False, False)):
            self.setUp()
            self.show_state(RESULT)
            self.assert_arrow_override("before the HUD goes away")
            self.publish(session, driving, 1)                                          # Driving OFF (pause) / Session OFF (Input Device soft OFF, scenario end)
            self.pump(5)
            self.assertFalse(self.overlay.visible)
            self.assert_stack(1, 1, "session=%s driving=%s" % (session, driving))
            self.assert_no_override("session=%s driving=%s" % (session, driving))

    def test_red_12b_the_stop_of_the_caller_leaves_no_override(self):
        self.show_state(F1_TOP)
        self.assert_arrow_override("before the stop")
        self.hud.set_stop_probe(lambda: True)
        self.hud.shutdown()
        self.assert_stack(1, 1, "after the stop")
        self.assert_no_override("after the stop")
        self.hud.shutdown()
        self.assert_stack(1, 1, "after a second shutdown")

    def test_red_12c_bve_window_gone_leaves_no_override(self):
        self.show_state(F1_TOP)
        self.api.alive = False                                                         # BVE ended / its window is gone: the HUD is unlinked and hidden
        self.pump(5)
        self.assert_stack(1, 1, "after BVE's window is gone")
        self.assert_no_override("after BVE's window is gone")

    def test_red_12d_an_operation_screen_left_by_a_failed_style_change_still_releases_the_cursor(self):
        self.show_state(F1_TOP)
        self.gui.set_raises = True                                                     # the style cannot be written when the HUD is to be click-through again
        self.show_state(0, ticks=3)
        self.assert_stack(1, 1, "although SetWindowLong failed")
        self.assert_no_override("although SetWindowLong failed")
        self.gui.set_raises = False
        self.pump(10)
        self.assert_stack(1, 1, "when the style could be written again")

    # -- 14 an exception inside the controller's own work -----------------------------------------------------------------------------------
    def test_red_14_a_failing_tick_in_an_operation_screen_does_not_keep_the_override_after_the_shutdown(self):
        self.show_state(F1_TOP)
        self.assert_arrow_override("before the failure")

        def broken(_overlay):
            raise RuntimeError("update step failed")

        self.hud._update_step = broken
        self.pump(5)
        self.hud.shutdown()
        self.assert_no_override("after a failing step and the shutdown")
        self.assert_stack(1, 1, "after a failing step and the shutdown")

    # -- 16 the guards of the push / pop ----------------------------------------------------------------------------------------------------
    def test_guard_16_leaving_without_an_operation_screen_restores_nothing(self):
        for _ in range(5):
            self.overlay.set_input_ownership(False)
        self.pump(10)
        self.assertEqual(self.spy.restores, 0)
        self.assertEqual(self.spy.sets, [])

    def test_red_16b_a_foreign_override_is_never_popped_by_the_hud(self):
        self.RealApp.setOverrideCursor(self.QCursor(self.Qt.CursorShape.WaitCursor))   # another feature's override, pushed first
        self.show_state(F1_TOP)
        self.show_state(0, ticks=3)
        self.assert_stack(1, 1, "with a foreign override under ours")
        self.assertIsNotNone(self.RealApp.overrideCursor(), "Q3-RED: the foreign override was popped")
        self.assertEqual(self.RealApp.overrideCursor().shape(), self.Qt.CursorShape.WaitCursor)
        for _ in range(4):
            self.overlay.set_input_ownership(False)
        self.assertEqual(self.RealApp.overrideCursor().shape(), self.Qt.CursorShape.WaitCursor, "Q3-RED: the foreign override was popped by a repeated HUD step")

    # -- the contracts around it stay -------------------------------------------------------------------------------------------------------
    def test_guard_input_ownership_and_foreground_contract_unchanged(self):
        self.show_state(F1_TOP, ticks=1)
        self.assertEqual(self.overlay.ownership_calls[0], True)
        self.assertTrue(self.overlay.has_input_ownership())
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd])
        self.show_state(0, ticks=2)
        self.assertEqual(self.overlay.ownership_calls[-1], False)
        self.assertFalse(self.overlay.has_input_ownership())
        self.assertEqual(self.overlay.foreground_calls, [self.overlay.hwnd, self.api.hwnd])
        self.assertEqual(self.hud.input_errors, 0)

    def test_guard_the_style_changes_only_the_click_through_bit(self):
        base = self.gui.exstyle
        self.show_state(F1_TOP, ticks=1)
        self.assertEqual(self.gui.exstyle, base & ~self.main.win32con.WS_EX_TRANSPARENT)
        self.show_state(0, ticks=2)
        self.assertEqual(self.gui.exstyle, base)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_RealOverlay(QtCase):
    """The real Overlay (offscreen): close, the shutdown of the process, the Alt+F4 close, the save dialog."""

    def setUp(self):
        super().setUp()
        from PyQt6.QtGui import QCloseEvent

        class SpontaneousClose(QCloseEvent):
            def spontaneous(self):
                return True

        self.Spontaneous, self.QCloseEvent = SpontaneousClose, QCloseEvent
        self.overlay = self.main.Overlay(0)
        self.overlay.timer.stop()
        self.overlay.show()
        self._closed = False

    def tearDown(self):
        self.overlay.user_close_handler = None
        self.overlay.close()
        super().tearDown()

    # -- 11 Alt+F4 --------------------------------------------------------------------------------------------------------------------------
    def test_red_11_alt_f4_keeps_the_screen_and_the_arrow_until_the_shutdown_removes_both(self):
        asked = []
        self.overlay.user_close_handler = lambda: asked.append(1)
        self.overlay.set_input_ownership(True)
        self.assert_arrow_override("in the operation screen")
        event = self.Spontaneous()
        self.overlay.closeEvent(event)                                               # Alt+F4: ignored, BVE is asked to end, the window stays as it is
        self.assertFalse(event.isAccepted())
        self.assertEqual(asked, [1])
        self.assert_arrow_override("the screen is still open after Alt+F4")
        self.assert_stack(1, 0, "after Alt+F4")
        self.overlay.user_close_handler = None                                       # the shutdown of the process (BVE ended, the Caller's Stop)
        self.overlay.close()
        self.assert_no_override("after the process closed the Overlay")
        self.assert_stack(1, 1, "after the process closed the Overlay")

    def test_guard_alt_f4_contract_the_user_close_is_still_ignored_and_asks_bve(self):
        asked = []
        self.overlay.user_close_handler = lambda: asked.append(1)
        event = self.Spontaneous()
        self.overlay.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(asked, [1])
        self.assertTrue(self.overlay.isVisible())

    # -- 13 the end of the Python process / 14 exceptions / disposal --------------------------------------------------------------------------
    def test_red_13_the_managed_cleanup_leaves_no_override(self):
        class Hud(object):
            def shutdown(self):
                pass                                                                   # a controller that did not release (or already forgot) the operation screen

        self.overlay.set_input_ownership(True)
        self.assert_arrow_override("before the cleanup")
        self.main._release_overlay(self.overlay, Hud())
        self.assert_no_override("after _release_overlay")
        self.assert_stack(1, 1, "after _release_overlay")

    def test_red_13b_the_cleanup_releases_the_cursor_itself_not_only_through_the_close_event(self):
        class Hud(object):
            def shutdown(self):
                pass

        self.overlay.set_input_ownership(True)
        self.overlay.close = lambda: None                                            # a close that never reaches closeEvent (the window is already gone)
        try:
            self.main._release_overlay(self.overlay, Hud())
        finally:
            del self.overlay.close
        self.assert_no_override("after _release_overlay without a closeEvent")
        self.assert_stack(1, 1, "after _release_overlay without a closeEvent")

    def test_red_14b_a_failing_controller_shutdown_does_not_keep_the_override(self):
        class Hud(object):
            def shutdown(self):
                raise RuntimeError("shutdown failed")

        self.overlay.set_input_ownership(True)
        self.main._release_overlay(self.overlay, Hud())
        self.assert_no_override("after a failing controller shutdown")
        self.assert_stack(1, 1, "after a failing controller shutdown")

    def test_red_14c_a_second_close_pops_nothing_more(self):
        self.RealApp.setOverrideCursor(self.QCursor(self.Qt.CursorShape.WaitCursor))
        self.overlay.set_input_ownership(True)
        self.overlay.close()
        self.overlay.close()
        self.overlay.closeEvent(self.QCloseEvent())
        self.assert_stack(1, 1, "after repeated closes")
        self.assertIsNotNone(self.RealApp.overrideCursor(), "Q3-RED: the foreign override was popped")
        self.assertEqual(self.RealApp.overrideCursor().shape(), self.Qt.CursorShape.WaitCursor)

    def test_guard_the_normal_mode_overlay_never_touches_the_cursor_stack(self):
        self.overlay.show()
        self.overlay.close()
        self.overlay.closeEvent(self.QCloseEvent())
        self.assertEqual((self.spy.sets, self.spy.restores, self.spy.changes), ([], 0, 0))

    # -- 15 the save dialog -------------------------------------------------------------------------------------------------------------------
    def _ask_dialog(self, inspect):
        import managed_input
        from PyQt6.QtCore import QTimer
        managed_input.attach_result_dialog(self.overlay)
        seen = {}

        def during():
            seen["top"] = self.RealApp.overrideCursor()
            seen["sets"], seen["restores"] = len(self.spy.sets), self.spy.restores
            if inspect:
                inspect(seen)
            self.overlay.close_result_dialog()

        QTimer.singleShot(100, during)
        answer = self.overlay.ask_result_save_path(os.path.join(ROOT, "x.jpg"))
        return answer, seen

    def test_red_15_the_save_dialog_leaves_the_stack_as_it_found_it(self):
        self.overlay.set_input_ownership(True)
        self.assert_stack(1, 0, "before the dialog")
        answer, seen = self._ask_dialog(None)
        self.assertEqual(answer, "")
        self.assert_arrow_override("after the dialog closed (the result screen is still open)")
        self.assertEqual(self.spy.balance, 1, "Q3-RED: the stack is not symmetric around the dialog")
        self.overlay.set_input_ownership(False)
        self.assert_no_override("after the result screen closed")
        self.assert_stack(len(self.spy.sets), len(self.spy.sets), "after the result screen closed")

    def test_guard_15b_the_dialog_keeps_the_cursors_of_its_own_while_it_is_open(self):
        self.overlay.set_input_ownership(True)
        answer, seen = self._ask_dialog(None)
        self.assertIsNone(seen["top"], "the arrow is forced onto the save dialog (no text cursor in the file name field)")

    def test_red_15c_a_dialog_that_raises_still_gives_the_stack_back(self):
        import managed_input
        from PyQt6.QtWidgets import QFileDialog
        self.overlay.set_input_ownership(True)
        managed_input.attach_result_dialog(self.overlay)
        def boom(dialog):
            raise RuntimeError("exec failed")

        QFileDialog.exec = boom
        try:
            with self.assertRaises(RuntimeError):
                self.overlay.ask_result_save_path(os.path.join(ROOT, "x.jpg"))
        finally:
            del QFileDialog.exec                                                     # (back to the inherited QDialog.exec)
        self.assert_arrow_override("after a failing dialog")
        self.assertEqual(self.spy.balance, 1, "Q3-RED: the stack is not symmetric after a failing dialog")
        self.overlay.set_input_ownership(False)
        self.assert_no_override("after the screen closed")

    def test_red_15d_the_stop_that_closes_the_dialog_leaves_no_override(self):
        self.overlay.set_input_ownership(True)
        self.assert_arrow_override("before the dialog")

        def stop(seen):
            self.overlay.set_input_ownership(False)                                  # the controller's shutdown hides the Overlay while the dialog still runs

        answer, seen = self._ask_dialog(stop)
        self.assert_no_override("after the stop closed the dialog")
        self.assertEqual(self.spy.balance, 0, "Q3-RED: the stack is not symmetric when the stop closes the dialog")

    def test_guard_the_dialog_without_an_operation_screen_touches_nothing(self):
        answer, seen = self._ask_dialog(None)
        self.assertEqual((self.spy.sets, self.spy.restores), ([], 0))

    # -- 18 the HUD over BVE's cursor ----------------------------------------------------------------------------------------------------------
    def test_guard_18b_the_hud_overlay_has_no_cursor_of_its_own(self):
        self.assertFalse(self.overlay.testAttribute(self.Qt.WidgetAttribute.WA_SetCursor))
        self.overlay.set_input_ownership(True)
        self.overlay.set_input_ownership(False)
        self.assertFalse(self.overlay.testAttribute(self.Qt.WidgetAttribute.WA_SetCursor), "the Overlay itself got a cursor (QWidget.setCursor is not the fix)")


class C_StaticGuards(unittest.TestCase):
    def test_guard_the_override_has_one_push_and_one_pop_in_main_py(self):
        main_src = uc.code_only(read("main.py"))
        self.assertLessEqual(len(re.findall(r"setOverrideCursor\(", main_src)), 1)
        self.assertLessEqual(len(re.findall(r"restoreOverrideCursor\(", main_src)), 1)
        self.assertEqual(len(re.findall(r"changeOverrideCursor\(", main_src)), 0)
        self.assertEqual(len(re.findall(r"\.setCursor\(|unsetCursor\(", main_src)), 0)

    def test_red_the_cursor_is_owned_by_the_overlay_next_to_the_input_ownership(self):
        main_src = read("main.py")
        self.assertEqual(len(re.findall(r"setOverrideCursor\(", uc.code_only(main_src))), 1, "Q3-RED: no override cursor push in main.py")
        self.assertEqual(len(re.findall(r"restoreOverrideCursor\(", uc.code_only(main_src))), 1, "Q3-RED: no override cursor pop in main.py")
        self.assertIn("Qt.CursorShape.ArrowCursor", main_src)
        body = uc.code_only(uc.method_source(main_src, "Overlay", "set_input_ownership"))
        self.assertIn("_operation_cursor", body, "Q3-RED: set_input_ownership does not drive the operation cursor")

    def test_guard_the_hud_controller_and_the_dialog_module_do_not_use_the_override_directly(self):
        for name in ("managed_hud.py", "managed_state.py", "managed_mode.py", "telemetry_gate.py"):
            self.assertNotRegex(uc.code_only(read(name)), r"OverrideCursor|QCursor|setCursor", name)

    def test_guard_the_window_flags_and_the_input_contract_tokens_are_unchanged(self):
        main_src = uc.code_only(read("main.py"))
        self.assertIn("self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)", main_src)
        self.assertEqual(len(re.findall(r"setWindowFlags\(", main_src)), 1)
        self.assertEqual(len(re.findall(r"setWindowFlag\(", main_src)), 0)
        self.assertNotIn("nativeEvent", main_src)
        self.assertNotIn("WM_NCHITTEST", main_src)
        self.assertEqual(len(re.findall(r"post_close_to_bve", main_src)), 1)
        self.assertEqual(len(re.findall(r"WM_CLOSE", main_src)), 1)

    def test_guard_the_night_b_f2_display_is_not_touched_by_this_phase(self):
        """Night B (Shadow comparison) changes the F2 four-value display and the telemetry intake; this phase only touches the input ownership / close / dialog."""
        main_src = read("main.py")
        for method in ("set_input_ownership", "closeEvent"):
            self.assertNotRegex(uc.code_only(uc.method_source(main_src, "Overlay", method)), r"bve_accel_z|bve_g|max_stop_g|CalcG|BveG", method)
        hud_src = uc.code_only(read("hud_ui.py"))
        self.assertNotRegex(hud_src, r"OverrideCursor|_operation_cursor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
