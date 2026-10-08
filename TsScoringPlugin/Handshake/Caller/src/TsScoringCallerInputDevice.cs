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
// Configure: one status dialog (everything is observed there).
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
        }

        public void Tick()
        {
            // intentionally empty: BVE's input polling stays untouched
        }

        public void SetAxisRanges(int[][] ranges)
        {
        }

        public void Configure(IWin32Window owner)
        {
            ObservationLog.Write("A", "CONFIGURE_OPENED", "inst=" + instNo);
            try
            {
                IntPtr handle = owner == null ? IntPtr.Zero : owner.Handle;
                MessageBoxW(handle, session.BuildStatusText(), HandshakeSession.ProductDisplayName + " - handshake status", MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND);
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
            try { session.End(); } catch { }
        }
    }
}
