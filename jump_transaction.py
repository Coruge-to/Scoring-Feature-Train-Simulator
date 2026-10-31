"""Phase PID-D4JA StationIndex ST-3d - the PURE layer of the official Jump transaction of the application (no Qt, no Win32, no socket, no file, no clock, no global state).

The transaction is one request and its answer:
  request     the application writes the official Jump (a scoring start or a retry) as the Jump wire v2 text, and keeps WHAT it asked for in a JumpExpectation
              (command kind, StationIndex, scope, requested position, time, RequestId, when it was sent);
  completion  the sender answers with a completion v2 (kind, selected index, the position read back after the jump, scope); transport (the RequestId of the envelope) and
              settlement (does the answer prove the request?) are two different things: a completion that the transport accepted still has to be judged;
  settlement  judge_completion answers success ONLY when every check holds (the AND of the checks, in a fixed order); every other answer names the first check that failed.

What this module does not do: it changes no state, sends nothing, cuts no history (the cut is station_identity.resolve_retry_history, applied by the one success branch of the application), and
writes no log line (settled_event only builds the fields of the one final diagnostic line of a transaction).

The wire is the one of jump_wire.py (the shared codec; this module never parses or formats a number or a command itself). Positions are compared as doubles, EXACTLY: the same canonical
codec is on both sides of the wire, so a request at x comes back as x (the owner decision of ST-3; a tolerance would be a way to accept a jump to the wrong place).
"""
import hmac
from typing import NamedTuple, Optional

import jump_wire
import station_identity

NO_INDEX = station_identity.NO_INDEX

# -- the purpose of a transaction ------------------------------------------------------------------------------------------------------------------
JUMP_RETRY = "retry"                 # the retry to a checkpoint: a formal success cuts the history to that checkpoint
JUMP_START = "start"                 # the scoring start: the history is never cut
JUMP_TURNBACK = "turnback"           # the pseudo-turnback Jump A -> B (Stage TB-C): the history is never cut, the B checkpoint is created by the chain after the completion proved the request
JUMPS = (JUMP_RETRY, JUMP_START, JUMP_TURNBACK)

# -- the words a transaction ends with (fixed words; they contain no value, no name and no path) ----------------------------------------------------
SETTLE_OK = "ok"                                          # formal success (managed: the RequestId is proven)
SETTLE_OK_PLAIN = "ok-plain"                              # the plain (normal) mode: every check but the RequestId holds; nothing is cut, nothing is settled formally
SETTLE_MALFORMED = "malformed-completion"
SETTLE_VERSION = "unsupported-completion-version"
SETTLE_REQUEST_ID = "request-id-mismatch"
SETTLE_KIND = "command-kind-mismatch"
SETTLE_SELECTED = "selected-index-mismatch"
SETTLE_SCOPE = "scope-mismatch"
SETTLE_REQUESTED_LOCATION = "requested-location-mismatch"
SETTLE_ACTUAL_LOCATION = "actual-location-mismatch"
SETTLE_SCENARIO = "scenario-changed"
SETTLE_HISTORY = "history-unresolvable"
SETTLE_UNSOLICITED = "unsolicited"
SETTLE_TIMEOUT = "timeout"
SETTLE_SEND_REFUSED = "send-refused"
SETTLE_ENDPOINT = "endpoint-gone"
SETTLE_CLEANUP = "cleanup"
SETTLE_SHUTDOWN = "shutdown"
SETTLE_INTERNAL = station_identity.INTERNAL_ERROR
SETTLE_WORDS = (SETTLE_OK, SETTLE_OK_PLAIN, SETTLE_MALFORMED, SETTLE_VERSION, SETTLE_REQUEST_ID, SETTLE_KIND, SETTLE_SELECTED, SETTLE_SCOPE, SETTLE_REQUESTED_LOCATION,
                SETTLE_ACTUAL_LOCATION, SETTLE_SCENARIO, SETTLE_HISTORY, SETTLE_UNSOLICITED, SETTLE_TIMEOUT, SETTLE_SEND_REFUSED, SETTLE_ENDPOINT, SETTLE_CLEANUP, SETTLE_SHUTDOWN,
                SETTLE_INTERNAL)

# -- what the transport said about the last completion of a transaction ----------------------------------------------------------------------------
LAST_NONE = "none"                   # no completion body has been seen
LAST_OK = "ok"                       # the transport accepted a completion for the outstanding request
LAST_STALE = "stale"                 # a completion of a request that was superseded / cancelled / timed out
LAST_DUPLICATE = "dup"               # a second completion of a request that was completed already
LAST_UNKNOWN = "unk"                 # a RequestId this application never issued
LAST_INVALID = "inv"                 # not a RequestId at all
_TRANSPORT_WORDS = {"ok": LAST_OK, "stale": LAST_STALE, "duplicate": LAST_DUPLICATE, "unknown": LAST_UNKNOWN, "invalid": LAST_INVALID}

COMMANDS = (jump_wire.KIND_STA, jump_wire.KIND_LOC)


class CompletionEvent(NamedTuple):
    """One completion body that the transport accepted and the settlement has not judged yet: the RequestId of its envelope (None in the plain mode) and its text (None when the
    intake itself failed: the settlement then takes the transaction to a failure)."""
    request_id: Optional[bytes]
    text: Optional[str]


def transport_word(result):
    """The short word of the answer of the transport (current_jump_client.complete) for the diagnostic; anything else is 'inv'."""
    return _TRANSPORT_WORDS.get(result, LAST_INVALID)


def release_word(raw):
    """The fixed word of the ending of a transaction for a reason that another part of the application named (the jump client, the session, the generation). Never raises."""
    if not isinstance(raw, str):
        return SETTLE_INTERNAL
    if raw in SETTLE_WORDS:
        return raw
    if raw.startswith("send-refused"):
        return SETTLE_SEND_REFUSED
    if raw.startswith("endpoint-"):
        return SETTLE_ENDPOINT
    if raw == "session-ended":
        return SETTLE_CLEANUP
    if raw == "generation":
        return SETTLE_SCENARIO
    return SETTLE_INTERNAL


# ==============================================================================================================================================
# the request
# ==============================================================================================================================================
class PlannedJump(NamedTuple):
    """One request that has been built and checked, not yet sent: the wire text, and the values that the answer is judged against. `location` is the value that is written
    (a signed zero is a zero)."""
    text: str
    command: str
    station_index: int
    scope: station_identity.StationScope
    location: float
    time_ms: int


def _request_refusal(reason):
    """The word of the application for a reason of the codec (the words the retry and the start already use)."""
    if not isinstance(reason, str):
        return station_identity.INTERNAL_ERROR
    if reason.startswith("location-"):
        return station_identity.LOCATION_INVALID
    if reason.startswith("time-"):
        return station_identity.TIME_INVALID
    if reason in (jump_wire.R_SCOPE_INCOMPLETE, jump_wire.R_SCENARIO_ID_SYNTAX, jump_wire.R_SCENARIO_ID_RANGE, jump_wire.R_LIST_ID_SYNTAX, jump_wire.R_COUNT_SYNTAX,
                  jump_wire.R_COUNT_RANGE):
        return station_identity.SCOPE_INCOMPLETE
    if reason.startswith("station-index-"):
        return station_identity.INDEX_OUT_OF_RANGE
    return station_identity.INTERNAL_ERROR


def build_jump_request(command, station_index, time_ms, scope, location):
    """(PlannedJump, None) for the v2 request of `command` (STA / LOC) at `station_index` of `scope`, else (None, reason). The text is written by the shared codec and nowhere else; the
    reason is one of the words the retry and the scoring start refuse with. Nothing here raises."""
    try:
        triple = None if scope is None else tuple(scope)
        text, why = jump_wire.format_request_v2(command, station_index, time_ms, triple, location)
        if why is not None:
            return None, _request_refusal(why)
        normalized, why = jump_wire.normalize_location(location)
        scope_value = station_identity.make_scope(*triple)
        if why is not None or scope_value is None:
            return None, station_identity.INTERNAL_ERROR
        return PlannedJump(text, command, station_index, scope_value, normalized, time_ms), None
    except Exception:
        return None, station_identity.INTERNAL_ERROR


class JumpExpectation(NamedTuple):
    """What an open transaction asked for (immutable; a change is a new value). `request_id` is None in the plain (normal) mode, which has none and can prove none. `sent_at` is the
    monotonic time of the send. `received` counts the completion bodies seen for this transaction (the transport's stale / duplicate answers included, as 0 or 1) and `last` is the
    transport's last word about them."""
    purpose: str
    command: str
    request_id: Optional[bytes]
    station_index: int
    scope: station_identity.StationScope
    location: float
    time_ms: int
    sent_at: float
    received: int
    last: str


def make_expectation(purpose, planned, request_id, sent_at):
    """The expectation of a request that was sent (the answer of the sender, a RequestId in the managed mode, is judged against it)."""
    return JumpExpectation(purpose, planned.command, None if request_id is None else bytes(request_id), planned.station_index, planned.scope, planned.location, planned.time_ms,
                           float(sent_at), 0, LAST_NONE)


def with_completion_seen(expectation, last):
    """The expectation after the transport reported a completion body for it (its word `last`); the same expectation when it is not one."""
    if not isinstance(expectation, JumpExpectation):
        return expectation
    return expectation._replace(received=1, last=last)


# ==============================================================================================================================================
# the settlement
# ==============================================================================================================================================
class SettleVerdict(NamedTuple):
    """The answer of judge_completion. `ok` False names the first failed check in `reason`; `formal` is True only for a success whose RequestId is proven (the only success that may cut
    a history). `selected_idx` / `actual_location` are what the completion said (NO_INDEX / None when it said nothing usable): diagnostics."""
    ok: bool
    reason: str
    selected_idx: int
    actual_location: Optional[float]
    formal: bool


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value == value and value not in (float("inf"), float("-inf"))


def _no(reason, selected=NO_INDEX, actual=None):
    return SettleVerdict(False, reason, selected, actual, False)


def judge_completion(expectation, completion, request_id, current_scope, listed_location):
    """The settlement of one completion. Success is the AND of: the completion was read as a v2 completion, the RequestId is the one of the request (managed mode), the command kind, the
    selected index, the scope, the requested position (the position that the adopted station list holds NOW for the requested index: `listed_location`), the actual position (read back
    after the jump) and the scenario / list still being the one of the request (`current_scope`). The first check that fails names the reason; nothing is compared with a tolerance.

    completion   a jump_wire.JumpCompletion, or None when the text was not a completion
    request_id   the RequestId of the envelope that carried it (None in the plain mode)
    Never raises: whatever can not be judged is a failure."""
    try:
        return _judge(expectation, completion, request_id, current_scope, listed_location)
    except Exception:
        return _no(SETTLE_INTERNAL)


def _judge(expectation, completion, request_id, current_scope, listed_location):
    if not isinstance(expectation, JumpExpectation):
        return _no(SETTLE_UNSOLICITED)
    if completion is None:
        return _no(SETTLE_MALFORMED)
    selected = completion.selected_idx if station_identity._is_int(getattr(completion, "selected_idx", None)) else NO_INDEX
    actual = completion.location if _finite(getattr(completion, "location", None)) else None
    if getattr(completion, "version", None) != jump_wire.V2:
        return _no(SETTLE_VERSION, selected, actual)
    if expectation.request_id is not None:
        if not isinstance(request_id, (bytes, bytearray)) or not hmac.compare_digest(bytes(request_id), expectation.request_id):
            return _no(SETTLE_REQUEST_ID, selected, actual)
    if completion.kind != expectation.command:
        return _no(SETTLE_KIND, selected, actual)
    if selected != expectation.station_index:
        return _no(SETTLE_SELECTED, selected, actual)
    if completion.scope is None or tuple(completion.scope) != tuple(expectation.scope):
        return _no(SETTLE_SCOPE, selected, actual)
    if not _finite(listed_location) or listed_location != expectation.location:
        return _no(SETTLE_REQUESTED_LOCATION, selected, actual)
    if actual is None or actual != expectation.location:
        return _no(SETTLE_ACTUAL_LOCATION, selected, actual)
    if current_scope is None or tuple(current_scope) != tuple(expectation.scope):
        return _no(SETTLE_SCENARIO, selected, actual)
    formal = expectation.request_id is not None
    return SettleVerdict(True, SETTLE_OK if formal else SETTLE_OK_PLAIN, selected, actual, formal)


# ==============================================================================================================================================
# the one final diagnostic line
# ==============================================================================================================================================
# The Caller keeps 160 characters of an application line; "[MANAGED] event=jump-settled pid=4294967295" (the longest pid) takes 43 of them. The fields are added in the order of their
# priority and a field that does not fit is left out, so that the end of the transaction and the items that find the request again (the id of the C# lines, the index, the scope with its
# count, the position, the command, the age, whether a completion was seen and what the transport said) survive the longest reason words.
SETTLED_FIELD_BUDGET = 160 - 43


def _location_text(value):
    if not _finite(value):
        return "bad"
    text, why = jump_wire.format_location(value)
    return text if why is None else "bad"


def settled_event(expectation, end, now, selected_idx=None, actual_location=None, history=None, retry_count=None):
    """("jump-settled", fields) - the ONE final diagnostic line of a transaction. Fixed words and numbers only (no raw body, no path, no token, no station name).

      end   how it ended (a word of SETTLE_WORDS; any other value is shown as internal-error)
      id    the first four bytes of the RequestId as 8 lower case hex digits (the form of the "id=" of the senders' lines and of the jump client); '-' = none (plain mode)
      ri    the requested StationIndex           sc  scenario:list:count of the request     rl  the requested position (canonical)     cmd  STA / LOC
      age   seconds since the send               comp  1 when a completion body was seen    lv  what the transport said last (none / ok / stale / dup / unk / inv)   kind  retry / start
      si / al  the selected index / the position that the completion said (when it said one)       h  history length before/after       c  the retry count
    Never raises."""
    try:
        word = end if end in SETTLE_WORDS else SETTLE_INTERNAL
        fields = [("end", word)]
        if isinstance(expectation, JumpExpectation):
            request_id = expectation.request_id
            fields += [("id", bytes(request_id)[:4].hex() if request_id else "-"), ("ri", str(expectation.station_index)), ("sc", station_identity._scope_text(expectation.scope)),
                       ("rl", _location_text(expectation.location)), ("cmd", expectation.command),
                       ("age", "%.1f" % max(0.0, float(now) - expectation.sent_at) if _finite(now) else "-"), ("comp", "1" if expectation.received else "0"),
                       ("lv", expectation.last), ("kind", expectation.purpose)]
        else:
            fields.append(("kind", "none"))
        if history is not None:
            fields.append(("h", "%d/%d" % (history[0], history[1])))
        if station_identity._is_int(retry_count):
            fields.append(("c", str(retry_count)))
        if station_identity._is_int(selected_idx) and selected_idx >= 0:
            fields.append(("si", str(selected_idx)))
        if actual_location is not None and _finite(actual_location):
            fields.append(("al", _location_text(actual_location)))
        chosen = {}
        used = 0
        for key, value in fields:
            cost = 1 + len(key) + 1 + len(value)
            if used + cost <= SETTLED_FIELD_BUDGET:
                chosen[key] = value
                used += cost
        return "jump-settled", chosen
    except Exception:
        return "jump-settled", {"end": SETTLE_INTERNAL}
