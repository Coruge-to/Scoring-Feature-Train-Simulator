"""HUD Z order check with REAL top-level windows (Qt) and the REAL Win32WindowApi / ManagedHudController._ensure_z_order. No BVE, no BveEX, no Caller.

Three windows: "bve" (the driving window stand-in), "select" (the scenario selection window stand-in) and "hud" (a window with the flags of the Overlay).
It reproduces the defect (a freshly shown HUD is in front of the selection window) and checks the correction. The selection window is never identified
by the HUD code: only its place in the Z order matters.

Usage: python -I tests\\zorder_real_check.py owned|unowned      (prints one JSON line; exit code 0 when it could run)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32con  # noqa: E402
import win32gui  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

import managed_hud  # noqa: E402
import managed_mode  # noqa: E402


def main():
    variant = sys.argv[1] if len(sys.argv) > 1 else "owned"
    app = QApplication(sys.argv[:1])

    def pump(ms=250):
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    bve = QWidget()
    bve.setWindowTitle("BVE Trainsim (Z-order check)")
    bve.setGeometry(300, 300, 520, 340)
    bve.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    bve.show()
    pump()
    bve_hwnd = int(bve.winId())

    select = QWidget()
    select.setWindowTitle("Z-order check: selection window")
    select.setGeometry(340, 340, 300, 200)
    select.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    select_hwnd = int(select.winId())
    if variant == "owned":
        win32gui.SetWindowLong(select_hwnd, win32con.GWL_HWNDPARENT, bve_hwnd)
    select.show()
    pump()

    hud = QWidget()
    hud.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)   # the Overlay's flags
    hud.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    hud.setGeometry(310, 310, 500, 300)

    class Gate(object):
        pass

    args = managed_mode.ManagedArgs(os.getpid(), "a" * 32, "test")
    api = managed_hud.Win32WindowApi()
    calls = []
    real_place = api.place_below

    def counting_place(overlay_hwnd, above):
        calls.append((overlay_hwnd, above))
        return real_place(overlay_hwnd, above)

    api.place_below = counting_place
    ctl = managed_hud.ManagedHudController(hud, None, api, args, lambda text: None)
    ctl._hwnd = bve_hwnd

    names = {bve_hwnd: "bve", select_hwnd: "select"}

    def order():
        hud_hwnd = int(hud.winId())
        names[hud_hwnd] = "hud"
        found = []

        def cb(hwnd, _):
            if hwnd in names and win32gui.IsWindowVisible(hwnd):
                found.append(names[hwnd])
            return True

        win32gui.EnumWindows(cb, None)
        return found

    result = {"variant": variant}

    # 1. what _tick_active does when the HUD is shown while the selection window is open: show, owner, order
    ctl._show()
    pump()
    ctl._ensure_owner()
    pump()
    before = order()
    result["before_fix"] = before
    result["defect_reproduced"] = before.index("hud") < before.index("select")

    fg0 = win32gui.GetForegroundWindow()
    ctl._ensure_z_order()
    pump()
    result["after_fix"] = order()
    del calls[:]
    for _ in range(50):
        ctl._ensure_z_order()
    result["repeat_calls"] = len(calls)
    result["foreground_unchanged"] = (win32gui.GetForegroundWindow() == fg0)

    # 2. the selection window is closed: the same HUD is directly above the driving window
    select.hide()
    pump()
    ctl._ensure_z_order()
    pump()
    result["closed_select"] = order()

    # 3. the Tick stops (HUD hidden), the selection window opens, the Tick resumes (HUD shown again): the same cycle as the soft OFF -> ON of the log
    ctl._hide("test")
    pump()
    select.show()
    select.raise_()          # BVE activates its selection window when it opens it: it comes to the front (test harness only)
    pump()
    ctl._show()
    pump()
    result["owner_released_before_show"] = (ctl.owner_releases == 1)
    ctl._ensure_owner()
    pump()
    result["reshow_before_fix"] = order()
    result["bve_kept_under_select"] = result["reshow_before_fix"].index("select") < result["reshow_before_fix"].index("bve")
    fg1 = win32gui.GetForegroundWindow()
    ctl._ensure_z_order()
    pump()
    result["reshow_after_hide"] = order()
    result["foreground_unchanged"] = result["foreground_unchanged"] and (win32gui.GetForegroundWindow() == fg1)

    ex = win32gui.GetWindowLong(int(hud.winId()), win32con.GWL_EXSTYLE)
    result["hud_topmost"] = bool(ex & win32con.WS_EX_TOPMOST)
    result["hud_owner_is_bve"] = (win32gui.GetWindow(int(hud.winId()), win32con.GW_OWNER) == bve_hwnd)

    for w in (hud, select, bve):
        w.close()
    pump(100)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
