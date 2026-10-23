using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA - the Legacy Jump control plane: the dedicated worker, the single gate, the state machine and the shutdown.
//
// What it does: after the host has confirmed the managed mode, ONE dedicated worker publishes the Legacy Jump Directory of this BVE process (a new dynamic loopback
// port, a new generation, a new token; CreateNew only), reads the datagrams that arrive, judges them with the shared validator, keeps the accepted command in the
// depth-1 queue and discards it when it can no longer be trusted (a newer command, a scenario boundary, the owner gone or changed, the endpoint re-created, Dispose,
// and a time limit only when one is injected). In the default build (the execution flag OFF) it does NOT execute anything: it calls no host API, announces no jump, and
// the Directory carries the REQUEST_ID capability only, so a managed application cannot send a command (it refuses with command-unsupported).
//
// LJX-1 (the execution flag ON, acceptance build only): the host Tick may claim the accepted command (TryClaimForTick, the one claim entry, never blocking), run it through
// the executor (LegacyJumpExecutor.cs) and hand the completion over (TryCompleteInPostSession). The worker never executes anything and never claims. The Directory then
// carries STA | LOC | REQUEST_ID (0x7), and only when every piece of the execution exists (LegacyJumpFeatures.All). The host call itself runs OUTSIDE the gate.
//
// Why a worker of its own: the host Tick stops while BVE is paused or loading, and the Directory must stay serviceable then. The worker never touches a BVE or
// AtsEX object; it uses the clock, the owner source, the port, the writer and the wait that LegacyJumpEnvironment hands it (the production objects, or wrapped by a
// test double). The host calls only OnHostTick, NoteScenarioBoundary and Dispose.
//
// Locking: ONE gate guards every mutable field of the endpoint, the queue and the books. `diag` is a leaf lock for the pending log lines and `flushGate` serialises
// the writing of those lines; the log callback is called only after the gate is released. The worker is the only thread that steps; Dispose and EnsureWorkerAlive
// never run a step. Every wait on the gate that Dispose makes is bounded.
//
// Shutdown order (decision D-5, PID-D0B-1 15.3): stop receiving, expire the queued command, stop request, bounded Join OUTSIDE the gate, WITHDRAWING, close the port,
// CLOSED, release the mapping. All of it happens before the telemetry part of the host extension shuts down. If the gate cannot be taken, the worker finishes the
// same teardown when it leaves.
//
// Host independent, BCL plus the shared DataPlane sources. Written in C# 5 syntax on purpose.
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    internal enum LegacyJumpState
    {
        NotStarted = 0,
        Publishing = 1,
        Ready = 2,
        Withdrawing = 3,
        RetryWaiting = 4,
        Disposing = 5,
        Closed = 6
    }

    /// <summary>The bounds of the plane. They are polling intervals, shutdown limits, a retry interval and capacities. NONE of them is a command lifetime.</summary>
    internal sealed class LegacyJumpTimings
    {
        internal int PollMs = 20;                  // worker polling interval
        internal int JoinMs = 1000;                // bound of the worker Join in Dispose (abnormal case only)
        internal int GateTryMs = 1000;             // bound of every gate acquisition Dispose makes (abnormal case only)
        internal int RetryMinMs = 250;             // Directory creation retry interval: first back-off (decision D-3, provisional)
        internal int RetryMaxMs = 2000;            // Directory creation retry interval: upper bound
        internal int MaxDatagramsPerStep = 32;     // capacity: datagrams read in one step
        internal long TtlMs = 0;                   // 0 = a command never expires by time (decision D-2); a positive value is injected by a test
        // LJX-1: the age limit of a QUEUED command when the execution is on (owner decision of the O-1 acceptance: 5.0 s; the managed application waits 10.0 s). It is an
        // abnormal-case limit of the queue, measured from the time the worker read the datagram. It is not a limit of a host call (those are never interrupted).
        internal const long ExecutionTtlMs = 5000;
    }

    /// <summary>Waits for a handle. The production implementation is a plain WaitHandle.WaitOne; a test wraps it.</summary>
    internal interface ILegacyJumpWait
    {
        bool WaitOne(WaitHandle handle, int milliseconds);
    }

    internal sealed class LegacyJumpSystemWait : ILegacyJumpWait
    {
        public bool WaitOne(WaitHandle handle, int milliseconds)
        {
            return handle.WaitOne(milliseconds);
        }
    }

    /// <summary>Everything the plane takes from outside. Production() hands out the real objects; nothing else can reach a host.</summary>
    internal sealed class LegacyJumpEnvironment
    {
        internal int BvePid;
        internal Func<long> ClockMs;
        internal IEndpointSource Source;
        internal ILegacyJumpSocketFactory Sockets;
        internal ILegacyJumpWriterFactory Writers;
        internal ILegacyJumpWait Waiter;
        internal Action<string> Log;
        internal LegacyJumpTimings Timings;
        internal bool ExecutionEnabled;            // LJX-1: the execution flag (false in the default build)
        internal int FeatureBits;                  // LJX-1: the pieces of the execution that exist (LegacyJumpFeatures); the contract is published only when this is All

        /// <summary>The environment of the product: the execution follows the build flag (OFF in the default build).</summary>
        internal static LegacyJumpEnvironment Production(int bvePid, Action<string> log)
        {
            return Production(bvePid, log, LegacyJumpBuild.ExecutionCompiledIn);
        }

        /// <summary>The same with the execution switched explicitly (the tests and the acceptance wiring). Enabled: all features, the 5.0 s TTL. Disabled: the 2A-alpha environment.</summary>
        internal static LegacyJumpEnvironment Production(int bvePid, Action<string> log, bool executionEnabled)
        {
            LegacyJumpEnvironment e = new LegacyJumpEnvironment();
            e.BvePid = bvePid;
            e.ExecutionEnabled = executionEnabled;
            e.FeatureBits = executionEnabled ? LegacyJumpExecutor.ImplementedFeatures : 0;
            Stopwatch sw = Stopwatch.StartNew();
            e.ClockMs = delegate { return sw.ElapsedMilliseconds; };
            e.Source = new ReaderEndpointSource();
            e.Sockets = new LegacyJumpUdpPortFactory();
            e.Writers = new LegacyJumpMappingWriterFactory();
            e.Waiter = new LegacyJumpSystemWait();
            e.Log = log;
            e.Timings = new LegacyJumpTimings();
            if (executionEnabled) e.Timings.TtlMs = LegacyJumpTimings.ExecutionTtlMs;
            return e;
        }
    }

    /// <summary>A consistent copy of the plane's books (taken under the gate).</summary>
    internal sealed class LegacyJumpSnapshot
    {
        internal LegacyJumpState State;
        internal UInt32 Generation;
        internal byte[] Token;
        internal UInt32 Port;
        internal int Attempts;
        internal int Published;               // endpoints that reached READY
        internal long Received;
        internal long RestartCount;
        internal LegacyJumpReceipt Queued;
    }

    internal sealed class LegacyJumpControlPlane : IDisposable, ILegacyJumpAvailability
    {
        private readonly object gate = new object();
        private readonly object diag = new object();
        private readonly object flushGate = new object();
        private readonly LegacyJumpEnvironment o;
        private readonly LegacyJumpTimings t;
        private readonly ManualResetEvent shutdown = new ManualResetEvent(false);
        private readonly ManualResetEvent closedEvent = new ManualResetEvent(false);
        private readonly Stopwatch gapClock = Stopwatch.StartNew();
        private readonly LegacyJumpCommandQueue queue;

        private volatile bool stopRequested;
        private volatile bool orphanTeardown;
        private volatile bool finished;
        private volatile bool stopStepRan;
        private volatile bool joinStepBegun;
        private volatile int stateValue;
        private volatile Thread worker;
        private int disposeStarted;
        private int eventsReleased;
        private int epoch;                    // the scenario boundary counter (Interlocked: the host's event thread writes it, no lock)
        private int stepsInside;
        private int maxStepsInside;
        private int publishersInside;
        private int maxPublishersInside;
        private int iterations;
        private long maxIterationGapMs;
        private long lastIterationAtMs = -1;
        private int afterDisposeAccess;
        private int refusedNoted;
        private int refusedLogged;            // Phase ST-3c: lines of refused (judged) commands written over the life of the plane; guarded by `diag` (NoteCapped)
        private int txLogged;                 // Phase ST-3c: transaction lines written over the life of the plane; guarded by `diag`
        private const int RefusedLogCapacity = 64;
        private const int TxLogCapacity = 256;
        private long claimContended;          // LJX-1: claims that found the gate busy (the Tick never waits)
        private int consecutiveFailures;      // LJX-1: execution failures in a row (the breaker), valid for the scenario boundary counter in breakerEpoch
        private int breakerEpoch;
        private const int BreakerLimit = 3;   // LJX-1: three failures in a row close AVAIL jump (OD-X6 option B; the number is proposed by the implementation, owner decision pending)

        // ---- guarded by `gate` ----
        private bool tornDown;
        private bool everStarted;
        private LegacyJumpEndpoint ep;
        private UInt32 previousGeneration;
        private byte[] previousToken;
        private int attempts;
        private int publishedEndpoints;
        private int backoffMs;
        private long nextRetryMs;
        private long lastNowMs;
        private long received;
        private long restartCount;
        private int loggedEpoch;
        private object keyOwner;
        private string keyValue;
        private readonly Dictionary<string, long> counters = new Dictionary<string, long>();
        private readonly StringBuilder shutdownOrder = new StringBuilder();

        // ---- guarded by `diag` ----
        private readonly List<string> pendingLog = new List<string>();
        private bool finalNoted;

        internal LegacyJumpControlPlane(LegacyJumpEnvironment environment)
        {
            if (environment == null) throw new ArgumentNullException("environment");
            if (environment.BvePid <= 0) throw new ArgumentOutOfRangeException("BvePid");
            if (environment.ClockMs == null || environment.Source == null || environment.Sockets == null || environment.Writers == null
                || environment.Waiter == null || environment.Timings == null)
            {
                throw new ArgumentException("environment");
            }
            LegacyJumpTimings tm = environment.Timings;
            if (tm.PollMs < 1 || tm.JoinMs < 1 || tm.GateTryMs < 1 || tm.RetryMinMs < 1 || tm.RetryMaxMs < tm.RetryMinMs || tm.MaxDatagramsPerStep < 1 || tm.TtlMs < 0L)
            {
                throw new ArgumentOutOfRangeException("Timings");
            }
            o = environment;
            t = environment.Timings;
            queue = new LegacyJumpCommandQueue(delegate(string line) { Note(line); });
        }

        /// <summary>Builds the plane with the production objects. It creates no port, no mapping and no thread: Start() does.</summary>
        internal static LegacyJumpControlPlane CreateProduction(int bvePid, Action<string> log)
        {
            return new LegacyJumpControlPlane(LegacyJumpEnvironment.Production(bvePid, log));
        }

        // ------------------------------------------------------------------ lock free readouts
        internal LegacyJumpState State { get { return (LegacyJumpState)stateValue; } }
        internal bool IsWorkerAlive { get { Thread w = worker; return w != null && w.IsAlive; } }
        internal int Iterations { get { return Thread.VolatileRead(ref iterations); } }
        internal int MaxStepsInside { get { return Thread.VolatileRead(ref maxStepsInside); } }
        internal int MaxPublishersInside { get { return Thread.VolatileRead(ref maxPublishersInside); } }
        internal long MaxIterationGapMs { get { return Interlocked.Read(ref maxIterationGapMs); } }
        internal int AfterDisposeAccess { get { return Thread.VolatileRead(ref afterDisposeAccess); } }

        // ---- LJX-1: the execution flag and what follows from it (lock free readouts) ----
        /// <summary>
        /// True only when the execution is switched on AND every piece of it exists (station jump, location jump, completion, and the Tick runner that claims and executes -
        /// without that nobody would ever execute what the Directory announces). Otherwise the plane is the 2A-alpha plane.
        /// </summary>
        internal bool ExecutionActive { get { return o.ExecutionEnabled && o.FeatureBits == LegacyJumpFeatures.All && runnerAttached; } }

        /// <summary>The build / environment flag alone (the plane may still be inactive because a piece is missing).</summary>
        internal bool ExecutionEnabledByBuild { get { return o.ExecutionEnabled; } }

        private volatile bool runnerAttached;

        /// <summary>The Tick runner (the only claimer) announces itself when it is built, before the plane is started.</summary>
        internal void AttachRunner()
        {
            runnerAttached = true;
        }

        /// <summary>The capabilities of the Directory: STA | LOC | REQUEST_ID when the execution is active, REQUEST_ID only otherwise. No other combination is ever published.</summary>
        internal int PublishedCapabilities { get { return ExecutionActive ? (int)JumpCapabilities.Published : (int)JumpCapabilities.RequestId; } }

        /// <summary>The scenario boundary counter (the host's event thread writes it).</summary>
        internal int Epoch { get { return Thread.VolatileRead(ref epoch); } }

        internal Func<int> EpochProbe { get { return delegate { return Thread.VolatileRead(ref epoch); }; } }

        /// <summary>The clock of the plane (monotonic milliseconds), for the diagnostic elapsed time of the executor.</summary>
        internal Func<long> Clock { get { return o.ClockMs; } }

        internal bool BreakerOpen
        {
            get { return Thread.VolatileRead(ref consecutiveFailures) >= BreakerLimit && Thread.VolatileRead(ref breakerEpoch) == Thread.VolatileRead(ref epoch); }
        }

        /// <summary>
        /// May the telemetry row announce the jump group (AVAIL jump, JUMP key)? Only while the execution is active, the plane is READY (the Directory carries the command
        /// bits), it is not stopping and the breaker is closed. It becomes false the moment any of these stops holding: the managed application then refuses to start a new
        /// scoring run (missing-jump) instead of sending a command that nobody will execute.
        /// </summary>
        internal bool JumpAvailable
        {
            get { return ExecutionActive && !stopRequested && (LegacyJumpState)stateValue == LegacyJumpState.Ready && !BreakerOpen; }
        }

        bool ILegacyJumpAvailability.JumpOpen { get { return JumpAvailable; } }

        private void SetState(LegacyJumpState s)
        {
            stateValue = (int)s;
        }

        /// <summary>Called before every use of an outside object. Counts the uses that happen after the plane has finished (they must be 0).</summary>
        private void Touch()
        {
            if (finished) Interlocked.Increment(ref afterDisposeAccess);
        }

        private long Now()
        {
            Touch();
            return o.ClockMs();
        }

        // ------------------------------------------------------------------ diagnostics
        private void Note(string line)
        {
            lock (diag)
            {
                if (finalNoted) return;           // nothing is logged after the final summary
                pendingLog.Add(line);
            }
        }

        /// <summary>The summary line: queued together with the closing of the log, so that no line can follow it.</summary>
        private void NoteFinal(string line)
        {
            lock (diag)
            {
                if (finalNoted) return;
                pendingLog.Add(line);
                finalNoted = true;
            }
        }

        private void FlushLog()
        {
            lock (flushGate)
            {
                string[] lines;
                lock (diag)
                {
                    if (pendingLog.Count == 0) return;
                    lines = pendingLog.ToArray();
                    pendingLog.Clear();
                }
                if (o.Log == null) return;
                Touch();
                for (int i = 0; i < lines.Length; i++)
                {
                    try { o.Log(lines[i]); } catch { }
                }
            }
        }

        private void Count(string key)
        {
            long n;
            counters.TryGetValue(key, out n);
            counters[key] = n + 1;
        }

        internal long CounterValue(string key)
        {
            if (key == "claim-contended") return Interlocked.Read(ref claimContended);
            lock (gate)
            {
                long n;
                if (counters.TryGetValue(key, out n)) return n;
                return queue.CounterValue(key);
            }
        }

        internal LegacyJumpSnapshot Snapshot()
        {
            lock (gate)
            {
                LegacyJumpSnapshot s = new LegacyJumpSnapshot();
                s.State = State;
                if (ep != null)
                {
                    s.Generation = ep.Generation;
                    s.Token = (byte[])ep.Token.Clone();
                    s.Port = ep.Port;
                }
                s.Attempts = attempts;
                s.Published = publishedEndpoints;
                s.Received = received;
                s.RestartCount = restartCount;
                LegacyJumpReceipt q = queue.Queued;
                s.Queued = q == null ? null : q.Copy();
                return s;
            }
        }

        /// <summary>Copies of the receipts (Rejected, Queued, Discarded), oldest first.</summary>
        internal LegacyJumpReceipt[] Outcomes()
        {
            lock (gate)
            {
                return queue.Snapshot();
            }
        }

        // ------------------------------------------------------------------ host entry points
        /// <summary>
        /// The one call the host Tick makes. The plane starts exactly once, when the host has confirmed the managed mode AND the scenario events are subscribed (a failed
        /// subscription starts nothing: fail closed, decision D-10); after that every call only checks that the worker is alive. It never waits for the worker.
        /// </summary>
        internal void OnHostTick(bool managed, bool boundaryObservable)
        {
            try
            {
                if (stopRequested) return;
                if (managed && boundaryObservable) Start();
                else if (managed && Interlocked.CompareExchange(ref refusedNoted, 1, 0) == 0)
                {
                    Note("event=jump-start-refused reason=events-not-subscribed");
                    FlushLog();
                }
                EnsureWorkerAlive();
            }
            catch
            {
            }
        }

        /// <summary>The scenario boundary (opened, closed, created) as the host sees it. Lock free; the worker discards the queued command at its next step.</summary>
        internal void NoteScenarioBoundary()
        {
            Interlocked.Increment(ref epoch);
        }

        // ------------------------------------------------------------------ LJX-1: the execution entries (host Tick thread only)
        /// <summary>
        /// THE claim entry (the only way a receipt leaves Queued for Executing). Never blocks the Tick: the gate is tried with a zero wait. The state of the plane is checked
        /// first without a lock (WITHDRAWING, CLOSED, retry: no claim). Under the gate the facts of now are checked in this order - scenario boundary, breaker, age (TTL),
        /// receiver generation, owner - and a command whose facts are void is Discarded (the host API is never called for it). Only then is the command claimed
        /// (Queued to Executing, written BEFORE the host call) and a ticket handed out. Returns null when nothing was claimed.
        /// </summary>
        internal LegacyJumpClaim TryClaimForTick(LegacyJumpClaimFacts facts)
        {
            if (!ExecutionActive || facts == null) return null;
            if (stopRequested || (LegacyJumpState)stateValue != LegacyJumpState.Ready) return null;
            if (!Monitor.TryEnter(gate, 0))
            {
                Interlocked.Increment(ref claimContended);
                return null;
            }
            LegacyJumpClaim ticket = null;
            try
            {
                if (stopRequested || tornDown || State != LegacyJumpState.Ready) return null;
                LegacyJumpReceipt q = queue.Queued;
                if (q == null || q.State != LegacyJumpCommandState.Queued) return null;
                if (queue.InFlight != null) return null;                       // one command in flight (INV-4): the next one waits
                long now = Now();
                string why = null;
                if (Thread.VolatileRead(ref epoch) != q.ScenarioEpoch) why = "scenario-epoch";
                else if (BreakerOpen) why = "breaker-open";
                else if (t.TtlMs > 0 && now - q.ReceivedAtMs > t.TtlMs) why = "ttl";
                else if (ep == null || ep.Generation != q.ReceiverGeneration) why = "endpoint-recreated";
                else
                {
                    string owner = LegacyJumpCommandQueue.OwnerMismatch(o.Source, o.BvePid, q);
                    if (owner != null) why = owner == "telemetry-changed" ? "owner-changed" : owner;
                }
                if (why != null)
                {
                    queue.DiscardQueued(q, why);
                    return null;
                }
                if (!facts.ScenarioCreated || !facts.SessionActive) return null;   // not a fact against the command: it waits for the next Tick (and its TTL)

                // Phase ST-3c: the judgement of a v2 command (scenario, station list id and count, index, location) comes BEFORE the claim. A command that does not hold against what the
                // plugin holds now is Discarded (the host API was never called, nothing is in flight) with the reason contract-<word>, and it is NOT a failure of the breaker: the breaker counts
                // only what went wrong after a claim (ReportExecution). A formal v1 command passes the judgement unchanged.
                LegacyJumpView view = null;
                try { if (facts.ViewProvider != null) view = facts.ViewProvider(); }
                catch (Exception) { view = null; }
                LegacyJumpDecision verdict = LegacyJumpJudge.Judge(q.Text, q.MessageType, view);
                if (!verdict.Accepted)
                {
                    queue.DiscardQueued(q, LegacyJumpJudge.DiscardPrefix + verdict.Reason);
                    NoteCapped(LegacyJumpJudge.RefusedLine(q.RequestId, verdict), ref refusedLogged, RefusedLogCapacity, "event=legacy-jump-refused-log-capped");
                    return null;
                }

                if (!queue.TryClaim(q, now)) return null;
                ticket = LegacyJumpClaim.From(q);
                ticket.Adopt(verdict);
            }
            finally
            {
                Monitor.Exit(gate);
                FlushLog();
            }
            return ticket;
        }

        /// <summary>
        /// The Tick reports the outcome of the host sequence: Executing to CompletionPending (success) or Failed. Returns 1 when taken, 0 when the gate was busy (report again
        /// on the next Tick; the command stays Executing meanwhile), -1 when the receipt is no longer Executing (Dispose, endpoint re-creation): nothing is changed then.
        /// </summary>
        internal int ReportExecution(LegacyJumpClaim ticket, LegacyJumpExecResult result)
        {
            if (ticket == null || ticket.Receipt == null || result == null) return -1;
            int outcome = -1;
            bool got = false;
            try
            {
                got = Monitor.TryEnter(gate, 50);
                if (!got) return 0;
                LegacyJumpReceipt r = ticket.Receipt;
                if (r.State != LegacyJumpCommandState.Executing)
                {
                    Count("report-after-end");
                    return -1;
                }
                queue.NoteExecuted(r, result.Ok, result.Step, result.ElapsedMs);
                if (result.Ok)
                {
                    queue.Finish(r, LegacyJumpCommandState.CompletionPending, null);
                    Interlocked.Exchange(ref consecutiveFailures, 0);
                }
                else
                {
                    queue.Finish(r, LegacyJumpCommandState.Failed, result.Reason ?? "failed");
                    RegisterFailure();
                }
                outcome = 1;
            }
            finally
            {
                if (got) Monitor.Exit(gate);
                FlushLog();
            }
            return outcome;
        }

        /// <summary>
        /// Phase ST-3c: the one line of a claimed command that ended (see LegacyJumpJudge.TransactionLine), written by the Tick runner. Never per Tick; capped over the life of the plane. It only
        /// reads: it changes no state of the command and no count of the breaker.
        /// </summary>
        internal void NoteTransaction(LegacyJumpClaim ticket, string status)
        {
            try
            {
                if (ticket == null) return;
                NoteCapped(LegacyJumpJudge.TransactionLine(ticket, status ?? "-", t.TtlMs, BreakerOpen), ref txLogged, TxLogCapacity, "event=legacy-jump-tx-log-capped");
                FlushLog();
            }
            catch
            {
            }
        }

        /// <summary>A diagnostic line with its own capacity (capacity, not time): the line itself while there is room, one "capped" line when the room is used up, then nothing.</summary>
        private void NoteCapped(string line, ref int logged, int capacity, string cappedEvent)
        {
            lock (diag)
            {
                if (finalNoted) return;
                if (logged > capacity) return;
                if (logged == capacity)
                {
                    logged++;
                    pendingLog.Add(cappedEvent + " limit=" + capacity);
                    return;
                }

                logged++;
                pendingLog.Add(line);
            }
        }

        private void RegisterFailure()
        {
            int e = Thread.VolatileRead(ref epoch);
            if (Thread.VolatileRead(ref breakerEpoch) != e)
            {
                Interlocked.Exchange(ref consecutiveFailures, 0);       // a new scenario starts the count again
                Interlocked.Exchange(ref breakerEpoch, e);
            }
            int n = Interlocked.Increment(ref consecutiveFailures);
            if (n == BreakerLimit) Note("event=jump-breaker-open failures=" + n);
        }

        /// <summary>Ends the in-flight command of the ticket as Abandoned (the runner found a fact against sending the completion). No effect when it already ended.</summary>
        internal void AbandonInFlight(LegacyJumpClaim ticket, string reason)
        {
            if (ticket == null || ticket.Receipt == null) return;
            bool got = false;
            try
            {
                got = Monitor.TryEnter(gate, 50);
                if (!got) return;
                LegacyJumpCommandState s = ticket.Receipt.State;
                if (s == LegacyJumpCommandState.Executing || s == LegacyJumpCommandState.CompletionPending) queue.Finish(ticket.Receipt, LegacyJumpCommandState.Abandoned, reason);
            }
            finally
            {
                if (got) Monitor.Exit(gate);
                FlushLog();
            }
        }

        /// <summary>
        /// The completion, in the post session part of the Tick (after the row of the execution Tick was written). The facts recorded at the acceptance are compared with those
        /// of now (comparison only: the destination is always the one the router resolves, never one taken from this comparison); a difference ends the command Abandoned.
        /// The sender says Sent (Completed), Excluded (Abandoned: consumed without a datagram) or Held (still CompletionPending: the same completion is tried again on the next
        /// Tick, until a fact changes or the plane stops). Completed is never assumed.
        /// </summary>
        internal int TryCompleteInPostSession(LegacyJumpClaim ticket, LegacyJumpClaimFacts facts, ILegacyJumpCompleteSender sender)
        {
            if (ticket == null || ticket.Receipt == null || sender == null) return LegacyJumpCompletion.None;
            int outcome = LegacyJumpCompletion.None;
            bool got = false;
            try
            {
                got = Monitor.TryEnter(gate, 50);
                if (!got) return LegacyJumpCompletion.Pending;
                LegacyJumpReceipt r = ticket.Receipt;
                if (r.State == LegacyJumpCommandState.Completed) return LegacyJumpCompletion.Done;
                if (r.State != LegacyJumpCommandState.CompletionPending) return LegacyJumpCompletion.Abandoned;
                if (stopRequested || tornDown)
                {
                    queue.Finish(r, LegacyJumpCommandState.Abandoned, "dispose");
                    return LegacyJumpCompletion.Abandoned;
                }
                if (ticket.Payload == null)
                {
                    queue.Finish(r, LegacyJumpCommandState.Abandoned, "completion-no-payload");
                    return LegacyJumpCompletion.Abandoned;
                }
                string why = CompletionMismatchLocked(r);
                if (why != null)
                {
                    queue.Finish(r, LegacyJumpCommandState.Abandoned, why);
                    return LegacyJumpCompletion.Abandoned;
                }
                int sent;
                try { sent = sender.SendJumpComplete(ticket.Payload, ticket.RequestId); }
                catch (ThreadAbortException) { throw; }
                catch (Exception)
                {
                    sent = LegacyJumpSend.Held;
                    Count("complete-send-exception");
                }
                if (sent == LegacyJumpSend.Sent)
                {
                    queue.Finish(r, LegacyJumpCommandState.Completed, null);
                    outcome = LegacyJumpCompletion.Done;
                }
                else if (sent == LegacyJumpSend.Excluded)
                {
                    queue.Finish(r, LegacyJumpCommandState.Abandoned, "completion-excluded");
                    outcome = LegacyJumpCompletion.Abandoned;
                }
                else
                {
                    Count("complete-held");
                    if (!ticket.PendingNoted)
                    {
                        ticket.PendingNoted = true;
                        queue.NoteCompletionPending(r);
                    }
                    outcome = LegacyJumpCompletion.Pending;
                }
            }
            finally
            {
                if (got) Monitor.Exit(gate);
                FlushLog();
            }
            return outcome;
        }

        /// <summary>The facts of the acceptance against those of now, for the completion: scenario boundary, receiver generation, owner. null = the completion may be sent.</summary>
        private string CompletionMismatchLocked(LegacyJumpReceipt r)
        {
            if (Thread.VolatileRead(ref epoch) != r.ScenarioEpoch) return "completion-scenario-changed";
            if (ep == null || ep.Generation != r.ReceiverGeneration) return "completion-jump-generation-changed";
            string owner = LegacyJumpCommandQueue.OwnerMismatch(o.Source, o.BvePid, r);
            if (owner == null) return null;
            return owner == "telemetry-changed" ? "completion-telemetry-changed" : "completion-owner-changed";
        }

        /// <summary>Starts the one dedicated worker (once). A second call, or a call after Dispose, does nothing: one instance owns one worker and one endpoint at a time.</summary>
        internal void Start()
        {
            if (stopRequested || (LegacyJumpState)stateValue != LegacyJumpState.NotStarted) return;      // the fast path takes no lock
            lock (gate)
            {
                if (stopRequested || (LegacyJumpState)stateValue != LegacyJumpState.NotStarted) return;
                everStarted = true;
                nextRetryMs = 0;
                SetState(LegacyJumpState.Publishing);
                StartWorkerLocked();
            }
            FlushLog();
        }

        private void StartWorkerLocked()
        {
            Thread th = new Thread(Loop);
            th.IsBackground = true;
            th.Name = "TS Scoring LegacyJump control";
            worker = th;
            Note("event=jump-worker-start restarts=" + restartCount);
            th.Start();
        }

        /// <summary>The liveness check of the host Tick: restarts a dead worker, never after a stop request. Takes no lock while the worker lives.</summary>
        internal bool EnsureWorkerAlive()
        {
            if (stopRequested) return false;
            Thread w = worker;
            if (w != null && w.IsAlive) return true;
            bool restarted = false;
            lock (gate)
            {
                if (stopRequested || tornDown || (LegacyJumpState)stateValue == LegacyJumpState.NotStarted) return false;
                w = worker;
                if (w != null && w.IsAlive) return true;
                restartCount++;
                StartWorkerLocked();
                restarted = true;
            }
            if (restarted) FlushLog();
            return true;
        }

        // ------------------------------------------------------------------ the worker
        private void Loop()
        {
            string exitReason = "stop";
            try
            {
                while (true)
                {
                    Touch();
                    bool stopped;
                    try { stopped = o.Waiter.WaitOne(shutdown, t.PollMs); }
                    catch (ThreadAbortException) { throw; }
                    catch { stopped = shutdown.WaitOne(t.PollMs); }          // an exception of the wait never ends the worker
                    if (stopped) break;
                    NoteIteration();
                    try { Step(); }
                    catch (ThreadAbortException) { throw; }
                    catch { }
                }
            }
            catch (ThreadAbortException)
            {
                exitReason = "abort";
            }
            catch
            {
                exitReason = "exception";
            }
            finally
            {
                try
                {
                    Note("event=jump-worker-exit reason=" + exitReason);
                    if (orphanTeardown)
                    {
                        lock (gate) { TeardownLocked(); }
                    }
                }
                catch { }
                FlushLog();
                if ((LegacyJumpState)stateValue == LegacyJumpState.Closed)
                {
                    finished = true;
                    try { closedEvent.Set(); } catch { }
                    ReleaseEvents();
                }
            }
        }

        private void NoteIteration()
        {
            long now = gapClock.ElapsedMilliseconds;
            long last = Interlocked.Exchange(ref lastIterationAtMs, now);
            if (last >= 0)
            {
                long gap = now - last;
                long seen;
                while (gap > (seen = Interlocked.Read(ref maxIterationGapMs)))
                {
                    if (Interlocked.CompareExchange(ref maxIterationGapMs, gap, seen) == seen) break;
                }
            }
            Interlocked.Increment(ref iterations);
        }

        /// <summary>One poll. Only the worker thread calls it.</summary>
        private void Step()
        {
            int inside = Interlocked.Increment(ref stepsInside);
            try
            {
                int seen;
                while (inside > (seen = Thread.VolatileRead(ref maxStepsInside)))
                {
                    if (Interlocked.CompareExchange(ref maxStepsInside, inside, seen) == seen) break;
                }
                StepCore();
            }
            finally
            {
                Interlocked.Decrement(ref stepsInside);
            }
        }

        private void StepCore()
        {
            try
            {
                lock (gate)
                {
                    if (tornDown) Interlocked.Increment(ref afterDisposeAccess);
                    if (stopRequested || tornDown) return;
                    LegacyJumpState s = State;
                    if (s == LegacyJumpState.Disposing || s == LegacyJumpState.Closed || s == LegacyJumpState.NotStarted) return;
                    try
                    {
                        StepLocked();
                    }
                    catch (ThreadAbortException)
                    {
                        throw;
                    }
                    catch (Exception ex)
                    {
                        Count("step-exception");
                        Note("event=jump-step-exception type=" + ex.GetType().Name);
                        try { RollbackEndpointLocked("step-exception"); } catch { }
                        EnterRetryLocked(lastNowMs, "step-exception", false);          // the time of this step: a clock that failed is not asked again
                    }
                }
            }
            finally
            {
                FlushLog();
            }
        }

        private void StepLocked()
        {
            long now = Now();                                 // the first thing every step does, inside the gate
            lastNowMs = now;
            LegacyJumpState s = State;
            int boundary = Thread.VolatileRead(ref epoch);
            if (boundary != loggedEpoch)
            {
                loggedEpoch = boundary;
                Note("event=jump-scenario-boundary epoch=" + boundary);
            }
            if (s == LegacyJumpState.Publishing || s == LegacyJumpState.RetryWaiting)
            {
                if (now >= nextRetryMs) TryCreateLocked(now);
                return;
            }
            if (s == LegacyJumpState.Ready)
            {
                ReadLocked(now, boundary);
                queue.Sweep(o.Source, o.BvePid, boundary, t.TtlMs, now);
            }
        }

        // ------------------------------------------------------------------ the endpoint: create, retry, withdraw
        private void TryCreateLocked(long now)
        {
            attempts++;
            bool priorWasRetry = State == LegacyJumpState.RetryWaiting;
            SetState(LegacyJumpState.Publishing);
            LegacyJumpEndpoint e = null;
            bool published = false;
            try
            {
                e = LegacyJumpEndpoint.Open(o, LegacyJumpNames.For(o.BvePid), previousGeneration, previousToken, delegate(string line) { Note(line); });      // bind, port check, generation, token, CreateNew
                if (stopRequested) throw new OperationCanceledException("stop-requested");
                PublishRaw(e, DataPlaneProtocol.Published, "PUBLISHED");
                published = true;
                int available = e.Socket.Available;                // the receive path exists before READY (RC-8): the port answers
                if (available < 0) throw new InvalidOperationException("receive-path");
                if (stopRequested) throw new OperationCanceledException("stop-requested");
                PublishRaw(e, DataPlaneProtocol.Published | DataPlaneProtocol.Ready, "READY");
                ep = e;
                previousGeneration = e.Generation;
                previousToken = (byte[])e.Token.Clone();
                publishedEndpoints++;
                backoffMs = 0;
                SetState(LegacyJumpState.Ready);
                Note("event=jump-endpoint-ready attempts=" + attempts + " gen=" + e.Generation + " port=" + e.Port);
            }
            catch (ThreadAbortException)
            {
                RollbackLocal(e, published, "abort");
                throw;
            }
            catch (Exception ex)
            {
                RollbackLocal(e, published, "create-failed:" + ex.GetType().Name);
                if (stopRequested)
                {
                    SetState(LegacyJumpState.Disposing);          // a stop is in progress: no retry, the teardown finishes the job
                    return;
                }
                Count("create-failed");
                EnterRetryLocked(now, ex.GetType().Name, priorWasRetry);
            }
        }

        /// <summary>The retry interval of the Directory creation (decision D-3). It is measured on the injected clock and means nothing else.</summary>
        private void EnterRetryLocked(long now, string why, bool wasWaiting)
        {
            backoffMs = backoffMs == 0 ? t.RetryMinMs : Math.Min(backoffMs * 2, t.RetryMaxMs);
            nextRetryMs = now + backoffMs;
            SetState(LegacyJumpState.RetryWaiting);
            if (!wasWaiting) Note("event=jump-recreate-pending reason=" + why + " attempts=" + attempts + " backoffMs=" + backoffMs);      // state changes only; the count is in `attempts`
        }

        /// <summary>A failed attempt: close the port, say CLOSED if PUBLISHED was written, release the mapping. No Reader has seen READY.</summary>
        private void RollbackLocal(LegacyJumpEndpoint e, bool published, string reason)
        {
            if (e != null)
            {
                try { e.Socket.Close(); } catch { }
                if (published)
                {
                    try { PublishRaw(e, DataPlaneProtocol.Closed, "CLOSED"); } catch { }
                }
                try { e.Writer.Release(); } catch { }
            }
            Note("event=jump-endpoint-rollback reason=" + reason);
        }

        /// <summary>RC-10: withdraw the CURRENT endpoint completely (WITHDRAWING, close the port, CLOSED, release); the next attempt publishes a new one.</summary>
        private void RollbackEndpointLocked(string reason)
        {
            SetState(LegacyJumpState.Withdrawing);
            queue.Expire("endpoint-recreated");
            queue.AbandonInFlight("endpoint-recreated");
            LegacyJumpEndpoint e = ep;
            if (e != null)
            {
                DrainRejectLocked("endpoint-withdrawn");
                try { PublishRaw(e, DataPlaneProtocol.Published | DataPlaneProtocol.Ready | DataPlaneProtocol.Withdrawing, "WITHDRAWING"); }
                catch (ThreadAbortException) { throw; }
                catch { }
                try { e.Socket.Close(); } catch { }
                try { PublishRaw(e, DataPlaneProtocol.Closed, "CLOSED"); } catch { }
                try { e.Writer.Release(); } catch { }
                Note(e.Validator.Summary());
            }
            ep = null;
            Note("event=jump-endpoint-withdrawn reason=" + reason);
        }

        /// <summary>The single writer path: every Directory write goes through here, under the gate (RC-9). Capabilities: REQUEST_ID only; CLOSED carries none.</summary>
        private void PublishRaw(LegacyJumpEndpoint e, UInt32 state, string what)
        {
            int inside = Interlocked.Increment(ref publishersInside);
            try
            {
                int seen;
                while (inside > (seen = Thread.VolatileRead(ref maxPublishersInside)))
                {
                    if (Interlocked.CompareExchange(ref maxPublishersInside, inside, seen) == seen) break;
                }
                if (!Monitor.IsEntered(gate)) throw new InvalidOperationException("writer-gate-not-held");
                Touch();
                if (state == DataPlaneProtocol.Closed)
                {
                    e.Writer.Publish(state, 0U, 0U, new byte[16], 0U);
                }
                else
                {
                    string key = e.Port + "/" + e.Generation + "/" + Convert.ToBase64String(e.Token);
                    if (!Object.ReferenceEquals(keyOwner, e.Writer)) { keyOwner = e.Writer; keyValue = key; }
                    else if (keyValue != key) Count("rc10-violation");          // RC-10: while one mapping is published its port, generation and token never change
                    e.Writer.Publish(state, e.Port, e.Generation, e.Token, (UInt32)PublishedCapabilities);
                }
                Note("event=jump-directory state=" + what + " gen=" + e.Generation + " port=" + e.Port);
            }
            finally
            {
                Interlocked.Decrement(ref publishersInside);
            }
        }

        // ------------------------------------------------------------------ datagrams
        private void ReadLocked(long now, int boundary)
        {
            LegacyJumpEndpoint e = ep;
            int n = 0;
            while (n < t.MaxDatagramsPerStep && !stopRequested && e != null && e.Socket.Available > 0)
            {
                byte[] data = e.Socket.ReadDatagram();
                n++;
                received++;
                e.Handle(data, now, boundary, queue);
            }
        }

        /// <summary>Datagrams that arrive while the endpoint is being withdrawn are read and counted as Rejected without validation: nothing is accepted or queued.</summary>
        private void DrainRejectLocked(string reason)
        {
            LegacyJumpEndpoint e = ep;
            if (e == null) return;
            try
            {
                int guard = 0;
                while (guard++ < 1000 && e.Socket.Available > 0)
                {
                    e.Socket.ReadDatagram();
                    received++;
                    LegacyJumpReceipt rejected = new LegacyJumpReceipt();
                    rejected.ReceivedAtMs = Now();
                    rejected.ReceiverGeneration = e.Generation;
                    queue.AddRejected(rejected, reason);
                }
            }
            catch
            {
            }
        }

        // ------------------------------------------------------------------ shutdown
        /// <summary>
        /// 1 stop receiving, 2 expire the queued command, 3 worker stop request, 4 bounded Join outside the gate, then (teardown) 5 WITHDRAWING, 6 close the port, 7 CLOSED,
        /// 8 release the mapping and the internal resources. Idempotent, never throws. When the gate cannot be taken in time the worker completes the teardown as it leaves.
        /// </summary>
        public void Dispose()
        {
            try
            {
                DisposeCore();
            }
            catch
            {
            }
        }

        private void DisposeCore()
        {
            if (Interlocked.CompareExchange(ref disposeStarted, 1, 0) != 0)
            {
                WaitClosed(t.JoinMs + t.GateTryMs);
                return;
            }
            stopRequested = true;                                 // step 1 (lock free: nothing is read and no READY is written from this instant)
            stopStepRan = true;
            Note("event=jump-dispose-begin state=" + State);
            bool got = false;
            try
            {
                got = Monitor.TryEnter(gate, t.GateTryMs);
                if (got)
                {
                    if (State != LegacyJumpState.Closed)
                    {
                        if (State != LegacyJumpState.NotStarted || ep != null) SetState(LegacyJumpState.Disposing);
                        DrainRejectLocked("dispose-in-progress");      // a datagram that already arrived is counted as Rejected
                        queue.Expire("dispose");                       // step 2
                        queue.AbandonInFlight("dispose");              // LJX-1: a command in flight ends Abandoned; the host call that may be running is never interrupted
                    }
                }
                else
                {
                    orphanTeardown = true;
                    Note("event=jump-dispose-gate-timeout step=expire");
                }
            }
            finally
            {
                if (got) Monitor.Exit(gate);
            }

            try { shutdown.Set(); } catch { }                     // step 3
            Note("event=jump-worker-stop-requested");
            Thread w = worker;
            if (w != null && w != Thread.CurrentThread)
            {
                joinStepBegun = true;
                Note("event=jump-join-begin timeoutMs=" + t.JoinMs);
                long started = gapClock.ElapsedMilliseconds;
                bool joined;
                try { joined = w.Join(t.JoinMs); } catch { joined = false; }          // step 4 (outside the gate, bounded)
                Note("event=jump-join-end result=" + (joined ? "joined" : "timeout") + " elapsedMs=" + (gapClock.ElapsedMilliseconds - started));
            }
            FlushLog();

            bool got2 = false;
            try
            {
                got2 = Monitor.TryEnter(gate, t.GateTryMs);
                if (got2)
                {
                    TeardownLocked();                             // steps 5 to 8
                }
                else
                {
                    orphanTeardown = true;
                    Note("event=jump-dispose-gate-timeout step=teardown");
                }
            }
            finally
            {
                if (got2) Monitor.Exit(gate);
            }
            if (!got2)
            {
                Thread w2 = worker;
                if (w2 == null || !w2.IsAlive)
                {
                    // the worker is already gone, so nobody else will finish: one more bounded attempt
                    if (Monitor.TryEnter(gate, t.GateTryMs))
                    {
                        try { TeardownLocked(); }
                        finally { Monitor.Exit(gate); }
                    }
                }
            }
            FlushLog();
            if (State == LegacyJumpState.Closed)
            {
                finished = true;
                try { closedEvent.Set(); } catch { }
                Thread w3 = worker;
                if (w3 == null || !w3.IsAlive) ReleaseEvents();
            }
        }

        private void TeardownLocked()
        {
            if (tornDown) return;
            tornDown = true;
            if (State != LegacyJumpState.Closed) SetState(LegacyJumpState.Withdrawing);
            queue.Expire("dispose");
            queue.AbandonInFlight("dispose");
            LegacyJumpEndpoint e = ep;
            if (stopStepRan) shutdownOrder.Append("stop");
            if (joinStepBegun) shutdownOrder.Append(shutdownOrder.Length > 0 ? ",join" : "join");
            if (e != null)
            {
                try { PublishRaw(e, DataPlaneProtocol.Published | DataPlaneProtocol.Ready | DataPlaneProtocol.Withdrawing, "WITHDRAWING"); } catch { }      // step 5
                shutdownOrder.Append(",withdrawing");
                DrainRejectLocked("dispose-in-progress");         // the datagrams that arrived up to the close are counted
                try { e.Socket.Close(); } catch { }               // step 6
                shutdownOrder.Append(",socket-close");
                try { PublishRaw(e, DataPlaneProtocol.Closed, "CLOSED"); } catch { }          // step 7: the canonical CLOSED value comes from the shared encoder
                shutdownOrder.Append(",closed");
                try { e.Writer.Release(); } catch { }             // step 8
                shutdownOrder.Append(",release");
                Note(e.Validator.Summary());
            }
            ep = null;
            SetState(LegacyJumpState.Closed);
            if (everStarted)
            {
                NoteFinal("event=jump-plane-final iterations=" + Thread.VolatileRead(ref iterations) + " maxStepsInside=" + Thread.VolatileRead(ref maxStepsInside)
                    + " maxPublishersInside=" + Thread.VolatileRead(ref maxPublishersInside) + " maxIterationGapMs=" + Interlocked.Read(ref maxIterationGapMs)
                    + " afterDisposeAccess=" + Thread.VolatileRead(ref afterDisposeAccess) + " received=" + received + " accepted=" + queue.CounterValue("queued")
                    + " rejected=" + queue.RejectedTotal() + " rc10Violations=" + CountOf("rc10-violation") + " shutdown-order=" + shutdownOrder.ToString() + ExecutionSummary());
            }
            try { closedEvent.Set(); } catch { }
        }

        private long CountOf(string key)
        {
            long n;
            return counters.TryGetValue(key, out n) ? n : 0L;
        }

        /// <summary>The totals of the execution for the final summary line: empty when the execution is not active, so that the line of the default build stays what it was.</summary>
        private string ExecutionSummary()
        {
            if (!ExecutionActive) return string.Empty;
            return " claimed=" + queue.CounterValue("claimed") + " executed=" + queue.CounterValue("executed") + " failed=" + queue.CounterValue("failed")
                + " completed=" + queue.CounterValue("completed") + " abandoned=" + queue.CounterValue("abandoned") + " claimContended=" + Interlocked.Read(ref claimContended)
                + " ageAtClaimMax=" + queue.AgeAtClaimMax + " execElapsedMax=" + queue.ExecElapsedMax;
        }

        private void WaitClosed(int milliseconds)
        {
            try { closedEvent.WaitOne(milliseconds); }
            catch { }
        }

        private void ReleaseEvents()
        {
            if (Interlocked.CompareExchange(ref eventsReleased, 1, 0) != 0) return;
            try { shutdown.Close(); } catch { }
            try { closedEvent.Close(); } catch { }
        }
    }
}
