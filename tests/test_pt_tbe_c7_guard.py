"""Stage TB-E 1.1 (OD-TE2-3): the C7 GUARD is STRUCTURAL. The helper pt_tbe_c7_structure compares the code of the PTPAIR chain of the C# senders with the exact formal statements; these tests prove that
the formal files pass and that every kind of deviation the Owner named is a violation:
  an unknown telemetry line, a malformed PTPAIR, a duplicate PTPAIR, a PTPAIR at a wrong position, a station count / pair count that does not match, a list id / generation that does not belong to the line,
  and unrelated code that merely contains the word PTPAIR.
The mutants are made in memory from the real source text (each must APPLY exactly once: an inapplicable mutant is an error, never a pass)."""
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

import pt_tbe_c7_structure as S


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def base_session():
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (S.BASE_COMMIT, S.SESSION)], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def mutate(text, old, new, count=1):
    """The mutant must apply exactly `count` times."""
    n = text.count(old)
    if n != count:
        raise AssertionError("the mutant does not apply: %d x %r" % (n, old[:60]))
    return text.replace(old, new)


def mutate_re(text, pattern, new):
    result, n = re.subn(pattern, new, text, count=1, flags=re.S)
    if n != 1:
        raise AssertionError("the mutant does not apply: %r" % pattern[:60])
    return result


class A_TheFormalFilesPass(unittest.TestCase):
    def test_the_session_adds_exactly_the_formal_two_lines_to_the_LC4b_file(self):
        base = base_session()
        if base is None:
            self.skipTest("cbebfd3 is not known to this checkout")
        self.assertEqual(S.session_violations(base, read(S.SESSION)), [])

    def test_the_session_alone_has_exactly_one_formal_key_at_the_formal_place(self):
        self.assertEqual(S.session_violations(None, read(S.SESSION)), [])

    def test_the_timeline_chain_is_the_formal_chain(self):
        self.assertEqual(S.timeline_violations(read(S.TIMELINE)), [])

    def test_the_current_sender_chain_is_the_formal_chain(self):
        self.assertEqual(S.current_violations(read(S.CURRENT)), [])

    def test_the_codec_states_the_stations_and_the_pairs_of_the_set_it_encodes(self):
        self.assertEqual(S.codec_violations(read(S.CODEC)), [])

    def test_the_line_ending_of_the_texts_does_not_matter_to_the_guard(self):
        base = base_session()
        self.assertEqual(S.session_violations(None if base is None else base.replace("\n", "\r\n"), read(S.SESSION).replace("\n", "\r\n")), [])
        self.assertEqual(S.timeline_violations(read(S.TIMELINE).replace("\n", "\r\n")), [])
        self.assertEqual(S.current_violations(read(S.CURRENT).replace("\n", "\r\n")), [])


class B_TheLegacySessionRefusesWhatIsNotTheFormalKey(unittest.TestCase):
    def setUp(self):
        self.base = base_session()
        self.text = read(S.SESSION)
        self.key_line = [l for l in self.text.split("\n") if S.SESSION_KEY in l.strip()][0]

    def violations(self, mutant):
        return S.session_violations(self.base, mutant) or S.session_violations(None, mutant)

    def test_an_unknown_telemetry_line_with_a_TB_E_marker_is_refused(self):
        m = mutate(self.text, self.key_line, self.key_line + '\n                    lb.Key("EXTRA", "1");   // TB-E')
        self.assertTrue(self.violations(m))

    def test_an_unknown_telemetry_line_without_any_marker_is_refused(self):
        m = mutate(self.text, self.key_line, self.key_line + '\n                    lb.Key("EXTRA", "1");')
        self.assertTrue(self.violations(m))

    def test_a_malformed_PTPAIR_value_is_refused(self):
        m = mutate(self.text, 'lb.Key("PTPAIR", timeline.PtPairText.Substring("PTPAIR:".Length));', 'lb.Key("PTPAIR", "1:BAD");')
        self.assertTrue(self.violations(m))

    def test_a_PTPAIR_value_that_keeps_the_key_name_inside_is_refused(self):
        m = mutate(self.text, 'Substring("PTPAIR:".Length)', "Substring(0)")
        self.assertTrue(self.violations(m))

    def test_a_malformed_PTPAIR_key_name_is_refused(self):
        m = mutate(self.text, 'lb.Key("PTPAIR", timeline', 'lb.Key("PTPAIR2", timeline')
        self.assertTrue(self.violations(m))

    def test_a_duplicate_PTPAIR_is_refused(self):
        m = mutate(self.text, self.key_line, self.key_line + "\n" + self.key_line)
        self.assertTrue(self.violations(m))

    def test_a_PTPAIR_at_a_wrong_position_inside_the_official_block_is_refused(self):
        m = mutate(self.text, self.key_line + "\n", "")
        m = mutate(m, "lb.Key(OfficialTargetWire.Key, officialValue);", self.key_line.strip() + "\n                        lb.Key(OfficialTargetWire.Key, officialValue);")
        self.assertTrue(self.violations(m))

    def test_a_PTPAIR_before_the_STIDX_statement_is_refused(self):
        m = mutate(self.text, self.key_line + "\n", "")
        m = mutate(m, '"TERM", TelemetryContract.I(sv.Term),', '"TERM", TelemetryContract.I(sv.Term),\n                        "PTPAIR", "x",')
        self.assertTrue(self.violations(m))

    def test_a_missing_PTPAIR_is_refused(self):
        m = mutate(self.text, self.key_line + "\n", "")
        self.assertTrue(S.session_violations(None, m))

    def test_an_unrelated_line_that_merely_contains_the_word_is_refused(self):
        m = mutate(self.text, self.key_line, self.key_line + '\n                    string unusedPtpair = "PTPAIR"; // TB-E PtPairText')
        self.assertTrue(self.violations(m))

    def test_a_comment_that_hides_a_changed_statement_is_refused(self):
        m = mutate(self.text, "if (official != null)", "if (official != null && timeline.Count > 0) // PTPAIR TB-E")
        self.assertTrue(self.violations(m))

    def test_a_removed_line_of_the_end_of_the_LC4b_file_is_refused(self):
        m = mutate(self.text, "if (official != null)", "if (official == null)")
        self.assertTrue(self.violations(m))


class C_TheTimelineChainIsTheFormalChain(unittest.TestCase):
    def setUp(self):
        self.text = read(S.TIMELINE)

    def test_a_station_count_that_does_not_match_the_list_is_refused(self):
        m = mutate_re(self.text, r"(ptRecords = new List<PseudoTurnbackRecord>\(list\.Count\);\s*for \(int i = 0; i < list\.Count)(; i\+\+\))", r"\1 - 1\2")
        self.assertTrue(S.timeline_violations(m))

    def test_a_record_capacity_that_does_not_match_the_list_is_refused(self):
        m = mutate(self.text, "new List<PseudoTurnbackRecord>(list.Count)", "new List<PseudoTurnbackRecord>(list.Count + 1)")
        self.assertTrue(S.timeline_violations(m))

    def test_a_list_id_that_does_not_belong_to_the_list_is_refused(self):
        m = mutate(self.text, "PseudoTurnbackPairCodec.Publish(ptRecords, listId)", "PseudoTurnbackPairCodec.Publish(ptRecords, StationListIdentity.EmptyId)")
        self.assertTrue(S.timeline_violations(m))

    def test_a_part_text_that_survives_the_reset_is_refused(self):
        m = mutate(self.text, "ptRecords = null; ptPairText = null;", "ptRecords = null;")
        self.assertTrue(S.timeline_violations(m))

    def test_a_part_text_made_before_the_list_identity_is_refused(self):
        line = "ptPairText = list.Count > 0 ? PseudoTurnbackPairCodec.Publish(ptRecords, listId) : null;"
        m = mutate_re(self.text, r"[ \t]*" + re.escape(line) + r"[^\n]*\n", "")
        m = mutate(m, "string payload = ComposeStaList();", line + "\n            string payload = ComposeStaList();")
        self.assertTrue(S.timeline_violations(m))

    def test_a_second_record_source_is_refused(self):
        m = mutate(self.text, "ptRecords.Add(new PseudoTurnbackRecord(list[i].RawArrTime > 0,", "ptRecords.Add(new PseudoTurnbackRecord(list[i].RawDepTime > 0,")
        self.assertTrue(S.timeline_violations(m))

    def test_an_unrelated_line_that_names_the_codec_is_refused(self):
        m = mutate(self.text, "private string ptPairText;", 'private string ptPairText;\n        private string unusedPtpair = "PTPAIR";')
        self.assertTrue(S.timeline_violations(m))


class D_TheCurrentSenderChainIsTheFormalChain(unittest.TestCase):
    def setUp(self):
        self.text = read(S.CURRENT)
        self.append = 'if (ptpairText != null) data += "," + ptpairText;'

    def test_a_duplicate_part_is_refused(self):
        m = mutate(self.text, self.append + "   // Phase TB-E: the PTPAIR part, same condition as STIDX", self.append + "\n                        " + self.append)
        self.assertTrue(S.current_violations(m))

    def test_an_unknown_telemetry_part_is_refused(self):
        m = mutate(self.text, self.append, self.append + '\n                        data += ",PTX:1:0";')
        self.assertTrue(S.current_violations(m))

    def test_a_malformed_part_is_refused(self):
        m = mutate(self.text, self.append, 'if (ptpairText != null) data += "," + "PTPAIR:1:00000000:0:0:";')
        self.assertTrue(S.current_violations(m))

    def test_a_part_outside_the_STIDX_condition_is_refused(self):
        m = mutate(self.text, "                        " + self.append + "   // Phase TB-E: the PTPAIR part, same condition as STIDX\n", "")
        m = mutate(m, "// Phase ST-1A: the STIDX part, appended as a part of its own", self.append + "\n                    // Phase ST-1A: the STIDX part, appended as a part of its own")
        self.assertTrue(S.current_violations(m))

    def test_a_station_count_that_does_not_match_the_list_is_refused(self):
        m = mutate_re(self.text, r"(ptRecords = new List<TSScoringPlugin\.Telemetry\.PseudoTurnbackRecord>\(stationList\.Count\);\s*for \(int i = 0; i < stationList\.Count)(; i\+\+\))", r"\1 - 1\2")
        self.assertTrue(S.current_violations(m))

    def test_a_list_id_that_does_not_belong_to_the_list_is_refused(self):
        m = mutate(self.text, "PseudoTurnbackPairCodec.Publish(ptRecords, stidxListId)", 'PseudoTurnbackPairCodec.Publish(ptRecords, "00000000")')
        self.assertTrue(S.current_violations(m))

    def test_a_part_text_that_survives_a_reset_is_refused(self):
        m = mutate_re(self.text, r"ptRecords = null; ptpairText = null;", "ptRecords = null;")
        self.assertTrue(S.current_violations(m))

    def test_an_unrelated_line_that_merely_contains_the_word_is_refused(self):
        m = mutate(self.text, "private string ptpairText = null;", 'private string ptpairText = null;\n        private string unusedPtpair = "PTPAIR";')
        self.assertTrue(S.current_violations(m))


class E_TheCodecStatesTheCountsOfTheSetItEncodes(unittest.TestCase):
    def setUp(self):
        self.text = read(S.CODEC)

    def test_a_pair_count_that_does_not_match_is_refused(self):
        m = mutate(self.text, 'set.Count.ToString(CultureInfo.InvariantCulture) + ":" + sb.ToString()', '(set.Count + 1).ToString(CultureInfo.InvariantCulture) + ":" + sb.ToString()')
        self.assertTrue(S.codec_violations(m))

    def test_a_station_count_that_does_not_match_is_refused(self):
        m = mutate(self.text, 'set.StationCount.ToString(CultureInfo.InvariantCulture) + ":" + set.Count', '(set.StationCount + 1).ToString(CultureInfo.InvariantCulture) + ":" + set.Count')
        self.assertTrue(S.codec_violations(m))

    def test_a_publish_that_encodes_another_set_is_refused(self):
        m = mutate(self.text, "Encode(PseudoTurnbackQualifier.Qualify(records), listId)", "Encode(PseudoTurnbackQualifier.Qualify(records), PseudoTurnbackPairCodec.EmptyListId)")
        self.assertTrue(S.codec_violations(m))

    def test_a_decode_that_does_not_compare_the_declared_pair_count_is_refused(self):
        m = mutate(self.text, "if (items.Count != pairCount) { reason = ReasonCount; return null; }", "")
        self.assertTrue(S.codec_violations(m))


class F_TheProjectsCompileWhatTheSendersUse(unittest.TestCase):
    """The probe project compiles the Legacy sources directly, so it must compile the shared sources they now use (the same rule as StationListIdentity.cs: test_stationindex_supply_st1a)."""
    PROJECTS = ("TsScoringPlugin/TsScoringPlugin/TsScoringPlugin.csproj",
                "TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.csproj",
                "TsScoringPlugin/Handshake/Tests/B1Probe/TSScoringPlugin.AtsExLegacy.Telemetry.B1Probe.csproj")

    def test_every_project_that_compiles_a_sender_includes_the_qualifier_and_the_codec_once(self):
        for path in self.PROJECTS:
            text = read(path)
            for name in ("PseudoTurnbackQualifier.cs", "PseudoTurnbackPairCodec.cs"):
                self.assertEqual(len(re.findall(r'Compile Include="[^"]*Shared\\' + re.escape(name) + '"', text)), 1, (path, name))
                self.assertNotIn("PseudoTurnbackStaging", text, path)

    def test_the_sources_are_in_the_shared_folder_and_the_staging_folder_is_gone(self):
        for name in ("PseudoTurnbackQualifier.cs", "PseudoTurnbackPairCodec.cs"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "Shared", name)))
            self.assertFalse(os.path.exists(os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "PseudoTurnbackStaging", name)))


if __name__ == "__main__":
    unittest.main()
