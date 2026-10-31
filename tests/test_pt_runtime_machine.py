"""PR-2 (clone): the runtime state machine of the pseudo-turnback chain, driven by a host stub (no main.py, no BVE, no socket). Owner contract: OD-PR-1 beta
(NO A checkpoint, ONE B checkpoint after the Jump completed and B is established), OD-PR-3 (purpose turnback), OD-PR-4 (A operating time once, at the arrival)."""
import inspect
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, 'tests')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pseudo_turnback_contract as C          # RED on cab7dce: the module does not exist
import pseudo_turnback_machine as M           # RED on cab7dce: the module does not exist

LID = "A1B2C3D4"
GEN = 7


def pairset(text=None, count=20):
    ps, why = C.decode_ptpair(text or "PTPAIR:1:%s:%d:1:5-6-0" % (LID, count), count)
    assert why is None, why
    return ps


class Host(object):
    """A tiny host stub: it records every action the machine returns."""

    def __init__(self, text=None, count=20):
        self.m = M.TurnbackMachine()
        self.m.set_pairset(pairset(text, count))
        self.count = count
        self.actions = []

    def run(self, acts):
        self.actions.extend(acts)
        return acts

    def arrive(self, now=100000, a=5, seq=1, gen=GEN, start=0, end=19, explicit_end=-1, active=True, lid=LID, count=None):
        return self.run(self.m.on_arrival(now, a, seq, gen, lid, self.count if count is None else count, start, end, explicit_end, active))

    def scored(self, now=100000, timing=True):
        return self.run(self.m.a_scoring_complete(now, timing))

    def tick(self, now, gen=GEN, active=True, paused=False, menu=False):
        return self.run(self.m.tick(now, gen, active, paused, menu))

    def kinds(self):
        return [a[0] for a in self.actions]

    def requests(self):
        return [a for a in self.actions if a[0] == "request_jump"]


class StartConditions(unittest.TestCase):
    def test_R5_no_request_before_the_arrival(self):
        h = Host()
        self.assertEqual(h.tick(10 ** 7), [])
        self.assertEqual(h.m.state, M.IDLE)

    def test_R6_no_request_before_the_A_scoring_is_complete(self):
        h = Host(); h.arrive()
        self.assertEqual(h.tick(100000 + 60000), [])           # a minute passes, the A scoring is not complete
        self.assertEqual(h.m.state, M.RECOGNIZED)

    def test_R7_request_exactly_at_arrival_plus_five_seconds_with_no_door_input(self):
        h = Host(); h.arrive(); h.scored()
        self.assertEqual(h.tick(100000 + 4999), [])
        acts = h.tick(100000 + 5000)
        self.assertEqual([a[0] for a in acts], ["request_jump"])
        self.assertEqual(acts[0][1]["target_index"], 6)
        for name in ("on_arrival", "a_scoring_complete", "tick", "on_jump_complete", "on_b_established", "on_jump_failed"):
            params = " ".join(inspect.signature(getattr(M.TurnbackMachine, name)).parameters)
            self.assertIsNone(re.search(r"door|signal|flag", params, re.I), name)

    def test_R8_R9_one_request_for_any_number_of_ticks_and_duplicate_arrivals(self):
        h = Host(); h.arrive(); h.scored()
        for k in range(100):
            h.arrive(now=100000 + k)                            # the same arrival seen on many ticks
        for k in range(200):
            h.tick(100000 + 5000 + k)
        self.assertEqual(len(h.requests()), 1)

    def test_R10_purpose_is_turnback_and_distinct(self):
        import jump_transaction as J
        h = Host(); h.arrive(); h.scored(); h.tick(105000)
        self.assertEqual(h.requests()[0][1]["purpose"], "turnback")
        self.assertNotIn(M.PURPOSE_TURNBACK, J.JUMPS)

    def test_R22_R34_pause_and_menu_hold_the_request_without_losing_it(self):
        h = Host(); h.arrive(); h.scored()
        self.assertEqual(h.tick(110000, paused=True), [])
        self.assertEqual(h.tick(110000, menu=True), [])
        self.assertEqual(len(h.tick(110000)), 1)

    def test_display_phases_in_bve_time(self):
        # Owner display contract (2026-10-31): WITHOUT a special arrival popup the guidance is shown for the whole 5.0 s (never split 3 s + 2 s)
        h = Host(); h.arrive(); h.scored()
        self.assertEqual(h.m.display_phase(100000 + 100), "guide")
        self.assertEqual(h.m.display_phase(100000 + 3000), "guide")
        self.assertEqual(h.m.display_phase(100000 + 4999), "guide")
        self.assertIsNone(h.m.display_phase(100000 + 5000))
        # WITH one the special popup is shown for 3.0 s, then the guidance for 2.0 s
        h = Host(); h.arrive(); h.run(h.m.a_scoring_complete(100000, True, True))
        self.assertEqual(h.m.display_phase(100000 + 100), "special")
        self.assertEqual(h.m.display_phase(100000 + 2999), "special")
        self.assertEqual(h.m.display_phase(100000 + 3000), "guide")
        self.assertEqual(h.m.display_phase(100000 + 4999), "guide")
        self.assertIsNone(h.m.display_phase(100000 + 5000))


class UseConditions(unittest.TestCase):
    def test_R26_R27_not_a_pair_station_starts_nothing(self):
        for a in (1, 4, 6, 7, 19):
            h = Host(); h.arrive(a=a); h.scored()
            self.assertEqual(h.m.state, M.IDLE, a)
            self.assertEqual(h.tick(10 ** 7), [])

    def test_PU1_start_station_must_be_before_A(self):
        for start in (5, 6, 9):
            h = Host(); h.arrive(start=start)
            self.assertEqual(h.m.state, M.IDLE, start)

    def test_PU2_PU3_end_station_rules(self):
        h = Host(); h.arrive(end=5);  self.assertEqual(h.m.state, M.IDLE)          # end == A: the user's terminal wins
        h = Host(); h.arrive(end=3);  self.assertEqual(h.m.state, M.IDLE)          # end < A
        h = Host(); h.arrive(explicit_end=6);  self.assertEqual(h.m.state, M.IDLE)  # explicit end == B is not selectable
        h = Host(); h.arrive(end=19, explicit_end=-1); self.assertEqual(h.m.state, M.RECOGNIZED)   # -1 default end is not B

    def test_PU5_list_identity_must_match(self):
        h = Host(); h.arrive(lid="00000001"); self.assertEqual(h.m.state, M.IDLE)
        h = Host(); h.arrive(count=21); self.assertEqual(h.m.state, M.IDLE)

    def test_R36_absent_or_invalid_key_is_the_current_behaviour(self):
        h = Host(); h.m.set_pairset(None); h.arrive(); h.scored()
        self.assertEqual(h.tick(10 ** 7), [])
        ps, why = C.decode_ptpair("PTPAIR:1:%s:20:1:5-6-9" % LID, 20)
        self.assertIsNone(ps)
        h.m.set_pairset(ps); h.arrive(); self.assertEqual(h.m.state, M.IDLE)

    def test_scoring_inactive_never_starts(self):
        h = Host(); h.arrive(active=False); self.assertEqual(h.m.state, M.IDLE)


class AOperatingTime(unittest.TestCase):
    def test_OD_PR4_A_time_scored_once_only_for_a_timing_pair_A(self):
        h = Host(); h.arrive()
        h.scored(timing=True); h.scored(timing=True); h.scored(timing=True)
        h.tick(105000)
        h.m.on_jump_complete(True, 6, GEN); h.m.on_b_established(106000)
        self.assertEqual(h.kinds().count("score_a_time"), 1)

    def test_not_a_timing_station_adds_nothing(self):
        h = Host(); h.arrive(); h.scored(timing=False)
        self.assertEqual(h.kinds().count("score_a_time"), 0)

    def test_normal_station_gets_no_extra_time_score(self):
        h = Host(); h.arrive(a=7); h.scored(timing=True)
        self.assertEqual(h.kinds(), [])

    def test_B_landing_does_not_add_the_A_score_again(self):
        h = Host(); h.arrive(); h.scored(); h.tick(105000)
        h.run(h.m.on_jump_complete(True, 6, GEN)); h.run(h.m.on_b_established(106000))
        self.assertEqual(h.kinds().count("score_a_time"), 1)


class CheckpointBeta(unittest.TestCase):
    def full(self, h):
        h.arrive(); h.scored(); h.tick(105000)
        h.run(h.m.on_jump_complete(True, 6, GEN))
        h.run(h.m.on_b_established(106000))

    def test_no_A_checkpoint_ever_and_exactly_one_B_checkpoint(self):
        h = Host(); self.full(h)
        cps = [a for a in h.actions if a[0] == "create_b_checkpoint"]
        self.assertEqual(len(cps), 1)
        self.assertEqual(cps[0][1]["station_index"], 6)
        self.assertEqual(cps[0][1]["stop_error"], 0.0)
        self.assertFalse(cps[0][1]["save_time_correction"])
        self.assertFalse([a for a in h.actions if "checkpoint" in a[0] and a[0] != "create_b_checkpoint"])
        for a in h.actions:
            if a[0] == "create_b_checkpoint":
                self.assertNotEqual(a[1]["station_index"], 5)

    def test_no_B_checkpoint_before_the_Jump_completed(self):
        h = Host(); h.arrive(); h.scored(); h.tick(105000)
        self.assertEqual(h.run(h.m.on_b_established(105001)), [])          # established is reported too early
        self.assertEqual(h.kinds().count("create_b_checkpoint"), 0)

    def test_B_checkpoint_waits_for_B_established(self):
        h = Host(); h.arrive(); h.scored(); h.tick(105000)
        self.assertEqual(h.run(h.m.on_jump_complete(True, 6, GEN)), [])
        self.assertEqual(h.kinds().count("create_b_checkpoint"), 0)
        self.assertEqual(len(h.run(h.m.on_b_established(106000))), 1)
        self.assertEqual(h.run(h.m.on_b_established(106001)), [])           # never a second one for the same Pair

    def test_R11_failure_never_creates_a_checkpoint_or_finishes(self):
        for how in ("timeout", "mismatch"):
            h = Host(); h.arrive(); h.scored(); h.tick(105000)
            if how == "timeout":
                h.run(h.m.on_jump_failed("timeout"))
            else:
                h.run(h.m.on_jump_complete(True, 5, GEN))                    # landed on A: does not prove the request
            self.assertEqual(h.m.state, M.FAILED)
            self.assertEqual(h.run(h.m.on_b_established(106000)), [])
            self.assertEqual([k for k in h.kinds() if k in ("create_b_checkpoint", "finish_scoring_after_jump")], [])

    def test_duplicate_and_unsolicited_completions_change_nothing(self):
        h = Host()
        self.assertEqual(h.run(h.m.on_jump_complete(True, 6, GEN)), [])     # unsolicited
        h.arrive(); h.scored(); h.tick(105000)
        h.run(h.m.on_jump_complete(True, 6, GEN))
        self.assertEqual(h.run(h.m.on_jump_complete(True, 6, GEN)), [])     # duplicate
        h.run(h.m.on_b_established(106000))
        self.assertEqual(h.kinds().count("create_b_checkpoint"), 1)

    def test_a_finished_arrival_is_not_issued_again(self):
        h = Host(); self.full(h)
        h.arrive(now=200000)                                                # the same ARRSEQ seen again
        h.scored(now=200000); h.tick(300000)
        self.assertEqual(len(h.requests()), 1)
        h.arrive(now=400000, seq=2); h.scored(now=400000); h.tick(405000)    # a NEW arrival of A (e.g. after a retry) is a new chain
        self.assertEqual(len(h.requests()), 2)


class FinalPair(unittest.TestCase):
    def test_R35_finish_is_decided_inside_the_completion_and_creates_no_checkpoint(self):
        h = Host("PTPAIR:1:%s:12:1:10-11-1" % LID, 12)
        h.arrive(a=10, end=11, explicit_end=-1)
        self.assertEqual(h.m.state, M.RECOGNIZED)
        h.scored(timing=True); h.tick(105000)
        acts = h.run(h.m.on_jump_complete(True, 11, GEN))
        self.assertEqual([a[0] for a in acts], ["finish_scoring_after_jump"])
        self.assertEqual(h.run(h.m.on_b_established(106000)), [])
        self.assertEqual([k for k in h.kinds() if "checkpoint" in k], [])
        self.assertEqual(h.kinds().count("score_a_time"), 1)


class DiscardAndReset(unittest.TestCase):
    def test_R19_retry_drops_the_pending_chain_and_rebuilds_from_a_later_arrival(self):
        for stage in ("recognized", "armed", "requested"):
            h = Host(); h.arrive()
            if stage != "recognized": h.scored()
            if stage == "requested": h.tick(105000)
            acts = h.run(h.m.on_retry())
            self.assertEqual(acts, [("discard_pending", "retry")], stage)
            self.assertEqual(h.m.state, M.IDLE)
            self.assertEqual(h.tick(10 ** 7), [])

    def test_R20_f5_drops_everything_and_forgets_the_issued_keys(self):
        h = Host(); h.arrive(); h.scored(); h.tick(105000)
        self.assertEqual(h.run(h.m.on_f5()), [("discard_pending", "world-reset")])
        self.assertEqual(h.m.issued, set())
        self.assertEqual(h.run(h.m.on_jump_complete(True, 6, GEN)), [])     # the old completion is stale
        h.arrive(seq=1); h.scored(); h.tick(205000)                         # the new world may use the same ARRSEQ
        self.assertEqual(len(h.requests()), 2)

    def test_R21_generation_change_never_executes_the_old_request(self):
        h = Host(); h.arrive(); h.scored()
        self.assertEqual(h.tick(105000, gen=GEN + 1), [("discard_pending", "generation")])
        h = Host(); h.arrive(); h.scored(); h.tick(105000)
        self.assertEqual(h.run(h.m.on_jump_complete(True, 6, GEN + 1)), [("discard_pending", "generation")])
        self.assertEqual(h.run(h.m.on_b_established(106000)), [])

    def test_R23_R24_scenario_close_and_input_device_off(self):
        for fn in ("on_scenario_close", "on_input_device_off"):
            h = Host(); h.arrive(); h.scored()
            self.assertEqual(h.run(getattr(h.m, fn)()), [("discard_pending", "world-reset")], fn)
            self.assertEqual(h.tick(10 ** 7), [])

    def test_scoring_ended_discards_the_armed_chain(self):
        h = Host(); h.arrive(); h.scored()
        self.assertEqual(h.tick(105000, active=False), [("discard_pending", "scoring-ended")])

    def test_B_resync_pending_is_dropped_by_f5(self):
        h = Host(); h.arrive(); h.scored(); h.tick(105000); h.run(h.m.on_jump_complete(True, 6, GEN))
        self.assertEqual(h.run(h.m.on_f5()), [("discard_pending", "world-reset")])
        self.assertEqual(h.run(h.m.on_b_established(106000)), [])


class MachineIsDoorAndSignalBlind(unittest.TestCase):
    def test_R3_R4_source_has_no_door_signal_distance_or_name_identifier(self):
        with open(os.path.join(ROOT, "pseudo_turnback_machine.py"), encoding="utf-8") as fh:
            text = fh.read()
        text = re.sub(r'"""[\s\S]*?"""', "", text)
        code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        for pat in (r"door", r"signal", r"distance", r"location", r"\bnames?\b", r"\babs\(", r"station_list", r"speed"):
            self.assertIsNone(re.search(pat, code, re.I), pat)


if __name__ == "__main__":
    unittest.main()
