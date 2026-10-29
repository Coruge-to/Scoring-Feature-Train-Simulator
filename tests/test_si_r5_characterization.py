"""Phase SI-R5.1 - the CHARACTERIZATION of the five 1 m reverse lookups (P01-P05) at fd431b4, kept as data (tests/si_r5_char_pins.json: "head" and "new").

What this file pins (it passes on fd431b4 and keeps passing while the stages of SI-R5.2 are implemented):
  INVARIANT   the scenes whose observable output is the SAME with the distance lookups and with the identity-based replacement (identity bound, index 0, last index, hold, pass station,
              Case 2, NEXTLOC = -1, scoring off): pinned for good.
  CHANGED     the scenes the replacement changes ON PURPOSE, each with its meaning:
                KNOWN-DEFECT     two stations within 1 m (B@1000 / C@1000.5, or both at 1000): the lowest index wins today, the target index decides after
                IDENTITY-MISSING the identity is missing / outside the list / does not match the position: today a distance fills it in, after the step is skipped
              Such a row is pinned to its HEAD answer until its stage is declared done in STAGE_DONE (the one line an implementation Stage edits: 'A' P03, 'B' P01+P04+P05, 'C' P02);
              from then on it is pinned to its NEW answer. Only the keys of the site (SITE_KEYS) are compared, so one stage never disturbs the rows of another.
The NEW answers are asserted as REDs in tests/red_si_r5_station_identity.py (class H_Characterization), which must fail on fd431b4 and pass on the replacement.
Isolation as tests/sia_rig.py (the real Overlay offscreen, every outside effect a recorder; nothing is written outside the redirected profile). Without PyQt6 every test is SKIPPED.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

STAGE_DONE = set()          # 'A' P03 | 'B' P01+P04+P05 | 'C' P02  -- edited by the implementation Stages of SI-R5.2

SITE_KEYS = {
    "P03": ("next_name", "next_timing", "rule"),
    "P04": ("popups", "score", "finished", "checkpoints", "scored_stop", "scored_time", "latch_index"),
    "P05": ("popups", "score", "finished", "checkpoints", "scored_stop", "scored_time", "latch_index"),
    "P02": ("popups", "score", "timing", "scored_time"),
}
STAGE_OF_SITE = {"P03": "A", "P04": "B", "P05": "B", "P02": "C"}

INVARIANT = (
    "P02_departure_index0_start_station", "P02_departure_pass_station_timing", "P02_departure_stop_station_timing",
    "P03_hud_next_bound", "P03_hud_nextloc_none", "P03_hud_not_scoring_mode_not_evaluated", "P03_hud_tgt_index0_and_last",
    "P04_hold_five_ticks_one_checkpoint", "P04_operational_stop_end_station", "P04_operational_stop_identity_bound",
    "P04_transition_tick_prev_differs_from_next_pass_to_opstop",
    "P05_normal_stop_identity_bound", "P05_normal_stop_last_index_terminal_end", "P05_normal_stop_station_index0",
)
CHANGED = {                     # scenario -> meaning
    "P02_departure_adjacent_pair_departing_C_1000p5": "KNOWN-DEFECT",
    "P02_departure_prev_position_mismatch": "IDENTITY-MISSING",
    "P02_departure_stop_station_prev_missing": "IDENTITY-MISSING",
    "P03_hud_adjacent_pair_target_C": "KNOWN-DEFECT",
    "P03_hud_next_tgt_unavailable": "IDENTITY-MISSING",
    "P03_hud_tgt_out_of_range": "IDENTITY-MISSING",
    "P04_operational_stop_adjacent_end_station_C": "KNOWN-DEFECT",
    "P04_operational_stop_end_station_tgt_unavailable": "IDENTITY-MISSING",
    "P04_operational_stop_tgt_unavailable": "IDENTITY-MISSING",
    "P05_adjacent_pair_B_1000_C_1000p5_target_is_C": "KNOWN-DEFECT",
    "P05_normal_stop_end_station_tgt_unavailable_not_terminal_flag": "IDENTITY-MISSING",
    "P05_normal_stop_tgt_unavailable": "IDENTITY-MISSING",
    "P05_same_place_B_C_1000_target_is_C": "KNOWN-DEFECT",
    "P05_tgt_out_of_range": "IDENTITY-MISSING",
}
_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-si-r5-char-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP["dir"].name)
    finally:
        for k, v in _TMP["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP["dir"].cleanup()
    if left:
        raise AssertionError("the module wrote into the redirected profile: %r" % (left,))


def site_of(name):
    return name.split("_")[0]


def subset(observation, site):
    return {k: observation[k] for k in SITE_KEYS[site] if k in observation}


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class Characterization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["si-r5-char"])
        import main
        import scoring_logic
        import si_r5_char_scenarios
        import sia_rig
        with open(os.path.join(HERE, "si_r5_char_pins.json"), encoding="utf-8") as f:
            cls.pins = json.load(f)
        cls.now = json.loads(json.dumps(si_r5_char_scenarios.run_all(main, scoring_logic, sia_rig)))

    def test_every_scenario_is_pinned_and_classified_once(self):
        names = set(self.now)
        self.assertEqual(names, set(self.pins["head"]))
        self.assertEqual(names, set(self.pins["new"]))
        classified = set(INVARIANT) | set(CHANGED)
        self.assertEqual(len(INVARIANT) + len(CHANGED), len(classified))
        self.assertEqual(names, classified, 'a scenario is neither INVARIANT nor CHANGED')

    def test_no_scenario_crashes(self):
        self.assertEqual([n for n, v in self.now.items() if "EXC" in v], [])

    def test_invariant_scenes_are_the_same_with_the_lookup_and_with_the_identity(self):
        for name in INVARIANT:
            site = site_of(name)
            with self.subTest(name):
                self.assertEqual(subset(self.pins["head"][name], site), subset(self.pins["new"][name], site), "the pins disagree: not invariant")
                self.assertEqual(subset(self.now[name], site), subset(self.pins["head"][name], site))

    def test_changed_scenes_are_pinned_to_their_stage(self):
        for name, meaning in sorted(CHANGED.items()):
            site = site_of(name)
            which = "new" if STAGE_OF_SITE[site] in STAGE_DONE else "head"
            with self.subTest("%s [%s -> %s]" % (name, meaning, which)):
                self.assertNotEqual(subset(self.pins["head"][name], site), subset(self.pins["new"][name], site), "not changed: should be INVARIANT")
                self.assertEqual(subset(self.now[name], site), subset(self.pins[which][name], site))

    def test_the_known_defect_rows_are_a_wrong_station_today(self):
        """The meaning of KNOWN-DEFECT: the HEAD answer names the LOWEST index of the two stations, the NEW answer names the target."""
        head, new = self.pins["head"], self.pins["new"]
        self.assertEqual(head["P03_hud_adjacent_pair_target_C"]["next_name"], "B")
        self.assertEqual(new["P03_hud_adjacent_pair_target_C"]["next_name"], "C")
        for name in ("P05_adjacent_pair_B_1000_C_1000p5_target_is_C", "P05_same_place_B_C_1000_target_is_C"):
            self.assertFalse(head[name]["finished"], name)
            self.assertTrue(new[name]["finished"], name)

    def test_the_identity_missing_rows_are_a_skip_after(self):
        """The meaning of IDENTITY-MISSING: today a distance fills the identity in (a score / a checkpoint / a name is produced), after nothing is produced."""
        head, new = self.pins["head"], self.pins["new"]
        self.assertEqual(new["P05_normal_stop_tgt_unavailable"]["popups"], [])
        self.assertEqual(new["P05_normal_stop_tgt_unavailable"]["checkpoints"], [0])
        self.assertEqual(new["P04_operational_stop_tgt_unavailable"]["checkpoints"], [0])
        self.assertEqual(new["P03_hud_next_tgt_unavailable"]["next_name"], "---")
        self.assertEqual(new["P03_hud_next_tgt_unavailable"]["rule"], ["SENTINEL", "SENTINEL"])
        self.assertNotEqual(head["P05_normal_stop_tgt_unavailable"]["popups"], [])
        self.assertNotEqual(head["P03_hud_next_tgt_unavailable"]["next_name"], "---")


if __name__ == "__main__":
    unittest.main()
