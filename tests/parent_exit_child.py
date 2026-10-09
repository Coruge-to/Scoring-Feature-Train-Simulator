"""Parent-exit fix test helper: runs main.run_managed() with a fake Overlay that owns a REAL UDP socket and a REAL (stand-in HUD) Qt window, the REAL
managed HUD controller and the REAL state-block reader / Stop watcher / owner-process watcher. No BVE, no 54321 unless asked, no keyboard hook.

Usage: python tests\\parent_exit_child.py --managed --owner caller --bve-pid N --instance HEX
Environment: TSS_P1_PORT = UDP port the fake Overlay binds (default: a free port picked by the OS, reported on stderr as [P1] udp-port=N)

Reports on stderr (one line each): [P1] udp-bound port=N | [P1] window-open | [P1] window-closed | [P1] udp-closed |
[P1] windows-remaining=N (after run_managed returned) | [P1] done code=N
"""
import ctypes
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtNetwork import QHostAddress, QUdpSocket  # noqa: E402
from PyQt6.QtWidgets import QWidget  # noqa: E402

import main  # noqa: E402
import managed_hud  # noqa: E402
import managed_state  # noqa: E402

WINDOW_TITLE = "TSSP1-HUD-STANDIN-%d" % os.getpid()


def say(text):
    try:
        sys.stderr.write("[P1] " + text + "\n")
        sys.stderr.flush()
    except Exception:
        pass  # the pipe to a vanished owner is broken: that must never matter


def count_windows(title):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return len(found)


class _FakeOverlay(object):
    """Same surface managed_hud / main._release_overlay use (see tests\\managed_hud_child.py), plus a real socket and a real window."""

    def __init__(self):
        self.timer = QTimer()
        self.udp_socket = QUdpSocket()
        wanted = int(os.environ.get("TSS_P1_PORT", "0"))
        self.udp_bind_ok = self.udp_socket.bind(QHostAddress.SpecialAddress.LocalHost, wanted)
        if self.udp_bind_ok:
            say("udp-bound port=%d" % self.udp_socket.localPort())
        self._window = QWidget()
        self._window.setWindowTitle(WINDOW_TITLE)
        self.visible = False

    def winId(self):
        return int(self._window.winId())

    def show(self):
        self.visible = True
        self._window.show()
        say("window-open")

    def hide(self):
        self.visible = False
        self._window.hide()

    def isVisible(self):
        return self.visible

    def setGeometry(self, x, y, w, h):
        pass

    def geometry(self):
        return None

    def update(self):
        pass

    def close(self):
        self._window.close()
        self._window.deleteLater()
        say("window-closed")


class _WindowApi(object):
    owner = 0

    def find_bve_window(self, bve_pid):
        return None  # the HUD never links: this helper is about the end of the process, not about the HUD's placement

    def is_window(self, hwnd):
        return True

    def is_iconic(self, hwnd):
        return False

    def client_rect_on_screen(self, hwnd):
        return (0, 0, 800, 600)

    def owner_of(self, overlay_hwnd):
        return self.owner

    def set_owner(self, overlay_hwnd, bve_hwnd):
        self.owner = bve_hwnd

    def z_above(self, hwnd):
        return 0

    def is_topmost(self, hwnd):
        return False

    def place_below(self, overlay_hwnd, above_hwnd):
        pass


def _factory():
    overlay = _FakeOverlay()
    if overlay.udp_bind_ok:
        # the stand-in HUD window opens shortly after AppReady, so the end of the process has a visible window to clean up
        QTimer.singleShot(150, overlay.show)
        real_close = overlay.udp_socket.close

        def traced_close():
            real_close()
            say("udp-closed")
        overlay.udp_socket.close = traced_close
    return overlay


def _hud_factory(overlay, args, log):
    reader = managed_state.StateReader(args, managed_state.Win32StateSource(), log)
    return managed_hud.ManagedHudController(overlay, reader, _WindowApi(), args, log, update_step=lambda o: o.update(), timer=overlay.timer)


if __name__ == "__main__":
    code = main.run_managed(sys.argv, overlay_factory=_factory, hud_factory=_hud_factory)
    say("windows-remaining=%d" % count_windows(WINDOW_TITLE))
    say("done code=%d" % code)
    sys.exit(code)
