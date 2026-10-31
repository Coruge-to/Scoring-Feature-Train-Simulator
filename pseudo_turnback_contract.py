"""PR-1b prototype (clone only): the Python side of the PTPAIR key (PTS-0 PTPAIR addendum XL-PT-2 / XL-PT-4): DECODE and VALIDATE only.

This module NEVER qualifies a pair. It has no function that builds a pair from a station list, a name, a position or a distance (PQ-P4). The key is judged as a whole: one violation
invalidates all of it, and no partial set is ever returned. Fixed reason words only (they contain no value). Pure: no Qt, no Win32, no socket, no file, no clock.

decode_ptpair(text, expected_station_count) -> (PairSet, None) | (None, reason). expected_station_count < 0 skips that check.
Absent key, zero pairs and an invalid key are three different things for the caller: absent = `None` is never passed here; zero pairs = a valid empty set; invalid = (None, reason)."""
from typing import NamedTuple, Tuple

KEY = "PTPAIR"
VERSION = 1
EMPTY_LIST_ID = "00000000"
CONTINUE = 0
COMPLETE_AFTER_JUMP = 1

R_PARTS = "parts"
R_VERSION = "version"
R_LIST_ID = "list-id"
R_INTEGER = "integer"
R_COUNT = "count-mismatch"
R_STATION_COUNT = "station-count"
R_MODE = "mode"
R_RANGE = "range"
R_ORDER = "order"
R_OVERLAP = "overlap"
R_FINAL = "final-structure"
R_LIMIT = "limit"


class Pair(NamedTuple):
    arrival: int
    departure: int
    mode: int


class PairSet(NamedTuple):
    list_id: str
    station_count: int
    pairs: Tuple[Pair, ...]


def _canonical_int(s):
    if not s or len(s) > 9 or (len(s) > 1 and s[0] == '0') or not all('0' <= c <= '9' for c in s):
        return None
    return int(s)


def _is_hash(s):
    return len(s) == 8 and all(c in "0123456789abcdefABCDEF" for c in s)


def validate(station_count, pairs):
    """None when the set is valid, else the reason word. The SAME rules as the C# PseudoTurnbackPairSet.TryCreate (PQ-4)."""
    if station_count < 0:
        return R_RANGE
    if not pairs:
        return None
    if station_count == 0:
        return R_RANGE
    if len(pairs) > (station_count - 1) // 2:
        return R_LIMIT
    previous_b = -1
    finals = 0
    for i, p in enumerate(pairs):
        if p.mode not in (CONTINUE, COMPLETE_AFTER_JUMP):
            return R_MODE
        if p.arrival < 1 or p.departure != p.arrival + 1 or p.departure >= station_count:
            return R_RANGE
        if i > 0 and p.arrival < previous_b:
            return R_ORDER
        if i > 0 and p.arrival <= previous_b:
            return R_OVERLAP
        previous_b = p.departure
        if p.mode == COMPLETE_AFTER_JUMP:
            finals += 1
            if i != len(pairs) - 1 or p.departure != station_count - 1:
                return R_FINAL
    if finals > 1:
        return R_FINAL
    return None


def decode_ptpair(text, expected_station_count=-1):
    try:
        if not isinstance(text, str):
            return None, R_PARTS
        p = text.split(':')
        if len(p) != 6 or p[0] != KEY:
            return None, R_PARTS
        if p[1] != "1":
            return None, R_VERSION
        if not _is_hash(p[2]):
            return None, R_LIST_ID
        station_count, pair_count = _canonical_int(p[3]), _canonical_int(p[4])
        if station_count is None or pair_count is None:
            return None, R_INTEGER
        if station_count == 0 and p[2] != EMPTY_LIST_ID:
            return None, R_LIST_ID
        if expected_station_count >= 0 and station_count != expected_station_count:
            return None, R_STATION_COUNT
        pairs = []
        if p[5]:
            for entry in p[5].split(';'):
                f = entry.split('-')
                if len(f) != 3:
                    return None, R_PARTS
                a, b, m = _canonical_int(f[0]), _canonical_int(f[1]), _canonical_int(f[2])
                if a is None or b is None or m is None:
                    return None, R_INTEGER
                if m not in (0, 1):
                    return None, R_MODE
                pairs.append(Pair(a, b, m))
        if len(pairs) != pair_count:
            return None, R_COUNT
        why = validate(station_count, pairs)
        if why is not None:
            return None, why
        return PairSet(p[2].upper(), station_count, tuple(pairs)), None
    except Exception:
        return None, R_PARTS
