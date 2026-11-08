"""Stage TB-H Stage 1 (RED): the scoring contract of the pseudo-turnback pair B (Owner ruling after the TB-G C-01 retest, 2026-11-01).

Contract (R2 / R3 / R4 / R5):
  * the B of every pair that the scoring section crosses is UNTIMED (effective timing for pair B = false): operating time 0 times, no stop position, no basic braking, no arrival bonus, no arrival checkpoint;
    the ONE pseudo-turnback B checkpoint stays; B -> next station is ordinary scoring.
  * reasons are separate: UNTIMED_SCORING_START (B is the start station of the Run) / UNTIMED_TURNBACK_B (the section crosses A -> B).
  * the set of B is decided by the section and the PairSet (StationIndex), never by name, door state, indicator lamp or signalFlag.
  * the theoretical score (main.py, the scoring settings page) leaves the crossed B out of n1 / n2 / n3.
  * the timing setting screen shows the crossed B as untimed and does not let the user toggle it.
  * Retry to the B checkpoint (layer A, state transition) restores the 'B operating time handled' state by itself and (layer B, scoring contract) scores nothing at B even when that state is lost.
RED = fails on the baseline 2387d17 for the contract reason. GUARD = passes on the baseline and must keep passing.
The REAL handlers are driven (handle_menu_enter, execute_retry, update_physics_and_scoring); the API names that do not exist yet are marked RED-API in the test name."""
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_pt_tbd_snapshot import Base as SnapshotBase, setUpModule, tearDownModule  # noqa: E402,F401
from test_pt_tbg_landing_order import Base as LandingBase  # noqa: E402

UNTIMED_B = "UNTIMED_TURNBACK_B"
UNTIMED_START = "UNTIMED_SCORING_START"


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def theory_of(owner, start, end):
    """The REAL scoring-settings handler (menu_state 6, the 'next page' row) computes the theoretical score."""
    owner.setting_start_idx, owner.setting_end_idx = start, end
    owner.menu_state, owner.menu_cursor, owner.menu_cursor_x = 6, 6, 0
    owner.handle_menu_enter(False)
    return owner.theoretical_score


class A_Theory(SnapshotBase):
    """R1 / R3: the theoretical score. Scene: S0 0 m / A 1 / B 2 / C 3 / D 4 (terminal), PTPAIR A=1 B=2; every station is a timing station, the brake rule is 'step', all four are scored stations."""

    def test_TH_1_the_B_of_a_crossed_pair_is_out_of_the_theoretical_score(self):
        s = self.scene(start=0, end=4)
        # stations 1..4 are scored stations; B (2) is not scored: n1 = n2 = n3 = 3 -> 3 * (500 + 500 + 300)
        self.assertEqual(theory_of(s.o, 0, 4), 3900, "RED on the baseline: it is 5200 (B counted as 500 + 500 + 300)")

    def test_TH_2_an_ordinary_route_without_a_PairSet_is_unchanged(self):
        s = self.P.Scene(self, with_pairs=False)
        self.assertEqual(theory_of(s.o, 0, 4), 5200, "GUARD: no PairSet -> every station counts, as ever")

    def test_TH_3_a_section_that_does_not_cross_the_pair_is_unchanged(self):
        s = self.scene(start=0, end=1)
        self.assertEqual(theory_of(s.o, 0, 1), 1300, "GUARD: the section ends at A, B is not in the section")
        s = self.scene(start=2, end=4)
        self.assertEqual(theory_of(s.o, 2, 4), 2600, "GUARD: B is the START station: it is out already (the start is never counted); C and D count")

    def test_TH_4_the_B_is_found_by_StationIndex_not_by_name_door_or_signal_flag(self):
        s = self.scene(start=0, end=4)
        for st in s.sl:
            st["name"] = "X"                                  # no station is called B / A
        s.sl[2]["is_pass"] = False
        s.o.bve_door, s.o.bve_doordir, s.o.bve_is_pass = 1, 0, 1
        self.assertEqual(theory_of(s.o, 0, 4), 3900, "RED on the baseline: names, doors and signals do not change which stations the section crosses")
        s = self.scene(start=0, end=4)
        s.sl[3]["name"] = "B"                                  # a station called B that is no pair B is NOT excluded
        self.assertEqual(theory_of(s.o, 0, 4), 3900, "the PairSet decides: exactly one B is out")

    def test_TH_5_a_timing_override_of_B_does_not_bring_it_back_and_the_other_stations_are_untouched(self):
        s = self.scene(start=0, end=4)
        s.o.user_timing_overrides[2] = True
        s.o.user_timing_overrides[3] = False                    # C is switched to untimed by the user: a normal station, its 300 goes
        self.assertEqual(theory_of(s.o, 0, 4), 3600, "RED on the baseline: 5200 - 300 (C) = 4900 there; with B out: 3900 - 300 (C) = 3600")

    def test_TH_6_the_base_off_and_time_off_flags_follow_the_scored_stations_only(self):
        s = self.scene(start=0, end=4)
        for st in s.sl:
            st["is_timing"] = False
        s.sl[2]["is_timing"] = True                               # only B is a timing station: B is no scored station -> no timing station is left
        theory_of(s.o, 0, 4)
        self.assertTrue(s.o.is_time_off, "RED on the baseline: B alone made the run look timed (n3 = 1)")

    def test_TH_7_every_pair_B_of_the_section_goes_out_in_C01_shape(self):
        # four pairs W..Z: A1/B1 .. A4/B4 -> 11 stations after W, 7 scored: 7 * 1300 = 9100 against 14300
        from pseudo_turnback_contract import decode_ptpair
        s = self.P.Scene(self, with_pairs=False)
        names = ["W", "X", "A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4", "Y", "Z"]
        sl = [self.P.station(n, 500.0 * i, raw_dep=self.P.T0 + 1000 * i, raw_arr=self.P.T0 + 1000 * i) for i, n in enumerate(names)]
        sl[-1]["is_terminal"] = True
        s.o.station_list = s.sl = sl
        ptpair = "PTPAIR:1:%s:12:4:2-3-0;4-5-0;6-7-0;8-9-0" % self.P.R.SCOPE_LIST_ID
        ps, why = self.PC.decode_ptpair(ptpair, 12)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        self.assertEqual(theory_of(s.o, 0, 11), 9100, "RED on the baseline: 14300 (the four B stations count 4 * 1300)")


class B_UntimedContract(SnapshotBase):
    """R2 / R4: effective timing and the reasons."""

    def test_UB_1_RED_API_the_reason_codes_are_separate(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        reason = getattr(self.S, "untimed_reason", None)
        self.assertIsNotNone(reason, "RED-API: scoring_logic.untimed_reason(owner, station_index) -> None | UNTIMED_SCORING_START | UNTIMED_TURNBACK_B does not exist on the baseline")
        o = s.o
        self.assertEqual(reason(o, 2), UNTIMED_B)
        self.assertEqual(reason(o, 0), UNTIMED_START)
        self.assertIsNone(reason(o, 1))
        self.assertIsNone(reason(o, 3))

    def test_UB_2_RED_API_B_as_the_scoring_start_has_its_own_reason(self):
        s = self.scene(start=2, end=4)
        self.press_start(s)
        reason = getattr(self.S, "untimed_reason", None)
        self.assertIsNotNone(reason, "RED-API")
        self.assertEqual(reason(s.o, 2), UNTIMED_START, "the section does not cross A -> B: the start reason, not the turnback reason")

    def test_UB_3_in_a_Run_that_crosses_the_pair_B_is_not_a_timing_station_whatever_the_override_says(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        self.assertTrue(o.is_station_timing(1), "A is an ordinary timing station")
        self.assertFalse(o.is_station_timing(2), "RED on the baseline: B is a timing station (is_timing True)")
        o.user_timing_overrides[2] = True
        self.assertFalse(o.is_station_timing(2), "an override can not switch pair B on")

    def test_UB_4_a_Run_that_does_not_cross_the_pair_keeps_the_ordinary_rule_for_B(self):
        s = self.scene(start=0, end=1)
        self.press_start(s)
        self.assertTrue(s.o.is_station_timing(2), "GUARD: the section ends at A, B is outside the Run: the ordinary rule (unchanged)")

    def test_UB_5_the_untimed_B_comes_from_the_fixed_section_and_the_PairSet_and_stays_after_the_menu_changes(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 3, 4              # what the menu says now: it must not release B inside the running Run
        self.assertFalse(o.is_station_timing(2), "RED on the baseline")
        for st in s.sl:
            st["name"] = "Z"
        o.bve_door, o.bve_doordir = 1, 1
        self.assertFalse(o.is_station_timing(2), "names / doors do not matter")

    def test_UB_6_the_timing_screen_before_the_start_follows_the_chosen_section(self):
        s = self.scene(start=0, end=4)                              # before the start button: the section is only chosen (settings)
        o = s.o
        self.assertFalse(o.is_station_timing(2), "RED on the baseline: with the chosen section crossing the pair, B is already untimed on the timing screen")
        s2 = self.scene(start=0, end=1)
        self.assertTrue(s2.o.is_station_timing(2), "GUARD: no crossing, B is an ordinary station while the section is chosen")
        s3 = self.P.Scene(self, with_pairs=False)
        s3.o.setting_start_idx, s3.o.setting_end_idx = 0, 4
        self.assertTrue(s3.o.is_station_timing(2), "GUARD: no PairSet -> never a pair B")

    def test_UB_7_the_user_can_not_toggle_B_and_no_override_is_left_behind(self):
        s = self.scene(start=0, end=4)
        o = s.o
        targets = o.get_timing_target_stas()
        o.menu_state = 8
        o.timing_cursor = targets.index(2)
        o.handle_menu_enter(False)
        self.assertNotIn(2, o.user_timing_overrides, "RED on the baseline: the toggle writes an override for B (it is hidden by the flag only while the section crosses the pair)")
        self.assertFalse(o.is_station_timing(2))
        o.timing_cursor = targets.index(3)
        o.handle_menu_enter(False)
        self.assertEqual(o.user_timing_overrides.get(3), False, "GUARD: an ordinary station still toggles (timing -> untimed)")

    def test_UB_8_the_all_stations_toggle_neither_changes_B_nor_sees_it_as_a_user_change(self):
        s = self.scene(start=0, end=4)
        o = s.o
        o.toggle_all_timing()
        self.assertNotIn(2, o.user_timing_overrides)
        self.assertFalse(o.is_station_timing(2))
        self.assertEqual(dict(o.user_timing_overrides), {}, "RED on the baseline: B (default timing, current untimed) reads as 'modified from default', so the first press clears instead of setting; with B untimed by contract nothing is modified")

    def test_UB_11_the_all_stations_toggle_writes_no_override_for_B_even_when_the_station_data_says_untimed(self):
        """The writer, not only the reader: with B's station data untimed (is_timing False) the 'make every station timed' button must still leave B alone (no direct write that could outlive the section)."""
        s = self.scene(start=0, end=4)
        o = s.o
        for st in s.sl:
            st["is_timing"] = False                                   # every station is untimed in the data: the button wants to switch them all on
        o.toggle_all_timing()
        self.assertNotIn(2, o.user_timing_overrides, "RED on the baseline: B receives an override")
        self.assertEqual({k: v for k, v in o.user_timing_overrides.items()}, {1: True, 3: True, 4: True}, "the ordinary stations after the start are switched on, B and the start are not")
        self.assertFalse(o.is_station_timing(2))

    def test_UB_9_the_timing_screen_names_the_reason_and_draws_B_as_untimed(self):
        with open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue("untimed_reason" in text, "RED on the baseline: the timing screen reads only is_station_timing / is_start; with the reason API it draws the turnback B as untimed and not clickable (no menu_click_zones entry)")

    def test_UB_10_no_door_lamp_or_signal_flag_is_read_by_the_pair_B_decision(self):
        # GUARD (forward): the decision functions exist only after the fix; on the baseline the search finds nothing and passes. After the fix the same test is the guard of R3 (door / lamp / signalFlag are not inputs)
        tree = ast.parse(source("scoring_logic.py"))
        names = ("untimed_reason", "turnback_b_indexes")
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                used = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                used |= {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                for forbidden in ("bve_door", "bve_doordir", "prev_doordir", "signalFlag", "signal_flag", "lamp", "name", "bve_is_pass", "is_pass"):
                    self.assertNotIn(forbidden, used, "%s must not read %s" % (node.name, forbidden))


class C_RetryToB(LandingBase):
    """R5, two layers kept apart. The real C-01 order (operational A, the Jump settlement absorbs the JUMP counter), Retry to the pseudo-turnback B checkpoint AFTER B was left."""

    def retry_after_departure(self):
        f = self.R.Flow(self, operational=True, order="complete_first").run(10)
        f.depart_b_only("close_then_go")
        f.after(3)
        before_retry = f.o.score
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        f.after(10)
        return f, before_retry

    def test_RB_3_layer_B_contract_B_departure_after_the_Retry_scores_no_operating_time(self):
        f, before_retry = self.retry_after_departure()
        o = f.o
        landed_score = o.score
        self.assertEqual(landed_score, o.save_data[1]["score"], "GUARD: the score of the B checkpoint is restored")
        f.depart_b_only("close_then_go")
        f.after(10)
        self.assertEqual(o.score, landed_score, "RED on the baseline: the B departure scores the operating time (+300)")

    def test_RB_4_layer_B_contract_the_untimed_B_holds_even_if_the_handled_mark_is_lost(self):
        f, _ = self.retry_after_departure()
        o = f.o
        landed_score = o.score
        o.has_scored_time_this_station = False               # layer A defeated on purpose: the contract alone must still give 0
        f.depart_b_only("close_then_go")
        f.after(10)
        self.assertEqual(o.score, landed_score, "RED on the baseline (and after a state-only fix): B is untimed by contract, whatever the handled mark says")

    def test_RB_5_the_Retry_landing_scores_no_stop_position_no_basic_braking_and_creates_no_arrival_checkpoint(self):
        f = self.R.Flow(self, operational=True, order="complete_first").run(10)
        f.depart_b_only("close_then_go")
        f.after(3)
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        landed_details = None
        f.after(10)
        o = f.o
        saved = o.save_data[1]
        self.assertEqual(o.score, saved["score"], "the restored score, nothing added by the landing")
        self.assertEqual(dict(o.score_details), dict(saved["score_details"]), "GUARD: stop position / basic braking of B are 0 times")
        self.assertEqual([(cp.get("station_index"), cp.get("origin", "-")) for cp in o.save_data], [(0, "-"), (2, "turnback")], "one pseudo-turnback B checkpoint, no arrival checkpoint of B")

    def test_RB_6_B_then_the_next_station_is_ordinary_scoring_after_the_Retry(self):
        f, _ = self.retry_after_departure()
        o = f.o
        f.depart_b_and_arrive_c()
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(f.fail_reasons(), [])
        self.assertGreater(o.score, o.save_data[1]["score"], "GUARD: C is scored (stop position / basic braking / its own operating time)")

    def test_RB_7_the_Retry_to_B_before_the_departure_scores_nothing_at_B(self):
        f = self.R.Flow(self, operational=True, order="complete_first").run(10)
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        f.after(10)
        o = f.o
        before = o.score
        f.depart_b_only("close_then_go")
        f.after(10)
        self.assertEqual(o.score, before, "GUARD (reference): without the earlier departure the mark path works today")


    def test_RB_9_after_a_Retry_to_B_following_the_departure_a_door_open_edge_at_B_scores_no_second_arrival(self):
        """The sibling of TBG-07 for the Retry: the door stations B (pairs 2 and 3 of C-01). The Retry lands at B; a door-open edge at B must not score the arrival of B (+500 stop position / basic braking / operating time)."""
        for operational in (True, False):
            with self.subTest(operational=operational):
                f = self.R.Flow(self, operational=operational, advance_arr=True, order="complete_first").run(10)
                f.depart_b_only("close_then_go")
                f.after(3)
                res = f.retry_to_b()
                self.assertTrue(res.accepted, res)
                f.after(10)
                o = f.o
                before, details = o.score, dict(o.score_details)
                f.scene.step(1, bve_door=1, bve_arr_idx=2, bve_arr_seq=o.bve_arr_seq + 1)
                f.scene.step(20)
                self.assertEqual(o.score, before, "no arrival score of B after the Retry landing")
                self.assertEqual(dict(o.score_details), details)
                self.assertEqual([cp.get("origin") for cp in o.save_data if cp.get("station_index") == 2], ["turnback"], "only the pseudo-turnback B checkpoint")

def legacy_theory(owner, start, end):
    """The theoretical score as the baseline 2387d17 computed it (main.py:1774-1802, every station after the start that is no pass station counts): the defect that Stage 2 removes, kept here as the reference formula."""
    n1 = n2 = n3 = 0
    for i in range(start, end + 1):
        st = owner.station_list[i]
        if not (i == start) and not st.get("is_pass", False):
            n1 += 1
            n2 += 1
        timed = False if i == start else owner.user_timing_overrides.get(i, st.get("is_timing", False))      # the baseline is_station_timing: the start, then the override, then the station data
        if timed:
            n3 += 1
    return n1 * 500, n2 * 500, n3 * 300


def theory_components(test, owner, start, end):
    """(stop, basic braking, operating time) of the theoretical score, each read through the REAL handler: the other two components are switched off (brake rule OFF / no timing station)."""
    saved_rules = [dict(r) for r in owner.brake_rules]
    saved_timing = [st.get("is_timing") for st in owner.station_list]
    try:
        for r in owner.brake_rules:
            r["apply"] = "OFF"
        for st in owner.station_list:
            st["is_timing"] = False
        stop = theory_of(owner, start, end)                                   # n1 * 500 only
        for r, old in zip(owner.brake_rules, saved_rules):
            r["apply"] = old["apply"]
        brake = theory_of(owner, start, end) - stop                           # n2 * 500
        for r in owner.brake_rules:
            r["apply"] = "OFF"
        for st, old in zip(owner.station_list, saved_timing):
            st["is_timing"] = old
        owner.user_timing_overrides.clear()
        time_score = theory_of(owner, start, end) - stop                      # n3 * 300
    finally:
        owner.brake_rules[:] = saved_rules
        for st, old in zip(owner.station_list, saved_timing):
            st["is_timing"] = old
    return stop, brake, time_score


class F_C01ShapeTheory(SnapshotBase):
    """Owner R1 / R3 on the C-01 shape (12 stations W X A1 B1 A2 B2 A3 B3 A4 B4 Y Z, four pairs): total AND the three components, the four B StationIndex taken from the RunPairSet."""

    def c01_scene(self):
        s = self.P.Scene(self, with_pairs=False)
        names = ["W", "X", "A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4", "Y", "Z"]
        sl = [self.P.station(n, 500.0 * i, raw_dep=self.P.T0 + 1000 * i, raw_arr=self.P.T0 + 1000 * i) for i, n in enumerate(names)]
        sl[-1]["is_terminal"] = True
        s.o.station_list = s.sl = sl
        ps, why = self.PC.decode_ptpair("PTPAIR:1:%s:12:4:2-3-0;4-5-0;6-7-0;8-9-0" % self.P.R.SCOPE_LIST_ID, 12)
        self.assertIsNone(why, why)
        s.machine.set_pairset(ps)
        return s

    def test_C01_1_the_defect_is_14300_and_the_contract_is_9100_difference_5200_by_component(self):
        s = self.c01_scene()
        o = s.o
        self.assertEqual(legacy_theory(o, 0, 11), (5500, 5500, 3300), "the baseline formula: 14300")
        stop, brake, time_score = theory_components(self, o, 0, 11)
        self.assertEqual((stop, brake, time_score), (3500, 3500, 2100), "RED on the baseline: it is (5500, 5500, 3300); contract: 7 scored stations")
        self.assertEqual(stop + brake + time_score, 9100)
        legacy = legacy_theory(o, 0, 11)
        self.assertEqual((legacy[0] - stop, legacy[1] - brake, legacy[2] - time_score), (2000, 2000, 1200), "4 pair B x (500 + 500 + 300) = 5200")
        self.assertEqual(sum(legacy) - 9100, 5200)
        self.assertEqual(theory_of(o, 0, 11), 9100)

    def test_C01_2_the_four_B_StationIndex_come_from_the_RunPairSet_and_the_settings_alike(self):
        s = self.c01_scene()
        o = s.o
        o.setting_start_idx, o.setting_end_idx = 0, 11
        self.assertEqual(self.S.turnback_b_indexes(o), frozenset({3, 5, 7, 9}), "before the button: the chosen section and the PairSet")
        self.press_start(s)
        snapshot = self.snap(s)
        self.assertEqual(snapshot.pairs, s.machine.fixed)
        self.assertEqual(self.S.turnback_b_indexes(o), frozenset(p.departure for p in s.machine.fixed), "during the Run: the RunPairSet")
        self.assertEqual(self.S.turnback_b_indexes(o), frozenset({3, 5, 7, 9}))

    def test_C01_3_A_stations_and_the_next_station_after_B_keep_their_theory_and_are_scored_stations(self):
        s = self.c01_scene()
        o = s.o
        stop, brake, time_score = theory_components(self, o, 0, 11)
        scored = [i for i in range(1, 12) if i not in (3, 5, 7, 9)]
        self.assertEqual(scored, [1, 2, 4, 6, 8, 10, 11], "X, A1..A4, Y, Z")
        self.assertEqual((stop, brake, time_score), (len(scored) * 500, len(scored) * 500, len(scored) * 300))
        # a section that starts AT A2: A2 is the start station (no arrival is scored there), so pair 2 is not crossed (qualifying_pair) and B2 stays an ordinary station; pairs 3 and 4 are crossed
        o.setting_start_idx, o.setting_end_idx = 4, 11
        self.assertEqual(self.S.turnback_b_indexes(o), frozenset({7, 9}))
        self.assertEqual(theory_of(o, 4, 11), 5 * 1300, "stations 5 (B2, ordinary here), 6, 8, 10, 11")

    def test_C01_4_nothing_but_the_PairSet_decides_names_doors_lamps_and_signals_are_no_input(self):
        s = self.c01_scene()
        o = s.o
        for st in s.sl:
            st["name"] = "B"                                        # every station is called B
        o.bve_door, o.bve_doordir, o.bve_is_pass = 1, 0, 1
        o.signalFlag = 1
        o.lamp = 1
        self.assertEqual(theory_of(o, 0, 11), 9100)
        s2 = self.P.Scene(self, with_pairs=False)
        self.assertEqual(theory_of(s2.o, 0, 4), 5200, "GUARD: without a PairSet every station counts, whatever it is called")


class G_ProspectiveEqualsTheButton(F_C01ShapeTheory):
    """The menus read the crossed pairs through the PURE turnback_crossed_pairs BEFORE the start button; the button fixes them through turnback_fix_section (byte-identical to the baseline, which a mutation harness of an earlier stage
    pins by text). The two must never part: every section of the scenes is run through the REAL button and compared."""

    def compare(self, s, start, end):
        o = s.o
        o.setting_start_idx, o.setting_end_idx = start, end
        before = self.S.turnback_b_indexes(o)                   # no Run yet: the chosen section (settings)
        self.press_start(s, expect=False)
        snapshot = self.snap(s)
        if snapshot is None or not o.is_scoring_mode:
            return None                                          # the start button refused this section
        return before, frozenset(p.departure for p in snapshot.pairs), self.S.turnback_b_indexes(o)

    def test_EQ_1_the_C01_scene_sections(self):
        compared = 0
        for start, end in ((0, 11), (0, -1), (1, 10), (2, 9), (0, 7), (4, 11), (0, 4), (6, 11), (0, 2)):
            with self.subTest(start=start, end=end):
                r = self.compare(self.c01_scene(), start, end)
                if r is None:
                    continue
                compared += 1
                self.assertEqual(r[0], r[1], "the prospective set equals what the button fixed")
                self.assertEqual(r[1], r[2], "and the running Run reads the snapshot")
        self.assertGreaterEqual(compared, 6, "a comparison that ran on nothing proves nothing")

    def test_EQ_2_the_five_station_scene_and_the_terminal_B_scene(self):
        compared = 0
        for terminal_b in (False, True):
            for start in (0, 1, 2):
                for end in (-1, 1, 2, 3, 4):
                    s = self.scene(terminal_b=terminal_b, start=start, end=end)
                    r = self.compare(s, start, end)
                    if r is None:
                        continue
                    compared += 1
                    self.assertEqual(r[0], r[1], (terminal_b, start, end))
                    self.assertEqual(r[1], r[2], (terminal_b, start, end))
        self.assertGreaterEqual(compared, 8)


    def test_EQ_3_the_dormant_terminal_B_correction_agrees_with_the_pure_helper(self):
        """The start button has a DORMANT defence (a terminal that is the B of a pair is resolved to its A and written back). With an abnormal input that reaches it, the pure helper must decide exactly as the button does."""
        s = self.scene(terminal_b=True, start=0, end=-1)
        o = s.o
        o.get_actual_terminal_idx = lambda: 2                       # abnormal input: the raw terminal B reaches the button
        prospective = self.S.turnback_crossed_pairs(o, 0, -1)
        self.S.turnback_fix_section(o)
        self.assertEqual(o.setting_end_idx, 1, "the existing dormant defence ran (the end became A)")
        self.assertEqual(tuple(prospective), tuple(s.machine.fixed), "the pure helper and the button agree")
        self.assertEqual(prospective, (), "the section ends at A: no pair is crossed")


class E_TimingScreenRender(SnapshotBase):
    """Owner R4 on the REAL screen: menu_ui.draw_menu (menu_state 8) is painted into an offscreen QImage; every text and every click zone is recorded. Scene: S0 (start) / A / B (pair B) / C / D."""

    def draw(self, s):
        from PyQt6.QtGui import QImage, QPainter
        import menu_ui
        o = s.o
        calls = []
        original = menu_ui.draw_text_with_outline

        def record(painter, text, *args, **kwargs):
            calls.append(text)
            return original(painter, text, *args, **kwargs)
        menu_ui.draw_text_with_outline = record
        self.addCleanup(setattr, menu_ui, "draw_text_with_outline", original)
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        o.menu_state = 8
        o.timing_scroll = getattr(o, "timing_scroll", 0)
        o.menu_click_zones = []
        try:
            menu_ui.draw_menu(o, painter, 1920)
        finally:
            painter.end()
            menu_ui.draw_text_with_outline = original
        # Stage UI-D3 (on purpose): the scoring page 1/3 is drawn behind the panel (dimmed): the texts of the TIMING PANEL are the ones after its title
        calls = calls[calls.index("=== 運転時分 設定 ==="):]
        return calls, list(o.menu_click_zones)

    @staticmethod
    def status_of(calls, name):
        i = calls.index(name)
        return calls[i + 1]

    @staticmethod
    def wide_zones(zones):
        """The row buttons (the wide box of a row that can be clicked) by list index: x0 == 410."""
        return sorted(z[4] for z in zones if len(z) == 6 and z[0] == 410.0)

    def test_UI_1_B_is_drawn_untimed_from_the_same_source_as_the_effective_timing(self):
        s = self.scene(start=0, end=4)
        o = s.o
        calls, zones = self.draw(s)
        for idx in o.get_timing_target_stas():
            name = s.sl[idx]["name"]
            self.assertEqual(self.status_of(calls, name), "採時" if o.is_station_timing(idx) else "非採時", "the screen reads is_station_timing for %s" % name)
        self.assertEqual(self.status_of(calls, "B"), "非採時", "RED on the baseline: B is drawn as a timing station")
        self.assertEqual(self.status_of(calls, "A"), "採時")
        self.assertEqual(self.status_of(calls, "C"), "採時")

    def test_UI_2_B_and_the_start_have_no_row_button_but_the_ordinary_stations_keep_theirs(self):
        s = self.scene(start=0, end=4)
        calls, zones = self.draw(s)
        self.assertEqual(self.wide_zones(zones), [1, 3, 4], "RED on the baseline: B (list index 2) has a row button there; the start (0) never has")

    def test_UI_3_selecting_B_never_makes_it_timed_whatever_the_route_of_the_click(self):
        s = self.scene(start=0, end=4)
        o = s.o
        targets = o.get_timing_target_stas()
        for _ in range(3):
            o.menu_state, o.timing_cursor = 8, targets.index(2)
            o.handle_menu_enter(False)                                   # the sink of the key AND of the click
        o.toggle_all_timing()
        o.user_timing_overrides[2] = True                                # a direct write by another route
        calls, zones = self.draw(s)
        self.assertEqual(self.status_of(calls, "B"), "非採時")
        self.assertFalse(o.is_station_timing(2))

    def test_UI_4_the_start_station_is_untimed_and_fixed_too(self):
        s = self.scene(start=0, end=4)
        o = s.o
        o.menu_state, o.timing_cursor = 8, 0
        o.handle_menu_enter(False)
        calls, zones = self.draw(s)
        self.assertEqual(self.status_of(calls, "S0"), "非採時")
        self.assertNotIn(0, o.user_timing_overrides)
        s2 = self.scene(start=2, end=4)                                    # B as the START: untimed and fixed (UNTIMED_SCORING_START)
        calls2, zones2 = self.draw(s2)
        self.assertEqual(self.status_of(calls2, "B"), "非採時")
        self.assertNotIn(0, self.wide_zones(zones2), "list index 0 = the start station B")

    def test_UI_5_an_ordinary_station_still_toggles_and_nothing_else_on_the_screen_changes(self):
        s = self.scene(start=0, end=4)
        o = s.o
        before, _ = self.draw(s)
        o.menu_state, o.timing_cursor = 8, o.get_timing_target_stas().index(3)
        o.handle_menu_enter(False)                                            # C: timing -> untimed
        after, _ = self.draw(s)
        self.assertEqual(self.status_of(after, "C"), "非採時")
        for name in ("S0", "A", "B", "D"):
            self.assertEqual(self.status_of(after, name), self.status_of(before, name), name + " is unchanged")
        o.handle_menu_enter(False)                                            # C: untimed -> timing again
        again, _ = self.draw(s)
        self.assertEqual(self.status_of(again, "C"), "採時")

    def test_UI_6_the_initial_setting_buttons_are_not_triggered_by_the_contract_untimed_B(self):
        s = self.scene(start=0, end=4)
        calls, _ = self.draw(s)
        self.assertNotIn("初期設定に戻す : A", calls, "RED on the baseline: B (default timing, now untimed) read as a user change")
        self.assertNotIn("変更可能な非採時駅を全て採時駅にする : A", calls, "Stage TB-H 5a (on purpose): the old text 始発駅以外を採時駅にする : A became the one label below; no changeable untimed station here")
        s_pos = self.scene(start=0, end=4)
        s_pos.sl[3]["is_timing"] = False                                       # an ordinary changeable station that is untimed by the data
        calls_pos, _ = self.draw(s_pos)
        self.assertIn("変更可能な非採時駅を全て採時駅にする : A", calls_pos, "Stage TB-H 5a: a POSITIVE assert (the label is drawn when a changeable untimed station exists); the old text is gone")
        o = s.o
        o.menu_state, o.timing_cursor = 8, o.get_timing_target_stas().index(1)
        o.handle_menu_enter(False)                                            # a real user change (A)
        calls2, _ = self.draw(s)
        self.assertIn("初期設定に戻す : A", calls2, "GUARD: a real user change still offers the reset")

    def test_UI_7_the_description_names_both_fixed_cases(self):
        with open(os.path.join(ROOT, "menu_ui.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("採点開始駅と、区間が跨ぐ疑似折り返しのB駅は非採時で固定", text)


class D_F5(SnapshotBase):
    """R6: F5 aborts the scoring and drops the Run: nothing of the old Run's pair B contract survives; a new Run fixes it again from its own section and RunPairSet."""

    def test_F5_1_RED_in_the_Run_B_is_untimed_before_the_reload(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        self.assertFalse(s.o.is_station_timing(2), "RED on the baseline: B is a timing station there")

    def test_F5_2_after_the_reload_the_old_Run_leaves_nothing_behind(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        o = s.o
        o.current_scenario_id += 1                                   # F5: a new world (ScenarioGeneration)
        s.step(3)                                                    # the product housekeeping / lifecycle guard run
        self.assertIsNone(self.S.active_scoring_section(o), "GUARD: the snapshot of the old generation is never used")
        self.assertIsNone(s.machine.fixed, "GUARD: the pairs of the old Run are dropped")
        o.setting_start_idx, o.setting_end_idx = 0, 1                # the menu of the new world: a section that does not cross the pair
        self.assertTrue(o.is_station_timing(2), "GUARD: no UNTIMED_TURNBACK_B is left behind; the settings are the source again")
        self.assertNotIn(2, o.user_timing_overrides)

    def test_F5_3_RED_a_new_Run_fixes_pair_B_again_from_its_own_section(self):
        s = self.scene(start=0, end=4)
        self.press_start(s)
        s.o.current_scenario_id += 1
        s.o.is_scoring_mode = False
        s.step(2)
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 4
        self.press_start(s)
        self.assertFalse(s.o.is_station_timing(2), "RED on the baseline (B is timed there); after the fix: fixed again by the new Run")
        self.assertTrue(s.o.is_station_timing(1))


if __name__ == "__main__":
    unittest.main()