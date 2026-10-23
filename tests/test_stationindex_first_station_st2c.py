"""Phase PID-D4JA StationIndex ST-2c - the CONTRACT tests of is_first_station (scoring_logic.update_physics_and_scoring, the first UDP line). Python only; nothing here builds,
starts a process or opens a socket.

What is_first_station IS (fixed by the audit of ST-2c; the audit documents are outside the repository)
  "the train still stands at the station where the scoring (or the retry to the first checkpoint of the history) began; that station is NOT an arrival". It is a latch:
    set    at the scoring start (main.py, after the identity of the start station was verified), at the Overlay start, and by execute_retry for the checkpoint at position 0
           of the history (the checkpoint whose role is "scoring_start", verified by station_identity.check_retry_checkpoint)
    reset  by the departure (speed >= 1 with the doors closed, not during a jump), by a change of NEXTLOC, and by execute_retry for any later position
  It never searched a station: the one distance test ("NEXTLOC more than 100 m from the train on the first UDP line clears the latch") is what ST-2c removes. The identity of the
  start station is verified at the places that SET the latch (N-01 / N-05 / T05 / T06 of the ST-2 canon) and again when the jump completes (ST-3d: selected_idx and the position,
  judged by jump_transaction.judge_completion); a train that is far from the station on the first line is simply a train that has not been jumped yet.

N-11   FIRST-STATION-100M-REMOVED        the latch does not depend on where the train is on the first UDP line (RED against 618d4b8)
G-xx   GUARD                             a contract that is GREEN before and after ST-2c and that keeps a mutation of the new code honest

Each RED fails with ContractViolation whose .code is the declared one against the product of 618d4b8 and passes against the product of ST-2c.

ISOLATION: as the files this one builds on (tests/sia_rig.py: the real Overlay offscreen, every outside effect a recorder, a stub UDP socket: 54321 / 54322 are never bound or
sent to). USERPROFILE / HOME point to an empty temporary folder for the whole module and the module asserts at its end that nothing was written there. The static tests (class
A_Static) need no Qt; the others are SKIPPED, never passed, when PyQt6 is not importable (python -I).
"""
import ast
import os
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

import sia_rig as R  # noqa: E402

T0 = 36000000
THIS_FILE = "tests/test_stationindex_first_station_st2c.py"

if HAS_QT:
    import test_char_stop_door_arrival_st0 as CH  # noqa: E402  (its rig only: Base.scene / tick drive update_physics_and_scoring)
    import test_stationindex_canon_st2 as C2  # noqa: E402  (its retry rig: RetryBase.run_retry / refusal / control)
    BaseScene, BaseRetry = CH.Base, C2.RetryBase
else:  # pragma: no cover
    BaseScene = BaseRetry = unittest.TestCase


class ContractViolation(AssertionError):
    """The product does not meet the contract; `code` names the violated clause."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST2C-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def st2c(tid, kind, code="", note=""):
    """Declare a test of ST-2c: its id, its kind ("RED": fails against 618d4b8 with `code`; "GUARD": green before and after) and one line."""
    assert kind in ("RED", "GUARD"), kind

    def deco(fn):
        fn.st2c = {"id": tid, "kind": kind, "code": code, "note": note}
        return fn
    return deco


class ContractMixin(object):
    def contract(self, ok, tid, code, detail=""):
        if not ok:
            raise ContractViolation(tid, code, detail)


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-st2c-")
    _TMP_HOME["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP_HOME["dir"].name
    os.environ["HOME"] = _TMP_HOME["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP_HOME["dir"].name)
    finally:
        for k, v in _TMP_HOME["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP_HOME["dir"].cleanup()
    if left:
        raise AssertionError("the ST-2c module wrote into the redirected profile: %r" % (left,))


def sta(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def abcd():
    """A idx0 @0, B idx1 @1000, C idx2 @2000, D idx3 @3000 (terminal)."""
    return [sta("A", 0.0), sta("B", 1000.0), sta("C", 2000.0), sta("D", 3000.0, terminal=True)]


def lists():
    """The station lists the latch must not care about: (label, stations, NEXTLOC of the start station, its StationIndex)."""
    return (
        ("ABCD, start at index 0", abcd(), 0.0, 0),
        ("ABCD, start at index 2", abcd(), 2000.0, 2),
        ("two stations at the same position (B1 / B2)", [sta("A", 0.0), sta("B1", 1000.0), sta("B2", 1000.0), sta("D", 3000.0, terminal=True)], 1000.0, 2),
        ("two stations 40 m apart", [sta("A", 0.0), sta("B1", 1000.0), sta("B2", 1040.0), sta("D", 3000.0, terminal=True)], 1040.0, 2),
        ("the start station is the last of the list", abcd(), 3000.0, 3),
        ("an empty list", [], 1000.0, 0),
    )


def read(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read().decode("utf-8-sig")


# ==============================================================================================================================================
# A - the source: no distance test is left in the first-line block, and none in the whole module
# ==============================================================================================================================================
class A_Static(ContractMixin, unittest.TestCase):
    @staticmethod
    def first_udp_block():
        tree = ast.parse(read("scoring_logic.py"))
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "update_physics_and_scoring"][0]
        blocks = [n for n in ast.walk(fn) if isinstance(n, ast.If) and "is_first_udp" in ast.unparse(n.test) and "bve_next_loc" in ast.unparse(n.test)]
        return fn, blocks

    @st2c("N-11", "RED", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE", "the first-line block of update_physics_and_scoring holds the synchronisation of the previous values and nothing else")
    def test_RED_N11_the_first_line_block_has_no_distance_test_and_no_search(self):
        _fn, blocks = self.first_udp_block()
        self.contract(len(blocks) == 1, "N-11", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE", "expected exactly one first-line block, found %d" % len(blocks))
        block = blocks[0]
        kinds = sorted({type(n).__name__ for stmt in block.body for n in ast.walk(stmt)} & {"Compare", "For", "While", "If", "Call", "ListComp", "GeneratorExp", "IfExp", "BoolOp"})
        targets = []
        for stmt in block.body:
            self.contract(isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Attribute), "N-11", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE",
                          "the block holds %s, not a plain assignment" % type(stmt).__name__)
            targets.append(stmt.targets[0].attr)
        self.contract(kinds == ["Call"] and targets == ["prev_door", "prev_doordir", "prev_next_loc", "is_first_udp"], "N-11", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE",
                      "block assigns %r and contains %r (the two getattr calls of the previous door values are the only calls allowed)" % (targets, kinds))
        calls = sorted({n.func.id for stmt in block.body for n in ast.walk(stmt) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})
        self.contract(calls == ["getattr"], "N-11", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE", "calls in the block: %r" % (calls,))

    @st2c("N-11", "RED", "HUNDRED-METRE-CONSTANT-IN-SCORING", "scoring_logic.py holds no 100.0 at all (the retry lost its 100 m search in ST-2b, the first-line test goes in ST-2c)")
    def test_RED_N11_scoring_logic_has_no_hundred_metre_constant(self):
        tree = ast.parse(read("scoring_logic.py"))
        hundreds = sorted(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 100.0)
        self.contract(hundreds == [], "N-11", "HUNDRED-METRE-CONSTANT-IN-SCORING", "float 100.0 at line(s) %r" % (hundreds,))

    @st2c("G-01", "GUARD", note="the first-line block still synchronises the previous door values and NEXTLOC, and it still waits for a NEXTLOC (is_first_udp is cleared only with one)")
    def test_GUARD_the_first_line_block_is_still_the_synchronisation_and_still_waits_for_a_nextloc(self):
        _fn, blocks = self.first_udp_block()
        self.assertEqual(len(blocks), 1)
        test = ast.unparse(blocks[0].test)
        self.assertIn("is_first_udp", test)
        self.assertIn("self.bve_next_loc != -1.0", test)
        body = [ast.unparse(s) for s in blocks[0].body]
        self.assertIn("self.prev_next_loc = self.bve_next_loc", body)
        self.assertIn("self.is_first_udp = False", body)

    @staticmethod
    def latch_sites():
        tree = ast.parse(read("scoring_logic.py"))
        sites = {}
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Attribute) and t.attr == "is_first_station":
                            sites.setdefault(fn.name, []).append(ast.unparse(node.value))
        return sites

    @st2c("N-11", "RED", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE", "update_physics_and_scoring resets the latch in exactly two places: the departure and the change of NEXTLOC (a third one is the distance test)")
    def test_RED_N11_the_physics_resets_the_latch_in_exactly_two_places(self):
        sites = self.latch_sites().get("update_physics_and_scoring")
        self.contract(sites == ["False", "False"], "N-11", "FIRST-STATION-DISTANCE-TEST-IN-SOURCE", "assignments in update_physics_and_scoring: %r" % (sites,))

    @st2c("G-02", "GUARD", note="the latch is still set only by execute_retry (position 0), the scoring start and the Overlay start, and the physics only ever resets it (never sets it)")
    def test_GUARD_the_places_that_set_the_latch_are_the_known_ones(self):
        sites = self.latch_sites()
        self.assertEqual(sorted(sites), ["execute_retry", "update_physics_and_scoring"])
        self.assertEqual(sites["execute_retry"], ["index == 0"])
        self.assertEqual(set(sites["update_physics_and_scoring"]), {"False"})
        main_src = read("main.py")
        self.assertEqual(main_src.count("self.is_first_station = True"), 2)         # the Overlay start and the scoring start
        self.assertEqual(main_src.count("is_first_station = False"), 0)


# ==============================================================================================================================================
# B - the first UDP line
# ==============================================================================================================================================
class Scene(ContractMixin, BaseScene):
    def first_line(self, stations, next_loc, distance, jumping=True, start_idx=None, speed=0.0):
        """The scoring start has just been confirmed: the latch and the first-line flag are set, the jump to the start station is requested (the train has not been moved yet),
        and the first UDP line carries a NEXTLOC that is `distance` m ahead of the train (negative: behind it)."""
        o = self.o
        o.is_scoring_mode = True
        o.station_list = stations
        o.setting_end_idx = max(len(stations) - 1, 0)
        o.save_data = [CH.cp(next_loc, T0, "S")]
        if start_idx is not None:
            o.setting_start_idx = start_idx
        o.bve_next_loc = o.prev_next_loc = next_loc
        o.bve_location = next_loc - distance
        o.bve_speed = speed
        o.bve_door = o.prev_door = 0
        o.has_departed = False
        o.jump_lock = False
        o.is_official_jumping = jumping
        o.is_first_udp = True
        o.is_first_station = True
        R.bind_identity(o)
        return o


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class B_FirstLine(Scene):
    @st2c("N-11", "RED", "FIRST-STATION-CLEARED-BY-DISTANCE", "a train far from NEXTLOC on the first UDP line (the jump has not moved it yet) keeps the first-station latch")
    def test_RED_N11_the_latch_does_not_depend_on_the_distance_of_the_first_line(self):
        for distance in (99.999, 100.0, 100.001, 150.0, 500.0, 5000.0, -100.001, -500.0, -5000.0):
            with self.subTest(distance=distance):
                self.rig.close()
                self.setUp()
                o = self.first_line(abcd(), 1000.0, distance)
                self.tick()
                self.contract(o.is_first_station is True, "N-11", "FIRST-STATION-CLEARED-BY-DISTANCE", "distance %r: is_first_station is %r after the first line" % (distance, o.is_first_station))
                self.assertFalse(o.is_first_udp)
                self.assertEqual(o.prev_next_loc, 1000.0)

    @st2c("N-11", "RED", "FIRST-STATION-CLEARED-BY-DISTANCE", "the same for every station list and every start index: the latch knows no list, no index, no nearest station, no station 0")
    def test_RED_N11_the_latch_is_the_same_for_every_list_and_every_start_station(self):
        for label, stations, next_loc, start_idx in lists():
            for distance in (0.0, 0.5, 49.0, 99.0, 100.001, 600.0, -600.0):
                with self.subTest(label=label, distance=distance):
                    self.rig.close()
                    self.setUp()
                    o = self.first_line(stations, next_loc, distance, start_idx=start_idx)
                    self.tick()
                    self.contract(o.is_first_station is True, "N-11", "FIRST-STATION-CLEARED-BY-DISTANCE", "%s, distance %r: is_first_station is %r" % (label, distance, o.is_first_station))
                    self.assertFalse(o.is_first_udp)

    @st2c("N-11", "RED", "FIRST-STATION-CLEARED-BY-DISTANCE", "the outcome is the same whether the jump is still pending or not, and whatever the speed that the first line shows")
    def test_RED_N11_the_latch_does_not_depend_on_the_jump_state_or_the_first_speed(self):
        for jumping in (True, False):
            for speed in (0.0, 0.4):
                with self.subTest(jumping=jumping, speed=speed):
                    self.rig.close()
                    self.setUp()
                    o = self.first_line(abcd(), 2000.0, 700.0, jumping=jumping, start_idx=2, speed=speed)
                    self.tick()
                    self.contract(o.is_first_station is True, "N-11", "FIRST-STATION-CLEARED-BY-DISTANCE", "jumping %r speed %r: is_first_station is %r" % (jumping, speed, o.is_first_station))

    @st2c("N-11", "RED", "START-STATION-ARRIVAL-SCORED-AFTER-FAR-FIRST-LINE", "the DANGER of ST-0 T20: after a far first line, the jump brings the train to the start station and it stops there - that is no arrival")
    def test_RED_N11_the_start_station_is_no_arrival_after_a_far_first_line(self):
        for distance in (600.0, -600.0):
            with self.subTest(distance=distance):
                self.rig.close()
                self.setUp()
                o = self.first_line(abcd(), 1000.0, distance)
                o.bve_doordir = 0                                                          # an operational stop (no door cycle needed)
                o.bve_margin_b = o.bve_margin_f = 5.0
                o.bve_time_ms = T0 + 60000
                self.tick()                                                                # the first line: the train is far
                o.is_official_jumping = False                                              # the jump completed: the train stands at the start station
                o.bve_location = 1000.0
                o.bve_speed = 0.0
                self.tick(3)
                saves, popups = self.arrivals(), len(self.stop_popups())
                self.contract((saves, popups) == (0, 0), "N-11", "START-STATION-ARRIVAL-SCORED-AFTER-FAR-FIRST-LINE", "checkpoints added %d, stop popups %d (expected 0 and 0)" % (saves, popups))
                self.assertTrue(o.is_first_station)

    @st2c("G-03", "GUARD", note="a train that stands at the start station on the first line (0 m, 99.9 m) keeps the latch: this was the only case the old test kept, and it still is")
    def test_GUARD_a_train_at_the_start_station_keeps_the_latch(self):
        for distance in (0.0, 0.004, 5.0, 99.9, -99.9):
            with self.subTest(distance=distance):
                self.rig.close()
                self.setUp()
                o = self.first_line(abcd(), 1000.0, distance)
                self.tick()
                self.assertTrue(o.is_first_station)
                self.assertFalse(o.is_first_udp)

    @st2c("G-09", "GUARD", note="after a retry to a LATER checkpoint (latch reset, first line pending) the first line never sets the latch, whatever the distance: only the start sets it")
    def test_GUARD_the_first_line_never_sets_the_latch(self):
        for distance in (0.0, 3.0, 99.9, 100.001, 600.0, -600.0):
            with self.subTest(distance=distance):
                self.rig.close()
                self.setUp()
                o = self.first_line(abcd(), 2000.0, distance, jumping=True, start_idx=0)
                o.is_first_station = False                                                 # what execute_retry leaves for position > 0
                o.is_official_retry = True
                self.tick()
                self.assertFalse(o.is_first_station)
                self.assertFalse(o.is_first_udp)

    @st2c("G-04", "GUARD", note="without a NEXTLOC (-1.0) the first line waits: is_first_udp stays set and so does the latch, however far the train is")
    def test_GUARD_the_first_line_waits_for_a_nextloc(self):
        o = self.first_line(abcd(), 1000.0, 600.0)
        o.bve_next_loc = o.prev_next_loc = -1.0
        self.tick()
        self.assertTrue(o.is_first_udp)
        self.assertTrue(o.is_first_station)


# ==============================================================================================================================================
# C - the latch is still reset by its three ways
# ==============================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class C_Release(Scene):
    def after_far_first_line(self, stations=None, next_loc=1000.0, distance=600.0, start_idx=None):
        o = self.first_line(stations if stations is not None else abcd(), next_loc, distance, start_idx=start_idx)
        self.tick()
        self.contract(o.is_first_station is True, "N-11", "FIRST-STATION-CLEARED-BY-DISTANCE", "the latch is already gone after the first line (distance %r)" % (distance,))
        o.is_official_jumping = False
        o.bve_location = next_loc
        return o

    @st2c("N-11", "RED", "FIRST-STATION-CLEARED-BY-DISTANCE", "the departure resets the latch (speed >= 1, doors closed, no jump) - it is the way the start station ends when the first line was far")
    def test_RED_N11_the_departure_resets_the_latch(self):
        o = self.after_far_first_line()
        self.tick()
        self.assertTrue(o.is_first_station)                                                # standing: still the start station
        o.bve_speed = 5.0
        self.tick()
        self.assertFalse(o.is_first_station)
        self.assertTrue(o.has_departed)

    @st2c("N-11", "RED", "FIRST-STATION-CLEARED-BY-DISTANCE", "a speed while the jump is still unfinished does not reset it (as before): only the departure of a train that was jumped does")
    def test_RED_N11_a_moving_train_during_the_jump_keeps_the_latch(self):
        o = self.first_line(abcd(), 1000.0, 600.0)
        o.bve_speed = 8.0
        self.tick()
        self.contract(o.is_first_station is True, "N-11", "FIRST-STATION-CLEARED-BY-DISTANCE", "the latch is %r after a far first line with a moving train during the jump" % (o.is_first_station,))
        self.tick(3)
        self.assertTrue(o.is_first_station)
        self.assertFalse(o.has_departed)

    @st2c("N-11", "RED", "FIRST-STATION-CLEARED-BY-DISTANCE", "a change of NEXTLOC (the next station comes) resets the latch")
    def test_RED_N11_a_change_of_nextloc_resets_the_latch(self):
        o = self.after_far_first_line()
        self.tick()
        self.assertTrue(o.is_first_station)
        o.bve_next_loc = 2000.0
        self.tick()
        self.assertFalse(o.is_first_station)

    @st2c("G-05", "GUARD", note="the departure and the NEXTLOC change reset the latch when the first line was near, too (the unchanged behaviour)")
    def test_GUARD_the_ways_to_reset_the_latch_with_a_near_first_line(self):
        o = self.first_line(abcd(), 1000.0, 3.0)
        self.tick()
        self.assertTrue(o.is_first_station)
        o.is_official_jumping = False
        o.bve_speed = 5.0
        self.tick()
        self.assertFalse(o.is_first_station)
        self.rig.close()
        self.setUp()
        o = self.first_line(abcd(), 1000.0, 3.0)
        self.tick()
        o.bve_next_loc = 2000.0
        self.tick()
        self.assertFalse(o.is_first_station)


# ==============================================================================================================================================
# D - the places that SET the latch verify the identity first (inherited boundary; nothing of it was touched by ST-2c)
# ==============================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class D_SetByAVerifiedIdentity(BaseRetry):
    @st2c("G-06", "GUARD", note="the retry to position 0 sets the latch whatever the StationIndex of that checkpoint is (0, 2, 4): the first checkpoint is the start, the index is the station")
    def test_GUARD_the_first_checkpoint_sets_the_latch_for_every_start_index(self):
        for start_index in (0, 2, 4):
            with self.subTest(start_index=start_index):
                self.reset()
                o = self.o
                self.hist[0] = C2.ck(self.stations, start_index, T0, role="scoring_start")
                o.is_first_station = False
                result = self.S.execute_retry(o, 0, True)
                self.assertTrue(result.accepted)
                self.assertTrue(o.is_first_station)
                self.assertFalse(o.is_official_retry)
                self.assertEqual(result.selected_station_index, start_index)

    @st2c("G-07", "GUARD", note="a later position is never the start, even when its StationIndex is 0 (the index is the station, the position is the history)")
    def test_GUARD_a_later_checkpoint_of_station_index_0_does_not_set_the_latch(self):
        self.reset()
        o = self.o
        o.save_data = self.hist + [C2.ck(self.stations, 0, T0 + 999999)]
        o.is_first_station = True
        result = self.S.execute_retry(o, 4, True)
        self.assertTrue(result.accepted)
        self.assertEqual(result.selected_station_index, 0)
        self.assertFalse(o.is_first_station)
        self.assertTrue(o.is_official_retry)

    @st2c("G-08", "GUARD", note="a checkpoint that does not verify (another scope, no StationIndex, an index out of the list, an old form) is refused and the latch is not touched; no distance is used instead")
    def test_GUARD_a_refused_retry_does_not_touch_the_latch_and_never_falls_back_to_a_position(self):
        mutations = (
            ("another scenario", lambda o, h: setattr(o, "current_scenario_id", o.current_scenario_id + 1)),
            ("another list id", lambda o, h: setattr(o, "bve_list_id", "other-list")),
            ("another count", lambda o, h: h[0].update(scope=(h[0]["scope"][0], h[0]["scope"][1], h[0]["scope"][2] + 1))),
            ("no StationIndex (old form, the position is right there)", lambda o, h: h[0].pop("station_index")),
            ("no scope (old form)", lambda o, h: h[0].pop("scope")),
            ("an index beyond the list", lambda o, h: h[0].update(station_index=5)),
            ("a negative index", lambda o, h: h[0].update(station_index=-1)),
            ("a bool for the index", lambda o, h: h[0].update(station_index=False)),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                self.reset()
                self.o.is_first_station = False
                self.o.is_first_udp = False
                mutate(self.o, self.hist)
                before = self.fingerprint()
                result = self.S.execute_retry(self.o, 0, True)
                self.assertFalse(result.accepted)
                self.assertEqual(self.sent(), [])
                self.assertEqual(self.fingerprint(), before)
                self.assertFalse(self.o.is_first_station)
                self.assertFalse(self.o.is_first_udp)


# ==============================================================================================================================================
class Z_Meta(unittest.TestCase):
    @staticmethod
    def cases():
        for cls in (A_Static, B_FirstLine, C_Release, D_SetByAVerifiedIdentity):
            for name in sorted(n for n in dir(cls) if n.startswith("test_") and n in cls.__dict__):
                yield cls, name, getattr(cls, name)

    def test_META_every_test_declares_its_id_and_its_kind(self):
        seen = {"RED": 0, "GUARD": 0}
        for cls, name, fn in self.cases():
            meta = getattr(fn, "st2c", None)
            self.assertIsNotNone(meta, "%s.%s has no st2c metadata" % (cls.__name__, name))
            self.assertEqual(name.startswith("test_RED_"), meta["kind"] == "RED", name)
            self.assertEqual(name.startswith("test_GUARD_"), meta["kind"] == "GUARD", name)
            self.assertGreaterEqual(len(meta["note"]), 20, name)
            if meta["kind"] == "RED":
                self.assertTrue(meta["code"].isupper() or "-" in meta["code"], name)
                self.assertEqual(meta["id"], "N-11", name)
            seen[meta["kind"]] += 1
        self.assertGreaterEqual(seen["RED"], 9)
        self.assertGreaterEqual(seen["GUARD"], 9)

    def test_META_the_contract_ids_of_the_audit_are_the_ones_used(self):
        ids = {fn.st2c["id"] for _c, _n, fn in self.cases()}
        self.assertEqual(ids, {"N-11", "G-01", "G-02", "G-03", "G-04", "G-05", "G-06", "G-07", "G-08", "G-09"})


if __name__ == "__main__":
    unittest.main()
