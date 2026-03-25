import time
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath, QPen, QLinearGradient, QFont
from config import *
from utils import draw_text_with_outline, draw_text_with_stroke, get_outline_color

def draw_hud(self, painter, logical_width):
    from main import KERNING_OFFSETS
    
    def get_text_offset(text):
        for suffix, offset in KERNING_OFFSETS.items():
            if text.endswith(suffix):
                return offset
        return 0

    pos_x_left, pos_x_right = MARGIN_LEFT, logical_width - MARGIN_RIGHT
    pos_x_label = pos_x_right - LABEL_WIDTH

    dbg_y = 500
    painter.setFont(QFont("sans-serif", 14, QFont.Weight.Bold))
    
    if self.bb_is_in_zone:
        mech_fail_str = "あり" if self.bb_state == "FAILED" else "なし"
        rule_fail_str = "発生" if (self.is_stopped_out_of_range or self.stop_notch_state == "STRONG") else "なし"
        bb_debug_text = f"[BB] State: {self.bb_state} | App: {self.bb_apply_count} | Rel: {self.bb_release_count} | 込め直し: {mech_fail_str} | 範囲外/強ブレーキ停車: {rule_fail_str}"
    else:
        bb_debug_text = "[BB] Out of Station Zone"

    jump_warn = f" | JumpLock: {'ON' if self.jump_lock else 'OFF'} | IgnorePass: {'ON' if self.ignore_next_pass_score else 'OFF'}"
    save_debug_str = f"[SAVE] Checkpoints: {len(self.save_data)} | Latest: {self.save_data[-1]['station_name']} (Score: {self.save_data[-1]['score']})" if self.save_data else "[SAVE] No checkpoints yet"

    if self.bve_btype == "Cl": cushion_str = f"[BRAKE MODE] 抑速: {'あり' if self.has_holding_brake else 'なし'} | 状態: 自動空気ブレーキ (段位概念なし)"
    else:
        c_min_text = self.all_brk_texts[self.cushion_min] if 0 <= self.cushion_min < len(self.all_brk_texts) else f"B{self.cushion_min}"
        c_max_text = self.all_brk_texts[self.cushion_max] if 0 <= self.cushion_max < len(self.all_brk_texts) else f"B{self.cushion_max}"
        dummy_text = "なし"
        if self.cushion_min > 1: dummy_text = self.all_brk_texts[1] if len(self.all_brk_texts) > 1 else "B1"
        cushion_str = f"[CUSHION] 無効段: {dummy_text} | 有効常用: {self.svc_brk_count}段 | 帯域: {c_min_text}" if c_min_text == c_max_text else f"[CUSHION] 無効段: {dummy_text} | 有効常用: {self.svc_brk_count}段 | 帯域: {c_min_text} - {c_max_text}"

    eb_freeze_status = "ON (Wait Drop/Stable)" if self.smee_eb_frozen else "OFF"
    ecb_debug_str = f" | Ecb_EB: {self.ecb_eb_accum_time:.2f}/{ECB_EB_ACCUM_THRESHOLD}s (Cool: {self.ecb_eb_cooling_time:.2f}/{ECB_EB_COOLING_THRESHOLD}s)" if self.bve_btype == "Ecb" else ""

    dbg_texts = []
    if (self.bve_time_ms / 1000.0) < self.rollback_msg_timer and self.rollback_msg:
        dbg_texts.append(f"★ {self.rollback_msg}")

    mode_str = "ON" if self.is_scoring_mode else "OFF"
    dbg_texts.extend([
        save_debug_str, 
        f"[TIMING] Mode: {mode_str} | Target is_timing: {self.bve_is_timing} | Prev is_timing: {self.prev_is_timing}",
        f"[STATE] 1st_Sta: {self.is_first_station} | Appr: {self.is_approaching} | StopScored: {self.has_scored_stop_this_station} | TimeScored: {self.has_scored_time_this_station}",
        f"[DEBUG X-RAY]{jump_warn}{ecb_debug_str}",
        f"BrakeType: {self.bve_btype} | InitExempt: {IGNORE_INITIAL_BRAKE} | RelExempt: {IGNORE_RELEASE_BRAKE}",
        cushion_str,
        bb_debug_text,
        f"BCP: {self.bcPressure:.1f} kPa | BPP: {self.bpPressure:.1f} / {self.bve_bp_initial * 0.9:.1f} kPa | EB_Freeze: {eb_freeze_status} | Thresh: {self.eb_freeze_threshold:.1f} kPa",
        f"Target_Cap_Val: {round(self.dbg_target_cap, 1)} | ActiveBlue: {round(float(self.dbg_blue), 1) if self.dbg_blue != 'None' else 'None'}  |  ActiveRed: {round(float(self.dbg_red), 1) if self.dbg_red != 'None' else 'None'}",
        f"CalcG: {self.bve_calc_g:.4f} G | MaxG: {self.max_stop_g:.4f} G | LastStop: {self.last_stop_g:.4f} G"
    ])
    
    # ★ X線ゴーグル（超軽量版）
    if self.show_graph:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRect(10, dbg_y - 20, 1100, len(dbg_texts) * 20 + 10)

        painter.setFont(QFont("sans-serif", 14, QFont.Weight.Bold))
        for i, text in enumerate(dbg_texts):
            if text.startswith("★ "):
                painter.setPen(QColor(255, 255, 0)) 
            else:
                painter.setPen(QColor(255, 255, 255)) 
            
            painter.drawText(20, dbg_y, text)
            dbg_y += 20

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

    display_list = []
    for p in self.popups:
        if p["type"] == "pos" or p["type"] == "neg":
            display_list.append(p)
    
    if self.is_speed_penalty and self.is_scoring_mode:
        display_list.append({"text": f"速度制限超過 -{self.speed_penalty_score}", "color": COLOR_B_EMG, "type": "neg", "category": "速度制限超過"})
        
    display_list.sort(key=lambda x: CATEGORY_ORDER.get(x.get("category", ""), 99))

    y_off = 0
    line_h = QFontMetrics(self.font_normal).height() + 10
    for p in display_list:
        draw_text_with_stroke(painter, p["text"], self.font_normal, p["color"], get_outline_color(p["color"]), pos_x_left, MARGIN_TOP_NORMAL + y_off)
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
        draw_text_with_stroke(painter, p["text"], self.font_big, p["color"], get_outline_color(p["color"]), pos_x_left, MARGIN_TOP_BIG + (i * line_h_big))

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
        if label_text and show_label: draw_text_with_stroke(painter, label_text, self.font_ui, label_color, get_outline_color(label_color), pos_x_label, y, "left")
        if value_text and show_value: draw_text_with_stroke(painter, value_text, self.font_ui, value_color, get_outline_color(value_color), pos_x_right, y, "right")

    if self.disp_settings["time"]:
        s = self.bve_time_ms // 1000
        h, m, sec = s // 3600, (s % 3600) // 60, s % 60
        draw_row_local("", COLOR_WHITE, f"{h:02}:{m:02}:{sec:02}", COLOR_WHITE, ui_y)
    ui_y += ui_step
    
    if self.disp_settings["time_left"]:
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
    
    if self.disp_settings["speed"]:
        draw_row_local("", COLOR_WHITE, f"{self.bve_speed:.1f} km/h", COLOR_WHITE, ui_y)
    ui_y += ui_step

    if self.disp_settings["limit"]:
        show_l, show_v = True, True
        if self.blink_active:
            is_type_changed = (self.target_type != self.base_limit_type)
            is_capped_blue = (self.limit_color == COLOR_P and self.disp_limit < self.effective_limit)
            if self.blink_phase < 0.5:
                l_text = "制限" if self.target_type == "map" else "信号"
                l_color = self.limit_color if (is_type_changed and not is_capped_blue) else COLOR_WHITE
                # ★ 浮動小数点バグ修正
                v_text = f"{int(round(self.disp_limit))} km/h" if self.disp_limit < 999.0 else "--- km/h"
                v_color = self.limit_color
            else:
                l_text = "制限" if self.base_limit_type == "map" else "信号"
                l_color = COLOR_WHITE
                v_text = f"{int(round(self.effective_limit))} km/h" if self.effective_limit < 999.0 else "--- km/h"
                v_color = COLOR_WHITE
        else:
            l_text = "制限" if self.base_limit_type == "map" else "信号"
            l_color = COLOR_WHITE
            v_text = f"{int(round(self.effective_limit))} km/h" if self.effective_limit < 999.0 else "--- km/h"
            v_color = COLOR_WHITE
        draw_row_local(l_text, l_color, v_text, v_color, ui_y, show_label=show_l, show_value=show_v)
    ui_y += ui_step

    if self.disp_settings["dist"]:
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
                # ★ 点滅を 5.0 秒間隔に修正
                show_timing = int(time.time() / 5.0) % 2 == 0
                label_text = "採時" if show_timing else ("通過" if is_p else "停車")
                label_col = COLOR_P if is_p else COLOR_B_EMG
            else:
                label_text = "通過" if is_p else "停車"
                label_col = COLOR_P if is_p else COLOR_B_EMG
                
            draw_row_local(label_text, label_col, d_str, d_color, ui_y)
        else:
            draw_row_local("停車", COLOR_B_EMG, "--- m", COLOR_WHITE, ui_y)
    ui_y += ui_step

    if self.is_scoring_mode:
        draw_row_local("得点", COLOR_WHITE, str(self.score), COLOR_B_EMG if self.score < 0 else COLOR_WHITE, ui_y)
    # ★ 採点モードOFF時に上に詰まるバグ修正 (if文の外に出す)
    ui_y += ui_step

    if self.disp_settings["handle"]:
        rev_color = COLOR_P if self.bve_rev_pos == 1 else (COLOR_B_EMG if self.bve_rev_pos == -1 else COLOR_N)
        if "抜取" in self.bve_rev_text: rev_color = COLOR_B_EMG
        pow_color = COLOR_P if self.bve_pow_notch > 0 else (COLOR_B_SVC if self.bve_pow_notch < 0 else COLOR_N)
        brk_color = COLOR_N
        if self.bve_brk_notch > 0: brk_color = COLOR_B_EMG if (self.bve_brk_notch >= self.bve_brk_max or "非常" in self.bve_brk_text or "EB" in self.bve_brk_text.upper()) else COLOR_B_SVC
        if "抜取" in self.bve_brk_text: brk_color = COLOR_B_EMG

        fm = QFontMetrics(self.font_ui)
        gap = 30       
        padding_x = 15 

        total_text_w = self.max_rev_w + gap + max(self.max_pow_w, self.max_brk_w) if self.is_single_handle else self.max_rev_w + gap + self.max_pow_w + gap + self.max_brk_w
        scale_ratio = min(1.0, LABEL_WIDTH / total_text_w) if total_text_w > 0 else 1.0

        bg_h_local, bg_y_offset = ui_step - 2, 5
        offset_to_top = fm.ascent() + (bg_h_local - fm.height()) / 2.0 + bg_y_offset
        base_bg_top_y = ui_y - offset_to_top
        scaled_bg_h = bg_h_local * scale_ratio
        bg_w_global = total_text_w * scale_ratio + padding_x * 2
        bg_x_global = pos_x_right - total_text_w * scale_ratio - padding_x

        gradient = QLinearGradient(bg_x_global, 0, bg_x_global + bg_w_global, 0)
        gradient.setColorAt(0.0, QColor(40, 40, 40, 0))
        gradient.setColorAt(0.15, QColor(*COLOR_BG))
        gradient.setColorAt(1.0, QColor(*COLOR_BG))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(int(bg_x_global), int(base_bg_top_y), int(bg_w_global), int(scaled_bg_h))

        painter.save()
        painter.translate(pos_x_right, base_bg_top_y)
        painter.scale(scale_ratio, scale_ratio)

        if self.is_single_handle:
            draw_text_with_stroke(painter, self.bve_rev_text, self.font_ui, rev_color, get_outline_color(rev_color), -max(self.max_pow_w, self.max_brk_w) - gap, offset_to_top, "right")
            
            handle_text = self.bve_pow_text if self.bve_pow_notch != 0 else (self.bve_brk_text if self.bve_brk_notch > 0 else self.bve_pow_text)
            handle_color = pow_color if self.bve_pow_notch != 0 else (brk_color if self.bve_brk_notch > 0 else COLOR_N)
            
            me_offset = get_text_offset(handle_text) if self.bve_brk_notch > 0 else 0
            draw_text_with_stroke(painter, handle_text, self.font_ui, handle_color, get_outline_color(handle_color), 0 + me_offset, offset_to_top, "right")
        else:
            draw_text_with_stroke(painter, self.bve_rev_text, self.font_ui, rev_color, get_outline_color(rev_color), -self.max_brk_w - gap - self.max_pow_w - gap, offset_to_top, "right")
            draw_text_with_stroke(painter, self.bve_pow_text, self.font_ui, pow_color, get_outline_color(pow_color), -self.max_brk_w - gap, offset_to_top, "right")
            
            brk_offset = get_text_offset(self.bve_brk_text)
            draw_text_with_stroke(painter, self.bve_brk_text, self.font_ui, brk_color, get_outline_color(brk_color), 0 + brk_offset, offset_to_top, "right")
        
        painter.restore()
        ui_y += scaled_bg_h + (ui_step - bg_h_local)
    else:
        ui_y += ui_step 

    if self.disp_settings["grad"]:
        grad_str = f"+{self.bve_gradient:.1f} ‰" if self.bve_gradient > 0 else (f"{self.bve_gradient:.1f} ‰" if self.bve_gradient < 0 else "0.0 ‰")
        draw_row_local("", COLOR_WHITE, grad_str, COLOR_WHITE, ui_y)