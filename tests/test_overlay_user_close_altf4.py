"""Phase UI-ALT-F4: a close that the USER asks for (Alt+F4 while the Overlay is in front) asks BVE to end; the Overlay is neither hidden nor destroyed.

    C:\\Python314\\python.exe -B -m unittest discover -s tests -p "test_overlay_user_close_altf4.py" -v

Layers: (A) characterization - what holds before and after the change (the flags of the Overlay, the save dialog, a close of the program, the F11 hold of the Caller,
the Input Device OFF path); (B) the contract with a real Overlay (offscreen) and the real controller against fakes: one close request, latch, reasons, F11 and cleanup
invariants; (C) real windows (Windows desktop): spontaneous() on a real HWND and the whole chain with a stand-in BVE process that counts WM_CLOSE.
(C) takes no foreground (see tests/overlay_input_ownership_real_check.py); the foreground variant runs only with TS_REAL_FOREGROUND=1.
No BVE, no BveEX, no Caller is started; nothing is typed and no mouse event is sent.
"""
import ast
import inspect
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import managed_hud as mh  # noqa: E402
import managed_state as ms  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402

HAS_QT = e4.HAS_QT
_APP = []


def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(["altf4"])
        _APP.append(app)
    return app


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def code_only(text):
    return re.sub(r"#.*", "", re.sub(r'"""[\s\S]*?"""', "", text))


def method_source(text, cls, name):
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    fn = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, fn)


# -- fakes ---------------------------------------------------------------------------------------------------------------------------------
class UserOverlay(e4.FakeOverlay):
    """The Overlay of the HUD controller tests with the Overlay methods of this phase: the input ownership, the foreground and the close request to BVE."""

    def __init__(self):
        super().__init__()
        self.menu_state = 0
        self.ownership = False
        self.ownership_calls = []
        self.foreground_calls = []
        self.foreground_works = True
        self.posts = []
        self.post_works = True
        self.api = None
        self.user_close_handler = None
        self.calls = []                        # everything the user close path must NOT do (see test_the_user_close_path_restores_closes_and_quits_nothing)

    def set_input_ownership(self, operation):
        self.ownership_calls.append(bool(operation))
        changed = self.ownership != bool(operation)
        self.ownership = bool(operation)
        return changed

    def has_input_ownership(self):
        return self.ownership

    def bring_to_foreground(self, hwnd):
        self.foreground_calls.append(hwnd)
        if self.foreground_works and self.api is not None:
            self.api.front = hwnd
        return self.foreground_works

    def post_close_to_bve(self, hwnd):
        self.posts.append(hwnd)
        return self.post_works

    def restore_bve_window(self):
        self.calls.append("restore_bve_window")

    def close(self):
        self.calls.append("close")
        super().close()


class UserApi(e4.FakeWindowApi):
    def __init__(self):
        super().__init__()
        self.front = 0

    def foreground_window(self):
        return self.front


class UserCase(unittest.TestCase):
    def setUp(self):
        e4.FakeOverlay.created = 0
        self.args = e4.args_for()
        self.log = e4.Log()
        self.source = e4.FakeSource(e4.make_block(self.args.bve_pid, self.args.instance))
        self.reader = ms.StateReader(self.args, self.source, self.log)
        self.overlay = UserOverlay()
        self.timer = e4.FakeTimer()
        self.api = UserApi()
        self.overlay.z_api = self.api
        self.overlay.api = self.api
        self.clock = e4.Clock()
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: None, timer=self.timer, clock=self.clock)
        self.count = 0
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.assertTrue(self.hud.shown)
        self.api.front = self.api.hwnd           # BVE is in front, as in normal driving

    def publish(self, session=False, driving=False, generation=0, closed=False):
        self.count += 1
        self.source.data = e4.make_block(self.args.bve_pid, self.args.instance, session, driving, closed, generation, self.count)

    def pump(self, ticks=1):
        for _ in range(ticks):
            self.clock.t += 0.02
            self.hud.tick()

    def lines(self, event):
        return self.log.events(event)


# =====================================================================================================================================================
class A_Characterization(unittest.TestCase):
    """CH-01..CH-09: what is true before and after this phase."""

    def test_ch01_the_overlay_is_a_click_through_tool_window_by_flags(self):
        main_src = code_only(read("main.py"))
        self.assertIn("self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)", main_src)
        self.assertIn("self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)", main_src)

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_ch02_ch03_the_save_dialog_belongs_to_the_overlay_but_its_close_is_not_a_close_of_the_overlay(self):
        qt_app()
        from PyQt6.QtCore import QEvent, QObject, QTimer
        from PyQt6.QtWidgets import QFileDialog
        import main
        import managed_input

        class Probe(QObject):
            def __init__(self):
                super().__init__()
                self.closes = 0

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Close:
                    self.closes += 1
                return False

        overlay = main.Overlay(0)
        overlay.timer.stop()
        handler_calls = []
        overlay.user_close_handler = lambda: handler_calls.append(1)
        probe = Probe()
        overlay.installEventFilter(probe)
        managed_input.attach_result_dialog(overlay)
        seen = {}

        def inspect_and_close():
            dialog = overlay.result_dialog
            seen["parent_is_overlay"] = dialog.parent() is overlay
            seen["non_native"] = dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
            overlay.close_result_dialog()

        try:
            overlay.show()
            QTimer.singleShot(100, inspect_and_close)
            self.assertEqual(overlay.ask_result_save_path(os.path.join(ROOT, "x.jpg")), "")
            self.assertEqual(seen, {"parent_is_overlay": True, "non_native": True})
            self.assertEqual(probe.closes, 0)                                   # the dialog's reject() never reaches the Overlay's closeEvent
            self.assertEqual(handler_calls, [])
            self.assertTrue(overlay.isVisible())
        finally:
            overlay.user_close_handler = None
            overlay.close()

    def test_ch04_ch05_show_and_hide_are_idempotent_and_the_tick_orders_show_owner_z(self):
        src = code_only(read("managed_hud.py"))
        show = src[src.index("    def _show(self):"):src.index("    def _hide(self")]
        self.assertIn("if self._shown:\n            return False", show)
        hide = src[src.index("    def _hide(self"):src.index("    def _set_interval")]
        self.assertIn("if not self._shown:\n            return", hide)
        tick = src[src.index("    def _tick_active(self):"):src.index("    def _tick_waiting_input(self):")]
        self.assertLess(tick.index("shown_now = self._show()"), tick.index("self._ensure_owner()"))
        self.assertLess(tick.index("self._ensure_owner()"), tick.index("self._ensure_z_order()"))

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_ch06_a_close_of_the_program_is_a_default_close_with_and_without_a_handler(self):
        qt_app()
        import main
        for handler in (None, lambda: self.fail("a close of the program must not reach the user close handler")):
            overlay = main.Overlay(0)
            overlay.timer.stop()
            overlay.user_close_handler = handler
            overlay.show()
            self.assertTrue(overlay.isVisible())
            overlay.close()                                                      # overlay.close() of the shutdown is not spontaneous
            self.assertFalse(overlay.isVisible())

    def test_ch07_the_f11_restore_is_done_only_by_the_restore_request_slot(self):
        src = read("main.py")
        slot = method_source(src, "_ManagedShutdownBridge", "on_f11_restore_requested")
        self.assertLess(slot.index("overlay.restore_bve_window()"), slot.index("control.set_fullscreen(False)"))
        self.assertLess(slot.index("control.set_fullscreen(False)"), slot.index("control.complete_restore()"))
        for token in ("restore_bve_window", "set_fullscreen", "complete_restore"):
            self.assertNotIn(token, code_only(read("managed_hud.py")))                           # the HUD controller never restores or toggles the BVE window
        self.assertEqual(len(re.findall(r"\.restore_bve_window\(", code_only(src))), 1)          # main.py calls it from this slot only (the shutdown's call is in managed_input)

    def test_ch08_the_close_hold_of_the_caller_is_unchanged(self):
        src = read(os.path.join("TsScoringPlugin", "Handshake", "Caller", "src", "BveWindowMessageObserver.cs"))
        for token in ("allowCloseOnce", "F11_A2_CLOSE_SUPPRESSED", "reason=already-waiting", "F11_A2_CLOSE_PASSTHROUGH", "F11_A2_RESTORE_REQUESTED", "F11_A2_CLOSE_REPOSTED",
                      "if (message.Msg == WM_CLOSE && HandleClose())"):
            self.assertIn(token, src, token)
        diff = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", "HEAD", "--", "TsScoringPlugin"], capture_output=True, text=True)
        if diff.returncode == 0:
            changed = [p for p in diff.stdout.split() if not p.endswith("Test-JumpProbeB1.ps1")]
            self.assertEqual(changed, [], "this phase changes no C#")

    def test_ch09_neither_the_off_path_nor_the_shutdown_sends_a_close_to_bve(self):
        """TS Scoring OFF (the Caller resets Enabled and stops this process) and every shutdown path end this process only: BVE keeps running."""
        for name in ("managed_mode.py", "managed_input.py", "managed_state.py", "pause_recovery.py", "managed_app_directory.py"):
            self.assertNotIn("WM_CLOSE", code_only(read(name)), name)
        main_src = read("main.py")
        for cls, name in (("_ManagedShutdownBridge", "on_shutdown_requested"), ("_ManagedShutdownBridge", "on_f11_restore_requested")):
            body = code_only(method_source(main_src, cls, name))
            self.assertNotIn("WM_CLOSE", body)
            self.assertNotIn("post_close", body)
        release = main_src[main_src.index("def _release_overlay"):main_src.index("def _open_managed_app_directory")]
        self.assertNotIn("WM_CLOSE", code_only(release))
        self.assertNotIn("post_close", code_only(release))


# =====================================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_RealOverlayCloseEvent(unittest.TestCase):
    """RED-01 / RED-04 / RED-16 with the real Overlay (offscreen): the decision of closeEvent."""

    @classmethod
    def setUpClass(cls):
        qt_app()
        import main
        from PyQt6.QtGui import QCloseEvent

        class SpontaneousClose(QCloseEvent):
            """What Windows delivers for Alt+F4: spontaneous() is True (proved on a real HWND by C_RealWindows)."""

            def spontaneous(self):
                return True

        cls.main, cls.Spontaneous, cls.QCloseEvent = main, SpontaneousClose, QCloseEvent

    def setUp(self):
        self.overlay = self.main.Overlay(0)
        self.overlay.timer.stop()
        self.overlay.show()

    def tearDown(self):
        self.overlay.user_close_handler = None
        self.overlay.close()

    def test_red01_a_close_of_the_user_is_ignored_and_the_overlay_stays(self):
        calls = []
        self.overlay.user_close_handler = lambda: calls.append(1)
        window = int(self.overlay.winId())
        event = self.Spontaneous()
        self.overlay.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.overlay.isVisible())
        self.assertEqual(int(self.overlay.winId()), window)
        self.assertEqual(calls, [1])

    def test_red04_a_close_of_the_program_is_accepted_without_the_handler(self):
        calls = []
        self.overlay.user_close_handler = lambda: calls.append(1)
        event = self.QCloseEvent()
        self.overlay.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(calls, [])

    def test_a_user_close_without_a_handler_is_the_default_close_normal_mode(self):
        self.assertIsNone(self.main.Overlay.user_close_handler)
        event = self.Spontaneous()
        self.overlay.closeEvent(event)
        self.assertTrue(event.isAccepted())

    def test_a_failing_handler_never_raises_out_of_close_event(self):
        def broken():
            raise RuntimeError("handler failed")

        self.overlay.user_close_handler = broken
        event = self.Spontaneous()
        self.overlay.closeEvent(event)                                  # (an exception here would end the managed process through its excepthook)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.overlay.isVisible())

    def test_red16_the_close_event_exists_and_the_normal_mode_entry_is_unchanged(self):
        src = read("main.py")
        self.assertIn("def closeEvent(self, event):", method_source(src, "Overlay", "closeEvent"))
        body = "".join(line.strip() for line in inspect.getsource(self.main._run_normal).splitlines()[1:])
        self.assertEqual(body, "app = QApplication(sys.argv)overlay = Overlay()overlay.show()return app.exec()")
        self.assertNotIn("user_close_handler", code_only(inspect.getsource(self.main._run_normal)))


# =====================================================================================================================================================
class B_RequestUserClose(UserCase):
    """RED-02, 03, 05, 06, 07, 08: the controller's one request to BVE."""

    def wire(self):
        self.overlay.user_close_handler = self.hud.request_user_close

    def test_red02_one_close_request_goes_to_the_bve_window(self):
        self.assertEqual(self.hud.request_user_close(), "sent")
        self.assertEqual(self.overlay.posts, [self.api.hwnd])
        self.assertEqual(self.lines("hud-user-close")[0].split("pid=")[1].split(" ", 1)[1], "sent=1")

    def test_red03_three_closes_make_one_request_and_two_skips(self):
        outcomes = [self.hud.request_user_close() for _ in range(3)]
        self.assertEqual(outcomes, ["sent", "already-sent", "already-sent"])
        self.assertEqual(len(self.overlay.posts), 1)
        skips = [line for line in self.lines("hud-user-close") if "reason=already-sent" in line]
        self.assertEqual(len(skips), 2)
        self.assertTrue(self.overlay.visible)                         # the Overlay is never hidden by the request

    def test_red03b_the_latch_is_not_re_armed_when_bve_does_not_close(self):
        self.hud.request_user_close()
        self.pump(200)                                                # BVE (the fake) never closes; many ticks later the user tries again
        self.assertEqual(self.hud.request_user_close(), "already-sent")
        self.assertEqual(len(self.overlay.posts), 1)

    def test_red05_nothing_is_sent_while_the_process_ends(self):
        self.hud.set_stop_probe(lambda: True)
        self.assertEqual(self.hud.request_user_close(), "stopping")
        self.assertEqual(self.overlay.posts, [])
        self.assertIn("reason=stopping", self.lines("hud-user-close")[0])
        self.assertTrue(self.overlay.visible)

    def test_red05b_nothing_is_sent_after_the_controller_shut_down(self):
        self.hud.shutdown()
        self.assertEqual(self.hud.request_user_close(), "stopping")
        self.assertEqual(self.overlay.posts, [])

    def test_red05c_a_failing_stop_probe_does_not_break_the_request(self):
        def broken():
            raise RuntimeError("probe")

        self.hud.set_stop_probe(broken)
        self.assertEqual(self.hud.request_user_close(), "sent")

    def test_red06_no_bve_window_nothing_is_sent_and_the_latch_stays_open(self):
        self.api.alive = False
        self.assertEqual(self.hud.request_user_close(), "no-window")
        self.assertEqual(self.overlay.posts, [])
        self.assertTrue(self.overlay.visible)
        self.api.alive = True
        self.assertEqual(self.hud.request_user_close(), "sent")        # nothing was asked yet, so the user's next close may ask

    def test_red06b_a_hud_that_never_found_the_window_sends_nothing(self):
        self.hud._hwnd = None
        self.assertEqual(self.hud.request_user_close(), "no-window")
        self.assertEqual(self.overlay.posts, [])

    def test_red07_a_failed_post_is_reported_once_and_the_latch_stays_set(self):
        self.overlay.post_works = False
        self.assertEqual(self.hud.request_user_close(), "post-failed")
        self.assertEqual(self.hud.request_user_close(), "already-sent")
        self.assertEqual(len(self.overlay.posts), 1)
        self.assertEqual(len([l for l in self.lines("hud-user-close") if "reason=post-failed" in l]), 1)
        self.assertTrue(self.overlay.visible)

    def test_red08_the_user_close_path_restores_closes_and_quits_nothing(self):
        for _ in range(3):
            self.hud.request_user_close()
        self.assertEqual(self.overlay.calls, [])                       # no restore_bve_window, no overlay.close
        self.assertEqual((self.overlay.hides, self.overlay.visible), (0, True))
        body = code_only(method_source(read("managed_hud.py"), "ManagedHudController", "request_user_close"))
        for token in ("restore", "set_fullscreen", "complete_restore", "quit", "close()", "shutdown", "_hide", "hide("):
            self.assertNotIn(token, body, token)

    def test_the_close_request_has_exactly_one_sender_and_one_message(self):
        main_src = code_only(read("main.py"))
        self.assertEqual(len(re.findall(r"post_close_to_bve", main_src)), 1)                       # the definition
        self.assertEqual(len(re.findall(r"WM_CLOSE", main_src)), 1)                                # the message in that definition
        hud_src = code_only(read("managed_hud.py"))
        self.assertEqual(len(re.findall(r"post_close_to_bve", hud_src)), 1)                        # the call in request_user_close
        self.assertEqual(code_only(method_source(read("managed_hud.py"), "ManagedHudController", "request_user_close")).count("post_close_to_bve"), 1)
        body = code_only(method_source(read("main.py"), "Overlay", "post_close_to_bve"))
        self.assertEqual(body.count("PostMessage"), 1)

    def test_the_summary_line_appears_only_when_the_user_asked_for_a_close(self):
        self.hud.shutdown()
        self.assertEqual(self.lines("user-close-summary"), [])
        self.setUp()
        self.hud.request_user_close()
        self.hud.request_user_close()
        self.hud.shutdown()
        self.assertEqual(len(self.lines("user-close-summary")), 1)
        self.assertIn("sent=1", self.lines("user-close-summary")[0])
        self.assertIn("skipped=1", self.lines("user-close-summary")[0])

    def test_the_log_lines_are_bounded(self):
        for _ in range(40):
            self.hud.request_user_close()
        self.assertLessEqual(len(self.lines("hud-user-close")), mh.INPUT_LINE_CAPS["hud-user-close"])

    def test_input_device_off_and_session_end_send_no_close_request(self):
        """Contract 4: TS Scoring OFF (the state leaves ACTIVE; the Caller then stops this process) is a different contract - BVE keeps running."""
        for session, driving in ((True, False), (False, False)):
            self.publish(session, driving, 1)
            self.pump(5)
        self.hud.shutdown()
        self.assertEqual(self.overlay.posts, [])
        self.assertEqual(self.lines("hud-user-close"), [])
        self.assertEqual(self.lines("user-close-summary"), [])


# =====================================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_WiringAndCleanup(unittest.TestCase):
    """The wiring of main.py: the handler of the managed Overlay, the stop probe, and the cleanup that must never ask BVE to end."""

    @classmethod
    def setUpClass(cls):
        qt_app()
        import main
        cls.main = main

    class FakeHud(object):
        def __init__(self):
            self.args = e4.args_for()
            self.requests = 0
            self.shutdowns = 0

        def request_user_close(self):
            self.requests += 1
            return "sent"

        def tick(self):
            pass

        def start(self):
            return True

        def shutdown(self):
            self.shutdowns += 1

    def test_attach_installs_the_handler_on_the_managed_overlay(self):
        overlay = self.main.Overlay(0)
        hud = self.FakeHud()
        try:
            self.assertTrue(self.main._attach_managed_hud(overlay, hud))
            self.assertEqual(overlay.user_close_handler, hud.request_user_close)
        finally:
            overlay.user_close_handler = None
            overlay.close()

    def test_a_hud_without_the_request_leaves_the_overlay_on_the_default_close(self):
        overlay = self.main.Overlay(0)

        class OldHud(object):
            args = e4.args_for()

            def tick(self):
                pass

            def start(self):
                return True

        try:
            self.assertTrue(self.main._attach_managed_hud(overlay, OldHud()))
            self.assertIsNone(overlay.user_close_handler)
        finally:
            overlay.close()

    def test_the_shutdown_close_never_reaches_the_handler(self):
        overlay = self.main.Overlay(0)
        hud = self.FakeHud()
        self.main._attach_managed_hud(overlay, hud)
        overlay.show()
        self.main._release_overlay(overlay, hud)
        self.assertEqual(hud.requests, 0)
        self.assertIsNone(overlay.user_close_handler)
        self.assertFalse(overlay.isVisible())
        self.assertEqual(hud.shutdowns, 1)

    def test_f11_one_close_request_and_one_restore_no_reentry(self):
        """F11 (borderless) with the Overlay in front: Python posts ONE close; the Caller holds it and asks for the restore; the restore slot runs once and the
        close is never posted again by Python."""
        import managed_mode

        class Control(object):
            _pid = 4242

            def __init__(self):
                self.calls = []

            def set_fullscreen(self, active):
                self.calls.append(("set_fullscreen", active))

            def complete_restore(self):
                self.calls.append(("complete_restore",))

        class Window(object):
            is_borderless_fullscreen = True

            def __init__(self):
                self.restores = 0
                self.posts = []

            def restore_bve_window(self):
                self.restores += 1

            def post_close_to_bve(self, hwnd):
                self.posts.append(hwnd)
                return True

        control, window = Control(), Window()
        bridge = self.main._ManagedShutdownBridge()
        bridge.overlay, bridge.f11_control, bridge.f11_log = window, control, lambda text: None
        args = e4.args_for()
        hud = mh.ManagedHudController(window, None, e4.FakeWindowApi(), args, lambda text: None)
        hud._hwnd = 5000
        for _ in range(3):
            hud.request_user_close()                    # the user presses Alt+F4 three times while the Caller holds the close
        bridge.on_f11_restore_requested()               # the Caller's one restore request
        self.assertEqual(window.posts, [5000])
        self.assertEqual(window.restores, 1)
        self.assertEqual(control.calls, [("set_fullscreen", False), ("complete_restore",)])
        self.assertTrue(hasattr(managed_mode, "F11CloseControl"))

    def test_the_shutdown_request_disarms_the_handler_before_it_quits(self):
        overlay = self.main.Overlay(0)
        hud = self.FakeHud()
        self.main._attach_managed_hud(overlay, hud)
        bridge = self.main._ManagedShutdownBridge()
        bridge.overlay = overlay
        order = []
        bridge.before_quit = lambda: order.append(("before_quit", overlay.user_close_handler))
        saved = self.main.QApplication.quit
        self.main.QApplication.quit = staticmethod(lambda: order.append(("quit", overlay.user_close_handler)))
        try:
            bridge.on_shutdown_requested()
        finally:
            self.main.QApplication.quit = saved
            overlay.close()
        self.assertEqual(order, [("before_quit", None), ("quit", None)])

    def test_quit_with_the_handler_armed_never_vetoes_the_end_of_the_loop(self):
        """quit() asks every window to close. Whatever Qt marks those closes as, the loop must end: a 3 s guard ends it with code 7 if a veto happened."""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        overlay = self.main.Overlay(0)
        hud = self.FakeHud()
        self.main._attach_managed_hud(overlay, hud)
        overlay.show()
        bridge = self.main._ManagedShutdownBridge()
        bridge.overlay = overlay
        QTimer.singleShot(100, bridge.on_shutdown_requested)
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(lambda: QApplication.exit(7))
        guard.start(3000)
        try:
            code = QApplication.instance().exec()
        finally:
            guard.stop()
            overlay.user_close_handler = None
            overlay.close()
        self.assertEqual(code, 0)
        self.assertEqual(hud.requests, 0)

    def test_run_managed_hands_the_stop_probe_over_before_the_attach(self):
        src = read("main.py")
        run = src[src.index("def run_managed"):src.index("def _run_normal")]
        self.assertIn("set_stop_probe(lambda: life.stop_requested)", run)
        self.assertLess(run.index("set_stop_probe(lambda: life.stop_requested)"), run.index("contract_ok = hud is None or _attach_managed_hud(overlay, hud)"))
        self.assertEqual(run.count("app.exec()"), 1)
        self.assertNotIn("QApplication.quit", run)


# =====================================================================================================================================================
def run_helper(*extra):
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}           # (other suites of this run set the offscreen platform)
    out = subprocess.run([sys.executable, "-B", os.path.join(HERE, "overlay_input_ownership_real_check.py"), "--root", ROOT] + list(extra), capture_output=True,
                         text=True, timeout=240, env=env)
    stdout, stderr = out.stdout or "", out.stderr or ""
    if out.returncode != 0 or not stdout.strip():
        raise AssertionError("helper failed rc=%s\n%s\n%s" % (out.returncode, stdout[-2000:], stderr[-2000:]))
    return json.loads(stdout.strip().splitlines()[-1])


@unittest.skipUnless(sys.platform == "win32" and HAS_QT, "needs the Windows desktop and PyQt6")
class C_RealWindows(unittest.TestCase):
    """RED-14: spontaneous() on a REAL HWND, and the whole chain Overlay -> one WM_CLOSE to the stand-in BVE. The foreground of the desktop is not touched."""

    @classmethod
    def setUpClass(cls):
        cls.r = run_helper()
        cls.steps = cls.r["steps"]

    def test_red14_a_close_message_to_the_real_hwnd_is_spontaneous_and_is_ignored(self):
        one = self.steps["5_user_close_1"]
        self.assertEqual(one["close_events_spontaneous"], [True])                   # Alt+F4 arrives as SC_CLOSE -> WM_CLOSE: spontaneous
        self.assertTrue(one["qt_visible"])
        self.assertTrue(one["hwnd_exists"])
        self.assertTrue(one["hwnd_unchanged"])
        self.assertEqual(one["overlay_hwnd"], self.steps["1_hud"]["overlay_hwnd"])  # the SAME window handle as before the close
        self.assertTrue(one["owner_is_bve"])
        self.assertEqual(one["bve_close_messages"], 1)
        self.assertTrue(one["bve_process_alive"])
        self.assertEqual(one["user_close_sent"], 1)

    def test_red14b_more_closes_change_nothing(self):
        total = self.steps["5_user_close_3_total"]
        self.assertEqual(total["close_events_spontaneous"], [True, True, True])
        self.assertEqual(total["bve_close_messages"], 1)
        self.assertEqual(total["user_close_skipped"], 2)
        self.assertTrue(total["qt_visible"])
        self.assertTrue(self.steps["5_after_ticks"]["qt_visible"])
        self.assertEqual(self.steps["5_after_ticks"]["reconciles"], 0)              # a handled close is not a loss: nothing is shown again

    def test_red13_alt_f4_on_the_save_dialog_cancels_the_dialog_only(self):
        step = self.steps["4b_alt_f4_on_the_dialog"]
        self.assertTrue(step["dialog_was_open"])
        self.assertFalse(step["dialog_open_after"])                                  # the dialog is cancelled ...
        self.assertEqual(step["overlay_close_events"], 0)                            # ... the Overlay never gets a close ...
        self.assertEqual(step["bve_close_messages_added"], 0)                        # ... BVE is not asked to end ...
        self.assertTrue(step["overlay_visible"])
        self.assertTrue(step["overlay_hwnd_unchanged"])
        self.assertTrue(step["bve_alive"])
        self.assertEqual(step["user_close_sent"], 0)
        self.assertEqual(step["menu_state"], 11)                                     # ... and the result screen is still there (screen 1: nothing was saved)

    def test_the_close_of_the_program_is_not_spontaneous_and_sends_nothing(self):
        step = self.steps["6_programmatic_close"]
        self.assertEqual(step["close_events_spontaneous"], [False])
        self.assertFalse(step["qt_visible"])
        self.assertEqual(step["bve_close_messages_added"], 0)
        self.assertEqual(self.r["bve_close_messages_total"], 1)

    def test_the_log_words(self):
        lines = self.r["hud_lines_after_user_close"]
        self.assertEqual(len([l for l in lines if "sent=1" in l]), 1)
        self.assertEqual(len([l for l in lines if "reason=already-sent" in l]), 2)


@unittest.skipUnless(sys.platform == "win32" and HAS_QT and os.environ.get("TS_REAL_FOREGROUND") == "1", "takes the foreground of the desktop: TS_REAL_FOREGROUND=1")
class D_RealForeground(unittest.TestCase):
    """RED-15 (as far as a stand-in allows): the situation of the live observation OBS-3C - the Overlay in front after its save dialog closed - then the user close."""

    @classmethod
    def setUpClass(cls):
        cls.r = run_helper("--foreground")
        cls.steps = cls.r["steps"]

    def test_red15_overlay_in_front_after_the_dialog_then_the_user_close(self):
        if not (self.steps.get("2_precondition_bve_in_front") and self.steps.get("5_precondition_overlay_in_front")):
            self.skipTest("the desktop did not let the test take the foreground (another application, possibly elevated, is in front)")
        self.assertEqual(self.steps["4_after_dialog"]["foreground"], "overlay")
        one = self.steps["5_user_close_1"]
        self.assertTrue(self.steps["5_precondition_overlay_in_front"])
        self.assertEqual(one["close_events_spontaneous"], [True])
        self.assertTrue(one["qt_visible"])
        self.assertTrue(one["hwnd_unchanged"])
        self.assertEqual(one["bve_close_messages"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
