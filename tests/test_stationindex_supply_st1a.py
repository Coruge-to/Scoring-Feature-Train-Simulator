"""Phase PID-D4JA StationIndex ST-1A (file S1) - tests of the STIDX SUPPLY: the six contracts that the ST-0 RED file declared for ST-1 (now GREEN here), the pure
Python unit and its observer, and the SOURCE-SHAPE pins that keep ST-1A what it is: a supply that is observed and recorded and read by nothing else.

  A  MIGRATED CONTRACTS  the six RED contracts of ST-0 (T21, T22 x2, U12 x3) with the SAME ids and codes. tests\\red_st0_stationindex_contract.py keeps the
                         originals as skipped evidence (MIGRATED); a contract id is executed in exactly one of the two files.
  B  WIRE AND PARSE      the part STIDX:1:<tgt>:<arr>:<arrseq>:<count>:<hash>, the shared vectors, the int32 and version rules.
  C  THE OBSERVER        receive / check / record, with an injected clock: ready and unavailable, NOT-READY and the grace, the scope and the generation counters, the
                         event numbers, reset, the diagnostic events (change only, capped), and that nothing can make it raise.
  C2 OBSERVABILITY       (Close Decision of ST-1A) what a log read after the live run can say: tgt / arrseq / arr changes, the reason codes, the summary with the last
                         values and the error counts, the 160 character limit of the Caller, the 300 / 3000 / 30000 points and that it is never a line per tick.
  D  ST-1A BOUNDARY      source-shape pins: who reads the new sender fields (nobody but the STIDX statements), where the part is written, that the Python hooks are
                         the four calls of main.py and that no other production module knows the unit.
  E  THE OVERLAY         (Qt, offscreen; only where PyQt6 is importable) a telemetry line WITH a STIDX part leaves every plain attribute of the Overlay exactly as the
                         same line WITHOUT it, and the real UDP path (STALIST then the line) reaches the observer.
The C# half (the CRC-32 vectors, the wire helper, the Legacy state machine and the whole Legacy session driven offline) is TsScoringPlugin\\Handshake\\Tests\\
Test-StationIndexSupplyST1A.ps1. The Current sender (Class1.cs) can not run offline: it is held by the pins of D and judged live in ST-1B.
"""
import ast
import importlib.util
import json
import os
import re
import socket
import sys
import time
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import station_index_contract as sic  # noqa: E402
import telemetry_contract as tc  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None

PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CLASS1 = os.path.join(PLUGIN, "TsScoringPlugin", "Class1.cs")
CURRENT_CSPROJ = os.path.join(PLUGIN, "TsScoringPlugin", "TsScoringPlugin.csproj")
LEGACY_SRC = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "src")
LEGACY_SESSION = os.path.join(LEGACY_SRC, "LegacyTelemetrySession.cs")
LEGACY_TIMELINE = os.path.join(LEGACY_SRC, "LegacyStationTimeline.cs")
LEGACY_CSPROJ = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
B1PROBE_CSPROJ = os.path.join(PLUGIN, "Handshake", "Tests", "B1Probe", "TSScoringPlugin.AtsExLegacy.Telemetry.B1Probe.csproj")
SHARED_IDENTITY_CS = os.path.join(PLUGIN, "Handshake", "Telemetry", "Shared", "StationListIdentity.cs")
VECTORS = os.path.join(HERE, "stidx_vectors_st0.json")

_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


def cs_code(path):
    """C# without comments, whitespace squashed to single blanks (string literals kept)."""
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", _TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else " ", text))


def vectors():
    with open(VECTORS, encoding="utf-8") as f:
        return json.load(f)


H03 = next(h for h in vectors()["crc32"] if h["id"] == "H03")
LIST4 = H03["payload"]                         # four stations at 0 / 1000 / 2000 / 3000 m
LIST4_ID = H03["hex"]
LOCS4 = [0.0, 1000.0, 2000.0, 3000.0]
PART_OK = "STIDX:1:1:-1:0:4:" + LIST4_ID


def telemetry(part, nextloc=1000.0, sid=7):
    """A (minimal) telemetry line as both senders write it: the STIDX part is one part of the comma separated line."""
    nl = "-1" if nextloc is None else repr(float(nextloc))
    return "SCENARIO_ID:%d,SPEED:0,TIME:36000000,LOCATION:5.0,NEXTLOC:%s%s" % (sid, nl, ("," + part) if part else "")


class Clock(object):
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Events(object):
    def __init__(self):
        self.items = []

    def __call__(self, event, **fields):
        self.items.append((event, fields))


# =============================================================================================================================================
# A - the six contracts of the ST-0 RED file, GREEN now (same ids, same codes)
# =============================================================================================================================================
class A_MigratedContracts(unittest.TestCase):
    def test_T21_STATION_INDEX_CONTRACT_the_stidx_unit_judges_every_vector(self):
        vec = vectors()
        self.assertEqual(len(vec["stidx"]), 17)
        wrong = []
        for v in vec["stidx"]:
            got = sic.verdict(v["line"], v["nextloc"], v["station_locations"], v["list_hash"], v["elapsed_since_mismatch_ms"], v["grace_ms"], v["prev_arrseq"])
            if got != v["verdict"]:
                wrong.append((v["id"], got, v["verdict"]))
        self.assertEqual(wrong, [], "vectors judged differently")

    def test_T22_STATION_LIST_ID_FUNCTION_the_python_list_id_matches_the_shared_vectors(self):
        vec = vectors()
        self.assertEqual(len(vec["crc32"]), 5)
        for h in vec["crc32"]:
            self.assertEqual("%08X" % (zlib.crc32(h["payload"].encode("utf-8")) & 0xFFFFFFFF), h["hex"], h["id"])      # the vectors agree with the standard library
            self.assertEqual(sic.list_id(h["payload"]), h["hex"], h["id"])

    def test_T22_STATION_LIST_IDENTITY_CS_the_shared_csharp_station_list_identity_exists(self):
        self.assertTrue(os.path.isfile(SHARED_IDENTITY_CS), "no Telemetry\\Shared\\StationListIdentity.cs")
        code = cs_code(SHARED_IDENTITY_CS)
        for needle in ("internal static class StationListIdentity", "internal static class StationIndexWire", "0xEDB88320u", "0xFFFFFFFFu", 'EmptyId = "00000000"',
                       "internal const int Version = 1;", 'internal const string Key = "STIDX";'):
            self.assertIn(needle, code)
        # its vector execution (CRC-32 of the five payloads, the wire helper against the vector lines) is Test-StationIndexSupplyST1A.ps1

    def test_U12_CURRENT_EMITS_STIDX_the_current_sender_emits_stidx(self):
        c1 = cs_code(CLASS1)
        self.assertIn("NEXTLOC:{nextStationLoc}", c1)
        self.assertIn("STIDX:1:", c1)

    def test_U12_LEGACY_EMITS_STIDX_the_legacy_sender_emits_stidx(self):
        ls = cs_code(LEGACY_SESSION)
        self.assertIn("lb.Group(TelemetryContract.TokStation,", ls)
        self.assertIn('"NEXTLOC", TelemetryContract.D(sv.NextLoc)', ls)
        self.assertIn('"STIDX"', ls)

    def test_U12_PYTHON_TOKEN_KEYS_the_python_vocabulary_knows_stidx(self):
        self.assertIn("NEXTLOC", tc.TOKEN_KEYS["station"])
        self.assertIn("STIDX", tc.TOKEN_KEYS["station"])


# =============================================================================================================================================
# B - the wire form, the parse rules and the pure judgement
# =============================================================================================================================================
class B_WireAndParse(unittest.TestCase):
    def test_the_constants_are_the_contract(self):
        self.assertEqual((sic.KEY, sic.PREFIX, sic.VERSION, sic.NO_STATION, sic.EMPTY_LIST_ID), ("STIDX", "STIDX:", 1, -1, "00000000"))
        self.assertEqual(sic.list_id(""), "00000000")

    def test_every_well_formed_vector_line_parses_and_formats_back_to_itself(self):
        n = 0
        for v in vectors()["stidx"]:
            if v["verdict"] in ("stidx-missing", "stidx-version"):
                continue
            fields, word = sic.parse_part(v["line"])
            self.assertIsNone(word, v["id"])
            self.assertEqual(sic.format_part(fields.tgt, fields.arr, fields.arrseq, fields.count, fields.list_id), v["line"], v["id"])
            n += 1
        self.assertEqual(n, 15)

    def test_parse_part_words(self):
        self.assertEqual(sic.parse_part(None), (None, sic.V_MALFORMED))
        self.assertEqual(sic.parse_part(5), (None, sic.V_MALFORMED))
        self.assertEqual(sic.parse_part("STIDX:2:1:-1:0:4:E1D70409")[1], sic.V_VERSION)
        self.assertEqual(sic.parse_part("STIDX:2")[1], sic.V_VERSION)                       # another version is not read any further
        self.assertEqual(sic.parse_part("STIDX:0:1:-1:0:4:E1D70409")[1], sic.V_VERSION)
        for bad in ("", "STIDX", "STIDX:", "STIDX:x", "STIDX:1", "STIDX:1:1:-1:0:4", "STIDX:1:1:-1:0:4:E1D7040", "STIDX:1:1:-1:0:4:E1D704090", "STIDX:1:1:-1:0:4:XXXXXXXX",
                    "STIDX:1:1:-1:0:4:E1D70409:5", "STIDX:1:+1:-1:0:4:E1D70409", "STIDX:1: 1:-1:0:4:E1D70409", "STIDX:1:1.0:-1:0:4:E1D70409", "stidx:1:1:-1:0:4:E1D70409",
                    "XSTIDX:1:1:-1:0:4:E1D70409"):
            self.assertEqual(sic.parse_part(bad), (None, sic.V_MALFORMED), bad)

    def test_a_number_outside_int32_is_a_range_violation_not_an_exception(self):
        self.assertEqual(sic.parse_part("STIDX:1:2147483648:-1:0:4:E1D70409"), (None, sic.V_RANGE))
        self.assertEqual(sic.parse_part("STIDX:1:1:-1:0:99999999999:E1D70409"), (None, sic.V_RANGE))
        fields, word = sic.parse_part("STIDX:1:2147483647:-1:0:2147483647:e1d70409")
        self.assertIsNone(word)
        self.assertEqual(fields.list_id, "E1D70409")                                           # the hash is compared as upper case

    def test_verdict_order_range_comes_before_the_list_and_the_list_before_nextloc(self):
        # out of range AND a wrong hash: range
        self.assertEqual(sic.verdict("STIDX:1:9:-1:0:4:DEADBEEF", 1000.0, LOCS4, LIST4_ID, 99999, 3000, -1), sic.V_RANGE)
        # wrong hash AND a wrong NEXTLOC (the locations are not trustworthy then): the list
        self.assertEqual(sic.verdict("STIDX:1:1:-1:0:4:DEADBEEF", 1500.0, LOCS4, LIST4_ID, 99999, 3000, -1), sic.V_LIST_MISMATCH)
        self.assertEqual(sic.verdict("STIDX:1:1:-1:0:4:DEADBEEF", 1500.0, LOCS4, LIST4_ID, 0, 3000, -1), sic.V_NOT_READY)
        # a wrong NEXTLOC AND an event number gap: NEXTLOC
        self.assertEqual(sic.verdict("STIDX:1:1:-1:9:4:" + LIST4_ID, 1500.0, LOCS4, LIST4_ID, 0, 3000, 2), sic.V_NEXTLOC)

    def test_the_same_hash_with_another_count_is_a_mismatch_at_once(self):
        self.assertEqual(sic.verdict("STIDX:1:1:-1:0:3:" + LIST4_ID, 1000.0, LOCS4, LIST4_ID, 0, 3000, -1), sic.V_LIST_MISMATCH)

    def test_a_missing_nextloc_is_a_nextloc_violation(self):
        self.assertEqual(sic.verdict(PART_OK, None, LOCS4, LIST4_ID, 0, 3000, -1), sic.V_NEXTLOC)

    def test_the_grace_boundary(self):
        part = "STIDX:1:1:-1:0:4:DEADBEEF"
        self.assertEqual(sic.verdict(part, 1000.0, LOCS4, LIST4_ID, 3000, 3000, -1), sic.V_NOT_READY)
        self.assertEqual(sic.verdict(part, 1000.0, LOCS4, LIST4_ID, 3001, 3000, -1), sic.V_LIST_MISMATCH)
        self.assertEqual(sic.verdict(part, 1000.0, LOCS4, None, 0, 3000, -1), sic.V_NOT_READY)             # no STALIST received yet

    def test_the_event_number_may_stay_or_step_by_one_and_nothing_else(self):
        for prev, seq, expected in ((-1, 0, "ok"), (-1, 7, "ok"), (3, 3, "ok"), (3, 4, "ok"), (3, 5, "gap"), (3, 2, "gap"), (3, 0, "gap"), (0, 0, "ok"), (0, 1, "ok")):
            got = sic.verdict("STIDX:1:1:-1:%d:4:%s" % (seq, LIST4_ID), 1000.0, LOCS4, LIST4_ID, 0, 3000, prev)
            self.assertEqual(got, sic.V_OK if expected == "ok" else sic.V_ARRSEQ_GAP, (prev, seq))

    def test_split_stalist_reads_tolerantly(self):
        self.assertEqual(sic.split_stalist(LIST4), (LOCS4, LIST4_ID))
        self.assertEqual(sic.split_stalist(""), ([], "00000000"))
        locations, ident = sic.split_stalist("A=0=notanumber=1,B=1=2=3")
        self.assertIsNone(locations)
        self.assertEqual(ident, sic.list_id("A=0=notanumber=1,B=1=2=3"))                          # the identity is of the RAW text whatever it says
        self.assertIsNone(sic.split_stalist("A=0")[0])

    def test_the_identity_is_of_the_raw_text_not_of_a_parsed_list(self):
        a = "A=0=0=-1=-1=-1=15000=0=0,B=1=1000=1=2=-1=15000=0=1"
        b = a.replace("=1000=", "=1000.0=")                                                         # the same station, another spelling of the number
        self.assertEqual(sic.split_stalist(a)[0], sic.split_stalist(b)[0])
        self.assertNotEqual(sic.list_id(a), sic.list_id(b))

    def test_the_words_are_the_fixed_words_of_the_contract(self):
        self.assertEqual(set(sic.VERDICTS), {"stidx-ok", "stidx-missing", "stidx-version", "stidx-range", "stidx-nextloc", "stidx-list-mismatch", "stidx-arrseq-gap", "NOT-READY",
                                             "stidx-malformed"})
        for w in sic.VERDICTS:
            self.assertRegex(w, r"^[A-Za-z\-]+$")                                                   # fixed words: nothing that could carry a name or a path


# =============================================================================================================================================
# C - the observer
# =============================================================================================================================================
class C_Observer(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = Events()
        self.o = sic.StationIndexObserver(log=self.events, clock=self.clock)

    def feed_ok(self, sid=7):
        self.o.note_stalist(LIST4)
        return self.o.observe(telemetry(PART_OK, 1000.0, sid), sid)

    def test_a_fresh_observer_is_unavailable(self):
        o = self.o
        self.assertEqual((o.ready, o.tgt_idx, o.arr_idx, o.arr_seq, o.count, o.list_id, o.scenario_id, o.scope), (False, -1, -1, -1, -1, "", None, None))
        self.assertEqual((o.verdict, o.list_generation, o.lines), (sic.V_MISSING, 0, 0))

    def test_stalist_then_line_is_ready_with_the_values_and_the_scope(self):
        self.assertEqual(self.feed_ok(), sic.V_OK)
        o = self.o
        self.assertEqual((o.ready, o.tgt_idx, o.arr_idx, o.arr_seq, o.count, o.list_id), (True, 1, -1, 0, 4, LIST4_ID))
        self.assertEqual((o.scenario_id, o.scope, o.list_generation), (7, (7, LIST4_ID, 4), 1))
        self.assertEqual(o.snapshot()["verdict"], sic.V_OK)

    def test_a_line_before_any_stalist_is_not_ready_and_the_values_are_unavailable(self):
        self.assertEqual(self.o.observe(telemetry(PART_OK), 7), sic.V_NOT_READY)
        o = self.o
        self.assertEqual((o.ready, o.tgt_idx, o.arr_idx, o.arr_seq, o.count, o.list_id), (False, -1, -1, -1, -1, ""))
        self.assertEqual(o.last_fields, (1, 1, -1, 0, 4, LIST4_ID))                                  # the raw numbers stay for the diagnostics
        o.note_stalist(LIST4)
        self.assertEqual(o.observe(telemetry(PART_OK), 7), sic.V_OK)

    def test_the_mismatch_becomes_a_violation_after_the_grace_on_the_injected_clock(self):
        o = self.o
        o.note_stalist(LIST4)
        bad = "STIDX:1:1:-1:0:4:DEADBEEF"
        self.assertEqual(o.observe(telemetry(bad), 7), sic.V_NOT_READY)
        self.clock.now += 2.9
        self.assertEqual(o.observe(telemetry(bad), 7), sic.V_NOT_READY)
        self.clock.now += 0.2
        self.assertEqual(o.observe(telemetry(bad), 7), sic.V_LIST_MISMATCH)
        self.assertFalse(o.ready)
        o.note_stalist("A=0=0=-1=-1=-1=15000=0=0")                                                  # whatever the list is now: a hash that fits again ends the mismatch
        self.assertEqual(o.observe(telemetry("STIDX:1:0:-1:0:1:" + sic.list_id("A=0=0=-1=-1=-1=15000=0=0"), 0.0), 7), sic.V_OK)
        self.clock.now += 10.0
        o.note_stalist(LIST4)
        self.assertEqual(o.observe(telemetry(bad), 7), sic.V_NOT_READY)                              # a new mismatch starts its grace from zero

    def test_an_empty_list_needs_no_stalist(self):
        part = "STIDX:1:-1:-1:0:0:00000000"
        self.assertEqual(self.o.observe(telemetry(part, None), 7), sic.V_OK)
        self.assertEqual((self.o.ready, self.o.count, self.o.scope), (True, 0, (7, "00000000", 0)))
        # ... even when an older list is still remembered
        self.o.note_stalist(LIST4)
        self.assertEqual(self.o.observe(telemetry(part, None), 7), sic.V_OK)

    def test_nextloc_must_follow_the_index(self):
        self.o.note_stalist(LIST4)
        self.assertEqual(self.o.observe(telemetry(PART_OK, 1500.0), 7), sic.V_NEXTLOC)
        self.assertEqual(self.o.observe(telemetry("STIDX:1:-1:-1:0:4:" + LIST4_ID, 1000.0), 7), sic.V_NEXTLOC)
        self.assertEqual(self.o.observe(telemetry("STIDX:1:-1:-1:0:4:" + LIST4_ID, -1.0), 7), sic.V_OK)

    def test_a_line_without_a_part_is_missing(self):
        self.o.note_stalist(LIST4)
        self.assertEqual(self.o.observe(telemetry(None), 7), sic.V_MISSING)
        self.assertEqual(self.o.counts, {sic.V_MISSING: 1})

    def test_event_numbers_a_gap_is_reported_and_the_run_continues_from_it(self):
        o = self.o
        o.note_stalist(LIST4)
        for seq, expected in ((0, sic.V_OK), (0, sic.V_OK), (1, sic.V_OK), (3, sic.V_ARRSEQ_GAP), (3, sic.V_OK), (4, sic.V_OK)):
            self.assertEqual(o.observe(telemetry("STIDX:1:1:-1:%d:4:%s" % (seq, LIST4_ID)), 7), expected, seq)

    def test_a_new_scenario_instance_starts_the_event_numbers_again(self):
        o = self.o
        o.note_stalist(LIST4)
        self.assertEqual(o.observe(telemetry("STIDX:1:1:2:9:4:" + LIST4_ID, 1000.0, 7), 7), sic.V_OK)
        self.assertEqual(o.observe(telemetry("STIDX:1:1:-1:0:4:" + LIST4_ID, 1000.0, 8), 8), sic.V_OK)       # 9 -> 0 in ANOTHER scenario is no gap
        self.assertEqual((o.scenario_id, o.scope, o.list_generation, o.list_changes_in_scenario), (8, (8, LIST4_ID, 4), 2, 0))
        self.assertEqual(o.observe(telemetry("STIDX:1:1:-1:5:4:" + LIST4_ID, 1000.0, 8), 8), sic.V_ARRSEQ_GAP)   # ... but 0 -> 5 inside one is

    def test_a_changed_list_inside_one_scenario_is_counted_as_the_anomaly_it_is(self):
        o = self.o
        self.feed_ok()
        short = "A=0=0=-1=-1=-1=15000=0=0,B=0=500=-1=-1=-1=15000=0=1"
        o.note_stalist(short)
        self.assertEqual(o.observe(telemetry("STIDX:1:1:-1:0:2:" + sic.list_id(short), 500.0), 7), sic.V_OK)
        self.assertEqual((o.list_generation, o.list_changes_in_scenario, o.scope), (2, 1, (7, sic.list_id(short), 2)))

    def test_reset_voids_what_was_received_but_keeps_the_latest_stalist(self):
        o = self.o
        self.feed_ok()
        o.reset()
        self.assertEqual((o.ready, o.tgt_idx, o.count, o.scope, o.list_generation, o.lines, o.counts, o.scenario_id), (False, -1, -1, None, 0, 0, {}, None))
        self.assertEqual(o.observe(telemetry(PART_OK), 7), sic.V_OK)                                 # the STALIST that arrived before the reset is still the list

    def test_events_are_written_on_a_change_only(self):
        for _ in range(5):
            self.feed_ok()
        self.assertEqual(len(self.events.items), 1)
        name, fields = self.events.items[0]
        self.assertEqual(name, "stidx")
        self.assertEqual((fields["verdict"], fields["tgt"], fields["arr"], fields["seq"], fields["cnt"], fields["list"], fields["scn"], fields["gen"]),
                         (sic.V_OK, 1, -1, 0, 4, LIST4_ID, 7, 1))
        self.o.observe(telemetry(PART_OK, 1500.0), 7)
        self.assertEqual([f["verdict"] for _e, f in self.events.items], [sic.V_OK, sic.V_NEXTLOC])
        self.o.observe(telemetry(PART_OK, 1500.0), 7)
        self.assertEqual(len(self.events.items), 2)

    def test_event_fields_are_fixed_words_and_numbers_only(self):
        self.feed_ok()
        self.o.observe(telemetry("STIDX:1:1:-1:0:4:DEADBEEF"), 7)
        for _name, fields in self.events.items:
            for key, value in fields.items():
                self.assertRegex(key, r"^[a-z]+$")
                self.assertRegex(str(value), r"^[A-Za-z0-9\-]+$", key)                               # no station name, no path, no free text
            self.assertLess(len("[MANAGED] event=stidx pid=123456 " + " ".join("%s=%s" % kv for kv in sorted(fields.items()))), 160)    # the Caller keeps 160 characters

    def test_the_events_are_capped_and_the_rest_is_counted(self):
        o = sic.StationIndexObserver(log=self.events, clock=self.clock, max_events=3)
        o.note_stalist(LIST4)
        for i in range(10):
            o.observe(telemetry(PART_OK, 1000.0 if i % 2 == 0 else 1500.0), 7)                       # ok / nextloc / ok / ...: a change every time
        self.assertEqual((len(self.events.items), o.events, o.events_suppressed), (3, 3, 7))
        o.reset()
        self.assertEqual((o.events, o.events_suppressed), (0, 0))

    def test_a_summary_is_written_at_the_set_line_numbers_and_when_the_generation_ends(self):
        o = sic.StationIndexObserver(log=self.events, clock=self.clock)
        o.note_stalist(LIST4)
        for _ in range(sic.SUMMARY_AT[0]):
            o.observe(telemetry(PART_OK), 7)
        # Close Decision: a summary point is two lines (p=1 the counts, p=2 the last values), because the Caller keeps 160 characters of a line
        sums = [f for e, f in self.events.items if e == "stidx-sum" and f["p"] == 1]
        self.assertEqual(len(sums), 1)
        self.assertEqual((sums[0]["n"], sums[0]["ok"], sums[0]["ntr"], sums[0]["miss"], sums[0]["bad"], sums[0]["gen"], sums[0]["final"]), (300, 300, 0, 0, 0, 1, 0))
        o.observe(telemetry(None), 7)                                                                # a line that carries no part
        o.observe(telemetry("STIDX:1:1:-1:0:4:" + LIST4_ID, 1500.0), 7)                               # a violation
        o.reset()
        sums = [f for e, f in self.events.items if e == "stidx-sum" and f["p"] == 1]
        self.assertEqual(len(sums), 2)
        self.assertEqual((sums[1]["n"], sums[1]["ok"], sums[1]["miss"], sums[1]["bad"], sums[1]["final"]), (302, 300, 1, 1, 1))
        o.reset()                                                                                    # nothing received since: nothing to say
        self.assertEqual(len([e for e, _f in self.events.items if e == "stidx-sum"]), 4)             # two summary points of two lines each
        for f in [f for e, f in self.events.items if e == "stidx-sum"]:
            for key, value in f.items():
                self.assertRegex(key, r"^[a-z]+$")
                if key in ("list", "verdict"):
                    self.assertRegex(str(value), r"^[A-Za-z0-9\-]+$", key)                           # the two words of p=2: the hash and the verdict
                else:
                    self.assertRegex(str(value), r"^-?[0-9]+$", key)                                 # everything else is a number
            self.assertLess(len("[MANAGED] event=stidx-sum pid=123456 " + " ".join("%s=%s" % kv for kv in sorted(f.items()))), 160)

    def test_the_summary_is_not_counted_against_the_event_budget(self):
        o = sic.StationIndexObserver(log=self.events, clock=self.clock, max_events=1)
        o.note_stalist(LIST4)
        o.observe(telemetry(PART_OK), 7)
        o.observe(telemetry(PART_OK, 1500.0), 7)                                                     # a change: over the budget of 1
        self.assertEqual((o.events, o.events_suppressed), (1, 1))
        o.reset()
        self.assertEqual([e for e, _f in self.events.items], ["stidx", "stidx-sum", "stidx-sum"])   # the two lines of the final summary

    def test_nothing_can_make_it_raise(self):
        o = self.o
        for junk in (None, 5, "", ",,,", "STIDX:", "STIDX:1:1:-1:0:4:E1D70409,STIDX:1:1:-1:0:4:E1D70409", "NEXTLOC:abc,STIDX:1:1:-1:0:4:E1D70409", "\x00\xff", "S" * 100000):
            self.assertIn(o.observe(junk, 7), sic.VERDICTS)
        for junk in (None, 5, "\x00", "A=B=C", "=" * 1000):
            o.note_stalist(junk)
        self.assertIn(o.observe(telemetry(PART_OK), None), sic.VERDICTS)

    def test_an_unreadable_stalist_can_only_end_in_a_mismatch(self):
        o = self.o
        o.note_stalist("A=0=notanumber=1")
        self.assertEqual(o.observe(telemetry(PART_OK), 7), sic.V_NOT_READY)
        self.clock.now += 5.0
        self.assertEqual(o.observe(telemetry(PART_OK), 7), sic.V_LIST_MISMATCH)

    def test_a_log_that_raises_does_not_matter(self):
        def broken(event, **fields):
            raise RuntimeError("log")
        o = sic.StationIndexObserver(log=broken, clock=self.clock)
        o.note_stalist(LIST4)
        self.assertEqual(o.observe(telemetry(PART_OK), 7), sic.V_OK)
        self.assertTrue(o.ready)

    def test_the_observer_imports_nothing_of_the_application(self):
        text = read_text(os.path.join(ROOT, "station_index_contract.py"))
        imports = set(re.findall(r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M))
        self.assertEqual(imports, {"re", "time", "zlib"})                                            # pure: no Qt, no Win32, no scoring, no telemetry module


# =============================================================================================================================================
# C2 - the observability of the observer (Close Decision of ST-1A): what a log read AFTER the live run (ST-1B) can say about tgt / arr / arrseq
# =============================================================================================================================================
def stidx_line(tgt, arr, seq, sid=7, count=4, list_id=None):
    """A telemetry line whose NEXTLOC follows tgt on the four-station list."""
    loc = LOCS4[tgt] if 0 <= tgt < len(LOCS4) else -1.0
    return telemetry("STIDX:1:%d:%d:%d:%d:%s" % (tgt, arr, seq, count, list_id or LIST4_ID), loc, sid)


class C2_Observability(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = Events()
        self.o = sic.StationIndexObserver(log=self.events, clock=self.clock)
        self.o.note_stalist(LIST4)

    def details(self):
        return [f for e, f in self.events.items if e == "stidx"]

    def sums(self, part):
        return [f for e, f in self.events.items if e == "stidx-sum" and f["p"] == part]

    def test_the_first_line_is_one_event_with_every_field_the_live_log_needs(self):
        self.o.observe(stidx_line(0, -1, 0), 7)
        (f,) = self.details()
        self.assertEqual((f["verdict"], f["tgt"], f["arr"], f["seq"], f["cnt"], f["list"], f["scn"], f["gen"], f["n"], f["why"]), (sic.V_OK, 0, -1, 0, 4, LIST4_ID, 7, 1, 1, "v-s"))

    def test_a_change_of_tgt_writes_an_event_and_nothing_else_does(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        for _ in range(50):
            o.observe(stidx_line(0, -1, 0), 7)                                                       # identical lines: nothing
        self.assertEqual(len(self.details()), 1)
        o.observe(stidx_line(1, -1, 0), 7)
        self.assertEqual([f["why"] for f in self.details()], ["v-s", "t"])
        self.assertEqual((self.details()[1]["tgt"], self.details()[1]["verdict"]), (1, sic.V_OK))
        self.assertEqual((o.tgt_changes, o.arrseq_changes, o.arr_without_seq), (1, 0, 0))

    def test_a_change_of_arrseq_writes_an_event_with_the_arrival_station(self):
        o = self.o
        o.observe(stidx_line(1, -1, 0), 7)
        o.observe(stidx_line(1, 1, 1), 7)                                                            # the arrival candidate event at station 1
        f = self.details()[-1]
        self.assertEqual((f["why"], f["tgt"], f["arr"], f["seq"], f["verdict"]), ("q", 1, 1, 1, sic.V_OK))
        o.observe(stidx_line(2, 1, 1), 7)                                                            # the target moves on, the event number does not
        self.assertEqual(self.details()[-1]["why"], "t")
        self.assertEqual((o.tgt_changes, o.arrseq_changes), (1, 1))

    def test_arr_and_arrseq_and_tgt_changing_together_are_one_event(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        o.observe(stidx_line(1, 0, 1), 7)
        self.assertEqual(len(self.details()), 2)
        self.assertEqual(self.details()[-1]["why"], "t-q")

    def test_arr_changing_inside_the_same_arrseq_is_logged_and_counted_but_is_no_new_verdict(self):
        o = self.o
        o.observe(stidx_line(1, 0, 1), 7)
        w = o.observe(stidx_line(1, 2, 1), 7)                                                        # the station of the event changed, the number of events did not
        self.assertEqual(w, sic.V_OK)                                                                # the verdict words are those of the contract: no new word
        f = self.details()[-1]
        self.assertEqual((f["why"], f["arr"], f["seq"], f["verdict"]), ("a", 2, 1, sic.V_OK))
        self.assertEqual(o.arr_without_seq, 1)
        o.observe(stidx_line(1, 2, 1), 7)
        self.assertEqual(len(self.details()), 2)                                                     # a repeat of it writes nothing
        o.reset()
        self.assertEqual(self.sums(1)[-1]["aa"], 1)

    def test_a_new_scenario_instance_is_a_scope_change_and_not_a_tgt_or_arrseq_change(self):
        o = self.o
        o.observe(stidx_line(2, 1, 3, sid=7), 7)
        o.observe(stidx_line(0, -1, 0, sid=8), 8)
        self.assertEqual(self.details()[-1]["why"], "s")
        self.assertEqual((o.tgt_changes, o.arrseq_changes, o.arr_without_seq), (0, 0, 0))

    def test_a_change_of_the_verdict_writes_an_event_and_an_error_is_written_when_it_begins(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        o.observe(telemetry("STIDX:1:0:-1:0:4:" + LIST4_ID, 1500.0), 7)                              # NEXTLOC does not follow tgt
        o.observe(telemetry("STIDX:1:0:-1:0:4:" + LIST4_ID, 1500.0), 7)                              # the same violation again: counted, not written
        o.observe(telemetry("STIDX:1:9:-1:0:4:" + LIST4_ID), 7)                                       # range
        o.observe(telemetry("STIDX:1:0:-1:0"), 7)                                                    # parse
        o.observe(telemetry("STIDX:2:0:-1:0:4:" + LIST4_ID), 7)                                      # version
        self.assertEqual([(f["verdict"], f["why"]) for f in self.details()][1:], [(sic.V_NEXTLOC, "v"), (sic.V_RANGE, "v-t"), (sic.V_MALFORMED, "v"), (sic.V_VERSION, "v")])      # (the range line also moved tgt)

    def test_unavailable_and_invalid_are_events_too(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        o.observe(telemetry(None), 7)                                                                # unavailable (the part is gone)
        self.assertEqual(self.details()[-1]["verdict"], sic.V_MISSING)
        o.observe(telemetry("STIDX:1:0:-1:0:4:DEADBEEF"), 7)                                         # not ready, then a hash violation after the grace
        self.clock.now += 5.0
        o.observe(telemetry("STIDX:1:0:-1:0:4:DEADBEEF"), 7)
        self.assertEqual([f["verdict"] for f in self.details()][1:], [sic.V_MISSING, sic.V_NOT_READY, sic.V_LIST_MISMATCH])

    def test_a_change_of_the_scope_writes_an_event(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        short = "A=0=0=-1=-1=-1=15000=0=0,B=0=500=-1=-1=-1=15000=0=1"
        o.note_stalist(short)
        o.observe(telemetry("STIDX:1:0:-1:0:2:" + sic.list_id(short), 0.0), 7)
        f = self.details()[-1]
        self.assertEqual((f["why"], f["cnt"], f["list"]), ("s", 2, sic.list_id(short)))

    def test_the_summary_part_2_carries_the_last_values_tgt_arr_arrseq_count_hash_scope_verdict(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        o.observe(stidx_line(2, 1, 1), 7)
        o.reset()
        (p2,) = self.sums(2)
        self.assertEqual((p2["tgt"], p2["arr"], p2["seq"], p2["cnt"], p2["list"], p2["scn"], p2["verdict"], p2["final"], p2["n"], p2["gen"]),
                         (2, 1, 1, 4, LIST4_ID, 7, sic.V_OK, 1, 2, 1))
        (p1,) = self.sums(1)
        self.assertEqual((p1["n"], p1["ok"], p1["final"], p1["nt"], p1["nq"], p1["aa"]), (2, 2, 1, 1, 1, 0))

    def test_the_summary_keeps_the_last_parsed_values_over_lines_that_carry_none_and_says_so_when_there_were_none(self):
        o = self.o
        o.observe(stidx_line(3, 2, 4), 7)
        o.observe(telemetry(None), 7)
        o.observe(telemetry("STIDX:1:3"), 7)                                                         # junk: not parsed
        o.reset()
        (p2,) = self.sums(2)
        self.assertEqual((p2["tgt"], p2["arr"], p2["seq"], p2["cnt"], p2["list"], p2["verdict"]), (3, 2, 4, 4, LIST4_ID, sic.V_MALFORMED))
        self.events.items[:] = []
        o.observe(telemetry(None), 7)
        o.reset()
        (p2,) = self.sums(2)
        self.assertEqual((p2["tgt"], p2["arr"], p2["seq"], p2["cnt"], p2["list"], p2["verdict"]), (-1, -1, -1, -1, "none", sic.V_MISSING))

    def test_the_summary_counts_the_parse_range_and_hash_errors_and_names_unavailable_and_invalid(self):
        o = self.o
        o.observe(stidx_line(0, -1, 0), 7)
        o.observe(telemetry("STIDX:1:0"), 7)                                                         # parse
        o.observe(telemetry("STIDX:9:0:-1:0:4:" + LIST4_ID), 7)                                      # parse class: version
        o.observe(telemetry("STIDX:1:7:-1:0:4:" + LIST4_ID), 7)                                      # range
        o.observe(telemetry("STIDX:1:0:-1:0:4:DEADBEEF"), 7)                                         # not ready (unavailable)
        self.clock.now += 5.0
        o.observe(telemetry("STIDX:1:0:-1:0:4:DEADBEEF"), 7)                                         # hash
        o.observe(telemetry(None), 7)                                                                # unavailable (missing)
        o.observe(telemetry("STIDX:1:0:-1:0:4:" + LIST4_ID, 1500.0), 7)                              # invalid: nextloc (part of bad only)
        o.reset()
        (p1,) = self.sums(1)
        self.assertEqual((p1["pe"], p1["rg"], p1["hm"]), (2, 1, 1))
        self.assertEqual((p1["miss"], p1["ntr"], p1["bad"], p1["ok"], p1["n"]), (1, 1, 5, 1, 8))      # unavailable = miss + ntr, invalid = bad

    def test_the_summary_points_are_the_set_line_numbers_300_3000_30000_and_the_end(self):
        o = sic.StationIndexObserver(log=self.events, clock=self.clock)
        o.note_stalist(LIST4)
        marks = []
        for i in range(1, 30001):
            o.observe(stidx_line(0, -1, 0), 7)
            if i in sic.SUMMARY_AT or i == 299 or i == 301:
                marks.append((i, len([f for e, f in self.events.items if e == "stidx-sum"])))
        self.assertEqual(marks, [(299, 0), (300, 2), (301, 2), (3000, 4), (30000, 6)])
        o.reset()
        self.assertEqual([f["final"] for f in self.sums(1)], [0, 0, 0, 1])
        self.assertEqual([f["n"] for f in self.sums(2)], [300, 3000, 30000, 30000])
        self.assertEqual(len(self.details()), 1)                                                     # 30000 identical lines: one event

    def test_a_long_run_never_becomes_a_line_per_tick(self):
        o = sic.StationIndexObserver(log=self.events, clock=self.clock)
        o.note_stalist(LIST4)
        for i in range(30000):
            o.observe(stidx_line((i // 100) % 4, -1, i // 400), 7)                                    # a change of tgt every 100 lines, of arrseq every 400
        details = len(self.details())
        self.assertLessEqual(details, o.max_events + o.max_progress_events)
        self.assertEqual(o.events + o.progress_events, details)
        self.assertGreater(o.progress_suppressed, 0)                                                 # what did not fit is counted, not written
        self.assertGreater(o.tgt_changes, o.progress_events)                                         # ... and the summary still has the totals
        o.reset()
        self.assertEqual((self.sums(1)[-1]["nt"], self.sums(1)[-1]["nq"]), (299, 74))               # 29900/100 target changes, 29600/400 event-number changes

    def test_the_progress_events_do_not_use_up_the_budget_of_the_verdict_events(self):
        o = sic.StationIndexObserver(log=self.events, clock=self.clock, max_events=3, max_progress_events=2)
        o.note_stalist(LIST4)
        for i in range(10):
            o.observe(stidx_line(i % 4, -1, 0), 7)                                                    # tgt changes every line
        self.assertEqual((o.events, o.progress_events, o.progress_suppressed), (1, 2, 7))
        o.observe(telemetry("STIDX:1:0:-1:0:4:" + LIST4_ID, 1500.0), 7)                              # a verdict change still gets through
        self.assertEqual(self.details()[-1]["verdict"], sic.V_NEXTLOC)
        o.reset()
        self.assertEqual((o.events, o.progress_events, o.progress_suppressed, o.tgt_changes, o.arrseq_changes, o.arr_without_seq), (0, 0, 0, 0, 0, 0))

    def test_every_line_the_observer_writes_fits_the_160_characters_of_the_caller_in_the_worst_case(self):
        worst_detail = {"verdict": sic.V_LIST_MISMATCH, "gen": 99, "n": 123456, "why": "v-s-t-q", "scn": 99999999, "tgt": 999, "arr": 999, "seq": 9999, "cnt": 999, "list": "FFFFFFFF"}
        # the largest digit count the numbers can have together: ok + ntr + miss + bad = n, pe + rg + hm <= bad, nt <= n, nq + aa <= n
        worst_p1 = {"p": 1, "n": 123456, "ok": 30864, "ntr": 30864, "miss": 30864, "bad": 30864, "gen": 99, "final": 1, "pe": 10288, "rg": 10288, "hm": 10288,
                    "nt": 123456, "nq": 61728, "aa": 61728}
        worst_p2 = {"p": 2, "n": 123456, "gen": 99, "final": 1, "verdict": sic.V_LIST_MISMATCH, "tgt": 99, "arr": 99, "seq": 9999, "cnt": 99, "list": "FFFFFFFF", "scn": 99999999}
        for event, fields in (("stidx", worst_detail), ("stidx-sum", worst_p1), ("stidx-sum", worst_p2)):
            line = "[MANAGED] event=%s pid=123456 " % event + " ".join("%s=%s" % kv for kv in sorted(fields.items()))
            self.assertLess(len(line), 160, line)
        # ... and the lines of the real observer have exactly these keys (so that the worst case above is the worst case)
        o = sic.StationIndexObserver(log=self.events, clock=self.clock)
        o.note_stalist(LIST4)
        o.observe(stidx_line(0, -1, 0), 7)
        o.reset()
        self.assertEqual(set(self.details()[0]), set(worst_detail))
        self.assertEqual(set(self.sums(1)[0]), set(worst_p1))
        self.assertEqual(set(self.sums(2)[0]), set(worst_p2))

    def test_the_detail_event_has_fixed_words_and_numbers_only_and_the_why_codes_are_the_known_ones(self):
        o = self.o
        for i, (t, a, q) in enumerate(((0, -1, 0), (1, -1, 0), (1, 1, 1), (2, 2, 1), (2, 2, 2))):
            o.observe(stidx_line(t, a, q), 7)
        for f in self.details():
            for key, value in f.items():
                self.assertRegex(key, r"^[a-z]+$")
                self.assertRegex(str(value), r"^[A-Za-z0-9\-]+$", key)
            self.assertRegex(f["why"], r"^(v|s|t|q|a)(-(v|s|t|q|a))*$")

    def test_an_observer_without_a_log_or_with_a_log_that_raises_still_counts(self):
        quiet = sic.StationIndexObserver(log=None, clock=self.clock)
        quiet.note_stalist(LIST4)
        quiet.observe(stidx_line(0, -1, 0), 7)
        quiet.observe(stidx_line(1, -1, 0), 7)
        quiet.reset()
        self.assertEqual(quiet.lines, 0)

        def broken(event, **fields):
            raise RuntimeError("log")
        noisy = sic.StationIndexObserver(log=broken, clock=self.clock)
        noisy.note_stalist(LIST4)
        noisy.observe(stidx_line(0, -1, 0), 7)
        self.assertEqual(noisy.observe(stidx_line(1, 0, 1), 7), sic.V_OK)
        self.assertEqual((noisy.tgt_changes, noisy.arrseq_changes), (1, 1))


# =============================================================================================================================================
# C3 - the Caller line cap of the managed application (Phase ST-1B Prep, owner decision G-1): the observer's lines reach the Caller's log
# =============================================================================================================================================
LIST12 = ",".join("S%d=0=%d=-1=-1=-1=15000=0=%d" % (i, i * 1000, i) for i in range(12))
LIST12_ID = sic.list_id(LIST12)


def line12(tgt, arr, seq, sid=50123456):
    """A telemetry line of a twelve-station run: NEXTLOC follows tgt (-1 = no next station)."""
    return telemetry("STIDX:1:%d:%d:%d:12:%s" % (tgt, arr, seq, LIST12_ID), tgt * 1000.0 if tgt >= 0 else -1.0, sid)


def twelve_station_run():
    """(lines, expected) of the twelve-station run: 200 lines on the way to station k, 120 lines stopped at it (arrival candidate event number k + 1), 100 lines
    after the last. `expected` is written from this SPECIFICATION (not read from the observer): the (why, tgt, arr, seq) of every change in order."""
    lines, expected = [], [("v-s", 0, -1, 0)]
    for k in range(12):
        lines += [line12(k, k - 1, k)] * 200
        lines += [line12(k, k, k + 1)] * 120
        expected.append(("q", k, k, k + 1))
        if k < 11:
            expected.append(("t", k + 1, k, k + 1))                                                    # the target moves on, the arrival station stays
        else:
            expected.append(("t", -1, k, k + 1))
    lines += [line12(-1, 11, 12)] * 100
    return lines, expected


class _Overlay(object):
    pass


class _Hud(object):
    """What the controller needs of ManagedHudController here: the line writer (the Caller copies what reaches it)."""
    def __init__(self):
        self.lines = []

    def emit_event(self, event, **fields):
        self.lines.append((event, fields))

    def of(self, event):
        return [f for e, f in self.lines if e == event]


class C3_CallerLineCap(unittest.TestCase):
    def setUp(self):
        import managed_input
        self.mi = managed_input
        self.hud = _Hud()
        self.ctl = managed_input.ManagedInputController(_Overlay(), self.hud, None, None)
        self.clock = Clock()
        self.seen = Events()                                                                      # what the observer WROTE (before the Caller cap)
        self.o = sic.StationIndexObserver(log=self._both, clock=self.clock)

    def _both(self, event, **fields):
        self.seen.items.append((event, fields))
        self.ctl.note(event, **fields)

    def run12(self, observer=None):
        o = observer or self.o
        o.note_stalist(LIST12)
        lines, expected = twelve_station_run()
        for text in lines:
            o.observe(text, 50123456)
        return len(lines), expected

    def why_tuples(self, rows):
        return [(f["why"], f["tgt"], f["arr"], f["seq"]) for f in rows]

    # -- the cap itself -----------------------------------------------------------------------------------------------------------------
    def test_there_is_a_cap_of_its_own_for_stidx_and_it_is_the_observer_progress_budget_plus_four(self):
        caps = self.mi.ManagedInputController.EVENT_LINE_CAPS
        self.assertEqual(caps["stidx"], 24)
        self.assertEqual(self.ctl.cap_for("stidx"), sic.DEFAULT_MAX_PROGRESS_EVENTS + 4)
        self.assertGreaterEqual(self.ctl.cap_for("stidx"), 21)                                      # the twelve-station run writes 21 detail lines

    def test_nothing_else_about_the_caps_changed(self):
        cls = self.mi.ManagedInputController
        self.assertEqual({k: v for k, v in cls.EVENT_LINE_CAPS.items() if k not in ("stidx", "jump-settled")}, {"input-hold": 24, "input-pause": 6, "input-resume": 6})        # (Phase ST-3d adds the cap of its own final line, jump-settled: 24)
        self.assertEqual((cls.EVENT_LINE_CAP, cls.TOTAL_LINE_BUDGET), (10, 70))
        self.assertEqual(self.ctl.cap_for("some-unregistered-event"), 10)                           # the default of the unregistered events
        self.assertEqual(self.ctl.cap_for("stidx-sum"), 10)                                         # a name of its own: it is NOT covered by the stidx cap, and keeps the default

    def test_stidx_and_stidx_sum_are_two_event_names_with_two_counters(self):
        for i in range(30):
            self.ctl.note("stidx", n=i)
        self.assertEqual((self.ctl._lines["stidx"], self.ctl.suppressed), (24, 6))
        self.ctl.note("stidx-sum", p=1)
        self.assertEqual((self.ctl._lines["stidx-sum"], self.ctl.suppressed), (1, 6))               # the detail cap never takes a summary line

    def test_the_cap_of_the_other_events_is_what_it_was(self):
        for event, cap in (("input-hold", 24), ("input-pause", 6), ("input-resume", 6), ("scoring-start", 10), ("window-fullscreen", 10), ("ff-release", 10)):
            hud = _Hud()
            ctl = self.mi.ManagedInputController(_Overlay(), hud, None, None)
            for i in range(30):
                ctl.note(event, n=i)
            self.assertEqual(len(hud.of(event)), cap, event)

    def test_a_saturated_stidx_does_not_use_up_the_cap_of_another_event(self):
        for i in range(30):
            self.ctl.note("stidx", n=i)
        for i in range(30):
            self.ctl.note("input-hold", n=i)
        self.assertEqual((len(self.hud.of("stidx")), len(self.hud.of("input-hold"))), (24, 24))     # (70 lines in all: still inside the shared total)

    # -- the twelve-station run ------------------------------------------------------------------------------------------------------
    def test_the_twelve_station_run_every_line_the_observer_writes_reaches_the_caller(self):
        n, expected = self.run12()
        self.o.reset()
        sent = [f for e, f in self.seen.items if e == "stidx"]
        got = self.hud.of("stidx")
        self.assertEqual((len(sent), len(got)), (21, 21))                                          # 1 verdict / scope event + the observer's 20 progress events
        self.assertEqual(got, sent)                                                                # the same lines, the same fields, in the same order
        self.assertEqual(self.why_tuples(got), expected[:21])                                      # ... and they are the first 21 changes of the SPECIFICATION
        self.assertEqual(self.ctl.suppressed, 0)

    def test_the_twelve_station_run_names_every_tgt_arr_and_arrseq_transition_it_can_name(self):
        self.run12()
        self.assertEqual((self.o.progress_events, self.o.progress_suppressed), (20, 4))            # what the OBSERVER keeps back (its budget 20, unchanged): the last four changes
        self.o.reset()
        got = self.hud.of("stidx")
        self.assertEqual([f["tgt"] for f in got if f["why"] == "t"], list(range(1, 11)))           # tgt 1 .. 10: the ten target changes of the 20 progress events
        self.assertEqual([(f["arr"], f["seq"]) for f in got if f["why"] == "q"], [(k, k + 1) for k in range(10)])   # the arrival at station 0 .. 9, event numbers 1 .. 10
        self.assertEqual(got[0]["why"], "v-s")                                                     # the verdict and the scope (scenario, count, hash) of the generation
        self.assertEqual((got[0]["verdict"], got[0]["scn"], got[0]["cnt"], got[0]["list"]), (sic.V_OK, 50123456, 12, LIST12_ID))
        self.assertTrue(all(f["verdict"] == sic.V_OK and f["scn"] == 50123456 and f["cnt"] == 12 and f["list"] == LIST12_ID for f in got))

    def test_the_twelve_station_run_the_summaries_reach_the_caller_and_carry_what_the_observer_kept_back(self):
        n, _expected = self.run12()
        self.o.reset()
        p1, p2 = self.hud.of("stidx-sum")[0::2], self.hud.of("stidx-sum")[1::2]
        self.assertEqual([f["p"] for f in p1], [1, 1, 1])
        self.assertEqual([f["p"] for f in p2], [2, 2, 2])
        self.assertEqual([f["n"] for f in p1], [300, 3000, n])
        self.assertEqual([f["final"] for f in p1], [0, 0, 1])
        last1, last2 = p1[-1], p2[-1]
        self.assertEqual((last1["nt"], last1["nq"], last1["aa"], last1["bad"], last1["pe"], last1["rg"], last1["hm"]), (12, 12, 0, 0, 0, 0, 0))
        self.assertEqual((last2["tgt"], last2["arr"], last2["seq"], last2["cnt"], last2["list"], last2["scn"], last2["verdict"]), (-1, 11, 12, 12, LIST12_ID, 50123456, sic.V_OK))
        self.assertEqual(len(self.hud.of("stidx-sum")), 6)
        self.assertEqual(self.ctl.suppressed, 0)

    def test_the_same_run_with_the_old_default_cap_lost_eleven_detail_lines_which_is_what_this_change_is_for(self):
        class Before(self.mi.ManagedInputController):
            EVENT_LINE_CAPS = {k: v for k, v in self.mi.ManagedInputController.EVENT_LINE_CAPS.items() if k != "stidx"}
        hud = _Hud()
        ctl = Before(_Overlay(), hud, None, None)
        o = sic.StationIndexObserver(log=ctl.note, clock=self.clock)
        self.run12(o)
        o.reset()
        self.assertEqual((len(hud.of("stidx")), len(hud.of("stidx-sum")), ctl.suppressed), (10, 6, 11))

    def test_identical_lines_add_nothing_to_what_reaches_the_caller(self):
        o = self.o
        o.note_stalist(LIST12)
        for _ in range(30000):
            o.observe(line12(0, -1, 0), 50123456)
        o.reset()
        self.assertEqual(len(self.hud.of("stidx")), 1)                                             # 30,000 identical lines: one event ...
        sums = self.hud.of("stidx-sum")
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in sums], [(1, 300, 0), (2, 300, 0), (1, 3000, 0), (2, 3000, 0), (1, 30000, 0), (2, 30000, 0), (1, 30000, 1), (2, 30000, 1)])
        self.assertEqual(self.ctl.suppressed, 0)                                                   # ... and the four summary points (8 lines) all reach the Caller

    # -- the error lines, the summary, the limit ------------------------------------------------------------------------------------------
    def test_an_error_after_the_observer_progress_budget_is_used_up_still_reaches_the_caller_and_the_summary_counts_the_rest(self):
        o = self.o
        o.note_stalist(LIST12)
        for i in range(11):                                                                        # tgt 0 .. 10 and the arrivals: 20 progress events
            o.observe(line12(i, i - 1, i), 50123456)
            o.observe(line12(i, i, i + 1), 50123456)
        self.assertEqual((o.events, o.progress_events), (1, 20))
        o.observe(telemetry("STIDX:1:10:10:11:12:" + LIST12_ID, 1234.0), 50123456)                  # NEXTLOC does not follow tgt
        o.observe(telemetry("STIDX:1:99:10:11:12:" + LIST12_ID), 50123456)                          # range
        o.reset()
        got = self.hud.of("stidx")
        self.assertEqual(len(got), 23)                                                             # 21 + 2 error events: all inside the cap of 24
        self.assertEqual([f["verdict"] for f in got][-2:], [sic.V_NEXTLOC, sic.V_RANGE])
        self.assertEqual(self.ctl.suppressed, 0)
        self.assertEqual((self.hud.of("stidx-sum")[0]["bad"], self.hud.of("stidx-sum")[0]["rg"]), (2, 1))

    def test_the_worst_case_of_one_generation_is_cut_at_the_cap_and_the_summary_still_gets_through(self):
        o = self.o
        o.note_stalist(LIST4)
        for i in range(25):
            o.observe(stidx_line(i % 4, -1, 0), 7)                                                 # progress: 20 events, 5 kept back by the observer
        for i in range(25):
            o.observe(telemetry("STIDX:1:0:-1:0:4:" + LIST4_ID, 1500.0) if i % 2 == 0 else stidx_line(0, -1, 0), 7)    # verdict changes
        o.reset()
        written = [f for e, f in self.seen.items if e == "stidx"]
        self.assertEqual(len(written), o.max_events + o.max_progress_events)                       # the most the observer can write for one generation: 20 + 20
        self.assertEqual(len(written), 40)
        self.assertEqual(len(self.hud.of("stidx")), 24)                                            # the Caller cap: the first 24
        self.assertEqual(self.hud.of("stidx"), written[:24])
        self.assertEqual(self.ctl.suppressed, 16)                                                  # ... the rest is only counted (input-summary: in_suppressed)
        self.assertEqual([(f["p"], f["final"]) for f in self.hud.of("stidx-sum")], [(1, 1), (2, 1)])

    def test_the_total_budget_of_the_controller_holds_the_stidx_family_next_to_a_heavy_real_session(self):
        # the heaviest controller traffic of the live logs read for this decision (live-d6 run A): input-hold 19, ff-release 6, window-fullscreen 4,
        # scoring-start 2, scoring-abort 1, scoring-finish 1 = 33 lines. The healthy twelve-station STIDX traffic is 21 + 6 = 27; the worst case of the cap is 24 + 8.
        for event, count in (("input-hold", 19), ("ff-release", 6), ("window-fullscreen", 4), ("scoring-start", 2), ("scoring-abort", 1), ("scoring-finish", 1)):
            for i in range(count):
                self.ctl.note(event, n=i)
        self.assertEqual(len(self.hud.lines), 33)
        self.run12()
        self.o.reset()
        self.assertEqual((len(self.hud.lines), self.ctl.suppressed), (33 + 27, 0))
        self.assertLessEqual(33 + self.ctl.cap_for("stidx") + 2 * (len(sic.SUMMARY_AT) + 1), self.mi.ManagedInputController.TOTAL_LINE_BUDGET)

    def test_the_cap_counts_per_process_not_per_generation_a_second_scenario_gets_what_is_left(self):
        # KNOWN LIMIT, pinned on purpose (ST-1B Prep decision): ManagedInputController counts per Python PROCESS, as every other event name does, and the Caller
        # starts ONE process per Caller instance. A second scenario generation of the same process finds the counters where the first one left them.
        o = self.o
        o.note_stalist(LIST4)
        for i in range(12):
            o.observe(stidx_line(i % 4, -1, 0, sid=7), 7)                                          # generation 1: 1 + 11 detail lines
        o.reset()
        first = len(self.hud.of("stidx"))
        for i in range(30):
            o.observe(stidx_line(i % 4, -1, 0, sid=8), 8)                                          # generation 2 (new scenario id)
        o.reset()
        self.assertEqual(first, 12)
        self.assertEqual(len(self.hud.of("stidx")), 24)                                            # not 12 + 20: the cap is the process's
        self.assertGreater(self.ctl.suppressed, 0)
        self.assertEqual(len(self.hud.of("stidx-sum")), 4)                                         # the closing summary (2 lines) of each generation: well inside the default 10 of stidx-sum


# =============================================================================================================================================
# D - the ST-1A boundary, as source-shape pins
# =============================================================================================================================================
class D_Boundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c1 = cs_code(CLASS1)
        cls.lses = cs_code(LEGACY_SESSION)
        cls.ltl = cs_code(LEGACY_TIMELINE)
        cls.shared = cs_code(SHARED_IDENTITY_CS)

    def test_one_version_everywhere(self):
        self.assertIn("internal const int Version = 1;", self.shared)
        self.assertEqual(sic.VERSION, 1)
        self.assertEqual(len(re.findall(r'",STIDX:1:"', self.c1)), 1)                                # the Current line writes version 1, the helper writes the other five fields

    def test_current_writes_the_part_once_after_the_unchanged_line_and_before_it_is_stored(self):
        m = re.search(r'string data = \$"[^"]*"; (if \(isInitialized && stidxListReady && stidxListCount == stationList\.Count\) \{ data \+= ",STIDX:1:" \+ '
                      r'TSScoringPlugin\.Telemetry\.StationIndexWire\.Fields\(stidxTarget, stidxArrivalIndex, stidxArrivalSeq, stidxListCount, stidxListId\); \}) lastUdpData = data;', self.c1)
        self.assertIsNotNone(m, "the STIDX statement is not directly between 'string data = ...;' and 'lastUdpData = data;'")
        self.assertEqual(self.c1.count("data +="), 1)
        self.assertNotIn("STIDX", re.search(r'string data = \$"([^"]*)";', self.c1).group(1))      # the interpolated line itself is exactly what it was

    def test_current_new_fields_are_read_by_the_stidx_statements_only(self):
        c1 = self.c1
        counts = {name: len(re.findall(r"\b" + name + r"\b", c1)) for name in ("stidxArrivalIndex", "stidxArrivalSeq", "stidxListId", "stidxListCount", "stidxListReady", "stidxTarget",
                                                                               "stidxDoorOpenedBefore")}
        # each count is the sum of exactly these statements: the declaration, the scenario-change reset, (for the list: the 1 Hz STALIST block), (for the arrival: the event),
        # (for the list: the condition of the part) and the argument of the part
        # Phase ST-3b (an intended change, not a drift): the Current sender now READS the identity of its station list to judge a jump command - BuildJumpView (id, count, ready) and the
        # completion (id, ready): stidxListId 4 -> 6, stidxListCount 5 -> 6, stidxListReady 4 -> 6. The STIDX statements themselves are unchanged; ST-1A's arrival / target / door reads are untouched.
        # Phase U10 (an intended change, not a drift): RejectStationList empties the published identity of a list that was rejected (id, count, ready: 6 -> 7 each); it publishes nothing and the STIDX statements are unchanged.
        self.assertEqual(counts, {"stidxArrivalIndex": 4, "stidxArrivalSeq": 4, "stidxListId": 7, "stidxListCount": 7, "stidxListReady": 7, "stidxTarget": 3, "stidxDoorOpenedBefore": 2})

    def test_current_state_machine_statements_are_untouched(self):
        c1 = self.c1
        for pinned in ("if (isStopped && isInMargin) hasDoorOpenedAtTarget = true;",
                       "if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true; if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal) { targetStationIndex++;",
                       "if (targetSt.IsPass) { if (location > nextStationLoc && !isTerminal) { targetStationIndex++;",
                       "if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal) { if (opStopDelayStartMs < 0) opStopDelayStartMs = timeMs; else if (timeMs >= opStopDelayStartMs + 300) { targetStationIndex++;",
                       "if (stationList[i].Location >= location - 50.0) { targetStationIndex = i;"):
            self.assertIn(pinned, c1)
        writes = re.findall(r"targetStationIndex\s*(\+\+|=(?!=))", c1)
        # Phase ST-3b (an intended change): ONE new write of the target, SelectTargetByRequestedIndex (the adopted StationIndex of an official jump); the declaration, the position search and the three
        # advances are the ones of before (tests\test_stationindex_current_st3b.py pins that the new write is reached only with an index and the old one only without)
        self.assertEqual(sorted(writes), sorted(["=", "=", "=", "++", "++", "++"]))

    def test_legacy_group_carries_stidx_as_its_last_key_inside_the_one_all_or_nothing_group(self):
        ls = self.lses
        m = re.search(r"lb\.Group\(TelemetryContract\.TokStation, (.*?)\); if \(!staListSent", ls)
        self.assertIsNotNone(m)
        keys = re.findall(r'"([A-Z]+)",', m.group(1))
        self.assertEqual(keys, ["NEXTLOC", "NEXTTIME", "ISPASS", "ISTIMING", "MARGINB", "MARGINF", "DOORDIR", "TERM", "STATNAME", "STIDX"])
        self.assertIn('"STIDX", StationIndexWire.Value(sv.Index, timeline.ArrivalIndex, timeline.ArrivalSeq, timeline.Count, timeline.ListId)', ls)
        self.assertEqual(ls.count("StationIndexWire"), 1)

    def test_legacy_timeline_new_members_are_read_only_by_the_part_and_the_state_machine_is_untouched(self):
        ltl = self.ltl
        for pinned in ("if (isStopped && isInMargin) { hasDoorOpenedAtTarget = true; }",
                       "if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) { hasDoorOpenedAtTarget = true; } if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal) { target++;",
                       "if (st.IsPass) { if (location > nextStationLoc && !isTerminal) { target++;",
                       "if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal) { if (opStopDelayStartMs < 0) { opStopDelayStartMs = timeMs; } else if (timeMs >= opStopDelayStartMs + 300) { target++;"):
            self.assertIn(pinned, ltl)
        counts = {name: len(re.findall(r"\b" + name + r"\b", ltl)) for name in ("arrivalIndex", "arrivalSeq", "listId", "doorOpenedBefore", "shownIndex")}
        self.assertEqual(counts, {"arrivalIndex": 4, "arrivalSeq": 4, "listId": 4, "doorOpenedBefore": 2, "shownIndex": 3})
        writes = re.findall(r"\btarget\s*(\+\+|=(?!=))", ltl)
        # Phase ST-3c (intended update; was three "="): the fourth "=" is SelectRequestedTarget (the target of an official v2 jump: the adopted index, no position involved); Reset, "no station in range"
        # and the position search are the three of before, and the three advances are untouched
        self.assertEqual(sorted(writes), sorted(["=", "=", "=", "=", "++", "++", "++"]))

    def test_the_senders_link_the_shared_file_and_the_probe_project_compiles_what_the_product_compiles(self):
        for path in (CURRENT_CSPROJ, LEGACY_CSPROJ, B1PROBE_CSPROJ):
            text = read_text(path)
            self.assertEqual(len(re.findall(r"StationListIdentity\.cs", text)), 2, path)             # the Include and its Link
        self.assertIn(r'Include="..\Handshake\Telemetry\Shared\StationListIdentity.cs"', read_text(CURRENT_CSPROJ))
        self.assertIn(r'Include="..\Shared\StationListIdentity.cs"', read_text(LEGACY_CSPROJ))

    def test_python_main_has_exactly_the_four_hooks_and_no_other_production_module_knows_the_unit(self):
        main = read_text(os.path.join(ROOT, "main.py"))
        # the three entry points are called once each (the STALIST datagram, the accepted line, the epoch reset); the lazy accessor only by the two that need the observer
        self.assertEqual(sorted(re.findall(r"self\.(_station_index_\w+)\(", main)),
                         sorted(["_station_index_note_stalist", "_station_index_observe", "_station_index_reset", "_station_index_observer", "_station_index_observer"]))
        # Phase ST-2a (intended update; was 2): the import, the constructor and ONE call of the pure list_id() when a STALIST is adopted (the identity of the adopted list)
        self.assertEqual(len(re.findall(r"station_index_contract\b", main)), 3)
        for name in os.listdir(ROOT):
            if name.endswith(".py") and name not in ("main.py", "station_index_contract.py"):
                text = read_text(os.path.join(ROOT, name))
                for word in ("station_index_contract", "_stidx_observer", "_station_index_"):
                    self.assertFalse(word in text, "%s knows %s" % (name, word))                    # (not assertNotIn: it would print the whole module)

    def test_the_observer_attribute_is_private_to_the_overlay(self):
        main = read_text(os.path.join(ROOT, "main.py"))
        self.assertEqual(len(re.findall(r"self\._stidx_observer\b", main)), 1)                       # stored once, in the lazy accessor
        # Phase ST-2a (intended update; was: no public attribute at all). ST-2a decided how the index is used: the observer's values become the published identity
        # attributes ONLY through the verified sync. Every assignment to them is inside __init__ (the defaults), _station_identity_apply or _station_identity_clear.
        published = ("bve_tgt_idx", "bve_arr_idx", "bve_arr_seq", "bve_list_id")
        where = set()
        tree = ast.parse(main)
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay"]:
            for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                for node in ast.walk(fn):
                    targets = []
                    if isinstance(node, ast.Assign):
                        for t in node.targets:
                            targets += list(t.elts) if isinstance(t, ast.Tuple) else [t]
                    for t in targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self" and (t.attr in published or t.attr.startswith("stidx")):
                            where.add((fn.name, t.attr))
        self.assertEqual({fn for fn, _attr in where}, {"__init__", "_station_identity_apply", "_station_identity_clear"})
        self.assertEqual({attr for _fn, attr in where}, set(published))
        self.assertNotRegex(main, r"(?m)^\s*self\.stidx\w*\s*=")


# =============================================================================================================================================
# E - the real Overlay (offscreen)
# =============================================================================================================================================
def port_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 54321))
        return True
    except OSError:
        return False
    finally:
        s.close()


WALL_CLOCK = ("last_time_change_real",)         # the one plain attribute that is a wall-clock stamp of the construction (time.time()): two Overlays can never agree on it


def plain_state(overlay):
    """Every plain attribute of the Overlay (basic types only, private names and the wall-clock stamp exempt): the state the scoring, the HUD and the menus read."""
    basic = (int, float, str, bool, type(None), list, tuple, dict, set, frozenset)
    return {k: repr(v) for k, v in sorted(vars(overlay).items()) if not k.startswith("_") and k not in WALL_CLOCK and isinstance(v, basic)}


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class E_RealOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if not port_free():
            raise unittest.SkipTest("UDP 54321 is in use (a running TS Scoring is never touched): INCONCLUSIVE")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["st1a"])
        import main
        import test_telemetry_l3 as l3
        cls.main, cls.l3 = main, l3

    def make(self):
        self._wdl = self.main.write_desktop_log
        self.main.write_desktop_log = lambda *a, **k: None                                           # the Overlay logs a door time to the Desktop; a test must not
        o = self.main.Overlay()
        o.timer.stop()
        return o

    def close(self, o):
        self.main.write_desktop_log = self._wdl
        o.udp_socket.close()
        o.close()
        o.deleteLater()

    def feed(self, o, text):
        if o.telemetry_gate.accept(text):
            o.apply_telemetry_text(text)

    def lines(self, with_part):
        out = []
        for i in range(3):
            base = self.l3.current_line(5)
            out.append(base + (",STIDX:1:1:-1:%d:3:%s" % (i, self.part_id) if with_part else ""))
        return out

    payload = "駅A=0=0=-1=-1=-1=15000=0=0,駅B=1=2000=36100000=36110000=-1=15000=0=0,駅C=0=4000=36200000=-1=-1=15000=0=1"
    part_id = sic.list_id(payload)

    def test_a_line_with_a_stidx_part_changes_no_plain_attribute_of_the_overlay(self):
        results = []
        for with_part in (False, True):
            o = self.make()
            try:
                o._station_index_note_stalist(self.payload)
                for text in self.lines(with_part):
                    self.feed(o, text)
                results.append(plain_state(o))
                observer = o.__dict__.get("_stidx_observer")
                self.assertIsNotNone(observer)
                self.assertEqual(observer.ready, with_part)                                          # the part is seen (or, without it, nothing is)
            finally:
                self.close(o)
        self.assertEqual(results[0], results[1])
        self.assertGreater(len(results[0]), 100)

    def test_the_epoch_reset_voids_the_observer(self):
        o = self.make()
        try:
            o._station_index_note_stalist(self.payload)
            for text in self.lines(True):
                self.feed(o, text)
            self.assertTrue(o._stidx_observer.ready)
            o.reset_telemetry_state()
            self.assertFalse(o._stidx_observer.ready)
            self.assertEqual(o._stidx_observer.lines, 0)
        finally:
            self.close(o)

    def test_the_real_udp_path_stalist_then_line_reaches_the_observer(self):
        o = self.make()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.sendto(("STALIST:" + self.payload).encode("utf-8"), ("127.0.0.1", 54321))
                s.sendto(self.lines(True)[0].encode("utf-8"), ("127.0.0.1", 54321))
            finally:
                s.close()
            end = time.time() + 3.0
            while time.time() < end:
                self.app.processEvents()
                obs = o.__dict__.get("_stidx_observer")
                if obs is not None and obs.lines >= 1:
                    break
                time.sleep(0.01)
            obs = o._stidx_observer
            self.assertEqual((obs.verdict, obs.ready, obs.tgt_idx, obs.count, obs.list_id, obs.scenario_id), (sic.V_OK, True, 1, 3, self.part_id, 5))
            self.assertEqual([st["location"] for st in o.station_list], [0.0, 2000.0, 4000.0])      # the station list itself came in as it always did
        finally:
            self.close(o)


# =============================================================================================================================================
# F - Phase ST-1B (final summary fix; owner decision on run ST1B-CUR-20261021-233632-dff7): the generation-end summary (final=1) is written when the application
#     ENDS, not only when a NEW generation begins. The live run of ONE generation (no reload) had four summaries, all final=0, and no final=1 at all.
# =============================================================================================================================================
def one_generation_run(sid=7):
    """(lines, expected): the shape of the live Current run in 3,800 lines - target 0, target 1 (t), arrival at 1 (q), target 2 (t), arrival at 2 (q).
    `expected` is written from this SPECIFICATION: (n, tgt, arr, seq) at the line that changed something."""
    lines = ([stidx_line(0, -1, 0, sid)] * 1500 + [stidx_line(1, -1, 0, sid)] * 1500 + [stidx_line(1, 1, 1, sid)] * 500 + [stidx_line(2, 1, 1, sid)] * 200
             + [stidx_line(2, 2, 2, sid)] * 100)
    return lines, {"n": 3800, "tgt": 2, "arr": 2, "seq": 2, "nt": 2, "nq": 2}


def sum_rows(rows, part=None, final=None):
    out = [f for e, f in rows if e == "stidx-sum"]
    if part is not None:
        out = [f for f in out if f["p"] == part]
    if final is not None:
        out = [f for f in out if f["final"] == final]
    return out


class F1_TheGenerationEndSummary(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = Events()
        self.o = sic.StationIndexObserver(log=self.events, clock=self.clock)
        self.o.note_stalist(LIST4)
        self.lines, self.want = one_generation_run()

    def run_all(self):
        for text in self.lines:
            self.o.observe(text, 7)

    def details(self):
        return [f for e, f in self.events.items if e == "stidx"]

    # -- the contract -------------------------------------------------------------------------------------------------------------------
    def test_a_generation_that_never_resets_has_no_final_summary_until_it_is_finished(self):
        self.run_all()
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in sum_rows(self.events.items)], [(1, 300, 0), (2, 300, 0), (1, 3000, 0), (2, 3000, 0)])
        self.o.finish()
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in sum_rows(self.events.items)[4:]], [(1, 3800, 1), (2, 3800, 1)])

    def test_the_final_summary_is_exactly_one_p1_and_one_p2_and_they_are_the_last_two_events(self):
        self.run_all()
        self.o.finish()
        self.assertEqual(len(sum_rows(self.events.items, final=1)), 2)
        self.assertEqual([(e, f["p"], f["final"]) for e, f in self.events.items[-2:]], [("stidx-sum", 1, 1), ("stidx-sum", 2, 1)])

    def test_the_final_values_are_the_last_detail_values_and_the_scope_and_the_counts(self):
        self.run_all()
        self.o.finish()
        p1, p2 = sum_rows(self.events.items, 1, 1)[0], sum_rows(self.events.items, 2, 1)[0]
        last = self.details()[-1]
        self.assertEqual((p2["tgt"], p2["arr"], p2["seq"]), (self.want["tgt"], self.want["arr"], self.want["seq"]))
        self.assertEqual((p2["tgt"], p2["arr"], p2["seq"], p2["cnt"], p2["list"], p2["scn"], p2["verdict"]),
                         (last["tgt"], last["arr"], last["seq"], last["cnt"], last["list"], last["scn"], last["verdict"]))
        self.assertEqual((p2["cnt"], p2["list"], p2["scn"], p2["verdict"], p2["gen"]), (4, LIST4_ID, 7, sic.V_OK, 1))
        self.assertEqual((p1["n"], p1["ok"], p1["ntr"], p1["miss"], p1["bad"], p1["pe"], p1["rg"], p1["hm"], p1["aa"]), (3800, 3800, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual((p1["nt"], p1["nq"]), (self.want["nt"], self.want["nq"]))
        self.assertEqual((sum(1 for f in self.details() if "t" in f["why"].split("-")), sum(1 for f in self.details() if "q" in f["why"].split("-"))), (2, 2))

    def test_every_summary_of_final_0_agrees_with_the_detail_lines_up_to_its_own_n_and_none_is_compared_with_a_later_value(self):
        # the Judge contract (B / C): a final=0 summary is a snapshot at its n
        self.run_all()
        self.o.finish()
        details = self.details()
        for p1 in sum_rows(self.events.items, 1, 0):
            upto = [f for f in details if f["n"] <= p1["n"]]
            self.assertEqual(p1["nt"], sum(1 for f in upto if "t" in f["why"].split("-")), p1["n"])
            self.assertEqual(p1["nq"], sum(1 for f in upto if "q" in f["why"].split("-")), p1["n"])
            (p2,) = [f for f in sum_rows(self.events.items, 2, 0) if f["n"] == p1["n"]]
            self.assertEqual((p2["tgt"], p2["arr"], p2["seq"]), (upto[-1]["tgt"], upto[-1]["arr"], upto[-1]["seq"]), p1["n"])
        self.assertEqual(sum_rows(self.events.items, 2, 0)[-1]["tgt"], 1)                           # n=3000 says tgt 1, the end says tgt 2: both are right at their own n

    def test_the_periodic_summaries_stay_final_0_and_finish_does_not_rewrite_them(self):
        self.run_all()
        before = list(self.events.items)
        self.o.finish()
        self.assertEqual(self.events.items[:len(before)], before)

    # -- exactly once -------------------------------------------------------------------------------------------------------------------
    def test_finish_twice_writes_one_final_summary(self):
        self.run_all()
        self.o.finish()
        self.o.finish()
        self.o.finish()
        self.assertEqual(len(sum_rows(self.events.items, final=1)), 2)

    def test_the_reset_that_follows_a_finish_writes_no_second_final(self):
        self.run_all()
        self.o.finish()
        self.o.reset()
        self.assertEqual(len(sum_rows(self.events.items, final=1)), 2)
        self.assertEqual(self.o.lines, 0)                                                         # ... and the reset still cleared everything

    def test_a_reset_without_a_finish_still_writes_the_final_summary_as_before(self):
        self.run_all()
        self.o.reset()
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in sum_rows(self.events.items, final=1)], [(1, 3800, 1), (2, 3800, 1)])
        self.o.finish()                                                                           # nothing is left to finish
        self.assertEqual(len(sum_rows(self.events.items, final=1)), 2)

    def test_each_generation_gets_its_own_final_one_by_reset_one_by_finish(self):
        self.run_all()
        self.o.reset()                                                                            # generation 1 ends because generation 2 begins
        for text in [stidx_line(0, -1, 0, 8)] * 40:
            self.o.observe(text, 8)
        self.o.finish()                                                                           # generation 2 ends because the application ends
        finals = sum_rows(self.events.items, 1, 1)
        self.assertEqual([(f["gen"], f["n"]) for f in finals], [(1, 3800), (1, 40)])              # (gen counts READY scopes since the reset: 1 each)
        self.assertEqual([f["scn"] for f in sum_rows(self.events.items, 2, 1)], [7, 8])

    def test_a_line_after_a_finish_makes_the_next_finish_write_a_new_final_that_is_not_stale(self):
        # not reachable at shutdown (no line comes after the loop ended); pinned so that a final=1 can never disagree with the last line
        self.run_all()
        self.o.finish()
        self.o.observe(stidx_line(2, 2, 3), 7)
        self.o.finish()
        finals = sum_rows(self.events.items, 2, 1)
        self.assertEqual([(f["n"], f["seq"]) for f in finals], [(3800, 2), (3801, 3)])

    # -- safe ---------------------------------------------------------------------------------------------------------------------------
    def test_nothing_received_writes_nothing_and_does_not_raise(self):
        fresh = sic.StationIndexObserver(log=self.events, clock=self.clock)
        fresh.finish()
        fresh.finish()
        self.assertEqual(self.events.items, [])
        self.o.finish()
        self.assertEqual(self.events.items, [])                                                   # a STALIST alone is no generation either

    def test_finish_with_no_sink_or_a_sink_that_raises_never_raises(self):
        silent = sic.StationIndexObserver(log=None, clock=self.clock)
        silent.note_stalist(LIST4)
        silent.observe(stidx_line(0, -1, 0), 7)
        silent.finish()

        def broken(event, **fields):
            raise OSError("the sink is gone")
        noisy = sic.StationIndexObserver(log=broken, clock=self.clock)
        noisy.note_stalist(LIST4)
        noisy.observe(stidx_line(0, -1, 0), 7)
        noisy.finish()
        noisy.finish()
        self.assertEqual(noisy.lines, 1)

    def test_finish_changes_no_value_the_observer_publishes_and_adds_no_detail_event(self):
        self.run_all()
        keys = ("ready", "tgt_idx", "arr_idx", "arr_seq", "count", "list_id", "scenario_id", "verdict", "list_generation", "tgt_changes", "arrseq_changes",
                "arr_without_seq", "events", "progress_events", "lines")
        before = ({k: getattr(self.o, k) for k in keys}, self.o.snapshot(), self.o.scope)
        details = len(self.details())
        self.o.finish()
        self.assertEqual(({k: getattr(self.o, k) for k in keys}, self.o.snapshot(), self.o.scope), before)
        self.assertEqual(len(self.details()), details)

    def test_the_wire_the_words_and_the_summary_points_are_what_they_were(self):
        self.assertEqual(sic.SUMMARY_AT, (300, 3000, 30000))
        self.assertEqual((sic.DEFAULT_MAX_PROGRESS_EVENTS, sic.DEFAULT_GRACE_MS, sic.VERSION), (20, 3000, 1))
        self.assertEqual(sic.format_part(1, 0, 1, 4, LIST4_ID), "STIDX:1:1:0:1:4:" + LIST4_ID)
        src = read_text(os.path.join(ROOT, "station_index_contract.py"))
        self.assertEqual(len(re.findall(r"def finish\(self", src)), 1)
        self.assertEqual(len(re.findall(r"\._summary\(True\)", src)), 2)                          # reset() and finish(): the two ways a generation ends
        self.assertEqual(len(re.findall(r"\._summary\(False\)", src)), 1)


class F2_TheCallerLineBudget(unittest.TestCase):
    """The final summary has to get through the managed application's own line caps (EVENT_LINE_CAPS is NOT changed: stidx-sum keeps the default of 10)."""

    def setUp(self):
        import managed_input
        self.mi = managed_input
        self.hud = _Hud()
        self.ctl = managed_input.ManagedInputController(_Overlay(), self.hud, None, None)
        self.clock = Clock()
        self.o = sic.StationIndexObserver(log=self.ctl.note, clock=self.clock)
        self.o.note_stalist(LIST4)

    def test_the_final_summary_of_the_live_shaped_run_reaches_the_caller(self):
        lines, want = one_generation_run()
        for text in lines:
            self.o.observe(text, 7)
        self.o.finish()
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in self.hud.of("stidx-sum")],
                         [(1, 300, 0), (2, 300, 0), (1, 3000, 0), (2, 3000, 0), (1, 3800, 1), (2, 3800, 1)])
        self.assertEqual(self.ctl.suppressed, 0)
        self.assertEqual(len(self.hud.of("stidx")), 5)
        self.assertEqual(self.hud.of("stidx-sum")[-1]["tgt"], want["tgt"])

    def test_the_worst_single_generation_of_30000_lines_still_gets_all_eight_summary_lines_through_the_default_cap_of_ten(self):
        for _ in range(30000):
            self.o.observe(stidx_line(0, -1, 0), 7)
        self.o.finish()
        sums = self.hud.of("stidx-sum")
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in sums],
                         [(1, 300, 0), (2, 300, 0), (1, 3000, 0), (2, 3000, 0), (1, 30000, 0), (2, 30000, 0), (1, 30000, 1), (2, 30000, 1)])
        self.assertEqual(self.ctl.suppressed, 0)
        self.assertLessEqual(2 * (len(sic.SUMMARY_AT) + 1), self.ctl.cap_for("stidx-sum"))

    def test_next_to_a_heavy_real_session_the_total_budget_of_the_controller_holds(self):
        for event, count in (("input-hold", 19), ("ff-release", 6), ("window-fullscreen", 4), ("scoring-start", 2), ("scoring-abort", 1), ("scoring-finish", 1)):
            for i in range(count):
                self.ctl.note(event, n=i)
        lines, _want = one_generation_run()
        for text in lines:
            self.o.observe(text, 7)
        self.o.finish()
        self.assertEqual((len(self.hud.lines), self.ctl.suppressed), (33 + 5 + 6, 0))
        self.assertLessEqual(len(self.hud.lines), self.mi.ManagedInputController.TOTAL_LINE_BUDGET)

    def test_the_caps_are_exactly_what_they_were(self):
        cls = self.mi.ManagedInputController
        self.assertEqual(cls.EVENT_LINE_CAPS, {"input-hold": 24, "input-pause": 6, "input-resume": 6, "stidx": 24, "jump-settled": 24})        # Phase ST-3d: + the ONE final line of an official jump transaction
        self.assertEqual((cls.EVENT_LINE_CAP, cls.TOTAL_LINE_BUDGET), (10, 70))


class F3_TheManagedEndPathInTheSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = read_text(os.path.join(ROOT, "main.py"))

    def cleanup_text(self):
        start = self.main.index("def cleanup_managed_resources():")
        return self.main[start:self.main.index("cleanup = cleanup_managed_resources if", start)]

    def test_the_overlay_has_one_finish_method_that_only_asks_the_existing_observer_to_finish(self):
        self.assertEqual(len(re.findall(r"def _station_index_finish\(self\):", self.main)), 1)
        start = self.main.index("def _station_index_finish(self):")
        body = self.main[start:self.main.index("\n    def ", start + 10)]
        self.assertIn("self.__dict__.get('_stidx_observer')", body)                                 # never creates the observer: nothing received = nothing to finish
        self.assertEqual(len(re.findall(r"\.finish\(\)", body)), 1)
        self.assertRegex(body, r"(?s)try:.*except Exception:\s*pass")
        for forbidden in ("score", "station_list", "checkpoint", "jump", "save", "hud", "popup", "rollback", "is_scoring"):
            self.assertNotIn(forbidden, body.lower(), forbidden)

    def test_the_cleanup_of_the_managed_run_calls_it_once_before_the_overlay_is_released_and_guards_it(self):
        text = self.cleanup_text()
        self.assertEqual(len(re.findall(r"_station_index_finish", text)), 1)                      # one lookup, one call ...
        self.assertEqual(len(re.findall(r"_station_index_finish", self.main)), 2)                 # ... and the definition: nothing else in main.py knows it
        self.assertLess(text.index("_station_index_finish"), text.index("_release_overlay(overlay, hud)"))   # the HUD controller (the line writer) is still alive
        self.assertRegex(text, r"_station_index_finish\", None\)[^\n]*\n\s*if finish is not None:\n\s*try:\n\s*finish\(\)\n\s*except Exception:\n\s*pass\n")

    def test_current_and_legacy_share_the_one_path_the_call_does_not_ask_who_the_sender_is(self):
        # the sender (Current plugin / Legacy telemetry DLL) is invisible to the application: both write the same STIDX part into the same telemetry line. So the finish must not depend
        # on the owner argument, on the DataPlane, or on any role word, and it must sit at the top level of the clean-up (not inside an `if` of the Caller-owned objects).
        text = self.cleanup_text()
        call = text.index("finish = getattr(overlay, \"_station_index_finish\"")
        line_start = text.rfind("\n", 0, call) + 1
        self.assertEqual(text[line_start:call], " " * 12)                                            # the indentation of the first statements of cleanup_managed_resources
        before = text[:call]
        for word in ("owner", "caller", "legacy", "current", "dataplane_receiver", "jump_client"):
            self.assertNotIn(word, before.lower().replace("telemetry_directory.publish_withdrawing()", ""), word)
        start = self.main.index("def _station_index_finish(self):")
        body = self.main[start:self.main.index("\n    def ", start + 10)].lower()
        for word in ("owner", "caller", "legacy", "current", "dataplane", "role", "pid"):
            self.assertNotIn(word, body, word)

    def test_the_other_shutdown_summaries_keep_their_order(self):
        text = self.cleanup_text()
        order = [text.index(w) for w in ("publish_withdrawing()", "_station_index_finish", "jump_client.close()", "dataplane_receiver.stop()", "dataplane_receiver.summary()",
                                         "_release_overlay(overlay, hud)", "telemetry_directory.close()")]
        self.assertEqual(order, sorted(order))

    def test_nothing_but_the_overlay_and_the_unit_knows_the_finish(self):
        for name in os.listdir(ROOT):
            if name.endswith(".py") and name not in ("main.py", "station_index_contract.py"):
                text = read_text(os.path.join(ROOT, name))
                self.assertFalse("_station_index_finish" in text, name)
                self.assertFalse(".finish()" in text and "_stidx" in text, name)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class F4_TheRealOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if not port_free():
            raise unittest.SkipTest("UDP 54321 is in use (a running TS Scoring is never touched): INCONCLUSIVE")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["st1a"])
        import main
        import test_telemetry_l3 as l3
        cls.main, cls.l3 = main, l3

    def make(self):
        self._wdl = self.main.write_desktop_log
        self.main.write_desktop_log = lambda *a, **k: None
        o = self.main.Overlay()
        o.timer.stop()
        self.rows = []
        o.input_event_sink = lambda event, **fields: self.rows.append((event, fields))
        return o

    def close(self, o):
        self.main.write_desktop_log = self._wdl
        o.udp_socket.close()
        o.close()
        o.deleteLater()

    payload = E_RealOverlay.payload
    part_id = E_RealOverlay.part_id

    def feed(self, o, count=5):
        o._station_index_note_stalist(self.payload)
        for i in range(count):
            text = self.l3.current_line(5) + (",STIDX:1:1:-1:%d:3:%s" % (min(i, 1), self.part_id))
            if o.telemetry_gate.accept(text):
                o.apply_telemetry_text(text)

    def test_finish_writes_the_final_summary_once_and_changes_no_plain_attribute(self):
        o = self.make()
        try:
            self.feed(o)
            before = plain_state(o)
            o._station_index_finish()
            o._station_index_finish()
            self.assertEqual(plain_state(o), before)
            self.assertEqual([(f["p"], f["final"]) for f in sum_rows(self.rows, final=1)], [(1, 1), (2, 1)])
            p2 = sum_rows(self.rows, 2, 1)[0]
            self.assertEqual((p2["tgt"], p2["arr"], p2["seq"], p2["cnt"], p2["list"], p2["scn"], p2["verdict"]), (1, -1, 1, 3, self.part_id, 5, sic.V_OK))
            self.assertEqual(sum_rows(self.rows, 1, 1)[0]["n"], 5)
        finally:
            self.close(o)

    def test_the_epoch_reset_after_a_finish_writes_no_second_final(self):
        o = self.make()
        try:
            self.feed(o)
            o._station_index_finish()
            o.reset_telemetry_state()
            self.assertEqual(len(sum_rows(self.rows, final=1)), 2)
        finally:
            self.close(o)

    def test_the_epoch_reset_alone_still_writes_the_final_of_the_generation_that_ends(self):
        o = self.make()
        try:
            self.feed(o)
            o.reset_telemetry_state()
            self.assertEqual(len(sum_rows(self.rows, final=1)), 2)
            o._station_index_finish()                                                             # the new generation has no line yet
            self.assertEqual(len(sum_rows(self.rows, final=1)), 2)
        finally:
            self.close(o)

    def test_an_overlay_that_received_nothing_finishes_silently_and_creates_no_observer(self):
        o = self.make()
        try:
            o._station_index_finish()
            self.assertEqual(self.rows, [])
            self.assertNotIn("_stidx_observer", o.__dict__)
        finally:
            self.close(o)


# the application process of F5: the REAL run_managed (real Win32 events, real Qt loop, real shutdown path) with a fake Overlay that carries the real STIDX methods of main.Overlay and
# the real ManagedInputController (the real line caps); the only fakes are the window and the HUD. It is fed STIDX lines 0.2 s after it starts.
F5_CHILD = r'''
import os, sys
ROOT = os.environ["TSS_F_ROOT"]
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from PyQt6.QtCore import QTimer
import main
import managed_input
import test_stationindex_supply_st1a as t

MODE = os.environ["TSS_F_MODE"]


class Timer(object):
    def stop(self):
        pass


class Hud(object):
    def emit_event(self, event, **fields):
        text = "[MANAGED] event=%s pid=1" % event
        for key in sorted(fields):
            text += " %s=%s" % (key, fields[key])
        sys.stderr.write(text + "\n")
        sys.stderr.flush()


class Overlay(object):
    _station_index_observer = main.Overlay._station_index_observer
    _station_index_note_stalist = main.Overlay._station_index_note_stalist
    _station_index_observe = main.Overlay._station_index_observe
    _station_index_reset = main.Overlay._station_index_reset
    _station_index_finish = getattr(main.Overlay, "_station_index_finish", None)
    _emit_input_event = main.Overlay._emit_input_event

    def __init__(self):
        self.timer = Timer()
        self.udp_bind_ok = True
        self.udp_port = 0
        self.current_scenario_id = 7
        managed_input.ManagedInputController(self, Hud(), None, None)
        QTimer.singleShot(200, self.feed)

    def close(self):
        pass

    def feed(self):
        if MODE == "none":
            return
        lines, _want = t.one_generation_run(7)
        self._station_index_note_stalist(t.LIST4)
        for text in lines:
            self._station_index_observe(text)
        if MODE in ("reset-then-more", "reset-last"):
            self._station_index_reset()
        if MODE == "reset-then-more":
            self.current_scenario_id = 8
            for text in [t.stidx_line(0, -1, 0, 8)] * 40:
                self._station_index_observe(text)
        if MODE == "raise":
            def boom():
                raise ValueError("fake runtime failure")
            QTimer.singleShot(300, boom)


if __name__ == "__main__":
    sys.exit(main.run_managed(sys.argv, overlay_factory=Overlay, hud_factory=lambda overlay, args, log: None))
'''


@unittest.skipUnless(HAS_QT and sys.platform == "win32", "PyQt6 / Win32 named objects are needed")
class F5_TheRealManagedShutdown(unittest.TestCase):
    def setUp(self):
        import subprocess
        import test_managed_mode_e2 as e2
        import managed_mode as mm
        self.sp, self.e2, self.mm = subprocess, e2, mm
        self.sync = mm.Win32Sync()
        self.args = e2.args_for()
        self.owner = e2.Owner(self.sync, self.args)
        self.proc = None

    def tearDown(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.communicate()
        self.owner.close()

    def run_child(self, mode, stop=True):
        env = dict(os.environ)
        env.update({"TSS_F_MODE": mode, "TSS_F_ROOT": ROOT, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"})
        self.proc = self.sp.Popen([sys.executable, "-c", F5_CHILD] + self.e2.argv_for(self.args), stdout=self.sp.PIPE, stderr=self.sp.PIPE, env=env, cwd=ROOT,
                                  creationflags=0x08000000)
        self.assertTrue(self.e2.wait_until(self.owner.ready, 20), "Ready was not published")
        time.sleep(1.0)                                                                           # the feed (0.2 s after start) is long done
        if stop:
            self.owner.set_stop()
        try:
            _out, err = self.proc.communicate(timeout=15)
        except self.sp.TimeoutExpired:
            self.proc.kill()
            _out, err = self.proc.communicate()
            self.fail("the child did not exit")
        text = err.decode("utf-8", "replace")
        rows = []
        for line in text.splitlines():
            m = re.search(r"\[MANAGED\] event=(stidx-sum|stidx) (.*)$", line)
            if m:
                fields = dict(kv.split("=", 1) for kv in m.group(2).split() if "=" in kv)
                rows.append((m.group(1), {k: (int(v) if k not in ("list", "verdict") and re.fullmatch(r"-?\d+", v) else v) for k, v in fields.items()}))
        return self.proc.returncode, text, rows

    def test_a_normal_stop_writes_the_final_summary_exactly_once_before_the_exit_line(self):
        code, text, rows = self.run_child("ok")
        self.assertEqual(code, 0, text)
        self.assertEqual([(f["p"], f["n"], f["final"]) for f in sum_rows(rows)], [(1, 300, 0), (2, 300, 0), (1, 3000, 0), (2, 3000, 0), (1, 3800, 1), (2, 3800, 1)], text)
        p2 = sum_rows(rows, 2, 1)[0]
        self.assertEqual((p2["tgt"], p2["arr"], p2["seq"], p2["cnt"], p2["list"], p2["scn"], p2["verdict"]), (2, 2, 2, 4, LIST4_ID, 7, sic.V_OK))
        p1 = sum_rows(rows, 1, 1)[0]
        self.assertEqual((p1["nt"], p1["nq"], p1["bad"], p1["pe"], p1["rg"], p1["hm"], p1["aa"]), (2, 2, 0, 0, 0, 0, 0))
        self.assertLess(text.index("event=stidx-sum"), text.index("event=exit"))
        self.assertGreater(text.rindex("event=stidx-sum"), text.index("event=stop-received"))
        self.assertEqual(text.count("final=1"), 2)

    def test_a_stop_without_any_stidx_line_is_a_safe_normal_exit_with_no_summary(self):
        code, text, rows = self.run_child("none")
        self.assertEqual(code, 0, text)
        self.assertEqual(rows, [])
        self.assertIn("event=exit", text)

    def test_a_reset_in_the_middle_gives_one_final_to_each_generation_and_none_twice(self):
        code, text, rows = self.run_child("reset-then-more")
        self.assertEqual(code, 0, text)
        self.assertEqual([(f["n"], f["scn"]) for f in sum_rows(rows, 2, 1)], [(3800, 7), (40, 8)], text)
        self.assertEqual(len(sum_rows(rows, 1, 1)), 2)

    def test_a_reset_right_before_the_stop_leaves_the_one_final_of_the_reset_and_writes_no_second(self):
        code, text, rows = self.run_child("reset-last")
        self.assertEqual(code, 0, text)
        self.assertEqual([(f["p"], f["n"]) for f in sum_rows(rows, final=1)], [(1, 3800), (2, 3800)], text)

    def test_an_exception_exit_runs_the_same_cleanup_so_the_final_summary_is_written_and_the_exit_code_is_the_error_one(self):
        code, text, rows = self.run_child("raise", stop=False)
        self.assertEqual(code, self.mm.EXIT_RUNTIME_ERROR, text)
        self.assertEqual([(f["p"], f["n"]) for f in sum_rows(rows, final=1)], [(1, 3800), (2, 3800)], text)
        self.assertLess(text.index("final=1"), text.index("event=exit"))


if __name__ == "__main__":
    unittest.main()
