"""Child process of tests/test_ofs_official_fullscreen.py (Phase OFS-1): a REAL main.Overlay on the real Windows Qt platform at a forced display scale (QT_SCALE_FACTOR is
set by the parent). Places it on a 1920x1080 physical rectangle (the official fullscreen) and prints the width of the HUD clock, the HUD bounding box and a digest of the
drawn pixels. usage: ofs_hinting_child.py <menu_state>"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.dont_write_bytecode = True

import numpy as np                                 # noqa: E402
from PyQt6.QtWidgets import QApplication           # noqa: E402
app = QApplication(sys.argv[:1])
import main                                        # noqa: E402

overlay = main.Overlay(udp_port=0)
overlay.timer.stop()
overlay.menu_state = int(sys.argv[1]) if len(sys.argv) > 1 else 0
overlay.set_client_rect_physical(0, 0, 1920, 1080)
app.processEvents()
img = overlay.grab().toImage()
ptr = img.constBits()
ptr.setsize(img.sizeInBytes())
a = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :]
ink = (a[:, :, :3].max(axis=2) > 235) & (a[:, :, 3] > 0)
ys, xs = np.nonzero(ink)
rows = np.nonzero(ink.any(axis=1))[0]
start = end = int(rows[0])
for r in rows[1:]:
    if r - end <= 2:
        end = int(r)
    else:
        break
band = ink[start:end + 1]
bx = np.nonzero(band.any(axis=0))[0]
print(json.dumps({"dpr": overlay.devicePixelRatioF(), "grab": [img.width(), img.height()], "clock_w": int(bx.max() - bx.min() + 1),
                  "hud_bbox": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
                  "digest": hashlib.sha256(bytes(ptr)).hexdigest()[:16],
                  "hinting": [int(f.hintingPreference().value) for f in (overlay.font_normal, overlay.font_big, overlay.font_ui, overlay.font_menu, overlay.font_desc)]}), flush=True)
