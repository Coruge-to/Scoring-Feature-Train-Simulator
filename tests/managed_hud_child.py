"""Phase E4 test helper: runs main.run_managed() with a fake Overlay (no window, no UDP port, no keyboard hook, no BVE) but with the REAL
managed HUD controller, the REAL state-block reader (real Windows mapping) and the REAL Qt timer / event loop / Stop watcher. The window side is
faked: the "BVE window" always exists, and every Overlay call is reported as one line on stderr, so a test can follow the HUD from outside.

Usage: python tests\\managed_hud_child.py --managed --owner test --bve-pid N --instance HEX
Environment: TSS_E4_CHILD = ok (default) | no-window (the BVE window is never found) | boom-update (the HUD update raises every tick)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402

import main  # noqa: E402
import managed_hud  # noqa: E402
import managed_state  # noqa: E402

MODE = os.environ.get("TSS_E4_CHILD", "ok")
CREATED = []


class _FakeOverlay(object):
    """Counts calls like the real Overlay would receive them. update() is the repaint; show/hide are the window operations."""

    def __init__(self):
        CREATED.append(self)
        self.udp_bind_ok = True
        self.timer = QTimer()
        self.visible = False
        self.shows = 0
        self.hides = 0
        self.updates = 0
        self.closed = False
        self.bve_time_ms = 0

    def winId(self):
        return 4242

    def show(self):
        self.visible = True
        self.shows += 1
        sys.stderr.write("[OVERLAY] show n=%d overlays=%d\n" % (self.shows, len(CREATED)))
        sys.stderr.flush()

    def hide(self):
        self.visible = False
        self.hides += 1
        sys.stderr.write("[OVERLAY] hide n=%d overlays=%d\n" % (self.hides, len(CREATED)))
        sys.stderr.flush()

    def isVisible(self):
        return self.visible

    def setGeometry(self, x, y, w, h):
        pass

    def geometry(self):
        return None

    def update(self):
        self.updates += 1

    def close(self):
        self.closed = True


class _FakeWindowApi(object):
    def find_bve_window(self, bve_pid):
        return None if MODE == "no-window" else 777

    def is_window(self, hwnd):
        return True

    def is_iconic(self, hwnd):
        return False

    def client_rect_on_screen(self, hwnd):
        return (0, 0, 800, 600)

    def owner_of(self, overlay_hwnd):
        return self.owner

    owner = 0

    def set_owner(self, overlay_hwnd, bve_hwnd):
        self.owner = bve_hwnd

    def z_above(self, hwnd):
        return 4242                      # the Overlay already is directly above the (fake) BVE window: nothing to order

    def is_topmost(self, hwnd):
        return False

    def place_below(self, overlay_hwnd, above_hwnd):
        pass


def _update_step(overlay):
    if MODE == "boom-update":
        raise ValueError("fake hud failure")
    overlay.update()


def _hud_factory(overlay, args, log):
    reader = managed_state.StateReader(args, managed_state.Win32StateSource(), log)
    return managed_hud.ManagedHudController(overlay, reader, _FakeWindowApi(), args, log, update_step=_update_step, timer=overlay.timer)


if __name__ == "__main__":
    sys.exit(main.run_managed(sys.argv, overlay_factory=_FakeOverlay, hud_factory=_hud_factory))
