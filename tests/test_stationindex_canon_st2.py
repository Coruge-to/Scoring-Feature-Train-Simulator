"""Phase PID-D4JA StationIndex ST-2a - the CONTRACT tests of the verified station identity (station_identity.py, Overlay._station_identity_sync, the first checkpoint, the
checkpoint of an arrival, the refusal of a scoring start). Python only; nothing here builds, starts a process or opens a socket.

What this file holds
  A  the PURE module station_identity: types, reason codes, snapshots, the decision of the sync, the isolation of the module (no Qt, no socket, no other module of the product)
  B  the SYNC in the real Overlay (offscreen): it runs AFTER the station list is adopted, the observer is never trusted alone, a generation / epoch clears the identity, the
     Legacy-type start (NOT-READY lines before the first STALIST) is "unavailable", never a mismatch                                          (N-03, N-05)
  C  the CHECKPOINTS: an arrival is saved under (scope, StationIndex) from the sender's ARRIDX or not at all; nothing is guessed from a position; the existing checkpoints are
     never touched by a refused one; the door time is the checkpoint's own station's                                                         (N-02, N-04, T04)
  D  the SCORING START: a verified identity of the chosen start station or no start at all (managed and normal mode alike)                   (N-01, T05, T09)
  E  the migrated ST-0 REDs and the book-keeping that keeps one contract id in exactly one place

The N-xx tests are written as REDs first (the contract is what the audit of ST-2 fixed, the codes are its declared codes): each of them fails with ContractViolation
whose .code is the declared one against the product of 69077aa, and passes against the product of ST-2a. The proof for 69077aa is the optional runner:

        python -B tests\\test_stationindex_canon_st2.py --red-check        (a repository copy at 69077aa: every N-xx must be RED-VALID; at ST-2a: every N-xx is UNEXPECTED-PASS)

T09 / T05 (start) / T04 (save) are the three ST-0 REDs that ST-2a turns GREEN: their conditions are executed HERE (same contract id, same declared code) and they are marked
MIGRATED in tests/red_st0_stationindex_contract.py, which keeps the original as the evidence of the RED.

ISOLATION: as the files this one builds on (tests/sia_rig.py: the real Overlay offscreen, every outside effect a recorder, a stub UDP socket: 54321 / 54322 are never bound or
sent to). USERPROFILE / HOME point to an empty temporary folder for the whole module and the module asserts at its end that nothing was written there.
"""
import ast
import math
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

try:
    import station_identity as SI
except ImportError:                                  # the product of 69077aa (the --red-check against the state before ST-2a): the pure tests then error, the N-xx REDs do not need it
    SI = None
import station_index_contract as SIC  # noqa: E402
import sia_rig as R  # noqa: E402
import test_jf1_retry_and_save_data_current as F1  # noqa: E402  (the rig of the save / retry tests: Base.arrive, Base.retry, Base.sent)
import test_char_stop_door_arrival_st0 as CH  # noqa: E402  (its rig only: Base.scene / tick / open_doors drive update_physics_and_scoring through a real stop)

SID, LID = R.SCOPE_SID, R.SCOPE_LIST_ID
T0 = 36000000
CHECKPOINT_FIELDS = ("station_index", "scope", "station_location", "role")
MIGRATED_FROM = "tests/red_st0_stationindex_contract.py"
THIS_FILE = "tests/test_stationindex_canon_st2.py"


class ContractViolation(AssertionError):
    """The product does not meet the contract; `code` names the violated clause (the optional runner compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST2A-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def n_red(tid, code, note=""):
    """Declare an N-xx contract: its id and the ONE failure code it has against the product before ST-2a."""
    def deco(fn):
        fn.st2a = {"id": tid, "code": code, "note": note}
        return fn
    return deco


class ContractMixin(object):
    def contract(self, ok, tid, code, detail=""):
        if not ok:
            raise ContractViolation(tid, code, detail)


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-st2a-")
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
        raise AssertionError("the ST-2a module wrote into the redirected profile: %r" % (left,))


def st(name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def abcd():
    return [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]


def adopted(stations, list_id=LID):
    return SI.StationList(stations, list_id=list_id)


def obs(**kw):
    """The public snapshot of a READY observer on the ABCD list at scenario SID."""
    base = {"ready": True, "scenario_id": SID, "list_id": LID, "count": 4, "tgt_idx": 1, "arr_idx": -1, "arr_seq": 0}
    base.update(kw)
    return base


class ForeignList(list):
    """A list that carries an identity of its own (what the adopted list is), without the module under test: the pre-ST-2a product can run it, too."""

    def __init__(self, items, list_id):
        super().__init__(items)
        self.list_id = list_id


def read(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read().decode("utf-8-sig")


# ==============================================================================================================================================
# A - the pure module
# ==============================================================================================================================================
class A_PureTypes(unittest.TestCase):
    def test_a_scope_is_equal_to_the_plain_tuple_and_immutable(self):
        scope = SI.StationScope(SID, LID, 4)
        self.assertEqual(scope, (SID, LID, 4))
        self.assertEqual((scope.scenario_id, scope.list_id, scope.count), (SID, LID, 4))
        with self.assertRaises(AttributeError):
            scope.count = 5

    def test_make_scope_refuses_every_incomplete_part(self):
        self.assertEqual(SI.make_scope(SID, LID, 4), (SID, LID, 4))
        self.assertEqual(SI.make_scope(0, "00000000", 0), (0, "00000000", 0))                # the empty list has an identity of its own
        for args in ((-1, LID, 4), (None, LID, 4), (SID, "", 4), (SID, None, 4), (SID, LID, -1), (SID, LID, None), (True, LID, 4), (SID, LID, True), ("7", LID, 4), (SID, 1234, 4)):
            with self.subTest(args=args):
                self.assertIsNone(SI.make_scope(*args))

    def test_a_valid_snapshot_takes_its_position_from_the_adopted_entry_and_is_immutable(self):
        scope = SI.make_scope(SID, LID, 4)
        snap = SI.build_snapshot(2, scope, adopted(abcd()), SI.ROLE_ARRIVED_STATION)
        self.assertEqual((snap.valid, snap.reason, snap.station_index, snap.station_location, snap.role, snap.scope), (True, SI.OK, 2, 2000.0, "arrived_station", scope))
        with self.assertRaises(AttributeError):
            snap.valid = False

    def test_every_refusal_has_its_reason_and_never_falls_back(self):
        good = adopted(abcd())
        scope = SI.make_scope(SID, LID, 4)
        nan_list = adopted([st("A", 0.0), st("B", float("nan")), st("C", 2000.0), st("D", 3000.0)])
        missing = adopted([st("A", 0.0), {"name": "B"}, st("C", 2000.0), st("D", 3000.0)])
        text_loc = adopted([st("A", 0.0), st("B", "1000.0"), st("C", 2000.0), st("D", 3000.0)])
        cases = (
            ("scope incomplete", (1, None, good, "arrived_station"), SI.SCOPE_INCOMPLETE),
            ("scope as a short tuple", (1, (SID, LID), good, "arrived_station"), SI.SCOPE_INCOMPLETE),
            ("no list", (1, scope, None, "arrived_station"), SI.NO_STATION_LIST),
            ("an empty list", (1, scope, adopted([]), "arrived_station"), SI.NO_STATION_LIST),
            ("count differs", (1, SI.make_scope(SID, LID, 5), good, "arrived_station"), SI.COUNT_MISMATCH),
            ("another list id", (1, SI.make_scope(SID, "DEADBEEF", 4), good, "arrived_station"), SI.LIST_MISMATCH),
            ("index -1", (-1, scope, good, "arrived_station"), SI.INDEX_NEGATIVE),
            ("index -7", (-7, scope, good, "arrived_station"), SI.INDEX_NEGATIVE),
            ("index not an integer", (1.0, scope, good, "arrived_station"), SI.INDEX_NEGATIVE),
            ("index is a bool", (True, scope, good, "arrived_station"), SI.INDEX_NEGATIVE),
            ("index == count", (4, scope, good, "arrived_station"), SI.INDEX_OUT_OF_RANGE),
            ("index far beyond", (99, scope, good, "arrived_station"), SI.INDEX_OUT_OF_RANGE),
            ("role of nobody", (1, scope, good, "terminal"), SI.ROLE_MISMATCH),
            ("empty role", (1, scope, good, ""), SI.ROLE_MISMATCH),
            ("position NaN", (1, scope, nan_list, "arrived_station"), SI.LOCATION_INVALID),
            ("position missing", (1, scope, missing, "arrived_station"), SI.LOCATION_INVALID),
            ("position a string", (1, scope, text_loc, "arrived_station"), SI.LOCATION_INVALID),
        )
        for label, args, reason in cases:
            with self.subTest(label):
                snap = SI.build_snapshot(*args)
                self.assertEqual((snap.valid, snap.reason), (False, reason))
                self.assertEqual(snap.station_index, args[0])                    # the refused CANDIDATE is reported as it was: it is not replaced by station 0 or a nearest station

    def test_a_plain_list_has_no_identity_of_its_own_and_is_not_refused_for_it_but_an_adopted_list_must_agree(self):
        scope = SI.make_scope(SID, LID, 4)
        self.assertTrue(SI.build_snapshot(1, scope, abcd(), SI.ROLE_ARRIVED_STATION).valid)
        self.assertEqual(SI.build_snapshot(1, scope, adopted(abcd(), list_id="DEADBEEF"), SI.ROLE_ARRIVED_STATION).reason, SI.LIST_MISMATCH)
        self.assertEqual(SI.build_snapshot(1, scope, adopted(abcd(), list_id=""), SI.ROLE_ARRIVED_STATION).reason, SI.LIST_MISMATCH)

    def test_the_adopted_list_is_a_list_for_everything_else(self):
        lst = adopted(abcd())
        self.assertEqual(len(lst), 4)
        self.assertEqual(lst, abcd())
        self.assertEqual([s["name"] for s in lst], ["A", "B", "C", "D"])
        self.assertEqual(lst.list_id, LID)
        self.assertEqual(SI.StationList().list_id, "")

    def test_positions_agree_only_when_both_are_finite_numbers_within_001_m(self):
        for a, b, ok in ((1000.0, 1000.0, True), (1000.0, 1000.009, True), (1000.0, 999.991, True), (1000.0, 1000.011, False), (1000.0, 1001.0, False),
                         (1000.0, None, False), (None, 1000.0, False), (1000.0, float("nan"), False), (1000.0, float("inf"), False), (True, 1.0, False), ("1000", 1000.0, False)):
            with self.subTest(a=a, b=b):
                self.assertEqual(SI.locations_agree(a, b), ok)

    def test_the_arrival_is_the_senders_arrival_index_and_it_must_correspond_to_the_physical_arrival(self):
        lst = adopted(abcd())
        ok = SI.arrival_snapshot(SID, LID, lst, 1, 1000.0)
        self.assertEqual((ok.valid, ok.station_index, ok.role, ok.station_location), (True, 1, "arrived_station", 1000.0))
        self.assertTrue(SI.arrival_snapshot(SID, LID, lst, 1, 1000.009).valid)
        for label, args, reason in (("the arrival judged is another station (A)", (SID, LID, lst, 1, 0.0), SI.LOCATION_MISMATCH),
                                    ("position far off", (SID, LID, lst, 1, 1001.0), SI.LOCATION_MISMATCH),
                                    ("position just off", (SID, LID, lst, 1, 1000.011), SI.LOCATION_MISMATCH),
                                    ("no position", (SID, LID, lst, 1, None), SI.LOCATION_MISMATCH),
                                    ("no arrival yet", (SID, LID, lst, -1, 1000.0), SI.INDEX_NEGATIVE),
                                    ("out of range", (SID, LID, lst, 4, 1000.0), SI.INDEX_OUT_OF_RANGE),
                                    ("no list id", (SID, "", lst, 1, 1000.0), SI.SCOPE_INCOMPLETE),
                                    ("unknown scenario", (-1, LID, lst, 1, 1000.0), SI.SCOPE_INCOMPLETE),
                                    ("another list id", (SID, "DEADBEEF", lst, 1, 1000.0), SI.LIST_MISMATCH)):
            with self.subTest(label):
                snap = SI.arrival_snapshot(*args)
                self.assertEqual((snap.valid, snap.reason), (False, reason))

    def test_the_target_index_is_not_a_condition_of_the_arrival_the_function_does_not_even_take_it(self):
        """Owner decision of the ST-2a review: TGTIDX == ARRIDX is NOT a condition. ARR=B with the target already on the next station C is a normal order of events."""
        import inspect
        self.assertEqual(list(inspect.signature(SI.arrival_snapshot).parameters), ["scenario_id", "list_id", "station_list", "arrival_index", "arrival_location"])
        self.assertFalse(hasattr(SI, "TARGET_MISMATCH"))
        self.assertNotIn("target-mismatch", SI.REASONS)
        lst = adopted(abcd())
        snap = SI.arrival_snapshot(SID, LID, lst, 1, 1000.0)
        self.assertTrue(snap.valid)

    def test_two_stations_at_the_same_position_or_close_by_are_two_identities(self):
        pair = adopted([st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("C", 1000.4), st("D", 3000.0)])
        snaps = [SI.arrival_snapshot(SID, LID, pair, i, pair[i]["location"]) for i in (1, 2, 3)]
        self.assertTrue(all(s.valid for s in snaps))
        self.assertEqual([s.station_index for s in snaps], [1, 2, 3])
        self.assertEqual(len({(tuple(s.scope), s.station_index) for s in snaps}), 3)
        self.assertEqual(snaps[0].station_location, snaps[1].station_location)               # the same position, told apart by the index and by nothing else

    def test_the_start_station_is_the_chosen_index_with_the_role_scoring_start(self):
        lst = adopted(abcd())
        snap = SI.start_snapshot(SID, LID, lst, 2)
        self.assertEqual((snap.valid, snap.station_index, snap.role, snap.station_location, snap.scope), (True, 2, "scoring_start", 2000.0, (SID, LID, 4)))
        for idx, reason in ((9, SI.INDEX_OUT_OF_RANGE), (4, SI.INDEX_OUT_OF_RANGE), (-1, SI.INDEX_NEGATIVE)):
            with self.subTest(idx=idx):
                self.assertEqual(SI.start_snapshot(SID, LID, lst, idx).reason, reason)
        self.assertEqual(SI.start_snapshot(SID, "", lst, 0).reason, SI.SCOPE_INCOMPLETE)
        self.assertEqual(SI.start_snapshot(SID, LID, None, 0).reason, SI.SCOPE_INCOMPLETE)

    def test_checkpoint_fields_come_from_a_valid_snapshot_only(self):
        lst = adopted(abcd())
        fields = SI.checkpoint_fields(SI.start_snapshot(SID, LID, lst, 2))
        self.assertEqual(set(fields), set(CHECKPOINT_FIELDS))
        self.assertEqual(fields, {"station_index": 2, "scope": (SID, LID, 4), "station_location": 2000.0, "role": "scoring_start"})
        self.assertIs(type(fields["scope"]), tuple)
        with self.assertRaises(ValueError):
            SI.checkpoint_fields(SI.start_snapshot(SID, LID, lst, 9))
        with self.assertRaises(ValueError):
            SI.checkpoint_fields(SI.build_snapshot(1, SI.make_scope(SID, LID, 4), lst, SI.ROLE_TARGET_STATION))          # the target role is never stored in a checkpoint

    def test_the_same_station_is_the_same_index_under_the_same_scope(self):
        lst = adopted(abcd())
        snap = SI.arrival_snapshot(SID, LID, lst, 1, 1000.0)
        held = dict(SI.checkpoint_fields(snap))
        self.assertTrue(SI.same_station(held, snap))
        self.assertFalse(SI.same_station(dict(held, station_index=2), snap))
        self.assertFalse(SI.same_station(dict(held, scope=(SID + 1, LID, 4)), snap))
        self.assertFalse(SI.same_station({"loc": 0.0}, snap))                                # an old-form checkpoint holds no station
        self.assertFalse(SI.same_station(None, snap))
        self.assertFalse(SI.same_station(held, SI.arrival_snapshot(SID, LID, lst, -1, 1000.0)))


class B_TheDecision(unittest.TestCase):
    def decide(self, observed, scenario=SID, stations=None, nextloc=1000.0):
        return SI.decide(observed, scenario, adopted(abcd()) if stations is None else stations, nextloc)

    def test_everything_agrees_the_indexes_are_usable_under_the_scope_of_the_adopted_list(self):
        d = self.decide(obs(arr_idx=1, arr_seq=3))
        self.assertEqual((d.usable, d.reason, d.scope, d.arr_seq), (True, SI.OK, (SID, LID, 4), 3))
        self.assertEqual((d.tgt.valid, d.tgt.station_index, d.tgt.role, d.tgt.station_location), (True, 1, "target_station", 1000.0))
        self.assertEqual((d.arr.valid, d.arr.station_index, d.arr.role), (True, 1, "arrived_station"))
        self.assertEqual(SI.published_values(d), (1, 1, 3, LID))

    def test_none_yet_is_not_a_refusal_of_the_whole(self):
        d = self.decide(obs(arr_idx=-1, tgt_idx=-1), nextloc=-1.0)
        self.assertTrue(d.usable)
        self.assertEqual((d.tgt.valid, d.tgt.reason, d.arr.valid, d.arr.reason), (False, SI.INDEX_NEGATIVE, False, SI.INDEX_NEGATIVE))
        self.assertEqual(SI.published_values(d), (-1, -1, 0, LID))

    def test_every_unusable_state_has_its_reason_and_publishes_nothing(self):
        lst = adopted(abcd())
        for label, args, reason in (
                ("no observer", (None, SID, lst, 1000.0), SI.NO_OBSERVER),
                ("not ready", (obs(ready=False), SID, lst, 1000.0), SI.NOT_READY),
                ("ready key missing", ({}, SID, lst, 1000.0), SI.NOT_READY),
                ("another scenario", (obs(scenario_id=SID + 1), SID, lst, 1000.0), SI.SCENARIO_MISMATCH),
                ("scenario unknown here", (obs(), -1, lst, 1000.0), SI.SCENARIO_MISMATCH),
                ("no station list", (obs(), SID, None, 1000.0), SI.NO_STATION_LIST),
                ("an empty station list", (obs(), SID, adopted([]), 1000.0), SI.NO_STATION_LIST),
                ("a list that carries no identity", (obs(), SID, abcd(), 1000.0), SI.NO_STATION_LIST),
                ("a list with an empty identity", (obs(), SID, adopted(abcd(), list_id=""), 1000.0), SI.NO_STATION_LIST),
                ("the line is for another list", (obs(list_id="DEADBEEF"), SID, lst, 1000.0), SI.LIST_MISMATCH),
                ("the line counts another number", (obs(count=3), SID, lst, 1000.0), SI.COUNT_MISMATCH)):
            with self.subTest(label):
                d = SI.decide(*args)
                self.assertEqual((d.usable, d.reason), (False, reason))
                self.assertIsNone(d.scope)
                self.assertFalse(d.tgt.valid)
                self.assertFalse(d.arr.valid)
                self.assertEqual(SI.published_values(d), (-1, -1, -1, ""))

    def test_a_target_that_is_not_where_the_application_holds_the_next_station_invalidates_the_target_only(self):
        """Owner decision of the ST-2a review: the target index is never a condition of the arrival. A target that does not agree with NEXTLOC is invalid ON ITS OWN
        (published as -1, reason location-mismatch for diagnosis); the scope and the arrival index of the same line stay usable."""
        lst = adopted(abcd())
        for label, nextloc in (("the next station the application holds is elsewhere", 1500.0), ("the next station is unknown", None), ("no next station (-1.0)", -1.0)):
            with self.subTest(label):
                d = SI.decide(obs(tgt_idx=2, arr_idx=1, arr_seq=4), SID, lst, nextloc)
                self.assertTrue(d.usable)
                self.assertEqual(d.scope, (SID, LID, 4))
                self.assertEqual((d.tgt.valid, d.tgt.reason), (False, SI.LOCATION_MISMATCH))
                self.assertEqual((d.arr.valid, d.arr.station_index), (True, 1))
                self.assertEqual(SI.published_values(d), (-1, 1, 4, LID))

    def test_a_bad_arrival_index_alone_leaves_the_target_usable_and_the_other_way_round(self):
        """The two indexes are validated independently; only the list / scenario / count / scope are shared (those make both unusable: see the table above)."""
        lst = adopted(abcd())
        for arr in (-1, 9):
            with self.subTest(arr=arr):
                d = SI.decide(obs(tgt_idx=1, arr_idx=arr, arr_seq=3), SID, lst, 1000.0)
                self.assertTrue(d.usable)
                self.assertEqual((d.tgt.valid, d.tgt.station_index, d.arr.valid), (True, 1, False))
                self.assertEqual(d.arr.reason, SI.INDEX_NEGATIVE if arr < 0 else SI.INDEX_OUT_OF_RANGE)
                self.assertEqual(SI.published_values(d), (1, -1, 3, LID))
        d = SI.decide(obs(tgt_idx=9, arr_idx=1), SID, lst, 1000.0)                        # a bad target index: the arrival stays
        self.assertEqual((d.usable, d.tgt.valid, d.arr.valid), (True, False, True))
        broken = adopted([st("A", 0.0), st("B", 1000.0), {"name": "C"}, st("D", 3000.0)])        # a position the entry does not have: only THAT station is unusable
        d = SI.decide(obs(tgt_idx=2, arr_idx=1), SID, broken, 1000.0)
        self.assertEqual((d.usable, d.tgt.valid, d.tgt.reason, d.arr.valid), (True, False, SI.LOCATION_INVALID, True))

    def test_the_arrival_and_the_next_target_may_name_two_different_stations(self):
        d = self.decide(obs(tgt_idx=2, arr_idx=1, arr_seq=2), nextloc=2000.0)
        self.assertEqual((d.usable, d.tgt.valid, d.tgt.station_index, d.arr.valid, d.arr.station_index), (True, True, 2, True, 1))
        self.assertEqual(SI.published_values(d), (2, 1, 2, LID))

    def test_the_observers_own_list_identity_alone_never_makes_the_indexes_usable(self):
        """N-03 in its pure form: the observer says READY for the list it received LAST; the adopted list is the one the application holds."""
        other = adopted([st("A", 0.0), st("B", 1000.0), st("C", 2000.0)], list_id="CAFEBABE")
        d = SI.decide(obs(), SID, other, 1000.0)
        self.assertEqual((d.usable, d.reason), (False, SI.LIST_MISMATCH))

    def test_a_decision_never_raises_for_a_garbage_observer(self):
        for observed in ({"ready": True}, {"ready": True, "scenario_id": SID}, obs(tgt_idx="x"), obs(arr_idx=None), obs(count=None), obs(list_id=None), obs(arr_seq="n"), "text", 5):
            with self.subTest(observed=observed):
                try:
                    d = SI.decide(observed, SID, adopted(abcd()), 1000.0)
                except AttributeError:
                    self.assertFalse(isinstance(observed, dict))                       # (only a non-dict can be refused by an exception: the sync guards that itself)
                    continue
                self.assertIn(d.reason, SI.REASONS)

    def test_the_unavailable_decision_is_fully_invalid(self):
        d = SI.unavailable(SI.NOT_READY)
        self.assertEqual((d.usable, d.reason, d.scope, d.arr_seq), (False, SI.NOT_READY, None, -1))
        for snap in (d.tgt, d.arr):
            self.assertEqual((snap.valid, snap.station_index, snap.reason), (False, -1, SI.NOT_READY))

    def test_the_reason_codes_are_fixed_words_apart_from_the_verdict_words_of_the_wire(self):
        self.assertEqual(len(SI.REASONS), len(set(SI.REASONS)))
        for word in SI.REASONS:
            self.assertRegex(word, r"^[a-z]+(-[a-z]+)*$")
            self.assertNotIn(word, SIC.VERDICTS)                                       # (the wire says what a LINE is; these say what the application may DO)
        for required in ("no-observer", "not-ready", "no-station-list", "scenario-mismatch", "list-mismatch", "count-mismatch", "index-negative", "index-out-of-range",
                         "location-invalid", "location-mismatch", "role-mismatch"):
            self.assertIn(required, SI.REASONS)
        self.assertEqual(set(SI.CHECKPOINT_ROLES), {"scoring_start", "arrived_station"})
        self.assertEqual(set(SI.ROLES), {"scoring_start", "arrived_station", "target_station"})


class C_TheModuleIsPure(unittest.TestCase):
    FORBIDDEN_IMPORTS = {"main", "scoring_logic", "managed_input", "managed_hud", "managed_mode", "station_index_contract", "telemetry_contract", "telemetry_gate", "config", "utils",
                         "PyQt6", "socket", "os", "sys", "time", "threading", "subprocess", "random", "json", "win32api", "win32gui", "keyboard", "zlib"}

    def setUp(self):
        self.text = read("station_identity.py")
        self.tree = ast.parse(self.text)

    def test_it_imports_nothing_but_math_and_typing(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        self.assertEqual(names, {"math", "typing"})
        self.assertEqual(names & self.FORBIDDEN_IMPORTS, set())

    def code_tokens(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        return names

    def test_it_keeps_no_global_mutable_state_and_does_no_input_or_output(self):
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal))
        for node in self.tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                self.assertNotIsInstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp))
        self.assertEqual(self.code_tokens() & {"open", "print", "input", "socket", "time", "monotonic", "write_desktop_log", "QUdpSocket", "readDatagram", "writeDatagram", "environ", "getenv"}, set())

    def test_it_does_not_know_the_bve_the_senders_or_the_other_modules_of_the_product(self):
        for word in ("station_index_contract", "_stidx_observer", "_station_index_", "managed_input"):
            self.assertTrue(word not in self.text, word)                               # (the ST-1A pin scans every production module for the first three)
        self.assertIsNone(re.search(r"\b(Current|Legacy|AtsEx|BveEx|BVE5|BVE6)\b", self.text))
    def test_every_function_takes_its_state_from_its_arguments(self):
        module_functions = {n.name for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        self.assertGreaterEqual(len(module_functions), 10)
        assigned_at_module_level = {t.id for n in self.tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        for fn in [n for n in self.tree.body if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                            self.assertNotIn(t.value.id, assigned_at_module_level, (fn.name, t.value.id))      # no write into a module-level container


# ==============================================================================================================================================
# B - the sync in the real Overlay
# ==============================================================================================================================================
class OverlayBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["st2a"])
        import main
        import scoring_logic
        import sia_managed_rig
        cls.main, cls.S, cls.MR = main, scoring_logic, sia_managed_rig


STALIST_ABC = "STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=0=2500.0=-1=-1=-1=15000=0=1"
STALIST_OTHER = "STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,E=0=1800.0=-1=-1=-1=15000=0=1"


class B_TheSync(OverlayBase):
    """The normal-mode Overlay of the rig (no gate, no DataPlane): the intake is the production read_udp_data."""

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o

    def feed(self, *texts):
        self.o.udp_socket.incoming.extend(t.encode("utf-8") for t in texts)
        self.o.read_udp_data()

    def line(self, stalist=STALIST_ABC, tgt=1, arr=-1, seq=0, sid=SID, with_part=True, **kw):
        kw["STIDX"] = self.MR.stidx(stalist, tgt, arr, seq) if with_part else None
        return self.MR.tele(sid, **kw)

    def test_the_station_list_that_is_adopted_carries_the_identity_of_its_raw_text_and_the_sync_publishes_it(self):
        o = self.o
        self.feed(STALIST_ABC, self.line())
        self.assertIsInstance(o.station_list, SI.StationList)
        self.assertEqual(o.station_list.list_id, SIC.list_id(STALIST_ABC.split(":", 1)[1]))
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq), (o.station_list.list_id, 1, -1, 0))
        self.assertTrue(o._station_identity.usable)
        self.assertEqual(o._station_identity.scope, (SID, o.station_list.list_id, 3))

    def test_the_arrival_candidate_of_the_sender_is_published_as_the_arrival_index(self):
        o = self.o
        self.feed(STALIST_ABC, self.line(tgt=1, arr=1, seq=1))
        self.assertEqual((o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq), (1, 1, 1))

    @n_red("N-03", "BINDING-USES-LATEST-STALIST-NOT-COMMITTED-LIST", "READY for the list received LAST, but the application holds another one: unusable (list-mismatch)")
    def test_RED_N03_a_ready_line_for_a_list_that_is_not_the_adopted_one_is_unusable(self):
        o = self.o
        self.feed(STALIST_ABC, self.line())
        # (the control: with the adopted list the identity is published)
        self.contract_n03(getattr(o, "bve_list_id", None) == SIC.list_id(STALIST_ABC.split(":", 1)[1]), "no identity is published for the adopted list (control)")
        o._station_index_note_stalist(STALIST_OTHER.split(":", 1)[1])                     # the observer received the LAST list ...
        o.apply_telemetry_text(self.line(stalist=STALIST_OTHER, tgt=1))                  # ... and judged a line for it READY ...
        self.assertTrue(o._stidx_observer.ready)
        self.assertEqual(len(o.station_list), 3)                                         # ... while the application still holds the first one (it never adopted the other)
        sync = getattr(o, "_station_identity_sync", None)
        self.contract_n03(sync is not None, "no _station_identity_sync: nothing compares the observer with the adopted list")
        sync()
        self.contract_n03(getattr(o, "bve_list_id", None) == "", "the identity %r was published for a list that is not the adopted one" % (getattr(o, "bve_list_id", None),))
        self.assertEqual((o._station_identity.usable, o._station_identity.reason, o.bve_tgt_idx, o.bve_arr_idx), (False, SI.LIST_MISMATCH, -1, -1))

    def contract_n03(self, ok, detail):
        if not ok:
            raise ContractViolation("N-03", "BINDING-USES-LATEST-STALIST-NOT-COMMITTED-LIST", detail)

    def test_the_count_and_the_scenario_of_a_ready_line_must_agree_with_the_application_too(self):
        o = self.o
        self.feed(STALIST_ABC, self.line())
        self.assertTrue(o._station_identity.usable)
        o.station_list = SI.StationList(o.station_list[:2], list_id=o.station_list.list_id)            # the SAME list id, another number of stations
        o._station_identity_sync()
        self.assertEqual((o._station_identity.usable, o._station_identity.reason, o.bve_list_id), (False, SI.COUNT_MISMATCH, ""))
        self.feed(STALIST_ABC, self.line())
        self.assertTrue(o._station_identity.usable)
        o.current_scenario_id = SID + 5
        o._station_identity_sync()
        self.assertEqual((o._station_identity.usable, o._station_identity.reason, o.bve_list_id), (False, SI.SCENARIO_MISMATCH, ""))

    def test_a_line_without_a_stidx_part_or_a_not_ready_observer_publishes_nothing(self):
        o = self.o
        self.feed(STALIST_ABC, self.line(with_part=False))
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq), ("", -1, -1, -1))
        self.assertEqual((o._station_identity.usable, o._station_identity.reason), (False, SI.NOT_READY))

    def test_a_sender_that_never_wrote_a_stidx_leaves_no_observer_and_the_reason_no_observer(self):
        o = self.o
        o._station_identity_sync()
        self.assertEqual((o._station_identity.usable, o._station_identity.reason, o.bve_list_id), (False, SI.NO_OBSERVER, ""))

    def test_a_new_station_list_that_the_observer_has_not_judged_yet_makes_the_identity_unusable_at_once(self):
        o = self.o
        self.feed(STALIST_ABC, self.line())
        self.assertTrue(o._station_identity.usable)
        self.feed(STALIST_OTHER)                                                         # the next STALIST is adopted at its arrival (normal mode) - the line that matches comes later
        self.assertEqual(o.station_list.list_id, SIC.list_id(STALIST_OTHER.split(":", 1)[1]))
        self.assertEqual((o._station_identity.usable, o._station_identity.reason, o.bve_list_id), (False, SI.LIST_MISMATCH, ""))
        self.feed(self.line(stalist=STALIST_OTHER, tgt=1))
        self.assertEqual((o._station_identity.usable, o.bve_list_id, o.bve_tgt_idx), (True, o.station_list.list_id, 1))

    def test_the_epoch_reset_and_the_generation_clear_the_published_identity(self):
        o = self.o
        self.feed(STALIST_ABC, self.line(tgt=1, arr=1, seq=1))
        self.assertEqual((o.bve_tgt_idx, o.bve_arr_idx), (1, 1))
        o.reset_telemetry_state()
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq), ("", -1, -1, -1))
        self.assertIsNone(o.__dict__.get("_station_identity"))
        self.feed(STALIST_ABC, self.line(tgt=1, arr=1, seq=1))
        self.assertEqual(o.bve_arr_idx, 1)
        o.reset_generation_state()
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq), ("", -1, -1, -1))
        self.assertEqual(o.station_list, [])

    def test_the_sync_never_raises_into_the_telemetry_step(self):
        o = self.o
        o.__dict__["_stidx_observer"] = object()                                        # an observer without snapshot(): the failure is a refusal, not an exception
        o._station_identity_sync()
        self.assertEqual((o._station_identity.usable, o._station_identity.reason, o.bve_list_id), (False, SI.INTERNAL_ERROR, ""))

    @n_red("N-05", "LEGACY-PRE-READY-IS-UNAVAILABLE-NOT-MISMATCH",
           "the first lines of a Legacy sender carry a STIDX before the first STALIST was seen: the identity is unavailable (not-ready), never a mismatch, and becomes usable by itself")
    def test_RED_N05_the_legacy_type_start_is_unavailable_until_ready_and_then_usable_without_any_anomaly(self):
        o = self.o
        for label, lead in (("Legacy type: 11 lines before the first STALIST", 11), ("Current type: READY from the first line", 0)):
            with self.subTest(label):
                self.rig.close()
                self.setUp()
                o = self.o
                reasons = []
                for _ in range(lead):
                    self.feed(self.line())                                              # a STIDX for a list that was not received yet
                    ident = getattr(o, "_station_identity", None)
                    reasons.append(None if ident is None else ident.reason)
                    self.contract_n05(getattr(o, "bve_list_id", None) == "", "an identity was published before any station list was adopted")
                self.contract_n05(all(r == SI.NOT_READY for r in reasons) if lead else True, "the reasons before READY were %r, not-ready expected" % (sorted(set(reasons), key=str),))
                self.feed(STALIST_ABC, self.line())
                self.contract_n05(getattr(o, "bve_list_id", None) == SIC.list_id(STALIST_ABC.split(":", 1)[1]) and getattr(o, "bve_tgt_idx", None) == 1, "the identity is not usable once the observer is READY")
                observer = o._stidx_observer
                self.assertTrue(observer.ready)
                self.assertEqual(observer.list_changes_in_scenario, 0)                  # no 'list change inside one scenario' anomaly
                self.assertEqual(observer.list_generation, 1)                          # one scope, seen once
                self.assertTrue(o._station_identity.usable)
                self.assertEqual(o._station_identity.reason, SI.OK)

    def contract_n05(self, ok, detail):
        if not ok:
            raise ContractViolation("N-05", "LEGACY-PRE-READY-IS-UNAVAILABLE-NOT-MISMATCH", detail)

    def test_the_identity_events_are_written_on_a_change_only(self):
        o = self.o
        seen = []
        o.input_event_sink = lambda event, **fields: seen.append((event, fields))
        self.feed(STALIST_ABC, self.line())
        for _ in range(50):
            self.feed(self.line())
        ids = [f for e, f in seen if e == "stidx-identity"]
        self.assertEqual([f["why"] for f in ids], [SI.NOT_READY, SI.OK])                # the list is adopted before the line that matches it: two states, each written once
        self.assertEqual((ids[1]["usable"], ids[1]["list"], ids[1]["cnt"]), (1, o.station_list.list_id, 3))
        self.feed(STALIST_OTHER)
        self.assertEqual([f["why"] for e, f in seen if e == "stidx-identity"], [SI.NOT_READY, SI.OK, SI.LIST_MISMATCH])


class B2_TheSyncInTheManagedMode(OverlayBase):
    def setUp(self):
        self.r = self.MR.ManagedRig(self.main)
        self.addCleanup(self.r.close)
        self.o = self.r.o

    def test_the_sync_runs_after_the_station_list_of_the_line_is_adopted_never_before(self):
        o, r = self.o, self.r
        calls, seen_by_the_observer = [], []
        original_sync, original_observe = o._station_identity_sync, o._station_index_observe

        def observe(text):
            seen_by_the_observer.append((len(o.station_list), o.bve_list_id))             # the line is observed BEFORE the list of that line is adopted: no identity yet
            return original_observe(text)

        def sync():
            calls.append((getattr(o.station_list, "list_id", None), o._stidx_observer.ready))
            return original_sync()

        o._station_index_observe, o._station_identity_sync = observe, sync
        r.go_active()
        expected = SIC.list_id(self.MR.STALIST.split(":", 1)[1])
        self.assertEqual(seen_by_the_observer[0], (0, ""))
        self.assertTrue(calls)
        self.assertEqual(calls[0], (expected, True))                                    # at the first sync the list of the line IS adopted and the observer READY for it
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx), (expected, 1))

    def test_the_stidx_that_is_seen_first_does_not_enable_anything_before_the_list_is_adopted(self):
        o, r = self.o, self.r
        r.go_active(with_stations=False)                                                  # a line with a STIDX but no STALIST at all
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx, o.bve_arr_idx), ("", -1, -1))
        self.assertFalse(o._stidx_observer.ready)
        r.send(self.MR.STALIST, self.MR.tele(1))
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx), (SIC.list_id(self.MR.STALIST.split(":", 1)[1]), 1))

    def test_a_new_generation_clears_the_identity_and_the_next_line_publishes_it_again(self):
        o, r = self.o, self.r
        r.go_active()
        self.assertTrue(o._station_identity.usable)
        r.publish(True, True, generation=2)
        r.tick(3)
        self.assertEqual((o.bve_list_id, o.bve_tgt_idx), ("", -1))
        self.assertEqual(o.station_list, [])
        r.send(self.MR.STALIST, self.MR.tele(2))
        r.tick(2)
        self.assertEqual((o.bve_tgt_idx, o.bve_list_id), (1, SIC.list_id(self.MR.STALIST.split(":", 1)[1])))

    def test_one_identity_event_per_change_reaches_the_managed_log(self):
        o, r = self.o, self.r
        r.go_active()
        for _ in range(30):
            r.send(self.MR.tele(1))
        events = r.events("stidx-identity")
        self.assertEqual(len(events), 1, events)
        self.assertIn("usable=1", events[0])
        self.assertIn("why=ok", events[0])
        self.assertLessEqual(len(events[0]), 160)                                       # the Caller copies 160 characters of a line


# ==============================================================================================================================================
# C - the checkpoint of an arrival
# ==============================================================================================================================================
class C_TheCheckpoints(ContractMixin, F1.Base):
    def arrive_unbound(self, next_loc, loc, saves, t=T0 + 60000, name="B", is_pass=1, arrival_loc=None):
        """One create_save_data call at an arrival WITHOUT the helper of the JF-1 rig that binds an identity by itself: what the Overlay publishes is what the test set.
        arrival_loc = the position the arrival was judged against (evaluate_arrival passes it); None = the call of the caller that names none."""
        o = self.o
        o.is_scoring_mode, o.is_scoring_finished = True, False
        o.save_data = saves
        o.bve_next_loc = o.prev_next_loc = next_loc
        o.bve_location = loc
        o.bve_time_ms = t
        o.bve_current_station_name = name
        o.bve_is_pass, o.bve_doordir, o.score = is_pass, 1, 0
        if arrival_loc is None:
            self.S.create_save_data(o)
        else:
            self.S.create_save_data(o, arrival_loc)
        return o.save_data

    @n_red("N-02", "SAVE-WHILE-IDENTITY-UNAVAILABLE", "no verified identity: no checkpoint is created, the scoring goes on, the existing checkpoints are left alone")
    def test_RED_N02_while_the_identity_is_unavailable_no_checkpoint_is_created_and_nothing_else_changes(self):
        o = self.o
        o.station_list = abcd()
        first = {"loc": 0.0, "time_ms": T0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0}
        for label, prepare in (("no list identity at all", lambda: setattr(o, "bve_list_id", "")),
                               ("no arrival index", lambda: R.bind_identity(o, arr_idx=-1, tgt_idx=1)),
                               ("an arrival index beyond the list", lambda: R.bind_identity(o, arr_idx=9, tgt_idx=-1)),
                               ("a negative arrival index", lambda: R.bind_identity(o, arr_idx=-4, tgt_idx=-1)),
                               ("an unknown scenario", lambda: (R.bind_identity(o, arr_idx=1, tgt_idx=1), setattr(o, "current_scenario_id", -1))),
                               ("the adopted list carries another identity", lambda: (R.bind_identity(o, arr_idx=1, tgt_idx=1), setattr(o, "station_list", ForeignList(abcd(), "DEADBEEF")))),
                               ("the position is not that of the named station", lambda: R.bind_identity(o, arr_idx=2, tgt_idx=-1))):
            with self.subTest(label):
                o.station_list = abcd()
                o.bve_list_id, o.bve_arr_idx, o.bve_tgt_idx, o.current_scenario_id = "", -1, -1, -1
                prepare()
                held = [dict(first)]
                saves = self.arrive_unbound(1000.0, 999.0, held)
                self.contract(len(saves) == 1 and saves[0] == first and saves is held, "N-02", "SAVE-WHILE-IDENTITY-UNAVAILABLE",
                              "%s: %d checkpoint(s) %r" % (label, len(saves), [c.get("station_name") for c in saves]))
                self.assertTrue(o.is_scoring_mode)                                      # the scoring itself goes on

    def test_a_refusal_is_logged_once_for_the_same_reason_and_the_same_candidate(self):
        o = self.o
        seen = []
        o.input_event_sink = lambda event, **fields: seen.append((event, fields))
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=-1, tgt_idx=1)
        for _ in range(5):
            self.arrive_unbound(1000.0, 999.0, [F1.cp(0.0, T0, name="A")])
        skips = [f for e, f in seen if e == "stidx-save-skip"]
        self.assertEqual(len(skips), 1)
        self.assertEqual((skips[0]["why"], skips[0]["idx"], skips[0]["role"], skips[0]["scn"], skips[0]["list"], skips[0]["cnt"]), (SI.INDEX_NEGATIVE, -1, "arrived_station", SID, LID, 4))
        R.bind_identity(o, arr_idx=9, tgt_idx=-1)
        self.arrive_unbound(1000.0, 999.0, [F1.cp(0.0, T0, name="A")])
        self.assertEqual([f["why"] for e, f in seen if e == "stidx-save-skip"], [SI.INDEX_NEGATIVE, SI.INDEX_OUT_OF_RANGE])
        R.bind_identity(o, arr_idx=1, tgt_idx=1)
        self.arrive_unbound(1000.0, 999.0, [F1.cp(0.0, T0, name="A")])               # a checkpoint is created: the next refusal of the same kind is news again
        R.bind_identity(o, arr_idx=9, tgt_idx=-1)
        self.arrive_unbound(1000.0, 999.0, [F1.cp(0.0, T0, name="A")])
        self.assertEqual(len([1 for e, f in seen if e == "stidx-save-skip"]), 3)

    def test_a_refused_checkpoint_never_overwrites_or_removes_a_valid_one(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=1, tgt_idx=1)
        saves = self.arrive(1000.0, 999.0, name="B", is_pass=1)
        good = [dict(c) for c in saves]
        o.bve_arr_idx = 99
        saves = self.arrive(2000.0, 1999.0, name="C", is_pass=1, saves=o.save_data)
        self.assertEqual([dict(c) for c in saves], good)
        o.bve_arr_idx = 2
        o.bve_tgt_idx = 2
        saves = self.arrive(2000.0, 1999.0, name="C", is_pass=1, saves=o.save_data)
        self.assertEqual([c["station_index"] for c in saves[1:]], [1, 2])

    def test_the_checkpoint_holds_the_scope_the_index_the_position_and_the_role(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=1, tgt_idx=1)
        saves = self.arrive(1000.0, 996.5, name="B", is_pass=1, score=300)
        new = saves[-1]
        self.assertEqual({k: new[k] for k in CHECKPOINT_FIELDS}, {"station_index": 1, "scope": (SID, LID, 4), "station_location": 1000.0, "role": "arrived_station"})
        self.assertEqual((new["loc"], new["target_loc"], new["stop_error"], new["score"]), (996.5, 1000.0, 3.5, 300))

    # -- the review of ST-2a: the TARGET index is not a condition of the checkpoint of an arrival; the ARRIVAL index must name the station the arrival was judged for --------
    def test_the_target_on_the_next_station_does_not_stop_the_checkpoint_of_the_arrival(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=1, tgt_idx=2)                                       # ARR = B, TGT = C: a normal order of events
        saves = self.arrive_unbound(1000.0, 999.0, [F1.cp(0.0, T0, name="A")], arrival_loc=1000.0)
        self.assertEqual([c["station_name"] for c in saves], ["A", "B"])
        self.assertEqual({k: saves[-1][k] for k in CHECKPOINT_FIELDS}, {"station_index": 1, "scope": (SID, LID, 4), "station_location": 1000.0, "role": "arrived_station"})

    def test_an_unavailable_target_does_not_stop_the_checkpoint_either(self):
        o = self.o
        o.station_list = abcd()
        for tgt in (-1, 1, 3):
            with self.subTest(tgt=tgt):
                R.bind_identity(o, arr_idx=1, tgt_idx=tgt)
                saves = self.arrive_unbound(1000.0, 999.0, [F1.cp(0.0, T0, name="A")], arrival_loc=1000.0)
                self.assertEqual([c.get("station_index") for c in saves], [None, 1])

    def test_the_arrival_index_must_name_the_station_the_arrival_was_judged_for_and_a_refusal_leaves_the_history_alone(self):
        o = self.o
        o.station_list = abcd()
        seen = []
        o.input_event_sink = lambda event, **fields: seen.append((event, fields))
        first = F1.with_identity(F1.cp(0.0, T0, name="A"), 0, 0.0, role="scoring_start")
        for label, arr, judged, why in (("the arrival was judged for A, ARR names B", 1, 0.0, SI.LOCATION_MISMATCH),
                                        ("the arrival was judged 0.5 m away from the named station", 1, 1000.5, SI.LOCATION_MISMATCH),
                                        ("the arrival was judged for C, ARR names B", 1, 2000.0, SI.LOCATION_MISMATCH),
                                        ("ARR is beyond the list", 9, 1000.0, SI.INDEX_OUT_OF_RANGE),
                                        ("ARR is none", -1, 1000.0, SI.INDEX_NEGATIVE)):
            with self.subTest(label):
                del seen[:]
                self.rig.close()
                self.setUp()
                o = self.o
                o.station_list = abcd()
                o.input_event_sink = lambda event, **fields: seen.append((event, fields))
                R.bind_identity(o, arr_idx=arr, tgt_idx=2)
                held = [dict(first), F1.with_identity(F1.cp(1000.0, T0 + 1, name="B"), 1, 1000.0)]
                before = [dict(c) for c in held]
                saves = self.arrive_unbound(1000.0, 999.0, held, arrival_loc=judged)
                self.assertIs(saves, held)
                self.assertEqual([dict(c) for c in saves], before)
                skips = [f for e, f in seen if e == "stidx-save-skip"]
                self.assertEqual(len(skips), 1)
                self.assertEqual((skips[0]["why"], skips[0]["idx"], skips[0]["tgt"]), (why, arr, 2))             # the target is recorded for diagnosis only
                self.assertTrue(o.is_scoring_mode)                                                                 # the scoring goes on

    def test_the_arrival_is_compared_with_the_position_the_arrival_was_judged_for_not_with_the_next_station_of_the_moment(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=1, tgt_idx=2)
        # NEXTLOC (C) has moved on, the stop was scored against B: the checkpoint is B's
        saves = self.arrive_unbound(2000.0, 999.0, [F1.cp(0.0, T0, name="A")], arrival_loc=1000.0)
        self.assertEqual([c.get("station_index") for c in saves], [None, 1])
        # a caller that names no position is compared with NEXTLOC (C): B is refused
        saves = self.arrive_unbound(2000.0, 999.0, [F1.cp(0.0, T0, name="A")])
        self.assertEqual([c.get("station_index") for c in saves], [None])

    def test_evaluate_arrival_hands_the_position_it_scored_the_stop_against_to_the_checkpoint(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=1, tgt_idx=2)
        o.is_scoring_mode, o.is_scoring_finished, o.setting_end_idx = True, False, 3
        o.save_data = [F1.cp(0.0, T0, name="A")]
        o.bve_next_loc, o.prev_next_loc, o.bve_location = 2000.0, 1000.0, 999.0         # (NEXTLOC has just moved to C; the stop was against B)
        o.bve_is_pass, o.bve_doordir, o.bve_time_ms = 1, 0, T0 + 60000
        self.S.evaluate_arrival(o, 50.0)
        self.assertEqual([c.get("station_index") for c in o.save_data], [None, 1])
        self.S.evaluate_arrival(o, 51.0, 1000.0)                                          # the door path names the position itself: still one checkpoint for B
        self.assertEqual([c.get("station_index") for c in o.save_data], [None, 1])

    def test_stations_at_the_same_position_and_close_by_are_told_apart_by_the_index_only(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("C", 1000.4), st("D", 3000.0, terminal=True)]
        for idx, name in ((1, "B1"), (2, "B2"), (3, "C")):
            R.bind_identity(o, arr_idx=idx, tgt_idx=idx)
            saves = self.arrive(o.station_list[idx]["location"], 999.0, name=name, is_pass=1, saves=o.save_data if idx > 1 else None)
        self.assertEqual([c["station_name"] for c in saves], ["A", "B1", "B2", "C"])
        self.assertEqual([c["station_index"] for c in saves[1:]], [1, 2, 3])

    def test_the_same_station_twice_is_one_checkpoint_and_a_float_difference_does_not_matter(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o, arr_idx=1, tgt_idx=1)
        self.arrive(1000.0, 999.0, is_pass=1)
        saves = self.arrive(1000.004, 999.0, is_pass=1, saves=o.save_data)
        self.assertEqual(len(saves), 2)
        o.bve_arr_idx = o.bve_tgt_idx = 2
        saves = self.arrive(2000.0, 1999.0, is_pass=1, saves=o.save_data)
        self.assertEqual(len(saves), 3)

    @n_red("N-04", "SAVE-DOORTIME-STATION-FROM-POSITION",
           "the door time is added for the station the CHECKPOINT names (same StationIndex), not for the first station found at a position")
    def test_RED_N04_the_door_time_station_is_the_station_of_the_checkpoint(self):
        o = self.o
        o.bve_door_close_time_ms = 4630
        # the pair at one position: B1 adds the door time, B2 (def_time later than now) does not
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0, def_time=99999999), st("D", 3000.0, terminal=True)]
        R.bind_identity(o, arr_idx=1, tgt_idx=1)
        saves = self.arrive(1000.0, 999.0, name="B1", is_pass=0)
        self.contract(saves[-1].get("time_ms") == T0 + 60000 + 4630, "N-04", "SAVE-DOORTIME-STATION-FROM-POSITION", "B1 (adds): time %r" % (saves[-1].get("time_ms"),))
        o.bve_arr_idx = o.bve_tgt_idx = 2
        saves = self.arrive(1000.0, 999.0, name="B2", is_pass=0, saves=o.save_data)
        self.contract(len(saves) == 3 and saves[-1].get("time_ms") == T0 + 60000, "N-04", "SAVE-DOORTIME-STATION-FROM-POSITION",
                      "B2 (def_time later: no door time) %r: %d checkpoint(s), time %r" % ([c.get("station_name") for c in saves], len(saves), saves[-1].get("time_ms")))
        # a frame in which prev_next_loc is still the previous target: the door time belongs to the arrival's own station
        self.log.clear()
        o.station_list = [st("A", 0.0), st("B", 1000.0), st("C", 2000.0, def_time=99999999), st("D", 3000.0, terminal=True)]
        R.bind_identity(o, arr_idx=2, tgt_idx=2)
        saves = self.arrive(2000.0, 1999.0, prev_next_loc=1000.0, name="C", is_pass=0)
        self.contract(saves[-1].get("time_ms") == T0 + 60000 and self.door_logs() == [], "N-04", "SAVE-DOORTIME-STATION-FROM-POSITION",
                      "C is the arrival (no door time) but %r were logged" % (self.door_logs(),))

    def test_the_door_time_of_a_station_that_does_add_names_that_station(self):
        o = self.o
        o.bve_door_close_time_ms = 4630
        o.station_list = [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        R.bind_identity(o, arr_idx=2, tgt_idx=2)
        saves = self.arrive(2000.0, 1999.0, prev_next_loc=1000.0, name="C", is_pass=0)
        self.assertEqual(saves[-1]["time_ms"], T0 + 60000 + 4630)
        self.assertEqual(self.door_logs(), ["[SAVE] 開扉時間を反映: Cにて 4630ms をセーブデータ時刻に加算"])

    def test_the_end_station_arrival_still_creates_no_checkpoint(self):
        o = self.o
        o.station_list = abcd()
        o.is_scoring_mode, o.is_first_station, o.setting_end_idx = True, True, 1
        o.save_data = [F1.cp(0.0, T0)]
        o.prev_next_loc = o.bve_next_loc = 1000.0
        o.bve_location = 1000.0
        R.bind_identity(o)                                  # Phase SI-R5.2-B: bound AFTER the position is set - the sender names B as the target (the end station is not found by a 1 m search)
        self.S.evaluate_arrival(o, 50.0)
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(len(o.save_data), 1)

    def test_nothing_is_created_when_not_scoring_or_when_finished(self):
        o = self.o
        o.station_list = abcd()
        R.bind_identity(o)
        o.bve_next_loc = 1000.0
        o.save_data = [F1.cp(0.0, T0)]
        o.is_scoring_mode = False
        self.S.create_save_data(o)
        o.is_scoring_mode, o.is_scoring_finished = True, True
        self.S.create_save_data(o)
        self.assertEqual(len(o.save_data), 1)


# ==============================================================================================================================================
# D - the scoring start
# ==============================================================================================================================================
class D_TheScoringStart(ContractMixin, F1.Base):
    def start_through_the_menu(self, start_idx):
        o = self.o
        o.setting_start_idx = start_idx
        o.menu_state = 10
        o.menu_cursor = 1
        o.handle_menu_enter(True)

    def fingerprint(self):
        o = self.o
        return (o.is_scoring_mode, o.is_official_jumping, list(o.save_data), self.sent(), o.expected_target_loc, o.expected_target_time, o.total_retry_count, o.is_first_station)

    @n_red("N-01", "START-WHILE-IDENTITY-UNAVAILABLE", "no verified identity: no scoring start - no scoring mode, no official jump, no checkpoint, no command")
    def test_RED_N01_while_the_identity_is_unavailable_the_scoring_start_is_refused(self):
        o = self.o
        o.station_list = abcd()
        o.current_scenario_id = SID
        for label, prepare in (("no list identity (the sync said not-ready)", lambda: setattr(o, "bve_list_id", "")),
                               ("an unknown scenario", lambda: (setattr(o, "bve_list_id", LID), setattr(o, "current_scenario_id", -1))),
                               ("no station list at all", lambda: (setattr(o, "bve_list_id", LID), setattr(o, "station_list", [])))):
            with self.subTest(label):
                self.rig.close()
                self.setUp()
                o = self.o
                o.station_list = abcd()
                o.current_scenario_id = SID
                prepare()
                self.start_through_the_menu(1)
                refused = (not o.is_scoring_mode) and (not o.is_official_jumping) and o.save_data == [] and self.sent() == []
                self.contract(refused, "N-01", "START-WHILE-IDENTITY-UNAVAILABLE",
                              "%s: scoring=%r official_jump=%r checkpoints=%d commands=%r" % (label, o.is_scoring_mode, o.is_official_jumping, len(o.save_data), self.sent()))

    def test_the_control_with_a_verified_identity_the_start_goes_ahead_and_the_first_checkpoint_names_the_start_station(self):
        o = self.o
        R.bind_identity(o)
        self.start_through_the_menu(2)
        self.assertEqual(self.sent(), [self.v2("STA", 2, T0)])
        self.assertTrue(o.is_scoring_mode and o.is_official_jumping)
        self.assertEqual(o.expected_target_loc, 2000.0)
        first = o.save_data[0]
        self.assertEqual({k: first[k] for k in CHECKPOINT_FIELDS}, {"station_index": 2, "scope": (SID, LID, 4), "station_location": 2000.0, "role": "scoring_start"})
        self.assertEqual((first["loc"], first["station_name"], first["time_ms"]), (2000.0, "C", T0))

    def test_a_refused_start_changes_nothing_and_is_not_a_fall_back_to_station_0_position_0_or_the_nearest_station(self):
        o = self.o
        R.bind_identity(o)
        o.save_data = []
        for bad in (9, 4, -1, -100):
            with self.subTest(bad=bad):
                before = self.fingerprint()
                self.start_through_the_menu(bad)
                self.assertEqual(self.fingerprint(), before)
                self.assertEqual(self.sent(), [])
                self.assertFalse(o.is_official_jumping)
                self.assertEqual((o.expected_target_loc, o.expected_target_time), (-1.0, -1))

    def test_a_refused_start_closes_the_menu_shows_one_warning_and_says_why(self):
        o = self.o
        seen = []
        o.input_event_sink = lambda event, **fields: seen.append((event, fields))
        o.station_list = abcd()
        o.current_scenario_id = SID
        self.start_through_the_menu(1)                                                  # no list identity published
        self.assertEqual([ev[0] for ev in self.events if ev[0] == "toggle"], ["toggle"])
        self.assertEqual(len([p for p in o.popups if p.get("category") == "警告"]), 1)
        refusals = [f for e, f in seen if e == "scoring-start-refused"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual((refusals[0]["why"], refusals[0]["src"]), (SI.SCOPE_INCOMPLETE, "identity"))

    def test_the_reason_of_a_refused_start_is_the_syncs_own_when_it_has_one(self):
        o = self.o
        seen = []
        o.input_event_sink = lambda event, **fields: seen.append((event, fields))
        o.station_list = abcd()
        o.current_scenario_id = SID
        o._station_identity = SI.unavailable(SI.NOT_READY)
        self.start_through_the_menu(1)
        self.assertEqual([f["why"] for e, f in seen if e == "scoring-start-refused"], [SI.NOT_READY])


class D2_TheScoringStartInTheManagedMode(OverlayBase):
    def setUp(self):
        self.r = self.MR.ManagedRig(self.main)
        self.addCleanup(self.r.close)
        self.o = self.r.o

    @n_red("N-01", "START-WHILE-IDENTITY-UNAVAILABLE", "managed mode: a sender without a usable STIDX: the start is refused (the same contract as the normal mode)")
    def test_RED_N01_managed_mode_a_start_without_a_usable_identity_is_refused(self):
        o, r = self.o, self.r
        r.go_active(STIDX=None)                                                         # the sender writes no STIDX: the managed gate (inputs present) lets the start through
        self.assertTrue(len(o.station_list) == 3)
        r.start_scoring_via_menu()
        refused = (not o.is_scoring_mode) and (not o.is_official_jumping) and o.save_data == [] and o.udp_socket.written == []
        if refused:
            self.assertTrue(any("src=identity" in e and "why=not-ready" in e for e in r.events("scoring-start-refused")), r.events("scoring-start-refused"))
        if not refused:
            raise ContractViolation("N-01", "START-WHILE-IDENTITY-UNAVAILABLE", "managed: scoring=%r official_jump=%r checkpoints=%d" % (o.is_scoring_mode, o.is_official_jumping, len(o.save_data)))

    def test_managed_mode_the_control_with_a_usable_identity_starts(self):
        o, r = self.o, self.r
        r.go_active()
        r.start_scoring_via_menu()
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(o.save_data[0]["station_index"], 0)
        self.assertEqual(o.save_data[0]["scope"], (1, SIC.list_id(self.MR.STALIST.split(":", 1)[1]), 3))
        self.assertEqual(r.events("scoring-start-refused"), [])


# ==============================================================================================================================================
# E - the three ST-0 REDs that ST-2a turns GREEN (executed here: same contract id, same declared code) and the book-keeping
# ==============================================================================================================================================
def bind_scope(o, stations, sid=SID, list_id=LID):
    o.current_scenario_id = sid
    o.bve_list_id = list_id
    o.station_list = stations


class E_Migrated(ContractMixin, F1.Base):
    def start_through_the_menu(self, start_idx):
        o = self.o
        o.setting_start_idx = start_idx
        o.menu_state = 10
        o.menu_cursor = 1
        o.handle_menu_enter(True)

    def test_RED_T09_the_scoring_start_stores_the_chosen_start_index_in_the_first_checkpoint(self):
        o = self.o
        bind_scope(o, o.station_list)
        self.start_through_the_menu(2)
        self.assertEqual(self.sent(), [self.v2("STA", 2, T0)])                                 # the fixture reached the start of the scoring
        first = o.save_data[0]
        self.assertEqual((first["loc"], first["station_name"]), (2000.0, "C"))
        missing = [k for k in CHECKPOINT_FIELDS if k not in first]
        ok = (not missing) and first["station_index"] == 2 and first["role"] == "scoring_start" and first["station_location"] == 2000.0
        self.contract(ok, "T09", "INITIAL-CHECKPOINT-HAS-NO-STATION-INDEX", "missing fields %r" % (missing,))
        self.assertEqual(first["scope"], (SID, LID, 4))

    def test_RED_T05_a_scoring_start_with_an_out_of_range_start_index_is_refused(self):
        bind_scope(self.o, self.o.station_list)
        self.start_through_the_menu(1)                                                              # the control: a valid start index starts the scoring and sends its jump
        self.assertEqual(self.sent(), [self.v2("STA", 1, T0)])
        for bad in (9, -1):
            with self.subTest(bad=bad):
                self.rig.close()
                self.setUp()
                o = self.o
                bind_scope(o, o.station_list)
                o.save_data = []
                self.start_through_the_menu(bad)
                refused = (not o.is_scoring_mode) and (not o.is_official_jumping) and o.save_data == [] and self.sent() == []
                self.contract(refused, "T05", "START-INDEX-OUT-OF-RANGE-NOT-REFUSED",
                              "scoring=%r official_jump=%r checkpoints=%d commands=%r" % (o.is_scoring_mode, o.is_official_jumping, len(o.save_data), self.sent()))

    def test_RED_T04_the_second_same_position_station_gets_its_own_checkpoint(self):
        o = self.o
        o.station_list = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        bind_scope(o, o.station_list)
        o.bve_arr_idx = 1
        self.arrive(1000.0, 999.0, name="B1", is_pass=1)
        self.assertEqual([c["station_name"] for c in o.save_data], ["A", "B1"])                      # the fixture made the first arrival's checkpoint
        o.bve_arr_idx = 2
        saves = self.arrive(1000.0, 999.0, name="B2", is_pass=1, saves=o.save_data)
        self.contract([c.get("station_index") for c in saves[1:]] == [1, 2], "T04", "SAME-POSITION-PAIR-DROPPED",
                      "checkpoints %r; the second arrival (NEXTLOC unchanged) was dropped by the float equality of target_loc" % ([c["station_name"] for c in saves],))


# ==============================================================================================================================================
# F - the HISTORY of the checkpoints (the owner's requirement of the ST-2a review): one ordered list from the start station to the present
# ==============================================================================================================================================
def abcde():
    return [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0), st("E", 4000.0, terminal=True)]


class F_TheCheckpointHistory(ContractMixin, F1.Base):
    def start_through_the_menu(self, start_idx):
        o = self.o
        o.setting_start_idx = start_idx
        o.menu_state = 10
        o.menu_cursor = 1
        o.handle_menu_enter(True)

    def test_the_history_runs_from_the_start_station_through_every_arrival_and_the_start_is_never_overwritten(self):
        o = self.o
        o.station_list = abcde()
        R.bind_identity(o, arr_idx=-1, tgt_idx=-1)
        self.start_through_the_menu(0)
        self.assertEqual(self.sent(), [self.v2("STA", 0, T0)])
        history = o.save_data
        start = history[0]
        start_copy = dict(start)
        self.assertEqual({k: start[k] for k in CHECKPOINT_FIELDS}, {"station_index": 0, "scope": (SID, LID, 5), "station_location": 0.0, "role": "scoring_start"})
        for idx, name in ((1, "B"), (2, "C"), (3, "D")):
            R.bind_identity(o, arr_idx=idx, tgt_idx=idx + 1)                              # (the target is already the next station)
            history = self.arrive(o.station_list[idx]["location"], o.station_list[idx]["location"] - 1.0, name=name, is_pass=1, saves=o.save_data)
            self.assertEqual([c["station_index"] for c in history], list(range(idx + 1)))
            self.assertIs(history[0], start)                                              # the start station is the same checkpoint, untouched
            self.assertEqual(dict(history[0]), start_copy)
        self.assertEqual([c["role"] for c in history], ["scoring_start", "arrived_station", "arrived_station", "arrived_station"])
        self.assertEqual([c["station_name"] for c in history], ["A", "B", "C", "D"])
        self.assertEqual({tuple(c["scope"]) for c in history}, {(SID, LID, 5)})
        # an earlier checkpoint is never overwritten by a later arrival
        before = [dict(c) for c in history]
        R.bind_identity(o, arr_idx=3, tgt_idx=4)
        history = self.arrive(3000.0, 2999.0, name="D", is_pass=1, saves=o.save_data)
        self.assertEqual([dict(c) for c in history], before)                              # the same arrival twice: one checkpoint

    def test_the_history_is_one_ordered_list_owned_by_the_overlay_and_the_retry_request_does_not_cut_it(self):
        """The structure the later phases build on: save_data is a plain list of dicts. Phase ST-2b changed WHEN the cut happens (ST-2a: the retry request cut it at once):
        the request keeps 'A B C D' and leaves the pending retry; the cut 'A B' is the pure rule resolve_retry_history that ST-3 applies after the matching completion."""
        o = self.o
        stations = abcde()
        history = []
        for idx, role in ((0, "scoring_start"), (1, "arrived_station"), (2, "arrived_station"), (3, "arrived_station")):
            history.append(F1.with_identity(F1.cp(stations[idx]["location"], T0 + idx, name=stations[idx]["name"]), idx, stations[idx]["location"], count=5, role=role))
        self.assertIs(type(history), list)
        bind_scope(o, stations)
        self.retry(1, history, stations=stations)
        self.assertIs(o.save_data, history)
        self.assertEqual([c["station_name"] for c in o.save_data], ["A", "B", "C", "D"])
        self.assertEqual([c["station_name"] for c in SI.resolve_retry_history(o.save_data, o.retry_pending, SID, LID, stations)], ["A", "B"])


# ==============================================================================================================================================
# G - the checkpoint by kind of stop, through the real per-tick scoring (update_physics_and_scoring): commercial stop, operational stop, pass
# ==============================================================================================================================================
class G_TheCheckpointByKindOfStop(ContractMixin, CH.Base):
    def bind(self, arr_idx, tgt_idx):
        R.bind_identity(self.o, arr_idx=arr_idx, tgt_idx=tgt_idx, sid=SID, list_id=LID)

    def test_a_commercial_stop_is_saved_when_the_arrival_is_judged_at_the_door_opening_with_its_restart_time(self):
        o = self.o
        o.bve_door_close_time_ms = 4630
        self.bind(1, 2)                                                                    # ARR = B, the target already names C
        self.scene(d=0.0, doordir=1, is_pass=0)
        self.tick()
        self.assertEqual(self.arrivals(), 0)                                               # stopped, doors closed: not an arrival
        self.open_doors()
        self.assertEqual(self.arrivals(), 1)
        saved = o.save_data[-1]
        self.assertEqual(self.stop_popups(), ["停止位置 +500"])
        self.assertEqual((saved["station_index"], saved["role"], saved["scope"], saved["station_location"]), (1, "arrived_station", (SID, LID, 4), 1000.0))
        self.assertEqual(saved["score"], o.score)                                          # the score of the arrival is settled before the checkpoint is taken
        self.assertEqual(saved["score"], 500)
        self.assertEqual(saved["time_ms"], CH.T0 + 60000 + 4630)                           # the existing restart time of a commercial stop: the door time is added

    def test_an_operational_stop_is_saved_when_the_stop_is_judged_with_the_time_of_the_stop(self):
        o = self.o
        o.bve_door_close_time_ms = 4630
        self.bind(1, 2)
        self.scene(d=0.0, doordir=0, is_pass=0)
        self.tick()
        self.assertEqual(o.bve_door, 0)                                                    # no door is ever opened
        self.assertEqual(self.arrivals(), 1)
        saved = o.save_data[-1]
        self.assertEqual((saved["station_index"], saved["role"]), (1, "arrived_station"))
        self.assertEqual(self.stop_popups(), ["停止位置 +500"])
        self.assertEqual((saved["score"], saved["time_ms"]), (500, CH.T0 + 60000))         # the time of the stop: no door time

    def test_a_pass_station_that_is_passed_makes_no_checkpoint_and_leaves_the_history_alone(self):
        for speed, doordir in ((0.0, 1), (0.0, 0), (60.0, 1)):
            with self.subTest(speed=speed, doordir=doordir):
                self.rig.close()
                self.setUp()
                o = self.o
                self.bind(1, 1)                                                            # the sender would even name B: the station TYPE is what excludes it
                self.scene(d=0.0, is_pass=1, doordir=doordir, speed=speed)
                before = [dict(c) for c in o.save_data]
                self.tick(4)
                self.assertEqual((self.arrivals(), self.stop_popups(), [dict(c) for c in o.save_data]), (0, [], before))

    def test_a_stop_whose_arrival_index_names_another_station_scores_but_saves_nothing(self):
        o = self.o
        self.bind(0, 2)                                                                    # ARR = A while the stop is judged for B
        self.scene(d=0.0, doordir=1, is_pass=0)
        before = [dict(c) for c in o.save_data]
        self.tick()
        self.open_doors()
        self.assertEqual(self.stop_popups(), ["停止位置 +500"])                             # the scoring goes on ...
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual([dict(c) for c in o.save_data], before)                           # ... and no checkpoint of a wrong station exists

    def test_the_end_station_of_the_scoring_is_not_a_checkpoint(self):
        o = self.o
        self.bind(1, 1)                                     # Phase SI-R5.2-B: the target names B, the station at NEXTLOC (the end station is not found by a 1 m search)
        self.scene(d=0.0, doordir=0, is_pass=0, end_idx=1)
        self.tick()
        self.assertTrue(o.is_scoring_finished)
        self.assertEqual(self.arrivals(), 0)

    def test_a_train_that_runs_through_a_station_it_does_not_stop_at_makes_no_checkpoint(self):
        for doordir in (1, 0):
            with self.subTest(doordir=doordir):
                self.rig.close()
                self.setUp()
                o = self.o
                self.bind(1, 1)
                self.scene(d=0.0, is_pass=0, doordir=doordir, speed=60.0)                  # a stopping station, but the train does not stop (no pass flag)
                before = [dict(c) for c in o.save_data]
                self.tick(4)
                self.assertEqual((self.arrivals(), [dict(c) for c in o.save_data]), (0, before))

    def test_an_operational_stop_is_saved_at_the_first_stop_inside_the_range_and_only_once(self):
        o = self.o
        self.bind(1, 2)
        self.scene(d=5.01, doordir=0, is_pass=0)                                           # stopped, but outside the author-defined range
        self.tick(2)
        self.assertEqual(self.arrivals(), 0)
        o.bve_location = o.bve_next_loc - 1.0                                              # now inside the range, stopped
        self.tick()
        self.assertEqual(self.arrivals(), 1)
        self.assertEqual(o.save_data[-1]["station_index"], 1)
        self.tick(5)                                                                       # staying there is no new arrival
        o.bve_door = 1
        self.tick()
        self.assertEqual(self.arrivals(), 1)

    def test_the_checkpoint_of_a_commercial_stop_does_not_wait_for_the_time_score_of_the_door_closing(self):
        """The checkpoint is taken at the door opening; the time score of the stop is settled later, when the door has closed and the next station is shown. Both are normal."""
        o = self.o
        o.bve_door_close_time_ms = 4630
        self.bind(1, 1)                                                                    # Phase SI-R5.2-C: the target names B, the station at NEXTLOC (prev_tgt_idx = B departs at the switch below)
        stations = [st("A", 0.0), st("B", 1000.0, raw_dep=CH.T0 + 65000), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        self.scene(d=0.0, doordir=1, is_pass=0, stations=stations)
        self.tick()
        self.open_doors()
        self.assertEqual(self.arrivals(), 1)
        saved = dict(o.save_data[-1])
        self.assertEqual(o.score_details["time"], 0)                                       # no time score yet ...
        self.assertEqual([p["text"] for p in o.popups if p["category"] == "運転時分"], [])
        self.assertEqual(saved["score"], 500)                                              # ... and the checkpoint holds the score of the moment it was taken
        o.bve_door = 0
        o.bve_next_loc = 2000.0                                                             # the door has closed: the sender shows the next station ...
        o.bve_tgt_idx = 2                                                                   # ... and its target (C)
        self.tick()
        self.assertEqual(len([p for p in o.popups if p["category"] == "運転時分"]), 1)      # the time score of the stop is settled NOW
        self.assertGreater(o.score, 500)
        self.assertEqual(self.arrivals(), 1)
        self.assertEqual(dict(o.save_data[-1]), saved)                                     # the checkpoint was not touched by it

    def test_the_seven_items_the_loc_method_always_stored_are_stored_as_before_and_the_lateness_is_not_added_to_the_time(self):
        """The saved time is the BVE time of the moment (+ the door time on a late arrival), NEVER + the lateness; the position is the train's, the target is NEXTLOC."""
        o = self.o
        o.bve_door_close_time_ms = 4630
        self.bind(1, 2)
        late = [st("A", 0.0), st("B", 1000.0, raw_dep=CH.T0 + 35000), st("C", 2000.0), st("D", 3000.0, terminal=True)]       # scheduled arrival T0 + 20 s, the train is 40 s late
        self.scene(d=1.5, doordir=1, is_pass=0, stations=late)
        self.tick()
        self.open_doors()
        saved = o.save_data[-1]
        self.assertEqual((saved["loc"], saved["target_loc"], saved["stop_error"], saved["station_name"], saved["score"]), (998.5, 1000.0, 1.5, "B", o.score))
        self.assertEqual(saved["time_ms"], CH.T0 + 60000 + 4630)                           # the door time, not the 40 s lateness
        self.assertEqual(saved["score_details"], o.score_details)
        self.assertIsNot(saved["score_details"], o.score_details)                          # a copy: later scoring does not rewrite the checkpoint
        # the same stop on time: nothing is added
        self.rig.close()
        self.setUp()
        o = self.o
        o.bve_door_close_time_ms = 4630
        self.bind(1, 2)
        early = [st("A", 0.0), st("B", 1000.0, raw_dep=CH.T0 + 90000), st("C", 2000.0), st("D", 3000.0, terminal=True)]      # scheduled arrival T0 + 75 s: the train is early
        self.scene(d=0.0, doordir=1, is_pass=0, stations=early)
        self.tick()
        self.open_doors()
        self.assertEqual(o.save_data[-1]["time_ms"], CH.T0 + 60000)


# ==============================================================================================================================================
# H - Phase ST-2b: the RETRY uses the saved StationIndex and nothing else (N-06 .. N-10, N-13 .. N-17)
#     The retry station is the StationIndex of the CHOSEN checkpoint, verified against the current scope; a checkpoint that does not verify is refused (no request, no
#     history change, no count, no score change, no exception) and the refusal leaves ONE diagnostic line. The history is not cut by the request (ST-3 cuts it).
# ==============================================================================================================================================
def n2b_red(tid, code, note=""):
    """Declare an ST-2b N-xx contract: its id and the ONE failure code it has against the product of ST-2a (1483b4b)."""
    def deco(fn):
        fn.st2b = {"id": tid, "code": code, "note": note}
        return fn
    return deco


def ck(stations, index, t, role="arrived_station", **override):
    """A checkpoint of station `index` with the seven old items and the four identity items of ST-2a."""
    entry = stations[index]
    c = F1.cp(entry["location"], t, score=10 * index, details=None if role == "scoring_start" else F1.ZERO, name=entry["name"])
    F1.with_identity(c, index, entry["location"], count=len(stations), role=role)
    c.update(override)
    return c


def history_of(stations, count):
    return [ck(stations, i, T0 + 60000 * i, role="scoring_start" if i == 0 else "arrived_station") for i in range(count)]


RID1, RID2 = b"\x01" * 16, b"\x02" * 16


class RetryBase(ContractMixin, F1.Base):
    """The history [A, B, C, D] of the list A..E (E is the end station: no checkpoint), under the scope (SID, LID, 5), at the confirmation of the retry."""

    def setUp(self):
        super().setUp()
        o = self.o
        self.stations = abcde()
        bind_scope(o, self.stations)
        self.hist = history_of(self.stations, 4)
        o.save_data = self.hist
        o.total_retry_count = 2
        o.score = 77
        self.lines = []
        o.input_event_sink = lambda event, **fields: self.lines.append((event, fields))

    def reset(self):
        self.rig.close()
        self.setUp()

    def fingerprint(self):
        """Everything a retry may touch: a refusal must leave ALL of it as it was (the menu, the popups, the count, the history list itself)."""
        o = self.o
        return (self.snap(), o.is_official_retry, o.is_first_station, o.total_retry_count, o.has_departed, o.is_first_udp, o.rollback_msg, o.rollback_msg_timer, o.score,
                dict(o.score_details), [dict(c) for c in o.save_data], id(o.save_data), o.menu_state, o.menu_cursor, len(o.popups), len(self.events),
                getattr(o, "retry_pending", None), o.__dict__.get("was_advancing_before_menu", "unset"))

    def run_retry(self, position):
        before = self.fingerprint()
        result = self.S.execute_retry(self.o, position, True)
        return result, self.fingerprint() == before, self.sent()

    def control(self, position=1):
        """The unchanged fixture is accepted by the product (a refusal test is only a refusal test when the same fixture without the fault is retried)."""
        result, unchanged, cmds = self.run_retry(position)
        self.assertEqual(cmds, [self.v2("STA", position, T0 + 60000 * position)])
        self.reset()

    def refusal(self, mutate, reason, tid, code, position=1):
        mutate(self.o, self.hist)
        result, unchanged, cmds = self.run_retry(position)
        got = getattr(result, "reason", None)
        self.contract(unchanged and cmds == [] and getattr(result, "accepted", None) is False and got == reason, tid, code,
                      "state unchanged %r, commands %r, result %r (expected a refusal with reason %s)" % (unchanged, cmds, result, reason))

    def confirm(self, position, advancing=True):
        o = self.o
        o.menu_state = 3
        o.menu_cursor = 0
        o.target_retry_idx = position
        o.handle_menu_enter(advancing)

    def managed(self, request_id=RID1):
        """The managed mode: a jump client exists; the send answers with the RequestId (None = the client refused to send)."""
        self.o.jump_client = object()
        self.send_result = request_id

    def events_of(self, name):
        return [f for e, f in self.lines if e == name]


class H_TheRetry(RetryBase):
    # -- N-06 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-06", "CHECKPOINT-POSITION-CONTRADICTS-INDEX", "the saved station_location must be the position of the saved index in the current list (0.01 m); no position is ever used to find the station")
    def test_RED_N06_a_checkpoint_position_that_contradicts_its_index_is_refused(self):
        self.control()
        for label, value, reason in (("0.5 m away", 1000.5, "location-mismatch"), ("0.02 m away", 1000.02, "location-mismatch"),
                                     ("not finite", float("nan"), "location-invalid"), ("not a number", "1000", "location-invalid"), ("missing is an old form", None, "old-form")):
            with self.subTest(label=label):
                self.reset()
                if value is None:
                    self.refusal(lambda o, h: h[1].pop("station_location"), reason, "N-06", "CHECKPOINT-POSITION-CONTRADICTS-INDEX")
                else:
                    self.refusal(lambda o, h, v=value: h[1].update(station_location=v), reason, "N-06", "CHECKPOINT-POSITION-CONTRADICTS-INDEX")
        self.reset()
        self.hist[1]["station_location"] = 1000.01                                               # exactly the tolerance: still the same station
        result = self.S.execute_retry(self.o, 1, True)
        self.assertEqual(self.sent(), [self.v2("STA", 1, T0 + 60000)])
        if result is not None:                                                                   # (the product of ST-2a returns nothing)
            self.assertTrue(result.accepted)

    # -- N-07 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-07", "CHECKPOINT-ROLE-MISMATCH", "the role is scoring_start for position 0 and arrived_station for every later position; any other word is refused")
    def test_RED_N07_a_checkpoint_with_a_wrong_role_is_refused(self):
        self.control()
        for label, position, role in (("an unknown word", 1, "foo"), ("a role that is no checkpoint role", 1, "target_station"), ("position 0 is not the start", 0, "arrived_station"),
                                      ("a later position claims the start", 1, "scoring_start"), ("no role at all", 1, None)):
            with self.subTest(label=label):
                self.reset()
                if role is None:
                    self.refusal(lambda o, h: h[1].pop("role"), "old-form", "N-07", "CHECKPOINT-ROLE-MISMATCH")
                else:
                    self.refusal(lambda o, h, p=position, r=role: h[p].update(role=r), "role-mismatch", "N-07", "CHECKPOINT-ROLE-MISMATCH", position=position)

    # -- N-08 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-08", "RETRY-WHILE-IDENTITY-UNAVAILABLE", "while the application holds no verified list / scenario identity the retry is refused (it never falls back to station 0)")
    def test_RED_N08_a_retry_while_the_current_identity_is_unavailable_is_refused(self):
        self.control()
        for label, mutate, reason in (("no list id", lambda o, h: setattr(o, "bve_list_id", ""), "scope-incomplete"),
                                      ("unknown scenario", lambda o, h: setattr(o, "current_scenario_id", -1), "scope-incomplete"),
                                      ("empty station list", lambda o, h: setattr(o, "station_list", []), "no-station-list"),
                                      ("no station list", lambda o, h: setattr(o, "station_list", None), "no-station-list"),
                                      ("station list attribute missing", lambda o, h: delattr(o, "station_list"), "no-station-list")):
            with self.subTest(label=label):
                self.reset()
                self.refusal(mutate, reason, "N-08", "RETRY-WHILE-IDENTITY-UNAVAILABLE")

    # -- N-09 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-09", "REFUSED-RETRY-IS-COUNTED", "the retry count grows only by a request that was sent: a refusal, a request that could not be sent and the same request twice add nothing")
    def test_RED_N09_a_refused_retry_is_not_counted_and_changes_nothing(self):
        o = self.o
        self.hist[1]["scope"] = (SID, LID, 6)                                                    # the checkpoint belongs to another list size
        self.assertNotIn("was_advancing_before_menu", o.__dict__)
        self.confirm(1)
        ok = (o.total_retry_count == 2 and self.sent() == [] and o.save_data is self.hist and len(o.save_data) == 4 and o.score == 77 and o.menu_state == 3 and
              "was_advancing_before_menu" not in o.__dict__ and not o.is_official_jumping)
        self.contract(ok, "N-09", "REFUSED-RETRY-IS-COUNTED",
                      "count %r (was 2), commands %r, history %d, menu_state %r, was_advancing set %r" % (o.total_retry_count, self.sent(), len(o.save_data), o.menu_state,
                                                                                                         "was_advancing_before_menu" in o.__dict__))
        for label, position, expected in (("a later station", 1, 3), ("the start", 0, 0)):
            with self.subTest(label=label):
                self.reset()
                self.confirm(position)
                self.assertEqual(o_count(self), expected)
        self.reset()
        self.managed(None)                                                                       # the managed client refused to send: the request was never sent
        self.confirm(1)
        self.assertEqual(o_count(self), 2)
        self.reset()
        self.managed(RID1)
        self.confirm(1)
        self.assertEqual(o_count(self), 3)
        self.o.is_official_jumping = False                                                       # (the jump is over)
        self.send_result = RID2
        self.confirm(2)
        self.assertEqual(o_count(self), 4)                                                       # another request: counted
        self.o.is_official_jumping = False
        self.confirm(3)                                                                          # the same RequestId answered again: it is the same request, counted once
        self.assertEqual(o_count(self), 4)

    # -- N-10 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-10", "SAVE-THEN-RETRY-CHAIN-SAME-POSITION", "an arrival saved at the second of two same-position stations is retried to THAT station")
    def test_RED_N10_the_second_same_position_station_is_saved_and_retried_as_itself(self):
        o = self.o
        stations = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0), st("E", 4000.0, terminal=True)]
        o.station_list = stations
        bind_scope(o, stations)
        o.bve_arr_idx = 1
        self.arrive(1000.0, 999.0, name="B1", is_pass=1, saves=[ck(stations, 0, T0, role="scoring_start")])
        o.bve_arr_idx = 2
        saves = self.arrive(1000.0, 999.0, name="B2", is_pass=1, saves=o.save_data)
        self.assertEqual([c["station_name"] for c in saves], ["A", "B1", "B2"])                  # (ST-2a: both arrivals have their own checkpoint)
        self.assertEqual([c["station_index"] for c in saves], [0, 1, 2])
        self.confirm(2)
        want = [self.v2("STA", 2, saves[2]["time_ms"])]
        self.contract(self.sent() == want, "N-10", "SAVE-THEN-RETRY-CHAIN-SAME-POSITION", "sent %r, expected %r (B1 and B2 are different stations)" % (self.sent(), want))


def o_count(test):
    return test.o.total_retry_count


class I_ThePendingRetry(RetryBase):
    # -- N-13 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-13", "RETRY-REQUEST-CUTS-THE-HISTORY", "the request alone does not cut the history: [A,B,C,D] stays, the choice is kept as a minimal pending retry (ST-3 cuts it after the matching completion)")
    def test_RED_N13_the_request_keeps_the_whole_history_and_leaves_a_pending_retry(self):
        for label, managed, rid in (("normal mode", False, None), ("managed mode", True, RID1)):
            with self.subTest(label=label):
                self.reset()
                o = self.o
                if managed:
                    self.managed(rid)
                self.S.execute_retry(o, 1, True)
                kept = o.save_data is self.hist and [c["station_name"] for c in o.save_data] == ["A", "B", "C", "D"]
                self.contract(kept, "N-13", "RETRY-REQUEST-CUTS-THE-HISTORY", "history %r after the request (identical list: %r)" % ([c["station_name"] for c in o.save_data], o.save_data is self.hist))
                p = getattr(o, "retry_pending", None)
                ok = (p is not None and p.selected_save_position == 1 and p.selected_station_index == 1 and tuple(p.selected_scope) == (SID, LID, 5) and p.checkpoint is self.hist[1] and
                      p.request_id == rid and p.scenario_id == SID and p.original_history_length == 4 and p.state == "sent")
                self.contract(ok, "N-13", "RETRY-REQUEST-CUTS-THE-HISTORY", "pending retry %r" % (p,))
                self.assertEqual(self.sent(), [self.v2("STA", 1, T0 + 60000)])

    # -- N-14 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-14", "RETRY-WHILE-PENDING-NOT-REFUSED", "while a retry is pending a second one is refused; once the jump is over the stale pending is simply replaced")
    def test_RED_N14_a_second_retry_while_one_is_pending_is_refused(self):
        o = self.o
        self.S.execute_retry(o, 1, True)
        self.assertTrue(o.is_official_jumping)
        first = self.sent()
        result, unchanged, cmds = self.run_retry(2)
        self.contract(unchanged and cmds == first and getattr(result, "accepted", None) is False and getattr(result, "reason", None) == "retry-pending", "N-14",
                      "RETRY-WHILE-PENDING-NOT-REFUSED", "second retry: unchanged %r, commands %r, result %r" % (unchanged, cmds, result))
        self.assertEqual(o.retry_pending.selected_save_position, 1)
        o.is_official_jumping = False                                                            # the jump is over: the pending is stale
        result, unchanged, cmds = self.run_retry(2)
        self.assertTrue(result.accepted)
        self.assertEqual(o.retry_pending.selected_save_position, 2)
        self.assertEqual(self.sent(), first + [self.v2("STA", 2, T0 + 120000)])

    # -- N-15 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-15", "PENDING-TRUNCATE-RESOLUTION-ABSENT", "the cut of the history after a matching completion is a pure function of (history, pending, current scope); ST-2b only fixes it, ST-3 wires it")
    def test_RED_N15_the_truncation_of_a_pending_retry_is_resolved_by_a_pure_function(self):
        self.contract(hasattr(SI, "resolve_retry_history"), "N-15", "PENDING-TRUNCATE-RESOLUTION-ABSENT", "station_identity has no resolve_retry_history")
        o = self.o
        self.managed(RID1)
        self.S.execute_retry(o, 1, True)
        pending = o.retry_pending
        scope = (SID, LID, self.stations)

        absent = object()

        def resolve(history=None, p=absent, current=scope):
            return SI.resolve_retry_history(self.hist if history is None else history, pending if p is absent else p, current[0], current[1], current[2])

        before = [dict(c) for c in self.hist]
        cut = resolve()
        self.assertEqual([c["station_name"] for c in cut], ["A", "B"])
        self.assertIsNot(cut, self.hist)
        self.assertEqual([dict(c) for c in self.hist], before)
        self.assertEqual(len(self.hist), 4)                                                      # the input is never touched
        self.assertIsNone(resolve(history=self.hist[:1]))                                         # the position is gone
        self.assertIsNone(resolve(history=[dict(c) for c in self.hist]))                          # another element at the position (cleared / replaced history)
        self.assertIsNone(resolve(current=(SID + 1, LID, self.stations)))                         # another scenario
        self.assertIsNone(resolve(current=(SID, "DEADBEEF", self.stations)))                      # another list
        self.assertIsNone(resolve(current=(SID, LID, self.stations[:3])))                         # another count
        self.assertIsNone(resolve(p=pending._replace(state="validated")))                         # the request was never sent
        self.assertIsNone(resolve(p=None))
        longer = self.hist + [ck(self.stations, 2, T0 + 999, name="C2")]                          # a checkpoint added after the request: the cut is by position
        self.assertEqual([c["station_name"] for c in resolve(history=longer)], ["A", "B"])
        self.reset()
        self.S.execute_retry(self.o, 0, True)
        zero = self.o.retry_pending
        self.assertEqual([c["station_name"] for c in SI.resolve_retry_history(self.hist, zero, SID, LID, self.stations)], ["A"])


class J_TheRetryHasNoSearch(unittest.TestCase):
    # -- N-16 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-16", "RETRY-REINFERS-THE-STATION", "execute_retry holds no search over the station list, no distance, no telemetry index and no station-0 constant: the station is the saved StationIndex")
    def test_RED_N16_execute_retry_does_not_infer_the_station(self):
        tree = ast.parse(read("scoring_logic.py"))
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"]
        self.assertEqual(len(fn), 1)
        found = []
        for node in ast.walk(fn[0]):
            if isinstance(node, (ast.For, ast.AsyncFor)) and any((isinstance(n, ast.Attribute) and n.attr == "station_list") or (isinstance(n, ast.Name) and n.id == "station_list")
                                                              for n in ast.walk(node.iter)):
                found.append("a loop over the station list (line %d)" % node.lineno)
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)) and any(
                    (isinstance(n, ast.Attribute) and n.attr == "station_list") or (isinstance(n, ast.Name) and n.id == "station_list") for g in node.generators for n in ast.walk(g.iter)):
                found.append("a comprehension over the station list (line %d)" % node.lineno)
            if isinstance(node, ast.Name) and node.id in {"enumerate", "min", "max", "abs", "target_bve_sta_idx"}:
                found.append("%s (line %d)" % (node.id, node.lineno))
            if isinstance(node, ast.Attribute) and node.attr in {"bve_tgt_idx", "bve_arr_idx", "bve_next_loc", "bve_location", "setting_start_idx"}:
                found.append("%s (line %d)" % (node.attr, node.lineno))
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and type(node.value.value) is int and node.value.value == 0 and
                    all(isinstance(t, (ast.Name, ast.Attribute)) for t in node.targets)):
                names = [t.attr if isinstance(t, ast.Attribute) else t.id for t in node.targets]
                if names != ["total_retry_count"]:
                    found.append("a constant 0 assigned to %s (line %d)" % (names, node.lineno))
        self.contract_ok(not found, "N-16", "RETRY-REINFERS-THE-STATION", "execute_retry: %s" % "; ".join(found))

    def contract_ok(self, ok, tid, code, detail=""):
        if not ok:
            raise ContractViolation(tid, code, detail)


class K_TheRefusalIsDiagnosed(RetryBase):
    # -- N-17 ---------------------------------------------------------------------------------------------------------------------------------
    @n2b_red("N-17", "RETRY-REFUSAL-NOT-DIAGNOSED", "ONE structured diagnostic line per retry operation (accepted or refused) in the internal log; nothing on the screen, no repetition, no per-tick output")
    def test_RED_N17_every_retry_operation_leaves_one_structured_line(self):
        o = self.o
        self.hist[1]["scope"] = (SID, LID, 6)
        popups_before = len(o.popups)
        self.confirm(1)
        names = [e for e, f in self.lines if e.startswith("retry-")]
        rejected = self.events_of("retry-rejected")
        ok = names == ["retry-rejected"] and len(rejected) == 1 and rejected[0].get("why") == "count-mismatch"
        self.contract(ok, "N-17", "RETRY-REFUSAL-NOT-DIAGNOSED", "retry events %r" % (names,))
        f = rejected[0]
        self.assertEqual((f["pos"], f["idx"], f["h"], f["c"], f["pend"], f["cur"], f["sav"]), (1, 1, "4/4", "2/2", "none", "%d:%s:5" % (SID, LID), "%d:%s:6" % (SID, LID)))
        self.assertEqual((len(o.popups), o.menu_state), (popups_before, 3))                      # nothing on the screen, the menu is where it was
        self.confirm(1)                                                                          # a second operation is a second line (none repeated inside one operation)
        self.assertEqual([e for e, _ in self.lines if e.startswith("retry-")], ["retry-rejected", "retry-rejected"])
        self.reset()
        self.managed(RID1)
        self.confirm(2)
        accepted = self.events_of("retry-accepted")
        self.assertEqual([e for e, _ in self.lines if e.startswith("retry-")], ["retry-accepted"])
        g = accepted[0]
        self.assertEqual((g["pos"], g["idx"], g["h"], g["c"], g["pend"], g["id"], g["cur"]), (2, 2, "4/4", "2/3", "sent", RID1[:4].hex().upper(), "%d:%s:5" % (SID, LID)))

    def test_the_line_fits_the_caller_cap_for_every_reason_and_names_nothing(self):
        """The Caller keeps 160 characters of an application line: prefix `[MANAGED] event=retry-rejected pid=1234567 ` + the fields (sorted) must fit, with a
        station list of 99 stations, a 4-digit scenario and a 15-checkpoint history."""
        self.assertTrue(hasattr(SI, "RETRY_REASONS"), "PREMISE-MISSING: station_identity.RETRY_REASONS (ST-2b) is not in this product; this test is never skipped")
        longest = 0
        for reason, mutate in (("count-mismatch", lambda o, h: h[3].update(scope=(SID, LID, 98))), ("location-mismatch", lambda o, h: h[3].update(station_location=1234.5)),
                               ("old-form", lambda o, h: h[3].pop("station_location")), ("role-mismatch", lambda o, h: h[3].update(role="x" * 40)),
                               ("index-out-of-range", lambda o, h: h[3].update(station_index=77)), ("no-station-list", lambda o, h: setattr(o, "station_list", []))):
            with self.subTest(reason=reason):
                self.reset()
                mutate(self.o, self.hist)
                self.o.current_scenario_id = 7777
                self.o.total_retry_count = 12
                self.confirm(3)
                line = [f for e, f in self.lines if e == "retry-rejected"][0]
                text = "[MANAGED] event=retry-rejected pid=1234567"
                for key in sorted(line):
                    text += " %s=%s" % (key, line[key])
                longest = max(longest, len(text))
                self.assertLessEqual(len(text), 160, text)
                self.assertNotIn("\\", text)
                self.assertNotIn("B", [w for w in text.split(" ") if w.startswith("name=")])    # no station name is ever a field


# ==============================================================================================================================================
# L - the eight ST-0 REDs that ST-2b turns GREEN (executed here: same contract id, same declared code, same body)
#     T08 T03 T04 T05 x2 T06 T09 (the retry) and T23 (static). tests/red_st0_stationindex_contract.py keeps the originals, unchanged, as MIGRATED evidence of the RED.
# ==============================================================================================================================================
def mst(name, loc, **kw):
    return CH.sta(name, loc, **kw)


def mcp(loc, t, name="X", target_loc=None, score=0, details=None, stop_error=0.0):
    d = {"loc": loc, "time_ms": t, "score": score, "target_loc": loc if target_loc is None else target_loc, "station_name": name, "stop_error": stop_error}
    if details is not None:
        d["score_details"] = dict(details)
    return d


def contract_cp(stations, index, loc, t, name, role="arrived_station", sid=SID, list_id=LID, count=None, details=None, station_location=None):
    """A checkpoint with ALL the fields of the contract on top of the seven existing ones (the helper of the ST-0 RED file)."""
    d = mcp(loc, t, name=name, target_loc=stations[index]["location"] if 0 <= index < len(stations) else loc, details=details)
    d.update(station_index=index, scope=(sid, list_id, len(stations) if count is None else count),
             station_location=stations[index]["location"] if station_location is None and 0 <= index < len(stations) else station_location, role=role)
    d["stop_error"] = d["target_loc"] - loc
    return d


class L_MigratedRetry(ContractMixin, F1.Base):
    def fingerprint(self):
        o = self.o
        return (self.snap(), o.is_official_retry, o.is_first_station, o.total_retry_count, o.has_departed, o.is_first_udp, o.rollback_msg, o.rollback_msg_timer,
                o.score, dict(o.score_details), [dict(c) for c in o.save_data], o.menu_state)

    def positive_control(self, stations):
        """A checkpoint whose saved index AND position agree is retried: it proves that the fixture of a REFUSAL test is accepted by a product that has no fault to refuse."""
        o = self.o
        bind_scope(o, stations)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 60000, "B", details=F1.ZERO)]
        cmds = self.retry(1, saves, stations)
        self.assertEqual(cmds, [self.v2("STA", 1, T0 + 60000)])
        self.events.clear()
        o.is_official_jumping = False

    def test_RED_T08_the_retry_station_is_the_saved_index_not_a_search_from_the_checkpoint_position(self):
        o = self.o
        stations = [mst("A", 0.0), mst("B", 1000.0), mst("C", 2000.0), mst("D", 3000.0, terminal=True)]
        self.positive_control(stations)
        bind_scope(o, stations)
        saved = contract_cp(stations, 2, 1500.0, T0 + 120000, "C", details=F1.ZERO)                     # 500 m from B and from C: a 100 m search finds nothing
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 60000, "B", details=F1.ZERO), saved]
        cmds = self.retry(2, saves, stations)
        self.contract(cmds == [self.v2("STA", 2, T0 + 120000)], "T08", "RETRY-DOES-NOT-USE-THE-SAVED-INDEX", "sent %r instead of the saved index 2" % (cmds,))

    def test_RED_T03_several_stations_within_100_m_keep_the_saved_index(self):
        o = self.o
        stations = [mst("A", 0.0), mst("B", 1000.0), mst("C", 1060.0), mst("D", 3000.0, terminal=True)]
        self.positive_control(stations)
        bind_scope(o, stations)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 1000, "B", details=F1.ZERO),
                 contract_cp(stations, 2, 1050.0, T0 + 60000, "C", details=F1.ZERO)]
        cmds = self.retry(2, saves, stations)
        self.contract(cmds == [self.v2("STA", 2, T0 + 60000)], "T03", "RETRY-IGNORES-THE-SAVED-INDEX-AMONG-NEIGHBOURS", "sent %r; the saved index is 2 (C), B is 50 m away" % (cmds,))

    def test_RED_T04_a_retry_to_the_second_of_two_same_position_stations_goes_to_the_second(self):
        o = self.o
        stations = [mst("A", 0.0), mst("B1", 1000.0), mst("B2", 1000.0), mst("D", 3000.0, terminal=True)]
        self.positive_control(stations)
        bind_scope(o, stations)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 1000, "B1", details=F1.ZERO),
                 contract_cp(stations, 2, 1000.0, T0 + 60000, "B2", details=F1.ZERO)]
        cmds = self.retry(2, saves, stations)
        self.contract(cmds == [self.v2("STA", 2, T0 + 60000)], "T04", "SAME-POSITION-PAIR-NOT-DISTINGUISHED", "sent %r; B1 and B2 are different elements" % (cmds,))

    def refusal_case(self, stations, saved_mutator, tid, code):
        o = self.o
        self.positive_control(stations)
        bind_scope(o, stations)
        saved = contract_cp(stations, 1, 1000.0, T0 + 60000, "B", details=F1.ZERO)
        saved_mutator(saved)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), saved]
        o.save_data = saves
        o.station_list = stations
        self.assertEqual(len(o.save_data), 2)
        before = self.fingerprint()
        self.S.execute_retry(o, 1, True)
        cmds = self.sent()
        changed = self.fingerprint() != before
        self.contract((cmds == []) and not changed, tid, code, "commands %r, state changed: %r" % (cmds, changed))

    def test_RED_T05_an_out_of_range_saved_index_is_refused_without_a_command_or_a_state_change(self):
        stations = [mst("A", 0.0), mst("B", 1000.0), mst("C", 2000.0), mst("D", 3000.0, terminal=True)]
        for bad in (9, 4, -1):
            with self.subTest(bad=bad):
                self.rig.close()
                self.setUp()
                self.refusal_case(stations, lambda c, bad=bad: c.update(station_index=bad), "T05", "INVALID-INDEX-NOT-REFUSED")

    def test_RED_T05_an_old_form_checkpoint_without_station_index_is_refused(self):
        stations = [mst("A", 0.0), mst("B", 1000.0), mst("C", 2000.0), mst("D", 3000.0, terminal=True)]
        self.refusal_case(stations, lambda c: c.pop("station_index"), "T05", "OLD-FORMAT-CHECKPOINT-NOT-REFUSED")

    def test_RED_T06_a_checkpoint_of_another_generation_or_list_is_refused(self):
        stations = [mst("A", 0.0), mst("B", 1000.0), mst("C", 2000.0), mst("D", 3000.0, terminal=True)]
        variants = (("scenario generation", lambda c: c.update(scope=(SID + 1, LID, 4))),
                    ("station list id", lambda c: c.update(scope=(SID, "DEADBEEF", 4))),
                    ("station count", lambda c: c.update(scope=(SID, LID, 5))))
        for label, mutate in variants:
            with self.subTest(label=label):
                self.rig.close()
                self.setUp()
                self.refusal_case(stations, mutate, "T06", "SCOPE-MISMATCH-NOT-REFUSED")

    def test_RED_T09_the_retry_to_the_initial_checkpoint_uses_the_chosen_start_station(self):
        o = self.o
        o.setting_start_idx = 2
        stations = [mst("A", 0.0), mst("P", 950.0), mst("Q", 1000.0), mst("D", 3000.0, terminal=True)]
        bind_scope(o, stations)
        initial = contract_cp(stations, 2, 1000.0, T0, "Q", role="scoring_start")
        self.assertEqual((initial["station_index"], initial["station_location"]), (2, 1000.0))
        cmds = self.retry(0, [initial], stations)
        self.contract(cmds == [self.v2("STA", 2, T0)] and o.expected_target_loc == 1000.0, "T09", "INITIAL-CHECKPOINT-RETRY-IGNORES-START-INDEX",
                      "sent %r, expected location %r (the position search lands on P, index 1)" % (cmds, o.expected_target_loc))

    def test_RED_T23_execute_retry_has_no_100_m_position_search(self):
        tree = ast.parse(read("scoring_logic.py"))
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"]
        self.assertEqual(len(fn), 1)                                                                  # the function exists exactly once (a path problem is not a contract failure)
        hundreds = [n.value for n in ast.walk(fn[0]) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 100.0]
        self.contract(not hundreds, "T23", "EXECUTE-RETRY-HAS-100M-SEARCH", "execute_retry still contains %d float 100.0" % len(hundreds))


# ==============================================================================================================================================
# M - Phase ST-2b: the pure retry layer of station_identity (no Qt, no Overlay) and the retry inside the real Overlay: every reason code, the order of the checks, StationIndex 0,
#     the first checkpoint and a middle checkpoint through the same path, the pending retry, the count, the diagnostic line
# ==============================================================================================================================================
def ck_list(count=4):
    stations = abcde()
    return stations, history_of(stations, count)


class M_ThePureRetryLayer(unittest.TestCase):
    def setUp(self):
        self.stations, self.hist = ck_list()
        self.list = adopted(self.stations)

    GIVEN = object()

    def check(self, position=1, scenario=SID, list_id=LID, stations=None, pending_active=False, history=GIVEN):
        return SI.check_retry_checkpoint(self.hist if history is self.GIVEN else history, position, scenario, list_id, self.list if stations is None else stations, pending_active)

    def test_the_types_and_the_vocabulary(self):
        self.assertEqual(SI.RetryResult._fields, ("accepted", "reason", "request_id", "selected_station_index"))
        self.assertEqual(SI.RetryPending._fields, ("selected_save_position", "selected_station_index", "selected_scope", "checkpoint", "request_id", "scenario_id",
                                                   "original_history_length", "state"))
        self.assertEqual(SI.RETRY_REASONS, ("no-checkpoint", "old-form", "retry-pending", "jump-unavailable", "time-invalid"))
        self.assertEqual(set(SI.RETRY_REASONS) & set(SI.REASONS), set())                 # new words only: the words of ST-2a are reused, none is duplicated under another name
        self.assertEqual(SI.RETRY_STATES, ("validated", "sent"))
        self.assertEqual(SI.REASONS, ("ok", "no-observer", "not-ready", "no-station-list", "scenario-mismatch", "list-mismatch", "count-mismatch", "index-negative",
                                      "index-out-of-range", "location-invalid", "location-mismatch", "role-mismatch", "scope-incomplete", "internal-error"))     # (ST-2a's tuple is unchanged)

    def test_an_intact_checkpoint_is_accepted_for_every_position_and_the_result_is_immutable(self):
        for position in range(4):
            with self.subTest(position=position):
                result = self.check(position)
                self.assertEqual(result, SI.RetryResult(True, "ok", None, position))
                with self.assertRaises(AttributeError):
                    result.accepted = False

    def test_station_index_0_is_a_station_like_any_other_at_the_start_and_later_in_the_history(self):
        # a loop line: the start station comes again as a later arrival (index 0, role arrived_station); neither is refused and neither is a fall-back
        loop = self.hist + [ck(self.stations, 0, T0 + 999999)]
        self.assertEqual(self.check(0, history=loop), SI.RetryResult(True, "ok", None, 0))
        self.assertEqual(self.check(4, history=loop), SI.RetryResult(True, "ok", None, 0))

    def test_no_checkpoint(self):
        for position in (-1, 4, 99, "1", 1.0, True, None):
            with self.subTest(position=position):
                self.assertEqual(self.check(position), SI.RetryResult(False, "no-checkpoint", None, -1))
        for history in (None, (), "abc", {}):
            self.assertEqual(self.check(0, history=history).reason, "no-checkpoint")
        self.assertEqual(self.check(0, history=[]).reason, "no-checkpoint")

    def test_the_order_of_the_checks(self):
        broken = self.hist[1]
        broken.pop("station_index")                                                      # old form ...
        broken["role"] = "foo"                                                           # ... and a wrong role ...
        broken["time_ms"] = -5                                                           # ... and a wrong time
        self.assertEqual(self.check(1, pending_active=True).reason, "retry-pending")      # pending first (after the position)
        self.assertEqual(self.check(9, pending_active=True).reason, "no-checkpoint")
        self.assertEqual(self.check(1, stations=[]).reason, "no-station-list")            # the application's side next
        self.assertEqual(self.check(1, list_id="").reason, "scope-incomplete")
        self.assertEqual(self.check(1).reason, "old-form")                                 # then the checkpoint's form
        broken["station_index"] = 1
        self.assertEqual(self.check(1).reason, "role-mismatch")                           # the position agrees with index 1, so the role is next
        broken["role"] = "arrived_station"
        self.assertEqual(self.check(1).reason, "time-invalid")
        broken["time_ms"] = T0
        self.assertEqual(self.check(1), SI.RetryResult(True, "ok", None, 1))

    def test_old_form(self):
        for key in ("station_index", "scope", "station_location", "role", "score"):
            with self.subTest(missing=key):
                self.setUp()
                self.hist[1].pop(key)
                self.assertEqual(self.check(1), SI.RetryResult(False, "old-form", None, 1 if key != "station_index" else -1))
                self.assertEqual(SI.missing_checkpoint_item(self.hist[1]), key)
        for label, scope in (("two items", (SID, LID)), ("four items", (SID, LID, 5, 1)), ("a string", "7:A1B2C3D4:5"), ("no list id", (SID, "", 5)), ("unknown scenario", (-1, LID, 5)),
                             ("a bool count", (SID, LID, True)), ("None", None)):
            with self.subTest(scope=label):
                self.setUp()
                self.hist[1]["scope"] = scope
                self.assertEqual(self.check(1).reason, "old-form")
        for label, items in (("score is not a number", {"score": "10"}), ("score is a bool", {"score": True}), ("score is NaN", {"score": float("nan")}), ("details are no dict", {"score_details": [1]})):
            with self.subTest(label=label):
                self.setUp()
                self.hist[1].update(items)
                self.assertEqual(self.check(1).reason, "old-form")
        self.setUp()
        self.hist[1] = "not a checkpoint"
        self.assertEqual(self.check(1).reason, "old-form")

    def test_scope_mismatch_names_the_first_difference_scenario_then_list_then_count(self):
        self.assertEqual(self.check(1, scenario=SID + 1).reason, "scenario-mismatch")
        self.assertEqual(self.check(1, list_id="DEADBEEF").reason, "list-mismatch")
        self.hist[1]["scope"] = (SID, LID, 6)
        self.assertEqual(self.check(1).reason, "count-mismatch")
        self.hist[1]["scope"] = (SID + 1, "DEADBEEF", 6)
        self.assertEqual(self.check(1).reason, "scenario-mismatch")
        self.hist[1]["scope"] = [SID, LID, 5]                                            # (a stored list is as good as a stored tuple)
        self.assertEqual(self.check(1).reason, "ok")

    def test_the_index_is_inside_the_list(self):
        for value, reason in ((-1, "index-negative"), (-9, "index-negative"), ("1", "index-negative"), (True, "index-negative"), (1.0, "index-negative"),
                              (5, "index-out-of-range"), (99, "index-out-of-range")):
            with self.subTest(index=value):
                self.setUp()
                self.hist[1]["station_index"] = value
                self.assertEqual(self.check(1).reason, reason)

    def test_the_position_is_a_check_of_the_index_never_a_way_to_find_it(self):
        self.hist[1]["station_location"] = 1000.0 + 0.01
        self.assertTrue(self.check(1).accepted)                                           # exactly the tolerance
        self.hist[1]["station_location"] = 1000.0 + 0.0101
        self.assertEqual(self.check(1).reason, "location-mismatch")
        self.hist[1]["station_location"] = 2000.0                                         # the position of ANOTHER station of the list: still a contradiction, never a re-identification
        self.assertEqual(self.check(1).reason, "location-mismatch")
        for bad in (float("nan"), float("inf"), "1000", True, [1000.0]):
            self.hist[1]["station_location"] = bad
            self.assertEqual(self.check(1).reason, "location-invalid", repr(bad))
        broken_list = adopted([st("A", 0.0), {"name": "B"}, st("C", 2000.0), st("D", 3000.0), st("E", 4000.0, terminal=True)])
        self.hist[1]["station_location"] = 1000.0
        self.assertEqual(self.check(1, stations=broken_list).reason, "location-invalid")  # the list entry has no position

    def test_the_role_is_the_role_of_the_place(self):
        for position, role, ok in ((0, "scoring_start", True), (0, "arrived_station", False), (1, "arrived_station", True), (1, "scoring_start", False),
                                   (1, "target_station", False), (1, "", False), (2, 5, False)):
            with self.subTest(position=position, role=role):
                self.setUp()
                self.hist[position]["role"] = role
                self.assertEqual(self.check(position).accepted, ok)
                if not ok:
                    self.assertEqual(self.check(position).reason, "role-mismatch")

    def test_the_time_is_a_finite_number_not_below_zero(self):
        for value, ok in ((0, True), (T0, True), (0.5, True), (-1, False), (float("nan"), False), (float("inf"), False), ("1", False), (True, False), (None, False)):
            with self.subTest(time_ms=value):
                self.setUp()
                self.hist[1]["time_ms"] = value
                self.assertEqual(self.check(1).accepted, ok)
                if not ok:
                    self.assertEqual(self.check(1).reason, "time-invalid")
        self.hist[1].pop("time_ms")
        self.assertEqual(self.check(1).reason, "time-invalid")

    def test_nothing_is_changed_and_nothing_raises(self):
        junk = (None, 0, "x", [], {}, (), object(), float("nan"), -1, 10 ** 30)
        before = [dict(c) for c in self.hist]
        for history in junk + (self.hist,):
            for position in junk + (0, 1, 3):
                for stations in junk[:3] + (self.list,):
                    for scenario in (None, "7", -1, SID):
                        for list_id in (None, 5, "", LID):
                            result = SI.check_retry_checkpoint(history, position, scenario, list_id, stations, False)
                            self.assertIsInstance(result, SI.RetryResult)
                            if history is self.hist and position in (0, 1, 3) and stations is self.list and scenario == SID and list_id == LID:
                                self.assertTrue(result.accepted)
                            else:
                                self.assertFalse(result.accepted)
        self.assertEqual([dict(c) for c in self.hist], before)

    def test_the_pending_retry_of_an_accepted_checkpoint(self):
        pending = SI.make_retry_pending(self.hist, 2)
        self.assertEqual((pending.selected_save_position, pending.selected_station_index, tuple(pending.selected_scope), pending.request_id, pending.scenario_id,
                          pending.original_history_length, pending.state), (2, 2, (SID, LID, 5), None, SID, 4, "validated"))
        self.assertIs(pending.checkpoint, self.hist[2])
        sent = pending._replace(request_id=b"\x09" * 16, state="sent")
        self.assertEqual((sent.request_id, sent.state), (b"\x09" * 16, "sent"))
        self.assertIsNone(SI.make_retry_pending(self.hist, 9))
        self.assertIsNone(SI.make_retry_pending(None, 0))
        self.assertIsNone(SI.make_retry_pending(self.hist, 1, state="completed"))             # ST-2b knows validated and sent only
        self.hist[1].pop("scope")
        self.assertIsNone(SI.make_retry_pending(self.hist, 1))

    def test_the_diagnostic_event_names_the_reason_and_the_numbers_and_nothing_else(self):
        scope = SI.StationScope(SID, LID, 5)
        refused = SI.check_retry_checkpoint(self.hist, 1, SID + 1, LID, self.list)
        self.hist[1]["station_name"] = "SECRET STATION NAME"
        event, fields = SI.retry_event(refused, 1, 4, 4, 2, 2, None, SI.StationScope(SID + 1, LID, 5), self.hist[1], self.list)
        self.assertEqual(event, "retry-rejected")
        self.assertEqual(fields, {"pos": 1, "idx": 1, "h": "4/4", "c": "2/2", "pend": "none", "cur": "%d:%s:5" % (SID + 1, LID), "why": "scenario-mismatch", "sav": "%d:%s:5" % (SID, LID)})
        accepted = SI.RetryResult(True, "ok", b"\xab\xcd\xef\x01" + b"\x00" * 12, 2)
        event, fields = SI.retry_event(accepted, 2, 4, 4, 2, 3, SI.make_retry_pending(self.hist, 2, accepted.request_id, "sent"), scope)
        self.assertEqual((event, fields["id"], fields["pend"], fields["c"], fields["h"]), ("retry-accepted", "ABCDEF01", "sent", "2/3", "4/4"))
        self.assertNotIn("SECRET", repr(fields))
        for result, extra in ((SI.check_retry_checkpoint(self.hist, 1, SID, LID, self.list), {}), (SI.RetryResult(False, "old-form", None, -1), {"miss": "scope"})):
            self.assertEqual(SI.retry_event(result, 1, 4, 4, 2, 2, None, scope, self.hist[1], self.list)[0], "retry-accepted" if result.accepted else "retry-rejected")
        # per reason: the one extra item that explains it
        for mutate, reason, key, expect in ((lambda c: c.update(station_location=1234.5), "location-mismatch", "loc", "1234.50/1000.00"), (lambda c: c.update(role="x" * 40), "role-mismatch", "role", "other"),
                                            (lambda c: c.pop("station_location"), "old-form", "miss", "station_location"), (lambda c: c.update(role="target_station"), "role-mismatch", "role", "target_station")):
            self.setUp()
            mutate(self.hist[1])
            result = self.check(1)
            self.assertEqual(result.reason, reason)
            self.assertEqual(SI.retry_event(result, 1, 4, 4, 2, 2, None, scope, self.hist[1], self.list)[1][key], expect)
        no_list = SI.RetryResult(False, "no-station-list", None, 1)
        self.assertEqual(SI.retry_event(no_list, 1, 4, 4, 2, 2, None, None, self.hist[1], [], "no-observer")[1]["sync"], "no-observer")
        self.assertEqual(SI.retry_event(no_list, 1, 4, 4, 2, 2, None, None, self.hist[1], [])[1]["cur"], "none")
        waiting = SI.make_retry_pending(self.hist, 1, b"\x01" * 16, "sent")
        self.assertEqual(SI.retry_event(SI.RetryResult(False, "retry-pending", None, 2), 2, 4, 4, 2, 2, waiting, scope)[1]["ppos"], 1)
        self.assertEqual(SI.retry_event(object(), 1, 4, 4, 2, 2, None, scope), ("retry-rejected", {"why": "internal-error"}))      # never raises


class M2_TheRetryInTheOverlay(RetryBase):
    def test_the_first_checkpoint_and_a_middle_checkpoint_use_the_same_path_and_their_own_saved_index(self):
        for position, expected_cmd in ((0, self.v2("STA", 0, T0)), (2, self.v2("STA", 2, T0 + 120000))):
            with self.subTest(position=position):
                self.reset()
                o = self.o
                o.setting_start_idx = 3                                                      # what the user has chosen NOW plays no part: the checkpoint carries its station
                o.bve_tgt_idx, o.bve_arr_idx, o.bve_next_loc, o.bve_location = 4, 4, 4000.0, 3999.0       # nor does what the sender says now, nor where the train is
                result = self.S.execute_retry(o, position, True)
                self.assertEqual((result.accepted, result.selected_station_index), (True, position))
                self.assertEqual(self.sent(), [expected_cmd])
                self.assertEqual(o.expected_target_loc, self.stations[position]["location"])
                self.assertEqual(o.is_official_retry, position > 0)
                self.assertEqual(o.is_first_station, position == 0)

    def test_station_index_0_later_in_the_history_is_retried_to_station_0_not_refused(self):
        o = self.o
        o.save_data = self.hist + [ck(self.stations, 0, T0 + 999999)]
        result = self.S.execute_retry(o, 4, True)
        self.assertEqual((result.accepted, result.selected_station_index), (True, 0))
        self.assertEqual(self.sent(), [self.v2("STA", 0, T0 + 999999)])
        self.assertTrue(o.is_official_retry)                                                 # (a later position is a retry; only position 0 is the first station)

    def test_the_loc_method_condition_is_kept_for_a_middle_station(self):
        o = self.o
        self.stations[1].update(def_time=T0 + 100000, raw_dep=T0 + 15000 + 60000)           # defined later than calculated, checkpoint earlier than defined
        self.hist[1]["time_ms"] = T0 + 60000
        self.S.execute_retry(o, 1, True)
        self.assertEqual(self.sent(), [self.v2("LOC", 1, T0 + 60000)])

    def test_the_reasons_of_the_overlay_side(self):
        o = self.o
        for label, setup, position, reason in (
                ("no checkpoint", lambda: None, 9, "no-checkpoint"),
                ("negative position", lambda: None, -1, "no-checkpoint"),
                ("time", lambda: self.hist[1].update(time_ms=-1), 1, "time-invalid"),
                ("no jump client in the managed mode", lambda: setattr(o, "dataplane_strict", True), 1, "jump-unavailable"),
                ):
            with self.subTest(label=label):
                self.reset()
                o = self.o
                setup()
                result, unchanged, cmds = self.run_retry(position)
                self.assertEqual((result.accepted, result.reason, cmds, unchanged), (False, reason, [], True))
        self.reset()
        self.o.save_data = None                                                              # (no list at all: the answer is a refusal, never an exception)
        self.assertEqual(self.S.execute_retry(self.o, 1, True).reason, "no-checkpoint")
        self.reset()
        o = self.o
        o.save_data = [object()]
        self.assertEqual(self.S.execute_retry(o, 0, True).reason, "old-form")
        o.retry_pending = "not a pending retry"                                              # a stale or foreign value never raises: it is no pending retry
        self.assertEqual(self.S.execute_retry(o, 0, True).reason, "old-form")

    def test_a_refusal_at_the_start_does_not_reset_the_retry_count_an_acceptance_does(self):
        o = self.o
        self.hist[0]["role"] = "arrived_station"
        result, unchanged, cmds = self.run_retry(0)
        self.assertEqual((result.reason, unchanged, o.total_retry_count), ("role-mismatch", True, 2))
        self.hist[0]["role"] = "scoring_start"
        self.S.execute_retry(o, 0, True)
        self.assertEqual(o.total_retry_count, 0)

    def test_the_request_id_and_the_pending_retry_of_the_managed_mode(self):
        o = self.o
        self.managed(RID1)
        result = self.S.execute_retry(o, 2, True)
        self.assertEqual((result.accepted, result.request_id), (True, RID1))
        self.assertEqual((o.retry_pending.request_id, o.retry_pending.state), (RID1, "sent"))
        self.reset()
        o = self.o
        self.managed(None)                                                                  # the client refused to send: accepted, but nothing was sent
        result = self.S.execute_retry(o, 2, True)
        self.assertEqual((result.accepted, result.request_id), (True, None))
        self.assertEqual((o.retry_pending.request_id, o.retry_pending.state), (None, "validated"))
        self.assertEqual(o.save_data, self.hist)                                             # (still whole)
        self.reset()
        o = self.o
        self.S.execute_retry(o, 2, True)                                                    # the normal mode has no RequestId: the plain send IS the request
        self.assertEqual((o.retry_pending.request_id, o.retry_pending.state), (None, "sent"))

    def test_the_session_and_the_generation_discard_the_pending_retry(self):
        import managed_input
        for discard in (managed_input.discard_scoring_session, managed_input.discard_generation_state):
            with self.subTest(discard=discard.__name__):
                self.reset()
                o = self.o
                self.S.execute_retry(o, 1, True)
                self.assertIsNotNone(o.retry_pending)
                discard(o)
                self.assertIsNone(o.retry_pending)
                self.assertEqual(o.save_data, [])
        self.assertIsNone(managed_input.generation_defaults()["retry_pending"])

    def test_a_new_scoring_start_discards_the_pending_retry(self):
        o = self.o
        self.S.execute_retry(o, 1, True)
        self.assertIsNotNone(o.retry_pending)
        o.is_official_jumping = False
        o.setting_start_idx = 1
        o.menu_state = 10
        o.menu_cursor = 1
        o.handle_menu_enter(True)
        self.assertTrue(o.is_scoring_mode)                                                    # the fixture reached the start of the scoring ...
        self.assertIsNone(o.retry_pending)                                                    # ... which began a new history: the old choice belongs to the old one
        self.assertEqual([c["role"] for c in o.save_data], ["scoring_start"])

    def test_a_pending_retry_whose_history_is_gone_is_stale_and_never_blocks_the_next_retry(self):
        o = self.o
        self.S.execute_retry(o, 1, True)
        self.assertTrue(o.is_official_jumping)
        o.save_data = history_of(self.stations, 4)                                          # another history (a new scoring session): the pending retry points at an object that is not in it
        o.save_data[1]["time_ms"] = T0 + 61000
        result = self.S.execute_retry(o, 1, True)
        self.assertTrue(result.accepted)
        self.assertIs(o.retry_pending.checkpoint, o.save_data[1])

    def test_the_diagnostic_goes_to_the_sink_only_and_the_normal_mode_without_a_sink_writes_nothing(self):
        o = self.o
        o.input_event_sink = None
        self.hist[1]["scope"] = (SID, LID, 6)
        self.confirm(1)
        self.assertEqual((o.total_retry_count, o.menu_state), (2, 3))                         # refused, silently
        self.assertEqual(self.lines, [])
        self.assertEqual(self.log, [])                                                       # nor the Desktop log

    def test_the_resume_flag_of_the_menu_is_restored_by_a_refusal_whatever_it_was(self):
        for before in (None, False, True):
            with self.subTest(before=before):
                self.reset()
                o = self.o
                if before is not None:
                    o.was_advancing_before_menu = before
                self.hist[1]["scope"] = (SID, LID, 6)
                self.confirm(1, advancing=False)
                self.assertEqual(o.__dict__.get("was_advancing_before_menu", None), before)
        self.reset()
        self.confirm(1, advancing=False)                                                     # an accepted retry resumes BVE (the flag is True) as before
        self.assertTrue(self.o.was_advancing_before_menu)

    def test_the_trace_and_the_count_are_the_only_new_methods_of_main_and_they_show_nothing_on_the_screen(self):
        source = read("main.py")
        tree = ast.parse(source)
        overlay = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay"][0]
        methods = {n.name: ast.get_source_segment(source, n) for n in overlay.body if isinstance(n, ast.FunctionDef)}
        for name in ("_retry_count", "_retry_trace"):
            self.assertIn(name, methods)
            self.assertNotIn("popup", methods[name].lower())
            self.assertNotIn("menu_state", methods[name])
        self.assertNotRegex(read("menu_ui.py") + read("hud_ui.py"), r"retry_notice|retry_pending|retry-rejected")      # no screen text for the refusal: menu_ui.py / hud_ui.py are untouched by ST-2b

    def test_the_diagnostic_budget_of_the_controller_is_unchanged(self):
        import managed_input
        self.assertEqual(managed_input.ManagedInputController.EVENT_LINE_CAPS, {"input-hold": 24, "input-pause": 6, "input-resume": 6, "stidx": 24, "jump-settled": 24})        # Phase ST-3d: the ONE final line of an official jump transaction
        self.assertEqual((managed_input.ManagedInputController.EVENT_LINE_CAP, managed_input.ManagedInputController.TOTAL_LINE_BUDGET), (10, 70))


class Z_Meta(unittest.TestCase):
    def test_every_st2b_n_red_has_a_declared_code_and_the_eight_retry_reds_are_executed_here_once(self):
        found = {}
        for cls in (H_TheRetry, I_ThePendingRetry, J_TheRetryHasNoSearch, K_TheRefusalIsDiagnosed):
            for name in dir(cls):
                meta = getattr(getattr(cls, name), "st2b", None)
                if meta is not None:
                    self.assertTrue(name.startswith("test_RED_"), name)
                    self.assertRegex(meta["code"], r"^[A-Z0-9\-]+$")
                    found.setdefault(meta["id"], set()).add(meta["code"])
        self.assertEqual(set(found), {"N-06", "N-07", "N-08", "N-09", "N-10", "N-13", "N-14", "N-15", "N-16", "N-17"})
        for tid, codes in found.items():
            self.assertEqual(len(codes), 1, tid)
        self.assertEqual(found["N-06"], {"CHECKPOINT-POSITION-CONTRADICTS-INDEX"})
        self.assertEqual(found["N-09"], {"REFUSED-RETRY-IS-COUNTED"})
        self.assertEqual(found["N-13"], {"RETRY-REQUEST-CUTS-THE-HISTORY"})
        self.assertEqual(found["N-17"], {"RETRY-REFUSAL-NOT-DIAGNOSED"})
        import red_st0_stationindex_contract as red
        for name, cls_name, tid, code in (("test_RED_T08_the_retry_station_is_the_saved_index_not_a_search_from_the_checkpoint_position", "RetryReds", "T08", "RETRY-DOES-NOT-USE-THE-SAVED-INDEX"),
                                          ("test_RED_T03_several_stations_within_100_m_keep_the_saved_index", "RetryReds", "T03", "RETRY-IGNORES-THE-SAVED-INDEX-AMONG-NEIGHBOURS"),
                                          ("test_RED_T04_a_retry_to_the_second_of_two_same_position_stations_goes_to_the_second", "RetryReds", "T04", "SAME-POSITION-PAIR-NOT-DISTINGUISHED"),
                                          ("test_RED_T05_an_out_of_range_saved_index_is_refused_without_a_command_or_a_state_change", "RetryReds", "T05", "INVALID-INDEX-NOT-REFUSED"),
                                          ("test_RED_T05_an_old_form_checkpoint_without_station_index_is_refused", "RetryReds", "T05", "OLD-FORMAT-CHECKPOINT-NOT-REFUSED"),
                                          ("test_RED_T06_a_checkpoint_of_another_generation_or_list_is_refused", "RetryReds", "T06", "SCOPE-MISMATCH-NOT-REFUSED"),
                                          ("test_RED_T09_the_retry_to_the_initial_checkpoint_uses_the_chosen_start_station", "RetryReds", "T09", "INITIAL-CHECKPOINT-RETRY-IGNORES-START-INDEX"),
                                          ("test_RED_T23_execute_retry_has_no_100_m_position_search", "StaticReds", "T23", "EXECUTE-RETRY-HAS-100M-SEARCH")):
            with self.subTest(name):
                self.assertTrue(hasattr(L_MigratedRetry, name))                                          # executed here ...
                meta = getattr(getattr(getattr(red, cls_name), name), "st0red")                           # ... and kept there, skipped, as the evidence of the RED
                self.assertEqual((meta["kind"], meta["id"], meta["code"], meta["to"]), ("MIGRATED", tid, code, THIS_FILE))
                self.assertTrue(getattr(getattr(getattr(red, cls_name), name), "__unittest_skip__", False))

    def test_u13_is_a_declared_red_until_st3_and_never_deleted_or_skipped(self):
        """OD-B2: Python uses the saved index (ST-2b) while the C# senders still re-select by 50 m (ST-3): U13 stayed in the RED file as a declared RED from ST-2b to ST-3d (not a
        GUARD, not skipped). Phase ST-3e0 (the intended change): the request chain is complete (Current ST-3b, Legacy ST-3c, Python ST-3d) and N-12 owns the package duty, so U13 is a GUARD
        again - never deleted, never skipped, no RED twin left behind. (The name of this test is kept: it is the canon's test of U13's lifecycle.)"""
        import red_st0_stationindex_contract as red
        fn = red.Guards.test_GUARD_U13_the_python_saved_index_and_the_csharp_fixed_request_land_together
        meta = fn.st0red
        self.assertEqual((meta["kind"], meta["id"], meta["code"]), ("GUARD", "U13", ""))
        self.assertFalse(getattr(fn, "__unittest_skip__", False))
        self.assertFalse(hasattr(red.Guards, "test_RED_U13_the_python_saved_index_and_the_csharp_fixed_request_land_together"))

    def test_every_n_red_has_a_declared_code_and_the_five_ids_are_all_there(self):
        found = {}
        for cls in (B_TheSync, C_TheCheckpoints, D_TheScoringStart, D2_TheScoringStartInTheManagedMode):
            for name in dir(cls):
                fn = getattr(cls, name)
                meta = getattr(fn, "st2a", None)
                if meta is not None:
                    self.assertTrue(name.startswith("test_RED_"), name)
                    self.assertRegex(meta["code"], r"^[A-Z0-9\-]+$")
                    found.setdefault(meta["id"], set()).add(meta["code"])
        self.assertEqual(set(found), {"N-01", "N-02", "N-03", "N-04", "N-05"})
        for tid, codes in found.items():
            self.assertEqual(len(codes), 1, tid)                                        # ONE declared reason per id
        self.assertEqual(found["N-01"], {"START-WHILE-IDENTITY-UNAVAILABLE"})
        self.assertEqual(found["N-02"], {"SAVE-WHILE-IDENTITY-UNAVAILABLE"})
        self.assertEqual(found["N-03"], {"BINDING-USES-LATEST-STALIST-NOT-COMMITTED-LIST"})
        self.assertEqual(found["N-04"], {"SAVE-DOORTIME-STATION-FROM-POSITION"})
        self.assertEqual(found["N-05"], {"LEGACY-PRE-READY-IS-UNAVAILABLE-NOT-MISMATCH"})

    def test_a_contract_id_is_executed_in_exactly_one_file(self):
        """T09 / T05 (start) / T04 (save) run HERE; the ST-0 file keeps them, unchanged, as MIGRATED evidence (skipped there)."""
        import red_st0_stationindex_contract as red
        for name, tid, code in (("test_RED_T09_the_scoring_start_stores_the_chosen_start_index_in_the_first_checkpoint", "T09", "INITIAL-CHECKPOINT-HAS-NO-STATION-INDEX"),
                                ("test_RED_T05_a_scoring_start_with_an_out_of_range_start_index_is_refused", "T05", "START-INDEX-OUT-OF-RANGE-NOT-REFUSED"),
                                ("test_RED_T04_the_second_same_position_station_gets_its_own_checkpoint", "T04", "SAME-POSITION-PAIR-DROPPED")):
            with self.subTest(name):
                self.assertTrue(hasattr(E_Migrated, name))                                                 # executed here ...
                cls = red.SaveReds
                meta = getattr(getattr(cls, name), "st0red")                                               # ... and kept there, skipped, as the evidence of the RED
                self.assertEqual((meta["kind"], meta["id"], meta["code"], meta["to"]), ("MIGRATED", tid, code, THIS_FILE))
                self.assertTrue(getattr(getattr(cls, name), "__unittest_skip__", False))
                self.assertEqual(MIGRATED_FROM, "tests/red_st0_stationindex_contract.py")

    def test_the_boundaries_of_stage_2a_hold(self):
        """ST-2a does not touch the retry (ST-2b), the first-station rule (ST-2c), the other five 1 m lookups (ST-4) or any C# / wire."""
        logic = read("scoring_logic.py")
        tree = ast.parse(logic)
        retry = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"][0]
        hundreds = [n.value for n in ast.walk(retry) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 100.0]
        self.assertEqual(len(hundreds), 0)                                              # Phase ST-2b: the 100 m search of the retry is gone (the first-station 100 m rule below is ST-2c)
        update = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "update_physics_and_scoring"][0]
        self.assertEqual(len([n for n in ast.walk(update) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 100.0]), 0)      # ... and so is the first-station 100 m rule (Phase ST-2c: was 1)
        create = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_save_data"][0]
        ones = [n.value for n in ast.walk(create) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 1.0]
        self.assertEqual(ones, [])                                                      # the 1 m reverse lookup of the Save is gone ...
        self.assertEqual(len(re.findall(r"abs\(st\[\"location\"\] - [A-Za-z_.]+\) < 1\.0", logic)), 0)               # ... the others are ST-4's (arrival, departure, two lookups of the arrival); Phase SI-R5.2-A re-pinned 5 -> 4 (the guidance, P03, takes bve_tgt_idx); Phase SI-R5.2-B re-pinned 4 -> 1 (P01, P04, P05 take bve_tgt_idx; only the departure, P02, is left); Phase SI-R5.2-C re-pinned 1 -> 0 (P02 takes prev_tgt_idx)
        for forbidden in ("StationList", "bve_arr_idx", "bve_tgt_idx"):                 # (Phase ST-2b: the retry reads station_identity and bve_list_id, the verified scope; it never reads the sender's indexes)
            self.assertNotIn(forbidden, ast.get_source_segment(logic, retry))


# ==============================================================================================================================================
# the optional runner: the N-xx REDs against the product of 69077aa
# ==============================================================================================================================================
def red_check(classes=None, attr="st2a"):
    """python -B tests\\test_stationindex_canon_st2.py --red-check   Every N-xx must fail with ContractViolation(declared code) (RED-VALID) against the product BEFORE ST-2a;
    against the product of ST-2a every one passes (UNEXPECTED-PASS here means 'GREEN')."""
    result_rows = []
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for cls in (classes or (B_TheSync, C_TheCheckpoints, D_TheScoringStart, D2_TheScoringStartInTheManagedMode)):
        for name in sorted(n for n in dir(cls) if n.startswith("test_RED_")):
            suite.addTest(loader.loadTestsFromName(name, cls))

    class Result(unittest.TestResult):
        def _meta(self, test):
            return getattr(getattr(test, test._testMethodName), attr)

        def addSuccess(self, test):
            super().addSuccess(test)
            result_rows.append((test.id().split(".")[-1], self._meta(test)["id"], self._meta(test)["code"], "PASS(GREEN)", ""))

        def addFailure(self, test, err):
            super().addFailure(test, err)
            exc, meta = err[1], self._meta(test)
            if isinstance(exc, ContractViolation) and exc.code == meta["code"]:
                result_rows.append((test.id().split(".")[-1], meta["id"], meta["code"], "RED-VALID", exc.detail[:160]))
            else:
                result_rows.append((test.id().split(".")[-1], meta["id"], meta["code"], "RED-INVALID", "failure: %s" % str(exc)[:160]))

        def addError(self, test, err):
            super().addError(test, err)
            meta = self._meta(test)
            result_rows.append((test.id().split(".")[-1], meta["id"], meta["code"], "RED-INVALID", "error %s: %s" % (err[0].__name__, str(err[1])[:160])))

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            result_rows.append((test.id().split(".")[-1], self._meta(test)["id"], self._meta(test)["code"], "NOT-RUN", reason))

        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            if err is None:
                return
            exc, meta = err[1], self._meta(test)
            status = "RED-VALID" if isinstance(exc, ContractViolation) and exc.code == meta["code"] else "RED-INVALID"
            result_rows.append((test.id().split(".")[-1], meta["id"], meta["code"], status, "subtest: %s" % str(exc)[:160]))

    suite.run(Result())                                                              # (the suite runs the module fixtures - the redirected profile - itself)
    for row in result_rows:
        print("%-12s %-5s %-52s %s" % (row[3], row[1], row[2], row[0]))
        if row[3] not in ("RED-VALID", "PASS(GREEN)"):
            print("             -> %s" % row[4])
    statuses = [r[3] for r in result_rows]
    print("")
    print("RESULT " + ", ".join("%s=%d" % (s, statuses.count(s)) for s in sorted(set(statuses))))
    return 0 if all(s in ("RED-VALID", "PASS(GREEN)") for s in statuses) else 1


if __name__ == "__main__":
    if "--red-check-2b" in sys.argv:
        sys.exit(red_check((H_TheRetry, I_ThePendingRetry, J_TheRetryHasNoSearch, K_TheRefusalIsDiagnosed), "st2b"))
    if "--red-check" in sys.argv:
        sys.exit(red_check())
    unittest.main()
