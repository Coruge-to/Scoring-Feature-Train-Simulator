"""Stage TB-B: the A-side of the pseudo-turnback in the REAL scoring (update_physics_and_scoring / evaluate_arrival), driven in BVE time by tests/pt_scene.py.

Owner contract: the A arrival is scored ONCE and completely (stop position, basic braking, the A operating time when A is a timing station); the A has NO checkpoint (OD-PR-1 beta) while its score, its details and the
history stay; B gets ONE checkpoint of its own, after the Jump completed and B is established (created by scoring_logic.create_turnback_b_checkpoint; the caller is Stage TB-C / D).
CH-* are CHARACTERISATIONS: they pin what the product does today (GREEN on the current scoring), so that the new seam is proved to change nothing else.
ISOLATION: USERPROFILE / HOME point to an empty temporary folder. Without PyQt6 the scene tests are SKIPPED, never passed."""
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

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-pt-continuity-")
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
        raise AssertionError("the continuity module wrote into the redirected profile: %r" % (left,))


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pt-continuity"])
        import main
        import scoring_logic
        import station_identity
        import pt_scene
        cls.main, cls.S, cls.SI, cls.P = main, scoring_logic, station_identity, pt_scene

    def arrive(self, braking="plain", error_m=0.3, timing_diff_ms=None, **kw):
        """Arrive at A. timing_diff_ms: the BVE clock reads (scheduled arrival - timing_diff_ms) at the door-open edge, so that the operating-time diff is whole seconds."""
        s = self.P.Scene(self, drive=False, **kw)
        if timing_diff_ms is not None:
            # the arrival time of A is T0 + 90 000 ms; make NEXTTIME = that, and the clock read it minus the diff at the arrival
            s.o.bve_time_ms = self.P.T0 + 90000 - timing_diff_ms - 600
            s.o.bve_next_time = self.P.T0 + 90000
        s.approach(braking)
        s.stop_at(error_m)
        t = s.open_door()
        return s, t


# ==============================================================================================================================================
# A: no checkpoint, score kept, one operating-time score
# ==============================================================================================================================================
class A_ArrivalAtPairA(Base):
    def test_R15b_the_A_of_a_pair_has_no_checkpoint(self):
        s, t = self.arrive()
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0])
        self.assertEqual(s.machine.state, M.ARMED)
        for _ in range(500):
            s.tick(16)
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0], "nor later: the checkpoint of the A is never created")

    def test_CH_A1_a_station_that_is_not_a_pair_a_creates_its_checkpoint_as_before(self):
        s, t = self.arrive(with_pairs=False)
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0, 1])
        cp = s.o.save_data[-1]
        self.assertEqual((cp["stop_error"], cp["station_name"]), (self.P.A_MARK - s.o.bve_location, "A"))

    def test_R17b_the_arrival_score_and_the_details_of_A_are_kept(self):
        s, t = self.arrive("stepwise", 0.3)
        self.assertEqual(s.o.score_details["stop"], 350)
        self.assertEqual(s.o.score_details["base_brake"], 500)
        score, details = s.o.score, dict(s.o.score_details)
        for _ in range(400):
            s.tick(16)
        self.assertEqual((s.o.score, dict(s.o.score_details)), (score, details), "nothing is added or taken back after the arrival (no leak into the Jump wait)")

    def test_R17b_the_same_arrival_judged_again_changes_neither_the_score_nor_the_chain(self):
        s, t = self.arrive("stepwise", 0.3)
        score, details, key = s.o.score, dict(s.o.score_details), s.machine.key
        s.step(3, bve_door=0)
        s.step(1, bve_door=1)                                            # the door opens a second time on the same stop (door chatter)
        self.assertEqual(([c["station_index"] for c in s.o.save_data], s.machine.key, s.machine.state), ([0], key, M.ARMED))
        self.assertEqual((s.o.score, dict(s.o.score_details)), (score, details))

    def test_G_A1_the_operating_time_of_A_is_scored_once_at_the_arrival(self):
        s, t = self.arrive(timing_diff_ms=5000)                          # the train is 5 s early: |diff| <= 9 s -> +300
        self.assertEqual(s.o.score_details["time"], 300)
        self.assertTrue(s.o.has_scored_time_this_station)
        for _ in range(300):
            s.tick(16)
        self.assertEqual(s.o.score_details["time"], 300, "once")

    def test_CH_A3_without_a_pair_the_operating_time_of_a_middle_station_is_not_scored_at_the_arrival(self):
        s, t = self.arrive(timing_diff_ms=5000, with_pairs=False)
        self.assertEqual(s.o.score_details["time"], 0)
        self.assertFalse(s.o.has_scored_time_this_station)

    def test_G_A1_a_pair_a_that_is_not_a_timing_station_scores_no_time(self):
        s = self.P.Scene(self, drive=False)
        s.sl[1]["is_timing"] = False
        s.o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        s.o.bve_next_time = self.P.T0 + 90000
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()
        self.assertEqual(s.o.score_details["time"], 0)
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0])

    def test_G_A1_the_time_is_not_scored_again_when_the_target_moves_on_without_a_jump(self):
        """The departure reaction (CH-A4 for the pair A): the flag of the arrival keeps the departure from scoring the same operating time a second time."""
        s, t = self.arrive(timing_diff_ms=5000)
        self.assertEqual(s.o.score_details["time"], 300)
        s.step(3, bve_door=0)
        s.step(1, bve_next_loc=self.P.B_MARK, bve_tgt_idx=2, bve_speed=1.0, bve_location=self.P.A_MARK - 0.3 + 0.5)       # the target moves forward (no Jump in the way)
        s.step(5, bve_speed=3.0, bve_location=self.P.A_MARK + 5.0)
        self.assertEqual(s.o.score_details["time"], 300)

    def test_the_order_of_the_A_arrival_scoring_is_time_then_stop_then_basic_braking(self):
        s, t = self.arrive("stepwise", 0.0, timing_diff_ms=5000)
        self.assertEqual({k: v for k, v in s.o.score_details.items() if v}, {"time": 300, "stop": 500, "base_brake": 500, "bonus": 500, "init_brake": -100})


# ==============================================================================================================================================
# the use conditions as the PRODUCT applies them (the StationIndex and the PairSet only)
# ==============================================================================================================================================
class P_UseConditionsInTheProduct(Base):
    def arrive_with(self, **settings):
        s = self.P.Scene(self, drive=False)
        for k, v in settings.items():
            setattr(s.o, k, v)
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()
        return s

    def test_E07_an_arrival_that_is_a_jump_landing_never_starts_a_chain_and_creates_no_pair_a_state(self):
        for field in ("jump_lock", "is_official_jumping"):
            with self.subTest(field=field):
                s = self.P.Scene(self, drive=False)
                s.approach("plain")
                s.stop_at(0.3)
                setattr(s.o, field, True)
                s.open_door()
                self.assertEqual(s.machine.state, M.IDLE)
                self.assertEqual([p for p in s.o.popups if p["category"] == "疑似折り返し"], [])

    def test_PU3_PU6_evaluate_arrival_itself_refuses_a_jump_landing_or_an_outstanding_jump(self):
        """The tick path rejects a phantom door-open during a Jump upstream; the evaluation keeps its own guard (defence in depth), proved by calling it directly."""
        for field in ("jump_lock", "is_official_jumping"):
            with self.subTest(field=field):
                s = self.P.Scene(self, drive=False)
                s.approach("plain")
                s.stop_at(0.3)
                setattr(s.o, field, True)
                self.S.evaluate_arrival(s.o, s.o.bve_time_ms / 1000.0, self.P.A_MARK)
                self.assertEqual(s.machine.state, M.IDLE)

    def test_E26_the_end_station_equal_to_A_is_a_normal_end_station_arrival(self):
        s = self.arrive_with(setting_end_idx=1)
        self.assertEqual(s.machine.state, M.IDLE)
        self.assertTrue(s.o.is_scoring_finished, "the end station A finishes the scoring as always")

    def test_the_resolved_terminal_is_used_when_the_end_station_is_not_chosen(self):
        s = self.arrive_with(setting_end_idx=-1)
        self.assertEqual(s.machine.state, M.ARMED)

    def test_PU1_a_scoring_start_at_or_after_A_makes_A_a_normal_station(self):
        for start in (1, 2):
            with self.subTest(start=start):
                s = self.arrive_with(setting_start_idx=start)
                self.assertEqual(s.machine.state, M.IDLE)

    def test_PU3_an_explicit_end_station_equal_to_B_is_not_a_pair(self):
        s = self.arrive_with(setting_end_idx=2)
        self.assertEqual(s.machine.state, M.IDLE)

    def test_PU5_a_station_list_that_is_not_the_one_of_the_pair_set_starts_nothing(self):
        s = self.arrive_with(bve_list_id="DEADBEEF")
        self.assertEqual(s.machine.state, M.IDLE)

    def test_the_arrival_at_a_station_that_is_not_a_pair_station_starts_nothing(self):
        s = self.P.Scene(self, drive=False)
        s.sl[1], s.sl[3] = s.sl[3], s.sl[1]                                  # (the stations are looked up by index only: swap the data, keep the pair 1-2)
        s.o.bve_tgt_idx = 3
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()
        self.assertEqual(s.machine.state, M.IDLE)

    def test_E05_an_operational_stop_at_A_is_the_same_pair_arrival(self):
        """CHARACTERISATION (ledger E05, UNKNOWN whether an A can be an operational stop in the 15 reference scenarios): the product's operational-stop arrival (speed 0, door direction 0) at a pair A starts the chain
        and scores the A operating time once, like the door-open arrival."""
        s = self.P.Scene(self, drive=False)
        s.o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
        s.o.bve_next_time = self.P.T0 + 90000
        s.approach("plain")
        s.o.bve_doordir = 0
        s.o.is_approaching = True
        s.step(4, bve_speed=0.0, bve_location=self.P.A_MARK - 0.3, bve_brk_notch=8, bve_doordir=0)
        self.assertEqual(s.machine.state, M.ARMED)
        self.assertEqual(s.o.score_details["time"], 300)
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0])


# ==============================================================================================================================================
# CH-A8: the close-range anchor of the A arrival (the product keeps it; the Jump settlement of O1 writes the B one)
# ==============================================================================================================================================
class H_CloseRangeCharacterisation(Base):
    def test_CH_A8_the_arrival_of_a_pair_a_still_keeps_the_stop_position_as_the_close_range_anchor(self):
        s, t = self.arrive()
        self.assertAlmostEqual(s.o.prev_actual_stop_loc, self.P.A_MARK - 0.3, places=6)

    def test_CH_A8_a_pair_a_that_is_not_a_pair_keeps_it_too(self):
        s, t = self.arrive(with_pairs=False)
        self.assertAlmostEqual(s.o.prev_actual_stop_loc, self.P.A_MARK - 0.3, places=6)

    def test_O1_the_settlement_supplies_the_B_anchor_and_a_turnback_request_adds_no_anchor_code(self):
        import inspect
        src = inspect.getsource(self.S)
        names = ("turnback_machine_of", "turnback_pair_a_of", "turnback_arrival_begin", "turnback_arrival_scored", "turnback_display_update", "create_turnback_b_checkpoint")
        import ast
        tree = ast.parse(src)
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names):
            text = ast.get_source_segment(src, fn)
            self.assertNotIn("prev_actual_stop_loc", text, fn.name)
            self.assertNotIn("close_range", text, fn.name)


# ==============================================================================================================================================
# B: the checkpoint of B
# ==============================================================================================================================================
class B_CheckpointOfB(Base):
    def test_R16_R17_R32_one_checkpoint_of_B_in_the_shape_of_a_scoring_start(self):
        s, t = self.arrive("stepwise", 0.3, timing_diff_ms=5000)
        o = s.o
        o.bve_time_ms += 7000
        o.bve_tgt_idx, o.bve_next_loc, o.bve_location = 2, self.P.B_MARK, self.P.B_MARK            # B is established: the train stands at B, the target is B
        score, details = o.score, dict(o.score_details)
        self.assertTrue(self.S.create_turnback_b_checkpoint(o, 2))
        self.assertEqual(len(o.save_data), 2)
        cp = o.save_data[-1]
        self.assertEqual((cp["station_index"], cp["station_name"], cp["loc"], cp["target_loc"], cp["time_ms"], cp["stop_error"], cp["origin"]),
                         (2, "B", self.P.B_MARK, self.P.B_MARK, o.bve_time_ms, 0.0, "turnback"))
        self.assertEqual((cp["score"], cp["score_details"]), (score, details))
        self.assertIsNot(cp["score_details"], o.score_details, "a copy: later points do not change the checkpoint")
        keys_of_start = set(self.SI.checkpoint_fields(self.SI.start_snapshot(o.current_scenario_id, o.bve_list_id, o.station_list, 2)))
        self.assertTrue(keys_of_start <= set(cp), "the same identity fields as a scoring start")
        self.assertEqual(cp["role"], "arrived_station", "a retry accepts scoring_start only at the first place of the history (measured: start_snapshot gives role-mismatch)")

    def test_R32_a_second_call_never_makes_a_second_checkpoint(self):
        s, t = self.arrive()
        self.assertTrue(self.S.create_turnback_b_checkpoint(s.o, 2))
        self.assertFalse(self.S.create_turnback_b_checkpoint(s.o, 2))
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0, 2])

    def test_no_checkpoint_when_the_scoring_is_off_finished_or_the_identity_is_not_verified(self):
        s, t = self.arrive()
        o = s.o
        o.is_scoring_finished = True
        self.assertFalse(self.S.create_turnback_b_checkpoint(o, 2))
        o.is_scoring_finished = False
        o.is_scoring_mode = False
        self.assertFalse(self.S.create_turnback_b_checkpoint(o, 2))
        o.is_scoring_mode = True
        for bad in (-1, 99, None, True):
            self.assertFalse(self.S.create_turnback_b_checkpoint(o, bad), bad)
        o.bve_list_id = ""
        self.assertFalse(self.S.create_turnback_b_checkpoint(o, 2))
        self.assertEqual([c["station_index"] for c in o.save_data], [0])

    def test_the_checkpoint_of_B_is_a_valid_retry_target_and_A_is_not_in_the_history(self):
        s, t = self.arrive("stepwise", 0.3)
        o = s.o
        self.assertTrue(self.S.create_turnback_b_checkpoint(o, 2))
        idx = [c["station_index"] for c in o.save_data]
        self.assertEqual(idx, [0, 2])
        self.assertNotIn(1, idx, "CH-A7: the A is never a retry destination")
        result = self.SI.check_retry_checkpoint(o.save_data, 1, o.current_scenario_id, o.bve_list_id, o.station_list, False)
        self.assertTrue(result.accepted, result)
        self.assertEqual(result.selected_station_index, 2)

    def test_the_checkpoint_does_not_ask_the_position_of_a_station(self):
        import ast
        import inspect
        src = inspect.getsource(self.S)
        fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "create_turnback_b_checkpoint")
        names = {getattr(n.func, "id", getattr(n.func, "attr", None)) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        self.assertFalse(names & {"abs", "min", "max", "sorted", "enumerate", "next", "any", "all", "find", "index"}, names)
        self.assertEqual([n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp))], [])

# ==============================================================================================================================================
# TB-DOOR-R1 .. R8: the START of the chain is the A ARRIVAL JUDGEMENT of the existing evaluation (Owner OD-TB-14); the door state is used by NONE of
# the recognition of the pair, the start of the chain, the display, the request, its time or the fail-closed decision.
# ============================================================================================================================================
class D_DoorIndependence(Base):
    GUIDE = "疑似折り返し"

    def edge_arrival(self, **kw):
        s = self.P.Scene(self, drive=False, **kw)
        s.approach("plain")
        s.stop_at(0.3)
        t = s.open_door()
        return s, t

    def operational_arrival(self, door=0):
        """An arrival WITHOUT a door-open edge: the operational stop (speed 0, door direction 0) the existing evaluation already judges as an arrival (a train without passengers, a stop without doors)."""
        s = self.P.Scene(self, drive=False)
        s.approach("plain")
        s.o.bve_doordir = 0
        s.o.is_approaching = True
        seen_doors = set()
        for _ in range(4):
            s.step(1, bve_speed=0.0, bve_location=self.P.A_MARK - 0.3, bve_brk_notch=8, bve_doordir=0, bve_door=door)
            seen_doors.add(s.o.bve_door)
        self.assertEqual(seen_doors, {door})
        return s, s.machine.arrival_ms

    def guides(self, s):
        return [p for p in s.o.popups if p["category"] == self.GUIDE]

    def requests(self, s, t):
        out = []
        for off in (4999, 5000, 5016, 6000):
            if s.o.bve_time_ms < t + off:
                s.tick(advance_ms=t + off - s.o.bve_time_ms)
            out.append((off, [a[0] for a in s.machine.tick(t + off, s.o.current_scenario_id, True)]))
        return out

    def test_TB_DOOR_R1_arrival_with_the_door_open_chain_display_request(self):
        s, t = self.edge_arrival()
        self.assertEqual(s.machine.state, M.ARMED)
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.requests(s, t), [(4999, []), (5000, ["request_jump"]), (5016, []), (6000, [])])

    def test_TB_DOOR_R2_arrival_without_any_door_opening_chain_display_request(self):
        s, t = self.operational_arrival(door=0)
        self.assertEqual(s.machine.state, M.ARMED)
        self.assertEqual(s.o.bve_door, 0, "the door never opened")
        self.assertEqual(len(self.guides(s)), 1, "the guidance is shown")
        self.assertEqual(self.requests(s, t), [(4999, []), (5000, ["request_jump"]), (5016, []), (6000, [])])
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0], "and still no checkpoint of the A")

    def test_TB_DOOR_R3_no_arrival_judgement_no_chain_whatever_the_door_does(self):
        # (a) the door opens and closes while the train is far from the station
        s = self.P.Scene(self, drive=False)
        s.approach("plain")
        for door in (1, 0, 1, 0):
            s.step(2, bve_door=door, bve_speed=3.0, bve_location=self.P.A_MARK - 400.0)
        self.assertEqual(s.machine.state, M.IDLE)
        # (b) the train stands in the stopping range with the door closed and a door direction that is not an operational stop: no arrival is judged
        s = self.P.Scene(self, drive=False)
        s.approach("plain")
        s.stop_at(0.3)
        s.step(30, bve_door=0)
        self.assertEqual((s.machine.state, [p for p in s.o.popups if p["category"] == self.GUIDE]), (M.IDLE, []))
        # (c) a door-open edge that lands outside the stopping range is not an arrival either
        s = self.P.Scene(self, drive=False)
        s.approach("plain")
        s.step(3, bve_speed=0.0, bve_location=self.P.A_MARK - 100.0)
        s.step(2, bve_door=1)
        self.assertEqual(s.machine.state, M.IDLE)

    def test_TB_DOOR_R4_a_door_that_can_not_be_closed_changes_no_pair_recognition(self):
        s, t = self.edge_arrival()
        base = self.S.turnback_pair_a_of(s.o, 1)
        self.assertIsNotNone(base)
        for field, value in (("bve_door", 0), ("bve_door", 1), ("bve_doordir", 0), ("bve_doordir", 1), ("prev_door", 1), ("prev_doordir", 0), ("bve_door_close_time_ms", 0),
                             ("bve_door_close_time_ms", 4600), ("bve_door_close_time_ms", 10 ** 9), ("bve_door_close_time_ms", -1)):
            setattr(s.o, field, value)
            self.assertEqual(self.S.turnback_pair_a_of(s.o, 1), base, (field, value))
            self.assertIsNone(self.S.turnback_pair_a_of(s.o, 2), (field, value))

    def test_TB_DOOR_R5_the_signal_flag_changes_no_pair_recognition(self):
        s, t = self.edge_arrival()
        base = self.S.turnback_pair_a_of(s.o, 1)
        for field, value in (("bve_signal_limit", 0.0), ("bve_signal_limit", 120.0), ("bve_fwd_sig_limit", 0.0), ("bve_fwd_sig_limit", 999.0), ("bve_signal_limit", -1.0)):
            setattr(s.o, field, value)
            self.assertEqual(self.S.turnback_pair_a_of(s.o, 1), base, (field, value))
        for fn in (self.S.turnback_pair_a_of, self.S.turnback_arrival_begin, M.qualifying_pair):
            import inspect
            self.assertNotRegex(" ".join(inspect.signature(fn).parameters), r"door|signal|flag")

    def test_TB_DOOR_R6_the_door_state_alone_never_changes_the_jump_permission(self):
        results = []
        for door, doordir in ((0, 1), (1, 1), (1, 0), (0, 0)):
            s, t = self.edge_arrival()
            s.o.bve_door, s.o.bve_doordir = door, doordir
            s.tick(advance_ms=4999)
            before = s.machine.tick(t + 4999, s.o.current_scenario_id, True)
            s.tick(advance_ms=1)
            at = s.machine.tick(t + 5000, s.o.current_scenario_id, True)
            results.append((before, [a[0] for a in at]))
        self.assertEqual(results, [([], ["request_jump"])] * 4)

    def test_TB_DOOR_R7_an_operational_stop_arrival_is_a_normal_A_arrival(self):
        edge, t_edge = self.edge_arrival()
        op, t_op = self.operational_arrival()
        for s in (edge, op):
            m = s.machine
            self.assertEqual((m.state, m.pair, m.has_special, len(s.o.save_data), len(self.guides(s))), (M.ARMED, m.pairset.pairs[0], False, 1, 1))
        self.assertEqual(edge.machine.key[2:3], op.machine.key[2:3])
        self.assertTrue(op.o.has_scored_stop_this_station)

    def test_TB_DOOR_R8_the_presence_or_absence_of_a_door_open_edge_cancels_no_established_chain(self):
        # a chain that started WITHOUT an edge survives a later door-open edge and requests once
        s, t = self.operational_arrival()
        key = s.machine.key
        s.o.bve_doordir = 1
        s.step(2, bve_door=1)
        s.step(2, bve_door=0)
        s.step(2, bve_door=1)
        self.assertEqual((s.machine.state, s.machine.key), (M.ARMED, key))
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.requests(s, t), [(4999, []), (5000, ["request_jump"]), (5016, []), (6000, [])])
        # a chain that started WITH an edge survives the door closing, opening and closing again
        s, t = self.edge_arrival()
        key = s.machine.key
        for door in (0, 1, 0, 1, 0):
            s.step(5, bve_door=door)
        self.assertEqual((s.machine.state, s.machine.key), (M.ARMED, key))
        self.assertEqual(self.requests(s, t), [(4999, []), (5000, ["request_jump"]), (5016, []), (6000, [])])


# ==============================================================================================================================================
# OD-TB-18: the checkpoint of B (role arrived_station) is a real retry target; the O1 settlement supplies the anchor again after the retry
# ==============================================================================================================================================
class R_RetryFromB(Base):
    RID = None

    def settle_retry(self, s):
        o = s.o
        s.step(3)
        s.step(1, bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=self.P.B_MARK, bve_speed=0.0, bve_next_loc=self.P.B_MARK, bve_tgt_idx=2)       # the JUMP count of the telemetry
        import jump_wire
        exp = o.jump_expectation
        text, why = jump_wire.format_completion_v2(exp.command, exp.station_index, exp.location, exp.time_ms, 1, tuple(exp.scope))
        self.assertIsNone(why)
        o._note_jump_complete(text)
        o._settle_jump_complete()
        self.assertFalse(o.is_official_jumping, "the retry Jump settled")

    def test_OD_TB_18_the_checkpoint_of_B_is_retried_with_the_O1_anchor_and_no_role_mismatch(self):
        s, t = self.arrive("stepwise", 0.3, timing_diff_ms=5000)
        o = s.o
        o.bve_time_ms += 9000
        self.assertTrue(self.S.create_turnback_b_checkpoint(o, 2))
        history = [dict(c) for c in o.save_data]
        score, details = o.score, dict(o.score_details)
        self.assertEqual([c["station_index"] for c in history], [0, 2])
        result = self.main.execute_retry(o, 1, False)
        self.assertTrue(result.accepted, result)
        self.assertNotEqual(result.reason, "role-mismatch")
        self.assertEqual(result.selected_station_index, 2)
        self.settle_retry(s)
        self.assertEqual([c["station_index"] for c in o.save_data], [0, 2], "history kept, no second checkpoint of B, none of A")
        self.assertEqual((o.score, dict(o.score_details)), (score, details), "the score of the checkpoint")
        self.assertEqual(o.prev_actual_stop_loc, self.P.B_MARK, "the O1 settlement supplied the anchor of THIS landing again")
        self.assertTrue(o.jump_lock)

    def test_OD_TB_18_no_checkpoint_of_the_A_ever_and_the_B_one_is_made_once(self):
        s, t = self.arrive()
        o = s.o
        self.assertTrue(self.S.create_turnback_b_checkpoint(o, 2))
        self.assertFalse(self.S.create_turnback_b_checkpoint(o, 2))
        self.assertEqual([c["station_index"] for c in o.save_data if c["station_index"] == 1], [])
        self.assertEqual([c["role"] for c in o.save_data], ["scoring_start", "arrived_station"])


# ==============================================================================================================================================
# OD-TB-19: turnback_machine is generation state of the Overlay (no singleton, no new owner, no resource)
# ============================================================================================================================================
class M_Ownership(Base):
    def test_OD_TB_19_the_machine_is_dropped_with_the_generation_and_rebuilt_empty(self):
        s = self.P.Scene(self, drive=False)
        old = self.S.turnback_machine_of(s.o)
        self.assertIsNotNone(old.pairset)
        s.o.reset_generation_state()
        self.assertNotIn("turnback_machine", s.o.__dict__)
        new = self.S.turnback_machine_of(s.o)
        self.assertIsNot(new, old)
        self.assertEqual((new.pairset, new.state, new.issued), (None, M.IDLE, set()))

    def test_OD_TB_19_two_overlays_never_share_a_machine_and_no_module_holds_one(self):
        import inspect
        s = self.P.Scene(self, drive=False)
        machine = self.S.turnback_machine_of(s.o)
        for module in (self.S, M, self.main):
            held = [name for name, value in vars(module).items() if isinstance(value, M.TurnbackMachine)]
            self.assertEqual(held, [], module.__name__)
        self.assertIs(self.S.turnback_machine_of(s.o), machine, "one machine per Overlay, created on first use")
        self.assertFalse(hasattr(M.TurnbackMachine, "close") or hasattr(M.TurnbackMachine, "dispose") or hasattr(M.TurnbackMachine, "__del__"), "nothing to shut down: a pure object")
        import managed_input
        self.assertIn("turnback_machine", managed_input.GENERATION_DROP)
        self.assertNotIn("turnback_machine", managed_input.KEPT_ACROSS_GENERATIONS)
        self.assertNotIn("turnback_machine", managed_input.generation_defaults())

    def test_OD_TB_19_the_scoring_session_off_leaves_no_request_behind(self):
        s, t = self.arrive()
        import managed_input
        managed_input.discard_scoring_session(s.o)
        self.assertFalse(s.o.is_scoring_mode)
        self.assertEqual(s.machine.tick(t + 5000, s.o.current_scenario_id, bool(s.o.is_scoring_mode)), [("discard_pending", "scoring-ended")])

# ==============================================================================================================================================
# TB-SELECT (product side) - Owner contract 2026-10-31. The pair A can not START a scoring (a start Jump that lands at A is no arrival, so no chain would begin) and can END one (the section
# does not cross A -> B); the pair B can START one (the ordinary logic, no chain) and can not END one (the train is placed there by the Jump, it never arrives by driving). The candidate lists are
# generated WITHOUT the excluded station (Stage TB-D); here: the existing generation is measured (what TB-D changes and what it must keep) and the sections that do not cross A -> B are proved to score as ever.
# ============================================================================================================================================
class TB_SELECT_Existing(Base):
    def candidates(self, s, target_x):
        o = s.o
        o.is_scoring_mode = False
        o.dropdown_active = False
        o.menu_state, o.menu_cursor, o.menu_cursor_x = 5, 0, target_x
        o.handle_menu_enter(False)
        return [opt["idx"] for opt in o.dropdown_options]

    def scene_with(self, pairset_text):
        s = self.P.Scene(self, drive=False, with_pairs=False)
        if pairset_text is not None:
            import pseudo_turnback_contract as PC
            ps, why = PC.decode_ptpair(pairset_text, len(s.sl))
            self.assertIsNone(why)
            self.S.turnback_machine_of(s.o).set_pairset(ps)
        return s

    def test_TB_SELECT_R5_the_existing_terminal_contract_decides_the_station_after_which_nothing_follows(self):
        """B is the LAST station here (a final pair): it is not a start candidate - by the EXISTING rule (a start must be before the end), identically with and without a PairSet."""
        for text in (None, "PTPAIR:1:A1B2C3D4:5:1:3-4-1"):
            s = self.scene_with(text)
            starts = self.candidates(s, 0)
            self.assertNotIn(4, starts, "the terminal station is never a start (existing contract)")
            self.assertIn(0, starts)

    def test_TB_SELECT_R8_the_candidates_of_the_ordinary_stations_are_unchanged(self):
        without = self.scene_with(None)
        with_pairs = self.scene_with("PTPAIR:1:A1B2C3D4:5:1:1-2-0")
        for x in (0, 1):
            a, b = self.candidates(without, x), self.candidates(with_pairs, x)
            ordinary = (0, 3, 4)
            self.assertEqual([i for i in a if i in ordinary], [i for i in b if i in ordinary], x)

    def test_TB_SELECT_R9_a_section_that_ends_at_A_scores_as_ever(self):
        s = self.P.Scene(self, drive=False)
        s.o.setting_start_idx, s.o.setting_end_idx = 0, 1
        s.approach("stepwise")
        s.stop_at(0.0)
        t = s.open_door()
        self.assertTrue(s.o.is_scoring_finished, "the end-station arrival finishes the scoring")
        self.assertEqual(s.machine.state, M.IDLE)
        self.assertEqual([p for p in s.o.popups if p["category"] == "疑似折り返し"], [])
        self.assertEqual(s.machine.tick(t + 5000, s.o.current_scenario_id, False), [], "no Jump, no chain")

    def test_TB_SELECT_R10_a_section_that_starts_at_B_scores_as_ever(self):
        s = self.P.Scene(self, drive=False)
        s.sl[1], s.sl[3] = s.sl[3], s.sl[1]                     # (the data of C stands at index 1 and the data of A at index 3: the arrival below is the one at index 3)
        s.o.setting_start_idx, s.o.setting_end_idx = 2, 3
        s.o.bve_tgt_idx = 3
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()
        self.assertTrue(s.o.is_scoring_finished)
        self.assertEqual(s.machine.state, M.IDLE)
        self.assertEqual([p for p in s.o.popups if p["category"] == "疑似折り返し"], [])
        # and the pair is not crossed from B: an arrival at the station that would be A (index 1) starts no chain either
        s2 = self.P.Scene(self, drive=False)
        s2.o.setting_start_idx = 2
        s2.approach("plain")
        s2.stop_at(0.3)
        s2.open_door()
        self.assertEqual(s2.machine.state, M.IDLE)


# ==============================================================================================================================================
# TB-SAVE-R1 .. R12 (Owner contract 2026-10-31): NO checkpoint at the A, the score and the history stay; ONE checkpoint of B (role arrived_station) after the Jump succeeded and B is established,
# a valid retry target that restores B and supplies the O1 anchor again. (R10 / R11 - the mutations that create an A checkpoint / create no B checkpoint - are in the mutation run, MB09 / MD10.)
# ============================================================================================================================================
class TB_SAVE(Base):
    settle_retry = R_RetryFromB.settle_retry

    def indexes(self, s):
        return [c["station_index"] for c in s.o.save_data]

    def test_TB_SAVE_R1_no_checkpoint_of_the_A_at_the_arrival(self):
        s, t = self.arrive("stepwise", 0.3)
        self.assertEqual([i for i in self.indexes(s) if i == 1], [])
        self.assertEqual(self.indexes(s), [0])

    def test_TB_SAVE_R2_the_score_is_kept(self):
        s, t = self.arrive("stepwise", 0.0, timing_diff_ms=5000)
        score, details = s.o.score, dict(s.o.score_details)
        self.assertGreater(score, 0)
        for _ in range(500):
            s.tick(16)
        self.assertEqual((s.o.score, dict(s.o.score_details)), (score, details))

    def test_TB_SAVE_R3_the_history_is_kept(self):
        s = self.P.Scene(self, drive=False)
        before = [dict(c) for c in s.o.save_data]
        s.approach("plain")
        s.stop_at(0.3)
        s.open_door()
        for _ in range(500):
            s.tick(16)
        self.assertEqual(s.o.save_data, before)

    def test_TB_SAVE_R4_no_checkpoint_of_B_before_B_is_established(self):
        s, t = self.arrive("plain", 0.3)
        for off in (1000, 3000, 5000, 7000):
            s.tick(advance_ms=t + off - s.o.bve_time_ms)
            s.machine.tick(t + off, s.o.current_scenario_id, True)
        self.assertEqual(s.machine.state, M.REQUESTED)
        self.assertEqual([i for i in self.indexes(s) if i == 2], [], "the request alone creates nothing; the checkpoint is made only by create_turnback_b_checkpoint after B is established")

    def test_TB_SAVE_R5_one_checkpoint_of_B_once_B_is_established(self):
        s, t = self.arrive("plain", 0.3)
        o = s.o
        o.bve_tgt_idx, o.bve_next_loc, o.bve_location = 2, self.P.B_MARK, self.P.B_MARK
        self.assertTrue(self.S.create_turnback_b_checkpoint(o, 2))
        self.assertEqual(self.indexes(s).count(2), 1)

    def test_TB_SAVE_R6_the_role_is_arrived_station(self):
        s, t = self.arrive()
        self.S.create_turnback_b_checkpoint(s.o, 2)
        self.assertEqual(s.o.save_data[-1]["role"], "arrived_station")

    def test_TB_SAVE_R7_R8_R9_the_B_checkpoint_is_retried_restores_B_and_supplies_the_anchor(self):
        s, t = self.arrive("stepwise", 0.3)
        o = s.o
        self.S.create_turnback_b_checkpoint(o, 2)
        result = self.main.execute_retry(o, 1, False)
        self.assertTrue(result.accepted, result)                              # R7
        self.assertEqual(result.selected_station_index, 2)                    # R8: the request names StationIndex B
        self.settle_retry(s)
        self.assertEqual(o.expected_target_loc, self.P.B_MARK)               # R8: B is where the Jump landed
        self.assertEqual(o.prev_actual_stop_loc, self.P.B_MARK)              # R9: the O1 anchor of this landing

    def test_TB_SAVE_R12_no_duplicate_checkpoint_of_B(self):
        s, t = self.arrive()
        for _ in range(5):
            self.S.create_turnback_b_checkpoint(s.o, 2)
        self.assertEqual(self.indexes(s).count(2), 1)

# ==============================================================================================================================================
# TB-SAVE-R13 .. R18 (Owner supplement 2026-10-31): the A and the B are ONE stop event with two roles. The checkpoint of B is made from the LATEST state at the moment B is established -
# the score, the details, the history, the time, the position and the target as they are after the Jump landed - and NEVER from a snapshot frozen at the A arrival. A penalty (the roll) or any
# change between the A arrival and the landing at B is in the checkpoint; a retry restores that latest state, not the value of the A arrival. (R16 - the mutation that stores the old A snapshot - is in the mutation run.)
# ============================================================================================================================================
class TB_SAVE_Latest(Base):
    settle_retry = R_RetryFromB.settle_retry

    def after_a(self):
        s, t = self.arrive("stepwise", 0.3, timing_diff_ms=5000)
        return s, t, s.o.score, dict(s.o.score_details)

    def penalty(self, s, points=-100):
        self.S.add_score_popup(s.o, points, "転動 %d" % points, None, "neg", "転動", s.o.bve_time_ms / 1000.0)

    def land_at_b(self, s, extra_ms=7000, error_m=0.4, target_offset=0.0):
        """B is established: the train stands where the Jump put it (0.4 m beyond the mark), the target is B, the clock is later than the A arrival."""
        o = s.o
        o.bve_time_ms += extra_ms
        o.bve_tgt_idx, o.bve_next_loc, o.bve_location, o.bve_speed = 2, self.P.B_MARK + target_offset, self.P.B_MARK + error_m, 0.0

    def test_TB_SAVE_R13_the_score_of_the_checkpoint_is_the_score_at_the_landing_not_the_score_at_the_A_arrival(self):
        s, t, score_a, _details = self.after_a()
        self.penalty(s)
        self.assertNotEqual(s.o.score, score_a, "the fixture: the two scores differ")
        score_b = s.o.score
        self.land_at_b(s)
        self.assertTrue(self.S.create_turnback_b_checkpoint(s.o, 2))
        self.assertEqual(s.o.save_data[-1]["score"], score_b)
        self.assertNotEqual(s.o.save_data[-1]["score"], score_a)

    def test_TB_SAVE_R14_a_roll_penalty_between_the_A_arrival_and_the_Jump_is_in_the_checkpoint(self):
        s, t, score_a, details_a = self.after_a()
        self.penalty(s, -100)
        self.assertEqual(s.o.score, score_a - 100)
        self.assertEqual(s.o.score_details["roll"], details_a["roll"] - 100)
        self.land_at_b(s)
        self.S.create_turnback_b_checkpoint(s.o, 2)
        cp = s.o.save_data[-1]
        self.assertEqual((cp["score"], cp["score_details"]["roll"]), (score_a - 100, details_a["roll"] - 100))
        self.assertEqual(cp["score_details"], s.o.score_details)

    def test_TB_SAVE_R15_a_change_of_the_history_between_the_A_arrival_and_the_landing_is_in_the_result(self):
        s, t, _score, _details = self.after_a()
        marker = dict(s.o.save_data[0], time_ms=s.o.save_data[0]["time_ms"] + 1, score=-7)
        s.o.save_data = s.o.save_data + [marker]                       # the history is a NEW list after the A arrival (as a retry cut makes it)
        self.land_at_b(s)
        self.S.create_turnback_b_checkpoint(s.o, 2)
        self.assertEqual([c["station_index"] for c in s.o.save_data], [0, 0, 2])
        self.assertIs(s.o.save_data[-2], marker, "the latest history, not the one of the A arrival")

    def test_TB_SAVE_R17_station_position_time_and_target_are_the_state_after_the_landing(self):
        s, t, _score, _details = self.after_a()
        self.land_at_b(s, extra_ms=7000, error_m=0.4, target_offset=0.2)       # (the established target differs from the list position, so a list-position target is visible)
        o = s.o
        self.S.create_turnback_b_checkpoint(o, 2)
        cp = o.save_data[-1]
        self.assertEqual((cp["station_index"], cp["station_name"], cp["role"]), (2, "B", "arrived_station"))
        self.assertAlmostEqual(cp["loc"], self.P.B_MARK + 0.4, places=6, msg="the actual landing, not the list position")
        self.assertEqual(cp["time_ms"], o.bve_time_ms)
        self.assertGreater(cp["time_ms"], t + 5000, "the time after the landing, not the one of the A arrival")
        self.assertEqual(cp["target_loc"], o.bve_next_loc)
        self.assertEqual(cp["stop_error"], 0.0)

    def test_TB_SAVE_R18_a_retry_restores_the_latest_score_of_the_checkpoint_not_the_A_arrival_value(self):
        s, t, score_a, details_a = self.after_a()
        o = s.o
        self.penalty(s, -100)
        self.land_at_b(s)
        self.S.create_turnback_b_checkpoint(o, 2)
        score_b, details_b = o.score, dict(o.score_details)
        self.assertNotEqual(score_b, score_a)
        self.penalty(s, -300)                                           # later, after B: the score moves on
        self.assertNotEqual(o.score, score_b)
        result = self.main.execute_retry(o, 1, False)
        self.assertTrue(result.accepted, result)
        self.assertEqual((o.score, dict(o.score_details)), (score_b, details_b), "restored at the request of the retry")
        self.settle_retry(s)
        self.assertEqual((o.score, dict(o.score_details)), (score_b, details_b))
        self.assertNotEqual(o.score, score_a)

if __name__ == "__main__":
    unittest.main()
