"""Phase LC-2 (Legacy scoring integration) - the CURRENT / LEGACY EQUIVALENCE CONTRACT and the minimal scoring slice, as an executable CHARACTERIZATION (no product change).

WHAT IS FIXED HERE
  The Python scoring is ONE code path for both hosts. The same trajectory handed to the real managed Overlay in the shape of the Current sender and in the shape of the AtsEX
  Legacy sender (tests/lc_legacy_feed.py: AVAIL named, no DOORTIME, no CALCG on the first sample after a Jump) must give
    * the same normalized input state at every tick                       (E01)
    * the same scoring state / result at every tick                       (E02)
    * the same check points / history / latest station / StationIndex / target (E03, E06)
    * a check point TIME that differs by the DOORTIME and by nothing else (E04)
  and the minimal slice (start -> Jump -> departure -> next station -> stop-position / basic-braking / running-time scoring -> check point -> history -> terminal) holds its values (E05).
  E07 fixes the Retry meaning on both shapes, E08 the StationIndex / host-neutrality boundary of the Python scoring.

WHAT IS NOT FIXED HERE (stays with the other phases)
  Slice A (the Jump boundary stop-jerk, LC-A09/A09C/A10), the history of C-LOOP-2 (LC-A11), the Retry/Jump rows C-LJ-3/5 and C-SIDX-4 (LC-A13..A16) are RED rows of tests/red_lc_legacy_scoring.py and
  are not touched. The missing DOORTIME stays RED-COND (LC-A28, OD-LC-6): this file characterizes the difference, it does not decide it.

The trajectories contain no acceleration into the Jump (the train stands at the start): that is the one place where the two shapes DO differ (CALCG of the Jump line, LC-A09) and it is out of scope here.
Needs PyQt6 (skipped otherwise). The rigs are the ones of the D6 / SIA tests: no socket, no real clock, no Desktop log.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HAS_QT = importlib.util.find_spec("PyQt6") is not None

import lc_legacy_feed as F  # noqa: E402

SHAPES = ("current", "legacy")
BASE_HEAD = "cab7dce265429ee43775ecbaa4c42f450058a653"

# what the sender wrote, as the Overlay holds it after the line (the normalized INPUT); DOORTIME (bve_door_close_time_ms) is the known difference and is compared apart
INPUT_FIELDS = ("bve_time_ms", "bve_speed", "bve_location", "bve_next_loc", "bve_next_time", "bve_margin_b", "bve_margin_f", "bve_door", "bve_doordir", "bve_is_pass", "bve_term",
                "bve_brk_notch", "bve_brk_max", "bve_btype", "cab_brk_count", "cushion_min", "cushion_max", "bve_max_pressure", "bve_train_length", "bve_map_limits",
                "map_head_limit", "map_tail_limit", "bve_clear_dist", "bve_jump_count", "bve_tgt_idx", "bve_arr_idx", "bve_list_id", "bve_calc_g", "current_scenario_id",
                "setting_stop_distance")
# what the scoring made of it (the RESULT state)
RESULT_FIELDS = ("score", "is_scoring_mode", "is_scoring_finished", "is_official_jumping", "jump_lock", "has_departed", "is_first_station", "has_scored_stop_this_station",
                 "has_scored_time_this_station", "bb_state", "bb_apply_count", "bb_release_count", "stop_notch_state", "is_stopping_zone", "prev_next_loc")

# the two trajectories: STRONG = the one of tests/red_lc_legacy_scoring.py (a constant brake notch 4 and the holding notch 8: init-brake penalty, no basic-braking credit, no time credit);
# RICH = a stepwise brake (notch 3 then 1) and NEXTTIME near the departure: basic braking, running time and stop position are all credited.
PROFILES = {
    "strong": {"decel_notch": lambda n, total: 4, "stop_notch": 8, "next_time_offset": None, "depart": (18.0, 1010.0)},
    "rich": {"decel_notch": lambda n, total: 3 if n < total * 0.6 else 1, "stop_notch": 1, "next_time_offset": 5000, "depart": (3.6, 1000.2)},
}


class LC2Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        cls._profile_dir = tempfile.TemporaryDirectory(prefix="ts-lc2-")
        cls._saved_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
        os.environ["USERPROFILE"] = os.environ["HOME"] = cls._profile_dir.name
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["lc2"])
        import main
        import d6_rig
        import sia_managed_rig
        cls.main, cls.D, cls.MR = main, d6_rig, sia_managed_rig

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls._profile_dir.cleanup()

    # ---- the driver --------------------------------------------------------------------------------------------------------------------------------------------
    def fresh(self):
        """One rig at a time (two installed rigs would restore each other's fakes): the previous one is closed first; every snapshot a test keeps is a copy."""
        if getattr(self, "r", None) is not None:
            self.r.close()
        self.r = self.D.D6Rig(self.main)
        self.o = self.r.o
        self.addCleanup(self.r.close)
        return self.r

    def land(self, cmd, shape, t=36000000):
        r = self.r
        r.send(F.line(shape, 1, t, 0.0, 0.0, jump=1, discontinuity=True, NEXTLOC=1000.0))
        r.tick(2)
        r.complete(cmd["request_id"], location=0.0, time_ms=t, count=1)
        r.tick(2)
        return t

    def leg(self, shape, prof, t, loc0, loc1, tgt, arr, seq, prev=(-1, 0), door_at_end=True, jump=1, nextloc=None):
        """Drive loc0 -> loc1 (cruise 20 m/s, then the constant 0.5 m/s2 that ends 0.4 m short), then open the doors (the arrival: STIDX names the arrival candidate `arr`, event number `seq`)."""
        r, MR = self.r, self.MR
        nextloc = loc1 if nextloc is None else nextloc
        nt = {} if prof["next_time_offset"] is None else {"nt": prof["next_time_offset"]}

        def send(t, speed, loc, **kw):
            if nt:
                kw["NEXTTIME"] = t + nt["nt"]
            r.send(F.line(shape, 1, t, speed, loc, jump=jump, NEXTLOC=nextloc, **kw))

        sid_pre = MR.stidx(MR.STALIST, tgt, prev[0], prev[1])
        loc, v, a = loc0, 20.0, 0.5
        stop_at = loc1 - 0.4
        steps = 0
        while loc + v * v / (2 * a) < stop_at and steps < 300:
            t += 1000
            loc += v
            send(t, v * 3.6, loc, calcg=0.0, STIDX=sid_pre)
            r.tick(1, 0.1)
            steps += 1
        v = (2 * a * (stop_at - loc)) ** 0.5
        total, n = int(v / a) + 1, 0
        while v > 0.0:
            t += 1000
            nv = max(v - a, 0.0)
            loc = loc + (v + nv) / 2
            v = nv
            if v == 0.0:
                loc = stop_at
            send(t, v * 3.6, loc, calcg=-0.051 if v > 0.0 else 0.0, BRK="N:%d:8" % prof["decel_notch"](n, total), STIDX=sid_pre)
            r.tick(1, 0.1)
            n += 1
        t += 1000
        send(t, 0.0, stop_at, calcg=0.0, BRK="N:%d:8" % prof["stop_notch"], STIDX=sid_pre)
        r.tick(3, 0.1)
        if door_at_end:
            t += 1000
            send(t, 0.0, stop_at, calcg=0.0, DOOR=1, BRK="N:%d:8" % prof["stop_notch"], STIDX=MR.stidx(MR.STALIST, tgt, arr, seq))
            r.tick(3, 0.1)
        return t

    def phase(self, name):
        o = self.o
        self.phases.append((name, o.bve_tgt_idx, o.bve_arr_idx, len(o.save_data), o.save_data[-1]["station_index"] if o.save_data else None, o.score, o.bve_next_loc,
                            bool(o.is_scoring_finished)))

    def drive(self, shape, profile="rich", end_idx=2):
        """start -> Jump (STA, idx 0) -> A to B (arrival, check point) -> doors close, departure -> B to C (terminal arrival, scoring finish).
        Returns a dict: trace (one row per tick: input vector, result vector), phases, mid / final snapshots, the sender's DOORTIME as the Overlay holds it, and the Overlay."""
        prof = PROFILES[profile]
        r = self.fresh()
        o = self.o
        self.phases, trace = [], []
        raw_tick = r.tick

        def tick(*a, **k):
            res = raw_tick(*a, **k)
            trace.append((tuple(getattr(o, f, "<unset>") for f in INPUT_FIELDS), tuple(getattr(o, f, "<unset>") for f in RESULT_FIELDS), tuple(sorted(o.score_details.items()))))
            return res
        r.tick = tick
        MR = self.MR
        r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
        o.setting_end_idx = end_idx
        r.start_scoring_via_menu()
        cmd = r.last_command()
        self.phase("started")
        t = self.land(cmd, shape)
        self.phase("landed")
        t = self.leg(shape, prof, t, 100.0, 1000.0, 1, 1, 1)
        self.phase("arrived-B")
        mid = F.snapshot(o)
        t += 3000
        r.send(F.line(shape, 1, t, 0.0, 999.6, jump=1, NEXTLOC=1000.0, DOOR=0, **({} if prof["next_time_offset"] is None else {"NEXTTIME": t + prof["next_time_offset"]}),
                      STIDX=MR.stidx(MR.STALIST, 1, 1, 1)))
        r.tick(2, 0.1)
        self.phase("doors-closed")
        t += 2000
        speed, loc = prof["depart"]
        r.send(F.line(shape, 1, t, speed, loc, jump=1, calcg=0.05, NEXTLOC=2500.0, STIDX=MR.stidx(MR.STALIST, 2, 1, 1)))
        r.tick(2, 0.1)
        self.phase("departed-B")
        mid_dep = F.snapshot(o)
        t = self.leg(shape, prof, t, loc, 2500.0, 2, 2, 2, prev=(1, 1))
        self.phase("arrived-C")
        return {"trace": trace, "phases": list(self.phases), "mid": mid, "mid_dep": mid_dep, "final": F.snapshot(o), "cmd": cmd, "o": o, "t": t,
                "door_time": getattr(o, "bve_door_close_time_ms", "<unset>"), "save_data": [dict(c) for c in o.save_data]}

    def both(self, profile="rich"):
        return {shape: self.drive(shape, profile) for shape in SHAPES}


# =====================================================================================================================================================
# E01 - E04: the equivalence contract
# =====================================================================================================================================================
class E_Equivalence(LC2Base):
    def test_E01_the_legacy_shaped_input_normalizes_to_the_current_state_at_every_tick(self):
        for profile in PROFILES:
            res = self.both(profile)
            c, l = res["current"]["trace"], res["legacy"]["trace"]
            self.assertEqual(len(c), len(l), profile)
            self.assertGreater(len(c), 100, "a real trajectory")
            for i, (rc, rl) in enumerate(zip(c, l)):
                if rc[0] != rl[0]:
                    names = [n for n, a, b in zip(INPUT_FIELDS, rc[0], rl[0]) if a != b]
                    self.fail("%s: tick %d: the normalized input differs in %r" % (profile, i, names))

    def test_E01B_the_ground_groups_are_normalized_the_same_and_no_trainlen_keeps_the_default(self):
        """TRAINLEN / MAPLIMITS / MAPHEAD / MAPTAIL / CLEARDIST (Phase SI-1): the same state on both shapes; a line without TRAINLEN leaves the Overlay default on both shapes."""
        ground = dict(TRAINLEN="100.0", MAPLIMITS="0.0=27.8_500.0=22.2", MAPHEAD="27.8", MAPTAIL="22.2", CLEARDIST="640.0")
        seen = {}
        for shape in SHAPES:
            r = self.fresh()
            r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
            r.send(F.line(shape, 1, 36000000, 0.0, 0.0, **ground))
            r.tick(2)
            o = self.o
            seen[shape] = (o.bve_train_length, o.bve_map_limits, o.map_head_limit, o.map_tail_limit, o.bve_clear_dist, o.setting_stop_distance)
        self.assertEqual(seen["current"], seen["legacy"])
        self.assertEqual(seen["legacy"], (100.0, [(0.0, 27.8), (500.0, 22.2)], 27.8, 22.2, 640.0, 110))
        # no TRAINLEN on the wire: the Overlay keeps its own default (20 m) on both shapes - it is NOT replaced by a made-up value; whether a Legacy vehicle really supplies its length is LR-1 (LC-B02)
        for shape in SHAPES:
            r = self.fresh()
            r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
            r.send(F.line(shape, 1, 36000000, 0.0, 0.0))
            r.tick(2)
            self.assertEqual((self.o.bve_train_length, self.o.setting_stop_distance), (20.0, -1), shape)

    def test_E02_the_scoring_state_and_result_are_the_same_at_every_tick(self):
        for profile in PROFILES:
            res = self.both(profile)
            c, l = res["current"]["trace"], res["legacy"]["trace"]
            for i, (rc, rl) in enumerate(zip(c, l)):
                if rc[1] != rl[1] or rc[2] != rl[2]:
                    names = [n for n, a, b in zip(RESULT_FIELDS, rc[1], rl[1]) if a != b] + (["score_details"] if rc[2] != rl[2] else [])
                    self.fail("%s: tick %d: the scoring differs in %r" % (profile, i, names))

    def test_E03_check_points_history_and_latest_station_are_the_same(self):
        for profile in PROFILES:
            res = self.both(profile)
            cc, cl = res["current"]["save_data"], res["legacy"]["save_data"]
            self.assertEqual(len(cc), len(cl))
            self.assertEqual(len(cc), 2, "one check point per arrival; the start and station B; the terminal adds none")
            for a, b in zip(cc, cl):
                a, b = dict(a), dict(b)
                a.pop("time_ms"), b.pop("time_ms")
                self.assertEqual(a, b, "every item of a check point except its time (identity, location, score, score_details, target, name, stop error)")
            self.assertEqual([c["station_index"] for c in cl], [0, 1])
            self.assertEqual(cl[-1]["station_index"], cc[-1]["station_index"], "the latest station")
            self.assertEqual(F.differences(res["current"]["final"], res["legacy"]["final"]), ["checkpoint-time"])
            self.assertEqual(F.differences(res["current"]["mid"], res["legacy"]["mid"]), ["checkpoint-time"])
            self.assertEqual(F.differences(res["current"]["mid_dep"], res["legacy"]["mid_dep"]), ["checkpoint-time"])

    def test_E04_the_check_point_time_differs_by_the_doortime_and_nothing_else(self):
        for profile in PROFILES:
            res = self.both(profile)
            tc = [c["time_ms"] for c in res["current"]["save_data"]]
            tl = [c["time_ms"] for c in res["legacy"]["save_data"]]
            self.assertEqual(tc[0], tl[0], "the start check point never gets the door time")
            self.assertEqual(tc[1] - tl[1], F.DOOR_CLOSE_TIME_MS, "the delayed arrival of B gets exactly the door close time")
            self.assertEqual(res["current"]["door_time"], F.DOOR_CLOSE_TIME_MS)
            self.assertEqual(res["legacy"]["door_time"], "<unset>", "the Legacy sender writes no DOORTIME: the Overlay holds none (the added value is 0)")

    def test_E04B_doortime_never_changes_a_score_and_a_missing_doortime_is_a_zero_door_time(self):
        """The DOORTIME is a TIME only. (a) any value: same score / details / popups; the check point time moves by exactly the value. (b) Legacy == Current with DOORTIME 0 in every item."""
        legacy = self.drive("legacy")
        for door_ms in (0, 3000, F.DOOR_CLOSE_TIME_MS, 9999):
            with mock.patch.object(F, "DOOR_CLOSE_TIME_MS", door_ms):
                cur = self.drive("current")
            self.assertEqual(F.differences(cur["final"], legacy["final"], ignore=("checkpoint-time",)), [], "door %d: a score / flag / station differs" % door_ms)
            self.assertEqual(cur["save_data"][1]["time_ms"] - legacy["save_data"][1]["time_ms"], door_ms)
            self.assertEqual(cur["save_data"][0]["time_ms"], legacy["save_data"][0]["time_ms"])
            if door_ms == 0:
                self.assertEqual(F.differences(cur["final"], legacy["final"]), [], "Legacy (no DOORTIME) is Current with DOORTIME 0 in every item, the check point times included")
            self.assertEqual([r[2] for r in cur["trace"]], [r[2] for r in legacy["trace"]], "the score details at every tick")


# =====================================================================================================================================================
# E05 - E06: the minimal slice (absolute values) and the station / target progression
# =====================================================================================================================================================
# the minimal slice of cab7dce / 52a11a9, measured (LC-2): phases = (name, target index, arrival index, history length, latest check point station, score, NEXTLOC, finished)
EXPECTED = {
    "strong": {
        "score": 400,
        "details": {"time": 0, "stop": 600, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": -200, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0},
        "popups": [("停止位置", "停止位置 +300")],
        "checkpoints": [(0.0, 0, "A"), (999.6, 200, "不明な駅")],
        "phases": [("started", 1, -1, 1, 0, 0, 1000.0, False), ("landed", 1, -1, 1, 0, 0, 1000.0, False), ("arrived-B", 1, 1, 2, 1, 200, 1000.0, False),
                   ("doors-closed", 1, 1, 2, 1, 200, 1000.0, False), ("departed-B", 2, 1, 2, 1, 200, 2500.0, False), ("arrived-C", 2, 2, 2, 1, 400, 2500.0, True)],
    },
    "rich": {
        "score": 1900,
        "details": {"time": 300, "stop": 600, "base_brake": 1000, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0},
        "popups": [("停止位置", "停止位置 +300"), ("基本制動", "階段制動階段緩め成功!!!"), ("基本制動", "基本制動 +500")],
        "checkpoints": [(0.0, 0, "A"), (999.6, 800, "不明な駅")],
        "phases": [("started", 1, -1, 1, 0, 0, 1000.0, False), ("landed", 1, -1, 1, 0, 0, 1000.0, False), ("arrived-B", 1, 1, 2, 1, 800, 1000.0, False),
                   ("doors-closed", 1, 1, 2, 1, 800, 1000.0, False), ("departed-B", 2, 1, 2, 1, 1100, 2500.0, False), ("arrived-C", 2, 2, 2, 1, 1900, 2500.0, True)],
    },
}


class E_MinimalSlice(LC2Base):
    def test_E05_the_minimal_slice_holds_its_values_on_both_shapes(self):
        for profile, expect in EXPECTED.items():
            res = self.both(profile)
            for shape in SHAPES:
                fin = res[shape]["final"]
                self.assertEqual(fin["score"], expect["score"], "%s/%s" % (profile, shape))
                self.assertEqual(fin["details"], expect["details"], "%s/%s" % (profile, shape))
                self.assertEqual(fin["popups"], expect["popups"], "%s/%s" % (profile, shape))
                self.assertEqual((fin["scoring"], fin["finished"], fin["jumping"], fin["jump_lock"]), (True, True, False, False), "%s/%s" % (profile, shape))
                self.assertEqual([(c[0], c[1], c[2]) for c in fin["checkpoints"]], expect["checkpoints"], "%s/%s" % (profile, shape))

    def test_E06_the_station_index_and_target_progression_is_the_same_and_pinned(self):
        for profile, expect in EXPECTED.items():
            res = self.both(profile)
            self.assertEqual(res["current"]["phases"], res["legacy"]["phases"], profile)
            self.assertEqual(res["legacy"]["phases"], expect["phases"], profile)

    def test_E06B_the_start_and_the_jump_request_are_the_same_on_both_shapes(self):
        import jump_wire
        seen = {}
        for shape in SHAPES:
            res = self.drive(shape)
            req = jump_wire.parse_request(res["cmd"]["text"])[0]
            cmds = [c for c in self.r.jump_commands() if not c.get("other")]
            seen[shape] = (req.kind, req.station_index, len(cmds))
        self.assertEqual(seen["current"], seen["legacy"])
        self.assertEqual(seen["legacy"], ("STA", 0, 1), "exactly one STA request for index 0; no second request during the whole slice")


# =====================================================================================================================================================
# E07: Retry on both shapes
# =====================================================================================================================================================
class E_Retry(LC2Base):
    def test_E07_a_retry_from_station_b_means_the_same_on_both_shapes(self):
        """Retry (index 0, the start check point) after the arrival at B: accepted, exactly one request, the score is rolled back at the request, the history is cut only at the settlement; the same on both shapes."""
        import jump_wire
        out = {}
        for shape in SHAPES:
            prof = PROFILES["rich"]
            r = self.fresh()
            o = self.o
            r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
            o.setting_end_idx = 2
            r.start_scoring_via_menu()
            cmd = r.last_command()
            t = self.land(cmd, shape)
            t = self.leg(shape, prof, t, 100.0, 1000.0, 1, 1, 1)
            n_cmd = len([c for c in r.jump_commands() if not c.get("other")])
            before = (o.score, len(o.save_data))
            self.assertEqual(before, (800, 2))
            res = self.main.execute_retry(o, 0, False)
            cmds = [c for c in r.jump_commands() if not c.get("other")]
            sent = cmds[-1]
            req = jump_wire.parse_request(sent["text"])[0]
            during = (res.accepted, res.reason, len(cmds) - n_cmd, (req.kind, req.station_index), o.is_official_jumping, (o.score, len(o.save_data)))
            t2 = t + 5000
            r.send(F.line(shape, 1, t2, 0.0, 0.0, jump=2, discontinuity=True, NEXTLOC=1000.0, STIDX=self.MR.stidx(self.MR.STALIST, 1, -1, 0)))
            r.tick(2)
            r.complete(sent["request_id"], location=0.0, time_ms=t2, count=2, kind="STA", index=0)
            r.tick(3)
            snap = F.snapshot(o)
            after = (o.score, len(o.save_data), o.is_official_jumping, o.jump_lock, o.bve_tgt_idx, [c["station_index"] for c in o.save_data], o.is_scoring_mode, o.is_scoring_finished)
            out[shape] = (during, after, snap["details"])
        self.assertEqual(out["current"], out["legacy"])
        during, after, _ = out["legacy"]
        self.assertEqual(during[:5], (True, "ok", 1, ("STA", 0), True))
        self.assertEqual(during[5], (0, 2), "the request rolls the score back to the chosen check point (0) at once; the history (2) is cut only at the settlement")
        self.assertEqual(after, (0, 1, False, True, -1, [0], True, False), "settled: score 0, history cut to the start check point, jump released, jump lock set again, scoring goes on")


# =====================================================================================================================================================
# E08: boundaries
# =====================================================================================================================================================
def _code(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        text = fh.read()
    return "\n".join(re.sub(r"#.*$", "", ln) for ln in text.splitlines())


class E_Boundary(unittest.TestCase):
    def test_E08_the_python_scoring_has_no_host_branch(self):
        code = _code("scoring_logic.py")
        for pat in (r"(?i)\blegacy\b", r"(?i)atsex", r"(?i)bveex", r"telemetry_gate", r"\.availability\b", r"(?i)\bavail(able)?_groups\b", r"(?i)is_legacy|is_current|host_kind|sender_kind"):
            self.assertIsNone(re.search(pat, code), "scoring_logic.py names the host: %s" % pat)
        self.assertEqual(len(re.findall(r"bve_door_close_time_ms", code)), 1, "the DOORTIME is read in exactly one place")
        self.assertIn("getattr(self, 'bve_door_close_time_ms', 0)", code, "an absent DOORTIME is the value 0 (not a branch)")

    def test_E08B_the_station_identity_is_never_searched_by_distance_in_the_scoring(self):
        code = _code("scoring_logic.py")
        hits = re.findall(r"[^\n]*\[\"location\"\][^\n]*", code)
        self.assertEqual(len(hits), 2, "the only reads of a station location: the jump target and the VERIFICATION of the departure index: %r" % (hits,))
        self.assertTrue(any("ideal_loc = station[" in h for h in hits))
        self.assertTrue(any("prev_idx_verified" in h and "<= 0.01" in h for h in hits))
        self.assertIsNone(re.search(r"(min|max|sorted)\([^\n]*(location|station_list|stations)[^\n]*key\s*=", code), "a nearest-station search")
        self.assertIsNone(re.search(r"abs\(\s*st\[\"location\"\]\s*-\s*(p_loc|self\.bve_next_loc)\s*\)\s*<\s*1\.0", code), "the old distance search is back")

    def test_E08C_the_season2_files_are_byte_identical_to_the_base(self):
        base = os.environ.get("LC_BASE", BASE_HEAD)
        x_paths = ("station_identity.py", "official_target_contract.py", "hud_target_contract.py", "station_index_contract.py",
                   "TsScoringPlugin/Handshake/Shared/ObservationLog.cs", "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs",
                   "TsScoringPlugin/Handshake/Bridge/Legacy/src/TsScoringLegacyBridge.cs", "TsScoringPlugin/Handshake/Bridge/src/ScenarioObserver.cs",
                   "TsScoringPlugin/Handshake/Bridge/src/ScenarioReadyTracker.cs")
        try:
            known = subprocess.run(["git", "cat-file", "-e", base + "^{commit}"], cwd=ROOT, capture_output=True).returncode == 0
        except OSError:
            known = False
        if not known:
            self.skipTest("git or the base commit %s is not available" % base[:7])
        self.assertEqual(subprocess.run(["git", "diff", "--quiet", base, "--"] + list(x_paths), cwd=ROOT).returncode, 0, "a Season 2 file differs from %s" % base)


if __name__ == "__main__":
    unittest.main()
