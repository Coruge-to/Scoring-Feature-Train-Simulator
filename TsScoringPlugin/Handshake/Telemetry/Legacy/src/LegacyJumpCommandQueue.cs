using System;
using System.Collections.Generic;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA - the command books of the Legacy Jump control plane.
//
// What it holds: one receipt per datagram the plane read (Rejected, Queued or Discarded), the queue of depth 1 (the newest accepted command wins), the single
// transition point that takes a receipt out of Queued, the discard reasons and the counters. A receipt keeps the text and the request id OPAQUELY: nothing here
// interprets a command, and nothing here can run one. In the 2A-alpha build a Queued command ends Discarded, or is still Queued when the plane stops (decision D-6).
// The time expiry exists only when a TTL is injected (the product default is none, decision D-2).
//
// LJX-1 (the minimal execution slice, behind the build flag): the receipt can leave Queued by ONE more way, TryClaim (Queued to Executing), and the claimed receipt
// then follows the in-flight states: Executing to Failed or CompletionPending, CompletionPending to Completed or Abandoned, Executing to Abandoned. Exactly one receipt
// is in flight at a time (INV-4). Discarded still means "the host API was never called for this command" (INV-2): it is reachable from Queued only.
//
// Host independent, BCL only. NOT thread safe: only the control plane touches it, always under its single gate (written at the top of LegacyJumpControlPlane.cs).
// Written in C# 5 syntax on purpose (the offline tests compile the product files directly).
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>
    /// Rejected: failed validation, nothing queued. Queued: accepted, waiting. Discarded: left the queue without any effect (the host API was never called).
    /// Executing: claimed by the Tick, the host API sequence is about to run or running. Failed: the sequence failed (no completion). CompletionPending: the sequence
    /// succeeded, the completion is not consumed yet. Completed: the completion was consumed by the sender. Abandoned: ended after the claim without a completion.
    /// </summary>
    internal enum LegacyJumpCommandState
    {
        Rejected = 0,
        Queued = 1,
        Discarded = 2,
        Executing = 3,
        CompletionPending = 4,
        Completed = 5,
        Failed = 6,
        Abandoned = 7
    }

    /// <summary>The record of one datagram. The token copy is a secret: it is never logged.</summary>
    internal sealed class LegacyJumpReceipt
    {
        internal long Sequence;
        internal LegacyJumpCommandState State;
        internal string Reason;
        internal byte[] RequestId;           // null when the envelope was not decodable
        internal UInt32 MessageType;
        internal string Text;
        internal int BvePid;
        internal string AppInstance;
        internal UInt32 AppPid;
        internal UInt32 TelemetryGeneration;
        internal byte[] TelemetryToken;
        internal UInt32 TelemetryPort;
        internal UInt32 ReceiverGeneration;
        internal long ReceivedAtMs;
        internal int ScenarioEpoch;
        internal long ClaimedAtMs = -1;          // LJX-1: the plane clock at the claim (-1 = never claimed)
        internal long AgeAtClaimMs = -1;         // LJX-1: ClaimedAtMs - ReceivedAtMs (-1 = never claimed)

        internal LegacyJumpReceipt Copy()
        {
            LegacyJumpReceipt c = (LegacyJumpReceipt)MemberwiseClone();
            if (RequestId != null) c.RequestId = (byte[])RequestId.Clone();
            if (TelemetryToken != null) c.TelemetryToken = (byte[])TelemetryToken.Clone();
            return c;
        }
    }

    /// <summary>Depth 1, newest first. Every way out of Queued goes through Transition.</summary>
    internal sealed class LegacyJumpCommandQueue
    {
        internal const int ResultCapacity = 512;        // the bounded list of receipts kept for diagnostics (capacity, not time)
        private const int LogCapacity = 32;             // command lines written to the log over the life of one plane

        private readonly Action<string> note;
        private readonly List<LegacyJumpReceipt> outcomes = new List<LegacyJumpReceipt>();
        private readonly Dictionary<string, long> counters = new Dictionary<string, long>();
        private LegacyJumpReceipt queued;
        private LegacyJumpReceipt inFlight;
        private long sequence;
        private int logged;
        private int execLogged;
        private const int ExecLogCapacity = 256;       // lines of the execution vocabulary (claimed / end / failed / complete...) over the life of one plane: capacity, not time

        internal LegacyJumpCommandQueue(Action<string> note)
        {
            this.note = note;
            AgeAtClaimMax = -1;
            ExecElapsedMax = -1;
        }

        /// <summary>The newest accepted receipt. It may have been discarded since: look at its State.</summary>
        internal LegacyJumpReceipt Queued { get { return queued; } }

        /// <summary>The one receipt that is Executing or CompletionPending, or null (INV-4: at most one).</summary>
        internal LegacyJumpReceipt InFlight { get { return inFlight; } }

        /// <summary>The largest age (ms) of a command at its claim, over all claims of this plane (-1 = no claim yet).</summary>
        internal long AgeAtClaimMax { get; private set; }

        /// <summary>The largest elapsed time (ms) of one host API sequence (-1 = none yet). A diagnostic only.</summary>
        internal long ExecElapsedMax { get; private set; }

        internal long CounterValue(string key)
        {
            long n;
            return counters.TryGetValue(key, out n) ? n : 0L;
        }

        internal long RejectedTotal()
        {
            long total = 0;
            foreach (KeyValuePair<string, long> kv in counters)
            {
                if (kv.Key.StartsWith("rejected:", StringComparison.Ordinal)) total += kv.Value;
            }
            return total;
        }

        private void Count(string key)
        {
            long n;
            counters.TryGetValue(key, out n);
            counters[key] = n + 1;
        }

        private void Emit(string line)
        {
            if (note == null) return;
            if (logged == LogCapacity)
            {
                logged++;
                note("event=jump-command-log-capped limit=" + LogCapacity);
                return;
            }
            if (logged > LogCapacity) return;
            logged++;
            note(line);
        }

        private void AddOutcome(LegacyJumpReceipt r)
        {
            outcomes.Add(r);
            while (outcomes.Count > ResultCapacity) outcomes.RemoveAt(0);
        }

        /// <summary>A datagram that failed validation (or was read while the endpoint was being withdrawn). Nothing is queued.</summary>
        internal void AddRejected(LegacyJumpReceipt r, string reason)
        {
            r.Sequence = ++sequence;
            r.State = LegacyJumpCommandState.Rejected;
            r.Reason = reason;
            AddOutcome(r);
            Count("rejected:" + reason);
        }

        /// <summary>An accepted command. The command that was Queued before is Discarded (replaced): depth 1, newest first.</summary>
        internal void Enqueue(LegacyJumpReceipt r)
        {
            r.Sequence = ++sequence;
            r.State = LegacyJumpCommandState.Queued;
            if (queued != null && queued.State == LegacyJumpCommandState.Queued) Transition(queued, LegacyJumpCommandState.Discarded, "replaced");
            queued = r;
            AddOutcome(r);
            Count("queued");
            Emit("event=jump-command-accepted seq=" + r.Sequence + " type=0x" + r.MessageType.ToString("x") + " id=" + JumpCommandValidator.Hex8(r.RequestId));
            // LJX-1: a newer command replaces a completion that is still pending (the managed application also ends its older request when it sends a newer one)
            if (inFlight != null && inFlight.State == LegacyJumpCommandState.CompletionPending) Finish(inFlight, LegacyJumpCommandState.Abandoned, "superseded");
        }

        /// <summary>The ONLY place where a receipt leaves Queued to Discarded. Anything else is an illegal transition (counted; the tests require 0).</summary>
        internal bool Transition(LegacyJumpReceipt r, LegacyJumpCommandState to, string reason)
        {
            if (r.State != LegacyJumpCommandState.Queued || to != LegacyJumpCommandState.Discarded)
            {
                Count("illegal-transition");
                return false;
            }
            r.State = to;
            r.Reason = reason;
            Count("discarded:" + reason);
            Emit("event=jump-command-discarded seq=" + r.Sequence + " reason=" + reason);
            return true;
        }

        /// <summary>The ONLY place where a receipt leaves Queued to Executing (the one claim entry). The write comes before the host call. At most one receipt is in flight.</summary>
        internal bool TryClaim(LegacyJumpReceipt r, long nowMs)
        {
            if (r.State != LegacyJumpCommandState.Queued || inFlight != null)
            {
                Count("illegal-transition");
                return false;
            }
            r.State = LegacyJumpCommandState.Executing;
            r.Reason = null;
            r.ClaimedAtMs = nowMs;
            r.AgeAtClaimMs = nowMs - r.ReceivedAtMs;
            inFlight = r;
            Count("claimed");
            CountMax("max-in-flight", 1);
            if (r.AgeAtClaimMs > AgeAtClaimMax) AgeAtClaimMax = r.AgeAtClaimMs;
            EmitExec("event=jump-exec-claimed seq=" + r.Sequence + " id=" + JumpCommandValidator.Hex8(r.RequestId) + " ageAtClaimMs=" + r.AgeAtClaimMs);
            return true;
        }

        /// <summary>
        /// The ONLY place where an in-flight receipt moves on: Executing to Failed / CompletionPending / Abandoned, CompletionPending to Completed / Abandoned. Any other pair
        /// is an illegal transition (counted; the tests require 0). A terminal state frees the in-flight slot.
        /// </summary>
        internal bool Finish(LegacyJumpReceipt r, LegacyJumpCommandState to, string reason)
        {
            bool legal = (r.State == LegacyJumpCommandState.Executing && (to == LegacyJumpCommandState.Failed || to == LegacyJumpCommandState.CompletionPending || to == LegacyJumpCommandState.Abandoned))
                || (r.State == LegacyJumpCommandState.CompletionPending && (to == LegacyJumpCommandState.Completed || to == LegacyJumpCommandState.Abandoned));
            if (!legal || !Object.ReferenceEquals(r, inFlight))
            {
                Count("illegal-transition");
                return false;
            }
            r.State = to;
            r.Reason = reason;
            if (to == LegacyJumpCommandState.Failed)
            {
                Count("failed");
                Count("failed:" + reason);
                EmitExec("event=jump-exec-failed seq=" + r.Sequence + " reason=" + reason);
            }
            else if (to == LegacyJumpCommandState.Completed)
            {
                Count("completed");
                EmitExec("event=jump-complete-sent seq=" + r.Sequence + " id=" + JumpCommandValidator.Hex8(r.RequestId));
            }
            else if (to == LegacyJumpCommandState.Abandoned)
            {
                Count("abandoned");
                Count("abandoned:" + reason);
                EmitExec("event=jump-complete-abandoned seq=" + r.Sequence + " reason=" + reason);
            }
            if (to != LegacyJumpCommandState.CompletionPending) inFlight = null;
            return true;
        }

        /// <summary>Ends the in-flight receipt (Executing or CompletionPending) as Abandoned (Dispose, endpoint re-creation). No effect when nothing is in flight.</summary>
        internal void AbandonInFlight(string reason)
        {
            if (inFlight != null) Finish(inFlight, LegacyJumpCommandState.Abandoned, reason);
        }

        /// <summary>A diagnostic of the execution: the elapsed time of the host sequence of one claimed command (recorded for the maximum; never a limit).</summary>
        internal void NoteExecuted(LegacyJumpReceipt r, bool ok, string step, long elapsedMs)
        {
            if (elapsedMs > ExecElapsedMax) ExecElapsedMax = elapsedMs;
            if (ok) Count("executed");
            EmitExec("event=jump-exec-end seq=" + r.Sequence + " ok=" + (ok ? "1" : "0") + " step=" + step + " elapsedMs=" + elapsedMs);
        }

        /// <summary>The first time a completion could not be consumed (held back): one line per command.</summary>
        internal void NoteCompletionPending(LegacyJumpReceipt r)
        {
            EmitExec("event=jump-complete-pending seq=" + r.Sequence + " id=" + JumpCommandValidator.Hex8(r.RequestId));
        }

        /// <summary>Raises a counter to a value (a high-water mark, e.g. the in-flight depth).</summary>
        internal void CountMax(string key, long value)
        {
            long n;
            counters.TryGetValue(key, out n);
            if (value > n) counters[key] = value;
        }

        private void EmitExec(string line)
        {
            if (note == null) return;
            if (execLogged == ExecLogCapacity)
            {
                execLogged++;
                note("event=jump-exec-log-capped limit=" + ExecLogCapacity);
                return;
            }
            if (execLogged > ExecLogCapacity) return;
            execLogged++;
            note(line);
        }

        /// <summary>Discards the Queued command, if there is one (endpoint re-creation, Dispose). Calling it twice discards once.</summary>
        internal void Expire(string reason)
        {
            if (queued != null && queued.State == LegacyJumpCommandState.Queued) Transition(queued, LegacyJumpCommandState.Discarded, reason);
        }

        /// <summary>
        /// Re-checks the Queued command against the facts of now. The causes, in this order: the scenario boundary moved, the injected TTL ran out (never when the TTL is 0),
        /// the owner (the managed application) is gone, the owner is another one. Returns the reason when the command was discarded, else null.
        /// </summary>
        internal string Sweep(IEndpointSource source, int bvePid, int scenarioEpoch, long ttlMs, long nowMs)
        {
            LegacyJumpReceipt q = queued;
            if (q == null || q.State != LegacyJumpCommandState.Queued) return null;
            if (scenarioEpoch != q.ScenarioEpoch) return Discard(q, "scenario-epoch");
            if (ttlMs > 0 && nowMs - q.ReceivedAtMs > ttlMs) return Discard(q, "ttl");
            string mismatch = OwnerMismatch(source, bvePid, q);
            if (mismatch != null) return Discard(q, mismatch == "telemetry-changed" ? "owner-changed" : mismatch);
            return null;
        }

        /// <summary>
        /// Compares the owner (the managed application) of now with the owner that was recorded when the command was accepted: "owner-lost" when it cannot be resolved,
        /// "owner-changed" when the application instance or process differs, "telemetry-changed" when its Telemetry generation, token or port differs, else null.
        /// Comparison only: the resolved owner is never used as a destination.
        /// </summary>
        internal static string OwnerMismatch(IEndpointSource source, int bvePid, LegacyJumpReceipt q)
        {
            TelemetryEndpoint owner;
            string why;
            bool resolved;
            try { resolved = source.TryResolve(bvePid, out owner, out why); }
            catch { owner = null; resolved = false; }
            if (!resolved || owner == null) return "owner-lost";
            if (!String.Equals(owner.AppInstance, q.AppInstance, StringComparison.Ordinal) || owner.AppProcessId != q.AppPid) return "owner-changed";
            if (owner.Generation != q.TelemetryGeneration || owner.Port != q.TelemetryPort || !LegacyJumpEndpoint.SameBytes(owner.Token, q.TelemetryToken)) return "telemetry-changed";
            return null;
        }

        /// <summary>Discards the Queued receipt (the claim found its facts void). Counted and logged like every other discard.</summary>
        internal string DiscardQueued(LegacyJumpReceipt q, string reason)
        {
            return Discard(q, reason);
        }

        private string Discard(LegacyJumpReceipt q, string reason)
        {
            return Transition(q, LegacyJumpCommandState.Discarded, reason) ? reason : null;
        }

        /// <summary>Copies of the receipts, oldest first.</summary>
        internal LegacyJumpReceipt[] Snapshot()
        {
            LegacyJumpReceipt[] r = new LegacyJumpReceipt[outcomes.Count];
            for (int i = 0; i < r.Length; i++) r[i] = outcomes[i].Copy();
            return r;
        }
    }
}
