"""Parent-exit fix tests: a managed Python started by the Caller (`--owner caller`) ends by itself when the BVE process named by --bve-pid is gone.

    C:\\Python314\\python.exe -m unittest discover -s tests -p "test_parent_exit_p1.py" -v

Incident (real machine, LI0-A): BVE PID 34044 vanished without a Stop request; the managed Python PID 30380 lived on and held UDP 54321, so the
managed Python of the next BVE (PID 26644) failed twice with `udp-bind-failed` (exit code 2) and the HUD never appeared.

Layers: (A) lifecycle against an in-memory fake with a process table, (B) the same watch against real Windows process handles, (C) real child
processes (fake Overlay with a real UDP socket and a real window, the real HUD controller and Stop watcher, the real main.py), (D) a 32-bit Caller,
(E) static guards. Fake BVE processes are throw-away `python -c sleep` processes started by the tests: the user's BVE is never touched, and no BVE,
BveEX or Caller is started. Tests that need UDP 54321 (real main.py) run only when the port is free.
"""
import ctypes
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import managed_mode as mm  # noqa: E402
from test_managed_mode_e2 import (FakeSync, HAS_QT, Log, Owner, StateBlockStandIn, args_for, new_instance, port_54321_is_free,  # noqa: E402
                                  wait_until)

HUD_CHILD = os.path.join(HERE, "parent_exit_child.py")
SMOKE_CHILD = os.path.join(HERE, "managed_smoke_child.py")
CREATE_NO_WINDOW = 0x08000000
WOW64_POWERSHELL = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SysWOW64", "WindowsPowerShell", "v1.0", "powershell.exe")


# ---------------------------------------------------------------------------------------------------------------------------------------
class FakeProcSync(FakeSync):
    """FakeSync plus a process table: processes are signaled objects, open_process hands out a handle to the OBJECT (as the real one does),
    so a pid that is later given to another process does not change what an already opened handle means."""

    def __init__(self, world=None, own_created=5000):
        FakeSync.__init__(self, world)
        self.procs = {}
        self.own_created = own_created
        self._handle_created = {}
        self.open_calls = []
        self.deny = set()
        self.raise_on_open = False

    def add_process(self, pid, created=1000):
        self.procs[pid] = (self._Obj(), created)

    def end_process(self, pid):
        with self.cond:
            self.procs[pid][0].signaled = True
            self.cond.notify_all()

    def recycle_pid(self, pid, created):
        """The pid now belongs to a NEW, living process."""
        self.procs[pid] = (self._Obj(), created)

    def open_process(self, pid):
        self.open_calls.append(pid)
        if self.raise_on_open:
            raise OSError("fake open failure")
        if pid in self.deny:
            return None, 5
        if pid not in self.procs:
            return None, 87
        obj, created = self.procs[pid]
        handle = self._new_handle(obj)
        self._handle_created[handle] = created
        return handle, 0

    def process_created(self, handle):
        return self.own_created if handle is None else self._handle_created[handle]

    def close(self, h):
        self._handle_created.pop(h, None)
        FakeSync.close(self, h)


BVE_PID = 880001


class Rig(object):
    """One lifecycle + its Owner on a FakeProcSync. The 'BVE' (BVE_PID) is a living process older than the application unless told otherwise."""

    def __init__(self, owner="caller", parent=True, sync=None, bve_pid=BVE_PID):
        self.sync = sync or FakeProcSync()
        if parent and bve_pid not in self.sync.procs:
            self.sync.add_process(bve_pid, created=1000)
        self.args = args_for(pid=bve_pid, owner=owner)
        self.owner = Owner(self.sync, self.args)
        self.log = Log()
        self.life = mm.ManagedLifecycle(self.args, self.sync, self.log)
        self.notified = []
        self.ready_at_notify = []

    def _notify(self):
        self.ready_at_notify.append(self.life.ready_published)
        self.notified.append(time.monotonic())

    def boot(self):
        code = self.life.acquire()
        if code is not None:
            return code
        self.life.start_stop_watch(self._notify)
        self.life.publish_ready()
        return None

    def wait_notified(self, count=1, seconds=3.0):
        return wait_until(lambda: len(self.notified) >= count, seconds)

    def handles_left(self):
        """Handles still open except the Owner's own Stop handle: must be none once the application ended."""
        return len(self.sync._handles) - 1


class A_FakeLifecycle(unittest.TestCase):
    def test_parent_alive_keeps_running(self):
        r = Rig()
        self.assertIsNone(r.boot())
        time.sleep(0.4)
        self.assertEqual(r.life.state, mm.STATE_READY)
        self.assertTrue(r.life.ready_published)
        self.assertTrue(r.owner.ready())
        self.assertEqual(r.notified, [])
        self.assertEqual(len(r.log.events("parent-watch-armed")), 1)
        r.owner.set_stop()
        self.assertTrue(r.wait_notified())
        self.assertEqual(r.life.shutdown(), 0)

    def test_stop_event_contract_is_unchanged_with_the_watch(self):
        r = Rig()
        r.boot()
        r.owner.set_stop()
        self.assertTrue(r.wait_notified())
        self.assertEqual(r.ready_at_notify, [False])               # Ready withdrawn before the hand-over
        self.assertEqual(r.life.shutdown(), mm.EXIT_OK)
        self.assertEqual(r.life.exit_reason, "stop-requested")
        self.assertFalse(r.owner.ready())
        self.assertEqual(r.handles_left(), 0)

    def test_parent_exit_without_stop_ends_by_itself(self):
        r = Rig()
        r.boot()
        self.assertTrue(r.owner.ready())
        r.sync.end_process(BVE_PID)
        self.assertTrue(r.wait_notified())
        self.assertEqual(r.ready_at_notify, [False])               # Ready withdrawn first
        self.assertFalse(r.owner.ready())
        self.assertEqual(r.life.shutdown(), mm.EXIT_OK)
        self.assertEqual(r.life.exit_reason, mm.REASON_PARENT_EXITED)
        self.assertNotEqual(r.life.exit_reason, "stop-requested")  # told apart from the Stop request
        self.assertEqual(len(r.log.events("watcher-ended")), 1)
        self.assertEqual(r.handles_left(), 0)                       # the owner-process handle was closed too
        self.assertEqual(len(r.log.events("exit")), 1)
        self.assertIn("reason=parent-process-exited", r.log.events("exit")[0])

    def test_parent_handle_is_closed_in_every_ending(self):
        for how in ("stop", "parent", "shutdown-only"):
            r = Rig()
            r.boot()
            if how == "stop":
                r.owner.set_stop()
                r.wait_notified()
            elif how == "parent":
                r.sync.end_process(BVE_PID)
                r.wait_notified()
            r.life.shutdown()
            self.assertEqual(r.handles_left(), 0, how)

    def test_parent_exit_before_the_watcher_starts_never_publishes_ready(self):
        r = Rig()
        self.assertIsNone(r.life.acquire())
        r.sync.end_process(BVE_PID)
        r.life.start_stop_watch(r._notify)
        self.assertFalse(r.life.publish_ready())
        self.assertFalse(r.owner.ready())
        self.assertTrue(r.wait_notified())
        self.assertEqual(r.life.shutdown(), 0)
        self.assertEqual(r.life.exit_reason, mm.REASON_PARENT_EXITED)
        self.assertIn("ready_published=false", r.log.events("exit")[0])

    def test_stop_and_parent_exit_at_once_end_the_process_once(self):
        # (a) both signaled before the watcher exists, (b) both signaled atomically while it waits: Stop wins, one hand-over, one exit line
        for phase in ("before", "while-waiting"):
            r = Rig()
            if phase == "before":
                self.assertIsNone(r.life.acquire())
                r.sync.end_process(BVE_PID)
                r.owner.set_stop()
                r.life.start_stop_watch(r._notify)
            else:
                r.boot()
                with r.sync.cond:
                    r.sync.procs[BVE_PID][0].signaled = True
                    r.sync._handles[r.owner.stop].signaled = True
                    r.sync.cond.notify_all()
            self.assertTrue(r.wait_notified(), phase)
            time.sleep(0.1)
            self.assertEqual(len(r.notified), 1, phase)
            self.assertEqual(r.life.shutdown(), 0)
            self.assertEqual(r.life.exit_reason, "stop-requested", phase)
            self.assertEqual(len(r.log.events("exit")), 1, phase)
            self.assertEqual(len(r.log.events("stop-received")), 1, phase)
            self.assertEqual(r.handles_left(), 0, phase)

    def test_racing_stop_and_parent_exit_never_end_twice(self):
        rnd = random.Random(20261010)
        for i in range(80):
            r = Rig()
            r.boot()
            barrier = threading.Barrier(2)

            def do_stop():
                barrier.wait()
                time.sleep(rnd_delay[0])
                r.owner.set_stop()

            def do_parent():
                barrier.wait()
                time.sleep(rnd_delay[1])
                r.sync.end_process(BVE_PID)

            rnd_delay = (rnd.random() * 0.003, rnd.random() * 0.003)
            threads = [threading.Thread(target=do_stop), threading.Thread(target=do_parent)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertTrue(r.wait_notified(), i)
            time.sleep(0.02)
            self.assertEqual(len(r.notified), 1, i)
            self.assertEqual(r.life.shutdown(), 0, i)
            self.assertIn(r.life.exit_reason, ("stop-requested", mm.REASON_PARENT_EXITED), i)
            self.assertEqual(len(r.log.events("exit")), 1, i)
            self.assertEqual(len(r.log.events("stop-received")), 1, i)
            self.assertEqual(r.handles_left(), 0, i)

    def test_parent_missing_at_start_exits_four_and_never_publishes_ready(self):
        r = Rig(parent=False)
        self.assertEqual(r.boot(), mm.EXIT_INIT_FAILED)
        self.assertEqual(r.life.state, mm.STATE_STOPPED)
        self.assertEqual(r.life.exit_reason, "parent-process-missing")
        self.assertFalse(r.owner.ready())
        self.assertEqual(r.log.events("ready-published"), [])
        self.assertIn("ready_published=false", r.log.events("exit")[0])
        self.assertEqual(r.handles_left(), 0)

    def test_recycled_pid_at_start_is_not_taken_for_the_owner(self):
        r = Rig(parent=False)
        r.sync.add_process(BVE_PID, created=9000)                  # born AFTER this application: cannot be the process that started it
        self.assertEqual(r.boot(), mm.EXIT_INIT_FAILED)
        self.assertEqual(r.life.exit_reason, "parent-process-missing:pid-reused")
        self.assertEqual(r.handles_left(), 0)

    def test_owner_already_exited_at_start_is_missing(self):
        r = Rig()
        r.sync.end_process(BVE_PID)                                # the process object lingers (someone holds a handle) but has ended
        self.assertEqual(r.boot(), mm.EXIT_INIT_FAILED)
        self.assertEqual(r.life.exit_reason, "parent-process-missing:already-exited")
        self.assertEqual(r.handles_left(), 0)

    def test_unwatchable_owner_fails_closed(self):
        r = Rig()
        r.sync.deny.add(BVE_PID)
        self.assertEqual(r.boot(), mm.EXIT_INIT_FAILED)
        self.assertEqual(r.life.exit_reason, "parent-process-unwatchable:win32-5")
        r2 = Rig()
        r2.sync.raise_on_open = True
        self.assertEqual(r2.boot(), mm.EXIT_INIT_FAILED)
        self.assertEqual(r2.life.exit_reason, "parent-process-unwatchable:OSError")
        self.assertEqual(r2.handles_left(), 0)

    def test_recycled_pid_after_open_does_not_confuse_the_watch(self):
        r = Rig()
        r.boot()
        r.sync.end_process(BVE_PID)
        r.sync.recycle_pid(BVE_PID, created=7000)                  # the number now names a living stranger
        self.assertTrue(r.wait_notified())                          # the HANDLE names the old process: its end is seen
        r.life.shutdown()
        self.assertEqual(r.life.exit_reason, mm.REASON_PARENT_EXITED)
        self.assertEqual(r.sync.open_calls, [BVE_PID])              # the pid is looked up once, at start, never searched again

    def test_recycled_pid_while_owner_lives_keeps_running(self):
        r = Rig()
        r.boot()
        r.sync.recycle_pid(BVE_PID, created=7000)                  # a number reused by another process does not end a watch on the real owner
        time.sleep(0.3)
        self.assertEqual(r.life.state, mm.STATE_READY)
        r.owner.set_stop()
        r.wait_notified()
        r.life.shutdown()

    def test_other_owner_tokens_and_manual_mode_are_not_watched(self):
        for owner in ("manual-test", "test", "callers", "caller2"):
            r = Rig(owner=owner, parent=False)                      # there is no such process at all
            self.assertIsNone(r.boot(), owner)
            self.assertEqual(r.sync.open_calls, [], owner)
            r.sync.procs[BVE_PID] = (r.sync._Obj(), 1)
            r.sync.end_process(BVE_PID)
            time.sleep(0.15)
            self.assertEqual(r.life.state, mm.STATE_READY, owner)
            self.assertEqual(r.notified, [], owner)
            r.owner.set_stop()
            r.wait_notified()
            self.assertEqual(r.life.shutdown(), 0)
            self.assertEqual(r.life.exit_reason, "stop-requested")
        self.assertFalse(mm.ManagedArgs(5, "a" * 32, "manual-test").watches_parent)
        self.assertTrue(mm.ManagedArgs(5, "a" * 32, "caller").watches_parent)

    def test_failure_paths_keep_their_exit_codes(self):
        r = Rig()
        r.boot()
        r.life.fail(mm.EXIT_RUNTIME_ERROR, "unhandled-exception")
        r.sync.end_process(BVE_PID)                                # a later parent exit must not change the first terminal reason
        time.sleep(0.1)
        self.assertEqual(r.life.shutdown(), mm.EXIT_RUNTIME_ERROR)
        self.assertEqual(r.life.exit_reason, "unhandled-exception")

    def test_broken_pipes_to_a_vanished_owner_do_not_turn_the_exit_code_into_120(self):
        class Broken(object):
            def write(self, text):
                raise BrokenPipeError("pipe closed")

            def flush(self):
                raise BrokenPipeError("pipe closed")

        saved = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = Broken(), Broken()
            mm.stderr_log("[MANAGED] event=probe")                  # a failed write mutes stderr ...
            self.assertNotIsInstance(sys.stderr, Broken)
            mm.settle_std_streams()                                 # ... and the final settle replaces a stdout whose flush fails
            self.assertNotIsInstance(sys.stdout, Broken)
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            sys.stdout, sys.stderr = saved

    def test_diagnostics_carry_no_path(self):
        r = Rig()
        r.boot()
        r.sync.end_process(BVE_PID)
        r.wait_notified()
        r.life.shutdown()
        for line in r.log.lines:
            self.assertNotIn("\\Users", line)
            self.assertTrue(line.startswith("[MANAGED] event="))


# ---------------------------------------------------------------------------------------------------------------------------------------
def start_fake_bve():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)


def kill_and_wait(p):
    if p.poll() is None:
        p.kill()
    p.wait(timeout=10)


def process_exit_code(pid, seconds):
    """(exited, code) for a process that is not our child. exited=True with code None when it is already gone."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(0x00100000 | 0x1000, False, pid)
    if not h:
        return True, None
    try:
        if k.WaitForSingleObject(h, int(seconds * 1000)) != 0:
            return False, None
        code = wintypes.DWORD()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        return True, int(code.value)
    finally:
        k.CloseHandle(h)


class NowIsMyBirthSync(mm.Win32Sync):
    """Real handles, but this (test) process pretends to have been created just now: the lifecycle under test runs inside the test process, which is
    OLDER than the fake BVE it starts, whereas the real application is always younger than its owner."""

    def process_created(self, handle):
        if handle is None:
            return int((time.time() + 11644473600) * 10000000)
        return mm.Win32Sync.process_created(self, handle)


class B_Win32Lifecycle(unittest.TestCase):
    """The same watch against real process handles (no Qt)."""

    def setUp(self):
        self.bve = start_fake_bve()
        self.sync = NowIsMyBirthSync()
        time.sleep(0.2)
        self.rig = Rig(sync=self.sync, parent=False, bve_pid=self.bve.pid)

    def tearDown(self):
        kill_and_wait(self.bve)

    def test_alive_then_killed_parent_ends_the_application(self):
        r = self.rig
        self.assertIsNone(r.boot())
        time.sleep(0.4)
        self.assertEqual(r.life.state, mm.STATE_READY)
        self.bve.kill()
        self.assertTrue(r.wait_notified(seconds=5.0))
        self.assertEqual(r.life.shutdown(), 0)
        self.assertEqual(r.life.exit_reason, mm.REASON_PARENT_EXITED)

    def test_missing_pid_and_dead_pid(self):
        r = Rig(sync=NowIsMyBirthSync(), parent=False, bve_pid=4000000001)
        self.assertEqual(r.boot(), mm.EXIT_INIT_FAILED)
        self.assertEqual(r.life.exit_reason, "parent-process-missing")
        dead = start_fake_bve()
        pid = dead.pid
        kill_and_wait(dead)
        r2 = Rig(sync=NowIsMyBirthSync(), parent=False, bve_pid=pid)
        self.assertEqual(r2.boot(), mm.EXIT_INIT_FAILED)
        self.assertTrue(r2.life.exit_reason.startswith("parent-process-missing"), r2.life.exit_reason)
        self.assertFalse(r2.owner.ready())

    def test_a_process_younger_than_the_application_is_not_its_owner(self):
        # the creation-time rule on real handles: a process started after this one is "younger" and so cannot have started it
        sync = mm.Win32Sync()
        own_t = sync.process_created(None)
        self.assertIsNotNone(own_t)
        older, _ = sync.open_process(self.bve.pid)
        younger_proc = start_fake_bve()
        try:
            younger, _ = sync.open_process(younger_proc.pid)
            self.assertGreater(sync.process_created(younger), own_t)
            self.assertGreaterEqual(sync.process_created(younger), sync.process_created(older))
            sync.close(younger)
        finally:
            sync.close(older)
            kill_and_wait(younger_proc)

    def test_current_process_times_are_readable(self):
        self.assertGreater(mm.Win32Sync().process_created(None), 0)


# ---------------------------------------------------------------------------------------------------------------------------------------
def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def can_bind(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def spawn(script, bve_pid, instance, owner, env_extra=None, main_py=False):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TSS_E2_FAKE"] = "ok"
    if env_extra:
        env.update(env_extra)
    argv = [sys.executable, script, "--managed", "--owner", owner, "--bve-pid", str(bve_pid), "--instance", instance]
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT, creationflags=CREATE_NO_WINDOW)


class Scenario(object):
    """One fake BVE + its Stop event + (optionally) a state block + one managed child, with clean-up."""

    def __init__(self, owner="caller", script=HUD_CHILD, port=None, with_block=True, main_py=False):
        self.sync = mm.Win32Sync()
        self.bve = start_fake_bve()
        time.sleep(0.15)
        self.args = args_for(pid=self.bve.pid, owner=owner)
        self.owner = Owner(self.sync, self.args)
        self.block = StateBlockStandIn(self.args) if with_block else None
        env = {"TSS_P1_PORT": str(port)} if port else None
        self.proc = spawn(script, self.bve.pid, self.args.instance, owner, env)

    def ready(self, seconds=30):
        return wait_until(self.owner.ready, seconds)

    def finish(self, seconds=8.0):
        try:
            out, err = self.proc.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, err = self.proc.communicate()
            raise AssertionError("child did not exit in time")
        return self.proc.returncode, err.decode("utf-8", "replace")

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.communicate(timeout=10)
        except Exception:
            pass
        kill_and_wait(self.bve)
        if self.block is not None:
            self.block.dispose()
        self.owner.close()


def lines_with(text, needle):
    return [line for line in text.splitlines() if needle in line]


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter (INCONCLUSIVE for the Qt glue)")
class C_RealProcesses(unittest.TestCase):
    def setUp(self):
        self.scenarios = []

    def tearDown(self):
        for s in self.scenarios:
            s.close()

    def scenario(self, **kw):
        s = Scenario(**kw)
        self.scenarios.append(s)
        return s

    # 1 / 2
    def test_parent_alive_keeps_running_and_stop_still_exits_zero(self):
        s = self.scenario()
        self.assertTrue(s.ready(), "Ready was not published")
        time.sleep(1.5)
        self.assertIsNone(s.proc.poll())                           # the owner lives: nothing ends the application
        self.assertTrue(s.owner.ready())
        started = time.monotonic()
        s.owner.set_stop()
        code, err = s.finish(3.0)
        self.assertEqual(code, 0, err)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertIn("reason=stop-requested", err)
        self.assertNotIn("parent-process-exited", err)
        self.assertFalse(s.owner.ready())

    # 3 / 4 / 5 / 6 / 7
    def test_parent_exit_without_stop_ends_cleanly_and_releases_everything(self):
        port = free_udp_port()
        s = self.scenario(port=port)
        self.assertTrue(s.ready(), "Ready was not published")
        time.sleep(0.5)                                           # the stand-in HUD window opens 150 ms after Ready
        self.assertIsNone(s.proc.poll())
        started = time.monotonic()
        s.bve.kill()                                               # no Stop request, no Caller: the owner just vanishes
        code, err = s.finish(8.0)
        elapsed = time.monotonic() - started
        self.assertEqual(code, 0, err)
        self.assertLess(elapsed, 5.0)
        self.assertIn("reason=parent-process-exited", err)
        self.assertNotIn("reason=stop-requested", err)
        self.assertIn("ready_published=true", err)
        self.assertIn("event=ready-withdrawn", err)                 # Ready withdrawn
        self.assertFalse(s.owner.ready())
        self.assertIn("[P1] window-open", err)                      # there was a HUD window ...
        self.assertIn("[P1] window-closed", err)                    # ... and it was closed by the ordinary clean-up
        self.assertIn("[P1] windows-remaining=0", err)              # none is left in the process
        self.assertIn("[P1] udp-closed", err)                       # the socket was closed by the ordinary clean-up
        self.assertIn("event=hud-summary", err)                     # the HUD controller shut down in order
        self.assertEqual(len(lines_with(err, "event=watcher-ended")), 1)   # the watcher ended normally
        self.assertEqual(len(lines_with(err, " event=exit ")), 1)
        self.assertNotIn("watcher-join-timeout", err)
        self.assertNotIn("cleanup-failed", err)
        self.assertTrue(can_bind(port), "the UDP port was not released")
        self.assertTrue(process_exit_code(s.proc.pid, 0.1)[0])

    # 8 (real processes)
    def test_stop_and_parent_exit_at_once_end_once(self):
        for i in range(6):
            s = self.scenario()
            self.assertTrue(s.ready(), i)
            barrier = threading.Barrier(2)

            def stop():
                barrier.wait()
                s.owner.set_stop()

            def kill():
                barrier.wait()
                s.bve.kill()

            threads = [threading.Thread(target=stop), threading.Thread(target=kill)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            code, err = s.finish(8.0)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(lines_with(err, " event=exit ")), 1, err)
            self.assertEqual(len(lines_with(err, " event=stop-received ")), 1, err)
            self.assertEqual(len(lines_with(err, " event=ready-withdrawn")), 1, err)
            self.assertIn("[P1] windows-remaining=0", err)

    # 9 / 10
    def test_owner_missing_at_start_never_publishes_ready(self):
        for label, pid in (("never existed", 4000000001), ("already gone", None)):
            inst = new_instance()
            if pid is None:
                dead = start_fake_bve()
                pid = dead.pid
                kill_and_wait(dead)
            args = mm.ManagedArgs(pid, inst, "caller")
            owner = Owner(mm.Win32Sync(), args)
            try:
                p = spawn(SMOKE_CHILD, pid, inst, "caller")
                out, err = p.communicate(timeout=30)
                err = err.decode("utf-8", "replace")
                self.assertEqual(p.returncode, mm.EXIT_INIT_FAILED, label + err)
                self.assertIn("reason=parent-process-missing", err, label)
                self.assertIn("ready_published=false", err, label)
                self.assertNotIn("event=ready-published", err, label)
                self.assertFalse(owner.ready(), label)
            finally:
                owner.close()

    def test_invalid_pids_are_rejected_by_the_arguments(self):
        for bad in ("0", "abc", "-5", "4294967296", "04", ""):
            p = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py"), "--managed", "--owner", "caller", "--bve-pid", bad, "--instance",
                                  new_instance()], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, creationflags=CREATE_NO_WINDOW)
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, mm.EXIT_ARGS_INVALID, bad)
            self.assertIn(b"reason=invalid-bve-pid", err, bad)

    # 11
    def test_manual_owner_is_not_watched(self):
        s = self.scenario(owner="manual-test")
        self.assertTrue(s.ready())
        s.bve.kill()
        time.sleep(1.5)
        self.assertIsNone(s.proc.poll())                           # exactly the pre-fix behaviour: only the Stop request ends it
        s.owner.set_stop()
        code, err = s.finish(5.0)
        self.assertEqual(code, 0, err)
        self.assertIn("reason=stop-requested", err)
        self.assertNotIn("parent-watch-armed", err)

    # incident, pre-fix equivalent (unwatched owner) -> udp-bind-failed; and with the watch -> clean next start
    def test_incident_reproduction_without_the_watch_then_the_fix(self):
        port = free_udp_port()
        old = self.scenario(owner="manual-test", port=port)        # = the pre-fix program: no watch of the BVE process
        self.assertTrue(old.ready())
        old.bve.kill()                                             # BVE PID 34044 vanishes without a Stop notice
        time.sleep(1.5)
        self.assertIsNone(old.proc.poll(), "the unwatched application must stay alive (the incident)")
        nxt = self.scenario(owner="manual-test", port=port)        # the next BVE session's application
        code, err = nxt.finish(30)
        self.assertEqual(code, mm.EXIT_BIND_FAILED, err)           # twice in the field: udp-bind-failed, exit code 2
        self.assertIn("reason=udp-bind-failed", err)
        self.assertFalse(nxt.owner.ready())
        old.owner.set_stop()
        self.assertEqual(old.finish(5.0)[0], 0)
        # with the fix (owner=caller): the same sequence leaves nothing behind
        fixed = self.scenario(owner="caller", port=port)
        self.assertTrue(fixed.ready())
        fixed.bve.kill()
        code, err = fixed.finish(8.0)
        self.assertEqual(code, 0, err)
        self.assertIn("reason=parent-process-exited", err)
        again = self.scenario(owner="caller", port=port)           # the next BVE session
        self.assertTrue(again.ready(), "the next application could not start")
        again.owner.set_stop()
        code, err = again.finish(5.0)
        self.assertEqual(code, 0, err)
        self.assertNotIn("udp-bind-failed", err)

    # 13 / 15 : the real main.py with the real Overlay on the real UDP 54321
    @unittest.skipUnless(port_54321_is_free(), "UDP 54321 is busy (a running TS Scoring / BVE): INCONCLUSIVE")
    def test_real_main_py_incident_and_fix_on_udp_54321(self):
        main_py = os.path.join(ROOT, "main.py")

        def real(owner):
            s = Scenario(owner=owner, script=main_py)
            self.scenarios.append(s)
            return s

        # pre-fix equivalent: an unwatched owner vanishes -> the application keeps 54321 -> the next one fails with exit code 2
        old = real("manual-test")
        self.assertTrue(old.ready(), "Ready was not published")
        old.bve.kill()
        time.sleep(1.5)
        self.assertIsNone(old.proc.poll())
        nxt = real("manual-test")
        code, err = nxt.finish(30)
        self.assertEqual(code, mm.EXIT_BIND_FAILED, err)
        self.assertIn("reason=udp-bind-failed", err)
        old.owner.set_stop()
        self.assertEqual(old.finish(8.0)[0], 0)
        self.assertTrue(wait_until(port_54321_is_free, 5))
        # the fix
        first = real("caller")
        self.assertTrue(first.ready(), "Ready was not published")
        time.sleep(1.0)
        self.assertIsNone(first.proc.poll())                       # alive owner: keeps running
        first.bve.kill()                                           # no Stop
        code, err = first.finish(8.0)
        self.assertEqual(code, 0, err)
        self.assertIn("reason=parent-process-exited", err)
        self.assertIn("ready_published=true", err)
        self.assertNotIn("watcher-join-timeout", err)
        self.assertTrue(wait_until(port_54321_is_free, 3), "UDP 54321 was not released")
        second = real("caller")                                    # the next BVE session: must NOT be udp-bind-failed
        self.assertTrue(second.ready(), "the next application could not start")
        self.assertIsNone(second.proc.poll())
        second.owner.set_stop()                                    # and the ordinary Stop still works
        code, err = second.finish(8.0)
        self.assertEqual(code, 0, err)
        self.assertIn("reason=stop-requested", err)
        self.assertNotIn("udp-bind-failed", err)


# ---------------------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAS_QT and os.path.exists(WOW64_POWERSHELL), "PyQt6 / 32-bit Windows PowerShell not available")
class D_Win32Caller(unittest.TestCase):
    """A 32-bit process plays the 32-bit BVE + Caller: it starts the 64-bit Python with `--owner caller --bve-pid <its own pid>` and then dies."""

    SCRIPT = r'''
param([string]$Py, [string]$Child, [string]$Out, [string]$Inst)
$ErrorActionPreference = 'Stop'
$bvePid = $PID
$stop = New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$bvePid.App.$Inst.Stop")
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Py
$psi.Arguments = '"' + $Child + '" --managed --owner caller --bve-pid ' + $bvePid + ' --instance ' + $Inst
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardError = $true
$psi.RedirectStandardOutput = $true
$p = [System.Diagnostics.Process]::Start($psi)
Set-Content -Path $Out -Value ("{0} {1} {2}" -f $p.Id, [Environment]::Is64BitProcess, [IntPtr]::Size) -Encoding ASCII
Start-Sleep -Seconds 600
'''

    def test_32bit_caller_launch_and_parent_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "fake32.ps1")
            out = os.path.join(tmp, "info.txt")
            with open(script, "w", encoding="ascii") as f:
                f.write(self.SCRIPT)
            inst = new_instance()
            ps = subprocess.Popen([WOW64_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script, sys.executable,
                                   SMOKE_CHILD, out, inst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                  creationflags=CREATE_NO_WINDOW)
            child_pid = None
            try:
                def info():
                    try:
                        with open(out) as f:
                            return f.read().split()
                    except OSError:
                        return []

                self.assertTrue(wait_until(lambda: len(info()) == 3, 30), "the 32-bit caller did not start")
                pid_text, is64, size = info()
                child_pid = int(pid_text)
                self.assertEqual((is64, size), ("False", "4"))      # really a 32-bit process
                self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8)  # and the application really is the 64-bit Python
                owner = Owner(mm.Win32Sync(), mm.ManagedArgs(ps.pid, inst, "caller"))
                try:
                    self.assertTrue(wait_until(owner.ready, 30), "Ready was not published")
                    time.sleep(1.0)
                    self.assertEqual(process_exit_code(child_pid, 0.0), (False, None))   # alive while the 32-bit owner lives
                    ps.kill()                                        # the 32-bit BVE vanishes; its stdout/stderr pipes break with it
                    ps.wait(timeout=10)
                    exited, code = process_exit_code(child_pid, 8.0)
                    self.assertTrue(exited, "the application survived its 32-bit owner")
                    self.assertEqual(code, 0)
                    self.assertFalse(owner.ready())
                finally:
                    owner.close()
            finally:
                if ps.poll() is None:
                    ps.kill()
                if child_pid is not None and not process_exit_code(child_pid, 0.0)[0]:
                    subprocess.run(["taskkill", "/F", "/PID", str(child_pid)], capture_output=True)


# ---------------------------------------------------------------------------------------------------------------------------------------
def _git(*args):
    try:
        r = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, timeout=60)
    except Exception:
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


class E_StaticGuards(unittest.TestCase):
    def source(self):
        with open(os.path.join(ROOT, "managed_mode.py"), encoding="utf-8") as f:
            return f.read()

    def test_no_kill_no_bve_api_no_polling_of_pids(self):
        src = self.source()
        for forbidden in ("TerminateProcess", "taskkill", ".kill(", "os.kill", "psutil", "EnumProcesses", "CreateToolhelp32Snapshot", "tasklist",
                          "BveEx", "AtsEx", "ReadProcessMemory", "WriteProcessMemory"):
            self.assertFalse(forbidden in src, forbidden)
        self.assertEqual(src.count("OpenProcess("), 1)              # one lookup of the pid, at start; afterwards only the handle is waited on

    def test_normal_mode_and_the_overlay_are_untouched(self):
        self.assertEqual(_git("diff", "HEAD", "--", "main.py", "hud_ui.py", "menu_ui.py", "scoring_logic.py", "network.py", "config.py", "utils.py"),
                         "")

    def test_the_control_plane_is_not_touched_by_this_fix(self):
        # the fix lives in managed_mode.py; the Caller, both Bridges and the shared protocol stay out of it (independent of what else is in the tree)
        changed = (_git("diff", "HEAD", "--name-only") or "").split()
        untracked = (_git("ls-files", "--others", "--exclude-standard") or "").split()
        for path in changed + untracked:
            self.assertFalse(path.startswith(("TsScoringPlugin/Handshake/Caller/", "TsScoringPlugin/Handshake/Bridge/", "TsScoringPlugin/Handshake/Shared/")), path)

    def test_the_e2_e3_contract_of_managed_mode_is_kept(self):
        # replaces the E4 guard "managed_mode.py is unchanged since E3": the fix is additive (the Stop contract, names, exit codes stay as they were)
        numstat = _git("diff", "--numstat", "b9611dad47e2c95f8fa1c89a8bd0286896c75cea", "--", "managed_mode.py")
        if numstat is None:
            self.skipTest("git not available (INCONCLUSIVE)")
        added, deleted, _ = numstat.split()
        self.assertLessEqual(int(deleted), 10, "more than a few E3 lines were rewritten")
        self.assertGreater(int(added), 0)
        self.assertEqual((mm.EXIT_OK, mm.EXIT_RUNTIME_ERROR, mm.EXIT_BIND_FAILED, mm.EXIT_DUPLICATE_INSTANCE, mm.EXIT_INIT_FAILED, mm.EXIT_ARGS_INVALID),
                         (0, 1, 2, 3, 4, 5))
        a = mm.ManagedArgs(77, "a" * 32, "caller")
        self.assertEqual((a.lock_name, a.stop_name, a.ready_name),
                         tuple("Local\\TSScoringPlugin.v1.77.App.%s.%s" % ("a" * 32, k) for k in ("Lock", "Stop", "Ready")))

    def test_py_compile(self):
        import py_compile
        with tempfile.TemporaryDirectory() as d:
            for name in ("managed_mode.py", "tests/parent_exit_child.py", "tests/test_parent_exit_p1.py"):
                py_compile.compile(os.path.join(ROOT, name), cfile=os.path.join(d, "x.pyc"), doraise=True)


if __name__ == "__main__":
    unittest.main()
