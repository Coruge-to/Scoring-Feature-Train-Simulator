"""PID-D4 Slice 1: Legacy C# sender -> Python receiver interop. The datagrams are produced by the REAL Legacy telemetry sender (the built DLL driven through the fake Legacy
API by Test-LegacyDataPlaneD4.ps1 -GoldenRoot <folder>); this test, when LEGACY_DATAPLANE_D4_GOLDEN names that folder, proves that the managed receiver accepts every one of
them with the exact pre-migration text and that the strict telemetry gate takes the lines (the HUD chain itself is checked by legacy_dataplane_chain_check.py)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import dataplane_contract as contract  # noqa: E402
import telemetry_dataplane_receiver as receiver_module  # noqa: E402
import telemetry_gate  # noqa: E402

TYPE_PREFIX = {1: "SCENARIO_ID:", 2: "STATUS:", 3: "STALIST:", 4: "META:"}


class Interop(unittest.TestCase):
    def setUp(self):
        folder = os.environ.get("LEGACY_DATAPLANE_D4_GOLDEN")
        if not folder:
            self.skipTest("LEGACY_DATAPLANE_D4_GOLDEN is not set (run Test-LegacyDataPlaneD4.ps1 -GoldenRoot first)")
        with open(os.path.join(folder, "legacy_identity.txt"), encoding="ascii") as stream:
            pid, instance, generation, token = stream.read().split()
        self.args = (int(pid), instance, int(generation), bytes.fromhex(token))
        self.datagrams = []
        with open(os.path.join(folder, "legacy_manifest.txt"), encoding="ascii") as stream:
            for line in stream.read().split("\n"):
                if line.strip():
                    index, kind = line.split()
                    with open(os.path.join(folder, "legacy_%s.bin" % index), "rb") as data:
                        self.datagrams.append((int(kind), data.read()))

    def test_the_receiver_accepts_every_legacy_datagram_with_the_exact_text(self):
        receiver = receiver_module.TelemetryDataPlaneReceiver(*self.args)
        texts = []
        for kind, data in self.datagrams:
            payload = receiver.accept(data)
            self.assertIsNotNone(payload, "datagram of type %d was rejected: %r" % (kind, receiver.reasons))
            text = payload.decode("utf-8")
            self.assertTrue(text.startswith(TYPE_PREFIX[kind]), (kind, text[:30]))
            texts.append(text)
        self.assertEqual((receiver.accepted, receiver.rejected), (len(self.datagrams), 0))
        self.assertEqual({k for k, _ in self.datagrams}, {1, 2, 3, 4})
        self.assertTrue(any(t == "STATUS:LOADED:PAUSED" for t in texts))

    def test_every_envelope_is_a_valid_v1_envelope_with_a_zero_request_id(self):
        pid = self.args[0]
        for kind, data in self.datagrams:
            envelope = contract.decode_envelope(data)
            self.assertEqual(envelope["message_type"], kind)
            self.assertEqual((envelope["bve_pid"], envelope["sender_pid"]), (pid, pid))
            self.assertFalse(any(envelope["request_id"]))

    def test_another_owner_rejects_the_same_datagrams(self):
        pid, instance, generation, token = self.args
        others = ((pid + 1, instance, generation, token), (pid, instance, generation + 1, token), (pid, instance, generation, bytes(reversed(token))),
                  (pid, "fedcba0987abcdeffedcba0987abcdef", generation, token))
        for other in others:
            receiver = receiver_module.TelemetryDataPlaneReceiver(*other)
            for _kind, data in self.datagrams:
                self.assertIsNone(receiver.accept(data))

    def test_the_plain_text_of_the_same_datagrams_is_never_accepted_by_the_managed_receiver(self):
        receiver = receiver_module.TelemetryDataPlaneReceiver(*self.args)
        for _kind, data in self.datagrams:
            plain = contract.decode_envelope(data)["payload"]
            self.assertIsNone(receiver.accept(plain))
        self.assertEqual(receiver.accepted, 0)

    def test_the_strict_gate_takes_the_legacy_lines(self):
        receiver = receiver_module.TelemetryDataPlaneReceiver(*self.args)
        gate = telemetry_gate.TelemetryGate(strict=True)
        gate.on_generation(1)
        taken = 0
        for kind, data in self.datagrams:
            text = receiver.accept(data).decode("utf-8")
            if kind == 1:
                self.assertTrue(gate.accept(text), text)
                taken += 1
        self.assertGreaterEqual(taken, 3)
        self.assertTrue(gate.ready)


if __name__ == "__main__":
    unittest.main(verbosity=2)
