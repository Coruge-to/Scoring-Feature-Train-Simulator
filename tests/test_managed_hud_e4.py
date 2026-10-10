"""Phase E4 tests: the Session / Driving state of the Caller as seen by the managed application, and the HUD link. Standard library only.

    C:\\Python314\\python.exe -m unittest discover -s tests -p "test_managed_hud_e4.py" -v

Layers: (A) the state block: layout, validation, contract constants shared with the Caller source; (B) the HUD gate (pure); (C) the reader against
a fake source; (D) the reader against a REAL Windows mapping (separate writer objects, other instances / PIDs, UI-thread cost); (E) the HUD
controller against fake Overlay / timer / window API (every state sequence of the specification); (F) real processes: the real Qt loop and Stop
watcher with a fake Overlay and the real controller + real mapping; (G) the real Overlay (offscreen, only when UDP 54321 is free) and the
guarantee that the scoring lifecycle was not touched; (H) static guards.
No BVE, no BveEX, no Caller is started; no file is written outside a temp directory; a running TS Scoring is never touched.
"""
import ast
import ctypes
import importlib.util
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import managed_hud as mh  # noqa: E402
import managed_mode as mm  # noqa: E402
import managed_state as ms  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None
CHILD = os.path.join(ROOT, "tests", "managed_hud_child.py")
E3_COMMIT = "b9611dad47e2c95f8fa1c89a8bd0286896c75cea"
L3_GRADIENT_COMMIT = "d9cc783df283138124396475bb9daaa95c1b6ea0"      # the commit before the HUD Z-order fix: main.py / hud_ui.py must not differ from it
CALLER_SRC = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Caller", "src")


def new_instance():
    return uuid.uuid4().hex


def args_for(pid=880001, inst=None, owner="test"):
    return mm.ManagedArgs(pid, inst or new_instance(), owner)


class Log(object):
    def __init__(self):
        self.lines = []
        self._lock = threading.Lock()

    def __call__(self, text):
        with self._lock:
            self.lines.append(text)

    def events(self, name):
        return [line for line in self.lines if (" event=%s " % name) in (line + " ")]


def make_block(pid, inst, session=False, driving=False, closed=False, generation=0, count=0, head=None, tail=None, magic=ms.STATE_MAGIC,
               version=ms.STATE_VERSION, size=ms.STATE_SIZE, flags=None, load_info=0, load_magic=0):
    """Builds the 64 bytes exactly as AppStatePublisher.cs lays them out (Phase SI-A6: load_info / load_magic are the bytes 48..55; 0 / 0 = an older Caller)."""
    import struct
    buf = bytearray(64)
    head = 2 * count if head is None else head
    tail = head if tail is None else tail
    if flags is None:
        flags = (1 if session else 0) | (2 if driving else 0) | (4 if closed else 0)
    struct.pack_into("<IIII", buf, 0, magic, version, size, pid)
    buf[16:32] = inst[:16].encode("ascii")
    struct.pack_into("<IIiI", buf, 32, head, flags, generation, count)
    struct.pack_into("<II", buf, 48, load_info, load_magic)
    struct.pack_into("<I", buf, 60, tail)
    return bytes(buf)


class FakeSource(object):
    def __init__(self, data=None, exists=True):
        self.data = data
        self.exists = exists
        self.opened_name = None
        self.reads = 0
        self.closed = 0
        self.raise_on_read = None

    def open(self, name):
        self.opened_name = name
        return self.exists

    def read(self):
        self.reads += 1
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.data

    def close(self):
        self.closed += 1


# ---------------------------------------------------------------------------------------------------------------------------------------
class A_StateBlock(unittest.TestCase):
    def setUp(self):
        self.inst = new_instance()
        self.pid = 4242

    def parse(self, data):
        return ms.parse_state(data, self.pid, self.inst)

    def test_valid_block_all_levels(self):
        for session in (False, True):
            for driving in (False, True):
                snap, reason = self.parse(make_block(self.pid, self.inst, session, driving, generation=7, count=3))
                self.assertIsNone(reason)
                self.assertEqual((snap.session, snap.driving, snap.generation, snap.change_count, snap.closed), (session, driving, 7, 3, False))

    def test_effective_levels(self):
        snap, _ = self.parse(make_block(self.pid, self.inst, True, True, closed=True, generation=2, count=5))
        self.assertTrue(snap.closed)
        self.assertFalse(snap.effective_session)
        self.assertFalse(snap.effective_driving)
        snap, _ = self.parse(make_block(self.pid, self.inst, False, True, generation=2, count=5, flags=2))   # Driving without Session is never Driving
        self.assertFalse(snap.effective_driving)

    def test_rejections(self):
        good = make_block(self.pid, self.inst, True, True, generation=1, count=1)
        cases = {
            "short": good[:63], "magic": make_block(self.pid, self.inst, magic=1), "version": make_block(self.pid, self.inst, version=2),
            "size": make_block(self.pid, self.inst, size=128), "pid": make_block(self.pid + 1, self.inst),
            "instance": make_block(self.pid, new_instance()), "torn": make_block(self.pid, self.inst, head=3, tail=3),
        }
        for reason, data in cases.items():
            snap, got = self.parse(data)
            self.assertIsNone(snap, reason)
            self.assertEqual(got, reason)
        self.assertEqual(self.parse(make_block(self.pid, self.inst, head=4, tail=6))[1], "torn")           # head != tail
        self.assertEqual(self.parse(make_block(self.pid, self.inst, flags=8))[1], "flags")                  # unknown flag
        self.assertEqual(self.parse(make_block(self.pid, self.inst, generation=-1))[1], "flags")            # negative generation
        self.assertEqual(self.parse(None)[1], "short")
        self.assertEqual(self.parse(b"")[1], "short")

    def test_instance_is_compared_on_its_first_16_digits(self):
        a = "0123456789abcdef" + "0" * 16
        b = "0123456789abcdef" + "f" * 16
        self.assertIsNone(ms.parse_state(make_block(self.pid, a), self.pid, b)[1])          # same prefix: same block family (the NAME carries all 32)
        self.assertEqual(ms.parse_state(make_block(self.pid, a), self.pid, "1123456789abcdef" + "0" * 16)[1], "instance")

    def test_name_follows_the_e2_family(self):
        n = ms.state_name(4242, self.inst)
        self.assertEqual(n, "Local\\TSScoringPlugin.v1.4242.App.%s.State" % self.inst)
        self.assertEqual(n.count("\\"), 1)

    def test_layout_constants_are_the_ones_of_the_caller_source(self):
        """The contract is written twice (C# and Python): every offset, the magic, the version and the flags must match the C# source text."""
        with open(os.path.join(CALLER_SRC, "AppStatePublisher.cs"), encoding="utf-8") as f:
            src = f.read()

        def const(name):
            m = re.search(r"public const (?:int|uint) %s = (0x[0-9A-Fa-f]+|\d+)u?;" % name, src)
            self.assertIsNotNone(m, name)
            return int(m.group(1), 0)

        pairs = [("Size", ms.STATE_SIZE), ("Magic", ms.STATE_MAGIC), ("Version", ms.STATE_VERSION), ("InstanceChars", ms.INSTANCE_CHARS),
                 ("OffMagic", ms.OFF_MAGIC), ("OffVersion", ms.OFF_VERSION), ("OffSize", ms.OFF_SIZE), ("OffPid", ms.OFF_PID),
                 ("OffInstance", ms.OFF_INSTANCE), ("OffHead", ms.OFF_HEAD), ("OffFlags", ms.OFF_FLAGS), ("OffGeneration", ms.OFF_GENERATION),
                 ("OffChangeCount", ms.OFF_CHANGE_COUNT), ("OffTail", ms.OFF_TAIL), ("FlagSession", ms.FLAG_SESSION),
                 ("FlagDriving", ms.FLAG_DRIVING), ("FlagClosed", ms.FLAG_CLOSED),
                 ("OffLoadInfo", ms.OFF_LOAD_INFO), ("OffLoadMagic", ms.OFF_LOAD_MAGIC), ("LoadMagic", ms.LOAD_MAGIC), ("LoadKnownBits", ms._KNOWN_LOAD_BITS)]
        for name, value in pairs:
            self.assertEqual(const(name), value, name)
        self.assertEqual(ms.LOAD_MAGIC.to_bytes(4, "little"), b"1DOL")                   # "LOD1" as a number
        self.assertEqual(ms.OFF_LOAD_INFO + ms._LOAD.size, 56)                          # the marker fills 48..55; 56..59 stay reserved
        self.assertEqual(ms.STATE_MAGIC.to_bytes(4, "little"), b"TSAS")
        # the Python struct formats cover exactly the documented offsets
        self.assertEqual(ms._HEADER.size, 32)
        self.assertEqual(ms.OFF_HEAD + ms._BODY.size, 48)
        self.assertEqual(ms.OFF_TAIL + ms._TAIL.size, 64)

    def test_session_and_driving_names_do_not_exist_as_events(self):
        # E0 sketched two named events; E4 publishes one block instead (generation + consistent pair). No such event name is used anywhere.
        for name in ("managed_state.py", "managed_hud.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn(".Session\"", text)
            self.assertNotIn(".Driving\"", text)


# ---------------------------------------------------------------------------------------------------------------------------------------
def snap(session=False, driving=False, generation=0, count=0, closed=False):
    return ms.StateSnapshot(session, driving, closed, generation, count, 2 * count)


class B_HudGate(unittest.TestCase):
    def test_initial_is_hidden_and_a_none_reading_changes_nothing(self):
        g = ms.HudGate()
        self.assertEqual((g.mode, g.session, g.driving), (ms.MODE_HIDDEN, False, False))
        self.assertIsNone(g.apply(None))
        self.assertIsNone(g.apply(snap()))
        self.assertEqual(g.suppressed, 2)
        self.assertEqual(g.changes, 0)

    def test_modes(self):
        g = ms.HudGate()
        c = g.apply(snap(True, False, 1, 1))
        self.assertEqual((c.mode, c.previous_mode, c.session_changed, c.driving_changed, c.generation_changed), (ms.MODE_WAITING, ms.MODE_HIDDEN, True, False, True))
        c = g.apply(snap(True, True, 1, 2))
        self.assertEqual((c.mode, c.driving_changed, c.generation_changed), (ms.MODE_ACTIVE, True, False))
        c = g.apply(snap(True, False, 1, 3))                       # soft OFF
        self.assertEqual((c.mode, c.session, c.driving), (ms.MODE_WAITING, True, False))
        c = g.apply(snap(True, True, 1, 4))                        # soft ON again: same generation
        self.assertEqual((c.mode, c.generation_changed), (ms.MODE_ACTIVE, False))
        c = g.apply(snap(False, False, 1, 5))                      # hard OFF
        self.assertEqual((c.mode, c.session_changed, c.driving_changed), (ms.MODE_HIDDEN, True, True))
        c = g.apply(snap(True, True, 2, 7))                        # reload
        self.assertEqual((c.mode, c.generation_changed, c.previous_generation), (ms.MODE_ACTIVE, True, 1))
        self.assertEqual(g.generation_changes, 2)

    def test_driving_without_session_never_activates(self):
        g = ms.HudGate()
        self.assertIsNone(g.apply(ms.StateSnapshot(False, True, False, 0, 0, 0)))
        self.assertEqual(g.mode, ms.MODE_HIDDEN)

    def test_closed_means_everything_off(self):
        g = ms.HudGate()
        g.apply(snap(True, True, 3, 2))
        c = g.apply(snap(True, True, 3, 3, closed=True))
        self.assertEqual((c.mode, c.session, c.driving, c.closed), (ms.MODE_HIDDEN, False, False, True))

    def test_identical_readings_are_suppressed_and_counted(self):
        g = ms.HudGate()
        g.apply(snap(True, True, 1, 2))
        for _ in range(500):
            self.assertIsNone(g.apply(snap(True, True, 1, 2)))
        self.assertEqual(g.suppressed, 500)
        self.assertEqual(g.changes, 1)

    def test_a_none_reading_after_a_good_one_keeps_the_last_truth_out_of_hud_activity(self):
        g = ms.HudGate()
        g.apply(snap(True, True, 1, 2))
        c = g.apply(None)                                          # the block became unreadable: HUD must not stay on
        self.assertEqual((c.mode, c.session, c.driving), (ms.MODE_HIDDEN, False, False))
        self.assertEqual(c.generation, 1)

    def test_missed_changes_converge_and_are_counted(self):
        g = ms.HudGate()
        g.apply(snap(True, True, 1, 2))
        # ON -> OFF -> ON happened between two reads: the count advanced by 3, the state is the same as before
        self.assertIsNone(g.apply(snap(True, True, 1, 5)))
        self.assertEqual(g.skipped_changes, 2)
        # OFF seen after four unseen changes: converges to the CURRENT value
        c = g.apply(snap(True, False, 1, 9))
        self.assertEqual((c.mode, c.skipped_changes), (ms.MODE_WAITING, 3))

    def test_change_count_wraps(self):
        g = ms.HudGate()
        g.apply(snap(True, True, 1, 0xFFFFFFFF))
        c = g.apply(snap(True, False, 1, 0))
        self.assertEqual(c.skipped_changes, 0)


# ---------------------------------------------------------------------------------------------------------------------------------------
class C_ReaderFake(unittest.TestCase):
    def setUp(self):
        self.args = args_for()
        self.log = Log()

    def reader(self, source):
        return ms.StateReader(self.args, source, self.log)

    def test_missing_block_breaks_the_managed_contract_with_one_diagnostic(self):
        r = self.reader(FakeSource(exists=False))
        self.assertFalse(r.open())
        self.assertTrue(r.unavailable)
        self.assertEqual(r.open_failure, "block-missing")
        self.assertIsNone(r.poll())
        self.assertEqual(len(self.log.events("state-contract-failed")), 1)
        line = self.log.events("state-contract-failed")[0]
        for word in ("phase=init", "reason=block-missing", "action=no-app-ready"):
            self.assertIn(word, line)
        self.assertEqual(len(self.log.lines), 1)                       # nothing else: no state-unavailable, no state-attached

    def test_open_reads_the_current_state_at_once(self):
        src = FakeSource(make_block(self.args.bve_pid, self.args.instance, True, True, generation=4, count=6))
        r = self.reader(src)
        self.assertTrue(r.open())
        self.assertEqual(src.opened_name, ms.state_name(self.args.bve_pid, self.args.instance))
        self.assertEqual((r.last.session, r.last.driving, r.last.generation), (True, True, 4))
        self.assertIn("valid=yes", self.log.events("state-attached")[0])

    def test_polling_does_not_log(self):
        src = FakeSource(make_block(self.args.bve_pid, self.args.instance, True, False, generation=1, count=1))
        r = self.reader(src)
        r.open()
        before = len(self.log.lines)
        for _ in range(2000):
            r.poll()
        self.assertEqual(len(self.log.lines), before)
        self.assertEqual(r.reads, 2000)

    def test_other_instance_and_other_pid_break_the_contract_at_start(self):
        for reason, data in (("instance", make_block(self.args.bve_pid, new_instance(), True, True, generation=1, count=1)),
                             ("pid", make_block(self.args.bve_pid + 5, self.args.instance, True, True, generation=1, count=1))):
            log = Log()
            src = FakeSource(data)
            r = ms.StateReader(self.args, src, log)
            self.assertFalse(r.open())
            self.assertEqual(r.open_failure, reason)
            self.assertFalse(r.attached)
            self.assertGreaterEqual(src.closed, 1)                         # nothing stays mapped
            self.assertIsNone(r.poll())
            self.assertEqual(len(log.events("state-contract-failed")), 1)  # reported once, with a fixed word
            self.assertIn("reason=" + reason, log.events("state-contract-failed")[0])
            self.assertNotIn(self.args.instance, log.events("state-contract-failed")[0].split("reason=")[1])

    def test_torn_copy_keeps_the_last_good_state_and_is_not_logged(self):
        good = make_block(self.args.bve_pid, self.args.instance, True, True, generation=2, count=2)
        src = FakeSource(good)
        r = self.reader(src)
        r.open()
        src.data = make_block(self.args.bve_pid, self.args.instance, True, False, generation=2, count=3, head=7, tail=6)
        before = len(self.log.lines)
        self.assertEqual(r.poll().driving, True)
        self.assertEqual(len(self.log.lines), before)
        self.assertGreater(r.torn_retries, 0)
        src.data = make_block(self.args.bve_pid, self.args.instance, True, False, generation=2, count=3)
        self.assertEqual(r.poll().driving, False)                           # converges to the current value

    def test_unstable_double_read_is_retried(self):
        a = make_block(self.args.bve_pid, self.args.instance, True, True, generation=1, count=1)
        b = make_block(self.args.bve_pid, self.args.instance, True, False, generation=1, count=2)
        seq = [a, b, b, b]

        class Flip(FakeSource):
            def read(inner):
                return seq.pop(0) if seq else b
        r = self.reader(Flip(a))
        r.open()
        seq[:] = [a, b, b, b]
        self.assertEqual(r.poll().driving, False)

    def test_read_exception_is_contained(self):
        src = FakeSource(make_block(self.args.bve_pid, self.args.instance, True, True, generation=1, count=1))
        r = self.reader(src)
        r.open()
        src.raise_on_read = OSError("boom")
        self.assertEqual(r.poll().session, True)                            # last good state, no exception
        self.assertEqual(r.lost, "read-OSError")
        self.assertEqual(len(self.log.events("state-lost")), 1)
        self.assertNotIn("boom", self.log.events("state-lost")[0])

    def test_close_releases_once_and_stops_reading(self):
        src = FakeSource(make_block(self.args.bve_pid, self.args.instance, True, True, generation=1, count=1))
        r = self.reader(src)
        r.open()
        r.close()
        r.close()
        reads = src.reads
        self.assertIsNone(r.poll())
        self.assertEqual(src.reads, reads)
        self.assertEqual(len(self.log.events("state-detached")), 1)
        self.assertGreaterEqual(src.closed, 1)

    def test_diagnostics_carry_no_path_and_no_user_text(self):
        src = FakeSource(make_block(self.args.bve_pid, self.args.instance, True, True, generation=1, count=1))
        r = self.reader(src)
        r.open()
        r.poll()
        r.close()
        text = "\n".join(self.log.lines)
        for needle in ("C:\\", "Users", "Desktop"):
            self.assertNotIn(needle, text)


# ---------------------------------------------------------------------------------------------------------------------------------------
class Win32BlockWriter(object):
    """A real named mapping written the way the Caller writes it (seqlock), from a DIFFERENT object than the reader."""

    def __init__(self, pid, inst):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
        k.CreateFileMappingW.restype = wintypes.HANDLE
        k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k = k
        self.pid, self.inst = pid, inst
        self.handle = k.CreateFileMappingW(ctypes.c_void_p(-1).value, None, 0x04, 0, 64, ms.state_name(pid, inst))
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.view = k.MapViewOfFile(self.handle, 0x0002, 0, 0, 64)
        self.count = 0
        self.session = self.driving = self.closed = False
        self.generation = 0
        self._put(make_block(pid, inst))

    def _put(self, data):
        ctypes.memmove(self.view, data, 64)

    def publish(self, session=None, driving=None, generation=None, closed=None):
        self.session = self.session if session is None else session
        self.driving = (self.driving if driving is None else driving) and self.session
        self.generation = self.generation if generation is None else generation
        self.closed = self.closed if closed is None else closed
        self.count += 1
        self._put(make_block(self.pid, self.inst, self.session, self.driving, self.closed, self.generation, self.count))

    def dispose(self):
        if self.view:
            self.k.UnmapViewOfFile(self.view)
            self.view = None
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


class D_ReaderWin32(unittest.TestCase):
    def setUp(self):
        self.args = args_for()
        self.log = Log()
        self.writers = []

    def tearDown(self):
        for w in self.writers:
            w.dispose()

    def writer(self, args=None):
        a = args or self.args
        w = Win32BlockWriter(a.bve_pid, a.instance)
        self.writers.append(w)
        return w

    def test_current_value_at_start_and_changes_follow(self):
        w = self.writer()
        w.publish(session=True, driving=True, generation=3)                      # published BEFORE the reader exists
        r = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        self.assertTrue(r.open())
        self.assertEqual((r.last.session, r.last.driving, r.last.generation), (True, True, 3))
        w.publish(driving=False)
        self.assertEqual(r.poll().driving, False)
        w.publish(session=False)
        self.assertEqual(r.poll().session, False)
        w.publish(session=True, driving=True, generation=4)
        self.assertEqual((r.poll().session, r.last.generation), (True, 4))
        r.close()

    def test_no_block_means_unavailable(self):
        r = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        self.assertFalse(r.open())
        self.assertTrue(r.unavailable)

    def test_stale_block_of_another_instance_and_another_pid_is_not_read(self):
        other_inst = self.writer(args_for(pid=self.args.bve_pid))
        other_inst.publish(session=True, driving=True, generation=9)
        other_pid = self.writer(args_for(pid=self.args.bve_pid + 1, inst=self.args.instance))
        other_pid.publish(session=True, driving=True, generation=9)
        r = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        self.assertFalse(r.open())                                               # neither name is ours
        mine = self.writer()
        r2 = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        self.assertTrue(r2.open())
        self.assertEqual((r2.last.session, r2.last.generation), (False, 0))      # not 9: the other blocks do not leak into ours
        r2.close()

    def test_reader_keeps_working_after_the_writer_let_go_and_close_releases(self):
        w = self.writer()
        w.publish(session=True, driving=True, generation=1)
        r = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        r.open()
        w.dispose()
        self.assertEqual(r.poll().driving, True)                                 # the mapping stays alive while the reader holds it
        r.close()
        reopen = ms.Win32StateSource()
        self.assertFalse(reopen.open(ms.state_name(self.args.bve_pid, self.args.instance)))   # nothing holds the name any more

    def test_poll_never_blocks_the_ui_thread(self):
        w = self.writer()
        w.publish(session=True, driving=True, generation=1)
        r = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        r.open()
        started = time.perf_counter()
        for _ in range(5000):
            r.poll()
        per_poll_ms = (time.perf_counter() - started) * 1000.0 / 5000
        self.assertLess(per_poll_ms, 0.5, "one poll took %.4f ms" % per_poll_ms)
        r.close()

    def test_concurrent_writer_never_produces_a_mixed_state(self):
        w = self.writer()
        r = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        r.open()
        stop = threading.Event()

        def churn():
            n = 0
            while not stop.is_set():
                n += 1
                w.publish(session=True, driving=True, generation=n)       # the writer always writes generation n as change number n
        t = threading.Thread(target=churn, daemon=True)
        t.start()
        bad = 0
        try:
            end = time.monotonic() + 1.0
            while time.monotonic() < end:
                s = r.poll()
                # the writer always writes (generation n, count n): a mixed reading would break this identity
                if s is not None and s.generation != s.change_count:
                    bad += 1
        finally:
            stop.set()
            t.join()
        self.assertEqual(bad, 0)
        r.close()


# ---------------------------------------------------------------------------------------------------------------------------------------
class FakeTimer(object):
    def __init__(self):
        self.intervals = []
        self.starts = 0

    def setInterval(self, ms):
        self.intervals.append(ms)

    def start(self):
        self.starts += 1


class FakeOverlay(object):
    created = 0

    def __init__(self):
        FakeOverlay.created += 1
        self.visible = False
        self.shows = 0
        self.hides = 0
        self.geoms = []
        self.updates = 0
        self.closed = False
        self.z_api = None              # when set: show() behaves like a (re)created native window and goes to the top of the Z order
        self.hwnd = 1000

    def winId(self):
        return self.hwnd

    def show(self):
        self.visible = True
        self.shows += 1
        if self.z_api is not None:
            self.z_api.z_on_show(self.hwnd)

    def hide(self):
        self.visible = False
        self.hides += 1

    def isVisible(self):
        return self.visible

    def setGeometry(self, x, y, w, h):
        self.geoms.append((x, y, w, h))

    def update(self):
        self.updates += 1

    def close(self):
        self.closed = True


class FakeWindowApi(object):
    def __init__(self):
        self.hwnd = 5000
        self.alive = True
        self.iconic = False
        self.rect = (100, 100, 800, 600)
        self.searches = 0
        self.owner_calls = []
        self.owners = {}
        # a fake Z order, top -> bottom (window ids); the Overlay joins it when it is shown. z_calls: every place_below the HUD asked for.
        self.z = [5000]
        self.topmost = set()
        self.z_calls = []
        self.z_queries = 0
        self.z_shows = 0
        self.z_fail = None

    def z_on_show(self, overlay_hwnd):
        """What Windows does with a newly shown (or re-created) top-level window: the top of the normal band, in front of everything non-topmost."""
        self.z_shows += 1
        owner = self.owners.get(overlay_hwnd, 0)                 # an owner still set when the window is shown is brought to the front WITH it
        if overlay_hwnd in self.z:
            self.z.remove(overlay_hwnd)
        if owner and owner in self.z:
            self.z.remove(owner)
            self.z.insert(self._normal_band_top(), owner)
        self.z.insert(self._normal_band_top(), overlay_hwnd)
        self.owners.pop(overlay_hwnd, None)                      # and Qt clears the owner while it shows the window (too late for the z effect)

    def _normal_band_top(self):
        i = 0
        while i < len(self.z) and self.z[i] in self.topmost:
            i += 1
        return i

    def z_above(self, hwnd):
        self.z_queries += 1
        if hwnd not in self.z:
            return 0
        i = self.z.index(hwnd)
        return self.z[i - 1] if i > 0 else 0

    def is_topmost(self, hwnd):
        return hwnd in self.topmost

    def place_below(self, overlay_hwnd, above_hwnd):
        self.z_calls.append((overlay_hwnd, above_hwnd))
        if self.z_fail is not None:
            raise self.z_fail
        if overlay_hwnd in self.z:
            self.z.remove(overlay_hwnd)
        if above_hwnd:
            self.z.insert(self.z.index(above_hwnd) + 1, overlay_hwnd)
        else:
            self.z.insert(self._normal_band_top(), overlay_hwnd)

    def find_bve_window(self, bve_pid):
        self.searches += 1
        return self.hwnd if self.alive else None

    def is_window(self, hwnd):
        return self.alive and hwnd == self.hwnd

    def is_iconic(self, hwnd):
        return self.iconic

    def client_rect_on_screen(self, hwnd):
        return self.rect

    def owner_of(self, overlay_hwnd):
        return self.owners.get(overlay_hwnd, 0)

    def set_owner(self, overlay_hwnd, bve_hwnd):
        self.owner_calls.append((overlay_hwnd, bve_hwnd))
        self.owners[overlay_hwnd] = bve_hwnd


class Clock(object):
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class ControllerCase(unittest.TestCase):
    def setUp(self):
        FakeOverlay.created = 0
        self.args = args_for()
        self.log = Log()
        self.source = FakeSource(make_block(self.args.bve_pid, self.args.instance))
        self.reader = ms.StateReader(self.args, self.source, self.log)
        self.overlay = FakeOverlay()
        self.timer = FakeTimer()
        self.api = FakeWindowApi()
        self.overlay.z_api = self.api
        self.clock = Clock()
        self.steps = []
        self.count = 0
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: self.steps.append(1),
                                           timer=self.timer, clock=self.clock)

    def publish(self, session=False, driving=False, generation=0, closed=False):
        self.count += 1
        self.source.data = make_block(self.args.bve_pid, self.args.instance, session, driving, closed, generation, self.count)

    def pump(self, ticks=1):
        for _ in range(ticks):
            self.clock.t += 0.02
            self.hud.tick()


class E_Controller(ControllerCase):
    def test_initial_state_is_hidden_and_nothing_is_updated(self):
        self.hud.start()
        self.pump(50)
        self.assertEqual((self.hud.mode, self.overlay.visible, self.overlay.shows, len(self.steps)), (ms.MODE_HIDDEN, False, 0, 0))
        self.assertEqual(self.timer.intervals, [mh.IDLE_INTERVAL_MS])
        self.assertEqual(self.api.searches, 0)                                   # no window search while nothing is shown
        self.assertIn("change=initial", self.log.events("state")[0])

    def test_session_and_driving_on_shows_and_updates(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(10)
        self.assertEqual(self.hud.mode, ms.MODE_ACTIVE)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.shows, 1)
        self.assertEqual(len(self.steps), 10)
        self.assertEqual(self.api.owner_calls, [(1000, 5000)])                  # linked once, to the window found by PID
        self.assertEqual(self.overlay.geoms, [(100, 100, 800, 600)])
        self.assertEqual(self.timer.intervals, [mh.IDLE_INTERVAL_MS, mh.ACTIVE_INTERVAL_MS])
        self.assertEqual(len(self.log.events("hud-update-start")), 1)
        self.assertEqual(len(self.log.events("hud-show")), 1)

    def test_session_on_alone_waits_and_shows_nothing(self):
        self.hud.start()
        self.publish(True, False, 1)
        self.pump(20)
        self.assertEqual((self.hud.mode, self.overlay.visible, len(self.steps)), (ms.MODE_WAITING, False, 0))

    def test_driving_off_waits_without_destroying_and_resumes_on_the_same_overlay(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.publish(True, False, 1)                                             # soft OFF
        self.pump(30)
        self.assertEqual((self.hud.mode, self.overlay.visible, self.overlay.hides), (ms.MODE_WAITING, False, 1))
        steps_in_wait = len(self.steps)
        self.pump(30)
        self.assertEqual(len(self.steps), steps_in_wait)                         # updates stopped while waiting
        self.assertFalse(self.overlay.closed)
        self.publish(True, True, 1)                                              # soft ON again, same generation
        self.pump(5)
        self.assertEqual((self.hud.mode, self.overlay.visible, self.overlay.shows), (ms.MODE_ACTIVE, True, 2))
        self.assertEqual(FakeOverlay.created, 1)
        # same overlay, same BVE window: the owner is released before the second show and set again right after it (the log's hud-owner-set n=2)
        self.assertEqual(self.api.owner_calls, [(1000, 5000), (1000, 0), (1000, 5000)])
        self.assertEqual(self.hud.link_count, 1)
        self.assertEqual(self.timer.starts, 0)                                   # the controller never starts / creates a timer

    def test_session_off_hides(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.publish(False, False, 1)
        self.pump(3)
        self.assertEqual((self.hud.mode, self.overlay.visible), (ms.MODE_HIDDEN, False))
        reasons = self.log.events("hud-hide")
        self.assertIn("reason=session-off", reasons[0])
        self.assertIn("reason=session-off", self.log.events("hud-update-wait")[0])

    def test_soft_and_hard_off_are_distinguishable_in_the_diagnostics(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.publish(True, False, 1)
        self.pump(2)
        self.assertIn("reason=driving-off", self.log.events("hud-hide")[0])
        self.publish(True, True, 1)
        self.pump(2)
        self.publish(False, False, 1)
        self.pump(2)
        self.assertIn("reason=session-off", self.log.events("hud-hide")[1])

    def test_reload_new_generation_reappears_on_the_same_overlay_and_python(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.publish(False, False, 1)                                            # scenario closed
        self.pump(3)
        self.publish(True, True, 2)                                              # reloaded: new ScenarioGeneration
        self.pump(3)
        self.assertEqual((self.hud.mode, self.overlay.visible, self.overlay.shows, FakeOverlay.created), (ms.MODE_ACTIVE, True, 2, 1))
        self.assertEqual(self.hud.gate.generation_changes, 2)
        self.assertTrue(any("generation-changed" in line and "prev_gen=1" in line and "gen=2" in line for line in self.log.events("state")))

    def test_generation_change_under_a_continuous_session_does_not_flicker(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.publish(True, True, 2)                                              # same levels, new generation (blink between two reads)
        self.pump(3)
        self.assertEqual((self.overlay.shows, self.overlay.hides), (1, 0))
        self.assertEqual(len(self.log.events("hud-update-start")), 1)

    def test_identical_readings_do_not_repeat_show_hide_timer_or_logs(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        before = len(self.log.lines)
        intervals = list(self.timer.intervals)
        self.pump(1000)
        self.assertEqual(len(self.log.lines), before)
        self.assertEqual((self.overlay.shows, self.overlay.hides), (1, 0))
        self.assertEqual(self.timer.intervals, intervals)
        self.assertEqual(len(self.steps), 1002)
        self.assertGreaterEqual(self.hud.gate.suppressed, 1000)

    def test_pause_keeps_the_driving_contract(self):
        # a Pause does not change Session / Driving (the Caller's Tick runs on): the HUD is neither hidden nor re-created
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(100)
        self.assertEqual((self.overlay.shows, self.overlay.hides, FakeOverlay.created), (1, 0, 1))

    def test_legacy_soft_off_oscillation_never_rebuilds_anything(self):
        self.hud.start()
        self.publish(True, True, 5)
        self.pump(2)
        for _ in range(5):                                                       # tick-stale soft OFF / ON in the SAME generation, Session stays ON
            self.publish(True, False, 5)
            self.pump(2)
            self.publish(True, True, 5)
            self.pump(2)
        self.assertEqual((self.overlay.shows, self.overlay.hides, FakeOverlay.created, self.hud.link_count), (6, 5, 1, 1))
        self.assertFalse(self.overlay.closed)

    def test_missed_notifications_converge_to_the_current_state(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        for g in range(2, 8):                                                    # six changes between two ticks; the last one is Driving OFF
            self.publish(True, g % 2 == 0, g)
        self.publish(True, False, 7)
        self.pump(2)
        self.assertEqual((self.hud.mode, self.overlay.visible), (ms.MODE_WAITING, False))
        self.assertGreater(self.hud.gate.skipped_changes, 0)
        self.assertTrue(any("coalesced=" in line for line in self.log.events("state")))

    def test_other_instance_signal_is_ignored(self):
        other = args_for(pid=self.args.bve_pid)
        self.source.data = make_block(other.bve_pid, other.instance, True, True, generation=1, count=1)
        self.hud.start()
        self.pump(20)
        self.assertEqual((self.hud.mode, self.overlay.shows), (ms.MODE_HIDDEN, 0))

    def test_block_missing_keeps_the_hud_hidden_without_error(self):
        self.source.exists = False
        self.hud.start()
        self.pump(20)
        self.assertEqual((self.hud.mode, self.overlay.shows, self.hud.errors), (ms.MODE_HIDDEN, 0, 0))

    def test_closed_block_hides(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.publish(False, False, 1, closed=True)
        self.pump(3)
        self.assertEqual((self.hud.mode, self.overlay.visible), (ms.MODE_HIDDEN, False))
        self.assertTrue(any("closed=yes" in line for line in self.log.events("state")))

    def test_started_after_the_caller_published(self):
        self.publish(True, True, 3)
        self.hud.start()                                                         # the first reading already says ON
        self.assertEqual(self.hud.mode, ms.MODE_ACTIVE)
        self.assertEqual(self.timer.intervals[-1], mh.ACTIVE_INTERVAL_MS)
        self.pump(2)
        self.assertTrue(self.overlay.visible)

    def test_no_bve_window_means_no_show_and_a_rate_limited_search(self):
        self.api.alive = False
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(100)                                                            # 2 s of fake time
        self.assertFalse(self.overlay.visible)
        self.assertLessEqual(self.api.searches, 5)
        self.assertEqual(len(self.log.events("hud-window-wait")), 1)
        self.assertEqual(len(self.steps), 100)                                   # the data keeps being updated
        self.api.alive = True
        self.pump(40)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.hud.link_count, 1)

    def test_bve_window_lost_hides_unlinks_and_does_not_quit(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.api.alive = False
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.assertEqual(len(self.log.events("hud-window-unlinked")), 1)
        self.assertFalse(self.hud._shutdown)                                      # the process lifetime is not the HUD's business
        self.api.alive = True
        self.api.hwnd = 6000                                                     # BVE restarted its window
        self.pump(40)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.api.owner_calls[-1], (1000, 6000))
        self.assertEqual(self.hud.link_count, 2)

    def test_minimized_bve_hides_and_restores(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.api.iconic = True
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.api.iconic = False
        self.pump(3)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(FakeOverlay.created, 1)

    def test_owner_is_set_after_show_and_set_again_when_the_native_window_lost_it(self):
        # Qt may create / re-create the native window at show(); an Overlay without its owner would not stay above BVE
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.assertEqual((self.hud.owner_sets, self.api.owner_calls), (1, [(1000, 5000)]))
        self.assertTrue(self.overlay.visible)
        self.api.owners.clear()                                                  # the window was re-created: no owner any more
        self.pump(2)
        self.assertEqual(self.hud.owner_sets, 2)
        self.pump(50)
        self.assertEqual(self.hud.owner_sets, 2)                                 # once it is right nothing is done again
        self.assertEqual(len(self.log.events("hud-owner-set")), 2)

    def test_geometry_follows_the_bve_window_only_when_it_changes(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(10)
        self.api.rect = (200, 150, 1000, 700)
        self.pump(10)
        self.assertEqual(self.overlay.geoms, [(100, 100, 800, 600), (200, 150, 1000, 700)])

    def test_hud_error_is_contained_logged_and_limited(self):
        hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log,
                                      update_step=lambda o: (_ for _ in ()).throw(ValueError("secret text C:\\Users\\x")), timer=self.timer, clock=self.clock)
        hud.start()
        self.publish(True, True, 1)
        for _ in range(50):
            self.clock.t += 0.02
            hud.tick()
        self.assertEqual(hud.errors, 50)
        errs = self.log.events("hud-error")
        self.assertEqual(len(errs), mh.MAX_HUD_ERROR_LINES)
        text = "\n".join(errs)
        self.assertIn("ValueError@", text)
        self.assertNotIn("secret text", text)
        self.assertNotIn("Users", text)
        self.assertEqual(hud.mode, ms.MODE_ACTIVE)                               # still running

    def test_shutdown_hides_releases_the_state_and_is_idempotent(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(3)
        self.hud.shutdown()
        self.hud.shutdown()
        self.assertFalse(self.overlay.visible)
        self.assertGreaterEqual(self.source.closed, 1)
        n = len(self.steps)
        self.hud.tick()
        self.assertEqual(len(self.steps), n)                                     # a late timer shot does nothing
        self.assertEqual(len(self.log.events("hud-summary")), 1)
        self.assertEqual(len(self.log.events("state-withdrawn")), 1)
        summary = self.log.events("hud-summary")[0]
        for field in ("shows=1", "hides=1", "errors=0", "links=1"):
            self.assertIn(field, summary)

    # -- the state block is a required part of the contract (start) and a fail-safe condition (after AppReady) -----------------------------
    def test_start_fails_without_a_block_and_the_controller_stays_inert(self):
        src = FakeSource(exists=False)
        hud = mh.ManagedHudController(self.overlay, ms.StateReader(self.args, src, self.log), self.api, self.args, self.log,
                                      update_step=lambda o: self.steps.append(1), timer=self.timer, clock=self.clock)
        self.assertFalse(hud.start())
        self.assertEqual(hud.startup_failure, "block-missing")
        for _ in range(20):
            hud.tick()
        self.assertEqual((self.overlay.shows, len(self.steps), self.api.searches), (0, 0, 0))
        self.assertFalse(hud.input_allowed)
        hud.shutdown()
        self.assertEqual(len(self.log.events("state-contract-failed")), 1)
        self.assertIn("end=init-failed", self.log.events("hud-summary")[0])

    def test_start_fails_for_every_invalid_first_reading(self):
        good = dict(pid=self.args.bve_pid, inst=self.args.instance)
        cases = {"magic": make_block(magic=1, **good), "version": make_block(version=2, **good), "size": make_block(size=65, **good),
                 "pid": make_block(pid=self.args.bve_pid + 1, inst=self.args.instance), "instance": make_block(pid=self.args.bve_pid, inst=new_instance()),
                 "flags": make_block(flags=16, **good), "torn": make_block(head=5, tail=5, **good)}
        for reason, data in cases.items():
            log = Log()
            reader = ms.StateReader(self.args, FakeSource(data), log, sleep=lambda s: None)
            hud = mh.ManagedHudController(FakeOverlay(), reader, self.api, self.args, log, update_step=lambda o: None, timer=self.timer, clock=self.clock)
            self.assertFalse(hud.start(), reason)
            self.assertEqual(hud.startup_failure, reason)
            self.assertEqual(len(log.events("state-contract-failed")), 1, reason)

    def test_a_momentarily_torn_first_copy_is_retried_not_failed(self):
        good = make_block(self.args.bve_pid, self.args.instance, True, True, generation=1, count=1)
        torn = make_block(self.args.bve_pid, self.args.instance, True, True, generation=1, count=1, head=3, tail=3)

        class Settling(FakeSource):
            calls = 0

            def read(inner):
                inner.calls += 1
                return torn if inner.calls <= 16 else good          # 3 attempts x 2 reads per round: the first rounds are torn
        reader = ms.StateReader(self.args, Settling(good), self.log, sleep=lambda s: None)
        self.assertTrue(reader.open())
        self.assertEqual(reader.last.generation, 1)
        self.assertEqual(len(self.log.events("state-contract-failed")), 0)

    def hud_active(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.assertEqual(self.hud.mode, ms.MODE_ACTIVE)
        self.assertTrue(self.hud.input_allowed)

    def test_failsafe_when_the_block_is_lost_after_ready(self):
        self.hud_active()
        steps_before, shows_before = len(self.steps), self.overlay.shows
        self.source.data = make_block(self.args.bve_pid + 1, self.args.instance, True, True, 1, 9)        # no longer ours
        self.pump(1)
        self.assertEqual(self.hud.failsafe, "pid")
        self.assertFalse(self.overlay.visible)                                   # HUD hidden
        self.assertFalse(self.hud.input_allowed)                                 # no new input operation
        self.assertEqual(self.hud.mode, ms.MODE_HIDDEN)
        self.pump(200)
        self.assertEqual(len(self.steps), steps_before)                          # HUD updates stopped
        self.assertEqual(self.overlay.shows, shows_before)
        self.assertFalse(self.overlay.closed)                                    # the Overlay is not destroyed
        self.assertEqual(FakeOverlay.created, 1)                                 # ... and not multiplied
        self.assertEqual(len(self.log.events("state-lost")), 1)                  # recorded once
        self.assertEqual(len(self.log.events("hud-hide")), 1)
        self.assertEqual(self.timer.starts, 0)                                   # the controller never starts/creates timers itself

    def test_failsafe_is_latched_even_if_the_block_looks_valid_again(self):
        self.hud_active()
        self.source.data = make_block(self.args.bve_pid, self.args.instance, magic=7)
        self.pump(1)
        self.publish(True, True, 5)
        self.pump(50)
        self.assertEqual(self.hud.failsafe, "magic")
        self.assertFalse(self.overlay.visible)
        self.assertFalse(self.hud.input_allowed)
        self.assertEqual(len(self.log.events("state-lost")), 1)

    def test_failsafe_from_a_waiting_or_hidden_state_hides_nothing_twice(self):
        self.hud.start()
        self.publish(True, False, 1)
        self.pump(3)
        self.source.raise_on_read = OSError("x")
        self.pump(3)
        self.assertEqual(self.hud.failsafe, "read-OSError")
        self.assertEqual((self.overlay.shows, self.overlay.hides), (0, 0))
        self.assertEqual(len(self.log.events("state-lost")), 1)

    def test_failsafe_still_ends_cleanly_on_stop(self):
        self.hud_active()
        self.source.data = None
        self.pump(2)
        self.assertEqual(self.hud.failsafe, "closed")
        self.hud.shutdown()                                                      # what the Stop request leads to
        self.assertGreaterEqual(self.source.closed, 1)
        self.assertEqual(len(self.log.events("hud-summary")), 1)
        self.assertIn("end=state-lost", self.log.events("hud-summary")[0])
        self.assertIn("failsafes=1", self.log.events("hud-summary")[0])

    def test_the_closed_flag_is_the_normal_end_and_not_a_loss(self):
        self.hud_active()
        self.publish(False, False, 1, closed=True)
        self.pump(5)
        self.assertIsNone(self.hud.failsafe)
        self.assertEqual(self.hud.mode, ms.MODE_HIDDEN)
        self.assertFalse(self.overlay.visible)
        self.assertEqual(len(self.log.events("state-closed")), 1)
        self.assertIn("loss=no", self.log.events("state-closed")[0])
        self.assertEqual(len(self.log.events("state-lost")), 0)
        self.pump(50)
        self.assertEqual(len(self.log.events("state-closed")), 1)                # once
        self.hud.shutdown()
        self.assertIn("end=caller-closed", self.log.events("hud-summary")[0])

    def test_input_is_allowed_only_while_active(self):
        self.hud.start()
        self.assertFalse(self.hud.input_allowed)
        self.publish(True, False, 1)
        self.pump(2)
        self.assertFalse(self.hud.input_allowed)                                 # soft OFF
        self.publish(True, True, 1)
        self.pump(2)
        self.assertTrue(self.hud.input_allowed)
        self.hud.shutdown()
        self.assertFalse(self.hud.input_allowed)

    def test_diagnostics_are_state_changes_only_with_a_fixed_vocabulary(self):
        self.hud.start()
        for g in range(1, 4):
            self.publish(True, True, g)
            self.pump(50)
            self.publish(False, False, g)
            self.pump(50)
        self.hud.shutdown()
        self.assertLess(len(self.log.lines), 40)
        text = "\n".join(self.log.lines)
        for needle in ("C:\\", "Users", "Desktop", "Traceback"):
            self.assertNotIn(needle, text)
        for line in self.log.lines:
            self.assertTrue(line.startswith("[MANAGED] event="), line)
            self.assertLess(len(line), 300)


# ---------------------------------------------------------------------------------------------------------------------------------------
SELECT = 7000      # the scenario selection window of BVE in the fake Z order (never identified by the HUD: only its place matters)
OTHER = 7100       # an unrelated application window
TOPMOST = 7200     # an always-on-top window of another application
HUD = 1000         # the Overlay


class I_ZOrder(ControllerCase):
    """The Z order of the HUD: directly above the BVE driving window, below whatever lies over that window (the scenario selection window), never
    topmost, never activating. The fake Z order is a list (top -> bottom); the Overlay joins it at the top when it is shown, like a (re)created native window."""

    def activate(self, z=None):
        if z is not None:
            self.api.z = list(z)
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(1)

    def test_select_window_over_the_driving_view_ends_up_over_the_hud(self):
        # [HUD, Select, BVE] (what show() produces) -> [Select, HUD, BVE]
        self.activate([SELECT, 5000])
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])
        self.assertEqual(self.hud.z_sets, 1)
        self.assertEqual(len(self.log.events("hud-zorder-set")), 1)

    def test_already_in_place_nothing_is_done(self):
        # [Select, HUD, BVE] -> unchanged, however long it stays like that
        self.activate([SELECT, 5000])
        self.api.z_calls.clear()
        self.pump(200)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [])
        self.assertEqual(self.hud.z_sets, 1)

    def test_without_a_select_window_the_hud_is_directly_above_bve(self):
        # [HUD, BVE]: the HUD is the window directly above BVE already: nothing to correct
        self.activate()
        self.assertEqual(self.api.z, [HUD, 5000])
        self.assertEqual(self.api.z_calls, [])
        self.assertEqual(self.hud.z_sets, 0)
        self.assertEqual(self.log.events("hud-zorder-set"), [])

    def test_unrelated_windows_keep_their_relations(self):
        # [HUD, OtherApp, Select, BVE] -> [OtherApp, Select, HUD, BVE]: HUD under the window directly above BVE; OtherApp / Select untouched relative to each other
        self.activate([OTHER, SELECT, 5000])
        self.assertEqual(self.api.z, [OTHER, SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])
        self.assertLess(self.api.z.index(OTHER), self.api.z.index(SELECT))

    def test_the_hud_is_not_taken_as_its_own_reference(self):
        # the window directly above BVE is the HUD itself: it is recognised and left alone (no call with the HUD as the reference)
        self.activate([SELECT, 5000])
        self.api.z_calls.clear()
        self.assertEqual(self.api.z_above(5000), HUD)
        self.pump(5)
        self.assertEqual(self.api.z_calls, [])
        for _hud, above in self.api.z_calls:
            self.assertNotEqual(above, HUD)

    def test_drift_while_shown_is_corrected_once(self):
        # a window appears over the driving view while the HUD is up (BVE opens its selection window): HUD above it -> moved under it, once
        self.activate()
        self.assertEqual(self.api.z, [HUD, 5000])
        self.api.z = [HUD, SELECT, 5000]
        self.pump(100)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])

    def test_selection_window_closed_the_same_hud_is_directly_above_bve_again(self):
        self.activate([SELECT, 5000])
        self.api.z.remove(SELECT)                          # the selection window is closed
        self.pump(20)
        self.assertEqual(self.api.z, [HUD, 5000])
        self.assertTrue(self.overlay.visible)
        self.assertEqual((self.overlay.shows, self.overlay.hides, FakeOverlay.created), (1, 0, 1))
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])  # no further correction was needed

    def test_a_topmost_window_over_the_driving_view_never_makes_the_hud_topmost(self):
        # the HUD fell below BVE: [Topmost, BVE, HUD]; the window directly above BVE is topmost -> HUD goes to the top of the NORMAL band, not behind the topmost one
        self.activate()
        self.api.topmost = {TOPMOST}
        self.api.z = [TOPMOST, 5000, HUD]
        self.pump(5)
        self.assertEqual(self.api.z, [TOPMOST, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, 0)])
        self.assertNotIn(HUD, self.api.topmost)
        for _hud, above in self.api.z_calls:
            self.assertNotIn(above, self.api.topmost)

    def test_hidden_hud_is_not_ordered(self):
        self.activate([SELECT, 5000])
        self.api.z_calls.clear()
        self.publish(True, False, 1)                       # soft OFF: hidden
        self.pump(5)
        self.assertFalse(self.overlay.visible)
        queries = self.api.z_queries
        self.api.z = [HUD, SELECT, 5000]
        self.pump(50)
        self.assertEqual(self.api.z_calls, [])
        self.assertEqual(self.api.z_queries, queries)      # not even looked at while hidden

    def test_minimized_bve_is_not_ordered_and_the_restore_is(self):
        self.activate([SELECT, 5000])
        self.api.iconic = True
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.api.z_calls.clear()
        queries = self.api.z_queries
        self.pump(10)
        self.assertEqual(self.api.z_queries, queries)
        self.api.iconic = False
        self.pump(3)                                       # shown again: top of the Z order -> corrected
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])

    def test_bve_window_lost_is_not_ordered(self):
        self.activate([SELECT, 5000])
        self.api.z_calls.clear()
        queries = self.api.z_queries
        self.api.alive = False
        self.pump(10)
        self.assertFalse(self.overlay.visible)
        self.assertEqual(self.api.z_calls, [])
        self.assertEqual(self.api.z_queries, queries)

    def test_hud_window_not_created_nothing_is_ordered(self):
        self.overlay.hwnd = 0
        self.activate([SELECT, 5000])
        self.pump(10)
        self.assertEqual((self.api.z_calls, self.api.z_queries, self.hud.z_sets, self.hud.z_errors), ([], 0, 0, 0))

    def test_correction_follows_every_show_after_a_soft_off(self):
        self.activate([SELECT, 5000])
        self.publish(True, False, 1)                       # soft OFF (the Tick stopped while the selection window was open)
        self.pump(5)
        self.assertFalse(self.overlay.visible)
        self.api.z_calls.clear()
        self.publish(True, True, 1)                        # soft ON: shown again -> at the top of the Z order -> corrected
        self.pump(5)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.api.z_shows, 2)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])
        self.assertEqual((self.overlay.shows, FakeOverlay.created), (2, 1))
        self.assertEqual(self.timer.starts, 0)             # no timer was (re)created or started by the HUD

    def test_correction_follows_the_show_of_a_reloaded_scenario(self):
        self.activate([SELECT, 5000])
        self.publish(False, False, 1)                      # hard OFF
        self.pump(5)
        self.api.z_calls.clear()
        self.publish(True, True, 2)                        # new ScenarioGeneration: the same Overlay is shown again
        self.pump(5)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])
        self.assertEqual((FakeOverlay.created, self.overlay.shows), (1, 2))

    def test_reshow_does_not_lift_the_bve_window_over_the_selection_window(self):
        # a window shown while it still has an owner takes the owner with it: the owner is released before show(), the BVE window stays under the selection window
        self.activate([SELECT, 5000])
        self.assertEqual(self.api.owners.get(HUD), 5000)
        self.publish(True, False, 1)
        self.pump(5)
        self.api.owner_calls.clear()
        self.publish(True, True, 1)
        self.pump(5)
        self.assertEqual(self.api.owner_calls[0], (HUD, 0))                 # released first
        self.assertEqual(self.api.owner_calls[1], (HUD, 5000))              # linked again right after the show
        self.assertEqual(self.hud.owner_releases, 1)
        self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertLess(self.api.z.index(SELECT), self.api.z.index(5000))
        self.assertEqual(self.api.owners.get(HUD), 5000)

    def test_first_show_releases_no_owner(self):
        self.activate()
        self.assertEqual(self.api.owner_calls, [(HUD, 5000)])
        self.assertEqual(self.hud.owner_releases, 0)

    def test_a_failing_owner_release_never_blocks_the_show(self):
        self.activate([SELECT, 5000])
        self.publish(True, False, 1)
        self.pump(3)
        real = self.api.set_owner

        def failing(overlay_hwnd, bve_hwnd):
            if bve_hwnd == 0:
                raise OSError("no")
            real(overlay_hwnd, bve_hwnd)

        self.api.set_owner = failing
        self.publish(True, True, 1)
        self.pump(3)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.hud.z_errors, 1)
        self.assertEqual(self.hud.errors, 0)

    def test_a_failing_order_operation_is_contained(self):
        self.api.z_fail = OSError("boom C:\\Users\\x")
        self.activate([SELECT, 5000])
        self.pump(100)
        self.assertTrue(self.overlay.visible)              # the HUD stays up, linked
        self.assertEqual((self.hud.link_count, self.overlay.hides, self.hud.errors), (1, 0, 0))
        self.assertEqual(self.hud.z_errors, 101)
        lines = self.log.events("hud-zorder-error")
        self.assertEqual(len(lines), mh.MAX_ZORDER_LINES)   # a few lines, then only counted
        self.assertNotIn("C:\\", "\n".join(lines))
        self.assertEqual(len(self.steps), 101)              # the data keeps being updated
        self.hud.shutdown()
        summary = self.log.events("hud-zorder-summary")
        self.assertEqual(len(summary), 1)
        self.assertIn("errors=101", summary[0])

    def test_only_a_pure_z_order_operation_is_asked_of_the_window_api(self):
        # nothing but z_above / is_topmost / place_below is added to the window API calls of the HUD, and no ordering happens while Z is right
        self.activate()
        self.pump(300)
        self.assertEqual(self.api.z_calls, [])
        self.assertEqual(self.hud.z_sets, 0)
        self.assertEqual(self.overlay.geoms, [(100, 100, 800, 600)])   # a Z operation moves or resizes nothing

    def test_summary_line_only_when_the_order_was_touched(self):
        self.activate()
        self.hud.shutdown()
        self.assertEqual(self.log.events("hud-zorder-summary"), [])

    def test_many_hide_show_cycles_never_multiply_the_overlay_the_timer_or_the_link(self):
        self.activate([SELECT, 5000])
        for generation in range(1, 9):
            self.publish(True, False, generation)                # soft OFF: hidden
            self.pump(3)
            self.publish(True, True, generation)                 # soft ON: shown again (the selection window is still open)
            self.pump(3)
            self.publish(False, False, generation)               # hard OFF (scenario ended)
            self.pump(3)
            self.publish(True, True, generation + 1)             # reload: a new ScenarioGeneration
            self.pump(3)
            self.assertEqual(self.api.z, [SELECT, HUD, 5000])
        self.assertEqual((FakeOverlay.created, self.hud.link_count, self.timer.starts), (1, 1, 0))
        self.assertEqual(self.overlay.shows, 1 + 2 * 8)        # one show per soft ON and one per reload
        self.assertEqual(self.api.z.count(HUD), 1)                # one HUD window in the Z order, however often it was shown
        self.assertLess(self.api.z.index(SELECT), self.api.z.index(5000))

    def test_the_same_result_for_every_host_the_controller_only_sees_a_bve_window(self):
        # Current (BVE6, 64 bit) and Legacy (BVE5, 32 bit) differ only in the process id and the window handle the Caller hands over
        for pid, hwnd, owner in ((6001, 5000, "caller"), (5001, 8800, "caller")):
            with self.subTest(pid=pid):
                FakeOverlay.created = 0
                args = args_for(pid=pid)
                source = FakeSource(make_block(args.bve_pid, args.instance))
                api = FakeWindowApi()
                api.hwnd = hwnd
                api.z = [SELECT, hwnd]
                overlay = FakeOverlay()
                overlay.z_api = api
                log = Log()
                hud = mh.ManagedHudController(overlay, ms.StateReader(args, source, log), api, args, log, update_step=lambda o: None,
                                              timer=FakeTimer(), clock=Clock())
                hud.start()
                source.data = make_block(args.bve_pid, args.instance, True, True, False, 1, 1)
                for _ in range(5):
                    hud.tick()
                self.assertEqual(api.z, [SELECT, HUD, hwnd])
                self.assertEqual(api.z_calls, [(HUD, SELECT)])


# ---------------------------------------------------------------------------------------------------------------------------------------
class J_Win32ZOrderApi(unittest.TestCase):
    """Win32WindowApi.place_below / z_above against a recording pywin32 stand-in: the exact SetWindowPos arguments, and nothing else."""

    def setUp(self):
        class Con(object):
            GW_HWNDPREV = 3
            HWND_TOP = 0
            SWP_NOSIZE = 1
            SWP_NOMOVE = 2
            SWP_NOZORDER = 4
            SWP_NOACTIVATE = 16
            SWP_SHOWWINDOW = 64
            WS_EX_TOPMOST = 8
            GWL_EXSTYLE = -20

        class Gui(object):
            def __init__(inner):
                inner.calls = []
                inner.prev = {}

            def SetWindowPos(inner, *a):
                inner.calls.append(("SetWindowPos",) + a)

            def GetWindow(inner, hwnd, cmd):
                inner.calls.append(("GetWindow", hwnd, cmd))
                if hwnd not in inner.prev:
                    raise OSError("no previous window")
                return inner.prev[hwnd]

            def GetWindowLong(inner, hwnd, index):
                inner.calls.append(("GetWindowLong", hwnd, index))
                return 8 if hwnd == 7200 else 0

        self.con, self.gui = Con, Gui()
        self.api = mh.Win32WindowApi.__new__(mh.Win32WindowApi)
        self.api._con, self.api._gui = Con, self.gui

    def test_place_below_a_window(self):
        self.api.place_below(1000, 7000)
        self.assertEqual(self.gui.calls, [("SetWindowPos", 1000, 7000, 0, 0, 0, 0, 2 | 1 | 16)])

    def test_place_below_nothing_is_the_top_of_the_normal_band(self):
        self.api.place_below(1000, 0)
        self.assertEqual(self.gui.calls, [("SetWindowPos", 1000, self.con.HWND_TOP, 0, 0, 0, 0, 2 | 1 | 16)])

    def test_flags_never_include_zorder_suppression_or_show_or_activation(self):
        self.api.place_below(1000, 7000)
        flags = self.gui.calls[0][-1]
        self.assertTrue(flags & self.con.SWP_NOACTIVATE and flags & self.con.SWP_NOMOVE and flags & self.con.SWP_NOSIZE)
        self.assertFalse(flags & (self.con.SWP_NOZORDER | self.con.SWP_SHOWWINDOW))
        self.assertNotEqual(self.gui.calls[0][2], -1)       # HWND_TOPMOST is -1

    def test_z_above_returns_the_previous_window_or_zero(self):
        self.gui.prev = {5000: 7000}
        self.assertEqual(self.api.z_above(5000), 7000)
        self.assertEqual(self.api.z_above(6000), 0)          # pywin32 raised: no previous window

    def test_is_topmost_reads_the_extended_style(self):
        self.assertTrue(self.api.is_topmost(7200))
        self.assertFalse(self.api.is_topmost(7000))


# ---------------------------------------------------------------------------------------------------------------------------------------
ZORDER_REAL = os.path.join(ROOT, "tests", "zorder_real_check.py")


class K_RealWindowsZOrder(unittest.TestCase):
    """REAL top-level windows (Qt) and the REAL Win32WindowApi: the defect is reproduced (the Overlay is shown in front of the selection window) and the
    correction puts it under it, for a selection window that is owned by the BVE window and for one that is not. Needs a desktop; no BVE, no BveEX."""

    def run_check(self, variant):
        if not HAS_QT or importlib.util.find_spec("win32gui") is None:
            self.skipTest("PyQt6 / pywin32 not importable (INCONCLUSIVE)")
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)                      # REAL windows: not the offscreen platform the other suites run with
        r = subprocess.run([sys.executable, ZORDER_REAL, variant], capture_output=True, timeout=120, cwd=ROOT, env=env, creationflags=0x08000000)
        out = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out + r.stderr.decode("utf-8", "replace"))
        import json
        return json.loads(out.strip().splitlines()[-1])

    def check(self, result):
        self.assertTrue(result["defect_reproduced"], result)            # show() really put the HUD in front of the selection window
        self.assertEqual(result["after_fix"], ["select", "hud", "bve"], result)
        self.assertEqual(result["repeat_calls"], 0, result)             # in place: nothing is done again
        self.assertEqual(result["closed_select"], ["hud", "bve"], result)
        self.assertTrue(result["owner_released_before_show"], result)   # the re-show released the owner first ...
        self.assertTrue(result["bve_kept_under_select"], result)        # ... so the BVE window was not lifted over the selection window with it
        self.assertEqual(result["reshow_before_fix"], ["hud", "select", "bve"], result)
        self.assertEqual(result["reshow_after_hide"], ["select", "hud", "bve"], result)
        self.assertTrue(result["hud_owner_is_bve"], result)
        self.assertFalse(result["hud_topmost"], result)
        self.assertTrue(result["foreground_unchanged"], result)         # the correction did not take the foreground

    def test_selection_window_owned_by_the_bve_window(self):
        self.check(self.run_check("owned"))

    def test_selection_window_not_owned(self):
        self.check(self.run_check("unowned"))


# ---------------------------------------------------------------------------------------------------------------------------------------
def start_child(args, mode="ok"):
    env = dict(os.environ)
    env["TSS_E4_CHILD"] = mode
    env["PYTHONIOENCODING"] = "utf-8"
    argv = ["--managed", "--owner", args.owner, "--bve-pid", str(args.bve_pid), "--instance", args.instance]
    return subprocess.Popen([sys.executable, CHILD] + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=ROOT, creationflags=0x08000000)


def wait_until(predicate, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class Owner(object):
    """Plays the Caller: creates Stop and the State block BEFORE the launch, publishes, sets Stop."""

    def __init__(self, args):
        self.sync = mm.Win32Sync()
        self.args = args
        self.stop, _ = self.sync.create_event(args.stop_name)
        self.block = Win32BlockWriter(args.bve_pid, args.instance)

    def ready(self):
        h = self.sync.open_event(self.args.ready_name)
        if h is None:
            return False
        try:
            return self.sync.is_set(h)
        finally:
            self.sync.close(h)

    def close(self):
        self.block.dispose()
        self.sync.close(self.stop)


class StderrPump(object):
    def __init__(self, proc):
        self.lines = []
        self._t = threading.Thread(target=self._run, args=(proc,), daemon=True)
        self._t.start()

    def _run(self, proc):
        for raw in iter(proc.stderr.readline, b""):
            self.lines.append(raw.decode("utf-8", "replace").rstrip())

    def count(self, text):
        return sum(1 for line in list(self.lines) if text in line)

    def join(self):
        self._t.join(3)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter (INCONCLUSIVE for the real Qt loop)")
class F_RealProcess(unittest.TestCase):
    def setUp(self):
        self.args = args_for()
        self.owner = Owner(self.args)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.communicate()
        self.owner.close()

    def launch(self, mode="ok"):
        p = start_child(self.args, mode)
        self.procs.append(p)
        pump = StderrPump(p)
        return p, pump

    def test_full_hud_sequence_with_the_real_loop_and_mapping(self):
        b = self.owner.block
        b.publish(session=False, driving=False, generation=0)
        p, pump = self.launch()
        self.assertTrue(wait_until(self.owner.ready, 20), "Ready was not published")
        time.sleep(0.4)
        self.assertEqual(pump.count("[OVERLAY] show"), 0)                        # initial: Session OFF / Driving OFF -> hidden
        b.publish(session=True, driving=True, generation=1)
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] show") == 1, 5), "HUD was not shown")
        b.publish(driving=False)                                                  # soft OFF
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] hide") == 1, 5))
        b.publish(driving=True)                                                   # soft ON again
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] show") == 2, 5))
        b.publish(session=False)                                                  # scenario closed
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] hide") == 2, 5))
        self.assertIsNone(p.poll())                                               # Python is still alive: no Stop was sent
        self.assertTrue(self.owner.ready())
        b.publish(session=True, driving=True, generation=2)                       # reload
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] show") == 3, 5))
        b.publish(session=False, driving=False, closed=True)                      # Caller Dispose: withdrawn + Closed, then Stop
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] hide") == 3, 5))
        started = time.monotonic()
        self.owner.sync.set_event(self.owner.stop)
        code = p.wait(5)
        pump.join()
        self.assertEqual(code, 0, "\n".join(pump.lines))
        self.assertLess(time.monotonic() - started, 3.0)
        text = "\n".join(pump.lines)
        self.assertIn("overlays=1", text)                                         # ONE overlay for the whole life of the process
        self.assertNotIn("overlays=2", text)
        self.assertEqual(text.count("event=hud-show"), 3)
        self.assertEqual(text.count("event=hud-hide"), 3)                         # soft OFF, session OFF, closed (the shutdown hide finds it hidden)
        self.assertIn("event=hud-summary", text)
        self.assertIn("event=exit", text)
        self.assertFalse(self.owner.ready())

    def test_state_present_before_start_is_the_first_reading(self):
        self.owner.block.publish(session=True, driving=True, generation=5)
        p, pump = self.launch()
        self.assertTrue(wait_until(self.owner.ready, 20))
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] show") == 1, 5))
        self.assertTrue(any("event=state" in line and "gen=5" in line and "mode=active" in line for line in pump.lines))
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)

    def test_stop_is_honoured_while_the_state_keeps_changing(self):
        b = self.owner.block
        p, pump = self.launch()
        self.assertTrue(wait_until(self.owner.ready, 20))
        stop = threading.Event()

        def churn():
            n = 0
            while not stop.is_set():
                n += 1
                b.publish(session=True, driving=(n % 2 == 0), generation=1 + n // 50)
                time.sleep(0.004)
        t = threading.Thread(target=churn, daemon=True)
        t.start()
        time.sleep(0.8)
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        stop.set()
        t.join()
        pump.join()
        self.assertFalse(self.owner.ready())

    def assert_init_failure(self, p, pump, reason):
        """The managed contract was not met at start: exit code 4, AppReady never published, no HUD, ONE state diagnostic."""
        code = p.wait(20)
        pump.join()
        text = "\n".join(pump.lines)
        self.assertEqual(code, 4, text)
        self.assertFalse(self.owner.ready())
        self.assertNotIn("event=ready-published", text)
        self.assertEqual(pump.count("[OVERLAY] show"), 0)
        self.assertEqual(text.count("event=state-contract-failed"), 1, text)
        self.assertIn("reason=" + reason, text)
        self.assertRegex(text, r"event=exit .*code=4 ")
        self.assertIn("ready_published=false", text)
        self.assertIn("end=init-failed", text)
        self.assertEqual(text.count("overlays=1"), 0)                             # the Overlay was never shown or rebuilt

    def test_state_block_missing_fails_the_init_with_exit_code_4_and_no_app_ready(self):
        self.owner.block.dispose()
        p, pump = self.launch()
        self.assert_init_failure(p, pump, "block-missing")

    def test_foreign_pid_block_fails_the_init(self):
        self.owner.block.dispose()
        foreign = Win32BlockWriter(self.args.bve_pid, self.args.instance)           # same NAME, but the header names another BVE process
        foreign._put(make_block(self.args.bve_pid + 1, self.args.instance, True, True, generation=1, count=1))
        self.owner.block = foreign
        p, pump = self.launch()
        self.assert_init_failure(p, pump, "pid")

    def test_foreign_instance_header_fails_the_init(self):
        self.owner.block.dispose()
        foreign = Win32BlockWriter(self.args.bve_pid, self.args.instance)
        foreign._put(make_block(self.args.bve_pid, new_instance(), True, True, generation=1, count=1))
        self.owner.block = foreign
        p, pump = self.launch()
        self.assert_init_failure(p, pump, "instance")

    def test_malformed_blocks_fail_the_init(self):
        for reason, data in (("magic", make_block(self.args.bve_pid, self.args.instance, magic=1)),
                             ("version", make_block(self.args.bve_pid, self.args.instance, version=9)),
                             ("flags", make_block(self.args.bve_pid, self.args.instance, flags=8))):
            self.owner.block._put(data)
            p, pump = self.launch()
            self.assert_init_failure(p, pump, reason)
            self.assertFalse(self.owner.ready())

    def test_hud_failsafe_when_the_block_turns_invalid_after_app_ready(self):
        """After AppReady the block becomes unusable (its header is overwritten): HUD hidden, updates stopped, ONE diagnostic, the process is NOT
        ended and the Overlay is neither rebuilt nor destroyed; it leaves with exit code 0 when the Caller's Stop arrives."""
        b = self.owner.block
        b.publish(session=True, driving=True, generation=1)
        p, pump = self.launch()
        self.assertTrue(wait_until(self.owner.ready, 20))
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] show") == 1, 5))
        b._put(make_block(self.args.bve_pid + 99, self.args.instance, True, True, generation=1, count=9))      # the block is no longer ours
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] hide") == 1, 5), "HUD was not hidden")
        self.assertTrue(wait_until(lambda: pump.count("event=state-lost") == 1, 5))
        time.sleep(0.6)
        self.assertIsNone(p.poll())                                                # the process is not killed
        self.assertTrue(self.owner.ready())                                        # AppReady stays: only the Stop request ends it
        b._put(make_block(self.args.bve_pid, self.args.instance, True, True, generation=7, count=10))         # a block that looks good again changes nothing
        time.sleep(0.6)
        self.assertEqual(pump.count("[OVERLAY] show"), 1)
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        pump.join()
        text = "\n".join(pump.lines)
        self.assertEqual(text.count("event=state-lost"), 1, text)                  # recorded once
        self.assertIn("phase=run", text)
        self.assertIn("end=state-lost", text)
        self.assertRegex(text, r"event=exit .*code=0 ")
        self.assertIn("overlays=1", text)
        self.assertNotIn("overlays=2", text)

    def test_normal_close_and_dispose_are_told_apart_from_a_loss(self):
        b = self.owner.block
        b.publish(session=True, driving=True, generation=1)
        p, pump = self.launch()
        self.assertTrue(wait_until(self.owner.ready, 20))
        self.assertTrue(wait_until(lambda: pump.count("[OVERLAY] show") == 1, 5))
        b.publish(session=False, driving=False, closed=True)                       # what Caller Dispose writes before it sets Stop
        self.assertTrue(wait_until(lambda: pump.count("event=state-closed") == 1, 5))
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        pump.join()
        text = "\n".join(pump.lines)
        self.assertEqual(text.count("event=state-lost"), 0)
        self.assertEqual(text.count("event=state-contract-failed"), 0)
        self.assertIn("end=caller-closed", text)
        self.assertIn("event=stop-received", text)

    def test_stop_without_a_closed_state_is_labelled_as_such(self):
        self.owner.block.publish(session=True, driving=True, generation=1)
        p, pump = self.launch()
        self.assertTrue(wait_until(self.owner.ready, 20))
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        pump.join()
        text = "\n".join(pump.lines)
        self.assertIn("end=stop-without-closed", text)
        self.assertEqual(text.count("event=state-lost"), 0)

    def test_no_bve_window_never_shows_and_still_exits_cleanly(self):
        self.owner.block.publish(session=True, driving=True, generation=1)
        p, pump = self.launch("no-window")
        self.assertTrue(wait_until(self.owner.ready, 20))
        time.sleep(0.8)
        self.assertEqual(pump.count("[OVERLAY] show"), 0)
        self.assertIsNone(p.poll())
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        pump.join()
        self.assertEqual(sum(1 for line in pump.lines if "event=hud-window-wait" in line), 1)

    def test_hud_exceptions_do_not_end_the_process(self):
        self.owner.block.publish(session=True, driving=True, generation=1)
        p, pump = self.launch("boom-update")
        self.assertTrue(wait_until(self.owner.ready, 20))
        time.sleep(0.8)
        self.assertIsNone(p.poll())
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        pump.join()
        self.assertEqual(sum(1 for line in pump.lines if "event=hud-error" in line), mh.MAX_HUD_ERROR_LINES)

    def test_foreign_instance_state_is_never_read(self):
        """A block of ANOTHER instance (another name) does not satisfy the contract: this instance's block is missing -> init failure."""
        self.owner.block.dispose()
        other = Win32BlockWriter(self.args.bve_pid, new_instance())
        other.publish(session=True, driving=True, generation=1)
        try:
            p, pump = self.launch()
            self.assert_init_failure(p, pump, "block-missing")
        finally:
            other.dispose()


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


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, timeout=30)
    except Exception:
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class G_RealOverlayAndScoringLifecycle(unittest.TestCase):
    def test_hud_update_step_keeps_scoring_inert_on_the_real_overlay(self):
        if not port_54321_is_free():
            self.skipTest("UDP 54321 is busy (a running TS Scoring is not touched) - INCONCLUSIVE")
        code = (
            "import os, sys\n"
            "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
            "sys.path.insert(0, %r)\n"
            "from PyQt6.QtWidgets import QApplication\n"
            "app = QApplication(sys.argv[:1])\n"
            "import main, managed_hud\n"
            "o = main.Overlay()\n"
            "o.timer.stop()\n"
            "before = (o.is_scoring_mode, len(o.save_data), len(o.popups), o.menu_state, o.score, o.is_scoring_finished)\n"
            "for i in range(300):\n"
            "    o.bve_time_ms = 1000 + i * 16\n"
            "    o.bve_speed = 20.0\n"
            "    o.bve_location = 100.0 + i\n"
            "    managed_hud.hud_update_step(o)\n"
            "after = (o.is_scoring_mode, len(o.save_data), len(o.popups), o.menu_state, o.score, o.is_scoring_finished)\n"
            "print('SCORING-INERT', before == after, after)\n"
            "o.udp_socket.close()\n"
        ) % ROOT
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=120, cwd=ROOT)
        out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("SCORING-INERT True (False, 0, 0, 0, 0, False)", out)

    def test_normal_mode_process_still_starts_binds_the_port_and_keeps_running(self):
        """The manual mode (python main.py, no arguments) is untouched: it binds UDP 54321, keeps running without BVE, and is ended here by its PID."""
        if not port_54321_is_free():
            self.skipTest("UDP 54321 is busy (a running TS Scoring is not touched) - INCONCLUSIVE")
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py")], env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=0x08000000)
        try:
            bound = wait_until(lambda: not port_54321_is_free(), 30)
            time.sleep(1.5)
            self.assertTrue(bound, "normal mode did not bind UDP 54321")
            self.assertIsNone(p.poll(), "normal mode ended by itself")
        finally:
            p.kill()
            p.communicate()
        self.assertTrue(wait_until(port_54321_is_free, 10))

    def test_the_overlay_class_and_update_logic_are_byte_identical_to_the_e3_commit(self):
        # Phase L3 added the telemetry gate to the Overlay; the guard now proves that THAT is all (tests/overlay_guard.py): update_logic, paintEvent
        # and every other member are AST-identical to the E3 commit, the datagram intake differs only by the accept() line, and the two blocks
        # that moved (telemetry application, jump completion) moved unchanged.
        old = _git("show", E3_COMMIT + ":main.py")
        new = _git("show", "9f25a26c6bc4a578767c7f306672811bf7bf341c:main.py")      # the commit Phase SI-A started from: SI-A's own change set is pinned by tests/test_split_equivalence_sia2.py
        if old is None or new is None:
            self.skipTest("E3 commit / git not available (INCONCLUSIVE)")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # tests\ is not a package
        import overlay_guard
        self.assertEqual(overlay_guard.problems(old, new), [])

    def test_scoring_and_ui_modules_are_unchanged_since_e3(self):
        # hud_ui.py: Phase L3, see test_hud_ui_*;  managed_mode.py: the owner-process watch (tests/test_parent_exit_p1.py guards how little of it moved)
        out = _git("diff", "--name-only", E3_COMMIT, "--", "menu_ui.py", "config.py", "network.py")
        if out is None:
            self.skipTest("git not available (INCONCLUSIVE)")
        self.assertEqual(out.strip(), "")
        # Phase SI-A (on purpose): scoring_logic.py and utils.py carry exactly ONE change since E3 - the switch of the Desktop debug log (no score, no rule, no constant)
        old_scoring, old_utils = _git("show", E3_COMMIT + ":scoring_logic.py"), _git("show", E3_COMMIT + ":utils.py")
        if old_scoring is None or old_utils is None:
            self.skipTest("git not available (INCONCLUSIVE)")

        def parts(src):
            tree = ast.parse(src.replace("\r\n", "\n"))
            return {(n.name if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else ast.dump(n)): ast.dump(n) for n in tree.body}

        for name, old, allowed_changed, allowed_added in (
                ("scoring_logic.py", old_scoring, {"write_limit_debug_log"}, set()),
                ("utils.py", old_utils, {"write_desktop_log"}, {"set_desktop_log_enabled", "desktop_log_enabled", "desktop_log_requested"})):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                new = f.read()
            a, b = parts(old), parts(new)
            removed = set(a) - set(b)
            changed = {k for k in set(a) & set(b) if a[k] != b[k]}
            added = set(b) - set(a)
            # the 'from utils import (...)' statement of scoring_logic gains desktop_log_enabled; the utils module gains the switch variable and the env name
            removed = {k for k in removed if not k.startswith("ImportFrom(module='utils'")}
            added = {k for k in added if not k.startswith("ImportFrom(module='utils'") and not k.startswith("Assign(targets=[Name(id='_desktop_log_enabled'")
                     and not k.startswith("Assign(targets=[Name(id='DESKTOP_LOG_ENV'")}
            self.assertEqual((removed, changed, added), (set(), allowed_changed, allowed_added), name)


# ---------------------------------------------------------------------------------------------------------------------------------------
class H_StaticGuards(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def imports_of(self, name):
        tree = ast.parse(self.read(name))
        found = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                found.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                found.add(n.module.split(".")[0])
        return found

    def test_state_and_hud_modules_are_gui_and_scoring_independent_at_import(self):
        for name in ("managed_state.py", "managed_hud.py"):
            imports = self.imports_of(name)
            self.assertFalse(imports & {"PyQt6", "keyboard", "main", "win32api", "subprocess", "socket"}, (name, imports))
        self.assertEqual(self.imports_of("managed_state.py") - {"ctypes", "struct", "time"}, set())
        # pywin32 (window handling only) and scoring_logic are imported lazily, never at module import
        self.assertEqual(self.imports_of("managed_hud.py") - {"time", "managed_state", "managed_mode", "telemetry_gate", "telemetry_contract", "win32con", "win32gui", "win32process", "scoring_logic"}, set())
        # scoring_logic and the window API are imported lazily, inside the functions that need them
        top = [n for n in ast.parse(self.read("managed_hud.py")).body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual({a.name for n in top for a in n.names if isinstance(n, ast.Import)}, {"time", "managed_state", "telemetry_gate", "telemetry_contract"})

    def test_no_forbidden_operation_in_the_hud_modules(self):
        text = self.read("managed_hud.py") + self.read("managed_state.py")
        code = re.sub(r'"""[\s\S]*?"""', "", text)
        code = re.sub(r"#.*", "", code)
        for token in ("PostMessage", "SendMessage", "keyboard", "on_press_key", "QApplication", ".quit(", "SetForegroundWindow", "taskkill",
                      "os._exit", "sys.exit", "subprocess", "Stop", "write_desktop_log", "is_scoring_mode", "begin_official_jump", "execute_retry",
                      "reset_score_accumulation", "reset_result_display_state", "TerminateProcess"):
            self.assertNotIn(token, code, token)

    def test_no_path_from_driving_or_session_alone_to_process_end(self):
        main_src = self.read("main.py")
        run = main_src[main_src.index("def run_managed"):main_src.index("def _run_normal")]
        self.assertEqual(run.count("app.exec()"), 1)
        self.assertNotIn("QApplication.quit", run)
        hud = self.read("managed_hud.py")
        self.assertNotIn("quit", re.sub(r'"""[\s\S]*?"""', "", hud))

    def test_the_overlay_has_exactly_one_timer_and_the_hud_never_creates_one(self):
        self.assertEqual(len(re.findall(r"QTimer\(", self.read("main.py"))), 1)
        self.assertNotIn("QTimer", re.sub(r'"""[\s\S]*?"""', "", self.read("managed_hud.py")))

    def test_managed_attach_uses_the_one_timer(self):
        src = self.read("main.py")
        attach = src[src.index("def _attach_managed_hud"):src.index("def _release_overlay")]
        self.assertIn("timer.timeout.connect(hud.tick)", attach)
        self.assertIn("timer.timeout.disconnect()", attach)
        self.assertNotIn("QTimer(", attach)

    def test_normal_mode_entry_is_unchanged(self):
        import inspect
        if not HAS_QT:
            self.skipTest("PyQt6 not importable")
        import main
        body = "".join(line.strip() for line in inspect.getsource(main._run_normal).splitlines()[1:])
        self.assertEqual(body, "app = QApplication(sys.argv)overlay = Overlay()overlay.show()return app.exec()")

    @staticmethod
    def code_only(text):
        return re.sub(r"#.*", "", re.sub(r'"""[\s\S]*?"""', "", text))

    def test_z_order_uses_no_global_topmost_no_activation_no_raise(self):
        hud = self.code_only(self.read("managed_hud.py"))
        for token in ("HWND_TOPMOST", "WindowStaysOnTopHint", "raise_", "activateWindow", "SetForegroundWindow", "BringWindowToTop", "SWP_SHOWWINDOW",
                      "SWP_NOZORDER", "SetFocus", "SetActiveWindow"):
            self.assertNotIn(token, hud, token)
        main = self.code_only(self.read("main.py"))
        for token in ("WindowStaysOnTopHint", "HWND_TOPMOST", "raise_(", "activateWindow"):
            self.assertNotIn(token, main, token)
        self.assertIn("self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)", main)

    def test_the_only_set_window_pos_is_the_pure_z_operation(self):
        hud = self.code_only(self.read("managed_hud.py"))
        self.assertEqual(hud.count("SetWindowPos("), 1)
        body = hud[hud.index("def place_below"):]
        body = body[:body.index("def hud_update_step")]
        for flag in ("SWP_NOMOVE", "SWP_NOSIZE", "SWP_NOACTIVATE"):
            self.assertIn(flag, body)
        self.assertEqual(hud.count("place_below("), 2)           # the definition and the controller's one call

    def test_the_selection_window_is_never_identified(self):
        hud = self.code_only(self.read("managed_hud.py"))
        for token in ("GetWindowText(hwnd).lower()", ):          # the BVE window lookup of the normal mode (title "bve trainsim") is the only title use
            self.assertEqual(hud.count(token), 1)
        for token in ("GetClassName", "ScenarioSelect", "シナリオ", "select", "Select", "generation_changed"):
            body = hud[hud.index("def _ensure_z_order"):hud.index("def _unlink")]
            self.assertNotIn(token, body, token)

    def test_the_hud_module_has_no_host_branch(self):
        hud = self.code_only(self.read("managed_hud.py"))
        for token in ("Legacy", "AtsEx", "BveEx", "BveEX", "Current", "BVE5", "BVE6"):
            self.assertNotIn(token, hud, token)

    def test_main_py_and_hud_ui_are_untouched_by_the_z_order_fix(self):
        out = _git("diff", "--name-only", L3_GRADIENT_COMMIT, "9f25a26c6bc4a578767c7f306672811bf7bf341c", "--", "main.py", "hud_ui.py", "scoring_logic.py", "menu_ui.py", "network.py", "telemetry_contract.py")
        if out is None:
            self.skipTest("git not available (INCONCLUSIVE)")
        self.assertEqual(out.strip(), "")

    def test_all_python_files_compile(self):
        import py_compile
        with tempfile.TemporaryDirectory() as d:
            for name in ("main.py", "managed_mode.py", "managed_state.py", "managed_hud.py", os.path.join("tests", "zorder_real_check.py"),
                         os.path.join("tests", "managed_hud_child.py"), os.path.join("tests", "fake_bve_window.py"),
                         os.path.join("tests", "test_managed_hud_e4.py")):
                py_compile.compile(os.path.join(ROOT, name), cfile=os.path.join(d, name.replace(os.sep, "_") + "c"), doraise=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
