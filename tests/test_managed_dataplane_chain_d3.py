"""PID-D3: the REAL main.py --managed --owner caller on its Directory-published loopback port.

The Caller's part is played by this test (state block, AppDirectory, Stop), the BVE window by tests\\fake_bve_window.py, the Current sender's part by
tests\\dataplane_feed.py. Proved here: the application advertises ENVELOPE_V1 + LEGACY_TEXT_PAYLOAD on a port of its own (never 54321), accepts exactly the
Envelope v1 datagrams of its owner and endpoint, rejects everything else (plain text, another token, another BVE PID, a jump completion) and reports the
counts once, at the end. Skipped when PyQt6 is missing; it neither binds nor needs UDP 54321."""
import os
import pathlib
import re
import subprocess
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
for path in (str(ROOT), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import dataplane_contract as contract
import dataplane_feed as feed
import managed_app_directory as directory
from app_directory_fixture import AppDirectoryFixture
import test_managed_hud_e4 as E4


@unittest.skipUnless(os.name == "nt" and E4.HAS_QT, "Windows and PyQt6 are required")
class ManagedDataPlaneChain(unittest.TestCase):
    def test_real_main_py_accepts_only_owned_envelopes_on_its_own_port(self):
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)
        env["PYTHONIOENCODING"] = "utf-8"
        window = subprocess.Popen([sys.executable, str(TESTS / "fake_bve_window.py"), "60"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, cwd=str(ROOT), env=env, creationflags=0x08000000)
        proc = None
        owner = fixture = reader = None
        try:
            ready_line = window.stdout.readline().decode("utf-8", "replace")
            self.assertIn("READY pid=", ready_line)
            bve_pid = int(ready_line.split("pid=")[1].split()[0])
            args = E4.args_for(pid=bve_pid, owner="caller")
            owner = E4.Owner(args)
            owner.block.publish(session=False, driving=False, generation=0)
            fixture = AppDirectoryFixture(args.bve_pid, args.instance)
            reader = directory.DirectoryReader(args.bve_pid)
            self.assertTrue(reader.open(), reader.open_failure)
            argv = [sys.executable, str(ROOT / "main.py"), "--managed", "--owner", "caller", "--bve-pid", str(args.bve_pid), "--instance", args.instance]
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT), env=env, creationflags=0x08000000)
            fixture.publish_process_started(proc.pid)
            self.assertTrue(E4.wait_until(owner.ready, 30), "main.py did not publish AppReady")
            fixture.publish_ready_accepted()

            snap = feed.wait_endpoint(bve_pid, args.instance, 10)
            self.assertIsNotNone(snap, "the Telemetry Directory did not become READY")
            self.assertEqual(snap["capabilities"], contract.CAP_ENVELOPE_V1 | contract.CAP_LEGACY_TEXT_PAYLOAD | contract.CAP_JUMP_COMPLETE_V1)   # PID-D6: + JUMP_COMPLETE_V1
            self.assertEqual((snap["bve_pid"], snap["app_instance"], snap["app_pid"]), (bve_pid, args.instance, proc.pid))
            port = snap["port"]
            self.assertNotEqual(port, 54321)
            self.assertFalse(feed.udp_port_is_free(port), "the application does not hold its published port")

            good = [
                feed.envelope_for(snap, contract.MSG_TELEMETRY, "SCENARIO_ID:1,SPEED:0,TIME:0,LOCATION:0"),
                feed.envelope_for(snap, contract.MSG_HEARTBEAT, "STATUS:LOADED:RUNNING"),
                feed.envelope_for(snap, contract.MSG_STATION_LIST, "STALIST:" + "東京" + "=1=0=0=0=0=15000=0=0"),
            ]
            bad_token = bytearray(snap["token"]); bad_token[0] ^= 0xFF
            bad = [
                b"SCENARIO_ID:1,SPEED:0,TIME:0,LOCATION:0",                                                   # the pre-migration plain line: never a managed success path
                feed.envelope_for(snap, contract.MSG_TELEMETRY, "SCENARIO_ID:2", token=bytes(bad_token)),     # another endpoint token
                feed.envelope_for(snap, contract.MSG_TELEMETRY, "SCENARIO_ID:3", bve_pid=bve_pid + 1),        # another BVE process
                feed.envelope_for(snap, contract.MSG_JUMP_STATION_TIME, "JUMP_STA_TIME:1:2", request_id=bytes(range(1, 17))),          # a jump COMMAND never belongs to the Telemetry receiver
            ]
            for datagram in good + bad:
                feed.send(port, datagram)
                time.sleep(0.02)
            time.sleep(1.0)

            owner.sync.set_event(owner.stop)
            code = proc.wait(10)
            stderr = proc.stderr.read().decode("utf-8", "replace")
            self.assertEqual(code, 0, stderr)
            summary = [line for line in stderr.splitlines() if "[DATAPLANE] event=summary" in line]
            self.assertEqual(len(summary), 1, stderr)
            self.assertRegex(summary[0], r"accepted=3 rejected=4")
            for reason in ("size", "token-mismatch", "bve-pid-mismatch", "message-type-not-allowed"):
                self.assertIn(reason + ":1", summary[0])
            self.assertEqual(len(re.findall(r"\[DATAPLANE\] event=first-accept", stderr)), 1)
            self.assertNotIn(snap["token"].hex(), stderr)
            fixture.publish_withdrawing()
            fixture.publish_closed()
            self.assertTrue(E4.wait_until(lambda: feed.udp_port_is_free(port), 10), "the Directory port was not released")
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill(); proc.communicate(timeout=10)
            if reader is not None: reader.close()
            if fixture is not None: fixture.close()
            if owner is not None: owner.close()
            if window.poll() is None:
                window.kill(); window.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
