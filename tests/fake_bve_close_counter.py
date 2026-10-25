"""Phase UI-ALT-F4 test helper: a stand-in for the BVE main window that COUNTS the WM_CLOSE messages it receives and does not close. A visible top-level window
whose title contains "BVE Trainsim", owned by THIS process, so that the managed HUD finds it by the process id. No BVE, no BveEX.

Usage: python tests\\fake_bve_close_counter.py [seconds]
Prints   READY pid=<pid> hwnd=<decimal>      once the window exists, and
         CLOSE n=<count>                     for every WM_CLOSE that reaches the window (the window stays open: the count is the evidence).
It exits after its parent closes stdin or after the time limit.
"""
import os
import sys
import threading
from ctypes import wintypes

from PyQt6.QtWidgets import QApplication, QWidget

WM_CLOSE = 0x0010


class CountingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.closes = 0

    def nativeEvent(self, event_type, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_CLOSE:
                self.closes += 1
                print("CLOSE n=%d" % self.closes, flush=True)
        except Exception:
            pass
        return False, 0

    def closeEvent(self, event):
        event.ignore()                       # the stand-in never ends: the message count is the observation


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    app = QApplication(sys.argv[:1])
    widget = CountingWindow()
    widget.setWindowTitle("BVE Trainsim (close counter)")
    widget.setGeometry(160, 160, 640, 400)
    widget.show()
    print("READY pid=%d hwnd=%d" % (os.getpid(), int(widget.winId())), flush=True)

    def leave():
        os._exit(0)                          # (app.quit() asks the windows to close first, and this one never agrees)

    def watch_stdin():
        try:
            sys.stdin.read()
        except Exception:
            pass
        leave()

    threading.Thread(target=watch_stdin, daemon=True).start()
    timer = threading.Timer(limit, leave)
    timer.daemon = True
    timer.start()
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
