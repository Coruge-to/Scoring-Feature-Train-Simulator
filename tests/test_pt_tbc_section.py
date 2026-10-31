"""Stage TB-C, slice C1: OD-TB-26 (the pairs the section crosses are FIXED at the scoring start button, never derived again at the A arrival) and OD-TB-24 (the default end sentinel setting_end_idx=-1 means
'terminal' and is resolved at the start button to the last valid end candidate, i.e. without the B of a pair). The REAL start handler (Overlay.handle_menu_enter, menu_state 10 / cursor 1) is driven.
After the start the settings are changed behind the product's back (the product's own menus can not do that during scoring): a fixed contract must not notice."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbc-red-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbc-red"])
        import main
        import scoring_logic
        import pt_scene
        import pseudo_turnback_contract
        cls.main, cls.S, cls.P, cls.PC = main, scoring_logic, pt_scene, pseudo_turnback_contract

    def scene(self, terminal_b=False, start=0, end=4):
        s = self.P.Scene(self, with_pairs=False)
        o = s.o
        if terminal_b:
            s.sl = s.sl[:3]
            s.sl[2]["is_terminal"] = True
            o.station_list = s.sl
            ptpair = "PTPAIR:1:%s:3:1:1-2-0" % self.P.R.SCOPE_LIST_ID
        else:
            ptpair = self.P.PTPAIR
        ps, why = self.PC.decode_ptpair(ptpair, len(s.sl))
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        o.setting_start_idx, o.setting_end_idx = start, end
        return s

    def press_start(self, s):
        """The REAL scoring start button. Afterwards the Jump is treated as settled by a test shortcut (the START settlement is O1's and is not under test here)."""
        o = s.o
        s.auto_fix = False                           # from here on only the PRODUCT fixes the section (the start button)
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor = 10, 1
        o.scoring_start_gate = None
        o.was_advancing_before_menu = False
        self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
        o.bve_location, o.bve_speed = 0.0, 0.0
        o.handle_menu_enter(False)
        self.assertTrue(o.is_scoring_mode, "the start button was refused")
        o.jump_expectation = None
        o.retry_pending = None
        o.is_official_jumping = False
        o.jump_lock = False
        o.is_first_udp = False
        o.is_first_station = False
        o.has_departed = True
        o.save_data[:] = [self.P.checkpoint0(s.sl, 0)]
        o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        o.bve_next_time = self.P.T0 + 90000
        o.bve_next_loc = o.prev_next_loc = self.P.A_MARK
        o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq = 1, 0, 0
        o.bve_location, o.bve_speed = self.P.A_MARK - 400.0, 30.0
        o.bve_door = o.prev_door = 0
        self.P.R.bind_identity(o, arr_idx=0, tgt_idx=1)
        self.S.reset_station_evaluation_state(o)

    def arrive_at_a(self, s):
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()


class OD26_FixedAtStart(Base):
    def test_OD26_a_crossing_section_stays_a_target_even_if_the_settings_drift_after_the_start(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        s.o.setting_start_idx = 1                    # drift: start == A (re-derivation at the A arrival finds PU-1 violated: a NON-crossing section)
        self.arrive_at_a(s)
        self.assertEqual(s.machine.state, M.ARMED, "the pair fixed at the start (0 -> 4 crosses A -> B) must run its chain")

    def test_OD26_a_non_crossing_section_stays_a_non_target_even_if_the_settings_drift_after_the_start(self):
        s = self.scene(start=2, end=4)
        self.press_start(s)
        s.o.setting_start_idx = 0                    # drift: re-derivation would find a crossing section 0 -> 4
        self.arrive_at_a(s)
        self.assertEqual(s.machine.state, M.IDLE, "B -> 4 fixed at the start crosses nothing: no chain")
        self.assertEqual(s.popups("疑似折り返し"), [])

    def test_OD26_a_new_scoring_start_regenerates_the_fixed_pair(self):
        s = self.scene(start=2, end=4)
        self.press_start(s)                          # fixed: B -> 4 (no pair)
        s.o.setting_start_idx = 0                    # a NEW start with a crossing section ...
        self.press_start(s)                          # ... must regenerate: the pair is now a target
        s.o.setting_start_idx = 1                    # drift after the second start
        self.arrive_at_a(s)
        self.assertEqual(s.machine.state, M.ARMED, "the second start fixed 0 -> 4: the first start's fixed value must not survive")

    def test_OD26_a_generation_change_discards_the_fixed_pair(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        o.current_scenario_id = o.current_scenario_id + 1       # generation change (the scoring session of the old generation is gone)
        o.is_scoring_mode = True
        s.machine.reset_world()
        s.machine.set_pairset(self.PC.decode_ptpair(self.P.PTPAIR, len(s.sl))[0])
        o.setting_start_idx, o.setting_end_idx = 0, 4
        self.arrive_at_a(s)
        # no start button was pressed in the new generation: the old fixed pair must NOT make the arrival a target
        self.assertEqual(s.machine.state, M.IDLE)


class OD24_UnspecifiedEndResolvesAtStart(Base):
    def test_OD24_a_terminal_B_with_the_default_end_resolves_to_A_at_the_start_button(self):
        s = self.scene(terminal_b=True, start=0, end=-1)
        self.press_start(s)
        self.assertEqual(s.o.setting_end_idx, 1, "the unspecified end is written as the last valid end candidate (A) by the start button")

    def test_OD24_a_terminal_B_still_ends_at_A_and_never_jumps_to_B(self):
        s = self.scene(terminal_b=True, start=0, end=-1)
        self.press_start(s)
        self.arrive_at_a(s)
        self.assertTrue(s.o.is_scoring_finished, "A is the end: the scoring finishes at the A arrival")
        self.assertEqual(s.machine.state, M.IDLE)
        self.assertEqual(s.popups("疑似折り返し"), [])

    def test_OD24_a_terminal_other_than_B_keeps_the_terminal_default(self):
        s = self.scene(start=0, end=-1)
        self.press_start(s)
        self.assertIn(s.o.setting_end_idx, (-1, 4), "unchanged behaviour when the terminal is not a B")


class OD26_MultiPairAndRetry(Base):
    def scene6(self):
        P = self.P
        s = P.Scene(self, with_pairs=False)
        o = s.o
        s.sl = [P.station("S0", 0.0, raw_dep=P.T0), P.station("A1", 200.0, raw_arr=P.T0 + 20000), P.station("B1", 300.0, raw_dep=P.T0 + 40000),
                P.station("A2", P.A_MARK, raw_arr=P.T0 + 90000), P.station("B2", 1500.0, raw_dep=P.T0 + 150000), P.station("E", 3000.0, terminal=True)]
        o.station_list = s.sl
        ps, why = self.PC.decode_ptpair("PTPAIR:1:%s:6:2:1-2-0;3-4-0" % P.R.SCOPE_LIST_ID, 6)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        o.setting_start_idx, o.setting_end_idx = 0, 5
        return s

    def test_OD26_a_section_that_crosses_two_pairs_fixes_the_whole_set_and_survives_a_drift(self):
        s = self.scene6()
        self.press_start(s)
        o = s.o
        # the train is placed before the SECOND pair's A (index 3); the settings drift so that a re-derivation would find A2 = the end (not crossing)
        o.setting_start_idx = 3                      # drift: start == A2
        o.bve_tgt_idx, o.bve_arr_idx = 3, 2
        o.bve_next_loc = o.prev_next_loc = self.P.A_MARK
        self.P.R.bind_identity(o, arr_idx=2, tgt_idx=3)
        self.S.reset_station_evaluation_state(o)
        s.approach("plain")
        s.stop_at(0.3)
        s.step(1, bve_door=1, bve_arr_idx=3, bve_arr_seq=1)
        self.assertEqual(s.machine.state, M.ARMED, "the set {A1->B1, A2->B2} was fixed at the start: A2 is a target whatever the settings say now")
        self.assertEqual(s.machine.pair.arrival, 3)

    def test_OD26_the_control_without_drift_arms_the_second_pair(self):
        s = self.scene6()
        self.press_start(s)
        o = s.o
        o.bve_tgt_idx, o.bve_arr_idx = 3, 2
        o.bve_next_loc = o.prev_next_loc = self.P.A_MARK
        self.P.R.bind_identity(o, arr_idx=2, tgt_idx=3)
        self.S.reset_station_evaluation_state(o)
        s.approach("plain")
        s.stop_at(0.3)
        s.step(1, bve_door=1, bve_arr_idx=3, bve_arr_seq=1)
        self.assertEqual(s.machine.state, M.ARMED)

    def test_OD26_a_retry_keeps_the_contract_fixed_at_the_start(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        result = self.main.execute_retry(o, 0, False)
        self.assertTrue(result.accepted, result)
        o.jump_expectation = None
        o.retry_pending = None
        o.is_official_jumping = False
        o.jump_lock = False
        o.setting_start_idx = 1                      # drift after the Retry
        o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        o.bve_next_loc = o.prev_next_loc = self.P.A_MARK
        o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq = 1, 0, 0
        o.bve_location, o.bve_speed = self.P.A_MARK - 400.0, 30.0
        o.bve_door = o.prev_door = 0
        self.P.R.bind_identity(o, arr_idx=0, tgt_idx=1)
        self.S.reset_station_evaluation_state(o)
        self.arrive_at_a(s)
        self.assertEqual(s.machine.state, M.ARMED, "a Retry keeps the section contract of the start button")


if __name__ == "__main__":
    unittest.main()
