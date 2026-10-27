"""Phase SI-R2.2-S2a: the receiving contract of the sender's OFFTGT part (the target station the host itself names). Pure: no Qt, no Win32, no clock of its own.

The wire (one comma-free part of the telemetry line, nine colon-separated fields):

    OFFTGT:1:<s>:<idx>:<count>:<hash>:<loc>:<mb>:<mf>

    s      K known | T terminal (no station follows) | N no station list | U temporarily unavailable | F read failed. 'NONE' is not a wire word: the application
           treats T and N as one semantic class (NONE_CLASS).
    idx    K: 0 <= idx < count.  Every other word: -1.
    count  K, T: the length of the adopted station list.  N: 0.  U, F: syntax only (the sender's canonical value is -1).
    hash   8 hex digits; K, T: the list_id of the adopted station list.  N, U, F: syntax only (the sender's canonical value is 00000000).
    loc    K: the location the sender read; it must agree with the adopted list within LOC_TOLERANCE_M.  Every other word: -1.
    mb, mf K: the sender's margins, >= 0.  Every other word: -1.

Numbers are canonical decimal text only (no '+', no leading zero, no '-0', no trailing fraction zero, no exponent, no NaN / Infinity): one value, one spelling.

The order of the checks is the contract; the first one that fails decides (version before arity, range before scope):
    part missing -> ABSENT | version token -> version -> arity -> state word -> number syntax -> range / sentinel -> scope (3,000 ms grace) -> loc

This module only DECIDES. It keeps no last-known value (a U is never replaced by an earlier K), falls back to nothing (no machine target, no STIDX target, no distance search, no
nearest station, no door state) and reads nothing of the HUD or the scoring. The clock is injected (evaluate / advance take the elapsed / current milliseconds).
"""
import re

PART_NAME = "OFFTGT"
WIRE_VERSION = 1
FIELD_COUNT = 9
STATE_WORDS = ("K", "T", "N", "U", "F")
LOC_TOLERANCE_M = 0.01
LIST_GRACE_MS = 3000

KNOWN, NONE_TERMINAL, NONE_EMPTY, UNAVAILABLE, READ_FAILED = "KNOWN", "NONE_TERMINAL", "NONE_EMPTY", "UNAVAILABLE", "READ_FAILED"
ABSENT, INVALID, NOT_INITIALIZED = "ABSENT", "INVALID", "NOT_INITIALIZED"
NONE_CLASS = (NONE_TERMINAL, NONE_EMPTY)
WIRE_TO_STATE = {"K": KNOWN, "T": NONE_TERMINAL, "N": NONE_EMPTY, "U": UNAVAILABLE, "F": READ_FAILED}

R_OK, R_NONE_TERMINAL, R_NONE_EMPTY, R_UNAVAILABLE, R_READ_FAILED = "off-ok", "off-none-terminal", "off-none-empty", "off-unavailable", "off-read-failed"
R_MISSING, R_VERSION, R_MALFORMED, R_RANGE = "off-missing", "off-version", "off-malformed", "off-range"
R_MISMATCH, R_NOT_READY, R_LOC = "off-list-mismatch", "off-not-ready", "off-loc"
STATE_REASON = {KNOWN: R_OK, NONE_TERMINAL: R_NONE_TERMINAL, NONE_EMPTY: R_NONE_EMPTY, UNAVAILABLE: R_UNAVAILABLE, READ_FAILED: R_READ_FAILED}

_INT32_MIN, _INT32_MAX = -2147483648, 2147483647
_INT = re.compile(r"0|-?[1-9][0-9]{0,10}")
_REAL = re.compile(r"-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{0,16}[1-9])?")
_HASH = re.compile(r"[0-9A-Fa-f]{8}")


def is_none_class(state):
    """T and N are one semantic class for the application (no station to show); the wire keeps them apart."""
    return state in NONE_CLASS


def _result(state, reason, index=-1, location=-1.0, margin_b=-1.0, margin_f=-1.0):
    return {"official_state": state, "official_index": index, "official_location": location,
            "official_margin_b": margin_b, "official_margin_f": margin_f, "official_reason": reason}


def initial_state():
    """The published values before the first line of a generation is judged: NOT_INITIALIZED, every number the sentinel."""
    return _result(NOT_INITIALIZED, R_NOT_READY)


def _int(token):
    if _INT.fullmatch(token) is None:
        return None
    value = int(token)
    return value if _INT32_MIN <= value <= _INT32_MAX else None


def _real(token):
    if token == "-0" or _REAL.fullmatch(token) is None:
        return None
    return float(token)


def capture(parts):
    """The first part of an already split telemetry line that names OFFTGT ('OFFTGT' alone or 'OFFTGT:...'); None when there is none. A later duplicate is ignored."""
    for part in parts:
        if part == PART_NAME or part.startswith(PART_NAME + ":"):
            return part
    return None


def decode(text):
    """One OFFTGT part -> (fields, None), or (None, reason) for off-version / off-malformed. Checks syntax only: nothing of the adopted list, no range, no scope."""
    fields = text.split(":")
    if fields[0] != PART_NAME or len(fields) < 2:
        return None, R_MALFORMED
    version = _int(fields[1])
    if version is None:
        return None, R_MALFORMED
    if version != WIRE_VERSION:
        return None, R_VERSION
    if len(fields) != FIELD_COUNT or fields[2] not in STATE_WORDS:
        return None, R_MALFORMED
    idx, count = _int(fields[3]), _int(fields[4])
    loc, margin_b, margin_f = _real(fields[6]), _real(fields[7]), _real(fields[8])
    if None in (idx, count, loc, margin_b, margin_f) or _HASH.fullmatch(fields[5]) is None:
        return None, R_MALFORMED
    return {"state": fields[2], "idx": idx, "count": count, "hash": fields[5].upper(), "loc": loc, "mb": margin_b, "mf": margin_f}, None


def _in_range(wire):
    state = wire["state"]
    if state == "K":
        return 0 <= wire["idx"] < wire["count"] and wire["mb"] >= 0 and wire["mf"] >= 0
    if wire["idx"] != -1 or wire["loc"] != -1 or wire["mb"] != -1 or wire["mf"] != -1:
        return False
    if state == "N":
        return wire["count"] == 0
    if state == "T":
        return wire["count"] >= 1
    return True


def _in_scope(wire, station_list, list_id):
    state = wire["state"]
    if state == "N":
        return len(station_list) == 0
    return list_id is not None and wire["count"] == len(station_list) and wire["hash"] == str(list_id).upper()


def evaluate(raw, station_list, list_id, mismatch_elapsed_ms):
    """Judges one captured part against the station list the application has adopted -> (the six published values as a dict, scope_ok).

    raw                  the part text, or None when the line carried no OFFTGT part
    station_list         the adopted list (entries have a 'location'); list_id its identity (None = it has none)
    mismatch_elapsed_ms  how long the scope (K, T, N) has already disagreed with the adopted list (0 at the first disagreement)
    scope_ok             False while a K / T / N does not fit the adopted list: the caller keeps (or starts) the grace timer; True discards it
    """
    if raw is None:
        return _result(ABSENT, R_MISSING), True
    wire, why = decode(raw)
    if wire is None:
        return _result(INVALID, why), True
    if not _in_range(wire):
        return _result(INVALID, R_RANGE), True
    state = wire["state"]
    if state in ("K", "T", "N") and not _in_scope(wire, station_list, list_id):
        if mismatch_elapsed_ms > LIST_GRACE_MS:
            return _result(INVALID, R_MISMATCH), False
        return _result(NOT_INITIALIZED, R_NOT_READY), False
    if state == "K":
        listed = station_list[wire["idx"]]["location"]
        if abs(listed - wire["loc"]) > LOC_TOLERANCE_M:
            return _result(INVALID, R_LOC), True
        return _result(KNOWN, R_OK, wire["idx"], listed, wire["mb"], wire["mf"]), True
    published = WIRE_TO_STATE[state]
    return _result(published, STATE_REASON[published]), True


def advance(raw, station_list, list_id, since_ms, now_ms):
    """One judgement with the grace timer folded in -> (the six published values, the new timer start in ms or None).

    since_ms is when the scope first disagreed (None = it agrees / has not been judged); now_ms is the caller's clock. Never raises: an internal error is
    NOT_INITIALIZED and the timer is left as it was."""
    try:
        elapsed = 0.0 if since_ms is None else now_ms - since_ms
        result, scope_ok = evaluate(raw, station_list, list_id, elapsed)
        if scope_ok:
            return result, None
        return result, (now_ms if since_ms is None else since_ms)
    except Exception:
        return initial_state(), since_ms


def timer_after_scenario(since_ms, previous_scenario, scenario):
    """A different scenario starts its grace over: the timer is dropped when the scenario id changed since the last judgement."""
    return None if scenario != previous_scenario else since_ms
