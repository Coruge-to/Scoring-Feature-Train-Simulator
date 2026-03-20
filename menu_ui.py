from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics
from config import *
from utils import draw_text_with_outline

def draw_menu(self, painter, logical_width):
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
            box_x = center_x - (text_w / 2) - 30
        elif align == "left":
            draw_x = center_x + x_offset
            box_x = draw_x - 30
        elif align == "right":
            draw_x = center_x + x_offset
            box_x = draw_x - text_w - 30
        
        box_w = text_w + 60
        box_h = fm.height() + 16
        
        box_y = y - fm.ascent() - 6 - (fm.descent() // 2)

        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(box_x), int(box_y), int(box_w), int(box_h), 8, 8)

        draw_text_with_outline(painter, text, self.font_normal, MENU_TEXT, MENU_OUTLINE, draw_x, y, align)
        
        if align == "center":
            self.menu_click_zones.append((center_x - 400, box_y, center_x + 400, box_y + box_h, action_idx))
        else:
            self.menu_click_zones.append((box_x, box_y, box_x + box_w, box_y + box_h, action_idx))

    def draw_setting_item(name, is_on, y, is_selected, action_idx):
        fm = QFontMetrics(self.font_normal)
        
        box_w = 800 
        box_x = center_x - (box_w / 2)
        box_h = fm.height() + 16
        box_y = y - fm.ascent() - 6 - (fm.descent() // 2)

        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(HIGHLIGHT_COLOR)
            painter.drawRoundedRect(int(box_x), int(box_y), int(box_w), int(box_h), 8, 8)

        draw_text_with_outline(painter, name, self.font_normal, MENU_TEXT, MENU_OUTLINE, box_x + 40, y, "left")
        
        val_text = "ON" if is_on else "OFF"
        val_color = COLOR_P if is_on else COLOR_B_EMG
        draw_text_with_outline(painter, val_text, self.font_normal, val_color, COLOR_WHITE, box_x + box_w - 40, y, "right")
        
        self.menu_click_zones.append((box_x, box_y, box_x + box_w, box_y + box_h, action_idx))

    if self.menu_state == 1:
        title = "=== メニュー ==="
        draw_text_with_outline(painter, title, self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, 200, "center")
        
        items = self.menu_items_on if self.is_scoring_mode else self.menu_items_off
        for i, text in enumerate(items):
            y_pos = 400 + i * 80
            draw_menu_item(text, y_pos, (i == self.menu_cursor), i, "center")
        
        draw_text_with_outline(painter, "↑ ↓ : 選択  |  Enter / Click : 決定・切替", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 870, "center")
        draw_text_with_outline(painter, "Backspace : 戻る  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 930, "center")

    elif self.menu_state == 2:
        draw_text_with_outline(painter, "=== 選択した駅からやり直す ===", self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, 200, "center")
        
        if not self.save_data:
            draw_text_with_outline(painter, "セーブされた駅がありません", self.font_normal, MENU_ERROR, MENU_OUTLINE, center_x, 450, "center")
        else:
            if self.menu_scroll > 0:
                draw_text_with_outline(painter, "▲", self.font_normal, MENU_TEXT, MENU_OUTLINE, center_x, 280, "center")
            
            for i in range(VISIBLE_LIST_COUNT):
                idx = self.menu_scroll + i
                if idx >= len(self.save_data): break
                
                cp = self.save_data[idx]
                y_pos = 350 + i * 80
                time_s = cp['time_ms'] // 1000
                h, m, s = time_s // 3600, (time_s % 3600) // 60, time_s % 60
                time_str = f"{h:02}:{m:02}:{s:02}"
                err = cp['stop_error']
                err_str = f"{abs(err):.2f} m" if abs(err) >= 0.01 else "0.00 m"
                if err < -0.01: err_str = "-" + err_str
                
                row_text = f"{cp.get('station_name', '駅')}  [位置: {err_str}]  スコア: {cp['score']}  時刻: {time_str}"
                draw_menu_item(row_text, y_pos, (idx == self.menu_cursor), idx, "center")
            
            if self.menu_scroll + VISIBLE_LIST_COUNT < len(self.save_data):
                draw_text_with_outline(painter, "▼", self.font_normal, MENU_TEXT, MENU_OUTLINE, center_x, 350 + VISIBLE_LIST_COUNT * 80, "center")

        draw_text_with_outline(painter, "↑ ↓ : 選択  |  Enter / Click : 決定・切替", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 870, "center")
        draw_text_with_outline(painter, "Backspace : 戻る  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 930, "center")

    elif self.menu_state == 3:
        cp = self.save_data[self.target_retry_idx]
        q_text = f"【 {cp.get('station_name', '駅')} 】からやり直しますか？"
        warn_text = "※これ以降のセーブデータは破棄されます"
        draw_text_with_outline(painter, q_text, self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, 350, "center")
        draw_text_with_outline(painter, warn_text, self.font_normal, MENU_ERROR, MENU_OUTLINE, center_x, 450, "center")
        
        y_pos = 600
        for i, text in enumerate(["はい", "いいえ"]):
            row_text = f"  {text}  "
            y_pos_btn = y_pos + i * 80
            draw_menu_item(row_text, y_pos_btn, (i == self.menu_cursor), i, "center")
            
        draw_text_with_outline(painter, "↑ ↓ : 選択  |  Enter / Click : 決定・切替", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 870, "center")
        draw_text_with_outline(painter, "Backspace : 戻る  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 930, "center")

    elif self.menu_state == 4:
        draw_text_with_outline(painter, "=== 環境設定 ===", self.font_big, MENU_TEXT, MENU_OUTLINE, center_x, 200, "center")
        for i in range(7):
            y_pos = 350 + i * 70
            key = self.settings_keys[i]
            name = self.settings_names[i]
            is_on = self.disp_settings[key]
            
            draw_setting_item(name, is_on, y_pos, (i == self.menu_cursor), i)
            
        draw_text_with_outline(painter, "↑ ↓ : 選択  |  Enter / Click : 決定・切替", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 870, "center")
        draw_text_with_outline(painter, "Backspace : 戻る  |  F6 : 閉じる", self.font_normal, COLOR_WHITE, COLOR_OUTLINE_BLACK, center_x, 930, "center")

    painter.restore()