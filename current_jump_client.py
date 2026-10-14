"""PID-D6 (necessary minimum slice): the managed application's side of the Current jump path (PID-D0B-1 contract sections 9-11, 13.2).

Sends the official jump command (JUMP_STA_TIME / JUMP_LOC_TIME, unchanged legacy text) inside an Envelope v1 with a fresh random nonzero 128-bit RequestId to the
loopback port that Current publishes in the Current Jump Receiver Directory, and correlates the JUMP_COMPLETE that comes back through the Telemetry receiver.

Pure apart from two injected seams (no Qt, no real clock, no socket of its own):
  send_datagram(data, port) -> bool   hands one datagram to the Overlay's UDP socket (loopback)
  source                              the read-only directory mapping (open / read / close), default: managed_app_directory.Win32DirectorySource(128)

Contract:
  * one request is outstanding at a time. A new command supersedes it: the old RequestId can then only answer "stale".
  * complete(request_id) answers exactly one of: "ok" (the outstanding request, first time), "duplicate" (that request already completed),
    "stale" (a request that was superseded / cancelled / timed out), "unknown" (never issued by this client: a mismatch), "invalid" (not 16 bytes / zero).
    ONLY "ok" may release the official-jump state; everything else changes nothing.
  * a withdrawn / closed / re-published (generation or token changed) endpoint, a timeout, a generation boundary or the shutdown CANCEL the outstanding request.
    A cancelled request is never retried against another endpoint (contract 13.2 step 7) and is never guessed to be complete from the telemetry.
  * nothing here changes the scoring state: a refused send, a cancel and a timeout are reported (log + counters + last_failure) so that a stuck official
    jump is DETECTABLE; the caller decides what to do. The three ways an official jump can be left unreleased - a refused send, a timeout and an endpoint that
    was withdrawn / changed while the request was outstanding - are handed to the caller ONCE through take_unreleased() (the application then aborts that
    scoring session through its existing jump-abort path). A cancel that the application itself asks for (session end, generation boundary, shutdown,
    scoring abort) is never reported that way.
"""
import hmac
import secrets
import time
from collections import OrderedDict

import dataplane_contract as contract

OUTSTANDING_TIMEOUT_S = 10.0       # a completion normally arrives within one BVE tick; this only bounds a lost one
WATCH_INTERVAL_S = 0.25            # how often an outstanding request re-reads the directory
CLOSED_CAPACITY = 32               # bounded memory of finished request ids (duplicate / stale detection)

COMMANDS = (
    ("JUMP_STA_TIME:", contract.MSG_JUMP_STATION_TIME, contract.JUMP_CAP_STATION_TIME),
    ("JUMP_LOC_TIME:", contract.MSG_JUMP_LOCATION_TIME, contract.JUMP_CAP_LOCATION_TIME),
)

R_OK = "ok"
R_DUPLICATE = "duplicate"
R_STALE = "stale"
R_UNKNOWN = "unknown"
R_INVALID = "invalid"


class _Request(object):
    __slots__ = ("request_id", "message_type", "sent_at", "port", "generation", "token", "text")

    def __init__(self, request_id, message_type, sent_at, port, generation, token, text):
        self.request_id = request_id
        self.message_type = message_type
        self.sent_at = sent_at
        self.port = port
        self.generation = generation
        self.token = token
        self.text = text


class CurrentJumpClient(object):
    def __init__(self, bve_pid, instance, app_pid, send_datagram, source=None, log=None, clock=time.monotonic, id_factory=None,
                 timeout_s=OUTSTANDING_TIMEOUT_S):
        contract.jump_name(bve_pid)                       # validates the PID
        contract.telemetry_name(bve_pid, instance)        # validates the instance text
        if not isinstance(app_pid, int) or isinstance(app_pid, bool) or not 1 <= app_pid <= 0xFFFFFFFF:
            raise ValueError("app-pid")
        self.bve_pid = bve_pid
        self.instance = instance
        self.app_pid = app_pid
        self._send = send_datagram
        self._source = source
        self._log = log
        self._clock = clock
        self._new_id = id_factory or (lambda: secrets.token_bytes(16))
        self._timeout_s = timeout_s
        self._attached = False
        self._closed = False
        self._outstanding = None
        self._finished = OrderedDict()                    # request_id -> final state ("completed", "superseded", "timeout", ...)
        self._next_watch = 0.0
        self._logged = set()
        self.last_failure = None                          # the last reason a request ended WITHOUT a completion (timeout / endpoint-... / superseded ...)
        self._unreleased = None                           # the reason an official jump was left unreleased, until the application takes it (take_unreleased)
        self.counts = {"sent": 0, "completed": 0}
        self.reasons = {}

    # -- state -----------------------------------------------------------------------------------------------------------------------------------
    @property
    def outstanding_id(self):
        return None if self._outstanding is None else self._outstanding.request_id

    @property
    def has_outstanding(self):
        return self._outstanding is not None

    def _count(self, key):
        self.reasons[key] = self.reasons.get(key, 0) + 1

    def _emit(self, line, once_key=None):
        if self._log is None:
            return
        if once_key is not None:
            if once_key in self._logged:
                return
            self._logged.add(once_key)
        try:
            self._log(line)
        except Exception:
            pass

    @staticmethod
    def _short(request_id):
        return bytes(request_id)[:4].hex()

    # -- the directory ---------------------------------------------------------------------------------------------------------------------------
    def _detach(self):
        if self._source is not None:
            try:
                self._source.close()
            except Exception:
                pass
        self._attached = False

    def _read_directory(self):
        """(snapshot dict, None) or (None, reason). Never raises."""
        try:
            if self._source is None:
                import managed_app_directory
                self._source = managed_app_directory.Win32DirectorySource(contract.DIRECTORY_SIZE)
            if not self._attached:
                if not self._source.open(contract.jump_name(self.bve_pid)):
                    return None, "jump-directory-missing"
                self._attached = True
            for _attempt in range(3):
                first = self._source.read()
                second = self._source.read()
                if first is None or second is None:
                    self._detach()
                    return None, "jump-directory-closed"
                if first != second:
                    continue
                try:
                    return contract.decode_jump_directory(first), None
                except ValueError as exc:
                    if str(exc) == "sequence":
                        continue
                    return None, "jump-directory-invalid:" + str(exc)
            return None, "jump-directory-torn"
        except Exception as exc:
            self._detach()
            return None, "jump-directory-error:" + type(exc).__name__

    @staticmethod
    def _usable(snapshot):
        return (snapshot["state"] & (contract.PUBLISHED | contract.READY)) == (contract.PUBLISHED | contract.READY) \
            and not snapshot["state"] & (contract.WITHDRAWING | contract.CLOSED)

    # -- sending ---------------------------------------------------------------------------------------------------------------------------------
    def _refuse(self, reason, text):
        self._count("refused:" + reason)
        self.last_failure = "send-refused:" + reason
        self._unreleased = self.last_failure
        self._emit("[JUMP] event=send-refused reason=%s" % reason, once_key="refused:" + reason)
        return None

    def send(self, text):
        """Sends one jump command. Returns the 16-byte RequestId, or None when the command could NOT be sent (the reason is counted and logged once)."""
        if self._closed:
            return self._refuse("client-closed", text)
        kind = None
        for prefix, message_type, capability in COMMANDS:
            if isinstance(text, str) and text.startswith(prefix):
                kind = (message_type, capability)
                break
        if kind is None:
            return self._refuse("unknown-command", text)
        snapshot, reason = self._read_directory()
        if snapshot is None:
            return self._refuse(reason, text)
        if snapshot["bve_pid"] != self.bve_pid:
            return self._refuse("bve-pid-mismatch", text)
        if not self._usable(snapshot):
            self._detach()                                  # a closed / withdrawn publication: re-open next time (a re-created endpoint is a new mapping)
            return self._refuse("jump-endpoint-not-usable", text)
        message_type, capability = kind
        if not snapshot["capabilities"] & contract.JUMP_CAP_REQUEST_ID:
            return self._refuse("request-id-unsupported", text)
        if not snapshot["capabilities"] & capability:
            return self._refuse("command-unsupported", text)

        if self._outstanding is not None:
            self._finish(self._outstanding, "superseded")
        request_id = self._new_id()
        while len(request_id) != 16 or not any(request_id) or request_id in self._finished:
            request_id = self._new_id()
        try:
            datagram = contract.encode_envelope(message_type, self.bve_pid, self.app_pid, snapshot["generation"], self.instance,
                                                snapshot["token"], request_id, text.encode("utf-8"))
            accepted = self._send(datagram, snapshot["port"])
        except Exception:
            accepted = False
        if accepted is False or (isinstance(accepted, int) and accepted < 0):
            return self._refuse("send-failed", text)
        self._outstanding = _Request(request_id, message_type, self._clock(), snapshot["port"], snapshot["generation"], bytes(snapshot["token"]), text)
        self._next_watch = self._clock() + WATCH_INTERVAL_S
        self._unreleased = None                             # a command is on its way again: nothing is left over from an earlier refusal
        self.counts["sent"] += 1
        self._emit("[JUMP] event=command-sent id=%s type=0x%x port=%d gen=%d" % (self._short(request_id), message_type, snapshot["port"], snapshot["generation"]))
        return request_id

    # -- completion ------------------------------------------------------------------------------------------------------------------------------
    def complete(self, request_id):
        """The JUMP_COMPLETE of `request_id` arrived through the Telemetry receiver. Returns R_OK only for the outstanding request."""
        try:
            request_id = bytes(request_id)
        except Exception:
            request_id = b""
        if len(request_id) != 16 or not any(request_id):
            return self._rejected(R_INVALID, request_id)
        current = self._outstanding
        if current is not None and hmac.compare_digest(current.request_id, request_id):
            self._finish(current, "completed")
            self.counts["completed"] += 1
            self._emit("[JUMP] event=complete-accepted id=%s" % self._short(request_id))
            return R_OK
        state = self._finished.get(request_id)
        if state is None:
            return self._rejected(R_UNKNOWN, request_id)
        return self._rejected(R_DUPLICATE if state == "completed" else R_STALE, request_id)

    def _rejected(self, result, request_id):
        self._count("complete-" + result)
        self._emit("[JUMP] event=complete-rejected result=%s id=%s" % (result, self._short(request_id) if request_id else "-"), once_key="complete-" + result)
        return result

    def _finish(self, request, state):
        if self._outstanding is request:
            self._outstanding = None
        self._finished[request.request_id] = state
        while len(self._finished) > CLOSED_CAPACITY:
            self._finished.popitem(last=False)
        if state != "completed":
            self._count("ended:" + state)
            if state != "superseded":                       # a newer command replacing an older one is not a failure
                self.last_failure = state

    def cancel(self, reason):
        """Ends the outstanding request without a completion (generation boundary, endpoint change, shutdown). A later completion for it is stale."""
        request = self._outstanding
        if request is None:
            return False
        self._finish(request, reason)
        self._emit("[JUMP] event=request-cancelled id=%s reason=%s" % (self._short(request.request_id), reason))
        return True

    def poll(self):
        """Called from the application's periodic update. Detects a lost completion (timeout) and a withdrawn / re-published endpoint. Never raises."""
        request = self._outstanding
        if request is None or self._closed:
            return
        try:
            now = self._clock()
            if now - request.sent_at >= self._timeout_s:
                self._finish(request, "timeout")
                self._unreleased = "timeout"
                self._emit("[JUMP] event=timeout id=%s after=%.1fs (no JUMP_COMPLETE: the official jump stays unreleased)" % (self._short(request.request_id), now - request.sent_at))
                return
            if now < self._next_watch:
                return
            self._next_watch = now + WATCH_INTERVAL_S
            snapshot, reason = self._read_directory()
            if snapshot is None:
                if reason in ("jump-directory-closed", "jump-directory-missing") or reason.startswith("jump-directory-invalid"):
                    self._cancel_unreleased("endpoint-" + reason)
                return
            if not self._usable(snapshot):
                self._detach()
                self._cancel_unreleased("endpoint-withdrawn")
            elif snapshot["generation"] != request.generation or bytes(snapshot["token"]) != request.token:
                self._cancel_unreleased("endpoint-changed")
        except Exception:
            pass

    def _cancel_unreleased(self, reason):
        """A cancel that the CLIENT decided (the endpoint is gone): the official jump of this request can no longer be completed, the application is told."""
        if self.cancel(reason):
            self._unreleased = reason

    def take_unreleased(self):
        """The reason an official jump was left unreleased (refused send / timeout / endpoint withdrawn or changed), once; None when there is none."""
        reason, self._unreleased = self._unreleased, None
        return reason

    def summary(self):
        reasons = ",".join("%s:%d" % (k, self.reasons[k]) for k in sorted(self.reasons)) or "-"
        return "[JUMP] event=summary sent=%d completed=%d outstanding=%d reasons=%s" % (
            self.counts["sent"], self.counts["completed"], 1 if self._outstanding is not None else 0, reasons)

    def close(self):
        """Shutdown: the outstanding request is cancelled, the mapping is released. Idempotent."""
        if self._closed:
            return
        self.cancel("shutdown")
        self._closed = True
        self._detach()
