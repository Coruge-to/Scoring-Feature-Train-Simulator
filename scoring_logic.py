from config import *
from utils import calculate_warning_distance, calculate_apex_speed
from PyQt6.QtNetwork import QHostAddress
from utils import calculate_warning_distance, calculate_apex_speed, write_desktop_log
import os
from datetime import datetime
import time

def execute_retry(self, index, is_bve_advancing):
    if index < 0 or index >= len(self.save_data): return
        
    self.is_official_retry = (index > 0)
    self.is_first_station = (index == 0)
    if index == 0:
        self.total_retry_count = 0
    self.is_scoring_finished = False  
    self.has_departed = False
    self.is_approaching = False
    self.is_stopped_out_of_range = False
    self.has_scored_time_this_station = False
    self.has_scored_stop_this_station = False
    self.end_message_time = 0.0
    self.is_first_udp = True
    
    self.save_data = self.save_data[:index + 1]
    cp = self.save_data[-1]
    self.score = cp["score"]

    if "score_details" in cp:
        self.score_details = cp["score_details"].copy()
    else:
        # 万が一古いセーブデータだった場合の保険
        for k in self.score_details: self.score_details[k] = 0

    #?self.bve_door = 0
    #?self.prev_door = 0

    self.rollback_msg = f">>> {cp.get('station_name', '駅')} へロールバック完了 <<<"
    self.rollback_msg_timer = self.bve_time_ms / 1000.0 + 5.0
    
    self.toggle_menu(is_bve_advancing)
    
    self.is_official_jumping = True
    self.jump_start_real_time = time.time()

    target_bve_sta_idx = 0
    ideal_loc = cp['loc']
    def_t = -1
    calc_t = -1  # ★ 追加
    
    if getattr(self, 'station_list', []):
        for i, st in enumerate(self.station_list):
            if abs(st["location"] - cp['loc']) < 100.0:
                target_bve_sta_idx = i
                ideal_loc = st["location"]
                def_t = st.get("def_time", -1)
                
                # ★ 追加：calc_t を計算して理不尽判定の材料にする
                raw_dep = st.get("raw_dep", -1)
                stop_t = st.get("stop_time", 15000)
                calc_t = (raw_dep - stop_t) if raw_dep >= 0 else -1
                break
    
    # =================================================================
    # ★ 修正：旧方式(LOC)に逃げる「完全な悪条件」の厳密化
    # 1. 途中駅である
    # 2. 作者が意図的に遅延設定(def_t > calc_t)にしている
    # 3. かつ、自分のセーブ時刻がその def_t より早い
    # =================================================================
    use_legacy = (target_bve_sta_idx > 0 and def_t >= 0 and calc_t >= 0 and def_t > calc_t and cp['time_ms'] < def_t)
    
    if use_legacy:
        cmd = f"JUMP_LOC_TIME:{ideal_loc}:{cp['time_ms']}"
    else:
        cmd = f"JUMP_STA_TIME:{target_bve_sta_idx}:{cp['time_ms']}"
        
    self.expected_target_loc = ideal_loc
    self.expected_target_time = cp['time_ms']
    self.udp_socket.writeDatagram(cmd.encode('utf-8'), QHostAddress.SpecialAddress.LocalHost, 54322)

def add_score_popup(self, points, text, color, ptype, category, current_time, force=False):
    if not getattr(self, 'is_scoring_mode', False) and not force: return
    # =================================================================
    # ★ 追加：採点終了後は、強制表示（終了メッセージ）以外の加点・減点をすべて弾く！
    # =================================================================
    if getattr(self, 'is_scoring_finished', False) and not force: return
    self.score += points
    # =================================================================
    # ★ 新規追加：カテゴリに応じた内訳貯金箱への自動振り分け
    # =================================================================
    cat_map = {
        "運転時分": "time", "停止位置": "stop", "基本制動": "base_brake",
        "ボーナス": "bonus", "転動": "roll", "停車時衝動": "jerk",
        "初動ブレーキ": "init_brake", "緩和ブレーキ": "rel_brake",
        "非常ブレーキ": "eb", "速度制限超過": "limit", "ATS信号無視": "ats"
    }
    if category in cat_map:
        key = cat_map[category]
        self.score_details[key] += points
    # =================================================================
    self.popups.append({"text": text, "color": color, "expire_time": current_time + 5.0, "type": ptype, "category": category})

def apply_time_score(self, diff_s, current_time):
    if not getattr(self, 'is_scoring_mode', False) or getattr(self, 'is_scoring_finished', False): return
    abs_diff = abs(diff_s)
    if abs_diff <= 9: add = 300
    elif abs_diff <= 19: add = 200
    elif abs_diff <= 29: add = 100
    else: add = 0
    if add > 0:
        # ★ 変更: force=True を削除！（通常のスコアとして扱う）
        add_score_popup(self, add, f"運転時分 +{add}", COLOR_N, "pos", "運転時分", current_time)

def apply_stop_score(self, d_m, current_time):
    if not getattr(self, 'is_scoring_mode', False): return False
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
    if not getattr(self, 'is_scoring_mode', False) or getattr(self, 'is_scoring_finished', False): return
    if not getattr(self, 'save_data', []) or self.save_data[-1]["target_loc"] != self.bve_next_loc:
        stop_error = self.bve_next_loc - self.bve_location
        
        # 基本は現在の時刻をそのまま保存する
        save_time_ms = self.bve_time_ms
        
        # =================================================================
        # ★ 追加：ドア開時間の加算（ズル防止ペナルティ）
        # =================================================================
        # 条件1: 始発駅（最初のセーブデータ）ではないこと
        if len(getattr(self, 'save_data', [])) > 0:
            # 条件2: 扉が開く駅であること（通過駅や運転停車は除外）
            if getattr(self, 'bve_is_pass', 0) == 0 and getattr(self, 'bve_doordir', 1) != 0:
                
                # 現在の駅のダイヤ情報を取得する
                curr_sta_idx = -1
                p_loc = getattr(self, 'prev_next_loc', getattr(self, 'bve_next_loc', -1.0))
                for i, st in enumerate(getattr(self, 'station_list', [])):
                    if abs(st["location"] - p_loc) < 1.0:
                        curr_sta_idx = i
                        break
                
                if curr_sta_idx >= 0:
                    st = getattr(self, 'station_list', [])[curr_sta_idx]
                    raw_dep = st.get("raw_dep", -1)
                    def_t = st.get("def_time", -1)
                    stop_t = st.get("stop_time", 15000)
                    
                    calc_t = (raw_dep - stop_t) if raw_dep >= 0 else -1
                    
                    # 条件3: 到着時間が「定刻(calc_t)」より遅れているか？（遅延時のみ加算）
                    is_delayed = (calc_t < 0) or (self.bve_time_ms > calc_t)
                    
                    # 条件4: ロールバック時に「新方式(STA)」が使われるか？
                    # (旧方式(LOC)の場合は目の前で扉が開くため加算不要)
                    will_use_sta = (def_t < 0) or (self.bve_time_ms >= def_t)
                    
                    # すべての悪条件（ズルできる条件）が揃った時のみ、ドア時間を加算して未来へ進める！
                    if is_delayed and will_use_sta:
                        door_time = getattr(self, 'bve_door_close_time_ms', 0)
                        save_time_ms += door_time
                        
                        # （確認用：後で消してもOKです）
                        write_desktop_log(f"[SAVE] ズル防止発動: {st.get('name', '駅')}にて {door_time}ms をセーブデータ時刻に加算")

        # =================================================================
        
        self.save_data.append({
            "loc": self.bve_location,
            "time_ms": save_time_ms,  # ズル防止計算済みの時間を保存する！
            "score": self.score,
            # ★ 追加：現在の内訳貯金箱の状態をコピーして保存（未来で加算されても影響を受けないように .copy() する）
            "score_details": self.score_details.copy(),
            "target_loc": self.bve_next_loc,
            "station_name": getattr(self, 'bve_current_station_name', '不明な駅'),
            "stop_error": stop_error
        })

def evaluate_arrival(self, current_time):
    if getattr(self, 'is_scoring_finished', False): return
    curr_sta_idx = -1
    # ★ 謎2解決：bve_next_loc がすでに更新されてしまっていることを防ぐため、prev_next_loc を使う
    p_loc = getattr(self, 'prev_next_loc', getattr(self, 'bve_next_loc', -1.0))
    for i, st in enumerate(getattr(self, 'station_list', [])):
        if abs(st["location"] - p_loc) < 1.0:
            curr_sta_idx = i
            break
            
    is_end_sta_match = (curr_sta_idx != -1 and curr_sta_idx == getattr(self, 'setting_end_idx', -1)) or (getattr(self, 'prev_term', 0) == 1)
    is_scoring_end_station = is_end_sta_match and not getattr(self, 'jump_lock', False) and getattr(self, 'is_scoring_mode', False)

    is_zero_stop = False
    if not getattr(self, 'is_first_station', False) and getattr(self, 'has_departed', False) and not getattr(self, 'has_scored_stop_this_station', False):
        if not getattr(self, 'jump_lock', False):
            is_zero_stop = apply_stop_score(self, p_loc - self.bve_location, current_time)
        self.has_scored_stop_this_station = True

    apply_ok = False
    release_ok = False
    is_rescue = False # ★ 追加: 救済フラグ

    # =================================================================
    # ★ 追加：現在の基本制動ルールを取得し、"OFF"なら判定自体をスキップ
    # =================================================================
    b_rule_app = getattr(self, 'active_rule_basic_apply', '階段')
    b_rule_rel = getattr(self, 'active_rule_basic_release', '階段')

    if b_rule_app != "OFF" and getattr(self, 'bb_is_in_zone', False) and not getattr(self, 'bb_evaluated', False) and not getattr(self, 'jump_lock', False):
        if not getattr(self, 'bb_is_stable', False):
            self.bb_is_stable = True
            process_bb_transition(self, self.bb_current_notch)
        self.bb_evaluated = True
        
        # 文字列を回数(数値)に変換する関数（回数計算用）
        def get_limit_val(s):
            if s == "1段": return 1
            if s == "2段": return 2
            if s == "3段": return 3
            return 0 # "階段"

        app_limit = get_limit_val(b_rule_app)
        rel_limit = get_limit_val(b_rule_rel)
        
        actual_margin = getattr(self, 'setting_stop_distance', -1) if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        dist_to_stop = p_loc - self.bve_location
        
        if abs(dist_to_stop) <= actual_margin:
            if getattr(self, 'bb_state', "IDLE") != "FAILED" and not getattr(self, 'is_stopped_out_of_range', False) and getattr(self, 'stop_notch_state', "IDLE") != "STRONG":
                if (getattr(self, 'bb_apply_count', 0) > 0 or getattr(self, 'bb_release_count', 0) > 0):
                    # ★ 変更：固定値ではなく、ルール上限値(app_limit)と比較
                    apply_ok = (app_limit == 0) or (getattr(self, 'bb_apply_count', 0) <= app_limit)
                    release_ok = (rel_limit == 0) or (getattr(self, 'bb_release_count', 0) <= rel_limit)
                    # =============================================================
                    # ★ 追加：1段制動設定時の救済措置（2段まで許容）
                    # =============================================================
                    if not apply_ok and b_rule_app == "1段" and getattr(self, 'bb_apply_count', 0) == 2 and release_ok:
                        is_rescue = True
                        apply_ok = True # 表示ブロックへ進めるために合格扱いにする
                    # =============================================================
                    

    if is_zero_stop and getattr(self, 'is_scoring_mode', False):
        add_score_popup(self, 0, "0cm停車成功!!!", COLOR_N, "big", "ボーナス", current_time)
        
    if apply_ok and release_ok and getattr(self, 'is_scoring_mode', False):
        # =============================================================
        # ★ 修正：救済フラグの有無で表示メッセージと点数を分岐
        if is_rescue:
            # 救済：メッセージを「2段制動〜」に変更し、点数を +300 にする
            add_score_popup(self, 0, f"2段制動{b_rule_rel}緩め成功!!!", COLOR_N, "big", "基本制動", current_time)
            add_score_popup(self, 300, "基本制動 +300", COLOR_N, "pos", "基本制動", current_time)
        else:
            # 通常成功：設定通りのルール名を表示し、点数を +500 にする
            add_score_popup(self, 0, f"{b_rule_app}制動{b_rule_rel}緩め成功!!!", COLOR_N, "big", "基本制動", current_time)
            add_score_popup(self, 500, "基本制動 +500", COLOR_N, "pos", "基本制動", current_time)
        # =============================================================

    if is_zero_stop and apply_ok and release_ok and getattr(self, 'is_scoring_mode', False):
        add_score_popup(self, 500, "ボーナス +500", COLOR_N, "pos", "ボーナス", current_time)

    if is_scoring_end_station:
        self.is_scoring_finished = True
        # ★ 謎4解決：5秒後にメッセージを出すためのタイマーをセット
        self.end_message_time = current_time + 5.0
        self.result_screen_time = current_time + 10.0

        try:
            total_details = sum(self.score_details.values())
            write_desktop_log("\n====== 採点終了！ スコア内訳の答え合わせ ======")
            write_desktop_log(f"  運転時分: {self.score_details.get('time', 0)}")
            write_desktop_log(f"  停止位置: {self.score_details.get('stop', 0)}")
            write_desktop_log(f"  基本制動: {self.score_details.get('base_brake', 0)}")
            write_desktop_log(f"  ボーナス: {self.score_details.get('bonus', 0)}")
            write_desktop_log(f"  転動: {self.score_details.get('roll', 0)}")
            write_desktop_log(f"  停車時衝動: {self.score_details.get('jerk', 0)}")
            write_desktop_log(f"  初動ブレーキ: {self.score_details.get('init_brake', 0)}")
            write_desktop_log(f"  緩和ブレーキ: {self.score_details.get('rel_brake', 0)}")
            write_desktop_log(f"  非常ブレーキ: {self.score_details.get('eb', 0)}")
            write_desktop_log(f"  速度制限超過: {self.score_details.get('limit', 0)}")
            write_desktop_log(f"  ATS信号無視: {self.score_details.get('ats', 0)}")
            write_desktop_log("----------------------------------------------")
            write_desktop_log(f"  内訳の合計: {total_details} 点")
            write_desktop_log(f"  実際の総合得点(self.score): {self.score} 点")
            if total_details == self.score:
                write_desktop_log("  => 判定: 【完全一致！！完璧です！】")
            else:
                write_desktop_log("  => 判定: 【不一致... どこかで加算漏れがあります】")
            write_desktop_log("==============================================\n")
        except Exception as e:
            write_desktop_log(f"[エラー] 答え合わせ出力失敗: {e}")
        # =================================================================

    else:
        if not getattr(self, 'jump_lock', False):
            create_save_data(self)

def evaluate_departure(self, current_time):
    if getattr(self, 'is_scoring_finished', False): return
    allow_score = not getattr(self, 'jump_lock', False) or getattr(self, 'is_official_retry', False)
    
    p_loc = getattr(self, 'prev_next_loc', -1.0)
    p_idx = -1
    if p_loc >= 0:
        for i, st in enumerate(getattr(self, 'station_list', [])):
            if abs(st["location"] - p_loc) < 1.0:
                p_idx = i
                break
    
    # ★ 厳密化：駅が特定できない、もしくはユーザー設定で非採時なら False
    is_timing_active = False
    if p_idx >= 0:
        # F6メニューの設定(override)も含めて判定する関数を呼ぶ
        is_timing_active = self.is_station_timing(p_idx)
    
    # =================================================================
    # ★ デバッグ用トラップ：出発判定が呼ばれた瞬間の全フラグを出力！
    debug_msg = f"[DEPARTURE ENTRY] p_loc={p_loc:.1f}, p_idx={p_idx}\n"
    debug_msg += f"  - allow_score: {allow_score} (jump_lock: {getattr(self, 'jump_lock', False)})\n"
    debug_msg += f"  - ignore_next: {getattr(self, 'ignore_next_pass_score', False)}\n"
    debug_msg += f"  - is_first_station: {getattr(self, 'is_first_station', False)}\n"
    debug_msg += f"  - is_timing_active: {is_timing_active}\n"
    debug_msg += f"  - prev_is_pass: {getattr(self, 'prev_is_pass', 0)}, prev_doordir: {getattr(self, 'prev_doordir', 1)}\n"
    debug_msg += f"  - has_scored_time: {getattr(self, 'has_scored_time_this_station', False)}\n"
    
    write_desktop_log(debug_msg)
    # =================================================================

    if not getattr(self, 'ignore_next_pass_score', False) and allow_score and not getattr(self, 'is_first_station', False):
        if getattr(self, 'prev_is_pass', 0) == 1 and is_timing_active:
            if not getattr(self, 'has_scored_time_this_station', False):
                apply_time_score(self, getattr(self, 'prev_diff_s', 0), current_time)
                self.has_scored_time_this_station = True
                self.is_official_retry = False 
        elif getattr(self, 'prev_is_pass', 0) == 0 and is_timing_active:
            if not getattr(self, 'has_scored_time_this_station', False):
                d = p_loc - self.bve_location
                
                # 過去にちゃんと許容範囲で止まっており、かつ、出発時刻の今この瞬間も許容範囲内にいること
                if (getattr(self, 'has_scored_stop_this_station', False) or getattr(self, 'is_official_retry', False)) and (-self.bve_margin_f <= d <= self.bve_margin_b):
                    # 発車時刻(raw_dep)を自力で引っ張り出して計算
                    dep_target_s = -1
                    if p_idx >= 0:
                        dep_target_s = getattr(self, 'station_list', [])[p_idx].get("raw_dep", -1) // 1000
                    if dep_target_s < 0:
                        dep_target_s = getattr(self, 'prev_next_time', self.bve_time_ms) // 1000
                    
                    dep_diff_s = dep_target_s - (self.bve_time_ms // 1000)
                    
                    apply_time_score(self, dep_diff_s, current_time)
                    self.has_scored_time_this_station = True
                    self.is_official_retry = False
                # =================================================================

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
    # =================================================================
    # ★ 新設：現在の座標から「今適用されるルール」をリアルタイム抽出！
    # =================================================================
    if getattr(self, 'is_scoring_mode', False) and getattr(self, 'station_list', []):
        
        # 1. 先に「次駅ターゲット」を特定する（ドアが閉まると切り替わる）
        next_idx = -1
        if self.bve_next_loc >= 0:
            for i, st in enumerate(self.station_list):
                if abs(st["location"] - self.bve_next_loc) < 1.0:
                    next_idx = i
                    break
        
        if next_idx >= 0:
            self.active_next_sta_name = self.station_list[next_idx].get("name", "不明な駅")
            self.active_next_sta_timing = self.is_station_timing(next_idx) if hasattr(self, 'is_station_timing') else False
        else:
            self.active_next_sta_name = "---"
            self.active_next_sta_timing = False
            
        # 2. 区間ルールの抽出（物理座標ではなく、次駅ターゲットを基準にする！）
        b_rules = getattr(self, 'brake_rules', [{"end_idx": -1, "apply": "階段", "release": "階段"}])
        p_rules = getattr(self, 'penalty_init_rules', [{"apply": "ON①", "release": "ON①"}])
        
        active_b_rule = b_rules[-1]
        active_p_rule = p_rules[-1] if len(p_rules) == len(b_rules) else {"apply": "ON①", "release": "ON①"}
        
        # 比較用インデックス（次駅が未定なら0とする）
        compare_idx = next_idx if next_idx >= 0 else 0
        
        for i, r in enumerate(b_rules):
            e_idx = r.get("end_idx", -1)
            if e_idx == -1 or e_idx >= len(self.station_list):
                active_b_rule = r
                active_p_rule = p_rules[i] if i < len(p_rules) else p_rules[-1]
                break
            
            # ★ 変更：列車の現在地ではなく、「次に向かっている駅」が区間内かで判定
            if compare_idx <= e_idx:
                active_b_rule = r
                active_p_rule = p_rules[i] if i < len(p_rules) else p_rules[-1]
                break
                
        self.active_rule_basic_apply = active_b_rule.get("apply", "階段")
        self.active_rule_basic_release = active_b_rule.get("release", "階段")
        self.active_rule_init_apply = active_p_rule.get("apply", "ON①")
        self.active_rule_init_release = active_p_rule.get("release", "ON①")
        
        # 3. 機能ON/OFFの文字列化（HUD表示用）
        f_list = []
        if getattr(self, 'pen_limit', True): f_list.append("[制限超]")
        if getattr(self, 'pen_jerk', True): f_list.append("[衝動]")
        if getattr(self, 'pen_eb', True): f_list.append("[EB]")
        if getattr(self, 'pen_ats', True): f_list.append("[ATS]")
        self.active_features_str = " ".join(f_list) if f_list else "すべてOFF"

    # =================================================================
    # ★ 謎4解決：お掃除係を最上部へ配置し、永遠に残るバグを消滅
    # =================================================================
    self.popups = [p for p in getattr(self, 'popups', []) if p["expire_time"] > current_time]
    
    # ★ 謎4解決：5秒遅延させた「お疲れ様」メッセージの発火
    # ★ 謎4解決：5秒遅延させた「お疲れ様」メッセージの発火
    if getattr(self, 'end_message_time', 0.0) > 0 and current_time >= self.end_message_time:
        # ★ 修正: 採点が正しく終了(is_scoring_finished)している場合のみ表示。中断されていたら弾く！
        if getattr(self, 'is_scoring_finished', False):
            add_score_popup(self, 0, "運転お疲れ様でした。", COLOR_WHITE, "big", "終了", current_time, force=True)
        self.end_message_time = 0.0
    
    # ★ 新規追加: 10秒経過で自動的にリザルト画面(11)を開く
    if getattr(self, 'result_screen_time', 0.0) > 0 and current_time >= self.result_screen_time:
        # ★ 修正: 採点が正しく終了している場合のみリザルト画面を開く！
        if getattr(self, 'is_scoring_finished', False):
            # ★ 修正: 直接 True を渡して確実に一時停止(Pキー送信)させる！
            self.toggle_menu(True) 
            self.menu_state = 11       
            self.menu_cursor = 0
            getattr(self, 'popups', []).clear()
        self.result_screen_time = 0.0

    decel_g = -self.bve_calc_g
    self.g_history.append((current_time, decel_g, self.bve_brk_notch, self.bve_brk_max))
    cutoff_time = current_time - 10.0
    self.g_history = [h for h in self.g_history if h[0] > cutoff_time]

    if self.bve_jump_count != getattr(self, 'last_jump_count', 0):
        write_desktop_log(f"[JUMP DETECT] BVEジャンプ検知！ カウント: {getattr(self, 'last_jump_count', 0)} -> {self.bve_jump_count}")
        real_now = time.time()
        is_valid_jump = False
        
        # =================================================================
        # ★ 謎1解決：鶴さん考案「座標・時間の一致判定」による絶対的ガード（完全復元版）
        # 2段ジャンプを考慮し、位置か時間の「どちらか」が目標値と一致すれば許容する
        # =================================================================
        if getattr(self, 'is_official_jumping', False):
            is_valid_jump = True
            
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
        
        # =================================================================
        # ★ 解除フェーズ：データが追いついたか確認し、シールドを破棄する
        # =================================================================
        if getattr(self, 'is_official_jumping', False):
            exp_loc = getattr(self, 'expected_target_loc', -1.0)
            exp_time = getattr(self, 'expected_target_time', -1)
            
            loc_match = abs(self.bve_location - exp_loc) < 0.01
            time_match = abs(self.bve_time_ms - exp_time) < 100
            
            # データが追いついて一致したら、0.5秒待たずに「即座に」シールド解除！
            if loc_match and time_match:
                self.is_official_jumping = False
            # 一致していなくても、0.5秒経ったら強制解除！（永久無敵になるのを防ぐ保険）
            elif real_now - getattr(self, 'jump_start_real_time', 0.0) >= 0.5:
                self.is_official_jumping = False

            #???
            if not self.is_official_jumping:
                self.prev_door = getattr(self, 'bve_door', 0)
                self.prev_doordir = getattr(self, 'bve_doordir', 1)
                self.prev_next_loc = self.bve_next_loc
                self.prev_is_pass = self.bve_is_pass
                self.prev_is_timing = self.bve_is_timing
                
        if not is_valid_jump and getattr(self, 'is_scoring_mode', False) and not getattr(self, 'is_scoring_finished', False):
            self.is_scoring_mode = False
            add_score_popup(self, 0, "不正なジャンプを検知しました。", COLOR_B_EMG, "big", "警告", current_time, force=True)
            add_score_popup(self, 0, "採点を中断します。", COLOR_B_EMG, "big", "警告", current_time, force=True)
            self.is_official_jumping = False
            
        self.jump_lock = True
        
        is_forward_jump = self.bve_location > (getattr(self, 'prev_frame_loc', 0.0) + 10.0)
        if is_forward_jump: self.ignore_next_pass_score = True
        else: self.ignore_next_pass_score = False
            
        self.blink_active = False
        self.blink_phase = 0.0
        if getattr(self, 'bve_door', 0) == 1: self.door_open_loc = self.bve_location
        self.last_jump_count = self.bve_jump_count

    in_station_zone = False
    if self.bve_next_loc >= 0 and self.bve_is_pass == 0:
        actual_margin = getattr(self, 'setting_stop_distance', -1) if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
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

            # =================================================================
            # ★ 修正：後退からの停車も考慮し、絶対値でGを判定する
            # =================================================================
            abs_stop_g = abs(self.last_stop_g)

            if getattr(self, 'pen_jerk', True):
                if abs_stop_g >= 0.10:
                    add_score_popup(self, -200, "停車時衝動 -200", COLOR_B_EMG, "neg", "停車時衝動", current_time)
                elif abs_stop_g >= 0.065:
                    add_score_popup(self, -100, "停車時衝動 -100", COLOR_B_EMG, "neg", "停車時衝動", current_time)
            self.is_stopping_zone = False
            
        curr_n = self.bve_brk_notch
        self.hb_prev_notch = curr_n
        
    elif 0.0 < abs(self.bve_speed) <= 1.5:
        self.is_stopping_zone = True
            
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
            if abs(self.bve_speed) > 0.0: 
                if getattr(self, 'pen_eb', True):
                    add_score_popup(self, -500, "非常ブレーキ使用 -500", COLOR_B_EMG, "neg", "非常ブレーキ", current_time)
                
                rule = getattr(self, 'active_rule_init_apply', 'ON①')
                is_initial_exempt = (rule == "OFF") or (rule == "ON②" and in_station_zone)

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
            
            # =========================================================
            # ★ 修正: Smee凍結解除時も、現在の緩和ルールの免除(OFF/ON②)をチェックする
            rel_rule = getattr(self, 'active_rule_init_release', 'ON①')
            is_rel_exempt = (rel_rule == "OFF") or (rel_rule == "ON②" and in_station_zone)
            # =========================================================
            
            if self.bcPressure <= self.eb_freeze_threshold and curr_state_unfrozen == "IDLE":
                self.smee_eb_frozen = False
                if abs(self.bve_speed) > 0.0 and not getattr(self, 'idle_entered_while_stopped', False) and not is_rel_exempt:
                    add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)
            elif is_stabilized:
                self.smee_eb_frozen = False
                if curr_state_unfrozen == "IDLE": 
                    if abs(self.bve_speed) > 0.0 and not getattr(self, 'idle_entered_while_stopped', False) and not is_rel_exempt:
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
            rule = getattr(self, 'active_rule_init_apply', 'ON①')
            is_initial_exempt = (rule == "OFF") or (rule == "ON②" and in_station_zone)
            
            if not is_initial_exempt and abs(self.bve_speed) > 0.0:
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
        rule = getattr(self, 'active_rule_init_release', 'ON①')
        is_release_exempt = (rule == "OFF") or (rule == "ON②" and in_station_zone)
        if not is_release_exempt and abs(self.bve_speed) > 0.0: 
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

    if getattr(self, 'bve_door', 0) == 1:
        if getattr(self, 'prev_door', 0) == 0:
            self.door_open_loc = self.bve_location
            self.roll_penalized = False
        else:
            if not getattr(self, 'roll_penalized', False):
                if abs(self.bve_location - getattr(self, 'door_open_loc', self.bve_location)) >= 0.05: 
                    add_score_popup(self, -500, "転動 -500", COLOR_B_EMG, "neg", "転動", current_time)
                    self.roll_penalized = True
    else:
        self.roll_penalized = False

    if getattr(self, 'bb_is_in_zone', False) and self.bve_speed < 0:
        self.bb_state = "FAILED"
    
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

    if getattr(self, 'is_scoring_mode', False) and not getattr(self, 'is_scoring_finished', False) and getattr(self, 'pen_limit', True):
        current_limit = getattr(self, 'effective_limit', 1000.0)
        
        # ★ 修正1：後退時（マイナス）の速度超過も絶対値で検知する
        abs_speed = abs(self.bve_speed)
        
        # 制限速度 + 1.0 km/h 以上で減点開始
        if current_limit < 999.0 and abs_speed >= current_limit + 1.0:
            if not getattr(self, 'is_speed_limit_exceeded', False):
                self.is_speed_limit_exceeded = True
                self.last_speed_limit_penalty_time = current_time - 1.0 # 初回は即座に減点
                
            if current_time - getattr(self, 'last_speed_limit_penalty_time', 0.0) >= 1.0:
                # 小数点以下切り捨ての減点幅（絶対値で計算）
                deduction = int(abs_speed - current_limit)
                if deduction > 0:
                    if not hasattr(self, 'accumulated_speed_penalty'):
                        self.accumulated_speed_penalty = 0
                    self.accumulated_speed_penalty += deduction
                    
                    # 既存のポップアップを探して上書き（居座り）
                    popup_found = False
                    for p in getattr(self, 'popups', []):
                        if p.get("category") == "速度制限超過":
                            p["text"] = f"速度制限超過 -{self.accumulated_speed_penalty}"
                            # ★ 修正2：「勝手に5秒後に消えるルール」の活用
                            # 超過している間は毎秒「寿命を5秒後に延長」し続ける。
                            # 速度を下回ると延長が止まり、最後の減点からぴったり5秒後に自然消滅する！
                            p["expire_time"] = current_time + 5.0
                            popup_found = True
                            break
                            
                    if not popup_found:
                        add_score_popup(self, -deduction, f"速度制限超過 -{self.accumulated_speed_penalty}", COLOR_B_EMG, "neg", "速度制限超過", current_time)
                    else:
                        self.score -= deduction
                        # ★ 追加：内訳貯金箱からも直接引く
                        self.score_details["limit"] -= deduction
                        
                    self.last_speed_limit_penalty_time = current_time
        else:
            self.is_speed_limit_exceeded = False
            # 速度が下回り、ポップアップが消滅したら累積をリセット
            if not any(p.get("category") == "速度制限超過" for p in getattr(self, 'popups', [])):
                self.accumulated_speed_penalty = 0

    if getattr(self, 'is_first_udp', False) and self.bve_next_loc != -1.0:
        self.prev_door = getattr(self, 'bve_door', 0)
        self.prev_doordir = getattr(self, 'bve_doordir', 1)
        self.prev_next_loc = self.bve_next_loc
        if abs(self.bve_next_loc - self.bve_location) > 100.0:
            self.is_first_station = False 
        self.is_first_udp = False
        
    if self.bve_speed >= 1.0 and getattr(self, 'bve_door', 0) == 0:
        self.has_departed = True
        self.stop_notch_state = "IDLE"
        if getattr(self, 'jump_lock', False):
            self.jump_lock = False
        self.is_first_station = False 
        
    current_s = self.bve_time_ms // 1000
    target_s = self.bve_next_time // 1000
    diff_s = target_s - current_s
    is_operational_stop = (self.bve_is_pass == 0 and getattr(self, 'bve_doordir', 1) == 0)
    
    if getattr(self, 'prev_next_loc', -1.0) != -1.0 and self.bve_next_loc != self.prev_next_loc:
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
        
    if not getattr(self, 'is_approaching', False) and self.bve_next_loc >= 0:
        actual_margin = getattr(self, 'setting_stop_distance', -1) if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        if abs(self.bve_next_loc - self.bve_location) < actual_margin:
            self.is_approaching = True

    if getattr(self, 'is_approaching', False) and self.bve_speed == 0.0 and not getattr(self, 'has_scored_stop_this_station', False):
        d = self.bve_next_loc - self.bve_location
        if not (-self.bve_margin_f <= d <= self.bve_margin_b):
            self.is_stopped_out_of_range = True 

    if is_operational_stop and getattr(self, 'is_approaching', False) and self.bve_speed == 0.0 and not getattr(self, 'has_scored_stop_this_station', False):
        # =================================================================
        # ★ 修正②: 作者定義の停止位置許容範囲内(-margin_f ~ margin_b)で停車した時だけ発動させる！
        # =================================================================
        dist_to_stop = self.bve_next_loc - self.bve_location
        if (-self.bve_margin_f <= dist_to_stop <= self.bve_margin_b):
            if not getattr(self, 'jump_lock', False) and not getattr(self, 'is_first_station', False):
                
                # 1. 先に時分採点を行う
                curr_sta_idx = -1
                p_loc = getattr(self, 'prev_next_loc', getattr(self, 'bve_next_loc', -1.0))
                for i, st in enumerate(getattr(self, 'station_list', [])):
                    if abs(st["location"] - p_loc) < 1.0:
                        curr_sta_idx = i
                        break
                is_scoring_end_station_op = (curr_sta_idx == getattr(self, 'setting_end_idx', -1)) or (getattr(self, 'prev_term', 0) == 1)
                is_timing_active_op = self.is_station_timing(curr_sta_idx) if curr_sta_idx >= 0 else False
                
                if is_scoring_end_station_op and is_timing_active_op and not getattr(self, 'has_scored_time_this_station', False):
                    # =================================================================
                    # ★ 修正④: 終了駅の到着時はC#の計算を無視して、着時刻(raw_arr)から正確に算出する
                    # =================================================================
                    arr_target_s = self.bve_next_time // 1000
                    if curr_sta_idx >= 0 and getattr(self, 'station_list', [])[curr_sta_idx].get("raw_arr", -1) >= 0:
                        arr_target_s = getattr(self, 'station_list', [])[curr_sta_idx]["raw_arr"] // 1000
                    arr_diff_s = arr_target_s - (self.bve_time_ms // 1000)
                    
                    apply_time_score(self, arr_diff_s, current_time)
                    self.is_official_retry = False
                    self.has_scored_time_this_station = True

                # 2. そのあとに到着判定（ここで終了フラグ is_scoring_finished が立つ）
                evaluate_arrival(self, current_time)
                    
            self.has_scored_stop_this_station = True

    # ★ 謎2解決：終了駅（TERM:1 または ユーザー指定駅）での扉開け時の時分採点
    curr_sta_idx = -1
    p_loc = getattr(self, 'prev_next_loc', getattr(self, 'bve_next_loc', -1.0))
    for i, st in enumerate(getattr(self, 'station_list', [])):
        if abs(st["location"] - p_loc) < 1.0:
            curr_sta_idx = i
            break
    is_scoring_end_station = (curr_sta_idx == getattr(self, 'setting_end_idx', -1)) or (getattr(self, 'prev_term', 0) == 1)

    is_timing_active = self.is_station_timing(curr_sta_idx) if curr_sta_idx >= 0 else False

    if not is_operational_stop and getattr(self, 'prev_door', 0) == 0 and getattr(self, 'bve_door', 0) == 1:
        # =========================================================
        # ★ 修正：ワープ待機中の「幻のドア開閉」を完全にシャットアウト
        if not getattr(self, 'is_official_jumping', False):
            if is_scoring_end_station and is_timing_active and not getattr(self, 'has_scored_time_this_station', False):
                allow_score = not getattr(self, 'jump_lock', False) or getattr(self, 'is_official_retry', False)
                if allow_score and not getattr(self, 'is_first_station', False):
                    apply_time_score(self, getattr(self, 'prev_diff_s', 0), current_time)
                    self.is_official_retry = False
                self.has_scored_time_this_station = True
                
            evaluate_arrival(self, current_time)
            self.has_scored_stop_this_station = True
        # =========================================================

    allow_score = not getattr(self, 'jump_lock', False) or getattr(self, 'is_official_retry', False)
    
    '''
    if not is_operational_stop and getattr(self, 'prev_door', 0) == 1 and getattr(self, 'bve_door', 0) == 0:
        # =========================================================
        # ★ 修正：ワープ待機中の「幻のドア開閉」をシャットアウト
        if not getattr(self, 'is_official_jumping', False):
            if getattr(self, 'prev_term', 0) == 0 and is_timing_active and not getattr(self, 'has_scored_time_this_station', False):
                if allow_score and not getattr(self, 'is_first_station', False):
                    apply_time_score(self, getattr(self, 'prev_diff_s', 0), current_time)
                    self.is_official_retry = False 
                self.has_scored_time_this_station = True
        # =========================================================
    '''
    self.prev_next_loc = self.bve_next_loc
    self.prev_door = getattr(self, 'bve_door', 0)
    self.prev_doordir = getattr(self, 'bve_doordir', 1)
    self.prev_is_pass = self.bve_is_pass
    self.prev_is_timing = self.bve_is_timing
    self.prev_term = self.bve_term
    self.prev_diff_s = diff_s

# ------------------ ここから下を上書き ------------------
    rnd_tail_limit = round(self.map_tail_limit, 1)
    rnd_head_limit = round(self.map_head_limit, 1)
    rnd_sig_limit  = round(self.bve_signal_limit, 1)
    rnd_fwd_sig_limit = round(self.bve_fwd_sig_limit, 1)

    true_map_limit = rnd_tail_limit 
    self.effective_limit = min(true_map_limit, rnd_sig_limit)
    base_limit = self.effective_limit 
    
    self.base_limit_type = "signal" if rnd_sig_limit < true_map_limit else "map"

    if self.bve_speed == 0.0:
        self.prev_base_limit = base_limit
        self.limit_changed_loc = self.bve_location

    if self.current_base_limit != base_limit:
        if self.current_base_limit < 999.0: 
            self.prev_base_limit = self.current_base_limit
            self.limit_changed_loc = self.bve_location
        self.current_base_limit = base_limit

    future_targets = []
    for loc, val in self.bve_map_limits:
        future_targets.append((loc, round(val, 1), "map"))
        
    if self.bve_fwd_sig_loc > self.bve_location and rnd_fwd_sig_limit < 999.0:
        future_targets.append((self.bve_fwd_sig_loc, rnd_fwd_sig_limit, "signal"))
        
    future_targets.sort(key=lambda x: x[0])

    is_waiting_tail = (rnd_tail_limit < rnd_head_limit)
    self.dbg_is_wait = is_waiting_tail

    if is_waiting_tail:
        target_val = min(rnd_head_limit, rnd_sig_limit)
        target_type = "signal" if rnd_sig_limit < rnd_head_limit else "map"
        target_loc = self.bve_location + self.bve_clear_dist
    else:
        target_val = self.effective_limit
        target_type = self.base_limit_type
        target_loc = self.bve_location

    active_red = None # ←この1行と、下の for loc, val, l_type in future_targets: の中身を丸ごと書き換えます。

    # =================================================================
    # ★ 新ロジック1：全ての制限の警告状態を一旦ストックする
    future_evals = []
    active_zone_end_dist = -1.0
    running_base_speed = base_limit

    for loc, val, l_type in future_targets:
        if loc > self.bve_location:
            peak_speed = max(running_base_speed, target_val) if is_waiting_tail else running_base_speed
            entry_speed = running_base_speed
            
            if peak_speed > val: 
                if is_waiting_tail and target_val > running_base_speed:
                    dist_of_hill = (loc - self.bve_location) - self.bve_clear_dist
                    if dist_of_hill < 0: dist_of_hill = 0
                    entry_speed = running_base_speed
                else:
                    if running_base_speed == base_limit and self.prev_base_limit < base_limit:
                        dist_of_hill = loc - self.limit_changed_loc
                        entry_speed = self.prev_base_limit
                    else:
                        dist_of_hill = 0
                        entry_speed = running_base_speed
                        
                if dist_of_hill > 0:
                    v_apex = calculate_apex_speed(entry_speed, peak_speed, dist_of_hill, val)
                else:
                    v_apex = entry_speed
            else:
                v_apex = peak_speed
            
            v_assumed = max(val, min(peak_speed, v_apex))
            
            if val < target_val:
                advanced_dist = max(0.0, self.bve_train_length - self.bve_clear_dist)
                zone_length = (loc - self.bve_location) + advanced_dist
                if is_waiting_tail and zone_length <= self.bve_train_length + 1.0:
                    target_val = val
                    target_type = l_type
                    target_loc = loc
                            
            # =========================================================
            # ★ 修正1: calc_v の階段崩壊バグを修正！
            # 全てを現在速度から計算せず、ちゃんと階段状(v_assumed)に計算する
            # =========================================================
            if val < peak_speed and val < self.effective_limit:
                if running_base_speed >= 999.0:
                    calc_v = max(self.bve_speed, val + 1.0)
                    if self.prev_base_limit < 999.0 and self.bve_speed < self.prev_base_limit:
                        calc_v = max(calc_v, self.prev_base_limit)
                else:
                    calc_v = max(v_assumed, val + 1.0)
                
                decel_dist, warn_dist = calculate_warning_distance(calc_v, val)
                dist_to_limit = loc - self.bve_location
                
                urgency = dist_to_limit - decel_dist
                is_warning = (dist_to_limit <= warn_dist)
                
                future_evals.append({
                    'loc': loc, 'val': val, 'dist': dist_to_limit, 
                    'decel_dist': decel_dist, 'urgency': urgency, 'type': l_type
                })
                
                if is_warning:
                    active_zone_end_dist = max(active_zone_end_dist, dist_to_limit)

            if val < running_base_speed:
                running_base_speed = val

    # =================================================================
    # ★ 新ロジック2：巻き込み発動（ブラックホール）
    active_reds = []
    if active_zone_end_dist > 0:
        for ev in future_evals:
            if ev['dist'] <= active_zone_end_dist:
                active_reds.append(ev)

    # =================================================================
    # ★ 新ロジック3：勝ち抜き戦と「絶対防壁ラチェット（ハイジャック防止）」
    # =================================================================
    if not hasattr(self, 'strictest_flashed_val'):
        self.strictest_flashed_val = 999.0
        self.strictest_flashed_key = None

    if not active_reds:
        self.current_flashing_key = None
        active_red = None
    else:
        active_reds.sort(key=lambda x: x['dist'])
        
        # 通過検知による防壁リセット
        current_keys = [f"{r['loc']}_{r['val']}" for r in active_reds]
        if getattr(self, 'current_flashing_key', None) not in current_keys:
            self.strictest_flashed_val = 999.0
            
        if not hasattr(self, 'limit_flash_counts'):
            self.limit_flash_counts = {}
            
        active_red = None
        for i, r in enumerate(active_reds):
            # ハイジャック防止：既に点滅した厳しい制限より緩いものは横入りさせない
            if r['val'] > self.strictest_flashed_val:
                continue
                
            key = f"{r['loc']}_{r['val']}"
            count = self.limit_flash_counts.get(key, 0)
            
            # 「最後の1つ(本命)」 または 「まだ2回点滅していない」ならこれを表示！
            if i == len(active_reds) - 1 or count < 2:
                active_red = r
                self.current_flashing_key = key
                self.strictest_flashed_val = r['val']
                self.strictest_flashed_key = key
                break
                
        if active_red is None:
            self.current_flashing_key = None
            
    # ロックした制限を通過した時の確実な解除処理
    is_passed = True
    if getattr(self, 'strictest_flashed_key', None):
        for loc, val, _ in future_targets:
            if f"{loc}_{val}" == self.strictest_flashed_key:
                is_passed = False
                break
    if is_passed:
        self.strictest_flashed_val = 999.0
        self.strictest_flashed_key = None
    # =================================================================

    active_blue = None
    if target_val > self.effective_limit: 
        is_capped = (target_val != min(rnd_head_limit, rnd_sig_limit)) if is_waiting_tail else False
        dist_for_blue = (target_loc - self.bve_location) if is_capped else max(1.0, self.bve_clear_dist)
        active_blue = {'val': target_val, 'dist': max(1.0, dist_for_blue), 'type': target_type}

    # =================================================================
    # ★ 修正: デバッグ変数の代入と、配列(active_reds)の文字列化
    self.dbg_target_cap = target_val
    self.dbg_red = str(active_red['val']) if active_red else "None"
    self.dbg_blue = str(active_blue['val']) if active_blue else "None"
    self.dbg_active_reds = ", ".join([f"{r['val']}km/h({r['dist']:.0f}m)" for r in active_reds]) if active_reds else "None"
    # =================================================================

    self.blink_active = False
    self.target_type = self.base_limit_type

    if self.bve_speed > 0.1:
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
    else:
        self.disp_limit = self.effective_limit
        self.limit_color = COLOR_WHITE
        self.blink_active = False

    if self.blink_active:
        self.blink_phase += dt / blink_cycle
        if self.blink_phase >= 1.0: 
            self.blink_phase -= 1.0
            if getattr(self, 'current_flashing_key', None):
                k = self.current_flashing_key
                self.limit_flash_counts[k] = self.limit_flash_counts.get(k, 0) + 1
    else:
        self.blink_phase = 0.0
        
    self.prev_frame_loc = self.bve_location

    #"""
    # =================================================================
    # ★ 原因究明用：デスクトップに Debug.log を出力するトラップ (賢い版 - 距離変動無視)
    # =================================================================
    import os
    debug_file = os.path.join(os.path.expanduser("~"), "Desktop", "Debug.log")
    
    future_str = str(future_targets[:2])
    
    # ★ 修正: Redsの距離変動でログが埋まらないよう、キーには「速度」だけを含める！
    # (例: "90.0, 70.0" のように速度だけを抽出)
    active_reds_key = ",".join([str(r['val']) for r in active_reds]) if active_reds else "None"
    
    # 状態を一意に特定するための「キー」を作成（Loc、時刻、そして「変動する距離」を排除）
    current_state_key = f"{self.map_head_limit}_{self.map_tail_limit}_{self.effective_limit}_{is_waiting_tail}_{target_val}_{self.dbg_target_cap}_{self.dbg_blue}_{self.dbg_red}_{active_reds_key}_{future_str}"
    
    # 2. ログに出力するテキスト本体 (出力する時はしっかり距離も出す)
    log_text = (f"[{current_time:.1f}s] Loc:{self.bve_location:.1f}m | HeadLmt:{self.map_head_limit} TailLmt:{self.map_tail_limit} Eff:{self.effective_limit}\n"
                f"    wait_tail:{is_waiting_tail} | tgt_val:{target_val} | clear_dist:{self.bve_clear_dist:.1f}\n"
                f"    future:{future_str}... \n"
                f"    RESULT -> TC:{self.dbg_target_cap} AB:{self.dbg_blue} AR:{self.dbg_red} | Reds:[{self.dbg_active_reds}]\n\n")

    try:
        # 初回起動時：とりあえず最初の1回目を書き込む
        if not hasattr(self, 'last_debug_state_key'):
            self.last_debug_state_key = current_state_key
            self.last_pending_log = log_text
            with open(debug_file, "a", encoding="utf-8") as f:
                f.write("====== DEBUG LOG START ======\n\n")
                f.write(log_text)
                
        # 状態が変化した瞬間！
        elif current_state_key != self.last_debug_state_key:
            with open(debug_file, "a", encoding="utf-8") as f:
                f.write(self.last_pending_log)
                f.write("--- 状態変化 ---\n")
                f.write(log_text)
                
            self.last_debug_state_key = current_state_key
            self.last_pending_log = log_text
            
        # 状態が全く同じ時（普段走っている間）
        else:
            self.last_pending_log = log_text
            
    except Exception:
        pass
    # =================================================================
    #"""