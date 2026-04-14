from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPen, QFont
from config import *
from utils import draw_text_with_outline
import math
import time

def draw_menu(self, painter, logical_width):
    # ==========================================================
    # ★★★ UI青枠 微調整用パラメータ (メインメニュー全般) ★★★
    # ==========================================================
    GLOBAL_BOX_X_OFFSET = -3
    MENU_BOX_Y_OFFSET = 1
    SCORING_BOX_Y_OFFSET = -4
    MAIN_ROW0_STA_MAX_W = 400
    # ==========================================================

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 220))
    painter.drawRect(0, 0, int(logical_width), int(BASE_SCREEN_H))
    
    painter.save()
    painter.resetTransform()
    scale_x = self.width() / BASE_SCREEN_W
    scale_y = self.height() / BASE_SCREEN_H
    menu_scale = min(scale_x, scale_y)
    offset_x = (self.width() - BASE_SCREEN_W * menu_scale) / 2
    offset_y = (self.height() - BASE_SCREEN_H * menu_scale) / 2
    painter.translate(offset_x, offset_y)
    painter.scale(menu_scale, menu_scale)
    
    MENU_OUTLINE = COLOR_OUTLINE_BLACK
    MENU_TEXT = COLOR_WHITE
    MENU_ERROR = COLOR_B_EMG
    HIGHLIGHT_COLOR = QColor(30, 80, 150, 200) 
    
    center_x = BASE_SCREEN_W / 2
    self.menu_click_zones.clear()

    def draw_menu_item(text, y, is_selected, action_idx, align="center", x_offset=0):
        fm = QFontMetrics(self.font_normal)
        text_w = fm.horizontalAdvance(text)
        
        if align == "center":
            draw_x = center_x + x_offset
            box_x = center_x + x_offset - (text_w / 2) - 30 + GLOBAL_BOX_X_OFFSET
        elif align == "left":
            draw_x = center_x + x_offset
            box_x = draw_x - 30 + GLOBAL_BOX_X_OFFSET
        elif align == "right":
            draw_x = center_x + x_offset
            box_x = draw_x - text_w - 30 + GLOBAL_BOX_X_OFFSET
        
        box_w = text_w + 60
        box_h = fm.height() + 16
        box_y = y - fm.ascent() - 6 - (fm.descent() // 2) + MENU_BOX_Y_OFFSET

        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(box_x), int(box_y), int(box_w), int(box_h), 8, 8)

        draw_text_with_outline(painter, text, self.font_normal, MENU_TEXT, MENU_OUTLINE, draw_x, y, align, passes=8)
        
        if align == "center":
            self.menu_click_zones.append((center_x + x_offset - 400, box_y, center_x + x_offset + 400, box_y + box_h, action_idx))
        else:
            self.menu_click_zones.append((box_x, box_y, box_x + box_w, box_y + box_h, action_idx))

    def draw_setting_item(name, is_on, y, is_selected, action_idx):
        fm = QFontMetrics(self.font_normal)
        box_w = 800 
        box_x = center_x - (box_w / 2) + GLOBAL_BOX_X_OFFSET
        box_h = fm.height() + 16
        box_y = y - fm.ascent() - 6 - (fm.descent() // 2) + MENU_BOX_Y_OFFSET

        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(box_x), int(box_y), int(box_w), int(box_h), 8, 8)

        draw_text_with_outline(painter, name, self.font_normal, MENU_TEXT, MENU_OUTLINE, box_x - GLOBAL_BOX_X_OFFSET + 40, y, "left", passes=8)
        val_text = "ON" if is_on else "OFF"
        val_color = COLOR_P if is_on else COLOR_B_EMG
        draw_text_with_outline(painter, val_text, self.font_normal, val_color, COLOR_WHITE, box_x - GLOBAL_BOX_X_OFFSET + box_w - 40, y, "right", passes=8)
        self.menu_click_zones.append((box_x, box_y, box_x + box_w, box_y + box_h, action_idx))

    MAIN_SHIFT_Y = 25

    title_text = ""
    title_y = 200
    if self.menu_state == 1:
        title_text = "=== メニュー ==="
        title_y = 315
    elif self.menu_state == 2: title_text = "=== 選択した駅からやり直す ==="
    elif self.menu_state == 4: title_text = "=== 環境設定 ==="
    elif self.menu_state in [5, 7]: 
        title_text = "=== 採点設定 (1/3) ==="
        title_y = 112 + MAIN_SHIFT_Y
    elif self.menu_state in [6, 9]: 
        title_text = "=== 採点設定 (2/3) ==="
        title_y = 112 + MAIN_SHIFT_Y

    if title_text and self.menu_state not in [3, 8]:
        draw_text_with_outline(painter, title_text, self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, title_y, "center", passes=8)

    def get_sta_name(idx):
        if not getattr(self, 'station_list', []): return "データ未受信"
        if idx == -1:
            for i in range(len(self.station_list)-1, -1, -1):
                if self.station_list[i].get("is_timing", False):
                    return self.station_list[i]["name"]
            return "不明"
        if 0 <= idx < len(self.station_list):
            return self.station_list[idx]["name"]
        return "不明"

    if self.menu_state == 1:
        items = getattr(self, 'current_menu_items', getattr(self, 'menu_items_off', []))
        for i, text in enumerate(items):
            draw_menu_item(text, 465 + i * 80, (i == self.menu_cursor), i, "center")

    elif self.menu_state == 2:
        SAVE_TITLE_Y = 200
        SAVE_NO_DATA_Y = 450
        SAVE_ARROW_UP_Y = 290
        SAVE_LIST_Y = 370
        SAVE_ROW_H = 80
        SAVE_VISIBLE_COUNT = 7
        
        SAVE_COL_BOX_W = 1560
        SAVE_COL_BOX_X_OFFSET = 0
        
        SAVE_COL_STA_W = 380
        SAVE_COL_POS_W = 310
        SAVE_COL_SCORE_W = 350
        SAVE_COL_TIME_W = 320
        SAVE_COL_GAP = 50
        
        draw_text_with_outline(painter, "=== 選択した駅からやり直す ===", self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, SAVE_TITLE_Y, "center", passes=8)
        
        if not self.save_data:
            draw_text_with_outline(painter, "セーブされた駅がありません", self.font_normal, MENU_ERROR, MENU_OUTLINE, center_x, SAVE_NO_DATA_Y, "center", passes=8)
        else:
            if self.menu_scroll > 0:
                draw_text_with_outline(painter, "▲", self.font_normal, MENU_TEXT, MENU_OUTLINE, center_x, SAVE_ARROW_UP_Y, "center", passes=8)
            
            fm = QFontMetrics(self.font_normal)
            box_x_base = center_x - (SAVE_COL_BOX_W / 2) + SAVE_COL_BOX_X_OFFSET
            
            total_content_w = SAVE_COL_STA_W + SAVE_COL_GAP + SAVE_COL_POS_W + SAVE_COL_GAP + SAVE_COL_SCORE_W + SAVE_COL_GAP + SAVE_COL_TIME_W
            start_x_offset = (SAVE_COL_BOX_W - total_content_w) / 2
            
            COL_STA_L   = start_x_offset
            COL_POS_L   = COL_STA_L + SAVE_COL_STA_W + SAVE_COL_GAP
            COL_SCORE_L = COL_POS_L + SAVE_COL_POS_W + SAVE_COL_GAP
            COL_TIME_L  = COL_SCORE_L + SAVE_COL_SCORE_W + SAVE_COL_GAP
            
            self.menu_click_zones.clear()
            
            for i in range(SAVE_VISIBLE_COUNT):
                idx = self.menu_scroll + i
                if idx >= len(self.save_data): break
                cp = self.save_data[idx]
                
                time_s = cp['time_ms'] // 1000
                h, m, s = time_s // 3600, (time_s % 3600) // 60, time_s % 60
                err = cp['stop_error']
                err_str = f"{abs(err):.2f} m" if abs(err) >= 0.01 else "0.00 m"
                if err < -0.01: err_str = "-" + err_str
                
                sta_name = cp.get('station_name', '駅')
                
                y = SAVE_LIST_Y + i * SAVE_ROW_H
                box_h = fm.height() + 16
                box_y = y - fm.ascent() - 6 - (fm.descent() // 2) + 1
                
                if idx == self.menu_cursor:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(30, 80, 150, 200)) 
                    painter.drawRoundedRect(int(box_x_base), int(box_y), int(SAVE_COL_BOX_W), int(box_h), 8, 8)
                
                self.menu_click_zones.append((box_x_base, box_y, box_x_base + SAVE_COL_BOX_W, box_y + box_h, idx))
                
                def draw_cell(text, col_l_offset, max_w, align):
                    if align == "left": cx = box_x_base + col_l_offset
                    elif align == "right": cx = box_x_base + col_l_offset + max_w
                    else: cx = box_x_base + col_l_offset + (max_w / 2)
                        
                    actual_w = fm.horizontalAdvance(text)
                    if actual_w > max_w:
                        sr = max_w / actual_w
                        cy = y - fm.ascent() + fm.height() / 2.0
                        painter.save()
                        painter.translate(cx, cy)
                        painter.scale(sr, sr)
                        painter.translate(-cx, -cy)
                        draw_text_with_outline(painter, text, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, y, align, passes=8)
                        painter.restore()
                    else:
                        draw_text_with_outline(painter, text, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, y, align, passes=8)

                def draw_kv_cell(label, value, col_l_offset, max_w):
                    label_x = box_x_base + col_l_offset
                    draw_text_with_outline(painter, label, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, label_x, y, "left", passes=8)
                    
                    label_w = fm.horizontalAdvance(label)
                    val_max_w = max_w - label_w - 10 
                    val_actual_w = fm.horizontalAdvance(value)
                    val_x = box_x_base + col_l_offset + max_w
                    
                    if val_actual_w > val_max_w:
                        sr = val_max_w / val_actual_w
                        cy = y - fm.ascent() + fm.height() / 2.0
                        painter.save()
                        painter.translate(val_x, cy)
                        painter.scale(sr, sr)
                        painter.translate(-val_x, -cy)
                        draw_text_with_outline(painter, value, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, val_x, y, "right", passes=8)
                        painter.restore()
                    else:
                        draw_text_with_outline(painter, value, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, val_x, y, "right", passes=8)

                draw_cell(sta_name, COL_STA_L, SAVE_COL_STA_W, "left")
                draw_kv_cell("位置:", err_str, COL_POS_L, SAVE_COL_POS_W)
                draw_kv_cell("得点:", str(cp['score']), COL_SCORE_L, SAVE_COL_SCORE_W)
                draw_kv_cell("時刻:", f"{h:02}:{m:02}:{s:02}", COL_TIME_L, SAVE_COL_TIME_W)

            if self.menu_scroll + SAVE_VISIBLE_COUNT < len(self.save_data):
                draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, SAVE_LIST_Y + SAVE_VISIBLE_COUNT * SAVE_ROW_H, "center", passes=8)

    elif self.menu_state == 3:
        CONFIRM_SHIFT_Y = 50 # ★ ここの数字で上下にエレベーター移動します

        cp = self.save_data[self.target_retry_idx]
        msg = f"【 {cp.get('station_name', '駅')} 】からやり直しますか？"
        fm_big = QFontMetrics(self.font_big)
        max_msg_w = 1700
        actual_w = fm_big.horizontalAdvance(msg)
        
        # ★ ここで基準となるY座標を定義し、SHIFT分を足し込む
        msg_y = 350 + CONFIRM_SHIFT_Y
        warn_y = 450 + CONFIRM_SHIFT_Y
        btn_start_y = 600 + CONFIRM_SHIFT_Y
        
        if actual_w > max_msg_w:
            sr = max_msg_w / actual_w
            # ★ 350 だった部分を msg_y に変更
            cy = msg_y - fm_big.ascent() + fm_big.height() / 2.0
            painter.save()
            painter.translate(center_x, cy)
            painter.scale(sr, sr)
            painter.translate(-center_x, -cy)
            draw_text_with_outline(painter, msg, self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, msg_y, "center", passes=8)
            painter.restore()
        else:
            # ★ 350 だった部分を msg_y に変更
            draw_text_with_outline(painter, msg, self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, msg_y, "center", passes=8)
            
        # ★ 450 だった部分を warn_y に変更
        draw_text_with_outline(painter, "※これ以降のセーブデータは破棄されます", self.font_normal, COLOR_B_EMG, COLOR_WHITE, center_x, warn_y, "center", passes=8)
        
        self.menu_click_zones.clear()
        fm_normal = QFontMetrics(self.font_normal)
        
        fixed_box_w = 220  
        fixed_box_h = fm_normal.height() + 16 
        box_offset_x = -2  
        
        for i, text in enumerate(["はい", "いいえ"]):
            draw_x = center_x
            box_x = center_x - (fixed_box_w / 2) + box_offset_x
            # ★ 600 だった部分を btn_start_y に変更
            box_y = btn_start_y + i * 80 - fm_normal.ascent() - 6 - (fm_normal.descent() // 2) + 1
            
            if i == self.menu_cursor:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(30, 80, 150, 200))
                painter.drawRoundedRect(int(box_x), int(box_y), int(fixed_box_w), int(fixed_box_h), 8, 8)
                
            # ★ 600 だった部分を btn_start_y に変更
            draw_text_with_outline(painter, text, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, draw_x, btn_start_y + i * 80, "center", passes=8)
            self.menu_click_zones.append((box_x, box_y, box_x + fixed_box_w, box_y + fixed_box_h, i))

    elif self.menu_state == 4:
        for i in range(7):
            key = self.settings_keys[i]
            name = self.settings_names[i]
            is_on = getattr(self, 'disp_settings', {}).get(key, True)
            draw_setting_item(name, is_on, 300 + i * 70, (i == self.menu_cursor), i)

    elif self.menu_state in [5, 7]:
        sta_start = get_sta_name(getattr(self, 'setting_start_idx', 0))
        sta_end = get_sta_name(getattr(self, 'setting_end_idx', -1))

        # =========================================================
        # ★ メイン設定画面 (1/2) のレイアウト微調整パラメータ
        # =========================================================
        MAIN_X_OFFSET = 50   
        list_y_start  = 212 + MAIN_SHIFT_Y
        row_h         = 65
        label_x       = 100 + MAIN_X_OFFSET      
        val_x_start   = 550 + MAIN_X_OFFSET  
        # =========================================================
        
        fm = QFontMetrics(self.font_menu)
        # ★ "階段" の文字幅を基準に固定幅を計算
        fixed_apply_w = fm.horizontalAdvance("階段")

        def draw_label(row_idx, text, y, text_color, outline_color):
            # ★ 修正: 化石ロジックを消去し、カーソルが合っている時だけ青枠を出すようにしました
            if self.menu_state == 5 and self.menu_cursor == row_idx:
                if getattr(self, 'menu_cursor_x', 0) == -1:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    label_w = fm.horizontalAdvance(text)
                    painter.drawRoundedRect(int(label_x - 15 + GLOBAL_BOX_X_OFFSET), int(y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(label_w + 30), int(fm.height() + 12), 6, 6)
            draw_text_with_outline(painter, text, self.font_menu, text_color, outline_color, label_x, y, "left", passes=8)

        def draw_blocks(row_idx, blocks, y, is_sub_window=False):
            cx = val_x_start if not is_sub_window else 150 
            interactive_idx = 0
            for b in blocks:
                text = str(b["text"])
                is_interactive = b.get("interactive", False)
                t_color = b.get("color", COLOR_WHITE)
                o_color = b.get("outline", COLOR_OUTLINE_BLACK)
                max_w = b.get("max_w", None)
                
                text_w = fm.horizontalAdvance(text)
                
                is_scaled = False
                sr = 1.0
                if max_w and text_w > max_w:
                    is_scaled = True
                    sr = max_w / text_w
                    actual_box_w = max_w
                else:
                    actual_box_w = text_w

                if is_interactive:
                    if not is_sub_window:
                        is_focused = (self.menu_state == 5 and self.menu_cursor == row_idx and getattr(self, 'menu_cursor_x', 0) == interactive_idx and not getattr(self, 'dropdown_active', False))
                    else:
                        is_focused = (self.menu_state == 7 and getattr(self, 'sub_cursor', 0) == row_idx and getattr(self, 'sub_cursor_x', 0) == interactive_idx and not getattr(self, 'dropdown_active', False))
                        
                    if is_focused:
                        painter.setPen(Qt.PenStyle.NoPen)
                        if self.menu_state == 5 and row_idx == 1 and getattr(self, 'input_mode_active', False):
                            painter.setBrush(QColor(150, 50, 50, 200)) 
                        else:
                            painter.setBrush(HIGHLIGHT_COLOR)
                        box_y = y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET
                        painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(box_y), int(actual_box_w + 20), int(fm.height() + 12), 6, 6)
                    interactive_idx += 1

                if is_scaled:
                    cy = y - fm.ascent() + fm.height() / 2.0
                    painter.save()
                    painter.translate(cx, cy)
                    painter.scale(sr, sr)
                    painter.translate(0, -cy + y)
                    draw_text_with_outline(painter, text, self.font_menu, t_color, o_color, 0, 0, "left", passes=8)
                    painter.restore()
                else:
                    draw_text_with_outline(painter, text, self.font_menu, t_color, o_color, cx, y, "left", passes=8)
                
                cx += actual_box_w + 20

        if self.menu_state == 5:
            draw_label(0, "採点区間", list_y_start, COLOR_WHITE, COLOR_OUTLINE_BLACK)
            draw_blocks(0, [
                {"text": sta_start, "interactive": True, "max_w": MAIN_ROW0_STA_MAX_W},
                {"text": "～", "interactive": False},
                {"text": sta_end, "interactive": True, "max_w": MAIN_ROW0_STA_MAX_W}
            ], list_y_start)

            tl = int(getattr(self, 'bve_train_length', 20.0))
            draw_label(1, "停車駅採点範囲", list_y_start + row_h, COLOR_WHITE, COLOR_OUTLINE_BLACK)
            margin_disp = getattr(self, 'input_buffer', "") if getattr(self, 'input_mode_active', False) else str(getattr(self, 'setting_stop_distance', -1))
            if not margin_disp or margin_disp == "-1": margin_disp = "_" 
            draw_blocks(1, [
                {"text": margin_disp, "interactive": True},
                {"text": "m", "interactive": False}
            ], list_y_start + row_h)

            draw_label(2, "運転時分", list_y_start + row_h*2, COLOR_N, COLOR_WHITE)
            change_x_time = label_x + fm.horizontalAdvance("運転時分　")
            is_focused_time = (self.menu_cursor == 2 and getattr(self, 'menu_cursor_x', 0) == 0 and not getattr(self, 'dropdown_active', False))
            if is_focused_time:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(change_x_time - 10 + GLOBAL_BOX_X_OFFSET), int(list_y_start + row_h*2 - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(fm.horizontalAdvance("変更") + 20), int(fm.height() + 12), 6, 6)
            draw_text_with_outline(painter, "変更", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, change_x_time, list_y_start + row_h*2, "left", passes=8)
            
            has_timing_station = False
            if hasattr(self, 'get_timing_target_stas'):
                timing_targets = self.get_timing_target_stas()
                if timing_targets:
                    for t_idx in timing_targets:
                        if hasattr(self, 'is_station_timing') and self.is_station_timing(t_idx):
                            has_timing_station = True
                            break
                        
            timing_disp_text = "ON" if has_timing_station else "OFF"
            timing_disp_color = COLOR_P if has_timing_station else COLOR_B_EMG
            
            draw_blocks(2, [{"text": timing_disp_text, "interactive": False, "color": timing_disp_color, "outline": COLOR_WHITE}], list_y_start + row_h*2)

            draw_label(3, "停止位置", list_y_start + row_h*3, COLOR_N, COLOR_WHITE)
            draw_blocks(3, [{"text": "ON", "interactive": False, "color": COLOR_P, "outline": COLOR_WHITE}], list_y_start + row_h*3)

            draw_label(4, "基本制動", list_y_start + row_h*4, COLOR_N, COLOR_WHITE)
            
            change_x = label_x + fm.horizontalAdvance("基本制動　") 
            change_text = "変更"
            text_w = fm.horizontalAdvance(change_text)
            is_focused = (self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 0 and not getattr(self, 'dropdown_active', False))
            if is_focused:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(change_x - 10 + GLOBAL_BOX_X_OFFSET), int(list_y_start + row_h*4 - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(text_w + 20), int(fm.height() + 12), 6, 6)
            draw_text_with_outline(painter, change_text, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, change_x, list_y_start + row_h*4, "left", passes=8)

            vis_rules = min(3, len(getattr(self, 'brake_rules', [])))
            FIXED_STA_W = 280      
            
            box_y_offset = 12
            box_width = 1210
            box_height = row_h * vis_rules + 5
            
            is_summary_focused = (self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 1 and not getattr(self, 'dropdown_active', False))
            if is_summary_focused:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(30, 80, 150, 150))
                painter.drawRoundedRect(int(val_x_start - 20 + GLOBAL_BOX_X_OFFSET), int(list_y_start + row_h*4 - fm.ascent() - box_y_offset), box_width, int(box_height), 6, 6)

            colon_x = val_x_start + FIXED_STA_W + 15 + fm.horizontalAdvance("～") + 15 + FIXED_STA_W + 15
            col_summary_x = colon_x + (fm.horizontalAdvance(":") // 2)

            if getattr(self, 'summary_scroll', 0) > 0:
                draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, col_summary_x, list_y_start + row_h*4 - 68, "center", passes=8)
                
            for i in range(vis_rules):
                r_idx = getattr(self, 'summary_scroll', 0) + i
                if r_idx >= len(self.brake_rules): break
                r_y = list_y_start + row_h * (4 + i) 
                rule = getattr(self, 'brake_rules', [])[r_idx]
                r_start = get_sta_name(getattr(self, 'setting_start_idx', 0)) if r_idx == 0 else get_sta_name(getattr(self, 'brake_rules', [])[r_idx-1]["end_idx"])
                r_end = get_sta_name(getattr(self, 'setting_end_idx', -1)) if rule.get("end_idx", -1) == -1 else get_sta_name(rule["end_idx"])
                
                cx = val_x_start
                
                w_start = fm.horizontalAdvance(r_start)
                if w_start > FIXED_STA_W:
                    sr = FIXED_STA_W / w_start
                    cy = r_y - fm.ascent() + fm.height() / 2.0
                    painter.save()
                    painter.translate(cx, cy)
                    painter.scale(sr, sr)
                    painter.translate(0, -cy + r_y)
                    draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                    painter.restore()
                else:
                    draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += FIXED_STA_W + 15
                
                draw_text_with_outline(painter, "～", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += fm.horizontalAdvance("～") + 15
                
                w_end = fm.horizontalAdvance(r_end)
                if w_end > FIXED_STA_W:
                    sr = FIXED_STA_W / w_end
                    cy = r_y - fm.ascent() + fm.height() / 2.0
                    painter.save()
                    painter.translate(cx, cy)
                    painter.scale(sr, sr)
                    painter.translate(0, -cy + r_y)
                    draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                    painter.restore()
                else:
                    draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += FIXED_STA_W + 15
                
                draw_text_with_outline(painter, ":", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += fm.horizontalAdvance(":") + 20
                
                if rule.get("apply", "OFF") == "OFF":
                    actual_w = fm.horizontalAdvance("OFF")
                    draw_text_with_outline(painter, "OFF", self.font_menu, COLOR_B_EMG, COLOR_WHITE, cx, r_y, "left", passes=8)
                else:
                    apply_val = rule.get("apply", "階段")
                    actual_w = fm.horizontalAdvance(apply_val)
                    offset_x = fixed_apply_w - actual_w # 右揃えのためのオフセット
                    draw_text_with_outline(painter, apply_val, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx + offset_x, r_y, "left", passes=8)
                    cx += fixed_apply_w + 15 
                    
                    draw_text_with_outline(painter, "制動 /", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                    cx += fm.horizontalAdvance("制動 /") + 15
                    
                    rel_val = rule.get("release", "階段")
                    actual_rel_w = fm.horizontalAdvance(rel_val)
                    offset_rel_x = fixed_apply_w - actual_rel_w # 右揃えのためのオフセット
                    draw_text_with_outline(painter, rel_val, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx + offset_rel_x, r_y, "left", passes=8)
                    cx += fixed_apply_w + 15
                    
                    draw_text_with_outline(painter, "緩め", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)

            if getattr(self, 'summary_scroll', 0) + 3 < len(getattr(self, 'brake_rules', [])):
                draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, col_summary_x, list_y_start + row_h*(4 + vis_rules), "center", passes=8)

            last_row = 5
            btn_y = 830 
            draw_menu_item("次へ (減点項目の設定)", btn_y, (self.menu_cursor == last_row and getattr(self, 'menu_cursor_x', 0) == -1), last_row, "center")

            desc_y = 870 
            desc_h = 135 
            painter.setPen(QPen(QColor(150, 150, 150), 2))
            painter.setBrush(QColor(20, 20, 20, 220))
            painter.drawRoundedRect(150, int(desc_y), 1620, int(desc_h), 10, 10)

            actual_margin = getattr(self, 'setting_stop_distance', -1)

            desc_dict = {
                0: "【 採点区間 】\n採点を行う区間を設定します。\n（※デフォルト:始発駅～終着駅）",
                1: f"【 停車駅採点範囲 】\n停車駅において、採点を行う停止位置からの距離を設定します。キーボードで数値入力が可能です。\n列車長より短い値は入力できません。（※列車長 {tl} m ＋ マージン {max(0, actual_margin - tl)} m ＝ 判定距離 {actual_margin} m）",
                2: "【 運転時分 】\n指定された採時駅への到着・出発時刻の正確さを採点します。\n（※0～±9秒 : 300点、±10～±19秒 : 200点、±20秒～±29秒 : 100点、±30秒～ : 0点）",
                3: "【 停止位置 】\n停車駅での停止位置の正確さを採点します。誤差0.00 mに近いほど高得点になります。\n（※許容範囲に停車した時、停止位置x[m]とすると、点数y = 500 × (1 - x)）",
                4: "【 基本制動 】\n駅に停車する際、指定された回数で制動・緩め操作が行われたかを採点します。\n（※基本制動の条件を満たすと500点、さらに0.00 mに停車した場合はボーナス500点）",
                last_row: "次の設定ページ（減点項目の設定）へ進みます。"
            }
            
            desc_text = ""
            if self.menu_cursor == 2 and getattr(self, 'menu_cursor_x', 0) == 0:
                desc_text = "【 運転時分 設定 】\n駅ごとの採時 / 非採時の設定を変更します。\n（※採点開始駅は非採時で固定）"
            elif self.menu_cursor == 4 and getattr(self, 'menu_cursor_x', 0) == 0:
                desc_text = "【 基本制動 設定 】\n区間ごとに異なる基本制動のルールを適用したい場合に追加・編集します。\nルールは区間別の数珠繋ぎになります。"
            else:
                desc_text = desc_dict.get(self.menu_cursor, "")

            for j, line in enumerate(desc_text.split('\n')):
                draw_text_with_outline(painter, line, self.font_desc, COLOR_WHITE, COLOR_OUTLINE_BLACK, 180, desc_y + 40 + (j * 40), "left", passes=8)

    if self.menu_state == 7:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0,0,0, 180))
        painter.drawRect(0,0, int(BASE_SCREEN_W), int(BASE_SCREEN_H))
        
        sub_w, sub_h = 1700, 850
        sub_x, sub_y = 110, (BASE_SCREEN_H - sub_h) / 2
        
        painter.setBrush(QColor(30, 30, 30, 240))
        painter.setPen(QPen(QColor(150, 150, 150), 3))
        painter.drawRoundedRect(int(sub_x), int(sub_y), int(sub_w), int(sub_h), 12, 12)
        
        draw_text_with_outline(painter, "=== 基本制動 設定 ===", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, sub_y + 130, "center", passes=8)
        
        vis_rules = min(5, len(getattr(self, 'brake_rules', []))) 
        
        sub_val_x_start = 300  
        SUB_FIXED_STA_W = 350  
        gap_tilde = 15         
        gap_sta2 = 15          
        gap_colon = 15         
        gap_rule = 20          
        
        fm = QFontMetrics(self.font_menu)
        fixed_apply_w = fm.horizontalAdvance("階段") 
        colon_x = sub_val_x_start + SUB_FIXED_STA_W + gap_tilde + fm.horizontalAdvance("～") + gap_sta2 + SUB_FIXED_STA_W + gap_colon
        sub_col_summary_x = colon_x + (fm.horizontalAdvance(":") // 2)

        if getattr(self, 'sub_scroll', 0) > 0:
            draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, sub_col_summary_x, sub_y + 200, "center", passes=8)
        
        sub_list_y_start = sub_y + 275 
        
        for i in range(vis_rules):
            r_idx = getattr(self, 'sub_scroll', 0) + i
            if r_idx >= len(getattr(self, 'brake_rules', [])): break
            rule = getattr(self, 'brake_rules', [])[r_idx]
            r_start = get_sta_name(getattr(self, 'setting_start_idx', 0)) if r_idx == 0 else get_sta_name(getattr(self, 'brake_rules', [])[r_idx-1]["end_idx"])
            r_end = get_sta_name(getattr(self, 'setting_end_idx', -1)) if rule.get("end_idx", -1) == -1 else get_sta_name(rule["end_idx"])
            is_last = (r_idx == len(getattr(self, 'brake_rules', [])) - 1)
            r_y = sub_list_y_start + (i * 70) 
            
            cx = sub_val_x_start 
            
            w_start = fm.horizontalAdvance(r_start)
            if w_start > SUB_FIXED_STA_W:
                sr = SUB_FIXED_STA_W / w_start
                cy = r_y - fm.ascent() + fm.height() / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(sr, sr)
                painter.translate(0, -cy + r_y)
                draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                painter.restore()
            else:
                draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += SUB_FIXED_STA_W + gap_tilde
            
            draw_text_with_outline(painter, "～", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("～") + gap_sta2
            
            w_end = fm.horizontalAdvance(r_end)
            is_focused = (getattr(self, 'sub_cursor', 0) == r_idx and getattr(self, 'sub_cursor_x', 0) == 0 and not getattr(self, 'dropdown_active', False))
            
            if w_end > SUB_FIXED_STA_W:
                if is_focused and is_last:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(SUB_FIXED_STA_W + 20), int(fm.height() + 12), 6, 6)
                    
                sr = SUB_FIXED_STA_W / w_end
                cy = r_y - fm.ascent() + fm.height() / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(sr, sr)
                painter.translate(0, -cy + r_y)
                draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                painter.restore()
            else:
                if is_focused and is_last:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(w_end + 20), int(fm.height() + 12), 6, 6)
                draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += SUB_FIXED_STA_W + gap_colon
            
            draw_text_with_outline(painter, ":", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance(":") + gap_rule
            
            idx_apply = 1 if is_last else 0
            idx_release = 2 if is_last else 1

            if rule.get("apply", "OFF") == "OFF":
                actual_w = fm.horizontalAdvance("OFF")
                if getattr(self, 'sub_cursor', 0) == r_idx and getattr(self, 'sub_cursor_x', 0) == idx_apply and not getattr(self, 'dropdown_active', False):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(actual_w + 20), int(fm.height() + 12), 6, 6)
                draw_text_with_outline(painter, "OFF", self.font_menu, COLOR_B_EMG, COLOR_WHITE, cx, r_y, "left", passes=8)
            else:
                apply_val = rule.get("apply", "階段")
                actual_w = fm.horizontalAdvance(apply_val)
                offset_x = fixed_apply_w - actual_w # 右揃え
                if getattr(self, 'sub_cursor', 0) == r_idx and getattr(self, 'sub_cursor_x', 0) == idx_apply and not getattr(self, 'dropdown_active', False):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    painter.drawRoundedRect(int(cx + offset_x - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(actual_w + 20), int(fm.height() + 12), 6, 6)
                draw_text_with_outline(painter, apply_val, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx + offset_x, r_y, "left", passes=8)
                cx += fixed_apply_w + 15
                
                draw_text_with_outline(painter, "制動 /", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += fm.horizontalAdvance("制動 /") + 15
                
                rel_val = rule.get("release", "階段")
                actual_rel_w = fm.horizontalAdvance(rel_val)
                offset_rel_x = fixed_apply_w - actual_rel_w # 右揃え
                if getattr(self, 'sub_cursor', 0) == r_idx and getattr(self, 'sub_cursor_x', 0) == idx_release and not getattr(self, 'dropdown_active', False):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    painter.drawRoundedRect(int(cx + offset_rel_x - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(actual_rel_w + 20), int(fm.height() + 12), 6, 6)
                draw_text_with_outline(painter, rel_val, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx + offset_rel_x, r_y, "left", passes=8)
                cx += fixed_apply_w + 15
                
                draw_text_with_outline(painter, "緩め", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)

        if getattr(self, 'sub_scroll', 0) + 5 < len(getattr(self, 'brake_rules', [])):
            draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, sub_col_summary_x, sub_list_y_start + (5 * 70) + 10, "center", passes=8)
        
        row_undo = len(getattr(self, 'brake_rules', [])) if len(getattr(self, 'brake_rules', [])) > 1 else -1
        row_done = len(getattr(self, 'brake_rules', [])) + 1 if len(getattr(self, 'brake_rules', [])) > 1 else len(getattr(self, 'brake_rules', []))
        
        btn_base_y = sub_list_y_start + (5 * 70) + 90 
        if row_undo != -1:
            draw_menu_item("１つ前の設定を修正する (この行を削除)", btn_base_y, (getattr(self, 'sub_cursor', 0) == row_undo), row_undo, "center")
        draw_menu_item("設定完了", btn_base_y + 80, (getattr(self, 'sub_cursor', 0) == row_done), row_done, "center")

    elif self.menu_state == 8:
        # ==========================================================
        # ★★★ 運転時分 設定画面の微調整パラメータ ★★★
        # ==========================================================
        TIMING_SUB_W = 1300                 # ウィンドウの横幅
        TIMING_SUB_H = 900                  # ウィンドウの縦幅
        TIMING_TITLE_Y_OFFSET = 125         # 表題のY座標
        TIMING_ARROW_UP_Y_OFFSET = 215      # ▲のY座標
        TIMING_LIST_Y_OFFSET = 290          # リスト(駅名)が始まるY座標
        TIMING_ROW_H = 75                   # 1行あたりの高さ
        TIMING_VISIBLE_COUNT = 6            # 1画面に表示する件数
        TIMING_ARROW_DOWN_Y_OFFSET = 7      # リスト下端から▼までの距離
        TIMING_BTN_Y_OFFSET = 70            # ウィンドウ下端から設定完了ボタンまでの距離
        TIMING_BOX_W = 1100                  # 選択時の青枠の横幅
        TIMING_BOX_X_OFFSET = 0             # 選択時の青枠のX座標ズレ調整
        TIMING_STA_MAX_W = 600              # 駅名の最大幅(これを超えると縮小)
        TIMING_INNER_MARGIN_X = 125         # ウィンドウ端から文字(駅名・ON/OFF)までの距離
        TIMING_HIGHLIGHT_OFFSET_X = 0       # 選択時の青枠微調整X
        TIMING_HIGHLIGHT_OFFSET_Y = 0       # 選択時の青枠微調整Y
        # ==========================================================
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRect(0, 0, int(BASE_SCREEN_W), int(BASE_SCREEN_H))
        
        SUB_X = (BASE_SCREEN_W - TIMING_SUB_W) / 2
        SUB_Y = (BASE_SCREEN_H - TIMING_SUB_H) / 2
        
        TITLE_Y = SUB_Y + TIMING_TITLE_Y_OFFSET
        ARROW_UP_Y = SUB_Y + TIMING_ARROW_UP_Y_OFFSET
        LIST_Y = SUB_Y + TIMING_LIST_Y_OFFSET
        ARROW_DOWN_Y = LIST_Y + (TIMING_VISIBLE_COUNT * TIMING_ROW_H) + TIMING_ARROW_DOWN_Y_OFFSET
        BTN_Y = SUB_Y + TIMING_SUB_H - TIMING_BTN_Y_OFFSET
        
        painter.setBrush(QColor(30, 30, 30, 240))
        painter.setPen(QPen(QColor(150, 150, 150), 3))
        painter.drawRoundedRect(int(SUB_X), int(SUB_Y), int(TIMING_SUB_W), int(TIMING_SUB_H), 12, 12)
        
        draw_text_with_outline(painter, "=== 運転時分 設定 ===", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, TITLE_Y, "center", passes=8)

        if hasattr(self, 'get_timing_target_stas'):
            targets = self.get_timing_target_stas()
        else:
            targets = []
        
        if not targets:
            draw_text_with_outline(painter, "設定可能な駅がありません", self.font_normal, COLOR_B_EMG, COLOR_OUTLINE_BLACK, center_x, LIST_Y + 50, "center", passes=8)
        else:
            if getattr(self, 'timing_scroll', 0) > 0:
                draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, ARROW_UP_Y, "center", passes=8)
            
            fm = QFontMetrics(self.font_normal)
            box_x_base = center_x - (TIMING_BOX_W / 2) + TIMING_BOX_X_OFFSET

            for i in range(TIMING_VISIBLE_COUNT):
                list_idx = getattr(self, 'timing_scroll', 0) + i
                if list_idx >= len(targets): break
                
                sta_idx = targets[list_idx]
                st = getattr(self, 'station_list', [])[sta_idx]
                sta_name = st.get("name", "不明な駅")
                
                is_timing = False
                if hasattr(self, 'is_station_timing'): is_timing = self.is_station_timing(sta_idx)
                is_start = (sta_idx == getattr(self, 'setting_start_idx', 0))
                
                if is_start:
                    stat_text = "非採時"
                    stat_color = COLOR_B_EMG
                    stat_outline = COLOR_WHITE
                else:
                    stat_text = "採時" if is_timing else "非採時"
                    stat_color = COLOR_P if is_timing else COLOR_B_EMG
                    stat_outline = COLOR_WHITE 

                y = LIST_Y + i * TIMING_ROW_H
                box_h = fm.height() + 16
                box_y = y - fm.ascent() - 6 - (fm.descent() // 2) + 1

                if list_idx == getattr(self, 'timing_cursor', 0):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    painter.drawRoundedRect(int(box_x_base + TIMING_HIGHLIGHT_OFFSET_X), int(box_y + TIMING_HIGHLIGHT_OFFSET_Y), int(TIMING_BOX_W), int(box_h), 8, 8)

                if not is_start:
                    self.menu_click_zones.append((box_x_base, box_y, box_x_base + TIMING_BOX_W, box_y + box_h, list_idx))

                cx_sta = SUB_X + TIMING_INNER_MARGIN_X
                actual_w = fm.horizontalAdvance(sta_name)
                if actual_w > TIMING_STA_MAX_W:
                    sr = TIMING_STA_MAX_W / actual_w
                    cy = y - fm.ascent() + fm.height() / 2.0
                    painter.save()
                    painter.translate(cx_sta, cy)
                    painter.scale(sr, sr)
                    painter.translate(-cx_sta, -cy)
                    draw_text_with_outline(painter, sta_name, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx_sta, y, "left", passes=8)
                    painter.restore()
                else:
                    draw_text_with_outline(painter, sta_name, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx_sta, y, "left", passes=8)

                cx_stat = SUB_X + TIMING_SUB_W - TIMING_INNER_MARGIN_X
                draw_text_with_outline(painter, stat_text, self.font_normal, stat_color, stat_outline, cx_stat, y, "right", passes=8)

            if getattr(self, 'timing_scroll', 0) + TIMING_VISIBLE_COUNT < len(targets):
                draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, ARROW_DOWN_Y, "center", passes=8)
                
            btn_text = "設定完了"
            btn_w = fm.horizontalAdvance(btn_text) + 60
            btn_h = fm.height() + 16
            btn_x = center_x - (btn_w / 2)
            btn_rect_y = BTN_Y - fm.ascent() - 6 - (fm.descent() // 2) + 1
            
            if getattr(self, 'timing_cursor', 0) == len(targets):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(btn_x + TIMING_HIGHLIGHT_OFFSET_X), int(btn_rect_y + TIMING_HIGHLIGHT_OFFSET_Y), int(btn_w), int(btn_h), 8, 8)
                
            draw_text_with_outline(painter, btn_text, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, BTN_Y, "center", passes=8)
            self.menu_click_zones.append((btn_x, btn_rect_y, btn_x + btn_w, btn_rect_y + btn_h, len(targets)))

    # ==========================================================
    # ★ 新規追加: 採点設定 (2/2) 減点項目のメイン描画 (menu_state == 6)
    # ==========================================================
    elif self.menu_state == 6:
        MAIN_X_OFFSET = 50   
        list_y_start  = 212 + MAIN_SHIFT_Y
        row_h         = 65
        
        # ★ 1/2と位置を完全に同期
        label_x       = 100 + MAIN_X_OFFSET 
        val_x_start   = 550 + MAIN_X_OFFSET
        
        fm = QFontMetrics(self.font_menu)
        fixed_apply_w = fm.horizontalAdvance("ON①")

        def draw_toggle_row(cursor_idx, label_text, is_on, base_y):
            if self.menu_cursor == cursor_idx and getattr(self, 'menu_cursor_x', 0) == -1:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                label_w = fm.horizontalAdvance(label_text)
                painter.drawRoundedRect(int(label_x - 15 + GLOBAL_BOX_X_OFFSET), int(base_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(label_w + 30), int(fm.height() + 12), 6, 6)
            draw_text_with_outline(painter, label_text, self.font_menu, COLOR_B_EMG, COLOR_WHITE, label_x, base_y, "left", passes=8)
            
            val_text = "ON" if is_on else "OFF"
            val_col = COLOR_P if is_on else COLOR_B_EMG
            
            is_val_focused = (self.menu_cursor == cursor_idx and getattr(self, 'menu_cursor_x', 0) == 0)
            if cursor_idx != 0: 
                if is_val_focused:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(HIGHLIGHT_COLOR)
                    val_w = fm.horizontalAdvance(val_text)
                    painter.drawRoundedRect(int(val_x_start - 10 + GLOBAL_BOX_X_OFFSET), int(base_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(val_w + 20), int(fm.height() + 12), 6, 6)
                
            draw_text_with_outline(painter, val_text, self.font_menu, val_col, COLOR_WHITE, val_x_start, base_y, "left", passes=8)

        draw_toggle_row(0, "転動", True, list_y_start)
        draw_toggle_row(1, "ATS信号無視", getattr(self, 'pen_ats', True), list_y_start + row_h)
        draw_toggle_row(2, "速度制限超過", getattr(self, 'pen_limit', True), list_y_start + row_h * 2)
        draw_toggle_row(3, "停車時衝動", getattr(self, 'pen_jerk', True), list_y_start + row_h * 3)
        draw_toggle_row(4, "非常ブレーキ", getattr(self, 'pen_eb', True), list_y_start + row_h * 4)

        y_init = list_y_start + row_h * 5
        if self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == -1:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            label_w = fm.horizontalAdvance("初動ブレーキ")
            painter.drawRoundedRect(int(label_x - 15 + GLOBAL_BOX_X_OFFSET), int(y_init - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(label_w + 30), int(row_h + fm.height() + 12), 6, 6)
            
        draw_text_with_outline(painter, "初動ブレーキ", self.font_menu, COLOR_B_EMG, COLOR_WHITE, label_x, y_init, "left", passes=8)
        draw_text_with_outline(painter, "緩和ブレーキ", self.font_menu, COLOR_B_EMG, COLOR_WHITE, label_x, y_init + row_h, "left", passes=8)
        
        change_x = label_x + 317
        change_text = "変更"
        text_w = fm.horizontalAdvance(change_text)
        is_focused = (self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == 0 and not getattr(self, 'dropdown_active', False))
        if is_focused:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(change_x - 10 + GLOBAL_BOX_X_OFFSET), int(y_init - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(text_w + 20), int(fm.height() + 12), 6, 6)
        draw_text_with_outline(painter, change_text, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, change_x, y_init, "left", passes=8)
        
        init_rules = getattr(self, 'penalty_init_rules', [{"apply": "ON①", "release": "ON①"}])
        vis_rules = min(3, len(getattr(self, 'brake_rules', [])))
        FIXED_STA_W = 270 
        box_y_offset = 12
        box_width = 1210
        box_height = row_h * vis_rules + 5
        
        is_summary_focused = (self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == 1 and not getattr(self, 'dropdown_active', False))
        
        list_cx_start = val_x_start

        if is_summary_focused:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 80, 150, 150))
            painter.drawRoundedRect(int(list_cx_start - 20 + GLOBAL_BOX_X_OFFSET), int(y_init - fm.ascent() - box_y_offset), box_width, int(box_height), 6, 6)
            
        col_summary_x = list_cx_start + FIXED_STA_W + 15 + fm.horizontalAdvance("～") + 15 + FIXED_STA_W + 15 + (fm.horizontalAdvance(":") // 2)
        summary_scroll = getattr(self, 'init_summary_scroll', 0)
        
        if summary_scroll > 0:
            draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, col_summary_x, y_init - 68, "center", passes=8)
            
        for i in range(vis_rules):
            r_idx = summary_scroll + i
            if r_idx >= len(getattr(self, 'brake_rules', [])): break
            r_y = y_init + row_h * i
            
            b_rule = getattr(self, 'brake_rules', [])[r_idx]
            p_rule = init_rules[r_idx] if r_idx < len(init_rules) else {"apply": "ON①", "release": "ON①"}
            
            r_start = get_sta_name(getattr(self, 'setting_start_idx', 0)) if r_idx == 0 else get_sta_name(getattr(self, 'brake_rules', [])[r_idx-1]["end_idx"])
            r_end = get_sta_name(getattr(self, 'setting_end_idx', -1)) if b_rule.get("end_idx", -1) == -1 else get_sta_name(b_rule["end_idx"])
            
            cx = list_cx_start
            
            w_start = fm.horizontalAdvance(r_start)
            if w_start > FIXED_STA_W:
                sr = FIXED_STA_W / w_start
                cy = r_y - fm.ascent() + fm.height() / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(sr, sr)
                painter.translate(0, -cy + r_y)
                draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                painter.restore()
            else:
                draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += FIXED_STA_W + 15
            
            draw_text_with_outline(painter, "～", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("～") + 15
            
            w_end = fm.horizontalAdvance(r_end)
            if w_end > FIXED_STA_W:
                sr = FIXED_STA_W / w_end
                cy = r_y - fm.ascent() + fm.height() / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(sr, sr)
                painter.translate(0, -cy + r_y)
                draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                painter.restore()
            else:
                draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += FIXED_STA_W + 15
            
            draw_text_with_outline(painter, ":", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance(":") + 20
            
            draw_text_with_outline(painter, "初動", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("初動") + 15
            
            apply_val = p_rule.get("apply", "ON①")
            actual_w = fm.horizontalAdvance(apply_val)
            a_col = COLOR_P if "ON" in apply_val else COLOR_B_EMG
            draw_text_with_outline(painter, apply_val, self.font_menu, a_col, COLOR_WHITE, cx, r_y, "left", passes=8)
            cx += fixed_apply_w + 15 
            
            draw_text_with_outline(painter, "/", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("/") + 15
            
            draw_text_with_outline(painter, "緩和", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("緩和") + 15
            
            rel_val = p_rule.get("release", "ON①")
            r_col = COLOR_P if "ON" in rel_val else COLOR_B_EMG
            draw_text_with_outline(painter, rel_val, self.font_menu, r_col, COLOR_WHITE, cx, r_y, "left", passes=8)
            
        if summary_scroll + 3 < len(getattr(self, 'brake_rules', [])):
            draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, col_summary_x, y_init + row_h*vis_rules, "center", passes=8)
        
        # 6: 採点開始 (前へを廃止し中央へ)
        btn_y = 830
        draw_menu_item("次へ (評価点の設定)", btn_y, (self.menu_cursor == 6 and getattr(self, 'menu_cursor_x', 0) == -1), 6, "center", x_offset=0)

        # 説明文
        desc_y = 870 
        desc_h = 135 
        painter.setPen(QPen(QColor(150, 150, 150), 2))
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(150, int(desc_y), 1620, int(desc_h), 10, 10)

        desc_dict = {
            0: "【 転動 】\nドア開扉中に車両が完全に停止していたかを採点します。\n（※ドア開扉中に5cm以上動くと-500点）",
            1: "【 ATS信号無視 】\n未実装\n（※保安装置が働く度に-500点）",
            2: "【 速度制限超過 】\n速度制限・信号制限を守ったかを採点します。\n（※1秒毎に超過した速度(km/h)を累積減点）",
            3: "【 停車時衝動 】\n列車が完全に停止する際のショックの大きさを停止直前の0.5秒におけるGの平均値により採点します。\n（※0.06G≒2.1km/h/s以上で-100点、0.10G≒3.5km/h/s以上で-200点）",
            4: "【 非常ブレーキ 】\n走行中に非常ブレーキを使用したかどうかを採点します。\n（※非常ブレーキを使用するごとに-500点）",
            5: "【 初動・緩和ブレーキ 】\n基本制動のルールを設定した区間ごとに、\n異なる初動・緩和ブレーキのルールを適用したい場合に追加・編集します。",
            6: "次の設定ページ（評価点の設定）へ進みます。"
        }
        
        desc_text = ""
        if self.menu_cursor == 5 and getattr(self, 'menu_cursor_x', 0) == 0:
            desc_text = "【 初動・緩和ブレーキ 設定 】\n特定区間だけ異なる初動・緩和ルールを適用したい場合に追加・編集します。\n基本制動のルールを設定した区間ごとに、ON①/ON②/OFFの切り替えを行います。"
        else:
            desc_text = desc_dict.get(self.menu_cursor, "")

        for j, line in enumerate(desc_text.split('\n')):
            draw_text_with_outline(painter, line, self.font_desc, COLOR_WHITE, COLOR_OUTLINE_BLACK, 180, desc_y + 40 + (j * 40), "left", passes=8)

    # ==========================================================
    # ★ 新規追加: 初動・緩和ブレーキ区間設定 サブウィンドウ (menu_state == 9)
    # ==========================================================
    elif self.menu_state == 9:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0,0,0, 180))
        painter.drawRect(0,0, int(BASE_SCREEN_W), int(BASE_SCREEN_H))
        
        sub_w, sub_h = 1700, 940
        sub_x, sub_y = 110, (BASE_SCREEN_H - sub_h) / 2
        SHIFT_Y = 30
        
        painter.setBrush(QColor(30, 30, 30, 240))
        painter.setPen(QPen(QColor(150, 150, 150), 3))
        painter.drawRoundedRect(int(sub_x), int(sub_y), int(sub_w), int(sub_h), 12, 12)
        
        draw_text_with_outline(painter, "=== 初動・緩和ブレーキ 設定 ===", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, sub_y + 110 + SHIFT_Y, "center", passes=8)

        fm = QFontMetrics(self.font_menu)
        fixed_apply_w = fm.horizontalAdvance("ON①") 
        init_rules = getattr(self, 'penalty_init_rules', [{"apply": "ON①", "release": "ON①"}])
        vis_rules = min(5, len(getattr(self, 'brake_rules', []))) 
        
        sub_val_x_start = 280  
        SUB_FIXED_STA_W = 340  
        gap_tilde = 15         
        gap_sta2 = 15          
        gap_colon = 15         
        gap_rule = 20          
        
        colon_x = sub_val_x_start + SUB_FIXED_STA_W + gap_tilde + fm.horizontalAdvance("～") + gap_sta2 + SUB_FIXED_STA_W + gap_colon
        sub_col_summary_x = colon_x + (fm.horizontalAdvance(":") // 2)
        
        sub_scroll = getattr(self, 'init_sub_scroll', 0)
        sub_cursor = getattr(self, 'init_sub_cursor', 0)
        sub_cursor_x = getattr(self, 'init_sub_cursor_x', 0)

        if sub_scroll > 0:
            draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, sub_col_summary_x, sub_y + 170 + SHIFT_Y, "center", passes=8)
        
        sub_list_y_start = sub_y + 240 + SHIFT_Y
        sta_start = get_sta_name(getattr(self, 'setting_start_idx', 0))
        sta_end = get_sta_name(getattr(self, 'setting_end_idx', -1))

        for i in range(vis_rules):
            r_idx = sub_scroll + i
            if r_idx >= len(getattr(self, 'brake_rules', [])): break
            
            b_rule = getattr(self, 'brake_rules', [])[r_idx]
            p_rule = init_rules[r_idx] if r_idx < len(init_rules) else {"apply": "ON①", "release": "ON①"}
            
            r_start = sta_start if r_idx == 0 else get_sta_name(getattr(self, 'brake_rules', [])[r_idx-1]["end_idx"])
            r_end = sta_end if b_rule.get("end_idx", -1) == -1 else get_sta_name(b_rule["end_idx"])
            
            r_y = sub_list_y_start + (i * 70) 
            cx = sub_val_x_start 
            
            w_start = fm.horizontalAdvance(r_start)
            if w_start > SUB_FIXED_STA_W:
                sr = SUB_FIXED_STA_W / w_start
                cy = r_y - fm.ascent() + fm.height() / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(sr, sr)
                painter.translate(0, -cy + r_y)
                draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                painter.restore()
            else:
                draw_text_with_outline(painter, r_start, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += SUB_FIXED_STA_W + gap_tilde
            
            draw_text_with_outline(painter, "～", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("～") + gap_sta2
            
            w_end = fm.horizontalAdvance(r_end)
            if w_end > SUB_FIXED_STA_W:
                sr = SUB_FIXED_STA_W / w_end
                cy = r_y - fm.ascent() + fm.height() / 2.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(sr, sr)
                painter.translate(0, -cy + r_y)
                draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, 0, 0, "left", passes=8)
                painter.restore()
            else:
                draw_text_with_outline(painter, r_end, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += SUB_FIXED_STA_W + gap_colon
            
            draw_text_with_outline(painter, ":", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance(":") + gap_rule
            
            idx_apply = 0
            idx_release = 1

            # 初動
            draw_text_with_outline(painter, "初動", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("初動") + 15
            
            apply_val = p_rule.get("apply", "ON①")
            actual_w = fm.horizontalAdvance(apply_val)
            if sub_cursor == r_idx and sub_cursor_x == idx_apply and not getattr(self, 'dropdown_active', False):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(actual_w + 20), int(fm.height() + 12), 6, 6)
            a_col = COLOR_P if "ON" in apply_val else COLOR_B_EMG
            draw_text_with_outline(painter, apply_val, self.font_menu, a_col, COLOR_WHITE, cx, r_y, "left", passes=8)
            cx += fixed_apply_w + 15 
            
            draw_text_with_outline(painter, "/", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("/") + 15
            
            # 緩和
            draw_text_with_outline(painter, "緩和", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            cx += fm.horizontalAdvance("緩和") + 15
            
            rel_val = p_rule.get("release", "ON①")
            actual_rel_w = fm.horizontalAdvance(rel_val)
            if sub_cursor == r_idx and sub_cursor_x == idx_release and not getattr(self, 'dropdown_active', False):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(actual_rel_w + 20), int(fm.height() + 12), 6, 6)
            r_col = COLOR_P if "ON" in rel_val else COLOR_B_EMG
            draw_text_with_outline(painter, rel_val, self.font_menu, r_col, COLOR_WHITE, cx, r_y, "left", passes=8)

        if sub_scroll + 5 < len(getattr(self, 'brake_rules', [])):
            draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, sub_col_summary_x, sub_list_y_start + (5 * 70) + 10, "center", passes=8)
        
        row_done = len(getattr(self, 'brake_rules', []))
        btn_base_y = sub_list_y_start + (5 * 70)
        draw_menu_item("設定完了", btn_base_y + 80, (sub_cursor == row_done), row_done, "center")

        # 説明文
        desc_y = btn_base_y + 120
        desc_h = 175 
        painter.setPen(QPen(QColor(150, 150, 150), 2))
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(150, int(desc_y), 1620, int(desc_h), 10, 10)
        desc_text = "ON① : 全区間で採点を行います。\nON② : 停車駅採点範囲内（停止位置目標の付近）での操作は減点免除となります。\nOFF  : 採点を行いません。\n※残圧停車を行う路線では、緩和をON②またはOFFにしてください。"
        for j, line in enumerate(desc_text.split('\n')):
            draw_text_with_outline(painter, line, self.font_desc, COLOR_WHITE, COLOR_OUTLINE_BLACK, 180, desc_y + 40 + (j * 40), "left", passes=8)

    # ==========================================================
    # ★ 新規追加: 評価点の設定 (3/3) メイン描画 (menu_state == 10)
    # ==========================================================
    elif self.menu_state == 10:
        MAIN_SHIFT_Y = 25
        title_text = "=== 採点設定 (3/3) ==="
        title_y = 112 + MAIN_SHIFT_Y
        draw_text_with_outline(painter, title_text, self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, title_y, "center", passes=8)

        # 数値の計算
        rank_a_pct = int(round(getattr(self, 'rank_a_ratio', 0.8) * 100))
        rank_b_pct = int(round(rank_a_pct * 0.8))
        rank_c_pct = int(round(rank_b_pct * 0.8))

        theory_score = getattr(self, 'theoretical_score', 12500)
        score_a = int(round(theory_score * (rank_a_pct / 100.0)))
        score_b = int(round(score_a * 0.8))
        score_c = int(round(score_a * 0.8 * 0.8))

        # ---------------------------------------------
        # 1. スライダーの描画
        # ---------------------------------------------
        slider_y = 265
        slider_w = 1200
        slider_x = center_x - (slider_w / 2)

        # 各ランクの境界となるX座標を計算
        x_d = slider_x
        x_c = slider_x + (slider_w * rank_c_pct / 100.0)
        x_b = slider_x + (slider_w * rank_b_pct / 100.0)
        x_a = slider_x + (slider_w * rank_a_pct / 100.0)
        x_end = slider_x + slider_w

        # 色を安全にQColor化するヘルパー関数
        def get_qc(color_val):
            return QColor(*color_val) if isinstance(color_val, tuple) else QColor(color_val)

        c_gray = get_qc((150, 150, 150))
        c_blue = get_qc(COLOR_P)
        c_green = get_qc(COLOR_N)
        c_red = get_qc(COLOR_B_EMG)

        # ==========================================================
        # ① 鶴さん考案の下地ハック：両端の丸み（RoundCap）を色付きで補完する
        # 左半分をグレー、右半分を赤で RoundCap として引いておく
        painter.setPen(QPen(c_gray, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(slider_x), int(slider_y), int(center_x), int(slider_y))
        
        painter.setPen(QPen(c_red, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(center_x), int(slider_y), int(x_end), int(slider_y))
        # ==========================================================

        # ② FlatCap(平らな端)で各ランクのセグメントを正確に上塗りする
        painter.setPen(QPen(c_gray, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLine(int(x_d), int(slider_y), int(x_c), int(slider_y))

        painter.setPen(QPen(c_blue, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLine(int(x_c), int(slider_y), int(x_b), int(slider_y))

        painter.setPen(QPen(c_green, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLine(int(x_b), int(slider_y), int(x_a), int(slider_y))

        painter.setPen(QPen(c_red, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLine(int(x_a), int(slider_y), int(x_end), int(slider_y))

        # ==========================================================
        # ③ 各バーの中央に「白縁取り ＋ バーと同色」の文字を描画する
        mid_d = (x_d + x_c) / 2
        mid_c = (x_c + x_b) / 2
        mid_b = (x_b + x_a) / 2
        mid_a = (x_a + x_end) / 2

        # 文字のY座標をバーの中心に合わせるための微調整
        text_y = slider_y + 10 
        font_rank_label = self.font_desc # やや小さめのフォント(25pt)を指定

        draw_text_with_outline(painter, "D", font_rank_label, c_gray, COLOR_WHITE, mid_d, text_y, "center", passes=8)
        draw_text_with_outline(painter, "C", font_rank_label, c_blue, COLOR_WHITE, mid_c, text_y, "center", passes=8)
        draw_text_with_outline(painter, "B", font_rank_label, c_green, COLOR_WHITE, mid_b, text_y, "center", passes=8)
        draw_text_with_outline(painter, "A", font_rank_label, c_red, COLOR_WHITE, mid_a, text_y, "center", passes=8)
        # ==========================================================

        # 両端のテキスト
        draw_text_with_outline(painter, "0%", self.font_ui, COLOR_WHITE, COLOR_OUTLINE_BLACK, slider_x - 30, slider_y + 20, "right", passes=8)
        draw_text_with_outline(painter, "100%", self.font_ui, COLOR_WHITE, COLOR_OUTLINE_BLACK, slider_x + slider_w + 30, slider_y + 20, "left", passes=8)

        def draw_node(pct, color_val, label_text, is_active=False):
            nx = slider_x + (slider_w * pct / 100)

            qc = QColor(*color_val) if isinstance(color_val, tuple) else QColor(color_val)
            
            if is_active:
                # 1. アニメーション変数を滑らかな「脈動」に変換する (0.0 〜 1.0 の sin波)
                t = time.time()
                pulse = (math.sin(t * math.pi) + 1) / 2 # 0.0 〜 1.0 のゆっくりした波
                
                painter.setPen(Qt.PenStyle.NoPen)
                
                glow_c = QColor(255, 80, 80)
                
                glow_c.setAlpha(60)
                painter.setBrush(glow_c)
                painter.drawEllipse(int(nx - 28), int(slider_y - 28), 56, 56)
                
                glow_size = 44 + (pulse * 20)
                
                glow_alpha = int(40 + (pulse * 80))
                
                glow_c.setAlpha(glow_alpha)
                painter.setBrush(glow_c)
                for s_offset in [0, 8]:
                    s = glow_size + s_offset
                    painter.drawEllipse(int(nx - s/2), int(slider_y - s/2), int(s), int(s))

            painter.setPen(QPen(qc, 8))
            painter.setBrush(QColor(*COLOR_WHITE)) # 白で塗りつぶし
            painter.drawEllipse(int(nx - 22), int(slider_y - 22), 44, 44)
            
            # 上の吹き出しボックス
            box_w = 100
            box_h = 45
            box_y = slider_y - 85
            painter.setPen(QPen(qc, 3))
            painter.setBrush(QColor(*COLOR_WHITE)) # ★ 修正
            painter.drawRoundedRect(int(nx - box_w/2), int(box_y), box_w, box_h, 5, 5)
            
            # 吹き出しの尻尾
            painter.drawLine(int(nx), int(box_y + box_h + 1), int(nx), int(slider_y - 28))
            
            # パーセント文字 (draw_text_with_outline はタプルをそのまま受け取れる)
            pct_str = getattr(self, 'input_buffer', "") + "%" if is_active and getattr(self, 'input_mode_active', False) else f"{pct}%"
            draw_text_with_outline(painter, pct_str, self.font_desc, color_val, COLOR_WHITE, nx, box_y + 35, "center", passes=8)
            return nx

        # C, B, A の順に描画 (HUDのカラー定数を使い回す)
        draw_node(rank_c_pct, COLOR_P, "C")       # 水色/青系 (COLOR_P)
        draw_node(rank_b_pct, COLOR_N, "B")       # 緑系 (COLOR_N)
        
        # Aノード（アクティブ判定）
        is_a_focused = (self.menu_cursor == 0)
        nx_a = draw_node(rank_a_pct, COLOR_B_EMG, "A", is_a_focused) # 赤系 (COLOR_B_EMG)

        # ---------------------------------------------
        # 2. 理論値・各ランク点数の描画
        # ---------------------------------------------
        table_y = 365
        row_h = 65
        col1_x = center_x - 450
        col2_x = center_x + 250
        col3_x = center_x + 450

        font_tbl = self.font_normal
        draw_text_with_outline(painter, "理論値", font_tbl, COLOR_WHITE, COLOR_OUTLINE_BLACK, col1_x, table_y, "left", passes=8)
        draw_text_with_outline(painter, f"{theory_score} 点", font_tbl, COLOR_WHITE, COLOR_OUTLINE_BLACK, col2_x, table_y, "right", passes=8)
        draw_text_with_outline(painter, "(100%)", font_tbl, COLOR_WHITE, COLOR_OUTLINE_BLACK, col3_x, table_y, "right", passes=8)

        draw_text_with_outline(painter, "Rank A", font_tbl, COLOR_B_EMG, COLOR_WHITE, col1_x, table_y + row_h, "left", passes=8)
        draw_text_with_outline(painter, f"{score_a} 点", font_tbl, COLOR_B_EMG, COLOR_WHITE, col2_x, table_y + row_h, "right", passes=8)
        draw_text_with_outline(painter, f"({rank_a_pct:>3}%)", font_tbl, COLOR_WHITE, COLOR_OUTLINE_BLACK, col3_x, table_y + row_h, "right", passes=8)

        draw_text_with_outline(painter, "Rank B", font_tbl, COLOR_N, COLOR_WHITE, col1_x, table_y + row_h*2, "left", passes=8)
        draw_text_with_outline(painter, f"{score_b} 点", font_tbl, COLOR_N, COLOR_WHITE, col2_x, table_y + row_h*2, "right", passes=8)
        draw_text_with_outline(painter, f"( {rank_b_pct}%)", font_tbl, COLOR_WHITE, COLOR_OUTLINE_BLACK, col3_x, table_y + row_h*2, "right", passes=8)

        draw_text_with_outline(painter, "Rank C", font_tbl, COLOR_P, COLOR_WHITE, col1_x, table_y + row_h*3, "left", passes=8)
        draw_text_with_outline(painter, f"{score_c} 点", font_tbl, COLOR_P, COLOR_WHITE, col2_x, table_y + row_h*3, "right", passes=8)
        draw_text_with_outline(painter, f"( {rank_c_pct}%)", font_tbl, COLOR_WHITE, COLOR_OUTLINE_BLACK, col3_x, table_y + row_h*3, "right", passes=8)

        # ---------------------------------------------
        # 3. 採点開始ボタンと説明文
        # ---------------------------------------------
        draw_menu_item("採点を開始する", 645, (self.menu_cursor == 1), 1, "center")

        desc_y = 693 
        desc_h = 312 
        painter.setPen(QPen(QColor(150, 150, 150), 2))
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(150, int(desc_y), 1620, int(desc_h), 10, 10)

        desc_lines = [
            "（※理論値 ＝ n₁ × 500 ＋ n₂ × 500 ＋ n₃ × 300）",
            "理論値とは、採点対象となる各駅で、各加点項目の全てを満点で獲得した場合の合計点数です。",
            "停止位置の採点対象となる駅の総数n₁ : 始発駅以外の停車駅の数",
            "基本制動の採点対象となる駅の総数n₂ : 始発駅以外 かつ 基本制動設定がOFF ではない停車駅の数",
            "運転時分の採点対象となる駅の総数n₃ : 採時駅の数",
            "",
            "Rank A は理論値の 60～90％ の間で調整が可能です。",
            "Rank B = Rank A × 0.8、Rank C = Rank B × 0.8 （整数値に四捨五入）で自動的に計算されます。",
            "やり直しをせずに試験を終え、かつ Rank A 以上の点数の場合には Rank S が与えられます。"
        ]
        for j, line in enumerate(desc_lines):
            draw_text_with_outline(painter, line, self.font_desc, COLOR_WHITE, COLOR_OUTLINE_BLACK, 180, desc_y + 35 + (j * 33), "left", passes=8)
    
    if getattr(self, 'dropdown_active', False) and len(getattr(self, 'dropdown_options', [])) > 0:
        fm = QFontMetrics(self.font_menu)
        max_w = max([fm.horizontalAdvance(opt["name"]) for opt in self.dropdown_options]) + 60
        box_w = max(250, max_w) 
        
        visible_opts = self.dropdown_options[getattr(self, 'dropdown_scroll', 0) : getattr(self, 'dropdown_scroll', 0) + 7]
        row_h = fm.height() + 16
        box_h = row_h * len(visible_opts) + 20
        
        start_x = center_x - (box_w / 2)
        start_y = BASE_SCREEN_H / 2 - (box_h / 2)
        
        painter.setPen(QPen(QColor(100, 100, 100), 4))
        painter.setBrush(QColor(20, 20, 20, 240))
        painter.drawRoundedRect(int(start_x), int(start_y), int(box_w), int(box_h), 8, 8)
        
        if getattr(self, 'dropdown_scroll', 0) > 0:
            draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, start_y - 10, "center", passes=8)
            
        for i, opt in enumerate(visible_opts):
            actual_idx = getattr(self, 'dropdown_scroll', 0) + i
            item_y = start_y + 10 + (i * row_h)
            if actual_idx == getattr(self, 'dropdown_cursor', 0):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(start_x + 5), int(item_y), int(box_w - 10), int(row_h), 4, 4)
                
            text_y_base = item_y + fm.ascent() + 8
            draw_text_with_outline(painter, opt["name"], self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, text_y_base, "center", passes=8)
            
        if getattr(self, 'dropdown_scroll', 0) + 7 < len(getattr(self, 'dropdown_options', [])):
            draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, start_y + box_h + 47, "center", passes=8)
    
    # ==========================================================
    # ★ 新規追加: 採点結果画面 (menu_state == 11)
    # ==========================================================
    elif self.menu_state == 11:
        painter.setPen(Qt.PenStyle.NoPen)
        # 背景を極大化して塗りつぶす（解像度変更時の黒切れ防止）
        painter.setBrush(QColor(15, 15, 15, 245))
        painter.drawRect(-5000, -5000, 10000, 10000)

        # ---------------------------------------------
        # 1. ヘッダー情報
        # ---------------------------------------------
        # [Y座標調整] ヘッダー全体の上部からの基本位置
        header_y = 137 
        
        draw_text_with_outline(painter, "=== 採点結果 ===", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, header_y, "center", passes=8)
        
        font_meta = self.font_normal
        # [Y座標調整] タイトル関連の行間 (header_y からの相対距離)
        draw_text_with_outline(painter, getattr(self, 'meta_route', '路線データ未取得'), font_meta, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, header_y + 90, "center", passes=8)
        draw_text_with_outline(painter, getattr(self, 'meta_vehicle', '車両データ未取得'), font_meta, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, header_y + 270, "center", passes=8)
        draw_text_with_outline(painter, getattr(self, 'meta_title', 'シナリオデータ未取得'), font_meta, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, header_y + 150, "center", passes=8)

        sta_start = get_sta_name(getattr(self, 'setting_start_idx', 0))
        sta_end = get_sta_name(getattr(self, 'setting_end_idx', -1))
        # [Y座標調整] 区間の表示位置
        draw_text_with_outline(painter, f"区間 ： {sta_start} ～ {sta_end}", font_meta, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, header_y + 210, "center", passes=8)

        # [Y座標調整] 区間とテーブルを区切る上の水平線の位置
        painter.setPen(QPen(QColor(100, 100, 100), 3))
        painter.drawLine(int(center_x - 650), int(header_y + 295), int(center_x + 650), int(header_y + 295))

        # ---------------------------------------------
        # 2. 内訳テーブルの描画
        # ---------------------------------------------
        table_y = header_y + 355
        row_h = 58 
        
        col1_lbl_x = center_x - 600
        col1_val_x = center_x - 100
        col2_lbl_x = center_x + 100
        col2_val_x = center_x + 600

        sd = getattr(self, 'score_details', {})
        
        # ==========================================================
        # ★ 冗長なgetattrをやめ、直接変数を参照してOFF判定！
        is_ats_off   = not self.pen_ats
        is_limit_off = not self.pen_limit
        is_jerk_off  = not self.pen_jerk
        is_eb_off    = not self.pen_eb
        is_init_off  = all(r.get("apply", "") == "OFF" for r in self.penalty_init_rules)
        is_rel_off   = all(r.get("release", "") == "OFF" for r in self.penalty_init_rules)
        #is_time_off = (len(self.get_timing_target_stas()) == 0)
        is_time_off  = getattr(self, 'is_time_off', False)
        is_base_off  = getattr(self, 'is_base_off', False)

        # 色を安全にQColor化するヘルパー
        def get_qc(color_val):
            return QColor(*color_val) if isinstance(color_val, tuple) else QColor(color_val)

        def draw_score_row(label1, key1, label2, key2, y_pos, is_off1=False, is_off2=False):
            # 点数の色判定用ヘルパー
            def get_val_color(val, is_off):
                c = get_qc(COLOR_B_EMG if val < 0 else (COLOR_N if val > 0 else COLOR_WHITE))
                if is_off: c.setAlpha(60)
                return c

            # --- 左列 ---
            val1 = sd.get(key1, 0)
            # ★修正: 確実に get_qc() を通す
            lbl_c1 = get_qc(COLOR_WHITE)
            v1_out = get_qc(COLOR_WHITE if val1 != 0 and not is_off1 else COLOR_OUTLINE_BLACK)

            val_str1 = str(val1)
            if is_off1: 
                lbl_c1.setAlpha(60) # ラベル透明度下げる
                val_str1 = ""       # OFFの時は「0」の数字ごと消し去る

            draw_text_with_outline(painter, label1, self.font_menu, lbl_c1, COLOR_OUTLINE_BLACK, col1_lbl_x, y_pos, "left", passes=8)
            draw_text_with_outline(painter, val_str1, self.font_menu, get_val_color(val1, is_off1), v1_out, col1_val_x, y_pos, "right", passes=8)
            
            # --- 右列 ---
            val2 = sd.get(key2, 0)
            # ★修正: 確実に get_qc() を通す
            lbl_c2 = get_qc(COLOR_WHITE)
            v2_out = get_qc(COLOR_WHITE if val2 != 0 and not is_off2 else COLOR_OUTLINE_BLACK)

            val_str2 = str(val2)
            if is_off2: 
                lbl_c2.setAlpha(60)
                val_str2 = ""       # OFFの時は「0」の数字ごと消し去る

            draw_text_with_outline(painter, label2, self.font_menu, lbl_c2, COLOR_OUTLINE_BLACK, col2_lbl_x, y_pos, "left", passes=8)
            draw_text_with_outline(painter, val_str2, self.font_menu, get_val_color(val2, is_off2), v2_out, col2_val_x, y_pos, "right", passes=8)

        draw_score_row("運転時分", "time", "ATS信号無視", "ats", table_y, is_time_off, is_ats_off)
        draw_score_row("停止位置", "stop", "速度制限超過", "limit", table_y + row_h, False, is_limit_off)
        draw_score_row("基本制動", "base_brake", "初動ブレーキ", "init_brake", table_y + row_h * 2, is_base_off, is_init_off)
        draw_score_row("転動", "roll", "緩和ブレーキ", "rel_brake", table_y + row_h * 3, False, is_rel_off)
        draw_score_row("停車時衝動", "jerk", "非常ブレーキ", "eb", table_y + row_h * 4, is_jerk_off, is_eb_off)
        # ==========================================================

        bonus_val = sd.get("bonus", 0)
        b_color = COLOR_N if bonus_val > 0 else COLOR_WHITE
        bo_color = COLOR_WHITE if bonus_val > 0 else COLOR_OUTLINE_BLACK
        draw_text_with_outline(painter, "ボーナス", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x - 250, table_y + row_h * 5.5, "left", passes=8)
        draw_text_with_outline(painter, f"{bonus_val} 点", self.font_menu, b_color, bo_color, center_x + 250, table_y + row_h * 5.5, "right", passes=8)

        painter.setPen(QPen(QColor(100, 100, 100), 3))
        painter.drawLine(int(center_x - 650), int(table_y + row_h * 5.9), int(center_x + 650), int(table_y + row_h * 5.9))

        # ---------------------------------------------
        # 3. 総合評価の計算と描画
        # ---------------------------------------------
        total_score = getattr(self, 'score', 0)
        retries = getattr(self, 'total_retry_count', 0)
        
        rank_a_pct = int(round(getattr(self, 'rank_a_ratio', 0.8) * 100))
        theory_score = getattr(self, 'theoretical_score', 12500)
        score_a = int(round(theory_score * (rank_a_pct / 100.0)))
        score_b = int(round(score_a * 0.8))
        score_c = int(round(score_a * 0.8 * 0.8))

        eval_rank = "D"
        eval_color = (150, 150, 150)
        
        if total_score >= score_a:
            if retries == 0:
                eval_rank = "S"
                eval_color = (255, 215, 0)
            else:
                eval_rank = "A"
                eval_color = COLOR_B_EMG
        elif total_score >= score_b:
            eval_rank = "B"
            eval_color = COLOR_N
        elif total_score >= score_c:
            eval_rank = "C"
            eval_color = COLOR_P

        bottom_y = table_y + row_h * 7.4
        draw_text_with_outline(painter, "合計", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x - 600, bottom_y, "left", passes=8)
        draw_text_with_outline(painter, f"{total_score} 点", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x + 100, bottom_y, "right", passes=8)
        
        draw_text_with_outline(painter, "評価", self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x + 325, bottom_y, "left", passes=8)
        
        painter.setPen(Qt.PenStyle.NoPen)
        glow_c = QColor(*eval_color) if isinstance(eval_color, tuple) else QColor(eval_color)
        glow_c.setAlpha(50)
        painter.setBrush(glow_c)
        painter.drawEllipse(int(center_x + 505), int(bottom_y - 74), 90, 90)
        
        f_rank = QFont(self.font_big)
        if f_rank.pointSize() > 0:
            f_rank.setPointSize(int(f_rank.pointSize()*1.2))
        elif f_rank.pixelSize() > 0:
            f_rank.setPixelSize(int(f_rank.pixelSize()*1.2))
            
        draw_text_with_outline(painter, eval_rank, f_rank, eval_color, COLOR_WHITE, center_x + 550, bottom_y + 5, "center", passes=8)

        # ==========================================================
        # 4. 操作ボタンと [H] ボタンの描画 (スクショ中は隠す！)
        # ==========================================================
        if not getattr(self, 'is_capturing_screenshot', False):
            btn_text = "閉じる" if getattr(self, 'is_result_saved', False) else "結果を保存する"
            draw_menu_item(btn_text, bottom_y + 110, (self.menu_cursor == 0), 0, "center")

    # ==========================================================
    # ★ 新規追加: 操作説明（ヘルプ）ボタンと小ウィンドウの描画
    # ==========================================================
    if self.menu_state not in [0, 3, 8] and not getattr(self, 'is_capturing_screenshot', False):
        # 画面右下にヘルプボタンを描画
        help_text = "操作説明 : H"
        fm_help = QFontMetrics(self.font_desc)
        hw = fm_help.horizontalAdvance(help_text) + 30
        hh = fm_help.height() + 10
        
        logical_right = self.width() / (2 * menu_scale) + BASE_SCREEN_W / 2
        logical_bottom = self.height() / (2 * menu_scale) + BASE_SCREEN_H / 2
        hx, hy = logical_right - hw - 10, logical_bottom - hh - 10
        
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.setBrush(QColor(50, 50, 50, 200))
        painter.drawRoundedRect(int(hx), int(hy), int(hw), int(hh), 5, 5)
        
        draw_text_with_outline(painter, help_text, self.font_desc, COLOR_WHITE, COLOR_OUTLINE_BLACK, hx + 15, hy + fm_help.ascent() + 7, "left", passes=8)
        self.menu_click_zones.append((hx, hy, hx + hw, hy + hh, 999))

        # ==========================================================
    # ★ 修正: 操作説明 [H] オーバーレイ (リストの行数で高さが自動可変)
    # ==========================================================
    if getattr(self, 'show_help', False):
        # 画面全体を暗転
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRect(-2000, -2000, 6000, 6000)

        # 1. 状態に応じたリストを先に作る
        help_items = []
        if self.menu_state in [1, 2, 3]:
            help_items.append(("↑↓", "移動"))
        elif self.menu_state != 11:
            help_items.append(("↑↓←→", "移動"))
        
        # 保存前のリザルト画面は Enter のみ。それ以外は戻る・閉じるを追加。
        if self.menu_state == 11 and not getattr(self, 'is_result_saved', False):
            help_items.append(("Enter", "決定"))
        else:
            help_items.extend([
                ("Enter", "決定"),
                ("Backspace", "戻る"),
                ("F6", "閉じる")
            ])

        # 2. リストの数(len)に応じて、ウィンドウの高さを自動計算！
        # (例: 1行なら185px, 4行なら350px)
        win_w = 500
        win_h = 130 + (len(help_items) * 55)
        win_x = center_x - (win_w / 2)
        win_y = (BASE_SCREEN_H - win_h) / 2
        
        # 3. 枠とタイトルの描画
        painter.setBrush(QColor(30, 30, 30, 240))
        painter.setPen(QPen(QColor(150, 150, 150), 3))
        painter.drawRoundedRect(int(win_x), int(win_y), int(win_w), int(win_h), 12, 12)
        draw_text_with_outline(painter, "=== 操作説明 ===", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, win_y + 60, "center", passes=8)
        
        # 4. 項目の描画
        colon_x = center_x + 45 
        start_y = win_y + 130 # 高さが可変になったので、パディング等の複雑な計算は不要！
        
        for i, (left_text, right_text) in enumerate(help_items):
            y_pos = start_y + i * 55
            draw_text_with_outline(painter, left_text, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, colon_x - 20, y_pos, "right", passes=8)
            draw_text_with_outline(painter, ":", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, colon_x, y_pos, "center", passes=8)
            draw_text_with_outline(painter, right_text, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, colon_x + 20, y_pos, "left", passes=8)

    painter.restore()