"""PID-D4 Legacy Jump 2A-alpha, Stage S1 (tests first): the Reader contract of the managed application's jump client (current_jump_client.py).

The 2A-alpha Writer (a Legacy plugin) deletes and re-creates its named Directory mapping at any time (RC-10). A Reader that keeps its mapping handle between two reads
makes that CreateNew fail, so the Reader contract is: every read is open -> read (twice) -> close, nothing is kept in between, the Directory name is resolved over the
two known host names (Current and Legacy) when a command is sent, and an outstanding request then reads only the name that was recorded.

These tests use counting fake sources (no operating system object, no clock of the machine, no socket) and the product client directly. They are written BEFORE the
Python Reader change (Stage S2): against the current Reader they are an EXPECTED RED, and each failing assertion carries a [contract:...] tag that names the missing
behaviour, so that a red of this file can be told apart from a defect of the test itself:

    [contract:reader-holds-handle]        the client keeps the mapping open between reads (open count != close count, or still open)
    [contract:name-resolution-api-missing] dataplane_contract has no legacy_jump_name / jump_directory_names yet
    [contract:read-directories-missing]   the client has no read-only read_directories() yet
    [contract:attached-flag]              the old _attached flag still exists in the client code

LEGACYJUMP_2A_PYROOT (optional) points at another directory that holds current_jump_client.py / dataplane_contract.py / managed_app_directory.py. It exists only so
that the S1 fixture check can run these tests against a synthetic reference Reader outside the repository; unset, the repository root is used.

PR-7 (real Windows mapping) is in test_legacy_jump_plane_interop_2a.py. PR-9 (Current regression) is the existing Current test files. PR-10 (name parity) is in
test_dataplane_contract_pid_d1.py.
"""
import os
import re
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("LEGACYJUMP_2A_PYROOT") or os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import current_jump_client  # noqa: E402
import dataplane_contract as contract  # noqa: E402

PID = 4242
INSTANCE = "0123456789abcdef0123456789abcdef"
APP_PID = 5555
TOKEN_A = bytes(range(101, 117))
TOKEN_B = bytes(range(201, 217))
STA = "JUMP_STA_TIME:1:36000"
LOC = "JUMP_LOC_TIME:123.5:36000"
READY = contract.PUBLISHED | contract.READY
ALL_CAPS = contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME | contract.JUMP_CAP_REQUEST_ID
REQUEST_ID_ONLY = contract.JUMP_CAP_REQUEST_ID
FIXED_PORTS = (54321, 54322)


def block(pid=PID, state=READY, port=41000, generation=11, token=TOKEN_A, caps=ALL_CAPS, seq=2, change=1):
    if state == contract.CLOSED:
        return contract.encode_jump_directory(pid, seq, state, 0, 0, 0, bytes(16), change, 0)
    return contract.encode_jump_directory(pid, seq, state, pid, port, generation, token, change, caps)


def current_name():
    return contract.jump_name(PID)


def legacy_name():
    return contract.legacy_jump_name(PID)


class Clock(object):
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class CountingSource(object):
    """The read-only mapping source of the client with a table of named blocks and exact open / close accounting.

    open() mirrors managed_app_directory.Win32DirectorySource.open: when a mapping is already open it answers True without opening another one (the old client relied on
    that by staying attached)."""

    def __init__(self, blocks=None):
        self.blocks = dict(blocks or {})
        self.current = None
        self.held = None                  # what an open handle still shows even after the writer released its own handle (a mapping lives while any handle is open)
        self.opens = 0
        self.closes = 0
        self.reads = 0
        self.requested = []
        self.read_error = None
        self.torn = False
        self._toggle = 0

    @property
    def is_open(self):
        return self.current is not None

    def open(self, name):
        self.requested.append(name)
        if self.current is not None:
            return True
        if self.blocks.get(name) is None:
            return False
        self.current = name
        self.held = self.blocks[name]
        self.opens += 1
        return True

    def read(self):
        if self.current is None:
            return None
        self.reads += 1
        if self.read_error is not None:
            raise self.read_error
        data = self.blocks.get(self.current, self.held)
        if self.torn:
            self._toggle += 1
            if self._toggle % 2 == 0:
                data = bytearray(data)
                data[40] ^= 0x01
                data = bytes(data)
        return data

    def close(self):
        if self.current is not None:
            self.current = None
            self.closes += 1


class Harness(object):
    def __init__(self, blocks=None, **kw):
        self.clock = Clock()
        self.source = CountingSource(blocks)
        self.sent = []
        self.log = []
        ids = iter(bytes([n]) * 16 for n in range(1, 200))
        self.client = current_jump_client.CurrentJumpClient(
            PID, INSTANCE, APP_PID, lambda data, port: self.sent.append((data, port)) or True, source=self.source, log=self.log.append,
            clock=self.clock.monotonic, id_factory=lambda: next(ids), **kw)

    def watch(self):
        """Lets the watch interval pass and polls once."""
        self.clock.advance(current_jump_client.WATCH_INTERVAL_S + 0.01)
        self.client.poll()


def code_of(path):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    text = re.sub(r"'''[\s\S]*?'''", "", text)
    return re.sub(r"#[^\n]*", "", text)


class ReaderContract2A(unittest.TestCase):
    def need_names(self):
        for attr in ("legacy_jump_name", "jump_directory_names"):
            if not hasattr(contract, attr):
                self.fail("[contract:name-resolution-api-missing] dataplane_contract.%s does not exist yet" % attr)

    def need_read_directories(self):
        if not hasattr(current_jump_client.CurrentJumpClient, "read_directories"):
            self.fail("[contract:read-directories-missing] CurrentJumpClient.read_directories() does not exist yet")

    def assert_no_handle(self, src, where):
        if src.is_open or src.opens != src.closes:
            self.fail("[contract:reader-holds-handle] %s: open=%s opens=%d closes=%d" % (where, src.is_open, src.opens, src.closes))

    # -- PR-1 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr1_no_handle_after_send_complete_idle_and_outstanding(self):
        h = Harness({current_name(): block()})
        rid = h.client.send(STA)
        self.assertIsNotNone(rid, "the command is sent over a READY Current directory")
        self.assert_no_handle(h.source, "after a successful send")
        self.assertEqual(h.client.complete(rid), current_jump_client.R_OK)
        self.assert_no_handle(h.source, "after the completion")
        for n in range(5):                                       # idle: no outstanding request
            h.watch()
            self.assert_no_handle(h.source, "idle poll #%d" % n)
        rid2 = h.client.send(LOC)
        self.assertIsNotNone(rid2)
        for n in range(6):                                       # outstanding: every watch reads, every watch closes
            h.watch()
            self.assert_no_handle(h.source, "outstanding poll #%d" % n)
        self.assertGreaterEqual(h.source.opens, 7, "the watch really read the directory each time")
        self.assertEqual(h.source.opens, h.source.closes)

    # -- PR-2 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr2_every_exit_of_the_read_closes_the_mapping(self):
        scenarios = []

        def add(label, blocks, reason, setup=None):
            scenarios.append((label, blocks, reason, setup))

        bad_magic = bytearray(block())
        bad_magic[0] ^= 0xFF
        add("missing", {}, "jump-directory-missing")
        add("decode failure", {current_name(): bytes(bad_magic)}, "jump-directory-invalid:magic")
        add("torn read", {current_name(): block()}, "jump-directory-torn", lambda s: setattr(s, "torn", True))
        add("read raises OSError", {current_name(): block()}, "jump-directory-error:OSError", lambda s: setattr(s, "read_error", OSError("boom")))
        add("another BVE pid", {current_name(): block(pid=PID + 4)}, "bve-pid-mismatch")
        add("PUBLISHED only (not READY)", {current_name(): block(state=contract.PUBLISHED)}, "jump-endpoint-not-usable")
        add("WITHDRAWING", {current_name(): block(state=READY | contract.WITHDRAWING)}, "jump-endpoint-not-usable")
        add("CLOSED", {current_name(): block(state=contract.CLOSED)}, "jump-endpoint-not-usable")
        add("no REQUEST_ID capability", {current_name(): block(caps=contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME)}, "request-id-unsupported")
        add("no command capability", {current_name(): block(caps=REQUEST_ID_ONLY)}, "command-unsupported")
        failures = []
        for label, blocks, reason, setup in scenarios:
            with self.subTest(label):
                h = Harness(blocks)
                if setup is not None:
                    setup(h.source)
                self.assertIsNone(h.client.send(STA), label)
                self.assertIn("refused:" + reason, h.client.reasons, "%s: the refusal vocabulary is unchanged" % label)
                if h.source.is_open or h.source.opens != h.source.closes:
                    failures.append("%s (open=%s opens=%d closes=%d)" % (label, h.source.is_open, h.source.opens, h.source.closes))
                self.assertEqual(h.sent, [], "%s: nothing is sent" % label)
        if failures:
            self.fail("[contract:reader-holds-handle] the mapping stays open after: " + "; ".join(failures))

    # -- PR-3 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr3_withdrawn_and_closed_leave_no_handle_and_a_new_endpoint_is_a_new_one(self):
        for terminal in (READY | contract.WITHDRAWING, contract.CLOSED):
            with self.subTest(state=terminal):
                h = Harness({current_name(): block(generation=11, token=TOKEN_A)})
                rid1 = h.client.send(STA)
                self.assertIsNotNone(rid1)
                self.assert_no_handle(h.source, "after the first send")
                first = contract.decode_envelope(h.sent[-1][0])
                self.assertEqual((first["generation"], bytes(first["token"])), (11, TOKEN_A))
                h.source.blocks[current_name()] = block(state=terminal, generation=11, token=TOKEN_A, seq=4, change=2)
                h.watch()
                self.assertEqual(h.client.take_unreleased(), "endpoint-withdrawn")
                self.assert_no_handle(h.source, "after the endpoint was seen withdrawn / closed")
                h.source.blocks[current_name()] = block(generation=12, token=TOKEN_B, seq=6, change=3, port=41001)
                rid2 = h.client.send(STA)
                self.assertIsNotNone(rid2)
                second = contract.decode_envelope(h.sent[-1][0])
                self.assertEqual((second["generation"], bytes(second["token"]), h.sent[-1][1]), (12, TOKEN_B, 41001), "only the NEW generation / token / port are used (RC-3)")
                self.assertEqual(h.client.complete(rid1), current_jump_client.R_STALE, "the cancelled request can only answer stale")
                self.assert_no_handle(h.source, "after the new send")

    # -- PR-4 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr4_outstanding_request_reads_open_read_close_each_watch_and_only_its_own_name(self):
        self.need_names()
        h = Harness({current_name(): block()})
        rid = h.client.send(STA)
        self.assertIsNotNone(rid)
        recorded = h.source.requested[:]
        before_opens = h.source.opens
        h.client.poll()                                        # inside the watch interval: no read at all
        self.assertEqual(h.source.opens, before_opens, "no read before the watch interval has passed")
        # a Legacy directory appears later: the request does not move over and nothing becomes ambiguous
        h.source.blocks[legacy_name()] = block(caps=REQUEST_ID_ONLY, port=42000, generation=21, token=TOKEN_B)
        mark = len(h.source.requested)
        for n in range(4):
            h.watch()
            self.assert_no_handle(h.source, "watch #%d" % n)
        later = set(h.source.requested[mark:])
        self.assertEqual(later, {current_name()}, "[contract:poll-reads-recorded-name-only] an outstanding request reads only the name recorded at send time, read: %r" % sorted(later))
        self.assertTrue(h.client.has_outstanding, "a Directory that appeared later does not cancel the request")
        # generation / token change -> endpoint-changed
        h.source.blocks[current_name()] = block(generation=12, token=TOKEN_B, seq=4, change=2)
        h.watch()
        self.assertEqual(h.client.take_unreleased(), "endpoint-changed")
        self.assert_no_handle(h.source, "after endpoint-changed")
        self.assertEqual(recorded[0], current_name())

    def test_pr4_outstanding_request_ends_when_its_directory_disappears(self):
        h = Harness({current_name(): block()})
        self.assertIsNotNone(h.client.send(STA))
        del h.source.blocks[current_name()]
        h.watch()
        got = h.client.take_unreleased()
        if got != "endpoint-jump-directory-missing" and h.source.is_open:
            self.fail("[contract:reader-holds-handle] the client still holds the vanished mapping open and never sees it disappear (got %r)" % (got,))
        self.assertEqual(got, "endpoint-jump-directory-missing")
        self.assert_no_handle(h.source, "after the directory vanished")

    def test_pr4_timeout_is_unchanged_and_releases(self):
        h = Harness({current_name(): block()})
        self.assertIsNotNone(h.client.send(STA))
        h.clock.advance(current_jump_client.OUTSTANDING_TIMEOUT_S + 1.0)
        h.client.poll()
        self.assertEqual(h.client.take_unreleased(), "timeout")
        self.assert_no_handle(h.source, "after the timeout")

    # -- PR-5 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr5_name_resolution(self):
        self.need_names()
        names = contract.jump_directory_names(PID)
        self.assertEqual(names, (contract.jump_name(PID), contract.legacy_jump_name(PID)), "Current first, Legacy second")
        # Current only (unchanged behaviour)
        h = Harness({current_name(): block()})
        self.assertIsNotNone(h.client.send(STA))
        self.assertEqual(h.sent[-1][1], 41000)
        # Legacy only, with command capabilities: the same generic mechanism takes it
        h = Harness({legacy_name(): block(port=42000, generation=21, token=TOKEN_B)})
        self.assertIsNotNone(h.client.send(STA))
        self.assertEqual((h.sent[-1][1], contract.decode_envelope(h.sent[-1][0])["generation"]), (42000, 21))
        # both usable: ambiguous, nothing is sent, no fallback to a fixed port
        h = Harness({current_name(): block(), legacy_name(): block(port=42000, generation=21, token=TOKEN_B)})
        self.assertIsNone(h.client.send(STA))
        self.assertIn("refused:jump-host-ambiguous", h.client.reasons)
        self.assertEqual(h.sent, [], "nothing is sent when two hosts claim the process")
        self.assertFalse([p for _d, p in h.sent if p in FIXED_PORTS])
        self.assert_no_handle(h.source, "after the ambiguous refusal")
        # neither exists
        h = Harness({})
        self.assertIsNone(h.client.send(STA))
        self.assertIn("refused:jump-directory-missing", h.client.reasons)
        self.assertEqual(sorted(set(h.source.requested)), sorted(names), "both known names were looked at, nothing else")
        # one exists but is invalid: the other (usable) one is taken, there is no ambiguity
        bad = bytearray(block())
        bad[0] ^= 0xFF
        h = Harness({current_name(): bytes(bad), legacy_name(): block(port=42000, generation=21, token=TOKEN_B)})
        self.assertIsNotNone(h.client.send(STA))
        self.assertEqual(h.sent[-1][1], 42000)
        # one is another BVE process's, the other usable
        h = Harness({current_name(): block(pid=PID + 4), legacy_name(): block(port=42000, generation=21, token=TOKEN_B)})
        self.assertIsNotNone(h.client.send(STA))
        # one exists but is WITHDRAWING, the other usable
        h = Harness({current_name(): block(state=READY | contract.WITHDRAWING), legacy_name(): block(port=42000, generation=21, token=TOKEN_B)})
        self.assertIsNotNone(h.client.send(STA))
        # the chosen name is fixed at send time: an outstanding request is not moved to a name that shows up later
        h = Harness({legacy_name(): block(port=42000, generation=21, token=TOKEN_B)})
        self.assertIsNotNone(h.client.send(STA))
        h.source.blocks[current_name()] = block()
        mark = len(h.source.requested)
        h.watch()
        self.assertEqual(set(h.source.requested[mark:]), {legacy_name()}, "[contract:poll-reads-recorded-name-only] the request stays on the name it was sent through")
        self.assertTrue(h.client.has_outstanding)
        # generation change of the recorded name ends the request
        h.source.blocks[legacy_name()] = block(port=42000, generation=22, token=TOKEN_B, seq=4, change=2)
        h.watch()
        self.assertEqual(h.client.take_unreleased(), "endpoint-changed")

    # -- PR-6 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr6_request_id_only_legacy_directory_sends_nothing(self):
        self.need_names()
        h = Harness({legacy_name(): block(caps=REQUEST_ID_ONLY, port=42000, generation=21, token=TOKEN_B)})
        for text in (STA, LOC):
            self.assertIsNone(h.client.send(text), "no RequestId for " + text)
        self.assertEqual(h.client.reasons.get("refused:command-unsupported"), 2)
        self.assertEqual(h.sent, [], "ZERO datagrams are handed to the send callback")
        self.assertIsNone(h.client.send("NORMAL_JUMP:1"))
        self.assertIn("refused:unknown-command", h.client.reasons)
        self.assertEqual(set(h.source.requested), set(contract.jump_directory_names(PID)), "only the two known directory names were ever opened")
        self.assertFalse([n for n in h.source.requested if "54321" in n or "54322" in n])
        self.assert_no_handle(h.source, "after the refusals")

    # -- read_directories (the read-only harness entry of G-3b) --------------------------------------------------------------------------
    def test_read_directories_is_read_only_and_closes(self):
        self.need_names()
        self.need_read_directories()
        h = Harness({current_name(): block(), legacy_name(): block(caps=REQUEST_ID_ONLY, port=42000, generation=21, token=TOKEN_B)})
        rows = h.client.read_directories()
        self.assertEqual([r[0] for r in rows], list(contract.jump_directory_names(PID)))
        self.assertTrue(all(r[1] is not None and r[2] is None for r in rows))
        self.assertEqual(rows[1][1]["capabilities"], REQUEST_ID_ONLY)
        self.assert_no_handle(h.source, "after read_directories")
        self.assertEqual(h.sent, [], "reading sends nothing")
        self.assertFalse(h.client.has_outstanding)
        self.assertEqual(h.client.counts, {"sent": 0, "completed": 0}, "reading changes no counter")
        del h.source.blocks[current_name()]
        rows = h.client.read_directories()
        self.assertEqual((rows[0][1], rows[0][2]), (None, "jump-directory-missing"))

    # -- PR-8 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr8_reader_cycle_time_is_recorded(self):
        self.need_read_directories()
        h = Harness({current_name(): block(), legacy_name(): block(caps=REQUEST_ID_ONLY, port=42000, generation=21, token=TOKEN_B)})
        loops = 2000
        begin = time.perf_counter()
        for _n in range(loops):
            h.client.read_directories()
        elapsed = time.perf_counter() - begin
        per = elapsed / loops * 1000.0
        sys.stderr.write("PR-8 reader cycle (2 names, fake source, pure python): %.4f ms per cycle over %d cycles\n" % (per, loops))
        self.assertGreater(per, 0.0)
        self.assertEqual(h.source.opens, h.source.closes, "every cycle opened and closed")
        self.assertEqual(h.source.opens, 2 * loops)

    # -- PR-11 -----------------------------------------------------------------------------------------------------------------------------
    def test_pr11_client_code_static_guards(self):
        code = code_of(os.path.join(ROOT, "current_jump_client.py")).lower()
        for word in ("legacy", "atsex", "bveex", "pyqt", "import socket", "qudp", "scenario", "54321", "54322"):
            self.assertNotIn(word, code, "the client code names no host, no Qt, no socket and no fixed port: " + word)
        if "_attached" in code:
            self.fail("[contract:attached-flag] the old _attached flag still exists in the client code")


if __name__ == "__main__":
    unittest.main()
