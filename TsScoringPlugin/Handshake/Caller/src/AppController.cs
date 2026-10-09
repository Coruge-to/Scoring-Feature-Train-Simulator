// ============================================================================
// PHASE E1 - the AppController DRY-RUN of one Caller instance (a pure state machine).
//
// It decides WHEN a future application start / stop would be requested, and nothing else. A request is only a decision: this file (and the
// whole Caller) starts nothing, holds no handle, opens no kernel object, sends nothing and controls no HUD or scoring. The session writes the
// decision to the observation log (APP_START_REQUEST / APP_STOP_REQUEST, always dryRun=yes); later phases will act on the same decisions.
//
// Input: the DrivingActive result of the Caller (Caller\src\DrivingActivityState.cs is read-only here), the published state of the scenario
// and its ScenarioGeneration. No clock, no I/O, no thread, no lock, no log: every rule is testable offline.
//
// START request: exactly ONE per ScenarioGeneration - at the first DrivingActive ON of that generation (DrivingActive already means "published
//   and a fresh Tick after the publication"; it is re-checked here, and generation 0 = "none yet" never qualifies).
//   No further request in the same generation: a repeated ON after a soft OFF, a Pause, a short Tick stop, the scenario-selection screen of the
//   legacy host, an ON / OFF oscillation. The first such suppressed ON of a generation is reported once (Suppressed); it is never repeated.
//   A different ScenarioGeneration carries nothing over from the old one: its first DrivingActive ON is a new request (new number).
// STOP request: exactly ONE per Caller instance, when Dispose begins - and only if a start request was made (nothing was "started" otherwise).
//   Nothing else produces a stop request: not a soft OFF, not a hard OFF, not the withdrawal of the scenario, not a new generation.
// After Dispose began the controller is closed: it never produces another request.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    /// <summary>What the controller decided in one observation.</summary>
    internal enum AppAction
    {
        None = 0,

        /// <summary>A start request was recorded (dry-run).</summary>
        StartRequested,

        /// <summary>A repeated DrivingActive ON in a generation that already has its start request; reported once per generation.</summary>
        StartSuppressed,

        /// <summary>The stop request was recorded (dry-run).</summary>
        StopRequested,

        /// <summary>Dispose began but no start request had ever been made: there is nothing to stop.</summary>
        StopNotRequired,
    }

    internal static class AppRequestReasons
    {
        public const string FirstDrivingOn = "first-driving-on";
        public const string CallerDispose = "caller-dispose";
        public const string AlreadyRequestedForGeneration = "already-requested-for-generation";
        public const string NoStartRequest = "no-start-request";
    }

    /// <summary>The result of one observation. RequestNumber is the 1-based number of the start / stop request (for StartSuppressed: of the request that already exists).</summary>
    internal struct AppStep
    {
        public AppAction Action;
        public int RequestNumber;
        public int ScenarioGeneration;
    }

    internal sealed class AppController
    {
        private int startCount;
        private int stopCount;
        private int suppressedCount;
        private int requestedGeneration;       // generation of the latest start request (0 = none)
        private int suppressReportedGeneration; // generation whose first suppression was already reported (0 = none)
        private bool previousActive;
        private bool closed;

        public int StartRequestCount { get { return startCount; } }

        public int StopRequestCount { get { return stopCount; } }

        /// <summary>Repeated ONs inside an already requested generation (all of them, reported or not).</summary>
        public int SuppressedCount { get { return suppressedCount; } }

        public int LastRequestedGeneration { get { return requestedGeneration; } }

        public bool Closed { get { return closed; } }

        /// <param name="drivingActive">DrivingActive after this step's evaluation.</param>
        /// <param name="scenarioPublished">The Caller's own reading of the scenario publication (the same value DrivingActive was given).</param>
        /// <param name="scenarioGeneration">ScenarioGeneration of that reading.</param>
        public AppStep Observe(bool drivingActive, bool scenarioPublished, int scenarioGeneration)
        {
            AppStep r = new AppStep();
            if (closed)
            {
                previousActive = false;
                return r;
            }

            bool eligible = drivingActive && scenarioPublished && scenarioGeneration > 0;
            bool rising = eligible && !previousActive;
            previousActive = eligible;
            if (!eligible)
            {
                return r; // OFF of any kind (soft, hard, withdrawal) changes nothing here: no stop, and the request memory stays
            }

            if (startCount > 0 && scenarioGeneration == requestedGeneration)
            {
                if (rising)
                {
                    suppressedCount++;
                    if (suppressReportedGeneration != scenarioGeneration)
                    {
                        suppressReportedGeneration = scenarioGeneration;
                        r.Action = AppAction.StartSuppressed;
                        r.RequestNumber = startCount;
                        r.ScenarioGeneration = scenarioGeneration;
                    }
                }

                return r;
            }

            startCount++;
            requestedGeneration = scenarioGeneration;
            r.Action = AppAction.StartRequested;
            r.RequestNumber = startCount;
            r.ScenarioGeneration = scenarioGeneration;
            return r;
        }

        /// <summary>Dispose began. The first call closes the controller; every later call (another path observing the same Dispose) returns None.</summary>
        public AppStep OnDispose()
        {
            AppStep r = new AppStep();
            if (closed)
            {
                return r;
            }

            closed = true;
            previousActive = false;
            if (startCount == 0)
            {
                r.Action = AppAction.StopNotRequired;
                return r;
            }

            stopCount++;
            r.Action = AppAction.StopRequested;
            r.RequestNumber = stopCount;
            r.ScenarioGeneration = requestedGeneration;
            return r;
        }
    }
}
