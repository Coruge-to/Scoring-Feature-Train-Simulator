import pathlib
import struct
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
import managed_app_directory as m

PID = 4242
INST = "0123456789abcdef0123456789abcdef"


def block(flags, instance=INST, app_pid=0, head=2, tail=2, **kw):
    raw = instance.encode("ascii") if instance else b"\0" * 32
    values = [m.DIRECTORY_MAGIC, m.DIRECTORY_VERSION, m.DIRECTORY_SIZE, PID,
              head, flags, raw, app_pid, 7, 0, 0, 0, tail]
    names = ["magic", "version", "size", "pid", "head", "flags", "instance",
             "app_pid", "count", "reserved0", "reserved1", "reserved2", "tail"]
    for key, value in kw.items():
        values[names.index(key)] = value
    return struct.pack("<IIIIII32sIIIIII", *values)


class FakeSource(object):
    def __init__(self, readings=None, opens=True):
        self.readings = list(readings or [])
        self.opens = opens
        self.closed = 0
        self.name = None
    def open(self, name):
        self.name = name
        return self.opens
    def read(self):
        if not self.readings:
            return None
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
    def close(self):
        self.closed += 1


class Contract(unittest.TestCase):
    def parse(self, data):
        return m.parse_directory(data, PID)
    def test_name(self):
        self.assertEqual(m.directory_name(PID), "Local\\TSScoringPlugin.v1.4242.AppDirectory")
        for bad in (0, -1, True, 0x100000000):
            with self.assertRaises(ValueError): m.directory_name(bad)
    def test_valid_lifecycle_states(self):
        cases = [
            (m.FLAG_INSTANCE_PUBLISHED, 0, False),
            (m.FLAG_INSTANCE_PUBLISHED | m.FLAG_PROCESS_STARTED, 99, False),
            (m.FLAG_INSTANCE_PUBLISHED | m.FLAG_PROCESS_STARTED | m.FLAG_READY_ACCEPTED, 99, True),
            (m.FLAG_INSTANCE_PUBLISHED | m.FLAG_PROCESS_STARTED | m.FLAG_READY_ACCEPTED | m.FLAG_WITHDRAWING, 99, False),
        ]
        for flags, app_pid, usable in cases:
            snap, reason = self.parse(block(flags, app_pid=app_pid))
            self.assertIsNone(reason)
            self.assertEqual(snap.usable, usable)
    def test_closed_is_exact_and_empty(self):
        snap, reason = self.parse(block(m.FLAG_CLOSED, instance="", app_pid=0))
        self.assertIsNone(reason)
        self.assertTrue(snap.closed)
        self.assertEqual((snap.instance, snap.app_pid), ("", 0))
        for data in (block(m.FLAG_CLOSED | m.FLAG_WITHDRAWING, instance=""),
                     block(m.FLAG_CLOSED, instance=INST), block(m.FLAG_CLOSED, instance="", app_pid=1)):
            self.assertEqual(self.parse(data)[1], "closed")
    def test_header_rejections(self):
        cases = [(b"x", "short"), (block(m.FLAG_INSTANCE_PUBLISHED, magic=0), "magic"),
                 (block(m.FLAG_INSTANCE_PUBLISHED, version=2), "version"),
                 (block(m.FLAG_INSTANCE_PUBLISHED, size=79), "size"),
                 (block(m.FLAG_INSTANCE_PUBLISHED, pid=1), "pid"),
                 (block(m.FLAG_INSTANCE_PUBLISHED, head=3, tail=3), "torn"),
                 (block(m.FLAG_INSTANCE_PUBLISHED, head=2, tail=4), "torn")]
        for data, expected in cases:
            self.assertEqual(self.parse(data)[1], expected)
    def test_flags_instance_pid_and_reserved_rejections(self):
        self.assertEqual(self.parse(block(0))[1], "flags")
        self.assertEqual(self.parse(block(m.FLAG_READY_ACCEPTED, app_pid=9))[1], "flags")
        self.assertEqual(self.parse(block(m.FLAG_INSTANCE_PUBLISHED | m.FLAG_PROCESS_STARTED, app_pid=0))[1], "app-pid")
        self.assertEqual(self.parse(block(m.FLAG_INSTANCE_PUBLISHED, app_pid=9))[1], "app-pid")
        self.assertEqual(self.parse(block(m.FLAG_INSTANCE_PUBLISHED, instance="g" * 32))[1], "instance")
        self.assertEqual(self.parse(block(m.FLAG_INSTANCE_PUBLISHED | 0x80))[1], "flags")
        for key in ("reserved0", "reserved1", "reserved2"):
            self.assertEqual(self.parse(block(m.FLAG_INSTANCE_PUBLISHED, **{key: 1}))[1], "reserved")


class Reader(unittest.TestCase):
    def test_open_and_poll(self):
        a = block(m.FLAG_INSTANCE_PUBLISHED)
        b = block(m.FLAG_INSTANCE_PUBLISHED | m.FLAG_PROCESS_STARTED, app_pid=55, head=4, tail=4)
        source = FakeSource([a, a, b, b])
        r = m.DirectoryReader(PID, source)
        self.assertTrue(r.open())
        self.assertEqual(source.name, m.directory_name(PID))
        self.assertEqual(r.last.instance, INST)
        self.assertEqual(r.poll().app_pid, 55)
    def test_missing_and_invalid_open_close_the_source(self):
        r = m.DirectoryReader(PID, FakeSource(opens=False))
        self.assertFalse(r.open())
        self.assertEqual(r.open_failure, "block-missing")
        bad = FakeSource([block(m.FLAG_INSTANCE_PUBLISHED, magic=0)] * 2)
        r = m.DirectoryReader(PID, bad)
        self.assertFalse(r.open())
        self.assertEqual((r.open_failure, bad.closed), ("magic", 1))
    def test_changed_copies_retry(self):
        a = block(m.FLAG_INSTANCE_PUBLISHED, head=2, tail=2)
        b = block(m.FLAG_INSTANCE_PUBLISHED, head=4, tail=4)
        source = FakeSource([a, b, b, b])
        r = m.DirectoryReader(PID, source)
        self.assertTrue(r.open())
        self.assertEqual(r.torn_retries, 1)
    def test_runtime_rejection_returns_none_not_stale_identity(self):
        good = block(m.FLAG_INSTANCE_PUBLISHED | m.FLAG_PROCESS_STARTED | m.FLAG_READY_ACCEPTED, app_pid=55)
        bad = block(m.FLAG_INSTANCE_PUBLISHED, magic=0)
        source = FakeSource([good, good, bad, bad])
        r = m.DirectoryReader(PID, source)
        self.assertTrue(r.open())
        self.assertIsNone(r.poll())
        self.assertEqual(r.last_rejection, "magic")
        self.assertEqual(r.last.app_pid, 55)


if __name__ == "__main__":
    unittest.main()
