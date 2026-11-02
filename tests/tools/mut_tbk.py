"""TB-K mutation harness: the display latch of the free-driving remaining time after the stop at a pseudo-turnback pair A (Overlay._free_turnback_a_latch_update / free_turnback_a_time_suppressed / the view branch).
New file; the existing harness files are NOT modified. usage: python mut_tbk.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
MN = "main.py"
NEW_MODULES = ("test_pt_tbk_free_driving",)
NEW_CLASSES = ("A_Arrival", "B_AfterTheStop", "C_Scoring", "D_Untouched")
MODS = list(NEW_MODULES) + ["test_pt_tbj_remaining_time", "test_hud_target_wiring_r23"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


SPEED = "if self.bve_speed == 0.0 and -target.margin_f <= dist <= target.margin_b:"
PAIRHERE = "p.arrival == target.index), None)"
RELEASE = "if latch is not None and not (pair_kept.arrival <= target.index <= pair_kept.departure):"
SCOPE = "if latch[0] != scope or pair_kept is None:"
OWNER = "if hud_target_contract.owner_is_scoring(self.is_scoring_mode, self.is_scoring_finished) or pairset is None:"
VIEW = 'return ("dashes", None) if self.free_turnback_a_time_suppressed() else None'
RESET = "        self._free_turnback_a_latch = None          # Stage TB-K: nothing of the previous"
SYNC = "self._free_turnback_a_latch_sync(host_target)"

M = [
 ("TK-01", "the speed condition is gone (a position inside the range latches while moving)", [(MN, SPEED, "if -target.margin_f <= dist <= target.margin_b:")]),
 ("TK-02", "the author range condition is gone (a speed 0 alone latches)", [(MN, SPEED, "if self.bve_speed == 0.0:")]),
 ("TK-03", "the front / back margins are swapped", [(MN, SPEED, "if self.bve_speed == 0.0 and -target.margin_b <= dist <= target.margin_f:")]),
 ("TK-04", "the B of a pair latches instead of the A", [(MN, PAIRHERE, "p.departure == target.index), None)")]),
 ("TK-05", "the latch is never ended by a target beyond the pair", [(MN, RELEASE, "if False:")]),
 ("TK-06", "the latch ends when the target moves from the A to the B (kept only on the A)", [(MN, RELEASE, "if latch is not None and not (pair_kept.arrival <= target.index <= pair_kept.arrival):")]),
 ("TK-07", "a target before the pair does not end the latch", [(MN, RELEASE, "if latch is not None and not (target.index <= pair_kept.departure):")]),
 ("TK-08", "the scenario scope is not checked", [(MN, SCOPE, "if pair_kept is None:")]),
 ("TK-09", "a scoring session does not drop the latch", [(MN, OWNER, "if pairset is None:")]),
 ("TK-10", "the view shows dashes whenever the scoring does not own the field", [(MN, VIEW, 'return ("dashes", None)')]),
 ("TK-11", "the epoch reset (F5 / a new scenario instance) keeps the latch", [(MN, RESET, "        pass          # Stage TB-K: nothing of the previous")]),
 ("TK-12", "the latch is never synchronised from the HUD target sync", [(MN, SYNC, "pass")]),
 ("TK-13", "a closed door is required (the door state decides)", [(MN, SPEED, "if self.bve_speed == 0.0 and self.bve_door == 0 and -target.margin_f <= dist <= target.margin_b:")]),
 ("TK-14", "the speed test is a tolerance (below 0.5 km/h latches)", [(MN, SPEED, "if abs(self.bve_speed) < 0.5 and -target.margin_f <= dist <= target.margin_b:")]),
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
    print("%-6s %s new=%d old=%d  %s" % (mid, "KILLED  " if bad else "SURVIVED", n_new, len(bad) - n_new, meaning[:120]))
    if bad:
        first_new = next((b for b in bad if any((" " + c + ".") in b for c in NEW_CLASSES)), None)
        if first_new:
            print("      new e.g. " + first_new[:150])
        killed += 1
    else:
        survivors.append(mid)
print("KILLED %d SURVIVORS %s NOT-APPLICABLE %s" % (killed, survivors, na))
sys.exit(0 if not survivors and not na else 1)
