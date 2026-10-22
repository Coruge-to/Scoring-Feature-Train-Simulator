using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;

// PHASE PID-D4JA StationIndex ST-3b - offline tests of the CURRENT jump decision (CurrentJumpExecution.cs), of the grammar gate of the Current jump endpoint
// (CurrentJumpEndpoint.cs, ValidGrammar over the shared JumpWire.cs) and of the numbers the Current plugin writes. No BVE, no BveEX, no socket, no file. Compiled by
// Test-CurrentJumpST3B.ps1 together with the product sources (C# 5 syntax). Class1.cs can not run offline: what it does around these functions is held by the source pins of
// tests\test_stationindex_current_st3b.py and judged live in ST-3e2.
public static class CurrentJumpST3BTestFixture
{
    const string Inst = "0123456789abcdef0123456789abcdef";
    const int Pid = 4242;
    const uint AppPid = 777U;
    const uint JumpGen = 91U;
    const string ListId = "A1B2C3D4";
    const int Scenario = 7;
    const int TimeMs = 36000000;

    // the station list of the tests: index 0 at 500, a pair at the SAME position (1, 2), a neighbour 40.5 m after them (3), one exactly 50 m after that (4), one far away with a fraction (5)
    static readonly double[] Locations = new double[] { 500.0, 1000.0, 1000.0, 1040.5, 1090.5, 20500.25 };

    static List<string> failures;
    static int checks;
    static void Check(string id, bool ok) { checks++; if (!ok) failures.Add(id); }

    sealed class FakeSource : IEndpointSource
    {
        public TelemetryEndpoint Endpoint;
        public bool TryResolve(int bveProcessId, out TelemetryEndpoint endpoint, out string reason)
        {
            endpoint = Endpoint;
            reason = Endpoint != null ? "ok" : "app-directory-missing";
            return Endpoint != null;
        }
    }

    static byte[] Token(byte seed) { byte[] t = new byte[16]; for (int i = 0; i < 16; i++) t[i] = (byte)(seed + i); return t; }
    static byte[] Req(byte seed) { byte[] t = new byte[16]; for (int i = 0; i < 16; i++) t[i] = (byte)(seed ^ (i * 7 + 1)); return t; }

    static CurrentJumpView View()
    {
        CurrentJumpView v = new CurrentJumpView();
        v.ScenarioId = Scenario;
        v.ListReady = true;
        v.ListId = ListId;
        v.ListCount = Locations.Length;
        v.Locations = (double[])Locations.Clone();
        return v;
    }

    static string Request(string kind, int idx, double location, int scenario, string listId, int count)
    {
        string reason;
        string text = JumpWire.FormatRequestV2(kind, idx, TimeMs, new JumpWireScope(scenario, listId, count), location, out reason);
        if (text == null) throw new InvalidOperationException("the fixture request is outside the contract: " + reason);
        return text;
    }

    static string Request(string kind, int idx) { return Request(kind, idx, Locations[idx], Scenario, ListId, Locations.Length); }

    static long Bits(double d) { return BitConverter.DoubleToInt64Bits(d); }

    public static string[] Run()
    {
        failures = new List<string>();
        checks = 0;
        Accepts();
        Refuses();
        Targets();
        Completions();
        StationText();
        Lines();
        Diagnostics();
        Grammar();
        LegacyCompatibleGate();
        failures.Insert(0, "CHECKS=" + checks);
        return failures.ToArray();
    }

    // ---- J: a v2 command that passes is adopted AS NAMED (N-22 same position, N-23 nearby, index 0, N-26 the adopted values) ---------------------------------
    static void Accepts()
    {
        CurrentJumpDecision d = CurrentJumpExecution.Judge(Request("STA", 0), View());
        Check("J01 station index 0 is a valid index: accepted, adopted 0, its own location (no fallback is needed, none is used)", d.Accepted && d.Reason == null && d.StationIndex == 0 && Bits(d.Location) == Bits(500.0) && d.Version == 2 && d.Kind == "STA");
        d = CurrentJumpExecution.Judge(Request("STA", 1), View());
        Check("J02 the first of the two stations at the same position is adopted as index 1", d.Accepted && d.StationIndex == 1 && d.Location == 1000.0);
        d = CurrentJumpExecution.Judge(Request("STA", 2), View());
        Check("J03 the SECOND of the two stations at the same position is adopted as index 2 (not 1, not 0)", d.Accepted && d.StationIndex == 2 && d.Location == 1000.0 && d.RequestedIndex == 2);
        d = CurrentJumpExecution.Judge(Request("LOC", 2), View());
        Check("J04 a location command to the second same-position station carries the adopted index 2 (LOC no longer has -1)", d.Accepted && d.Kind == "LOC" && d.StationIndex == 2 && d.Location == 1000.0);
        d = CurrentJumpExecution.Judge(Request("STA", 3), View());
        Check("J05 the station 40.5 m after the pair is adopted as 3 (the pair is within 50 m behind it)", d.Accepted && d.StationIndex == 3 && d.Location == 1040.5);
        d = CurrentJumpExecution.Judge(Request("STA", 1), View());
        Check("J06 and the station BEHIND is adopted as 1 when it is the one named (the nearby station 3 does not replace it)", d.Accepted && d.StationIndex == 1);
        d = CurrentJumpExecution.Judge(Request("STA", 4), View());
        Check("J07 a station exactly 50 m after the previous one is adopted as 4", d.Accepted && d.StationIndex == 4 && d.Location == 1090.5);
        d = CurrentJumpExecution.Judge(Request("STA", Locations.Length - 1), View());
        Check("J08 the last index is adopted", d.Accepted && d.StationIndex == Locations.Length - 1 && d.Location == 20500.25);
        bool every = true;
        for (int i = 0; i < Locations.Length; i++)
        {
            CurrentJumpDecision s = CurrentJumpExecution.Judge(Request("STA", i), View());
            CurrentJumpDecision l = CurrentJumpExecution.Judge(Request("LOC", i), View());
            every &= s.Accepted && s.StationIndex == i && s.RequestedIndex == i && Bits(s.Location) == Bits(Locations[i]) && l.Accepted && l.StationIndex == i && Bits(l.Location) == Bits(Locations[i]);
        }
        Check("J09 every index of the list, STA and LOC alike, is adopted exactly as named with the plugin's own location bits", every);
        d = CurrentJumpExecution.Judge(Request("STA", 3), View());
        Check("J10 the time and the scope are carried (time 36000000, scenario 7, list A1B2C3D4, count 6)", d.TimeMs == TimeMs && d.Scope != null && d.Scope.ScenarioId == Scenario && d.Scope.ListId == ListId && d.Scope.Count == Locations.Length);
    }

    // ---- R: everything else is refused with no adopted value (N-24 contradiction, N-25 scope, v1, malformed) -----------------------------------------------
    static void Refuses()
    {
        CurrentJumpDecision d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length), View());
        Check("R01 index and location that contradict the list are refused (location-mismatch), and no other station is chosen", !d.Accepted && d.Reason == "location-mismatch" && d.StationIndex == -1 && d.RequestedIndex == 1);
        d = CurrentJumpExecution.Judge(Request("LOC", 3, Locations[1], Scenario, ListId, Locations.Length), View());
        Check("R02 the same contradiction in a location command is refused; the nearest station to the location (index 1) is not adopted", !d.Accepted && d.Reason == "location-mismatch" && d.StationIndex == -1);
        double ulp = BitConverter.Int64BitsToDouble(Bits(Locations[1]) + 1L);
        d = CurrentJumpExecution.Judge(Request("STA", 1, ulp, Scenario, ListId, Locations.Length), View());
        Check("R03 a location one unit in the last place away is refused: the comparison is exact, there is no tolerance", !d.Accepted && d.Reason == "location-mismatch");
        d = CurrentJumpExecution.Judge(Request("STA", 2, 1000.5, Scenario, ListId, Locations.Length), View());
        Check("R04 a location half a metre away is refused", !d.Accepted && d.Reason == "location-mismatch");
        d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[1], Scenario + 1, ListId, Locations.Length), View());
        Check("R05 another scenario is refused (scenario-mismatch)", !d.Accepted && d.Reason == "scenario-mismatch" && d.StationIndex == -1);
        d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[1], Scenario, "A1B2C3D5", Locations.Length), View());
        Check("R06 another list id is refused (list-mismatch)", !d.Accepted && d.Reason == "list-mismatch" && d.StationIndex == -1);
        d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[1], Scenario, ListId, Locations.Length + 1), View());
        Check("R07 another count is refused (count-mismatch)", !d.Accepted && d.Reason == "count-mismatch" && d.StationIndex == -1);
        CurrentJumpView notReady = View();
        notReady.ListReady = false;
        d = CurrentJumpExecution.Judge(Request("STA", 1), notReady);
        Check("R08 a list whose identity is not ready is refused (list-not-ready)", !d.Accepted && d.Reason == "list-not-ready");
        d = CurrentJumpExecution.Judge(Request("STA", 1), null);
        Check("R09 no view at all is a refusal, not an exception", !d.Accepted && d.Reason == "scenario-mismatch");
        CurrentJumpView inconsistent = View();
        inconsistent.Locations = new double[] { 1.0, 2.0 };
        d = CurrentJumpExecution.Judge(Request("STA", 1), inconsistent);
        Check("R10 a plugin list that does not have the count of its own identity is refused (list-inconsistent)", !d.Accepted && d.Reason == "list-inconsistent");
        inconsistent.Locations = null;
        d = CurrentJumpExecution.Judge(Request("STA", 1), inconsistent);
        Check("R11 no list at all is refused (list-inconsistent)", !d.Accepted && d.Reason == "list-inconsistent");
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:6:500", View());
        Check("R12 a negative index is refused by the shared reader (malformed, station-index-range) and nothing is adopted", !d.Accepted && d.Reason == "malformed" && d.Detail == "station-index-range" && d.StationIndex == -1);
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:6:36000000:7:A1B2C3D4:6:500", View());
        Check("R13 an index equal to the count is refused by the shared reader (malformed, station-index-range)", !d.Accepted && d.Reason == "malformed" && d.Detail == "station-index-range" && d.StationIndex == -1);
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:2147483647:36000000:7:A1B2C3D4:6:500", View());
        Check("R14 Int32 maximum as the index is refused", !d.Accepted && d.Reason == "malformed" && d.StationIndex == -1);
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:1:36000000", View());
        Check("R15 a v1 station command is read but not executed (unsupported-version)", !d.Accepted && d.Reason == "unsupported-version" && d.Version == 1 && d.Kind == "STA" && d.StationIndex == -1 && !d.HasRequest);
        d = CurrentJumpExecution.Judge("JUMP_LOC_TIME:1000:36000000", View());
        Check("R16 a v1 location command is read but not executed (unsupported-version)", !d.Accepted && d.Reason == "unsupported-version" && d.Version == 1 && d.Kind == "LOC");
        d = CurrentJumpExecution.Judge("hello", View());
        Check("R17 a text that is no command is malformed (prefix)", !d.Accepted && d.Reason == "malformed" && d.Detail == "prefix" && d.Version == 0);
        d = CurrentJumpExecution.Judge("", View());
        Check("R18 an empty text is malformed (empty)", !d.Accepted && d.Reason == "malformed" && d.Detail == "empty");
        d = CurrentJumpExecution.Judge(null, View());
        Check("R19 a null text is malformed, never an exception", !d.Accepted && d.Reason == "malformed" && d.Detail == "empty");
        d = CurrentJumpExecution.Judge("JUMP_LOC_TIME:NaN:36000000:7:A1B2C3D4:6:1", View());
        Check("R20 a NaN location is malformed (location-syntax)", !d.Accepted && d.Reason == "malformed" && d.Detail == "location-syntax");
        d = CurrentJumpExecution.Judge("JUMP_LOC_TIME:Infinity:36000000:7:A1B2C3D4:6:1", View());
        Check("R21 an Infinity location is malformed (location-syntax)", !d.Accepted && d.Reason == "malformed" && d.Detail == "location-syntax");
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:1:36000000:7:A1B2C3D4:6:1000:9", View());
        Check("R22 eight fields are malformed (field-count)", !d.Accepted && d.Reason == "malformed" && d.Detail == "field-count");
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME: 1:36000000:7:A1B2C3D4:6:1000", View());
        Check("R23 a blank inside a number is malformed (station-index-syntax)", !d.Accepted && d.Reason == "malformed" && d.Detail == "station-index-syntax");
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:1:36000000:7:a1b2c3d4:6:1000", View());
        Check("R24 a lower-case list id is malformed (list-id-syntax)", !d.Accepted && d.Reason == "malformed" && d.Detail == "list-id-syntax");
        d = CurrentJumpExecution.Judge(new string('x', 100000), View());
        Check("R25 a huge text is refused without an exception", !d.Accepted && d.Reason == "malformed");
        d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[3], Scenario + 1, "A1B2C3D5", Locations.Length + 1), View());
        Check("R26 the first failing step gives the reason: scenario before list, count and location", !d.Accepted && d.Reason == "scenario-mismatch");
        d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[3], Scenario, "A1B2C3D5", Locations.Length + 1), View());
        Check("R27 list id before count and location", !d.Accepted && d.Reason == "list-mismatch");
        d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length + 1), View());
        Check("R28 count before location", !d.Accepted && d.Reason == "count-mismatch");
        bool known = true;
        string[] texts = new string[] { Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length), "JUMP_STA_TIME:1:2", "x", "", Request("STA", 1, Locations[1], 99, ListId, 6), Request("LOC", 2, Locations[2], Scenario, "FFFFFFFF", 6) };
        for (int i = 0; i < texts.Length; i++)
        {
            CurrentJumpDecision x = CurrentJumpExecution.Judge(texts[i], View());
            known &= !x.Accepted && Array.IndexOf(CurrentJumpExecution.Reasons, x.Reason) >= 0 && x.StationIndex == -1;
        }
        Check("R29 every reason the judgement gives is one of the fixed words, and a refusal never carries an adopted index", known);
        bool distinct = true;
        for (int i = 0; i < CurrentJumpExecution.Reasons.Length; i++)
            for (int j = i + 1; j < CurrentJumpExecution.Reasons.Length; j++) distinct &= CurrentJumpExecution.Reasons[i] != CurrentJumpExecution.Reasons[j];
        Check("R30 the reason words are distinct (19)", distinct && CurrentJumpExecution.Reasons.Length == 19);
        // G-RC-1: the VERDICT of the texts whose refusal lines the D checks read is the reader's and the plugin's own, word for word (the diagnostic never changes it; a count of 5 against a list of 6 is not a count mismatch of the reader)
        string[][] verdicts = new string[][]
        {
            new string[] { "JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:5:500", "malformed", "station-index-range" }, new string[] { "JUMP_STA_TIME:5:36000000:7:A1B2C3D4:5:500", "malformed", "station-index-range" },
            new string[] { "JUMP_STA_TIME:999:36000000:7:A1B2C3D4:5:500", "malformed", "station-index-range" }, new string[] { "JUMP_STA_TIME:abc:36000000:7:A1B2C3D4:5:500", "malformed", "station-index-syntax" },
            new string[] { "JUMP_STA_TIME:3:36000000:7:A1B2C3D4:xyz:500", "malformed", "count-syntax" }, new string[] { "JUMP_STA_TIME:3:36000000:7:A1B2C3D4:5", "malformed", "field-count" },
            new string[] { "JUMP_STA_TIME:3:36000000:7:A1B2C3D4:5:500:9", "malformed", "field-count" }, new string[] { "JUMP_STA_TIME:1:36000000", "unsupported-version", null },
            new string[] { "JUMP_STA_TIME:3:36000000:7", "malformed", "field-count" }, new string[] { "JUMP_STA_TIME;3;36000000;7;A1B2C3D4;5;500", "malformed", "prefix" },
            new string[] { "JUMP_STA_TIME:1:36000000:7:A1B2C3D4:7:1000", "count-mismatch", null }, new string[] { "JUMP_LOC_TIME:500:36000000:7:A1B2C3D4:5:-1", "malformed", "station-index-range" }
        };
        bool verdictsHold = true;
        for (int i = 0; i < verdicts.Length; i++)
        {
            CurrentJumpDecision v = CurrentJumpExecution.Judge(verdicts[i][0], View());
            verdictsHold &= !v.Accepted && v.StationIndex == -1 && v.Reason == verdicts[i][1] && (verdicts[i][2] == null ? v.Detail == null : v.Detail == verdicts[i][2]);
        }
        Check("R31 the refusal words of the diagnostic texts are the reader's and the plugin's own (" + verdicts.Length + " texts: station-index-range, the syntax words, field-count, prefix, unsupported-version, count-mismatch)", verdictsHold);
    }

    // ---- T: the target after the jump (N-22 / N-23 / N-28): the requested index, never a position ---------------------------------------------------------------
    static void Targets()
    {
        string reason;
        Check("T01 same position: index 2 stays 2", CurrentJumpExecution.ResolveRequestedTarget(2, 1000.0, Locations, out reason) == 2 && reason == null);
        Check("T02 same position: index 1 stays 1", CurrentJumpExecution.ResolveRequestedTarget(1, 1000.0, Locations, out reason) == 1);
        Check("T03 nearby: index 3 (40.5 m after the pair) stays 3", CurrentJumpExecution.ResolveRequestedTarget(3, 1040.5, Locations, out reason) == 3);
        Check("T04 nearby: index 1 stays 1 although station 3 is within 50 m in front", CurrentJumpExecution.ResolveRequestedTarget(1, 1000.0, Locations, out reason) == 1);
        Check("T05 exactly 50 m apart: index 4 stays 4", CurrentJumpExecution.ResolveRequestedTarget(4, 1090.5, Locations, out reason) == 4);
        Check("T06 index 0 is resolved to 0", CurrentJumpExecution.ResolveRequestedTarget(0, 500.0, Locations, out reason) == 0 && reason == null);
        bool all = true;
        for (int i = 0; i < Locations.Length; i++) all &= CurrentJumpExecution.ResolveRequestedTarget(i, Locations[i], Locations, out reason) == i;
        Check("T07 every index resolves to itself", all);
        Check("T08 a negative index is refused (reinit-index-range), no station is chosen", CurrentJumpExecution.ResolveRequestedTarget(-1, 500.0, Locations, out reason) == -1 && reason == "reinit-index-range");
        Check("T09 an index at the count is refused (reinit-index-range)", CurrentJumpExecution.ResolveRequestedTarget(Locations.Length, 500.0, Locations, out reason) == -1 && reason == "reinit-index-range");
        Check("T10 Int32 maximum is refused", CurrentJumpExecution.ResolveRequestedTarget(int.MaxValue, 500.0, Locations, out reason) == -1 && reason == "reinit-index-range");
        Check("T11 a list that no longer has the location is refused (reinit-location-mismatch), no other index is chosen", CurrentJumpExecution.ResolveRequestedTarget(1, 1001.0, Locations, out reason) == -1 && reason == "reinit-location-mismatch");
        Check("T12 a list that shrank is refused", CurrentJumpExecution.ResolveRequestedTarget(5, 20500.25, new double[] { 500.0, 1000.0 }, out reason) == -1 && reason == "reinit-index-range");
        Check("T13 no list is refused", CurrentJumpExecution.ResolveRequestedTarget(0, 500.0, null, out reason) == -1 && reason == "reinit-index-range");
        double ulp = BitConverter.Int64BitsToDouble(Bits(1000.0) + 1L);
        Check("T14 the comparison is exact (one unit in the last place is a refusal)", CurrentJumpExecution.ResolveRequestedTarget(1, ulp, Locations, out reason) == -1 && reason == "reinit-location-mismatch");
    }

    // ---- C: the completion (N-26, N-29): the adopted index, the real position, the canonical numbers, any culture ---------------------------------------------------
    static void Completions()
    {
        string reason;
        string text = CurrentJumpExecution.FormatCompletion("STA", 2, 999.75, TimeMs, 3, Scenario, ListId, Locations.Length, out reason);
        JumpWireCompletion c = text == null ? null : JumpWire.ParseCompletion(text, out reason);
        Check("C01 a v2 completion of nine fields is written and read back by the shared reader", text != null && c != null && c.Version == 2 && text.Split(':').Length == 9 && text.StartsWith("JUMP_COMPLETE:STA:2:"));
        Check("C02 it carries the adopted index, the position the host REPORTS (999.75, not the requested 1000), the time, the jump count and the scope", c != null && c.SelectedIndex == 2 && Bits(c.Location) == Bits(999.75)
            && c.TimeMs == TimeMs && c.JumpCount == 3 && c.Scope != null && c.Scope.ScenarioId == Scenario && c.Scope.ListId == ListId && c.Scope.Count == Locations.Length);
        text = CurrentJumpExecution.FormatCompletion("LOC", 4, 1090.5, TimeMs, 1, Scenario, ListId, Locations.Length, out reason);
        c = text == null ? null : JumpWire.ParseCompletion(text, out reason);
        Check("C03 a LOC completion carries the adopted index 4, never -1", c != null && c.Kind == "LOC" && c.SelectedIndex == 4);
        double precise = 1000.1234567890123;
        text = CurrentJumpExecution.FormatCompletion("STA", 1, precise, TimeMs, 0, Scenario, ListId, Locations.Length, out reason);
        c = text == null ? null : JumpWire.ParseCompletion(text, out reason);
        Check("C04 a position of 17 significant digits is written so that it reads back to the same bits", c != null && Bits(c.Location) == Bits(precise));
        text = CurrentJumpExecution.FormatCompletion("STA", 1, -0.0, TimeMs, 0, Scenario, ListId, Locations.Length, out reason);
        Check("C05 -0.0 is written as 0", text != null && text.Split(':')[3] == "0");
        Check("C06 NaN is not written (location-range)", CurrentJumpExecution.FormatCompletion("STA", 1, double.NaN, TimeMs, 0, Scenario, ListId, 6, out reason) == null && reason == "location-range");
        Check("C07 Infinity is not written (location-range)", CurrentJumpExecution.FormatCompletion("STA", 1, double.PositiveInfinity, TimeMs, 0, Scenario, ListId, 6, out reason) == null && reason == "location-range");
        Check("C08 -1.0 is an ordinary position for the formatter (the plugin abandons an unreadable position instead of writing a stand-in)", CurrentJumpExecution.FormatCompletion("STA", 1, -1.0, TimeMs, 0, Scenario, ListId, 6, out reason) != null);
        Check("C09 a negative selected index is not written (selected-idx-range)", CurrentJumpExecution.FormatCompletion("STA", -1, 1.0, TimeMs, 0, Scenario, ListId, 6, out reason) == null && reason == "selected-idx-range");
        Check("C10 a selected index at the count is not written (selected-idx-range)", CurrentJumpExecution.FormatCompletion("STA", 6, 1.0, TimeMs, 0, Scenario, ListId, 6, out reason) == null && reason == "selected-idx-range");
        Check("C11 a negative time is not written (time-range)", CurrentJumpExecution.FormatCompletion("STA", 1, 1.0, -1, 0, Scenario, ListId, 6, out reason) == null && reason == "time-range");
        Check("C12 a negative jump count is not written (jump-count-range)", CurrentJumpExecution.FormatCompletion("STA", 1, 1.0, TimeMs, -1, Scenario, ListId, 6, out reason) == null && reason == "jump-count-range");
        Check("C13 a list id that is not eight upper-case hex digits is not written (list-id-syntax)", CurrentJumpExecution.FormatCompletion("STA", 1, 1.0, TimeMs, 0, Scenario, "a1b2c3d4", 6, out reason) == null && reason == "list-id-syntax");
        Check("C14 scenario -1 is not written (scenario-id-range)", CurrentJumpExecution.FormatCompletion("STA", 1, 1.0, TimeMs, 0, -1, ListId, 6, out reason) == null && reason == "scenario-id-range");
        Check("C15 count 0 is not written (count-range)", CurrentJumpExecution.FormatCompletion("STA", 1, 1.0, TimeMs, 0, Scenario, ListId, 0, out reason) == null && reason == "count-range");
        Check("C16 a kind that is neither STA nor LOC is not written (kind)", CurrentJumpExecution.FormatCompletion("XXX", 1, 1.0, TimeMs, 0, Scenario, ListId, 6, out reason) == null && reason == "kind");
        string reference = CurrentJumpExecution.FormatCompletion("STA", 3, 12345.678901234567, TimeMs, 2, Scenario, ListId, 6, out reason);
        string[] cultures = new string[] { "en-US", "de-DE", "fr-FR", "ja-JP", "tr-TR", "ru-RU" };
        int tried = 0;
        bool same = true;
        CultureInfo savedCulture = Thread.CurrentThread.CurrentCulture;
        CultureInfo savedUi = Thread.CurrentThread.CurrentUICulture;
        try
        {
            for (int i = 0; i < cultures.Length; i++)
            {
                CultureInfo ci;
                try { ci = new CultureInfo(cultures[i]); } catch { continue; }
                tried++;
                Thread.CurrentThread.CurrentCulture = ci;
                Thread.CurrentThread.CurrentUICulture = ci;
                string t = CurrentJumpExecution.FormatCompletion("STA", 3, 12345.678901234567, TimeMs, 2, Scenario, ListId, 6, out reason);
                same &= t == reference && t != null && t.IndexOf(',') < 0;
            }
        }
        finally
        {
            Thread.CurrentThread.CurrentCulture = savedCulture;
            Thread.CurrentThread.CurrentUICulture = savedUi;
        }
        Check("C17 the completion text is identical under every culture of the machine that exists (" + tried + " tried) and has no comma", tried >= 3 && same);
    }

    // ---- S: the station position in the STALIST text (N-29) -------------------------------------------------------------------------------------------------------
    static void StationText()
    {
        Check("S01 an ordinary position keeps its short text (1000.5)", CurrentJumpExecution.StationLocationText(1000.5) == "1000.5" && CurrentJumpExecution.StationLocationText(20500.25) == "20500.25" && CurrentJumpExecution.StationLocationText(1000.0) == "1000");
        double v = 1000.1234567890123;
        string t = CurrentJumpExecution.StationLocationText(v);
        double back;
        Check("S02 a position of 17 significant digits reads back to the same bits through the shared reader", JumpWire.ParseLocation(t, out back) == null && Bits(back) == Bits(v));
        double[] samples = new double[] { 0.0, -0.0, 12.5, 0.1, 1.0 / 3.0, 99999.99999999999, 123456.78901234567, 20500.25, 1e-5, 4096.000000000001 };
        bool round = true;
        for (int i = 0; i < samples.Length; i++)
        {
            string s = CurrentJumpExecution.StationLocationText(samples[i]);
            double r;
            string why = JumpWire.ParseLocation(s, out r);
            round &= why == null && (samples[i] == 0.0 ? r == 0.0 : Bits(r) == Bits(samples[i])) && s.IndexOf(',') < 0;
        }
        Check("S03 sample positions round-trip exactly (the zero of either sign reads back as zero)", round);
        bool fine = true;
        double[] outside = new double[] { 1e12, 1e-12, double.NaN, double.PositiveInfinity, double.NegativeInfinity, -1e12 };
        for (int i = 0; i < outside.Length; i++)
        {
            string s = null;
            try { s = CurrentJumpExecution.StationLocationText(outside[i]); } catch { s = null; }
            fine &= s != null && s.Length > 0;
        }
        Check("S04 a position outside the wire contract does not throw and gives a text (it can not be the target of a v2 command)", fine);
        CultureInfo savedCulture = Thread.CurrentThread.CurrentCulture;
        bool dot = true;
        try
        {
            string[] names = new string[] { "de-DE", "fr-FR", "ru-RU" };
            for (int i = 0; i < names.Length; i++)
            {
                CultureInfo ci;
                try { ci = new CultureInfo(names[i]); } catch { continue; }
                Thread.CurrentThread.CurrentCulture = ci;
                dot &= CurrentJumpExecution.StationLocationText(1000.5) == "1000.5" && CurrentJumpExecution.StationLocationText(outside[0]).IndexOf(',') < 0;
            }
        }
        finally { Thread.CurrentThread.CurrentCulture = savedCulture; }
        Check("S05 a comma culture does not turn the decimal point into a comma", dot);
    }

    // ---- L: the diagnostic lines: bounded, one per request, only numbers and fixed words -------------------------------------------------------------------------
    static void Lines()
    {
        byte[] id = Req(3);
        bool ok = true;
        string[] reasons = CurrentJumpExecution.Reasons;
        for (int i = 0; i < reasons.Length; i++)
        {
            CurrentJumpDecision d = CurrentJumpExecution.Judge(Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length), View());
            string line = CurrentJumpExecution.RefusedLine(id, d, reasons[i], i % 2 == 0 ? "-" : "station-index-range");
            ok &= line.Length <= CurrentJumpExecution.MaxLineLength && line.StartsWith("event=current-jump-refused id=") && line.IndexOf("reason=" + reasons[i] + " ") > 0 && line.IndexOf('\n') < 0 && line.IndexOf('\r') < 0;
        }
        Check("L01 a refusal line of every reason is one bounded line with the event, the id and the reason", ok);
        CurrentJumpDecision rd = CurrentJumpExecution.Judge("JUMP_STA_TIME:1:36000000", View());
        string line1 = CurrentJumpExecution.RefusedLine(null, rd, rd.Reason, rd.Detail);
        Check("L02 a command without a RequestId (normal mode) and without a v2 request prints id=- and no request fields (a v1 text names no index and no count: ?): " + line1, line1.IndexOf("id=-") > 0 && line1.IndexOf("req_idx=? req_count=? current_count=6 scope=-") > 0 && line1.IndexOf("req_loc") < 0);
        Check("L03 the id is the first four bytes in hex", CurrentJumpExecution.IdText(id) == "020b0c15");
        Check("L04 a null id is - and an empty id is -", CurrentJumpExecution.IdText(null) == "-" && CurrentJumpExecution.IdText(new byte[0]) == "-");
        string worst = CurrentJumpExecution.CompletedLine(id, "STA", int.MaxValue - 1, int.MaxValue - 1, -999999999.12345678, 999999999.87654329, int.MaxValue, int.MaxValue);
        Check("L05 the completed line is bounded even with the widest numbers (" + worst.Length + " characters)", worst.Length <= CurrentJumpExecution.MaxLineLength && worst.StartsWith("event=current-jump-complete id=") && worst.EndsWith("status=handed"));
        string normal = CurrentJumpExecution.CompletedLine(id, "LOC", 2, 2, 1000.0, 999.75, TimeMs, 4);
        Check("L06 the completed line names the requested index, the selected index, the scope verdict, both positions, the time and the status: " + normal, normal.IndexOf("req_idx=2 sel_idx=2 scope=ok req_loc=1000 act_loc=999.75 time=36000000 jc=4 status=handed") > 0);
        string aborted = CurrentJumpExecution.AbortedLine(id, "STA", 3, "scenario-changed", "-");
        Check("L07 the aborted line names the adopted index and the reason", aborted.Length <= CurrentJumpExecution.MaxLineLength && aborted.IndexOf("sel_idx=3 reason=scenario-changed detail=-") > 0);
        string pattern = "event=[a-z-]+( [a-z_]+=[A-Za-z0-9.+?\\-]+)*";
        System.Text.RegularExpressions.Regex shape = new System.Text.RegularExpressions.Regex("^" + pattern + "$");
        Check("L08 every line is event= followed by key=value words of numbers and fixed words only", shape.IsMatch(line1) && shape.IsMatch(worst) && shape.IsMatch(normal) && shape.IsMatch(aborted));
        CultureInfo savedCulture = Thread.CurrentThread.CurrentCulture;
        string deLine;
        try
        {
            try { Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE"); } catch { }
            deLine = CurrentJumpExecution.CompletedLine(id, "LOC", 2, 2, 1000.5, 999.75, TimeMs, 4);
        }
        finally { Thread.CurrentThread.CurrentCulture = savedCulture; }
        Check("L09 a comma culture changes nothing in a line", deLine == CurrentJumpExecution.CompletedLine(id, "LOC", 2, 2, 1000.5, 999.75, TimeMs, 4) && deLine.IndexOf(',') < 0);

        CurrentJumpDecision lineDecision = CurrentJumpExecution.Judge(Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length), View());
        string refusedLine = CurrentJumpExecution.RefusedLine(id, lineDecision, lineDecision.Reason, lineDecision.Detail);
        string refusedComma;
        try
        {
            try { Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE"); } catch { }
            refusedComma = CurrentJumpExecution.RefusedLine(id, lineDecision, lineDecision.Reason, lineDecision.Detail);
        }
        finally { Thread.CurrentThread.CurrentCulture = savedCulture; }
        Check("L10 a refusal line names the requested index and position as plain invariant numbers, in any culture: " + refusedLine, refusedLine.IndexOf("reason=location-mismatch detail=- req_idx=1 req_count=6 current_count=6 scope=ok req_loc=1040.5") > 0 && refusedComma == refusedLine);
    }

    // ---- D: G-RC-1, what a refusal line says about the named index and count (Commit Prep). The shared reader returns no value when it refuses, so the line reads the two fields by position,
    // for the line only; the verdict is the reader's and the plugin's own. -------------------------------------------------------------------------------------------------------------
    static string Refusal(string text, CurrentJumpView view)
    {
        CurrentJumpDecision d = CurrentJumpExecution.Judge(text, view);
        return CurrentJumpExecution.RefusedLine(Req(3), d, d.Reason, d.Detail);
    }

    static bool Has(string line, string part) { return line.IndexOf(part, StringComparison.Ordinal) > 0; }

    static void Diagnostics()
    {
        string line;
        CurrentJumpDecision d;
        d = CurrentJumpExecution.Judge("JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:5:500", View());
        line = Refusal("JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:5:500", View());
        Check("D01 index -1 with count 5: the reader's word is the one word station-index-range, and the line keeps the named values: " + line, !d.Accepted && d.Reason == "malformed" && d.Detail == "station-index-range" && Has(line, "reason=malformed detail=station-index-range req_idx=-1 req_count=5 current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:5:36000000:7:A1B2C3D4:5:500", View());
        Check("D02 index 5 with count 5 (index == count): the same single word, req_idx=5 req_count=5: " + line, Has(line, "detail=station-index-range req_idx=5 req_count=5 current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:999:36000000:7:A1B2C3D4:5:500", View());
        Check("D03 index 999 with count 5: " + line, Has(line, "detail=station-index-range req_idx=999 req_count=5 current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:abc:36000000:7:A1B2C3D4:5:500", View());
        Check("D04 an index that is not a number: req_idx=? and the count is kept: " + line, Has(line, "detail=station-index-syntax req_idx=? req_count=5 current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:3:36000000:7:A1B2C3D4:xyz:500", View());
        Check("D05 a count that is not a number: req_count=? and the index is kept: " + line, Has(line, "detail=count-syntax req_idx=3 req_count=? current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:3:36000000:7:A1B2C3D4:5", View());
        Check("D06 too few fields: nothing can be read by position (? ?): " + line, Has(line, "detail=field-count req_idx=? req_count=? current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:3:36000000:7:A1B2C3D4:5:500:9", View());
        Check("D07 too many fields: (? ?): " + line, Has(line, "detail=field-count req_idx=? req_count=? current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:1:36000000", View());
        Check("D08 a v1 text names neither a count nor a scope (? ?) and is refused as unsupported-version: " + line, Has(line, "reason=unsupported-version detail=- req_idx=? req_count=? current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:3:36000000:7", View());
        Check("D09 a text of four fields (a version that does not exist): (? ?): " + line, Has(line, "detail=field-count req_idx=? req_count=? current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME;3;36000000;7;A1B2C3D4;5;500", View());
        Check("D10 another delimiter: (? ?), the prefix is the reason: " + line, Has(line, "detail=prefix req_idx=? req_count=? current_count=6 scope=-"));
        line = Refusal("JUMP_STA_TIME:1:36000000:7:A1B2C3D4:7:1000", View());
        Check("D11 after a good parse, a count that is not the plugin's: the line has the named count 7 and the plugin's real count 6: " + line, Has(line, "reason=count-mismatch detail=- req_idx=1 req_count=7 current_count=6 scope=no req_loc=1000"));
        line = Refusal(Request("STA", 1, Locations[1], Scenario, "A1B2C3D5", Locations.Length), View());
        Check("D12 after a good parse, a list id that is not the plugin's keeps the index and the counts (and not the list id): " + line, Has(line, "reason=list-mismatch detail=- req_idx=1 req_count=6 current_count=6 scope=no") && !Has(line, "A1B2C3D5"));
        line = Refusal(Request("STA", 1, Locations[1], Scenario + 1, ListId, Locations.Length), View());
        Check("D13 after a good parse, another scenario keeps the same three values: " + line, Has(line, "reason=scenario-mismatch detail=- req_idx=1 req_count=6 current_count=6 scope=no"));
        line = Refusal("JUMP_STA_TIME:2:36000000:7:A1B2C3D4:xyz:500", View());
        Check("D14 only the index can be read: " + line, Has(line, "req_idx=2 req_count=? current_count=6"));
        line = Refusal("JUMP_STA_TIME:x:36000000:7:A1B2C3D4:5:500", View());
        Check("D15 only the count can be read: " + line, Has(line, "req_idx=? req_count=5 current_count=6"));
        line = Refusal("JUMP_STA_TIME:x:36000000:7:A1B2C3D4:y:500", View());
        Check("D16 neither can be read: " + line, Has(line, "req_idx=? req_count=? current_count=6"));
        line = Refusal("JUMP_LOC_TIME:500:36000000:7:A1B2C3D4:5:-1", View());
        Check("D17 a location command keeps its index in the last field (the layout differs from STA): " + line, Has(line, "detail=station-index-range req_idx=-1 req_count=5 current_count=6 scope=-"));
        CurrentJumpView three = View();
        three.Locations = new double[] { 1.0, 2.0, 3.0 };
        CurrentJumpView noList = View();
        noList.Locations = null;
        Check("D18 current_count is the length of the plugin's own list (3 here), and ? when there is no view or no list", Has(Refusal("JUMP_STA_TIME:x:1:7:A1B2C3D4:5:5", three), "current_count=3") && Has(Refusal("JUMP_STA_TIME:x:1:7:A1B2C3D4:5:5", null), "current_count=?")
            && Has(Refusal("JUMP_STA_TIME:x:1:7:A1B2C3D4:5:5", noList), "current_count=?") && Has(Refusal("JUMP_STA_TIME:x:1:7:A1B2C3D4:5:5", View()), "current_count=6"));

        // the line does not carry the command: no prefix, no separator, no list id, no time, no location text of a malformed command
        string[] bodies = new string[] { "JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:5:500.25", "JUMP_LOC_TIME:500.25:36000000:7:A1B2C3D4:5:abc", "JUMP_STA_TIME:3:36000000:7:A1B2C3D4:5", Request("STA", 1, Locations[3], Scenario, "A1B2C3D5", Locations.Length) };
        bool clean = true;
        for (int i = 0; i < bodies.Length; i++)
        {
            string l = Refusal(bodies[i], View());
            clean &= l.IndexOf("JUMP_") < 0 && l.IndexOf(':') < 0 && l.IndexOf("A1B2C3D") < 0 && l.IndexOf("36000000") < 0 && l.IndexOf("500.25") < 0 && l.IndexOf('\n') < 0 && l.IndexOf('\r') < 0 && l.Length <= CurrentJumpExecution.MaxLineLength;
        }
        Check("D19 a refusal line never carries the body: no command word, no ':' , no list id, no time, no position of a malformed command", clean);

        // every value of the line is a short number or ?
        System.Text.RegularExpressions.Regex shape = new System.Text.RegularExpressions.Regex("^event=current-jump-refused id=[0-9a-f-]+ v=[0-9] kind=[A-Z-]+ reason=[a-z-]+ detail=[a-z-]+ req_idx=(\\?|-?[0-9]{1,10}) req_count=(\\?|-?[0-9]{1,10}) current_count=(\\?|[0-9]+) scope=(ok|no|-)( req_loc=[0-9.eE+\\-]+)?$");
        bool shaped = true;
        string[] shapes = new string[] { "JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:5:500", "JUMP_STA_TIME:abc:1:7:A1B2C3D4:xyz:500", "x", "", null, "JUMP_STA_TIME:1:36000000", Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length), Request("LOC", 2, Locations[2], Scenario + 1, ListId, Locations.Length) };
        for (int i = 0; i < shapes.Length; i++) shaped &= shape.IsMatch(Refusal(shapes[i], View()));
        Check("D20 a refusal line is the fixed words and short numbers or ? (" + shapes.Length + " shapes)", shaped);

        // the widest numbers: each value is bounded by itself, so the line is whole (the tail req_loc is not cut) at the cap
        string longest = "";
        bool whole = true;
        string[] details = new string[] { "station-index-syntax", "selected-idx-syntax", "location-precision", "station-index-range", "scope-incomplete" };
        string[] words = CurrentJumpExecution.Reasons;
        for (int i = 0; i < words.Length; i++)
        {
            // a command that was read (it has a position, the detail is "-"): the widest numbers and the widest position, the tail req_loc must be whole
            CurrentJumpDecision w = new CurrentJumpDecision();
            w.Version = 2;
            w.Kind = "STA";
            w.HasRequest = true;
            w.RequestedIndex = int.MaxValue - 1;
            w.RequestedLocation = -999999999.12345678;
            w.Diagnostic = new CurrentJumpDiagnostic("-2147483648", "-2147483648", "2147483647");
            string l = CurrentJumpExecution.RefusedLine(Req(3), w, words[i], "-");
            if (l.Length > longest.Length) longest = l;
            whole &= l.Length <= CurrentJumpExecution.MaxLineLength && l.EndsWith("req_loc=" + CurrentJumpExecution.StationLocationText(-999999999.12345678));
            // a command the reader refused (no position; the widest reader word as the detail)
            CurrentJumpDecision m = new CurrentJumpDecision();
            m.Version = 2;
            m.Kind = "STA";
            m.Diagnostic = new CurrentJumpDiagnostic("-2147483648", "-2147483648", "2147483647");
            for (int j = 0; j < details.Length; j++)
            {
                string l2 = CurrentJumpExecution.RefusedLine(Req(3), m, words[i], details[j]);
                if (l2.Length > longest.Length) longest = l2;
                whole &= l2.Length <= CurrentJumpExecution.MaxLineLength && l2.IndexOf("current_count=2147483647 scope=-") > 0;
            }
        }
        Check("D21 the longest refusal line (" + longest.Length + " characters, widest numbers, every reason) is within the cap and whole, so no value is cut by it: " + longest, whole && longest.Length > 150);

        // a diagnostic that was not built from a body (garbage, too long, a null) still prints only a number or ?
        CurrentJumpDecision g = new CurrentJumpDecision();
        g.Diagnostic = new CurrentJumpDiagnostic("JUMP_STA_TIME:1", "a b", new string('9', 50));
        string gl = CurrentJumpExecution.RefusedLine(Req(3), g, "malformed", "prefix");
        CurrentJumpDecision gn = new CurrentJumpDecision();
        gn.Diagnostic = null;
        string gnl = CurrentJumpExecution.RefusedLine(Req(3), gn, "malformed", "prefix");
        Check("D22 a value that is not a short number prints as ? (even from a hand-made diagnostic), and a missing diagnostic prints ? ? ?: " + gl, Has(gl, "req_idx=? req_count=? current_count=? scope=-") && Has(gnl, "req_idx=? req_count=? current_count=? scope=-") && Has(CurrentJumpExecution.RefusedLine(Req(3), null, "malformed", "prefix"), "req_idx=? req_count=? current_count=? scope=-"));

        // never an exception, always ? or a short number, for texts that are not commands
        string[] odd = new string[] { null, "", ":", "::::::", ":::::::", "JUMP_STA_TIME", "JUMP_STA_TIME::::::", "JUMP_STA_TIME:\u0000:1:7:A1B2C3D4:5:5", "JUMP_STA_TIME:１:1:7:A1B2C3D4:５:5", "JUMP_STA_TIME:123456789012:1:7:A1B2C3D4:123456789012:5",
            "JUMP_STA_TIME:-:1:7:A1B2C3D4:-:5", "JUMP_STA_TIME:+1:1:7:A1B2C3D4:+5:5", "JUMP_STA_TIME: 1:1:7:A1B2C3D4:5 :5", new string(':', 6), new string('9', 300), "JUMP_STA_TIME:" + new string('1', 300) + ":1:7:A1B2C3D4:5:5", new string(':', 100000) };
        bool safe = true;
        for (int i = 0; i < odd.Length; i++)
        {
            try
            {
                CurrentJumpDiagnostic x = CurrentJumpExecution.Describe(odd[i], View());
                CurrentJumpDecision y = CurrentJumpExecution.Judge(odd[i], View());
                string ol = CurrentJumpExecution.RefusedLine(Req(3), y, y.Reason, y.Detail);
                safe &= x != null && y.Diagnostic != null && !y.Accepted && ol.Length <= CurrentJumpExecution.MaxLineLength && x.CurrentCountText == "6";
                string[] vs = new string[] { x.RequestedIndexText, x.RequestedCountText };
                for (int k = 0; k < vs.Length; k++) safe &= vs[k] == "?" || System.Text.RegularExpressions.Regex.IsMatch(vs[k], "^-?[0-9]{1,10}$");
            }
            catch { safe = false; }
        }
        Check("D23 texts that are not commands never throw, are never accepted, and give only ? or a short number (" + odd.Length + " texts; full-width digits, a sign alone, a blank, 12 digits and 100000 separators included)", safe);
        CurrentJumpDiagnostic none = CurrentJumpExecution.Describe(null, null);
        Check("D24 no text and no view is (? ? ?)", none.RequestedIndexText == "?" && none.RequestedCountText == "?" && none.CurrentCountText == "?");
        CurrentJumpDiagnostic ok2 = CurrentJumpExecution.Describe("JUMP_STA_TIME:0:1:7:A1B2C3D4:1:5", View());
        Check("D25 index 0 and count 1 are read as they are (0 is a value, not an absence)", ok2.RequestedIndexText == "0" && ok2.RequestedCountText == "1" && ok2.CurrentCountText == "6");

        CurrentJumpDiagnostic longText = CurrentJumpExecution.Describe("JUMP_STA_TIME:1:36000000:7:A1B2C3D4:5:" + new string('1', 300), View());
        Check("D28 a text longer than a command can be is not scanned at all (? ?), whatever its first fields say", longText.RequestedIndexText == "?" && longText.RequestedCountText == "?" && longText.CurrentCountText == "6");

        // the verdict is the reader's and the plugin's own: for every kind of text the verdict does not depend on the diagnostic (it is set after the verdict and nothing reads it back)
        bool same = true;
        string[] verdictTexts = new string[] { Request("STA", 0), Request("LOC", 5), Request("STA", 1, Locations[3], Scenario, ListId, Locations.Length), "JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:5:500", "JUMP_STA_TIME:1:36000000", "x", null };
        for (int i = 0; i < verdictTexts.Length; i++)
        {
            CurrentJumpDecision a = CurrentJumpExecution.Judge(verdictTexts[i], View());
            CurrentJumpDecision b = CurrentJumpExecution.Judge(verdictTexts[i], View());
            b.Diagnostic = new CurrentJumpDiagnostic("999", "999", "999");
            same &= a.Accepted == b.Accepted && a.Reason == b.Reason && a.Detail == b.Detail && a.StationIndex == b.StationIndex && Bits(a.Location) == Bits(b.Location) && a.Version == b.Version && a.Kind == b.Kind && a.HasRequest == b.HasRequest && a.RequestedIndex == b.RequestedIndex && a.TimeMs == b.TimeMs;
        }
        Check("D26 an accepted command is accepted and a refused one refused with the same words whatever the diagnostic says (" + verdictTexts.Length + " texts)", same);
        bool acceptedOk = true;
        for (int i = 0; i < Locations.Length; i++)
        {
            CurrentJumpDecision a = CurrentJumpExecution.Judge(Request("STA", i), View());
            acceptedOk &= a.Accepted && a.StationIndex == i && a.Diagnostic.RequestedIndexText == i.ToString(CultureInfo.InvariantCulture) && a.Diagnostic.RequestedCountText == "6" && a.Diagnostic.CurrentCountText == "6";
        }
        Check("D27 an accepted command adopts the index it names, and its diagnostic names the same index (the line of a later host-stage refusal)", acceptedOk);
    }

    // ---- V: the grammar gate of the endpoint (N-49): v1 and v2 over the shared reader ---------------------------------------------------------------------------------
    static byte[] Command(uint type, string text, byte[] requestId)
    {
        return DataPlaneProtocol.EncodeEnvelope(type, (uint)Pid, AppPid, JumpGen, Inst, Token(9), requestId, Encoding.UTF8.GetBytes(text));
    }

    static JumpCommandValidator NewValidator(bool sharedWireGrammar)
    {
        FakeSource src = new FakeSource();
        src.Endpoint = new TelemetryEndpoint((uint)Pid, Inst, AppPid, 40001U, 5U, Token(50), 3U, 7U);
        // true = the Current gate (the form CurrentJumpEndpoint.Create builds); false = the five argument form that the Legacy plane builds (LegacyJumpEndpoint.Open)
        return sharedWireGrammar ? new JumpCommandValidator(Pid, JumpGen, Token(9), src, null, true) : new JumpCommandValidator(Pid, JumpGen, Token(9), src, null);
    }

    static void Grammar()
    {
        JumpCommandValidator v = NewValidator(true);
        string reason;
        byte seed = 40;
        CurrentJumpCommand c = v.Validate(Command(0x100U, "JUMP_STA_TIME:3:43000000", Req(seed++)), out reason);
        Check("V01 a v1 station command is still a valid grammar (the transition is not broken)", c == null ? false : c.Text == "JUMP_STA_TIME:3:43000000");
        c = v.Validate(Command(0x101U, "JUMP_LOC_TIME:1000.5:36000000", Req(seed++)), out reason);
        Check("V02 a v1 location command is still a valid grammar", c != null && c.Text == "JUMP_LOC_TIME:1000.5:36000000");
        string sta = Request("STA", 3);
        string loc = Request("LOC", 2);
        byte[] idSta = Req(seed++);
        c = v.Validate(Command(0x100U, sta, idSta), out reason);
        Check("V03 a v2 station command is a valid grammar and is handed on unchanged (" + sta + ")", c != null && c.Text == sta && c.MessageType == 0x100U);
        c = v.Validate(Command(0x101U, loc, Req(seed++)), out reason);
        Check("V04 a v2 location command is a valid grammar and is handed on unchanged (" + loc + ")", c != null && c.Text == loc && c.MessageType == 0x101U);
        c = v.Validate(Command(0x100U, loc, Req(seed++)), out reason);
        Check("V05 a v2 location text under the station type is refused (payload-grammar)", c == null && reason == "payload-grammar");
        c = v.Validate(Command(0x101U, sta, Req(seed++)), out reason);
        Check("V06 a v2 station text under the location type is refused (payload-grammar)", c == null && reason == "payload-grammar");
        c = v.Validate(Command(0x100U, sta + ":9", Req(seed++)), out reason);
        Check("V07 eight fields are refused (payload-grammar)", c == null && reason == "payload-grammar");
        c = v.Validate(Command(0x101U, "JUMP_LOC_TIME:NaN:36000000:7:A1B2C3D4:6:1", Req(seed++)), out reason);
        Check("V08 a v2 NaN location is refused (payload-grammar)", c == null && reason == "payload-grammar");
        c = v.Validate(Command(0x100U, "JUMP_STA_TIME:-1:36000000:7:A1B2C3D4:6:500", Req(seed++)), out reason);
        Check("V09 a v2 negative index is refused by the grammar (payload-grammar)", c == null && reason == "payload-grammar");
        c = v.Validate(Command(0x100U, "JUMP_STA_TIME:3", Req(seed++)), out reason);
        Check("V10 one field is refused (payload-grammar)", c == null && reason == "payload-grammar");
        string[] ambiguous = new string[] { "JUMP_STA_TIME: 3:43000000", "JUMP_STA_TIME:3 :43000000", "JUMP_STA_TIME:+3:43000000", "JUMP_STA_TIME:03:43000000", "JUMP_STA_TIME:3:+43000000", "JUMP_STA_TIME:3:043000000", "JUMP_STA_TIME:-0:43000000" };
        int refused = 0;
        for (int i = 0; i < ambiguous.Length; i++)
        {
            c = v.Validate(Command(0x100U, ambiguous[i], Req(seed++)), out reason);
            if (c == null && reason == "payload-grammar") refused++;
        }
        Check("V11 the ambiguous v1 spellings (blank, leading +, leading zero, minus zero) are refused by the shared reader (" + refused + " of " + ambiguous.Length + ")", refused == ambiguous.Length);
        string[] oldDouble = new string[] { "JUMP_LOC_TIME: 1000:36000000", "JUMP_LOC_TIME:+1000:36000000", "JUMP_LOC_TIME:1e3:36000000", "JUMP_LOC_TIME:.5:36000000", "JUMP_LOC_TIME:5.:36000000" };
        int refusedLoc = 0;
        for (int i = 0; i < oldDouble.Length; i++)
        {
            c = v.Validate(Command(0x101U, oldDouble[i], Req(seed++)), out reason);
            if (c == null && reason == "payload-grammar") refusedLoc++;
        }
        Check("V12 location spellings that the old reader took but the contract does not allow are refused (blank, +, .5, 5.: " + refusedLoc + " of 4)", refusedLoc == 4);
        c = v.Validate(Command(0x101U, "JUMP_LOC_TIME:1e3:36000000", Req(seed++)), out reason);
        Check("V13 the exponent form that the contract does allow is still a valid v1 grammar", c != null && c.Text == "JUMP_LOC_TIME:1e3:36000000");
        long before = v.Accepted;
        c = v.Validate(Command(0x100U, sta, idSta), out reason);
        Check("V14 the RequestId rules of the validator are untouched: a v2 command with an id that was accepted is a duplicate", c == null && reason == "duplicate-request-id" && v.Accepted == before);
    }

    // ---- G: the five argument validator (the form the LEGACY plane builds) keeps the grammar this gate had before ST-3b (review of ST-3b, G-3B-2 plan A) ------------------------------
    static readonly string[] AmbiguousSta = new string[] { "JUMP_STA_TIME: 1:0", "JUMP_STA_TIME:1: 0", "JUMP_STA_TIME:1:0 ", "JUMP_STA_TIME:+1:0", "JUMP_STA_TIME:01:0", "JUMP_STA_TIME:1:0\n" };
    static readonly string[] AmbiguousLoc = new string[] { "JUMP_LOC_TIME: 1000.5:0", "JUMP_LOC_TIME:1000.5 :0", "JUMP_LOC_TIME:.5:0", "JUMP_LOC_TIME:5.:0", "JUMP_LOC_TIME:+5:0", "JUMP_LOC_TIME:007:0",
                                                        "JUMP_LOC_TIME:1e300:0", "JUMP_LOC_TIME:1e-300:0", "JUMP_LOC_TIME:1000000001:0", "JUMP_LOC_TIME:1e-10:0" };

    static void LegacyCompatibleGate()
    {
        JumpCommandValidator legacy = NewValidator(false);
        JumpCommandValidator current = NewValidator(true);
        string reason;
        byte seed = 120;
        CurrentJumpCommand c = legacy.Validate(Command(0x100U, "JUMP_STA_TIME:3:43000000", Req(seed++)), out reason);
        Check("G01 the five argument validator accepts a formal v1 station command", c != null && c.Text == "JUMP_STA_TIME:3:43000000" && c.MessageType == 0x100U);
        c = legacy.Validate(Command(0x101U, "JUMP_LOC_TIME:1000.5:36000000", Req(seed++)), out reason);
        Check("G02 the five argument validator accepts a formal v1 location command", c != null && c.Text == "JUMP_LOC_TIME:1000.5:36000000" && c.MessageType == 0x101U);
        c = legacy.Validate(Command(0x100U, Request("STA", 3), Req(seed++)), out reason);
        Check("G03 the five argument validator refuses a v2 station command (seven fields: payload-grammar, as before ST-3b; Legacy has no v2 until ST-3c)", c == null && reason == "payload-grammar");
        c = legacy.Validate(Command(0x101U, Request("LOC", 3), Req(seed++)), out reason);
        Check("G04 the five argument validator refuses a v2 location command (payload-grammar, as before ST-3b)", c == null && reason == "payload-grammar");
        c = legacy.Validate(Command(0x100U, "JUMP_LOC_TIME:1000.5:36000000", Req(seed++)), out reason);
        Check("G05 the five argument validator still refuses a location text under the station type", c == null && reason == "payload-grammar");
        c = legacy.Validate(Command(0x101U, "JUMP_LOC_TIME:NaN:36000000", Req(seed++)), out reason);
        Check("G06 the five argument validator still refuses a NaN location", c == null && reason == "payload-grammar");
        int legacyTook = 0;
        int currentRefused = 0;
        for (int i = 0; i < AmbiguousSta.Length; i++)
        {
            c = legacy.Validate(Command(0x100U, AmbiguousSta[i], Req(seed++)), out reason);
            if (c != null && c.Text == AmbiguousSta[i]) legacyTook++;
            c = current.Validate(Command(0x100U, AmbiguousSta[i], Req(seed++)), out reason);
            if (c == null && reason == "payload-grammar") currentRefused++;
        }
        for (int i = 0; i < AmbiguousLoc.Length; i++)
        {
            c = legacy.Validate(Command(0x101U, AmbiguousLoc[i], Req(seed++)), out reason);
            if (c != null && c.Text == AmbiguousLoc[i]) legacyTook++;
            c = current.Validate(Command(0x101U, AmbiguousLoc[i], Req(seed++)), out reason);
            if (c == null && reason == "payload-grammar") currentRefused++;
        }
        int all = AmbiguousSta.Length + AmbiguousLoc.Length;
        Check("G07 the 16 ambiguous v1 spellings are taken by the five argument validator exactly as before ST-3b (" + legacyTook + " of " + all + ")", all == 16 && legacyTook == all);
        Check("G08 the same 16 are refused by the Current gate (" + currentRefused + " of " + all + "): the two grammars are chosen by the constructor, nothing else", currentRefused == all);
    }
}
