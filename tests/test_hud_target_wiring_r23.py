"""Phase SI-R2.3 (C4b): the display target reaches the HUD - the wiring of main.py and hud_ui.py to hud_target_contract.py, and what must NOT change.

  A  static: where the sync runs, who writes the display state, what hud_ui.py reads, and that the scoring side / the official supply are byte-identical (case A: the display layer is NEW, nothing
     of the scoring is touched; Night A has nothing to port into this stage)
  B  the real Overlay (tests/sia_rig.py, the wire fixture of tests/official_target_wire_fixture.py; PyQt6 needed: Gate B, skipped by `python -I`): the owner follows the expression at every
     draw, the sync writes nothing but the display state, the terminal freeze lives and dies as the contract says, a failing derivation shows no target

The meaning vectors (tests/official_target_vectors.json) are observed by the RED runners (tests/red_official_target_*.py); the pure rules are tests/test_hud_target_contract_r23.py.
"""
import ast
import hashlib
import importlib.util
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hud_target_contract as H  # noqa: E402
import official_target_contract as OC  # noqa: E402
import official_target_wire_fixture as F  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None

# the git blob ids (LF text) of the sources SI-R2.3 must not change: the scoring (B2 / B3 contract), the input / generation classification, the official supply and the telemetry names
PINNED_BLOBS = {
    "scoring_logic.py": "e8d1a3d0879933f182bbc829a82d8748b6f697b6",
    "managed_input.py": "6b0bda0bb5e95e22d14d58efa868a14ff004904d",
    "official_target_contract.py": "9c0a68979113626724ccfa48e9c9d8cd117b3bae",
    "telemetry_contract.py": "0cc2ef6a9e412e189ab34c84f435c59bdca061e4",
    "network.py": "c3e394245a21f41ffeb02e89cf075c5218e111f8",
}
FIELDS = H.HudTarget._fields
STATE_ATTRS = ("_hud_target", "_hud_freeze")


def read_source(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def code_of(rel):
    """The code of a source file without its docstrings and comments (the words a docstring explains are not the words the code uses)."""
    tree = ast.parse(read_source(rel))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            body[0] = ast.Pass()
    return ast.unparse(tree)


def blob_id(rel):
    with open(os.path.join(ROOT, rel), "rb") as fh:
        data = fh.read().replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def overlay_class(tree):
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")


def methods(cls):
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def self_stores(node):
    """The names of the attributes of `self` that the subtree assigns (Store / Del)."""
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and isinstance(n.value, ast.Name) and n.value.id == "self"}


def calls_of(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == name and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"]


class A_Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_tree = ast.parse(read_source("main.py"))
        cls.overlay = overlay_class(cls.main_tree)
        cls.methods = methods(cls.overlay)
        cls.hud_tree = ast.parse(read_source("hud_ui.py"))

    def test_the_sync_runs_after_every_judged_line(self):
        body = self.methods["_offtgt_sync"].body
        last = body[-1]
        self.assertIsInstance(last, ast.Expr)
        self.assertEqual(len(calls_of(last, "_hud_target_sync")), 1)
        self.assertEqual(len(calls_of(self.methods["_offtgt_sync"], "_hud_target_sync")), 1)

    def test_the_sync_runs_right_before_the_hud_is_drawn(self):
        paint = self.methods["paintEvent"]
        order = [(n.lineno, "sync" if (isinstance(n.func, ast.Attribute) and n.func.attr == "_hud_target_sync") else "draw")
                 for n in ast.walk(paint) if isinstance(n, ast.Call) and ((isinstance(n.func, ast.Attribute) and n.func.attr == "_hud_target_sync")
                                                                           or (isinstance(n.func, ast.Name) and n.func.id == "draw_hud"))]
        self.assertEqual([kind for _line, kind in sorted(order)], ["sync", "draw"])

    def test_the_sync_is_not_called_from_anywhere_else(self):
        callers = sorted(name for name, fn in self.methods.items() if calls_of(fn, "_hud_target_sync"))
        self.assertEqual(callers, ["_offtgt_sync", "paintEvent"])

    def test_the_display_state_is_initialised_reset_and_written_by_its_owners_only(self):
        writers = {name for name, fn in self.methods.items() if self_stores(fn) & set(STATE_ATTRS)}
        self.assertEqual(writers, {"__init__", "reset_telemetry_state", "_hud_target_sync"})
        for name in ("__init__", "reset_telemetry_state"):
            self.assertTrue(set(STATE_ATTRS) <= self_stores(self.methods[name]), name)
        init_sources = [ast.unparse(s) for s in self.methods["__init__"].body if isinstance(s, ast.Assign)]
        self.assertIn("self._hud_target = hud_target_contract.NO_TARGET", init_sources)
        self.assertIn("self._hud_freeze = None", init_sources)

    def test_the_hud_methods_write_nothing_but_the_display_state(self):
        hud_methods = {name: fn for name, fn in self.methods.items() if name.startswith("_hud_")}
        self.assertEqual(sorted(hud_methods), ["_hud_machine_target", "_hud_target_sync", "_hud_timing_of_index"])
        for name, fn in hud_methods.items():
            self.assertLessEqual(self_stores(fn), set(STATE_ATTRS), name)

    def test_the_nine_views_are_read_only_properties_of_the_display_target(self):
        views = {}
        for node in self.overlay.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("hud_target_"):
                self.assertIsInstance(node.value, ast.Call)
                self.assertEqual(node.value.func.id, "_hud_target_property")
                views[node.targets[0].id] = node.value.args[0].value
        self.assertEqual(views, {"hud_target_" + f: f for f in FIELDS})
        self.assertEqual(len(views), 9)

    def test_nothing_assigns_a_view_of_the_display_target(self):
        for rel in ("main.py", "hud_ui.py", "scoring_logic.py", "managed_input.py", "network.py", "managed_hud.py", "menu_ui.py"):
            tree = ast.parse(read_source(rel))
            stores = sorted(n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and n.attr.startswith("hud_target_"))
            self.assertEqual(stores, [], rel)
            self.assertNotIn("setattr(self, 'hud_target", read_source(rel), rel)

    def test_hud_ui_reads_the_display_target_and_not_the_machine_target(self):
        draw = next(n for n in self.hud_tree.body if isinstance(n, ast.FunctionDef) and n.name == "draw_hud")
        reads = {n.attr for n in ast.walk(draw) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and isinstance(n.value, ast.Name) and n.value.id == "self" and n.attr.startswith("hud_target_")}
        self.assertEqual(reads, {"hud_target_next_loc", "hud_target_next_time", "hud_target_is_pass", "hud_target_margin_b", "hud_target_margin_f", "hud_target_timing"})
        text = read_source("hud_ui.py")
        for word in ("bve_next_loc", "bve_next_time", "bve_is_pass", "bve_margin_b", "bve_margin_f", "get_timing_target_stas", "is_station_timing", "_hud_target", "_hud_freeze", "hud_target_contract"):
            self.assertNotIn(word, text, word)
        for name in OC.initial_state():
            self.assertNotIn(name, text, name)

    def test_main_py_reads_the_published_values_only_through_the_display_module(self):
        text = read_source("main.py")
        for name in H.OFFTGT_ATTRS:
            self.assertNotIn(name, text, name)
        self.assertEqual(text.count("hud_target_contract.offtgt_of(self)"), 1)

    def test_the_scoring_side_and_the_official_supply_are_byte_identical(self):
        for rel, want in sorted(PINNED_BLOBS.items()):
            self.assertEqual(blob_id(rel), want, rel)

    def test_the_scoring_side_does_not_know_the_display_target(self):
        for rel in ("scoring_logic.py", "managed_input.py", "network.py", "official_target_contract.py", "telemetry_contract.py"):
            text = read_source(rel)
            for word in ("hud_target", "_hud_target", "_hud_freeze", "hud_target_contract", "offtgt_of"):
                self.assertNotIn(word, text, "%s: %s" % (rel, word))

    def test_the_display_layer_has_no_arm_wait_and_no_distance_search_of_the_close_range_work(self):
        # Night A (the close range arm wait) is not in this stage: nothing of it may arrive through the display layer
        for rel in ("hud_target_contract.py", "hud_ui.py"):
            code = code_of(rel)
            for word in ("target_arm", "arm_wait", "close_range", "50.0", "50 m"):
                self.assertNotIn(word, code, "%s: %s" % (rel, word))
        main_hud = "\n".join(ast.unparse(fn) for name, fn in self.methods.items() if name.startswith("_hud_"))
        for word in ("target_arm", "arm_wait", "close_range", "bve_tgt_idx", "bve_arr_idx", "setting_start_idx"):
            self.assertNotIn(word, main_hud, word)

    def test_the_machine_target_is_still_written_in_three_places_only(self):
        counts = {rel: len(re.findall(r"self\.bve_next_loc\s*=[^=]", read_source(rel))) for rel in ("main.py", "network.py")}
        self.assertEqual(counts, {"main.py": 2, "network.py": 1})


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_Overlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = F.harness_init()
        if env:
            raise unittest.SkipTest("the real Overlay can not run here: " + env)
        cls.vec = F.load_vectors()

    @classmethod
    def tearDownClass(cls):
        left = F.harness_leftovers()
        if left:
            raise AssertionError("the run wrote into the redirected profile: %s" % left)

    MACHINE = {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}

    def step(self, sc, **kw):
        base = {"loc": 500.0, "machine": dict(self.MACHINE), "official": {"state": "K", "index": 2}}
        base.update(kw)
        sc.step(base)
        return sc.hud["dist"], sc.hud["time_left"]

    @staticmethod
    def snapshot(o):
        """Every value the sync must not touch: the machine target / scoring state (plain attributes) and the six published values; the display state itself (underscore) is the one thing allowed to move."""
        basic = (int, float, str, bool, type(None), list, tuple, dict, set, frozenset)
        return {k: repr(v) for k, v in sorted(vars(o).items()) if not k.startswith("_") and isinstance(v, basic) and k not in ("last_update_time", "last_udp_time")}

    def test_a_fresh_overlay_has_no_target_and_the_views_are_read_only(self):
        with F.Scene(self.vec) as sc:
            o = sc.o
            self.assertEqual(tuple(getattr(o, "hud_target_" + f) for f in FIELDS), tuple(H.NO_TARGET))
            for name in ("hud_target_next_loc", "hud_target_owner", "hud_target_timing"):
                with self.assertRaises(AttributeError):
                    setattr(o, name, 1)

    def test_the_owner_follows_the_expression_at_every_draw(self):
        expected = {(False, False): "official", (True, False): "machine", (True, True): "official", (False, True): "official"}
        for (mode, finished), who in expected.items():
            with self.subTest(mode=mode, finished=finished):
                with F.Scene(self.vec) as sc:
                    sc.load_list("L4")
                    dist, tleft = self.step(sc, own={"mode": mode, "finished": finished})
                    self.assertEqual((dist, tleft), ("1500.0 m", "06:00") if who == "official" else ("500.0 m", "01:00"))
                    self.assertEqual(sc.o.hud_target_source, H.SOURCE_OFFICIAL if who == "official" else H.SOURCE_MACHINE)
                    self.assertEqual(sc.o.hud_target_owner, H.OWNER_BVE if who == "official" else H.OWNER_TS)

    def test_the_owner_changes_with_the_flags_alone_not_with_a_line(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            self.assertEqual(self.step(sc, own={"mode": True, "finished": False}), ("500.0 m", "01:00"))
            sc.o.is_scoring_finished = True                    # the scoring finishes inside a Tick: no telemetry line arrives with it
            self.assertEqual(sc.render()["dist"], "1500.0 m")
            sc.o.is_scoring_finished = False
            self.assertEqual(sc.render()["dist"], "500.0 m")
            sc.o.is_scoring_mode = False
            self.assertEqual(sc.render()["dist"], "1500.0 m")

    def test_a_retry_that_goes_on_after_its_jump_keeps_the_scoring_owner_until_the_scoring_ends(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            running = {"mode": True, "finished": False}
            sources = []
            for own in (dict(running, jumping=True, retry=True), dict(running, jumping=False, retry=False), dict(running), dict(running, finished=True), {"mode": False, "finished": False}):
                self.step(sc, own=own)
                sources.append(sc.o.hud_target_source)
            self.assertEqual(sources, [H.SOURCE_MACHINE, H.SOURCE_MACHINE, H.SOURCE_MACHINE, H.SOURCE_OFFICIAL, H.SOURCE_OFFICIAL])

    def test_the_sync_and_the_draw_write_nothing_but_the_display_state(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            for own in ({"mode": False, "finished": False}, {"mode": True, "finished": False}, {"mode": True, "finished": True}):
                self.step(sc, own=own, loc=3000.0, door=1, time_ms=36620000, term=1, official={"state": "K", "index": 3})
                before = self.snapshot(sc.o)
                official = sc.official()
                tgt = (sc.o.bve_tgt_idx, sc.o.bve_arr_idx, sc.o.bve_next_loc, sc.o.bve_next_time)
                sc.o._hud_target_sync()
                sc.render()
                sc.o._hud_target_sync()
                self.assertEqual(self.snapshot(sc.o), before)
                self.assertEqual(sc.official(), official)
                self.assertEqual((sc.o.bve_tgt_idx, sc.o.bve_arr_idx, sc.o.bve_next_loc, sc.o.bve_next_time), tgt)

    def test_the_target_is_ready_at_the_line_before_any_draw(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.push(sc.telemetry_text(dict(sc.state, official={"state": "K", "index": 1}, loc=500.0)))
            self.assertEqual((sc.o.hud_target_source, sc.o.hud_target_next_loc), (H.SOURCE_OFFICIAL, 1000.0))

    def test_the_terminal_freeze_is_display_only_and_follows_the_owner(self):
        terminal = dict(loc=3000.0, door=1, term=1, official={"state": "K", "index": 3})
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            self.step(sc, own={"mode": False, "finished": False}, time_ms=36620000, **terminal)
            self.assertEqual(sc.o._hud_freeze, H.TerminalFreeze((7, sc.list_id), 3, 40))
            self.assertEqual(sc.hud["time_left"], "00:40")
            # later lines of the same stop keep the SAME freeze: now + 40 s, the remaining time is constant (a freeze made again on every line would count down)
            self.step(sc, own={"mode": False, "finished": False}, time_ms=36640000, **terminal)
            self.assertEqual((sc.o._hud_freeze.diff_s, sc.hud["time_left"]), (40, "00:40"))
            # a scoring session starts: BVE no longer owns the target, the freeze ends and the HUD shows the machine target
            self.step(sc, own={"mode": True, "finished": False}, time_ms=36630000, machine={"nextloc": 3000.0, "nexttime": 36660000, "tgt": 3}, **terminal)
            self.assertIsNone(sc.o._hud_freeze)
            self.assertEqual(sc.hud["time_left"], "00:30")
            # it finishes with the doors still open: a NEW freeze of that moment, not the old 40 s
            self.step(sc, own={"mode": True, "finished": True}, time_ms=36650000, **terminal)
            self.assertEqual(sc.o._hud_freeze, H.TerminalFreeze((7, sc.list_id), 3, 10))
            self.assertEqual(sc.hud["time_left"], "00:10")

    def test_a_new_scenario_ends_the_freeze_and_shows_no_old_terminal_time(self):
        terminal = dict(loc=3000.0, door=1, term=1, official={"state": "K", "index": 3})
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            self.step(sc, own={"mode": False, "finished": False}, time_ms=36620000, **terminal)
            self.assertIsNotNone(sc.o._hud_freeze)
            sc.o.reset_telemetry_state()                       # the epoch reset of a new scenario instance
            self.assertIsNone(sc.o._hud_freeze)
            self.assertEqual(tuple(sc.o._hud_target), tuple(H.NO_TARGET))
            self.assertEqual(tuple(sc.render()[k] for k in ("dist", "time_left")), ("--- m", "--:--"))

    def test_the_last_known_target_is_not_held_by_the_overlay(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            self.assertEqual(self.step(sc, own={"mode": False, "finished": False}), ("1500.0 m", "06:00"))
            self.assertEqual(self.step(sc, official={"state": "U", "index": -1}), ("--- m", "--:--"))
            self.assertEqual(sc.o.hud_target_reason, "hud-none-unavailable")
            self.assertEqual(self.step(sc, official={"state": "F", "index": -1}), ("--- m", "--:--"))
            self.assertEqual(sc.o.hud_target_reason, "hud-none-read-failed")
            self.assertEqual(self.step(sc, official={"state": "T", "index": -1}), ("--- m", "--:--"))
            self.assertEqual(sc.o.hud_target_reason, "hud-none-terminal")

    def test_a_failing_derivation_shows_no_target_and_never_the_machine_target(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            self.step(sc, own={"mode": True, "finished": False})
            original = H.derive

            def broken(*_args):
                raise RuntimeError("defect simulation")
            H.derive = broken
            try:
                self.assertEqual(self.step(sc, own={"mode": True, "finished": False}), ("--- m", "--:--"))      # even for the scoring owner: no target is better than a wrong one
                self.assertEqual((sc.o.hud_target_source, sc.o.hud_target_reason, sc.o._hud_freeze), (H.SOURCE_NONE, H.R_INTERNAL, None))
            finally:
                H.derive = original
            self.assertEqual(self.step(sc, own={"mode": True, "finished": False}), ("500.0 m", "01:00"))

    def test_the_timing_label_follows_the_owner(self):
        # the timing station blink (the label of the distance row) is decided by the display target: the machine condition for the scoring owner, the official station for BVE
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.o.setting_start_idx = 0
            sc.o.setting_end_idx = 3
            self.step(sc, own={"mode": False, "finished": False}, official={"state": "K", "index": 2})
            self.assertTrue(sc.o.hud_target_timing)
            self.step(sc, own={"mode": False, "finished": False}, official={"state": "K", "index": 0})        # the start station of the section is never a timing station
            self.assertFalse(sc.o.hud_target_timing)
            sc.o.user_timing_overrides[2] = False
            self.step(sc, own={"mode": False, "finished": False}, official={"state": "K", "index": 2})
            self.assertFalse(sc.o.hud_target_timing)
            self.step(sc, own={"mode": False, "finished": False}, official={"state": "T", "index": -1})
            self.assertFalse(sc.o.hud_target_timing)

    def test_the_timing_condition_of_the_scoring_owner_is_the_one_draw_hud_used_before(self):
        # (a timing station in the chosen section) AND (the next station of the scoring is a timing station: active_next_sta_timing, else ISTIMING)
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            o = sc.o
            o.setting_start_idx, o.setting_end_idx = 0, 3
            running = {"mode": True, "finished": False}
            o.active_next_sta_timing = True
            self.step(sc, own=running)
            self.assertTrue(o.hud_target_timing)                                  # a timing station in the section and the next station is one
            o.active_next_sta_timing = False
            self.step(sc, own=running)
            self.assertFalse(o.hud_target_timing)                                 # the next station of the scoring is not a timing station
            o.active_next_sta_timing = True
            o.user_timing_overrides.update({1: False, 2: False, 3: False})        # no timing station is left in the section (the start station never is one)
            self.step(sc, own=running)
            self.assertFalse(o.hud_target_timing)
            del o.active_next_sta_timing                                          # no scoring rule has run yet: the sender's ISTIMING decides (the vector line carries ISTIMING:1)
            o.user_timing_overrides.clear()
            self.step(sc, own=running)
            self.assertTrue(o.hud_target_timing)

    def test_an_official_station_outside_the_chosen_section_is_not_a_timing_station(self):
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 1
            self.step(sc, own={"mode": False, "finished": False}, official={"state": "K", "index": 1})
            self.assertTrue(sc.o.hud_target_timing)
            self.step(sc, own={"mode": False, "finished": False}, official={"state": "K", "index": 2})
            self.assertFalse(sc.o.hud_target_timing)

    def test_the_label_of_the_distance_row_is_drawn_from_the_display_target(self):
        # the label blinks "timing" / "stop" every 5 s of BVE time while the target is a timing station; at TIME 10:00:00 the phase shows the timing label
        with F.Scene(self.vec) as sc:
            sc.load_list("L5P")
            sc.o.setting_start_idx, sc.o.setting_end_idx = 0, 4
            bve = {"mode": False, "finished": False}
            self.step(sc, own=bve, official={"state": "K", "index": 1})
            self.assertEqual(sc.hud["label"], "\u63a1\u6642")
            sc.o.user_timing_overrides[1] = False
            self.step(sc, own=bve, official={"state": "K", "index": 1})
            self.assertEqual(sc.hud["label"], "\u505c\u8eca")
            self.step(sc, own=bve, official={"state": "K", "index": 2})              # a pass station that is not a timing station any more: the pass label
            sc.o.user_timing_overrides[2] = False
            self.step(sc, own=bve, official={"state": "K", "index": 2})
            self.assertEqual(sc.hud["label"], "\u901a\u904e")
            self.step(sc, own=bve, official={"state": "T", "index": -1})
            self.assertEqual(sc.hud["label"], "\u505c\u8eca")

    def test_the_colour_of_the_distance_follows_the_margins_of_the_display_target(self):
        # the distance is white / "in the margin" / "overrun" by the margins of the TARGET THE HUD SHOWS: the official margins (mb / mf) for BVE, the sender's MARGINB / MARGINF (5 m / 5 m here) for the scoring
        import config
        with F.Scene(self.vec) as sc:
            sc.load_list("L4")
            drawn = []
            sc.hud_ui.draw_text_with_stroke = lambda painter, text, font, color, *a, **k: drawn.append((text, color))      # the Scene puts the original back when it closes

            def colour_of(text):
                return [color for shown, color in drawn if shown == text]

            official = {"state": "K", "index": 1, "mb": 1.0, "mf": 1.0}
            bve = {"mode": False, "finished": False}
            for loc, text, want in ((998.0, "2.00 m", config.COLOR_WHITE), (1003.0, "-3.00 m", config.COLOR_B_EMG), (1000.5, "-0.50 m", config.COLOR_N), (999.5, "0.50 m", config.COLOR_N)):
                drawn.clear()
                self.step(sc, own=bve, loc=loc, official=official)
                self.assertEqual(colour_of(text), [want], "BVE owner, %s" % text)
            for loc, text, want in ((998.0, "2.00 m", config.COLOR_N), (1003.0, "-3.00 m", config.COLOR_N), (1006.0, "-6.0 m", config.COLOR_B_EMG)):
                drawn.clear()
                self.step(sc, own={"mode": True, "finished": False}, loc=loc, official=official)       # the machine target (NEXTLOC 1000) and its 5 m margins, whatever the official margins say
                self.assertEqual(colour_of(text), [want], "scoring owner, %s" % text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
