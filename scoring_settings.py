"""INITIAL-DEFAULTS: the running snapshot of the scoring settings (Commit 3).

The F1 settings of the Overlay (pen_*, penalty_init_rules, rank_a_ratio, user_timing_overrides) are the SCENARIO settings: they are regenerated from the saved defaults at every scenario load and the user may edit them in F1 before the scoring starts.
The scoring start freezes them in ONE immutable ScoringSettings (the attribute _scoring_settings of the Overlay, exactly like the scoring section snapshot of scoring_logic). While the Run is active the scoring reads ONLY the snapshot;
before the start (no active Run) it reads the live attributes. Nothing of the snapshot is shared with a live value: lists and dicts are copied into tuples, and `value` hands out fresh objects.

Pure: no Qt, no Overlay import (the Overlay is a duck-typed argument).
"""
from typing import NamedTuple


class ScoringSettings(NamedTuple):
    generation: object
    rolling: bool
    safety_intervention: bool
    speed_limit_exceeded: bool
    stop_shock: bool
    emergency_brake: bool
    init_rules: tuple                     # ((end_idx, apply, release), ...)
    a_rank_ratio: float
    timing_overrides: tuple               # ((station_index, bool), ...) sorted by index


# the live Overlay attribute of every name, and the value it has when the attribute does not exist
LIVE = {
    "rolling": ("pen_roll", True),
    "speed_limit_exceeded": ("pen_limit", True),
    "stop_shock": ("pen_jerk", True),
    "emergency_brake": ("pen_eb", True),
    "a_rank_ratio": ("rank_a_ratio", 0.7),
}
DEFAULT_INIT_RULES = [{"apply": "ON①", "release": "ON①"}]


def build(overlay):
    """Called once by the scoring start, before the scoring mode is switched on."""
    rules = tuple((r.get("end_idx", -1), r.get("apply", "ON①"), r.get("release", "ON①")) for r in getattr(overlay, "penalty_init_rules", DEFAULT_INIT_RULES))
    overrides = tuple(sorted((int(k), bool(v)) for k, v in getattr(overlay, "user_timing_overrides", {}).items()))
    return ScoringSettings(
        generation=getattr(overlay, "current_scenario_id", -1),
        rolling=bool(getattr(overlay, "pen_roll", True)),
        safety_intervention=False,                                   # the beta has no safety device scoring: always off, whatever pen_ats holds
        speed_limit_exceeded=bool(getattr(overlay, "pen_limit", True)),
        stop_shock=bool(getattr(overlay, "pen_jerk", True)),
        emergency_brake=bool(getattr(overlay, "pen_eb", True)),
        init_rules=rules,
        a_rank_ratio=float(getattr(overlay, "rank_a_ratio", 0.7)),
        timing_overrides=overrides)


def active(overlay):
    """The snapshot of the Run that is going on, else None (a scoring that is off or finished, or another scenario generation, is never served)."""
    snapshot = overlay.__dict__.get("_scoring_settings")
    if snapshot is None:
        return None
    if not getattr(overlay, "is_scoring_mode", False) or getattr(overlay, "is_scoring_finished", False):
        return None
    if snapshot.generation != getattr(overlay, "current_scenario_id", -1):
        return None
    return snapshot


def housekeeping(overlay):
    """Once per scoring tick: a snapshot that is no longer the Run's is dropped, never carried on."""
    if overlay.__dict__.get("_scoring_settings") is not None and active(overlay) is None:
        overlay._scoring_settings = None


def value(overlay, name):
    """One scoring setting: the snapshot while a Run is active, otherwise the live attribute (before the start). `init_rules` is a list of fresh dicts; `safety_intervention` is False in the beta."""
    snapshot = active(overlay)
    if name == "safety_intervention":
        return False
    if name == "init_rules":
        if snapshot is not None:
            return [{"end_idx": e, "apply": a, "release": r} for e, a, r in snapshot.init_rules]
        return getattr(overlay, "penalty_init_rules", DEFAULT_INIT_RULES)
    if snapshot is not None:
        return getattr(snapshot, name)
    attribute, fallback = LIVE[name]
    return getattr(overlay, attribute, fallback)


def timing_override(overlay, station_index):
    """(has_override, value): the override of a station for the scoring - the snapshot while a Run is active, otherwise the live F1 overrides."""
    snapshot = active(overlay)
    if snapshot is not None:
        for index, flag in snapshot.timing_overrides:
            if index == station_index:
                return True, flag
        return False, False
    live = getattr(overlay, "user_timing_overrides", {})
    if station_index in live:
        return True, live[station_index]
    return False, False
