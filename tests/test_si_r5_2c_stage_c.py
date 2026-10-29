"""Phase SI-R5.2-C - the tests of Stage C of the replacement of the five 1 m reverse lookups: P02 (evaluate_departure, the time score of the station that was LEFT) takes the target
index that was kept BEFORE the target switched (prev_tgt_idx), verified against prev_next_loc within 0.01 m. After this Stage no 1 m reverse lookup is left in the Python product.

A discovery test (it passes). The REDs of the whole replacement stay in tests/red_si_r5_station_identity.py. Classes A-D use the real Overlay offscreen (skipped without PyQt6); E is static.
The scenes name the indexes themselves (tests/si_r5_scene.py): nothing here searches a station list by a position.
"""
import ast
import hashlib
import os
import re
import sys
import tempfile
import unittest

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

EFFECT_P02 = "suppress_departure_timing_evaluation"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-si-r5-2c-")
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
        cls.app = QApplication.instance() or QApplication(["si-r5-2c"])
        import main
        import managed_input
        import scoring_logic
        import si_r5_scene
        import sia_rig
        import station_identity
        cls.main, cls.MI, cls.S, cls.R, cls.X, cls.SI = main, managed_input, scoring_logic, sia_rig, si_r5_scene, station_identity

    def setUp(self):
        self.c = self.X.Scene(self.main, self.S, self.R)
        self.addCleanup(self.c.close)

    def fresh(self):
        self.c.close()
        self.setUp()

    def abcd(self):
        return self.X.abcd(self.R)

    def sta(self, name, loc, **kw):
        return self.X.sta(self.R, name, loc, **kw)

    def timing(self):
        return self.c.popups("運転時分")

    def left(self, stations, from_loc, to_loc, prev_tgt, tgt_after, **kw):
        """Stand at `from_loc` and leave for `to_loc`: the target switches forward on this tick and evaluate_departure runs."""
        self.c.scene(stations, from_loc, **kw)
        self.c.departure(from_loc, to_loc, prev_tgt, tgt_after=tgt_after)


# ======================================================================================================================================================
# A. P02 evaluate_departure: the index kept before the switch names the station that was left
# ======================================================================================================================================================
class A_P02(Base):
    def test_the_index_kept_before_the_switch_names_the_left_station(self):
        self.left(self.abcd(), 1000.0, 2000.0, 1, 2)
        self.assertEqual(len(self.timing()), 1)
        self.assertEqual(self.c.missing("P02"), [])

    def test_the_first_index_zero_is_an_index(self):
        o = self.c.scene(self.abcd(), 0.0, prev_tgt=0)
        o.setting_start_idx = 1
        self.c.departure(0.0, 1000.0, 0, tgt_after=1)
        self.assertEqual(len(self.timing()), 1)

    def test_the_last_index_of_the_list_is_an_index(self):
        stations = [self.sta("A", 0.0), self.sta("B", 1000.0), self.sta("C", 2000.0), self.sta("D", 3000.0), self.sta("E", 4000.0, terminal=True)]
        self.left(stations, 3000.0, 4000.0, 3, 4, end_idx=4)
        self.assertEqual(len(self.timing()), 1)
        self.fresh()
        self.left(stations, 4000.0, 5000.0, 4, -1, end_idx=4, tgt=4)        # the last index itself (it is a valid index inside the list: no missing event)
        self.assertEqual(self.c.missing("P02"), [])

    def test_an_index_outside_the_list_scores_nothing_and_names_no_other_station(self):
        for bad in (4, 99, -2, -1, True, 1.0, None, "1"):
            self.fresh()
            self.left(self.abcd(), 1000.0, 2000.0, bad, 2)
            self.assertEqual(self.timing(), [], repr(bad))
            self.assertEqual(len(self.c.missing("P02")), 1, repr(bad))
            self.assertEqual(self.c.missing("P02")[0]["cls"], "unexpected_missing", repr(bad))

    def test_the_target_index_minus_one_is_never_used(self):
        self.left(self.abcd(), 1000.0, 2000.0, -1, 2)                        # bve_tgt_idx - 1 = 1 is B, the station that was left: still no score
        self.assertEqual(self.timing(), [])

    def test_the_target_index_itself_is_never_used(self):
        self.left(self.abcd(), 1000.0, 2000.0, -1, 1)
        self.assertEqual(self.timing(), [])

    def test_the_official_target_is_never_used(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
        o.official_state, o.official_index, o.official_location = "KNOWN", 1, 1000.0
        self.c.departure(1000.0, 2000.0, -1, tgt_after=2)
        self.assertEqual(self.timing(), [])

    def test_the_nearest_station_and_the_lowest_index_are_never_chosen(self):
        both = [self.sta("A", 0.0), self.sta("B", 1000.0, is_timing=False), self.sta("C", 1000.0, is_timing=True), self.sta("D", 3000.0, terminal=True)]
        self.left(both, 1000.0, 3000.0, 2, 3, tgt=2)                         # C is the left station (timing); the lowest index at that place is B (not timing)
        self.assertEqual(len(self.timing()), 1)
        self.fresh()
        self.left(both, 1000.0, 3000.0, -1, 3, tgt=2)                        # no index: not B (lowest) and not C (nearest)
        self.assertEqual(self.timing(), [])

    def test_a_station_that_is_not_a_timing_station_is_not_scored(self):
        both = [self.sta("A", 0.0), self.sta("B", 1000.0, is_timing=False), self.sta("C", 2000.0), self.sta("D", 3000.0, terminal=True)]
        self.left(both, 1000.0, 2000.0, 1, 2)
        self.assertEqual(self.timing(), [])
        self.assertEqual(self.c.missing("P02"), [])                          # a verified index that is not a timing station is not a missing index


# ======================================================================================================================================================
# B. the 0.01 m verification against prev_next_loc
# ======================================================================================================================================================
class B_Verification(Base):
    def depart_from_a(self, prev_next):
        """Station A is at 0.0; the previous NEXTLOC is `prev_next`."""
        o = self.c.scene(self.abcd(), 0.0, prev_tgt=0, prev_next=prev_next)
        o.setting_start_idx = 1
        self.c.departure(0.0, 1000.0, 0, tgt_after=1)

    def test_within_the_tolerance_the_index_is_used(self):
        for off in (0.0, 0.005, 0.0099):
            self.fresh()
            self.depart_from_a(off)
            self.assertEqual(len(self.timing()), 1, off)

    def test_exactly_at_the_tolerance_the_index_is_used(self):
        self.depart_from_a(0.01)
        self.assertEqual(len(self.timing()), 1)

    def test_beyond_the_tolerance_it_is_a_position_mismatch(self):
        for off in (0.0101, 0.02, 0.5, 0.999, 1.0, 50.0):
            self.fresh()
            self.depart_from_a(off)
            self.assertEqual(self.timing(), [], off)
            got = self.c.missing("P02")
            self.assertEqual(len(got), 1, off)
            self.assertEqual(got[0]["cls"], "position_mismatch", off)
            self.assertEqual(got[0]["prev_tgt"], 0, off)

    def test_the_old_one_metre_tolerance_is_gone(self):
        self.fresh()
        self.depart_from_a(0.5)                                              # the old lookup would have found A (|0 - 0.5| < 1.0)
        self.assertEqual(self.timing(), [])

    def test_a_valid_index_for_another_station_is_a_mismatch_not_a_re_selection(self):
        self.left(self.abcd(), 1000.0, 2000.0, 2, 2)                         # prev_tgt_idx names C but prev_next_loc is B
        self.assertEqual(self.timing(), [])
        self.assertEqual(self.c.missing("P02")[0]["cls"], "position_mismatch")


# ======================================================================================================================================================
# C. prev_tgt_idx: initial value, the one mirror per tick, the clears
# ======================================================================================================================================================
class C_State(Base):
    def test_the_initial_value_is_minus_one(self):
        self.assertEqual(self.c.o.prev_tgt_idx, -1)
        self.assertEqual(self.MI.generation_defaults()["prev_tgt_idx"], -1)

    def test_the_tick_mirrors_the_target_beside_prev_next_loc(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=2, arr=1, prev_tgt=-1)
        self.c.tick()
        self.assertEqual((o.prev_tgt_idx, o.prev_next_loc), (2, o.bve_next_loc))

    def test_the_mirror_is_written_after_the_departure_was_evaluated(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=1)
        self.c.departure(1000.0, 2000.0, 1, tgt_after=2)
        self.assertEqual(len(self.timing()), 1)                              # the tick used the OLD value (B) ...
        self.assertEqual(o.prev_tgt_idx, 2)                                  # ... and kept the NEW target (C) for the next departure

    def test_a_target_anomaly_clears_it(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=2, arr=1)
        self.c.tick()
        o.bve_tgt_idx = -1
        self.c.tick()
        self.assertEqual(o.prev_tgt_idx, -1)

    def test_the_scoring_session_end_clears_it(self):
        o = self.c.o
        o.prev_tgt_idx = 3
        self.MI.discard_scoring_session(o)
        self.assertEqual(o.prev_tgt_idx, -1)

    def test_the_generation_boundary_clears_it(self):
        o = self.c.o
        o.prev_tgt_idx = 3
        self.MI.discard_generation_state(o)
        self.assertEqual(o.prev_tgt_idx, -1)
        o.prev_tgt_idx = 3
        o.reset_generation_state()                                           # F5 / scenario reload / close go through the generation boundary
        self.assertEqual(o.prev_tgt_idx, -1)

    def test_an_old_value_after_a_generation_boundary_is_not_used(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=1)
        o.reset_generation_state()
        self.assertEqual(o.prev_tgt_idx, -1)

    def test_an_old_value_after_a_jump_is_rejected_by_the_position(self):
        o = self.c.scene(self.abcd(), 2000.0, prev_tgt=1)                    # kept for B, then a jump moved the train to C: the settle copied the new NEXTLOC
        self.assertEqual(o.prev_next_loc, 2000.0)
        self.c.departure(2000.0, 3000.0, 1, tgt_after=3)
        self.assertEqual(self.timing(), [])
        self.assertEqual(self.c.missing("P02")[0]["cls"], "position_mismatch")


# ======================================================================================================================================================
# D. the diagnostics of P02
# ======================================================================================================================================================
class D_Diagnostics(Base):
    def test_a_missing_index_in_a_running_session_is_unexpected_missing_with_the_effect(self):
        self.left(self.abcd(), 1000.0, 2000.0, -1, 2)
        got = self.c.missing("P02")
        self.assertEqual(len(got), 1)
        f = got[0]
        self.assertEqual((f["site"], f["a"], f["cls"], f["action"], f["effect"]), ("P02", "P02", "unexpected_missing", "skip", EFFECT_P02))
        self.assertEqual((f["prev_tgt"], f["tgt"], f["scoring"]), (-1, 2, 1))

    def test_a_position_mismatch_carries_the_effect_and_the_mismatching_index(self):
        self.left(self.abcd(), 1000.0, 2000.0, 2, 2)
        f = self.c.missing("P02")[0]
        self.assertEqual((f["cls"], f["action"], f["effect"], f["prev_tgt"]), ("position_mismatch", "skip", EFFECT_P02, 2))

    def test_the_run_has_one_start_and_one_end(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
        self.c.departure(1000.0, 2000.0, -1, tgt_after=2)                    # start
        self.assertEqual((len(self.c.missing("P02")), len(self.c.missing_end("P02"))), (1, 0))
        o.has_scored_time_this_station = False
        o.bve_next_loc = 2000.0
        o.prev_next_loc = 2000.0
        self.c.departure(2000.0, 3000.0, 2, tgt_after=3)                     # a verified departure: the run ends
        self.assertEqual((len(self.c.missing("P02")), len(self.c.missing_end("P02"))), (1, 1))
        self.assertEqual(self.c.missing_end("P02")[0]["recovery"], "established")

    def test_a_missing_index_inside_an_official_jump_window_is_expected_unavailable(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
        o.is_official_jumping = True
        self.c.departure(1000.0, 2000.0, -1, tgt_after=2)
        self.assertEqual(self.c.missing("P02")[0]["cls"], "expected_unavailable")
        self.assertEqual(self.timing(), [])

    def test_with_the_session_off_and_a_usable_identity_it_is_contractual_none(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
        o.is_scoring_mode = False
        self.X.decision_target_none(o)                                       # a usable identity whose target is none (what a READY sender publishes)
        self.S.evaluate_departure(o, 50.0)
        self.assertEqual(self.c.missing("P02")[0]["cls"], "contractual_none")

    def test_nothing_is_reported_where_no_score_would_have_been_made_anyway(self):
        for name, value in (("is_first_station", True), ("ignore_next_pass_score", True), ("jump_lock", True)):
            self.fresh()
            o = self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
            setattr(o, name, value)
            o.prev_next_loc = 1000.0
            self.S.evaluate_departure(o, 50.0)
            self.assertEqual(self.c.missing("P02"), [], name)
            self.assertEqual(self.timing(), [], name)

    def test_a_finished_scoring_reports_nothing_and_scores_nothing(self):
        o = self.c.scene(self.abcd(), 1000.0, prev_tgt=1)
        o.is_scoring_finished = True
        self.S.evaluate_departure(o, 50.0)
        self.assertEqual((self.timing(), self.c.missing("P02")), ([], []))

    def test_the_normal_mode_has_the_same_safe_behaviour_and_no_diagnostic(self):
        self.left(self.abcd(), 1000.0, 2000.0, 2, 2)                         # a mismatch
        managed = self.timing()
        self.fresh()
        self.c.o.input_event_sink = None
        self.left(self.abcd(), 1000.0, 2000.0, 2, 2)
        self.c.o.input_event_sink = None
        self.assertEqual(self.timing(), managed)
        self.assertEqual(self.c.events, [])
        self.fresh()
        self.left(self.abcd(), 1000.0, 2000.0, 1, 2)                         # a verified departure scores the same in both
        managed_ok = self.timing()
        self.fresh()
        self.c.o.input_event_sink = None
        self.left(self.abcd(), 1000.0, 2000.0, 1, 2)
        self.assertEqual(self.timing(), managed_ok)
        self.assertEqual(len(managed_ok), 1)

    def test_neither_mode_writes_anything_else_for_a_missing_or_mismatching_index(self):
        from unittest import mock
        for sink_off in (False, True):                                       # managed (sink installed) and normal (no sink)
            for prev_tgt in (-1, 2):                                         # a missing index and a position mismatch
                self.fresh()
                if sink_off:
                    self.c.o.input_event_sink = None
                emit = mock.Mock()
                if sink_off:
                    self.c.o._emit_input_event = emit                                       # the normal mode emits nothing at all
                with mock.patch.object(self.S, "write_desktop_log") as log:
                    self.left(self.abcd(), 1000.0, 2000.0, prev_tgt, 2)
                    if sink_off:
                        self.c.o.input_event_sink = None
                self.assertEqual(log.call_count, 0, (sink_off, prev_tgt))
                self.assertEqual(emit.call_count, 0, (sink_off, prev_tgt))
                self.assertEqual(self.timing(), [], (sink_off, prev_tgt))
                self.assertEqual(len(self.c.missing("P02")), 0 if sink_off else 1, (sink_off, prev_tgt))

    def test_no_event_is_written_for_a_verified_departure(self):
        self.left(self.abcd(), 1000.0, 2000.0, 1, 2)
        self.assertEqual([e for e in self.c.events if e[0] in (self.X.EVENT, self.X.EVENT_END)], [])


# ======================================================================================================================================================
# E. static
# ======================================================================================================================================================
class E_Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read_src("scoring_logic.py")
        cls.tree = ast.parse(cls.text)
        cls.departure = ast.get_source_segment(cls.text, function_node(cls.tree, "evaluate_departure"))
        cls.update = ast.get_source_segment(cls.text, function_node(cls.tree, "update_physics_and_scoring"))

    def test_p02_reads_prev_tgt_idx_and_verifies_it_within_one_centimetre(self):
        self.assertIn("getattr(self, 'prev_tgt_idx', -1)", self.departure)
        self.assertEqual(len(re.findall(r"<=\s*0\.01\b", self.departure)), 1)
        self.assertEqual(len(re.findall(r"abs\([^\n]*\)\s*<=?\s*1\.0", self.departure)), 0, "no 1 m tolerance in evaluate_departure")

    def test_p02_has_no_search_no_fallback_and_no_other_identity_source(self):
        self.assertNotRegex(self.departure, r"enumerate\(|\bfor\s+\w+(\s*,\s*\w+)?\s+in\b|\bmin\(|\bmax\(|\bsorted\(|\bnext\(|nearest|bve_tgt_idx\s*-\s*1|tgt_idx\s*-\s*1|official_index|official_state|bve_arr_idx")
        self.assertNotRegex(self.departure, r"\.index\(|by_position|find_station|station_at")

    def test_p02_notes_the_site_and_the_effect_once_each(self):
        self.assertEqual(len(re.findall(r'note_missing\(self, "P02"', self.departure)), 1)
        self.assertEqual(len(re.findall(r'note_present\(self, "P02"', self.departure)), 1)
        self.assertEqual(self.text.count(EFFECT_P02), 1)
        self.assertEqual(len(re.findall(r"position_mismatch=", self.departure)), 1)

    def test_prev_tgt_idx_is_written_once_in_the_scoring_logic_beside_prev_next_loc_after_every_evaluation(self):
        self.assertEqual(len(re.findall(r"self\.prev_tgt_idx\s*=[^=]", self.text)), 1)
        lines = self.update.splitlines()
        at = [i for i, l in enumerate(lines) if re.match(r"\s+self\.prev_tgt_idx\s*=\s*self\.bve_tgt_idx\b", l)]
        self.assertEqual(len(at), 1)
        i = at[0]
        self.assertRegex(lines[i - 1], r"^\s+self\.prev_next_loc = self\.bve_next_loc$")          # directly after the NEXTLOC copy ...
        self.assertRegex(lines[i + 1], r"^\s+self\.prev_door = ")                                 # ... and before the other previous-tick values
        self.assertEqual(len(lines[i]) - len(lines[i].lstrip()), 4)                                # the tail of the function (not inside a branch)
        for call in ("evaluate_departure(self, current_time)", "evaluate_arrival("):
            self.assertLess(self.update.index(call), self.update.index(lines[i].strip()), call)    # every evaluation of the tick has read the old value first

    def test_main_and_managed_input_carry_only_the_default_and_the_clears(self):
        main, managed = read_src("main.py"), read_src("managed_input.py")
        self.assertEqual(re.findall(r"self\.prev_tgt_idx\s*=\s*[^\n]+", main), ["self.prev_tgt_idx = -1"])
        self.assertEqual(len(re.findall(r"prev_tgt_idx", main)), 1)
        self.assertEqual(len(re.findall(r'"prev_tgt_idx": -1', managed)), 1)
        self.assertEqual(len(re.findall(r'overlay\.prev_tgt_idx = d\["prev_tgt_idx"\]', managed)), 1)
        self.assertEqual(len(re.findall(r"prev_tgt_idx", managed)), 3)                  # the default, and the assignment that reads it (two names on one line)

    def test_retry_checkpoint_jump_and_closerange_do_not_know_prev_tgt_idx(self):
        for name in ("execute_retry", "create_save_data", "begin_official_jump", "update_close_range_departure_reset", "close_range_pair_is_close"):
            self.assertNotIn("prev_tgt_idx", ast.get_source_segment(self.text, function_node(self.tree, name)), name)
        main = read_src("main.py")
        settle = main[main.index("def _settle_jump_complete"):]
        settle = settle[:settle.index("\n    def ", 10)]
        self.assertNotIn("prev_tgt_idx", settle)
        for name in ("jump_transaction.py", "jump_wire.py", "station_identity.py", "station_index_contract.py", "official_target_contract.py", "hud_target_contract.py"):
            self.assertNotIn("prev_tgt_idx", read_src(name), name)

    def test_only_evaluate_departure_and_the_one_tail_line_know_prev_tgt_idx(self):
        owners = {}
        for fn in (n for n in self.tree.body if isinstance(n, ast.FunctionDef)):
            seg = ast.get_source_segment(self.text, fn)
            if "prev_tgt_idx" in seg:
                owners[fn.name] = len(re.findall(r"prev_tgt_idx", seg))
        self.assertEqual(sorted(owners), ["evaluate_departure", "update_physics_and_scoring"])
        self.assertEqual(owners["update_physics_and_scoring"], 1)                      # the mirror only: no gate, no other reader (CloseRange, Jump, the HUD and the rules never look at it)

    def test_the_station_identity_classifier_is_the_one_of_stage_a(self):
        blob = read_src("station_identity.py").encode("utf-8")
        self.assertEqual(hashlib.sha1(b"blob %d\0" % len(blob) + blob).hexdigest(), "2c971098059a6b8948cd842ed84af8ece9a054b9")

    def test_the_effect_words_of_all_five_sites_are_still_one_each(self):
        for word in ("suppress_terminal_evaluation", "suppress_departure_timing_evaluation", "suppress_timing_checkpoint_and_completion", "suppress_open_door_arrival_evaluation",
                     "hud_placeholder+keep_existing_rule_section"):
            self.assertEqual(self.text.count(word), 1, word)

    def test_no_one_metre_lookup_is_left_in_the_python_product(self):
        import red_si_r5_global_close_guard as G
        for name in G.python_product_files():
            with open(name, encoding="utf-8") as f:
                self.assertEqual(G.scan_python(f.read(), os.path.basename(name)), [], name)
        self.assertEqual(G.ALLOW_PY, {})


if __name__ == "__main__":
    unittest.main()
