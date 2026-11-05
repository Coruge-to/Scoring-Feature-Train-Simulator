"""Stage P1 mutation harness: the EFFECTIVE STATION STATE (effective_station_state.py, its wiring in main.py / hud_ui.py, the SI-R2.3 selector of hud_target_contract.py, the PairSet READY check). It SUPERSEDES the TB-J
and TB-K harnesses (mut_tbj.py / mut_tbk.py mutated text that no longer exists: the old view body and the free-driving latch); their meaning lives on in TJ-* below (the Jump wait modes) and in EF-* (the latch is gone).
usage: python mut_effective.py <byte copy root> [id prefixes]
One mutant at a time on a THROW-AWAY byte copy of the FINAL tree (every file is restored after every mutant). A mutant is KILLED when a test of MODS fails (the first failing module stops the run of that mutant).
The byte copy must be at a SHORT path (e.g. C:\\Users\\tsuru\\tspm1); it needs the tests and the root sources, not .git."""
import os
import subprocess
import sys

ROOT = sys.argv[1]
ES, MN, HU, HC, RP = "effective_station_state.py", "main.py", "hud_ui.py", "hud_target_contract.py", "route_pairset.py"
MODS = ["test_hud_target_wiring_r23", "test_pt_tbj_remaining_time", "test_pt_tbj_discard_gate", "test_pt_effective_state", "test_pt_tbh_selfdrive_hud", "test_pt_tbk_free_driving"]


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" in raw)


# (id, meaning, [(file, old, new), ...])
M = [
 # -- the effective timetable (the Owner's required mutants)
 ("EF-01", "pair A departure suppression deleted", [(ES, "    elif role == Role.PAIR_A:\n        departure, departure_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK", "    elif False:\n        departure, departure_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK")]),
 ("EF-02", "pair B arrival suppression deleted", [(ES, "    if role == Role.PAIR_B:\n        arrival, arrival_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK", "    if False:\n        arrival, arrival_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK")]),
 ("EF-03", "pair A arrival is suppressed too", [(ES, "    elif role == Role.PAIR_A:\n        departure, departure_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK", "    elif role == Role.PAIR_A:\n        arrival, arrival_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK\n        departure, departure_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK")]),
 ("EF-04", "pair B departure is suppressed too", [(ES, "    if role == Role.PAIR_B:\n        arrival, arrival_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK", "    if role == Role.PAIR_B:\n        departure, departure_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK\n        arrival, arrival_source = None, TimeSource.SUPPRESSED_FOR_TURNBACK")]),
 ("EF-05", "A passed: the completed B arrival is shown (the raw arrival is used for the time)", [(ES, "            arrival, departure, _, _ = effective_times(inp.stations[effective_index], role)", "            arrival, departure = _defined(inp.stations[effective_index].sender_arrival_ms), effective_times(inp.stations[effective_index], role)[1]")]),
 ("EF-06", "B with the doors open does not show the departure of B (the arrival is always selected)", [(ES, "        if role in (Role.PAIR_A, Role.PAIR_B):\n            kind = TimeKind.DEPARTURE if inp.time_kind == \"DEPARTURE\" else TimeKind.ARRIVAL", "        if role in (Role.PAIR_A, Role.PAIR_B):\n            kind = TimeKind.ARRIVAL")]),
 ("EF-07", "a missing B departure is an ordinary --:-- in free driving (no contract violation)", [(ES, "if role == Role.PAIR_B and kind == TimeKind.DEPARTURE:", "if False:")]),
 ("EF-08", "a missing B departure after the landing is an ordinary --:--", [(ES, "            if selected is None:\n                violation = CONTRACT_PAIR_B_DEPARTURE\n", "            if selected is None:\n                pass\n")]),
 ("EF-09", "a missing B departure after the landing falls back to the display time (the completed arrival)", [(ES, "            selected = effective_times(row, Role.PAIR_B)[1]\n", "            selected = effective_times(row, Role.PAIR_B)[1] or display_time\n")]),
 ("EF-10", "an ordinary station is suppressed like a pair A", [(ES, "        else:\n            roles[s.index] = Role.NORMAL", "        else:\n            roles[s.index] = Role.PAIR_A")]),
 ("EF-11", "the terminal contract is broken (the terminal selects no arrival)", [(ES, "            if role in (Role.PASS, Role.TERMINAL):\n                kind = TimeKind.ARRIVAL", "            if role in (Role.PASS,):\n                kind = TimeKind.ARRIVAL")]),
 ("EF-12", "the PairSet readiness is ignored (the pairs suppress without being trusted)", [(ES, "    a_set = {a for a, b in inp.pairs} if inp.pairset_ready else set()", "    a_set = {a for a, b in inp.pairs}")]),
 ("EF-13", "derive rewrites its input", [(ES, "def derive(inp):\n    n = len(inp.stations)", "def derive(inp):\n    object.__setattr__(inp, \"now_ms\", 0)\n    n = len(inp.stations)")]),
 ("EF-14", "derive keeps a module-level store (a second state)", [(ES, "def derive(inp):\n    n = len(inp.stations)", "_SEEN = []\n\n\ndef derive(inp):\n    _SEEN.append(inp)\n    n = len(inp.stations)")]),
 ("EF-15", "the effective target of a live chain is the raw official target", [(ES, "effective_index = machine.held_a_index if _index_ok(machine.held_a_index, n) else scoring_index", "effective_index = cursor_index")]),
 ("EF-16", "the free-driving branch is preferred while scoring", [(ES, "    elif sc.active:\n        effective_index = scoring_index", "    elif False:\n        effective_index = scoring_index")]),
 ("EF-17", "a scoring Run that does not cross a pair is given the pair B departure rule", [(ES, "        if sc.crosses_pair and scoring_index is not None and scoring_index in sc.crossed_b_indexes:", "        if True:")]),
 # -- the Jump wait modes (the meaning of the old TJ-* mutants)
 ("TJ-01", "the countdown rounds down", [(HU, "count_s = max(0, -(-int(effective_state.countdown_ms) // 1000))", "count_s = max(0, int(effective_state.countdown_ms) // 1000)")]),
 ("TJ-02", "the countdown rounds to the nearest second", [(HU, "count_s = max(0, -(-int(effective_state.countdown_ms) // 1000))", "count_s = max(0, int(round(int(effective_state.countdown_ms) / 1000.0)))")]),
 ("TJ-03", "the countdown can go negative", [(HU, "count_s = max(0, -(-int(effective_state.countdown_ms) // 1000))", "count_s = -(-int(effective_state.countdown_ms) // 1000)")]),
 ("TJ-05", "the departure of B is not used for the display", [(HU, "shown_time = effective_state.selected_time_ms or 0", "shown_time = 0")]),
 ("TJ-06", "the countdown is off by a second (a second timer)", [(ES, "countdown, jump_deadline = deadline - inp.now_ms, deadline", "countdown, jump_deadline = deadline - inp.now_ms + 1000, deadline")]),
 ("TJ-07", "the cancelled wait is a request", [(ES, "turnback_state, mode = TurnbackState.CANCELLED, RemainingMode.TURNBACK_CANCELLED", "turnback_state, mode = TurnbackState.CANCELLED, RemainingMode.TURNBACK_REQUESTED")]),
 ("TJ-08", "00:00 is released after the Jump request", [(ES, "mode, countdown = RemainingMode.TURNBACK_REQUESTED, 0", "mode, countdown = RemainingMode.NORMAL_TIMETABLE, None")]),
 ("TJ-09", "the departure of B is never used after the landing", [(ES, "            selected = effective_times(row, Role.PAIR_B)[1]\n", "            selected = None\n")]),
 ("TJ-15", "the first window and the re-stop window are swapped (the TB-J mode mapping)", [(ES, "mode = RemainingMode.TURNBACK_INITIAL_COUNTDOWN if machine.restop_count == 0 else RemainingMode.TURNBACK_RESTOP_COUNTDOWN", "mode = RemainingMode.TURNBACK_RESTOP_COUNTDOWN if machine.restop_count == 0 else RemainingMode.TURNBACK_INITIAL_COUNTDOWN")]),
 ("TJ-16", "the chain is never alive (the machine is not read)", [(MN, "alive = turnback_held_a_target(self) is not None", "alive = False")]),
 ("TJ-17", "the Run never crosses (no crossed B)", [(MN, "crossed = turnback_b_indexes(self)", "crossed = frozenset()")]),
 # -- SI-R2.3, the door, the wiring
 ("SR-01", "the selector always selects the arrival", [(MN, "hud_target_contract.select_time_kind(self.bve_door, cursor.location, self.bve_location)", "\"ARRIVAL\"")]),
 ("SR-02", "the selector boundary moves (<= instead of < NEAR_M)", [(HC, "abs(official_location - location) < NEAR_M", "abs(official_location - location) <= NEAR_M")]),
 ("SR-03", "the door is read a second time for something else", [(MN, "bool(self.hud_target_timing), scoring_view)", "bool(self.hud_target_timing or self.bve_door), scoring_view)")]),
 ("SR-04", "the door state is dropped from the selector (door ignored)", [(HC, "return KIND_DEPARTURE if (door != 0 and abs(official_location - location) < NEAR_M) else KIND_ARRIVAL", "return KIND_DEPARTURE if (abs(official_location - location) < NEAR_M) else KIND_ARRIVAL")]),
 ("WI-01", "the old free-driving latch is brought back", [(MN, "    def _effective_rows(self):", "    def free_turnback_a_time_suppressed(self):\n        return False\n\n    def _effective_rows(self):")]),
 ("WI-02", "the HUD time row reads the raw display target time again", [(HU, "shown_time = effective_state.selected_time_ms or 0", "shown_time = self.hud_target_next_time")]),
 ("RP-01", "the PairSet READY check is ignored by the intake", [(RP, "            violation = pair_check(decoded)", "            violation = None")]),
 ("RP-02", "the READY check never finds a missing B departure", [(ES, "        if row_b is None or _defined(row_b.sender_departure_ms) is None:\n            return CONTRACT_PAIR_B_DEPARTURE", "        if False:\n            return CONTRACT_PAIR_B_DEPARTURE")]),
 ("RP-03", "the READY check is not passed by the application", [(MN, "route_pairset.sync(self, turnback_machine_of, self._pair_time_check)", "route_pairset.sync(self, turnback_machine_of)")]),
]


def run():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("RT_ROOT", None)
    env.pop("QT_QPA_PLATFORM", None)
    bad, ran = [], 0
    for mod in MODS:
        r = subprocess.run([sys.executable, "-B", os.path.join("tests", mod + ".py")], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        ran += 1
        fails = [l for l in r.stderr.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
        if r.returncode != 0 or fails:
            bad = fails or ["%s exit %d: %s" % (mod, r.returncode, r.stderr[-200:].replace("\n", " "))]
            bad = [("%s :: %s" % (mod, b)) for b in bad]
            break
    return bad, ran


only = sys.argv[2:] if len(sys.argv) > 2 else None
base_bad, ran = run()
print("BASELINE of the mutation modules: failing=%d (modules run=%d of %d)" % (len(base_bad), ran, len(MODS)))
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
        bad, ran = run()
    finally:
        for f, (orig, crlf, text) in files.items():
            open(os.path.join(ROOT, f), "wb").write(orig.encode("utf-8"))
    print("%-6s %s %s" % (mid, "KILLED  " if bad else "SURVIVED", meaning[:100]))
    if bad:
        print("      first: " + bad[0][:170])
        killed += 1
    else:
        survivors.append(mid)
print("KILLED %d SURVIVORS %s NOT-APPLICABLE %s" % (killed, survivors, na))
sys.exit(0 if not survivors and not na else 1)
