using System;
using System.Diagnostics;
using System.IO.MemoryMappedFiles;
using System.Security.AccessControl;
using System.Threading;

// ============================================================================
// PHASE SI-A7 (M1a) - the Tick independent CONTROL PLANE of the Bridge, shared by the Current and the Legacy adapter.
// This file is HOST INDEPENDENT: it names no type of any host and no object of the simulator (the verification scripts check that, comments included).
// It moved here from Bridge\Legacy\src (Phase L1, where only the Legacy adapter used it); the Current adapter now uses the very same source.
//
// Why it exists: the extension's Tick (and the data updates) can stop while the simulation is paused. The handshake therefore must not wait for Tick.
// The control plane owns only named kernel objects, one memory section and plain numbers:
//   Enabled / Stop (opened, set by the Caller)     BridgeAvailable / Ready (created here)     BridgeInfo (measurement block, as Phase B)
// and it runs on ONE background thread of its own (never the host's thread). That thread NEVER touches anything of the simulator or of the host's
// object model: not the hacker object, not the scenario, the vehicle, the time manager, the current position, the current time, the station list, or any
// other object whose thread safety is not established. Those are read on Tick by the ready-level tracker only. What the thread MAY use is exactly:
//   named events, the memory-mapped files above, Stopwatch, the observation log, and plain numbers handed over through the two callbacks below.
//
// Behaviour = the Phase B handshake of the Current adapter, same names, same rules, driven by a thread instead of Tick:
//   * BridgeAvailable: created and set when the Bridge loads; reset and released only by WithdrawAvailability (Bridge Dispose).
//   * Ready: created and set while the Caller is Enabled and Stop is not set; withdrawn as soon as Stop is set or Enabled is lost
//     (that is: also while the simulation is paused and Tick is silent). Re-created when the Caller is enabled again.
//   * Withdrawing Ready first tells the owner (handshakeLost) so that the external ready-level publication stops BEFORE Ready goes. The level itself is kept
//     by the owner. Creating Ready tells the owner (handshakeUp, with the new ReadyEpoch) AFTER Ready exists, and the owner publishes the HELD level again
//     right away - from this thread, with no Tick - using only the plain numbers it already keeps.
//   * ReadyEpoch = the number of Ready creations of this instance (1 = the first). It is a lock free volatile value that is set BEFORE the handshake is
//     reported up, so a Tick that sees the handshake up always sees the epoch of that very Ready.
//   * The thread survives any exception of one step (the step withdraws Ready and the next poll starts over); it ends only on Shutdown.
//
// LOCK ORDER (the only one, fixed by the verification scripts):
//   control gate  ->  owner's gate (the tracker).
//   The control plane takes its own gate and, while holding it, calls handshakeLost / handshakeUp, which take the owner's gate. Nothing that holds the
//   owner's gate takes the control gate: the owner and the adapter's Tick read this class through lock free volatile members only
//   (HandshakeUp, ReadyEpoch, IsWorkerAlive). The observation log is a leaf lock below both.
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
        private readonly Action<int> handshakeUp;                // called AFTER Ready was published (the new ReadyEpoch)
        private readonly int pollMs;
        private readonly object gate = new object();
        private readonly ManualResetEvent shutdown = new ManualResetEvent(false);

        private volatile bool up;                                // Ready is published (read by Tick without a lock)
        private volatile int readyEpoch;                         // number of the current / latest Ready creation (read without a lock; set before 'up')
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
        private int stepExceptions;

        internal HandshakeControlPlane(int pid, long loadQpc, long loadUtcTicks, Action<string, string, string> log, Action<string> handshakeLost, Action<int> handshakeUp, int pollMs)
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

        /// <summary>The number of the current (or, while the handshake is down, the latest) Ready creation. 0 = Ready was never created. Lock free.</summary>
        internal int ReadyEpoch { get { return readyEpoch; } }

        internal bool IsAvailablePublished { get { lock (gate) { return available != null; } } }

        /// <summary>Lock free: the worker thread exists and runs.</summary>
        internal bool IsWorkerAlive { get { Thread w = worker; return w != null && w.IsAlive; } }

        internal int ReadyCreateCount { get { lock (gate) { return readyCreateCount; } } }

        internal int ReadyDestroyCount { get { lock (gate) { return readyDestroyCount; } } }

        /// <summary>Exceptions swallowed by Step (the offline tests: 0 in every normal run).</summary>
        internal int StepExceptionCount { get { lock (gate) { return stepExceptions; } } }

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
                t.Name = "TS Scoring control plane";
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
                    try
                    {
                        Step();
                    }
                    catch
                    {
                        // one bad step must not end the control plane (a pause may last minutes and Tick cannot restart it then); Step already withdrew Ready
                    }
                }
            }
            catch
            {
                // an extension must never take the host down
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
                    stepExceptions++;
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
        /// After this call Step does nothing. Safe to call more than once; the thread is joined outside the gate.
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
            readyEpoch = readyCreateCount;   // BEFORE 'up': whoever sees the handshake up sees the epoch of this Ready
            up = true;
            log("B", "READY_CREATE_OK", "sinceCtorBeginMs=" + SinceLoadMs() + " createdNew=" + (created ? "Y" : "N") + " createCount=" + readyCreateCount + " readyEpoch=" + readyEpoch);
            try { handshakeUp(readyEpoch); } catch { }
        }

        /// <summary>Withdraws Ready (and the handshake's own handles). BridgeAvailable is NOT touched.</summary>
        private void ReleaseLocked(string reason)
        {
            up = false;

            // The external ready-level publication exists only while Ready exists: it is withdrawn first (the level itself is kept by the owner).
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
                log("B", "READY_DISPOSED", "reason=" + reason + " destroyCount=" + readyDestroyCount + " readyEpoch=" + readyEpoch);
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
