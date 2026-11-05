"""Stage P1 (replaces the Stage TB-K latch contract): the remaining-time field in FREE DRIVING follows the host's OFFICIAL target and the EFFECTIVE TIMETABLE decides what is shown. The REAL Overlay / draw_hud is driven by
WIRE-FAITHFUL fixtures (tests/ts_eff_fixtures.py: the real TB-G route, the REAL ticks of the live S-02 stop, the sender's COMPLETED A departure / B arrival) and by the original values.

What moved here from TB-K (the meaning of FD_01..FD_33): before the stop the ordinary display; pair A departure and pair B arrival never shown (dashes); the ordinary stations and the terminal unchanged; score / history /
checkpoint / Jump untouched; a new scenario / generation / PairSet leaves nothing behind; a scoring start owns the field. What is GONE: the latch (the old display stayed on '--:--' after an arrival that the application had
to re-judge from the speed and the range): nothing of that exists any more - no arrival judgement, no range memo, no previous-target snapshot, no wait of a tick.
Live evidence behind it (S-02, 2026-11-05): with the official target already B in the stop tick the old display showed 02:37 = B's COMPLETED arrival."""
import ast
import dataclasses
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ts_eff_fixtures as F  # noqa: E402
import effective_station_state as ess  # noqa: E402
from test_pt_tbj_remaining_time import RtBase, setUpModule, tearDownModule, source  # noqa: E402,F401

DASH = "--:--"
Z = F.real_profile()[1]
NORMAL, HIDDEN = ess.RemainingMode.NORMAL_TIMETABLE, ess.RemainingMode.FREE_TURNBACK_HIDDEN


class FdBase(RtBase):
    def free_scene(self, values, pairset=True):
        import pseudo_turnback_contract
        s = self.P.Scene(self, with_pairs=False)
        o = s.o
        sl = []
        for st in F.stations(values):
            e = self.P.station(st["name"], st["location"], timing=st["is_timing"], terminal=st["is_terminal"])
            e.update(raw_arr=st["raw_arr"], raw_dep=st["raw_dep"], def_time=st["def_time"], stop_time=st["stop_time"], is_pass=st["is_pass"])
            sl.append(e)
        o.station_list = s.sl = sl
        if pairset:
            ps, why = pseudo_turnback_contract.decode_ptpair("PTPAIR:1:%s:12:4:2-3-0;4-5-0;6-7-0;8-9-0" % self.P.R.SCOPE_LIST_ID, 12)
            self.assertIsNone(why, why)
            s.machine.set_pairset(ps)
        s.machine.discard_all()
        o.is_scoring_mode, o.is_scoring_finished = False, False
        o.bve_arr_idx, o.bve_arr_seq = -1, -1
        return s

    def show(self, s, tick):
        from official_target_contract import KNOWN
        o = s.o
        o.official_state, o.official_index = KNOWN, tick.cursor
        o.official_location = F.host_stations()[tick.cursor]["location"]
        o.official_margin_b = o.official_margin_f = F.MARGIN_M
        o.official_reason = ""
        o.bve_door, o.bve_speed, o.bve_location, o.bve_time_ms = tick.door, tick.speed, tick.location, tick.bve_ms
        return self.left(s)

    @staticmethod
    def thin(ticks):
        """Every 10th tick, the last one and EVERY tick within 3 ticks of a change of the official target or of the speed being exactly 0.0 (the interesting ticks are never skipped; drawing every tick of a long drive is slow)."""
        keep = set()
        n = len(ticks)
        for i, tk in enumerate(ticks):
            if i % 10 == 0 or i == n - 1:
                keep.add(i)
            for j in range(max(0, i - 3), min(n, i + 4)):
                if ticks[j].cursor != tk.cursor or (ticks[j].speed == 0.0) != (tk.speed == 0.0):
                    keep.add(i)
        return [ticks[i] for i in sorted(keep)]

    def drive_texts(self, ticks, values):
        """[(tick, the text of the remaining-time field)] for the thinned ticks, on ONE scene (the order of the ticks is kept)."""
        s = self.free_scene(values)
        return [(tk, self.show(s, tk)) for tk in self.thin(ticks)]


class A_FollowTheOfficialTarget(FdBase):
    def test_FD_01_the_field_follows_the_official_target_of_every_tick_in_every_cursor_order(self):
        for v in F.VALUES:
            for order in F.ORDERS:
                res = self.drive_texts(F.approach_and_stop(order), v)
                for tick, text in res:
                    self.assertEqual(text == DASH, tick.cursor == F.B, "%s/%s ms %d cursor %d: %r" % (v, order, tick.bve_ms, tick.cursor, text))
                self.assertTrue(all(x not in (None, "02:37") for _, x in res), "%s/%s: B's completed arrival is never shown" % (v, order))

    def test_FD_02_the_live_S02_case_O1_and_O2_with_the_completed_values_are_dashes_not_02_37(self):
        stop_ms = F.real_profile()[0][Z][0]
        for order in ("same", "lead1"):
            res = self.drive_texts(F.approach_and_stop(order), "cmpl")
            self.assertEqual({x for tk, x in res if tk.bve_ms >= stop_ms}, {DASH}, order)

    def test_FD_03_passing_A_without_a_stop_shows_dashes_once_the_target_is_the_arrival_of_B(self):
        for v in F.VALUES:
            for adv in F.PASS_ADVANCE:
                res = self.drive_texts(F.pass_a_no_stop(adv), v)
                self.assertEqual({x for tk, x in res if tk.cursor == F.B}, {DASH}, "%s/%s" % (v, adv))
                self.assertTrue(all(x != DASH for tk, x in res if tk.cursor == F.A), "%s/%s: before: the arrival of A" % (v, adv))

    def test_FD_04_the_stop_and_the_pass_show_the_same_dashes(self):
        for v in F.VALUES:
            stopped = {x for tk, x in self.drive_texts(F.approach_and_stop("same"), v) if tk.cursor == F.B}
            passed = {x for tk, x in self.drive_texts(F.pass_a_no_stop("marker"), v) if tk.cursor == F.B}
            self.assertEqual((stopped, passed), ({DASH}, {DASH}))

    def test_FD_05_the_train_moves_off_after_the_arrival_and_the_field_stays_dashes_while_the_target_is_B(self):
        for v in F.VALUES:
            moving = [x for tk, x in self.drive_texts(F.restart_after_arrival(), v) if tk.speed > 0.0 and tk.cursor == F.B]
            self.assertTrue(moving)
            self.assertEqual(set(moving), {DASH}, v)

    def test_FD_06_pair_A_departure_is_dashes_A_open_or_closed(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.assertEqual(self.show(s, F.Tick(28920000, 210.0, 3.0, F.A, door=1)), DASH, "A open, doors open near A: the departure of A is undefined (the completed 28940000 -> 00:20 is never shown)")
            self.assertEqual(self.show(s, F.Tick(28920000, 219.0, 0.0, F.A, door=1)), DASH)
            self.assertNotEqual(self.show(s, F.Tick(28920000, 218.0, 0.0, F.A, door=0)), DASH, "the official target is still A in this tick, the doors are closed: the arrival of A - followed, not compensated")
            self.assertNotEqual(self.show(s, F.Tick(28900000, 200.0, 5.0, F.A, door=0)), DASH, "A closed before the cursor moves: the arrival of A")

    def test_FD_07_pair_B_departure_shows_the_departure_of_B_when_SI_R23_selects_it(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.assertEqual(self.show(s, F.Tick(29080000, 268.0, 0.0, F.B, door=1)), "00:10", "B open: doors open near B select the departure: 29090000 - 29080000")
            self.assertEqual(self.show(s, F.Tick(29080000, 268.0, 0.0, F.B, door=0)), DASH, "B closed: the arrival of B is undefined")

    def test_FD_08_after_B_the_next_ordinary_station_returns_to_the_normal_display(self):
        for v in F.VALUES:
            tail = [x for tk, x in self.drive_texts(F.pass_b_to_normal(), v) if tk.cursor == F.A2]
            self.assertTrue(tail)
            self.assertTrue(all(x not in (None, DASH) for x in tail), v)

    def test_FD_09_no_jump_countdown_and_no_hold_of_A_in_free_driving(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            for tick in self.thin(F.approach_and_stop("same")) + self.thin(F.pass_a_no_stop("marker")):
                self.show(s, tick)
                st = s.o.effective_station_state
                self.assertEqual((st.countdown_ms, st.jump_deadline, st.turnback_state, st.effective_target_index), (None, None, ess.TurnbackState.NONE, st.raw_target_index))
            self.assertIsNone(s.o.turnback_remaining_view(), "the TB-J accessor is scoring only")


class B_Untouched(FdBase):
    def test_FD_10_an_ordinary_stop_station_keeps_its_remaining_time(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.assertEqual(self.show(s, F.Tick(28847000, 119.0, 0.0, F.X, door=0)), "00:03")
            self.assertEqual(self.show(s, F.Tick(28855000, 119.0, 0.0, F.X, door=0)), "-00:05")
            self.assertEqual(self.show(s, F.Tick(28850000, 119.0, 0.0, F.X, door=1)), "00:20", "doors open near X: the departure 28870000")

    def test_FD_11_the_terminal_keeps_its_arrival_and_the_freeze(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.assertEqual(self.show(s, F.Tick(30030000, 1400.0, 5.0, F.Z, door=0)), "00:10")
            first = self.show(s, F.Tick(30030000, 1415.0, 0.0, F.Z, door=1))
            later = self.show(s, F.Tick(30035000, 1415.0, 0.0, F.Z, door=1))
            self.assertEqual((first, later), ("00:10", "00:10"), "the terminal freeze: the remaining time stays as it was when the doors first opened")

    def test_FD_12_the_Jump_time_plan_is_the_same_for_original_and_completed_values(self):
        got = {}
        for v in F.VALUES:
            s = self.free_scene(v)
            snap = types.SimpleNamespace(scope=(self.P.R.SCOPE_SID, self.P.R.SCOPE_LIST_ID, 12))
            got[v] = {idx: s.o._scoring_start_plan(snap, idx)[2] for idx in (F.X, F.B)}
        self.assertEqual(got["orig"], got["cmpl"])
        self.assertEqual(got["cmpl"], {F.X: 28840000, F.B: 29060000})

    def test_FD_13_the_theoretical_score_is_9100_on_the_wire_faithful_route(self):
        for v in F.VALUES:
            o = self.free_scene(v).o
            o.setting_start_idx, o.setting_end_idx = 0, 11
            o.menu_state, o.menu_cursor, o.menu_cursor_x = 6, 6, 0
            o.handle_menu_enter(False)
            self.assertEqual(o.theoretical_score, 9100, v)

    def test_FD_14_score_history_checkpoint_and_the_machine_are_untouched_by_reading_the_state(self):
        results = []
        for reads in (0, 25):
            s = self.free_scene("cmpl")
            o = s.o
            for tick in self.thin(F.approach_and_stop("same")):
                self.show(s, tick)
                for _ in range(reads):
                    _ = o.effective_station_state
                    _ = o.turnback_remaining_view()
            results.append((o.score, len(o.save_data), dict(o.score_details), s.machine.state, s.machine.jump_earliest_ms, o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq, list(o.brake_rules),
                            sorted(k for k in o.__dict__ if any(w in k for w in ("free_turnback", "range_memo", "effective_state", "stop_observed", "arrival_observed", "prev_target")))))
        self.assertEqual(results[0], results[1], "reading the state writes nothing; and the Overlay holds no latch / memo / snapshot")
        self.assertEqual(results[0][-1], [])


class C_ScopeAndOwnership(FdBase):
    def test_FD_15_a_new_scenario_instance_leaves_no_effective_target(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.show(s, F.Tick(28903264, 219.5764, 0.0, F.B))
            self.assertEqual(s.o.effective_station_state.effective_target_index, F.B)
            s.o.reset_telemetry_state()
            st = s.o.effective_station_state
            self.assertEqual((st.raw_target_index, st.effective_target_index, st.station_role, st.remaining_time_mode, st.selected_time_ms), (None, None, None, NORMAL, None))

    def test_FD_16_a_scenario_or_generation_change_leaves_nothing(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.show(s, F.Tick(28903264, 219.5764, 0.0, F.B))
            s.o.current_scenario_id = getattr(s.o, "current_scenario_id", 0) + 1
            st = s.o.effective_station_state
            self.assertEqual(st, s.o.effective_station_state, "derived from the current values only")
            s.o.apply_telemetry_text("SCENARIO_ID:%d" % (s.o.current_scenario_id + 7))
            self.assertIsNone(s.o.effective_station_state.effective_target_index)

    def test_FD_17_the_PairSet_decides_the_role_and_a_missing_set_means_no_pair_knowledge(self):
        s = self.free_scene("cmpl")
        self.show(s, F.Tick(28903264, 219.5764, 0.0, F.B))
        self.assertEqual(s.o.effective_station_state.station_role, ess.Role.PAIR_B)
        s.machine.pairset = None
        self.assertEqual(s.o.effective_station_state.station_role, ess.Role.NORMAL)
        import pseudo_turnback_contract
        ps, why = pseudo_turnback_contract.decode_ptpair("PTPAIR:1:%s:12:1:4-5-0" % self.P.R.SCOPE_LIST_ID, 12)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        self.assertEqual(s.o.effective_station_state.station_role, ess.Role.NORMAL, "B (3) is no pair B of the new set")

    def test_FD_18_a_scoring_start_gives_the_field_to_the_scoring_target_contract(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            self.show(s, F.Tick(28903264, 219.5764, 0.0, F.B))
            self.assertEqual(s.o.effective_station_state.remaining_time_mode, HIDDEN)
            o = s.o
            o.is_scoring_mode, o.is_scoring_finished, o.bve_tgt_idx = True, False, F.X
            o._hud_target_sync()
            st = o.effective_station_state
            self.assertEqual((st.scoring_target_index, st.remaining_time_mode, st.selected_time_kind, st.effective_target_index), (F.X, NORMAL, ess.TimeKind.SCORING_NEXTTIME, F.X), "the scoring contract, whatever the official target says")
            self.assertIsNone(o.turnback_remaining_view(), "no chain, the Run does not cross: the ordinary scoring display")

    def test_FD_19_the_end_of_the_scoring_returns_the_field_to_the_official_target(self):
        s = self.free_scene("cmpl")
        o = s.o
        self.show(s, F.Tick(28903264, 219.5764, 0.0, F.B))
        o.is_scoring_mode, o.is_scoring_finished, o.bve_tgt_idx = True, False, F.X
        o._hud_target_sync()
        o.is_scoring_mode, o.is_scoring_finished = False, True
        o._hud_target_sync()
        st = o.effective_station_state
        self.assertEqual((st.scoring_target_index, st.remaining_time_mode, st.effective_target_index), (None, HIDDEN, F.B))


class D_WireAndReadyContract(unittest.TestCase):
    """The wire text goes through the REAL Overlay.read_udp_data (Current and Legacy framing); the PairSet READY check refuses a pair whose required time is missing."""
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls._tmp = tempfile.TemporaryDirectory(prefix="ts-p1-")
        cls._saved = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
        os.environ["USERPROFILE"] = os.environ["HOME"] = cls._tmp.name
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["p1-wire"])
        import main
        import sia_rig as R
        cls.main, cls.R = main, R

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls._tmp.cleanup()

    def feed(self, framing, values, tick, payload=None, pairs=F.PAIR_MODES):
        rig = self.R.Rig(self.main)
        try:
            o = rig.o
            payload = payload if payload is not None else F.stalist_payload(values)
            o.udp_socket.incoming.append(("STALIST:" + payload).encode("utf-8"))
            o.read_udp_data()
            o.udp_socket.incoming.append(F.telemetry_line(framing, values, tick, pairs=pairs, payload=payload).encode("utf-8"))
            o.read_udp_data()
            o._hud_target_sync()
            holder = o.__dict__.get("route_pairset")
            return {"state": o.effective_station_state, "stations": [(s["name"], s["raw_arr"], s["raw_dep"]) for s in o.station_list],
                    "pairset": holder.state if holder is not None else None, "why": holder.last_reason if holder is not None else None,
                    "machine_pairs": None if o.__dict__.get("turnback_machine") is None or o.turnback_machine.pairset is None else len(o.turnback_machine.pairset.pairs)}
        finally:
            rig.close()

    def test_WR_01_current_and_legacy_wire_give_the_same_effective_state(self):
        for v in F.VALUES:
            for order in F.ORDERS:
                for idx in (0, Z, Z + 20):
                    tick = F.approach_and_stop(order)[idx]
                    a, b = self.feed("cur", v, tick), self.feed("leg", v, tick)
                    self.assertEqual(a, b, "%s/%s tick %d" % (v, order, idx))

    def test_WR_02_the_wire_reaches_the_state_as_the_completed_values_and_the_state_ignores_them(self):
        tick = F.approach_and_stop("same")[Z + 3]
        for framing in ("cur", "leg"):
            got = self.feed(framing, "cmpl", tick)
            st = {n: (a, d) for n, a, d in got["stations"]}
            self.assertEqual((st["閉閉-A"], st["閉閉-B"]), ((28910000, 28940000), (29060000, 29090000)), "the sender's completed times arrive")
            self.assertEqual((got["pairset"], got["machine_pairs"]), ("READY_NONEMPTY", 4), got)
            s = got["state"]
            self.assertEqual((s.raw_target_index, s.effective_target_index, s.station_role, s.remaining_time_mode, s.selected_time_ms), (F.B, F.B, ess.Role.PAIR_B, HIDDEN, None))
            self.assertEqual((s.raw_arrival_time, s.effective_arrival_time, s.arrival_time_source), (29060000, None, ess.TimeSource.SUPPRESSED_FOR_TURNBACK), "the completed arrival is only RAW")
        for framing in ("cur", "leg"):
            orig_state, cmpl_state = self.feed(framing, "orig", tick)["state"], self.feed(framing, "cmpl", tick)["state"]
            self.assertEqual(orig_state, dataclasses.replace(cmpl_state, raw_arrival_time=None), "the original values give the same state except the raw value")

    def test_WR_03_READY_refuses_a_pair_whose_B_has_no_departure_time(self):
        host = F.complete_like_sender(F.host_stations())
        host[F.B]["dep"] = -1
        payload = ",".join("=".join([h["name"], "1", F.fmt_num(h["location"]), str(h["arr"]), str(h["dep"]), str(h["default"]), str(h["stop"]), "0", "1" if h["terminal"] else "0"]) for h in host)
        tick = F.approach_and_stop("same")[Z + 3]
        got = self.feed("cur", "cmpl", tick, payload=payload)
        self.assertEqual((got["pairset"], got["why"], got["machine_pairs"]), ("UNAVAILABLE", ess.CONTRACT_PAIR_B_DEPARTURE, None), "fail closed: the set is not adopted, so no managed scoring start can use it")
        self.assertEqual(got["state"].station_role, ess.Role.NORMAL, "no pair knowledge (the route data violate the contract): never a silent pair B")

    def test_WR_04_READY_refuses_a_pair_whose_A_has_no_arrival_time(self):
        host = F.complete_like_sender(F.host_stations())
        host[F.A]["arr"] = -1
        payload = ",".join("=".join([h["name"], "1", F.fmt_num(h["location"]), str(h["arr"]), str(h["dep"]), str(h["default"]), str(h["stop"]), "0", "1" if h["terminal"] else "0"]) for h in host)
        got = self.feed("cur", "cmpl", F.approach_and_stop("same")[Z + 3], payload=payload)
        self.assertEqual((got["pairset"], got["why"]), ("UNAVAILABLE", ess.CONTRACT_PAIR_A_ARRIVAL))

    def test_WR_05_the_certified_route_has_the_required_times_on_every_pair(self):
        for v in F.VALUES:
            self.assertIsNone(ess.pair_time_violation(F.PAIRS, F.rows(v)), v)
        host = F.host_stations()
        for a, b in F.PAIRS:
            self.assertTrue(host[a]["arr"] > 0 and host[a]["dep"] <= 0, "A: arrival only (the Qualifier's rule)")
            self.assertTrue(host[b]["dep"] > 0 and host[b]["arr"] <= 0, "B: departure only (the Qualifier's rule)")

    def test_WR_06_the_PairSet_intake_still_reads_no_station(self):
        text = source("route_pairset.py")
        self.assertNotIn("raw_arr", text)
        self.assertNotIn("raw_dep", text)
        tree = ast.parse(text)
        names = {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
        self.assertNotIn("stations", names)


class E_TheHudAndTheTimeReadTheSameState(FdBase):
    """Stage P1: the ordinary HUD (the distance row, the label) and the remaining-time row are two readings of the SAME moment: the effective target of the state names the station of the HUD target in free driving and
    in a live pseudo-turnback chain (the Stage 6 hold of A) and after the landing (B)."""

    def hud_station(self, o):
        loc = o.hud_target_next_loc
        names = [i for i, st in enumerate(o.station_list) if abs(st["location"] - loc) < 0.01]
        return names[0] if names else None

    def test_FD_20_free_driving_the_HUD_target_is_the_effective_target(self):
        for v in F.VALUES:
            s = self.free_scene(v)
            for tick in self.thin(F.approach_and_stop("same")) + self.thin(F.pass_a_no_stop("zone_exit")):
                self.show(s, tick)
                st = s.o.effective_station_state
                self.assertEqual((st.effective_target_index, self.hud_station(s.o)), (tick.cursor, tick.cursor), (v, tick.bve_ms))

    def test_FD_21_a_live_chain_keeps_A_for_the_HUD_and_for_the_state_even_when_the_raw_target_is_B(self):
        s, t, f = self.scene()
        o = s.o
        o._hud_target_sync()
        self.assertEqual((o.effective_station_state.effective_target_index, self.hud_station(o)), (1, 1))
        self.move(s, t + 2000)
        self.b_target(s, t + 2100, bve_speed=2.0, bve_location=self.P.A_MARK + 9.7, bve_brk_notch=0)
        o._hud_target_sync()
        st = o.effective_station_state
        self.assertEqual((o.bve_tgt_idx, st.scoring_target_index, st.effective_target_index, self.hud_station(o)), (2, 2, 1, 1), "raw / scoring target B, the effective target and the HUD: A")
        self.assertEqual(st.remaining_time_mode, ess.RemainingMode.TURNBACK_CANCELLED)

    def test_FD_22_after_the_landing_the_state_and_the_HUD_move_to_B(self):
        flow = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        flow.to_arrival_at_a()
        flow.to_request()
        flow.land()
        flow.after(3)
        o = flow.scene.o
        o._hud_target_sync()
        st = o.effective_station_state
        self.assertEqual((st.effective_target_index, self.hud_station(o), st.turnback_state, st.selected_time_kind), (2, 2, ess.TurnbackState.NONE, ess.TimeKind.DEPARTURE))
        self.assertEqual(st.selected_time_ms, flow.scene.sl[2]["raw_dep"])


if __name__ == "__main__":
    unittest.main()
