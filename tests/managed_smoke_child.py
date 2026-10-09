"""Phase E2 test helper: runs main.run_managed() with a FAKE Overlay (no HUD, no UDP port, no keyboard hook, no BVE) so that the real Qt glue
(queued shutdown bridge, excepthook, exit code) and the real named Win32 objects can be tested while a real TS Scoring may be running.

Usage: python tests\\managed_smoke_child.py --managed --owner test --bve-pid N --instance HEX
Mode (environment variable TSS_E2_FAKE): ok (default) | bind-fail | raise-in-init | raise-after-ready
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402

import main  # noqa: E402

MODE = os.environ.get("TSS_E2_FAKE", "ok")


class _FakeTimer(object):
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeOverlay(object):
    def __init__(self, bind_ok):
        self.udp_bind_ok = bind_ok
        self.timer = _FakeTimer()
        self.closed = False

    def close(self):
        self.closed = True


def _factory():
    if MODE == "raise-in-init":
        raise RuntimeError("fake init failure")
    overlay = _FakeOverlay(MODE != "bind-fail")
    if MODE == "raise-after-ready":
        def boom():
            raise ValueError("fake runtime failure")
        QTimer.singleShot(300, boom)
    return overlay


if __name__ == "__main__":
    sys.exit(main.run_managed(sys.argv, overlay_factory=_factory))
