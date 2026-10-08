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
    /// One "enabled cycle" of the Caller (Load .. Dispose). Publishes Enabled/Stop and watches the Bridge on ONE background monitor thread:
    ///
    ///   WaitingForBridge --BridgeAvailable seen--> (BridgeAvailable) --> WaitingForHandshake --Ready--> Connected
    ///   Connected --Ready lost, Bridge still there--> WaitingForHandshake
    ///   any --BridgeAvailable lost--> WaitingForBridge (a new absence stretch)
    ///   WaitingForBridge --absent for BridgeMissingTimeoutMs--> BridgeMissingTimedOut (ONE notice per absence stretch)
    ///   BridgeMissingTimedOut --BridgeAvailable back--> WaitingForHandshake (notice re-armed)
    ///
    /// Only the absence of BridgeAvailable means "BveEX / the Bridge is not there". A missing Ready (BveEX's Tick runs only while a
    /// scenario is driven) and a missing scenario never produce the BveEX notice and have no timeout.
    /// Nothing here runs on BVE's threads except the cheap Start/End calls.
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
        private long timeoutReachedQpc;
        private long judgeQpc;

        // Phase C3: ScenarioReady as seen from the Caller. Read only: transitions are written to the log, nothing else reacts to them yet.
        private EventWaitHandle scenarioEvent;
        private MemoryMappedFile scenarioSection;
        private MemoryMappedViewAccessor scenarioView;
        private bool scenarioReadyLevel;
        private int scenarioGenerationSeen;      // last valid ScenarioGeneration read (0 = none yet)
        private int scenarioReadyOnCount;
        private int scenarioReadyOffCount;
        private int scenarioGenerationChanges;

        private bool noticedThisAbsence;
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
            : this(HandshakeProtocol.CurrentProcessId(), DefaultShowNotice)
        {
        }

        /// <summary>Test constructor: explicit PID and a notice sink that can be a test double.</summary>
        internal HandshakeSession(int pid, Action<string> showNotice)
        {
            this.pid = pid;
            this.showNotice = showNotice ?? DefaultShowNotice;
        }

        internal CallerPhase Phase { get { lock (gate) { return phase; } } }
        internal int NoticeCount { get { lock (gate) { return noticeCount; } } }
        internal int BridgeSeenCount { get { lock (gate) { return bridgeSeenCount; } } }
        internal int BridgeLostCount { get { lock (gate) { return bridgeLostCount; } } }
        internal int ReadyConnectCount { get { lock (gate) { return readyConnectCount; } } }
        internal int ReadyLostCount { get { lock (gate) { return readyLostCount; } } }
        internal bool NoticeArmed { get { lock (gate) { return !noticedThisAbsence; } } }
        internal bool MissedBridgeTarget { get { lock (gate) { return missedBridgeTarget; } } }
        internal bool MonitorAlive { get { Thread t; lock (gate) { t = monitor; } return t != null && t.IsAlive; } }
        internal bool ScenarioReadyLevel { get { lock (gate) { return scenarioReadyLevel; } } }
        internal int ScenarioGenerationSeen { get { lock (gate) { return scenarioGenerationSeen; } } }
        internal int ScenarioReadyOnCount { get { lock (gate) { return scenarioReadyOnCount; } } }
        internal int ScenarioReadyOffCount { get { lock (gate) { return scenarioReadyOffCount; } } }
        internal int ScenarioGenerationChanges { get { lock (gate) { return scenarioGenerationChanges; } } }

        private static void DefaultShowNotice(string text)
        {
            MessageBoxW(IntPtr.Zero, text, ProductDisplayName, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST);
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

                    ObserveScenarioLocked(now);
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

        private void OnBridgeSeenLocked(long now)
        {
            CallerPhase phaseBefore = phase;
            bool noticeWasShownThisAbsence = noticedThisAbsence;
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

            noticedThisAbsence = false; // the absence stretch is over: re-arm the notice for the next one
            timeoutLoggedThisAbsence = false;
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
            noticedThisAbsence = false;
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

            if (missingMs < HandshakeTiming.BridgeMissingTimeoutMs)
            {
                return;
            }

            phase = CallerPhase.BridgeMissingTimedOut;
            timedOutEver = true;
            if (!timeoutLoggedThisAbsence)
            {
                timeoutLoggedThisAbsence = true;
                timeoutReachedQpc = now;
                Obs("TIMEOUT_REACHED", "timeoutMs=" + HandshakeTiming.BridgeMissingTimeoutMs + " missingMs=" + Math.Round(missingMs, 1) + " sinceEnabledMs=" + SinceEnabledMs(now) + " noticeArmed=" + (!noticedThisAbsence && !noticeInFlight ? "yes" : "no"));
            }

            if (!noticedThisAbsence && !noticeInFlight)
            {
                noticedThisAbsence = true;
                noticeInFlight = true;
                Thread thread = new Thread(ShowNoticeIfStillNeeded);
                thread.IsBackground = true;
                thread.Name = "TSScoringPlugin.Caller.Notice";
                thread.Start();
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
        private void ShowNoticeIfStillNeeded()
        {
            try
            {
                bool show;
                string decision;
                lock (gate)
                {
                    judgeQpc = Stopwatch.GetTimestamp();
                    Obs("NOTICE_JUDGE_BEGIN", "lagSinceTimeoutMs=" + Math.Round(HandshakeProtocol.QpcToMs(judgeQpc - timeoutReachedQpc), 1) + " sinceEnabledMs=" + SinceEnabledMs(judgeQpc));

                    // Re-check everything right before showing: still enabled, not disposed, Bridge still absent, still timed out.
                    // (Same single condition as Phase B; split only so the log can say which part decided.)
                    bool phaseTimedOut = phase == CallerPhase.BridgeMissingTimedOut;
                    bool bridgeAtRecheck = false;
                    if (phaseTimedOut && started)
                    {
                        bridgeAtRecheck = SignalledLocked(ref bridge, HandshakeProtocol.BridgeAvailableName(pid));
                    }

                    show = phaseTimedOut && started && !bridgeAtRecheck;
                    decision = show ? "bridge-still-missing" : !phaseTimedOut ? "phase-changed-" + phase : !started ? "not-started" : "bridge-present-at-recheck";
                    Obs("NOTICE_PRESHOW", "decision=" + (show ? "show" : "suppress") + " reason=" + decision + " bridgeAtRecheck=" + (phaseTimedOut && started ? (bridgeAtRecheck ? "Present" : "Missing") : "NotChecked") + " phase=" + phase);
                    if (show)
                    {
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
                            atCall = SignalledLocked(ref bridge, HandshakeProtocol.BridgeAvailableName(pid)) ? "Present" : "Missing";
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
                sb.AppendLine("Bridge-missing timeout (" + HandshakeTiming.BridgeMissingTimeoutMs + " ms) occurred: " + (timedOutEver ? "yes" : "no"));
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
