using System;
using System.Globalization;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4JA StationIndex ST-3c - the Legacy jump now reads its commands through the shared JumpWire (CurrentJumpEndpoint.cs's gate and LegacyJumpClaim.From), judges a v2 command
// BEFORE the claim (LegacyJumpJudge: scenario, station list identity and count, index range, index and location together; a refusal is a Discarded receipt, never a failure of the
// breaker), executes it with the ADOPTED StationIndex, targets that station after the jump (LegacyStationTimeline.RequestTarget) and answers with the v2 completion. A formal v1
// command keeps the semantics it had (see the notes at the claim, the executor and BuildPayload). Everything here stays host independent and in C# 5 syntax.
//
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
        internal Func<LegacyJumpView> ViewProvider;     // Phase ST-3c: what a v2 command is judged against, read when (and only when) a command is about to be judged; null = nothing to judge against
    }

    /// <summary>
    /// Phase ST-3c: what a v2 jump command is judged against, as the telemetry session holds it NOW: the scenario id of the active instance (-1 = none), the identity of the station list (the
    /// CRC-32 list id and the count) and the station locations in list order. Read on the Tick thread; nothing here reads the host.
    /// </summary>
    internal sealed class LegacyJumpView
    {
        internal int ScenarioId = -1;
        internal bool ListReady;
        internal string ListId;
        internal int ListCount;
        internal double[] Locations;
    }

    /// <summary>
    /// Phase ST-3c: the OPTIONAL scope port of the telemetry session (a session that has it takes part in the v2 transaction; a double that does not behaves as a v1-only session).
    /// NoteOfficialJump(index, location): a v2 jump was executed with that ADOPTED station; the next re-initialisation targets it. JumpView(): the scope now. TakeTargetRefusal(): why the
    /// rebuilt list could not carry the target (reinit-...), once.
    /// </summary>
    internal interface ILegacyJumpScopePort
    {
        void NoteOfficialJump(int adoptedIndex, double adoptedLocation);
        LegacyJumpView JumpView();
        string TakeTargetRefusal();
    }

    /// <summary>One claimed command, as the Tick executes it. The values are read from the receipt text once, at the claim, by the shared JumpWire reader.</summary>
    internal sealed class LegacyJumpClaim
    {
        internal long Sequence;
        internal byte[] RequestId;
        internal int Kind;
        internal int Version = JumpWire.V1;         // 1 = a formal v1 command (executed as before ST-3c); 2 = a v2 command (judged before the claim, executed with the adopted values)
        internal int StaIndex = -1;                 // v1 only: the index the command names
        internal double Location;                   // v1 only: the location the command names
        internal int RequestedIndex = -1;           // v2 only: what the command named (diagnostic; the host is never called with it)
        internal double RequestedLocation;          // v2 only
        internal int AdoptedIndex = -1;             // v2 only: the index that the judgement of the claim accepted
        internal double AdoptedLocation;            // v2 only: the location of that station in the list
        internal int SelectedIndex = -1;            // the index the host call received (-1 = none: a v1 location command); the completion reports this field and nothing else
        internal int TimeMs;
        internal long AgeAtClaimMs;
        internal byte[] Payload;                    // the completion text, built once after the row of the execution Tick was sent
        internal int ReadBackTimeMs;
        internal double ReadBackLocation;
        internal LegacyJumpReceipt Receipt;         // the live receipt of the plane (only the plane changes its state)
        internal bool PendingNoted;
        internal bool TxNoted;                      // the one transaction line of this command has been written

        /// <summary>
        /// Reads the receipt with the shared JumpWire reader (v1: three fields, v2: seven); a receipt that does not read as one of the two commands gets Kind Unknown (the executor then
        /// refuses it before any host call). Reading judges nothing: a v2 claim is only executable after Adopt().
        /// </summary>
        internal static LegacyJumpClaim From(LegacyJumpReceipt r)
        {
            LegacyJumpClaim t = new LegacyJumpClaim();
            t.Receipt = r;
            t.Sequence = r.Sequence;
            t.RequestId = r.RequestId == null ? null : (byte[])r.RequestId.Clone();
            t.AgeAtClaimMs = r.AgeAtClaimMs;
            string why;
            JumpWireRequest w = JumpWire.ParseRequest(r.Text, out why);
            if (w == null) return t;
            t.Version = w.Version;
            t.TimeMs = w.TimeMs;
            bool v2 = w.Version == JumpWire.V2;
            if (r.MessageType == DataPlaneMessageTypes.JumpStationTime && w.Kind == JumpWire.KindSta && w.HasStationIndex)
            {
                t.Kind = LegacyJumpKind.Station;
                if (v2) { t.RequestedIndex = w.StationIndex; t.RequestedLocation = w.Location; }
                else t.StaIndex = w.StationIndex;
            }
            else if (r.MessageType == DataPlaneMessageTypes.JumpLocationTime && w.Kind == JumpWire.KindLoc && w.HasLocation)
            {
                t.Kind = LegacyJumpKind.Location;
                if (v2) { t.RequestedIndex = w.StationIndex; t.RequestedLocation = w.Location; }
                else t.Location = w.Location;
            }
            return t;
        }

        /// <summary>The judgement of the claim accepted a v2 command: the host is called with these values (the station of the list), never with the request's own.</summary>
        internal void Adopt(LegacyJumpDecision d)
        {
            if (d == null || !d.Accepted || d.Version != JumpWire.V2) return;
            AdoptedIndex = d.AdoptedIndex;
            AdoptedLocation = d.AdoptedLocation;
        }
    }

    internal sealed class LegacyJumpExecResult
    {
        internal bool Ok;
        internal bool Moved;                       // Phase LC-4 (C-LJ-2): the first host call returned, i.e. the vehicle was moved, whatever happened afterwards
        internal string Step = "check";
        internal string Reason;
        internal long ElapsedMs;
        internal int ReadBackTimeMs;
        internal double ReadBackLocation;
    }

    /// <summary>
    /// Runs the host sequence of one claimed command. The arguments are checked BEFORE the first host call; the result is checked AFTER the last one. The read back must show
    /// exactly the requested time and, for a v1 command, a location within 0.01 m of the target (the v1 managed application accepts a completion at the same tolerance); for a v2
    /// command (Phase ST-3c) the location must EQUAL the location of the adopted station. A failed sequence is never repeated and never repaired.
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
            bool v2 = t.Version == JumpWire.V2;
            if (v2)
            {
                // Phase ST-3c: a v2 command is executed with the values that the judgement of the claim ADOPTED; a v2 claim that carries none was never judged and is never executed
                if (t.AdoptedIndex < 0 || Double.IsNaN(t.AdoptedLocation) || Double.IsInfinity(t.AdoptedLocation)) { Fail(r, "bad-args", "check"); return; }
            }
            else
            {
                if (t.Kind == LegacyJumpKind.Station && t.StaIndex < 0) { Fail(r, "bad-args", "check"); return; }
                if (t.Kind == LegacyJumpKind.Location && (Double.IsNaN(t.Location) || Double.IsInfinity(t.Location))) { Fail(r, "bad-args", "check"); return; }
            }

            // 2 the host before the call: it must be readable, and the station must exist. v1: the host's own station is the reference (as before ST-3c). v2: the reference is the location
            // of the ADOPTED station in the list, and the host must agree with it BEFORE the vehicle is moved.
            LegacyJumpReadBack before = null;
            try { before = host.ReadBack(); }
            catch (Exception) { before = null; }
            if (before == null) { Fail(r, "readback-unavailable", "check"); return; }
            int selected = v2 ? t.AdoptedIndex : (t.Kind == LegacyJumpKind.Station ? t.StaIndex : -1);
            double expected = v2 ? t.AdoptedLocation : t.Location;
            if (t.Kind == LegacyJumpKind.Station || v2)
            {
                if (selected >= before.StationCount) { Fail(r, "station-out-of-range", "check"); return; }
            }

            if (t.Kind == LegacyJumpKind.Station)
            {
                double stationAt = Double.NaN;
                try { stationAt = host.StationLocation(selected); }
                catch (Exception) { stationAt = Double.NaN; }
                if (Double.IsNaN(stationAt) || Double.IsInfinity(stationAt)) { Fail(r, "station-unreadable", "check"); return; }
                if (v2) { if (stationAt != expected) { Fail(r, "station-location-mismatch", "check"); return; } }
                else expected = stationAt;
            }

            // 3 the host sequence: the first call, then the clock. A failure of the second call is a partial execution. The selected index that the completion reports is set from the very
            // value that the station call receives (t.SelectedIndex): it is not copied from the request and it is not derived from a position.
            int boundary = lifecycle == null ? 0 : lifecycle();
            r.Step = "initialize";
            t.SelectedIndex = selected;
            try
            {
                if (t.Kind == LegacyJumpKind.Station) host.MoveToStation(t.SelectedIndex);
                else host.MoveToLocation(expected, t.TimeMs);
            }
            catch (Exception)
            {
                Fail(r, "api-exception", "initialize");
                return;
            }
            r.Moved = true;
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
            // v2 (Phase ST-3c, owner decision OD-S3-8 option A): the location the vehicle really has must EQUAL the location of the adopted station; there is no tolerance. v1 keeps the 0.01 m it had.
            if (Double.IsNaN(after.Location) || (v2 ? after.Location != expected : Math.Abs(after.Location - expected) >= LocationToleranceM)) { Fail(r, "readback-location-mismatch", "read-back"); return; }
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
        private bool payloadDue;                          // Phase LC-4 (C-LJ-1): the executed command still owes its completion payload; bound to the COMMAND, not to the Tick that executed it

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
            ILegacyJumpScopePort scope = session as ILegacyJumpScopePort;
            if (scope != null) f.ViewProvider = scope.JumpView;
            return f;
        }

        /// <summary>The executed jump reaches the session: a v2 jump hands over the station it ADOPTED (the next re-initialisation targets it), a v1 jump the earlier note (position search).</summary>
        private void NoteJump(LegacyJumpClaim t)
        {
            ILegacyJumpScopePort scope = session as ILegacyJumpScopePort;
            if (t.Version == JumpWire.V2 && scope != null) scope.NoteOfficialJump(t.SelectedIndex, t.AdoptedLocation);
            else session.NoteOfficialJump();
        }

        /// <summary>The completion text of a command whose row was sent: the six field v1 text, or the nine field v2 text with the scope of NOW; null = it can not be written (the command is abandoned).</summary>
        private byte[] CompletionOf(LegacyJumpClaim t, int jumpCount)
        {
            if (t.Version != JumpWire.V2) return BuildPayload(t, jumpCount);
            ILegacyJumpScopePort scope = session as ILegacyJumpScopePort;
            if (scope == null) return null;
            LegacyJumpView view = null;
            try { view = scope.JumpView(); }
            catch (Exception) { view = null; }
            return BuildPayload(t, jumpCount, view);
        }

        /// <summary>One line per command that ended (never per Tick): see LegacyJumpControlPlane.NoteTransaction.</summary>
        private void NoteEnd(LegacyJumpClaim t, string status)
        {
            if (t == null || t.TxNoted) return;
            t.TxNoted = true;
            plane.NoteTransaction(t, status);
        }

        /// <summary>Before the session: claim, execute, read back (all on the host Tick thread).</summary>
        internal void TickPre()
        {
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
                if (res.Ok) { pending = t; payloadDue = true; }
                if (plane.ReportExecution(t, res) == 0)
                {
                    unreportedClaim = t;
                    unreportedResult = res;
                }
                if (res.Ok) NoteJump(t);
                else
                {
                    // C-LJ-2: a host that was moved and then failed is a discontinuity of the station state like any other; the note carries NO station (the target stays unset, nothing is adopted or searched)
                    if (res.Moved) session.NoteOfficialJump();
                    NoteEnd(t, "failed-" + (res.Reason ?? "failed"));
                }
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
                if (payloadDue)
                {
                    payloadDue = false;                               // made once: a busy gate at the reports of the execution Tick only delays it
                    // a row must have been sent since the execution Tick and the last row must carry the counter that the completion carries (with a free gate that is the row of the execution Tick itself)
                    int count = session.LastLineJumpCount;
                    if (session.LinesSent <= linesBefore) { End(pending, "completion-line-missing"); return; }
                    if (count < 0) { End(pending, "completion-jump-not-announced"); return; }
                    // Phase ST-3c: a list (re-read after the jump) that could not carry the adopted station abandons the command; it is never repaired and nothing is announced for it
                    ILegacyJumpScopePort scope = session as ILegacyJumpScopePort;
                    string refusal = pending.Version == JumpWire.V2 && scope != null ? scope.TakeTargetRefusal() : null;
                    if (refusal != null) { End(pending, refusal); return; }
                    pending.Payload = CompletionOf(pending, count);
                    if (pending.Payload == null) { End(pending, "completion-format"); return; }
                }
                int result = plane.TryCompleteInPostSession(pending, Facts(), sender);
                if (result != LegacyJumpCompletion.Pending)
                {
                    NoteEnd(pending, result == LegacyJumpCompletion.Done ? "completed" : "abandoned");
                    pending = null;
                }
            }
            catch (Exception)
            {
            }
        }

        /// <summary>The runner found a fact against announcing the completion: the command ends Abandoned with that reason, one transaction line, nothing is sent.</summary>
        private void End(LegacyJumpClaim t, string reason)
        {
            plane.AbandonInFlight(t, reason);
            NoteEnd(t, "abandoned-" + reason);
            pending = null;
        }

        private void DropEnded()
        {
            if (pending == null || pending.Receipt == null) return;
            LegacyJumpCommandState s = pending.Receipt.State;
            if (s != LegacyJumpCommandState.Executing && s != LegacyJumpCommandState.CompletionPending) pending = null;
        }

        /// <summary>
        /// The v1 completion: JUMP_COMPLETE:&lt;STA|LOC&gt;:&lt;index or -1&gt;:&lt;location&gt;:&lt;time&gt;:&lt;jump count&gt; (six fields, invariant culture): the text a v1 managed application has always read. The index is
        /// the one the host call received (SelectedIndex: -1 for a v1 location command); the location is what the host reported after the jump, written through the shared codec.
        /// </summary>
        internal static byte[] BuildPayload(LegacyJumpClaim t, int jumpCount)
        {
            string text = "JUMP_COMPLETE:" + (t.Kind == LegacyJumpKind.Station ? JumpWire.KindSta : JumpWire.KindLoc)
                + ":" + t.SelectedIndex.ToString(CultureInfo.InvariantCulture)
                + ":" + LocationText(t.ReadBackLocation)
                + ":" + t.ReadBackTimeMs.ToString(CultureInfo.InvariantCulture)
                + ":" + jumpCount.ToString(CultureInfo.InvariantCulture);
            return Encoding.UTF8.GetBytes(text);
        }

        /// <summary>
        /// Phase ST-3c: the v2 completion (nine fields, JumpWire.FormatCompletionV2): the selected index is the one the host call received (SelectedIndex, for a location command too), the
        /// location is what the host reported after the jump, the scope (scenario id, list id, count) is the scope of NOW. Null = something is outside the contract (no scope, an index the
        /// list no longer holds, a location the codec can not write): the command is then abandoned and nothing is announced.
        /// </summary>
        internal static byte[] BuildPayload(LegacyJumpClaim t, int jumpCount, LegacyJumpView view)
        {
            if (view == null) return null;
            string reason;
            JumpWireScope scope = JumpWire.ValidateScope(view.ScenarioId, view.ListId, view.ListCount, out reason);
            if (scope == null) return null;
            string text = JumpWire.FormatCompletionV2(t.Kind == LegacyJumpKind.Station ? JumpWire.KindSta : JumpWire.KindLoc, t.SelectedIndex, t.ReadBackLocation, t.ReadBackTimeMs, jumpCount, scope, out reason);
            return text == null ? null : Encoding.UTF8.GetBytes(text);
        }

        /// <summary>A position as text: the shared codec's form (the shortest that reads back exactly); a value outside its contract keeps a plain invariant 17 digit form (it can not be a station).</summary>
        internal static string LocationText(double value)
        {
            string reason;
            string text = JumpWire.FormatLocation(value, out reason);
            return text == null ? value.ToString("G17", CultureInfo.InvariantCulture) : text;
        }
    }

    // ============================================================================================================================================
    // Phase ST-3c - the judgement of a v2 command, before the claim
    // ============================================================================================================================================

    /// <summary>
    /// What a refusal line may say about the command and the plugin's own list, as text: the index and the count the command NAMED (as received, a short number or "?") and the count of the
    /// list the plugin holds. For the diagnostic line ONLY: nothing reads it to decide, to call the host, to choose a station or to write a completion (the same isolation as Current's G-RC-1).
    /// </summary>
    internal sealed class LegacyJumpDiagnostic
    {
        internal static readonly LegacyJumpDiagnostic Unknown = new LegacyJumpDiagnostic(LegacyJumpJudge.DiagUnknown, LegacyJumpJudge.DiagUnknown, LegacyJumpJudge.DiagUnknown);

        internal readonly string RequestedIndexText;
        internal readonly string RequestedCountText;
        internal readonly string CurrentCountText;

        internal LegacyJumpDiagnostic(string requestedIndexText, string requestedCountText, string currentCountText)
        {
            RequestedIndexText = requestedIndexText;
            RequestedCountText = requestedCountText;
            CurrentCountText = currentCountText;
        }
    }

    /// <summary>The verdict on one command. Accepted: for a v2 command AdoptedIndex / AdoptedLocation are the ADOPTED values (the ones the host is called with). Otherwise Reason (and Detail) say why.</summary>
    internal sealed class LegacyJumpDecision
    {
        internal bool Accepted;
        internal string Reason;                       // null when Accepted
        internal string Detail;                       // "-" or a JumpWire reason word (malformed)
        internal int Version;                         // 0 = the text could not be read; 1; 2
        internal string Kind = "-";                   // STA / LOC, "-" when unknown
        internal int RequestedIndex = -1;             // v2 only
        internal double RequestedLocation;            // v2 only
        internal bool HasRequest;                     // RequestedIndex / RequestedLocation / Scope are set
        internal int AdoptedIndex = -1;               // the adopted index (v2)
        internal double AdoptedLocation;              // the adopted location (v2): the location of the adopted station
        internal int TimeMs;
        internal JumpWireScope Scope;
        internal LegacyJumpDiagnostic Diagnostic = LegacyJumpDiagnostic.Unknown;   // for RefusedLine only; set once by Judge after the verdict, never read by the verdict code
    }

    internal static class LegacyJumpJudge
    {
        // the verdict words (fixed; none contains a value). They are the words of the Current judgement, so that the two senders refuse for the same reason in the same words.
        internal const string RMalformed = "malformed";                         // Detail: the JumpWire reason word
        internal const string RScenarioMismatch = "scenario-mismatch";
        internal const string RListNotReady = "list-not-ready";
        internal const string RListMismatch = "list-mismatch";
        internal const string RCountMismatch = "count-mismatch";
        internal const string RListInconsistent = "list-inconsistent";
        internal const string RIndexRange = "index-out-of-range";
        internal const string RLocationMismatch = "location-mismatch";
        internal const string DiscardPrefix = "contract-";                      // the Discarded reason of a refused command: contract-<word>

        internal const int MaxLineLength = 200;
        internal const string DiagUnknown = "?";
        internal const int MaxDiagValueLength = 11;          // "-2147483648": a value longer than any Int32 text is not printed
        internal const int MaxDiagScanLength = 256;          // a command of the wire is far shorter; a longer text is not scanned at all

        /// <summary>
        /// The verdict on the text of one command (JumpWire v1 or v2 grammar). Never throws. A formal v1 command is accepted as it is (it names no scope, so there is nothing to compare it
        /// with; it is executed as before ST-3c). A v2 command is accepted only when, in this order, the scenario, the list (id and count), the plugin's own list, the index range and the
        /// location of that index all agree with what the plugin holds now: no fallback station, no nearest station, no search, no index derived from a position.
        /// </summary>
        internal static LegacyJumpDecision Judge(string text, uint messageType, LegacyJumpView view)
        {
            LegacyJumpDecision d = new LegacyJumpDecision();
            try
            {
                JudgeCore(text, messageType, view, d);
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

        private static void JudgeCore(string text, uint messageType, LegacyJumpView view, LegacyJumpDecision d)
        {
            string why;
            JumpWireRequest r = JumpWire.ParseRequest(text, out why);
            if (r == null)
            {
                d.Reason = RMalformed;
                d.Detail = why;
                return;
            }

            d.Version = r.Version;
            d.Kind = r.Kind;
            d.TimeMs = r.TimeMs;
            if ((messageType == DataPlaneMessageTypes.JumpStationTime && r.Kind != JumpWire.KindSta) || (messageType == DataPlaneMessageTypes.JumpLocationTime && r.Kind != JumpWire.KindLoc))
            {
                d.Reason = RMalformed;
                d.Detail = JumpWire.RKind;
                return;
            }

            if (r.Version != JumpWire.V2)
            {
                d.Accepted = true;
                return;
            }

            d.HasRequest = true;
            d.Scope = r.Scope;
            d.RequestedIndex = r.StationIndex;
            d.RequestedLocation = r.Location;
            if (view == null || view.ScenarioId != r.Scope.ScenarioId) { d.Reason = RScenarioMismatch; return; }
            if (!view.ListReady) { d.Reason = RListNotReady; return; }
            if (!string.Equals(view.ListId, r.Scope.ListId, StringComparison.Ordinal)) { d.Reason = RListMismatch; return; }
            if (view.ListCount != r.Scope.Count) { d.Reason = RCountMismatch; return; }
            if (view.Locations == null || view.Locations.Length != view.ListCount) { d.Reason = RListInconsistent; return; }
            if (r.StationIndex < 0 || r.StationIndex >= view.Locations.Length) { d.Reason = RIndexRange; return; }
            if (view.Locations[r.StationIndex] != r.Location) { d.Reason = RLocationMismatch; return; }
            d.Accepted = true;
            d.AdoptedIndex = r.StationIndex;
            d.AdoptedLocation = view.Locations[r.StationIndex];
        }

        // -- what a refusal line says about the named index and count -----------------------------------------------------------------------------------------
        // The shared reader returns no value when it refuses, so the line could not say WHICH index or count was named. This extraction reads only the two fields of a seven field command by
        // position, for the line and for nothing else: it is not the reader, it decides nothing, and its result is never passed to the verdict, the host, the adopted index or the completion. It
        // keeps no text: a field is a short number as received, or "?" (no seven fields, an unknown prefix, a field that is not -digits, a value longer than an Int32 text, a text longer than a
        // command can be). It never throws. (A command that the Managed gate refused first never gets here: its receipt carries the reason payload-grammar only.)
        internal static LegacyJumpDiagnostic Describe(string text, LegacyJumpView view)
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
                return new LegacyJumpDiagnostic(indexText, countText, currentText);
            }
            catch
            {
                return LegacyJumpDiagnostic.Unknown;
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

        /// <summary>The field as received when it is an optional '-' followed by digits and no longer than an Int32 text; otherwise "?". No parsing and no judgement of the value. The refusal line prints
        /// every diagnostic value through it, so nothing but a short number or "?" can reach the line.</summary>
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

        // -- the diagnostic lines (one per request; never per Tick; only numbers and fixed words) -----------------------------------------------------------------
        /// <summary>The first four bytes of the RequestId as 8 lower case hex digits: the same form as the "id=" of the queue lines, so that the lines of one request can be put side by side.</summary>
        internal static string IdText(byte[] requestId)
        {
            if (requestId == null) return "-";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 4 && i < requestId.Length; i++) sb.Append(requestId[i].ToString("x2", CultureInfo.InvariantCulture));
            return sb.Length == 0 ? "-" : sb.ToString();
        }

        private static string Cap(string line)
        {
            return line.Length <= MaxLineLength ? line : line.Substring(0, MaxLineLength);
        }

        private static string Word(string text)
        {
            return string.IsNullOrEmpty(text) ? "-" : text;
        }

        private static string PositionText(double value)
        {
            string reason;
            string text = JumpWire.FormatLocation(value, out reason);
            return text == null ? "?" : text;
        }

        /// <summary>The scope verdict of a refusal: "no" when the scenario or the list (id, count, readiness) is not the one the command names, "ok" when the scope held and something later failed.</summary>
        private static string ScopeVerdict(string reason)
        {
            if (reason == RScenarioMismatch || reason == RListNotReady || reason == RListMismatch || reason == RCountMismatch || reason == RListInconsistent) return "no";
            return "ok";
        }

        /// <summary>A command that was refused by the judgement before the claim: no host call, no claim, no completion, nothing counted by the breaker.</summary>
        internal static string RefusedLine(byte[] requestId, LegacyJumpDecision d)
        {
            string scope = "-";
            if (d != null && d.HasRequest) scope = ScopeVerdict(d.Reason);
            LegacyJumpDiagnostic diag = d == null || d.Diagnostic == null ? LegacyJumpDiagnostic.Unknown : d.Diagnostic;     // req_idx / req_count / current_count: as received or "?"
            return Cap("event=legacy-jump-refused id=" + IdText(requestId) + " v=" + (d == null ? 0 : d.Version).ToString(CultureInfo.InvariantCulture) + " kind=" + (d == null ? "-" : Word(d.Kind))
                + " reason=" + Word(d == null ? null : d.Reason) + " detail=" + Word(d == null ? null : d.Detail) + " req_idx=" + DiagNumber(diag.RequestedIndexText)
                + " req_count=" + DiagNumber(diag.RequestedCountText) + " current_count=" + DiagNumber(diag.CurrentCountText) + " scope=" + scope
                + (d != null && d.HasRequest ? " req_loc=" + PositionText(d.RequestedLocation) : ""));
        }

        /// <summary>
        /// The one line of a command that was claimed and ended (never per Tick): the request, the index it asked for and the one the host received, the locations (asked, measured, difference),
        /// the age at the claim, the TTL, the state of the breaker and how it ended. A command that was refused before the claim has RefusedLine instead.
        /// </summary>
        internal static string TransactionLine(LegacyJumpClaim t, string status, long ttlMs, bool breakerOpen)
        {
            bool v2 = t.Version == JumpWire.V2;
            string reqIdx = v2 ? t.RequestedIndex.ToString(CultureInfo.InvariantCulture) : (t.Kind == LegacyJumpKind.Station ? t.StaIndex.ToString(CultureInfo.InvariantCulture) : "-");
            double requestedLocation = v2 ? t.RequestedLocation : t.Location;
            string reqLoc = v2 || t.Kind == LegacyJumpKind.Location ? PositionText(requestedLocation) : "-";
            bool measured = status == "completed" || status.StartsWith("abandoned", StringComparison.Ordinal) || status.IndexOf("readback-location", StringComparison.Ordinal) >= 0;
            string actual = measured ? PositionText(t.ReadBackLocation) : "-";
            string delta = "-";
            if (actual != "-" && actual != "?" && reqLoc != "-" && reqLoc != "?") delta = (t.ReadBackLocation - requestedLocation).ToString("G17", CultureInfo.InvariantCulture);
            return Cap("event=legacy-jump-tx id=" + IdText(t.RequestId) + " v=" + t.Version.ToString(CultureInfo.InvariantCulture) + " kind=" + (t.Kind == LegacyJumpKind.Station ? JumpWire.KindSta : (t.Kind == LegacyJumpKind.Location ? JumpWire.KindLoc : "-"))
                + " req_idx=" + reqIdx + " sel_idx=" + t.SelectedIndex.ToString(CultureInfo.InvariantCulture) + " validation=" + (v2 ? "ok" : "v1") + " claim=ok age=" + t.AgeAtClaimMs.ToString(CultureInfo.InvariantCulture)
                + " ttl=" + ttlMs.ToString(CultureInfo.InvariantCulture) + " breaker=" + (breakerOpen ? "open" : "closed") + " req_loc=" + reqLoc + " act_loc=" + actual + " dlt=" + delta + " status=" + Word(status));
        }
    }
}
