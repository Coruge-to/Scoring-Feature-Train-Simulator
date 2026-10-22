"""PID-D4 Legacy Jump LJX-1 (the minimal execution slice): the managed application against the Legacy jump execution (tests first, RED before the product).

What this file pins from the Python side:
  A  the Python application is NOT changed by LJX-1 (hash pins of the modules that carry the jump contract, and the 10.0 s outstanding timeout);
  B  the scoring start gate: an AVAIL part without `jump` refuses the start (missing-jump), an AVAIL part with `jump` does not;
  C  the command capability: a Legacy Jump Directory with REQUEST_ID only refuses both commands (command-unsupported), one with STA|LOC|REQUEST_ID (0x7) lets both pass;
  D  the real round trip on Windows: a served product plane (real named mapping, real loopback UDP port, the dedicated worker, a fake Legacy host) with the execution
     enabled; the PRODUCT client of this repository reads the real Directory and sends a real datagram; the plane executes on a Tick and sends the type 5 JUMP_COMPLETE to a
     real loopback socket of this test; the product receiver and client accept it. No BVE, no fixed port (54321 / 54322 are never bound or written to).

While the product does not exist (Stage S1) the D tests fail with [contract:serve-script-absent] (an EXPECTED RED).
"""
import hashlib
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
for p in (REPO, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import current_jump_client as cjc  # noqa: E402
import d6_rig  # noqa: E402
import dataplane_contract as contract  # noqa: E402
import managed_app_directory  # noqa: E402
import managed_input  # noqa: E402
import telemetry_contract as tc  # noqa: E402
import telemetry_dataplane_receiver as receiver_module  # noqa: E402

SERVE = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Tests", "Serve-LegacyJumpExecLJX1.ps1")
DEFAULT_DLL = os.path.join(REPO, "TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "out", "TSScoringPlugin.AtsExLegacy.Telemetry.dll")
PRODUCT_DLL = os.environ.get("LEGACYJUMP_LJX1_PRODUCT_DLL") or DEFAULT_DLL
FIXED_PORTS = (54321, 54322)

PYTHON_PINS = {
    "current_jump_client.py": "C2E41A1DFA47274E527A41926D7FEBC52D070A380124BCC05C2536CA0C1F10EC",
    # Phase ST-1B Prep (owner decision G-1; the pin moved, was 6A7B6594...): EVENT_LINE_CAPS gained the one entry "stidx": 24 (the Caller line cap of the STIDX detail event). Nothing of the
    # jump contract or the scoring changed; tests\test_stationindex_supply_st1a.py (class C3) pins the caps and Test-LegacyDataPlaneD4.ps1 (F07) limits the change to that statement.
    "managed_input.py": "060A958CA831382282C282A17D6C38BF72EFC27D8766A325F5A57A7C2A6234A9",
    # Phase ST-1A (two pins moved; were 114DAC75... and F1C9457A...): telemetry_contract.py gained the word STIDX in TOKEN_KEYS["station"] (+ a comment); main.py gained the STIDX
    # intake (one import, four helper methods, three one-line calls). Neither touches the jump contract; tests\test_stationindex_supply_st1a.py (class D) pins the hooks.
    "telemetry_contract.py": "792B5C6E1D6BE9181088B0020120B2A22A98AABD322A0154B44E9F6FCDBE6C71",
    # Phase ST-1B Final Summary Fix (the pin moved again, was EC5B501A...): main.py gained the method _station_index_finish and one guarded call of it in the managed clean-up (the STIDX
    # generation-end summary). Nothing of the jump contract or the scoring changed; tests\test_stationindex_supply_st1a.py (classes F3 / F5) pins the call and its place.
    "main.py": "4D077792FDD5084C35A8253EE4E8FCA383E4CAEC7DB1ACA83F8559B1F99FB813",
    "dataplane_contract.py": "53D23EA683DE8C6344932DEF5D550C0646B3B95ECC5561A3CDAF66F46D9EF27D",
    "scoring_logic.py": "3A790E478C0A2F10DDC9E28E905A399D736E4DF8AA3D9C646AD76B76D1611945",
    "telemetry_dataplane_receiver.py": "7E651F9E2523F035C9A15ED1AF7A23EC8D373BDAB99B7085A8E9BA26521A44E9",
    "managed_app_directory.py": "7B77DA8C4D04B32603AE7BFFAA1A74FCE07253B1BE2084ECB11EBBE5B46DCA8A",
}

STATIONS = [0.0, 1000.0, 2000.0, 3000.0]
SCORING_TOKENS = ["time", "speed", "loc", "station", "door", "handle", "brake_type", "brake_cab", "prates"]


def row(tokens):
    return "SCENARIO_ID:7,%s,SPEED:0.0,TIME:36000000,LOCATION:100.0" % tc.format_avail(tokens)


class A_ThePythonSideIsUnchanged(unittest.TestCase):
    def test_the_modules_that_carry_the_jump_contract_are_byte_identical_to_the_start_of_ljx1(self):
        for name, expected in sorted(PYTHON_PINS.items()):
            with open(os.path.join(REPO, name), "rb") as stream:
                actual = hashlib.sha256(stream.read()).hexdigest().upper()
            self.assertEqual(actual, expected, name)

    def test_the_outstanding_timeout_is_ten_seconds_and_the_legacy_ttl_is_below_it(self):
        self.assertEqual(cjc.OUTSTANDING_TIMEOUT_S, 10.0)
        self.assertLess(5.0, cjc.OUTSTANDING_TIMEOUT_S)


class B_TheScoringStartGate(unittest.TestCase):
    def test_a_row_without_jump_refuses_the_start_with_missing_jump(self):
        line = tc.parse_telemetry(row(SCORING_TOKENS))
        self.assertTrue(line.valid)
        self.assertEqual(managed_input.scoring_input_blockers(line.availability, "Ecb", True), ["missing-jump"])

    def test_a_row_with_jump_does_not(self):
        line = tc.parse_telemetry(row(SCORING_TOKENS + ["jump"]))
        self.assertTrue(line.valid)
        self.assertEqual(managed_input.scoring_input_blockers(line.availability, "Ecb", True), [])

    def test_jump_is_a_known_token_with_its_key_and_its_completion(self):
        self.assertIn("jump", tc.KNOWN_TOKENS)
        self.assertEqual(tc.TOKEN_KEYS["jump"], ("JUMP", "JUMP_COMPLETE"))


class C_TheCommandCapability(unittest.TestCase):
    PID = 4242

    def client(self, caps):
        directory = d6_rig.FakeJumpDirectory(self.PID, name=contract.legacy_jump_name(self.PID), caps=caps)
        sent = []
        client = cjc.CurrentJumpClient(self.PID, "0123456789abcdef0123456789abcdef", 777, lambda data, port: sent.append(data) or len(data), source=directory)
        return client, sent

    def test_request_id_only_refuses_both_commands(self):
        client, sent = self.client(contract.JUMP_CAP_REQUEST_ID)
        self.assertIsNone(client.send("JUMP_STA_TIME:1:36000000"))
        self.assertEqual(client.last_failure, "send-refused:command-unsupported")
        self.assertIsNone(client.send("JUMP_LOC_TIME:1.5:36000000"))
        self.assertEqual(client.last_failure, "send-refused:command-unsupported")
        self.assertEqual(sent, [])

    def test_the_full_capability_set_lets_both_commands_through(self):
        client, sent = self.client(contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME | contract.JUMP_CAP_REQUEST_ID)
        self.assertEqual(contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME | contract.JUMP_CAP_REQUEST_ID, 7)
        self.assertIsNotNone(client.send("JUMP_STA_TIME:1:36000000"))
        self.assertIsNotNone(client.send("JUMP_LOC_TIME:1.5:36000000"))
        self.assertEqual(len(sent), 2)


class CountingWin32Source(object):
    def __init__(self):
        self.real = managed_app_directory.Win32DirectorySource(contract.DIRECTORY_SIZE)

    @property
    def is_open(self):
        return self.real.is_open

    def open(self, name):
        return self.real.open(name)

    def read(self):
        return self.real.read()

    def close(self):
        self.real.close()


class ServedPlane(object):
    """One PowerShell process that serves a product plane (execution enabled or not) on a synthetic BVE PID; commands and replies are files of a control directory."""

    def __init__(self, execution, instance, app_pid, telemetry_port, telemetry_generation, telemetry_token):
        self.dir = tempfile.mkdtemp(prefix="tssl1-")
        self.n = 0
        self.error = None
        self.ready = None
        if not os.path.isfile(SERVE):
            self.error = {"kind": "serve-script-absent", "code": "serve-script-absent", "text": "Serve-LegacyJumpExecLJX1.ps1 does not exist yet"}
            return
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SERVE, "-ControlDir", self.dir, "-ProductDll", PRODUCT_DLL, "-TimeoutSec", "240",
                "-Instance", instance, "-AppPid", str(app_pid), "-TelemetryPort", str(telemetry_port), "-TelemetryGeneration", str(telemetry_generation),
                "-TelemetryTokenHex", telemetry_token.hex()]
        if execution:
            args.append("-Exec")
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
            if self.error is None and self.proc.poll() is None:
                try:
                    self.command("finish", 20.0)
                except Exception:
                    pass
            if self.error is None and self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=20)
                except Exception:
                    self.proc.kill()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


@unittest.skipUnless(os.name == "nt", "needs Windows named mappings")
class D_TheServedPlane(unittest.TestCase):
    INSTANCE = "0123456789abcdef0123456789abcdef"
    APP_PID = 8888
    TEL_GEN = 5
    TEL_TOKEN = bytes(range(50, 66))

    def setUp(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(5.0)
        self.port = self.sock.getsockname()[1]
        self.assertNotIn(self.port, FIXED_PORTS)
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        self.sock.close()

    def serve(self, execution):
        server = ServedPlane(execution, self.INSTANCE, self.APP_PID, self.port, self.TEL_GEN, self.TEL_TOKEN)
        self.servers.append(server)
        if server.error is not None:
            self.fail("[contract:%s] %s" % (server.error.get("code") or server.error.get("kind"), server.error.get("text")))
        return server

    def client_for(self, server):
        pid = server.ready["bve_pid"]
        sent = []

        def send(data, port):
            self.assertNotIn(port, FIXED_PORTS)
            sent.append(data)
            out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                return out.sendto(data, ("127.0.0.1", port))
            finally:
                out.close()

        client = cjc.CurrentJumpClient(pid, self.INSTANCE, self.APP_PID, send, source=CountingWin32Source())
        return client, pid

    def completion(self, pid):
        datagram, _addr = self.sock.recvfrom(65535)
        receiver = receiver_module.TelemetryDataPlaneReceiver(pid, self.INSTANCE, self.TEL_GEN, self.TEL_TOKEN)
        payload = receiver.accept(datagram)
        self.assertIsNotNone(payload, receiver.reasons)
        return receiver, payload.decode("utf-8")

    def test_the_execution_build_publishes_the_full_capability_set(self):
        server = self.serve(True)
        self.assertEqual(server.ready["caps"], 7)
        client, pid = self.client_for(server)
        snapshot, reason = client._read_directory()
        self.assertIsNone(reason)
        self.assertEqual(snapshot["capabilities"], 7)
        self.assertEqual(snapshot["state"] & (contract.PUBLISHED | contract.READY), contract.PUBLISHED | contract.READY)

    def test_the_default_build_still_refuses_the_command(self):
        server = self.serve(False)
        self.assertEqual(server.ready["caps"], 4)
        client, _pid = self.client_for(server)
        self.assertIsNone(client.send("JUMP_STA_TIME:1:36000000"))
        self.assertEqual(client.last_failure, "send-refused:command-unsupported")

    def test_a_station_jump_round_trip_with_the_product_client_and_receiver(self):
        server = self.serve(True)
        client, pid = self.client_for(server)
        rid = client.send("JUMP_STA_TIME:2:36100000")
        self.assertIsNotNone(rid, client.last_failure)
        reply = server.command("tick")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["host"], ["MoveToStation(2)", "SetClockMs(36100000)"])
        receiver, text = self.completion(pid)
        parts = text.split(":")
        self.assertEqual(parts[0:2], ["JUMP_COMPLETE", "STA"])
        self.assertEqual(int(parts[2]), 2)
        self.assertLess(abs(float(parts[3]) - STATIONS[2]), 0.01)
        self.assertEqual(int(parts[4]), 36100000)
        self.assertEqual(int(parts[5]), reply["jump_count"])
        self.assertEqual(receiver.last_request_id, rid)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_OK)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_DUPLICATE)

    def test_a_location_jump_round_trip_with_the_product_client_and_receiver(self):
        server = self.serve(True)
        client, pid = self.client_for(server)
        rid = client.send("JUMP_LOC_TIME:1234.5:36200000")
        self.assertIsNotNone(rid, client.last_failure)
        reply = server.command("tick")
        self.assertEqual(reply["host"], ["MoveToLocation(1234.5,36200000)", "SetClockMs(36200000)"])
        receiver, text = self.completion(pid)
        parts = text.split(":")
        self.assertEqual(parts[0:2], ["JUMP_COMPLETE", "LOC"])
        self.assertEqual(int(parts[2]), -1)
        self.assertLess(abs(float(parts[3]) - 1234.5), 0.01)
        self.assertEqual(receiver.last_request_id, rid)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_OK)

    def test_a_completion_after_the_client_cancelled_is_stale(self):
        server = self.serve(True)
        client, pid = self.client_for(server)
        rid = client.send("JUMP_STA_TIME:1:36000000")
        self.assertIsNotNone(rid, client.last_failure)
        client.cancel("scoring-aborted")
        server.command("tick")
        receiver, _text = self.completion(pid)
        self.assertEqual(receiver.last_request_id, rid)
        self.assertEqual(client.complete(receiver.last_request_id), cjc.R_STALE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
