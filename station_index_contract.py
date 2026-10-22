"""Phase PID-D4JA StationIndex ST-1A - the STIDX supply contract on the Python side (pure: no Qt, no Win32, no scoring state).

What this module is
  * the vocabulary and the pure checks of the versioned telemetry part

        STIDX:1:<tgt>:<arr>:<arrseq>:<count>:<hash>

    that BOTH senders (the BveEX Current plugin and the AtsEX Legacy telemetry DLL) write into their per-Tick telemetry line with the SAME meaning:
        tgt     index (0..count-1) of the station the line's NEXTLOC / NEXTTIME / ... belong to; -1 = no next station (then NEXTLOC is -1)
        arr     index of the station at which the last ARRIVAL CANDIDATE EVENT happened (the sender's door-open / operational-stop flag went false -> true
                for that target); -1 = none yet. It is NOT "arrival succeeded": whether the stop counts is still decided by the physical rules of Python
        arrseq  number of arrival candidate events since the scenario instance began (0 = none); +1 per event
        count   number of stations of the list the line was written for
        hash    CRC-32 (8 upper-case hex digits) of the UTF-8 text of the STALIST payload (the text after "STALIST:"); an empty list is 00000000
    and the scope in which an index means anything: (BVE PID, SCENARIO_ID, hash, count). The PID is the one of the DataPlane the line arrived on, the
    SCENARIO_ID is the one of the same line, so the scope is atomic with the index.
  * StationIndexObserver: RECEIVES (the STALIST text and the telemetry line), CHECKS (syntax, version, range, list identity, NEXTLOC invariant, event numbers)
    and RECORDS (an independent state of its own + fixed-word diagnostic events). It never reads or writes the scoring state, the station list, the
    checkpoints, the HUD or the jump state: Phase ST-1A only SUPPLIES the index. Using it as the identity of a station is a later Stage.

The vector table tests/stidx_vectors_st0.json is the shared specification of verdict() and list_id() (the C# half is StationListIdentity.cs).
"""
import re
import time
import zlib

KEY = "STIDX"
PREFIX = "STIDX:"
VERSION = 1
NO_STATION = -1
EMPTY_LIST_ID = "00000000"

# The tolerance of the identity / position invariant (05 M-6): the same 0.01 m as everywhere in the jump contract.
NEXTLOC_TOLERANCE_M = 0.01
# How long a STIDX whose hash differs from the latest STALIST is only NOT-READY (the STALIST is re-sent once a second, so the two meet within about a
# second). The value is undecided (OD-NEW-6): it is a PARAMETER of verdict(); this is only the default of the observer.
DEFAULT_GRACE_MS = 3000
# The line numbers of one generation at which the observer writes a summary event (and it writes one more when the generation ends): about 5 s, 50 s and 500 s of the
# 60 Hz Tick. The managed log keeps few lines per event name, so these are few and spread out.
SUMMARY_AT = (300, 3000, 30000)
# Close Decision (observability): the detail event `stidx` is also written when the target (tgt) or the arrival event number (arrseq) of the line changes. Those PROGRESS
# events have a budget of their own (a long line with many stations can not use up the budget of the verdict / scope events, and the other way round).
DEFAULT_MAX_PROGRESS_EVENTS = 20
# The reason codes of the `why` field of an event (joined with "-" in this order): v verdict changed, s scope changed, t tgt changed, q arrseq changed,
# a arr changed while arrseq did not (a violation of the contract that has no verdict of its own: it is only logged and counted, aa in the summary).
WHY_VERDICT, WHY_SCOPE, WHY_TGT, WHY_ARRSEQ, WHY_ARR_ONLY = "v", "s", "t", "q", "a"
V_OK = "stidx-ok"
V_MISSING = "stidx-missing"
V_VERSION = "stidx-version"
V_RANGE = "stidx-range"
V_NEXTLOC = "stidx-nextloc"
V_LIST_MISMATCH = "stidx-list-mismatch"
V_ARRSEQ_GAP = "stidx-arrseq-gap"
V_NOT_READY = "NOT-READY"
# ST-1A addition (the vector table has no case for it): the part is there but is not of the form of the contract
V_MALFORMED = "stidx-malformed"

VERDICTS = (V_OK, V_MISSING, V_VERSION, V_RANGE, V_NEXTLOC, V_LIST_MISMATCH, V_ARRSEQ_GAP, V_NOT_READY, V_MALFORMED)
# What the summary counts as a parse error (pe), a range error (rg) and a hash error (hm). nextloc and arrseq-gap are part of `bad` only; unavailable = miss + ntr.
_PARSE_ERRORS = (V_MALFORMED, V_VERSION)

_INT32_MAX = 2 ** 31 - 1
_PART = re.compile(r"^STIDX:(-?[0-9]{1,11}):(-?[0-9]{1,11}):(-?[0-9]{1,11}):(-?[0-9]{1,11}):(-?[0-9]{1,11}):([0-9A-Fa-f]{8})$", re.ASCII)
_VERSION_ONLY = re.compile(r"^STIDX:(-?[0-9]{1,11})(?::|$)", re.ASCII)


def list_id(payload_text):
    """The identity of a station list: CRC-32 of the UTF-8 text of the STALIST payload, as 8 upper-case hex digits (an empty payload gives 00000000)."""
    return "%08X" % (zlib.crc32(payload_text.encode("utf-8")) & 0xFFFFFFFF)


class StidxFields(object):
    """The numbers of one STIDX part (as written, not yet trusted)."""
    __slots__ = ("version", "tgt", "arr", "arrseq", "count", "list_id")

    def __init__(self, version, tgt, arr, arrseq, count, hash_text):
        self.version, self.tgt, self.arr, self.arrseq, self.count, self.list_id = version, tgt, arr, arrseq, count, hash_text

    def as_tuple(self):
        return (self.version, self.tgt, self.arr, self.arrseq, self.count, self.list_id)


def format_part(tgt, arr, arrseq, count, hash_text):
    """The part a sender writes (the Python twin of StationIndexWire.Value; used by the tests and the offline rigs)."""
    return "%s%d:%d:%d:%d:%d:%s" % (PREFIX, VERSION, tgt, arr, arrseq, count, hash_text)


def parse_part(part):
    """(StidxFields, None) for a well formed part of version 1, else (None, word): V_VERSION for another version, V_MALFORMED for anything else."""
    if part is None or not isinstance(part, str):
        return None, V_MALFORMED
    m = _VERSION_ONLY.match(part)
    if m is None:
        return None, V_MALFORMED
    if int(m.group(1)) != VERSION:
        return None, V_VERSION
    m = _PART.match(part)
    if m is None:
        return None, V_MALFORMED
    numbers = [int(g) for g in m.groups()[:5]]
    if any(abs(n) > _INT32_MAX for n in numbers):
        return None, V_RANGE
    return StidxFields(numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], m.group(6).upper()), None


def verdict(line, nextloc, station_locations, list_hash, elapsed_since_mismatch_ms, grace_ms, prev_arrseq):
    """The pure judgement of ONE STIDX part against what the receiver knows (the shared vectors pin it).

    line                       the STIDX part (a str) or None when the telemetry line has none
    nextloc                    the NEXTLOC of the same telemetry line (float) or None
    station_locations          the locations of the stations of the latest STALIST, in order
    list_hash                  the list_id of the raw text of the latest STALIST, or None when none was received
    elapsed_since_mismatch_ms  how long the hash has differed from list_hash already
    grace_ms                   while the mismatch is younger than this the verdict is only NOT-READY
    prev_arrseq                the arrseq of the previous line of this scenario instance, or -1 when there is none
    Order of the checks: missing, version / malformed, range, list identity, NEXTLOC invariant, arrseq continuity."""
    if line is None:
        return V_MISSING
    fields, word = parse_part(line)
    if word is not None:
        return word
    count = fields.count
    if count < 0 or not (NO_STATION <= fields.tgt < count) or not (NO_STATION <= fields.arr < count) or fields.arrseq < 0:
        return V_RANGE
    if list_hash is None or fields.list_id != str(list_hash).upper():
        return V_LIST_MISMATCH if elapsed_since_mismatch_ms > grace_ms else V_NOT_READY
    if count != len(station_locations):
        return V_LIST_MISMATCH                       # the same hash but another number of stations: the two can not both be the list of this line
    if nextloc is None:
        return V_NEXTLOC
    expected = station_locations[fields.tgt] if fields.tgt >= 0 else -1.0
    if abs(nextloc - expected) > NEXTLOC_TOLERANCE_M + 1e-9:
        return V_NEXTLOC
    if prev_arrseq >= 0 and fields.arrseq != prev_arrseq and fields.arrseq != prev_arrseq + 1:
        return V_ARRSEQ_GAP
    return V_OK


def split_stalist(payload_text):
    """(locations, list_id) of a STALIST payload, read tolerantly: the list_id is always of the RAW text; an entry that has no readable location makes the
    list unusable for the NEXTLOC check (locations = None), which can only end in a mismatch verdict, never in an exception."""
    locations = []
    if payload_text:
        for entry in payload_text.split(","):
            fields = entry.split("=")
            try:
                locations.append(float(fields[2]))
            except (IndexError, ValueError):
                return None, list_id(payload_text)
    return locations, list_id(payload_text)


def _part_of(telemetry_text, key):
    """The value text of the first `key:` part of a telemetry line, or None. (Parts are separated by ','; STIDX and NEXTLOC contain no ','.)"""
    prefix = key + ":"
    for part in telemetry_text.split(","):
        if part.startswith(prefix):
            return part
    return None


class StationIndexObserver(object):
    """Receives, checks and records STIDX. Independent state: nothing here is read by, or written into, the scoring.

    Public state (all of it reset by reset(); the unavailable form is -1 / "" / False):
        ready        True only while the last line was judged V_OK: only then are the index values below the sender's current truth
        tgt_idx, arr_idx, arr_seq, count, list_id      the values of the last READY line
        scenario_id  the SCENARIO_ID of the last line that carried a STIDX part (None before any)
        verdict      the last verdict word
        list_generation   how many distinct READY scopes (scenario_id, list_id, count) were seen since reset(); a change of the list inside ONE scenario
                          instance is counted in list_changes_in_scenario (the contract calls it an anomaly)
        counts       verdict word -> number of lines
        last_fields  the raw numbers of the last parsed part (diagnostics only)
    log(event, **fields) is called only on a CHANGE: of the verdict or of the scope (at most `max_events` times between two reset()s), or of the target tgt / the
    event number arrseq / the arrival station arr without a new arrseq (PROGRESS events, at most `max_progress_events` times between two reset()s; an event that
    is also a verdict or scope change uses the first budget). The `why` field names the reasons (WHY_*). Never once per line: a run of identical lines writes nothing.
    Besides that two SUMMARY lines (log("stidx-sum", p=1 ...): the numbers of lines by kind and the parse / range / hash error counts, so that "every line carried a
    STIDX" can be read from a log that only keeps changes; p=2: the LAST values seen: tgt arr seq cnt list scn verdict) are written when a generation has had
    SUMMARY_AT lines and once more when it ends (reset(): a new generation begins; finish(): the application ends - whichever comes first); these are not counted against
    the event budgets. The two parts are two lines because the Caller keeps
    160 characters of a line and the fields do not fit in one."""

    def __init__(self, log=None, clock=None, grace_ms=DEFAULT_GRACE_MS, max_events=20, max_progress_events=DEFAULT_MAX_PROGRESS_EVENTS):
        self._log = log
        self._clock = clock if clock is not None else time.monotonic
        self.grace_ms = grace_ms
        self.max_events = max_events
        self.max_progress_events = max_progress_events
        self._stalist_locations = None
        self._stalist_list_id = None
        self._stalist_received = False
        self.reset()

    # -- lifecycle ---------------------------------------------------------------------------------------------------------------------------
    def reset(self):
        """A new scenario generation (or a new application instance): every value received from a STIDX is void. The latest STALIST is kept (it is replaced
        by the next one within a second, and one that arrived just before the reset belongs to the new generation)."""
        if getattr(self, "lines", 0) > 0 and not getattr(self, "_final_written", False):
            self._summary(True)                              # the generation that ends here: its totals are written before they are cleared (unless finish() wrote them already)
        self._final_written = False
        self.ready = False
        self.tgt_idx = NO_STATION
        self.arr_idx = NO_STATION
        self.arr_seq = NO_STATION
        self.count = NO_STATION
        self.list_id = ""
        self.scenario_id = None
        self.verdict = V_MISSING
        self.list_generation = 0
        self.list_changes_in_scenario = 0
        self.counts = {}
        self.lines = 0
        self.events = 0
        self.events_suppressed = 0
        self.progress_events = 0
        self.progress_suppressed = 0
        self.tgt_changes = 0                                 # how many times tgt changed from one line to the next (parsed parts only)
        self.arrseq_changes = 0                              # ... arrseq
        self.arr_without_seq = 0                             # ... arr changed while arrseq and the scenario did not (a contract violation)
        self.last_fields = None
        self._last_parsed = None                             # the last part that could be PARSED (sticky across lines without one): the "last observed" values
        self._seen = None                                    # the previous parsed part of this scenario instance: the baseline of the change detection
        self._scope = None
        self._prev_arrseq = NO_STATION
        self._mismatch_since = None
        self._logged_verdict = None

    def finish(self):
        """The application ends (the managed shutdown): the generation that is running ends here, so its generation-end summary (final=1) is written, exactly once.
        reset() is the other way a generation ends (a new one begins); whichever comes first writes it and the other finds it written. Nothing received = nothing is
        written. A line that arrives after a finish is a new fact: the next finish or reset writes the summary again, so a final=1 never disagrees with the last line.
        Never raises (the sink is guarded in the summary); never changes a value the observer publishes."""
        if self.lines > 0 and not self._final_written:
            self._final_written = True
            self._summary(True)

    @property
    def scope(self):
        """(scenario_id, list_id, count) of the last READY line, or None. (The BVE PID is the one of the DataPlane the line arrived on.)"""
        return self._scope

    # -- the intake --------------------------------------------------------------------------------------------------------------------------
    def note_stalist(self, payload_text):
        """The raw text of a STALIST datagram (without "STALIST:"). Never raises."""
        try:
            self._stalist_locations, self._stalist_list_id = split_stalist(payload_text)
            self._stalist_received = True
        except Exception:
            self._stalist_locations, self._stalist_list_id, self._stalist_received = None, None, False

    def observe(self, telemetry_text, scenario_id=None):
        """One accepted telemetry line. Returns the verdict word. Never raises, never touches anything outside this object."""
        try:
            return self._observe(telemetry_text, scenario_id)
        except Exception:
            self._record(V_MALFORMED, None, scenario_id)
            return V_MALFORMED

    def snapshot(self):
        """A copy of the public state (for the diagnostics and the tests)."""
        return {"ready": self.ready, "tgt_idx": self.tgt_idx, "arr_idx": self.arr_idx, "arr_seq": self.arr_seq, "count": self.count, "list_id": self.list_id,
                "scenario_id": self.scenario_id, "verdict": self.verdict, "list_generation": self.list_generation,
                "list_changes_in_scenario": self.list_changes_in_scenario, "counts": dict(self.counts), "lines": self.lines}

    # -- inside ------------------------------------------------------------------------------------------------------------------------------
    def _observe(self, telemetry_text, scenario_id):
        part = _part_of(telemetry_text, KEY)
        if part is not None and scenario_id is not None and self.scenario_id is not None and scenario_id != self.scenario_id:
            self._prev_arrseq = NO_STATION                  # a new scenario instance: the event numbers start again
            self._mismatch_since = None
            self._seen = None                               # ... and so do the baselines of the change detection (a new scenario is a scope change, not a tgt / arrseq one)
        nextloc = None
        nextloc_part = _part_of(telemetry_text, "NEXTLOC")
        if nextloc_part is not None:
            try:
                nextloc = float(nextloc_part.split(":", 1)[1])
            except ValueError:
                nextloc = None
        now_ms = self._clock() * 1000.0
        fields = None
        if part is not None:
            fields, _word = parse_part(part)
        locations = self._stalist_locations if self._stalist_locations is not None else []
        list_hash = self._stalist_list_id if (self._stalist_received and self._stalist_locations is not None) else None
        if fields is not None and fields.count == 0 and fields.list_id == EMPTY_LIST_ID:
            locations, list_hash = [], EMPTY_LIST_ID        # an empty list sends no STALIST at all: the sender's own statement "no stations" is the list
        elapsed = 0
        if fields is not None and (list_hash is None or fields.list_id != list_hash):
            if self._mismatch_since is None:
                self._mismatch_since = now_ms
            elapsed = now_ms - self._mismatch_since
        else:
            self._mismatch_since = None
        word = verdict(part, nextloc, locations, list_hash, elapsed, self.grace_ms, self._prev_arrseq)
        self._record(word, fields, scenario_id)
        return word

    def _record(self, word, fields, scenario_id):
        self.lines += 1
        self._final_written = False                          # (a line after finish(): the summary written by it is no longer the last word)
        self.verdict = word
        self.counts[word] = self.counts.get(word, 0) + 1
        self.last_fields = None if fields is None else fields.as_tuple()
        if scenario_id is not None:
            self.scenario_id = scenario_id
        if fields is not None and word in (V_OK, V_ARRSEQ_GAP):
            self._prev_arrseq = fields.arrseq
        scope_changed = False
        if word == V_OK:
            self.ready = True
            self.tgt_idx, self.arr_idx, self.arr_seq, self.count, self.list_id = fields.tgt, fields.arr, fields.arrseq, fields.count, fields.list_id
            scope = (self.scenario_id, fields.list_id, fields.count)
            if scope != self._scope:
                if self._scope is not None and self._scope[0] == scope[0]:
                    self.list_changes_in_scenario += 1
                self.list_generation += 1
                self._scope = scope
                scope_changed = True
        else:
            self.ready = False
            self.tgt_idx = self.arr_idx = self.arr_seq = self.count = NO_STATION
            self.list_id = ""
        why = []
        if word != self._logged_verdict:
            why.append(WHY_VERDICT)
        if scope_changed:
            why.append(WHY_SCOPE)
        progress = []
        if fields is not None:
            self._last_parsed = fields
            if self._seen is not None:
                if fields.tgt != self._seen.tgt:
                    self.tgt_changes += 1
                    progress.append(WHY_TGT)
                if fields.arrseq != self._seen.arrseq:
                    self.arrseq_changes += 1
                    progress.append(WHY_ARRSEQ)
                elif fields.arr != self._seen.arr:
                    self.arr_without_seq += 1
                    progress.append(WHY_ARR_ONLY)
            self._seen = fields
        self._logged_verdict = word
        if why:
            self._emit(word, fields, why + progress, False)
        elif progress:
            self._emit(word, fields, progress, True)
        if self.lines in SUMMARY_AT:
            self._summary(False)

    def _summary(self, final):
        """The `stidx-sum` lines of this generation. p=1: all lines / ok / NOT-READY / missing / other (violations) and the parse (pe), range (rg) and hash (hm)
        error counts, the numbers of tgt (nt) / arrseq (nq) changes and of arr changes without an arrseq (aa). p=2: the LAST values seen (the last part that could
        be parsed, whatever its verdict) with the verdict of the last line and the scenario id. Fixed words and numbers only. unavailable = miss + ntr, invalid = bad."""
        if self._log is None:
            return
        ok = self.counts.get(V_OK, 0)
        not_ready = self.counts.get(V_NOT_READY, 0)
        missing = self.counts.get(V_MISSING, 0)
        parse_errors = sum(self.counts.get(w, 0) for w in _PARSE_ERRORS)
        flag = 1 if final else 0
        try:
            self._log("stidx-sum", p=1, n=self.lines, ok=ok, ntr=not_ready, miss=missing, bad=self.lines - ok - not_ready - missing, gen=self.list_generation,
                      final=flag, pe=parse_errors, rg=self.counts.get(V_RANGE, 0), hm=self.counts.get(V_LIST_MISMATCH, 0), nt=self.tgt_changes, nq=self.arrseq_changes,
                      aa=self.arr_without_seq)
        except Exception:
            pass
        last = self._last_parsed
        values = {"p": 2, "n": self.lines, "gen": self.list_generation, "final": flag, "verdict": self.verdict,
                  "tgt": NO_STATION, "arr": NO_STATION, "seq": NO_STATION, "cnt": NO_STATION, "list": "none"}
        if last is not None:
            values.update({"tgt": last.tgt, "arr": last.arr, "seq": last.arrseq, "cnt": last.count, "list": last.list_id})
        if self.scenario_id is not None:
            values["scn"] = self.scenario_id
        try:
            self._log("stidx-sum", **values)
        except Exception:
            pass

    def _emit(self, word, fields, why, progress_only):
        if self._log is None:
            return
        if progress_only:
            if self.progress_events >= self.max_progress_events:
                self.progress_suppressed += 1
                return
            self.progress_events += 1
        else:
            if self.events >= self.max_events:
                self.events_suppressed += 1
                return
            self.events += 1
        values = {"verdict": word, "gen": self.list_generation, "n": self.lines, "why": "-".join(why)}
        if self.scenario_id is not None:
            values["scn"] = self.scenario_id
        if fields is not None:
            values.update({"tgt": fields.tgt, "arr": fields.arr, "seq": fields.arrseq, "cnt": fields.count, "list": fields.list_id})
        try:
            self._log("stidx", **values)
        except Exception:
            pass
