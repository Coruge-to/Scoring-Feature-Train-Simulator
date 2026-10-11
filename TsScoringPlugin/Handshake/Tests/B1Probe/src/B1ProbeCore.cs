using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

// ============================================================================
// PHASE SI-B1 - B1-probe: an OBSERVATION-ONLY core for the AtsEX Legacy host. THIS IS NOT A PRODUCT FEATURE and it is NOT Phase SI-B2.
//
// Question it answers (SI-B1 audit): is it safe and equivalent to move the train / set the time from the Legacy Extension Tick with
//   Scenario.Initialize(int) / Scenario.InitializeTimeAndLocation(double,int) followed by TimeManager.SetTime(int)?
// It runs exactly ONE explicitly requested call sequence per request file, on the host's Extension Tick, and logs everything around it.
//
// This file is HOST INDEPENDENT: it names no AtsEx / BveTypes type (the adapter is B1ProbeHost.cs, the only file that calls the host). Everything
// that touches the host goes through IB1ProbeHost and is called from BeginTick only (the Tick thread). Reading the request file, the consumed ledger
// and writing the log are plain file operations: they never touch a BVE object.
//
// Built ONLY into the probe DLL (TSScoringPlugin.AtsExLegacy.Telemetry.B1Probe.csproj). The product telemetry DLL does not contain it.
// It sends nothing to UDP 54321 / 54322, declares nothing in AVAIL (no "jump"), gives no COMPLETE and starts no scoring.
// Written in C# 5 style on purpose: the offline tests compile this very file with Windows PowerShell's Add-Type.
// ============================================================================
namespace TSScoringPlugin.Telemetry.B1Probe
{
    internal static class B1Op
    {
        internal const string SetTime = "SetTime";
        internal const string InitStation = "InitializeStationThenSetTime";
        internal const string InitLocation = "InitializeLocationThenSetTime";
    }

    /// <summary>Fixed reason words of PROBE_REQUEST_REJECTED / PROBE_DISPOSE_REJECTED (no free text from the file is ever written to the log).</summary>
    internal static class B1Reason
    {
        internal const string Unreadable = "unreadable";
        internal const string TooLarge = "too-large";
        internal const string BadFormat = "bad-format";
        internal const string UnknownKey = "unknown-key";
        internal const string DuplicateKey = "duplicate-key";
        internal const string MissingKey = "missing-key";
        internal const string BadValue = "bad-value";
        internal const string BadOperation = "bad-operation";
        internal const string OperationArgs = "operation-args";
        internal const string NotExecuteOnce = "not-execute-once";
        internal const string CreatedInFuture = "created-in-future";
        internal const string CreatedBeforeProcess = "created-before-process-start";
        internal const string TooOld = "too-old";
        internal const string GenerationMismatch = "generation-mismatch";
        internal const string GenerationChanged = "generation-changed";
        internal const string ExecutionCap = "execution-cap";
        internal const string NotReadyTimeout = "not-ready-timeout";
        internal const string StationOutOfRange = "station-out-of-range";
        internal const string SnapshotUnreadable = "snapshot-unreadable";
        internal const string LedgerFailed = "ledger-failed";
        internal const string DisposeStarted = "dispose-started";
        internal const string PendingDropped = "pending-request-dropped";
    }

    /// <summary>One parsed request (see ParseRequest). Immutable after parsing.</summary>
    internal sealed class B1Request
    {
        internal string TestId;
        internal string RequestId;
        internal string Operation;
        internal int StationIndex = -1;                 // -1 = not given
        internal double LocationM = double.NaN;         // NaN = not given
        internal int TimeMs;
        internal DateTime CreatedUtc;
        internal int ExpectGeneration = -1;             // -1 = not given
        internal bool ExecuteOnce;
    }

    internal static class B1RequestParser
    {
        internal const int MaxBytes = 2048;
        internal const string Header = "B1PROBE-REQUEST 1";
        internal const string TimeFormat = "yyyy-MM-ddTHH:mm:ss.fffZ";
        private static readonly Regex TestIdPattern = new Regex("^[A-Za-z0-9_-]{1,24}$", RegexOptions.CultureInvariant);
        private static readonly Regex RequestIdPattern = new Regex("^[A-Za-z0-9-]{8,48}$", RegexOptions.CultureInvariant);
        private static readonly string[] Keys = new string[] { "TestId", "RequestId", "Operation", "StationIndex", "LocationM", "TimeMs", "CreatedAtUtc", "ExpectGeneration", "ExecuteOnce" };

        /// <summary>
        /// Strict key=value parser. Nothing from the file is trusted: a reason word (B1Reason) is returned for every failure and the ids are returned
        /// only when they themselves are valid (so a log line never carries free text from a request).
        /// </summary>
        internal static bool TryParse(string text, out B1Request request, out string reason, out string testIdIfValid, out string requestIdIfValid)
        {
            request = null;
            reason = B1Reason.BadFormat;
            testIdIfValid = null;
            requestIdIfValid = null;
            if (text == null)
            {
                reason = B1Reason.Unreadable;
                return false;
            }

            if (text.Length > MaxBytes)
            {
                reason = B1Reason.TooLarge;
                return false;
            }

            Dictionary<string, string> kv = new Dictionary<string, string>(StringComparer.Ordinal);
            bool headerSeen = false;
            string[] lines = text.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');
            for (int i = 0; i < lines.Length; i++)
            {
                string line = lines[i].Trim();
                if (line.Length == 0 || line[0] == '#')
                {
                    continue;
                }

                if (!headerSeen)
                {
                    if (line != Header)
                    {
                        reason = B1Reason.BadFormat;
                        return false;
                    }

                    headerSeen = true;
                    continue;
                }

                int eq = line.IndexOf('=');
                if (eq <= 0)
                {
                    reason = B1Reason.BadFormat;
                    return false;
                }

                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1).Trim();
                if (Array.IndexOf(Keys, key) < 0)
                {
                    reason = B1Reason.UnknownKey;
                    return false;
                }

                if (kv.ContainsKey(key))
                {
                    reason = B1Reason.DuplicateKey;
                    return false;
                }

                kv[key] = value;
            }

            if (!headerSeen)
            {
                reason = B1Reason.BadFormat;
                return false;
            }

            string v;
            if (kv.TryGetValue("TestId", out v) && TestIdPattern.IsMatch(v)) { testIdIfValid = v; }
            if (kv.TryGetValue("RequestId", out v) && RequestIdPattern.IsMatch(v)) { requestIdIfValid = v; }

            string[] required = new string[] { "TestId", "RequestId", "Operation", "TimeMs", "CreatedAtUtc", "ExecuteOnce" };
            for (int i = 0; i < required.Length; i++)
            {
                if (!kv.ContainsKey(required[i]))
                {
                    reason = B1Reason.MissingKey;
                    return false;
                }
            }

            B1Request r = new B1Request();
            r.TestId = kv["TestId"];
            r.RequestId = kv["RequestId"];
            if (!TestIdPattern.IsMatch(r.TestId) || !RequestIdPattern.IsMatch(r.RequestId))
            {
                reason = B1Reason.BadValue;
                return false;
            }

            r.Operation = kv["Operation"];
            if (r.Operation != B1Op.SetTime && r.Operation != B1Op.InitStation && r.Operation != B1Op.InitLocation)
            {
                reason = B1Reason.BadOperation;
                return false;
            }

            if (kv["ExecuteOnce"] != "true")
            {
                reason = B1Reason.NotExecuteOnce;
                return false;
            }

            r.ExecuteOnce = true;
            if (!ParseInt(kv["TimeMs"], 0, 172800000, out r.TimeMs))
            {
                reason = B1Reason.BadValue;
                return false;
            }

            if (!DateTime.TryParseExact(kv["CreatedAtUtc"], TimeFormat, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out r.CreatedUtc))
            {
                reason = B1Reason.BadValue;
                return false;
            }

            if (kv.TryGetValue("ExpectGeneration", out v) && !ParseInt(v, 1, 1000000, out r.ExpectGeneration))
            {
                reason = B1Reason.BadValue;
                return false;
            }

            bool haveStation = kv.ContainsKey("StationIndex");
            bool haveLocation = kv.ContainsKey("LocationM");
            if (haveStation && !ParseInt(kv["StationIndex"], 0, 9999, out r.StationIndex))
            {
                reason = B1Reason.BadValue;
                return false;
            }

            if (haveLocation)
            {
                double loc;
                if (!double.TryParse(kv["LocationM"], NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out loc)
                    || double.IsNaN(loc) || double.IsInfinity(loc) || loc < -100000.0 || loc > 10000000.0)
                {
                    reason = B1Reason.BadValue;
                    return false;
                }

                r.LocationM = loc;
            }

            bool argsOk;
            if (r.Operation == B1Op.SetTime) { argsOk = !haveStation && !haveLocation; }
            else if (r.Operation == B1Op.InitStation) { argsOk = haveStation && !haveLocation; }
            else { argsOk = haveLocation && !haveStation; }
            if (!argsOk)
            {
                reason = B1Reason.OperationArgs;
                return false;
            }

            request = r;
            reason = null;
            return true;
        }

        private static bool ParseInt(string s, int min, int max, out int value)
        {
            value = 0;
            int v;
            if (string.IsNullOrEmpty(s) || !int.TryParse(s, NumberStyles.None, CultureInfo.InvariantCulture, out v))
            {
                return false;
            }

            if (v < min || v > max)
            {
                return false;
            }

            value = v;
            return true;
        }
    }

    /// <summary>
    /// What the probe could read at one moment. A value that could not be read is null (never a default); FailedReads names what failed.
    /// Counters are the host adapter's own event counters (incremented by event handlers, not read from BVE).
    /// </summary>
    internal sealed class B1Snapshot
    {
        internal bool ScenarioCreated;
        internal int ScenarioObjectId;                       // RuntimeHelpers.GetHashCode of the original Scenario object: an id of the instance, never compared across processes
        internal int? TimeMs;
        internal double? Location;
        internal double? SpeedMps;
        internal bool? DoorsClosed;
        internal int? Power;
        internal int? Brake;
        internal int? Reverser;
        internal int? StationCount;
        internal double? ReqStationLocation;                  // Stations[requested index].Location
        internal bool? ReqStationPass;
        internal int? StationAtIndex;                         // the station whose location is within 0.5 m of the train, -1 = none
        internal int? PrevStationIndex;                       // the last station at or behind the train, -1 = none
        internal int? NextStationIndex;                       // the first station ahead of the train, -1 = none
        internal double? NextStationLocation;
        internal bool? NextStationPass;
        internal double? SignalLimitMps;
        internal double? ForwardSignalLimitMps;
        internal double? GroundLimitMps;
        internal double? NativeLocation;                      // the ATS side view (INative.VehicleState): refreshed by the host at the ATS Elapse, so it may lag one frame
        internal double? NativeSpeedKmh;
        internal int? NativeTimeMs;
        internal double? NativeBcKpa;
        internal double? NativeBpKpa;
        internal int? NativePower;
        internal int? NativeBrake;
        internal int? NativeReverser;
        internal string FailedReads = string.Empty;           // comma separated names
    }

    internal sealed class B1Counters
    {
        internal int ScenarioOpened;
        internal int ScenarioClosed;
        internal int ScenarioCreated;
        internal int NativeStarted;                           // the ATS Initialize call as AtsEX relays it (INative.Started)
        internal int NativeDoorOpened;
        internal int NativeDoorClosed;
        internal int NativeSignalUpdated;
        internal int NativeBeaconPassed;

        internal int LifecycleTotal()
        {
            return ScenarioOpened + ScenarioClosed + ScenarioCreated;
        }

        internal B1Counters Copy()
        {
            return (B1Counters)MemberwiseClone();
        }
    }

    /// <summary>The state of the telemetry session as the probe may see it (a read of the session's own counters and of the tapped datagram; no BVE object).</summary>
    internal sealed class B1SessionView
    {
        internal bool ScenarioActive;
        internal int ScenarioId;
        internal int Discontinuities;
        internal int LinesSent;
        internal int LinesSkipped;
        internal string LastAvail;
        internal string LastLine;                             // the last telemetry line (SCENARIO_ID:...), null when none
        internal long LineSeq;                                // number of telemetry lines the tap has seen
    }

    /// <summary>Everything that touches BVE. Called from B1ProbeEngine.BeginTick / EndTick only, i.e. on the host's Tick thread. Snapshot never throws.</summary>
    internal interface IB1ProbeHost
    {
        bool IsScenarioCreated();
        B1Snapshot Snapshot(int stationIndexOfInterest);
        B1Counters Counters();
        void SetTime(int timeMs);
        void InitializeStation(int stationIndex);
        void InitializeLocation(double location, int timeMs);
    }

    internal interface IB1ProbeIo
    {
        bool RequestExists();
        string ReadRequest();                                  // null = unreadable
        string RequestSignature();                             // changes when the file changes
        bool Retire(string word);                              // renames the request file; false = it could not be renamed
        bool LedgerContains(string requestId);
        bool LedgerAppend(string requestId);                   // true = durably appended
        void WriteLine(string line);
        DateTime UtcNow { get; }
        DateTime NowLocal { get; }
        DateTime ProcessStartUtc { get; }                      // the start of this probe instance (the name is historical): requests created before it are refused
        int ProcessId { get; }
        int ThreadId { get; }
        long MonotonicMs { get; }
        string ProcessMetrics();                               // "thr=.. hnd=.."
    }

    internal sealed class B1Config
    {
        internal int MinTicksInGeneration = 10;
        internal int MaxPendingTicks = 600;
        internal int StabilityTicks = 5;
        internal int MaxExecutions = 8;
        internal double MaxRequestAgeSeconds = 1800.0;
        internal double FutureSkewSeconds = 10.0;
        internal double ProcessStartSkewSeconds = 1.0;
        internal double LocationToleranceM = 0.01;
        internal int DisposeWaitMs = 500;
    }

    internal sealed class B1Status
    {
        internal int Accepted;
        internal int Rejected;
        internal int Executed;
        internal int Duplicates;
        internal int ReentrantTicks;
        internal int ApiCallsAfterDispose;
        internal int Exceptions;
        internal int HostCalls;                               // SetTime / Initialize* calls made
    }

    internal sealed class B1ProbeEngine
    {
        internal const string ProbeBuildWord = "B1-PROBE-OBSERVATION-ONLY";

        private enum Phase { Pending, Observing }

        private sealed class Active
        {
            internal B1Request Req;
            internal Phase State;
            internal long AcceptTick;
            internal int AcceptGeneration;
            internal int PendingTicks;
            internal bool PendingLogged;
            internal long ExecTick;
            internal B1Snapshot Before;
            internal B1Snapshot Immediate;
            internal B1Counters CountersBefore;
            internal B1SessionView ViewBefore;
            internal bool CallFailed;
            internal bool Partial;
            internal double CallMs;
            internal bool TimeOk;
            internal bool LocOk;
            internal double ExpectLoc = double.NaN;
            internal List<B1Snapshot> Samples = new List<B1Snapshot>();
            internal List<long> SampleTicks = new List<long>();
        }

        // CALCG is not read from the API: the telemetry session computes it from two consecutive samples, so it leaves it out of the Tick in which it detects a discontinuity
        // (it is back with the next line). That one token is therefore an EXPECTED loss in a Tick that carried a discontinuity; any other loss is not.
        private const string ExpectedLossToken = "calcg";

        private readonly IB1ProbeHost host;
        private readonly IB1ProbeIo io;
        private readonly Func<B1SessionView> sessionView;
        private readonly B1Config cfg;
        private readonly object execGate = new object();
        private readonly HashSet<string> consumed = new HashSet<string>(StringComparer.Ordinal);
        private readonly B1Status status = new B1Status();

        private volatile bool disposing;
        private bool inCall;
        private int callThreadId;
        private Active active;
        private long tickSeq;
        private long prevTickMono = -1;
        private double gapMs;
        private int generation;
        private int lastScenarioId = -1;
        private int ticksInGeneration;
        private B1Counters endTickCounters;
        private string ignoredSignature;
        private int tickThreadId = -1;
        private bool tickThreadLogged;
        private bool disposeAfterTickLogged;

        internal B1ProbeEngine(IB1ProbeHost host, IB1ProbeIo io, Func<B1SessionView> sessionView, B1Config config)
        {
            this.host = host;
            this.io = io;
            this.sessionView = sessionView;
            this.cfg = config ?? new B1Config();
            this.endTickCounters = new B1Counters();
        }

        internal B1Status Status { get { return status; } }

        internal int Generation { get { return generation; } }

        internal bool HasPending { get { return active != null && active.State == Phase.Pending; } }

        internal bool IsObserving { get { return active != null && active.State == Phase.Observing; } }

        internal bool IsDisposing { get { return disposing; } }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // logging: every line carries test, req, host, generation, scenario id and Tick sequence; free text never comes from a request
        // ---------------------------------------------------------------------------------------------------------------------------------
        internal static string Clean(string s)
        {
            if (string.IsNullOrEmpty(s))
            {
                return "-";
            }

            string t = Regex.Replace(s, "[A-Za-z]:\\\\[^\\s]*", "<path>");
            t = Regex.Replace(t, "\\\\\\\\[^\\s]+", "<path>");
            t = Regex.Replace(t, "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "<mail>");
            t = Regex.Replace(t, "[^\\x21-\\x7E]", "_");
            if (t.Length > 120)
            {
                t = t.Substring(0, 120);
            }

            return t.Length == 0 ? "-" : t;
        }

        private static string N(double? v)
        {
            return v.HasValue ? v.Value.ToString("0.###", CultureInfo.InvariantCulture) : "na";
        }

        private static string N(int? v)
        {
            return v.HasValue ? v.Value.ToString(CultureInfo.InvariantCulture) : "na";
        }

        private static string N(bool? v)
        {
            return v.HasValue ? (v.Value ? "1" : "0") : "na";
        }

        private static string YN(bool b)
        {
            return b ? "yes" : "no";
        }

        private static string KmhOf(double? mps)
        {
            return mps.HasValue ? (mps.Value * 3.6).ToString("0.###", CultureInfo.InvariantCulture) : "na";
        }

        private void Emit(string ev, string testId, string requestId, string kv)
        {
            try
            {
                B1SessionView v = null;
                try { v = sessionView != null ? sessionView() : null; } catch { }
                StringBuilder sb = new StringBuilder(256);
                sb.Append(io.NowLocal.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture));
                sb.Append(" P=").Append(io.ProcessId);
                sb.Append(" T=").Append(io.ThreadId);
                sb.Append(' ').Append(ev);
                sb.Append(" test=").Append(testId ?? "-");
                sb.Append(" req=").Append(requestId ?? "-");
                sb.Append(" host=AtsExLegacy");
                sb.Append(" gen=").Append(generation);
                sb.Append(" scn=").Append(v != null ? v.ScenarioId.ToString(CultureInfo.InvariantCulture) : "na");
                sb.Append(" tick=").Append(tickSeq);
                if (!string.IsNullOrEmpty(kv))
                {
                    sb.Append(' ').Append(kv);
                }

                io.WriteLine(sb.ToString());
            }
            catch
            {
                // a log can never affect BVE
            }
        }

        /// <summary>A line about the active request: it carries the request fields (op, station, reqLoc, reqTimeMs) itself. A line about nothing in particular has test=- req=-.</summary>
        private void Emit(string ev, Active a, string kv)
        {
            Emit(ev, a != null ? a.Req.TestId : null, a != null ? a.Req.RequestId : null, (a != null ? RequestText(a.Req) + " " : string.Empty) + kv);
        }

        private static string RequestText(B1Request r)
        {
            return "op=" + r.Operation + " station=" + (r.StationIndex >= 0 ? r.StationIndex.ToString(CultureInfo.InvariantCulture) : "na")
                + " reqLoc=" + (double.IsNaN(r.LocationM) ? "na" : r.LocationM.ToString("0.###", CultureInfo.InvariantCulture))
                + " reqTimeMs=" + r.TimeMs.ToString(CultureInfo.InvariantCulture);
        }

        private static string SnapText(string prefix, B1Snapshot s)
        {
            if (s == null)
            {
                return prefix + "snapshot=none";
            }

            StringBuilder sb = new StringBuilder(384);
            sb.Append(prefix).Append("TimeMs=").Append(N(s.TimeMs));
            sb.Append(' ').Append(prefix).Append("Loc=").Append(N(s.Location));
            sb.Append(' ').Append(prefix).Append("SpdKmh=").Append(KmhOf(s.SpeedMps));
            sb.Append(' ').Append(prefix).Append("DoorsClosed=").Append(N(s.DoorsClosed));
            sb.Append(' ').Append(prefix).Append("Handle=").Append(N(s.Power)).Append('/').Append(N(s.Brake)).Append('/').Append(N(s.Reverser));
            sb.Append(' ').Append(prefix).Append("Stations=").Append(N(s.StationCount));
            sb.Append(' ').Append(prefix).Append("StAt=").Append(N(s.StationAtIndex));
            sb.Append(' ').Append(prefix).Append("StPrev=").Append(N(s.PrevStationIndex));
            sb.Append(' ').Append(prefix).Append("StNext=").Append(N(s.NextStationIndex)).Append('@').Append(N(s.NextStationLocation)).Append("/pass=").Append(N(s.NextStationPass));
            sb.Append(' ').Append(prefix).Append("SigKmh=").Append(KmhOf(s.SignalLimitMps));
            sb.Append(' ').Append(prefix).Append("FwdSigKmh=").Append(KmhOf(s.ForwardSignalLimitMps));
            sb.Append(' ').Append(prefix).Append("GndKmh=").Append(KmhOf(s.GroundLimitMps));
            sb.Append(' ').Append(prefix).Append("Ats=t").Append(N(s.NativeTimeMs)).Append("/loc").Append(N(s.NativeLocation)).Append("/kmh").Append(N(s.NativeSpeedKmh))
                .Append("/bc").Append(N(s.NativeBcKpa)).Append("/bp").Append(N(s.NativeBpKpa)).Append("/h").Append(N(s.NativePower)).Append('.').Append(N(s.NativeBrake)).Append('.').Append(N(s.NativeReverser));
            sb.Append(' ').Append(prefix).Append("ScnObj=").Append(s.ScenarioObjectId.ToString(CultureInfo.InvariantCulture));
            sb.Append(' ').Append(prefix).Append("BadReads=").Append(string.IsNullOrEmpty(s.FailedReads) ? "-" : s.FailedReads);
            return sb.ToString();
        }

        private static string CounterText(string prefix, B1Counters c)
        {
            return prefix + "Evt=open" + c.ScenarioOpened + "/close" + c.ScenarioClosed + "/create" + c.ScenarioCreated
                + " " + prefix + "AtsEvt=start" + c.NativeStarted + "/dopen" + c.NativeDoorOpened + "/dclose" + c.NativeDoorClosed + "/sig" + c.NativeSignalUpdated + "/beacon" + c.NativeBeaconPassed;
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // host calls: the only places the engine uses the host; none after Dispose began
        // ---------------------------------------------------------------------------------------------------------------------------------
        private B1Snapshot SafeSnapshot(int stationIndex)
        {
            if (disposing)
            {
                status.ApiCallsAfterDispose++;
                return null;
            }

            try
            {
                return host.Snapshot(stationIndex);
            }
            catch (Exception ex)
            {
                status.Exceptions++;
                Emit("PROBE_EXCEPTION", active, "where=snapshot type=" + Clean(ex.GetType().Name) + " msg=" + Clean(ex.Message));
                return null;
            }
        }

        private B1Counters SafeCounters()
        {
            try
            {
                B1Counters c = host.Counters();
                return c != null ? c.Copy() : new B1Counters();
            }
            catch
            {
                return new B1Counters();
            }
        }

        private B1SessionView SafeView()
        {
            try
            {
                B1SessionView v = sessionView != null ? sessionView() : null;
                return v ?? new B1SessionView();
            }
            catch
            {
                return new B1SessionView();
            }
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // the Tick (host Tick thread)
        // ---------------------------------------------------------------------------------------------------------------------------------
        internal void BeginTick(double elapsedMs)
        {
            bool taken = false;
            try
            {
                if (disposing)
                {
                    if (!disposeAfterTickLogged)
                    {
                        disposeAfterTickLogged = true;
                        Emit("PROBE_DISPOSE_REJECTED", active, "reason=" + B1Reason.DisposeStarted + " where=tick");
                    }

                    return;
                }

                if (inCall)
                {
                    status.ReentrantTicks++;
                    Emit("PROBE_REENTRANT_TICK", active, "where=begin inCallThread=" + callThreadId + " nowThread=" + io.ThreadId);
                    return;
                }

                Monitor.Enter(execGate);
                taken = true;
                if (disposing)
                {
                    return;
                }

                tickSeq++;
                long mono = io.MonotonicMs;
                gapMs = prevTickMono < 0 ? 0.0 : (double)(mono - prevTickMono);
                prevTickMono = mono;
                int tid = io.ThreadId;
                if (tickThreadId != tid)
                {
                    Emit("PROBE_TICK_THREAD", active, "tickThread=" + tid + " previous=" + (tickThreadId < 0 ? "none" : tickThreadId.ToString(CultureInfo.InvariantCulture)) + " first=" + YN(!tickThreadLogged));
                    tickThreadLogged = true;
                    tickThreadId = tid;
                }

                if (active == null && io.RequestExists())
                {
                    HandleRequestFile();
                }

                if (active != null && active.State == Phase.Pending)
                {
                    TryExecute();
                }
            }
            catch (Exception ex)
            {
                status.Exceptions++;
                Emit("PROBE_EXCEPTION", active, "where=begin-tick type=" + Clean(ex.GetType().Name) + " msg=" + Clean(ex.Message));
            }
            finally
            {
                if (taken)
                {
                    Monitor.Exit(execGate);
                }
            }
        }

        /// <summary>Called after the telemetry session handled the same Tick (so the session's own reading of the jump is visible).</summary>
        internal void EndTick()
        {
            bool taken = false;
            try
            {
                if (disposing || inCall)
                {
                    return;
                }

                Monitor.Enter(execGate);
                taken = true;
                if (disposing)
                {
                    return;
                }

                B1SessionView v = SafeView();
                if (v.ScenarioActive)
                {
                    if (v.ScenarioId != lastScenarioId)
                    {
                        generation++;
                        lastScenarioId = v.ScenarioId;
                        ticksInGeneration = 0;
                        Emit("PROBE_GENERATION", active, "scenarioId=" + v.ScenarioId + " generation=" + generation);
                    }

                    ticksInGeneration++;
                }
                else
                {
                    ticksInGeneration = 0;
                }

                endTickCounters = SafeCounters();
                if (active != null && active.State == Phase.Observing)
                {
                    Observe(v);
                }
            }
            catch (Exception ex)
            {
                status.Exceptions++;
                Emit("PROBE_EXCEPTION", active, "where=end-tick type=" + Clean(ex.GetType().Name) + " msg=" + Clean(ex.Message));
            }
            finally
            {
                if (taken)
                {
                    Monitor.Exit(execGate);
                }
            }
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // the request file
        // ---------------------------------------------------------------------------------------------------------------------------------
        private void Reject(B1Request parsed, string testId, string requestId, string reason, bool markConsumed)
        {
            status.Rejected++;
            Emit("PROBE_REQUEST_REJECTED", testId, requestId, (parsed != null ? RequestText(parsed) + " " : string.Empty) + "reason=" + reason);
            if (markConsumed && requestId != null)
            {
                consumed.Add(requestId);
                try { io.LedgerAppend(requestId); } catch { }
            }

            RetireFile("rejected");
        }

        private void RetireFile(string word)
        {
            string signature = null;
            try { signature = io.RequestSignature(); } catch { }
            bool ok = false;
            try { ok = io.Retire(word); } catch { ok = false; }
            if (!ok)
            {
                ignoredSignature = signature;
                Emit("PROBE_RETIRE_FAILED", active, "word=" + word);
            }
        }

        private void HandleRequestFile()
        {
            string signature = null;
            try { signature = io.RequestSignature(); } catch { }
            if (signature != null && signature == ignoredSignature)
            {
                return;
            }

            string text = null;
            try { text = io.ReadRequest(); } catch { text = null; }
            B1Request r;
            string reason;
            string testId;
            string requestId;
            if (!B1RequestParser.TryParse(text, out r, out reason, out testId, out requestId))
            {
                Reject(null, testId, requestId, reason, false);
                return;
            }

            if (consumed.Contains(r.RequestId) || SafeLedgerContains(r.RequestId))
            {
                status.Duplicates++;
                Emit("PROBE_DUPLICATE_IGNORED", r.TestId, r.RequestId, RequestText(r) + " reason=already-consumed");
                RetireFile("duplicate");
                return;
            }

            if (status.Executed >= cfg.MaxExecutions)
            {
                Reject(r, r.TestId, r.RequestId, B1Reason.ExecutionCap, true);
                return;
            }

            DateTime now = io.UtcNow;
            double ageSec = (now - r.CreatedUtc).TotalSeconds;
            if (ageSec < -cfg.FutureSkewSeconds)
            {
                Reject(r, r.TestId, r.RequestId, B1Reason.CreatedInFuture, true);
                return;
            }

            if (r.CreatedUtc < io.ProcessStartUtc.AddSeconds(-cfg.ProcessStartSkewSeconds))
            {
                Reject(r, r.TestId, r.RequestId, B1Reason.CreatedBeforeProcess, true);
                return;
            }

            if (ageSec > cfg.MaxRequestAgeSeconds)
            {
                Reject(r, r.TestId, r.RequestId, B1Reason.TooOld, true);
                return;
            }

            if (r.ExpectGeneration >= 0 && r.ExpectGeneration != generation)
            {
                Reject(r, r.TestId, r.RequestId, B1Reason.GenerationMismatch, true);
                return;
            }

            Active a = new Active();
            a.Req = r;
            a.State = Phase.Pending;
            a.AcceptTick = tickSeq;
            a.AcceptGeneration = generation;
            active = a;
            status.Accepted++;
            Emit("PROBE_REQUEST_ACCEPTED", a, "createdAgeMs=" + ((long)(ageSec * 1000.0)).ToString(CultureInfo.InvariantCulture)
                + " gapSincePrevTickMs=" + gapMs.ToString("0", CultureInfo.InvariantCulture) + " ticksInGeneration=" + ticksInGeneration + " generationAtAccept=" + generation
                + " executions=" + status.Executed);
        }

        private bool SafeLedgerContains(string id)
        {
            try { return io.LedgerContains(id); } catch { return false; }
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // execution: ONE request, at most once, on the Tick
        // ---------------------------------------------------------------------------------------------------------------------------------
        private bool Guard(Active a, string where)
        {
            if (disposing)
            {
                Emit("PROBE_DISPOSE_REJECTED", a, "reason=" + B1Reason.DisposeStarted + " where=" + where);
                return false;
            }

            return true;
        }

        private void TryExecute()
        {
            Active a = active;
            B1Request r = a.Req;
            if (!Guard(a, "before-execute"))
            {
                return;
            }

            if (a.AcceptGeneration != generation && a.AcceptGeneration != 0)
            {
                FinishRejected(a, B1Reason.GenerationChanged);
                return;
            }

            if (a.AcceptGeneration == 0)
            {
                a.AcceptGeneration = generation;       // a request placed before any scenario existed binds to the first generation it sees
            }

            B1SessionView v = SafeView();
            B1Counters now = SafeCounters();
            bool created = false;
            try { created = host.IsScenarioCreated(); } catch { created = false; }
            bool lifecycleQuiet = now.LifecycleTotal() == endTickCounters.LifecycleTotal();
            bool ready = v.ScenarioActive && created && ticksInGeneration >= cfg.MinTicksInGeneration && lifecycleQuiet;
            if (!ready)
            {
                a.PendingTicks++;
                if (!a.PendingLogged)
                {
                    a.PendingLogged = true;
                    Emit("PROBE_PENDING", a, "scenarioActive=" + YN(v.ScenarioActive) + " created=" + YN(created) + " ticksInGeneration=" + ticksInGeneration
                        + " need=" + cfg.MinTicksInGeneration + " lifecycleQuiet=" + YN(lifecycleQuiet));
                }

                if (a.PendingTicks > cfg.MaxPendingTicks)
                {
                    FinishRejected(a, B1Reason.NotReadyTimeout);
                }

                return;
            }

            B1Snapshot before = SafeSnapshot(r.StationIndex);
            if (before == null || !before.TimeMs.HasValue || !before.Location.HasValue)
            {
                FinishRejected(a, B1Reason.SnapshotUnreadable);
                return;
            }

            if (r.Operation == B1Op.InitStation)
            {
                if (!before.StationCount.HasValue || r.StationIndex >= before.StationCount.Value)
                {
                    FinishRejected(a, B1Reason.StationOutOfRange);
                    return;
                }

                if (!before.ReqStationLocation.HasValue)
                {
                    FinishRejected(a, B1Reason.SnapshotUnreadable);
                    return;
                }
            }

            // write-ahead: the request counts as consumed BEFORE the host is called, so that even a crash can never replay it
            bool ledgerOk = false;
            try { ledgerOk = io.LedgerAppend(r.RequestId); } catch { ledgerOk = false; }
            if (!ledgerOk)
            {
                FinishRejected(a, B1Reason.LedgerFailed);
                return;
            }

            consumed.Add(r.RequestId);
            status.Executed++;
            a.Before = before;
            a.CountersBefore = now;
            a.ViewBefore = v;
            a.ExecTick = tickSeq;
            a.ExpectLoc = r.Operation == B1Op.InitStation ? before.ReqStationLocation.Value : (r.Operation == B1Op.InitLocation ? r.LocationM : before.Location.Value);
            Emit("PROBE_EXECUTE_BEGIN", a, "tickThread=" + io.ThreadId + " executionNo=" + status.Executed + " scenarioActive=yes createdFlag=yes ticksInGeneration=" + ticksInGeneration
                + " atsElapseBefore=yes(extension-tick-after-ats-elapse) " + io.ProcessMetrics());
            Emit("PROBE_BEFORE", a, SnapText("b", before) + " " + CounterText("b", now) + " sessionDiscontinuities=" + v.Discontinuities + " sessionLines=" + v.LinesSent + " sessionSkipped=" + v.LinesSkipped);

            Stopwatch total = Stopwatch.StartNew();
            inCall = true;
            callThreadId = io.ThreadId;
            try
            {
                if (r.Operation == B1Op.InitStation)
                {
                    if (!RunCall(a, "initialize", "PROBE_INITIALIZE", delegate { host.InitializeStation(r.StationIndex); }))
                    {
                        return;
                    }
                }
                else if (r.Operation == B1Op.InitLocation)
                {
                    if (!RunCall(a, "initialize", "PROBE_INITIALIZE", delegate { host.InitializeLocation(r.LocationM, r.TimeMs); }))
                    {
                        return;
                    }
                }

                RunCall(a, "set-time", "PROBE_SET_TIME", delegate { host.SetTime(r.TimeMs); });
            }
            finally
            {
                inCall = false;
                total.Stop();
                a.CallMs = total.Elapsed.TotalMilliseconds;
                FinishCalls(a);
            }
        }

        private bool RunCall(Active a, string step, string eventPrefix, Action call)
        {
            if (!Guard(a, "before-" + step))
            {
                a.Partial = true;
                return false;
            }

            status.HostCalls++;
            Emit(eventPrefix + "_BEGIN", a, "step=" + step + " callThread=" + io.ThreadId);
            Stopwatch sw = Stopwatch.StartNew();
            try
            {
                call();
            }
            catch (Exception ex)
            {
                sw.Stop();
                a.CallFailed = true;
                status.Exceptions++;
                Emit("PROBE_EXCEPTION", a, "where=" + step + " type=" + Clean(ex.GetType().Name) + " msg=" + Clean(ex.Message) + " elapsedMs=" + sw.Elapsed.TotalMilliseconds.ToString("0.###", CultureInfo.InvariantCulture));
                Emit(eventPrefix + "_END", a, "step=" + step + " ok=no elapsedMs=" + sw.Elapsed.TotalMilliseconds.ToString("0.###", CultureInfo.InvariantCulture));
                return false;
            }

            sw.Stop();
            Emit(eventPrefix + "_END", a, "step=" + step + " ok=yes elapsedMs=" + sw.Elapsed.TotalMilliseconds.ToString("0.###", CultureInfo.InvariantCulture));
            return true;
        }

        private void FinishRejected(Active a, string reason)
        {
            active = null;
            Reject(a.Req, a.Req.TestId, a.Req.RequestId, reason, true);
        }

        /// <summary>The read back right after the calls (still in BeginTick, before the telemetry session handled the Tick).</summary>
        private void FinishCalls(Active a)
        {
            B1Request r = a.Req;
            a.State = Phase.Observing;
            B1Snapshot after = disposing ? null : SafeSnapshot(r.StationIndex);
            a.Immediate = after;
            if (after == null)
            {
                Emit("PROBE_AFTER_CALL", a, "readback=none partial=" + YN(a.Partial) + " callFailed=" + YN(a.CallFailed) + " callMs=" + a.CallMs.ToString("0.###", CultureInfo.InvariantCulture));
                a.TimeOk = false;
                a.LocOk = false;
            }
            else
            {
                a.TimeOk = after.TimeMs.HasValue && after.TimeMs.Value == r.TimeMs;
                a.LocOk = after.Location.HasValue && Math.Abs(after.Location.Value - a.ExpectLoc) <= cfg.LocationToleranceM;
                B1Counters c = SafeCounters();
                Emit("PROBE_AFTER_CALL", a, SnapText("a", after) + " " + CounterText("a", c)
                    + " expectLoc=" + N(a.ExpectLoc) + " locDelta=" + N(after.Location.HasValue ? (double?)(after.Location.Value - a.ExpectLoc) : null)
                    + " timeOk=" + YN(a.TimeOk) + " locOk=" + YN(a.LocOk) + " tolM=" + cfg.LocationToleranceM.ToString("0.###", CultureInfo.InvariantCulture)
                    + " partial=" + YN(a.Partial) + " callFailed=" + YN(a.CallFailed) + " callMs=" + a.CallMs.ToString("0.###", CultureInfo.InvariantCulture) + " " + io.ProcessMetrics());
            }

            bool retired = false;
            try { retired = io.Retire("consumed-" + r.RequestId); }
            catch { retired = false; }
            if (!retired)
            {
                Emit("PROBE_RETIRE_FAILED", a, "word=consumed");
            }
            if (RequestStillThere())
            {
                // a request file that cannot be renamed must never be read again by this process (the id is consumed anyway)
                try { ignoredSignature = io.RequestSignature(); } catch { }
            }
        }

        private bool RequestStillThere()
        {
            try { return io.RequestExists(); } catch { return false; }
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // observation: the same Tick (after the telemetry session), the next Tick, then a short stability window
        // ---------------------------------------------------------------------------------------------------------------------------------
        private static string ParseLineValue(string line, string key)
        {
            if (line == null)
            {
                return null;
            }

            Match m = Regex.Match(line, "(^|,)" + Regex.Escape(key) + ":([^,]*)");
            return m.Success ? m.Groups[2].Value : null;
        }

        private static string[] AvailTokens(string avail)
        {
            if (string.IsNullOrEmpty(avail))
            {
                return new string[0];
            }

            Match m = Regex.Match(avail, "AVAIL:1:([^,]*)");
            if (!m.Success || m.Groups[1].Value.Length == 0)
            {
                return new string[0];
            }

            return m.Groups[1].Value.Split('+');
        }

        private void Observe(B1SessionView v)
        {
            Active a = active;
            B1Request r = a.Req;
            long k = tickSeq - a.ExecTick;
            if (a.AcceptGeneration != generation)
            {
                Emit("PROBE_OBSERVATION_END", a, "reason=generation-changed afterTicks=" + k);
                active = null;
                return;
            }

            B1Snapshot s = SafeSnapshot(r.StationIndex);
            B1Counters c = SafeCounters();
            if (k == 0)
            {
                bool lineSent = v.LinesSent > a.ViewBefore.LinesSent;
                string lineTime = ParseLineValue(v.LastLine, "TIME");
                string lineLoc = ParseLineValue(v.LastLine, "LOCATION");
                bool lineTimeOk = lineSent && lineTime == r.TimeMs.ToString(CultureInfo.InvariantCulture);
                double ll;
                bool lineLocOk = lineSent && lineLoc != null && double.TryParse(lineLoc, NumberStyles.Float, CultureInfo.InvariantCulture, out ll)
                    && s != null && s.Location.HasValue && Math.Abs(ll - s.Location.Value) <= cfg.LocationToleranceM;
                string[] before = AvailTokens(a.ViewBefore.LastAvail);
                string[] after = AvailTokens(v.LastAvail);
                int discDelta = v.Discontinuities - a.ViewBefore.Discontinuities;
                List<string> lost = new List<string>();
                List<string> lostUnexpected = new List<string>();
                for (int i = 0; i < before.Length; i++)
                {
                    if (Array.IndexOf(after, before[i]) < 0)
                    {
                        lost.Add(before[i]);
                        if (!(discDelta > 0 && before[i] == ExpectedLossToken))
                        {
                            lostUnexpected.Add(before[i]);
                        }
                    }
                }

                bool groupsKept = lineSent && lostUnexpected.Count == 0;
                bool noLifecycle = c.LifecycleTotal() == a.CountersBefore.LifecycleTotal();
                bool noReentry = status.ReentrantTicks == 0;
                bool noException = !a.CallFailed && !a.Partial;
                bool timeChanged = a.Before.TimeMs.HasValue && Math.Abs(r.TimeMs - a.Before.TimeMs.Value) > 300;
                string sameTickLocal = SnapText("s", s);
                Emit("PROBE_AFTER_SAME_TICK", a, sameTickLocal + " " + CounterText("s", c)
                    + " sessionLineSent=" + YN(lineSent) + " sessionLineTime=" + (lineTime ?? "na") + " sessionLineLoc=" + (lineLoc ?? "na")
                    + " sessionDiscontinuitiesDelta=" + discDelta + " sessionSkippedDelta=" + (v.LinesSkipped - a.ViewBefore.LinesSkipped)
                    + " availLost=" + (lost.Count == 0 ? "-" : string.Join("+", lost.ToArray()))
                    + " availLostUnexpected=" + (lostUnexpected.Count == 0 ? "-" : string.Join("+", lostUnexpected.ToArray()))
                    + " lineTimeOk=" + YN(lineTimeOk) + " lineLocOk=" + YN(lineLocOk) + " " + io.ProcessMetrics());

                bool hostTimeOk = s != null && s.TimeMs.HasValue && s.TimeMs.Value == r.TimeMs;
                bool hostLocOk = s != null && s.Location.HasValue && Math.Abs(s.Location.Value - a.ExpectLoc) <= cfg.LocationToleranceM;
                bool speedOk = SpeedExpectationOk(a, s);
                bool candidate = a.TimeOk && a.LocOk && hostTimeOk && hostLocOk && lineSent && lineTimeOk && lineLocOk && groupsKept && noLifecycle && noReentry && noException && speedOk;
                // the B2 completion rule candidate: read back == requested (time exact, location within 0.01 m), the Tick's own telemetry line was sent AFTER the call and shows the same, no group lost, nothing re-entered
                Emit("PROBE_COMPLETION_CANDIDATE", a, "result=" + (candidate ? "MET" : "NOT_MET")
                    + " immediateTimeOk=" + YN(a.TimeOk) + " immediateLocOk=" + YN(a.LocOk) + " tickEndTimeOk=" + YN(hostTimeOk) + " tickEndLocOk=" + YN(hostLocOk)
                    + " lineSentSameTick=" + YN(lineSent) + " lineTimeOk=" + YN(lineTimeOk) + " lineLocOk=" + YN(lineLocOk) + " groupsKept=" + YN(groupsKept)
                    + " noLifecycleEvent=" + YN(noLifecycle) + " noReentry=" + YN(noReentry) + " noException=" + YN(noException) + " speedExpectation=" + SpeedExpectationWord(a) + " speedOk=" + YN(speedOk)
                    + " discontinuitySameTick=" + (discDelta > 0 ? "yes" : "no") + " timeChangeOver300ms=" + YN(timeChanged) + " tolM=" + cfg.LocationToleranceM.ToString("0.###", CultureInfo.InvariantCulture));
                a.Samples.Add(s);
                a.SampleTicks.Add(tickSeq);
                return;
            }

            a.Samples.Add(s);
            a.SampleTicks.Add(tickSeq);
            if (k == 1)
            {
                Emit("PROBE_AFTER_NEXT_TICK", a, SnapText("n", s) + " " + CounterText("n", c)
                    + " sessionDiscontinuitiesDelta=" + (v.Discontinuities - a.ViewBefore.Discontinuities) + " sessionLines=" + v.LinesSent + " sessionSkippedDelta=" + (v.LinesSkipped - a.ViewBefore.LinesSkipped)
                    + " lastLineTime=" + (ParseLineValue(v.LastLine, "TIME") ?? "na") + " lastAvailKept=" + YN(AvailTokens(v.LastAvail).Length >= AvailTokens(a.ViewBefore.LastAvail).Length));
            }
            else
            {
                Emit("PROBE_STABILITY", a, "k=" + k + " " + SnapText("t", s) + " " + CounterText("t", c));
            }

            if (k >= cfg.StabilityTicks)
            {
                Summarize(a, v, c);
                active = null;
            }
        }

        private static string SpeedExpectationWord(Active a)
        {
            B1Request r = a.Req;
            if (r.Operation == B1Op.SetTime)
            {
                return "unchanged";
            }

            if (r.Operation == B1Op.InitStation && a.Before.ReqStationPass.HasValue && !a.Before.ReqStationPass.Value)
            {
                return "zero";
            }

            return "na";
        }

        private static bool SpeedExpectationOk(Active a, B1Snapshot now)
        {
            string word = SpeedExpectationWord(a);
            if (word == "na")
            {
                return true;
            }

            if (now == null || !now.SpeedMps.HasValue)
            {
                return false;
            }

            if (word == "zero")
            {
                return Math.Abs(now.SpeedMps.Value) <= 0.05;
            }

            return a.Before.SpeedMps.HasValue && Math.Abs(now.SpeedMps.Value - a.Before.SpeedMps.Value) <= 1e-6;
        }

        private void Summarize(Active a, B1SessionView v, B1Counters c)
        {
            B1Request r = a.Req;
            bool timeAdvances = true;
            bool locNotBack = true;
            bool noLifecycle = c.LifecycleTotal() == a.CountersBefore.LifecycleTotal();
            int? prevT = a.Immediate != null ? a.Immediate.TimeMs : null;
            double? prevL = a.Immediate != null ? a.Immediate.Location : null;
            int samples = 0;
            bool nextTickRepeat = false;
            for (int i = 1; i < a.Samples.Count; i++)
            {
                B1Snapshot s = a.Samples[i];
                samples++;
                if (s == null || !s.TimeMs.HasValue || !s.Location.HasValue)
                {
                    timeAdvances = false;
                    locNotBack = false;
                    continue;
                }

                if (prevT.HasValue)
                {
                    if (i == 1)
                    {
                        // the Tick right after the call: BVE hands back the SAME time (and location, speed) as the read-back of the call; that is normal, going backwards is not
                        if (s.TimeMs.Value < prevT.Value) { timeAdvances = false; }
                        else if (s.TimeMs.Value == prevT.Value) { nextTickRepeat = true; }
                    }
                    else if (s.TimeMs.Value <= prevT.Value)
                    {
                        timeAdvances = false;       // from the second Tick after the call on, time must advance strictly
                    }
                }
                if (prevL.HasValue && s.Location.Value < prevL.Value - cfg.LocationToleranceM) { locNotBack = false; }
                prevT = s.TimeMs;
                prevL = s.Location;
            }

            int atsStartedDelta = c.NativeStarted - a.CountersBefore.NativeStarted;
            // every sample belongs to its own Tick: sample i was taken in Tick ExecTick + i (so a repeated value is never a repeated sample)
            bool distinctTicks = a.SampleTicks.Count == a.Samples.Count;
            for (int i = 0; distinctTicks && i < a.SampleTicks.Count; i++)
            {
                if (a.SampleTicks[i] != a.ExecTick + i) { distinctTicks = false; }
            }

            bool stable = timeAdvances && locNotBack && noLifecycle && distinctTicks && !a.CallFailed && !a.Partial && samples >= cfg.StabilityTicks;
            Emit("PROBE_STABILITY_SUMMARY", a, "stable=" + YN(stable) + " samples=" + samples + " timeAdvancing=" + YN(timeAdvances) + " locationNotBackwards=" + YN(locNotBack)
                + " noLifecycleEvent=" + YN(noLifecycle) + " atsStartedDelta=" + atsStartedDelta + " doorOpenedDelta=" + (c.NativeDoorOpened - a.CountersBefore.NativeDoorOpened)
                + " doorClosedDelta=" + (c.NativeDoorClosed - a.CountersBefore.NativeDoorClosed) + " signalUpdatedDelta=" + (c.NativeSignalUpdated - a.CountersBefore.NativeSignalUpdated)
                + " beaconDelta=" + (c.NativeBeaconPassed - a.CountersBefore.NativeBeaconPassed) + " reentrantTicks=" + status.ReentrantTicks
                + " sessionDiscontinuitiesDelta=" + (v.Discontinuities - a.ViewBefore.Discontinuities) + " sessionSkippedDelta=" + (v.LinesSkipped - a.ViewBefore.LinesSkipped)
                + " nextTickRepeat=" + YN(nextTickRepeat) + " distinctTicks=" + YN(distinctTicks)
                + " callMs=" + a.CallMs.ToString("0.###", CultureInfo.InvariantCulture) + " " + io.ProcessMetrics());
            Emit("PROBE_OBSERVATION_END", a, "reason=complete afterTicks=" + cfg.StabilityTicks + " executions=" + status.Executed);
        }

        // ---------------------------------------------------------------------------------------------------------------------------------
        // Dispose (any thread)
        // ---------------------------------------------------------------------------------------------------------------------------------
        internal void OnDispose()
        {
            if (disposing)
            {
                return;
            }

            disposing = true;       // FIRST: from here on no host call is started
            Emit("PROBE_DISPOSE_BEGIN", active, "pending=" + YN(active != null && active.State == Phase.Pending) + " observing=" + YN(active != null && active.State == Phase.Observing)
                + " inCall=" + YN(inCall) + " sameThreadAsCall=" + YN(inCall && callThreadId == io.ThreadId) + " disposeThread=" + io.ThreadId);
            bool entered = false;
            try
            {
                entered = Monitor.TryEnter(execGate, cfg.DisposeWaitMs);
                Active a = active;
                if (a != null && a.State == Phase.Pending)
                {
                    Emit("PROBE_DISPOSE_REJECTED", a, "reason=" + B1Reason.PendingDropped + " where=dispose (the request file is left as it is; it is stale for the next process)");
                }
                else if (a != null)
                {
                    Emit("PROBE_DISPOSE_REJECTED", a, "reason=observation-dropped where=dispose");
                }
            }
            finally
            {
                if (entered)
                {
                    Monitor.Exit(execGate);
                }
            }

            Emit("PROBE_DISPOSE_END", active, "gateEntered=" + YN(entered) + " apiCallsAfterDispose=" + status.ApiCallsAfterDispose + " executed=" + status.Executed + " exceptions=" + status.Exceptions
                + " reentrantTicks=" + status.ReentrantTicks);
        }

        /// <summary>One line at start-up so that an installed probe is unmistakable in the log (the probe does nothing else until a request file exists).</summary>
        internal void LogInit(string version, string extra)
        {
            Emit("PROBE_INIT", "-", "-", "build=" + ProbeBuildWord + " ver=" + Clean(version) + " mode=idle-until-request-file " + (extra ?? string.Empty)
                + " maxExecutions=" + cfg.MaxExecutions + " minTicksInGeneration=" + cfg.MinTicksInGeneration + " stabilityTicks=" + cfg.StabilityTicks + " " + io.ProcessMetrics());
        }
    }

    /// <summary>The real file side: Downloads\TSScoring-B1Probe-request.txt (read, then renamed), -consumed.txt (the write-ahead ledger) and TSScoring-B1Probe.log (append only, capped).</summary>
    internal sealed class B1ProbeFileIo : IB1ProbeIo
    {
        internal const string RequestFileName = "TSScoring-B1Probe-request.txt";
        internal const string LedgerFileName = "TSScoring-B1Probe-consumed.txt";
        internal const string LogFileName = "TSScoring-B1Probe.log";
        private const long LogCapBytes = 2L * 1024 * 1024;

        private readonly string dir;
        private readonly object sync = new object();
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private readonly DateTime startUtc;
        private readonly int pid;
        private bool capped;

        internal B1ProbeFileIo(string directoryOverride)
        {
            dir = directoryOverride;
            if (dir == null)
            {
                string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                dir = Path.Combine(profile, "Downloads");
            }

            Process p = null;
            try { p = Process.GetCurrentProcess(); } catch { }
            pid = p != null ? p.Id : 0;
            // the start of THIS probe instance (a new BVE process, or a new Extension instance in the same process): a request created before it is stale and refused
            startUtc = DateTime.UtcNow;
        }

        private string RequestPath { get { return Path.Combine(dir, RequestFileName); } }

        public bool RequestExists()
        {
            return File.Exists(RequestPath);
        }

        public string ReadRequest()
        {
            try
            {
                FileInfo fi = new FileInfo(RequestPath);
                if (!fi.Exists)
                {
                    return null;
                }

                if (fi.Length > B1RequestParser.MaxBytes)
                {
                    return new string('x', B1RequestParser.MaxBytes + 1);
                }

                using (FileStream fs = new FileStream(RequestPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (StreamReader sr = new StreamReader(fs, new UTF8Encoding(false)))
                {
                    return sr.ReadToEnd();
                }
            }
            catch
            {
                return null;
            }
        }

        public string RequestSignature()
        {
            try
            {
                FileInfo fi = new FileInfo(RequestPath);
                return fi.Exists ? fi.Length.ToString(CultureInfo.InvariantCulture) + ":" + fi.LastWriteTimeUtc.Ticks.ToString(CultureInfo.InvariantCulture) : null;
            }
            catch
            {
                return null;
            }
        }

        public bool Retire(string word)
        {
            try
            {
                if (!File.Exists(RequestPath))
                {
                    return true;
                }

                string safe = Regex.Replace(word ?? "retired", "[^A-Za-z0-9-]", "_");
                string target = Path.Combine(dir, "TSScoring-B1Probe-request." + safe + "." + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff", CultureInfo.InvariantCulture) + ".txt");
                File.Move(RequestPath, target);
                return true;
            }
            catch
            {
                return false;
            }
        }

        private string LedgerPath { get { return Path.Combine(dir, LedgerFileName); } }

        public bool LedgerContains(string requestId)
        {
            try
            {
                if (!File.Exists(LedgerPath))
                {
                    return false;
                }

                string[] lines = File.ReadAllLines(LedgerPath);
                for (int i = 0; i < lines.Length; i++)
                {
                    if (string.Equals(lines[i].Trim(), requestId, StringComparison.Ordinal))
                    {
                        return true;
                    }
                }

                return false;
            }
            catch
            {
                return false;
            }
        }

        public bool LedgerAppend(string requestId)
        {
            try
            {
                lock (sync)
                {
                    using (FileStream fs = new FileStream(LedgerPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                    {
                        byte[] b = Encoding.ASCII.GetBytes(requestId + "\r\n");
                        fs.Write(b, 0, b.Length);
                        fs.Flush(true);
                    }
                }

                return true;
            }
            catch
            {
                return false;
            }
        }

        public void WriteLine(string line)
        {
            try
            {
                lock (sync)
                {
                    string path = Path.Combine(dir, LogFileName);
                    if (capped)
                    {
                        return;
                    }

                    if (File.Exists(path) && new FileInfo(path).Length > LogCapBytes)
                    {
                        capped = true;
                        line = DateTime.Now.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + " P=" + pid + " PROBE_LOG_CAP_REACHED";
                    }

                    using (FileStream fs = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                    {
                        byte[] b = new UTF8Encoding(false).GetBytes(line + "\r\n");
                        fs.Write(b, 0, b.Length);
                    }
                }
            }
            catch
            {
                // a diagnostic log never takes BVE down
            }
        }

        public DateTime UtcNow { get { return DateTime.UtcNow; } }

        public DateTime NowLocal { get { return DateTime.Now; } }

        public DateTime ProcessStartUtc { get { return startUtc; } }

        public int ProcessId { get { return pid; } }

        public int ThreadId { get { return Thread.CurrentThread.ManagedThreadId; } }

        public long MonotonicMs { get { return clock.ElapsedMilliseconds; } }

        public string ProcessMetrics()
        {
            try
            {
                Process p = Process.GetCurrentProcess();
                return "procThreads=" + p.Threads.Count + " procHandles=" + p.HandleCount;
            }
            catch
            {
                return "procThreads=na procHandles=na";
            }
        }
    }
}
