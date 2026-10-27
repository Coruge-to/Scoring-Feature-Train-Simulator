"""Phase SI-R2.2-S2a (C2a): the pure receiving contract of the OFFTGT part (official_target_contract.py).

Pure: no Qt, no Overlay, no clock. Every row runs under Gate A (`python -I`). The connection to the Overlay (defaults, intake points, ABSENT compatibility, generation /
scenario boundaries) is tested by test_official_target_supply_s2a.py with the C2b change set.

The wire encoder is the fixture's section A (tests/official_target_wire_fixture.py); this module is the DECODER. The two are tied together here: the section-A constants must be the
module's constants, and every sender-canonical step of the meaning vectors must be read back as the state the vector expects.
"""
import ast
import hashlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import official_target_contract as C  # noqa: E402
import official_target_wire_fixture as F  # noqa: E402

WIRE_CORPUS_SHA256 = "081E3D72B031532728A19211B3713751F77C614858562994EEE144D0AE9A3E1A"     # the wire text of every official step of the meaning vectors (list_id ABCD1234)
LIST_ID = "ABCD1234"
FORBIDDEN = ("bve5", "bve6", "bve_version", "host_version", "landing", "touchdown", "terminaldeparturetime")


class SList(list):
    """The adopted station list as the Overlay holds it: a list of station dicts that carries its list_id."""

    def __init__(self, items=(), list_id=None):
        super().__init__(items)
        self.list_id = list_id


def stations(*locations):
    return SList([{"location": float(x)} for x in locations], LIST_ID)


L5 = stations(0, 1000, 2000, 3000, 4000)
EMPTY = SList([], "00000000")


def judge(raw, station_list=L5, elapsed=0):
    result, scope_ok = C.evaluate(raw, station_list, getattr(station_list, "list_id", None), elapsed)
    return result, scope_ok


def state_reason(raw, station_list=L5, elapsed=0):
    result, _ok = judge(raw, station_list, elapsed)
    return result["official_state"], result["official_reason"]


class FixtureAndModuleAgree(unittest.TestCase):
    """Section A of the fixture is the documented wire; the module must be the same wire."""

    def test_the_fixture_wire_is_final(self):
        self.assertIs(F.PROVISIONAL, False)

    def test_the_wire_constants_are_the_same(self):
        self.assertEqual(F.PART_NAME, C.PART_NAME)
        self.assertEqual(F.WIRE_VERSION, C.WIRE_VERSION)
        self.assertEqual(F.STATE_WORDS, C.STATE_WORDS)
        self.assertEqual(F.WIRE_TO_STATE, C.WIRE_TO_STATE)
        self.assertEqual(tuple(F.NONE_CLASS), C.NONE_CLASS)
        self.assertEqual(F.LOC_TOLERANCE_M, C.LOC_TOLERANCE_M)
        self.assertEqual(F.LIST_GRACE_MS, C.LIST_GRACE_MS)
        self.assertEqual(len(F.FIELD_ORDER) + 2, C.FIELD_COUNT)

    def test_the_published_attributes_are_the_fixture_attributes(self):
        self.assertEqual(set(C.initial_state()), set(F.OFFICIAL_ATTRS.values()))

    def test_every_state_is_a_python_state_and_every_reason_a_fixture_verdict(self):
        for state in set(C.WIRE_TO_STATE.values()) | {C.ABSENT, C.INVALID, C.NOT_INITIALIZED}:
            self.assertIn(state, F.PY_STATES)
        reasons = {C.R_OK, C.R_NONE_TERMINAL, C.R_NONE_EMPTY, C.R_UNAVAILABLE, C.R_READ_FAILED, C.R_MISSING, C.R_VERSION, C.R_MALFORMED, C.R_RANGE, C.R_MISMATCH, C.R_NOT_READY, C.R_LOC}
        self.assertTrue(reasons <= set(F.PY_VERDICTS), sorted(reasons - set(F.PY_VERDICTS)))

    def test_the_vector_wire_corpus_is_the_one_fixed_by_the_stage_0_audit(self):
        vec = F.load_vectors()
        lines = []
        for case in vec["cases"]:
            cur = case["list"]
            for i, step in enumerate(case["steps"]):
                cur = step.get("list", cur)
                off = step.get("official")
                if off is None:
                    continue
                sl = [] if cur == "EMPTY" else vec["lists"][cur]
                try:
                    part = F.build_part(off, LIST_ID, len(sl), sl)
                except Exception as exc:
                    part = "EXC:" + type(exc).__name__
                lines.append("%s#%d\t%s" % (case["id"], i, part))
        self.assertEqual(hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest().upper(), WIRE_CORPUS_SHA256)


class SenderCanonical(unittest.TestCase):
    """The five states of the wire, spelled the way the sender spells them (fixture build_part)."""

    def test_k_is_known_and_publishes_the_adopted_list_location(self):
        raw = F.build_part({"state": "K", "index": 2}, LIST_ID, 5, L5)
        self.assertEqual(raw, "OFFTGT:1:K:2:5:ABCD1234:2000:5:5")
        result, ok = judge(raw)
        self.assertTrue(ok)
        self.assertEqual(result, {"official_state": "KNOWN", "official_index": 2, "official_location": 2000.0, "official_margin_b": 5.0, "official_margin_f": 5.0, "official_reason": "off-ok"})

    def test_the_published_location_is_the_listed_one_not_the_wire_one(self):
        result, _ = judge("OFFTGT:1:K:2:5:ABCD1234:2000.009:5:5")
        self.assertEqual(result["official_location"], 2000.0)

    def test_t_n_u_f(self):
        self.assertEqual(state_reason("OFFTGT:1:T:-1:5:ABCD1234:-1:-1:-1"), ("NONE_TERMINAL", "off-none-terminal"))
        self.assertEqual(state_reason("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", EMPTY), ("NONE_EMPTY", "off-none-empty"))
        self.assertEqual(state_reason("OFFTGT:1:U:-1:-1:00000000:-1:-1:-1"), ("UNAVAILABLE", "off-unavailable"))
        self.assertEqual(state_reason("OFFTGT:1:F:-1:-1:00000000:-1:-1:-1"), ("READ_FAILED", "off-read-failed"))

    def test_non_k_states_publish_only_the_sentinel(self):
        for raw, sl in (("OFFTGT:1:T:-1:5:ABCD1234:-1:-1:-1", L5), ("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", EMPTY), ("OFFTGT:1:U:-1:-1:00000000:-1:-1:-1", L5), ("OFFTGT:1:F:-1:-1:00000000:-1:-1:-1", L5)):
            result, _ = judge(raw, sl)
            self.assertEqual((result["official_index"], result["official_location"], result["official_margin_b"], result["official_margin_f"]), (-1, -1.0, -1.0, -1.0), raw)

    def test_u_and_f_accept_a_listed_count_and_hash_as_syntax_only(self):
        self.assertEqual(state_reason("OFFTGT:1:U:-1:5:ABCD1234:-1:-1:-1"), ("UNAVAILABLE", "off-unavailable"))
        self.assertEqual(state_reason("OFFTGT:1:F:-1:5:ABCD1234:-1:-1:-1"), ("READ_FAILED", "off-read-failed"))
        self.assertEqual(state_reason("OFFTGT:1:U:-1:7:DEADBEEF:-1:-1:-1"), ("UNAVAILABLE", "off-unavailable"))
        self.assertEqual(state_reason("OFFTGT:1:U:-1:7:DEADBEEF:-1:-1:-1", EMPTY), ("UNAVAILABLE", "off-unavailable"))

    def test_the_five_states_are_five_different_states_and_none_is_not_a_wire_word(self):
        states = [state_reason(raw, sl)[0] for raw, sl in (
            ("OFFTGT:1:K:2:5:ABCD1234:2000:5:5", L5), ("OFFTGT:1:T:-1:5:ABCD1234:-1:-1:-1", L5), ("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", EMPTY),
            ("OFFTGT:1:U:-1:-1:00000000:-1:-1:-1", L5), ("OFFTGT:1:F:-1:-1:00000000:-1:-1:-1", L5))]
        self.assertEqual(len(set(states)), 5)
        self.assertNotIn("NONE", C.STATE_WORDS)
        self.assertEqual(state_reason("OFFTGT:1:NONE:-1:5:ABCD1234:-1:-1:-1"), ("INVALID", "off-malformed"))

    def test_the_none_class_is_t_or_n_only(self):
        self.assertEqual({s for s in set(C.WIRE_TO_STATE.values()) | {C.ABSENT, C.INVALID, C.NOT_INITIALIZED} if C.is_none_class(s)}, {"NONE_TERMINAL", "NONE_EMPTY"})

    def test_hash_case_is_not_significant(self):
        self.assertEqual(state_reason("OFFTGT:1:K:2:5:abcd1234:2000:5:5"), ("KNOWN", "off-ok"))

    def test_a_negative_listed_location_is_a_normal_location(self):
        sl = SList([{"location": -50.0}], LIST_ID)
        result, _ = judge("OFFTGT:1:K:0:1:ABCD1234:-50:0:0", sl)
        self.assertEqual((result["official_state"], result["official_location"]), ("KNOWN", -50.0))
        self.assertEqual(state_reason("OFFTGT:1:K:0:1:ABCD1234:-49.5:0:0", sl), ("INVALID", "off-loc"))

    def test_the_k_location_agrees_within_a_hundredth_of_a_metre(self):
        self.assertEqual(state_reason("OFFTGT:1:K:2:5:ABCD1234:2000.009:5:5"), ("KNOWN", "off-ok"))
        self.assertEqual(state_reason("OFFTGT:1:K:2:5:ABCD1234:1999.991:5:5"), ("KNOWN", "off-ok"))
        self.assertEqual(state_reason("OFFTGT:1:K:2:5:ABCD1234:2000.011:5:5"), ("INVALID", "off-loc"))
        self.assertEqual(state_reason("OFFTGT:1:K:2:5:ABCD1234:1500:5:5"), ("INVALID", "off-loc"))


class CheckOrder(unittest.TestCase):
    """version -> arity -> state word -> number syntax -> range / sentinel -> scope -> loc: the first failure decides."""

    CASES = [
        # (name, raw, expected state, expected reason)
        ("part is only the name", "OFFTGT", "INVALID", "off-malformed"),
        ("empty part body", "OFFTGT:", "INVALID", "off-malformed"),
        ("version 0", "OFFTGT:0:K:2:5:ABCD1234:2000:5:5", "INVALID", "off-version"),
        ("version 2", "OFFTGT:2:K:2:5:ABCD1234:2000:5:5", "INVALID", "off-version"),
        ("version -1", "OFFTGT:-1:K:2:5:ABCD1234:2000:5:5", "INVALID", "off-version"),
        ("version 2 wins over arity", "OFFTGT:2:K", "INVALID", "off-version"),
        ("version 2 wins over a bad state word", "OFFTGT:2:Z:1:1:1:1:1:1", "INVALID", "off-version"),
        ("version 01", "OFFTGT:01:K:2:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("version x", "OFFTGT:x:K:2:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("version empty", "OFFTGT::K:2:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("version + 1", "OFFTGT:+1:K:2:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("8 fields", "OFFTGT:1:K:2:5:ABCD1234:2000:5", "INVALID", "off-malformed"),
        ("10 fields", "OFFTGT:1:K:2:5:ABCD1234:2000:5:5:9", "INVALID", "off-malformed"),
        ("arity wins over a bad state word", "OFFTGT:1:Z:2", "INVALID", "off-malformed"),
        ("state Z", "OFFTGT:1:Z:-1:5:ABCD1234:-1:-1:-1", "INVALID", "off-malformed"),
        ("state NONE", "OFFTGT:1:NONE:-1:5:ABCD1234:-1:-1:-1", "INVALID", "off-malformed"),
        ("state lower case", "OFFTGT:1:k:2:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("state empty", "OFFTGT:1::2:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("idx x", "OFFTGT:1:K:x:5:ABCD1234:2000:5:5", "INVALID", "off-malformed"),
        ("loc abc", "OFFTGT:1:K:2:5:ABCD1234:abc:5:5", "INVALID", "off-malformed"),
        ("hash too short", "OFFTGT:1:K:2:5:ABCD12:2000:5:5", "INVALID", "off-malformed"),
        ("hash too long", "OFFTGT:1:K:2:5:ABCD12345:2000:5:5", "INVALID", "off-malformed"),
        ("hash not hex", "OFFTGT:1:K:2:5:ABCDEFGH:2000:5:5", "INVALID", "off-malformed"),
        ("hash trailing newline", "OFFTGT:1:K:2:5:ABCD1234\n:2000:5:5", "INVALID", "off-malformed"),
        ("syntax wins over range", "OFFTGT:1:K:-1:5:ABCD1234:abc:5:5", "INVALID", "off-malformed"),
        ("K idx -1", "OFFTGT:1:K:-1:5:ABCD1234:2000:5:5", "INVALID", "off-range"),
        ("K idx = count", "OFFTGT:1:K:5:5:ABCD1234:4000:5:5", "INVALID", "off-range"),
        ("K idx > count", "OFFTGT:1:K:12:5:ABCD1234:2000:5:5", "INVALID", "off-range"),
        ("K negative back margin", "OFFTGT:1:K:2:5:ABCD1234:2000:-1:5", "INVALID", "off-range"),
        ("K negative front margin", "OFFTGT:1:K:2:5:ABCD1234:2000:5:-0.5", "INVALID", "off-range"),
        ("T with an idx", "OFFTGT:1:T:0:5:ABCD1234:-1:-1:-1", "INVALID", "off-range"),
        ("T with count 0", "OFFTGT:1:T:-1:0:00000000:-1:-1:-1", "INVALID", "off-range"),
        ("N with count 5", "OFFTGT:1:N:-1:5:ABCD1234:-1:-1:-1", "INVALID", "off-range"),
        ("N with an idx", "OFFTGT:1:N:2:0:00000000:-1:-1:-1", "INVALID", "off-range"),
        ("U with an idx", "OFFTGT:1:U:1:5:ABCD1234:-1:-1:-1", "INVALID", "off-range"),
        ("F with an idx", "OFFTGT:1:F:3:5:ABCD1234:-1:-1:-1", "INVALID", "off-range"),
        ("U that resends the last K location", "OFFTGT:1:U:-1:5:ABCD1234:2000:-1:-1", "INVALID", "off-range"),
        ("U that resends the last K margin", "OFFTGT:1:U:-1:5:ABCD1234:-1:5:5", "INVALID", "off-range"),
        ("T with a location", "OFFTGT:1:T:-1:5:ABCD1234:4000:-1:-1", "INVALID", "off-range"),
        ("range wins over scope", "OFFTGT:1:K:9:5:DEADBEEF:2000:5:5", "INVALID", "off-range"),
    ]

    def test_every_case(self):
        for name, raw, state, reason in self.CASES:
            for elapsed in (0, 3100):
                with self.subTest(name=name, elapsed=elapsed):
                    self.assertEqual(state_reason(raw, L5, elapsed), (state, reason))

    def test_a_failing_part_publishes_the_sentinel_and_never_a_station(self):
        for name, raw, state, reason in self.CASES:
            result, _ = judge(raw)
            self.assertEqual((result["official_index"], result["official_location"], result["official_margin_b"], result["official_margin_f"]), (-1, -1.0, -1.0, -1.0), name)


class CanonicalNumbers(unittest.TestCase):
    """One value, one spelling: a spelling the sender never produces is malformed (the receiver does not 'repair' it)."""

    NON_ASCII_DIGITS = [chr(0x0665), chr(0xFF15)]      # an Arabic-Indic five and a full-width five: digits to str.isdigit, not to the wire
    REJECTED = ["01", "007", "+1", "+2", "-0", "-00", "1e3", "1E3", "2e0", "NaN", "nan", "Infinity", "-Infinity", "inf", " 5", "5 ", "5\n", "0x10", "5_0", "1,5", "", "-", "--1",
                "2147483648", "-2147483649", "99999999999"] + NON_ASCII_DIGITS

    def test_an_index_is_canonical_int32_text(self):
        for token in self.REJECTED + ["2.0", "2.", ".5"]:
            with self.subTest(token=token):
                self.assertEqual(state_reason("OFFTGT:1:K:%s:5:ABCD1234:2000:5:5" % token), ("INVALID", "off-malformed"))

    def test_a_count_is_canonical_int32_text(self):
        for token in self.REJECTED:
            with self.subTest(token=token):
                self.assertEqual(state_reason("OFFTGT:1:K:2:%s:ABCD1234:2000:5:5" % token), ("INVALID", "off-malformed"))

    def test_a_real_is_canonical_decimal_text(self):
        bad = ["01", "00.5", "+1", "-0", "-0.0", "0.0", "2000.0", "5.50", "1e3", "1.5e-3", "NaN", "Infinity", "-Infinity", " 5", "5 ", "5\n", ".5", "5.", "", "-", "1,5", chr(0x0665),
               "1" * 16, "1." + "1" * 18]
        for token in bad:
            for position, template in (("loc", "OFFTGT:1:K:2:5:ABCD1234:%s:5:5"), ("mb", "OFFTGT:1:K:2:5:ABCD1234:2000:%s:5"), ("mf", "OFFTGT:1:K:2:5:ABCD1234:2000:5:%s")):
                with self.subTest(token=token, position=position):
                    self.assertEqual(state_reason(template % token), ("INVALID", "off-malformed"))

    def test_the_sentinel_spelling_is_minus_one_only(self):
        for token in ("-1.0", "-01", "-1e0", "-1.00"):
            self.assertEqual(state_reason("OFFTGT:1:T:%s:5:ABCD1234:-1:-1:-1" % token), ("INVALID", "off-malformed"), token)
            self.assertEqual(state_reason("OFFTGT:1:T:-1:5:ABCD1234:%s:-1:-1" % token), ("INVALID", "off-malformed"), token)

    def test_canonical_spellings_are_read(self):
        for loc in ("0", "2000", "1999.99", "2000.01", "2000.009", "570.04", "0.5", "-0.5", "-50", "123456789012345", "0.00000000000000001"):
            wire = C.decode("OFFTGT:1:K:2:5:ABCD1234:%s:0.25:12.5" % loc)
            self.assertIsNotNone(wire[0], loc)
            self.assertEqual(wire[0]["loc"], float(loc))
        self.assertEqual(C.decode("OFFTGT:1:K:2147483647:2147483647:ABCD1234:1:0:0")[0]["idx"], 2147483647)
        self.assertEqual(C.decode("OFFTGT:1:T:-2147483648:5:ABCD1234:-1:-1:-1")[0]["idx"], -2147483648)

    def test_a_negative_location_is_read_for_k_without_being_taken_for_the_sentinel(self):
        sl = SList([{"location": -1.0}, {"location": 100.0}], LIST_ID)
        result, _ = judge("OFFTGT:1:K:0:2:ABCD1234:-1:0:0", sl)
        self.assertEqual((result["official_state"], result["official_index"], result["official_location"]), ("KNOWN", 0, -1.0))


class ScopeAndGrace(unittest.TestCase):
    def test_scope_is_count_and_hash_of_the_adopted_list(self):
        self.assertEqual(state_reason("OFFTGT:1:K:2:5:DEADBEEF:2000:5:5"), ("NOT_INITIALIZED", "off-not-ready"))
        self.assertEqual(state_reason("OFFTGT:1:K:2:6:ABCD1234:2000:5:5"), ("NOT_INITIALIZED", "off-not-ready"))
        self.assertEqual(state_reason("OFFTGT:1:T:-1:4:ABCD1234:-1:-1:-1"), ("NOT_INITIALIZED", "off-not-ready"))
        self.assertEqual(state_reason("OFFTGT:1:T:-1:5:DEADBEEF:-1:-1:-1"), ("NOT_INITIALIZED", "off-not-ready"))

    def test_the_grace_is_three_thousand_milliseconds(self):
        for raw in ("OFFTGT:1:K:2:5:DEADBEEF:2000:5:5", "OFFTGT:1:K:2:6:ABCD1234:2000:5:5", "OFFTGT:1:T:-1:4:ABCD1234:-1:-1:-1"):
            self.assertEqual(state_reason(raw, L5, 0), ("NOT_INITIALIZED", "off-not-ready"))
            self.assertEqual(state_reason(raw, L5, 3000), ("NOT_INITIALIZED", "off-not-ready"))
            self.assertEqual(state_reason(raw, L5, 3001), ("INVALID", "off-list-mismatch"))

    def test_scope_ok_is_false_exactly_while_the_scope_disagrees(self):
        self.assertFalse(judge("OFFTGT:1:K:2:5:DEADBEEF:2000:5:5")[1])
        self.assertFalse(judge("OFFTGT:1:K:2:5:DEADBEEF:2000:5:5", L5, 9999)[1])
        self.assertTrue(judge("OFFTGT:1:K:2:5:ABCD1234:2000:5:5")[1])
        self.assertTrue(judge("OFFTGT:1:U:-1:5:DEADBEEF:-1:-1:-1")[1])
        self.assertTrue(judge("OFFTGT:1:F:-1:5:DEADBEEF:-1:-1:-1")[1])
        self.assertTrue(judge(None)[1])
        self.assertTrue(judge("OFFTGT:1:K:2:5:ABCD1234:abc:5:5")[1])

    def test_u_and_f_have_no_scope(self):
        for word in ("U", "F"):
            self.assertEqual(state_reason("OFFTGT:1:%s:-1:99:DEADBEEF:-1:-1:-1" % word, EMPTY, 9999)[1], "off-unavailable" if word == "U" else "off-read-failed")

    def test_no_adopted_list_is_a_scope_disagreement_for_k_and_t(self):
        none_list = []
        self.assertEqual(C.evaluate("OFFTGT:1:K:2:5:ABCD1234:2000:5:5", none_list, None, 0), (C._result("NOT_INITIALIZED", "off-not-ready"), False))
        self.assertEqual(C.evaluate("OFFTGT:1:K:2:5:ABCD1234:2000:5:5", none_list, None, 3100)[0]["official_reason"], "off-list-mismatch")
        self.assertEqual(C.evaluate("OFFTGT:1:T:-1:5:ABCD1234:-1:-1:-1", none_list, None, 0)[0]["official_state"], "NOT_INITIALIZED")

    def test_n_needs_wire_count_zero_and_an_empty_adopted_list(self):
        self.assertEqual(state_reason("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", EMPTY), ("NONE_EMPTY", "off-none-empty"))
        self.assertEqual(C.evaluate("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", [], None, 0)[0]["official_state"], "NONE_EMPTY")      # an empty list that has no list_id (no STALIST ever came)
        self.assertEqual(state_reason("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", L5), ("NOT_INITIALIZED", "off-not-ready"))
        self.assertEqual(state_reason("OFFTGT:1:N:-1:0:00000000:-1:-1:-1", L5, 3100), ("INVALID", "off-list-mismatch"))
        self.assertEqual(state_reason("OFFTGT:1:N:-1:5:ABCD1234:-1:-1:-1", EMPTY), ("INVALID", "off-range"))                  # count 5 is not an N

    def test_scope_is_not_asked_of_n_by_hash(self):
        self.assertEqual(state_reason("OFFTGT:1:N:-1:0:DEADBEEF:-1:-1:-1", EMPTY), ("NONE_EMPTY", "off-none-empty"))


class Advance(unittest.TestCase):
    """The grace timer folded into one call; the clock is the caller's."""

    BAD = "OFFTGT:1:K:2:5:DEADBEEF:2000:5:5"
    GOOD = "OFFTGT:1:K:2:5:ABCD1234:2000:5:5"

    def test_the_timer_starts_at_the_first_disagreement_and_is_kept(self):
        r1, t1 = C.advance(self.BAD, L5, LIST_ID, None, 10000.0)
        self.assertEqual((r1["official_state"], t1), ("NOT_INITIALIZED", 10000.0))
        r2, t2 = C.advance(self.BAD, L5, LIST_ID, t1, 13000.0)
        self.assertEqual((r2["official_state"], t2), ("NOT_INITIALIZED", 10000.0))
        r3, t3 = C.advance(self.BAD, L5, LIST_ID, t2, 13001.0)
        self.assertEqual((r3["official_state"], r3["official_reason"], t3), ("INVALID", "off-list-mismatch", 10000.0))

    def test_an_agreeing_judgement_discards_the_timer(self):
        _, t = C.advance(self.BAD, L5, LIST_ID, None, 10000.0)
        r, t = C.advance(self.GOOD, L5, LIST_ID, t, 10500.0)
        self.assertEqual((r["official_state"], t), ("KNOWN", None))
        r, t = C.advance(self.BAD, L5, LIST_ID, t, 14000.0)                    # the disagreement counts from here, not from 10000
        self.assertEqual((r["official_state"], t), ("NOT_INITIALIZED", 14000.0))

    def test_a_judgement_without_scope_discards_the_timer(self):
        _, t = C.advance(self.BAD, L5, LIST_ID, None, 10000.0)
        for raw in (None, "OFFTGT:1:U:-1:-1:00000000:-1:-1:-1", "OFFTGT:1:F:-1:-1:00000000:-1:-1:-1", "OFFTGT:1:K:x", "OFFTGT:1:K:-1:5:ABCD1234:2000:5:5"):
            self.assertIsNone(C.advance(raw, L5, LIST_ID, t, 10100.0)[1], raw)

    def test_the_timer_is_dropped_for_another_scenario_only(self):
        self.assertEqual(C.timer_after_scenario(10000.0, 7, 7), 10000.0)
        self.assertIsNone(C.timer_after_scenario(10000.0, 7, 8))
        self.assertIsNone(C.timer_after_scenario(None, 7, 8))
        self.assertIsNone(C.timer_after_scenario(10000.0, None, 7))

    def test_an_internal_error_is_not_initialized_and_the_timer_stays(self):
        r, t = C.advance("OFFTGT:1:K:2:5:ABCD1234:2000:5:5", None, LIST_ID, 5.0, 10.0)
        self.assertEqual(r, C.initial_state())
        self.assertEqual(t, 5.0)
        r, t = C.advance("OFFTGT:1:K:2:5:ABCD1234:2000:5:5", L5, LIST_ID, 5.0, "now")
        self.assertEqual((r, t), (C.initial_state(), 5.0))

    def test_a_sequence_does_not_remember_the_last_known_target(self):
        _, t = C.advance(self.GOOD, L5, LIST_ID, None, 1.0)
        r, _ = C.advance("OFFTGT:1:U:-1:-1:00000000:-1:-1:-1", L5, LIST_ID, t, 2.0)
        self.assertEqual((r["official_state"], r["official_index"], r["official_location"]), ("UNAVAILABLE", -1, -1.0))
        r, _ = C.advance("OFFTGT:1:F:-1:-1:00000000:-1:-1:-1", L5, LIST_ID, t, 3.0)
        self.assertEqual((r["official_state"], r["official_index"]), ("READ_FAILED", -1))
        r, _ = C.advance(None, L5, LIST_ID, t, 4.0)
        self.assertEqual((r["official_state"], r["official_reason"], r["official_index"]), ("ABSENT", "off-missing", -1))
        r, _ = C.advance("OFFTGT:1:K:x", L5, LIST_ID, t, 5.0)
        self.assertEqual((r["official_state"], r["official_index"]), ("INVALID", -1))


class Capture(unittest.TestCase):
    def test_the_first_offtgt_part_is_taken(self):
        parts = "A:1,OFFTGT:1:K:2:5:ABCD1234:2000:5:5,B:2,OFFTGT:1:T:-1:5:ABCD1234:-1:-1:-1".split(",")
        self.assertEqual(C.capture(parts), "OFFTGT:1:K:2:5:ABCD1234:2000:5:5")

    def test_a_line_without_the_part_has_none(self):
        self.assertIsNone(C.capture("A:1,B:2".split(",")))
        self.assertIsNone(C.capture([]))

    def test_the_name_must_match_exactly(self):
        for part in ("OFFTGX:1:K", "offtgt:1:K", "OFFTGT1:1:K", " OFFTGT:1:K", "XOFFTGT:1:K", "OFFTG:1"):
            self.assertIsNone(C.capture([part]), part)

    def test_the_bare_name_is_captured_and_then_refused(self):
        self.assertEqual(C.capture(["OFFTGT"]), "OFFTGT")
        self.assertEqual(state_reason("OFFTGT"), ("INVALID", "off-malformed"))

    def test_a_part_with_no_state_is_captured_and_refused(self):
        self.assertEqual(C.capture(["OFFTGT:"]), "OFFTGT:")
        self.assertEqual(state_reason("OFFTGT:"), ("INVALID", "off-malformed"))


class VectorsRead(unittest.TestCase):
    """Every sender-canonical, non-generation step of the meaning vectors (supply) is read back as the state its expectation names. The Overlay-level rows (generation,
    held replay, HUD) are the C2b tests; this is the pure half of the same vectors."""

    SKIP_KEYS = ("generation", "no_line")

    def test_the_supply_vectors(self):
        vec = F.load_vectors()
        checked = 0
        for case in vec["cases"]:
            if not case["id"].startswith("SUP-"):
                continue
            if any(k in step for step in case["steps"] for k in self.SKIP_KEYS) or any(step.get("expect", {}).get("held") for step in case["steps"]):
                continue
            cur = case["list"]
            since = None
            now = 1000000.0
            for i, step in enumerate(case["steps"]):
                cur = step.get("list", cur)
                sl = SList([] if cur == "EMPTY" else [{"location": s["location"]} for s in vec["lists"][cur]], LIST_ID)
                raw = None
                if step.get("official") is not None:
                    raw = F.build_part(step["official"], LIST_ID, len(sl), vec["lists"][cur] if cur != "EMPTY" else [])
                now += step.get("advance_ms", 0)
                result, since = C.advance(raw, sl, LIST_ID, since, now)
                exp = step.get("expect", {})
                where = "%s#%d" % (case["id"], i)
                if "official_state" in exp:
                    self.assertEqual(result["official_state"], exp["official_state"], where)
                    checked += 1
                if "official_state_in" in exp:
                    self.assertIn(result["official_state"], exp["official_state_in"], where)
                    checked += 1
                if "state_not" in exp:
                    self.assertNotEqual(result["official_state"], exp["state_not"], where)
                if "official_index" in exp:
                    self.assertEqual(result["official_index"], exp["official_index"], where)
                if "official_reason" in exp:
                    self.assertEqual(result["official_reason"], exp["official_reason"], where)
                if "official_location" in exp:
                    self.assertEqual(result["official_location"], exp["official_location"], where)
        self.assertGreaterEqual(checked, 40)


class ModuleBoundary(unittest.TestCase):
    """The module is pure and reads nothing of the application."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "official_target_contract.py"), encoding="utf-8") as fh:
            cls.source = fh.read()
        cls.tree = ast.parse(cls.source)

    def test_it_imports_the_standard_re_module_only(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"re"})

    def test_it_has_no_forbidden_word(self):
        lowered = self.source.lower()
        for word in FORBIDDEN:
            self.assertNotIn(word, lowered)

    def test_it_has_no_fallback_source(self):
        # the contract names what it never reads; these words must not appear in code (the docstring lists them in prose, which is why only identifiers are checked)
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for word in ("bve_next_loc", "bve_next_time", "bve_tgt_idx", "bve_arr_idx", "nextloc", "nexttime", "door", "doordir", "tgt"):
            self.assertNotIn(word, names)

    def test_the_application_side_does_not_read_the_published_values_yet(self):
        # AC-2.3 of SI-R2.2-S2a: the HUD and the scoring never read one of the six published values nor import the module (they are connected in SI-R2.3).
        # (Only the six published names are pinned: scoring_logic.py already has unrelated identifiers that start with official_ for the official jump.)
        for rel in ("hud_ui.py", "scoring_logic.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for name in C.initial_state():
                self.assertNotIn(name, text, rel)
            self.assertNotIn("official_target_contract", text, rel)

    def test_the_module_file_is_ascii(self):
        with open(os.path.join(ROOT, "official_target_contract.py"), "rb") as fh:
            data = fh.read()
        self.assertFalse([b for b in data if b > 127])


if __name__ == "__main__":
    unittest.main()
