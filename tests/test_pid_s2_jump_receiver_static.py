"""Phase PID-S2 (RED -> GREEN, static): a MANAGED Current BVE holds no fixed jump port.

PID-R5 managed mode does not bind 54322 (not in the constructor; bound only once the router has decided on the plain Normal mode; closed when Managed)
PID-R6 the plain (Normal) mode keeps its contract: port 54322, the plain command grammar and the `if (normal)` execution rule
PID-R7 the managed jump path (the per-PID Current Jump endpoint) is untouched
The decision logic is a few lines of Class1.cs inside a BveEx plugin that can not run offline, so this is a source-shape test; the live evidence is the
listening-socket check of a real BVE (netstat) in the dual-BVE acceptance.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASS1 = os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "Class1.cs")


def read():
    with open(CLASS1, encoding="utf-8") as handle:
        return handle.read()


def body_of(src, start_marker, end_marker):
    start = src.index(start_marker)
    return src[start:src.index(end_marker, start)]


class PID_R5_ManagedBindsNothing(unittest.TestCase):
    def test_the_constructor_does_not_bind_54322(self):
        src = read()
        ctor = body_of(src, "public ScoringPlugin(PluginBuilder builder)", "private void HeartbeatTimer_Elapsed")
        self.assertNotIn("new UdpClient(54322)", ctor)
        self.assertNotRegex(ctor, r"udpReceiver\s*=")

    def test_exactly_one_bind_site_and_it_is_the_sync_method(self):
        src = read()
        self.assertEqual(src.count("new UdpClient(54322)"), 1)
        sync = body_of(src, "private void SyncJumpReceiver()", "private List<JumpInput> CollectJumpCommands")
        self.assertIn("new UdpClient(54322)", sync)

    def test_the_bind_needs_the_normal_mode_and_the_managed_mode_closes_the_receiver(self):
        sync = body_of(read(), "private void SyncJumpReceiver()", "private List<JumpInput> CollectJumpCommands")
        managed_branch = sync[sync.index("CurrentSenderMode.Managed"):sync.index("CurrentSenderMode.Normal")]
        self.assertIn("udpReceiver.Close()", managed_branch)
        self.assertIn("return;", managed_branch)
        guard = re.search(r"if \(mode != TSScoringPlugin\.DataPlane\.CurrentSenderMode\.Normal \|\| jumpReceiverBindTried \|\| udpReceiver != null\) return;", sync)
        self.assertIsNotNone(guard, "Undetermined / Managed never reach the bind; it is tried once")
        self.assertLess(guard.start(), sync.index("new UdpClient(54322)"))

    def test_the_tick_syncs_the_receiver_before_the_jump_loop_and_not_in_a_pulse(self):
        src = read()
        sync_call = src.index("if (!pulse) SyncJumpReceiver();")
        loop = src.index("if (!pulse && (udpReceiver != null || jumpEndpoint != null))")
        self.assertLess(sync_call, loop)

    def test_dispose_still_closes_the_receiver(self):
        self.assertIn("if (udpReceiver != null) { udpReceiver.Close(); udpReceiver = null; }", read())


class PID_R6_PlainModeKeepsItsContract(unittest.TestCase):
    def test_port_grammar_and_the_normal_only_execution(self):
        src = read()
        self.assertIn("new UdpClient(54322)", src)
        self.assertIn("if (normal) commands.Add(new JumpInput(Encoding.UTF8.GetString(rData), null));", src)
        self.assertIn('msg.StartsWith("JUMP_STA_TIME:")', src)
        self.assertIn('msg.StartsWith("JUMP_LOC_TIME:")', src)

    def test_a_bind_failure_stays_fail_soft_and_logged(self):
        sync = body_of(read(), "private void SyncJumpReceiver()", "private List<JumpInput> CollectJumpCommands")
        self.assertIn("jump-receiver-bind-failed", sync)
        self.assertIn("udpReceiver = null;", sync)


class PID_R7_ManagedJumpPathUntouched(unittest.TestCase):
    def test_the_per_pid_endpoint_is_created_drained_and_disposed(self):
        src = read()
        self.assertIn("CurrentJumpEndpoint.Create(bvePid", src)
        self.assertIn("jumpEndpoint.Drain(validated)", src)
        self.assertIn("jumpEndpoint.Dispose()", src)
        self.assertIn("new JumpInput(c.Text, c.RequestId)", src)


if __name__ == "__main__":
    unittest.main()
