"""Stage P1: the EFFECTIVE STATION STATE of the TScoring display - ONE read model that the ordinary HUD time row (and, later, the F2 Debug and the user-facing F2) reads. Pure: no Qt, no Win32, no clock, no scoring,
no machine, no UI; it imports nothing of the application.

derive(EffectiveInputs) -> EffectiveStationState is a PURE FUNCTION of its inputs. It keeps no state, owns no authority and writes nothing; its inputs are plain snapshots of values the application already holds
(the station list as RECEIVED, the static PairSet, the host's official target, the SI-R2.3 time-kind selection, the scoring / machine VIEW). The machine stays the one writer of the pseudo-turnback state:
`turnback_state` is a VIEW of it.

THE TOP-LEVEL CONTRACT (Owner, P1): three branches, decided FIRST.
  1. free driving (no scoring session): the effective target IS the host's official target. No automatic Jump, no Jump countdown, no TScoring-made hold of A, no arrival / stop / pass judgement of any kind.
  2. scoring AND the Run crosses a pseudo-turnback pair A -> B: the pseudo_turnback_machine has priority. The effective target is the pair A while the chain lives (until the official Jump succeeded AND B is
     established); the remaining time is the Jump wait (00:10 / --:-- / 00:05 / 00:00); after the Jump it is the departure of B.
  3. scoring but the Run does not cross a pair (or the target is no pair station of the chain): the CURRENT scoring target contract is kept as it is (the display time is the one the scoring HUD already has).

THE EFFECTIVE TIMETABLE (the only place where the meaning of a pair's times is decided): pair A: arrival valid, departure UNDEFINED (SUPPRESSED_FOR_TURNBACK); pair B: arrival UNDEFINED (SUPPRESSED_FOR_TURNBACK),
departure valid and REQUIRED; every other station: as the sender sent it. The sender's completed A departure / B arrival (the STALIST 'raw_arr' / 'raw_dep' are the sender's FINAL times) are never used. The
selection of the arrival or the departure time of the official target is the existing SI-R2.3 selector (hud_target_contract.select_time_kind), given as an input.
Nothing here decides an arrival, a stop, a pass, a pair, a Jump or a score."""
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple

KNOWN = "KNOWN"                 # official_target_contract.KNOWN (the wire word of a target the host names)


class Role(str, Enum):
    NORMAL = "NORMAL"
    PAIR_A = "PAIR_A"
    PAIR_B = "PAIR_B"
    TERMINAL = "TERMINAL"
    PASS = "PASS"


class TimeSource(str, Enum):
    SENDER_FINAL = "SENDER_FINAL"                          # the value the sender put on the wire (authored, or completed for an ordinary station: the application cannot tell and need not)
    SUPPRESSED_FOR_TURNBACK = "SUPPRESSED_FOR_TURNBACK"    # pair A departure / pair B arrival: undefined by the pair semantics, whatever the sender completed
    NONE = "NONE"                                          # the sender sent no usable time


class TimeKind(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"
    SCORING_NEXTTIME = "SCORING_NEXTTIME"   # the scoring target's own display time (the C# machine time), kept as it is
    NONE = "NONE"                           # the Jump wait: no timetable time is looked at


class RemainingMode(str, Enum):
    NORMAL_TIMETABLE = "NORMAL_TIMETABLE"
    FREE_TURNBACK_HIDDEN = "FREE_TURNBACK_HIDDEN"
    TURNBACK_INITIAL_COUNTDOWN = "TURNBACK_INITIAL_COUNTDOWN"
    TURNBACK_CANCELLED = "TURNBACK_CANCELLED"
    TURNBACK_RESTOP_COUNTDOWN = "TURNBACK_RESTOP_COUNTDOWN"
    TURNBACK_REQUESTED = "TURNBACK_REQUESTED"


class TurnbackState(str, Enum):
    """A VIEW of pseudo_turnback_machine (never a second writable state)."""
    NONE = "NONE"
    WAITING = "WAITING"
    CANCELLED = "CANCELLED"
    REQUESTED = "REQUESTED"
    AWAITING_B = "AWAITING_B"


CONTRACT_PAIR_B_DEPARTURE = "pair-b-departure-missing"   # a certified pair B without a departure time is a contract violation (never an ordinary --:--)
CONTRACT_PAIR_A_ARRIVAL = "pair-a-arrival-missing"


@dataclass(frozen=True)
class StationRow:
    index: int
    sender_arrival_ms: int        # as received (the sender's FINAL time); -1 / <= 0 = no time
    sender_departure_ms: int
    is_pass: bool = False
    is_terminal: bool = False


@dataclass(frozen=True)
class Cursor:
    """The host's official target (OFFTGT): the wire state word and the station index."""
    state: str
    index: int = -1


@dataclass(frozen=True)
class MachineView:
    """A READ of pseudo_turnback_machine (state names are the machine's own). chain_alive = the machine holds the chain whose A the HUD keeps (turnback_held_a_target is not None)."""
    state_name: str = "idle"
    restop_count: int = 0
    wait_deadline_ms: Optional[int] = None       # machine.wait_deadline_ms()
    awaiting_b: bool = False
    chain_alive: bool = False
    held_a_index: Optional[int] = None           # the A of the live chain


@dataclass(frozen=True)
class ScoringView:
    active: bool = False                          # owner_is_scoring(is_scoring_mode, is_scoring_finished)
    crosses_pair: bool = False                    # the Run's section crosses a pseudo-turnback pair A -> B (the Run's fixed pairs)
    crossed_b_indexes: FrozenSet[int] = frozenset()
    scoring_target_index: Optional[int] = None    # the C# scoring target (bve_tgt_idx)
    machine: Optional[MachineView] = None
    basic_brake_rule: Optional[str] = None        # read-only: the rule the scoring applies now (the F2 / overlay side connects it in P2)


@dataclass(frozen=True)
class EffectiveInputs:
    stations: Tuple[StationRow, ...]
    pairs: Tuple[Tuple[int, int], ...]            # (A, B) of the static PairSet; () when none
    pairset_ready: bool                           # the PairSet is the certified one of the CURRENT station list
    cursor: Cursor
    time_kind: str                                # the SI-R2.3 selection for the official target: 'ARRIVAL' | 'DEPARTURE' (hud_target_contract.select_time_kind)
    now_ms: int
    display_time_ms: Optional[int]                # the display target's time as the application already derives it (None = none); used ONLY for stations that are no pair station of the effective rule
    display_timing: bool = False
    scoring: ScoringView = ScoringView()


@dataclass(frozen=True)
class EffectiveStationState:
    raw_target_index: Optional[int]               # the host's official target (KNOWN) else None
    scoring_target_index: Optional[int]           # the C# scoring target (scoring only)
    effective_target_index: Optional[int]
    station_role: Optional[Role]
    turnback_state: TurnbackState
    selected_time_kind: TimeKind
    raw_arrival_time: Optional[int]               # of the effective target station, as received
    raw_departure_time: Optional[int]
    effective_arrival_time: Optional[int]
    effective_departure_time: Optional[int]
    arrival_time_source: TimeSource
    departure_time_source: TimeSource
    remaining_time_mode: RemainingMode
    selected_time_ms: Optional[int]               # the absolute timetable time the HUD counts down to (None = --:--); only for the timetable modes
    countdown_ms: Optional[int]                   # the Jump wait: ms to the deadline (INITIAL / RESTOP), 0 (REQUESTED), None otherwise
    jump_deadline: Optional[int]
    timing_enabled: bool
    effective_basic_brake_rule: Optional[str]
    contract_violation: Optional[str] = None      # a pair whose required time is missing: never shown as a normal --:--


def _defined(ms):
    return ms if isinstance(ms, int) and not isinstance(ms, bool) and ms > 0 else None


def _roles(inp):
    a_set = {a for a, b in inp.pairs} if inp.pairset_ready else set()
    b_set = {b for a, b in inp.pairs} if inp.pairset_ready else set()
    roles = {}
    for s in inp.stations:
        if s.index in a_set:
            roles[s.index] = Role.PAIR_A
        elif s.index in b_set:
            roles[s.index] = Role.PAIR_B
        elif s.is_terminal:
            roles[s.index] = Role.TERMINAL
        elif s.is_pass:
            roles[s.index] = Role.PASS
        else:
            roles[s.index] = Role.NORMAL
    return roles


def effective_times(row, role):
    """THE effective timetable: (arrival, departure, arrival_source, departure_source) of one station. The ONLY place where the suppression of a pair's undefined times lives."""
    arrival, departure = _defined(row.sender_arrival_ms), _defined(row.sender_departure_ms)
    arrival_source = TimeSource.SENDER_FINAL if arrival is not None else TimeSource.NONE
    departure_source = TimeSource.SENDER_FINAL if departure is not None else TimeSource.NONE
    if role == Role.PAIR_B:
        arrival, arrival_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK
    elif role == Role.PAIR_A:
        departure, departure_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK
    return arrival, departure, arrival_source, departure_source


def pair_time_violation(pairs, stations):
    """The REQUIRED times of every certified pair (Owner P1 contract): A has an arrival time, B has a DEPARTURE time (the sender's final times). The C# Qualifier certifies a B only when its departure is stated, so
    a violation means inconsistent route data or sender. None when consistent, else the fixed reason word. A pair set with such a pair must not become READY (route_pairset fail closed); the pair B departure is
    never an optional field that falls back to an ordinary --:--."""
    by_index = {s.index: s for s in stations}
    for a, b in pairs:
        row_a, row_b = by_index.get(a), by_index.get(b)
        if row_a is None or _defined(row_a.sender_arrival_ms) is None:
            return CONTRACT_PAIR_A_ARRIVAL
        if row_b is None or _defined(row_b.sender_departure_ms) is None:
            return CONTRACT_PAIR_B_DEPARTURE
    return None


def _index_ok(index, n):
    return isinstance(index, int) and not isinstance(index, bool) and 0 <= index < n


def derive(inp):
    n = len(inp.stations)
    roles = _roles(inp)
    sc = inp.scoring
    machine = sc.machine
    cursor_index = inp.cursor.index if (inp.cursor.state == KNOWN and _index_ok(inp.cursor.index, n)) else None
    scoring_index = sc.scoring_target_index if (sc.active and _index_ok(sc.scoring_target_index, n)) else None

    turnback_state = TurnbackState.NONE
    kind = TimeKind.NONE
    mode = RemainingMode.NORMAL_TIMETABLE
    countdown = None
    jump_deadline = None
    selected = None
    violation = None
    display_time = _defined(inp.display_time_ms)

    if sc.active and machine is not None and machine.chain_alive:
        # branch 2: the machine has priority; the effective target is the A of the live chain until B is established
        effective_index = machine.held_a_index if _index_ok(machine.held_a_index, n) else scoring_index
        deadline = machine.wait_deadline_ms
        if deadline is not None:
            turnback_state = TurnbackState.WAITING
            mode = RemainingMode.TURNBACK_INITIAL_COUNTDOWN if machine.restop_count == 0 else RemainingMode.TURNBACK_RESTOP_COUNTDOWN
            countdown, jump_deadline = deadline - inp.now_ms, deadline
        elif machine.state_name == "restop-wait":
            turnback_state, mode = TurnbackState.CANCELLED, RemainingMode.TURNBACK_CANCELLED
        elif machine.state_name == "requested" or machine.awaiting_b:
            turnback_state = TurnbackState.REQUESTED if machine.state_name == "requested" else TurnbackState.AWAITING_B
            mode, countdown = RemainingMode.TURNBACK_REQUESTED, 0
        else:
            kind, selected = TimeKind.SCORING_NEXTTIME, display_time
    elif sc.active:
        effective_index = scoring_index
        if sc.crosses_pair and scoring_index is not None and scoring_index in sc.crossed_b_indexes:
            # the Jump succeeded and B is established: the departure of B (required by the pair contract); never an ordinary fallback
            kind = TimeKind.DEPARTURE
            row = inp.stations[scoring_index]
            selected = effective_times(row, Role.PAIR_B)[1]
            if selected is None:
                violation = CONTRACT_PAIR_B_DEPARTURE
        else:
            kind, selected = TimeKind.SCORING_NEXTTIME, display_time        # branch 3: the current scoring target contract
    else:
        # branch 1: free driving - the official target, SI-R2.3 selects the time kind, the effective timetable decides whether that time is defined
        effective_index = cursor_index
        role = roles.get(effective_index) if effective_index is not None else None
        if role in (Role.PAIR_A, Role.PAIR_B):
            kind = TimeKind.DEPARTURE if inp.time_kind == "DEPARTURE" else TimeKind.ARRIVAL
            arrival, departure, _, _ = effective_times(inp.stations[effective_index], role)
            selected = departure if kind == TimeKind.DEPARTURE else arrival
            if selected is None:
                mode = RemainingMode.FREE_TURNBACK_HIDDEN
                if role == Role.PAIR_B and kind == TimeKind.DEPARTURE:
                    violation = CONTRACT_PAIR_B_DEPARTURE            # the required departure of a pair B is missing
        else:
            if role in (Role.PASS, Role.TERMINAL):
                kind = TimeKind.ARRIVAL
            elif role == Role.NORMAL:
                kind = TimeKind.DEPARTURE if inp.time_kind == "DEPARTURE" else TimeKind.ARRIVAL
            selected = display_time

    row = inp.stations[effective_index] if effective_index is not None else None
    role = roles.get(effective_index) if row is not None else None
    if row is not None:
        eff_arrival, eff_departure, arrival_source, departure_source = effective_times(row, role)
        raw_arrival, raw_departure = _defined(row.sender_arrival_ms), _defined(row.sender_departure_ms)
    else:
        eff_arrival = eff_departure = raw_arrival = raw_departure = None
        arrival_source = departure_source = TimeSource.NONE
    if mode in (RemainingMode.TURNBACK_INITIAL_COUNTDOWN, RemainingMode.TURNBACK_RESTOP_COUNTDOWN, RemainingMode.TURNBACK_CANCELLED, RemainingMode.TURNBACK_REQUESTED, RemainingMode.FREE_TURNBACK_HIDDEN):
        selected = None

    return EffectiveStationState(
        raw_target_index=cursor_index, scoring_target_index=scoring_index, effective_target_index=effective_index, station_role=role, turnback_state=turnback_state,
        selected_time_kind=kind, raw_arrival_time=raw_arrival, raw_departure_time=raw_departure, effective_arrival_time=eff_arrival, effective_departure_time=eff_departure,
        arrival_time_source=arrival_source, departure_time_source=departure_source, remaining_time_mode=mode, selected_time_ms=selected, countdown_ms=countdown,
        jump_deadline=jump_deadline, timing_enabled=bool(inp.display_timing), effective_basic_brake_rule=sc.basic_brake_rule if sc.active else None, contract_violation=violation)
