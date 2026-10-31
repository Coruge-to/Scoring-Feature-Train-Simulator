"""Stage TB-C, slice C3 - what happens after the pseudo-turnback Jump: the completion (the end word of the transaction, never the fall of is_official_jumping), the establishment of B, the BVE-time monitor
(OD-TB-28: first B-side time after the Jump, positive advances only, 1.0 s, no wall clock), the O1 anchor convergence for START / Retry / turnback in the early and the late target order (OD-TB-29),
the B mark and the B checkpoint, and the diagnostics-only failure (OD-TB-30). Drives the REAL product through the offscreen rig."""
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
FAIL_REASON = "pseudo-turnback-b-state-invariant-failed"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-pt-tbc-completion-")
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
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pt-tbc-completion"])
        import main
        import scoring_logic
        import jump_transaction
        import jump_wire
        import station_identity
        import pt_scene
        cls.main, cls.S, cls.JT, cls.JW, cls.SI, cls.P = main, scoring_logic, jump_transaction, jump_wire, station_identity, pt_scene

    def scene(self):
        s = self.P.Scene(self)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + 500.0
        self.events = []
        o._emit_input_event = lambda event, **f: self.events.append((event, f))
        self.menu_toggles = []
        o.toggle_menu = lambda adv: self.menu_toggles.append(adv)
        return s

    def to_completion(self, s, late_target=True):
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.jump_tick(late_target)
        s.complete()
        s.tick(16)                  # the first scoring tick after the completion: the driver reads the end word and takes the first B-side BVE time
        return s.o

    def b_checkpoints(self, o):
        return [c for c in o.save_data if c.get("origin") == "turnback"]

    def assert_stopped_on_the_safe_side(self, s, reason):
        o = s.o
        self.assertEqual(self.b_checkpoints(o), [], "no B checkpoint")
        self.assertFalse(o.has_scored_time_this_station, "no B mark")
        self.assertFalse(o.is_scoring_mode, "the scoring stops")
        self.assertIsNone(o.jump_expectation, "no outstanding")
        self.assertEqual([p for p in o.popups if p.get("category") == "警告"], [], "no warning popup")
        self.assertIn(reason, [f["reason"] for e, f in self.events if e == "turnback-fail"])
        self.assertFalse(self.S.official_jump_f1_hold(o), "the F1 hold is released with the stop")
        self.assertEqual(s.machine.state, M.IDLE)
        self.assertFalse(s.machine.awaiting_b)


class A_TheBStateMonitor(Base):
    def test_the_normal_case_establishes_B_before_the_monitor_matters(self):
        for late_target in (False, True):
            with self.subTest(late_target=late_target):
                s = self.scene()
                o = self.to_completion(s, late_target)
                if late_target:
                    self.assertTrue(s.machine.awaiting_b)
                    self.assertEqual(self.b_checkpoints(o), [])
                    self.assertFalse(o.has_scored_time_this_station)
                    s.target_to_b()
                self.assertEqual(len(self.b_checkpoints(o)), 1)
                self.assertTrue(o.has_scored_time_this_station)
                self.assertEqual(s.machine.state, M.IDLE)
                self.assertEqual([f for e, f in self.events if e == "turnback-fail"], [])

    def test_the_reference_is_the_first_B_side_time_and_the_jump_difference_is_not_counted(self):
        for delta_s in (-3600, 0, 3600):                       # the Jump moves the BVE time by hours either way
            with self.subTest(delta_s=delta_s):
                s = self.scene()
                s.sl[2]["raw_dep"] = self.P.T0 + 90000 + 15000 + delta_s * 1000
                o = self.to_completion(s, late_target=True)
                self.assertTrue(s.machine.awaiting_b)
                s.tick(16)
                self.assertLess(s.machine.b_watch["acc"], 100, "only the advance after the first B-side time counts")
                self.assertTrue(o.is_scoring_mode)

    def test_a_Pause_never_advances_the_monitor_and_never_stops_the_scoring(self):
        s = self.scene()
        o = self.to_completion(s, late_target=True)
        for _ in range(900):                                    # 90 s of the wall clock, BVE time frozen
            s.rig.advance(0.1)
            s.tick(advance_ms=0)
            o._poll_jump_client()
        self.assertTrue(o.is_scoring_mode)
        self.assertTrue(s.machine.awaiting_b)
        self.assertLessEqual(s.machine.b_watch["acc"], 16)
        self.assertTrue(self.S.official_jump_f1_hold(o), "F1 stays ignored while B is being established")
        s.target_to_b()
        self.assertEqual(len(self.b_checkpoints(o)), 1)

    def test_less_than_1_second_of_BVE_time_without_B_still_waits_and_B_then_establishes(self):
        s = self.scene()
        o = self.to_completion(s, late_target=True)
        s.tick(advance_ms=400)
        s.tick(advance_ms=500)
        self.assertTrue(o.is_scoring_mode, "0.9 s: still waiting")
        s.target_to_b()
        self.assertEqual(len(self.b_checkpoints(o)), 1)

    def test_1_second_of_positive_BVE_time_without_B_is_a_product_failure(self):
        s = self.scene()
        o = self.to_completion(s, late_target=True)
        history = len(o.save_data)
        s.tick(advance_ms=500)
        s.tick(advance_ms=500)
        self.assert_stopped_on_the_safe_side(s, FAIL_REASON)
        self.assertEqual(len(o.save_data), history)
        sent = []
        o.send_jump_command = lambda cmd: sent.append(cmd)
        for _ in range(200):
            s.tick(16)
        self.assertEqual(sent, [], "no automatic resend")
        self.assertEqual(len([e for e, f in self.events if e == "turnback-fail"]), 1)

    def test_zero_and_negative_differences_add_nothing_and_only_positive_ones_do(self):
        machine = M.TurnbackMachine()
        machine.start_b_watch()
        self.assertEqual(machine.b_watch_observe(1000000), 0)
        self.assertEqual(machine.b_watch_observe(1000000), 0, "0 difference")
        self.assertEqual(machine.b_watch_observe(999000), 0, "negative difference")
        self.assertEqual(machine.b_watch_observe(999400), 400, "positive, counted from the new reference")
        self.assertEqual(machine.b_watch_observe(999400), 400)
        self.assertFalse(machine.b_watch_exceeded())
        self.assertEqual(machine.b_watch_observe(1000000), 1000)
        self.assertTrue(machine.b_watch_exceeded())

    def test_the_monitor_does_not_read_any_clock(self):
        import ast
        import inspect
        for fn in (self.S.turnback_establish_b, M.TurnbackMachine.b_watch_observe, M.TurnbackMachine.b_watch_exceeded):
            tree = ast.parse(inspect.getsource(fn).replace("\r", "").lstrip() if False else __import__("textwrap").dedent(inspect.getsource(fn)))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            self.assertFalse(names & {"time", "monotonic", "perf_counter", "datetime", "sleep"}, fn)

    def test_a_generation_change_drops_the_monitor_and_the_chain(self):
        s = self.scene()
        o = self.to_completion(s, late_target=True)
        o.reset_generation_state()
        self.assertNotIn("turnback_machine", o.__dict__)

    def test_the_B_target_must_be_B_not_any_other_target(self):
        s = self.scene()
        o = self.to_completion(s, late_target=True)
        s.step(1, bve_next_loc=s.sl[3]["location"], bve_tgt_idx=3)
        self.assertEqual(self.b_checkpoints(o), [], "a target that is not B does not establish B")


class B_FailuresAreNeverASuccess(Base):
    def test_a_completion_that_does_not_prove_the_request_ends_the_chain_without_a_mark_or_a_checkpoint(self):
        for name, over in (("selected index", {"idx": 3}), ("scope(list id)", {"scope": (7, "DEADBEEF", 5)}), ("scope(scenario)", {"scope": (99, "A1B2C3D4", 5)})):
            with self.subTest(name=name):
                s = self.scene()
                t_a = s.arrive_a()
                s.run_to_request(t_a)
                s.jump_tick(late_target=True)
                s.complete(**over)
                s.tick(16)
                self.assertEqual(self.b_checkpoints(s.o), [])
                self.assertFalse(s.o.has_scored_time_this_station)
                self.assertFalse(s.o.is_scoring_mode)
                self.assertEqual(s.machine.state, M.IDLE)
                self.assertFalse(s.machine.awaiting_b)
                self.assertEqual([p for p in s.o.popups if p.get("category") == "警告"], [])

    def test_a_lost_completion_ends_by_the_existing_timeout_without_a_checkpoint(self):
        s = self.scene()
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.rig.advance(11.0)
        s.o._poll_jump_client()
        s.tick(16)
        self.assertEqual(self.b_checkpoints(s.o), [])
        self.assertFalse(s.o.is_scoring_mode)
        self.assertFalse(self.S.official_jump_f1_hold(s.o))

    def test_the_fall_of_is_official_jumping_alone_is_not_a_success(self):
        s = self.scene()
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.o.is_official_jumping = False                      # something dropped the flag; the transaction has no end word
        s.jump_tick(late_target=True)
        s.tick(16)
        self.assertEqual(self.b_checkpoints(s.o), [])
        self.assertFalse(s.machine.awaiting_b)

    def test_a_failure_end_word_is_not_a_success_word(self):
        ok = (self.JT.SETTLE_OK, self.JT.SETTLE_OK_PLAIN)
        for word in self.JT.SETTLE_WORDS:
            if word in ok:
                continue
            s = self.scene()
            o = s.o
            t_a = s.arrive_a()
            s.run_to_request(t_a)
            s.o._finish_jump_transaction(word, 2, s.sl[2]["location"])
            s.tick(16)
            self.assertEqual(self.b_checkpoints(o), [], word)
            self.assertFalse(s.machine.awaiting_b, word)

    def test_a_B_with_an_invalid_landing_is_a_product_failure(self):
        s = self.scene()
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.o._finish_jump_transaction(self.JT.SETTLE_OK, 2, float("nan"))
        s.tick(16)
        self.assert_stopped_on_the_safe_side(s, FAIL_REASON)


class C_TheAnchorConverges(Base):
    """OD-TB-29: START-at-B, Retry-to-B and the pseudo-turnback B end in the same state in the early and in the late target order: StationIndex B, B target, the anchor = the actual landing, nothing outstanding."""
    def landing(self, s, purpose, late):
        o = s.o
        if purpose == "turnback":
            t_a = s.arrive_a()
            s.run_to_request(t_a)
        elif purpose == "start":
            s.arrive_a(start=2)
            s.auto_fix = False
            o.is_scoring_mode = False
            o.menu_state, o.menu_cursor = 10, 1
            o.scoring_start_gate = None
            o.was_advancing_before_menu = False
            self.P.R.bind_identity(o, arr_idx=1, tgt_idx=2)
            o.handle_menu_enter(False)
            self.assertIsNotNone(o.jump_expectation)
        else:                                                                   # retry to the B checkpoint of a finished turnback
            t_a = s.arrive_a()
            s.run_to_request(t_a)
            s.jump_tick()
            s.complete()
            o.bve_arr_idx = 2
            s.step(10)
            self.assertTrue(self.main.execute_retry(o, len(o.save_data) - 1, False).accepted)
        s.jump_tick(late_target=late)
        s.complete()
        if late:
            s.target_to_b()
        o.bve_arr_idx = 2
        s.step(10)

    def final(self, o):
        return (o.bve_tgt_idx, o.bve_next_loc, o.prev_actual_stop_loc, o.jump_expectation is not None, o.is_official_jumping, o.retry_pending is not None)

    def test_START_Retry_and_turnback_end_in_the_same_final_state_in_both_orders(self):
        finals = {}
        for purpose in ("start", "retry", "turnback"):
            for late in (False, True):
                with self.subTest(purpose=purpose, late=late):
                    s = self.scene()
                    self.landing(s, purpose, late)
                    f = self.final(s.o)
                    finals[(purpose, late)] = f
                    self.assertEqual(f, (2, s.sl[2]["location"], s.sl[2]["location"], False, False, False), "StationIndex B, the B target, the anchor = the actual landing, nothing outstanding")
                    self.assertIsNone(s.machine.landing_watch, "the landing watch is one-shot: it ends when the target is the landing station")
        self.assertEqual(len(set(finals.values())), 1)

    def test_the_anchor_survives_to_the_close_range_departure_in_both_orders(self):
        pendings = {}
        for purpose in ("start", "retry", "turnback"):
            for late in (False, True):
                with self.subTest(purpose=purpose, late=late):
                    s = self.scene()
                    s.sl[3]["location"] = s.sl[2]["location"] + 49.4           # a close pair B -> C (the O1 protection)
                    self.landing(s, purpose, late)
                    o = s.o
                    b = s.sl[2]
                    o.bve_time_ms = b["raw_dep"] - 100
                    o.bve_next_time = b["raw_dep"]
                    s.step(2, bve_door=0, bve_speed=0.0)
                    s.step(1, advance_ms=100, bve_next_loc=s.sl[3]["location"], bve_tgt_idx=3, bve_speed=0.0)
                    pendings[(purpose, late)] = bool(o.close_range_departure_reset_pending)       # right at the B -> C switch
        self.assertTrue(all(pendings.values()), pendings)

    def test_the_official_function_is_idempotent_and_not_copied(self):
        s = self.scene()
        o = s.o
        self.S.close_range_fix_landing_stop(o, 2, 1500.0)
        first = o.prev_actual_stop_loc
        self.S.close_range_fix_landing_stop(o, 2, 1500.0)
        self.assertEqual((first, o.prev_actual_stop_loc), (1500.0, 1500.0))
        import ast
        src = open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        for name in ("turnback_establish_b", "turnback_landing_step", "turnback_drive", "turnback_request"):
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            assigned = [t for n in ast.walk(fn) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Attribute) and t.attr in ("prev_actual_stop_loc", "close_range_departure_reset_pending")]
            self.assertEqual(assigned, [], "%s writes the O1 state itself" % name)

    def test_an_anchor_that_stays_wrong_is_a_failure_and_no_checkpoint_is_made(self):
        s = self.scene()
        original = self.S.close_range_fix_landing_stop
        self.S.close_range_fix_landing_stop = lambda owner, idx, loc: None            # the official function does nothing
        self.addCleanup(lambda: setattr(self.S, "close_range_fix_landing_stop", original))
        o = self.to_completion(s, late_target=True)
        s.target_to_b()
        self.assertEqual(self.b_checkpoints(o), [])
        self.assertFalse(o.has_scored_time_this_station)
        self.assertFalse(o.is_scoring_mode)

    def test_the_checkpoint_comes_after_the_target_the_anchor_and_the_mark(self):
        s = self.scene()
        order = []
        original_fix, original_cp = self.S.close_range_fix_landing_stop, self.S.create_turnback_b_checkpoint
        self.S.close_range_fix_landing_stop = lambda owner, idx, loc: (order.append("anchor"), original_fix(owner, idx, loc))[1]
        self.S.create_turnback_b_checkpoint = lambda owner, idx, *rest: (order.append(("checkpoint", owner.bve_tgt_idx, owner.prev_actual_stop_loc, owner.has_scored_time_this_station)), original_cp(owner, idx, *rest))[1]
        self.addCleanup(lambda: (setattr(self.S, "close_range_fix_landing_stop", original_fix), setattr(self.S, "create_turnback_b_checkpoint", original_cp)))
        o = self.to_completion(s, late_target=True)
        self.assertEqual(order, [], "nothing before the B target")
        s.target_to_b()
        self.assertEqual(order, ["anchor", ("checkpoint", 2, 1500.0, True)])


class D_TheCheckpointOfBIsTheLatestState(Base):
    def test_the_B_checkpoint_has_the_latest_score_and_the_actual_landing(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        o.score -= 100
        o.score_details["roll"] = -100                     # a change between the A arrival and the Jump
        s.jump_tick()
        s.complete()
        s.tick(16)
        cp = self.b_checkpoints(o)[0]
        self.assertEqual(cp["score"], o.score)
        self.assertEqual(cp["score_details"]["roll"], -100)
        self.assertEqual(cp["loc"], s.sl[2]["location"])
        self.assertEqual(cp["station_index"], 2)
        self.assertEqual(cp["role"], "arrived_station")
        self.assertEqual(len([c for c in o.save_data if c.get("station_index") == 1]), 0, "no A checkpoint")


if __name__ == "__main__":
    unittest.main()
