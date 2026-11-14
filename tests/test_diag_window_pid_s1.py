"""Phase PID-S1 (RED -> GREEN): the "time and position" window lock of the MANAGED Overlay touches only the window of the BVE process it is linked to.

PID-R1 two windows with the title: only the window of the owned BVE PID is returned / locked
PID-R2 only another process's window: nothing is operated (and no title-only lookup is made)
PID-R3 the PID of the linked HWND and --bve-pid disagree (or the image is not BveTs.exe): fail closed, no guess
PID-R4 a stale HWND is refused
PID-R6 plain (non managed) mode keeps its title lookup
Real Overlay methods run against a fake win32gui; no window, no BVE.
"""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TITLE = "時刻と位置"
OWN_PID, OTHER_PID = 222, 111


class FakeGui(object):
    def __init__(self):
        self.windows = {}       # hwnd -> dict(title, pid, children, alive)
        self.enabled = {}       # child hwnd -> bool
        self.find_window_calls = 0
        self.enable_calls = []

    def add(self, hwnd, title, pid, children=()):
        self.windows[hwnd] = {"title": title, "pid": pid, "children": list(children), "alive": True}
        for child in children:
            self.windows[child] = {"title": "", "pid": pid, "children": [], "alive": True}
            self.enabled[child] = True

    def IsWindow(self, hwnd):
        return hwnd in self.windows and self.windows[hwnd]["alive"]

    def GetWindowThreadProcessId(self, hwnd):
        return (1, self.windows[hwnd]["pid"])

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


class Harness(unittest.TestCase):
    def setUp(self):
        import main
        import managed_input
        self.main, self.mi = main, managed_input
        self.gui = FakeGui()
        self.saved = (main.win32gui, managed_input.process_image_name)
        main.win32gui = self.gui
        managed_input.process_image_name = lambda pid: "bvets.exe"
        self.events = []
        o = types.SimpleNamespace()
        for name in ("_sync_time_position_window_lock", "_release_time_position_window_lock", "_expected_bve_pid", "_diag_child_is_ours"):
            setattr(o, name, types.MethodType(getattr(main.Overlay, name), o))
        o._emit_input_event = lambda event, **f: self.events.append((event, f))
        o.is_managed_input = True
        o.run_identity_source = lambda: (OWN_PID, 0, 1)
        o.bve_hwnd = 1000
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.time_position_child_enabled = {}
        o.time_position_lock_target = None
        self.o = o
        self.gui.add(1000, "BVE Trainsim", OWN_PID)

    def tearDown(self):
        self.main.win32gui, self.mi.process_image_name = self.saved


class PID_R1_R2_OwnedWindowOnly(Harness):
    def test_r1_two_windows_with_the_title_only_the_owned_one_is_locked(self):
        self.gui.add(2000, TITLE, OTHER_PID, children=(2001, 2002))
        self.gui.add(3000, TITLE, OWN_PID, children=(3001, 3002))
        self.o._sync_time_position_window_lock()
        self.assertEqual(self.o.time_position_lock_target, 3000)
        self.assertFalse(self.gui.enabled[3001] or self.gui.enabled[3002])
        self.assertTrue(self.gui.enabled[2001] and self.gui.enabled[2002])
        self.assertEqual(self.gui.find_window_calls, 0)
        self.assertEqual(self.events, [])

    def test_r1_find_diag_window_returns_the_owned_one_even_if_the_other_comes_first(self):
        self.gui.add(2000, TITLE, OTHER_PID)
        self.gui.add(3000, TITLE, OWN_PID)
        self.assertEqual(self.mi.GuiInputApi(self.gui, OWN_PID).find_diag_window(), 3000)

    def test_r2_only_another_process_window_nothing_is_operated(self):
        self.gui.add(2000, TITLE, OTHER_PID, children=(2001, 2002))
        self.o._sync_time_position_window_lock()
        self.assertEqual(self.gui.enable_calls, [])
        self.assertEqual(self.gui.find_window_calls, 0)
        self.assertIsNone(self.o.time_position_lock_target)

    def test_release_after_the_owned_window_goes_restores_only_what_was_disabled(self):
        self.gui.add(3000, TITLE, OWN_PID, children=(3001,))
        self.o._sync_time_position_window_lock()
        self.assertFalse(self.gui.enabled[3001])
        self.o.is_scoring_mode = False
        self.o._sync_time_position_window_lock()
        self.assertTrue(self.gui.enabled[3001])
        self.assertIsNone(self.o.time_position_lock_target)

    def test_a_child_that_changed_owner_is_not_re_enabled(self):
        self.gui.add(3000, TITLE, OWN_PID, children=(3001,))
        self.o._sync_time_position_window_lock()
        self.gui.windows[3001]["pid"] = OTHER_PID           # a recycled handle that now belongs to another process
        self.gui.enable_calls.clear()
        self.o._release_time_position_window_lock()
        self.assertEqual(self.gui.enable_calls, [])


class PID_R3_R4_FailClosed(Harness):
    def _no_effect(self, reason):
        self.gui.add(3000, TITLE, OWN_PID, children=(3001,))
        self.gui.add(2000, TITLE, OTHER_PID, children=(2001,))
        self.o._sync_time_position_window_lock()
        self.assertEqual(self.gui.enable_calls, [])
        self.assertEqual(self.gui.find_window_calls, 0)
        self.assertIsNone(self.o.time_position_lock_target)
        self.assertEqual(self.events, [("diag-window-refused", {"reason": reason})])

    def test_r3_runtime_pid_and_bve_pid_disagree(self):
        self.o.run_identity_source = lambda: (OTHER_PID, 0, 1)      # --bve-pid says 111, the linked HWND belongs to 222: neither is adopted
        self._no_effect("pid-mismatch")

    def test_r3_the_image_is_not_the_bve_executable(self):
        self.mi.process_image_name = lambda pid: "notepad.exe"
        self._no_effect("image-mismatch")

    def test_r3_the_image_is_unreadable(self):
        self.mi.process_image_name = lambda pid: None
        self._no_effect("image-mismatch")

    def test_r3_no_expected_pid(self):
        self.o.run_identity_source = lambda: (None, 0, 1)
        self._no_effect("no-expected-pid")

    def test_r4_stale_hwnd(self):
        self.gui.windows[1000]["alive"] = False
        self._no_effect("stale-hwnd")

    def test_r4_no_linked_hwnd(self):
        self.o.bve_hwnd = None
        self._no_effect("stale-hwnd")

    def test_no_event_while_scoring_is_off(self):
        self.o.run_identity_source = lambda: (OTHER_PID, 0, 1)
        self.o.is_scoring_mode = False
        self.o._sync_time_position_window_lock()
        self.assertEqual(self.events, [])


class PID_R6_PlainModeKeepsItsContract(Harness):
    def test_plain_mode_uses_the_title_lookup_as_before(self):
        self.o.is_managed_input = False
        self.gui.add(3000, TITLE, OWN_PID, children=(3001,))
        self.o._sync_time_position_window_lock()
        self.assertEqual(self.gui.find_window_calls, 1)
        self.assertEqual(self.o.time_position_lock_target, 3000)
        self.assertFalse(self.gui.enabled[3001])


class Static(unittest.TestCase):
    def test_the_title_only_lookup_is_not_on_the_managed_path(self):
        import ast
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as handle:
            src = handle.read()
        tree = ast.parse(src)
        func = [n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Overlay" for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "_sync_time_position_window_lock"][0]
        body = ast.get_source_segment(src, func)
        self.assertIn("managed_input.owned_bve_pid(", body)
        self.assertIn("managed_input.window_owned_by(", body)
        managed_part, _, plain_part = body.partition("else:\n                diag_hwnd = win32gui.FindWindow")
        self.assertTrue(plain_part, "the title-only lookup must sit in the plain-mode else branch")
        self.assertNotIn("FindWindow(None", managed_part)


if __name__ == "__main__":
    unittest.main()
