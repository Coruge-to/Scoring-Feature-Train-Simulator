"""Phase E4 test helper: a stand-in for the BVE main window. A visible top-level window whose title contains "BVE Trainsim", owned by THIS
process, so that the managed HUD can find it by the process id. No BVE, no BveEX. It exits after its parent closes stdin or after a time limit.

Usage: python tests\\fake_bve_window.py [seconds]      (prints one line: READY pid=<pid> hwnd=<decimal> )
"""
import sys
import threading
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    app = QApplication(sys.argv[:1])
    widget = QWidget()
    widget.setWindowTitle("BVE Trainsim (E4 test window)")
    widget.setGeometry(120, 120, 640, 400)
    widget.show()
    print("READY pid=%d hwnd=%d" % (__import__("os").getpid(), int(widget.winId())), flush=True)

    def watch_stdin():
        try:
            sys.stdin.read()
        except Exception:
            pass
        QTimer.singleShot(0, app.quit)

    threading.Thread(target=watch_stdin, daemon=True).start()
    QTimer.singleShot(int(limit * 1000), app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
