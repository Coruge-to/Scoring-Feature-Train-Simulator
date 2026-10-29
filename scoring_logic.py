import os

from PyQt6.QtNetwork import QHostAddress

from config import *
import jump_transaction
import jump_wire
import station_identity
from utils import (
    calculate_apex_speed,
    calculate_warning_distance,
    desktop_log_enabled,
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

    # 不正ジャンプなどの警告は、後続の時刻巻き戻りリセットでも保持する
    self.popups = [
        popup
        for popup in getattr(self, 'popups', [])
        if popup.get("category") == "警告"
    ]

    # 非常ブレーキ判定
    self.manual_eb_accum_time = 0.0
    self.manual_eb_cooling_time = 0.0

    # 手動EB減点済み状態は維持する。
    # 公式ジャンプ直前に成立していたEBを、
    # ジャンプ直後の新規EBとして再採点させない。

    # 基本制動判定
    self.bb_state = "IDLE"
    self.bb_apply_count = 0
    self.bb_release_count = 0
    self.bb_first_valid_stop_detected = False
    self.bb_moved_after_first_valid_stop = False

    # 初動・緩和ブレーキ判定
    self.hb_strong_entered = False
    self.has_evaluated_initial_brake = False
    self.idle_entered_while_stopped = False
    self.hb_cushion_entry_time = 0.0
    self.hb_cushion_max_g = 0.0

    # 停止イベント検出
    self.prev_stop_detection_speed = getattr(
        self,
        'bve_speed',
        0.0,
    )

def reset_station_evaluation_state(self):
    """
    現在の対象駅に対する接近・範囲外停車・採点済み状態を初期化する。

    出発済み状態、基本制動の状態・回数、得点、採点設定、
    リトライ回数は変更しない。
    初回有効停止の記録と、その後の再移動の記録は駅単位の状態なので初期化する。
    """
    self.is_approaching = False
    self.is_stopped_out_of_range = False
    self.has_scored_time_this_station = False
    self.has_scored_stop_this_station = False
    self.operational_stop_margins = None                  # 運転停車の到着駅の停止位置許容幅(MARGINF, MARGINB)は駅単位の状態
    self.operational_stop_latch = None                    # 運転停車の停止成立記録(駅index, 停止成立時刻, 予定発車時刻)は駅単位の状態
    self.bb_first_valid_stop_detected = False
    self.bb_moved_after_first_valid_stop = False
    self.close_range_departure_reset_pending = False
    self.prev_actual_stop_loc = -1.0


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
    if not desktop_log_enabled():
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

def update_manual_emergency_brake_state(self, dt):
    is_eb_handle = (
        self.bve_brk_notch >= self.bve_brk_max
        or "非常" in self.bve_brk_text
        or "EB" in self.bve_brk_text.upper()
    )

    if self.bve_btype == "Cl":
        # 自動空気ブレーキ車は、EBハンドル位置を直接使用する。
        manual_eb_qualified = is_eb_handle

    else:
        # Ecb・Smee共通の手動EB累積判定。
        if is_eb_handle:
            self.manual_eb_accum_time += dt

            if (
                self.manual_eb_accum_time
                >= MANUAL_EB_ACCUM_THRESHOLD
            ):
                self.manual_eb_accum_time = (
                    MANUAL_EB_ACCUM_THRESHOLD
                )

            self.manual_eb_cooling_time = 0.0

        else:
            if self.manual_eb_accum_time > 0.0:
                self.manual_eb_cooling_time += dt

                if (
                    self.manual_eb_cooling_time
                    >= MANUAL_EB_COOLING_THRESHOLD
                ):
                    self.manual_eb_accum_time = 0.0
                    self.manual_eb_cooling_time = 0.0
            else:
                self.manual_eb_cooling_time = 0.0

        manual_eb_qualified = (
            self.manual_eb_accum_time
            >= MANUAL_EB_ACCUM_THRESHOLD
        )

    return is_eb_handle, manual_eb_qualified


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

    elif 0.0 < abs(self.bve_speed): #<= 1.5
        self.is_stopping_zone = True

def update_manual_emergency_brake_penalty(
    self,
    current_time,
    manual_eb_qualified,
    in_station_zone,
):
    eb_event_active = manual_eb_qualified

    # 基本制動評価中に物理EBが成立した場合は、加点資格を失わせる。
    # 初回有効停止の後（速度0.0km/hのまま）の操作は観測対象外とする。
    if (
        manual_eb_qualified
        and self.bb_is_in_zone
        and not getattr(self, 'bb_first_valid_stop_detected', False)
    ):
        self.bb_state = "FAILED"

    if eb_event_active:
        if not self.manual_eb_penalty_applied:
            if abs(self.bve_speed) > 0.0:
                if getattr(self, 'pen_eb', True):
                    add_score_popup(
                        self,
                        -500,
                        "非常ブレーキ使用 -500",
                        COLOR_B_EMG,
                        "neg",
                        "非常ブレーキ",
                        current_time,
                    )

                rule = getattr(
                    self,
                    'active_rule_init_apply',
                    'ON①',
                )
                is_initial_exempt = (
                    rule == "OFF"
                    or (
                        rule == "ON②"
                        and in_station_zone
                    )
                )

                if (
                    not is_initial_exempt
                    and not getattr(
                        self,
                        'has_evaluated_initial_brake',
                        False,
                    )
                ):
                    add_score_popup(
                        self,
                        -100,
                        "初動ブレーキ -100",
                        COLOR_B_EMG,
                        "neg",
                        "初動ブレーキ",
                        current_time,
                    )
                    self.has_evaluated_initial_brake = True

            self.manual_eb_penalty_applied = True

    else:
        self.manual_eb_penalty_applied = False

def update_smee_virtual_emergency_brake(
    self,
    current_time,
    in_station_zone,
):
    if self.bve_btype != "Smee":
        self.smee_virtual_eb_active = False
        return

    was_virtual_eb_active = getattr(
        self,
        'smee_virtual_eb_active',
        False,
    )

    bp_threshold = (
        self.bve_bp_initial * SMEE_VIRTUAL_EB_BP_RATIO
    )

    bp_is_low = (
        self.bpPressure < bp_threshold
    )

    eb_time_qualified = (
        self.manual_eb_accum_time
        >= MANUAL_EB_ACCUM_THRESHOLD
    )

    if not was_virtual_eb_active:
        # 仮想EBの開始条件:
        # BPが規定値未満、かつ冷却時間を含む
        # EB累積判定が0.3秒以上。
        if (
            bp_is_low
            and eb_time_qualified
        ):
            self.smee_virtual_eb_active = True

        return

    # 一度仮想EBへ入った後は、
    # EB累積時間がリセットされてもBP回復まで維持する。
    if bp_is_low:
        self.smee_virtual_eb_active = True
        return

    # BPが規定値以上へ回復したため、
    # 採点上の仮想EBを解除する。
    self.smee_virtual_eb_active = False

    state_after_virtual_eb = get_notch_state(
        self,
        self.bve_brk_notch,
    )

    # 仮想EB解除時も、現在の緩和ルールに基づいて免除を判定する。
    rel_rule = getattr(
        self,
        'active_rule_init_release',
        'ON①',
    )
    is_rel_exempt = (
        rel_rule == "OFF"
        or (
            rel_rule == "ON②"
            and in_station_zone
        )
    )

    # 仮想EBから直接IDLEへ復帰した場合は、
    # EcB車でEBから一気に緩解した場合と同等に扱う。
    if (
        state_after_virtual_eb == "IDLE"
        and abs(self.bve_speed) > 0.0
        and not getattr(
            self,
            'idle_entered_while_stopped',
            False,
        )
        and not is_rel_exempt
    ):
        add_score_popup(
            self,
            -100,
            "緩和ブレーキ -100",
            COLOR_B_EMG,
            "neg",
            "緩和ブレーキ",
            current_time,
        )

def update_initial_and_release_brake_penalty(
    self,
    current_time,
    decel_g,
    in_station_zone,
    is_eb_handle,
):

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
                    elif self.bve_btype == "Smee" and self.smee_virtual_eb_active: pass
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
                    elif self.bve_btype == "Smee" and self.smee_virtual_eb_active: pass
                    else:
                        if prev_state == "CUSHION":
                            stay_time = current_time - self.hb_cushion_entry_time
                            if stay_time < 0.5: add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)
                        else: add_score_popup(self, -100, "緩和ブレーキ -100", COLOR_B_EMG, "neg", "緩和ブレーキ", current_time)

        self.hb_strong_entered = False
        self.has_evaluated_initial_brake = False

    self.hb_prev_notch = curr_n


def begin_official_jump(self, target_loc, target_time):
    """
    採点開始またはリトライによる公式ジャンプの保護を開始する。

    ジャンプ先の位置・時刻を記録し、
    C#からJUMP_COMPLETEを受信するまで公式ジャンプ状態を維持する。
    """
    reset_transient_scoring_state(self)

    self.is_official_jumping = True
    self.expected_target_loc = target_loc
    self.expected_target_time = target_time
    self.pending_jump_complete = None


def execute_retry(self, index, is_bve_advancing):
    """Phase ST-2b: the retry to the checkpoint at position `index` of the history. Returns a station_identity.RetryResult.

    The station is the StationIndex stored in that checkpoint, verified against the scope of the application (station_identity.check_retry_checkpoint); it is never
    searched by a position. A checkpoint that does not verify is REFUSED: nothing is changed, nothing is sent (the caller counts nothing and shows nothing). An accepted
    retry sends the jump request, keeps the choice as self.retry_pending and does NOT cut the history (ST-3 cuts it when the jump completed as requested)."""
    history = getattr(self, 'save_data', None)
    station_list = getattr(self, 'station_list', None)
    try:
        pending = getattr(self, 'retry_pending', None)
        pending_active = (isinstance(pending, station_identity.RetryPending) and getattr(self, 'is_official_jumping', False) and
                          0 <= pending.selected_save_position < len(history) and history[pending.selected_save_position] is pending.checkpoint)
        result = station_identity.check_retry_checkpoint(history, index, getattr(self, 'current_scenario_id', -1), getattr(self, 'bve_list_id', ""), station_list, pending_active)
    except Exception:
        return station_identity.RetryResult(False, station_identity.INTERNAL_ERROR, None, station_identity.NO_INDEX)
    if not result.accepted:
        return result
    managed = getattr(self, 'dataplane_strict', False) or getattr(self, 'jump_client', None) is not None
    if managed and getattr(self, 'jump_client', None) is None:
        return result._replace(accepted=False, reason=station_identity.JUMP_UNAVAILABLE)

    # Phase ST-3d: the request is built (and refused if the wire can not carry it) BEFORE anything is changed, by the one builder of the Jump wire v2
    cp = history[index]
    station_index = result.selected_station_index
    station = station_list[station_index]
    ideal_loc = station["location"]
    def_t = station.get("def_time", -1)

    # 駅データから比較用の計算時刻を求める
    raw_dep = station.get("raw_dep", -1)
    stop_t = station.get("stop_time", 15000)
    calc_t = (raw_dep - stop_t) if raw_dep >= 0 else -1

    # LOC方式を使用する条件
    # 1. 開始駅以外の途中駅である
    # 2. 作者定義時刻が計算時刻より遅い
    # 3. チェックポイント時刻が作者定義時刻より早い
    use_loc_method = (station_index > 0 and def_t >= 0 and calc_t >= 0 and def_t > calc_t and cp['time_ms'] < def_t)

    request_time = cp['time_ms']
    if isinstance(request_time, float) and request_time.is_integer():
        request_time = int(request_time)                      # a whole time of the history is written as the integer that it is
    planned, refusal = jump_transaction.build_jump_request(jump_wire.KIND_LOC if use_loc_method else jump_wire.KIND_STA, station_index, request_time,
                                                           station_identity.scope_of(getattr(self, 'current_scenario_id', -1), getattr(self, 'bve_list_id', ""), station_list), ideal_loc)
    if planned is None:
        return result._replace(accepted=False, reason=refusal)

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

    self.score = cp["score"]

    if "score_details" in cp:
        self.score_details = cp["score_details"].copy()
    else:
        # 万が一古いセーブデータだった場合の保険
        for k in self.score_details: self.score_details[k] = 0

    # ATS信号無視が無効な間は、復元した内訳でも0を維持する
    if not is_ats_signal_ignore_effective(getattr(self, 'pen_ats', False)):
        self.score_details['ats'] = 0

    #?self.bve_door = 0
    #?self.prev_door = 0

    self.rollback_msg = f">>> {cp.get('station_name', '駅')} へロールバック完了 <<<"
    self.rollback_msg_timer = self.bve_time_ms / 1000.0 + 5.0

    self.toggle_menu(is_bve_advancing)

    begin_official_jump(self, ideal_loc, cp['time_ms'])
    pending = station_identity.make_retry_pending(history, index)
    self.retry_pending = pending
    request_id = self.send_jump_command(planned.text)
    # the request was sent: a RequestId (managed mode) or the plain send (normal mode: no id). A managed send the client refused leaves the pending retry 'validated'.
    if pending is not None and (request_id is not None or not managed):
        self.retry_pending = pending._replace(request_id=request_id, state=station_identity.RETRY_SENT)
    self._open_jump_transaction(jump_transaction.JUMP_RETRY, planned, request_id)
    return result._replace(request_id=request_id)

def add_score_popup(
    self,
    points,
    text,
    color,
    ptype,
    category,
    current_time,
    force=False,
):
    if (
        not getattr(self, 'is_scoring_mode', False)
        and not force
    ):
        return

    # 採点終了後は、強制表示を除く新たな加点・減点を受け付けない
    if (
        getattr(self, 'is_scoring_finished', False)
        and not force
    ):
        return

    # ATS信号無視が無効な間は、得点・内訳・ポップアップへ反映しない
    if (
        category == "ATS信号無視"
        and not is_ats_signal_ignore_effective(getattr(self, 'pen_ats', False))
    ):
        return

    self.score += points

    # 得点をカテゴリ別の内訳へ反映する
    cat_map = {
        "運転時分": "time",
        "停止位置": "stop",
        "基本制動": "base_brake",
        "ボーナス": "bonus",
        "転動": "roll",
        "停車時衝動": "jerk",
        "初動ブレーキ": "init_brake",
        "緩和ブレーキ": "rel_brake",
        "非常ブレーキ": "eb",
        "速度制限超過": "limit",
        "ATS信号無視": "ats",
    }

    if category in cat_map:
        key = cat_map[category]
        self.score_details[key] += points

    self.popups.append({
        "text": text,
        "color": color,
        "expire_time": current_time + 5.0,
        "type": ptype,
        "category": category,
    })

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
    x_cm = int(round(abs(d_m_rounded) * 100))
    if x_cm <= 100:
        add = 5 * (100 - x_cm)
        if add > 0:
            add_score_popup(self, add, f"停止位置 +{add}", COLOR_N, "pos", "停止位置", current_time)
        if x_cm < 1: return True
    return False

def note_save_skipped(self, snapshot):
    """Phase ST-2a: the checkpoint of this arrival was NOT created because the identity of the station is not verified. The scoring goes on, the checkpoints that
    exist stay as they are. One diagnostic line per change of (reason, candidate index): a refusal that repeats says nothing new."""
    key = (snapshot.reason, snapshot.station_index)
    if getattr(self, '_save_skip_key', None) == key:
        return
    self._save_skip_key = key
    note = getattr(self, '_station_identity_note', None)
    if note is None:
        return
    scope = snapshot.scope
    fields = {"why": snapshot.reason, "idx": snapshot.station_index, "role": snapshot.role, "loc": "none" if snapshot.station_location is None else "%.2f" % snapshot.station_location,
              "tgt": getattr(self, 'bve_tgt_idx', -1)}                    # the target index is recorded for diagnosis only; it is never a condition of the checkpoint
    if scope is not None:
        fields.update({"scn": scope.scenario_id, "list": scope.list_id, "cnt": scope.count})
    try:
        note("stidx-save-skip", **fields)
    except Exception:
        pass


def create_save_data(self, arrival_loc=None):
    if not getattr(self, 'is_scoring_mode', False) or getattr(self, 'is_scoring_finished', False): return

    # Phase ST-2a: the station of the checkpoint is the VERIFIED arrival index the sender supplied (never a position that is searched in the station list); when it
    # is not verified - or does not correspond to the arrival the application judged (arrival_loc: the position the stop was scored against, NEXTLOC when the caller
    # names none) - no checkpoint is created and none that exists is touched. The sender's TARGET index is not a condition: it may name the next station by now.
    snapshot = station_identity.arrival_snapshot(
        getattr(self, 'current_scenario_id', -1), getattr(self, 'bve_list_id', ""), getattr(self, 'station_list', None),
        getattr(self, 'bve_arr_idx', -1), getattr(self, 'bve_next_loc', None) if arrival_loc is None else arrival_loc)
    if not snapshot.valid:
        note_save_skipped(self, snapshot)
        return

    if not getattr(self, 'save_data', []) or not station_identity.same_station(self.save_data[-1], snapshot):
        stop_error = self.bve_next_loc - self.bve_location

        # 基本は現在の時刻をそのまま保存する
        save_time_ms = self.bve_time_ms

        # 実際の開扉時間を基準停車時間へ加算する
        # 条件1: 始発駅（最初のセーブデータ）ではないこと
        if len(getattr(self, 'save_data', [])) > 0:
            # 条件2: 扉が開く駅であること（通過駅や運転停車は除外）
            if getattr(self, 'bve_is_pass', 0) == 0 and getattr(self, 'bve_doordir', 1) != 0:

                # 現在の駅のダイヤ情報を取得する（チェックポイントと同じStationIndexの駅）
                st = self.station_list[snapshot.station_index]
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

        checkpoint = {
            "loc": self.bve_location,
            "time_ms": save_time_ms,  # 開扉時間を反映した時刻を保存する
            "score": self.score,
            # 後続の得点変更から独立させるため、現在の得点内訳をコピーして保存する
            "score_details": self.score_details.copy(),
            "target_loc": self.bve_next_loc,
            "station_name": getattr(self, 'bve_current_station_name', '不明な駅'),
            "stop_error": stop_error
        }
        checkpoint.update(station_identity.checkpoint_fields(snapshot))
        self.save_data.append(checkpoint)
        self._save_skip_key = None

def close_range_fix_previous_stop(self, arrival_loc):
    """The actual stop position of the stop that was just established, kept for the NEXT target switch. -1.0 when the identity of the arrival is not verified."""
    snapshot = station_identity.arrival_snapshot(
        getattr(self, 'current_scenario_id', -1), getattr(self, 'bve_list_id', ""), getattr(self, 'station_list', None),
        getattr(self, 'bve_arr_idx', -1), arrival_loc)
    self.prev_actual_stop_loc = self.bve_location if snapshot.valid else -1.0


def init_basic_braking_state(self, current_time):
    """The new-section state of the basic braking: counts at zero, the start is the handle of this moment (the zone entry and the close-range departure reset share it)."""
    self.bb_state = "IDLE"
    self.bb_apply_count = 0
    self.bb_release_count = 0
    self.bb_evaluated = False
    self.bb_current_notch = self.bve_brk_notch
    self.bb_prev_stable_notch = self.bve_brk_notch
    self.bb_notch_change_time = current_time
    self.bb_is_stable = True


def close_range_pair_is_close(self, stop_distance):
    """Evaluated ONCE at the target switch: stop -> stop only (neither target is a pass station), with a fixed actual stop position of the previous stop.
    near edge = NEXTLOC + margin1 = bve_next_loc - bve_margin_b (bve_margin_b is abs(margin1)); margin2 (bve_margin_f) is not used. stop_distance is given by the caller."""
    if not getattr(self, 'is_scoring_mode', False):
        return False
    if getattr(self, 'prev_is_pass', 0) != 0 or self.bve_is_pass != 0:
        return False
    anchor = getattr(self, 'prev_actual_stop_loc', -1.0)
    if anchor < 0.0 or self.bve_next_loc < 0.0:
        return False
    return self.bve_next_loc - self.bve_margin_b - anchor <= stop_distance


def update_close_range_departure_reset(self, current_time):
    """The first POSITIVE movement after a close stop -> stop switch: the station evaluation state (early stop) and the basic braking state are reset in the same tick, once."""
    if not getattr(self, 'close_range_departure_reset_pending', False):
        return
    if self.bve_speed > 0.0:
        reset_station_evaluation_state(self)
        init_basic_braking_state(self, current_time)
        self.prev_stop_detection_speed = self.bve_speed      # the crossing of zero on THIS tick is the start of the movement, not a stop


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
            create_save_data(self, p_loc)
            close_range_fix_previous_stop(self, p_loc)

def operational_stop_station(self):
    """Time Fix B2: (station index, scheduled departure ms) of the operational stop that is arrived at. The index is the sender's arrival index VERIFIED against the adopted station list and the position the
    stop was judged against (station_identity.arrival_snapshot: the identity the checkpoint of this arrival uses; nothing is searched by a position); the time is the departure time of that entry of the
    list (the NEXTTIME the sender shows once the stop is made when the list has none). (-1, -1) when the identity is not verified: the latch then names no station and the departure keeps the range rule of Time Fix B."""
    snapshot = station_identity.arrival_snapshot(
        getattr(self, 'current_scenario_id', -1), getattr(self, 'bve_list_id', ""), getattr(self, 'station_list', None),
        getattr(self, 'bve_arr_idx', -1), getattr(self, 'bve_next_loc', None))
    if not snapshot.valid:
        return -1, -1
    scheduled_ms = self.station_list[snapshot.station_index].get("raw_dep", -1)
    if scheduled_ms <= 0:
        scheduled_ms = getattr(self, 'bve_next_time', -1)
    return snapshot.station_index, scheduled_ms


def resolve_operational_stop_completion(latch, now_ms):
    """Time Fix B2: how a LATCHED operational stop is completed on the Tick on which the sender switches the target to the next station.

    latch   (station index, time of the stop, scheduled departure time) in ms of the BVE clock, written when the stop was made inside the author-defined range
    now_ms  the time of the Tick of the switch
    The stop is NOT judged again (the vehicle may have crept away while it waited); the cause is read from the record alone, in this order:
      late-arrival            the stop was made after the scheduled departure: the time of the stop is the actual time
      scheduled-time-reached  the Tick is at or after the scheduled departure (a movement on that Tick has no priority over it): error 0
      early-movement          otherwise the vehicle left before the scheduled departure: the time of the Tick is the actual time
    Returns None when there is no usable scheduled departure time (nothing is scored), else a dict with reason, station_index, scheduled_ms, actual_ms, signed_error_ms (actual - scheduled),
    absolute_error_ms and diff_s: the error in whole seconds as apply_time_score reads it (each time floored to the second, as everywhere in this module; 0 for scheduled-time-reached)."""
    station_index, stopped_ms, scheduled_ms = latch
    if scheduled_ms <= 0:
        return None
    if stopped_ms > scheduled_ms:
        reason, actual_ms = "late-arrival", stopped_ms
    elif now_ms >= scheduled_ms:
        reason, actual_ms = "scheduled-time-reached", scheduled_ms
    else:
        reason, actual_ms = "early-movement", now_ms
    signed_error_ms = actual_ms - scheduled_ms
    return {
        "reason": reason,
        "station_index": station_index,
        "scheduled_ms": scheduled_ms,
        "actual_ms": actual_ms,
        "signed_error_ms": signed_error_ms,
        "absolute_error_ms": abs(signed_error_ms),
        "diff_s": 0 if reason == "scheduled-time-reached" else scheduled_ms // 1000 - actual_ms // 1000,
    }


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
    # Time Fix B3: 公式ジャンプの完了待ちの間に起きた運転停車の発車(targetの切替)は、ジャンプが置き換える前の世界の出来事なので運転時分を採点しない
    is_stale_operational_stop = getattr(self, 'prev_doordir', 1) == 0 and getattr(self, 'is_official_jumping', False)
    if not getattr(self, 'ignore_next_pass_score', False) and allow_score and not getattr(self, 'is_first_station', False):
        if getattr(self, 'prev_is_pass', 0) == 1 and is_timing_active:
            if not getattr(self, 'has_scored_time_this_station', False):
                apply_time_score(self, getattr(self, 'prev_diff_s', 0), current_time)
                self.has_scored_time_this_station = True
                self.is_official_retry = False
        elif getattr(self, 'prev_is_pass', 0) == 0 and is_timing_active and not is_stale_operational_stop:
            if not getattr(self, 'has_scored_time_this_station', False):
                d = p_loc - self.bve_location

                # 判定に使う停止位置許容幅。この時点のbve_margin_*はtgt切替後の次駅のものなので、運転停車では到着時に保持した到着駅の許容幅を使う
                margin_f = self.bve_margin_f
                margin_b = self.bve_margin_b
                if getattr(self, 'prev_doordir', 1) == 0:
                    kept_margins = getattr(self, 'operational_stop_margins', None)
                    if kept_margins is not None:
                        margin_f, margin_b = kept_margins

                # Time Fix B2: 運転停車は到着時に作者定義の許容範囲内で一度停止成立を判定済み(latch)。発車時は位置を再判定せず、senderがtargetを切り替えたTickの時刻で確定する
                op_latch = getattr(self, 'operational_stop_latch', None) if getattr(self, 'prev_doordir', 1) == 0 else None
                if op_latch is not None and op_latch[0] == p_idx:
                    completion = resolve_operational_stop_completion(op_latch, self.bve_time_ms)
                    if completion is not None:
                        apply_time_score(self, completion["diff_s"], current_time)
                    self.has_scored_time_this_station = True
                    self.is_official_retry = False
                # 過去にちゃんと許容範囲で止まっており、かつ、出発時刻の今この瞬間も許容範囲内にいること
                elif (getattr(self, 'has_scored_stop_this_station', False) or getattr(self, 'is_official_retry', False)) and (-margin_f <= d <= margin_b):
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

def update_basic_braking_first_stop(self):
    """
    通常停車駅で許容停止位置内に初めて停止した時点で、基本制動の観測を打ち切る。

    初回有効停止より前のapply・release・込め直し・手動EBは従来どおり観測する。
    初回有効停止の後は、速度0.0km/hのままのブレーキ操作（EB、増圧、緩解）を
    基本制動へ影響させない。扉開前に速度が0.0以外になった場合は、実際の再移動として
    基本制動を不可逆にFAILEDへ遷移させる。元の位置へ戻っても資格は戻さない。

    運転停車は最初の停止で評価が確定するため対象外とする。
    既存の範囲外停止判定（is_stopped_out_of_range）や転動判定とは独立している。
    停止位置の加点は従来どおり扉開時の最終停止位置で計算される。
    """
    if getattr(self, 'bb_evaluated', False):
        return

    if getattr(self, 'bb_first_valid_stop_detected', False):
        if self.bve_speed != 0.0:
            self.bb_moved_after_first_valid_stop = True
        if getattr(self, 'bb_moved_after_first_valid_stop', False):
            self.bb_state = "FAILED"
        return

    if not getattr(self, 'bb_is_in_zone', False) or self.bve_speed != 0.0:
        return
    if getattr(self, 'is_official_jumping', False) or getattr(self, 'jump_lock', False):
        return
    if getattr(self, 'is_stopped_out_of_range', False):
        return
    if self.bve_is_pass != 0 or getattr(self, 'bve_doordir', 1) == 0:
        return

    dist_to_stop = self.bve_next_loc - self.bve_location
    if not (-self.bve_margin_f <= dist_to_stop <= self.bve_margin_b):
        return

    # 初回有効停止: 保留中のノッチ変化を確定し、基本制動の結果を仮確定する
    if not getattr(self, 'bb_is_stable', True):
        self.bb_is_stable = True
        process_bb_transition(self, self.bb_current_notch)

    self.bb_first_valid_stop_detected = True
    self.bb_moved_after_first_valid_stop = False

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
        if is_ats_signal_ignore_effective(getattr(self, 'pen_ats', False)): f_list.append("[ATS]")
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

    is_eb_handle, manual_eb_qualified = (
        update_manual_emergency_brake_state(self, dt)
    )

    update_manual_emergency_brake_penalty(
        self,
        current_time,
        manual_eb_qualified,
        in_station_zone,
    )

    update_smee_virtual_emergency_brake(
        self,
        current_time,
        in_station_zone,
    )

    update_initial_and_release_brake_penalty(
        self,
        current_time,
        decel_g,
        in_station_zone,
        is_eb_handle,
    )

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

    update_close_range_departure_reset(self, current_time)

    if getattr(self, 'bb_is_in_zone', False) and self.bve_speed < 0:
        self.bb_state = "FAILED"

    if in_station_zone and not getattr(self, 'close_range_departure_reset_pending', False) and not self.bb_is_in_zone:
        init_basic_braking_state(self, current_time)
        self.bb_is_in_zone = True

    elif not in_station_zone and self.bb_is_in_zone:
        self.bb_is_in_zone = False

    update_basic_braking_first_stop(self)

    if (
        self.bb_is_in_zone
        and self.bve_speed > 0.0
        and not self.bb_evaluated
        and not getattr(self, 'bb_first_valid_stop_detected', False)
    ):
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
        # Phase ST-2c: where the train is on the first line decides nothing (it used to clear is_first_station when NEXTLOC was more than 100 m away, which is the case while the
        # jump to the start station has not moved the train yet). The latch is set by the scoring start / the retry to the first checkpoint, whose station identity was verified,
        # and is reset only by the departure and the change of NEXTLOC below (and by a retry to a later checkpoint).
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

        close_range_stop_distance = getattr(self, 'setting_stop_distance', -1) if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        close_pair = is_forward_transition and not getattr(self, 'is_official_jumping', False) and close_range_pair_is_close(self, close_range_stop_distance)

        self.ignore_next_pass_score = False
        self.is_first_station = False

        reset_station_evaluation_state(self)
        reset_station_evaluation_state(self)

        self.bb_evaluated = False
        self.bb_is_in_zone = False
        self.close_range_departure_reset_pending = close_pair
        update_close_range_departure_reset(self, current_time)       # a positive speed on the switch tick (operational stop) is the departure itself

    if not getattr(self, 'is_approaching', False) and self.bve_next_loc >= 0:
        actual_margin = getattr(self, 'setting_stop_distance', -1) if getattr(self, 'setting_stop_distance', -1) != -1 else (self.bve_train_length + STATION_MARGIN)
        if abs(self.bve_next_loc - self.bve_location) < actual_margin:
            self.is_approaching = True

    prev_stop_speed = getattr(
        self,
        'prev_stop_detection_speed',
        self.bve_speed,
    )

    is_exact_stop = self.bve_speed == 0.0

    crossed_zero = (
        prev_stop_speed != 0.0
        and self.bve_speed != 0.0
        and (prev_stop_speed > 0.0)
        != (self.bve_speed > 0.0)
    )

    stop_detected = is_exact_stop or crossed_zero

    if (
        getattr(self, 'is_approaching', False)
        and stop_detected
        and not getattr(self, 'close_range_departure_reset_pending', False)
        and not getattr(
            self,
            'has_scored_stop_this_station',
            False,
        )
    ):
        d = self.bve_next_loc - self.bve_location

        if not (
            -self.bve_margin_f
            <= d
            <= self.bve_margin_b
        ):
            self.is_stopped_out_of_range = True

    self.prev_stop_detection_speed = self.bve_speed

    # Time Fix B3: 公式ジャンプの完了待ちの間のテレメトリは、ジャンプが置き換える前の世界(旧位置・旧時刻)を表す。運転停車の停止成立・latchは作らない(着地後の最初の停止から作り直す)
    if is_operational_stop and getattr(self, 'is_approaching', False) and self.bve_speed == 0.0 and not getattr(self, 'has_scored_stop_this_station', False) and not getattr(self, 'is_official_jumping', False) and not getattr(self, 'close_range_departure_reset_pending', False):
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

            # Time Fix B3: 採点終了駅の運転停車は、この到着で採点が終了する(発車は評価しない)ので、停止成立の記録は残さない
            if not getattr(self, 'is_scoring_finished', False):
                # 運転停車の到着が成立した時点で、到着した駅の停止位置許容幅を保持する（発車時のtgt切替後に次駅の許容幅を使わないため）
                self.operational_stop_margins = (self.bve_margin_f, self.bve_margin_b)
                # Time Fix B2: 停止成立時刻と予定発車時刻も保持する(発車時は許容範囲を再判定せず、この記録で運転時分を確定する)
                latch_index, latch_scheduled_ms = operational_stop_station(self)
                self.operational_stop_latch = (latch_index, self.bve_time_ms, latch_scheduled_ms)
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

    # Time Fix B3: 走行中(速度が0.0以外。正負を問わない)だけ制限速度の案内を点滅表示する。停止中(0.0)は通常表示
    if self.bve_speed != 0.0:
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