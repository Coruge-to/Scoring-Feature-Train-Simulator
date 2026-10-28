"""Phase SI-R2.3 (C4a): the pure display-target contract (hud_target_contract.py).

Pure: no Qt, no Overlay, no clock. Every row runs under Gate A (`python -I`). The connection to the Overlay and the HUD (the properties, the sync points, the draw_hud reads) is tested by
test_hud_target_wiring_r23.py with the C4b change set; the RED rows of tests/red_official_target_*.py observe the whole path.

The NEXTTIME table is the one of the SI-R2.3 Entry (nexttime-contract.md section 2). The vector rows below are the SAME vectors the RED runner R-NT-EQ uses (tests/official_target_vectors.json):
the derivation must give the C# NEXTTIME (the vector's target_nexttime) for every step of NT-01..NT-04, NT-POS, NT-ZERO and TERM-2.
"""
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hud_target_contract as H  # noqa: E402
import official_target_contract as OC  # noqa: E402
import official_target_wire_fixture as F  # noqa: E402

SCOPE = (7, "ABCD1234")
T0 = 36000000


def station(location, arr=-1, dep=-1, is_pass=False, is_terminal=False):
    return {"location": float(location), "raw_arr": arr, "raw_dep": dep, "is_pass": is_pass, "is_terminal": is_terminal}


LIST = [station(0, T0 - 60000, T0 - 10000), station(1000, T0 + 60000, T0 + 120000), station(2000, T0 + 360000, T0 + 420000, is_pass=True),
        station(3000, T0 + 660000, -1, is_terminal=True), station(4000, 0, 0)]
MACHINE = H.MachineTarget(2500.0, T0 + 5000, 1, 4.0, 6.0, True)


def official(state=OC.KNOWN, index=1, location=None, mb=5.0, mf=5.0, reason="off-ok"):
    if location is None:
        location = LIST[index]["location"] if state == OC.KNOWN else -1.0
    return H.OfficialTarget(state, index if state == OC.KNOWN else -1, location, mb if state == OC.KNOWN else -1.0, mf if state == OC.KNOWN else -1.0, reason)


def derive(scoring=False, off=None, timing=False, station_list=LIST, location=500.0, time_ms=T0, door=0, scope=SCOPE, freeze=None, machine=MACHINE):
    return H.derive(scoring, lambda: machine, off if off is not None else official(), lambda index: timing, station_list, location, time_ms, door, scope, freeze)


class OwnerRule(unittest.TestCase):
    def test_the_owner_expression_truth_table(self):
        self.assertTrue(H.owner_is_scoring(True, False))
        self.assertFalse(H.owner_is_scoring(True, True))      # finished: BVE again
        self.assertFalse(H.owner_is_scoring(False, False))    # no scoring session
        self.assertFalse(H.owner_is_scoring(False, True))

    def test_a_non_bool_flag_is_read_as_the_expression_does(self):
        self.assertTrue(H.owner_is_scoring(1, 0))
        self.assertFalse(H.owner_is_scoring(0, 0))
        self.assertFalse(H.owner_is_scoring(None, None))

    def test_the_owner_is_derived_on_every_call_and_never_latched(self):
        seen = []
        for mode, finished in ((False, False), (True, False), (True, True), (True, False), (False, False)):
            seen.append(H.owner_is_scoring(mode, finished))
        self.assertEqual(seen, [False, True, False, True, False])


class ScoringOwner(unittest.TestCase):
    def test_the_scoring_target_is_shown_as_it_is(self):
        target, freeze = derive(scoring=True, off=official(OC.KNOWN, 3))
        self.assertEqual((target.owner, target.source, target.reason), (H.OWNER_TS, H.SOURCE_MACHINE, H.R_MACHINE))
        self.assertEqual((target.next_loc, target.next_time, target.is_pass, target.margin_b, target.margin_f, target.timing), tuple(MACHINE))
        self.assertIsNone(freeze)

    def test_the_official_target_is_not_read_while_scoring(self):
        for off in (official(OC.KNOWN, 3), official(OC.NONE_TERMINAL, reason="off-none-terminal"), official(OC.UNAVAILABLE, reason="off-unavailable"),
                    official(OC.NOT_INITIALIZED, reason="off-not-ready"), None):
            with self.subTest(off=off):
                target, _freeze = H.derive(True, lambda: MACHINE, off, lambda index: True, LIST, 500.0, T0, 0, SCOPE, None)       # the official argument may even be None
                self.assertEqual(tuple(target)[2:8], tuple(MACHINE))

    def test_a_machine_none_stays_none_and_is_not_replaced_by_the_official_target(self):
        none_machine = H.MachineTarget(-1.0, -1, 0, 5.0, 5.0, False)
        target, _freeze = derive(scoring=True, off=official(OC.KNOWN, 2), machine=none_machine)
        self.assertEqual((target.next_loc, target.next_time), (-1.0, -1))
        self.assertEqual(target.source, H.SOURCE_MACHINE)

    def test_a_scoring_owner_discards_the_terminal_freeze(self):
        freeze = H.TerminalFreeze(SCOPE, 3, 40)
        _target, kept = derive(scoring=True, freeze=freeze)
        self.assertIsNone(kept)


class Reads(unittest.TestCase):
    """What is read when: the scoring target only for a scoring owner, the timing flag only for a KNOWN target."""

    @staticmethod
    def boom(*_args):
        raise AssertionError("read although the contract says it is not read here")

    def test_the_machine_target_is_not_asked_for_when_bve_owns_the_target(self):
        target, _freeze = H.derive(False, self.boom, official(OC.KNOWN, 1), lambda index: False, LIST, 500.0, T0, 0, SCOPE, None)
        self.assertEqual(target.source, H.SOURCE_OFFICIAL)

    def test_the_timing_flag_is_not_asked_for_unless_the_target_is_known(self):
        for state in (OC.NONE_TERMINAL, OC.NONE_EMPTY, OC.UNAVAILABLE, OC.READ_FAILED, OC.ABSENT, OC.INVALID, OC.NOT_INITIALIZED):
            with self.subTest(state=state):
                H.derive(False, self.boom, official(state, reason="x"), self.boom, LIST, 500.0, T0, 0, SCOPE, None)
        H.derive(True, lambda: MACHINE, official(OC.KNOWN, 1), self.boom, LIST, 500.0, T0, 0, SCOPE, None)       # scoring owner: the timing flag is the machine's
        H.derive(False, self.boom, official(OC.KNOWN, 9, location=9000.0), self.boom, LIST, 500.0, T0, 0, SCOPE, None)            # a bad index is none before any flag is asked for

    def test_the_timing_flag_receives_the_official_index(self):
        asked = []
        H.derive(False, self.boom, official(OC.KNOWN, 2), lambda index: asked.append(index) or True, LIST, 500.0, T0, 0, SCOPE, None)
        self.assertEqual(asked, [2])

    def test_the_published_attributes_are_the_six_of_the_receiver(self):
        self.assertEqual(set(H.OFFTGT_ATTRS), set(OC.initial_state()))
        self.assertEqual(len(H.OFFTGT_ATTRS), 6)
        # the order is the field order of OfficialTarget: offtgt_of(source) builds the tuple positionally
        self.assertEqual(H.OFFTGT_ATTRS, tuple("official_" + field for field in H.OfficialTarget._fields))
        self.assertEqual(H.OFFTGT_ATTRS, ("official_state", "official_index", "official_location", "official_margin_b", "official_margin_f", "official_reason"))

    def test_offtgt_of_puts_every_value_into_its_own_field(self):
        defaults = OC.initial_state()
        source = type("Published", (), dict(defaults, official_state="KNOWN", official_index=3, official_location=3000.0, official_margin_b=1.5, official_margin_f=2.5, official_reason="off-ok"))()
        got = H.offtgt_of(source)
        self.assertEqual((got.state, got.index, got.location, got.margin_b, got.margin_f, got.reason), ("KNOWN", 3, 3000.0, 1.5, 2.5, "off-ok"))

    def test_offtgt_of_reads_the_six_attributes_and_writes_nothing(self):
        class Source(object):
            pass
        source = Source()
        for index, name in enumerate(H.OFFTGT_ATTRS):
            setattr(source, name, index)
        before = dict(vars(source))
        got = H.offtgt_of(source)
        self.assertEqual(tuple(got), (0, 1, 2, 3, 4, 5))
        self.assertEqual(vars(source), before)
        self.assertEqual(H.offtgt_of(type("Defaults", (), OC.initial_state())()), H.OfficialTarget(OC.NOT_INITIALIZED, -1, -1.0, -1.0, -1.0, "off-not-ready"))


class OfficialKnown(unittest.TestCase):
    def test_a_known_target_is_the_official_station(self):
        target, freeze = derive(off=official(OC.KNOWN, 1, mb=3.0, mf=7.0), timing=True, time_ms=T0)
        self.assertEqual((target.owner, target.source, target.reason), (H.OWNER_BVE, H.SOURCE_OFFICIAL, H.R_OFFICIAL))
        self.assertEqual((target.next_loc, target.is_pass, target.margin_b, target.margin_f, target.timing), (1000.0, 0, 3.0, 7.0, True))
        self.assertEqual(target.next_time, T0 + 60000)
        self.assertIsNone(freeze)

    def test_the_machine_target_is_not_used_when_bve_owns_the_target(self):
        target, _freeze = derive(off=official(OC.KNOWN, 0))
        self.assertNotEqual(target.next_loc, MACHINE.next_loc)
        self.assertEqual(target.next_loc, 0.0)                    # the location of station 0 is 0.0: a valid target, not 'none'

    def test_a_pass_station_is_labelled_a_pass(self):
        target, _freeze = derive(off=official(OC.KNOWN, 2))
        self.assertEqual(target.is_pass, 1)

    def test_the_timing_flag_is_the_callers_and_is_not_invented(self):
        self.assertFalse(derive(timing=False)[0].timing)
        self.assertTrue(derive(timing=True)[0].timing)

    def test_the_identity_is_the_index_not_a_distance(self):
        for location in (0.0, 999.0, 1000.0, 1999.0, 2999.0, 99999.0):
            with self.subTest(location=location):
                self.assertEqual(derive(off=official(OC.KNOWN, 1), location=location)[0].next_loc, 1000.0)


class NoneStates(unittest.TestCase):
    CASES = (
        (OC.NONE_TERMINAL, "off-none-terminal", "hud-none-terminal"),
        (OC.NONE_EMPTY, "off-none-empty", "hud-none-empty"),
        (OC.UNAVAILABLE, "off-unavailable", "hud-none-unavailable"),
        (OC.READ_FAILED, "off-read-failed", "hud-none-read-failed"),
        (OC.ABSENT, "off-missing", "hud-none-absent"),
        (OC.INVALID, "off-range", "hud-none-invalid"),
        (OC.NOT_INITIALIZED, "off-not-ready", "hud-none-not-initialized"),
    )

    def test_every_state_but_known_is_none_with_a_reason_of_its_own(self):
        reasons = []
        for state, off_reason, hud_reason in self.CASES:
            with self.subTest(state=state):
                target, freeze = derive(off=official(state, reason=off_reason))
                self.assertEqual((target.owner, target.source, target.next_loc, target.next_time, target.timing), (H.OWNER_BVE, H.SOURCE_NONE, -1.0, -1, False))
                self.assertEqual(target.reason, hud_reason)
                self.assertIsNone(freeze)
                reasons.append(target.reason)
        self.assertEqual(len(set(reasons)), len(reasons))        # U / F / T / N / ABSENT / INVALID / NOT_INITIALIZED are told apart

    def test_the_reason_table_covers_every_non_known_state_of_the_receiver(self):
        states = {OC.NONE_TERMINAL, OC.NONE_EMPTY, OC.UNAVAILABLE, OC.READ_FAILED, OC.ABSENT, OC.INVALID, OC.NOT_INITIALIZED}
        self.assertEqual(set(H.NONE_REASON), states)

    def test_an_unknown_state_word_is_none_too(self):
        target, _freeze = derive(off=H.OfficialTarget("SOMETHING", 1, 1000.0, 5.0, 5.0, "x"))
        self.assertEqual((target.source, target.reason, target.next_loc), (H.SOURCE_NONE, H.R_UNKNOWN_STATE, -1.0))

    def test_a_known_target_whose_index_the_list_does_not_have_is_none(self):
        for index in (-1, 5, 99, None, True, "1"):
            with self.subTest(index=index):
                target, _freeze = derive(off=H.OfficialTarget(OC.KNOWN, index, 1000.0, 5.0, 5.0, "off-ok"))
                self.assertEqual((target.source, target.reason, target.next_loc), (H.SOURCE_NONE, H.R_BAD_INDEX, -1.0))

    def test_an_empty_list_is_none(self):
        target, _freeze = derive(off=official(OC.KNOWN, 0), station_list=[])
        self.assertEqual((target.source, target.reason), (H.SOURCE_NONE, H.R_BAD_INDEX))

    def test_the_last_known_target_is_not_kept(self):
        # K -> U -> K -> F -> T: the display follows each state; nothing is carried over and nothing is converted into K
        sequence = [official(OC.KNOWN, 1), official(OC.UNAVAILABLE, reason="off-unavailable"), official(OC.KNOWN, 2), official(OC.READ_FAILED, reason="off-read-failed"),
                    official(OC.NONE_TERMINAL, reason="off-none-terminal")]
        sources, freeze = [], None
        for off in sequence:
            target, freeze = derive(off=off, freeze=freeze)
            sources.append((target.source, target.next_loc))
        self.assertEqual(sources, [(H.SOURCE_OFFICIAL, 1000.0), (H.SOURCE_NONE, -1.0), (H.SOURCE_OFFICIAL, 2000.0), (H.SOURCE_NONE, -1.0), (H.SOURCE_NONE, -1.0)])

    def test_the_terminal_none_is_not_hidden_behind_the_terminal_station(self):
        # official T (no station follows) is NONE even while the doors are open at the last station
        target, _freeze = derive(off=official(OC.NONE_TERMINAL, reason="off-none-terminal"), location=3000.0, door=1)
        self.assertEqual((target.source, target.next_loc, target.next_time), (H.SOURCE_NONE, -1.0, -1))

    def test_none_target_constants(self):
        self.assertEqual((H.NO_TARGET.owner, H.NO_TARGET.source, H.NO_TARGET.reason), (H.OWNER_BVE, H.SOURCE_NONE, "hud-none-not-initialized"))
        self.assertEqual(H.none_target(H.OWNER_TS, "x").owner, H.OWNER_TS)


class NextTime(unittest.TestCase):
    """nexttime-contract.md section 2, row by row (K target `entry`, t = time_ms)."""

    def time_of(self, index, location, time_ms, door, freeze=None, station_list=LIST):
        off = official(OC.KNOWN, index)
        return H.official_time(station_list[index], index, off.location, location, time_ms, door, SCOPE, freeze)

    def test_a_stop_station_running_shows_the_arrival(self):
        self.assertEqual(self.time_of(1, 500.0, T0, 0)[0], T0 + 60000)

    def test_a_stop_station_with_the_doors_open_at_the_target_shows_the_departure(self):
        self.assertEqual(self.time_of(1, 1000.0, T0 + 70000, 1)[0], T0 + 120000)
        self.assertEqual(self.time_of(1, 1000.0 - 99.9, T0 + 70000, 1)[0], T0 + 120000)

    def test_the_doors_open_far_from_the_target_are_not_a_departure(self):
        self.assertEqual(self.time_of(1, 1000.0 - 100.0, T0, 1)[0], T0 + 60000)      # exactly NEAR_M is not 'within'
        self.assertEqual(self.time_of(1, 0.0, T0, 1)[0], T0 + 60000)

    def test_the_doors_closed_at_the_target_show_the_arrival(self):
        self.assertEqual(self.time_of(1, 1000.0, T0, 0)[0], T0 + 60000)

    def test_a_pass_station_shows_the_arrival_whatever_the_doors_do(self):
        self.assertEqual(self.time_of(2, 1500.0, T0, 0)[0], T0 + 360000)
        self.assertEqual(self.time_of(2, 2000.0, T0, 1)[0], T0 + 360000)

    def test_a_time_that_is_not_defined_is_none(self):
        self.assertEqual(self.time_of(4, 3500.0, T0, 0)[0], -1)                    # arr 0 / dep 0 (the vector L4Z)
        self.assertEqual(self.time_of(4, 4000.0, T0, 1)[0], -1)
        for bad in (None, -1, 0, "36000000", True, 12.5):
            with self.subTest(bad=bad):
                self.assertEqual(self.time_of(1, 500.0, T0, 0, station_list=[station(0), {"location": 1000.0, "raw_arr": bad, "raw_dep": bad}])[0], -1)

    def test_the_departure_that_is_not_defined_is_none_not_the_arrival(self):
        entry = [station(0), station(1000, T0 + 60000, -1)]
        self.assertEqual(self.time_of(1, 1000.0, T0, 1, station_list=entry)[0], -1)

    def test_a_missing_key_is_not_defined(self):
        entry = [{"location": 0.0}, {"location": 1000.0}]
        self.assertEqual(self.time_of(1, 1000.0, T0, 1, station_list=entry)[0], -1)

    def test_a_terminal_before_the_doors_open_shows_the_arrival_and_keeps_no_freeze(self):
        time_ms, freeze = self.time_of(3, 2900.0, T0 + 600000, 0)
        self.assertEqual((time_ms, freeze), (T0 + 660000, None))

    def test_a_terminal_freezes_the_difference_when_the_doors_first_open(self):
        time_ms, freeze = self.time_of(3, 3000.0, T0 + 620000, 1)
        self.assertEqual(freeze, H.TerminalFreeze(SCOPE, 3, 40))
        self.assertEqual(time_ms, T0 + 620000 + 40000)
        # the freeze is the caller's: later Ticks show now + diff
        time_ms, freeze = self.time_of(3, 3000.0, T0 + 680000, 1, freeze)
        self.assertEqual((time_ms, freeze.diff_s), (T0 + 680000 + 40000, 40))

    def test_the_freeze_survives_the_doors_closing_and_a_jump_away(self):
        _t, freeze = self.time_of(3, 3000.0, T0 + 620000, 1)
        time_ms, kept = self.time_of(3, 3000.0, T0 + 650000, 0, freeze)
        self.assertEqual((time_ms, kept), (T0 + 650000 + 40000, freeze))
        time_ms, kept = self.time_of(3, 2500.0, T0 + 621000, 1, freeze)
        self.assertEqual((time_ms, kept), (T0 + 621000 + 40000, freeze))

    def test_doors_open_far_from_the_terminal_do_not_freeze(self):
        time_ms, freeze = self.time_of(3, 2500.0, T0 + 620000, 1)
        self.assertEqual((time_ms, freeze), (T0 + 660000, None))

    def test_the_freeze_difference_is_truncated_toward_zero_like_the_csharp_division(self):
        for arrival_offset, now_offset, expected in ((660500, 620000, 40), (660000, 620500, 39), (660000, 660000, 0), (660000, 660500, 0), (660000, 661500, -1), (660000, 662000, -2)):
            with self.subTest(arrival=arrival_offset, now=now_offset):
                terminal = [station(0), station(3000, T0 + arrival_offset, -1, is_terminal=True)]
                _t, freeze = H.official_time(terminal[1], 1, 3000.0, 3000.0, T0 + now_offset, 1, SCOPE, None)
                self.assertEqual(freeze.diff_s, expected)

    def test_a_late_terminal_shows_a_negative_remaining_time(self):
        time_ms, freeze = self.time_of(3, 3000.0, T0 + 700000, 1)
        self.assertEqual(freeze.diff_s, -40)
        self.assertEqual(time_ms, T0 + 700000 - 40000)

    def test_a_terminal_without_an_arrival_is_none_and_freezes_nothing(self):
        terminal = [station(0), station(3000, -1, -1, is_terminal=True)]
        self.assertEqual(H.official_time(terminal[1], 1, 3000.0, 3000.0, T0, 1, SCOPE, None), (-1, None))

    def test_a_departure_only_terminal_uses_the_arrival_the_sender_made_final(self):
        # the sender fills arr = dep - stoppage; the wire arr is the final one (nexttime-contract.md section 2)
        terminal = [station(0), station(3000, T0 + 645000, T0 + 660000, is_terminal=True)]
        self.assertEqual(H.official_time(terminal[1], 1, 3000.0, 2800.0, T0 + 600000, 0, SCOPE, None)[0], T0 + 645000)

    def test_the_freeze_does_not_cross_a_scope(self):
        _t, freeze = self.time_of(3, 3000.0, T0 + 620000, 1)
        other = (8, "ABCD1234")
        time_ms, kept = H.official_time(LIST[3], 3, 3000.0, 3000.0, T0 + 630000, 1, other, freeze)
        self.assertEqual(kept, H.TerminalFreeze(other, 3, 30))               # a new freeze of the new scope, not the old 40 s
        self.assertEqual(time_ms, T0 + 630000 + 30000)
        time_ms, kept = H.official_time(LIST[3], 3, 3000.0, 2900.0, T0 + 630000, 0, other, freeze)
        self.assertEqual((time_ms, kept), (T0 + 660000, None))                # nothing to freeze yet: the old freeze is gone, not shown
        _time, kept = H.official_time(LIST[3], 3, 3000.0, 3000.0, T0 + 630000, 1, (7, "FFFFFFFF"), freeze)
        self.assertEqual(kept.diff_s, 30)                                    # a different list identity is a different scope too

    def test_the_freeze_does_not_cross_an_index(self):
        _t, freeze = self.time_of(3, 3000.0, T0 + 620000, 1)
        time_ms, kept = H.official_time(LIST[1], 1, 1000.0, 500.0, T0 + 630000, 0, SCOPE, freeze)
        self.assertEqual((time_ms, kept), (T0 + 60000, None))

    def test_the_freeze_of_one_terminal_is_not_used_for_another_terminal(self):
        # a list that flags two stations as terminal (the freeze is keyed on the index too, not only on the scope)
        two = [station(0), station(3000, T0 + 660000, -1, is_terminal=True), station(4000, T0 + 800000, -1, is_terminal=True)]
        _t, freeze = H.official_time(two[1], 1, 3000.0, 3000.0, T0 + 620000, 1, SCOPE, None)
        self.assertEqual(freeze, H.TerminalFreeze(SCOPE, 1, 40))
        time_ms, kept = H.official_time(two[2], 2, 4000.0, 4000.0, T0 + 700000, 1, SCOPE, freeze)
        self.assertEqual(kept, H.TerminalFreeze(SCOPE, 2, 100))
        self.assertEqual(time_ms, T0 + 700000 + 100000)

    def test_only_a_known_official_target_keeps_a_freeze(self):
        _t, freeze = self.time_of(3, 3000.0, T0 + 620000, 1)
        for off in (official(OC.UNAVAILABLE, reason="off-unavailable"), official(OC.NONE_TERMINAL, reason="off-none-terminal"), official(OC.NOT_INITIALIZED, reason="off-not-ready")):
            with self.subTest(state=off.state):
                self.assertIsNone(derive(off=off, freeze=freeze)[1])
        self.assertIsNone(derive(scoring=True, freeze=freeze)[1])
        self.assertEqual(derive(off=official(OC.KNOWN, 3), freeze=freeze, location=3000.0, door=1, time_ms=T0 + 630000)[1], freeze)

    def test_derive_keeps_the_freeze_through_a_known_terminal_and_makes_one(self):
        target, freeze = derive(off=official(OC.KNOWN, 3), location=3000.0, door=1, time_ms=T0 + 620000)
        self.assertEqual((target.next_time, freeze), (T0 + 660000, H.TerminalFreeze(SCOPE, 3, 40)))
        target, freeze = derive(off=official(OC.KNOWN, 3), location=3000.0, door=1, time_ms=T0 + 680000, freeze=freeze)
        self.assertEqual(target.next_time, T0 + 720000)


class VectorEquivalence(unittest.TestCase):
    """The derivation reproduces the C# NEXTTIME of the meaning vectors (the pure twin of the RED row R-NT-EQ)."""

    @classmethod
    def setUpClass(cls):
        cls.vec = F.load_vectors()

    def entries(self, key):
        return [{"location": s["location"], "raw_arr": s.get("arr", -1), "raw_dep": s.get("dep", -1), "is_pass": bool(s.get("pass")), "is_terminal": bool(s.get("terminal"))}
                for s in self.vec["lists"][key]]

    def run_case(self, case_id):
        case = F.case_by_id(self.vec, case_id)
        current_list = case["list"]
        freeze, scope_no, checked = None, 0, 0
        for step, state in F.iter_merged(case):
            if "list" in step:
                current_list = step["list"]
            if "generation" in step:
                scope_no = step["generation"]
            expect = step.get("expect", {})
            if expect.get("owner") != "BVE" or "target_nexttime" not in expect:
                continue
            official_step = step["official"]
            entries = self.entries(current_list)
            if official_step["state"] != "K":
                freeze = None
                self.assertEqual(expect["target_nexttime"], -1)
                continue
            index = official_step["index"]
            scope = (state["sid"], current_list, scope_no)
            got, freeze = H.official_time(entries[index], index, entries[index]["location"], state["loc"], state["time_ms"], state["door"], scope, freeze)
            wanted = expect["target_nexttime"] if expect["target_nexttime"] > 0 else H.NO_TIME            # the C# value 0 is 'no time' (the HUD reads NEXTTIME > 0)
            self.assertEqual(got, wanted, "%s step %s" % (case_id, step.get("note", state["time_ms"])))
            checked += 1
        self.assertGreater(checked, 0)

    def test_the_vectors_of_the_nexttime_derivation(self):
        for case_id in ("NT-01", "NT-02", "NT-03", "NT-04", "NT-04-GEN", "NT-POS", "NT-ZERO", "TERM-2"):
            with self.subTest(case=case_id):
                self.run_case(case_id)


class SourceDiscipline(unittest.TestCase):
    """The module is a read model: no write to any application state, no outside dependency, none of the words the contract forbids."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "hud_target_contract.py"), encoding="utf-8") as fh:
            cls.source = fh.read()
        cls.tree = ast.parse(cls.source)

    def test_the_module_imports_nothing_but_the_receiver_constants(self):
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(sorted(imports), ["collections", "official_target_contract"])

    def test_no_attribute_is_assigned_anywhere(self):
        stores = [n for n in ast.walk(self.tree) if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del))]
        self.assertEqual(stores, [])
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal))

    def test_no_subscript_is_assigned_so_no_input_is_changed(self):
        stores = [n for n in ast.walk(self.tree) if isinstance(n, ast.Subscript) and isinstance(n.ctx, (ast.Store, ast.Del))]
        self.assertEqual(stores, [])

    def test_the_forbidden_words_are_absent(self):
        tree = ast.parse(self.source)
        for node in ast.walk(tree):                                  # the docstrings explain the contract in its own words: only the code is searched
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                body[0] = ast.Pass()
        code = ast.unparse(tree)
        for word in ("bve_next_", "bve_tgt_idx", "bve_arr_idx", "is_scoring_mode =", "bve5", "bve6", "landing", "touchdown", "TerminalDepartureTime", "GoTo", "nearest", "PyQt", "win32", "time.time",
                     "monotonic", "datetime", "target_arm"):
            self.assertNotIn(word, code, word)

    def test_no_last_known_target_is_kept(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} | {n.arg for n in ast.walk(self.tree) if isinstance(n, ast.arg)}
        for name in names:
            self.assertNotIn("last", name.lower())
            self.assertNotIn("previous", name.lower())
            self.assertNotIn("held", name.lower())

    def test_the_results_are_immutable_and_the_calls_repeat(self):
        target, freeze = derive(off=official(OC.KNOWN, 3), location=3000.0, door=1, time_ms=T0 + 620000)
        with self.assertRaises(AttributeError):
            target.next_loc = 1.0
        with self.assertRaises(AttributeError):
            freeze.diff_s = 1
        again = derive(off=official(OC.KNOWN, 3), location=3000.0, door=1, time_ms=T0 + 620000)
        self.assertEqual((target, freeze), again)

    def test_the_inputs_are_not_changed(self):
        station_list = [dict(s) for s in LIST]
        before = [dict(s) for s in station_list]
        derive(off=official(OC.KNOWN, 3), station_list=station_list, location=3000.0, door=1, time_ms=T0 + 620000)
        self.assertEqual(station_list, before)

    def test_the_constants_of_the_contract(self):
        self.assertEqual(H.NEAR_M, 100.0)
        self.assertEqual(H.NO_TIME, -1)
        self.assertEqual((H.OWNER_TS, H.OWNER_BVE), ("TS", "BVE"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
