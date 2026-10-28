"""Phase PID-D4JA StationIndex U10 - the CONTRACT tests of the stop range of the CURRENT C# sender (Class1.cs, the station list builder). Python only; the file is only READ; nothing here
compiles, builds, starts a process, opens a socket or writes a file. The behaviour of the range reader is held by the compiled test Handshake/Tests/Test-CurrentStationRangeU10.ps1
(it compiles the method of Class1.cs itself); Class1.cs as a whole can not run offline (it needs the BveEX host), so what it does AROUND that reader is held here by the SHAPE of its
statements (a pin is not a run of the behaviour: the live proof is ST-3e2).

What U10 IS (recovered from the ST-0 RED, tests/red_st0_stationindex_contract.py, "CURRENT-MARGIN-FALLBACK-5.0-PRESENT")
  "a range that can not be read does not become 5.0 / 5.0 in the Current sender (fail-closed like Legacy)". Legacy's TryStations rejects the WHOLE list (and the station group is not sent)
  when an exception is thrown or the Location / MarginMin / MarginMax is not finite. The Current builder used to catch the read and use 5.0, so a station that nobody could read was
  announced as a normal +-5 m station (fail-open).

The contract (Phase U10)
  * the range of one station is read by ONE strict reader (ReadStationRange); it reports a stage (min-read / max-read / min-invalid / max-invalid) and writes no stand-in value
  * the first station that fails rejects the WHOLE list: nothing is added, nothing is removed, nothing is re-numbered (the StationIndex is the position in the host list; a list without
    a station would shift every later index), and the station part of that Tick is left
  * a rejected list is never published: no STALIST text, no list id / count, no ready flag, no STIDX, no completion; a pending jump is abandoned (list-not-ready)
  * the rejection is latched for the scenario: the inputs are the host's static map data, so the answer would be the same on every Tick; nothing is retried per Tick and no thread or
    timer is added. The latch ends where the scenario ends (the scenario is gone / the scenario changed), which is the existing way to a new list
  * ONE diagnostic line per rejection (fixed words and numbers; never an exception message, a path or a station name)

Each RED fails with ContractViolation whose .code is the declared one against the tree of b3a5fe1 (the preconditions are plain assertions that come first, so a moved source is
RED-INVALID and never a RED) and passes against the tree of this phase. A GUARD passes before and after.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CLASS1 = os.path.join(PLUGIN, "TsScoringPlugin", "Class1.cs")
LEGACY_EXT = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "src", "LegacyTelemetryExtension.cs")
THIS_FILE = "tests/test_stationindex_station_range_u10.py"


class ContractViolation(AssertionError):
    """The tree does not meet the contract; `code` names the violated clause (a RED run compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("U10-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def u10(tid, kind, code="", note=""):
    """Declare a test of U10: its id, its kind ("RED": fails against b3a5fe1 with `code`; "GUARD": green before and after) and one line."""
    assert kind in ("RED", "GUARD"), kind

    def deco(fn):
        fn.u10 = {"id": tid, "kind": kind, "code": code, "note": note}
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
    """The body of the method whose declaration matches `signature` (a regular expression ending before its '{'), or None."""
    m = re.search(signature, code)
    return None if m is None else block_at(code, m.start())


C1 = cs_code(CLASS1)
READER_SIG = r"private static string ReadStationRange\(object station, StationData sd, out string exceptionType\) "
REJECT_SIG = r"private void RejectStationList\(int stationIndex, string stage, string exceptionType\) "


def builder_loop():
    """The station enumeration of the list builder: from `for (int i = 0; i < stations.Count; i++)` to its closing brace."""
    marker = "for (int i = 0; i < stations.Count; i++) {"
    i = C1.index(marker)
    return C1[i:i + len(marker) - 1] + block_at(C1, i + len(marker) - 2)


class A_TheFallbackIsGone(unittest.TestCase):
    @u10("U10", "RED", "CURRENT-MARGIN-FALLBACK-5.0-PRESENT", "a range that can not be read does not become 5.0 / 5.0 (the original RED of ST-0, kept with its code)")
    def test_RED_U10_the_current_sender_has_no_5_0_fallback_for_an_unreadable_range(self):
        self.assertIn("sd.MarginMin = Math.Abs((double)st.MarginMin);", C1)                                         # the read is where it was (a moved source is RED-INVALID)
        self.assertIn("sd.MarginMax = (double)st.MarginMax;", C1)
        fallbacks = re.findall(r"catch \{ sd\.Margin(?:Min|Max) = 5\.0; \}", C1)
        contract(not fallbacks, "U10", "CURRENT-MARGIN-FALLBACK-5.0-PRESENT", "%d catch-and-use-5.0 fallbacks remain" % len(fallbacks))
        # any other literal written to a station range is the same defect in another shape (a different catch, a different number)
        literals = re.findall(r"\bsd\.Margin(?:Min|Max)\s*=\s*-?\d", C1)
        contract(not literals, "U10", "CURRENT-MARGIN-FALLBACK-5.0-PRESENT", "%d literal assignments to a station range remain" % len(literals))
        # the only 5.0 that is left is the initial value of the two per-Tick locals (no target station): a different requirement, not a stand-in for an unreadable range
        self.assertIn("double marginBack = 5.0; double marginFront = 5.0;", C1)
        self.assertEqual(len(re.findall(r"\b5\.0\b", C1)), 2)

    @u10("N-U10-01", "RED", "RANGE-READER-IS-NOT-ONE-STRICT-FUNCTION", "ONE strict reader: two reads, two stages of failure, two finite checks, no stand-in value")
    def test_RED_N_U10_01_one_strict_reader(self):
        body = method_body(C1, READER_SIG)
        contract(body is not None, "N-U10-01", "RANGE-READER-IS-NOT-ONE-STRICT-FUNCTION", "ReadStationRange(object station, StationData sd, out string exceptionType) is missing")
        self.assertIn("dynamic st = station;", body)
        self.assertIn("try { sd.MarginMin = Math.Abs((double)st.MarginMin); } catch (Exception minEx) { exceptionType = minEx.GetType().Name; return \"min-read\"; }", body)
        self.assertIn("try { sd.MarginMax = (double)st.MarginMax; } catch (Exception maxEx) { exceptionType = maxEx.GetType().Name; return \"max-read\"; }", body)
        self.assertIn("if (double.IsNaN(sd.MarginMin) || double.IsInfinity(sd.MarginMin)) return \"min-invalid\";", body)
        self.assertIn("if (double.IsNaN(sd.MarginMax) || double.IsInfinity(sd.MarginMax)) return \"max-invalid\";", body)
        self.assertTrue(body.rstrip("} ").endswith("return null;"), "the reader returns null only when both members were read and are finite")
        contract(not re.search(r"Margin(?:Min|Max)\s*=\s*-?\d", body), "N-U10-01", "RANGE-READER-IS-NOT-ONE-STRICT-FUNCTION", "the reader writes a literal into a range")
        contract(len(re.findall(r"\bReadStationRange\(", C1)) == 2, "N-U10-01", "RANGE-READER-IS-NOT-ONE-STRICT-FUNCTION", "the reader is the definition and ONE call (the builder)")


class B_TheWholeListIsRejected(unittest.TestCase):
    @u10("N-U10-02", "RED", "RANGE-FAILURE-DOES-NOT-REJECT-THE-LIST", "the first failing station rejects the whole list and leaves the builder before the station is added")
    def test_RED_N_U10_02_a_failing_station_rejects_the_whole_list(self):
        loop = builder_loop()
        self.assertIn("stationList.Add(sd);", loop)
        self.assertEqual(loop.count("stationList.Add(sd);"), 1)
        call = "string rangeFailType; string rangeFailStage = ReadStationRange((object)st, sd, out rangeFailType);"
        contract(call in loop, "N-U10-02", "RANGE-FAILURE-DOES-NOT-REJECT-THE-LIST", "the builder does not read the range through ReadStationRange")
        verdict = "if (rangeFailStage != null) { RejectStationList(i, rangeFailStage, rangeFailType); throw new InvalidOperationException(\"station range rejected\"); }"
        contract(verdict in loop, "N-U10-02", "RANGE-FAILURE-DOES-NOT-REJECT-THE-LIST", "a failing station does not reject the list and leave the builder")
        contract(loop.index(call) < loop.index(verdict) < loop.index("stationList.Add(sd);"), "N-U10-02", "RANGE-FAILURE-DOES-NOT-REJECT-THE-LIST", "the station is added before its range was judged")

    @u10("N-U10-03", "RED", "STATIONINDEX-SHIFT-OR-PARTIAL-LIST", "no station is skipped, removed, inserted or re-numbered; the order of the host list is the StationIndex", )
    def test_RED_N_U10_03_the_station_index_is_the_host_position_and_never_shifts(self):
        loop = builder_loop()
        self.assertIn("StationData sd = new StationData();", loop)
        contract("continue;" not in loop, "N-U10-03", "STATIONINDEX-SHIFT-OR-PARTIAL-LIST", "the builder skips a station (the later StationIndex would shift)")
        contract(not re.search(r"stationList\.(Remove|RemoveAt|RemoveAll|RemoveRange|Insert|InsertRange|Reverse|Sort)\(", C1), "N-U10-03", "STATIONINDEX-SHIFT-OR-PARTIAL-LIST", "a station is removed / inserted / re-ordered")
        contract(re.search(r"\bsd\.(Index|StationIndex)\b", C1) is None and "stationIndexOffset" not in C1, "N-U10-03", "STATIONINDEX-SHIFT-OR-PARTIAL-LIST", "a second index exists")
        # the reader is reached through the rejection only: there is no branch that keeps the station after a failed range
        self.assertNotIn("rangeFailStage == null) stationList.Add", loop)
        contract("ReadStationRange(" in loop, "N-U10-03", "STATIONINDEX-SHIFT-OR-PARTIAL-LIST", "the loop does not judge the range")


class C_TheRejectedListIsNeverPublished(unittest.TestCase):
    @u10("N-U10-04", "RED", "REJECTED-LIST-STATE-LEFT-BEHIND", "the rejection empties the list and every published value, latches the scenario and abandons a pending jump")
    def test_RED_N_U10_04_the_rejection_leaves_nothing_published(self):
        body = method_body(C1, REJECT_SIG)
        contract(body is not None, "N-U10-04", "REJECTED-LIST-STATE-LEFT-BEHIND", "RejectStationList(int stationIndex, string stage, string exceptionType) is missing")
        for stmt in ("int built = stationList.Count;", "stationRangeRejected = true;", "stationList.Clear();", "lastStaListPacket = \"\";",
                     "stidxListId = TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;", "stidxListCount = 0;", "stidxListReady = false;", "isInitialized = false;",
                     "AbandonPendingJump(TSScoringPlugin.DataPlane.CurrentJumpExecution.RListNotReady, \"-\");"):
            contract(stmt in body, "N-U10-04", "REJECTED-LIST-STATE-LEFT-BEHIND", "missing in the rejection: " + stmt)
        contract(not re.search(r"(stidxListReady|isInitialized|initialStaListSent)\s*=\s*true", body), "N-U10-04", "REJECTED-LIST-STATE-LEFT-BEHIND", "the rejection publishes something")
        contract("lastStaListPacket = \"STALIST:\"" not in body and "staInfoList" not in body, "N-U10-04", "REJECTED-LIST-STATE-LEFT-BEHIND", "the rejection composes a STALIST")
        # a rejection never chooses a station: no target is set or searched (no index 0, no nearest station, no position search) and nothing is added to the list
        contract(not re.search(r"targetStationIndex|SelectTarget|hasDoorOpenedAtTarget|stationList\.Add|nearest|Math\.Abs\(", body), "N-U10-04", "REJECTED-LIST-STATE-LEFT-BEHIND", "the rejection picks, adds or searches a station")
        # the three places that publish a list are all inside the gated station part (see N-U10-05) and none of them is reachable from the rejection
        contract(body.index("stationRangeRejected = true;") < body.index("stationList.Clear();"), "N-U10-04", "REJECTED-LIST-STATE-LEFT-BEHIND", "the list is emptied before the scenario is latched")

    @u10("N-U10-05", "RED", "LATCH-DOES-NOT-GATE-THE-STATION-PART", "while the scenario is latched nothing of the station part runs: no build, no STALIST, no ready flag, no target")
    def test_RED_N_U10_05_the_latch_gates_the_whole_station_part(self):
        gate = "if (!stationRangeRejected) try { var stations = map.Stations;"
        contract(gate in C1, "N-U10-05", "LATCH-DOES-NOT-GATE-THE-STATION-PART", "the station part is not behind the latch")
        start = C1.index(gate)
        end = C1.index("double signalLimit = 1000.0;", start)
        part = C1[start:end]
        # SI-R2.4 C5b: "SelectUnsetTarget();" replaces SelectTargetByPosition(location, areDoorsClosed); (the index-less re-initialisation is UNSET now)
        for inside in ("stationList.Clear();", "lastStaListPacket = \"STALIST:\"", "stidxListReady = true;", "isInitialized = true;", "SelectUnsetTarget();",
                       "if (!initialStaListSent ||", "var targetSt = stationList[targetStationIndex];"):
            contract(inside in part, "N-U10-05", "LATCH-DOES-NOT-GATE-THE-STATION-PART", "outside the gated part or missing: " + inside)
        # the gate is a statement of its own: the try and its catch are the ones of before (a rejection that throws out of the builder is swallowed there, after it was diagnosed)
        contract(part.rstrip().endswith("catch { }"), "N-U10-05", "LATCH-DOES-NOT-GATE-THE-STATION-PART", "the gated statement is not the old try / catch")

    @u10("N-U10-06", "RED", "LATCH-LIFECYCLE-WRONG", "the latch is declared, set in one place only and cleared exactly where a scenario ends or changes (the existing way to a new list)")
    def test_RED_N_U10_06_the_latch_lifecycle(self):
        contract("private bool stationRangeRejected = false;" in C1, "N-U10-06", "LATCH-LIFECYCLE-WRONG", "the latch is not declared")
        contract(C1.count("stationRangeRejected = true;") == 1, "N-U10-06", "LATCH-LIFECYCLE-WRONG", "the latch is set in %d places" % C1.count("stationRangeRejected = true;"))
        gone = re.search(r"if \(!BveHacker\.IsScenarioCreated\) \{([^}]*)\}", C1)
        change = re.search(r"if \(!object\.Equals\(currentScenario, BveHacker\.Scenario\)\) \{(.*?)initialStaListSent = false; lastStaListSendTime = DateTime\.MinValue; AbandonPendingJump\(", C1)
        self.assertIsNotNone(gone)
        self.assertIsNotNone(change)
        contract("stationRangeRejected = false;" in gone.group(1), "N-U10-06", "LATCH-LIFECYCLE-WRONG", "the latch survives a scenario that is gone")
        contract("stationRangeRejected = false;" in change.group(1), "N-U10-06", "LATCH-LIFECYCLE-WRONG", "the latch survives a scenario change")
        contract(C1.count("stationRangeRejected = false;") == 3, "N-U10-06", "LATCH-LIFECYCLE-WRONG", "the latch is cleared in %d places (declaration + 2)" % C1.count("stationRangeRejected = false;"))

    @u10("N-U10-07", "RED", "REJECTION-DIAGNOSTIC-WRONG", "one structured line per rejection: fixed words and numbers; no exception message, path, stack trace or station name")
    def test_RED_N_U10_07_the_diagnostic(self):
        body = method_body(C1, REJECT_SIG)
        contract(body is not None, "N-U10-07", "REJECTION-DIAGNOSTIC-WRONG", "RejectStationList is missing")
        line = re.search(r'"event=current-station-list-rejected scn=" \+ scenarioId \+ " idx=" \+ stationIndex \+ " stage=" \+ stage \+ " ex=" \+ exceptionType \+ " built=" \+ built '
                         r'\+ " verdict=rejected retry=scenario-change action=hold"', body)
        contract(line is not None, "N-U10-07", "REJECTION-DIAGNOSTIC-WRONG", "the diagnostic line does not carry event / scn / idx / stage / ex / built / verdict / retry / action")
        contract("try { if (diagnostics != null) diagnostics.Write(" in body, "N-U10-07", "REJECTION-DIAGNOSTIC-WRONG", "the line is not written through the per-process diagnostics (400 lines at most)")
        contract(not re.search(r"\.(Message|StackTrace|Source|ToString)\b|\.Name\b|Path\b", body), "N-U10-07", "REJECTION-DIAGNOSTIC-WRONG", "the diagnostic names a message, a path or a name")
        contract(C1.count("event=current-station-list-rejected") == 1 and len(re.findall(r"\bRejectStationList\(", C1)) == 2, "N-U10-07", "REJECTION-DIAGNOSTIC-WRONG",
                 "the diagnostic is written in one place and the rejection is called from the builder only")


class D_Guards(unittest.TestCase):
    @u10("G-U10-01", "GUARD", note="the reads of a normal station are what they were: |MarginMin| and MarginMax, in this order, Min first")
    def test_GUARD_the_normal_reads_are_unchanged(self):
        self.assertIn("sd.MarginMin = Math.Abs((double)st.MarginMin);", C1)
        self.assertIn("sd.MarginMax = (double)st.MarginMax;", C1)
        self.assertLess(C1.index("sd.MarginMin = Math.Abs((double)st.MarginMin);"), C1.index("sd.MarginMax = (double)st.MarginMax;"))
        self.assertEqual(C1.count("Math.Abs((double)st.MarginMin)"), 1)
        self.assertEqual(C1.count("marginBack = targetSt.MarginMin;"), 2)
        self.assertEqual(C1.count("marginFront = targetSt.MarginMax;"), 2)

    @u10("G-U10-02", "GUARD", note="the station list is still built in the host order, one StationData per host station, by the same enumeration")
    def test_GUARD_the_list_is_still_built_in_host_order(self):
        self.assertIn("for (int i = 0; i < stations.Count; i++) { dynamic st = stations[i]; StationData sd = new StationData(); sd.Location = st.Location;", C1)
        self.assertEqual(C1.count("stationList.Add(sd);"), 1)
        self.assertIn("if (!isInitialized || stations.Count != stationList.Count) { stationList.Clear();", C1)

    @u10("G-U10-03", "GUARD", note="Legacy stays fail-closed as it is: the whole list is refused on an exception or a range that is not finite (no Legacy change)")
    def test_GUARD_legacy_refuses_the_whole_list(self):
        ext = cs_code(LEGACY_EXT)
        self.assertIn("if (!TelemetryContract.Finite(r.Location) || !TelemetryContract.Finite(r.MarginMin) || !TelemetryContract.Finite(r.MarginMax)) { return false; }", ext)
        self.assertIn("catch { stations = null; return false; }", ext)

    @u10("G-U10-04", "GUARD", note="no thread, timer or task is added for the rejection: the Current sender has exactly the one heartbeat timer it had")
    def test_GUARD_no_new_thread_or_timer(self):
        self.assertEqual(len(re.findall(r"\bnew (?:System\.Threading\.)?Thread\(", C1)), 0)
        self.assertEqual(len(re.findall(r"\bTask\.(?:Run|Factory)", C1)), 0)
        self.assertEqual(len(re.findall(r"\bnew (?:System\.Timers\.)?Timer\(", C1)), 1)
        self.assertEqual(len(re.findall(r"ThreadPool|BackgroundWorker|Parallel\.", C1)), 0)

    @u10("G-U10-05", "GUARD", note="the index-less selection, the 100 m door test and the requested selection stay where ST-3b / SI-R2.4 left them (U10 does not touch the target); SI-R2.4 C5b: the 50 m position search is gone (count 0), the index-less selection is UNSET")
    def test_GUARD_the_target_state_machine_is_untouched(self):
        self.assertEqual(C1.count("location - 50.0"), 0)
        self.assertIn("if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true;", C1)
        self.assertIn("if (requestedStationIndex >= 0) SelectTargetByRequestedIndex(requestedStationIndex, location, areDoorsClosed); else if (!requestedTargetRefused) SelectUnsetTarget();", C1)


if __name__ == "__main__":
    unittest.main()
