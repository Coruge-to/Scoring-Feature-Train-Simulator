"""Phase PID-D4JA StationIndex ST-3b - the CONTRACT tests of the CURRENT C# sender's jump transaction. Python only; the files are only READ (Class1.cs, CurrentJumpEndpoint.cs,
CurrentJumpExecution.cs, the two project files); nothing here compiles, builds, starts a process, opens a socket or writes a file. The behaviour of the pure decision unit is held by
the compiled tests Handshake/Tests/Test-CurrentJumpST3B.ps1; Class1.cs can not run offline (it needs the BveEX host), so what it does AROUND that unit is held here by the SHAPE of its
statements (a pin is not a run of the behaviour: the live proof is ST-3e2).

The ids are the ones of the Start Audit (13-Red-Test-Plan.md) and of the ST-3b handoff (N-49 / N-50 were proposed there):
  U01  CURRENT-STA-JUMP-DOES-NOT-FIX-REQUESTED-INDEX            (migrated here from tests/red_st0_stationindex_contract.py, same id and code)
  N-22 CURRENT-KEEPS-REQUESTED-INDEX-SAME-POSITION              after a jump the target is the requested index (two stations at one position)
  N-23 CURRENT-KEEPS-REQUESTED-INDEX-NEARBY                     the 50 m position search is not reachable from the jump path (a station 40.5 m / 50 m away)
  N-24 CURRENT-REJECTS-INDEX-LOCATION-CONTRADICTION             the verdict is taken before any host call; a refusal ends the iteration
  N-25 CURRENT-REJECTS-SCOPE-MISMATCH                           scenario / list id / count are compared with what the plugin holds now
  N-26 CURRENT-COMPLETE-SELECTED-IS-THE-API-ARGUMENT            the adopted variable is the API argument AND the selected index of the completion; no request echo
  N-27 CURRENT-NON-JUMP-REINIT-STAYS-POSITION-BASED  (GUARD)    first Tick / scenario change / manual time jump / a changed station count keep the 50 m search
  N-28 CURRENT-LOC-JUMP-REINITIALISES-AND-CARRIES-INDEX         a location jump re-initialises the target state itself and carries the adopted index
  N-29 CURRENT-NUMBERS-ARE-INVARIANT-AND-ROUNDTRIP              STALIST and completion numbers go through the canonical codec; no hand parse in the plugin
  N-30 CURRENT-MISSING-API-OR-TIMEFIELD-ANNOUNCES-NOTHING       no host call and no completion when the jump method or the time field is missing
  N-49 CURRENT-VALIDGRAMMAR-READS-V1-AND-V2-VIA-JUMPWIRE        the grammar gate of the endpoint is the shared reader
  N-50 CURRENT-COMPLETION-IS-SENT-ONCE-PER-REQUEST              one send site, one place that empties the pending jump, an explicit end for every other outcome
  G-PC-1                                                        the Current project links JumpWire.cs; the Legacy project gets a compile-only link and nothing else changes

Each RED fails against the tree BEFORE this phase with ContractViolation whose .code is the declared one (the preconditions are plain assertions that come first, so a moved source
is RED-INVALID and never a RED); the same tests pass against the tree of ST-3b. N-27 is a GUARD: it passes before and after.
"""
import hashlib
import os
import re
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CURRENT_DIR = os.path.join(PLUGIN, "TsScoringPlugin")
CLASS1 = os.path.join(CURRENT_DIR, "Class1.cs")
ENDPOINT = os.path.join(CURRENT_DIR, "CurrentJumpEndpoint.cs")
EXECUTION = os.path.join(CURRENT_DIR, "CurrentJumpExecution.cs")
CURRENT_CSPROJ = os.path.join(CURRENT_DIR, "TsScoringPlugin.csproj")
LEGACY_DIR = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy")
LEGACY_CSPROJ = os.path.join(LEGACY_DIR, "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
JUMPWIRE = os.path.join(PLUGIN, "Handshake", "Telemetry", "Shared", "JumpWire.cs")
JUMPWIRE_ST3A_SHA256 = "8C444AB61096F8D0F372B761B2A848F30C5B66979CCFC0313AF8F68C0B086BCA"      # the file as committed by ST-3a (a435a44): ST-3b links it, it does not change it


class ContractViolation(AssertionError):
    """The tree does not meet the contract; `code` names the violated clause (a RED run compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST3B-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def red(tid, code):
    def deco(fn):
        fn.st3b = {"kind": "RED", "id": tid, "code": code}
        return fn
    return deco


def guard(tid):
    def deco(fn):
        fn.st3b = {"kind": "GUARD", "id": tid, "code": ""}
        return fn
    return deco


def contract(ok, tid, code, detail=""):
    if not ok:
        raise ContractViolation(tid, code, detail)


_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


def cs_code(path):
    """C# source without comments, whitespace squashed, string literals kept as they are."""
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", _TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else " ", text))


def block_at(code, start):
    """The text from the first '{' at/after `start` to its matching '}' (string literals are skipped), or None."""
    i = code.index("{", start)
    depth = 0
    pos = i
    while pos < len(code):
        ch = code[pos]
        if ch == '"':
            m = re.compile(r'"(?:\\.|[^"\\])*"').match(code, pos)
            pos = m.end() if m else pos + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return code[i:pos + 1]
        pos += 1
    return None


def method_body(code, signature):
    """The body of the method whose declaration starts with `signature` (a regular expression), or None."""
    m = re.search(signature, code)
    return None if m is None else block_at(code, m.end() - 1 if code[m.end() - 1] == "{" else m.start())


def compile_items(path):
    """The (Include, Link-or-None) pair of every <Compile> element of an MSBuild project."""
    text = re.sub(r"<!--.*?-->", "", read_text(path), flags=re.S)
    items = []
    for m in re.finditer(r'<Compile\s+Include="([^"]+)"\s*(?:/>|>(.*?)</Compile>)', text, flags=re.S):
        link = re.search(r"<Link>([^<]*)</Link>", m.group(2) or "")
        items.append((m.group(1), link.group(1) if link else None))
    return items


def project_properties(path):
    """{property name: [text, ...]} of every element that sits directly under a PropertyGroup (the MSBuild namespace is dropped)."""
    tree = ET.parse(path)
    out = {}
    for group in tree.getroot():
        if not group.tag.endswith("PropertyGroup"):
            continue
        for p in group:
            name = p.tag.split("}")[-1]
            out.setdefault(name, []).append((group.get("Condition"), (p.text or "").strip()))
    return out


class Fixture(object):
    @classmethod
    def load(cls):
        c1 = cs_code(CLASS1)
        start = c1.index("foreach (JumpInput jumpInput in CollectJumpCommands())")
        end = c1.index("double speed = 0.0;", start)
        loop = c1[start:end]
        i_loc = loop.index('else if (msg.StartsWith("JUMP_LOC_TIME:"))')
        return c1, loop, loop[:i_loc], loop[i_loc:]


C1, LOOP, STA, LOC = Fixture.load()
LOOP_ANCHOR_OK = 'if (msg.StartsWith("JUMP_STA_TIME:"))' in LOOP
POSITION_SEARCH = "if (stationList[i].Location >= location - 50.0)"


def precondition_sources():
    """Plain assertions on the audited anchors: a moved source is RED-INVALID, never a RED."""
    assert 'if (msg.StartsWith("JUMP_STA_TIME:"))' in C1, "the STA branch is not where it was"
    assert 'else if (msg.StartsWith("JUMP_LOC_TIME:"))' in C1, "the LOC branch is not where it was"
    assert POSITION_SEARCH in C1, "the 50 m position search is not where it was"
    assert "pendingJumpComplete" in C1 and "SendJumpComplete(" in C1


# ==============================================================================================================================================
class A_Grammar(unittest.TestCase):
    @red("N-49", "validgrammar-parses-by-hand")
    def test_N49_the_grammar_gate_of_the_endpoint_is_the_shared_reader(self):
        ep = cs_code(ENDPOINT)
        self.assertIn("private static bool ValidGrammar(UInt32 messageType, string text)", ep)                 # the gate is there (a moved source is RED-INVALID)
        body = method_body(ep, r"private static bool ValidGrammar\(UInt32 messageType, string text\) \{")
        self.assertIsNotNone(body)
        contract("JumpWire.ParseRequest(" in body and ".Split(" not in body and "TryParse" not in body, "N-49", "validgrammar-parses-by-hand",
                 "ValidGrammar still splits and parses the command text itself")
        contract("JumpWire.KindSta" in body and "JumpWire.KindLoc" in body, "N-49", "validgrammar-parses-by-hand", "the kind is not read from the shared reader")


# the gate of the validator as it was before ST-3b (PID-D6), squashed and comment free: what the Legacy plane's five argument validator keeps until ST-3c (review of ST-3b, G-3B-2 plan A)
PRE_ST3B_GATE = ('{ string[] parts = text.Split(\':\'); if (parts.Length != 3) return false; int time; if (!Int32.TryParse(parts[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out time)) return false; '
                 'if (messageType == DataPlaneMessageTypes.JumpStationTime) { int index; return parts[0] == "JUMP_STA_TIME" && Int32.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out index); } '
                 'double location; return parts[0] == "JUMP_LOC_TIME" && Double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out location) && !Double.IsNaN(location) && !Double.IsInfinity(location); }')


class A2_LegacyGateKept(unittest.TestCase):
    """Plan A for G-3B-2 (ST-3b): only the Current endpoint reads the command through JumpWire; the Legacy plane keeps the grammar it had. Phase ST-3c ENDED the Legacy part of this plan: the Legacy plane builds the
    six argument form as well (see test_only_the_current_endpoint_builds_the_shared_gate). The retained five argument validator is still held byte for byte (the first two tests): it is dead code in the product now."""

    def test_the_old_three_field_gate_is_kept_byte_for_byte_as_ValidGrammarV1(self):
        ep = cs_code(ENDPOINT)
        body = method_body(ep, r"private static bool ValidGrammarV1\(UInt32 messageType, string text\) \{")
        self.assertEqual(body, PRE_ST3B_GATE)

    def test_the_five_argument_validator_is_the_old_gate_and_the_six_argument_one_chooses(self):
        ep = cs_code(ENDPOINT)
        self.assertIn("internal JumpCommandValidator(int bvePid, UInt32 generation, byte[] token, IEndpointSource source, Action<string> log) : this(bvePid, generation, token, source, log, false) { }", ep)
        self.assertIn("internal JumpCommandValidator(int bvePid, UInt32 generation, byte[] token, IEndpointSource source, Action<string> log, bool sharedWireGrammar) {", ep)
        self.assertIn('if (!(sharedWireGrammar ? ValidGrammar(env.MessageType, text) : ValidGrammarV1(env.MessageType, text))) { reason = "payload-grammar"; return null; }', ep)
        self.assertEqual(len(re.findall(r"\bValidGrammarV1\(", ep)), 2)                      # the definition and the one call
        self.assertEqual(len(re.findall(r"(?<![A-Za-z])ValidGrammar\(", ep)), 2)             # the definition and the one call

    def test_only_the_current_endpoint_builds_the_shared_gate(self):
        ep = cs_code(ENDPOINT)
        builds = re.findall(r"new JumpCommandValidator\([^;]*;", ep)
        self.assertEqual(builds, ["new JumpCommandValidator(bvePid, generation, token, source, log, true);"])
        src_dir = os.path.join(LEGACY_DIR, "src")
        legacy_builds = []
        for name in sorted(os.listdir(src_dir)):
            if not name.endswith(".cs"):
                continue
            text = cs_code(os.path.join(src_dir, name))
            self.assertNotIn("sharedWireGrammar", text, name)
            legacy_builds += [(name, b) for b in re.findall(r"new JumpCommandValidator\([^;]*;", text)]
        # Phase ST-3c (intended update; was the FIVE argument form = the old predicate): the Legacy plane builds the SIX argument form too, i.e. the shared JumpWire grammar; the five argument form and
        # ValidGrammarV1 stay in CurrentJumpEndpoint.cs (a Current product file ST-3c does not touch) but no plane builds it any more (its removal is a Current change, ST-3e)
        self.assertEqual(legacy_builds, [("LegacyJumpEndpoint.cs", "new JumpCommandValidator(env.BvePid, generation, token, recording, note, true);")])


# ==============================================================================================================================================
class B_Selection(unittest.TestCase):
    @red("U01", "CURRENT-STA-JUMP-DOES-NOT-FIX-REQUESTED-INDEX")
    def test_U01_the_current_sender_fixes_the_requested_index(self):
        precondition_sources()
        contract(re.search(r"targetStationIndex = (sIdx|requestedStationIndex|pendingJumpStationIndex)", C1) is not None, "U01",
                 "CURRENT-STA-JUMP-DOES-NOT-FIX-REQUESTED-INDEX", "targetStationIndex is only ever assigned by the 50 m position search or advanced, never from the requested index")

    @red("N-22", "target-not-from-requested-index")
    def test_N22_the_target_after_a_jump_is_the_requested_index_even_at_the_same_position(self):
        precondition_sources()
        body = method_body(C1, r"private void SelectTargetByRequestedIndex\(int requestedStationIndex, double location, bool areDoorsClosed\) \{")
        contract(body is not None and "targetStationIndex = requestedStationIndex;" in body, "N-22", "target-not-from-requested-index", "no function assigns the target from the requested index")
        contract("ResolveRequestedTarget(requestedTargetIndex, requestedTargetLocation," in C1 and "if (requestedStationIndex >= 0) SelectTargetByRequestedIndex(requestedStationIndex," in C1,
                 "N-22", "target-not-from-requested-index", "the re-initialisation does not take the requested index")
        contract(body is not None and "stationList[i]" not in body and "for (" not in body, "N-22", "target-not-from-requested-index", "the requested-index function searches")

    @red("N-23", "position-search-reachable-from-jump")
    def test_N23_the_50_m_search_is_not_reachable_from_the_jump_path(self):
        precondition_sources()
        by_position = method_body(C1, r"private void SelectTargetByPosition\(double location, bool areDoorsClosed\) \{")
        contract(by_position is not None and POSITION_SEARCH in by_position, "N-23", "position-search-reachable-from-jump", "the 50 m search does not live in its own function")
        contract(C1.count("location - 50.0") == 1, "N-23", "position-search-reachable-from-jump", "the 50 m comparison exists more than once")
        calls = re.findall(r"SelectTargetByPosition\(", C1)
        contract(len(calls) == 2 and "else if (!requestedTargetRefused) SelectTargetByPosition(location, areDoorsClosed);" in C1, "N-23", "position-search-reachable-from-jump",
                 "the position search is called from more than the single arm that carries no index")
        by_index = method_body(C1, r"private void SelectTargetByRequestedIndex\(int requestedStationIndex, double location, bool areDoorsClosed\) \{")
        contract(by_index is not None and "Location >=" not in by_index and "for (" not in by_index and "foreach" not in by_index and "break;" not in by_index,
                 "N-23", "position-search-reachable-from-jump", "the requested-index function contains a search")
        contract("SelectTargetByPosition" not in LOOP and "location - 50.0" not in LOOP, "N-23", "position-search-reachable-from-jump", "the jump branches reach the position search")
        resolve = cs_code(EXECUTION)
        contract("Math." not in method_body(resolve, r"internal static int ResolveRequestedTarget\(int requestedIndex, double expectedLocation, double\[\] locations, out string reason\) \{"),
                 "N-23", "position-search-reachable-from-jump", "the resolver of the requested target does arithmetic on a position")

    @red("N-28", "loc-branch-does-not-reinitialise")
    def test_N28_a_location_jump_reinitialises_the_target_state_and_carries_the_index(self):
        precondition_sources()
        contract("ReinitializeTargetStateAfterJump();" in LOC and 'BeginPendingJump("LOC", jumpRequestId, jumpDecision);' in LOC, "N-28", "loc-branch-does-not-reinitialise",
                 "the LOC branch does not re-initialise the target state itself or does not begin the pending jump with the adopted decision")
        reinit = method_body(C1, r"private void ReinitializeTargetStateAfterJump\(\) \{")
        contract(reinit is not None and "isInitialized = false;" in reinit, "N-28", "loc-branch-does-not-reinitialise", "the shared re-initialisation does not clear isInitialized")
        contract("pendingJumpStationIndex = -1;" not in LOC and "pendingJumpStationIndex = -1;" not in STA, "N-28", "loc-branch-does-not-reinitialise", "a branch still writes -1 as the selected index")
        begin = method_body(C1, r"private void BeginPendingJump\(string kind, byte\[\] requestId, TSScoringPlugin\.DataPlane\.CurrentJumpDecision decision\) \{")
        contract(begin is not None and "pendingJumpStationIndex = decision.StationIndex;" in begin and "requestedTargetIndex = decision.StationIndex;" in begin, "N-28",
                 "loc-branch-does-not-reinitialise", "the pending jump does not carry the adopted index")

    @guard("N-27")
    def test_N27_a_reinitialisation_without_an_index_keeps_the_position_search(self):
        precondition_sources()
        self.assertEqual(C1.count("location - 50.0"), 1)
        self.assertIn("hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[i].Location - location) < 50.0;", C1)                    # the door state of the found station (unchanged)
        self.assertRegex(C1, r"if \(!BveHacker\.IsScenarioCreated\) \{[^}]*isInitialized = false;")                                              # no scenario
        self.assertRegex(C1, r"if \(!object\.Equals\(currentScenario, BveHacker\.Scenario\)\) \{.*?isInitialized = false;")                      # scenario change
        self.assertRegex(C1, r"if \(lastTimeMs != 0 && Math\.Abs\(jumpTimeErrorMs\) > 300\) \{ isInitialized = false;")                         # a manual time jump / a freeze
        self.assertIn("if (!isInitialized || stations.Count != stationList.Count)", C1)                                                          # the first Tick and a changed station count
        self.assertIn("jumpCounter++;", C1)


# ==============================================================================================================================================
class C_Refusal(unittest.TestCase):
    @red("N-24", "no-verdict-before-host-call")
    def test_N24_the_verdict_is_taken_before_any_host_call_and_a_refusal_ends_the_iteration(self):
        precondition_sources()
        self.assertIn(".Invoke(", LOOP)
        i_judge = LOOP.find("CurrentJumpExecution.Judge(msg, BuildJumpView())")
        contract(i_judge >= 0 and i_judge < LOOP.index(".Invoke("), "N-24", "no-verdict-before-host-call", "the command is not judged before the first host call")
        contract("if (!jumpDecision.Accepted) { JumpRefused(jumpRequestId, jumpDecision, jumpDecision.Reason, jumpDecision.Detail); continue; }" in LOOP, "N-24", "no-verdict-before-host-call",
                 "a refused verdict does not end the iteration before the branches")
        contract(LOOP.index("if (!jumpDecision.Accepted)") < LOOP.index('if (msg.StartsWith("JUMP_STA_TIME:"))'), "N-24", "no-verdict-before-host-call", "the verdict comes after the branches")
        unit = cs_code(EXECUTION)
        contract("if (view.Locations[r.StationIndex] != r.Location) { d.Reason = RLocationMismatch; return d; }" in unit and "if (r.StationIndex < 0 || r.StationIndex >= view.Locations.Length)" in unit,
                 "N-24", "no-verdict-before-host-call", "the unit does not compare the named index with the named location")

    @red("N-25", "scope-not-compared")
    def test_N25_scenario_list_and_count_are_compared_with_what_the_plugin_holds_now(self):
        precondition_sources()
        view = method_body(C1, r"private TSScoringPlugin\.DataPlane\.CurrentJumpView BuildJumpView\(\) \{")
        contract(view is not None and "view.ScenarioId = scenarioId;" in view and "view.ListReady = stidxListReady;" in view and "view.ListId = stidxListId;" in view
                 and "view.ListCount = stidxListCount;" in view and "view.Locations = StationLocations();" in view, "N-25", "scope-not-compared", "the plugin does not hand its scenario / list identity / station list to the judgement")
        unit = cs_code(EXECUTION)
        for word in ("RScenarioMismatch", "RListNotReady", "RListMismatch", "RCountMismatch", "RListInconsistent"):
            contract(("d.Reason = " + word + ";") in unit, "N-25", "scope-not-compared", "the judgement has no " + word)

    @red("N-30", "missing-api-announces-completion")
    def test_N30_a_missing_jump_method_or_time_field_makes_no_call_and_no_completion(self):
        precondition_sources()
        for name, branch, method in (("STA", STA, "jumpStaMethod"), ("LOC", LOC, "jumpMethod")):
            contract((("if (%s == null)" % method) in branch) and (("if (%s != null)" % method) not in branch), "N-30", "missing-api-announces-completion",
                     name + ": the missing jump method is not refused")
            contract("if (timeField == null)" in branch and "FindJumpTimeField(scenario, bindFlagsAll, out rawTimeMgr)" in branch, "N-30", "missing-api-announces-completion",
                     name + ": the missing time field is not refused")
            contract(branch.index("if (timeField == null)") < branch.index(".Invoke("), "N-30", "missing-api-announces-completion", name + ": the time field is looked for after the host was called")
            contract(branch.index("if (%s == null)" % method) < branch.index(".Invoke("), "N-30", "missing-api-announces-completion", name + ": the method is looked for after the host was called")
            contract(re.search(r"if \(%s == null\) \{ JumpRefused\([^;]*\); continue; \}" % method, branch) is not None, "N-30", "missing-api-announces-completion",
                     name + ": a missing jump method does not end the iteration")
            contract(branch.index("BeginPendingJump(") > branch.index(".Invoke("), "N-30", "missing-api-announces-completion", name + ": the pending jump begins before the host call")


# ==============================================================================================================================================
class D_Selected(unittest.TestCase):
    @red("N-26", "selected-is-request-echo")
    def test_N26_the_adopted_variable_is_the_api_argument_and_the_selected_index(self):
        precondition_sources()
        contract("int adoptedIndex = jumpDecision.StationIndex;" in LOOP and "double adoptedLocation = jumpDecision.Location;" in LOOP, "N-26", "selected-is-request-echo",
                 "the plugin does not keep the adopted values of the verdict in variables")
        contract(re.search(r"jumpStaMethod\.Invoke\( ?rawScenario, new object\[\] \{ adoptedIndex \} ?\);", STA) is not None, "N-26", "selected-is-request-echo",
                 "the station jump is not called with the adopted index")
        contract("jumpMethod.Invoke(rawScenario, new object[] { adoptedLocation, 0 });" in LOC, "N-26", "selected-is-request-echo", "the location jump is not called with the adopted location")
        contract(not re.search(r"\bsIdx\b", C1) and not re.search(r"\brLoc\b", C1), "N-26", "selected-is-request-echo", "a variable parsed from the request text is still used")
        completion = C1[C1.index("string completeReason = null;"):C1.index("if (completeMessage == null)")]
        contract("FormatCompletion( pendingJumpType, pendingJumpStationIndex, completedLocation, completedTime, jumpCounter, scenarioId, stidxListId, stationList.Count, out completeReason);" in completion,
                 "N-26", "selected-is-request-echo", "the completion does not carry the adopted index, the observed position and the current scope")
        contract(len(re.findall(r"pendingJumpStationIndex = ", C1)) >= 3, "N-26", "selected-is-request-echo", "the pending index is not written by the pending jump")

    @red("N-29", "culture-dependent-numbers")
    def test_N29_the_numbers_of_the_plugin_go_through_the_canonical_codec(self):
        precondition_sources()
        contract("StationLocationText(st.Location)" in C1 and "{st.Location}" not in C1, "N-29", "culture-dependent-numbers", "the STALIST position is not written by the canonical codec")
        contract('$"JUMP_COMPLETE:' not in C1 and "{completedLocation}" not in C1 and "FormatCompletion(" in C1, "N-29", "culture-dependent-numbers",
                 "the completion is still an interpolated string with the current culture")
        contract("double.TryParse(" not in C1 and "int.TryParse(parts[" not in C1 and "Split(':')" not in C1, "N-29", "culture-dependent-numbers", "the plugin still parses the command text by hand")


# ==============================================================================================================================================
class E_Once(unittest.TestCase):
    @red("N-50", "pending-outlives-its-request")
    def test_N50_the_completion_is_sent_once_per_request_and_every_other_end_is_explicit(self):
        precondition_sources()
        self.assertEqual(len(re.findall(r"\.SendJumpComplete\(", C1)), 1)                       # one send site (true before and after)
        clear = method_body(C1, r"private void ClearPendingJump\(\) \{")
        contract(clear is not None, "N-50", "pending-outlives-its-request", "no single place empties the pending jump")
        flag_clears = re.findall(r"(?<!bool )pendingJumpComplete = false;", C1)
        contract(len(flag_clears) == 1 and "pendingJumpComplete = false;" in clear, "N-50", "pending-outlives-its-request", "the pending flag is cleared in more than one place")
        contract(len(re.findall(r"pendingJumpComplete = true;", C1)) == 1, "N-50", "pending-outlives-its-request", "the pending flag is set in more than one place")
        i_none = C1.index("if (!BveHacker.IsScenarioCreated)")
        no_scenario = C1[i_none:C1.index("if (udpClient != null)", i_none)]
        i_change = C1.index("if (!object.Equals(currentScenario, BveHacker.Scenario))")
        change = C1[i_change:C1.index("var bindFlagsAllDump", i_change)]
        contract("AbandonPendingJump(" in no_scenario and "AbandonPendingJump(" in change, "N-50", "pending-outlives-its-request", "a pending jump survives the end or the change of its scenario")
        begin = method_body(C1, r"private void BeginPendingJump\(string kind, byte\[\] requestId, TSScoringPlugin\.DataPlane\.CurrentJumpDecision decision\) \{")
        contract(begin is not None and "if (pendingJumpComplete) AbandonPendingJump(" in begin, "N-50", "pending-outlives-its-request", "a new jump does not end the one it supersedes")
        send = C1[C1.index("if (batch.SendJumpComplete(completeBytes, pendingJumpRequestId))"):]
        send = send[:send.index("}") + 1]
        contract("ClearPendingJump();" in send, "N-50", "pending-outlives-its-request", "the pending jump is not emptied after the send")
        abandon = method_body(C1, r"private void AbandonPendingJump\(string reason, string detail\) \{")
        contract(abandon is not None and "ClearPendingJump();" in abandon, "N-50", "pending-outlives-its-request", "an abandoned jump is not emptied")


# ==============================================================================================================================================
class F_Projects(unittest.TestCase):
    @red("G-PC-1", "jumpwire-not-linked-into-current")
    def test_GPC1_the_current_project_links_jumpwire_once_and_compiles_the_unit(self):
        current = compile_items(CURRENT_CSPROJ)
        self.assertEqual([t for t in current if t[0] == "CurrentJumpEndpoint.cs"], [("CurrentJumpEndpoint.cs", None)])                           # the existing reference stays
        self.assertEqual([t for t in current if t[0].endswith("StationListIdentity.cs")], [("..\\Handshake\\Telemetry\\Shared\\StationListIdentity.cs", "Shared\\StationListIdentity.cs")])
        wire = [t for t in current if t[0].endswith("JumpWire.cs")]
        contract(wire == [("..\\Handshake\\Telemetry\\Shared\\JumpWire.cs", "Shared\\JumpWire.cs")], "G-PC-1", "jumpwire-not-linked-into-current", "JumpWire.cs is not linked once, as the other shared files")
        contract([t for t in current if t[0] == "CurrentJumpExecution.cs"] == [("CurrentJumpExecution.cs", None)], "G-PC-1", "jumpwire-not-linked-into-current", "CurrentJumpExecution.cs is not compiled once")
        includes = [t[0] for t in current]
        contract(len(includes) == len(set(includes)) and not any("*" in i for i in includes), "G-PC-1", "jumpwire-not-linked-into-current", "a duplicate or a wildcard Compile item")

    LEGACY_EXPECTED = sorted([
        ("src\\AssemblyInfo.cs", None), ("src\\LegacyApi.cs", None), ("..\\..\\..\\TsScoringPlugin\\CurrentDataPlane.cs", "Shared\\CurrentDataPlane.cs"),
        ("..\\..\\..\\TsScoringPlugin\\CurrentJumpEndpoint.cs", "Shared\\CurrentJumpEndpoint.cs"), ("src\\LegacyDataPlaneSink.cs", None), ("src\\LegacyGroundLimits.cs", None),
        ("src\\LegacyHandleContract.cs", None), ("..\\Shared\\GenericHandleTextContract.cs", "Shared\\GenericHandleTextContract.cs"), ("src\\LegacyInputProbe.cs", None),
        ("..\\Shared\\DataPlaneProtocol.cs", "Shared\\DataPlaneProtocol.cs"), ("..\\Shared\\TelemetryDirectoryReader.cs", "Shared\\TelemetryDirectoryReader.cs"),
        ("src\\LegacyInputTelemetry.cs", None), ("src\\LegacyJumpCommandQueue.cs", None), ("src\\LegacyJumpControlPlane.cs", None), ("src\\LegacyJumpEndpoint.cs", None),
        ("src\\LegacyJumpExecutor.cs", None), ("src\\LegacyScoringProbe.cs", None), ("src\\LegacyStationTimeline.cs", None), ("src\\LegacyTelemetrySession.cs", None),
        ("src\\LegacyTelemetryExtension.cs", None), ("..\\Shared\\TelemetryContract.cs", "Shared\\TelemetryContract.cs"), ("..\\Shared\\StationListIdentity.cs", "Shared\\StationListIdentity.cs"),
        ("..\\Shared\\JumpWire.cs", "Shared\\JumpWire.cs"),
        ("..\\Shared\\PackageContract.cs", "Shared\\PackageContract.cs")], key=lambda t: t[0])             # Phase ST-3e0 (pin moved): the package contract (TSJUMP2, constants only) is the one more link

    @red("G-PC-1", "legacy-jumpwire-link-missing")
    def test_GPC1_the_legacy_project_gets_one_compile_only_link_of_jumpwire_and_nothing_else_changes(self):
        legacy = compile_items(LEGACY_CSPROJ)
        # the facts that must hold before AND after (plain assertions: a failure here is RED-INVALID)
        self.assertEqual([t for t in legacy if t[0].endswith("CurrentJumpEndpoint.cs")], [("..\\..\\..\\TsScoringPlugin\\CurrentJumpEndpoint.cs", "Shared\\CurrentJumpEndpoint.cs")])
        props = project_properties(LEGACY_CSPROJ)
        self.assertEqual(props["TargetFrameworkVersion"], [(None, "v4.8")])
        self.assertEqual(props["DefineConstants"], [(None, "TRACE"), ("'$(LegacyJumpExec)' == 'true'", "$(DefineConstants);LEGACY_JUMP_EXEC")])
        self.assertEqual(props["LangVersion"], [(None, "9.0")])
        self.assertEqual(props["TreatWarningsAsErrors"], [(None, "true")])
        self.assertNotIn("ProjectReference", read_text(LEGACY_CSPROJ))
        self.assertEqual(sorted(set(re.findall(r'<Reference Include="([^"]+)"', read_text(LEGACY_CSPROJ)))),
                         ["AtsEx.PluginHost", "BveTypes", "FastCaching", "FastMember", "System", "System.Core", "TypeWrapping"])
        # the contract of G-PC-1
        wire = [t for t in legacy if t[0].endswith("JumpWire.cs")]
        contract(wire == [("..\\Shared\\JumpWire.cs", "Shared\\JumpWire.cs")], "G-PC-1", "legacy-jumpwire-link-missing", "the Legacy project does not link JumpWire.cs exactly once in the form of the other shared links")
        contract(sorted(legacy, key=lambda t: t[0]) == self.LEGACY_EXPECTED, "G-PC-1", "legacy-jumpwire-link-missing", "the Legacy compile set is not the old set plus the one link")
        includes = [t[0] for t in legacy]
        contract(len(includes) == len(set(includes)), "G-PC-1", "legacy-jumpwire-link-missing", "a duplicate Compile Include")
        contract(not any("CurrentJumpExecution" in i for i in includes), "G-PC-1", "legacy-jumpwire-link-missing", "the Current-only unit reaches the Legacy project")

    def test_GPC1_the_legacy_runtime_does_not_name_jumpwire(self):
        """Phase ST-3c (intended update): the Legacy project links JumpWire.cs and TWO Legacy sources name it - the executor (the claim reader, the judgement and the completion) and the timeline (the
        STALIST positions); no Legacy source names the Current-only unit or the Current plugin. (Before ST-3c: compile-only, no Legacy source named the codec.)"""
        src = os.path.join(LEGACY_DIR, "src")
        named = []
        for base, _dirs, files in os.walk(LEGACY_DIR):
            if os.sep + "obj" in base or os.sep + "out" in base:
                continue
            for name in files:
                if name.endswith(".cs"):
                    text = cs_code(os.path.join(base, name))
                    if "JumpWire" in text:
                        named.append(name)
                    self.assertNotIn("CurrentJumpExecution", text, name)
        self.assertEqual(sorted(named), ["LegacyJumpExecutor.cs", "LegacyStationTimeline.cs"])
        executor = cs_code(os.path.join(src, "LegacyJumpExecutor.cs"))
        self.assertIn("JumpWireRequest w = JumpWire.ParseRequest(r.Text, out why);", executor)                      # the Legacy claim reads the command with the shared reader (ST-3c)
        self.assertNotIn(".Split(", executor)                                                                         # and has no parser of its own any more

    def test_the_jumpwire_source_is_the_one_of_st3a(self):
        with open(JUMPWIRE, "rb") as f:
            text = f.read().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")                           # LF-normalised, as the other source pins
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest().upper(), JUMPWIRE_ST3A_SHA256)


# ==============================================================================================================================================
class G_Shape(unittest.TestCase):
    """GREEN-only structure of the new code (these hold for the tree of ST-3b; the unit they read does not exist before it)."""

    def test_the_decisions_live_in_the_pure_unit_and_the_diagnostics_have_three_call_sites(self):
        self.assertTrue(os.path.isfile(EXECUTION))
        sites = len(re.findall(r"\bJumpDiag\(", C1))
        self.assertEqual(sites, 4)                                                                                   # the definition and the three writers (refused / aborted / completed)
        for fn in (r"private void JumpRefused\(", r"private void AbandonPendingJump\(string reason, string detail\) \{"):
            self.assertIsNotNone(re.search(fn, C1))
        self.assertEqual(len(re.findall(r"RefusedLine\(", C1)), 1)
        self.assertEqual(len(re.findall(r"AbortedLine\(", C1)), 1)
        self.assertEqual(len(re.findall(r"CompletedLine\(", C1)), 1)

    def test_the_reinitialisation_is_consumed_once_and_a_refusal_never_falls_back_to_the_position(self):
        i = C1.index("int requestedStationIndex = -1;")
        block = C1[i:C1.index("isInitialized = true;", i)]
        self.assertIn("requestedTargetIndex = -1; requestedTargetLocation = 0.0;", block)                             # consumed whatever the verdict
        self.assertIn("requestedTargetRefused = true; AbandonPendingJump(reinitReason, \"-\");", block)
        self.assertIn("else if (!requestedTargetRefused) SelectTargetByPosition(location, areDoorsClosed);", block)

    def test_the_completion_is_never_a_stand_in(self):
        self.assertNotIn("completedLocation = -1.0", C1)
        self.assertNotIn("completedTime = -1", C1)
        self.assertIn("completedLocationRead = true;", C1)
        self.assertIn("completedTimeRead = true;", C1)

    def test_the_actual_location_is_the_one_the_host_reports(self):
        self.assertIn("completedLocation = BveHacker.Scenario.VehicleLocation.Location;", C1)

    def test_the_station_and_location_jumps_use_the_same_helper_for_the_time_field(self):
        self.assertEqual(len(re.findall(r"FindJumpTimeField\(scenario, bindFlagsAll, out rawTimeMgr\)", C1)), 2)

    def test_the_door_state_expression_is_the_one_of_before_in_both_selectors(self):
        self.assertEqual(C1.count("hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList["), 2)


# ==============================================================================================================================================
class H_RefusalDiagnostic(unittest.TestCase):
    """G-RC-1 (Commit Prep): the refusal line says WHICH index and count a command named. The values are read by position for the line only (CurrentJumpExecution.Describe); the verdict stays the
    shared reader's and the plugin's own. The behaviour is held by the compiled tests (D01..D27, B08..B10); these pins hold the SHAPE around it."""

    EXEC = cs_code(EXECUTION)

    def test_GRC1_only_the_pure_unit_knows_the_diagnostic(self):
        for name in (r"\bCurrentJumpDiagnostic\b", r"\bDescribe\(", r"\bDiagNumber\b", r"\bDiagField\b", r"\.Diagnostic\b", r"req_count", r"current_count", r"\bMaxDiagValueLength\b"):
            self.assertIsNone(re.search(name, C1), name + " reached Class1.cs (the plugin must not read or build the diagnostic)")
            self.assertIsNone(re.search(name, cs_code(ENDPOINT)), name + " reached the endpoint")
            self.assertIsNone(re.search(name, cs_code(JUMPWIRE)), name + " reached the shared wire codec")
        self.assertIn("internal static CurrentJumpDiagnostic Describe(string text, CurrentJumpView view)", self.EXEC)
        src = os.path.join(LEGACY_DIR, "src")
        for name in sorted(os.listdir(src)):
            if name.endswith(".cs"):
                text = cs_code(os.path.join(src, name))
                if name != "LegacyJumpExecutor.cs":                                                                    # Phase ST-3c: the Legacy judgement has its OWN isolated extraction (LegacyJumpJudge.Describe)
                    self.assertNotIn("Describe(", text, name)
                self.assertNotIn("CurrentJumpDiagnostic", text, name)

    def test_GRC1_the_diagnostic_is_set_after_the_verdict_and_read_only_by_the_line(self):
        judge = method_body(self.EXEC, r"internal static CurrentJumpDecision Judge\(string text, CurrentJumpView view\) ")
        self.assertIsNotNone(judge)
        self.assertNotIn("return JudgeCore(", judge)                                                                   # the verdict is no longer returned before the diagnostic is attached
        self.assertLess(judge.index("JudgeCore(text, view, d);"), judge.index("d.Diagnostic = Describe(text, view);"))
        self.assertLess(judge.index("d.Diagnostic = Describe(text, view);"), judge.index("return d;", judge.index("d.Diagnostic = Describe(text, view);")))
        core = method_body(self.EXEC, r"private static CurrentJumpDecision JudgeCore\(string text, CurrentJumpView view, CurrentJumpDecision d\) ")
        self.assertIsNotNone(core)
        self.assertNotIn("Diag", core)
        for sig in (r"internal static int ResolveRequestedTarget\(int requestedIndex, double expectedLocation, double\[\] locations, out string reason\) ",
                    r"internal static string FormatCompletion\(string kind, int selectedIdx, double actualLocation, int timeMs, int jumpCount, int scenarioId, string listId, int count, out string reason\) "):
            body = method_body(self.EXEC, sig)
            self.assertIsNotNone(body, sig)
            self.assertNotIn("Diag", body)
        self.assertEqual(len(re.findall(r"\.Diagnostic\b", self.EXEC)), 3)                                             # one write (Judge), two reads (RefusedLine)

    def test_GRC1_the_line_has_the_three_values_through_the_number_guard_within_the_unchanged_cap(self):
        line = method_body(self.EXEC, r"internal static string RefusedLine\(byte\[\] requestId, CurrentJumpDecision d, string reason, string detail\) ")
        self.assertIsNotNone(line)
        self.assertIn('" req_idx=" + DiagNumber(diag.RequestedIndexText) + " req_count=" + DiagNumber(diag.RequestedCountText) + " current_count=" + DiagNumber(diag.CurrentCountText) + " scope="', line)
        self.assertEqual(len(re.findall(r"DiagNumber\(", line)), 3)
        self.assertIn("internal const int MaxLineLength = 200;", self.EXEC)                                           # the cap is the one of before
        describe = method_body(self.EXEC, r"internal static CurrentJumpDiagnostic Describe\(string text, CurrentJumpView view\) ")
        self.assertIsNotNone(describe)
        self.assertIn("catch", describe)
        self.assertNotIn("throw", describe)
        self.assertNotIn("JumpWire.Parse", describe)                                                                   # not a second reader
        self.assertNotIn("TryParse", self.EXEC)
        self.assertNotIn("Convert.", self.EXEC)
        self.assertEqual(len(re.findall(r"RefusedLine\(", C1)), 1)                                                     # still one refusal formatter site, so one line per refused request


if __name__ == "__main__":
    unittest.main()
