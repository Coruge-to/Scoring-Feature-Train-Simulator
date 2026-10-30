"""Phase LC-1 (Legacy scoring integration) - the FEED fixture: the same trajectory handed to the REAL managed Overlay in the shape of the Current sender and in the shape of
the AtsEX Legacy sender, and the snapshot of what the scoring did with it. Not a unit test (the name does not start with test_).

THE TWO SHAPES (cab7dce, checked in LegacyTelemetrySession.cs / Class1.cs):
  * current : AVAIL absent (= everything available); CALCG on EVERY line (the Jump line carries CALCG:0.00000); DOORTIME on every line.
  * legacy  : AVAIL = the groups the Legacy sender really announces (LEGACY_AVAIL); NO DOORTIME at all (Handshake-PhaseL3-LegacyTelemetry.md: "X"); CALCG is NOT written on the
              first sample after a discontinuity (a Jump: LegacyTelemetrySession.cs haveLastSample=false -> `if (haveLastSample)` guards the CALCG group) and on the first sample of an epoch;
              TRAINLEN / MAPLIMITS / CLEARDIST / MAPHEAD are written when readable (Phase SI-1, LegacyGroundLimits.cs) so they are NOT a difference any more.
Nothing here is a new product rule: the shapes are what the senders write today. The KNOWN DIFFERENCES between the two shapes (DOORTIME, the CALCG of the Jump line) are the only
ones the equivalence rows may report.
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
LEGACY_AVAIL = ["time", "speed", "loc", "grad", "station", "door", "handle", "brake_type", "brake_cab", "prates", "trainlen", "maplimit", "maplimit_ahead", "calcg", "jump", "meta"]
DOOR_CLOSE_TIME_MS = 4600           # the DoorSet.StandardCloseTime of the Current sender (the order of magnitude Night C measured: "about 4.6 s")

KNOWN_DIFFERENCES = ("doortime", "calcg-on-jump-line")


def _dedupe(text, keys):
    """MR.tele writes defaults (NEXTLOC, BRK, JUMP ...) and then appends the given keys: a real sender writes each key once, and the STIDX NEXTLOC invariant reads the FIRST
    NEXTLOC of a line - so for every key that the caller overrides only the LAST part is kept."""
    names = set(k.upper() for k in keys) | {"BRK"}
    parts = text.split(",")
    last = {}
    for i, p in enumerate(parts):
        last[p.split(":", 1)[0]] = i
    return ",".join(p for i, p in enumerate(parts) if p.split(":", 1)[0] not in names or last[p.split(":", 1)[0]] == i)

def line(shape, sid, time_ms, speed, loc, jump=0, calcg=0.0, discontinuity=False, **keys):
    """One telemetry line of `shape` ('current' | 'legacy'). `discontinuity` marks the first sample after a Jump (Legacy: no CALCG; Current: CALCG:0.00000)."""
    keys = dict(keys)
    keys["JUMP"] = jump
    if shape == "current":
        keys["CALCG"] = "%.5f" % (0.0 if discontinuity else calcg)
        keys["DOORTIME"] = DOOR_CLOSE_TIME_MS
        return _dedupe(MR.tele(sid, time_ms=time_ms, speed=speed, loc=loc, **keys), keys)
    if shape == "legacy":
        if not discontinuity:
            keys["CALCG"] = "%.5f" % calcg
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
