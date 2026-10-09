// ============================================================================
// PHASE D1 - the DrivingActive state of one Caller instance (a pure state machine).
//
//   DrivingActive = CallerEnabled AND CallerNotDisposed AND ScenarioReadyPublished AND TickFresh
//                   AND a Tick observed AFTER the ScenarioReady publication was first seen
//
// No clock, no I/O, no thread, no log: the caller passes the inputs and the measured Tick age, so every rule is testable offline. Nothing in
// the Caller consumes the result yet (it is a read-only internal state; later phases may use it).
//
// Hard OFF (at once, whatever the Tick age): Dispose began, Caller disabled, ScenarioReady not published.
// Soft OFF: the last Tick is MORE than AppProtocol.TickStaleOffMs (2000 ms) old. A soft OFF only says "BVE is not running frames"
//           (a long menu operation, a hang); it is not the end of the scenario session.
// Hysteresis: OFF -> ON at a Tick age <= 250 ms (inclusive); ON -> OFF only above 2000 ms; in between the previous state is kept.
//
// Arming (Phase D1-OBS finding C-1): when ScenarioReady is first seen published the Tick sequence at that moment is recorded (armSeq). Only a
// Tick with a sequence beyond armSeq counts, so a Tick that arrived before the publication (even within the 20 ms monitor period) never turns
// DrivingActive ON, and a republication alone never does either. Withdrawal of ScenarioReady, Dispose and disabling discard the arm; a new
// ScenarioGeneration under a still-published ScenarioReady re-arms. A new Caller instance starts unarmed and OFF.
// The sequence is a 64-bit counter compared by wrap-around subtraction, so an overflow is harmless.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    /// <summary>Why DrivingActive went OFF. Hard = the scenario session ended for the Caller; Soft = only the Tick stopped.</summary>
    internal enum DrivingOffReason
    {
        None = 0,
        Dispose,
        Disabled,
        ScenarioReadyOff,
        TickStale,
    }

    internal static class DrivingOffReasons
    {
        public static string Name(DrivingOffReason reason)
        {
            switch (reason)
            {
                case DrivingOffReason.Dispose:
                    return "dispose";
                case DrivingOffReason.Disabled:
                    return "disabled";
                case DrivingOffReason.ScenarioReadyOff:
                    return "scenario-ready-off";
                case DrivingOffReason.TickStale:
                    return "tick-stale";
                default:
                    return "none";
            }
        }

        public static bool IsHard(DrivingOffReason reason)
        {
            return reason == DrivingOffReason.Dispose || reason == DrivingOffReason.Disabled || reason == DrivingOffReason.ScenarioReadyOff;
        }
    }

    /// <summary>The result of one evaluation. Changed is true only on the evaluation in which the state flipped.</summary>
    internal struct DrivingStep
    {
        public bool Changed;
        public bool Active;
        public DrivingOffReason OffReason;
    }

    internal sealed class DrivingActivityState
    {
        private bool active;
        private bool armed;
        private long armSeq;
        private int armGeneration;

        public bool Active { get { return active; } }

        public bool Armed { get { return armed; } }

        public long ArmSequence { get { return armSeq; } }

        /// <param name="enabled">The Caller is started and not disabled.</param>
        /// <param name="notDisposed">Dispose has not begun.</param>
        /// <param name="scenarioReadyPublished">The Caller's own reading of ScenarioReady (unchanged reader).</param>
        /// <param name="scenarioGeneration">ScenarioGeneration of that reading.</param>
        /// <param name="tickSeq">Tick count of this Caller instance, read AFTER ScenarioReady was read.</param>
        /// <param name="tickAgeMs">Age of the last Tick in ms; negative = no Tick seen yet.</param>
        public DrivingStep Evaluate(bool enabled, bool notDisposed, bool scenarioReadyPublished, int scenarioGeneration, long tickSeq, double tickAgeMs)
        {
            DrivingStep r = new DrivingStep();

            if (!(enabled && notDisposed && scenarioReadyPublished))
            {
                armed = false; // the arm belongs to one publication: withdrawal, Dispose and disabling discard it
                if (active)
                {
                    active = false;
                    r.Changed = true;
                    r.OffReason = !notDisposed ? DrivingOffReason.Dispose : !enabled ? DrivingOffReason.Disabled : DrivingOffReason.ScenarioReadyOff;
                }

                r.Active = active;
                return r;
            }

            if (!armed)
            {
                // ScenarioReady has just been seen published: remember where the Tick count stands. Never ON in this evaluation.
                armed = true;
                armSeq = tickSeq;
                armGeneration = scenarioGeneration;
                r.Active = active;
                return r;
            }

            if (scenarioGeneration != armGeneration)
            {
                // another scenario under a publication that was never seen withdrawn: Ticks of the old one are not used
                armSeq = tickSeq;
                armGeneration = scenarioGeneration;
                if (active)
                {
                    active = false;
                    r.Changed = true;
                    r.OffReason = DrivingOffReason.ScenarioReadyOff;
                }

                r.Active = active;
                return r;
            }

            bool tickSeen = tickAgeMs >= 0;
            if (active)
            {
                if (tickSeen && tickAgeMs > AppProtocol.TickStaleOffMs)
                {
                    active = false;
                    r.Changed = true;
                    r.OffReason = DrivingOffReason.TickStale;
                }
            }
            else if (tickSeen && NewerThan(tickSeq, armSeq) && tickAgeMs <= AppProtocol.TickFreshOnMs)
            {
                active = true;
                r.Changed = true;
            }

            r.Active = active;
            return r;
        }

        /// <summary>True when a is beyond b in a 64-bit counter that may wrap around (a Tick count that overflowed is still newer).</summary>
        internal static bool NewerThan(long a, long b)
        {
            return unchecked(a - b) > 0;
        }
    }
}
