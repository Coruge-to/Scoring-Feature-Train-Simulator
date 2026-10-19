"""PID-D6 (necessary minimum slice) - the managed JUMP_COMPLETE with a RequestId.

Root cause being closed (audit 2026-10-14): in managed mode the JUMP_COMPLETE never reached Python, so the official-jump state set by the scoring start
(is_official_jumping, then jump_lock) was never released and every scoring feature behind it stayed dead (basic brake, running time, stop position, departure,
door-open arrival, the scoring end, the result display, the F8 auto release).

    A  current_jump_client: the RequestId (generation, carriage), the match / duplicate / stale / unknown / invalid answers, the cancel rules, the timeout
    B  telemetry_dataplane_receiver: the type 5 envelope (and what is still refused)
    C  the real Overlay (tests/d6_rig.py, the production wiring of run_managed): command with a RequestId, release only by the matching completion, the whole
       scoring run A -> B up to the result display, the lost completion is detected, the F8 auto release, the D3 chain and the normal mode are unchanged
    D  static guards: no fixed 54321 / 54322 in the managed path, Current / Legacy separation, the shutdown order
"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import current_jump_client as cjc  # noqa: E402
import dataplane_contract as contract  # noqa: E402
import telemetry_dataplane_receiver as receiver_module  # noqa: E402

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

PID = 880001
INSTANCE = "0123456789abcdef0123456789abcdef"
APP_PID = 4711
JUMP_TOKEN = bytes(range(101, 117))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as stream:
        return stream.read()


class FakeDirectory(object):
    """The read-only mapping source of the jump client (a byte buffer the test edits).

    PID-D4 / Legacy Jump 2A-alpha (Stage S4): it is NAME AWARE. It exists under exactly one Directory name (default: the Current name of PID) and answers every other name as
    absent, so a client that looks at the Current AND the Legacy name finds only the Directory that was published under its own name. The old fake said True to every name,
    which now reads as two usable Directories (jump-host-ambiguous). Several Directories behind one source: FakeDirectories below."""

    def __init__(self, port=41000, generation=11, token=JUMP_TOKEN, caps=7, name=None):
        self.name = contract.jump_name(PID) if name is None else name
        self.requested = []
        self.port, self.generation, self.token, self.caps = port, generation, token, caps
        self.state = contract.PUBLISHED | contract.READY
        self.seq = 0
        self.change = 0
        self.present = True
        self.opened = False
        self.broken = False
        self.publish()

    def publish(self, state=None, **kw):
        if state is not None:
            self.state = state
        for k, v in kw.items():
            setattr(self, k, v)
        self.seq += 2
        self.change += 1
        if self.state == contract.CLOSED:
            self.block = contract.encode_jump_directory(PID, self.seq, self.state, 0, 0, 0, bytes(16), self.change, 0)
        else:
            self.block = contract.encode_jump_directory(PID, self.seq, self.state, PID, self.port, self.generation, self.token, self.change, self.caps)

    def withdraw(self):
        self.publish(contract.PUBLISHED | contract.READY | contract.WITHDRAWING)

    def make_invalid(self):
        """The mapping under this name exists but holds a block that is not a Jump Directory (a bad magic)."""
        self.block = bytes(len(self.block))

    def open(self, name):
        self.requested.append(name)
        if name != self.name or not self.present:
            self.opened = False
            return False
        self.opened = True
        return True

    def read(self):
        if self.broken:
            raise OSError("mapping gone")
        return self.block if self.opened else None

    def close(self):
        self.opened = False


class FakeDirectories(object):
    """One read-only source in front of several name-aware FakeDirectory objects: open(name) selects the one published under that name; an unknown name is absent."""

    def __init__(self, *directories):
        self.by_name = {}
        for directory in directories:
            assert directory.name not in self.by_name, "one Directory per name: " + directory.name
            self.by_name[directory.name] = directory
        self.selected = None
        self.requested = []

    def open(self, name):
        self.requested.append(name)
        self.close()
        directory = self.by_name.get(name)
        if directory is None or not directory.open(name):
            return False
        self.selected = directory
        return True

    def read(self):
        return None if self.selected is None else self.selected.read()

    def close(self):
        if self.selected is not None:
            self.selected.close()
            self.selected = None


class Clock(object):
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Wire(object):
    """The datagram transport of the client: records (data, port); fail = the socket refuses."""

    def __init__(self):
        self.sent = []
        self.fail = False

    def __call__(self, data, port):
        if self.fail:
            return -1
        self.sent.append((data, port))
        return len(data)


def make_client(directory=None, wire=None, clock=None, ids=None, **kw):
    directory = directory or FakeDirectory()
    wire = wire or Wire()
    clock = clock or Clock()
    lines = []
    id_factory = None
    if ids is not None:
        queue = list(ids)
        id_factory = lambda: queue.pop(0)  # noqa: E731
    client = cjc.CurrentJumpClient(PID, INSTANCE, APP_PID, wire, source=directory, log=lines.append, clock=clock, id_factory=id_factory, **kw)
    return client, directory, wire, clock, lines


STA = "JUMP_STA_TIME:0:36000000"
LOC = "JUMP_LOC_TIME:1000.0:36000000"


# ----------------------------------------------------------------------------------------------------------------------------------------------------
class A_ClientRequestId(unittest.TestCase):
    def test_the_command_carries_a_nonzero_random_request_id_in_a_contract_envelope(self):
        client, directory, wire, _clock, _lines = make_client()
        rid = client.send(STA)
        self.assertIsNotNone(rid)
        self.assertEqual(len(rid), 16)
        self.assertTrue(any(rid))
        data, port = wire.sent[0]
        self.assertEqual(port, directory.port)
        env = contract.decode_envelope(data)
        self.assertEqual(env["message_type"], contract.MSG_JUMP_STATION_TIME)
        self.assertEqual(env["request_id"], rid)
        self.assertEqual((env["bve_pid"], env["sender_pid"]), (PID, APP_PID))          # the sender of a command is the managed application
        self.assertEqual((env["app_instance"], env["generation"], env["token"]), (INSTANCE, directory.generation, directory.token))
        self.assertEqual(env["payload"], STA.encode("utf-8"))                            # the legacy text is unchanged
        self.assertEqual(client.outstanding_id, rid)

    def test_a_location_command_uses_its_own_message_type(self):
        client, _d, wire, _c, _l = make_client()
        client.send(LOC)
        env = contract.decode_envelope(wire.sent[0][0])
        self.assertEqual((env["message_type"], env["payload"]), (contract.MSG_JUMP_LOCATION_TIME, LOC.encode("utf-8")))

    def test_every_command_gets_a_fresh_request_id(self):
        client, _d, _w, _c, _l = make_client()
        ids = {client.send(STA) for _ in range(40)}
        self.assertEqual(len(ids), 40)

    def test_a_zero_or_repeated_id_from_the_generator_is_never_used(self):
        good1, good2 = bytes([1] * 16), bytes([2] * 16)
        client, _d, _w, _c, _l = make_client(ids=[bytes(16), good1, good1, good2])
        self.assertEqual(client.send(STA), good1)
        self.assertEqual(client.send(STA), good2)

    def test_the_sender_pid_is_the_application_and_the_instance_is_its_own(self):
        client, _d, wire, _c, _l = make_client()
        client.send(STA)
        env = contract.decode_envelope(wire.sent[0][0])
        self.assertNotEqual(env["sender_pid"], 0)
        self.assertEqual(env["sender_pid"], APP_PID)


class A_ClientCompletion(unittest.TestCase):
    def test_the_matching_request_id_is_accepted_once(self):
        client, _d, _w, _c, lines = make_client()
        rid = client.send(STA)
        self.assertEqual(client.complete(rid), cjc.R_OK)
        self.assertFalse(client.has_outstanding)
        self.assertEqual(client.counts["completed"], 1)
        self.assertTrue(any("event=complete-accepted" in l for l in lines))

    def test_a_second_completion_of_the_same_request_is_a_duplicate(self):
        client, _d, _w, _c, _l = make_client()
        rid = client.send(STA)
        self.assertEqual(client.complete(rid), cjc.R_OK)
        self.assertEqual(client.complete(rid), cjc.R_DUPLICATE)
        self.assertEqual(client.complete(rid), cjc.R_DUPLICATE)

    def test_an_id_that_was_never_issued_is_a_mismatch(self):
        client, _d, _w, _c, _l = make_client()
        rid = client.send(STA)
        other = bytes(b ^ 0xFF for b in rid)
        self.assertEqual(client.complete(other), cjc.R_UNKNOWN)
        self.assertTrue(client.has_outstanding)                                          # the outstanding request is untouched
        self.assertEqual(client.complete(rid), cjc.R_OK)

    def test_a_completion_without_any_request_is_unknown(self):
        client, _d, _w, _c, _l = make_client()
        self.assertEqual(client.complete(bytes([9] * 16)), cjc.R_UNKNOWN)

    def test_a_newer_command_supersedes_the_older_one_which_is_then_stale(self):
        client, _d, _w, _c, _l = make_client()
        first = client.send(STA)
        second = client.send(LOC)
        self.assertEqual(client.outstanding_id, second)
        self.assertEqual(client.complete(first), cjc.R_STALE)
        self.assertTrue(client.has_outstanding)
        self.assertEqual(client.complete(second), cjc.R_OK)
        self.assertIsNone(client.last_failure)                                           # a superseded request is not a failure

    def test_invalid_ids_are_refused_without_touching_the_request(self):
        client, _d, _w, _c, _l = make_client()
        rid = client.send(STA)
        for bad in (None, b"", bytes(16), bytes(15), bytes(17), "x" * 16):
            self.assertIn(client.complete(bad), (cjc.R_INVALID,), repr(bad))
        self.assertEqual(client.outstanding_id, rid)

    def test_rejections_are_logged_once_per_kind_and_counted(self):
        client, _d, _w, _c, lines = make_client()
        client.send(STA)
        for i in range(5):
            client.complete(bytes([i + 1] * 16))
        self.assertEqual(len([l for l in lines if "event=complete-rejected" in l]), 1)
        self.assertEqual(client.reasons["complete-unknown"], 5)


class A_ClientRefusalAndCancel(unittest.TestCase):
    def refused(self, client, text=STA):
        self.assertIsNone(client.send(text))
        self.assertFalse(client.has_outstanding)
        self.assertTrue(client.last_failure.startswith("send-refused:"), client.last_failure)
        return client.last_failure

    def test_a_missing_directory_refuses_the_send_and_creates_no_request(self):
        client, directory, wire, _c, lines = make_client()
        directory.present = False
        self.assertEqual(self.refused(client), "send-refused:jump-directory-missing")
        self.assertEqual(wire.sent, [])
        self.assertTrue(any("event=send-refused reason=jump-directory-missing" in l for l in lines))

    def test_a_withdrawn_or_closed_endpoint_is_not_used(self):
        client, directory, wire, _c, _l = make_client()
        directory.withdraw()
        self.assertEqual(self.refused(client), "send-refused:jump-endpoint-not-usable")
        directory.publish(contract.CLOSED)
        self.assertEqual(self.refused(client), "send-refused:jump-endpoint-not-usable")
        self.assertEqual(wire.sent, [])

    def test_a_not_ready_endpoint_is_not_used(self):
        client, directory, wire, _c, _l = make_client()
        directory.publish(contract.PUBLISHED)
        self.assertEqual(self.refused(client), "send-refused:jump-endpoint-not-usable")
        self.assertEqual(wire.sent, [])

    def test_the_request_id_capability_is_required(self):
        client, directory, wire, _c, _l = make_client()
        directory.publish(caps=contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME)
        self.assertEqual(self.refused(client), "send-refused:request-id-unsupported")
        self.assertEqual(wire.sent, [])

    def test_the_command_capability_is_required(self):
        client, directory, wire, _c, _l = make_client()
        directory.publish(caps=contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_REQUEST_ID)
        self.assertEqual(self.refused(client, LOC), "send-refused:command-unsupported")
        self.assertIsNotNone(client.send(STA))

    def test_a_failed_socket_write_leaves_no_request(self):
        client, _d, wire, _c, _l = make_client()
        wire.fail = True
        self.assertEqual(self.refused(client), "send-refused:send-failed")

    def test_an_unknown_command_text_is_not_sent(self):
        client, _d, wire, _c, _l = make_client()
        self.assertEqual(self.refused(client, "JUMP_SOMETHING:1"), "send-refused:unknown-command")
        self.assertEqual(wire.sent, [])

    def test_a_refused_send_does_not_cancel_the_outstanding_request(self):
        client, directory, _w, _c, _l = make_client()
        rid = client.send(STA)
        directory.withdraw()
        self.assertIsNone(client.send(LOC))
        self.assertEqual(client.outstanding_id, rid)

    def test_a_refusal_is_logged_once_per_reason(self):
        client, directory, _w, _c, lines = make_client()
        directory.present = False
        for _ in range(6):
            client.send(STA)
        self.assertEqual(len([l for l in lines if "event=send-refused" in l]), 1)
        self.assertEqual(client.reasons["refused:jump-directory-missing"], 6)

    def test_a_withdrawn_endpoint_cancels_the_outstanding_request_and_a_late_completion_is_stale(self):
        client, directory, wire, clock, lines = make_client()
        rid = client.send(STA)
        directory.withdraw()
        clock.t += cjc.WATCH_INTERVAL_S + 0.01
        client.poll()
        self.assertFalse(client.has_outstanding)
        self.assertEqual(client.last_failure, "endpoint-withdrawn")
        self.assertEqual(client.complete(rid), cjc.R_STALE)
        self.assertEqual(len(wire.sent), 1)                                              # never retried
        self.assertTrue(any("event=request-cancelled" in l and "reason=endpoint-withdrawn" in l for l in lines))

    def test_a_changed_token_or_generation_cancels_without_a_retry_against_the_new_endpoint(self):
        for change in (dict(token=bytes(range(7, 23))), dict(generation=12)):
            client, directory, wire, clock, _l = make_client()
            rid = client.send(STA)
            directory.publish(**change)
            clock.t += cjc.WATCH_INTERVAL_S + 0.01
            client.poll()
            self.assertEqual(client.last_failure, "endpoint-changed", change)
            self.assertEqual(client.complete(rid), cjc.R_STALE)
            self.assertEqual(len(wire.sent), 1, change)

    def test_a_closed_endpoint_cancels(self):
        client, directory, _w, clock, _l = make_client()
        rid = client.send(STA)
        directory.publish(contract.CLOSED)
        clock.t += cjc.WATCH_INTERVAL_S + 0.01
        client.poll()
        self.assertEqual(client.last_failure, "endpoint-withdrawn")
        self.assertEqual(client.complete(rid), cjc.R_STALE)

    def test_an_unreadable_directory_never_raises(self):
        client, directory, _w, clock, _l = make_client()
        client.send(STA)
        directory.broken = True
        clock.t += cjc.WATCH_INTERVAL_S + 0.01
        client.poll()                                                                    # must not raise
        directory.broken = False

    def test_a_lost_completion_times_out_and_is_reported(self):
        client, _d, wire, clock, lines = make_client()
        rid = client.send(STA)
        clock.t += cjc.OUTSTANDING_TIMEOUT_S - 0.5
        client.poll()
        self.assertTrue(client.has_outstanding)
        clock.t += 1.0
        client.poll()
        self.assertFalse(client.has_outstanding)
        self.assertEqual(client.last_failure, "timeout")
        self.assertTrue(any("event=timeout" in l for l in lines))
        self.assertEqual(client.complete(rid), cjc.R_STALE)                              # a very late completion changes nothing
        self.assertEqual(len(wire.sent), 1)                                              # and the request is not resent
        self.assertIn("ended:timeout", client.reasons)

    def test_cancel_by_the_application_is_idempotent(self):
        client, _d, _w, _c, _l = make_client()
        rid = client.send(STA)
        self.assertTrue(client.cancel("generation"))
        self.assertFalse(client.cancel("generation"))
        self.assertEqual(client.complete(rid), cjc.R_STALE)

    def test_close_cancels_and_a_closed_client_sends_nothing(self):
        client, directory, wire, _c, _l = make_client()
        rid = client.send(STA)
        client.close()
        client.close()
        self.assertEqual(client.last_failure, "shutdown")
        self.assertFalse(directory.opened)
        self.assertIsNone(client.send(STA))
        self.assertEqual(len(wire.sent), 1)
        self.assertEqual(client.complete(rid), cjc.R_STALE)

    def test_the_memory_of_finished_requests_is_bounded(self):
        client, _d, _w, _c, _l = make_client()
        first = client.send(STA)
        for _ in range(cjc.CLOSED_CAPACITY + 5):
            client.send(STA)
        self.assertEqual(client.complete(first), cjc.R_UNKNOWN)                          # forgotten: still never accepted
        self.assertLessEqual(len(client._finished), cjc.CLOSED_CAPACITY)

    def test_the_summary_names_the_counters(self):
        client, _d, _w, _c, _l = make_client()
        client.complete(client.send(STA))
        self.assertIn("sent=1 completed=1 outstanding=0", client.summary())

    # -- take_unreleased: the three ways an official jump is left unreleased are reported once; the application's own cancels are not ------------------------
    def test_a_timeout_is_reported_once_as_unreleased(self):
        client, _d, _w, clock, _l = make_client()
        client.send(STA)
        self.assertIsNone(client.take_unreleased())
        clock.t += cjc.OUTSTANDING_TIMEOUT_S + 0.5
        client.poll()
        self.assertEqual(client.take_unreleased(), "timeout")
        self.assertIsNone(client.take_unreleased())

    def test_a_refused_send_is_reported_as_unreleased(self):
        client, directory, _w, _c, _l = make_client()
        directory.present = False
        client.send(STA)
        self.assertEqual(client.take_unreleased(), "send-refused:jump-directory-missing")
        self.assertIsNone(client.take_unreleased())

    def test_a_withdrawn_or_changed_endpoint_is_reported_as_unreleased(self):
        for change, expected in ((None, "endpoint-withdrawn"), (dict(generation=12), "endpoint-changed")):
            client, directory, _w, clock, _l = make_client()
            client.send(STA)
            directory.withdraw() if change is None else directory.publish(**change)
            clock.t += cjc.WATCH_INTERVAL_S + 0.01
            client.poll()
            self.assertEqual(client.take_unreleased(), expected)

    def test_a_cancel_the_application_asked_for_is_not_reported_as_unreleased(self):
        for reason in ("generation", "session-ended", "scoring-aborted", "shutdown"):
            client, _d, _w, _c, _l = make_client()
            client.send(STA)
            client.cancel(reason)
            self.assertIsNone(client.take_unreleased(), reason)

    def test_a_completion_or_a_newer_command_leaves_nothing_unreleased(self):
        client, directory, _w, _c, _l = make_client()
        directory.present = False
        client.send(STA)
        directory.present = True
        client.send(STA)                                                                 # a command is on its way again: the old refusal is not left over
        self.assertIsNone(client.take_unreleased())
        client.send(LOC)
        client.complete(client.outstanding_id)
        self.assertIsNone(client.take_unreleased())


# ----------------------------------------------------------------------------------------------------------------------------------------------------
GEN = 7
TOKEN = bytes(range(1, 17))
REQ = bytes(range(16, 32))
COMPLETE = b"JUMP_COMPLETE:STA:0:0.0:36000000:1"


def env(mtype=contract.MSG_JUMP_COMPLETE, payload=COMPLETE, bve_pid=PID, sender=PID, gen=GEN, instance=INSTANCE, token=TOKEN, request_id=REQ):
    return contract.encode_envelope(mtype, bve_pid, sender, gen, instance, token, request_id, payload)


def make_receiver(lines=None):
    return receiver_module.TelemetryDataPlaneReceiver(PID, INSTANCE, GEN, TOKEN, None if lines is None else lines.append)


class B_ReceiverType5(unittest.TestCase):
    def test_type_5_is_accepted_and_its_request_id_is_exposed(self):
        r = make_receiver()
        self.assertEqual(r.accept(env()), COMPLETE)
        self.assertEqual(r.last_request_id, REQ)
        self.assertEqual((r.accepted, r.rejected), (1, 0))

    def test_the_request_id_does_not_survive_into_the_next_datagram(self):
        r = make_receiver()
        r.accept(env())
        self.assertEqual(r.accept(env(contract.MSG_TELEMETRY, b"SCENARIO_ID:1", request_id=bytes(16))), b"SCENARIO_ID:1")
        self.assertIsNone(r.last_request_id)
        r.accept(env())
        self.assertIsNone(r.accept(b"junk"))
        self.assertIsNone(r.last_request_id)

    def test_a_zero_request_id_is_not_a_completion(self):
        r = make_receiver()
        self.assertIsNone(r.accept(env(request_id=bytes(16))))
        self.assertEqual(r.reasons, {"request-id": 1})

    def test_the_ownership_rules_apply_to_type_5_as_to_every_type(self):
        for kw, reason in ((dict(bve_pid=PID + 1), "bve-pid-mismatch"), (dict(instance="fedcba9876543210fedcba9876543210"), "app-instance-mismatch"),
                           (dict(gen=GEN + 1), "generation-mismatch"), (dict(token=bytes(range(2, 18))), "token-mismatch"), (dict(sender=PID + 1), "sender-pid-mismatch")):
            r = make_receiver()
            self.assertIsNone(r.accept(env(**kw)), reason)
            self.assertEqual(r.reasons, {reason: 1}, reason)
            self.assertIsNone(r.last_request_id)

    def test_the_payload_of_type_5_must_be_a_jump_complete(self):
        r = make_receiver()
        self.assertIsNone(r.accept(env(payload=b"SCENARIO_ID:1,SPEED:1")))
        self.assertEqual(r.reasons, {"payload-grammar": 1})

    def test_a_jump_complete_text_under_another_type_is_refused(self):
        for mtype in (contract.MSG_TELEMETRY, contract.MSG_HEARTBEAT, contract.MSG_STATION_LIST, contract.MSG_METADATA):
            r = make_receiver()
            self.assertIsNone(r.accept(env(mtype, COMPLETE, request_id=bytes(16))), mtype)
            self.assertEqual(r.reasons, {"payload-grammar": 1})

    def test_the_jump_commands_never_belong_to_the_telemetry_receiver(self):
        for mtype, text in ((contract.MSG_JUMP_STATION_TIME, b"JUMP_STA_TIME:1:2"), (contract.MSG_JUMP_LOCATION_TIME, b"JUMP_LOC_TIME:1.0:2")):
            r = make_receiver()
            self.assertIsNone(r.accept(env(mtype, text)))
            self.assertEqual(r.reasons, {"message-type-not-allowed": 1})

    def test_a_plain_jump_complete_line_is_not_an_envelope(self):
        r = make_receiver()
        self.assertIsNone(r.accept(COMPLETE))
        self.assertEqual(r.reasons, {"size": 1})

    def test_the_directory_advertises_the_capability(self):
        self.assertTrue(contract.TELEMETRY_PUBLISHED_CAPS & contract.CAP_JUMP_COMPLETE_V1)
        self.assertEqual(contract.TELEMETRY_PUBLISHED_CAPS & ~contract.TELEMETRY_KNOWN_CAPS, 0)


# ----------------------------------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class OverlayCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["d6"])
        import main
        import d6_rig
        import sia_managed_rig as MR
        cls.main, cls.D, cls.MR = main, d6_rig, MR

    def setUp(self):
        self.r = self.D.D6Rig(self.main)
        self.o = self.r.o
        self.saved_profile = os.environ.get("USERPROFILE")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["USERPROFILE"] = self.tmp.name

    def tearDown(self):
        self.r.close()
        if self.saved_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self.saved_profile
        self.tmp.cleanup()

    # helpers ---------------------------------------------------------------------------------------------------------------------------------
    def start(self, end_idx=1):
        r, o = self.r, self.o
        r.go_active()
        o.setting_end_idx = end_idx
        r.start_scoring_via_menu()
        return r.last_command()

    def telemetry(self, t, **kw):
        kw.setdefault("JUMP", 1)
        self.r.send(self.MR.tele(1, time_ms=t, **kw))
        self.r.tick(2)

    def jump_done_by_bve(self, rid=None, complete=True):
        """BVE jumps (the sender's JUMP counter moves), then Current answers with the completion of `rid`."""
        self.telemetry(36000000, speed=0.0, loc=0.0)
        if complete:
            self.r.complete(rid, location=0.0, time_ms=36000000, count=1)
            self.r.tick(2)

    def drive_a_to_b(self, t0=36000000):
        t = t0
        for step in range(1, 6):
            t += 20000
            self.telemetry(t, speed=60.0, loc=200.0 * step, NEXTLOC=1000.0)
        t += 20000
        self.telemetry(t, speed=0.0, loc=1000.0, NEXTLOC=1000.0, DOOR=0)
        t += 5000
        self.telemetry(t, speed=0.0, loc=1000.0, NEXTLOC=1000.0, DOOR=1)
        return t


class C_CommandAndRelease(OverlayCase):
    def test_the_scoring_start_sends_one_command_with_a_nonzero_request_id_and_nothing_to_a_fixed_port(self):
        cmd = self.start()
        written = self.o.udp_socket.written
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0][1], self.r.jump_dir.port)
        self.assertNotIn(54322, [port for _data, port in written])
        self.assertNotIn(54321, [port for _data, port in written])
        self.assertEqual(cmd["message_type"], contract.MSG_JUMP_STATION_TIME)
        self.assertTrue(any(cmd["request_id"]))
        self.assertEqual(cmd["text"], "JUMP_STA_TIME:0:36000000")                         # the legacy text is unchanged
        self.assertEqual(cmd["sender_pid"], self.D.APP_PID)
        self.assertEqual(self.r.client.outstanding_id, cmd["request_id"])
        self.assertTrue(self.o.is_official_jumping)

    def test_the_matching_completion_releases_the_official_jump_and_the_departure_releases_the_lock(self):
        r, o = self.r, self.o
        cmd = self.start()
        self.jump_done_by_bve(cmd["request_id"], complete=False)
        self.assertTrue(o.jump_lock)                                                     # BVE jumped: the lock is set ...
        self.assertTrue(o.is_official_jumping)                                           # ... and held until the completion
        r.complete(cmd["request_id"])
        r.tick(2)
        self.assertFalse(o.is_official_jumping)
        self.telemetry(36020000, speed=30.0, loc=100.0, NEXTLOC=1000.0)
        self.assertFalse(o.jump_lock)                                                    # the existing departure rule releases it
        self.assertTrue(o.has_departed)
        self.assertEqual(r.client.counts["completed"], 1)

    def test_a_mismatching_request_id_releases_nothing(self):
        r, o = self.r, self.o
        cmd = self.start()
        self.jump_done_by_bve(cmd["request_id"], complete=False)
        wrong = bytes(b ^ 0x5A for b in cmd["request_id"])
        r.complete(wrong)
        r.tick(2)
        self.assertTrue(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        self.assertEqual(r.client.outstanding_id, cmd["request_id"])
        r.complete(cmd["request_id"])                                                    # the right one still works afterwards
        self.assertFalse(o.is_official_jumping)

    def test_a_duplicate_completion_changes_nothing(self):
        r, o = self.r, self.o
        cmd = self.start()
        self.jump_done_by_bve(cmd["request_id"])
        self.assertFalse(o.is_official_jumping)
        o.is_official_jumping = True                       # a later official jump is under way ...
        o.pending_jump_complete = None
        r.complete(cmd["request_id"])                      # ... and the old completion arrives again
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(r.client.reasons.get("complete-duplicate"), 1)

    def test_a_stale_completion_of_a_superseded_command_changes_nothing(self):
        r, o = self.r, self.o
        first = self.start()
        o.send_jump_command("JUMP_STA_TIME:0:36000000")    # the retry sends a newer command before the old one completed
        second = r.last_command()
        self.assertNotEqual(first["request_id"], second["request_id"])
        r.complete(first["request_id"])
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(r.client.reasons.get("complete-stale"), 1)
        r.complete(second["request_id"])
        self.assertFalse(o.is_official_jumping)

    def test_a_plain_unwrapped_jump_complete_is_dropped_in_the_managed_mode(self):
        r, o = self.r, self.o
        self.start()
        r.send_raw(b"JUMP_COMPLETE:STA:0:0.0:36000000:1")
        self.assertTrue(o.is_official_jumping)
        self.assertIsNone(o.pending_jump_complete)

    def test_a_completion_envelope_of_another_endpoint_is_dropped(self):
        r, o = self.r, self.o
        cmd = self.start()
        bad = contract.encode_envelope(contract.MSG_JUMP_COMPLETE, r.pid, r.pid, self.D.TELEMETRY_GEN, r.instance, bytes(range(2, 18)), cmd["request_id"],
                                       b"JUMP_COMPLETE:STA:0:0.0:36000000:1")
        r.send_raw(bad)
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(r.receiver.reasons.get("token-mismatch"), 1)
        self.assertEqual(r.client.outstanding_id, cmd["request_id"])

    def test_a_refused_send_never_falls_back_to_a_fixed_port_and_the_scoring_session_is_aborted(self):
        r, o = self.r, self.o
        r.go_active()
        r.jump_dir.present = False                          # Current published no jump endpoint
        r.start_scoring_via_menu()
        self.assertEqual(o.udp_socket.written, [])          # nothing was written anywhere: no fixed-port fallback
        self.assertEqual(r.client.last_failure, "send-refused:jump-directory-missing")
        self.assertFalse(r.client.has_outstanding)
        self.assertTrue(o.is_official_jumping)               # until the next datagram of the sender drives the poll ...
        r.send("STATUS:LOADED:RUNNING")
        self.assertFalse(o.is_scoring_mode)                  # ... then the session is aborted: no endless, silent dead scoring session
        self.assertFalse(o.is_official_jumping)
        self.assertEqual(o.udp_socket.written, [])

    def test_the_generation_boundary_cancels_the_outstanding_request(self):
        import managed_input
        r, o = self.r, self.o
        cmd = self.start()
        managed_input.discard_generation_state(o)
        self.assertFalse(r.client.has_outstanding)
        self.assertEqual(r.client.last_failure, "generation")
        r.complete(cmd["request_id"])
        self.assertFalse(o.is_official_jumping)             # discard reset it; the stale completion must not matter
        self.assertEqual(r.client.reasons.get("complete-stale"), 1)

    def test_the_end_of_the_scoring_session_cancels_the_outstanding_request(self):
        import managed_input
        r, o = self.r, self.o
        self.start()
        managed_input.discard_scoring_session(o)
        self.assertFalse(r.client.has_outstanding)
        self.assertEqual(r.client.last_failure, "session-ended")


class C_TheWholeScoringRun(OverlayCase):
    def test_start_jump_completion_run_a_to_b_end_and_result_display(self):
        r, o = self.r, self.o
        cmd = self.start(end_idx=1)                                             # the scoring section is shortened to A -> B
        self.jump_done_by_bve(cmd["request_id"])
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.is_scoring_mode)
        t = self.drive_a_to_b()
        self.assertTrue(o.has_departed)
        self.assertFalse(o.jump_lock)
        self.assertTrue(o.is_scoring_finished)                                  # the scoring end ...
        self.assertGreater(o.end_message_time, 0.0)
        self.assertEqual(len(r.events("scoring-finish")), 1)
        self.telemetry(t + 6000, speed=0.0, loc=1000.0, NEXTLOC=1000.0, DOOR=1)
        self.assertIn("運転お疲れ様でした。", [p["text"] for p in o.popups])      # ... the scoring-end message ...
        self.telemetry(t + 12000, speed=0.0, loc=1000.0, NEXTLOC=1000.0, DOOR=1)
        self.assertEqual(o.menu_state, 11)                                      # ... and the result display
        self.assertGreater(o.score, 0)                                          # the scoring features ran (the stop at B was scored)

    def test_without_the_completion_the_run_stays_dead_exactly_as_in_the_stage_a_regression(self):
        """The reproduction of the audited failure: the same drive, but the completion never arrives."""
        r, o = self.r, self.o
        self.start(end_idx=1)
        self.jump_done_by_bve(complete=False)
        self.drive_a_to_b()
        self.assertTrue(o.is_official_jumping)
        self.assertTrue(o.jump_lock)
        self.assertFalse(o.has_departed)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(o.score, 0)
        self.assertEqual(o.menu_state, 0)

    # -- the timeout contract: a completion that never arrives ends THAT scoring session (fail closed), it neither sticks silently nor resumes scoring ---------
    def lose_the_completion(self, end_idx=1):
        r = self.r
        cmd = self.start(end_idx=end_idx)
        self.jump_done_by_bve(complete=False)
        r.rig.advance(cjc.OUTSTANDING_TIMEOUT_S + 1.0)
        r.send("STATUS:LOADED:RUNNING")                                         # the next datagram of the sender drives the watch
        return cmd

    def test_a_lost_completion_is_detected_and_aborts_the_scoring_session_through_the_jump_abort_path(self):
        r, o = self.r, self.o
        self.lose_the_completion()
        self.assertFalse(r.client.has_outstanding)
        self.assertEqual(r.client.last_failure, "timeout")                       # the failure stays recorded (the abort has nothing left to cancel)
        self.assertTrue(any("event=timeout" in line for line in r.jump_lines))
        self.assertEqual(len(r.jump_commands()), 1)                              # never resent
        self.assertFalse(o.is_scoring_mode)                                      # the session is over ...
        self.assertFalse(o.is_official_jumping)                                  # ... nothing is left half-released ...
        self.assertTrue(o.jump_lock)                                             # ... the lock follows the existing abort path (released by the next departure)
        self.assertFalse(o.is_scoring_finished)                                  # no result is fixed
        self.assertEqual(o.menu_state, 0)                                        # and none is shown
        texts = [p["text"] for p in o.popups]
        self.assertIn("採点を中断します。", texts)
        self.assertTrue(all(p.get("category") == "警告" for p in o.popups))

    def test_the_abort_is_reported_by_the_input_controller_like_the_illegal_jump_abort(self):
        r = self.r
        self.lose_the_completion()
        r.tick(2)
        aborts = r.events("scoring-abort")
        self.assertEqual(len(aborts), 1)
        self.assertIn("reason=jump", str(aborts[0]))

    def test_a_very_late_completion_is_stale_and_never_revives_the_aborted_session(self):
        r, o = self.r, self.o
        cmd = self.lose_the_completion()
        r.complete(cmd["request_id"])
        r.tick(2)
        self.assertEqual(r.client.reasons.get("complete-stale"), 1)
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_official_jumping)
        self.assertIsNone(o.pending_jump_complete)

    def test_after_the_abort_the_drive_scores_nothing_and_shows_no_result(self):
        r, o = self.r, self.o
        cmd = self.lose_the_completion(end_idx=1)
        r.complete(cmd["request_id"])
        self.drive_a_to_b()
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(o.score, 0)
        self.assertEqual(o.menu_state, 0)
        self.assertEqual(len(r.events("scoring-finish")), 0)
        self.assertNotIn("運転お疲れ様でした。", [p["text"] for p in o.popups])

    def test_the_abort_happens_once_and_a_second_poll_changes_nothing(self):
        r, o = self.r, self.o
        self.lose_the_completion()
        popups = len(o.popups)
        r.send("STATUS:LOADED:RUNNING")
        r.send("STATUS:LOADED:RUNNING")
        self.assertEqual(len(o.popups), popups)
        self.assertEqual(r.client.take_unreleased(), None)

    def test_after_the_abort_the_next_scoring_start_works_again(self):
        r, o = self.r, self.o
        self.lose_the_completion(end_idx=1)
        self.assertFalse(o.is_scoring_mode)
        r.start_scoring_via_menu()                                               # a normal start: a new official jump with a new request id
        again = r.last_command()
        self.assertEqual(len(r.jump_commands()), 2)
        self.assertTrue(o.is_scoring_mode)
        self.assertTrue(o.is_official_jumping)
        self.assertTrue(r.client.has_outstanding)
        r.complete(again["request_id"])
        self.assertFalse(o.is_official_jumping)
        self.assertTrue(o.is_scoring_mode)

    def test_a_withdrawn_endpoint_during_the_official_jump_aborts_the_session(self):
        r, o = self.r, self.o
        cmd = self.start(end_idx=1)
        r.jump_dir.withdraw()
        r.rig.advance(cjc.WATCH_INTERVAL_S + 0.1)
        r.send("STATUS:LOADED:RUNNING")
        self.assertFalse(r.client.has_outstanding)
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_official_jumping)
        r.complete(cmd["request_id"])                                            # stale
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(len(r.jump_commands()), 1)                              # never retried against another endpoint

    def test_a_cancel_the_application_asked_for_is_never_an_abort_of_a_later_session(self):
        import managed_input
        r, o = self.r, self.o
        self.start(end_idx=1)
        managed_input.discard_scoring_session(o)                                 # the session ended by itself: the client cancels, nothing is reported
        self.assertIsNone(r.client.take_unreleased())
        r.start_scoring_via_menu()
        r.send("STATUS:LOADED:RUNNING")
        self.assertTrue(o.is_scoring_mode)                                       # the new session is not aborted by the old cancel
        self.assertTrue(o.is_official_jumping)

    def test_the_normal_mode_has_no_client_and_no_abort(self):
        import types
        o = types.SimpleNamespace(jump_client=None)
        self.main.Overlay._poll_jump_client(o)                                   # no client: nothing to poll, nothing to abort (the normal mode is unchanged)


class C_F8AutoReleaseIsRecovered(OverlayCase):
    """The existing F8 contract (not changed here): F8 is usable while stopped, it is suppressed while driving, and TS Scoring itself returns a fast forward that
    was started while stopped to normal speed once the train drives. That release is skipped while the official jump is unreleased - the regression."""

    def f8(self):
        return [p for p in self.r.api_win32.posted if p[2] == 0x77 and p[1] == 0x0100]

    def fast_forward_after_departure(self, completed):
        r, o = self.r, self.o
        cmd = self.start(end_idx=1)
        self.jump_done_by_bve(cmd["request_id"], complete=completed)
        t = 36000000
        # started while stopped: the BVE time runs ten times faster than the real time, the train stands: nothing is injected
        t += 5000
        self.r.send(self.MR.tele(1, time_ms=t, speed=0.0, loc=0.0, JUMP=1))
        self.r.tick(1, seconds=0.06)
        self.assertEqual(self.f8(), [])
        # the train drives off while the fast forward is still on
        t += 5000
        self.r.send(self.MR.tele(1, time_ms=t, speed=5.0, loc=10.0, JUMP=1))
        self.r.tick(1, seconds=0.06)
        return len(self.f8()), len(r.events("ff-release"))

    def test_the_fast_forward_started_while_stopped_is_released_after_the_departure(self):
        self.assertEqual(self.fast_forward_after_departure(True), (1, 1))

    def test_without_the_completion_the_release_is_skipped(self):
        self.assertEqual(self.fast_forward_after_departure(False), (0, 0))


class C_TheOtherPathsAreUnchanged(OverlayCase):
    def test_the_pid_d3_chain_telemetry_stalist_heartbeat_meta_still_flows(self):
        r, o = self.r, self.o
        r.go_active()
        self.assertEqual(len(o.station_list), 3)
        r.send("STATUS:LOADED:PAUSED")
        self.assertEqual(o.bve_actual_state, "PAUSED")
        r.send("META:T:R:V:A:C")
        self.assertEqual(o.meta_title, "T")
        r.send(self.MR.tele(1, time_ms=36001000, speed=12.5, loc=40.0))
        self.assertAlmostEqual(o.bve_speed, 12.5)
        self.assertGreaterEqual(r.receiver.accepted, 4)

    def test_a_plain_telemetry_line_is_still_dropped_in_the_managed_mode(self):
        r, o = self.r, self.o
        r.go_active()
        before = o.bve_speed
        r.send_raw(self.MR.tele(1, time_ms=36002000, speed=99.0).encode("utf-8"))
        self.assertEqual(o.bve_speed, before)

    def test_the_normal_mode_keeps_the_plain_fixed_port_protocol(self):
        import sia_rig as R
        # the Overlay of the normal mode: no receiver, no strict flag, no jump client
        self.r.close()
        rig = R.Rig(self.main)
        try:
            o = rig.o
            self.assertIsNone(o.jump_client)
            self.assertFalse(o.dataplane_strict)
            o.send_jump_command("JUMP_STA_TIME:0:5")
            self.assertEqual(o.udp_socket.written, [(b"JUMP_STA_TIME:0:5", 54322)])
            o.is_official_jumping = True
            o.expected_target_loc = 0.0
            o.udp_socket.incoming.append(b"JUMP_COMPLETE:STA:0:0.0:5:1")
            o.read_udp_data()
            self.assertFalse(o.is_official_jumping)
        finally:
            rig.close()
            self.r = self.D.D6Rig(self.main)      # tearDown closes it


# ----------------------------------------------------------------------------------------------------------------------------------------------------
class E_ManagedJumpLog(unittest.TestCase):
    """The Caller copies only '[MANAGED] ' lines of the application's stderr: the client's lines must reach it in that form (live evidence of command-sent /
    complete-accepted / timeout), a bounded number of them, with the closing summary always present."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import main
        cls.main = main

    def args(self):
        import types
        return types.SimpleNamespace(instance=INSTANCE, owner="caller", bve_pid=PID)

    def test_a_client_line_becomes_a_managed_event_line_the_caller_copies(self):
        out = []
        emit = self.main._managed_jump_log(out.append, self.args())
        emit("[JUMP] event=command-sent id=ab12cd34 type=0x100 port=41000 gen=11")
        self.assertEqual(out, ["[MANAGED] event=jump-command-sent inst=%s owner=caller pid=%d id=ab12cd34 type=0x100 port=41000 gen=11" % (INSTANCE, PID)])
        self.assertTrue(out[0].startswith("[MANAGED] "))                                 # AppProcessManager copies exactly these
        self.assertLessEqual(len(out[0]), 160)                                           # and keeps 160 characters of each

    def test_a_line_that_is_not_a_client_event_is_passed_through_untouched(self):
        out = []
        self.main._managed_jump_log(out.append, self.args())("[MANAGED] event=other x=1")
        self.assertEqual(out, ["[MANAGED] event=other x=1"])

    def test_the_number_of_event_lines_is_bounded_and_the_summary_is_always_issued(self):
        out = []
        emit = self.main._managed_jump_log(out.append, self.args(), limit=3)
        for i in range(10):
            emit("[JUMP] event=command-sent id=%08x" % i)
        emit("[JUMP] event=summary sent=10 completed=0 outstanding=0 reasons=-")
        self.assertEqual(len(out), 4)
        self.assertIn("event=jump-summary ", out[-1])

    def test_every_event_name_of_the_client_survives_the_conversion(self):
        out = []
        emit = self.main._managed_jump_log(out.append, self.args())
        for name in ("command-sent", "complete-accepted", "complete-rejected", "timeout", "request-cancelled", "send-refused"):
            emit("[JUMP] event=%s id=00000000" % name)
        self.assertEqual([line.split()[1] for line in out], ["event=jump-" + n for n in ("command-sent", "complete-accepted", "complete-rejected", "timeout", "request-cancelled", "send-refused")])


# ----------------------------------------------------------------------------------------------------------------------------------------------------
class D_StaticGuards(unittest.TestCase):
    def test_the_fixed_jump_port_appears_in_one_place_of_the_python_application_the_normal_mode_branch(self):
        for name in ("main.py", "scoring_logic.py", "managed_input.py", "managed_hud.py", "current_jump_client.py"):
            text = read(name)
            expected = 1 if name == "main.py" else 0
            self.assertEqual(len(re.findall(r"54322", text)), expected, name)
        main = read("main.py")
        start = main.index("    def send_jump_command(")
        branch = main[start:main.index("    def _unwrap_dataplane", start)]
        self.assertIn("54322", branch)
        # the managed branch returns before the fixed-port write
        self.assertLess(branch.index("client.send(command)"), branch.index("54322"))

    def test_no_python_module_writes_to_the_fixed_telemetry_port(self):
        for name in ("main.py", "scoring_logic.py", "current_jump_client.py", "telemetry_dataplane_receiver.py"):
            self.assertEqual(len(re.findall(r"writeDatagram\([^)]*54321", read(name))), 0, name)

    def test_the_client_names_no_host_and_uses_no_qt_or_socket(self):
        code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", read("current_jump_client.py"), flags=re.S)).lower()
        for word in ("legacy", "atsex", "bveex", "pyqt", "import socket", "qudp"):
            self.assertNotIn(word, code, word)

    def test_the_scoring_functions_other_than_the_transport_line_are_untouched(self):
        # the only change of scoring_logic.py in this slice is the transport call of execute_retry (pinned by tests/test_managed_input_sia3.py as well)
        text = read("scoring_logic.py")
        self.assertEqual(len(re.findall(r"send_jump_command", text)), 1)

    def test_the_shutdown_order_the_client_is_cancelled_before_the_receiver_stops(self):
        main = read("main.py")
        body = main[main.index("        def cleanup_managed_resources():"):main.index("        cleanup = cleanup_managed_resources")]
        self.assertLess(body.index("telemetry_directory.publish_withdrawing()"), body.index("jump_client.close()"))
        self.assertLess(body.index("jump_client.close()"), body.index("dataplane_receiver.stop()"))
        self.assertLess(body.index("dataplane_receiver.stop()"), body.index("telemetry_directory.close()"))

    def test_the_client_is_created_for_the_caller_owner_only(self):
        main = read("main.py")
        at = main.index("                jump_client = current_jump_client.CurrentJumpClient(")
        enclosing = [line for line in main[:at].split("\n") if line.startswith("            ") and not line.startswith("             ")][-1]
        self.assertEqual(enclosing.strip(), 'if args.owner == "caller":')           # the nearest block header above it (12 spaces) is the caller-owner branch

    def test_the_c_sharp_and_python_constants_agree(self):
        with open(os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "CurrentJumpEndpoint.cs"), encoding="utf-8") as stream:
            source = stream.read()
        caps = dict((m.group(1), int(m.group(2), 16)) for m in re.finditer(r"internal const UInt32 (StationTime|LocationTime|RequestId) = 0x([0-9A-Fa-f]+)U;", source))
        self.assertEqual(caps, {"StationTime": contract.JUMP_CAP_STATION_TIME, "LocationTime": contract.JUMP_CAP_LOCATION_TIME, "RequestId": contract.JUMP_CAP_REQUEST_ID})
        with open(os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "CurrentDataPlane.cs"), encoding="utf-8") as stream:
            plane = stream.read()
        types = dict((m.group(1), int(m.group(2), 16)) for m in re.finditer(r"internal const UInt32 (JumpComplete|JumpStationTime|JumpLocationTime) = (?:0x)?([0-9A-Fa-f]+)U;", plane))
        self.assertEqual(types, {"JumpComplete": 5, "JumpStationTime": 0x100, "JumpLocationTime": 0x101})
        self.assertEqual((contract.MSG_JUMP_COMPLETE, contract.MSG_JUMP_STATION_TIME, contract.MSG_JUMP_LOCATION_TIME), (5, 0x100, 0x101))


# ----------------------------------------------------------------------------------------------------------------------------------------------------
class F_NameAwareFakeSources(unittest.TestCase):
    """PID-D4 / Legacy Jump 2A-alpha (Stage S4): the fake source answers the Directory NAME it was asked for (the client looks at the Current and the Legacy name).

    Current only, Legacy only, both, neither, one of them invalid; an unknown name is absent; the block that is read is the block of the name that was opened."""

    CURRENT = contract.jump_name(PID)
    LEGACY = contract.legacy_jump_name(PID)

    def pair(self, current=True, legacy=True):
        current_dir = FakeDirectory(name=self.CURRENT)
        legacy_dir = FakeDirectory(port=42000, generation=21, token=bytes(range(201, 217)), name=self.LEGACY)
        current_dir.present, legacy_dir.present = current, legacy
        return current_dir, legacy_dir, FakeDirectories(current_dir, legacy_dir)

    def send_via(self, source):
        client, _directory, wire, _clock, _lines = make_client(directory=source)
        return client, wire, client.send(STA)

    def test_the_fake_directory_answers_only_the_name_it_was_published_under(self):
        current_dir, legacy_dir, _source = self.pair()
        self.assertTrue(current_dir.open(self.CURRENT))
        self.assertEqual(current_dir.read(), current_dir.block)
        current_dir.close()
        self.assertFalse(current_dir.open(self.LEGACY))
        self.assertIsNone(current_dir.read())                                          # nothing is open: no block is handed out
        self.assertFalse(legacy_dir.open(self.CURRENT))
        self.assertFalse(legacy_dir.open("Local\\TSScoringPlugin.v1.%d.SomethingElse" % PID))
        self.assertTrue(legacy_dir.open(self.LEGACY))
        legacy_dir.present = False
        self.assertFalse(legacy_dir.open(self.LEGACY))                                 # absent stays absent under its own name

    def test_the_set_reads_the_block_of_the_name_that_was_opened_and_an_unknown_name_is_absent(self):
        current_dir, legacy_dir, source = self.pair()
        self.assertNotEqual(current_dir.block, legacy_dir.block)
        self.assertTrue(source.open(self.LEGACY))
        self.assertEqual(source.read(), legacy_dir.block)
        source.close()
        self.assertIsNone(source.read())
        self.assertTrue(source.open(self.CURRENT))
        self.assertEqual(source.read(), current_dir.block)
        source.close()
        self.assertFalse(source.open("Local\\TSScoringPlugin.v1.%d.Unknown" % PID))
        self.assertIsNone(source.read())
        self.assertFalse(current_dir.opened or legacy_dir.opened)

    def test_current_only_the_command_goes_to_the_current_port(self):
        _current_dir, _legacy_dir, source = self.pair(current=True, legacy=False)
        client, wire, rid = self.send_via(source)
        self.assertIsNotNone(rid)
        self.assertEqual([port for _data, port in wire.sent], [41000])
        self.assertEqual(sorted(set(source.requested)), sorted([self.CURRENT, self.LEGACY]), "both known names were looked at")

    def test_legacy_only_the_command_goes_to_the_legacy_port(self):
        _current_dir, _legacy_dir, source = self.pair(current=False, legacy=True)
        client, wire, rid = self.send_via(source)
        self.assertIsNotNone(rid)
        self.assertEqual([port for _data, port in wire.sent], [42000])

    def test_both_directories_are_ambiguous_nothing_is_preferred_nothing_is_sent(self):
        _current_dir, _legacy_dir, source = self.pair(current=True, legacy=True)
        client, wire, rid = self.send_via(source)
        self.assertIsNone(rid)
        self.assertEqual(wire.sent, [])
        self.assertEqual(client.reasons.get("refused:jump-host-ambiguous"), 1)

    def test_neither_directory_exists_the_command_is_refused_as_missing(self):
        _current_dir, _legacy_dir, source = self.pair(current=False, legacy=False)
        client, wire, rid = self.send_via(source)
        self.assertIsNone(rid)
        self.assertEqual(wire.sent, [])
        self.assertEqual(client.reasons.get("refused:jump-directory-missing"), 1)

    def test_one_invalid_directory_does_not_hide_the_other_usable_one(self):
        for invalid_name, expected_port in ((self.LEGACY, 41000), (self.CURRENT, 42000)):
            current_dir, legacy_dir, source = self.pair()
            (legacy_dir if invalid_name == self.LEGACY else current_dir).make_invalid()
            client, wire, rid = self.send_via(source)
            self.assertIsNotNone(rid, invalid_name)
            self.assertEqual([port for _data, port in wire.sent], [expected_port], invalid_name)

    def test_both_invalid_nothing_is_sent(self):
        current_dir, legacy_dir, source = self.pair()
        current_dir.make_invalid()
        legacy_dir.make_invalid()
        client, wire, rid = self.send_via(source)
        self.assertIsNone(rid)
        self.assertEqual(wire.sent, [])

    def test_a_name_blind_fake_would_read_as_two_directories_which_is_why_the_fake_is_name_aware(self):
        class NameBlind(FakeDirectory):
            def open(self, name):                                  # the old behaviour: every name is "there"
                self.opened = self.present
                return self.present

        client, wire, rid = self.send_via(NameBlind())
        self.assertIsNone(rid)
        self.assertEqual(client.reasons.get("refused:jump-host-ambiguous"), 1)
        client, wire, rid = self.send_via(FakeDirectory())             # the name-aware Current-only fake is not ambiguous
        self.assertIsNotNone(rid)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class G_NameAwareRigFake(unittest.TestCase):
    """The same name-aware contract for the stand-in directory of the rig (tests/d6_rig.py): Current only, Legacy only, both, neither, one invalid."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import d6_rig
        cls.D = d6_rig
        cls.CURRENT = contract.jump_name(PID)
        cls.LEGACY = contract.legacy_jump_name(PID)

    def pair(self, current=True, legacy=True):
        current_dir = self.D.FakeJumpDirectory(PID)
        legacy_dir = self.D.FakeJumpDirectory(PID, port=42000, generation=21, token=bytes(range(201, 217)), name=self.LEGACY)
        current_dir.present, legacy_dir.present = current, legacy
        return current_dir, legacy_dir, self.D.FakeJumpDirectories(current_dir, legacy_dir)

    def resolve(self, source):
        client, _directory, wire, _clock, _lines = make_client(directory=source)
        return client, wire, client.send(STA)

    def test_the_rig_fake_is_the_current_directory_by_default_and_answers_no_other_name(self):
        directory = self.D.FakeJumpDirectory(PID)
        self.assertEqual(directory.name, self.CURRENT)
        self.assertFalse(directory.open(self.LEGACY))
        self.assertIsNone(directory.read())
        self.assertTrue(directory.open(self.CURRENT))
        self.assertEqual(directory.read(), directory.block)
        directory.close()
        directory.present = False
        self.assertFalse(directory.open(self.CURRENT))

    def test_the_rig_set_reads_the_block_of_the_name_that_was_opened(self):
        current_dir, legacy_dir, source = self.pair()
        self.assertNotEqual(current_dir.block, legacy_dir.block)
        self.assertTrue(source.open(self.LEGACY))
        self.assertEqual(source.read(), legacy_dir.block)
        source.close()
        self.assertTrue(source.open(self.CURRENT))
        self.assertEqual(source.read(), current_dir.block)
        source.close()
        self.assertFalse(source.open("Local\\TSScoringPlugin.v1.%d.Unknown" % PID))
        self.assertIsNone(source.read())

    def test_the_five_worlds_through_the_client(self):
        worlds = (
            ("current only", dict(current=True, legacy=False), [41000], None),
            ("legacy only", dict(current=False, legacy=True), [42000], None),
            ("both", dict(current=True, legacy=True), [], "refused:jump-host-ambiguous"),
            ("neither", dict(current=False, legacy=False), [], "refused:jump-directory-missing"),
        )
        for label, kw, ports, refusal in worlds:
            _c, _l, source = self.pair(**kw)
            client, wire, rid = self.resolve(source)
            self.assertEqual([port for _data, port in wire.sent], ports, label)
            self.assertEqual(rid is None, refusal is not None, label)
            if refusal is not None:
                self.assertEqual(client.reasons.get(refusal), 1, label)
        for invalid, expected_port in ((self.LEGACY, 41000), (self.CURRENT, 42000)):
            current_dir, legacy_dir, source = self.pair()
            (legacy_dir if invalid == self.LEGACY else current_dir).make_invalid()
            client, wire, rid = self.resolve(source)
            self.assertIsNotNone(rid, invalid)
            self.assertEqual([port for _data, port in wire.sent], [expected_port], invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
