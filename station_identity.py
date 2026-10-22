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
