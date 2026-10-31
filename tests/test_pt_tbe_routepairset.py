"""Stage TB-E (A): the RoutePairSet holder, pure. The static, certified pair set of the CURRENT scenario generation as the Python side accepts it (OD-TE-1..6).

The holder only JUDGES what the C# Qualifier published (PTPAIR:1:<list_id>:<station_count>:<pair_count>:<entries>): it never qualifies a pair. Three states are kept apart (OD-TE-4): UNAVAILABLE (nothing
accepted for this generation), READY_EMPTY (the sender stated: zero pairs) and READY_NONEMPTY. The generation is the SCENARIO_ID of the line that carried the key (received) against the Overlay's
current_scenario_id (current): older is dropped, equal is judged, newer is never applied ahead (OD-TE-3). A repeated identical text changes nothing; a different valid text of the same binding is a conflict and
never overwrites the first (OD-TE-5)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LID = "A1B2C3D4"
EMPTY = "PTPAIR:1:%s:5:0:" % LID
ONE = "PTPAIR:1:%s:5:1:1-2-0" % LID
TWO = "PTPAIR:1:%s:6:2:1-2-0;3-4-0" % LID


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import route_pairset
        cls.RP = route_pairset

    def holder(self):
        return self.RP.RoutePairSetHolder()

    def offer(self, h, text, received=7, current=7, list_id=LID, count=5):
        return h.offer(received, current, text, list_id, count)


class A_States(Base):
    def test_a_new_holder_is_unavailable_and_holds_nothing(self):
        h = self.holder()
        self.assertEqual((h.state, h.pairset, h.text, h.generation), (self.RP.UNAVAILABLE, None, None, None))

    def test_the_three_states_are_three_different_values(self):
        RP = self.RP
        self.assertEqual(len({RP.UNAVAILABLE, RP.READY_EMPTY, RP.READY_NONEMPTY}), 3)

    def test_zero_pairs_stated_by_the_sender_is_ready_empty_not_unavailable(self):
        h = self.holder()
        verdict, why = self.offer(h, EMPTY)
        self.assertEqual((verdict, h.state), (self.RP.ACCEPTED, self.RP.READY_EMPTY))
        self.assertNotEqual(h.state, self.RP.UNAVAILABLE)
        self.assertEqual(h.pairset.pairs, ())

    def test_one_pair_is_ready_nonempty(self):
        h = self.holder()
        self.offer(h, ONE)
        self.assertEqual(h.state, self.RP.READY_NONEMPTY)
        self.assertEqual([(p.arrival, p.departure, p.mode) for p in h.pairset.pairs], [(1, 2, 0)])

    def test_several_pairs_keep_their_order(self):
        h = self.holder()
        self.offer(h, TWO, count=6)
        self.assertEqual(h.state, self.RP.READY_NONEMPTY)
        self.assertEqual([(p.arrival, p.departure) for p in h.pairset.pairs], [(1, 2), (3, 4)])

    def test_the_absence_of_the_key_is_not_an_empty_set(self):
        h = self.holder()
        verdict, why = h.offer(7, 7, None, LID, 5)
        self.assertEqual((verdict, h.state), (self.RP.UNCHANGED, self.RP.UNAVAILABLE))

    def test_no_station_list_is_no_binding(self):
        h = self.holder()
        verdict, why = h.offer(7, 7, ONE, "", 0)
        self.assertEqual((verdict, h.state), (self.RP.REJECTED, self.RP.UNAVAILABLE))


class B_Validation(Base):
    BAD = (
        ("same index (a == b)", "PTPAIR:1:%s:5:1:1-1-0" % LID),
        ("duplicate pair", "PTPAIR:1:%s:5:2:1-2-0;1-2-0" % LID),
        ("duplicate A", "PTPAIR:1:%s:5:2:1-2-0;1-3-0" % LID),
        ("duplicate B / overlap", "PTPAIR:1:%s:6:2:1-2-0;2-3-0" % LID),
        ("out of range index", "PTPAIR:1:%s:5:1:4-5-0" % LID),
        ("a == 0", "PTPAIR:1:%s:5:1:0-1-0" % LID),
        ("wrong order", "PTPAIR:1:%s:6:2:3-4-0;1-2-0" % LID),
        ("missing parts", "PTPAIR:1:%s:5:1" % LID),
        ("missing payload", "PTPAIR"),
        ("other version", "PTPAIR:2:%s:5:1:1-2-0" % LID),
        ("count mismatch", "PTPAIR:1:%s:5:2:1-2-0" % LID),
        ("station count mismatch", "PTPAIR:1:%s:6:1:1-2-0" % LID),
        ("other station list", "PTPAIR:1:FFFFFFFF:5:1:1-2-0"),
        ("non numeric", "PTPAIR:1:%s:5:1:x-2-0" % LID),
        ("unknown mode", "PTPAIR:1:%s:5:1:1-2-7" % LID),
        ("other key name", "OTHERKEY:1:%s:5:1:1-2-0" % LID),
        ("not a text", 5),
    )

    def test_every_invalid_payload_is_rejected_and_leaves_the_holder_unavailable(self):
        for label, text in self.BAD:
            with self.subTest(label):
                h = self.holder()
                verdict, why = self.offer(h, text)
                self.assertEqual(verdict, self.RP.REJECTED, label)
                self.assertTrue(why)
                self.assertEqual((h.state, h.pairset, h.text), (self.RP.UNAVAILABLE, None, None), label)

    def test_an_invalid_payload_never_damages_an_accepted_set(self):
        for label, text in self.BAD:
            with self.subTest(label):
                h = self.holder()
                self.offer(h, ONE)
                keep = (h.state, h.pairset, h.text)
                verdict, why = self.offer(h, text)
                self.assertEqual(verdict, self.RP.REJECTED, label)
                self.assertEqual((h.state, h.pairset, h.text), keep, label)

    def test_the_reason_words_are_fixed_and_carry_no_value(self):
        h = self.holder()
        verdict, why = self.offer(h, "PTPAIR:2:%s:5:1:1-2-0" % LID)
        self.assertEqual(why, "version")
        verdict, why = self.offer(h, "PTPAIR:1:FFFFFFFF:5:1:1-2-0")
        self.assertEqual(why, "list-id")
        for _, t in self.BAD:
            v, w = self.offer(self.holder(), t)
            self.assertNotIn(LID, str(w))


class C_Generation(Base):
    def test_an_equal_generation_is_judged_and_accepted(self):
        h = self.holder()
        verdict, _ = self.offer(h, ONE, received=7, current=7)
        self.assertEqual((verdict, h.generation), (self.RP.ACCEPTED, 7))

    def test_an_older_generation_is_dropped_at_once(self):
        h = self.holder()
        verdict, why = self.offer(h, ONE, received=6, current=7)
        self.assertEqual((verdict, why, h.state, h.generation), (self.RP.REJECTED, "stale-generation", self.RP.UNAVAILABLE, None))

    def test_an_older_generation_does_not_replace_an_accepted_set(self):
        h = self.holder()
        self.offer(h, ONE, received=7, current=7)
        verdict, why = self.offer(h, TWO, received=6, current=7, count=6)
        self.assertEqual((verdict, why, h.text, h.generation), (self.RP.REJECTED, "stale-generation", ONE, 7))

    def test_a_newer_generation_is_never_applied_ahead_and_the_current_one_is_not_moved(self):
        h = self.holder()
        verdict, why = self.offer(h, ONE, received=8, current=7)
        self.assertEqual((verdict, why, h.state, h.generation, h.text), (self.RP.REJECTED, "ahead-generation", self.RP.UNAVAILABLE, None, None))

    def test_a_newer_generation_does_not_touch_an_accepted_current_set(self):
        h = self.holder()
        self.offer(h, ONE, received=7, current=7)
        verdict, why = self.offer(h, TWO, received=8, current=7, count=6)
        self.assertEqual((verdict, h.state, h.text, h.generation), (self.RP.REJECTED, self.RP.READY_NONEMPTY, ONE, 7))

    def test_an_unknown_generation_is_not_a_generation(self):
        h = self.holder()
        verdict, why = h.offer(None, 7, ONE, LID, 5)
        self.assertEqual((verdict, h.state), (self.RP.REJECTED, self.RP.UNAVAILABLE))

    def test_the_binding_of_a_new_generation_replaces_the_old_one_after_the_invalidation(self):
        h = self.holder()
        self.offer(h, ONE, received=7, current=7)
        h.invalidate("epoch")
        self.assertEqual((h.state, h.pairset, h.text, h.generation), (self.RP.UNAVAILABLE, None, None, None))
        verdict, _ = self.offer(h, TWO, received=8, current=8, count=6)
        self.assertEqual((verdict, h.generation, h.text), (self.RP.ACCEPTED, 8, TWO))

    def test_a_changed_station_list_is_a_new_binding_not_a_conflict(self):
        h = self.holder()
        self.offer(h, ONE)
        verdict, _ = self.offer(h, "PTPAIR:1:FFFFFFFF:6:1:1-2-0", list_id="FFFFFFFF", count=6)
        self.assertEqual((verdict, h.state, h.list_id, h.station_count), (self.RP.ACCEPTED, self.RP.READY_NONEMPTY, "FFFFFFFF", 6))


class D_Repeats(Base):
    def test_the_same_text_again_is_idempotent(self):
        h = self.holder()
        self.offer(h, ONE)
        pairset, accepted = h.pairset, h.accepted
        for _ in range(5):
            verdict, why = self.offer(h, ONE)
            self.assertEqual(verdict, self.RP.UNCHANGED)
        self.assertIs(h.pairset, pairset)
        self.assertEqual(h.accepted, accepted)
        self.assertEqual(h.state, self.RP.READY_NONEMPTY)

    def test_the_same_empty_text_again_is_idempotent(self):
        h = self.holder()
        self.offer(h, EMPTY)
        verdict, _ = self.offer(h, EMPTY)
        self.assertEqual((verdict, h.state, h.accepted), (self.RP.UNCHANGED, self.RP.READY_EMPTY, 1))

    def test_a_different_valid_text_of_the_same_binding_is_a_conflict_and_never_overwrites(self):
        h = self.holder()
        self.offer(h, ONE)
        verdict, why = self.offer(h, "PTPAIR:1:%s:5:1:2-3-0" % LID)
        self.assertEqual((verdict, why, h.text), (self.RP.REJECTED, "conflict", ONE))
        self.assertEqual([(p.arrival, p.departure) for p in h.pairset.pairs], [(1, 2)])

    def test_a_conflict_from_empty_to_nonempty_does_not_overwrite_either(self):
        h = self.holder()
        self.offer(h, EMPTY)
        verdict, why = self.offer(h, ONE)
        self.assertEqual((verdict, why, h.state), (self.RP.REJECTED, "conflict", self.RP.READY_EMPTY))

    def test_the_absence_of_the_key_in_one_line_does_not_drop_a_ready_state(self):
        h = self.holder()
        self.offer(h, ONE)
        verdict, why = h.offer(7, 7, None, LID, 5)
        self.assertEqual((verdict, h.state, h.text), (self.RP.UNCHANGED, self.RP.READY_NONEMPTY, ONE))

    def test_an_invalidated_holder_accepts_the_same_text_again_as_a_new_acceptance(self):
        h = self.holder()
        self.offer(h, ONE)
        h.invalidate("epoch")
        verdict, _ = self.offer(h, ONE)
        self.assertEqual((verdict, h.state, h.accepted), (self.RP.ACCEPTED, self.RP.READY_NONEMPTY, 2))


class E_Diagnostics(Base):
    def test_the_last_event_says_version_generations_state_count_and_reason(self):
        h = self.holder()
        self.offer(h, ONE, received=7, current=7)
        ev = h.last_event
        self.assertEqual((ev["ver"], ev["rx"], ev["cur"], ev["state"], ev["pairs"]), (1, 7, 7, self.RP.READY_NONEMPTY, 1))
        self.offer(h, ONE, received=9, current=7)
        ev = h.last_event
        self.assertEqual((ev["rx"], ev["cur"], ev["why"]), (9, 7, "ahead-generation"))

    def test_the_event_contains_only_words_numbers_and_the_one_safe_list_id_form(self):
        """Stage TB-E 1.1 (OD-TE2-R3; was: the event must NOT contain the list id): the list id is part of the diagnostic contract, but ONLY in its safe form (8 hex digits, upper case). Every other value is
        a number, a word of the fixed vocabulary or the 8-hex fingerprint. The full contract is test_pt_tbe_diagnostics."""
        import re
        h = self.holder()
        self.offer(h, ONE)
        flat = dict((k, v) for k, v in h.last_event.items() if k != "summary")
        flat.update(("summary." + k, v) for k, v in h.last_event["summary"].items())
        for k, v in flat.items():
            self.assertTrue(isinstance(v, (int, str)) or v is None, (k, v))
        self.assertEqual(h.last_event["list_id"], LID)
        self.assertEqual(h.last_event["summary"]["list_id"], LID)
        for k, v in flat.items():
            if isinstance(v, str):
                self.assertTrue(re.match(r"\A[0-9A-F]{8}\Z", v) or re.match(r"\A[A-Za-z_-]+\Z", v), (k, v))
        self.assertNotIn(ONE, str(h.last_event))                         # never the payload itself


if __name__ == "__main__":
    unittest.main()
