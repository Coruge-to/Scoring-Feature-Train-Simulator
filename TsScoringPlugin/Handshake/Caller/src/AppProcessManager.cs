using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Security.AccessControl;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

// ============================================================================
// PHASE E3 - the managed application PROCESS of one Caller instance: start it, see AppReady, stop it at Dispose.
//
// Who does what:
//   AppController (E1, pure)   decides WHEN a start / stop would be requested (one start request per ScenarioGeneration, one stop at Dispose).
//   AppProcessManager (here)   turns a start request into AT MOST ONE real process and owns everything about it: the launcher configuration,
//                              the instance id, the Stop event, Process.Start, the AppReady wait, the PID, the exit watch, the diagnostics and
//                              the release of every resource. HandshakeSession only forwards the two decisions.
//
// One process per Caller instance, on purpose (E3 has no restart):
//   * a start request while a process is starting / ready / stopping is SUPPRESSED (a reload only raises another logical request);
//   * once an attempt has reached Process.Start, no second attempt is made in this Caller instance, whatever happened to the first
//     (exited, crashed, never Ready, Process.Start failed) - an automatic restart is a later phase;
//   * a missing / invalid launcher.json does NOT use the attempt: nothing was started, a later request may try again.
// The only thing that ends the process is Shutdown() (Caller Dispose). Scenario end, Pause, DrivingActive soft / hard OFF and a withdrawn
// ScenarioReady never reach this class. The one other place that sets the Stop event is the clean-up of a process that never became Ready
// (E0 section 3.4 "AppFailed time-out clean-up"): such a process has no other way to end.
//
// Threading: RequestStart is cheap (a lock and one thread start; no file, no process, no wait) because it runs on the Caller's monitor thread.
// Everything slow runs on ONE worker thread per Caller instance, which is the sole owner of the Process object. Shutdown() runs on BVE's Dispose
// thread: it sets the Stop event, wakes the worker and waits for it for a FINITE time (AppProcessOptions.ShutdownJoinMs). Nothing waits
// without a limit and nothing runs on BVE's Tick path.
//
// Kill policy (E0 section 4.1 / note 3): after Stop has been set the process gets StopGraceMs to leave by itself. Only if it does not, the
// process THIS class started (held by its Process handle, never found by name) is killed once; the result is logged either way.
//
// Names (the E2 contract, mirrored by managed_mode.py): Local\TSScoringPlugin.v1.<BVE PID>.App.<INST>.{Lock,Stop,Ready}; INST = a new
// 32-digit lower-case hex per attempt. The Caller creates Stop BEFORE the launch; Python creates Lock and Ready.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal static class AppObjectNames
    {
        public const string Prefix = "Local\\TSScoringPlugin.v1.";

        public static string Lock(int bveProcessId, string instance) { return Prefix + bveProcessId + ".App." + instance + ".Lock"; }
        public static string Stop(int bveProcessId, string instance) { return Prefix + bveProcessId + ".App." + instance + ".Stop"; }
        public static string Ready(int bveProcessId, string instance) { return Prefix + bveProcessId + ".App." + instance + ".Ready"; }
    }

    /// <summary>THE single place of the E3 timing values (the production defaults; tests build their own AppProcessOptions).</summary>
    internal static class AppProcessTiming
    {
        /// <summary>No AppReady this long after Process.Start -> AppFailed. E0 section 3.3 fixed 15 s; the E2 real start (Qt + UDP bind) measured about 1-3 s.</summary>
        public const int ReadyTimeoutMs = 15000;

        /// <summary>Spacing of the AppReady probe (the named event is opened afresh each time; E0 note 7). Runs on the worker thread only.</summary>
        public const int ReadyPollMs = 25;

        /// <summary>How often a Ready process is looked at for an exit (and the shutdown signal looked at). Worker thread only.</summary>
        public const int ExitPollMs = 100;

        /// <summary>After Stop is set the process may take this long to exit by itself (E0 acceptance: "within 3 s"; E2 smoke: exit 0 well inside it).</summary>
        public const int StopGraceMs = 3000;

        /// <summary>After the one Kill: how long to wait for the exit to show.</summary>
        public const int KillWaitMs = 2000;

        /// <summary>After the exit: how long the stderr / stdout readers get to reach their end.</summary>
        public const int StreamDrainMs = 500;

        /// <summary>Extra room the Dispose thread gives the worker on top of grace + kill + drain.</summary>
        public const int ShutdownMarginMs = 1500;

        /// <summary>The owner token of E2's --owner argument (lower-case letters, digits, '-'; first character a letter).</summary>
        public const string Owner = "caller";

        /// <summary>Lines of the application's stderr copied to the shared log per process; the rest is only counted.</summary>
        public const int MaxStderrLogLines = 20;

        /// <summary>Longest copied stderr line (printable ASCII only).</summary>
        public const int MaxStderrLineChars = 160;
    }

    internal sealed class AppProcessOptions
    {
        public int ReadyTimeoutMs = AppProcessTiming.ReadyTimeoutMs;
        public int ReadyPollMs = AppProcessTiming.ReadyPollMs;
        public int ExitPollMs = AppProcessTiming.ExitPollMs;
        public int StopGraceMs = AppProcessTiming.StopGraceMs;
        public int KillWaitMs = AppProcessTiming.KillWaitMs;
        public int StreamDrainMs = AppProcessTiming.StreamDrainMs;
        public int ShutdownMarginMs = AppProcessTiming.ShutdownMarginMs;

        public int ShutdownJoinMs { get { return StopGraceMs + KillWaitMs + StreamDrainMs + ShutdownMarginMs; } }
    }

    internal enum AppProcessState
    {
        /// <summary>Nothing running and no attempt used (also after a missing / invalid launcher.json).</summary>
        None = 0,

        /// <summary>A start request was accepted: configuration, Process.Start and the AppReady wait are in progress.</summary>
        Starting,

        /// <summary>AppReady was seen on a live process.</summary>
        Ready,

        /// <summary>Shutdown began (Stop set); the process has not been seen to exit yet.</summary>
        Stopping,

        /// <summary>The process ended (after Ready, or at Shutdown). The attempt is used.</summary>
        Exited,

        /// <summary>The attempt failed: Process.Start failed, exit before Ready, or no Ready in time. The attempt is used.</summary>
        Failed,
    }

    internal enum AppLaunchDecision
    {
        /// <summary>The worker was started (it may still end in "no configuration").</summary>
        Started = 0,

        /// <summary>A process is starting / ready / stopping: nothing new is started.</summary>
        SuppressedAlive,

        /// <summary>This Caller instance already used its one attempt (the process is gone): nothing new is started.</summary>
        SuppressedAttemptUsed,

        /// <summary>Dispose began: no new start.</summary>
        Closed,
    }

    internal sealed class AppProcessManager
    {
        private const int NoExit = int.MinValue;

        private static readonly Regex ErrorTypePattern = new Regex(@"^\s*([A-Za-z_][A-Za-z0-9_.]{0,60}(?:Error|Exception|Exit|Interrupt))\b", RegexOptions.CultureInvariant);

        private readonly object sync = new object();
        private readonly int bveProcessId;
        private readonly Action<string, string> log;
        private readonly Func<LauncherConfigResult> configProvider;
        private readonly AppProcessOptions options;
        private readonly ManualResetEvent shutdownSignal = new ManualResetEvent(false);

        private AppProcessState state = AppProcessState.None;
        private bool closed;
        private Thread worker;
        private EventWaitHandle stopEvent;
        private int stopSignalCount;
        private string lastConfigKey = string.Empty;

        private int launchRequestCount;
        private int suppressedCount;
        private int attempts;
        private int processStartCount;
        private int appPid;
        private string instance = string.Empty;
        private int exitCode = NoExit;
        private bool killed;
        private bool readyAccepted;

        // streams (written by thread-pool threads)
        private int stderrLines;
        private int stderrLogged;
        private int stderrDropped;
        private long stdoutBytes;
        private string lastErrorType = string.Empty;
        private readonly ManualResetEvent stderrEof = new ManualResetEvent(false);
        private readonly ManualResetEvent stdoutEof = new ManualResetEvent(false);

        /// <summary>Offline tests only: called on the worker thread right after AppReady was seen and before it is accepted.</summary>
        internal Action ReadyObservedHook { get; set; }

        public AppProcessManager(int bveProcessId, Action<string, string> log, Func<LauncherConfigResult> configProvider, AppProcessOptions options)
        {
            this.bveProcessId = bveProcessId;
            this.log = log;
            this.configProvider = configProvider ?? (() => LauncherConfigLoader.Load(LauncherConfigLoader.ConfiguredPath()));
            this.options = options ?? new AppProcessOptions();
        }

        public AppProcessState State { get { lock (sync) { return state; } } }

        public bool Closed { get { lock (sync) { return closed; } } }

        public int AppPid { get { lock (sync) { return appPid; } } }

        public string Instance { get { lock (sync) { return instance; } } }

        /// <summary>Calls of RequestStart (every logical request that reached this class).</summary>
        public int LaunchRequestCount { get { lock (sync) { return launchRequestCount; } } }

        public int SuppressedCount { get { lock (sync) { return suppressedCount; } } }

        /// <summary>Attempts that reached the point of no return (Stop event created, Process.Start about to be called). Never more than 1.</summary>
        public int AttemptCount { get { lock (sync) { return attempts; } } }

        /// <summary>Real Process.Start calls (successful or not). Never more than 1.</summary>
        public int ProcessStartCount { get { lock (sync) { return processStartCount; } } }

        public int StopSignalCount { get { lock (sync) { return stopSignalCount; } } }

        public bool ExitObserved { get { lock (sync) { return exitCode != NoExit; } } }

        public int ExitCode { get { lock (sync) { return exitCode == NoExit ? 0 : exitCode; } } }

        public bool Killed { get { lock (sync) { return killed; } } }

        public bool ReadyAccepted { get { lock (sync) { return readyAccepted; } } }

        public int StderrLineCount { get { return Volatile.Read(ref stderrLines); } }

        public int StderrLoggedCount { get { return Volatile.Read(ref stderrLogged); } }

        public long StdoutByteCount { get { return Interlocked.Read(ref stdoutBytes); } }

        public string LastErrorType { get { lock (sync) { return lastErrorType; } } }

        public bool WorkerAlive { get { Thread t; lock (sync) { t = worker; } return t != null && t.IsAlive; } }

        // ------------------------------------------------------------------------------------------------------------------------------
        // The logical start request (monitor thread; no I/O, no wait)
        // ------------------------------------------------------------------------------------------------------------------------------
        public AppLaunchDecision RequestStart(int scenarioGeneration, int requestNumber)
        {
            string why = null;
            AppProcessState snapshot;
            int pidSnapshot;
            AppLaunchDecision decision;
            lock (sync)
            {
                launchRequestCount++;
                if (closed)
                {
                    return AppLaunchDecision.Closed;
                }

                snapshot = state;
                pidSnapshot = appPid;
                if (state == AppProcessState.Starting || state == AppProcessState.Ready || state == AppProcessState.Stopping)
                {
                    suppressedCount++;
                    decision = AppLaunchDecision.SuppressedAlive;
                    why = "process-" + state.ToString().ToLowerInvariant();
                }
                else if (attempts > 0)
                {
                    suppressedCount++;
                    decision = AppLaunchDecision.SuppressedAttemptUsed;
                    why = "attempt-already-used";
                }
                else
                {
                    state = AppProcessState.Starting;
                    decision = AppLaunchDecision.Started;
                    Thread t = new Thread(() => RunWorker(scenarioGeneration, requestNumber));
                    t.IsBackground = true;
                    t.Name = "TSScoringPlugin.Caller.AppProcess";
                    worker = t;
                    t.Start();
                }
            }

            if (decision != AppLaunchDecision.Started)
            {
                Log("APP_LAUNCH_SUPPRESSED", "ScenarioGeneration=" + scenarioGeneration + " requestNo=" + requestNumber + " reason=" + why + " state=" + snapshot + " appPid=" + pidSnapshot);
            }

            return decision;
        }

        // ------------------------------------------------------------------------------------------------------------------------------
        // Dispose (BVE's Dispose thread; bounded)
        // ------------------------------------------------------------------------------------------------------------------------------
        /// <summary>Caller Dispose: no new start, Stop is set once, the process gets a finite time to end, every resource is released. Idempotent.</summary>
        public void Shutdown()
        {
            Thread w;
            AppProcessState snapshot;
            int pidSnapshot;
            lock (sync)
            {
                if (closed)
                {
                    return;
                }

                closed = true;
                w = worker;
                snapshot = state;
                pidSnapshot = appPid;
            }

            if (w == null)
            {
                Log("APP_SHUTDOWN_END", "state=" + snapshot + " processStarted=no stopSignals=0");
                shutdownSignal.Set();
                DisposeSignals();
                return;
            }

            Log("APP_SHUTDOWN_BEGIN", "state=" + snapshot + " appPid=" + pidSnapshot);
            SignalStop("caller-dispose");
            shutdownSignal.Set();
            bool joined = false;
            try { joined = w.Join(options.ShutdownJoinMs); } catch { }

            AppProcessState endState;
            int endPid;
            int endCode;
            bool endKilled;
            int stops;
            lock (sync)
            {
                endState = state;
                endPid = appPid;
                endCode = exitCode;
                endKilled = killed;
                stops = stopSignalCount;
            }

            if (!joined)
            {
                Log("APP_SHUTDOWN_JOIN_TIMEOUT", "limitMs=" + options.ShutdownJoinMs + " state=" + endState + " appPid=" + endPid + " residual=possible");
            }

            Log("APP_SHUTDOWN_END", "state=" + endState + " appPid=" + endPid + " exitCode=" + (endCode == NoExit ? "none" : endCode.ToString(CultureInfo.InvariantCulture)) + " killed=" + (endKilled ? "yes" : "no") + " stopSignals=" + stops + " joined=" + (joined ? "yes" : "no"));
            if (joined)
            {
                DisposeSignals(); // the worker is gone: nothing waits on these any more
            }
        }

        /// <summary>The three wait handles of this instance are released (Shutdown, after the worker ended). A late stream callback is guarded by its own try/catch.</summary>
        private void DisposeSignals()
        {
            try { shutdownSignal.Dispose(); } catch { }
            try { stderrEof.Dispose(); } catch { }
            try { stdoutEof.Dispose(); } catch { }
        }

        /// <summary>Sets the Stop event, at most once per instance. A no-op while the event does not exist yet (the worker checks the closed flag itself).</summary>
        private void SignalStop(string reason)
        {
            string inst;
            int pid;
            lock (sync)
            {
                if (stopEvent == null || stopSignalCount > 0)
                {
                    return;
                }

                try
                {
                    stopEvent.Set();
                }
                catch (ObjectDisposedException)
                {
                    return;
                }

                stopSignalCount++;
                inst = instance;
                pid = appPid;
            }

            Log("APP_STOP_SIGNALLED", "instance=" + inst + " appPid=" + pid + " reason=" + reason);
        }

        // ------------------------------------------------------------------------------------------------------------------------------
        // The worker: the sole owner of the Process object
        // ------------------------------------------------------------------------------------------------------------------------------
        private void RunWorker(int generation, int requestNo)
        {
            Process process = null;
            string inst = null;
            EventWaitHandle stop = null;
            AppProcessState finalState = AppProcessState.Failed;
            bool attemptUsed = false;
            try
            {
                LauncherConfigResult config = configProvider();
                if (config == null || config.Status != LauncherConfigStatus.Loaded || config.Config == null)
                {
                    LogConfigIssue(config, generation, requestNo);
                    finalState = AppProcessState.None;
                    return;
                }

                lastConfigKey = string.Empty;
                inst = Guid.NewGuid().ToString("N");
                bool created;
                stop = new EventWaitHandle(false, EventResetMode.ManualReset, AppObjectNames.Stop(bveProcessId, inst), out created);
                if (!created)
                {
                    Log("APP_LAUNCH_FAILED", "reason=stop-event-already-exists instance=" + inst);
                    attemptUsed = true;
                    lock (sync) { attempts++; }
                    return;
                }

                lock (sync)
                {
                    if (closed)
                    {
                        finalState = AppProcessState.None;
                        Log("APP_LAUNCH_ABORTED", "reason=caller-disposing instance=" + inst);
                        return;
                    }

                    attempts++;
                    attemptUsed = true;
                    instance = inst;
                    stopEvent = stop;
                }

                ProcessStartInfo psi = BuildStartInfo(config.Config, bveProcessId, inst);
                process = new Process();
                process.StartInfo = psi;
                process.OutputDataReceived += OnStdout;
                process.ErrorDataReceived += OnStderr;

                Log("APP_LAUNCH_BEGIN", "ScenarioGeneration=" + generation + " requestNo=" + requestNo + " instance=" + inst + " attempt=1 shell=no windowless=yes");
                long startQpc = Stopwatch.GetTimestamp();
                lock (sync) { processStartCount++; }
                try
                {
                    process.Start();
                    process.BeginErrorReadLine();
                    process.BeginOutputReadLine();
                }
                catch (Exception ex)
                {
                    int native = 0;
                    Win32Exception w32 = ex as Win32Exception;
                    if (w32 != null)
                    {
                        native = w32.NativeErrorCode;
                    }

                    Log("APP_PROCESS_START_FAILED", "instance=" + inst + " type=" + ex.GetType().Name + " win32=" + native);
                    bool startedAnyway = false;
                    try { startedAnyway = process.Id != 0; } catch { }
                    if (!startedAnyway)
                    {
                        finalState = AppProcessState.Failed;
                        return;
                    }
                }

                int pid = process.Id;
                lock (sync) { appPid = pid; }
                Log("APP_PROCESS_STARTED", "appPid=" + pid + " instance=" + inst + " bvePid=" + bveProcessId + " startMs=" + Ms(Stopwatch.GetTimestamp() - startQpc));
                finalState = Supervise(process, inst, startQpc);
            }
            catch (Exception ex)
            {
                Log("APP_PROCESS_EXCEPTION", "type=" + ex.GetType().Name);
                finalState = attemptUsed ? AppProcessState.Failed : AppProcessState.None;
            }
            finally
            {
                Cleanup(process, stop, finalState);
            }
        }

        /// <summary>Ready wait, exit watch and the stop sequence of one started process. Returns the final state.</summary>
        private AppProcessState Supervise(Process process, string inst, long startQpc)
        {
            string readyName = AppObjectNames.Ready(bveProcessId, inst);
            int pid = process.Id;
            Log("APP_READY_WAIT_BEGIN", "appPid=" + pid + " instance=" + inst + " timeoutMs=" + options.ReadyTimeoutMs);

            // ---- wait for AppReady (finite) ----
            while (true)
            {
                if (process.HasExited)
                {
                    int code = ReadExitCode(process);
                    RecordExit(code, false);
                    DrainStreams();
                    if (shutdownSignal.WaitOne(0))
                    {
                        Log("APP_EXITED", "appPid=" + pid + " exitCode=" + code + " exitName=" + ExitName(code) + " killed=no phase=before-ready-at-dispose");
                        return AppProcessState.Exited;
                    }

                    Log("APP_EXIT_BEFORE_READY", "appPid=" + pid + " exitCode=" + code + " exitName=" + ExitName(code) + " waitedMs=" + Ms(Stopwatch.GetTimestamp() - startQpc));
                    return AppProcessState.Failed;
                }

                if (shutdownSignal.WaitOne(0))
                {
                    return StopSequence(process, "caller-dispose", AppProcessState.Exited);
                }

                if (Ms(Stopwatch.GetTimestamp() - startQpc) >= options.ReadyTimeoutMs)
                {
                    Log("APP_READY_TIMEOUT", "appPid=" + pid + " timeoutMs=" + options.ReadyTimeoutMs + " instance=" + inst);
                    SignalStop("ready-timeout-cleanup");
                    return StopSequence(process, "ready-timeout", AppProcessState.Failed);
                }

                if (ReadyIsSet(readyName))
                {
                    Action hook = ReadyObservedHook;
                    if (hook != null)
                    {
                        try { hook(); } catch { }
                    }

                    bool accept;
                    string ignoredReason = null;
                    lock (sync)
                    {
                        if (closed)
                        {
                            accept = false;
                            ignoredReason = "caller-disposing";
                        }
                        else if (process.HasExited)
                        {
                            accept = false;
                            ignoredReason = "process-exited";
                        }
                        else
                        {
                            accept = true;
                            state = AppProcessState.Ready;
                            readyAccepted = true;
                        }
                    }

                    if (accept)
                    {
                        Log("APP_READY", "appPid=" + pid + " instance=" + inst + " waitedMs=" + Ms(Stopwatch.GetTimestamp() - startQpc));
                        break;
                    }

                    Log("APP_READY_IGNORED", "appPid=" + pid + " instance=" + inst + " reason=" + ignoredReason);
                    if (ignoredReason == "caller-disposing")
                    {
                        return StopSequence(process, "caller-dispose", AppProcessState.Exited);
                    }

                    continue; // the process exited: the next turn reports it
                }

                shutdownSignal.WaitOne(options.ReadyPollMs);
            }

            // ---- Ready: watch for an exit until Shutdown ----
            while (true)
            {
                if (shutdownSignal.WaitOne(0))
                {
                    return StopSequence(process, "caller-dispose", AppProcessState.Exited);
                }

                if (process.HasExited)
                {
                    int code = ReadExitCode(process);
                    RecordExit(code, false);
                    DrainStreams();
                    if (shutdownSignal.WaitOne(0))
                    {
                        Log("APP_EXITED", "appPid=" + pid + " exitCode=" + code + " exitName=" + ExitName(code) + " killed=no phase=at-dispose");
                    }
                    else
                    {
                        Log("APP_EXIT_AFTER_READY", "appPid=" + pid + " exitCode=" + code + " exitName=" + ExitName(code) + " restart=no");
                    }

                    return AppProcessState.Exited;
                }

                shutdownSignal.WaitOne(options.ExitPollMs);
            }
        }

        /// <summary>Stop is (already) set: give the process StopGraceMs, then Kill the process this class started - once - and record the end.</summary>
        private AppProcessState StopSequence(Process process, string reason, AppProcessState finalState)
        {
            int pid = process.Id;
            lock (sync)
            {
                if (state != AppProcessState.Failed)
                {
                    state = AppProcessState.Stopping;
                }
            }

            long t0 = Stopwatch.GetTimestamp();
            bool exited = process.WaitForExit(options.StopGraceMs);
            bool wasKilled = false;
            if (!exited)
            {
                Log("APP_STOP_TIMEOUT", "appPid=" + pid + " graceMs=" + options.StopGraceMs + " reason=" + reason + " action=kill-own-process");
                try
                {
                    process.Kill();
                    wasKilled = true;
                    Log("APP_KILLED", "appPid=" + pid);
                }
                catch (Exception ex)
                {
                    Log("APP_KILL_FAILED", "appPid=" + pid + " type=" + ex.GetType().Name);
                }

                exited = process.WaitForExit(options.KillWaitMs);
            }

            if (!exited)
            {
                Log("APP_PROCESS_RESIDUAL", "appPid=" + pid + " alive=yes note=still-running-after-kill-wait");
                return finalState == AppProcessState.Failed ? AppProcessState.Failed : AppProcessState.Stopping;
            }

            int code = ReadExitCode(process);
            RecordExit(code, wasKilled);
            DrainStreams();
            Log("APP_EXITED", "appPid=" + pid + " exitCode=" + code + " exitName=" + (wasKilled ? "killed" : ExitName(code)) + " killed=" + (wasKilled ? "yes" : "no") + " phase=" + reason + " waitedMs=" + Ms(Stopwatch.GetTimestamp() - t0));
            return finalState;
        }

        private void RecordExit(int code, bool wasKilled)
        {
            lock (sync)
            {
                exitCode = code;
                killed = wasKilled;
            }
        }

        private static int ReadExitCode(Process process)
        {
            try { return process.ExitCode; } catch { return -1; }
        }

        /// <summary>After the process is gone: both readers get StreamDrainMs to reach their end, then ONE summary line is written.</summary>
        private void DrainStreams()
        {
            long deadline = Stopwatch.GetTimestamp() + options.StreamDrainMs * Stopwatch.Frequency / 1000;
            bool err = stderrEof.WaitOne(options.StreamDrainMs);
            long remaining = (deadline - Stopwatch.GetTimestamp()) * 1000 / Stopwatch.Frequency;
            bool outp = stdoutEof.WaitOne((int)Math.Max(0, Math.Min(options.StreamDrainMs, remaining)));
            string last;
            lock (sync) { last = lastErrorType; }
            Log("APP_STREAMS", "stderrLines=" + StderrLineCount + " stderrLogged=" + StderrLoggedCount + " stderrDropped=" + Volatile.Read(ref stderrDropped) + " stdoutBytes=" + StdoutByteCount + " stderrEnd=" + (err ? "yes" : "no") + " stdoutEnd=" + (outp ? "yes" : "no") + (last.Length > 0 ? " lastErrorType=" + last : string.Empty));
        }

        /// <summary>The worker is leaving: every resource this class holds is released, the final state is published.</summary>
        private void Cleanup(Process process, EventWaitHandle ownStop, AppProcessState finalState)
        {
            if (process != null)
            {
                try { process.CancelOutputRead(); } catch { }
                try { process.CancelErrorRead(); } catch { }
                try { process.Dispose(); } catch { }
            }

            lock (sync)
            {
                // The Stop event is released under the lock so that a concurrent Shutdown never sets a disposed handle.
                if (ownStop != null)
                {
                    try { ownStop.Dispose(); } catch { }
                }

                stopEvent = null;
                state = finalState;
            }
        }

        // ------------------------------------------------------------------------------------------------------------------------------
        // Pieces (pure or nearly)
        // ------------------------------------------------------------------------------------------------------------------------------
        /// <summary>
        /// The one place a process start is described. FileName is the absolute interpreter, never a command line and never looked up on PATH; no
        /// shell. .NET Framework has no ArgumentList, so the command line is built from FIXED tokens plus three validated values: the script path
        /// (absolute, no quote, no control character, does not end with a backslash - LauncherConfigLoader), the decimal BVE PID and the 32-digit
        /// hex instance. No text from outside the launcher file or this class reaches the command line. No "-I" (the per-user site-packages must stay visible).
        /// </summary>
        internal static ProcessStartInfo BuildStartInfo(LauncherConfig config, int bveProcessId, string inst)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = config.PythonExecutable;
            psi.Arguments = BuildArguments(config.ScriptPath, bveProcessId, inst);
            psi.WorkingDirectory = config.WorkingDirectory;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.RedirectStandardError = true;
            psi.RedirectStandardOutput = true;
            psi.StandardErrorEncoding = Encoding.UTF8;
            psi.StandardOutputEncoding = Encoding.UTF8;
            return psi;
        }

        internal static string BuildArguments(string scriptPath, int bveProcessId, string inst)
        {
            return "\"" + scriptPath + "\" --managed --owner " + AppProcessTiming.Owner + " --bve-pid " + bveProcessId.ToString(CultureInfo.InvariantCulture) + " --instance " + inst;
        }

        private static bool ReadyIsSet(string name)
        {
            try
            {
                EventWaitHandle handle;
                if (!EventWaitHandle.TryOpenExisting(name, EventWaitHandleRights.Synchronize, out handle))
                {
                    return false;
                }

                using (handle)
                {
                    return handle.WaitOne(0);
                }
            }
            catch
            {
                return false;
            }
        }

        private static int Ms(long qpcTicks)
        {
            return (int)Math.Min(int.MaxValue, qpcTicks * 1000 / Stopwatch.Frequency);
        }

        /// <summary>The names of the E2 exit-code table (managed_mode.py).</summary>
        internal static string ExitName(int code)
        {
            switch (code)
            {
                case 0: return "normal";
                case 1: return "runtime-error";
                case 2: return "udp-bind-failed";
                case 3: return "duplicate-instance";
                case 4: return "init-failed";
                case 5: return "args-invalid";
                default: return "other";
            }
        }

        private void LogConfigIssue(LauncherConfigResult config, int generation, int requestNo)
        {
            string evt = config != null && config.Status == LauncherConfigStatus.Invalid ? "APP_LAUNCH_CONFIG_INVALID" : "APP_LAUNCH_CONFIG_ABSENT";
            string reason = config == null ? "no-result" : config.Reason;
            string key = evt + "/" + reason;
            lock (sync)
            {
                if (key == lastConfigKey)
                {
                    return; // the same situation again: one line is enough
                }

                lastConfigKey = key;
            }

            Log(evt, "reason=" + reason + " ScenarioGeneration=" + generation + " requestNo=" + requestNo + " started=no");
        }

        private void Log(string evt, string detail)
        {
            try
            {
                if (log != null)
                {
                    log(evt, detail);
                }
            }
            catch
            {
            }
        }

        // ------------------------------------------------------------------------------------------------------------------------------
        // The application's output (thread-pool threads): counted; a bounded part of stderr is copied to the log
        // ------------------------------------------------------------------------------------------------------------------------------
        private void OnStdout(object sender, DataReceivedEventArgs e)
        {
            try
            {
                if (e.Data == null)
                {
                    stdoutEof.Set();
                    return;
                }

                Interlocked.Add(ref stdoutBytes, e.Data.Length + 2);
            }
            catch
            {
            }
        }

        private void OnStderr(object sender, DataReceivedEventArgs e)
        {
            try
            {
                if (e.Data == null)
                {
                    stderrEof.Set();
                    return;
                }

                Interlocked.Increment(ref stderrLines);
                string line = e.Data;
                if (line.StartsWith("[MANAGED] ", StringComparison.Ordinal))
                {
                    // The E2 diagnostic lines (state changes, ASCII, no path). Copied up to a fixed number per process.
                    if (Interlocked.Increment(ref stderrLogged) <= AppProcessTiming.MaxStderrLogLines)
                    {
                        Log("APP_STDERR", "line=" + Printable(line, AppProcessTiming.MaxStderrLineChars));
                    }
                    else
                    {
                        Interlocked.Decrement(ref stderrLogged);
                        Interlocked.Increment(ref stderrDropped);
                    }

                    return;
                }

                // Anything else (a traceback, a library message) may hold a path or user text: only the exception TYPE is kept.
                Match m = ErrorTypePattern.Match(line);
                if (m.Success)
                {
                    lock (sync) { lastErrorType = Printable(m.Groups[1].Value, 64); }
                }
            }
            catch
            {
            }
        }

        private static string Printable(string text, int max)
        {
            StringBuilder sb = new StringBuilder(Math.Min(text.Length, max));
            foreach (char c in text)
            {
                if (sb.Length >= max)
                {
                    break;
                }

                sb.Append(c >= 0x20 && c <= 0x7E ? c : '?');
            }

            return sb.ToString();
        }
    }
}
