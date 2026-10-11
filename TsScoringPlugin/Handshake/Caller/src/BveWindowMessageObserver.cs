using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace TSScoringPlugin.Handshake
{
    internal sealed class BveWindowMessageObserver : NativeWindow, IDisposable
    {
        private const int WM_CLOSE = 0x0010;
        private const int WM_DESTROY = 0x0002;
        private const int WM_SIZE = 0x0005;
        private const int WM_WINDOWPOSCHANGING = 0x0046;
        private const int WM_WINDOWPOSCHANGED = 0x0047;
        private const int WM_NCDESTROY = 0x0082;

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);

        private readonly object gate = new object();
        private readonly int instanceNumber;
        private readonly int processId;
        private readonly EventWaitHandle fullscreenActive;
        private readonly EventWaitHandle restoreRequested;
        private readonly EventWaitHandle restoreCompleted;
        private IntPtr observedWindow;
        private bool attached;
        private bool disposed;
        private bool waitingForRestore;
        private bool allowCloseOnce;

        private BveWindowMessageObserver(int instanceNumber, int processId)
        {
            this.instanceNumber = instanceNumber;
            this.processId = processId;
            fullscreenActive = new EventWaitHandle(false, EventResetMode.ManualReset, F11CloseProtocol.FullscreenActive(processId));
            restoreRequested = new EventWaitHandle(false, EventResetMode.AutoReset, F11CloseProtocol.RestoreRequested(processId));
            restoreCompleted = new EventWaitHandle(false, EventResetMode.AutoReset, F11CloseProtocol.RestoreCompleted(processId));
        }

        internal bool Attached { get { return attached; } }

        internal static BveWindowMessageObserver TryAttach(int instanceNumber)
        {
            int processId = Process.GetCurrentProcess().Id;
            BveWindowMessageObserver observer = new BveWindowMessageObserver(instanceNumber, processId);
            observer.AttachCurrentMainWindow();
            return observer;
        }

        internal void RetryAttach()
        {
            if (!attached && !disposed)
            {
                AttachCurrentMainWindow();
            }
        }

        private void AttachCurrentMainWindow()
        {
            try
            {
                IntPtr window = Process.GetCurrentProcess().MainWindowHandle;
                if (window == IntPtr.Zero)
                {
                    ObservationLog.Write("B", "F11_A2_ATTACH_SKIPPED", "inst=" + instanceNumber + " reason=no-main-window");
                    return;
                }

                uint windowProcessId;
                uint windowThreadId = GetWindowThreadProcessId(window, out windowProcessId);
                if (windowThreadId == 0 || windowProcessId != unchecked((uint)processId))
                {
                    ObservationLog.Write("B", "F11_A2_ATTACH_SKIPPED", "inst=" + instanceNumber + " reason=window-mismatch");
                    return;
                }

                observedWindow = window;
                AssignHandle(window);
                attached = true;
                ObservationLog.Write("B", "F11_A2_ATTACHED", "inst=" + instanceNumber + " hwnd=" + Hex(window) + " uiThread=" + windowThreadId);
            }
            catch (Exception ex)
            {
                ObservationLog.Write("B", "F11_A2_ATTACH_FAILED", "inst=" + instanceNumber + " type=" + ex.GetType().Name);
            }
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == WM_CLOSE && HandleClose())
            {
                return;
            }

            bool observed = IsObserved(message.Msg);
            if (observed) { ObservationLog.Write("B", "F11_A2_MSG_ENTER", Detail(message)); }
            base.WndProc(ref message);
            if (observed) { ObservationLog.Write("B", "F11_A2_MSG_RETURN", Detail(message)); }
        }

        private bool HandleClose()
        {
            lock (gate)
            {
                if (allowCloseOnce)
                {
                    allowCloseOnce = false;
                    ObservationLog.Write("B", "F11_A2_CLOSE_ALLOWED", "inst=" + instanceNumber + " reason=reposted");
                    return false;
                }

                if (waitingForRestore)
                {
                    ObservationLog.Write("B", "F11_A2_CLOSE_SUPPRESSED", "inst=" + instanceNumber + " reason=already-waiting");
                    return true;
                }

                if (!fullscreenActive.WaitOne(0))
                {
                    ObservationLog.Write("B", "F11_A2_CLOSE_PASSTHROUGH", "inst=" + instanceNumber + " fullscreen=0");
                    return false;
                }

                waitingForRestore = true;
                restoreCompleted.Reset();
                restoreRequested.Set();
                ObservationLog.Write("B", "F11_A2_RESTORE_REQUESTED", "inst=" + instanceNumber + " timeoutMs=" + F11CloseProtocol.RestoreTimeoutMs);
                Thread waiter = new Thread(WaitForRestoreAndRepost);
                waiter.IsBackground = true;
                waiter.Name = "TSScoringPlugin.F11CloseWaiter";
                waiter.Start();
                return true;
            }
        }

        private void WaitForRestoreAndRepost()
        {
            bool completed = false;
            try { completed = restoreCompleted.WaitOne(F11CloseProtocol.RestoreTimeoutMs); }
            catch (Exception ex) { ObservationLog.Write("B", "F11_A2_WAIT_FAILED", "inst=" + instanceNumber + " type=" + ex.GetType().Name); }

            lock (gate)
            {
                if (disposed) { return; }
                waitingForRestore = false;
                allowCloseOnce = true;
            }

            ObservationLog.Write("B", completed ? "F11_A2_RESTORE_COMPLETED" : "F11_A2_RESTORE_TIMEOUT", "inst=" + instanceNumber);
            if (!PostMessage(observedWindow, WM_CLOSE, IntPtr.Zero, IntPtr.Zero))
            {
                ObservationLog.Write("B", "F11_A2_REPOST_FAILED", "inst=" + instanceNumber + " error=" + Marshal.GetLastWin32Error());
            }
            else
            {
                ObservationLog.Write("B", "F11_A2_CLOSE_REPOSTED", "inst=" + instanceNumber);
            }
        }

        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) { return; }
                disposed = true;
            }

            try { if (attached) { ReleaseHandle(); } } catch { }
            attached = false;
            try { fullscreenActive.Dispose(); } catch { }
            try { restoreRequested.Dispose(); } catch { }
            try { restoreCompleted.Dispose(); } catch { }
            ObservationLog.Write("B", "F11_A2_OBSERVER_DISPOSED", "inst=" + instanceNumber);
        }

        private string Detail(Message message)
        {
            return "inst=" + instanceNumber + " msg=" + message.Msg + " hwnd=" + Hex(message.HWnd);
        }

        private static bool IsObserved(int message)
        {
            return message == WM_CLOSE || message == WM_DESTROY || message == WM_NCDESTROY || message == WM_SIZE || message == WM_WINDOWPOSCHANGING || message == WM_WINDOWPOSCHANGED;
        }

        private static string Hex(IntPtr value) { return "0x" + value.ToInt64().ToString("X"); }
    }
}
