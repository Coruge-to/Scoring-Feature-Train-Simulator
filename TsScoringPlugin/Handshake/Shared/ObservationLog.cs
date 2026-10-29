using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

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
//
// SI-R5.3 R53-04A (UI thread contract): a blocking wait on an STA (UI) thread lets the CLR dispatch window messages, which re-entered BVE's paint code
// inside the scenario-opened handler. Therefore an STA caller NEVER waits here: it tries the in-process lock with Monitor.TryEnter(sync, 0) and the
// cross-DLL mutex with one non-pumping Win32 WaitForSingleObject(handle, 0). If either is busy the line is not written; it is counted in
// "dropped" and shown by the next successful write as droppedBefore=N (the existing mechanism). Mutex.WaitOne(0) is NOT usable on STA (it dispatches
// messages on contention). Every other thread keeps the old behaviour: it waits up to LockWaitMs. Known diagnostic limit: a last drop that is not followed
// by a successful write is not visible in the log.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    /// <summary>Result of the one non-waiting attempt to own the cross-DLL log mutex.</summary>
    internal enum NoWaitResult
    {
        Acquired,
        Abandoned,   // the previous owner died: the mutex is OURS now
        Busy,
        Failed,
    }

    internal static class ObservationLog
    {
        internal const string FileName = "TSScoring-Phase-C1-Observation.log";
        internal const string FolderName = "Downloads";
        internal const long DefaultMaxBytes = 4L * 1024 * 1024;
        internal const int LockWaitMs = 30;

        // Win32 wait results (the only P/Invoke of this log: one declaration, compiled identically into the Current Bridge, the Legacy Bridge and the Caller)
        private const uint WaitObject0 = 0x00000000;
        private const uint WaitAbandoned = 0x00000080;
        private const uint WaitTimeout = 0x00000102;
        private const uint WaitFailed = 0xFFFFFFFF;

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

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

        /// <summary>WAIT_OBJECT_0 -> Acquired, WAIT_ABANDONED -> Abandoned (owned), WAIT_TIMEOUT -> Busy, WAIT_FAILED and anything else -> Failed.</summary>
        internal static NoWaitResult ClassifyWaitResult(uint result)
        {
            switch (result)
            {
                case WaitObject0: return NoWaitResult.Acquired;
                case WaitAbandoned: return NoWaitResult.Abandoned;
                case WaitTimeout: return NoWaitResult.Busy;
                default: return NoWaitResult.Failed; // WaitFailed (0xFFFFFFFF) and every unknown value
            }
        }

        /// <summary>
        /// Tries to own the mutex WITHOUT waiting and without letting the CLR pump messages. The handle is kept alive by a SafeHandle reference for the
        /// duration of the call (a disposed mutex gives Failed, never an exception). The caller releases the mutex only after Acquired / Abandoned.
        /// </summary>
        internal static NoWaitResult TryAcquireNoWait(Mutex mutex)
        {
            SafeWaitHandle handle = null;
            bool added = false;
            try
            {
                handle = mutex.SafeWaitHandle;
                handle.DangerousAddRef(ref added);
                return ClassifyWaitResult(WaitForSingleObject(handle.DangerousGetHandle(), 0));
            }
            catch
            {
                return NoWaitResult.Failed;
            }
            finally
            {
                if (added)
                {
                    handle.DangerousRelease();
                }
            }
        }

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
                Interlocked.Exchange(ref dropped, 0);
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
            WriteStamped(track, evt, detail, DateTime.Now, Stopwatch.GetTimestamp());
        }

        /// <summary>Same as Write, with the time stamp taken earlier: the immutable payload a component built inside its own gate (SI-R5.3 C prime).</summary>
        internal static void WriteStamped(string track, string evt, string detail, DateTime now, long qpc)
        {
            try
            {
                if (Thread.CurrentThread.GetApartmentState() == ApartmentState.STA)
                {
                    // UI thread: never wait (a wait would let the CLR dispatch window messages into BVE's code)
                    bool entered = false;
                    try
                    {
                        entered = Monitor.TryEnter(sync, 0);
                        if (!entered)
                        {
                            Interlocked.Increment(ref dropped);
                            return;
                        }

                        WriteLocked(now, qpc, track, evt, detail, true);
                    }
                    finally
                    {
                        if (entered)
                        {
                            Monitor.Exit(sync);
                        }
                    }

                    return;
                }

                lock (sync)
                {
                    WriteLocked(now, qpc, track, evt, detail, false);
                }
            }
            catch
            {
                // a diagnostic log must never take BVE down
            }
        }

        private static void WriteLocked(DateTime now, long qpc, string track, string evt, string detail, bool ui)
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
                    if (ui)
                    {
                        NoWaitResult acquired = TryAcquireNoWait(fileLock);
                        locked = acquired == NoWaitResult.Acquired || acquired == NoWaitResult.Abandoned;
                        if (!locked)
                        {
                            Interlocked.Increment(ref dropped); // busy or failed: do not wait, do not write
                            return;
                        }
                    }
                    else
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
                            Interlocked.Increment(ref dropped);
                            return;
                        }
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

                    long droppedNow = Interlocked.Read(ref dropped);
                    if (droppedNow > 0)
                    {
                        pendingDropped = droppedNow;
                        sb.Append(" droppedBefore=").Append(pendingDropped);
                    }

                    sb.Append("\r\n");
                }

                if (AppendText(sb.ToString()))
                {
                    Interlocked.Add(ref dropped, -pendingDropped);
                }
                else
                {
                    Interlocked.Increment(ref dropped);
                }
            }
            catch
            {
                Interlocked.Increment(ref dropped);
            }
            finally
            {
                if (locked && fileLock != null)
                {
                    try { fileLock.ReleaseMutex(); } catch { } // only after Acquired / Abandoned / WaitOne success
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
