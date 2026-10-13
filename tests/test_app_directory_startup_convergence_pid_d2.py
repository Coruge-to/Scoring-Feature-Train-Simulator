import os
import types
import unittest

import main

class Snapshot:
    def __init__(self, started=False, app_pid=0, withdrawing=False, closed=False):
        self.bve_pid = 123
        self.instance = "a" * 32
        self.instance_published = True
        self.process_started = started
        self.app_pid = app_pid
        self.withdrawing = withdrawing
        self.closed = closed

class Reader:
    def __init__(self, _pid, snapshots):
        self.snapshots = list(snapshots)
        self.last = self.snapshots.pop(0)
        self.last_rejection = None
        self.open_failure = None
    def open(self):
        return True
    def poll(self):
        if self.snapshots:
            self.last = self.snapshots.pop(0)
        return self.last

def args():
    return types.SimpleNamespace(owner="caller", bve_pid=123, instance="a" * 32)

class StartupConvergenceTests(unittest.TestCase):
    def test_waits_for_process_started_and_matching_pid(self):
        reader, error = main._open_managed_app_directory(
            args(), lambda pid: Reader(pid, [Snapshot(), Snapshot(True, os.getpid())]),
            startup_timeout=1.0, sleep=lambda seconds: None,
            clock=iter([0.0, 0.1]).__next__)
        self.assertIsNone(error)
        self.assertTrue(reader.last.process_started)

    def test_timeout_is_bounded(self):
        reader, error = main._open_managed_app_directory(
            args(), lambda pid: Reader(pid, [Snapshot()]), startup_timeout=1.0,
            sleep=lambda seconds: None, clock=iter([0.0, 2.0]).__next__)
        self.assertEqual("process-started-timeout", error)

    def test_instance_mismatch_is_immediate(self):
        snap = Snapshot()
        snap.instance = "b" * 32
        reader, error = main._open_managed_app_directory(
            args(), lambda pid: Reader(pid, [snap]), sleep=lambda seconds: self.fail("must not sleep"))
        self.assertEqual("instance-mismatch", error)

    def test_withdrawing_is_immediate(self):
        reader, error = main._open_managed_app_directory(
            args(), lambda pid: Reader(pid, [Snapshot(withdrawing=True)]),
            sleep=lambda seconds: self.fail("must not sleep"))
        self.assertEqual("withdrawing", error)

    def test_nonzero_pid_before_started_is_rejected(self):
        reader, error = main._open_managed_app_directory(
            args(), lambda pid: Reader(pid, [Snapshot(app_pid=999)]),
            sleep=lambda seconds: self.fail("must not sleep"))
        self.assertEqual("app-pid-before-process-started", error)

if __name__ == "__main__":
    unittest.main()
