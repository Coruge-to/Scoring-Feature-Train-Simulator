"""TB-G C-01 mutation harness (new file; the existing harness files are NOT modified).
usage: python mut_tbg.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FIXED tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
The failing tests are split into  'new' = test_pt_tbg_landing_order  and  'old' = every other test of MODS.
Kinds:  required   must be KILLED (a defect of the contract)
        redundant  a guard that is redundant on its own because another guard of the same contract covers the path (adjudicated at the C-01 root-cause stage: M9 / M11); reported, never counted as a
                   survivor; the contract is checked by the mutant that removes BOTH guards (TG-05)
Per mutant the line is printed:  ID  KILLED/SURVIVED  old=<n> new=<n>   and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
SL, MN = "scoring_logic.py", "main.py"
NEW_MODULE = "test_pt_tbg_landing_order"
MODS = [NEW_MODULE, "test_pt_tbc_completion", "test_pt_tbc_lifecycle", "test_pt_tbd_retry", "test_pt_tbd_real_flow", "test_pt_tbc_od33_start_equivalence", "test_pt_tbc_section",
        "test_close_range_entry_paths"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


def fix_line_with_eol():
    text, _ = read(os.path.join(ROOT, SL))
    text = text.replace("\r\n", "\n")
    for line in text.split("\n"):
        if line.strip().startswith("self.jump_lock = True") and "TB-G C-01" in line:
            return line + "\n"
    raise SystemExit("the fix line is not in scoring_logic.py")


FIX = fix_line_with_eol()
NO_FIX = [(SL, FIX, "")]

# the three guards that read jump_lock for the landing at B (root-cause stage: M11 outer / M10 inner stop score / M9 inner checkpoint)
OUTER_OLD = "            if not getattr(self, 'jump_lock', False) and not getattr(self, 'is_first_station', False):\n                # Phase SI-R5.2-B"
OUTER_NEW = "            if not getattr(self, 'is_first_station', False):\n                # Phase SI-R5.2-B"
STOP_OLD = "        if not getattr(self, 'jump_lock', False):\n            is_zero_stop = apply_stop_score(self, p_loc - self.bve_location, current_time)"
STOP_NEW = "        if True:\n            is_zero_stop = apply_stop_score(self, p_loc - self.bve_location, current_time)"
CP_OLD = "        if not getattr(self, 'jump_lock', False):\n            if not is_turnback_a:"
CP_NEW = "        if True:\n            if not is_turnback_a:"
ABORT_OLD = "        self.has_scored_time_this_station = False\n        turnback_stop_scoring(self, fail)\n        return\n    machine.on_b_established(now_ms)"
ABORT_NEW = "        self.has_scored_time_this_station = False\n        return\n    machine.on_b_established(now_ms)"
DUP_OLD = "    if not create_turnback_b_checkpoint(self, b_index, jump_time):\n        self.has_scored_time_this_station = False\n        turnback_stop_scoring(self, fail)\n        return\n    machine.on_b_established(now_ms)"
IGNORE_NEW = "    create_turnback_b_checkpoint(self, b_index, jump_time)\n    machine.on_b_established(now_ms)"

# (id, kind, meaning, [(file, old, new), ...])
M = [
 ("TG-01", "required", "the lock is not taken at the Jump request (the fix line is missing)", NO_FIX),
 ("TG-02", "required", "the lock is taken with the wrong value (False)", [(SL, "    self.jump_lock = True       # TB-G C-01", "    self.jump_lock = False      # TB-G C-01")]),
 ("TG-03", "required", "the Current settlement absorbs the JUMP counter and the lock disappears (main.py, turnback Jump)", [(MN, "        self.last_jump_count = completed_jump_count\n",
   "        self.last_jump_count = completed_jump_count\n        if expectation.purpose == jump_transaction.JUMP_TURNBACK:\n            self.jump_lock = False\n")]),
 ("TG-04", "required", "the settlement record of the turnback Jump releases the lock (state owner wrong, scoring_logic.py)", [(SL,
   "    machine.settlement = pseudo_turnback_machine.Settlement(expectation.purpose, end, selected, actual, expectation.scope, origin, generation, expectation.time_ms)\n",
   "    machine.settlement = pseudo_turnback_machine.Settlement(expectation.purpose, end, selected, actual, expectation.scope, origin, generation, expectation.time_ms)\n"
   "    if expectation.purpose == jump_transaction.JUMP_TURNBACK:\n        self.jump_lock = False\n")]),
 ("TG-05", "required", "the landing at B is processed as an ordinary arrival: the outer (operational stop) AND the inner (stop score, checkpoint) guards ignore the lock (M12)",
  [(SL, OUTER_OLD, OUTER_NEW), (SL, STOP_OLD, STOP_NEW), (SL, CP_OLD, CP_NEW)]),
 ("TG-06", "required", "the stop score of an arrival ignores the lock: a door-open edge at B scores the 0 cm stop (+500) a second time (M10)", [(SL, STOP_OLD, STOP_NEW)]),
 ("TG-07", "redundant", "the outer guard of the operational stop path alone ignores the lock (M11: the inner guards still protect the landing)", [(SL, OUTER_OLD, OUTER_NEW)]),
 ("TG-08", "redundant", "the inner checkpoint guard alone ignores the lock (M9: the outer guard and the stop guard come first)", [(SL, CP_OLD, CP_NEW)]),
 ("TG-09", "required", "the B checkpoint is created twice (the 'never a second checkpoint of the same B' refusal is removed and the establishment creates twice)",
  [(SL, "    if getattr(self, 'save_data', []) and station_identity.same_station(self.save_data[-1], snapshot):\n        return False                                                     # never a second checkpoint of the same B\n", ""),
   (SL, DUP_OLD, "    create_turnback_b_checkpoint(self, b_index, jump_time)\n    create_turnback_b_checkpoint(self, b_index, jump_time)\n    machine.on_b_established(now_ms)")]),
 ("TG-10", "required", "only the abort is suppressed, the wrong state stays (the fix is missing AND the duplicate-B branch no longer stops the scoring, M4)", NO_FIX + [(SL, ABORT_OLD, ABORT_NEW)]),
 ("TG-11", "required", "the duplicate B checkpoint is tolerated (the fix is missing AND the result of the turnback creator is ignored, M5)", NO_FIX + [(SL, DUP_OLD, IGNORE_NEW)]),
 ("TG-12", "required", "the operating time of B is not marked as scored (the B departure could score time, M7)", [(SL,
   "    self.has_scored_time_this_station = True\n    if not create_turnback_b_checkpoint(self, b_index, jump_time):", "    self.has_scored_time_this_station = False\n    if not create_turnback_b_checkpoint(self, b_index, jump_time):")]),
 ("TG-13", "required", "the lock is never released by the departure: no return to the ordinary scoring after B (M8)", [(SL,
   "        if getattr(self, 'jump_lock', False):\n            self.jump_lock = False\n\n        self.is_first_station = False", "        if getattr(self, 'jump_lock', False):\n            pass\n\n        self.is_first_station = False")]),
 ("TG-14", "required", "awaiting_b is released at the completion (M6)", [(SL,
   "                machine.on_jump_complete(True, record.selected, generation)\n", "                machine.on_jump_complete(True, record.selected, generation)\n                machine.awaiting_b = False\n")]),
 ("TG-15", "required", "the lock is taken BEFORE the refusals of the request (a refused request leaves the scoring locked)", [(SL,
   "    machine = turnback_machine_of(self)\n    station_list = getattr(self, 'station_list', None) or []\n    b_index = request[\"target_index\"]\n",
   "    machine = turnback_machine_of(self)\n    self.jump_lock = True\n    station_list = getattr(self, 'station_list', None) or []\n    b_index = request[\"target_index\"]\n")]),
 ("TG-16", "required", "the fix line is placed AFTER the command is sent and the transaction is opened (position of the owner moved; the entry no longer takes the lock before the Jump goes out)", NO_FIX + [(SL,
   "    self._open_jump_transaction(jump_transaction.JUMP_TURNBACK, planned, request_id)\n", "    self._open_jump_transaction(jump_transaction.JUMP_TURNBACK, planned, request_id)\n" + FIX)]),
 ("TG-17", "required", "F5 / generation change: the stale chain is no longer dropped by the lifecycle guard", [(SL, "    if stale:\n        machine.discard_all()\n        return stale\n", "    if stale:\n        return stale\n")]),
 ("TG-18", "required", "Retry: the chain still waiting in its 5.0 s window is not dropped when a Retry Jump is in flight", [(SL, "        machine.on_retry()\n        return True\n    return stale", "        return True\n    return stale")]),
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
print("BASELINE of the mutation modules: failing=%d (modules=%d) tests reported=%d new-module tests=%d" % (len(base_bad), len(MODS), ran_tests, sum(1 for l in out.splitlines() if NEW_MODULE in l or "A_RealOrderContracts" in l or "B_LockOwnership" in l or "C_RetryF5Start" in l or "D_FixtureGapAndStatic" in l)))
if base_bad:
    for b in base_bad[:10]:
        print("   ", b[:200])
    sys.exit(1)
survivors, redundant, na, killed = [], [], [], 0
for mid, kind, meaning, edits in M:
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
            out_text = text.replace("\n", "\r\n") if crlf else text
            open(os.path.join(ROOT, f), "wb").write(out_text.encode("utf-8"))
        bad, out, err = run()
    finally:
        for f, (orig, crlf, text) in files.items():
            open(os.path.join(ROOT, f), "wb").write(orig.encode("utf-8"))
    n_new = sum(1 for b in bad if NEW_MODULE in b or any(c in b for c in ("A_RealOrderContracts", "B_LockOwnership", "C_RetryF5Start", "D_FixtureGapAndStatic")))
    n_old = len(bad) - n_new
    state = "KILLED  " if bad else "SURVIVED"
    tag = "" if kind == "required" else " [%s]" % kind
    print("%-6s %s old=%d new=%d%s  %s" % (mid, state, n_old, n_new, tag, meaning[:110]))
    if bad:
        first_new = next((b for b in bad if any(c in b for c in ("A_RealOrderContracts", "B_LockOwnership", "C_RetryF5Start", "D_FixtureGapAndStatic"))), None)
        first_old = next((b for b in bad if b is not first_new and not any(c in b for c in ("A_RealOrderContracts", "B_LockOwnership", "C_RetryF5Start", "D_FixtureGapAndStatic"))), None)
        if first_new:
            print("      new e.g. " + first_new[:150])
        if first_old:
            print("      old e.g. " + first_old[:150])
    if bad:
        killed += 1
        if kind == "redundant":
            redundant.append(mid + "(killed)")
    elif kind == "redundant":
        redundant.append(mid + "(survived: redundant guard, adjudicated)")
    else:
        survivors.append(mid)
print("KILLED %d SURVIVORS %s REDUNDANT %s NOT-APPLICABLE %s" % (killed, survivors, redundant, na))
sys.exit(0 if not survivors and not na else 1)
