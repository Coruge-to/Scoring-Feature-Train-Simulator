"""INITIAL-DEFAULTS Stage F1: the left-over 70 of the A boundary (Owner 2026-11-11). RED-only: the product code is not changed.

The 70s are classified by ROLE and CALL PATH (never by a line number; the sites are found by the code around the literal):
  A boundary - introduction default         Overlay.__init__            self.rank_a_ratio = <v>                                         must be 0.6
  A boundary - input fallback               F1 Enter of page 3/3        ... a_rank_percent_valid(val) else <v>                          must be 0.6
  F1 display default                        menu_ui.draw_menu (twice)   getattr(self, 'rank_a_ratio', <v>)                              must be 0.6   (page 3/3 and the result screen)
  scoring settings generation default       scoring_settings.LIVE / build  ("rank_a_ratio", <v>) / getattr(overlay, "rank_a_ratio", <v>)  must be 0.6
  (already 60)                              Overlay._apply_initial_defaults  ... else 0.6                                              stays 0.6
  ANOTHER contract - must NOT become 60     rank_multi 0.7 (the B / C decay multiplier: main.py once, menu_ui twice), PRESETS['advanced'] A boundary 70 (the 上級 preset), layout pixels, budgets
The aggregate test fails while ANY site of the A boundary fallback group keeps 0.7; the 'must not change' tests fail if a blanket 70 -> 60 replacement is made."""
import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import idf1_red_support as X  # noqa: E402
import sia_rig as R  # noqa: E402


def setUpModule():
    X.redirect_profile("ts-idf1-f70-")


def tearDownModule():
    X.restore_profile()


# id, file, role, regex (group 1 = the literal), expected number of occurrences
A_RANK_FALLBACK_SITES = (
    ("main.overlay_init_default", "main.py", "A boundary: introduction default (Overlay construction, before the first SCENARIO_ID)", r"self\.rank_a_ratio = ([0-9.]+)\s", 1),
    ("menu_ui.f1_display_default", "menu_ui.py", "F1 display default (page 3/3 and the result screen)", r"getattr\(self, 'rank_a_ratio', ([0-9.]+)\)", 2),
    ("scoring_settings.live_default", "scoring_settings.py", "scoring settings: live accessor default", r'"a_rank_ratio": \("rank_a_ratio", ([0-9.]+)\)', 1),
    ("scoring_settings.build_default", "scoring_settings.py", "scoring settings: snapshot build default", r'getattr\(overlay, "rank_a_ratio", ([0-9.]+)\)', 1),
)
# the sixth site (main.py, the F1 input fallback of an out-of-range Enter) is no literal any more: it is the shared normalization (initial_defaults.normalize_a_rank_percent -> A_RANK_BUILTIN_PERCENT = 60)
ALREADY_SIXTY = (
    ("main.generation_fallback", "main.py", "scenario settings generation: an invalid saved A boundary falls back to 60 (already contract-conform)", r"a_rank_percent_valid\(defaults\.a_rank_percent\) else ([0-9.]+)", 1),
)
OTHER_CONTRACT = (
    ("main.rank_multi", "main.py", "B / C decay multiplier (another contract: stays 0.7)", r"self\.rank_multi = ([0-9.]+)", 1, 0.7),
    ("menu_ui.rank_multi", "menu_ui.py", "B / C decay multiplier display default (another contract: stays 0.70)", r"getattr\(self, 'rank_multi', ([0-9.]+)\)", 2, 0.7),
)


def literals(site):
    text = X.source(site[1])
    found = [float(v) for v in re.findall(site[3], text)]
    return found


class Fallback70Sites(unittest.TestCase):
    def test_the_anchors_are_found(self):
        """HARNESS: every anchor of the map still exists with the expected count (a drifted anchor must not silently pass the RED)."""
        for site in A_RANK_FALLBACK_SITES + ALREADY_SIXTY + tuple(s[:5] for s in OTHER_CONTRACT):
            self.assertEqual(len(literals(site)), site[4], "IDF1-HARNESS: anchor %s found %d occurrences, expected %d" % (site[0], len(literals(site)), site[4]))

    def test_the_a_boundary_input_fallback_group_is_60_everywhere_AGGREGATE(self):
        """The aggregate RED: lists EVERY site of the A boundary fallback group that is not 0.6 yet."""
        leftovers = []
        for site in A_RANK_FALLBACK_SITES:
            for value in literals(site):
                if value != 0.6:
                    leftovers.append("%s=%s" % (site[0], value))
        self.assertEqual(leftovers, [], "IDF1-RED: the A boundary default / fallback is still not 60 at: %s" % ", ".join(leftovers))

    def test_the_site_count_of_the_group_is_six(self):
        """The F0 audit found 6 sites of the left-over 70: 5 literals (main introduction default, scoring_settings x2, menu_ui x2) + the F1 input fallback, which F2 replaced by the shared normalization."""
        total = sum(site[4] for site in A_RANK_FALLBACK_SITES)
        self.assertEqual(total, 5, "IDF1-HARNESS: the map has %d literal sites, expected 5 (+ the replaced F1 input fallback)" % total)

    def test_the_f1_input_fallback_is_the_shared_normalization_and_60(self):
        import initial_defaults as D
        main_text = X.source("main.py")
        self.assertEqual(main_text.count("normalize_a_rank_percent(self.input_buffer)"), 1, "IDF1-RED: F1 does not confirm the A boundary input through the shared normalization")
        self.assertNotIn("a_rank_percent_valid(val) else", main_text, "IDF1-RED: the old F1 fallback expression is still in main.py")
        self.assertEqual(D.A_RANK_BUILTIN_PERCENT, 60, "IDF1-GUARD: the normalization fallback is not 60")
        self.assertEqual(D.normalize_a_rank_percent("49"), (60, True))

    def test_the_generation_fallback_is_already_60(self):
        for site in ALREADY_SIXTY:
            self.assertEqual(literals(site), [0.6], "IDF1-GUARD: %s is not 0.6" % site[0])

    def test_another_contract_must_not_become_60_rank_multi(self):
        for site in OTHER_CONTRACT:
            self.assertEqual(literals(site[:5]), [site[5]] * site[4], "IDF1-GUARD: %s was changed (%s): it is another contract (the B / C multiplier), not the A boundary" % (site[0], site[2]))

    def test_another_contract_must_not_become_60_the_advanced_preset_is_70(self):
        import initial_defaults as D
        self.assertEqual({k: v[1] for k, v in D.PRESETS.items()}, {"beginner": 50, "intermediate": 60, "advanced": 70}, "IDF1-GUARD: a preset A boundary changed (the 上級 preset is 70 by contract)")

    def test_the_other_70s_of_the_product_are_not_a_boundary(self):
        """The rest of the 70s are layout pixels / budgets (menu_ui row steps and offsets, ENV_ROW_STEP, managed_input TOTAL_LINE_BUDGET, hud gradient stop): none is read as the A boundary."""
        for name in ("managed_input.py", "hud_ui.py", "scoring_logic.py", "config.py", "initial_defaults_ui.py"):
            for number, line in enumerate(X.source(name).splitlines(), 1):
                if re.search(r"\b70\b|\b0\.7\b|\b0\.70\b", line) and "rank_" in line and "rank_multi" not in line:
                    self.fail("IDF1-HARNESS: %s:%d reads a 70 next to rank_: classify it (%s)" % (name, number, line.strip()[:100]))


# one RED per site (a leftover is reported as its own failure), plus the dynamic consequences
def _site_test(site):
    def body(self):
        values = literals(site)
        self.assertEqual(values, [0.6] * site[4], "IDF1-RED: %s still %s (%s)" % (site[0], values, site[2]))
    return body


for _site in A_RANK_FALLBACK_SITES:
    setattr(Fallback70Sites, "test_site_%s" % _site[0].replace(".", "_"), _site_test(_site))


class Fallback70Behaviour(unittest.TestCase):
    """The behaviour behind the sites (the call paths), independent of how the literal is written."""

    @classmethod
    def setUpClass(cls):
        X.qt_app()
        import main
        import scoring_settings
        cls.main, cls.SS = main, scoring_settings

    def test_a_new_overlay_starts_with_the_a_boundary_60(self):
        rig = R.Rig(self.main)
        try:
            self.assertEqual(rig.o.rank_a_ratio, 0.6, "IDF1-RED: a new Overlay holds the A boundary %.2f before the first scenario (introduction default)" % rig.o.rank_a_ratio)
        finally:
            rig.close()

    def test_the_scoring_settings_defaults_are_60(self):
        bare = types.SimpleNamespace()
        self.assertEqual(self.SS.value(bare, "a_rank_ratio"), 0.6, "IDF1-RED: the live accessor default of the A boundary is not 60")
        self.assertEqual(self.SS.build(bare).a_rank_ratio, 0.6, "IDF1-RED: the snapshot build default of the A boundary is not 60")

    def test_the_f1_display_default_is_60(self):
        rig = R.Rig(self.main)
        try:
            o = rig.o
            o.width, o.height = (lambda: 1920), (lambda: 1080)
            o.show_help = False
            o.dropdown_active = False
            del o.rank_a_ratio                                          # the attribute is missing: the display default is what F1 shows
            texts, _ = X.render_f1(o, 10, menu_cursor=0)
            self.assertEqual(X.a_pct_shown(texts)[-1][0], "60%", "IDF1-RED: F1 page 3/3 shows %s for a missing A boundary (display default)" % X.a_pct_shown(texts)[-1][0])
        finally:
            rig.close()

    def test_the_f1_input_fallback_is_60_for_an_out_of_range_input(self):
        rig = R.Rig(self.main)
        try:
            o = rig.o
            o.rank_a_ratio = 0.8
            X.f1_edit_and_commit(o, "49")
            self.assertEqual(o.rank_a_ratio, 0.6, "IDF1-RED: the F1 input fallback is %.2f" % o.rank_a_ratio)
        finally:
            rig.close()

    def test_the_blanket_replace_detector_the_b_c_multiplier_and_the_advanced_preset_keep_70(self):
        rig = R.Rig(self.main)
        try:
            self.assertEqual(rig.o.rank_multi, 0.7, "IDF1-GUARD: rank_multi (the B / C multiplier) is another contract and stays 0.7")
        finally:
            rig.close()
        import initial_defaults as D
        self.assertEqual(D.apply_preset(D.builtin_defaults(), "advanced").a_rank_percent, 70, "IDF1-GUARD: the advanced preset A boundary is 70")


if __name__ == "__main__":
    unittest.main()
