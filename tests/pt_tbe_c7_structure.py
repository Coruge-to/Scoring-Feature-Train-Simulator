"""Stage TB-E 1.1 (OD-TE2-3): the STRUCTURAL guard of the PTPAIR additions to the C# senders. Not a test module (no test* name): the tests import it (test_lc5_ui_shutdown C7 and test_pt_tbe_c7_guard).

The PTPAIR supply is ONE formal chain, and only that chain may exist:
  records (the five raw values of EVERY station of the list, read once while the list is built)
  -> PseudoTurnbackPairCodec.Publish(records, <the list id of the same list>)   [the only producer of the part text]
  -> the part text is cleared wherever the list identity is cleared (Reset / the two resets of the Current sender)
  -> the part is written ONCE, right after STIDX, under STIDX's own condition, and never anywhere else.
A guard that only looked for the word PTPAIR in an added line would accept any code that happens to contain it. This one compares the CODE lines (comments removed) that mention the chain with the exact
formal statements, in order, with their neighbours, so that an unknown telemetry line, a malformed or duplicated PTPAIR, a PTPAIR at another place, a wrong station / pair count, a list id or a
generation that does not belong to the line, and an unrelated line that merely contains the word are ALL differences. Each function returns the list of violations (empty = the formal chain, exactly)."""
import difflib
import re

SESSION = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs"
TIMELINE = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs"
CURRENT = "TsScoringPlugin/TsScoringPlugin/Class1.cs"
CODEC = "TsScoringPlugin/Handshake/Telemetry/Shared/PseudoTurnbackPairCodec.cs"
BASE_COMMIT = "cbebfd3"

_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)


def norm(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def code_lines(text):
    """[(line number, stripped code with comments removed)] for every non-empty code line; string literals are kept intact."""
    def drop(m):
        s = m.group(0)
        return "" if s.startswith("/") else s
    out = []
    for n, line in enumerate(norm(text).split("\n")):
        code = _TOKEN.sub(drop, line).strip()
        if code:
            out.append((n, code))
    return out


def _mentions(lines, tokens):
    return [(n, c) for n, c in lines if any(t in c for t in tokens)]


def _neighbour(lines, n, offset):
    """The code line `offset` code lines away from line n (None when out of range)."""
    idx = [i for i, (k, _) in enumerate(lines) if k == n]
    if not idx:
        return None
    j = idx[0] + offset
    return lines[j][1] if 0 <= j < len(lines) else None


def _chain(text, tokens, expected, neighbours):
    """The ordered chain of the code lines that mention `tokens` must be EXACTLY `expected`; each (statement, offset, wanted line) of `neighbours` must hold for the (single) statement."""
    v = []
    lines = code_lines(text)
    found = _mentions(lines, tokens)
    if [c for _, c in found] != list(expected):
        v.append("chain: %r != %r" % ([c for _, c in found], list(expected)))
        return v
    for statement, offset, wanted in neighbours:
        at = [n for n, c in found if c == statement]
        if len(at) != 1:
            v.append("statement count %d: %s" % (len(at), statement))
            continue
        for n in at:
            got = _neighbour(lines, n, offset)
            if got != wanted:
                v.append("neighbour %+d of %s is %r, not %r" % (offset, statement, got, wanted))
    return v


# -- the Legacy sender (LegacyTelemetrySession.cs) -----------------------------------------------------------------------------------------------------------
SESSION_COMMENT = "// Phase TB-E: the PTPAIR key, right after STIDX (the Current sender writes the same part in the same place); absent when the list could not be qualified (fail closed)"
SESSION_KEY = 'if (timeline.PtPairText != null) lb.Key("PTPAIR", timeline.PtPairText.Substring("PTPAIR:".Length));'
SESSION_PREV = '"STIDX", StationIndexWire.Value(sv.Index, timeline.ArrivalIndex, timeline.ArrivalSeq, timeline.Count, timeline.ListId));'
SESSION_NEXT = "if (official != null)"
# Formal LastStop BveG (2026-11-08, an intended change): the Shadow sway block (ACCELX / SWAY / SWAYR, LineBuilder.Part) and the CALCG group with its reference-sample state are retired; the added lines are exactly the PTPAIR key and the ACCELZ block, the removed lines are exactly the declared CALCG / sway lines.
# (history) Shadow comparison (Stage 1, on purpose): the ACCELZ group of the official AccelerationZ, one formal block (its own try / catch) before the CALCG block; the lines are listed as they are in the file; Shadow sway diagnostics (an intended change, not a drift): the ACCELX / SWAY group (own try / catch, after the ACCELZ block) and LineBuilder.Part (the SWAYR diagnostic part of its own). Nothing was removed or changed: the added lines are listed as they are in the file
SESSION_FORMAL_ADDED = ['// Phase TB-E: the PTPAIR key, right after STIDX (the Current sender writes the same part in the same place); absent when the list could not be qualified (fail closed)', 'if (timeline.PtPairText != null) lb.Key("PTPAIR", timeline.PtPairText.Substring("PTPAIR:".Length));', '// The official AccelerationZ of this Tick, m/s^2 exactly as read (no unit change, no abs, no clamp, no smoothing): the one input of the stop-jerk scoring. It needs no previous sample.', '// A value that cannot be read is not written and its token is not in AVAIL; nothing is put in its place.', 'try', 'ILegacyVibrationApi vibration = api as ILegacyVibrationApi;', 'double accelZ;', 'if (vibration != null && vibration.TryAccelerationZ(out accelZ) && !double.IsNaN(accelZ) && !double.IsInfinity(accelZ))', 'lb.Group(TelemetryContract.TokAccelZ, "ACCELZ", TelemetryContract.F(accelZ, "F6"));', '}', 'catch', '{']
SESSION_FORMAL_REMOVED = ['private double lastSpeedMps;', 'private bool haveLastSample;', 'lastSpeedMps = 0.0;', 'haveLastSample = false;', 'haveLastSample = false;', 'haveLastSample = false;', '// acceleration from two samples of THIS scenario instance; the first sample has no reference and says nothing', 'if (haveLastSample)', 'double g = 0.0;', 'if (timeMs > lastTimeMs && timeMs - lastTimeMs < 1000)', 'double dt = (timeMs - lastTimeMs) / 1000.0;', 'g = ((speedMps - lastSpeedMps) / dt) / TelemetryContract.GravityMps2;', '', 'lb.Group(TelemetryContract.TokCalcG, "CALCG", TelemetryContract.F(g, "F5"));', 'lastSpeedMps = speedMps;', 'haveLastSample = true;']


def session_violations(base_text, current_text):
    """base_text = LegacyTelemetrySession.cs of the LC-4b commit (None when git does not know it), current_text = the file now. Exactly the two formal lines may be ADDED and nothing may be removed or changed."""
    v = []
    cur = norm(current_text)
    cl = [l.strip() for l in cur.split("\n")]
    if base_text is not None:
        bl = [l.strip() for l in norm(base_text).split("\n")]
        added, removed = [], []
        for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, bl, cl, autojunk=False).get_opcodes():
            if op in ("delete", "replace"):
                removed += bl[a1:a2]
            if op in ("insert", "replace"):
                added += cl[b1:b2]
        if removed != SESSION_FORMAL_REMOVED:
            v.append("lines removed or changed: %r" % removed[:3])
        if added != SESSION_FORMAL_ADDED:
            v.append("added lines are not exactly the formal ones (PTPAIR key + Shadow ACCELZ block): %r" % added[:4])
    keys = [i for i, l in enumerate(cl) if l == SESSION_KEY]
    if len(keys) != 1:
        v.append("the formal PTPAIR key line occurs %d times (must be 1)" % len(keys))
    else:
        i = keys[0]
        if cl[i - 1] != SESSION_COMMENT or cl[i - 2] != SESSION_PREV or cl[i + 1] != SESSION_NEXT:
            v.append("the PTPAIR key is not directly after the STIDX statement and before the OFFTGT block")
    mentions = [c for _, c in _mentions(code_lines(cur), ("PTPAIR", "PtPair"))]
    if mentions != [SESSION_KEY]:
        v.append("code that mentions PTPAIR / PtPair: %r" % mentions[:3])
    return v


# -- the Legacy timeline (LegacyStationTimeline.cs) --------------------------------------------------------------------------------------------------------
_TL_TOKENS = ("PseudoTurnback", "ptRecords", "ptPairText", "PtPairText", "PTPAIR")
_TL_EXPECTED = (
    "private List<PseudoTurnbackRecord> ptRecords;",
    "private string ptPairText;",
    "internal string PtPairText { get { return ptPairText; } }",
    "ptRecords = null; ptPairText = null;",
    "ptRecords = new List<PseudoTurnbackRecord>(list.Count);",
    "ptRecords.Add(new PseudoTurnbackRecord(list[i].RawArrTime > 0, list[i].RawDepTime > 0, list[i].IsTerminal, list[i].IsPass));",
    "ptPairText = list.Count > 0 ? PseudoTurnbackPairCodec.Publish(ptRecords, listId) : null;",
)
_TL_NEIGHBOURS = (
    ("ptRecords = null; ptPairText = null;", -1, "listId = StationListIdentity.EmptyId;"),
    ("ptRecords = new List<PseudoTurnbackRecord>(list.Count);", 1, "for (int i = 0; i < list.Count; i++)"),
    ("ptRecords = new List<PseudoTurnbackRecord>(list.Count);", 2, "{"),
    ("ptRecords = new List<PseudoTurnbackRecord>(list.Count);", 3, "ptRecords.Add(new PseudoTurnbackRecord(list[i].RawArrTime > 0, list[i].RawDepTime > 0, list[i].IsTerminal, list[i].IsPass));"),
    ("ptRecords = new List<PseudoTurnbackRecord>(list.Count);", 4, "}"),
    ("ptPairText = list.Count > 0 ? PseudoTurnbackPairCodec.Publish(ptRecords, listId) : null;", -1,
     "listId = payload == null ? StationListIdentity.EmptyId : StationListIdentity.Compute(payload.Substring(StaListPrefix.Length));"),
)


def timeline_violations(text):
    return _chain(text, _TL_TOKENS, _TL_EXPECTED, _TL_NEIGHBOURS)


# -- the Current sender (Class1.cs) ------------------------------------------------------------------------------------------------------------------------
_CU_TOKENS = ("PseudoTurnback", "ptRecords", "ptpairText", "PTPAIR")
_CU_RESET = "ptRecords = null; ptpairText = null;"
_CU_EXPECTED = (
    "private List<TSScoringPlugin.Telemetry.PseudoTurnbackRecord> ptRecords = null;",
    "private string ptpairText = null;",
    _CU_RESET,
    _CU_RESET,
    "ptRecords = new List<TSScoringPlugin.Telemetry.PseudoTurnbackRecord>(stationList.Count);",
    "ptRecords.Add(new TSScoringPlugin.Telemetry.PseudoTurnbackRecord(stationList[i].RawArrTime > 0, stationList[i].RawDepTime > 0, stationList[i].IsTerminal, stationList[i].IsPass));",
    "ptpairText = staInfoList.Count > 0 ? TSScoringPlugin.Telemetry.PseudoTurnbackPairCodec.Publish(ptRecords, stidxListId) : null;",
    'if (ptpairText != null) data += "," + ptpairText;',
)
_CU_STIDX = 'data += ",STIDX:1:" + TSScoringPlugin.Telemetry.StationIndexWire.Fields(stidxTarget, stidxArrivalIndex, stidxArrivalSeq, stidxListCount, stidxListId);'
_CU_NEIGHBOURS = (
    ('if (ptpairText != null) data += "," + ptpairText;', -1, _CU_STIDX),
    ('if (ptpairText != null) data += "," + ptpairText;', -3, "if (isInitialized && stidxListReady && stidxListCount == stationList.Count)"),
    ("ptRecords = new List<TSScoringPlugin.Telemetry.PseudoTurnbackRecord>(stationList.Count);", 1, "for (int i = 0; i < stationList.Count; i++)"),
    ("ptRecords = new List<TSScoringPlugin.Telemetry.PseudoTurnbackRecord>(stationList.Count);", 3, "ptRecords.Add(new TSScoringPlugin.Telemetry.PseudoTurnbackRecord(stationList[i].RawArrTime > 0, stationList[i].RawDepTime > 0, stationList[i].IsTerminal, stationList[i].IsPass));"),
    ("ptpairText = staInfoList.Count > 0 ? TSScoringPlugin.Telemetry.PseudoTurnbackPairCodec.Publish(ptRecords, stidxListId) : null;", -1, "stidxListReady = true;"),
    ("ptpairText = staInfoList.Count > 0 ? TSScoringPlugin.Telemetry.PseudoTurnbackPairCodec.Publish(ptRecords, stidxListId) : null;", -2,
     "stidxListId = staInfoList.Count > 0 ? TSScoringPlugin.Telemetry.StationListIdentity.Compute(string.Join(\",\", staInfoList)) : TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;"),
)


_CU_DATA = (
    None,          # string data = $"SCENARIO_ID:...";  (the one line of the base telemetry, not judged here beyond its first characters)
    _CU_STIDX,
    'if (ptpairText != null) data += "," + ptpairText;',
    'data += "," + TSScoringPlugin.Telemetry.OfficialTargetWire.Key + ":" + officialValue;',
)


def current_violations(text):
    v = _chain(text, _CU_TOKENS, _CU_EXPECTED, _CU_NEIGHBOURS)
    if not v:
        # the telemetry line of the Current sender is built by exactly four statements: no other part may be appended to it
        built = [c for _, c in code_lines(text) if re.search(r"(^|[^\w.])data\s*\+?=\s", c)]
        if len(built) != len(_CU_DATA) or not built[0].startswith('string data = $"SCENARIO_ID:') or built[1:] != list(_CU_DATA[1:]):
            v.append("the telemetry line is not built by exactly the formal statements: %r" % [b[:60] for b in built])
    if not v:
        lines = code_lines(text)
        for n in [n for n, c in lines if c == _CU_RESET]:
            if _neighbour(lines, n, -1) != "stidxListId = TSScoringPlugin.Telemetry.StationListIdentity.EmptyId;":
                v.append("a PTPAIR reset is not directly after the list identity reset")
    return v

# -- the shared Codec (PseudoTurnbackPairCodec.cs): the part states the stations and the pairs of the set it encodes, and Publish is Qualify -> Encode with the same list id ----------------------------------
_CD_TOKENS = ("Qualify(", "Encode(", "return Key", "set.StationCount == 0", "i < set.Count")
_CD_EXPECTED = (
    "public static string Encode(PseudoTurnbackPairSet set, string listId)",
    "if (set.StationCount == 0) id = EmptyListId;",
    "for (int i = 0; i < set.Count; i++)",
    'return Key + ":" + Version.ToString(CultureInfo.InvariantCulture) + ":" + id + ":" + set.StationCount.ToString(CultureInfo.InvariantCulture) + ":" + set.Count.ToString(CultureInfo.InvariantCulture) + ":" + sb.ToString();',
    "try { return Encode(PseudoTurnbackQualifier.Qualify(records), listId); }",
)


def codec_violations(text):
    v = _chain(text, _CD_TOKENS, _CD_EXPECTED, ())
    # TryDecode is the validation mirror: it must stay a decode that compares the declared pair count with the parsed one
    if "if (items.Count != pairCount) { reason = ReasonCount; return null; }" not in [c for _, c in code_lines(text)]:
        v.append("the declared pair count is no longer compared with the parsed one")
    return v
