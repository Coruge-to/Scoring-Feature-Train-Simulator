# UiPumpProbe.ps1 - shared test helper (dot-sourced; defines types only, runs nothing).
# Detects whether a call made on an STA / MTA thread DISPATCHES window messages (the "message pump" that re-entered BVE's paint code in R53-04A).
# A message-only window is created on the calling thread; one posted message and one sent message are made pending; the dispatch count seen
# by the window procedure DURING the call is the result. Holders keep a Monitor / named Mutex busy on another thread.
# Test code only: nothing here is compiled into a product DLL. This script is ASCII-only on purpose.
$script:UiPumpProbeSource = @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace UiPumpProbe
{
    public sealed class ProbeWindow : NativeWindow
    {
        public const int WmPosted = 0x8001;
        public const int WmSent = 0x8002;
        public int PostedSeen;
        public int SentSeen;

        [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
        [DllImport("user32.dll")] private static extern uint GetQueueStatus(uint flags);
        [DllImport("user32.dll")] private static extern IntPtr SendMessageTimeout(IntPtr h, int msg, IntPtr w, IntPtr l, int flags, int timeout, out IntPtr result);

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WmPosted) { Interlocked.Increment(ref PostedSeen); }
            else if (m.Msg == WmSent) { Interlocked.Increment(ref SentSeen); }
            base.WndProc(ref m);
        }

        public void Create()
        {
            CreateParams cp = new CreateParams();
            cp.Parent = new IntPtr(-3); // HWND_MESSAGE
            CreateHandle(cp);
        }

        public int Total { get { return PostedSeen + SentSeen; } }

        public void Post() { PostMessage(Handle, WmPosted, IntPtr.Zero, IntPtr.Zero); }

        /// <summary>A sent message from another thread: it is dispatched only when this (the window's) thread pumps.</summary>
        public Thread SendFromOtherThread()
        {
            IntPtr h = Handle;
            Thread t = new Thread(delegate () { IntPtr r; SendMessageTimeout(h, WmSent, IntPtr.Zero, IntPtr.Zero, 2, 3000, out r); });
            t.IsBackground = true;
            t.Start();
            return t;
        }

        /// <summary>True once a SENT message from another thread is really waiting in this thread's queue (QS_SENDMESSAGE). The CLR pump dispatches SENT messages and paints; a posted message alone is not dispatched by a wait.</summary>
        public bool WaitSentPending(int timeoutMs)
        {
            Stopwatch sw = Stopwatch.StartNew();
            while (sw.ElapsedMilliseconds < timeoutMs) { if (((GetQueueStatus(0x0040) >> 16) & 0x0040) != 0) { return true; } Thread.Sleep(0); }
            return false;
        }

        public void Drain() { Application.DoEvents(); }

        public void Destroy() { try { DestroyHandle(); } catch { } }
    }

    public sealed class ProbeResult
    {
        public string Name;
        public string Apartment;
        public double ElapsedMs;
        public int Dispatched;          // messages the window procedure saw DURING the call
        public int PendingAfterDrain;   // messages that were really pending (proves the window could receive them)
        public string Value;            // "true" / "false" / "threw:<type>"
        public string Detail;
        public override string ToString() { return Name + " apt=" + Apartment + " ms=" + ElapsedMs.ToString("F2") + " dispatched=" + Dispatched + " pending=" + PendingAfterDrain + " value=" + Value + (string.IsNullOrEmpty(Detail) ? "" : " " + Detail); }
    }

    public sealed class MonitorHolder : IDisposable
    {
        private readonly object target;
        private readonly ManualResetEventSlim ready = new ManualResetEventSlim(false);
        private readonly ManualResetEventSlim release = new ManualResetEventSlim(false);
        private Thread thread;
        public MonitorHolder(object target) { this.target = target; }
        public void Start()
        {
            thread = new Thread(delegate () { Monitor.Enter(target); ready.Set(); release.Wait(); Monitor.Exit(target); });
            thread.IsBackground = true;
            thread.Start();
            ready.Wait();
        }
        public void Release() { release.Set(); if (thread != null) { thread.Join(); thread = null; } }
        public void Dispose() { Release(); }
    }

    public sealed class MutexHolder : IDisposable
    {
        private readonly string name;
        private readonly bool abandon;
        private readonly ManualResetEventSlim ready = new ManualResetEventSlim(false);
        private readonly ManualResetEventSlim release = new ManualResetEventSlim(false);
        private Thread thread;
        private Mutex keep;
        public bool AcquireFailed;
        public MutexHolder(string name, bool abandon) { this.name = name; this.abandon = abandon; }
        public void Start()
        {
            thread = new Thread(delegate ()
            {
                Mutex m = new Mutex(false, name);
                keep = m;
                if (!m.WaitOne(3000)) { AcquireFailed = true; ready.Set(); return; } // never hang the harness (a mutant that leaks ownership would block this forever)
                ready.Set();
                if (abandon) { return; } // the thread ends while owning the mutex: abandoned
                release.Wait();
                m.ReleaseMutex();
            });
            thread.IsBackground = true;
            thread.Start();
            ready.Wait();
            if (abandon) { thread.Join(); }
        }
        public void Release() { release.Set(); if (thread != null) { thread.Join(); thread = null; } }
        public void Dispose() { Release(); try { if (keep != null) { keep.Dispose(); } } catch { } }
    }

    public delegate void ProbeBody(ProbeWindow window, ProbeResult result);

    public static class Probe
    {
        /// <summary>Runs the body on a NEW thread of the given apartment, with a message-only window on that thread.</summary>
        public static ProbeResult OnThread(string name, ApartmentState apartment, ProbeBody body)
        {
            ProbeResult result = new ProbeResult();
            result.Name = name;
            result.Apartment = apartment.ToString();
            Thread t = new Thread(delegate ()
            {
                ProbeWindow w = new ProbeWindow();
                try
                {
                    w.Create();
                    body(w, result);
                }
                catch (Exception ex) { result.Detail = "harness-exception:" + ex.GetType().Name + ":" + ex.Message; }
                finally { w.Destroy(); }
            });
            t.SetApartmentState(apartment);
            t.IsBackground = true;
            t.Start();
            t.Join();
            return result;
        }

        /// <summary>Makes one posted and one sent message pending, runs the call, records the dispatch count and the time.</summary>
        public static void Measure(ProbeWindow w, ProbeResult r, Action call)
        {
            w.Post();
            Thread sender = w.SendFromOtherThread();
            w.WaitSentPending(1000); // the sender is now blocked in SendMessage until this thread pumps (verified by the queue status, not by a sleep)
            int before = w.Total;
            Stopwatch sw = Stopwatch.StartNew();
            try { call(); }
            catch (Exception ex) { r.Value = "threw:" + ex.GetType().Name; }
            sw.Stop();
            r.ElapsedMs = sw.Elapsed.TotalMilliseconds;
            r.Dispatched = w.Total - before;
            int mid = w.Total;
            w.Drain();
            sender.Join(3000);
            r.PendingAfterDrain = w.Total - mid;
        }

        /// <summary>Same, for a call on a reflected product method (static, public or not).</summary>
        public static void MeasureMethod(ProbeWindow w, ProbeResult r, MethodInfo method, object target, object[] args)
        {
            Measure(w, r, delegate () { method.Invoke(target, args); });
        }
    }
}
'@

# Compiles the helper (plus optional extra C# that uses it) once per session. The extra source must live in its own namespace.
function Install-UiPumpProbe([string]$ExtraSource = '', [string]$ExtraMarkerType = '') {
    if ('UiPumpProbe.ProbeWindow' -as [type]) { if (-not $ExtraMarkerType -or ($ExtraMarkerType -as [type])) { return } else { throw 'UiPumpProbe helper already compiled without the requested extra source; start a new process' } }
    Add-Type -ReferencedAssemblies 'System.Windows.Forms' -TypeDefinition ($script:UiPumpProbeSource + "
" + $ExtraSource)
}
