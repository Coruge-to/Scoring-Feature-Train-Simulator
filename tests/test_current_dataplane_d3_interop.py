"""PID-D3: C# sender -> Python receiver interop. The datagrams are produced by the Current sender's own router (Test-CurrentDataPlaneD3.ps1 -GoldenRoot <folder>);
this test, when CURRENT_DATAPLANE_D3_GOLDEN names that folder, proves that the managed receiver accepts them and recovers the exact pre-migration payload."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import telemetry_dataplane_receiver as receiver_module

EXPECTED = {
    "stalist": "STALIST:東京=1=0=0=0=0=15000=0=0",
    "meta": "META:タイトル:路線:車両:作者:コメント",
    "telemetry": "SCENARIO_ID:5,SPEED:12.5,TIME:1000,LOCATION:30",
    "heartbeat": "STATUS:LOADED:PAUSED",
}


class Interop(unittest.TestCase):
    def setUp(self):
        folder = os.environ.get("CURRENT_DATAPLANE_D3_GOLDEN")
        if not folder:
            self.skipTest("CURRENT_DATAPLANE_D3_GOLDEN is not set (run Test-CurrentDataPlaneD3.ps1 -GoldenRoot first)")
        self.folder = folder
        with open(os.path.join(folder, "current_identity.txt"), encoding="ascii") as stream:
            pid, instance, generation, token = stream.read().split()
        self.args = (int(pid), instance, int(generation), bytes.fromhex(token))

    def test_the_receiver_accepts_every_csharp_datagram_with_the_exact_payload(self):
        r = receiver_module.TelemetryDataPlaneReceiver(*self.args)
        for name, text in EXPECTED.items():
            with open(os.path.join(self.folder, "current_%s.bin" % name), "rb") as stream:
                data = stream.read()
            self.assertEqual(r.accept(data), text.encode("utf-8"), name)
        self.assertEqual((r.accepted, r.rejected), (4, 0))

    def test_another_owner_rejects_the_same_datagrams(self):
        pid, instance, generation, token = self.args
        for other in ((pid + 1, instance, generation, token), (pid, instance, generation + 1, token), (pid, instance, generation, bytes(reversed(token)))):
            r = receiver_module.TelemetryDataPlaneReceiver(*other)
            with open(os.path.join(self.folder, "current_telemetry.bin"), "rb") as stream:
                self.assertIsNone(r.accept(stream.read()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
