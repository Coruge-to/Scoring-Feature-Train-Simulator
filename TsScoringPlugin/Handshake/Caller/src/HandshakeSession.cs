using System;
using System.Diagnostics;
using System.IO.MemoryMappedFiles;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Text;
using System.Threading;

namespace TSScoringPlugin.Handshake
{
    /// <summary>
    /// Caller-side dependency state. BridgeAvailable is a transient step (evaluated and left within one monitor step).
    /// </summary>
    internal enum CallerPhase
    {
        Disabled,
        WaitingForBridge,
        BridgeAvailable,
        WaitingForHandshake,
        Connected,
        BridgeMissingTimedOut,
        Disposed,
    }

    /// <summary>
    /// The Caller's waiting times, one constant per MEANING. (BridgeMissingTimeoutMs in Shared\HandshakeProtocol.cs is kept as it was: the Bridge
    /// compiles that file, so it must not change; the Caller no longer decides anything with it.)
    /// </summary>
    internal static class CallerNoticeTiming
    {
        /// <summary>Start-up diagnostic: BridgeAvailable still never seen this long after Enabled -> ONE log line. Never a dialog, never the notice latch.</summary>
        public const int StartupBridgeDiagnosticMs = 1000;

        /// <summary>Lost connection: BridgeAvailable was seen once and is then gone this long -> the dependency notice.</summary>
        public const int ConnectionLostNoticeMs = 500;
    }

    /// <summary>
    /// What the BveEX dependency notice knows about this Caller instance (Phase M1). Derived from the phase machine, never stored.
    /// </summary>
    internal enum DependencyState
    {
        /// <summary>Enabled, no Tick yet and BridgeAvailable never seen: nothing is shown to the user (the 500 ms is a log line only).</summary>
        StartupWaiting,

        /// <summary>The first Tick arrived and BridgeAvailable was missing: the one-time dependency check has run.</summary>
        UseStarted,

        /// <summary>BridgeAvailable is (or was a moment ago, under 500 ms) present.</summary>
        Connected,

        /// <summary>BridgeAvailable was seen once and has been gone for ConnectionLostNoticeMs (500 ms) or longer.</summary>
        ConnectionLost,
    }

    /// <summary>
    /// One "enabled cycle" of the Caller (Load .. Dispose). Publishes Enabled/Stop and watches the Bridge on ONE background monitor thread:
    ///
    ///   WaitingForBridge --BridgeAvailable seen--> (BridgeAvailable) --> WaitingForHandshake --Ready--> Connected
    ///   Connected --Ready lost, Bridge still there--> WaitingForHandshake
    ///   any --BridgeAvailable lost--> WaitingForBridge (a new absence stretch)
    ///   WaitingForBridge --never seen, absent for StartupBridgeDiagnosticMs (1000 ms)--> BridgeMissingTimedOut (one log line)
    ///   WaitingForBridge --seen before, absent for ConnectionLostNoticeMs (500 ms)--> BridgeMissingTimedOut (the notice)
    ///   BridgeMissingTimedOut --BridgeAvailable back--> WaitingForHandshake
    ///
    /// Only the absence of BridgeAvailable means "BveEX / the Bridge is not there". A missing Ready (BveEX's Tick runs only while a
    /// scenario is driven) and a missing scenario never produce the BveEX notice.
    ///
    /// Phase M1 - WHEN the notice may appear. The notice is ONE per Caller instance (single latch <c>noticeShown</c>, taken at the moment the
    /// dialog is committed; a suppressed attempt leaves it free). Two triggers share it:
    ///   * first use: BVE called Tick for the first time (<see cref="NotifyTick"/>, a flag only) and the monitor thread, looking at the named
    ///     BridgeAvailable event DIRECTLY (not the cached state), finds it missing;
    ///   * connection lost: BridgeAvailable had been seen and is then gone for ConnectionLostNoticeMs (500 ms).
    /// Before the first BridgeAvailable the 500 ms is only a diagnostic log line: the scenario list (no Tick) never produces a notice.
    /// Nothing here runs on BVE's threads except the cheap Start/End/NotifyTick calls.
    ///
    /// Phase D1 adds DrivingActive (DrivingActivityState.cs) as an internal, read-only state evaluated by the same monitor thread; it changes
    /// nothing above (the notice, the phases and ScenarioReady are untouched) and nothing consumes it yet.
    ///
    /// Phase E1 adds the AppController dry-run (AppController.cs): the monitor thread hands it the DrivingActive result after each evaluation and
    /// Dispose tells it once. It only decides and logs (APP_START_REQUEST once per ScenarioGeneration, APP_STOP_REQUEST once at Dispose); it starts,
    /// stops and sends nothing, and BVE's Tick path is unchanged.
    ///
    /// Phase E3 lets the production instance act on those two decisions through AppProcessManager.cs: the start request becomes at most ONE managed
    /// application process (launcher.json permitting), Dispose sets its Stop event and waits a finite time for the exit. The decisions, their
    /// log lines and the Tick path are unchanged; nothing but Dispose ever stops the process.
    ///
    /// Phase E4 publishes the Session (ScenarioReady) and Driving (DrivingActive) levels, with the ScenarioGeneration, to that process through its
    /// state block (AppStatePublisher.cs) from the same monitor step. The levels, the phases and every earlier decision are unchanged; the
    /// publication never starts or stops the process, and it is identical for the Current and the Legacy Bridge.
    /// </summary>
    internal sealed class HandshakeSession
    {
        private const uint MB_OK = 0x00000000;
        private const uint MB_ICONINFORMATION = 0x00000040;
        private const uint MB_SETFOREGROUND = 0x00010000;
        private const uint MB_TOPMOST = 0x00040000;

        [DllImport("user32.dll", EntryPoint = "MessageBoxW", CharSet = CharSet.Unicode)]
        private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

        // Human-facing product name (the technical identifiers elsewhere keep "TSScoringPlugin").
        internal const string ProductDisplayName = "TS Scoring";
        internal const string ProviderName = "Coruge-to";

        internal const string NoticeText =
            "TS ScoringにはBveEXが必要です。\r\n" +
            "設定 → 入力デバイス でBveEXを有効にし、BVEを再起動してください。";

        /// <summary>Diagnostic for the offline tests: monitor threads currently alive (must return to 0 after every cycle).</summary>
        internal static int LiveMonitors;

        private readonly object gate = new object();
        private readonly int pid;
        private readonly Action<string> showNotice;

        private EventWaitHandle enabled;
        private EventWaitHandle stop;
        private EventWaitHandle bridge;
        private EventWaitHandle ready;
        private ManualResetEvent wake;
        private Thread monitor;

        private bool started;
        private CallerPhase phase = CallerPhase.Disabled;
        private bool bridgePresent;
        private bool readyPresent;

        // Phase C1 observation (log only)
        private static int cycleCounter;
        private int cycleNo;
        private bool firstCheckLogged;
        private bool firstAvailLogged;
        private bool firstReadyLogged;
        private bool timeoutLoggedThisAbsence;
        private bool startupDiagLogged;
        private long timeoutReachedQpc;
        private long judgeQpc;

        // Phase C3: ScenarioReady as seen from the Caller. Read only: transitions are written to the log, nothing else reacts to them yet.
        private EventWaitHandle scenarioEvent;
        private MemoryMappedFile scenarioSection;
        private MemoryMappedViewAccessor scenarioView;
        private bool scenarioReadyLevel;
        private int scenarioGenerationSeen;      // last valid ScenarioGeneration read (0 = none yet)
        private bool scenarioLoadSupported;      // Phase SI-A6: the Bridge published a valid load marker in the last valid reading
        private uint scenarioLoadInfo;           // Phase SI-A6: its bits (ScenarioState.LoadCreated / LoadTickSeen) - they belong to scenarioGenerationSeen (one reading)
        private int scenarioReadyOnCount;
        private int scenarioReadyOffCount;
        private int scenarioGenerationChanges;

        // Phase M1: the single notice latch (per Caller instance) and the first-Tick hand-over from BVE's thread to the monitor thread.
        private enum NoticeTrigger { FirstUse, ConnectionLost }

        private volatile bool tickSeen;          // written by BVE's Tick (first call only); read by the monitor
        private long firstTickQpc;               // written before tickSeen is published
        private bool firstTickJudged;
        private bool noticeShown;                // the latch: a dialog was committed for this instance
        private long noticeTriggerQpc;
        private readonly Func<bool> bridgeProbeOverride;   // offline tests only (null in production)

        // Phase D1: DrivingActive (see DrivingActivityState.cs). Internal and read-only: nothing consumes it yet.
        // BVE's Tick only writes the two Interlocked values; the monitor thread evaluates the state under the gate.
        private long lastTickQpc;                // Interlocked (64-bit value, BVE5 is a 32-bit process): time of the last Tick
        private long tickSeq;                    // Interlocked: Tick count of THIS Caller instance (never carried over to another instance)
        private readonly DrivingActivityState driving = new DrivingActivityState();
        private int drivingOnCount;
        private int drivingHardOffCount;
        private int drivingSoftOffCount;
        private int drivingExceptionLines;
        private long drivingOnQpc;
        private DrivingOffReason drivingLastOffReason;

        // Phase E1: the AppController dry-run (see AppController.cs). Decisions only: nothing is started, stopped or sent. Evaluated by the
        // monitor thread after DrivingActive, and once by End(); BVE's Tick never touches it.
        private AppController appController = new AppController();
        private int appExceptionLines;

        // Phase E3: the one managed application process of this Caller instance (AppProcessManager.cs). Null = this instance never starts an
        // application (every offline-test constructor); the production constructor creates it. Start requests are forwarded from the monitor
        // thread (cheap); Dispose calls Shutdown outside the gate. Nothing about it runs on BVE's Tick path.
        private readonly AppProcessManager appProcess;

        private bool noticeInFlight;
        private bool timedOutEver;
        private bool missedBridgeTarget;
        private int noticeCount;
        private int bridgeSeenCount;
        private int bridgeLostCount;
        private int readyConnectCount;
        private int readyLostCount;

        private long enabledQpc;
        private long absenceStartQpc;
        private long handshakeStartQpc;
        private long bridgeFirstSeenQpc;
        private long bridgeLostQpc;
        private long readyLastQpc;
        private long readyLostQpc;
        private double firstBridgeDetectMs = -1;
        private double latestBridgeDetectMs = -1;
        private double latestHandshakeMs = -1;
        private DateTime enabledLocal;

        /// <summary>Production constructor: this BVE process, real MessageBox.</summary>
        public HandshakeSession()
            : this(HandshakeProtocol.CurrentProcessId(), DefaultShowNotice, null, true, null)
        {
        }

        /// <summary>Test constructor: explicit PID and a notice sink that can be a test double.</summary>
        internal HandshakeSession(int pid, Action<string> showNotice)
            : this(pid, showNotice, null)
        {
        }

        /// <summary>Test constructor: additionally replaces the direct BridgeAvailable check (to separate it from the cached state).</summary>
        internal HandshakeSession(int pid, Action<string> showNotice, Func<bool> bridgeProbeOverride)
            : this(pid, showNotice, bridgeProbeOverride, false, null)
        {
        }

        /// <summary>Test constructor (Phase E3): additionally injects the application process manager (null = none). The other test constructors never start an application.</summary>
        internal HandshakeSession(int pid, Action<string> showNotice, Func<bool> bridgeProbeOverride, AppProcessManager appProcessManager)
            : this(pid, showNotice, bridgeProbeOverride, false, appProcessManager)
        {
        }

        private HandshakeSession(int pid, Action<string> showNotice, Func<bool> bridgeProbeOverride, bool startApplication, AppProcessManager appProcessManager)
        {
            this.pid = pid;
            this.showNotice = showNotice ?? DefaultShowNotice;
            this.bridgeProbeOverride = bridgeProbeOverride;
            if (appProcessManager != null)
            {
                appProcess = appProcessManager;
            }
            else if (startApplication)
            {
                appProcess = new AppProcessManager(pid, LogAppProcess, null, null);
            }
        }

        internal CallerPhase Phase { get { lock (gate) { return phase; } } }
        internal int NoticeCount { get { lock (gate) { return noticeCount; } } }
        internal int BridgeSeenCount { get { lock (gate) { return bridgeSeenCount; } } }
        internal int BridgeLostCount { get { lock (gate) { return bridgeLostCount; } } }
        internal int ReadyConnectCount { get { lock (gate) { return readyConnectCount; } } }
        internal int ReadyLostCount { get { lock (gate) { return readyLostCount; } } }
        internal bool NoticeArmed { get { lock (gate) { return !noticeShown && !noticeInFlight; } } }
        internal bool NoticeShown { get { lock (gate) { return noticeShown; } } }
        internal bool FirstTickSeen { get { return tickSeen; } }
        internal bool FirstTickJudged { get { lock (gate) { return firstTickJudged; } } }
        internal DependencyState State { get { lock (gate) { return StateLocked(); } } }
        internal bool MissedBridgeTarget { get { lock (gate) { return missedBridgeTarget; } } }
        internal bool MonitorAlive { get { Thread t; lock (gate) { t = monitor; } return t != null && t.IsAlive; } }
        internal bool ScenarioReadyLevel { get { lock (gate) { return scenarioReadyLevel; } } }
        internal int ScenarioGenerationSeen { get { lock (gate) { return scenarioGenerationSeen; } } }
        internal int ScenarioReadyOnCount { get { lock (gate) { return scenarioReadyOnCount; } } }
        internal int ScenarioReadyOffCount { get { lock (gate) { return scenarioReadyOffCount; } } }
        internal int ScenarioGenerationChanges { get { lock (gate) { return scenarioGenerationChanges; } } }
        internal bool DrivingActive { get { lock (gate) { return driving.Active; } } }
        internal int DrivingActiveOnCount { get { lock (gate) { return drivingOnCount; } } }
        internal int DrivingHardOffCount { get { lock (gate) { return drivingHardOffCount; } } }
        internal int DrivingSoftOffCount { get { lock (gate) { return drivingSoftOffCount; } } }
        internal DrivingOffReason DrivingLastOffReason { get { lock (gate) { return drivingLastOffReason; } } }
        internal long TickSequence { get { return Interlocked.Read(ref tickSeq); } }
        internal int AppStartRequestCount { get { lock (gate) { return appController == null ? 0 : appController.StartRequestCount; } } }
        internal int AppStopRequestCount { get { lock (gate) { return appController == null ? 0 : appController.StopRequestCount; } } }
        internal int AppSuppressedCount { get { lock (gate) { return appController == null ? 0 : appController.SuppressedCount; } } }
        internal AppProcessManager AppProcess { get { return appProcess; } }

        private static void DefaultShowNotice(string text)
        {
            MessageBoxW(IntPtr.Zero, text, ProductDisplayName, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST);
        }

        /// <summary>
        /// Called from BVE's Tick (every frame it runs). Every call does two atomic writes for DrivingActive (Phase D1: the Tick time, then the
        /// Tick count); only the FIRST call also raises the first-Tick flag (Phase M1: one timestamp and one flag write).
        /// No lock, no I/O, no log, no dialog, no wait, no kernel object: the monitor thread reads the values and decides.
        /// </summary>
        public void NotifyTick()
        {
            Interlocked.Exchange(ref lastTickQpc, Stopwatch.GetTimestamp());
            Interlocked.Increment(ref tickSeq);

            if (tickSeen)
            {
                return;
            }

            firstTickQpc = Stopwatch.GetTimestamp();
            tickSeen = true; // volatile write: publishes firstTickQpc
        }

        /// <summary>Cheap: creates the two events and starts the single monitor thread. Called from BVE's Load.</summary>
        public void Start()
        {
            lock (gate)
            {
                if (started)
                {
                    return; // one monitor per session; never a second thread
                }

                started = true;

                // Create Stop first and Enabled last, so a Bridge that sees Enabled always finds Stop.
                bool created;
                stop = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.StopName(pid), out created);
                stop.Reset();
                enabled = new EventWaitHandle(false, EventResetMode.ManualReset, HandshakeProtocol.EnabledName(pid), out created);
                enabled.Set();

                enabledQpc = Stopwatch.GetTimestamp();
                absenceStartQpc = enabledQpc;
                enabledLocal = DateTime.Now;
                phase = CallerPhase.WaitingForBridge;
                cycleNo = Interlocked.Increment(ref cycleCounter);
                Obs("CALLER_ENABLED_CREATED", "pid=" + pid + " ver=" + ObservationLog.Version);

                wake = new ManualResetEvent(false);
                monitor = new Thread(MonitorLoop);
                monitor.IsBackground = true;
                monitor.Name = "TSScoringPlugin.Caller.BridgeMonitor";
                monitor.Start();
            }
        }

        /// <summary>Called from Dispose: monitoring ends, Stop is signalled, Enabled is withdrawn, every handle is released.</summary>
        public void End()
        {
            lock (gate)
            {
                if (phase == CallerPhase.Disposed)
                {
                    return;
                }

                Obs("CALLER_DISPOSE_BEGIN", "phaseBefore=" + phase + " sinceEnabledMs=" + SinceEnabledMs(Stopwatch.GetTimestamp()));
                phase = CallerPhase.Disposed;
                EvaluateDrivingLocked(Stopwatch.GetTimestamp()); // Phase D1: DrivingActive goes OFF (hard, dispose) before anything is released
                PublishAppStateLocked();                         // Phase E4: Session OFF / Driving OFF reach the application (Closed is set by Shutdown, before Stop)
                DisposeAppControllerLocked();                    // Phase E1: the one dry-run stop request (Dispose began), before anything is released

                try { if (wake != null) { wake.Set(); } } catch { }
                try { if (stop != null) { stop.Set(); } } catch { }
                try { if (enabled != null) { enabled.Reset(); } } catch { }

                if (scenarioReadyLevel)
                {
                    scenarioReadyLevel = false;
                    scenarioReadyOffCount++;
                    ObsA("SCN_READY_OFF", "ScenarioGeneration=" + scenarioGenerationSeen + " reason=caller-dispose");
                }

                ReleaseScenarioObjectsLocked();
                Release(ref ready);
                Release(ref bridge);
                Release(ref enabled);
                Release(ref stop);
                Obs("CALLER_DISPOSE_END", string.Empty);
            }

            ShutdownAppProcess(); // Phase E3: Stop to the managed application, a finite wait for its exit (outside the gate, off the monitor thread)
        }

        /// <summary>
        /// Phase D1: evaluates DrivingActive from what the Caller already knows. Gate must be held and ScenarioReady must have been read
        /// just before (Step) or the Caller must be ending. The Tick count is read AFTER ScenarioReady (a Tick between the publication and this
        /// reading is not counted as "after the publication"), and the Tick time AFTER the count (BVE's Tick writes the time first), so the
        /// time always belongs to a Tick at least as new as the count says. Only state CHANGES are logged. Never throws.
        /// </summary>
        private void EvaluateDrivingLocked(long now)
        {
            try
            {
                long seq = Interlocked.Read(ref tickSeq);
                long last = Interlocked.Read(ref lastTickQpc);
                double ageMs = last == 0 ? -1 : Math.Max(0, HandshakeProtocol.QpcToMs(now - last));
                bool isEnabled = started && phase != CallerPhase.Disabled && phase != CallerPhase.Disposed;
                DrivingStep step = driving.Evaluate(isEnabled, phase != CallerPhase.Disposed, scenarioReadyLevel, scenarioGenerationSeen, seq, ageMs);
                if (!step.Changed)
                {
                    return;
                }

                string age = Math.Round(ageMs, 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
                if (step.Active)
                {
                    drivingOnCount++;
                    drivingOnQpc = now;
                    ObsA("DRIVING_ACTIVE_ON", "ScenarioGeneration=" + scenarioGenerationSeen + " tickAgeMs=" + age + " onCount=" + drivingOnCount);
                }
                else
                {
                    bool hard = DrivingOffReasons.IsHard(step.OffReason);
                    drivingLastOffReason = step.OffReason;
                    if (hard)
                    {
                        drivingHardOffCount++;
                    }
                    else
                    {
                        drivingSoftOffCount++;
                    }

                    ObsA("DRIVING_ACTIVE_OFF", "reason=" + DrivingOffReasons.Name(step.OffReason) + " class=" + (hard ? "hard" : "soft") + " ScenarioGeneration=" + scenarioGenerationSeen + " tickAgeMs=" + age + " activeForMs=" + Math.Round(HandshakeProtocol.QpcToMs(now - drivingOnQpc), 1).ToString(System.Globalization.CultureInfo.InvariantCulture));
                }
            }
            catch (Exception ex)
            {
                if (drivingExceptionLines < 3)
                {
                    drivingExceptionLines++;
                    ObsA("DRIVING_EXCEPTION", "type=" + ex.GetType().Name);
                }
            }
        }

        /// <summary>
        /// Phase E1: feeds the AppController dry-run with what DrivingActive just decided (monitor thread, gate held, right after
        /// EvaluateDrivingLocked). Only decisions are logged; nothing is started or sent. Never throws.
        /// </summary>
        private void ObserveAppControllerLocked()
        {
            try
            {
                LogAppStepLocked(appController.Observe(driving.Active, scenarioReadyLevel, scenarioGenerationSeen));
            }
            catch (Exception ex)
            {
                LogAppExceptionLocked(ex);
            }
        }

        /// <summary>
        /// Phase E4: hands the two levels the Caller already decided to the managed application (monitor thread, gate held, right after
        /// EvaluateDrivingLocked; and once from End()). Session = ScenarioReady is published for the current ScenarioGeneration (never while
        /// Dispose began); Driving = the D1 DrivingActive result, only ever with Session. The manager remembers it and writes it only when it
        /// changed, so this costs a lock and a compare on an unchanged state. No log here, no I/O, no process action. Never throws.
        /// </summary>
        private void PublishAppStateLocked()
        {
            try
            {
                if (appProcess != null)
                {
                    bool session = scenarioReadyLevel && phase != CallerPhase.Disposed;
                    bool load = scenarioLoadSupported && phase != CallerPhase.Disposed;   // Phase SI-A6: a withdrawn state carries no marker
                    appProcess.PublishStateWithLoad(session, session && driving.Active, scenarioGenerationSeen, load ? scenarioLoadInfo : 0u, load);
                }
            }
            catch (Exception ex)
            {
                LogAppExceptionLocked(ex);
            }
        }

        /// <summary>Phase E1: Dispose began (gate held). The controller records the one stop request, or notes that there is nothing to stop. Never throws.</summary>
        private void DisposeAppControllerLocked()
        {
            try
            {
                LogAppStepLocked(appController.OnDispose());
            }
            catch (Exception ex)
            {
                LogAppExceptionLocked(ex);
            }
        }

        private void LogAppStepLocked(AppStep step)
        {
            switch (step.Action)
            {
                case AppAction.StartRequested:
                    ObsA("APP_START_REQUEST", "pid=" + pid + " ScenarioGeneration=" + step.ScenarioGeneration + " requestNo=" + step.RequestNumber + " reason=" + AppRequestReasons.FirstDrivingOn + " dryRun=yes");
                    RequestAppLaunchLocked(step); // Phase E3: the decision above is acted on by the process manager (its own APP_LAUNCH_* / APP_* lines say what happened)
                    break;

                case AppAction.StartSuppressed:
                    ObsA("APP_START_SUPPRESSED", "pid=" + pid + " ScenarioGeneration=" + step.ScenarioGeneration + " requestNo=" + step.RequestNumber + " reason=" + AppRequestReasons.AlreadyRequestedForGeneration + " dryRun=yes");
                    break;

                case AppAction.StopRequested:
                    ObsA("APP_STOP_REQUEST", "pid=" + pid + " requestNo=" + step.RequestNumber + " reason=" + AppRequestReasons.CallerDispose + " startRequests=" + appController.StartRequestCount + " lastScenarioGeneration=" + step.ScenarioGeneration + " dryRun=yes");
                    break;

                case AppAction.StopNotRequired:
                    ObsA("APP_STOP_NOT_REQUIRED", "pid=" + pid + " reason=" + AppRequestReasons.NoStartRequest + " dryRun=yes");
                    break;
            }
        }

        /// <summary>Phase E3: forwards one start request to the process manager (monitor thread, gate held). Cheap: a lock and one thread start. Never throws.</summary>
        private void RequestAppLaunchLocked(AppStep step)
        {
            try
            {
                if (appProcess != null)
                {
                    appProcess.RequestStart(step.ScenarioGeneration, step.RequestNumber);
                }
            }
            catch (Exception ex)
            {
                LogAppExceptionLocked(ex);
            }
        }

        /// <summary>Phase E3: Dispose reached the process manager (called by End() AFTER the gate was released). Bounded; never throws.</summary>
        private void ShutdownAppProcess()
        {
            try
            {
                if (appProcess != null)
                {
                    appProcess.Shutdown();
                }
            }
            catch (Exception ex)
            {
                lock (gate)
                {
                    LogAppExceptionLocked(ex);
                }
            }
        }

        private void LogAppProcess(string evt, string detail)
        {
            ObsA(evt, detail);
        }

        private void LogAppExceptionLocked(Exception ex)
        {
            try
            {
                if (appExceptionLines < 3)
                {
                    appExceptionLines++;
                    ObsA("APP_EXCEPTION", "type=" + ex.GetType().Name);
                }
            }
            catch
            {
            }
        }

        private static void Release(ref EventWaitHandle handle)
        {
            try
            {
                if (handle != null)
                {
                    handle.Dispose();
                }
            }
            catch
            {
            }

            handle = null;
        }

        private void MonitorLoop()
        {
            Interlocked.Increment(ref LiveMonitors);
            try
            {
                ManualResetEvent signal;
                lock (gate) { signal = wake; }
                Obs("MONITOR_LOOP_BEGIN", "sinceEnabledMs=" + SinceEnabledMs(Stopwatch.GetTimestamp()));

                // WaitOne returns true as soon as End() sets the signal, so the thread ends promptly; otherwise it ticks every CallerPollMs.
                while (!signal.WaitOne(HandshakeTiming.CallerPollMs))
                {
                    Step();
                }
            }
            catch
            {
                // a monitor must never take BVE down
            }
            finally
            {
                Interlocked.Decrement(ref LiveMonitors);
            }
        }

        private void Step()
        {
            try
            {
                lock (gate)
                {
                    if (phase == CallerPhase.Disposed || phase == CallerPhase.Disabled)
                    {
                        return;
                    }

                    long now = Stopwatch.GetTimestamp();
                    bridgePresent = SignalledLocked(ref bridge, HandshakeProtocol.BridgeAvailableName(pid));
                    readyPresent = bridgePresent && SignalledLocked(ref ready, HandshakeProtocol.ReadyName(pid));

                    if (!firstCheckLogged)
                    {
                        firstCheckLogged = true;
                        Obs("AVAIL_FIRST_CHECK", "result=" + (bridgePresent ? "Present" : "Missing") + " sinceEnabledMs=" + SinceEnabledMs(now));
                    }

                    switch (phase)
                    {
                        case CallerPhase.WaitingForBridge:
                            if (bridgePresent)
                            {
                                OnBridgeSeenLocked(now);
                            }
                            else
                            {
                                CheckBridgeTimeoutLocked(now);
                            }

                            break;

                        case CallerPhase.BridgeMissingTimedOut:
                            if (bridgePresent)
                            {
                                OnBridgeSeenLocked(now); // the Bridge is back: re-arm, then wait for the handshake
                            }

                            break;

                        case CallerPhase.BridgeAvailable:
                        case CallerPhase.WaitingForHandshake:
                            if (!bridgePresent)
                            {
                                OnBridgeLostLocked(now);
                            }
                            else if (readyPresent)
                            {
                                OnReadyLocked(now);
                            }

                            break;

                        case CallerPhase.Connected:
                            if (!bridgePresent)
                            {
                                OnBridgeLostLocked(now);
                            }
                            else if (readyPresent)
                            {
                                readyLastQpc = now;
                            }
                            else
                            {
                                // Ready vanished but the Bridge is still there: BveEX is on, the handshake is only interrupted. No notice.
                                readyLostCount++;
                                readyLostQpc = now;
                                handshakeStartQpc = now;
                                phase = CallerPhase.WaitingForHandshake;
                                Obs("READY_LOST", "bridgeStillPresent=Y count=" + readyLostCount + " sinceEnabledMs=" + SinceEnabledMs(now));
                            }

                            break;
                    }

                    JudgeFirstTickLocked(now);
                    ObserveScenarioLocked(now);
                    EvaluateDrivingLocked(now);
                    PublishAppStateLocked();   // Phase E4: BEFORE the controller, so a start request always finds the current state remembered
                    ObserveAppControllerLocked();
                }
            }
            catch (ObjectDisposedException)
            {
                // handle released by a concurrent End(): nothing left to watch
            }
            catch
            {
            }
        }

        /// <summary>An event counts as present only while it exists AND is signalled. Gate must be held.</summary>
        private static bool SignalledLocked(ref EventWaitHandle handle, string name)
        {
            try
            {
                if (handle == null)
                {
                    EventWaitHandle candidate;
                    if (!EventWaitHandle.TryOpenExisting(name, EventWaitHandleRights.Synchronize, out candidate))
                    {
                        return false;
                    }

                    handle = candidate;
                }

                return handle.WaitOne(0);
            }
            catch (ObjectDisposedException)
            {
                handle = null;
                return false;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// The one-time dependency check of Phase M1, run by the monitor thread after BVE's first Tick. BridgeAvailable is looked at
        /// DIRECTLY (the named event, right now); the cached state, Ready, the Bridge kind and everything about the scenario are not consulted.
        /// Present: nothing happens and the notice latch stays free. Missing: the first-use notice is requested (once per instance).
        /// </summary>
        private void JudgeFirstTickLocked(long now)
        {
            if (firstTickJudged || !tickSeen || phase == CallerPhase.Disposed)
            {
                return;
            }

            firstTickJudged = true;
            bool cached = bridgePresent;
            bool direct = ProbeBridgeDirectLocked();
            Obs("FIRST_TICK_SEEN", "sinceEnabledMs=" + SinceEnabledMs(firstTickQpc) + " lagMs=" + Math.Round(HandshakeProtocol.QpcToMs(now - firstTickQpc), 1) + " phase=" + phase);

            bool request = !direct && !noticeShown && !noticeInFlight;
            Obs("FIRST_TICK_JUDGE", "bridgeDirect=" + (direct ? "Present" : "Missing") + " bridgeCached=" + (cached ? "Present" : "Missing") + " noticeShown=" + (noticeShown ? "yes" : "no") + " noticeInFlight=" + (noticeInFlight ? "yes" : "no") + " decision=" + (direct ? "no-notice-bridge-present" : request ? "request-notice" : "no-notice-already-handled"));
            if (request)
            {
                StartNoticeLocked(NoticeTrigger.FirstUse, now);
            }
        }

        /// <summary>
        /// BridgeAvailable, checked directly: our own cached handle is dropped first (an open handle of ours would keep a dead named
        /// object alive), then the event is opened by name and must exist AND be signalled. Gate must be held.
        /// </summary>
        private bool ProbeBridgeDirectLocked()
        {
            Release(ref bridge);
            if (bridgeProbeOverride != null)
            {
                try { return bridgeProbeOverride(); } catch { return false; }
            }

            return SignalledLocked(ref bridge, HandshakeProtocol.BridgeAvailableName(pid));
        }

        private DependencyState StateLocked()
        {
            switch (phase)
            {
                case CallerPhase.BridgeAvailable:
                case CallerPhase.WaitingForHandshake:
                case CallerPhase.Connected:
                    return DependencyState.Connected;
            }

            if (bridgeSeenCount > 0)
            {
                return phase == CallerPhase.BridgeMissingTimedOut ? DependencyState.ConnectionLost : DependencyState.Connected;
            }

            return tickSeen ? DependencyState.UseStarted : DependencyState.StartupWaiting;
        }

        private void StartNoticeLocked(NoticeTrigger trigger, long now)
        {
            noticeInFlight = true;
            noticeTriggerQpc = now;
            Thread thread = new Thread(() => ShowNoticeIfStillNeeded(trigger));
            thread.IsBackground = true;
            thread.Name = "TSScoringPlugin.Caller.Notice";
            thread.Start();
        }

        private void OnBridgeSeenLocked(long now)
        {
            CallerPhase phaseBefore = phase;
            bool noticeWasShownThisAbsence = noticeShown;
            phase = CallerPhase.BridgeAvailable;
            bridgeSeenCount++;
            latestBridgeDetectMs = HandshakeProtocol.QpcToMs(now - absenceStartQpc);
            if (bridgeFirstSeenQpc == 0)
            {
                bridgeFirstSeenQpc = now;
                firstBridgeDetectMs = latestBridgeDetectMs;
            }

            if (latestBridgeDetectMs > HandshakeTiming.TargetBridgeAvailableMs)
            {
                missedBridgeTarget = true;
            }

            timeoutLoggedThisAbsence = false; // the absence stretch is over (the notice latch is NOT re-armed: one notice per instance)
            handshakeStartQpc = now;

            Obs(firstAvailLogged ? "AVAIL_SEEN" : "AVAIL_FIRST_PRESENT", "phaseBefore=" + phaseBefore + " sinceEnabledMs=" + SinceEnabledMs(now) + " absentMs=" + Math.Round(latestBridgeDetectMs, 1) + " over500=" + (latestBridgeDetectMs > HandshakeTiming.TargetBridgeAvailableMs ? "yes" : "no") + " noticeShownThisAbsence=" + (noticeWasShownThisAbsence ? "yes" : "no") + " seenCount=" + bridgeSeenCount);
            firstAvailLogged = true;

            if (readyPresent)
            {
                OnReadyLocked(now);
            }
            else
            {
                phase = CallerPhase.WaitingForHandshake;
            }
        }

        private void OnReadyLocked(long now)
        {
            phase = CallerPhase.Connected;
            readyConnectCount++;
            readyLastQpc = now;
            latestHandshakeMs = HandshakeProtocol.QpcToMs(now - handshakeStartQpc);
            Obs(firstReadyLogged ? "READY_CONNECTED" : "READY_FIRST_PRESENT", "sinceEnabledMs=" + SinceEnabledMs(now) + " handshakeMs=" + Math.Round(latestHandshakeMs, 1) + " connectCount=" + readyConnectCount);
            firstReadyLogged = true;
        }

        private void OnBridgeLostLocked(long now)
        {
            if (phase == CallerPhase.Connected)
            {
                readyLostCount++;
                readyLostQpc = now;
            }

            CallerPhase lostFrom = phase;
            phase = CallerPhase.WaitingForBridge;
            bridgeLostCount++;
            bridgeLostQpc = now;
            absenceStartQpc = now;          // a NEW absence stretch
            timeoutLoggedThisAbsence = false;
            Obs("AVAIL_LOST", "phaseBefore=" + lostFrom + " sinceEnabledMs=" + SinceEnabledMs(now) + " lostCount=" + bridgeLostCount);
        }

        private void CheckBridgeTimeoutLocked(long now)
        {
            double missingMs = HandshakeProtocol.QpcToMs(now - absenceStartQpc);
            if (missingMs > HandshakeTiming.TargetBridgeAvailableMs)
            {
                missedBridgeTarget = true;
            }

            // Two different waits (Phase M1): before BridgeAvailable was ever seen the wait is the START-UP diagnostic (1000 ms): one log
            // line, no dialog, the notice latch and the first-Tick judgement untouched (a scenario list without Tick has nothing to complain
            // about; the first Tick decides). After it was seen once, losing it for ConnectionLostNoticeMs (500 ms) is a lost connection.
            bool startup = bridgeSeenCount == 0;
            if (missingMs < (startup ? CallerNoticeTiming.StartupBridgeDiagnosticMs : CallerNoticeTiming.ConnectionLostNoticeMs))
            {
                return;
            }

            phase = CallerPhase.BridgeMissingTimedOut;
            timedOutEver = true;

            if (startup)
            {
                if (!startupDiagLogged)
                {
                    startupDiagLogged = true;
                    Obs("STARTUP_BRIDGE_DELAY", "startupDiagnosticMs=" + CallerNoticeTiming.StartupBridgeDiagnosticMs + " missingMs=" + Math.Round(missingMs, 1) + " sinceEnabledMs=" + SinceEnabledMs(now) + " firstTickSeen=" + (tickSeen ? "yes" : "no") + " noticeShown=" + (noticeShown ? "yes" : "no") + " userVisible=no");
                }

                return;
            }

            if (!timeoutLoggedThisAbsence)
            {
                timeoutLoggedThisAbsence = true;
                timeoutReachedQpc = now;
                Obs("TIMEOUT_REACHED", "timeoutMs=" + CallerNoticeTiming.ConnectionLostNoticeMs + " missingMs=" + Math.Round(missingMs, 1) + " sinceEnabledMs=" + SinceEnabledMs(now) + " noticeArmed=" + (!noticeShown && !noticeInFlight ? "yes" : "no") + " kind=connection-lost firstTickSeen=" + (tickSeen ? "yes" : "no"));
            }

            if (!noticeShown && !noticeInFlight)
            {
                StartNoticeLocked(NoticeTrigger.ConnectionLost, now);
            }
        }

        /// <summary>Phase C1 observation: one log line tagged Track B and with this enabled-cycle's number. Never throws.</summary>
        private void Obs(string evt, string detail)
        {
            ObservationLog.Write("B", evt, "cycle=" + cycleNo + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail));
        }

        /// <summary>Phase C3: one log line tagged Track A (scenario life cycle) with this enabled-cycle's number. Never throws.</summary>
        private void ObsA(string evt, string detail)
        {
            ObservationLog.Write("A", evt, "cycle=" + cycleNo + (string.IsNullOrEmpty(detail) ? string.Empty : " " + detail));
        }

        private double SinceEnabledMs(long nowQpc)
        {
            return enabledQpc == 0 ? -1 : Math.Round(HandshakeProtocol.QpcToMs(nowQpc - enabledQpc), 1);
        }

        /// <summary>
        /// Phase C3: reads ScenarioReady (event + state block of this BVE process). ScenarioReady counts only while Ready (and so
        /// BridgeAvailable) is present and BOTH the event is set and the validated block says level 1 for this PID. Transitions are logged;
        /// the handles are opened lazily and released as soon as Ready is gone. Gate must be held.
        /// </summary>
        private void ObserveScenarioLocked(long now)
        {
            bool level = false;
            bool valid = false;
            ScenarioState state = new ScenarioState();

            if (readyPresent)
            {
                if (OpenScenarioObjectsLocked())
                {
                    bool eventSet = false;
                    try { eventSet = scenarioEvent.WaitOne(0); }
                    catch (ObjectDisposedException) { scenarioEvent = null; }

                    valid = scenarioView != null && ScenarioState.TryReadView(scenarioView, pid, out state);
                    level = valid && eventSet && state.Ready;
                }
            }
            else
            {
                ReleaseScenarioObjectsLocked();
            }

            // Phase SI-A6: the load marker of the SAME reading as the generation (one seqlock read); no valid reading = no information
            scenarioLoadSupported = valid && state.LoadSupported;
            scenarioLoadInfo = scenarioLoadSupported ? (uint)state.LoadInfo : 0u;

            if (valid && state.ScenarioGeneration != scenarioGenerationSeen)
            {
                int from = scenarioGenerationSeen;
                scenarioGenerationSeen = state.ScenarioGeneration;
                scenarioGenerationChanges++;
                ObsA("SCN_GENERATION_CHANGED", "from=" + from + " to=" + scenarioGenerationSeen + " ready=" + (level ? "Y" : "N") + " sinceEnabledMs=" + SinceEnabledMs(now));
            }

            if (level != scenarioReadyLevel)
            {
                scenarioReadyLevel = level;
                if (level)
                {
                    scenarioReadyOnCount++;
                    ObsA("SCN_READY_ON", "ScenarioGeneration=" + scenarioGenerationSeen + " sinceEnabledMs=" + SinceEnabledMs(now) + " onCount=" + scenarioReadyOnCount);
                }
                else
                {
                    scenarioReadyOffCount++;
                    string why = !bridgePresent ? "bridge-lost" : !readyPresent ? "ready-lost" : "level-false";
                    ObsA("SCN_READY_OFF", "ScenarioGeneration=" + scenarioGenerationSeen + " reason=" + why + " sinceEnabledMs=" + SinceEnabledMs(now) + " offCount=" + scenarioReadyOffCount);
                }
            }
        }

        /// <summary>Opens the ScenarioReady event and the state block when they exist. False while either is missing. Gate must be held.</summary>
        private bool OpenScenarioObjectsLocked()
        {
            try
            {
                if (scenarioEvent == null)
                {
                    EventWaitHandle candidate;
                    if (!EventWaitHandle.TryOpenExisting(HandshakeProtocol.ScenarioReadyName(pid), EventWaitHandleRights.Synchronize, out candidate))
                    {
                        return false;
                    }

                    scenarioEvent = candidate;
                }

                if (scenarioView == null)
                {
                    MemoryMappedFile section = null;
                    try
                    {
                        section = MemoryMappedFile.OpenExisting(HandshakeProtocol.ScenarioStateName(pid), MemoryMappedFileRights.Read);
                        scenarioView = section.CreateViewAccessor(0, ScenarioState.Size, MemoryMappedFileAccess.Read);
                        scenarioSection = section;
                    }
                    catch
                    {
                        if (section != null)
                        {
                            try { section.Dispose(); } catch { }
                        }

                        scenarioView = null;
                        scenarioSection = null;
                        return false;
                    }
                }

                return true;
            }
            catch
            {
                return false;
            }
        }

        private void ReleaseScenarioObjectsLocked()
        {
            EventWaitHandle e = scenarioEvent;
            scenarioEvent = null;
            if (e != null)
            {
                try { e.Dispose(); } catch { }
            }

            MemoryMappedViewAccessor v = scenarioView;
            scenarioView = null;
            if (v != null)
            {
                try { v.Dispose(); } catch { }
            }

            MemoryMappedFile s = scenarioSection;
            scenarioSection = null;
            if (s != null)
            {
                try { s.Dispose(); } catch { }
            }
        }

        /// <summary>Runs on its own short-lived thread so the monitor keeps watching while a dialog is open.</summary>
        private void ShowNoticeIfStillNeeded(NoticeTrigger trigger)
        {
            try
            {
                bool show;
                string decision;
                lock (gate)
                {
                    judgeQpc = Stopwatch.GetTimestamp();
                    string lag = Math.Round(HandshakeProtocol.QpcToMs(judgeQpc - (trigger == NoticeTrigger.FirstUse ? noticeTriggerQpc : timeoutReachedQpc)), 1).ToString(System.Globalization.CultureInfo.InvariantCulture);
                    Obs("NOTICE_JUDGE_BEGIN", (trigger == NoticeTrigger.FirstUse ? "lagSinceFirstUseMs=" : "lagSinceTimeoutMs=") + lag + " sinceEnabledMs=" + SinceEnabledMs(judgeQpc) + " trigger=" + (trigger == NoticeTrigger.FirstUse ? "first-use" : "connection-lost"));

                    // Re-check everything right before showing: still enabled, not disposed, no notice yet, and BridgeAvailable still
                    // missing when looked at DIRECTLY. A connection-lost notice additionally needs the 500 ms timeout state to still hold.
                    // (Split only so the log can say which part decided.)
                    bool stateHolds = trigger == NoticeTrigger.ConnectionLost ? phase == CallerPhase.BridgeMissingTimedOut : phase != CallerPhase.Disposed;
                    bool bridgeAtRecheck = false;
                    if (stateHolds && started && !noticeShown)
                    {
                        bridgeAtRecheck = ProbeBridgeDirectLocked();
                    }

                    show = stateHolds && started && !noticeShown && !bridgeAtRecheck;
                    decision = show ? "bridge-still-missing" : !stateHolds ? "phase-changed-" + phase : !started ? "not-started" : noticeShown ? "already-noticed" : "bridge-present-at-recheck";
                    Obs("NOTICE_PRESHOW", "decision=" + (show ? "show" : "suppress") + " reason=" + decision + " bridgeAtRecheck=" + (stateHolds && started && !noticeShown ? (bridgeAtRecheck ? "Present" : "Missing") : "NotChecked") + " phase=" + phase);
                    if (show)
                    {
                        noticeShown = true; // the latch: this Caller instance never notices again
                        noticeCount++;
                    }
                }

                if (show)
                {
                    // Diagnostic only (never changes the decision above): is the Bridge present at the very moment the dialog is requested?
                    string atCall = "NotChecked";
                    lock (gate)
                    {
                        if (phase != CallerPhase.Disposed)
                        {
                            atCall = ProbeBridgeDirectLocked() ? "Present" : "Missing";
                        }
                    }

                    long callQpc = Stopwatch.GetTimestamp();
                    Obs("NOTICE_SHOW_CALL", "bridgeAtCall=" + atCall + " gapSinceRecheckMs=" + Math.Round(HandshakeProtocol.QpcToMs(callQpc - judgeQpc), 1) + " sinceEnabledMs=" + SinceEnabledMs(callQpc));
                    showNotice(NoticeText);
                    Obs("NOTICE_DIALOG_CLOSED", "openMs=" + Math.Round(HandshakeProtocol.QpcToMs(Stopwatch.GetTimestamp() - callQpc), 1));
                }
                else
                {
                    Obs("NOTICE_SUPPRESSED", "reason=" + decision);
                }
            }
            catch
            {
            }
            finally
            {
                lock (gate)
                {
                    noticeInFlight = false;
                }
            }
        }

        private static string CombinedState(CallerPhase p)
        {
            switch (p)
            {
                case CallerPhase.Connected:
                    return "Connected";
                case CallerPhase.BridgeAvailable:
                case CallerPhase.WaitingForHandshake:
                    return "Bridge loaded, waiting for handshake";
                case CallerPhase.BridgeMissingTimedOut:
                    return "Bridge missing, timed out";
                case CallerPhase.Disposed:
                    return "Disposed";
                case CallerPhase.Disabled:
                    return "Disabled";
                default:
                    return "Waiting for Bridge";
            }
        }

        private static string ClockAgo(long nowQpc, long thenQpc)
        {
            if (thenQpc == 0)
            {
                return "-";
            }

            return DateTime.Now.AddMilliseconds(-HandshakeProtocol.QpcToMs(nowQpc - thenQpc)).ToString("HH:mm:ss.fff");
        }

        private static string Ms(double value)
        {
            return value >= 0 ? value.ToString("F1") + " ms" : "-";
        }

        /// <summary>Text for the single Configure dialog (read-only snapshot; the monitor thread does all state changes).</summary>
        public string BuildStatusText()
        {
            StringBuilder sb = new StringBuilder();
            long nowQpc = Stopwatch.GetTimestamp();
            bool readyNow;
            lock (gate)
            {
                readyNow = phase == CallerPhase.Connected;
                bool isEnabled = started && phase != CallerPhase.Disposed;

                sb.AppendLine("Product : " + ProductDisplayName);
                sb.AppendLine("Provider: " + ProviderName);
                sb.AppendLine("Phase   : C3 build " + ObservationLog.Version + " (Phase B handshake behaviour + ScenarioReady, Current BveEX mode)");
                sb.AppendLine("Log     : " + ObservationLog.FolderName + "\\" + ObservationLog.FileName);
                sb.AppendLine("Assembly: " + Assembly.GetExecutingAssembly().GetName().Name + ".dll");
                sb.AppendLine();
                sb.AppendLine("Caller           : " + (isEnabled ? "Enabled" : "Disabled"));
                sb.AppendLine("Dependency state : " + phase);
                sb.AppendLine("BridgeAvailable  : " + (isEnabled && bridgePresent ? "Present" : "Missing"));
                sb.AppendLine("Ready            : " + (isEnabled && readyPresent ? "Present" : "Missing"));
                sb.AppendLine("Combined state   : " + CombinedState(phase));
                sb.AppendLine("ScenarioReady    : " + (isEnabled && scenarioReadyLevel ? "Yes" : "No") + "   (not the same as Ready; stays Yes on the title screen until the scenario is closed)");
                sb.AppendLine("ScenarioGeneration: " + (scenarioGenerationSeen > 0 ? scenarioGenerationSeen.ToString() : "-") + "   (changes seen: " + scenarioGenerationChanges + ", Ready on/off: " + scenarioReadyOnCount + "/" + scenarioReadyOffCount + ")");
                sb.AppendLine("BVE PID : " + pid + "   (" + (Environment.Is64BitProcess ? "64-bit" : "32-bit") + ")");
                sb.AppendLine();
                sb.AppendLine("Enabled object          : " + HandshakeProtocol.EnabledName(pid));
                sb.AppendLine("BridgeAvailable object  : " + HandshakeProtocol.BridgeAvailableName(pid));
                sb.AppendLine("Ready object            : " + HandshakeProtocol.ReadyName(pid));
                sb.AppendLine("Stop object             : " + HandshakeProtocol.StopName(pid));
                sb.AppendLine("ScenarioReady object    : " + HandshakeProtocol.ScenarioReadyName(pid));
                sb.AppendLine("ScenarioState object    : " + HandshakeProtocol.ScenarioStateName(pid));
                sb.AppendLine();
                sb.AppendLine("Enabled created              : " + (enabledQpc != 0 ? enabledLocal.ToString("HH:mm:ss.fff") : "-"));
                sb.AppendLine("BridgeAvailable first seen    : " + ClockAgo(nowQpc, bridgeFirstSeenQpc));
                sb.AppendLine("BridgeAvailable lost at       : " + (bridgeLostCount > 0 ? ClockAgo(nowQpc, bridgeLostQpc) : "-"));
                sb.AppendLine("Ready last confirmed          : " + (readyConnectCount > 0 ? ClockAgo(nowQpc, readyLastQpc) : "-"));
                sb.AppendLine("Ready lost at                 : " + (readyLostCount > 0 ? ClockAgo(nowQpc, readyLostQpc) : "-"));
                sb.AppendLine("Time to BridgeAvailable (first / latest): " + Ms(firstBridgeDetectMs) + " / " + Ms(latestBridgeDetectMs));
                sb.AppendLine("Latest handshake time (Bridge seen or Ready lost -> Ready): " + Ms(latestHandshakeMs));
                sb.AppendLine("Over the " + HandshakeTiming.TargetBridgeAvailableMs + " ms BridgeAvailable target: " + (missedBridgeTarget ? "yes" : "no"));
                sb.AppendLine("Bridge-missing timeout (" + CallerNoticeTiming.ConnectionLostNoticeMs + " ms) occurred: " + (timedOutEver ? "yes" : "no"));
                sb.AppendLine("Notice shown : " + (noticeCount > 0 ? "yes (" + noticeCount + "x)" : "no"));
                sb.AppendLine("Bridge seen " + bridgeSeenCount + "x, lost " + bridgeLostCount + "x;  Ready connected " + readyConnectCount + "x, lost " + readyLostCount + "x");
            }

            BridgeInfo info;
            if (readyNow && BridgeInfo.TryRead(pid, out info))
            {
                sb.AppendLine();
                sb.AppendLine("BridgeInfo: Available (Phase B measurement, " + (info.Bitness == 64 ? "64-bit" : "32-bit") + ")");
                sb.AppendLine("  Bridge load -> BridgeAvailable created: " + HandshakeProtocol.QpcToMs(info.AvailableCreatedQpc - info.BridgeLoadQpc).ToString("F1") + " ms");
                sb.AppendLine("  Bridge load -> latest Ready created   : " + HandshakeProtocol.QpcToMs(info.ReadyCreatedQpc - info.BridgeLoadQpc).ToString("F1") + " ms");
                sb.AppendLine("  BridgeAvailable created " + info.AvailableCreateCount + "x / destroyed " + info.AvailableDestroyCount + "x;  Ready created " + info.ReadyCreateCount + "x / destroyed " + info.ReadyDestroyCount + "x");
                sb.AppendLine("  Last Enabled seen / Stop seen: " + ClockAgo(nowQpc, info.LastEnabledSeenQpc) + " / " + ClockAgo(nowQpc, info.LastStopSeenQpc));
            }
            else
            {
                sb.AppendLine();
                sb.AppendLine("BridgeInfo: Unavailable");
            }

            return sb.ToString();
        }
    }
}
