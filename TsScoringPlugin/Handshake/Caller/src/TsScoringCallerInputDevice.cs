using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Mackoy.Bvets;

// ============================================================================
// PHASE C1 OBSERVATION BUILD - input-device Caller (human-facing name: "TS Scoring").
// Implements only BVE's public Mackoy.Bvets.IInputDevice. It does NOT start
// Python, HUD, scoring, UDP, hooks, registry, or touch BVE/BveEX settings.
// Constructor: nothing (Phase C1 adds log lines only). Load: publish Enabled and start the ONE background monitor.
// Dispose: stop monitoring, publish Stop, withdraw Enabled, release everything.
// Configure (Properties): starts the 'initial defaults' window (a separate Python process, from launcher.json; see InitialDefaultsLauncher.cs) and returns at once;
// the status dialog is only the fallback of a failed start.
// The only file this DLL writes is the Phase C1 observation log (Shared\ObservationLog.cs).
// The class/namespace names are technical identifiers and keep "TSScoringPlugin".
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    public class TsScoringCallerInputDevice : IInputDevice
    {
        private const uint MB_OK = 0x00000000;
        private const uint MB_ICONINFORMATION = 0x00000040;
        private const uint MB_SETFOREGROUND = 0x00010000;

        [DllImport("user32.dll", EntryPoint = "MessageBoxW", CharSet = CharSet.Unicode)]
        private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

        private static int instances;

        private readonly int instNo;
        private readonly HandshakeSession session;
        private BveWindowMessageObserver closeObserver;
        private bool closeObserverTickRetryDone;

        public TsScoringCallerInputDevice()
        {
            // no side effects before Load (Phase C1 only writes log lines here)
            instNo = Interlocked.Increment(ref instances);
            ObservationLog.Write("B", "CALLER_CTOR_BEGIN", "inst=" + instNo + " ver=" + ObservationLog.Version + " bitness=" + (Environment.Is64BitProcess ? 64 : 32));
            session = new HandshakeSession();
            ObservationLog.Write("B", "CALLER_CTOR_END", "inst=" + instNo);
        }

        public void Load(string path)
        {
            ObservationLog.Write("B", "CALLER_LOAD_BEGIN", "inst=" + instNo);
            try { session.Start(); } catch { }
            try { closeObserver = BveWindowMessageObserver.TryAttach(instNo); } catch { }
        }

        public void Tick()
        {
            // Phase F11-A1 diagnostic only: Load can run before BVE has published MainWindowHandle.
            // Retry exactly once on BVE's first Tick, when the main window is already available.
            if (!closeObserverTickRetryDone)
            {
                closeObserverTickRetryDone = true;
                if (closeObserver == null)
                {
                    try { closeObserver = BveWindowMessageObserver.TryAttach(instNo); } catch { }
                }
                else
                {
                    try { closeObserver.RetryAttach(); } catch { }
                }
            }

            try { session.NotifyTick(); } catch { }
        }

        public void SetAxisRanges(int[][] ranges)
        {
        }

        /// <summary>Test hook only (null in production): receives the notice that would be shown in the MessageBox, so that a test never opens a window.</summary>
        internal static Action<IntPtr, string, string> ShowNotice { get; set; }

        public void Configure(IWin32Window owner)
        {
            ObservationLog.Write("A", "CONFIGURE_OPENED", "inst=" + instNo);
            try
            {
                // Properties: start the 'initial defaults' window (a separate Python process, started from launcher.json) and return at once.
                // A second press while the window is open starts nothing. Only a failed start falls back to the status text of the handshake (as before).
                string notice = null;
                try
                {
                    InitialDefaultsLaunchResult launch = InitialDefaultsLauncher.TryLaunch();
                    if (!launch.Started && !launch.AlreadyRunning)
                    {
                        notice = InitialDefaultsLauncher.FailureNotice(launch);
                    }
                }
                catch
                {
                    notice = InitialDefaultsLauncher.FailureNotice(null);
                }

                if (notice != null)
                {
                    IntPtr handle = owner == null ? IntPtr.Zero : owner.Handle;
                    string text = notice + "\r\n\r\n" + session.BuildStatusText();
                    string caption = HandshakeSession.ProductDisplayName + " - handshake status";
                    Action<IntPtr, string, string> show = ShowNotice;
                    if (show != null)
                    {
                        show(handle, text, caption);
                    }
                    else
                    {
                        MessageBoxW(handle, text, caption, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND);
                    }
                }
            }
            catch
            {
            }

            ObservationLog.Write("A", "CONFIGURE_CLOSED", "inst=" + instNo);
        }

        // This device never produces input; subscriptions are accepted and ignored.
        public event InputEventHandler LeverMoved
        {
            add { }
            remove { }
        }

        public event InputEventHandler KeyDown
        {
            add { }
            remove { }
        }

        public event InputEventHandler KeyUp
        {
            add { }
            remove { }
        }

        public void Dispose()
        {
            ObservationLog.Write("B", "F11_A2_INPUT_DISPOSE_BEGIN", "inst=" + instNo);
            try { session.End(); } catch { }
            try { if (closeObserver != null) { closeObserver.Dispose(); } } catch { }
            closeObserver = null;
            ObservationLog.Write("B", "F11_A2_INPUT_DISPOSE_END", "inst=" + instNo);
        }
    }
}
