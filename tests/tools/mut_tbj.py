"""TB-J mutation harness: the remaining-time field of the ordinary TScoring HUD while a pseudo-turnback chain lives (Overlay.turnback_remaining_view and the time_left row of hud_ui.draw_hud). New file; the existing harness
files (mut_tbf.py / mut_tbg.py / mut_tbh*.py / mut_tbi.py) are NOT modified.
usage: python mut_tbj.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
HU, MN, MM = "hud_ui.py", "main.py", "pseudo_turnback_machine.py"
NEW_MODULES = ("test_pt_tbj_remaining_time", "test_pt_tbj_discard_gate")
NEW_CLASSES = ("A_FirstWindow", "B_CancelAndRestop", "C_Discard", "D_Guards", "E_FreeDriving", "F_JumpRequestedAndLanding", "G_AfterLanding", "H_Discard", "I_Rounding", "J_NothingElseMoves", "K_CountdownIsDroppedByTheProductEntries", "L_AfterTheLanding")
MODS = list(NEW_MODULES) + ["test_pt_tbh_selfdrive_hud", "test_hud_target_wiring_r23"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


CEIL = "            count_s = max(0, -(-int(remaining_view[1]) // 1000))"
DASH = '        elif remaining_view is not None and remaining_view[0] == "dashes":\n            draw_row_local("", COLOR_WHITE, "--:--", COLOR_WHITE, ui_y)\n'
SHOWN = "            shown_time = remaining_view[1]\n"
COUNT_RET = '                return ("count", deadline - self.bve_time_ms)\n'
ACCESSOR = "        if self.state in (RECOGNIZED, ARMED):\n            return self.jump_earliest_ms\n"
RESTOP = '            if machine.state == pseudo_turnback_machine.RESTOP_WAIT:\n                return ("dashes", None)\n'
HELD = '                return ("count", 0)\n'
BBRANCH = "        if isinstance(index, int) and 0 <= index < len(station_list) and index in turnback_b_indexes(self):\n"
BRET = '            return ("time", departure) if isinstance(departure, int) and departure > 0 else ("dashes", None)\n'
GATE = "        if not hud_target_contract.owner_is_scoring(self.is_scoring_mode, self.is_scoring_finished):\n            return None\n"

# (id, meaning, [(file, old, new), ...])
M = [
 ("TJ-01", "the countdown rounds down (floor) instead of up", [(HU, CEIL, "            count_s = max(0, int(remaining_view[1]) // 1000)")]),
 ("TJ-02", "the countdown rounds to the nearest second", [(HU, CEIL, "            count_s = max(0, int(round(int(remaining_view[1]) / 1000.0)))")]),
 ("TJ-03", "the countdown can go negative (no clamp at 00:00)", [(HU, CEIL, "            count_s = -(-int(remaining_view[1]) // 1000)")]),
 ("TJ-04", "the dashes of the cancellation are not drawn (the old held A time shows)", [(HU, DASH, '        elif False:\n            pass\n')]),
 ("TJ-05", "the departure of B is not used for the display (the machine target stays)", [(HU, SHOWN, "            pass\n")]),
 ("TJ-06", "the countdown starts from the arrival + 10 s instead of the Jump time (a second timer)", [(MN, COUNT_RET, '                return ("count", machine.arrival_ms + 10000 - self.bve_time_ms)\n')]),
 ("TJ-07", "the cancellation wait shows the countdown", [(MN, RESTOP, '            if machine.state == pseudo_turnback_machine.RESTOP_WAIT:\n                return ("count", 5000)\n')]),
 ("TJ-08", "00:00 is released after the Jump request (no hold until B is established)", [(MN, HELD, "                return None\n")]),
 ("TJ-09", "the departure of B is never used after the landing", [(MN, BBRANCH, "        if False and isinstance(index, int) and 0 <= index < len(station_list) and index in turnback_b_indexes(self):\n")]),
 ("TJ-10", "a B without a departure time falls back to the machine target (the completed arrival)", [(MN, BRET, '            return ("time", departure) if isinstance(departure, int) and departure > 0 else None\n')]),
 ("TJ-11", "the scoring-owner gate is gone (free driving reads the chain)", [(MN, GATE, "")]),
 ("TJ-13", "the machine accessor also returns the stale deadline of the cancelled wait", [(MM, ACCESSOR, "        if self.state in (RECOGNIZED, ARMED, RESTOP_WAIT):\n            return self.jump_earliest_ms\n")]),
 ("TJ-14", "the machine accessor returns the arrival + 10 s (a second timer)", [(MM, ACCESSOR, "        if self.state in (RECOGNIZED, ARMED):\n            return self.arrival_ms + 10000\n")]),
 ("TJ-12", "the B branch ignores which pairs the Run crosses (every station with a departure time)", [(MN, "and index in turnback_b_indexes(self):", "and True:")]),
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
        if first_new:
            print("      new e.g. " + first_new[:150])
        killed += 1
    else:
        survivors.append(mid)
print("KILLED %d SURVIVORS %s NOT-APPLICABLE %s" % (killed, survivors, na))
sys.exit(0 if not survivors and not na else 1)
