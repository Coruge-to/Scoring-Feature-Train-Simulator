using System;
using System.Diagnostics;

// ============================================================================
// INITIAL DEFAULTS - the Properties entry of the input-device Caller.
// The Input Device Properties button opens the 'initial defaults' window. The window is the Python application started with the one argument --initial-defaults, as a SEPARATE process:
// the Properties callback only starts it and returns at once (it never waits for the window, never redirects its pipes, never shows a console).
// The start comes ONLY from the existing launcher.json contract (LauncherConfigLoader: python / script / working directory): this class knows no product file name, no system store and no window of its own.
// One window at a time: while the child process lives, a further request starts nothing. When the child has exited, a new request starts a new window. The window does not depend on the BVE exit
// (nothing here waits for it or kills it; the window ends by its own OK / x).
// Every failure is a short result (never an exception, never a stack trace, never a long path).
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal sealed class InitialDefaultsLaunchResult
    {
        public bool Started;
        public bool AlreadyRunning;

        /// <summary>Short fixed-vocabulary code of the failure (empty when started).</summary>
        public string Reason = string.Empty;
    }

    internal static class InitialDefaultsLauncher
    {
        internal const string Argument = "--initial-defaults";
        internal const int MaxNoticeChars = 160;

        private static readonly object Gate = new object();
        private static Process running;

        /// <summary>The command line: the quoted script path and the flag. The managed-mode arguments are never passed.</summary>
        internal static string BuildArguments(string scriptPath)
        {
            return "\"" + scriptPath + "\" " + Argument;
        }

        internal static ProcessStartInfo BuildStartInfo(LauncherConfig config)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = config.PythonExecutable;
            psi.Arguments = BuildArguments(config.ScriptPath);
            psi.WorkingDirectory = config.WorkingDirectory;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            return psi;
        }

        /// <summary>Starts the window (or refuses a second one). Never throws; returns at once.</summary>
        internal static InitialDefaultsLaunchResult TryLaunch()
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
                            return new InitialDefaultsLaunchResult { AlreadyRunning = true, Reason = "already-running" };
                        }

                        try
                        {
                            running.Dispose();
                        }
                        catch
                        {
                        }

                        running = null;
                    }

                    LauncherConfigResult cfg = LauncherConfigLoader.Load(LauncherConfigLoader.ConfiguredPath());
                    if (cfg == null || cfg.Status != LauncherConfigStatus.Loaded || cfg.Config == null)
                    {
                        string why = cfg == null ? "none" : cfg.Status.ToString().ToLowerInvariant() + (string.IsNullOrEmpty(cfg.Reason) ? string.Empty : ":" + cfg.Reason);
                        return Fail("launcher-" + why);
                    }

                    Process process = Process.Start(BuildStartInfo(cfg.Config));
                    if (process == null)
                    {
                        return Fail("start-returned-null");
                    }

                    running = process;
                    ObservationLog.Write("A", "INITDEF_STARTED", "pid=" + process.Id);
                    return new InitialDefaultsLaunchResult { Started = true };
                }
            }
            catch (Exception ex)
            {
                return Fail("start-failed:" + ex.GetType().Name);
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
