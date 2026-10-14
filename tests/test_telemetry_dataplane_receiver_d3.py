"""PID-D3: the managed Telemetry receiver's ownership validation, the capability publication and the Overlay's fail-closed unwrap.

Standard library only (the Overlay part imports main.py, which needs PyQt6 like the other Overlay tests; it never creates a widget or a socket)."""
import ctypes
import os
import re
import struct
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import dataplane_contract as contract
import telemetry_dataplane_receiver as receiver_module
import telemetry_receiver_directory as directory

PID = 12345
INSTANCE = "0123456789abcdef0123456789abcdef"
OTHER_INSTANCE = "fedcba9876543210fedcba9876543210"
TOKEN = bytes(range(1, 17))
OTHER_TOKEN = bytes(range(2, 18))
ZERO = bytes(16)
REQ = bytes(range(16, 32))
GEN = 7

TELEMETRY = "SCENARIO_ID:5,SPEED:12.5,TIME:1000,LOCATION:30".encode("utf-8")
STALIST = "STALIST:東京=1=0=0=0=0=15000=0=0".encode("utf-8")
META = "META:タイトル:路線:車両:作者:コメント".encode("utf-8")
HEARTBEAT = b"STATUS:LOADED:RUNNING"


def env(mtype=1, payload=TELEMETRY, bve_pid=PID, sender=PID, gen=GEN, instance=INSTANCE, token=TOKEN, request_id=ZERO):
    return contract.encode_envelope(mtype, bve_pid, sender, gen, instance, token, request_id, payload)


def make(log=None):
    return receiver_module.TelemetryDataPlaneReceiver(PID, INSTANCE, GEN, TOKEN, log)


class AcceptTests(unittest.TestCase):
    def test_the_four_message_types_give_back_the_exact_payload_bytes(self):
        r = make()
        for mtype, payload in ((1, TELEMETRY), (2, HEARTBEAT), (3, STALIST), (4, META)):
            self.assertEqual(r.accept(env(mtype, payload)), payload)
        self.assertEqual((r.accepted, r.rejected), (4, 0))

    def test_multibyte_payload_survives_byte_for_byte(self):
        r = make()
        out = r.accept(env(4, META))
        self.assertEqual(out.decode("utf-8"), "META:タイトル:路線:車両:作者:コメント")

    def test_maximum_datagram_is_accepted_and_one_more_byte_cannot_even_be_built(self):
        r = make()
        payload = b"SCENARIO_ID:" + b"a" * (65411 - 12)
        datagram = env(1, payload)
        self.assertEqual(len(datagram), 65507)
        self.assertEqual(r.accept(datagram), payload)
        with self.assertRaises(ValueError):
            env(1, payload + b"a")

    def test_first_accept_is_logged_once_and_never_per_packet(self):
        lines = []
        r = make(lines.append)
        for _ in range(50):
            r.accept(env())
        self.assertEqual(len(lines), 1)
        self.assertIn("event=first-accept", lines[0])
        self.assertNotIn("SCENARIO_ID", lines[0])


class RejectTests(unittest.TestCase):
    def reject(self, datagram, reason):
        lines = []
        r = make(lines.append)
        before = (r.accepted,)
        self.assertIsNone(r.accept(datagram))
        self.assertEqual(r.reasons, {reason: 1}, r.reasons)
        self.assertEqual((r.accepted,), before)
        self.assertEqual(len(lines), 1)
        self.assertNotIn(TOKEN.hex(), lines[0])
        return r

    def test_structure(self):
        good = bytearray(env())
        x = bytearray(good); x[0] = 0
        self.reject(bytes(x), "magic")
        x = bytearray(good); x[4] = 2
        self.reject(bytes(x), "version")
        x = bytearray(good); x[6] = 95
        self.reject(bytes(x), "header-size")
        x = bytearray(good); x[12] = 1
        self.reject(bytes(x), "flags")
        self.reject(bytes(good[:95]), "size")
        self.reject(bytes(good[:-1]), "payload-length")
        self.reject(bytes(good) + b"x", "payload-length")
        x = bytearray(good); x[-1] = 0xFF
        self.reject(bytes(x), "utf8")
        x = bytearray(good); x[32] = 0xFF
        self.reject(bytes(x), "malformed")

    def test_identity_matrix_leaves_the_state_unchanged(self):
        self.reject(env(bve_pid=PID + 1, sender=PID + 1), "bve-pid-mismatch")
        self.reject(env(instance=OTHER_INSTANCE), "app-instance-mismatch")
        self.reject(env(gen=GEN + 1), "generation-mismatch")
        self.reject(env(token=OTHER_TOKEN), "token-mismatch")
        wrong_byte = bytearray(TOKEN); wrong_byte[15] ^= 1
        self.reject(env(token=bytes(wrong_byte)), "token-mismatch")
        self.reject(env(sender=PID + 1), "sender-pid-mismatch")

    def test_message_type_and_request_id_rules(self):
        # PID-D6: type 5 JUMP_COMPLETE is accepted now (tests/test_jump_complete_d6.py); the jump COMMANDS never belong to this receiver
        self.reject(env(0x100, b"JUMP_STA_TIME:1:2", sender=PID, request_id=REQ), "message-type-not-allowed")
        self.reject(env(0x101, b"JUMP_LOC_TIME:1:2", request_id=REQ), "message-type-not-allowed")
        self.reject(env(1, TELEMETRY, request_id=REQ), "request-id")
        self.reject(env(5, b"JUMP_COMPLETE:STA:1:0.0:0:0", request_id=ZERO), "request-id")
        x = bytearray(env()); x[8] = 0x77
        self.reject(bytes(x), "message-type-unknown")

    def test_payload_grammar_pairing(self):
        self.reject(env(1, STALIST), "payload-grammar")
        self.reject(env(2, TELEMETRY), "payload-grammar")
        self.reject(env(3, META), "payload-grammar")
        self.reject(env(4, HEARTBEAT), "payload-grammar")

    def test_a_plain_legacy_datagram_is_not_an_envelope(self):
        self.reject(TELEMETRY, "size")                                 # a short plain line is shorter than the 96-byte header
        self.reject(TELEMETRY + b",PAD:" + b"x" * 100, "magic")        # a long plain line has no envelope magic
        self.reject(b"x" * 10, "size")

    def test_closed_receiver_accepts_nothing(self):
        r = make()
        self.assertEqual(r.accept(env()), TELEMETRY)
        r.stop()
        self.assertIsNone(r.accept(env()))
        self.assertEqual(r.reasons, {"receiver-closed": 1})

    def test_summary_is_one_aggregate_line(self):
        r = make()
        r.accept(env()); r.accept(env(gen=99)); r.accept(env(gen=99))
        s = r.summary()
        self.assertIn("accepted=1", s)
        self.assertIn("rejected=2", s)
        self.assertIn("generation-mismatch:2", s)
        self.assertNotIn("\n", s)

    def test_constructor_validates_its_identity(self):
        for args in ((0, INSTANCE, GEN, TOKEN), (PID, "XYZ", GEN, TOKEN), (PID, INSTANCE, 0, TOKEN), (PID, INSTANCE, GEN, ZERO), (PID, INSTANCE, GEN, b"short")):
            with self.assertRaises(ValueError):
                receiver_module.TelemetryDataPlaneReceiver(*args)

    def test_two_owners_never_accept_each_others_stream(self):
        a = receiver_module.TelemetryDataPlaneReceiver(100, INSTANCE, 1, TOKEN)
        b = receiver_module.TelemetryDataPlaneReceiver(200, OTHER_INSTANCE, 1, OTHER_TOKEN)
        for _ in range(200):
            self.assertIsNotNone(a.accept(env(bve_pid=100, sender=100, gen=1, instance=INSTANCE, token=TOKEN)))
            self.assertIsNone(b.accept(env(bve_pid=100, sender=100, gen=1, instance=INSTANCE, token=TOKEN)))
            self.assertIsNotNone(b.accept(env(bve_pid=200, sender=200, gen=1, instance=OTHER_INSTANCE, token=OTHER_TOKEN)))
            self.assertIsNone(a.accept(env(bve_pid=200, sender=200, gen=1, instance=OTHER_INSTANCE, token=OTHER_TOKEN)))
        self.assertEqual((a.accepted, b.accepted, a.rejected, b.rejected), (200, 200, 200, 200))

    def test_same_pid_stale_instance_and_stale_token_are_rejected_even_on_the_new_port(self):
        new = receiver_module.TelemetryDataPlaneReceiver(PID, OTHER_INSTANCE, 1, OTHER_TOKEN)
        self.assertIsNone(new.accept(env(instance=INSTANCE, token=TOKEN, gen=1)))
        self.assertIsNone(new.accept(env(instance=OTHER_INSTANCE, token=TOKEN, gen=1)))
        self.assertIsNotNone(new.accept(env(instance=OTHER_INSTANCE, token=OTHER_TOKEN, gen=1)))


class FakeKernel32(object):
    """Just enough of kernel32 for TelemetryDirectoryPublisher: the 'mapping' is a ctypes buffer."""
    def __init__(self):
        self.buffer = ctypes.create_string_buffer(128)
        self.closed = []

    def CreateFileMappingW(self, *args):
        return 1

    def MapViewOfFile(self, *args):
        return ctypes.addressof(self.buffer)

    def UnmapViewOfFile(self, view):
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def snapshot(self):
        return contract.decode_telemetry_directory(bytes(self.buffer.raw))


class CapabilityTests(unittest.TestCase):
    def test_constants_are_the_contract_values_and_the_published_value_is_composed(self):
        self.assertEqual((contract.CAP_ENVELOPE_V1, contract.CAP_LEGACY_TEXT_PAYLOAD, contract.CAP_JUMP_COMPLETE_V1), (1, 2, 4))
        self.assertEqual(contract.TELEMETRY_KNOWN_CAPS, 7)
        self.assertEqual(contract.TELEMETRY_PUBLISHED_CAPS, contract.CAP_ENVELOPE_V1 | contract.CAP_LEGACY_TEXT_PAYLOAD | contract.CAP_JUMP_COMPLETE_V1)   # PID-D6
        self.assertTrue(contract.TELEMETRY_PUBLISHED_CAPS & contract.CAP_JUMP_COMPLETE_V1)

    def test_python_and_csharp_constants_agree(self):
        with open(os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "CurrentDataPlane.cs"), encoding="utf-8") as stream:
            source = stream.read()
        found = dict((m.group(1), int(m.group(2), 16)) for m in re.finditer(r"internal const UInt32 (EnvelopeV1|LegacyTextPayload|JumpCompleteV1) = 0x([0-9A-Fa-f]+)U;", source))
        self.assertEqual(found, {"EnvelopeV1": contract.CAP_ENVELOPE_V1, "LegacyTextPayload": contract.CAP_LEGACY_TEXT_PAYLOAD, "JumpCompleteV1": contract.CAP_JUMP_COMPLETE_V1})
        types_found = dict((m.group(1), int(m.group(2))) for m in re.finditer(r"internal const UInt32 (Telemetry|Heartbeat|StationList|Metadata) = (\d+)U;", source))
        self.assertEqual(types_found, {"Telemetry": contract.MSG_TELEMETRY, "Heartbeat": contract.MSG_HEARTBEAT, "StationList": contract.MSG_STATION_LIST, "Metadata": contract.MSG_METADATA})

    def test_literal_0x3_is_not_repeated_in_product_code(self):
        for name in ("telemetry_receiver_directory.py", "main.py", "telemetry_dataplane_receiver.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as stream:
                text = stream.read()
            self.assertIsNone(re.search(r"capabilities\s*=\s*(0x3|3)\b", text), name)

    def test_ready_snapshot_carries_the_composed_capabilities_and_closed_carries_none(self):
        k = FakeKernel32()
        p = directory.TelemetryDirectoryPublisher(PID, INSTANCE, 777, 40100, kernel32=k)
        composed = contract.CAP_ENVELOPE_V1 | contract.CAP_LEGACY_TEXT_PAYLOAD | contract.CAP_JUMP_COMPLETE_V1
        self.assertEqual(k.snapshot()["capabilities"], composed)               # PUBLISHED already advertises the capabilities
        p.publish_ready()
        snap = k.snapshot()
        self.assertEqual(snap["state"], contract.PUBLISHED | contract.READY)
        self.assertEqual(snap["capabilities"], composed)
        self.assertEqual((snap["generation"], snap["token"]), (p.generation, p.token))
        p.publish_withdrawing()
        self.assertEqual(k.snapshot()["capabilities"], composed)
        p.close()
        closed = k.snapshot()
        self.assertEqual((closed["state"], closed["capabilities"], closed["port"]), (contract.CLOSED, 0, 0))

    def test_unsupported_capabilities_are_refused_at_publication_and_at_decode(self):
        with self.assertRaisesRegex(ValueError, "capabilities"):
            directory.TelemetryDirectoryPublisher(PID, INSTANCE, 777, 40100, kernel32=FakeKernel32(), capabilities=8)
        raw = bytearray(contract.encode_telemetry_directory(PID, 2, 3, INSTANCE, 777, 40100, 7, TOKEN, 1, 3))
        struct.pack_into("<I", raw, 96, 0x8)
        with self.assertRaisesRegex(ValueError, "capabilities"):
            contract.decode_telemetry_directory(bytes(raw))

    def test_receiver_identity_comes_from_the_published_endpoint(self):
        k = FakeKernel32()
        p = directory.TelemetryDirectoryPublisher(PID, INSTANCE, 777, 40100, kernel32=k)
        p.publish_ready()
        snap = k.snapshot()
        r = receiver_module.TelemetryDataPlaneReceiver(PID, INSTANCE, snap["generation"], snap["token"])
        good = contract.encode_envelope(1, PID, PID, snap["generation"], INSTANCE, snap["token"], ZERO, TELEMETRY)
        self.assertEqual(r.accept(good), TELEMETRY)


class OverlayUnwrapTests(unittest.TestCase):
    """main.Overlay._unwrap_dataplane / the run_managed wiring, without a widget or a socket."""

    @classmethod
    def setUpClass(cls):
        try:
            import main
        except Exception as exc:                      # PyQt6 / pywin32 / keyboard not importable here
            raise unittest.SkipTest("main.py not importable: %s" % type(exc).__name__)
        cls.main = main

    def stub(self, rec=None, strict=False):
        return types.SimpleNamespace(dataplane_receiver=rec, dataplane_strict=strict)

    def test_normal_mode_passes_the_plain_datagram_through_untouched(self):
        unwrap = self.main.Overlay._unwrap_dataplane
        self.assertIs(unwrap(self.stub(), TELEMETRY), TELEMETRY)

    def test_managed_without_a_receiver_rejects_everything(self):
        unwrap = self.main.Overlay._unwrap_dataplane
        self.assertIsNone(unwrap(self.stub(strict=True), TELEMETRY))
        self.assertIsNone(unwrap(self.stub(strict=True), env()))

    def test_managed_with_a_receiver_hands_on_only_the_unwrapped_owned_payload(self):
        unwrap = self.main.Overlay._unwrap_dataplane
        s = self.stub(make(), strict=True)
        self.assertEqual(unwrap(s, env()), TELEMETRY)
        self.assertIsNone(unwrap(s, TELEMETRY))                       # fixed-port style plaintext is never a managed success path
        self.assertIsNone(unwrap(s, env(token=OTHER_TOKEN)))

    def test_run_managed_wiring_order(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as stream:
            source = stream.read()
        body = source[source.index("def run_managed"):source.index("def _run_normal")]
        strict = body.index("overlay.dataplane_strict = True")
        publisher = body.index("telemetry_receiver_directory.TelemetryDirectoryPublisher(")
        attach = body.index("overlay.dataplane_receiver = dataplane_receiver")
        ready = body.index("telemetry_directory.publish_ready()")
        stop = body.index("dataplane_receiver.stop()")
        release = body.index("_release_overlay(overlay, hud)")
        withdraw = body.index("telemetry_directory.publish_withdrawing()")
        self.assertLess(strict, publisher)
        self.assertLess(publisher, attach)
        self.assertLess(attach, ready)
        self.assertLess(withdraw, stop)
        self.assertLess(stop, release)
        self.assertIn('args.owner == "caller"', body[max(0, strict - 120):strict + 60])

    def test_read_udp_data_unwraps_before_the_utf8_decode_and_normal_ports_are_unchanged(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as stream:
            source = stream.read().replace("\r\n", "\n")
        body = source[source.index("    def read_udp_data"):source.index("    def _unwrap_dataplane")]
        self.assertLess(body.index("self._unwrap_dataplane(datagram)"), body.index("datagram.decode('utf-8')"))
        self.assertIn("def __init__(self, udp_port=54321):", source)
        self.assertIn("Overlay(0 if args.owner == \"caller\" else 54321)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
