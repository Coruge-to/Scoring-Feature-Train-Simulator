"""Phase SI-R5.2-B - the tests of Stage B of the replacement of the five 1 m reverse lookups: P01 (evaluate_arrival, the end-station judgement), P04 (the operational-stop
pre-arrival timing, with its explicit missing-index GATE) and P05 (the normal-stop door-open arrival) take the scoring target the C# state machine holds (bve_tgt_idx).

A discovery test (it passes). The REDs of the whole replacement stay in tests/red_si_r5_station_identity.py (P01 / P03 / P04 / P05 are green since this Stage, P02 stays RED until
SI-R5.2-C). Classes A-D use the real Overlay offscreen (skipped without PyQt6); E is static. The scenes name the indexes themselves (tests/si_r5_scene.py): nothing here uses the
rig's position default (sia_rig.bind_identity) and no scene searches a station list.
"""
import ast
import hashlib
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

_TMP = {}

EFFECT_P01 = "suppress_terminal_evaluation"
EFFECT_P04 = "suppress_timing_checkpoint_and_completion"
EFFECT_P05 = "suppress_open_door_arrival_evaluation"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-si-r5-2b-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP["dir"].name)
    finally:
        for k, v in _TMP["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP["dir"].cleanup()
    if left:
        raise AssertionError("the module wrote into the redirected profile: %r" % (left,))


def read_src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def function_node(tree, name):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError("function not found: " + name)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["si-r5-2b"])
        import main
        import scoring_logic
        import si_r5_scene
        import sia_rig
        import station_identity
        cls.main, cls.S, cls.R, cls.X, cls.SI = main, scoring_logic, sia_rig, si_r5_scene, station_identity

    def setUp(self):
        self.c = self.X.Scene(self.main, self.S, self.R)
        self.addCleanup(self.c.close)

    def abcd(self):
        return self.X.abcd(self.R)

    def adj(self):
        return self.X.adjacent(self.R)

    def fresh(self):
        self.c.close()
        self.setUp()


# ======================================================================================================================================================
# A. P01 evaluate_arrival
# ======================================================================================================================================================
class A_P01(Base):
    def test_a_verified_target_of_the_end_station_ends_the_scoring(self):
        o = self.c.scene(self.abcd(), 2000.0, end_idx=2, tgt=2, arr=0)
        self.S.evaluate_arrival(o, 50.0)
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(self.c.missing("P01"), [])

    def test_the_station_is_the_target_not_the_arrival_and_not_the_position(self):
        o = self.c.scene(self.abcd(), 2000.0, end_idx=1, tgt=2, arr=1)         # arrival names the end station B, the target names C: C is not the end station
        self.S.evaluate_arrival(o, 50.0)
        self.assertFalse(o.is_scoring_finished)

    def test_index_zero_is_an_index(self):
        o = self.c.scene(self.abcd(), 0.0, end_idx=0, tgt=0, arr=0)
        self.S.evaluate_arrival(o, 50.0)
        self.assertTrue(o.is_scoring_finished)

    def test_a_missing_target_never_ends_the_scoring_even_when_the_terminal_flag_is_set(self):
        o = self.c.scene(self.abcd(), 3000.0, end_idx=3, tgt=-1, arr=3)
        o.prev_term = 1                                                          # the C# says terminal; the end-station judgement is still not made without the station
        self.S.evaluate_arrival(o, 50.0)
        self.assertFalse(o.is_scoring_finished)

    def test_a_missing_target_with_the_end_station_at_the_position_does_not_end(self):
        for end_idx, loc in ((0, 0.0), (3, 3000.0), (2, 2000.0)):
            self.fresh()
            o = self.c.scene(self.abcd(), loc, end_idx=end_idx, tgt=-1, arr=end_idx)
            self.S.evaluate_arrival(o, 50.0)
            self.assertFalse(o.is_scoring_finished, loc)

    def test_a_bool_a_float_a_none_a_string_and_an_out_of_range_index_are_missing(self):
        for bad in (True, 1.0, None, "1", 99, -2):
            self.fresh()
            o = self.c.scene(self.abcd(), 1000.0, end_idx=1, tgt=1, arr=1)
            o.bve_tgt_idx = bad
            self.S.evaluate_arrival(o, 50.0)
            self.assertFalse(o.is_scoring_finished, repr(bad))
            self.assertEqual(len(self.c.missing("P01")), 1, repr(bad))

    def test_the_official_target_is_never_used_instead(self):
        o = self.c.scene(self.abcd(), 1000.0, end_idx=3, tgt=-1, arr=1)
        o.official_state, o.official_index, o.official_location = "KNOWN", 3, 3000.0
        self.S.evaluate_arrival(o, 50.0)
        self.assertFalse(o.is_scoring_finished)

    def test_the_event_names_the_site_the_action_and_the_effect(self):
        o = self.c.scene(self.abcd(), 2000.0, end_idx=2, tgt=-1, arr=2)
        self.S.evaluate_arrival(o, 50.0)
        got = self.c.missing("P01")
        self.assertEqual(len(got), 1)
        f = got[0]
        self.assertEqual((f["a"], f["site"], f["cls"], f["action"], f["effect"], f["scoring"], f["tgt"]), ("P01", "P01", "unexpected_missing", "skip", EFFECT_P01, 1, -1))
        for k in self.X.REQUIRED_FIELDS:
            self.assertIn(k, f)

    def test_the_stop_score_is_a_physical_judgement_and_is_not_suppressed(self):
        o = self.c.scene(self.abcd(), 1000.0, end_idx=3, tgt=-1, arr=1)
        o.has_scored_stop_this_station = False
        self.S.evaluate_arrival(o, 50.0)
        self.assertTrue(o.has_scored_stop_this_station)


# ======================================================================================================================================================
# B. P04 operational-stop pre-arrival timing and its explicit gate
# ======================================================================================================================================================
class B_P04(Base):
    def spies(self):
        arrival = mock.patch.object(self.S, "evaluate_arrival", wraps=self.S.evaluate_arrival)
        checkpoint = mock.patch.object(self.S, "create_save_data", wraps=self.S.create_save_data)
        latch = mock.patch.object(self.S, "operational_stop_station", wraps=self.S.operational_stop_station)
        timing = mock.patch.object(self.S, "apply_time_score", wraps=self.S.apply_time_score)
        out = []
        for p in (arrival, checkpoint, latch, timing):
            out.append(p.start())
            self.addCleanup(p.stop)
        return out

    def test_a_verified_target_scores_once_and_the_latch_names_the_station(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0)
        self.c.operational_arrival(5)
        self.assertEqual((self.c.checkpoints(), o.operational_stop_latch[0]), ([0, 1], 1))

    def test_the_adjacent_end_station_is_the_target_and_its_arrival_time_is_scored(self):
        o = self.c.scene(self.adj(), 1000.5, doordir=0, end_idx=2, tgt=2, arr=2)
        o.bve_next_time = o.bve_time_ms + 5000
        self.c.operational_arrival()
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(len(self.c.popups("運転時分")), 1)

    def test_the_gate_reaches_neither_the_checkpoint_nor_the_completion_nor_the_latch(self):
        arrival, checkpoint, latch, timing = self.spies()
        o = self.c.scene(self.abcd(), 2000.0, doordir=0, end_idx=2, tgt=-1, arr=2)
        self.c.operational_arrival(6)
        self.assertEqual((arrival.call_count, checkpoint.call_count, latch.call_count, timing.call_count), (0, 0, 0, 0))
        self.assertEqual(self.c.checkpoints(), [0])
        self.assertFalse(o.is_scoring_finished)
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertFalse(o.has_scored_time_this_station)
        self.assertIsNone(getattr(o, "operational_stop_latch", None))
        self.assertEqual(self.c.popups("停止位置") + self.c.popups("運転時分"), [])

    def test_the_gate_does_not_end_the_scoring_by_the_terminal_flag_or_the_end_station_at_the_position(self):
        o = self.c.scene(self.abcd(), 3000.0, doordir=0, end_idx=3, tgt=-1, arr=3)
        o.bve_term = 1
        self.c.operational_arrival(4)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(self.c.checkpoints(), [0])

    def test_the_gate_does_not_score_the_time_of_a_timing_end_station(self):
        o = self.c.scene(self.adj(), 1000.5, doordir=0, end_idx=2, tgt=-1, arr=2)
        o.bve_next_time = o.bve_time_ms + 5000
        self.c.operational_arrival(3)
        self.assertEqual(self.c.popups("運転時分"), [])
        self.assertFalse(o.is_scoring_finished)

    def test_the_gate_is_level_triggered_the_return_evaluates_exactly_once(self):
        arrival, checkpoint, latch, _timing = self.spies()
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(40)
        self.assertEqual(arrival.call_count, 0)
        o.bve_tgt_idx = 1
        self.c.tick(5)
        self.assertEqual((arrival.call_count, checkpoint.call_count, latch.call_count), (1, 1, 1))
        self.assertEqual(self.c.checkpoints(), [0, 1])
        self.assertEqual(o.operational_stop_latch[0], 1)

    def test_a_long_hold_reports_one_start_one_end_and_the_tick_count(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(200)
        o.bve_tgt_idx = 1
        self.c.tick(2)
        got, ends = self.c.missing("P04"), self.c.missing_end("P04")
        self.assertEqual((len(got), len(ends)), (1, 1))
        f = got[0]
        self.assertEqual((f["a"], f["site"], f["cls"], f["action"], f["effect"], f["avail"]), ("P04", "P04", "unexpected_missing", "skip", EFFECT_P04, 0))
        self.assertEqual((ends[0]["ticks"], ends[0]["recovery"], ends[0]["cls"]), (200, "established", "unexpected_missing"))

    def test_even_one_tick_is_unexpected_inside_an_open_window(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        o.jump_baseline_pending = True                                           # a generation start: the arrival is a scoring opportunity, so it is never expected
        self.c.operational_arrival(1)
        self.assertEqual([f["cls"] for f in self.c.missing("P04")], ["unexpected_missing"])

    def test_the_gate_does_not_apply_where_the_identity_is_not_used(self):
        # a jump lock / the first station: the HEAD path (no end-station judgement, the latch from the arrival index) is untouched and reports nothing
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        o.jump_lock = True
        self.c.operational_arrival(3)
        self.assertEqual(self.c.missing("P04"), [])
        self.assertTrue(o.has_scored_stop_this_station)
        self.assertEqual(o.operational_stop_latch[0], 1)

    def test_the_official_jump_wait_makes_no_arrival_and_reports_nothing(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        o.is_official_jumping = True
        self.c.operational_arrival(3)
        self.assertEqual(self.c.missing("P04"), [])
        self.assertFalse(o.has_scored_stop_this_station)

    def test_a_stop_outside_the_range_makes_no_arrival_and_reports_nothing(self):
        o = self.c.scene(self.abcd(), 1000.0, d=20.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(3)
        self.assertEqual(self.c.missing("P04"), [])


# ======================================================================================================================================================
# C. P05 normal-stop door-open arrival
# ======================================================================================================================================================
class C_P05(Base):
    def test_a_verified_target_scores_checkpoints_and_ends_at_the_end_station(self):
        o = self.c.scene(self.abcd(), 1000.0)
        self.c.door_edge()
        self.assertEqual((self.c.checkpoints(), len(self.c.popups("停止位置"))), ([0, 1], 1))
        self.fresh()
        o = self.c.scene(self.abcd(), 3000.0)
        self.c.door_edge()
        self.assertTrue(o.is_scoring_finished)

    def test_the_adjacent_pair_and_the_same_place_name_the_target(self):
        for stations, loc in ((self.adj(), 1000.5), (self.X.same_place(self.R), 1000.0)):
            self.fresh()
            o = self.c.scene(stations, loc, end_idx=2, tgt=2, arr=2)
            self.c.door_edge()
            self.assertTrue(o.is_scoring_finished)

    def test_a_missing_target_evaluates_nothing_and_reports_the_edge_once(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        self.c.door_edge()
        self.assertEqual(self.c.popups(), [])
        self.assertEqual(self.c.checkpoints(), [0])
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertFalse(o.has_scored_time_this_station)
        got = self.c.missing("P05")
        self.assertEqual(len(got), 1)
        f = got[0]
        self.assertEqual((f["a"], f["site"], f["cls"], f["action"], f["effect"], f["tgt"], f["avail"]), ("P05", "P05", "unexpected_missing", "skip", EFFECT_P05, -1, 0))

    def test_the_end_station_at_the_position_is_not_inferred(self):
        o = self.c.scene(self.abcd(), 3000.0, end_idx=3, tgt=-1, arr=3)
        o.bve_term = 1
        self.c.door_edge()
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(self.c.checkpoints(), [0])

    def test_the_arrival_is_edge_triggered_and_is_not_retried_when_the_identity_returns(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        self.c.door_edge()
        o.bve_tgt_idx = 1                                                        # the identity returns while the doors stay open
        self.c.tick(10)
        self.assertEqual(self.c.popups(), [])
        self.assertEqual(self.c.checkpoints(), [0])
        self.assertFalse(o.has_scored_stop_this_station)
        self.assertEqual(len(self.c.missing_end("P05")), 1)
        self.assertEqual(self.c.missing_end("P05")[0]["ticks"], 1)

    def test_a_new_door_edge_after_the_return_evaluates_normally(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        self.c.door_edge()
        o.bve_tgt_idx = 1
        o.bve_door = 0
        self.c.tick(2)
        o.bve_door = 1
        self.c.tick(2)
        self.assertEqual(self.c.checkpoints(), [0, 1])
        self.assertTrue(o.has_scored_stop_this_station)

    def test_a_door_edge_outside_the_range_is_not_an_opportunity_and_reports_nothing(self):
        self.c.scene(self.abcd(), 1000.0, d=20.0, tgt=-1, arr=1)
        self.c.door_edge()
        self.assertEqual(self.c.missing("P05"), [])

    def test_no_target_by_contract_reports_nothing(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        o.bve_next_loc = -1.0
        self.c.door_edge()
        self.assertEqual(self.c.missing("P05"), [])

    def test_a_generation_start_is_expected_then_never_again_inside_the_same_window(self):
        o = self.c.scene(self.abcd(), 1000.0)
        o.is_scoring_mode = False
        o.jump_baseline_pending = True
        self.X.decision_unavailable(o, self.SI.NOT_READY)
        self.c.door_edge()
        self.assertEqual([f["cls"] for f in self.c.missing("P05")], ["expected_unavailable"])
        o.bve_tgt_idx = 1                                                        # the first valid index of the window
        o.bve_door = 0
        self.c.tick(2)
        o.bve_tgt_idx = -1                                                       # lost again inside the same window
        o.bve_door = 1
        self.c.tick(2)
        self.assertEqual([f["cls"] for f in self.c.missing("P05")], ["expected_unavailable", "unexpected_missing"])

    def test_the_official_target_is_never_used_instead(self):
        o = self.c.scene(self.abcd(), 1000.0, end_idx=3, tgt=-1, arr=1)
        o.official_state, o.official_index, o.official_location = "KNOWN", 3, 3000.0
        self.c.door_edge()
        self.assertEqual(self.c.popups(), [])
        self.assertFalse(o.is_scoring_finished)


# ======================================================================================================================================================
# D. the three sites together: managed / normal parity, no new state, no replacement
# ======================================================================================================================================================
class D_Common(Base):
    def run_scenes(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(4)
        o.is_approaching = False
        o.bve_doordir = 1
        o.has_scored_stop_this_station = False
        o.bve_door = o.prev_door = 0
        self.c.door_edge()
        self.S.evaluate_arrival(o, 50.0)
        return o

    def test_the_managed_and_the_normal_mode_skip_alike_and_only_the_managed_mode_reports(self):
        results = []
        for managed in (True, False):
            self.fresh()
            if not managed:
                self.c.o.input_event_sink = None
            o = self.run_scenes()
            results.append((len(o.popups), o.score, o.is_scoring_finished, len(o.save_data), o.has_scored_stop_this_station))
            events = [(e, f["site"]) for e, f in self.c.events]
            if managed:
                self.assertEqual(sorted(x for x in events if x[1] != "P03"), [("stidx-missing-index", "P01"), ("stidx-missing-index", "P04"), ("stidx-missing-index", "P05")])      # (P03 is the HUD step of the same ticks: Stage A)
            else:
                self.assertEqual(events, [])
            self.assertEqual(hasattr(o, "_missing_tracker"), managed)
        self.assertEqual(results[0], results[1])

    def test_each_site_has_its_own_effect_and_every_event_is_a_skip(self):
        self.run_scenes()
        got = {f["site"]: (f["a"], f["action"], f["effect"]) for f in self.c.missing() if f["site"] != "P03"}
        self.assertEqual(got, {"P01": ("P01", "skip", EFFECT_P01), "P04": ("P04", "skip", EFFECT_P04), "P05": ("P05", "skip", EFFECT_P05)})

    def test_a_failing_sink_changes_nothing_in_the_scoring(self):
        def boom(event, **fields):
            raise RuntimeError("sink")
        self.c.o.input_event_sink = boom
        o = self.run_scenes()
        got = ([p["text"] for p in o.popups], o.score, o.is_scoring_finished, len(o.save_data))
        self.fresh()
        self.c.o.input_event_sink = None
        o = self.run_scenes()
        self.assertEqual(got, ([p["text"] for p in o.popups], o.score, o.is_scoring_finished, len(o.save_data)))

    def test_no_state_is_added_and_the_published_indexes_are_not_written(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        before = set(vars(o))
        self.c.door_edge()
        self.S.evaluate_arrival(o, 50.0)
        added = set(vars(o)) - before
        self.assertEqual({n for n in added if re.search(r"held|hold_reason|retry|pending|latch|tgt|idx|index", n)}, set())
        self.assertIn("_missing_tracker", added)
        self.assertEqual((o.bve_tgt_idx, o.bve_arr_idx, o.bve_next_loc), (-1, 1, 1000.0))

    def test_the_events_carry_no_station_name_and_no_replacement(self):
        self.run_scenes()
        for f in self.c.missing():
            for k, v in f.items():
                self.assertFalse(isinstance(v, str) and v in ("A", "B", "C", "D"), k)
            self.assertFalse(any(k in f for k in ("chosen", "idx", "station", "name")))

    def test_the_p03_hud_step_and_the_three_sites_keep_separate_runs(self):
        o = self.c.scene(self.abcd(), 1000.0, d=300.0, speed=10.0, tgt=-1, arr=1)
        self.c.tick()
        o.bve_speed = 0.0
        o.bve_location = 1000.0
        self.c.door_edge()
        self.assertEqual(sorted((f["site"], f["cls"]) for f in self.c.missing()), [("P03", "unexpected_missing"), ("P05", "unexpected_missing")])

    def test_close_range_adjacent_pair_is_unchanged(self):
        o = self.c.scene(self.adj(), 1000.5, end_idx=2, tgt=2, arr=2)
        self.c.door_edge()
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(self.c.missing(), [])


# ======================================================================================================================================================
# E. static: the Stage B boundaries
# ======================================================================================================================================================
class E_Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read_src("scoring_logic.py")
        cls.tree = ast.parse(cls.text)
        cls.arrival = ast.get_source_segment(cls.text, function_node(cls.tree, "evaluate_arrival"))
        cls.update = ast.get_source_segment(cls.text, function_node(cls.tree, "update_physics_and_scoring"))

    def test_the_three_sites_have_no_distance_lookup_and_read_the_target_index(self):
        for name, src in (("evaluate_arrival", self.arrival), ("update_physics_and_scoring", self.update)):
            self.assertEqual(len(re.findall(r"abs\(st\[.location.\]", src)), 0, name)
            self.assertIn("bve_tgt_idx", src, name)
            self.assertIn("station_identity.index_in_list", src, name)
            self.assertNotRegex(src, r"official_(state|index|location|reason|margin)", name)
        self.assertNotRegex(self.arrival, r"enumerate\(|station_list\)\s*:|for\s+\w+(,\s*\w+)?\s+in\s+.*station_list")

    def test_evaluate_arrival_signature_is_unchanged(self):
        node = function_node(self.tree, "evaluate_arrival")
        self.assertEqual([a.arg for a in node.args.args], ["self", "current_time", "arrival_target_loc"])
        self.assertEqual([getattr(d, "value", "?") for d in node.args.defaults], [None])

    def test_the_effect_words_are_these_and_each_is_used_once(self):
        for word in (EFFECT_P01, EFFECT_P04, EFFECT_P05):
            self.assertEqual(self.text.count('"%s"' % word), 1, word)
        self.assertEqual(len(re.findall(r'note_missing\(self, "P0[145]"', self.text)), 3)
        self.assertEqual(len(re.findall(r'note_present\(self, "P0[145]"', self.text)), 3)        # P01 in evaluate_arrival; P04 and P05 together on the arrival target of the tick

    def test_the_p04_gate_guards_the_evaluation_the_latch_and_the_recorded_stop(self):
        node = function_node(self.tree, "update_physics_and_scoring")
        guards = {"evaluate_arrival": False, "operational_stop_station": False, "has_scored_stop_this_station": False, "apply_time_score": False}

        def under_gate(parents):
            return any(isinstance(p, ast.If) and "arrival_deferred" in ast.unparse(p.test) and "not" in ast.unparse(p.test) for p in parents)

        def visit(n, parents):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("evaluate_arrival", "operational_stop_station") and len(n.args) <= 2:
                if n.func.id == "evaluate_arrival" and len(n.args) == 2:
                    guards["evaluate_arrival"] = under_gate(parents)
                if n.func.id == "operational_stop_station":
                    guards["operational_stop_station"] = under_gate(parents)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "apply_time_score" and any(isinstance(p, ast.If) and "is_scoring_end_station_op" in ast.unparse(p.test) for p in parents):
                guards["apply_time_score"] = under_gate(parents)
            if isinstance(n, ast.Assign) and any(ast.unparse(t) == "self.has_scored_stop_this_station" for t in n.targets) and isinstance(n.value, ast.Constant) and n.value.value is True \
                    and any(isinstance(p, ast.If) and "arrival_deferred" in ast.unparse(p.test) for p in parents):
                guards["has_scored_stop_this_station"] = under_gate(parents)
            for ch in ast.iter_child_nodes(n):
                visit(ch, parents + [n])

        visit(node, [])
        self.assertEqual(guards, {"evaluate_arrival": True, "operational_stop_station": True, "has_scored_stop_this_station": True, "apply_time_score": True})

    def test_the_gate_is_computed_from_the_identity_only(self):
        self.assertRegex(self.update, r"arrival_deferred = not arrival_identity_ok")
        self.assertEqual(len(re.findall(r"arrival_deferred\s*=", self.update)), 2)                      # the default and the gate

    def test_scoring_logic_gained_no_function_and_no_new_state(self):
        self.assertIsNone(re.search(r"_missing_tracker|MissingTracker|stidx-missing|def \w*missing\w*|def note_identity", self.text))
        self.assertIsNone(re.search(r"self\.(bve_tgt_idx|bve_arr_idx|bve_arr_seq)\s*=[^=]", self.text))
        self.assertEqual(len(re.findall(r"self\.prev_tgt_idx\s*=[^=]", self.text)), 1)        # Phase SI-R5.2-C: the one mirror beside prev_next_loc
        self.assertIsNone(re.search(r"held_target_idx|hold_reason|retry_door|door_retry|pending_arrival", self.text))

    def test_station_identity_main_and_managed_input_are_not_part_of_this_stage(self):
        blob = read_src("station_identity.py").encode("utf-8")
        self.assertEqual(hashlib.sha1(b"blob %d\0" % len(blob) + blob).hexdigest(), "2c971098059a6b8948cd842ed84af8ece9a054b9")      # the classifier of SI-R5.2-A, as it was committed
        for name in ("main.py", "managed_input.py"):
            self.assertNotRegex(read_src(name), r"_missing_tracker|MissingTracker|note_missing|stidx-missing", name)        # Phase SI-R5.2-C: prev_tgt_idx (-1) is the one state added to main / managed_input

    def test_p02_no_longer_looks_up_by_distance_and_p03_keeps_its_stage_a_form(self):
        departure = ast.get_source_segment(self.text, function_node(self.tree, "evaluate_departure"))
        self.assertEqual(len(re.findall(r"abs\(st\[.location.\]\s*-\s*p_loc\)\s*<\s*1\.0", departure)), 0)        # Phase SI-R5.2-C: P02 reads prev_tgt_idx
        self.assertRegex(self.update, r'note_missing\(self, "P03", current_time, target_idx, "hud_placeholder\+keep_existing_rule_section"\)')

    def test_the_global_close_guard_has_no_lookup_left_after_stage_c(self):
        import red_si_r5_global_close_guard as G
        found = G.scan_python(self.text, "scoring_logic.py")
        self.assertEqual(found, [])        # Phase SI-R5.2-C: 1 -> 0
        self.assertEqual(G.ALLOW_PY, {})


if __name__ == "__main__":
    unittest.main()
