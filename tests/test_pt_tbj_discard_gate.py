"""Stage TB-J final gate (tests only): (2) the countdown of turnback_remaining_view is dropped by the EXISTING product entries (not by calling the machine alone), (3) after the landing the B is chosen from the Run's fixed
A -> B pair (never by a name or by the value the machine target happens to hold).

The entries that are driven (nothing is replaced):
  * F5 / scenario reset  : Overlay.apply_telemetry_text with a new SCENARIO_ID (is_scoring_mode off, route_pairset.clear), then the next scoring tick
  * ScenarioGeneration   : a changed current_scenario_id, then the next scoring tick (scoring_logic.turnback_lifecycle_guard: generation != the chain's)
  * Retry start          : scoring_logic.begin_official_jump (the call that execute_retry makes for the Retry Jump) with the Jump in flight, then the next tick (turnback_lifecycle_guard)
  * RunPairSet change    : the PairSet published to the machine replaced by another one (TurnbackMachine.set_pairset, what route_pairset.sync calls), then the next tick (drop_if_pair_not_in_run)
The pre-states are the four the display can be in: 00:10 (first window), 00:05 (after a re-stop), --:-- (cancelled), 00:00 (the request was made, B not established).
Disclosed boundary (existing machine contract, characterised below): once the Jump is REQUESTED the chain is not a waiting chain any more: a Retry cannot start (the F1 hold), and a replaced PairSet does not drop it
(only a waiting chain is dropped by drop_if_pair_not_in_run); F5 and a generation change drop it in every state."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbj_remaining_time import RtBase, setUpModule, tearDownModule  # noqa: E402,F401


class DiscardBase(RtBase):
    PRE = ("count10", "dashes", "count5", "zero")

    def pre(self, kind):
        s, t, f = self.scene()
        if kind == "count10":
            self.at(s, t + 1000)
        elif kind == "dashes":
            self.move(s, t + 2000)
        elif kind == "count5":
            self.move(s, t + 2000)
            self.restop(s, t + 3000)
        elif kind == "zero":
            self.at(s, t + 10000)
        return s, t, f

    def expect_before(self, s, kind):
        view = s.o.turnback_remaining_view()
        want = {"count10": ("count", 9000), "dashes": ("dashes", None), "count5": ("count", 5000), "zero": ("count", 0)}[kind]
        self.assertEqual(view, want, kind)
        self.assertEqual(self.left(s), {"count10": "00:09", "dashes": "--:--", "count5": "00:05", "zero": "00:00"}[kind])

    def trigger(self, s, how):
        import pseudo_turnback_contract
        o = s.o
        if how == "f5":
            o.apply_telemetry_text("SCENARIO_ID:%d" % (getattr(o, "current_scenario_id", 0) + 7))
        elif how == "retry":
            self.S.begin_official_jump(o, 100.0, o.bve_time_ms)
            o.is_official_jumping = True
        elif how == "generation":
            o.current_scenario_id = getattr(o, "current_scenario_id", 0) + 1
        elif how == "pairset":
            ps, why = pseudo_turnback_contract.decode_ptpair("PTPAIR:1:%s:5:1:3-4-0" % self.P.R.SCOPE_LIST_ID, 5)
            self.assertIsNone(why, why)
            s.machine.set_pairset(ps)
        s.step(1)                                                       # the next scoring tick: the product's own lifecycle guard runs

    def assert_dropped(self, s, kind, how):
        o = s.o
        self.assertIsNone(o.turnback_remaining_view(), "%s after %s: the old countdown state is gone" % (kind, how))
        self.assertIsNone(s.machine.jump_earliest_ms)
        for _ in range(3):                                              # and it does not come back
            s.step(1)
            self.assertIsNone(o.turnback_remaining_view())


class K_CountdownIsDroppedByTheProductEntries(DiscardBase):
    def test_RT_22_F5_scenario_reset_drops_every_pre_state(self):
        for kind in self.PRE:
            s, t, f = self.pre(kind)
            self.expect_before(s, kind)
            self.trigger(s, "f5")
            self.assertFalse(s.o.is_scoring_mode, "the new scenario instance ends the scoring")
            self.assert_dropped(s, kind, "f5")

    def test_RT_24_ScenarioGeneration_change_drops_every_pre_state(self):
        for kind in self.PRE:
            s, t, f = self.pre(kind)
            self.expect_before(s, kind)
            self.trigger(s, "generation")
            self.assert_dropped(s, kind, "generation")

    def test_RT_23_Retry_start_drops_the_waiting_pre_states(self):
        for kind in ("count10", "dashes", "count5"):
            s, t, f = self.pre(kind)
            self.expect_before(s, kind)
            self.trigger(s, "retry")
            self.assert_dropped(s, kind, "retry")

    def test_RT_25_RunPairSet_change_drops_the_waiting_pre_states(self):
        for kind in ("count10", "dashes", "count5"):
            s, t, f = self.pre(kind)
            self.expect_before(s, kind)
            self.trigger(s, "pairset")
            self.assert_dropped(s, kind, "pairset")

    def test_RT_23_25_boundary_after_the_request_a_retry_cannot_start_and_the_chain_is_not_a_waiting_chain(self):
        s, t, f = self.pre("zero")
        self.assertEqual(s.machine.state, self.M.REQUESTED)
        self.assertTrue(self.S.official_jump_f1_hold(s.o), "F1 (the Retry menu) is held while the chain's own Jump is in flight")
        self.trigger(s, "pairset")
        self.assertEqual((s.o.turnback_remaining_view(), s.machine.state), (("count", 0), self.M.REQUESTED), "characterisation of the existing contract: drop_if_pair_not_in_run only drops a WAITING chain")

    def test_RT_the_dropped_countdown_never_reaches_the_next_Run(self):
        s, t, f = self.pre("count10")
        self.trigger(s, "f5")
        self.assert_dropped(s, "count10", "f5")
        s.o.is_scoring_mode, s.o.is_scoring_finished = True, False          # a new Run owns the HUD again
        self.assertIsNone(s.o.turnback_remaining_view())
        self.assertIsNone(s.machine.fixed, "nothing of the old Run's fixed pairs either")


class L_AfterTheLanding(RtBase):
    def flow(self):
        flow = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first")
        flow.to_arrival_at_a()
        flow.to_request()
        return flow

    def test_RT_gate3_not_established_00_00_then_B_raw_dep_then_ordinary(self):
        flow = self.flow()
        s, o = flow.scene, flow.o
        self.assertEqual(s.machine.state, self.M.REQUESTED)
        self.assertEqual((o.turnback_remaining_view(), self.left(s)), (("count", 0), "00:00"), "requested, B not established")
        s.machine.on_jump_complete(True, 2, s.machine.generation)          # the host's settlement judged the Jump: the machine waits for B to be established (awaiting_b)
        self.assertTrue(s.machine.awaiting_b)
        self.assertEqual((o.turnback_remaining_view(), self.left(s)), (("count", 0), "00:00"), "completed but B not established: still 00:00")
        flow2 = self.flow()                                                # the whole product path (land, settle, B established) on a fresh scene
        s, o = flow2.scene, flow2.o
        flow2.land()
        flow2.after(3)
        self.assertEqual(s.machine.state, self.M.IDLE, "B established")
        dep = s.sl[2]["raw_dep"]
        self.assertEqual(o.turnback_remaining_view(), ("time", dep))
        diff = dep // 1000 - o.bve_time_ms // 1000
        self.assertEqual(self.left(s), "%02d:%02d" % (diff // 60, diff % 60) if diff >= 0 else "-%02d:%02d" % (-diff // 60, -diff % 60))

    def test_RT_gate3_B_without_raw_dep_shows_dashes(self):
        flow = self.flow()
        s, o = flow.scene, flow.o
        flow.land()
        flow.after(3)
        s.sl[2]["raw_dep"] = -1
        self.assertEqual((o.turnback_remaining_view(), self.left(s)), (("dashes", None), "--:--"))

    def test_RT_gate3_the_B_is_the_fixed_pair_B_not_a_name_and_not_the_machine_target_value(self):
        flow = self.flow()
        s, o = flow.scene, flow.o
        flow.land()
        flow.after(3)
        for st in s.sl:
            st["name"] = "same"                                           # no name can tell the B
        s.sl[4]["raw_dep"] = o.bve_time_ms + 30000                        # another station with a departure time: it is no B of the Run's pair
        fixed_b = {p.departure for p in s.machine.fixed}
        self.assertEqual(fixed_b, {2}, "the Run's fixed A -> B pair of the scene")
        self.assertEqual(self.S.turnback_b_indexes(o), frozenset(fixed_b), "the view's B set is the Run's pairs, nothing else")
        for garbage in (-1, 0, o.bve_time_ms + 7000, o.bve_time_ms - 50000):
            o.bve_next_time = garbage                                     # whatever the C# machine target holds
            self.assertEqual(o.turnback_remaining_view(), ("time", s.sl[2]["raw_dep"]), garbage)
        o.bve_tgt_idx = 4
        self.assertIsNone(o.turnback_remaining_view(), "a station that is no B of the fixed pair is never given the B display")
        o.bve_tgt_idx = 2
        s.machine.fixed = []
        s.machine.fixed_by_a = {}
        o.__dict__.pop("_scoring_section", None)
        o.setting_end_idx = 1                                             # the Run (settings) no longer crosses the pair: the B of the old Run is no B any more
        self.assertIsNone(o.turnback_remaining_view())


if __name__ == "__main__":
    unittest.main()
