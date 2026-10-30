"""Phase LC-5 (Legacy scoring integration) - UI ownership, shutdown, Dispose and the separation of the known Legacy exit crash, as an executable contract (L5-R1 .. L5-R20).

THE POINT
  The Python side does not know which sender feeds it; the Legacy shape of the feed differs from the Current one only by its AVAIL and by the keys of its lines. So the UI / end contracts
  that are Closed for Current (HUD click-through, operation screens own the input, ONE close request to BVE for Alt+F4, Input Device OFF ends TS Scoring only) must hold for a LIVE
  Legacy scoring session too: an outstanding Jump, a pending Retry, a finished run with its result screen. Every row below is run on BOTH shapes (class Legacy / class Current).
  No product line changed in LC-5: every row is CHAR / GUARD (see the deliverables). The two things this file fixes that no earlier test did are
    * the end of a LIVE Legacy session (pending Jump / Retry are dropped, cleanup order, once-ness), and
    * the classification table of the known Legacy exit crash as a pure function (L5-R14 / L5-R15), so that LC-8 evidence is judged by a fixed table.
  The C# half (TEL_FINAL once and last, Dispose order, Caller End guard, Kill once) is checked at the source text (no build, no BVE). The Telemetry Dispose has NO second-call guard;
  that is recorded as a CHARACTERIZED GAP (G-L5-1), not fixed here (a C# change belongs to the Legacy DLL placement of LC-6 / Night C, Owner decision OD-LC5-1).
Needs PyQt6 for the Python rows (skipped otherwise). The Overlay is the real one against the recorders of tests/d6_rig.py: no socket, no real clock, no BVE.
"""
import importlib.util
import os
import re
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PyQt6") is not None

import lc_legacy_feed as F  # noqa: E402
import test_lc4b_python_jump_state as L4B  # noqa: E402  (its Managed rig base only)

WM_CLOSE = 0x0010
OPERATION_SCREENS = {"main": 1, "retry-list": 2, "retry-confirm": 3, "settings": 5, "scoring-settings": 10, "result": 11, "abort-confirm": 12}


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def block(src, start, end=None):
    """The text from `start` to `end` (or to the end of the file)."""
    i = src.index(start)
    j = len(src) if end is None else src.index(end, i + len(start))
    return src[i:j]


def in_order(testcase, text, needles):
    last = -1
    for n in needles:
        i = text.find(n, last + 1)
        testcase.assertGreater(i, last, "%r is missing or out of order (after position %d)" % (n, last))
        last = i


# ===================================================================================================================================================
# the Python rows, on both shapes
# ===================================================================================================================================================
class Contract(object):
    """Mixed into L4B.Managed (shape = 'legacy' | 'current')."""

    def setUp(self):
        super().setUp()
        import sia_rig
        self.FakeApp = sia_rig.FakeApp
        self.wire_ui()

    # -- wiring ---------------------------------------------------------------------------------------------------------------------------------
    def wire_ui(self):
        """The Overlay's ownership / foreground methods become recorders (the real ones need a real HWND); the HUD controller drives them exactly as in production."""
        r, o = self.r, self.o
        self.bve_hwnd = r.win.hwnd
        self.front = self.bve_hwnd
        self.own = {"state": False, "set": [], "foreground": []}
        r.win.foreground_window = lambda: self.front

        def set_input_ownership(operation):
            changed = self.own["state"] != bool(operation)
            self.own["set"].append(bool(operation))
            self.own["state"] = bool(operation)
            return changed

        def bring_to_foreground(hwnd):
            self.own["foreground"].append(hwnd)
            self.front = hwnd
            return True

        o.set_input_ownership, o.has_input_ownership, o.bring_to_foreground = set_input_ownership, lambda: self.own["state"], bring_to_foreground
        self.socket_closes = []
        real_close = o.udp_socket.close
        o.udp_socket.close = lambda: (self.socket_closes.append(1), real_close())[1]

    def overlay_hwnd(self):
        return int(self.o.winId())

    def posted_closes(self):
        return [p for p in self.r.rig.api.posted if p[1] == WM_CLOSE]

    def user_close(self):
        """What Windows delivers for Alt+F4 / the window menu on the Overlay: a SPONTANEOUS close event. Returns the event (accepted = the window would close)."""
        from PyQt6.QtGui import QCloseEvent

        class Spontaneous(QCloseEvent):
            def spontaneous(self):
                return True

        event = Spontaneous()
        self.o.closeEvent(event)
        return event

    def cleanup_like_run_managed(self):
        """The cleanup closure of main.run_managed, step by step in its order (the order itself is pinned against the source by S1)."""
        o, r = self.o, self.r
        for name, arg in (("_station_index_finish", None), ("_jump_transaction_finish", "shutdown")):
            fn = getattr(o, name, None)
            if fn is not None:
                fn() if arg is None else fn(arg)
        r.client.close()
        r.receiver.stop()
        self.main._release_overlay(o, r.hud)

    def live_outstanding_jump(self):
        self.start()                                   # the scoring start asks the sender for a Jump (A at idx 0)
        self.assertTrue(self.o.is_official_jumping and self.outstanding(), "PREMISE an outstanding Jump")

    def live_pending_retry(self):
        self.to_b()
        res = self.main.execute_retry(self.o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertIsNotNone(self.o.retry_pending)
        self.assertTrue(self.outstanding(), "PREMISE the Retry waits for its Jump")

    def assert_session_gone(self, why):
        o = self.o
        self.assertFalse(o.is_scoring_mode, why)
        self.assertFalse(self.outstanding(), why + ": a Jump is still outstanding")
        self.assertIsNone(o.retry_pending, why + ": a Retry is still pending")
        self.assertIsNone(o.jump_expectation, why)
        self.assertFalse(o.is_official_jumping, why)

    # -- L5-R20  the normal HUD is click-through, inactive, never takes the foreground ---------------------------------------------------------------
    def test_R20_the_normal_hud_passes_every_input_to_bve_and_takes_no_foreground(self):
        self.r.go_active(**self.avail())
        self.r.tick(10, 0.1)
        self.assertNotIn(True, self.own["set"], "the HUD took the input")
        self.assertEqual(self.own["foreground"], [], "the HUD took the foreground")
        self.assertFalse(self.own["state"])
        self.assertEqual(self.front, self.bve_hwnd)
        self.assertEqual(self.r.rig.api.posted, [], "something was posted to BVE")

    # -- L5-R1 / F1 contract  the operation screens own the input and the foreground, BVE gets nothing -------------------------------------------------
    def test_R01_every_operation_screen_takes_the_input_and_the_foreground_and_hands_both_back(self):
        self.start()
        self.r.tick(3, 0.1)
        o = self.o
        for name, state in sorted(OPERATION_SCREENS.items()):
            with self.subTest(screen=name):
                o.menu_state = state
                self.r.tick(3, 0.1)
                self.assertTrue(self.own["state"], "%s did not take the input" % name)
                self.assertEqual(self.front, self.overlay_hwnd(), "%s did not take the foreground" % name)
                o.menu_state = 0
                self.r.tick(3, 0.1)
                self.assertFalse(self.own["state"], "%s kept the input after it closed" % name)
                self.assertEqual(self.front, self.bve_hwnd, "%s did not hand the foreground back to BVE" % name)
        self.assertEqual(self.posted_closes(), [])

    def test_R01b_the_scoring_start_screens_of_a_live_session_do_not_close_the_overlay(self):
        self.start()
        self.r.tick(3, 0.1)
        self.assertTrue(self.o.is_scoring_mode)
        self.assertFalse(self.own["state"], "the menu left the input with the Overlay after the start")
        self.assertEqual(self.front, self.bve_hwnd)
        self.assertEqual(self.o.menu_state, 0)

    def test_R01c_after_the_jump_of_the_start_completes_the_ui_is_the_normal_hud_again(self):
        self.land(self.start())
        self.r.tick(3, 0.1)
        o = self.o
        self.assertTrue(o.is_scoring_mode and not o.is_official_jumping, "PREMISE the Jump completed")
        self.assertEqual(o.menu_state, 0)
        self.assertFalse(self.own["state"], "the Overlay kept the input after the Jump")
        self.assertEqual(self.front, self.bve_hwnd, "the foreground is not with BVE after the Jump")
        self.assertEqual(self.posted_closes(), [])

    # -- L5-R1 / L5-R2  Alt+F4 on an operation screen of a LIVE session ------------------------------------------------------------------------------
    def test_R01_R02_alt_f4_on_an_operation_screen_closes_nothing_and_asks_bve_once(self):
        self.live_outstanding_jump()
        self.r.tick(2, 0.1)
        self.o.menu_state = OPERATION_SCREENS["main"]
        self.r.tick(3, 0.1)
        self.assertTrue(self.own["state"])
        for n in range(4):
            event = self.user_close()
            self.assertFalse(event.isAccepted(), "close #%d: the Overlay would close" % (n + 1))
        self.assertEqual([p[0] for p in self.posted_closes()], [self.bve_hwnd], "BVE did not get exactly ONE WM_CLOSE")
        self.assertEqual(self.r.hud.user_close_sent, 1)
        self.assertEqual(self.r.hud.user_close_skipped, 3)
        self.assertTrue(self.o.is_scoring_mode, "Alt+F4 ended the scoring session by itself")
        self.assertEqual(self.FakeApp.quits, 0, "the process was asked to quit by the user close")

    def test_R02_a_failed_post_keeps_the_latch_and_never_posts_twice(self):
        self.r.go_active(**self.avail())
        calls = []

        def broken(hwnd):
            calls.append(hwnd)
            return False

        self.o.post_close_to_bve = broken
        self.user_close()
        self.user_close()
        self.assertEqual(calls, [self.bve_hwnd])
        self.assertEqual(self.r.hud.user_close_sent, 0)

    def test_R01_alt_f4_on_the_normal_hud_is_not_the_overlays_business(self):
        """On the normal HUD the Overlay is click-through and not in front: Alt+F4 reaches BVE itself. The Overlay posts nothing by itself."""
        self.r.go_active(**self.avail())
        self.r.tick(10, 0.1)
        self.assertEqual(self.posted_closes(), [])
        self.assertFalse(self.own["state"])

    # -- L5-R3 / L5-R4  Input Device OFF = the Stop of the Caller: TS Scoring ends, BVE does not --------------------------------------------------------
    def test_R03_input_device_off_never_asks_bve_to_end(self):
        self.live_outstanding_jump()
        stopping = [False]
        self.r.hud.set_stop_probe(lambda: stopping[0])
        stopping[0] = True                                           # the Caller's Stop event is set
        event = self.user_close()                                    # a late Alt+F4 while the process ends
        self.assertFalse(event.isAccepted())
        self.r.hud.shutdown()
        self.cleanup_like_run_managed()
        self.assertEqual(self.posted_closes(), [], "TS Scoring OFF closed BVE")
        self.assertEqual(self.r.hud.user_close_sent, 0)

    def _run_lifecycle_to_the_stop(self, reason_event="stop"):
        import test_managed_mode_e2 as E2
        import managed_mode
        sync = E2.FakeSync()
        args = E2.args_for()
        owner = E2.Owner(sync, args)
        self.addCleanup(owner.close)
        before = threading.active_count()
        life = managed_mode.ManagedLifecycle(args, sync, E2.Log())
        self.assertIsNone(life.acquire())
        notified = threading.Event()
        life.start_stop_watch(notified.set)
        self.assertTrue(life.publish_ready())
        self.assertGreater(threading.active_count(), before, "PREMISE the stop watcher runs")
        owner.set_stop()
        self.assertTrue(notified.wait(3), "the stop was not noticed")
        return life, before, managed_mode

    def test_R04_R05_the_stop_ends_the_python_process_with_exit_zero_once_and_leaves_no_thread(self):
        self.live_pending_retry()
        life, before, mm = self._run_lifecycle_to_the_stop()
        bridge = self.main._ManagedShutdownBridge()
        bridge.overlay = self.o
        bridge.before_quit = self.o.close_result_dialog
        bridge.on_shutdown_requested()                               # the UI-thread slot the watcher's notification reaches
        self.assertIsNone(self.o.user_close_handler, "the user close handler stayed armed")
        self.assertEqual(self.FakeApp.quits, 1)
        runs = []

        def cleanup():
            runs.append(1)
            self.cleanup_like_run_managed()

        self.assertEqual(life.shutdown(cleanup), mm.EXIT_OK)
        self.assertEqual(life.shutdown(cleanup), mm.EXIT_OK, "the second shutdown changed the result")
        self.assertEqual(runs, [1], "the cleanup ran %d times" % len(runs))
        self.assertEqual(life.exit_reason, "stop-requested")
        self.assertEqual(threading.active_count(), before, "a thread is left")
        self.assertEqual(self.posted_closes(), [])
        self.assert_session_gone("after the stop")

    # -- L5-R6  the end of the scenario ----------------------------------------------------------------------------------------------------------------
    def test_R06_scenario_close_discards_the_scoring_session_and_keeps_the_process(self):
        self.live_pending_retry()
        self.r.publish(session=False, driving=False)                 # the Caller: Session OFF (scenario closed / Input Device soft OFF)
        self.r.tick(3, 0.1)
        self.assert_session_gone("scenario close")
        self.assertFalse(self.r.hud._shutdown, "the scenario close ended the HUD controller (Python must live on: INV-SHUT-10)")
        self.assertEqual(self.FakeApp.quits, 0)
        self.assertEqual(self.posted_closes(), [])
        self.assertEqual(self.own["state"], False)
        self.assertEqual(self.r.events("hud-summary"), [], "the summary is the line of the END of the process")

    def test_R06b_a_pause_keeps_the_session_and_a_new_generation_drops_it(self):
        self.live_outstanding_jump()
        self.r.publish(session=True, driving=False)
        self.r.tick(3, 0.1)
        self.assertTrue(self.o.is_scoring_mode, "a Pause ended the session")
        self.r.publish(session=True, driving=True, generation=2)
        self.r.tick(3, 0.1)
        self.assertFalse(self.o.is_scoring_mode, "a new ScenarioGeneration kept the old session")
        self.assertFalse(self.outstanding())

    # -- L5-R7 / L5-R8  nothing pending survives the end -------------------------------------------------------------------------------------------------
    def test_R07_an_outstanding_jump_is_dropped_at_the_end_and_a_late_completion_is_stale(self):
        self.live_outstanding_jump()
        cmd = self.r.last_command()
        self.r.hud.shutdown()
        self.cleanup_like_run_managed()
        self.assert_session_gone("shutdown with a Jump outstanding")
        n = len(self.commands())
        self.r.complete(cmd["request_id"], location=0.0, time_ms=36000000, count=1)           # the sender answers after the end
        self.assertEqual(len(self.commands()), n, "a command was sent after the end")
        self.assertFalse(self.o.is_scoring_mode)
        self.assertIn("outstanding=0", self.o.jump_client.summary())

    def test_R08_a_pending_retry_is_dropped_at_the_end(self):
        self.live_pending_retry()
        self.r.hud.shutdown()
        self.cleanup_like_run_managed()
        self.assert_session_gone("shutdown with a Retry pending")
        self.assertEqual(self.posted_closes(), [])

    def test_R07_R08_the_end_after_a_timeout_abort_is_clean(self):
        """L5-R18 (A15): the silent sender aborted the session at 10.0 s; the end after that has nothing left to drop and does not abort a second time."""
        self.start()
        self.r.tick(3, 3.5)
        self.assertEqual(len(self.aborts()), 1)
        self.r.hud.shutdown()
        self.cleanup_like_run_managed()
        self.assert_session_gone("end after the timeout abort")
        self.assertEqual(len(self.aborts()), 1, self.aborts())

    # -- the result screen / the save dialog ---------------------------------------------------------------------------------------------------------
    def test_R01_the_result_save_dialog_is_closed_once_by_the_end_and_its_owner_is_the_overlay(self):
        class Dialog(object):
            rejects = 0

            def reject(self):
                Dialog.rejects += 1

        self.start()
        self.o.menu_state = OPERATION_SCREENS["result"]
        self.r.tick(3, 0.1)
        self.o.result_dialog = Dialog()
        self.r.hud.shutdown()
        self.assertEqual(Dialog.rejects, 1, "the open save dialog was not rejected exactly once")
        self.r.hud.shutdown()
        self.assertEqual(Dialog.rejects, 1)
        self.assertIn("QFileDialog(overlay,", read("managed_input.py"), "the save dialog is not owned by the Overlay")

    # -- L5-R9 / R10 / R12 / R13  resources and once-ness ---------------------------------------------------------------------------------------------------
    def test_R09_R13_the_end_closes_the_listener_once_releases_every_hook_and_writes_one_summary(self):
        self.live_pending_retry()
        self.o.menu_state = OPERATION_SCREENS["main"]
        self.r.tick(3, 0.1)
        self.assertTrue(self.kb_active(), "PREMISE the menu holds key hooks")
        self.r.hud.shutdown()
        self.cleanup_like_run_managed()
        self.cleanup_like_run_managed()                              # a repeated end changes nothing
        self.assertEqual(self.kb_active(), [], "a key hook is left")
        self.assertEqual(len(self.r.events("hud-summary")), 1, "the summary line is not exactly one")
        self.assertGreaterEqual(len(self.socket_closes), 1, "the UDP listener was not closed")
        self.assertTrue(self.r.client._closed and self.r.receiver is not None)
        self.assertFalse(self.own["state"], "the input stayed with the Overlay")

    def kb_active(self):
        return self.r.rig.kb.active()

    def test_R16_the_user_close_after_the_end_does_nothing(self):
        self.live_outstanding_jump()
        self.r.hud.shutdown()
        self.cleanup_like_run_managed()
        self.user_close()
        self.assertEqual(self.posted_closes(), [])


class Legacy(Contract, L4B.Managed):
    shape = "legacy"


class Current(Contract, L4B.Managed):
    """L5-R16: the same rows on the Current shape of the feed (the Closed Current contract is not changed by LC-5)."""
    shape = "current"


# ===================================================================================================================================================
# the Legacy rows that exist only for the Legacy shape (A14 / A15 / A16 stay guards)
# ===================================================================================================================================================
class LegacyGuards(L4B.Managed):
    shape = "legacy"

    def setUp(self):
        super().setUp()

    def test_R17_a_retry_after_the_finish_is_refused_and_still_after_the_end(self):
        self.to_b()
        self.o.is_scoring_finished = True
        self.assertEqual(self.main.execute_retry(self.o, 0, False).reason, "scoring-finished")
        self.r.hud.shutdown()
        self.assertFalse(self.main.execute_retry(self.o, 0, False).accepted)

    def test_R19_the_jump_counter_baseline_is_the_first_line_that_carries_the_key_and_the_end_follows(self):
        r, o, MR = self.r, self.o, self.MR
        r.publish(True, True, 1)
        r.tick(2)
        r.send(MR.STALIST, L4B.without_jump_key(MR.tele(1, time_ms=36000000, avail=L4B.NO_JUMP_AVAIL)))
        r.tick(2)
        r.send(F.line("legacy", 1, 36001000, 0.0, 0.0, jump=3, NEXTLOC=1000.0))
        r.tick(2)
        self.assertEqual((o.last_jump_count, o.jump_lock, o.is_official_jumping), (3, False, False))
        self.assertEqual(self.aborts(), [])
        r.hud.shutdown()
        self.assertEqual(len(r.events("hud-summary")), 1)

    def test_R18_a_jump_unavailable_refusal_does_not_stop_the_session_from_ending(self):
        self.to_b()
        self.r.send(self.line_at_b(36004000, avail=L4B.NO_JUMP_AVAIL, with_jump=False))
        self.r.tick(2, 0.1)
        self.assertEqual(self.main.execute_retry(self.o, 0, False).reason, "jump-unavailable")
        self.r.hud.shutdown()
        self.r.client.close()
        self.assertFalse(self.o.is_scoring_mode)


# ===================================================================================================================================================
# S: the source rows (no Qt needed)
# ===================================================================================================================================================
class T_Threads(unittest.TestCase):
    """L5-R10: the two threads of the Python side (stop watch, F11 restore watch) end with their owner also when no Stop ever came (a failure, the loop ended by itself)."""

    def test_T1_a_lifecycle_that_ends_without_a_stop_cancels_its_watcher(self):
        import test_managed_mode_e2 as E2
        import managed_mode as mm
        import time
        sync, args = E2.FakeSync(), E2.args_for()
        owner = E2.Owner(sync, args)
        self.addCleanup(owner.close)
        before = threading.active_count()
        life = mm.ManagedLifecycle(args, sync, E2.Log())
        self.assertIsNone(life.acquire())
        life.start_stop_watch(lambda: None)
        self.assertTrue(life.publish_ready())
        self.assertGreater(threading.active_count(), before)
        started = time.monotonic()
        self.assertEqual(life.shutdown(), mm.EXIT_OK)
        self.assertEqual(threading.active_count(), before, "the stop watcher is left")
        self.assertLess(time.monotonic() - started, mm._WATCHER_JOIN_SECONDS, "the watcher was ended by the join timeout, not by its cancel event")

    def test_T2_the_f11_control_ends_its_watcher_with_its_shutdown_and_does_it_once(self):
        import test_managed_mode_e2 as E2
        import managed_mode as mm
        import time
        sync = E2.FakeSync()
        lines = E2.Log()
        before = threading.active_count()
        control = mm.F11CloseControl(777001, sync, lines)
        control.start(lambda: None)
        self.assertGreater(threading.active_count(), before)
        started = time.monotonic()
        control.shutdown()
        control.shutdown()
        self.assertEqual(threading.active_count(), before, "the F11 watcher is left")
        self.assertLess(time.monotonic() - started, mm._WATCHER_JOIN_SECONDS)
        self.assertEqual(len(lines.events("f11-control-ended")) if hasattr(lines, "events") else 1, 1)


class S_SourceOrder(unittest.TestCase):
    def test_S1_the_cleanup_of_run_managed_keeps_its_order(self):
        src = read("main.py")
        cleanup = block(src, "def cleanup_managed_resources():", "cleanup = cleanup_managed_resources if")
        in_order(self, cleanup, ["telemetry_directory.publish_withdrawing()", "finish()", 'transaction_finish("shutdown")', "jump_client.close()", "dataplane_receiver.stop()",
                                 "_release_overlay(overlay, hud)", "telemetry_directory.close()"])
        tail = block(src, "cleanup = cleanup_managed_resources if", "return result\n")
        in_order(self, tail, ["life.shutdown(cleanup)", "directory_reader.close()", "f11_control.shutdown()", "app.processEvents()"])

    def test_S2_release_overlay_ends_the_hud_first_and_disarms_the_user_close_before_the_window_closes(self):
        body = block(read("main.py"), "def _release_overlay(overlay, hud=None):", "def _open_managed_app_directory")
        in_order(self, body, ["hud.shutdown()", "timer.stop()", "user_close_handler = None", "keyboard.unhook(hook)", "_release_time_position_window_lock", "sock.close()", "overlay.close()"])

    def test_S3_the_stop_slot_disarms_the_handler_before_it_quits(self):
        body = block(read("main.py"), "def on_shutdown_requested(self):", "def _attach_managed_hud")
        in_order(self, body, ["overlay.user_close_handler = None", "callback()", "QApplication.quit()"])

    def test_S4_the_python_side_starts_no_subprocess_and_only_two_known_threads(self):
        for name in ("main.py", "managed_hud.py", "managed_input.py", "managed_mode.py", "managed_state.py", "managed_app_directory.py", "current_jump_client.py",
                     "telemetry_dataplane_receiver.py", "telemetry_receiver_directory.py", "pause_recovery.py", "scoring_logic.py", "jump_transaction.py"):
            src = read(name)
            for word in ("subprocess", "Popen", "os.system", "multiprocessing", "QProcess", "QThread"):
                self.assertNotIn(word, src, "%s uses %s" % (name, word))
        owners = sorted(n for n in os.listdir(ROOT) if n.endswith(".py") and "threading.Thread(" in read(n))
        self.assertEqual(owners, ["managed_mode.py"], "a thread is started outside managed_mode.py")
        self.assertEqual(read("managed_mode.py").count("threading.Thread("), 2)      # the stop watch and the F11 restore watch; both are joined by their shutdown

    def test_S5_the_user_close_handler_is_armed_only_by_the_managed_attach(self):
        src = read("main.py")
        self.assertEqual(len(re.findall(r"user_close_handler\s*=\s*request_user_close", src)), 1)
        self.assertNotIn("user_close_handler", block(src, "def _run_normal():"))


class S_CSharp(unittest.TestCase):
    EXT = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs"
    SES = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs"
    CALLER = "TsScoringPlugin/Handshake/Caller/src/HandshakeSession.cs"
    APM = "TsScoringPlugin/Handshake/Caller/src/AppProcessManager.cs"
    BRIDGE = "TsScoringPlugin/Handshake/Bridge/Legacy/src/TsScoringLegacyBridge.cs"

    def dispose(self):
        return block(read(self.EXT), "public override void Dispose()", "private void OnHeartbeat")

    def test_C1_TEL_FINAL_is_written_once_in_the_source_and_last_in_the_dispose(self):
        self.assertEqual(read(self.EXT).count('"TEL_FINAL"'), 1)
        body = self.dispose()
        in_order(self, body, ["heartbeat.Stop()", "ScenarioOpened -= OnScenarioOpened", "jump.Dispose()", "session.OnDispose()", '"TEL_FINAL"'])
        self.assertEqual(body.rstrip().rstrip("}").rstrip().splitlines()[-1].strip().startswith("diag.Event(\"TEL_FINAL\""), True, "TEL_FINAL is not the last statement")

    def test_C2_the_session_dispose_has_a_second_call_guard_so_TEL_DISPOSE_is_written_once(self):
        body = block(read(self.SES), "internal void OnDispose()", "private void EndEpoch")
        self.assertRegex(body, r"if \(disposed\)\s*\{\s*return;\s*\}")
        self.assertEqual(read(self.SES).count('"TEL_DISPOSE"'), 1)

    def test_C3_G_L5_1_CHARACTERIZED_GAP_the_telemetry_extension_dispose_has_no_second_call_guard(self):
        """Owner decision OD-LC5-1. A second Dispose() of the extension would write TEL_FINAL a second time. The host disposes an extension ONCE (so no product failure is known);
        the guard is a C# change and belongs to the Legacy DLL placement (LC-6) / Night C. If this row fails the guard was added: update the row, do not delete it."""
        self.assertNotRegex(self.dispose(), r"if \s*\(\s*disposedFlag\s*\)\s*\{?\s*return")
        self.assertEqual(self.dispose().count("disposedFlag = true;"), 1)

    def test_C4_the_caller_end_returns_at_once_when_disposed_and_stops_the_application_after_releasing_the_gate(self):
        body = block(read(self.CALLER), "public void End()", "/// <summary>\n        /// Phase D1")
        self.assertRegex(body, r"if \(phase == CallerPhase\.Disposed\)\s*\{\s*return;\s*\}")
        in_order(self, body, ["phase = CallerPhase.Disposed", "PublishAppStateLocked()", "DisposeAppControllerLocked()", "stop.Set()", "Release(ref stop)", "ShutdownAppProcess()"])
        self.assertLess(body.index("Release(ref stop)"), body.index("ShutdownAppProcess()"))

    def test_C5_the_app_process_is_killed_only_after_the_grace_and_only_once_and_never_by_name(self):
        src = read(self.APM)
        self.assertEqual(src.count("process.Kill()"), 1)
        stop = block(src, "private AppProcessState StopSequence(", "private void RecordExit")
        in_order(self, stop, ["WaitForExit(options.StopGraceMs)", "APP_STOP_TIMEOUT", "process.Kill()", "WaitForExit(options.KillWaitMs)", "APP_PROCESS_RESIDUAL", "APP_EXITED"])
        for word in ("Process.GetProcessesByName", "taskkill"):
            self.assertNotIn(word, src)

    def test_C6_the_bridge_withdraws_ScenarioReady_before_Ready(self):
        body = block(read(self.BRIDGE), "public override void Dispose()", "// Control plane wiring")
        in_order(self, body, ["UnsubscribeObservers()", "t.OnDispose()", 'c.Shutdown("bridge-dispose")', "c.WithdrawAvailability()"])

    def test_C7_no_c_sharp_file_of_the_shutdown_set_is_changed_by_lc5(self):
        """GUARD (also the Close condition): the C# of the end is as it was at LC-4b (cbebfd3). Skipped when git is not available."""
        import subprocess
        try:
            out = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", "cbebfd3", "--", self.EXT, self.SES, self.CALLER, self.APM, self.BRIDGE], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git is not available")
        if out.returncode != 0:
            self.skipTest("cbebfd3 is not known to this checkout")
        self.assertEqual(out.stdout.decode().split(), [])


# ===================================================================================================================================================
# K: the classification of the known Legacy exit crash (L5-R14 / L5-R15). A pure function = the frozen table of the X01 check of Judge-LjX1-v2.1 (class names as in LC-0).
# It is the TABLE LC-8 evidence is read with; the live judge stays the PowerShell one. Nothing here claims a cause.
# ===================================================================================================================================================
BASE = dict(app_version="5.8.7554.391", module="ntdll.dll", exception="c0000005", offset="60d99", wer="8be44026", host="Legacy", same_run=True,
            tel_final_seen=True, seconds_after_final=0.42, before_dispose_begin=False, executing_left=0, queue_left=0, api_in_progress=False,
            resources_left=0, shutdown_order_ok=True, python_unhandled_exception=False, product_log_present=True, reproduces_on_current=False, wer_present=True)

BASELINE = "BASELINE_KNOWN_PROCEED"
SUSPECT = "PRODUCT-SUSPECT"
INCONCLUSIVE = "INCONCLUSIVE"
NONE = "NONE"


def classify_crash(ev):
    """None for no crash. The Legacy ntdll baseline needs EVERY condition; a wrong signature or a product-side anomaly is SUSPECT; what cannot be decided is INCONCLUSIVE."""
    if ev is None:
        return NONE
    if not ev["same_run"]:
        return INCONCLUSIVE                                   # a BveTs PID outside this run: attribution impossible (the Legacy side is unaffected)
    anomaly = (not ev["shutdown_order_ok"] or ev["executing_left"] or ev["queue_left"] or ev["api_in_progress"] or ev["resources_left"]
               or ev["python_unhandled_exception"] or not ev["product_log_present"])
    if ev["host"] != "Legacy":
        return SUSPECT                                        # the Current host baseline (clr) is a different, external table; here any other host is suspect
    signature = (ev["app_version"], ev["module"].lower(), ev["exception"].lower().replace("0x", ""), ev["offset"].lower().replace("0x", "").lstrip("0"))
    if signature != ("5.8.7554.391", "ntdll.dll", "c0000005", "60d99"):
        return SUSPECT
    if not ev["wer_present"]:
        return INCONCLUSIVE
    if not str(ev["wer"]).startswith("8be44026"):
        return SUSPECT
    if not ev["tel_final_seen"] or ev["before_dispose_begin"]:
        return SUSPECT                                        # before the shutdown completed
    if ev["seconds_after_final"] <= 0:
        return SUSPECT
    if anomaly or ev["reproduces_on_current"]:
        return SUSPECT                                        # a baseline signature with a product-side deviation is never excused
    if ev["seconds_after_final"] > 5.0:
        return INCONCLUSIVE
    return BASELINE


class K_CrashClassification(unittest.TestCase):
    def ev(self, **kw):
        d = dict(BASE)
        d.update(kw)
        return d

    def test_K0_no_crash_is_none(self):
        self.assertEqual(classify_crash(None), NONE)

    def test_K1_the_known_signature_after_a_clean_shutdown_is_the_baseline(self):
        for dt in (0.37, 0.47, 1.0, 5.0):
            self.assertEqual(classify_crash(self.ev(seconds_after_final=dt)), BASELINE, dt)

    def test_K2_L5_R14_no_product_side_anomaly_is_hidden_behind_the_known_signature(self):
        for field, value in (("tel_final_seen", False), ("before_dispose_begin", True), ("executing_left", 1), ("queue_left", 1), ("api_in_progress", True), ("resources_left", 2),
                             ("shutdown_order_ok", False), ("python_unhandled_exception", True), ("product_log_present", False), ("reproduces_on_current", True), ("seconds_after_final", 0.0),
                             ("seconds_after_final", -0.5)):
            with self.subTest(field=field, value=value):
                self.assertEqual(classify_crash(self.ev(**{field: value})), SUSPECT)

    def test_K3_L5_R15_an_unknown_signature_is_never_the_baseline(self):
        for field, value in (("app_version", "5.8.7554.392"), ("module", "KERNELBASE.dll"), ("module", "clr.dll"), ("exception", "80131506"), ("exception", "e0434352"),
                             ("offset", "62b39"), ("offset", "60d9a"), ("wer", "921753a5"), ("wer", "82627722"), ("host", "Current"), ("host", "Unknown")):
            with self.subTest(field=field, value=value):
                self.assertEqual(classify_crash(self.ev(**{field: value})), SUSPECT)

    def test_K4_what_cannot_be_decided_is_inconclusive_not_known(self):
        self.assertEqual(classify_crash(self.ev(seconds_after_final=5.01)), INCONCLUSIVE)
        self.assertEqual(classify_crash(self.ev(wer_present=False)), INCONCLUSIVE)
        self.assertEqual(classify_crash(self.ev(same_run=False)), INCONCLUSIVE)

    def test_K5_the_notation_of_the_signature_does_not_change_the_class(self):
        self.assertEqual(classify_crash(self.ev(exception="0xC0000005", offset="0x00060D99")), BASELINE)

    def test_K6_the_table_matches_the_frozen_judge_when_it_is_present(self):
        path = os.path.join(os.path.expanduser("~"), "Documents", "TS-Scoring-Claude-Handoff", "pid-d4ja-ljx1-tool-v2.1-20261020-153627", "artifacts", "Judge-LjX1-v2.1.ps1")
        if not os.path.isfile(path):
            self.skipTest("the frozen judge is not on this machine")
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for needle in ("AppVersion = '5.8.7554.391'", "Module = 'ntdll.dll'", "Exc = 'c0000005'", "Off = '60d99'", "Wer = '8be44026'", "$dt -gt 5.0", "TEL_FINAL never appeared",
                       "before jump-dispose-begin", "BASELINE_KNOWN_PROCEED"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
