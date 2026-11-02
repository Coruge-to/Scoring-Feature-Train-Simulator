"""TB-I mutation harness: the timing screen cursor skips the fixed untimed rows; the basic brake rule boundary candidates keep the A and leave out the B of a crossed pair, and the A as a boundary starts the next rule at its B (Owner contract 3; new file; the existing harness files mut_tbf.py / mut_tbg.py / mut_tbh*.py are NOT modified).
usage: python mut_tbi.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test: tests/test_pt_tbi_cursor_candidates.py (CU / BI / IR) plus the existing candidate, timing and receiver groups.
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
MU, MN = "menu_ui.py", "main.py"
NEW_MODULES = ("test_pt_tbi_cursor_candidates", "test_pt_tbi_brake_chain")
NEW_CLASSES = ("A_TimingCursor", "B_BasicBrakeCandidates", "C_InitialAndRelaxationInheritance", "A_Candidates", "B_EffectiveRanges", "C_RuntimeAndScore")
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
LEFT = "        left_out = {p.departure for p in self.brake_chain_pairs()}        # the B of a crossed pair is no boundary; the A stays (the next rule then starts at its B)\n"
CHAIN_RET = "        return snapshot.pairs if snapshot is not None else turnback_crossed_pairs(self, getattr(self, 'setting_start_idx', 0), getattr(self, 'setting_end_idx', -1))\n"
MAPRET = "            if pair.arrival == boundary_idx:\n                return pair.departure\n"
RSTART = "                start = self.brake_boundary_next_start(stop)\n"
SIDX = "                        s_idx = getattr(self, 'setting_start_idx', 0) if sub_c == 0 else self.brake_boundary_next_start(rules[sub_c-1].get(\"end_idx\", -1))\n"
HELPER = "        return fn(r_idx)\n"
SITE9 = "r_start = sta_start if r_idx == 0 else get_sta_name(_brake_rule_start(self, r_idx))"
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
 ("TB-01", "the A of a crossed pair is left out again (the first reading)", [(MN, LEFT, "        left_out = {p.arrival for p in self.brake_chain_pairs()} | {p.departure for p in self.brake_chain_pairs()}\n")]),
 ("TB-02", "the B of a crossed pair stays a boundary candidate", [(MN, LEFT, "        left_out = set()\n")]),
 ("TB-04", "a station named B is left out (a name decides)", [(MN, RET, RET.replace('s["idx"] not in left_out]', 's["idx"] not in left_out and s["name"] != "B"]'))]),
 ("TB-05", "an open door leaves every station out (the door state decides)", [(MN, RET, RET.replace('s["idx"] not in left_out]', 's["idx"] not in left_out and not getattr(self, "bve_door", 0)]'))]),
 ("TB-06", "the terminal of the section is no candidate any more", [(MN, RET, RET.replace('s["idx"] <= e_overall', 's["idx"] < e_overall'))]),
 ("TB-07", "the first station after the section start is dropped from the window", [(MN, RET, RET.replace('s["idx"] > s_idx', 's["idx"] > s_idx + 1'))]),
 ("TB-08", "the boundary candidates are built inline again (a second generator)", [(MN, CALL, "                        valid_stas = []; valid_stas.append({\"idx\": 0})\n" + CALL)]),
 ("TB-09", "the initial / relaxation screen builds its own station candidates", [(MN, "if is_last and self.menu_state == 7:", "if is_last and self.menu_state in (7, 9):")]),
 ("TB-10", "the pairs of the settings are ignored (only the Run snapshot is read)", [(MN, CHAIN_RET, CHAIN_RET.replace("else turnback_crossed_pairs(self, getattr(self, 'setting_start_idx', 0), getattr(self, 'setting_end_idx', -1))", "else ()"))]),
 ("TC-01", "the A as a boundary starts the next rule at the A itself (no mapping)", [(MN, MAPRET, "            if pair.arrival == boundary_idx:\n                return boundary_idx\n")]),
 ("TC-02", "the A is mapped to a wrong station (arrival + 2)", [(MN, MAPRET, "            if pair.arrival == boundary_idx:\n                return pair.arrival + 2\n")]),
 ("TC-03", "the effective range ignores the mapping (start = the boundary)", [(MN, RSTART, "                start = stop\n")]),
 ("TC-04", "the next boundary candidates start at the plain boundary (the old s_idx)", [(MN, SIDX, "                        s_idx = getattr(self, 'setting_start_idx', 0) if sub_c == 0 else rules[sub_c-1].get(\"end_idx\", -1)\n")]),
 ("TC-05", "the screens draw the plain boundary of the previous rule (all four screens)", [(MU, HELPER, "        return getattr(self, 'brake_rules', [])[r_idx - 1][\"end_idx\"]\n")]),
 ("TC-06", "the initial / relaxation screen draws the plain boundary", [(MU, SITE9, "r_start = sta_start if r_idx == 0 else get_sta_name(getattr(self, 'brake_rules', [])[r_idx-1][\"end_idx\"])")]),
 ("TC-07", "a name decides which station is an A (the mapping reads the name)", [(MN, MAPRET, "            if pair.arrival == boundary_idx or self.station_list[boundary_idx].get('name') == 'A':\n                return pair.departure\n")]),
 ("TC-08", "the pairs of the chain are read from the settings only (the Run snapshot is ignored)", [(MN, CHAIN_RET, "        return turnback_crossed_pairs(self, getattr(self, 'setting_start_idx', 0), getattr(self, 'setting_end_idx', -1))\n")]),
 ("TC-09", "the ranges end with the sentinel instead of the section end", [(MN, "            out.append((start, end if stop == -1 else stop))\n", "            out.append((start, stop))\n")]),
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
