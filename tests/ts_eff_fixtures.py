"""Fixtures of the effective station state tests (Stage P1; test equipment). WIRE-FAITHFUL: the sender (Current Class1.cs:936-968, Legacy LegacyStationTimeline.cs:536-547) COMPLETES the pair A departure and the pair B
arrival before it writes the STALIST, so the application receives the COMPLETED values as raw_arr / raw_dep. The older fixtures (tests/pt_scene.py) give -1 there and could not show a defect that the live S-02 run showed.

Fixture NAME grammar:  <scenario>__<values>__<framing>__<order>
  values  : orig = A departure / B arrival missing (-1: the ORIGINAL timetable values, the old fixture premise);  cmpl = the values the sender really puts on the wire (completed)
  framing : model = the pure inputs;  cur = the Current telemetry line;  leg = the Legacy line (AVAIL part, station group first). The application must reach the SAME state from cur and leg.
  order   : the host cursor around the stop:  stays (cursor stays on A, O0) / lag1 (leaves A one tick AFTER speed 0.0) / same (A->B in the very tick speed becomes 0.0, O1) / lead1 (B one tick BEFORE speed 0.0, O2) / na

The ticks around the stop are REAL (tests/p1data/s02_stop_profile_ticks.csv, the live S-02 run): 16-18 ms apart, speed 0.0030 km/h one tick before the first exact 0.0. Synthetic scenarios cycle the recorded delta
pattern; no fixed 16.7 ms is used."""
import csv
import os
import sys
import zlib
from dataclasses import dataclass, field
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import effective_station_state as ess  # noqa: E402
import hud_target_contract as H  # noqa: E402

DATA = os.path.join(HERE, "p1data")
TERMINAL_DEP_SENTINEL = 2147483647     # Class1.cs:110 (int.MaxValue): departureTime="t"
MARGIN_M = 3.0                         # the author range of every station of the route: +-3 m (card contract; it is not on the wire)
PAIRS = ((2, 3), (4, 5), (6, 7), (8, 9))
PAIR_MODES = ((2, 3, 0), (4, 5, 0), (6, 7, 0), (8, 9, 0))
W, X, A, B, A2, B2, Y, Z = 0, 1, 2, 3, 4, 5, 10, 11
VALUES = ("orig", "cmpl")


def _int(text):
    return int(float(text))


def host_stations():
    """The route as the HOST reports it (the S-02 live run): name, location, arrival, departure, default, stoppage."""
    out = []
    with open(os.path.join(DATA, "tbg12_station_probe.csv"), encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            dep = _int(r["departure_ms"])
            out.append({"index": _int(r["index"]), "name": r["name"], "location": float(r["location"]), "arr": _int(r["arrival_ms"]),
                        "dep": -1 if dep == TERMINAL_DEP_SENTINEL else dep, "default": _int(r["default_ms"]), "stop": _int(r["stoppage_ms"]),
                        "pass": r["pass"] == "True", "terminal": r["is_terminal"] == "True"})
    return out


def complete_like_sender(host):
    """The sender's completion, a port of Class1.cs:936-968. Valid for a route in which every station has a defined time (the TB-G route): the default-time fill and the position interpolation are not modelled."""
    out = []
    for h in host:
        arr, dep = h["arr"], h["dep"]
        assert arr > 0 or dep > 0, "route with an untimed station: interpolation is not modelled (%s)" % h["name"]
        if not h["terminal"] and arr > 0 and dep <= 0:
            dep = arr + h["stop"]
        elif dep > 0 and dep < TERMINAL_DEP_SENTINEL and arr <= 0:
            arr = max(0, dep - h["stop"])
        out.append(dict(h, arr=arr, dep=dep))
    return out


def stations(values):
    """values 'orig' | 'cmpl' -> the dict list of station entries as the application's STALIST parser builds them (name, location, raw_arr, raw_dep, def_time, stop_time, is_pass, is_terminal, is_timing)."""
    chosen = complete_like_sender(host_stations()) if values == "cmpl" else host_stations()
    return [{"name": h["name"], "is_timing": h["index"] != 0, "location": h["location"], "raw_arr": h["arr"], "raw_dep": h["dep"], "def_time": h["default"], "stop_time": h["stop"],
             "is_pass": h["pass"], "is_terminal": h["terminal"]} for h in chosen]


def rows(values):
    return tuple(ess.StationRow(i, s["raw_arr"], s["raw_dep"], s["is_pass"], s["is_terminal"]) for i, s in enumerate(stations(values)))


# -- the wire ----------------------------------------------------------------------------------------------------------------------------------------------------------------
def fmt_num(x):
    return str(int(x)) if (x == int(x) and abs(x) < 1e15) else repr(float(x))


def stalist_payload(values):
    chosen = complete_like_sender(host_stations()) if values == "cmpl" else host_stations()
    parts = []
    for h in chosen:
        timing = 1 if (h["index"] != 0 and (h["arr"] > 0 or h["dep"] > 0)) else 0       # Class1.cs:884-885, 933
        parts.append("=".join([h["name"], str(timing), fmt_num(h["location"]), str(h["arr"]), str(h["dep"]), str(h["default"]), str(h["stop"]), "1" if h["pass"] else "0", "1" if h["terminal"] else "0"]))
    return ",".join(parts)


def list_id(values, payload=None):
    return "%08X" % (zlib.crc32((payload if payload is not None else stalist_payload(values)).encode("utf-8")) & 0xFFFFFFFF)


def ptpair_part(values, pairs=PAIR_MODES, payload=None):
    return "PTPAIR:1:%s:12:%d:%s" % (list_id(values, payload), len(pairs), ";".join("%d-%d-%d" % p for p in pairs))


def offtgt_part(values, cursor_index, payload=None):
    host = host_stations()
    if cursor_index is None:
        return "OFFTGT:1:U:-1:12:%s:-1:-1:-1" % list_id(values, payload)
    return "OFFTGT:1:K:%d:12:%s:%s:%s:%s" % (cursor_index, list_id(values, payload), fmt_num(host[cursor_index]["location"]), fmt_num(MARGIN_M), fmt_num(MARGIN_M))


def stidx_part(values, tgt=-1, arr=-1, seq=0, payload=None):
    return "STIDX:1:%d:%d:%d:12:%s" % (tgt, arr, seq, list_id(values, payload))


def telemetry_line(framing, values, tick, sid=7, pairs=PAIR_MODES, payload=None):
    """One telemetry line of the free driving (the C# target is unset in free driving: STIDX tgt = arr = -1 as the live run logged; NEXTLOC -1 / NEXTTIME 0 are an ASSUMPTION - the path reads OFFTGT)."""
    core = ["SCENARIO_ID:%d" % sid, "TIME:%d" % tick.bve_ms, "LOCATION:%s" % tick.location, "SPEED:%s" % tick.speed, "BTYPE:Ecb", "BRK:N:0:8"]
    station = ["NEXTLOC:-1", "NEXTTIME:0", "ISPASS:0", "ISTIMING:0", "DOORDIR:0", "TERM:0", stidx_part(values, payload=payload), ptpair_part(values, pairs, payload), offtgt_part(values, tick.cursor, payload)]
    rest = ["DOOR:%d" % tick.door, "CAB:8:0", "PRATES:0_0.1_0.2_0.3_0.4_0.5_0.6_0.7_0.8:440.0", "JUMP:0"]
    if framing == "cur":
        return ",".join(core + station + rest)
    if framing == "leg":
        avail = "AVAIL:1:time+speed+loc+station+door+handle+brake_type+brake_cab+prates+jump"
        return ",".join(core[:1] + [avail] + station + core[1:] + rest)
    raise ValueError(framing)


# -- ticks ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Tick:
    bve_ms: int
    location: float
    speed: float
    cursor: Optional[int]
    door: int = 0


def real_profile():
    """The recorded S-02 ticks around the stop: [(bve_ms, location, speed_kmh)] and the index of the first tick whose speed is exactly 0.0."""
    out = []
    with open(os.path.join(DATA, "s02_stop_profile_ticks.csv"), encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            out.append((_int(r["bve_ms"]), float(r["location_m"]), float(r["speed_kmh"])))
    return out, next(i for i, (_, _, v) in enumerate(out) if v == 0.0)


def real_dt_pattern():
    prof, _ = real_profile()
    return [prof[i][0] - prof[i - 1][0] for i in range(1, len(prof))]


ORDERS = ("stays", "lag1", "same", "lead1")


def approach_and_stop(order, pad_after=40):
    prof, z = real_profile()
    flip = {"stays": 10 ** 9, "lag1": z + 1, "same": z, "lead1": z - 1}[order]
    return [Tick(ms, loc, v, B if i >= flip else A) for i, (ms, loc, v) in enumerate(prof[: z + 1 + pad_after])]


def _cycle_dt(n):
    pat = real_dt_pattern()
    return [pat[i % len(pat)] for i in range(n)]


def drive(start_ms, loc0, loc1, kmh, cursor_of_loc, door=0):
    ms, loc, ticks = start_ms, loc0, []
    mps = kmh / 3.6
    while loc < loc1:
        ticks.append(Tick(ms, round(loc, 4), kmh, cursor_of_loc(loc), door))
        dt = _cycle_dt(len(ticks) + 1)[len(ticks)]
        ms += dt
        loc += mps * dt / 1000.0
    return ticks


# the host cursor advances A->B when the train passes the A marker (H-marker) or when it leaves the A range (H-zone): the host rule is not public, so both are exercised
PASS_ADVANCE = {"marker": lambda loc: B if loc > 220.0 else A, "zone_exit": lambda loc: B if loc > 220.0 + MARGIN_M else A}


def pass_a_no_stop(advance="marker"):
    return drive(28890000, 200.0, 262.0, 15.0, PASS_ADVANCE[advance])


def restart_after_arrival():
    base = approach_and_stop("same", pad_after=10)
    last = base[-1]
    ms, loc, out = last.bve_ms, last.location, list(base)
    for i, dt in enumerate(_cycle_dt(400)):
        ms += dt
        speed = min(3.0, 0.02 * (i + 1))
        loc += (speed / 3.6) * dt / 1000.0
        out.append(Tick(ms, round(loc, 4), speed, B))
        if loc > 240.0:
            break
    return out


def pass_b_to_normal():
    base = restart_after_arrival()
    last = base[-1]
    return base + drive(last.bve_ms, last.location, 292.0, 12.0, lambda loc: A2 if loc > 270.0 else B)


# -- the pure inputs --------------------------------------------------------------------------------------------------------------------------------------------------------------
def display_time(values, tick):
    """The display target's time as the application derives it for the official owner (hud_target_contract.official_time on the entry the cursor names): what the sync hands the effective state."""
    if tick.cursor is None:
        return None
    entry = stations(values)[tick.cursor]
    t, _ = H.official_time(entry, tick.cursor, entry["location"], tick.location, tick.bve_ms, tick.door, ("s", "l"), None)
    return None if t <= 0 else t


def build_inputs(tick, values, pairs=PAIRS, pairset_ready=True, scoring=None):
    cursor = ess.Cursor("KNOWN", tick.cursor) if tick.cursor is not None else ess.Cursor("UNAVAILABLE", -1)
    loc = stations(values)[tick.cursor]["location"] if tick.cursor is not None else -1.0
    return ess.EffectiveInputs(rows(values), tuple(pairs) if pairset_ready else (), pairset_ready, cursor, H.select_time_kind(tick.door, loc, tick.location), tick.bve_ms,
                               display_time(values, tick), True, scoring if scoring is not None else ess.ScoringView())


def derive_ticks(ticks, values, **kw):
    return [(t, ess.derive(build_inputs(t, values, **kw))) for t in ticks]


# -- the scoring chain of C-12 (the machine VIEW the host reads) --------------------------------------------------------------------------------------------------------------
def chain_view(kind, t_a, deadline=None, a=A, b=B):
    """kind: wait_first / cancelled / restop_wait / recancelled / requested / awaiting_b / b_established"""
    crossed = frozenset({b})
    if kind == "wait_first":
        return ess.ScoringView(True, True, crossed, a, ess.MachineView("armed", 0, t_a + 10000, False, True, a))
    if kind == "cancelled":
        return ess.ScoringView(True, True, crossed, b, ess.MachineView("restop-wait", 0, None, False, True, a))
    if kind == "restop_wait":
        return ess.ScoringView(True, True, crossed, b, ess.MachineView("armed", 1, deadline, False, True, a))
    if kind == "recancelled":
        return ess.ScoringView(True, True, crossed, b, ess.MachineView("restop-wait", 1, None, False, True, a))
    if kind == "requested":
        return ess.ScoringView(True, True, crossed, b, ess.MachineView("requested", 2, None, False, True, a))
    if kind == "awaiting_b":
        return ess.ScoringView(True, True, crossed, b, ess.MachineView("completed", 2, None, True, True, a))
    if kind == "b_established":
        return ess.ScoringView(True, True, crossed, b, ess.MachineView("idle", 0, None, False, False, None))
    raise ValueError(kind)


def tbj_chain(t_a=28903264):
    """C-12 as ticks: [(label, Tick, ScoringView)]. window 1 = arrival + 10 s; cancel +3.2 s; re-stop +6 s (window to +11 s); re-cancel +8 s; re-stop +9 s (window to +14 s); request +14 s."""
    spec = [("first_0s", "wait_first", 0, None), ("first_3s", "wait_first", 3000, None), ("cancelled_3.2s", "cancelled", 3200, None), ("restop1_at_6s", "restop_wait", 6000, t_a + 11000),
            ("restop1_at_7s", "restop_wait", 7000, t_a + 11000), ("recancelled_8s", "recancelled", 8000, None), ("restop2_at_9s", "restop_wait", 9000, t_a + 14000),
            ("requested_14s", "requested", 14000, None), ("awaiting_b_14.1s", "awaiting_b", 14100, None), ("b_established_14.5s", "b_established", 14500, None)]
    return [(label, Tick(t_a + dt, 219.5764, 0.0, B if kind != "wait_first" else A), chain_view(kind, t_a, deadline)) for label, kind, dt, deadline in spec]
