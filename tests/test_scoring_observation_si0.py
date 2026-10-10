"""Phase SI-0 (scoring integration, read-only observation): CHARACTERIZATION of what the current production Python does, fixed BEFORE anything is connected.

Nothing in this file changes production code. It pins, with the AST and with the real Overlay (offscreen Qt, the Win32 / keyboard / time seams replaced by recorders):

  A. BCP is not a scoring input (the audit finding against the Phase L3 document).
  B. Which telemetry items the speed-limit score and the speed-limit guidance really depend on (MAPLIMITS / CLEARDIST are guidance only; the score reads MAPTAIL and
     SIGLIMIT) and where TRAINLEN is used.
  C. Every place that writes the Desktop debug log, and which of them can carry a station name.
  D. The path from the result-save dialog to the Stop request.
  E. The seams of Overlay.update_logic: the order of its parts, and the module level names it needs from outside (keyboard, win32gui, win32api, time, QApplication).
  F. The behaviour of the parts a later phase must keep identical when it moves them into the managed mode: Esc, window loss, P-to-P, the F7 / P / F8 key
     suppression, the "time and position" window, the fast-forward release (F8 injection), F11 and F12.
  G. What a change of the scenario generation discards TODAY, name by name, for the variables decision D-3 says must be discarded at a generation boundary.

When a later phase changes one of these on purpose, it updates the matching assertion in the same commit; until then this file is the specification the code is held to.
"""
import ast
import builtins
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

PRODUCTION = ["main.py", "scoring_logic.py", "hud_ui.py", "menu_ui.py", "utils.py", "config.py", "managed_hud.py", "managed_mode.py", "managed_state.py",
              "telemetry_contract.py", "telemetry_gate.py"]


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def tree(name):
    return ast.parse(read(name))


def functions(module_tree):
    """Every function / method of a module by (qualified) name."""
    out = {}
    for node in ast.walk(module_tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out["%s.%s" % (node.name, item.name)] = item
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
    return out


def attrs_of(func):
    """Names of every attribute read or written anywhere in the function (self.x -> x), plus every string given to getattr / setattr / hasattr (getattr(self, 'x') -> x)."""
    names = {n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)}
    for n in ast.walk(func):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("getattr", "setattr", "hasattr") and len(n.args) >= 2 \
                and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            names.add(n.args[1].value)
    return names


def source_of(name, func):
    return ast.get_source_segment(read(name), func)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class A_BcpIsNotAScoringInput(unittest.TestCase):
    def test_scoring_logic_never_mentions_the_brake_cylinder_pressure(self):
        text = read("scoring_logic.py")
        self.assertNotIn("bcPressure", text)
        self.assertNotIn("BCP", text)
        self.assertNotIn("bcp", text.lower())                             # not even as a word

    def test_the_only_readers_of_bcPressure_are_the_telemetry_intake_and_the_hud_diagnostic_row(self):
        users = {name for name in PRODUCTION if "bcPressure" in read(name)}
        self.assertEqual(users, {"main.py", "hud_ui.py", "telemetry_contract.py"})
        main_lines = [l.strip() for l in read("main.py").splitlines() if "bcPressure" in l]
        self.assertEqual(main_lines, ["self.bcPressure = 0.0", 'elif part.startswith("BCP:"): self.bcPressure = float(part.split(\':\')[1])'])
        contract = [l.strip() for l in read("telemetry_contract.py").splitlines() if "bcPressure" in l]
        self.assertEqual(len(contract), 1)                  # the default of the telemetry state, nothing else
        hud_lines = [l.strip() for l in read("hud_ui.py").splitlines() if "bcPressure" in l]
        self.assertEqual(hud_lines, ['pressure_parts.append(f"BCP: {self.bcPressure:.1f} kPa")'])

    def test_the_hud_row_is_a_diagnostic_text_behind_the_bcp_item(self):
        src = read("hud_ui.py")
        i = src.index("bcPressure")
        window = src[max(0, i - 400):i + 100]
        self.assertIn('hud_data_available(self, "bcp")', window)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class B_WhatTheSpeedLimitScoreAndTheGuidanceNeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fn = functions(tree("scoring_logic.py"))

    def test_the_speed_limit_score_reads_effective_limit_speed_and_the_user_setting_only(self):
        a = attrs_of(self.fn["update_speed_limit_penalty"])
        for needed in ("effective_limit", "bve_speed", "pen_limit", "is_scoring_mode", "is_scoring_finished", "is_official_jumping", "is_first_udp"):
            self.assertIn(needed, a)
        for forbidden in ("bve_map_limits", "bve_clear_dist", "map_head_limit", "map_tail_limit", "bve_train_length", "bve_fwd_sig_limit", "bve_fwd_sig_loc",
                          "bve_signal_limit", "bve_calc_g"):
            self.assertNotIn(forbidden, a)

    def test_effective_limit_is_the_smaller_of_MAPTAIL_and_SIGLIMIT(self):
        src = source_of("scoring_logic.py", self.fn["update_physics_and_scoring"])
        for line in ("rnd_tail_limit = round(self.map_tail_limit, 1)", "rnd_sig_limit  = round(self.bve_signal_limit, 1)", "true_map_limit = rnd_tail_limit",
                     "self.effective_limit = min(true_map_limit, rnd_sig_limit)"):
            self.assertIn(line, src)

    def test_the_limit_penalty_default_is_on(self):
        self.assertIn("self.pen_limit = True", read("main.py"))
        self.assertIn("getattr(self, 'pen_limit', True)", source_of("scoring_logic.py", self.fn["update_speed_limit_penalty"]))

    def test_MAPLIMITS_and_CLEARDIST_feed_only_the_guidance_of_update_physics_and_scoring(self):
        users = {}
        for name in ("scoring_logic.py", "main.py", "hud_ui.py", "menu_ui.py", "utils.py"):
            for q, f in functions(tree(name)).items():
                for attr in ("bve_map_limits", "bve_clear_dist"):
                    if attr in attrs_of(f):
                        users.setdefault(attr, set()).add("%s:%s" % (name, q))
        self.assertEqual(users["bve_map_limits"], {"scoring_logic.py:update_physics_and_scoring", "main.py:Overlay.__init__", "main.py:Overlay.apply_telemetry_text"})
        self.assertEqual(users["bve_clear_dist"], {"scoring_logic.py:update_physics_and_scoring", "scoring_logic.py:write_limit_debug_log", "main.py:Overlay.__init__", "main.py:Overlay.apply_telemetry_text"})

    def test_the_guidance_block_never_touches_the_score(self):
        src = source_of("scoring_logic.py", self.fn["update_physics_and_scoring"])
        start = src.index("future_targets = []")
        end = src.index("write_limit_debug_log(")
        block = src[start:end]
        for forbidden in ("self.score", "score_details", "add_score_popup", "accumulated_speed_penalty", "popups"):
            self.assertNotIn(forbidden, block)
        for guidance_output in ("self.disp_limit", "self.limit_color", "self.blink_active", "self.target_type"):
            self.assertIn(guidance_output, block)

    def test_MAPHEAD_matters_only_to_the_guidance_too(self):
        users = set()
        for q, f in functions(tree("scoring_logic.py")).items():
            if "map_head_limit" in attrs_of(f):
                users.add(q)
        self.assertEqual(users, {"update_physics_and_scoring", "write_limit_debug_log"})

    def test_train_length_decides_the_stop_range_and_the_guidance(self):
        users = {q for q, f in functions(tree("scoring_logic.py")).items() if "bve_train_length" in attrs_of(f)}
        self.assertEqual(users, {"evaluate_arrival", "update_physics_and_scoring"})      # the stop range (arrival) and the speed-limit guidance
        text = read("scoring_logic.py")
        self.assertEqual(text.count("self.bve_train_length + STATION_MARGIN"), 3)
        self.assertEqual(text.count("getattr(self, 'setting_stop_distance', -1) if getattr(self, 'setting_stop_distance', -1) != -1"), 3)
        main = read("main.py")
        self.assertIn("self.setting_stop_distance = round(int(self.bve_train_length) * 1.1)", main)
        self.assertIn("self.bve_train_length = max(float(part.split(':')[1]), 20.0)", main)
        self.assertIn("self.bve_train_length = 20.0", main)

    def test_the_shared_vocabulary_names_the_two_groups_separately(self):
        import telemetry_contract as tc
        self.assertEqual(tc.TOKEN_KEYS["maplimit"], ("MAPHEAD", "MAPTAIL"))
        self.assertEqual(tc.TOKEN_KEYS["maplimit_ahead"], ("MAPLIMITS", "CLEARDIST"))
        self.assertEqual(tc.TOKEN_KEYS["trainlen"], ("TRAINLEN",))


# ----------------------------------------------------------------------------------------------------------------------------------------------
class C_EveryWriterOfTheDesktopDebugLog(unittest.TestCase):
    @staticmethod
    def calls(name, callee):
        out = []
        for node in ast.walk(tree(name)):
            if isinstance(node, ast.Call):
                f = node.func
                if (isinstance(f, ast.Name) and f.id == callee) or (isinstance(f, ast.Attribute) and f.attr == callee):
                    out.append(node)
        return out

    def test_the_call_sites_of_write_desktop_log_by_file(self):
        counts = {name: len(self.calls(name, "write_desktop_log")) for name in PRODUCTION}
        self.assertEqual({k: v for k, v in counts.items() if v}, {"main.py": 11, "scoring_logic.py": 22})
        self.assertEqual(counts["managed_hud.py"] + counts["managed_mode.py"] + counts["managed_state.py"] + counts["hud_ui.py"], 0)

    def test_the_log_function_has_one_switch_and_swallows_every_error(self):
        """SI-0 recorded: unconditional, no switch. Phase SI-A (on purpose): ONE module switch, on by default (normal mode unchanged), switched off by managed
        mode at its start unless TS_SCORING_DESKTOP_LOG=1; nothing else about the function changed."""
        src = read("utils.py")
        i = src.index("def write_desktop_log")
        body = src[i:src.index("def get_outline_color")]
        self.assertIn('os.path.join(os.path.expanduser("~"), "Desktop")', body)
        self.assertIn('"debug.log"', body)
        self.assertIn('open(log_file, "a", encoding="utf-8")', body)
        self.assertEqual(body.count("if "), 1)
        self.assertIn("if not _desktop_log_enabled:\n        return\n", body.replace("\r\n", "\n"))         # the one switch, before anything is touched
        self.assertIn("_desktop_log_enabled = True", src)                # on by default: the normal mode is unchanged
        self.assertIn("except:", body)

    def test_the_limit_debug_log_is_off_by_default_and_writes_the_same_file(self):
        self.assertIn("self.enable_limit_debug_log = False", read("main.py"))
        src = source_of("scoring_logic.py", functions(tree("scoring_logic.py"))["write_limit_debug_log"])
        self.assertIn("if not getattr(self, 'enable_limit_debug_log', False):", src)
        self.assertIn('"Desktop"', src)
        self.assertIn('"Debug.log"', src)         # the same file as debug.log on Windows (case-insensitive)

    def test_only_two_sites_can_carry_a_station_name(self):
        carrying = []
        for name in ("main.py", "scoring_logic.py"):
            for call in self.calls(name, "write_desktop_log"):
                text = ast.get_source_segment(read(name), call)
                if "name" in text and ("get('name'" in text or 'get("name"' in text):
                    carrying.append((name, text.split("\n")[1].strip() if "\n" in text else text))
        self.assertEqual(len(carrying), 2)
        self.assertEqual(sorted(t for _, t in carrying), sorted(['f"[SAVE] 開扉時間を反映: "', '"[TIMING FALLBACK]\\n"']))

    def test_the_dead_network_module_is_imported_by_nobody(self):
        for name in PRODUCTION:
            text = read(name)
            self.assertNotIn("import network", text)
            self.assertNotIn("from network", text)

    def test_the_log_is_written_to_the_desktop_folder_of_the_profile(self):
        import utils
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "Desktop"))
            saved = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
            os.environ["USERPROFILE"] = home
            os.environ["HOME"] = home
            try:
                utils.write_desktop_log("first line")
                utils.write_desktop_log("second line")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            path = os.path.join(home, "Desktop", "debug.log")
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertRegex(lines[0], r"^\[\d\d:\d\d:\d\d\.\d{3}\] first line$")

    def test_without_a_desktop_folder_nothing_is_written_and_nothing_is_raised(self):
        import utils
        with tempfile.TemporaryDirectory() as home:
            saved = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
            os.environ["USERPROFILE"] = home
            os.environ["HOME"] = home
            try:
                utils.write_desktop_log("nobody reads this")
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertEqual(os.listdir(home), [])


# ----------------------------------------------------------------------------------------------------------------------------------------------
class D_TheResultSaveDialogAndTheStopRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_src = read("main.py")
        cls.main_tree = ast.parse(cls.main_src)
        cls.fn = functions(cls.main_tree)

    def callers_of(self, method):
        out = set()
        for q, f in self.fn.items():
            for node in ast.walk(f):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method:
                    out.add(q)
        return out

    def test_the_dialog_has_exactly_one_call_site_and_one_path_to_it(self):
        self.assertEqual(self.main_src.count("QFileDialog.getSaveFileName"), 1)
        self.assertEqual(self.callers_of("take_result_screenshot"), {"Overlay.handle_menu_enter"})
        self.assertEqual(self.callers_of("handle_menu_enter"), {"Overlay._handle_mouse", "Overlay._handle_keys"})      # parts of the shared step (SI-A2); the step has one entry per mode
        for name in PRODUCTION:
            if name != "main.py":
                self.assertNotIn("QFileDialog", read(name))

    def test_the_managed_modules_cannot_reach_the_dialog_today(self):
        for name in ("managed_hud.py", "managed_mode.py", "managed_state.py"):
            t = tree(name)
            identifiers = {n.id for n in ast.walk(t) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(t) if isinstance(n, ast.Attribute)}
            for needle in ("update_logic", "handle_menu_enter", "take_result_screenshot", "QFileDialog"):
                self.assertNotIn(needle, identifiers, name)
        run_managed = ast.get_source_segment(self.main_src, self.fn["run_managed"])
        self.assertIn("overlay.timer.stop()", run_managed)
        identifiers = {n.id for n in ast.walk(self.fn["run_managed"]) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(self.fn["run_managed"]) if isinstance(n, ast.Attribute)}
        self.assertNotIn("update_logic", identifiers)                        # named in comments only

    def test_before_the_dialog_only_two_of_the_four_hook_groups_are_released(self):
        src = ast.get_source_segment(self.main_src, self.fn["Overlay.take_result_screenshot"])
        self.assertNotIn("QFileDialog", src)                              # Phase SI-A: the dialog call moved into Overlay.ask_result_save_path (managed mode replaces it)
        self.assertEqual(ast.get_source_segment(self.main_src, self.fn["Overlay.ask_result_save_path"]).count("QFileDialog.getSaveFileName"), 1)
        dialog = src.index("self.ask_result_save_path(")
        before = src[:dialog]
        self.assertIn("getattr(self, 'hook_dict', {}).values()", before)
        self.assertIn("getattr(self, 'sys_hook_dict', {}).values()", before)
        self.assertNotIn("f8_hook_dict", src)
        self.assertNotIn("numeric_router_hook", src)

    def test_the_stop_request_reaches_the_ui_thread_as_a_queued_quit(self):
        bridge = ast.get_source_segment(self.main_src, next(n for n in self.main_tree.body if isinstance(n, ast.ClassDef) and n.name == "_ManagedShutdownBridge"))
        self.assertIn("shutdown_requested = pyqtSignal()", bridge)
        self.assertIn("QApplication.quit()", bridge)
        run_managed = ast.get_source_segment(self.main_src, self.fn["run_managed"])
        self.assertIn("life.start_stop_watch(bridge.shutdown_requested.emit)", run_managed)
        self.assertIn("result = life.shutdown(cleanup)", run_managed)
        # the clean-up runs AFTER app.exec() returned; a modal native dialog that keeps exec() from returning is exactly the open question of a later live test
        self.assertLess(run_managed.index("app.exec()"), run_managed.index("life.shutdown(cleanup)"))

    def test_the_clean_up_releases_the_hooks_but_not_the_time_and_position_window(self):
        cleanup = ast.get_source_segment(self.main_src, self.fn["_release_overlay"])
        for name in ("hook_dict", "sys_hook_dict", "f8_hook_dict", "numeric_router_hook"):
            self.assertIn(name, cleanup)
        self.assertNotIn("EnableWindow", cleanup)
        self.assertNotIn("FindWindow", cleanup)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class E_TheSeamsOfUpdateLogic(unittest.TestCase):
    # Phase SI-A2 cut update_logic into these methods, without changing a statement. They are listed in the order in which the original single function
    # executed its parts: every test below that was written for the single function now reads the concatenation of these bodies in that order.
    PARTS = ["update_logic", "_kick_start_first_press", "_follow_bve_window", "_run_input_and_scoring_step", "_detect_and_release_fast_forward",
             "_resolve_bve_advancing", "_kick_start_second_press", "_sync_system_key_suppression", "_sync_f8_suppression",
             "_sync_time_position_window_lock", "_sync_menu_key_suppression", "_sync_numeric_input", "_handle_mouse", "_handle_keys",
             "_restore_standard_window", "_advance_scoring_clock_and_score"]

    @classmethod
    def setUpClass(cls):
        cls.main_src = read("main.py")
        funcs = functions(ast.parse(cls.main_src))
        cls.funcs = {n: funcs["Overlay." + n] for n in cls.PARTS}
        cls.func = cls.funcs["update_logic"]
        cls.src = "\n".join(ast.get_source_segment(cls.main_src, cls.funcs[n]) for n in cls.PARTS)

    def test_the_step_calls_its_parts_in_the_order_of_the_original_function(self):
        step = self.funcs["_run_input_and_scoring_step"]
        called = [n.func.attr for n in sorted((n for n in ast.walk(step) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"), key=lambda n: (n.lineno, n.col_offset))]
        self.assertEqual(called, ["_detect_and_release_fast_forward", "_resolve_bve_advancing", "_kick_start_second_press", "_sync_system_key_suppression",
                                  "_sync_f8_suppression", "_sync_time_position_window_lock", "_sync_menu_key_suppression", "_sync_numeric_input",
                                  "_handle_mouse", "_handle_keys", "_advance_scoring_clock_and_score"])
        head = self.funcs["update_logic"]
        called = [n.func.attr for n in sorted((n for n in ast.walk(head) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"), key=lambda n: (n.lineno, n.col_offset))]
        self.assertEqual([c for c in called if c.startswith("_")], ["_kick_start_first_press", "_follow_bve_window", "_run_input_and_scoring_step"])

    def test_the_parts_run_in_this_order(self):
        markers = [
            "if keyboard.is_pressed('esc'): QApplication.quit()",          # Esc quits (normal mode only)
            "self.bve_hwnd = self.find_bve_window()",                      # window search by title over all processes
            "if self.was_bve_found and self.bve_hwnd is None:",           # the BVE window disappeared (then QApplication.quit())
            "write_desktop_log(\"[MAIN] BVEの凍結を確認。キックスタートを実行します。\")",
            "win32gui.SetWindowLong(int(self.winId()), win32con.GWL_HWNDPARENT, self.bve_hwnd)",
            "self.setGeometry(client_x, client_y, w, h)",
            "real_now = time.time()",                                      # fast-forward detection
            "win32api.PostMessage(self.bve_hwnd, win32con.WM_KEYDOWN, 0x77, 0) # F8",
            "is_bve_advancing = ('RUNNING' in self.bve_actual_state)",
            "if getattr(self, 'auto_pause_pending', False) and getattr(self, 'station_list', []):",
            "sys_block_keys = ['f7', 'p']",
            "should_block_f8 = ",
            'diag_hwnd = win32gui.FindWindow(None, "時刻と位置")',
            "should_block_keys = (self.menu_state != 0) and is_bve_active",
            "self.numeric_router_hook = keyboard.hook(self.numeric_router.on_event, suppress=True)",
            "numeric_events = self.numeric_router.drain()",
            "is_left_clicked = ",
            "for zone in self.menu_click_zones:",
            "for key in self.key_states.keys():",
            "if key == 'f1':",
            "elif key == 'f2':",
            "elif key == 'f11':",
            "elif key == 'f12':",
            "reset_transient_scoring_state(self)",
            "update_physics_and_scoring(self, current_time, dt)",
            "self.update()",
        ]
        last = -1
        for m in markers:
            i = self.src.find(m)
            self.assertGreater(i, last, "out of order or missing: %r" % m)
            last = i

    def test_the_module_level_names_update_logic_needs_from_outside(self):
        external = set()
        for func in self.funcs.values():
            local = {a.arg for a in func.args.args}
            for node in ast.walk(func):
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    local.add(node.id)
                if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                    args = node.args
                    local.update(a.arg for a in args.args)
                if isinstance(node, ast.ExceptHandler) and node.name:
                    local.add(node.name)
            loaded = {n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            external |= {n for n in loaded - local if not hasattr(builtins, n)}
        self.assertEqual(external, {"QApplication", "keyboard", "win32gui", "win32api", "win32con", "time", "write_desktop_log", "reset_transient_scoring_state",
                                    "update_physics_and_scoring", "BASE_SCREEN_W", "BASE_SCREEN_H"})

    def test_there_is_no_other_caller_of_update_logic_than_the_timer(self):
        t = ast.parse(read("main.py"))
        references = [n for n in ast.walk(t) if isinstance(n, ast.Attribute) and n.attr == "update_logic"]
        self.assertEqual(len(references), 1)                              # the timer connection; everything else that names it is a comment or a docstring
        self.assertIn("self.timer.timeout.connect(self.update_logic)", read("main.py"))

    def test_the_tracked_keys(self):
        i = self.main_src.index("keys_to_track = ")
        line = self.main_src[i:self.main_src.index("\n", i)]
        self.assertEqual(ast.literal_eval(line.split("= ", 1)[1]), ['a', 'f1', 'f2', 'f5', 'f8', 'f11', 'f12', 'p', 'up', 'down', 'left', 'right', 'enter', 'backspace', 'h'])
        for dead in ("f5", "'p'"):                                         # tracked, but no branch of the key loop handles them
            self.assertNotIn("key == " + dead, self.src)
        for handled in ("key == 'f1'", "key == 'f2'", "key == 'f11'", "key == 'f12'", "key == 'h' and self.menu_state != 0", "key == 'a' and self.menu_state == 8"):
            self.assertIn(handled, self.src)

    def test_f12_has_one_call_site_and_shares_the_state_with_f11(self):
        self.assertEqual(self.main_src.count("standard_style = win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE"), 1)
        self.assertIn("elif key == 'f12':\n                    self._restore_standard_window()", self.src.replace("\r\n", "\n"))
        f12 = ast.get_source_segment(self.main_src, self.funcs["_restore_standard_window"])
        self.assertIn("self.is_borderless_fullscreen = False", f12)
        self.assertIn("win32gui.SetWindowPos(self.bve_hwnd, 0, 100, 100, 1280, 720,", f12)
        self.assertIn("win32con.SC_RESTORE", f12)
        toggle = ast.get_source_segment(self.main_src, functions(ast.parse(self.main_src))["Overlay.toggle_borderless_fullscreen"])
        for shared in ("is_borderless_fullscreen", "bve_original_style", "bve_original_placement"):
            self.assertIn(shared, toggle)


# ----------------------------------------------------------------------------------------------------------------------------------------------
class FakeKeyboard:
    def __init__(self):
        self.pressed = set()
        self.hooks = []
        self.unhooked = []
        self.counter = 0

    def is_pressed(self, key):
        return key in self.pressed

    def on_press_key(self, key, callback, suppress=False):
        self.counter += 1
        handle = ("key", key, bool(suppress), self.counter)
        self.hooks.append(handle)
        return handle

    def hook(self, callback, suppress=False):
        self.counter += 1
        handle = ("hook", None, bool(suppress), self.counter)
        self.hooks.append(handle)
        return handle

    def unhook(self, handle):
        self.unhooked.append(handle)

    def active(self):
        return sorted(h[1] if h[0] == "key" else "<all>" for h in self.hooks if h not in self.unhooked)


class FakeGui:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.foreground = hwnd
        self.diag = 0                       # the hwnd of the "time and position" window, 0 = none
        self.enabled = True
        self.calls = []

    def IsWindow(self, h):
        return h == self.hwnd

    def GetForegroundWindow(self):
        return self.foreground

    def IsIconic(self, h):
        return False

    def GetClientRect(self, h):
        return (0, 0, 1920, 1080)

    def ClientToScreen(self, h, pt):
        return (0, 0)

    def FindWindow(self, cls, title):
        return self.diag if title == "時刻と位置" else 0

    def IsWindowEnabled(self, h):
        return self.enabled

    def EnableWindow(self, h, flag):
        self.calls.append(("EnableWindow", h, bool(flag)))
        self.enabled = bool(flag)

    def GetCursorPos(self):
        return (0, 0)

    def SetWindowLong(self, h, index, value):
        self.calls.append(("SetWindowLong", h, index, value))

    def SendMessage(self, h, msg, w, l):
        self.calls.append(("SendMessage", h, msg, w, l))

    def SetWindowPos(self, *args):
        self.calls.append(("SetWindowPos",) + args)

    def GetWindowLong(self, h, index):
        return 0x14CF0000

    def GetWindowPlacement(self, h):
        return (0, 1, (0, 0), (0, 0), (100, 100, 1380, 820))

    def __getattr__(self, name):             # any other call is recorded and answers None
        def recorder(*args):
            self.calls.append((name,) + args)
        return recorder


class FakeApi:
    def __init__(self):
        self.posted = []

    def PostMessage(self, h, msg, w, l):
        self.posted.append((h, msg, w, l))

    def GetAsyncKeyState(self, key):
        return 0


class FakeTime:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


class StubSignal:
    def connect(self, slot):
        self.slot = slot


class StubUdp:
    """Stands in for QUdpSocket: the characterization never binds UDP 54321, so it can run next to a live TS Scoring without touching its datagrams."""
    def __init__(self, parent=None):
        self.readyRead = StubSignal()
        self.written = []

    def bind(self, address, port):
        return True

    def hasPendingDatagrams(self):
        return False

    def writeDatagram(self, data, address, port):
        self.written.append((bytes(data), port))

    def close(self):
        return None


class FakeApp:
    quits = 0

    @classmethod
    def quit(cls):
        cls.quits += 1

    @staticmethod
    def processEvents():
        return None


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class F_UpdateLogicCharacterization(unittest.TestCase):
    """The real Overlay (offscreen) with every outside effect replaced by a recorder. The Overlay never touches the real keyboard, a real window, the real clock or UDP 54321."""
    HWND = 4242

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["si0"])
        import main
        cls.main = main

    def setUp(self):
        m = self.main
        self.saved = {n: getattr(m, n) for n in ("keyboard", "win32gui", "win32api", "time", "QApplication", "QTimer", "QUdpSocket", "write_desktop_log")}
        self.kb, self.gui, self.api, self.clock = FakeKeyboard(), FakeGui(self.HWND), FakeApi(), FakeTime()
        self.log = []
        FakeApp.quits = 0
        m.keyboard, m.win32gui, m.win32api, m.time, m.QApplication, m.QUdpSocket = self.kb, self.gui, self.api, self.clock, FakeApp, StubUdp
        m.write_desktop_log = lambda msg, *a, **k: self.log.append(msg)
        self.o = m.Overlay()
        self.o.timer.stop()
        o = self.o
        o.bve_hwnd = self.HWND
        o.is_linked = True
        o.was_bve_found = True
        o.menu_state = 0
        o.bve_actual_state = "RUNNING"

    def tearDown(self):
        m = self.main
        for n, v in self.saved.items():
            setattr(m, n, v)
        try:
            self.o.udp_socket.close()
            self.o.close()
            self.o.deleteLater()
        except Exception:
            pass

    @staticmethod
    def station(name):
        return {"name": name, "is_timing": True, "location": 1000.0, "raw_arr": -1, "raw_dep": -1, "def_time": -1, "stop_time": 15000, "is_pass": False, "is_terminal": False}

    def tick(self, n=1):
        for _ in range(n):
            self.o.update_logic()

    # -- Esc, window loss ---------------------------------------------------------------------------------------------------------------
    def test_esc_quits_the_application_in_normal_mode(self):
        self.kb.pressed.add("esc")
        self.tick()
        self.assertEqual(FakeApp.quits, 1)

    def test_losing_the_bve_window_after_it_was_found_quits(self):
        self.gui.hwnd = 0                                  # IsWindow(4242) is now False
        self.gui.EnumWindows = lambda cb, extra: None      # no window carries the title any more
        self.tick()
        self.assertEqual(FakeApp.quits, 1)
        self.assertFalse(self.o.is_bve_loaded)

    def test_a_window_that_was_never_found_does_not_quit(self):
        self.o.was_bve_found = False
        self.gui.hwnd = 0
        self.gui.EnumWindows = lambda cb, extra: None
        self.o.bve_hwnd = None
        self.tick()
        self.assertEqual(FakeApp.quits, 0)

    # -- P to P (the kick start) ---------------------------------------------------------------------------------------------------------
    def test_pause_at_start_with_no_station_list_posts_P_once_and_the_second_P_when_time_runs(self):
        o = self.o
        o.is_bve_loaded = True
        o.station_list = []
        o.bve_actual_state = "PAUSED"
        o.initial_kickstart_done = False
        o.bve_time_ms = 36000000
        self.tick()
        P = 0x50
        self.assertEqual(self.api.posted, [(self.HWND, self.main.win32con.WM_KEYDOWN, P, 0), (self.HWND, self.main.win32con.WM_KEYUP, P, 0)])
        self.assertTrue(o.auto_pause_pending)
        self.assertTrue(o.initial_kickstart_done)
        self.assertEqual(o.bve_actual_state, "RUNNING")
        self.assertIn("[MAIN] BVEの凍結を確認。キックスタートを実行します。", self.log)
        self.api.posted.clear()
        self.tick()
        self.assertEqual(self.api.posted, [])                               # no station list yet: no second P
        o.station_list = [self.station("S")]
        o.bve_time_ms += 500                                                # the BVE time advanced
        self.tick()
        self.assertEqual(len(self.api.posted), 2)                           # the pausing P
        self.assertFalse(o.auto_pause_pending)

    def test_a_station_list_left_over_from_an_earlier_scenario_suppresses_the_kick_start(self):
        o = self.o
        o.is_bve_loaded = True
        o.station_list = [self.station("left over")]
        o.bve_actual_state = "PAUSED"
        o.initial_kickstart_done = False
        self.tick()
        self.assertEqual(self.api.posted, [])
        self.assertFalse(getattr(o, "auto_pause_pending", False))

    def test_already_running_only_marks_the_kick_start_done(self):
        o = self.o
        o.is_bve_loaded = True
        o.station_list = []
        o.bve_actual_state = "RUNNING"
        o.initial_kickstart_done = False
        self.tick()
        self.assertEqual(self.api.posted, [])
        self.assertTrue(o.initial_kickstart_done)

    # -- F7 / P suppression ----------------------------------------------------------------------------------------------------------------
    def scoring(self, speed=0.0, finished=False):
        o = self.o
        o.is_scoring_mode = True
        o.is_scoring_finished = finished
        o.bve_speed = speed

    def test_scoring_in_front_suppresses_F7_and_P_but_not_F8_at_a_standstill(self):
        self.scoring(speed=0.0)
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])
        self.assertTrue(all(h[2] for h in self.kb.hooks))                   # every hook suppresses
        self.assertTrue(self.o.sys_keys_blocked)

    def test_scoring_while_running_also_suppresses_F8(self):
        self.scoring(speed=5.0)
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        self.assertTrue(self.o.f8_physically_blocked)

    def test_the_hooks_are_not_registered_when_the_BVE_window_is_not_in_front(self):
        self.scoring(speed=5.0)
        self.gui.foreground = 1
        self.tick()
        self.assertEqual(self.kb.active(), [])

    def test_F8_is_not_suppressed_when_the_debug_flag_is_off(self):
        self.scoring(speed=5.0)
        self.o.F8_disable = False
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "p"])

    def test_the_suppression_ends_the_moment_the_scoring_is_finished_or_the_window_loses_the_front(self):
        self.scoring(speed=5.0)
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        self.o.is_scoring_finished = True
        self.tick()
        self.assertEqual(self.kb.active(), [])
        self.assertFalse(self.o.sys_keys_blocked)
        self.assertFalse(self.o.f8_physically_blocked)
        self.o.is_scoring_finished = False
        self.tick()
        self.assertEqual(self.kb.active(), ["f7", "f8", "p"])
        self.gui.foreground = 1
        self.tick()
        self.assertEqual(self.kb.active(), [])

    def test_an_open_menu_suppresses_F7_and_P_and_the_menu_keys_without_scoring(self):
        self.o.menu_state = 1
        self.tick()
        active = self.kb.active()
        for key in ("f7", "p", "f8", "up", "down", "left", "right", "enter", "backspace", "h", "0", "9"):
            self.assertIn(key, active)
        self.assertIn("<all>", active)                                      # the numeric-input router (a global hook)
        self.o.menu_state = 0
        self.tick()
        self.assertEqual(self.kb.active(), [])

    # -- the "time and position" window -----------------------------------------------------------------------------------------------------
    def test_the_time_and_position_window_is_disabled_while_scoring_and_enabled_again_after(self):
        self.gui.diag = 777
        self.scoring(speed=0.0)
        self.tick()
        self.assertIn(("EnableWindow", 777, False), self.gui.calls)
        self.gui.calls.clear()
        self.tick()
        self.assertEqual(self.gui.calls, [])                                # only a CHANGE is applied, never every frame
        self.o.is_scoring_finished = True
        self.tick()
        self.assertEqual(self.gui.calls, [("EnableWindow", 777, True)])

    def test_the_window_is_left_alone_when_there_is_no_scoring_and_no_menu(self):
        self.gui.diag = 777
        self.tick()
        self.assertEqual(self.gui.calls, [])

    def test_the_window_is_disabled_by_the_open_menu_too(self):
        self.gui.diag = 777
        self.o.menu_state = 1
        self.tick()
        self.assertIn(("EnableWindow", 777, False), self.gui.calls)

    # -- the fast-forward release ------------------------------------------------------------------------------------------------------------
    def fast_forward(self, bve_ms=1000):
        o = self.o
        self.tick()                                                         # the first tick only sets the reference
        self.clock.now += 0.06                                              # 60 ms later ...
        o.bve_time_ms += bve_ms                                             # ... the BVE clock moved by a second (about 16 times real time)
        self.tick()

    def test_fast_forward_while_driving_in_a_scoring_run_posts_F8(self):
        self.scoring(speed=5.0)
        self.fast_forward()
        F8 = 0x77
        self.assertEqual([p for p in self.api.posted if p[2] == F8], [(self.HWND, self.main.win32con.WM_KEYDOWN, F8, 0), (self.HWND, self.main.win32con.WM_KEYUP, F8, 0)])
        self.assertIn("[MAIN] 走行中の早送りを検知しました。強制解除(等倍速戻し)を実行します。", self.log)
        self.assertFalse(self.o.is_fast_forwarding)

    def test_the_threshold_is_ten_times_not_five(self):
        self.scoring(speed=5.0)
        self.tick()
        self.clock.now += 0.125                                             # (binary fractions: the ratios below are exact)
        self.o.bve_time_ms += 1000                                          # 8 times real time
        self.tick()
        self.assertFalse(self.o.is_fast_forwarding)
        self.assertEqual([p for p in self.api.posted if p[2] == 0x77], [])
        self.clock.now += 0.125
        self.o.bve_time_ms += 1250                                          # exactly 10 times real time
        self.tick()
        self.assertEqual(len([p for p in self.api.posted if p[2] == 0x77]), 2)

    def test_no_release_at_a_standstill_after_the_scoring_or_while_an_official_jump_runs(self):
        for setup in (lambda: self.scoring(speed=0.0), lambda: self.scoring(speed=5.0, finished=True), lambda: (self.scoring(speed=5.0), setattr(self.o, "is_official_jumping", True))):
            self.api.posted.clear()
            self.o.is_fast_forwarding = False
            self.o.ff_check_real_time = 0.0
            setup()
            self.fast_forward()
            self.assertEqual([p for p in self.api.posted if p[2] == 0x77], [])

    def test_no_release_without_scoring(self):
        self.o.bve_speed = 5.0
        self.fast_forward()
        self.assertEqual([p for p in self.api.posted if p[2] == 0x77], [])

    # -- F11 / F12 -----------------------------------------------------------------------------------------------------------------------------
    def test_F11_toggles_the_borderless_state_only_with_the_BVE_window_in_front(self):
        calls = []
        self.o.toggle_borderless_fullscreen = lambda: calls.append("toggle")
        self.kb.pressed.add("f11")
        self.gui.foreground = 1
        self.tick()
        self.assertEqual(calls, [])
        self.gui.foreground = self.HWND
        self.tick()
        self.assertEqual(calls, [])                                         # the key was already held while another window was in front: it does not fire when BVE comes back
        self.kb.pressed.discard("f11")
        self.tick()
        self.kb.pressed.add("f11")
        self.tick()
        self.assertEqual(calls, ["toggle"])
        self.tick()
        self.assertEqual(calls, ["toggle"])                                 # held key: once

    def test_F11_works_without_scoring_and_without_a_menu(self):
        self.assertFalse(self.o.is_scoring_mode)
        calls = []
        self.o.toggle_borderless_fullscreen = lambda: calls.append("toggle")
        self.kb.pressed.add("f11")
        self.tick()
        self.assertEqual(calls, ["toggle"])

    def test_F11_remembers_the_original_style_and_placement_and_F11_again_restores_them(self):
        self.main.QTimer = type("T", (), {"singleShot": staticmethod(lambda ms, fn: fn())})
        self.main.win32api.MonitorFromWindow = lambda h, flag: 1
        self.main.win32api.GetMonitorInfo = lambda mon: {"Monitor": (0, 0, 1920, 1080)}
        try:
            self.o.toggle_borderless_fullscreen()
        finally:
            pass
        self.assertEqual(self.o.bve_original_style, 0x14CF0000)
        self.assertEqual(self.o.bve_original_placement[4], (100, 100, 1380, 820))
        self.assertTrue(self.o.is_borderless_fullscreen)
        self.gui.calls.clear()
        self.o.toggle_borderless_fullscreen()
        self.assertFalse(self.o.is_borderless_fullscreen)
        kinds = [c[0] for c in self.gui.calls]
        self.assertEqual(kinds, ["SetWindowLong", "SetWindowPos", "SetWindowPlacement"])

    def test_F12_forces_the_standard_window_whatever_the_state_was(self):
        con = self.main.win32con
        self.o.is_borderless_fullscreen = True
        self.kb.pressed.add("f12")
        self.tick()
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertIn(("SetWindowLong", self.HWND, con.GWL_STYLE, con.WS_OVERLAPPEDWINDOW | con.WS_VISIBLE), self.gui.calls)
        self.assertIn(("SendMessage", self.HWND, con.WM_SYSCOMMAND, con.SC_RESTORE, 0), self.gui.calls)
        self.assertIn(("SetWindowPos", self.HWND, 0, 100, 100, 1280, 720, con.SWP_NOZORDER | con.SWP_FRAMECHANGED | con.SWP_SHOWWINDOW), self.gui.calls)
        self.assertIn("[WINDOW] F12操作により標準ウィンドウ状態へ復元しました", self.log)

    def test_F12_is_not_done_when_the_BVE_window_is_not_in_front(self):
        self.kb.pressed.add("f12")
        self.gui.foreground = 1
        self.tick()
        self.assertEqual([c for c in self.gui.calls if c[0] in ("SetWindowLong", "SendMessage", "SetWindowPos")], [])

    # -- F1 / F2 -----------------------------------------------------------------------------------------------------------------------------
    def test_F2_toggles_the_diagnostic_display_and_the_graph(self):
        self.assertFalse(getattr(self.o, "show_graph", False))
        self.kb.pressed.add("f2")
        self.tick()
        self.assertTrue(self.o.show_graph)
        self.assertTrue(self.o.debug_all_penalties)

    def test_F1_opens_the_menu_with_the_BVE_window_in_front(self):
        self.kb.pressed.add("f1")
        self.tick()
        self.assertNotEqual(self.o.menu_state, 0)


# ----------------------------------------------------------------------------------------------------------------------------------------------
D3_VARIABLES = [
    "manual_eb_penalty_applied", "manual_eb_accum_time", "manual_eb_cooling_time", "smee_virtual_eb_active",
    "hb_cushion_entry_time", "hb_cushion_max_g", "hb_prev_notch", "hb_strong_entered",
    "bb_apply_count", "bb_current_notch", "bb_evaluated", "bb_is_in_zone", "bb_is_stable", "bb_notch_change_time", "bb_prev_stable_notch", "bb_release_count", "bb_state",
    "last_jump_count", "bve_jump_count", "station_list", "is_official_jumping", "is_official_retry", "jump_lock",
    "is_scoring_mode", "is_scoring_finished", "setting_start_idx", "setting_end_idx", "setting_stop_distance", "setting_initial_brake",
    "prev_base_limit", "prev_diff_s", "prev_door", "prev_doordir", "prev_frame_loc", "prev_is_pass", "prev_is_timing", "prev_next_loc", "prev_term", "last_update_time",
    "menu_state", "is_linked", "bve_hwnd",
]


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class G_WhatAGenerationChangeDiscardsToday(unittest.TestCase):
    """Decision D-3 lists what must be discarded at a generation boundary. This is what the code does TODAY (the starting point of the later phase):
    every variable is set to a marker object, a new scenario id arrives, and what still holds the marker was NOT discarded."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["si0g"])
        import main
        cls.main = main

    def setUp(self):
        self.saved_udp = self.main.QUdpSocket
        self.main.QUdpSocket = StubUdp
        self.o = self.main.Overlay()
        self.o.timer.stop()

    def tearDown(self):
        self.main.QUdpSocket = self.saved_udp
        try:
            self.o.close()
            self.o.deleteLater()
        except Exception:
            pass

    def survivors(self, action):
        marker = object()
        o = self.o
        o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")                      # the first scenario id: nothing to discard yet
        for name in D3_VARIABLES:
            self.assertTrue(hasattr(o, name), name)
            setattr(o, name, marker)
        action(o)
        return {name for name in D3_VARIABLES if getattr(o, name) is marker}

    def test_every_variable_of_the_list_exists_on_a_new_overlay(self):
        for name in D3_VARIABLES:
            self.assertTrue(hasattr(self.o, name), name)

    def test_a_new_scenario_id_discards_the_scoring_settings_the_menu_and_the_scoring_flag_only(self):
        kept = self.survivors(lambda o: o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0"))
        discarded = set(D3_VARIABLES) - kept
        self.assertEqual(discarded, {"is_scoring_mode", "is_scoring_finished", "setting_start_idx", "setting_end_idx", "setting_stop_distance", "setting_initial_brake", "menu_state"})

    def test_everything_else_of_the_list_survives_a_scenario_change_today(self):
        kept = self.survivors(lambda o: o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0"))
        self.assertEqual(kept, {
            "manual_eb_penalty_applied", "manual_eb_accum_time", "manual_eb_cooling_time", "smee_virtual_eb_active",
            "hb_cushion_entry_time", "hb_cushion_max_g", "hb_prev_notch", "hb_strong_entered",
            "bb_apply_count", "bb_current_notch", "bb_evaluated", "bb_is_in_zone", "bb_is_stable", "bb_notch_change_time", "bb_prev_stable_notch", "bb_release_count", "bb_state",
            "last_jump_count", "bve_jump_count", "station_list", "is_official_jumping", "is_official_retry", "jump_lock",
            "prev_base_limit", "prev_diff_s", "prev_door", "prev_doordir", "prev_frame_loc", "prev_is_pass", "prev_is_timing", "prev_next_loc", "prev_term", "last_update_time",
            "is_linked", "bve_hwnd"})

    def test_the_telemetry_state_reset_of_a_managed_generation_discards_none_of_them(self):
        kept = self.survivors(lambda o: o.reset_telemetry_state())
        self.assertEqual(kept, set(D3_VARIABLES))

    def test_the_same_scenario_id_again_discards_nothing(self):
        kept = self.survivors(lambda o: o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0"))
        self.assertEqual(kept, set(D3_VARIABLES))

    def test_the_first_ever_scenario_id_discards_nothing_either(self):
        o = self.o
        marker = object()
        for name in D3_VARIABLES:
            setattr(o, name, marker)
        o.apply_telemetry_text("SCENARIO_ID:7,SPEED:0")
        self.assertEqual({n for n in D3_VARIABLES if getattr(o, n) is marker}, set(D3_VARIABLES))
        self.assertEqual(o.current_scenario_id, 7)

if __name__ == "__main__":
    unittest.main()
