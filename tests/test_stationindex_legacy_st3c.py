"""Phase PID-D4JA StationIndex ST-3c - the CONTRACT tests of the LEGACY (AtsEX) sender's jump transaction and of the STALIST acknowledgement (R1-B), as they can be read from the SOURCES.
Python only; the files are only READ; nothing here compiles, builds, starts a process, opens a socket or writes a file. The BEHAVIOUR of the Legacy jump plane (claim, judgement, execution,
completion, target, breaker, R1-B) is held by the compiled tests Handshake/Tests/Test-LegacyJumpST3C.ps1 (cases N-31 .. N-68, R1B-1 .. R1B-8); what this file holds is the SHAPE of the
statements that those tests can not see (a hand parse that was left behind, a request echoed instead of the adopted value, a flag set without the acknowledgement) and the fences around the
change (what ST-3c does not touch). A pin is not a run of the behaviour: the live proof is ST-3e2.

The ids are the ones of the Start Audit (13-Red-Test-Plan.md) and the ones that ST-3c fixed before it wrote a line of product (artifact 04-Red-Baseline.md):
  N-34  LEGACY-COMPLETE-SELECTED-IS-THE-HOST-ARGUMENT           the completion's selected index is the field that the host call received; no request echo, no -1 for a location jump
  N-38  LEGACY-EXISTING-JUMP-CONTRACT-UNCHANGED  (GUARD)         TTL 5000, breaker 3, the order of the claim checks, the single place where a failure is counted
  N-51  LEGACY-GATE-IS-THE-SHARED-JUMPWIRE                       the Legacy plane builds the six argument validator (the shared JumpWire grammar); there is no other predicate
  N-52  LEGACY-V2-IS-READ-BY-THE-SHARED-READER                   the claim reads the command with JumpWire.ParseRequest; no Split / TryParse of its own
  N-55  LEGACY-VALIDATION-REFUSAL-HAPPENS-BEFORE-THE-CLAIM       the judgement sits between the owner check and TryClaim, and the claim entry never counts a failure
  N-64  LEGACY-REQUEST-TARGET-IS-NOT-A-POSITION-LOOKUP           the requested target resolver has no loop and no arithmetic on a position (U13 anchor: the identifier RequestTarget)
  N-65  LEGACY-STALIST-LOCATIONS-ARE-CANONICAL                   ComposeStaList writes the positions through the shared codec
  N-66  LEGACY-REFUSAL-DIAGNOSTIC-IS-ISOLATED                    the numbers of the refusal line are set after the verdict and printed through a number guard
  N-69  ST3C-DOES-NOT-TOUCH-CURRENT-OR-PYTHON  (GUARD)           the Current product, the Python product, the shared codec and the project files are byte-identical to the tree of ST-3b (blob ids)
  R1B-9 LEGACY-STALIST-IS-NOT-MARKED-SENT-UNCONDITIONALLY        no unconditional flag after a Send; the acknowledgement interface exists and is Legacy only
  U13   the declared RED of ST-0 stays a RED (its formula grows in the same change that introduces RequestTarget)

Each RED fails against the tree BEFORE this phase with ContractViolation whose .code is the declared one (the preconditions are plain assertions that come first, so a moved source is
RED-INVALID and never a RED); the same tests pass against the tree of ST-3c. N-38 and N-69 are GUARDs: they pass before and after.
"""
import hashlib
import os
import re
import subprocess
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CURRENT_DIR = os.path.join(PLUGIN, "TsScoringPlugin")
LEGACY_DIR = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy")
LEGACY_SRC = os.path.join(LEGACY_DIR, "src")
SHARED_DIR = os.path.join(PLUGIN, "Handshake", "Telemetry", "Shared")
LEGACY_CSPROJ = os.path.join(LEGACY_DIR, "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
CURRENT_CSPROJ = os.path.join(CURRENT_DIR, "TsScoringPlugin.csproj")
ENDPOINT = os.path.join(LEGACY_SRC, "LegacyJumpEndpoint.cs")
EXECUTOR = os.path.join(LEGACY_SRC, "LegacyJumpExecutor.cs")
PLANE = os.path.join(LEGACY_SRC, "LegacyJumpControlPlane.cs")
TIMELINE = os.path.join(LEGACY_SRC, "LegacyStationTimeline.cs")
SESSION = os.path.join(LEGACY_SRC, "LegacyTelemetrySession.cs")
SINK = os.path.join(LEGACY_SRC, "LegacyDataPlaneSink.cs")
CONTRACT = os.path.join(SHARED_DIR, "TelemetryContract.cs")
RED_ST0 = os.path.join(HERE, "red_st0_stationindex_contract.py")

# the files that ST-3c does not touch, as committed by ST-3b (9d8ef74): git blob ids. Phase ST-3d changes three of the Python ones on purpose (main.py, scoring_logic.py, managed_input.py: their rows are gone;\n# the Python side of the transaction is held by tests/test_stationindex_python_st3d.py now); station_identity.py, jump_wire.py, current_jump_client.py and dataplane_contract.py stay byte-identical.
UNTOUCHED = {
    # Phase U10 changed Class1.cs on purpose (the stop range of the station list builder, tests\test_stationindex_station_range_u10.py): the blob moved from a1c34ae7... (ST-3b); ST-3c itself still does not touch it
    # Time Fix A changed Class1.cs on purpose (the arrival fill-in of the station list builder, tests\test_timefix_a_terminal_arrival.py): the blob moved from a9b420a0... (U10)
    # Time Fix B2 changed Class1.cs on purpose (the operational stop leaves the target at once when the vehicle leaves, tests\test_timefix_b2_operational_stop_contract.py / Handshake\Tests\Test-TimeFixB2.ps1): the blob moved from b703adb0... (Time Fix A)
    "TsScoringPlugin/TsScoringPlugin/Class1.cs": "04a120116b8ab9e12af28ceb297e57e416ae9b27",
    "TsScoringPlugin/TsScoringPlugin/CurrentJumpEndpoint.cs": "3e0d3bffbb74e4a2ecc6d10d378a8b6e2788ae6f",
    "TsScoringPlugin/TsScoringPlugin/CurrentJumpExecution.cs": "8a54d6a14100e0021ca248d28369c335f965fafe",
    "TsScoringPlugin/TsScoringPlugin/CurrentDataPlane.cs": "71b0ebaa6f52871ceb2a59456a2b527041241c46",
    # Phase ST-3e0 changes both projects on purpose (exactly one Compile item of Shared\PackageContract.cs each; the blobs moved from 61092229... / defbe148...): their rows are gone; the projects are held by
    # tests/test_stationindex_package_st3e0.py (E0-25: each differs from the blob of 0b8e511 by that one item only) and by the compile lists of this file and of test_jf1_current_csharp_source_pins.py
    "TsScoringPlugin/TsScoringPlugin/AtsLoggerPlugin.cs": "22209df3e50762dd17c68c9bb788af6f8faf98b7",
    "TsScoringPlugin/TsScoringPlugin/Properties/AssemblyInfo.cs": "e704abd24867f658d3a0391e231395dff85ad5d2",
    "TsScoringPlugin/Handshake/Telemetry/Shared/JumpWire.cs": "dff2a85a25ff22f76892b3d19209b1da9c089387",
    "TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs": "bed2ed8585b502578d4d4e17f64307206d0920fc",
    "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs": "bfa15b21eb2d815e1bd158aa890ddb168475898f",
    "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs": "cde81d8f5411df680cb17b10288a3c8d9b01f561",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/AssemblyInfo.cs": "d601dec6a3a0feff0e7e6ed54c610ecb0d53bd51",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs": "12a0f84ad865443ad64c76e308907f5b7bcfdcf9",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpCommandQueue.cs": "c9517db9074f45ef447991cd52280ef512047070",
    "station_identity.py": "93ce7abce5a7050896c00ba6eddd3290e7b192d2",
    "jump_wire.py": "00579f8031221333f2f6e471d7e30ab3f8b1a365",
    "current_jump_client.py": "bfcee44c0a0f79a76a8a6e950c738084523f1cf9",
    "dataplane_contract.py": "56da8579207ae7f6d866f17ce4aafe6d0553c23f",
    "tests/jump_wire_vectors.json": "a9fc787a99853961eaecf33e22aac4eba6308029",
}


class ContractViolation(AssertionError):
    """The tree does not meet the contract; `code` names the violated clause (a RED run compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST3C-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def red(tid, code):
    def deco(fn):
        fn.st3c = {"kind": "RED", "id": tid, "code": code}
        return fn
    return deco


def guard(tid):
    def deco(fn):
        fn.st3c = {"kind": "GUARD", "id": tid, "code": ""}
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


def method_bodies(code, signature):
    """The bodies of every method whose declaration matches the regular expression `signature` (which must end where the body's '{' starts)."""
    out = []
    for m in re.finditer(signature, code):
        out.append(block_at(code, m.end() - 1 if code[m.end() - 1] == "{" else m.start()))
    return [b for b in out if b is not None]


def method_body(code, signature):
    bodies = method_bodies(code, signature)
    return bodies[0] if bodies else None


def compile_items(path):
    text = re.sub(r"<!--.*?-->", "", read_text(path), flags=re.S)
    items = []
    for m in re.finditer(r'<Compile\s+Include="([^"]+)"\s*(?:/>|>(.*?)</Compile>)', text, flags=re.S):
        link = re.search(r"<Link>([^<]*)</Link>", m.group(2) or "")
        items.append((m.group(1), link.group(1) if link else None))
    return items


EX = cs_code(EXECUTOR)
PL = cs_code(PLANE)
TL = cs_code(TIMELINE)
SE = cs_code(SESSION)
SK = cs_code(SINK)
TC = cs_code(CONTRACT)


def precondition_sources():
    """Plain assertions on the audited anchors: a moved source is RED-INVALID, never a RED."""
    assert "internal sealed class LegacyJumpClaim" in EX and "internal static byte[] BuildPayload(" in EX, "the claim / the payload builder are not where they were"
    assert "internal LegacyJumpClaim TryClaimForTick(LegacyJumpClaimFacts facts)" in PL, "the claim entry is not where it was"
    assert "private void SelectTarget(double location, bool areDoorsClosed)" in TL, "the position search is not where it was"
    assert "internal string ComposeStaList()" in TL, "ComposeStaList is not where it was"
    assert "private void TickCore(TimeSpan elapsed)" in SE, "the Tick is not where it was"
    assert "internal interface ITelemetrySink" in TC, "the sink interface is not where it was"


# ==============================================================================================================================================
class A_GateAndClaim(unittest.TestCase):
    @red("N-51", "gate-built-with-old-predicate")
    def test_N51_the_legacy_plane_builds_the_shared_grammar_gate_and_only_that(self):
        precondition_sources()
        builds = []
        for name in sorted(os.listdir(LEGACY_SRC)):
            if name.endswith(".cs"):
                builds += [(name, b) for b in re.findall(r"new JumpCommandValidator\([^;]*;", cs_code(os.path.join(LEGACY_SRC, name)))]
        contract(builds == [("LegacyJumpEndpoint.cs", "new JumpCommandValidator(env.BvePid, generation, token, recording, note, true);")], "N-51", "gate-built-with-old-predicate",
                 "the Legacy plane builds the validator in another way: %r" % (builds,))

    @red("N-52", "claim-parses-by-hand")
    def test_N52_the_claim_reads_the_command_with_the_shared_reader(self):
        precondition_sources()
        body = method_body(EX, r"internal static LegacyJumpClaim From\(LegacyJumpReceipt r\) \{")
        self.assertIsNotNone(body)
        contract("JumpWire.ParseRequest(" in body, "N-52", "claim-parses-by-hand", "LegacyJumpClaim.From does not call the shared reader")
        contract(".Split(" not in EX and "TryParse" not in EX and ".Parse(" not in EX, "N-52", "claim-parses-by-hand", "the executor file still splits or parses a command text itself")
        contract('ToString("R"' not in EX and "NumberStyles" not in EX, "N-52", "claim-parses-by-hand", "the executor file still writes or reads a number with its own format")

    @red("N-34", "selected-from-request-field")
    def test_N34_the_completion_selected_index_is_the_field_the_host_call_received(self):
        precondition_sources()
        bodies = method_bodies(EX, r"internal static byte\[\] BuildPayload\([^)]*\) \{")
        contract(len(bodies) >= 1, "N-34", "selected-from-request-field", "no BuildPayload")
        for b in bodies:
            contract("SelectedIndex" in b and "StaIndex" not in b, "N-34", "selected-from-request-field", "BuildPayload does not take the selected index from SelectedIndex (or reuses StaIndex)")
        run = method_body(EX, r"private void Run\(LegacyJumpClaim t, Func<int> lifecycle, LegacyJumpExecResult r\) \{")
        self.assertIsNotNone(run)
        contract("host.MoveToStation(t.SelectedIndex)" in run and "host.MoveToStation(t.StaIndex)" not in run, "N-34", "selected-from-request-field",
                 "the station call does not receive the field that the completion reports")
        contract("t.SelectedIndex = " in run and run.index("t.SelectedIndex = ") < run.index("host.MoveToStation(t.SelectedIndex)"), "N-34", "selected-from-request-field",
                 "the selected index is not set before the host call")
        contract("RequestedIndex" not in run and "RequestedLocation" not in run, "N-34", "selected-from-request-field", "the executor reads what the command NAMED instead of what the judgement adopted")

    @red("N-56", "completion-location-echo")
    def test_N56_the_v2_completion_reports_the_measured_location_through_the_codec(self):
        precondition_sources()
        bodies = [b for b in method_bodies(EX, r"internal static byte\[\] BuildPayload\([^)]*\) \{") if "FormatCompletionV2" in b]
        contract(len(bodies) == 1, "N-56", "completion-location-echo", "there is no v2 completion builder over JumpWire.FormatCompletionV2")
        body = bodies[0]
        contract("t.ReadBackLocation" in body and "t.ReadBackTimeMs" in body and "t.SelectedIndex" in body, "N-56", "completion-location-echo",
                 "the completion does not report the read-back location / time and the selected index")
        contract("AdoptedLocation" not in body and "RequestedLocation" not in body and "t.Location" not in body and "AdoptedIndex" not in body and "RequestedIndex" not in body, "N-56",
                 "completion-location-echo", "the completion reports a value of the request or of the judgement instead of the measured / selected one")
        contract('"R"' not in body and "ToString(" not in body, "N-56", "completion-location-echo", "the completion writes a number with its own format")

    @red("N-36", "v2-readback-not-exact")
    def test_N36_the_v2_readback_location_is_compared_exactly_and_v1_keeps_its_tolerance(self):
        precondition_sources()
        run = method_body(EX, r"private void Run\(LegacyJumpClaim t, Func<int> lifecycle, LegacyJumpExecResult r\) \{")
        self.assertIsNotNone(run)
        tolerances = re.findall(r"LocationToleranceM", run)
        contract(len(tolerances) == 1 and "after.Location != " in run, "N-36", "v2-readback-not-exact", "the read-back check has no exact comparison next to the one tolerance of v1")


class B_Claim(unittest.TestCase):
    @red("N-55", "judge-absent-before-claim")
    def test_N55_the_judgement_sits_between_the_owner_check_and_the_claim(self):
        precondition_sources()
        body = method_body(PL, r"internal LegacyJumpClaim TryClaimForTick\(LegacyJumpClaimFacts facts\) \{")
        self.assertIsNotNone(body)
        for word in ('"scenario-epoch"', '"breaker-open"', '"ttl"', '"endpoint-recreated"', "OwnerMismatch("):
            self.assertIn(word, body)
        contract("LegacyJumpJudge.Judge(" in body, "N-55", "judge-absent-before-claim", "the claim entry does not judge the command")
        contract(body.index("OwnerMismatch(") < body.index("LegacyJumpJudge.Judge(") < body.index("queue.TryClaim("), "N-55", "judge-absent-before-claim", "the judgement is not between the owner check and TryClaim")
        contract("RegisterFailure" not in body and "ReportExecution" not in body, "N-55", "judge-absent-before-claim", "the claim entry counts a failure")

    @guard("N-38")
    def test_N38_the_existing_jump_contract_is_unchanged(self):
        precondition_sources()
        self.assertIn("internal const long ExecutionTtlMs = 5000;", PL)
        self.assertIn("private const int BreakerLimit = 3;", PL)
        body = method_body(PL, r"internal LegacyJumpClaim TryClaimForTick\(LegacyJumpClaimFacts facts\) \{")
        order = [body.index(w) for w in ('"scenario-epoch"', '"breaker-open"', '"ttl"', '"endpoint-recreated"', "OwnerMismatch(")]
        self.assertEqual(order, sorted(order), "the order of the claim checks changed")
        self.assertIn("if (!facts.ScenarioCreated || !facts.SessionActive) return null;", body)
        self.assertIn("if (queue.InFlight != null) return null;", body)
        self.assertEqual(len(re.findall(r"\bRegisterFailure\(\)", PL)), 2)                                  # the definition and the one call in ReportExecution
        report = method_body(PL, r"internal int ReportExecution\(LegacyJumpClaim ticket, LegacyJumpExecResult result\) \{")
        self.assertIn("RegisterFailure();", report)
        self.assertIn("queue.Finish(r, LegacyJumpCommandState.Failed, result.Reason ?? \"failed\");", report)
        self.assertIn("Interlocked.Exchange(ref consecutiveFailures, 0);", report)                          # a success resets the count
        self.assertIn("if (n == BreakerLimit)", PL)


class C_Timeline(unittest.TestCase):
    @red("N-64", "request-target-absent")
    def test_N64_the_requested_target_is_a_one_shot_that_does_not_search(self):
        precondition_sources()
        contract(re.search(r"\bRequestTarget\b", TL) is not None, "N-64", "request-target-absent", "the timeline has no RequestTarget")
        for name in ("ExpireRequestedTarget", "TakeRequestRefusal"):
            contract(name in TL, "N-64", "request-target-absent", "the timeline has no " + name)
        select = method_body(TL, r"private void SelectTarget\(double location, bool areDoorsClosed\) \{")
        self.assertIsNotNone(select)
        contract("requestedTarget" in select or "SelectRequestedTarget(" in select, "N-64", "request-target-absent", "SelectTarget does not look at the request")
        resolver = method_body(TL, r"private void SelectRequestedTarget\([^)]*\) \{")
        contract(resolver is not None and "for (" not in resolver and "foreach" not in resolver and "while" not in resolver and "Math." not in resolver.replace("Math.Abs(list[index].Location - location) < 50.0", ""),
                 "N-64", "request-target-absent", "the requested-target resolver searches")
        reset = method_body(TL, r"internal void Reset\(\) \{")
        contract(reset is not None and "requestedTarget" in reset, "N-64", "request-target-absent", "Reset does not clear the request")

    @red("N-65", "stalist-uses-D")
    def test_N65_the_stalist_writes_the_positions_through_the_shared_codec(self):
        precondition_sources()
        body = method_body(TL, r"internal string ComposeStaList\(\) \{")
        self.assertIsNotNone(body)
        contract("LocationText(st.Location)" in body and "TelemetryContract.D(st.Location)" not in body, "N-65", "stalist-uses-D", "ComposeStaList does not write the position through LocationText")
        helper = method_body(TL, r"private static string LocationText\(double value\) \{")
        contract(helper is not None and "JumpWire.FormatLocation(" in helper, "N-65", "stalist-uses-D", "the position text does not come from the shared codec")


class D_Diagnostic(unittest.TestCase):
    @red("N-66", "diag-absent")
    def test_N66_the_refusal_numbers_are_set_after_the_verdict_and_printed_through_a_number_guard(self):
        precondition_sources()
        contract("event=legacy-jump-refused" in EX, "N-66", "diag-absent", "no refusal line")
        judge = method_body(EX, r"internal static LegacyJumpDecision Judge\(string text, uint messageType, LegacyJumpView view\) \{")
        core = method_body(EX, r"private static void JudgeCore\([^)]*\) \{")
        contract(judge is not None and core is not None, "N-66", "diag-absent", "the judgement has no Judge / JudgeCore")
        contract("Describe(" in judge and "Describe(" not in core and "Diag" not in core, "N-66", "diag-absent", "the verdict code reads the diagnostic")
        line = method_body(EX, r"internal static string RefusedLine\([^)]*\) \{")
        contract(line is not None and len(re.findall(r"DiagNumber\(", line)) == 3 and "text" not in line.replace("Text", ""), "N-66", "diag-absent",
                 "the refusal line does not print its three numbers through the number guard")
        contract("MaxLineLength = 200" in EX, "N-66", "diag-absent", "no 200 character cap")


class E_Acknowledgement(unittest.TestCase):
    @red("R1B-9", "unconditional-sent-flag")
    def test_R1B9_no_flag_is_set_right_after_a_send_that_was_not_acknowledged(self):
        precondition_sources()
        contract(re.search(r"sink\.Send\(staList\); staListSent = true;", SE) is None and re.search(r"sink\.Send\(metaPacket\); metaSent = true;", SE) is None, "R1B-9",
                 "unconditional-sent-flag", "the session still marks the STALIST / META sent right after Send")
        contract("ITelemetrySinkAck" in SE and ".TrySend(" in SE, "R1B-9", "unconditional-sent-flag", "the session does not use the acknowledgement")
        contract(re.search(r"bool (\w+) = SendAccepted\(staList\);[^}]*?if \(\1\) \{ staListSent = true;", SE) is not None, "R1B-9", "unconditional-sent-flag", "the STALIST flag is not set under the acknowledgement")
        contract(re.search(r"bool (\w+) = SendAccepted\(metaPacket\);[^}]*?if \(\1\) \{ metaSent = true;", SE) is not None, "R1B-9", "unconditional-sent-flag", "the META flag is not set under the acknowledgement")

    @red("R1B-ack", "ack-interface-absent")
    def test_R1B_the_acknowledgement_interface_is_optional_and_Legacy_only(self):
        precondition_sources()
        contract("internal interface ITelemetrySinkAck : ITelemetrySink { bool TrySend(string text); }" in TC, "R1B-ack", "ack-interface-absent", "no ITelemetrySinkAck next to ITelemetrySink")
        contract(re.search(r"class LegacyDataPlaneSink : ITelemetrySink, ITelemetrySinkAck, ILegacyJumpCompleteSender", SK) is not None, "R1B-ack", "ack-interface-absent",
                 "the Legacy data plane sink does not implement it")
        contract("public bool TrySend(string text)" in SK and "public void Send(string text) { TrySend(text); }" in SK, "R1B-ack", "ack-interface-absent", "Send is not a thin wrapper of TrySend")
        # the Current sender and the interface it already has are untouched: the contract file is not part of the Current project
        names = [i for i, _ in compile_items(CURRENT_CSPROJ)]
        self.assertFalse([n for n in names if "TelemetryContract" in n])
        self.assertIn("void Send(string text);", TC)


class F_Untouched(unittest.TestCase):
    @guard("N-69")
    def test_N69_the_Current_product_the_Python_product_and_the_shared_codec_are_byte_identical_to_ST3b(self):
        for rel, blob in sorted(UNTOUCHED.items()):
            path = os.path.join(ROOT, *rel.split("/"))
            self.assertTrue(os.path.exists(path), rel)
            try:
                out = subprocess.run(["git", "hash-object", path], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            except (OSError, subprocess.SubprocessError):
                self.skipTest("git is not available")
            if out.returncode != 0:
                self.skipTest("git hash-object failed: " + out.stderr.decode("utf-8", "replace")[:120])
            self.assertEqual(out.stdout.decode("ascii").strip(), blob, rel)

    @guard("N-69")
    def test_N69_the_Legacy_project_compiles_exactly_the_sources_it_did(self):
        names = [i for i, _ in compile_items(LEGACY_CSPROJ)]
        # Phase ST-3e0 adds exactly one compile item (..\Shared\PackageContract.cs, the package contract, constants only): the 23 sources of ST-3c are all still there
        self.assertEqual(len([n for n in names if not n.endswith("PackageContract.cs")]), 23)         # 22 AtsEx free sources + LegacyTelemetryExtension.cs
        self.assertEqual(names.count("..\\Shared\\PackageContract.cs"), 1)
        self.assertNotIn("src\\LegacyJumpJudge.cs", names)                                           # the judgement lives in LegacyJumpExecutor.cs: no new product file
        self.assertTrue(all(n in names for n in ("src\\LegacyJumpExecutor.cs", "src\\LegacyJumpControlPlane.cs", "src\\LegacyStationTimeline.cs", "..\\Shared\\JumpWire.cs")))


class G_U13(unittest.TestCase):
    @red("U13", "u13-formula-not-extended")
    def test_U13_stays_a_declared_red_when_RequestTarget_arrives(self):
        precondition_sources()
        text = read_text(RED_ST0)
        i = text.index("U13")
        window = text[i:i + 6000]
        contract("legacy_stalist_acked" in window, "U13", "u13-formula-not-extended", "the U13 formula has no Legacy R1-B term, so RequestTarget alone would turn it into an UNEXPECTED-PASS")
        contract("RequestTarget" in window, "U13", "u13-formula-not-extended", "the Legacy RequestTarget condition is gone from the formula")


if __name__ == "__main__":
    unittest.main()
