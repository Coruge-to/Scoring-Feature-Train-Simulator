"""Phase SI-A2 - the split of Overlay.update_logic changed NOTHING: the same scripted input gives the same Overlay and the same outside effects.

The reference is the main.py of the commit that was HEAD when SI-A started (9f25a26), loaded from git as a module of its own. Both implementations are
built in the test rig (tests/sia_rig.py: every outside effect is a recorder) and driven with the SAME randomized script: key presses and releases, the
foreground window, the "time and position" window, telemetry values, station lists, jump counters, clock steps, mouse clicks, window invalidation,
fullscreen completion. After every tick a digest of the whole Overlay state (every plain attribute) and the length and tail of every recorder is taken.
The two traces must be identical, exception for exception.

The harness proves that it can see a difference: a deliberately broken copy of the new implementation (one part removed) must produce a different trace.
"""
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sia_rig as R  # noqa: E402

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

BASELINE = "9f25a26c6bc4a578767c7f306672811bf7bf341c"        # HEAD when Phase SI-A started: the last commit of Phase SI-1
KEYS = ["f1", "f2", "f11", "f12", "up", "down", "left", "right", "enter", "backspace", "h", "a", "p", "f8", "f5"]
TELEMETRY = [
    "SCENARIO_ID:%d,SPEED:%s,LOCATION:%s,TIME:%d",
]
SKIP_ATTRS = {"timer", "udp_socket", "numeric_router", "telemetry_gate", "font_normal", "font_big", "font_ui", "font_menu", "font_desc"}


def digest(value, depth=0):
    if depth > 6:
        return "<deep>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(digest(v, depth + 1) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join("%s:%s" % (digest(k, depth + 1), digest(v, depth + 1)) for k, v in sorted(value.items(), key=lambda kv: repr(kv[0]))) + "}"
    if isinstance(value, (set, frozenset)):
        return "{" + ",".join(sorted(digest(v, depth + 1) for v in value)) + "}"
    return "<%s>" % type(value).__name__


def overlay_digest(o):
    items = []
    for name, value in sorted(vars(o).items()):
        if name in SKIP_ATTRS or name.startswith("_"):
            continue
        d = digest(value)
        if d.startswith("<") and d.endswith(">"):
            continue
        items.append((name, d))
    g = o.geometry()
    items.append(("geometry", (g.x(), g.y(), g.width(), g.height(), o.isVisible())))
    return items


def make_script(seed, steps=420):
    rng = random.Random(seed)
    script = []
    scenario = 1
    loc = 0.0
    time_ms = 36000000
    for i in range(steps):
        s = {}
        for key in KEYS:
            r = rng.random()
            if r < 0.07:
                s.setdefault("press", []).append(key)
            elif r < 0.30:
                s.setdefault("release", []).append(key)
        if rng.random() < 0.05:
            s["fg"] = rng.random() < 0.8
        if rng.random() < 0.04:
            s["diag"] = rng.choice([0, 777])
        s["adv"] = rng.choice([0.0005, 0.016, 0.016, 0.016, 0.05, 0.06, 0.125, 0.2])
        if rng.random() < 0.5:
            time_ms += rng.choice([0, 16, 16, 16, 60, 1000, 1250, 5000])
            s["time_ms"] = time_ms
        if rng.random() < 0.02:
            time_ms -= rng.choice([1000, 90000])
            s["time_ms"] = time_ms
        if rng.random() < 0.3:
            s["speed"] = rng.choice([0.0, 0.05, 0.1, 5.0, 30.0, -3.0])
        if rng.random() < 0.3:
            loc += rng.choice([0.0, 0.1, 5.0, 250.0])
            s["loc"] = loc
        if rng.random() < 0.15:
            s["notch"] = rng.choice([0, 1, 2, 5, 8])
        if rng.random() < 0.06:
            s["bp"] = rng.choice([0.0, 350.0, 490.0])
        if rng.random() < 0.04:
            s["btype"] = rng.choice(["Ecb", "Smee", "Cl"])
        if rng.random() < 0.05:
            s["door"] = rng.choice([0, 1])
        if rng.random() < 0.03:
            s["jump"] = rng.choice([0, 1, 2, 3])
        if rng.random() < 0.03:
            scenario += 1
            s["scenario"] = scenario
        if rng.random() < 0.05:
            s["status"] = rng.choice(["STATUS:LOADED:PAUSED", "STATUS:LOADED:RUNNING"])
        if rng.random() < 0.04:
            s["stalist"] = rng.choice([
                "STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=0=2500.0=-1=-1=-1=15000=0=1",
                "STALIST:",
            ])
        if rng.random() < 0.05:
            s["scoring"] = rng.choice([True, False])
        if rng.random() < 0.03:
            s["finished"] = rng.choice([True, False])
        if rng.random() < 0.03:
            s["official"] = rng.choice([True, False])
        if rng.random() < 0.04:
            s["menu"] = rng.choice([0, 1, 5, 6, 10, 11, 12])
        if rng.random() < 0.10:
            s["mouse"] = (rng.random() < 0.5, rng.randint(0, 1920), rng.randint(0, 1080))
        if rng.random() < 0.05:
            s["flush"] = True
        if rng.random() < 0.02:
            s["invalidate"] = rng.choice(["gone", "back", "other"])
        if rng.random() < 0.02:
            s["iconic"] = rng.random() < 0.5
        script.append(s)
    return script


def apply_step(rig, s):
    o, kb, gui, api = rig.o, rig.kb, rig.gui, rig.api
    for key in s.get("press", []):
        kb.pressed.add(key)
    for key in s.get("release", []):
        kb.pressed.discard(key)
    if "fg" in s:
        gui.foreground = gui.hwnd if s["fg"] else 1
    if "diag" in s:
        gui.diag = s["diag"]
    rig.advance(s["adv"])
    if "time_ms" in s:
        o.bve_time_ms = s["time_ms"]
    if "speed" in s:
        o.bve_speed = s["speed"]
    if "loc" in s:
        o.bve_location = s["loc"]
    if "notch" in s:
        o.bve_brk_notch = s["notch"]
    if "bp" in s:
        o.bpPressure = s["bp"]
    if "btype" in s:
        o.bve_btype = s["btype"]
    if "door" in s:
        o.bve_door = s["door"]
    if "jump" in s:
        o.bve_jump_count = s["jump"]
    if "scenario" in s:
        o.apply_telemetry_text("SCENARIO_ID:%d,SPEED:0" % s["scenario"])
    datagrams = [s[k].encode("utf-8") for k in ("status", "stalist") if k in s]
    if datagrams:
        o.udp_socket.incoming = datagrams
        o.read_udp_data()
    if "scoring" in s:
        o.is_scoring_mode = s["scoring"]
    if "finished" in s:
        o.is_scoring_finished = s["finished"]
    if "official" in s:
        o.is_official_jumping = s["official"]
    if "menu" in s:
        o.menu_state = s["menu"]
        o.current_menu_items = o.menu_items_on if o.is_scoring_mode else o.menu_items_off
    if "mouse" in s:
        api.left_down, x, y = s["mouse"]
        gui.cursor = (x, y)
    if "flush" in s:
        R.FakeQTimer.flush()
    if "invalidate" in s:
        mode = s["invalidate"]
        if mode == "gone":
            gui.valid = set()
            gui.titles = {}
        elif mode == "back":
            gui.valid = {gui.hwnd}
            gui.titles = {gui.hwnd: "BVE Trainsim 6"}
        else:
            gui.valid = {9001}
            gui.titles = {9001: "BVE Trainsim 6"}
            gui.foreground = 9001
    if "iconic" in s:
        gui.iconic = s["iconic"]


def recorder_state(rig):
    ovl = int(rig.o.winId())                                            # the native handle of the overlay differs from instance to instance
    tail = tuple((call[:1] + (("OVERLAY",) if len(call) > 1 and call[1] == ovl else call[1:2]) + call[2:]) for call in rig.gui.calls[-3:])
    return {
        "hooks": len(rig.kb.hooks), "unhooked": len(rig.kb.unhooked), "active": tuple(rig.kb.active()),
        "hook_tail": tuple(rig.kb.hooks[-4:]), "unhook_tail": tuple(rig.kb.unhooked[-4:]),
        "gui_calls": len(rig.gui.calls), "gui_tail": tail, "diag_enabled": rig.gui.enabled, "style": rig.gui.style,
        "posted": len(rig.api.posted), "posted_tail": tuple(rig.api.posted[-3:]),
        "log_tail": tuple(rig.log[-3:]), "log": len(rig.log), "single_shots": len(R.FakeQTimer.pending), "quits": R.FakeApp.quits,
        "udp_written": len(rig.o.udp_socket.written), "udp_tail": tuple(rig.o.udp_socket.written[-2:]),
        "dialogs": len(R.FakeFileDialog.calls),
    }

def run(module, seed, wrap=None):
    rig = R.Rig(module)
    try:
        if wrap is not None:
            wrap(rig.o)
        trace = []
        for s in make_script(seed):
            apply_step(rig, s)
            try:
                rig.tick()
                err = None
            except Exception as e:  # the exception itself is part of the trace
                err = "%s: %s" % (type(e).__name__, e)
            trace.append((err, tuple(overlay_digest(rig.o)), recorder_state(rig)))
        return trace
    finally:
        rig.close()


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class SplitIsBehaviourPreserving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["sia2"])
        import main
        cls.main = main
        cls.baseline = R.load_main_from_git(BASELINE)
        cls.saved_profile = os.environ.get("USERPROFILE")
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["USERPROFILE"] = cls.tmp.name                       # the result screen would create a folder in Documents

    @classmethod
    def tearDownClass(cls):
        if cls.saved_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = cls.saved_profile
        cls.tmp.cleanup()

    def setUp(self):
        if self.baseline is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")

    def test_the_baseline_module_is_the_one_before_the_split(self):
        self.assertFalse(hasattr(self.baseline.Overlay, "_run_input_and_scoring_step"))
        self.assertTrue(hasattr(self.main.Overlay, "_run_input_and_scoring_step"))

    def test_the_scripts_exercise_the_interesting_paths(self):
        trace = run(self.baseline, 1)
        digests = [dict(t[1]) for t in trace]
        seen = lambda name, values: {d[name] for d in digests} >= set(values)
        self.assertTrue(seen("menu_state", ["0", "1"]))
        self.assertTrue(any(d["is_scoring_mode"] == "True" for d in digests))
        self.assertTrue(any(d["is_borderless_fullscreen"] == "True" for d in digests))
        self.assertGreater(max(t[2]["hooks"] for t in trace), 3)            # key hooks were registered
        self.assertGreater(trace[-1][2]["posted"], 5)                       # messages were posted to the BVE window
        self.assertGreater(trace[-1][2]["gui_calls"], 5)                     # window calls were made

    def test_the_traces_are_identical_for_many_scripts(self):
        for seed in range(1, 41):
            old = run(self.baseline, seed)
            new = run(self.main, seed)
            self.assertEqual(len(old), len(new))
            for i, (a, b) in enumerate(zip(old, new)):
                if a != b:
                    diff = [(n, x, y) for (n, x), (_n, y) in zip(a[1], b[1]) if x != y]
                    self.fail("seed %d step %d: error %r vs %r; state diff %s; recorders %s vs %s" % (seed, i, a[0], b[0], diff[:5], a[2], b[2]))

    def test_the_harness_sees_a_removed_part(self):
        """A vacuous comparison would pass anything: with the F8 suppression part removed from the new implementation the traces must differ."""
        broken = run(self.main, 3, wrap=lambda o: setattr(o, "_sync_f8_suppression", lambda is_bve_active: None))
        reference = run(self.baseline, 3)
        self.assertNotEqual(broken, reference)

    def test_the_harness_sees_a_changed_order(self):
        """Two parts that touch the same recorder in a different order (the F8 hook is registered before the F7 / P hooks) change the hook handles."""
        def swap(o):
            original = type(o)._sync_system_key_suppression
            o._sync_system_key_suppression = lambda is_bve_active: (o._sync_f8_suppression(is_bve_active), original(o, is_bve_active))[1]
        differing = [seed for seed in range(1, 9) if run(self.main, seed, wrap=swap) != run(self.baseline, seed)]
        self.assertTrue(differing, "no script saw the changed order")


class SiAScopeOfMain(unittest.TestCase):
    """Everything that Phase SI-A changed in main.py, member by member (the commit SI-A started from is the reference). A change that is not on this list fails."""
    NEW_MEMBERS = {
        # the split of update_logic (A2)
        "_advance_scoring_clock_and_score", "_detect_and_release_fast_forward", "_follow_bve_window", "_handle_keys", "_handle_mouse", "_kick_start_first_press",
        "_kick_start_second_press", "_resolve_bve_advancing", "_restore_standard_window", "_run_input_and_scoring_step", "_sync_f8_suppression",
        "_sync_menu_key_suppression", "_sync_numeric_input", "_sync_system_key_suppression", "_sync_time_position_window_lock",
        # what the managed mode needs (A3)
        "_emit_input_event", "_take_pending_station_list", "adopt_bve_window", "apply_held_telemetry", "ask_result_save_path", "close_result_dialog",
        "drop_held_station_list", "forget_stale_bve_window", "managed_window_step", "reset_generation_state", "restore_bve_window",
        # SI-A6: the ONE place where managed mode presses P (a recovery token). SI-A / SI-A4's kick_start_managed, kick_start_wanted and kick_start_managed_waiting are gone.
        "press_p_for_recovery",
    }
    CHANGED_MEMBERS = {"update_logic", "apply_telemetry_text", "handle_menu_enter", "read_udp_data", "take_result_screenshot", "toggle_borderless_fullscreen"}
    REMOVED_LINES = {
        "apply_telemetry_text": {"if len(vals) >= 3: self.bve_bp_initial = float(vals[2])",
                                 "self.max_pow_w = get_adjusted_max_w(pow_list, apply_offset=False)"},       # SI-A4: the holding speed texts are width candidates, too
        "take_result_screenshot": {'save_path, _ = QFileDialog.getSaveFileName(self, "採点結果を保存", os.path.join(save_dir, default_name), "JPEG Image (*.jpg);;PNG Image (*.png)")'},
        "handle_menu_enter": set(), "read_udp_data": set(), "toggle_borderless_fullscreen": set(),
    }

    @classmethod
    def setUpClass(cls):
        import subprocess
        out = subprocess.run(["git", "-C", R.ROOT, "show", BASELINE + ":main.py"], capture_output=True)
        cls.old = out.stdout.decode("utf-8").replace("\r\n", "\n") if out.returncode == 0 else None
        with open(os.path.join(R.ROOT, "main.py"), encoding="utf-8") as f:
            cls.new = f.read().replace("\r\n", "\n")

    def setUp(self):
        if self.old is None:
            self.skipTest("baseline commit / git not available (INCONCLUSIVE)")

    @staticmethod
    def members(src):
        import ast
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
        return {n.name: (ast.dump(n), ast.get_source_segment(src, n)) for n in cls.body if isinstance(n, ast.FunctionDef)}, tree

    def test_the_overlay_members_added_changed_and_removed(self):
        mo, _ = self.members(self.old)
        mn, _ = self.members(self.new)
        self.assertEqual(set(mo) - set(mn), set())
        self.assertEqual(set(mn) - set(mo), self.NEW_MEMBERS)
        self.assertEqual({n for n in set(mo) & set(mn) if mo[n][0] != mn[n][0]}, self.CHANGED_MEMBERS)

    def test_the_changed_members_removed_nothing_but_the_listed_lines(self):
        import difflib
        mo, _ = self.members(self.old)
        mn, _ = self.members(self.new)
        for name, allowed in self.REMOVED_LINES.items():
            a = [l.strip() for l in mo[name][1].split("\n") if l.strip()]
            b = [l.strip() for l in mn[name][1].split("\n") if l.strip()]
            removed = {l[1:] for l in difflib.unified_diff(a, b, lineterm="", n=0) if l.startswith("-") and not l.startswith("---")}
            self.assertEqual(removed, allowed, name)

    def test_the_module_level_changes(self):
        import ast
        _, to = self.members(self.old)
        _, tn = self.members(self.new)
        top_o = {getattr(n, "name", ast.dump(n)): ast.dump(n) for n in to.body}
        top_n = {getattr(n, "name", ast.dump(n)): ast.dump(n) for n in tn.body}
        self.assertEqual(set(top_o) - set(top_n), set())
        self.assertEqual({k for k in set(top_n) - set(top_o)}, {"Import(names=[alias(name='managed_input')])", "Import(names=[alias(name='pause_recovery')])", "Import(names=[alias(name='utils')])"})
        self.assertEqual({k for k in set(top_o) & set(top_n) if top_o[k] != top_n[k]}, {"Overlay", "_ManagedShutdownBridge", "_attach_managed_hud", "run_managed"})

    def test_the_init_of_the_overlay_is_untouched(self):
        mo, _ = self.members(self.old)
        mn, _ = self.members(self.new)
        self.assertEqual(mo["__init__"][0], mn["__init__"][0])
        for name in ("paintEvent", "toggle_menu", "handle_menu_up", "handle_menu_down", "handle_menu_left", "handle_menu_right", "handle_menu_backspace",
                     "handle_dropdown_enter", "find_bve_window", "_settle_jump_complete", "reset_telemetry_state"):
            self.assertEqual(mo[name][0], mn[name][0], name)


if __name__ == "__main__":
    unittest.main()
