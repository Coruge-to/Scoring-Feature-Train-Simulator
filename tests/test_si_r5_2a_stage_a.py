"""Phase SI-R5.2-A - the tests of Stage A of the replacement of the five 1 m reverse lookups: the missing-index CLASSIFIER (station_identity.py, pure), its managed
DIAGNOSTIC (the run tracker and the events stidx-missing-index / stidx-missing-end), and P03 (HUD next station / rule section) on bve_tgt_idx.

A discovery test (it passes). The REDs of the whole replacement stay in tests/red_si_r5_station_identity.py (P03 + its diagnostics + its Characterization rows are green
since this Stage, P01 / P02 / P04 / P05 stay RED until SI-R5.2-B / C). Classes A-C need no Qt; D uses the real Overlay offscreen (skipped without PyQt6); E is static.
Nothing here uses the rig's position default (sia_rig.bind_identity) and no scene searches a station list: the scenes name the indexes themselves (tests/si_r5_scene.py).
"""
import ast
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

import station_identity as SI  # noqa: E402

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-si-r5-2a-")
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


def classify(site=SI.SITE_P03, loaded=True, active=True, finished=False, usable=False, window=False, established=False, mismatch=False, ms=0.0, ticks=0):
    return SI.classify_missing(site, loaded, active, finished, usable, window, established, mismatch, ms, ticks)


# ======================================================================================================================================================
# A. the classifier (pure)
# ======================================================================================================================================================
class A_Classifier(unittest.TestCase):
    def test_the_four_classes_are_the_vocabulary(self):
        self.assertEqual(SI.MISSING_CLASSES, ("expected_unavailable", "contractual_none", "unexpected_missing", "position_mismatch"))

    def test_a_running_session_in_the_steady_state_is_unexpected_whatever_the_duration(self):
        for ms, ticks in ((0.0, 1), (500.0, 30), (5000.0, 400)):
            self.assertEqual(classify(ms=ms, ticks=ticks).cls, "unexpected_missing", (ms, ticks))

    def test_a_negative_target_alone_is_not_a_contractual_none(self):
        # the classifier does not even receive the index: "bve_tgt_idx < 0" is not an input of the contract; only the facts of the lifecycle are
        for usable in (False, True):
            self.assertEqual(classify(usable=usable).cls, "unexpected_missing")

    def test_contractual_none_has_three_causes(self):
        self.assertEqual(classify(loaded=False).cls, "contractual_none")                      # no scenario loaded
        self.assertEqual(classify(finished=True).cls, "contractual_none")                     # a formal terminal
        self.assertEqual(classify(active=False, usable=True).cls, "contractual_none")         # session off with a usable identity (the target is none by contract)
        self.assertEqual(classify(loaded=False, window=True).cls, "contractual_none")         # a window does not turn a contract into an expectation

    def test_an_open_window_before_the_first_index_is_expected(self):
        self.assertEqual(classify(window=True).cls, "expected_unavailable")
        self.assertEqual(classify(active=False, usable=False, window=True).cls, "expected_unavailable")

    def test_once_established_the_window_never_turns_expected_again(self):
        self.assertEqual(classify(window=True, established=True).cls, "unexpected_missing")

    def test_the_soft_warning_is_the_earlier_of_one_second_and_sixty_ticks(self):
        self.assertFalse(classify(window=True, ms=999.0, ticks=59).soft_warning)
        self.assertTrue(classify(window=True, ms=1000.0, ticks=1).soft_warning)
        self.assertTrue(classify(window=True, ms=1.0, ticks=60).soft_warning)
        self.assertEqual(classify(window=True, ms=1500.0, ticks=10).cls, "expected_unavailable")       # a soft warning keeps the class

    def test_the_hard_anomaly_is_the_earlier_of_two_seconds_and_120_ticks(self):
        self.assertEqual(classify(window=True, ms=1999.0, ticks=119).cls, "expected_unavailable")
        for ms, ticks in ((2000.0, 1), (1.0, 120)):
            got = classify(window=True, ms=ms, ticks=ticks)
            self.assertEqual((got.cls, got.hard_anomaly), ("unexpected_missing", True), (ms, ticks))

    def test_the_thresholds_are_the_contract_numbers(self):
        self.assertEqual((SI.SOFT_WARNING_MS, SI.SOFT_WARNING_TICKS, SI.HARD_ANOMALY_MS, SI.HARD_ANOMALY_TICKS), (1000.0, 60, 2000.0, 120))

    def test_a_site_that_would_lose_a_scoring_opportunity_is_never_expected_in_a_running_session(self):
        for site in (SI.SITE_P04, SI.SITE_P05):
            self.assertEqual(classify(site=site, window=True).cls, "unexpected_missing", site)
            self.assertEqual(classify(site=site, active=False, window=True).cls, "expected_unavailable", site)      # scoring off: no opportunity is lost
        for site in (SI.SITE_P01, SI.SITE_P02, SI.SITE_P03):
            self.assertEqual(classify(site=site, window=True).cls, "expected_unavailable", site)

    def test_a_position_mismatch_exists_for_p02_only_and_only_in_a_running_session(self):
        self.assertEqual(classify(site=SI.SITE_P02, mismatch=True).cls, "position_mismatch")
        self.assertEqual(classify(site=SI.SITE_P02, mismatch=True, window=True).cls, "position_mismatch")
        for site in (SI.SITE_P01, SI.SITE_P03, SI.SITE_P04, SI.SITE_P05):
            self.assertNotEqual(classify(site=site, mismatch=True).cls, "position_mismatch", site)
        self.assertEqual(classify(site=SI.SITE_P02, mismatch=True, finished=True).cls, "contractual_none")

    def test_bad_numbers_never_raise_and_never_count_as_time(self):
        for ms in (None, "x", float("nan"), float("inf"), -5.0, True):
            self.assertEqual(classify(window=True, ms=ms).cls, "expected_unavailable", repr(ms))
        for ticks in (None, "7", -3, 1.5, True):
            self.assertEqual(classify(window=True, ticks=ticks).cls, "expected_unavailable", repr(ticks))

    def test_index_in_list_is_a_bound_check_only(self):
        for index, count, ok in ((0, 4, True), (3, 4, True), (4, 4, False), (-1, 4, False), (0, 0, False), (True, 4, False), (1.0, 4, False), (None, 4, False), ("1", 4, False)):
            self.assertEqual(SI.index_in_list(index, count), ok, (index, count))

    def test_why_names_the_reason_and_never_a_station(self):
        usable = SI.decide({"ready": True, "scenario_id": 7, "list_id": "A1B2C3D4", "count": 1, "tgt_idx": -1, "arr_idx": 0, "arr_seq": 1}, 7,
                           SI.StationList([{"location": 0.0}], "A1B2C3D4"), 0.0)
        self.assertEqual(SI.missing_why("P03", SI.unavailable(SI.NOT_READY), 0, 4), "not-ready")
        self.assertEqual(SI.missing_why("P03", usable, -1, 4), "index-negative")
        self.assertEqual(SI.missing_why("P03", None, -1, 4), "index-negative")
        self.assertEqual(SI.missing_why("P03", None, 99, 4), "index-out-of-range")
        self.assertEqual(SI.missing_why("P02", None, 1, 4, position_mismatch=True), "location-mismatch")


class A2_ClassifierIsPure(unittest.TestCase):
    """The classifier section reads no station list, searches no position, makes no index and knows no official target."""
    SECTION = ("index_in_list", "classify_missing", "reinit_window_open", "missing_why", "missing_facts", "MissingTracker", "note_missing", "note_present", "note_not_required",
               "_emit_missing_events", "_list_text", "_positive")

    def nodes(self):
        tree = ast.parse(read_src("station_identity.py"))
        out = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in self.SECTION}
        self.assertEqual(sorted(out), sorted(self.SECTION))
        return out

    def test_no_loop_over_a_station_list_and_no_position_search(self):
        for name, node in self.nodes().items():
            for n in ast.walk(node):
                if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
                    src = ast.unparse(n)
                    self.assertNotRegex(src, r"station_list|stations\b|\[.location.\]", name)
                if isinstance(n, ast.Call):
                    fname = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
                    self.assertNotIn(fname, ("sorted", "index", "enumerate", "next", "abs"), name)
                    if fname in ("min", "max"):
                        self.assertEqual(n.keywords, [], name)                      # no choice by a key (a nearest / a lowest index)

    def test_no_official_target_no_index_creation_no_assignment_of_a_scoring_state(self):
        for name, node in self.nodes().items():
            src = ast.unparse(node)
            self.assertNotRegex(src, r"official_(state|index|location|reason|margin)", name)
            for n in ast.walk(node):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        text = ast.unparse(t)
                        # the only attribute the section ever writes on the application state is its own tracker
                        if text.startswith("state.") or text.startswith("self."):
                            self.assertTrue(text in ("state._missing_tracker", "self._sites") or text.startswith("self._sites["), (name, text))

    def test_the_global_close_guard_does_not_flag_the_classifier(self):
        import red_si_r5_global_close_guard as G
        self.assertEqual(G.scan_python(read_src("station_identity.py"), "station_identity.py"), [])


# ======================================================================================================================================================
# B. the run tracker (pure)
# ======================================================================================================================================================
def facts(site="P03", index=-1, window=False, active=True, finished=False, usable=False, scn=7, t=1000, loaded=True, mismatch=False, why="index-negative", prev=-1):
    return SI.MissingFacts(site, loaded, active, finished, usable, window, mismatch, why, index, prev, t, scn, "A1B2C3D4", 2500.0, 2500.0)


class B_Tracker(unittest.TestCase):
    def setUp(self):
        self.k = SI.MissingTracker()

    def test_a_run_is_one_event_at_its_start_and_one_end_when_the_index_is_back(self):
        got = self.k.missing(facts(), 1.0)
        self.assertEqual([e for e, _ in got], ["stidx-missing-index"])
        for i in range(30):
            self.assertEqual(self.k.missing(facts(), 1.0 + 0.016 * (i + 1)), [])
        end = self.k.present("P03", 7, False, 2.0, 5000)
        self.assertEqual([e for e, _ in end], ["stidx-missing-end"])
        f = end[0][1]
        self.assertEqual((f["site"], f["ticks"], f["recovery"], f["t"], f["cls"]), ("P03", 31, "established", 5000, "unexpected_missing"))
        self.assertEqual((f["a"], sorted(f)[0]), ("P03", "a"))
        self.assertEqual(f["elapsed_ms"], 1000)
        self.assertEqual(self.k.present("P03", 7, False, 2.1), [])                      # not twice

    def test_the_start_event_carries_the_required_fields_and_no_station_name(self):
        f = self.k.missing(facts(index=99, why="index-out-of-range"), 1.0, "hud_placeholder")[0][1]
        for key in ("a", "site", "cls", "why", "t", "scn", "list", "scoring", "session", "tgt", "prev_tgt", "nextloc", "prev_nextloc", "avail", "action", "soft", "hard", "effect"):
            self.assertIn(key, f)
        self.assertEqual(f["a"], f["site"])
        self.assertEqual(sorted(f)[0], "a")                               # emit_event sorts the fields: the short site field stays in the first 160 characters the Caller keeps
        self.assertEqual((f["site"], f["cls"], f["why"], f["tgt"], f["scoring"], f["session"], f["avail"], f["action"], f["soft"], f["hard"]),
                         ("P03", "unexpected_missing", "index-out-of-range", 99, 1, "active", 0, "skip", 0, 0))
        self.assertEqual((f["nextloc"], f["list"]), ("2500.00", "A1B2C3D4"))
        self.assertFalse(any(k in f for k in ("chosen", "idx", "station", "name")))
        line = "[MANAGED] event=%s pid=%d" % ("stidx-missing-index", 12345) + "".join(" %s=%s" % (k, f[k]) for k in sorted(f))
        self.assertIn("a=P03", line[:160])                                # the site survives the 160 characters of the Caller (the full line is the Python-side log)

    def test_a_change_inside_the_run_reports_again_but_the_run_keeps_counting(self):
        self.k.missing(facts(index=-1), 1.0)
        again = self.k.missing(facts(index=99, why="index-out-of-range"), 1.016)
        self.assertEqual(len(again), 1)
        end = self.k.present("P03", 7, False, 1.1)[0][1]
        self.assertEqual(end["ticks"], 2)

    def test_an_expected_window_reports_the_soft_warning_and_turns_unexpected_at_the_hard_limit(self):
        seen = []
        for tick in range(1, 131):
            for event, f in self.k.missing(facts(window=True), 10.0 + 0.016 * (tick - 1)):
                seen.append((tick, f["cls"], f["soft"], f["hard"]))
        self.assertEqual(seen[0], (1, "expected_unavailable", 0, 0))
        self.assertEqual(seen[1], (60, "expected_unavailable", 1, 0))
        self.assertEqual(seen[2], (120, "unexpected_missing", 1, 1))
        self.assertEqual(len(seen), 3)

    def test_the_real_time_wins_when_the_ticks_are_slow(self):
        seen = []
        for tick in range(1, 7):
            for event, f in self.k.missing(facts(window=True), 10.0 + 0.5 * (tick - 1)):
                seen.append((tick, f["cls"], f["soft"], f["hard"]))
        self.assertEqual(seen, [(1, "expected_unavailable", 0, 0), (3, "expected_unavailable", 1, 0), (5, "unexpected_missing", 1, 1)])

    def test_after_the_first_index_of_a_window_a_second_loss_in_the_same_window_is_unexpected(self):
        self.assertEqual(self.k.missing(facts(window=True), 1.0)[0][1]["cls"], "expected_unavailable")
        self.k.present("P03", 7, True, 1.1)                                              # established (the window is still open)
        again = self.k.missing(facts(window=True), 1.2)
        self.assertEqual(again[0][1]["cls"], "unexpected_missing")

    def test_a_valid_index_before_the_clear_does_not_consume_the_window(self):
        self.k.present("P03", 7, False, 1.0)
        self.k.missing(facts(window=False), 1.1)                                          # a steady loss opens a run (unexpected)
        self.k.present("P03", 7, False, 1.2)
        self.assertEqual(self.k.present("P03", 7, True, 2.0), [])                         # the window opens with the index still valid: armed, nothing consumed
        self.assertEqual(self.k.missing(facts(window=True), 2.1)[0][1]["cls"], "expected_unavailable")

    def test_a_new_window_is_armed_again(self):
        self.k.missing(facts(window=True), 1.0)
        self.k.present("P03", 7, True, 1.1)
        self.k.present("P03", 7, False, 1.2)                                              # the window closed (Jump Complete)
        self.k.present("P03", 7, True, 5.0)                                               # the next official jump
        self.assertEqual(self.k.missing(facts(window=True), 5.1)[0][1]["cls"], "expected_unavailable")

    def test_a_closing_window_turns_the_class_unexpected(self):
        self.k.missing(facts(window=True), 1.0)
        got = self.k.missing(facts(window=False), 1.1)                                    # Jump Complete without an index: no longer expected
        self.assertEqual(got[0][1]["cls"], "unexpected_missing")

    def test_a_scenario_change_drops_the_run_silently(self):
        self.k.missing(facts(scn=7), 1.0)
        self.assertEqual(self.k.present("P03", 8, False, 2.0), [])
        got = self.k.missing(facts(scn=8), 3.0)
        self.assertEqual(len(got), 1)
        end = self.k.present("P03", 8, False, 3.1)[0][1]
        self.assertEqual(end["ticks"], 1)

    def test_the_contract_none_ends_a_run_without_a_recovery(self):
        self.k.missing(facts(), 1.0)
        end = self.k.release("P03", 7, 1.5, 900)
        self.assertEqual([e for e, _ in end], ["stidx-missing-end"])
        self.assertEqual(end[0][1]["recovery"], "nextloc_none")
        self.assertEqual(self.k.release("P03", 7, 1.6), [])

    def test_the_time_going_backwards_never_gives_a_negative_duration(self):
        self.k.missing(facts(), 50.0)
        end = self.k.present("P03", 7, False, 10.0)[0][1]
        self.assertEqual(end["elapsed_ms"], 0)

    def test_the_sites_are_tracked_apart(self):
        self.k.missing(facts(site="P03"), 1.0)
        got = self.k.missing(facts(site="P05"), 1.0)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(self.k.present("P03", 7, False, 1.1)), 1)
        self.assertEqual(len(self.k.present("P05", 7, False, 1.1)), 1)

    def test_the_session_word(self):
        self.assertEqual(self.k.missing(facts(active=True), 1.0)[0][1]["session"], "active")
        k = SI.MissingTracker()
        self.assertEqual(k.missing(facts(active=True, finished=True), 1.0)[0][1]["session"], "finished")
        k = SI.MissingTracker()
        self.assertEqual(k.missing(facts(active=False, usable=True), 1.0)[0][1]["session"], "off")


# ======================================================================================================================================================
# C. note_* : the glue to the application state (managed only)
# ======================================================================================================================================================
class _State(object):
    def __init__(self, sink=True):
        self.events = []
        self.station_list = SI.StationList([{"location": 0.0}, {"location": 1000.0}], "A1B2C3D4")
        self.current_scenario_id = 7
        self.is_scoring_mode = True
        self.is_scoring_finished = False
        self.bve_time_ms = 12345
        self.bve_next_loc = 1000.0
        self.prev_next_loc = 1000.0
        if sink:
            self.input_event_sink = lambda event, **fields: self.events.append((event, dict(fields)))
            self._station_identity_note = lambda event, **fields: self.input_event_sink(event, **fields)


class C_Glue(unittest.TestCase):
    def test_the_normal_mode_keeps_nothing_and_writes_nothing(self):
        s = _State(sink=False)
        SI.note_missing(s, "P03", 1.0, -1)
        SI.note_present(s, "P03", 1.1)
        SI.note_not_required(s, "P03", 1.2)
        self.assertFalse(hasattr(s, "_missing_tracker"))
        self.assertEqual(s.events, [])

    def test_the_managed_mode_reports_and_ends(self):
        s = _State()
        SI.note_missing(s, "P03", 1.0, -1, "hud_placeholder")
        SI.note_missing(s, "P03", 1.016, -1, "hud_placeholder")
        SI.note_present(s, "P03", 1.032)
        self.assertEqual([e for e, _ in s.events], ["stidx-missing-index", "stidx-missing-end"])
        self.assertEqual(s.events[1][1]["ticks"], 2)

    def test_present_without_any_miss_creates_nothing(self):
        s = _State()
        SI.note_present(s, "P03", 1.0)
        SI.note_not_required(s, "P03", 1.0)
        self.assertFalse(hasattr(s, "_missing_tracker"))

    def test_a_broken_sink_never_raises_into_the_scoring(self):
        s = _State()

        def boom(event, **fields):
            raise RuntimeError("sink")
        s._station_identity_note = boom
        SI.note_missing(s, "P03", 1.0, -1)
        SI.note_present(s, "P03", 1.1)

    def test_a_state_without_the_fields_never_raises(self):
        class Bare(object):
            input_event_sink = staticmethod(lambda event, **fields: None)
        SI.note_missing(Bare(), "P03", 1.0, -1)
        SI.note_present(Bare(), "P03", 1.0)

    def test_the_window_is_read_from_the_flags_and_written_nowhere(self):
        s = _State()
        s.is_official_jumping = False
        s.jump_baseline_pending = False
        self.assertFalse(SI.reinit_window_open(s, True))
        s.is_official_jumping = True
        self.assertTrue(SI.reinit_window_open(s, True))
        s.is_official_jumping = False
        s.jump_baseline_pending = True
        self.assertTrue(SI.reinit_window_open(s, True))
        s.jump_baseline_pending = False
        s.is_scoring_mode = False
        self.assertTrue(SI.reinit_window_open(s, False))
        self.assertFalse(SI.reinit_window_open(s, True))
        self.assertEqual((s.is_official_jumping, s.jump_baseline_pending, s.is_scoring_mode), (False, False, False))


# ======================================================================================================================================================
# D. P03 on the real Overlay
# ======================================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class D_P03(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["si-r5-2a"])
        import main
        import scoring_logic
        import si_r5_scene
        import sia_rig
        cls.main, cls.S, cls.R, cls.X = main, scoring_logic, sia_rig, si_r5_scene

    def setUp(self):
        self.c = self.X.Scene(self.main, self.S, self.R)
        self.addCleanup(self.c.close)
        self.o = self.c.o

    def hud(self, stations=None, loc=2000.0, d=500.0, **kw):
        o = self.c.scene(stations or self.X.abcd(self.R), loc, d=d, speed=10.0, **kw)
        o.brake_rules = [{"end_idx": 1, "apply": "1段", "release": "1段"}, {"end_idx": -1, "apply": "2段", "release": "2段"}]
        o.penalty_init_rules = [{"apply": "ON①", "release": "ON①"}, {"apply": "OFF", "release": "OFF"}]
        o.active_rule_basic_apply = o.active_rule_basic_release = "SENTINEL"
        self.c.tick()
        return o

    def shown(self, o):
        return (o.active_next_sta_name, o.active_next_sta_timing, o.active_rule_basic_apply, o.active_rule_basic_release, o.active_rule_init_apply, o.active_rule_init_release)

    # -- ownership: bve_tgt_idx, nothing else ---------------------------------------------------------------------------------------------------
    def test_the_station_is_the_target_index_and_not_the_station_at_nextloc(self):
        o = self.hud(tgt=1, arr=1)                                      # NEXTLOC 2000 is C; the target says B
        self.assertEqual(o.active_next_sta_name, "B")
        self.assertEqual(o.active_rule_basic_apply, "1段")               # the rule section of index 1 (end_idx 1), not that of index 2

    def test_a_missing_index_never_falls_back_to_station_zero_or_the_station_at_nextloc(self):
        o = self.hud(self.X.abcd(self.R), 0.0, d=100.0, tgt=-1, arr=-1)  # NEXTLOC 0.0 is station A (index 0)
        self.assertEqual((o.active_next_sta_name, o.active_next_sta_timing, o.active_rule_basic_apply), ("---", False, "SENTINEL"))

    def test_a_missing_index_never_falls_back_to_the_previous_valid_index(self):
        o = self.hud(tgt=2, arr=1)
        self.assertEqual(o.active_next_sta_name, "C")
        o.bve_tgt_idx = -1
        self.c.tick()
        self.assertEqual(o.active_next_sta_name, "---")

    def test_the_official_target_is_never_used_instead(self):
        o = self.c.scene(self.X.abcd(self.R), 2000.0, d=500.0, speed=10.0, tgt=-1, arr=-1)
        o.official_state, o.official_index, o.official_location = "KNOWN", 3, 3000.0
        self.c.tick()
        self.assertEqual(o.active_next_sta_name, "---")
        self.assertEqual((o.official_index, o.official_location, o.bve_tgt_idx), (3, 3000.0, -1))

    def test_the_scoring_target_is_not_written_by_the_hud_step(self):
        o = self.hud(tgt=2, arr=1)
        self.assertEqual((o.bve_tgt_idx, o.bve_arr_idx, o.bve_next_loc), (2, 1, 2000.0))
        o.bve_tgt_idx = -1
        self.c.tick(3)
        self.assertEqual((o.bve_tgt_idx, o.bve_arr_idx, o.bve_next_loc), (-1, 1, 2000.0))

    def test_the_bound_index_of_a_bool_or_a_float_is_not_an_index(self):
        for bad in (True, 1.0, None, "1"):
            self.c.close()
            self.setUp()
            o = self.hud(tgt=2, arr=1)
            o.bve_tgt_idx = bad
            self.c.tick()
            self.assertEqual(o.active_next_sta_name, "---", repr(bad))

    def test_a_hold_keeps_the_station_of_the_held_target(self):
        o = self.hud(self.X.abcd(self.R), 1000.0, d=0.0, tgt=1, arr=1)
        names = set()
        for _ in range(10):
            self.c.tick()
            names.add((o.active_next_sta_name, o.active_rule_basic_apply))
        self.assertEqual(names, {("B", "1段")})

    def test_nextloc_none_keeps_the_existing_convention_and_reports_nothing(self):
        o = self.hud(tgt=2, arr=1)
        o.bve_next_loc = -1.0
        o.bve_tgt_idx = -1
        self.c.tick(3)
        self.assertEqual((o.active_next_sta_name, o.active_next_sta_timing, o.active_rule_basic_apply), ("---", False, "1段"))
        self.assertEqual(self.c.missing("P03"), [])

    def test_nextloc_none_with_a_valid_index_is_still_the_next_unknown_convention(self):
        o = self.hud(tgt=2, arr=1)
        o.bve_next_loc = -1.0
        self.c.tick()
        self.assertEqual((o.active_next_sta_name, o.active_rule_basic_apply), ("---", "1段"))

    def test_the_rule_section_is_kept_through_a_missing_run_and_recomputed_at_the_return(self):
        o = self.hud(tgt=2, arr=1)
        self.assertEqual(o.active_rule_basic_apply, "2段")
        o.bve_tgt_idx = -1
        self.c.tick(5)
        self.assertEqual(o.active_rule_basic_apply, "2段")               # kept, not reset to the first section
        o.bve_tgt_idx = 0
        o.bve_next_loc, o.bve_location = 0.0, -100.0
        self.c.tick()
        self.assertEqual((o.active_next_sta_name, o.active_rule_basic_apply), ("A", "1段"))

    # -- managed / normal parity ----------------------------------------------------------------------------------------------------------------
    def test_the_managed_and_the_normal_mode_skip_alike_and_only_the_managed_mode_reports(self):
        results = []
        for managed in (True, False):
            self.c.close()
            self.setUp()
            if not managed:
                self.o.input_event_sink = None
            o = self.hud(tgt=-1, arr=-1)
            self.c.tick(4)
            o.bve_tgt_idx = 2
            self.c.tick(2)
            results.append((self.shown(o), len(o.popups), o.score, tuple(o.station_list.__class__.__mro__[:1])))
            events = [e for e, _ in self.c.events]
            self.assertEqual(events, ["stidx-missing-index", "stidx-missing-end"] if managed else [])
            self.assertEqual(hasattr(o, "_missing_tracker"), managed)
        self.assertEqual(results[0], results[1])

    def test_a_failing_sink_changes_nothing_on_the_screen(self):
        def boom(event, **fields):
            raise RuntimeError("sink")
        self.o.input_event_sink = boom
        o = self.hud(tgt=-1, arr=-1)
        self.assertEqual((o.active_next_sta_name, o.active_rule_basic_apply), ("---", "SENTINEL"))

    # -- the diagnostic -------------------------------------------------------------------------------------------------------------------------
    def test_one_start_event_for_a_long_run_and_one_end_with_the_tick_count(self):
        o = self.hud(tgt=-1, arr=-1)
        self.c.tick(49)
        o.bve_tgt_idx = 2
        self.c.tick(2)
        got, ends = self.c.missing("P03"), self.c.missing_end("P03")
        self.assertEqual((len(got), len(ends)), (1, 1))
        self.assertEqual((ends[0]["ticks"], ends[0]["recovery"], ends[0]["cls"]), (50, "established", "unexpected_missing"))
        f = got[0]
        self.assertEqual((f["cls"], f["action"], f["session"], f["scoring"], f["tgt"], f["effect"]), ("unexpected_missing", "skip", "active", 1, -1, "hud_placeholder+keep_existing_rule_section"))

    def test_an_official_jump_window_is_expected_until_the_first_index_and_then_never_again(self):
        o = self.c.scene(self.X.abcd(self.R), 2000.0, d=500.0, speed=10.0, tgt=-1, arr=-1)
        o.is_official_jumping = True
        self.c.tick(3)
        self.assertEqual([f["cls"] for f in self.c.missing("P03")], ["expected_unavailable"])
        o.bve_tgt_idx = 2                                                  # the first valid index of the new generation
        self.c.tick(2)
        o.bve_tgt_idx = -1                                                 # lost again inside the same window
        self.c.tick(2)
        self.assertEqual([f["cls"] for f in self.c.missing("P03")], ["expected_unavailable", "unexpected_missing"])
        self.assertEqual(len(self.c.missing_end("P03")), 1)

    def test_an_official_jump_that_started_with_a_valid_index_is_still_expected_after_the_clear(self):
        o = self.c.scene(self.X.abcd(self.R), 2000.0, d=500.0, speed=10.0, tgt=2, arr=1)
        self.c.tick(2)
        o.is_official_jumping = True                                       # the request is made; the old indexes are still published for a moment
        self.c.tick(2)
        o.bve_tgt_idx = -1                                                 # the generation is re-initialized
        self.c.tick(3)
        self.assertEqual([f["cls"] for f in self.c.missing("P03")], ["expected_unavailable"])

    def test_an_expected_window_that_does_not_close_turns_unexpected_at_the_hard_limit(self):
        o = self.c.scene(self.X.abcd(self.R), 2000.0, d=500.0, speed=10.0, tgt=-1, arr=-1)
        o.is_official_jumping = True
        self.c.tick(125)
        got = self.c.missing("P03")
        self.assertEqual([(f["cls"], f["soft"], f["hard"]) for f in got], [("expected_unavailable", 0, 0), ("expected_unavailable", 1, 0), ("unexpected_missing", 1, 1)])

    def test_a_finished_session_reports_a_contractual_none(self):
        o = self.c.scene(self.X.abcd(self.R), 3000.0, d=100.0, speed=0.0, tgt=-1, arr=3)
        o.is_scoring_finished = True
        self.c.tick()
        self.assertEqual([(f["cls"], f["session"]) for f in self.c.missing("P03")], [("contractual_none", "finished")])
        self.assertEqual(o.active_next_sta_name, "---")

    def test_nothing_is_reported_when_every_index_is_bound(self):
        self.hud(tgt=2, arr=1)
        self.c.tick(20)
        self.assertEqual([e for e in self.c.events if e[0] in (self.X.EVENT, self.X.EVENT_END)], [])


# ======================================================================================================================================================
# E. static: the Stage A boundaries
# ======================================================================================================================================================
def function_node(tree, name):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError("function not found: " + name)


class E_Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read_src("scoring_logic.py")
        cls.tree = ast.parse(cls.text)

    def test_p03_has_no_distance_lookup_and_reads_the_target_index(self):
        node = function_node(self.tree, "update_physics_and_scoring")
        src = ast.get_source_segment(self.text, node)
        self.assertEqual(len(re.findall(r"abs\(st\[.location.\]\s*-\s*self\.bve_next_loc\)", src)), 0)
        self.assertIn("bve_tgt_idx", src)
        self.assertIn("station_identity.index_in_list", src)
        self.assertNotRegex(src, r"official_(state|index|location|reason|margin)")

    def test_the_remaining_one_metre_lookup_is_exactly_the_one_of_stage_c(self):
        sites = {}
        for fn in (n for n in self.tree.body if isinstance(n, ast.FunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Compare) and isinstance(n.left, ast.Call) and getattr(n.left.func, "id", "") == "abs" and isinstance(n.ops[0], ast.Lt) \
                        and isinstance(n.comparators[0], ast.Constant) and n.comparators[0].value == 1.0 and "location" in ast.unparse(n.left):
                    sites[fn.name] = sites.get(fn.name, 0) + 1
        self.assertEqual(sites, {"evaluate_departure": 1})        # Phase SI-R5.2-B: P01, P04, P05 are gone; only P02 (Stage C) is left

    def test_the_global_close_guard_counts_the_one_old_lookup_of_stage_c(self):
        import red_si_r5_global_close_guard as G
        found = G.scan_python(self.text, "scoring_logic.py")
        self.assertEqual(sorted(k for k, _ in found), ["F1", "F5"])        # Phase SI-R5.2-B: 4 -> 1 (P02 only)
        owners = set()
        for _, line in found:
            for fn in (n for n in self.tree.body if isinstance(n, ast.FunctionDef)):
                if fn.lineno <= line <= fn.end_lineno:
                    owners.add(fn.name)
        self.assertEqual(owners, {"evaluate_departure"})
        self.assertEqual(G.ALLOW_PY, {})
        for name in ("station_identity.py", "main.py", "managed_input.py"):
            self.assertEqual(G.scan_python(read_src(name), name), [], name)

    def test_the_characterization_pins_stage_a_and_b_are_done(self):
        import test_si_r5_characterization as T
        self.assertEqual(T.STAGE_DONE, {"A", "B"})
        self.assertEqual(sorted(s for s, st in T.STAGE_OF_SITE.items() if st in T.STAGE_DONE), ["P03", "P04", "P05"])
        self.assertEqual(sorted(s for s, st in T.STAGE_OF_SITE.items() if st not in T.STAGE_DONE), ["P02"])

    def test_scoring_logic_gained_no_function_and_no_new_state(self):
        # the glue lives in station_identity; the stage touches update_physics_and_scoring only
        self.assertIsNone(re.search(r"_missing_tracker|MissingTracker|stidx-missing|def \w*missing\w*|def note_identity", self.text), "a tracker / event / helper definition in scoring_logic.py")
        self.assertIsNone(re.search(r"self\.(bve_tgt_idx|bve_arr_idx|bve_arr_seq|prev_tgt_idx)\s*=[^=]", self.text))

    def test_main_and_managed_input_gained_nothing(self):
        for name in ("main.py", "managed_input.py"):
            self.assertNotRegex(read_src(name), r"_missing_tracker|MissingTracker|note_missing|stidx-missing|prev_tgt_idx", name)


if __name__ == "__main__":
    unittest.main()
