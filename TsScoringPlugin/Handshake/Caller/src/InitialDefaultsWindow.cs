using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;

// ============================================================================
// INITIAL DEFAULTS - the window side of the Properties entry (Owner 2026-11-12, Stage IO-1).
// The 'initial defaults' window is an OWNED window of the BVE settings dialog that opened it (the Python side sets the owner; see initial_defaults_ui.py). This file holds the few Win32 calls the Caller needs:
//   * to validate the owner candidate (the HWND must exist and belong to THIS BVE pid; an HWND of another pid is never used),
//   * to find the window of the child process (only top-level windows of the child's own pid are looked at),
//   * to bring an existing window back when Properties is pressed again: restore if minimised, re-own it to the BVE settings dialog that is in front now, SetForegroundWindow, a limited AttachThreadInput retry,
//     and FlashWindowEx when the system refuses to move the window to the front (it is never forced; there is no key injection of any kind),
//   * to see whether an initial-defaults window of any BVE already exists (the named mutex of the Python side), so that a second BVE never starts a second window and never takes the ownership over.
// Everything here is best effort: every call is guarded, nothing throws into BVE, nothing waits for the child.
// ============================================================================
namespace TSScoringPlugin.Handshake
{
    internal enum InitialDefaultsActivation
    {
        None = 0,
        NoWindow = 1,
        Reactivated = 2,
        Flashed = 3,
        ForeignRejected = 4,
    }

    internal static class InitialDefaultsWindow
    {
        internal const string MutexName = "Local\\TSScoring.InitialDefaults.v1";
        private const int SW_RESTORE = 9;
        private const uint GW_OWNER = 4;
        private const int GWLP_HWNDPARENT = -8;
        private const long WS_CAPTION = 0x00C00000L;
        private const int GWL_STYLE = -16;
        private const uint FLASHW_ALL = 3;
        private const uint FLASHW_TIMERNOFG = 12;
        private const uint SYNCHRONIZE = 0x00100000;
        private const int ForegroundPollMs = 160;

        /// <summary>Test hook only (false in production): the system refuses to move the window to the front, so that the FlashWindowEx fallback can be tested.</summary>
        internal static bool TestForegroundRefused { get; set; }

        /// <summary>Test hook only (null in production): told which window was flashed.</summary>
        internal static Action<IntPtr> FlashObserver { get; set; }

        private delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)]
        private struct FLASHWINFO
        {
            public uint cbSize;
            public IntPtr hwnd;
            public uint dwFlags;
            public uint uCount;
            public uint dwTimeout;
        }

        [DllImport("user32.dll")]
        private static extern bool IsWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsIconic(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        private static extern bool BringWindowToTop(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumProc callback, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern IntPtr GetWindow(IntPtr hWnd, uint command);

        [DllImport("user32.dll", EntryPoint = "GetWindowLongW")]
        private static extern int GetWindowLong32(IntPtr hWnd, int index);

        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
        private static extern IntPtr GetWindowLongPtr64(IntPtr hWnd, int index);

        [DllImport("user32.dll", EntryPoint = "SetWindowLongW")]
        private static extern int SetWindowLong32(IntPtr hWnd, int index, int newLong);

        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
        private static extern IntPtr SetWindowLongPtr64(IntPtr hWnd, int index, IntPtr newLong);

        [DllImport("user32.dll")]
        private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);

        [DllImport("user32.dll")]
        private static extern bool FlashWindowEx(ref FLASHWINFO info);

        [DllImport("kernel32.dll")]
        private static extern uint GetCurrentThreadId();

        [DllImport("kernel32.dll", EntryPoint = "OpenMutexW", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr OpenMutex(uint access, bool inherit, string name);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        /// <summary>The pid that owns the window (0 when the window does not exist).</summary>
        internal static int PidOf(IntPtr hwnd)
        {
            try
            {
                if (hwnd == IntPtr.Zero || !IsWindow(hwnd))
                {
                    return 0;
                }

                uint pid;
                GetWindowThreadProcessId(hwnd, out pid);
                return (int)pid;
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>True when the HWND exists and belongs to exactly this pid (a window of another pid is never usable).</summary>
        internal static bool BelongsTo(IntPtr hwnd, int pid)
        {
            return pid > 0 && PidOf(hwnd) == pid;
        }

        internal static IntPtr Foreground()
        {
            try
            {
                return GetForegroundWindow();
            }
            catch
            {
                return IntPtr.Zero;
            }
        }

        internal static IntPtr OwnerOf(IntPtr hwnd)
        {
            try
            {
                return hwnd == IntPtr.Zero ? IntPtr.Zero : GetWindow(hwnd, GW_OWNER);
            }
            catch
            {
                return IntPtr.Zero;
            }
        }

        /// <summary>The HWND text of a log line (hexadecimal, never longer than 8 digits).</summary>
        internal static string Hex(IntPtr hwnd)
        {
            return "0x" + (hwnd.ToInt64() & 0xFFFFFFFFL).ToString("X");
        }

        /// <summary>The decimal text handed to the child (a plain unsigned number; the Python side parses it strictly).</summary>
        internal static string Decimal(IntPtr hwnd)
        {
            return (hwnd.ToInt64() & 0xFFFFFFFFL).ToString();
        }

        internal static bool AnyWindowOfTheNamedMutexExists()
        {
            IntPtr handle = IntPtr.Zero;
            try
            {
                handle = OpenMutex(SYNCHRONIZE, false, MutexName);
                return handle != IntPtr.Zero;
            }
            catch
            {
                return false;
            }
            finally
            {
                if (handle != IntPtr.Zero)
                {
                    CloseHandle(handle);
                }
            }
        }

        /// <summary>The window of the child: a visible (or minimised) top-level window WITH a title bar that belongs to exactly the child's pid. Only that pid is looked at.</summary>
        internal static IntPtr FindWindowOf(int pid)
        {
            List<IntPtr> found = new List<IntPtr>();
            try
            {
                EnumWindows(delegate(IntPtr hwnd, IntPtr lParam)
                {
                    uint owner;
                    GetWindowThreadProcessId(hwnd, out owner);
                    if ((int)owner == pid && (IsWindowVisible(hwnd) || IsIconic(hwnd)) && (Style(hwnd) & WS_CAPTION) == WS_CAPTION)
                    {
                        found.Add(hwnd);
                    }

                    return true;
                }, IntPtr.Zero);
            }
            catch
            {
            }

            return found.Count == 0 ? IntPtr.Zero : found[0];
        }

        private static long Style(IntPtr hwnd)
        {
            try
            {
                return (long)(uint)(IntPtr.Size == 8 ? GetWindowLongPtr64(hwnd, GWL_STYLE).ToInt64() : GetWindowLong32(hwnd, GWL_STYLE));
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>Makes <paramref name="owner"/> the owner of <paramref name="hwnd"/> (a window of the child process; the call is allowed across processes of the same user).</summary>
        internal static bool SetOwner(IntPtr hwnd, IntPtr owner)
        {
            try
            {
                if (IntPtr.Size == 8)
                {
                    SetWindowLongPtr64(hwnd, GWLP_HWNDPARENT, owner);
                }
                else
                {
                    SetWindowLong32(hwnd, GWLP_HWNDPARENT, owner.ToInt32());
                }

                return OwnerOf(hwnd) == owner;
            }
            catch
            {
                return false;
            }
        }

        private static bool WaitForeground(IntPtr hwnd)
        {
            if (TestForegroundRefused)
            {
                return false;
            }

            int waited = 0;
            while (waited <= ForegroundPollMs)
            {
                if (Foreground() == hwnd)
                {
                    return true;
                }

                Thread.Sleep(20);
                waited += 20;
            }

            return Foreground() == hwnd;
        }

        /// <summary>Brings the existing window back: restore when minimised, re-own to the settings dialog in front, SetForegroundWindow, a limited AttachThreadInput retry, FlashWindowEx as the last resort.</summary>
        internal static InitialDefaultsActivation Reactivate(IntPtr window, IntPtr newOwner, int bvePid)
        {
            try
            {
                if (IsIconic(window))
                {
                    ShowWindow(window, SW_RESTORE);
                    ObservationLog.Write("A", "INITDEF_RESTORED", "hwnd=" + Hex(window));
                }

                if (newOwner != IntPtr.Zero && BelongsTo(newOwner, bvePid) && OwnerOf(window) != newOwner)
                {
                    IntPtr before = OwnerOf(window);
                    bool ok = SetOwner(window, newOwner);
                    ObservationLog.Write("A", ok ? "INITDEF_OWNER_REBOUND" : "INITDEF_OWNER_INVALID", "hwnd=" + Hex(window) + " from=" + Hex(before) + " to=" + Hex(newOwner));
                }

                BringWindowToTop(window);
                SetForegroundWindow(window);
                bool front = WaitForeground(window);
                if (!front)
                {
                    IntPtr fg = Foreground();
                    uint fgThread = 0;
                    uint pidIgnored;
                    if (fg != IntPtr.Zero)
                    {
                        fgThread = GetWindowThreadProcessId(fg, out pidIgnored);
                    }

                    uint me = GetCurrentThreadId();
                    bool attached = false;
                    try
                    {
                        if (fgThread != 0 && fgThread != me)
                        {
                            attached = AttachThreadInput(me, fgThread, true);
                        }

                        BringWindowToTop(window);
                        SetForegroundWindow(window);
                    }
                    finally
                    {
                        if (attached)
                        {
                            AttachThreadInput(me, fgThread, false);
                        }
                    }

                    front = WaitForeground(window);
                }

                if (front)
                {
                    ObservationLog.Write("A", "INITDEF_REACTIVATED", "hwnd=" + Hex(window));
                    return InitialDefaultsActivation.Reactivated;
                }

                FLASHWINFO info = new FLASHWINFO();
                info.cbSize = (uint)Marshal.SizeOf(typeof(FLASHWINFO));
                info.hwnd = window;
                info.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG;
                info.uCount = 3;
                info.dwTimeout = 0;
                FlashWindowEx(ref info);
                try
                {
                    Action<IntPtr> observer = FlashObserver;
                    if (observer != null)
                    {
                        observer(window);
                    }
                }
                catch
                {
                }

                ObservationLog.Write("A", "INITDEF_FLASHED", "hwnd=" + Hex(window));
                return InitialDefaultsActivation.Flashed;
            }
            catch
            {
                return InitialDefaultsActivation.None;
            }
        }

        /// <summary>The Properties button was pressed again while the child lives: find its window (only the child's own pid) and bring it back. Never starts a process.</summary>
        internal static InitialDefaultsActivation ActivateExisting(Process running, int ownerBvePid, InitialDefaultsOwner request)
        {
            try
            {
                if (request == null || request.BvePid != ownerBvePid)
                {
                    ObservationLog.Write("A", "INITDEF_FOREIGN_BVE_REJECTED", "bvePid=" + (request == null ? 0 : request.BvePid) + " ownerPid=" + ownerBvePid);
                    return InitialDefaultsActivation.ForeignRejected;
                }

                IntPtr window = FindWindowOf(running.Id);
                if (window == IntPtr.Zero)
                {
                    ObservationLog.Write("A", "INITDEF_NO_WINDOW", "pid=" + running.Id);
                    return InitialDefaultsActivation.NoWindow;
                }

                ObservationLog.Write("A", "INITDEF_HWND_FOUND", "hwnd=" + Hex(window) + " pid=" + running.Id);
                IntPtr newOwner = request.OwnerHwnd != IntPtr.Zero ? request.OwnerHwnd : request.MainHwnd;
                return Reactivate(window, newOwner, ownerBvePid);
            }
            catch
            {
                return InitialDefaultsActivation.None;
            }
        }
    }
}
