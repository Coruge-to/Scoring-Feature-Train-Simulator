"""Phase SI-R5.1 - the GLOBAL CLOSE GUARD of StationIndex Season 2: no product path selects a station identity, a target or a NEXTLOC by a distance.

NOT a discovery test (the name starts with red_): run it as   python -B tests/red_si_r5_global_close_guard.py [result.tsv]
    RED    must FAIL on fd431b4 (it finds the five 1 m reverse lookups of scoring_logic.py) and pass when the last of them is gone (SI-R5.2-C)
    GUARD  must PASS on fd431b4 and after: the detector itself (positive and negative samples), the empty Python allow-list, the narrow C# allow-list

THE DETECTOR (lexical and conservative: dead code is scanned like live code; it needs no call graph):
    F1  a loop / comprehension / generator over a station list whose body or condition COMPARES a station's ["location"] / .get("location")   (the 1 m lookup in every spelling, next(...) included)
    F2  min / max / sorted with key= that reads a station location                                                                             (the nearest station)
    F3  <station list>.index(...)                                                                                                              (the position -> index helper)
    F4  a def or a call named like nearest / by_position / by_loc / find_station / station_at                                                  (a helper that selects by position)
    F5  abs(<station>["location"] - x) compared with a constant in 0.1 .. 1.0 (0.01 m is the verification tolerance)                                                                          (the five old lines, also outside a loop)
NOT flagged, by shape and not by an allow-list: the physical judgement of a train against an already chosen station (abs(dist_to_stop) <= margin, the stop range, the CloseRange
anchor expression), the VERIFICATION of an index by a position (station_identity.locations_agree), the scan by a FLAG (is_terminal, is_pass), index-first reads (station_list[i]["location"]).
THE PYTHON ALLOW-LIST IS EMPTY. THE C# ALLOW-LIST IS THE FOUR DOOR-FLAG LINES BELOW (an exact text, never a line number; widening it is an Owner decision).
Scope: the Python product = every *.py outside tests/ (and outside the C# tree); the C# product = every *.cs of TsScoringPlugin outside Handshake/Tests and Handshake/Probes.
"""
import ast
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ALLOW_PY = {}                         # (file, finding) -> reason ; EMPTY on purpose
ALLOW_CS = (                          # the physical judgements of the DOOR FLAG on an already chosen index (Current: Class1.cs ; Legacy: LegacyStationTimeline.cs)
    "hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(stationList[requestedStationIndex].Location - location) < 50.0;",
    "if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0) hasDoorOpenedAtTarget = true;",
    "if (!areDoorsClosed && Math.Abs(nextStationLoc - location) < 100.0)",
    "hasDoorOpenedAtTarget = !areDoorsClosed && Math.Abs(list[index].Location - location) < 50.0;",
)
_TMP = {}


def case(kind, req, group="CORE"):
    assert kind in ("RED", "GUARD")

    def deco(fn):
        fn.rc = {"kind": kind, "req": req, "group": group, "note": ""}
        return fn
    return deco


def contract(cond, why):
    if not cond:
        raise AssertionError("CONTRACT: " + why)


# ------------------------------------------------------------------------------------------------------------------------------------------------
# the detector
# ------------------------------------------------------------------------------------------------------------------------------------------------
NAME_PAT = re.compile(r"(nearest|by_position|by_loc\b|find_station|station_at)", re.I)


def _is_location_read(node):
    """station["location"] / station.get("location")"""
    if isinstance(node, ast.Subscript):
        sl = node.slice
        return isinstance(sl, ast.Constant) and sl.value == "location"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        a = node.args[0]
        return isinstance(a, ast.Constant) and a.value == "location"
    return False


def _reads_location(node):
    return any(_is_location_read(n) for n in ast.walk(node))


def _compares_location(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Compare) and _reads_location(n):
            return True
    return False


def _station_iter(node):
    return "station" in ast.unparse(node).lower()


def scan_python(text, filename="<sample>"):
    tree = ast.parse(text)
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.For) and _station_iter(n.iter):
            if any(_compares_location(s) for s in n.body):
                found.append(("F1", n.lineno))
        elif isinstance(n, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
            for g in n.generators:
                if _station_iter(g.iter) and (any(_compares_location(c) for c in g.ifs) or (hasattr(n, "elt") and _compares_location(n.elt))):
                    found.append(("F1", n.lineno))
        elif isinstance(n, ast.Call):
            fname = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")
            if fname in ("min", "max", "sorted"):
                for kw in n.keywords:
                    if kw.arg == "key" and (_reads_location(kw.value) or "location" in ast.unparse(kw.value).lower()):
                        found.append(("F2", n.lineno))
            if isinstance(n.func, ast.Attribute) and n.func.attr == "index" and "station" in ast.unparse(n.func.value).lower():
                found.append(("F3", n.lineno))
            if NAME_PAT.search(fname):
                found.append(("F4", n.lineno))
        elif isinstance(n, ast.FunctionDef) and NAME_PAT.search(n.name):
            found.append(("F4", n.lineno))
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Call) and getattr(n.left.func, "id", "") == "abs" and len(n.comparators) == 1 \
                and isinstance(n.ops[0], (ast.Lt, ast.LtE)) and isinstance(n.comparators[0], ast.Constant) and isinstance(n.comparators[0].value, (int, float)) \
                and 0.1 <= n.comparators[0].value <= 1.0 and _reads_location(n.left):
            found.append(("F5", n.lineno))
    return sorted(set(found), key=lambda f: (f[1], f[0]))


def python_product_files():
    out = []
    for base, dirs, files in os.walk(ROOT):
        rel = os.path.relpath(base, ROOT)
        top = rel.split(os.sep)[0]
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "tests", "TsScoringPlugin", "docs", "node_modules")]
        if top in ("tests", "TsScoringPlugin", ".git"):
            continue
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(base, f))
    return sorted(out)


def cs_product_files():
    out = []
    base = os.path.join(ROOT, "TsScoringPlugin")
    for b, dirs, files in os.walk(base):
        rel = os.path.relpath(b, base).replace("\\", "/")
        if rel.startswith("Handshake/Tests") or rel.startswith("Handshake/Probes") or "/obj" in rel or "/bin" in rel or rel.startswith("obj") or rel.startswith("bin"):
            dirs[:] = []
            continue
        for f in files:
            if f.endswith(".cs"):
                out.append(os.path.join(b, f))
    return sorted(out)


CS_STATION_ABS = re.compile(r"Math\.Abs\(\s*(?:(?:[Ss]tation\w*|list|targetSt|st)\b[^()]*?\.Location|nextStationLoc|[\w\.]*[Ss]tationLoc\w*)\s*-")
CS_SELECT = re.compile(r"(FindIndex|OrderBy|\.Min\(|\.Max\(|Nearest\w*)\b.*Location")


def scan_cs(path):
    hits, selects = [], []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for no, line in enumerate(f, 1):
            s = line.strip()
            if s.startswith("//"):
                continue
            if CS_STATION_ABS.search(s):
                hits.append((no, s))
            if CS_SELECT.search(s):
                selects.append((no, s))
    return hits, selects


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-si-r5-guard-")


def tearDownModule():
    _TMP["dir"].cleanup()


POSITIVE = {
    "the five old lines": 'def f(self, station_list, p):\n    for i, st in enumerate(station_list):\n        if abs(st["location"] - p) < 1.0:\n            return i\n',
    "a genexpr with next": 'def f(self, p):\n    return next((i for i, s in enumerate(self.station_list) if abs(s["location"] - p) <= 1.0), -1)\n',
    "get spelling": 'def f(self, p):\n    for i, st in enumerate(self.station_list):\n        if st.get("location") == p:\n            return i\n',
    "a list comprehension": 'def f(self, p):\n    return [i for i, st in enumerate(station_list) if abs(st["location"] - p) < 50.0][0]\n',
    "min by distance": 'def f(self, p):\n    return min(self.station_list, key=lambda s: abs(s["location"] - p))\n',
    "sorted by distance": 'def f(self, p):\n    return sorted(stations, key=lambda s: abs(s["location"] - p))[0]\n',
    "index helper": 'def f(self, loc):\n    return [s["location"] for s in self.station_list].index(loc)\n',
    "a nearest helper": 'def nearest_station(self, p):\n    return 0\n',
    "a position helper call": 'def f(self):\n    return find_station_by_position(1.0)\n',
    "an abs line outside a loop": 'def f(st, p):\n    return abs(st["location"] - p) < 1.0\n',
}
NEGATIVE = {
    "the stop range of the chosen target": 'def f(self):\n    d = self.bve_next_loc - self.bve_location\n    return -self.bve_margin_f <= d <= self.bve_margin_b\n',
    "the margin judgement": 'def f(self, actual_margin):\n    return abs(self.bve_next_loc - self.bve_location) < actual_margin\n',
    "the CloseRange anchor expression": 'def f(self, anchor, stop_distance):\n    return self.bve_next_loc - self.bve_margin_b - anchor <= stop_distance\n',
    "index first, location verifies": 'def f(self, station_list, i, p):\n    return abs(station_list[i]["location"] - p) <= 0.01\n',
    "a scan by a flag": 'def f(self):\n    for i, station in enumerate(self.station_list):\n        if station.get("is_terminal", False):\n            return i\n    return -1\n',
    "a menu list by is_pass": 'def f(self):\n    return [{"idx": i} for i, s in enumerate(self.station_list) if not s.get("is_pass", False)]\n',
    "a door judgement on a known official target": 'def f(door, official_location, location):\n    return door != 0 and abs(official_location - location) < 100.0\n',
    "roll distance": 'def f(self):\n    return abs(self.bve_location - self.door_open_loc)\n',
}


class A_TheDetector(unittest.TestCase):
    @case("GUARD", "every positive sample is detected", "DETECTOR")
    def test_G_detector_finds_every_spelling(self):
        for name, text in POSITIVE.items():
            self.assertTrue(scan_python(text), name)

    @case("GUARD", "no negative sample (the legitimate physical judgements, the verification and the flag scans) is detected", "DETECTOR")
    def test_G_detector_does_not_flag_physical_judgements(self):
        for name, text in NEGATIVE.items():
            self.assertEqual(scan_python(text), [], name)

    @case("GUARD", "the Python allow-list is empty", "DETECTOR")
    def test_G_python_allow_list_is_empty(self):
        self.assertEqual(ALLOW_PY, {})

    @case("GUARD", "the CloseRange functions of the product are not flagged (they judge a chosen station physically)", "DETECTOR")
    def test_G_close_range_is_not_flagged(self):
        text = read(os.path.join(ROOT, "scoring_logic.py"))
        tree = ast.parse(text)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in ("close_range_pair_is_close", "update_close_range_departure_reset", "close_range_fix_previous_stop", "init_basic_braking_state"):
                self.assertEqual(scan_python(ast.get_source_segment(text, node)), [], node.name)

    @case("GUARD", "the verification helpers of station_identity.py are not flagged", "DETECTOR")
    def test_G_verification_is_not_flagged(self):
        self.assertEqual(scan_python(read(os.path.join(ROOT, "station_identity.py"))), [])

    @case("GUARD", "the scan covers every Python product file (a file cannot hide from it) and reads them all", "DETECTOR")
    def test_G_scope_is_the_whole_product(self):
        names = {os.path.basename(p) for p in python_product_files()}
        for must in ("scoring_logic.py", "main.py", "managed_input.py", "managed_hud.py", "station_identity.py", "hud_target_contract.py", "official_target_contract.py", "station_index_contract.py"):
            self.assertIn(must, names)
        for p in python_product_files():
            ast.parse(read(p))


class B_TheProduct(unittest.TestCase):
    def findings(self):
        out = []
        for p in python_product_files():
            for kind, line in scan_python(read(p), p):
                out.append((os.path.relpath(p, ROOT), kind, line))
        return out

    @case("RED", "GLOBAL CLOSE (Python): the product has NO distance-based station / target / NEXTLOC selection (HEAD: the five 1 m lookups of scoring_logic.py)", "PRODUCT")
    def test_R_python_product_has_no_distance_selection(self):
        found = self.findings()
        contract(not found, "%d finding(s): %s" % (len(found), ", ".join("%s %s:%d" % (f[0], f[1], f[2]) for f in found)))

    @case("GUARD", "every finding of the product today is one of the five old lines in scoring_logic.py (no sixth site, nothing in any other file)", "PRODUCT")
    def test_G_no_site_outside_the_five(self):
        found = self.findings()
        self.assertTrue(all(f[0] == "scoring_logic.py" for f in found), found)
        self.assertLessEqual(len([f for f in found if f[1] == "F5"]), 0, found)         # Phase SI-R5.2-A: P03 is gone (5 -> 4); SI-R5.2-B: P01, P04, P05 are gone (4 -> 1); SI-R5.2-C: P02 is gone (1 -> 0)

    @case("GUARD", "GLOBAL CLOSE (C#): the only station-position judgements are the four door-flag lines, and no C# product code selects a station by position", "PRODUCT")
    def test_G_cs_product_allow_list_is_exact(self):
        seen = []
        for p in cs_product_files():
            hits, selects = scan_cs(p)
            self.assertEqual(selects, [], "%s selects by position: %r" % (p, selects))
            for no, s in hits:
                seen.append(s)
        outside = sorted(set(s for s in seen if s not in ALLOW_CS))
        self.assertEqual(outside, [], "station-position judgements outside the allow-list")
        for s in ALLOW_CS:
            self.assertIn(s, seen, "allow-list entry not found: " + s)
        self.assertEqual(len(seen), 4, seen)

    @case("GUARD", "the test binder (Scene.bind: the test double of a READY sender) has only the allowed roles - it binds and keeps the indexes the caller names; no call at all, no loop, no search", "PRODUCT")
    def test_G_test_binder_has_only_the_allowed_roles(self):
        text = read(os.path.join(HERE, "si_r5_scene.py"))
        tree = ast.parse(text)
        binder = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "bind"]
        self.assertEqual(len(binder), 1)
        for n in ast.walk(binder[0]):
            self.assertNotIsInstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp, ast.Call, ast.Lambda), ast.dump(n)[:80])
        # the SI-R5 test files themselves contain none of the detector's shapes and do not use the rig's position default
        for name in ("si_r5_scene.py", "si_r5_char_scenarios.py", "red_si_r5_station_identity.py", "test_si_r5_characterization.py"):
            body = read(os.path.join(HERE, name))
            self.assertEqual(scan_python(body, name), [], name)
            self.assertNotIn("bind_identity(", body, name)

    @case("GUARD", "the old 5-line pin of the CloseRange fixture and the ST-4 pins are the only places that spell the old line outside the product", "PRODUCT")
    def test_G_old_line_is_spelled_only_in_pins(self):
        pat = re.compile(r'abs\(st\["location"\]\s*-\s*[\w\.\']+\)\s*<\s*1\.0')
        spelled = set()
        for f in os.listdir(HERE):
            if f.endswith(".py") and pat.search(read(os.path.join(HERE, f))):
                spelled.add(f)
        self.assertLessEqual(spelled, {"red_close_range_contract.py", "test_managed_input_sia3.py", "test_stationindex_canon_st2.py", "test_char_stop_door_source_pins_st0.py",
                                       "red_si_r5_global_close_guard.py", "red_si_r5_station_identity.py", "test_si_r5_characterization.py"})


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------------------------------------------------------------------------------
class _Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []

    def _row(self, test, outcome, detail):
        fn = getattr(test, test._testMethodName, None)
        rc = getattr(fn, "rc", {"kind": "?", "req": "", "group": "", "note": ""})
        kind = rc["kind"]
        if outcome == "pass":
            cls = "GUARD-OK" if kind == "GUARD" else "RED-INVALID"
        elif outcome == "fail":
            cls = ("RED-VALID" if kind == "RED" else "GUARD-BROKEN") if detail.startswith("CONTRACT:") else ("OLD-EXPECTATION" if kind == "RED" else "GUARD-BROKEN")
        elif outcome == "skip":
            cls = "SKIPPED"
        else:
            cls = "ERROR"
        self.rows.append((test._testMethodName, kind, rc["group"], rc["req"], outcome, cls, detail.replace("\t", " ").replace("\n", " | ")[:400]))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._row(test, "pass", "")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._row(test, "fail", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        self._row(test, "error", "%s: %s" % (err[0].__name__, err[1]))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._row(test, "skip", reason)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else None
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    res = _Result()
    suite.run(res)
    rows = sorted(res.rows, key=lambda r: r[0])
    lines = ["test\tkind\tgroup\trequirement\toutcome\tclassification\tdetail"] + ["\t".join(r) for r in rows]
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    counts = {}
    for r in rows:
        counts[r[5]] = counts.get(r[5], 0) + 1
    for r in rows:
        print("%-16s %-6s %-10s %s" % (r[5], r[1], r[2], r[0]))
    print("SUMMARY " + ", ".join("%s=%d" % kv for kv in sorted(counts.items())) + " total=%d" % len(rows))
    return 0 if all(r[5] in ("RED-VALID", "GUARD-OK") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
