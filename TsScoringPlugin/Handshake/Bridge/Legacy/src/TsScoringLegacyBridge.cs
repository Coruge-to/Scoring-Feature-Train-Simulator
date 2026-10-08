using System;
using System.Diagnostics;
using System.Threading;
using AtsEx.PluginHost;
using AtsEx.PluginHost.Plugins;
using AtsEx.PluginHost.Plugins.Extensions;
using BveTypes.ClassWrappers;

// ============================================================================
// PHASE L1 - AtsEX LEGACY adapter of the TS Scoring Bridge (human-facing name: "TS Scoring").
//
// This is the ONLY file of the Legacy Bridge that names an AtsEX / BveTypes type. Everything else is shared with the Current BveEX Bridge
// (ScenarioReadyTracker, ScenarioReadyPublisher, ScenarioObserver, HandshakeProtocol, ObservationLog) or host independent
// (HandshakeControlPlane). The external contract is the Current one: same named objects, same Ready, same ScenarioReady, same
// ScenarioGeneration, same candidate-E meaning. Nothing of the Current contract is weakened and nothing is guessed.
//
// Legacy API mapping (AtsEx.PluginHost 1.0 / BveTypes of the Legacy host)           Current BveEX equivalent
//   IBveHacker.ScenarioOpened(ScenarioOpenedEventArgs)                              same
//   IBveHacker.ScenarioClosed(EventArgs)                                            same
//   IBveHacker.PreviewScenarioCreated / ScenarioCreated(ScenarioCreatedEventArgs)   same
//   IBveHacker.IsScenarioCreated, IBveHacker.Scenario                               same
//   Scenario.TimeManager, Scenario.Vehicle                                          same
//   Scenario.LocationManager (UserVehicleLocationManager).Location : double         Scenario.VehicleLocation.Location
//   IExtensionSet.AllExtensionsLoaded (EventHandler)                                same (observation only)
//   Tick: TickResult Tick(TimeSpan)  (returns ExtensionTickResult)                  void Tick(TimeSpan)
//   no PreviewTick / PostTick on IBveHacker                                         PreviewTick / PostTick (candidate F, diagnostics only)
//
// Candidate E is unchanged: per ScenarioGeneration, at the first Tick where ScenarioOpened and ScenarioCreated were received,
// IsScenarioCreated is true, Scenario / TimeManager / LocationManager (position finite) / Vehicle are readable, the Bridge is not disposed
// and the handshake (Enabled + Ready) is up. PostTick is not used at all (it does not exist in Legacy).
//
// Threads: the control plane (Enabled / Stop / BridgeAvailable / Ready, Dispose requests) runs on its own background thread and touches
// named kernel objects only. BveHacker, Scenario, Vehicle and TimeManager are read on the host's Tick thread only (inside the tracker).
// While the simulation is paused and Tick is silent, turning TS Scoring OFF withdraws ScenarioReady and Ready at once; turning it ON again
// restores Ready at once, and the (kept) ScenarioReady level is published again by the first Tick after that.
//
// No exception ever leaves the constructor, Tick, Dispose or an event handler.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    [Plugin(PluginType.Extension)]
    public class TsScoringLegacyBridgePrototype : AssemblyPluginBase, IExtension
    {
        private static int instances;

        private readonly long loadQpc;
        private readonly long loadUtcTicks;

        private int pid;
        private int instNo;
        private bool firstTickSeen;
        private bool subscribedExtensions;

        private IBveHacker hacker;
        private ScenarioObserver observer;
        private volatile ScenarioReadyTracker tracker;
        private volatile HandshakeControlPlane control;

        // diagnostics: the control plane restored Ready (thread) -> the first Tick afterwards publishes ScenarioReady again
        private long handshakeUpQpc;
        private int handshakeUpPending;

        public TsScoringLegacyBridgePrototype(PluginBuilder builder)
            : base(builder)
        {
            loadQpc = Stopwatch.GetTimestamp();
            loadUtcTicks = DateTime.UtcNow.Ticks;
            instNo = Interlocked.Increment(ref instances);
            Obs("AB", "BRIDGE_CTOR_BEGIN", "ver=" + ObservationLog.Version + " bitness=" + (Environment.Is64BitProcess ? 64 : 32) + " host=AtsExLegacy");

            // The ONLY side effect of loading before the observation wiring: one named event that says "the Bridge exists". Never throws.
            BeginControl(false);

            // Read-only observation wiring, AFTER BridgeAvailable so it can never delay it.
            try { SubscribeObservers(); } catch { }

            // The control thread starts last: the tracker (and its handshake-lost callback target) exists before Ready can appear.
            try { if (control != null) { control.Start(); } } catch { }

            Obs("AB", "BRIDGE_CTOR_END", "sinceCtorBeginMs=" + SinceLoadMs() + " availablePublished=" + AvailableFlag() + " observer=" + (observer != null ? "Y" : "N"));
        }

        public override TickResult Tick(TimeSpan elapsed)
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

            return new ExtensionTickResult();
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
        // Control plane wiring (internal so the offline tests can run it without AtsEX's PluginBuilder)
        // ------------------------------------------------------------------------------------------------------------------

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

        private void OnControlHandshakeUp()
        {
            Interlocked.Exchange(ref handshakeUpQpc, Stopwatch.GetTimestamp());
            Interlocked.Exchange(ref handshakeUpPending, 1);
        }

        /// <summary>Diagnostics: the control plane is back (e.g. TS Scoring ON again during a pause); BVE data is published again on this Tick.</summary>
        private void NoteTickAfterHandshakeUp()
        {
            if (Interlocked.Exchange(ref handshakeUpPending, 0) == 1)
            {
                long since = Stopwatch.GetTimestamp() - Interlocked.Read(ref handshakeUpQpc);
                Obs("A", "LEGACY_TICK_AFTER_HANDSHAKE_UP", "sinceHandshakeUpMs=" + Math.Round(HandshakeProtocol.QpcToMs(since), 1) + " (ScenarioReady is published again from Tick, never from the control thread)");
            }
        }

        private bool HandshakeUp()
        {
            HandshakeControlPlane c = control;
            return c != null && c.HandshakeUp;
        }

        // ------------------------------------------------------------------------------------------------------------------
        // Observation + ScenarioReady (the host independent core is shared with the Current adapter)
        // ------------------------------------------------------------------------------------------------------------------

        private double SinceLoadMs()
        {
            return Math.Round(HandshakeProtocol.QpcToMs(Stopwatch.GetTimestamp() - loadQpc), 1);
        }

        private void Obs(string track, string evt, string detail)
        {
            ObservationLog.Write(track, evt, "inst=" + instNo + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail));
        }

        /// <summary>Creates the scenario observer. Internal so the offline tests can attach fake readers.</summary>
        internal void BeginObservation(Func<int> readIsCreated, Func<string> probeBveInfo)
        {
            observer = new ScenarioObserver(Obs, readIsCreated, probeBveInfo, ReadyFlag, delegate { return Environment.TickCount; });
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
        /// Legacy adapter: one safe read of what ScenarioReady needs, on the Tick thread only. Four references plus one finite-number check on
        /// the vehicle position (Scenario.LocationManager.Location); no value is stored or logged, only yes/no facts. Any null, NaN, Infinity or
        /// exception leaves a short reason code in Failure (exception TYPE name only) and the caller retries on the next Tick.
        /// </summary>
        private BveSnapshot ReadSnapshot()
        {
            IBveHacker h = hacker;
            return BveSnapshotBuilder.Build(
                h == null ? -1 : ReadIsCreatedValue(),
                delegate { return h.Scenario; },
                delegate (object scenario) { return ((Scenario)scenario).TimeManager; },
                delegate (object scenario) { return ((Scenario)scenario).LocationManager; },
                delegate (object location) { return ((UserVehicleLocationManager)location).Location; },
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
            tracker = new ScenarioReadyTracker(Obs, readSnapshot, HandshakeUp, publisher, null);
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
            try { ScenarioReadyTracker t = tracker; if (t != null) { t.OnScenarioOpened(); } } catch { }
        }

        private void OnHackerScenarioClosed(EventArgs e)
        {
            try { if (observer != null) { observer.OnScenarioClosed(); } } catch { }
            try { ScenarioReadyTracker t = tracker; if (t != null) { t.OnScenarioClosed(); } } catch { }
        }

        private void OnHackerPreviewScenarioCreated(ScenarioCreatedEventArgs e)
        {
            try { if (observer != null) { observer.OnPreviewScenarioCreated(); } } catch { }
        }

        private void OnHackerScenarioCreated(ScenarioCreatedEventArgs e)
        {
            try { if (observer != null) { observer.OnScenarioCreated(); } } catch { }
            try { ScenarioReadyTracker t = tracker; if (t != null) { t.OnScenarioCreated(); } } catch { }
        }

        private void OnAllExtensionsLoaded(object sender, EventArgs e)
        {
            try { if (observer != null) { observer.OnAllExtensionsLoaded(); } } catch { }
        }
    }
}
