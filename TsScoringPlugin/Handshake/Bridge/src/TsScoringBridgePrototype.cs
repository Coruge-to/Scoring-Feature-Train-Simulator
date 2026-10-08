using System;
using System.Diagnostics;
using System.IO.MemoryMappedFiles;
using System.Security.AccessControl;
using System.Threading;
using BveEx.PluginHost.Plugins;
using BveEx.PluginHost.Plugins.Extensions;

// ============================================================================
// PHASE B HANDSHAKE PROTOTYPE - BveEX Bridge (a minimal BveEX extension), human-facing name: "TS Scoring".
// Contract used: BveEX's public Plugin API only (PluginAttribute, AssemblyPluginBase, IExtension, Tick, Dispose).
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
//  * Constructor: stores two timestamps and publishes BridgeAvailable (no thread, timer, file, socket, reflection, window, hook).
//  * Tick (BveEX's, cheap): at most every HandshakeTiming.BridgePollMs it peeks for the Caller's Enabled event while "Searching".
//    While "Connected" it only watches Enabled/Stop; when the Caller stops (Stop set, or Enabled lost) it withdraws Ready and
//    goes back to Searching, so a later enabled cycle is picked up without restarting BVE.
//  * Dispose (BveEX switched off / ending): Ready, BridgeInfo and BridgeAvailable are reset and released.
//  * No exception ever leaves the constructor, Tick or Dispose.
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

        public TsScoringBridgePrototype(PluginBuilder builder)
            : base(builder)
        {
            loadQpc = Stopwatch.GetTimestamp();
            loadUtcTicks = DateTime.UtcNow.Ticks;

            // The ONLY side effect of loading: one named event that says "the Bridge exists". Never throws.
            PublishAvailability();
        }

        public override void Tick(TimeSpan elapsed)
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
                    Release();
                    state = BridgeState.Searching;
                }
            }
            catch
            {
                // An extension must never take BVE down; on any problem withdraw Ready and keep searching.
                try { Release(); } catch { }
                state = BridgeState.Searching;
            }
        }

        public override void Dispose()
        {
            try { Release(); } catch { }
            try { WithdrawAvailability(); } catch { }
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

                bool created;
                EventWaitHandle handle = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.BridgeAvailableName(pid), out created);
                handle.Set();
                available = handle;
                availableCreatedQpc = Stopwatch.GetTimestamp();
                availableCreateCount++;
            }
            catch
            {
                // creation failed: BVE must not be affected; Tick retries
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
        private void Release()
        {
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
    }
}
