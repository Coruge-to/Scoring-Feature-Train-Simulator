using System;
using System.Diagnostics;
using System.IO.MemoryMappedFiles;
using System.Security.AccessControl;
using System.Threading;

// ============================================================================
// PHASE L1 - Tick independent CONTROL PLANE of the Bridge (host independent: no AtsEX / BveEX type in this file).
//
// Why it exists: in AtsEX legacy mode the extension's Tick (and the data updates) can stop while the simulation is paused (verified in the
// DenGo project). The control plane therefore must not wait for Tick. It owns only named kernel objects and nothing of BVE:
//   Enabled / Stop (opened, set by the Caller)     BridgeAvailable / Ready (created here)     BridgeInfo (measurement block, as Phase B)
// and it runs on ONE background thread of its own (never BVE's thread). The thread NEVER touches BveHacker, Scenario, Vehicle, TimeManager
// or any other BVE object: those are read on Tick by the ScenarioReady tracker only (thread safety of BVE internals is not established).
//
// Behaviour = the Phase B handshake of the Current adapter, same names, same rules, driven by a thread instead of Tick:
//   * BridgeAvailable: created and set when the Bridge loads; reset and released only by WithdrawAvailability (Bridge Dispose).
//   * Ready: created and set while the Caller is Enabled and Stop is not set; withdrawn as soon as Stop is set or Enabled is lost
//     (that is: also while the simulation is paused and Tick is silent). Re-created when the Caller is enabled again.
//   * Withdrawing Ready first tells the owner (handshakeLost) so that the external ScenarioReady publication stops BEFORE Ready goes.
//     The ScenarioReady LEVEL is kept by the tracker. Re-publication is decided on the next Tick (by the tracker), not here.
//
// Locking: one private gate serialises Step / Shutdown / Publish / Withdraw. Tick never takes that gate (it reads the volatile 'up' flag),
// so the tracker's gate and this gate are never taken in opposite orders.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal sealed class HandshakeControlPlane
    {
        /// <summary>Number of control threads currently running in this process (offline tests: must be 0 after every Dispose).</summary>
        internal static int LiveWorkers;

        private readonly int pid;
        private readonly long loadQpc;
        private readonly long loadUtcTicks;
        private readonly Action<string, string, string> log;     // (track, event, detail)
        private readonly Action<string> handshakeLost;           // called BEFORE Ready is withdrawn (reason code)
        private readonly Action handshakeUp;                     // called AFTER Ready was published
        private readonly int pollMs;
        private readonly object gate = new object();
        private readonly ManualResetEvent shutdown = new ManualResetEvent(false);

        private volatile bool up;                                // Ready is published (read by Tick without a lock)
        private bool stopped;
        private Thread worker;

        private EventWaitHandle available;
        private EventWaitHandle enabled;
        private EventWaitHandle stop;
        private EventWaitHandle ready;
        private MemoryMappedFile infoSection;

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

        internal HandshakeControlPlane(int pid, long loadQpc, long loadUtcTicks, Action<string, string, string> log, Action<string> handshakeLost, Action handshakeUp, int pollMs)
        {
            this.pid = pid;
            this.loadQpc = loadQpc;
            this.loadUtcTicks = loadUtcTicks;
            this.log = log ?? delegate { };
            this.handshakeLost = handshakeLost ?? delegate { };
            this.handshakeUp = handshakeUp ?? delegate { };
            this.pollMs = pollMs < 1 ? HandshakeTiming.CallerPollMs : pollMs;
        }

        /// <summary>Ready is published (TS Scoring enabled, Stop not set). Lock free; safe to read from Tick.</summary>
        internal bool HandshakeUp { get { return up; } }

        internal bool IsAvailablePublished { get { lock (gate) { return available != null; } } }

        internal bool IsWorkerAlive { get { Thread w = worker; return w != null && w.IsAlive; } }

        internal int ReadyCreateCount { get { lock (gate) { return readyCreateCount; } } }

        internal int ReadyDestroyCount { get { lock (gate) { return readyDestroyCount; } } }

        /// <summary>Starts the control thread once (no-op while it runs or after Shutdown).</summary>
        internal void Start()
        {
            lock (gate)
            {
                if (stopped || IsWorkerAlive)
                {
                    return;
                }

                Thread t = new Thread(Loop);
                t.IsBackground = true;
                t.Name = "TS Scoring legacy control plane";
                worker = t;
                t.Start();
            }
        }

        private void Loop()
        {
            Interlocked.Increment(ref LiveWorkers);
            try
            {
                while (!shutdown.WaitOne(pollMs))
                {
                    Step();
                }
            }
            catch
            {
                // an extension must never take BVE down; Tick restarts the thread (Start) if it ever ends
            }
            finally
            {
                Interlocked.Decrement(ref LiveWorkers);
            }
        }

        /// <summary>One poll of the control plane. Public to the assembly so the offline tests can drive it without the thread.</summary>
        internal void Step()
        {
            lock (gate)
            {
                if (stopped)
                {
                    return;
                }

                try
                {
                    if (available == null)
                    {
                        PublishAvailabilityLocked(); // the load attempt failed: retry cheaply
                    }

                    if (ready == null)
                    {
                        if (available != null)
                        {
                            TryConnectLocked();
                        }
                    }
                    else if (!StillEnabledLocked())
                    {
                        ReleaseLocked("caller-stopped-or-disabled");
                    }
                }
                catch (Exception ex)
                {
                    try { ReleaseLocked("control-exception-" + ex.GetType().Name); } catch { }
                }
            }
        }

        /// <summary>Creates and sets the BridgeAvailable event once. Never throws.</summary>
        internal void PublishAvailability()
        {
            lock (gate)
            {
                PublishAvailabilityLocked();
            }
        }

        private void PublishAvailabilityLocked()
        {
            try
            {
                if (available != null || stopped)
                {
                    return;
                }

                log("B", "AVAIL_CREATE_BEGIN", "sinceCtorBeginMs=" + SinceLoadMs());
                bool created;
                EventWaitHandle handle = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.BridgeAvailableName(pid), out created);
                handle.Set();
                available = handle;
                availableCreatedQpc = Stopwatch.GetTimestamp();
                availableCreateCount++;
                log("B", "AVAIL_CREATE_OK", "sinceCtorBeginMs=" + SinceLoadMs() + " createdNew=" + (created ? "Y" : "N") + " createCount=" + availableCreateCount);
            }
            catch (Exception ex)
            {
                log("B", "AVAIL_CREATE_FAIL", "type=" + ex.GetType().Name);
            }
        }

        /// <summary>Resets and releases BridgeAvailable (Bridge Dispose only).</summary>
        internal void WithdrawAvailability()
        {
            lock (gate)
            {
                EventWaitHandle toRelease = available;
                available = null;
                if (toRelease != null)
                {
                    availableDestroyedQpc = Stopwatch.GetTimestamp();
                    availableDestroyCount++;
                    try { toRelease.Reset(); } catch { }
                    try { toRelease.Dispose(); } catch { }
                    log("B", "AVAIL_DISPOSED", "destroyCount=" + availableDestroyCount);
                }
            }
        }

        /// <summary>
        /// Stops the thread (waits a short time for it), withdraws Ready and every handle of the handshake. BridgeAvailable is NOT touched.
        /// After this call Step does nothing. Safe to call more than once.
        /// </summary>
        internal void Shutdown(string reason)
        {
            Thread t;
            lock (gate)
            {
                t = worker;
            }

            try { shutdown.Set(); } catch { }
            if (t != null && t != Thread.CurrentThread)
            {
                try { t.Join(1000); } catch { }
            }

            lock (gate)
            {
                stopped = true;
                try { ReleaseLocked(reason); } catch { }
            }
        }

        private bool StillEnabledLocked()
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

        private void TryConnectLocked()
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
            log("B", "READY_CREATE_BEGIN", "sinceCtorBeginMs=" + SinceLoadMs() + " createCount=" + (readyCreateCount + 1));

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
                WriteInfoLocked();
            }
            catch
            {
                DisposeInfoLocked(); // the measurement must never decide the handshake
            }

            bool created;
            ready = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.ReadyName(pid), out created);
            ready.Set();
            up = true;
            log("B", "READY_CREATE_OK", "sinceCtorBeginMs=" + SinceLoadMs() + " createdNew=" + (created ? "Y" : "N") + " createCount=" + readyCreateCount);
            try { handshakeUp(); } catch { }
        }

        /// <summary>Withdraws Ready (and the handshake's own handles). BridgeAvailable is NOT touched.</summary>
        private void ReleaseLocked(string reason)
        {
            up = false;

            // ScenarioReady is published only while Ready exists: it is withdrawn first (the level itself is kept by the tracker).
            try { handshakeLost(reason); } catch { }

            EventWaitHandle readyToRelease = ready;
            ready = null;
            if (readyToRelease != null)
            {
                readyDestroyedQpc = Stopwatch.GetTimestamp();
                readyDestroyCount++;
                try
                {
                    info.ReadyDestroyedQpc = readyDestroyedQpc;
                    info.ReadyDestroyCount = readyDestroyCount;
                    info.LastStopSeenQpc = lastStopSeenQpc;
                    WriteInfoLocked();
                }
                catch
                {
                }

                try { readyToRelease.Reset(); } catch { }
                try { readyToRelease.Dispose(); } catch { }
                log("B", "READY_DISPOSED", "reason=" + reason + " destroyCount=" + readyDestroyCount);
            }

            DisposeInfoLocked();

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

        private void WriteInfoLocked()
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

        private void DisposeInfoLocked()
        {
            MemoryMappedFile sectionToRelease = infoSection;
            infoSection = null;
            if (sectionToRelease != null)
            {
                try { sectionToRelease.Dispose(); } catch { }
            }
        }

        private double SinceLoadMs()
        {
            return Math.Round(HandshakeProtocol.QpcToMs(Stopwatch.GetTimestamp() - loadQpc), 1);
        }
    }
}
