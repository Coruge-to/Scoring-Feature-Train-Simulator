"""Phase JF-1 (file F3) - SOURCE-SHAPE PINS of the Current plugin (TsScoringPlugin\\TsScoringPlugin\\Class1.cs and CurrentJumpEndpoint.cs), the current link set of the
Legacy telemetry project, and the register of the items that only a real BVE observation can settle (JF-0 v2 groups C (Current side), J20 (static part), the C#
half of X06, and the facts F-11, F-12, F-28, F-32).

WHY ONLY TEXT: Class1.cs depends on the BveEX host and can not be compiled or run offline, and under the J3 constraint it must not be changed. JF-0 v2 section 1
(T3') therefore fixes it by its SOURCE: a pin reads the file and checks the SHAPE of the statements that make a behaviour what it is. A pin is NOT a run of the
behaviour. Nothing here compiles, loads or executes C#; the files are only read.

THE NAMES MEAN (JF-0 v2 test specification, section 0.2 and section 1 rule 7):
    test_CURRENT_...          today's neutral shape
    test_CURRENT_DANGER_...   a shape that makes a KNOWN dangerous behaviour. Passing it does NOT mean the behaviour is safe or an approved contract. Every one
                              carries (see jf0()) the JF-0 v2 id, what is dangerous, the phase that turns it into its TARGET, and the condition under which the
                              pin is reversed or deleted.
    test_TARGET_A_/_B_...     the future contract; ALL are skipped in JF-1, the reason names the contract id; the expectation is the contract's, never weakened.
    test_MANUAL_...           an observation that needs the real BVE (JF-0 v2 L-1 ... L-9, U-1). It has NO assertion and is NOT an automated pass: it is a skip
                              whose reason starts with 'requires BVE observation'. No expectation is recorded for it.
A skip is never counted as a pass.

THE CLASS1.CS DRIFT GUARD (test_CURRENT_DRIFT_class1_cs_is_the_audited_revision_...) - a JF-1 guard of THIS FILE ONLY. It is NOT a substitute for the pin P5 of the
other test files, and a matching hash alone proves no contract: the individual shape pins below stay in force and are the evidence.
    hash      : SHA-256 over the NORMALISED text
    normalise : (1) decode the file as UTF-8, dropping a leading BOM; (2) replace every CRLF and every lone CR by LF; (3) encode as UTF-8. Nothing else (comments,
                trailing blanks and the final newline are kept). At the audited revision the raw and the normalised hash are the same (LF, no BOM).
    the hash MUST NOT BE UPDATED MECHANICALLY. When Class1.cs is changed on purpose (JF-3, the J3 limited release), first re-audit the changed lines, the shape pins
    below, the contract and the regression range, record that, and only then set the new value.

ISOLATION: files are only read (Class1.cs, CurrentJumpEndpoint.cs, the Legacy csproj, two Python sources). No socket, no process, no write, no Desktop, no Downloads.
"""
import hashlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CLASS1 = os.path.join(PLUGIN, "TsScoringPlugin", "Class1.cs")
ENDPOINT = os.path.join(PLUGIN, "TsScoringPlugin", "CurrentJumpEndpoint.cs")
DATAPLANE = os.path.join(PLUGIN, "TsScoringPlugin", "CurrentDataPlane.cs")
LEGACY_CSPROJ = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")

CLASS1_AUDITED_NORMALISED_SHA256 = "29613E1495667222990B1FB8D197415BE4988869CA3F2C3CFD7810EAAEA1F4F6"

OWN_IDS = ["C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12", "C13", "C15", "C16", "C17", "J20", "X06", "F11", "F12", "F32", "DRIFT",
           "L1", "L2", "L3", "L4", "L5", "L6", "L8", "L9", "U1", "F28"]
# (F11 / F12 / F28 / F32 stand for the facts F-11, F-12, F-32 of JF-0 v2; DRIFT is the guard above; L7 is NOT here: it is an automated REACH test in file F1)


def jf0(case_id, kind, danger=None, phase=None, flip=None):
    """Attach the JF-0 v2 metadata to a test method. kind: CURRENT | CURRENT_DANGER | TARGET | MANUAL."""
    def deco(fn):
        fn.jf0 = {"id": case_id, "kind": kind, "danger": danger, "phase": phase, "flip": flip}
        return fn
    return deco


def danger(case_id, what, phase, flip):
    return jf0(case_id, "CURRENT_DANGER", danger=what, phase=phase, flip=flip)


# ----------------------------------------------------------------------------------------------------------------------------------------------
_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def strip_comments(text):
    """C# source without // and /* */ comments; string literals are kept as they are."""
    return _TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else " ", text)


def squash(text):
    return re.sub(r"\s+", " ", text)


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


def code(path):
    return squash(strip_comments(read_text(path).replace("\r\n", "\n").replace("\r", "\n")))


def normalised_sha256(path):
    with open(path, "rb") as f:
        text = f.read().decode("utf-8-sig")
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest().upper()


class Pins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c1 = code(CLASS1)
        cls.ep = code(ENDPOINT)
        cls.dp = code(DATAPLANE)
        # the two command branches and the stretch before the telemetry values (C# of Class1.cs, squashed)
        i_sta = cls.c1.index('if (msg.StartsWith("JUMP_STA_TIME:"))')
        i_loc = cls.c1.index('else if (msg.StartsWith("JUMP_LOC_TIME:"))')
        i_end = cls.c1.index("double speed = 0.0;")
        cls.sta_branch = cls.c1[i_sta:i_loc]
        cls.loc_branch = cls.c1[i_loc:i_end]
        cls.jump_loop = cls.c1[cls.c1.index("foreach (JumpInput jumpInput in CollectJumpCommands())"):i_end]
        cls.init_loop = re.search(r"for \(int i = 0; i < stationList\.Count; i\+\+\) \{ if \(stationList\[i\]\.Location >= location - 50\.0\) \{ (.*?) \} \} isInitialized = true; \}",
                                  cls.c1)

    # -- the drift guard -------------------------------------------------------------------------------------------------------------------------
    @jf0("DRIFT", "CURRENT")
    def test_CURRENT_DRIFT_class1_cs_is_the_audited_revision_normalised_sha256(self):
        """See the module docstring: LF-normalised UTF-8 SHA-256, never to be updated mechanically; the shape pins below remain the evidence."""
        self.assertEqual(normalised_sha256(CLASS1), CLASS1_AUDITED_NORMALISED_SHA256,
                         "Class1.cs changed: re-audit the changed lines, every pin of this file, the contract and the regression range BEFORE touching this value")

    # -- C02 / C03 / C17 / X06 : the target station is chosen again by POSITION after a jump ---------------------------------------------------------
    def test_CURRENT_pins_found_the_initialisation_loop(self):
        self.assertIsNotNone(self.init_loop, "the initialisation loop of the target station is not in the audited shape")
        self.assertIn("targetStationIndex = i;", self.init_loop.group(1))
        self.assertIn("break;", self.init_loop.group(1))

    @danger("C02", "after a jump to station B at the SAME position as station A (A earlier in the list) the sender's target is A: the first station whose location is not "
                   "more than 50 m behind the vehicle wins, so the requested B is never the target",
            "JF-2 (TARGET-A V-4: such a request is refused in advance) / JF-3 (TARGET-B B2: the requested index is kept)", "the target is the requested index; this pin is replaced by TARGET_B_C02")
    def test_CURRENT_DANGER_C02_the_first_station_in_range_wins_so_the_second_of_two_same_position_stations_is_never_the_target(self):
        body = self.init_loop.group(1)
        self.assertEqual(len(re.findall(r"targetStationIndex = i;", body)), 1)
        self.assertRegex(body, r"targetStationIndex = i; hasDoorOpenedAtTarget = [^;]+; break;$")           # the first hit ends the search
        self.assertNotIn("sIdx", body)                                                                       # the requested index plays no part

    @danger("C03", "the 50 m range is INCLUSIVE ('>='): a station exactly 50 m behind the jump position is chosen as target instead of the requested one",
            "JF-2 (TARGET-A V-4 extended: refused in advance, boundary included) / JF-3 (TARGET-B B2)", "the requested index is kept; this pin is replaced by TARGET_B_C03")
    def test_CURRENT_DANGER_C03_the_back_range_of_50_m_is_inclusive(self):
        self.assertIn("if (stationList[i].Location >= location - 50.0)", self.c1)
        self.assertNotIn("stationList[i].Location > location - 50.0", self.c1)

    @jf0("C04", "CURRENT")
    def test_CURRENT_C04_the_door_open_detection_uses_100_m_and_the_initial_state_uses_50_m(self):
        self.assertIn("if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true;", self.c1)
        self.assertIn("hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[i].Location - location) < 50.0;", self.init_loop.group(1))

    @jf0("C05", "CURRENT")
    def test_CURRENT_C05_when_no_station_is_in_range_the_target_index_is_left_as_it_was(self):
        """Current has no 'no next station' value: after the loop the code only sets isInitialized (the Legacy timeline sets target = Count)."""
        self.assertNotRegex(self.c1, r"targetStationIndex = (stationList\.Count|-1)")
        self.assertRegex(self.c1, r"break; \} \} isInitialized = true; \}")

    @danger("C17", "a station 40 m BEHIND the requested one (not at the same position) is also chosen as target: the requested station is never the target while that earlier "
                   "station is within 50 m",
            "JF-2 (TARGET-A V-4 extended: refused in advance) / JF-3 (TARGET-B B2)", "the requested index is kept; this pin is replaced by TARGET_B_C17")
    def test_CURRENT_DANGER_C17_the_requested_index_is_only_echoed_and_never_feeds_the_target(self):
        self.assertEqual(len(re.findall(r"\bsIdx\b", self.c1)), 3)                       # the TryParse, the Invoke argument, the echo for the completion text
        self.assertIn("pendingJumpStationIndex = sIdx;", self.sta_branch)
        self.assertNotRegex(self.c1, r"targetStationIndex = (sIdx|pendingJumpStationIndex)")

    @danger("X06", "(C# half of the chain) the STA branch re-initialises the target state and then announces completion with the REQUESTED index, while the target itself is chosen by position "
                   "afterwards: Python's completion check can not see which station the sender really targets",
            "JF-2 (TARGET-A V-4) / JF-3 (TARGET-B B2, B3 / K7)", "the sender keeps the requested index and reports the next index; this pin is replaced")
    def test_CURRENT_DANGER_X06_the_completion_is_announced_after_a_position_based_reinitialisation(self):
        branch = self.sta_branch
        self.assertLess(branch.index("isInitialized = false;"), branch.index("pendingJumpComplete = true;"))
        self.assertLess(branch.index("pendingJumpComplete = true;"), branch.index("pendingJumpStationIndex = sIdx;"))
        # the re-selection by position happens in the NEXT initialisation pass (isInitialized == false), not in the jump branch
        self.assertNotIn("targetStationIndex", branch)

    # -- C06 - C10 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("C06", "CURRENT")
    def test_CURRENT_C06_a_request_without_a_scenario_is_skipped_silently_with_no_completion(self):
        self.assertEqual(self.sta_branch.count("if (scenario == null) continue;"), 1)
        self.assertEqual(self.loc_branch.count("if (scenario == null) continue;"), 1)
        self.assertLess(self.sta_branch.index("if (scenario == null) continue;"), self.sta_branch.index("pendingJumpComplete = true;"))
        self.assertLess(self.loc_branch.index("if (scenario == null) continue;"), self.loc_branch.index("pendingJumpComplete = true;"))

    @danger("C07", "if the jump method is not found the call is skipped but the completion is STILL announced: the sender reports a jump that did not happen",
            "JF-2 (TARGET-A K4: the position check catches it) / JF-3 (TARGET-B B4, B7: no completion, a failure response)", "no completion without a jump; this pin is replaced")
    def test_CURRENT_DANGER_C07_a_missing_jump_method_does_not_prevent_the_completion(self):
        self.assertRegex(self.sta_branch, r"if \(jumpStaMethod != null\) \{ jumpStaMethod\.Invoke\( rawScenario, new object\[\] \{ sIdx \} \); \}")
        self.assertRegex(self.loc_branch, r"if \(jumpMethod != null\) \{ jumpMethod\.Invoke\(rawScenario, new object\[\] \{ rLoc, 0 \}\); \}")
        for branch, pattern in ((self.sta_branch, r"if \(jumpStaMethod != null\) \{ jumpStaMethod\.Invoke\( rawScenario, new object\[\] \{ sIdx \} \); \}"),
                                (self.loc_branch, r"if \(jumpMethod != null\) \{ jumpMethod\.Invoke\(rawScenario, new object\[\] \{ rLoc, 0 \}\); \}")):
            # the completion statement is NOT inside the 'method found' block: it comes after that block is closed
            self.assertGreater(branch.index("pendingJumpComplete = true;"), re.search(pattern, branch).end())

    @jf0("C08", "CURRENT")
    def test_CURRENT_C08_an_exception_of_the_jump_call_ends_in_an_empty_catch_and_no_completion(self):
        for branch in (self.sta_branch, self.loc_branch):
            self.assertLess(branch.index("Invoke("), branch.index("pendingJumpComplete = true;"))
            self.assertRegex(branch, r"pendingJumpStationIndex = (sIdx|-1); \} \} \} catch \{ \} \} \}")

    @danger("C09", "if the time field ('c') of the time manager is not found, the time is not set but the completion is still announced (with the current time)",
            "JF-3 (TARGET-B B4: a failure response instead)", "no completion without the time being set; this pin is replaced by TARGET_B_C09")
    def test_CURRENT_DANGER_C09_a_missing_time_field_does_not_prevent_the_completion(self):
        for branch in (self.sta_branch, self.loc_branch):
            self.assertIn('GetField("c", bindFlagsAll)', branch)
            self.assertIn("if (timeField != null && rTimeMs >= 0) timeField.SetValue(rawTimeMgr, rTimeMs);", branch)
            self.assertLess(branch.index("timeField.SetValue"), branch.index("pendingJumpComplete = true;"))

    @jf0("C10", "CURRENT")
    def test_CURRENT_C10_the_completion_is_sent_only_when_initialised_and_stays_pending_until_the_send_succeeds(self):
        self.assertIn("if (pendingJumpComplete && isInitialized)", self.c1)
        sent = re.search(r"if \(batch\.SendJumpComplete\(completeBytes, pendingJumpRequestId\)\) \{ pendingJumpComplete = false; pendingJumpRequestId = null; pendingJumpType = \"\"; "
                         r"pendingJumpStationIndex = -1; \}", self.c1)
        self.assertIsNotNone(sent)
        self.assertEqual(len(re.findall(r"(?<!bool )pendingJumpComplete = false;", self.c1)), 1)         # the only place that clears the pending flag (the declaration excepted)

    @jf0("C11", "CURRENT")
    def test_CURRENT_C11_the_requested_station_index_is_passed_on_without_any_range_check(self):
        parse = 'int.TryParse(parts[1], out int sIdx) && int.TryParse(parts[2], out int rTimeMs)'
        self.assertIn(parse, self.sta_branch)
        self.assertNotRegex(self.sta_branch, r"sIdx\s*(<|>|<=|>=)\s*|(<|>|<=|>=)\s*sIdx\b|Count")

    # -- C12 / C13 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("C12", "CURRENT")
    def test_CURRENT_C12_a_location_jump_does_not_reinitialise_the_target_state_itself(self):
        """Estimate (JF-0 v2): a LOC jump relies on the time-discontinuity check; it never sets isInitialized = false in its own branch."""
        self.assertNotIn("isInitialized", self.loc_branch)
        self.assertIn("isInitialized = false;", self.sta_branch)

    @jf0("C13", "CURRENT")
    def test_CURRENT_C13_the_jump_counter_counts_time_discontinuities_of_more_than_300_ms(self):
        self.assertEqual(len(re.findall(r"jumpCounter\+\+;", self.c1)), 1)
        self.assertRegex(self.c1, r"if \(lastTimeMs != 0 && Math\.Abs\(jumpTimeErrorMs\) > 300\) \{ isInitialized = false;[^}]*jumpCounter\+\+; \}")

    # -- C15 -------------------------------------------------------------------------------------------------------------------------------------
    @danger("C15", "a scenario change does not reset the target index: a stale index of the previous scenario can survive and, if no station is in range, is used (or points past the new list)",
            "JF-3 (TARGET-B B6: reset to 0 and 'no next station' unified)", "the index is reset on a scenario change; this pin is replaced by TARGET_B_C15")
    def test_CURRENT_DANGER_C15_the_target_index_survives_a_scenario_change(self):
        block = re.search(r"if \(!object\.Equals\(currentScenario, BveHacker\.Scenario\)\) \{(.*?)initialStaListSent = false; lastStaListSendTime = DateTime\.MinValue; \}", self.c1)
        self.assertIsNotNone(block)
        self.assertIn("isInitialized = false;", block.group(1))
        self.assertNotIn("targetStationIndex", block.group(1))
        writes = re.findall(r"targetStationIndex\s*(\+\+|=(?!=))", self.c1)
        self.assertEqual(sorted(writes), sorted(["=", "=", "++", "++", "++"]))         # the declaration, the position search, three advances: no reset anywhere

    # -- C16 / F28 / F11 -------------------------------------------------------------------------------------------------------------------------
    @danger("C16", "the location of a LOC command is parsed with the CURRENT CULTURE, while the endpoint's validator uses the invariant culture: on a culture with ',' as decimal "
                   "separator a validated command can fail to run (silently, then a timeout)",
            "JF-3 (TARGET-B B10: InvariantCulture); whether it happens on a real machine is L-8", "the culture is fixed; this pin is replaced by TARGET_B_C16")
    def test_CURRENT_DANGER_C16_the_loc_command_location_is_parsed_without_a_culture(self):
        self.assertIn("double.TryParse(parts[1], out double rLoc)", self.loc_branch)
        self.assertNotIn("CultureInfo", self.loc_branch)
        self.assertIn("Double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out location)", self.ep)

    @jf0("F28", "CURRENT")
    def test_CURRENT_F28_the_sta_command_parts_are_parsed_without_a_culture_too_but_integers_are_culture_safe_in_practice(self):
        self.assertIn("int.TryParse(parts[1], out int sIdx)", self.sta_branch)
        self.assertIn("Int32.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out index)", self.ep)

    @jf0("F11", "CURRENT")
    def test_CURRENT_F11_the_completion_text_formats_the_location_with_the_current_culture(self):
        """Estimate (JF-0 v2 F-11): the interpolation of a double has no culture, so a ',' culture would write '1000,5'. The Python side then fails to parse it (see file F2 J15)."""
        self.assertIn('$"JUMP_COMPLETE:{pendingJumpType}" + $":{pendingJumpStationIndex}" + $":{completedLocation}" + $":{completedTime}" + $":{jumpCounter}"', self.c1)
        text = self.c1[self.c1.index('string completeMessage ='):self.c1.index("byte[] completeBytes")]
        self.assertNotIn("CultureInfo", text)
        self.assertNotIn("ToString(", text)

    # -- F12 : one slot, several commands per Tick -------------------------------------------------------------------------------------------------
    @jf0("F12", "CURRENT")
    def test_CURRENT_F12_every_command_of_a_tick_is_run_and_only_one_pending_slot_exists(self):
        self.assertNotIn("break;", self.jump_loop)                                  # the loop never stops after the first command
        self.assertEqual(len(re.findall(r"private bool pendingJumpComplete\b", self.c1)), 1)
        self.assertEqual(len(re.findall(r"private byte\[\] pendingJumpRequestId\b", self.c1)), 1)
        self.assertEqual(len(re.findall(r"pendingJumpRequestId = jumpRequestId;", self.c1)), 2)      # STA and LOC both overwrite the same slot

    # -- J20 (static) ----------------------------------------------------------------------------------------------------------------------------
    @danger("J20", "no failure response exists in the sender: not in Class1.cs, not in the endpoint, not in the data plane; an unrunnable jump is only ever noticed by Python's 10 s timeout",
            "JF-3 (TARGET-B B7 / FC-7 JUMP_FAILED)", "a failure message exists; this pin is replaced by TARGET_B_J20")
    def test_CURRENT_DANGER_J20_the_sender_has_no_failure_response(self):
        for name, text in (("Class1.cs", self.c1), ("CurrentJumpEndpoint.cs", self.ep), ("CurrentDataPlane.cs", self.dp)):
            self.assertNotIn("JUMP_FAILED", text, name)
            self.assertNotIn("JumpFailed", text, name)
        self.assertEqual(len(re.findall(r'"JUMP_COMPLETE:', self.c1)), 1)                                      # the only jump message the sender writes

    # -- F32 : the Legacy project's link set -------------------------------------------------------------------------------------------------------
    @jf0("F32", "CURRENT")
    def test_CURRENT_F32_the_legacy_telemetry_project_links_exactly_this_set_of_sources_and_not_the_current_jump_endpoint(self):
        text = read_text(LEGACY_CSPROJ)
        items = sorted(re.findall(r'<Compile Include="([^"]+)"', text))
        self.assertEqual(items, sorted([
            "src\\AssemblyInfo.cs", "src\\LegacyApi.cs", "..\\..\\..\\TsScoringPlugin\\CurrentDataPlane.cs", "src\\LegacyDataPlaneSink.cs", "src\\LegacyGroundLimits.cs",
            "src\\LegacyHandleContract.cs", "..\\Shared\\GenericHandleTextContract.cs", "src\\LegacyInputProbe.cs", "..\\Shared\\DataPlaneProtocol.cs",
            "..\\Shared\\TelemetryDirectoryReader.cs", "src\\LegacyInputTelemetry.cs", "src\\LegacyScoringProbe.cs", "src\\LegacyStationTimeline.cs",
            "src\\LegacyTelemetrySession.cs", "src\\LegacyTelemetryExtension.cs", "..\\Shared\\TelemetryContract.cs"]))
        self.assertNotIn("CurrentJumpEndpoint", re.sub(r"<!--.*?-->", "", text, flags=re.S))


# ==============================================================================================================================================
class Targets(unittest.TestCase):
    """TARGET expectations (all skipped in JF-1), written against the same text so that a later phase can switch them on."""

    @classmethod
    def setUpClass(cls):
        cls.c1 = code(CLASS1)

    @unittest.skip("TARGET-B B2 (JF-3, J3 limited release): after a STA jump to B at the same position as A the sender's target is B (the requested index)")
    @jf0("C02", "TARGET")
    def test_TARGET_B_C02_the_requested_index_is_the_target_even_when_an_earlier_station_has_the_same_position(self):
        self.assertRegex(self.c1, r"targetStationIndex = (sIdx|requestedStationIndex|pendingJumpStationIndex)")

    @unittest.skip("TARGET-B B2 (JF-3): the 50 m boundary does not move the target away from the requested index")
    @jf0("C03", "TARGET")
    def test_TARGET_B_C03_the_boundary_station_does_not_replace_the_requested_index(self):
        self.assertRegex(self.c1, r"targetStationIndex = (sIdx|requestedStationIndex|pendingJumpStationIndex)")

    @unittest.skip("TARGET-B B2 (JF-3): an earlier station within 50 m does not replace the requested index")
    @jf0("C17", "TARGET")
    def test_TARGET_B_C17_an_earlier_station_within_50_m_does_not_replace_the_requested_index(self):
        self.assertRegex(self.c1, r"targetStationIndex = (sIdx|requestedStationIndex|pendingJumpStationIndex)")

    @unittest.skip("TARGET-B B6 (JF-3): 'no next station' is unified to Count and a scenario change resets the target index to 0")
    @jf0("C05", "TARGET")
    def test_TARGET_B_C05_no_next_station_sets_the_index_to_count(self):
        self.assertRegex(self.c1, r"targetStationIndex = stationList\.Count")

    @unittest.skip("TARGET-B B6 (JF-3): a scenario change resets the target index to 0")
    @jf0("C15", "TARGET")
    def test_TARGET_B_C15_a_scenario_change_resets_the_target_index(self):
        block = re.search(r"if \(!object\.Equals\(currentScenario, BveHacker\.Scenario\)\) \{(.*?)initialStaListSent = false;", self.c1)
        self.assertIsNotNone(block)
        self.assertIn("targetStationIndex = 0;", block.group(1))

    @unittest.skip("TARGET-B B4 / B7 (JF-3): a missing jump method gives a failure response, not a completion")
    @jf0("C07", "TARGET")
    def test_TARGET_B_C07_a_missing_jump_method_does_not_announce_a_completion(self):
        self.fail("TARGET-B B4/B7: the expectation (a failure response instead of a completion) can not be stated on today's text; its format is undecided (U-12)")

    @unittest.skip("TARGET-B B4 (JF-3): a missing time field gives a failure response, not a completion")
    @jf0("C09", "TARGET")
    def test_TARGET_B_C09_a_missing_time_field_does_not_announce_a_completion(self):
        self.fail("TARGET-B B4/B7: the expectation can not be stated on today's text; the failure format is undecided (U-12)")

    @unittest.skip("TARGET-B B5 (JF-3): a LOC jump re-initialises the target state in its own branch")
    @jf0("C12", "TARGET")
    def test_TARGET_B_C12_a_location_jump_reinitialises_the_target_state(self):
        i_loc = self.c1.index('else if (msg.StartsWith("JUMP_LOC_TIME:"))')
        branch = self.c1[i_loc:self.c1.index("double speed = 0.0;")]
        self.assertIn("isInitialized = false;", branch)

    @unittest.skip("TARGET-B B10 (JF-3): the LOC location is parsed with the invariant culture")
    @jf0("C16", "TARGET")
    def test_TARGET_B_C16_the_loc_location_is_parsed_with_the_invariant_culture(self):
        self.assertRegex(self.c1, r"double\.TryParse\(parts\[1\], (System\.Globalization\.)?NumberStyles\.Float, (System\.Globalization\.)?CultureInfo\.InvariantCulture, out double rLoc\)")

    @unittest.skip("TARGET-B B7 / FC-7 (JF-3): the sender answers an unrunnable jump with a failure response")
    @jf0("J20", "TARGET")
    def test_TARGET_B_J20_the_sender_has_a_failure_response(self):
        self.assertIn("JUMP_FAILED", self.c1)

    @unittest.skip("TARGET-A V-3 (JF-2, Python side): a station index outside the list is refused by the sender's caller; the C# side keeps no range check (C11)")
    @jf0("C11", "TARGET")
    def test_TARGET_A_C11_the_range_is_checked_before_the_request_is_sent(self):
        self.fail("TARGET-A V-3: the check lives on the Python side (see file F1 TARGET_A_S17); there is nothing to state on the C# text")

    @unittest.skip("TARGET-A V-4 (JF-2) / TARGET-B B2, B3, K7 (JF-3): the completion reports the sender's real next index")
    @jf0("X06", "TARGET")
    def test_TARGET_B_X06_the_completion_carries_the_next_station_index(self):
        self.assertRegex(self.c1, r"JUMP_COMPLETE:\{pendingJumpType\}\" \+ \$\":\{pendingJumpStationIndex\}\" \+ \$\":\{completedLocation\}\" \+ \$\":\{completedTime\}\" \+ \$\":\{jumpCounter\}\" \+ \$\":\{")


# ==============================================================================================================================================
class Manual(unittest.TestCase):
    """What only a real BVE observation can settle. NO assertion, NO expectation, NOT an automated pass (each is a skip)."""

    @unittest.skip("requires BVE observation (L-1): BVE6 Current, STA jump to B at the same position as A - STATNAME / NEXTLOC / arrival and whether an index could tell A from B")
    @jf0("L1", "MANUAL")
    def test_MANUAL_L1_same_position_a_b_after_a_sta_jump(self):
        pass

    @unittest.skip("requires BVE observation (L-2): what Initialize(int) changes for a same-position station (doors, time, stop time)")
    @jf0("L2", "MANUAL")
    def test_MANUAL_L2_initialize_on_a_same_position_station(self):
        pass

    @unittest.skip("requires BVE observation (L-3): BVE's reaction to an out-of-range station index; and whether the S19 pair (no door time, STA retry) re-creates the door-close reservation")
    @jf0("L3", "MANUAL")
    def test_MANUAL_L3_out_of_range_index_and_the_s19_pair(self):
        pass

    @unittest.skip("requires BVE observation (L-4): a LOC jump with a time difference below 300 ms - is the target station re-initialised")
    @jf0("L4", "MANUAL")
    def test_MANUAL_L4_loc_jump_below_300_ms(self):
        pass

    @unittest.skip("requires BVE observation (L-5): after a STA jump to a station with an earlier station within 50 m (not at the same position), is the earlier one selected")
    @jf0("L5", "MANUAL")
    def test_MANUAL_L5_close_previous_station(self):
        pass

    @unittest.skip("requires BVE observation (L-6): the real positions of the pseudo-turnback pairs A / B in the maps (same position or close)")
    @jf0("L6", "MANUAL")
    def test_MANUAL_L6_pseudo_turnback_pair_positions(self):
        pass

    @unittest.skip("requires BVE observation (L-8): whether the decimal-separator culture issue (C16 / F-28) happens on a real machine locale")
    @jf0("L8", "MANUAL")
    def test_MANUAL_L8_decimal_separator_culture(self):
        pass

    @unittest.skip("requires BVE observation (L-9): whether Current's station build equals the Legacy build for the same input (the Legacy side of the STALIST fill-in is run in file F4; the Current side can not run offline)")
    @jf0("L9", "MANUAL")
    def test_MANUAL_L9_current_and_legacy_station_build_equivalence(self):
        pass

    @unittest.skip("requires BVE observation (U-1): the distribution of completed_time minus expected_time; no tolerance is decided and none is recorded here")
    @jf0("U1", "MANUAL")
    def test_MANUAL_U1_completion_time_tolerance(self):
        pass


# ==============================================================================================================================================
class Z_Meta(unittest.TestCase):
    PREFIXES = (("test_CURRENT_DANGER_", "CURRENT_DANGER"), ("test_CURRENT_", "CURRENT"), ("test_TARGET_A_", "TARGET"), ("test_TARGET_B_", "TARGET"), ("test_MANUAL_", "MANUAL"))

    @staticmethod
    def case_methods():
        for cls in (Pins, Targets, Manual):
            for name in sorted(n for n in dir(cls) if n.startswith("test_")):
                yield cls, name, getattr(cls, name)

    @classmethod
    def kind_of(cls, name):
        for prefix, kind in cls.PREFIXES:
            if name.startswith(prefix):
                return kind
        return None

    def test_META_every_test_has_a_known_prefix_and_metadata_of_the_same_kind_except_the_pin_finder(self):
        count = 0
        for cls, name, fn in self.case_methods():
            if name == "test_CURRENT_pins_found_the_initialisation_loop":
                continue                                                     # a precondition of the pins, not a case of JF-0 v2
            count += 1
            kind = self.kind_of(name)
            self.assertIsNotNone(kind, name)
            meta = getattr(fn, "jf0", None)
            self.assertIsNotNone(meta, name)
            self.assertEqual(meta["kind"], kind, name)
            self.assertIn(meta["id"], OWN_IDS, name)
            self.assertIn(meta["id"], name)
        self.assertGreater(count, 40)

    def test_META_every_CURRENT_DANGER_carries_its_four_facts(self):
        seen = 0
        for cls, name, fn in self.case_methods():
            if self.kind_of(name) != "CURRENT_DANGER":
                continue
            seen += 1
            meta = fn.jf0
            self.assertTrue(name.startswith("test_CURRENT_DANGER_" + meta["id"]), name)
            for key, shortest in (("danger", 21), ("phase", 8), ("flip", 21)):
                self.assertTrue(meta[key] and len(meta[key]) >= shortest, (name, key))
        self.assertEqual(seen, 9)

    def test_META_every_TARGET_is_skipped_with_a_contract_id_in_the_reason(self):
        seen = 0
        for cls, name, fn in self.case_methods():
            if self.kind_of(name) != "TARGET":
                continue
            seen += 1
            self.assertTrue(getattr(fn, "__unittest_skip__", False), name)
            reason = getattr(fn, "__unittest_skip_why__", "")
            self.assertRegex(reason, r"TARGET-[AB] ", name)
            self.assertRegex(reason, r"(V-\d|B\d+|FC-\d|K\d)", name)
        self.assertGreaterEqual(seen, 12)

    def test_META_the_manual_items_are_skips_with_no_assertion_and_cover_L1_to_L9_and_U1(self):
        import ast
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        manual = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Manual")
        seen = []
        for fn in (n for n in manual.body if isinstance(n, ast.FunctionDef)):
            seen.append(fn.name)
            body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
            self.assertTrue(all(isinstance(n, ast.Pass) for n in body), fn.name)               # nothing but 'pass': no assertion, no expectation
            method = getattr(Manual, fn.name)
            self.assertTrue(getattr(method, "__unittest_skip__", False), fn.name)
            self.assertTrue(method.__unittest_skip_why__.startswith("requires BVE observation"), fn.name)
        self.assertEqual(len(seen), 9)
        self.assertEqual(sorted(getattr(Manual, n).jf0["id"] for n in seen), sorted(["L1", "L2", "L3", "L4", "L5", "L6", "L8", "L9", "U1"]))

    def test_META_every_own_id_has_a_test(self):
        have = {fn.jf0["id"] for _c, _n, fn in self.case_methods() if hasattr(fn, "jf0")}
        self.assertEqual(sorted(set(OWN_IDS) - have), [])
        self.assertEqual(sorted(have - set(OWN_IDS)), [])

    def test_META_the_files_are_only_read_and_no_network_or_process_is_used(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            source = f.read()
        body = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", source, flags=re.S))
        # (the words are written in two pieces so that this list does not match itself)
        for word in ("sock" "et", "sub" "process", "Po" "pen", "os." "system", "expand" "user", "Desk" "top", "Down" "loads", "open(" "path, \"w", "write" "("):
            self.assertNotIn(word, body, word)


if __name__ == "__main__":
    unittest.main()
