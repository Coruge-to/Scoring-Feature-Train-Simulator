import sys
import time
import math
import win32gui
import win32con
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QFontDatabase, QPainterPath, QFontMetrics
import keyboard

# --- 設定項目 ---
FONT_PATH = r"C:\WINDOWS\FONTS\UDDIGIKYOKASHON-R.TTC"
FONT_SIZE_NORMAL = 35  
FONT_SIZE_BIG = 55
FONT_SIZE_UI = 40

COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_OUTLINE = (255, 255, 255)

COLOR_N = (0, 180, 80)      
COLOR_P = (0, 120, 220)     
COLOR_B_SVC = (220, 120, 0) 
COLOR_B_EMG = (200, 20, 20) 

OUTLINE_WIDTH = 8  

BASE_SCREEN_W = 1920.0
BASE_SCREEN_H = 1080.0

MARGIN_LEFT = 50          
MARGIN_TOP_BIG = 124      
MARGIN_TOP_NORMAL = 294   

MARGIN_RIGHT = 50         
MARGIN_TOP_UI = 100       
LABEL_WIDTH = 380         
# ----------------

def calculate_warning_distance(current_speed, next_limit):
    if next_limit < current_speed:
        v0 = current_speed / 3.6
        v1 = next_limit / 3.6
        a = 2.5 / 3.6 
        decel_dist = (v0**2 - v1**2) / (2 * a)
        margin_dist = v0 * 5.0 
        return decel_dist + margin_dist
    else:
        return 300.0

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowTransparentForInput |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(0, 0, 1920, 1080)

        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            family = QFontDatabase.applicationFontFamilies(font_id)[0]
            self.font_normal = QFont(family, FONT_SIZE_NORMAL, QFont.Weight.Bold)
            self.font_big = QFont(family, FONT_SIZE_BIG, QFont.Weight.Bold)
            self.font_ui = QFont(family, FONT_SIZE_UI, QFont.Weight.Bold)
        else:
            self.font_normal = QFont("sans-serif", FONT_SIZE_NORMAL, QFont.Weight.Bold)
            self.font_big = QFont("sans-serif", FONT_SIZE_BIG, QFont.Weight.Bold)
            self.font_ui = QFont("sans-serif", FONT_SIZE_UI, QFont.Weight.Bold)

        self.popups = []
        self.is_speed_penalty = False
        self.speed_penalty_score = 0
        self.last_penalty_time = 0
        self.key_states = {str(i): False for i in range(1, 8)}

        self.dummy_distance = 100100.0  
        self.dummy_score = 100
        
        self.current_limit = 120
        self.next_limit = 50
        self.warning_start_dist = calculate_warning_distance(self.current_limit, self.next_limit)
        self.dist_to_next_limit = self.warning_start_dist + 150.0 
        
        self.blink_phase = 0.0
        self.last_update_time = time.time()

        self.bve_hwnd = None
        self.was_bve_found = False # BVEが一度でも見つかったかどうかのフラグ
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(16)
        
        print("BVE Score Overlay Prototype 起動完了。")

    def find_bve_window(self):
        found_hwnd = None
        def callback(hwnd, _):
            nonlocal found_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "bve trainsim" in title.lower():
                    found_hwnd = hwnd
        win32gui.EnumWindows(callback, None)
        return found_hwnd

    def check_visibility(self):
        """ウィンドウの最小化・重なりを判定して表示/非表示を切り替える"""
        if not self.bve_hwnd or not win32gui.IsWindow(self.bve_hwnd):
            self.hide()
            return

        if win32gui.IsIconic(self.bve_hwnd):
            self.hide()
            return

        try:
            bve_rect = win32gui.GetWindowRect(self.bve_hwnd) 
            self_hwnd = int(self.winId())
            curr_hwnd = win32gui.GetWindow(self.bve_hwnd, win32con.GW_HWNDFIRST)
            
            while curr_hwnd and curr_hwnd != self.bve_hwnd:
                if win32gui.IsWindowVisible(curr_hwnd) and curr_hwnd != self_hwnd:
                    rect = win32gui.GetWindowRect(curr_hwnd)
                    if (rect[2] - rect[0]) > 0 and (rect[3] - rect[1]) > 0:
                        intersect = not (rect[2] <= bve_rect[0] or rect[0] >= bve_rect[2] or 
                                         rect[3] <= bve_rect[1] or rect[1] >= bve_rect[3])
                        if intersect:
                            title = win32gui.GetWindowText(curr_hwnd)
                            if title and title not in ["Program Manager", ""]:
                                self.hide()
                                return
                curr_hwnd = win32gui.GetWindow(curr_hwnd, win32con.GW_HWNDNEXT)
            
            self.show()
        except Exception:
            self.hide()

    def update_logic(self):
        if keyboard.is_pressed('esc'):
            QApplication.quit()

        # BVEウィンドウの有効性チェック
        if self.bve_hwnd is None or not win32gui.IsWindow(self.bve_hwnd):
            self.bve_hwnd = self.find_bve_window()
            
            # 【修正ポイント】もし一度見つかっていたのに見失った（閉じられた）なら、アプリを終了する
            if self.was_bve_found and self.bve_hwnd is None:
                print("BVEの終了を検知しました。アプリを終了します。")
                QApplication.quit()
                return
        
        if self.bve_hwnd:
            self.was_bve_found = True # 一度見つかったフラグを立てる
            self.check_visibility()
            
            # 位置追従
            if self.isVisible():
                try:
                    client_rect = win32gui.GetClientRect(self.bve_hwnd)
                    if client_rect[2] > 0 and client_rect[3] > 0:
                        client_x, client_y = win32gui.ClientToScreen(self.bve_hwnd, (0, 0))
                        w, h = client_rect[2], client_rect[3]
                        current_geom = self.geometry()
                        if (current_geom.x() != client_x or current_geom.y() != client_y or 
                            current_geom.width() != w or current_geom.height() != h):
                            self.setGeometry(client_x, client_y, w, h)
                except Exception:
                    self.bve_hwnd = None
        else:
            # BVEが見つかっていない間は非表示
            self.hide()

        # --- 以下、描画・計算ロジック（変更なし） ---
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time

        for key in self.key_states.keys():
            is_pressed = keyboard.is_pressed(key)
            if is_pressed and not self.key_states[key]:
                if key == '1': self.popups.append({"text": "基本制動 +500", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "pos"})
                elif key == '2': self.popups.append({"text": "停止位置 +55", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "pos"})
                elif key == '3': self.popups.append({"text": "停車時衝動 -100", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg"})
                elif key == '4':
                    self.is_speed_penalty = not self.is_speed_penalty
                    if self.is_speed_penalty: self.speed_penalty_score, self.last_penalty_time = 10, current_time
                    else: self.popups.append({"text": f"速度制限超過 -{self.speed_penalty_score}", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg"})
                elif key == '5': self.popups.append({"text": "ATS信号無視 -500", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg"})
                elif key == '6': self.popups.append({"text": "階段制動階段緩め成功!!!", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "big"})
                elif key == '7': self.popups.append({"text": "0cm停車成功!!!", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "big"})
            self.key_states[key] = is_pressed

        if self.is_speed_penalty:
            if current_time - self.last_penalty_time >= 1.0:
                self.speed_penalty_score += 3
                self.last_penalty_time = current_time

        self.popups = [p for p in self.popups if p["expire_time"] > current_time]
        
        speed_per_frame = 0.8
        self.dummy_distance -= speed_per_frame
        if self.dummy_distance < -2.0: self.dummy_distance = 100100.0 

        self.dist_to_next_limit -= speed_per_frame
        
        if 0 < self.dist_to_next_limit <= self.warning_start_dist:
            progress = self.dist_to_next_limit / self.warning_start_dist
            blink_cycle = 0.5 + (0.5 * progress)
            self.blink_phase += dt / blink_cycle
            if self.blink_phase >= 1.0: self.blink_phase -= 1.0
        else:
            self.blink_phase = 0.0

        if self.dist_to_next_limit < 0:
            self.current_limit = self.next_limit
            if self.dist_to_next_limit < -150: 
                targets = {120: 50, 50: 130, 130: 100, 100: 120}
                self.next_limit = targets.get(self.current_limit, 120)
                self.warning_start_dist = calculate_warning_distance(self.current_limit, self.next_limit)
                self.dist_to_next_limit = self.warning_start_dist + 150.0 
        
        self.update() 

    def draw_text_with_outline(self, painter, text, font, text_color, x, y, align="left"):
        path = QPainterPath()
        if align == "right":
            fm = QFontMetrics(font)
            x -= fm.horizontalAdvance(text)
        path.addText(x, y, font, text)
        pen = QPen(QColor(*COLOR_OUTLINE), OUTLINE_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*text_color))
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self.height() / BASE_SCREEN_H if self.height() > 0 else 1.0
        painter.scale(scale, scale)
        logical_width = self.width() / scale

        pos_x_left, pos_x_right = MARGIN_LEFT, logical_width - MARGIN_RIGHT
        pos_x_label = pos_x_right - LABEL_WIDTH

        y_off_p, y_off_n = 0, 0
        line_h = QFontMetrics(self.font_normal).height() + 10
        for p in [p for p in self.popups if p["type"] == "pos"]:
            self.draw_text_with_outline(painter, p["text"], self.font_normal, p["color"], pos_x_left, MARGIN_TOP_NORMAL + y_off_p)
            y_off_p += line_h
        
        base_neg_y = MARGIN_TOP_NORMAL + y_off_p
        if self.is_speed_penalty:
            self.draw_text_with_outline(painter, f"速度制限超過 -{self.speed_penalty_score}", self.font_normal, COLOR_B_EMG, pos_x_left, base_neg_y + y_off_n)
            y_off_n += line_h
        for p in [p for p in self.popups if p["type"] == "neg"]:
            self.draw_text_with_outline(painter, p["text"], self.font_normal, p["color"], pos_x_left, base_neg_y + y_off_n)
            y_off_n += line_h

        line_h_big = QFontMetrics(self.font_big).height() + 10
        for i, p in enumerate([p for p in self.popups if p["type"] == "big"]):
            self.draw_text_with_outline(painter, p["text"], self.font_big, p["color"], pos_x_left, MARGIN_TOP_BIG + (i * line_h_big))

        ui_y, ui_step = MARGIN_TOP_UI, 60
        self.draw_text_with_outline(painter, time.strftime("%H:%M:%S"), self.font_ui, COLOR_BLACK, pos_x_right, ui_y, "right")
        ui_y += ui_step
        is_delayed = int(time.time() / 10) % 2 == 0
        self.draw_text_with_outline(painter, "- 00:15" if is_delayed else "02:19", self.font_ui, COLOR_B_EMG if is_delayed else COLOR_BLACK, pos_x_right, ui_y, "right")
        ui_y += ui_step
        self.draw_text_with_outline(painter, "49.7 km/h", self.font_ui, COLOR_BLACK, pos_x_right, ui_y, "right")
        ui_y += ui_step

        l_text, l_color = f"{self.current_limit} km/h", COLOR_BLACK
        if 0 < self.dist_to_next_limit <= self.warning_start_dist:
            if self.blink_phase < 0.5:
                l_text = f"{self.next_limit} km/h"
                l_color = COLOR_P if self.next_limit > self.current_limit else COLOR_B_EMG
            else: l_text = ""
        
        self.draw_text_with_outline(painter, "最大", self.font_ui, COLOR_BLACK, pos_x_label, ui_y)
        if l_text: self.draw_text_with_outline(painter, l_text, self.font_ui, l_color, pos_x_right, ui_y, "right")
        ui_y += ui_step

        d = self.dummy_distance
        d_str = f"{d/1000.0:.2f} km" if d >= 100000 else f"{d/1000.0:.3f} km" if d >= 10000 else f"{d:.1f} m" if d >= 5 else f"{d:.2f} m"
        is_p = d >= 5000
        self.draw_text_with_outline(painter, "通過" if is_p else "停車", self.font_ui, COLOR_P if is_p else COLOR_B_EMG, pos_x_label, ui_y)
        self.draw_text_with_outline(painter, d_str, self.font_ui, COLOR_BLACK, pos_x_right, ui_y, "right")
        ui_y += ui_step

        self.draw_text_with_outline(painter, "得点", self.font_ui, COLOR_BLACK, pos_x_label, ui_y)
        self.draw_text_with_outline(painter, str(self.dummy_score), self.font_ui, COLOR_B_EMG if self.dummy_score < 0 else COLOR_BLACK, pos_x_right, ui_y, "right")
        ui_y += ui_step

        st = int(time.time() / 2) % 4
        revs = [("前", COLOR_P), ("切", COLOR_N), ("前", COLOR_P), ("後", COLOR_B_EMG)]
        pows = [("P5", COLOR_P), ("N", COLOR_N), ("B4", COLOR_B_SVC), ("非常", COLOR_B_EMG)]
        self.draw_text_with_outline(painter, revs[st][0], self.font_ui, revs[st][1], pos_x_label, ui_y)
        self.draw_text_with_outline(painter, pows[st][0], self.font_ui, pows[st][1], pos_x_right, ui_y, "right")
        ui_y += ui_step
        self.draw_text_with_outline(painter, "+2.4 ‰", self.font_ui, COLOR_BLACK, pos_x_right, ui_y, "right")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()
    sys.exit(app.exec())