"""TB-F Stage 1 mutation harness (new file; the existing harness files are NOT modified).
usage: python mut_tbf.py <harness dir with run_red.py> <byte copy root> [name prefixes]
One mutant at a time on a THROW-AWAY byte copy; the file is restored after every mutant. Definitions follow the canon
(cr-entry-1-followup-plan V-1..V-3 plus the two extra mutants TF-04 / TF-05 for +/-0.0 and sign reversal).
A mutant is KILLED when at least one test of MODS fails. The failing tests are split into
  'new'  = the TB-F guard class  test_pt_tbd_real_flow.C_TheLandingAtBScoresCorrectly
  'old'  = every other test of MODS (the tests that existed at HEAD 6d4d1af)
so that the contribution of the added guards is visible. Per mutant the line is printed:  NAME  KILLED/SURVIVED  old=<n> new=<n>"""
import os
import subprocess
import sys

ROOT = sys.argv[2]
SL, MN = "scoring_logic.py", "main.py"
MODS = ["test_pt_tbd_candidates", "test_pt_tbd_snapshot", "test_pt_tbd_retry", "test_pt_tbd_real_flow", "test_pt_tbc_section", "test_pt_scoring_continuity", "test_pt_static_pins",
        "test_pt_tbc_completion", "test_pt_runtime_time_contract", "test_pt_tbc_od33_start_equivalence", "test_close_range_entry_paths", "test_close_range_reuse", "test_close_range_contract"]
NEW_CLASS = "C_TheLandingAtBScoresCorrectly"

M = [
 ("TF-01 (V-1) the supply of the actual landing at the settlement is removed", MN,
  "        close_range_fix_landing_stop(self, verdict.selected_idx, verdict.actual_location)\n", "        pass\n"),
 ("TF-02 (V-2) the supply is skipped only for a pseudo-turnback Jump", MN,
  "        close_range_fix_landing_stop(self, verdict.selected_idx, verdict.actual_location)\n",
  "        if expectation.purpose != jump_transaction.JUMP_TURNBACK:\n"
  "            close_range_fix_landing_stop(self, verdict.selected_idx, verdict.actual_location)\n"),
 ("TF-03 (V-3) the pending state no longer suppresses the out-of-range stop flag", SL,
  "        and not getattr(self, 'close_range_departure_reset_pending', False)\n        and not getattr(\n            self,\n            'has_scored_stop_this_station',",
  "        and not getattr(\n            self,\n            'has_scored_stop_this_station',"),
 ("TF-04 (V-4) a zero speed (+0.0 / -0.0) releases the pending state like a movement", SL,
  "    if self.bve_speed > 0.0:\n        reset_station_evaluation_state(self)", "    if self.bve_speed >= 0.0:\n        reset_station_evaluation_state(self)"),
 ("TF-05 (extra) a reversing train is taken for a stopped train", SL,
  "    is_exact_stop = self.bve_speed == 0.0\n", "    is_exact_stop = self.bve_speed <= 0.0\n"),
]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


def run():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TS_REPO=ROOT, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, os.path.join(sys.argv[1], "run_red.py")] + MODS, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    bad = [l for l in r.stdout.splitlines() if l.startswith(("FAIL", "ERROR", "SUBFAIL"))]
    return bad, r.stdout, r.stderr[-300:]


only = sys.argv[3:] if len(sys.argv) > 3 else None
base_bad, out, err = run()
print("BASELINE of the mutation modules: failing=%d (modules=%d)" % (len(base_bad), len(MODS)))
ran_tests = sum(1 for l in out.splitlines() if l.split(" ", 1)[0] in ("ok", "FAIL", "ERROR", "skip"))
print("BASELINE tests reported: %d; new-class tests present: %d" % (ran_tests, sum(1 for l in out.splitlines() if NEW_CLASS in l)))
if base_bad:
    for b in base_bad[:10]:
        print("   ", b[:200])
    sys.exit(1)
survivors, na, killed = [], [], 0
for name, f, old, new in M:
    if only and not any(name.startswith(o) for o in only):
        continue
    path = os.path.join(ROOT, f)
    orig, crlf = read(path)
    t = orig.replace("\r\n", "\n")
    if t.count(old) != 1:
        print("NOT-APPLICABLE %s (count=%d)" % (name, t.count(old)))
        na.append(name)
        continue
    t2 = t.replace(old, new)
    if crlf:
        t2 = t2.replace("\n", "\r\n")
    open(path, "wb").write(t2.encode("utf-8"))
    try:
        bad, out, err = run()
    finally:
        open(path, "wb").write(orig.encode("utf-8"))
    n_new = sum(1 for b in bad if NEW_CLASS in b)
    n_old = len(bad) - n_new
    print("%-86s %s old=%d new=%d%s" % (name, "KILLED  " if bad else "SURVIVED", n_old, n_new, "" if bad else ("  " + err.strip()[-100:])))
    if bad:
        killed += 1
        first_old = next((b for b in bad if NEW_CLASS not in b), None)
        first_new = next((b for b in bad if NEW_CLASS in b), None)
        if first_old:
            print("      old e.g. " + first_old[:150])
        if first_new:
            print("      new e.g. " + first_new[:150])
    else:
        survivors.append(name)
print("KILLED %d SURVIVORS %s NOT-APPLICABLE %s" % (killed, survivors, na))
