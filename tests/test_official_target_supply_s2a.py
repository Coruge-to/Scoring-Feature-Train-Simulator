"""Phase SI-R2.2-S2a (C2b): the OFFTGT part reaches the Overlay as six published values - and nothing reads them yet.

Integration tests of the real Overlay (tests/sia_rig.py: every outside effect a recorder) with the wire fixture of section A. The pure half (decode / evaluate / advance) is
test_official_target_contract_s2a.py. These rows need PyQt6 (Gate B); an interpreter that hides it skips them (Gate A).

  A  the defaults and the published names (telemetry_contract) and the intake points of main.py
  B  the supply profile: every meaning vector of the supply file, its HUD expectations removed (the HUD is SI-R2.3), reads back as the state it names
  C  ABSENT compatibility: a line without the part is today's behaviour; the part changes no other plain attribute
  D  boundaries: generation (reset / epoch), scenario (the grace restarts), process (a new Overlay is NOT_INITIALIZED), the three evaluation moments
  E  the staged-green ledger: the 13 rows of the three RED runners that become GUARD in S2a, and only those
  F  the naming rule of main.py (LJX-1) and the unread-by-HUD/scoring guard
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import official_target_contract as C  # noqa: E402
import official_target_wire_fixture as F  # noqa: E402
import telemetry_contract as tc  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None
OFFICIAL_NAMES = tuple(sorted(C.initial_state()))

# the 13 rows of the RED runners that turn from RED-VALID to GUARD when S2a (the supply of the six values) is implemented; every other row keeps the verdict it had at 6655333
S2A_GREEN_ROWS = {
    "supply": ("R-OFF-05", "R-OFF-06", "R-OFF-07", "R-OFF-08", "R-STATE-3", "R-GEN-2", "R-INIT-1", "R-INIT-5"),
    "ownership": ("R-SEM-01", "R-TERM-2"),
    "reinit": ("R-REINIT-F5-1", "R-REINIT-F5-2", "R-REINIT-F5-3"),
}
# SI-R2.2-S2b (intended update, OD-S2B-2) turns more rows to GUARD, stage by stage: the C# senders write the part. C3a (the shared reader and wire helper, the Legacy sender) turns R-CS-SRC-02;
# C3b (the Current sender) turns R-CS-SRC-01 / 04 / 08. This ledger is the staged-green boundary of the commit it stands in; the meaning contract (decode / evaluate / supply) is not touched.
S2B_GREEN_ROWS = {
    "supply": ("R-CS-SRC-02",),
}
EXPECTED_AFTER_S2A = {"RED-VALID": 49, "GUARD": 42}                      # S2a: 50 / 41; S2b C3a: 49 / 42
# the 50 rows that stay RED after S2a fail only for reasons that belong to a later stage: the HUD (SI-R2.3: HUD-DIST / HUD-TIMELEFT / NOT-EQUIVALENT-TO-CSHARP), the C# supply
# (S2b: the named NOT-IMPLEMENTED words) and the distance search (SI-R2.4: CURRENT- / LEGACY- / DISTANCE-SEARCH-REMAINS). A supply, state, index, location or reason word is a defect of S2a.
REMAINING_RED_WORD = re.compile(r"^(HUD-DIST:|HUD-TIMELEFT:|NOT-EQUIVALENT-TO-CSHARP|CURRENT-|LEGACY-|DISTANCE-SEARCH-REMAINS|"
                                r"NOT-IMPLEMENTED:(current-calls-helper|helper-in-shared|legacy-calls-helper|helper-absent|no-official-part-in-current))")


def read_source(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class A_DefaultsAndIntake(unittest.TestCase):
    def test_the_defaults_carry_the_six_published_values(self):
        defaults = tc.telemetry_state_defaults()
        self.assertEqual({k: defaults[k] for k in OFFICIAL_NAMES}, C.initial_state())

    def test_the_initial_state_is_distinct_from_every_wire_state(self):
        self.assertEqual(C.initial_state()["official_state"], "NOT_INITIALIZED")
        self.assertNotIn(C.initial_state()["official_state"], set(C.WIRE_TO_STATE.values()))

    def test_the_part_is_a_known_telemetry_token_and_never_required(self):
        self.assertIn(C.PART_NAME, tc.TOKEN_KEYS["station"])
        for required in tc.REQUIRED_KEYS:
            self.assertNotIn(C.PART_NAME, required if isinstance(required, str) else tuple(required))

    def test_the_published_names_are_the_fixture_names(self):
        self.assertEqual(set(OFFICIAL_NAMES), set(F.OFFICIAL_ATTRS.values()))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class _QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = F.harness_init()
        if env:
            raise unittest.SkipTest("the real Overlay can not run here: " + env)
        cls.vec = F.load_vectors()

    @classmethod
    def tearDownClass(cls):
        left = F.harness_leftovers()
        if left:
            raise AssertionError("the run wrote into the redirected profile: %s" % left)


def supply_profile(step):
    """The supply vectors with their HUD expectations removed: S2a publishes the values, the HUD reads them in SI-R2.3."""
    ex = step.get("expect")
    if ex:
        for key in ("hud_dist", "hud_time_left", "hud_dist_either", "hud_time_left_either", "target_nextloc", "target_nexttime", "alt_target_nextloc", "alt_target_nexttime", "owner"):
            ex.pop(key, None)


class B_SupplyProfile(_QtCase):
    def run_supply(self, case_id):
        """The vector on a fresh Overlay; the sender's own advance_ms also moves the Overlay's clock (the 3,000 ms grace is a fact about the data, not about this machine)."""
        ctx = F.Ctx()
        case = F.case_by_id(self.vec, case_id)
        with F.Scene(self.vec, strict=case.get("strict", False)) as sc:
            sc.load_list(case["list"])
            for n, step in enumerate(case["steps"]):
                step = json.loads(json.dumps(step))
                supply_profile(step)
                sc.rig.clock.now += step.get("advance_ms", 0) / 1000.0
                sc.step(step)
                F.check_expect(ctx, sc, step, "%s#%d" % (case_id, n))
        self.assertEqual(ctx.premise_fail, [], case_id)
        self.assertEqual(ctx.contract_fail, [], case_id)

    def test_every_supply_vector_reads_back(self):
        ids = [c["id"] for c in self.vec["cases"] if c["file"] == "supply"]
        self.assertGreaterEqual(len(ids), 15)
        for case_id in ids:
            with self.subTest(case=case_id):
                self.run_supply(case_id)

    def test_the_reset_returns_the_defaults(self):
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"loc": 2500.0, "machine": {"nextloc": 3000.0, "nexttime": 36660000, "tgt": 3}, "official": {"state": "K", "index": 3}})
            self.assertEqual(sc.official()["state"], "KNOWN")
            sc.o.reset_telemetry_state()
            self.assertEqual({a: getattr(sc.o, a) for a in OFFICIAL_NAMES}, C.initial_state())


def plain_values(overlay):
    basic = (int, float, str, bool, type(None), list, tuple, dict, set, frozenset)
    skip = set(OFFICIAL_NAMES) | {"last_update_time", "last_udp_time"}
    return {k: repr(v) for k, v in sorted(vars(overlay).items()) if not k.startswith("_") and k not in skip and isinstance(v, basic)}


class C_AbsentCompatibility(_QtCase):
    def lines(self, sc, with_part):
        steps = [
            {"loc": 100.0, "machine": {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}},
            {"loc": 600.0, "machine": {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}},
            {"loc": 1100.0, "machine": {"nextloc": 2000.0, "nexttime": 36360000, "tgt": 2}},
        ]
        for i, step in enumerate(steps):
            if with_part:
                step = dict(step, official={"state": "K", "index": step["machine"]["tgt"]})
            sc.step(step)

    def test_a_line_without_the_part_is_absent_and_a_part_changes_no_other_plain_attribute(self):
        seen = []
        hud = []
        for with_part in (False, True):
            with F.Scene(self.vec, strict=False) as sc:
                sc.load_list("L5")
                self.lines(sc, with_part)
                seen.append((sc.official()["state"], plain_values(sc.o)))
                hud.append(dict(sc.hud))
        self.assertEqual(seen[0][0], "ABSENT")
        self.assertEqual(seen[1][0], "KNOWN")
        self.assertEqual(seen[0][1], seen[1][1])
        self.assertEqual(hud[0], hud[1])

    def test_absent_publishes_the_sentinel_and_never_a_target(self):
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"loc": 100.0, "machine": {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}})
            self.assertEqual({a: getattr(sc.o, a) for a in OFFICIAL_NAMES}, dict(C._result(C.ABSENT, C.R_MISSING)))
            self.assertEqual(sc.o.bve_next_loc, 1000.0)
            self.assertEqual(sc.o.bve_tgt_idx, 1)

    def test_a_part_never_reaches_the_machine_target_or_the_identity(self):
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"loc": 100.0, "machine": {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}, "official": {"state": "K", "index": 3}})
            self.assertEqual(sc.official()["index"], 3)
            self.assertEqual((sc.o.bve_next_loc, sc.o.bve_next_time, sc.o.bve_tgt_idx), (1000.0, 36060000, 1))

    def test_a_later_line_without_the_part_does_not_keep_the_earlier_value(self):
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"loc": 100.0, "machine": {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}, "official": {"state": "K", "index": 3}})
            self.assertEqual(sc.official()["state"], "KNOWN")
            sc.step({"loc": 150.0})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("ABSENT", -1))

    def test_a_duplicate_part_is_ignored_after_the_first(self):
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            text = sc.telemetry_text(dict(sc.state, official={"state": "K", "index": 2})) + "," + F.build_part({"state": "T"}, sc.list_id, sc.count, sc.stations)
            sc.push(text)
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 2))


class D_Boundaries(_QtCase):
    def test_a_new_overlay_is_not_initialized(self):
        with F.Scene(self.vec, strict=False) as sc:
            self.assertEqual({a: getattr(sc.o, a) for a in OFFICIAL_NAMES}, C.initial_state())

    def test_a_list_alone_does_not_judge_before_any_line(self):
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            self.assertEqual(sc.official()["state"], "NOT_INITIALIZED")

    def test_the_epoch_reset_returns_the_defaults_and_the_first_line_judges_again(self):
        with F.Scene(self.vec, strict=True) as sc:
            sc.load_list("L5")
            sc.step({"generation": 1, "sid": 7, "loc": 2500.0, "machine": {"nextloc": 3000.0, "nexttime": 36660000, "tgt": 3}, "official": {"state": "K", "index": 3}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 3))
            sc.o.telemetry_gate.on_generation(2)
            sc.step({"generation": 2, "sid": 8, "list": "L5", "loc": 100.0, "machine": {"nextloc": 1000.0, "nexttime": 36060000, "tgt": 1}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("ABSENT", -1))
            sc.step({"loc": 150.0, "official": {"state": "K", "index": 2}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 2))

    def test_a_scenario_change_restarts_the_grace(self):
        bad = {"state": "K", "index": 2, "hash_override": "DEADBEEF"}
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"sid": 7, "loc": 500.0, "official": bad})
            self.assertEqual(sc.official()["state"], "NOT_INITIALIZED")
            sc.rig.clock.now += 3.1
            sc.step({"sid": 7, "loc": 510.0, "official": bad})
            self.assertEqual(sc.official()["state"], "INVALID")
            sc.rig.clock.now += 0.1
            sc.step({"sid": 8, "loc": 520.0, "official": bad})
            self.assertEqual(sc.official()["state"], "NOT_INITIALIZED")           # a new scenario starts its own 3,000 ms
            sc.rig.clock.now += 3.1
            sc.step({"sid": 8, "loc": 530.0, "official": bad})
            self.assertEqual(sc.official()["state"], "INVALID")

    def test_the_grace_ends_at_three_thousand_milliseconds_of_the_clock(self):
        bad = {"state": "K", "index": 2, "count_override": 6}
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"loc": 500.0, "official": bad})
            sc.rig.clock.now += 3.0
            sc.step({"loc": 501.0, "official": bad})
            self.assertEqual(sc.official()["state"], "NOT_INITIALIZED")
            sc.rig.clock.now += 0.001
            sc.step({"loc": 502.0, "official": bad})
            self.assertEqual((sc.official()["state"], sc.official()["reason"]), ("INVALID", "off-list-mismatch"))

    def test_the_list_adopted_right_after_the_line_judges_it_again(self):
        # managed order (second moment): the line is applied while the list it belongs to is still pending, the list is adopted right after it. Without the second
        # judgement the line would stay NOT_INITIALIZED until the next line.
        with F.Scene(self.vec, strict=True) as sc:
            sc.step({"list": "L4", "loc": 100.0, "official": {"state": "K", "index": 1}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 1))
            sc.step({"list": "L5", "loc": 110.0, "official": {"state": "K", "index": 4}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 4))

    def test_a_station_list_alone_never_judges_again(self):
        # normal mode: the list is adopted when its datagram arrives; no judgement happens until the next line (nothing is re-read without a line)
        with F.Scene(self.vec, strict=False) as sc:
            sc.load_list("L4")
            sc.step({"loc": 100.0, "official": {"state": "K", "index": 1}})
            self.assertEqual(sc.official()["state"], "KNOWN")
            sc.load_list("L5")
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 1))
            sc.step({"loc": 110.0, "official": {"state": "K", "index": 4}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 4))

    def test_the_held_line_and_its_held_list_are_judged_together(self):
        # managed order (third moment): the sender is ahead, so the line and the list that came with it are held; apply_held_telemetry applies the line (the old list is still
        # adopted: not ready) and then adopts the held list, which must judge the line again. Without that judgement the line would stay NOT_INITIALIZED until the next line.
        with F.Scene(self.vec, strict=True) as sc:
            sc.step({"generation": 1, "sid": 7, "list": "L5", "loc": 2500.0, "official": {"state": "K", "index": 3}})
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 3))
            sc.step({"sid": 8, "list": "L4", "loc": 100.0, "official": {"state": "K", "index": 1}})
            self.assertEqual(sc.o.telemetry_gate.last_verdict, "held")
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 3))              # a held line is not applied: nothing changes yet
            held = sc.o.telemetry_gate.on_generation(2)
            self.assertTrue(held)
            sc.o.apply_held_telemetry(held)
            self.assertEqual((sc.official()["state"], sc.official()["index"]), ("KNOWN", 1))

    def test_the_held_line_is_judged_when_the_generation_arrives(self):
        ctx = F.Ctx()
        F.run_case(ctx, self.vec, F.case_by_id(self.vec, "SUP-N6"), mutate=supply_profile)
        self.assertEqual((ctx.premise_fail, ctx.contract_fail), ([], []))


def run_red(runner):
    proc = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "tests", "red_official_target_%s.py" % runner), "--expect", "red"], cwd=ROOT, capture_output=True, timeout=300)
    rows = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) == 5 and not line.startswith(("UNEXPECTED", "SUMMARY")):
            rows[cells[0]] = (cells[2], cells[3], cells[4])
    return proc.returncode, rows


class E_StagedGreen(_QtCase):
    """The staged-green ledger: exactly the rows of S2A_GREEN_ROWS (13, S2a) and S2B_GREEN_ROWS (S2b, as far as its commits go) moved, every other row kept its verdict (the intended remainder belongs to S2b, SI-R2.3 and SI-R2.4). The name of the test is kept for the ledger of earlier reports."""

    def test_exactly_the_thirteen_rows_become_guard(self):
        verdicts = {}
        for runner in ("supply", "ownership", "reinit"):
            code, rows = run_red(runner)
            self.assertGreater(len(rows), 15, runner)
            for rid, (verdict, predicted, reason) in rows.items():
                verdicts[(runner, rid)] = (verdict, predicted, reason)
        self.assertEqual(len(verdicts), 91)
        moved = {key for key, (verdict, predicted, _r) in verdicts.items() if verdict != predicted}
        expected = {(runner, rid) for runner, ids in S2A_GREEN_ROWS.items() for rid in ids} | {(runner, rid) for runner, ids in S2B_GREEN_ROWS.items() for rid in ids}
        self.assertEqual(sorted(moved), sorted(expected))
        for key in expected:
            self.assertEqual(verdicts[key][0], "GUARD", key)
            self.assertEqual(verdicts[key][1], "RED-VALID", key)
        counts = {}
        for verdict, _p, _r in verdicts.values():
            counts[verdict] = counts.get(verdict, 0) + 1
        self.assertEqual(counts, EXPECTED_AFTER_S2A)
        for key, (verdict, predicted, reason) in verdicts.items():
            if verdict == "RED-VALID":
                for word in reason.split("+"):
                    self.assertRegex(word, REMAINING_RED_WORD, "%s: %s" % (key, word))


class F_Naming(unittest.TestCase):
    def test_main_py_adds_no_identifier_that_carries_the_official_word(self):
        # tests/ljx1_contract_regions.py counts every statement that names `official` as part of the jump contract: the supply of the six values uses the wire name `offtgt`.
        text = read_source("main.py")
        for name in OFFICIAL_NAMES:
            self.assertNotIn(name, text)
        self.assertEqual(re.findall(r"\bofficial_target_contract\b", text), ["official_target_contract"])
        self.assertIn("offtgt", text)

    def test_the_hud_and_the_scoring_do_not_read_the_published_values(self):
        for rel in ("hud_ui.py", "scoring_logic.py", "managed_input.py"):
            text = read_source(rel)
            for name in OFFICIAL_NAMES:
                self.assertNotIn(name, text, rel)

    def test_the_machine_target_is_still_written_in_three_places_only(self):
        counts = {rel: len(re.findall(r"self\.bve_next_loc\s*=[^=]", read_source(rel))) for rel in ("main.py", "network.py")}
        self.assertEqual(counts, {"main.py": 2, "network.py": 1})


if __name__ == "__main__":
    unittest.main()
