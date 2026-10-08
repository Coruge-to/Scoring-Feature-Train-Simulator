using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;

// ============================================================================
// PHASE C1 OBSERVATION BUILD - shared diagnostic log (compiled into BOTH DLLs; no shared assembly).
//
// One fixed text file: <user profile>\Downloads\TSScoring-Phase-C1-Observation.log (the folder comes from the OS at run time,
// so no user or path text exists in the binaries). Both DLLs of one BVE process append to it; a NEW BVE process (new PID)
// truncates it first, so two different runs are never mixed. Within one process the first DLL that logs does the truncation
// (decided by a per-PID named marker under a per-PID named mutex), the second DLL only appends.
//
// Line format (one event per line, state changes only - never per frame):
//   HH:mm:ss.fff q=<QPC ms> P=<pid> S=<Caller|Bridge> T=<A|B|AB> th=<managed thread> EVENT key=value ...
//   T = Track: A scenario life cycle, B start-up / dependency notice, AB both.
//
// Privacy: only counters, flags, ids, timings and exception TYPE names are logged. Never a message text, path, scenario / vehicle /
// machine / user name. Failure policy: nothing in this class can throw into BVE; a failed write only increments a drop counter.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal static class ObservationLog
    {
        internal const string FileName = "TSScoring-Phase-C1-Observation.log";
        internal const string FolderName = "Downloads";
        internal const long DefaultMaxBytes = 4L * 1024 * 1024;
        internal const int LockWaitMs = 30;

#if CALLER_DLL
        internal const string Source = "Caller";
#else
        internal const string Source = "Bridge";
#endif

        private static readonly object sync = new object();

        // Offline-test hooks only (null / 0 in production): a private log file, a fake PID, a small size cap.
        internal static string TestPath { get; set; }
        internal static int TestPid { get; set; }
        internal static long TestMaxBytes { get; set; }

        private static bool ready;
        private static string path;
        private static int pid;
        private static Mutex fileLock;
        private static EventWaitHandle runMarker;
        private static long dropped;
        private static bool capped;

        internal static string Version
        {
            get
            {
                try { return Assembly.GetExecutingAssembly().GetName().Version.ToString(); }
                catch { return "?"; }
            }
        }

        /// <summary>The path the production build writes to. Pure: creates nothing.</summary>
        internal static string DefaultPath()
        {
            try
            {
                string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                if (string.IsNullOrEmpty(profile))
                {
                    return null;
                }

                return Path.Combine(Path.Combine(profile, FolderName), FileName);
            }
            catch
            {
                return null;
            }
        }

        internal static void ResetForTests()
        {
            lock (sync)
            {
                ready = false;
                capped = false;
                dropped = 0;
                path = null;
                pid = 0;
                try { if (fileLock != null) { fileLock.Dispose(); } } catch { }
                try { if (runMarker != null) { runMarker.Dispose(); } } catch { }
                fileLock = null;
                runMarker = null;
            }
        }

        /// <summary>Writes one observation line. NEVER throws.</summary>
        internal static void Write(string track, string evt, string detail)
        {
            try
            {
                long qpc = Stopwatch.GetTimestamp();
                DateTime now = DateTime.Now;
                lock (sync)
                {
                    WriteLocked(now, qpc, track, evt, detail);
                }
            }
            catch
            {
                // a diagnostic log must never take BVE down
            }
        }

        private static void WriteLocked(DateTime now, long qpc, string track, string evt, string detail)
        {
            if (!ready)
            {
                path = TestPath ?? DefaultPath();
                pid = TestPid != 0 ? TestPid : HandshakeProtocol.CurrentProcessId();
                ready = true;
                if (path != null)
                {
                    try
                    {
                        fileLock = new Mutex(false, "Local\\TSScoringPlugin.v1." + pid + ".ObsLogLock");
                    }
                    catch
                    {
                        fileLock = null;
                    }
                }
            }

            if (path == null || capped)
            {
                return;
            }

            bool locked = false;
            try
            {
                if (fileLock != null)
                {
                    try
                    {
                        locked = fileLock.WaitOne(LockWaitMs);
                    }
                    catch (AbandonedMutexException)
                    {
                        locked = true; // the other DLL's thread died while holding it: we own it now
                    }

                    if (!locked)
                    {
                        dropped++;
                        return;
                    }
                }

                if (runMarker == null)
                {
                    bool createdNew;
                    EventWaitHandle marker = new EventWaitHandle(false, EventResetMode.ManualReset, "Local\\TSScoringPlugin.v1." + pid + ".ObsLogRun", out createdNew);
                    runMarker = marker; // kept for the life of the process on purpose: it is what says "this run already initialised the log"
                    if (createdNew)
                    {
                        StartNewRun(now, qpc);
                    }
                }

                long limit = TestMaxBytes > 0 ? TestMaxBytes : DefaultMaxBytes;
                bool overCap = false;
                try { overCap = new FileInfo(path).Exists && new FileInfo(path).Length > limit; } catch { }

                long pendingDropped = 0;
                StringBuilder sb = new StringBuilder(160);
                if (overCap)
                {
                    capped = true;
                    sb.Append(Prefix(now, qpc, "AB")).Append("LOG_CAP_REACHED limitBytes=").Append(limit).Append("\r\n");
                }
                else
                {
                    sb.Append(Prefix(now, qpc, track)).Append(evt);
                    if (!string.IsNullOrEmpty(detail))
                    {
                        sb.Append(' ').Append(detail);
                    }

                    if (dropped > 0)
                    {
                        pendingDropped = dropped;
                        sb.Append(" droppedBefore=").Append(pendingDropped);
                    }

                    sb.Append("\r\n");
                }

                if (AppendText(sb.ToString()))
                {
                    dropped -= pendingDropped;
                }
                else
                {
                    dropped++;
                }
            }
            catch
            {
                dropped++;
            }
            finally
            {
                if (locked && fileLock != null)
                {
                    try { fileLock.ReleaseMutex(); } catch { }
                }
            }
        }

        private static string Prefix(DateTime now, long qpc, string track)
        {
            return now.ToString("HH:mm:ss.fff") + " q=" + HandshakeProtocol.QpcToMs(qpc).ToString("F1") + " P=" + pid + " S=" + Source + " T=" + track + " th=" + Thread.CurrentThread.ManagedThreadId + " ";
        }

        private static void StartNewRun(DateTime now, long qpc)
        {
            StringBuilder sb = new StringBuilder(256);
            sb.Append("# TS Scoring Phase C1 observation log (diagnostic build, not for production)\r\n");
            sb.Append("# run start ").Append(now.ToString("yyyy-MM-dd HH:mm:ss")).Append(" P=").Append(pid).Append(" initializedBy=").Append(Source).Append(" ver=").Append(Version).Append("\r\n");
            sb.Append("# line: HH:mm:ss.fff q=<QPC ms> P=<pid> S=<Caller|Bridge> T=<A scenario|B start-up|AB> th=<thread> EVENT key=value\r\n");
            try
            {
                using (FileStream fs = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.ReadWrite))
                {
                    byte[] bytes = new UTF8Encoding(false).GetBytes(sb.ToString());
                    fs.Write(bytes, 0, bytes.Length);
                }
            }
            catch
            {
                // could not truncate (locked / folder missing): fall back to appending so the run is still recorded if possible
                AppendText(sb.ToString().Replace("# run start", "# run start (append fallback)"));
            }
        }

        private static bool AppendText(string text)
        {
            try
            {
                using (FileStream fs = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                {
                    byte[] bytes = new UTF8Encoding(false).GetBytes(text);
                    fs.Write(bytes, 0, bytes.Length);
                }

                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
