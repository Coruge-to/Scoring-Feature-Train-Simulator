"""Phase PID-FIX (RED -> GREEN): the owner PID of a window comes from win32process, NOT from win32gui.

Root: the real pywin32 `win32gui` has no GetWindowThreadProcessId (it lives in `win32process`). PID-S1 (d226ad3) was only tested against a fake win32gui that
carried the function, so on a real Windows every managed step answered `pid-unreadable` and the "time and position" lock never worked.

The fakes here follow the REAL module boundary: the gui fake has NO GetWindowThreadProcessId; the process fake is a separate object with the real
signature (thread id, process id). R9 runs against the real Windows API.

PID-FIX-R1  works although the gui object has no GetWindowThreadProcessId
PID-FIX-R2  the process module's GetWindowThreadProcessId is called
PID-FIX-R3  the PROCESS id (second item) is used, never the thread id
PID-FIX-R4  the real PID of the owned HWND is returned
PID-FIX-R5  the target window is returned only when --bve-pid matches
PID-FIX-R6  mismatch / image mismatch: fail closed
PID-FIX-R7  stale HWND: nothing operated
PID-FIX-R8  a same-title window of another PID is not operated
PID-FIX-R9  real Windows, known HWNDs: the value equals the one of user32.GetWindowThreadProcessId
PID-FIX-R10 `pid-unreadable` is not raised in the normal condition (no event, no budget use) over many steps
"""
import ast
import ctypes
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TITLE = "時刻と位置"
OWN_PID, OTHER_PID = 222, 111


class RealShapedGui(object):
    """win32gui as it really is for this purpose: windows, titles, enabling, and NO GetWindowThreadProcessId."""

    def __init__(self):
        self.windows = {}
        self.enabled = {}
        self.enable_calls = []
        self.find_window_calls = 0

    def add(self, hwnd, title, pid, children=()):
        self.windows[hwnd] = {"title": title, "pid": pid, "children": list(children), "alive": True}
        for child in children:
            self.windows[child] = {"title": "", "pid": pid, "children": [], "alive": True}
            self.enabled[child] = True

    def IsWindow(self, hwnd):
        return hwnd in self.windows and self.windows[hwnd]["alive"]

    def GetWindowText(self, hwnd):
        return self.windows[hwnd]["title"]

    def EnumWindows(self, callback, extra):
        for hwnd in list(self.windows):
            if self.windows[hwnd]["alive"] and not callback(hwnd, extra):
                return

    def EnumChildWindows(self, hwnd, callback, extra):
        for child in self.windows[hwnd]["children"]:
            callback(child, extra)

    def FindWindow(self, cls, title):
        self.find_window_calls += 1
        for hwnd, w in self.windows.items():
            if w["alive"] and w["title"] == title:
                return hwnd
        return 0

    def IsWindowEnabled(self, hwnd):
        return self.enabled[hwnd]

    def EnableWindow(self, hwnd, value):
        self.enable_calls.append((hwnd, bool(value)))
        self.enabled[hwnd] = bool(value)


class RealShapedProc(object):
    """win32process.GetWindowThreadProcessId(hwnd) -> (thread id, process id); the thread id is deliberately different from every PID."""

    def __init__(self, gui):
        self.gui = gui
        self.calls = []

    def GetWindowThreadProcessId(self, hwnd):
        self.calls.append(hwnd)
        if hwnd not in self.gui.windows:
            raise OSError("invalid window handle")
        return (987654, self.gui.windows[hwnd]["pid"])


class Base(unittest.TestCase):
    def setUp(self):
        import managed_input
        self.mi = managed_input
        self.gui = RealShapedGui()
        self.proc = RealShapedProc(self.gui)
        self.saved = (managed_input.process_image_name, getattr(managed_input, "process_api", None))
        managed_input.process_image_name = lambda pid: "bvets.exe"
        self.gui.add(1000, "BVE Trainsim", OWN_PID)

    def tearDown(self):
        self.mi.process_image_name = self.saved[0]
        if self.saved[1] is not None:
            self.mi.process_api = self.saved[1]


class PID_FIX_R1_R4(Base):
    def test_r1_works_although_the_gui_object_has_no_GetWindowThreadProcessId(self):
        self.assertFalse(hasattr(self.gui, "GetWindowThreadProcessId"))
        self.assertEqual(self.mi.owned_bve_pid(self.gui, 1000, OWN_PID, proc=self.proc), (OWN_PID, "ok"))

    def test_r2_the_process_module_is_asked(self):
        self.mi.owned_bve_pid(self.gui, 1000, OWN_PID, proc=self.proc)
        self.assertEqual(self.proc.calls, [1000])

    def test_r3_the_process_id_not_the_thread_id(self):
        pid, why = self.mi.owned_bve_pid(self.gui, 1000, OWN_PID, proc=self.proc)
        self.assertEqual(pid, OWN_PID)
        self.assertNotEqual(pid, 987654)
        self.assertEqual(self.mi.window_process_id(1000, proc=self.proc), OWN_PID)

    def test_r4_window_owned_by_uses_the_real_pid(self):
        self.assertTrue(self.mi.window_owned_by(self.gui, 1000, OWN_PID, proc=self.proc))
        self.assertFalse(self.mi.window_owned_by(self.gui, 1000, 987654, proc=self.proc))


class PID_FIX_R5_R8(Base):
    TARGET, OTHER = 3000, 2000

    def test_r5_only_the_window_of_the_bve_pid_is_returned(self):
        self.gui.add(self.OTHER, TITLE, OTHER_PID)
        self.gui.add(self.TARGET, TITLE, OWN_PID)
        self.assertEqual(self.mi.GuiInputApi(self.gui, OWN_PID, proc=self.proc).find_diag_window(), self.TARGET)

    def test_r6_mismatch_is_fail_closed(self):
        self.assertEqual(self.mi.owned_bve_pid(self.gui, 1000, OTHER_PID, proc=self.proc), (None, "pid-mismatch"))
        self.mi.process_image_name = lambda pid: "notepad.exe"
        self.assertEqual(self.mi.owned_bve_pid(self.gui, 1000, OWN_PID, proc=self.proc), (None, "image-mismatch"))

    def test_r6_an_api_exception_is_fail_closed(self):
        broken = types.SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (_ for _ in ()).throw(OSError("boom")))
        self.assertEqual(self.mi.owned_bve_pid(self.gui, 1000, OWN_PID, proc=broken), (None, "pid-unreadable"))
        self.assertFalse(self.mi.window_owned_by(self.gui, 1000, OWN_PID, proc=broken))
        self.gui.add(self.TARGET, TITLE, OWN_PID)
        self.assertEqual(self.mi.GuiInputApi(self.gui, OWN_PID, proc=broken).find_diag_window(), 0)

    def test_r7_a_stale_hwnd_operates_nothing(self):
        self.gui.windows[1000]["alive"] = False
        self.assertEqual(self.mi.owned_bve_pid(self.gui, 1000, OWN_PID, proc=self.proc), (None, "stale-hwnd"))
        self.assertEqual(self.proc.calls, [])
        self.assertEqual(self.gui.enable_calls, [])

    def test_r8_a_same_title_window_of_another_pid_is_not_returned(self):
        self.gui.add(self.OTHER, TITLE, OTHER_PID, children=(2001,))
        self.assertEqual(self.mi.GuiInputApi(self.gui, OWN_PID, proc=self.proc).find_diag_window(), 0)
        self.assertEqual(self.gui.find_window_calls, 0)
        self.assertEqual(self.gui.enable_calls, [])


class PID_FIX_R9_RealWindows(unittest.TestCase):
    def test_r9_known_real_hwnds_agree_with_user32(self):
        import win32gui
        import managed_input
        user32 = ctypes.windll.user32
        checked = 0
        for hwnd in (user32.GetShellWindow(), user32.GetDesktopWindow(), user32.GetForegroundWindow()):
            if not hwnd:
                continue
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
            if not pid.value:
                continue
            self.assertEqual(managed_input.window_process_id(hwnd), pid.value)
            checked += 1
        self.assertGreaterEqual(checked, 1)
        self.assertFalse(hasattr(win32gui, "GetWindowThreadProcessId"), "this test documents why win32gui must not be used for the PID")

    def test_r9_a_real_window_is_not_reported_pid_unreadable(self):
        import managed_input
        import win32gui
        user32 = ctypes.windll.user32
        hwnd = user32.GetShellWindow() or user32.GetDesktopWindow()
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        pid, why = managed_input.owned_bve_pid(win32gui, hwnd, pid.value)
        self.assertNotEqual(why, "pid-unreadable")
        self.assertNotEqual(why, "pid-mismatch")           # the shell is not BveTs.exe: image-mismatch is the right refusal


class PID_FIX_R10_OverlayNormalConditionIsQuiet(Base):
    def test_r10_no_refusal_event_over_many_steps(self):
        import main
        gui = self.gui
        saved = (main.win32gui, self.mi.process_api if hasattr(self.mi, "process_api") else None)
        main.win32gui = gui
        self.mi.process_api = lambda: self.proc
        events = []
        o = types.SimpleNamespace()
        for name in ("_sync_time_position_window_lock", "_release_time_position_window_lock", "_expected_bve_pid", "_diag_child_is_ours"):
            setattr(o, name, types.MethodType(getattr(main.Overlay, name), o))
        o._emit_input_event = lambda event, **f: events.append((event, f))
        o.is_managed_input = True
        o.run_identity_source = lambda: (OWN_PID, 0, 1)
        o.bve_hwnd = 1000
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.time_position_child_enabled = {}
        o.time_position_lock_target = None
        self.gui.add(3000, TITLE, OWN_PID, children=(3001,))
        try:
            for _ in range(200):
                o._sync_time_position_window_lock()
        finally:
            main.win32gui = saved[0]
            if saved[1] is not None:
                self.mi.process_api = saved[1]
        self.assertEqual(events, [])
        self.assertEqual(o.time_position_lock_target, 3000)
        self.assertFalse(gui.enabled[3001])


class Static(unittest.TestCase):
    def test_no_PID_is_read_from_the_gui_object(self):
        with open(os.path.join(ROOT, "managed_input.py"), encoding="utf-8") as handle:
            src = handle.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "GetWindowThreadProcessId":
                owner = ast.get_source_segment(src, node.value)
                self.assertNotIn("gui", owner, "GetWindowThreadProcessId read from the gui object: " + owner)


if __name__ == "__main__":
    unittest.main()
