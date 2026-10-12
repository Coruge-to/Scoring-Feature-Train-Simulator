import os
import pathlib
import subprocess
import sys
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
for path in (str(ROOT), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import main
import managed_app_directory as directory
from app_directory_fixture import AppDirectoryFixture
import test_managed_hud_e4 as E4


class Args(object):
    def __init__(self, owner="caller", pid=812345, instance=None):
        self.owner = owner
        self.bve_pid = pid
        self.instance = instance or uuid.uuid4().hex


class FakeReader(object):
    def __init__(self, snapshot=None, opened=True, failure=None, raises=False):
        self.last = snapshot
        self.opened = opened
        self.open_failure = failure
        self.raises = raises
        self.closed = 0

    def open(self):
        if self.raises:
            raise RuntimeError("probe")
        return self.opened

    def close(self):
        self.closed += 1


class Snapshot(object):
    def __init__(self, args, app_pid=None):
        self.bve_pid = args.bve_pid
        self.instance = args.instance
        self.app_pid = os.getpid() if app_pid is None else app_pid
        self.instance_published = True
        self.process_started = True
        self.ready_accepted = False
        self.withdrawing = False
        self.closed = False


class ProductPreflightUnit(unittest.TestCase):
    def call(self, args, reader):
        opened, reason = main._open_managed_app_directory(args, lambda _pid: reader)
        self.assertIs(opened, reader if args.owner == "caller" else None)
        return reason

    def test_test_owner_keeps_the_existing_contract(self):
        reader = FakeReader(raises=True)
        self.assertIsNone(main._open_managed_app_directory(Args(owner="test"), lambda _pid: reader)[1])
        self.assertEqual(reader.closed, 0)

    def test_matching_caller_identity_is_accepted_before_ready_accepted(self):
        args = Args()
        self.assertIsNone(self.call(args, FakeReader(Snapshot(args))))

    def test_missing_and_invalid_identity_are_fail_closed(self):
        args = Args()
        cases = []
        cases.append((FakeReader(opened=False, failure="block-missing"), "block-missing"))
        cases.append((FakeReader(None), "snapshot-unavailable"))
        snap = Snapshot(args); snap.bve_pid += 1; cases.append((FakeReader(snap), "bve-pid-mismatch"))
        snap = Snapshot(args); snap.instance = uuid.uuid4().hex; cases.append((FakeReader(snap), "instance-mismatch"))
        snap = Snapshot(args); snap.instance_published = False; cases.append((FakeReader(snap), "instance-not-published"))
        snap = Snapshot(args); snap.process_started = False; cases.append((FakeReader(snap), "process-not-started"))
        snap = Snapshot(args, os.getpid() + 1000); cases.append((FakeReader(snap), "app-pid-mismatch"))
        snap = Snapshot(args); snap.withdrawing = True; cases.append((FakeReader(snap), "withdrawing"))
        snap = Snapshot(args); snap.closed = True; cases.append((FakeReader(snap), "closed"))
        cases.append((FakeReader(raises=True), "read-error:RuntimeError"))
        for reader, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.call(args, reader), expected)


@unittest.skipUnless(os.name == "nt" and E4.HAS_QT, "Windows and PyQt6 are required")
class ProductPreflightProcess(unittest.TestCase):
    def test_real_main_caller_identity_reaches_ready_and_closes_cleanly(self):
        if not E4.port_54321_is_free():
            self.skipTest("UDP 54321 is busy; a running TS Scoring is not touched")
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)
        env["PYTHONIOENCODING"] = "utf-8"
        window = subprocess.Popen([sys.executable, str(TESTS / "fake_bve_window.py"), "60"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=str(ROOT), env=env, creationflags=0x08000000)
        proc = None
        owner = fixture = reader = None
        try:
            ready_line = window.stdout.readline().decode("utf-8", "replace")
            self.assertIn("READY pid=", ready_line)
            bve_pid = int(ready_line.split("pid=")[1].split()[0])
            args = E4.args_for(pid=bve_pid, owner="caller")
            owner = E4.Owner(args)
            owner.block.publish(session=False, driving=False, generation=0)
            fixture = AppDirectoryFixture(args.bve_pid, args.instance)
            reader = directory.DirectoryReader(args.bve_pid)
            self.assertTrue(reader.open(), reader.open_failure)
            argv = [sys.executable, str(ROOT / "main.py"), "--managed", "--owner", "caller",
                    "--bve-pid", str(args.bve_pid), "--instance", args.instance]
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=str(ROOT), env=env, creationflags=0x08000000)
            fixture.publish_process_started(proc.pid)
            self.assertTrue(E4.wait_until(owner.ready, 30), "main.py did not publish AppReady")
            fixture.publish_ready_accepted()
            snap = reader.poll()
            self.assertEqual((snap.app_pid, snap.instance, snap.usable), (proc.pid, args.instance, True))
            owner.sync.set_event(owner.stop)
            code = proc.wait(8)
            stderr = proc.stderr.read().decode("utf-8", "replace")
            self.assertEqual(code, 0, stderr)
            fixture.publish_withdrawing()
            fixture.publish_closed()
            self.assertTrue(reader.poll().closed)
            self.assertTrue(E4.wait_until(E4.port_54321_is_free, 10))
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill(); proc.communicate(timeout=10)
            if reader is not None: reader.close()
            if fixture is not None: fixture.close()
            if owner is not None: owner.close()
            if window.poll() is None:
                window.kill(); window.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
