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

PHASE ST-3b (Current C# wiring; the audited Class1.cs below is the revision AFTER it): the characterization of the dangerous shapes that ST-3b removed is FLIPPED, as the audit
(Start Audit 14, section 1) and the owner's plan fixed: C02 / C03 / C17 / X06 (the target after a jump), C07 / C09 (no jump method / no time field), C11 (no range check), C12 (a location
jump does not re-initialise), C16 / F28 / F11 (the culture of the numbers) were DANGER or neutral pins of the old shape; each id keeps its place here as a CURRENT pin of the NEW shape
(the new shape is also held by tests\\test_stationindex_current_st3b.py, the contract of ST-3b), and its TARGET twin is gone. C06 / C08 / C10 / F12 / F32 / C15 / J20 are re-pinned to
the shape ST-3b gave them (the same intent: a request without a scenario gives no completion; an exception gives no completion; the completion stays pending until the send succeeds;
one pending slot; the link sets; the target index survives a scenario change - still FUTURE, JF-3 B6; no failure response - OD-S3-6). What ST-3b did NOT touch stays as it was: C04,
C05, C13, C15, J20, the MANUAL items.

ISOLATION: files are only read (Class1.cs, CurrentJumpEndpoint.cs, CurrentJumpExecution.cs, the Legacy csproj, two Python sources). No socket, no process, no write, no Desktop, no Downloads.
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
EXECUTION = os.path.join(PLUGIN, "TsScoringPlugin", "CurrentJumpExecution.cs")
DATAPLANE = os.path.join(PLUGIN, "TsScoringPlugin", "CurrentDataPlane.cs")
LEGACY_CSPROJ = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
CURRENT_CSPROJ = os.path.join(PLUGIN, "TsScoringPlugin", "TsScoringPlugin.csproj")

CLASS1_AUDITED_NORMALISED_SHA256 = "830E16A65CA42E16D97A1D15E3871AA642D321B7C29BEC11005EF17675FC5BEC"
# Phase U10 (the stop range of the station list builder): the value moved from 4D8FF9CB... after the changed lines were re-audited (ReadStationRange, RejectStationList, the latch stationRangeRejected and its gate; the 5.0 / 5.0
# fallback of an unreadable range is gone). Every shape pin of this file still passes unchanged; tests\\test_stationindex_station_range_u10.py holds the contract of the new shape.
# Phase ST-3b (the Current jump wiring): the value moved from 009BA364... after the changed lines were re-audited (the jump transaction, the one-shot StationIndex re-initialisation, the canonical numbers; every shape pin of this
# file was re-pinned or flipped as the module docstring says, and tests\\test_stationindex_current_st3b.py holds the contract of the new shape).
# Phase ST-1A (J3-G2: R1 / R5 / R6 in their observation-only form): the value moved from 29613E14... after the changed lines were re-audited. The change is ADDITIVE and only the
# STIDX statements read what it adds; every shape pin of this file (C02 ... C17, X06, F11, F12, U1, L1 ... L9) is unchanged and still passes; tests\\test_stationindex_supply_st1a.py
# (class D) pins who reads the new fields, where the part is written and that no new write of targetStationIndex exists.

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


def compile_items(path):
    """The (Include, Link-or-None) pair of every <Compile> element of an MSBuild project; XML comments are ignored."""
    text = re.sub(r"<!--.*?-->", "", read_text(path), flags=re.S)
    items = []
    for m in re.finditer(r'<Compile\s+Include="([^"]+)"\s*(?:/>|>(.*?)</Compile>)', text, flags=re.S):
        link = re.search(r"<Link>([^<]*)</Link>", m.group(2) or "")
        items.append((m.group(1), link.group(1) if link else None))
    return items


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
        # Phase ST-3b: the position search lives in its own function, reached only by a re-initialisation that carries NO StationIndex
        cls.init_loop = re.search(r"private void SelectTargetByPosition\(double location, bool areDoorsClosed\) \{ for \(int i = 0; i < stationList\.Count; i\+\+\) \{ if \(stationList\[i\]\.Location >= location - 50\.0\) \{ (.*?) \} \} \}",
                                  cls.c1)
        cls.ex = code(EXECUTION)

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

    @jf0("C02", "CURRENT")
    def test_CURRENT_C02_after_a_jump_the_target_is_the_requested_index_so_the_second_of_two_same_position_stations_is_the_target(self):
        """Phase ST-3b (FLIPPED from DANGER C02, its TARGET_B twin is this test): the re-initialisation that follows an official jump takes the ADOPTED index; the first-in-range search is
        the one of a re-initialisation without an index and is unchanged."""
        body = self.init_loop.group(1)
        self.assertEqual(len(re.findall(r"targetStationIndex = i;", body)), 1)
        self.assertRegex(body, r"targetStationIndex = i; hasDoorOpenedAtTarget = [^;]+; break;$")           # the index-less search: the first hit ends it (unchanged)
        self.assertNotIn("requestedStationIndex", body)                                                      # and the requested index plays no part in IT
        self.assertRegex(self.c1, r"targetStationIndex = requestedStationIndex;")                           # the jump path: the requested index is the target
        self.assertIn("if (requestedStationIndex >= 0) SelectTargetByRequestedIndex(requestedStationIndex, location, areDoorsClosed); else if (!requestedTargetRefused) SelectTargetByPosition(location, areDoorsClosed);", self.c1)

    @jf0("C03", "CURRENT")
    def test_CURRENT_C03_the_back_range_of_50_m_of_the_index_less_search_is_inclusive_and_the_jump_path_never_reaches_it(self):
        """Phase ST-3b (FLIPPED from DANGER C03): the inclusive 50 m range is a fact of the search of a re-initialisation without an index only."""
        self.assertIn("if (stationList[i].Location >= location - 50.0)", self.c1)
        self.assertNotIn("stationList[i].Location > location - 50.0", self.c1)
        self.assertEqual(self.c1.count("location - 50.0"), 1)
        self.assertNotIn("location - 50.0", self.jump_loop)                                                  # the jump branches never name the search
        self.assertNotIn("SelectTargetByPosition", self.jump_loop)

    @jf0("C04", "CURRENT")
    def test_CURRENT_C04_the_door_open_detection_uses_100_m_and_the_initial_state_uses_50_m(self):
        self.assertIn("if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true;", self.c1)
        self.assertIn("hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[i].Location - location) < 50.0;", self.init_loop.group(1))

    @jf0("C05", "CURRENT")
    def test_CURRENT_C05_when_no_station_is_in_range_the_target_index_is_left_as_it_was(self):
        """Current has no 'no next station' value: after the loop the code only sets isInitialized (the Legacy timeline sets target = Count)."""
        self.assertNotRegex(self.c1, r"targetStationIndex = (stationList\.Count|-1)")
        self.assertRegex(self.c1, r"private void SelectTargetByPosition\(double location, bool areDoorsClosed\) \{ for \(int i = 0; i < stationList\.Count; i\+\+\) \{ if \(stationList\[i\]\.Location >= location - 50\.0\) \{ targetStationIndex = i; [^}]*break; \} \} \}")

    @jf0("C17", "CURRENT")
    def test_CURRENT_C17_a_station_behind_the_requested_one_within_50_m_does_not_replace_it(self):
        """Phase ST-3b (FLIPPED from DANGER C17): the adopted index feeds the target; the plugin no longer parses an index out of the command text."""
        self.assertNotRegex(self.c1, r"\bsIdx\b")
        self.assertIn("targetStationIndex = requestedStationIndex;", self.c1)
        by_index = re.search(r"private void SelectTargetByRequestedIndex\(int requestedStationIndex, double location, bool areDoorsClosed\) \{ (.*?) \}", self.c1)
        self.assertIsNotNone(by_index)
        self.assertNotIn("for (", by_index.group(1))                                                          # no search on the way from the index to the target
        self.assertNotIn("Location >=", by_index.group(1))
        self.assertIn("pendingJumpStationIndex = decision.StationIndex;", self.c1)

    @jf0("X06", "CURRENT")
    def test_CURRENT_X06_the_completion_is_announced_after_an_index_based_reinitialisation_with_the_adopted_index(self):
        """Phase ST-3b (FLIPPED from DANGER X06, its TARGET_B twin is this test): the pending jump (and with it the one-shot index) is begun after the host call and after the target state was
        cleared; the target itself is taken from that index in the next initialisation pass, and the completion carries the same adopted index."""
        for branch in (self.sta_branch, self.loc_branch):
            self.assertLess(branch.index("ReinitializeTargetStateAfterJump();"), branch.index("BeginPendingJump("))
            self.assertNotIn("targetStationIndex", branch)                                                    # the jump branch itself does not write the target
        self.assertRegex(self.c1, r"FormatCompletion\( pendingJumpType, pendingJumpStationIndex,")
        self.assertIn("requestedTargetIndex = decision.StationIndex;", self.c1)

    # -- C06 - C10 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("C06", "CURRENT")
    def test_CURRENT_C06_a_request_without_a_scenario_is_refused_with_one_diagnostic_and_no_completion(self):
        """Phase ST-3b (re-pinned): the silent `continue` became a refusal with a reason (scenario-missing); the intent - no host call, no completion - is the same."""
        for branch in (self.sta_branch, self.loc_branch):
            self.assertEqual(branch.count("CurrentJumpExecution.RScenarioMissing"), 1)
            self.assertRegex(branch, r"if \(rawScenario == null\) \{ JumpRefused\(jumpRequestId, jumpDecision, TSScoringPlugin\.DataPlane\.CurrentJumpExecution\.RScenarioMissing, \"-\"\); continue; \}")
            self.assertLess(branch.index("RScenarioMissing"), branch.index("BeginPendingJump("))
            self.assertLess(branch.index("RScenarioMissing"), branch.index(".Invoke("))

    @jf0("C07", "CURRENT")
    def test_CURRENT_C07_a_missing_jump_method_is_refused_before_the_host_call_and_no_completion_is_announced(self):
        """Phase ST-3b (FLIPPED from DANGER C07; OD-S3-6: no failure response - the refusal is one diagnostic line, Python's own timeout releases the jump)."""
        for branch, method in ((self.sta_branch, "jumpStaMethod"), (self.loc_branch, "jumpMethod")):
            self.assertRegex(branch, r"if \(%s == null\) \{ JumpRefused\(jumpRequestId, jumpDecision, TSScoringPlugin\.DataPlane\.CurrentJumpExecution\.RApiMissing, \"-\"\); continue; \}" % method)
            self.assertNotIn("if (%s != null)" % method, branch)
            self.assertLess(branch.index("RApiMissing"), branch.index(".Invoke("))
            self.assertGreater(branch.index("BeginPendingJump("), branch.index(".Invoke("))

    @jf0("C08", "CURRENT")
    def test_CURRENT_C08_an_exception_of_the_jump_call_ends_in_one_diagnostic_and_no_completion(self):
        """Phase ST-3b (re-pinned): the empty catch writes one line (jump-exception, the exception TYPE only) now; the pending jump is begun only after the host call and the time were set."""
        for branch in (self.sta_branch, self.loc_branch):
            self.assertLess(branch.index("Invoke("), branch.index("BeginPendingJump("))
            self.assertLess(branch.index("timeField.SetValue(rawTimeMgr, adoptedTimeMs);"), branch.index("BeginPendingJump("))
            self.assertIn("catch (Exception jumpEx) { JumpRefused(jumpRequestId, jumpDecision, TSScoringPlugin.DataPlane.CurrentJumpExecution.RJumpException, jumpEx.GetType().Name); }", branch)
            self.assertNotIn("jumpEx.Message", branch)

    @jf0("C09", "CURRENT")
    def test_CURRENT_C09_a_missing_time_field_is_refused_before_the_host_call_and_no_completion_is_announced(self):
        """Phase ST-3b (FLIPPED from DANGER C09): the time field is looked for BEFORE the host is called; without it nothing is called and nothing is announced."""
        for branch in (self.sta_branch, self.loc_branch):
            self.assertIn("FindJumpTimeField(scenario, bindFlagsAll, out rawTimeMgr)", branch)
            self.assertRegex(branch, r"if \(timeField == null\) \{ JumpRefused\(jumpRequestId, jumpDecision, TSScoringPlugin\.DataPlane\.CurrentJumpExecution\.RTimeFieldMissing, \"-\"\); continue; \}")
            self.assertLess(branch.index("if (timeField == null)"), branch.index(".Invoke("))
            self.assertIn("timeField.SetValue(rawTimeMgr, adoptedTimeMs);", branch)
        helper = re.search(r"private static System\.Reflection\.FieldInfo FindJumpTimeField\(.*?\{ (.*?) \} ", self.c1)
        self.assertIsNotNone(helper)
        self.assertIn('GetField("c", flags)', helper.group(1))

    @jf0("C10", "CURRENT")
    def test_CURRENT_C10_the_completion_is_sent_only_when_initialised_and_stays_pending_until_the_send_succeeds(self):
        """Phase ST-3b (re-pinned): the pending jump is emptied in ONE place (ClearPendingJump), after the send succeeded or when the jump is abandoned."""
        self.assertIn("if (pendingJumpComplete && isInitialized)", self.c1)
        sent = re.search(r"if \(batch\.SendJumpComplete\(completeBytes, pendingJumpRequestId\)\) \{ JumpDiag\(.*?\); ClearPendingJump\(\); \}", self.c1)
        self.assertIsNotNone(sent)
        self.assertEqual(len(re.findall(r"(?<!bool )pendingJumpComplete = false;", self.c1)), 1)         # the only place that clears the pending flag (the declaration excepted)
        clear = re.search(r"private void ClearPendingJump\(\) \{ (.*?) \}", self.c1)
        self.assertIsNotNone(clear)
        for field in ("pendingJumpComplete = false;", "pendingJumpRequestId = null;", 'pendingJumpType = "";', "pendingJumpStationIndex = -1;", "requestedTargetIndex = -1;"):
            self.assertIn(field, clear.group(1))

    @jf0("C11", "CURRENT")
    def test_CURRENT_C11_the_requested_station_index_is_judged_against_the_list_before_any_host_call(self):
        """Phase ST-3b (FLIPPED from C11): range, scope and location are checked by the judgement (CurrentJumpExecution.Judge) before the first host call."""
        self.assertLess(self.jump_loop.index("CurrentJumpExecution.Judge(msg, BuildJumpView())"), self.jump_loop.index(".Invoke("))
        self.assertIn("if (r.StationIndex < 0 || r.StationIndex >= view.Locations.Length) { d.Reason = RIndexRange; return d; }", self.ex)
        self.assertNotRegex(self.sta_branch, r"int\.TryParse")

    # -- C12 / C13 -------------------------------------------------------------------------------------------------------------------------------
    @jf0("C12", "CURRENT")
    def test_CURRENT_C12_a_location_jump_reinitialises_the_target_state_itself(self):
        """Phase ST-3b (FLIPPED from C12, its TARGET_B twin is this test): a location jump no longer relies on the time-discontinuity check; the shared re-initialisation clears isInitialized."""
        self.assertIn("ReinitializeTargetStateAfterJump();", self.loc_branch)
        self.assertIn("ReinitializeTargetStateAfterJump();", self.sta_branch)
        body = re.search(r"private void ReinitializeTargetStateAfterJump\(\) \{ (.*?) \}", self.c1)
        self.assertIsNotNone(body)
        self.assertIn("isInitialized = false;", body.group(1))

    @jf0("C13", "CURRENT")
    def test_CURRENT_C13_the_jump_counter_counts_time_discontinuities_of_more_than_300_ms(self):
        self.assertEqual(len(re.findall(r"jumpCounter\+\+;", self.c1)), 1)
        self.assertRegex(self.c1, r"if \(lastTimeMs != 0 && Math\.Abs\(jumpTimeErrorMs\) > 300\) \{ isInitialized = false;[^}]*jumpCounter\+\+; \}")

    # -- C15 -------------------------------------------------------------------------------------------------------------------------------------
    @danger("C15", "a scenario change does not reset the target index: a stale index of the previous scenario can survive and, if no station is in range, is used (or points past the new list)",
            "JF-3 (TARGET-B B6: reset to 0 and 'no next station' unified)", "the index is reset on a scenario change; this pin is replaced by TARGET_B_C15")
    def test_CURRENT_DANGER_C15_the_target_index_survives_a_scenario_change(self):
        block = re.search(r"if \(!object\.Equals\(currentScenario, BveHacker\.Scenario\)\) \{(.*?)initialStaListSent = false; lastStaListSendTime = DateTime\.MinValue; AbandonPendingJump\(.*?\); \}", self.c1)
        self.assertIsNotNone(block)
        self.assertIn("isInitialized = false;", block.group(1))
        self.assertNotIn("targetStationIndex", block.group(1))
        writes = re.findall(r"targetStationIndex\s*(\+\+|=(?!=))", self.c1)
        # the declaration, the requested-index selector (ST-3b), the position search, three advances: no reset anywhere
        self.assertEqual(sorted(writes), sorted(["=", "=", "=", "++", "++", "++"]))

    # -- C16 / F28 / F11 -------------------------------------------------------------------------------------------------------------------------
    @jf0("C16", "CURRENT")
    def test_CURRENT_C16_the_command_text_is_read_by_the_shared_reader_so_no_culture_decides_the_location(self):
        """Phase ST-3b (FLIPPED from DANGER C16, its TARGET_B twin is this test): the plugin does not parse the command text at all; the endpoint's gate and the plugin's judgement both use the shared JumpWire reader."""
        self.assertNotIn("double.TryParse", self.c1)
        self.assertNotIn("Split(':')", self.c1)
        self.assertIn("CurrentJumpExecution.Judge(msg, BuildJumpView())", self.jump_loop)
        self.assertIn("JumpWire.ParseRequest(text, out reason)", self.ep)
        self.assertIn("JumpWire.ParseRequest(text, out why)", self.ex)
        self.assertNotIn("TryParse", self.ex)

    @jf0("F28", "CURRENT")
    def test_CURRENT_F28_the_station_command_parts_are_read_by_the_shared_reader_in_the_endpoint_and_in_the_plugin(self):
        """Phase ST-3b (FLIPPED from F28): no integer of the command is read with TryParse any more, in the plugin or in the Current gate of the endpoint. The old three-field predicate lives on only as
        ValidGrammarV1, the grammar of the five argument validator (the Legacy plane's, until ST-3c); it is pinned apart (tests\\test_stationindex_current_st3b.py, A2_LegacyGateKept)."""
        self.assertNotIn("int.TryParse(parts[1], out int sIdx)", self.sta_branch)
        gate = re.search(r"private static bool ValidGrammar\(UInt32 messageType, string text\) \{ (.*?) \} ", self.ep)
        self.assertIsNotNone(gate)
        self.assertNotIn("TryParse", gate.group(1))
        old = re.search(r"private static bool ValidGrammarV1\(UInt32 messageType, string text\) \{ (.*?) \} (?=\}|private|internal)", self.ep)
        self.assertIsNotNone(old)
        self.assertEqual(self.ep.count("Int32.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out index)"), 1)       # the one that is left is inside ValidGrammarV1
        self.assertIn("Int32.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out index)", old.group(1))

    @jf0("F11", "CURRENT")
    def test_CURRENT_F11_the_completion_text_is_written_by_the_canonical_formatter_in_any_culture(self):
        """Phase ST-3b (FLIPPED from F11): the interpolation of a double (the current culture, 15 digits) is gone; JumpWire.FormatCompletionV2 writes the nine fields (invariant, shortest exact text)."""
        self.assertNotIn('$"JUMP_COMPLETE:', self.c1)
        self.assertNotIn("{completedLocation}", self.c1)
        text = self.c1[self.c1.index("string completeReason = null;"):self.c1.index("if (completeMessage == null)")]
        self.assertIn("CurrentJumpExecution.FormatCompletion(", text)
        self.assertNotIn("CultureInfo", text)
        self.assertNotIn("ToString(", text)
        self.assertIn("JumpWire.FormatCompletionV2(kind, selectedIdx, actualLocation, timeMs, jumpCount, scope, out reason)", self.ex)

    # -- F12 : one slot, several commands per Tick -------------------------------------------------------------------------------------------------
    @jf0("F12", "CURRENT")
    def test_CURRENT_F12_every_command_of_a_tick_is_run_and_only_one_pending_slot_exists(self):
        """Phase ST-3b (re-pinned): still one pending slot; a command that is begun while another is pending now ENDS it explicitly (superseded) instead of overwriting it silently."""
        self.assertNotIn("break;", self.jump_loop)                                  # the loop never stops after the first command
        self.assertEqual(len(re.findall(r"private bool pendingJumpComplete\b", self.c1)), 1)
        self.assertEqual(len(re.findall(r"private byte\[\] pendingJumpRequestId\b", self.c1)), 1)
        self.assertEqual(len(re.findall(r"pendingJumpRequestId = requestId;", self.c1)), 1)          # BeginPendingJump, called by STA and LOC alike
        self.assertEqual(len(re.findall(r"BeginPendingJump\(", self.c1)), 3)                          # the definition and the two branches
        self.assertIn("if (pendingJumpComplete) AbandonPendingJump(TSScoringPlugin.DataPlane.CurrentJumpExecution.RSuperseded", self.c1)

    # -- J20 (static) ----------------------------------------------------------------------------------------------------------------------------
    @danger("J20", "no failure response exists in the sender: not in Class1.cs, not in the endpoint, not in the data plane; an unrunnable jump is only ever noticed by Python's 10 s timeout",
            "JF-3 (TARGET-B B7 / FC-7 JUMP_FAILED)", "a failure message exists; this pin is replaced by TARGET_B_J20")
    def test_CURRENT_DANGER_J20_the_sender_has_no_failure_response(self):
        for name, text in (("Class1.cs", self.c1), ("CurrentJumpEndpoint.cs", self.ep), ("CurrentDataPlane.cs", self.dp), ("CurrentJumpExecution.cs", self.ex)):
            self.assertNotIn("JUMP_FAILED", text, name)
            self.assertNotIn("JumpFailed", text, name)
        self.assertEqual(len(re.findall(r"CurrentJumpExecution\.FormatCompletion\(", self.c1)), 1)            # the only jump message the sender writes (ST-3b: through the one formatter)
        self.assertEqual(len(re.findall(r'"JUMP_COMPLETE:', self.c1)), 0)

    # -- F32 : the link sets of the Legacy and the Current project ---------------------------------------------------------------------------------
    # PID-D4 / LEGACY JUMP 2A-ALPHA (Stage S4): the Legacy project now links the Current jump endpoint source ONCE, as the one shared link that gives it the four
    # shared types (JumpDirectoryPublisher, JumpCommandValidator, CurrentJumpCommand, JumpCapabilities). The Current project's own reference is the existing contract
    # and is pinned apart, and the Legacy sources never call CurrentJumpEndpoint.Create. Each expectation below is its own exact count (no short-name total).
    LEGACY_SHARED_LINK = ("..\\..\\..\\TsScoringPlugin\\CurrentJumpEndpoint.cs", "Shared\\CurrentJumpEndpoint.cs")
    LEGACY_EXPECTED_ITEMS = sorted([
        ("src\\AssemblyInfo.cs", None), ("src\\LegacyApi.cs", None), ("..\\..\\..\\TsScoringPlugin\\CurrentDataPlane.cs", "Shared\\CurrentDataPlane.cs"),
        LEGACY_SHARED_LINK, ("src\\LegacyDataPlaneSink.cs", None), ("src\\LegacyGroundLimits.cs", None), ("src\\LegacyHandleContract.cs", None),
        ("..\\Shared\\GenericHandleTextContract.cs", "Shared\\GenericHandleTextContract.cs"), ("src\\LegacyInputProbe.cs", None),
        ("..\\Shared\\DataPlaneProtocol.cs", "Shared\\DataPlaneProtocol.cs"), ("..\\Shared\\TelemetryDirectoryReader.cs", "Shared\\TelemetryDirectoryReader.cs"),
        ("src\\LegacyInputTelemetry.cs", None), ("src\\LegacyJumpCommandQueue.cs", None), ("src\\LegacyJumpControlPlane.cs", None), ("src\\LegacyJumpEndpoint.cs", None), ("src\\LegacyJumpExecutor.cs", None),      # Phase LJX-1 (pin moved): the executor file
        ("src\\LegacyScoringProbe.cs", None), ("src\\LegacyStationTimeline.cs", None), ("src\\LegacyTelemetrySession.cs", None), ("src\\LegacyTelemetryExtension.cs", None),
        ("..\\Shared\\TelemetryContract.cs", "Shared\\TelemetryContract.cs"),
        ("..\\Shared\\StationListIdentity.cs", "Shared\\StationListIdentity.cs"),           # Phase ST-1A (pin moved): the one shared file of the STIDX supply
        ("..\\Shared\\JumpWire.cs", "Shared\\JumpWire.cs")], key=lambda t: t[0])                    # Phase ST-3b / G-PC-1 (pin moved): the compile-only link of the wire codec (nothing of Legacy calls it before ST-3c)

    @jf0("F32", "CURRENT")
    def test_CURRENT_F32_the_legacy_project_links_exactly_this_set_of_sources_with_the_one_shared_current_jump_endpoint_link_and_the_current_project_keeps_its_own(self):
        # (1) the Legacy project: the exact (Include, Link) pairs, 23 of them (22 before Phase ST-3b, 21 before Phase ST-1A, 20 before Phase LJX-1)
        legacy = compile_items(LEGACY_CSPROJ)
        self.assertEqual(sorted(legacy, key=lambda t: t[0]), self.LEGACY_EXPECTED_ITEMS)
        self.assertEqual(len(legacy), 23)
        # (2) the shared link: exactly one element, exactly this Include and this Link; nothing else of the Current plugin folder besides CurrentDataPlane.cs
        endpoint_links = [t for t in legacy if t[0].endswith("CurrentJumpEndpoint.cs")]
        self.assertEqual(endpoint_links, [self.LEGACY_SHARED_LINK])
        leaving = sorted(t[0] for t in legacy if t[0].startswith("..\\..\\"))
        self.assertEqual(leaving, ["..\\..\\..\\TsScoringPlugin\\CurrentDataPlane.cs", "..\\..\\..\\TsScoringPlugin\\CurrentJumpEndpoint.cs"])
        # (3) the Current project: its own plain reference stays (the existing contract) and it links nothing from the Legacy folder
        current = compile_items(CURRENT_CSPROJ)
        self.assertEqual([t for t in current if t[0].endswith("CurrentJumpEndpoint.cs")], [("CurrentJumpEndpoint.cs", None)])
        self.assertEqual([t for t in current if "Legacy" in t[0]], [])
        # Phase ST-3b: the Current project links the wire codec once (as the other shared files) and compiles the Current-only decision unit once; the Legacy project does NOT compile the unit
        self.assertEqual([t for t in current if t[0].endswith("JumpWire.cs")], [("..\\Handshake\\Telemetry\\Shared\\JumpWire.cs", "Shared\\JumpWire.cs")])
        self.assertEqual([t for t in current if t[0].endswith("CurrentJumpExecution.cs")], [("CurrentJumpExecution.cs", None)])
        self.assertEqual([t for t in legacy if "CurrentJumpExecution" in t[0]], [])
        # (4) the shared source is the same file for both projects and defines the shared types once (no copy of them in any Legacy-compiled source)
        shared_types = re.findall(r"\b(?:class|struct|enum|interface)\s+(JumpCapabilities|CurrentJumpCommand|JumpCommandValidator|JumpDirectoryPublisher|CurrentJumpEndpoint)\b", self.ep)
        self.assertEqual(sorted(shared_types), sorted(["JumpCapabilities", "CurrentJumpCommand", "JumpCommandValidator", "JumpDirectoryPublisher", "CurrentJumpEndpoint"]))
        for rel in (name for name, link in legacy if link is None):
            text = code(os.path.join(os.path.dirname(LEGACY_CSPROJ), rel))
            for shared in shared_types:
                self.assertIsNone(re.search(r"\b(?:class|struct|enum|interface)\s+" + shared + r"\b", text), (rel, shared))
            # (5) no Legacy source names the endpoint class or calls its Create method (the type exists in the Legacy DLL, it is never used)
            self.assertIsNone(re.search(r"\bCurrentJumpEndpoint\b", text), rel)


# ==============================================================================================================================================
class Targets(unittest.TestCase):
    """TARGET expectations (all skipped in JF-1), written against the same text so that a later phase can switch them on."""

    @classmethod
    def setUpClass(cls):
        cls.c1 = code(CLASS1)


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


    @unittest.skip("TARGET-B B7 / FC-7 (JF-3): the sender answers an unrunnable jump with a failure response")
    @jf0("J20", "TARGET")
    def test_TARGET_B_J20_the_sender_has_a_failure_response(self):
        self.assertIn("JUMP_FAILED", self.c1)

    @unittest.skip("TARGET-A V-3 (JF-2, Python side): a station index outside the list is refused by the sender's caller; the C# side checks the range too since ST-3b (C11 flipped)")
    @jf0("C11", "TARGET")
    def test_TARGET_A_C11_the_range_is_checked_before_the_request_is_sent(self):
        self.fail("TARGET-A V-3: the check lives on the Python side (see file F1 TARGET_A_S17); there is nothing to state on the C# text")



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
        self.assertGreater(count, 30)                                      # 35 after ST-3b (43 before: the eight TARGET twins that became CURRENT pins are gone)

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
        self.assertEqual(seen, 2)                                          # ST-3b: C15 (JF-3 B6) and J20 (OD-S3-6: no failure response) are the DANGER pins that remain (9 before)

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
        self.assertGreaterEqual(seen, 4)                                   # C05, C15, J20 and the Python-side C11 remain (12 before)

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
