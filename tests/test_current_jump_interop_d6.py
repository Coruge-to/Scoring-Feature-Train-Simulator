"""PID-D6: the C# <-> Python round trip of the jump command and its completion, with the REAL production code on both sides.

  Python (current_jump_client, the real client) builds the command datagrams  ->  the real C# CurrentJumpEndpoint validator (CurrentJumpEndpoint.cs, compiled by
  Tests\\Test-CurrentJumpD6.ps1 -InteropFolder) accepts or rejects them  ->  for an accepted command the real C# router (CurrentDataPlane.cs) builds the type 5
  JUMP_COMPLETE envelope with the echoed RequestId  ->  Python's real receiver (telemetry_dataplane_receiver) and client match it.

Nothing is installed, no BVE runs, no fixed port is used: the C# side runs in a PowerShell process on the same machine and talks to this test through files.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import current_jump_client as cjc  # noqa: E402
import d6_rig  # noqa: E402
import dataplane_contract as contract  # noqa: E402
import telemetry_dataplane_receiver as receiver_module  # noqa: E402

SCRIPT = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Tests", "Test-CurrentJumpD6.ps1")
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")

BVE_PID = 4242
INSTANCE = "0123456789abcdef0123456789abcdef"
APP_PID = 777
JUMP_GEN = 91
JUMP_TOKEN = bytes(range(9, 25))
TEL_PORT = 40001
TEL_GEN = 5
TEL_TOKEN = bytes(range(50, 66))


@unittest.skipUnless(os.path.isfile(POWERSHELL) and os.path.isfile(SCRIPT), "Windows PowerShell / the C# test script is not available (INCONCLUSIVE)")
class JumpRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = cls.tmp.name
        directory = d6_rig.FakeJumpDirectory(BVE_PID, port=41555, generation=JUMP_GEN, token=JUMP_TOKEN)
        cls.sent = []
        client = cjc.CurrentJumpClient(BVE_PID, INSTANCE, APP_PID, lambda data, port: cls.sent.append(data) or len(data), source=directory)
        cls.client = client
        cls.rid_sta = client.send("JUMP_STA_TIME:3:43000000")
        cls.rid_loc = client.send("JUMP_LOC_TIME:1000.5:36000000")
        good_sta, good_loc = cls.sent
        tampered = bytearray(good_loc)
        tampered[64] ^= 0xFF
        other_sender = contract.encode_envelope(contract.MSG_JUMP_STATION_TIME, BVE_PID, APP_PID + 1, JUMP_GEN, INSTANCE, JUMP_TOKEN, bytes([7] * 16), b"JUMP_STA_TIME:1:2")
        telemetry_type = contract.encode_envelope(contract.MSG_TELEMETRY, BVE_PID, BVE_PID, JUMP_GEN, INSTANCE, JUMP_TOKEN, bytes(16), b"SCENARIO_ID:1")
        cls.commands = [
            ("sta_ok", good_sta, "accept"),
            ("loc_ok", good_loc, "accept"),
            ("loc_duplicate", good_loc, "duplicate-request-id"),
            ("token_tampered", bytes(tampered), "token-mismatch"),
            ("sender_not_the_app", other_sender, "sender-pid-mismatch"),
            ("telemetry_type", telemetry_type, "message-type-not-allowed"),
            ("plain_text", b"JUMP_STA_TIME:3:43000000", "envelope-size"),
        ]
        with open(os.path.join(folder, "identity.txt"), "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join([
                "bve_pid=%d" % BVE_PID, "instance=%s" % INSTANCE, "app_pid=%d" % APP_PID, "jump_generation=%d" % JUMP_GEN, "jump_token=%s" % JUMP_TOKEN.hex(),
                "telemetry_port=%d" % TEL_PORT, "telemetry_generation=%d" % TEL_GEN, "telemetry_token=%s" % TEL_TOKEN.hex()]) + "\n")
        with open(os.path.join(folder, "commands.txt"), "w", encoding="utf-8", newline="\n") as stream:
            for name, data, expected in cls.commands:
                stream.write("%s|%s|%s\n" % (name, data.hex(), expected))
        cls.proc = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SCRIPT, "-RepositoryRoot", ROOT, "-InteropFolder", folder],
                                 capture_output=True, timeout=300)
        cls.output = cls.proc.stdout.decode("utf-8", "replace") + cls.proc.stderr.decode("utf-8", "replace")
        cls.results = {}
        path = os.path.join(folder, "results.txt")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as stream:
                for line in stream.read().splitlines():
                    fields = line.split("|")
                    cls.results[fields[0]] = fields[1:]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_csharp_offline_tests_passed(self):
        self.assertEqual(self.proc.returncode, 0, self.output[-3000:])
        self.assertIn("PID-D6 Current jump offline tests passed.", self.output)

    def test_the_real_csharp_validator_accepts_what_the_python_client_sends_and_rejects_the_rest(self):
        for name, _data, expected in self.commands:
            self.assertIn(name, self.results, name)
            result = self.results[name]
            if expected == "accept":
                self.assertEqual(result[0], "accept", name)
            else:
                self.assertEqual(result, ["reject", expected], name)

    def test_the_accepted_command_text_is_what_python_sent(self):
        self.assertEqual(self.results["sta_ok"][1], "JUMP_STA_TIME:3:43000000")
        self.assertEqual(self.results["loc_ok"][1], "JUMP_LOC_TIME:1000.5:36000000")

    def test_the_completion_built_by_csharp_echoes_the_request_id_and_python_accepts_it(self):
        for name, rid, kind in (("sta_ok", self.rid_sta, "STA"), ("loc_ok", self.rid_loc, "LOC")):
            result = self.results[name]
            self.assertEqual(result[3], str(TEL_PORT), name)                           # addressed to the Telemetry endpoint
            datagram = bytes.fromhex(result[2])
            env = contract.decode_envelope(datagram)
            self.assertEqual(env["message_type"], contract.MSG_JUMP_COMPLETE, name)
            self.assertEqual(env["request_id"], rid, name)                              # the RequestId of the command, byte for byte
            receiver = receiver_module.TelemetryDataPlaneReceiver(BVE_PID, INSTANCE, TEL_GEN, TEL_TOKEN)
            payload = receiver.accept(datagram)                                         # the real managed receiver accepts the C# datagram
            self.assertIsNotNone(payload, (name, receiver.reasons))
            self.assertTrue(payload.decode("utf-8").startswith("JUMP_COMPLETE:" + kind + ":"), name)
            self.assertEqual(receiver.last_request_id, rid, name)

    def test_the_python_client_matches_the_csharp_completion_of_the_outstanding_request_only(self):
        loc = contract.decode_envelope(bytes.fromhex(self.results["loc_ok"][2]))["request_id"]
        sta = contract.decode_envelope(bytes.fromhex(self.results["sta_ok"][2]))["request_id"]
        self.assertEqual(self.client.complete(sta), cjc.R_STALE)                        # superseded by the later command
        self.assertEqual(self.client.complete(loc), cjc.R_OK)
        self.assertEqual(self.client.complete(loc), cjc.R_DUPLICATE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
