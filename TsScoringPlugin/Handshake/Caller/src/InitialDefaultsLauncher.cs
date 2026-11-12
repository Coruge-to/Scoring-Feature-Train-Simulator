using System;
using System.Diagnostics;

// ============================================================================
// INITIAL DEFAULTS - the Properties entry of the input-device Caller.
// The Input Device Properties button opens the 'initial defaults' window. The window is the Python application started with the one argument --initial-defaults, as a SEPARATE process:
// the Properties callback only starts it and returns at once (it never waits for the window, never redirects its pipes, never shows a console).
// The start comes ONLY from the existing launcher.json contract (LauncherConfigLoader: python / script / working directory): this class knows no product file name, no system store and no window of its own.
// One window at a time: while the child process lives, a further request starts nothing. When the child has exited, a new request starts a new window.
// OWNERSHIP (Stage IO-1, Owner 2026-11-12): the window belongs to the BVE settings dialog that was in front when Properties was pressed. The Caller passes three plain numbers through the environment of the child
// (an internal Caller/Python contract; the argument stays exactly --initial-defaults): the pid of THIS BVE, the HWND that was in front (the settings dialog) and the HWND of the BVE main window.
// Every HWND is checked against the pid first; an HWND of another pid is never passed. When Properties is pressed again while the window lives, the existing window is restored / re-owned / brought to the front
// (InitialDefaultsWindow.cs): no second process, no key injection. A second BVE never takes the window over and never starts a second one (it is refused with a diagnostic line).
// The window ends by its own OK / x, or without saving when the BVE that owns it ends (the Python side watches that pid).
// Every failure is a short result (never an exception, never a stack trace, never a long path).
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal sealed class InitialDefaultsLaunchResult
    {
        public bool Started;
        public bool AlreadyRunning;

        /// <summary>The existing window was found and brought back (or only flashed); None when nothing was done.</summary>
        public InitialDefaultsActivation Activation;

        /// <summary>Short fixed-vocabulary code of the failure (empty when started).</summary>
        public string Reason = string.Empty;
    }

    /// <summary>The BVE the window belongs to: its pid and two HWNDs of THAT pid (any of them may be zero, never an HWND of another pid).</summary>
    internal sealed class InitialDefaultsOwner
    {
        public int BvePid;
        public IntPtr OwnerHwnd;
        public IntPtr MainHwnd;
    }

    internal static class InitialDefaultsLauncher
    {
        internal const string Argument = "--initial-defaults";
        internal const string EnvBvePid = "TSSCORING_INITDEF_BVE_PID";
        internal const string EnvOwnerHwnd = "TSSCORING_INITDEF_OWNER_HWND";
        internal const string EnvMainHwnd = "TSSCORING_INITDEF_BVE_MAIN_HWND";
        internal const int MaxNoticeChars = 160;

        private static readonly object Gate = new object();
        private static Process running;
        private static int runningBvePid;

        /// <summary>The command line: the quoted script path and the flag. The managed-mode arguments are never passed.</summary>
        internal static string BuildArguments(string scriptPath)
        {
            return "\"" + scriptPath + "\" " + Argument;
        }

        internal static ProcessStartInfo BuildStartInfo(LauncherConfig config)
        {
            return BuildStartInfo(config, null);
        }

        internal static ProcessStartInfo BuildStartInfo(LauncherConfig config, InitialDefaultsOwner owner)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = config.PythonExecutable;
            psi.Arguments = BuildArguments(config.ScriptPath);
            psi.WorkingDirectory = config.WorkingDirectory;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            if (owner != null && owner.BvePid > 0)
            {
                psi.EnvironmentVariables[EnvBvePid] = owner.BvePid.ToString();
                psi.EnvironmentVariables[EnvOwnerHwnd] = InitialDefaultsWindow.Decimal(owner.OwnerHwnd);
                psi.EnvironmentVariables[EnvMainHwnd] = InitialDefaultsWindow.Decimal(owner.MainHwnd);
            }

            return psi;
        }

        /// <summary>
        /// The owner information of THIS BVE: the owner candidate (the settings dialog) is used only when it belongs to <paramref name="bvePid"/>, otherwise the HWND that is in front now is used when it belongs to it;
        /// the main window likewise. Null when no HWND of this pid is usable (the window is then started without an owner, as before this stage).
        /// </summary>
        internal static InitialDefaultsOwner ResolveOwner(IntPtr ownerCandidate, int bvePid, IntPtr mainCandidate)
        {
            try
            {
                if (bvePid <= 0)
                {
                    return null;
                }

                IntPtr owner = IntPtr.Zero;
                if (InitialDefaultsWindow.BelongsTo(ownerCandidate, bvePid))
                {
                    owner = ownerCandidate;
                }
                else
                {
                    IntPtr front = InitialDefaultsWindow.Foreground();
                    if (InitialDefaultsWindow.BelongsTo(front, bvePid))
                    {
                        owner = front;
                    }
                }

                IntPtr main = InitialDefaultsWindow.BelongsTo(mainCandidate, bvePid) ? mainCandidate : IntPtr.Zero;
                if (owner == IntPtr.Zero && main == IntPtr.Zero)
                {
                    ObservationLog.Write("A", "INITDEF_OWNER_INVALID", "bvePid=" + bvePid);
                    return null;
                }

                return new InitialDefaultsOwner { BvePid = bvePid, OwnerHwnd = owner, MainHwnd = main };
            }
            catch
            {
                return null;
            }
        }

        /// <summary>The owner information of the BVE this Caller runs in (production): the candidate comes from Properties, the main window from the process.</summary>
        internal static InitialDefaultsOwner ResolveOwner(IntPtr ownerCandidate)
        {
            try
            {
                using (Process me = Process.GetCurrentProcess())
                {
                    return ResolveOwner(ownerCandidate, me.Id, me.MainWindowHandle);
                }
            }
            catch
            {
                return null;
            }
        }

        /// <summary>Starts the window without owner information (as before this stage), or refuses a second one. Never throws; returns at once.</summary>
        internal static InitialDefaultsLaunchResult TryLaunch()
        {
            return TryLaunchOwned(null);
        }

        /// <summary>Starts the window owned by the BVE settings dialog, brings the existing one back, or refuses a window of another BVE. Never throws; returns at once.</summary>
        internal static InitialDefaultsLaunchResult TryLaunchOwned(InitialDefaultsOwner owner)
        {
            try
            {
                lock (Gate)
                {
                    if (running != null)
                    {
                        bool alive;
                        try
                        {
                            alive = !running.HasExited;
                        }
                        catch
                        {
                            alive = false;
                        }

                        if (alive)
                        {
                            ObservationLog.Write("A", "INITDEF_ALREADY_RUNNING", "-");
                            InitialDefaultsActivation activation = InitialDefaultsActivation.None;
                            if (owner != null)
                            {
                                activation = InitialDefaultsWindow.ActivateExisting(running, runningBvePid, owner);
                            }

                            return new InitialDefaultsLaunchResult { AlreadyRunning = true, Reason = "already-running", Activation = activation };
                        }

                        try
                        {
                            running.Dispose();
                        }
                        catch
                        {
                        }

                        running = null;
                        runningBvePid = 0;
                    }

                    if (InitialDefaultsWindow.AnyWindowOfTheNamedMutexExists())
                    {
                        // a window of another BVE (or of a manual start) is open: it is neither taken over nor duplicated, and the user gets a clear line in the log
                        ObservationLog.Write("A", "INITDEF_FOREIGN_BVE_REJECTED", "bvePid=" + (owner == null ? 0 : owner.BvePid));
                        return new InitialDefaultsLaunchResult { AlreadyRunning = true, Reason = "foreign-window-open", Activation = InitialDefaultsActivation.ForeignRejected };
                    }

                    LauncherConfigResult cfg = LauncherConfigLoader.Load(LauncherConfigLoader.ConfiguredPath());
                    if (cfg == null || cfg.Status != LauncherConfigStatus.Loaded || cfg.Config == null)
                    {
                        string why = cfg == null ? "none" : cfg.Status.ToString().ToLowerInvariant() + (string.IsNullOrEmpty(cfg.Reason) ? string.Empty : ":" + cfg.Reason);
                        return Fail("launcher-" + why);
                    }

                    Process process = Process.Start(BuildStartInfo(cfg.Config, owner));
                    if (process == null)
                    {
                        return Fail("start-returned-null");
                    }

                    running = process;
                    runningBvePid = owner == null ? 0 : owner.BvePid;
                    ObservationLog.Write("A", "INITDEF_STARTED", "pid=" + process.Id);
                    if (owner != null)
                    {
                        ObservationLog.Write("A", "INITDEF_OWNER_SET", "bvePid=" + owner.BvePid + " owner=" + InitialDefaultsWindow.Hex(owner.OwnerHwnd) + " main=" + InitialDefaultsWindow.Hex(owner.MainHwnd));
                    }

                    WatchExit(process);
                    return new InitialDefaultsLaunchResult { Started = true };
                }
            }
            catch (Exception ex)
            {
                return Fail("start-failed:" + ex.GetType().Name);
            }
        }

        /// <summary>One log line when the window process ends (the event runs on a pool thread; nothing here waits for the child).</summary>
        private static void WatchExit(Process process)
        {
            try
            {
                int id = process.Id;
                process.EnableRaisingEvents = true;
                process.Exited += delegate
                {
                    try
                    {
                        ObservationLog.Write("A", "INITDEF_EXITED", "pid=" + id + " code=" + process.ExitCode);
                    }
                    catch
                    {
                    }
                };
            }
            catch
            {
            }
        }

        private static InitialDefaultsLaunchResult Fail(string reason)
        {
            if (reason.Length > 80)
            {
                reason = reason.Substring(0, 80);
            }

            try
            {
                ObservationLog.Write("A", "INITDEF_FAILED", "reason=" + reason);
            }
            catch
            {
            }

            return new InitialDefaultsLaunchResult { Reason = reason };
        }

        /// <summary>The short line shown in front of the status text when the window could not be started (no stack trace, no path: the reason code is a fixed short word).</summary>
        internal static string FailureNotice(InitialDefaultsLaunchResult result)
        {
            string reason = result == null || string.IsNullOrEmpty(result.Reason) ? "unknown" : result.Reason;
            int colon = reason.IndexOf(':');
            string code = colon >= 0 ? reason.Substring(0, colon) : reason;
            string text = "\u521D\u671F\u5024\u8A2D\u5B9A\u753B\u9762\u3092\u8D77\u52D5\u3067\u304D\u307E\u305B\u3093\u3067\u3057\u305F (" + code + ")";
            return text.Length > MaxNoticeChars ? text.Substring(0, MaxNoticeChars) : text;
        }
    }
}
