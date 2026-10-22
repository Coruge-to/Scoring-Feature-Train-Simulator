"""Phase PID-D4JA StationIndex ST-0 (file R1) - the RED SUITE: tests of the TARGET contract (the StationIndex is the identity of a station; no fixed-distance search
decides it) that FAIL against the product of today, each for ONE declared reason.

THIS FILE IS NOT TEST-DISCOVERED ON PURPOSE: its name does not start with 'test', so `unittest discover -s tests` (the official regression entry) does not run it and the known-fail
set of 30 rows is not touched. Run it with its own runner (which also checks WHY every test fails):
        python -B tests\\red_st0_stationindex_contract.py            (exit 0 = every RED fails for its declared reason and every GUARD passes)
        cd tests ; python -B -m unittest red_st0_stationindex_contract   (the raw unittest view: the REDs are plain failures; run from the tests folder)
The tests are written exactly as the contract states them; they are NEVER weakened and NEVER inverted. When the product meets the contract they simply pass, and from
that moment the file is renamed to test_*.py (the ST-1 handoff lists the order).

PHASE ST-1A (owner decisions OJ-4 / OJ-5, which replace the renaming above): this file is NOT renamed while a RED is left in it. The six contracts that ST-1A turns GREEN
(T21, T22 x2, U12 x3) are MIGRATED: their test is executed in tests\\test_stationindex_supply_st1a.py (same contract id and code) and is kept HERE, unchanged, as the
evidence of the ST-0 RED - marked @migrated, so it is skipped and never counted as a RED. A contract id is executed in exactly one of the two files. Every other RED
stays a RED and must keep failing for its declared reason (a pass is UNEXPECTED-PASS).

HOW A RED IS VALID (the runner checks all of it):
  * a RED fails with ContractViolation whose .code is the code declared in @red(...)         -> RED-VALID
  * any other failure or error (fixture, import, attribute, path, another assertion)         -> RED-INVALID
  * a pass                                                                                    -> UNEXPECTED-PASS  (stop: the product already meets it, or the test is too weak)
  * a skip (no PyQt6)                                                                         -> NOT-RUN
  * a @guard test is NOT a RED: it passes today and must keep passing (it guards a constraint on a FUTURE state)                     -> GUARD-OK
Every fixture precondition is a plain assertion BEFORE the contract() call, so a broken fixture is RED-INVALID and never a RED.

INTERFACE ASSUMPTIONS (everything the contract of the audit does not fix to an exact name is collected here, in ONE place, to be changed by ST-1 and nowhere else):
  CHECKPOINT_FIELDS   06-Save-Checkpoint-Retry-Contract.md section 2: station_index, scope = (SCENARIO_ID, list_id, count), station_location, role
  bind_scope()        05 section 9: the Overlay exposes bve_tgt_idx / bve_arr_idx / bve_list_id as public attributes; the scenario world is the existing current_scenario_id
  ADAPTER             12 ST-1 / 05 section 5: the pure STIDX unit is the new module station_index_contract (a "proposal" in the audit); its entry function is NOT fixed by the
                      audit - ADAPTER_VERDICT below is this file's binding point; a different name is a one-line change here
The scores / popups / timing of the physical evaluation are the CHARACTERIZED ones (test_char_stop_door_arrival_st0.py) and are never part of a RED.

ISOLATION: as the JF-1 files this file builds on (sia_rig: offscreen Overlay, recorders for keyboard / Win32 / clock / dialog / log, a stub UDP socket: UDP 54321 / 54322 are never
bound or sent to). USERPROFILE / HOME point to an empty temporary folder for the whole module and the module asserts at its end that nothing was written there.
"""
import ast
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
import zlib

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

import test_char_stop_door_arrival_st0 as C1  # noqa: E402  (the characterization scene: Base.scene / tick, F_Departure.departure_scene)
import test_jf1_jump_completion_and_chain_current as F2  # noqa: E402  (the managed jump rig of JF-1: Base.start, r.complete)
import test_jf1_retry_and_save_data_current as F1  # noqa: E402  (the retry rig of JF-1: Base.retry, snap, sent)

PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CLASS1 = os.path.join(PLUGIN, "TsScoringPlugin", "Class1.cs")
LEGACY_SESSION = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "src", "LegacyTelemetrySession.cs")
SHARED_IDENTITY_CS = os.path.join(PLUGIN, "Handshake", "Telemetry", "Shared", "StationListIdentity.cs")
VECTORS = os.path.join(HERE, "stidx_vectors_st0.json")
T0 = 36000000

# ---- the interface assumptions (see the module docstring) ----------------------------------------------------------------------------------------
CHECKPOINT_FIELDS = ("station_index", "scope", "station_location", "role")
ADAPTER_MODULE = "station_index_contract"
ADAPTER_VERDICT = "verdict"            # verdict(line, nextloc, station_locations, list_hash, elapsed_since_mismatch_ms, grace_ms, prev_arrseq) -> one verdict word of the vector table
ADAPTER_LIST_ID = "list_id"            # list_id(payload_text) -> 8 upper-case hex digits (CRC-32 of the UTF-8 STALIST payload)
MIGRATED_TO = "tests/test_stationindex_supply_st1a.py"       # Phase ST-1A: where the six migrated contracts (T21, T22 x2, U12 x3) are executed now
SCOPE_SID = 7
SCOPE_LIST_ID = "A1B2C3D4"


class ContractViolation(AssertionError):
    """The product does not meet the contract. `code` names the violated clause; the runner compares it with the code declared in @red."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST0-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def red(tid, code, items=(), artifact="", note=""):
    """Declare a RED: id of 11-Red-Test-Plan.md (T..) or, where the audit has no id for the clause, U<n> = item n of the owner's RED list; the ONE failure code; items = the numbers of
    the owner's RED list (items 1-13 of the request of this session; NOT the characterization list 1-20 of the other two files); the JF-1 / audit id it supersedes or relates to."""
    def deco(fn):
        fn.st0red = {"kind": "RED", "id": tid, "code": code, "items": tuple(items), "artifact": artifact, "note": note}
        return fn
    return deco


def guard(tid, items=(), artifact="", note=""):
    """Declare a GUARD: not a RED. It passes today and guards a constraint on a future state."""
    def deco(fn):
        fn.st0red = {"kind": "GUARD", "id": tid, "code": "", "items": tuple(items), "artifact": artifact, "note": note}
        return fn
    return deco


def migrated(tid, code, to, items=(), artifact="", note=""):
    """Phase ST-1A: a RED whose contract is GREEN now and is executed in `to` (tests\\test_stationindex_supply_st1a.py, same id and code). The original test below stays as the
    evidence of the ST-0 RED, unchanged, and is SKIPPED here: it is neither a RED nor a GUARD, and a contract id never runs in both files."""
    def deco(fn):
        fn.st0red = {"kind": "MIGRATED", "id": tid, "code": code, "items": tuple(items), "artifact": artifact, "note": note, "to": to}
        return unittest.skip("MIGRATED at ST-1A: %s / %s is executed in %s" % (tid, code, to))(fn)
    return deco


class RedMixin(object):
    def contract(self, ok, tid, code, detail=""):
        if not ok:
            raise ContractViolation(tid, code, detail)


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-st0-r1-")
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
        raise AssertionError("the ST-0 R1 module wrote into the redirected profile: %r" % (left,))


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def cs_code(path):
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", _TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else " ", text))


def st(name, loc, **kw):
    return C1.sta(name, loc, **kw)


def cp(loc, t, name="X", target_loc=None, score=0, details=None, stop_error=0.0):
    d = {"loc": loc, "time_ms": t, "score": score, "target_loc": loc if target_loc is None else target_loc, "station_name": name, "stop_error": stop_error}
    if details is not None:
        d["score_details"] = dict(details)
    return d


def scope_of(stations, sid=SCOPE_SID, list_id=SCOPE_LIST_ID):
    return (sid, list_id, len(stations))


def bind_scope(o, stations, sid=SCOPE_SID, list_id=SCOPE_LIST_ID):
    """Make the Overlay hold the CURRENT scope the checkpoints below carry (the only place that knows the attribute names; see INTERFACE ASSUMPTIONS)."""
    o.current_scenario_id = sid
    o.bve_list_id = list_id
    o.station_list = stations


def contract_cp(stations, index, loc, t, name, role="arrived_station", sid=SCOPE_SID, list_id=SCOPE_LIST_ID, count=None, details=None, station_location=None):
    """A checkpoint with ALL the fields of the contract (06 section 2) on top of the seven existing ones."""
    d = cp(loc, t, name=name, target_loc=stations[index]["location"] if 0 <= index < len(stations) else loc, details=details)
    d.update(station_index=index, scope=(sid, list_id, len(stations) if count is None else count),
             station_location=stations[index]["location"] if station_location is None and 0 <= index < len(stations) else station_location, role=role)
    d["stop_error"] = d["target_loc"] - loc
    return d


# ==============================================================================================================================================
# the retry (T03 T04 T05 T06 T08 T09)
# ==============================================================================================================================================
class RetryReds(RedMixin, F1.Base):
    def fingerprint(self):
        """Everything execute_retry changes before it sends (the JF-1 R15 - R21 list): a refusal must leave ALL of it as it was."""
        o = self.o
        return (self.snap(), o.is_official_retry, o.is_first_station, o.total_retry_count, o.has_departed, o.is_first_udp, o.rollback_msg, o.rollback_msg_timer,
                o.score, dict(o.score_details), [dict(c) for c in o.save_data], o.menu_state)

    def positive_control(self, stations):
        """A checkpoint whose saved index AND position agree is retried by the CURRENT product too: it proves that the fixture of a REFUSAL test is accepted by a product that has no refusal."""
        o = self.o
        bind_scope(o, stations)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 60000, "B", details=F1.ZERO)]
        cmds = self.retry(1, saves, stations)
        self.assertEqual(cmds, ["JUMP_STA_TIME:1:%d" % (T0 + 60000)])
        self.events.clear()
        o.is_official_jumping = False

    @red("T08", "RETRY-DOES-NOT-USE-THE-SAVED-INDEX", items=(6,), artifact="JF-1 TARGET_A_R04 (the R04 position case can not tell the two apart; this fixture does)",
         note="the retry station is the saved station_index even when the checkpoint position is more than 100 m from every station")
    def test_RED_T08_the_retry_station_is_the_saved_index_not_a_search_from_the_checkpoint_position(self):
        o = self.o
        stations = [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        self.positive_control(stations)
        bind_scope(o, stations)
        saved = contract_cp(stations, 2, 1500.0, T0 + 120000, "C", details=F1.ZERO)                     # 500 m from B and from C: a 100 m search finds nothing
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 60000, "B", details=F1.ZERO), saved]
        cmds = self.retry(2, saves, stations)
        self.contract(cmds == ["JUMP_STA_TIME:2:%d" % (T0 + 120000)], "T08", "RETRY-DOES-NOT-USE-THE-SAVED-INDEX", "sent %r instead of the saved index 2" % (cmds,))

    @red("T03", "RETRY-IGNORES-THE-SAVED-INDEX-AMONG-NEIGHBOURS", items=(2,), artifact="JF-1 CURRENT_DANGER_R06 / X01 and TARGET_A_R04",
         note="two stations within 100 m: the retry goes to the saved index, not to the lowest index of a position search")
    def test_RED_T03_several_stations_within_100_m_keep_the_saved_index(self):
        o = self.o
        stations = [st("A", 0.0), st("B", 1000.0), st("C", 1060.0), st("D", 3000.0, terminal=True)]
        self.positive_control(stations)
        bind_scope(o, stations)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 1000, "B", details=F1.ZERO),
                 contract_cp(stations, 2, 1050.0, T0 + 60000, "C", details=F1.ZERO)]
        cmds = self.retry(2, saves, stations)
        self.contract(cmds == ["JUMP_STA_TIME:2:%d" % (T0 + 60000)], "T03", "RETRY-IGNORES-THE-SAVED-INDEX-AMONG-NEIGHBOURS", "sent %r; the saved index is 2 (C), B is 50 m away" % (cmds,))

    @red("T04", "SAME-POSITION-PAIR-NOT-DISTINGUISHED", items=(3,), artifact="JF-1 CURRENT_DANGER_R07 and TARGET_A_R07",
         note="two stations at the SAME position: the retry to the second one goes to the second one")
    def test_RED_T04_a_retry_to_the_second_of_two_same_position_stations_goes_to_the_second(self):
        o = self.o
        stations = [st("A", 0.0), st("B1", 1000.0), st("B2", 1000.0), st("D", 3000.0, terminal=True)]
        self.positive_control(stations)
        bind_scope(o, stations)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), contract_cp(stations, 1, 1000.0, T0 + 1000, "B1", details=F1.ZERO),
                 contract_cp(stations, 2, 1000.0, T0 + 60000, "B2", details=F1.ZERO)]
        cmds = self.retry(2, saves, stations)
        self.contract(cmds == ["JUMP_STA_TIME:2:%d" % (T0 + 60000)], "T04", "SAME-POSITION-PAIR-NOT-DISTINGUISHED", "sent %r; B1 and B2 are different elements" % (cmds,))

    def refusal_case(self, stations, saved_mutator, tid, code):
        o = self.o
        self.positive_control(stations)
        bind_scope(o, stations)
        saved = contract_cp(stations, 1, 1000.0, T0 + 60000, "B", details=F1.ZERO)
        saved_mutator(saved)
        saves = [contract_cp(stations, 0, 0.0, T0, "A", role="scoring_start"), saved]
        o.save_data = saves                                                                         # (the rig's retry() does this too; done here so that the fingerprint is taken AFTER it)
        o.station_list = stations
        self.assertEqual(len(o.save_data), 2)
        before = self.fingerprint()
        self.S.execute_retry(o, 1, True)
        cmds = self.sent()
        changed = self.fingerprint() != before
        self.contract((cmds == []) and not changed, tid, code, "commands %r, state changed: %r" % (cmds, changed))

    @red("T05", "INVALID-INDEX-NOT-REFUSED", items=(4,), artifact="JF-1 TARGET_A_R08 / R09 (their zero-candidate premise belongs to the rejected provisional supply; this is the Cross-Layer case)",
         note="a saved station_index outside 0..count-1 is refused: no command, no state change, no fall-back to station 0 (the position would still find station B)")
    def test_RED_T05_an_out_of_range_saved_index_is_refused_without_a_command_or_a_state_change(self):
        stations = [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        for bad in (9, 4, -1):
            with self.subTest(bad=bad):
                self.rig.close()
                self.setUp()
                self.refusal_case(stations, lambda c, bad=bad: c.update(station_index=bad), "T05", "INVALID-INDEX-NOT-REFUSED")

    @red("T05", "OLD-FORMAT-CHECKPOINT-NOT-REFUSED", items=(4,), artifact="06 section 2: a checkpoint without station_index is invalid; no compatibility reader",
         note="a checkpoint of the old form (no station_index) is refused, not retried by a position search")
    def test_RED_T05_an_old_form_checkpoint_without_station_index_is_refused(self):
        stations = [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        self.refusal_case(stations, lambda c: c.pop("station_index"), "T05", "OLD-FORMAT-CHECKPOINT-NOT-REFUSED")

    @red("T06", "SCOPE-MISMATCH-NOT-REFUSED", items=(5,), artifact="06 section 4-2 / 05 section 8 (new test, no JF-1 counterpart)",
         note="a checkpoint of ANOTHER scenario generation / station list is refused (fail-closed); the position and the index would both still fit")
    def test_RED_T06_a_checkpoint_of_another_generation_or_list_is_refused(self):
        stations = [st("A", 0.0), st("B", 1000.0), st("C", 2000.0), st("D", 3000.0, terminal=True)]
        variants = (("scenario generation", lambda c: c.update(scope=(SCOPE_SID + 1, SCOPE_LIST_ID, 4))),
                    ("station list id", lambda c: c.update(scope=(SCOPE_SID, "DEADBEEF", 4))),
                    ("station count", lambda c: c.update(scope=(SCOPE_SID, SCOPE_LIST_ID, 5))))
        for label, mutate in variants:
            with self.subTest(label=label):
                self.rig.close()
                self.setUp()
                self.refusal_case(stations, mutate, "T06", "SCOPE-MISMATCH-NOT-REFUSED")

    @red("T09", "INITIAL-CHECKPOINT-RETRY-IGNORES-START-INDEX", items=(7,), artifact="JF-1 CURRENT_DANGER_R10 and TARGET_A_R10",
         note="the retry to the first checkpoint jumps to the station the user chose (setting_start_idx = 2), not to a nearer earlier station")
    def test_RED_T09_the_retry_to_the_initial_checkpoint_uses_the_chosen_start_station(self):
        o = self.o
        o.setting_start_idx = 2
        stations = [st("A", 0.0), st("P", 950.0), st("Q", 1000.0), st("D", 3000.0, terminal=True)]
        bind_scope(o, stations)
        initial = contract_cp(stations, 2, 1000.0, T0, "Q", role="scoring_start")
        self.assertEqual((initial["station_index"], initial["station_location"]), (2, 1000.0))
        cmds = self.retry(0, [initial], stations)
        self.contract(cmds == ["JUMP_STA_TIME:2:%d" % T0] and o.expected_target_loc == 1000.0, "T09", "INITIAL-CHECKPOINT-RETRY-IGNORES-START-INDEX",
                      "sent %r, expected location %r (the position search lands on P, index 1)" % (cmds, o.expected_target_loc))


# ==============================================================================================================================================
# the scoring start and the checkpoint creation (T09 T04)
# ==============================================================================================================================================
class SaveReds(RedMixin, F1.Base):
    def start_through_the_menu(self, start_idx):
        o = self.o
        o.setting_start_idx = start_idx
        o.menu_state = 10
        o.menu_cursor = 1
        o.handle_menu_enter(True)

    @red("T09", "INITIAL-CHECKPOINT-HAS-NO-STATION-INDEX", items=(7,), artifact="JF-1 TARGET_A_S01 (its field names are the JF-2 ones; the Cross-Layer fields are 06 section 2)",
         note="the scoring start stores station_index = setting_start_idx, the scope, the station position and role scoring_start in the first checkpoint")
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

    @red("T05", "START-INDEX-OUT-OF-RANGE-NOT-REFUSED", items=(4,), artifact="JF-1 CURRENT_DANGER_S17 and TARGET_A_S17; 06 section 3-3 (setting_start_idx out of range: the scoring is not started)",
         note="a scoring start whose setting_start_idx is outside the station list is refused: no scoring mode, no official jump, no checkpoint, no command")
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

    @red("T04", "SAME-POSITION-PAIR-DROPPED", items=(3,), artifact="JF-1 CURRENT_DANGER_S04 and TARGET_B_S04 (its attribute bve_next_idx is the JF-3 name; the Cross-Layer name is bve_arr_idx)",
         note="the arrival at the second of two same-position stations creates its own checkpoint with its own station_index")
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
# the completion of a jump (T07)
# ==============================================================================================================================================
class CompletionReds(RedMixin, F2.Base):
    @red("T07", "COMPLETION-INDEX-MISMATCH-ACCEPTED", items=(8,), artifact="JF-1 CURRENT_DANGER_J06 and TARGET_A_J06",
         note="a JUMP_COMPLETE that names another station index than the request (location matching) aborts the scoring and releases the jump state")
    def test_RED_T07_a_completion_with_another_station_index_aborts_the_scoring(self):
        r, o = self.r, self.o
        cmd = self.start()
        self.assertEqual(cmd["text"], "JUMP_STA_TIME:0:%d" % T0)                                    # the request is for station index 0
        self.assertTrue(o.is_scoring_mode and o.is_official_jumping)
        r.complete(cmd["request_id"], location=0.0, time_ms=T0, index=2)                           # the sender says it ended at index 2 (the location still matches)
        aborted = (not o.is_scoring_mode) and o.jump_lock and (not o.is_official_jumping)
        self.contract(aborted, "T07", "COMPLETION-INDEX-MISMATCH-ACCEPTED",
                      "scoring=%r jump_lock=%r official_jump=%r" % (o.is_scoring_mode, o.jump_lock, o.is_official_jumping))


# ==============================================================================================================================================
# the arrival and the departure (item 11, item 9)
# ==============================================================================================================================================
class PhysicsReds(RedMixin, C1.Base):
    @red("U11", "ARRIVAL-IDENTITY-FROM-POSITION", items=(11,), artifact="05 section 9 (bve_tgt_idx) / 02 C-ID-6; counterpart of CHAR ITEM18 an_arrival_at_the_second_same_position_station",
         note="the arrival identity is the sender's target index (bve_tgt_idx = 2, the end station), not the lowest index found by a 1.0 m search from NEXTLOC")
    def test_RED_U11_the_arrival_identity_is_the_target_index_not_a_one_metre_lookup(self):
        pair = [st("A", 0.0), st("B1", 1000.0, is_timing=True), st("B2", 1000.0, is_timing=False), st("D", 3000.0, terminal=True)]
        o = self.scene(d=0.0, stations=pair, end_idx=2)
        o.bve_tgt_idx = 2
        o.bve_current_station_name = "B2"
        self.tick()
        self.open_doors()
        self.assertTrue(o.has_scored_stop_this_station)                                              # the physical arrival happened (door edge, inside the range)
        self.contract(o.is_scoring_finished, "U11", "ARRIVAL-IDENTITY-FROM-POSITION", "the scoring did not end at the end station B2 (index 2): the arrival was attributed to index 1")

    @red("U09", "DEPARTURE-USES-NEW-STATION-MARGIN", items=(9,), artifact="02 F-ST-1 / 04 section 2.3; counterpart of CHAR T19 the_departure_is_judged_with_the_new_targets_margin",
         note="the departure from B is judged with B's own range (2 m): 10 m short of B is out of range, whatever range the next target C (20 m) has")
    def test_RED_U09_the_departure_is_judged_with_the_origin_stations_margin(self):
        F1x = C1.F_Departure
        F1x.departure_scene(self, origin_margin=5.0, new_margin=5.0, d=3.0)                         # control: 3 m short of B with equal 5 m ranges scores the time
        self.assertEqual(self.o.score_details["time"], 300)
        self.rig.close()
        self.setUp()
        o = F1x.departure_scene(self, origin_margin=2.0, new_margin=20.0)
        self.contract(o.score_details["time"] == 0, "U09", "DEPARTURE-USES-NEW-STATION-MARGIN",
                      "time score %r: 10 m short of B is outside B's own 2 m range but inside C's 20 m" % (o.score_details["time"],))
        self.rig.close()
        self.setUp()
        o = F1x.departure_scene(self, origin_margin=20.0, new_margin=2.0)
        self.contract(o.score_details["time"] == 300, "U09", "DEPARTURE-USES-NEW-STATION-MARGIN",
                      "time score %r: 10 m short of B is inside B's own 20 m range but outside C's 2 m" % (o.score_details["time"],))


# ==============================================================================================================================================
# static REDs (no Qt)
# ==============================================================================================================================================
class StaticReds(RedMixin, unittest.TestCase):
    @red("T23", "EXECUTE-RETRY-HAS-100M-SEARCH", items=(6,), artifact="11 T23 (AP-9): no 100.0 in execute_retry",
         note="execute_retry contains no 100.0 position search")
    def test_RED_T23_execute_retry_has_no_100_m_position_search(self):
        tree = ast.parse(read_text(os.path.join(ROOT, "scoring_logic.py")))
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"]
        self.assertEqual(len(fn), 1)                                                                  # the function exists exactly once (a path problem is RED-INVALID)
        hundreds = [n.value for n in ast.walk(fn[0]) if isinstance(n, ast.Constant) and isinstance(n.value, float) and n.value == 100.0]
        self.contract(not hundreds, "T23", "EXECUTE-RETRY-HAS-100M-SEARCH", "execute_retry still contains %d float 100.0" % len(hundreds))

    @red("U01", "CURRENT-STA-JUMP-DOES-NOT-FIX-REQUESTED-INDEX", items=(1,), artifact="JF-1 TARGET_B_C02 / C03 / C17 (their regular expression)",
         note="after a requested jump the Current sender's target is the requested index, so no 50 m position search can choose another station")
    def test_RED_U01_the_current_sender_fixes_the_requested_index(self):
        c1 = cs_code(CLASS1)
        self.assertIn('if (msg.StartsWith("JUMP_STA_TIME:"))', c1)                                  # the STA branch is there (a moved source is RED-INVALID)
        self.assertIn("if (stationList[i].Location >= location - 50.0)", c1)                          # and the 50 m search of today is still where it was
        self.contract(re.search(r"targetStationIndex = (sIdx|requestedStationIndex|pendingJumpStationIndex)", c1) is not None, "U01",
                      "CURRENT-STA-JUMP-DOES-NOT-FIX-REQUESTED-INDEX", "targetStationIndex is only ever assigned by the 50 m position search or advanced, never from the requested index")

    @red("U10", "CURRENT-MARGIN-FALLBACK-5.0-PRESENT", items=(10,), artifact="OD-NEW-7 / 05 M-4 / 04 section 2.4",
         note="a range that can not be read does not become 5.0 / 5.0 in the Current sender (fail-closed like Legacy)")
    def test_RED_U10_the_current_sender_has_no_5_0_fallback_for_an_unreadable_range(self):
        c1 = cs_code(CLASS1)
        self.assertIn("sd.MarginMin = Math.Abs((double)st.MarginMin);", c1)                           # the read is where it was
        self.assertIn("sd.MarginMax = (double)st.MarginMax;", c1)
        fallbacks = re.findall(r"catch \{ sd\.Margin(?:Min|Max) = 5\.0; \}", c1)
        self.contract(not fallbacks, "U10", "CURRENT-MARGIN-FALLBACK-5.0-PRESENT", "%d catch-and-use-5.0 fallbacks remain" % len(fallbacks))

    @migrated("U12", "CURRENT-EMITS-NO-STIDX", MIGRATED_TO, items=(12,), artifact="05 section 5 (STIDX:1:... next to NEXTLOC)",
         note="the Current sender's telemetry line carries the versioned STIDX key")
    def test_RED_U12_the_current_sender_emits_stidx(self):
        c1 = cs_code(CLASS1)
        self.assertIn("NEXTLOC:{nextStationLoc}", c1)
        self.contract("STIDX:1:" in c1, "U12", "CURRENT-EMITS-NO-STIDX", "no STIDX:1: in the telemetry string of Class1.cs")

    @migrated("U12", "LEGACY-EMITS-NO-STIDX", MIGRATED_TO, items=(12,), artifact="05 section 5 (STIDX inside the Legacy station group, all-or-nothing)",
         note="the Legacy sender's station group carries the STIDX key")
    def test_RED_U12_the_legacy_sender_emits_stidx(self):
        ls = cs_code(LEGACY_SESSION)
        self.assertIn("lb.Group(TelemetryContract.TokStation,", ls)                                  # the station group and its NEXTLOC are where they were
        self.assertIn('"NEXTLOC", TelemetryContract.D(sv.NextLoc)', ls)
        self.contract('"STIDX"' in ls, "U12", "LEGACY-EMITS-NO-STIDX", 'no "STIDX" key in the station group of LegacyTelemetrySession.cs')

    @migrated("U12", "PYTHON-TOKEN-KEYS-LACK-STIDX", MIGRATED_TO, items=(12,), artifact="05 section 5: TOKEN_KEYS['station'] gets STIDX",
         note="the Python telemetry vocabulary knows STIDX as a key of the station token")
    def test_RED_U12_the_python_vocabulary_knows_stidx(self):
        import telemetry_contract
        self.assertIn("NEXTLOC", telemetry_contract.TOKEN_KEYS["station"])
        self.contract("STIDX" in telemetry_contract.TOKEN_KEYS["station"], "U12", "PYTHON-TOKEN-KEYS-LACK-STIDX", "TOKEN_KEYS['station'] = %r" % (telemetry_contract.TOKEN_KEYS["station"],))

    # -- T21 / T22 -------------------------------------------------------------------------------------------------------------------------------
    @migrated("T21", "STATION-INDEX-CONTRACT-ABSENT", MIGRATED_TO, items=(),
         artifact="11 T21 / 12 ST-1 (station_index_contract.py is the audit's proposal): parse, version, range, NEXTLOC invariant, hash grace",
         note="the pure STIDX unit exists and returns the verdict words of the vector table (the failure while the module is absent is the declared RED reason, not an import error)")
    def test_RED_T21_the_stidx_unit_judges_every_vector(self):
        with open(VECTORS, encoding="utf-8") as f:
            vec = json.load(f)
        self.assertEqual(len(vec["stidx"]), 17)                                                       # the vector table is the one of this phase
        present = importlib.util.find_spec(ADAPTER_MODULE) is not None
        self.contract(present, "T21", "STATION-INDEX-CONTRACT-ABSENT", "no module %s (the pure STIDX parser / lifecycle unit of ST-1)" % ADAPTER_MODULE)
        mod = importlib.import_module(ADAPTER_MODULE)
        verdict = getattr(mod, ADAPTER_VERDICT)
        wrong = []
        for v in vec["stidx"]:
            got = verdict(v["line"], v["nextloc"], v["station_locations"], v["list_hash"], v["elapsed_since_mismatch_ms"], v["grace_ms"], v["prev_arrseq"])
            if got != v["verdict"]:
                wrong.append((v["id"], got, v["verdict"]))
        self.contract(not wrong, "T21", "STATION-INDEX-CONTRACT-ABSENT", "vectors judged differently: %r" % (wrong,))

    @migrated("T22", "STATION-LIST-IDENTITY-CS-ABSENT", MIGRATED_TO, items=(), artifact="11 T22 / 12 ST-1: Telemetry/Shared/StationListIdentity.cs (the C# half of the shared CRC-32 vectors)",
         note="the shared C# StationListIdentity exists (its vector execution is an ST-1 PowerShell test)")
    def test_RED_T22_the_shared_csharp_station_list_identity_exists(self):
        self.assertTrue(os.path.isdir(os.path.join(PLUGIN, "Handshake", "Telemetry")))                # the folder tree is there (a moved tree is RED-INVALID)
        self.contract(os.path.isfile(SHARED_IDENTITY_CS), "T22", "STATION-LIST-IDENTITY-CS-ABSENT", "no %s" % os.path.relpath(SHARED_IDENTITY_CS, ROOT))

    @migrated("T22", "STATION-LIST-ID-FUNCTION-ABSENT", MIGRATED_TO, items=(),
         artifact="11 T22 / 05 section 2: list_id = CRC-32 of the UTF-8 STALIST payload (the Python half of the shared vectors)",
         note="the Python unit computes list_id for every shared CRC-32 vector")
    def test_RED_T22_the_python_list_id_matches_the_shared_vectors(self):
        with open(VECTORS, encoding="utf-8") as f:
            vec = json.load(f)
        for h in vec["crc32"]:                                                                        # the vectors themselves agree with the standard library
            self.assertEqual("%08X" % (zlib.crc32(h["payload"].encode("utf-8")) & 0xFFFFFFFF), h["hex"], h["id"])
        present = importlib.util.find_spec(ADAPTER_MODULE) is not None
        self.contract(present, "T22", "STATION-LIST-ID-FUNCTION-ABSENT", "no module %s (list_id lives there)" % ADAPTER_MODULE)
        mod = importlib.import_module(ADAPTER_MODULE)
        fn = getattr(mod, ADAPTER_LIST_ID)
        wrong = [(h["id"], fn(h["payload"])) for h in vec["crc32"] if fn(h["payload"]) != h["hex"]]
        self.contract(not wrong, "T22", "STATION-LIST-ID-FUNCTION-ABSENT", "list_id differs for %r" % (wrong,))


# ==============================================================================================================================================
# guards (not REDs)
# ==============================================================================================================================================
class Guards(unittest.TestCase):
    @guard("U13", items=(13,), artifact="OD-NEW-3 / 12 section 0: ST-2a is never accepted alone",
           note="Python must not use the saved station_index for the retry while the Current sender still re-selects by 50 m: the two land together or not at all")
    def test_GUARD_U13_the_python_saved_index_and_the_csharp_fixed_request_land_together(self):
        tree = ast.parse(read_text(os.path.join(ROOT, "scoring_logic.py")))
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"]
        self.assertEqual(len(fn), 1)
        python_uses_saved_index = any(isinstance(n, ast.Constant) and n.value == "station_index" for n in ast.walk(fn[0]))
        c1 = cs_code(CLASS1)
        csharp_fixes_request = re.search(r"targetStationIndex = (sIdx|requestedStationIndex|pendingJumpStationIndex)", c1) is not None
        self.assertFalse(python_uses_saved_index and not csharp_fixes_request,
                         "ST-2a alone: Python retries by the saved station_index but Class1.cs still re-selects the target by position (ST-3 missing) - Legacy evidence must be added at ST-3")

    @guard("T22", items=(), artifact="the vector table is part of the RED validity",
           note="the shared vector table is well formed: unique ids, CRC-32 values equal to the standard library, the verdict words of the audit only")
    def test_GUARD_the_vector_table_is_well_formed(self):
        with open(VECTORS, encoding="utf-8") as f:
            vec = json.load(f)
        ids = [h["id"] for h in vec["crc32"]] + [v["id"] for v in vec["stidx"]]
        self.assertEqual(len(ids), len(set(ids)))
        for h in vec["crc32"]:
            self.assertEqual("%08X" % (zlib.crc32(h["payload"].encode("utf-8")) & 0xFFFFFFFF), h["hex"], h["id"])
        words = {"stidx-ok", "stidx-missing", "stidx-version", "stidx-range", "stidx-nextloc", "stidx-list-mismatch", "stidx-arrseq-gap", "NOT-READY"}
        self.assertEqual({v["verdict"] for v in vec["stidx"]} - words, set())
        self.assertEqual(vec["crc32"][0]["payload"], "")
        self.assertEqual(vec["crc32"][0]["hex"], "00000000")                                          # count == 0  ->  00000000 (05 section 2)

    @guard("U11", items=(11,), artifact="the RED scenes are the characterized ones",
           note="every RED of this file has the metadata the runner needs (kind, id, ONE code)")
    def test_GUARD_every_red_declares_one_code(self):
        seen = 0
        for cls in (RetryReds, SaveReds, CompletionReds, PhysicsReds, StaticReds, Guards):
            for name in sorted(n for n in dir(cls) if n.startswith("test_")):
                meta = getattr(getattr(cls, name), "st0red", None)
                if meta is None:
                    continue
                self.assertIn(meta["kind"], ("RED", "GUARD", "MIGRATED"), name)
                if meta["kind"] in ("RED", "MIGRATED"):
                    self.assertRegex(meta["code"], r"^[A-Z0-9.\-]+$", name)
                    self.assertTrue(name.startswith("test_RED_"), name)
                else:
                    self.assertTrue(name.startswith("test_GUARD_"), name)
                if meta["kind"] == "MIGRATED":
                    self.assertTrue(meta["to"].startswith("tests/test_") and meta["to"].endswith(".py"), name)       # Phase ST-1A: it runs in a discovered test file
                self.assertGreaterEqual(len(meta["note"]), 20, name)
                seen += 1
        self.assertGreaterEqual(seen, 18)


# ==============================================================================================================================================
# the runner: a RED is valid only when it fails for its declared reason
# ==============================================================================================================================================
class _RedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = {}

    @staticmethod
    def _meta(test):
        return getattr(getattr(test, test._testMethodName, None), "st0red", None)

    def _row(self, test, status, detail=""):
        meta = self._meta(test) or {"kind": "?", "id": "?", "code": ""}
        self.rows[test.id()] = (meta["kind"], meta["id"], meta["code"], status, detail)

    def addSuccess(self, test):
        super().addSuccess(test)
        meta = self._meta(test)
        if meta is None:
            return
        self._row(test, "GUARD-OK" if meta["kind"] == "GUARD" else "UNEXPECTED-PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        meta = self._meta(test)
        if meta is None:
            return
        exc = err[1]
        if meta["kind"] == "GUARD":
            self._row(test, "GUARD-FAILED", str(exc)[:200])
        elif isinstance(exc, ContractViolation) and exc.code == meta["code"]:
            self._row(test, "RED-VALID", exc.detail[:200])
        elif isinstance(exc, ContractViolation):
            self._row(test, "RED-INVALID", "wrong code %s (declared %s)" % (exc.code, meta["code"]))
        else:
            self._row(test, "RED-INVALID", "other assertion: %s" % str(exc)[:200])

    def addError(self, test, err):
        super().addError(test, err)
        meta = self._meta(test)
        if meta is not None:
            self._row(test, "RED-INVALID" if meta["kind"] == "RED" else "GUARD-FAILED", "error %s: %s" % (err[0].__name__, str(err[1])[:200]))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        meta = self._meta(test)
        if meta is not None:
            self._row(test, "MIGRATED" if meta["kind"] == "MIGRATED" else "NOT-RUN", "skip: %s" % reason[:120])

    def addSubTest(self, test, subtest, err):
        """A RED with sub-cases is valid only when EVERY sub-case fails for the declared reason: one passing sub-case makes the whole test UNEXPECTED-PASS."""
        super().addSubTest(test, subtest, err)
        meta = self._meta(test)
        if meta is None:
            return
        key = test.id()
        previous = self.rows.get(key)
        if err is None:
            self.rows[key] = (meta["kind"], meta["id"], meta["code"], "UNEXPECTED-PASS", "a sub-case passed: %s" % (subtest._subDescription() if hasattr(subtest, "_subDescription") else subtest))
            return
        exc = err[1]
        if previous is not None and previous[3] != "RED-VALID":
            return                                                                                  # an earlier sub-case already made the row invalid / unexpected: keep that
        if isinstance(exc, ContractViolation) and exc.code == meta["code"]:
            self.rows[key] = (meta["kind"], meta["id"], meta["code"], "RED-VALID", exc.detail[:200])
        else:
            self.rows[key] = (meta["kind"], meta["id"], meta["code"], "RED-INVALID", "subtest: %s" % str(exc)[:200])


def run():
    """Run this module's tests and classify them. Called through the importable module (not through __main__) so that ContractViolation is one class."""
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = _RedResult()
    suite.run(result)
    names = sorted(result.rows)
    counts = {}
    for n in names:
        kind, tid, code, status, detail = result.rows[n]
        counts[status] = counts.get(status, 0) + 1
        print("%-16s %-4s %-5s %-52s %s" % (status, kind, tid, code, n.split(".")[-1]))
        if status not in ("RED-VALID", "GUARD-OK", "MIGRATED"):
            print("                 -> %s" % detail)
    print("")
    print("RESULT %s" % ", ".join("%s=%d" % (k, counts[k]) for k in sorted(counts)))
    other = [(t.id(), str(e)[:160]) for t, e in result.errors + result.failures if t.id().split(" (")[0] not in result.rows]       # (a sub-case id is 'test.id (param=...)')
    for n, e in other:
        print("UNCLASSIFIED %s: %s" % (n, e))
    bad = sum(v for k, v in counts.items() if k not in ("RED-VALID", "GUARD-OK", "MIGRATED")) + len(other)
    print("RED SUITE: %s" % ("ALL RED FAIL FOR THEIR DECLARED REASON, ALL GUARDS PASS" if bad == 0 else "NOT VALID (%d row(s) need a decision)" % bad))
    return 0 if bad == 0 else 1


def main():
    return importlib.import_module("red_st0_stationindex_contract").run()


if __name__ == "__main__":
    sys.exit(main())
