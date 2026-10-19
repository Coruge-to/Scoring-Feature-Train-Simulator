using System;
using System.Collections.Generic;
using TSScoringPlugin.DataPlane;

// ============================================================================
// PHASE PID-D4 / LEGACY JUMP 2A-ALPHA - the command books of the Legacy Jump control plane.
//
// What it holds: one receipt per datagram the plane read (Rejected, Queued or Discarded), the queue of depth 1 (the newest accepted command wins), the single
// transition point that takes a receipt out of Queued, the discard reasons and the counters. A receipt keeps the text and the request id OPAQUELY: nothing here
// interprets a command, and nothing here can run one. There is no Executing state (decision D-6): a Queued command ends Discarded, or is still Queued when the
// plane stops. The time expiry exists only when a TTL is injected (the product default is none, decision D-2).
//
// Host independent, BCL only. NOT thread safe: only the control plane touches it, always under its single gate (written at the top of LegacyJumpControlPlane.cs).
// Written in C# 5 syntax on purpose (the offline tests compile the product files directly).
// ============================================================================
namespace TSScoringPlugin.Telemetry
{
    /// <summary>Rejected: failed validation, nothing queued. Queued: accepted, waiting. Discarded: left the queue without any effect. There is no further state.</summary>
    internal enum LegacyJumpCommandState
    {
        Rejected = 0,
        Queued = 1,
        Discarded = 2
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
        private long sequence;
        private int logged;

        internal LegacyJumpCommandQueue(Action<string> note)
        {
            this.note = note;
        }

        /// <summary>The newest accepted receipt. It may have been discarded since: look at its State.</summary>
        internal LegacyJumpReceipt Queued { get { return queued; } }

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
        }

        /// <summary>The ONLY place where a receipt leaves Queued. Anything else is an illegal transition (counted; the tests require 0).</summary>
        internal bool Transition(LegacyJumpReceipt r, LegacyJumpCommandState to, string reason)
        {
            if (r.State != LegacyJumpCommandState.Queued)
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
            TelemetryEndpoint owner;
            string why;
            bool resolved;
            try { resolved = source.TryResolve(bvePid, out owner, out why); }
            catch { owner = null; resolved = false; }
            if (!resolved || owner == null) return Discard(q, "owner-lost");
            if (!String.Equals(owner.AppInstance, q.AppInstance, StringComparison.Ordinal) || owner.AppProcessId != q.AppPid
                || owner.Generation != q.TelemetryGeneration || owner.Port != q.TelemetryPort || !LegacyJumpEndpoint.SameBytes(owner.Token, q.TelemetryToken))
            {
                return Discard(q, "owner-changed");
            }
            return null;
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
