"""Phase E2 tests of the Python managed mode. Standard library only (unittest). Run with the interpreter that runs TS Scoring:

    C:\\Python314\\python.exe -m unittest discover -s tests -p "test_managed_mode_e2.py" -v

Layers: (A) argument parsing, (B) lifecycle state machine against an in-memory fake, (C) the same lifecycle against real Windows named
objects, (D) real child processes (fake Overlay, plus the real main.py for argument errors / bind), (E) static guards and regression.
No BVE, no BveEX, no Caller is started; no file is written outside a temp directory; the user's running TS Scoring is not touched.
"""
import ast
import importlib.util
import os
import py_compile
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import managed_mode as mm  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None
CHILD = os.path.join(ROOT, "tests", "managed_smoke_child.py")
BASELINE = "a43f18efca37caf64d33bb7c7d5529efd5b7067b"


def read_text(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return f.read()


def new_instance():
    return uuid.uuid4().hex  # 32 lowercase hex


def fake_pid(seed=4000000001):
    return seed


def args_for(inst=None, pid=777001, owner="test"):
    return mm.ManagedArgs(pid, inst or new_instance(), owner)


def argv_for(args, extra=()):
    return ["--managed", "--owner", args.owner, "--bve-pid", str(args.bve_pid), "--instance", args.instance] + list(extra)


class Log(object):
    def __init__(self):
        self.lines = []
        self._lock = threading.Lock()

    def __call__(self, text):
        with self._lock:
            self.lines.append(text)

    def events(self, name):
        return [line for line in self.lines if (" event=%s " % name) in (line + " ")]


# ---------------------------------------------------------------------------------------------------------------------------------------
class FakeSync(object):
    """In-memory stand-in for Win32Sync with the same semantics (names are shared between FakeSync users via `world`)."""

    class _Obj(object):
        def __init__(self):
            self.signaled = False
            self.refs = 0

    def __init__(self, world=None):
        self.world = world if world is not None else {}
        self.cond = threading.Condition()
        self._handles = {}
        self._next = 100
        self.fail_create = set()

    def _new_handle(self, obj):
        self._next += 1
        self._handles[self._next] = obj
        obj.refs += 1
        return self._next

    def _create(self, name):
        if name in self.fail_create:
            raise OSError("fake create failure")
        existed = False
        if name is None:
            obj = self._Obj()
        else:
            obj = self.world.get(name)
            existed = obj is not None
            if obj is None:
                obj = self.world[name] = self._Obj()
        return self._new_handle(obj), existed

    def create_mutex(self, name):
        return self._create(name)

    def create_event(self, name):
        return self._create(name)

    def open_event(self, name):
        obj = self.world.get(name)
        return None if obj is None else self._new_handle(obj)

    def set_event(self, h):
        with self.cond:
            self._handles[h].signaled = True
            self.cond.notify_all()

    def reset_event(self, h):
        with self.cond:
            self._handles[h].signaled = False

    def is_set(self, h):
        return self._handles[h].signaled

    def close(self, h):
        obj = self._handles.pop(h)
        obj.refs -= 1
        if obj.refs == 0:
            for key, value in list(self.world.items()):
                if value is obj:
                    del self.world[key]

    def wait_any(self, handles, timeout_ms=None):
        deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000.0
        with self.cond:
            while True:
                for index, h in enumerate(handles):
                    if self._handles[h].signaled:
                        return index
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return -1
                self.cond.wait(remaining)


class Owner(object):
    """Plays the Caller: creates the Stop event, observes Ready, sets Stop. Works on any sync implementation."""

    def __init__(self, sync, args):
        self.sync = sync
        self.args = args
        self.stop, _ = sync.create_event(args.stop_name)

    def set_stop(self):
        self.sync.set_event(self.stop)

    def ready(self):
        handle = self.sync.open_event(self.args.ready_name)
        if handle is None:
            return False
        try:
            return self.sync.is_set(handle)
        finally:
            self.sync.close(handle)

    def close(self):
        self.sync.close(self.stop)


def wait_until(predicate, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------------------------------------------------------------------
class A_ArgumentParsing(unittest.TestCase):
    INST = "0123456789abcdef0123456789abcdef"

    def parse(self, *a):
        return mm.parse_managed_args(list(a))

    def test_valid(self):
        args, err = self.parse("--managed", "--owner", "caller", "--bve-pid", "4242", "--instance", self.INST)
        self.assertIsNone(err)
        self.assertEqual((args.bve_pid, args.instance, args.owner), (4242, self.INST, "caller"))
        self.assertEqual(args.stop_name, "Local\\TSScoringPlugin.v1.4242.App.%s.Stop" % self.INST)
        self.assertEqual(args.ready_name, "Local\\TSScoringPlugin.v1.4242.App.%s.Ready" % self.INST)
        self.assertEqual(args.lock_name, "Local\\TSScoringPlugin.v1.4242.App.%s.Lock" % self.INST)

    def test_equals_form_and_order(self):
        args, err = self.parse("--instance=" + self.INST, "--bve-pid=1", "--managed", "--owner=manual-test")
        self.assertIsNone(err)
        self.assertEqual(args.bve_pid, 1)

    def test_flag_detection_is_explicit(self):
        self.assertFalse(mm.is_managed_requested([]))
        self.assertFalse(mm.is_managed_requested(["--instance", self.INST, "--bve-pid", "1"]))
        self.assertFalse(mm.is_managed_requested(["--managed-x"]))
        self.assertTrue(mm.is_managed_requested(["--managed"]))

    def test_missing(self):
        base = ["--managed", "--owner", "t", "--bve-pid", "5", "--instance", self.INST]
        for drop in ("--owner", "--bve-pid", "--instance"):
            argv = list(base)
            i = argv.index(drop)
            del argv[i:i + 2]
            args, err = mm.parse_managed_args(argv)
            self.assertIsNone(args)
            self.assertEqual(err, "missing-option:" + drop)
        self.assertEqual(mm.parse_managed_args(["--owner", "t", "--bve-pid", "5", "--instance", self.INST])[1], "managed-flag-missing")
        self.assertEqual(mm.parse_managed_args(["--managed", "--bve-pid"])[1], "missing-value:--bve-pid")
        self.assertEqual(mm.parse_managed_args(["--managed"])[1], "missing-option:--bve-pid")

    def test_invalid_instance(self):
        base = ["--managed", "--owner", "t", "--bve-pid", "5", "--instance"]
        for bad in ("", "abc", "0123456789ABCDEF0123456789ABCDEF", "0123456789abcdef0123456789abcdef0", "zzzzzzzzzzzzzzzzzzzzzzzz",
                    "0123456789abcdef\\..\\x", "0123456789abcdef.Stop", "0123456789abcde ", "Local\\0123456789abcdef", "0123456789abcdef\n", "0123456789abcdef\r\n"):
            args, err = mm.parse_managed_args(base + [bad])
            self.assertIsNone(args, repr(bad))
            self.assertEqual(err, "invalid-instance", repr(bad))
            if bad.strip():
                self.assertNotIn(bad.strip(), err)  # the value is never echoed

    def test_invalid_bve_pid(self):
        base = ["--managed", "--owner", "t", "--instance", self.INST, "--bve-pid"]
        for bad in ("0", "-5", "abc", "12x", "", "007", "4294967296", "99999999999", "1.5", " 7"):
            args, err = mm.parse_managed_args(base + [bad])
            self.assertIsNone(args, repr(bad))
            self.assertEqual(err, "invalid-bve-pid", repr(bad))
        self.assertIsNotNone(mm.parse_managed_args(base + ["4294967295"])[0])

    def test_invalid_owner_unknown_and_duplicates(self):
        base = ["--managed", "--bve-pid", "5", "--instance", self.INST]
        for bad in ("", "Caller", "1abc", "a" * 17, "a b", "a\\b"):
            self.assertEqual(mm.parse_managed_args(base + ["--owner", bad])[1], "invalid-owner", repr(bad))
        good = base + ["--owner", "t"]
        self.assertEqual(mm.parse_managed_args(good + ["--extra"])[1], "unknown-argument")
        self.assertEqual(mm.parse_managed_args(good + ["--owner", "u"])[1], "duplicate-option:--owner")
        self.assertEqual(mm.parse_managed_args(good + ["--managed"])[1], "duplicate-managed-flag")


# ---------------------------------------------------------------------------------------------------------------------------------------
class LifecycleContract(object):
    """Shared by the fake (B) and the real Win32 (C) variants. Subclasses provide make_sync()."""

    def make_sync(self):
        raise NotImplementedError

    def setUp(self):
        self.sync = self.make_sync()
        self.log = Log()
        self.args = args_for()
        self.owner_sync = self.owner_sync_for(self.sync)
        self.owner = Owner(self.owner_sync, self.args)
        self.notified = threading.Event()
        self.created = []

    def owner_sync_for(self, sync):
        return sync

    def tearDown(self):
        for life in self.created:
            life.shutdown()
        self.owner.close()

    def life(self, args=None, sync=None):
        life = mm.ManagedLifecycle(args or self.args, sync or self.sync, self.log)
        self.created.append(life)
        return life

    def up(self, life=None):
        life = life or self.life()
        self.assertIsNone(life.acquire())
        life.start_stop_watch(self.notified.set)
        self.assertTrue(life.publish_ready())
        return life

    # -- Ready is only set when the contract is complete ---------------------------------------------------------------------------------
    def test_initial_state_has_no_ready(self):
        life = self.life()
        self.assertEqual(life.state, mm.STATE_NEW)
        self.assertFalse(life.ready_published)
        self.assertFalse(self.owner.ready())

    def test_no_ready_before_required_initialisation(self):
        life = self.life()
        self.assertIsNone(life.acquire())
        self.assertFalse(self.owner.ready())          # contract objects open, watcher not started
        self.assertEqual(life.state, mm.STATE_INITIALIZING)
        with self.assertRaises(RuntimeError):
            life.publish_ready()                      # not before the stop watcher runs
        self.assertFalse(self.owner.ready())
        life.start_stop_watch(self.notified.set)
        self.assertFalse(self.owner.ready())          # still not published by itself

    def test_ready_after_initialisation(self):
        life = self.up()
        self.assertTrue(self.owner.ready())
        self.assertTrue(life.ready_published)
        self.assertEqual(life.state, mm.STATE_READY)

    def test_ready_and_stop_are_independent_of_scenario_state_names(self):
        # AppReady is only the Ready object of this instance: no ScenarioReady / Driving object is created or read
        life = self.up()
        names = [n for n in getattr(self.sync, "world", {}) if "ScenarioReady" in n or "Driving" in n or "Session" in n]
        self.assertEqual(names, [])
        self.assertTrue(life.ready_published)

    # -- Stop ---------------------------------------------------------------------------------------------------------------------------
    def test_stop_request_withdraws_ready_and_exits_zero(self):
        life = self.up()
        self.owner.set_stop()
        self.assertTrue(self.notified.wait(3))
        self.assertFalse(self.owner.ready())          # withdrawn before the UI is even told (the callback runs afterwards)
        self.assertTrue(life.stop_requested)
        self.assertEqual(life.shutdown(), mm.EXIT_OK)
        self.assertEqual(life.exit_reason, "stop-requested")
        self.assertEqual(life.state, mm.STATE_STOPPED)

    def test_ready_is_withdrawn_before_notification(self):
        seen = []
        life = self.life()
        life.acquire()
        life.start_stop_watch(lambda: seen.append(self.owner.ready()))
        life.publish_ready()
        self.owner.set_stop()
        self.assertTrue(wait_until(lambda: seen))
        self.assertEqual(seen, [False])

    def test_duplicate_stop_requests_notify_once(self):
        count = []
        life = self.life()
        life.acquire()
        life.start_stop_watch(lambda: count.append(1))
        life.publish_ready()
        self.owner.set_stop()
        self.owner.set_stop()
        self.assertTrue(wait_until(lambda: count))
        self.assertFalse(life.request_stop("again"))   # already stopping: idempotent, no second effect
        self.assertFalse(life.request_stop("again"))
        time.sleep(0.1)
        self.assertEqual(count, [1])
        self.assertEqual(len(self.log.events("stop-received")), 1)

    def test_stop_for_another_instance_is_ignored(self):
        life = self.up()
        other = args_for(pid=self.args.bve_pid)
        other_owner = Owner(self.owner_sync, other)
        try:
            other_owner.set_stop()
            self.assertFalse(self.notified.wait(0.3))
            self.assertTrue(self.owner.ready())
            self.assertFalse(life.stop_requested)
        finally:
            other_owner.close()

    def test_stop_for_another_bve_process_is_ignored(self):
        life = self.up()
        other = mm.ManagedArgs(self.args.bve_pid + 1, self.args.instance, "test")   # same INST, different BVE PID
        other_owner = Owner(self.owner_sync, other)
        try:
            other_owner.set_stop()
            self.assertFalse(self.notified.wait(0.3))
            self.assertFalse(life.stop_requested)
        finally:
            other_owner.close()

    def test_old_stop_of_a_previous_instance_is_not_received(self):
        old = args_for(pid=self.args.bve_pid)
        old_owner = Owner(self.owner_sync, old)
        old_owner.set_stop()                           # left behind, still signaled, handle still open
        try:
            life = self.up()
            self.assertFalse(self.notified.wait(0.3))
            self.assertFalse(life.stop_requested)
            self.assertTrue(self.owner.ready())
        finally:
            old_owner.close()

    def test_stop_set_before_start_up_is_not_lost_and_never_publishes_ready(self):
        self.owner.set_stop()
        life = self.life()
        self.assertIsNone(life.acquire())
        life.start_stop_watch(self.notified.set)
        self.assertTrue(self.notified.wait(3))
        self.assertFalse(life.publish_ready())
        self.assertFalse(self.owner.ready())
        self.assertEqual(life.shutdown(), mm.EXIT_OK)
        self.assertEqual(self.log.events("ready-published"), [])
        self.assertEqual(len(self.log.events("stop-already-set")), 1)

    def test_stop_during_start_up_never_leaves_ready(self):
        life = self.life()
        life.acquire()
        life.start_stop_watch(self.notified.set)
        self.owner.set_stop()
        self.assertTrue(self.notified.wait(3))
        self.assertFalse(life.publish_ready())
        self.assertFalse(self.owner.ready())

    # -- exit codes ---------------------------------------------------------------------------------------------------------------------
    def test_normal_exit_without_stop(self):
        life = self.up()
        self.assertEqual(life.shutdown(), mm.EXIT_OK)
        self.assertEqual(life.exit_reason, "event-loop-ended")
        self.assertFalse(self.owner.ready())

    def test_stop_event_missing_is_an_init_failure(self):
        self.owner.close()
        self.owner = Owner(self.owner_sync, args_for())      # a different instance; ours has no Stop object
        life = self.life()
        self.assertEqual(life.acquire(), mm.EXIT_INIT_FAILED)
        self.assertEqual(life.exit_reason, "stop-event-missing")
        self.assertFalse(self.owner.ready())
        self.assertEqual(self.log.events("ready-published"), [])
        self.assertEqual(life.state, mm.STATE_STOPPED)
        self.assertEqual(life.shutdown(), mm.EXIT_INIT_FAILED)
        # nothing stays open: a retry can take the Lock again
        retry = self.life()
        self.assertEqual(retry.acquire(), mm.EXIT_INIT_FAILED)
        self.assertNotEqual(retry.exit_reason, "duplicate-instance")

    def test_init_failure_after_acquire_leaves_no_ready(self):
        life = self.life()
        life.acquire()
        self.assertTrue(life.fail(mm.EXIT_BIND_FAILED, "udp-bind-failed"))
        self.assertFalse(life.publish_ready())
        self.assertFalse(self.owner.ready())
        self.assertEqual(life.shutdown(), mm.EXIT_BIND_FAILED)

    def test_runtime_exception_withdraws_ready(self):
        life = self.up()
        self.assertTrue(self.owner.ready())
        life.fail(mm.EXIT_RUNTIME_ERROR, "unhandled-exception:ValueError@x.py:1")
        self.assertFalse(self.owner.ready())
        self.assertEqual(life.shutdown(), mm.EXIT_RUNTIME_ERROR)

    def test_first_terminal_reason_wins(self):
        life = self.up()
        life.fail(mm.EXIT_RUNTIME_ERROR, "first")
        life.request_stop("later")
        life.fail(mm.EXIT_BIND_FAILED, "later")
        self.assertEqual(life.shutdown(), mm.EXIT_RUNTIME_ERROR)
        self.assertEqual(life.exit_reason, "first")
        args2 = args_for()
        owner2 = Owner(self.owner_sync, args2)
        try:
            life2 = self.up(self.life(args2))
            life2.request_stop("stop")
            life2.fail(mm.EXIT_RUNTIME_ERROR, "after-stop")
            self.assertEqual(life2.shutdown(), mm.EXIT_OK)
        finally:
            owner2.close()

    def test_exception_in_cleanup_does_not_keep_ready_or_objects(self):
        life = self.up()

        def bad():
            raise RuntimeError("cleanup")
        self.assertEqual(life.shutdown(bad), mm.EXIT_OK)
        self.assertFalse(self.owner.ready())
        self.assertEqual(len(self.log.events("cleanup-failed")), 1)

    def test_shutdown_is_idempotent_and_ends_the_watcher(self):
        life = self.up()
        watcher = life._watcher
        self.assertTrue(watcher.is_alive())
        self.assertEqual(life.shutdown(), mm.EXIT_OK)
        self.assertEqual(life.shutdown(), mm.EXIT_OK)
        self.assertFalse(watcher.is_alive())
        self.assertEqual(len(self.log.events("exit")), 1)

    def test_shutdown_does_not_wait_for_a_stop_that_never_comes(self):
        life = self.up()
        started = time.monotonic()
        life.shutdown()
        self.assertLess(time.monotonic() - started, 1.5)

    # -- duplicate / stale / sequences --------------------------------------------------------------------------------------------------
    def test_duplicate_instance_exits_three_and_keeps_the_first_ready(self):
        first = self.up()
        second = self.life()
        self.assertEqual(second.acquire(), mm.EXIT_DUPLICATE_INSTANCE)
        self.assertEqual(second.exit_reason, "duplicate-instance")
        self.assertTrue(self.owner.ready())            # the duplicate did not touch the first one's Ready
        self.assertFalse(second.ready_published)
        self.assertEqual(second.shutdown(), mm.EXIT_DUPLICATE_INSTANCE)
        self.assertTrue(self.owner.ready())
        self.assertTrue(first.ready_published)

    def test_stale_ready_of_the_same_instance_is_cleared(self):
        stale, _ = self.owner_sync.create_event(self.args.ready_name)
        self.owner_sync.set_event(stale)               # left over and still held by someone
        try:
            life = self.life()
            self.assertIsNone(life.acquire())
            self.assertFalse(self.owner.ready())       # not Ready merely because an old object was signaled
            self.assertEqual(len(self.log.events("ready-stale-cleared")), 1)
            life.start_stop_watch(self.notified.set)
            self.assertTrue(life.publish_ready())
            self.assertTrue(self.owner.ready())
        finally:
            self.owner_sync.close(stale)

    def test_consecutive_launches(self):
        for _ in range(5):
            args = args_for(pid=self.args.bve_pid)
            owner = Owner(self.owner_sync, args)
            life = self.life(args)
            self.assertIsNone(life.acquire())
            life.start_stop_watch(self.notified.set)
            self.assertTrue(life.publish_ready())
            self.assertTrue(owner.ready())
            self.notified.clear()
            owner.set_stop()
            self.assertTrue(self.notified.wait(3))
            self.assertEqual(life.shutdown(), mm.EXIT_OK)
            self.assertFalse(owner.ready())
            owner.close()

    def test_same_instance_can_start_again_after_a_clean_exit(self):
        first = self.up()
        self.assertEqual(first.shutdown(), mm.EXIT_OK)
        self.notified.clear()
        second = self.life()
        self.assertIsNone(second.acquire())
        second.start_stop_watch(self.notified.set)
        self.assertFalse(self.owner.ready())
        self.assertTrue(second.publish_ready())

    def test_parallel_instances_are_isolated(self):
        a = self.up()
        args_b = args_for(pid=self.args.bve_pid)
        owner_b = Owner(self.owner_sync, args_b)
        notified_b = threading.Event()
        b = self.life(args_b)
        b.acquire()
        b.start_stop_watch(notified_b.set)
        b.publish_ready()
        try:
            self.assertTrue(self.owner.ready() and owner_b.ready())
            owner_b.set_stop()
            self.assertTrue(notified_b.wait(3))
            self.assertFalse(self.notified.is_set())
            self.assertTrue(self.owner.ready())
            self.assertFalse(owner_b.ready())
            self.assertEqual(b.shutdown(), mm.EXIT_OK)
            self.assertFalse(a.stop_requested)
        finally:
            owner_b.close()

    def test_zero_one_and_many_events_in_the_world(self):
        # 0 events other than ours (setUp), 1 foreign event, many foreign events: only our own Stop matters
        foreign = [Owner(self.owner_sync, args_for(pid=self.args.bve_pid)) for _ in range(20)]
        try:
            life = self.up()
            for o in foreign:
                o.set_stop()
            self.assertFalse(self.notified.wait(0.3))
            self.assertTrue(self.owner.ready())
            self.owner.set_stop()
            self.assertTrue(self.notified.wait(3))
            self.assertEqual(life.shutdown(), mm.EXIT_OK)
        finally:
            for o in foreign:
                o.close()

    def test_diagnostics_are_state_changes_only_and_carry_no_path(self):
        life = self.up()
        time.sleep(0.3)                                # a quiet period must not produce log lines
        count_quiet = len(self.log.lines)
        time.sleep(0.3)
        self.assertEqual(len(self.log.lines), count_quiet)
        life.shutdown()
        text = "\n".join(self.log.lines)
        for needle in ("C:\\", "Users", "Desktop"):
            self.assertNotIn(needle, text)
        last = self.log.events("exit")[0]
        self.assertIn("code=0", last)
        self.assertIn("ready_published=true", last)


class B_LifecycleFake(LifecycleContract, unittest.TestCase):
    def make_sync(self):
        return FakeSync()

    def test_lock_creation_failure_is_an_init_failure(self):
        self.sync.fail_create.add(self.args.lock_name)
        life = self.life()
        self.assertEqual(life.acquire(), mm.EXIT_INIT_FAILED)
        self.assertTrue(life.exit_reason.startswith("lock-create-failed"))

    def test_event_creation_failure_is_an_init_failure_and_releases_everything(self):
        self.sync.fail_create.add(self.args.ready_name)
        life = self.life()
        self.assertEqual(life.acquire(), mm.EXIT_INIT_FAILED)
        self.assertTrue(life.exit_reason.startswith("ready-create-failed"))
        self.assertNotIn(self.args.lock_name, self.sync.world)       # the Lock was released again
        self.assertNotIn(self.args.ready_name, self.sync.world)

    def test_all_objects_are_released_after_shutdown(self):
        life = self.up()
        life.shutdown()
        self.owner.close()
        self.owner.close = lambda: None
        self.assertEqual(self.sync.world, {})

    def test_gui_independent(self):
        source = read_text(os.path.join(ROOT, "managed_mode.py"))
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(PyQt|scoring_logic|main|hud_ui|menu_ui|keyboard|win32)", source, re.M))


class C_LifecycleWin32(LifecycleContract, unittest.TestCase):
    """The same contract against real Windows named objects (separate Win32Sync objects for the app and the owner)."""

    def make_sync(self):
        return mm.Win32Sync()

    def owner_sync_for(self, sync):
        return mm.Win32Sync()

    def test_names_are_session_local_and_user_input_free(self):
        for name in (self.args.lock_name, self.args.stop_name, self.args.ready_name):
            self.assertTrue(name.startswith("Local\\TSScoringPlugin.v1."))
            self.assertEqual(name.count("\\"), 1)


# ---------------------------------------------------------------------------------------------------------------------------------------
def port_54321_is_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 54321))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_child(script, args, mode="ok", extra_env=None):
    env = dict(os.environ)
    env["TSS_E2_FAKE"] = mode
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen([sys.executable, script] + argv_for(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT,
                            creationflags=0x08000000)  # CREATE_NO_WINDOW


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter (INCONCLUSIVE for the Qt glue)")
class D_RealProcesses(unittest.TestCase):
    def setUp(self):
        self.sync = mm.Win32Sync()
        self.args = args_for()
        self.owner = Owner(self.sync, self.args)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.communicate()
        self.owner.close()

    def child(self, mode="ok", args=None):
        p = start_child(CHILD, args or self.args, mode)
        self.procs.append(p)
        return p

    def finish(self, p, seconds=5.0):
        try:
            out, err = p.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            self.fail("child did not exit in time")
        return p.returncode, err.decode("utf-8", "replace")

    def test_ready_then_stop_exits_zero_within_three_seconds(self):
        p = self.child()
        self.assertTrue(wait_until(self.owner.ready, 15), "Ready was not published")
        self.assertIsNone(p.poll())
        started = time.monotonic()
        self.owner.set_stop()
        code, err = self.finish(p, 3.0)
        self.assertEqual(code, 0, err)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertFalse(self.owner.ready())
        self.assertIn("event=exit", err)
        self.assertIn("reason=stop-requested", err)
        self.assertIn("ready_published=true", err)

    def test_other_instance_stop_does_not_stop_the_child(self):
        other = Owner(self.sync, args_for(pid=self.args.bve_pid))
        try:
            p = self.child()
            self.assertTrue(wait_until(self.owner.ready, 15))
            other.set_stop()
            time.sleep(0.6)
            self.assertIsNone(p.poll())
            self.assertTrue(self.owner.ready())
            self.owner.set_stop()
            self.assertEqual(self.finish(p, 3.0)[0], 0)
        finally:
            other.close()

    def test_stop_missing_exits_four_without_ready(self):
        args = args_for()                                  # no owner => no Stop object
        p = self.child(args=args)
        code, err = self.finish(p, 15)
        self.assertEqual(code, mm.EXIT_INIT_FAILED, err)
        self.assertIn("stop-event-missing", err)
        self.assertNotIn("ready-published", err)

    def test_duplicate_instance_exits_three(self):
        first = self.child()
        self.assertTrue(wait_until(self.owner.ready, 15))
        second = self.child()
        code, err = self.finish(second, 15)
        self.assertEqual(code, mm.EXIT_DUPLICATE_INSTANCE, err)
        self.assertTrue(self.owner.ready())
        self.owner.set_stop()
        self.assertEqual(self.finish(first, 3.0)[0], 0)

    def test_bind_failure_exits_two_without_ready(self):
        p = self.child("bind-fail")
        code, err = self.finish(p, 15)
        self.assertEqual(code, mm.EXIT_BIND_FAILED, err)
        self.assertIn("reason=udp-bind-failed", err)
        self.assertNotIn("ready-published", err)
        self.assertFalse(self.owner.ready())

    def test_init_exception_exits_four_without_ready(self):
        p = self.child("raise-in-init")
        code, err = self.finish(p, 15)
        self.assertEqual(code, mm.EXIT_INIT_FAILED, err)
        self.assertNotIn("ready-published", err)
        self.assertFalse(self.owner.ready())
        self.assertIn("RuntimeError@", err)
        self.assertNotIn("fake init failure", err)         # no exception message in the diagnostics

    def test_exception_after_ready_exits_one_and_ready_does_not_stay(self):
        p = self.child("raise-after-ready")
        code, err = self.finish(p, 15)
        self.assertEqual(code, mm.EXIT_RUNTIME_ERROR, err)
        self.assertIn("ready-published", err)
        self.assertIn("ready-withdrawn", err)
        self.assertIn("ValueError@", err)
        self.assertFalse(self.owner.ready())

    def test_stop_before_launch_exits_zero_without_ready(self):
        self.owner.set_stop()
        p = self.child()
        code, err = self.finish(p, 15)
        self.assertEqual(code, 0, err)
        self.assertNotIn("ready-published", err)

    def test_consecutive_and_parallel_children(self):
        for _ in range(3):
            args = args_for(pid=self.args.bve_pid)
            o = Owner(self.sync, args)
            try:
                p = self.child(args=args)
                self.assertTrue(wait_until(o.ready, 15))
                o.set_stop()
                self.assertEqual(self.finish(p, 3.0)[0], 0)
            finally:
                o.close()
        a, b = args_for(pid=1234), args_for(pid=1234)
        oa, ob = Owner(self.sync, a), Owner(self.sync, b)
        try:
            pa, pb = self.child(args=a), self.child(args=b)
            self.assertTrue(wait_until(lambda: oa.ready() and ob.ready(), 20))
            oa.set_stop()
            self.assertEqual(self.finish(pa, 3.0)[0], 0)
            time.sleep(0.3)
            self.assertIsNone(pb.poll())
            self.assertTrue(ob.ready())
            ob.set_stop()
            self.assertEqual(self.finish(pb, 3.0)[0], 0)
        finally:
            oa.close()
            ob.close()

    def test_real_main_py_argument_errors_exit_five(self):
        for argv in (["--managed"], ["--managed", "--owner", "t", "--bve-pid", "x", "--instance", new_instance()],
                     ["--managed", "--owner", "t", "--bve-pid", "5", "--instance", "BAD"]):
            p = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")] + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 cwd=ROOT, creationflags=0x08000000)
            self.procs.append(p)
            code, err = self.finish(p, 30)
            self.assertEqual(code, mm.EXIT_ARGS_INVALID, err)
            self.assertIn("event=args-invalid", err)

    def test_real_main_py_managed_mode(self):
        """Real Overlay. If the UDP port is held by a running TS Scoring the correct outcome is exit 2 (and the running one is untouched);
        if the port is free the full Ready -> Stop -> exit 0 path is exercised."""
        free = port_54321_is_free()
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")] + argv_for(self.args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=ROOT, creationflags=0x08000000)
        self.procs.append(p)
        if free:
            self.assertTrue(wait_until(self.owner.ready, 30), "Ready was not published")
            self.owner.set_stop()
            code, err = self.finish(p, 5.0)
            self.assertEqual(code, 0, err)
            print("[real main.py managed mode: port free -> Ready/Stop/exit 0]", file=sys.stderr)
        else:
            code, err = self.finish(p, 30)
            self.assertEqual(code, mm.EXIT_BIND_FAILED, err)
            self.assertFalse(self.owner.ready())
            print("[real main.py managed mode: port 54321 busy -> exit 2 verified; success path INCONCLUSIVE]", file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------------------------------------
def _git(*args):
    try:
        r = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, timeout=30)
    except Exception:
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


class E_StaticGuardsAndRegression(unittest.TestCase):
    def test_py_compile(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("main.py", "managed_mode.py", "config.py", "utils.py", "hud_ui.py", "menu_ui.py", "scoring_logic.py",
                         os.path.join("tests", "managed_smoke_child.py"), os.path.join("tests", "test_managed_mode_e2.py")):
                py_compile.compile(os.path.join(ROOT, name), cfile=os.path.join(d, name.replace(os.sep, "_") + "c"), doraise=True)

    def test_process_start_and_exe_packaging_are_not_introduced(self):
        caller = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Caller", "src")
        for name in os.listdir(caller):
            text = read_text(os.path.join(caller, name), "utf-8-sig")
            for token in ("Process.Start", "ProcessStartInfo", "main.py", "python"):
                if token == "python":
                    self.assertIsNone(re.search(r"(?i)\bpython", re.sub(r"//.*", "", text)), name)   # code, not comments
                else:
                    self.assertNotIn(token, re.sub(r"//.*", "", text), name)
        for name in ("main.py", "managed_mode.py"):
            text = read_text(os.path.join(ROOT, name))
            self.assertNotRegex(text, r"(?i)pyinstaller|nuitka|cx_freeze|py2exe")
        self.assertNotIn("subprocess", read_text(os.path.join(ROOT, "managed_mode.py")))
        for entry in os.listdir(ROOT):
            self.assertFalse(entry.lower().endswith((".spec", ".exe")), entry)

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_dispatch_normal_vs_managed(self):
        import main
        calls = []
        saved = (main._run_normal, main.run_managed)
        main._run_normal = lambda: calls.append("normal") or 11
        main.run_managed = lambda argv, **k: calls.append("managed") or 22
        try:
            self.assertEqual(main.main(["main.py"]), 11)
            # managed-only options without the explicit flag never enable managed mode and never require anything
            self.assertEqual(main.main(["main.py", "--instance", "x", "--bve-pid", "1", "--owner", "o"]), 11)
            self.assertEqual(main.main(["main.py", "-platform", "windows"]), 11)
            self.assertEqual(main.main(["main.py", "--managed"]), 22)
        finally:
            main._run_normal, main.run_managed = saved
        self.assertEqual(calls, ["normal", "normal", "normal", "managed"])

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_normal_mode_entry_is_unchanged(self):
        import inspect
        import main
        body = "".join(line.strip() for line in inspect.getsource(main._run_normal).splitlines()[1:])
        self.assertEqual(body, "app = QApplication(sys.argv)overlay = Overlay()overlay.show()return app.exec()")
        main_src = inspect.getsource(main.main)
        self.assertIn("return _run_normal()", main_src)

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_existing_python_modules_import(self):
        import config, utils, hud_ui, menu_ui, scoring_logic, main  # noqa: F401
        self.assertTrue(hasattr(main, "Overlay"))

    def test_overlay_is_unchanged_except_for_the_bind_result(self):
        old = _git("show", BASELINE + ":main.py")
        if old is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        new = read_text(os.path.join(ROOT, "main.py"))

        def overlay_class(src):
            tree = ast.parse(src)
            return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")

        old_c, new_c = overlay_class(old), overlay_class(new)
        self.assertEqual(len(old_c.body), len(new_c.body))
        differing = []
        for a, b in zip(old_c.body, new_c.body):
            if ast.dump(a) != ast.dump(b):
                differing.append(a.name)
                self.assertEqual(a.name, "__init__")
                self.assertEqual(len(a.body), len(b.body))
                stmts = [(x, y) for x, y in zip(a.body, b.body) if ast.dump(x) != ast.dump(y)]
                self.assertEqual(len(stmts), 1)
                x, y = stmts[0]
                self.assertIn("self.udp_socket.bind(", ast.unparse(x))
                self.assertEqual(ast.unparse(y), "self.udp_bind_ok = " + ast.unparse(x))
        self.assertEqual(differing, ["__init__"])
        # the other top-level definitions (outside the new managed-mode block) are untouched
        old_top = [ast.dump(n) for n in ast.parse(old).body if not isinstance(n, (ast.Import, ast.ImportFrom, ast.If)) and getattr(n, "name", "") != "Overlay"]
        new_top = [ast.dump(n) for n in ast.parse(new).body if not isinstance(n, (ast.Import, ast.ImportFrom, ast.If))
                   and getattr(n, "name", "") not in ("Overlay", "_ManagedShutdownBridge", "_release_overlay", "run_managed", "_run_normal", "main")]
        self.assertEqual(old_top, new_top)

    def test_caller_bridge_and_dlls_are_unchanged(self):
        if _git("cat-file", "-e", BASELINE) is None and _git("rev-parse", BASELINE) is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        changed = _git("diff", "--name-only", BASELINE, "--", "TsScoringPlugin")
        untracked = _git("ls-files", "--others", "--exclude-standard", "--", "TsScoringPlugin")
        if changed is None or untracked is None:
            self.skipTest("git not available (INCONCLUSIVE)")
        self.assertEqual(changed.strip(), "")
        self.assertEqual(untracked.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
