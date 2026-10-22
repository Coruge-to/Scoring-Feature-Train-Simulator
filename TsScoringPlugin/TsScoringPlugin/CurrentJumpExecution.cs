using System;
using System.Globalization;
using System.Text;

// ============================================================================
// PHASE PID-D4JA StationIndex ST-3b - the CURRENT jump decision, pure. CURRENT-ONLY (compiled into the Current project only; the Legacy project does not link it).
//
// Class1.cs can not run offline (it needs the BveEX host), so everything it DECIDES about an official jump lives here and is held by compiled tests
// (Handshake\Tests\Test-CurrentJumpST3B.ps1); Class1.cs only reads its own fields, calls this file and talks to the host. Host independent: no BVE / BveEx / AtsEx name, no
// file, no socket, no clock, no thread, no state. Written in C# 5 syntax on purpose (the offline tests compile the product files directly).
//
// The contract (the wire is JumpWire.cs, Telemetry\Shared; the Python twin is jump_wire.py):
//   * a v2 command is executed ONLY with the StationIndex it names, after the scenario, the list (id and count), the index and the location have been checked against what the plugin
//     holds NOW. The first check that fails refuses the command: no host call, no completion, one diagnostic line. There is no fallback station, no nearest station and no search.
//   * a v1 command is read (it is a valid grammar) but not executed: it carries no scope, so nothing could be checked (the official transaction of ST-3 is v2).
//   * the station the plugin targets after an official jump is the ADOPTED index (ResolveRequestedTarget). The position search of Class1.cs is a different function that is reached
//     only when NO index was requested (first Tick, scenario change, manual time jump): the two never meet.
//   * the completion carries the index that was really adopted and the position the vehicle really has (read from the host), through the JumpWire v2 formatter.
// ============================================================================
namespace TSScoringPlugin.DataPlane
{
    /// <summary>What the plugin holds at the moment a command is judged. Built by the caller from its own fields; nothing here reads the host.</summary>
    internal sealed class CurrentJumpView
    {
        internal int ScenarioId = -1;                 // the plugin's scenario id (-1 = none)
        internal bool ListReady;                      // the identity of the station list has been computed for this scenario
        internal string ListId;                       // that identity (8 characters 0-9 A-F)
        internal int ListCount;                       // the count that identity was computed for
        internal double[] Locations;                  // the station list in list order (null = none)
    }

    /// <summary>What a refusal line may say about the command and the plugin's own list, as text: the index and the count the command NAMED (as received, a short number or "?") and the count of the
    /// plugin's list. For the diagnostic line ONLY: nothing reads it to decide, to call the host, to choose a station or to write a completion.</summary>
    internal sealed class CurrentJumpDiagnostic
    {
        internal static readonly CurrentJumpDiagnostic Unknown = new CurrentJumpDiagnostic(CurrentJumpExecution.DiagUnknown, CurrentJumpExecution.DiagUnknown, CurrentJumpExecution.DiagUnknown);

        internal readonly string RequestedIndexText;
        internal readonly string RequestedCountText;
        internal readonly string CurrentCountText;

        internal CurrentJumpDiagnostic(string requestedIndexText, string requestedCountText, string currentCountText)
        {
            RequestedIndexText = requestedIndexText;
            RequestedCountText = requestedCountText;
            CurrentCountText = currentCountText;
        }
    }

    /// <summary>The verdict on one command. Accepted: StationIndex / Location are the ADOPTED values (the ones the host is called with). Otherwise Reason (and Detail) say why.</summary>
    internal sealed class CurrentJumpDecision
    {
        internal bool Accepted;
        internal string Reason;                       // null when Accepted
        internal string Detail;                       // "-" or a JumpWire reason word (malformed)
        internal int Version;                         // 0 = the text could not be read; 1; 2
        internal string Kind = "-";                   // STA / LOC, "-" when unknown
        internal int RequestedIndex = -1;             // v2 only
        internal double RequestedLocation;            // v2 only
        internal bool HasRequest;                     // RequestedIndex / RequestedLocation / Scope are set
        internal int StationIndex = -1;               // the adopted index
        internal double Location;                     // the adopted location (the location of the adopted station)
        internal int TimeMs;
        internal JumpWireScope Scope;
        internal CurrentJumpDiagnostic Diagnostic = CurrentJumpDiagnostic.Unknown;   // for RefusedLine only (G-RC-1); set once by Judge after the verdict, never read by the verdict code
    }

    internal static class CurrentJumpExecution
    {
        // -- the verdict words (fixed; none contains a value) -----------------------------------------------------------------------------------------------
        internal const string RMalformed = "malformed";                         // Detail: the JumpWire reason word
        internal const string RUnsupportedVersion = "unsupported-version";
        internal const string RScenarioMismatch = "scenario-mismatch";
        internal const string RListNotReady = "list-not-ready";
        internal const string RListMismatch = "list-mismatch";
        internal const string RCountMismatch = "count-mismatch";
        internal const string RListInconsistent = "list-inconsistent";
        internal const string RIndexRange = "index-out-of-range";
        internal const string RLocationMismatch = "location-mismatch";
        // the execution stage (decided by the plugin around the host calls)
        internal const string RScenarioMissing = "scenario-missing";
        internal const string RApiMissing = "api-missing";
        internal const string RTimeFieldMissing = "time-field-missing";
        internal const string RJumpException = "jump-exception";
        internal const string RReinitRange = "reinit-index-range";
        internal const string RReinitLocation = "reinit-location-mismatch";
        internal const string RCompletionUnreadable = "completion-unreadable";
        internal const string RCompletionFormat = "completion-format";
        internal const string RSuperseded = "superseded";
        internal const string RScenarioChanged = "scenario-changed";

        internal const int MaxLineLength = 200;
        internal const string DiagUnknown = "?";
        internal const int MaxDiagValueLength = 11;          // "-2147483648": a value longer than any Int32 text is not printed
        internal const int MaxDiagScanLength = 256;          // a command of the wire is far shorter; a longer text is not scanned at all

        internal static readonly string[] Reasons = new string[]
        {
            RMalformed, RUnsupportedVersion, RScenarioMismatch, RListNotReady, RListMismatch, RCountMismatch, RListInconsistent, RIndexRange, RLocationMismatch,
            RScenarioMissing, RApiMissing, RTimeFieldMissing, RJumpException, RReinitRange, RReinitLocation, RCompletionUnreadable, RCompletionFormat, RSuperseded, RScenarioChanged
        };

        // -- 1. the judgement of one command (before ANY host call) -----------------------------------------------------------------------------------------
        /// <summary>The verdict on the text of one command (JumpWire v1 or v2 grammar). Never throws. The first failing step gives the reason:
        /// grammar, version, scenario, list ready, list id, count, the plugin's own list, index range, location.</summary>
        internal static CurrentJumpDecision Judge(string text, CurrentJumpView view)
        {
            CurrentJumpDecision d = new CurrentJumpDecision();
            try
            {
                JudgeCore(text, view, d);
            }
            catch
            {
                d.Accepted = false;
                d.Reason = RMalformed;
                d.Detail = JumpWire.RLocationRange;
            }
            d.Diagnostic = Describe(text, view);               // after the verdict, for the diagnostic line only; the verdict above is final
            return d;
        }

        private static CurrentJumpDecision JudgeCore(string text, CurrentJumpView view, CurrentJumpDecision d)
        {
            string why;
            JumpWireRequest r = JumpWire.ParseRequest(text, out why);
            if (r == null)
            {
                d.Reason = RMalformed;
                d.Detail = why;
                return d;
            }
            d.Version = r.Version;
            d.Kind = r.Kind;
            d.TimeMs = r.TimeMs;
            if (r.Version != JumpWire.V2)
            {
                d.Reason = RUnsupportedVersion;
                return d;
            }
            d.HasRequest = true;
            d.Scope = r.Scope;
            d.RequestedIndex = r.StationIndex;
            d.RequestedLocation = r.Location;

            if (view == null || view.ScenarioId != r.Scope.ScenarioId) { d.Reason = RScenarioMismatch; return d; }
            if (!view.ListReady) { d.Reason = RListNotReady; return d; }
            if (!string.Equals(view.ListId, r.Scope.ListId, StringComparison.Ordinal)) { d.Reason = RListMismatch; return d; }
            if (view.ListCount != r.Scope.Count) { d.Reason = RCountMismatch; return d; }
            if (view.Locations == null || view.Locations.Length != view.ListCount) { d.Reason = RListInconsistent; return d; }
            if (r.StationIndex < 0 || r.StationIndex >= view.Locations.Length) { d.Reason = RIndexRange; return d; }
            if (view.Locations[r.StationIndex] != r.Location) { d.Reason = RLocationMismatch; return d; }

            d.Accepted = true;
            d.StationIndex = r.StationIndex;
            d.Location = view.Locations[r.StationIndex];
            return d;
        }

        // -- 2. the target after an official jump ----------------------------------------------------------------------------------------------------------
        /// <summary>The ONE re-initialisation that follows an official jump: the index to target, or -1 with the reason when the plugin's list (re-read after the jump) can no longer carry it.
        /// It never looks at the vehicle position and never chooses another station: a refusal is a refusal.</summary>
        internal static int ResolveRequestedTarget(int requestedIndex, double expectedLocation, double[] locations, out string reason)
        {
            reason = null;
            if (locations == null || requestedIndex < 0 || requestedIndex >= locations.Length) { reason = RReinitRange; return -1; }
            if (locations[requestedIndex] != expectedLocation) { reason = RReinitLocation; return -1; }
            return requestedIndex;
        }

        // -- 3. the numbers the plugin writes --------------------------------------------------------------------------------------------------------------
        /// <summary>The JUMP_COMPLETE v2 text of a jump that adopted `selectedIdx`; `actualLocation` and `timeMs` are what the host reports. Null with a JumpWire reason word when something is outside the contract.</summary>
        internal static string FormatCompletion(string kind, int selectedIdx, double actualLocation, int timeMs, int jumpCount, int scenarioId, string listId, int count, out string reason)
        {
            JumpWireScope scope = JumpWire.ValidateScope(scenarioId, listId, count, out reason);
            if (scope == null) return null;
            return JumpWire.FormatCompletionV2(kind, selectedIdx, actualLocation, timeMs, jumpCount, scope, out reason);
        }

        /// <summary>The location of a station in the STALIST text: the shortest text that reads back to exactly the same double (invariant culture), so that the Python side holds the very value the
        /// plugin compares against. A value outside the wire contract falls back to the plain invariant "G17" (such a station can not be the target of a v2 command).</summary>
        internal static string StationLocationText(double location)
        {
            string reason;
            string text = JumpWire.FormatLocation(location, out reason);
            if (text != null) return text;
            return location.ToString("G17", CultureInfo.InvariantCulture);
        }

        // -- 3b. what a refusal line says about the named index and count (G-RC-1) --------------------------------------------------------------------------
        // The shared reader returns no value when it refuses (a negative or too large index is "station-index-range" and nothing else), so the line could not say WHICH index or count was named. This
        // extraction reads only the two fields of a seven field command by position, for the line and for nothing else: it is not the reader, it decides nothing, and its result is never passed to the
        // verdict, the host, the adopted index or the completion. It keeps no text: a field is a short number as received, or "?" (no seven fields, an unknown prefix, a field that is not -digits, a
        // value longer than an Int32 text, a text longer than a command can be). It never throws.
        /// <summary>The index and count a command names and the count of the plugin's list, for the refusal line.</summary>
        internal static CurrentJumpDiagnostic Describe(string text, CurrentJumpView view)
        {
            try
            {
                string indexText = DiagUnknown;
                string countText = DiagUnknown;
                int idxField;
                if (DiagFields(text, out idxField))
                {
                    indexText = DiagNumber(DiagField(text, idxField));
                    countText = DiagNumber(DiagField(text, 5));
                }
                string currentText = DiagUnknown;
                if (view != null && view.Locations != null) currentText = view.Locations.Length.ToString(CultureInfo.InvariantCulture);
                return new CurrentJumpDiagnostic(indexText, countText, currentText);
            }
            catch
            {
                return CurrentJumpDiagnostic.Unknown;
            }
        }

        /// <summary>True when the text has the shape of a seven field command (JUMP_STA_TIME or JUMP_LOC_TIME and six separators); idxField is the field that holds the index (1 for STA, 6 for LOC).</summary>
        private static bool DiagFields(string text, out int idxField)
        {
            idxField = -1;
            if (text == null || text.Length > MaxDiagScanLength) return false;
            int separators = 0;
            for (int i = 0; i < text.Length; i++) if (text[i] == ':') separators++;
            if (separators != 6) return false;
            string prefix = DiagField(text, 0);
            if (string.Equals(prefix, JumpWire.PrefixSta, StringComparison.Ordinal)) idxField = 1;
            else if (string.Equals(prefix, JumpWire.PrefixLoc, StringComparison.Ordinal)) idxField = 6;
            return idxField >= 0;
        }

        /// <summary>Field number `wanted` (0-based) of a text that has six separators.</summary>
        private static string DiagField(string text, int wanted)
        {
            int start = 0;
            for (int n = 0; n < wanted; n++) start = text.IndexOf(':', start) + 1;
            int end = text.IndexOf(':', start);
            if (end < 0) end = text.Length;
            return text.Substring(start, end - start);
        }

        /// <summary>The field as received when it is an optional '-' followed by digits and no longer than an Int32 text; otherwise "?". No parsing and no judgement of the value. The refusal line prints every
        /// diagnostic value through it, so nothing but a short number or "?" can reach the line.</summary>
        private static string DiagNumber(string field)
        {
            if (field == null || field.Length == 0 || field.Length > MaxDiagValueLength) return DiagUnknown;
            int p = field[0] == '-' ? 1 : 0;
            if (p >= field.Length) return DiagUnknown;
            for (int i = p; i < field.Length; i++)
            {
                if (field[i] < '0' || field[i] > '9') return DiagUnknown;
            }
            return field;
        }

        // -- 4. the diagnostic lines (one per request; never per Tick; never a value that is not a number or a fixed word) --------------------------------
        internal static string IdText(byte[] requestId)
        {
            if (requestId == null) return "-";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 4 && i < requestId.Length; i++) sb.Append(requestId[i].ToString("x2", CultureInfo.InvariantCulture));
            return sb.Length == 0 ? "-" : sb.ToString();
        }

        private static string LocationText(double value)
        {
            string reason;
            string text = JumpWire.FormatLocation(value, out reason);
            return text == null ? "?" : text;
        }

        private static string Cap(string line)
        {
            return line.Length <= MaxLineLength ? line : line.Substring(0, MaxLineLength);
        }

        private static string Word(string text)
        {
            return string.IsNullOrEmpty(text) ? "-" : text;
        }

        /// <summary>The scope verdict of a refusal: "no" when the scenario or the list (id, count, readiness) is not the one the command names, "ok" when the scope held and something later failed.</summary>
        private static string ScopeVerdict(string reason)
        {
            if (reason == RScenarioMismatch || reason == RListNotReady || reason == RListMismatch || reason == RCountMismatch || reason == RListInconsistent) return "no";
            return "ok";
        }

        /// <summary>A command that was refused before the host was called (or whose host call failed).</summary>
        internal static string RefusedLine(byte[] requestId, CurrentJumpDecision d, string reason, string detail)
        {
            string scope = "-";
            if (d != null && d.HasRequest) scope = ScopeVerdict(reason);
            CurrentJumpDiagnostic diag = d == null || d.Diagnostic == null ? CurrentJumpDiagnostic.Unknown : d.Diagnostic;     // req_idx / req_count / current_count: as received or "?" (G-RC-1)
            return Cap("event=current-jump-refused id=" + IdText(requestId) + " v=" + (d == null ? 0 : d.Version).ToString(CultureInfo.InvariantCulture) + " kind=" + (d == null ? "-" : Word(d.Kind))
                + " reason=" + Word(reason) + " detail=" + Word(detail) + " req_idx=" + DiagNumber(diag.RequestedIndexText) + " req_count=" + DiagNumber(diag.RequestedCountText)
                + " current_count=" + DiagNumber(diag.CurrentCountText) + " scope=" + scope
                + (d != null && d.HasRequest ? " req_loc=" + LocationText(d.RequestedLocation) : ""));
        }

        /// <summary>A command that was executed but whose completion will never be sent.</summary>
        internal static string AbortedLine(byte[] requestId, string kind, int adoptedIndex, string reason, string detail)
        {
            return Cap("event=current-jump-aborted id=" + IdText(requestId) + " kind=" + Word(kind) + " sel_idx=" + adoptedIndex.ToString(CultureInfo.InvariantCulture) + " reason=" + Word(reason) + " detail=" + Word(detail));
        }

        /// <summary>The completion that the sender took (the one line of a successful request): status=handed = handed to the router, which sent it or recorded its own exclusion (hold-off and endpoint rules are the router's, see its own log lines).</summary>
        internal static string CompletedLine(byte[] requestId, string kind, int requestedIndex, int selectedIdx, double requestedLocation, double actualLocation, int timeMs, int jumpCount)
        {
            return Cap("event=current-jump-complete id=" + IdText(requestId) + " v=2 kind=" + Word(kind) + " req_idx=" + requestedIndex.ToString(CultureInfo.InvariantCulture)
                + " sel_idx=" + selectedIdx.ToString(CultureInfo.InvariantCulture) + " scope=ok req_loc=" + LocationText(requestedLocation) + " act_loc=" + LocationText(actualLocation)
                + " time=" + timeMs.ToString(CultureInfo.InvariantCulture) + " jc=" + jumpCount.ToString(CultureInfo.InvariantCulture) + " status=handed");
        }
    }
}
