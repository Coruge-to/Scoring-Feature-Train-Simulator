"""Phase LC-1 (Legacy scoring integration) - the FEED fixture: the same trajectory handed to the REAL managed Overlay in the shape of the Current sender and in the shape of
the AtsEX Legacy sender, and the snapshot of what the scoring did with it. Not a unit test (the name does not start with test_).

THE TWO SHAPES (as the senders write them after the stop-jerk scoring moved to the official AccelerationZ; CALCG is retired from both):
  * current : AVAIL absent (= everything available); ACCELZ on EVERY line (the official AccelerationZ, m/s^2, needs no previous sample); DOORTIME on every line.
  * legacy  : AVAIL = the groups the Legacy sender really announces (LEGACY_AVAIL, accelz included); NO DOORTIME at all (Handshake-PhaseL3-LegacyTelemetry.md: "X"); ACCELZ on every line too;
              TRAINLEN / MAPLIMITS / CLEARDIST / MAPHEAD are written when readable (Phase SI-1, LegacyGroundLimits.cs) so they are NOT a difference any more.
`line(..., calcg=g)` keeps its old name: g is the deceleration in G as the old tests wrote it (negative while braking) and is written as ACCELZ = g * 9.80665 (m/s^2, the same sign as the
official value). `old_sender_calcg=x` writes a retired CALCG part on purpose (an old sender): the application must ignore it.
Nothing here is a new product rule. The KNOWN DIFFERENCE between the two shapes (DOORTIME) is the only one the equivalence rows may report.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sia_managed_rig as MR  # noqa: E402

# the groups of the Legacy sender that matter to the scoring (no doortime, no bcp / bpp). jump is announced only while the Legacy Jump control plane is open (LJX-1).
LEGACY_AVAIL = ["time", "speed", "loc", "grad", "station", "door", "handle", "brake_type", "brake_cab", "prates", "trainlen", "maplimit", "maplimit_ahead", "accelz", "jump", "meta"]
DOOR_CLOSE_TIME_MS = 4600           # the DoorSet.StandardCloseTime of the Current sender (the order of magnitude Night C measured: "about 4.6 s")

KNOWN_DIFFERENCES = ("doortime",)
STANDARD_GRAVITY = 9.80665


def _dedupe(text, keys):
    """MR.tele writes defaults (NEXTLOC, BRK, JUMP ...) and then appends the given keys: a real sender writes each key once, and the STIDX NEXTLOC invariant reads the FIRST
    NEXTLOC of a line - so for every key that the caller overrides only the LAST part is kept."""
    names = set(k.upper() for k in keys) | {"BRK"}
    parts = text.split(",")
    last = {}
    for i, p in enumerate(parts):
        last[p.split(":", 1)[0]] = i
    return ",".join(p for i, p in enumerate(parts) if p.split(":", 1)[0] not in names or last[p.split(":", 1)[0]] == i)

def line(shape, sid, time_ms, speed, loc, jump=0, calcg=0.0, discontinuity=False, old_sender_calcg=None, **keys):
    """One telemetry line of `shape` ('current' | 'legacy'). The official ACCELZ part is calcg * 9.80665 (m/s^2) unless the caller gives ACCELZ itself; `discontinuity` is kept for the
    old call sites (the official value follows no speed discontinuity, so both senders write the same part). `old_sender_calcg` adds a retired CALCG part."""
    keys = dict(keys)
    keys["JUMP"] = jump
    if "ACCELZ" in keys and keys["ACCELZ"] is None:
        del keys["ACCELZ"]                              # ACCELZ=None: a line that carries no ACCELZ part
    elif "ACCELZ" not in keys:
        keys["ACCELZ"] = "%.6f" % (calcg * STANDARD_GRAVITY)
    if old_sender_calcg is not None:
        keys["CALCG"] = "%.5f" % old_sender_calcg
    if shape == "current":
        keys["DOORTIME"] = DOOR_CLOSE_TIME_MS
        return _dedupe(MR.tele(sid, time_ms=time_ms, speed=speed, loc=loc, **keys), keys)
    if shape == "legacy":
        return _dedupe(MR.tele(sid, time_ms=time_ms, speed=speed, loc=loc, avail=LEGACY_AVAIL, **keys), keys)
    raise ValueError(shape)


def snapshot(o):
    """What the scoring produced (the comparable result): totals, details, the texts of the popups, the check points (position, score, station) and the flags."""
    popups = [(p.get("category"), p.get("text")) for p in getattr(o, "popups", [])]
    cps = [(round(c["loc"], 3), c["score"], c.get("station_name"), c.get("time_ms")) for c in o.save_data]
    return {
        "score": o.score,
        "details": dict(o.score_details),
        "popups": popups,
        "checkpoints": cps,
        "scoring": bool(o.is_scoring_mode),
        "finished": bool(o.is_scoring_finished),
        "jumping": bool(o.is_official_jumping),
        "jump_lock": bool(o.jump_lock),
    }


def differences(a, b, ignore=()):
    """The keys of two snapshots that differ (a checkpoint time is compared apart so that the DOORTIME difference is reported by its own name)."""
    out = []
    for k in sorted(set(a) | set(b)):
        if k in ignore:
            continue
        if k == "checkpoints":
            pa = [c[:3] for c in a[k]]
            pb = [c[:3] for c in b[k]]
            if pa != pb:
                out.append(k)
            ta = [c[3] for c in a[k]]
            tb = [c[3] for c in b[k]]
            if ta != tb and "checkpoint-time" not in ignore:
                out.append("checkpoint-time")
        elif a.get(k) != b.get(k):
            out.append(k)
    return out
