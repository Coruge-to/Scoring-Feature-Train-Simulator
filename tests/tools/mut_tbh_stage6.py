"""TB-H Stage 6 mutation harness (new file; the existing harness files are NOT modified).
usage: python mut_tbh_stage6.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test (Owner, after the C-11 live run): B reached by driving from the pending A is the unrecoverable failure: fail-closed as before (no Jump, B not scored, no checkpoint, scoring abort, internal reason
pseudo-turnback-self-drive-b) and now the red two-line user warning 不正な移動が検知されました。／採点を中止します。; the illegal-Jump warning has the SAME user wording and a different internal trace; moving away from A is
recoverable; the HUD target is the pair A exactly while the re-stop wait lasts (display layer only: the raw target, the scoring target and the StationIndex are never changed).
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
SL, PM, MAIN = "scoring_logic.py", "pseudo_turnback_machine.py", "main.py"
NEW_MODULES = ("test_pt_tbh_selfdrive_hud",)
NEW_CLASSES = ("A_SelfDriveB", "B_HudTarget")
MODS = list(NEW_MODULES) + ["test_pt_tbh_arestop", "test_pt_tbc_request", "test_pt_tbd_retry"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


TEXTS = 'ILLEGAL_MOVE_TEXTS = ("不正な移動が検知されました。", "採点を中止します。")'
JUMP_LOOP = '            for text in ILLEGAL_MOVE_TEXTS:\n                add_score_popup(self, 0, text, COLOR_B_EMG, "big", "警告", current_time, force=True)\n'
SHOW_CALL = "            turnback_stop_scoring(self, act[1])\n            turnback_illegal_move_show(self)\n            aborted = True\n"
SHOW_BODY = '        add_score_popup(self, 0, text, COLOR_B_EMG, "big", "警告", now, force=True)\n'
DROP_THEN_IF = '        turnback_drop_popups(self)\n        if act[0] == "abort_scoring_self_drive_b":\n'
STOP_DIAG = '    turnback_diag(self, "turnback-fail", reason=reason)\n\n\ndef official_jump_f1_hold'
HOLD_RETURN = "    return kept[1]\n"
HOLD_STATE = "    if machine is None or not (machine.state in pseudo_turnback_machine.LIVE or machine.awaiting_b) or not turnback_session_active(self):\n        return None\n"
HOLD_MATCH = "    if not kept or kept[0] != machine.arrival_ms:\n        return None\n"
MAIN_USE = "        held = turnback_held_a_target(self)\n        if held is not None:\n            return held\n"

# (id, meaning, [(file, old, new), ...])
M = [
 ("S6M-01", "the user wording is the old illegal-Jump line 1", [(SL, TEXTS, 'ILLEGAL_MOVE_TEXTS = ("不正なジャンプを検知しました。", "採点を中止します。")')]),
 ("S6M-02", "the user wording is the old illegal-Jump line 2", [(SL, TEXTS, 'ILLEGAL_MOVE_TEXTS = ("不正な移動が検知されました。", "採点を中断します。")')]),
 ("S6M-03", "the illegal Jump shows only the first line", [(SL, JUMP_LOOP, JUMP_LOOP.replace("ILLEGAL_MOVE_TEXTS:", "ILLEGAL_MOVE_TEXTS[:1]:"))]),
 ("S6M-04", "B reached by driving shows no user warning (diagnostics only again)", [(SL, SHOW_CALL, "            turnback_stop_scoring(self, act[1])\n            aborted = True\n")]),
 ("S6M-05", "the warning of B by driving is not forced (the popup is refused while the scoring is off)", [(SL, SHOW_BODY, SHOW_BODY.replace(", force=True", ""))]),
 ("S6M-06", "the warning of B by driving is not red", [(SL, SHOW_BODY, SHOW_BODY.replace("COLOR_B_EMG", "COLOR_WHITE"))]),
 ("S6M-07", "the warning of B by driving is shown for any dropped wait state too", [(SL, DROP_THEN_IF, "        turnback_drop_popups(self)\n        turnback_illegal_move_show(self)\n        if act[0] == \"abort_scoring_self_drive_b\":\n")]),
 ("S6M-08", "every internal failure shows the user warning (OD-TB-30 broken)", [(SL, STOP_DIAG, '    turnback_diag(self, "turnback-fail", reason=reason)\n    turnback_illegal_move_show(self)\n\n\ndef official_jump_f1_hold')]),
 ("S6M-09", "the internal reason of B by driving is the illegal-Jump one", [(PM, 'SELF_DRIVE_B_REASON = "pseudo-turnback-self-drive-b"', 'SELF_DRIVE_B_REASON = "pseudo-turnback-illegal-jump"')]),
 ("S6M-10", "an illegal Jump writes a pseudo-turnback failure line (the two causes are no longer distinguishable)", [(SL, JUMP_LOOP, JUMP_LOOP + '            turnback_diag(self, "turnback-fail", reason="pseudo-turnback-self-drive-b")\n')]),
 ("S6M-11", "the abort of B by driving forgets to stop the scoring", [(SL, SHOW_CALL, "            turnback_illegal_move_show(self)\n            aborted = True\n")]),
 ("S6M-12", "the held HUD target is never returned", [(SL, HOLD_RETURN, "    return None\n")]),
 ("S6M-13", "the hold is released by the re-stop (only the re-stop wait is held: the old candidate)", [(SL, HOLD_STATE, "    if machine is None or machine.state != pseudo_turnback_machine.RESTOP_WAIT or not turnback_session_active(self):\n        return None\n")]),
 ("S6M-14", "an older arrival's capture is used", [(SL, HOLD_MATCH, "    if not kept:\n        return None\n")]),
 ("S6M-16", "the application's HUD derivation does not use the held target", [(MAIN, MAIN_USE, "")]),
 ("S6M-17", "the held target depends on a door", [(SL, HOLD_STATE, "    if machine is None or not (machine.state in pseudo_turnback_machine.LIVE or machine.awaiting_b) or getattr(self, 'bve_door', 0) == 99 or not turnback_session_active(self):\n        return None\n")]),
 ("S6M-18", "the held target writes into the raw target", [(SL, HOLD_RETURN, "    self.bve_next_loc = kept[1].next_loc\n    return kept[1]\n")]),
 ("S6M-19", "the hold is never released by the end of the chain (the state is not tested)", [(SL, HOLD_STATE, "    if machine is None or not turnback_session_active(self):\n        return None\n")]),
 ("S6M-20", "the hold is released when the Jump is requested (only the waiting states are held)", [(SL, HOLD_STATE, "    if machine is None or not (machine.state in pseudo_turnback_machine.WAITING or machine.awaiting_b) or not turnback_session_active(self):\n        return None\n")]),
 ("S6M-21", "the hold is released when the Jump completes, before B is established", [(SL, HOLD_STATE, "    if machine is None or not (machine.state in pseudo_turnback_machine.LIVE) or not turnback_session_active(self):\n        return None\n")]),
 ("S6M-22", "the rule overlay names B (the departure of the pair) instead of A", [(SL, "    return stations[pair.arrival].get('name', '不明な駅'), bool(held.timing)\n", "    return stations[pair.departure].get('name', '不明な駅'), bool(held.timing)\n")]),
 ("S6M-23", "the rule overlay line ignores the held station", [("hud_ui.py", "        if held_station is not None:\n            n_sta, n_timing = held_station\n", "")]),
 ("S6M-24", "the rule overlay shows the held station even without a held target (a stale name)", [(SL, "    if held is None or pair is None or not stations or not (0 <= pair.arrival < len(stations)):\n        return None\n", "    if pair is None or not stations or not (0 <= pair.arrival < len(stations)):\n        return None\n")]),
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
