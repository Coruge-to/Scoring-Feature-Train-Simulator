using System;
using System.Diagnostics;

// ============================================================================
// PHASE C3 - ScenarioReady life-cycle (host independent core).
//
// ScenarioReady means: "inside BVE a valid scenario has been built and the BVE references TS Scoring needs can be read safely on Tick".
// It is NOT "the driving screen is visible": returning to the title screen produces no ScenarioClosed, so ScenarioReady stays true there,
// and the title-screen return is never guessed from TICK_GAP, Tick speed, elapsed time or IsScenarioCreated alone.
// A future HUD / scoring pause, if needed, is a separate state (DrivingActive) for Phase D.
//
// Establishment (Phase C2 candidate E), per ScenarioGeneration, at the FIRST Tick where ALL of these hold:
//   ScenarioOpened received, ScenarioCreated received, IsScenarioCreated == true, Scenario / TimeManager / VehicleLocation / Vehicle
//   references readable, VehicleLocation a finite number, Bridge not disposed, TS Scoring enabled and the Phase B handshake (Ready) up.
//   PostTick is NOT a condition (AtsEX Legacy has none). Candidate F is diagnostics only and never sets ScenarioReady.
//
// Phase SI-A6 adds a LOAD MARKER next to the level (ScenarioState.LoadInfo, same seqlock write): bit0 "ScenarioCreated of this generation was received"
// (set by the event itself, so it is published without any Tick - a Pause that inherits a reload never ticks), bit1 "the first Tick of this generation after
// ScenarioCreated was received". Both are 0 right after ScenarioOpened / ScenarioClosed. The marker never influences ScenarioReady, its establishment or its clearing.
//
// Clearing: ScenarioClosed, the safe reset at the next ScenarioOpened (BEFORE the generation number is increased), Bridge Dispose.
// Publication (named Event + state block) additionally stops while the handshake is down (TS Scoring OFF / Caller stopped) and is
// published again at once when the handshake is back (ScenarioReady is a LEVEL, not an edge); the level itself is not cleared by that.
// Not clearing: Pause, Tick stop / TICK_GAP, title-screen return, IsScenarioCreated alone, the Phase B Ready staying up, isReload, one
// transient failure to read a reference (only the failures BEFORE establishment are retried on the next Tick).
//
// This class knows no BveEX type: the Current adapter (TsScoringBridgePrototype) feeds it plain calls and three small delegates, so an
// AtsEX Legacy adapter can reuse it unchanged. Every entry point is exception safe and silent unless something changes.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    /// <summary>One safe read of the BVE objects (filled by the host adapter; no names or values are carried, only yes/no facts).</summary>
    internal struct BveSnapshot
    {
        public int IsScenarioCreated;          // 1 true, 0 false, -1 unreadable
        public bool ScenarioRef;
        public bool TimeManagerRef;
        public bool VehicleLocationRef;
        public bool VehicleLocationFinite;     // the position is a finite number (not NaN / Infinity)
        public bool VehicleRef;
        public string Failure;                 // null = every reference was read; otherwise a short reason code (never a message text)

        public bool Usable { get { return IsScenarioCreated == 1 && string.IsNullOrEmpty(Failure); } }

        public string PendingReason()
        {
            if (!string.IsNullOrEmpty(Failure))
            {
                return Failure;
            }

            return IsScenarioCreated == 1 ? null : IsScenarioCreated == 0 ? "not-created" : "created-unreadable";
        }
    }

    /// <summary>
    /// Host independent evaluation of one BVE read: the host adapter supplies tiny accessors, this decides what counts as usable.
    /// Null, NaN, Infinity or an exception never count as readable; each leaves a short reason code (exception TYPE name only) and the
    /// caller retries on the next Tick. No value is kept or logged: only whether a reference exists and the position is a finite number.
    /// </summary>
    internal static class BveSnapshotBuilder
    {
        internal static BveSnapshot Build(
            int isScenarioCreated,
            Func<object> getScenario,
            Func<object, object> getTimeManager,
            Func<object, object> getVehicleLocation,
            Func<object, double> getPosition,
            Func<object, object> getVehicle)
        {
            BveSnapshot s = new BveSnapshot();
            s.IsScenarioCreated = isScenarioCreated;
            if (isScenarioCreated != 1)
            {
                return s; // before the scenario exists BVE's objects are not touched at all
            }

            try
            {
                object scenario = getScenario();
                if (ReferenceEquals(scenario, null))
                {
                    s.Failure = "scenario-null";
                    return s;
                }

                s.ScenarioRef = true;

                if (ReferenceEquals(getTimeManager(scenario), null))
                {
                    s.Failure = "timemanager-null";
                    return s;
                }

                s.TimeManagerRef = true;

                object location = getVehicleLocation(scenario);
                if (ReferenceEquals(location, null))
                {
                    s.Failure = "vehiclelocation-null";
                    return s;
                }

                s.VehicleLocationRef = true;

                double position = getPosition(location);
                if (double.IsNaN(position) || double.IsInfinity(position))
                {
                    s.Failure = "vehiclelocation-nonfinite";
                    return s;
                }

                s.VehicleLocationFinite = true;

                if (ReferenceEquals(getVehicle(scenario), null))
                {
                    s.Failure = "vehicle-null";
                    return s;
                }

                s.VehicleRef = true;
                return s;
            }
            catch (Exception ex)
            {
                s.Failure = "exc-" + ex.GetType().Name;
                return s;
            }
        }
    }

    /// <summary>The outside world of the tracker: the named Event + the state block. Replaceable by a fake in the offline tests.</summary>
    internal interface IScenarioReadyPublisher
    {
        bool IsOpen { get; }
        void Open(int generation, bool ready);
        void Update(int generation, bool ready);
        void Close();
    }

    /// <summary>
    /// Phase SI-A6: a publisher that also carries the load marker of the generation (ScenarioState.LoadInfo). The tracker uses it when the publisher offers it
    /// (the real publisher does) and falls back to the two-argument form otherwise, so every fake publisher of the earlier phases keeps working unchanged.
    /// </summary>
    internal interface IScenarioLoadPublisher : IScenarioReadyPublisher
    {
        void OpenWithLoad(int generation, bool ready, int loadInfo);
        void UpdateWithLoad(int generation, bool ready, int loadInfo);
    }

    internal sealed class ScenarioReadyTracker
    {
        /// <summary>Ticks (with the handshake up, after ScenarioCreated) without establishment before the stall diagnostics are written.</summary>
        internal const int EStallTicks = 300;

        private readonly object gate = new object();
        private readonly Action<string, string, string> log;
        private readonly Func<BveSnapshot> read;
        private readonly Func<bool> handshakeUp;
        private readonly IScenarioReadyPublisher publisher;
        private readonly Func<long> nowMs;

        private int generation;                // 0 = nothing opened yet
        private bool disposed;
        private bool generationOpen;           // ScenarioOpened seen and not yet closed
        private bool createdSeen;
        private bool level;                    // ScenarioReady of the current generation
        private bool publishedLevel;           // what the outside currently shows (false when nothing is published)
        private bool publishing;               // the publisher is open (Event + state block exist)
        private bool publishFailLogged;        // one SR_PUBLISH_FAIL line per failing stretch (the Tick retries silently)
        private long ticksTotal;
        private long openedAtMs;

        // Phase SI-A6: the load marker of the CURRENT generation (ScenarioState.LoadCreated / LoadTickSeen). Reset by ScenarioOpened and ScenarioClosed, set by
        // ScenarioCreated (an event, so it needs no Tick) and by the first Tick after it. publishedLoad is what the outside currently shows.
        private int loadInfo;
        private int publishedLoad;

        // per generation diagnostics
        private int waitingTicks;
        private string lastPending;
        private bool handshakeWaitLogged;
        private bool stallLogged;
        private bool fDiagLogged;

        // counters for the offline tests
        private int establishedCount;
        private int clearedCount;

        internal ScenarioReadyTracker(Action<string, string, string> log, Func<BveSnapshot> read, Func<bool> handshakeUp, IScenarioReadyPublisher publisher, Func<long> nowMs)
        {
            this.log = log ?? delegate { };
            this.read = read ?? delegate { BveSnapshot none = new BveSnapshot(); none.IsScenarioCreated = -1; none.Failure = "no-reader"; return none; };
            this.handshakeUp = handshakeUp ?? delegate { return false; };
            this.publisher = publisher;
            this.nowMs = nowMs ?? delegate { return Stopwatch.GetTimestamp() * 1000 / Stopwatch.Frequency; };
        }

        internal int ScenarioGeneration { get { lock (gate) { return generation; } } }
        internal bool IsScenarioReady { get { lock (gate) { return level && !disposed; } } }
        internal bool IsPublished { get { lock (gate) { return publishing && publishedLevel; } } }
        internal bool IsPublishing { get { lock (gate) { return publishing; } } }
        internal int EstablishedCount { get { lock (gate) { return establishedCount; } } }
        internal int ClearedCount { get { lock (gate) { return clearedCount; } } }

        // ---- host events ----

        /// <summary>BveEX ScenarioOpened. Clears first (safe reset), then opens the next generation.</summary>
        public void OnScenarioOpened()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (disposed)
                    {
                        return;
                    }

                    bool hadLevel = level;
                    bool wasOpen = generationOpen;
                    loadInfo = 0;                    // the load marker never outlives its generation (it goes with the reset below)
                    if (hadLevel)
                    {
                        ClearLocked("opened-reset"); // 1. reset: the previous generation can no longer be seen as ScenarioReady
                    }

                    int previous = generation;
                    generation = ScenarioGenerationRule.Next(generation); // 2. only then the number moves
                    if (previous == int.MaxValue)
                    {
                        Emit("SR_GENERATION_WRAPPED", "from=" + previous + " to=" + generation);
                    }

                    generationOpen = true;
                    createdSeen = false;
                    level = false;
                    waitingTicks = 0;
                    lastPending = null;
                    handshakeWaitLogged = false;
                    stallLogged = false;
                    fDiagLogged = false;
                    openedAtMs = nowMs();
                    Emit("SR_OPENED", Gen() + " previous=" + previous + " levelClearedFirst=" + (hadLevel ? "yes" : "no") + " previousGenerationWasOpen=" + (wasOpen ? "yes" : "no") + " handshake=" + Handshake());
                    PushStateLocked();
                }
            });
        }

        public void OnScenarioCreated()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (disposed)
                    {
                        return;
                    }

                    if (!generationOpen)
                    {
                        // ScenarioCreated without a ScenarioOpened of ours (late attach): the generation rule needs both, so no ScenarioReady.
                        Emit("SR_CREATED_WITHOUT_OPEN", Gen() + " (ScenarioReady needs ScenarioOpened and ScenarioCreated of the same generation; waiting for the next ScenarioOpened)");
                        return;
                    }

                    createdSeen = true;
                    loadInfo |= ScenarioState.LoadCreated;   // Phase SI-A6: published at once (BVE's own event thread; no Tick is needed for this)
                    SyncLoadLocked();
                    Emit("SR_CREATED", Gen() + " handshake=" + Handshake());
                }
            });
        }

        /// <summary>BveEX ScenarioClosed: the only normal way ScenarioReady ends.</summary>
        public void OnScenarioClosed()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (disposed)
                    {
                        return;
                    }

                    bool hadLevel = level;
                    loadInfo = 0;
                    if (hadLevel)
                    {
                        ClearLocked("closed");
                    }
                    else
                    {
                        Emit("SR_CLOSED_NO_LEVEL", Gen() + " generationOpen=" + (generationOpen ? "yes" : "no"));
                    }

                    generationOpen = false;
                    createdSeen = false;
                    level = false;
                    PushStateLocked(); // the block keeps the generation number, level 0
                }
            });
        }

        /// <summary>The extension's own Tick. The only place where establishment is decided.</summary>
        public void OnTick()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (disposed)
                    {
                        return;
                    }

                    ticksTotal++;
                    bool up = SafeHandshake();

                    // The publication follows the handshake: it opens as soon as Ready is up (generation visible, level 0 or the kept level),
                    // is retried when a publish failed, and is withdrawn while the handshake is down.
                    if (up && (!publishing || (level && !publishedLevel)))
                    {
                        PublishLocked(!publishing ? (level ? "handshake-back" : "handshake-up") : "retry");
                    }
                    else if (!up && publishing)
                    {
                        WithdrawLocked("handshake-down");
                    }

                    if (generationOpen && createdSeen && (loadInfo & ScenarioState.LoadTickSeen) == 0)
                    {
                        loadInfo |= ScenarioState.LoadTickSeen;  // Phase SI-A6: the first Tick of this generation after ScenarioCreated
                    }

                    SyncLoadLocked();

                    if (level)
                    {
                        return; // established: nothing is read any more (a transient reference failure must not clear it)
                    }

                    if (!generationOpen || !createdSeen)
                    {
                        return;
                    }

                    if (!up)
                    {
                        if (!handshakeWaitLogged)
                        {
                            handshakeWaitLogged = true;
                            Emit("SR_WAIT", Gen() + " reason=handshake-not-up (TS Scoring is off or Ready is not established yet)");
                        }

                        return;
                    }

                    waitingTicks++;
                    BveSnapshot snapshot = ReadSafe();
                    string pending = snapshot.PendingReason();
                    if (pending == null)
                    {
                        EstablishLocked(snapshot);
                        return;
                    }

                    if (pending != lastPending)
                    {
                        lastPending = pending;
                        Emit("SR_PENDING", Gen() + " reason=" + pending + " tickInGen=" + waitingTicks + " tick=" + ticksTotal);
                    }

                    if (waitingTicks >= EStallTicks && !stallLogged)
                    {
                        stallLogged = true;
                        Emit("SR_E_STALLED", Gen() + " ticks=" + waitingTicks + " lastReason=" + pending + " (the first PostTick will be probed for diagnostics only; candidate F never sets ScenarioReady)");
                    }
                }
            });
        }

        /// <summary>BveEX PostTick: DIAGNOSTICS ONLY, current host only. Writes what candidate F would have seen when E has not been established for a long time.</summary>
        public void OnPostTick()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (disposed || level || !stallLogged || fDiagLogged || !generationOpen || !createdSeen)
                    {
                        return;
                    }

                    fDiagLogged = true;
                    BveSnapshot f = ReadSafe();
                    Emit("SR_F_DIAG", Gen() + " " + Facts(f) + " usable=" + (f.Usable ? "yes" : "no") + " (diagnostic only: ScenarioReady is not set from PostTick)");
                }
            });
        }

        /// <summary>The Phase B handshake went away (Caller stopped / TS Scoring off / Release): stop publishing; the level is kept.</summary>
        public void OnHandshakeLost(string reason)
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (publishing)
                    {
                        WithdrawLocked(reason);
                    }
                }
            });
        }

        /// <summary>Bridge Dispose (BveEX off / BVE ending): clear, close everything, ignore every later call.</summary>
        public void OnDispose()
        {
            Safe(delegate
            {
                lock (gate)
                {
                    if (disposed)
                    {
                        return;
                    }

                    if (level)
                    {
                        ClearLocked("bridge-dispose");
                    }

                    level = false;
                    generationOpen = false;
                    createdSeen = false;
                    if (publishing)
                    {
                        WithdrawLocked("bridge-dispose");
                    }

                    disposed = true;
                    Emit("SR_DISPOSED", Gen() + " established=" + establishedCount + " cleared=" + clearedCount + " ticks=" + ticksTotal);
                }
            });
        }

        // ---- internals (gate held) ----

        private void EstablishLocked(BveSnapshot s)
        {
            level = true;
            establishedCount++;
            Emit("SR_ESTABLISHED", Gen() + " candidate=E tick=" + ticksTotal + " tickInGen=" + waitingTicks + " sinceOpenedMs=" + (nowMs() - openedAtMs) + " atUtc=" + DateTime.UtcNow.ToString("HH:mm:ss.fff") + " " + Facts(s) + " handshake=" + Handshake());
            PublishLocked("established");
        }

        /// <summary>Ends the level of the current generation. Publication (if any) shows level 0 at once.</summary>
        private void ClearLocked(string reason)
        {
            bool was = level;
            level = false;
            if (was)
            {
                clearedCount++;
            }

            if (publishing)
            {
                try
                {
                    UpdatePublisherLocked(false);
                    publishedLevel = false;
                }
                catch (Exception ex)
                {
                    Emit("SR_PUBLISH_FAIL", Gen() + " step=clear type=" + ex.GetType().Name);
                }
            }

            Emit("SR_CLEARED", Gen() + " reason=" + reason + " wasReady=" + (was ? "yes" : "no") + " clearedCount=" + clearedCount);
        }

        /// <summary>Makes the current (generation, level) visible: opens the publisher when needed. Retried on later Ticks if it fails.</summary>
        private void PublishLocked(string why)
        {
            if (publisher == null)
            {
                return;
            }

            try
            {
                if (!publishing)
                {
                    IScenarioLoadPublisher withLoad = publisher as IScenarioLoadPublisher;
                    if (withLoad != null)
                    {
                        withLoad.OpenWithLoad(generation, level, loadInfo);
                        publishedLoad = loadInfo;
                    }
                    else
                    {
                        publisher.Open(generation, level);
                    }

                    publishing = true;
                }
                else
                {
                    UpdatePublisherLocked(level);
                }

                publishedLevel = level;
                Emit("SR_PUBLISHED", Gen() + " level=" + (level ? "1" : "0") + " why=" + why);
            }
            catch (Exception ex)
            {
                Emit("SR_PUBLISH_FAIL", Gen() + " step=publish type=" + ex.GetType().Name);
            }
        }

        private void WithdrawLocked(string reason)
        {
            try
            {
                if (publisher != null)
                {
                    publisher.Close();
                }
            }
            catch (Exception ex)
            {
                Emit("SR_PUBLISH_FAIL", Gen() + " step=close type=" + ex.GetType().Name);
            }

            publishing = false;
            publishedLevel = false;
            Emit("SR_WITHDRAWN", Gen() + " reason=" + reason + " levelKept=" + (level ? "yes" : "no"));
        }

        /// <summary>Keeps the visible generation number current while the publisher is open (level taken from the tracker).</summary>
        private void PushStateLocked()
        {
            if (!publishing || publisher == null)
            {
                return;
            }

            try
            {
                UpdatePublisherLocked(level);
                publishedLevel = level;
            }
            catch (Exception ex)
            {
                Emit("SR_PUBLISH_FAIL", Gen() + " step=push type=" + ex.GetType().Name);
            }
        }

        /// <summary>One publisher update with the current generation, the given level and (when the publisher carries it) the load marker.</summary>
        private void UpdatePublisherLocked(bool ready)
        {
            IScenarioLoadPublisher withLoad = publisher as IScenarioLoadPublisher;
            if (withLoad != null)
            {
                withLoad.UpdateWithLoad(generation, ready, loadInfo);
                publishedLoad = loadInfo;
            }
            else
            {
                publisher.Update(generation, ready);
            }
        }

        /// <summary>Phase SI-A6: writes the state again when only the load marker changed since the last write (ScenarioCreated, the first Tick). No write otherwise.</summary>
        private void SyncLoadLocked()
        {
            if (publishing && publisher is IScenarioLoadPublisher && publishedLoad != loadInfo)
            {
                PushStateLocked();      // a publisher without the marker (every fake of the earlier phases) is never written to because of it
            }
        }

        private BveSnapshot ReadSafe()
        {
            try
            {
                return read();
            }
            catch (Exception ex)
            {
                BveSnapshot failed = new BveSnapshot();
                failed.IsScenarioCreated = -1;
                failed.Failure = "exc-" + ex.GetType().Name;
                return failed;
            }
        }

        private bool SafeHandshake()
        {
            try { return handshakeUp(); }
            catch { return false; }
        }

        private string Handshake()
        {
            return SafeHandshake() ? "up" : "down";
        }

        private static string Facts(BveSnapshot s)
        {
            return "scenarioRef=" + (s.ScenarioRef ? "ok" : "no")
                + " timeManagerRef=" + (s.TimeManagerRef ? "ok" : "no")
                + " vehicleLocationFinite=" + (s.VehicleLocationFinite ? "yes" : "no")
                + " vehicleRef=" + (s.VehicleRef ? "ok" : "no")
                + " isScenarioCreated=" + (s.IsScenarioCreated == 1 ? "1" : s.IsScenarioCreated == 0 ? "0" : "unreadable")
                + (!string.IsNullOrEmpty(s.Failure) ? " failure=" + s.Failure : string.Empty);
        }

        private string Gen()
        {
            return "ScenarioGeneration=" + generation;
        }

        private void Emit(string evt, string detail)
        {
            if (evt == "SR_PUBLISH_FAIL")
            {
                if (publishFailLogged)
                {
                    return;
                }

                publishFailLogged = true;
            }
            else if (evt == "SR_PUBLISHED")
            {
                publishFailLogged = false;
            }

            try { log("A", evt, detail); }
            catch { }
        }

        private static void Safe(Action action)
        {
            try { action(); }
            catch { }
        }
    }
}
