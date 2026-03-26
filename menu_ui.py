from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPen
from config import *
from utils import draw_text_with_outline

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
            draw_x = center_x
            box_x = center_x - (text_w / 2) - 30 + GLOBAL_BOX_X_OFFSET
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
            self.menu_click_zones.append((center_x - 400, box_y, center_x + 400, box_y + box_h, action_idx))
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

    title_text = ""
    title_y = 200
    if self.menu_state == 1: title_text = "=== メニュー ==="
    elif self.menu_state == 2: title_text = "=== 選択した駅からやり直す ==="
    elif self.menu_state == 4: title_text = "=== 環境設定 ==="
    elif self.menu_state in [5, 7]: 
        title_text = "=== 採点設定 (1/2) ==="
        title_y = 100
    elif self.menu_state == 6: 
        title_text = "=== 採点設定 (2/2) : 減点項目 ==="
        title_y = 100

    if title_text and self.menu_state not in [3, 8]:
        draw_text_with_outline(painter, title_text, self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, title_y, "center", passes=8)

    if self.menu_state not in [3, 8]:
        if self.menu_state in [5, 6, 7]:
            draw_text_with_outline(painter, "↑ ↓ ← → : 選択  |  Enter / Click : 決定・リスト開閉", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 980, "center", passes=8)
            draw_text_with_outline(painter, "Backspace : 戻る / 白紙入力(項目削除)  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 1030, "center", passes=8)
        else:
            draw_text_with_outline(painter, "↑ ↓ : 選択  |  Enter / Click : 決定・切替", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 980, "center", passes=8)
            draw_text_with_outline(painter, "Backspace : 戻る  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 1030, "center", passes=8)

    def get_sta_name(idx):
        if not self.station_list: return "データ未受信"
        if idx == -1:
            for i in range(len(self.station_list)-1, -1, -1):
                if self.station_list[i].get("is_timing", False):
                    return self.station_list[i]["name"]
            return "不明"
        if 0 <= idx < len(self.station_list):
            return self.station_list[idx]["name"]
        return "不明"

    if self.menu_state == 1:
        items = self.menu_items_on if self.is_scoring_mode else self.menu_items_off
        for i, text in enumerate(items):
            draw_menu_item(text, 350 + i * 80, (i == self.menu_cursor), i, "center")

    elif self.menu_state == 2:
        # ==========================================================
        # ★★★ セーブデータ画面 (選択した駅からやり直す) 微調整パラメータ ★★★
        # ==========================================================
        SAVE_TITLE_Y = 200
        SAVE_NO_DATA_Y = 450
        SAVE_ARROW_UP_Y = 260
        SAVE_LIST_Y = 320
        SAVE_ROW_H = 80
        SAVE_VISIBLE_COUNT = 6
        SAVE_ARROW_DOWN_OFFSET = 30
        
        SAVE_COL_BOX_W = 1560
        SAVE_COL_BOX_X_OFFSET = 0
        
        SAVE_COL_STA_W = 380
        SAVE_COL_POS_W = 300
        SAVE_COL_SCORE_W = 350
        SAVE_COL_TIME_W = 320
        SAVE_COL_GAP = 50
        # ==========================================================
        
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
                draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, SAVE_LIST_Y + SAVE_VISIBLE_COUNT * SAVE_ROW_H + SAVE_ARROW_DOWN_OFFSET, "center", passes=8)

    elif self.menu_state == 3:
        cp = self.save_data[self.target_retry_idx]
        msg = f"【 {cp.get('station_name', '駅')} 】からやり直しますか？"
        fm_big = QFontMetrics(self.font_big)
        max_msg_w = 1700
        actual_w = fm_big.horizontalAdvance(msg)
        
        if actual_w > max_msg_w:
            sr = max_msg_w / actual_w
            cy = 350 - fm_big.ascent() + fm_big.height() / 2.0
            painter.save()
            painter.translate(center_x, cy)
            painter.scale(sr, sr)
            painter.translate(-center_x, -cy)
            draw_text_with_outline(painter, msg, self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 350, "center", passes=8)
            painter.restore()
        else:
            draw_text_with_outline(painter, msg, self.font_big, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 350, "center", passes=8)
            
        draw_text_with_outline(painter, "※これ以降のセーブデータは破棄されます", self.font_normal, COLOR_B_EMG, COLOR_OUTLINE_BLACK, center_x, 450, "center", passes=8)
        
        self.menu_click_zones.clear()
        fm_normal = QFontMetrics(self.font_normal)
        
        fixed_box_w = 220  
        fixed_box_h = fm_normal.height() + 16 
        box_offset_x = -2  
        
        for i, text in enumerate(["はい", "いいえ"]):
            draw_x = center_x
            box_x = center_x - (fixed_box_w / 2) + box_offset_x
            box_y = 600 + i * 80 - fm_normal.ascent() - 6 - (fm_normal.descent() // 2) + 1
            
            if i == self.menu_cursor:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(30, 80, 150, 200))
                painter.drawRoundedRect(int(box_x), int(box_y), int(fixed_box_w), int(fixed_box_h), 8, 8)
                
            draw_text_with_outline(painter, text, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, draw_x, 600 + i * 80, "center", passes=8)
            self.menu_click_zones.append((box_x, box_y, box_x + fixed_box_w, box_y + fixed_box_h, i))

        draw_text_with_outline(painter, "↑ ↓ : 選択  |  Enter / Click : 決定・切替", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 870, "center", passes=8)
        draw_text_with_outline(painter, "Backspace : 戻る  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 930, "center", passes=8)

    elif self.menu_state == 4:
        for i in range(7):
            key = self.settings_keys[i]
            name = self.settings_names[i]
            is_on = self.disp_settings[key]
            draw_setting_item(name, is_on, 300 + i * 70, (i == self.menu_cursor), i)

    elif self.menu_state in [5, 7]:
        sta_start = get_sta_name(self.setting_start_idx)
        sta_end = get_sta_name(self.setting_end_idx)

        # =========================================================
        # ★ メイン設定画面 (1/2) のレイアウト微調整パラメータ
        # =========================================================
        MAIN_X_OFFSET = 50   
        list_y_start  = 200
        row_h         = 65
        label_x       = 100 + MAIN_X_OFFSET      
        val_x_start   = 550 + MAIN_X_OFFSET  
        # =========================================================
        
        fm = QFontMetrics(self.font_menu)

        def draw_label(row_idx, text, y, text_color, outline_color):
            vis_rules = min(3, len(self.brake_rules))
            if self.menu_state == 5 and (self.menu_cursor == row_idx or (row_idx == 4 and 4 <= self.menu_cursor < 4 + vis_rules)):
                if self.menu_cursor_x == -1:
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
                        is_focused = (self.menu_state == 5 and self.menu_cursor == row_idx and self.menu_cursor_x == interactive_idx and not self.dropdown_active)
                    else:
                        is_focused = (self.menu_state == 7 and self.sub_cursor == row_idx and self.sub_cursor_x == interactive_idx and not self.dropdown_active)
                        
                    if is_focused:
                        painter.setPen(Qt.PenStyle.NoPen)
                        if self.menu_state == 5 and row_idx == 1 and self.input_mode_active:
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

        draw_label(0, "採点区間", list_y_start, COLOR_WHITE, COLOR_OUTLINE_BLACK)
        draw_blocks(0, [
            {"text": sta_start, "interactive": True, "max_w": MAIN_ROW0_STA_MAX_W},
            {"text": "～", "interactive": False},
            {"text": sta_end, "interactive": True, "max_w": MAIN_ROW0_STA_MAX_W}
        ], list_y_start)

        tl = int(self.bve_train_length)
        draw_label(1, "停車駅採点範囲", list_y_start + row_h, COLOR_WHITE, COLOR_OUTLINE_BLACK)
        margin_disp = self.input_buffer if self.input_mode_active else str(self.setting_stop_distance)
        if not margin_disp: margin_disp = "_" 
        draw_blocks(1, [
            {"text": margin_disp, "interactive": True},
            {"text": "m", "interactive": False}
        ], list_y_start + row_h)

        draw_label(2, "運転時分", list_y_start + row_h*2, COLOR_N, COLOR_WHITE)
        change_x_time = label_x + fm.horizontalAdvance("運転時分　")
        is_focused_time = (self.menu_state == 5 and self.menu_cursor == 2 and self.menu_cursor_x == 0 and not self.dropdown_active)
        if is_focused_time:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(change_x_time - 10 + GLOBAL_BOX_X_OFFSET), int(list_y_start + row_h*2 - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(fm.horizontalAdvance("変更") + 20), int(fm.height() + 12), 6, 6)
        draw_text_with_outline(painter, "変更", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, change_x_time, list_y_start + row_h*2, "left", passes=8)
        
        # ★ 修正箇所: 採時駅が1つでもあるかチェックし、すべてOFFなら赤色のOFFを表示
        has_timing_station = False
        timing_targets = self.get_timing_target_stas()
        if timing_targets:
            for t_idx in timing_targets:
                if self.is_station_timing(t_idx):
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
        is_focused = (self.menu_state == 5 and self.menu_cursor == 4 and self.menu_cursor_x == 0 and not self.dropdown_active)
        if is_focused:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(change_x - 10 + GLOBAL_BOX_X_OFFSET), int(list_y_start + row_h*4 - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(text_w + 20), int(fm.height() + 12), 6, 6)
        draw_text_with_outline(painter, change_text, self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, change_x, list_y_start + row_h*4, "left", passes=8)

        vis_rules = min(3, len(self.brake_rules))
        FIXED_STA_W = 280      
        
        box_y_offset = 12
        box_width = 1210
        box_height = row_h * vis_rules + 5
        
        is_summary_focused = (self.menu_state == 5 and self.menu_cursor == 4 and self.menu_cursor_x == 1 and not self.dropdown_active)
        if is_summary_focused:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 80, 150, 150))
            painter.drawRoundedRect(int(val_x_start - 20 + GLOBAL_BOX_X_OFFSET), int(list_y_start + row_h*4 - fm.ascent() - box_y_offset), box_width, int(box_height), 6, 6)

        col_summary_x = val_x_start + FIXED_STA_W + 15 + (fm.horizontalAdvance("～") // 2)

        if self.summary_scroll > 0:
            draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, col_summary_x, list_y_start + row_h*4 - 68, "center", passes=8)
            
        for i in range(vis_rules):
            r_idx = self.summary_scroll + i
            if r_idx >= len(self.brake_rules): break
            r_y = list_y_start + row_h * (4 + i) 
            rule = self.brake_rules[r_idx]
            r_start = get_sta_name(self.setting_start_idx) if r_idx == 0 else get_sta_name(self.brake_rules[r_idx-1]["end_idx"])
            r_end = get_sta_name(self.setting_end_idx) if rule["end_idx"] == -1 else get_sta_name(rule["end_idx"])
            
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
            
            if rule["apply"] == "OFF":
                draw_text_with_outline(painter, "OFF", self.font_menu, COLOR_B_EMG, COLOR_WHITE, cx, r_y, "left", passes=8)
            else:
                draw_text_with_outline(painter, rule["apply"], self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += fm.horizontalAdvance(rule["apply"]) + 15
                draw_text_with_outline(painter, "制動 /", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += fm.horizontalAdvance("制動 /") + 15
                draw_text_with_outline(painter, rule["release"], self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                cx += fm.horizontalAdvance(rule["release"]) + 15
                draw_text_with_outline(painter, "緩め", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)

        if self.summary_scroll + 3 < len(self.brake_rules):
            draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, col_summary_x, list_y_start + row_h*(4 + vis_rules), "center", passes=8)

        last_row = 5
        btn_y = 720 
        draw_menu_item("次へ (減点項目の設定)", btn_y, (self.menu_state == 5 and self.menu_cursor == last_row and self.menu_cursor_x == -1), last_row, "center")

        desc_y = 770 
        desc_h = 135 
        painter.setPen(QPen(QColor(150, 150, 150), 2))
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(150, int(desc_y), 1620, int(desc_h), 10, 10)

        actual_margin = self.setting_stop_distance

        desc_dict = {
            0: "【 採点区間 】\n採点を行う区間を設定します。\n（※デフォルト:始発駅～終着駅）",
            1: f"【 停車駅採点範囲 】\n停車駅において、採点を行う停止位置からの距離を設定します。キーボードで数値入力が可能です。\n列車長より短い値は入力できません。（※列車長 {tl} m ＋ マージン {max(0, actual_margin - tl)} m ＝ 判定距離 {actual_margin} m）",
            2: "【 運転時分 】\n指定された採時駅への到着・出発時刻の正確さを採点します。\n（※0～±9秒 : 300点、±10～±19秒 : 200点、±20秒～±29秒 : 100点、±30秒～ : 0点）",
            3: "【 停止位置 】\n停車駅での停止位置の正確さを採点します。誤差0.00 mに近いほど高得点になります。\n （※許容範囲に停車した時、停止位置x[m]とすると、点数y = 500 × (1 - x)）",
            4: "【 基本制動 】\n駅に停車する際、指定された回数で制動・緩め操作が行われたかを採点します。\n（※基本制動の条件を満たすと500点、さらに0.00 mに停車した場合はボーナス500点）",
            last_row: "次の設定ページ（減点項目の設定）へ進みます。"
        }
        
        desc_text = ""
        if self.menu_state == 5:
            if self.menu_cursor == 2 and self.menu_cursor_x == 0:
                desc_text = "【 運転時分 設定 】\n駅ごとの採時 / 非採時の設定を個別に変更します。\n（※採点開始駅は非採時で固定されます）"
            elif self.menu_cursor == 4 and self.menu_cursor_x == 0:
                desc_text = "【 基本制動 設定 】\n特定区間だけ異なる基本制動ルールを適用したい場合に追加・編集します。\nルールはチェーン（数珠繋ぎ）になります。"
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
            
            vis_rules = min(5, len(self.brake_rules)) 
            
            # =========================================================
            # ★ 基本制動設定UI 微調整パラメータ
            # =========================================================
            sub_val_x_start = 300  
            SUB_FIXED_STA_W = 350  
            gap_tilde = 15         
            gap_sta2 = 15          
            gap_colon = 15         
            gap_rule = 20          
            # =========================================================
            
            colon_x = sub_val_x_start + SUB_FIXED_STA_W + gap_tilde + fm.horizontalAdvance("～") + gap_sta2 + SUB_FIXED_STA_W + gap_colon
            sub_col_summary_x = colon_x + (fm.horizontalAdvance(":") // 2)

            if self.sub_scroll > 0:
                draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, sub_col_summary_x, sub_y + 200, "center", passes=8)
            
            sub_list_y_start = sub_y + 275 
            
            for i in range(vis_rules):
                r_idx = self.sub_scroll + i
                if r_idx >= len(self.brake_rules): break
                rule = self.brake_rules[r_idx]
                r_start = sta_start if r_idx == 0 else get_sta_name(self.brake_rules[r_idx-1]["end_idx"])
                r_end = sta_end if rule["end_idx"] == -1 else get_sta_name(rule["end_idx"])
                is_last = (r_idx == len(self.brake_rules) - 1)
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
                is_focused = (self.sub_cursor == r_idx and self.sub_cursor_x == 0 and not self.dropdown_active)
                
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

                if rule["apply"] == "OFF":
                    tw = fm.horizontalAdvance("OFF")
                    if self.sub_cursor == r_idx and self.sub_cursor_x == idx_apply and not self.dropdown_active:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(HIGHLIGHT_COLOR)
                        painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(tw + 20), int(fm.height() + 12), 6, 6)
                    draw_text_with_outline(painter, "OFF", self.font_menu, COLOR_B_EMG, COLOR_WHITE, cx, r_y, "left", passes=8)
                else:
                    tw = fm.horizontalAdvance(rule["apply"])
                    if self.sub_cursor == r_idx and self.sub_cursor_x == idx_apply and not self.dropdown_active:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(HIGHLIGHT_COLOR)
                        painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(tw + 20), int(fm.height() + 12), 6, 6)
                    draw_text_with_outline(painter, rule["apply"], self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                    cx += tw + 15
                    
                    draw_text_with_outline(painter, "制動 /", self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
                    cx += fm.horizontalAdvance("制動 /") + 15
                    
                    tw_rel = fm.horizontalAdvance(rule["release"])
                    if self.sub_cursor == r_idx and self.sub_cursor_x == idx_release and not self.dropdown_active:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(HIGHLIGHT_COLOR)
                        painter.drawRoundedRect(int(cx - 10 + GLOBAL_BOX_X_OFFSET), int(r_y - fm.ascent() - 6 + SCORING_BOX_Y_OFFSET), int(tw_rel + 20), int(fm.height() + 12), 6, 6)
                    draw_text_with_outline(painter, rule["release"], self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, cx, r_y, "left", passes=8)
            
            if self.sub_scroll + 5 < len(self.brake_rules):
                draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, sub_col_summary_x, sub_list_y_start + (5 * 70) + 10, "center", passes=8)
            
            row_undo = len(self.brake_rules) if len(self.brake_rules) > 1 else -1
            row_done = len(self.brake_rules) + 1 if len(self.brake_rules) > 1 else len(self.brake_rules)
            
            btn_base_y = sub_list_y_start + (5 * 70) + 90 
            if row_undo != -1:
                draw_menu_item("１つ前の設定を修正する (この行を削除)", btn_base_y, (self.sub_cursor == row_undo), row_undo, "center")
            draw_menu_item("設定完了", btn_base_y + 80, (self.sub_cursor == row_done), row_done, "center")

    elif self.menu_state == 6:
        draw_text_with_outline(painter, "=== 採点設定 (2/2) : 減点項目 ===", self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, 200, "center", passes=8)
        draw_text_with_outline(painter, "※減点項目の個別設定は現在開発中です", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 300, "center", passes=8)
        
        draw_menu_item("【デバッグ】全減点項目をONにして採点を開始する", 500, (self.menu_cursor == 0), 0, "center")
        draw_menu_item("ページ1に戻る", 600, (self.menu_cursor == 1), 1, "center")

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

        targets = self.get_timing_target_stas()
        
        if not targets:
            draw_text_with_outline(painter, "設定可能な駅がありません", self.font_normal, COLOR_B_EMG, COLOR_OUTLINE_BLACK, center_x, LIST_Y + 50, "center", passes=8)
        else:
            if self.timing_scroll > 0:
                draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, ARROW_UP_Y, "center", passes=8)
            
            fm = QFontMetrics(self.font_normal)
            box_x_base = center_x - (TIMING_BOX_W / 2) + TIMING_BOX_X_OFFSET

            for i in range(TIMING_VISIBLE_COUNT):
                list_idx = self.timing_scroll + i
                if list_idx >= len(targets): break
                
                sta_idx = targets[list_idx]
                st = self.station_list[sta_idx]
                sta_name = st.get("name", "不明な駅")
                
                is_timing = self.is_station_timing(sta_idx)
                is_start = (sta_idx == self.setting_start_idx)
                
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

                if list_idx == self.timing_cursor:
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

            if self.timing_scroll + TIMING_VISIBLE_COUNT < len(targets):
                draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, ARROW_DOWN_Y, "center", passes=8)
                
            btn_text = "設定完了"
            btn_w = fm.horizontalAdvance(btn_text) + 60
            btn_h = fm.height() + 16
            btn_x = center_x - (btn_w / 2)
            btn_rect_y = BTN_Y - fm.ascent() - 6 - (fm.descent() // 2) + 1
            
            if self.timing_cursor == len(targets):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(btn_x + TIMING_HIGHLIGHT_OFFSET_X), int(btn_rect_y + TIMING_HIGHLIGHT_OFFSET_Y), int(btn_w), int(btn_h), 8, 8)
                
            draw_text_with_outline(painter, btn_text, self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, BTN_Y, "center", passes=8)
            self.menu_click_zones.append((btn_x, btn_rect_y, btn_x + btn_w, btn_rect_y + btn_h, len(targets)))

    if self.dropdown_active and len(self.dropdown_options) > 0:
        fm = QFontMetrics(self.font_menu)
        max_w = max([fm.horizontalAdvance(opt["name"]) for opt in self.dropdown_options]) + 60
        box_w = max(250, max_w) 
        
        visible_opts = self.dropdown_options[self.dropdown_scroll : self.dropdown_scroll + 7]
        row_h = fm.height() + 16
        box_h = row_h * len(visible_opts) + 20
        
        start_x = center_x - (box_w / 2)
        start_y = BASE_SCREEN_H / 2 - (box_h / 2)
        
        painter.setPen(QPen(QColor(100, 100, 100), 4))
        painter.setBrush(QColor(20, 20, 20, 240))
        painter.drawRoundedRect(int(start_x), int(start_y), int(box_w), int(box_h), 8, 8)
        
        if self.dropdown_scroll > 0:
            draw_text_with_outline(painter, "▲", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, start_y - 10, "center", passes=8)
            
        for i, opt in enumerate(visible_opts):
            actual_idx = self.dropdown_scroll + i
            item_y = start_y + 10 + (i * row_h)
            if actual_idx == self.dropdown_cursor:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(HIGHLIGHT_COLOR)
                painter.drawRoundedRect(int(start_x + 5), int(item_y), int(box_w - 10), int(row_h), 4, 4)
                
            text_y_base = item_y + fm.ascent() + 8
            draw_text_with_outline(painter, opt["name"], self.font_menu, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, text_y_base, "center", passes=8)
            
        if self.dropdown_scroll + 7 < len(self.dropdown_options):
            draw_text_with_outline(painter, "▼", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, start_y + box_h + 47, "center", passes=8)

    painter.restore()