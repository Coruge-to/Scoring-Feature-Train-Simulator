"""Phase SI-A - the input and scoring side of the MANAGED application: the same scoring and key handling that the manual mode (python main.py) has always had,
run from the Caller's Session / Driving state.

What this module is
  * the STATE CONTRACT in code: which parts of the Overlay belong to a scenario generation / a scoring session (discarded) and which are the user's settings,
    the window state or infrastructure (kept) - see GENERATION_DEFAULTS / GENERATION_DROP / KEPT_ACROSS_GENERATIONS;
  * the discard functions: discard_scoring_session (loss of the state block, Stop) and discard_generation_state (Session OFF, a new scenario instance).
    Driving OFF alone (a Pause) discards nothing (Phase SI-A4, ManagedInputController.on_pause);
  * ManagedInputController: the policy that connects the shared step of the Overlay (Overlay._run_input_and_scoring_step, the former update_logic) to
    ManagedHudController: when it runs, what is released when it must stop, the scoring-start gate, the diagnostic events.

The six states are kept apart:
    Python running      the process (Caller / managed_mode own it; nothing here ends it)
    Session active      ScenarioReady (state block)                      -> ManagedHudController.gate
    Driving active      DrivingActive (state block)                      -> ManagedHudController.gate
    Scoring active      the USER's start (menu) and nothing else: is_scoring_mode and not is_scoring_finished
    HUD active          ManagedHudController._shown
    Input suppression   the key hooks and the lock of the "time and position" window: ONLY while Session + Driving are active, telemetry of the current
                        generation has been received AND the user's scoring / menu asks for it; released in the same tick otherwise.

The pure parts (tables, discard functions, the gate) need no Qt, no window and no keyboard; the keyboard and the window API are injected.
"""

# -- the state contract ------------------------------------------------------------------------------------------------------------------------
# Every plain attribute the Overlay has (its __init__, the attributes it sets later, the ones scoring_logic sets on it) is in exactly ONE of these sets:
# GENERATION_DEFAULTS / GENERATION_DROP (discarded with a scenario generation), KEPT_ACROSS_GENERATIONS (user settings, window state, infrastructure,
# input-hold bookkeeping) or the keys of telemetry_contract.telemetry_state_defaults() (the latest telemetry values; reset by Overlay.reset_telemetry_state).
# tests/test_managed_input_sia3.py proves the classification is complete, so a new attribute forces a decision here.


def _default_brake_rules():
    return [{"end_idx": -1, "apply": "階段", "release": "階段"}]


def _default_penalty_init_rules():
    return [{"end_idx": -1, "apply": "ON①", "release": "ON①"}]


def generation_defaults():
    """name -> value for every attribute that belongs to ONE scenario generation / scoring session (fresh containers on every call)."""
    from config import COLOR_WHITE
    return {
        # the scoring session and its result
        "popups": [], "score": 0, "score_details": {key: 0 for key in ("time", "stop", "base_brake", "roll", "jerk", "init_brake", "rel_brake", "eb", "limit", "ats", "bonus")},
        "is_scoring_mode": False, "is_scoring_finished": False, "is_result_saved": False, "saved_file_path": "",
        "end_message_time": 0.0, "result_screen_time": 0.0, "theoretical_score": 0, "total_retry_count": 0, "save_data": [],
        "rollback_msg": "", "rollback_msg_timer": 0.0,
        "is_speed_limit_exceeded": False, "last_speed_limit_penalty_time": 0.0, "accumulated_speed_penalty": 0,
        # emergency brake (manual EB and Smee virtual EB)
        "manual_eb_penalty_applied": False, "smee_virtual_eb_active": False, "manual_eb_accum_time": 0.0, "manual_eb_cooling_time": 0.0,
        # basic braking
        "bb_state": "IDLE", "bb_apply_count": 0, "bb_release_count": 0, "bb_is_in_zone": False, "bb_evaluated": False, "bb_current_notch": 0,
        "bb_notch_change_time": 0.0, "bb_prev_stable_notch": 0, "bb_is_stable": True,
        # initial / relaxation brake
        "hb_prev_notch": 0, "hb_cushion_entry_time": 0.0, "hb_cushion_max_g": 0.0, "hb_strong_entered": False,
        # roll
        "door_open_loc": 0.0, "roll_penalty_count": 0, "roll_was_moving": False,
        # position / time changes
        "bve_jump_count": 0, "last_jump_count": 0, "jump_lock": False, "ignore_next_pass_score": False, "is_official_jumping": False,
        "is_official_retry": False, "expected_target_loc": -1.0, "expected_target_time": -1, "pending_jump_complete": None,
        # the menu
        "menu_state": 0, "menu_cursor": 0, "menu_scroll": 0, "target_retry_idx": -1, "menu_cursor_x": -1, "dropdown_active": False, "dropdown_cursor": 0,
        "dropdown_scroll": 0, "dropdown_options": [], "dropdown_target": "", "dropdown_target_rule_idx": -1, "summary_scroll": 0, "sub_cursor": 0,
        "sub_cursor_x": 0, "sub_scroll": 0, "input_buffer": "", "input_mode_active": False, "input_fresh": True, "init_summary_scroll": 0,
        "init_sub_scroll": 0, "init_sub_cursor": 0, "init_sub_cursor_x": 0, "show_help": False, "timing_cursor": 0, "timing_scroll": 0,
        # the stations / sections chosen for the scoring (indexes into the station list of that scenario)
        "setting_start_idx": 0, "setting_end_idx": -1, "setting_stop_distance": -1, "setting_initial_brake": "NONE",
        "brake_rules": _default_brake_rules(), "penalty_init_rules": _default_penalty_init_rules(), "user_timing_overrides": {},
        # the station list and the scenario information of that scenario, the scoring clock and the previous-frame values
        "station_list": [], "pending_station_list": None, "last_update_time": 0.0, "prev_frame_loc": 0.0, "g_history": [], "last_bve_time_ms": 0,
        "meta_title": "", "meta_route": "", "meta_vehicle": "", "meta_author": "", "meta_comment": "",
        "prev_base_limit": 1000.0, "prev_diff_s": 0, "prev_door": 0, "prev_doordir": 1, "prev_is_pass": 0, "prev_is_timing": 0, "prev_next_loc": -1.0,
        "prev_term": 0,
        # the evaluation of the current station
        "is_first_udp": True, "is_first_station": True, "is_approaching": False, "is_stopped_out_of_range": False, "has_scored_time_this_station": False,
        "has_scored_stop_this_station": False, "has_departed": False, "is_stopping_zone": False, "max_stop_g": 0.0, "last_stop_g": 0.0,
        "stop_notch_state": "IDLE",
        # the speed limit guidance (blink / candidates of the previous scenario)
        "disp_limit": 1000.0, "limit_color": COLOR_WHITE, "effective_limit": 1000.0, "current_base_limit": 1000.0, "limit_changed_loc": -1.0,
        "base_limit_type": "map", "target_type": "map", "blink_phase": 0.0, "blink_active": False, "dbg_is_wait": False, "dbg_target_cap": 1000.0,
        "dbg_red": "None", "dbg_blue": "None",
        # fast-forward detection
        "ff_check_real_time": 0.0, "ff_check_bve_time": 0, "is_fast_forwarding": False,
        # the BVE time / position reference of the sender is the sender's, the bp_initial of the vehicle is received again for every generation
        "bve_bp_initial_received": False,
        # the kick start (P to P) and the BVE status of the previous scenario
        "is_bve_loaded": False, "initial_kickstart_done": False, "auto_pause_pending": False, "bve_actual_state": "",
    }


# attributes that scoring_logic / the Overlay create later with getattr defaults: removing them returns them to "never set"
GENERATION_DROP = frozenset({
    "kick_bve_time", "was_advancing_before_menu", "current_menu_items", "limit_flash_counts", "strictest_flashed_key", "strictest_flashed_val",
    "current_flashing_key", "active_features_str", "active_next_sta_name", "active_next_sta_timing", "active_rule_basic_apply",
    "active_rule_basic_release", "active_rule_init_apply", "active_rule_init_release", "bb_first_valid_stop_detected",
    "bb_moved_after_first_valid_stop", "has_evaluated_initial_brake", "idle_entered_while_stopped", "prev_stop_detection_speed", "dbg_active_reds",
    "last_debug_state_key", "last_pending_log", "bve_door_close_time_ms", "is_base_off", "is_time_off",
})

# the user's settings, the window state, the infrastructure and the input-hold bookkeeping: deliberately NOT discarded with a generation
KEPT_ACROSS_GENERATIONS = frozenset({
    # user settings (HUD items, scoring switches, evaluation ranks, the debug switches)
    "disp_settings", "settings_keys", "settings_names", "pen_eb", "pen_jerk", "pen_limit", "pen_ats", "rank_a_ratio", "rank_multi", "F8_disable",
    "enable_limit_debug_log", "debug_all_penalties", "show_graph", "menu_items_off", "menu_items_on",
    # window state of the BVE window (validated against the window handle before it is used again) and the link
    "is_borderless_fullscreen", "bve_original_placement", "bve_original_style", "bve_hwnd", "was_bve_found", "is_linked",
    # input hold bookkeeping (released by ManagedInputController / the Overlay's own tick, never "reset" blindly)
    "keys_blocked", "hook_dict", "sys_keys_blocked", "sys_hook_dict", "f8_physically_blocked", "f8_hook_dict", "numeric_router", "numeric_router_hook",
    "key_states", "key_press_timers", "last_left_click", "menu_click_zones", "active_panel_rect", "active_dropdown_rect", "active_help_rect",
    "is_capturing_screenshot",
    # infrastructure
    "timer", "udp_socket", "udp_bind_ok", "telemetry_gate", "font_normal", "font_big", "font_ui", "font_menu", "font_desc", "last_time_change_real",
    # identity / monotonic counters (the SCENARIO_ID branch and the roll popups use them across scenarios)
    "current_scenario_id", "needs_margin_recalc", "roll_event_id",
    # the generation machinery itself
    "held_station_list", "jump_baseline_pending",
})


def discard_scoring_session(overlay):
    """The scoring SESSION is over (soft OFF, Session OFF, a generation boundary): scoring inactive, its state discarded. Nothing of the scenario
    itself (station list, the chosen stations and rules, the latest telemetry values, the user's settings) is touched, so the user can start again.
    The menu is closed WITHOUT pressing anything in BVE."""
    from scoring_logic import reset_result_display_state, reset_roll_state, reset_speed_penalty_state, reset_station_evaluation_state
    d = generation_defaults()
    for name in (
        "popups", "score", "score_details", "is_scoring_mode", "is_scoring_finished", "is_result_saved", "saved_file_path", "end_message_time", "result_screen_time",
        "theoretical_score", "total_retry_count", "save_data", "rollback_msg", "rollback_msg_timer",
        "manual_eb_penalty_applied", "smee_virtual_eb_active", "manual_eb_accum_time", "manual_eb_cooling_time",
        "bb_state", "bb_apply_count", "bb_release_count", "bb_is_in_zone", "bb_evaluated", "bb_current_notch", "bb_notch_change_time",
        "bb_prev_stable_notch", "bb_is_stable", "hb_prev_notch", "hb_cushion_entry_time", "hb_cushion_max_g", "hb_strong_entered",
        "jump_lock", "ignore_next_pass_score", "is_official_jumping", "is_official_retry", "expected_target_loc", "expected_target_time",
        "pending_jump_complete", "menu_state", "menu_cursor", "menu_scroll", "target_retry_idx", "menu_cursor_x", "dropdown_active", "dropdown_cursor",
        "dropdown_scroll", "dropdown_options", "dropdown_target", "dropdown_target_rule_idx", "summary_scroll", "sub_cursor", "sub_cursor_x", "sub_scroll",
        "input_buffer", "input_mode_active", "input_fresh", "show_help", "last_update_time", "g_history", "blink_phase", "blink_active",
        "is_first_udp", "is_first_station", "has_departed", "ff_check_real_time", "ff_check_bve_time", "is_fast_forwarding",
    ):
        setattr(overlay, name, d[name])
    reset_result_display_state(overlay)
    reset_speed_penalty_state(overlay)
    reset_roll_state(overlay)
    reset_station_evaluation_state(overlay)
    for name in ("current_menu_items", "was_advancing_before_menu", "limit_flash_counts", "strictest_flashed_key", "strictest_flashed_val", "current_flashing_key",
                 "active_features_str", "bb_first_valid_stop_detected", "bb_moved_after_first_valid_stop", "has_evaluated_initial_brake",
                 "idle_entered_while_stopped", "prev_stop_detection_speed"):
        overlay.__dict__.pop(name, None)


def discard_generation_state(overlay):
    """A NEW scenario instance (ScenarioGeneration): everything that belongs to the previous scenario is discarded - the scoring session, the 42 variables
    of decision D-3 (tests/test_scoring_observation_si0.py D3_VARIABLES), the station list and the references into it, the guidance state, the
    kick start state - and the reference of the sender's JUMP counter is taken again from the FIRST accepted telemetry of the generation. The user's
    settings, the infrastructure and the window state are kept. The latest telemetry VALUES are reset by Overlay.reset_telemetry_state."""
    for name, value in generation_defaults().items():
        setattr(overlay, name, value)
    for name in GENERATION_DROP:
        overlay.__dict__.pop(name, None)
    overlay.jump_baseline_pending = True


# -- what a scoring run needs from the telemetry ----------------------------------------------------------------------------------------------------
# A scoring run is only started when the data its rules read are really there. Without an AVAIL part (the Current sender) every group is available and
# nothing changes; with an explicit AVAIL (a sender that can lack groups) a missing group refuses the start instead of letting the scoring run on construction
# defaults (brake notch 0, brake type Ecb, brake pipe 0 kPa, ...). The scoring rules themselves are NOT changed.
SCORING_REQUIRED_TOKENS = ("time", "speed", "loc", "station", "door", "handle", "brake_type", "brake_cab", "prates", "jump")


def scoring_input_blockers(availability, btype, bp_initial_received):
    """Fixed words (in this order) for every input a scoring run would silently replace by a default. Empty = nothing is missing."""
    blockers = []
    for token in SCORING_REQUIRED_TOKENS:
        if not availability.has(token):
            blockers.append("missing-" + token.replace("_", "-"))
    if btype == "Smee":
        if not availability.has("bpp"):
            blockers.append("missing-bpp")
        if not bp_initial_received:
            blockers.append("bp-initial-not-received")
    return blockers


def refusal_popup(overlay, text):
    """The one warning shown when the user's scoring start is refused (the HUD's warning popup; forced so that it shows without a scoring run)."""
    from config import COLOR_B_EMG
    from scoring_logic import add_score_popup
    add_score_popup(overlay, 0, text, COLOR_B_EMG, "big", "警告", overlay.bve_time_ms / 1000.0, force=True)


class GuiInputApi(object):
    """The two window operations of the input hold ("time and position" window). `gui` is the win32gui module (or a fake with the same functions)."""
    DIAG_TITLE = "時刻と位置"

    def __init__(self, gui):
        self._gui = gui

    def find_diag_window(self):
        return self._gui.FindWindow(None, self.DIAG_TITLE)

    def is_enabled(self, hwnd):
        return bool(self._gui.IsWindowEnabled(hwnd))

    def enable(self, hwnd):
        self._gui.EnableWindow(hwnd, True)


def attach_result_dialog(overlay):
    """Managed mode: the result save dialog is a Qt dialog INSTANCE, not the native static dialog, so that the Stop request (or the loss of the parent
    process) can close it (Overlay.close_result_dialog -> reject) and its nested event loop returns before the application quits. The caller of the dialog
    (Overlay.take_result_screenshot) is unchanged."""
    def ask(default_path):
        from PyQt6.QtWidgets import QFileDialog
        dialog = QFileDialog(overlay, "採点結果を保存", default_path, "JPEG Image (*.jpg);;PNG Image (*.png)")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        overlay.result_dialog = dialog
        try:
            accepted = dialog.exec()
        finally:
            overlay.result_dialog = None
        if accepted:
            files = dialog.selectedFiles()
            return files[0] if files else ""
        return ""

    overlay.ask_result_save_path = ask
    return ask


def release_hooks(overlay, keyboard_api):
    """Unhooks every key hook the Overlay holds and clears the flags; returns the names of the groups that were held (empty = nothing was)."""
    held = []
    for name, flag, label in (("sys_hook_dict", "sys_keys_blocked", "sys"), ("f8_hook_dict", "f8_physically_blocked", "f8"), ("hook_dict", "keys_blocked", "menu")):
        hooks = getattr(overlay, name, None)
        was_held = bool(hooks) or bool(getattr(overlay, flag, False))
        if hooks:
            for hook in list(hooks.values()):
                if hook:
                    try:
                        keyboard_api.unhook(hook)
                    except Exception:
                        pass
            hooks.clear()
        if was_held:
            held.append(label)
        if hasattr(overlay, flag) or was_held:
            setattr(overlay, flag, False)
    router_hook = getattr(overlay, "numeric_router_hook", None)
    if router_hook is not None:
        try:
            keyboard_api.unhook(router_hook)
        except Exception:
            pass
        overlay.numeric_router_hook = None
        held.append("router")
    router = getattr(overlay, "numeric_router", None)
    if router is not None:
        router.reset()
    return held


def hold_kinds(overlay):
    """The input hold that exists NOW, as a sorted tuple of fixed words ('sys', 'f8', 'menu', 'router'); empty = nothing is suppressed."""
    kinds = []
    if getattr(overlay, "sys_keys_blocked", False):
        kinds.append("sys")
    if getattr(overlay, "f8_physically_blocked", False):
        kinds.append("f8")
    if getattr(overlay, "keys_blocked", False):
        kinds.append("menu")
    if getattr(overlay, "numeric_router_hook", None) is not None:
        kinds.append("router")
    return tuple(sorted(kinds))


def window_lock_wanted(overlay):
    """The Overlay locks the "time and position" window while a menu is open or a scoring run is on (the same rule as Overlay._sync_time_position_window_lock)."""
    return (getattr(overlay, "menu_state", 0) != 0) or (getattr(overlay, "is_scoring_mode", False) and not getattr(overlay, "is_scoring_finished", False))


class ManagedInputController(object):
    """Connects the shared step of the Overlay to ManagedHudController.

    hud       needs input_allowed, linked_hwnd, telemetry_ready, telemetry_availability, emit_event(event, **fields)
    keyboard  the keyboard module (unhook) - injected, never imported here
    gui_api   GuiInputApi (or a fake)
    """

    def __init__(self, overlay, hud, keyboard_api, gui_api, popup=None):
        self._o = overlay
        self._hud = hud
        self._kb = keyboard_api
        self._gui = gui_api
        self._popup = popup if popup is not None else refusal_popup
        self._generation = None
        self._scoring = False
        self._finished = False
        self._hold = ()
        self._lock_wanted_last = False
        self._lines = {}
        self._total = 0
        self.steps = 0
        self.releases = 0
        self.refusals = 0
        self.aborts = 0
        self.suppressed = 0
        self.pauses = 0
        self._resync = False                # Phase SI-A4: the next step follows a pause (Driving OFF with the Session ON)
        overlay.scoring_start_gate = self.start_gate
        overlay.input_event_sink = self.note
        overlay.is_managed_input = True

    # -- diagnostics ----------------------------------------------------------------------------------------------------------------------
    # The Caller copies at most 200 `[MANAGED]` lines of one Python process into its log (and 160 characters of each): this controller keeps to a part of that
    # budget (a cap per event name and a total); what does not fit is only counted (input-summary).
    EVENT_LINE_CAP = 10
    EVENT_LINE_CAPS = {"input-hold": 24, "input-pause": 6, "input-resume": 6}              # (a menu opened and closed again is two lines)
    TOTAL_LINE_BUDGET = 70

    def cap_for(self, event):
        return self.EVENT_LINE_CAPS.get(event, self.EVENT_LINE_CAP)

    def note(self, event, **fields):
        """One `[MANAGED] event=...` line (fixed words and numbers only: no station name, no path), within the line budget."""
        count = self._lines.get(event, 0)
        if count >= self.cap_for(event) or self._total >= self.TOTAL_LINE_BUDGET:
            self.suppressed += 1
            return
        self._lines[event] = count + 1
        self._total += 1
        try:
            self._hud.emit_event(event, **fields)
        except Exception:
            pass

    # -- the step -------------------------------------------------------------------------------------------------------------------------
    def step(self, overlay):
        """ManagedHudController's update step (Session ON, Driving ON, telemetry of the generation received)."""
        if self._resync:
            self._resync = False
            self._resync_clock()
        hwnd = self._hud.linked_hwnd
        if hwnd is None:
            self.release("no-window")
            from managed_hud import hud_update_step
            hud_update_step(overlay)
            return
        if getattr(overlay, "is_capturing_screenshot", False):
            return                                  # the result-save dialog runs its own event loop inside a step: no second step inside it
        self.steps += 1
        overlay.managed_window_step(hwnd)
        self._observe()

    def tick_waiting(self):
        """Session ON, Driving ON but no telemetry of this generation yet: nothing is suppressed, nothing is pressed. (Phase SI-A6: the kick start (P to P) is
        not done here - this state is also what an ordinary scenario load looks like for a moment; P is pressed only for a recovery token, see pause_recovery.)"""
        self.release("telemetry-wait")

    # -- the scoring start gate ------------------------------------------------------------------------------------------------------------
    def start_blockers(self):
        o = self._o
        blockers = []
        if not self._hud.input_allowed:
            blockers.append("not-active")
        if not self._hud.telemetry_ready:
            blockers.append("telemetry-not-ready")
        if not getattr(o, "station_list", None):
            blockers.append("no-station-list")
        blockers += scoring_input_blockers(self._hud.telemetry_availability, getattr(o, "bve_btype", "Ecb"), getattr(o, "bve_bp_initial_received", False))
        return blockers

    def start_gate(self):
        """Overlay.scoring_start_gate: True = the user's start may proceed; False = refused (one warning on the HUD, one line in the log)."""
        blockers = self.start_blockers()
        if not blockers:
            return True
        self.refusals += 1
        self.note("scoring-start-refused", reason=blockers[0], blockers=len(blockers), n=self.refusals)
        if self._popup is not None:
            try:
                self._popup(self._o, "採点を開始できません（入力が揃っていません）")
            except Exception:
                pass
        return False

    # -- state changes ---------------------------------------------------------------------------------------------------------------------
    def on_generation(self, generation):
        """A new ScenarioGeneration: scoring inactive, the previous scenario's state discarded, the input released."""
        if self._generation is not None and self._scoring:
            self.note("scoring-abort", reason="generation")
        self._o.reset_generation_state()
        self.release("generation")
        self._resync = False
        self._generation = generation
        self._scoring = False
        self._finished = False

    def on_pause(self, reason="driving-off"):
        """Phase SI-A4: Driving left ACTIVE while the Session stays ON - a Pause (BVE stops its Ticks, the Caller's tick-stale soft OFF), a scenario selection
        screen, a short stop. The Python side cannot tell these apart, and none of them ends the scoring: the process, the Overlay and the SCORING SESSION stay
        (score, targets, settings, station list, clock reference); only the input is released, at once (hooks off, "time and position" window enabled; an
        open menu is closed without pressing anything in BVE). Scoring is not aborted and nothing is logged as an abort. When Driving is ON again the first
        step takes the scoring clock from the current BVE time, so the time of the pause is never counted as a step (see _resync_clock). What DOES end a
        scoring session is unchanged: Session OFF, a new ScenarioGeneration, the loss of the state block, the end of the process, the user's own abort."""
        self.release(reason)
        self.pauses += 1
        self._resync = True
        self.note("input-pause", scoring="yes" if self._scoring else "no", n=self.pauses)

    def _resync_clock(self):
        """The first step after a pause: dt = 0 for this step (the scoring clock reference becomes the current BVE time) when BVE time moved on while the
        step did not run; the fast-forward measurement starts afresh. A time that went BACK is left to the existing rule of the step (reset of the transient
        scoring state); a scoring clock that was never started (0.0) is left to it, too."""
        o = self._o
        current = o.bve_time_ms / 1000.0
        moved = o.last_update_time != 0.0 and current > o.last_update_time
        if moved:
            o.last_update_time = current
        o.ff_check_real_time = 0.0
        o.is_fast_forwarding = False
        self.note("input-resume", clock="synced" if moved else "kept", n=self.pauses)

    def on_inactive(self, reason):
        """The state left ACTIVE for good: 'session-off' (scenario ended), 'state-lost' (the state block is gone). Scoring inactive, its state discarded,
        the input released at once. The process and the settings stay. (Driving OFF alone is NOT this: see on_pause.)"""
        if self._scoring:
            self.note("scoring-abort", reason=reason)
            self.aborts += 1
        if reason == "session-off":
            self._o.reset_generation_state()
        else:
            discard_scoring_session(self._o)
        self.release(reason)
        self._scoring = False
        self._finished = False
        self._resync = False

    def on_shutdown(self):
        """Stop request / the parent is gone: the result dialog is closed, the scoring state discarded, the input released and the windows restored as far
        as they can be."""
        o = self._o
        try:
            o.close_result_dialog()
        except Exception:
            pass
        discard_scoring_session(o)
        self.release("shutdown")
        try:
            o.restore_bve_window()
        except Exception:
            pass

    # -- the release -----------------------------------------------------------------------------------------------------------------------
    def release(self, reason):
        """Every key hook is removed and the "time and position" window enabled again, in this call. Safe to repeat. Logs one line if something was held."""
        o = self._o
        held = release_hooks(o, self._kb)
        lock_released = False
        if self._lock_wanted_last or window_lock_wanted(o):         # only a window this application locked is unlocked (no window search every tick otherwise)
            try:
                diag = self._gui.find_diag_window()
                if diag and not self._gui.is_enabled(diag):
                    self._gui.enable(diag)
                    lock_released = True
            except Exception:
                pass
        if getattr(o, "menu_state", 0) != 0 and reason not in ("telemetry-wait",):
            o.menu_state = 0
            o.input_mode_active = False
            o.dropdown_active = False
            o.show_help = False
        self._lock_wanted_last = False
        if held or lock_released or self._hold:
            self.releases += 1
            self.note("input-hold", state="release", reason=reason, kinds="+".join(held + (["diag"] if lock_released else [])) or "none")
        self._hold = ()

    # -- observation (state changes only) ---------------------------------------------------------------------------------------------------
    def _observe(self):
        o = self._o
        active = bool(getattr(o, "is_scoring_mode", False)) and not getattr(o, "is_scoring_finished", False)
        finished = bool(getattr(o, "is_scoring_finished", False))
        if active and not self._scoring:
            self.note("scoring-start", gen=self._generation if self._generation is not None else 0)
        elif not active and self._scoring:
            if finished:
                self.note("scoring-finish")
            else:
                self.aborts += 1
                self.note("scoring-abort", reason="jump" if getattr(o, "jump_lock", False) and any(p.get("category") == "警告" for p in getattr(o, "popups", [])) else "user")
        self._scoring = active
        self._finished = finished
        wanted = window_lock_wanted(o)
        self._lock_wanted_last = wanted
        kinds = list(hold_kinds(o))
        if wanted and self._diag_locked():
            kinds.append("diag")                         # the "time and position" window of BVE really is disabled by this application
        hold = tuple(sorted(kinds))
        if hold != self._hold:
            if hold:
                self.note("input-hold", state="set", kinds="+".join(hold))
            elif self._hold:
                self.releases += 1
                self.note("input-hold", state="release", reason="state", kinds="+".join(self._hold))
            self._hold = hold

    def _diag_locked(self):
        try:
            diag = self._gui.find_diag_window()
            return bool(diag) and not self._gui.is_enabled(diag)
        except Exception:
            return False

    def summary_fields(self):
        return dict(in_steps=self.steps, in_releases=self.releases, in_refusals=self.refusals, in_aborts=self.aborts, in_suppressed=self.suppressed)
