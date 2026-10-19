"""PID-D4 Legacy Jump 2A-alpha, Stage S1 (tests first): the managed application's product jump client against a REAL product plane on Windows (PR-7, ITR-05, ITR-12).

A product plane (the Legacy plugin's Jump control plane) is served by TsScoringPlugin/Handshake/Tests/Serve-LegacyJumpPlane2A.ps1 on a synthetic BVE PID: a real named
mapping `Local\\TSScoringPlugin.v1.<synthetic pid>.LegacyJump`, a real loopback UDP port, the dedicated worker. This file talks to it with the PRODUCT client and the real
`managed_app_directory.Win32DirectorySource` (wrapped by a counter), through plain files of a control directory. No BVE, no Qt, no fixed port: UDP 54321 / 54322 are never
bound and never written to, and the synthetic PID is odd and huge so that it can never be a live process.

Written BEFORE the product exists (Stage S1): while the plane is absent from the product DLL, setUpClass records the reason and every test fails with
    [contract:plane-absent]            the product DLL has no LegacyJump control plane yet (an EXPECTED RED)
and once the plane exists but the Python Reader is the old one the tests fail with
    [contract:reader-holds-handle]     the client keeps the mapping open between reads
    [contract:read-directories-missing] the client has no read-only read_directories() yet

Environment (optional; they exist so that the S1 fixture check can run these tests against a synthetic reference outside the repository):
    LEGACYJUMP_2A_PYROOT       directory with current_jump_client.py / dataplane_contract.py / managed_app_directory.py
    LEGACYJUMP_2A_PRODUCT_DLL  the product Legacy telemetry DLL that holds the plane
Unset: the repository root and Telemetry/Legacy/out/TSScoringPlugin.AtsExLegacy.Telemetry.dll are used.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROOT = os.environ.get("LEGACYJUMP_2A_PYROOT") or REPO
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import current_jump_client  # noqa: E402
import dataplane_contract as contract  # noqa: E402
import managed_app_directory  # noqa: E402

DEFAULT_DLL = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "out", "TSScoringPlugin.AtsExLegacy.Telemetry.dll")
PRODUCT_DLL = os.environ.get("LEGACYJUMP_2A_PRODUCT_DLL") or DEFAULT_DLL
SERVE = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Tests", "Serve-LegacyJumpPlane2A.ps1")
STA = "JUMP_STA_TIME:1:36000"
LOC = "JUMP_LOC_TIME:123.5:36000"
FIXED_PORTS = (54321, 54322)


class CountingWin32Source(object):
    """The real read-only mapping source, with open / close accounting."""

    def __init__(self):
        self.real = managed_app_directory.Win32DirectorySource(contract.DIRECTORY_SIZE)
        self.opens = 0
        self.closes = 0
        self.requested = []

    @property
    def is_open(self):
        return self.real.is_open

    def open(self, name):
        self.requested.append(name)
        was_open = self.real.is_open
        ok = self.real.open(name)
        if ok and not was_open:
            self.opens += 1
        return ok

    def read(self):
        return self.real.read()

    def close(self):
        if self.real.is_open:
            self.closes += 1
        self.real.close()


class PlaneServer(object):
    """The served product plane: one PowerShell process, commands and replies as files."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="tss2a-")
        self.n = 0
        self.error = None
        self.ready = None
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SERVE, "-ControlDir", self.dir, "-ProductDll", PRODUCT_DLL, "-TimeoutSec", "240"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.time() + 150
        ready = os.path.join(self.dir, "ready.json")
        err = os.path.join(self.dir, "error.json")
        while time.time() < deadline:
            loaded = self._load(ready)
            if loaded is not None:
                self.ready = loaded
                return
            loaded = self._load(err)
            if loaded is not None:
                self.error = loaded
                return
            if self.proc.poll() is not None and not os.path.exists(ready) and not os.path.exists(err):
                self.error = {"kind": "script", "code": "", "text": "the serve script ended with exit code %s without a word" % self.proc.returncode}
                return
            time.sleep(0.1)
        self.error = {"kind": "script", "code": "", "text": "the serve script did not become ready in time"}

    @staticmethod
    def _load(path):
        """The parsed JSON file, or None when it does not exist yet or cannot be read at this moment (a scanner or the writer may still hold it: Windows then says Permission denied)."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def command(self, word, timeout=30.0):
        self.n += 1
        name = "%04d" % self.n
        path = os.path.join(self.dir, "cmd-%s.txt" % name)
        with open(path + ".tmp", "w", encoding="ascii") as handle:
            handle.write(word)
        os.replace(path + ".tmp", path)
        reply = os.path.join(self.dir, "reply-%s.json" % name)
        deadline = time.time() + timeout
        while time.time() < deadline:
            loaded = self._load(reply)
            if loaded is not None:
                return loaded
            time.sleep(0.02)
        raise AssertionError("no reply to %r" % word)

    def close(self):
        try:
            if self.error is None and not getattr(self, "finished", False) and self.proc.poll() is None:
                try:
                    self.command("finish", 20.0)
                except Exception:
                    pass
            if self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=20)
                except Exception:
                    self.proc.kill()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


class PlaneInterop2A(unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        if os.name != "nt":
            cls.skip_reason = "needs Windows named mappings"
            return
        if not os.path.exists(PRODUCT_DLL):
            cls.server = None
            cls.missing_dll = True
            return
        cls.missing_dll = False
        cls.server = PlaneServer()

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            cls.server.close()

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)
        if getattr(self, "missing_dll", False):
            self.fail("[contract:plane-absent] the product DLL does not exist: %s" % PRODUCT_DLL)
        err = self.server.error
        if err is not None:
            if err.get("kind") == "product-absent":
                self.fail("[contract:plane-absent] the product DLL has no LegacyJump control plane yet (%s)" % err.get("code"))
            self.fail("[contract:plane-start-failed] %s: %s" % (err.get("kind"), str(err.get("text"))[:300]))
        self.server.command("await-ready", 30.0)

    def status(self):
        return self.server.command("status")

    def client(self, source, sent=None):
        s = self.status()
        out = [] if sent is None else sent
        return current_jump_client.CurrentJumpClient(
            s["bve_pid"], s["app_instance"], s["app_pid"], lambda data, port: out.append((data, port)) or True, source=source), s

    def need_read_directories(self):
        if not hasattr(current_jump_client.CurrentJumpClient, "read_directories"):
            self.fail("[contract:read-directories-missing] CurrentJumpClient.read_directories() does not exist yet")
        for attr in ("legacy_jump_name", "jump_directory_names"):
            if not hasattr(contract, attr):
                self.fail("[contract:name-resolution-api-missing] dataplane_contract.%s does not exist yet" % attr)

    def legacy_row(self, client, pid):
        rows = client.read_directories()
        by_name = dict((r[0], r) for r in rows)
        return by_name[contract.legacy_jump_name(pid)], by_name[contract.jump_name(pid)]

    # -- PR-7 ------------------------------------------------------------------------------------------------------------------------------
    def test_pr7_each_poll_then_dispose_and_create_succeeds_at_the_first_attempt(self):
        self.need_read_directories()
        src = CountingWin32Source()
        client, st = self.client(src)
        previous = (st["generation"], st["token"])
        firsts = 0
        cycles = 6
        for i in range(cycles):
            for _n in range(20):                              # idle reads between the cycles: none of them may keep the mapping
                (name, snap, reason), (cname, csnap, creason) = self.legacy_row(client, st["bve_pid"])
                if src.is_open:
                    self.fail("[contract:reader-holds-handle] cycle %d: the Reader still holds the mapping after a read" % i)
            self.assertIsNone(reason, "cycle %d: the Legacy directory is readable" % i)
            self.assertIsNotNone(snap, "cycle %d: the Legacy directory exists" % i)
            self.assertEqual((csnap, creason), (None, "jump-directory-missing"), "the Current directory name does not exist for this synthetic process")
            self.assertEqual(snap["capabilities"], contract.JUMP_CAP_REQUEST_ID, "REQUEST_ID only")
            self.assertEqual((snap["port"], snap["generation"], snap["token"].hex()), (st["port"], st["generation"], st["token"]), "the Reader sees exactly what the plane published")
            self.assertFalse(snap["port"] in FIXED_PORTS)
            st = self.server.command("cycle", 30.0)
            if st["attempts"] == 1 and st["state"] == "Ready":
                firsts += 1
            else:
                self.fail("[contract:reader-holds-handle] cycle %d: the re-created plane needed %s attempts (state %s): a Reader kept the old mapping" % (i, st["attempts"], st["state"]))
            self.assertNotEqual((st["generation"], st["token"]), previous, "the re-created endpoint is a new one (generation / token)")
            previous = (st["generation"], st["token"])
        self.assertEqual(firsts, cycles, "EVERY re-creation succeeded at the first CreateNew while the Reader polled between the cycles")
        self.assertEqual(src.opens, src.closes, "the Reader opened and closed the same number of times")
        self.assertGreaterEqual(src.opens, cycles * 20, "the Legacy directory was opened (and closed) on every read; the Current name is never there")

    def test_pr7_negative_control_a_retained_handle_blocks_the_recreation(self):
        s0 = self.status()
        raw = managed_app_directory.Win32DirectorySource(contract.DIRECTORY_SIZE)
        name = s0["name"]
        self.assertTrue(raw.open(name), "the test's own old-style reader opens the live mapping")
        try:
            mid = self.server.command("cycle-nowait", 30.0)
            self.assertNotEqual((mid["state"], mid["attempts"]), ("Ready", 1), "the hazard is real: with a retained handle the first CreateNew cannot succeed")
            self.assertEqual(mid["published"], 0, "the plane publishes nothing while its name is held")
        finally:
            raw.close()
        after = self.server.command("await-ready", 30.0)
        self.assertEqual(after["state"], "Ready", "once the retained handle is closed the plane recovers by itself")
        self.assertGreaterEqual(after["attempts"], 2)

    # -- ITR-12 ----------------------------------------------------------------------------------------------------------------------------
    def test_itr12_request_id_only_the_product_client_refuses_and_the_plane_receives_nothing(self):
        self.need_read_directories()
        src = CountingWin32Source()
        sent = []
        client, st = self.client(src, sent)
        before = self.status()
        for text in (STA, LOC):
            self.assertIsNone(client.send(text), "no RequestId for " + text)
        self.assertIsNone(client.send("NORMAL_JUMP:1"))
        self.assertEqual(client.reasons.get("refused:command-unsupported"), 2)
        self.assertEqual(client.reasons.get("refused:unknown-command"), 1)
        self.assertEqual(sent, [], "ZERO datagrams are handed to the send callback (nothing is sent to the plane, nothing to a fixed port)")
        if src.is_open or src.opens != src.closes:
            self.fail("[contract:reader-holds-handle] the client keeps the mapping open after a refused send (opens=%d closes=%d)" % (src.opens, src.closes))
        self.assertEqual(sorted(set(src.requested)), sorted(contract.jump_directory_names(st["bve_pid"])), "only the two known directory names were opened")
        after = self.status()
        self.assertEqual((after["received"], after["outcomes"]), (before["received"], before["outcomes"]), "the plane received no datagram from the Python side")
        self.assertEqual(after["caps_union"], contract.JUMP_CAP_REQUEST_ID, "the plane asked the Directory for REQUEST_ID only")
        with open(os.path.join(ROOT, "current_jump_client.py"), "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("54321", text)
        self.assertNotIn("54322", text)

    # -- re-creation seen from the Reader --------------------------------------------------------------------------------------------------
    def test_recreation_publishes_new_values_and_the_reader_never_uses_the_old_ones(self):
        self.need_read_directories()
        src = CountingWin32Source()
        client, st = self.client(src)
        old = (st["generation"], st["token"], st["port"])
        self.server.command("arm-fault", 10.0)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.assertNotIn(old[2], FIXED_PORTS)
            probe.sendto(b"\x01\x02\x03", ("127.0.0.1", old[2]))      # any datagram: the plane's next read fails -> it withdraws and re-creates
        finally:
            probe.close()
        deadline = time.time() + 15
        seen_new = None
        seen_old_after_new = False
        while time.time() < deadline:
            (name, snap, reason), _current = self.legacy_row(client, st["bve_pid"])
            if src.is_open:
                self.fail("[contract:reader-holds-handle] the Reader still holds the mapping after a read")
            if snap is not None and snap["state"] == (contract.PUBLISHED | contract.READY):
                key = (snap["generation"], snap["token"].hex(), snap["port"])
                if key != old:
                    seen_new = key
                elif seen_new is not None:
                    seen_old_after_new = True
                if seen_new is not None and time.time() > deadline - 14:
                    break
            time.sleep(0.01)
        self.assertIsNotNone(seen_new, "the Reader saw the NEW endpoint of the re-created plane")
        self.assertFalse(seen_old_after_new, "the old generation / token never came back (RC-3)")
        self.assertNotIn(seen_new[2], FIXED_PORTS)
        self.assertEqual(src.opens, src.closes)

    def test_zz_after_the_plane_finished_the_mapping_name_and_the_port_are_free(self):
        s0 = self.status()
        name, port = s0["name"], s0["port"]
        self.assertNotIn(port, FIXED_PORTS)
        final = self.server.command("finish", 30.0)
        self.server.finished = True
        self.assertEqual(final["state"], "Ready", "the last status before the shutdown")
        self.server.proc.wait(timeout=60)
        src = managed_app_directory.Win32DirectorySource(contract.DIRECTORY_SIZE)
        self.assertFalse(src.open(name), "the mapping is gone after the plane's Dispose")
        self.assertFalse(src.is_open)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(("127.0.0.1", port))                       # the plane's port can be bound again: the plane closed its socket
        finally:
            probe.close()

if __name__ == "__main__":
    unittest.main()
