import os

from PyQt6.QtNetwork import QHostAddress

from config import *
from utils import (
    calculate_apex_speed,
    calculate_warning_distance,
    write_desktop_log,
)

def reset_transient_scoring_state(self):
    """
    ジャンプや時刻巻き戻りによって継続不能になった、
    フレーム間の一時的な採点・物理判定状態を初期化する。

    総得点、得点内訳、採点設定、リトライ回数、
    駅単位の採点済み状態は変更しない。
    """
    self.g_history.clear()
    self.bcp_history.clear()

    # 不正ジャンプなどの警告は、後続の時刻巻き戻りリセットでも保持する
    self.popups = [
        popup
        for popup in getattr(self, 'popups', [])
        if popup.get("category") == "警告"
    ]

    # 非常ブレーキ判定
    self.ecb_eb_accum_time = 0.0
    self.ecb_eb_cooling_time = 0.0
    self.smee_eb_frozen = False
    self.eb_applied = False

    # 基本制動判定
    self.bb_state = "IDLE"
    self.bb_apply_count = 0
    self.bb_release_count = 0

    # 初動・緩和ブレーキ判定
    self.hb_strong_entered = False


def reset_station_evaluation_state(self):
    """
    現在の対象駅に対する接近・範囲外停車・採点済み状態を初期化する。

    出発済み状態、基本制動の内部状態、得点、採点設定、
    リトライ回数は変更しない。
    """
    self.is_approaching = False
    self.is_stopped_out_of_range = False
    self.has_scored_time_this_station = False
    self.has_scored_stop_this_station = False


def reset_score_accumulation(self):
    """
    総得点と採点内訳を同時に0へ戻す。

    チェックポイント、リトライ回数、採点設定、
    採点中・終了済みなどの状態は変更しない。
    """
    self.score = 0

    for key in self.score_details:
        self.score_details[key] = 0


def reset_result_display_state(self):
    """
    前回の採点終了後に残る、結果表示・保存関連の状態を初期化する。

    採点中かどうか、得点、得点内訳、チェックポイント、
    リトライ回数、採点設定は変更しない。
    """
    self.is_scoring_finished = False
    self.is_result_saved = False
    self.saved_file_path = ""
    self.end_message_time = 0.0
    self.result_screen_time = 0.0


def reset_speed_penalty_state(self):
    """
    速度制限超過の継続判定と表示用累積値を初期化する。

    総得点、得点内訳、制限速度予告の表示状態は変更しない。
    """
    self.is_speed_limit_exceeded = False
    self.last_speed_limit_penalty_time = 0.0
    self.accumulated_speed_penalty = 0


def reset_roll_state(self):
    """
    転動距離と移動中状態を初期化し、
    次の転動を新しい表示事象として扱う。

    総得点、転動の得点内訳、既存ポップアップは変更しない。
    """
    self.door_open_loc = self.bve_location
    self.roll_penalty_count = 0
    self.roll_was_moving = False
    self.roll_event_id += 1

def write_limit_debug_log(
    self,
    current_time,
    is_waiting_tail,
    target_val,
    future_targets,
    active_reds,
):
    if not getattr(self, 'enable_limit_debug_log', False):
        return

    debug_file = os.path.join(
        os.path.expanduser("~"),
        "Desktop",
        "Debug.log"
    )
    future_str = str(future_targets[:2])

    # 距離変動による過剰なログ出力を避けるため、制限値だけを状態キーに含める
    active_reds_key = (
        ",".join(str(red['val']) for red in active_reds)
        if active_reds
        else "None"
    )

    # 距離などの連続的に変動する値を除いて診断状態を識別する
    current_state_key = (
        f"{self.map_head_limit}_"
        f"{self.map_tail_limit}_"
        f"{self.effective_limit}_"
        f"{is_waiting_tail}_"
        f"{target_val}_"
        f"{self.dbg_target_cap}_"
        f"{self.dbg_blue}_"
        f"{self.dbg_red}_"
        f"{active_reds_key}_"
        f"{future_str}"
    )

    log_text = (
        f"[{current_time:.1f}s] "
        f"Loc:{self.bve_location:.1f}m | "
        f"HeadLmt:{self.map_head_limit} "
        f"TailLmt:{self.map_tail_limit} "
        f"Eff:{self.effective_limit}\n"
        f"    wait_tail:{is_waiting_tail} | "
        f"tgt_val:{target_val} | "
        f"clear_dist:{self.bve_clear_dist:.1f}\n"
        f"    future:{future_str}... \n"
        f"    RESULT -> "
        f"TC:{self.dbg_target_cap} "
        f"AB:{self.dbg_blue} "
        f"AR:{self.dbg_red} | "
        f"Reds:[{self.dbg_active_reds}]\n\n"
    )

    try:
        if not hasattr(self, 'last_debug_state_key'):
            self.last_debug_state_key = current_state_key
            self.last_pending_log = log_text

            with open(debug_file, "a", encoding="utf-8") as file:
                file.write("====== DEBUG LOG START ======\n\n")
                file.write(log_text)

        elif current_state_key != self.last_debug_state_key:
            with open(debug_file, "a", encoding="utf-8") as file:
                file.write(self.last_pending_log)
                file.write("--- 状態変化 ---\n")
                file.write(log_text)

            self.last_debug_state_key = current_state_key
            self.last_pending_log = log_text

        else:
            self.last_pending_log = log_text

    except Exception:
        pass

def update_result_display(self, current_time):
    # 表示期限を過ぎたポップアップを削除する
    self.popups = [
        popup
        for popup in getattr(self, 'popups', [])
        if popup["expire_time"] > current_time
    ]

    # 採点終了から5秒後に終了メッセージを表示する
    if (
        getattr(self, 'end_message_time', 0.0) > 0
        and current_time >= self.end_message_time
    ):
        if getattr(self, 'is_scoring_finished', False):
            add_score_popup(
                self,
                0,
                "運転お疲れ様でした。",
                COLOR_WHITE,
                "big",
                "終了",
                current_time,
                force=True,
            )

        self.end_message_time = 0.0

    # 採点終了から10秒後にリザルト画面を開く
    if (
        getattr(self, 'result_screen_time', 0.0) > 0
        and current_time >= self.result_screen_time
    ):
        if getattr(self, 'is_scoring_finished', False):
            self.toggle_menu(True)
            self.menu_state = 11
            self.menu_cursor = 0
            getattr(self, 'popups', []).clear()

        self.result_screen_time = 0.0

def update_speed_limit_penalty(self, current_time):
    if (
        getattr(self, 'is_scoring_mode', False)
        and not getattr(self, 'is_scoring_finished', False)
        and not getattr(self, 'is_official_jumping', False)
        and not getattr(self, 'is_first_udp', False)
        and getattr(self, 'pen_limit', True)
    ):
        current_limit = getattr(self, 'effective_limit', 1000.0)

        # 前進・後退のどちらでも速度の絶対値で超過を判定する
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
                            # 超過中は表示期限を更新し続ける
                            # 超過解消後は、最後の減点から5秒後にポップアップを終了する
                            p["expire_time"] = current_time + 5.0
                            popup_found = True
                            break

                    if not popup_found:
                        add_score_popup(self, -deduction, f"速度制限超過 -{self.accumulated_speed_penalty}", COLOR_B_EMG, "neg", "速度制限超過", current_time)
                    else:
                        self.score -= deduction
                        # 速度超過減点を得点内訳にも反映する
                        self.score_details["limit"] -= deduction

                    self.last_speed_limit_penalty_time = current_time
        else:
            self.is_speed_limit_exceeded = False
            # 速度が下回り、ポップアップが消滅したら累積をリセット
            if not any(p.get("category") == "速度制限超過" for p in getattr(self, 'popups', [])):
                self.accumulated_speed_penalty = 0

def detect_physical_emergency_brake(self, dt):
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
    return is_eb_handle, physical_eb_tripped

def update_stop_jerk_penalty(self, current_time, decel_g):
    if self.bve_speed == 0.0:
        if self.is_stopping_zone:
            self.stop_notch_state = get_notch_state(self, self.bve_brk_notch)

            recent_g = [h[1] for h in self.g_history if current_time - h[0] <= 0.5]
            if recent_g:
                self.last_stop_g = sum(recent_g) / len(recent_g)
            else:
                self.last_stop_g = decel_g

            # 前進・後退のどちらでも加速度の絶対値で停車時衝動を判定する
            abs_stop_g = abs(self.last_stop_g)

            if getattr(self, 'pen_jerk', True):
                if abs_stop_g >= 0.10:
                    add_score_popup(self, -200, "停車時衝動 -200", COLOR_B_EMG, "neg", "停車時衝動", current_time)
                elif abs_stop_g >= 0.065:
                    add_score_popup(self, -100, "停車時衝動 -100", COLOR_B_EMG, "neg", "停車時衝動", current_time)
            self.is_stopping_zone = False

        curr_n = self.bve_brk_notch
        self.hb_prev_notch = curr_n

    elif 0.0 < abs(self.bve_speed): #<= 1.5
        self.is_stopping_zone = True

def update_emergency_brake_penalty(
    self,
    current_time,
    physical_eb_tripped,
    in_station_zone,
):
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
    else:
        self.eb_applied = False

def begin_official_jump(self, target_loc, target_time):
    """
    採点開始またはリトライによる公式ジャンプの保護を開始する。

    ジャンプ先の位置・時刻を記録し、
    C#からJUMP_COMPLETEを受信するまで公式ジャンプ状態を維持する。
    """
    self.is_official_jumping = True
    self.expected_target_loc = target_loc
    self.expected_target_time = target_time
    self.pending_jump_complete = None


def execute_retry(self, index, is_bve_advancing):
    if index < 0 or index >= len(self.save_data): return

    self.is_official_retry = (index > 0)
    self.is_first_station = (index == 0)

    if index == 0:
        self.total_retry_count = 0

    reset_result_display_state(self)
    reset_speed_penalty_state(self)
    reset_roll_state(self)

    self.has_departed = False
    reset_station_evaluation_state(self)
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

    target_bve_sta_idx = 0
    ideal_loc = cp['loc']
    def_t = -1
    calc_t = -1  # 比較用の計算時刻

    if getattr(self, 'station_list', []):
        for i, st in enumerate(self.station_list):
            if abs(st["location"] - cp['loc']) < 100.0:
                target_bve_sta_idx = i
                ideal_loc = st["location"]
                def_t = st.get("def_time", -1)

                # 駅データから比較用の計算時刻を求める
                raw_dep = st.get("raw_dep", -1)
                stop_t = st.get("stop_time", 15000)
                calc_t = (raw_dep - stop_t) if raw_dep >= 0 else -1
                break

    # LOC方式を使用する条件
    # 1. 開始駅以外の途中駅である
    # 2. 作者定義時刻が計算時刻より遅い
    # 3. チェックポイント時刻が作者定義時刻より早い
    use_legacy = (target_bve_sta_idx > 0 and def_t >= 0 and calc_t >= 0 and def_t > calc_t and cp['time_ms'] < def_t)

    if use_legacy:
        cmd = f"JUMP_LOC_TIME:{ideal_loc}:{cp['time_ms']}"
    else:
        cmd = f"JUMP_STA_TIME:{target_bve_sta_idx}:{cp['time_ms']}"

    begin_official_jump(self, ideal_loc, cp['time_ms'])
    self.udp_socket.writeDatagram(cmd.encode('utf-8'), QHostAddress.SpecialAddress.LocalHost, 54322)

def add_score_popup(self, points, text, color, ptype, category, current_time, force=False):
    if not getattr(self, 'is_scoring_mode', False) and not force: return
    # 採点終了後は、強制表示を除く新たな加点・減点を受け付けない
    if getattr(self, 'is_scoring_finished', False) and not force: return
    self.score += points
    # 得点をカテゴリ別の内訳へ反映する
    cat_map = {
        "運転時分": "time", "停止位置": "stop", "基本制動": "base_brake",
        "ボーナス": "bonus", "転動": "roll", "停車時衝動": "jerk",
        "初動ブレーキ": "init_brake", "緩和ブレーキ": "rel_brake",
        "非常ブレーキ": "eb", "速度制限超過": "limit", "ATS信号無視": "ats"
    }
    if category in cat_map:
        key = cat_map[category]
        self.score_details[key] += points
    self.popups.append({"text": text, "color": color, "expire_time": current_time + 5.0, "type": ptype, "category": category})

def apply_time_score(self, diff_s, current_time):
    if not getattr(self, 'is_scoring_mode', False) or getattr(self, 'is_scoring_finished', False): return
    abs_diff = abs(diff_s)
    if abs_diff <= 9: add = 300
    elif abs_diff <= 19: add = 200
    elif abs_diff <= 29: add = 100
    else: add = 0
    if add > 0:
        # 運転時分は通常の加点として処理する
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

        # 実際の開扉時間を基準停車時間へ加算する
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
                        write_desktop_log(
                            f"[SAVE] 開扉時間を反映: "
                            f"{st.get('name', '駅')}にて "
                            f"{door_time}ms をセーブデータ時刻に加算"
                        )

        self.save_data.append({
            "loc": self.bve_location,
            "time_ms": save_time_ms,  # 開扉時間を反映した時刻を保存する
            "score": self.score,
            # 後続の得点変更から独立させるため、現在の得点内訳をコピーして保存する
            "score_details": self.score_details.copy(),
            "target_loc": self.bve_next_loc,
            "station_name": getattr(self, 'bve_current_station_name', '不明な駅'),
            "stop_error": stop_error
        })

def evaluate_arrival(self, current_time, arrival_target_loc=None):
    if getattr(self, 'is_scoring_finished', False):
        return

    curr_sta_idx = -1

    if arrival_target_loc is None:
        # 運転停車など、従来経路では直前のターゲット駅を使用する
        p_loc = getattr(
            self,
            'prev_next_loc',
            getattr(self, 'bve_next_loc', -1.0)
        )
    else:
        # 通常停車駅の開扉時は、BVE公式が示している現在の駅を使用する
        p_loc = arrival_target_loc

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
    is_rescue = False # 2段制動の救済適用状態

    # 現在の基本制動ルールを取得し、OFFの場合は判定を省略する
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
                    # 制動・緩和回数を現在のルール上限と比較する
                    apply_ok = (app_limit == 0) or (getattr(self, 'bb_apply_count', 0) <= app_limit)
                    release_ok = (rel_limit == 0) or (getattr(self, 'bb_release_count', 0) <= rel_limit)
                    # 1段制動設定では、2段制動を減点付きで救済する
                    if not apply_ok and b_rule_app == "1段" and getattr(self, 'bb_apply_count', 0) == 2 and release_ok:
                        is_rescue = True
                        apply_ok = True # 表示ブロックへ進めるために合格扱いにする


    if is_zero_stop and getattr(self, 'is_scoring_mode', False):
        add_score_popup(self, 0, "0cm停車成功!!!", COLOR_N, "big", "ボーナス", current_time)

    if apply_ok and release_ok and getattr(self, 'is_scoring_mode', False):
        # 救済適用の有無に応じて表示内容と加点を切り替える
        if is_rescue:
            # 救済：メッセージを「2段制動〜」に変更し、点数を +300 にする
            add_score_popup(self, 0, f"2段制動{b_rule_rel}緩め成功!!!", COLOR_N, "big", "基本制動", current_time)
            add_score_popup(self, 300, "基本制動 +300", COLOR_N, "pos", "基本制動", current_time)
        else:
            # 通常成功：設定通りのルール名を表示し、点数を +500 にする
            add_score_popup(self, 0, f"{b_rule_app}制動{b_rule_rel}緩め成功!!!", COLOR_N, "big", "基本制動", current_time)
            add_score_popup(self, 500, "基本制動 +500", COLOR_N, "pos", "基本制動", current_time)

    if is_zero_stop and apply_ok and release_ok and getattr(self, 'is_scoring_mode', False):
        add_score_popup(self, 500, "ボーナス +500", COLOR_N, "pos", "ボーナス", current_time)

    if is_scoring_end_station:
        self.is_scoring_finished = True
        # 採点終了から5秒後に終了メッセージを表示する
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
                write_desktop_log("  => 判定: 【得点内訳と総合得点が一致】")
            else:
                write_desktop_log("  => 判定: 【得点内訳と総合得点が不一致】")
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

    # 駅を特定できない場合、または採時対象外の場合は時分採点を行わない
    is_timing_active = False
    if p_idx >= 0:
        # F6メニューの設定(override)も含めて判定する関数を呼ぶ
        is_timing_active = self.is_station_timing(p_idx)
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
                        station = (
                            getattr(self, 'station_list', [])[p_idx]
                            if 0 <= p_idx < len(getattr(self, 'station_list', []))
                            else {}
                        )

                        write_desktop_log(
                            "[TIMING FALLBACK]\n"
                            f"  - station: {station.get('name', '不明な駅')}\n"
                            f"  - station_idx: {p_idx}\n"
                            f"  - station_loc: {p_loc}\n"
                            f"  - raw_dep: {station.get('raw_dep', -1)}\n"
                            f"  - def_time: {station.get('def_time', -1)}\n"
                            f"  - stop_time: {station.get('stop_time', -1)}\n"
                            f"  - is_timing: {is_timing_active}\n"
                            f"  - is_terminal: {station.get('is_terminal', False)}\n"
                            f"  - prev_next_time_exists: {hasattr(self, 'prev_next_time')}\n"
                            f"  - prev_next_time: {getattr(self, 'prev_next_time', None)}\n"
                            f"  - bve_time_ms: {self.bve_time_ms}\n"
                            f"  - is_official_retry: {getattr(self, 'is_official_retry', False)}\n"
                        )

                        dep_target_s = getattr(
                            self,
                            'prev_next_time',
                            self.bve_time_ms
                        ) // 1000

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
    # 現在の対象区間に適用される基本制動ルールを取得する
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

            # 次の対象駅を基準に適用区間を判定する
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

    update_result_display(self, current_time)

    decel_g = -self.bve_calc_g
    self.g_history.append((current_time, decel_g, self.bve_brk_notch, self.bve_brk_max))
    cutoff_time = current_time - 10.0
    self.g_history = [h for h in self.g_history if h[0] > cutoff_time]

    if self.bve_jump_count != getattr(self, 'last_jump_count', 0):
        write_desktop_log(f"[JUMP DETECT] BVEジャンプ検知！ カウント: {getattr(self, 'last_jump_count', 0)} -> {self.bve_jump_count}")

        # 前回の不正ジャンプ警告が表示中なら、
        # 追加のジャンプが発生した時点で表示を終了する
        self.popups = [
            popup
            for popup in getattr(self, 'popups', [])
            if popup.get("category") != "警告"
        ]

        is_valid_jump = False
        was_official_jumping = getattr(
            self,
            'is_official_jumping',
            False
        )

        if was_official_jumping:
            # 公式ジャンプ中のJUMP通知は、C#の完了通知が届くまで保留する。
            # この通知だけでは公式ジャンプの成否を確定しない。
            is_valid_jump = True

        # ジャンプ前の物理・ブレーキ判定状態を破棄
        reset_transient_scoring_state(self)

        # ジャンプ検出時だけ初期化する状態
        self.has_evaluated_initial_brake = False
        self.idle_entered_while_stopped = False

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

    update_stop_jerk_penalty(
        self,
        current_time,
        decel_g,
    )

    is_eb_handle, physical_eb_tripped = (
        detect_physical_emergency_brake(self, dt)
    )

    update_emergency_brake_penalty(
        self,
        current_time,
        physical_eb_tripped,
        in_station_zone,
    )

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

            # Smeeの凍結解除時も、現在の緩和ルールに基づいて免除を判定する
            rel_rule = getattr(self, 'active_rule_init_release', 'ON①')
            is_rel_exempt = (rel_rule == "OFF") or (rel_rule == "ON②" and in_station_zone)

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

    if getattr(self, 'is_official_jumping', False):
        # 公式ジャンプによる位置変化を転動として扱わない
        self.door_open_loc = self.bve_location
        self.roll_penalty_count = 0
        self.roll_was_moving = False

    elif getattr(self, 'bve_door', 0) == 1:
        is_rolling = self.bve_speed != 0.0

        if getattr(self, 'prev_door', 0) == 0:
            # 開扉した位置を転動距離の基準位置にする
            self.door_open_loc = self.bve_location
            self.roll_penalty_count = 0

            # 開扉後の最初の転動事象
            self.roll_event_id += 1
            self.roll_was_moving = is_rolling

        else:
            # 勾配による転動方向は基本的に一定とみなし、
            # 開扉位置からの変位を転動距離として扱う
            roll_distance = abs(
                self.bve_location
                - getattr(self, 'door_open_loc', self.bve_location)
            )
            current_roll_count = int((roll_distance + 1e-9) / 0.05)

            # 開扉中の累積変位について、未減点の回数を求める
            new_penalty_count = (
                current_roll_count
                - getattr(self, 'roll_penalty_count', 0)
            )

            if new_penalty_count > 0:
                penalty_points = 500 * new_penalty_count
                current_event_id = getattr(self, 'roll_event_id', 0)

                # 現在の転動事象に対応するポップアップだけを探す。
                # 前回の転動表示が残っていても再利用しない。
                roll_popup = next(
                    (
                        popup
                        for popup in getattr(self, 'popups', [])
                        if popup.get("category") == "転動"
                        and popup.get("type") == "neg"
                        and popup.get("roll_event_id") == current_event_id
                    ),
                    None
                )

                if roll_popup is None:
                    # 新しい転動事象、または既存表示が消えた後なので、
                    # 今回成立した減点額から新規表示する
                    add_score_popup(
                        self,
                        -penalty_points,
                        f"転動 -{penalty_points}",
                        COLOR_B_EMG,
                        "neg",
                        "転動",
                        current_time
                    )

                    # 直前に追加された転動ポップアップへ、
                    # 転動事象IDと表示期間内の累積額を記録する
                    for popup in reversed(getattr(self, 'popups', [])):
                        if (
                            popup.get("category") == "転動"
                            and popup.get("type") == "neg"
                            and "roll_event_id" not in popup
                        ):
                            popup["roll_event_id"] = current_event_id
                            popup["roll_display_penalty"] = penalty_points
                            break

                else:
                    # 同じ転動事象が続いている間だけ、同じ行へ累積する
                    display_penalty = (
                        roll_popup.get("roll_display_penalty", 0)
                        + penalty_points
                    )

                    roll_popup["roll_display_penalty"] = display_penalty
                    roll_popup["text"] = f"転動 -{display_penalty}"
                    roll_popup["expire_time"] = current_time + 5.0

                    # add_score_popup()を呼ばないため、
                    # 新たに成立した分を得点と内訳へ直接反映する
                    self.score -= penalty_points
                    self.score_details["roll"] -= penalty_points

                # 開扉中の累積減点回数を更新
                self.roll_penalty_count = current_roll_count

            # 動いていた状態から完全停止した瞬間に、
            # 次回の転動を新しい表示事象として扱う
            if getattr(self, 'roll_was_moving', False) and not is_rolling:
                self.roll_event_id += 1

            self.roll_was_moving = is_rolling

    else:
        # 閉扉時は転動距離をリセットする。
        # event_idは以前のポップアップとの衝突を防ぐため維持する。
        self.door_open_loc = self.bve_location
        self.roll_penalty_count = 0
        self.roll_was_moving = False

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

    update_speed_limit_penalty(self, current_time)

    if getattr(self, 'is_first_udp', False) and self.bve_next_loc != -1.0:
        self.prev_door = getattr(self, 'bve_door', 0)
        self.prev_doordir = getattr(self, 'bve_doordir', 1)
        self.prev_next_loc = self.bve_next_loc
        if abs(self.bve_next_loc - self.bve_location) > 100.0:
            self.is_first_station = False
        self.is_first_udp = False

    if (
        not getattr(self, 'is_official_jumping', False)
        and self.bve_speed >= 1.0
        and getattr(self, 'bve_door', 0) == 0
    ):
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

        reset_station_evaluation_state(self)

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
        # 作者定義の停止位置許容範囲内（-margin_f～margin_b）で停車した場合にのみ到着処理を行う
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
                    # 終了駅では駅データの着時刻を優先して運転時分を算出する
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

    # 通常停車駅の開扉時は、BVE公式が現在示している駅を対象にする
    curr_sta_idx = -1
    arrival_target_loc = getattr(self, 'bve_next_loc', -1.0)

    for i, st in enumerate(getattr(self, 'station_list', [])):
        if abs(st["location"] - arrival_target_loc) < 1.0:
            curr_sta_idx = i
            break

    is_scoring_end_station = (
        curr_sta_idx == getattr(self, 'setting_end_idx', -1)
    ) or (
        getattr(self, 'bve_term', 0) == 1
    )

    is_timing_active = (
        self.is_station_timing(curr_sta_idx)
        if curr_sta_idx >= 0
        else False
    )

    if (
        not is_operational_stop
        and getattr(self, 'prev_door', 0) == 0
        and getattr(self, 'bve_door', 0) == 1
    ):
        # 開扉後にBVE公式が示している対象駅との停止位置誤差
        arrival_stop_error = (
            arrival_target_loc
            - self.bve_location
        )

        is_within_arrival_target_margin = (
            arrival_target_loc >= 0.0
            and -self.bve_margin_f
            <= arrival_stop_error
            <= self.bve_margin_b
        )

        # 公式ジャンプ中の幻の開扉、および対象駅以外での開扉を拒否
        if (
            not getattr(self, 'is_official_jumping', False)
            and curr_sta_idx >= 0
            and is_within_arrival_target_margin
        ):
            if (
                is_scoring_end_station
                and is_timing_active
                and not getattr(
                    self,
                    'has_scored_time_this_station',
                    False
                )
            ):
                allow_score = (
                    not getattr(self, 'jump_lock', False)
                    or getattr(self, 'is_official_retry', False)
                )

                if (
                    allow_score
                    and not getattr(self, 'is_first_station', False)
                ):
                    apply_time_score(
                        self,
                        getattr(self, 'prev_diff_s', 0),
                        current_time
                    )
                    self.is_official_retry = False

                self.has_scored_time_this_station = True

            evaluate_arrival(
                self,
                current_time,
                arrival_target_loc
            )
            self.has_scored_stop_this_station = True

    self.prev_next_loc = self.bve_next_loc
    self.prev_door = getattr(self, 'bve_door', 0)
    self.prev_doordir = getattr(self, 'bve_doordir', 1)
    self.prev_is_pass = self.bve_is_pass
    self.prev_is_timing = self.bve_is_timing
    self.prev_term = self.bve_term
    self.prev_diff_s = diff_s

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

    # 各制限候補の予告判定結果を収集する
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

            # 直前の仮定速度を引き継ぎ、段階的な速度低下を前提に予告速度を計算する
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

    # 同じ制動対象区間に含まれる制限候補を統合する
    active_reds = []
    if active_zone_end_dist > 0:
        for ev in future_evals:
            if ev['dist'] <= active_zone_end_dist:
                active_reds.append(ev)

    # 最も厳しい制限候補を選択し、緩い候補による警告の上書きを防ぐ
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
            # 表示済みの厳しい制限を、後続の緩い候補で上書きしない
            if r['val'] > self.strictest_flashed_val:
                continue

            key = f"{r['loc']}_{r['val']}"
            count = self.limit_flash_counts.get(key, 0)

            # 最終候補、または点滅回数が2回未満の候補を表示する
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

    active_blue = None
    if target_val > self.effective_limit:
        is_capped = (target_val != min(rnd_head_limit, rnd_sig_limit)) if is_waiting_tail else False
        dist_for_blue = (target_loc - self.bve_location) if is_capped else max(1.0, self.bve_clear_dist)
        active_blue = {'val': target_val, 'dist': max(1.0, dist_for_blue), 'type': target_type}

    # 制限速度診断に使用する現在の判定状態を保存する
    self.dbg_target_cap = target_val
    self.dbg_red = str(active_red['val']) if active_red else "None"
    self.dbg_blue = str(active_blue['val']) if active_blue else "None"
    self.dbg_active_reds = ", ".join([f"{r['val']}km/h({r['dist']:.0f}m)" for r in active_reds]) if active_reds else "None"

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

    write_limit_debug_log(
        self,
        current_time,
        is_waiting_tail,
        target_val,
        future_targets,
        active_reds,
    )

    self.prev_frame_loc = self.bve_location