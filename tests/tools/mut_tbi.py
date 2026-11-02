"""TB-I Stage 8 mutation harness: the timing screen cursor skips the fixed untimed rows; the basic brake rule boundary candidates leave out the A and the B of a crossed pair (new file; the existing harness files mut_tbf.py / mut_tbg.py / mut_tbh*.py are NOT modified).
usage: python mut_tbi.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test: tests/test_pt_tbi_cursor_candidates.py (CU / BI / IR) plus the existing candidate, timing and receiver groups.
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
MU, MN = "menu_ui.py", "main.py"
NEW_MODULES = ("test_pt_tbi_cursor_candidates",)
NEW_CLASSES = ("A_TimingCursor", "B_BasicBrakeCandidates", "C_InitialAndRelaxationInheritance")
MODS = list(NEW_MODULES) + ["test_pt_tbd_candidates", "test_pt_tbh_pairb_contract", "test_pt_tbh_bulk_timing_button", "test_pt_tbd_timing_targets", "test_pt_tbe_receiver"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


STOPS = "        stops = [p for p in range(len(targets)) if untimed_reason(self, targets[p]) is None]\n        stops.append(len(targets))\n"
SHOW_FIRST = "        if cursor == self._timing_cursor_stops()[0]:\n            self.timing_scroll = 0\n"
SHOW_DOWN = "                self.timing_scroll = cursor - 6 + 1\n"
UP = "                self.timing_cursor = before[-1]\n"
DOWN = "                self.timing_cursor = after[0]\n"
OPEN = "                self.timing_cursor = self._timing_cursor_stops()[0]         # Stage TB-I: the first row the cursor may stop on (the done button when no station is changeable)\n"
ZONE = "                if not is_start:                                                                      # Stage TB-I: a fixed untimed row takes no click at all (the cursor never stops on it)\n"
LEFT = "        left_out = {p.arrival for p in pairs} | {p.departure for p in pairs}\n"
CROSSED = "turnback_crossed_pairs(self, getattr(self, 'setting_start_idx', 0), getattr(self, 'setting_end_idx', -1))"
RET = '        return [s for s in self._scoring_candidate_stations() if s["idx"] > s_idx and s["idx"] <= e_overall and s["idx"] not in left_out]\n'
CALL = "                        opts = self._brake_end_candidates(s_idx)                 # Stage TB-I: the A and the B of a crossed pair are no boundary\n"

# (id, meaning, [(file, old, new), ...])
M = [
 ("TI-01", "the cursor stops on the fixed untimed rows too (the predicate is gone)", [(MN, STOPS, "        stops = [p for p in range(len(targets))]\n        stops.append(len(targets))\n")]),
 ("TI-02", "the screen opens on the old fixed row 1", [(MN, OPEN, "                self.timing_cursor = 1 if len(self.get_timing_target_stas()) > 1 else len(self.get_timing_target_stas())\n")]),
 ("TI-03", "down skips one stop too many", [(MN, DOWN, "                self.timing_cursor = after[0] + 1\n")]),
 ("TI-04", "up leaves the first stop to the row above it", [(MN, UP, "                self.timing_cursor = before[-1] - 1 if before[-1] == stops[0] else before[-1]\n")]),
 ("TI-05", "the scroll window is not moved down with the cursor", [(MN, SHOW_DOWN, "                pass\n")]),
 ("TI-06", "the first stop does not bring the list back to its top", [(MN, SHOW_FIRST, "        if False:\n            self.timing_scroll = 0\n")]),
 ("TI-07", "the done button is no stop (no changeable station: the list is empty)", [(MN, STOPS, "        stops = [p for p in range(len(targets)) if untimed_reason(self, targets[p]) is None]\n")]),
 ("TI-08", "the station-name click zone is also made for the fixed rows", [(MU, ZONE, "                if True:                                                                      # Stage TB-I: a fixed untimed row takes no click at all (the cursor never stops on it)\n")]),
 ("TI-09", "the stops are chosen by the timing state instead of the fixed reason", [(MN, STOPS, "        stops = [p for p in range(len(targets)) if self.is_station_timing(targets[p]) or untimed_reason(self, targets[p]) is None]\n        stops = [p for p in stops if untimed_reason(self, targets[p]) is None and p != 1]\n        stops.append(len(targets))\n")]),
 ("TB-01", "the A of a crossed pair stays a boundary candidate", [(MN, LEFT, "        left_out = {p.departure for p in pairs}\n")]),
 ("TB-02", "the B of a crossed pair stays a boundary candidate", [(MN, LEFT, "        left_out = {p.arrival for p in pairs}\n")]),
 ("TB-03", "every pair of the route is left out, not only the pairs of the section", [(MN, CROSSED, "turnback_crossed_pairs(self, 0, len(self.station_list) - 1)")]),
 ("TB-04", "a station named B is left out (a name decides)", [(MN, RET, RET.replace('s["idx"] not in left_out]', 's["idx"] not in left_out and s["name"] != "B"]'))]),
 ("TB-05", "an open door leaves every station out (the door state decides)", [(MN, RET, RET.replace('s["idx"] not in left_out]', 's["idx"] not in left_out and not getattr(self, "bve_door", 0)]'))]),
 ("TB-06", "the terminal of the section is no candidate any more", [(MN, RET, RET.replace('s["idx"] <= e_overall', 's["idx"] < e_overall'))]),
 ("TB-07", "the first station after the section start is dropped from the window", [(MN, RET, RET.replace('s["idx"] > s_idx', 's["idx"] > s_idx + 1'))]),
 ("TB-08", "the boundary candidates are built inline again (a second generator)", [(MN, CALL, "                        valid_stas = []; valid_stas.append({\"idx\": 0})\n" + CALL)]),
 ("TB-09", "the initial / relaxation screen builds its own station candidates", [(MN, "if is_last and self.menu_state == 7:", "if is_last and self.menu_state in (7, 9):")]),
 ("TB-10", "the left-out set is built only from the Run snapshot (the settings are ignored)", [(MN, "pairs = snapshot.pairs if snapshot is not None else " + CROSSED, "pairs = snapshot.pairs if snapshot is not None else ()")]),
]


def run():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TS_REPO=ROOT, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("RT_ROOT", None)
    r = subprocess.run([sys.executable, os.path.join(sys.argv[1], "run_red.py")] + MODS, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    bad = [l for l in r.stdout.splitlines() if l.startswith(("FAIL", "ERROR", "SUBFAIL"))]
    return bad, r.stdout, r.stderr[-300:]


only = sys.argv[3:] if len(sys.argv) > 3 else None
base_bad, out, err = run()
ran_tests = sum(1 for l in out.splitlines() if l.split(" ", 1)[0] in ("ok", "FAIL", "ERROR", "skip"))
print("BASELINE of the mutation modules: failing=%d (modules=%d) tests reported=%d" % (len(base_bad), len(MODS), ran_tests))
if base_bad:
    for b in base_bad[:10]:
        print("   ", b[:200])
    sys.exit(1)
survivors, na, killed = [], [], 0
for mid, meaning, edits in M:
    if only and not any(mid.startswith(o) for o in only):
        continue
    files = {}
    for f, old, new in edits:
        if f not in files:
            orig, crlf = read(os.path.join(ROOT, f))
            files[f] = [orig, crlf, orig.replace("\r\n", "\n")]
        text = files[f][2]
        if text.count(old) != 1:
            print("NOT-APPLICABLE %s (%s count=%d)" % (mid, f, text.count(old)))
            na.append(mid)
            files = None
            break
        files[f][2] = text.replace(old, new)
    if files is None:
        continue
    try:
        for f, (orig, crlf, text) in files.items():
            open(os.path.join(ROOT, f), "wb").write((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
        bad, out, err = run()
    finally:
        for f, (orig, crlf, text) in files.items():
            open(os.path.join(ROOT, f), "wb").write(orig.encode("utf-8"))
    n_new = sum(1 for b in bad if any((" " + c + ".") in b for c in NEW_CLASSES))
    n_old = len(bad) - n_new
    print("%-6s %s new=%d old=%d  %s" % (mid, "KILLED  " if bad else "SURVIVED", n_new, n_old, meaning[:120]))
    if bad:
        first_new = next((b for b in bad if any((" " + c + ".") in b for c in NEW_CLASSES)), None)
        first_old = next((b for b in bad if b is not first_new and not any((" " + c + ".") in b for c in NEW_CLASSES)), None)
        if first_new:
            print("      new e.g. " + first_new[:150])
        if first_old:
            print("      old e.g. " + first_old[:150])
        killed += 1
    else:
        survivors.append(mid)
print("KILLED %d SURVIVORS %s NOT-APPLICABLE %s" % (killed, survivors, na))
sys.exit(0 if not survivors and not na else 1)
