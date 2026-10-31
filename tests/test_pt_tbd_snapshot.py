"""Stage TB-D, slice D2 (OD-TD-4 and the dormant-defence GUARD of the TB-C start-time correction): the scoring start button fixes ONE immutable scoring-section snapshot (start / end StationIndex, section, generation,
the crossed pairs, target-or-not) in ONE attribute of the Overlay; after it nothing re-derives start / end / pairs from the settings, the candidates, the target, NEXTLOC, the position, the doors or the signals.
The REAL start handler (Overlay.handle_menu_enter, menu_state 10 / cursor 1) is driven. The TB-C correction of the start button (turnback_fix_section: an end that is a B is written back as its A) must stay
as a dormant defence: with the new candidate contract the end is already A BEFORE the button, so the defence must not fire; when it fires (abnormal input) it must be diagnosable."""
import ast
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
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbd-snap-")
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


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbd-snap"])
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

    def press_start(self, s, expect=True):
        """The REAL scoring start button (as tests/test_pt_tbc_section.py)."""
        o = s.o
        s.auto_fix = False
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor = 10, 1
        o.scoring_start_gate = None
        o.was_advancing_before_menu = False
        self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
        o.bve_location, o.bve_speed = 0.0, 0.0
        o.handle_menu_enter(False)
        if expect:
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
        return s.open_door()

    def snap(self, s):
        return s.o.__dict__.get("_scoring_section")


class A_Snapshot(Base):
    def test_SN_1_there_is_no_snapshot_before_the_start(self):
        s = self.scene()
        self.assertIsNone(self.snap(s))

    def test_SN_2_the_start_fixes_one_immutable_snapshot(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        snap = self.snap(s)
        self.assertIsNotNone(snap)
        self.assertEqual((snap.start, snap.end, snap.section), (0, 4, (0, 4)))
        self.assertEqual(snap.generation, s.o.current_scenario_id)
        self.assertEqual(tuple(snap.pairs), (self.PC.Pair(1, 2, 0),))
        self.assertTrue(snap.turnback)
        with self.assertRaises(AttributeError):
            snap.end = 1
        s2 = self.scene(start=2, end=4)
        self.press_start(s2)
        self.assertEqual((tuple(self.snap(s2).pairs), self.snap(s2).turnback), ((), False), "B -> 4 crosses no pair")

    def test_SN_2b_a_refused_start_makes_no_snapshot(self):
        s = self.scene()
        o = s.o
        o._scoring_start_plan = lambda snapshot, index=None: (0.0, "", -1, None, "refused-for-the-test")
        self.press_start(s, expect=False)
        self.assertFalse(o.is_scoring_mode)
        self.assertIsNone(self.snap(s))

    def test_SN_3_nothing_after_the_start_changes_the_section_and_the_end_judgement_follows_the_snapshot(self):
        s = self.scene(start=0, end=1)                       # the section ends at A
        self.press_start(s)
        before = self.snap(s)
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 1, 4         # the UI values drift
        for field, value in (("bve_door", 1), ("bve_doordir", 0), ("bve_signal_limit", 0.0)):
            setattr(o, field, value)
        o.bve_door, o.bve_doordir, o.bve_signal_limit = 0, 1, 1000.0
        self.assertIs(self.snap(s), before)
        self.arrive_at_a(s)
        self.assertTrue(o.is_scoring_finished, "the end station of the snapshot (A) ends the scoring whatever the UI value says now")
        self.assertEqual(s.machine.state, M.IDLE)

    def test_SN_3b_a_section_that_crosses_A_to_B_keeps_running_whatever_the_UI_value_says(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        o.setting_end_idx = 1                                  # the UI value drifts to the A
        self.arrive_at_a(s)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(s.machine.state, M.ARMED, "the pair fixed at the start is a target whatever the UI says now")

    def test_SN_3c_target_nextloc_position_changes_do_not_rebuild_the_snapshot(self):
        s = self.scene()
        self.press_start(s)
        before = self.snap(s)
        o = s.o
        o.bve_tgt_idx, o.bve_next_loc, o.bve_location = 3, 3000.0, 2000.0
        s.step(3)
        self.assertIs(self.snap(s), before)
        self.assertEqual((before.start, before.end), (0, 4))

    def test_SN_11_the_timing_rule_of_the_running_scoring_takes_the_start_of_the_snapshot(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        self.assertFalse(o.is_station_timing(0), "the start station of the Run is no timing station")
        o.setting_start_idx = 1                                  # the UI value drifts
        self.assertTrue(o.is_station_timing(1), "the start of the Run is still the snapshot\x27s (0)")
        self.assertFalse(o.is_station_timing(0))

    def test_SN_4_a_retry_keeps_the_snapshot_and_never_rebuilds_it_from_the_UI(self):
        s = self.scene()
        self.press_start(s)
        before = self.snap(s)
        o = s.o
        result = self.main.execute_retry(o, 0, False)
        self.assertTrue(result.accepted, result)
        o.setting_start_idx, o.setting_end_idx = 2, 3
        s.step(2)
        self.assertIs(self.snap(s), before)

    def test_SN_6_a_generation_change_drops_the_snapshot(self):
        s = self.scene()
        self.press_start(s)
        o = s.o
        o.current_scenario_id = o.current_scenario_id + 1
        self.assertIsNone(self.S.active_scoring_section(o), "never used for another generation")
        s.step(1)
        self.assertIsNone(self.snap(s), "dropped, not carried into the new generation")

    def test_SN_7_the_end_of_the_scoring_and_the_session_off_drop_the_snapshot(self):
        for how in ("session-off", "finished"):
            with self.subTest(how=how):
                s = self.scene()
                self.press_start(s)
                if how == "session-off":
                    s.o.is_scoring_mode = False
                else:
                    s.o.is_scoring_finished = True
                self.assertIsNone(self.S.active_scoring_section(s.o))
                s.step(1)
                self.assertIsNone(self.snap(s))

    def test_SN_8_a_new_start_makes_a_new_snapshot_from_the_new_selection(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        first = self.snap(s)
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 3
        self.press_start(s)
        second = self.snap(s)
        self.assertIsNot(first, second)
        self.assertEqual((second.start, second.end), (2, 3))

    def test_SN_9_without_a_snapshot_the_settings_are_read_as_ever(self):
        s = self.P.Scene(self, drive=True)                      # the rig stands in for the start button; no snapshot
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 1
        self.assertIsNone(self.snap(s))
        s.approach("stepwise")
        s.stop_at(0.0)
        s.open_door()
        self.assertTrue(s.o.is_scoring_finished)

    def test_SN_10_the_pairs_are_the_fixed_set_and_no_runtime_reader_of_the_settings_is_left(self):
        s = self.scene()
        self.press_start(s)
        self.assertIs(self.snap(s).pairs, s.machine.fixed)
        tree = ast.parse(source("scoring_logic.py"))
        allowed = {"turnback_fix_section", "build_scoring_section", "section_start_index", "section_end_judge_index"}
        offenders = []
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
            if fn.name in allowed:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Constant) and node.value in ("setting_start_idx", "setting_end_idx"):
                    offenders.append((fn.name, node.value))
        self.assertEqual(offenders, [], "the runtime readers take the snapshot")


class B_FixSectionDefence(Base):
    def prepared(self, **kw):
        s = self.scene(terminal_b=True, start=0, end=-1, **kw)
        return s

    def spy_diag(self, s):
        events = []
        original = self.S.turnback_diag

        def spy(owner, event, **fields):
            events.append(event)
            return original(owner, event, **fields)
        self.S.turnback_diag = spy
        self.addCleanup(lambda: setattr(self.S, "turnback_diag", original))
        return events

    def test_FS1_the_end_is_already_A_in_the_UI_stage_before_the_start_button(self):
        s = self.prepared()
        o = s.o
        self.assertEqual(o.setting_end_idx, -1)
        self.assertEqual(o.get_actual_terminal_idx(), 1)
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 0, 1
        o.handle_menu_enter(False)
        self.assertEqual([x["idx"] for x in o.dropdown_options][-1], 1)

    def test_FS2_the_input_of_the_defence_and_the_snapshot_are_A_from_the_start(self):
        s = self.prepared()
        seen = []
        original = self.main.turnback_fix_section

        def spy(owner):
            seen.append((owner.get_actual_terminal_idx(), owner.setting_end_idx))
            return original(owner)
        self.main.turnback_fix_section = spy
        self.addCleanup(lambda: setattr(self.main, "turnback_fix_section", original))
        self.press_start(s)
        self.assertEqual(seen, [(1, -1)], "the end that reaches the start button is A (actual terminal) with the sentinel untouched")
        self.assertEqual((self.snap(s).start, self.snap(s).end), (0, 1))

    def test_FS3_the_correction_does_not_fire_in_the_normal_path(self):
        s = self.prepared()
        events = self.spy_diag(s)
        self.press_start(s)
        self.assertEqual(s.o.setting_end_idx, -1, "nothing was written back by the start button")
        self.assertNotIn("turnback-end-corrected", events)

    def test_FS4_without_the_correction_the_run_that_ends_at_A_has_an_empty_pair_set(self):
        s = self.prepared()
        self.press_start(s)
        self.assertEqual(tuple(s.machine.fixed), ())
        self.assertEqual(tuple(self.snap(s).pairs), ())
        self.assertFalse(self.snap(s).turnback)

    def test_FS5_the_arrival_at_A_finishes_the_scoring_and_no_official_jump_is_requested(self):
        s = self.prepared()
        self.press_start(s)
        t = self.arrive_at_a(s)
        self.assertTrue(s.o.is_scoring_finished)
        self.assertEqual(s.machine.state, M.IDLE)
        s.tick(advance_ms=t + 6000 - s.o.bve_time_ms)
        self.assertIsNone(s.o.jump_expectation)

    def test_FS6_the_defence_is_kept_and_diagnosable_when_the_input_is_abnormal(self):
        s = self.prepared()
        events = self.spy_diag(s)
        o = s.o
        o.get_actual_terminal_idx = lambda: 2                     # an abnormal input: the actual terminal is the B
        self.press_start(s)
        self.assertEqual(o.setting_end_idx, 1, "the TB-C defence still writes the A back")
        self.assertEqual(events.count("turnback-end-corrected"), 1, "and says so")

    def test_FS7_the_defence_does_not_hide_a_broken_contract(self):
        """The same scene WITHOUT the abnormal input must satisfy FS1 / FS2 / FS3 on its own: the final value alone is never the proof."""
        s = self.prepared()
        events = self.spy_diag(s)
        before = (s.o.setting_end_idx, s.o.get_actual_terminal_idx())
        self.press_start(s)
        self.assertEqual(before, (-1, 1))
        self.assertEqual(events.count("turnback-end-corrected"), 0)
        self.assertEqual(self.snap(s).end, 1)


class C_LifecycleContract(Base):
    """Stage 2.1 (Owner decision 2): the lifecycle of the snapshot as a MEANING, not as source lines. One scoring Run lasts from the start button until the scoring is aborted (menu), an illegal Jump ends it, the scenario
    is reloaded (F5: another generation) or it finishes; inside it the snapshot is made once and never rewritten. Observed from outside: every value ever assigned to Overlay._scoring_section, and every fixing of the
    section on the machine (TurnbackMachine.fix_section)."""

    def setUp(self):
        import pseudo_turnback_machine as PM
        self.assigned = []
        self.fixings = []
        cls = self.main.Overlay
        original_setattr = cls.__setattr__
        assigned = self.assigned

        def spy_setattr(obj, name, value):
            if name == "_scoring_section":
                assigned.append(value)
            return original_setattr(obj, name, value)
        cls.__setattr__ = spy_setattr
        self.addCleanup(lambda: setattr(cls, "__setattr__", original_setattr))
        original_fix = PM.TurnbackMachine.fix_section
        fixings = self.fixings

        def spy_fix(machine, pairs, generation):
            fixings.append((id(machine), generation))
            return original_fix(machine, pairs, generation)
        PM.TurnbackMachine.fix_section = spy_fix
        self.addCleanup(lambda: setattr(PM.TurnbackMachine, "fix_section", original_fix))

    def made(self):
        return [v for v in self.assigned if v is not None]

    def test_LC_1_no_valid_snapshot_before_the_start(self):
        s = self.scene()
        self.assertIsNone(self.snap(s))
        self.assertIsNone(self.S.active_scoring_section(s.o))
        self.assertEqual(self.assigned, [])

    def test_LC_2_one_start_makes_exactly_one_snapshot_and_fixes_the_section_once(self):
        s = self.scene()
        self.press_start(s)
        self.assertEqual(len(self.made()), 1)
        self.assertIs(self.made()[0], self.snap(s))
        self.assertEqual(len(self.fixings), 1)

    def test_LC_3_the_ticks_of_one_run_use_the_same_object_and_never_write_it_again(self):
        s = self.scene()
        self.press_start(s)
        first = self.snap(s)
        content = tuple(first)
        written, fixed = len(self.assigned), len(self.fixings)
        s.step(30)
        self.arrive_at_a(s)                                    # the chain of the pseudo-turnback runs inside the Run
        s.step(30)
        self.assertIs(self.snap(s), first)
        self.assertEqual(len(self.assigned), written, "nothing is assigned to the attribute during the Run")
        self.assertEqual(tuple(self.snap(s)), content, "the content is what the start fixed")
        self.assertEqual(len(self.fixings), fixed, "the section is not fixed again while the Run goes on")
        with self.assertRaises(AttributeError):
            first.start = 3

    def test_LC_4_the_pairs_stay_the_one_tuple_of_the_machine_for_the_whole_run(self):
        s = self.scene()
        self.press_start(s)
        snap, fixed = self.snap(s), s.machine.fixed
        self.assertIs(snap.pairs, fixed)
        s.step(10)
        self.arrive_at_a(s)
        s.step(10)
        self.main.execute_retry(s.o, 0, False)
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 3
        s.step(10)
        self.assertIs(s.machine.fixed, fixed)
        self.assertIs(self.snap(s).pairs, s.machine.fixed)
        self.assertEqual(s.machine.fixed_generation, self.snap(s).generation)

    def test_LC_5_a_retry_of_the_run_neither_rebuilds_nor_fixes_again(self):
        s = self.scene()
        self.press_start(s)
        first, written, fixed = self.snap(s), len(self.assigned), len(self.fixings)
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 3
        self.assertTrue(self.main.execute_retry(s.o, 0, False).accepted)
        s.step(5)
        self.assertIs(self.snap(s), first)
        self.assertEqual((len(self.assigned), len(self.fixings)), (written, fixed))

    def test_LC_6_every_end_of_the_run_makes_the_old_snapshot_unusable_and_it_is_not_carried_on(self):
        ways = {
            "abort-by-the-menu-or-an-illegal-jump": lambda o: setattr(o, "is_scoring_mode", False),
            "finished": lambda o: setattr(o, "is_scoring_finished", True),
            "scenario-reload-F5": lambda o: setattr(o, "current_scenario_id", o.current_scenario_id + 1),
        }
        for name, end_it in ways.items():
            with self.subTest(way=name):
                s = self.scene()
                self.press_start(s)
                self.assertIsNotNone(self.snap(s))
                n = len(self.made())
                end_it(s.o)
                self.assertIsNone(self.S.active_scoring_section(s.o), "never used once the Run is over")
                s.step(2)
                self.assertIsNone(self.snap(s), "dropped, not carried on")
                self.assertEqual(len(self.made()), n, "and no new snapshot was made by the ticks")

    def test_LC_7_the_next_run_gets_a_new_snapshot_and_a_new_fixed_tuple(self):
        s = self.scene()
        self.press_start(s)
        old, old_pairs = self.snap(s), s.machine.fixed
        s.o.is_scoring_mode = False
        s.step(2)
        self.assertIsNone(self.snap(s))
        self.press_start(s)
        new = self.snap(s)
        self.assertIsNotNone(new)
        self.assertIsNot(new, old)
        self.assertIsNot(new.pairs, old_pairs, "the old tuple is not reused")
        self.assertEqual(tuple(new.pairs), tuple(old_pairs))
        self.assertIs(new.pairs, s.machine.fixed)
        self.assertEqual(len(self.made()), 2)
        self.assertEqual(len(self.fixings), 2)


if __name__ == "__main__":
    unittest.main()
