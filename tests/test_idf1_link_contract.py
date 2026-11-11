"""INITIAL-DEFAULTS Stage F1: the saved_defaults -> scenario_settings -> running_snapshot link contract (Owner 2026-11-11). RED-only: the product code is not changed.

  presets      初級 / 中級 / 上級 change the six deductions and the A boundary ONLY; the 8 environment items (mixed ON / OFF), the timing-station setting (ON and OFF), the saved defaults, the save path, the file bytes / mtime,
               the save count and every unrelated widget state are identical before and after; the save function is never called by a preset press
  no write-back an F1 change (A boundary, environment, timing, deductions) never writes the saved defaults (file bytes / mtime unchanged, save function called 0 times, the loaded defaults unchanged)
  regeneration the scenario settings come from the saved file again: at the first load of a (restarted) Overlay, at another scenario, at an F5-like reload (a new SCENARIO_ID of the same route) and through the formal entry
               Overlay._apply_initial_defaults; the F1 display follows; the saved defaults stay
  snapshot     the scoring start freezes the A boundary and the deductions; a later change of the live values or an uncommitted F1 draft never reaches it

Most of these hold TODAY (GREEN guards, 'IDF1-GUARD'); they are the contracts the Stage F2 change must not break."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import idf1_red_support as X  # noqa: E402
import sia_rig as R  # noqa: E402


def setUpModule():
    X.redirect_profile("ts-idf1-link-")


def tearDownModule():
    X.restore_profile()


# ================================================================================================================ presets: non-interference
ENV_MIXED_A = (True, False, True, True, False, True, False, True)           # speed limit ON, advance OFF: a valid mixed state
ENV_MIXED_B = (False, True, False, False, False, False, True, False)        # speed limit OFF, advance OFF
PRESET_KEYS = (("beginner", "preset_beginner"), ("intermediate", "preset_intermediate"), ("advanced", "preset_advanced"))
ALLOWED_TO_CHANGE = ("pen_rolling", "pen_speed", "pen_shock", "pen_eb", "pen_init", "a_rank")


def ui_state(dialog):
    """Every widget of the window except the deduction items and the A boundary (the only things a preset may change)."""
    from PyQt6.QtWidgets import QWidget
    spin = dialog.findChild(QWidget, "a_rank")
    state = {}
    for index, w in enumerate(dialog.findChildren(QWidget)):
        name = w.objectName()
        if name in ALLOWED_TO_CHANGE or (spin is not None and spin.isAncestorOf(w)):
            continue
        text = w.text() if hasattr(w, "text") and callable(w.text) else None
        checked = w.isChecked() if hasattr(w, "isChecked") else None
        state[(type(w).__name__, name or index)] = (w.isVisible(), w.isEnabled(), text, checked, w.geometry().getRect())
    return state


class PresetNonInterference(X.DialogBase):
    def fixture(self, env, timing):
        b = self.D.builtin_defaults()
        return b._replace(environment=self.D.Environment(*env), all_changeable_non_timed_to_timed=timing, a_rank_percent=75)

    def spy_save(self):
        calls = []
        real = self.D.save
        self.D.save = lambda *a, **k: calls.append((a, k))
        self.addCleanup(lambda: setattr(self.D, "save", real))
        return calls

    def check(self, preset, button, env, timing):
        defaults = self.fixture(env, timing)
        self.D.save(defaults, self.path)                           # the fixture file (bypasses the spy below)
        before_file = X.file_snapshot(self.path)
        direct_calls = self.spy_save()
        self.saves = []
        d = self.make(defaults=defaults)
        before_ui = ui_state(d)
        before_collect = self.U.collect(d)
        before_path = self.D.defaults_path()
        self.find(d, button).click()
        self.app_events()
        after_collect = self.U.collect(d)
        label = "%s env=%s timing=%s" % (preset, "".join("1" if v else "0" for v in env), timing)
        self.assertEqual(after_collect.environment, before_collect.environment, "IDF1-GUARD: a preset changed the 8 environment items (%s)" % label)
        self.assertEqual(after_collect.all_changeable_non_timed_to_timed, before_collect.all_changeable_non_timed_to_timed, "IDF1-GUARD: a preset changed the timing-station setting (%s)" % label)
        self.assertIs(after_collect.penalties.safety_intervention, False, "IDF1-GUARD: a preset set the safety intervention (%s)" % label)
        penalties, percent = self.D.PRESETS[preset]
        self.assertEqual(after_collect.penalties, penalties, "IDF1-GUARD: the deductions after %s are not the preset table (%s)" % (preset, label))
        self.assertEqual(after_collect.a_rank_percent, percent, "IDF1-GUARD: the A boundary after %s is not the preset table (%s)" % (preset, label))
        self.assertEqual(ui_state(d), before_ui, "IDF1-GUARD: a preset changed an unrelated widget state (%s)" % label)
        self.assertEqual(self.saves, [], "IDF1-GUARD: a preset press called the save callback (%s)" % label)
        self.assertEqual(direct_calls, [], "IDF1-GUARD: a preset press called initial_defaults.save (%s)" % label)
        self.assertEqual(X.file_snapshot(self.path), before_file, "IDF1-GUARD: a preset press changed the saved file bytes / mtime (%s)" % label)
        self.assertEqual(self.D.defaults_path(), before_path, "IDF1-GUARD: the save target changed (%s)" % label)
        self.assertEqual(self.message(d), "", "IDF1-GUARD: a preset press shows a message (%s)" % label)
        self.assertTrue(self.is_open(d), "IDF1-GUARD: a preset press closed the window (%s)" % label)

    def test_beginner_changes_only_the_deductions_and_the_a_boundary(self):
        for env in (ENV_MIXED_A, ENV_MIXED_B):
            for timing in (True, False):
                with self.subTest(env=env, timing=timing):
                    self.check("beginner", "preset_beginner", env, timing)

    def test_intermediate_changes_only_the_deductions_and_the_a_boundary(self):
        for env in (ENV_MIXED_A, ENV_MIXED_B):
            for timing in (True, False):
                with self.subTest(env=env, timing=timing):
                    self.check("intermediate", "preset_intermediate", env, timing)

    def test_advanced_changes_only_the_deductions_and_the_a_boundary(self):
        for env in (ENV_MIXED_A, ENV_MIXED_B):
            for timing in (True, False):
                with self.subTest(env=env, timing=timing):
                    self.check("advanced", "preset_advanced", env, timing)

    def test_pressing_all_presets_in_turn_keeps_the_environment_and_the_timing_setting(self):
        for timing in (True, False):
            d = self.make(defaults=self.fixture(ENV_MIXED_A, timing))
            before = self.U.collect(d)
            for _, button in PRESET_KEYS + PRESET_KEYS[::-1]:
                self.find(d, button).click()
            after = self.U.collect(d)
            self.assertEqual((after.environment, after.all_changeable_non_timed_to_timed), (before.environment, before.all_changeable_non_timed_to_timed), "IDF1-GUARD: a preset sequence changed the environment / timing setting")
            self.assertEqual(self.saves, [])

    def test_the_safety_intervention_item_stays_off_and_unchangeable_after_every_preset(self):
        for _, button in PRESET_KEYS:
            d = self.make()
            box = self.find(d, "pen_safety")
            self.find(d, button).click()
            self.assertFalse(box.isChecked(), "IDF1-GUARD: a preset checked the safety intervention item")
            box.setChecked(True)
            self.assertFalse(box.isChecked(), "IDF1-GUARD: the safety intervention item can be turned on")

    def test_a_preset_followed_by_close_discards_it_and_saves_nothing(self):
        before = X.file_snapshot(self.path)
        d = self.make(defaults=self.fixture(ENV_MIXED_A, True))
        self.find(d, "preset_advanced").click()
        d.reject()
        self.assertEqual(self.saves, [], "IDF1-GUARD: closing after a preset saved")
        self.assertEqual(X.file_snapshot(self.path), before)


# ================================================================================================================ no write-back of an F1 change
class NoWriteBack(X.LinkBase):
    def start(self):
        defaults = self.base(a=60)
        self.fixture_defaults = defaults
        self.snapshot = self.write_saved(defaults)
        self.scenario(5)
        self.assertEqual(self.o.rank_a_ratio, 0.6, "IDF1-HARNESS: the scenario did not take the saved 60")

    def untouched(self, why):
        self.assert_file_untouched(self.snapshot, why)
        self.assertEqual(self.saved(), self.fixture_defaults, "IDF1-GUARD: %s changed the loaded saved defaults" % why)

    def test_a_boundary_80_from_f1_never_reaches_the_saved_defaults(self):
        self.start()
        X.f1_edit_and_commit(self.o, "80")
        self.assertEqual(self.o.rank_a_ratio, 0.8, "IDF1-GUARD: the scenario settings do not hold the F1 value")
        self.assertEqual(self.saved().a_rank_percent, 60, "IDF1-GUARD: the saved A boundary is not 60")
        self.untouched("the F1 A boundary edit")

    def test_a_boundary_by_the_arrow_keys_never_reaches_the_saved_defaults(self):
        self.start()
        self.o.menu_state, self.o.menu_cursor = 10, 0
        for _ in range(5):
            self.o.handle_menu_right()
        self.assertEqual(self.o.rank_a_ratio, 0.65)
        self.untouched("the F1 arrow keys on the A boundary")

    def test_environment_change_never_reaches_the_saved_defaults(self):
        self.start()
        self.o.set_speed_limit_visible(False)
        self.o.set_disp_setting("time", False)
        self.assertEqual((self.o.disp_settings["limit"], self.o.disp_settings["limit_advance"], self.o.disp_settings["time"]), (False, False, False), "IDF1-HARNESS: the F1 environment change did not apply")
        self.untouched("an F1 environment change")

    def test_timing_station_change_never_reaches_the_saved_defaults(self):
        self.start()
        self.o.user_timing_overrides[3] = True
        self.untouched("an F1 timing-station change")

    def test_deduction_change_never_reaches_the_saved_defaults(self):
        self.start()
        self.o.is_scoring_mode = False
        for cursor in (0, 2, 3, 4):
            self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x = 6, cursor, 0
            self.o.handle_menu_enter(False)
        self.assertEqual((self.o.pen_roll, self.o.pen_limit, self.o.pen_jerk, self.o.pen_eb), (False, False, False, False), "IDF1-HARNESS: the F1 deduction toggles did not apply")
        self.untouched("an F1 deduction change")

    def test_the_f1_cancel_and_the_correction_never_reach_the_saved_defaults(self):
        self.start()
        X.f1_start_edit(self.o)
        X.f1_type(self.o, "49")
        X.f1_cancel(self.o)
        self.untouched("an F1 cancel")
        X.f1_edit_and_commit(self.o, "49")
        self.untouched("an F1 out-of-range commit")

    def test_every_other_setting_is_equally_untouched_in_one_sequence(self):
        self.start()
        X.f1_edit_and_commit(self.o, "80")
        self.o.set_speed_limit_visible(False)
        self.o.user_timing_overrides[1] = False
        self.o.menu_state, self.o.menu_cursor, self.o.menu_cursor_x = 6, 3, 0
        self.o.handle_menu_enter(False)
        self.untouched("a sequence of F1 changes")


# ================================================================================================================ regeneration: first load / another scenario / F5-like / the formal entry
class Regeneration(X.LinkBase):
    def start_with_f1_80(self):
        self.snapshot = self.write_saved(self.base(a=60))
        self.scenario(5)
        X.f1_edit_and_commit(self.o, "80")
        self.assertEqual(self.o.rank_a_ratio, 0.8, "IDF1-HARNESS: the F1 value is not applied before the reload")
        texts, _ = X.render_f1(self.o, 10, menu_cursor=0)
        self.assertEqual(X.a_pct_shown(texts)[-1][0], "80%", "IDF1-HARNESS: the F1 page does not show 80% before the reload")

    def after_reload(self, why):
        self.assertEqual(self.o.rank_a_ratio, 0.6, "IDF1-GUARD: %s did not regenerate the A boundary from the saved 60" % why)
        texts, _ = X.render_f1(self.o, 10, menu_cursor=0)
        self.assertEqual(X.a_pct_shown(texts)[-1][0], "60%", "IDF1-GUARD: the F1 page does not show 60%% after %s" % why)
        self.assertEqual(self.saved().a_rank_percent, 60, "IDF1-GUARD: the saved A boundary changed (%s)" % why)
        self.assertEqual(X.file_snapshot(self.path), self.snapshot, "IDF1-GUARD: %s changed the saved file" % why)
        self.assertEqual(self.save_calls, [], "IDF1-GUARD: %s called the save function" % why)

    def test_first_load_of_a_restarted_overlay_reads_the_saved_60(self):
        """Reason: the Overlay is a new process (current_scenario_id == -1 and the F1 attributes are the construction defaults); the first SCENARIO_ID reads the file."""
        self.start_with_f1_80()
        self.rig.close()
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.assertEqual(self.o.current_scenario_id, -1, "IDF1-HARNESS: the new Overlay is not at its first scenario")
        self.scenario(5)
        self.after_reload("the first load of a restarted Overlay")

    def test_another_scenario_load_regenerates_from_the_saved_60(self):
        """Reason: SCENARIO_ID changes (another scenario / route): the previous scenario's F1 values are discarded."""
        self.start_with_f1_80()
        self.scenario(6)
        self.after_reload("another scenario")

    def test_f5_like_reload_of_the_same_scenario_regenerates_from_the_saved_60(self):
        """Reason: F5 makes BVE issue a NEW SCENARIO_ID for the SAME route; the Python side has no F5 branch, the new id alone triggers the regeneration."""
        self.start_with_f1_80()
        self.scenario(7)
        self.scenario(8)                                    # reload twice: every new id regenerates
        self.after_reload("an F5-like reload (a new SCENARIO_ID)")

    def test_the_formal_entry_apply_initial_defaults_regenerates_from_the_saved_60(self):
        """Reason: the formal entry itself (Overlay._apply_initial_defaults), without the SCENARIO_ID text parser."""
        self.start_with_f1_80()
        self.o._apply_initial_defaults(self.o.current_scenario_id)
        self.after_reload("Overlay._apply_initial_defaults")

    def test_the_same_scenario_id_again_is_not_a_reload(self):
        self.start_with_f1_80()
        self.scenario(5)
        self.assertEqual(self.o.rank_a_ratio, 0.8, "IDF1-GUARD: a repeated SCENARIO_ID regenerated the F1 values")

    def test_the_regeneration_reads_the_file_at_every_load(self):
        self.snapshot = self.write_saved(self.base(a=60))
        self.scenario(5)
        self.write_saved(self.base(a=75))
        self.scenario(6)
        self.assertEqual(self.o.rank_a_ratio, 0.75, "IDF1-GUARD: the second load did not read the changed file")


# ================================================================================================================ running_snapshot
class RunningSnapshot(X.LinkBase):
    def start_scoring(self):
        self.snapshot = self.write_saved(self.base(a=60))
        self.scenario(5)
        o = self.o
        self.assertEqual(o.rank_a_ratio, 0.6, "IDF1-HARNESS: the scenario did not take the saved 60")
        o.is_scoring_mode = True                                  # the wiring of the scoring start (scoring_settings.build before is_scoring_mode) is fixed by test_initial_defaults_apply
        o._scoring_settings = self.SS.build(o)
        return o

    def test_the_a_boundary_of_the_snapshot_is_60_and_stays_60(self):
        o = self.start_scoring()
        self.assertEqual(o._scoring_settings.a_rank_ratio, 0.6, "IDF1-GUARD: the snapshot does not hold 60")
        self.assertEqual(self.SS.value(o, "a_rank_ratio"), 0.6)
        o.rank_a_ratio = 0.8                                      # the scenario settings change after the start
        self.assertEqual(self.SS.value(o, "a_rank_ratio"), 0.6, "IDF1-GUARD: the running snapshot followed the live A boundary")
        self.assertEqual(o._scoring_settings.a_rank_ratio, 0.6)

    def test_an_f1_draft_after_the_start_never_reaches_the_snapshot(self):
        o = self.start_scoring()
        X.f1_start_edit(o)
        X.f1_type(o, "80")                                       # an uncommitted draft
        self.assertEqual(self.SS.value(o, "a_rank_ratio"), 0.6, "IDF1-GUARD: an F1 draft reached the running snapshot")
        X.f1_commit(o)                                           # committed into the scenario settings
        self.assertEqual(o.rank_a_ratio, 0.8)
        self.assertEqual(self.SS.value(o, "a_rank_ratio"), 0.6, "IDF1-GUARD: an F1 commit after the start reached the running snapshot")

    def test_an_out_of_range_commit_after_the_start_never_reaches_the_snapshot(self):
        o = self.start_scoring()
        X.f1_edit_and_commit(o, "49")
        self.assertEqual(self.SS.value(o, "a_rank_ratio"), 0.6, "IDF1-GUARD: a corrected F1 commit reached the running snapshot")
        self.assertEqual(o._scoring_settings.a_rank_ratio, 0.6)

    def test_the_deductions_of_the_snapshot_are_fixed(self):
        o = self.start_scoring()
        o.pen_limit, o.pen_jerk, o.pen_eb, o.pen_roll = False, False, False, False
        V = self.SS.value
        self.assertEqual((V(o, "speed_limit_exceeded"), V(o, "stop_shock"), V(o, "emergency_brake"), V(o, "rolling")), (True, True, True, True), "IDF1-GUARD: a deduction followed the live value")

    def test_the_snapshot_is_a_value_not_a_reference_to_the_live_attributes(self):
        o = self.start_scoring()
        before = o._scoring_settings
        o.rank_a_ratio = 0.9
        o.pen_limit = False
        o.penalty_init_rules[0]["apply"] = "ON②"
        self.assertEqual(o._scoring_settings, before, "IDF1-GUARD: the snapshot changed with the live values")

    def test_the_environment_settings_are_not_part_of_the_snapshot_OWNER_QUESTION(self):
        """FINDING (reported, no RED): ScoringSettings has NO environment field; the 8 environment items are display settings that stay switchable in F1 during a Run. The Owner asked for a 'fixed' contract for the environment in the
        running snapshot: today there is nothing to freeze. This test only pins the FACT (the snapshot is untouched by an environment change); whether the environment must be frozen is an Owner decision."""
        o = self.start_scoring()
        before = o._scoring_settings
        o.set_speed_limit_visible(False)
        self.assertNotIn("environment", self.SS.ScoringSettings._fields)
        self.assertEqual(o._scoring_settings, before, "IDF1-GUARD: an environment change reached the running snapshot")


if __name__ == "__main__":
    unittest.main()
