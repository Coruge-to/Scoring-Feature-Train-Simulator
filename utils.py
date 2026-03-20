import math
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPen, QFontMetrics, QPainterPath
from config import *

def calculate_warning_distance(current_speed, next_limit):
    if next_limit < current_speed:
        speed_diff = current_speed - next_limit
        a_kmh = 3.5 if speed_diff >= 40.0 else 2.5
        v0 = current_speed / 3.6
        v1 = next_limit / 3.6
        a = a_kmh / 3.6 
        decel_dist = (v0**2 - v1**2) / (2 * a)
        margin_dist = v0 * 5.0 
        return decel_dist, decel_dist + margin_dist
    return 0.0, 0.0

def calculate_apex_speed(v_start_kmh, v_target_kmh, dist_m, lower_limit_kmh):
    v0 = v_start_kmh / 3.6
    v1 = lower_limit_kmh / 3.6
    a1 = 1.5 / 3.6 
    speed_diff = v_target_kmh - lower_limit_kmh 
    a_kmh = 3.5 if speed_diff >= 40.0 else 2.5
    a2 = a_kmh / 3.6 
    A = (a1 + a2) / (2 * a1 * a2)
    B = 5.0
    C = -(dist_m + (v0**2)/(2*a1) + (v1**2)/(2*a2))
    D = B**2 - 4*A*C
    if D < 0: return v_start_kmh 
    v_apex = (-B + math.sqrt(D)) / (2 * A)
    v_apex_kmh = v_apex * 3.6
    return max(v_start_kmh, min(v_apex_kmh, v_target_kmh))

def get_outline_color(t_color):
    return COLOR_OUTLINE_BLACK if t_color == COLOR_WHITE else COLOR_OUTLINE_WHITE

def draw_text_with_outline(painter, text, font, text_color, outline_color, x, y, align="left"):
    path = QPainterPath()
    fm = QFontMetrics(font)
    if align == "right": x -= fm.horizontalAdvance(text)
    elif align == "center": x -= fm.horizontalAdvance(text) / 2
    path.addText(x, y, font, text)
    
    pen = QPen(QColor(*outline_color) if isinstance(outline_color, tuple) else QColor(outline_color), OUTLINE_WIDTH)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    
    brush = QColor(*text_color) if isinstance(text_color, tuple) else QColor(text_color)
    painter.setBrush(brush)
    painter.drawPath(path)