import math
import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath, QPen
from config import *

# ★ ネットワークファイル用のログ関数
def write_debug_log(msg):
    try:
        with open("debug_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except:
        pass

def get_outline_color(t_color):
    return COLOR_OUTLINE_BLACK if t_color == COLOR_WHITE else COLOR_OUTLINE_WHITE

# 【軽量版】8方向ずらし描画（F6メニューや、X線ゴーグルなど文字が細かい画面用）
def draw_text_with_outline(painter, text, font, text_color, outline_color, x, y, align="left", passes=8):
    fm = QFontMetrics(font)
    text_str = str(text)
    if align == "right":
        x -= fm.horizontalAdvance(text_str)
    elif align == "center":
        x -= fm.horizontalAdvance(text_str) / 2

    painter.setFont(font)
    
    if isinstance(outline_color, tuple):
        painter.setPen(QColor(*outline_color))
    else:
        painter.setPen(outline_color)
        
    offset = OUTLINE_WIDTH / 2.0
    offsets = [(-offset, -offset), (0, -offset), (offset, -offset), 
               (-offset, 0),                     (offset, 0), 
               (-offset, offset),  (0, offset),  (offset, offset)]
               
    for dx, dy in offsets:
        painter.drawText(int(x + dx), int(y + dy), text_str)

    if isinstance(text_color, tuple):
        painter.setPen(QColor(*text_color))
    else:
        painter.setPen(text_color)
    painter.drawText(int(x), int(y), text_str)

# ★【高品質版】パス・ストローク描画（HUDのデカ文字用・Wordと同じ美しい縁取り）
def draw_text_with_stroke(painter, text, font, text_color, outline_color, x, y, align="left", stroke_width=OUTLINE_WIDTH):
    path = QPainterPath()
    fm = QFontMetrics(font)
    text_str = str(text)
    
    if align == "right":
        x -= fm.horizontalAdvance(text_str)
    elif align == "center":
        x -= fm.horizontalAdvance(text_str) / 2
        
    path.addText(x, y, font, text_str)
    
    if isinstance(outline_color, tuple):
        pen_color = QColor(*outline_color)
    else:
        pen_color = outline_color
        
    pen = QPen(pen_color, stroke_width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(path)
    
    painter.setPen(Qt.PenStyle.NoPen)
    if isinstance(text_color, tuple):
        brush_color = QColor(*text_color)
    else:
        brush_color = text_color
    painter.setBrush(brush_color)
    painter.drawPath(path)

# ==========================================================
# ★ scoring_logic.py で使われる計算用関数（迷子になっていたものを統合）
# ==========================================================
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