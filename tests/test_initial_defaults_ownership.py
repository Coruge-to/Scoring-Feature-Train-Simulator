"""INITIAL-DEFAULTS window ownership (Owner 2026-11-12, Stage IO-1): the 'initial defaults' window is an OWNED window of the BVE settings dialog that opened it (Properties) with the STANDARD owned-window behaviour (no own taskbar button, no Alt+Tab entry; Owner ruling 2026-11-12 - recovery is the Properties re-press, not the taskbar),
never goes behind its owner, is not global top-most, follows the owner to the BVE main window when the settings dialog closes, and ends (without saving) when BVE ends.

NATIVE-ONLY tests: they start the REAL product entry (`python main.py --initial-defaults`) in child processes together with a fake-BVE helper process that owns REAL top-level windows (tests/ownership_fake_bve.py);
the owner / z-order / style facts are read with Win32 from this process. They need an interactive Windows desktop and are never judged offscreen. Every child gets a temporary LOCALAPPDATA (nothing real is touched).
Messages: 'IO1-RED: ...' = the ownership contract is not met (PRODUCT-RED on d4eb3cc); 'IO1-GUARD: ...' = a contract that already holds and must stay GREEN; 'IO1-HARNESS: ...' = the harness itself is broken.
The Caller half of the contract (re-press, restore, re-own, foreground, flash, foreign BVE, double start) is tested by TsScoringPlugin/Handshake/Tests/Test-InitialDefaultsOwnership.ps1."""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)                                  # runnable alone from the tests folder (python -m unittest test_initial_defaults_ownership)
ENTRY =[sys.executable, "-B", os.path.join(ROOT, "main.py"), "--initial-defaults"]
HELPER = [sys.executable, "-B", os.path.join(HERE, "ownership_fake_bve.py")]
WINDOWS = os.name == "nt"
TITLE = "初期値設定"
ENV_PID, ENV_OWNER, ENV_MAIN = "TSSCORING_INITDEF_BVE_PID", "TSSCORING_INITDEF_OWNER_HWND", "TSSCORING_INITDEF_BVE_MAIN_HWND"
GWL_EXSTYLE, GWL_STYLE, GW_OWNER = -20, -16, 4
WS_EX_TOPMOST, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW, WS_CAPTION, WS_SYSMENU = 0x8, 0x40000, 0x80, 0x00C00000, 0x00080000
SW_MINIMIZE, SW_RESTORE = 6, 9


def shell_lists_in_taskbar(f):
    """The documented shell rule (Win32 'Window Features / Taskbar buttons'): a visible window gets a taskbar button when it is unowned and not a tool window, or when it has WS_EX_APPWINDOW; an owned window without WS_EX_APPWINDOW gets none."""
    if f["ex"] & WS_EX_TOOLWINDOW and not f["ex"] & WS_EX_APPWINDOW:
        return False
    return bool(f["ex"] & WS_EX_APPWINDOW) or not f["owner"]


def shell_lists_in_alt_tab(f):
    """Alt+Tab lists the same windows as the taskbar rule (visible, not a tool window, unowned or WS_EX_APPWINDOW)."""
    return shell_lists_in_taskbar(f) and not (f["ex"] & WS_EX_TOOLWINDOW and not f["ex"] & WS_EX_APPWINDOW)

if WINDOWS:
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    u32.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]
    u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    u32.GetWindow.restype = wt.HWND
    u32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    u32.IsWindow.argtypes = [wt.HWND]
    u32.IsIconic.argtypes = [wt.HWND]
    u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    u32.IsWindowVisible.argtypes = [wt.HWND]
    u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    u32.GetForegroundWindow.restype = wt.HWND
    u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u32.GetWindowThreadProcessId.restype = wt.DWORD
    u32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    u32.BringWindowToTop.argtypes = [wt.HWND]
    u32.SetForegroundWindow.argtypes = [wt.HWND]
    k32.GetCurrentThreadId.restype = wt.DWORD


def hwnd_value(h):
    return int(h) if h else 0


def zorder():
    order = []
    u32.EnumWindows(ENUMPROC(lambda h, _: order.append(hwnd_value(h)) or True), 0)
    return order


def z_index(hwnd):
    order = zorder()
    return order.index(hwnd) if hwnd in order else None


def window_pid(hwnd):
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def title_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(wt.HWND(hwnd), buf, 256)
    return buf.value


def bring_to_top(hwnd):
    """Activates the window like a click on it does (a z-order call alone is refused for a background window): AttachThreadInput to the foreground thread, SetForegroundWindow. Never an ALT tap."""
    fg = u32.GetForegroundWindow()
    cur = k32.GetCurrentThreadId()
    fg_thread = u32.GetWindowThreadProcessId(fg, None) if fg else 0
    target_thread = u32.GetWindowThreadProcessId(wt.HWND(hwnd), None)
    others = [t for t in {fg_thread, target_thread} if t and t != cur]
    for t in others:
        u32.AttachThreadInput(cur, t, True)
    try:
        u32.BringWindowToTop(wt.HWND(hwnd))
        u32.SetForegroundWindow(wt.HWND(hwnd))
    finally:
        for t in others:
            u32.AttachThreadInput(cur, t, False)
    wait_until(lambda: hwnd_value(u32.GetForegroundWindow()) == hwnd, 3)
    if hwnd_value(u32.GetForegroundWindow()) != hwnd:
        raise AssertionError("IO1-HARNESS: could not activate the window %s (foreground %s)" % (hwnd, hwnd_value(u32.GetForegroundWindow())))


def facts(hwnd):
    return {"owner": hwnd_value(u32.GetWindow(wt.HWND(hwnd), GW_OWNER)), "ex": u32.GetWindowLongPtrW(wt.HWND(hwnd), GWL_EXSTYLE) & 0xFFFFFFFF, "style": u32.GetWindowLongPtrW(wt.HWND(hwnd), GWL_STYLE) & 0xFFFFFFFF}


def process_windows(pid):
    found = []

    def callback(h, _):
        if window_pid(hwnd_value(h)) == pid and u32.IsWindowVisible(h):
            found.append(hwnd_value(h))
        return True
    u32.EnumWindows(ENUMPROC(callback), 0)
    return found


def wait_until(condition, seconds, step=0.05):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(step)
    return condition()


class FakeBve(object):
    def __init__(self, mode):
        self.proc = subprocess.Popen(HELPER + [mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=0x08000000)
        line = self.proc.stdout.readline().decode("utf-8")
        if not line:
            raise AssertionError("IO1-HARNESS: the fake-BVE helper printed nothing")
        info = json.loads(line)
        self.pid, self.main, self.settings = info["pid"], info["main"], info["settings"]

    def command(self, text):
        self.proc.stdin.write((text + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def new_settings(self):
        self.command("new-settings")
        self.settings = json.loads(self.proc.stdout.readline().decode("utf-8"))["settings"]
        return self.settings

    def stop(self):
        try:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait(10)
        except Exception:
            pass


class Product(object):
    def __init__(self, env_extra, profile):
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)
        for key in ("LOCALAPPDATA", "USERPROFILE", "HOME"):
            env[key] = profile
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for key in (ENV_PID, ENV_OWNER, ENV_MAIN):
            env.pop(key, None)
        env.update(env_extra)
        self.profile = profile
        self.proc = subprocess.Popen(ENTRY, cwd=ROOT, env=env, creationflags=0x08000000, stderr=subprocess.PIPE)

    def window(self, seconds=25):
        def find():
            for h in process_windows(self.proc.pid):
                if title_of(h) == TITLE:
                    return h
            return 0
        return wait_until(find, seconds)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)

    def saved_json(self):
        return os.path.exists(os.path.join(self.profile, "Coruge-to", "TS Scoring", "initial-defaults.json"))


@unittest.skipUnless(WINDOWS, "needs Windows")
class OwnershipNative(unittest.TestCase):
    def setUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="io1-profile-")
        self.addCleanup(self.profile.cleanup)
        self.stoppers = []
        self.addCleanup(lambda: [s.stop() for s in self.stoppers])

    def bve(self):
        b = FakeBve("bve")
        self.stoppers.append(b)
        return b

    def other_app(self):
        a = FakeBve("app")
        self.stoppers.append(a)
        return a

    def product(self, bve, owner=None, main=None, pid=None, extra=None):
        env = {ENV_PID: str(bve.pid if pid is None else pid), ENV_OWNER: str(bve.settings if owner is None else owner), ENV_MAIN: str(bve.main if main is None else main)}
        if extra:
            env.update(extra)
        p = Product(env, self.profile.name)
        self.stoppers.append(p)
        return p

    # R1 ------------------------------------------------------------------------------------------------------------------------------------
    def test_R1_first_properties_opens_one_window_owned_by_the_bve_settings_dialog(self):
        b = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        self.assertEqual(len([h for h in process_windows(p.proc.pid) if title_of(h) == TITLE]), 1, "IO1-RED: more than one window")
        self.assertEqual(facts(w)["owner"], b.settings, "IO1-RED: the window is not owned by the BVE settings dialog (owner=%s, settings=%s)" % (facts(w)["owner"], b.settings))

    # R2 ------------------------------------------------------------------------------------------------------------------------------------
    def test_R2_clicking_the_bve_settings_dialog_does_not_send_the_window_behind_it(self):
        b = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        bring_to_top(b.settings)                                                      # what a click on the settings dialog does to the z-order
        time.sleep(0.4)
        self.assertLess(z_index(w), z_index(b.settings), "IO1-RED: the initial-defaults window went BEHIND the BVE settings dialog")

    # R3 + R13 ------------------------------------------------------------------------------------------------------------------------------
    def test_R3_another_application_can_be_brought_in_front_and_the_window_is_not_topmost(self):
        b = self.bve()
        a = self.other_app()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        bring_to_top(a.main)
        time.sleep(0.4)
        self.assertLess(z_index(a.main), z_index(w), "IO1-GUARD: another application can not be brought in front of the window")
        f = facts(w)
        self.assertFalse(f["ex"] & WS_EX_TOPMOST, "IO1-GUARD: the window is global top-most")
        self.assertTrue(f["owner"] == b.settings, "IO1-RED: the window is not owned (an unowned window is not part of the contract)")

    def test_R13_taskbar_and_alt_tab_contract(self):
        """Owner ruling 2026-11-12 (taskbar contract): the window is an owned window with the STANDARD Win32/Qt behaviour: no WS_EX_APPWINDOW (R13-A), so no own taskbar button (R13-B) and no Alt+Tab entry (R13-C);
        no WS_EX_TOOLWINDOW added to hide it, not global top-most (R13-E), the standard title bar stays, and the owner is the BVE settings dialog (R13-D)."""
        b = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        f = facts(w)
        self.assertEqual(f["owner"], b.settings, "IO1-RED: R13-D not owned by the BVE settings dialog")
        self.assertFalse(f["ex"] & WS_EX_APPWINDOW, "IO1-RED: R13-A the owned window carries WS_EX_APPWINDOW (ex=0x%X): it gets its own taskbar button 'Python 3.14 (64-bit)' and an Alt+Tab entry" % f["ex"])
        self.assertFalse(f["ex"] & WS_EX_TOOLWINDOW, "IO1-RED: R13-A WS_EX_TOOLWINDOW must not be added to hide the window (the owned-window behaviour is the reference) (ex=0x%X)" % f["ex"])
        self.assertFalse(shell_lists_in_taskbar(f), "IO1-RED: R13-B the shell would show an independent taskbar button for this window")
        self.assertFalse(shell_lists_in_alt_tab(f), "IO1-RED: R13-C the shell would list this window in Alt+Tab as an independent entry")
        self.assertFalse(f["ex"] & WS_EX_TOPMOST, "IO1-RED: R13-E the window is global top-most")
        self.assertEqual(f["style"] & WS_CAPTION, WS_CAPTION, "IO1-GUARD: the standard Windows title bar is gone")
        self.assertTrue(f["style"] & WS_SYSMENU, "IO1-GUARD: the standard close button / system menu is gone")

    def test_R13_minimized_window_stays_one_valid_window_and_restores_as_the_same_window(self):
        """R13-H/I at the window level: a minimized owned window has no taskbar button (accepted), but the process stays ONE, the HWND stays valid and owned, and SW_RESTORE (what the Caller does on the next Properties press) brings back THE SAME window."""
        b = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        owner_before = facts(w)["owner"]
        u32.ShowWindow(wt.HWND(w), SW_MINIMIZE)
        self.assertTrue(wait_until(lambda: u32.IsIconic(wt.HWND(w)), 3), "IO1-GUARD: the harness could not minimize the window")
        self.assertIsNone(p.proc.poll(), "IO1-RED: R13-H the process ended when the window was minimized")
        self.assertTrue(u32.IsWindow(wt.HWND(w)), "IO1-RED: R13-H the HWND became invalid after minimizing")
        self.assertEqual(facts(w)["owner"], owner_before, "IO1-RED: R13-H the owner changed by minimizing")
        self.assertFalse(facts(w)["ex"] & WS_EX_APPWINDOW, "IO1-RED: R13-A a minimized owned window must not gain WS_EX_APPWINDOW")
        u32.ShowWindow(wt.HWND(w), SW_RESTORE)
        self.assertTrue(wait_until(lambda: not u32.IsIconic(wt.HWND(w)) and u32.IsWindowVisible(wt.HWND(w)), 3), "IO1-RED: R13-H SW_RESTORE did not restore the window")
        self.assertEqual([h for h in process_windows(p.proc.pid) if title_of(h) == TITLE], [w], "IO1-RED: R13-I the restored window is not the same single window")
        self.assertEqual(facts(w)["owner"], owner_before, "IO1-RED: R13-H the owner changed by restoring")

    # R5 ------------------------------------------------------------------------------------------------------------------------------------
    def test_R5_a_second_start_while_the_window_lives_opens_nothing_and_exits_at_once(self):
        b = self.bve()
        p = self.product(b)
        self.assertTrue(p.window(), "IO1-HARNESS: the window did not appear")
        q = self.product(b)
        self.assertTrue(wait_until(lambda: q.proc.poll() is not None, 20), "IO1-GUARD: the second start did not end")
        code = q.proc.returncode
        self.assertEqual(code, 0, "IO1-GUARD: the second start must exit 0")
        self.assertEqual(len([h for h in process_windows(q.proc.pid)]), 0, "IO1-GUARD: the second start opened a window")
        self.assertEqual(len([h for h in process_windows(p.proc.pid) if title_of(h) == TITLE]), 1)

    # R8 ------------------------------------------------------------------------------------------------------------------------------------
    def test_R8_an_owner_of_another_bve_pid_is_never_used(self):
        b = self.bve()
        other = self.bve()
        p = self.product(b, owner=other.settings, main=other.main)                      # the HWNDs belong to ANOTHER process than the announced BVE pid
        ended = wait_until(lambda: p.proc.poll() is not None, 15)
        wins = [h for h in process_windows(p.proc.pid) if title_of(h) == TITLE]
        self.assertEqual(wins, [], "IO1-RED: a window was started with an owner of another BVE pid")
        self.assertTrue(ended, "IO1-RED: the product did not end")
        code = p.proc.returncode
        self.assertEqual(code, 3, "IO1-RED: an unusable owner must end the start with exit code 3 (got %r)" % code)

    # R9 ------------------------------------------------------------------------------------------------------------------------------------
    def test_R9_garbage_or_invalid_owner_values_do_not_crash_and_do_not_start_an_unowned_window(self):
        b = self.bve()
        cases = [{ENV_PID: "abc", ENV_OWNER: "1", ENV_MAIN: "2"}, {ENV_PID: str(b.pid), ENV_OWNER: "not-a-number", ENV_MAIN: "0"}, {ENV_PID: str(b.pid), ENV_OWNER: "0", ENV_MAIN: "0"},
                 {ENV_PID: str(b.pid), ENV_OWNER: "999999999", ENV_MAIN: "999999998"}, {ENV_PID: "-5", ENV_OWNER: str(b.settings), ENV_MAIN: str(b.main)}]
        for env in cases:
            p = Product(env, self.profile.name)
            self.stoppers.append(p)
            ended = wait_until(lambda: p.proc.poll() is not None, 15)
            self.assertEqual([h for h in process_windows(p.proc.pid) if title_of(h) == TITLE], [], "IO1-RED: an unowned window was started for %r" % env)
            self.assertTrue(ended, "IO1-RED: the product did not end for %r" % env)
            code = p.proc.returncode
            self.assertEqual(code, 3, "IO1-RED: unusable owner values %r must end with exit code 3 (got %r)" % (env, code))
        p = self.product(b, owner=999999999)                                            # an invalid owner HWND but a valid main HWND of the same BVE: the main window is used
        w = p.window()
        self.assertTrue(w, "IO1-RED: a valid main HWND must be the fallback of an invalid owner HWND")
        self.assertEqual(facts(w)["owner"], b.main, "IO1-RED: the fallback owner is not the BVE main window")

    # R10 -----------------------------------------------------------------------------------------------------------------------------------
    def test_R10_when_the_settings_dialog_is_destroyed_the_owner_moves_to_the_main_window_of_the_same_bve(self):
        b = self.bve()
        other = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        self.assertEqual(facts(w)["owner"], b.settings, "IO1-RED: not owned by the settings dialog at the start")
        b.command("destroy-settings")
        ok = wait_until(lambda: facts(w)["owner"] == b.main, 4)
        self.assertTrue(ok, "IO1-RED: the owner did not move to the BVE main window (owner=%s main=%s)" % (facts(w)["owner"], b.main))
        self.assertNotEqual(facts(w)["owner"], other.main, "IO1-RED: moved to the main window of ANOTHER bve")
        self.assertFalse(facts(w)["ex"] & WS_EX_APPWINDOW, "IO1-RED: R13-A the owner change must not give the window its own taskbar button")
        self.assertFalse(shell_lists_in_taskbar(facts(w)), "IO1-RED: R13-B after the owner change the shell would list the window in the taskbar")
        self.assertIsNone(p.proc.poll(), "IO1-RED: the window must survive the settings dialog (the process ended)")

    # R11 -----------------------------------------------------------------------------------------------------------------------------------
    def test_R11_when_bve_ends_the_window_and_the_process_end_without_saving(self):
        b = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        t0 = time.time()
        b.stop()
        code = wait_until(lambda: p.proc.poll() is not None, 6)
        took = time.time() - t0
        self.assertTrue(code, "IO1-RED: the process is still alive %.1f s after BVE ended (an orphaned window)" % took)
        self.assertEqual(p.proc.returncode, 0, "IO1-RED: the exit code after the BVE exit must be 0")
        self.assertLessEqual(took, 3.0, "IO1-RED: the window needed %.1f s to end after BVE ended (limit 2 s plus the poll)" % took)
        self.assertFalse(p.saved_json(), "IO1-RED: closing because BVE ended must not save")

    # R12 (x / Esc never save here; Alt+F4 is covered in-process by test_initial_defaults_windows_ui, because a posted Alt+F4 does not reach a window without WS_SYSMENU the way the keyboard does) ------------------------------------------------------------------------------------------------------
    def _close_by(self, how):
        b = self.bve()
        p = self.product(b)
        w = p.window()
        self.assertTrue(w, "IO1-HARNESS: the window did not appear")
        if how == "x":
            u32.PostMessageW(wt.HWND(w), 0x0010, 0, 0)                                    # WM_CLOSE
        elif how == "altf4":
            u32.SendMessageW(wt.HWND(w), 0x0104, 0x73, 1 << 29)                           # WM_SYSKEYDOWN VK_F4 with the ALT context bit (what Alt+F4 does)
        else:
            u32.SendMessageW(wt.HWND(w), 0x0100, 0x1B, 0)                                 # WM_KEYDOWN VK_ESCAPE
            u32.SendMessageW(wt.HWND(w), 0x0101, 0x1B, 0)
        code = wait_until(lambda: p.proc.poll() is not None, 10)
        self.assertTrue(code, "IO1-GUARD: the window did not close by %s" % how)
        self.assertEqual(p.proc.returncode, 0)
        self.assertFalse(p.saved_json(), "IO1-GUARD: %s saved" % how)

    def test_R12_x_saves_nothing(self):
        self._close_by("x")

    def test_R12_esc_saves_nothing(self):
        self._close_by("esc")


    # R12 (OK still saves, in an owned window; in-process, a real native Qt dialog, a real fake-BVE owner) ----------------------------------------------------
    @unittest.skipIf(os.environ.get("QT_QPA_PLATFORM") == "offscreen", "needs the native platform")
    def test_R12_ok_still_saves_in_an_owned_window(self):
        import initial_defaults_ui as ui
        from PyQt6.QtWidgets import QApplication, QWidget
        b = self.bve()
        path = os.path.join(self.profile.name, "ok-case", "initial-defaults.json")
        seen = {}

        class FreeInstance(object):
            def acquire(self):
                return True

            def release(self):
                pass

        def exec_fn(dialog):
            dialog.show()                                                             # exec() would show it; the owner is applied by Qt when the window is shown
            QApplication.processEvents()
            seen["owner"] = facts(int(dialog.winId()))["owner"]
            dialog.findChild(QWidget, "a_rank").setValue(77)
            dialog.findChild(QWidget, "ok").click()

        env = {ENV_PID: str(b.pid), ENV_OWNER: str(b.settings), ENV_MAIN: str(b.main)}
        code = ui.run(["main.py", "--initial-defaults"], defaults_path=path, instance=FreeInstance(), exec_fn=exec_fn, environ=env)
        self.assertEqual(code, 0)
        self.assertEqual(seen.get("owner"), b.settings, "IO1-RED: the in-process dialog was not owned by the settings dialog")
        self.assertTrue(os.path.exists(path), "IO1-GUARD: OK did not save in an owned window")
        self.assertEqual(json.load(open(path, encoding="utf-8"))["a_rank_percent"], 77)
        self.assertEqual([n for n in os.listdir(os.path.dirname(path)) if n != "initial-defaults.json"], [], "IO1-GUARD: a temporary file is left")
    # compatibility -------------------------------------------------------------------------------------------------------------------------
    def test_without_any_owner_information_the_plain_start_still_works_and_is_unowned(self):
        p = Product({}, self.profile.name)
        self.stoppers.append(p)
        w = p.window()
        self.assertTrue(w, "IO1-GUARD: the development start without owner information must still show the window")
        self.assertEqual(facts(w)["owner"], 0, "IO1-GUARD: no owner information means no owner")
        self.assertFalse(facts(w)["ex"] & WS_EX_TOPMOST)


@unittest.skipUnless(WINDOWS, "needs Windows")
class OwnerLogic(unittest.TestCase):
    """The pure logic of the owner information (no window): parsing, validation, choice."""

    def module(self):
        import initial_defaults_ui as ui
        return ui

    def test_the_owner_contract_names_exist(self):
        ui = self.module()
        for name in ("ENV_BVE_PID", "ENV_OWNER_HWND", "ENV_MAIN_HWND", "read_owner_request", "choose_owner", "OwnerBinding", "EXIT_OWNER_INVALID"):
            self.assertTrue(hasattr(ui, name), "IO1-RED: initial_defaults_ui has no %s" % name)
        self.assertEqual(ui.ENV_BVE_PID, ENV_PID)
        self.assertEqual(ui.ENV_OWNER_HWND, ENV_OWNER)
        self.assertEqual(ui.ENV_MAIN_HWND, ENV_MAIN)

    def test_parse_accepts_decimal_and_hex_only(self):
        ui = self.module()
        self.assertTrue(hasattr(ui, "read_owner_request"), "IO1-RED: no read_owner_request")
        ok, err = ui.read_owner_request({ENV_PID: "123", ENV_OWNER: "456", ENV_MAIN: "0x2A"})
        self.assertIsNone(err)
        self.assertEqual((ok.bve_pid, ok.owner_hwnd, ok.main_hwnd), (123, 456, 42))
        self.assertEqual(ui.read_owner_request({}), (None, None), "no information at all is the plain start")
        for bad in ({ENV_PID: "12 3", ENV_OWNER: "1", ENV_MAIN: "1"}, {ENV_PID: "1e3", ENV_OWNER: "1", ENV_MAIN: "1"}, {ENV_PID: "0", ENV_OWNER: "1", ENV_MAIN: "1"}, {ENV_PID: "5", ENV_OWNER: "-1", ENV_MAIN: "1"},
                    {ENV_PID: "5", ENV_OWNER: "0", ENV_MAIN: "0"}, {ENV_PID: "5"}, {ENV_PID: "", ENV_OWNER: "", ENV_MAIN: ""}):
            req, err = ui.read_owner_request(bad)
            self.assertIsNone(req, "IO1-RED: %r must be refused" % (bad,))
            self.assertTrue(err, "IO1-RED: %r has no error text" % (bad,))

    def test_choose_owner_uses_the_owner_then_the_main_window_and_checks_the_pid(self):
        ui = self.module()
        self.assertTrue(hasattr(ui, "choose_owner"), "IO1-RED: no choose_owner")

        class Api(object):
            def __init__(self, windows, alive=True):
                self.windows, self.alive = windows, alive

            def process_alive(self, pid):
                return self.alive

            def is_window(self, h):
                return h in self.windows

            def window_pid(self, h):
                return self.windows.get(h, 0)

        req = ui.OwnerRequest(100, 11, 12) if hasattr(ui, "OwnerRequest") else None
        self.assertIsNotNone(req, "IO1-RED: no OwnerRequest")
        self.assertEqual(ui.choose_owner(req, Api({11: 100, 12: 100}))[0], 11)
        self.assertEqual(ui.choose_owner(req, Api({12: 100}))[0], 12, "the main window must replace a vanished owner")
        self.assertIsNone(ui.choose_owner(req, Api({11: 999, 12: 999}))[0], "a window of another pid must never be used")
        self.assertIsNone(ui.choose_owner(req, Api({11: 100}, alive=False))[0], "IO1-RED: a BVE that is gone has no owner")
        self.assertEqual(ui.choose_owner(req, Api({11: 999, 12: 100}))[0], 12, "the owner of another pid is skipped, the main window of the right pid is used")

    def test_binding_tick_follows_the_owner_rules(self):
        ui = self.module()
        self.assertTrue(hasattr(ui, "OwnerBinding"), "IO1-RED: no OwnerBinding")

        class Api(object):
            def __init__(self):
                self.windows = {11: 100, 12: 100, 21: 200}
                self.alive = {100: True, 200: True}
                self.owner_of = {5: 11}
                self.set_calls = []

            def process_alive(self, pid):
                return self.alive.get(pid, False)

            def is_window(self, h):
                return h in self.windows

            def window_pid(self, h):
                return self.windows.get(h, 0)

            def get_owner(self, h):
                return self.owner_of.get(h, 0)

            def set_owner(self, h, o):
                self.set_calls.append((h, o))
                self.owner_of[h] = o
                return True

        api = Api()
        binding = ui.OwnerBinding(ui.OwnerRequest(100, 11, 12), api, 11)
        binding.dialog_hwnd = 5
        self.assertEqual(binding.tick(), "alive")
        self.assertEqual(api.set_calls, [], "nothing changes while the owner is fine")
        del api.windows[11]
        api.owner_of[5] = 0                                                       # what Windows does when the owner is destroyed
        self.assertEqual(binding.tick(), "alive")
        self.assertEqual(api.set_calls, [(5, 12)], "IO1-RED: the owner must move to the main window of the same bve")
        del api.windows[12]
        api.owner_of[5] = 0
        self.assertEqual(binding.tick(), "alive")
        self.assertNotIn((5, 21), api.set_calls, "IO1-RED: a window of ANOTHER bve was used as the owner")
        api.alive[100] = False
        self.assertEqual(binding.tick(), "bve-exited", "IO1-RED: the end of the bve must be reported")
    def test_the_python_side_never_uses_a_global_topmost_hint_and_polls_gently(self):
        src = open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8").read()
        self.assertNotIn("WindowStaysOnTopHint", src, "IO1-RED: a global top-most hint would keep the window above Chrome, Copilot and the task manager")
        self.assertNotIn("HWND_TOPMOST", src)
        ui = self.module()
        self.assertTrue(hasattr(ui, "POLL_INTERVAL_MS"), "IO1-RED: no poll interval")
        self.assertTrue(250 <= ui.POLL_INTERVAL_MS <= 1000, "IO1-RED: the owner poll interval %r is outside 250..1000 ms" % ui.POLL_INTERVAL_MS)
        for bad in ("os._exit", "TerminateProcess", "time.sleep(", "WaitForSingleObject(handle, 0xFFFFFFFF"):
            self.assertNotIn(bad, src, "IO1-RED: the Python side must not contain %r (no blocking wait, no forced exit)" % bad)

    def test_R13A_the_source_adds_no_extended_window_style_at_all(self):
        """R13-A (source level): no WS_EX_APPWINDOW, no WS_EX_TOOLWINDOW, no WS_EX_TOPMOST, no set/get of the extended style: the owned-window behaviour of Win32 / Qt is the reference, nothing is patched in to show or hide the window."""
        src = open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8").read()
        found = [bad for bad in ("WS_EX_APPWINDOW", "WS_EX_TOOLWINDOW", "WS_EX_TOPMOST", "set_exstyle", "get_exstyle", "GWL_EXSTYLE", "0x00040000", "WindowStaysOnTopHint", "HWND_TOPMOST", "Qt.WindowType.Tool", "WindowType.Tool") if bad in src]
        self.assertEqual(found, [], "IO1-RED: R13-A initial_defaults_ui.py contains %r (owned-window standard behaviour is the reference; no taskbar patching)" % found)

    def test_main_py_keeps_the_exact_flag_contract(self):
        ui = self.module()
        class _Held(object):
            def acquire(self):
                return False                                    # a mutant that accepted the extra argument would stop here (no window, no blocking event loop)

            def release(self):
                pass

        self.assertEqual(ui.run(["main.py", "--initial-defaults", "extra"], instance=_Held(), exec_fn=lambda d: self.fail("IO1-GUARD: the window must not be shown")), 2, "IO1-GUARD: extra arguments must stay refused (the owner travels in the environment)")

if __name__ == "__main__":
    unittest.main()
