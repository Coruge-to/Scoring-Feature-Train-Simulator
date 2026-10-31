"""Stage TB-E (C): the sources. (1) The qualification of a pair lives ONLY in the shared C# Qualifier (OD-TE-6): no Python module of the product qualifies a pair, and the Python intake names none of the things that
a pair must never be derived from (station name, position, distance, door, signal flag, nearest station, the NEXTLOC target, the time display, adjacency). (2) Current and Legacy differ only in how they collect the
five raw values (OD-TE-2): one shared Publish, one wire, the same carrying condition as STIDX, no Qualify / Encode call in an adapter. (3) The wiring of the lifecycle hooks of the Python side.
Source-shape guards in the style of the Current C# source pins (Current cannot run offline); the Legacy and the shared sources are also executed offline by Test-PseudoTurnbackQualifier.ps1."""
import ast
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TEL = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry")
CURRENT = os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def functions(source, names):
    tree = ast.parse(source)
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names}


def code_lines(text):
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


class A_ThePythonSideNeverQualifies(unittest.TestCase):
    FORBIDDEN_WORDS = ("name", "location", "distance", "door", "signal", "nearest", "nextloc", "next_loc", "timetable", "adjacen", "is_pass", "raw_arr", "raw_dep", "is_terminal", "terminal")

    def test_the_intake_module_exists_and_imports_only_the_decoder(self):
        src = read(ROOT, "route_pairset.py")
        tree = ast.parse(src)
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                imported.add((n.module or "").split(".")[0])
        # Stage TB-E 1.1 (intended update; was the decoder and typing only): the diagnostic summary needs hashlib (the short fingerprint) and re (the one safe list id form). Still no qualifier, no station module.
        self.assertLessEqual(imported, {"pseudo_turnback_contract", "typing", "hashlib", "re"})

    def test_the_intake_names_nothing_a_pair_must_never_be_derived_from(self):
        src = read(ROOT, "route_pairset.py")
        tree = ast.parse(src)
        idents = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                idents.append(n.id)
            elif isinstance(n, ast.Attribute):
                idents.append(n.attr)
            elif isinstance(n, ast.arg):
                idents.append(n.arg)
            elif isinstance(n, ast.FunctionDef):
                idents.append(n.name)
        for ident in idents:
            for word in self.FORBIDDEN_WORDS:
                self.assertNotIn(word, ident.lower(), "route_pairset names %r" % ident)

    def test_the_intake_reads_no_attribute_or_key_by_a_forbidden_word(self):
        tree = ast.parse(read(ROOT, "route_pairset.py"))
        keys = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
                keys.append(n.slice.value)
            if isinstance(n, ast.Call):
                fn = n.func
                called = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if called in ("getattr", "get", "hasattr") and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
                    keys.append(n.args[1].value)
                if called == "get" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    keys.append(n.args[0].value)
        for key in keys:
            for word in self.FORBIDDEN_WORDS:
                self.assertNotIn(word, key.lower(), "route_pairset reads %r" % key)

    def test_the_intake_never_walks_the_station_list(self):
        tree = ast.parse(read(ROOT, "route_pairset.py"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name):
                self.assertNotIn(n.value.id, ("station_list", "stations", "sl"))
            if isinstance(n, (ast.For, ast.comprehension)):
                it = n.iter
                if isinstance(it, ast.Name):
                    self.assertNotIn(it.id, ("station_list", "stations", "sl"))

    def test_no_python_module_of_the_product_has_a_function_that_qualifies_a_pair(self):
        allowed = {"qualifying_pair"}                                  # the use conditions PU-1..PU-5 of an already certified pair, not a qualification
        for name in sorted(os.listdir(ROOT)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(read(ROOT, name))
            for n in ast.walk(tree):
                if isinstance(n, ast.FunctionDef) and re.search(r"qualif|find_pair|derive_pair|make_pair|build_pairs|detect_pair", n.name, re.I):
                    self.assertIn(n.name, allowed, "%s defines %s" % (name, n.name))

    def test_the_intake_is_the_only_caller_of_set_pairset_in_the_product(self):
        callers = []
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".py") and name != "pseudo_turnback_machine.py":
                if re.search(r"\.set_pairset\(", read(ROOT, name)):
                    callers.append(name)
        self.assertEqual(callers, ["route_pairset.py"])


class B_TheLifecycleWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = read(ROOT, "main.py")
        cls.tree = ast.parse(cls.main)

    def fn(self, name):
        for n in ast.walk(self.tree):
            if isinstance(n, (ast.FunctionDef,)) and n.name == name:
                return ast.get_source_segment(self.main, n)
        self.fail("no function " + name)

    def test_every_applied_line_is_followed_by_the_sync(self):
        self.assertIn("_route_pairset_sync()", self.fn("read_udp_data"))
        self.assertIn("_route_pairset_sync()", self.fn("apply_held_telemetry"))

    def test_the_sync_is_after_the_station_list_is_adopted(self):
        seg = self.fn("read_udp_data")
        self.assertLess(seg.index("self.station_list = committed"), seg.index("_route_pairset_sync()"))
        seg = self.fn("apply_held_telemetry")
        self.assertLess(seg.index("self.station_list = held"), seg.index("_route_pairset_sync()"))

    def test_the_line_is_captured_where_the_parts_are_split(self):
        seg = self.fn("apply_telemetry_text")
        self.assertIn("route_pairset.capture(parts)", seg)

    def test_the_new_instance_the_new_generation_the_session_and_the_shutdown_invalidate(self):
        self.assertIn("route_pairset.clear(", self.fn("reset_telemetry_state"))
        self.assertIn("route_pairset.clear(", self.fn("apply_telemetry_text"))
        self.assertIn("route_pairset.clear(", self.fn("_release_overlay"))

    def test_the_generation_drop_names_the_holder(self):
        import managed_input
        self.assertIn("route_pairset", managed_input.GENERATION_DROP)

    def test_the_start_gate_names_the_unavailable_state(self):
        src = read(ROOT, "managed_input.py")
        self.assertIn("pairset-unavailable", src)
        seg = src[src.index("def start_blockers"):src.index("def start_gate")]
        self.assertIn("route_pairset", seg)

    def test_the_vocabulary_of_the_telemetry_line_names_the_part(self):
        import telemetry_contract
        self.assertIn("PTPAIR", telemetry_contract.TOKEN_KEYS["station"])


class C_TheSharedSourcesAndTheTwoAdapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codec = read(TEL, "Shared", "PseudoTurnbackPairCodec.cs")
        cls.qual = read(TEL, "Shared", "PseudoTurnbackQualifier.cs")
        cls.cur = read(CURRENT, "Class1.cs")
        cls.leg = read(TEL, "Legacy", "src", "LegacyStationTimeline.cs")
        cls.leg_session = read(TEL, "Legacy", "src", "LegacyTelemetrySession.cs")
        cls.cur_proj = read(CURRENT, "TsScoringPlugin.csproj")
        cls.leg_proj = read(TEL, "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")

    def test_the_staging_folder_is_gone_and_the_sources_are_shared(self):
        self.assertFalse(os.path.exists(os.path.join(TEL, "PseudoTurnbackStaging")))
        for f in ("PseudoTurnbackQualifier.cs", "PseudoTurnbackPairCodec.cs"):
            self.assertTrue(os.path.exists(os.path.join(TEL, "Shared", f)), f)

    def test_both_projects_compile_both_shared_sources(self):
        for proj in (self.cur_proj, self.leg_proj):
            for f in ("PseudoTurnbackQualifier.cs", "PseudoTurnbackPairCodec.cs"):
                self.assertRegex(proj, r'<Compile Include="[^"]*Shared\\' + re.escape(f) + '"')

    def test_there_is_one_publish_and_it_is_total(self):
        self.assertEqual(len(re.findall(r"public static string Publish\(", self.codec)), 1)
        body = self.codec[self.codec.index("public static string Publish("):]
        body = body[:body.index("\n        }\n")]
        self.assertIn("try", body)
        self.assertIn("catch", body)
        self.assertIn("return null", body)

    def test_each_adapter_calls_publish_once_and_neither_qualifies_nor_encodes(self):
        for label, src in (("Current", self.cur), ("Legacy", self.leg)):
            code = code_lines(src)
            self.assertEqual(len(re.findall(r"PseudoTurnbackPairCodec\.Publish\(", code)), 1, label)
            self.assertNotIn("PseudoTurnbackQualifier.Qualify", code, label)
            self.assertNotIn("PseudoTurnbackPairCodec.Encode", code, label)
            self.assertNotIn("PseudoTurnbackPairSet", code, label)

    def test_each_adapter_hands_over_exactly_the_five_raw_values(self):
        for label, src, names in (("Current", self.cur, "stationList"), ("Legacy", self.leg, "list")):
            code = code_lines(src)
            calls = re.findall(r"new (?:TSScoringPlugin\.Telemetry\.)?PseudoTurnbackRecord\(([^;]*)\)\);", code)
            self.assertEqual(len(calls), 1, label)
            used = set(re.findall(r"\b(Raw\w+|IsTerminal|IsPass|Location|Name|Door\w*|Time\w*|Stoppage\w*|Margin\w*|IsScoring|HasTimeDef|DefaultTime)\b", calls[0]))
            self.assertEqual(used, {"RawArrTime", "RawDepTime", "IsTerminal", "IsPass"}, label)

    def test_the_seam_is_after_the_first_terminal_is_kept_and_before_the_last_station_becomes_the_terminal(self):
        for label, src, kept, last in (
                ("Current", self.cur, "explicitTerminalFound = true", "if (!explicitTerminalFound && stationList.Count > 0)"),
                ("Legacy", self.leg, "explicitTerminalFound = true", "if (!explicitTerminalFound && list.Count > 0)")):
            i_kept = src.index(kept)
            i_rec = re.search(r"new (?:TSScoringPlugin\.Telemetry\.)?PseudoTurnbackRecord\(", src).start()
            i_last = src.index(last)
            self.assertLess(i_kept, i_rec, label)
            self.assertLess(i_rec, i_last, label)

    def test_the_current_part_is_carried_under_the_condition_of_the_stidx_part(self):
        i = self.cur.index('data += ",STIDX:1:"')
        j = self.cur.index('ptpairText', i)
        k = self.cur.index("OfficialTargetWire.Value(", i)
        self.assertLess(i, j)
        self.assertLess(j, k)
        guard = self.cur.rindex("if (isInitialized && stidxListReady && stidxListCount == stationList.Count)", 0, i)
        self.assertLess(guard, i)
        self.assertEqual(len(re.findall(r'",\s*"\s*\+\s*ptpairText|","\s*\+\s*ptpairText', self.cur)), 1)

    def test_the_current_state_is_cleared_where_the_list_identity_is(self):
        resets = [m.start() for m in re.finditer(r"^\s+stidxListId = TSScoringPlugin\.Telemetry\.StationListIdentity\.EmptyId;", self.cur, re.M)]
        self.assertGreaterEqual(len(resets), 2)
        for pos in resets:
            self.assertIn("ptpairText = null", self.cur[pos:pos + 400])

    def test_the_legacy_part_is_a_key_of_the_station_group_after_stidx_and_is_cleared_with_the_list(self):
        self.assertIn('"PTPAIR"', self.leg_session)
        self.assertLess(self.leg_session.index('"STIDX"'), self.leg_session.index('"PTPAIR"'))
        self.assertIn("PtPairText", self.leg_session)
        for m in re.finditer(r"^\s+listId = StationListIdentity\.EmptyId;", self.leg, re.M):
            self.assertIn("ptPairText = null", self.leg[m.start():m.start() + 300])

    def test_the_shared_sources_know_no_host_and_no_forbidden_input(self):
        for label, src in (("codec", self.codec), ("qualifier", self.qual)):
            code = code_lines(src)
            for bad in ("door", "signal", "distance", "location", "speed", "Math.Abs", "BveEx", "AtsEx", "dynamic"):
                self.assertFalse(re.search(bad, code, re.I), "%s has %s" % (label, bad))


if __name__ == "__main__":
    unittest.main()
