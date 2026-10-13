"""PID-D2 managed-mode test helper.

Runs main.run_managed() with a fake Overlay. The helper does not create a HUD,
keyboard hook, or BVE connection, but it owns a real loopback UDP socket so the
PID-D2 Telemetry Directory receives the same valid dynamic-port contract as the
product Overlay.

Usage:
    python tests/managed_smoke_child.py --managed --owner test --bve-pid N --instance HEX

Environment variable TSS_E2_FAKE:
    ok (default) | bind-fail | raise-in-init | raise-after-ready
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtNetwork import QHostAddress, QUdpSocket  # noqa: E402

import main  # noqa: E402


MODE = os.environ.get("TSS_E2_FAKE", "ok")


class _FakeTimer(object):
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeOverlay(object):
    def __init__(self, bind_ok):
        self.timer = _FakeTimer()
        self.closed = False
        self.udp_socket = QUdpSocket()
        if bind_ok:
            self.udp_bind_ok = self.udp_socket.bind(
                QHostAddress.SpecialAddress.LocalHost,
                0,
            )
        else:
            self.udp_bind_ok = False
        self.udp_port = (
            int(self.udp_socket.localPort())
            if self.udp_bind_ok
            else 0
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.udp_socket.close()


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
    sys.exit(
        main.run_managed(
            sys.argv,
            overlay_factory=_factory,
            hud_factory=lambda overlay, args, log: None,
        )
    )
