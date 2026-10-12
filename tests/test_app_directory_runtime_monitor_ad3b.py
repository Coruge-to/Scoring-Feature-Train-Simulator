import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import managed_app_directory as mad


class Reader(object):
    def __init__(self, values):
        self.values = list(values)
        self.last_rejection = None

    def poll(self):
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, tuple):
            value, self.last_rejection = value
        return value


class Snap(object):
    def __init__(self, pid=101, instance="1" * 32, app_pid=202, ready=False,
                 published=True, started=True, withdrawing=False, closed=False):
        self.bve_pid = pid
        self.instance = instance
        self.app_pid = app_pid
        self.instance_published = published
        self.process_started = started
        self.ready_accepted = ready
        self.withdrawing = withdrawing
        self.closed = closed


class RuntimeDirectoryMonitorContract(unittest.TestCase):
    def monitor(self, values):
        return mad.RuntimeDirectoryMonitor(Reader(values), 101, "1" * 32, 202)

    def test_waits_for_ready_then_monitors(self):
        mon = self.monitor([Snap(), Snap(ready=True)])
        first = mon.poll()
        self.assertEqual(first.mode, mad.RUNTIME_WAIT_READY)
        self.assertFalse(first.active)
        second = mon.poll()
        self.assertEqual(second.mode, mad.RUNTIME_MONITORING)
        self.assertTrue(second.active)
        self.assertTrue(mon.accepted)

    def test_ready_revocation_latches_and_cannot_recover(self):
        mon = self.monitor([Snap(ready=True), Snap(ready=False), Snap(ready=True)])
        self.assertTrue(mon.poll().active)
        failed = mon.poll()
        self.assertTrue(failed.failed)
        self.assertEqual(failed.reason, "ready-revoked")
        again = mon.poll()
        self.assertTrue(again.failed)
        self.assertEqual(again.reason, "ready-revoked")

    def test_identity_and_process_contract_fail_closed(self):
        cases = [
            (Snap(pid=102), "bve-pid-mismatch"),
            (Snap(instance="2" * 32), "instance-mismatch"),
            (Snap(app_pid=203), "app-pid-mismatch"),
            (Snap(published=False), "instance-not-published"),
            (Snap(started=False), "process-not-started"),
        ]
        for snap, expected in cases:
            with self.subTest(expected=expected):
                result = self.monitor([snap]).poll()
                self.assertTrue(result.failed)
                self.assertEqual(result.reason, expected)

    def test_reader_rejection_and_exception_fail_closed(self):
        rejected = self.monitor([(None, "flags")]).poll()
        self.assertTrue(rejected.failed)
        self.assertEqual(rejected.reason, "read-flags")
        raised = self.monitor([RuntimeError("x")]).poll()
        self.assertTrue(raised.failed)
        self.assertEqual(raised.reason, "read-error:RuntimeError")

    def test_withdrawing_and_closed_are_terminal_not_failed(self):
        for snap, expected in ((Snap(withdrawing=True), "withdrawing"),
                               (Snap(instance="", app_pid=0, published=False, started=False, closed=True), "closed")):
            with self.subTest(expected=expected):
                result = self.monitor([snap]).poll()
                self.assertTrue(result.terminal)
                self.assertFalse(result.failed)
                self.assertEqual(result.reason, expected)

    def test_terminal_is_latched(self):
        mon = self.monitor([Snap(withdrawing=True), Snap(ready=True)])
        self.assertTrue(mon.poll().terminal)
        result = mon.poll()
        self.assertTrue(result.terminal)
        self.assertEqual(result.reason, "withdrawing")

    def test_constructor_rejects_invalid_identity(self):
        with self.assertRaises(ValueError):
            mad.RuntimeDirectoryMonitor(Reader([Snap()]), 0, "1" * 32, 202)
        with self.assertRaises(ValueError):
            mad.RuntimeDirectoryMonitor(Reader([Snap()]), 101, "not-an-instance", 202)
        with self.assertRaises(ValueError):
            mad.RuntimeDirectoryMonitor(Reader([Snap()]), 101, "1" * 32, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
