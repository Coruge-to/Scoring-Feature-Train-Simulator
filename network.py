from config import *

def process_udp_data(self):
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
                            brk_eval_list = brk_list[1:] if self.is_single_handle and len(brk_list) > 1 else brk_list
                            # ここはUIフォントメトリクス計算なので維持
                            from PyQt6.QtGui import QFontMetrics
                            fm = QFontMetrics(self.font_ui)
                            self.max_rev_w = max([fm.horizontalAdvance(s) for s in rev_list] + [40])
                            self.max_pow_w = max([fm.horizontalAdvance(s) for s in pow_list] + [40])
                            self.max_brk_w = max([fm.horizontalAdvance(s) for s in brk_eval_list] + [40])
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
                            invalid_count = 0
                            min_valid = 1
                            found_min_valid = False
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
                    elif part.startswith("MAPLIMITS:"):
                        limits_str = part.split(':', 1)[1].replace('∞', '1000').replace('Infinity', '1000')
                        self.bve_map_limits = []
                        if limits_str:
                            for pair in limits_str.split('_'):
                                if '=' in pair:
                                    loc_s, val_s = pair.split('=')
                                    try: self.bve_map_limits.append((float(loc_s), float(val_s)))
                                    except ValueError: pass
                except Exception: continue 
        except Exception: pass