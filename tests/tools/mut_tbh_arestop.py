"""TB-H Stage 3/4 mutation harness for the A re-stop wait (new file; the existing harness files mut_tbf.py / mut_tbg.py / mut_tbh.py ... are NOT modified).
usage: python mut_tbh_arestop.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test (Owner ruling R7 = plan 3, C-01 retest Close 2026-11-01): speed != 0 while the Jump waits cancels it (guidance removed at once, red two-line warning, RESTOP_WAIT, no Jump); a re-stop = speed == 0 inside the
author-defined stop range of the same A (never the 330 m range), warning removed at once, two-line guidance, a NEW 5.0 s, ONE Jump; A is never scored again; the wait state is dropped by the lifecycle events; the train driven
from A to B by itself aborts the scoring (fail-closed). Door, indicator lamp and signalFlag decide nothing; Current and Legacy share the path.
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
SL, PM = "scoring_logic.py", "pseudo_turnback_machine.py"
NEW_MODULES = ("test_pt_tbh_arestop",)
NEW_CLASSES = ("A_WaitAndCancel", "B_NoRescore", "C_Lifecycle", "D_Independence", "E_ContractsKept", "F_Machine")
MODS = list(NEW_MODULES) + ["test_pt_runtime_machine", "test_pt_display_contract", "test_pt_scoring_continuity", "test_pt_tbc_completion", "test_pt_tbc_lifecycle", "test_pt_tbc_request",
                            "test_pt_tbd_retry", "test_pt_tbd_snapshot", "test_pt_tbg_landing_order", "test_pt_tbh_pairb_contract", "test_pt_tbh_retry_state"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


CANCEL_ADD = '        add_score_popup(self, 0, text, COLOR_B_EMG, "big", TURNBACK_CANCEL_CATEGORY, now_ms / 1000.0)'
HOOK = ("    if identity_ok and turnback_other_arrival(self, curr_sta_idx):       # Stage TB-H: the train was driven from A to B by itself: the scoring is aborted, B is not scored as an ordinary arrival\n"
        "        return\n")
RESTOP_BRANCH = "            self.window_ms = now_ms\n            self.jump_earliest_ms = now_ms + REQUEST_AFTER_MS\n            self.has_special = False"
MOVING = "        if moving is True:\n            self.state = RESTOP_WAIT"
RESTOP_GATE = "            if moving is not False or in_stop_range is not True:"
RESTOP_SHOW = "    turnback_drop_popups(self)\n    turnback_display_update(self, now_ms / 1000.0)"
RANGE_EXPR = "            in_range = -margin_f <= a_position - position <= margin_b"

# (id, meaning, [(file, old, new), ...])
M = [
 ("AM-01", "speed != 0 never cancels the Jump (the movement branch is dead)", [(PM, MOVING, "        if False:\n            self.state = RESTOP_WAIT")]),
 ("AM-02", "the red cancellation warning is not shown", [(SL, CANCEL_ADD, "        pass")]),
 ("AM-03", "the guidance is not removed when the Jump is cancelled", [(SL, "    turnback_drop_popups(self)\n    for text in TURNBACK_CANCEL_TEXTS:", "    for text in TURNBACK_CANCEL_TEXTS:")]),
 ("AM-04", "a re-stop is accepted outside the author range of A (the range judgement is always true)", [(SL, RANGE_EXPR, "            in_range = True")]),
 ("AM-05", "a re-stop is accepted while the train still moves (moving is not required to be False)", [(PM, RESTOP_GATE, "            if in_stop_range is not True:")]),
 ("AM-06", "no new 5.0 s after a re-stop (the Jump is allowed at once)", [(PM, RESTOP_BRANCH, "            self.window_ms = now_ms\n            self.jump_earliest_ms = now_ms\n            self.has_special = False")]),
 ("AM-07", "the second movement does not cancel again (only the first wait can be cancelled)", [(PM, MOVING, "        if moving is True and self.restop_count == 0:\n            self.state = RESTOP_WAIT")]),
 ("AM-08", "A is scored again after a re-stop (the station evaluation state of A is reset)", [(SL, RESTOP_SHOW, "    reset_station_evaluation_state(self)\n" + RESTOP_SHOW)]),
 ("AM-09", "the Jump request is not recorded in the issued keys (the same arrival could request again)", [(PM, "        self.issued.add(self.key)\n        if not jump_available:", "        if not jump_available:")]),
 ("AM-10", "F5 (reset_world) leaves the chain state alone", [(PM, "        self._clear_session()\n        self.state = IDLE\n        return [(\"discard_pending\", \"world-reset\")] if had else []", "        self._clear_session()\n        pass\n        return [(\"discard_pending\", \"world-reset\")] if had else []")]),
 ("AM-11", "a START / Retry Jump in flight no longer drops the RESTOP_WAIT chain (the new block of the guard is dead)", [(SL,
   "    if (machine.state == pseudo_turnback_machine.RESTOP_WAIT\n", "    if (False and machine.state == pseudo_turnback_machine.RESTOP_WAIT\n")]),
 ("AM-12", "a generation change does not drop the chain (machine and lifecycle guard compare no generation)", [
   (PM, "        if generation != self.generation or not scoring_active:\n            return self._discard(\"generation\" if generation != self.generation else \"scoring-ended\")\n        if paused or menu_open:\n            return []\n        if self.state == RESTOP_WAIT:",
        "        if not scoring_active:\n            return self._discard(\"scoring-ended\")\n        if paused or menu_open:\n            return []\n        if self.state == RESTOP_WAIT:"),
   (SL, "    stale = (not turnback_session_active(self)\n             or (machine.fixed_generation is not None and machine.fixed_generation != generation)\n             or (machine.generation is not None and machine.generation != generation))",
        "    stale = (not turnback_session_active(self))")]),
 ("AM-13", "a changed RunPairSet does not drop the waiting chain", [(SL, "    if machine.drop_if_pair_not_in_run():", "    if False:")]),
 ("AM-14a", "arrival at B by driving only drops the state (no failure, no abort)", [(PM, "        if station_index == self.pair.departure:\n            self.state = FAILED", "        if False:\n            self.state = FAILED")]),
 ("AM-14b", "arrival at B by driving is still scored as an ordinary arrival (the host never reports the abort)", [(SL, "            aborted = True\n    return aborted", "            aborted = True\n    return False")]),
 ("AM-15", "the door state is mixed into the decision (an open door ignores the movement)", [(SL, "    machine = self.__dict__.get('turnback_machine')\n    kept = machine.stop_range if machine is not None else None",
   "    if getattr(self, 'bve_door', 0) != 0:\n        moving = False\n    machine = self.__dict__.get('turnback_machine')\n    kept = machine.stop_range if machine is not None else None")]),
 ("AM-16", "the 330 m scoring range is used as the stop range of A", [(SL, "    numbers = (stop_position, getattr(self, 'bve_margin_f', None), getattr(self, 'bve_margin_b', None))", "    numbers = (stop_position, 330.0, 330.0)")]),
 ("AM-17", "only the managed (Current) host shows the cancellation: the common Python path of Legacy is broken", [(SL,
   "            elif act[0] == \"cancel_jump\":\n                turnback_cancel_show(self, now_ms)", "            elif act[0] == \"cancel_jump\" and getattr(self, 'jump_client', None) is not None:\n                turnback_cancel_show(self, now_ms)")]),
 ("AM-18", "the OLD request time (arrival + 5.0 s) is still used after a re-stop", [(PM, "        if now_ms < self.jump_earliest_ms:\n            return []", "        if now_ms < self.arrival_ms + REQUEST_AFTER_MS:\n            return []")]),
 ("AM-19", "a re-stop overwrites the arrival time of A", [(PM, RESTOP_BRANCH, "            self.window_ms = now_ms\n            self.arrival_ms = now_ms\n            self.jump_earliest_ms = now_ms + REQUEST_AFTER_MS\n            self.has_special = False")]),
 ("AM-20", "the stop range of A is not kept at the arrival (a re-stop can never be established)", [(SL, "stop_range=turnback_stop_range_capture(self, stop_position))", "stop_range=None)")]),
 ("AM-21", "the boundaries of the stop range are outside", [(SL, RANGE_EXPR, "            in_range = -margin_f < a_position - position < margin_b")]),
 ("AM-22", "the warning is not removed at the re-stop", [(SL, RESTOP_SHOW, "    turnback_display_update(self, now_ms / 1000.0)")]),
 ("AM-23", "the warning stays 10.0 s instead of 5.0 s", [(SL, "TURNBACK_CANCEL_CATEGORY, now_ms / 1000.0)", "TURNBACK_CANCEL_CATEGORY, now_ms / 1000.0 + 5.0)")]),
 ("AM-24", "the warning has the colour of the guidance, not the red of the illegal-Jump warning", [(SL, "COLOR_B_EMG, \"big\", TURNBACK_CANCEL_CATEGORY", "COLOR_WHITE, \"big\", TURNBACK_CANCEL_CATEGORY")]),
 ("AM-25", "the guidance after a re-stop has one line only", [(SL, "    for text in ((TURNBACK_GUIDANCE_TEXT,) if machine.restop_count == 0 else (TURNBACK_GUIDANCE_TEXT, TURNBACK_RESTOP_GUIDANCE_TEXT)):", "    for text in (TURNBACK_GUIDANCE_TEXT,):")]),
 ("AM-26", "the guidance window still ends 5.0 s after the ARRIVAL (not after the re-stop)", [(SL, "machine.window_ms / 1000.0 + TURNBACK_TOTAL_SECONDS", "machine.arrival_ms / 1000.0 + TURNBACK_TOTAL_SECONDS")]),
 ("AM-27", "the formal arrival at another station does not drop the wait state", [(PM, "        return self._drop(\"other-station-arrival\")", "        return []")]),
 ("AM-28", "evaluate_arrival does not ask about the arrival at another station / B at all", [(SL, HOOK, "")]),
 ("AM-29", "an unknown movement (None) cancels the Jump", [(PM, MOVING, "        if moving is not False:\n            self.state = RESTOP_WAIT")]),
 ("AM-31", "the popups of the chain outlive its state (the display tick no longer takes them)", [(SL, "        turnback_drop_popups(self, warning=(machine.state != pseudo_turnback_machine.RESTOP_WAIT))\n", "")]),
 ("AM-30", "an unknown range (None) is accepted as a re-stop", [(PM, RESTOP_GATE, "            if moving is not False or in_stop_range is False:")]),
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
