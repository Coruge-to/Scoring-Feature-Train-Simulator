"""TEST-ONLY oracle of the pseudo-turnback static recognition (PTS-0 Pair contract PQ-13). The PRODUCT never imports this: the Python application does not qualify pairs (PQ-P4);
the C# shared Qualifier does. This independent implementation is the oracle that the vectors are computed with and that the C# prototype is compared against.

A record is a 4-tuple of 0/1: (arrival_stated, departure_stated, raw_terminal, is_pass). Position in the list is the StationIndex. Nothing else is accepted."""
import re

TIME = re.compile(r'^\d{1,2}:\d{2}(:\d{2})?$')


def effective_terminal(records):
    if not records:
        return -1
    for i, r in enumerate(records):
        if r[2]:
            return i
    return len(records) - 1


def qualify(records):
    """-> list of (a, b, mode) with mode 0 = ContinueScoring, 1 = CompleteAfterJump."""
    n = len(records)
    if n == 0:
        return []
    t = effective_terminal(records)
    any_t = any(r[2] for r in records)
    out = []
    for a in range(1, n - 1):
        ra, rb = records[a], records[a + 1]
        a_ok = ra[0] and not ra[1] and not ra[3] and not ra[2] and a < t
        b_ok = (not rb[0]) and rb[1] and not rb[3] and not rb[2] and (a + 1) <= t
        if a_ok and b_ok:
            out.append((a, a + 1, 1 if (not any_t and a + 1 == n - 1) else 0))
    return out


def records_from_station_text(text):
    """Station list text -> records. Comments, blank lines and entirely empty records are removed BEFORE the StationIndex is assigned (Strict re-audit rule 7).
    Fields: key, name, arrival, departure, ...; arrival 'p' = pass, departure 't' = terminal; a time is stated when it looks like H:MM[:SS]."""
    lines = text.splitlines()
    out = []
    for line in lines[1:]:
        s = line.strip()
        if s == '' or s[0] in ';#' or s.startswith('//'):
            continue
        f = [x.strip() for x in line.split(',')]
        if all(x == '' for x in f):
            continue
        while len(f) < 6:
            f.append('')
        arr, dep = f[2], f[3]
        out.append((1 if TIME.match(arr) else 0, 1 if TIME.match(dep) else 0, 1 if dep.lower() == 't' else 0, 1 if arr.lower() == 'p' else 0))
    return out
