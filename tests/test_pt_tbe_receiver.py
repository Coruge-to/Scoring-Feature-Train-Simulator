"""Stage TB-E (B): the Python receiver. A telemetry line that carries the PTPAIR key is applied with the REAL Overlay (apply_telemetry_text, then the sync that follows every applied line); what the
Overlay does with it is judged through the product's own observable surfaces: the machine's pair set (the place the TB-D candidate lists read), the REAL scoring setup menu (handle_menu_enter), the REAL
managed start gate, the REAL lifecycle hooks (a new scenario generation, session off, shutdown) and Retry.
Owner decisions OD-TE-1..6; the TB-C / TB-D contracts (A excluded from the start candidates, B from the end candidates, the Run-specific set fixed once at the start button) are only USED here."""
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

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbe-recv-")
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


LID = "A1B2C3D4"
SID = 7


def line(scn, ptpair=None, extra=""):
    text = "SCENARIO_ID:%d,TIME:36000000,LOCATION:0.0,SPEED:0.0%s" % (scn, extra)
    if ptpair is not None:
        text += "," + ptpair
    return text


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbe-recv"])
        import main
        import scoring_logic
        import pt_scene
        import route_pairset
        import sia_managed_rig
        cls.main, cls.S, cls.P, cls.RP, cls.MR = main, scoring_logic, pt_scene, route_pairset, sia_managed_rig

    def scene(self, stations=None):
        s = self.P.Scene(self, drive=False, with_pairs=False)
        if stations is not None:
            s.sl = stations
            s.o.station_list = s.sl
        s.o.is_scoring_mode = False
        return s

    def feed(self, s, scn=SID, ptpair=None):
        """One applied telemetry line: apply_telemetry_text, then the sync the product runs after every applied line."""
        s.o.apply_telemetry_text(line(scn, ptpair))
        s.o._route_pairset_sync()

    def machine_pairset(self, s):
        machine = s.o.__dict__.get('turnback_machine')
        return None if machine is None else machine.pairset

    def cands(self, s, x):
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 0, x
        o.handle_menu_enter(False)
        return [opt["idx"] for opt in o.dropdown_options]

    def starts(self, s):
        return self.cands(s, 0)

    def ends(self, s):
        return self.cands(s, 1)


class A_TheLineIntake(Base):
    def test_capture_takes_the_generation_and_the_text_of_the_same_line(self):
        parts = line(9, "PTPAIR:1:%s:5:1:1-2-0" % LID).split(",")
        self.assertEqual(self.RP.capture(parts), (9, "PTPAIR:1:%s:5:1:1-2-0" % LID))

    def test_capture_of_a_line_without_the_key_is_none(self):
        self.assertIsNone(self.RP.capture(line(9).split(",")))

    def test_capture_without_a_generation_keeps_the_text_and_no_generation(self):
        self.assertEqual(self.RP.capture(["PTPAIR:1:%s:5:0:" % LID, "TIME:5"]), (None, "PTPAIR:1:%s:5:0:" % LID))

    def test_a_line_with_pairs_makes_the_machine_hold_the_pair_set_the_candidates_read(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual(self.RP.state_of(s.o), self.RP.READY_NONEMPTY)
        ps = self.machine_pairset(s)
        self.assertIsNotNone(ps)
        self.assertEqual([(p.arrival, p.departure) for p in ps.pairs], [(1, 2)])

    def test_a_line_with_zero_pairs_is_ready_empty_and_creates_no_machine(self):
        s = self.scene()
        s.o.__dict__.pop('turnback_machine', None)
        self.feed(s, ptpair="PTPAIR:1:%s:5:0:" % LID)
        self.assertEqual(self.RP.state_of(s.o), self.RP.READY_EMPTY)
        self.assertNotIn('turnback_machine', s.o.__dict__)

    def test_before_any_line_the_state_is_unavailable_and_it_is_not_an_empty_route(self):
        s = self.scene()
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.feed(s)                                                 # a line WITHOUT the key
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertNotEqual(self.RP.state_of(s.o), self.RP.READY_EMPTY)

    def test_the_normal_mode_has_no_gate_so_it_is_not_made_to_wait_for_the_key(self):
        s = self.scene()
        self.assertFalse(hasattr(s.o, "scoring_start_gate"))
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)

    def test_an_invalid_key_leaves_the_state_unavailable_and_the_machine_without_a_pair_set(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-1-0" % LID)
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertIsNone(self.machine_pairset(s))

    def test_the_key_of_another_station_list_is_not_adopted(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:FFFFFFFF:5:1:1-2-0")
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)

    def test_the_sync_after_the_station_list_changed_drops_the_old_binding(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        s.o.bve_list_id = "0000AAAA"                                 # the adopted list is another one now, the line carries no key
        self.feed(s)
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertIsNone(self.machine_pairset(s))

    def test_a_line_without_the_key_does_not_drop_a_ready_state(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.feed(s)
        self.feed(s)
        self.assertEqual(self.RP.state_of(s.o), self.RP.READY_NONEMPTY)
        self.assertIsNotNone(self.machine_pairset(s))

    def test_the_generation_of_the_line_is_judged_against_the_current_generation(self):
        s = self.scene()
        s.o._ptpair_raw = (SID - 1, "PTPAIR:1:%s:5:1:1-2-0" % LID)          # an older generation's line
        s.o._route_pairset_sync()
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        s.o._ptpair_raw = (SID + 1, "PTPAIR:1:%s:5:1:1-2-0" % LID)          # a newer one: never applied ahead, the current generation is not moved
        s.o._route_pairset_sync()
        self.assertEqual((self.RP.state_of(s.o), s.o.current_scenario_id), (self.RP.UNAVAILABLE, SID))
        self.assertIsNone(self.machine_pairset(s))


class B_TheCandidates(Base):
    """The REAL scoring setup menu, with the pair set that the product itself delivered (no injection)."""

    def test_the_a_of_a_pair_is_no_start_and_the_b_is_no_end_the_end_list_also_leaves_the_start(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertNotIn(1, self.starts(s))
        self.assertIn(2, self.starts(s))
        self.assertNotIn(2, self.ends(s))
        self.assertIn(1, self.ends(s))

    def test_ready_empty_leaves_the_candidates_as_they_ever_were(self):
        plain = self.scene()
        before = (self.starts(plain), self.ends(plain))
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:0:" % LID)
        self.assertEqual((self.starts(s), self.ends(s)), before)

    def test_same_named_stations_are_told_apart_by_the_station_index(self):
        P = self.P
        sl = [P.station("S0", 0.0, raw_dep=P.T0), P.station("X", 1000.0, raw_arr=P.T0 + 9000), P.station("Y", 1500.0, raw_dep=P.T0 + 15000),
              P.station("X", 3000.0), P.station("Z", 5000.0, terminal=True)]
        s = self.scene(stations=sl)
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        starts = self.starts(s)
        self.assertNotIn(1, starts)
        self.assertIn(3, starts)                                      # the other station called X stays

    def test_the_raw_terminal_that_is_a_b_is_no_end_and_the_initial_end_is_the_last_filtered_candidate(self):
        P = self.P
        sl = [P.station("S0", 0.0, raw_dep=P.T0), P.station("NA", P.A_MARK, raw_arr=P.T0 + 90000), P.station("NB", P.B_MARK, raw_dep=P.T0 + 150000, terminal=True)]
        s = self.scene(stations=sl)
        self.assertEqual(s.o.get_actual_terminal_idx(), 2)
        self.feed(s, ptpair="PTPAIR:1:%s:3:1:1-2-0" % LID)
        self.assertNotIn(2, self.ends(s))
        s.o.setting_end_idx = -1
        self.assertEqual(s.o.get_actual_terminal_idx(), 1)

    def test_the_end_stations_of_the_brake_rules_are_not_changed_by_the_pair_set(self):
        def brake(s):
            o = s.o
            o.is_scoring_mode = False
            o.dropdown_active = False
            o.brake_rules = [{"end_idx": -1, "apply": "階段", "release": "階段"}]
            o.menu_state, o.sub_cursor, o.sub_cursor_x = 7, 0, 0
            o.handle_menu_enter(False)
            return [opt["idx"] for opt in o.dropdown_options]
        before = brake(self.scene())
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual(brake(s), before)

    def test_a_start_or_end_chosen_before_the_set_arrived_is_normalised_not_refused(self):
        s = self.scene()
        s.o.setting_start_idx, s.o.setting_end_idx = 1, 2
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual((s.o.setting_start_idx, s.o.setting_end_idx), (0, -1))

    def test_an_allowed_choice_is_left_alone(self):
        s = self.scene()
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 4
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual((s.o.setting_start_idx, s.o.setting_end_idx), (2, 4))

    def test_the_settings_of_a_running_scoring_are_never_normalised(self):
        s = self.scene()
        s.o.is_scoring_mode = True
        s.o.setting_start_idx, s.o.setting_end_idx = 1, 2
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual((s.o.setting_start_idx, s.o.setting_end_idx), (1, 2))


class C_RepeatsAndTheRun(Base):
    def test_the_same_key_on_every_line_changes_nothing_after_the_first(self):
        s = self.scene()
        text = "PTPAIR:1:%s:5:1:1-2-0" % LID
        self.feed(s, ptpair=text)
        machine, pairset = s.o.turnback_machine, self.machine_pairset(s)
        accepted = self.RP.holder_of(s.o).accepted
        s.o.setting_start_idx = 2
        for _ in range(6):
            self.feed(s, ptpair=text)
        self.assertIs(s.o.turnback_machine, machine)
        self.assertIs(self.machine_pairset(s), pairset)
        self.assertEqual(self.RP.holder_of(s.o).accepted, accepted)
        self.assertEqual(s.o.setting_start_idx, 2)

    def test_a_different_valid_key_of_the_same_generation_never_overwrites_the_first(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        pairset = self.machine_pairset(s)
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:2-3-0" % LID)
        self.assertIs(self.machine_pairset(s), pairset)
        self.assertEqual([(p.arrival, p.departure) for p in pairset.pairs], [(1, 2)])

    def test_the_same_key_again_does_not_normalise_a_later_choice_it_is_not_a_new_acceptance(self):
        s = self.scene()
        text = "PTPAIR:1:%s:5:1:1-2-0" % LID
        self.feed(s, ptpair=text)
        s.o.setting_start_idx = 1                                   # (not reachable through the candidate lists; what is judged is that a repeated key re-initialises nothing)
        self.feed(s, ptpair=text)
        self.assertEqual(s.o.setting_start_idx, 1)

    def test_a_repeated_key_during_the_run_does_not_fix_the_section_again(self):
        s = self.scene()
        text = "PTPAIR:1:%s:5:1:1-2-0" % LID
        self.feed(s, ptpair=text)
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 4
        self.S.turnback_fix_section(o)
        machine = o.turnback_machine
        fixed, fixed_by_a = machine.fixed, machine.fixed_by_a
        self.assertEqual([(p.arrival, p.departure) for p in fixed], [(1, 2)])
        o.is_scoring_mode = True
        for _ in range(4):
            self.feed(s, ptpair=text)
        self.assertIs(machine.fixed, fixed)
        self.assertIs(machine.fixed_by_a, fixed_by_a)
        # even a conflicting key during the run changes neither the pair set nor the fixed section
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:3-4-0" % LID)
        self.assertIs(machine.fixed, fixed)
        self.assertEqual([(p.arrival, p.departure) for p in machine.pairset.pairs], [(1, 2)])

    def test_the_run_pair_set_is_taken_from_the_route_pair_set_the_product_delivered(self):
        s2 = self.scene()
        self.feed(s2, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        o = s2.o
        o.setting_start_idx, o.setting_end_idx = 0, 4
        self.S.turnback_fix_section(o)
        self.assertEqual([(p.arrival, p.departure) for p in o.turnback_machine.fixed], [(1, 2)])
        o.setting_start_idx, o.setting_end_idx = 0, 1                 # a section that ends at the A: no pair is crossed
        self.S.turnback_fix_section(o)
        self.assertEqual(o.turnback_machine.fixed, ())


class F_TheRunPairSet(Base):
    """OD-TE-1 steps 8-10: the Run's pair set is taken ONCE from the route pair set the product delivered and the start / end of the section (the existing TB-C / TB-D contract is only used)."""
    KEY = "PTPAIR:1:%s:6:2:1-2-0;3-4-0" % LID

    def six(self):
        P = self.P
        sl = [P.station("S0", 0.0, raw_dep=P.T0), P.station("A1", 200.0, raw_arr=P.T0 + 20000), P.station("B1", 300.0, raw_dep=P.T0 + 40000),
              P.station("A2", P.A_MARK, raw_arr=P.T0 + 90000), P.station("B2", 1500.0, raw_dep=P.T0 + 150000), P.station("E", 3000.0, terminal=True)]
        s = self.scene(stations=sl)
        self.feed(s, ptpair=self.KEY)
        return s

    def fixed(self, s, start, end):
        s.o.setting_start_idx, s.o.setting_end_idx = start, end
        self.S.turnback_fix_section(s.o)
        return [(p.arrival, p.departure) for p in s.o.turnback_machine.fixed]

    def test_a_section_over_two_pairs_fixes_both(self):
        s = self.six()
        self.assertEqual(self.fixed(s, 0, 5), [(1, 2), (3, 4)])

    def test_a_section_over_one_pair_fixes_that_pair_only(self):
        s = self.six()
        self.assertEqual(self.fixed(s, 0, 3), [(1, 2)])                # the section ends at the A of the second pair: that pair is not crossed

    def test_a_section_that_starts_at_a_b_does_not_include_the_pair_before_it(self):
        s = self.six()
        self.assertEqual(self.fixed(s, 2, 5), [(3, 4)])

    def test_a_section_that_crosses_no_pair_has_an_empty_run_set(self):
        s = self.six()
        self.assertEqual(self.fixed(s, 2, 3), [])
        self.assertEqual(self.fixed(s, 4, 5), [])

    def test_the_section_that_ends_at_an_a_has_no_pair_of_that_a(self):
        s = self.six()
        self.assertEqual(self.fixed(s, 0, 1), [])

    def test_the_next_run_is_fixed_anew_from_its_own_start_and_end(self):
        s = self.six()
        first = self.fixed(s, 0, 5)
        machine = s.o.turnback_machine
        fixed_before = machine.fixed
        second = self.fixed(s, 2, 5)
        self.assertEqual((first, second), ([(1, 2), (3, 4)], [(3, 4)]))
        self.assertIsNot(machine.fixed, fixed_before)

    def test_no_run_set_is_made_without_a_ready_route_pair_set(self):
        s = self.scene()
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 4
        self.S.turnback_fix_section(s.o)
        self.assertNotIn('turnback_machine', s.o.__dict__)


class D_Lifecycle(Base):
    def test_a_new_scenario_generation_invalidates_the_old_set_and_a_new_key_is_accepted_as_the_new_generation(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual(self.RP.state_of(s.o), self.RP.READY_NONEMPTY)
        s.o.apply_telemetry_text(line(SID + 1))                      # the first line of the next scenario instance (F5): no key yet
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertIsNone(self.machine_pairset(s))
        s.o._route_pairset_sync()
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.feed(s, scn=SID + 1, ptpair="PTPAIR:1:%s:5:0:" % LID)
        self.assertEqual((self.RP.state_of(s.o), self.RP.holder_of(s.o).generation), (self.RP.READY_EMPTY, SID + 1))

    def test_the_old_key_is_not_reused_for_the_new_generation(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.feed(s, scn=SID + 1)                                     # the new generation says nothing
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertIsNone(self.machine_pairset(s))

    def test_a_failure_inside_the_sync_is_fail_closed(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        self.assertEqual(self.RP.state_of(s.o), self.RP.READY_NONEMPTY)
        original = self.RP.sync
        self.RP.sync = lambda overlay, machine_of: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            s.o._route_pairset_sync()
        finally:
            self.RP.sync = original
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertIsNone(self.machine_pairset(s))

    def test_the_epoch_reset_of_the_telemetry_gate_invalidates_too(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        s.o.reset_telemetry_state()
        self.assertEqual(self.RP.state_of(s.o), self.RP.UNAVAILABLE)
        self.assertIsNone(self.machine_pairset(s))

    def test_a_new_generation_drops_the_run_pair_set_with_the_route_pair_set(self):
        s = self.scene()
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 4
        self.S.turnback_fix_section(o)
        self.assertTrue(o.turnback_machine.fixed)
        o.apply_telemetry_text(line(SID + 1))
        machine = o.__dict__.get('turnback_machine')
        self.assertTrue(machine is None or (machine.fixed is None and machine.pairset is None))

    def test_the_retry_neither_receives_nor_derives_the_route_pair_set_again(self):
        s = self.scene()
        o = s.o
        self.feed(s, ptpair="PTPAIR:1:%s:5:1:1-2-0" % LID)
        o.setting_start_idx, o.setting_end_idx = 0, 4
        self.S.turnback_fix_section(o)
        o.is_scoring_mode = True
        holder = self.RP.holder_of(o)
        before = (holder.accepted, o.turnback_machine, o.turnback_machine.pairset, o.turnback_machine.fixed, o.turnback_machine.fixed_by_a)
        o.send_jump_command = lambda cmd: None
        try:
            self.main.execute_retry(o, 0, False)
        except Exception:
            pass                                                      # (the rig's history may refuse the retry: what is judged is that nothing of the pair sets moved)
        after = (holder.accepted, o.turnback_machine, o.turnback_machine.pairset, o.turnback_machine.fixed, o.turnback_machine.fixed_by_a)
        self.assertTrue(all(a is b or a == b for a, b in zip(before, after)))
        self.assertIs(self.RP.holder_of(o), holder)

    def test_the_sources_of_the_retry_do_not_name_the_route_pair_set(self):
        for name in ("scoring_logic.py",):
            with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) and fn.name in ("execute_retry", "turnback_lifecycle_guard", "turnback_fix_section"):
                    for n in ast.walk(fn):
                        ident = n.id if isinstance(n, ast.Name) else (n.attr if isinstance(n, ast.Attribute) else "")
                        self.assertNotIn("route_pairset", ident, fn.name)


class E_ManagedMode(Base):
    def setUp(self):
        self.r = self.MR.ManagedRig(self.main)
        self.addCleanup(self.r.close)
        self.o = self.r.o

    def key(self, count=3, pairs=0, entries=""):
        lid = self.MR.station_index_contract.list_id(self.MR.STALIST.split(":", 1)[1])
        return "PTPAIR:1:%s:%d:%d:%s" % (lid, count, pairs, entries)

    def test_without_the_key_the_start_is_refused_with_a_diagnostic_and_no_popup(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=None)
        self.assertEqual(self.RP.state_of(o), self.RP.UNAVAILABLE)
        self.assertIn("pairset-unavailable", o.scoring_start_gate.__self__.start_blockers())
        r.start_scoring_via_menu()
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(any("pairset-unavailable" in e for e in r.events("scoring-start-refused")), r.events("scoring-start-refused"))
        self.assertEqual([p for p in o.popups if p.get("category") == "警告"], [])

    def test_with_a_stated_zero_pair_set_the_start_goes_ahead(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key())
        self.assertEqual(self.RP.state_of(o), self.RP.READY_EMPTY)
        self.assertNotIn("pairset-unavailable", o.scoring_start_gate.__self__.start_blockers())
        r.start_scoring_via_menu()
        self.assertTrue(o.is_scoring_mode)

    def test_the_ready_state_is_reached_before_the_first_menu_is_ever_opened(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key(count=3, pairs=0))
        self.assertEqual(o.menu_state, 0)
        self.assertEqual(self.RP.state_of(o), self.RP.READY_EMPTY)

    def test_the_diagnostic_event_names_the_version_the_generations_the_state_and_the_count(self):
        r = self.r
        r.go_active(PTPAIR=self.key())
        events = r.events("routepairset")
        self.assertTrue(events, "no routepairset event")
        text = " ".join(str(e) for e in events)
        for word in ("ver=1", "state=READY_EMPTY", "pairs=0", "rx=", "cur="):
            self.assertIn(word, text)

    def test_a_new_scenario_generation_in_the_managed_mode_invalidates_and_waits_for_the_new_key(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key())
        self.assertEqual(self.RP.state_of(o), self.RP.READY_EMPTY)
        r.publish(True, True, 2)
        r.tick(2)
        r.send(self.MR.STALIST, self.MR.tele(2, PTPAIR=None))
        r.tick(2)
        self.assertEqual(self.RP.state_of(o), self.RP.UNAVAILABLE)
        self.assertIn("pairset-unavailable", o.scoring_start_gate.__self__.start_blockers())
        r.send(self.MR.STALIST, self.MR.tele(2, PTPAIR=self.key()))
        self.assertEqual(self.RP.state_of(o), self.RP.READY_EMPTY)

    def test_the_session_off_discards_the_state(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key())
        r.publish(False, False)
        r.tick(3)
        self.assertEqual(self.RP.state_of(o), self.RP.UNAVAILABLE)

    def test_the_shutdown_discards_the_state(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key())
        self.main._release_overlay(o, r.hud)
        self.assertEqual(self.RP.state_of(o), self.RP.UNAVAILABLE)

    def test_one_line_without_the_key_does_not_make_the_ready_state_unavailable(self):
        r, o = self.r, self.o
        r.go_active(PTPAIR=self.key())
        r.send(self.MR.tele(1, PTPAIR=None))
        self.assertEqual(self.RP.state_of(o), self.RP.READY_EMPTY)

if __name__ == "__main__":
    unittest.main()
