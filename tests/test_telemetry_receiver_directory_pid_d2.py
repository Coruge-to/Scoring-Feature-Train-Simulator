import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import dataplane_contract as contract
import telemetry_receiver_directory as directory

I = "0123456789abcdef0123456789abcdef"


class TelemetryDirectorySourceTests(unittest.TestCase):
    def test_name_and_closed_contract(self):
        self.assertEqual(contract.telemetry_name(12345, I), "Local\\TSScoringPlugin.v1.12345.App." + I + ".Telemetry")
        raw = contract.encode_telemetry_directory(12345, 8, contract.CLOSED, "", 0, 0, 0, bytes(16), 4, 0)
        self.assertEqual(contract.decode_telemetry_directory(raw)["state"], contract.CLOSED)

    def test_publisher_has_seqlock_and_fail_closed_primitives(self):
        with open(os.path.join(ROOT, "telemetry_receiver_directory.py"), encoding="utf-8") as stream:
            source = stream.read()
        for token in ("CreateFileMappingW", "MapViewOfFile", "UnmapViewOfFile", "CloseHandle", "_ERROR_ALREADY_EXISTS"):
            self.assertIn(token, source)
        tree = ast.parse(source)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TelemetryDirectoryPublisher")
        methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"publish_ready", "publish_withdrawing", "close", "_publish"} <= methods)
        self.assertIn("data[:_HEAD_OFFSET]", source)
        self.assertLess(source.index("data[:_HEAD_OFFSET]"), source.index("struct.pack(\"<I\", odd)"))
        self.assertLess(source.index("struct.pack(\"<I\", odd)"), source.index("struct.pack(\"<I\", even)"))

    def test_main_keeps_normal_54321_and_managed_caller_uses_zero(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as stream:
            source = stream.read().replace("\r\n", "\n")
        self.assertIn("def __init__(self, udp_port=54321):", source)
        self.assertIn("Overlay(0 if args.owner == \"caller\" else 54321)", source)
        self.assertIn("def _run_normal():\n    app = QApplication(sys.argv)\n    overlay = Overlay()", source)
        self.assertIn("telemetry_directory.publish_withdrawing()", source)
        self.assertLess(source.index("telemetry_directory.publish_withdrawing()"), source.index("_release_overlay(overlay, hud)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
