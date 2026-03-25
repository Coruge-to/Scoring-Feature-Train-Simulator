from config import *
import builtins

def write_debug_log(text):
    try:
        import os
        desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
        with open(os.path.join(desktop, 'debug.log'), 'a', encoding='utf-8') as f:
            f.write(text + '\n')
    except Exception:
        pass

def process_udp_data(self):
    while self.udp_socket.hasPendingDatagrams():
        datagram, host, port = self.udp_socket.readDatagram(self.udp_socket.pendingDatagramSize())
        try:
            text = datagram.decode('utf-8')

            # =========================================================
            # ★ 修正: 小分けにされた STALIST を結合して復元する
            # =========================================================
            if text.startswith("STALIST:"):
                try:
                    parts = text.split(':', 4)
                    if len(parts) >= 5:
                        b_id = parts[1]
                        c_idx = int(parts[2])
                        t_chunks = int(parts[3])
                        sta_data = parts[4]

                        # 新しい送信タイミング(b_id)が来たらバッファをクリア
                        if getattr(self, 'sta_buffer_id', "") != b_id:
                            self.sta_buffer_id = b_id
                            self.sta_buffer = {}

                        parsed_chunk = []
                        if sta_data:
                            for sta_str in sta_data.split(','):
                                sp = sta_str.split('=')
                                if len(sp) >= 3:
                                    s_name = sp[0]
                                    s_timing = sp[1]
                                    s_loc = float(sp[2])
                                    s_rarr = int(sp[3]) if len(sp) >= 4 else -1
                                    s_rdep = int(sp[4]) if len(sp) >= 5 else -1
                                    s_def = int(sp[5]) if len(sp) >= 6 else -1
                                    s_stop = int(sp[6]) if len(sp) >= 7 else 15000
                                    parsed_chunk.append({
                                        "name": s_name, "is_timing": (s_timing == '1'), "location": s_loc,
                                        "raw_arr": s_rarr, "raw_dep": s_rdep, "def_time": s_def, "stop_time": s_stop
                                    })
                        
                        self.sta_buffer[c_idx] = parsed_chunk

                        # すべてのチャンクが揃ったら結合して station_list に登録
                        if len(self.sta_buffer) == t_chunks:
                            new_list = []
                            for i in range(t_chunks):
                                new_list.extend(self.sta_buffer.get(i, []))
                            self.station_list = new_list
                            self.sta_buffer.clear()
                            write_debug_log(f"[STALIST受信完了] 全{len(self.station_list)}駅のデータを取得しました。")
                except Exception as e:
                    write_debug_log(f"STALIST結合エラー: {e}")
                continue

            parts = text.split(',')
            for part in parts:
                try:
                    if part.startswith("SCENARIO_ID:"):
                        new_id = int(part.split(':')[1])
                        if getattr(self, 'current_scenario_id', -1) != new_id:
                            if getattr(self, 'current_scenario_id', -1) != -1:
                                self.is_scoring_mode = False
                                self.score = 0
                                self.save_data.clear()
                                self.popups.clear()
                                self.station_list.clear()
                                self.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}]
                                self.setting_start_idx = 0
                                self.setting_end_idx = -1
                                self.input_buffer = ""
                                if self.menu_state != 0:
                                    self.menu_state = 0 
                                write_debug_log(f"シナリオ変更検知 (ID: {new_id})。スコア等を初期化しました。")
                            
                            self.current_scenario_id = new_id
                            # シナリオが変わったら範囲を-1(未確定)に戻す
                            self.setting_stop_distance = -1

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
                            
                            from PyQt6.QtGui import QFontMetrics
                            fm = QFontMetrics(self.font_ui)
                            
                            from main import KERNING_OFFSETS
                            def get_adjusted_max_w(text_list, apply_offset=False):
                                adjusted_widths = []
                                for s in text_list:
                                    w = fm.horizontalAdvance(s)
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
                        new_tl = max(float(part.split(':')[1]), 20.0)
                        # =========================================================
                        # ★ 修正: 範囲が -1 の場合、即座に 列車長×2 を計算して代入する！
                        # =========================================================
                        if getattr(self, 'bve_train_length', 0) != new_tl or self.setting_stop_distance == -1:
                            self.bve_train_length = new_tl
                            self.setting_stop_distance = int(new_tl) * 2
                        # =========================================================
                        
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
        except Exception: pass