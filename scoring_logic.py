from config import *
from utils import calculate_warning_distance, calculate_apex_speed
from PyQt6.QtNetwork import QHostAddress

def execute_retry(self, index, is_bve_advancing):
    if index < 0 or index >= len(self.save_data): return
    self.save_data = self.save_data[:index + 1]
    cp = self.save_data[-1]
    self.score = cp["score"]
    self.rollback_msg = f">>> {cp.get('station_name', '駅')} へロールバック完了 <<<"
    self.rollback_msg_timer = self.bve_time_ms / 1000.0 + 5.0
    
    self.toggle_menu(is_bve_advancing)
    retry_cmd = f"RETRY:{cp['target_loc']}:{cp['time_ms']}"
    self.udp_socket.writeDatagram(retry_cmd.encode('utf-8'), QHostAddress.SpecialAddress.LocalHost, 54322)

def add_score_popup(self, points, text, color, ptype, category, current_time):
    if not self.is_scoring_mode: return
    self.score += points
    self.popups.append({"text": text, "color": color, "expire_time": current_time + 5.0, "type": ptype, "category": category})

def apply_time_score(self, diff_s, current_time):
    if not self.is_scoring_mode: return
    abs_diff = abs(diff_s)
    if abs_diff <= 9: add = 300
    elif abs_diff <= 19: add = 200
    elif abs_diff <= 29: add = 100
    else: add = 0
    if add > 0:
        add_score_popup(self, add, f"運転時分 +{add}", COLOR_N, "pos", "運転時分", current_time)

def apply_stop_score(self, d_m, current_time):
    if not self.is_scoring_mode: return False
    if self.is_stopped_out_of_range: return False
    if not (-self.bve_margin_f <= d_m <= self.bve_margin_b): return False
    d_m_rounded = round(d_m, 2)
    x_cm = int(abs(d_m_rounded) * 100)
    if x_cm <= 100:
        add = 5 * (100 - x_cm)
        if add > 0:
            add_score_popup(self, add, f"停止位置 +{add}", COLOR_N, "pos", "停止位置", current_time)
        if x_cm < 1: return True 
    return False

def create_save_data(self):
    if not self.is_scoring_mode: return
    if not self.save_data or self.save_data[-1]["target_loc"] != self.bve_next_loc:
        stop_error = self.bve_next_loc - self.bve_location
        self.save_data.append({
            "loc": self.bve_location,
            "time_ms": self.bve_time_ms,
            "score": self.score,
            "target_loc": self.bve_next_loc,
            "station_name": getattr(self, 'bve_current_station_name', '不明な駅'),
            "stop_error": stop_error
        })

def evaluate_arrival(self, current_time):
    is_zero_stop = False
    if not self.is_first_station and self.has_departed and not self.has_scored_stop_this_station:
        if not self.jump_lock:
            is_zero_stop = apply_stop_score(self, self.bve_next_loc - self.bve_location, current_time)
        self.has_scored_stop_this_station = True

    apply_ok = False
    release_ok = False

    if self.bb_is_in_zone and not self.bb_evaluated and not self.jump_lock:
        if not self.bb_is_stable:
            self.bb_is_stable = True
            process_bb_transition(self, self.bb_current_notch)
        self.bb_evaluated = True
        
        actual_margin = self.setting_stop_distance if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        dist_to_stop = self.bve_next_loc - self.bve_location
        
        if abs(dist_to_stop) <= actual_margin:
            if self.bb_state != "FAILED" and not self.is_stopped_out_of_range and self.stop_notch_state != "STRONG":
                if (self.bb_apply_count > 0 or self.bb_release_count > 0):
                    apply_ok = (BASIC_BRAKE_APPLY_LIMIT == 0) or (self.bb_apply_count <= BASIC_BRAKE_APPLY_LIMIT)
                    release_ok = (BASIC_BRAKE_RELEASE_LIMIT == 0) or (self.bb_release_count <= BASIC_BRAKE_RELEASE_LIMIT)

    if is_zero_stop and self.is_scoring_mode:
        add_score_popup(self, 0, "0cm停車成功!!!", COLOR_N, "big", "ボーナス", current_time)
        
    if apply_ok and release_ok and self.is_scoring_mode:
        apply_str = f"{BASIC_BRAKE_APPLY_LIMIT}段制動" if BASIC_BRAKE_APPLY_LIMIT > 0 else "階段制動"
        release_str = f"{BASIC_BRAKE_RELEASE_LIMIT}段緩め" if BASIC_BRAKE_RELEASE_LIMIT > 0 else "階段緩め"
        add_score_popup(self, 0, f"{apply_str}{release_str}成功!!!", COLOR_N, "big", "基本制動", current_time)
        add_score_popup(self, 500, "基本制動 +500", COLOR_N, "pos", "基本制動", current_time)

    if is_zero_stop and self.is_scoring_mode:
        add_score_popup(self, 500, "ボーナス +500", COLOR_N, "pos", "ボーナス", current_time)

    if not self.jump_lock:
        create_save_data(self)

def evaluate_departure(self, current_time):
    if not self.ignore_next_pass_score and not self.jump_lock and not self.is_first_station:
        if self.prev_is_pass == 1 and self.prev_is_timing == 1:
            if not self.has_scored_time_this_station:
                apply_time_score(self, self.prev_diff_s, current_time)
                self.has_scored_time_this_station = True
        elif self.prev_is_pass == 0 and self.prev_doordir == 0 and self.prev_is_timing == 1:
            if not self.has_scored_time_this_station:
                d = self.prev_next_loc - self.bve_location
                if (-self.bve_margin_f <= d <= self.bve_margin_b):
                    apply_time_score(self, self.prev_diff_s, current_time)
                    self.has_scored_time_this_station = True

def process_bb_transition(self, stable_notch):
    if stable_notch != self.bb_prev_stable_notch:
        if self.bve_btype == "Cl":
            if stable_notch >= 2 and self.bb_prev_stable_notch in [0, 1]:
                if self.bb_state == "RELEASING": self.bb_state = "FAILED"
                elif self.bb_state != "FAILED":
                    self.bb_state = "APPLYING"
                    self.bb_apply_count += 1
            elif stable_notch == 0 and self.bb_prev_stable_notch >= 1:
                if self.bb_state != "FAILED":
                    self.bb_state = "RELEASING"
                    self.bb_release_count += 1
        else:
            if stable_notch > self.bb_prev_stable_notch:
                if self.bb_state == "RELEASING": self.bb_state = "FAILED"
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

def update_physics_and_scoring(self, current_time, dt):
    decel_g = -self.bve_calc_g
    self.g_history.append((current_time, decel_g, self.bve_brk_notch, self.bve_brk_max))
    cutoff_time = current_time - 10.0
    self.g_history = [h for h in self.g_history if h[0] > cutoff_time]

    if self.bve_jump_count != self.last_jump_count:
        self.jump_lock = True
        
        is_forward_jump = self.bve_location > (self.prev_frame_loc + 10.0)
        if is_forward_jump: self.ignore_next_pass_score = True
        else: self.ignore_next_pass_score = False
            
        self.blink_active = False
        self.blink_phase = 0.0
        if self.bve_door == 1: self.door_open_loc = self.bve_location
        self.last_jump_count = self.bve_jump_count
        
        self.g_history.clear()
        self.bcp_history.clear()
        self.popups.clear()
        self.ecb_eb_accum_time = 0.0
        self.ecb_eb_cooling_time = 0.0
        self.smee_eb_frozen = False
        self.eb_applied = False
        self.bb_state = "IDLE"
        self.bb_apply_count = 0
        self.bb_release_count = 0
        self.hb_strong_entered = False
        self.has_evaluated_initial_brake = False
        self.idle_entered_while_stopped = False

    in_station_zone = False
    if self.bve_next_loc >= 0:
        actual_margin = self.setting_stop_distance if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        dist_to_stop = self.bve_next_loc - self.bve_location
        if abs(dist_to_stop) <= actual_margin:
            in_station_zone = True

    if self.bve_speed == 0.0:
        if self.is_stopping_zone:
            self.stop_notch_state = get_notch_state(self, self.bve_brk_notch)
            
            recent_g = [h[1] for h in self.g_history if current_time - h[0] <= 0.5]
            if recent_g:
                self.last_stop_g = sum(recent_g) / len(recent_g)
            else:
                self.last_stop_g = decel_g
                
            if self.last_stop_g >= 0.10:
                add_score_popup(self, -200, "停車時衝動 -200", COLOR_B_EMG, "neg", "停車時衝動", current_time)
            elif self.last_stop_g >= 0.06:
                add_score_popup(self, -100, "停車時衝動 -100", COLOR_B_EMG, "neg", "停車時衝動", current_time)
            self.is_stopping_zone = False
            
        curr_n = self.bve_brk_notch
        self.hb_prev_notch = curr_n
        
    elif 0.0 < self.bve_speed <= 1.5:
        self.is_stopping_zone = True
            
    # ★ ここにあった if self.bve_speed > 0.0: を削除し、インデントを左に戻しました！
    is_eb_handle = (self.bve_brk_notch >= self.bve_brk_max or "非常" in self.bve_brk_text or "EB" in self.bve_brk_text.upper())
    physical_eb_tripped = False
    
    if self.bve_btype == "Smee": physical_eb_tripped = (self.bpPressure <= self.bve_bp_initial - 5.0)
    elif self.bve_btype == "Cl": physical_eb_tripped = is_eb_handle
    else:
        if is_eb_handle:
            self.ecb_eb_accum_time += dt
            if self.ecb_eb_accum_time >= ECB_EB_ACCUM_THRESHOLD: self.ecb_eb_accum_time = ECB_EB_ACCUM_THRESHOLD
            self.ecb_eb_cooling_time = 0.0
        else:
            if self.ecb_eb_accum_time > 0.0:
                self.ecb_eb_cooling_time += dt
                if self.ecb_eb_cooling_time >= ECB_EB_COOLING_THRESHOLD:
                    self.ecb_eb_accum_time = 0.0
                    self.ecb_eb_cooling_time = 0.0
            else: self.ecb_eb_cooling_time = 0.0
        physical_eb_tripped = (self.ecb_eb_accum_time >= ECB_EB_ACCUM_THRESHOLD)

    if physical_eb_tripped:
        if self.bb_is_in_zone: self.bb_state = "FAILED"
        if not self.eb_applied:
            if self.bve_speed > 0.0: 
                add_score_popup(self, -500, "非常ブレーキ使用 -500", COLOR_B_EMG, "neg", "非常ブレーキ", current_time)
                
                actual_exempt = getattr(self, 'setting_initial_brake', IGNORE_INITIAL_BRAKE)
                is_initial_exempt = (actual_exempt == "ALL") or (actual_exempt == "STATION" and in_station_zone)
                if not is_initial_exempt and not getattr(self, 'has_evaluated_initial_brake', False):
                    add_score_popup(self, -100, "初動ブレーキ -100", COLOR_B_EMG, "neg", "初動ブレーキ", current_time)
                    self.has_evaluated_initial_brake = True

            self.eb_applied = True
    else: self.eb_applied = False

    if self.bve_btype == "Smee":
        if self.bpPressure < self.bve_bp_initial * 0.9:
            self.smee_eb_frozen = True
            self.bcp_history.clear()
        elif self.smee_eb_frozen:
            self.bcp_history.append((current_time, self.bcPressure))
            HISTORY_SEC, STABLE_SEC = 0.6, 0.5
            self.bcp_history = [h for h in self.bcp_history if current_time - h[0] <= HISTORY_SEC]
            is_stabilized = False
            if len(self.bcp_history) >= 5 and (current_time - self.bcp_history[0][0]) >= STABLE_SEC:
                max_p, min_p = max(h[1] for h in self.bcp_history), min(h[1] for h in self.bcp_history)
                if (max_p - min_p) < 2.0: is_stabilized = True
            curr_state_unfrozen = get_notch_state(self, self.bve_brk_notch)
            if self.bcPressure <= self.eb_freeze_threshold and curr_state_unfrozen == "IDLE":
                self.smee_eb_frozen = False
                if self.bve_speed > 0.0 and not getattr(self, 'idle_entered_while_stopped', False):
                    add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)
            elif is_stabilized:
                self.smee_eb_frozen = False
                if curr_state_unfrozen == "IDLE": 
                    if self.bve_speed > 0.0 and not getattr(self, 'idle_entered_while_stopped', False):
                        add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)
        else: self.bcp_history.clear()

    curr_n = self.bve_brk_notch
    curr_state = get_notch_state(self, curr_n)
    prev_state = get_notch_state(self, self.hb_prev_notch)

    if curr_state == "IDLE":
        if self.bve_speed == 0.0:
            self.idle_entered_while_stopped = True
    else:
        self.idle_entered_while_stopped = False

    if curr_state == "CUSHION":
        if prev_state != "CUSHION":
            self.hb_cushion_entry_time = current_time
            self.hb_cushion_max_g = 0.0
        if decel_g > self.hb_cushion_max_g: self.hb_cushion_max_g = decel_g

    if curr_state == "STRONG":
        self.hb_strong_entered = True 
        if prev_state != "STRONG":
            actual_exempt = getattr(self, 'setting_initial_brake', IGNORE_INITIAL_BRAKE)
            is_initial_exempt = (actual_exempt == "ALL") or (actual_exempt == "STATION" and in_station_zone)
            
            if not is_initial_exempt and self.bve_speed > 0.0:
                if not getattr(self, 'has_evaluated_initial_brake', False):
                    if self.bve_btype == "Cl":
                        if is_eb_handle: add_score_popup(self, -100, "初動ブレーキ -100", COLOR_B_EMG, "neg", "初動ブレーキ", current_time)
                    elif self.bve_btype == "Smee" and self.smee_eb_frozen: pass 
                    else:
                        if prev_state == "CUSHION":
                            stay_time = current_time - self.hb_cushion_entry_time
                            if stay_time < 0.5: add_score_popup(self, -100, "初動ブレーキ -100", COLOR_B_EMG, "neg", "初動ブレーキ", current_time)
                        else: add_score_popup(self, -100, "初動ブレーキ -100", COLOR_B_EMG, "neg", "初動ブレーキ", current_time)
                    
                    self.has_evaluated_initial_brake = True

    if curr_state == "IDLE" and prev_state != "IDLE":
        is_release_exempt = (IGNORE_RELEASE_BRAKE == "ALL") or (IGNORE_RELEASE_BRAKE == "STATION" and in_station_zone)
        if not is_release_exempt and self.bve_speed > 0.0: 
            if not getattr(self, 'idle_entered_while_stopped', False):
                if getattr(self, 'hb_strong_entered', False):
                    if self.bve_btype == "Cl": pass 
                    elif self.bve_btype == "Smee" and self.smee_eb_frozen: pass 
                    else:
                        if prev_state == "CUSHION":
                            stay_time = current_time - self.hb_cushion_entry_time
                            if stay_time < 0.5: add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)
                        else: add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)
        
        self.hb_strong_entered = False
        self.has_evaluated_initial_brake = False

    self.hb_prev_notch = curr_n

    if self.bve_door == 1:
        if self.prev_door == 0:
            self.door_open_loc = self.bve_location
            self.roll_penalized = False
        else:
            if not self.roll_penalized:
                if abs(self.bve_location - self.door_open_loc) >= 0.05: 
                    add_score_popup(self, -500, "転動 -500", COLOR_B_EMG, "neg", "転動", current_time)
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
            process_bb_transition(self, self.bb_current_notch)

    if self.is_speed_penalty:
        if current_time - self.last_penalty_time >= 1.0:
            self.speed_penalty_score += 3
            self.last_penalty_time = current_time

    self.popups = [p for p in self.popups if p["expire_time"] > current_time]

    if self.is_first_udp and self.bve_next_loc != -1.0:
        self.prev_door = self.bve_door
        self.prev_doordir = self.bve_doordir
        self.prev_next_loc = self.bve_next_loc
        if abs(self.bve_next_loc - self.bve_location) > 100.0:
            self.is_first_station = False 
        self.is_first_udp = False
        
    if self.bve_speed >= 1.0 and self.bve_door == 0:
        self.has_departed = True
        self.stop_notch_state = "IDLE"
        if self.jump_lock:
            self.jump_lock = False
        self.is_first_station = False 
        
    current_s = self.bve_time_ms // 1000
    target_s = self.bve_next_time // 1000
    diff_s = target_s - current_s
    is_operational_stop = (self.bve_is_pass == 0 and self.bve_doordir == 0)
    
    if self.prev_next_loc != -1.0 and self.bve_next_loc != self.prev_next_loc:
        is_forward_transition = (self.bve_next_loc > self.prev_next_loc)
        if is_forward_transition:
            evaluate_departure(self, current_time)
            
        self.ignore_next_pass_score = False
        self.is_first_station = False
        self.is_approaching = False
        self.is_stopped_out_of_range = False
        self.has_scored_time_this_station = False
        self.has_scored_stop_this_station = False
        self.bb_evaluated = False
        self.bb_is_in_zone = False
        
    if not self.is_approaching and self.bve_next_loc >= 0:
        actual_margin = self.setting_stop_distance if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        if abs(self.bve_next_loc - self.bve_location) < actual_margin:
            self.is_approaching = True

    if self.is_approaching and self.bve_speed == 0.0 and not self.has_scored_stop_this_station:
        d = self.bve_next_loc - self.bve_location
        if not (-self.bve_margin_f <= d <= self.bve_margin_b):
            self.is_stopped_out_of_range = True 

    if is_operational_stop and self.is_approaching and self.bve_speed == 0.0 and not self.has_scored_stop_this_station:
        if not self.jump_lock and not self.is_first_station:
            evaluate_arrival(self, current_time)
        self.has_scored_stop_this_station = True

    if not is_operational_stop and self.prev_door == 0 and self.bve_door == 1:
        if self.bve_term == 1 and self.bve_is_timing == 1 and not self.has_scored_time_this_station:
            if not self.jump_lock and not self.is_first_station:
                apply_time_score(self, diff_s, current_time)
            self.has_scored_time_this_station = True
            
        evaluate_arrival(self, current_time)
        self.has_scored_stop_this_station = True

    if not is_operational_stop and self.prev_door == 1 and self.bve_door == 0:
        if self.prev_term == 0 and self.prev_is_timing == 1 and not self.has_scored_time_this_station:
            if not self.jump_lock and not self.is_first_station:
                apply_time_score(self, self.prev_diff_s, current_time)
            self.has_scored_time_this_station = True

    self.prev_next_loc = self.bve_next_loc
    self.prev_door = self.bve_door
    self.prev_doordir = self.bve_doordir
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
        
    self.prev_frame_loc = self.bve_location