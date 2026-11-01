"""Stage TB-H Stage 1 (RED), LAYER A of the Retry to the pseudo-turnback B (Owner ruling R5): the STATE TRANSITION of the Retry landing, kept apart from the scoring contract of pair B
(tests/test_pt_tbh_pairb_contract.py). Root cause (baseline 2387d17, trace in the stage report): after the first departure from B jump_lock is False; the Retry's own settlement absorbs the sender's JUMP counter,
so the jump rule never takes the lock again; turnback_landing_step ends the landing watch at once because jump_lock is False, the 'B operating time handled' mark is never set, and the departure scores +300.
These tests must stay GREEN even when pair B is untimed by contract (the contract must not hide a state-transition defect): the layer-A fix is its own commit (Commit 2)."""
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import jump_transaction  # noqa: E402
from test_pt_tbg_landing_order import Base as LandingBase, setUpModule, tearDownModule  # noqa: E402,F401


class A_RetryLandingState(LandingBase):
    def retry_after_departure(self):
        f = self.R.Flow(self, operational=True, order="complete_first").run(10)
        f.depart_b_only("close_then_go")
        f.after(3)
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        f.after(10)
        return f

    def test_RB_1_layer_A_state_the_B_operating_time_stays_handled_after_the_Retry_landing(self):
        f = self.retry_after_departure()
        o = f.o
        self.assertTrue(o.has_scored_time_this_station, "RED on the baseline: the landing watch ended because jump_lock is False (the settlement absorbs the counter), the 'handled' mark was never set")

    def test_RB_2_layer_A_state_the_landing_watch_does_not_depend_on_the_jump_rule_lock(self):
        f = self.R.Flow(self, operational=True, order="complete_first").run(10)
        f.depart_b_only("close_then_go")
        f.after(3)
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        machine = f.scene.machine
        # the Retry Jump has settled: the watch of the landing is armed and is still waiting for the target switch; it is released by the landing step, not dropped by an unrelated lock
        for _ in range(10):
            f.scene.step(1)
        self.assertTrue(f.o.has_scored_time_this_station)
        self.assertIsNone(machine.landing_watch)

    def landing_state(self, order, index, station, depart_first):
        f = self.R.Flow(self, operational=True, order=order).run(10)
        if depart_first:
            f.depart_b_only("close_then_go")
            f.after(3)
        o = f.o
        res = self.main.execute_retry(o, index, False)
        self.assertTrue(res.accepted, res)
        f.telemetry_landing(o.jump_expectation, station)
        f.after(10)
        return (o.score, dict(o.score_details), bool(o.jump_lock), bool(o.has_scored_time_this_station), bool(o.is_official_retry), f.scene.machine.landing_watch is not None)

    def test_RB_8_RED_the_state_after_a_Retry_landing_does_not_depend_on_the_order_the_host_reports_the_Jump(self):
        """The reference order (the jump rule sets jump_lock) and the real order (the settlement absorbs the JUMP counter) must end in the same Retry state: for the turnback B checkpoint and for the start checkpoint, before and after the B departure."""
        for index, station in ((0, 0), (1, 2)):
            for depart_first in (False, True):
                with self.subTest(index=index, depart_first=depart_first):
                    real = self.landing_state("complete_first", index, station, depart_first)
                    reference = self.landing_state("detect_first", index, station, depart_first)
                    self.assertEqual(real, reference, "RED on the baseline when depart_first is True: real %r / reference %r (jump_lock, handled mark)" % (real, reference))


class B_RetryLockOwnership(LandingBase):
    """Owner O-2: who takes jump_lock at a Retry, and who does not. Real C-01 order (operational A, the settlement absorbs the JUMP counter), Retry to the turnback B checkpoint AFTER the B departure (lock released by the rule)."""
    JT = jump_transaction

    def after_departure(self):
        f = self.R.Flow(self, operational=True, order="complete_first").run(10)
        f.depart_b_only("close_then_go")
        f.after(3)
        self.assertFalse(f.o.jump_lock, "the first departure released the chain's lock")
        return f

    def start_retry(self, f, index=1):
        res = self.main.execute_retry(f.o, index, False)
        self.assertTrue(res.accepted, res)
        self.assertFalse(f.o.jump_lock, "execute_retry itself takes no lock (byte-identical entry)")
        return f.o.jump_expectation

    def test_RL_1_a_successful_Retry_takes_the_lock_at_its_settlement_and_the_first_departure_releases_it(self):
        f = self.after_departure()
        exp = self.start_retry(f)
        f.telemetry_landing(exp, 2)
        f.after(10)
        o = f.o
        self.assertTrue(o.jump_lock, "RED on the baseline: the landing of the Retry is not protected")
        self.assertTrue(o.has_scored_time_this_station)
        before = o.score
        f.depart_b_only("close_then_go")
        f.after(10)
        self.assertFalse(o.jump_lock, "released by the first departure (existing rule)")
        self.assertEqual(o.score, before, "B: no operating time (handled mark AND the pair B contract)")

    def test_RL_2_a_Retry_that_ends_in_another_word_than_ok_never_takes_the_lock(self):
        words = [self.JT.SETTLE_TIMEOUT, self.JT.SETTLE_SCOPE, self.JT.SETTLE_KIND, self.JT.SETTLE_SELECTED, self.JT.SETTLE_ACTUAL_LOCATION, self.JT.SETTLE_REQUESTED_LOCATION,
                 self.JT.SETTLE_MALFORMED, self.JT.SETTLE_REQUEST_ID, self.JT.SETTLE_SEND_REFUSED, self.JT.SETTLE_ENDPOINT, self.JT.SETTLE_UNSOLICITED]
        for word in words:
            with self.subTest(end=word):
                f = self.after_departure()
                self.start_retry(f)
                self.assertTrue(f.o._finish_jump_transaction(word))
                self.assertFalse(f.o.jump_lock, "failed / timed-out Retry: no lock (GUARD: also true on the baseline; it guards the new line against a lock taken too early)")
                self.assertIsNone(f.scene.machine.landing_watch)

    def test_RL_3_a_discarded_Retry_never_takes_the_lock(self):
        for word in (self.JT.SETTLE_CLEANUP, self.JT.SETTLE_SHUTDOWN, self.JT.SETTLE_SCENARIO, self.JT.SETTLE_HISTORY):
            with self.subTest(end=word):
                f = self.after_departure()
                self.start_retry(f)
                self.assertTrue(f.o._finish_jump_transaction(word))
                self.assertFalse(f.o.jump_lock)

    def test_RL_4_a_stale_generation_never_takes_the_lock(self):
        f = self.after_departure()
        exp = self.start_retry(f)
        o = f.o
        o.current_scenario_id += 1                                       # F5 / a new world while the Retry was in flight
        self.S.note_jump_settlement(o, exp, self.JT.SETTLE_OK, 2, 1500.0, None)
        self.assertFalse(o.jump_lock, "the Retry belongs to the old generation (the success word alone is not enough)")
        f2 = self.after_departure()
        exp2 = self.start_retry(f2)
        f2.o.current_scenario_id += 1
        f2.telemetry_landing(exp2, 2)                                    # the real completion of an old-generation request: the judge says scenario-changed
        record = f2.scene.machine.settlement
        self.assertEqual(record.end, self.JT.SETTLE_SCENARIO)
        self.assertIsNone(f2.scene.machine.landing_watch, "no landing watch and no Retry lock branch for a stale generation (a lock that appears here is the EXISTING abort path of a refused completion, main.py, which also ends the scoring; it is not the Retry lock)")

    def test_RL_5_the_settlements_of_START_and_of_the_pseudo_turnback_Jump_are_not_touched(self):
        f = self.after_departure()
        exp = self.start_retry(f)
        o = f.o
        for purpose in (self.JT.JUMP_START, self.JT.JUMP_TURNBACK):
            with self.subTest(purpose=purpose):
                o.jump_lock = False
                self.S.note_jump_settlement(o, exp._replace(purpose=purpose), self.JT.SETTLE_OK, 2, 1500.0, None)
                self.assertFalse(o.jump_lock, "only a successful RETRY takes the lock here (the turnback request takes its own, the START has is_first_station)")

    def test_RL_6_an_ordinary_station_Retry_keeps_the_ordinary_operating_time_rule(self):
        """GUARD (R2: the ordinary station contract is unchanged): a Retry to the ordinary checkpoint of C scores the C departure as it always did (+200 here), with or without the lock."""
        f = self.R.Flow(self, operational=False, order="complete_first").run(10)
        f.depart_b_and_arrive_c()
        o = f.o
        index = len(o.save_data) - 1
        self.assertEqual(o.save_data[index]["station_index"], 3)
        res = self.main.execute_retry(o, index, False)
        self.assertTrue(res.accepted, res)
        f.telemetry_landing(o.jump_expectation, 3)
        f.after(10)
        s, c, d = f.scene, f.scene.sl[3], f.scene.sl[4]
        before = o.score
        o.bve_time_ms = c["raw_dep"] - 100
        o.bve_next_time = c["raw_dep"]
        s.step(2, bve_door=0, bve_speed=0.0)
        s.step(1, advance_ms=100, bve_next_loc=d["location"], bve_tgt_idx=4, bve_speed=0.0)
        s.step(3, bve_speed=1.5, bve_location=c["location"] + 3.0, bve_brk_notch=0)
        s.step(10)
        self.assertEqual(o.score - before, 200, "the ordinary rule (is_official_retry) scores the departure of C")
        self.assertFalse(o.jump_lock, "the lock of the Retry is released by the departure")

    def test_RL_7_the_lock_never_replaces_the_pair_B_contract(self):
        f = self.after_departure()
        exp = self.start_retry(f)
        f.telemetry_landing(exp, 2)
        f.after(10)
        o = f.o
        o.jump_lock = False                                             # the lock lost / released early
        o.has_scored_time_this_station = False                          # and the handled mark lost
        before = o.score
        f.depart_b_only("close_then_go")
        f.after(10)
        self.assertEqual(o.score, before, "pair B untimed by contract even without lock and mark")

    def test_RL_8_static_execute_retry_takes_no_lock_and_the_lock_line_is_in_note_jump_settlement(self):
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

        def sets_lock(fn):
            return any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "jump_lock" for t in n.targets) for n in ast.walk(fn))
        self.assertTrue(sets_lock(fns["note_jump_settlement"]), "RED on the baseline")
        self.assertFalse(sets_lock(fns["execute_retry"]), "execute_retry stays byte-identical: it takes no lock")


if __name__ == "__main__":
    unittest.main()
