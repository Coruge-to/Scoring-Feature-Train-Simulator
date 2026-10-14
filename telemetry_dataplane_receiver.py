"""PID-D3: ownership validation of the managed Telemetry receiver (PID-D0B-1 contract sections 10-12).

Pure: no Qt, no clock, no I/O. One instance belongs to one managed application launch. It is built from the launch arguments (BVE PID,
AppInstance) and from the endpoint the application itself published (DataPlane generation + 128-bit token), and answers one question per
datagram: "is this an Envelope v1 datagram for THIS owner and THIS endpoint, and what is its (unchanged) UTF-8 payload?".

A rejected datagram changes nothing but the rejection counters: the caller drops it and never hands it to the Telemetry, STALIST, META or
STATUS handling. The Caller ScenarioGeneration and the telemetry SCENARIO_ID are NOT compared here; the DataPlane generation is a separate value.

Message types accepted: TELEMETRY, HEARTBEAT, STATION_LIST, METADATA and (PID-D6) JUMP_COMPLETE (5). The jump commands (0x100/0x101) go to the Current jump
endpoint, never to this receiver. The RequestId of an accepted JUMP_COMPLETE is left in `last_request_id`; WHICH request it answers (a match, a duplicate, a
stale or unknown id) is decided by current_jump_client, not here.
"""
import hmac

import dataplane_contract as contract

ACCEPTED_TYPES = (contract.MSG_TELEMETRY, contract.MSG_HEARTBEAT, contract.MSG_STATION_LIST, contract.MSG_METADATA, contract.MSG_JUMP_COMPLETE)

# MessageType -> the prefix the existing text payload starts with (TESTSPEC DPE-T-009)
PAYLOAD_PREFIX = {
    contract.MSG_TELEMETRY: b"SCENARIO_ID:",
    contract.MSG_HEARTBEAT: b"STATUS:LOADED:",
    contract.MSG_STATION_LIST: b"STALIST:",
    contract.MSG_METADATA: b"META:",
    contract.MSG_JUMP_COMPLETE: b"JUMP_COMPLETE:",
}

# stable rejection reasons
R_CLOSED = "receiver-closed"
R_MALFORMED = "malformed"
R_BVE_PID = "bve-pid-mismatch"
R_INSTANCE = "app-instance-mismatch"
R_GENERATION = "generation-mismatch"
R_TOKEN = "token-mismatch"
R_SENDER = "sender-pid-mismatch"
R_TYPE = "message-type-not-allowed"
R_PAYLOAD = "payload-grammar"
R_NOT_ATTACHED = "dataplane-not-attached"

_STRUCTURE_REASONS = {
    "size": "size", "magic": "magic", "version": "version", "header-size": "header-size", "flags": "flags",
    "payload-length": "payload-length", "instance": "instance-format", "utf8": "utf8", "identity": "identity-zero",
    "request-id": "request-id", "message-type": "message-type-unknown",
}


class TelemetryDataPlaneReceiver(object):
    def __init__(self, bve_pid, instance, generation, token, log=None):
        contract.telemetry_name(bve_pid, instance)          # validates the PID and the instance text
        token = bytes(token)
        if len(token) != 16 or not any(token):
            raise ValueError("token")
        if not isinstance(generation, int) or isinstance(generation, bool) or not 1 <= generation <= 0xFFFFFFFF:
            raise ValueError("generation")
        self.bve_pid = bve_pid
        self.instance = instance
        self.generation = generation
        self._token = token
        self._log = log
        self._closed = False
        self.accepted = 0
        self.rejected = 0
        self.reasons = {}
        self._first_accept_logged = False
        # the RequestId (16 bytes) of the datagram accept() returned last when it was a JUMP_COMPLETE; None for every other accepted type and after a reject
        self.last_request_id = None

    # -- diagnostics (state changes and aggregates only; never per packet) -------------------------------------------------------------------
    def _emit(self, line):
        if self._log is None:
            return
        try:
            self._log(line)
        except Exception:
            pass

    def _reject(self, reason):
        self.rejected += 1
        first = reason not in self.reasons
        self.reasons[reason] = self.reasons.get(reason, 0) + 1
        if first:
            self._emit("[DATAPLANE] event=reject reason=%s inst=%s" % (reason, self.instance[:8]))
        return None

    def stop(self):
        """Contract 15.2 step 3: no datagram is accepted any more (called after the endpoint is withdrawn, before the socket is closed)."""
        self._closed = True

    def summary(self):
        reasons = ",".join("%s:%d" % (k, self.reasons[k]) for k in sorted(self.reasons)) or "-"
        return "[DATAPLANE] event=summary accepted=%d rejected=%d reasons=%s inst=%s" % (self.accepted, self.rejected, reasons, self.instance[:8])

    # -- one datagram -----------------------------------------------------------------------------------------------------------------------
    def accept(self, datagram):
        """Returns the payload bytes (exactly the pre-migration UTF-8 datagram) or None. Never raises."""
        self.last_request_id = None
        try:
            return self._accept(datagram)
        except Exception:
            return self._reject(R_MALFORMED)

    def _accept(self, datagram):
        if self._closed:
            return self._reject(R_CLOSED)
        try:
            env = contract.decode_envelope(datagram)           # steps 1-4 (+ UTF-8 / request-id / known type, all of which only reject)
        except ValueError as exc:
            return self._reject(_STRUCTURE_REASONS.get(str(exc), R_MALFORMED))
        if env["bve_pid"] != self.bve_pid:                     # step 5
            return self._reject(R_BVE_PID)
        if env["app_instance"] != self.instance:               # step 6
            return self._reject(R_INSTANCE)
        if env["generation"] != self.generation:               # step 7
            return self._reject(R_GENERATION)
        if not hmac.compare_digest(env["token"], self._token):
            return self._reject(R_TOKEN)
        mtype = env["message_type"]
        if mtype not in ACCEPTED_TYPES:                        # step 8
            return self._reject(R_TYPE)
        if env["sender_pid"] != self.bve_pid:                  # SenderPid rule for BVE-originated messages (contract 11)
            return self._reject(R_SENDER)
        payload = env["payload"]                               # step 9 (request id) was checked by the decoder; step 10: payload grammar
        if not payload.startswith(PAYLOAD_PREFIX[mtype]):
            return self._reject(R_PAYLOAD)
        self.accepted += 1
        if not self._first_accept_logged:
            self._first_accept_logged = True
            self._emit("[DATAPLANE] event=first-accept type=%d gen=%d inst=%s" % (mtype, self.generation, self.instance[:8]))
        if mtype == contract.MSG_JUMP_COMPLETE:
            self.last_request_id = bytes(env["request_id"])
        return payload
