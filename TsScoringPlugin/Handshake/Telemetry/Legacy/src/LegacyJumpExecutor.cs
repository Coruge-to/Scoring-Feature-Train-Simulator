using System;
using System.Globalization;
using System.Threading;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4 / LEGACY JUMP LJX-1 - the minimal execution slice: the executor, the Tick runner and the small types around them.
//
// What it does (only when the execution is enabled, see LegacyJumpBuild and the flag of the plane): on the host Tick the runner claims at most ONE accepted command from
// the plane (TryClaimForTick, the one claim entry), the executor runs the host sequence of that command through the host seam (station jump: Initialize(index) then
// SetTime(time); location jump: InitializeTimeAndLocation(location, time) then SetTime(time)), the session writes its row, and only then the completion is handed to the
// sender. Order inside one Tick: [runner.TickPre: claim, host calls, read back] [session.OnTick] [runner.TickPost: completion].
//
// Host independent, BCL only: NO host type, no Legacy API name in this file. The seam ILegacyJumpHost is implemented by exactly one type (AtsExLegacyJumpHost in
// LegacyTelemetryExtension.cs), which is the only place that names the host jump API. The executor never creates a thread, a timer or a task, never aborts a call and
// never waits: a host call that does not return holds the host Tick, and the plane does not hold its gate while the call runs, so the worker and Dispose are not stopped.
// Written in C# 5 syntax on purpose (the offline tests compile the product files directly).
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>
    /// The build flag of the execution slice (OD-X16 option A). The default build does not have the symbol: the execution is OFF and the plane behaves exactly like the
    /// 2A-alpha plane. The acceptance build is made with /p:LegacyJumpExec=true (the project then defines LEGACY_JUMP_EXEC). Nothing else switches it on.
    /// </summary>
    internal static class LegacyJumpBuild
    {
#if LEGACY_JUMP_EXEC
        internal const bool ExecutionCompiledIn = true;
#else
        internal const bool ExecutionCompiledIn = false;
#endif
    }

    /// <summary>The pieces the execution is made of. The jump contract (Directory capabilities 0x7 and AVAIL jump) is published only when ALL of them exist.</summary>
    internal static class LegacyJumpFeatures
    {
        internal const int Sta = 1;           // station jump (JUMP_STA_TIME)
        internal const int Loc = 2;           // location jump (JUMP_LOC_TIME)
        internal const int Complete = 4;      // the completion (JUMP_COMPLETE with the RequestId and the counter)
        internal const int All = Sta | Loc | Complete;
    }

    /// <summary>What the sender says about one completion: Held = nothing was consumed (try again), Sent = a datagram left, Excluded = consumed without a datagram.</summary>
    internal static class LegacyJumpSend
    {
        internal const int Held = 0;
        internal const int Sent = 1;
        internal const int Excluded = 2;
    }

    /// <summary>The result of one attempt to complete a command in the post session part of the Tick.</summary>
    internal static class LegacyJumpCompletion
    {
        internal const int None = 0;
        internal const int Done = 1;
        internal const int Pending = 2;
        internal const int Abandoned = 3;
    }

    internal static class LegacyJumpKind
    {
        internal const int Unknown = 0;
        internal const int Station = 1;
        internal const int Location = 2;
    }

    /// <summary>What the host seam reads back after a jump: the clock of the scenario (ms), the location (m) and how many stations the route has.</summary>
    internal sealed class LegacyJumpReadBack
    {
        internal int TimeMs;
        internal double Location;
        internal int StationCount;
    }

    /// <summary>
    /// The host seam of the executor. Implemented by AtsExLegacyJumpHost (the one type that names the host jump API) and by the fakes of the tests. Every method is called
    /// on the host Tick thread only. ReadBack returns null and StationLocation returns NaN when the value cannot be read; the three Move / Set methods throw when the host
    /// call fails.
    /// </summary>
    internal interface ILegacyJumpHost
    {
        bool IsScenarioCreated();
        LegacyJumpReadBack ReadBack();
        double StationLocation(int index);
        void MoveToStation(int index);
        void MoveToLocation(double location, int timeMs);
        void SetClockMs(int timeMs);
    }

    /// <summary>Where the runner hands a completion: the real implementation is the Legacy data plane sink.</summary>
    internal interface ILegacyJumpCompleteSender
    {
        int SendJumpComplete(byte[] payload, byte[] requestId);
    }

    /// <summary>What the runner needs from the telemetry session: the official jump note, the number of rows sent, the counter of the last row, whether an instance is active.</summary>
    internal interface ILegacyJumpSessionPort
    {
        void NoteOfficialJump();
        int LinesSent { get; }
        int LastLineJumpCount { get; }
        bool ScenarioActive { get; }
    }

    /// <summary>Whether the telemetry row may announce the jump group (AVAIL jump and the JUMP key). Implemented by the plane.</summary>
    internal interface ILegacyJumpAvailability
    {
        bool JumpOpen { get; }
    }

    /// <summary>The facts the Tick thread reads and hands to the plane: the scenario is created, the telemetry session has an active instance.</summary>
    internal sealed class LegacyJumpClaimFacts
    {
        internal bool ScenarioCreated;
        internal bool SessionActive;
    }

    /// <summary>One claimed command, as the Tick executes it. The values are parsed from the receipt text once, at the claim.</summary>
    internal sealed class LegacyJumpClaim
    {
        internal long Sequence;
        internal byte[] RequestId;
        internal int Kind;
        internal int StaIndex = -1;
        internal double Location;
        internal int TimeMs;
        internal long AgeAtClaimMs;
        internal byte[] Payload;                    // the completion text, built once after the row of the execution Tick was sent
        internal int ReadBackTimeMs;
        internal double ReadBackLocation;
        internal LegacyJumpReceipt Receipt;         // the live receipt of the plane (only the plane changes its state)
        internal bool PendingNoted;

        /// <summary>Parses the receipt; a receipt that does not read as one of the two commands gets Kind Unknown (the executor then refuses it before any host call).</summary>
        internal static LegacyJumpClaim From(LegacyJumpReceipt r)
        {
            LegacyJumpClaim t = new LegacyJumpClaim();
            t.Receipt = r;
            t.Sequence = r.Sequence;
            t.RequestId = r.RequestId == null ? null : (byte[])r.RequestId.Clone();
            t.AgeAtClaimMs = r.AgeAtClaimMs;
            string[] parts = r.Text == null ? new string[0] : r.Text.Split(':');
            int time;
            if (parts.Length != 3 || !Int32.TryParse(parts[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out time)) return t;
            t.TimeMs = time;
            if (r.MessageType == DataPlaneMessageTypes.JumpStationTime && parts[0] == "JUMP_STA_TIME")
            {
                int index;
                if (Int32.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out index))
                {
                    t.StaIndex = index;
                    t.Kind = LegacyJumpKind.Station;
                }
            }
            else if (r.MessageType == DataPlaneMessageTypes.JumpLocationTime && parts[0] == "JUMP_LOC_TIME")
            {
                double loc;
                if (Double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out loc))
                {
                    t.Location = loc;
                    t.Kind = LegacyJumpKind.Location;
                }
            }
            return t;
        }
    }

    internal sealed class LegacyJumpExecResult
    {
        internal bool Ok;
        internal string Step = "check";
        internal string Reason;
        internal long ElapsedMs;
        internal int ReadBackTimeMs;
        internal double ReadBackLocation;
    }

    /// <summary>
    /// Runs the host sequence of one claimed command. The arguments are checked BEFORE the first host call; the result is checked AFTER the last one. The read back must show
    /// exactly the requested time and a location within 0.01 m of the target (the managed application accepts a completion at the same tolerance). A failed sequence is
    /// never repeated and never repaired.
    /// </summary>
    internal sealed class LegacyJumpExecutor
    {
        internal const int MaxTimeMs = 172800000;           // 48 hours: the range that the host jump was verified for
        internal const double LocationToleranceM = 0.01;

        private readonly ILegacyJumpHost host;
        private readonly Func<long> clock;
        private int inCall;

        internal LegacyJumpExecutor(ILegacyJumpHost host, Func<long> clockMs)
        {
            if (host == null) throw new ArgumentNullException("host");
            if (clockMs == null) throw new ArgumentNullException("clockMs");
            this.host = host;
            this.clock = clockMs;
        }

        /// <summary>The features this executor really implements. The plane publishes the jump contract only when this is All.</summary>
        internal static int ImplementedFeatures { get { return LegacyJumpFeatures.All; } }

        private long Now()
        {
            try { return clock(); }
            catch { return 0L; }
        }

        private static LegacyJumpExecResult Fail(LegacyJumpExecResult r, string reason, string step)
        {
            r.Ok = false;
            r.Reason = reason;
            r.Step = step;
            return r;
        }

        /// <summary>Never throws. lifecycle reads the scenario boundary counter of the plane: a boundary during the call fails the command (the host state is not trusted then).</summary>
        internal LegacyJumpExecResult Execute(LegacyJumpClaim t, Func<int> lifecycle)
        {
            LegacyJumpExecResult r = new LegacyJumpExecResult();
            long start = Now();
            if (Interlocked.CompareExchange(ref inCall, 1, 0) != 0)
            {
                Fail(r, "reentrant", "guard");
                r.ElapsedMs = Now() - start;
                return r;
            }
            try
            {
                Run(t, lifecycle, r);
            }
            catch (Exception)
            {
                Fail(r, "exception", r.Step);
            }
            finally
            {
                Interlocked.Exchange(ref inCall, 0);
            }
            r.ElapsedMs = Now() - start;
            return r;
        }

        private void Run(LegacyJumpClaim t, Func<int> lifecycle, LegacyJumpExecResult r)
        {
            // 1 the arguments, before any host call
            if (t == null || (t.Kind != LegacyJumpKind.Station && t.Kind != LegacyJumpKind.Location)) { Fail(r, "bad-args", "check"); return; }
            if (t.TimeMs < 0 || t.TimeMs > MaxTimeMs) { Fail(r, "bad-args", "check"); return; }
            if (t.Kind == LegacyJumpKind.Station && t.StaIndex < 0) { Fail(r, "bad-args", "check"); return; }
            if (t.Kind == LegacyJumpKind.Location && (Double.IsNaN(t.Location) || Double.IsInfinity(t.Location))) { Fail(r, "bad-args", "check"); return; }

            // 2 the host before the call: it must be readable, and the station must exist
            LegacyJumpReadBack before = null;
            try { before = host.ReadBack(); }
            catch (Exception) { before = null; }
            if (before == null) { Fail(r, "readback-unavailable", "check"); return; }
            double expected = t.Location;
            if (t.Kind == LegacyJumpKind.Station)
            {
                if (t.StaIndex >= before.StationCount) { Fail(r, "station-out-of-range", "check"); return; }
                double stationAt = Double.NaN;
                try { stationAt = host.StationLocation(t.StaIndex); }
                catch (Exception) { stationAt = Double.NaN; }
                if (Double.IsNaN(stationAt) || Double.IsInfinity(stationAt)) { Fail(r, "station-unreadable", "check"); return; }
                expected = stationAt;
            }

            // 3 the host sequence: the first call, then the clock. A failure of the second call is a partial execution.
            int boundary = lifecycle == null ? 0 : lifecycle();
            r.Step = "initialize";
            try
            {
                if (t.Kind == LegacyJumpKind.Station) host.MoveToStation(t.StaIndex);
                else host.MoveToLocation(t.Location, t.TimeMs);
            }
            catch (Exception)
            {
                Fail(r, "api-exception", "initialize");
                return;
            }
            r.Step = "set-time";
            try
            {
                host.SetClockMs(t.TimeMs);
            }
            catch (Exception)
            {
                Fail(r, "partial-execution", "set-time");
                return;
            }

            // 4 the read back: the time exactly, the location within the tolerance, and no scenario boundary in between
            r.Step = "read-back";
            LegacyJumpReadBack after = null;
            try { after = host.ReadBack(); }
            catch (Exception) { after = null; }
            if (after == null) { Fail(r, "readback-unavailable-after", "read-back"); return; }
            r.ReadBackTimeMs = after.TimeMs;
            r.ReadBackLocation = after.Location;
            if (after.TimeMs != t.TimeMs) { Fail(r, "readback-time-mismatch", "read-back"); return; }
            if (Double.IsNaN(after.Location) || Math.Abs(after.Location - expected) >= LocationToleranceM) { Fail(r, "readback-location-mismatch", "read-back"); return; }
            if ((lifecycle == null ? 0 : lifecycle()) != boundary) { Fail(r, "lifecycle-event-during-call", "read-back"); return; }
            r.Ok = true;
            r.Step = "done";
        }
    }

    /// <summary>
    /// The two halves of the Tick around the telemetry session: TickPre claims and executes, TickPost hands the completion over. Everything is guarded: nothing leaves these
    /// methods. It holds at most one command (the one in flight); a command whose completion cannot be consumed is retried on the next Tick until a fact changes.
    /// </summary>
    internal sealed class LegacyJumpTickRunner
    {
        private readonly LegacyJumpControlPlane plane;
        private readonly LegacyJumpExecutor executor;
        private readonly ILegacyJumpHost host;
        private readonly ILegacyJumpSessionPort session;
        private readonly ILegacyJumpCompleteSender sender;
        private LegacyJumpClaim pending;                    // executed, completion not consumed
        private LegacyJumpClaim unreportedClaim;           // executed, but the plane could not take the report yet
        private LegacyJumpExecResult unreportedResult;
        private int linesBefore;
        private bool executedThisRound;

        internal LegacyJumpTickRunner(LegacyJumpControlPlane plane, LegacyJumpExecutor executor, ILegacyJumpHost host, ILegacyJumpSessionPort session, ILegacyJumpCompleteSender sender)
        {
            if (plane == null) throw new ArgumentNullException("plane");
            if (executor == null) throw new ArgumentNullException("executor");
            if (host == null) throw new ArgumentNullException("host");
            if (session == null) throw new ArgumentNullException("session");
            if (sender == null) throw new ArgumentNullException("sender");
            this.plane = plane;
            this.executor = executor;
            this.host = host;
            this.session = session;
            this.sender = sender;
            plane.AttachRunner();
        }

        private LegacyJumpClaimFacts Facts()
        {
            LegacyJumpClaimFacts f = new LegacyJumpClaimFacts();
            try { f.ScenarioCreated = host.IsScenarioCreated(); }
            catch (Exception) { f.ScenarioCreated = false; }
            try { f.SessionActive = session.ScenarioActive; }
            catch (Exception) { f.SessionActive = false; }
            return f;
        }

        /// <summary>Before the session: claim, execute, read back (all on the host Tick thread).</summary>
        internal void TickPre()
        {
            executedThisRound = false;
            try
            {
                if (!plane.ExecutionActive) return;
                DropEnded();
                if (pending != null || unreportedClaim != null) return;       // one command in flight
                LegacyJumpClaim t = plane.TryClaimForTick(Facts());
                if (t == null) return;
                linesBefore = session.LinesSent;
                LegacyJumpExecResult res = executor.Execute(t, plane.EpochProbe);
                t.ReadBackTimeMs = res.ReadBackTimeMs;
                t.ReadBackLocation = res.ReadBackLocation;
                executedThisRound = true;
                if (res.Ok) pending = t;
                if (plane.ReportExecution(t, res) == 0)
                {
                    unreportedClaim = t;
                    unreportedResult = res;
                }
                if (res.Ok) session.NoteOfficialJump();
            }
            catch (Exception)
            {
            }
        }

        /// <summary>After the session: the completion, once the row of the execution Tick was sent.</summary>
        internal void TickPost()
        {
            try
            {
                if (unreportedClaim != null)
                {
                    if (plane.ReportExecution(unreportedClaim, unreportedResult) == 0) return;
                    unreportedClaim = null;
                    unreportedResult = null;
                }
                if (pending == null) return;
                if (!plane.ExecutionActive) return;
                if (executedThisRound)
                {
                    // the row of THIS Tick must have been sent and must have carried the counter that the completion carries
                    int count = session.LastLineJumpCount;
                    if (session.LinesSent <= linesBefore) { plane.AbandonInFlight(pending, "completion-line-missing"); pending = null; return; }
                    if (count < 0) { plane.AbandonInFlight(pending, "completion-jump-not-announced"); pending = null; return; }
                    pending.Payload = BuildPayload(pending, count);
                }
                int result = plane.TryCompleteInPostSession(pending, Facts(), sender);
                if (result != LegacyJumpCompletion.Pending) pending = null;
            }
            catch (Exception)
            {
            }
        }

        private void DropEnded()
        {
            if (pending == null || pending.Receipt == null) return;
            LegacyJumpCommandState s = pending.Receipt.State;
            if (s != LegacyJumpCommandState.Executing && s != LegacyJumpCommandState.CompletionPending) pending = null;
        }

        /// <summary>JUMP_COMPLETE:&lt;STA|LOC&gt;:&lt;index or -1&gt;:&lt;location&gt;:&lt;time&gt;:&lt;jump count&gt; with the invariant culture: the text the managed application has always read.</summary>
        internal static byte[] BuildPayload(LegacyJumpClaim t, int jumpCount)
        {
            string text = "JUMP_COMPLETE:" + (t.Kind == LegacyJumpKind.Station ? "STA" : "LOC")
                + ":" + (t.Kind == LegacyJumpKind.Station ? t.StaIndex.ToString(CultureInfo.InvariantCulture) : "-1")
                + ":" + t.ReadBackLocation.ToString("R", CultureInfo.InvariantCulture)
                + ":" + t.ReadBackTimeMs.ToString(CultureInfo.InvariantCulture)
                + ":" + jumpCount.ToString(CultureInfo.InvariantCulture);
            return System.Text.Encoding.UTF8.GetBytes(text);
        }
    }
}
