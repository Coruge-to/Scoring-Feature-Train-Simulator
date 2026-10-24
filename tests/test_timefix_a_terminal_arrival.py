"""Time Fix A (remaining time "--:--" at a terminal station) - SOURCE-SHAPE PINS of the arrival fill-in in the Current plugin (Class1.cs) and the Legacy telemetry
(LegacyStationTimeline.cs). The behaviour itself is RUN by Handshake/Tests/Test-TimeFixA.ps1 (the cut-out spans of Class1.cs and the real Legacy sources); Class1.cs can not run offline.

The contract: the station ROLE (IsTerminal) does not decide whether the arrival time is filled in from the departure time; the VALIDITY of the departure time does. A departure that is
undefined (-1) or the terminal sentinel (BVE6 = Int32.MaxValue ms, BVE5 = Int32.MaxValue + 1 ms) is never a usable time. IsTerminal itself stays (terminal handling, scoring finish, the
target station state machine). The departure of a terminal is NOT generated from an arrival (the first branch keeps its !IsTerminal).

ISOLATION: files are only read. No socket, no process, no write. No PyQt6, so it also runs under python -I.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
CLASS1 = os.path.join(PLUGIN, "TsScoringPlugin", "Class1.cs")
LEGACY_SRC = os.path.join(PLUGIN, "Handshake", "Telemetry", "Legacy", "src")
LEGACY_TIMELINE = os.path.join(LEGACY_SRC, "LegacyStationTimeline.cs")
LEGACY_EXT = os.path.join(LEGACY_SRC, "LegacyTelemetryExtension.cs")

_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")


def cs_code(path):
    """C# without comments, whitespace squashed to single blanks (string literals kept)."""
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", _TOKEN.sub(lambda m: m.group(0) if m.group(0).startswith('"') else " ", text))


class ShortCase(unittest.TestCase):
    longMessage = False

    def assertIn(self, member, container, msg=None):
        if member not in container:
            raise self.failureException(msg or "pin not found: %r" % (member[:240],))

    def assertNotIn(self, member, container, msg=None):
        if member in container:
            raise self.failureException(msg or "pin found but must be absent: %r" % (member[:240],))


class CurrentArrivalFillIn(ShortCase):
    @classmethod
    def setUpClass(cls):
        cls.cur = cs_code(CLASS1)

    def test_A01_arrival_is_filled_in_from_a_usable_departure_whatever_the_role(self):
        self.assertIn("else if ( stationList[i].DepTime > 0 && stationList[i].DepTime < TerminalDepartureTimeBve6Ms && stationList[i].ArrTime <= 0 ) { "
                      "stationList[i].ArrTime = stationList[i].DepTime - stationList[i].StoppageTime; if (stationList[i].ArrTime < 0) { stationList[i].ArrTime = 0; } }", self.cur)

    def test_A02_the_role_no_longer_gates_the_arrival_fill_in(self):
        self.assertNotIn("!stationList[i].IsTerminal && stationList[i].DepTime > 0", self.cur)
        self.assertEqual(len(re.findall(r"stationList\[i\]\.DepTime > 0 && stationList\[i\]\.DepTime < TerminalDepartureTimeBve6Ms", self.cur)), 1)

    def test_A03_the_departure_of_a_terminal_is_still_never_made_up_from_an_arrival(self):
        self.assertIn("if ( !stationList[i].IsTerminal && stationList[i].ArrTime > 0 && stationList[i].DepTime <= 0 ) { stationList[i].DepTime = stationList[i].ArrTime + stationList[i].StoppageTime; }", self.cur)

    def test_A04_the_terminal_sentinels_of_BVE5_and_BVE6_are_unchanged(self):
        self.assertIn("private const long TerminalDepartureTimeBve6Ms = int.MaxValue;", self.cur)
        self.assertIn("private const long TerminalDepartureTimeBve5Ms = (long)int.MaxValue + 1L;", self.cur)
        self.assertIn("bool isTerminalTime = departureTimeMs == TerminalDepartureTimeBve5Ms || departureTimeMs == TerminalDepartureTimeBve6Ms;", self.cur)
        self.assertIn("else if ( departureTimeMs >= -1L && departureTimeMs < TerminalDepartureTimeBve6Ms ) { sd.RawDepTime = (int)departureTimeMs; }", self.cur)

    def test_A05_a_sentinel_departure_is_stored_as_undefined(self):
        self.assertIn("if (isTerminalTime) { sd.IsTerminal = true; sd.RawDepTime = -1; }", self.cur)

    def test_A06_the_terminal_role_is_still_derived_the_same_way(self):
        self.assertEqual(sorted(set(re.findall(r"\bsd\.IsTerminal = (\w+);", self.cur))), ["false", "true"])
        self.assertIn("stationList[stationList.Count - 1].IsTerminal = true;", self.cur)
        self.assertIn("bool explicitTerminalFound = false;", self.cur)

    def test_A07_the_terminal_next_time_still_reads_the_arrival_time(self):
        self.assertIn("if (isTerminal) { if (hasDoorOpenedAtTarget) {", self.cur)
        self.assertIn("else nextStationTime = targetSt.ArrTime > 0 ? targetSt.ArrTime : targetSt.InterpolatedTime;", self.cur)

    def test_A08_the_default_time_anchor_and_stoppage_reader_are_unchanged(self):
        self.assertIn("try { sd.StoppageTime = st.StoppageTimeMilliseconds; } catch { try { sd.StoppageTime = (int)((TimeSpan)st.StoppageTime).TotalMilliseconds; } catch { sd.StoppageTime = 15000; } }", self.cur)
        self.assertIn("if (stationList[i].IsTerminal) { stationList[i].DepTime = -1; stationList[i].InterpolatedTime = stationList[i].ArrTime; }", self.cur)


class LegacyArrivalFillIn(ShortCase):
    @classmethod
    def setUpClass(cls):
        cls.tl = cs_code(LEGACY_TIMELINE)
        cls.ext = cs_code(LEGACY_EXT)

    def test_B01_arrival_is_filled_in_from_a_usable_departure_whatever_the_role(self):
        self.assertIn("else if (list[i].DepTime > 0 && list[i].DepTime < int.MaxValue && list[i].ArrTime <= 0) { list[i].ArrTime = list[i].DepTime - list[i].StoppageTime; if (list[i].ArrTime < 0) { list[i].ArrTime = 0; } }", self.tl)

    def test_B02_the_role_no_longer_gates_the_arrival_fill_in(self):
        self.assertNotIn("!list[i].IsTerminal && list[i].DepTime > 0", self.tl)

    def test_B03_the_departure_of_a_terminal_is_still_never_made_up_from_an_arrival(self):
        self.assertIn("if (!list[i].IsTerminal && list[i].ArrTime > 0 && list[i].DepTime <= 0) { list[i].DepTime = list[i].ArrTime + list[i].StoppageTime; }", self.tl)

    def test_B04_the_departure_reader_judges_the_value_not_the_role(self):
        self.assertIn("if (r.DepartureMs >= -1 && r.DepartureMs < int.MaxValue) { sd.RawDepTime = r.DepartureMs; }", self.tl)
        self.assertNotIn("!r.IsTerminal && r.DepartureMs", self.tl)
        self.assertIn("sd.IsTerminal = r.IsTerminal;", self.tl)

    def test_B05_the_terminal_role_is_still_derived_the_same_way(self):
        self.assertIn("list[list.Count - 1].IsTerminal = true;", self.tl)
        self.assertIn("bool explicitTerminalFound = false;", self.tl)
        self.assertIn("r.IsTerminal = st.IsTerminal;", self.ext)
        self.assertIn("r.DepartureMs = st.DepartureTimeMilliseconds;", self.ext)

    def test_B06_the_terminal_next_time_still_reads_the_arrival_time(self):
        self.assertIn("nextStationTime = st.ArrTime > 0 ? st.ArrTime : st.InterpolatedTime;", self.tl)

    def test_B07_the_stalist_keeps_its_nine_fields(self):
        self.assertIn(".Append(TelemetryContract.I(st.ArrTime)).Append('=') .Append(TelemetryContract.I(st.DepTime)).Append('=') .Append(TelemetryContract.I(st.DefaultTime)).Append('=')"
                      " .Append(TelemetryContract.I(st.StoppageTime)).Append('=') .Append(st.IsPass ? \"1\" : \"0\").Append('=') .Append(st.IsTerminal ? \"1\" : \"0\");", self.tl)


if __name__ == "__main__":
    unittest.main()
