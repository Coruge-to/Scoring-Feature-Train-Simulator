import sys
import time
import win32api
import win32gui
import win32con
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPainter, QFontDatabase
from PyQt6.QtNetwork import QUdpSocket, QHostAddress
import keyboard

from config import *
from network import process_udp_data
from scoring_logic import execute_retry, update_physics_and_scoring
from menu_ui import draw_menu
from hud_ui import draw_hud

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(0, 0, 1920, 1080)

        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            family = QFontDatabase.applicationFontFamilies(font_id)[0]
            self.font_normal = QFont(family, FONT_SIZE_NORMAL, QFont.Weight.Bold)
            self.font_big = QFont(family, FONT_SIZE_BIG, QFont.Weight.Bold)
            self.font_ui = QFont(family, FONT_SIZE_UI, QFont.Weight.Bold)
        else:
            self.font_normal, self.font_big, self.font_ui = QFont("sans-serif", 35, QFont.Weight.Bold), QFont("sans-serif", 55, QFont.Weight.Bold), QFont("sans-serif", 40, QFont.Weight.Bold)

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
        
        keys_to_track = ['1','2','3','4','5','6','7','f6','up','down','enter','backspace']
        self.key_states = {k: False for k in keys_to_track}
        
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
        
        self.keys_blocked = False
        self.hook_p = None
        self.hook_up = None
        self.hook_down = None
        self.hook_enter = None
        self.hook_backspace = None
        
        self.menu_items_off = ["運転を再開する", "採点設定", "環境設定"]
        self.menu_items_on = ["運転を再開する", "採点を中断する", "選択した駅からやり直す", "環境設定"]
        
        self.rollback_msg = ""
        self.rollback_msg_timer = 0.0
        self.prev_frame_loc = 0.0

        self.blink_phase = 0.0
        self.blink_active = False
        self.last_update_time = 0.0
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
        self.dbg_is_wait = False
        self.dbg_target_cap = 1000.0
        self.dbg_red = "None"
        self.dbg_blue = "None"

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(16)

    def read_udp_data(self):
        process_udp_data(self)

    def toggle_menu(self, is_bve_advancing):
        if self.menu_state == 0:
            self.menu_state = 1
            self.menu_cursor = 0
            if is_bve_advancing and self.bve_hwnd:
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYDOWN, 0x50, 0)
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYUP, 0x50, 0)
        else:
            self.menu_state = 0
            if not is_bve_advancing and self.bve_hwnd:
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYDOWN, 0x50, 0)
                win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYUP, 0x50, 0)

    def handle_menu_up(self):
        self.menu_cursor -= 1
        if self.menu_state == 1:
            items = self.menu_items_on if self.is_scoring_mode else self.menu_items_off
            if self.menu_cursor < 0: self.menu_cursor = len(items) - 1
        elif self.menu_state == 2:
            if self.menu_cursor < 0: self.menu_cursor = 0
            if self.menu_cursor < self.menu_scroll: self.menu_scroll = self.menu_cursor
        elif self.menu_state == 3:
            if self.menu_cursor < 0: self.menu_cursor = 1
        elif self.menu_state == 4:
            if self.menu_cursor < 0: self.menu_cursor = 6

    def handle_menu_down(self):
        self.menu_cursor += 1
        if self.menu_state == 1:
            items = self.menu_items_on if self.is_scoring_mode else self.menu_items_off
            if self.menu_cursor >= len(items): self.menu_cursor = 0
        elif self.menu_state == 2:
            max_idx = max(0, len(self.save_data) - 1)
            if self.menu_cursor > max_idx: self.menu_cursor = max_idx
            # ★ config.py で定義した定数を使って同期させる
            if self.menu_cursor >= self.menu_scroll + VISIBLE_LIST_COUNT:
                self.menu_scroll = self.menu_cursor - VISIBLE_LIST_COUNT + 1
        elif self.menu_state == 3:
            if self.menu_cursor > 1: self.menu_cursor = 0
        elif self.menu_state == 4:
            if self.menu_cursor > 6: self.menu_cursor = 0

    def handle_menu_enter(self, is_bve_advancing):
        if self.menu_state == 1:
            items = self.menu_items_on if self.is_scoring_mode else self.menu_items_off
            selected = items[self.menu_cursor]
            if selected == "運転を再開する": self.toggle_menu(is_bve_advancing)
            elif selected == "採点設定":
                self.is_scoring_mode = True
                self.score = 0
                self.save_data.clear()
                self.popups.clear()
                self.toggle_menu(is_bve_advancing)
            elif selected == "採点を中断する":
                self.is_scoring_mode = False
                self.popups.clear()
                self.toggle_menu(is_bve_advancing)
            elif selected == "選択した駅からやり直す":
                if len(self.save_data) > 0:
                    self.menu_state = 2
                    self.menu_cursor = 0
                    self.menu_scroll = 0
            elif "環境設定" in selected:
                self.menu_state = 4
                self.menu_cursor = 0
        elif self.menu_state == 2:
            if len(self.save_data) > 0:
                self.target_retry_idx = self.menu_cursor
                self.menu_state = 3
                self.menu_cursor = 0
        elif self.menu_state == 3:
            if self.menu_cursor == 0: execute_retry(self, self.target_retry_idx, is_bve_advancing)
            elif self.menu_cursor == 1: 
                self.menu_state = 2
                self.menu_cursor = self.target_retry_idx
        elif self.menu_state == 4:
            if self.menu_cursor <= 6:
                key = self.settings_keys[self.menu_cursor]
                self.disp_settings[key] = not self.disp_settings[key]

    def handle_menu_backspace(self, is_bve_advancing):
        if self.menu_state == 1: self.toggle_menu(is_bve_advancing)
        elif self.menu_state == 2:
            self.menu_state = 1
            self.menu_cursor = 0
        elif self.menu_state == 3:
            self.menu_state = 2
            self.menu_cursor = self.target_retry_idx
        elif self.menu_state == 4:
            self.menu_state = 1
            self.menu_cursor = 0

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
        
        should_block_keys = (self.menu_state != 0) and is_bve_active
        if should_block_keys and not self.keys_blocked:
            self.hook_p = keyboard.on_press_key('p', lambda e: None, suppress=True)
            self.hook_up = keyboard.on_press_key('up', lambda e: None, suppress=True)
            self.hook_down = keyboard.on_press_key('down', lambda e: None, suppress=True)
            self.hook_enter = keyboard.on_press_key('enter', lambda e: None, suppress=True)
            self.hook_backspace = keyboard.on_press_key('backspace', lambda e: None, suppress=True)
            self.keys_blocked = True
        elif not should_block_keys and self.keys_blocked:
            if self.hook_p: keyboard.unhook(self.hook_p)
            if self.hook_up: keyboard.unhook(self.hook_up)
            if self.hook_down: keyboard.unhook(self.hook_down)
            if self.hook_enter: keyboard.unhook(self.hook_enter)
            if self.hook_backspace: keyboard.unhook(self.hook_backspace)
            self.hook_p = self.hook_up = self.hook_down = self.hook_enter = self.hook_backspace = None
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
                        self.menu_cursor = action_idx
                        self.handle_menu_enter(is_bve_advancing)
                        break
        self.last_left_click = is_left_clicked

        for key in self.key_states.keys():
            is_pressed = keyboard.is_pressed(key)
            if is_pressed and not self.key_states[key] and is_bve_active:
                if key == 'f6': self.toggle_menu(is_bve_advancing)
                elif self.menu_state != 0:
                    if key == 'up': self.handle_menu_up()
                    elif key == 'down': self.handle_menu_down()
                    elif key == 'enter': self.handle_menu_enter(is_bve_advancing)
                    elif key == 'backspace': self.handle_menu_backspace(is_bve_advancing)
                elif key == '4' and self.menu_state == 0:
                    self.is_speed_penalty = not self.is_speed_penalty
                    if self.is_speed_penalty: self.speed_penalty_score, self.last_penalty_time = 10, current_time
                elif key == '5' and self.menu_state == 0:
                    self.show_graph = not self.show_graph
                    from scoring_logic import add_score_popup
                    text = "テレメトリ ON" if self.show_graph else "テレメトリ OFF"
                    add_score_popup(self, 0, text, COLOR_P, "pos", "システム", current_time)
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
            self.last_update_time = current_time
        else:
            dt = current_time - self.last_update_time
            self.last_update_time = current_time
        self.last_bve_time_ms = self.bve_time_ms

        update_physics_and_scoring(self, current_time, dt)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = self.height() / BASE_SCREEN_H if self.height() > 0 else 1.0
        painter.scale(scale, scale)
        logical_width = self.width() / scale

        if self.menu_state != 0:
            draw_menu(self, painter, logical_width)
        else:
            draw_hud(self, painter, logical_width)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    overlay = Overlay()
    overlay.show()
    sys.exit(app.exec())