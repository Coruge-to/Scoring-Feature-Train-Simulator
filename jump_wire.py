"""Phase PID-D4JA StationIndex ST-3a - the Jump wire codec (pure: no Qt, no Win32, no socket, no file, no clock, no locale, no global state, no product module).

What this module is
  * the grammar of the official Jump command and of its completion, READ in version 1 and READ / WRITTEN in version 2;
  * the typed, immutable result of reading one message, or a fixed reason word (nothing here raises for a bad input);
  * the one place that spells a Jump position as text and reads it back EXACTLY (the same IEEE-754 double on both sides of the wire).
  ST-3a only fixes the contract. Nothing in the application imports this module yet: the senders / readers are wired in ST-3b (Current), ST-3c (Legacy), ST-3d (Python).

The wire (the body of the datagram; separator ":"; ASCII; no whitespace; no terminator). The version is the FIELD COUNT (W1: Directory, Envelope and capability bits are unchanged):

    request v1 (read only)   JUMP_STA_TIME:<idx>:<time_ms>                         JUMP_LOC_TIME:<location>:<time_ms>                              3 fields
    request v2               JUMP_STA_TIME:<idx>:<time_ms>:<scenario_id>:<list_id>:<count>:<location>
                             JUMP_LOC_TIME:<location>:<time_ms>:<scenario_id>:<list_id>:<count>:<idx>                                              7 fields
    completion v1 (read)     JUMP_COMPLETE:<STA|LOC>:<idx or -1>:<location>:<time_ms>:<jump_count>                                                6 fields
    completion v2            JUMP_COMPLETE:<STA|LOC>:<selected_idx>:<location>:<time_ms>:<jump_count>:<scenario_id>:<list_id>:<count>            9 fields

  The RequestId of a command is NOT in the body: it is the 16 byte field of the Envelope (v1 datagram header) and is echoed by the sender in the Envelope of the completion.
  Meaning of the fields: idx / selected_idx = StationIndex of the scope (v2: 0 <= idx < count, an LOC request carries the index too); location = the requested position (request)
  or the position read back after the jump (completion); (scenario_id, list_id, count) = the scope in which an index means anything; jump_count = the sender's JUMP counter.
  A v1 message has no scope: it can not carry a StationIndex that means anything (a v1 LOC request has no index at all). Whether v1 is still accepted is decided by the callers
  (ST-3: a formal transaction needs v2). There is no v1 writer on purpose.

Fields
  integers     0 | -?[1-9][0-9]*   (no sign '+', no leading zero, no space); a value outside Int32 is "<field>-range"; v2: time_ms >= 0, scenario_id >= 0, count >= 1, jump_count >= 0
  list_id      exactly 8 characters 0-9 A-F (upper case): the CRC-32 of the STALIST payload (the list identity of the STIDX unit)
  location     -?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?  with at most 17 significant digits, |x| <= 1e9 and (x == 0 or |x| >= 1e-9). NaN, Infinity, a decimal comma, a space,
               a hex / underscore / full width form are syntax errors. The value is the correctly rounded double (Python float() is the reference). -0.0 is normalised to +0.0
               (a signed zero has no meaning for a position). The writer produces the canonical text: the shortest text that reads back to the same double, no exponent unless
               the magnitude is below 1e-4, no ".0", "E" upper case ("0", "1000", "1234.5678", "1.5E-05").

Reading order (the first failing step gives the reason): empty -> prefix -> field-count -> kind (completion) -> the syntax of every field in textual order -> the ranges in this
order: v2 request time, scenario_id, count, location, index; v2 completion time, jump_count, scenario_id, count, location, selected_idx (v1: time, jump_count, location, index).
Every function returns (value, None) or (None, reason); the reason words are REASONS. tests/jump_wire_vectors.json is the shared specification (the C# twin is
Telemetry/Shared/JumpWire.cs); a position is never used to choose a station: the codec has no station list.
"""
import math
import re
from types import MappingProxyType
from typing import NamedTuple, Optional

from station_identity import StationScope

V1 = 1
V2 = 2
KIND_STA = "STA"
KIND_LOC = "LOC"
PREFIX_STA = "JUMP_STA_TIME"
PREFIX_LOC = "JUMP_LOC_TIME"
PREFIX_COMPLETE = "JUMP_COMPLETE"
INT32_MAX = 2147483647
INT32_MIN = -2147483648
LOCATION_MAX_ABS = 1.0e9
LOCATION_MIN_ABS = 1.0e-9
MAX_SIGNIFICANT_DIGITS = 17

# -- the reason words (fixed; they contain no value) ------------------------------------------------------------------------------------------------
R_EMPTY = "empty"
R_PREFIX = "prefix"
R_FIELD_COUNT = "field-count"
R_KIND = "kind"
R_STATION_INDEX_SYNTAX = "station-index-syntax"
R_SELECTED_IDX_SYNTAX = "selected-idx-syntax"
R_TIME_SYNTAX = "time-syntax"
R_SCENARIO_ID_SYNTAX = "scenario-id-syntax"
R_LIST_ID_SYNTAX = "list-id-syntax"
R_COUNT_SYNTAX = "count-syntax"
R_LOCATION_SYNTAX = "location-syntax"
R_LOCATION_PRECISION = "location-precision"
R_JUMP_COUNT_SYNTAX = "jump-count-syntax"
R_TIME_RANGE = "time-range"
R_JUMP_COUNT_RANGE = "jump-count-range"
R_SCENARIO_ID_RANGE = "scenario-id-range"
R_COUNT_RANGE = "count-range"
R_LOCATION_RANGE = "location-range"
R_STATION_INDEX_RANGE = "station-index-range"
R_SELECTED_IDX_RANGE = "selected-idx-range"
R_SCOPE_INCOMPLETE = "scope-incomplete"
REASONS = (R_EMPTY, R_PREFIX, R_FIELD_COUNT, R_KIND, R_STATION_INDEX_SYNTAX, R_SELECTED_IDX_SYNTAX, R_TIME_SYNTAX, R_SCENARIO_ID_SYNTAX, R_LIST_ID_SYNTAX, R_COUNT_SYNTAX,
           R_LOCATION_SYNTAX, R_LOCATION_PRECISION, R_JUMP_COUNT_SYNTAX, R_TIME_RANGE, R_JUMP_COUNT_RANGE, R_SCENARIO_ID_RANGE, R_COUNT_RANGE, R_LOCATION_RANGE,
           R_STATION_INDEX_RANGE, R_SELECTED_IDX_RANGE, R_SCOPE_INCOMPLETE)

_INT = re.compile(r"0|-?[1-9][0-9]*")
_LIST_ID = re.compile(r"[0-9A-F]{8}")
_LOCATION = re.compile(r"(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?)([0-9]+))?")
_OVERFLOW = 2 ** 40                      # stands for "an integer text longer than 11 characters": far outside Int32, never converted (Python limits int() of a long text)

# -- the field layouts: (name, parser) in TEXTUAL order -----------------------------------------------------------------------------------------------
_INT_FIELD, _LIST_FIELD, _LOC_FIELD = "int", "list", "loc"
_LAYOUT_REQ_V1_STA = (("station-index", _INT_FIELD), ("time", _INT_FIELD))
_LAYOUT_REQ_V1_LOC = (("location", _LOC_FIELD), ("time", _INT_FIELD))
_LAYOUT_REQ_V2_STA = (("station-index", _INT_FIELD), ("time", _INT_FIELD), ("scenario-id", _INT_FIELD), ("list-id", _LIST_FIELD), ("count", _INT_FIELD), ("location", _LOC_FIELD))
_LAYOUT_REQ_V2_LOC = (("location", _LOC_FIELD), ("time", _INT_FIELD), ("scenario-id", _INT_FIELD), ("list-id", _LIST_FIELD), ("count", _INT_FIELD), ("station-index", _INT_FIELD))
_LAYOUT_COMP_V1 = (("selected-idx", _INT_FIELD), ("location", _LOC_FIELD), ("time", _INT_FIELD), ("jump-count", _INT_FIELD))
_LAYOUT_COMP_V2 = _LAYOUT_COMP_V1 + (("scenario-id", _INT_FIELD), ("list-id", _LIST_FIELD), ("count", _INT_FIELD))
_RANGE_ORDER_REQ_V1 = ("time", "location", "station-index")
_RANGE_ORDER_REQ_V2 = ("time", "scenario-id", "count", "location", "station-index")
_RANGE_ORDER_COMP_V1 = ("time", "jump-count", "location", "selected-idx")
_RANGE_ORDER_COMP_V2 = ("time", "jump-count", "scenario-id", "count", "location", "selected-idx")
_SYNTAX_REASON = MappingProxyType({"station-index": R_STATION_INDEX_SYNTAX, "selected-idx": R_SELECTED_IDX_SYNTAX, "time": R_TIME_SYNTAX, "scenario-id": R_SCENARIO_ID_SYNTAX,
                                    "list-id": R_LIST_ID_SYNTAX, "count": R_COUNT_SYNTAX, "location": R_LOCATION_SYNTAX, "jump-count": R_JUMP_COUNT_SYNTAX})
_RANGE_REASON = MappingProxyType({"station-index": R_STATION_INDEX_RANGE, "selected-idx": R_SELECTED_IDX_RANGE, "time": R_TIME_RANGE, "scenario-id": R_SCENARIO_ID_RANGE,
                                  "count": R_COUNT_RANGE, "location": R_LOCATION_RANGE, "jump-count": R_JUMP_COUNT_RANGE})


class JumpRequest(NamedTuple):
    """One read request. v1: scope None, and station_index is None for LOC / location is None for STA. v2: everything set."""
    version: int
    kind: str
    station_index: Optional[int]
    time_ms: int
    location: Optional[float]
    scope: Optional[StationScope]


class JumpCompletion(NamedTuple):
    """One read completion. v1: scope None (and selected_idx may be -1 for LOC). v2: everything set, 0 <= selected_idx < scope.count."""
    version: int
    kind: str
    selected_idx: int
    location: float
    time_ms: int
    jump_count: int
    scope: Optional[StationScope]


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# -- location -------------------------------------------------------------------------------------------------------------------------------------------
def parse_location(text):
    """(float, None) for a location text, else (None, reason): location-syntax, location-precision (more than 17 significant digits) or location-range."""
    if not isinstance(text, str):
        return None, R_LOCATION_SYNTAX
    m = _LOCATION.fullmatch(text)
    if m is None:
        return None, R_LOCATION_SYNTAX
    negative, integer, fraction, exp_sign, exp_digits = m.groups()
    fraction = fraction or ""
    digits = (integer + fraction).lstrip("0")
    if not digits:
        return 0.0, None                                                    # a zero is a zero whatever its exponent, and never "-0.0"
    stripped = digits.rstrip("0")
    if len(stripped) > MAX_SIGNIFICANT_DIGITS:
        return None, R_LOCATION_PRECISION
    exp_digits = (exp_digits or "0").lstrip("0")
    if len(exp_digits) > 6:
        return None, R_LOCATION_RANGE
    exponent = int(exp_digits or "0")
    if exp_sign == "-":
        exponent = -exponent
    e10 = exponent - len(fraction) + (len(digits) - len(stripped))            # value = stripped * 10 ** e10
    order = len(stripped) + e10                                             # 10 ** (order - 1) <= |value| < 10 ** order
    if order > 10 or order < -8:
        return None, R_LOCATION_RANGE
    value = float(("-" if negative else "") + stripped + "e" + str(e10))      # float() of a text is correctly rounded
    if abs(value) > LOCATION_MAX_ABS or abs(value) < LOCATION_MIN_ABS:
        return None, R_LOCATION_RANGE
    return value, None


def normalize_location(value):
    """(float, None) for a number inside the position contract (-0.0 becomes 0.0), else (None, location-syntax) for a non-number or (None, location-range)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, R_LOCATION_SYNTAX
    try:
        x = float(value)
    except (OverflowError, ValueError):
        return None, R_LOCATION_RANGE
    if not math.isfinite(x):
        return None, R_LOCATION_RANGE
    if x == 0.0:
        return 0.0, None
    if abs(x) > LOCATION_MAX_ABS or abs(x) < LOCATION_MIN_ABS:
        return None, R_LOCATION_RANGE
    return x, None


def format_location(value):
    """(text, None): the canonical text of a position that reads back (parse_location) to exactly the same double; else (None, reason)."""
    x, reason = normalize_location(value)
    if reason is not None:
        return None, reason
    if x == 0.0:
        return "0", None
    mantissa, separator, exponent = repr(x).partition("e")                  # repr is the shortest text that reads back to x, locale independent
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    text = mantissa + ("E" + exponent if separator else "")
    back, reason = parse_location(text)
    if reason is not None or back != x:
        return None, R_LOCATION_RANGE
    return text, None


# -- scope ----------------------------------------------------------------------------------------------------------------------------------------------
def validate_scope(scenario_id, list_id, count):
    """(StationScope, None) when (scenario_id, list_id, count) is a scope a Jump may carry, else (None, reason): syntax words first (scenario-id, list-id, count), then ranges."""
    if not _is_int(scenario_id):
        return None, R_SCENARIO_ID_SYNTAX
    if not isinstance(list_id, str) or _LIST_ID.fullmatch(list_id) is None:
        return None, R_LIST_ID_SYNTAX
    if not _is_int(count):
        return None, R_COUNT_SYNTAX
    if scenario_id < 0 or scenario_id > INT32_MAX:
        return None, R_SCENARIO_ID_RANGE
    if count < 1 or count > INT32_MAX:
        return None, R_COUNT_RANGE
    return StationScope(scenario_id, list_id, count), None


# -- the shared checks ----------------------------------------------------------------------------------------------------------------------------------
def _int_value(text):
    return (-_OVERFLOW if text.startswith("-") else _OVERFLOW) if len(text) > 11 else int(text)


def _read_fields(layout, texts):
    """The syntax phase: {name: typed value}, or (None, reason) for the first field in textual order that is not of its form. A location out of range is kept
    as the pair (None, location-range) for the range phase."""
    values = {}
    for (name, form), text in zip(layout, texts):
        if form == _INT_FIELD:
            if _INT.fullmatch(text) is None:
                return None, _SYNTAX_REASON[name]
            values[name] = _int_value(text)
        elif form == _LIST_FIELD:
            if _LIST_ID.fullmatch(text) is None:
                return None, _SYNTAX_REASON[name]
            values[name] = text
        else:
            number, reason = parse_location(text)
            if reason in (R_LOCATION_SYNTAX, R_LOCATION_PRECISION):
                return None, reason
            values[name] = (number, reason)
    return values, None


def _check_ranges(order, values, version):
    """The range phase: None when every value is inside its contract, else the reason of the first failing field of `order`."""
    for name in order:
        if name == "location":
            if values[name][1] is not None:
                return R_LOCATION_RANGE
            continue
        v = values[name]
        if version == V1:
            ok = INT32_MIN <= v <= INT32_MAX
        elif name == "count":
            ok = 1 <= v <= INT32_MAX
        elif name in ("station-index", "selected-idx"):
            ok = 0 <= v < values["count"]
        else:
            ok = 0 <= v <= INT32_MAX
        if not ok:
            return _RANGE_REASON[name]
    return None


def _scope_of(values):
    return StationScope(values["scenario-id"], values["list-id"], values["count"])


# -- reading --------------------------------------------------------------------------------------------------------------------------------------------
def parse_request(text):
    """(JumpRequest, None) for a v1 (3 fields) or v2 (7 fields) request, else (None, reason)."""
    if not isinstance(text, str) or text == "":
        return None, R_EMPTY
    parts = text.split(":")
    if parts[0] == PREFIX_STA:
        kind = KIND_STA
    elif parts[0] == PREFIX_LOC:
        kind = KIND_LOC
    else:
        return None, R_PREFIX
    if len(parts) == 3:
        version = V1
        layout = _LAYOUT_REQ_V1_STA if kind == KIND_STA else _LAYOUT_REQ_V1_LOC
        order = _RANGE_ORDER_REQ_V1
    elif len(parts) == 7:
        version = V2
        layout = _LAYOUT_REQ_V2_STA if kind == KIND_STA else _LAYOUT_REQ_V2_LOC
        order = _RANGE_ORDER_REQ_V2
    else:
        return None, R_FIELD_COUNT
    values, reason = _read_fields(layout, parts[1:])
    if reason is not None:
        return None, reason
    order = tuple(n for n in order if n in values)
    reason = _check_ranges(order, values, version)
    if reason is not None:
        return None, reason
    location = values["location"][0] + 0.0 if "location" in values else None
    return JumpRequest(version, kind, values.get("station-index"), values["time"], location, _scope_of(values) if version == V2 else None), None


def parse_completion(text):
    """(JumpCompletion, None) for a v1 (6 fields) or v2 (9 fields) completion, else (None, reason)."""
    if not isinstance(text, str) or text == "":
        return None, R_EMPTY
    parts = text.split(":")
    if parts[0] != PREFIX_COMPLETE:
        return None, R_PREFIX
    if len(parts) == 6:
        version, layout, order = V1, _LAYOUT_COMP_V1, _RANGE_ORDER_COMP_V1
    elif len(parts) == 9:
        version, layout, order = V2, _LAYOUT_COMP_V2, _RANGE_ORDER_COMP_V2
    else:
        return None, R_FIELD_COUNT
    if parts[1] != KIND_STA and parts[1] != KIND_LOC:
        return None, R_KIND
    values, reason = _read_fields(layout, parts[2:])
    if reason is not None:
        return None, reason
    reason = _check_ranges(order, values, version)
    if reason is not None:
        return None, reason
    return JumpCompletion(version, parts[1], values["selected-idx"], values["location"][0] + 0.0, values["time"], values["jump-count"],
                          _scope_of(values) if version == V2 else None), None


# -- writing (v2 only) ----------------------------------------------------------------------------------------------------------------------------------
def _typed_fields(layout, given):
    """The format-side twin of _read_fields: the typed values of `given` in the form of `layout`, or (None, reason) of the first one that is not of its form."""
    values = {}
    for name, form in layout:
        v = given[name]
        if form == _INT_FIELD:
            if not _is_int(v):
                return None, _SYNTAX_REASON[name]
            values[name] = v
        elif form == _LIST_FIELD:
            if not isinstance(v, str) or _LIST_ID.fullmatch(v) is None:
                return None, _SYNTAX_REASON[name]
            values[name] = v
        else:
            number, reason = normalize_location(v)
            if reason == R_LOCATION_SYNTAX:
                return None, reason
            values[name] = (number, reason)
    return values, None


def _scope_triple(scope):
    if isinstance(scope, tuple) and len(scope) == 3:
        return scope
    return None


def format_request_v2(kind, station_index, time_ms, scope, location):
    """(text, None) for the v2 request of `kind` (STA / LOC) at `station_index` of `scope`, else (None, reason). The text is the one place a request is assembled."""
    if kind != KIND_STA and kind != KIND_LOC:
        return None, R_KIND
    triple = _scope_triple(scope)
    if triple is None:
        return None, R_SCOPE_INCOMPLETE
    layout = _LAYOUT_REQ_V2_STA if kind == KIND_STA else _LAYOUT_REQ_V2_LOC
    given = {"station-index": station_index, "time": time_ms, "scenario-id": triple[0], "list-id": triple[1], "count": triple[2], "location": location}
    values, reason = _typed_fields(layout, given)
    if reason is not None:
        return None, reason
    reason = _check_ranges(_RANGE_ORDER_REQ_V2, values, V2)
    if reason is not None:
        return None, reason
    text_location, reason = format_location(values["location"][0])
    if reason is not None:
        return None, reason
    texts = {"station-index": str(station_index), "time": str(time_ms), "scenario-id": str(triple[0]), "list-id": triple[1], "count": str(triple[2]), "location": text_location}
    return ":".join([PREFIX_STA if kind == KIND_STA else PREFIX_LOC] + [texts[name] for name, _form in layout]), None


def format_completion_v2(kind, selected_idx, location, time_ms, jump_count, scope):
    """(text, None) for the v2 completion of `kind` that selected `selected_idx` of `scope`, else (None, reason)."""
    if kind != KIND_STA and kind != KIND_LOC:
        return None, R_KIND
    triple = _scope_triple(scope)
    if triple is None:
        return None, R_SCOPE_INCOMPLETE
    given = {"selected-idx": selected_idx, "location": location, "time": time_ms, "jump-count": jump_count, "scenario-id": triple[0], "list-id": triple[1], "count": triple[2]}
    values, reason = _typed_fields(_LAYOUT_COMP_V2, given)
    if reason is not None:
        return None, reason
    reason = _check_ranges(_RANGE_ORDER_COMP_V2, values, V2)
    if reason is not None:
        return None, reason
    text_location, reason = format_location(values["location"][0])
    if reason is not None:
        return None, reason
    texts = {"selected-idx": str(selected_idx), "location": text_location, "time": str(time_ms), "jump-count": str(jump_count), "scenario-id": str(triple[0]),
             "list-id": triple[1], "count": str(triple[2])}
    return ":".join([PREFIX_COMPLETE, kind] + [texts[name] for name, _form in _LAYOUT_COMP_V2]), None
