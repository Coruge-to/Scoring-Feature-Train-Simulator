"""Phase SI-A3 - the existing scoring and operation features run in the MANAGED application (BVE6 Current), from the Caller's Session / Driving state.

    A  the state contract: every Overlay attribute is classified; what a generation / a scoring session discards; the 42 variables of decision D-3
    B  the scoring input gate (pure)
    C  the six states kept apart: Python running / Session / Driving / Scoring / HUD / input suppression, all combinations
    D  scoring, pause, scenario end, re-selection, reload, soft OFF, soft ON
    E  keys, windows, F11 / F12, the "time and position" window, the fast-forward release in managed mode
    F  P to P in managed mode (per generation, Session / Driving gated)
    G  the station list and the JUMP reference of a generation
    H  the Stop request, the loss of the parent, the fail-safe, the result save dialog
    I  Desktop debug.log (privacy), the static guards (no Legacy branch, nothing of the senders changed)

The real Overlay and the real controllers are used; the keyboard, the windows, the clock and UDP are the recorders of tests/sia_rig.py.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sia_rig as R  # noqa: E402

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

ROOT = R.ROOT
BASELINE = "9f25a26c6bc4a578767c7f306672811bf7bf341c"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def git(*args):
    try:
        out = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, timeout=60)
    except Exception:
        return None
    return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


_APP = []


def qt_app():
    """The QApplication of the process (kept alive here: a QApplication that nobody references is destroyed and the next widget crashes the process)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(["sia3"])
        _APP.append(app)
    return app


# ----------------------------------------------------------------------------------------------------------------------------------------------
def overlay_attribute_names():
    """Every plain attribute the Overlay has: assigned in __init__, in any other Overlay method, or by scoring_logic on the overlay (underscore names exempt)."""
    tree = ast.parse(read("main.py"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
    names = set()
    for m in cls.body:
        if isinstance(m, ast.FunctionDef):
            for n in ast.walk(m):
                if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name) and n.value.id == "self":
                    names.add(n.attr)
    # attributes the VirtualWindow helper class of take_result_screenshot assigns on ITS self are not the Overlay's
    names.discard("_orig")
    for f in ("scoring_logic.py",):
        names |= set(re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\+=|-=)(?!=)", read(f)))
    return {n for n in names if not n.startswith("_")}


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class A_StateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qt_app()
        import main
        import managed_input
        import telemetry_contract
        cls.main, cls.mi, cls.tc = main, managed_input, telemetry_contract

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.o = self.rig.o

    def tearDown(self):
        self.rig.close()

    def test_every_overlay_attribute_is_classified_exactly_once(self):
        mi = self.mi
        sets = {
            "discard": set(mi.generation_defaults()),
            "drop": set(mi.GENERATION_DROP),
            "kept": set(mi.KEPT_ACROSS_GENERATIONS),
            "telemetry": set(self.tc.telemetry_state_defaults()),
        }
        known = set().union(*sets.values())
        missing = sorted(overlay_attribute_names() - known)
        self.assertEqual(missing, [], "unclassified Overlay attributes (decide: discard with the generation, or keep): %s" % missing)
        keys = list(sets)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                self.assertEqual(sorted(sets[a] & sets[b]), [], (a, b))

    def test_the_discard_defaults_are_the_construction_defaults(self):
        fresh = vars(self.o)
        for name, value in self.mi.generation_defaults().items():
            if name in fresh and name != "bve_actual_state":                 # (the rig sets RUNNING on its Overlay)
                self.assertEqual(fresh[name], value, name)

    def test_the_42_variables_of_decision_D3_are_discarded_by_a_generation_and_only_the_window_references_remain(self):
        import test_scoring_observation_si0 as si0
        marker = object()
        o = self.o
        self.rig.gui.valid = {R.Rig.HWND}
        for name in si0.D3_VARIABLES:
            setattr(o, name, marker)
        o.reset_telemetry_state()
        o.reset_generation_state()
        survivors = {name for name in si0.D3_VARIABLES if getattr(o, name) is marker}
        self.assertEqual(len(si0.D3_VARIABLES), 42)
        self.assertEqual(survivors, set())                                  # (bve_hwnd = marker is not a valid window -> forgotten as well)
        self.assertIsNone(o.bve_hwnd)
        self.assertFalse(o.is_linked)

    def test_a_valid_window_reference_survives_a_generation_and_a_stale_one_does_not(self):
        o = self.o
        o.bve_hwnd = R.Rig.HWND
        o.is_borderless_fullscreen = True
        o.bve_original_style = 5
        o.reset_generation_state()
        self.assertEqual((o.bve_hwnd, o.is_borderless_fullscreen, o.bve_original_style), (R.Rig.HWND, True, 5))
        self.rig.gui.valid = set()
        o.reset_generation_state()
        self.assertEqual((o.bve_hwnd, o.is_borderless_fullscreen, o.bve_original_style, o.is_linked), (None, False, None, False))

    def test_everything_a_generation_must_not_carry_over_is_gone(self):
        o = self.o
        o.manual_eb_penalty_applied = True
        o.manual_eb_accum_time = 0.3
        o.manual_eb_cooling_time = 0.5
        o.smee_virtual_eb_active = True
        o.hb_prev_notch, o.hb_strong_entered, o.hb_cushion_entry_time, o.hb_cushion_max_g = 7, True, 3.0, 0.2
        o.bb_state, o.bb_apply_count, o.bb_release_count, o.bb_is_in_zone, o.bb_evaluated = "FAILED", 3, 2, True, True
        o.bb_current_notch, o.bb_prev_stable_notch, o.bb_notch_change_time, o.bb_is_stable = 5, 4, 9.0, False
        o.last_jump_count, o.bve_jump_count, o.jump_lock = 4, 4, True
        o.station_list = [R.station("old")]
        o.is_official_jumping, o.is_official_retry = True, True
        o.setting_start_idx, o.setting_end_idx, o.setting_stop_distance, o.setting_initial_brake = 2, 5, 90, "STATION"
        o.is_scoring_mode, o.is_scoring_finished, o.score, o.total_retry_count = True, True, -800, 3
        o.score_details["eb"] = -500
        o.save_data.append({"x": 1})
        o.popups.append({"text": "t", "expire_time": 1e9, "category": "転動"})
        o.prev_next_loc, o.prev_door, o.prev_term, o.last_update_time, o.prev_frame_loc = 1000.0, 1, 1, 77.0, 55.0
        o.strictest_flashed_val, o.strictest_flashed_key, o.current_flashing_key, o.limit_flash_counts = 40.0, "k", "k", {"k": 2}
        o.blink_active, o.blink_phase, o.disp_limit, o.current_base_limit, o.prev_base_limit = True, 0.5, 40.0, 40.0, 60.0
        o.menu_state, o.menu_cursor, o.dropdown_active, o.input_buffer = 5, 3, True, "12"
        o.pending_jump_complete, o.expected_target_loc = {"x": 1}, 500.0
        o.is_fast_forwarding, o.ff_check_real_time = True, 5.0
        o.is_bve_loaded, o.initial_kickstart_done, o.auto_pause_pending, o.bve_actual_state = True, True, True, "PAUSED"
        o.meta_title = "route"
        o.bve_bp_initial_received = True
        o.reset_telemetry_state()
        o.reset_generation_state()
        self.assertEqual((o.manual_eb_penalty_applied, o.manual_eb_accum_time, o.manual_eb_cooling_time, o.smee_virtual_eb_active), (False, 0.0, 0.0, False))
        self.assertEqual((o.hb_prev_notch, o.hb_strong_entered, o.hb_cushion_entry_time, o.hb_cushion_max_g), (0, False, 0.0, 0.0))
        self.assertEqual((o.bb_state, o.bb_apply_count, o.bb_release_count, o.bb_is_in_zone, o.bb_evaluated), ("IDLE", 0, 0, False, False))
        self.assertEqual((o.bb_current_notch, o.bb_prev_stable_notch, o.bb_notch_change_time, o.bb_is_stable), (0, 0, 0.0, True))
        self.assertEqual((o.last_jump_count, o.bve_jump_count, o.jump_lock, o.jump_baseline_pending), (0, 0, False, True))
        self.assertEqual((o.station_list, o.is_official_jumping, o.is_official_retry), ([], False, False))
        self.assertEqual((o.setting_start_idx, o.setting_end_idx, o.setting_stop_distance, o.setting_initial_brake), (0, -1, -1, "NONE"))
        self.assertEqual((o.is_scoring_mode, o.is_scoring_finished, o.score, o.total_retry_count, o.save_data, o.popups), (False, False, 0, 0, [], []))
        self.assertEqual(set(o.score_details.values()), {0})
        self.assertEqual((o.prev_next_loc, o.prev_door, o.prev_term, o.last_update_time, o.prev_frame_loc), (-1.0, 0, 0, 0.0, 0.0))
        for dropped in ("strictest_flashed_val", "strictest_flashed_key", "current_flashing_key", "limit_flash_counts"):
            self.assertNotIn(dropped, vars(o))
        self.assertEqual((o.blink_active, o.blink_phase, o.disp_limit, o.current_base_limit, o.prev_base_limit), (False, 0.0, 1000.0, 1000.0, 1000.0))
        self.assertEqual((o.menu_state, o.menu_cursor, o.dropdown_active, o.input_buffer), (0, 0, False, ""))
        self.assertEqual((o.pending_jump_complete, o.expected_target_loc, o.is_fast_forwarding, o.ff_check_real_time), (None, -1.0, False, 0.0))
        self.assertEqual((o.is_bve_loaded, o.initial_kickstart_done, o.auto_pause_pending, o.bve_actual_state), (False, False, False, ""))
        self.assertEqual((o.meta_title, o.bve_bp_initial_received), ("", False))

    def test_a_generation_keeps_the_users_settings_and_the_infrastructure(self):
        o = self.o
        o.pen_eb, o.pen_limit, o.rank_a_ratio, o.F8_disable, o.show_graph = False, False, 0.8, False, True
        o.disp_settings["speed"] = False
        sock, timer, gate = o.udp_socket, o.timer, o.telemetry_gate
        o.reset_telemetry_state()
        o.reset_generation_state()
        self.assertEqual((o.pen_eb, o.pen_limit, o.rank_a_ratio, o.F8_disable, o.show_graph, o.disp_settings["speed"]), (False, False, 0.8, False, True, False))
        self.assertIs(o.udp_socket, sock)
        self.assertIs(o.timer, timer)
        self.assertIs(o.telemetry_gate, gate)

    def test_the_session_discard_keeps_the_scenario_and_closes_the_menu_without_pressing_anything(self):
        o = self.o
        o.station_list = [R.station("A")]
        o.setting_start_idx = 1
        o.is_scoring_mode = True
        o.score = -300
        o.menu_state = 5
        o.bve_speed = 12.5
        self.mi.discard_scoring_session(o)
        self.assertEqual((o.is_scoring_mode, o.score, o.menu_state), (False, 0, 0))
        self.assertEqual((len(o.station_list), o.setting_start_idx, o.bve_speed), (1, 1, 12.5))
        self.assertEqual(self.rig.api.posted, [])

    def test_the_normal_mode_has_no_gate_no_sink_and_applies_a_station_list_at_once(self):
        o = self.o
        self.assertFalse(hasattr(o, "scoring_start_gate"))
        self.assertFalse(hasattr(o, "input_event_sink"))
        o.udp_socket.incoming = [b"STALIST:A=1=0.0=-1=-1=-1=15000=0=0"]
        o.read_udp_data()
        self.assertEqual([s["name"] for s in o.station_list], ["A"])
        self.assertFalse(hasattr(o, "pending_station_list"))

    def test_the_normal_mode_generation_path_is_unchanged(self):
        """The strict gate is what asks for the generation reset: the normal (manual) gate never does, so apply_telemetry_text of normal mode discards only what it
        always discarded (SI-0 list: tests/test_scoring_observation_si0.py G)."""
        o = self.o
        o.station_list = [R.station("old")]
        o.last_jump_count = 5
        o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.assertEqual((len(o.station_list), o.last_jump_count), (1, 5))
        self.assertFalse(hasattr(o, "jump_baseline_pending"))


# ----------------------------------------------------------------------------------------------------------------------------------------------
class B_ScoringInputGate(unittest.TestCase):
    def setUp(self):
        import managed_input
        import telemetry_contract
        self.mi, self.tc = managed_input, telemetry_contract

    def avail(self, *tokens):
        return self.tc.Availability(tokens)

    def test_a_sender_without_AVAIL_has_everything_and_nothing_is_missing(self):
        for btype in ("Ecb", "Cl", "Smee"):
            self.assertEqual(self.mi.scoring_input_blockers(self.tc.ALL_AVAILABLE, btype, True), [])

    def test_Smee_needs_a_received_bp_initial_even_without_AVAIL(self):
        self.assertEqual(self.mi.scoring_input_blockers(self.tc.ALL_AVAILABLE, "Smee", False), ["bp-initial-not-received"])
        self.assertEqual(self.mi.scoring_input_blockers(self.tc.ALL_AVAILABLE, "Ecb", False), [])

    def test_an_explicit_AVAIL_must_carry_every_group_the_rules_read(self):
        full = self.mi.SCORING_REQUIRED_TOKENS
        self.assertEqual(self.mi.scoring_input_blockers(self.avail(*full), "Ecb", False), [])
        for token in full:
            have = [t for t in full if t != token]
            self.assertEqual(self.mi.scoring_input_blockers(self.avail(*have), "Ecb", False), ["missing-" + token.replace("_", "-")], token)

    def test_Smee_also_needs_the_bpp_group_with_an_explicit_AVAIL(self):
        full = self.mi.SCORING_REQUIRED_TOKENS
        self.assertEqual(self.mi.scoring_input_blockers(self.avail(*full), "Smee", True), ["missing-bpp"])
        self.assertEqual(self.mi.scoring_input_blockers(self.avail(*(full + ("bpp",))), "Smee", True), [])

    def test_the_gate_words_are_fixed_words(self):
        for blockers in (self.mi.scoring_input_blockers(self.avail(), "Smee", False),):
            for word in blockers:
                self.assertRegex(word, r"^[a-z-]+$")

    def test_the_required_groups_are_known_tokens_and_the_pieces_the_scoring_rules_read(self):
        self.assertTrue(set(self.mi.SCORING_REQUIRED_TOKENS) <= self.tc.KNOWN_TOKENS)
        for not_required in ("bcp", "maplimit_ahead", "trainlen", "doortime", "meta"):
            self.assertNotIn(not_required, self.mi.SCORING_REQUIRED_TOKENS)       # BCP is no scoring input; TRAINLEN / limit candidates are SI-B questions


# ----------------------------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class ManagedCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qt_app()
        import main
        import sia_managed_rig as MR
        cls.main, cls.MR = main, MR

    def setUp(self):
        self.r = self.MR.ManagedRig(self.main)
        self.o, self.kb, self.gui, self.api, self.win = self.r.o, self.r.kb, self.r.gui, self.r.api_win32, self.r.win
        self.saved_profile = os.environ.get("USERPROFILE")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["USERPROFILE"] = self.tmp.name

    def tearDown(self):
        self.r.close()
        if self.saved_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = self.saved_profile
        self.tmp.cleanup()

    def posted_keys(self, code):
        return [p for p in self.api.posted if p[2] == code and p[1] == R.WM_KEYDOWN]

    def held(self):
        return self.kb.active()

    def scoring_on(self):
        return self.o.is_scoring_mode and not self.o.is_scoring_finished


class C_TheSixStatesAreKeptApart(ManagedCase):
    def test_python_running_alone_scoring_is_off_and_nothing_is_suppressed(self):
        self.assertTrue(self.r.attached)
        self.r.tick(20)
        self.assertEqual((self.r.hud.mode, self.o.is_scoring_mode, self.held(), self.gui.mutating()), ("hidden", False, [], []))
        self.assertEqual(self.api.posted, [])

    def test_the_four_session_driving_combinations_and_the_input_only_in_the_both_on_one(self):
        r, o = self.r, self.o
        r.go_active()
        o.is_scoring_mode = True
        o.bve_speed = 5.0
        r.tick(2)
        self.assertEqual(self.held(), ["f7", "f8", "p"])                    # (Session ON, Driving ON, telemetry): suppression exists
        for session, driving, expected_mode in ((True, False, "waiting"), (False, False, "hidden"), (False, True, "hidden")):
            r.publish(session, driving)
            r.tick(3)
            self.assertEqual(r.hud.mode, expected_mode, (session, driving))
            self.assertEqual(self.held(), [], (session, driving))
            if session:
                # Phase SI-A4: Driving OFF with the Session ON is a pause: the input is released but the scoring session is KEPT, and it goes on when Driving is ON again
                self.assertTrue(o.is_scoring_mode, (session, driving))
                r.publish(True, True)
                r.tick(2)
                self.assertTrue(o.is_scoring_mode)
                self.assertEqual(self.held(), ["f7", "f8", "p"])
            else:
                self.assertFalse(o.is_scoring_mode, (session, driving))    # Session OFF: the scoring session is gone
                r.publish(True, True)
                r.tick(2)
                self.assertFalse(o.is_scoring_mode)                          # coming back never resumes it
                self.assertEqual(self.held(), [])
                o.is_scoring_mode = True                                     # (the user starts again)
                r.tick(2)
                self.assertEqual(self.held(), ["f7", "f8", "p"])

    def test_session_on_and_driving_on_without_telemetry_shows_nothing_and_suppresses_nothing(self):
        r, o = self.r, self.o
        r.publish(True, True, 1)
        r.tick(5)
        self.assertEqual((r.hud.mode, r.hud.shown, self.held()), ("active", False, []))
        o.is_scoring_mode = True
        o.bve_speed = 5.0
        r.tick(3)
        self.assertEqual(self.held(), [])                                    # the step does not run before telemetry of this generation arrived

    def test_the_input_step_runs_only_while_all_of_session_driving_and_telemetry_hold(self):
        r = self.r
        r.go_active()
        steps = r.input.steps
        r.tick(5)
        self.assertEqual(r.input.steps, steps + 5)
        r.publish(True, False)
        r.tick(5)
        self.assertEqual(r.input.steps, steps + 5)

    def test_hud_active_is_not_scoring_active(self):
        r = self.r
        r.go_active()
        self.assertTrue(r.hud.shown)
        self.assertFalse(self.o.is_scoring_mode)
        self.assertEqual(self.held(), [])                                    # no menu, no scoring: BVE's keys are untouched

    def test_hud_and_input_use_the_pid_matched_window_and_never_search_by_title(self):
        r, o = self.r, self.o
        o.find_bve_window = lambda: (_ for _ in ()).throw(AssertionError("title search in managed mode"))
        self.gui.titles = {5000: "BVE Trainsim 6", 9001: "BVE Trainsim 5 (another BVE)"}
        self.gui.valid = {5000, 9001}
        r.go_active()
        self.kb.pressed.add("f12")
        r.tick(2)
        self.assertTrue(all(c[1] == 5000 for c in self.gui.mutating() if c[0] in ("SetWindowLong", "SetWindowPos") and c[1] in (5000, 9001)))
        self.assertTrue(any(c[0] == "SetWindowPos" and c[1] == 5000 and c[5:7] == (1280, 720) for c in self.gui.calls))
        self.assertEqual([c for c in self.gui.calls if len(c) > 1 and c[1] == 9001], [])


class D_ScoringPauseEndReselectReloadSoftOff(ManagedCase):
    def test_the_user_starts_and_the_start_needs_nothing_else(self):
        r, o = self.r, self.o
        r.go_active()
        r.start_scoring_via_menu()
        self.assertTrue(o.is_scoring_mode)
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(o.udp_socket.written[-1][1], 54322)
        self.assertEqual(len(r.events("scoring-start")), 1)
        self.assertEqual(len(r.events("scoring-start-refused")), 0)

    def test_the_menu_keys_are_suppressed_while_the_menu_is_open_and_released_when_it_closes(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f1")
        self.assertEqual(o.menu_state, 1)
        r.tick()
        for key in ("f7", "p", "f8", "up", "down", "enter", "backspace", "h", "0", "<all>"):
            self.assertIn(key, self.held())
        r.tap("f1")
        r.tick(2)
        self.assertEqual((o.menu_state, self.held()), (0, []))

    def test_scoring_suppresses_f7_p_and_while_driving_f8_and_the_time_and_position_window(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active(speed=0.0)
        r.start_scoring_via_menu()
        o.is_official_jumping = False
        r.send(self.MR.tele(1, speed=3.0))
        r.tick(3)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        self.assertFalse(self.gui.enabled)
        self.assertTrue(any("state=set" in e and "diag" in e for e in r.events("input-hold")))         # the window lock is part of the hold: "diag" in the kinds
        self.assertEqual(r.events("window-lock"), [])

    def test_scoring_end_releases_the_suppression_and_the_window(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active()
        o.is_scoring_mode = True
        o.bve_speed = 4.0
        r.tick(3)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        o.is_scoring_finished = True
        r.tick(2)
        self.assertEqual(self.held(), [])
        self.assertTrue(self.gui.enabled)
        self.assertEqual(len(r.events("scoring-finish")), 1)

    def test_the_users_interrupt_releases_everything_and_is_logged_as_an_abort_by_the_user(self):
        r, o = self.r, self.o
        r.go_active()
        o.is_scoring_mode = True
        r.tick(2)
        r.tap("f1")
        r.tap("down")
        r.tap("enter")
        r.tap("up")
        r.tap("enter")
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.menu_state, self.held()), (False, 0, []))
        self.assertTrue(any("reason=user" in e for e in r.events("scoring-abort")))

    def test_pause_keeps_the_scoring_state_and_the_suppression_and_resumes_the_same_run(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        o.score = -600
        o.manual_eb_penalty_applied = True
        r.tick(3)
        before = (o.score, o.manual_eb_penalty_applied, o.is_scoring_mode, tuple(self.held()))
        r.tick(100, seconds=0.05)                                            # BVE paused: no telemetry line arrives, the Caller's Tick goes on (Driving stays ON)
        self.assertEqual((o.score, o.manual_eb_penalty_applied, o.is_scoring_mode, tuple(self.held())), before)
        self.assertFalse(self.gui.enabled)
        r.send(self.MR.tele(1, time_ms=36000100, speed=5.0))                 # resumed
        r.tick(3)
        self.assertEqual((o.score, o.is_scoring_mode), (-600, True))
        self.assertEqual(r.hud.mode, "active")

    def test_scenario_end_session_off_discards_scoring_releases_everything_and_presses_nothing(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        o.score = -300
        r.tick(3)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        posted = list(self.api.posted)
        r.publish(False, False)
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score, self.held(), o.menu_state), (False, 0, [], 0))
        self.assertTrue(self.gui.enabled)
        self.assertEqual(self.api.posted, posted)                           # no P, no F8 injected on the way out
        self.assertEqual(o.station_list, [])
        self.assertEqual(r.hud.mode, "hidden")
        self.assertTrue(any("reason=session-off" in e for e in r.events("input-hold")))
        self.assertTrue(any("reason=session-off" in e for e in r.events("scoring-abort")))

    def test_scenario_end_with_the_menu_open_closes_it_and_releases_the_menu_keys(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f1")
        r.tick()
        self.assertTrue(self.held())
        r.publish(False, False)
        r.tick(2)
        self.assertEqual((o.menu_state, self.held()), (0, []))

    def test_selection_screen_wait_has_no_key_hook_no_window_lock_and_no_hud(self):
        r = self.r
        r.go_active(speed=5.0)
        self.o.is_scoring_mode = True
        r.publish(False, False)
        r.tick(5)
        self.kb.pressed.update({"f7", "p", "f8", "f1"})
        r.tick(5)
        self.assertEqual((self.held(), r.hud.shown, self.o.menu_state), ([], False, 0))     # F1 does nothing while no scenario session exists

    def test_reselect_a_new_generation_starts_clean_and_scoring_stays_off_until_the_user_starts_it(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1, speed=5.0)
        r.start_scoring_via_menu()
        o.is_official_jumping = False
        o.score = -400
        o.manual_eb_penalty_applied = True
        o.smee_virtual_eb_active = True
        o.last_jump_count = 3
        o.setting_end_idx = 2
        r.publish(False, False)
        r.tick(3)
        r.publish(True, True, 2)
        r.tick(2)
        r.send(self.MR.STALIST, self.MR.tele(2, speed=0.0))
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, o.score, o.manual_eb_penalty_applied, o.smee_virtual_eb_active, o.setting_end_idx), (False, 0, False, False, -1))
        self.assertEqual(self.held(), [])
        self.assertEqual((len(o.station_list), r.hud.mode, o.current_scenario_id), (3, "active", 2))
        self.assertEqual(len(r.events("hud-update-start")), 2)               # the SAME controller / Overlay resumed (nothing was rebuilt)

    def test_reload_a_new_generation_without_a_session_gap_discards_the_scoring_state_at_once(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1, speed=5.0)
        o.is_scoring_mode = True
        o.score = -900
        o.manual_eb_accum_time = 0.3
        r.tick(3)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        r.publish(True, True, 2)                                             # the Caller names the new generation; the sender has not sent a line of it yet
        r.tick(2)
        self.assertEqual((o.is_scoring_mode, o.score, o.manual_eb_accum_time, self.held()), (False, 0, 0.0, []))
        self.assertTrue(any("reason=generation" in e for e in r.events("scoring-abort")))
        self.assertFalse(r.hud.shown)                                        # and the HUD waits for the telemetry of the new generation

    def test_a_reload_whose_telemetry_arrived_before_the_caller_is_applied_when_the_generation_arrives(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1)
        new_list = "STALIST:X=1=0.0=-1=-1=-1=15000=0=0,Y=0=900.0=-1=-1=-1=15000=0=1"
        r.send(new_list, self.MR.tele(2, speed=0.0))                         # the sender is ahead of the Caller: HELD, not applied
        r.tick(2)
        self.assertEqual(len(o.station_list), 3)                              # still the first scenario's list
        self.assertFalse(r.hud.shown)
        r.publish(True, True, 2)
        r.tick(3)
        self.assertEqual([s["name"] for s in o.station_list], ["X", "Y"])
        self.assertEqual((o.current_scenario_id, r.hud.shown), (2, True))

    def test_driving_off_keeps_the_scoring_session_and_releases_the_input_at_once(self):
        """Phase SI-A4 (this was `soft_off_discards_the_scoring_session` until the real-machine acceptance of SI-A: BVE's Pause stops the Ticks, the Caller
        reports that as Driving OFF, and a Pause must not end the user's scoring; the Python side cannot tell it from any other Driving OFF)."""
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        o.score = -200
        r.tick(3)
        posted = list(self.api.posted)
        r.publish(True, False)
        r.tick()
        self.assertEqual((o.is_scoring_mode, o.score, self.held()), (True, -200, []))
        self.assertTrue(self.gui.enabled)
        self.assertEqual(r.hud.mode, "waiting")
        self.assertEqual(len(o.station_list), 3)
        self.assertEqual(r.events("scoring-abort"), [])
        self.assertEqual(self.api.posted, posted)                             # nothing is pressed in BVE on the way out
        self.assertTrue(any("scoring=yes" in e for e in r.events("input-pause")))

    def test_driving_on_again_continues_the_same_scoring_and_input_is_live_again(self):
        r, o = self.r, self.o
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        o.score = -150
        r.tick(2)
        r.publish(True, False)
        r.tick(3)
        r.publish(True, True)
        r.tick(5)
        self.assertEqual((o.is_scoring_mode, o.score, self.held()), (True, -150, ["f7", "f8", "p"]))
        self.assertEqual(r.events("scoring-abort"), [])
        o.is_scoring_mode = False
        r.tick(2)
        r.tap("f1")
        self.assertEqual(o.menu_state, 1)                                     # the menu works again

    def test_soft_off_during_the_menu_closes_it_quietly(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f1")
        posted = len(self.api.posted)
        r.publish(True, False)
        r.tick(2)
        self.assertEqual((o.menu_state, self.held(), len(self.api.posted)), (0, [], posted))

    def test_no_scoring_state_is_discarded_while_nothing_changes(self):
        r, o = self.r, self.o
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        o.score = -200
        r.tick(50)
        self.assertEqual((o.is_scoring_mode, o.score), (True, -200))

    def test_the_scoring_start_is_refused_without_a_station_list_and_the_menu_closes_with_one_warning(self):
        r, o = self.r, self.o
        r.go_active(with_stations=False)
        r.start_scoring_via_menu()
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(o.menu_state, 0)
        self.assertEqual([p["text"] for p in o.popups], ["採点を開始できません（入力が揃っていません）"])
        self.assertTrue(any("reason=no-station-list" in e for e in r.events("scoring-start-refused")))
        self.assertEqual(o.udp_socket.written, [])

    def test_the_scoring_start_is_refused_for_a_smee_run_without_a_received_bp_initial(self):
        r, o = self.r, self.o
        r.go_active(BTYPE="Smee")
        o.bve_btype = "Smee"
        self.assertFalse(getattr(o, "bve_bp_initial_received", False))
        r.start_scoring_via_menu()
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(any("reason=bp-initial-not-received" in e for e in r.events("scoring-start-refused")))

    def test_the_scoring_start_is_allowed_for_a_smee_run_once_bp_initial_was_received(self):
        r, o = self.r, self.o
        r.go_active(BTYPE="Smee", BPP="490.0:490.0")
        r.start_scoring_via_menu()
        self.assertTrue(o.is_scoring_mode)

    def test_the_scoring_start_is_refused_when_an_explicit_AVAIL_lacks_a_group(self):
        r, o = self.r, self.o
        have = [t for t in self.main_managed_input().SCORING_REQUIRED_TOKENS if t != "handle"]
        r.go_active(avail=have)
        r.start_scoring_via_menu()
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(any("reason=missing-handle" in e for e in r.events("scoring-start-refused")))

    def main_managed_input(self):
        import managed_input
        return managed_input

    def test_the_managed_overlay_has_the_gate_and_the_event_sink(self):
        self.assertTrue(callable(self.o.scoring_start_gate))
        self.assertTrue(callable(self.o.input_event_sink))


class E_KeysAndWindowsInManagedMode(ManagedCase):
    def test_esc_does_not_quit_the_managed_application(self):
        r = self.r
        r.go_active()
        self.kb.pressed.add("esc")
        r.tick(5)
        self.assertEqual(R.FakeApp.quits, 0)

    def test_losing_the_bve_window_does_not_quit_the_managed_application(self):
        r = self.r
        r.go_active()
        self.gui.valid = set()
        self.gui.titles = {}
        self.win.alive = False
        r.tick(10, seconds=0.6)
        self.assertEqual(R.FakeApp.quits, 0)
        self.assertEqual(self.held(), [])
        self.assertTrue(any("hud-window-unlinked" in e for e in r.log.lines))

    def test_f11_is_borderless_and_f11_again_restores_the_linked_window(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(o.is_borderless_fullscreen)
        r.tap("f11")
        self.assertFalse(o.is_borderless_fullscreen)
        self.assertEqual([e for e in r.events("window-fullscreen")], [e for e in r.log.lines if "event=window-fullscreen" in e])
        self.assertEqual(len(r.events("window-fullscreen")), 2)

    def test_f12_forces_the_standard_window_and_f11_f12_sequences_work(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f11")
        R.FakeQTimer.flush()
        r.tap("f12")
        self.assertFalse(o.is_borderless_fullscreen)
        r.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(o.is_borderless_fullscreen)
        self.assertEqual(len(r.events("window-standard")), 1)

    def test_f11_and_f12_do_nothing_while_the_bve_window_is_not_in_front(self):
        r = self.r
        r.go_active()
        self.gui.foreground = 1
        r.tap("f11")
        r.tap("f12")
        self.assertEqual(self.gui.mutating(), [])

    def test_f11_and_f12_do_nothing_without_a_scenario_session(self):
        r = self.r
        r.publish(False, False)
        r.tick(3)
        r.tap("f11")
        r.tap("f12")
        self.assertEqual(self.gui.mutating(), [])

    def test_a_different_bve_window_starts_without_the_fullscreen_state_of_the_old_one(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f11")
        R.FakeQTimer.flush()
        self.assertTrue(o.is_borderless_fullscreen)
        o.adopt_bve_window(9001)
        self.assertEqual((o.is_borderless_fullscreen, o.bve_original_style, o.bve_hwnd), (False, None, 9001))

    def test_the_fast_forward_is_released_in_a_scoring_run_in_managed_mode(self):
        r, o = self.r, self.o
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        o.bve_speed = 5.0
        r.tick(2)
        before = len(self.posted_keys(R.KEY_F8))
        r.send(self.MR.tele(1, time_ms=o.bve_time_ms + 5000, speed=5.0))
        r.tick(1, seconds=0.06)
        self.assertEqual(len(self.posted_keys(R.KEY_F8)), before + 1)
        self.assertEqual(len(r.events("ff-release")), 1)

    def test_the_time_and_position_window_is_restored_at_once_when_the_scoring_ends_or_the_session_ends(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active()
        o.is_scoring_mode = True
        r.tick(2)
        self.assertFalse(self.gui.enabled)
        r.publish(False, False)
        r.tick(2)
        self.assertTrue(self.gui.enabled)
        self.assertEqual([c for c in self.gui.calls if c[0] == "EnableWindow"], [("EnableWindow", 777, False), ("EnableWindow", 777, True)])

    def test_the_hud_still_sits_directly_above_the_driving_window(self):
        r = self.r
        r.go_active()
        r.tick(5)
        self.assertEqual(len(self.win.z_calls), 1)
        self.assertEqual(len(r.events("hud-owner-set")), 1)
        self.assertEqual(self.win.z[0], int(self.o.winId()))

    def test_the_scenario_selection_window_contract_nothing_is_touched_without_a_session(self):
        """Session OFF = the BVE scenario selection screen is up: no hook, no EnableWindow, no injected key, no window change by this application."""
        r = self.r
        r.go_active(speed=5.0)
        self.o.is_scoring_mode = True
        r.publish(False, False)
        r.tick(5)
        self.api.posted.clear()
        self.gui.calls.clear()
        self.kb.pressed.update({"f1", "f2", "f7", "f8", "p", "f11", "f12", "enter"})
        r.tick(10)
        self.assertEqual((self.held(), self.api.posted, self.gui.mutating()), ([], [], []))


class F_PtoPInManagedMode(ManagedCase):
    """Phase SI-A6: managed mode presses P ONLY for a recovery token (tests/test_pause_recovery_sia6.py). Phase SI-A pressed it whenever "Session ON, Driving ON,
    STATUS PAUSED, no station list" held, and SI-A4 also with Driving OFF; both fired on ordinary scenario loads (a short PAUSED window follows every first Tick).
    The situations of those tests are kept - and now must send NO P at all."""

    def paused_load(self):
        r = self.r
        r.publish(True, True, 1)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(2)

    def test_pause_at_load_presses_nothing_even_when_the_time_runs_and_the_list_is_there(self):
        r, o = self.r, self.o
        self.paused_load()
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertFalse(o.initial_kickstart_done)
        r.tick(5)
        r.send(self.MR.STALIST, self.MR.tele(1, time_ms=36000500))
        r.tick(2)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertFalse(o.auto_pause_pending)
        r.tick(5)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)
        self.assertEqual(r.events("kickstart"), [])

    def test_no_kick_start_without_a_session(self):
        r = self.r
        r.publish(False, False, 1)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(5)
        self.assertEqual(self.posted_keys(R.KEY_P), [])

    def test_driving_off_with_a_paused_status_presses_nothing(self):
        """Phase SI-A4 pressed here (`the kick start acts with Driving OFF`); SI-A6 withdrew it: this is also what an ordinary load looks like for a moment."""
        r = self.r
        r.publish(True, False, 1)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(5)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)

    def test_the_kick_start_waits_for_the_window(self):
        r = self.r
        self.win.alive = False
        r.publish(True, True, 1)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(5, seconds=0.6)
        self.assertEqual(self.posted_keys(R.KEY_P), [])

    def test_the_station_list_of_the_previous_generation_still_means_nothing_for_the_next_generation(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1)
        self.assertEqual(len(o.station_list), 3)
        r.publish(False, False)
        r.tick(2)
        r.publish(True, True, 2)
        r.tick(2)
        self.assertEqual(o.station_list, [])
        r.send("STATUS:LOADED:PAUSED")
        r.tick(3)
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)

    def test_each_generation_presses_nothing(self):
        r = self.r
        for generation in (1, 2, 3):
            r.publish(True, True, generation)
            r.tick(2)
            r.send("STATUS:LOADED:PAUSED")
            r.tick(3)
            self.assertEqual(len(self.posted_keys(R.KEY_P)), 0, generation)
            r.publish(False, False)
            r.tick(2)

    def test_a_status_of_the_previous_scenario_does_not_leak_into_the_next_one(self):
        r, o = self.r, self.o
        self.paused_load()
        r.publish(False, False)
        r.tick(2)
        r.publish(True, True, 2)
        r.tick(3)
        self.assertEqual((o.bve_actual_state, o.is_bve_loaded, o.initial_kickstart_done), ("", False, False))
        self.assertEqual(len(self.posted_keys(R.KEY_P)), 0)

class G_StationListAndJumpReference(ManagedCase):
    def test_a_station_list_becomes_THE_list_with_the_accepted_line_that_follows_it(self):
        r, o = self.r, self.o
        r.go_active(with_stations=False)
        self.assertEqual(o.station_list, [])
        r.send(self.MR.STALIST)                                               # no telemetry line after it yet
        self.assertEqual(o.station_list, [])
        r.send(self.MR.tele(1))
        self.assertEqual(len(o.station_list), 3)

    def test_a_station_list_followed_by_a_stale_line_is_dropped(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1)
        r.publish(False, False)
        r.tick(2)
        r.publish(True, True, 2)
        r.tick(2)
        self.assertEqual(o.station_list, [])
        r.send(self.MR.STALIST, self.MR.tele(1))                              # a straggler of the previous scenario (retired SCENARIO_ID)
        self.assertEqual(o.station_list, [])
        self.assertIsNone(o.pending_station_list)
        r.send(self.MR.STALIST, self.MR.tele(2))
        self.assertEqual(len(o.station_list), 3)

    def test_the_first_accepted_line_of_a_generation_is_the_jump_reference(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1, JUMP=5)
        self.assertEqual((o.last_jump_count, o.bve_jump_count, o.jump_lock), (5, 5, False))
        o.is_scoring_mode = True
        r.tick(5)
        self.assertTrue(o.is_scoring_mode)                                    # the late start of the process does not look like a jump
        r.publish(False, False)
        r.tick(2)
        r.publish(True, True, 2)
        r.tick(2)
        r.send(self.MR.STALIST, self.MR.tele(2, JUMP=9))
        r.tick(2)
        self.assertEqual((o.last_jump_count, o.jump_lock), (9, False))

    def test_a_real_jump_after_the_reference_is_still_detected_and_aborts_the_scoring(self):
        r, o = self.r, self.o
        r.go_active(sid=1, generation=1, JUMP=5)
        o.is_scoring_mode = True
        o.is_official_jumping = False
        r.tick(2)                                                              # (the start is seen by the controller before the jump comes)
        r.send(self.MR.tele(1, JUMP=6))
        r.tick(2)
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual([p["text"] for p in o.popups], ["不正なジャンプを検知しました。", "採点を中断します。"])
        self.assertTrue(any("reason=jump" in e for e in r.events("scoring-abort")))
        self.assertEqual(self.held(), [])

    def test_bp_initial_received_follows_the_three_element_BPP_per_generation(self):
        r, o = self.r, self.o
        r.go_active(BPP="300.0")
        self.assertFalse(o.bve_bp_initial_received)
        r.send(self.MR.tele(1, BPP="300.0:490.0"))
        self.assertTrue(o.bve_bp_initial_received)
        r.publish(False, False)
        r.tick(2)
        r.publish(True, True, 2)
        r.tick(2)
        self.assertFalse(o.bve_bp_initial_received)

    def test_pending_station_lists_never_survive_the_session_end(self):
        r, o = self.r, self.o
        r.go_active()
        r.send(self.MR.STALIST)                                               # pending
        r.publish(False, False)
        r.tick(2)
        self.assertIsNone(o.pending_station_list)
        self.assertEqual(o.station_list, [])


class H_StopParentLossFailSafeAndTheSaveDialog(ManagedCase):
    def test_stop_releases_every_hook_enables_the_window_and_restores_the_fullscreen(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active(speed=5.0)
        r.tap("f11")
        R.FakeQTimer.flush()
        o.is_scoring_mode = True
        r.tick(3)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        self.assertFalse(self.gui.enabled)
        self.gui.calls.clear()
        r.hud.shutdown()
        self.assertEqual((self.held(), self.gui.enabled, o.is_scoring_mode, o.is_borderless_fullscreen), ([], True, False, False))
        self.assertTrue(any(c[0] == "SetWindowPlacement" for c in self.gui.calls))                    # the fullscreen was undone
        self.assertEqual(len(r.events("input-summary")), 1)

    def test_stop_is_idempotent(self):
        r = self.r
        r.go_active(speed=5.0)
        self.o.is_scoring_mode = True
        r.tick(3)
        r.hud.shutdown()
        calls = len(self.gui.calls)
        hooks = len(self.kb.unhooked)
        r.hud.shutdown()
        self.assertEqual((len(self.gui.calls), len(self.kb.unhooked)), (calls, hooks))

    def test_stop_with_the_menu_open_releases_the_menu_keys(self):
        r, o = self.r, self.o
        r.go_active()
        r.tap("f1")
        r.tick()
        r.hud.shutdown()
        self.assertEqual((self.held(), o.menu_state, o.numeric_router_hook), ([], 0, None))

    def test_the_state_block_lost_after_ready_releases_the_input_for_good(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        r.tick(3)
        self.assertEqual(self.held(), ["f7", "f8", "p"])
        r.source.raise_on_read = OSError("x")
        r.tick(3)
        self.assertEqual((self.held(), self.gui.enabled, o.is_scoring_mode, r.hud.failsafe), ([], True, False, "read-OSError"))
        r.source.raise_on_read = None
        o.is_scoring_mode = True
        r.tick(5)
        self.assertEqual(self.held(), [])                                       # latched: the input stays closed until the Stop request

    def test_stop_while_the_result_save_dialog_is_open_closes_the_dialog_and_the_loop_returns(self):
        """A real Qt event loop: the dialog (a non-native Qt dialog instance in managed mode) is open inside the step; the Stop request closes it, the
        nested loop returns, and the application quits - well inside the 3 seconds the Caller waits."""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        import managed_input
        r, o = self.r, self.o
        managed_input.attach_result_dialog(o)
        o.is_scoring_mode = True
        o.is_scoring_finished = True
        o.station_list = [R.station("A")]
        bridge = self.main._ManagedShutdownBridge()
        bridge.before_quit = o.close_result_dialog
        marks = {}

        def open_dialog():
            marks["t0"] = time.time()
            o.take_result_screenshot()
            marks["returned"] = time.time()

        def stop():
            marks["dialog_open"] = o.result_dialog is not None
            marks["stop_at"] = time.time()
            bridge.on_shutdown_requested()

        QTimer.singleShot(0, open_dialog)
        QTimer.singleShot(300, stop)
        QTimer.singleShot(5000, QApplication.instance().quit)               # watchdog (must not be what ends the dialog)
        QApplication.instance().exec()
        self.assertTrue(marks.get("dialog_open"), "the dialog was not open when Stop arrived")
        self.assertIn("returned", marks)
        self.assertLess(marks["returned"] - marks["stop_at"], 1.0)
        self.assertEqual(R.FakeApp.quits, 1)                                    # the application quit request of the bridge
        self.assertIsNone(getattr(o, "result_dialog", None))
        self.assertFalse(o.is_result_saved)
        self.assertFalse(o.is_capturing_screenshot)

    def test_the_managed_step_does_not_run_inside_the_open_save_dialog(self):
        r, o = self.r, self.o
        r.go_active()
        o.is_capturing_screenshot = True
        steps = r.input.steps
        r.tick(5)
        self.assertEqual(r.input.steps, steps)
        o.is_capturing_screenshot = False
        r.tick()
        self.assertEqual(r.input.steps, steps + 1)

    def test_the_save_dialog_saves_through_the_qt_dialog_instance(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        import managed_input
        o = self.o
        ask = managed_input.attach_result_dialog(o)
        target = os.path.join(self.tmp.name, "result.jpg")
        seen = {}

        def accept():
            from PyQt6.QtWidgets import QLineEdit
            dialog = o.result_dialog
            seen["non_native"] = bool(dialog.testOption(type(dialog).Option.DontUseNativeDialog))
            dialog.findChild(QLineEdit, "fileNameEdit").setText(target)         # what the user types
            dialog.accept()

        QTimer.singleShot(200, accept)
        self.assertEqual(ask(os.path.join(self.tmp.name, "x.jpg")).replace("/", "\\"), target)
        self.assertTrue(seen["non_native"])

    def test_cancelling_the_qt_save_dialog_gives_no_path(self):
        from PyQt6.QtCore import QTimer
        import managed_input
        o = self.o
        ask = managed_input.attach_result_dialog(o)
        QTimer.singleShot(200, o.close_result_dialog)
        self.assertEqual(ask(os.path.join(self.tmp.name, "x.jpg")), "")

    def test_closing_a_dialog_that_is_not_open_is_harmless(self):
        self.o.close_result_dialog()
        self.o.result_dialog = None
        self.o.close_result_dialog()


class J_EmergencyBrakeThroughTheManagedPath(ManagedCase):
    """The EB rules are the unchanged scoring_logic ones (SI-A1 pinned them in manual mode); here they run from real telemetry lines through the managed step."""

    def run_lines(self, brk_by_step, btype="Ecb", bpp_by_step=None, start_ms=36000000, step_ms=100):
        r = self.r
        for i, brk in enumerate(brk_by_step):
            kw = {}
            if bpp_by_step is not None:
                kw["BPP"] = bpp_by_step[i]
            r.send(self.MR.tele(1, time_ms=start_ms + i * step_ms, speed=10.0, brk=brk, btype=btype, **kw))
            r.tick()

    def scoring_ready(self, **kw):
        r, o = self.r, self.o
        r.go_active(speed=10.0, **kw)
        o.is_scoring_mode = True
        o.is_official_jumping = False
        o.station_list = [R.station("S1", 5000.0)]
        r.tick(2)
        return o

    def eb(self):
        return [p["text"] for p in self.o.popups if p["text"].startswith("非常ブレーキ")]

    def test_Ecb_an_eb_handle_of_0_3_seconds_costs_500_once_and_the_handle_release_does_not_charge_it_again(self):
        o = self.scoring_ready()
        self.run_lines(["N:0:8"] + ["EB:8:8"] * 6 + ["N:0:8"] * 4 + ["EB:8:8"] * 3)
        self.assertEqual(self.eb(), ["非常ブレーキ使用 -500"])
        self.assertEqual(o.score_details["eb"], -500)

    def test_Ecb_less_than_0_3_seconds_is_no_eb(self):
        o = self.scoring_ready()
        self.run_lines(["N:0:8"] + ["EB:8:8"] * 2 + ["N:0:8"] * 3)
        self.assertEqual((self.eb(), o.score_details["eb"]), ([], 0))

    def test_Smee_virtual_eb_starts_with_a_low_pipe_and_ends_when_the_pipe_recovers(self):
        o = self.scoring_ready(BTYPE="Smee", BPP="490.0:490.0")
        self.run_lines(["N:0:8"] + ["EB:8:8"] * 5 + ["N:0:8"] * 3 + ["N:0:8"] * 3,
                       btype="Smee", bpp_by_step=["490.0:490.0"] + ["380.0:490.0"] * 5 + ["380.0:490.0"] * 3 + ["480.0:490.0"] * 3)
        self.assertFalse(o.smee_virtual_eb_active)
        self.assertEqual(o.score_details["eb"], -500)
        self.assertEqual(o.score_details["rel_brake"], -100)                   # the one relaxation charge when the virtual EB ends at idle

    def test_Smee_virtual_eb_is_active_while_the_pipe_is_low(self):
        o = self.scoring_ready(BTYPE="Smee", BPP="490.0:490.0")
        self.run_lines(["N:0:8"] + ["EB:8:8"] * 5 + ["N:0:8"] * 3, btype="Smee", bpp_by_step=["490.0:490.0"] + ["380.0:490.0"] * 8)
        self.assertTrue(o.smee_virtual_eb_active)

    def test_CURRENT_a_run_that_started_with_bp_initial_keeps_the_fail_open_if_BPP_disappears_later(self):
        """CURRENT (unchanged scoring rule): when the BPP group disappears in the middle of a run the brake pipe reads its last value; a sender that stops sending BPP
        while the pipe is low keeps the virtual EB. The start gate refuses a Smee run WITHOUT bp_initial; it does not watch the run afterwards (SI-B: a sender
        never drops a group inside a scenario instance)."""
        o = self.scoring_ready(BTYPE="Smee", BPP="490.0:490.0")
        self.run_lines(["N:0:8"] + ["EB:8:8"] * 5 + ["N:0:8"] * 4, btype="Smee", bpp_by_step=["490.0:490.0"] + ["380.0:490.0"] * 9)
        self.assertTrue(o.smee_virtual_eb_active)

    def test_the_eb_state_of_a_run_is_not_carried_into_the_next_generation(self):
        r, o = self.r, self.o
        o = self.scoring_ready()
        self.run_lines(["N:0:8"] + ["EB:8:8"] * 6)
        self.assertTrue(o.manual_eb_penalty_applied)
        r.publish(False, False)
        r.tick(2)
        r.publish(True, True, 2)
        r.tick(2)
        r.send(self.MR.STALIST, self.MR.tele(2, speed=10.0))
        r.tick(2)
        self.assertEqual((o.manual_eb_penalty_applied, o.manual_eb_accum_time, o.manual_eb_cooling_time, o.smee_virtual_eb_active), (False, 0.0, 0.0, False))

    def test_pause_does_not_accumulate_eb_time(self):
        o = self.scoring_ready()
        self.run_lines(["N:0:8"])
        for _ in range(30):
            self.r.send(self.MR.tele(1, time_ms=36000000, speed=10.0, brk="EB:8:8"))       # the time stands still (paused): dt = 0
            self.r.tick()
        self.assertEqual((o.manual_eb_accum_time, self.eb()), (0.0, []))


class K_TruthTable(ManagedCase):
    def test_python_session_driving_scoring_all_combinations(self):
        """Python running is always true here (the process exists). For every Session x Driving x Scoring-requested combination: what the HUD does, whether the
        scoring survives, and whether anything is suppressed."""
        for session in (False, True):
            for driving in (False, True):
                for scoring in (False, True):
                    with self.subTest(session=session, driving=driving, scoring=scoring):
                        self.tearDown()
                        self.setUp()
                        r, o = self.r, self.o
                        r.go_active(speed=5.0)
                        o.is_scoring_mode = scoring
                        r.tick(3)
                        expected_hold = ["f7", "f8", "p"] if scoring else []
                        self.assertEqual(self.held(), expected_hold)
                        r.publish(session, driving)
                        r.tick(3)
                        live = session and driving
                        self.assertEqual(r.hud.mode, "active" if live else ("waiting" if session else "hidden"))
                        if live:
                            self.assertEqual((o.is_scoring_mode, self.held()), (scoring, expected_hold))
                        elif session:
                            self.assertEqual((o.is_scoring_mode, self.held(), self.gui.enabled), (scoring, [], True))    # SI-A4: Driving OFF = pause: kept, input released
                        else:
                            self.assertEqual((o.is_scoring_mode, self.held(), self.gui.enabled), (False, [], True))


class L_RobustnessOfTheRelease(ManagedCase):
    def test_the_event_lines_stay_within_the_part_of_the_callers_budget_that_is_ours(self):
        """The Caller copies at most 200 [MANAGED] lines per Python process: the input controller writes at most TOTAL_LINE_BUDGET of them and at most
        EVENT_LINE_CAP per event name; the rest is only counted."""
        r, o = self.r, self.o
        r.go_active(speed=5.0)
        before = len(r.log.lines)
        for _ in range(60):
            o.is_scoring_mode = True
            r.tick(2)
            o.is_scoring_mode = False
            r.tick(2)
        ours = [l for l in r.log.lines[before:] if " event=scoring-" in l or " event=input-hold " in l]
        self.assertLessEqual(len(ours), r.input.TOTAL_LINE_BUDGET)
        for name in ("scoring-start", "scoring-abort", "input-hold"):
            self.assertLessEqual(len([l for l in ours if (" event=%s " % name) in l]), r.input.cap_for(name), name)
        self.assertGreater(r.input.suppressed, 0)
        r.hud.shutdown()
        self.assertIn("in_suppressed=%d" % r.input.suppressed, r.events("input-summary")[0])

    def test_every_line_fits_the_160_characters_the_caller_keeps(self):
        r, o = self.r, self.o
        r.go_active(speed=5.0)
        r.start_scoring_via_menu()
        r.tick(5)
        r.publish(False, False)
        r.tick(3)
        r.hud.shutdown()
        ours = [l for l in r.log.lines if any((" event=%s" % n) in l for n in ("scoring-", "input-", "kickstart", "ff-release", "window-"))]
        self.assertGreater(len(ours), 3)
        for line in ours:                                                       # (the 189-character state line is the HUD controller's own, from before SI-A)
            self.assertLessEqual(len(line), 160, line)
            line.encode("ascii")                                                # the Caller prints ASCII only


    def test_a_hook_that_cannot_be_unhooked_twice_does_not_break_the_release(self):
        r, o = self.r, self.o
        self.kb.strict_unhook = True
        r.go_active(speed=5.0)
        o.is_scoring_mode = True
        r.tick(3)
        r.tap("f1")
        r.tick()
        r.publish(False, False)
        r.tick(2)
        r.hud.shutdown()
        self.assertEqual(self.held(), [])
        self.assertEqual(len(self.kb.unhooked), len(set(self.kb.unhooked)))      # every hook was removed exactly once

    def test_the_release_is_repeatable_and_quiet(self):
        r = self.r
        r.go_active()
        for _ in range(5):
            r.input.release("test")
        self.assertEqual(r.events("input-hold"), [])

    def test_a_window_that_is_gone_makes_the_release_harmless(self):
        r, o = self.r, self.o
        self.gui.diag = 777
        r.go_active()
        o.is_scoring_mode = True
        r.tick(3)
        self.gui.EnableWindow = lambda h, flag: (_ for _ in ()).throw(RuntimeError("window gone"))
        r.publish(False, False)
        r.tick(3)
        self.assertEqual((o.is_scoring_mode, self.held()), (False, []))

    def test_the_input_events_carry_no_station_name_and_no_path(self):
        r, o = self.r, self.o
        o.station_list = [R.station("秘密の駅")]
        r.go_active(speed=5.0)
        r.start_scoring_via_menu()
        r.tick(5)
        r.publish(False, False)
        r.tick(3)
        text = "\n".join(r.log.lines)
        self.assertNotIn("駅", text)
        self.assertNotIn(self.tmp.name, text)
        self.assertNotIn("\\", text)


# ----------------------------------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class M_TheProductionWiringInARealProcess(unittest.TestCase):
    """The REAL main.py in managed mode (real Overlay, real create_controller with the real Win32 state mapping and the real window API, real Qt loop), a
    stand-in for the BVE window in another process, the Caller's part played by this test (state block, Stop). The sender's datagrams go to the real UDP
    54321 (skipped when something else owns it). Not a single scoring key is pressed: this proves the wiring, the AppReady / Stop contract and the clean end."""

    def setUp(self):
        import test_managed_hud_e4 as E4
        self.E4 = E4
        if not E4.port_54321_is_free():
            self.skipTest("UDP 54321 is busy (a running TS Scoring is never touched) - INCONCLUSIVE")
        self.procs = []
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)
        env["PYTHONIOENCODING"] = "utf-8"
        self.env = env
        window = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_bve_window.py"), "60"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env, cwd=ROOT, creationflags=0x08000000)
        self.procs.append(window)
        ready = window.stdout.readline().decode("utf-8", "replace")
        self.window = window
        self.assertIn("READY pid=", ready)
        self.bve_pid = int(ready.split("pid=")[1].split()[0])
        self.args = E4.args_for(pid=self.bve_pid)
        self.owner = E4.Owner(self.args)

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                try:
                    if p.stdin:
                        p.stdin.close()
                except Exception:
                    pass
                try:
                    p.wait(3)
                except Exception:
                    p.kill()
            try:
                p.communicate(timeout=3)
            except Exception:
                pass
        self.owner.close()

    def send_udp(self, *texts):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for t in texts:
            s.sendto(t.encode("utf-8"), ("127.0.0.1", 54321))
        s.close()

    def test_appready_telemetry_hud_soft_off_session_off_reload_and_stop(self):
        E4 = self.E4
        import sia_managed_rig as MR
        b = self.owner.block
        b.publish(session=False, driving=False, generation=0)
        argv = [sys.executable, os.path.join(ROOT, "main.py"), "--managed", "--owner", "test", "--bve-pid", str(self.bve_pid), "--instance", self.args.instance]
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=ROOT, creationflags=0x08000000)
        self.procs.append(p)
        pump = E4.StderrPump(p)
        self.assertTrue(E4.wait_until(self.owner.ready, 30), "AppReady was not published\n" + "\n".join(pump.lines))
        b.publish(session=True, driving=True, generation=1)
        self.assertTrue(E4.wait_until(lambda: pump.count("event=hud-update-start") >= 1, 5))      # the Caller names the generation BEFORE the sender sends a line of it (loading takes seconds)
        for _ in range(40):
            self.send_udp(MR.STALIST, MR.tele(11, speed=0.0))
            if pump.count("event=hud-show") >= 1:
                break
            time.sleep(0.1)
        self.assertGreaterEqual(pump.count("event=hud-show"), 1, "\n".join(pump.lines))
        self.assertGreaterEqual(pump.count("event=telemetry-first"), 1)
        b.publish(driving=False)                                              # soft OFF
        self.assertTrue(E4.wait_until(lambda: pump.count("event=hud-hide") >= 1, 5))
        b.publish(driving=True)                                               # soft ON: the same process, the same Overlay
        self.assertTrue(E4.wait_until(lambda: pump.count("event=hud-update-start") >= 2, 5))
        b.publish(session=False)                                              # scenario ended
        self.assertTrue(E4.wait_until(lambda: pump.count("reason=session-off") >= 1, 5))
        self.assertIsNone(p.poll())
        self.assertTrue(self.owner.ready())
        b.publish(session=True, driving=True, generation=2)                   # re-selected / reloaded
        self.assertTrue(E4.wait_until(lambda: pump.count("event=hud-update-start") >= 3, 5))
        for _ in range(40):
            self.send_udp(MR.STALIST, MR.tele(12, speed=0.0))
            if pump.count("event=hud-show") >= 2:
                break
            time.sleep(0.1)
        self.assertGreaterEqual(pump.count("event=hud-show"), 2, "\n".join(pump.lines))
        self.assertIsNone(p.poll())
        b.publish(session=False, driving=False, closed=True)
        time.sleep(0.3)
        started = time.monotonic()
        self.owner.sync.set_event(self.owner.stop)
        code = p.wait(5)
        pump.join()
        text = "\n".join(pump.lines)
        self.assertEqual(code, 0, text)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assertNotIn("Traceback", text)
        self.assertIn("event=input-summary", text)                            # the input controller was attached by the production wiring and ended with the process
        self.assertEqual(pump.count("event=hud-error"), 0, text)
        self.assertEqual(pump.count("event=stop-received"), 1)
        self.assertEqual(pump.count("event=exit "), 1)
        self.assertIn("code=0", [l for l in pump.lines if "event=exit " in l][0])
        self.assertEqual(pump.count("scoring-start"), 0)                      # nothing scored: no key was pressed

    def test_stop_without_any_state_change_ends_cleanly_and_leaves_no_python_behind(self):
        E4 = self.E4
        b = self.owner.block
        b.publish(session=False, driving=False, generation=0)
        argv = [sys.executable, os.path.join(ROOT, "main.py"), "--managed", "--owner", "test", "--bve-pid", str(self.bve_pid), "--instance", self.args.instance]
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=ROOT, creationflags=0x08000000)
        self.procs.append(p)
        pump = E4.StderrPump(p)
        self.assertTrue(E4.wait_until(self.owner.ready, 30))
        self.owner.sync.set_event(self.owner.stop)
        self.assertEqual(p.wait(5), 0)
        self.assertTrue(E4.wait_until(E4.port_54321_is_free, 10))             # UDP 54321 is free again


# ----------------------------------------------------------------------------------------------------------------------------------------------
class I_DesktopLogAndStaticGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import utils
        cls.utils = utils

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME", "TS_SCORING_DESKTOP_LOG")}
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "Desktop"))
        os.environ["USERPROFILE"] = self.tmp.name
        os.environ["HOME"] = self.tmp.name
        self.enabled = self.utils.desktop_log_enabled()

    def tearDown(self):
        self.utils.set_desktop_log_enabled(self.enabled)
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def logfile(self):
        return os.path.join(self.tmp.name, "Desktop", "debug.log")

    def test_normal_mode_keeps_writing_by_default(self):
        self.assertTrue(self.enabled)
        self.utils.write_desktop_log("hello")
        self.assertTrue(os.path.isfile(self.logfile()))

    def test_a_disabled_log_writes_nothing_and_raises_nothing(self):
        self.utils.set_desktop_log_enabled(False)
        self.utils.write_desktop_log("駅名を含む行")
        self.assertFalse(os.path.exists(self.logfile()))

    def test_the_log_is_requested_only_by_the_exact_value_1(self):
        self.assertFalse(self.utils.desktop_log_requested({}))
        for value in ("0", "", "true", "yes", "2", " 1", "1 "):
            self.assertFalse(self.utils.desktop_log_requested({"TS_SCORING_DESKTOP_LOG": value}), value)
        self.assertTrue(self.utils.desktop_log_requested({"TS_SCORING_DESKTOP_LOG": "1"}))

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_managed_mode_switches_the_log_off_at_start_unless_asked_for(self):
        qt_app()
        import main
        for env, expected in ((None, False), ("1", True)):
            if env is None:
                os.environ.pop("TS_SCORING_DESKTOP_LOG", None)
            else:
                os.environ["TS_SCORING_DESKTOP_LOG"] = env
            self.utils.set_desktop_log_enabled(True)
            # run_managed reads its arguments first: an invalid managed command line returns before anything else, so call the same two lines the way it does
            main.utils.set_desktop_log_enabled(main.utils.desktop_log_requested())
            self.assertEqual(self.utils.desktop_log_enabled(), expected)
        src = ast.get_source_segment(read("main.py"), next(n for n in ast.parse(read("main.py")).body if isinstance(n, ast.FunctionDef) and n.name == "run_managed"))
        self.assertIn("utils.set_desktop_log_enabled(utils.desktop_log_requested())", src)
        self.assertLess(src.index("set_desktop_log_enabled"), src.index("QApplication(argv[:1])"))

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_a_whole_managed_scoring_session_writes_no_desktop_log(self):
        """The REAL write_desktop_log (not a recorder) with the managed default: scoring, an EB, a jump abort, the result screen - nothing reaches the Desktop."""
        qt_app()
        import main
        import sia_managed_rig as MR
        self.utils.set_desktop_log_enabled(False)
        r = MR.ManagedRig(main, capture_log=False)
        try:
            r.go_active(speed=5.0)
            r.start_scoring_via_menu()
            r.o.is_official_jumping = False
            r.send(MR.tele(1, speed=5.0, JUMP=2))
            r.tick(5)
            r.o.is_scoring_mode = True
            r.o.is_scoring_finished = True
            r.o.station_list = [R.station("駅名")]
            r.tick(3)
            r.hud.shutdown()
        finally:
            r.close()
        self.assertFalse(os.path.exists(self.logfile()), "a managed session wrote the Desktop log")

    @unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
    def test_the_same_session_with_the_log_asked_for_does_write_it(self):
        qt_app()
        import main
        import sia_managed_rig as MR
        self.utils.set_desktop_log_enabled(True)
        r = MR.ManagedRig(main, capture_log=False)
        try:
            r.go_active(speed=5.0)
            r.start_scoring_via_menu()
        finally:
            r.close()
        self.assertTrue(os.path.isfile(self.logfile()))

    def test_every_writer_of_the_log_is_behind_the_one_switch(self):
        """33 call sites of write_desktop_log (11 in main.py, 22 in scoring_logic.py) all go through utils.write_desktop_log; the only other writer
        (the limit diagnostic, off by default) checks the same switch; no other production code opens a file on the Desktop."""
        counts = {}
        for name in ("main.py", "scoring_logic.py", "hud_ui.py", "menu_ui.py", "utils.py", "managed_hud.py", "managed_input.py", "managed_mode.py",
                     "managed_state.py", "telemetry_contract.py", "telemetry_gate.py"):
            tree = ast.parse(read(name))
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ((isinstance(n.func, ast.Name) and n.func.id == "write_desktop_log")
                                                                           or (isinstance(n.func, ast.Attribute) and n.func.attr == "write_desktop_log"))]
            if calls:
                counts[name] = len(calls)
        self.assertEqual(counts, {"main.py": 11, "scoring_logic.py": 22})
        self.assertEqual(sum(counts.values()), 33)
        openers = {}
        for name in ("main.py", "scoring_logic.py", "hud_ui.py", "menu_ui.py", "utils.py", "managed_hud.py", "managed_input.py", "managed_mode.py",
                     "managed_state.py", "telemetry_contract.py", "telemetry_gate.py", "config.py"):
            tree = ast.parse(read(name))
            for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                text = ast.get_source_segment(read(name), func) or ""
                if re.search(r"\bopen\(", text) and ("Desktop" in text or "debug" in text.lower()):
                    openers.setdefault(name, []).append(func.name)
        self.assertEqual(openers, {"scoring_logic.py": ["write_limit_debug_log"], "utils.py": ["write_desktop_log"]})
        limit = ast.get_source_segment(read("scoring_logic.py"), next(n for n in ast.walk(ast.parse(read("scoring_logic.py"))) if isinstance(n, ast.FunctionDef) and n.name == "write_limit_debug_log"))
        self.assertIn("desktop_log_enabled()", limit)
        self.assertIn("enable_limit_debug_log", limit)
        self.assertEqual(read("main.py").count("enable_limit_debug_log"), 1)       # the switch is only initialised (False); nothing turns it on
        self.assertIn("self.enable_limit_debug_log = False", read("main.py"))

    def test_the_log_lines_of_the_managed_application_carry_no_names_or_paths(self):
        """The new diagnostic events are built from fixed words and numbers: no f-string interpolation of anything but numbers / fixed words."""
        text = read("managed_input.py")
        for call in re.findall(r'self\.note\(([^)]*)\)', text):
            self.assertNotIn("station", call.lower())
            self.assertNotIn("name", call.lower())
            self.assertNotIn("path", call.lower())

    # -- the senders and the Caller are not touched ----------------------------------------------------------------------------------------------
    def test_the_senders_the_bridges_the_caller_and_the_protocol_are_unchanged_since_si_a_started(self):
        # (the PowerShell test scripts and the Docs of TsScoringPlugin\Handshake are excluded: their scope guards were re-pinned and this phase has its own document)
        out = git("diff", "--name-only", BASELINE, "--", "TsScoringPlugin", ":(exclude)TsScoringPlugin/Handshake/Tests", ":(exclude)TsScoringPlugin/Handshake/Docs")
        if out is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        # Phase SI-A6 changes exactly these files (the load marker, Bridge -> Caller -> application) and nothing else under TsScoringPlugin: not the Current sender
        # (Class1.cs), not the Legacy / Current telemetry, not the projects, not the launcher, not the Caller's other sources.
        h = "TsScoringPlugin/Handshake/"
        allowed = {h + "Shared/HandshakeProtocol.cs", h + "Bridge/src/ScenarioReadyTracker.cs", h + "Bridge/src/ScenarioReadyPublisher.cs", h + "Bridge/src/AssemblyInfo.cs",
                   h + "Bridge/Legacy/src/AssemblyInfo.cs", h + "Caller/src/AppProcessManager.cs", h + "Caller/src/AppStatePublisher.cs",
                   h + "Caller/src/HandshakeSession.cs", h + "Caller/src/AssemblyInfo.cs"}
        self.assertEqual(set(out.split()), allowed, "SI-A (+ SI-A6) must not change anything else under TsScoringPlugin: %s" % out)
        untracked = git("ls-files", "--others", "--exclude-standard", "--", "TsScoringPlugin", ":(exclude)TsScoringPlugin/Handshake/Docs", ":(exclude)TsScoringPlugin/Handshake/Tests")
        self.assertEqual((untracked or "").strip(), "")

    def test_the_c_plus_plus_ddenGo_and_launcher_files_are_unchanged(self):
        out = git("diff", "--name-only", BASELINE, "--", ".", ":(exclude)tests", ":(exclude)*.py", ":(exclude)TsScoringPlugin")
        if out is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        changed = [l for l in out.splitlines() if l.strip() and not l.startswith("TsScoringPlugin/Handshake/Docs/")]
        self.assertEqual(changed, [])

    def test_no_legacy_or_atsex_branch_exists_in_the_python_production_code_that_si_a_added(self):
        text = read("managed_input.py").lower()
        for word in ("legacy", "atsex", "ats-ex", "bve5"):
            self.assertNotIn(word, text)
        out = git("diff", BASELINE, "--", "main.py", "managed_hud.py", "utils.py", "scoring_logic.py", "telemetry_gate.py")
        if out is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        added = [l[1:] for l in out.splitlines() if l.startswith("+") and not l.startswith("+++")]
        for line in added:
            for word in ("legacy", "atsex", "ats-ex", "bve5"):
                self.assertNotIn(word, line.lower(), line)

    def test_scoring_points_and_rules_are_unchanged(self):
        out = git("diff", BASELINE, "--", "scoring_logic.py", "config.py", "menu_ui.py", "hud_ui.py")
        if out is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        removed = [l for l in out.splitlines() if l.startswith("-") and not l.startswith("---")]
        self.assertEqual(removed, [l for l in removed if "from utils import" in l or l.strip("-").strip() in ("", ")")], removed)

    def test_the_scoring_function_bodies_are_ast_identical_to_the_baseline(self):
        old = git("show", BASELINE + ":scoring_logic.py")
        if old is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        new = read("scoring_logic.py")

        def functions(src):
            return {n.name: ast.dump(n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}

        a, b = functions(old.replace("\r\n", "\n")), functions(new)
        self.assertEqual(set(a), set(b))
        changed = sorted(n for n in a if a[n] != b[n])
        self.assertEqual(changed, ["write_limit_debug_log"])                    # only the diagnostic writer got the switch; no score, no rule, no constant

    def test_the_config_constants_are_identical_to_the_baseline(self):
        old = git("show", BASELINE + ":config.py")
        if old is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")
        self.assertEqual(ast.dump(ast.parse(old.replace("\r\n", "\n"))), ast.dump(ast.parse(read("config.py"))))


if __name__ == "__main__":
    unittest.main()
