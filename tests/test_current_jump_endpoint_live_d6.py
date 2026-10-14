"""PID-D6: the REAL Current jump endpoint (C#, named mapping + loopback UDP socket) against the REAL Python client (Win32 mapping reader + a real UDP socket).

The C# endpoint runs in a helper PowerShell process (Tests\\Serve-CurrentJumpEndpointD6.ps1) under an unused synthetic BVE PID, so nothing of a running BVE or of
a running TS Scoring is touched, no fixed port is used and nothing is installed. What this proves beyond tests/test_current_jump_interop_d6.py is the glue
between the two worlds: the 128-byte directory published by C# is read by managed_app_directory.Win32DirectorySource, decoded by dataplane_contract, and the
datagram that the client sends over a real socket is accepted by the real validator behind the published port.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import current_jump_client as cjc  # noqa: E402
import dataplane_contract as contract  # noqa: E402

SCRIPT = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Tests", "Serve-CurrentJumpEndpointD6.ps1")
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
INSTANCE = "0123456789abcdef0123456789abcdef"
APP_PID = 4321


def wait_for(path, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if os.path.isfile(path):
            return True
        time.sleep(0.05)
    return False


@unittest.skipUnless(sys.platform == "win32" and os.path.isfile(POWERSHELL) and os.path.isfile(SCRIPT), "Windows PowerShell / the helper script is not available (INCONCLUSIVE)")
class LiveEndpoint(unittest.TestCase):
    def test_a_real_client_sends_a_command_the_real_endpoint_accepts_and_sees_the_endpoint_close(self):
        pid = 1900100000 + (os.getpid() & 0xFFFF)
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.Popen([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SCRIPT, "-Folder", folder, "-BvePid", str(pid),
                                     "-Instance", INSTANCE, "-AppPid", str(APP_PID), "-Seconds", "40", "-RepositoryRoot", ROOT],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000)
            client = None
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.assertTrue(wait_for(os.path.join(folder, "endpoint.txt"), 60), "the C# endpoint did not start: %r" % (proc.poll(),))
                with open(os.path.join(folder, "endpoint.txt"), encoding="utf-8") as stream:
                    published_port = int(stream.read().strip().split("=")[1])

                lines = []
                client = cjc.CurrentJumpClient(pid, INSTANCE, APP_PID, lambda data, port: sock.sendto(data, ("127.0.0.1", port)), log=lines.append)
                # first two datagrams that must be dropped by the real endpoint: the pre-migration plain text and an envelope with a wrong endpoint token
                sock.sendto(b"JUMP_STA_TIME:2:36000000", ("127.0.0.1", published_port))
                snapshot, _reason = client._read_directory()
                self.assertEqual((snapshot["port"], snapshot["capabilities"]), (published_port, 7))
                sock.sendto(contract.encode_envelope(contract.MSG_JUMP_STATION_TIME, pid, APP_PID, snapshot["generation"], INSTANCE, bytes(range(1, 17)),
                                                     bytes([9] * 16), b"JUMP_STA_TIME:2:36000000"), ("127.0.0.1", published_port))
                rid = client.send("JUMP_STA_TIME:2:36000000")                          # real Win32 mapping read + real UDP datagram
                self.assertIsNotNone(rid, client.last_failure)
                self.assertTrue(wait_for(os.path.join(folder, "served.txt"), 20), "the endpoint did not accept the command")
                with open(os.path.join(folder, "served.txt"), encoding="utf-8") as stream:
                    served = stream.read().splitlines()
                self.assertEqual(served, ["JUMP_STA_TIME:2:36000000|" + rid.hex()])
                self.assertNotEqual(published_port, 54322)

                # the endpoint goes away: the client keeps its handle and sees the CLOSED snapshot, the request is cancelled, no retry
                open(os.path.join(folder, "stop.flag"), "w").close()
                self.assertTrue(wait_for(os.path.join(folder, "done.txt"), 30), "the endpoint did not close")
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.bind(("127.0.0.1", published_port))                           # the endpoint's socket is released
                except OSError:
                    self.fail("the endpoint's port was not released")
                finally:
                    probe.close()
                client._next_watch = 0.0
                client.poll()
                self.assertFalse(client.has_outstanding)
                self.assertEqual(client.last_failure, "endpoint-withdrawn")
                self.assertEqual(client.complete(rid), cjc.R_STALE)
                self.assertIsNone(client.send("JUMP_STA_TIME:2:36000000"))
                self.assertIn(client.last_failure, ("send-refused:jump-endpoint-not-usable", "send-refused:jump-directory-missing"))
            finally:
                try:
                    open(os.path.join(folder, "stop.flag"), "w").close()
                except OSError:
                    pass
                sock.close()
                if client is not None:
                    client.close()
                try:
                    proc.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
            self.assertTrue(os.path.isfile(os.path.join(folder, "served-summary.txt")))
            with open(os.path.join(folder, "served-summary.txt"), encoding="utf-8") as stream:
                self.assertEqual(stream.read().strip(), "accepted=1 rejected=2")        # the plain text and the wrong-token envelope were dropped


if __name__ == "__main__":
    unittest.main(verbosity=2)
