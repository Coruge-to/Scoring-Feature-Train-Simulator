"""Phase PID-D4JA StationIndex ST-0 (file C2) - SOURCE-SHAPE PINS of where the BVE-internal door state, the author-defined stop range and the stop kind come from,
and of the thresholds around them, in the Current plugin (Class1.cs), the Legacy telemetry (LegacyTelemetryExtension.cs, LegacyTelemetrySession.cs,
LegacyStationTimeline.cs) and the Python scoring (scoring_logic.py, main.py, telemetry_contract.py).

A pin reads text and checks the SHAPE of the statements; it is NOT a run of the behaviour (Class1.cs needs the BveEX host and can not run offline). The Legacy
state machine is RUN by Test-StationStopCharST0.ps1; the Python behaviour by test_char_stop_door_arrival_st0.py.
Every pin carries one of the five meanings of test_char_stop_door_arrival_st0.py (REQUIREMENT-BACKED / CURRENT-BEHAVIOR-ONLY / KNOWN-DEFECT-BEHAVIOR /
CROSS-LAYER-DIFFERENCE / FUTURE-REPLACEMENT-TARGET), the id of 11-Red-Test-Plan.md of the contract-gap audit and the number of the owner's CHARACTERIZATION list of this session ("item n", items 1-20).
NOTHING here approves a current behaviour as a requirement: the thresholds (0.1 km/h, 300 ms, 100 m, 50 m, 5.0) are pinned as they are.

ISOLATION: files are only read. No socket, no process, no write. This file needs no PyQt6, so it also runs under python -I.
"""
import ast
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CLASS1 = os.path.join(PLUGIN, "TsScoringPlugin", "Class1.cs")
LEGACY_SRC = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "src")
LEGACY_EXT = os.path.join(LEGACY_SRC, "LegacyTelemetryExtension.cs")
LEGACY_SESSION = os.path.join(LEGACY_SRC, "LegacyTelemetrySession.cs")
LEGACY_TIMELINE = os.path.join(LEGACY_SRC, "LegacyStationTimeline.cs")

LABELS = ("REQUIREMENT-BACKED", "CURRENT-BEHAVIOR-ONLY", "KNOWN-DEFECT-BEHAVIOR", "CROSS-LAYER-DIFFERENCE", "FUTURE-REPLACEMENT-TARGET")
PLAN_IDS = {"T13", "T14", "T15", "T16", "T17", "T18", "T19", "T20"}


def st0(tid, label, items=(), note=""):
    assert label in LABELS, label

    def deco(fn):
        fn.st0 = {"id": tid, "label": label, "items": tuple(items), "note": note}
        return fn
    return deco


_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


def cs_code(path):
    """C# without comments, whitespace squashed to single blanks (string literals kept)."""
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", _TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else " ", text))


def py_text(name):
    return read_text(os.path.join(ROOT, name))


def py_function(name, func):
    tree = ast.parse(py_text(name))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return node
    raise AssertionError("%s has no function %s" % (name, func))


def floats_in(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, float)]


class ShortCase(unittest.TestCase):
    """unittest's assertIn / assertRegex print the whole container on a failure; these texts are whole source files, so the messages here name only the pin."""
    longMessage = False

    def assertIn(self, member, container, msg=None):
        if member not in container:
            raise self.failureException(msg or "pin not found: %r" % (member[:200],))

    def assertNotIn(self, member, container, msg=None):
        if member in container:
            raise self.failureException(msg or "pin found but must be absent: %r" % (member[:200],))

    def assertRegex(self, text, expected_regex, msg=None):
        if not re.search(expected_regex, text):
            raise self.failureException(msg or "pattern not found: %r" % (str(getattr(expected_regex, "pattern", expected_regex))[:200],))

    def assertNotRegex(self, text, unexpected_regex, msg=None):
        m = re.search(unexpected_regex, text)
        if m:
            raise self.failureException(msg or "pattern found but must be absent: %r at %r" % (str(getattr(unexpected_regex, "pattern", unexpected_regex))[:120], m.group(0)[:80]))


class Pins(ShortCase):
    @classmethod
    def setUpClass(cls):
        cls.cur = cs_code(CLASS1)
        cls.lext = cs_code(LEGACY_EXT)
        cls.lses = cs_code(LEGACY_SESSION)
        cls.ltl = cs_code(LEGACY_TIMELINE)

    # -- the BVE-internal door state (items 1, 2, 3; T16) ----------------------------------------------------------------------------------------
    @st0("T16", "REQUIREMENT-BACKED", items=(1,), note="Current takes the door state from Vehicle.Doors.AreAllClosed, once, and sends it as DOOR:0 (all closed) / 1")
    def test_PIN_T16_current_reads_vehicle_doors_AreAllClosed_and_sends_it_as_DOOR(self):
        self.assertEqual(self.cur.count("vehicle.Doors.AreAllClosed"), 1)
        self.assertIn("try { if (vehicle != null) areDoorsClosed = vehicle.Doors.AreAllClosed; } catch { }", self.cur)
        self.assertIn("DOOR:{(areDoorsClosed ? 0 : 1)}", self.cur)
        self.assertEqual(len(re.findall(r"\bareDoorsClosed = ", self.cur)), 2)                    # the default true and the one API read

    @st0("T16", "REQUIREMENT-BACKED", items=(2,), note="Legacy takes the door state from current.Vehicle.Doors.AreAllClosed, once, and sends it as DOOR:0 / 1")
    def test_PIN_T16_legacy_reads_vehicle_doors_AreAllClosed_and_sends_it_as_DOOR(self):
        self.assertEqual(self.lext.count("Vehicle.Doors.AreAllClosed"), 1)
        self.assertIn("try { allClosed = current.Vehicle.Doors.AreAllClosed; return true; } catch { return false; }", self.lext)
        self.assertIn('lb.Group(TelemetryContract.TokDoor, "DOOR", doorsClosed ? "0" : "1");', self.lses)

    @st0("T16", "CURRENT-BEHAVIOR-ONLY", items=(1, 2), note="only the all-doors-closed bit is used: no left/right (GetSide), no per-car (CarDoors), no AreAllClosingOrClosed in any product source")
    def test_PIN_T16_no_other_door_api_is_used_by_either_sender(self):
        for name, text in (("Class1.cs", self.cur), ("LegacyTelemetryExtension.cs", self.lext), ("LegacyTelemetrySession.cs", self.lses), ("LegacyStationTimeline.cs", self.ltl)):
            self.assertEqual(sorted(set(re.findall(r"\bDoors\.(\w+)", text))), sorted(set(re.findall(r"\bDoors\.(AreAllClosed)\b", text))), name)
            for api in ("GetSide", "CarDoors", "AreAllClosingOrClosed", "IsOpen"):
                self.assertNotIn(api, text, name + " " + api)

    @st0("T16", "CROSS-LAYER-DIFFERENCE", items=(1, 2, 12), note="F-DR-3: when the door state can not be read Current keeps DOOR:0 and still sends the station group (fail-open); Legacy sends neither group (fail-closed)")
    def test_PIN_T16_a_lost_door_state_is_fail_open_in_current_and_fail_closed_in_legacy(self):
        self.assertIn("bool areDoorsClosed = true;", self.cur)
        self.assertIn("haveDoors = api.TryDoorsClosed(out doorsClosed);", self.lses)
        self.assertIn("bool haveStations = haveDoors && api.TryStationCount(out stationCount)", self.lses)
        self.assertIn("if (haveDoors) { lb.Group(TelemetryContract.TokDoor,", self.lses)

    @st0("T16", "REQUIREMENT-BACKED", items=(3,), note="Python reads DOOR / DOORDIR into bve_door / bve_doordir and keeps the previous value in prev_door / prev_doordir")
    def test_PIN_T16_python_reads_the_door_tokens_into_bve_door_and_bve_doordir(self):
        main = py_text("main.py")
        self.assertIn('elif part.startswith("DOOR:"): self.bve_door = int(part.split(\':\')[1])', main)
        self.assertIn('elif part.startswith("DOORDIR:"): self.bve_doordir = int(part.split(\':\')[1])', main)
        self.assertIn("self.prev_door = getattr(self, 'bve_door', 0)", py_text("scoring_logic.py"))

    # -- the author-defined stop range (items 10, 11, 12, 13; T17) -----------------------------------------------------------------------------
    @st0("T17", "REQUIREMENT-BACKED", items=(10,), note="Current reads Station.MarginMin (absolute value) and Station.MarginMax; Legacy reads the same two members; MinStopPosition / MaxStopPosition are used by nobody")
    def test_PIN_T17_both_senders_take_the_range_from_Station_MarginMin_and_MarginMax(self):
        self.assertIn("try { sd.MarginMin = Math.Abs((double)st.MarginMin); }", self.cur)
        self.assertIn("try { sd.MarginMax = (double)st.MarginMax; }", self.cur)
        self.assertIn("r.MarginMin = st.MarginMin;", self.lext)
        self.assertIn("r.MarginMax = st.MarginMax;", self.lext)
        self.assertIn("sd.MarginMin = Math.Abs(r.MarginMin);", self.ltl)
        self.assertIn("sd.MarginMax = r.MarginMax;", self.ltl)
        for name, text in (("Class1.cs", self.cur), ("LegacyTelemetryExtension.cs", self.lext), ("LegacyStationTimeline.cs", self.ltl)):
            self.assertNotIn("MinStopPosition", text, name)
            self.assertNotIn("MaxStopPosition", text, name)

    @st0("T17", "REQUIREMENT-BACKED", items=(11,), note="the range of the TARGET station only is sent: MARGINB = MarginMin, MARGINF = MarginMax; no other station's range is in any message")
    def test_PIN_T17_the_target_stations_range_is_sent_as_MARGINB_and_MARGINF(self):
        self.assertEqual(self.cur.count("marginBack = targetSt.MarginMin;"), 2)                     # the normal path and the transition-tick re-derivation
        self.assertEqual(self.cur.count("marginFront = targetSt.MarginMax;"), 2)
        self.assertIn("MARGINB:{marginBack},MARGINF:{marginFront}", self.cur)
        self.assertEqual(self.ltl.count("marginBack = st.MarginMin;"), 2)
        self.assertEqual(self.ltl.count("marginFront = st.MarginMax;"), 2)
        self.assertIn('"MARGINB", TelemetryContract.D(sv.MarginBack), "MARGINF", TelemetryContract.D(sv.MarginFront),', self.lses)

    @st0("T17", "REQUIREMENT-BACKED", items=(11,), note="F-ST-2: the STALIST of both senders carries no range, no door side and no stop kind of the non-target stations (nine fields: name, timing, location, times, stoppage, pass, terminal)")
    def test_PIN_T17_the_stalist_carries_no_range_for_the_other_stations(self):
        added = re.search(r"staInfoList\.Add\((.*?)\); \}", self.cur)
        self.assertIsNotNone(added)
        self.assertNotIn("Margin", added.group(1))
        self.assertNotIn("DoorDir", added.group(1))
        body = self.ltl[self.ltl.index("internal string ComposeStaList()"):]
        body = body[:body.index("return sb.ToString();")]
        self.assertNotIn("Margin", body)
        self.assertNotIn("DoorDir", body)

    @st0("T17", "KNOWN-DEFECT-BEHAVIOR", items=(12,), note="Phase U10 (inverted - it was: a range that can not be read becomes 5.0 / 5.0 and the station is still announced, fail-open): it rejects the whole list like Legacy; no stand-in range is left")
    def test_PIN_T17_current_rejects_the_whole_list_when_the_range_can_not_be_read(self):
        self.assertNotIn("catch { sd.MarginMin = 5.0; }", self.cur)
        self.assertNotIn("catch { sd.MarginMax = 5.0; }", self.cur)
        self.assertEqual(len(re.findall(r"\bsd\.Margin(?:Min|Max)\s*=\s*-?\d", self.cur)), 0)
        self.assertIn("string rangeFailStage = ReadStationRange((object)st, sd, out rangeFailType); if (rangeFailStage != null) { RejectStationList(i, rangeFailStage, rangeFailType);", self.cur)
        self.assertIn("double marginBack = 5.0; double marginFront = 5.0;", self.cur)                 # the initial value of the per-Tick locals (no target station) is a different requirement and stays

    @st0("T17", "CROSS-LAYER-DIFFERENCE", items=(13,), note="Legacy: a station whose range is not finite makes TryStations fail, so no station group is sent at all (fail-closed)")
    def test_PIN_T17_legacy_refuses_the_whole_list_when_a_range_is_not_finite(self):
        self.assertIn("if (!TelemetryContract.Finite(r.Location) || !TelemetryContract.Finite(r.MarginMin) || !TelemetryContract.Finite(r.MarginMax)) { return false; }", self.lext)
        self.assertIn("(api.TryStations(out stations) && stations != null && stations.Count == stationCount)", self.lses)
        self.assertIn("catch { staList = null; }", self.lses)

    @st0("T17", "CURRENT-BEHAVIOR-ONLY", items=(10, 14), note="the range test of the sender state machine: distToStop in [-MarginMax, MarginMin], both bounds inclusive, in Current and in Legacy")
    def test_PIN_T17_the_sender_range_test_is_inclusive_on_both_sides(self):
        self.assertIn("bool isInMargin = (distToStop >= -marginFront && distToStop <= marginBack);", self.cur)
        self.assertIn("bool isInMargin = distToStop >= -marginFront && distToStop <= marginBack;", self.ltl)

    @st0("T17", "REQUIREMENT-BACKED", items=(10,), note="the Python range test is the same inequality on d = NEXTLOC - location, at every place it is used")
    def test_PIN_T17_python_uses_the_same_inequality_everywhere(self):
        text = re.sub(r"\s+", " ", py_text("scoring_logic.py"))
        # apply_stop_score (d_m), the departure judgement and the out-of-range detection (d), the first-valid-stop gate of the basic braking and the operational
        # arrival (dist_to_stop), the door-edge arrival (arrival_stop_error): six places, one inequality
        found = {v: len(re.findall(r"-\s?self\.bve_margin_f <= " + v + r" <= self\.bve_margin_b", text)) for v in ("d_m", "d", "dist_to_stop", "arrival_stop_error")}
        # Time Fix B (on purpose, was "d": 2): the departure judgement of evaluate_departure takes its range from the local margin_f / margin_b (the telemetry margin of the new target for a normal stop,
        # the range kept at the arrival for an operational stop) - the SAME inequality on the local names, pinned below; the out-of-range detection keeps the telemetry names
        self.assertEqual(found, {"d_m": 1, "d": 1, "dist_to_stop": 2, "arrival_stop_error": 1})
        self.assertEqual(len(re.findall(r"-\s?margin_f <= d <= margin_b", text)), 1)

    # -- the stop kind (items 5, 6, 8, 9; T14, T15) ---------------------------------------------------------------------------------------------
    @st0("T14", "REQUIREMENT-BACKED", items=(5, 6), note="the stop kind comes from author-defined Station values: Pass and DoorSideNumber (Current) / DoorSide (Legacy); Python derives is_operational_stop from ISPASS and DOORDIR only")
    def test_PIN_T14_the_stop_kind_comes_from_Pass_and_DoorSide(self):
        self.assertIn("try { sd.IsPass = st.Pass; }", self.cur)
        self.assertIn("try { sd.DoorDir = (int)st.DoorSideNumber; } catch { sd.DoorDir = 1; }", self.cur)
        self.assertIn("r.Pass = st.Pass;", self.lext)
        self.assertIn("r.DoorSide = st.DoorSide;", self.lext)
        self.assertIn("sd.IsPass = r.Pass;", self.ltl)
        self.assertIn("sd.DoorDir = r.DoorSide;", self.ltl)
        self.assertIn("is_operational_stop = (self.bve_is_pass == 0 and getattr(self, 'bve_doordir', 1) == 0)", re.sub(r"\s+", " ", py_text("scoring_logic.py")))

    @st0("T14", "REQUIREMENT-BACKED", items=(6, 10), note="owner point 10: an operational stop is NOT inferred from 'the doors did not open': no sender or Python statement sets DoorDir / bve_doordir to 0 from a door state")
    def test_PIN_T14_nothing_infers_an_operational_stop_from_a_door_that_stayed_closed(self):
        for name, text in (("Class1.cs", self.cur), ("LegacyStationTimeline.cs", self.ltl), ("LegacyTelemetrySession.cs", self.lses), ("LegacyTelemetryExtension.cs", self.lext)):
            self.assertNotRegex(text, r"\bDoorDir = 0\b", name)
            self.assertNotRegex(text, r"\bdoorDir = 0\b", name)
        for name in ("main.py", "scoring_logic.py", "managed_input.py", "telemetry_contract.py", "pause_recovery.py"):
            code = re.sub(r"#.*", "", py_text(name))
            self.assertNotRegex(code, r"bve_doordir\s*=\s*0\b", name)
        for name in ("main.py", "scoring_logic.py"):
            code = re.sub(r"#.*", "", py_text(name))
            self.assertEqual(len(re.findall(r"bve_doordir\s*=", code)), len(re.findall(r"bve_doordir\s*=\s*int\(", code)) + len(re.findall(r"bve_doordir\s*=\s*1\b", code)), name)

    @st0("T14", "KNOWN-DEFECT-BEHAVIOR", items=(6,), note="C-TY-5: a DoorSideNumber that can not be read becomes 1 (a normal stop) in Current; Legacy refuses the list; Python's default is 1")
    def test_PIN_T14_a_lost_door_side_becomes_a_normal_stop_in_current(self):
        self.assertIn("catch { sd.DoorDir = 1; }", self.cur)
        self.assertIn("int currentDoorDir = 1;", self.cur)
        self.assertIn("v.DoorDir = 1;", self.ltl)

    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(6, 8), note="the sender state machine: an operational stop (DoorDir == 0) arrives on 'stopped and in range' without looking at the doors; a normal stop looks at the doors")
    def test_PIN_T14_the_sender_arrival_of_an_operational_stop_does_not_look_at_the_doors(self):
        op = self.cur[self.cur.index("else if (targetSt.DoorDir == 0)"):]
        op = op[:op.index("else { if (!areDoorsClosed")]                                           # the operational branch ends where the normal-stop branch begins
        self.assertIn("if (isStopped && isInMargin) hasDoorOpenedAtTarget = true;", op)
        self.assertNotIn("areDoorsClosed", op)
        legacy = self.ltl[self.ltl.index("else if (st.DoorDir == 0)"):]
        legacy = legacy[:legacy.index("else { if (!areDoorsClosed")]
        self.assertIn("if (isStopped && isInMargin) { hasDoorOpenedAtTarget = true; }", legacy)
        self.assertNotIn("areDoorsClosed", legacy)

    @st0("T15", "REQUIREMENT-BACKED", items=(9,), note="a pass station (Pass) advances by position only (location > station location, not for a terminal), in both senders")
    def test_PIN_T15_a_pass_station_advances_by_position_only(self):
        self.assertIn("if (targetSt.IsPass) { if (location > nextStationLoc && !isTerminal) { targetStationIndex++;", self.cur)
        self.assertIn("if (st.IsPass) { if (location > nextStationLoc && !isTerminal) { target++;", self.ltl)

    # -- thresholds (items 14, 15; T14) ------------------------------------------------------------------------------------------------------------
    # Time Fix B3 (an intended change, owner decision): the cross-layer difference F-ST-3 is RESOLVED - the senders called < 0.1 km/h 'stopped', Python called exactly 0.0 'stopped'. BVE supplies exactly 0.0 while the
    # train stands, so all three now use speed == 0.0 (tests/test_timefix_b3_zero_speed_contract.py, Handshake/Tests/Test-TimeFixB3.ps1 hold the contract).
    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(14,), note="Time Fix B3: the senders and Python all call exactly 0.0 'stopped' (the 0.1 km/h band of the senders is gone; F-ST-3 resolved)")
    def test_PIN_T14_the_stop_threshold_is_exactly_zero_in_the_senders_and_in_python(self):
        self.assertIn("bool isStopped = speed == 0.0;", self.cur)
        self.assertIn("bool isStopped = speedKmh == 0.0;", self.ltl)
        sl = re.sub(r"\s+", " ", py_text("scoring_logic.py"))
        self.assertIn("is_exact_stop = self.bve_speed == 0.0", sl)
        self.assertIn("and self.bve_speed == 0.0 and not getattr(self, 'has_scored_stop_this_station', False)", sl)

    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(15,), note="an operational stop leaves the target only after the scheduled departure time AND 300 ms (not after the real departure), in both senders")
    def test_PIN_T14_the_operational_stop_advances_after_the_departure_time_and_300_ms(self):
        self.assertIn("if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal) { if (opStopDelayStartMs < 0) opStopDelayStartMs = timeMs; else if (timeMs >= opStopDelayStartMs + 300) { targetStationIndex++;", self.cur)
        self.assertIn("if (hasDoorOpenedAtTarget && timeMs >= depTime && !isTerminal) { if (opStopDelayStartMs < 0) { opStopDelayStartMs = timeMs; } else if (timeMs >= opStopDelayStartMs + 300) { target++;", self.ltl)

    @st0("T13", "CURRENT-BEHAVIOR-ONLY", items=(7,), note="the sender state machine for a normal stop: the door must be open within 100 m of the target, and the target advances when the doors are all closed again")
    def test_PIN_T13_the_sender_arrival_of_a_normal_stop_is_a_door_open_within_100_m(self):
        self.assertIn("if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true; if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal) { targetStationIndex++;", self.cur)
        self.assertIn("if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) { hasDoorOpenedAtTarget = true; } if (hasDoorOpenedAtTarget && areDoorsClosed && !isTerminal) { target++;", self.ltl)

    # -- the end station (item 17) --------------------------------------------------------------------------------------------------------------
    @st0("T14", "CROSS-LAYER-DIFFERENCE", items=(17,), note="F-TY-1: Current derives 'terminal' from sentinel departure times (BVE5 / BVE6 'dep = t'), Legacy reads Station.IsTerminal; no common rule exists")
    def test_PIN_T14_the_terminal_station_is_derived_differently_in_current_and_legacy(self):
        self.assertIn("bool isTerminalTime = departureTimeMs == TerminalDepartureTimeBve5Ms || departureTimeMs == TerminalDepartureTimeBve6Ms;", self.cur)
        self.assertIn("sd.IsTerminal = true;", self.cur)
        self.assertEqual(sorted(set(re.findall(r"\bsd\.IsTerminal = (\w+);", self.cur))), ["false", "true"])      # only ever set from the sentinel test, never from a Station member
        self.assertIn("r.IsTerminal = st.IsTerminal;", self.lext)
        self.assertIn("sd.IsTerminal = r.IsTerminal;", self.ltl)
        self.assertNotIn("TerminalDepartureTime", self.ltl)

    @st0("T14", "CURRENT-BEHAVIOR-ONLY", items=(17,), note="the fill-in is common: when no station is terminal the LAST station is made terminal, in both senders (and only the first stated terminal stays)")
    def test_PIN_T14_both_senders_make_the_last_station_terminal_when_none_is_stated(self):
        self.assertIn("stationList[stationList.Count - 1].IsTerminal = true;", self.cur)
        self.assertIn("list[list.Count - 1].IsTerminal = true;", self.ltl)

    # -- the distance searches that decide an identity today (items 18, 19, 20; T20) -----------------------------------------------------------
    @st0("T13", "FUTURE-REPLACEMENT-TARGET", items=(18,), note="C-ID-6: scoring_logic.py decides a station identity by a '< 1.0' position search at exactly these places (create_save_data, evaluate_arrival, evaluate_departure, 3 in update_physics_and_scoring)")
    def test_PIN_ITEM18_the_one_metre_reverse_lookups_of_the_scoring(self):
        tree = ast.parse(py_text("scoring_logic.py"))
        sites = {}
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Compare) and isinstance(node.left, ast.Call) and getattr(node.left.func, "id", "") == "abs" and len(node.comparators) == 1 \
                        and isinstance(node.ops[0], ast.Lt) and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value == 1.0:
                    src = ast.unparse(node.left)
                    if "location" in src:
                        sites[fn.name] = sites.get(fn.name, 0) + 1
        # Phase ST-2a (inverted: create_save_data was one of the six): the checkpoint takes its station from the verified StationIndex; the other five are ST-4's
        # Phase SI-R5.2-A (re-pinned: P03, the HUD next station / rule section, takes bve_tgt_idx): four remain, 2 in update_physics_and_scoring (SI-R5.2-B / C)
        # Phase SI-R5.2-B (re-pinned: P01, P04, P05 take bve_tgt_idx): one remains, evaluate_departure (P02, SI-R5.2-C)
        # Phase SI-R5.2-C (re-pinned: P02 takes prev_tgt_idx, verified against prev_next_loc within 0.01 m): none remains
        self.assertEqual(sites, {})

    @st0("T20", "KNOWN-DEFECT-BEHAVIOR", items=(19,), note="C-ID-5 (Phase ST-2b: inverted - it was: execute_retry picks the retry station by a '< 100.0' search from the check point position, lowest index, and falls back to station 0): the retry station is the saved StationIndex")
    def test_PIN_ITEM19_execute_retry_takes_the_saved_index_and_has_no_100_m_search_and_no_station_0_fallback(self):
        fn = py_function("scoring_logic.py", "execute_retry")
        self.assertEqual(floats_in(fn).count(100.0), 0)
        src = ast.unparse(fn)
        self.assertNotIn("target_bve_sta_idx", src)
        self.assertNotIn("< 100.0", src)
        self.assertIn("station_identity.check_retry_checkpoint", src)

    @st0("T20", "KNOWN-DEFECT-BEHAVIOR", items=(20,), note="DS02 (Phase ST-2c: inverted - it was: is_first_station is cleared by 'abs(NEXTLOC - location) > 100.0' on the first line): no distance test is left in scoring_logic.py")
    def test_PIN_ITEM20_is_first_station_has_no_100_m_distance_test(self):
        sl = re.sub(r"\s+", " ", py_text("scoring_logic.py"))
        self.assertNotIn("if abs(self.bve_next_loc - self.bve_location) > 100.0", sl)
        self.assertEqual(floats_in(ast.parse(py_text("scoring_logic.py"))).count(100.0), 0)
        self.assertIn("self.prev_next_loc = self.bve_next_loc", sl)
        self.assertIn("self.is_first_udp = False", sl)

    @st0("T20", "KNOWN-DEFECT-BEHAVIOR", items=(16, 19), note="C-ID-7: the checkpoint duplicate key is the float equality of target_loc")
    def test_PIN_ITEM19_the_checkpoint_duplicate_key_is_the_station_index_under_its_scope(self):
        sl = re.sub(r"\s+", " ", py_text("scoring_logic.py"))
        # Phase ST-2a (inverted: the key was the float equality of target_loc): the key is (scope, StationIndex)
        self.assertNotIn('self.save_data[-1]["target_loc"] != self.bve_next_loc', sl)
        self.assertIn("not station_identity.same_station(self.save_data[-1], snapshot)", sl)


class Z_Meta(unittest.TestCase):
    def test_META_every_pin_has_an_id_a_label_and_a_plan_id(self):
        seen = 0
        for name in sorted(n for n in dir(Pins) if n.startswith("test_")):
            meta = getattr(getattr(Pins, name), "st0", None)
            self.assertIsNotNone(meta, name)
            self.assertIn(meta["label"], LABELS, name)
            self.assertIn(meta["id"], PLAN_IDS, name)
            self.assertTrue(name.startswith("test_PIN_"), name)
            self.assertGreaterEqual(len(meta["note"]), 20, name)
            seen += 1
        self.assertGreaterEqual(seen, 20)

    def test_META_the_sources_are_read_as_the_audited_files(self):
        for path in (CLASS1, LEGACY_EXT, LEGACY_SESSION, LEGACY_TIMELINE):
            self.assertTrue(os.path.isfile(path), path)


if __name__ == "__main__":
    unittest.main()
