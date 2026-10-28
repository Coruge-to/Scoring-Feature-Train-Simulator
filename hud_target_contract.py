"""Phase SI-R2.3 (C4a): the display target of the HUD - who owns the target the HUD shows, and what that target is. Pure: no Qt, no Win32, no clock of its own, no scoring state.

THE OWNERSHIP RULE (decided; the same expression is already used at 7 places of the application):
        target_owner_is_scoring = is_scoring_mode and not is_scoring_finished
  * owner TS  (a scoring session runs, a Retry included): the HUD shows the SCORING target = the machine values the C# state machine holds, unchanged. The official target is not read.
  * owner BVE (no scoring session, or it is finished): the HUD shows the OFFICIAL target (official_target_contract) and nothing else. Only a KNOWN target is shown; every other
    state (T, N, U, F, ABSENT, INVALID, NOT_INITIALIZED) is NONE ("--- m" / "--:--") with a reason word of its own. The last KNOWN target is never kept (E-11 plan A) and the machine
    target, a distance, the nearest station, a 50 m / 100 m search or the old scoring target are never a fallback.

The display target is a READ MODEL derived from its inputs on every call. Nothing here writes the machine target, the official state or the scoring state, and a target is never
chosen by a distance: the identity of the station is the official index, always.

The only state is the display-only TERMINAL FREEZE (H6): the remaining time of a terminal station freezes when the doors first open there (the C# state machine does the same for the scoring
target; that one is not duplicated and not read). It lives for one scope (scenario id + station list identity) and one official index, and ends with a scoring owner, any state other than
KNOWN, a different index or a different scope. It is the caller's value: this module returns the new freeze and keeps nothing.

The remaining time of a KNOWN target is derived from the timetable only (the STALIST arrival / departure the sender made final), the doors and the positions:
  terminal           doors opened within NEAR_M of the target for the first time -> freeze diff = (arrival - now) / 1000 (truncated toward zero, as the C# integer division) and show now + diff;
                     before that the arrival
  pass               the arrival
  stop               the departure while the doors are open within NEAR_M of the target, otherwise the arrival
  a time that is not defined (<= 0) is none (-1), as the existing 'NEXTTIME > 0' contract of the HUD.
"""
from collections import namedtuple

from official_target_contract import KNOWN, NONE_TERMINAL, NONE_EMPTY, UNAVAILABLE, READ_FAILED, ABSENT, INVALID, NOT_INITIALIZED

OWNER_TS, OWNER_BVE = "TS", "BVE"
SOURCE_MACHINE, SOURCE_OFFICIAL, SOURCE_NONE = "MACHINE", "OFFICIAL", "NONE"
NEAR_M = 100.0                        # the doors are 'open at the target' within this distance of it (the C# hasDoorOpenedAtTarget of a normal stop)
NO_TIME = -1

R_MACHINE, R_OFFICIAL = "hud-scoring-machine", "hud-official"
R_BAD_INDEX, R_UNKNOWN_STATE, R_INTERNAL = "hud-none-bad-index", "hud-none-unknown-state", "hud-none-internal-error"
NONE_REASON = {NONE_TERMINAL: "hud-none-terminal", NONE_EMPTY: "hud-none-empty", UNAVAILABLE: "hud-none-unavailable", READ_FAILED: "hud-none-read-failed",
               ABSENT: "hud-none-absent", INVALID: "hud-none-invalid", NOT_INITIALIZED: "hud-none-not-initialized"}

# next_loc: -1.0 = no target; next_time: ms, -1 = none; is_pass: 0 / 1; timing: the 'timing station' label may blink
HudTarget = namedtuple("HudTarget", "owner source next_loc next_time is_pass margin_b margin_f timing reason")
MachineTarget = namedtuple("MachineTarget", "next_loc next_time is_pass margin_b margin_f timing")
OfficialTarget = namedtuple("OfficialTarget", "state index location margin_b margin_f reason")
TerminalFreeze = namedtuple("TerminalFreeze", "scope index diff_s")


OFFTGT_ATTRS = ("official_state", "official_index", "official_location", "official_margin_b", "official_margin_f", "official_reason")


def offtgt_of(source):
    """The OfficialTarget that the six published values of `source` (the Overlay) hold. Reads the attributes by name and writes nothing: the application module that calls this names none of them."""
    return OfficialTarget(*[getattr(source, name) for name in OFFTGT_ATTRS])


def owner_is_scoring(is_scoring_mode, is_scoring_finished):
    """True = the scoring session owns the target (TS); False = BVE does. Derived every time, never latched."""
    return bool(is_scoring_mode) and not bool(is_scoring_finished)


def none_target(owner, reason):
    return HudTarget(owner, SOURCE_NONE, -1.0, NO_TIME, 0, -1.0, -1.0, False, reason)


NO_TARGET = none_target(OWNER_BVE, NONE_REASON[NOT_INITIALIZED])


def _defined_time(value):
    """A timetable time in ms, or NO_TIME when it is not defined (<= 0, not an int)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else NO_TIME


def _truncated_seconds(diff_ms):
    """diff_ms / 1000 truncated toward zero (the C# integer division), not floored."""
    return diff_ms // 1000 if diff_ms >= 0 else -((-diff_ms) // 1000)


def official_time(entry, index, official_location, location, time_ms, door, scope, freeze):
    """The remaining-time target of a KNOWN official target -> (ms or NO_TIME, the terminal freeze to keep).

    entry is the station of the adopted list the official index names (raw_arr / raw_dep are the sender's final times), location and time_ms are the train's, door is the door state
    (0 = closed), scope identifies the scenario and the list the freeze belongs to."""
    if freeze is not None and (freeze.scope != scope or freeze.index != index):
        freeze = None
    arrival, departure = _defined_time(entry.get("raw_arr")), _defined_time(entry.get("raw_dep"))
    doors_open_here = door != 0 and abs(official_location - location) < NEAR_M
    if entry.get("is_terminal"):
        if freeze is None and doors_open_here and arrival != NO_TIME:
            freeze = TerminalFreeze(scope, index, _truncated_seconds(arrival - time_ms))
        if freeze is not None:
            return time_ms + freeze.diff_s * 1000, freeze
        return arrival, None
    if entry.get("is_pass"):
        return arrival, None
    return (departure if doors_open_here else arrival), None


def derive(scoring, machine_of, offtgt, timing_of, station_list, location, time_ms, door, scope, freeze):
    """The display target of this moment -> (HudTarget, the terminal freeze to keep).

    scoring           owner_is_scoring(...)
    machine_of        () -> the MachineTarget of the scoring target; called only when scoring
    offtgt            the OfficialTarget; read only when BVE owns the target
    timing_of         (index) -> whether that station of the chosen section is a timing station; called only for a KNOWN target
    station_list      the adopted station list; location / time_ms / door the train's; scope / freeze see official_time"""
    if scoring:
        machine = machine_of()
        return HudTarget(OWNER_TS, SOURCE_MACHINE, machine.next_loc, machine.next_time, machine.is_pass, machine.margin_b, machine.margin_f, bool(machine.timing), R_MACHINE), None
    if offtgt.state != KNOWN:
        return none_target(OWNER_BVE, NONE_REASON.get(offtgt.state, R_UNKNOWN_STATE)), None
    index = offtgt.index
    if not (isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(station_list)):
        return none_target(OWNER_BVE, R_BAD_INDEX), None
    entry = station_list[index]
    next_time, freeze = official_time(entry, index, offtgt.location, location, time_ms, door, scope, freeze)
    is_pass = 1 if entry.get("is_pass") else 0
    return HudTarget(OWNER_BVE, SOURCE_OFFICIAL, offtgt.location, next_time, is_pass, offtgt.margin_b, offtgt.margin_f, bool(timing_of(index)), R_OFFICIAL), freeze
