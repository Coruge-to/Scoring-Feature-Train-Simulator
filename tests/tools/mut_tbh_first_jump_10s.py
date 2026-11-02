"""TB-H Stage 5b mutation harness for the FIRST Jump at arrival + 10.0 s (new file; the existing harness files mut_tbf.py / mut_tbg.py / mut_tbh.py / mut_tbh_arestop.py / mut_tbh_bulk_button.py ... are NOT modified).
usage: python mut_tbh_first_jump_10s.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test (Owner, after the C-06 live run): the first window of an arrival is 10.0 s: the arrival result popups keep their normal 5.0 s, the guidance is shown 5-10 s with or without them, ONE Jump at 10.0 s; speed != 0 from the arrival
tick on (0-5 s and 5-10 s) cancels (guidance removed at once, the arrival result popups end through the popup list, the red two-line warning, no Jump); a re-stop window stays 5.0 s; A is never scored again; one Jump; the wait state is dropped by
F5 / Retry / generation change.
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
SL, PM = "scoring_logic.py", "pseudo_turnback_machine.py"
NEW_MODULES = ("test_pt_tbh_first_jump_10s",)
NEW_CLASSES = ("A_FirstWindow", "B_Cancellation", "C_AfterReStop", "D_ContractsKept", "E_Lifecycle", "F_Machine", "G_PopupOwnership")
MODS = list(NEW_MODULES) + ["test_pt_tbh_arestop", "test_pt_display_contract", "test_pt_runtime_machine", "test_pt_tbc_request", "test_pt_scoring_continuity", "test_pt_tbd_retry"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


ON_ARRIVAL = "        self.jump_earliest_ms = now_ms + FIRST_REQUEST_AFTER_MS      # Stage TB-H 5b: fixed at the arrival: arrival + 10.0 s\n"
GUIDE_FROM = "        guide_from = FIRST_GUIDE_FROM_MS if self.restop_count == 0 else 0\n        if dt < guide_from:\n            return \"special\" if self.has_special else None\n        return \"guide\"\n"
EXTRA = "        return (FIRST_REQUEST_AFTER_MS - REQUEST_AFTER_MS) if self.restop_count == 0 else 0\n"
MOVING = "        if moving is True:\n            self.state = RESTOP_WAIT"
RESTOP_BRANCH = "            self.window_ms = now_ms\n            self.jump_earliest_ms = now_ms + REQUEST_AFTER_MS\n            self.has_special = False"
SPECIAL_LIST = "    special = [p for p in self.popups[popups_before:] if is_arrival_special_popup(p)]\n"
CANCEL_PAIR = "    turnback_drop_arrival_results(self)\n    turnback_drop_popups(self)\n    for text in TURNBACK_CANCEL_TEXTS:"
DROP_BODY = "    if any(is_arrival_special_popup(p) for p in (getattr(self, 'popups', None) or ())):\n        self.popups = [p for p in self.popups if not is_arrival_special_popup(p)]\n"
EXPIRE = "machine.window_ms / 1000.0 + TURNBACK_TOTAL_SECONDS + machine.first_window_extra_ms() / 1000.0"
SPECIAL_PRED = "    return popup.get(\"type\") == \"big\" and popup.get(\"category\") in (\"基本制動\", \"ボーナス\")"
RESTOP_SHOW = "    turnback_drop_popups(self)\n    turnback_display_update(self, now_ms / 1000.0)"

# (id, meaning, [(file, old, new), ...])
M = [
 ("JMM-01", "the first Jump is requested at arrival + 5.0 s again", [(PM, ON_ARRIVAL, "        self.jump_earliest_ms = now_ms + REQUEST_AFTER_MS\n")]),
 ("JMM-02", "the arrival result popups are cut to 3.0 s again", [(SL, SPECIAL_LIST, SPECIAL_LIST + "    for p in special:\n        p[\"expire_time\"] = machine.arrival_ms / 1000.0 + 3.0\n")]),
 ("JMM-03", "the guidance is shown from 0 s (with a result popup too)", [(PM, GUIDE_FROM, "        guide_from = FIRST_GUIDE_FROM_MS if self.restop_count == 0 else 0\n        if dt < guide_from:\n            return \"guide\"\n        return \"guide\"\n")]),
 ("JMM-04", "no guidance between 5 s and 10 s", [(PM, GUIDE_FROM, "        guide_from = FIRST_GUIDE_FROM_MS if self.restop_count == 0 else 0\n        if dt < guide_from:\n            return \"special\" if self.has_special else None\n        return None\n")]),
 ("JMM-05", "without a result popup the guidance is shown from the arrival (the quiet five seconds are gone)", [(PM, GUIDE_FROM, "        guide_from = FIRST_GUIDE_FROM_MS if self.restop_count == 0 else 0\n        if dt < guide_from:\n            return \"special\" if self.has_special else \"guide\"\n        return \"guide\"\n")]),
 ("JMM-06", "a movement in the first five seconds is ignored", [(PM, MOVING, "        if moving is True and now_ms - self.arrival_ms >= 5000:\n            self.state = RESTOP_WAIT")]),
 ("JMM-07", "a movement between five and ten seconds is ignored", [(PM, MOVING, "        if moving is True and now_ms - self.arrival_ms < 5000:\n            self.state = RESTOP_WAIT")]),
 ("JMM-08", "a re-stop window is 10.0 s as well", [(PM, RESTOP_BRANCH, "            self.window_ms = now_ms\n            self.jump_earliest_ms = now_ms + FIRST_REQUEST_AFTER_MS\n            self.has_special = False")]),
 ("JMM-09", "the guidance of the first window still ends at 5.0 s (the popup expire time is not extended)", [(SL, EXPIRE, "machine.window_ms / 1000.0 + TURNBACK_TOTAL_SECONDS")]),
 ("JMM-10", "the guidance of a re-stop window also lasts 10.0 s (the extra time is not limited to the first window)", [(PM, EXTRA, "        return (FIRST_REQUEST_AFTER_MS - REQUEST_AFTER_MS)\n")]),
 ("JMM-11", "the cancellation does not end the arrival result popups", [(SL, CANCEL_PAIR, "    turnback_drop_popups(self)\n    for text in TURNBACK_CANCEL_TEXTS:")]),
 ("JMM-12", "the cancellation clears the whole popup list (the score lines go too)", [(SL, DROP_BODY, "    self.popups = []\n")]),
 ("JMM-13", "the result-popup predicate is widened to every 'big' popup", [(SL, SPECIAL_PRED, "    return popup.get(\"type\") == \"big\"")]),
 ("JMM-14", "A is scored again after a re-stop (the station evaluation state of A is reset)", [(SL, RESTOP_SHOW, "    reset_station_evaluation_state(self)\n" + RESTOP_SHOW)]),
 ("JMM-15", "the Jump request is not recorded in the issued keys (the same arrival could request again)", [(PM, "        self.issued.add(self.key)\n        if not jump_available:", "        if not jump_available:")]),
 ("JMM-16", "F5 (reset_world) leaves the chain state alone", [(PM, "        self._clear_session()\n        self.state = IDLE\n        return [(\"discard_pending\", \"world-reset\")] if had else []", "        self._clear_session()\n        pass\n        return [(\"discard_pending\", \"world-reset\")] if had else []")]),
 ("JMM-17", "a generation change does not drop the chain", [
   (PM, "        if generation != self.generation or not scoring_active:\n            return self._discard(\"generation\" if generation != self.generation else \"scoring-ended\")\n        if paused or menu_open:\n            return []\n        if self.state == RESTOP_WAIT:",
        "        if not scoring_active:\n            return self._discard(\"scoring-ended\")\n        if paused or menu_open:\n            return []\n        if self.state == RESTOP_WAIT:"),
   (SL, "    stale = (not turnback_session_active(self)\n             or (machine.fixed_generation is not None and machine.fixed_generation != generation)\n             or (machine.generation is not None and machine.generation != generation))",
        "    stale = (not turnback_session_active(self))")]),
 ("JMM-18", "the first window's guidance is never removed when the chain leaves its states (the display tick keeps the old popup)", [(SL, "        turnback_drop_popups(self, warning=(machine.state != pseudo_turnback_machine.RESTOP_WAIT))\n", "")]),
 ("JMM-19", "the first-window constant is 9.9 s", [(PM, "FIRST_REQUEST_AFTER_MS = 2 * REQUEST_AFTER_MS", "FIRST_REQUEST_AFTER_MS = 2 * REQUEST_AFTER_MS - 100")]),
 ("JMM-20", "the guidance starts at 3.0 s", [(PM, "FIRST_GUIDE_FROM_MS = REQUEST_AFTER_MS ", "FIRST_GUIDE_FROM_MS = REQUEST_AFTER_MS - 2000 ")]),
 ("JMM-21", "the arrival result flag is never set (the host reports no result popup)", [(SL, "    machine.a_scoring_complete(machine.arrival_ms, False, bool(special))\n", "    machine.a_scoring_complete(machine.arrival_ms, False, False)\n")]),
 ("JMM-22", "the test helper that ticks to the request still stops at 5.0 s", [("tests/pt_scene.py", "        self.tick(advance_ms=t_a + 10000 - o.bve_time_ms)\n", "        self.tick(advance_ms=t_a + 5000 - o.bve_time_ms)\n")]),
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
    print("%-7s %s new=%d old=%d  %s" % (mid, "KILLED  " if bad else "SURVIVED", n_new, n_old, meaning[:120]))
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
