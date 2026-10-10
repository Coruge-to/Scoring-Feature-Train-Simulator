"""Phase SI-A test rig: the REAL Overlay (offscreen Qt) with every outside effect replaced by a recorder.

Shared by the characterization (test_characterization_sia1.py), the behaviour-preserving split proof (test_split_sia2.py) and the managed integration
tests. Nothing here touches the real keyboard, a real window, the real clock, a real UDP port or the Desktop log: the Overlay is built against a stub
QUdpSocket (so UDP 54321 is never bound and a running TS Scoring is never disturbed), keyboard / win32gui / win32api / time / QApplication /
QTimer.singleShot / QFileDialog / write_desktop_log are fakes that record what the code does with them.

The rig works on ANY module object that looks like main.py (the current one, or the pre-SI-A one loaded from git), so that two implementations can be
driven with the same script and compared.
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VK_LBUTTON = 0x01
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
KEY_P = 0x50
KEY_F8 = 0x77


class FakeKeyboard(object):
    """keyboard: held keys, registered hooks (with the callback kept so a test can feed events), unhooks. A hook that is unhooked twice raises KeyError
    like the real library does for an unknown handle."""

    def __init__(self):
        self.pressed = set()
        self.hooks = []
        self.callbacks = {}
        self.unhooked = []
        self.counter = 0
        self.strict_unhook = False

    def is_pressed(self, key):
        return key in self.pressed

    def on_press_key(self, key, callback, suppress=False):
        self.counter += 1
        handle = ("key", key, bool(suppress), self.counter)
        self.hooks.append(handle)
        self.callbacks[handle] = callback
        return handle

    def hook(self, callback, suppress=False):
        self.counter += 1
        handle = ("hook", None, bool(suppress), self.counter)
        self.hooks.append(handle)
        self.callbacks[handle] = callback
        return handle

    def unhook(self, handle):
        if self.strict_unhook and (handle not in self.hooks or handle in self.unhooked):
            raise KeyError(handle)
        self.unhooked.append(handle)

    def active(self):
        return sorted(h[1] if h[0] == "key" else "<all>" for h in self.hooks if h not in self.unhooked)

    def active_handles(self):
        return [h for h in self.hooks if h not in self.unhooked]


class FakeGui(object):
    """win32gui: one valid BVE window, an optional "time and position" window, the foreground window, the style / placement of the BVE window and a
    record of every mutating call. Any call that is not modelled is recorded and answers None."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.valid = {hwnd}
        self.titles = {hwnd: "BVE Trainsim 6"}       # visible top-level windows (hwnd -> title), what EnumWindows reports
        self.foreground = hwnd
        self.diag = 0                                # the hwnd of the "time and position" window, 0 = none
        self.enabled = True
        self.calls = []
        self.style = 0x14CF0000
        self.placement = (0, 1, (0, 0), (0, 0), (100, 100, 1380, 820))
        self.iconic = False
        self.client = (0, 0, 1920, 1080)
        self.client_origin = (0, 0)
        self.cursor = (0, 0)
        self.raise_on_client_rect = False

    # -- windows -------------------------------------------------------------------------------------------------------------------------
    def IsWindow(self, h):
        return h in self.valid

    def IsWindowVisible(self, h):
        return h in self.titles

    def GetWindowText(self, h):
        return self.titles.get(h, "")

    def EnumWindows(self, callback, extra):
        for h in list(self.titles):
            callback(h, extra)

    def GetForegroundWindow(self):
        return self.foreground

    def IsIconic(self, h):
        return self.iconic

    def GetClientRect(self, h):
        if self.raise_on_client_rect:
            raise RuntimeError("window is gone")
        return self.client

    def ClientToScreen(self, h, pt):
        return self.client_origin

    def FindWindow(self, cls, title):
        return self.diag if title == "時刻と位置" else 0

    def IsWindowEnabled(self, h):
        return self.enabled

    def EnableWindow(self, h, flag):
        self.calls.append(("EnableWindow", h, bool(flag)))
        self.enabled = bool(flag)

    def GetCursorPos(self):
        return self.cursor

    def SetWindowLong(self, h, index, value):
        self.calls.append(("SetWindowLong", h, index, value))
        if index == -16:                              # GWL_STYLE
            self.style = value

    def GetWindowLong(self, h, index):
        return self.style

    def SendMessage(self, h, msg, w, l):
        self.calls.append(("SendMessage", h, msg, w, l))

    def SetWindowPos(self, *args):
        self.calls.append(("SetWindowPos",) + args)

    def GetWindowPlacement(self, h):
        return self.placement

    def SetWindowPlacement(self, h, placement):
        self.calls.append(("SetWindowPlacement", h, placement))

    def mutating(self):
        return [c for c in self.calls if c[0] in ("SetWindowLong", "SendMessage", "SetWindowPos", "SetWindowPlacement", "EnableWindow")]

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def recorder(*args):
            self.calls.append((name,) + args)
        return recorder


class FakeApi(object):
    """win32api: PostMessage record, the left mouse button, monitor information."""

    def __init__(self):
        self.posted = []
        self.left_down = False

    def PostMessage(self, h, msg, w, l):
        self.posted.append((h, msg, w, l))

    def GetAsyncKeyState(self, key):
        if key == VK_LBUTTON and self.left_down:
            return 0x8000
        return 0

    def MonitorFromWindow(self, h, flag):
        return 1

    def GetMonitorInfo(self, mon):
        return {"Monitor": (0, 0, 1920, 1080)}

    def keys_posted(self):
        """The virtual-key codes posted as key-down, in order."""
        return [p[2] for p in self.posted if p[1] == WM_KEYDOWN]


class FakeTime(object):
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s

    def monotonic(self):
        return self.now


class FakeApp(object):
    quits = 0

    @classmethod
    def quit(cls):
        cls.quits += 1

    @staticmethod
    def processEvents():
        return None


class FakeQTimer(object):
    """Replaces the QTimer name of main.py AFTER the Overlay has been built (the Overlay needs a real timer object): singleShot calls are queued and run
    by flush(), so a test decides when the OS 'finished maximizing'."""
    pending = []

    @classmethod
    def singleShot(cls, ms, fn):
        cls.pending.append((ms, fn))

    @classmethod
    def flush(cls):
        ran = 0
        while cls.pending:
            _ms, fn = cls.pending.pop(0)
            fn()
            ran += 1
        return ran


class StubSignal(object):
    def connect(self, slot):
        self.slot = slot


class StubUdp(object):
    """Stands in for QUdpSocket: UDP 54321 is never bound, datagrams to the BVE side (54322) are recorded."""

    def __init__(self, parent=None):
        self.readyRead = StubSignal()
        self.written = []
        self.incoming = []

    def bind(self, address, port):
        return True

    def hasPendingDatagrams(self):
        return bool(self.incoming)

    def pendingDatagramSize(self):
        return len(self.incoming[0])

    def readDatagram(self, size):
        return self.incoming.pop(0), None, None

    def writeDatagram(self, data, address, port):
        self.written.append((bytes(data), port))

    def close(self):
        return None


class FakeFileDialog(object):
    """QFileDialog.getSaveFileName replaced by a scripted answer (path or '' for cancel); the calls are recorded."""
    answer = ""
    calls = []
    on_call = None

    @classmethod
    def getSaveFileName(cls, parent, caption, directory, filter_):
        cls.calls.append((caption, directory, filter_))
        if cls.on_call is not None:
            cls.on_call()
        return cls.answer, ""


SEAMS = ("keyboard", "win32gui", "win32api", "time", "QApplication", "QTimer", "QUdpSocket", "QFileDialog", "write_desktop_log")


def station(name, loc=1000.0, timing=True, is_pass=False, terminal=False):
    return {"name": name, "is_timing": timing, "location": loc, "raw_arr": -1, "raw_dep": -1, "def_time": -1, "stop_time": 15000,
            "is_pass": is_pass, "is_terminal": terminal}


class Rig(object):
    """One Overlay of module `m` with all seams faked. Use as: rig = Rig(main); ...; rig.close()."""
    HWND = 4242

    def __init__(self, m, hwnd=HWND, stub_qtimer=False, capture_log=True):
        if getattr(m, "_sia_rig_installed", False):
            raise RuntimeError("a Rig of this module is already installed: two rigs would restore each other's fakes")
        m._sia_rig_installed = True
        self.m = m
        self.hwnd = hwnd
        self.saved_scoring = None
        self.kb, self.gui, self.api, self.clock = FakeKeyboard(), FakeGui(hwnd), FakeApi(), FakeTime()
        self.log = []
        FakeApp.quits = 0
        FakeQTimer.pending = []
        FakeFileDialog.calls = []
        FakeFileDialog.answer = ""
        FakeFileDialog.on_call = None
        if getattr(m, "QTimer", None) is FakeQTimer:                       # a previous rig of this module is still installed
            from PyQt6.QtCore import QTimer as real_timer
            m.QTimer = real_timer
        self.saved = {n: getattr(m, n) for n in SEAMS if hasattr(m, n)}
        m.keyboard, m.win32gui, m.win32api, m.time, m.QApplication, m.QUdpSocket = self.kb, self.gui, self.api, self.clock, FakeApp, StubUdp
        m.QFileDialog = FakeFileDialog
        import scoring_logic
        self.scoring_logic = scoring_logic
        self.saved_scoring = scoring_logic.write_desktop_log
        if capture_log:                                                    # (False: the REAL write_desktop_log runs, for the privacy tests)
            m.write_desktop_log = lambda msg, *a, **k: self.log.append(msg)
            scoring_logic.write_desktop_log = m.write_desktop_log
        self.o = m.Overlay()
        self.o.timer.stop()
        m.QTimer = FakeQTimer
        o = self.o
        o.bve_hwnd = hwnd
        o.is_linked = True
        o.was_bve_found = True
        o.menu_state = 0
        o.bve_actual_state = "RUNNING"

    def close(self):
        m = self.m
        m._sia_rig_installed = False
        for n, v in self.saved.items():
            setattr(m, n, v)
        if self.saved_scoring is not None:
            self.scoring_logic.write_desktop_log = self.saved_scoring
        try:
            self.o.udp_socket.close()
            self.o.close()
            self.o.deleteLater()
        except Exception:
            pass

    # -- driving ---------------------------------------------------------------------------------------------------------------------------
    def tick(self, n=1):
        for _ in range(n):
            self.o.update_logic()

    def release(self, key):
        self.kb.pressed.discard(key)

    def press(self, key):
        self.kb.pressed.add(key)

    def tap(self, key, ticks=2):
        """Press and release a key across ticks so that exactly one key-down edge is seen."""
        self.kb.pressed.discard(key)
        self.tick()
        self.kb.pressed.add(key)
        self.tick()
        self.kb.pressed.discard(key)
        if ticks > 2:
            self.tick(ticks - 2)

    def advance(self, seconds):
        self.clock.now += seconds


def load_main_from_git(commit, name="main_baseline"):
    """The main.py of an earlier commit as a module (its imports resolve to the CURRENT sibling modules). None when git or the commit is unavailable."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", "%s:main.py" % commit], capture_output=True, timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    module = types.ModuleType(name)
    module.__file__ = os.path.join(ROOT, name + ".py")
    exec(compile(out.stdout.decode("utf-8"), module.__file__, "exec"), module.__dict__)
    return module
