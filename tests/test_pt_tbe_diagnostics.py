"""Stage TB-E 1.1 (OD-TE2-R3 / OD-TE2-R4): the DIAGNOSTIC CONTRACT of the route pair set intake and the state contract of an invalid / contradicting payload.

Every event (the holder's last_event, and the managed `routepairset` line built from it) carries FIXED WORDS AND NUMBERS ONLY:
  protocol version (ver), received / current generation (rx / cur), the list id and station count of the adopted list (list_id / stations), the declared / received / parsed pair counts of the payload
  (declared / received / parsed), the current state (state), the accepted pair count (pairs), the rejection reason (why), whether the existing state was kept (preserved = true / false) and a SAFE summary
  of the payload (summary: len, ver, list_id, stations, declared, received, parsed, fp; flat in the line as p_*). The raw payload, a control character or an unbounded string never enters an event.
The state contract: not yet accepted + invalid = UNAVAILABLE; accepted + the same content = idempotent; accepted + invalid or contradicting = the first accepted state is kept; a changed generation = the old
sets are void; an invalid payload never clears an accepted state and a later value never overwrites it."""
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbe-diag-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


LID = "A1B2C3D4"
EMPTY = "PTPAIR:1:%s:5:0:" % LID
ONE = "PTPAIR:1:%s:5:1:1-2-0" % LID
CONFLICT = "PTPAIR:1:%s:5:1:2-3-0" % LID
BAD_COUNT = "PTPAIR:1:%s:5:2:1-2-0" % LID                    # declares 2, carries 1
HEX8 = re.compile(r"\A[0-9A-F]{8}\Z")
TOP_KEYS = {"ver", "rx", "cur", "list_id", "stations", "declared", "received", "parsed", "state", "pairs", "why", "preserved", "summary"}
SUMMARY_KEYS = {"len", "ver", "list_id", "stations", "declared", "received", "parsed", "fp"}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import route_pairset
        cls.RP = route_pairset

    def holder(self):
        return self.RP.RoutePairSetHolder()

    def offer(self, h, text, received=7, current=7, list_id=LID, count=5):
        return h.offer(received, current, text, list_id, count)

    def words(self):
        """The fixed vocabulary every str field of an event is taken from."""
        RP = self.RP
        return {RP.UNAVAILABLE, RP.READY_EMPTY, RP.READY_NONEMPTY, RP.PRESERVED, RP.NOT_PRESERVED, RP.NO_ID,
                RP.R_ABSENT, RP.R_SAME, RP.R_STALE_GENERATION, RP.R_AHEAD_GENERATION, RP.R_UNKNOWN_GENERATION, RP.R_NO_LIST, RP.R_LIST_ID, RP.R_CONFLICT}

    def assert_safe(self, event):
        """Every value of the event is an int, a vocabulary word, an 8-hex id / fingerprint, or one of the contract's reason words (lower case letters and '-')."""
        flat = dict((k, v) for k, v in event.items() if k != "summary")
        flat.update(("p_" + k, v) for k, v in event["summary"].items())
        for k, v in flat.items():
            if v is None or (isinstance(v, int) and not isinstance(v, bool)):
                continue
            self.assertIsInstance(v, str, (k, v))
            self.assertLessEqual(len(v), 24, (k, v))
            self.assertTrue(v in self.words() or HEX8.match(v) or re.match(r"\A[a-z][a-z-]*\Z", v), (k, v))


class A_TheEventFields(Base):
    def test_an_accepted_payload_event_has_exactly_the_contract_fields(self):
        h = self.holder()
        self.offer(h, ONE)
        ev = h.last_event
        self.assertEqual(set(ev), TOP_KEYS)
        self.assertEqual(set(ev["summary"]), SUMMARY_KEYS)
        self.assertEqual((ev["ver"], ev["rx"], ev["cur"], ev["list_id"], ev["stations"]), (1, 7, 7, LID, 5))
        self.assertEqual((ev["declared"], ev["received"], ev["parsed"], ev["state"], ev["pairs"], ev["why"]), (1, 1, 1, self.RP.READY_NONEMPTY, 1, self.RP.READY_NONEMPTY))

    def test_the_summary_states_the_payload_length_version_list_id_counts_and_a_fingerprint(self):
        h = self.holder()
        self.offer(h, ONE)
        s = h.last_event["summary"]
        self.assertEqual((s["len"], s["ver"], s["list_id"], s["stations"], s["declared"], s["received"], s["parsed"]), (len(ONE), 1, LID, 5, 1, 1, 1))
        self.assertRegex(s["fp"], HEX8)

    def test_an_invalid_payload_of_an_unaccepted_holder_keeps_unavailable_and_says_not_preserved(self):
        h = self.holder()
        verdict, why = self.offer(h, BAD_COUNT)
        ev = h.last_event
        self.assertEqual((verdict, why, ev["state"], ev["pairs"], ev["preserved"]), (self.RP.REJECTED, "count-mismatch", self.RP.UNAVAILABLE, 0, "false"))
        self.assertEqual((ev["list_id"], ev["stations"], ev["declared"], ev["received"], ev["parsed"]), (LID, 5, 2, 1, 1))
        self.assertEqual((ev["summary"]["declared"], ev["summary"]["received"], ev["summary"]["parsed"], ev["summary"]["len"]), (2, 1, 1, len(BAD_COUNT)))

    def test_the_declared_and_the_parsed_pair_counts_differ_when_an_entry_is_malformed(self):
        h = self.holder()
        self.offer(h, "PTPAIR:1:%s:5:2:1-2-0;3-x-0" % LID)
        ev = h.last_event
        self.assertEqual((ev["declared"], ev["received"], ev["parsed"]), (2, 2, 1))

    def test_an_invalid_payload_after_an_accepted_one_keeps_the_state_and_says_preserved(self):
        h = self.holder()
        self.offer(h, ONE)
        verdict, why = self.offer(h, BAD_COUNT)
        ev = h.last_event
        self.assertEqual((verdict, why, ev["state"], ev["pairs"], ev["preserved"]), (self.RP.REJECTED, "count-mismatch", self.RP.READY_NONEMPTY, 1, "true"))
        self.assertEqual((h.text, h.state), (ONE, self.RP.READY_NONEMPTY))

    def test_a_contradicting_payload_of_the_same_generation_keeps_the_first_and_says_preserved(self):
        h = self.holder()
        self.offer(h, ONE)
        verdict, why = self.offer(h, CONFLICT)
        ev = h.last_event
        self.assertEqual((verdict, why, ev["preserved"], ev["pairs"]), (self.RP.REJECTED, "conflict", "true", 1))
        self.assertEqual(h.text, ONE)

    def test_the_very_same_payload_again_is_idempotent_and_says_preserved(self):
        h = self.holder()
        self.offer(h, ONE)
        accepted = h.accepted
        verdict, why = self.offer(h, ONE)
        self.assertEqual((verdict, why, h.accepted, h.last_event["preserved"]), (self.RP.UNCHANGED, "same", accepted, "true"))

    def test_a_stale_and_an_ahead_generation_state_both_generations_and_keep_the_state(self):
        h = self.holder()
        self.offer(h, ONE)
        self.offer(h, ONE, received=5, current=7)
        ev = h.last_event
        self.assertEqual((ev["rx"], ev["cur"], ev["why"], ev["preserved"]), (5, 7, "stale-generation", "true"))
        self.offer(h, ONE, received=9, current=7)
        ev = h.last_event
        self.assertEqual((ev["rx"], ev["cur"], ev["why"], ev["preserved"]), (9, 7, "ahead-generation", "true"))

    def test_a_missing_generation_is_said_as_none_and_the_state_is_unavailable(self):
        h = self.holder()
        verdict, why = h.offer(None, 7, ONE, LID, 5)
        ev = h.last_event
        self.assertEqual((verdict, why, ev["rx"], ev["cur"], ev["preserved"]), (self.RP.REJECTED, "unknown-generation", None, 7, "false"))

    def test_a_list_id_that_is_not_the_one_of_the_adopted_list_is_said_with_both_ids(self):
        h = self.holder()
        verdict, why = self.offer(h, "PTPAIR:1:DEADBEEF:5:0:")
        ev = h.last_event
        self.assertEqual((verdict, why, ev["list_id"], ev["summary"]["list_id"]), (self.RP.REJECTED, "list-id", LID, "DEADBEEF"))

    def test_an_invalidation_says_that_nothing_was_preserved(self):
        h = self.holder()
        self.offer(h, ONE)
        h.invalidate("scenario-change")
        ev = h.last_event
        self.assertEqual((ev["state"], ev["pairs"], ev["why"], ev["preserved"]), (self.RP.UNAVAILABLE, 0, "scenario-change", "false"))
        self.assertEqual(set(ev), TOP_KEYS)

    def test_a_line_without_the_key_is_an_event_that_keeps_the_state(self):
        h = self.holder()
        self.offer(h, ONE)
        h.offer(7, 7, None, LID, 5)
        ev = h.last_event
        self.assertEqual((ev["why"], ev["preserved"], ev["state"]), ("absent", "true", self.RP.READY_NONEMPTY))
        self.assertEqual(ev["summary"]["len"], -1)

    def test_every_event_of_every_kind_passes_the_safe_value_check(self):
        h = self.holder()
        for text in (None, EMPTY, ONE, BAD_COUNT, CONFLICT, "PTPAIR:1:DEADBEEF:5:0:", "junk", ""):
            self.offer(h, text)
            self.assert_safe(h.last_event)
        h.invalidate("epoch-reset")
        self.assert_safe(h.last_event)


class B_TheSummaryIsSafe(Base):
    def test_a_huge_payload_with_control_characters_and_names_never_reaches_the_event(self):
        h = self.holder()
        raw = "PTPAIR:1:%s:5:1:" % LID + ("1-2-0;" * 20000) + "\r\n\x00\x1b[31m東京駅,STATNAME:SECRET" * 50
        started = time.time()
        verdict, why = self.offer(h, raw)
        self.assertLess(time.time() - started, 2.0)
        ev = h.last_event
        self.assertEqual(verdict, self.RP.REJECTED)
        self.assert_safe(ev)
        text = repr(ev)
        self.assertLess(len(text), 700)
        for needle in ("SECRET", "\\x00", "\\x1b", "1-2-0;1-2-0", "東"):
            self.assertNotIn(needle, text)
        self.assertLessEqual(ev["received"], self.RP.ENTRY_LIMIT)
        self.assertLessEqual(ev["summary"]["len"], 10 ** self.RP.DIGIT_LIMIT)

    def test_a_list_id_that_is_not_eight_hex_digits_is_never_copied(self):
        h = self.holder()
        for bad in ("A1B2C3D4\r\nINJECT", "zzzzzzzz", "A1B2C3D", "A1B2C3D4E", "東京駅名", ""):
            self.offer(h, "PTPAIR:1:%s:5:0:" % bad)
            ev = h.last_event
            self.assertEqual(ev["summary"]["list_id"], self.RP.NO_ID, bad)
            self.assertNotIn("INJECT", repr(ev))
            self.assert_safe(ev)

    def test_an_adopted_list_id_that_is_not_safe_is_never_copied(self):
        h = self.holder()
        h.offer(7, 7, ONE, "A1B2\r\nC3D4", 5)
        self.assertEqual(h.last_event["list_id"], self.RP.NO_ID)
        self.assert_safe(h.last_event)

    def test_numbers_of_the_payload_are_bounded_digits_only(self):
        h = self.holder()
        self.offer(h, "PTPAIR:1:%s:%s:%s:" % (LID, "9" * 40, "-5"))
        ev = h.last_event
        self.assertEqual((ev["summary"]["stations"], ev["summary"]["declared"]), (-1, -1))
        self.assert_safe(ev)

    def test_a_payload_that_is_no_string_is_summarised_without_error(self):
        for value in (b"PTPAIR:1", 12345, 3.5, ["PTPAIR"], object()):
            s = self.RP.summarize(value)
            self.assertEqual(set(s), SUMMARY_KEYS)
            self.assertEqual((s["len"], s["fp"]), (-1, self.RP.NO_ID))

    def test_the_fingerprint_is_short_deterministic_and_tells_two_payloads_apart(self):
        a, b = self.RP.fingerprint(ONE), self.RP.fingerprint(CONFLICT)
        self.assertRegex(a, HEX8)
        self.assertEqual(a, self.RP.fingerprint(ONE))
        self.assertNotEqual(a, b)
        self.assertNotIn(ONE, a)

    def test_the_summary_of_junk_has_no_list_id_and_no_counts(self):
        s = self.RP.summarize("\x00\x01 not a key")
        self.assertEqual((s["list_id"], s["ver"], s["stations"], s["declared"], s["received"], s["parsed"]), (self.RP.NO_ID, -1, -1, -1, -1, -1))
        self.assertGreaterEqual(s["len"], 0)


class C_TheManagedLine(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbe-diag"])
        import main
        import route_pairset
        import sia_managed_rig
        cls.main, cls.RP, cls.MR = main, route_pairset, sia_managed_rig

    def setUp(self):
        self.r = self.MR.ManagedRig(self.main)
        self.addCleanup(self.r.close)
        self.o = self.r.o

    def key(self, count=3, pairs=0, entries="", lid=None):
        lid = lid or self.MR.station_index_contract.list_id(self.MR.STALIST.split(":", 1)[1])
        return "PTPAIR:1:%s:%d:%d:%s" % (lid, count, pairs, entries)

    def last(self):
        events = self.r.events("routepairset")
        self.assertTrue(events, "no routepairset event")
        return events[-1]

    def fields(self, line):
        return dict(re.findall(r"(\w+)=(\S*)", line))

    def test_the_line_of_an_accepted_payload_has_every_contract_field(self):
        self.r.go_active(PTPAIR=self.key())
        f = self.fields(self.last())
        for k in ("ver", "rx", "cur", "list_id", "stations", "declared", "received", "parsed", "state", "pairs", "why", "preserved", "p_len", "p_ver", "p_list_id", "p_stations", "p_fp"):
            self.assertIn(k, f, k)
        self.assertEqual((f["ver"], f["state"], f["pairs"], f["declared"], f["parsed"], f["stations"], f["preserved"]), ("1", "READY_EMPTY", "0", "0", "0", "3", "false"))

    def test_the_line_of_an_invalid_payload_has_the_rejection_the_state_and_the_safe_summary(self):
        bad = self.key(count=3, pairs=2, entries="1-2-0")
        self.r.go_active(PTPAIR=bad)
        line = self.last()
        f = self.fields(line)
        self.assertEqual((f["state"], f["why"], f["pairs"], f["preserved"], f["declared"], f["received"], f["parsed"], f["p_len"]), ("UNAVAILABLE", "count-mismatch", "0", "false", "2", "1", "1", str(len(bad))))
        self.assertRegex(f["p_fp"], HEX8)
        self.assertNotIn(bad, line)
        self.assertNotIn("1-2-0", line)

    def test_an_invalid_payload_after_an_accepted_one_is_said_preserved_and_the_machine_keeps_its_set(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key())
        accepted = self.RP.holder_of(o).accepted
        r.send(self.MR.tele(1, PTPAIR=self.key(count=3, pairs=5, entries="")))
        f = self.fields(self.last())
        self.assertEqual((f["state"], f["why"], f["preserved"]), ("READY_EMPTY", "count-mismatch", "true"))
        self.assertEqual((self.RP.state_of(o), self.RP.holder_of(o).accepted), (self.RP.READY_EMPTY, accepted))

    def test_the_same_invalid_payload_repeated_is_one_line_and_a_different_one_is_another_line(self):
        r = self.r
        r.go_active(PTPAIR=self.key(count=3, pairs=2, entries="1-2-0"))
        n = len(r.events("routepairset"))
        r.send(self.MR.tele(1, PTPAIR=self.key(count=3, pairs=2, entries="1-2-0")))
        self.assertEqual(len(r.events("routepairset")), n)                                   # the same payload, the same reason: no flood
        r.send(self.MR.tele(1, PTPAIR=self.key(count=3, pairs=4, entries="1-2-0")))
        self.assertEqual(len(r.events("routepairset")), n + 1)                               # another payload with the same reason: said again
        self.assertEqual(self.fields(self.last())["declared"], "4")

    def test_a_line_with_a_hostile_payload_never_carries_it(self):
        hostile = "PTPAIR:1:A1B2C3D4\r\nSECRET:5:0:" + "X" * 5000
        self.r.go_active(PTPAIR=hostile)
        for line in self.r.events("routepairset"):
            self.assertNotIn("SECRET", line)
            self.assertNotIn("XXXX", line)
            self.assertLess(len(line), 600)


class D_TheStateContract(Base):
    """OD-TE2-R4, one row per case."""

    def test_not_yet_accepted_plus_invalid_keeps_unavailable(self):
        h = self.holder()
        self.offer(h, BAD_COUNT)
        self.assertEqual((h.state, h.pairset, h.text, h.accepted), (self.RP.UNAVAILABLE, None, None, 0))

    def test_accepted_plus_the_same_content_is_idempotent(self):
        h = self.holder()
        self.offer(h, ONE)
        pairset = h.pairset
        self.offer(h, ONE)
        self.assertIs(h.pairset, pairset)
        self.assertEqual(h.accepted, 1)

    def test_accepted_plus_invalid_keeps_the_first_state(self):
        h = self.holder()
        self.offer(h, ONE)
        for bad in (BAD_COUNT, "junk", "PTPAIR:1:%s:6:0:" % LID, "PTPAIR:1:DEADBEEF:5:0:", "PTPAIR:2:%s:5:0:" % LID):
            self.offer(h, bad)
            self.assertEqual((h.state, h.text), (self.RP.READY_NONEMPTY, ONE), bad)

    def test_accepted_plus_the_same_generation_and_other_content_keeps_the_first_state(self):
        h = self.holder()
        self.offer(h, ONE)
        self.offer(h, CONFLICT)
        self.offer(h, EMPTY)
        self.assertEqual((h.state, h.text, h.accepted), (self.RP.READY_NONEMPTY, ONE, 1))

    def test_a_changed_generation_voids_the_old_state_and_waits_for_the_new_supply(self):
        h = self.holder()
        self.offer(h, ONE)
        h.invalidate("scenario-change")
        self.assertEqual((h.state, h.pairset, h.text, h.generation), (self.RP.UNAVAILABLE, None, None, None))
        verdict, _ = self.offer(h, CONFLICT, received=8, current=8)
        self.assertEqual((verdict, h.text), (self.RP.ACCEPTED, CONFLICT))

    def test_an_invalid_payload_never_clears_an_accepted_state_and_a_later_value_never_overwrites_it(self):
        h = self.holder()
        self.offer(h, EMPTY)
        self.offer(h, "garbage")
        self.offer(h, ONE)
        self.assertEqual((h.state, h.text), (self.RP.READY_EMPTY, EMPTY))


if __name__ == "__main__":
    unittest.main()
