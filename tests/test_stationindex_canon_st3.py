"""Phase PID-D4JA StationIndex ST-3a - the CONTRACT tests of the Jump wire (jump_wire.py: the pure Python codec; the C# twin is Telemetry/Shared/JumpWire.cs, held to the SAME
vector table by Handshake/Tests/Test-JumpWireST3A.ps1). Python only; nothing here builds, starts a process, opens a socket or writes a file.

What this file holds (the ids are the ones of the Start Audit, 13-Red-Test-Plan.md)
  A  N-18  JUMP-REQUEST-V2-GRAMMAR            the v2 request: 7 fields, the STA / LOC order, scope, StationIndex, location; the codec never re-selects by position
  B  N-19  JUMP-COMPLETE-V2-PARSE             the v2 completion: exactly 9 fields; selected_idx / scope / location are fields, a malformed one is a reason word
  C  N-20  JUMP-WIRE-VECTOR-PARITY            tests/jump_wire_vectors.json: the Python half (the C# half is Test-JumpWireST3A.ps1, which reads the same file)
  D  N-21a START-AND-RETRY-SHARE-THE-BUILDER  one place assembles the wire text; no role (start / retry) exists in the codec. (N-21b - the call sites of execute_retry and
                                              handle_menu_enter - needs main.py / scoring_logic.py and belongs to ST-3d: ST-3a does not wire the codec)
  E  numbers   location grammar, contract range, -0.0, exact round trip (Python float() is the reference of a correct parse), the splitmix64 corpus shared with the C# half
  F  scope     (scenario_id, list_id, count)
  G  v1        the READ-ONLY v1 grammar and its equivalence with the readers that exist (main.py inline reader; the C# readers are in Test-JumpWireST3A.ps1)
  H  purity    the module is pure (no Qt, socket, file, clock, locale, global state, product module) and is NOT wired into the product yet

The tests were written as REDs first: against the tree before jump_wire.py each of them fails with ContractViolation whose code is the declared one ("jump-wire-module-absent",
"vector-table-absent"), never with an ImportError; they pass against the module of ST-3a.
"""
import ast
import math
import os
import re
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VECTORS_PATH = os.path.join(HERE, "jump_wire_vectors.json")
MODULE_PATH = os.path.join(ROOT, "jump_wire.py")
PS_TEST_PATH = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Tests", "Test-JumpWireST3A.ps1")
CS_PATH = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "Shared", "JumpWire.cs")


class ContractViolation(AssertionError):
    """The tree does not meet the contract; `code` names the violated clause (a RED run compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST3A-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def load_module(tid):
    if not os.path.isfile(MODULE_PATH):
        raise ContractViolation(tid, "jump-wire-module-absent", "jump_wire.py does not exist: the Jump wire v2 codec is not implemented")
    import importlib
    return importlib.import_module("jump_wire")


_VECTORS = {}


def load_vectors(tid):
    if "doc" not in _VECTORS:
        if not os.path.isfile(VECTORS_PATH):
            raise ContractViolation(tid, "vector-table-absent", "tests/jump_wire_vectors.json does not exist")
        import json
        with open(VECTORS_PATH, "r", encoding="utf-8") as f:
            _VECTORS["doc"] = json.load(f)
    return _VECTORS["doc"]


def bits_of(x):
    return "%016X" % struct.unpack(">Q", struct.pack(">d", x))[0]


def float_of(bits_hex):
    return struct.unpack(">d", struct.pack(">Q", int(bits_hex, 16)))[0]


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def scope_tuple(fields):
    if fields["scenario_id"] is None:
        return None
    return (fields["scenario_id"], fields["list_id"], fields["count"])


def scope_of_input(d):
    if d is None:
        return None
    return (d["scenario_id"], d["list_id"], d["count"])


# ------------------------------------------------------------------------------------------------------------------------------------------------------------
def splitmix64_stream(seed):
    state = seed
    mask = 0xFFFFFFFFFFFFFFFF
    while True:
        state = (state + 0x9E3779B97F4A7C15) & mask
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
        yield z ^ (z >> 31)


def corpus_family_a(doc):
    """(bits, x) of the binary family: a random mantissa and an exponent in 2^-29 .. 2^30 (the sign from bit 63): exact in every language, no arithmetic."""
    gen = splitmix64_stream(int(doc["corpus"]["seed"], 16))
    out = []
    for _ in range(doc["corpus"]["family_a"]["count"]):
        z1, z2, z3 = next(gen), next(gen), next(gen)
        k = ((z2 >> 32) % 60) - 29
        sign = (z3 >> 63) & 1
        b = (sign << 63) | ((k + 1023) << 52) | (z1 & ((1 << 52) - 1))
        x = float_of("%016X" % b)
        if abs(x) > 1e9:
            continue
        out.append(("%016X" % b, x))
    return out


def corpus_family_b(doc):
    """(text) of the decimal family: up to 17 significant digits, a point at a random place (integers only: no float arithmetic)."""
    gen = splitmix64_stream(int(doc["corpus"]["seed"], 16) ^ 0x5555555555555555)
    out = []
    for _ in range(doc["corpus"]["family_b"]["count"]):
        z1, z2, z3 = next(gen), next(gen), next(gen)
        d = 1 + ((z1 >> 20) % 17)
        n = z2 % (10 ** d)
        frac = (z3 >> 24) % (d + 1)
        s = str(n)
        if frac > 0:
            s = s.zfill(frac + 1)
            s = s[:-frac] + "." + s[-frac:]
        if (z3 >> 63) & 1:
            s = "-" + s
        out.append(s)
    return out


# ============================================================================================================================================================
class A_RequestGrammar(unittest.TestCase):
    """N-18 JUMP-REQUEST-V2-GRAMMAR"""

    def test_N18_every_valid_request_vector_parses_to_the_typed_fields(self):
        jw, doc = load_module("N-18"), load_vectors("N-18")
        n = 0
        for v in doc["parse"]:
            if v["dir"] != "request" or not v["valid"]:
                continue
            with self.subTest(vector=v["id"]):
                got, reason = jw.parse_request(v["raw"])
                self.assertIsNone(reason)
                f = v["fields"]
                self.assertEqual((got.version, got.kind, got.station_index, got.time_ms), (v["version"], v["kind"], f["station_index"], f["time_ms"]))
                if f["location_bits"] is None:
                    self.assertIsNone(got.location)
                else:
                    self.assertEqual(bits_of(got.location), f["location_bits"])
                self.assertEqual(None if got.scope is None else tuple(got.scope), scope_tuple(f))
                n += 1
        self.assertGreaterEqual(n, 30)

    def test_N18_every_invalid_request_vector_gives_its_reason_word_and_no_message(self):
        jw, doc = load_module("N-18"), load_vectors("N-18")
        n = 0
        for v in doc["parse"]:
            if v["dir"] != "request" or v["valid"]:
                continue
            with self.subTest(vector=v["id"]):
                got, reason = jw.parse_request(v["raw"])
                self.assertIsNone(got)
                self.assertEqual(reason, v["reason"])
                self.assertIn(reason, jw.REASONS)
                n += 1
        self.assertGreaterEqual(n, 80)

    def test_N18_a_v2_request_is_exactly_seven_fields_and_the_request_id_is_not_one_of_them(self):
        jw = load_module("N-18")
        scope = (12345678, "E1D70409", 4)
        for kind, prefix in (("STA", "JUMP_STA_TIME"), ("LOC", "JUMP_LOC_TIME")):
            text, reason = jw.format_request_v2(kind, 2, 36060000, scope, 1000.5)
            self.assertIsNone(reason)
            parts = text.split(":")
            self.assertEqual(len(parts), 7, text)
            self.assertEqual(parts[0], prefix)
        sta, _ = jw.format_request_v2("STA", 2, 36060000, scope, 1000.5)
        loc, _ = jw.format_request_v2("LOC", 2, 36060000, scope, 1000.5)
        # STA: <idx>:<time>:<scenario>:<list>:<count>:<location>        LOC: <location>:<time>:<scenario>:<list>:<count>:<idx>
        self.assertEqual(sta.split(":")[1:], ["2", "36060000", "12345678", "E1D70409", "4", "1000.5"])
        self.assertEqual(loc.split(":")[1:], ["1000.5", "36060000", "12345678", "E1D70409", "4", "2"])
        got, reason = jw.parse_request(sta + ":0123456789ABCDEF0123456789ABCDEF")
        self.assertEqual((got, reason), (None, "field-count"))

    def test_N18_the_version_is_the_field_count_and_nothing_else_is_guessed(self):
        jw = load_module("N-18")
        scope = (1, "592BCC9A", 2)
        v2, _ = jw.format_request_v2("STA", 1, 0, scope, 5.0)
        v1 = "JUMP_STA_TIME:1:0"
        self.assertEqual(jw.parse_request(v2)[0].version, jw.V2)
        self.assertEqual(jw.parse_request(v1)[0].version, jw.V1)
        for n in (1, 2, 4, 5, 6, 8, 9, 11):
            text = ":".join(["JUMP_STA_TIME"] + ["1"] * (n - 1))
            self.assertEqual(jw.parse_request(text), (None, "field-count"), text)

    def test_N18_same_location_stations_keep_the_index_they_were_asked_for(self):
        jw, doc = load_module("N-18"), load_vectors("N-18")
        by_id = {v["id"]: v for v in doc["parse"]}
        for a, b in (("RQ-V2-STA-SAMELOC-A", "RQ-V2-STA-SAMELOC-B"), ("RQ-V2-LOC-SAMELOC-A", "RQ-V2-LOC-SAMELOC-B")):
            ra, rb = jw.parse_request(by_id[a]["raw"])[0], jw.parse_request(by_id[b]["raw"])[0]
            self.assertEqual(bits_of(ra.location), bits_of(rb.location))        # the same position
            self.assertEqual((ra.station_index, rb.station_index), (1, 2))      # a different station: never the smallest index with that position
            self.assertEqual(ra.scope, rb.scope)

    def test_N18_nearby_stations_keep_the_index_they_were_asked_for(self):
        jw, doc = load_module("N-18"), load_vectors("N-18")
        by_id = {v["id"]: v for v in doc["parse"]}
        ra = jw.parse_request(by_id["RQ-V2-STA-NEAR-A"]["raw"])[0]
        rb = jw.parse_request(by_id["RQ-V2-STA-NEAR-B"]["raw"])[0]
        self.assertLess(abs(rb.location - ra.location), 50.0)                   # inside the 50 m window of the old reselection
        self.assertEqual((ra.station_index, rb.station_index), (1, 2))

    def test_N18_the_codec_has_no_way_to_choose_a_station_by_position(self):
        jw = load_module("N-18")
        public = [n for n in dir(jw) if not n.startswith("_")]
        self.assertEqual([n for n in public if re.search(r"(?i)nearest|reselect|search|closest|by_position|station_list|find_station|pick", n)], [])
        import inspect
        for name in ("parse_request", "parse_completion", "format_request_v2", "format_completion_v2"):
            params = list(inspect.signature(getattr(jw, name)).parameters)
            self.assertEqual([p for p in params if re.search(r"(?i)list|stations", p)], [], name)

    def test_N18_format_vectors_of_the_request(self):
        jw, doc = load_module("N-18"), load_vectors("N-18")
        n = 0
        for v in doc["format"]:
            if v["dir"] != "request":
                continue
            with self.subTest(vector=v["id"]):
                i = v["input"]
                text, reason = jw.format_request_v2(i["kind"], i["station_index"], i["time_ms"], scope_of_input(i["scope"]), float_of(i["location_bits"]))
                if v["valid"]:
                    self.assertIsNone(reason)
                    self.assertEqual(text, v["text"])
                    back, r2 = jw.parse_request(text)
                    self.assertIsNone(r2)
                    self.assertEqual((back.station_index, back.time_ms), (i["station_index"], i["time_ms"]))
                else:
                    self.assertEqual((text, reason), (None, v["reason"]))
                n += 1
        self.assertGreaterEqual(n, 20)

    def test_N18_a_v2_request_text_is_ascii_without_whitespace(self):
        jw, doc = load_module("N-18"), load_vectors("N-18")
        for v in doc["format"]:
            if v["dir"] == "request" and v["valid"]:
                text, _ = jw.format_request_v2(v["input"]["kind"], v["input"]["station_index"], v["input"]["time_ms"], scope_of_input(v["input"]["scope"]), float_of(v["input"]["location_bits"]))
                self.assertRegex(text, r"\A[A-Za-z0-9_:.+\-]+\Z")


# ============================================================================================================================================================
class B_CompletionGrammar(unittest.TestCase):
    """N-19 JUMP-COMPLETE-V2-PARSE"""

    def test_N19_every_valid_completion_vector_parses_to_the_typed_fields(self):
        jw, doc = load_module("N-19"), load_vectors("N-19")
        n = 0
        for v in doc["parse"]:
            if v["dir"] != "completion" or not v["valid"]:
                continue
            with self.subTest(vector=v["id"]):
                got, reason = jw.parse_completion(v["raw"])
                self.assertIsNone(reason)
                f = v["fields"]
                self.assertEqual((got.version, got.kind, got.selected_idx, got.time_ms, got.jump_count), (v["version"], v["kind"], f["selected_idx"], f["time_ms"], f["jump_count"]))
                self.assertEqual(bits_of(got.location), f["location_bits"])
                self.assertEqual(None if got.scope is None else tuple(got.scope), scope_tuple(f))
                n += 1
        self.assertGreaterEqual(n, 14)

    def test_N19_every_invalid_completion_vector_is_malformed_with_its_reason_word(self):
        jw, doc = load_module("N-19"), load_vectors("N-19")
        n = 0
        for v in doc["parse"]:
            if v["dir"] != "completion" or v["valid"]:
                continue
            with self.subTest(vector=v["id"]):
                got, reason = jw.parse_completion(v["raw"])
                self.assertIsNone(got)
                self.assertEqual(reason, v["reason"])
                n += 1
        self.assertGreaterEqual(n, 45)

    def test_N19_a_v2_completion_is_exactly_nine_fields(self):
        jw = load_module("N-19")
        scope = (12345678, "E1D70409", 4)
        for kind in ("STA", "LOC"):
            text, reason = jw.format_completion_v2(kind, 2, 1000.5, 36060000, 1, scope)
            self.assertIsNone(reason)
            self.assertEqual(len(text.split(":")), 9)
            self.assertEqual(text.split(":")[:2], ["JUMP_COMPLETE", kind])
        text, _ = jw.format_completion_v2("STA", 2, 1000.5, 36060000, 1, scope)
        self.assertEqual(jw.parse_completion(text)[0].version, jw.V2)
        for n in (1, 2, 3, 4, 5, 7, 8, 10, 11):
            self.assertEqual(jw.parse_completion(":".join(["JUMP_COMPLETE", "STA"] + ["1"] * (n - 2))), (None, "field-count"), n)
        # the old Python reader accepted any text with >= 6 fields and ignored the rest; the v2 reader accepts 6 (v1) or 9 (v2) and nothing in between or above
        self.assertEqual(jw.parse_completion(text + ":1"), (None, "field-count"))

    def test_N19_the_selected_index_is_a_field_of_the_completion_and_never_minus_one(self):
        jw = load_module("N-19")
        scope = (1, "592BCC9A", 4)
        text, reason = jw.format_completion_v2("LOC", 3, 2000.0, 0, 0, scope)
        self.assertIsNone(reason)
        self.assertEqual(jw.parse_completion(text)[0].selected_idx, 3)
        self.assertEqual(jw.format_completion_v2("LOC", -1, 2000.0, 0, 0, scope), (None, "selected-idx-range"))
        self.assertEqual(jw.parse_completion("JUMP_COMPLETE:LOC:-1:2000:0:0:1:592BCC9A:4"), (None, "selected-idx-range"))
        self.assertEqual(jw.parse_completion("JUMP_COMPLETE:LOC:4:2000:0:0:1:592BCC9A:4"), (None, "selected-idx-range"))

    def test_N19_the_completion_status_is_exactly_STA_or_LOC(self):
        jw = load_module("N-19")
        for kind in ("SKIP", "sta", "loc", "OK", "", "STA ", "FAIL", "STAT"):
            self.assertEqual(jw.parse_completion("JUMP_COMPLETE:%s:1:1000:0:0:1:592BCC9A:4" % kind), (None, "kind"), kind)
            self.assertEqual(jw.format_completion_v2(kind, 1, 1000.0, 0, 0, (1, "592BCC9A", 4)), (None, "kind"), kind)

    def test_N19_format_vectors_of_the_completion(self):
        jw, doc = load_module("N-19"), load_vectors("N-19")
        n = 0
        for v in doc["format"]:
            if v["dir"] != "completion":
                continue
            with self.subTest(vector=v["id"]):
                i = v["input"]
                text, reason = jw.format_completion_v2(i["kind"], i["selected_idx"], float_of(i["location_bits"]), i["time_ms"], i["jump_count"], scope_of_input(i["scope"]))
                if v["valid"]:
                    self.assertIsNone(reason)
                    self.assertEqual(text, v["text"])
                    back, r2 = jw.parse_completion(text)
                    self.assertIsNone(r2)
                    self.assertEqual(back.selected_idx, i["selected_idx"])
                else:
                    self.assertEqual((text, reason), (None, v["reason"]))
                n += 1
        self.assertGreaterEqual(n, 14)


# ============================================================================================================================================================
class C_VectorParity(unittest.TestCase):
    """N-20 JUMP-WIRE-VECTOR-PARITY (the Python half; the C# half is Handshake/Tests/Test-JumpWireST3A.ps1 reading the SAME file)"""

    REQUIRED_CATEGORIES = (
        "RQ-V2-STA-01", "RQ-V2-LOC-01", "CP-V2-STA-CURRENT", "CP-V2-STA-LEGACY", "RQ-V2-STA-IDX0", "RQ-V2-STA-LAST", "RQ-V2-STA-SAMELOC-A", "RQ-V2-STA-SAMELOC-B",
        "RQ-V2-STA-NEAR-A", "RQ-V2-STA-NEAR-B", "RQ-V2-LOC-ZERO", "RQ-V2-LOC-NEG", "RQ-V2-STA-DECIMAL", "RQ-V2-STA-BIGKM", "RQ-V2-SCEN-MAX", "RQ-X-SCEN-NEGATIVE",
        "RQ-X-COUNT-ZERO", "RQ-X-LISTID-LOWER", "RQ-X-RID-APPENDED", "RQ-X-FC-4", "RQ-X-FC-11", "RQ-X-PREFIX-UNKNOWN", "RQ-X-IDX-ALPHA", "RQ-X-IDX-EQ-COUNT", "RQ-X-IDX-NEGATIVE",
        "RQ-X-LOC-NAN", "RQ-X-LOC-INF", "RQ-X-LOC-NEGINF", "RQ-X-LOC-COMMA", "RQ-X-LOC-TRAILING-GARBAGE", "RQ-X-EMPTY-LOC", "RQ-X-LOC-LEADING-SPACE", "RQ-X-LOC-EXP-NODIGITS",
        "RQ-X-DUP-SEP-B", "CP-X-KIND-SKIP", "CP-X-SEL-EQ-COUNT", "RQ-V1-STA-01", "RQ-V1-LOC-01", "CP-V1-STA-01", "CP-V1-LOC-MINUS1")

    def test_N20_the_table_is_well_formed(self):
        jw, doc = load_module("N-20"), load_vectors("N-20")
        self.assertEqual(doc["schema"], 1)
        ids = [v["id"] for v in doc["parse"]] + [v["id"] for v in doc["locations"]] + [v["id"] for v in doc["format"]] + [v["id"] for v in doc["numbers"]]
        self.assertEqual(len(ids), len(set(ids)))
        for v in doc["parse"]:
            self.assertEqual(v["valid"], v["reason"] is None, v["id"])
            self.assertIn(v["dir"], ("request", "completion"))
            if not v["valid"]:
                self.assertIn(v["reason"], doc["reasons"], v["id"])
        self.assertEqual(tuple(doc["reasons"]), tuple(jw.REASONS))
        self.assertEqual(doc["limits"]["int32_max"], jw.INT32_MAX)
        self.assertEqual(float_of(doc["limits"]["location_max_abs_bits"]), jw.LOCATION_MAX_ABS)
        self.assertEqual(float_of(doc["limits"]["location_min_abs_bits"]), jw.LOCATION_MIN_ABS)
        self.assertEqual(doc["limits"]["location_max_significant_digits"], jw.MAX_SIGNIFICANT_DIGITS)

    def test_N20_every_category_of_the_contract_is_in_the_table(self):
        load_module("N-20")
        doc = load_vectors("N-20")
        ids = set(v["id"] for v in doc["parse"])
        self.assertEqual([c for c in self.REQUIRED_CATEGORIES if c not in ids], [])

    def test_N20_every_reason_word_is_exercised_by_the_table(self):
        jw, doc = load_module("N-20"), load_vectors("N-20")
        seen = set(v["reason"] for v in doc["parse"] if not v["valid"]) | set(v["reason"] for v in doc["locations"] if not v["valid"]) | set(v["reason"] for v in doc["format"] if not v["valid"])
        self.assertEqual(sorted(set(jw.REASONS) - seen), [])

    def test_N20_the_python_codec_gives_the_table_verdict_for_every_message(self):
        jw, doc = load_module("N-20"), load_vectors("N-20")
        for v in doc["parse"]:
            with self.subTest(vector=v["id"]):
                fn = jw.parse_request if v["dir"] == "request" else jw.parse_completion
                got, reason = fn(v["raw"])
                self.assertEqual(got is not None, v["valid"])
                self.assertEqual(reason, v["reason"])
                if v["valid"] and v["canonical"] is not None:
                    self.assertEqual(self.rewrite(jw, got), v["canonical"])

    @staticmethod
    def rewrite(jw, got):
        if hasattr(got, "selected_idx"):
            return jw.format_completion_v2(got.kind, got.selected_idx, got.location, got.time_ms, got.jump_count, got.scope)[0]
        return jw.format_request_v2(got.kind, got.station_index, got.time_ms, got.scope, got.location)[0]

    def test_N20_the_python_codec_gives_the_table_verdict_for_every_location_text(self):
        jw, doc = load_module("N-20"), load_vectors("N-20")
        for v in doc["locations"]:
            with self.subTest(vector=v["id"]):
                got, reason = jw.parse_location(v["text"])
                self.assertEqual(reason, v["reason"])
                if v["valid"]:
                    self.assertEqual(bits_of(got), v["bits"])
                else:
                    self.assertIsNone(got)

    def test_N20_the_number_vectors_round_trip_through_the_python_formatter(self):
        jw, doc = load_module("N-20"), load_vectors("N-20")
        for v in doc["numbers"]:
            with self.subTest(vector=v["id"]):
                x = float_of(v["bits"])
                text, reason = jw.format_location(x)
                self.assertIsNone(reason)
                self.assertEqual(text, v["text"])
                back, r2 = jw.parse_location(text)
                self.assertIsNone(r2)
                self.assertEqual(bits_of(back), bits_of(0.0 if x == 0.0 else x))

    def test_N20_the_corpus_generator_matches_its_recorded_first_outputs(self):
        load_module("N-20")
        doc = load_vectors("N-20")
        gen = splitmix64_stream(int(doc["corpus"]["seed"], 16))
        self.assertEqual(["%016X" % next(gen) for _ in doc["corpus"]["reference"]], doc["corpus"]["reference"])

    def test_N20_the_csharp_half_exists_and_reads_the_same_table(self):
        load_module("N-20")
        if not os.path.isfile(PS_TEST_PATH):
            raise ContractViolation("N-20", "csharp-half-absent", "Handshake/Tests/Test-JumpWireST3A.ps1 does not exist")
        if not os.path.isfile(CS_PATH):
            raise ContractViolation("N-20", "csharp-jumpwire-absent", "Handshake/Telemetry/Shared/JumpWire.cs does not exist")
        ps = read_text(PS_TEST_PATH)
        self.assertIn("jump_wire_vectors.json", ps)
        self.assertIn("JumpWire.cs", ps)
        self.assertNotRegex(ps, r"[^\x00-\x7f]")                                                       # the PS test is ASCII only on purpose

    def test_N20_the_csharp_twin_is_host_independent(self):
        load_module("N-20")
        if not os.path.isfile(CS_PATH):
            raise ContractViolation("N-20", "csharp-jumpwire-absent", "Handshake/Telemetry/Shared/JumpWire.cs does not exist")
        code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", read_text(CS_PATH), flags=re.S))
        self.assertNotRegex(code, r"BveEx|BveEX|AtsEx|AtsEX|Legacy|Caller|Handshake|BveHacker|System\.IO|System\.Net|System\.Threading|System\.Reflection|System\.Diagnostics|File\.|Directory\.")
        self.assertNotRegex(code, r"54321|54322")
        for banned in ("$\"", "?.", " out var ", "=> "):
            self.assertNotIn(banned, code, "C# 5 syntax only: " + banned)
        for fmt in ('"G15"', '"G16"', '"G17"'):                                                          # the verified formats (the BCL "R" is not exact on .NET Framework)
            self.assertIn(fmt, code)
        self.assertNotIn('"R"', code)
        self.assertIn("CultureInfo.InvariantCulture", code)


# ============================================================================================================================================================
class D_SingleBuilder(unittest.TestCase):
    """N-21a START-AND-RETRY-SHARE-THE-BUILDER (the codec half; N-21b - the two call sites - is ST-3d)"""

    def test_N21a_the_wire_text_is_assembled_in_exactly_two_functions(self):
        load_module("N-21a")
        tree = ast.parse(read_text(MODULE_PATH))
        assemblers = []
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
                    assemblers.append(fn.name)
                    break
        self.assertEqual(sorted(set(assemblers)), ["format_completion_v2", "format_request_v2"])

    def test_N21a_the_command_words_are_module_constants_and_not_literals_elsewhere(self):
        load_module("N-21a")
        tree = ast.parse(read_text(MODULE_PATH))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                docstrings.add(id(node.body[0].value))
        hits = [(n.lineno, n.value) for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and re.search(r"JUMP_(STA|LOC)_TIME|JUMP_COMPLETE", n.value)]
        top = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for t in node.targets:
                    top[t.id] = node.value.value
        self.assertEqual([top.get(k) for k in ("PREFIX_STA", "PREFIX_LOC", "PREFIX_COMPLETE")], ["JUMP_STA_TIME", "JUMP_LOC_TIME", "JUMP_COMPLETE"])
        # the only code literals that spell a command word are the three constants themselves
        self.assertEqual(sorted(v for _ln, v in hits), ["JUMP_COMPLETE", "JUMP_LOC_TIME", "JUMP_STA_TIME"], hits)
    def test_N21a_start_and_retry_cannot_be_told_apart_by_the_codec(self):
        jw = load_module("N-21a")
        import inspect
        for name in ("format_request_v2", "format_completion_v2", "parse_request", "parse_completion"):
            self.assertEqual([p for p in inspect.signature(getattr(jw, name)).parameters if re.search(r"(?i)start|retry|role|official|checkpoint", p)], [], name)
        self.assertEqual([n for n in dir(jw) if re.search(r"(?i)start|retry|checkpoint|official", n)], [])
        scope = (3, "0A0B0C0D", 3)
        a = jw.format_request_v2("STA", 2, 36060000, scope, 1040.5)
        b = jw.format_request_v2("STA", 2, 36060000, scope, 1040.5)
        self.assertEqual(a, b)

    def test_N21a_the_codec_is_wired_into_the_product_by_the_transaction_layer_and_its_two_readers_only(self):
        load_module("N-21a")
        users = []
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".py") and name != "jump_wire.py" and "jump_wire" in read_text(os.path.join(ROOT, name)):
                users.append(name)
        # Phase ST-3d (was: "not wired into any product module yet"; N-21b, the two call sites, is executed in tests/test_stationindex_python_st3d.py): the transaction layer writes the
        # request, the scoring logic needs its command words, the Overlay reads the completion; nothing else knows the codec
        self.assertEqual(users, ["jump_transaction.py", "main.py", "scoring_logic.py"])


# ============================================================================================================================================================
class E_Numbers(unittest.TestCase):
    LOCATION_CANONICAL = re.compile(r"\A-?(0|[1-9][0-9]*)(\.[0-9]+)?(E[+-][0-9]{2,})?\Z")

    def test_the_location_range_is_inclusive_at_both_ends_and_closed_beyond(self):
        jw = load_module("N-E")
        self.assertEqual(jw.LOCATION_MAX_ABS, 1.0e9)
        self.assertEqual(jw.LOCATION_MIN_ABS, 1.0e-9)
        self.assertEqual(jw.MAX_SIGNIFICANT_DIGITS, 17)
        for x in (1e9, -1e9, 1e-9, -1e-9, 0.0):
            self.assertEqual(jw.normalize_location(x)[1], None, x)
        for x in (math.nextafter(1e9, math.inf), math.nextafter(-1e9, -math.inf), math.nextafter(1e-9, 0.0), 5e-324, 1.7976931348623157e308):
            self.assertEqual(jw.normalize_location(x), (None, "location-range"), repr(x))
        for x in (math.nan, math.inf, -math.inf):
            self.assertEqual(jw.normalize_location(x), (None, "location-range"), repr(x))
        for bad in (None, "1.0", True, False, [1.0], b"1"):
            self.assertEqual(jw.normalize_location(bad), (None, "location-syntax"), repr(bad))
        self.assertEqual(jw.normalize_location(3), (3.0, None))

    def test_minus_zero_is_normalised_to_plus_zero_everywhere(self):
        jw = load_module("N-E")
        self.assertEqual(bits_of(jw.normalize_location(-0.0)[0]), "0000000000000000")
        for text in ("-0", "-0.0", "-0e5", "-0.000", "0", "0.0"):
            self.assertEqual(bits_of(jw.parse_location(text)[0]), "0000000000000000", text)
        self.assertEqual(jw.format_location(-0.0), ("0", None))
        self.assertEqual(jw.format_location(0.0), ("0", None))

    def test_the_formatter_writes_the_canonical_form_only(self):
        jw = load_module("N-E")
        for x in (0.0, 0.1, 0.01, 0.34, 1.0, 1234.5678, 1.2345678901234567, 123456.789, -50.5, 999999999.0, 1e9, 1e-9, 1.5e-5, 0.0001, 98765.43210987654, 2.0 ** -20):
            text, reason = jw.format_location(x)
            self.assertIsNone(reason)
            self.assertRegex(text, self.LOCATION_CANONICAL)
            self.assertNotIn("e", text)
            self.assertFalse(text.endswith(".0"))
            self.assertEqual(bits_of(jw.parse_location(text)[0]), bits_of(x))

    def test_every_location_the_parser_accepts_is_the_correctly_rounded_double(self):
        jw, doc = load_module("N-E"), load_vectors("N-E")
        for v in doc["locations"]:
            if v["valid"]:
                with self.subTest(vector=v["id"]):
                    self.assertEqual(bits_of(jw.parse_location(v["text"])[0]), bits_of(float(v["text"]) + 0.0))

    def test_corpus_a_binary_doubles_survive_format_and_parse_bit_for_bit(self):
        jw, doc = load_module("N-E"), load_vectors("N-E")
        corpus = corpus_family_a(doc)
        self.assertGreater(len(corpus), 15000)
        bad = []
        for b, x in corpus:
            text, reason = jw.format_location(x)
            back, r2 = jw.parse_location(text) if text is not None else (None, "format")
            if reason is not None or r2 is not None or bits_of(back) != bits_of(x + 0.0):
                bad.append((b, text, reason, r2))
        self.assertEqual(bad[:5], [])

    def test_corpus_b_decimal_texts_are_read_as_python_float_reads_them(self):
        jw, doc = load_module("N-E"), load_vectors("N-E")
        texts = corpus_family_b(doc)
        valid = 0
        bad = []
        for text in texts:
            got, reason = jw.parse_location(text)
            if reason is not None:
                self.assertIn(reason, ("location-range", "location-precision"), text)
                continue
            valid += 1
            if bits_of(got) != bits_of(float(text) + 0.0):
                bad.append(text)
            again, r2 = jw.format_location(got)
            if r2 is not None or bits_of(jw.parse_location(again)[0]) != bits_of(got):
                bad.append(("format", text))
        self.assertGreater(valid, 3000)
        self.assertEqual(bad[:5], [])

    def test_a_correct_parse_differs_from_the_net_framework_parse_on_these_values(self):
        # the evidence behind the codec's own exact parser (C#): .NET Framework Double.Parse / "R" are NOT correctly rounded for these texts (measured on the build machine)
        jw, doc = load_module("N-E"), load_vectors("N-E")
        by_id = {v["id"]: v for v in doc["numbers"]}
        for vid in ("NUM-NET-PARSE-1", "NUM-NET-PARSE-2", "NUM-NET-PARSE-3", "NUM-NET-R-1", "NUM-NET-R-2", "NUM-NET-R-3", "NUM-NET-R-4"):
            v = by_id[vid]
            self.assertEqual(bits_of(jw.parse_location(v["text"])[0]), v["bits"])
            self.assertEqual(jw.format_location(float_of(v["bits"])), (v["text"], None))

    def test_the_codec_uses_no_locale_and_no_locale_dependent_formatting(self):
        load_module("N-E")
        code = read_text(MODULE_PATH)
        tree = ast.parse(code)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= set(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertNotIn("locale", imported)
        self.assertNotRegex(code, r"\{[A-Za-z0-9_.\[\]]*:[^}\"']*n\}|setlocale|localeconv|format\(.*['\"]n['\"]")
        try:
            import locale
            saved = locale.setlocale(locale.LC_ALL)
            try:
                for name in ("German_Germany.1252", "de_DE.UTF-8", "French_France.1252", "fr_FR.UTF-8"):
                    try:
                        locale.setlocale(locale.LC_ALL, name)
                    except Exception:
                        continue
                    jw = load_module("N-E")
                    self.assertEqual(jw.format_location(1234.5), ("1234.5", None))
                    self.assertEqual(bits_of(jw.parse_location("1234.5")[0]), bits_of(1234.5))
                    self.assertEqual(jw.parse_location("1234,5"), (None, "location-syntax"))
            finally:
                locale.setlocale(locale.LC_ALL, saved)
        except Exception as exc:                                                                         # no comma locale installed: the static check above is the proof
            if isinstance(exc, AssertionError):
                raise


# ============================================================================================================================================================
class F_Scope(unittest.TestCase):
    def test_the_scope_type_is_the_station_identity_scope(self):
        jw = load_module("N-F")
        import station_identity
        scope, reason = jw.validate_scope(12345678, "E1D70409", 4)
        self.assertIsNone(reason)
        self.assertIsInstance(scope, station_identity.StationScope)
        self.assertEqual(scope, (12345678, "E1D70409", 4))

    def test_scope_boundaries(self):
        jw = load_module("N-F")
        M = jw.INT32_MAX
        ok = [(0, "00000000", 1), (M, "FFFFFFFF", M), (1, "0123ABCD", 2)]
        for s in ok:
            self.assertEqual(jw.validate_scope(*s)[1], None, s)
        bad = [((-1, "E1D70409", 4), "scenario-id-range"), ((M + 1, "E1D70409", 4), "scenario-id-range"), ((1, "E1D70409", 0), "count-range"), ((1, "E1D70409", -1), "count-range"),
               ((1, "E1D70409", M + 1), "count-range"), ((1, "e1d70409", 4), "list-id-syntax"), ((1, "E1D7040", 4), "list-id-syntax"), ((1, "E1D704090", 4), "list-id-syntax"),
               ((1, "E1D7040G", 4), "list-id-syntax"), ((1, "", 4), "list-id-syntax"), ((1, None, 4), "list-id-syntax"), ((1, "E1D70409 ", 4), "list-id-syntax"),
               ((1.0, "E1D70409", 4), "scenario-id-syntax"), ((None, "E1D70409", 4), "scenario-id-syntax"), ((True, "E1D70409", 4), "scenario-id-syntax"),
               ((1, "E1D70409", 4.0), "count-syntax"), ((1, "E1D70409", None), "count-syntax"), ((1, "E1D70409", True), "count-syntax")]
        for args, reason in bad:
            self.assertEqual(jw.validate_scope(*args), (None, reason), args)

    def test_a_missing_scope_is_not_a_v2_message(self):
        jw = load_module("N-F")
        self.assertEqual(jw.format_request_v2("STA", 0, 0, None, 1.0), (None, "scope-incomplete"))
        self.assertEqual(jw.format_completion_v2("STA", 0, 1.0, 0, 0, None), (None, "scope-incomplete"))
        self.assertEqual(jw.format_request_v2("STA", 0, 0, (1, "E1D70409"), 1.0), (None, "scope-incomplete"))

    def test_the_index_is_always_checked_against_the_count_of_the_scope(self):
        jw = load_module("N-F")
        for count in (1, 2, 4, 100):
            self.assertEqual(jw.format_request_v2("STA", count - 1, 0, (1, "E1D70409", count), 1.0)[1], None)
            self.assertEqual(jw.format_request_v2("STA", count, 0, (1, "E1D70409", count), 1.0), (None, "station-index-range"))
            self.assertEqual(jw.format_request_v2("STA", -1, 0, (1, "E1D70409", count), 1.0), (None, "station-index-range"))


# ============================================================================================================================================================
def legacy_python_completion_reader(text):
    """A transcription of main.py read_udp_data (the JUMP_COMPLETE branch) - the reader that has existed until ST-3d. The test below pins that the transcription is still what the source says."""
    if not text.startswith("JUMP_COMPLETE:"):
        return None
    parts = text.split(":")
    if len(parts) >= 6:
        try:
            return {"type": parts[1], "station_index": int(parts[2]), "location": float(parts[3]), "time": int(parts[4]), "jump_count": int(parts[5])}
        except ValueError:
            return None
    return None


class G_V1Compatibility(unittest.TestCase):
    def test_the_legacy_python_reader_in_main_py_is_gone_the_completion_is_read_by_the_codec(self):
        """Phase ST-3d (was: "the legacy Python reader in main.py is what this file transcribes"): the inline split / int / float reader of the JUMP_COMPLETE text no longer exists; the
        completion is read by jump_wire.parse_completion in the settlement, and a v1 text is a reason word there, never a success."""
        main = read_text(os.path.join(ROOT, "main.py"))
        i = main.index('elif text.startswith("JUMP_COMPLETE:"):')
        block = main[i:i + 200]
        self.assertNotIn("complete_parts", main)
        self.assertIn("self._note_jump_complete(text)", block)
        self.assertEqual(main.count("jump_wire.parse_completion("), 1)

    def test_v1_vectors_parse_as_version_1_without_scope(self):
        jw, doc = load_module("N-G"), load_vectors("N-G")
        n = 0
        for v in doc["parse"]:
            if v["valid"] and v["version"] == 1:
                fn = jw.parse_request if v["dir"] == "request" else jw.parse_completion
                got, reason = fn(v["raw"])
                self.assertIsNone(reason, v["id"])
                self.assertEqual((got.version, got.scope), (1, None), v["id"])
                n += 1
        self.assertGreaterEqual(n, 13)

    def test_a_v1_request_can_not_be_mistaken_for_an_identity_carrying_message(self):
        jw = load_module("N-G")
        sta = jw.parse_request("JUMP_STA_TIME:2:36060000")[0]
        loc = jw.parse_request("JUMP_LOC_TIME:1000.5:36060000")[0]
        self.assertEqual((sta.version, sta.scope, sta.location), (1, None, None))
        self.assertEqual((loc.version, loc.scope, loc.station_index), (1, None, None))               # v1 LOC never carried an index
        v1c = jw.parse_completion("JUMP_COMPLETE:LOC:-1:2000:36200000:3")[0]
        self.assertEqual((v1c.version, v1c.selected_idx, v1c.scope), (1, -1, None))

    def test_there_is_no_v1_writer(self):
        jw = load_module("N-G")
        self.assertEqual([n for n in dir(jw) if re.search(r"(?i)v1", n) and callable(getattr(jw, n))], [])
        self.assertEqual([n for n in dir(jw) if n.startswith("format_")], ["format_completion_v2", "format_location", "format_request_v2"])

    def test_the_v1_reader_accepts_what_the_legacy_python_reader_accepts_on_formal_input(self):
        jw, doc = load_module("N-G"), load_vectors("N-G")
        for v in doc["parse"]:
            if v["dir"] == "completion" and v["valid"] and v["version"] == 1:
                with self.subTest(vector=v["id"]):
                    old = legacy_python_completion_reader(v["raw"])
                    new = jw.parse_completion(v["raw"])[0]
                    self.assertIsNotNone(old)
                    self.assertEqual((old["type"], old["station_index"], old["time"], old["jump_count"]), (new.kind, new.selected_idx, new.time_ms, new.jump_count))
                    self.assertEqual(bits_of(old["location"] + 0.0), bits_of(new.location))

    def test_where_the_legacy_python_reader_was_lax_the_codec_is_strict_and_the_difference_is_recorded(self):
        jw = load_module("N-G")
        scope_tail = ":12345678:E1D70409:4"
        lax = [
            ("a v2 completion read as v1 (the extra fields were ignored)", "JUMP_COMPLETE:STA:2:1000.5:36060000:1" + scope_tail, True, True),     # the codec reads it as v2: accepted, with the scope
            ("a 7 field completion (the 7th ignored)", "JUMP_COMPLETE:STA:2:1000.5:36060000:1:x", True, False),
            ("whitespace in a number", "JUMP_COMPLETE:STA: 2:1000.5:36060000:1", True, False),
            ("a plus sign", "JUMP_COMPLETE:STA:+2:1000.5:36060000:1", True, False),
            ("a leading zero", "JUMP_COMPLETE:STA:02:1000.5:36060000:1", True, False),
            ("an underscore (Python only)", "JUMP_COMPLETE:STA:2:1_000.5:36060000:1", True, False),
            ("inf", "JUMP_COMPLETE:STA:2:inf:36060000:1", True, False),
            ("nan", "JUMP_COMPLETE:STA:2:nan:36060000:1", True, False),
            ("an unknown kind", "JUMP_COMPLETE:XYZ:2:1000.5:36060000:1", True, False),
        ]
        for label, text, old_accepts, new_accepts in lax:
            with self.subTest(case=label):
                self.assertEqual(legacy_python_completion_reader(text) is not None, old_accepts)
                self.assertEqual(jw.parse_completion(text)[0] is not None, new_accepts)


# ============================================================================================================================================================
class H_Purity(unittest.TestCase):
    ALLOWED_IMPORTS = {"re", "math", "types", "typing", "station_identity"}

    def test_the_module_imports_nothing_but_the_pure_standard_library_and_the_scope_type(self):
        load_module("N-H")
        tree = ast.parse(read_text(MODULE_PATH))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= set(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(sorted(imported - self.ALLOWED_IMPORTS), [])

    def test_the_module_does_no_io_and_keeps_no_mutable_global_state(self):
        load_module("N-H")
        source = read_text(MODULE_PATH)
        tree = ast.parse(source)
        self.assertEqual([n.lineno for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))], [])
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        self.assertEqual(sorted(names & {"open", "print", "socket", "input", "exec", "eval", "__import__", "time", "datetime", "random", "os", "sys", "environ", "getenv"}), [])
        for node in tree.body:                                                                  # module level: constants, compiled patterns, functions, types - no list / dict / set
            if isinstance(node, ast.Assign):
                self.assertNotIsInstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp), ast.dump(node)[:80])
        for forbidden in ("PyQt6", "main", "scoring_logic", "managed_input", "current_jump_client", "dataplane_contract", "station_index_contract"):
            self.assertNotRegex(source, r"(?m)^\s*(import|from)\s+%s\b" % forbidden)

    def test_the_results_are_immutable(self):
        jw = load_module("N-H")
        req = jw.parse_request("JUMP_STA_TIME:2:36060000:12345678:E1D70409:4:1000.5")[0]
        with self.assertRaises(AttributeError):
            req.station_index = 3
        comp = jw.parse_completion("JUMP_COMPLETE:STA:2:1000.5:36060000:1:12345678:E1D70409:4")[0]
        with self.assertRaises(AttributeError):
            comp.selected_idx = 3
        self.assertIsInstance(req, tuple)
        self.assertIsInstance(comp, tuple)

    def test_the_functions_never_raise_for_a_bad_input(self):
        jw = load_module("N-H")
        weird = [None, "", 0, 1.5, b"JUMP_STA_TIME:1:2", [], {}, "\x00", "JUMP_STA_TIME:" + "9" * 5000, ":" * 500, "JUMP_STA_TIME:1:2:3:4:5:" + "1" * 10000, "\ud800", "JUMP_COMPLETE:" + ":".join(["9" * 400] * 8)]
        for w in weird:
            for fn in (jw.parse_request, jw.parse_completion, jw.parse_location, jw.normalize_location, jw.format_location):
                got = fn(w)
                self.assertEqual(len(got), 2)
                self.assertTrue((got[0] is None) != (got[1] is None) or got[0] is not None)
        self.assertEqual(jw.parse_request(None), (None, "empty"))
        self.assertEqual(jw.format_request_v2(None, None, None, None, None)[0], None)
        self.assertEqual(jw.format_completion_v2("STA", "x", "y", [], {}, 5)[0], None)

    def test_a_long_garbage_text_is_refused_in_bounded_time(self):
        jw = load_module("N-H")
        import time as _t
        t0 = _t.perf_counter()
        for text in ("JUMP_STA_TIME:1:2:3:E1D70409:4:" + "9" * 200000, "JUMP_LOC_TIME:" + "1e" * 100000 + ":0:1:E1D70409:4:1", "1" + "0" * 100000 + "e-99999999999"):
            jw.parse_request(text)
            jw.parse_location(text)
        self.assertLess(_t.perf_counter() - t0, 2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
