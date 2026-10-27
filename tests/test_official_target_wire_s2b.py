"""Phase SI-R2.2-S2b: the C# senders write the OFFTGT part of the host's official next-station target.

The contract of the receiving side is S2a (official_target_contract.py, unchanged). This file holds the sending side that can be held without BVE:

  A  the golden table (tests/official_target_wire_golden.json): the exact part for a reading, the canonical numbers, and the Python round trip of every part
  B  the shared source (StationListIdentity.cs): the reader core and the wire helper are plain, stateless, host independent and read only
  C  the Legacy sender (LegacyTelemetrySession.cs / LegacyTelemetryExtension.cs): the port, the key, the exception separation, the read only adapter

The C# is also executed: Handshake/Tests/Test-OfficialTargetWireS2B.ps1 compiles these sources in memory and runs the same golden table, the reader core and the Legacy sender
(it needs Windows PowerShell 5.1; it is a gate of its own, like the other Test-*.ps1). What an offline run can not reach - the host reads of the Current sender (Class1.cs) -
is held by the source pins of this file and, later, by the live runs.
"""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import official_target_contract as C  # noqa: E402
import official_target_wire_fixture as F  # noqa: E402

GOLDEN_PATH = os.path.join(HERE, "official_target_wire_golden.json")
SHARED = "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs"
SESSION = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs"
EXTENSION = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs"
LEGACY_API = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs"
CLASS1 = "TsScoringPlugin/TsScoringPlugin/Class1.cs"

# the words that would make the official target a corrected value: a distance, a door, a speed, a position, a search, a machine value, the terminal sentinel (E-9 section 4 and 5)
FORBIDDEN_WORDS = re.compile(
    r"Doors?\b|AreAllClosed|DoorSide|DoorDir|\bSpeed|VehicleLocation|Location\s*[-+]\s*\w*Location|NEXTLOC|NEXTTIME|STIDX|GetValueAt|Nearest|Distance|\bSearch|SelectTarget"
    r"|TerminalDeparture|\bMachine|Math\.(Sqrt|Pow|Min|Max)|\bstatic\s+(?:readonly\s+)?(?!class\b)[\w<>\[\],\.]+\s+\w+\s*(?:=|;)")
HOST_WORDS = re.compile(r"AtsEx|BveTypes|BveEx|Scenario|Conductor|MapObjectList")
# E-9 section 1: no write to the host, no move of the list
WRITE_WORDS = re.compile(r"\bCurrentIndex\s*=(?!=)|GoToByIndex|\.GoTo\(|\.Insert\(|\.Add\(|\.Remove(?:At)?\(|\.Clear\(|Initialize|OnJumped|Harmony|\.Invoke\(|GetField|GetProperty|GetMethod|BindingFlags")


def load_golden():
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def real(token):
    return {"NaN": float("nan"), "Infinity": float("inf"), "-Infinity": float("-inf"), "NegZero": -0.0}.get(token) if token in ("NaN", "Infinity", "-Infinity", "NegZero") else float(token)


def code(rel):
    return F.strip_cs_comments(F.read_source(rel))


def block(text, header):
    found = F.extract_block(text, header)
    assert found is not None, header
    return found


STATE_OF_WIRE = {"K": "KNOWN", "T": "NONE_TERMINAL", "N": "NONE_EMPTY", "U": "UNAVAILABLE", "F": "READ_FAILED"}


# ==============================================================================================================================================
# A - the golden table
# ==============================================================================================================================================
class A_Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load_golden()
        cls.cases = cls.doc["cases"]

    def test_the_table_is_well_formed(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 40)
        self.assertEqual({c["state"] for c in self.cases}, set(C.STATE_WORDS))
        for c in self.cases:
            self.assertEqual(set(c), {"id", "state", "reading", "listId", "expected", "twin", "canonicalOnly", "note"}, c["id"])
            rd = c["reading"]
            if rd["isNull"]:
                self.assertEqual(set(rd), {"isNull"}, c["id"])
            else:
                self.assertEqual(set(rd), {"isNull", "hostNull", "cursorOk", "cursor", "countOk", "count", "nextOk", "loc", "marginMin", "marginMax"}, c["id"])
                for name in ("loc", "marginMin", "marginMax"):
                    self.assertIsInstance(rd[name], str, c["id"])
            self.assertEqual(c["expected"] is None, bool(c["canonicalOnly"]), c["id"])

    def test_every_pinned_part_is_one_the_sender_may_write(self):
        # nine fields, the version 1, a state word of the table, the grammar of the receiver for every number: no 2000.0, no 5.50, no +1, no -0, no exponent, no NaN / Infinity
        for c in self.cases:
            if c["expected"] is None:
                continue
            f = c["expected"].split(":")
            self.assertEqual((len(f), f[0], f[1]), (9, "OFFTGT", "1"), c["id"])
            self.assertEqual(f[2], c["state"], c["id"])
            self.assertRegex(f[3], r"^(0|-?[1-9][0-9]{0,10})$", c["id"])
            self.assertRegex(f[4], r"^(0|-?[1-9][0-9]{0,10})$", c["id"])
            self.assertRegex(f[5], r"^[0-9A-F]{8}$", c["id"])
            for token in f[6:]:
                self.assertRegex(token, r"^-?(0|[1-9][0-9]{0,14})(\.[0-9]{0,16}[1-9])?$", c["id"])
                self.assertNotEqual(token, "-0", c["id"])

    def test_the_unavailable_and_failed_forms_are_the_fixed_forms(self):
        for c in self.cases:
            if c["state"] in ("U", "F"):
                self.assertEqual(c["expected"], "OFFTGT:1:%s:-1:-1:00000000:-1:-1:-1" % c["state"], c["id"])

    def test_the_empty_list_and_the_terminal_forms(self):
        for c in self.cases:
            if c["state"] == "N":
                self.assertEqual(c["expected"], "OFFTGT:1:N:-1:0:00000000:-1:-1:-1", c["id"])
            if c["state"] == "T":
                f = c["expected"].split(":")
                self.assertEqual((f[3], f[6], f[7], f[8]), ("-1", "-1", "-1", "-1"), c["id"])
                self.assertGreaterEqual(int(f[4]), 1, c["id"])

    def test_a_known_part_is_never_partial(self):
        # a K carries every field; whatever cannot be written canonically is F (never a K with a missing or stand-in number)
        for c in self.cases:
            if c["state"] == "K" and c["expected"] is not None:
                f = c["expected"].split(":")
                self.assertGreaterEqual(float(f[8]), 0.0, c["id"])
                self.assertGreaterEqual(float(f[7]), 0.0, c["id"])
                self.assertGreaterEqual(int(f[4]), 1, c["id"])
                self.assertTrue(0 <= int(f[3]) < int(f[4]), c["id"])

    def test_the_twin_cases_are_the_parts_of_the_fixture_of_the_receiving_side(self):
        # tests/official_target_wire_fixture.py (the provisional writer of the S2a vectors) and the table agree: the text of C# is the text the vectors were made with
        checked = 0
        for c in self.cases:
            if not c["twin"] or c["expected"] is None:
                continue
            rd = c["reading"]
            list_id = c["listId"] if c["listId"] is not None else "00000000"
            if c["state"] == "K":
                sem = {"state": "K", "index": rd["cursor"] + 1, "loc": real(rd["loc"]), "mb": abs(real(rd["marginMin"])), "mf": real(rd["marginMax"])}
                text = F.build_part(sem, list_id, rd["count"])
            elif c["state"] == "T":
                text = F.build_part({"state": "T"}, list_id, rd["count"])
            elif c["state"] == "N":
                text = F.build_part({"state": "N", "count_override": 0, "hash_override": "00000000"}, list_id, 0)
            else:
                text = F.build_part({"state": c["state"], "count_override": -1, "hash_override": "00000000"}, "00000000", -1)
            self.assertEqual(text, c["expected"], c["id"])
            checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_every_pinned_part_is_judged_by_the_receiving_contract_as_the_state_it_means(self):
        judged = 0
        for c in self.cases:
            if c["expected"] is None:
                continue
            wire, why = C.decode(c["expected"])
            self.assertIsNone(why, c["id"])
            self.assertEqual(wire["state"], c["state"], c["id"])
            station_list = [{"location": wire["loc"] if i == wire["idx"] else 0.0} for i in range(max(wire["count"], 0))]
            result, scope_ok = C.evaluate(c["expected"], station_list, wire["hash"], 0)
            self.assertTrue(scope_ok, c["id"])
            self.assertEqual(result["official_state"], STATE_OF_WIRE[c["state"]], c["id"])
            if c["state"] == "K":
                self.assertEqual(result["official_index"], wire["idx"], c["id"])
                self.assertAlmostEqual(result["official_location"], wire["loc"], places=6, msg=c["id"])
                self.assertEqual(result["official_margin_b"], wire["mb"], c["id"])
                self.assertEqual(result["official_margin_f"], wire["mf"], c["id"])
            judged += 1
        self.assertGreaterEqual(judged, 40)

    def test_the_forbidden_forms_are_refused_by_the_receiver(self):
        # the other side of the canonical rule: what the sender never writes, the receiver does not accept either (S2a)
        good = "OFFTGT:1:K:1:4:E1D70409:%s:5:10"
        self.assertIsNone(C.decode(good % "2000")[1])
        for bad in ("2000.0", "-0", "+1", "1e3", "NaN", "Infinity", "5.50", "0.10"):
            self.assertIsNotNone(C.decode(good % bad)[1], bad)


# ==============================================================================================================================================
# B - the shared source
# ==============================================================================================================================================
class B_SharedSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = F.read_source(SHARED)
        cls.text = F.strip_cs_comments(cls.raw)
        cls.blocks = {name: block(cls.text, r"internal\s+(?:sealed\s+|static\s+)class\s+" + name) for name in ("OfficialTargetReading", "OfficialTargetStation", "OfficialTargetHost", "OfficialTargetReader", "OfficialTargetWire")}

    def test_the_five_types_live_in_StationListIdentity_cs_and_are_internal(self):
        for name in self.blocks:
            self.assertEqual(len(re.findall(r"\bclass\s+" + name + r"\b", self.text)), 1, name)
        self.assertRegex(self.text, r"internal\s+static\s+class\s+OfficialTargetReader")
        self.assertRegex(self.text, r"internal\s+static\s+class\s+OfficialTargetWire")
        self.assertNotRegex(self.text, r"\bpublic\s+(?:sealed\s+|static\s+)?class\s+OfficialTarget")

    def test_the_stationindex_helpers_are_not_touched(self):
        # StationListIdentity and StationIndexWire keep every character of their code (the STIDX part is not part of this phase)
        self.assertEqual(F.normalized_sha(block(self.text, r"internal\s+static\s+class\s+StationListIdentity")), "271817b24915d68491a7d4378cf1050d4bda421d2b498f520ef8afc0bca28b0f")
        self.assertEqual(F.normalized_sha(block(self.text, r"internal\s+static\s+class\s+StationIndexWire")), "14fb80cb194558d623d04791d013baaec4bae99b2613e417c95762436a2400a4")

    def test_the_wire_helper_knows_exactly_the_five_state_words(self):
        wire = self.blocks["OfficialTargetWire"]
        words = set(re.findall(r'"([KTNUF])"', wire)) | set(re.findall(r"'([KTNUF])'", wire))
        self.assertEqual(words, set("KTNUF"))
        self.assertIn('"OFFTGT"', wire)

    def test_the_host_has_getters_only_and_the_data_classes_no_behaviour(self):
        host = self.blocks["OfficialTargetHost"]
        fields = re.findall(r"internal\s+([\w<>, ]+?)\s+(\w+)\s*;", host)
        self.assertEqual([name for _t, name in fields], ["GetStations", "GetCursor", "GetCount", "ReadStation"])
        for type_name, name in fields:
            self.assertTrue(type_name.startswith("Func<"), name + ": " + type_name)       # no Action<>, no setter: nothing can be written to the host through this object
        for name in ("OfficialTargetReading", "OfficialTargetStation"):
            self.assertNotRegex(self.blocks[name], r"\(")

    def test_the_reader_and_the_wire_keep_nothing_between_two_ticks(self):
        for name in ("OfficialTargetReader", "OfficialTargetWire"):
            body = self.blocks[name]
            self.assertRegex(body.split("{", 1)[0], r"\bstatic\b", name)                  # a static class: there is no instance to hold a value
            # no static field (a const is not a state; a method is not a field), no instance field
            self.assertIsNone(re.search(r"\bstatic\s+(?!class\b)(?!readonly\b)[\w<>\[\],\.]+\s+\w+\s*(?:=|;)", body), name)
            self.assertNotRegex(body, r"\bstatic\s+readonly\b")
            self.assertNotRegex(body, r"(?m)^\s*(?:private|internal|public)\s+(?!static\b|const\b)[\w<>\[\],\.]+\s+\w+\s*(?:=[^;(]*)?;")

    def test_the_reader_and_the_wire_are_host_independent_and_read_only(self):
        for name, body in self.blocks.items():
            self.assertIsNone(FORBIDDEN_WORDS.search(body), name)
            self.assertIsNone(HOST_WORDS.search(body), name)
            self.assertIsNone(WRITE_WORDS.search(body), name)
        self.assertIsNone(re.search(r"AtsEx|BveTypes|BveEx", self.text))

    def test_every_read_of_the_reader_has_a_try_of_its_own(self):
        reader = self.blocks["OfficialTargetReader"]
        for call in ("host.GetStations()", "host.GetCursor(stations)", "host.GetCount(stations)", "host.ReadStation(stations, next)"):
            i = reader.index(call)
            before = reader[:i]
            self.assertGreater(before.rfind("try"), before.rfind("catch"), call)           # the nearest try before the call is open
        self.assertGreaterEqual(len(re.findall(r"\bcatch\b", reader)), 4)

    def test_numbers_are_written_with_the_invariant_culture_only(self):
        wire = self.blocks["OfficialTargetWire"]
        calls = re.findall(r"\.(?:ToString|TryParse)\([^;]*", wire)
        self.assertGreaterEqual(len(calls), 3)
        for call in calls:
            self.assertIn("CultureInfo.InvariantCulture", call)
        self.assertNotIn('"R"', wire)                                                   # "R" can stop at 15 digits on a 64-bit .NET Framework
        self.assertNotRegex(wire, r"CurrentCulture|string\.Format|\$\"")

    def test_c_sharp_5_is_enough(self):
        # the PowerShell test path compiles the shared source with the C# 5 compiler of Windows PowerShell
        for pattern in (r"\?\.", r"\?\[", r"\$\"", r"nameof\(", r"\bout\s+var\b", r"=>", r"\bis\s+\w+\s+\w+\)", r"\bdefault\s*\(\s*\)", r"\bdefault\s*:\s*\w+\s*;"):
            self.assertIsNone(re.search(pattern, self.text), pattern)


# ==============================================================================================================================================
# C - the Legacy sender
# ==============================================================================================================================================
class C_LegacySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = code(SESSION)
        cls.extension = code(EXTENSION)

    def test_the_port_is_declared_in_the_session_file_only_and_the_Legacy_API_is_untouched(self):
        self.assertEqual(len(re.findall(r"interface\s+ILegacyOfficialTargetApi", self.session)), 1)
        for rel in F.product_cs_files():
            if rel != SESSION:
                self.assertIsNone(re.search(r"interface\s+ILegacyOfficialTargetApi", code(rel)), rel)
        api = code(LEGACY_API)
        self.assertNotRegex(api, r"OfficialTarget|ReadOfficialTarget")
        port = block(self.session, r"internal\s+interface\s+ILegacyOfficialTargetApi")
        self.assertEqual(re.findall(r"\b\w+\s+(\w+)\s*\(\s*\)\s*;", port), ["ReadOfficialTarget"])           # one method: one READ

    def test_the_fake_of_the_earlier_phases_is_not_asked_to_carry_the_port(self):
        fake = code("TsScoringPlugin/Handshake/Tests/TelemetryTestFixture.cs")
        self.assertNotIn("OfficialTarget", fake)

    def test_the_nine_argument_constructor_is_the_earlier_sender(self):
        # it chains to the new constructor with official = null: the row has no OFFTGT key
        self.assertRegex(re.sub(r"\s+", "", self.session), re.escape("ILegacyJumpAvailabilityjumpAvail):this(api,sink,nowMs,idSeed,diag,input,scoring,groundApi,jumpAvail,null){}"))
        self.assertRegex(self.session, r"internal\s+LegacyTelemetrySession\([^)]*ILegacyJumpAvailability\s+jumpAvail,\s*ILegacyOfficialTargetApi\s+official\)")
        self.assertRegex(self.session, r"private\s+readonly\s+ILegacyOfficialTargetApi\s+official\s*;")
        self.assertEqual(len(re.findall(r"this\.official\s*=\s*official\s*;", self.session)), 1)

    def test_the_key_is_the_last_key_of_the_station_group_and_is_made_in_a_try_of_its_own(self):
        flat = re.sub(r"\s+", "", self.session)
        want = ("StationIndexWire.Value(sv.Index,timeline.ArrivalIndex,timeline.ArrivalSeq,timeline.Count,timeline.ListId));"
                "if(official!=null){stringofficialValue;try{officialValue=OfficialTargetWire.Value(official.ReadOfficialTarget(),timeline.ListId);}"
                "catch{officialValue=OfficialTargetWire.Placeholder(\"F\");}lb.Key(OfficialTargetWire.Key,officialValue);}")
        self.assertEqual(flat.count(want), 1)
        # the key is only ever written there, and the session holds no value between two Ticks
        self.assertEqual(len(re.findall(r"lb\.Key\(", self.session)), 1)
        self.assertEqual(len(re.findall(r"\bOfficialTargetReading\b", self.session)), 1)             # the return type of the port: no field, no local copy of a reading
        self.assertEqual(len(re.findall(r"\bOfficialTargetWire\b", self.session)), 3)
        self.assertEqual(len(re.findall(r"\bofficial\.", self.session)), 1)                          # the port is called once: one read per line

    def test_the_key_adds_no_token_and_the_group_call_is_unchanged(self):
        # OFFTGT is a key of the station group (the token is announced already); LineBuilder.Key only appends a key
        key = block(self.session, r"internal\s+void\s+Key\(string key, string value\)")
        self.assertNotIn("tokens", key)
        self.assertRegex(key, r"body\.Append\(','\)\.Append\(key\)\.Append\(':'\)\.Append\(value\)")
        self.assertEqual(len(re.findall(r"lb\.Group\(TelemetryContract\.TokStation,", self.session)), 1)

    def test_the_adapter_implements_the_port_and_is_wired_as_the_tenth_argument(self):
        self.assertRegex(self.extension, r"class\s+AtsExLegacyApi\s*:\s*ILegacyApi,\s*ILegacyInputApi,\s*ILegacyScoringApi,\s*ILegacyGroundApi,\s*ILegacyOfficialTargetApi")
        self.assertIn("diag, api, api, api, jumpAvail, api);", self.extension)
        self.assertEqual(len(re.findall(r"OfficialTargetReading\s+ILegacyOfficialTargetApi\.ReadOfficialTarget\(\)", self.extension)), 1)

    def test_the_adapter_only_reads(self):
        body = block(self.extension, r"OfficialTargetReading\s+ILegacyOfficialTargetApi\.ReadOfficialTarget\(\)")
        self.assertIsNone(WRITE_WORDS.search(body))
        self.assertIsNone(FORBIDDEN_WORDS.search(body))
        # every assignment is to a local, to a delegate of the host adapter object or to a field of our own data object: never to a member of a host object
        targets = set(re.findall(r"(?<![\w.])([A-Za-z_][\w.]*)\s*=(?![=>])", body))
        self.assertEqual(targets, {"host", "host.GetStations", "host.GetCursor", "host.GetCount", "host.ReadStation", "scenario", "vehicle", "conductor", "item", "station", "read",
                                   "read.Location", "read.MarginMin", "read.MarginMax"})
        # the host reads: the public getters of Conductor.Stations (CurrentIndex, Count, the indexer) and the station values
        for want in ("((MapObjectList)list).CurrentIndex;", "((MapObjectList)list).Count;", "((MapObjectList)list)[index]", "station.Location", "station.MarginMin", "station.MarginMax", "conductor.Stations"):
            self.assertIn(want, body)
        self.assertEqual(len(re.findall(r"\bCurrentIndex\b", body)), 1)
        self.assertEqual(len(re.findall(r"\bCurrentIndex\b", self.extension)), 1)                    # the one and only mention of the cursor in the whole file

    def test_the_adapter_reads_the_scenario_wrapper_of_this_tick_only(self):
        body = block(self.extension, r"OfficialTargetReading\s+ILegacyOfficialTargetApi\.ReadOfficialTarget\(\)")
        self.assertIn("Scenario scenario = current;", body)
        self.assertNotRegex(body, r"hacker\.")


if __name__ == "__main__":
    unittest.main()
