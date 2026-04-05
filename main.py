import sys
import os
import time
import win32api
import win32gui
import win32con
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QFontDatabase, QColor, QFontMetrics, QPen
from PyQt6.QtNetwork import QUdpSocket, QHostAddress
import keyboard

from config import *
from scoring_logic import execute_retry, update_physics_and_scoring
from menu_ui import draw_menu
from hud_ui import draw_hud

def write_desktop_log(msg):
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    log_file = os.path.join(desktop, "debug.log")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except:
        pass

KERNING_OFFSETS = {
    "メ": 12,
    "°": 35
}

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(0, 0, 1920, 1080)

        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            family = QFontDatabase.applicationFontFamilies(font_id)[0]
            self.font_normal = QFont(family, 35, QFont.Weight.Bold)
            self.font_big = QFont(family, FONT_SIZE_BIG, QFont.Weight.Bold)
            self.font_ui = QFont(family, FONT_SIZE_UI, QFont.Weight.Bold)
            self.font_menu = QFont(family, 35, QFont.Weight.Bold)
            self.font_desc = QFont(family, 25, QFont.Weight.Bold)
        else:
            self.font_normal, self.font_big, self.font_ui, self.font_menu, self.font_desc = QFont("sans-serif", 35, QFont.Weight.Bold), QFont("sans-serif", 55, QFont.Weight.Bold), QFont("sans-serif", 40, QFont.Weight.Bold), QFont("sans-serif", 35, QFont.Weight.Bold), QFont("sans-serif", 25, QFont.Weight.Bold)

        self.popups = []
        self.score = 0
        self.is_scoring_mode = False 
        
        self.disp_settings = {
            "time": True, "time_left": True, "speed": True, "limit": True,
            "dist": True, "handle": True, "grad": True
        }
        self.settings_keys = list(self.disp_settings.keys())
        self.settings_names = ["現在時刻", "残り時間", "現在速度", "制限速度", "残距離", "ハンドル・レバーサ位置", "勾配"]
        
        self.is_speed_penalty = False
        self.speed_penalty_score = 0
        self.last_penalty_time = 0.0
        
        keys_to_track = ['0','1','2','3','4','5','6','7','8','9','f5','f6','f8','p','up','down','left','right','enter','backspace', 'h']
        self.key_states = {k: False for k in keys_to_track}
        self.show_help = False # ★ ヘルプ表示フラグ
        
        self.eb_applied = False
        self.smee_eb_frozen = False

        self.bve_btype = "Ecb"
        self.bcPressure = 0.0
        self.bpPressure = 0.0  
        self.bve_bp_initial = 490.0
        self.bcp_history = []
        self.bve_pressure_rates = []
        self.bve_max_pressure = 440.0
        self.eb_freeze_threshold = 20.0

        self.ecb_eb_accum_time = 0.0
        self.ecb_eb_cooling_time = 0.0

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
        self.jump_lock = False
        self.ignore_next_pass_score = False

        self.save_data = []  
        self.menu_state = 0   
        self.menu_cursor = 0  
        self.menu_scroll = 0  
        self.target_retry_idx = -1 
        self.menu_click_zones = [] 
        self.last_left_click = False

        self.menu_cursor_x = -1        
        self.dropdown_active = False  
        self.dropdown_cursor = 0      
        self.dropdown_scroll = 0      
        self.dropdown_options = []    
        self.dropdown_target = ""     
        self.dropdown_target_rule_idx = -1 
        
        self.setting_start_idx = 0
        self.setting_end_idx = -1
        self.setting_stop_distance = -1 
        self.setting_initial_brake = "NONE"
        
        self.current_scenario_id = -1
        self.needs_margin_recalc = True
        
        self.brake_rules = [
            {"end_idx": -1, "apply": "階段", "release": "階段"}
        ]
        
        self.summary_scroll = 0
        self.sub_cursor = 0
        self.sub_cursor_x = 0
        self.sub_scroll = 0
        
        self.input_buffer = ""
        self.input_mode_active = False
        self.input_fresh = True 
        
        self.keys_blocked = False
        self.hook_dict = {}
        
        self.debug_all_penalties = False
        
        self.pen_eb = True
        self.pen_jerk = True
        self.pen_limit = True
        self.pen_ats = True
        self.penalty_init_rules = [{"end_idx": -1, "apply": "ON①", "release": "ON①"}]
        self.init_summary_scroll = 0
        self.init_sub_scroll = 0
        self.init_sub_cursor = 0
        self.init_sub_cursor_x = 0
        
        self.menu_items_off = ["運転を再開する", "採点設定", "環境設定"]
        self.menu_items_on = ["運転を再開する", "採点を中断する", "選択した駅からやり直す", "環境設定"]
        
        self.rollback_msg = ""
        self.rollback_msg_timer = 0.0
        self.prev_frame_loc = 0.0

        self.blink_phase = 0.0
        self.blink_active = False
        self.last_update_time = 0.0
        self.show_graph = True 
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
        self.last_time_change_real = time.time()
        self.bve_gradient = 0.0
        self.bve_next_loc = -1.0
        self.bve_next_time = -1
        self.bve_is_pass = 0
        self.bve_is_timing = 0
        self.bve_margin_b = 5.0 
        self.bve_margin_f = 5.0 
        self.bve_door = 0
        self.bve_doordir = 1
        self.bve_term = 0

        self.station_list = []
        
        self.user_timing_overrides = {} 
        self.timing_cursor = 0
        self.timing_scroll = 0
        
        self.bve_rev_text = "切"
        self.bve_rev_pos = 0
        self.bve_pow_text = "N"
        self.bve_pow_notch = 0
        self.bve_brk_text = "N"
        self.bve_brk_notch = 0
        self.bve_brk_max = 8 
        self.is_single_handle = False
        self.all_brk_texts = []
        self.bve_current_station_name = "不明な駅"

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
        
        self.is_first_udp = True
        self.is_first_station = True
        self.prev_next_loc = -1.0
        self.prev_door = 0
        self.prev_doordir = 1
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
        self.hb_strong_entered = False
        self.dbg_is_wait = False
        self.dbg_target_cap = 1000.0
        self.dbg_red = "None"
        self.dbg_blue = "None"

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(16)

    def read_udp_data(self):
        latest_telemetry = None

        while self.udp_socket.hasPendingDatagrams():
            datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
            try:
                text = datagram.decode('utf-8')
                
                if text.startswith("STALIST:"):
                    sta_data = text.split(':', 1)[1]
                    new_list = []
                    if sta_data:
                        for sta_str in sta_data.split(','):
                            parts = sta_str.split('=')
                            if len(parts) >= 3:
                                s_name = parts[0]
                                s_timing = parts[1]
                                s_loc = float(parts[2])
                                s_rarr = int(parts[3]) if len(parts) >= 4 else -1
                                s_rdep = int(parts[4]) if len(parts) >= 5 else -1
                                s_def = int(parts[5]) if len(parts) >= 6 else -1
                                s_stop = int(parts[6]) if len(parts) >= 7 else 15000
                                # ★ 追加：受信パケットから is_pass フラグを読み取って保存
                                s_is_pass = (parts[7] == '1') if len(parts) >= 8 else False
                                new_list.append({
                                    "name": s_name, 
                                    "is_timing": (s_timing == '1'), 
                                    "location": s_loc,
                                    "raw_arr": s_rarr,
                                    "raw_dep": s_rdep,
                                    "def_time": s_def,
                                    "stop_time": s_stop,
                                    "is_pass": s_is_pass
                                })
                    if new_list:
                        self.station_list = new_list
                else:
                    latest_telemetry = text
            except Exception:
                pass

        if latest_telemetry:
            parts = latest_telemetry.split(',')
            for part in parts:
                try:
                    if part.startswith("SCENARIO_ID:"):
                        new_id = int(part.split(':')[1])
                        if self.current_scenario_id != new_id:
                            if self.current_scenario_id != -1:
                                self.is_scoring_mode = False
                                self.score = 0
                                self.save_data.clear()
                                self.popups.clear()
                                self.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}]
                                self.setting_start_idx = 0
                                self.setting_end_idx = -1
                                self.setting_stop_distance = -1
                                self.setting_initial_brake = "NONE"
                                self.input_buffer = ""
                                if self.menu_state != 0:
                                    self.menu_state = 0
                                self.user_timing_overrides.clear()
                            self.needs_margin_recalc = True
                            self.current_scenario_id = new_id
                            
                    elif part.startswith("SPEED:"): self.bve_speed = float(part.split(':')[1])
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
                    elif part.startswith("DOORDIR:"): self.bve_doordir = int(part.split(':')[1])
                    elif part.startswith("TERM:"): self.bve_term = int(part.split(':')[1])
                    elif part.startswith("STATNAME:"): self.bve_current_station_name = part.split(':', 1)[1]
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
                    elif part.startswith("HTYPE:"): self.is_single_handle = (int(part.split(':')[1]) == 1)
                    elif part.startswith("ALLTXT:"):
                        vals = part.split(':')
                        if len(vals) >= 4:
                            rev_list = [s.strip() for s in vals[1].split('_') if s.strip()]
                            pow_list = [s.strip() for s in vals[2].split('_') if s.strip()]
                            brk_list = [s.strip() for s in vals[3].split('_') if s.strip()]
                            self.all_brk_texts = brk_list
                            
                            fm_local = QFontMetrics(self.font_ui)
                            
                            def get_adjusted_max_w(text_list, apply_offset=False):
                                adjusted_widths = []
                                for s in text_list:
                                    w = fm_local.horizontalAdvance(s)
                                    if apply_offset:
                                        for suffix, offset in KERNING_OFFSETS.items():
                                            if s.endswith(suffix):
                                                w -= offset
                                                break
                                    adjusted_widths.append(w)
                                return max(adjusted_widths + [40]) if adjusted_widths else 40

                            brk_eval_list = brk_list[1:] if self.is_single_handle and len(brk_list) > 1 else brk_list
                            
                            self.max_rev_w = get_adjusted_max_w(rev_list, apply_offset=False)
                            self.max_pow_w = get_adjusted_max_w(pow_list, apply_offset=False)
                            self.max_brk_w = get_adjusted_max_w(brk_eval_list, apply_offset=True)
                            
                    elif part.startswith("SIGLIMIT:"): self.bve_signal_limit = float(part.split(':')[1])
                    elif part.startswith("TRAINLEN:"): 
                        self.bve_train_length = max(float(part.split(':')[1]), 20.0)
                        if getattr(self, 'needs_margin_recalc', False) or self.setting_stop_distance == -1:
                            self.setting_stop_distance = int(self.bve_train_length) * 2
                            self.needs_margin_recalc = False

                    elif part.startswith("MAPLIMITS:"):
                        limits_str = part.split(':', 1)[1]
                        parsed_limits = []
                        if limits_str:
                            for pair in limits_str.split('_'):
                                try:
                                    l, v = pair.split('=')
                                    parsed_limits.append((float(l), float(v)))
                                except: pass
                        self.bve_map_limits = parsed_limits
                            
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
                    elif part.startswith("BCP:"): self.bcPressure = float(part.split(':')[1])
                    elif part.startswith("BPP:"):
                        vals = part.split(':')
                        if len(vals) >= 2: self.bpPressure = float(vals[1])
                        if len(vals) >= 3: self.bve_bp_initial = float(vals[2])
                    elif part.startswith("PRATES:"):
                        vals = part.split(':')
                        if len(vals) >= 3 and vals[1]:
                            rates = [float(x) for x in vals[1].split('_')]
                            self.bve_pressure_rates = rates
                            self.bve_max_pressure = float(vals[2])
                            search_end = min(len(rates), self.cab_brk_count + 1)
                            min_valid = 1
                            found_min_valid = False
                            invalid_count = 0
                            for i in range(1, search_end):
                                if rates[i] <= 0.0: invalid_count += 1
                                else:
                                    if not found_min_valid:
                                        min_valid = i
                                        found_min_valid = True
                            self.cushion_min = min_valid
                            self.svc_brk_count = self.cab_brk_count - invalid_count
                            if self.svc_brk_count <= 3: self.cushion_count = 1
                            else: self.cushion_count = (self.svc_brk_count - 2) // 2
                            self.cushion_max = self.cushion_min + self.cushion_count - 1
                            if min_valid < len(rates): self.eb_freeze_threshold = (self.bve_max_pressure * rates[min_valid]) - 5.0
                            else: self.eb_freeze_threshold = 20.0
                            if self.eb_freeze_threshold < 5.0: self.eb_freeze_threshold = 5.0
                except Exception: continue 

    def is_station_timing(self, sta_idx):
        if sta_idx == self.setting_start_idx:
            return False 
        if sta_idx in self.user_timing_overrides:
            return self.user_timing_overrides[sta_idx] 
        if 0 <= sta_idx < len(self.station_list):
            return self.station_list[sta_idx].get("is_timing", False) 
        return False
        
    def get_timing_target_stas(self):
        if not self.station_list: return []
        end_idx = self.setting_end_idx if self.setting_end_idx != -1 else self.get_actual_terminal_idx()
        if end_idx == -1 or end_idx >= len(self.station_list):
            end_idx = len(self.station_list) - 1
        return [i for i in range(len(self.station_list)) if self.setting_start_idx <= i <= end_idx]

    def get_actual_terminal_idx(self):
        if not self.station_list: return -1
        timing_stas = [i for i, s in enumerate(self.station_list) if s.get("is_timing", False)]
        return timing_stas[-1] if timing_stas else -1

    def get_current_brake_rule(self):
        if not self.is_scoring_mode or not self.station_list:
            return "制動：階段 / 緩め：階段"

        next_loc = self.bve_next_loc
        actual_terminal_idx = self.get_actual_terminal_idx()
        overall_end_loc = self.station_list[actual_terminal_idx]["location"] if 0 <= actual_terminal_idx < len(self.station_list) else -1.0
        
        if next_loc < 0 or next_loc > overall_end_loc:
            return "制動：階段 / 緩め：階段"

        rule = self.brake_rules[0]
        current_loc = self.bve_location
        
        for r in self.brake_rules:
            end_sta_idx = r["end_idx"]
            end_loc = self.station_list[end_sta_idx]["location"] if 0 <= end_sta_idx < len(self.station_list) else overall_end_loc
            
            if current_loc <= end_loc:
                rule = r
                break
                
        if rule["apply"] == "OFF":
            return "OFF"
        
        apply_text = rule["apply"]
        release_text = rule["release"]
        return f"制動：{apply_text} / 緩め：{release_text}"

    def toggle_menu(self, is_bve_advancing):
        if self.menu_state == 0:
            self.menu_state = 1
            self.menu_cursor = 0
            self.menu_cursor_x = -1
            if is_bve_advancing and self.bve_hwnd:
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYDOWN, 0x50, 0)
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYUP, 0x50, 0)
        else:
            if self.menu_state == 5 and self.input_mode_active:
                self.finalize_margin_input()
            self.menu_state = 0
            self.input_mode_active = False
            if not is_bve_advancing and self.bve_hwnd:
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYDOWN, 0x50, 0)
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYUP, 0x50, 0)

    def finalize_margin_input(self):
        if self.input_mode_active:
            if self.input_fresh or not self.input_buffer:
                self.input_mode_active = False
                return
            try:
                val = int(self.input_buffer)
                tl = int(self.bve_train_length)
                self.setting_stop_distance = max(tl, val)
            except ValueError:
                pass
            self.input_mode_active = False

    def handle_menu_up(self):
        if self.menu_state == 5:
            if getattr(self, 'input_mode_active', False): return
            if self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 1:
                self.summary_scroll = max(0, getattr(self, 'summary_scroll', 0) - 1)
                return
            if getattr(self, 'menu_cursor_x', 0) == -1:
                self.menu_cursor -= 1
                if self.menu_cursor < 0: self.menu_cursor = 5
            return
        elif self.menu_state == 6:
            if self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == 1:
                self.init_summary_scroll = max(0, getattr(self, 'init_summary_scroll', 0) - 1)
                return
            if getattr(self, 'menu_cursor_x', 0) == -1:
                self.menu_cursor -= 1
                if self.menu_cursor < 0: self.menu_cursor = 6
            return

        if self.menu_state in [7, 9]:
            rules = getattr(self, 'brake_rules', []) if self.menu_state == 7 else getattr(self, 'penalty_init_rules', [])
            sub_c = getattr(self, 'sub_cursor', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor', 0)
            sub_s = getattr(self, 'sub_scroll', 0) if self.menu_state == 7 else getattr(self, 'init_sub_scroll', 0)
            sub_x = getattr(self, 'sub_cursor_x', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor_x', 0)

            row_undo = len(rules) if len(rules) > 1 and self.menu_state == 7 else -1
            row_done = len(rules) + 1 if len(rules) > 1 and self.menu_state == 7 else len(rules)
            
            old_sub_c = sub_c
            sub_c -= 1
            if sub_c == row_undo and row_undo != -1: sub_c -= 1
            if sub_c < 0: sub_c = row_done
            
            if sub_c < len(rules):
                if sub_c < sub_s: sub_s = sub_c

            if self.menu_state == 7:
                if old_sub_c != row_done and old_sub_c != row_undo and sub_c < len(rules):
                    old_is_last = (old_sub_c == len(rules) - 1)
                    new_is_last = (sub_c == len(rules) - 1)
                    if old_is_last and not new_is_last: sub_x = max(0, sub_x - 1)
                    elif not old_is_last and new_is_last: sub_x = min(2, sub_x + 1)
                
                self.sub_cursor = sub_c
                self.sub_scroll = sub_s
                self.sub_cursor_x = sub_x if sub_c < len(rules) else 0
            else:
                self.init_sub_cursor = sub_c
                self.init_sub_scroll = sub_s
                self.init_sub_cursor_x = sub_x if sub_c < len(rules) else 0
            return

        if self.menu_state == 8:
            targets = self.get_timing_target_stas() if hasattr(self, 'get_timing_target_stas') else []
            if not targets: return
            if getattr(self, 'timing_cursor', 0) > 1: self.timing_cursor -= 1
            if getattr(self, 'timing_cursor', 0) == 1 and getattr(self, 'timing_scroll', 0) > 0:
                self.timing_scroll = 0
            elif getattr(self, 'timing_cursor', 0) < len(targets) and getattr(self, 'timing_cursor', 0) < getattr(self, 'timing_scroll', 0):
                self.timing_scroll = getattr(self, 'timing_cursor', 0)
            return

        self.menu_cursor -= 1
        if self.menu_state == 1:
            items = getattr(self, 'menu_items_on', []) if getattr(self, 'is_scoring_mode', False) else getattr(self, 'menu_items_off', [])
            if self.menu_cursor < 0: self.menu_cursor = len(items) - 1
        elif self.menu_state == 2:
            if self.menu_cursor < 0: self.menu_cursor = 0
            if self.menu_cursor < getattr(self, 'menu_scroll', 0): self.menu_scroll = self.menu_cursor
        elif self.menu_state == 3:
            if self.menu_cursor < 0: self.menu_cursor = 1
        elif self.menu_state == 4:
            if self.menu_cursor < 0: self.menu_cursor = 6

    def handle_menu_down(self):
        if self.menu_state == 5:
            if getattr(self, 'input_mode_active', False): return
            if self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 1:
                vis_rules = min(3, len(getattr(self, 'brake_rules', [])))
                if getattr(self, 'summary_scroll', 0) + vis_rules < len(getattr(self, 'brake_rules', [])):
                    self.summary_scroll += 1
                return
            if getattr(self, 'menu_cursor_x', 0) == -1:
                self.menu_cursor += 1
                if self.menu_cursor > 5: self.menu_cursor = 0
            return
        elif self.menu_state == 6:
            if self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == 1:
                vis_rules = min(3, len(getattr(self, 'penalty_init_rules', [])))
                if getattr(self, 'init_summary_scroll', 0) + vis_rules < len(getattr(self, 'penalty_init_rules', [])):
                    self.init_summary_scroll += 1
                return
            if getattr(self, 'menu_cursor_x', 0) == -1:
                self.menu_cursor += 1
                if self.menu_cursor > 6: self.menu_cursor = 0
            return
            
        if self.menu_state in [7, 9]:
            rules = getattr(self, 'brake_rules', []) if self.menu_state == 7 else getattr(self, 'penalty_init_rules', [])
            sub_c = getattr(self, 'sub_cursor', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor', 0)
            sub_s = getattr(self, 'sub_scroll', 0) if self.menu_state == 7 else getattr(self, 'init_sub_scroll', 0)
            sub_x = getattr(self, 'sub_cursor_x', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor_x', 0)

            row_undo = len(rules) if len(rules) > 1 and self.menu_state == 7 else -1
            row_done = len(rules) + 1 if len(rules) > 1 and self.menu_state == 7 else len(rules)
            
            old_sub_c = sub_c
            sub_c += 1
            if row_undo != -1 and sub_c == row_undo: pass 
            elif row_undo == -1 and sub_c == len(rules): sub_c = row_done
            
            if sub_c > row_done: sub_c = 0
            
            if sub_c < len(rules):
                if sub_c >= sub_s + 5: sub_s = sub_c - 5 + 1

            if self.menu_state == 7:
                if old_sub_c != row_done and old_sub_c != row_undo and sub_c < len(rules):
                    old_is_last = (old_sub_c == len(rules) - 1)
                    new_is_last = (sub_c == len(rules) - 1)
                    if old_is_last and not new_is_last: sub_x = max(0, sub_x - 1)
                    elif not old_is_last and new_is_last: sub_x = min(2, sub_x + 1)
                
                self.sub_cursor = sub_c
                self.sub_scroll = sub_s
                self.sub_cursor_x = sub_x if sub_c < len(rules) else 0
            else:
                self.init_sub_cursor = sub_c
                self.init_sub_scroll = sub_s
                self.init_sub_cursor_x = sub_x if sub_c < len(rules) else 0
            return

        if self.menu_state == 8:
            targets = self.get_timing_target_stas() if hasattr(self, 'get_timing_target_stas') else []
            if not targets: return
            max_cursor = len(targets) 
            if getattr(self, 'timing_cursor', 0) < max_cursor: self.timing_cursor += 1
            if getattr(self, 'timing_cursor', 0) < len(targets):
                if getattr(self, 'timing_cursor', 0) >= getattr(self, 'timing_scroll', 0) + 6:
                    self.timing_scroll = getattr(self, 'timing_cursor', 0) - 6 + 1
            return

        self.menu_cursor += 1
        if self.menu_state == 1:
            items = getattr(self, 'menu_items_on', []) if getattr(self, 'is_scoring_mode', False) else getattr(self, 'menu_items_off', [])
            if self.menu_cursor >= len(items): self.menu_cursor = 0
        elif self.menu_state == 2:
            max_idx = max(0, len(getattr(self, 'save_data', [])) - 1)
            if self.menu_cursor > max_idx: self.menu_cursor = max_idx
            if self.menu_cursor >= getattr(self, 'menu_scroll', 0) + 7:
                self.menu_scroll = self.menu_cursor - 7 + 1
        elif self.menu_state == 3:
            if self.menu_cursor > 1: self.menu_cursor = 0
        elif self.menu_state == 4:
            if self.menu_cursor > 6: self.menu_cursor = 0

    def handle_menu_left(self):
        if self.menu_state == 5:
            if getattr(self, 'input_mode_active', False): return
            self.menu_cursor_x = max(-1, getattr(self, 'menu_cursor_x', 0) - 1)
        elif self.menu_state == 6:
            self.menu_cursor_x = max(-1, getattr(self, 'menu_cursor_x', 0) - 1)
        elif self.menu_state == 7:
            if getattr(self, 'sub_cursor', 0) < len(getattr(self, 'brake_rules', [])):
                self.sub_cursor_x = max(0, getattr(self, 'sub_cursor_x', 0) - 1)
        elif self.menu_state == 9:
            if getattr(self, 'init_sub_cursor', 0) < len(getattr(self, 'penalty_init_rules', [])):
                self.init_sub_cursor_x = max(0, getattr(self, 'init_sub_cursor_x', 0) - 1)

    def handle_menu_right(self):
        if self.menu_state == 5:
            if getattr(self, 'input_mode_active', False): return
            if self.menu_cursor == 0: max_x = 1
            elif self.menu_cursor == 1: max_x = 0
            elif self.menu_cursor == 2: max_x = 0 
            elif self.menu_cursor == 4: max_x = 1
            else: max_x = -1
            self.menu_cursor_x = min(max_x, getattr(self, 'menu_cursor_x', 0) + 1)
            
        elif self.menu_state == 6:
            if self.menu_cursor == 0: max_x = -1
            elif 1 <= self.menu_cursor <= 4: max_x = 0
            elif self.menu_cursor == 5: max_x = 1
            else: max_x = -1
            self.menu_cursor_x = min(max_x, getattr(self, 'menu_cursor_x', 0) + 1)

        elif self.menu_state in [7, 9]:
            rules = getattr(self, 'brake_rules', []) if self.menu_state == 7 else getattr(self, 'penalty_init_rules', [])
            sub_c = getattr(self, 'sub_cursor', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor', 0)
            sub_c_x = getattr(self, 'sub_cursor_x', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor_x', 0)

            if sub_c < len(rules):
                rule = rules[sub_c]
                is_last = (sub_c == len(rules) - 1)
                
                if rule.get("apply", "OFF") == "OFF" and self.menu_state == 7: max_x = 1 if is_last else 0
                else: max_x = 2 if is_last and self.menu_state == 7 else 1
                
                if self.menu_state == 7: self.sub_cursor_x = min(max_x, sub_c_x + 1)
                else: self.init_sub_cursor_x = min(max_x, sub_c_x + 1)

    def handle_menu_enter(self, is_bve_advancing):
        if self.menu_state == 1:
            items = getattr(self, 'menu_items_on', []) if getattr(self, 'is_scoring_mode', False) else getattr(self, 'menu_items_off', [])
            selected = items[self.menu_cursor]
            if selected == "運転を再開する": self.toggle_menu(is_bve_advancing)
            elif selected == "採点設定":
                self.menu_state = 5
                self.menu_cursor = 0
                self.menu_cursor_x = -1
            elif selected == "採点を中断する":
                self.is_scoring_mode = False
                getattr(self, 'popups', []).clear()
                self.toggle_menu(is_bve_advancing)
            elif selected == "選択した駅からやり直す":
                if len(getattr(self, 'save_data', [])) > 0:
                    self.menu_state = 2
                    self.menu_cursor = 0
                    self.menu_scroll = 0
            elif "環境設定" in selected:
                self.menu_state = 4
                self.menu_cursor = 0
        elif self.menu_state == 2:
            if len(getattr(self, 'save_data', [])) > 0:
                self.target_retry_idx = self.menu_cursor
                self.menu_state = 3
                self.menu_cursor = 0
        elif self.menu_state == 3:
            if self.menu_cursor == 0: execute_retry(self, getattr(self, 'target_retry_idx', -1), is_bve_advancing)
            elif self.menu_cursor == 1: 
                self.menu_state = 2
                self.menu_cursor = getattr(self, 'target_retry_idx', 0)
        elif self.menu_state == 4:
            if self.menu_cursor <= 6:
                key = getattr(self, 'settings_keys', [])[self.menu_cursor]
                getattr(self, 'disp_settings', {})[key] = not getattr(self, 'disp_settings', {})[key]

        elif self.menu_state == 5:
            valid_stas = []
            if getattr(self, 'station_list', []):
                valid_stas.append({"idx": 0, "name": self.station_list[0]["name"]})
                for i, s in enumerate(self.station_list):
                    if i > 0 and not s.get("is_pass", False):
                        valid_stas.append({"idx": i, "name": s["name"]})

            if self.menu_cursor == 0 and getattr(self, 'menu_cursor_x', 0) >= 0:
                self.dropdown_active = True
                self.dropdown_cursor = 0
                self.dropdown_scroll = 0
                self.dropdown_target = "start_sta" if getattr(self, 'menu_cursor_x', 0) == 0 else "end_sta"
                actual_terminal_idx = self.get_actual_terminal_idx() if hasattr(self, 'get_actual_terminal_idx') else -1
                
                if self.dropdown_target == "start_sta":
                    e_idx = getattr(self, 'setting_end_idx', -1) if getattr(self, 'setting_end_idx', -1) != -1 else actual_terminal_idx
                    opts = [s for s in valid_stas if s["idx"] < e_idx]
                else:
                    s_idx = getattr(self, 'setting_start_idx', 0)
                    opts = [s for s in valid_stas if s["idx"] > s_idx]
                self.dropdown_options = opts if opts else [{"idx": -1, "name": "選択可能駅なし"}]
                
            elif self.menu_cursor == 1 and getattr(self, 'menu_cursor_x', 0) == 0:
                if not getattr(self, 'input_mode_active', False):
                    self.input_mode_active = True
                    self.input_buffer = "" 
                else:
                    self.finalize_margin_input()
            
            elif self.menu_cursor == 2 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.menu_state = 8
                self.timing_scroll = 0
                targets = self.get_timing_target_stas() if hasattr(self, 'get_timing_target_stas') else []
                self.timing_cursor = 1 if (targets and len(targets) > 1) else len(targets)
            
            elif self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.menu_state = 7
                self.sub_cursor = len(getattr(self, 'brake_rules', [])) - 1 
                self.sub_cursor_x = 0
                self.sub_scroll = max(0, len(getattr(self, 'brake_rules', [])) - 5)
            elif self.menu_cursor == 5: 
                self.menu_state = 6
                self.menu_cursor = 0
                self.menu_cursor_x = -1
                
                while len(getattr(self, 'penalty_init_rules', [])) < len(getattr(self, 'brake_rules', [])):
                    idx = len(getattr(self, 'penalty_init_rules', []))
                    default_apply = "OFF" if getattr(self, 'brake_rules', [])[idx].get("apply", "") == "1段" else "ON①"
                    getattr(self, 'penalty_init_rules', []).append({"apply": default_apply, "release": "ON①"})
                if len(getattr(self, 'penalty_init_rules', [])) > len(getattr(self, 'brake_rules', [])):
                    self.penalty_init_rules = getattr(self, 'penalty_init_rules', [])[:len(getattr(self, 'brake_rules', []))]
                    
                for i, p_rule in enumerate(getattr(self, 'penalty_init_rules', [])):
                    if i < len(getattr(self, 'brake_rules', [])):
                        if getattr(self, 'brake_rules', [])[i].get("apply", "") == "1段" and p_rule.get("apply", "") == "ON①":
                            p_rule["apply"] = "OFF"

        elif self.menu_state == 6:
            if self.menu_cursor == 1 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.pen_ats = not getattr(self, 'pen_ats', True)
            elif self.menu_cursor == 2 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.pen_limit = not getattr(self, 'pen_limit', True)
            elif self.menu_cursor == 3 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.pen_jerk = not getattr(self, 'pen_jerk', True)
            elif self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.pen_eb = not getattr(self, 'pen_eb', True)
            elif self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == 0:
                self.menu_state = 9
                self.init_sub_cursor = 0 
                self.init_sub_cursor_x = 0
                self.init_sub_scroll = max(0, len(getattr(self, 'penalty_init_rules', [])) - 5)
            elif self.menu_cursor == 6:
                self.is_scoring_mode = True
                self.score = 0
                getattr(self, 'save_data', []).clear()
                getattr(self, 'popups', []).clear()
                self.debug_all_penalties = False
                
                self.expected_jump = True

                self.is_first_station = True
                self.has_departed = False
                self.is_approaching = False
                self.is_stopped_out_of_range = False
                self.has_scored_time_this_station = False
                self.has_scored_stop_this_station = False
                
                start_loc = 0.0
                start_sta_name = "不明な駅"
                target_time_ms = -1
                retry_cmd = "" 
                
                if getattr(self, 'station_list', []) and 0 <= getattr(self, 'setting_start_idx', 0) < len(getattr(self, 'station_list', [])):
                    st = self.station_list[self.setting_start_idx]
                    start_loc = st.get("location", 0.0)
                    start_sta_name = st.get("name", "不明な駅")
                    
                    raw_arr = st.get("raw_arr", -1)
                    raw_dep = st.get("raw_dep", -1)
                    def_t = st.get("def_time", -1)
                    stop_t = st.get("stop_time", 15000)
                    
                    if self.setting_start_idx == 0:
                        retry_cmd = f"JUMP_STA:0"
                        if def_t >= 0: target_time_ms = def_t
                        else: target_time_ms = max(0, getattr(self, 'bve_time_ms', 0))
                    else:
                        if raw_arr >= 0: target_time_ms = raw_arr
                        else:
                            calc_t = (raw_dep - stop_t) if raw_dep >= 0 else -1
                            if calc_t >= 0 and def_t >= 0: target_time_ms = min(calc_t, def_t)
                            elif calc_t >= 0: target_time_ms = calc_t
                            elif def_t >= 0: target_time_ms = def_t
                        
                        if target_time_ms < 0: target_time_ms = max(0, getattr(self, 'bve_time_ms', 0))
                        retry_cmd = f"RETRY:{start_loc}:{target_time_ms}"
                
                self.is_official_jumping = True
                self.jump_start_real_time = time.time()
                self.expected_target_loc = start_loc
                self.expected_target_time = target_time_ms

                getattr(self, 'save_data', []).append({
                    "loc": start_loc,
                    "time_ms": target_time_ms,
                    "score": 0,
                    "target_loc": start_loc, 
                    "station_name": start_sta_name,
                    "stop_error": 0.0
                })
                
                if retry_cmd != "":
                    self.udp_socket.writeDatagram(retry_cmd.encode('utf-8'), QHostAddress.SpecialAddress.LocalHost, 54322)
                
                self.toggle_menu(is_bve_advancing)

        elif self.menu_state in [7, 9]:
            rules = getattr(self, 'brake_rules', []) if self.menu_state == 7 else getattr(self, 'penalty_init_rules', [])
            sub_c = getattr(self, 'sub_cursor', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor', 0)
            sub_c_x = getattr(self, 'sub_cursor_x', 0) if self.menu_state == 7 else getattr(self, 'init_sub_cursor_x', 0)

            row_undo = len(rules) if len(rules) > 1 and self.menu_state == 7 else -1
            row_done = len(rules) + 1 if len(rules) > 1 and self.menu_state == 7 else len(rules)
            
            if sub_c == row_undo and row_undo != -1:
                if len(rules) > 1:
                    rules.pop()
                    rules[-1]["end_idx"] = -1
                    if self.menu_state == 7:
                        if self.sub_cursor >= len(rules): self.sub_cursor -= 1
                        if getattr(self, 'sub_scroll', 0) > 0 and len(rules) - getattr(self, 'sub_scroll', 0) < 5: self.sub_scroll = max(0, len(rules) - 5)
                        if getattr(self, 'summary_scroll', 0) > 0 and len(rules) - getattr(self, 'summary_scroll', 0) < 3: self.summary_scroll = max(0, len(rules) - 3)
            elif sub_c == row_done:
                self.menu_state = 6 if self.menu_state == 9 else 5
            elif sub_c < len(rules):
                is_last = (sub_c == len(rules) - 1)
                self.dropdown_active = True
                self.dropdown_cursor = 0
                self.dropdown_scroll = 0
                self.dropdown_target_rule_idx = sub_c
                
                if is_last and self.menu_state == 7:
                    if sub_c_x == 0: 
                        self.dropdown_target = "sub_end_sta"
                        s_idx = getattr(self, 'setting_start_idx', 0) if sub_c == 0 else rules[sub_c-1].get("end_idx", -1)
                        
                        valid_stas = []
                        if getattr(self, 'station_list', []):
                            valid_stas.append({"idx": 0, "name": self.station_list[0]["name"]})
                            for i, s in enumerate(self.station_list):
                                if i > 0 and not s.get("is_pass", False):
                                    valid_stas.append({"idx": i, "name": s["name"]})

                        actual_terminal_idx = self.get_actual_terminal_idx() if hasattr(self, 'get_actual_terminal_idx') else -1
                        e_overall = getattr(self, 'setting_end_idx', -1) if getattr(self, 'setting_end_idx', -1) != -1 else actual_terminal_idx
                        
                        opts = [s for s in valid_stas if s["idx"] > s_idx and s["idx"] <= e_overall]
                        self.dropdown_options = opts if opts else [{"idx": -1, "name": "選択可能駅なし"}]
                    elif sub_c_x == 1:
                        self.dropdown_target = "sub_apply"
                        self.dropdown_options = [{"idx": 0, "name": "階段"}, {"idx": 1, "name": "1段"}, {"idx": 2, "name": "2段"}, {"idx": 3, "name": "3段"}, {"idx": 4, "name": "OFF"}]
                    elif sub_c_x == 2:
                        self.dropdown_target = "sub_release"
                        self.dropdown_options = [{"idx": 0, "name": "階段"}, {"idx": 1, "name": "1段"}, {"idx": 2, "name": "2段"}, {"idx": 3, "name": "3段"}]
                else:
                    if sub_c_x == 0:
                        self.dropdown_target = "sub_apply" if self.menu_state == 7 else "init_sub_apply"
                        if self.menu_state == 7: self.dropdown_options = [{"idx": 0, "name": "階段"}, {"idx": 1, "name": "1段"}, {"idx": 2, "name": "2段"}, {"idx": 3, "name": "3段"}, {"idx": 4, "name": "OFF"}]
                        else: 
                            if getattr(self, 'brake_rules', [])[sub_c].get("apply", "") == "1段":
                                self.dropdown_options = [{"idx": 0, "name": "ON②"}, {"idx": 1, "name": "OFF"}]
                            else:
                                self.dropdown_options = [{"idx": 0, "name": "ON①"}, {"idx": 1, "name": "ON②"}, {"idx": 2, "name": "OFF"}]
                    elif sub_c_x == 1:
                        self.dropdown_target = "sub_release" if self.menu_state == 7 else "init_sub_release"
                        if self.menu_state == 7: self.dropdown_options = [{"idx": 0, "name": "階段"}, {"idx": 1, "name": "1段"}, {"idx": 2, "name": "2段"}, {"idx": 3, "name": "3段"}]
                        else: self.dropdown_options = [{"idx": 0, "name": "ON①"}, {"idx": 1, "name": "ON②"}, {"idx": 2, "name": "OFF"}]

        elif self.menu_state == 8:
            targets = self.get_timing_target_stas() if hasattr(self, 'get_timing_target_stas') else []
            if targets:
                if getattr(self, 'timing_cursor', 0) == len(targets):
                    self.menu_state = 5
                elif 0 <= getattr(self, 'timing_cursor', 0) < len(targets):
                    sta_idx = targets[self.timing_cursor]
                    if sta_idx != getattr(self, 'setting_start_idx', 0):
                        current_status = self.is_station_timing(sta_idx) if hasattr(self, 'is_station_timing') else False
                        getattr(self, 'user_timing_overrides', {})[sta_idx] = not current_status

    def handle_dropdown_enter(self):
        selected_opt = getattr(self, 'dropdown_options', [])[getattr(self, 'dropdown_cursor', 0)]
        if selected_opt.get("name") == "選択可能駅なし":
            self.dropdown_active = False
            return
            
        val_name = selected_opt.get("name")
        val_idx = selected_opt.get("idx")
        
        if getattr(self, 'dropdown_target', "") == "start_sta":
            self.setting_start_idx = val_idx
            self.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}] 
            self.penalty_init_rules = [{"apply": "ON①", "release": "ON①"}]
        elif getattr(self, 'dropdown_target', "") == "end_sta":
            self.setting_end_idx = val_idx
            self.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}] 
            self.penalty_init_rules = [{"apply": "ON①", "release": "ON①"}]
            
        elif getattr(self, 'dropdown_target', "") in ["sub_end_sta", "init_sub_end_sta"]:
            rules = getattr(self, 'brake_rules', []) if getattr(self, 'dropdown_target', "") == "sub_end_sta" else getattr(self, 'penalty_init_rules', [])
            actual_terminal_idx = self.get_actual_terminal_idx() if hasattr(self, 'get_actual_terminal_idx') else -1
            e_overall = getattr(self, 'setting_end_idx', -1) if getattr(self, 'setting_end_idx', -1) != -1 else actual_terminal_idx
            is_terminal = (val_idx == e_overall)
            rules[-1]["end_idx"] = val_idx
            
            if not is_terminal:
                if getattr(self, 'dropdown_target', "") == "sub_end_sta":
                    rules.append({"end_idx": -1, "apply": "階段", "release": "階段"})
                    self.sub_cursor = len(rules) - 1
                    self.sub_cursor_x = 0
                    if self.sub_cursor >= getattr(self, 'sub_scroll', 0) + 5: self.sub_scroll = self.sub_cursor - 5 + 1
                else:
                    rules.append({"end_idx": -1, "apply": "ON①", "release": "ON①"})
                    self.init_sub_cursor = len(rules) - 1
                    self.init_sub_cursor_x = 0
                    if self.init_sub_cursor >= getattr(self, 'init_sub_scroll', 0) + 5: self.init_sub_scroll = self.init_sub_cursor - 5 + 1
                    
        elif getattr(self, 'dropdown_target', "") == "sub_apply":
            idx = getattr(self, 'dropdown_target_rule_idx', 0)
            old_val = getattr(self, 'brake_rules', [])[idx].get("apply", "")
            getattr(self, 'brake_rules', [])[idx]["apply"] = val_name
            
            # ★ 1段制動と連動して初動の値を自動変更＆復元する処理
            if len(getattr(self, 'penalty_init_rules', [])) > idx:
                if val_name == "1段":
                    if getattr(self, 'penalty_init_rules', [])[idx].get("apply") == "ON①":
                        getattr(self, 'penalty_init_rules', [])[idx]["apply"] = "OFF"
                elif old_val == "1段" and val_name != "1段":
                    # 1段制動からそれ以外に戻した場合は ON① に復帰させる
                    getattr(self, 'penalty_init_rules', [])[idx]["apply"] = "ON①"

            if val_name == "OFF": self.sub_cursor_x = 0
            if val_name == "1段": self.setting_initial_brake = "STATION"
            
        elif getattr(self, 'dropdown_target', "") == "sub_release":
            getattr(self, 'brake_rules', [])[getattr(self, 'dropdown_target_rule_idx', 0)]["release"] = val_name
        elif getattr(self, 'dropdown_target', "") == "init_sub_apply":
            getattr(self, 'penalty_init_rules', [])[getattr(self, 'dropdown_target_rule_idx', 0)]["apply"] = val_name
        elif getattr(self, 'dropdown_target', "") == "init_sub_release":
            getattr(self, 'penalty_init_rules', [])[getattr(self, 'dropdown_target_rule_idx', 0)]["release"] = val_name
            
        self.dropdown_active = False

    def handle_menu_backspace(self, is_bve_advancing):
        # ★ 新規追加: ヘルプ画面が開いている場合は、ヘルプを閉じるだけで戻らない
        if getattr(self, 'show_help', False):
            self.show_help = False
            return
        
        if self.menu_state == 5 and self.menu_cursor == 1 and getattr(self, 'input_mode_active', False):
            self.input_fresh = False 
            if len(getattr(self, 'input_buffer', "")) > 0: self.input_buffer = self.input_buffer[:-1]
            return

        if self.menu_state == 1: self.toggle_menu(is_bve_advancing)
        elif self.menu_state == 2:
            self.menu_state = 1
            self.menu_cursor = 0
        elif self.menu_state == 3:
            self.menu_state = 2
            self.menu_cursor = getattr(self, 'target_retry_idx', 0)
        elif self.menu_state == 4:
            self.menu_state = 1
            self.menu_cursor = 0
        elif self.menu_state == 5:
            if getattr(self, 'input_mode_active', False): self.finalize_margin_input() if hasattr(self, 'finalize_margin_input') else None
            self.menu_state = 1
            self.menu_cursor = 0
        elif self.menu_state == 6:
            self.menu_state = 5
            self.menu_cursor = 5
            self.menu_cursor_x = -1
        elif self.menu_state == 7:
            self.menu_state = 5 
        elif self.menu_state == 8:
            self.menu_state = 5
        elif self.menu_state == 9:
            self.menu_state = 6

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

    def update_logic(self):
        if keyboard.is_pressed('esc'): QApplication.quit()

        is_bve_active = False
        if self.bve_hwnd is None or not win32gui.IsWindow(self.bve_hwnd):
            self.bve_hwnd = self.find_bve_window()
            self.is_linked = False
            if self.was_bve_found and self.bve_hwnd is None:
                QApplication.quit()
                return
        
        if self.bve_hwnd:
            self.was_bve_found = True 
            is_bve_active = (win32gui.GetForegroundWindow() == self.bve_hwnd)
            
            if not self.is_linked:
                try:
                    win32gui.SetWindowLong(int(self.winId()), win32con.GWL_HWNDPARENT, self.bve_hwnd)
                    self.is_linked = True
                    self.show()
                except Exception: pass
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
                    if not self.isVisible(): self.show()
            except Exception:
                self.bve_hwnd = None
                self.is_linked = False
                self.hide()
        else:
            self.hide()

        current_time = self.bve_time_ms / 1000.0

        if self.bve_time_ms != self.last_bve_time_ms:
            self.last_time_change_real = time.time()
        is_bve_advancing = (time.time() - self.last_time_change_real) < 0.1

        # =================================================================
        # ★ 追加：F7キー（時刻表ジャンプ）の物理的ブロック
        # 採点モード中かつBVEアクティブ時なら、常にF7を無効化する
        # =================================================================
        should_block_f7 = getattr(self, 'is_scoring_mode', False) and not getattr(self, 'is_scoring_finished', False) and is_bve_active
        if should_block_f7 and not getattr(self, 'f7_blocked', False):
            self.f7_hook = keyboard.on_press_key('f7', lambda e: None, suppress=True)
            self.f7_blocked = True
        elif not should_block_f7 and getattr(self, 'f7_blocked', False):
            if hasattr(self, 'f7_hook') and self.f7_hook:
                keyboard.unhook(self.f7_hook)
            self.f7_blocked = False
        
        should_block_keys = (self.menu_state != 0) and is_bve_active
        if should_block_keys and not self.keys_blocked:
            block_keys = ['0','1','2','3','4','5','6','7','8','9','p','f8','up','down','left','right','enter','backspace', 'h']
            for k in block_keys:
                self.hook_dict[k] = keyboard.on_press_key(k, lambda e: None, suppress=True)
            self.keys_blocked = True
        elif not should_block_keys and self.keys_blocked:
            for hook in self.hook_dict.values():
                if hook: keyboard.unhook(hook)
            self.hook_dict.clear()
            self.keys_blocked = False

        is_left_clicked = (win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000) != 0
        if is_left_clicked and not self.last_left_click:
            if self.menu_state != 0 and is_bve_active:
                cursor_pos = win32gui.GetCursorPos()
                geom = self.geometry()
                scale_x = geom.width() / BASE_SCREEN_W
                scale_y = geom.height() / BASE_SCREEN_H
                menu_scale = min(scale_x, scale_y)
                offset_x = (geom.width() - BASE_SCREEN_W * menu_scale) / 2
                offset_y = (geom.height() - BASE_SCREEN_H * menu_scale) / 2
                lx = (cursor_pos[0] - geom.x() - offset_x) / menu_scale
                ly = (cursor_pos[1] - geom.y() - offset_y) / menu_scale
                
                for zone in self.menu_click_zones:
                    x1, y1, x2, y2, action_idx = zone
                    if x1 <= lx <= x2 and y1 <= ly <= y2:
                        if action_idx == 999: # ★ ヘルプボタンが押された場合
                            self.show_help = not getattr(self, 'show_help', False)
                            break
                        self.menu_cursor = action_idx
                        self.menu_cursor_x = -1
                        self.handle_menu_enter(is_bve_advancing)
                        break
        self.last_left_click = is_left_clicked

        for key in self.key_states.keys():
            is_pressed = keyboard.is_pressed(key)
            if is_pressed and not self.key_states[key] and is_bve_active:
                
                if key in [str(i) for i in range(10)]:
                    if self.menu_state == 5 and self.menu_cursor == 1 and self.input_mode_active:
                        if self.input_fresh:
                            self.input_buffer = key
                            self.input_fresh = False
                        elif len(self.input_buffer) < 4:
                            self.input_buffer += key
                            
                elif key == 'f6': self.toggle_menu(is_bve_advancing)
                elif key == 'h' and self.menu_state != 0: # ★ Hキーが押された場合
                    self.show_help = not getattr(self, 'show_help', False)
                elif self.menu_state != 0:
                    if self.dropdown_active:
                        if key == 'up':
                            if self.dropdown_cursor > 0:
                                self.dropdown_cursor -= 1
                                if self.dropdown_cursor < self.dropdown_scroll:
                                    self.dropdown_scroll = self.dropdown_cursor
                        elif key == 'down':
                            if self.dropdown_cursor < len(self.dropdown_options) - 1:
                                self.dropdown_cursor += 1
                                if self.dropdown_cursor >= self.dropdown_scroll + 7:
                                    self.dropdown_scroll = self.dropdown_cursor - 7 + 1
                        elif key == 'enter': self.handle_dropdown_enter()
                        elif key == 'backspace': self.dropdown_active = False 
                    else:
                        if key == 'up': self.handle_menu_up()
                        elif key == 'down': self.handle_menu_down()
                        elif key == 'left': self.handle_menu_left()
                        elif key == 'right': self.handle_menu_right()
                        elif key == 'enter': self.handle_menu_enter(is_bve_advancing)
                        elif key == 'backspace': self.handle_menu_backspace(is_bve_advancing)
                elif key == '4' and self.menu_state == 0:
                    self.is_speed_penalty = not self.is_speed_penalty
                    if self.is_speed_penalty: self.speed_penalty_score, self.last_penalty_time = 10, current_time
            self.key_states[key] = is_pressed

        if self.last_update_time == 0.0 or current_time < self.last_update_time:
            dt = 0.0
            self.g_history.clear()
            self.bcp_history.clear()
            self.popups.clear()
            self.ecb_eb_accum_time = 0.0
            self.ecb_eb_cooling_time = 0.0
            self.smee_eb_frozen = False
            self.eb_applied = False
            self.jump_lock = False
            self.ignore_next_pass_score = False  
            self.bb_state = "IDLE"
            self.bb_apply_count = 0
            self.bb_release_count = 0
            self.hb_strong_entered = False 
            self.last_update_time = current_time
        else:
            dt = current_time - self.last_update_time
            self.last_update_time = current_time
        self.last_bve_time_ms = self.bve_time_ms

        update_physics_and_scoring(self, current_time, dt)
        
        self.update() 

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        hud_scale = self.height() / BASE_SCREEN_H if self.height() > 0 else 1.0
        hud_logical_width = self.width() / hud_scale if hud_scale > 0 else BASE_SCREEN_W

        if self.menu_state != 0:
            draw_menu(self, painter, hud_logical_width)
        else:
            painter.scale(hud_scale, hud_scale)
            draw_hud(self, painter, hud_logical_width)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()
    sys.exit(app.exec())