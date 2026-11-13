"""Phase OFS-1: HUD Z order in BVE's official fullscreen with REAL top-level windows and the REAL Win32WindowApi / ManagedHudController._ensure_z_order.
No BVE, no BveEX, no Caller.

Stand-ins (all topmost, like OFS-0 measured them): "bve" (the BVE window), "proxy" (a window of the class D3DProxyWindow of THIS process, owned by "bve",
topmost | transparent | no-activate, created after "bve" so it lies over it), "dialog" (a later topmost window of BVE: menu / settings / selection window
stand-in) and "hud" (a window with the flags of the Overlay, owner "bve", NOT topmost until the controller places it).

Usage: python tests\\zorder_real_check_ofs.py      (prints one JSON line; exit code 0 when it could run)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import win32api  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

import managed_hud  # noqa: E402
import managed_mode  # noqa: E402


def make_proxy(owner_hwnd):
    """A real top-level window of the class "D3DProxyWindow": WS_POPUP, topmost | transparent | no-activate | layered, owned by the BVE stand-in."""
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "D3DProxyWindow"
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpfnWndProc = {win32con.WM_DESTROY: lambda hwnd, msg, w, l: 0}
    try:
        win32gui.RegisterClass(wc)
    except win32gui.error:
        pass                                                   # already registered
    ex = win32con.WS_EX_TOPMOST | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_LAYERED
    hwnd = win32gui.CreateWindowEx(ex, "D3DProxyWindow", "D3DProxyWindow", win32con.WS_POPUP, 330, 330, 480, 300, owner_hwnd, 0, wc.hInstance, None)
    win32gui.SetLayeredWindowAttributes(hwnd, 0, 255, win32con.LWA_ALPHA)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    return hwnd


def main():
    app = QApplication(sys.argv[:1])

    def pump(ms=250):
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def topmost_widget(title, rect):
        w = QWidget()
        w.setWindowTitle(title)
        w.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        w.setGeometry(*rect)
        w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        w.show()
        pump()
        return w

    bve = topmost_widget("BVE Trainsim (OFS check)", (300, 300, 520, 340))
    bve_hwnd = int(bve.winId())
    proxy_hwnd = make_proxy(bve_hwnd)
    pump()
    dialog = topmost_widget("OFS check: dialog", (360, 360, 300, 200))
    dialog_hwnd = int(dialog.winId())

    hud = QWidget()
    hud.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)   # the Overlay's flags
    hud.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    hud.setGeometry(310, 310, 500, 300)

    args = managed_mode.ManagedArgs(os.getpid(), "a" * 32, "test")
    api = managed_hud.Win32WindowApi()
    ctl = managed_hud.ManagedHudController(hud, None, api, args, lambda text: None)
    ctl._hwnd = bve_hwnd

    names = {bve_hwnd: "bve", proxy_hwnd: "proxy", dialog_hwnd: "dialog"}

    def order():
        names[int(hud.winId())] = "hud"
        found = []

        def cb(hwnd, _):
            if hwnd in names and win32gui.IsWindowVisible(hwnd):
                found.append(names[hwnd])
            return True

        win32gui.EnumWindows(cb, None)
        return found

    def topmost(hwnd):
        return bool(win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST)

    result = {}
    result["api_sees_the_proxy"] = bool(api.is_bve_proxy(proxy_hwnd, os.getpid()))
    result["api_ignores_the_dialog"] = not api.is_bve_proxy(dialog_hwnd, os.getpid())
    result["api_ignores_other_pid"] = not api.is_bve_proxy(proxy_hwnd, os.getpid() + 1)
    result["bve_is_topmost"] = api.is_topmost(bve_hwnd)

    # 1. the first show: show(), owner, order (what _tick_active does)
    ctl._show()
    pump()
    ctl._ensure_owner()
    pump()
    result["before_fix"] = order()
    hud_hwnd = int(hud.winId())
    result["hud_topmost_before_fix"] = topmost(hud_hwnd)
    fg0 = win32gui.GetForegroundWindow()
    ctl._ensure_z_order()
    pump()
    result["after_fix"] = order()
    result["hud_topmost_after_fix"] = topmost(hud_hwnd)
    result["foreground_unchanged"] = (win32gui.GetForegroundWindow() == fg0)
    result["hud_owner_is_bve"] = (win32gui.GetWindow(hud_hwnd, win32con.GW_OWNER) == bve_hwnd)
    result["in_place_sets"] = ctl.z_sets
    ctl._ensure_z_order()
    result["in_place_sets_after_repeat"] = ctl.z_sets

    # 2. the dialog is closed, the HUD is hidden and shown again (a soft OFF -> ON): directly above the proxy window
    dialog.hide()
    pump()
    ctl._hide("test")
    pump()
    ctl._show()
    pump()
    ctl._ensure_owner()
    pump()
    ctl._ensure_z_order()
    pump()
    result["reshow_without_dialog"] = order()
    result["hud_topmost_reshow"] = topmost(int(hud.winId()))

    for w in (hud, dialog, bve):
        w.close()
    try:
        win32gui.DestroyWindow(proxy_hwnd)
    except Exception:
        pass
    pump(100)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
