import types
import unittest

import managed_app_directory
import managed_hud


class FakeTimer:
    def __init__(self):
        self.intervals = []
    def setInterval(self, value):
        self.intervals.append(value)


class FakeOverlay:
    def __init__(self):
        self.visible = False
        self.hide_calls = 0
        self.show_calls = 0
    def hide(self):
        self.visible = False
        self.hide_calls += 1
    def show(self):
        self.visible = True
        self.show_calls += 1
    def isVisible(self):
        return self.visible
    def winId(self):
        return 10


class FakeStateReader:
    def __init__(self):
        self.lost = None
        self.closed = 0
    def poll(self):
        return None
    def close(self):
        self.closed += 1


class FakeDirectoryReader:
    def __init__(self):
        self.closed = 0
    def close(self):
        self.closed += 1


class FakeMonitor:
    def __init__(self, results):
        self.results = list(results)
        self.mode = managed_app_directory.RUNTIME_WAIT_READY
        self.reader = FakeDirectoryReader()
        self.polls = 0
    def poll(self):
        self.polls += 1
        result = self.results.pop(0)
        self.mode = result.mode
        return result


class FakeInput:
    def __init__(self):
        self.inactive = []
        self.shutdowns = 0
    def step(self):
        return None
    def on_inactive(self, reason):
        self.inactive.append(reason)
    def on_shutdown(self):
        self.shutdowns += 1
    def summary_fields(self):
        return {}


class FakeRecovery:
    def __init__(self):
        self.closed = []
        self.created = 0
        self.refused = 0
    def close(self, reason):
        self.closed.append(reason)
    def summary_fields(self):
        return {}


class HudDirectoryIntegration(unittest.TestCase):
    def controller(self, monitor):
        overlay = FakeOverlay()
        state = FakeStateReader()
        timer = FakeTimer()
        args = types.SimpleNamespace(instance='a'*32, owner='caller', bve_pid=123)
        hud = managed_hud.ManagedHudController(
            overlay, state, object(), args, lambda _line: None,
            update_step=None, timer=timer, directory_monitor=monitor,
        )
        return hud, overlay, state, timer

    def test_waiting_blocks_state_and_hud_work(self):
        monitor = FakeMonitor([managed_app_directory.RuntimeDirectoryResult(managed_app_directory.RUNTIME_WAIT_READY)])
        hud, overlay, state, timer = self.controller(monitor)
        hud.tick()
        self.assertEqual(monitor.polls, 1)
        self.assertEqual(hud.ticks, 1)
        self.assertIsNone(hud.failsafe)
        self.assertFalse(hud.input_allowed)
        self.assertEqual(timer.intervals, [managed_hud.IDLE_INTERVAL_MS])
        self.assertEqual(state.closed, 0)
        self.assertEqual(overlay.show_calls, 0)

    def test_failed_directory_uses_existing_failsafe(self):
        result = managed_app_directory.RuntimeDirectoryResult(managed_app_directory.RUNTIME_FAILED, 'ready-revoked')
        monitor = FakeMonitor([result])
        hud, overlay, _state, _timer = self.controller(monitor)
        inp = FakeInput()
        recovery = FakeRecovery()
        hud.attach_input(inp)
        hud.attach_recovery(recovery)
        hud._shown = True
        overlay.visible = True
        hud.tick()
        self.assertEqual(hud.failsafe, 'app-directory-ready-revoked')
        self.assertEqual(inp.inactive, ['app-directory-lost'])
        self.assertEqual(recovery.closed, ['app-directory-lost'])
        self.assertFalse(overlay.visible)
        self.assertFalse(hud.input_allowed)
        hud.tick()
        self.assertEqual(monitor.polls, 1)

    def test_terminal_is_safe_and_reported_as_caller_closed(self):
        result = managed_app_directory.RuntimeDirectoryResult(managed_app_directory.RUNTIME_TERMINAL, 'withdrawing')
        monitor = FakeMonitor([result])
        logs = []
        hud, overlay, state, _timer = self.controller(monitor)
        hud._log = logs.append
        hud._shown = True
        overlay.visible = True
        hud.tick()
        self.assertEqual(hud.failsafe, 'app-directory-withdrawing')
        self.assertEqual(hud._directory_terminal, 'withdrawing')
        hud.shutdown()
        self.assertEqual(state.closed, 1)
        self.assertEqual(monitor.reader.closed, 1)
        self.assertTrue(any('end=caller-closed' in line for line in logs))

    def test_monitoring_allows_state_poll(self):
        class StateReader(FakeStateReader):
            def __init__(self):
                super().__init__()
                self.polls = 0
            def poll(self):
                self.polls += 1
                return None
        monitor = FakeMonitor([managed_app_directory.RuntimeDirectoryResult(managed_app_directory.RUNTIME_MONITORING)])
        hud, _overlay, _state, _timer = self.controller(monitor)
        state = StateReader()
        hud._reader = state
        hud.tick()
        self.assertEqual(state.polls, 1)
        self.assertIsNone(hud.failsafe)


if __name__ == '__main__':
    unittest.main()
