"""Overlay coordinate contract (Phase OVS-1). Pure functions: no Qt, no Win32.

Unit tags used in this project:
  phys     Win32 physical pixels (GetClientRect / ClientToScreen / GetCursorPos / SetWindowPos). The only source of truth for where BVE is.
  logical  Qt logical pixels (QWidget.setGeometry / width / height). Qt multiplies them by devicePixelRatio when it talks to Windows.
  design   the 1920x1080 reference coordinates the HUD and the menus are drawn in.

The Overlay is placed on the BVE client rectangle in PHYSICAL pixels (SetWindowPos). Drawing keeps using the widget's own logical size (a ratio, so the
display scale cancels out). A click is mapped back with the same PHYSICAL rectangle, so drawing and hit testing agree at every display scale.
"""
from config import BASE_SCREEN_H, BASE_SCREEN_W


def logical_geometry(rect_phys, dpr):
    """The logical (x, y, w, h) that corresponds to a physical rect at device pixel ratio `dpr`. Only used to keep Qt's own geometry in step before the
    exact physical placement; never a source of truth."""
    x, y, w, h = rect_phys
    if not dpr or dpr <= 0:
        dpr = 1.0
    return round(x / dpr), round(y / dpr), max(1, round(w / dpr)), max(1, round(h / dpr))


def menu_local_point(cursor_phys, rect_phys):
    """Design coordinates (1920x1080 space) of a physical cursor position for the menu screens: the same letterbox transform as menu_ui.draw_menu
    (scale = min(width ratio, height ratio), centred), evaluated on the physical client rectangle."""
    x, y, w, h = rect_phys
    scale = min(w / BASE_SCREEN_W, h / BASE_SCREEN_H)
    offset_x = (w - BASE_SCREEN_W * scale) / 2
    offset_y = (h - BASE_SCREEN_H * scale) / 2
    return (cursor_phys[0] - x - offset_x) / scale, (cursor_phys[1] - y - offset_y) / scale


WS_CAPTION = 0x00C00000
WS_EX_TOPMOST = 0x00000008


def is_native_fullscreen(style, exstyle):
    """Phase OFS-1: True when the BVE window is in BVE's own (official) fullscreen: TOPMOST and without a caption. BVE makes its window topmost only there
    (OFS-0 measurement: window mode ex 0x50100 with a caption, TScoring's F11 state ex 0x50000 without a caption but not topmost, official fullscreen
    ex 0x50008 without a caption). The values may come from GetWindowLong as signed 32 bit numbers."""
    return bool((exstyle & 0xFFFFFFFF) & WS_EX_TOPMOST) and not ((style & 0xFFFFFFFF) & WS_CAPTION)


def rects_match(a, b, tolerance=1):
    """True when two (x, y, w, h) rectangles agree within `tolerance` physical pixels (rounding of the logical <-> physical conversion)."""
    return a is not None and b is not None and all(abs(p - q) <= tolerance for p, q in zip(a, b))
