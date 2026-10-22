"""Phase PID-D4JA StationIndex ST-2a - the IDENTITY of a station inside the application (pure: no Qt, no Win32, no socket, no file, no clock, no global state).

What this module is
  * the types and the pure checks that turn an index the sender supplied (STIDX: target index, arrival index) into a VERIFIED, IMMUTABLE identity snapshot;
  * the one place that knows when such an index may be used as the identity of a station, and when it may NOT (then a reason code says why).

The roles of the modules (owner decision of ST-2a)
  the STIDX unit        parses the wire, observes, diagnoses (it does not decide anything for the scoring);
  main.py               owns the identity state: it reads the observer ONLY through its public snapshot, compares it with the station list the application has
                        ADOPTED and publishes the verified result (Overlay._station_identity_sync is the single entrance);
  this module           scope, StationIndex, role, position, validity, fail-closed decisions, immutable types, pure functions;
  scoring_logic.py      uses ONLY verified snapshots (never the observer) for the checkpoints.

The scope of an index is (SCENARIO_ID, station list id, station count). The observer's own list generation counter, the Python ScenarioGeneration, the telemetry
epoch, the application instance and the BVE process id are other kinds of ownership / lifetime / diagnostics and are NEVER part of the scope.

A snapshot that is not valid never falls back: no station 0, no nearest station, no position 0.0. The caller decides what to refuse (the scoring start, the creation
of a checkpoint). Nothing here raises for a bad input: an invalid input is an invalid snapshot with a reason code.
"""
import math
from typing import NamedTuple, Optional

NO_INDEX = -1

# -- the roles a station can have in a snapshot ---------------------------------------------------------------------------------------------------
ROLE_SCORING_START = "scoring_start"          # the station the scoring was started at (the first checkpoint)
ROLE_ARRIVED_STATION = "arrived_station"      # a station the train arrived at (a later checkpoint)
ROLE_TARGET_STATION = "target_station"        # the station the sender's NEXT* values belong to (never stored in a checkpoint)
CHECKPOINT_ROLES = (ROLE_SCORING_START, ROLE_ARRIVED_STATION)
ROLES = CHECKPOINT_ROLES + (ROLE_TARGET_STATION,)

# -- the reason codes (fixed words; they contain no station name and no path) -----------------------------------------------------------------------
# (a different name space from the verdict words of the STIDX unit on purpose: those say what the WIRE is, these say what the application may DO with it)
OK = "ok"
NO_OBSERVER = "no-observer"                  # no STIDX line was ever received in this application instance
NOT_READY = "not-ready"                      # the last STIDX line was not judged good (not yet matching the list, malformed, version, range, ...)
NO_STATION_LIST = "no-station-list"          # the application has not adopted a station list that carries its identity
SCENARIO_MISMATCH = "scenario-mismatch"      # the observed scenario is not the scenario of the application
LIST_MISMATCH = "list-mismatch"              # the station list the index was written for is not the adopted one
COUNT_MISMATCH = "count-mismatch"            # the number of stations differs
INDEX_NEGATIVE = "index-negative"            # the sender says "none" (-1) or a value below it
INDEX_OUT_OF_RANGE = "index-out-of-range"    # index >= count
LOCATION_INVALID = "location-invalid"        # the adopted entry has no finite position
LOCATION_MISMATCH = "location-mismatch"      # the position of the adopted entry and the position the application observes disagree
ROLE_MISMATCH = "role-mismatch"              # the role is not one of the roles of the contract
SCOPE_INCOMPLETE = "scope-incomplete"        # a part of (scenario id, list id, count) is missing
INTERNAL_ERROR = "internal-error"            # the sync itself failed (never raised into the telemetry step): fail-closed like any other refusal
REASONS = (OK, NO_OBSERVER, NOT_READY, NO_STATION_LIST, SCENARIO_MISMATCH, LIST_MISMATCH, COUNT_MISMATCH, INDEX_NEGATIVE, INDEX_OUT_OF_RANGE, LOCATION_INVALID,
           LOCATION_MISMATCH, ROLE_MISMATCH, SCOPE_INCOMPLETE, INTERNAL_ERROR)

# The tolerance of the position / identity invariant: the same 0.01 m as everywhere in the jump contract and in the STIDX unit.
LOCATION_TOLERANCE_M = 0.01


class StationScope(NamedTuple):
    """The range in which a station index means anything. Equal to the plain tuple (scenario_id, list_id, count)."""
    scenario_id: int
    list_id: str
    count: int


class StationIdentitySnapshot(NamedTuple):
    """One verified (or refused) identity of one station. Immutable. When `valid` is False the other fields only DESCRIBE the refused candidate (diagnostics)."""
    station_index: int
    scope: Optional[StationScope]
    station_location: Optional[float]
    role: str
    valid: bool
    reason: str


class IdentityDecision(NamedTuple):
    """What the sync decided for one telemetry line: `usable` says whether the sender's indexes may be used at all (then `scope` is the scope of the adopted list);
    `tgt` and `arr` are the snapshots of the target station and of the last arrival-candidate station (each of them can be invalid on its own: -1 = none)."""
    usable: bool
    reason: str
    scope: Optional[StationScope]
    tgt: StationIdentitySnapshot
    arr: StationIdentitySnapshot
    arr_seq: int


class StationList(list):
    """The station list the application ADOPTED, carrying the identity (list_id) of the raw STALIST it was parsed from. For everything else it is a plain list."""

    def __init__(self, items=(), list_id=""):
        super().__init__(items)
        self.list_id = list_id


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def make_scope(scenario_id, list_id, count):
    """The StationScope, or None when a part of it is missing (an unknown scenario is -1, an unknown list is "")."""
    if not _is_int(scenario_id) or scenario_id < 0:
        return None
    if not isinstance(list_id, str) or not list_id:
        return None
    if not _is_int(count) or count < 0:
        return None
    return StationScope(scenario_id, list_id, count)


def scope_of(scenario_id, list_id, station_list):
    """The scope of a station list the application holds (count = its length); None when a part is missing."""
    return make_scope(scenario_id, list_id, len(station_list) if station_list is not None else None)


def _refused(reason, index, scope, role, location=None):
    return StationIdentitySnapshot(index, scope, location, role, False, reason)


def _location_of(entry):
    try:
        value = entry["location"]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def build_snapshot(index, scope, station_list, role):
    """The verified identity of station `index` in `station_list` under `scope`, or a refused snapshot with the reason.

    Valid only when: the scope is complete, the list is there, its length is the scope's count, (when the list carries its own list_id) that is the scope's list id,
    the index is an integer inside 0..count-1, the role is one of ROLES and the entry has a finite position. The position of a valid snapshot is the one OF THE
    ADOPTED ENTRY: the identity never comes from a position."""
    if scope is not None and not isinstance(scope, StationScope):
        try:
            scope = make_scope(*scope)
        except TypeError:
            scope = None
    if scope is None:
        return _refused(SCOPE_INCOMPLETE, index, None, role)
    if station_list is None or len(station_list) == 0:
        return _refused(NO_STATION_LIST, index, scope, role)
    if len(station_list) != scope.count:
        return _refused(COUNT_MISMATCH, index, scope, role)
    adopted_id = getattr(station_list, "list_id", None)
    if adopted_id is not None and adopted_id != scope.list_id:
        return _refused(LIST_MISMATCH, index, scope, role)
    if not _is_int(index) or index < 0:
        return _refused(INDEX_NEGATIVE, index, scope, role)
    if index >= scope.count:
        return _refused(INDEX_OUT_OF_RANGE, index, scope, role)
    if role not in ROLES:
        return _refused(ROLE_MISMATCH, index, scope, role)
    location = _location_of(station_list[index])
    if location is None:
        return _refused(LOCATION_INVALID, index, scope, role)
    return StationIdentitySnapshot(index, scope, location, role, True, OK)


def locations_agree(adopted_location, observed_location):
    """True when the two positions are both finite and differ by no more than the tolerance (a missing position never agrees)."""
    if isinstance(adopted_location, bool) or isinstance(observed_location, bool):
        return False
    if not isinstance(adopted_location, (int, float)) or not isinstance(observed_location, (int, float)):
        return False
    if not math.isfinite(adopted_location) or not math.isfinite(observed_location):
        return False
    return abs(adopted_location - observed_location) <= LOCATION_TOLERANCE_M + 1e-9


def start_snapshot(scenario_id, list_id, station_list, start_index):
    """The identity of the station the user chose to start the scoring at (setting_start_idx), role scoring_start."""
    return build_snapshot(start_index, scope_of(scenario_id, list_id, station_list), station_list, ROLE_SCORING_START)


def arrival_snapshot(scenario_id, list_id, station_list, arrival_index, arrival_location):
    """The identity of the station the train arrived at, role arrived_station: the sender's arrival index (ARRIDX), accepted only when it CORRESPONDS to the physical
    arrival the application judged - `arrival_location`, the position of the station the stop was scored against, is the position of the adopted entry. Any other
    case is refused (nothing is guessed from the position). The sender's TARGET index plays no part: the target may already name the NEXT station when the arrival
    is saved, and that is normal."""
    scope = scope_of(scenario_id, list_id, station_list)
    snapshot = build_snapshot(arrival_index, scope, station_list, ROLE_ARRIVED_STATION)
    if not snapshot.valid:
        return snapshot
    if not locations_agree(snapshot.station_location, arrival_location):
        return snapshot._replace(valid=False, reason=LOCATION_MISMATCH)
    return snapshot


def checkpoint_fields(snapshot):
    """The four identity items of a checkpoint (station_index, scope, station_location, role) from a VALID snapshot; the scope is stored as a plain tuple."""
    if not snapshot.valid or snapshot.role not in CHECKPOINT_ROLES:
        raise ValueError("only a valid snapshot with a checkpoint role can be stored")
    return {"station_index": snapshot.station_index, "scope": tuple(snapshot.scope), "station_location": snapshot.station_location, "role": snapshot.role}


def same_station(checkpoint, snapshot):
    """True when the checkpoint (a dict) already holds the station of this valid snapshot: same StationIndex under the same scope."""
    if not isinstance(checkpoint, dict) or not snapshot.valid:
        return False
    stored_scope = checkpoint.get("scope")
    return checkpoint.get("station_index") == snapshot.station_index and stored_scope is not None and tuple(stored_scope) == tuple(snapshot.scope)


_NONE_SNAPSHOT = StationIdentitySnapshot(NO_INDEX, None, None, "", False, NOT_READY)


def unavailable(reason):
    """The decision 'the sender's indexes can not be used', with the reason."""
    tgt = _NONE_SNAPSHOT._replace(role=ROLE_TARGET_STATION, reason=reason)
    arr = _NONE_SNAPSHOT._replace(role=ROLE_ARRIVED_STATION, reason=reason)
    return IdentityDecision(False, reason, None, tgt, arr, NO_INDEX)


def decide(observed, scenario_id, station_list, nextloc):
    """The single decision of the sync, pure.

    observed      the PUBLIC snapshot (a dict) of the STIDX observer, or None when there is no observer; read keys: ready, scenario_id, list_id, count, tgt_idx,
                  arr_idx, arr_seq
    scenario_id   the scenario of the application (Overlay.current_scenario_id), taken from the same telemetry line
    station_list  the station list the application ADOPTED (a StationList that carries its list_id)
    nextloc       the position the application holds as the next station's (Overlay.bve_next_loc), -1.0 when none

    The sender's indexes are usable only when ALL of these hold: the observer is READY, its scenario is the application's, the application adopted a list that carries
    its identity and the list id and the count of the STIDX line are those of the adopted list. The target snapshot is separate: it is valid only when (a target is named
    and) the position the application holds for the next station is the position of the adopted entry of that index - a target that does not agree is invalid ON ITS OWN
    (diagnostics only) and never makes the arrival index unusable: the arrival is checked against the arrival the application judged (arrival_snapshot)."""
    if observed is None:
        return unavailable(NO_OBSERVER)
    if not observed.get("ready"):
        return unavailable(NOT_READY)
    if observed.get("scenario_id") != scenario_id:
        return unavailable(SCENARIO_MISMATCH)
    adopted_id = getattr(station_list, "list_id", None)
    if station_list is None or len(station_list) == 0 or not adopted_id:
        return unavailable(NO_STATION_LIST)
    if observed.get("list_id") != adopted_id:
        return unavailable(LIST_MISMATCH)
    if observed.get("count") != len(station_list):
        return unavailable(COUNT_MISMATCH)
    scope = make_scope(scenario_id, adopted_id, len(station_list))
    if scope is None:
        return unavailable(SCOPE_INCOMPLETE)
    tgt_index, arr_index = observed.get("tgt_idx", NO_INDEX), observed.get("arr_idx", NO_INDEX)
    tgt = build_snapshot(tgt_index, scope, station_list, ROLE_TARGET_STATION)
    arr = build_snapshot(arr_index, scope, station_list, ROLE_ARRIVED_STATION)
    if tgt.valid and not locations_agree(tgt.station_location, nextloc):
        tgt = tgt._replace(valid=False, reason=LOCATION_MISMATCH)      # the next station the application holds is not the one the index names: the TARGET is not used
    arr_seq = observed.get("arr_seq", NO_INDEX)
    return IdentityDecision(True, OK, scope, tgt, arr, arr_seq if _is_int(arr_seq) else NO_INDEX)


def published_values(decision):
    """(tgt_idx, arr_idx, arr_seq, list_id) the application publishes for a decision: a snapshot that is not valid is -1, an unusable decision is (-1, -1, -1, "")."""
    if not decision.usable:
        return NO_INDEX, NO_INDEX, NO_INDEX, ""
    return (decision.tgt.station_index if decision.tgt.valid else NO_INDEX,
            decision.arr.station_index if decision.arr.valid else NO_INDEX,
            decision.arr_seq, decision.scope.list_id)


# ==============================================================================================================================================================
# Phase PID-D4JA StationIndex ST-2b - the RETRY: the station of a retry is the StationIndex of the checkpoint the user chose, verified against the scope the application holds.
# Nothing is searched by a position (no distance, no nearest, no station 0, no first of the list); a checkpoint that does not verify is REFUSED with a reason code and
# nothing is changed. Pure like the rest of this module: the caller (scoring_logic.execute_retry) owns the state and decides what to do with the answer.
# ==============================================================================================================================================================
NO_CHECKPOINT = "no-checkpoint"              # there is no checkpoint at the chosen position of the history
OLD_FORM = "old-form"                        # the checkpoint lacks an item of the contract (no compatibility reader: the station is never rebuilt from its position)
RETRY_PENDING = "retry-pending"              # a retry is already waiting for its jump
JUMP_UNAVAILABLE = "jump-unavailable"        # the request can not be made safely (the managed mode has no jump client)
TIME_INVALID = "time-invalid"                # the time of the checkpoint is not a finite number >= 0
RETRY_REASONS = (NO_CHECKPOINT, OLD_FORM, RETRY_PENDING, JUMP_UNAVAILABLE, TIME_INVALID)      # (the other reasons of a refusal are the words of REASONS)

RETRY_VALIDATED = "validated"                # the pending retry exists, the request was not sent (yet / the client refused to send it)
RETRY_SENT = "sent"                          # the request was sent
RETRY_STATES = (RETRY_VALIDATED, RETRY_SENT)

CHECKPOINT_IDENTITY_KEYS = ("station_index", "scope", "station_location", "role")


class RetryResult(NamedTuple):
    """The answer of one retry operation. `accepted` False = refused and NOTHING was changed (no request, no pending, no count, no history, no score). `request_id` is the
    RequestId of the sent request (None: not sent / the plain mode has none). `selected_station_index` is the StationIndex of the chosen checkpoint (NO_INDEX when unknown)."""
    accepted: bool
    reason: str
    request_id: Optional[bytes]
    selected_station_index: int


class RetryPending(NamedTuple):
    """What ST-3 needs to settle a retry after its jump: the chosen checkpoint (the very object, by identity), where it is in the history, its StationIndex and scope (the
    expectation of the completion's selected index), the RequestId and the size of the history when the request was made. Nothing here changes the history."""
    selected_save_position: int
    selected_station_index: int
    selected_scope: StationScope
    checkpoint: dict
    request_id: Optional[bytes]
    scenario_id: int
    original_history_length: int
    state: str


def _finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _saved_index(checkpoint):
    index = checkpoint.get("station_index") if isinstance(checkpoint, dict) else None
    return index if _is_int(index) else NO_INDEX


def _retry_refused(reason, checkpoint=None):
    return RetryResult(False, reason, None, _saved_index(checkpoint))


def missing_checkpoint_item(checkpoint):
    """The first item the checkpoint lacks ('' = none): the four identity items, then the score (and the item breakdown when it is there but is not a dict)."""
    if not isinstance(checkpoint, dict):
        return "checkpoint"
    for key in CHECKPOINT_IDENTITY_KEYS + ("score",):
        if checkpoint.get(key) is None:
            return key
    if not _finite_number(checkpoint["score"]):
        return "score"
    if "score_details" in checkpoint and not isinstance(checkpoint["score_details"], dict):
        return "score_details"
    return ""


def check_retry_checkpoint(save_data, position, scenario_id, list_id, station_list, pending_active=False):
    """Verifies the checkpoint at `position` of the history for a retry; returns a RetryResult (accepted = every check passed; nothing is sent or changed here).

    The first check that fails names the refusal: no checkpoint at the position (no-checkpoint) -> a retry is pending (retry-pending) -> the application holds no station list
    (no-station-list) or no complete scope (scope-incomplete) -> the checkpoint lacks an item (old-form) -> its scope is not the scope of the application (scenario-mismatch,
    list-mismatch, count-mismatch) -> its StationIndex is not inside the list (index-negative, index-out-of-range) -> its position is not a finite number (location-invalid)
    or is not the position of that index in the list, 0.01 m (location-mismatch) -> its role is not the role of its place (role-mismatch: scoring_start at position 0,
    arrived_station after it) -> its time is not a finite number >= 0 (time-invalid). The StationIndex 0 is an index like any other."""
    try:
        return _check_retry_checkpoint(save_data, position, scenario_id, list_id, station_list, pending_active)
    except Exception:
        return RetryResult(False, INTERNAL_ERROR, None, NO_INDEX)       # nothing here raises: whatever could not be examined is a refusal


def _check_retry_checkpoint(save_data, position, scenario_id, list_id, station_list, pending_active):
    if not isinstance(save_data, list) or not _is_int(position) or position < 0 or position >= len(save_data):
        return _retry_refused(NO_CHECKPOINT)
    checkpoint = save_data[position]
    if pending_active:
        return _retry_refused(RETRY_PENDING, checkpoint)
    if station_list is None or len(station_list) == 0:
        return _retry_refused(NO_STATION_LIST, checkpoint)
    current = scope_of(scenario_id, list_id, station_list)
    if current is None:
        return _retry_refused(SCOPE_INCOMPLETE, checkpoint)
    if missing_checkpoint_item(checkpoint) != "":
        return _retry_refused(OLD_FORM, checkpoint)
    stored = checkpoint["scope"]
    saved_scope = make_scope(*stored) if isinstance(stored, (tuple, list)) and len(stored) == 3 else None
    if saved_scope is None:
        return _retry_refused(OLD_FORM, checkpoint)
    if saved_scope.scenario_id != current.scenario_id:
        return _retry_refused(SCENARIO_MISMATCH, checkpoint)
    if saved_scope.list_id != current.list_id:
        return _retry_refused(LIST_MISMATCH, checkpoint)
    if saved_scope.count != current.count:
        return _retry_refused(COUNT_MISMATCH, checkpoint)
    snapshot = build_snapshot(checkpoint["station_index"], current, station_list, ROLE_ARRIVED_STATION)
    if not snapshot.valid:
        return _retry_refused(snapshot.reason, checkpoint)
    if not _finite_number(checkpoint["station_location"]):
        return _retry_refused(LOCATION_INVALID, checkpoint)
    if not locations_agree(snapshot.station_location, checkpoint["station_location"]):
        return _retry_refused(LOCATION_MISMATCH, checkpoint)
    if checkpoint["role"] != (ROLE_SCORING_START if position == 0 else ROLE_ARRIVED_STATION):
        return _retry_refused(ROLE_MISMATCH, checkpoint)
    if not _finite_number(checkpoint.get("time_ms")) or checkpoint["time_ms"] < 0:
        return _retry_refused(TIME_INVALID, checkpoint)
    return RetryResult(True, OK, None, snapshot.station_index)


def make_retry_pending(save_data, position, request_id=None, state=RETRY_VALIDATED):
    """The pending retry of a checkpoint that check_retry_checkpoint accepted (None when the arguments do not describe one: nothing here raises)."""
    try:
        checkpoint = save_data[position]
        scope = StationScope(*checkpoint["scope"])
        if state not in RETRY_STATES:
            return None
        return RetryPending(position, checkpoint["station_index"], scope, checkpoint, request_id, scope.scenario_id, len(save_data), state)
    except (KeyError, IndexError, TypeError):
        return None


def resolve_retry_history(save_data, pending, scenario_id, list_id, station_list):
    """The history after a retry whose jump COMPLETED as requested: a NEW list holding save_data[0 .. position] (the input is never changed), or None when the pending
    retry no longer describes this history: it is not a sent pending retry, the element at the position is not the chosen checkpoint (the history was cleared or replaced),
    the scope of the application is not the scope of the choice. Checkpoints added after the request do not matter: the cut is by position. This module only FIXES the
    rule; settling a retry (ST-3: the completion's selected index must be the chosen StationIndex) is the caller's."""
    if not isinstance(pending, RetryPending) or pending.state != RETRY_SENT or not isinstance(save_data, list):
        return None
    position = pending.selected_save_position
    if not _is_int(position) or position < 0 or position >= len(save_data) or save_data[position] is not pending.checkpoint:
        return None
    current = scope_of(scenario_id, list_id, station_list)
    if current is None or tuple(current) != tuple(pending.selected_scope):
        return None
    if save_data[position].get("station_index") != pending.selected_station_index:
        return None
    return list(save_data[:position + 1])


def _scope_text(scope):
    """scenario:list:count with fixed characters only (the list id is 8 hexadecimal digits; anything else is cut to alphanumerics)."""
    try:
        scenario_id, list_id, count = scope
        return "%d:%s:%d" % (scenario_id, "".join(ch for ch in str(list_id) if ch.isalnum())[:8], count)
    except (TypeError, ValueError):
        return "none"


def _location_text(value):
    return "%.2f" % value if _finite_number(value) else "bad"


def retry_event(result, position, history_before, history_after, count_before, count_after, pending, current_scope, checkpoint=None, station_list=None, sync_reason=""):
    """(event name, fields) of the ONE diagnostic line of a retry operation: `retry-accepted` or `retry-rejected`. Fixed words and numbers only (no station name, no path):
    the line must fit the 160 characters the Caller keeps. h and c are 'before/after' of the history length and of the retry count (a refusal shows the same number twice),
    pend is the state of the pending retry (none / validated / sent), cur is the scope of the application and sav the scope of the checkpoint (only where they differ).
    Never raises."""
    try:
        accepted = bool(result.accepted)
        fields = {"pos": position, "idx": result.selected_station_index, "h": "%d/%d" % (history_before, history_after), "c": "%d/%d" % (count_before, count_after),
                  "pend": pending.state if isinstance(pending, RetryPending) else "none", "cur": _scope_text(current_scope) if current_scope is not None else "none"}
        if accepted:
            fields["id"] = result.request_id[:4].hex().upper() if isinstance(result.request_id, (bytes, bytearray)) and result.request_id else "-"
            return "retry-accepted", fields
        reason = result.reason
        fields["why"] = reason
        if reason in (SCENARIO_MISMATCH, LIST_MISMATCH, COUNT_MISMATCH):
            fields["sav"] = _scope_text(checkpoint.get("scope")) if isinstance(checkpoint, dict) else "none"
        elif reason in (LOCATION_INVALID, LOCATION_MISMATCH):
            listed = None
            if isinstance(checkpoint, dict) and station_list is not None and _is_int(checkpoint.get("station_index")) and 0 <= checkpoint["station_index"] < len(station_list):
                listed = _location_of(station_list[checkpoint["station_index"]])
            fields["loc"] = "%s/%s" % (_location_text(checkpoint.get("station_location") if isinstance(checkpoint, dict) else None), _location_text(listed))
        elif reason == ROLE_MISMATCH:
            role = checkpoint.get("role") if isinstance(checkpoint, dict) else None
            fields["role"] = role if role in ROLES else "other"
        elif reason == OLD_FORM:
            fields["miss"] = missing_checkpoint_item(checkpoint) or "scope"
        elif reason in (NO_STATION_LIST, SCOPE_INCOMPLETE) and sync_reason:
            fields["sync"] = sync_reason
        elif reason == RETRY_PENDING and isinstance(pending, RetryPending):
            fields["ppos"] = pending.selected_save_position
        return "retry-rejected", fields
    except Exception:
        return "retry-rejected", {"why": INTERNAL_ERROR}