"""Child process of tests/test_ovs_overlay_physical_px.py (Phase OVS-1): a REAL main.Overlay on the real Windows Qt platform at a forced display scale
(QT_SCALE_FACTOR is set by the parent). Applies BVE client rectangles the way the product does (or the way it did before OVS-1) and reports the real Win32
rectangle after every step, the Qt DPR, the physical size of what is drawn and a click round trip.
usage: ovs_dpr_child.py <mode: product|legacy_setgeometry> <json list of [x, y, w, h]> <menu_state>
The window is never shown (a created native window is enough for SetWindowPos / GetWindowRect / grab). Units: every *_phys value is Win32 physical px."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.dont_write_bytecode = True
mode = sys.argv[1]
rects = json.loads(sys.argv[2])
menu_state = int(sys.argv[3])

import numpy as np                                 # noqa: E402
import win32gui                                    # noqa: E402
from PyQt6.QtWidgets import QApplication           # noqa: E402
app = QApplication(sys.argv[:1])
import main                                        # noqa: E402
import overlay_transform                           # noqa: E402

overlay = main.Overlay(udp_port=0)
overlay.menu_state = menu_state
steps = []
for x, y, w, h in rects:
    if mode == "product":
        overlay.set_client_rect_physical(x, y, w, h)
    else:
        overlay.setGeometry(x, y, w, h)           # the pre-OVS-1 call: Win32 physical px handed to Qt's logical setGeometry
    app.processEvents()
    left, top, right, bottom = win32gui.GetWindowRect(int(overlay.winId()))
    steps.append([left, top, right - left, bottom - top])
pix = overlay.grab()
img = pix.toImage()
ptr = img.constBits(); ptr.setsize(img.sizeInBytes())
a = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :]
ink = (a[:, :, :3].max(axis=2) > 170) & (a[:, :, 3] > 0)
ys, xs = np.nonzero(ink)
box = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)] if len(ys) else None
rows = np.nonzero(ink.any(axis=1))[0]
band = None
if len(rows):
    start = end = int(rows[0])
    for r in rows[1:]:
        if r - end <= 2:
            end = int(r)
        else:
            break
    band = [start, end - start + 1]
out = {"dpr": overlay.devicePixelRatioF(), "win32_rect_steps": steps, "grab_phys_size": [img.width(), img.height()], "ink_bbox_phys": box, "first_band_phys": band,
       "qt_geometry": list(overlay.geometry().getRect()), "client_phys": [float(v) for v in overlay.client_rect_physical()]}

# click round trip (menu screens only): the centre of every click zone, placed on the screen with the DRAWING's transform, must be found again by the hit test
if menu_state and mode == "product":
    gw, gh = img.width(), img.height()
    scale = min(gw / 1920.0, gh / 1080.0)
    ox, oy = (gw - 1920 * scale) / 2, (gh - 1080 * scale) / 2
    cx0, cy0 = overlay.client_rect_physical()[:2]
    worst, with_ink, count = 0.0, 0, 0
    for zone in overlay.menu_click_zones:
        x1, y1, x2, y2 = zone[:4]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        cursor = (cx0 + ox + cx * scale, cy0 + oy + cy * scale)
        lx, ly = overlay_transform.menu_local_point(cursor, overlay.client_rect_physical())
        worst = max(worst, abs(lx - cx), abs(ly - cy))
        px1, py1, px2, py2 = (int(ox + x1 * scale), int(oy + y1 * scale), int(ox + x2 * scale), int(oy + y2 * scale))
        px1, py1, px2, py2 = max(0, px1), max(0, py1), min(gw, px2), min(gh, py2)
        count += 1
        if px2 > px1 and py2 > py1 and ink[py1:py2, px1:px2].any():
            with_ink += 1
    out["click"] = {"zones": count, "zones_with_ink_under_drawn_box": with_ink, "worst_round_trip_error_design_units": worst}
if mode == "product":
    # the real client_rect_applied: true on the rectangle just placed, false once something else (Qt rescaling, a move) changed the real window
    last = tuple(rects[-1])
    out["applied_after_place"] = bool(overlay.client_rect_applied(last))
    win32gui.SetWindowPos(int(overlay.winId()), 0, 5, 5, 300, 200, 0x4 | 0x10)        # something else moves / resizes the real window (SWP_NOZORDER | SWP_NOACTIVATE)
    app.processEvents()
    out["applied_after_foreign_move"] = bool(overlay.client_rect_applied(last))
print(json.dumps(out), flush=True)
os._exit(0)
