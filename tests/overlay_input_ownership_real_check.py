"""Phase UI-ALT-F4: facts about the REAL Overlay window (real Qt + real Win32): who receives the mouse, who is in front, what a close that comes from the
user does. The real Overlay class and the real ManagedHudController / Win32WindowApi of the tree given by --root; the BVE window is a stand-in process
(tests\\fake_bve_close_counter.py) that counts the WM_CLOSE messages it receives. No BVE, no BveEX, no Caller. Nothing is typed and no mouse event is sent: a close
is sent as a window message to the Overlay's own handle.

Without --foreground nothing here takes the foreground of the desktop (the controller declines to take it from another application). With --foreground the
script takes it on purpose to build the situations of the live observation (the Overlay or the save dialog in front).

Usage: python -B tests\\overlay_input_ownership_real_check.py [--root DIR] [--foreground]      (prints ONE JSON object; exit code 0 when it could run)
"""
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def parse(argv):
    root = os.path.dirname(HERE)
    foreground = False
    i = 0
    while i < len(argv):
        if argv[i] == "--root":
            root = os.path.abspath(argv[i + 1])
            i += 1
        elif argv[i] == "--foreground":
            foreground = True
        i += 1
    return root, foreground


def main():
    root, with_foreground = parse(sys.argv[1:])
    os.environ.pop("QT_QPA_PLATFORM", None)          # real windows: an offscreen platform (set by other suites in the same run) has no window handles
    sys.path.insert(0, root)
    import win32api
    import win32con
    import win32gui
    import win32process
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QApplication, QFileDialog

    import main as ts_main
    import managed_hud
    import managed_mode

    app = QApplication(sys.argv[:1])
    result = {"root": root, "foreground_steps": with_foreground, "steps": {}}

    def pump(ms=250):
        end = time.monotonic() + ms / 1000.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def force_foreground(hwnd):
        """The test's own way to be in front (the situation, not the product): same method as the product's hand-over."""
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        front = win32gui.GetForegroundWindow()
        front_thread = win32process.GetWindowThreadProcessId(front)[0] if front else 0
        own_thread = win32api.GetCurrentThreadId()
        joined = False
        try:
            if front_thread and front_thread != own_thread:
                try:
                    joined = bool(win32process.AttachThreadInput(own_thread, front_thread, True))
                except Exception:
                    joined = False
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
        finally:
            if joined:
                win32process.AttachThreadInput(own_thread, front_thread, False)
        pump(80)
        return win32gui.GetForegroundWindow() == hwnd

    # -- the stand-in BVE window (another process) ---------------------------------------------------------------------------------------
    bve = subprocess.Popen([sys.executable, "-B", os.path.join(HERE, "fake_bve_close_counter.py"), "90"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
    lines = []

    def read_lines():
        for line in bve.stdout:
            lines.append(line.strip())

    first = bve.stdout.readline().strip()
    if not first.startswith("READY"):
        result["error"] = "fake BVE did not start: " + first
        print(json.dumps(result))
        return 2
    threading.Thread(target=read_lines, daemon=True).start()
    bve_pid = int(first.split("pid=")[1].split()[0])
    bve_hwnd = int(first.split("hwnd=")[1].split()[0])
    names = {bve_hwnd: "bve"}

    def who(hwnd):
        return names.get(hwnd, "none" if not hwnd else "other")

    class CloseProbe(QObject):
        def __init__(self):
            super().__init__()
            self.events = []

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Close:
                self.events.append(bool(event.spontaneous()))
            return False

    args = managed_mode.ManagedArgs(bve_pid, "a" * 32, "test")
    log_lines = []

    def make_overlay_and_controller():
        overlay = ts_main.Overlay(0)
        overlay.timer.stop()
        ctl = managed_hud.ManagedHudController(overlay, None, managed_hud.Win32WindowApi(), args, log_lines.append, update_step=lambda ov: ov.update(), timer=None)
        ctl._hwnd = bve_hwnd
        probe = CloseProbe()
        overlay.installEventFilter(probe)
        calls = []
        if hasattr(ctl, "request_user_close"):
            overlay.user_close_handler = ctl.request_user_close
        return overlay, ctl, probe, calls

    def tick(ctl, count=1, ms=20):
        for _ in range(count):
            ctl._tick_active()
            pump(ms)

    def snapshot(overlay, tag):
        ohwnd = int(overlay.winId())
        names[ohwnd] = "overlay"
        style = win32gui.GetWindowLong(ohwnd, win32con.GWL_EXSTYLE)
        left, top, right, bottom = win32gui.GetWindowRect(ohwnd)
        hit = win32gui.WindowFromPoint(((left + right) // 2, (top + bottom) // 2))
        front = win32gui.GetForegroundWindow()
        info = {"tag": tag, "overlay_hwnd": ohwnd, "exstyle": "0x%08X" % (style & 0xFFFFFFFF), "click_through": bool(style & win32con.WS_EX_TRANSPARENT),
                "qt_visible": bool(overlay.isVisible()), "hwnd_exists": bool(win32gui.IsWindow(ohwnd)), "hwnd_visible": bool(win32gui.IsWindowVisible(ohwnd)),
                "owner_is_bve": win32gui.GetWindow(ohwnd, win32con.GW_OWNER) == bve_hwnd, "hit_at_center": who(hit), "foreground": who(front),
                "enabled": bool(win32gui.IsWindowEnabled(ohwnd))}
        return info

    steps = result["steps"]

    # -- 1. the HUD (no menu) ---------------------------------------------------------------------------------------------------------------
    overlay, ctl, probe, calls = make_overlay_and_controller()
    tick(ctl, 5)
    names[int(overlay.winId())] = "overlay"
    steps["1_hud"] = snapshot(overlay, "hud")
    hwnd0 = int(overlay.winId())

    # -- 2. an operation screen is open (F1 menu / settings / result: menu_state != 0) ------------------------------------------------------------
    if with_foreground:
        steps["2_precondition_bve_in_front"] = force_foreground(bve_hwnd)
    overlay.toggle_menu(False)                    # F1: the menu is really drawn (an opaque backdrop is what a click-through-free layered window hits)
    tick(ctl, 45)
    steps["2_operation_screen"] = snapshot(overlay, "operation-screen-open")
    steps["2_operation_screen"]["menu_state"] = overlay.menu_state
    steps["2_operation_screen"]["same_hwnd"] = int(overlay.winId()) == hwnd0
    steps["2_operation_screen"]["has_input_ownership"] = bool(overlay.has_input_ownership()) if hasattr(overlay, "has_input_ownership") else None

    # -- 3. the operation screen is closed again ---------------------------------------------------------------------------------------------------
    overlay.toggle_menu(False)
    tick(ctl, 10)
    steps["3_operation_screen_closed"] = snapshot(overlay, "operation-screen-closed")
    steps["3_operation_screen_closed"]["same_hwnd"] = int(overlay.winId()) == hwnd0

    # -- 4. the save dialog (owner = Overlay) closes: who gets the foreground back? ------------------------------------------------------------------
    if with_foreground:
        overlay.menu_state = 11
        tick(ctl, 45)
        steps["4_before_dialog"] = snapshot(overlay, "result-screen")
        dialog = QFileDialog(overlay, "save")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.open()
        pump(300)
        dhwnd = int(dialog.winId())
        names[dhwnd] = "dialog"
        steps["4_dialog_in_front"] = force_foreground(dhwnd)
        steps["4_dialog_open"] = snapshot(overlay, "dialog-open")
        dialog.reject()
        pump(400)
        steps["4_after_dialog"] = snapshot(overlay, "dialog-closed")
        tick(ctl, 5)
        steps["4_after_dialog_ticks"] = snapshot(overlay, "dialog-closed-after-ticks")
        overlay.menu_state = 0
        tick(ctl, 10)

    # -- 4b. Alt+F4 on the open save dialog (the close arrives at the dialog's own window): the dialog is cancelled, nothing else happens ---------------------
    overlay.menu_state = 11
    tick(ctl, 5)
    closes_before = sum(1 for l in lines if l.startswith("CLOSE"))
    probe_before = len(probe.events)
    dialog2 = QFileDialog(overlay, "save")
    dialog2.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog2.open()
    pump(300)
    dhwnd2 = int(dialog2.winId())
    was_open = bool(dialog2.isVisible())
    win32gui.SendMessage(dhwnd2, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
    pump(300)
    tick(ctl, 3)
    steps["4b_alt_f4_on_the_dialog"] = {"dialog_was_open": was_open, "dialog_open_after": bool(dialog2.isVisible()), "overlay_close_events": len(probe.events) - probe_before,
                                         "bve_close_messages_added": sum(1 for l in lines if l.startswith("CLOSE")) - closes_before, "overlay_visible": bool(overlay.isVisible()),
                                         "overlay_hwnd_unchanged": int(overlay.winId()) == hwnd0, "bve_alive": bve.poll() is None,
                                         "user_close_sent": getattr(ctl, "user_close_sent", None), "menu_state": overlay.menu_state}
    overlay.menu_state = 0
    tick(ctl, 10)

    # -- 5. the user closes the Overlay (Alt+F4 while it is in front arrives as SC_CLOSE, then WM_CLOSE) ---------------------------------------------
    if with_foreground:
        steps["5_precondition_overlay_in_front"] = force_foreground(int(overlay.winId()))
    before_close = int(overlay.winId())
    win32gui.SendMessage(before_close, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
    pump(400)
    after = snapshot(overlay, "after-user-close")
    after["close_events_spontaneous"] = list(probe.events)
    after["hwnd_unchanged"] = int(overlay.winId()) == before_close if overlay.isVisible() else None
    after["controller_shown_flag"] = ctl.shown
    after["user_close_sent"] = getattr(ctl, "user_close_sent", None)
    after["bve_close_messages"] = sum(1 for l in lines if l.startswith("CLOSE"))
    after["bve_process_alive"] = bve.poll() is None
    steps["5_user_close_1"] = after
    for n in (2, 3):
        win32gui.SendMessage(int(overlay.winId()), win32con.WM_CLOSE, 0, 0)
        pump(200)
    steps["5_user_close_3_total"] = {"close_events_spontaneous": list(probe.events), "bve_close_messages": sum(1 for l in lines if l.startswith("CLOSE")),
                                     "user_close_sent": getattr(ctl, "user_close_sent", None), "user_close_skipped": getattr(ctl, "user_close_skipped", None),
                                     "qt_visible": bool(overlay.isVisible())}
    tick(ctl, 10)
    steps["5_after_ticks"] = {"qt_visible": bool(overlay.isVisible()), "controller_shown_flag": ctl.shown, "reconciles": getattr(ctl, "reconciles", None)}
    result["hud_lines_after_user_close"] = [l for l in log_lines if "hud-user-close" in l or "hud-reconcile" in l]
    result["hud_input_lines"] = [l.replace("[MANAGED] ", "") for l in log_lines if "hud-input" in l or "hud-zorder" in l or "hud-error" in l]

    # -- 6. a close the PROGRAM asks for (the shutdown's overlay.close()) ------------------------------------------------------------------------------
    overlay2, ctl2, probe2, calls2 = make_overlay_and_controller()
    tick(ctl2, 5)
    close_before = sum(1 for l in lines if l.startswith("CLOSE"))
    overlay2.close()
    pump(300)
    steps["6_programmatic_close"] = {"close_events_spontaneous": list(probe2.events), "qt_visible": bool(overlay2.isVisible()),
                                     "bve_close_messages_added": sum(1 for l in lines if l.startswith("CLOSE")) - close_before}

    # -- 7. the shown flag against a hidden Overlay (no close involved) -------------------------------------------------------------------------------
    overlay3, ctl3, probe3, calls3 = make_overlay_and_controller()
    tick(ctl3, 5)
    shown_before = ctl3.shown
    overlay3.hide()
    pump(100)
    tick(ctl3, 5)
    steps["7_hidden_from_outside"] = {"shown_flag_before": shown_before, "shown_flag_after": ctl3.shown, "qt_visible_after": bool(overlay3.isVisible()),
                                      "reconciles": getattr(ctl3, "reconciles", None)}

    # -- end ---------------------------------------------------------------------------------------------------------------------------------------------
    result["bve_close_messages_total"] = sum(1 for l in lines if l.startswith("CLOSE"))
    try:
        bve.stdin.close()
    except Exception:
        pass
    for o in (overlay, overlay2, overlay3):
        try:
            o.user_close_handler = None
            o.close()
        except Exception:
            pass
    try:
        bve.wait(timeout=10)
    except Exception:
        bve.kill()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
