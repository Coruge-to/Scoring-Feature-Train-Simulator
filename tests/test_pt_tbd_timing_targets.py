"""Stage 2.1 (Owner decision 3): Overlay.get_timing_target_stas - the station range that the timing screens, the timing toggle and the HUD 'timing station' label work on - takes the scoring-section snapshot while a
scoring Run is active (start button .. abort / illegal Jump / F5 reload / finish) and the settings of the menu before it. The callers (menu_ui.py: settings screen and timing screen; main.py: the menu_state 8 handlers,
toggle_all_timing and the two HUD readers) are not changed; only this one reader switches its source.
The REAL start handler is driven (as tests/test_pt_tbd_snapshot.py)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbd_snapshot import Base as SnapshotBase, setUpModule, tearDownModule  # noqa: E402,F401


def legacy_targets(o, start, end):
    """The formula this function had before Stage 2.1, for the settings (start, end)."""
    if not o.station_list:
        return []
    end_idx = end if end != -1 else o.get_actual_terminal_idx()
    if end_idx == -1 or end_idx >= len(o.station_list):
        end_idx = len(o.station_list) - 1
    return [i for i in range(len(o.station_list)) if start <= i <= end_idx]


class A_BeforeTheStart(SnapshotBase):
    def test_TT_1_before_the_start_the_settings_are_read_as_ever_and_nothing_raises(self):
        s = self.scene(start=1, end=3)
        self.assertIsNone(self.snap(s))
        self.assertEqual(s.o.get_timing_target_stas(), [1, 2, 3])
        s.o.setting_start_idx, s.o.setting_end_idx = 0, -1
        self.assertEqual(s.o.get_timing_target_stas(), legacy_targets(s.o, 0, -1))
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 99
        self.assertEqual(s.o.get_timing_target_stas(), legacy_targets(s.o, 2, 99))
        s.o.station_list = []
        self.assertEqual(s.o.get_timing_target_stas(), [])

    def test_TT_2_an_ordinary_route_gives_the_same_ranges_before_and_during_the_run(self):
        for start, end in ((0, 4), (0, 2), (1, 3), (2, 4), (0, -1)):
            with self.subTest(start=start, end=end):
                s = self.P.Scene(self, with_pairs=False)
                s.o.setting_start_idx, s.o.setting_end_idx = start, end
                before = s.o.get_timing_target_stas()
                self.assertEqual(before, legacy_targets(s.o, start, end))
                self.press_start(s)
                self.assertIsNotNone(self.snap(s))
                self.assertEqual(s.o.get_timing_target_stas(), before, "the result of an ordinary route does not change by the start")


class B_DuringTheRun(SnapshotBase):
    def test_TT_3_after_the_start_the_snapshot_is_read_and_the_UI_values_do_not_matter(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        self.assertEqual(o.get_timing_target_stas(), [0, 1, 2, 3, 4])
        o.setting_start_idx, o.setting_end_idx = 3, 3
        self.assertEqual(o.get_timing_target_stas(), [0, 1, 2, 3, 4])
        o.setting_start_idx, o.setting_end_idx = 2, -1
        self.assertEqual(o.get_timing_target_stas(), [0, 1, 2, 3, 4])

    def test_TT_4_a_retry_of_the_run_keeps_the_fixed_range(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        self.assertTrue(self.main.execute_retry(o, 0, False).accepted)
        o.setting_start_idx, o.setting_end_idx = 3, 4
        s.step(3)
        self.assertEqual(o.get_timing_target_stas(), [0, 1, 2, 3, 4])

    def test_TT_5_target_and_nextloc_changes_never_send_the_reader_back_to_the_UI(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 4, 4
        for tgt, loc, pos in ((3, 3000.0, 2000.0), (1, 500.0, 100.0), (4, 4000.0, 3900.0)):
            o.bve_tgt_idx, o.bve_next_loc, o.bve_location = tgt, loc, pos
            s.step(2)
            self.assertEqual(o.get_timing_target_stas(), [0, 1, 2, 3, 4], (tgt, loc))

    def test_TT_6_an_old_snapshot_is_never_used_after_the_run_is_over(self):
        ways = {
            "generation (F5 reload)": lambda o: setattr(o, "current_scenario_id", o.current_scenario_id + 1),
            "session off / abort / illegal Jump": lambda o: setattr(o, "is_scoring_mode", False),
            "finished": lambda o: setattr(o, "is_scoring_finished", True),
        }
        for name, end_it in ways.items():
            with self.subTest(way=name):
                s = self.scene(start=0, end=4)
                self.press_start(s)
                o = s.o
                self.assertEqual(o.get_timing_target_stas(), [0, 1, 2, 3, 4])
                o.setting_start_idx, o.setting_end_idx = 1, 2            # what the menu says now
                end_it(o)
                self.assertEqual(o.get_timing_target_stas(), [1, 2], "the settings again - the old snapshot is not used")
                s.step(2)
                self.assertEqual(o.get_timing_target_stas(), [1, 2])

    def test_TT_7_a_new_start_switches_to_the_range_of_the_new_snapshot(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        self.assertEqual(s.o.get_timing_target_stas(), [0, 1, 2, 3, 4])
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 3
        self.assertEqual(s.o.get_timing_target_stas(), [0, 1, 2, 3, 4], "still the first Run")
        self.press_start(s)
        self.assertEqual(s.o.get_timing_target_stas(), [2, 3])


class C_PseudoTurnbackTerminalB(SnapshotBase):
    def test_TT_8_with_a_terminal_B_the_range_ends_at_A_before_and_during_the_run_and_B_never_comes_back(self):
        s = self.scene(terminal_b=True, start=0, end=-1)
        o = s.o
        self.assertEqual(o.get_actual_terminal_idx(), 1)
        self.assertEqual(o.get_timing_target_stas(), [0, 1], "before the start: the initial end station is A")
        self.press_start(s)
        self.assertEqual(self.snap(s).end, 1)
        self.assertEqual(o.get_timing_target_stas(), [0, 1])
        o.setting_end_idx = 2                                              # the UI value drifts to the B
        self.assertEqual(o.get_timing_target_stas(), [0, 1], "B is not taken back into the scoring range")
        o.setting_end_idx = -1
        s.step(3)
        self.assertNotIn(2, o.get_timing_target_stas())

    def test_TT_9_a_section_that_crosses_the_pair_keeps_its_range_up_to_the_end(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        self.assertEqual(s.o.get_timing_target_stas(), [0, 1, 2, 3, 4])
        self.assertTrue(self.snap(s).turnback)


class D_TheReaderItself(SnapshotBase):
    def test_TT_10_only_the_source_of_this_one_reader_changed(self):
        import ast
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        overlay = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
        fn = next(n for n in overlay.body if isinstance(n, ast.FunctionDef) and n.name == "get_timing_target_stas")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        self.assertIn("active_scoring_section", names, "the running Run is read through the one validity check")
        self.assertIn("setting_start_idx", names, "and the settings stay the source before the start")
        self.assertIn("get_actual_terminal_idx", names)


if __name__ == "__main__":
    unittest.main()
