"""Phase SI-R5.1 - the RED / GUARD fixation of the replacement of the five 1 m reverse lookups (Owner decision of 2026-10-29, OD-R5E-1..14 as answered).

NOT a discovery test (the name starts with red_): run it as   python -B tests/red_si_r5_station_identity.py [result.tsv]
Every test carries a kind:
    RED    must FAIL on the product of fd431b4 (the distance lookups) and must fail by a CONTRACT assertion; it passes on the replacement
    GUARD  must PASS on fd431b4 and keep passing on the replacement (non-regression, ownership, hold, boundaries)
The runner prints RED-VALID / RED-INVALID / GUARD-OK / GUARD-BROKEN / FIXTURE-INVALID / OLD-EXPECTATION / ERROR (as tests/red_close_range_contract.py).

THE CONTRACT (the scenes are in tests/si_r5_scene.py):
  identity     P01, P03, P04, P05 read bve_tgt_idx; P02 reads prev_tgt_idx (new, -1 initially, mirror of bve_tgt_idx at the end of every update_physics_and_scoring,
               cleared by Overlay.__init__, the generation defaults, discard_scoring_session) and uses it only when it is inside the list AND its station is within
               0.01 m of prev_next_loc; otherwise the departure station is -1 = no time score. Never: bve_tgt_idx - 1, nearest, 1 m, an older index, station 0.
  a missing identity   the identity-dependent step of THAT tick is skipped (P01 no end-station judgement; P02 no time score; P03 '---' and the rule section is NOT changed
               by a station guess; P04 no pre-arrival timing, no checkpoint, no scoring end, nothing recorded as scored; P05 no door-open arrival evaluation).
  classification   the skip is reported as the event stidx-missing-index (fields: tests/si_r5_scene.REQUIRED_FIELDS) with cls =
               expected_unavailable  generation start / reload / F5 re-initialization / an official jump window            (a PASS candidate inside the lifecycle window only)
               contractual_none      no scenario loaded / scoring session off with a usable identity / scoring finished (a formal terminal)   (PASS)
               unexpected_missing    a running scoring session, steady state: normal running, hold, departure, door-open arrival, checkpoint   (PRODUCT FAIL candidate)
               position_mismatch     P02 only: prev_tgt_idx is valid but its station is not at prev_next_loc                                  (PRODUCT FAIL candidate in a running session)
               and stidx-missing-end (site, ticks) when the same site finds its identity again.
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

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

_TMP = {}


class PremiseBroken(Exception):
    """A premise of the scene did not hold: the fixture, not the contract, is at fault."""


def premise(cond, why):
    if not cond:
        raise PremiseBroken(why)


def contract(cond, why):
    if not cond:
        raise AssertionError("CONTRACT: " + why)


def case(kind, req, group="CORE", note=""):
    assert kind in ("RED", "GUARD")

    def deco(fn):
        fn.rc = {"kind": kind, "req": req, "group": group, "note": note}
        return fn
    return deco


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-si-r5-red-")
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


def function_source(text, name):
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node)
    raise PremiseBroken("function not found: " + name)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["si-r5-red"])
        import main
        import managed_input
        import scoring_logic
        import si_r5_scene
        import sia_rig
        import station_identity
        cls.main, cls.S, cls.R, cls.X, cls.MI, cls.SI = main, scoring_logic, sia_rig, si_r5_scene, managed_input, station_identity

    def setUp(self):
        self.c = self.X.Scene(self.main, self.S, self.R)
        self.addCleanup(self.c.close)
        self.o = self.c.o

    # -- helpers -------------------------------------------------------------------------------------------------------------------------------
    def abcd(self):
        return self.X.abcd(self.R)

    def adj(self, **kw):
        return self.X.adjacent(self.R, **kw)

    def sta(self, name, loc, **kw):
        return self.X.sta(self.R, name, loc, **kw)

    def one_missing(self, site, cls):
        got = self.c.missing(site)
        contract(len(got) == 1, "exactly one stidx-missing-index event for %s (got %d)" % (site, len(got)))
        f = got[0]
        contract(f.get("cls") == cls, "%s is classified %s (got %s)" % (site, cls, f.get("cls")))
        contract(f.get("action") == "skip", "%s action=skip" % site)
        for k in self.X.REQUIRED_FIELDS:
            contract(k in f, "field %s is reported" % k)
        return f


# ======================================================================================================================================================
# P01 evaluate_arrival
# ======================================================================================================================================================
class A_P01(Base):
    @case("GUARD", "P01 a verified identity of a user-chosen end station ends the scoring at the door-open arrival", "P01")
    def test_G_P01_bound_end_station_finishes(self):
        o = self.c.scene(self.abcd(), 2000.0, end_idx=2)
        self.c.door_edge()
        premise(o.has_scored_stop_this_station, "the arrival ran")
        self.assertTrue(o.is_scoring_finished)

    @case("RED", "P01 identity missing -> no end-station judgement (evaluate_arrival called directly)", "P01")
    def test_R_P01_missing_identity_no_end_judgement(self):
        o = self.c.scene(self.abcd(), 2000.0, end_idx=2, tgt=-1, arr=2)
        self.S.evaluate_arrival(o, 50.0)
        contract(not o.is_scoring_finished, "bve_tgt_idx = -1 must not end the scoring (HEAD finds the station by distance)")

    @case("RED", "P01 identity missing never falls back to station 0 (a scoring end station that is index 0 at the target position)", "P01")
    def test_R_P01_missing_identity_no_station0_fallback(self):
        o = self.c.scene(self.abcd(), 0.0, end_idx=0, tgt=-1, arr=0)
        self.S.evaluate_arrival(o, 50.0)
        contract(not o.is_scoring_finished, "bve_tgt_idx = -1 must not name station 0 (HEAD finds it by distance)")

    @case("RED", "P01 adjacent stations B@1000 / C@1000.5 with target C: the end station C is recognised (no lowest-index 1 m pick)", "P01")
    def test_R_P01_adjacent_pair_names_the_target(self):
        o = self.c.scene(self.adj(), 1000.5, end_idx=2, tgt=2, arr=2)
        self.S.evaluate_arrival(o, 50.0)
        contract(o.is_scoring_finished, "end station C (index 2) was not recognised: the lookup picked B")

    @case("RED", "P01 two stations at the SAME position: the target index decides, not the lowest index", "P01")
    def test_R_P01_same_place_names_the_target(self):
        o = self.c.scene(self.X.same_place(self.R), 1000.0, end_idx=2, tgt=2, arr=2)
        self.S.evaluate_arrival(o, 50.0)
        contract(o.is_scoring_finished, "end station C (index 2) was not recognised: the lookup picked B")

    @case("RED", "P01 reads bve_tgt_idx, not the arrival index (target C, arrival candidate B)", "P01")
    def test_R_P01_reads_the_target_not_the_arrival(self):
        o = self.c.scene(self.adj(), 1000.5, end_idx=2, tgt=2, arr=1)
        self.S.evaluate_arrival(o, 50.0)
        contract(o.is_scoring_finished, "bve_tgt_idx = 2 names the end station")


# ======================================================================================================================================================
# P02 evaluate_departure + prev_tgt_idx
# ======================================================================================================================================================
class B_P02(Base):
    def timing_popups(self):
        return self.c.popups("運転時分")

    @case("GUARD", "P02 a verified prev_tgt_idx scores the time of the station that was left", "P02")
    def test_G_P02_bound_departure_scores_time(self):
        self.c.scene(self.abcd(), 1000.0, prev_tgt=1)
        self.c.departure(1000.0, 2000.0, 1, tgt_after=2)
        self.assertEqual(len(self.timing_popups()), 1)

    @case("GUARD", "P02 index 0 is an index like any other (a start station that is a timing station)", "P02")
    def test_G_P02_index0(self):
        o = self.c.scene(self.abcd(), 0.0, prev_tgt=0)
        o.setting_start_idx = 1
        self.c.departure(0.0, 1000.0, 0, tgt_after=1)
        self.assertEqual(len(self.timing_popups()), 1)

    @case("GUARD", "P02 a pass station that is a timing station is scored through prev_tgt_idx (Case 2 side)", "P02")
    def test_G_P02_pass_station(self):
        sl = [self.sta("A", 0.0), self.sta("B", 1000.0, is_pass=True), self.sta("C", 2000.0), self.sta("D", 3000.0, terminal=True)]
        self.c.scene(sl, 1000.0, prev_tgt=1)
        self.c.departure(1000.0, 2000.0, 1, tgt_after=2, prev_is_pass=1)
        self.assertEqual(len(self.timing_popups()), 1)

    @case("RED", "P02 adjacent B@1000 (not timing) / C@1000.5 (timing): leaving C scores C through prev_tgt_idx = 2", "P02")
    def test_R_P02_adjacent_pair_names_the_left_station(self):
        self.c.scene(self.adj(timing_b=False, timing_c=True), 1000.5, tgt=2, prev_tgt=2)
        self.c.departure(1000.5, 3000.0, 2, tgt_after=3)
        contract(len(self.timing_popups()) == 1, "the time of C was not scored: the lookup picked B (not a timing station)")

    @case("RED", "P02 prev_tgt_idx valid but its station is not at prev_next_loc (0.01 m): no time score", "P02")
    def test_R_P02_position_mismatch_no_time(self):
        self.c.scene(self.abcd(), 1000.0, prev_tgt=2)
        self.c.departure(1000.0, 2000.0, 2, tgt_after=2)
        contract(self.timing_popups() == [], "prev_tgt_idx = 2 (C) with prev_next_loc at B must not score (HEAD finds B by distance)")

    @case("RED", "P02 prev_tgt_idx = -1: no time score and bve_tgt_idx - 1 is NOT used", "P02")
    def test_R_P02_prev_missing_no_tgt_minus_one(self):
        self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
        self.c.departure(1000.0, 2000.0, -1, tgt_after=2)
        contract(self.timing_popups() == [], "no previous index: nothing may be derived from bve_tgt_idx (=2) or from the position")

    @case("RED", "P02 prev_tgt_idx outside the list: no time score, no fall-back to an older index or station 0", "P02")
    def test_R_P02_prev_out_of_range(self):
        for bad in (99, 4, -2):
            self.c.close()
            self.setUp()
            self.c.scene(self.abcd(), 1000.0, prev_tgt=bad)
            self.c.departure(1000.0, 2000.0, bad, tgt_after=2)
            contract(self.timing_popups() == [], "prev_tgt_idx = %d must not score" % bad)

    @case("RED", "prev_tgt_idx starts at -1 (Overlay.__init__)", "P02-state")
    def test_R_P02_init(self):
        contract(hasattr(self.o, "prev_tgt_idx"), "Overlay has no prev_tgt_idx")
        contract(self.o.prev_tgt_idx == -1, "initial value is -1")

    @case("RED", "prev_tgt_idx is a mirror of bve_tgt_idx written at the end of the tick (beside prev_next_loc)", "P02-state")
    def test_R_P02_mirror(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=2, arr=1, prev_tgt=-1)
        self.c.tick()
        contract(getattr(o, "prev_tgt_idx", None) == 2, "after a tick prev_tgt_idx = the bve_tgt_idx of that tick")

    @case("RED", "prev_tgt_idx follows a target anomaly: bve_tgt_idx = -1 at a tick clears it (no older index is kept)", "P02-state")
    def test_R_P02_anomaly_clears(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=2, arr=1)
        self.c.tick()
        o.bve_tgt_idx = -1
        self.c.tick()
        contract(getattr(o, "prev_tgt_idx", None) == -1, "an invalid target must clear prev_tgt_idx")

    @case("RED", "prev_tgt_idx is a generation default (-1) and a generation boundary clears it", "P02-state")
    def test_R_P02_generation_clear(self):
        contract(self.MI.generation_defaults().get("prev_tgt_idx") == -1, "generation_defaults()['prev_tgt_idx'] == -1")
        self.o.prev_tgt_idx = 3
        self.MI.discard_generation_state(self.o)
        contract(self.o.prev_tgt_idx == -1, "discard_generation_state must clear it")

    @case("RED", "the end of the scoring session (soft OFF / Session OFF / F5 side) clears prev_tgt_idx", "P02-state")
    def test_R_P02_session_end_clear(self):
        self.o.prev_tgt_idx = 3
        self.MI.discard_scoring_session(self.o)
        contract(getattr(self.o, "prev_tgt_idx", None) == -1, "discard_scoring_session must clear it")

    @case("GUARD", "a generation boundary leaves no bve_tgt_idx / bve_arr_idx of the old scenario", "P02-state")
    def test_G_generation_clears_the_published_indexes(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=1, arr=1)
        o.reset_generation_state()
        self.assertEqual((o.bve_tgt_idx, o.bve_arr_idx), (-1, -1))

    @case("GUARD", "after a generation boundary a door-open edge evaluates nothing (no old index is used)", "P02-state")
    def test_G_generation_then_door_edge_evaluates_nothing(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=1, arr=1)
        o.reset_generation_state()
        o.bve_next_loc = 1000.0
        o.bve_location = 1000.0
        self.c.door_edge()
        self.assertEqual((self.c.popups(), len(o.save_data)), ([], 0))


# ======================================================================================================================================================
# P03 HUD next station / rule section
# ======================================================================================================================================================
class C_P03(Base):
    def hud(self, sl, loc, d=500.0, **kw):
        o = self.c.scene(sl, loc, d=d, speed=10.0, **kw)
        o.brake_rules = [{"end_idx": 1, "apply": "1段", "release": "1段"}, {"end_idx": -1, "apply": "2段", "release": "2段"}]
        o.penalty_init_rules = [{"apply": "ON①", "release": "ON①"}, {"apply": "OFF", "release": "OFF"}]
        o.active_rule_basic_apply = o.active_rule_basic_release = "SENTINEL"
        self.c.tick()
        return o

    @case("GUARD", "P03 a verified target index shows its station and selects its rule section", "P03")
    def test_G_P03_bound(self):
        o = self.hud(self.abcd(), 2000.0, tgt=2, arr=1)
        self.assertEqual((o.active_next_sta_name, o.active_rule_basic_apply), ("C", "2段"))

    @case("GUARD", "P03 index 0 and the last index are indexes like any other", "P03")
    def test_G_P03_boundaries(self):
        o = self.hud(self.abcd(), 0.0, d=100.0, tgt=0, arr=0)
        first = o.active_next_sta_name
        o.bve_next_loc, o.bve_tgt_idx, o.bve_location = 3000.0, 3, 2900.0
        self.c.tick()
        self.assertEqual((first, o.active_next_sta_name), ("A", "D"))

    @case("GUARD", "P03 NEXTLOC = -1 (no target at all) keeps the existing 'next unknown' convention: '---', first rule section", "P03")
    def test_G_P03_nextloc_none_convention(self):
        o = self.hud(self.abcd(), 2000.0)
        o.bve_next_loc = -1.0
        self.c.tick()
        self.assertEqual((o.active_next_sta_name, o.active_rule_basic_apply), ("---", "1段"))

    @case("GUARD", "P03 hold: the index of the target does not move over ticks while it is held (operational stop / mis-pass)", "P03")
    def test_G_P03_hold_is_constant(self):
        o = self.hud(self.abcd(), 1000.0, d=0.0, tgt=1, arr=1)
        names = []
        for _ in range(5):
            self.c.tick()
            names.append((o.active_next_sta_name, o.active_rule_basic_apply))
        self.assertEqual(set(names), {("B", "1段")})

    @case("GUARD", "P03 ownership: the official target does not overwrite the scoring target while the scoring runs", "P03")
    def test_G_P03_official_does_not_override(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=2, arr=1)
        o.official_state, o.official_index, o.official_location = "KNOWN", 3, 3000.0
        self.c.tick()
        self.assertEqual((o.active_next_sta_name, o.bve_tgt_idx), ("C", 2))

    @case("GUARD", "P03 Case 2: a pass station between two stops is shown when it is the target", "P03")
    def test_G_P03_pass_station_target(self):
        sl = [self.sta("A", 0.0), self.sta("P", 1500.0, is_pass=True), self.sta("C", 2000.0), self.sta("D", 3000.0, terminal=True)]
        o = self.hud(sl, 1500.0, tgt=1, arr=0)
        self.assertEqual(o.active_next_sta_name, "P")

    @case("RED", "P03 adjacent B@1000 / C@1000.5 with target C shows C and selects the rule of C", "P03")
    def test_R_P03_adjacent_pair(self):
        o = self.hud(self.adj(), 1000.5, d=300.0, tgt=2, arr=1)
        contract(o.active_next_sta_name == "C", "HUD next station is %r, not C (lowest-index 1 m pick)" % o.active_next_sta_name)
        contract(o.active_rule_basic_apply == "2段", "the rule section of C (index 2 > end_idx 1) is the second")

    @case("RED", "P03 identity missing -> '---', timing False, and the rule section is NOT changed by a station guess", "P03")
    def test_R_P03_missing(self):
        o = self.hud(self.abcd(), 2000.0, tgt=-1, arr=-1)
        contract(o.active_next_sta_name == "---", "HUD next station is %r (HEAD finds it by distance)" % o.active_next_sta_name)
        contract(o.active_next_sta_timing is False, "timing label off")
        contract(o.active_rule_basic_apply == "SENTINEL", "the rule section was recomputed (compare_idx 0 / distance); it must stay as it was")

    @case("RED", "P03 index outside the list -> '---', rule section unchanged", "P03")
    def test_R_P03_out_of_range(self):
        o = self.hud(self.abcd(), 2000.0, tgt=99, arr=1)
        contract(o.active_next_sta_name == "---" and o.active_rule_basic_apply == "SENTINEL", "an index outside the list names no station (got %r / %r)" % (o.active_next_sta_name, o.active_rule_basic_apply))


# ======================================================================================================================================================
# P04 operational-stop pre-arrival timing + the explicit gate
# ======================================================================================================================================================
class D_P04(Base):
    @case("GUARD", "P04 operational stop with a verified identity: one checkpoint of the right station, the latch names it, and it stays so while held", "P04")
    def test_G_P04_hold_five_ticks(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0)
        self.c.operational_arrival(5)
        self.assertEqual((self.c.checkpoints(), o.operational_stop_latch[0]), ([0, 1], 1))

    @case("GUARD", "P04 operational stop at the user-chosen end station ends the scoring", "P04")
    def test_G_P04_end_station(self):
        o = self.c.scene(self.abcd(), 2000.0, doordir=0, end_idx=2)
        self.c.operational_arrival()
        self.assertTrue(o.is_scoring_finished)

    @case("RED", "P04 adjacent end station C@1000.5: the arrival time of the END station is scored and the scoring ends", "P04")
    def test_R_P04_adjacent_end_station(self):
        o = self.c.scene(self.adj(), 1000.5, doordir=0, end_idx=2, tgt=2, arr=2)
        o.bve_next_time = o.bve_time_ms + 5000
        self.c.operational_arrival()
        contract(o.is_scoring_finished, "the end station C was not recognised (lookup picked B)")
        contract(len(self.c.popups("運転時分")) == 1, "the arrival time of the end station was not scored")

    @case("RED", "P04 gate: identity missing at an operational stop -> no timing, no checkpoint, no scoring end, nothing recorded as scored", "P04")
    def test_R_P04_missing_gate(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(3)
        contract(self.c.checkpoints() == [0], "a checkpoint was created without a target identity: %r" % (self.c.checkpoints(),))
        contract(not o.has_scored_stop_this_station, "the stop was recorded as scored")
        contract(getattr(o, "operational_stop_latch", None) is None, "a latch was written")
        contract(self.c.popups("停止位置") == [], "a stop-position score was given")

    @case("RED", "P04 gate at the END station: no scoring end and no checkpoint-only state (the end station is not a checkpoint)", "P04")
    def test_R_P04_missing_end_station(self):
        o = self.c.scene(self.abcd(), 2000.0, doordir=0, end_idx=2, tgt=-1, arr=2)
        self.c.operational_arrival(3)
        contract(not o.is_scoring_finished, "the scoring ended without a target identity")
        contract(self.c.checkpoints() == [0], "a checkpoint was created at the end station")

    @case("RED", "P04 the gate is level-triggered: when the identity returns the arrival is evaluated once (one checkpoint, right station)", "P04")
    def test_R_P04_missing_then_recovered(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(3)
        contract(self.c.checkpoints() == [0], "nothing may be created while the identity is missing")
        o.bve_tgt_idx = 1
        self.c.tick(2)
        contract(self.c.checkpoints() == [0, 1], "after the identity returned exactly one checkpoint of station 1 (got %r)" % (self.c.checkpoints(),))


# ======================================================================================================================================================
# P05 normal-stop door-open arrival
# ======================================================================================================================================================
class E_P05(Base):
    @case("GUARD", "P05 a verified identity: the door-open arrival scores, makes the checkpoint of the station, and a terminal end station ends the scoring", "P05")
    def test_G_P05_bound(self):
        o = self.c.scene(self.abcd(), 1000.0)
        self.c.door_edge()
        self.assertEqual((self.c.checkpoints(), len(self.c.popups("停止位置"))), ([0, 1], 1))
        self.c.close(); self.setUp()
        o = self.c.scene(self.abcd(), 3000.0)
        self.c.door_edge()
        self.assertTrue(o.is_scoring_finished)

    @case("GUARD", "P05 index 0 is an index like any other", "P05")
    def test_G_P05_index0(self):
        o = self.c.scene(self.abcd(), 0.0)
        o.save_data = []
        self.c.door_edge()
        self.assertTrue(o.has_scored_stop_this_station)

    @case("GUARD", "P05 ownership: the official target does not move the door-open arrival to another station", "P05")
    def test_G_P05_official_does_not_override(self):
        o = self.c.scene(self.abcd(), 1000.0, end_idx=1, tgt=1, arr=1)
        o.official_state, o.official_index, o.official_location = "KNOWN", 3, 3000.0
        self.c.door_edge()
        self.assertTrue(o.is_scoring_finished)

    @case("RED", "P05 adjacent B@1000 / C@1000.5 with target C: the arrival is C's (end-station C recognised)", "P05")
    def test_R_P05_adjacent_pair(self):
        o = self.c.scene(self.adj(), 1000.5, end_idx=2, tgt=2, arr=2)
        self.c.door_edge()
        contract(o.is_scoring_finished, "the door-open arrival was attached to B (lowest index within 1 m)")

    @case("RED", "P05 two stations at the same position: the target index decides", "P05")
    def test_R_P05_same_place(self):
        o = self.c.scene(self.X.same_place(self.R), 1000.0, end_idx=2, tgt=2, arr=2)
        self.c.door_edge()
        contract(o.is_scoring_finished, "the door-open arrival was attached to B (lowest index)")

    @case("RED", "P05 identity missing -> the door-open arrival is not evaluated (no stop score, no checkpoint, not recorded as scored)", "P05")
    def test_R_P05_missing(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        self.c.door_edge()
        contract(self.c.popups() == [] and self.c.checkpoints() == [0], "an arrival was evaluated without a target identity (popups %r, checkpoints %r)" % (self.c.popups(), self.c.checkpoints()))
        contract(not o.has_scored_stop_this_station, "recorded as scored")

    @case("RED", "P05 index outside the list -> not evaluated (no station is chosen)", "P05")
    def test_R_P05_out_of_range(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=99, arr=1)
        self.c.door_edge()
        contract(self.c.popups() == [] and not o.has_scored_stop_this_station, "an arrival was evaluated for an index outside the list")

    @case("RED", "terminal none: a target 'none' at the old terminal position does not end the scoring by position", "P05")
    def test_R_P05_terminal_none(self):
        o = self.c.scene(self.abcd(), 3000.0, end_idx=3, arr=3)
        self.X.decision_target_none(o)
        premise(o.bve_tgt_idx == -1 and o.bve_arr_idx == 3, "a usable identity with target none")
        self.c.door_edge()
        contract(not o.is_scoring_finished and self.c.checkpoints() == [0], "the old terminal station was inferred from the position")

    @case("RED", "read failed / unusable identity: no other station is inferred", "P05")
    def test_R_P05_read_failed(self):
        o = self.c.scene(self.abcd(), 1000.0)
        self.X.decision_unavailable(o, self.SI.INTERNAL_ERROR)
        self.c.door_edge()
        contract(self.c.popups() == [] and self.c.checkpoints() == [0] and not o.has_scored_stop_this_station, "a station was inferred from the position")


# ======================================================================================================================================================
# the missing-index classification and the observation (diagnostics)
# ======================================================================================================================================================
class F_Diagnostics(Base):
    @case("GUARD", "a running scoring with every identity present reports NO missing-index event (the real-run audit counts zero)", "DIAG")
    def test_G_no_event_when_everything_is_bound(self):
        self.c.scene(self.abcd(), 1000.0)
        self.c.door_edge()
        self.c.departure(1000.0, 2000.0, 1, tgt_after=2)
        self.assertEqual([e for e in self.c.events if e[0] in (self.X.EVENT, self.X.EVENT_END)], [])

    @case("RED", "P01 missing in a running session is unexpected_missing", "DIAG")
    def test_R_diag_p01_unexpected(self):
        o = self.c.scene(self.abcd(), 2000.0, end_idx=2, tgt=-1, arr=2)
        self.S.evaluate_arrival(o, 50.0)
        f = self.one_missing("P01", "unexpected_missing")
        contract(f.get("scoring") == 1 and f.get("tgt") == -1, "scoring active and bve_tgt_idx recorded")

    @case("RED", "P02 missing prev_tgt_idx at a normal departure is unexpected_missing", "DIAG")
    def test_R_diag_p02_unexpected(self):
        self.c.scene(self.abcd(), 1000.0, prev_tgt=-1)
        self.c.departure(1000.0, 2000.0, -1, tgt_after=2)
        f = self.one_missing("P02", "unexpected_missing")
        contract(f.get("prev_tgt") == -1 and f.get("tgt") == 2, "prev_tgt_idx and bve_tgt_idx recorded")

    @case("RED", "P02 valid prev_tgt_idx whose station is not at prev_next_loc is position_mismatch", "DIAG")
    def test_R_diag_p02_position_mismatch(self):
        self.c.scene(self.abcd(), 1000.0, prev_tgt=2)
        self.c.departure(1000.0, 2000.0, 2, tgt_after=2)
        f = self.one_missing("P02", "position_mismatch")
        contract(f.get("prev_tgt") == 2, "the mismatching prev_tgt_idx is recorded")

    @case("RED", "P03 missing in a running session is unexpected_missing", "DIAG")
    def test_R_diag_p03_unexpected(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=-1, arr=-1)
        self.c.tick()
        self.one_missing("P03", "unexpected_missing")

    @case("RED", "P04 missing during an operational-stop hold is unexpected_missing (one event for the whole run of ticks)", "DIAG")
    def test_R_diag_p04_hold_unexpected(self):
        self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(4)
        self.one_missing("P04", "unexpected_missing")

    @case("RED", "P05 missing at the door-open edge is unexpected_missing", "DIAG")
    def test_R_diag_p05_edge_unexpected(self):
        self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        self.c.door_edge()
        self.one_missing("P05", "unexpected_missing")

    @case("RED", "generation start (scoring off, NOT_READY, baseline pending) is an expected_unavailable candidate", "DIAG")
    def test_R_diag_expected_generation_start(self):
        o = self.c.scene(self.abcd(), 1000.0)
        o.is_scoring_mode = False
        o.jump_baseline_pending = True
        self.X.decision_unavailable(o, self.SI.NOT_READY)
        self.c.door_edge()
        f = self.one_missing("P05", "expected_unavailable")
        contract(f.get("why") == "not-ready", "the reason of the decision is reported")

    @case("RED", "scoring off after F5 / session end with an unusable identity is an expected_unavailable candidate", "DIAG")
    def test_R_diag_expected_after_f5(self):
        o = self.c.scene(self.abcd(), 1000.0)
        self.MI.discard_scoring_session(o)
        self.X.decision_unavailable(o, self.SI.LIST_MISMATCH)
        self.c.door_edge()
        self.one_missing("P05", "expected_unavailable")

    @case("RED", "an official jump window (Retry / start) in a running session is an expected_unavailable candidate", "DIAG")
    def test_R_diag_expected_official_jump_window(self):
        o = self.c.scene(self.abcd(), 2000.0, d=500.0, speed=10.0, tgt=-1, arr=-1)
        o.is_official_jumping = True
        self.c.tick()
        self.one_missing("P03", "expected_unavailable")

    @case("RED", "a formal terminal-none (scoring finished) is contractual_none", "DIAG")
    def test_R_diag_contractual_terminal_none(self):
        o = self.c.scene(self.abcd(), 3000.0, end_idx=3, tgt=-1, arr=3)
        o.is_scoring_finished = True
        self.c.door_edge()
        self.one_missing("P05", "contractual_none")

    @case("RED", "no scenario loaded (empty list, scenario id -1) is contractual_none", "DIAG")
    def test_R_diag_contractual_not_loaded(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=-1)
        o.is_scoring_mode = False
        o.station_list = self.SI.StationList([], "")
        o.current_scenario_id = -1
        self.c.door_edge()
        self.one_missing("P05", "contractual_none")

    @case("RED", "scoring session off with a USABLE identity whose target is none is contractual_none", "DIAG")
    def test_R_diag_contractual_session_off(self):
        o = self.c.scene(self.abcd(), 3000.0, end_idx=3, arr=3)
        o.is_scoring_mode = False
        self.X.decision_target_none(o)
        self.c.door_edge()
        self.one_missing("P05", "contractual_none")

    @case("RED", "run length is observable: one event on the first skipped tick, one stidx-missing-end with the tick count when the identity returns", "DIAG")
    def test_R_diag_run_length_and_recovery(self):
        o = self.c.scene(self.abcd(), 1000.0, doordir=0, tgt=-1, arr=1)
        self.c.operational_arrival(3)
        o.bve_tgt_idx = 1
        self.c.tick(2)
        self.one_missing("P04", "unexpected_missing")
        ends = self.c.missing_end("P04")
        contract(len(ends) == 1, "one stidx-missing-end for P04 (got %d)" % len(ends))
        contract(ends[0].get("ticks") == 3, "the skipped tick count is reported (got %r)" % ends[0].get("ticks"))

    @case("RED", "the observation names no replacement: no event field carries a station name or a chosen index", "DIAG")
    def test_R_diag_names_no_replacement(self):
        o = self.c.scene(self.abcd(), 1000.0, tgt=-1, arr=1)
        self.c.door_edge()
        f = self.one_missing("P05", "unexpected_missing")
        for k, v in f.items():
            contract(not (isinstance(v, str) and v in ("A", "B", "C", "D")), "field %s carries a station name" % k)
        contract(not any(k in f for k in ("chosen", "idx", "station", "name")), "a replacement is reported")
        contract(not o.has_scored_stop_this_station, "and nothing was evaluated")

    @case("RED", "the unexpected count of a run can be audited: two sites, two events, both unexpected_missing, none expected", "DIAG")
    def test_R_diag_audit_count(self):
        o = self.c.scene(self.abcd(), 1000.0, d=300.0, speed=10.0, tgt=-1, arr=1)
        self.c.tick()
        o.bve_speed = 0.0
        o.bve_location = 1000.0
        self.c.door_edge()
        got = sorted((f["site"], f["cls"]) for f in self.c.missing())
        contract(got == [("P03", "unexpected_missing"), ("P05", "unexpected_missing")], "got %r" % (got,))


# ======================================================================================================================================================
# the Characterization rows that the replacement changes on purpose (the NEW answers of tests/si_r5_char_pins.json)
# ======================================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class H_Characterization(Base):
    """One RED per CHANGED row: the observation of the scene equals the NEW pin (fails on fd431b4 by the HEAD answer)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import json
        import si_r5_char_scenarios
        import test_si_r5_characterization as T
        with open(os.path.join(HERE, "si_r5_char_pins.json"), encoding="utf-8") as f:
            cls.pins = json.load(f)
        cls.now = json.loads(json.dumps(si_r5_char_scenarios.run_all(cls.main, cls.S, cls.R)))
        cls.T = T


def _make_changed_row(name, meaning):
    def run(self):
        site = name.split("_")[0]
        keys = self.T.SITE_KEYS[site]
        got = {k: self.now[name][k] for k in keys if k in self.now[name]}
        want = {k: self.pins["new"][name][k] for k in keys if k in self.pins["new"][name]}
        contract(got == want, "%s [%s]: observed %r, the replacement answers %r" % (name, meaning, got, want))
    run.__name__ = "test_R_char_" + name
    return case("RED", "Characterization %s: %s" % (meaning, name), "CHAR")(run)


def _install_changed_rows():
    import json
    with open(os.path.join(HERE, "si_r5_char_pins.json"), encoding="utf-8") as f:
        pins = json.load(f)
    names = {}
    # the meaning table lives in the characterization test; it is read as text here so that this runner does not import PyQt6 at import time
    src = read_src(os.path.join("tests", "test_si_r5_characterization.py"))
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CHANGED":
            names = ast.literal_eval(node.value)
    for name, meaning in sorted(names.items()):
        setattr(H_Characterization, "test_R_char_" + name, _make_changed_row(name, meaning))


_install_changed_rows()

# ======================================================================================================================================================
# static: ownership, the retry/checkpoint contract, CloseRange, Current / Legacy
# ======================================================================================================================================================
class G_Static(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sl = read_src("scoring_logic.py")

    @case("RED", "S33 re-pin: scoring_logic.py assigns prev_tgt_idx exactly once (the mirror beside prev_next_loc)", "STATIC")
    def test_R_S33_prev_tgt_idx_single_mirror(self):
        found = re.findall(r"self\.prev_tgt_idx\s*=[^=][^\n]*", self.sl)
        contract(len(found) == 1, "assignments of prev_tgt_idx: %r" % (found,))

    @case("GUARD", "S33 kept: scoring_logic.py never assigns the sender's published indexes (bve_tgt_idx / bve_arr_idx / bve_arr_seq)", "STATIC")
    def test_G_S33_published_indexes_are_read_only(self):
        self.assertIsNone(re.search(r"self\.(bve_tgt_idx|bve_arr_idx|bve_arr_seq)\s*=[^=]", self.sl))

    @case("GUARD", "CloseRange is untouched: its state machine never mentions prev_tgt_idx or bve_tgt_idx", "STATIC")
    def test_G_close_range_does_not_use_the_new_state(self):
        for name in ("close_range_pair_is_close", "update_close_range_departure_reset", "close_range_fix_previous_stop", "init_basic_braking_state", "reset_station_evaluation_state"):
            src = function_source(self.sl, name)
            self.assertNotIn("prev_tgt_idx", src, name)
            self.assertNotIn("bve_tgt_idx", src, name)

    @case("GUARD", "Retry / checkpoint are not rebuilt from prev_tgt_idx or the target (the checkpoint StationIndex is the source)", "STATIC")
    def test_G_retry_and_checkpoint_do_not_use_the_target_index(self):
        for name in ("execute_retry", "create_save_data"):
            src = function_source(self.sl, name)
            self.assertNotIn("prev_tgt_idx", src, name)
            self.assertNotIn("bve_tgt_idx", src, name)

    @case("GUARD", "ownership: scoring_logic.py reads no official_* value (the scoring target is the machine target)", "STATIC")
    def test_G_scoring_does_not_read_official(self):
        self.assertIsNone(re.search(r"official_(state|index|location|reason|margin)", self.sl))

    @case("GUARD", "Current / Legacy: both senders write the STIDX part through the one wire builder (the Python contract is shared)", "STATIC")
    def test_G_current_and_legacy_share_the_wire(self):
        cur = read_src(os.path.join("TsScoringPlugin", "TsScoringPlugin", "Class1.cs"))
        leg = read_src(os.path.join("TsScoringPlugin", "Handshake", "Telemetry", "Legacy", "src", "LegacyTelemetrySession.cs"))
        self.assertIn("StationIndexWire.Fields(stidxTarget, stidxArrivalIndex", cur)
        self.assertIn("StationIndexWire.Value(sv.Index, timeline.ArrivalIndex", leg)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------------------------------------------------------------------------------
class _Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []

    def _row(self, test, outcome, detail):
        fn = getattr(test, test._testMethodName, None)
        rc = getattr(fn, "rc", {"kind": "?", "req": "", "group": "", "note": ""})
        kind = rc["kind"]
        if outcome == "pass":
            cls = "GUARD-OK" if kind == "GUARD" else "RED-INVALID"
        elif outcome == "fail":
            if detail.startswith("CONTRACT:"):
                cls = "RED-VALID" if kind == "RED" else "GUARD-BROKEN"
            else:
                cls = "OLD-EXPECTATION" if kind == "RED" else "GUARD-BROKEN"
        elif outcome == "premise":
            cls = "FIXTURE-INVALID"
        elif outcome == "skip":
            cls = "SKIPPED"
        else:
            cls = "ERROR"
        self.rows.append((test._testMethodName, kind, rc["group"], rc["req"], outcome, cls, detail.replace("\t", " ").replace("\n", " | ")[:300]))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._row(test, "pass", "")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._row(test, "fail", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        if isinstance(err[1], PremiseBroken):
            self._row(test, "premise", str(err[1]))
        else:
            self._row(test, "error", "%s: %s" % (err[0].__name__, err[1]))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._row(test, "skip", reason)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else None
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = _Result()
    suite.run(res)
    rows = sorted(res.rows, key=lambda r: r[0])
    lines = ["test\tkind\tgroup\trequirement\toutcome\tclassification\tdetail"] + ["\t".join(r) for r in rows]
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    counts = {}
    for r in rows:
        counts[r[5]] = counts.get(r[5], 0) + 1
    for r in rows:
        print("%-16s %-6s %-12s %s" % (r[5], r[1], r[2], r[0]))
    print("SUMMARY " + ", ".join("%s=%d" % kv for kv in sorted(counts.items())) + " total=%d" % len(rows))
    return 0 if all(r[5] in ("RED-VALID", "GUARD-OK") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
