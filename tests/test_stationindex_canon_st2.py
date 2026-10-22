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
        R.bind_identity(o)
        o.is_scoring_mode, o.is_first_station, o.setting_end_idx = True, True, 1
        o.save_data = [F1.cp(0.0, T0)]
        o.prev_next_loc = o.bve_next_loc = 1000.0
        o.bve_location = 1000.0
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
        self.assertEqual(self.sent(), ["JUMP_STA_TIME:2:%d" % T0])
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
        self.assertEqual(self.sent(), ["JUMP_STA_TIME:2:%d" % T0])                                 # the fixture reached the start of the scoring
        first = o.save_data[0]
        self.assertEqual((first["loc"], first["station_name"]), (2000.0, "C"))
        missing = [k for k in CHECKPOINT_FIELDS if k not in first]
        ok = (not missing) and first["station_index"] == 2 and first["role"] == "scoring_start" and first["station_location"] == 2000.0
        self.contract(ok, "T09", "INITIAL-CHECKPOINT-HAS-NO-STATION-INDEX", "missing fields %r" % (missing,))
        self.assertEqual(first["scope"], (SID, LID, 4))

    def test_RED_T05_a_scoring_start_with_an_out_of_range_start_index_is_refused(self):
        bind_scope(self.o, self.o.station_list)
        self.start_through_the_menu(1)                                                              # the control: a valid start index starts the scoring and sends its jump
        self.assertEqual(self.sent(), ["JUMP_STA_TIME:1:%d" % T0])
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
        self.assertEqual(self.sent(), ["JUMP_STA_TIME:0:%d" % T0])
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

    def test_the_history_is_one_ordered_list_owned_by_the_overlay_and_the_retry_cuts_it(self):
        """The structure the later phases build on (ST-2b / ST-3 change WHEN the cut happens, not the structure): save_data is a plain list of dicts, the retry keeps
        [0..index]. ST-2a does not touch the retry; this only records that the structure can express 'A B C D -> A B'."""
        o = self.o
        stations = abcde()
        history = []
        for idx, role in ((0, "scoring_start"), (1, "arrived_station"), (2, "arrived_station"), (3, "arrived_station")):
            history.append(F1.with_identity(F1.cp(stations[idx]["location"], T0 + idx, name=stations[idx]["name"]), idx, stations[idx]["location"], count=5, role=role))
        self.assertIs(type(history), list)
        self.retry(1, history, stations=stations)
        self.assertEqual([c["station_name"] for c in o.save_data], ["A", "B"])


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
        self.bind(1, 2)
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
        self.bind(1, 2)
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
        o.bve_next_loc = 2000.0                                                             # the door has closed: the sender shows the next station
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


class Z_Meta(unittest.TestCase):
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
        self.assertEqual(len(hundreds), 1)                                              # the 100 m search of the retry is still there: ST-2b removes it
        update = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "update_physics_and_scoring"][0]
        self.assertEqual(len([n for n in ast.walk(update) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 100.0]), 1)      # ... and so is the first-station 100 m rule (ST-2c)
        create = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_save_data"][0]
        ones = [n.value for n in ast.walk(create) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 1.0]
        self.assertEqual(ones, [])                                                      # the 1 m reverse lookup of the Save is gone ...
        self.assertEqual(len(re.findall(r"abs\(st\[\"location\"\] - [A-Za-z_.]+\) < 1\.0", logic)), 5)                 # ... the five others are ST-4's (arrival, departure, guidance, two lookups of the arrival)
        for forbidden in ("station_identity", "StationList", "bve_arr_idx", "bve_list_id"):
            self.assertNotIn(forbidden, ast.get_source_segment(logic, retry))


# ==============================================================================================================================================
# the optional runner: the N-xx REDs against the product of 69077aa
# ==============================================================================================================================================
def red_check():
    """python -B tests\\test_stationindex_canon_st2.py --red-check   Every N-xx must fail with ContractViolation(declared code) (RED-VALID) against the product BEFORE ST-2a;
    against the product of ST-2a every one passes (UNEXPECTED-PASS here means 'GREEN')."""
    result_rows = []
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for cls in (B_TheSync, C_TheCheckpoints, D_TheScoringStart, D2_TheScoringStartInTheManagedMode):
        for name in sorted(n for n in dir(cls) if n.startswith("test_RED_")):
            suite.addTest(loader.loadTestsFromName(name, cls))

    class Result(unittest.TestResult):
        def _meta(self, test):
            return getattr(getattr(test, test._testMethodName), "st2a")

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
    if "--red-check" in sys.argv:
        sys.exit(red_check())
    unittest.main()
