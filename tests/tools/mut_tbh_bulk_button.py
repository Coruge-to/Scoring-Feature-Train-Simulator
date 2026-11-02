"""TB-H Stage 5a mutation harness for the bulk timing button (new file; the existing harness files mut_tbf.py / mut_tbg.py / mut_tbh.py / mut_tbh_arestop.py ... are NOT modified).
usage: python mut_tbh_bulk_button.py <harness dir with run_red.py> <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when at least one test of MODS fails.
Contract under test: the bulk button of the timing screen is shown only when a CHANGEABLE untimed station exists (the start of the Run and the crossed pair B are fixed and never counted); its label is ONE text
(変更可能な非採時駅を全て採時駅にする : A, no case split); the A key makes only changeable untimed stations of the screen timed, never the fixed ones; after a user change the same key is the reset (existing text, behaviour,
priority); the fixed reasons, the Run snapshot and the theoretical score (9100) are untouched.
Per mutant the line is printed:  ID  KILLED/SURVIVED  new=<n> old=<n>  and the first failing tests."""
import os
import subprocess
import sys

ROOT = sys.argv[2]
MU, MN = "menu_ui.py", "main.py"
NEW_MODULES = ("test_pt_tbh_bulk_timing_button",)
NEW_CLASSES = ("A_Label", "B_NoChangeableUntimed", "C_OneChangeableUntimed", "D_TheoreticalScoreAndC01Shape", "E_Dispatch")
MODS = list(NEW_MODULES) + ["test_pt_tbh_pairb_contract", "test_pt_tbd_timing_targets"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


LABEL = 'btn_a_text = "変更可能な非採時駅を全て採時駅にする : A"'
RESET = 'btn_a_text = "初期設定に戻す : A"'
SHOW_BULK = "        elif not default_all_timing:\n            show_btn = True"
CONTRACT_LAMBDA = "        is_untimed_by_contract = (lambda i: self.untimed_reason(i) is not None) if hasattr(self, 'untimed_reason') else (lambda i: i == s_idx)"
W_SKIP = "                if untimed_reason(self, idx) is not None: continue\n                if not getattr(self, 'station_list', [])[idx].get(\"is_timing\", False):"
M_SKIP = "            if untimed_reason(self, idx) is not None: continue        # Stage TB-H: the start and the crossed pair B are fixed untimed, never a user change\n"
IS_TIMING_HEAD = "        if untimed_reason(self, sta_idx) is not None:         # Stage TB-H:"
ALL_TARGETS = "            for idx in targets:\n                if untimed_reason(self, idx) is not None: continue\n                if not getattr"

# (id, meaning, [(file, old, new), ...])
M = [
 ("BM-01", "the writer of the A key no longer skips the fixed stations", [(MN, W_SKIP, "                if not getattr(self, 'station_list', [])[idx].get(\"is_timing\", False):")]),
 ("BM-02", "the fixed stations count as a user change in the A key (the first press clears instead of timing)", [(MN, M_SKIP, "")]),
 ("BM-03", "the screen counts the fixed stations for the button condition", [(MU, CONTRACT_LAMBDA, "        is_untimed_by_contract = (lambda i: False)")]),
 ("BM-04", "the bulk button is always shown", [(MU, SHOW_BULK, "        else:\n            show_btn = True")]),
 ("BM-05", "the bulk button is never shown", [(MU, SHOW_BULK, "        elif False:\n            show_btn = True")]),
 ("BM-06", "is_station_timing ignores the fixed reasons", [(MN, IS_TIMING_HEAD, "        if False:         # Stage TB-H:")]),
 ("BM-07", "the A key acts on every station of the list, not on the stations of the screen", [(MN, ALL_TARGETS, "            for idx in range(len(self.station_list)):\n                if untimed_reason(self, idx) is not None: continue\n                if not getattr")]),
 ("BM-08", "the label is the OLD text again", [(MU, LABEL, 'btn_a_text = "始発駅以外を採時駅にする : A"')]),
 ("BM-09", "the label is a case split on the pseudo-turnback (a different text when a PairSet exists)", [(MU, LABEL, 'btn_a_text = "変更可能な非採時駅を全て採時駅にする : A" if not getattr(getattr(self, "turnback_machine", None), "pairset", None) else "採点開始駅・例外駅以外を全て採時駅にする : A"')]),
 ("BM-10", "the label loses the final key hint", [(MU, LABEL, 'btn_a_text = "変更可能な非採時駅を全て採時駅にする"')]),
 ("BM-11", "the reset label text is changed (the reset keeps its existing text)", [(MU, RESET, 'btn_a_text = "初期設定へ戻す : A"')]),
 ("BM-12", "the bulk label has the priority over the reset (the two roles are swapped in the label)", [(MU, "        if is_modified_from_default:\n            show_btn = True", "        if False:\n            show_btn = True")]),
 ("BM-13", "the reset no longer clears the overrides (the key keeps only one role)", [(MN, "            self.user_timing_overrides.clear()\n        else:", "            pass\n        else:")]),
 ("BM-14", "the A key makes the changeable stations timed even when the screen differs from the data default (no reset role)", [(MN, "        if is_modified_from_default:\n            # 変更されているなら初期設定に戻す（クリア）", "        if False:\n            # 変更されているなら初期設定に戻す（クリア）")]),
 ("BM-15", "a fixed station whose data says untimed is counted in default_all_timing (the button shows for fixed stations only)", [(MU, "            if is_untimed_by_contract(idx): continue\n            st = getattr(self, 'station_list', [])[idx]\n            if not st.get(\"is_timing\", False):", "            st = getattr(self, 'station_list', [])[idx]\n            if not st.get(\"is_timing\", False):")]),
 ("BM-16", "the click zone 998 does not reach the A key sink (a third, different route)", [(MN, "                        elif action_idx == 998: # 一括採時ボタン\n                            self.toggle_all_timing()", "                        elif action_idx == 998: # 一括採時ボタン\n                            pass")]),
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
