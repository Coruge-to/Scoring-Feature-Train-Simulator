"""Stage TB-E: the RoutePairSet intake of the Python side. The certified, STATIC pair set of the CURRENT scenario generation (every pseudo-turnback pair A -> B of the route) as the C# Qualifier published it
on the telemetry line (PTPAIR:1:<list_id>:<station_count>:<pair_count>:<entries>, PTS-0 XL-PT).

This module JUDGES what it is given; it never qualifies a pair (OD-TE-6): it has no input from which a pair could be derived (no station, no name, no position, no distance, no door, no signal flag), it
decodes with pseudo_turnback_contract (the validation mirror of the C# rules) and keeps the answer. The three states are kept apart (OD-TE-4): UNAVAILABLE (nothing accepted for this generation: the sender
stated nothing yet, the key was invalid, or the state was invalidated), READY_EMPTY (the sender stated: zero pairs) and READY_NONEMPTY. The generation is the SCENARIO_ID of the line that carried the key
(received) against the Overlay's current scenario id (current) (OD-TE-3). The run-specific set (machine.fixed) is NOT touched here: it is fixed once by the scoring start button (TB-C / TB-D).

Pure holder; the functions below the holder only connect it to the Overlay (the attribute `route_pairset`, the machine's pair set, the diagnostic sink)."""
import hashlib
import re

import pseudo_turnback_contract as contract

UNAVAILABLE = "UNAVAILABLE"
READY_EMPTY = "READY_EMPTY"
READY_NONEMPTY = "READY_NONEMPTY"

ACCEPTED = "accepted"          # the key was judged valid and is now the state of this binding
UNCHANGED = "unchanged"        # nothing to judge (no key) or the very same text again: nothing changed
REJECTED = "rejected"          # the key was not adopted; the previous state, if any, is kept

R_ABSENT = "absent"
R_SAME = "same"
R_STALE_GENERATION = "stale-generation"
R_AHEAD_GENERATION = "ahead-generation"
R_UNKNOWN_GENERATION = "unknown-generation"
R_NO_LIST = "no-station-list"
R_LIST_ID = contract.R_LIST_ID
R_CONFLICT = "conflict"

KEY_PREFIX = contract.KEY + ":"
SCENARIO_PREFIX = "SCENARIO_ID:"
ATTRIBUTE = "route_pairset"

# -- the diagnostic contract (Stage TB-E 1.1, OD-TE2-R3). An event carries FIXED WORDS AND NUMBERS ONLY: the protocol version, the received / current generation, the list id and the station count of the
# adopted list, the declared / received / parsed pair counts of the payload, the state, the accepted pair count, the rejection reason, whether the existing state was preserved, and a SAFE summary of the payload
# (its length, the version it states, its list id in the one safe form, its station count, its declared and parsed pair counts and a short fingerprint). The raw payload, a station name, a control character or
# an unbounded string never enters an event: every value below is an int, a word of the fixed vocabulary, an 8-digit hex id or an 8-digit hex fingerprint.
SAFE_LIST_ID = re.compile(r"\A[0-9A-Fa-f]{8}\Z")      # the one safe list id form (the CRC-32 of the station list, 8 hex digits)
NO_ID = "-"                                           # a missing or unsafe id / fingerprint
NO_NUMBER = -1                                        # a missing or unsafe number
FINGERPRINT_LENGTH = 8                                # hex digits of the SHA-256 prefix
FINGERPRINT_INPUT_LIMIT = 4096                        # at most this many characters of the payload are hashed
ENTRY_LIMIT = 4096                                    # at most this many entries are counted / parsed for the summary
DIGIT_LIMIT = 9                                       # canonical numbers of the wire have at most this many digits
PRESERVED = "true"
NOT_PRESERVED = "false"


def safe_id(value):
    """The list id in its safe form (8 hex digits, upper case) or NO_ID. Nothing else ever passes."""
    if isinstance(value, str) and SAFE_LIST_ID.match(value):
        return value.upper()
    return NO_ID


def safe_number(value):
    """A plain non-negative int of at most DIGIT_LIMIT digits, else NO_NUMBER (a bool is no number)."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10 ** DIGIT_LIMIT:
        return value
    return NO_NUMBER


def _generation(value):
    """A generation as the event states it: a plain int of a bounded size, else None (never a bool, a string or a huge number)."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) < 10 ** 12:
        return value
    return None


def _digits(text):
    if isinstance(text, str) and 0 < len(text) <= DIGIT_LIMIT and all("0" <= c <= "9" for c in text):
        return int(text)
    return NO_NUMBER


def fingerprint(text):
    """A short, one-way fingerprint of the payload (the first 8 hex digits of the SHA-256 of at most FINGERPRINT_INPUT_LIMIT characters), NO_ID when there is no text."""
    if not isinstance(text, str):
        return NO_ID
    data = text[:FINGERPRINT_INPUT_LIMIT].encode("utf-8", "backslashreplace")
    return hashlib.sha256(data).hexdigest()[:FINGERPRINT_LENGTH].upper()


def summarize(text):
    """The SAFE summary of one payload (never the payload itself): len = its length, ver = the version it states, list_id = its list id in the safe form, stations / declared = the numbers it states,
    received = how many entries it carries, parsed = how many of them are well formed (a pair of three canonical numbers), fp = the fingerprint. Judges nothing and never raises."""
    summary = {"len": NO_NUMBER, "ver": NO_NUMBER, "list_id": NO_ID, "stations": NO_NUMBER, "declared": NO_NUMBER, "received": NO_NUMBER, "parsed": NO_NUMBER, "fp": NO_ID}
    try:
        if not isinstance(text, str):
            return summary
        summary["len"] = min(len(text), 10 ** DIGIT_LIMIT - 1)
        summary["fp"] = fingerprint(text)
        parts = text.split(":", 5)
        if parts[0] != contract.KEY:
            return summary
        if len(parts) > 1:
            summary["ver"] = _digits(parts[1])
        if len(parts) > 2:
            summary["list_id"] = safe_id(parts[2])
        if len(parts) > 3:
            summary["stations"] = _digits(parts[3])
        if len(parts) > 4:
            summary["declared"] = _digits(parts[4])
        if len(parts) > 5:
            entries = parts[5]
            received = parsed = 0
            if entries:
                for entry in entries.split(";", ENTRY_LIMIT)[:ENTRY_LIMIT]:
                    received += 1
                    fields = entry.split("-", 3)
                    if len(fields) == 3 and all(_digits(f) != NO_NUMBER for f in fields):
                        parsed += 1
            summary["received"] = received
            summary["parsed"] = parsed
    except Exception:
        pass
    return summary


def capture(parts):
    """(received generation, key text) of one telemetry line given as its comma-split parts, or None when the line carries no key. The generation is the SCENARIO_ID of the SAME line (None when it can not be read)."""
    text = None
    generation = None
    for part in parts:
        if text is None and part.startswith(KEY_PREFIX):
            text = part
        elif generation is None and part.startswith(SCENARIO_PREFIX):
            try:
                generation = int(part[len(SCENARIO_PREFIX):])
            except ValueError:
                generation = None
    if text is None:
        return None
    return generation, text


class RoutePairSetHolder(object):
    def __init__(self):
        self.accepted = 0
        self.last_event = None
        self.last_reason = None
        self._last_rejection = None
        self._reset()

    def _reset(self):
        self.state = UNAVAILABLE
        self.generation = None
        self.list_id = None
        self.station_count = None
        self.pairset = None
        self.text = None

    def invalidate(self, reason):
        """The binding ends (a new scenario instance / generation, another station list, session off, shutdown): nothing of the old set remains."""
        self._reset()
        self.last_reason = reason
        self._last_rejection = None
        self._note(None, None, reason, None, None, None, ACCEPTED)

    def _note(self, received, current, why, text, list_id, station_count, verdict):
        """Builds the event of one judgement (fixed words and numbers only; see the diagnostic contract above). `preserved` = a state accepted earlier was kept as it was (never true for an acceptance or
        an invalidation, never true when nothing had been accepted)."""
        summary = summarize(text)
        self.last_event = {
            "ver": contract.VERSION,
            "rx": _generation(received), "cur": _generation(current),
            "list_id": safe_id(list_id), "stations": safe_number(station_count),
            "declared": summary["declared"], "received": summary["received"], "parsed": summary["parsed"],
            "state": self.state,
            "pairs": 0 if self.pairset is None else len(self.pairset.pairs),
            "why": why,
            "preserved": PRESERVED if (verdict in (UNCHANGED, REJECTED) and self.state != UNAVAILABLE) else NOT_PRESERVED,
            "summary": summary}

    def _result(self, verdict, why, received, current, text=None, list_id=None, station_count=None):
        self.last_reason = why
        self._note(received, current, why, text, list_id, station_count, verdict)
        return verdict, why

    def offer(self, received_generation, current_generation, text, list_id, station_count, pair_check=None):
        """Judges one line's key. Returns (verdict, reason word). `text` None = the line carries no key (nothing is judged and nothing is dropped: one line without the key does not end a ready state)."""
        def result(verdict, why):
            return self._result(verdict, why, received_generation, current_generation, text, list_id, station_count)
        if text is None:
            return result(UNCHANGED, R_ABSENT)
        if not isinstance(received_generation, int) or isinstance(received_generation, bool) or not isinstance(current_generation, int):
            return result(REJECTED, R_UNKNOWN_GENERATION)
        if received_generation < current_generation:
            return result(REJECTED, R_STALE_GENERATION)
        if received_generation > current_generation:
            return result(REJECTED, R_AHEAD_GENERATION)
        if not list_id or not isinstance(station_count, int) or station_count <= 0:
            return result(REJECTED, R_NO_LIST)
        same_binding = (self.state != UNAVAILABLE and self.generation == received_generation
                        and self.list_id == list_id and self.station_count == station_count)
        if same_binding:
            if text == self.text:
                return result(UNCHANGED, R_SAME)
            decoded, why = contract.decode_ptpair(text, station_count)
            if decoded is None:
                return result(REJECTED, why)
            return result(REJECTED, R_CONFLICT)
        decoded, why = contract.decode_ptpair(text, station_count)
        if decoded is None:
            return result(REJECTED, why)
        if decoded.list_id != str(list_id).upper():
            return result(REJECTED, R_LIST_ID)
        if pair_check is not None:
            # Stage P1 (Owner contract): the REQUIRED times of a certified pair (A arrival, B departure) are judged by the caller's check (this module still reads no station): a violation is the fixed reason word of the
            # check and the set is NOT adopted (fail closed: no managed scoring start on it)
            violation = pair_check(decoded)
            if violation is not None:
                return result(REJECTED, violation)
        self.state = READY_NONEMPTY if decoded.pairs else READY_EMPTY
        self.generation = received_generation
        self.list_id = str(list_id)
        self.station_count = station_count
        self.pairset = decoded
        self.text = text
        self.accepted += 1
        return result(ACCEPTED, self.state)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
# the connection to the Overlay
def holder_of(overlay):
    holder = overlay.__dict__.get(ATTRIBUTE)
    if holder is None:
        holder = RoutePairSetHolder()
        overlay.__dict__[ATTRIBUTE] = holder
    return holder


def state_of(overlay):
    holder = overlay.__dict__.get(ATTRIBUTE)
    return UNAVAILABLE if holder is None else holder.state


def _emit(overlay, holder):
    event = holder.last_event
    sink = getattr(overlay, "_emit_input_event", None)
    if event is None or sink is None:
        return
    summary = event["summary"]
    try:
        sink("routepairset", ver=event["ver"], rx=-1 if event["rx"] is None else event["rx"], cur=-1 if event["cur"] is None else event["cur"],
             list_id=event["list_id"], stations=event["stations"], declared=event["declared"], received=event["received"], parsed=event["parsed"],
             state=event["state"], pairs=event["pairs"], why=event["why"], preserved=event["preserved"],
             p_len=summary["len"], p_ver=summary["ver"], p_list_id=summary["list_id"], p_stations=summary["stations"], p_fp=summary["fp"])
    except Exception:
        pass


def _release_pairset(overlay):
    """The machine no longer holds a pair set (the candidate lists and the arrival judgement read it there); the Run-specific set and the chain are dropped with it."""
    machine = overlay.__dict__.get("turnback_machine")
    if machine is not None:
        machine.set_pairset(None)
        machine.discard_all()


def clear(overlay, reason):
    """Invalidates the state (new scenario instance / generation, session off, shutdown, an internal failure). Nothing is carried over."""
    holder = overlay.__dict__.get(ATTRIBUTE)
    if holder is None:
        return
    was = holder.state
    holder.invalidate(reason)
    _release_pairset(overlay)
    if was != UNAVAILABLE:
        _emit(overlay, holder)


def sync(overlay, machine_of, pair_check=None):
    """After a telemetry line was applied and its station list adopted: judges the key of that line (`overlay._ptpair_raw`, set by apply_telemetry_text) against the adopted list and the current generation, and
    hands a NEW non-empty set to the machine. `machine_of` creates the machine on first use (scoring_logic.turnback_machine_of); an empty or unavailable state never creates one."""
    holder = holder_of(overlay)
    station_list = getattr(overlay, "station_list", None)
    list_id = getattr(station_list, "list_id", None) or getattr(overlay, "bve_list_id", "")
    count = len(station_list) if station_list else 0
    raw = overlay.__dict__.get("_ptpair_raw")
    current = getattr(overlay, "current_scenario_id", -1)
    if holder.state != UNAVAILABLE and (holder.list_id != list_id or holder.station_count != count):
        holder.invalidate("list-changed")
        _release_pairset(overlay)
        _emit(overlay, holder)
    if raw is None:
        verdict, why = holder.offer(None, current, None, list_id, count)
    else:
        verdict, why = holder.offer(raw[0], current, raw[1], list_id, count, pair_check)
    if verdict == ACCEPTED:
        if holder.state == READY_NONEMPTY:
            machine_of(overlay).set_pairset(holder.pairset)
            _normalise_choice(overlay, holder.pairset)
        _emit(overlay, holder)
    else:
        # a rejection is said once per (reason, payload fingerprint): the same payload again is no new news (no flood), another payload with the same reason is
        rejection = (why, holder.last_event["summary"]["fp"]) if verdict == REJECTED else None
        if rejection is not None and rejection != holder._last_rejection:
            _emit(overlay, holder)
        holder._last_rejection = rejection
        return verdict, why
    holder._last_rejection = None
    return verdict, why


def _normalise_choice(overlay, pairset):
    """A start or end chosen BEFORE the set arrived (it can not be refused afterwards): the A of a pair is no start and the B of a pair is no end. Only outside a running scoring; the sentinel of the end is -1."""
    if getattr(overlay, "is_scoring_mode", False):
        return
    if getattr(overlay, "setting_start_idx", 0) in {p.arrival for p in pairset.pairs}:
        overlay.setting_start_idx = 0
    if getattr(overlay, "setting_end_idx", -1) in {p.departure for p in pairset.pairs}:
        overlay.setting_end_idx = -1
