import sys
import time
import math
import win32gui
import win32con
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QFontDatabase, QPainterPath, QFontMetrics, QLinearGradient
from PyQt6.QtNetwork import QUdpSocket, QHostAddress
import keyboard

# ==========================================
# ★ 採点システム カスタマイズ設定 ★
# ==========================================
BASIC_BRAKE_APPLY_LIMIT = 3   
BASIC_BRAKE_RELEASE_LIMIT = 2 

STATION_MARGIN = 200.0

IGNORE_INITIAL_BRAKE = "NONE"
IGNORE_RELEASE_BRAKE = "NONE"
# ==========================================

# --- 描画・UI 設定項目 ---
FONT_PATH = r"C:\WINDOWS\FONTS\UDDIGIKYOKASHON-R.TTC"
FONT_SIZE_NORMAL = 35  
FONT_SIZE_BIG = 55
FONT_SIZE_UI = 40

COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_OUTLINE_BLACK = (0, 0, 0)
COLOR_OUTLINE_WHITE = (255, 255, 255)
COLOR_BG = (40, 40, 40, 100) 
COLOR_N = (0, 180, 80)      
COLOR_P = (0, 120, 220)     
COLOR_B_SVC = (220, 120, 0) 
COLOR_B_EMG = (200, 20, 20) 

OUTLINE_WIDTH = 6 
BASE_SCREEN_W = 1920.0
BASE_SCREEN_H = 1080.0

MARGIN_LEFT = 50          
MARGIN_TOP_BIG = 122      
MARGIN_TOP_NORMAL = 294   
MARGIN_RIGHT = 50         
MARGIN_TOP_UI = 100       
LABEL_WIDTH = 380         

STRICT_BLUE_CAP = True  

CATEGORY_ORDER = {
    "システム": 0,
    "停止位置": 1,
    "基本制動": 2,
    "運転時分": 3,
    "ボーナス": 4,
    "ATS信号無視": 5,
    "速度制限超過": 6,
    "初動ブレーキ": 7,
    "非常ブレーキ": 8,
    "緩和ブレーキ": 9,
    "停車時衝動": 10,
    "転動": 11
}

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

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
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
        self.score = 0
        
        self.is_speed_penalty = False
        self.speed_penalty_score = 0
        self.last_penalty_time = 0
        self.key_states = {str(i): False for i in range(1, 8)}
        
        self.eb_applied = False

        self.bve_btype = "Ecb"
        self.bb_state = "IDLE"
        self.bb_apply_count = 0
        self.bb_release_count = 0
        self.bb_is_in_zone = False
        self.bb_evaluated = False
        self.bb_current_notch = 0
        self.bb_notch_change_time = 0.0
        self.bb_prev_stable_notch = 0
        self.bb_is_stable = True

        self.door_open_loc = 0.0
        self.roll_penalized = False

        self.bve_jump_count = 0
        self.last_jump_count = 0
        self.has_jumped_current_station = False

        self.blink_phase = 0.0
        self.blink_active = False
        self.last_update_time = time.time()

        self.show_graph = False
        self.g_history = []  

        self.bve_hwnd = None
        self.was_bve_found = False 
        self.is_linked = False 
        
        self.udp_socket = QUdpSocket(self)
        self.udp_socket.bind(QHostAddress.SpecialAddress.LocalHost, 54321)
        self.udp_socket.readyRead.connect(self.read_udp_data)
        
        self.bve_speed = 0.0
        self.bve_location = 0.0
        self.bve_time_ms = 0
        self.bve_gradient = 0.0
        self.bve_next_loc = -1.0
        self.bve_next_time = -1
        self.bve_is_pass = 0
        self.bve_is_timing = 0
        self.bve_margin_b = 5.0 
        self.bve_margin_f = 5.0 
        
        self.bve_rev_text = "切"
        self.bve_rev_pos = 0
        self.bve_pow_text = "N"
        self.bve_pow_notch = 0
        self.bve_brk_text = "N"
        self.bve_brk_notch = 0
        self.bve_brk_max = 8 
        self.is_single_handle = False
        
        self.all_brk_texts = []

        self.max_rev_w = 40
        self.max_pow_w = 40
        self.max_brk_w = 40

        self.bve_signal_limit = 1000.0
        self.bve_train_length = 20.0
        self.bve_map_limits = []
        
        self.bve_fwd_sig_limit = 1000.0
        self.bve_fwd_sig_loc = -1.0

        self.disp_limit = 1000.0
        self.limit_color = COLOR_WHITE
        self.last_bve_time_ms = 0

        self.effective_limit = 1000.0
        self.current_base_limit = 1000.0
        self.prev_base_limit = 1000.0
        self.limit_changed_loc = -1.0
        
        self.base_limit_type = "map"
        self.target_type = "map"
        
        self.bve_door = 0
        self.bve_term = 0
        
        self.is_first_udp = True
        self.is_first_station = True
        self.prev_next_loc = -1.0
        self.prev_door = 0
        self.prev_is_pass = 0
        self.prev_is_timing = 0
        self.prev_term = 0
        self.prev_diff_s = 0
        
        self.is_approaching = False
        self.is_stopped_out_of_range = False
        self.has_scored_time_this_station = False
        self.has_scored_stop_this_station = False
        self.has_departed = False

        self.map_head_limit = 1000.0
        self.map_tail_limit = 1000.0
        self.bve_clear_dist = 0.0
        
        self.bve_calc_g = 0.0
        self.is_stopping_zone = False
        self.max_stop_g = 0.0
        self.last_stop_g = 0.0
        
        # ★ V40.3: 停車瞬間のノッチを記録する変数
        self.stop_notch_state = "IDLE"

        self.cab_brk_count = 8
        self.has_holding_brake = False
        self.svc_brk_count = 8
        self.cushion_count = 2
        self.cushion_min = 1
        self.cushion_max = 2

        self.hb_prev_notch = 0
        self.hb_cushion_entry_time = 0.0
        self.hb_cushion_max_g = 0.0
        
        self.dbg_is_wait = False
        self.dbg_target_cap = 1000.0
        self.dbg_red = "None"
        self.dbg_blue = "None"

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(16)

    def read_udp_data(self):
        while self.udp_socket.hasPendingDatagrams():
            datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            try:
                text = datagram.decode('utf-8')
                parts = text.split(',')
                for part in parts:
                    try:
                        if part.startswith("SPEED:"): self.bve_speed = float(part.split(':')[1])
                        elif part.startswith("LOCATION:"): self.bve_location = float(part.split(':')[1])
                        elif part.startswith("TIME:"): self.bve_time_ms = int(part.split(':')[1])
                        elif part.startswith("GRADIENT:"): self.bve_gradient = float(part.split(':')[1])
                        elif part.startswith("NEXTLOC:"): self.bve_next_loc = float(part.split(':')[1])
                        elif part.startswith("NEXTTIME:"): self.bve_next_time = int(part.split(':')[1])
                        elif part.startswith("ISPASS:"): self.bve_is_pass = int(part.split(':')[1])
                        elif part.startswith("ISTIMING:"): self.bve_is_timing = int(part.split(':')[1])
                        elif part.startswith("MARGINB:"): self.bve_margin_b = float(part.split(':')[1])
                        elif part.startswith("MARGINF:"): self.bve_margin_f = float(part.split(':')[1])
                        elif part.startswith("DOOR:"): self.bve_door = int(part.split(':')[1])
                        elif part.startswith("TERM:"): self.bve_term = int(part.split(':')[1])
                        elif part.startswith("REV:"):
                            vals = part.split(':')
                            if len(vals) >= 3:
                                self.bve_rev_text = vals[1].strip()
                                self.bve_rev_pos = int(vals[2])
                        elif part.startswith("POW:"):
                            vals = part.split(':')
                            if len(vals) >= 3:
                                self.bve_pow_text = vals[1].strip()
                                self.bve_pow_notch = int(vals[2])
                        elif part.startswith("BRK:"):
                            vals = part.split(':')
                            if len(vals) >= 4:
                                self.bve_brk_text = vals[1].strip()
                                self.bve_brk_notch = int(vals[2])
                                self.bve_brk_max = int(vals[3])
                        elif part.startswith("HTYPE:"):
                            self.is_single_handle = (int(part.split(':')[1]) == 1)
                        elif part.startswith("ALLTXT:"):
                            vals = part.split(':')
                            if len(vals) >= 4:
                                rev_list = [s.strip() for s in vals[1].split('_') if s.strip()]
                                pow_list = [s.strip() for s in vals[2].split('_') if s.strip()]
                                brk_list = [s.strip() for s in vals[3].split('_') if s.strip()]
                                
                                self.all_brk_texts = brk_list
                                
                                brk_eval_list = brk_list[1:] if self.is_single_handle and len(brk_list) > 1 else brk_list
                                fm = QFontMetrics(self.font_ui)
                                self.max_rev_w = max([fm.horizontalAdvance(s) for s in rev_list] + [40])
                                self.max_pow_w = max([fm.horizontalAdvance(s) for s in pow_list] + [40])
                                self.max_brk_w = max([fm.horizontalAdvance(s) for s in brk_eval_list] + [40])
                                if len(vals) >= 5 and vals[4]:
                                    hld_list = [s.strip() for s in vals[4].split('_') if s.strip()]
                                    max_hld_w = max([fm.horizontalAdvance(s) for s in hld_list] + [0])
                                    self.max_pow_w = max(self.max_pow_w, max_hld_w)
                        elif part.startswith("SIGLIMIT:"): self.bve_signal_limit = float(part.split(':')[1])
                        elif part.startswith("TRAINLEN:"): self.bve_train_length = max(float(part.split(':')[1]), 20.0)
                        elif part.startswith("FWDSIGLIMIT:"): self.bve_fwd_sig_limit = float(part.split(':')[1])
                        elif part.startswith("FWDSIGLOC:"): self.bve_fwd_sig_loc = float(part.split(':')[1])
                        elif part.startswith("MAPHEAD:"): self.map_head_limit = float(part.split(':')[1])
                        elif part.startswith("MAPTAIL:"): self.map_tail_limit = float(part.split(':')[1])
                        elif part.startswith("CLEARDIST:"): self.bve_clear_dist = float(part.split(':')[1])
                        elif part.startswith("CALCG:"): self.bve_calc_g = float(part.split(':')[1])
                        elif part.startswith("BTYPE:"): self.bve_btype = part.split(':')[1].strip()
                        elif part.startswith("JUMP:"): self.bve_jump_count = int(part.split(':')[1])
                        elif part.startswith("CAB:"): 
                            vals = part.split(':')
                            if len(vals) >= 3:
                                self.cab_brk_count = int(vals[1])
                                self.has_holding_brake = (vals[2] == "1")
                                self.svc_brk_count = self.cab_brk_count - (1 if self.has_holding_brake else 0)
                                if self.svc_brk_count <= 3:
                                    self.cushion_count = 1
                                else:
                                    self.cushion_count = (self.svc_brk_count - 2) // 2
                                self.cushion_min = 2 if self.has_holding_brake else 1
                                self.cushion_max = self.cushion_min + self.cushion_count - 1
                        elif part.startswith("MAPLIMITS:"):
                            limits_str = part.split(':', 1)[1]
                            limits_str = limits_str.replace('∞', '1000').replace('Infinity', '1000')
                            self.bve_map_limits = []
                            if limits_str:
                                for pair in limits_str.split('_'):
                                    if '=' in pair:
                                        loc_s, val_s = pair.split('=')
                                        try:
                                            self.bve_map_limits.append((float(loc_s), float(val_s)))
                                        except ValueError:
                                            pass
                    except Exception:
                        continue 
            except Exception:
                pass

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

    def apply_time_score(self, diff_s):
        abs_diff = abs(diff_s)
        if abs_diff <= 9: add = 300
        elif abs_diff <= 19: add = 200
        elif abs_diff <= 29: add = 100
        else: add = 0
        if add > 0:
            self.score += add
            self.popups.append({"text": f"運転時分 +{add}", "color": COLOR_N, "expire_time": time.time() + 5.0, "type": "pos", "category": "運転時分"})

    def apply_stop_score(self, d_m):
        if self.is_stopped_out_of_range: return False
        if not (-self.bve_margin_f <= d_m <= self.bve_margin_b): return False
        d_m_rounded = round(d_m, 2)
        x_cm = int(abs(d_m_rounded) * 100)
        if x_cm <= 100:
            add = 5 * (100 - x_cm)
            if add > 0:
                self.score += add
                self.popups.append({"text": f"停止位置 +{add}", "color": COLOR_N, "expire_time": time.time() + 5.0, "type": "pos", "category": "停止位置"})
            if x_cm < 1: 
                return True
        return False

    def process_bb_transition(self, stable_notch):
        if stable_notch != self.bb_prev_stable_notch:
            if self.bve_btype == "Cl":
                if stable_notch >= 2 and self.bb_prev_stable_notch in [0, 1]:
                    if self.bb_state == "RELEASING":
                        self.bb_state = "FAILED"
                    elif self.bb_state != "FAILED":
                        self.bb_state = "APPLYING"
                        self.bb_apply_count += 1
                elif stable_notch == 0 and self.bb_prev_stable_notch >= 1:
                    if self.bb_state != "FAILED":
                        self.bb_state = "RELEASING"
                        self.bb_release_count += 1
            else:
                if stable_notch > self.bb_prev_stable_notch:
                    if self.bb_state == "RELEASING":
                        self.bb_state = "FAILED"
                    elif self.bb_state != "FAILED":
                        self.bb_state = "APPLYING"
                        self.bb_apply_count += 1
                elif stable_notch < self.bb_prev_stable_notch and stable_notch >= 0:
                    if self.bb_state != "FAILED":
                        self.bb_state = "RELEASING"
                        self.bb_release_count += 1
            self.bb_prev_stable_notch = stable_notch

    def get_notch_state(self, notch):
        if self.bve_btype == "Cl":
            if notch == 0: return "IDLE"
            elif notch == 1: return "CUSHION"
            else: return "STRONG"
        else:
            if notch < self.cushion_min: return "IDLE"
            elif notch <= self.cushion_max: return "CUSHION"
            else: return "STRONG"

    def update_logic(self):
        if keyboard.is_pressed('esc'):
            QApplication.quit()

        if self.bve_hwnd is None or not win32gui.IsWindow(self.bve_hwnd):
            self.bve_hwnd = self.find_bve_window()
            self.is_linked = False
            if self.was_bve_found and self.bve_hwnd is None:
                QApplication.quit()
                return
        
        if self.bve_hwnd:
            self.was_bve_found = True 
            if not self.is_linked:
                try:
                    win32gui.SetWindowLong(int(self.winId()), win32con.GWL_HWNDPARENT, self.bve_hwnd)
                    self.is_linked = True
                    self.show()
                except Exception:
                    pass

            try:
                if win32gui.IsIconic(self.bve_hwnd):
                    if self.isVisible(): self.hide()
                else:
                    client_rect = win32gui.GetClientRect(self.bve_hwnd)
                    if client_rect[2] > 0 and client_rect[3] > 0:
                        client_x, client_y = win32gui.ClientToScreen(self.bve_hwnd, (0, 0))
                        w, h = client_rect[2], client_rect[3]
                        current_geom = self.geometry()
                        if (current_geom.x() != client_x or current_geom.y() != client_y or 
                            current_geom.width() != w or current_geom.height() != h):
                            self.setGeometry(client_x, client_y, w, h)
                    if not self.isVisible(): 
                        self.show()
            except Exception:
                self.bve_hwnd = None
                self.is_linked = False
                self.hide()
        else:
            self.hide()

        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time
        self.last_bve_time_ms = self.bve_time_ms

        decel_g = -self.bve_calc_g

        self.g_history.append((current_time, decel_g, self.bve_brk_notch, self.bve_brk_max))
        cutoff_time = current_time - 10.0
        self.g_history = [h for h in self.g_history if h[0] > cutoff_time]

        just_jumped = False
        if self.bve_jump_count != self.last_jump_count:
            self.has_jumped_current_station = True
            just_jumped = True
            self.blink_active = False
            self.blink_phase = 0.0
            if self.bve_door == 1:
                self.door_open_loc = self.bve_location
            self.last_jump_count = self.bve_jump_count

        in_station_zone = False
        if self.bve_next_loc >= 0:
            dist_to_stop = self.bve_next_loc - self.bve_location
            if abs(dist_to_stop) <= (self.bve_train_length + STATION_MARGIN):
                in_station_zone = True

        if 0.0 < self.bve_speed <= 1.5:
            self.is_stopping_zone = True
            if decel_g > self.max_stop_g:
                self.max_stop_g = decel_g
        elif self.bve_speed == 0.0:
            if self.is_stopping_zone:
                # ★ V40.3: 速度が0になった瞬間のノッチ帯域を記録
                self.stop_notch_state = self.get_notch_state(self.bve_brk_notch)
                self.last_stop_g = self.max_stop_g
                if self.max_stop_g >= 0.10:
                    self.score -= 200
                    self.popups.append({"text": "停車時衝動 -200", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "停車時衝動"})
                elif self.max_stop_g >= 0.07:
                    self.score -= 100
                    self.popups.append({"text": "停車時衝動 -100", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "停車時衝動"})
                self.is_stopping_zone = False
        else:
            self.is_stopping_zone = False
            self.max_stop_g = 0.0

        if self.bve_speed > 0.0:
            if self.bve_brk_notch >= self.bve_brk_max or "非常" in self.bve_brk_text or "EB" in self.bve_brk_text.upper():
                if not self.eb_applied:
                    self.score -= 500
                    self.popups.append({"text": "非常ブレーキ使用 -500", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "非常ブレーキ"})
                    self.eb_applied = True
            else:
                self.eb_applied = False

            curr_n = self.bve_brk_notch
            curr_state = self.get_notch_state(curr_n)
            prev_state = self.get_notch_state(self.hb_prev_notch)

            if curr_state == "CUSHION":
                if prev_state != "CUSHION":
                    self.hb_cushion_entry_time = current_time
                    self.hb_cushion_max_g = 0.0
                if decel_g > self.hb_cushion_max_g:
                    self.hb_cushion_max_g = decel_g

            if curr_state == "STRONG" and prev_state != "STRONG":
                is_initial_exempt = (IGNORE_INITIAL_BRAKE == "ALL") or (IGNORE_INITIAL_BRAKE == "STATION" and in_station_zone)
                if not is_initial_exempt:
                    if prev_state == "CUSHION":
                        stay_time = current_time - self.hb_cushion_entry_time
                        g_check = True
                        if self.bve_btype != "Cl":
                            g_check = (self.hb_cushion_max_g >= 0.010)
                        
                        if stay_time < 0.5 or not g_check:
                            self.score -= 100
                            self.popups.append({"text": "初動ブレーキ -100", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "初動ブレーキ"})
                    else:
                        self.score -= 100
                        self.popups.append({"text": "初動ブレーキ -100", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "初動ブレーキ"})

            if curr_state == "IDLE" and prev_state != "IDLE":
                is_release_exempt = (IGNORE_RELEASE_BRAKE == "ALL") or (IGNORE_RELEASE_BRAKE == "STATION" and in_station_zone)
                if not is_release_exempt:
                    if prev_state == "CUSHION":
                        stay_time = current_time - self.hb_cushion_entry_time
                        if stay_time < 0.5:
                            self.score -= 100
                            self.popups.append({"text": "緩和ブレーキ -100", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "緩和ブレーキ"})
                    else:
                        self.score -= 100
                        self.popups.append({"text": "緩和ブレーキ -100", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "緩和ブレーキ"})

            self.hb_prev_notch = curr_n
        else:
            self.hb_prev_notch = 0
            self.hb_cushion_entry_time = 0.0
            self.hb_cushion_max_g = 0.0
            self.eb_applied = False

        # ★ V40.3: 駅ジャンプ制限を解除し、純粋な位置変化だけで転動を判定
        if self.bve_door == 1:
            if self.prev_door == 0:
                self.door_open_loc = self.bve_location
                self.roll_penalized = False
            else:
                if not self.roll_penalized:
                    if abs(self.bve_location - self.door_open_loc) >= 0.1: 
                        self.score -= 500
                        self.popups.append({"text": "転動 -500", "color": COLOR_B_EMG, "expire_time": current_time + 5.0, "type": "neg", "category": "転動"})
                        self.roll_penalized = True
        else:
            self.roll_penalized = False

        if in_station_zone and not self.bb_is_in_zone:
            self.bb_state = "IDLE"
            self.bb_apply_count = 0
            self.bb_release_count = 0
            self.bb_is_in_zone = True
            self.bb_evaluated = False
            self.bb_current_notch = self.bve_brk_notch
            self.bb_prev_stable_notch = self.bve_brk_notch
            self.bb_notch_change_time = current_time
            self.bb_is_stable = True
            
        elif not in_station_zone and self.bb_is_in_zone:
            self.bb_is_in_zone = False

        if self.bb_is_in_zone and self.bve_speed > 0.0 and not self.bb_evaluated:
            current_notch = self.bve_brk_notch
            if current_notch != self.bb_current_notch:
                self.bb_current_notch = current_notch
                self.bb_notch_change_time = current_time
                self.bb_is_stable = False
            if not self.bb_is_stable and (current_time - self.bb_notch_change_time) >= 0.3:
                self.bb_is_stable = True
                self.process_bb_transition(self.bb_current_notch)

        for key in self.key_states.keys():
            is_pressed = keyboard.is_pressed(key)
            if is_pressed and not self.key_states[key]:
                if key == '4':
                    self.is_speed_penalty = not self.is_speed_penalty
                    if self.is_speed_penalty: self.speed_penalty_score, self.last_penalty_time = 10, current_time
                elif key == '5':
                    self.show_graph = not self.show_graph
                    text = "テレメトリ ON" if self.show_graph else "テレメトリ OFF"
                    self.popups.append({"text": text, "color": COLOR_P, "expire_time": current_time + 3.0, "type": "pos", "category": "システム"})
            self.key_states[key] = is_pressed

        if self.is_speed_penalty:
            if current_time - self.last_penalty_time >= 1.0:
                self.speed_penalty_score += 3
                self.last_penalty_time = current_time

        self.popups = [p for p in self.popups if p["expire_time"] > current_time]

        if self.is_first_udp and self.bve_next_loc != -1.0:
            self.prev_door = self.bve_door
            self.prev_next_loc = self.bve_next_loc
            self.is_first_udp = False
            
        if self.bve_speed > 1.0:
            self.has_departed = True
            self.stop_notch_state = "IDLE"  # ★ 発車したら記録をリセット
            
        current_s = self.bve_time_ms // 1000
        target_s = self.bve_next_time // 1000
        diff_s = target_s - current_s
        
        if self.prev_next_loc != -1.0 and self.bve_next_loc != self.prev_next_loc:
            if self.prev_is_timing == 1 and self.prev_is_pass == 1 and not self.has_scored_time_this_station:
                if not self.has_jumped_current_station:
                    self.apply_time_score(self.prev_diff_s)
                
            self.is_first_station = False
            self.is_approaching = False
            self.is_stopped_out_of_range = False
            self.has_scored_time_this_station = False
            self.has_scored_stop_this_station = False
            
            if not just_jumped:
                self.has_jumped_current_station = False 
            
        if not self.is_approaching and self.bve_next_loc >= 0:
            if 0 < (self.bve_next_loc - self.bve_location) < (self.bve_train_length + STATION_MARGIN):
                self.is_approaching = True
                
        if self.is_approaching and self.bve_speed <= 0.1 and not self.has_scored_stop_this_station:
            d = self.bve_next_loc - self.bve_location
            if not (-self.bve_margin_f <= d <= self.bve_margin_b):
                self.is_stopped_out_of_range = True

        if self.prev_door == 1 and self.bve_door == 0:
            if self.prev_term == 0 and self.prev_is_timing == 1 and self.prev_is_pass == 0 and not self.has_scored_time_this_station:
                if not self.has_jumped_current_station:
                    self.apply_time_score(self.prev_diff_s)
                self.has_scored_time_this_station = True

        if self.prev_door == 0 and self.bve_door == 1:
            if self.bve_term == 1 and self.bve_is_timing == 1 and self.bve_is_pass == 0 and not self.has_scored_time_this_station:
                if not self.has_jumped_current_station:
                    self.apply_time_score(diff_s)
                self.has_scored_time_this_station = True
                
            is_zero_stop = False
            if not self.is_first_station and self.has_departed and not self.has_scored_stop_this_station:
                if not self.has_jumped_current_station:
                    is_zero_stop = self.apply_stop_score(self.bve_next_loc - self.bve_location)
                self.has_scored_stop_this_station = True
                
            if self.bb_is_in_zone and not self.bb_evaluated and not self.has_jumped_current_station:
                if not self.bb_is_stable:
                    self.bb_is_stable = True
                    self.process_bb_transition(self.bb_current_notch)

                self.bb_evaluated = True
                dist_to_stop = self.bve_next_loc - self.bve_location
                if -self.bve_margin_f <= dist_to_stop <= self.bve_margin_b:
                    # ★ V40.3: 停車時に強ブレーキ（STRONG）に入っていたら、基本制動のフラグを折る
                    if self.stop_notch_state == "STRONG":
                        self.bb_state = "FAILED"

                    if self.bb_state != "FAILED" and (self.bb_apply_count > 0 or self.bb_release_count > 0):
                        apply_ok = (BASIC_BRAKE_APPLY_LIMIT == 0) or (self.bb_apply_count <= BASIC_BRAKE_APPLY_LIMIT)
                        release_ok = (BASIC_BRAKE_RELEASE_LIMIT == 0) or (self.bb_release_count <= BASIC_BRAKE_RELEASE_LIMIT)
                        
                        if apply_ok and release_ok:
                            self.score += 500
                            apply_str = f"{BASIC_BRAKE_APPLY_LIMIT}段制動" if BASIC_BRAKE_APPLY_LIMIT > 0 else "階段制動"
                            release_str = f"{BASIC_BRAKE_RELEASE_LIMIT}段緩め" if BASIC_BRAKE_RELEASE_LIMIT > 0 else "階段緩め"
                            
                            self.popups.append({"text": f"{apply_str}{release_str}成功!!!", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "big", "category": "基本制動"})
                            self.popups.append({"text": "基本制動 +500", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "pos", "category": "基本制動"})
                            
                            if is_zero_stop:
                                self.score += 500
                                self.popups.append({"text": "ボーナス +500", "color": COLOR_N, "expire_time": current_time + 5.0, "type": "pos", "category": "ボーナス"})

        self.prev_next_loc = self.bve_next_loc
        self.prev_door = self.bve_door
        self.prev_is_pass = self.bve_is_pass
        self.prev_is_timing = self.bve_is_timing
        self.prev_term = self.bve_term
        self.prev_diff_s = diff_s

        true_map_limit = self.map_tail_limit 
        self.effective_limit = min(true_map_limit, self.bve_signal_limit)
        base_limit = self.effective_limit if self.effective_limit < 999.0 else 120.0 
        
        self.base_limit_type = "signal" if self.bve_signal_limit < true_map_limit else "map"

        if self.current_base_limit != base_limit:
            if self.current_base_limit != 1000.0:
                self.prev_base_limit = self.current_base_limit
                self.limit_changed_loc = self.bve_location
            self.current_base_limit = base_limit

        future_targets = []
        for loc, val in self.bve_map_limits:
            future_targets.append((loc, val, "map"))
            
        if self.bve_fwd_sig_loc > self.bve_location and self.bve_fwd_sig_limit < 999.0:
            future_targets.append((self.bve_fwd_sig_loc, self.bve_fwd_sig_limit, "signal"))
            
        future_targets.sort(key=lambda x: x[0])

        is_waiting_tail = (self.map_tail_limit < self.map_head_limit)
        self.dbg_is_wait = is_waiting_tail

        if is_waiting_tail:
            target_val = min(self.map_head_limit, self.bve_signal_limit)
            target_type = "signal" if self.bve_signal_limit < self.map_head_limit else "map"
            target_loc = self.bve_location + self.bve_clear_dist
        else:
            target_val = base_limit
            target_type = self.base_limit_type
            target_loc = self.bve_location

        active_red = None

        for loc, val, l_type in future_targets:
            if loc > self.bve_location:
                peak_speed = max(base_limit, target_val) if is_waiting_tail else base_limit
                v_apex = peak_speed
                entry_speed = base_limit
                
                if peak_speed > val: 
                    if is_waiting_tail and target_val > base_limit:
                        dist_of_hill = (loc - self.bve_location) - self.bve_clear_dist
                        if dist_of_hill < 0: dist_of_hill = 0
                        entry_speed = base_limit
                    else:
                        if self.prev_base_limit < base_limit:
                            dist_of_hill = loc - self.limit_changed_loc
                            entry_speed = self.prev_base_limit
                        else:
                            dist_of_hill = 0
                            entry_speed = base_limit
                            
                    if dist_of_hill > 0:
                        v_apex = calculate_apex_speed(entry_speed, peak_speed, dist_of_hill, val)
                    else:
                        v_apex = entry_speed
                
                v_assumed = max(val, min(peak_speed, v_apex))
                
                if val < target_val:
                    if (target_val - val) > 10.0:
                        available_dist = dist_of_hill if (is_waiting_tail and target_val > base_limit) else (loc - self.bve_location)
                        if available_dist < 0: available_dist = 0
                        
                        _, warn_dist_apex = calculate_warning_distance(v_apex, val)
                        if available_dist <= warn_dist_apex or v_apex <= val + 2.0:
                            target_val = val
                            target_type = l_type
                            target_loc = loc
                                
                if v_assumed <= val and target_val > val:
                    v_assumed = target_val
                            
                if val < v_assumed:
                    decel_dist, warn_dist = calculate_warning_distance(v_assumed, val)
                    dist_to_limit = loc - self.bve_location
                    if dist_to_limit <= warn_dist:
                        urgency = dist_to_limit - decel_dist
                        if not active_red or urgency < active_red['urgency']:
                            active_red = {'val': val, 'dist': dist_to_limit, 'decel_dist': decel_dist, 'urgency': urgency, 'type': l_type}

        active_blue = None
        
        if target_val > self.effective_limit and target_val < 999.0:
            is_capped = (target_val != min(self.map_head_limit, self.bve_signal_limit)) if is_waiting_tail else (target_val != base_limit)
            dist_for_blue = (target_loc - self.bve_location) if is_capped else max(1.0, self.bve_clear_dist)
            active_blue = {'val': target_val, 'dist': max(1.0, dist_for_blue), 'type': target_type}
            
        elif not is_waiting_tail and target_val < self.effective_limit and target_val < 999.0:
            dist_for_blue = target_loc - self.bve_location
            active_blue = {'val': target_val, 'dist': max(1.0, dist_for_blue), 'type': target_type}

        self.dbg_target_cap = target_val
        self.dbg_red = str(active_red['val']) if active_red else "None"
        self.dbg_blue = str(active_blue['val']) if active_blue else "None"

        self.blink_active = False
        self.target_type = self.base_limit_type

        if active_red:
            self.disp_limit = active_red['val']
            self.limit_color = COLOR_B_EMG
            self.blink_active = True
            self.target_type = active_red['type']
            if active_red['dist'] > active_red['decel_dist']:
                blink_cycle = 1.5
            else:
                progress = active_red['dist'] / max(1.0, active_red['decel_dist'])
                blink_cycle = 1.0 + 0.5 * max(0.0, progress)
                
        elif active_blue:
            self.disp_limit = active_blue['val']
            self.limit_color = COLOR_P
            self.blink_active = True
            self.target_type = active_blue['type']
            progress = active_blue['dist'] / max(1.0, self.bve_train_length)
            blink_cycle = 1.0 + 0.5 * max(0.0, min(1.0, progress))
            
        else:
            self.disp_limit = self.effective_limit
            self.limit_color = COLOR_WHITE

        if self.blink_active:
            self.blink_phase += dt / blink_cycle
            if self.blink_phase >= 1.0: 
                self.blink_phase -= 1.0
        else:
            self.blink_phase = 0.0
        
        self.update() 

    def draw_row(self, label_text, label_color, value_text, value_color, y, show_label=True, show_value=True):
        pass

    def draw_text_with_outline(self, painter, text, font, text_color, outline_color, x, y, align="left"):
        path = QPainterPath()
        fm = QFontMetrics(font)
        if align == "right": x -= fm.horizontalAdvance(text)
        elif align == "center": x -= fm.horizontalAdvance(text) / 2
        path.addText(x, y, font, text)
        pen = QPen(QColor(*outline_color), OUTLINE_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*text_color))
        painter.drawPath(path)

    def get_outline_color(self, t_color):
        return COLOR_OUTLINE_BLACK if t_color == COLOR_WHITE else COLOR_OUTLINE_WHITE

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self.height() / BASE_SCREEN_H if self.height() > 0 else 1.0
        painter.scale(scale, scale)
        logical_width = self.width() / scale

        pos_x_left, pos_x_right = MARGIN_LEFT, logical_width - MARGIN_RIGHT
        pos_x_label = pos_x_right - LABEL_WIDTH

        # ==========================================
        # ★ デバッグ表示
        # ==========================================
        dbg_y = 200
        painter.setFont(QFont("sans-serif", 14, QFont.Weight.Bold))
        
        if self.bb_is_in_zone:
            failed_str = "あり" if self.bb_state == "FAILED" else "なし"
            bb_debug_text = f"[BB] State: {self.bb_state} | Apply: {self.bb_apply_count} | Rel: {self.bb_release_count} | 込め直し: {failed_str}"
        else:
            bb_debug_text = "[BB] Out of Station Zone"

        jump_warn = " | !! JUMP DETECTED !!" if self.has_jumped_current_station else ""
        
        c_min_text = self.all_brk_texts[self.cushion_min] if 0 <= self.cushion_min < len(self.all_brk_texts) else f"B{self.cushion_min}"
        c_max_text = self.all_brk_texts[self.cushion_max] if 0 <= self.cushion_max < len(self.all_brk_texts) else f"B{self.cushion_max}"
        cushion_str = f"[CUSHION] 抑速: {'あり' if self.has_holding_brake else 'なし'} | 常用: {self.svc_brk_count}段 | 帯域: {c_min_text} - {c_max_text}"

        dbg_texts = [
            f"[DEBUG X-RAY]{jump_warn}",
            f"BrakeType: {self.bve_btype} | InitExempt: {IGNORE_INITIAL_BRAKE} | RelExempt: {IGNORE_RELEASE_BRAKE}",
            cushion_str,
            bb_debug_text,
            f"Target_Cap_Val: {self.dbg_target_cap}",
            f"ActiveBlue: {self.dbg_blue}  |  ActiveRed: {self.dbg_red}",
            f"CalcG: {self.bve_calc_g:.4f} G | MaxG: {self.max_stop_g:.4f} G | LastStop: {self.last_stop_g:.4f} G"
        ]
        
        for text in dbg_texts:
            path = QPainterPath()
            path.addText(20, dbg_y, QFont("sans-serif", 14, QFont.Weight.Bold), text)
            painter.setPen(QPen(QColor(*COLOR_BLACK), 3))
            painter.drawPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*COLOR_WHITE))
            painter.drawPath(path)
            dbg_y += 20

        # ==========================================
        # ★ テレメトリ・オシロスコープ描画
        # ==========================================
        if self.show_graph and len(self.g_history) > 1:
            graph_w = 800
            graph_h = 250
            graph_x = MARGIN_LEFT
            graph_y = BASE_SCREEN_H - graph_h - 50
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 200))
            painter.drawRect(int(graph_x), int(graph_y), int(graph_w), int(graph_h))
            
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            y_005 = graph_y + graph_h - (0.05 / 0.15) * graph_h
            y_010 = graph_y + graph_h - (0.10 / 0.15) * graph_h
            painter.drawLine(int(graph_x), int(y_005), int(graph_x + graph_w), int(y_005))
            painter.drawLine(int(graph_x), int(y_010), int(graph_x + graph_w), int(y_010))

            y_z1 = graph_y + graph_h - (0.015 / 0.15) * graph_h
            y_z2 = graph_y + graph_h - (0.055 / 0.15) * graph_h
            painter.setPen(QPen(QColor(200, 200, 0, 150), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(graph_x), int(y_z1), int(graph_x + graph_w), int(y_z1))
            painter.setPen(QPen(QColor(255, 50, 50, 150), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(graph_x), int(y_z2), int(graph_x + graph_w), int(y_z2))
            
            now = time.time()
            path_g = QPainterPath()
            path_notch = QPainterPath()
            
            first = True
            for h_data in self.g_history:
                t, g, notch, b_max = h_data
                x = graph_x + graph_w - ((now - t) / 10.0) * graph_w
                yg = graph_y + graph_h - (min(max(g, 0.0), 0.15) / 0.15) * graph_h
                
                n_norm = max(0.0, min(notch, b_max)) / max(1.0, float(b_max))
                yn = graph_y + graph_h - n_norm * graph_h
                
                x = max(graph_x, min(x, graph_x + graph_w))

                if first:
                    path_g.moveTo(x, yg)
                    path_notch.moveTo(x, yn)
                    first = False
                else:
                    path_g.lineTo(x, yg)
                    path_notch.lineTo(x, yn)
                    
            pen_g = QPen(QColor(0, 255, 100), 3)
            pen_g.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_g)
            painter.drawPath(path_g)
            
            pen_n = QPen(QColor(100, 150, 255), 2)
            pen_n.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_n)
            painter.drawPath(path_notch)
            
            painter.setFont(QFont("sans-serif", 12, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(int(graph_x + 10), int(graph_y + 25), "[TELEMETRY - 10 Seconds]  Green: Decel G (0.0-0.15) / Blue: Notch (0-Max)")
            painter.drawText(int(graph_x + 10), int(y_z1 - 5), "ZONE1 (0.015G)")
            painter.drawText(int(graph_x + 10), int(y_z2 - 5), "ZONE2 (0.055G)")

        # ==========================================
        # ★ ポップアップの描画 (順序固定ソート)
        # ==========================================
        display_list = []
        for p in self.popups:
            if p["type"] == "pos" or p["type"] == "neg":
                display_list.append(p)
        
        if self.is_speed_penalty:
            display_list.append({
                "text": f"速度制限超過 -{self.speed_penalty_score}", 
                "color": COLOR_B_EMG, 
                "type": "neg", 
                "category": "速度制限超過"
            })
            
        display_list.sort(key=lambda x: CATEGORY_ORDER.get(x.get("category", ""), 99))

        y_off = 0
        line_h = QFontMetrics(self.font_normal).height() + 10
        for p in display_list:
            self.draw_text_with_outline(painter, p["text"], self.font_normal, p["color"], self.get_outline_color(p["color"]), pos_x_left, MARGIN_TOP_NORMAL + y_off)
            y_off += line_h

        line_h_big = QFontMetrics(self.font_big).height() + 10
        for i, p in enumerate([p for p in self.popups if p["type"] == "big"]):
            fm = QFontMetrics(self.font_big)
            text_w = fm.horizontalAdvance(p["text"])
            bg_h = line_h_big
            bg_w = text_w + 60
            bg_x = pos_x_left - 20 
            visual_offset_y = 6 
            bg_y = MARGIN_TOP_BIG + (i * line_h_big) - fm.ascent() - (bg_h - fm.height()) / 2 - visual_offset_y
            
            gradient = QLinearGradient(bg_x, 0, bg_x + bg_w, 0)
            r, g, b, a = COLOR_BG
            gradient.setColorAt(0.0, QColor(r, g, b, a))   
            gradient.setColorAt(0.7, QColor(r, g, b, a))
            gradient.setColorAt(1.0, QColor(r, g, b, 0))   
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(int(bg_x), int(bg_y), int(bg_w), int(bg_h))
            self.draw_text_with_outline(painter, p["text"], self.font_big, p["color"], self.get_outline_color(p["color"]), pos_x_left, MARGIN_TOP_BIG + (i * line_h_big))

        ui_y = MARGIN_TOP_UI
        ui_step = 60
        
        def draw_row_local(label_text, label_color, value_text, value_color, y, show_label=True, show_value=True):
            fm = QFontMetrics(self.font_ui)
            value_width = fm.horizontalAdvance(value_text) if value_text else 0
            padding_x = 15
            if label_text: bg_x = pos_x_label - padding_x
            else: bg_x = pos_x_right - value_width - padding_x
                
            bg_w = (pos_x_right - bg_x) + padding_x
            bg_h = ui_step - 2 
            bg_y_offset = 5
            bg_y = y - fm.ascent() - (bg_h - fm.height()) / 2 - bg_y_offset
            
            gradient = QLinearGradient(bg_x, 0, bg_x + bg_w, 0)
            r, g, b, a = COLOR_BG
            gradient.setColorAt(0.0, QColor(r, g, b, 0))   
            gradient.setColorAt(0.15, QColor(r, g, b, a))  
            gradient.setColorAt(1.0, QColor(r, g, b, a))   
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(int(bg_x), int(bg_y), int(bg_w), int(bg_h))
            
            if label_text and show_label:
                self.draw_text_with_outline(painter, label_text, self.font_ui, label_color, self.get_outline_color(label_color), pos_x_label, y, "left")
            if value_text and show_value:
                self.draw_text_with_outline(painter, value_text, self.font_ui, value_color, self.get_outline_color(value_color), pos_x_right, y, "right")

        s = self.bve_time_ms // 1000
        h, m, sec = s // 3600, (s % 3600) // 60, s % 60
        draw_row_local("", COLOR_WHITE, f"{h:02}:{m:02}:{sec:02}", COLOR_WHITE, ui_y)
        ui_y += ui_step
        
        if self.bve_next_time > 0:
            current_s = self.bve_time_ms // 1000
            target_s = self.bve_next_time // 1000
            diff_s = target_s - current_s
            if diff_s >= 0:
                tm, ts = diff_s // 60, diff_s % 60
                draw_row_local("", COLOR_WHITE, f"{tm:02}:{ts:02}", COLOR_WHITE, ui_y)
            else:
                abs_diff = abs(diff_s)
                tm, ts = abs_diff // 60, abs_diff % 60
                draw_row_local("", COLOR_WHITE, f"-{tm:02}:{ts:02}", COLOR_B_EMG, ui_y)
        else:
            draw_row_local("", COLOR_WHITE, "--:--", COLOR_WHITE, ui_y)
        ui_y += ui_step
        
        draw_row_local("", COLOR_WHITE, f"{self.bve_speed:.1f} km/h", COLOR_WHITE, ui_y)
        ui_y += ui_step

        show_l, show_v = True, True
        if self.blink_active:
            is_type_changed = (self.target_type != self.base_limit_type)
            is_capped_blue = (self.limit_color == COLOR_P and self.disp_limit < self.effective_limit)

            if self.blink_phase < 0.5:
                l_text = "制限" if self.target_type == "map" else "信号"
                if is_type_changed and not is_capped_blue:
                    l_color = self.limit_color
                else:
                    l_color = COLOR_WHITE
                v_text = f"{int(self.disp_limit)} km/h" if self.disp_limit < 999.0 else "--- km/h"
                v_color = self.limit_color
            else:
                l_text = "制限" if self.base_limit_type == "map" else "信号"
                l_color = COLOR_WHITE
                v_text = f"{int(self.effective_limit)} km/h" if self.effective_limit < 999.0 else "--- km/h"
                v_color = COLOR_WHITE
        else:
            l_text = "制限" if self.base_limit_type == "map" else "信号"
            l_color = COLOR_WHITE
            if self.effective_limit >= 999.0:
                v_text = "--- km/h"
            elif self.effective_limit >= 0:
                v_text = f"{int(self.effective_limit)} km/h"
            else:
                v_text = ""
            v_color = COLOR_WHITE

        draw_row_local(l_text, l_color, v_text, v_color, ui_y, show_label=show_l, show_value=show_v)
        ui_y += ui_step

        if self.bve_next_loc >= 0:
            d = self.bve_next_loc - self.bve_location
            abs_d = abs(d) 
            if abs_d >= 99999.5: d_str = f"{abs_d/1000.0:.2f} km"
            elif abs_d >= 9999.95: d_str = f"{abs_d/1000.0:.3f} km"
            elif abs_d >= 4.95: d_str = f"{abs_d:.1f} m"
            else: d_str = f"{abs_d:.2f} m"
            if d < -0.01: d_str = "-" + d_str

            is_p = (self.bve_is_pass == 1)
            d_color = COLOR_WHITE
            if not is_p:
                if -self.bve_margin_f <= d <= self.bve_margin_b: d_color = COLOR_N 
                elif d < -self.bve_margin_f: d_color = COLOR_B_EMG 
            
            if self.bve_is_timing == 1:
                show_timing = int(time.time() / 5.0) % 2 == 0
                if is_p:
                    label_text = "採時" if show_timing else "通過"
                    label_col = COLOR_P
                else:
                    label_text = "採時" if show_timing else "停車"
                    label_col = COLOR_B_EMG
            else:
                label_text = "通過" if is_p else "停車"
                label_col = COLOR_P if is_p else COLOR_B_EMG
                
            draw_row_local(label_text, label_col, d_str, d_color, ui_y)
        else:
            draw_row_local("停車", COLOR_B_EMG, "--- m", COLOR_WHITE, ui_y)
        ui_y += ui_step

        draw_row_local("得点", COLOR_WHITE, str(self.score), COLOR_B_EMG if self.score < 0 else COLOR_WHITE, ui_y)
        ui_y += ui_step

        rev_color = COLOR_N
        if self.bve_rev_pos == 1: rev_color = COLOR_P
        elif self.bve_rev_pos == -1: rev_color = COLOR_B_EMG
        if "抜取" in self.bve_rev_text: rev_color = COLOR_B_EMG

        pow_color = COLOR_N
        if self.bve_pow_notch > 0: pow_color = COLOR_P
        elif self.bve_pow_notch < 0: pow_color = COLOR_B_SVC 

        brk_color = COLOR_N
        if self.bve_brk_notch > 0:
            if self.bve_brk_notch >= self.bve_brk_max or "非常" in self.bve_brk_text or "EB" in self.bve_brk_text.upper():
                brk_color = COLOR_B_EMG
            else: 
                brk_color = COLOR_B_SVC
        if "抜取" in self.bve_brk_text: brk_color = COLOR_B_EMG

        fm = QFontMetrics(self.font_ui)
        gap = 30       
        padding_x = 15 

        if self.is_single_handle:
            max_handle_w = max(self.max_pow_w, self.max_brk_w)
            total_text_w = self.max_rev_w + gap + max_handle_w
        else:
            total_text_w = self.max_rev_w + gap + self.max_pow_w + gap + self.max_brk_w

        scale_ratio = 1.0
        if total_text_w > LABEL_WIDTH:
            scale_ratio = LABEL_WIDTH / total_text_w

        bg_h_local = ui_step - 2
        bg_y_offset = 5
        offset_to_top = fm.ascent() + (bg_h_local - fm.height()) / 2.0 + bg_y_offset
        base_bg_top_y = ui_y - offset_to_top

        scaled_bg_h = bg_h_local * scale_ratio
        scaled_text_w = total_text_w * scale_ratio

        bg_w_global = scaled_text_w + padding_x * 2
        bg_x_global = pos_x_right - scaled_text_w - padding_x
        bg_y_global = base_bg_top_y

        gradient = QLinearGradient(bg_x_global, 0, bg_x_global + bg_w_global, 0)
        r, g, b, a = COLOR_BG
        gradient.setColorAt(0.0, QColor(r, g, b, 0))
        gradient.setColorAt(0.15, QColor(r, g, b, a))
        gradient.setColorAt(1.0, QColor(r, g, b, a))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(int(bg_x_global), int(bg_y_global), int(bg_w_global), int(scaled_bg_h))

        painter.save()
        painter.translate(pos_x_right, base_bg_top_y)
        painter.scale(scale_ratio, scale_ratio)

        local_baseline_y = offset_to_top

        if self.is_single_handle:
            if self.bve_pow_notch > 0 or self.bve_pow_notch < 0: 
                handle_text, handle_color = self.bve_pow_text, pow_color
            elif self.bve_brk_notch > 0: 
                handle_text, handle_color = self.bve_brk_text, brk_color
            else:
                handle_text, handle_color = self.bve_pow_text, COLOR_N
            x_handle = 0
            x_rev = -max_handle_w - gap
            self.draw_text_with_outline(painter, self.bve_rev_text, self.font_ui, rev_color, self.get_outline_color(rev_color), x_rev, local_baseline_y, "right")
            self.draw_text_with_outline(painter, handle_text, self.font_ui, handle_color, self.get_outline_color(handle_color), x_handle, local_baseline_y, "right")
            
        else:
            x_brk = 0
            x_pow = -self.max_brk_w - gap
            x_rev = -self.max_brk_w - gap - self.max_pow_w - gap
            self.draw_text_with_outline(painter, self.bve_rev_text, self.font_ui, rev_color, self.get_outline_color(rev_color), x_rev, local_baseline_y, "right")
            self.draw_text_with_outline(painter, self.bve_pow_text, self.font_ui, pow_color, self.get_outline_color(pow_color), x_pow, local_baseline_y, "right")
            self.draw_text_with_outline(painter, self.bve_brk_text, self.font_ui, brk_color, self.get_outline_color(brk_color), x_brk, local_baseline_y, "right")

        painter.restore()

        ui_y += scaled_bg_h + (ui_step - bg_h_local)
        
        if self.bve_gradient > 0:
            grad_str = f"+{self.bve_gradient:.1f} ‰"
        elif self.bve_gradient < 0:
            grad_str = f"{self.bve_gradient:.1f} ‰"
        else:
            grad_str = "0.0 ‰"
            
        draw_row_local("", COLOR_WHITE, grad_str, COLOR_WHITE, ui_y)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()
    sys.exit(app.exec())