"""Phase LC-1 (Legacy scoring integration) - the RED / CHARACTERIZATION / GUARD ledger of the PYTHON part (an executable specification index; NOT a discoverable unit test: the file
name does not start with test_).

Usage:   python -B tests/red_lc_legacy_scoring.py [--expect red|green] [--only LC-A09,LC-A11]      (needs PyQt6: do NOT use `python -I`)
  --expect red   (default, the state of cab7dce): every row must show its PREDICTED verdict. RED rows must FAIL by an AssertionError that contains the declared reason (a RED that fails for
                 another reason, or errors, is INVALID); CHAR / GUARD rows must PASS.
  --expect green (after the LC implementation): every row except the RED-CONDITIONAL ones must PASS.
Kinds:  RED = fails today for the stated reason; CHAR = pins what the code does today (passes, never inverted); GUARD = an invariant that must keep holding;
        RED-COND = a RED that only becomes a requirement after an Owner decision (OD-LC-6 DOORTIME).
One row per id: `ID | kind | verdict | predicted | reason`.   Exit code 0 = every row as predicted.

The Legacy-shaped feed (tests/lc_legacy_feed.py) is what the AtsEX Legacy sender writes today (no DOORTIME, no CALCG on the first sample after a Jump, AVAIL named). Nothing here writes
outside a temporary profile folder; the Overlay is the real one against the recorders of tests/sia_rig.py (UDP 54321 / 54322 are never bound or sent to).
"""
import os
import subprocess
import sys
import tempfile
import traceback
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.TemporaryDirectory(prefix="ts-lc1-")
os.environ["USERPROFILE"] = _TMP.name
os.environ["HOME"] = _TMP.name

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:       # pragma: no cover
    HAS_QT = False

import lc_legacy_feed as F  # noqa: E402

ROWS = {}               # id -> dict(kind, reason, note)


def lc(rid, kind, reason="", note=""):
    assert kind in ("RED", "CHAR", "GUARD", "RED-COND"), kind

    def deco(fn):
        fn.lc = rid
        ROWS[rid] = {"kind": kind, "reason": reason, "note": note, "name": fn.__name__}
        return fn
    return deco


class Base(unittest.TestCase):
    """The direct scene (no managed plumbing): the real Overlay, the telemetry-free way of tests/test_char_stop_door_arrival_st0.py."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["lc1"])
        import main
        import scoring_logic
        import sia_rig as R
        cls.main, cls.S, cls.R = main, scoring_logic, R

    def setUp(self):
        self.rig = self.R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.t = 100.0

    def stations(self):
        R = self.R
        out = []
        for name, loc, term in (("A", 0.0, False), ("B", 1000.0, False), ("C", 2500.0, True)):
            d = R.station(name, loc, terminal=term)
            d.update(def_time=-1, raw_dep=-1, stop_time=15000)
            out.append(d)
        return out

    def scoring_scene(self):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.station_list = self.stations()
        o.setting_end_idx = 2
        o.bve_next_loc = o.prev_next_loc = 1000.0
        o.bve_margin_b = o.bve_margin_f = 5.0
        o.has_departed = True
        o.is_first_station = False
        o.is_first_udp = False
        o.bve_time_ms = 36000000
        self.R.bind_identity(o)
        return o

    def step(self, dt=0.1, speed=None, calc_g=None, loc=None, jump=None, official=None):
        o = self.o
        self.t += dt
        o.bve_time_ms += int(round(dt * 1000))
        if speed is not None:
            o.bve_speed = speed
        if calc_g is not None:
            o.bve_calc_g = calc_g
        if loc is not None:
            o.bve_location = loc
        if jump is not None:
            o.bve_jump_count = jump
        if official is not None:
            o.is_official_jumping = official
        self.S.update_physics_and_scoring(o, self.t, dt)

    def jerk_popups(self):
        return [p["text"] for p in self.o.popups if p.get("category") == "停車時衝動"]

    def accelerate(self, n=20, g=0.08):
        """n steps of an accelerating train (calc_g = +g: the sender writes the acceleration as a positive CALCG)."""
        for i in range(n):
            self.step(speed=5.0 + 0.3 * i, calc_g=g, loc=100.0 + 0.6 * i)


class ManagedBase(unittest.TestCase):
    """The managed rig of the D6 tests: strict data plane, jump client, the published Caller state."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["lc1m"])
        import main
        import d6_rig
        import sia_managed_rig
        cls.main, cls.D, cls.MR = main, d6_rig, sia_managed_rig

    def setUp(self):
        self.r = self.D.D6Rig(self.main)
        self.o = self.r.o
        self.addCleanup(self.r.close)

    def start(self, shape="legacy", end_idx=2):
        r, o = self.r, self.o
        r.go_active(**({"avail": F.LEGACY_AVAIL} if shape == "legacy" else {}))
        o.setting_end_idx = end_idx
        r.start_scoring_via_menu()
        return r.last_command()

    def commands(self):
        return [c for c in self.r.jump_commands() if not c.get("other")]

    def land(self, cmd, shape="legacy", t=36000000):
        """BVE jumped (the sender's JUMP counter moves; Legacy: the first sample after the discontinuity has no CALCG), then the completion of the request arrives."""
        r = self.r
        r.send(F.line(shape, 1, t, 0.0, 0.0, jump=1, discontinuity=True, NEXTLOC=1000.0))
        r.tick(2)
        r.complete(cmd["request_id"], location=0.0, time_ms=t, count=1)
        r.tick(2)
        return t

    def leg(self, shape, t, loc0, loc1, nextloc, tgt, arr, seq, door_at_end=True, jump=1, prev=(-1, 0)):
        """Drive from loc0 to loc1 (an approach that brakes to a stop 0.4 m short), then open the doors (the arrival: STIDX names the arrival candidate `arr`, event number `seq`)."""
        r, MR = self.r, self.MR
        loc, v, a = loc0, 20.0, 0.5                       # cruise at 20 m/s, then the constant 0.5 m/s2 (0.051 G) that ends 0.4 m short of the target
        stop_at = loc1 - 0.4
        steps = 0
        while loc + v * v / (2 * a) < stop_at and steps < 300:
            t += 1000
            loc += v
            r.send(F.line(shape, 1, t, v * 3.6, loc, jump=jump, calcg=0.0, NEXTLOC=nextloc, STIDX=MR.stidx(MR.STALIST, tgt, prev[0], prev[1])))
            r.tick(1, 0.1)
            steps += 1
        d = stop_at - loc
        v = (2 * a * d) ** 0.5
        while v > 0.0:
            t += 1000
            nv = max(v - a, 0.0)
            loc = loc + (v + nv) / 2
            v = nv
            if v == 0.0:
                loc = stop_at
            r.send(F.line(shape, 1, t, v * 3.6, loc, jump=jump, calcg=-0.051 if v > 0.0 else 0.0, NEXTLOC=nextloc, BRK="N:4:8", STIDX=MR.stidx(MR.STALIST, tgt, prev[0], prev[1])))
            r.tick(1, 0.1)
        t += 1000
        r.send(F.line(shape, 1, t, 0.0, stop_at, jump=jump, calcg=0.0, NEXTLOC=nextloc, BRK="N:8:8", STIDX=MR.stidx(MR.STALIST, tgt, prev[0], prev[1])))
        r.tick(3, 0.1)
        if door_at_end:
            t += 1000
            r.send(F.line(shape, 1, t, 0.0, stop_at, jump=jump, calcg=0.0, NEXTLOC=nextloc, DOOR=1, BRK="N:8:8", STIDX=MR.stidx(MR.STALIST, tgt, arr, seq)))
            r.tick(3, 0.1)
        return t
    def run_trajectory(self, shape):
        """start -> Jump(STA, idx 0) -> A to B (arrival, check point) -> doors close, B to C (terminal arrival, scoring-finish). Returns the snapshot after B and the final one."""
        cmd = self.start(shape)
        t = self.land(cmd, shape)
        t = self.leg(shape, t, 100.0, 1000.0, 1000.0, 1, 1, 1)
        mid = F.snapshot(self.o)
        r, MR = self.r, self.MR
        t += 3000
        r.send(F.line(shape, 1, t, 0.0, 999.6, jump=1, NEXTLOC=1000.0, DOOR=0, STIDX=MR.stidx(MR.STALIST, 1, 1, 1)))
        r.tick(2, 0.1)
        t += 2000
        r.send(F.line(shape, 1, t, 18.0, 1010.0, jump=1, calcg=0.05, NEXTLOC=2500.0, STIDX=MR.stidx(MR.STALIST, 2, 1, 1)))
        r.tick(2, 0.1)
        t = self.leg(shape, t, 1010.0, 2500.0, 2500.0, 2, 2, 2, prev=(1, 1))
        return mid, F.snapshot(self.o), cmd


# ===================================================================================================================================================
# A. the minimal slice on the Legacy-shaped feed (CHAR: the contract holds today; Season 2 proved it on the real machine)
# ===================================================================================================================================================
class A_Slice(ManagedBase):
    @lc("LC-A01", "CHAR", note="the scoring start on a Legacy-shaped feed sends exactly one STA request for index 0 and keeps the scoring on")
    def test_A01_start_sends_one_sta_request(self):
        cmd = self.start("legacy")
        cmds = self.commands()
        self.assertEqual(len(cmds), 1)
        self.r.tick(5)
        self.assertEqual(len(self.commands()), 1, "no second request")
        import jump_wire
        req = jump_wire.parse_request(cmd["text"])[0]
        self.assertEqual((req.kind, req.station_index), ("STA", 0))
        self.assertTrue(self.o.is_scoring_mode and self.o.is_official_jumping)

    @lc("LC-A02", "CHAR", note="after the Jump and its completion the official jump is released and the target is the requested next station")
    def test_A02_landing_releases_the_jump(self):
        cmd = self.start("legacy")
        self.land(cmd, "legacy")
        o = self.o
        self.assertFalse(o.is_official_jumping)
        self.assertIsNone(o.jump_expectation)
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(o.bve_tgt_idx, 1)

    @lc("LC-A03", "CHAR", note="the first departure releases the jump lock (the existing departure rule) on the Legacy-shaped feed")
    def test_A03_first_departure_releases_the_lock(self):
        cmd = self.start("legacy")
        t = self.land(cmd, "legacy")
        self.assertTrue(self.o.jump_lock)
        MR = self.MR
        t += 20000
        self.r.send(F.line("legacy", 1, t, 30.0, 100.0, jump=1, calcg=0.05, NEXTLOC=1000.0, STIDX=MR.stidx(MR.STALIST, 1)))
        self.r.tick(2, 0.1)
        self.assertFalse(self.o.jump_lock)
        self.assertTrue(self.o.has_departed)

    def _both(self):
        results = {}
        for shape in ("current", "legacy"):
            self.r.close()
            self.r = self.D.D6Rig(self.main)
            self.o = self.r.o
            results[shape] = self.run_trajectory(shape)
        return results

    @lc("LC-A04", "CHAR", note="the stop-position score of the first stop is made on the Legacy-shaped feed")
    def test_A04_stop_position_scored(self):
        outcome = {}
        for shape in ("current", "legacy"):
            self.r.close()
            self.r = self.D.D6Rig(self.main)
            self.o = self.r.o
            cmd = self.start(shape, end_idx=1)               # B is the end station: its stop is scored and the scoring finishes
            t = self.land(cmd, shape)
            self.leg(shape, t, 100.0, 1000.0, 1000.0, 1, 1, 1)
            outcome[shape] = F.snapshot(self.o)
        leg = outcome["legacy"]
        self.assertTrue(leg["finished"], leg)
        self.assertEqual(leg["details"]["stop"], 300, leg["details"])
        self.assertIn(("停止位置", "停止位置 +300"), leg["popups"])
        self.assertEqual(leg["details"]["stop"], outcome["current"]["details"]["stop"])
    @lc("LC-A05", "CHAR", note="the basic-braking / initial-brake / release-brake details are the same on both shapes")
    def test_A05_basic_braking_equal(self):
        res = self._both()
        for k in ("base_brake", "init_brake", "rel_brake"):
            self.assertEqual(res["legacy"][1]["details"][k], res["current"][1]["details"][k], k)

    @lc("LC-A06", "CHAR", note="the timing details (running time / departure time) are the same on both shapes")
    def test_A06_timing_equal(self):
        res = self._both()
        self.assertEqual(res["legacy"][1]["details"]["time"], res["current"][1]["details"]["time"])

    @lc("LC-A07", "CHAR", note="one check point per arrival; the doors staying open do not add another; the terminal adds none (INV-SIDX-7)")
    def test_A07_checkpoint_once(self):
        cmd = self.start("legacy")
        t = self.land(cmd, "legacy")
        t = self.leg("legacy", t, 100.0, 1000.0, 1000.0, 1, 1, 1)
        self.assertEqual(len(self.o.save_data), 2)
        self.r.send(F.line("legacy", 1, t + 1000, 0.0, 999.6, jump=1, NEXTLOC=1000.0, DOOR=1, STIDX=self.MR.stidx(self.MR.STALIST, 1, 1, 1)))
        self.r.tick(3, 0.1)
        self.assertEqual(len(self.o.save_data), 2)

    @lc("LC-A08", "CHAR", note="THE EQUIVALENCE: the whole result is the same on the two shapes except the DOORTIME of the check point time (the known difference, exactly the door close time)")
    def test_A08_current_legacy_equivalence(self):
        res = self._both()
        for idx, name in ((0, "after B"), (1, "final")):
            a, b = res["current"][idx], res["legacy"][idx]
            diff = F.differences(a, b)
            self.assertLessEqual(set(diff), {"checkpoint-time"}, "%s: %r" % (name, diff))
        a, b = res["current"][1]["checkpoints"], res["legacy"][1]["checkpoints"]
        self.assertEqual(len(a), len(b))
        for ca, cb in zip(a[1:], b[1:]):
            self.assertEqual(ca[3] - cb[3], F.DOOR_CLOSE_TIME_MS, "the DOORTIME difference is exactly the door close time (%r vs %r)" % (ca, cb))

    @lc("LC-A28", "RED-COND", reason="door-time-unavailable", note="OD-LC-6: the missing DOORTIME of a Legacy delayed arrival is not silent (a fixed word in the log) - or the Legacy sender writes the quantity")
    def test_A28_missing_doortime_is_not_silent(self):
        self.r.close()
        self.r = self.D.D6Rig(self.main)
        self.o = self.r.o
        self.run_trajectory("legacy")
        text = "\n".join(str(x) for x in getattr(self.r.rig, "log", []))
        self.assertIn("door-time-unavailable", text, "no fixed word says that the door close time could not be added")


# ===================================================================================================================================================
# B. Slice A (Jump boundary stop-jerk) and the history (C-LOOP-2)
# ===================================================================================================================================================
class B_SliceA(Base):
    @lc("LC-A09", "RED", reason="false stop-jerk penalty", note="Slice A: an accelerating train, a Jump whose first sample has speed 0.0 and no CALCG (Legacy): no stop-jerk penalty")
    def test_A09_no_false_penalty_on_the_jump_landing(self):
        self.scoring_scene()
        self.accelerate()
        self.assertTrue(self.o.is_stopping_zone)
        self.step(speed=0.0, jump=1, official=True)                       # the Legacy sample: speed 0.0, the CALCG of the moving train is still held
        self.assertEqual(self.jerk_popups(), [], "false stop-jerk penalty: %r" % (self.jerk_popups(),))

    @lc("LC-A09B", "CHAR", note="the same Jump on the Current shape (CALCG:0 on the Jump line) makes no penalty")
    def test_A09B_current_shape_no_penalty(self):
        self.scoring_scene()
        self.accelerate()
        self.step(speed=0.0, calc_g=0.0, jump=1, official=True)
        self.assertEqual(self.jerk_popups(), [])

    @lc("LC-A09C", "RED", reason="stop-jerk state survives the boundary", note="the formal boundary (reset_transient_scoring_state) clears the judged state of the stop-jerk (is_stopping_zone, last_stop_g, stop_notch_state)")
    def test_A09C_boundary_clears_the_stop_jerk_state(self):
        self.scoring_scene()
        o = self.o
        self.accelerate()
        o.last_stop_g = -0.08
        o.stop_notch_state = "EMERGENCY"
        self.S.reset_transient_scoring_state(o)
        self.assertEqual((o.is_stopping_zone, o.last_stop_g, o.stop_notch_state), (False, 0.0, "IDLE"), "stop-jerk state survives the boundary: %r" % ((o.is_stopping_zone, o.last_stop_g, o.stop_notch_state),))

    @lc("LC-A09D", "CHAR", note="a new scenario generation drops the stop-jerk state (F5): it already does today (the Retry / F5 initialisation of the fix must not conflict with it)")
    def test_A09D_generation_clears_the_stop_jerk_state(self):
        import managed_input
        o = self.scoring_scene()
        self.accelerate()
        self.assertTrue(o.is_stopping_zone)
        managed_input.discard_generation_state(o)
        self.assertEqual((o.is_stopping_zone, o.last_stop_g), (False, 0.0), "stop-jerk state survives the generation: %r" % ((o.is_stopping_zone, o.last_stop_g),))

    @lc("LC-A09E", "GUARD", note="a real hard stop still makes the penalty (the fix must not remove the rule): -0.12 G for the last 0.5 s, then 0.0 -> -200")
    def test_A09E_a_real_hard_stop_is_penalised(self):
        self.scoring_scene()
        self.accelerate(5)
        for i in range(8):
            self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.12)
        self.step(speed=0.0, calc_g=-0.12)
        self.assertEqual(self.jerk_popups(), ["停車時衝動 -200"])

    @lc("LC-A09F", "GUARD", note="the same station, a normal stop -> move -> stop: the second stop is judged again (the state is not lost by normal movement)")
    def test_A09F_normal_restop_is_judged_again(self):
        self.scoring_scene()
        for _ in range(2):
            self.accelerate(5)
            for i in range(8):
                self.step(speed=max(2.0 - 0.3 * i, 0.5), calc_g=-0.12)
            self.step(speed=0.0, calc_g=-0.12)
        self.assertEqual(self.jerk_popups(), ["停車時衝動 -200", "停車時衝動 -200"])

    @lc("LC-A10", "RED", reason="evaluated while the jump is pending", note="LJ-PEN-B: the stop-jerk is not evaluated while the official jump is pending (is_official_jumping) with no BVE jump counter movement yet")
    def test_A10_no_evaluation_while_the_jump_is_pending(self):
        self.scoring_scene()
        self.accelerate()
        self.step(speed=0.0, official=True)
        self.assertEqual(self.jerk_popups(), [], "evaluated while the jump is pending: %r" % (self.jerk_popups(),))

    @lc("LC-A11", "RED", reason="history grows while the time is frozen", note="C-LOOP-2: the step does not add to the history when the BVE time did not advance")
    def test_A11_frozen_time_does_not_grow_the_history(self):
        self.scoring_scene()
        self.o.bve_speed = 5.0
        for _ in range(1000):
            self.S.update_physics_and_scoring(self.o, 200.0, 0.0)
        self.assertEqual(len(self.o.g_history), 1, "history grows while the time is frozen: %d" % len(self.o.g_history))

    @lc("LC-A11B", "RED", reason="duplicates dominate the stop value", note="C-LOOP-2: 600 duplicates of a frozen value do not dominate the 0.5 s mean of the stop-jerk")
    def test_A11B_duplicates_do_not_dominate_the_stop_value(self):
        self.scoring_scene()
        self.accelerate(3, g=0.0)
        for i in range(10):
            self.step(dt=0.04, speed=2.0, calc_g=-0.01)
        self.o.bve_speed = 2.0
        self.o.bve_calc_g = -0.20                                          # the value of the frozen menu moment, repeated by the 16 ms step with the BVE time frozen
        for _ in range(600):
            self.S.update_physics_and_scoring(self.o, self.t, 0.0)
        self.step(dt=0.1, speed=0.0, calc_g=-0.01)
        self.assertLess(abs(self.o.last_stop_g), 0.1, "duplicates dominate the stop value: %r" % (self.o.last_stop_g,))

    @lc("LC-A11C", "RED", reason="history keeps", note="C-LOOP-2: with the time frozen the NEWEST value replaces the entry of that time (the older entries are untouched)")
    def test_A11C_frozen_time_replaces_the_newest_entry_only(self):
        self.scoring_scene()
        self.step(dt=0.1, speed=5.0, calc_g=0.01)
        self.step(dt=0.1, speed=5.0, calc_g=0.02)
        for g in (0.03, 0.04):
            self.o.bve_calc_g = g
            self.S.update_physics_and_scoring(self.o, self.t, 0.0)
        values = [round(h[1], 3) for h in self.o.g_history]
        self.assertEqual(values, [-0.01, -0.04], "history keeps %r" % (values,))
    @lc("LC-A12", "GUARD", note="with the time advancing the history keeps one entry per step, inside the 10 s retention")
    def test_A12_advancing_time_keeps_the_window(self):
        self.scoring_scene()
        self.o.bve_speed = 5.0
        for _ in range(150):
            self.step(dt=0.1, speed=5.0, calc_g=0.0)
        n = len(self.o.g_history)
        self.assertTrue(98 <= n <= 101, n)


# ===================================================================================================================================================
# C. Retry / Jump / generation / F5 / Pause
# ===================================================================================================================================================
class C_RetryJump(ManagedBase):
    def at_b(self):
        cmd = self.start("legacy")
        t = self.land(cmd, "legacy")
        t = self.leg("legacy", t, 100.0, 1000.0, 1000.0, 1, 1, 1)
        return t

    @lc("LC-A13", "RED", reason="accepted after the finish", note="C-SIDX-4: after scoring-finish a Retry is refused (scoring-finished)")
    def test_A13_no_retry_after_the_finish(self):
        self.o.setting_end_idx = 2
        mid, final, cmd = self.run_trajectory("legacy")
        self.assertTrue(final["finished"], final)
        res = self.main.execute_retry(self.o, 0, False)
        self.assertFalse(res.accepted, "accepted after the finish: reason=%r" % (res.reason,))
        self.assertEqual(res.reason, "scoring-finished")

    @lc("LC-A14", "RED", reason="a Retry is sent while the jump is unavailable", note="C-LJ-3(i): AVAIL without the jump group (breaker open): the Retry is refused JUMP_UNAVAILABLE and nothing is sent")
    def test_A14_no_retry_while_the_jump_is_unavailable(self):
        t = self.at_b()
        before = len(self.commands())
        no_jump = [a for a in F.LEGACY_AVAIL if a != "jump"]
        self.r.send(self.MR.tele(1, time_ms=t + 1000, speed=0.0, loc=999.6, avail=no_jump, CALCG="0.00000", DOOR=1, STIDX=self.MR.stidx(self.MR.STALIST, 1, 1, 1)).replace(",JUMP:0", ""))
        self.r.tick(2, 0.1)
        res = self.main.execute_retry(self.o, 0, False)
        sent = len(self.commands()) - before
        self.assertEqual(sent, 0, "a Retry is sent while the jump is unavailable (sent=%d, accepted=%r)" % (sent, res.accepted))
        self.assertFalse(res.accepted)
        self.assertEqual(res.reason, "jump-unavailable")

    @lc("LC-A15", "RED", reason="no abort without a datagram", note="C-LJ-3(ii): an outstanding jump with no datagram for 10.5 s is aborted (the poll is not only datagram driven)")
    def test_A15_silent_sender_aborts_after_the_timeout(self):
        self.start("legacy")
        self.assertTrue(self.o.is_official_jumping)
        for _ in range(3):
            self.r.tick(1, 3.5)
        self.assertFalse(self.o.is_official_jumping, "no abort without a datagram (jumping=%r scoring=%r)" % (self.o.is_official_jumping, self.o.is_scoring_mode))

    @lc("LC-A16", "RED", reason="baseline", note="C-LJ-5: a first accepted line WITHOUT the JUMP key, then a line with JUMP:3 - the counter is adopted as the baseline, no jump lock, no abort")
    def test_A16_jump_baseline_is_the_first_line_that_has_the_key(self):
        r, o, MR = self.r, self.o, self.MR
        no_jump = [a for a in F.LEGACY_AVAIL if a != "jump"]
        r.publish(True, True, 1)
        r.tick(2)
        r.send(MR.STALIST, MR.tele(1, time_ms=36000000, avail=no_jump).replace(",JUMP:0", ""))
        r.tick(2)
        r.send(MR.tele(1, time_ms=36001000, avail=F.LEGACY_AVAIL, JUMP=3).replace(",JUMP:0", ""))
        r.tick(2)
        self.assertEqual((o.last_jump_count, o.jump_lock), (3, False), "baseline: last_jump_count=%r jump_lock=%r" % (o.last_jump_count, o.jump_lock))

    @lc("LC-A17", "CHAR", note="C-LOOP-4 is NOT reproduced in the managed flow: the fast-forward state is already cleared when the official jump is settled (OD-LC-9 can stay closed unless a real-machine run shows otherwise)")
    def test_A17_ff_cleared_by_the_settlement(self):
        cmd = self.start("legacy")
        o = self.o
        o.is_fast_forwarding = True
        o.ff_check_real_time = 1.0
        self.land(cmd, "legacy")
        self.assertFalse(o.is_fast_forwarding, "fast-forward survives the jump")

    @lc("LC-A18", "CHAR", note="Retry: a refused request changes nothing and sends nothing; an accepted one sends exactly one request, keeps the history (cut only at the settlement)")
    def test_A18_retry_refusal_and_acceptance(self):
        t = self.at_b()
        o = self.o
        n_cmd, n_hist, score = len(self.commands()), len(o.save_data), o.score
        res = self.main.execute_retry(o, 99, False)
        self.assertFalse(res.accepted)
        self.assertEqual((len(self.commands()), len(o.save_data), o.score, o.is_official_jumping), (n_cmd, n_hist, score, False))
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertEqual(len(o.save_data), n_hist, "the history is not cut by the request")
        self.assertTrue(o.is_official_jumping)

    @lc("LC-A19", "CHAR", note="a new generation discards the scoring session and the outstanding jump (no stale completion can release anything)")
    def test_A19_generation_discards_the_session(self):
        self.start("legacy")
        self.assertTrue(self.o.is_official_jumping)
        self.r.publish(True, True, 2)
        self.r.tick(4)
        self.assertFalse(self.o.is_scoring_mode)
        self.assertFalse(self.o.is_official_jumping)
        self.assertIsNone(self.o.jump_expectation)

    @lc("LC-A20", "CHAR", note="Pause (Driving OFF, Session ON) keeps the scoring and the score; the resume does not score the frozen time")
    def test_A20_pause_keeps_the_session(self):
        t = self.at_b()
        o = self.o
        score, hist = o.score, len(o.save_data)
        self.r.publish(True, False)
        self.r.tick(5, 1.0)
        self.assertTrue(o.is_scoring_mode)
        self.r.publish(True, True)
        self.r.tick(3, 0.1)
        self.assertEqual((o.score, len(o.save_data)), (score, hist))

    @lc("LC-A21", "CHAR", note="F5 (a reload = a new generation): the scoring is off, nothing of the old session is left outstanding")
    def test_A21_f5_resets_the_scoring(self):
        self.at_b()
        self.r.publish(True, True, 2)
        self.r.tick(4)
        o = self.o
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(len(o.save_data), 0)
        self.assertIsNone(o.retry_pending)

    @lc("LC-A22", "CHAR", note="Session OFF (scenario closed / Input Device OFF at the Caller) discards the scoring session")
    def test_A22_session_off_discards(self):
        self.at_b()
        self.r.publish(False, False)
        self.r.tick(4)
        self.assertFalse(self.o.is_scoring_mode)


# ===================================================================================================================================================
# D. GUARDs of the boundaries (static, against the Git blobs of cab7dce)
# ===================================================================================================================================================
X_PATHS = ("station_identity.py", "official_target_contract.py", "hud_target_contract.py", "station_index_contract.py",
           "TsScoringPlugin/Handshake/Shared/ObservationLog.cs", "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs",
           "TsScoringPlugin/Handshake/Bridge/Legacy/src/TsScoringLegacyBridge.cs", "TsScoringPlugin/Handshake/Bridge/src/ScenarioObserver.cs",
           "TsScoringPlugin/Handshake/Bridge/src/ScenarioReadyTracker.cs")
BASE_HEAD = "cab7dce265429ee43775ecbaa4c42f450058a653"


class D_Guards(unittest.TestCase):
    @lc("LC-A25", "GUARD", note="StationIndex non-interference: no distance search in scoring_logic.py; the Season 2 files are byte-identical to the base blobs (BASE=cab7dce, or LC_BASE env after Season 2 push)")
    def test_A25_station_index_untouched(self):
        text = open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8").read()
        import re
        self.assertIsNone(re.search(r"abs\(\s*st\[\"location\"\]\s*-\s*(p_loc|self\.bve_next_loc)\s*\)\s*<\s*1\.0", text), "a distance search is back")
        base = os.environ.get("LC_BASE", BASE_HEAD)
        out = subprocess.run(["git", "diff", "--quiet", base, "--"] + list(X_PATHS), cwd=ROOT).returncode
        self.assertEqual(out, 0, "a Season 2 file differs from %s" % base)


# ===================================================================================================================================================
# runner
# ===================================================================================================================================================
def main(argv):
    expect = "red"
    only = None
    for i, a in enumerate(argv):
        if a == "--expect" and i + 1 < len(argv):
            expect = argv[i + 1]
        if a == "--only" and i + 1 < len(argv):
            only = set(argv[i + 1].split(","))
    if not HAS_QT:
        print("ENV | PyQt6 is not importable: nothing was run")
        return 2
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    for cls in (A_Slice, B_SliceA, C_RetryJump, D_Guards):
        for name in loader.getTestCaseNames(cls):
            fn = getattr(cls, name)
            rid = getattr(fn, "lc", None)
            if rid and (only is None or rid in only):
                suite.addTest(cls(name))
    verdicts = {}
    for case in suite:
        fn = getattr(case, case._testMethodName)
        rid = fn.lc
        res = unittest.TestResult()
        unittest.TestSuite([case]).run(res)               # (a suite, so that setUpClass / tearDownClass run)
        if res.errors:
            verdicts[rid] = ("ERROR", res.errors[0][1].strip().splitlines()[-1][:150])
        elif res.failures:
            verdicts[rid] = ("FAIL", res.failures[0][1].strip().splitlines()[-1][:150])
        elif res.skipped:
            verdicts[rid] = ("SKIP", res.skipped[0][1][:100])
        else:
            verdicts[rid] = ("PASS", "")
    bad = 0
    print("ID | kind | verdict | predicted | detail")
    for rid in sorted(ROWS):
        if rid not in verdicts:
            continue
        row = ROWS[rid]
        v, detail = verdicts[rid]
        kind = row["kind"]
        if expect == "green":
            predicted = "PASS" if kind != "RED-COND" else "(any)"
            ok = (v == "PASS") or kind == "RED-COND"
        elif kind in ("RED", "RED-COND"):
            predicted = "FAIL(%s)" % row["reason"]
            ok = v == "FAIL" and row["reason"].lower() in detail.lower()
        else:
            predicted = "PASS"
            ok = v == "PASS"
        if not ok:
            bad += 1
        print("%s | %s | %s | %s | %s%s" % (rid, kind, v, predicted, "" if ok else "MISMATCH: ", detail))
    print("rows=%d mismatches=%d expect=%s" % (len(verdicts), bad, expect))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
