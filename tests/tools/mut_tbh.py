"""TB-H mutation harness (new file; the existing harness files mut_tbf.py / mut_tbg.py ... are NOT modified).
usage: python mut_tbh.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test (Owner rulings R2 / R3 / R4 / R5 / R6 of 2026-11-01): the B of every crossed pair is untimed (UNTIMED_TURNBACK_B), scored 0 times, left out of the theoretical score and drawn untimed / not clickable;
a successful Retry of the current generation takes jump_lock at its settlement (layer A, independent of the contract).
Kinds:  required   must be KILLED
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
SL, MN, MU = "scoring_logic.py", "main.py", "menu_ui.py"
NEW_MODULES = ("test_pt_tbh_pairb_contract", "test_pt_tbh_retry_state")
NEW_CLASSES = ("A_Theory", "B_UntimedContract", "C_RetryToB", "D_F5", "E_TimingScreenRender", "F_C01ShapeTheory", "G_ProspectiveEqualsTheButton", "A_RetryLandingState", "B_RetryLockOwnership")   # the classes of the two new modules (run_red.py names tests by class)
MODS = list(NEW_MODULES) + ["test_pt_runtime_time_contract", "test_pt_tbd_retry", "test_pt_tbd_snapshot", "test_pt_tbd_timing_targets", "test_pt_tbg_landing_order", "test_pt_tbd_candidates",
                            "test_pt_tbc_completion", "test_pt_tbc_lifecycle", "test_close_range_entry_paths"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


UNTIMED_TB = "    if station_index in turnback_b_indexes(self):\n        return UNTIMED_TURNBACK_B\n"
LOCK_LINES = ("        if expectation.purpose == jump_transaction.JUMP_RETRY and tuple(expectation.scope)[0] == generation:\n"
              "            self.jump_lock = True")
# the three guards that read jump_lock for the landing at B (as mut_tbg.py)
OUTER_OLD = "            if not getattr(self, 'jump_lock', False) and not getattr(self, 'is_first_station', False):\n                # Phase SI-R5.2-B"
OUTER_NEW = "            if not getattr(self, 'is_first_station', False):\n                # Phase SI-R5.2-B"
STOP_OLD = "        if not getattr(self, 'jump_lock', False):\n            is_zero_stop = apply_stop_score(self, p_loc - self.bve_location, current_time)"
STOP_NEW = "        if True:\n            is_zero_stop = apply_stop_score(self, p_loc - self.bve_location, current_time)"
CP_OLD = "        if not getattr(self, 'jump_lock', False):\n            if not is_turnback_a:"
CP_NEW = "        if True:\n            if not is_turnback_a:"
MARK_OLD = "    self.has_scored_time_this_station = True\n    if not create_turnback_b_checkpoint(self, b_index, jump_time):"
MARK_NEW = "    self.has_scored_time_this_station = False\n    if not create_turnback_b_checkpoint(self, b_index, jump_time):"


def lock_line_with_comment():
    text, _ = read(os.path.join(ROOT, SL))
    text = text.replace("\r\n", "\n")
    i = text.index(LOCK_LINES)
    j = text.index("\n", text.index("self.jump_lock = True", i)) + 1
    return text[i:j]


LOCK_BLOCK = lock_line_with_comment()

# (id, meaning, [(file, old, new), ...])
M = [
 ("TH-01", "pair B untimed fixing removed: untimed_reason knows only the start (B is a timing station again)", [(SL, UNTIMED_TB, "")]),
 ("TH-02", "the two reasons are merged: the crossed B reports UNTIMED_SCORING_START", [(SL, "        return UNTIMED_TURNBACK_B\n", "        return UNTIMED_SCORING_START\n")]),
 ("TH-03", "the B stop position is mixed back into the real score: the arrival stop score ignores the landing lock (+500 at B)", [(SL, STOP_OLD, STOP_NEW)]),
 ("TH-04", "the B basic braking / whole arrival is mixed back: the outer, the stop and the checkpoint guards all ignore the lock", [(SL, OUTER_OLD, OUTER_NEW), (SL, STOP_OLD, STOP_NEW), (SL, CP_OLD, CP_NEW)]),
 ("TH-05", "the B operating time is mixed back: untimed removed AND the handled mark lost (the two defences of the departure)", [(SL, UNTIMED_TB, ""), (SL, MARK_OLD, MARK_NEW)]),
 ("TH-06", "the theoretical score counts pair B again (1300 per B)", [(MN, "                        if i in turnback_b:\n                            continue\n", "")]),
 ("TH-07", "the ordinary-station count n1 of the theoretical score keeps pair B (only the stop position stays in)", [(MN, "                        if i in turnback_b:\n                            continue\n", "                        if i in turnback_b:\n                            n1 += 1\n                            continue\n")]),
 ("TH-08", "the timing screen draws pair B as a timing station again (only the start is drawn untimed)", [(MU, "is_start = (self.untimed_reason(sta_idx) is not None) if hasattr(self, 'untimed_reason') else (sta_idx == getattr(self, 'setting_start_idx', 0))", "is_start = (sta_idx == getattr(self, 'setting_start_idx', 0))")]),
 ("TH-09", "the timing screen lets the user switch pair B (the toggle only protects the start)", [(MN, "                    if untimed_reason(self, sta_idx) is None:", "                    if sta_idx != getattr(self, 'setting_start_idx', 0):")]),
 ("TH-10", "the Retry takes no lock at its settlement (layer A deleted)", [(SL, LOCK_BLOCK, "")]),
 ("TH-11", "a Retry that did NOT succeed takes the lock too (the condition left the ok branch)", [(SL, LOCK_BLOCK, ""), (SL,
   "    else:\n        machine.landing_watch = None\n\n\ndef turnback_jump_available",
   "    else:\n        machine.landing_watch = None\n    if expectation.purpose == jump_transaction.JUMP_RETRY:\n        self.jump_lock = True\n\n\ndef turnback_jump_available")]),
 ("TH-12", "a Retry of a stale generation takes the lock (the generation test is gone)", [(SL, " and tuple(expectation.scope)[0] == generation:\n            self.jump_lock = True", ":\n            self.jump_lock = True")]),
 ("TH-13", "the lock is never released by the departure: B -> next station is not scored in the ordinary way", [(SL,
   "        if getattr(self, 'jump_lock', False):\n            self.jump_lock = False\n\n        self.is_first_station = False", "        if getattr(self, 'jump_lock', False):\n            pass\n\n        self.is_first_station = False")]),
 ("TH-14", "F5 / a new generation: the old snapshot (and with it the old pair B set) is still used", [(SL, "    if snapshot.generation != getattr(self, 'current_scenario_id', -1):\n        return None\n", "")]),
 ("TH-15", "the pair B set is re-derived from the settings during a Run (the fixed Run snapshot is not the source)", [(SL,
   "    pairs = snapshot.pairs if snapshot is not None else turnback_crossed_pairs(", "    pairs = turnback_crossed_pairs(")]),
 ("TH-16", "the Retry lock is taken only in the managed (Current) host: the common Python path of Legacy is broken", [(SL, LOCK_LINES, "        if expectation.purpose == jump_transaction.JUMP_RETRY and tuple(expectation.scope)[0] == generation and getattr(self, 'jump_client', None) is not None:\n            self.jump_lock = True")]),
 ("TH-17", "the start button fixes no pairs (the RunPairSet is empty)", [(SL, "    machine.fix_section(crossed, getattr(self, 'current_scenario_id', -1))", "    machine.fix_section((), getattr(self, 'current_scenario_id', -1))")]),
 ("TH-18", "before the start button the chosen section is not read (the timing screen and the theoretical score see no pair B)", [(SL,
   "else turnback_crossed_pairs(self, getattr(self, 'setting_start_idx', 0), getattr(self, 'setting_end_idx', -1))", "else ()")]),
 ("TH-19", "pair B is found by the station NAME (a station called B)", [(SL, UNTIMED_TB, "    if station_index in turnback_b_indexes(self) or str(self.station_list[station_index].get('name')) == 'B':\n        return UNTIMED_TURNBACK_B\n")]),
 ("TH-20", "a user override wins over the contract (the override is read before the reason)", [(MN,
   "        if untimed_reason(self, sta_idx) is not None:", "        if sta_idx in self.user_timing_overrides:\n            return self.user_timing_overrides[sta_idx]\n        if untimed_reason(self, sta_idx) is not None:")]),
 ("TH-21", "the all-stations toggle writes an override for pair B", [(MN,
   "            for idx in targets:\n                if untimed_reason(self, idx) is not None: continue\n                if not getattr", "            for idx in targets:\n                if idx == getattr(self, 'setting_start_idx', 0): continue\n                if not getattr")]),
 ("TH-23", "the pure helper decides differently from the start button (the terminal-B end sentinel is not resolved in turnback_crossed_pairs)", [(SL,
   "        if resolved != terminal and resolved > start:\n            explicit_end = resolved\n        else:\n            resolved = terminal\n    else:\n        resolved = explicit_end\n    list_id = getattr(station_list, 'list_id', None) or getattr(self, 'bve_list_id', \"\")\n    return tuple(p for p in machine.pairset.pairs\n                 if pseudo_turnback_machine.qualifying_pair(machine.pairset, p.arrival, list_id, len(station_list), start, resolved, explicit_end) is not None)\n\n\nUNTIMED_SCORING_START",
   "        if resolved != terminal and resolved > start:\n            pass\n        resolved = terminal\n    else:\n        resolved = explicit_end\n    list_id = getattr(station_list, 'list_id', None) or getattr(self, 'bve_list_id', \"\")\n    return tuple(p for p in machine.pairset.pairs\n                 if pseudo_turnback_machine.qualifying_pair(machine.pairset, p.arrival, list_id, len(station_list), start, resolved, explicit_end) is not None)\n\n\nUNTIMED_SCORING_START")]),
 ("TH-22", "the initial-setting buttons read pair B as a user change", [(MU,
   "        is_untimed_by_contract = (lambda i: self.untimed_reason(i) is not None) if hasattr(self, 'untimed_reason') else (lambda i: i == s_idx)", "        is_untimed_by_contract = (lambda i: i == s_idx)")]),
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
