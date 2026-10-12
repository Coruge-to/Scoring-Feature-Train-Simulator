"""AD3A: AppDirectory fixture connected to the real E2, E4 and SI-A3 process paths."""
import os
import pathlib
import subprocess
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
for path in (str(ROOT), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import managed_app_directory as directory
from app_directory_fixture import AppDirectoryFixture
import test_managed_mode_e2 as E2
import test_managed_hud_e4 as E4

CREATE_NO_WINDOW = 0x08000000


@unittest.skipUnless(os.name == "nt", "Windows named mappings are required")
class ProcessPathContract(unittest.TestCase):
    def setUp(self):
        self.procs = []
        self.resources = []

    def tearDown(self):
        for proc in reversed(self.procs):
            if proc.poll() is None:
                proc.kill()
            try:
                proc.communicate(timeout=10)
            except Exception:
                pass
        for resource in reversed(self.resources):
            try:
                resource.close()
            except Exception:
                try:
                    resource.dispose()
                except Exception:
                    pass

    def track(self, resource):
        self.resources.append(resource)
        return resource

    def launch(self, command, env=None):
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(ROOT), env=env, creationflags=CREATE_NO_WINDOW)
        self.procs.append(proc)
        return proc

    def reader(self, pid):
        reader = self.track(directory.DirectoryReader(pid))
        self.assertTrue(reader.open(), reader.open_failure)
        return reader

    def assert_started(self, fixture, reader, proc):
        fixture.publish_process_started(proc.pid)
        snap = reader.poll()
        self.assertEqual((snap.instance, snap.app_pid, snap.process_started, snap.usable),
                         (fixture.instance, proc.pid, True, False))

    def assert_ready(self, fixture, reader):
        fixture.publish_ready_accepted()
        snap = reader.poll()
        self.assertTrue(snap.ready_accepted)
        self.assertTrue(snap.usable)

    def assert_withdrawn_and_closed(self, fixture, reader):
        fixture.publish_withdrawing()
        snap = reader.poll()
        self.assertTrue(snap.withdrawing)
        self.assertFalse(snap.usable)
        fixture.publish_closed()
        snap = reader.poll()
        self.assertEqual((snap.instance, snap.app_pid, snap.flags), ("", 0, directory.FLAG_CLOSED))

    @unittest.skipUnless(E2.HAS_QT, "PyQt6 is required")
    def test_e2_real_managed_child_has_one_directory_identity(self):
        args = E2.args_for(pid=971001)
        owner = self.track(E2.Owner(E2.mm.Win32Sync(), args))
        fixture = self.track(AppDirectoryFixture(args.bve_pid, args.instance))
        reader = self.reader(args.bve_pid)
        env = dict(os.environ)
        env["TSS_E2_FAKE"] = "ok"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = self.launch([sys.executable, E2.CHILD] + E2.argv_for(args), env)
        self.assert_started(fixture, reader, proc)
        self.assertTrue(E2.wait_until(owner.ready, 20), "E2 child did not publish Ready")
        self.assert_ready(fixture, reader)
        owner.set_stop()
        code = proc.wait(5)
        self.assertEqual(code, 0, proc.stderr.read().decode("utf-8", "replace"))
        self.assert_withdrawn_and_closed(fixture, reader)

    @unittest.skipUnless(E4.HAS_QT, "PyQt6 is required")
    def test_e4_real_hud_child_has_one_directory_identity(self):
        args = E4.args_for(pid=971002)
        owner = self.track(E4.Owner(args))
        fixture = self.track(AppDirectoryFixture(args.bve_pid, args.instance))
        reader = self.reader(args.bve_pid)
        owner.block.publish(session=False, driving=False, generation=0)
        env = dict(os.environ)
        env["TSS_E4_CHILD"] = "ok"
        env["PYTHONIOENCODING"] = "utf-8"
        argv = [sys.executable, E4.CHILD, "--managed", "--owner", args.owner,
                "--bve-pid", str(args.bve_pid), "--instance", args.instance]
        proc = self.launch(argv, env)
        self.assert_started(fixture, reader, proc)
        self.assertTrue(E4.wait_until(owner.ready, 20), "E4 child did not publish Ready")
        self.assert_ready(fixture, reader)
        owner.sync.set_event(owner.stop)
        code = proc.wait(5)
        self.assertEqual(code, 0, proc.stderr.read().decode("utf-8", "replace"))
        self.assert_withdrawn_and_closed(fixture, reader)

    @unittest.skipUnless(E4.HAS_QT, "PyQt6 is required")
    def test_sia3_real_main_process_has_one_directory_identity(self):
        if not E4.port_54321_is_free():
            self.skipTest("UDP 54321 is busy; a running TS Scoring is not touched")
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)
        env["PYTHONIOENCODING"] = "utf-8"
        window = self.launch([sys.executable, str(TESTS / "fake_bve_window.py"), "60"], env)
        ready_line = window.stdout.readline().decode("utf-8", "replace")
        self.assertIn("READY pid=", ready_line)
        bve_pid = int(ready_line.split("pid=")[1].split()[0])
        args = E4.args_for(pid=bve_pid)
        owner = self.track(E4.Owner(args))
        fixture = self.track(AppDirectoryFixture(args.bve_pid, args.instance))
        reader = self.reader(args.bve_pid)
        owner.block.publish(session=False, driving=False, generation=0)
        argv = [sys.executable, str(ROOT / "main.py"), "--managed", "--owner", "test",
                "--bve-pid", str(args.bve_pid), "--instance", args.instance]
        proc = self.launch(argv, env)
        self.assert_started(fixture, reader, proc)
        self.assertTrue(E4.wait_until(owner.ready, 30), "main.py did not publish AppReady")
        self.assert_ready(fixture, reader)
        owner.sync.set_event(owner.stop)
        code = proc.wait(5)
        self.assertEqual(code, 0, proc.stderr.read().decode("utf-8", "replace"))
        self.assert_withdrawn_and_closed(fixture, reader)
        self.assertTrue(E4.wait_until(E4.port_54321_is_free, 10))


if __name__ == "__main__":
    unittest.main(verbosity=2)
