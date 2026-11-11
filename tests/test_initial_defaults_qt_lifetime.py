"""INITIAL-DEFAULTS Qt lifetime fix (Owner 2026-11-11, LA-0 root cause): `main.py --initial-defaults` must keep its QApplication alive for the whole run().

The defect: `initial_defaults_ui.run()` created the QApplication in a bare expression statement. CPython dropped the object at once, and the next QDialog() ended the process with a Qt fail-fast
(Qt6Core.dll, exception 0xC0000409). Every earlier test called run() inside a process that already had a QApplication, so the creation branch of the product was never executed.

These tests start the REAL product entry (`python main.py --initial-defaults`) in a fresh child process that has NO QApplication, and the Caller-like variants of it.
Messages: 'QC1-RED: ...' = the lifetime contract is broken (PRODUCT-RED on the unfixed code); 'QC1-GUARD: ...' = a contract that already holds and must stay GREEN; 'QC1-HARNESS: ...' = the harness itself is broken.
Nothing here touches the real user data: every child gets a temporary LOCALAPPDATA / USERPROFILE; the window is closed with WM_CLOSE (the x button), nothing is saved.
The tests need an interactive Windows desktop (like test_initial_defaults_windows_ui.py)."""
import ast
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENTRY = [sys.executable, os.path.join(ROOT, "main.py"), "--initial-defaults"]
WINDOWS = os.name == "nt"
FAIL_FAST = 0xC0000409

if WINDOWS:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    _u32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]
    _u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    _k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    _k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    _k32.CloseHandle.argtypes = [wt.HANDLE]

_STILL_ACTIVE = 259


class Child(object):
    """A running process known by its PID (the start method does not matter)."""

    def __init__(self, pid):
        self.pid = pid
        self.handle = _k32.OpenProcess(0x100000 | 0x1000 | 0x0001, False, pid)      # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE
        if not self.handle:
            raise AssertionError("QC1-HARNESS: OpenProcess(%d) failed" % pid)

    def exit_code(self):
        code = wt.DWORD()
        _k32.GetExitCodeProcess(self.handle, ctypes.byref(code))
        return None if code.value == _STILL_ACTIVE else code.value

    def wait(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            code = self.exit_code()
            if code is not None:
                return code
            time.sleep(0.05)
        return None

    def windows(self, visible_only):
        found = []

        def callback(hwnd, _):
            owner = wt.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == self.pid and (not visible_only or _u32.IsWindowVisible(hwnd)):
                found.append(hwnd)
            return True
        _u32.EnumWindows(_WNDENUMPROC(callback), 0)
        return found

    def close_windows(self):
        for hwnd in self.windows(False):
            _u32.PostMessageW(hwnd, 0x0010, 0, 0)                                     # WM_CLOSE = the x button

    def terminate(self):
        if self.exit_code() is None:
            _k32.TerminateProcess(self.handle, 99)
            _k32.WaitForSingleObject(self.handle, 5000)

    def release(self):
        _k32.CloseHandle(self.handle)


def wer_events_since(since):
    """Application Error (1000) / Windows Error Reporting (1001) events of python.exe written after `since` (a UTC datetime)."""
    stamp = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    query = "*[System[(EventID=1000 or EventID=1001) and TimeCreated[@SystemTime>='%s']]]" % stamp
    out = subprocess.run(["wevtutil", "qe", "Application", "/q:" + query, "/f:xml"], capture_output=True, timeout=60)
    text = out.stdout.decode("utf-8", errors="replace")
    return sum(1 for block in text.split("<Event ")[1:] if "python.exe" in block)


def alive_python_children():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"], capture_output=True, timeout=60)
    return [ln for ln in out.stdout.decode("utf-8", errors="replace").splitlines() if ln.strip().lower().startswith('"python.exe"')]


def _clean_env(profile, platform):
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    if platform:
        env["QT_QPA_PLATFORM"] = platform
    for key in ("LOCALAPPDATA", "USERPROFILE", "HOME"):                          # NOT APPDATA: Python's user site-packages (PyQt6, pywin32) live under it
        env[key] = profile
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


_POWERSHELL_START = (
    "$psi = New-Object System.Diagnostics.ProcessStartInfo; "
    "$psi.FileName = $env:QC1_PY; $psi.Arguments = '\"' + $env:QC1_SCRIPT + '\" --initial-defaults'; $psi.WorkingDirectory = $env:QC1_CWD; "
    "$psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; "
    "$p = [System.Diagnostics.Process]::Start($psi); [Console]::Out.WriteLine($p.Id)")


@unittest.skipUnless(WINDOWS, "needs Windows")
class RealProcessEntryTests(unittest.TestCase):
    """`python main.py --initial-defaults` as a real process with no QApplication in the parent: it must show the window, end by WM_CLOSE with exit code 0, and leave no crash report."""

    def setUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="qc1-profile-")
        self.addCleanup(self.profile.cleanup)
        self.started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=2)
        self.children = []
        self.addCleanup(self._cleanup_children)

    def _cleanup_children(self):
        for child in self.children:
            child.terminate()
            child.release()

    def _track(self, pid):
        child = Child(pid)
        self.children.append(child)
        return child

    def _assert_window_closes_with_exit_0(self, child, label):
        deadline = time.time() + 12.0
        shown_at = None
        t0 = time.time()
        while time.time() < deadline:
            code = child.exit_code()
            if code is not None:
                if code == 0 and shown_at is None:
                    self.fail("QC1-HARNESS: %s: the process ended with exit 0 before any window was shown (is another initial-defaults window open in this session? the named mutex then ends it at once)" % label)
                self.fail("QC1-RED: %s: the process ended by itself after %.1fs with exit code 0x%08X before the window could be closed%s" % (
                    label, time.time() - t0, code, " (Qt fail-fast: the QApplication was not kept alive)" if code == FAIL_FAST else ""))
            if child.windows(True):
                shown_at = time.time() - t0
                break
            time.sleep(0.05)
        self.assertIsNotNone(shown_at, "QC1-RED: %s: no window was shown within 12 s" % label)
        time.sleep(0.3)
        self.assertIsNone(child.exit_code(), "QC1-RED: %s: the process ended while its window was open" % label)
        child.close_windows()
        code = child.wait(10.0)
        self.assertIsNotNone(code, "QC1-RED: %s: the process did not end after WM_CLOSE" % label)
        self.assertEqual(code, 0, "QC1-RED: %s: exit code after WM_CLOSE is 0x%08X, not 0" % (label, code))

    def _assert_clean_afterwards(self, label):
        self.assertEqual(os.listdir(self.profile.name).count("initial-defaults.json"), 0, "QC1-RED: %s: closing with the x button created a saved file" % label)
        for _, _, files in os.walk(self.profile.name):
            self.assertEqual([f for f in files if f.endswith((".tmp", ".tsnew"))], [], "QC1-RED: %s: a temporary file was left behind" % label)
        time.sleep(0.2)
        self.assertEqual(wer_events_since(self.started), 0, "QC1-RED: %s: Application Error / WER events were written by python.exe during the test" % label)

    def _run_with_popen(self, label, **popen_kwargs):
        env = _clean_env(self.profile.name, None)
        proc = subprocess.Popen(ENTRY, cwd=ROOT, env=env, **popen_kwargs)
        self.addCleanup(lambda: [s.close() for s in (proc.stdin, proc.stdout, proc.stderr) if s is not None])
        child = self._track(proc.pid)
        self._assert_window_closes_with_exit_0(child, label)
        self._assert_clean_afterwards(label)

    def test_r2_native_entry_shows_the_window_and_ends_by_wm_close_with_exit_0(self):
        self._run_with_popen("native entry")

    def test_r4_with_the_standard_streams_connected(self):
        self._run_with_popen("standard streams connected (pipes)", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_r5_with_the_standard_streams_to_devnull(self):
        self._run_with_popen("standard streams = DEVNULL", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_r6_with_create_no_window(self):
        self._run_with_popen("CREATE_NO_WINDOW", creationflags=0x08000000)

    def test_r3_started_like_the_caller_with_a_dotnet_process_start_info(self):
        """The Caller starts the window with System.Diagnostics.ProcessStartInfo (UseShellExecute=false, CreateNoWindow=true, the working directory from launcher.json, no redirection)."""
        env = _clean_env(self.profile.name, None)
        env["QC1_PY"] = sys.executable
        env["QC1_SCRIPT"] = ENTRY[1]
        env["QC1_CWD"] = self.profile.name                                              # like launcher.json's workingDirectory: not the script folder
        # the start result goes to a FILE, not a pipe: the started child inherits the standard handles, and a pipe would stay open (and block the read) until the window is closed
        result_dir = tempfile.TemporaryDirectory(prefix="qc1-start-")
        self.addCleanup(result_dir.cleanup)
        result_path = os.path.join(result_dir.name, "pid.txt")
        with open(result_path, "wb") as result_file:
            out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_START], env=env, stdout=result_file, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=120)
        with open(result_path, "rb") as result_file:
            text = result_file.read().decode("utf-8", errors="replace").strip()
        self.assertTrue(text.isdigit(), "QC1-HARNESS: the PowerShell ProcessStartInfo start returned %r (exit %s)" % (text, out.returncode))
        child = self._track(int(text))
        self._assert_window_closes_with_exit_0(child, "Caller-like ProcessStartInfo")
        self._assert_clean_afterwards("Caller-like ProcessStartInfo")

    def test_r1_offscreen_entry_does_not_crash(self):
        """The offscreen platform has no window to close: the entry must stay alive (the event loop runs) for 3 s; the test then ends its own child."""
        env = _clean_env(self.profile.name, "offscreen")
        proc = subprocess.Popen(ENTRY, cwd=ROOT, env=env)
        child = self._track(proc.pid)
        t0 = time.time()
        while time.time() - t0 < 3.0:
            code = child.exit_code()
            if code is not None:
                self.fail("QC1-RED: offscreen entry: the process ended after %.1fs with exit code 0x%08X%s" % (
                    time.time() - t0, code, " (Qt fail-fast: the QApplication was not kept alive)" if code == FAIL_FAST else ""))
            time.sleep(0.05)
        # a crashed process stays alive for a few seconds while Windows collects the report, so 'alive' alone proves nothing: the Application Error event (written at the crash) is the evidence
        crashed = wer_events_since(self.started)
        child.terminate()
        self.assertEqual(crashed, 0, "QC1-RED: offscreen entry: python.exe wrote an Application Error event (the process crashed; Windows keeps it alive while it collects the report)")
        self._assert_clean_afterwards("offscreen entry")

    def test_three_consecutive_starts_each_show_the_window_and_end_with_exit_0(self):
        for number in (1, 2, 3):
            label = "start %d of 3" % number
            env = _clean_env(self.profile.name, None)
            proc = subprocess.Popen(ENTRY, cwd=ROOT, env=env)
            child = self._track(proc.pid)
            self._assert_window_closes_with_exit_0(child, label)
            self.assertEqual(proc.wait(timeout=10), 0, "QC1-RED: %s: exit code" % label)
            leftovers = [c for c in self.children if c.exit_code() is None]
            self.assertEqual(leftovers, [], "QC1-RED: %s: a process is still running after the window was closed" % label)
        self._assert_clean_afterwards("three consecutive starts")


_SNIPPET = r'''
import os, sys
sys.path.insert(0, @ROOT@)
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
import initial_defaults_ui as U
PRE = @PRE@
order = []
if PRE:
    pre_app = QApplication(["pre"])
print("INSTANCE_BEFORE_RUN=%s" % (QApplication.instance() is not None), flush=True)
class Free:
    def acquire(self):
        return True
    def release(self):
        pass
_orig = U.build_dialog
def build(defaults, save):
    print("INSTANCE_AT_BUILD=%s" % (QApplication.instance() is not None), flush=True)
    return _orig(defaults, save)
U.build_dialog = build
def exec_fn(dialog):
    app = QApplication.instance()
    print("INSTANCE_AT_EXEC=%s" % (app is not None), flush=True)
    if app is not None:
        app.destroyed.connect(lambda *_: order.append("app"))
    dialog.destroyed.connect(lambda *_: order.append("dialog"))
    def while_shown():
        print("INSTANCE_WHILE_SHOWN=%s VISIBLE=%s" % (QApplication.instance() is not None, dialog.isVisible()), flush=True)
        dialog.close()
    QTimer.singleShot(300, while_shown)
    dialog.exec()
code = U.run(["main.py", "--initial-defaults"], defaults_path=@PATH@, instance=Free(), exec_fn=exec_fn)
print("RUN_RETURNED=%s" % code, flush=True)
if PRE:
    print("PRE_APP_STILL_CURRENT=%s" % (QApplication.instance() is pre_app), flush=True)
    pre_app.processEvents()
    print("PRE_APP_USABLE=True", flush=True)
print("DESTROY_ORDER=%s" % ",".join(order), flush=True)
'''


@unittest.skipUnless(WINDOWS, "needs Windows")
class QApplicationLifetimeTests(unittest.TestCase):
    """run() in a FRESH process, observed from inside by test hooks (exec_fn / build_dialog wrapper); no mutex (a free instance) so that no other window can interfere."""

    def setUp(self):
        self.profile = tempfile.TemporaryDirectory(prefix="qc1-life-")
        self.addCleanup(self.profile.cleanup)

    def _run(self, platform, pre):
        path = os.path.join(self.profile.name, "initial-defaults.json")
        code = _SNIPPET.replace("@ROOT@", repr(ROOT)).replace("@PRE@", "True" if pre else "False").replace("@PATH@", repr(path))
        env = _clean_env(self.profile.name, platform)
        out = subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, timeout=120)
        text = out.stdout.decode("utf-8", errors="replace")
        markers = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        return out.returncode & 0xFFFFFFFF, markers, out.stderr.decode("utf-8", errors="replace")[-300:], path

    def test_the_created_application_lives_from_run_start_to_the_end_of_the_event_loop(self):
        for platform in ("offscreen", "windows"):
            with self.subTest(platform=platform):
                code, m, err, path = self._run(platform, pre=False)
                self.assertEqual(m.get("INSTANCE_BEFORE_RUN"), "False", "QC1-HARNESS: the fresh process did not report 'no QApplication before run()' (%s): exit 0x%08X %s" % (platform, code, err))
                self.assertEqual(m.get("INSTANCE_AT_BUILD"), "True", "QC1-RED: no QApplication when the dialog is built (%s): exit 0x%08X %s" % (platform, code, err))
                self.assertEqual(m.get("INSTANCE_AT_EXEC"), "True", "QC1-RED: no QApplication when the event loop starts (%s)" % platform)
                self.assertEqual(m.get("INSTANCE_WHILE_SHOWN"), "True VISIBLE=True", "QC1-RED: no QApplication while the dialog is shown (%s)" % platform)
                self.assertEqual(m.get("RUN_RETURNED"), "0", "QC1-RED: run() did not return 0 (%s)" % platform)
                self.assertEqual(code, 0, "QC1-RED: the process exit code is 0x%08X (%s)" % (code, platform))
                self.assertFalse(os.path.exists(path), "QC1-RED: closing the dialog created the saved file (%s)" % platform)

    def test_the_application_is_the_last_qt_object_to_go(self):
        for platform in ("offscreen", "windows"):
            with self.subTest(platform=platform):
                code, m, err, _ = self._run(platform, pre=False)
                self.assertEqual(code, 0, "QC1-RED: the process exit code is 0x%08X (%s)" % (code, platform))
                self.assertEqual(m.get("DESTROY_ORDER"), "dialog,app", "QC1-GUARD: the QApplication must be the last Qt object destroyed, after the dialog (%s): %r" % (platform, m.get("DESTROY_ORDER")))

    def test_an_existing_application_is_used_and_never_destroyed_by_run(self):
        for platform in ("offscreen", "windows"):
            with self.subTest(platform=platform):
                code, m, err, _ = self._run(platform, pre=True)
                self.assertEqual(code, 0, "QC1-GUARD: exit code 0x%08X with an existing QApplication (%s) %s" % (code, platform, err))
                self.assertEqual(m.get("INSTANCE_BEFORE_RUN"), "True")
                self.assertEqual(m.get("INSTANCE_AT_BUILD"), "True")
                self.assertEqual(m.get("INSTANCE_WHILE_SHOWN"), "True VISIBLE=True")
                self.assertEqual(m.get("PRE_APP_STILL_CURRENT"), "True", "QC1-GUARD: run() destroyed or replaced the existing QApplication (%s)" % platform)
                self.assertEqual(m.get("PRE_APP_USABLE"), "True")
                self.assertNotIn("app", (m.get("DESTROY_ORDER") or "").split(","), "QC1-GUARD: run() destroyed the QApplication it did not create (%s): %r" % (platform, m.get("DESTROY_ORDER")))


class QApplicationReferenceStaticTest(unittest.TestCase):
    """A secondary guard only (the evidence is the real-process tests above): the QApplication that run() creates must be assigned to a name, never dropped as an expression statement."""

    def test_run_keeps_the_created_qapplication_in_a_local_variable(self):
        with open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")

        def calls_qapplication(node):
            return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "QApplication" for c in ast.walk(node))
        dropped = [n.lineno for n in ast.walk(run) if isinstance(n, ast.Expr) and calls_qapplication(n.value)]
        kept = [n.lineno for n in ast.walk(run) if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and calls_qapplication(n.value)]
        self.assertEqual(dropped, [], "QC1-RED: run() drops the QApplication it creates (expression statement at line %s)" % dropped)
        self.assertTrue(kept, "QC1-RED: run() assigns the QApplication it creates to no variable")


if __name__ == "__main__":
    unittest.main()
