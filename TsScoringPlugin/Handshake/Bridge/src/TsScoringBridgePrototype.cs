using System;
using System.Diagnostics;
using System.IO.MemoryMappedFiles;
using System.Security.AccessControl;
using System.Threading;
using BveEx.PluginHost;
using BveTypes.ClassWrappers;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;

// ============================================================================
// PHASE C1 OBSERVATION BUILD - BveEX Bridge (a minimal BveEX extension), human-facing name: "TS Scoring".
// Phase B behaviour is unchanged (BridgeAvailable at load, Ready from Tick, same event names, same timings).
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
//   * Tick runs "every frame while driving" - i.e. only while a scenario is being run, NOT at BVE start-up and NOT in the menus.
//
// Therefore the Bridge announces itself in two steps:
//   1. BridgeAvailable - created and set when BveEX loads the Bridge (constructor, one named event, nothing else).
//      It only means "BveEX and the Bridge exist". It does NOT mean a scenario is loaded or anything is scored.
//   2. Ready - the Caller<->Bridge handshake, created from Tick while BridgeAvailable is valid, Enabled is set and Stop is not.
//      Ready is NOT ScenarioReady (a future event) and NOT "the scoring app is up".
//
// Behaviour:
//  * Constructor: stores two timestamps and publishes BridgeAvailable (no thread, timer, socket, reflection, window, hook).
//    Afterwards (so BridgeAvailable is never delayed by it) the observation subscriptions are made.
//  * Tick (BveEX's, cheap): at most every HandshakeTiming.BridgePollMs it peeks for the Caller's Enabled event while "Searching".
//    While "Connected" it only watches Enabled/Stop; when the Caller stops (Stop set, or Enabled lost) it withdraws Ready and
//    goes back to Searching, so a later enabled cycle is picked up without restarting BVE.
//  * Dispose (BveEX switched off / ending): Ready, BridgeInfo and BridgeAvailable are reset and released.
//  * No exception ever leaves the constructor, Tick, Dispose or an event handler.
// BridgeInfo is a PHASE B MEASUREMENT block (removal candidate after Phase B); it exists only while Ready is published.
// It does not contain the current ScoringPlugin, AtsLoggerPlugin, any ATS data, or any code of this repository.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    [Plugin(PluginType.Extension)]
    public class TsScoringBridgePrototype : AssemblyPluginBase, IExtension
    {
        private enum BridgeState
        {
            Searching,
            Connected,
        }

        private static int instances;

        private readonly long loadQpc;
        private readonly long loadUtcTicks;

        private BridgeState state = BridgeState.Searching;
        private int pid;
        private int lastCheckTick;
        private bool firstCheckDone;

        private EventWaitHandle available;
        private EventWaitHandle enabled;
        private EventWaitHandle stop;
        private EventWaitHandle ready;
        private MemoryMappedFile infoSection;

        // Instrumentation counters (kept across cycles while this instance lives).
        private BridgeInfo info;
        private long availableCreatedQpc;
        private long availableDestroyedQpc;
        private int availableCreateCount;
        private int availableDestroyCount;
        private long lastEnabledSeenQpc;
        private long lastStopSeenQpc;
        private long readyDestroyedQpc;
        private int readyCreateCount;
        private int readyDestroyCount;

        // Phase C1 observation (log only)
        private int instNo;
        private IBveHacker hacker;
        private ScenarioObserver observer;
        private bool firstTickSeen;
        private bool subscribedExtensions;

        // Phase C3 ScenarioReady (the host independent core lives in ScenarioReadyTracker; this class is the Current BveEX adapter)
        private ScenarioReadyTracker tracker;

        public TsScoringBridgePrototype(PluginBuilder builder)
            : base(builder)
        {
            loadQpc = Stopwatch.GetTimestamp();
            loadUtcTicks = DateTime.UtcNow.Ticks;
            instNo = Interlocked.Increment(ref instances);
            Obs("AB", "BRIDGE_CTOR_BEGIN", "ver=" + ObservationLog.Version + " bitness=" + (Environment.Is64BitProcess ? 64 : 32));

            // The ONLY side effect of loading: one named event that says "the Bridge exists". Never throws.
            PublishAvailability();

            // Read-only observation wiring, AFTER BridgeAvailable so it can never delay it.
            try { SubscribeObservers(); } catch { }

            Obs("AB", "BRIDGE_CTOR_END", "sinceCtorBeginMs=" + SinceLoadMs() + " availablePublished=" + (available != null ? "Y" : "N") + " observer=" + (observer != null ? "Y" : "N"));
        }

        public override void Tick(TimeSpan elapsed)
        {
            try
            {
                if (!firstTickSeen)
                {
                    firstTickSeen = true;
                    Obs("AB", "BRIDGE_FIRST_TICK", "sinceCtorBeginMs=" + SinceLoadMs() + " availablePublished=" + (available != null ? "Y" : "N") + " ready=" + ReadyFlag() + " isCreated=" + ReadIsCreatedText());
                }

                if (observer != null)
                {
                    observer.OnTick();
                }
            }
            catch
            {
            }

            // Phase B handshake first (Ready may be created in this very Tick), then the ScenarioReady decision which needs it.
            HandshakeStep();

            try
            {
                if (tracker != null)
                {
                    tracker.OnTick();
                }
            }
            catch
            {
            }
        }

        /// <summary>The Phase B part of Tick (unchanged logic): cheap poll for Enabled / Stop, Ready create and withdraw.</summary>
        private void HandshakeStep()
        {
            try
            {
                int now = Environment.TickCount;
                if (firstCheckDone && unchecked(now - lastCheckTick) < HandshakeTiming.BridgePollMs)
                {
                    return;
                }

                firstCheckDone = true;
                lastCheckTick = now;

                if (available == null)
                {
                    PublishAvailability(); // the constructor attempt failed: retry cheaply
                }

                if (state == BridgeState.Searching)
                {
                    if (available != null)
                    {
                        TryConnect();
                    }
                }
                else if (!StillEnabled())
                {
                    Release("caller-stopped-or-disabled");
                    state = BridgeState.Searching;
                }
            }
            catch (Exception ex)
            {
                // An extension must never take BVE down; on any problem withdraw Ready and keep searching.
                try { Release("tick-exception-" + ex.GetType().Name); } catch { }
                state = BridgeState.Searching;
            }
        }

        public override void Dispose()
        {
            Obs("AB", "BRIDGE_DISPOSE_BEGIN", "sinceCtorBeginMs=" + SinceLoadMs() + " ready=" + ReadyFlag() + " availablePublished=" + (available != null ? "Y" : "N"));
            try { UnsubscribeObservers(); } catch { }
            try { if (observer != null) { observer.OnDispose(); } } catch { }
            try { if (tracker != null) { tracker.OnDispose(); } } catch { } // ScenarioReady is cleared and withdrawn before Ready
            try { Release("bridge-dispose"); } catch { }
            try { WithdrawAvailability(); } catch { }
            Obs("AB", "BRIDGE_DISPOSE_END", string.Empty);
        }

        /// <summary>Creates and sets the BridgeAvailable event once. Internal so the offline tests can run it without BveEX's PluginBuilder.</summary>
        internal void PublishAvailability()
        {
            try
            {
                if (available != null)
                {
                    return;
                }

                if (pid == 0)
                {
                    pid = HandshakeProtocol.CurrentProcessId();
                }

                Obs("B", "AVAIL_CREATE_BEGIN", "sinceCtorBeginMs=" + SinceLoadMs());
                bool created;
                EventWaitHandle handle = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.BridgeAvailableName(pid), out created);
                handle.Set();
                available = handle;
                availableCreatedQpc = Stopwatch.GetTimestamp();
                availableCreateCount++;
                Obs("B", "AVAIL_CREATE_OK", "sinceCtorBeginMs=" + SinceLoadMs() + " createdNew=" + (created ? "Y" : "N") + " createCount=" + availableCreateCount);
            }
            catch (Exception ex)
            {
                // creation failed: BVE must not be affected; Tick retries
                Obs("B", "AVAIL_CREATE_FAIL", "type=" + ex.GetType().Name);
            }
        }

        private void WithdrawAvailability()
        {
            EventWaitHandle toRelease = available;
            available = null;
            if (toRelease != null)
            {
                availableDestroyedQpc = Stopwatch.GetTimestamp();
                availableDestroyCount++;
                try { toRelease.Reset(); } catch { }
                try { toRelease.Dispose(); } catch { }
                Obs("B", "AVAIL_DISPOSED", "destroyCount=" + availableDestroyCount);
            }
        }

        private void TryConnect()
        {
            EventWaitHandle foundEnabled;
            if (!EventWaitHandle.TryOpenExisting(HandshakeProtocol.EnabledName(pid), EventWaitHandleRights.Synchronize, out foundEnabled))
            {
                return;
            }

            if (!foundEnabled.WaitOne(0))
            {
                foundEnabled.Dispose();
                return;
            }

            EventWaitHandle foundStop;
            if (!EventWaitHandle.TryOpenExisting(HandshakeProtocol.StopName(pid), EventWaitHandleRights.Synchronize, out foundStop))
            {
                foundEnabled.Dispose();
                return;
            }

            if (foundStop.WaitOne(0))
            {
                lastStopSeenQpc = Stopwatch.GetTimestamp();
                foundStop.Dispose();
                foundEnabled.Dispose();
                return;
            }

            enabled = foundEnabled;
            stop = foundStop;
            lastEnabledSeenQpc = Stopwatch.GetTimestamp();
            Obs("B", "READY_CREATE_BEGIN", "sinceCtorBeginMs=" + SinceLoadMs() + " createCount=" + (readyCreateCount + 1));

            // Instrumentation first (best effort, never decisive), then Ready, so a Caller that sees Ready can read the numbers.
            readyCreateCount++;
            try
            {
                infoSection = MemoryMappedFile.CreateOrOpen(HandshakeProtocol.InfoName(pid), BridgeInfo.Size, MemoryMappedFileAccess.ReadWrite);
                info = new BridgeInfo
                {
                    ProtocolVersion = BridgeInfo.InfoVersion,
                    Bitness = Environment.Is64BitProcess ? 64 : 32,
                    BridgeLoadQpc = loadQpc,
                    AvailableCreatedQpc = availableCreatedQpc,
                    ReadyCreatedQpc = Stopwatch.GetTimestamp(),
                    BridgeLoadUtcTicks = loadUtcTicks,
                    ReadyCreatedUtcTicks = DateTime.UtcNow.Ticks,
                    AvailableDestroyedQpc = availableDestroyedQpc,
                    ReadyDestroyedQpc = readyDestroyedQpc,
                    AvailableCreateCount = availableCreateCount,
                    AvailableDestroyCount = availableDestroyCount,
                    ReadyCreateCount = readyCreateCount,
                    ReadyDestroyCount = readyDestroyCount,
                    LastEnabledSeenQpc = lastEnabledSeenQpc,
                    LastStopSeenQpc = lastStopSeenQpc,
                };
                WriteInfo();
            }
            catch
            {
                DisposeInfo(); // the measurement must never decide the handshake
            }

            bool created;
            ready = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.ReadyName(pid), out created);
            ready.Set();
            state = BridgeState.Connected;
            Obs("B", "READY_CREATE_OK", "sinceCtorBeginMs=" + SinceLoadMs() + " createdNew=" + (created ? "Y" : "N") + " createCount=" + readyCreateCount);
        }

        private bool StillEnabled()
        {
            if (enabled == null || stop == null)
            {
                return false;
            }

            if (stop.WaitOne(0))
            {
                lastStopSeenQpc = Stopwatch.GetTimestamp();
                return false;
            }

            return enabled.WaitOne(0);
        }

        private void WriteInfo()
        {
            if (infoSection == null)
            {
                return;
            }

            using (MemoryMappedViewAccessor view = infoSection.CreateViewAccessor(0, BridgeInfo.Size, MemoryMappedFileAccess.ReadWrite))
            {
                info.WriteTo(view);
            }
        }

        private void DisposeInfo()
        {
            MemoryMappedFile sectionToRelease = infoSection;
            infoSection = null;
            if (sectionToRelease != null)
            {
                try { sectionToRelease.Dispose(); } catch { }
            }
        }

        /// <summary>Withdraws Ready (and the handshake's own handles). BridgeAvailable is NOT touched here; only Dispose removes it.</summary>
        private void Release(string reason)
        {
            // ScenarioReady is published only while Ready exists: withdraw it first (the level itself is kept by the tracker).
            try { if (tracker != null) { tracker.OnHandshakeLost(reason); } } catch { }

            EventWaitHandle readyToRelease = ready;
            ready = null;
            if (readyToRelease != null)
            {
                // Record the destruction (visible only while the measurement block still exists), then withdraw Ready.
                readyDestroyedQpc = Stopwatch.GetTimestamp();
                readyDestroyCount++;
                try
                {
                    info.ReadyDestroyedQpc = readyDestroyedQpc;
                    info.ReadyDestroyCount = readyDestroyCount;
                    info.LastStopSeenQpc = lastStopSeenQpc;
                    WriteInfo();
                }
                catch
                {
                }

                try { readyToRelease.Reset(); } catch { }
                try { readyToRelease.Dispose(); } catch { }
                Obs("B", "READY_DISPOSED", "reason=" + reason + " destroyCount=" + readyDestroyCount);
            }

            DisposeInfo();

            EventWaitHandle stopToRelease = stop;
            stop = null;
            if (stopToRelease != null)
            {
                try { stopToRelease.Dispose(); } catch { }
            }

            EventWaitHandle enabledToRelease = enabled;
            enabled = null;
            if (enabledToRelease != null)
            {
                try { enabledToRelease.Dispose(); } catch { }
            }
        }

        // ------------------------------------------------------------------------------------------------------------------
        // Phase C1 observation (log only; every method below is exception-safe and has no effect on the handshake)
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
            return ready != null ? "Y" : "N";
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
            tracker = new ScenarioReadyTracker(Obs, readSnapshot, HandshakeUp, publisher, null);
        }

        /// <summary>The Phase B handshake is up: TS Scoring is enabled, Stop is not set and Ready is published.</summary>
        private bool HandshakeUp()
        {
            return state == BridgeState.Connected && ready != null;
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
