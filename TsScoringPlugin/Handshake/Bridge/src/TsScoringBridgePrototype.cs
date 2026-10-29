using System;
using System.Diagnostics;
using System.Threading;
using BveEx.PluginHost;
using BveTypes.ClassWrappers;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;

// ============================================================================
// PHASE C1 OBSERVATION BUILD - BveEX Bridge (a minimal BveEX extension), human-facing name: "TS Scoring".
// Phase SI-A7 (M1a): the Phase B handshake no longer runs inside Tick. It is driven by the host independent control plane (HandshakeControlPlane.cs, the same
// source the Legacy adapter uses): one background thread that owns only named kernel objects and plain numbers. Names, rules and the external contract
// (BridgeAvailable at load, Ready while the Caller is enabled and Stop is not set, ScenarioReady only while Ready exists) are unchanged; what changes is WHEN:
// Ready appears within one control poll (20 ms) of Enabled instead of at the next Tick, and it is withdrawn / created again while the simulation is paused.
//
// Phase C1 only ADDS log lines (Shared\ObservationLog.cs) and read-only event subscriptions (Bridge\src\ScenarioObserver.cs):
//   Track B: constructor begin / end, BridgeAvailable create begin / ok, Ready create begin / ok, subscription done, first Tick, Dispose,
//            Ready and BridgeAvailable disposal.
//   Track A: ScenarioOpened, PreviewScenarioCreated, ScenarioCreated, IsScenarioCreated, ScenarioClosed, Tick / PreviewTick / PostTick
//            ordering, and the ScenarioReady CANDIDATES A-F (log lines only; there is NO ScenarioReady event, state or notification).
//
// Contract used: BveEX's public Plugin API only (PluginAttribute, AssemblyPluginBase, IExtension, Tick, Dispose, IBveHacker events).
//
// Lifecycle facts this prototype is built on (BveEX public documentation):
//   * The constructor runs when BveEX loads the extension.
//   * Tick runs "every frame while driving" - i.e. only while a scenario is being run, NOT at BVE start-up and NOT in the menus, and NOT while paused.
//
// Therefore the Bridge announces itself in two steps:
//   1. BridgeAvailable - created and set when BveEX loads the Bridge (constructor, one named event, nothing else).
//      It only means "BveEX and the Bridge exist". It does NOT mean a scenario is loaded or anything is scored.
//   2. Ready - the Caller<->Bridge handshake, created by the control plane while BridgeAvailable is valid, Enabled is set and Stop is not.
//      Ready is NOT ScenarioReady (a future event) and NOT "the scoring app is up".
//
// Behaviour:
//  * Constructor: stores two timestamps and publishes BridgeAvailable (no timer, socket, reflection, window, hook). Afterwards (so BridgeAvailable is never
//    delayed by it) the observation subscriptions are made, and LAST the control thread starts.
//  * Control thread (HandshakeControlPlane): peeks for the Caller's Enabled event while "Searching"; while "Connected" it only watches Enabled / Stop; when the
//    Caller stops (Stop set, or Enabled lost) it withdraws the external ScenarioReady and Ready, and a later enabled cycle is picked up without restarting
//    BVE - also during a pause. When Ready is created again the held ScenarioReady level is published again by that thread (Phase SI-A7), with a new Ready epoch
//    and TickSeenInEpoch = 0. The thread never touches BveHacker, Scenario, Vehicle, TimeManager, the position, the time or the station list.
//  * Tick (BveEX's, cheap): restarts the control thread if it ever ended, feeds the observer and the ScenarioReady tracker (the ONLY place that reads BVE
//    objects and that establishes ScenarioReady).
//  * Dispose (BveEX switched off / ending): ScenarioReady, the control thread, Ready, BridgeInfo and BridgeAvailable are reset and released.
//  * No exception ever leaves the constructor, Tick, Dispose or an event handler.
// BridgeInfo is a PHASE B MEASUREMENT block (removal candidate after Phase B); it exists only while Ready is published.
// It does not contain the current ScoringPlugin, AtsLoggerPlugin, any ATS data, or any code of this repository.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    [Plugin(PluginType.Extension)]
    public class TsScoringBridgePrototype : AssemblyPluginBase, IExtension
    {
        private static int instances;

        private readonly long loadQpc;
        private readonly long loadUtcTicks;

        private int pid;

        // Phase C1 observation (log only)
        private int instNo;
        private IBveHacker hacker;
        private ScenarioObserver observer;
        private bool firstTickSeen;
        private bool subscribedExtensions;

        // Phase C3 ScenarioReady (the host independent core lives in ScenarioReadyTracker; this class is the Current BveEX adapter)
        private volatile ScenarioReadyTracker tracker;

        // Phase SI-A7: the control plane (shared with the Legacy adapter)
        private volatile HandshakeControlPlane control;

        // diagnostics: the control plane restored Ready (thread) -> the held ScenarioReady was published again by that thread; the first Tick afterwards is noted
        private long handshakeUpQpc;
        private int handshakeUpPending;

        public TsScoringBridgePrototype(PluginBuilder builder)
            : base(builder)
        {
            loadQpc = Stopwatch.GetTimestamp();
            loadUtcTicks = DateTime.UtcNow.Ticks;
            instNo = Interlocked.Increment(ref instances);
            Obs("AB", "BRIDGE_CTOR_BEGIN", "ver=" + ObservationLog.Version + " bitness=" + (Environment.Is64BitProcess ? 64 : 32));

            // The ONLY side effect of loading before the observation wiring: one named event that says "the Bridge exists". Never throws.
            BeginControl(false);

            // Read-only observation wiring, AFTER BridgeAvailable so it can never delay it.
            try { SubscribeObservers(); } catch { }

            // The control thread starts last: the tracker (and its handshake callbacks' target) exists before Ready can appear.
            try { if (control != null) { control.Start(); } } catch { }

            Obs("AB", "BRIDGE_CTOR_END", "sinceCtorBeginMs=" + SinceLoadMs() + " availablePublished=" + AvailableFlag() + " observer=" + (observer != null ? "Y" : "N"));
        }

        public override void Tick(TimeSpan elapsed)
        {
            try
            {
                if (!firstTickSeen)
                {
                    firstTickSeen = true;
                    Obs("AB", "BRIDGE_FIRST_TICK", "sinceCtorBeginMs=" + SinceLoadMs() + " availablePublished=" + AvailableFlag() + " ready=" + ReadyFlag() + " isCreated=" + ReadIsCreatedText());
                }

                HandshakeControlPlane c = control;
                if (c != null && !c.IsWorkerAlive)
                {
                    c.Start(); // the control thread ended unexpectedly: restart it (no effect after Dispose)
                }

                if (observer != null)
                {
                    observer.OnTick();
                }
            }
            catch
            {
            }

            try
            {
                NoteTickAfterHandshakeUp();
                ScenarioReadyTracker t = tracker;
                if (t != null)
                {
                    t.OnTick();
                }
            }
            catch
            {
            }
        }

        public override void Dispose()
        {
            Obs("AB", "BRIDGE_DISPOSE_BEGIN", "sinceCtorBeginMs=" + SinceLoadMs() + " ready=" + ReadyFlag() + " availablePublished=" + AvailableFlag());
            try { UnsubscribeObservers(); } catch { }
            try { if (observer != null) { observer.OnDispose(); } } catch { }
            try { ScenarioReadyTracker t = tracker; if (t != null) { t.OnDispose(); } } catch { } // ScenarioReady is cleared and withdrawn before Ready
            try { HandshakeControlPlane c = control; if (c != null) { c.Shutdown("bridge-dispose"); } } catch { }
            try { HandshakeControlPlane c = control; if (c != null) { c.WithdrawAvailability(); } } catch { }
            Obs("AB", "BRIDGE_DISPOSE_END", string.Empty);
        }

        // ------------------------------------------------------------------------------------------------------------------
        // Control plane wiring (internal so the offline tests can run it without BveEX's PluginBuilder)
        // ------------------------------------------------------------------------------------------------------------------

        /// <summary>Creates and sets the BridgeAvailable event once (what the constructor does first). Internal so the offline tests can run it without BveEX's PluginBuilder.</summary>
        internal void PublishAvailability()
        {
            BeginControl(false);
        }

        /// <summary>Creates the control plane and publishes BridgeAvailable. The thread is started by the constructor (or the test).</summary>
        internal void BeginControl(bool startThread)
        {
            try
            {
                if (pid == 0)
                {
                    pid = HandshakeProtocol.CurrentProcessId();
                }

                if (control == null)
                {
                    control = new HandshakeControlPlane(pid, loadQpc, loadUtcTicks, Obs, OnControlHandshakeLost, OnControlHandshakeUp, HandshakeTiming.CallerPollMs);
                }

                control.PublishAvailability();
                if (startThread)
                {
                    control.Start();
                }
            }
            catch
            {
                // BVE must not be affected; the control thread / Tick retries
            }
        }

        /// <summary>The control thread's Ready was withdrawn (TS Scoring OFF / Caller stopped / Dispose): stop the external ScenarioReady publication.</summary>
        private void OnControlHandshakeLost(string reason)
        {
            try
            {
                ScenarioReadyTracker t = tracker;
                if (t != null)
                {
                    t.OnHandshakeLost(reason); // touches the named Event and the state block only, never a BVE object
                }
            }
            catch
            {
            }
        }

        /// <summary>The control thread created Ready (epoch = its ReadyEpoch): the tracker starts the epoch and publishes the HELD ScenarioReady again, with no Tick.</summary>
        private void OnControlHandshakeUp(int readyEpoch)
        {
            Interlocked.Exchange(ref handshakeUpQpc, Stopwatch.GetTimestamp());
            Interlocked.Exchange(ref handshakeUpPending, 1);
            try
            {
                ScenarioReadyTracker t = tracker;
                if (t != null)
                {
                    t.OnHandshakeUp(readyEpoch); // plain numbers and the named Event / state block only, never a BVE object
                }
            }
            catch
            {
            }
        }

        private int ControlReadyEpoch()
        {
            HandshakeControlPlane c = control;
            return c == null ? 0 : c.ReadyEpoch;
        }

        /// <summary>Diagnostics: the first Tick after the control plane restored Ready (e.g. TS Scoring ON again during a pause).</summary>
        private void NoteTickAfterHandshakeUp()
        {
            if (Interlocked.Exchange(ref handshakeUpPending, 0) == 1)
            {
                long since = Stopwatch.GetTimestamp() - Interlocked.Read(ref handshakeUpQpc);
                Obs("A", "CURRENT_TICK_AFTER_HANDSHAKE_UP", "sinceHandshakeUpMs=" + Math.Round(HandshakeProtocol.QpcToMs(since), 1) + " (the held ScenarioReady was already published again by the control thread; this Tick only continues from there)");
            }
        }

        /// <summary>The Phase B handshake is up: TS Scoring is enabled, Stop is not set and Ready is published (a lock free volatile read).</summary>
        private bool HandshakeUp()
        {
            HandshakeControlPlane c = control;
            return c != null && c.HandshakeUp;
        }

        // ------------------------------------------------------------------------------------------------------------------
        // Phase C1 observation (log only; every method below is exception-safe and has no effect on the handshake)
        // ------------------------------------------------------------------------------------------------------------------

        private double SinceLoadMs()
        {
            return Math.Round(HandshakeProtocol.QpcToMs(Stopwatch.GetTimestamp() - loadQpc), 1);
        }

        private void ObsStamped(string track, string evt, string detail, DateTime now, long qpc)
        {
            ObservationLog.WriteStamped(track, evt, "inst=" + instNo + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail), now, qpc);
        }

        private void Obs(string track, string evt, string detail)
        {
            ObservationLog.Write(track, evt, "inst=" + instNo + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail));
        }

        /// <summary>Creates the scenario observer. Internal so the offline tests can attach fake readers.</summary>
        internal void BeginObservation(Func<int> readIsCreated, Func<string> probeBveInfo)
        {
            observer = new ScenarioObserver(Obs, readIsCreated, probeBveInfo, ReadyFlag, delegate { return Environment.TickCount; }); observer.StampedLog = ObsStamped;
        }

        private string ReadyFlag()
        {
            return HandshakeUp() ? "Y" : "N";
        }

        private string AvailableFlag()
        {
            HandshakeControlPlane c = control;
            return c != null && c.IsAvailablePublished ? "Y" : "N";
        }

        private string ReadIsCreatedText()
        {
            if (hacker == null)
            {
                return "n/a";
            }

            int v = ReadIsCreatedValue();
            return v == 1 ? "1" : v == 0 ? "0" : "unreadable";
        }

        private int ReadIsCreatedValue()
        {
            try { return hacker.IsScenarioCreated ? 1 : 0; }
            catch { return -1; }
        }

        /// <summary>
        /// Current BveEX adapter: one safe read of what ScenarioReady needs. Four references plus one finite-number check on the vehicle
        /// position; no value is stored or logged, only yes/no facts. Any null, NaN, Infinity or exception leaves a short reason code in
        /// Failure (exception TYPE name only) and the caller simply retries on the next Tick.
        /// </summary>
        private BveSnapshot ReadSnapshot()
        {
            IBveHacker h = hacker;
            return BveSnapshotBuilder.Build(
                h == null ? -1 : ReadIsCreatedValue(),
                delegate { return h.Scenario; },
                delegate (object scenario) { return ((Scenario)scenario).TimeManager; },
                delegate (object scenario) { return ((Scenario)scenario).VehicleLocation; },
                delegate (object location) { return ((VehicleLocation)location).Location; },
                delegate (object scenario) { return ((Scenario)scenario).Vehicle; });
        }

        /// <summary>null = the BVE objects ScenarioReady needs are readable now (candidate E of the C1 log vocabulary).</summary>
        private string ProbeBveInfo()
        {
            return ReadSnapshot().Failure;
        }

        /// <summary>Creates the ScenarioReady tracker. Internal so the offline tests can attach fake readers and a fake publisher.</summary>
        internal void BeginScenarioReady(Func<BveSnapshot> readSnapshot, IScenarioReadyPublisher publisherOverride)
        {
            if (pid == 0)
            {
                pid = HandshakeProtocol.CurrentProcessId();
            }

            IScenarioReadyPublisher publisher = publisherOverride ?? new ScenarioReadyPublisher(pid);
            tracker = new ScenarioReadyTracker(Obs, readSnapshot, HandshakeUp, publisher, null, ControlReadyEpoch); tracker.StampedLog = ObsStamped;
        }

        private void SubscribeObservers()
        {
            IBveHacker h = null;
            try
            {
                h = BveHacker;
            }
            catch (Exception ex)
            {
                Obs("AB", "SUBSCRIBE_FAIL", "target=BveHacker type=" + ex.GetType().Name);
            }

            if (h == null)
            {
                Obs("AB", "SUBSCRIBE_DONE", "ok=0 reason=no-BveHacker");
                return;
            }

            hacker = h;
            BeginObservation(ReadIsCreatedValue, ProbeBveInfo);
            BeginScenarioReady(ReadSnapshot, null);

            int ok = 0;
            int fail = 0;
            Sub("ScenarioOpened", delegate { h.ScenarioOpened += OnHackerScenarioOpened; }, ref ok, ref fail);
            Sub("ScenarioClosed", delegate { h.ScenarioClosed += OnHackerScenarioClosed; }, ref ok, ref fail);
            Sub("PreviewScenarioCreated", delegate { h.PreviewScenarioCreated += OnHackerPreviewScenarioCreated; }, ref ok, ref fail);
            Sub("ScenarioCreated", delegate { h.ScenarioCreated += OnHackerScenarioCreated; }, ref ok, ref fail);
            Sub("PreviewTick", delegate { h.PreviewTick += OnHackerPreviewTick; }, ref ok, ref fail);
            Sub("PostTick", delegate { h.PostTick += OnHackerPostTick; }, ref ok, ref fail);
            Sub("AllExtensionsLoaded", delegate { Extensions.AllExtensionsLoaded += OnAllExtensionsLoaded; subscribedExtensions = true; }, ref ok, ref fail);

            Obs("AB", "SUBSCRIBE_DONE", "ok=" + ok + " failed=" + fail + " isCreatedAtCtor=" + ReadIsCreatedText());
        }

        private void Sub(string name, Action action, ref int ok, ref int fail)
        {
            try
            {
                action();
                ok++;
                Obs("AB", "SUBSCRIBE", "event=" + name + " result=ok");
            }
            catch (Exception ex)
            {
                fail++;
                Obs("AB", "SUBSCRIBE", "event=" + name + " result=fail type=" + ex.GetType().Name);
            }
        }

        private void UnsubscribeObservers()
        {
            IBveHacker h = hacker;
            if (h == null)
            {
                return;
            }

            try { h.ScenarioOpened -= OnHackerScenarioOpened; } catch { }
            try { h.ScenarioClosed -= OnHackerScenarioClosed; } catch { }
            try { h.PreviewScenarioCreated -= OnHackerPreviewScenarioCreated; } catch { }
            try { h.ScenarioCreated -= OnHackerScenarioCreated; } catch { }
            try { h.PreviewTick -= OnHackerPreviewTick; } catch { }
            try { h.PostTick -= OnHackerPostTick; } catch { }
            if (subscribedExtensions)
            {
                subscribedExtensions = false;
                try { Extensions.AllExtensionsLoaded -= OnAllExtensionsLoaded; } catch { }
            }

            Obs("AB", "UNSUBSCRIBED", string.Empty);
        }

        private void OnHackerScenarioOpened(ScenarioOpenedEventArgs e)
        {
            bool reload = false;
            try { reload = e.IsReload; } catch { }
            try { if (observer != null) { observer.OnScenarioOpened(reload); } } catch { }
            try { if (tracker != null) { tracker.OnScenarioOpened(); } } catch { }
        }

        private void OnHackerScenarioClosed(EventArgs e)
        {
            try { if (observer != null) { observer.OnScenarioClosed(); } } catch { }
            try { if (tracker != null) { tracker.OnScenarioClosed(); } } catch { }
        }

        private void OnHackerPreviewScenarioCreated(ScenarioCreatedEventArgs e)
        {
            try { if (observer != null) { observer.OnPreviewScenarioCreated(); } } catch { }
        }

        private void OnHackerScenarioCreated(ScenarioCreatedEventArgs e)
        {
            try { if (observer != null) { observer.OnScenarioCreated(); } } catch { }
            try { if (tracker != null) { tracker.OnScenarioCreated(); } } catch { }
        }

        private void OnHackerPreviewTick(object sender, EventArgs e)
        {
            try { if (observer != null) { observer.OnPreviewTick(); } } catch { }
        }

        private void OnHackerPostTick(object sender, EventArgs e)
        {
            try { if (observer != null) { observer.OnPostTick(); } } catch { }
            try { if (tracker != null) { tracker.OnPostTick(); } } catch { }
        }

        private void OnAllExtensionsLoaded(object sender, EventArgs e)
        {
            try { if (observer != null) { observer.OnAllExtensionsLoaded(); } } catch { }
        }
    }
}
