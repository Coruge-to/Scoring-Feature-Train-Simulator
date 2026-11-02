"""TB-G C-01 (Stage fix): the landing of the pseudo-turnback Jump at B is not an arrival, whatever the ORDER in which the host reports the Jump.

Real C-01 order (Current, managed; 2026-11-01 13:31:27.525-.543): A is an OPERATIONAL stop; the Jump completes with the telemetry already naming B (arrived StationIndex B, target B); the Overlay's
_settle_jump_complete ABSORBS the sender's JUMP counter (main.py: bve_jump_count = last_jump_count = completed count), so the jump rule of update_physics_and_scoring (the [JUMP DETECT] block that sets
jump_lock) never runs. The fix is ONE line in scoring_logic.turnback_request: jump_lock is taken right after begin_official_jump and released by the first departure from B (existing rule). The events are
driven by the PRODUCT functions only (tests/pt_scene.py + tests/tbg_c01_rig.py); only the seams of the rig are replaced.

class A_RealOrderContracts   what the fix guarantees (RED on the baseline a411e78: 8 failures; GREEN with the fix)
class B_LockOwnership        the lock is taken at the request (never earlier), kept through the landing, released only by the first departure; the checkpoint of B; a refused request takes no lock
class C_RetryF5Start         Retry to B / F5 / the next START after the landing, in the real order
class D_FixtureGapAndStatic  why the existing fixtures could not see it; the one line is in the one entry both hosts share
Out of scope here (recorded in the stage report, NOT encoded): the operating time of B after a Retry to B that follows a B departure (landing watch ends while jump_lock is False) - a separate pre-existing path."""
import ast
import glob
import inspect
import itertools
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
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbg-landing-")
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


# column indexes of Flow.rows (tests/tbg_c01_rig.py COLUMNS)
SCORE, STOP, ARR, TGT, AWAIT, SCORING_ON, LOCK, JUMPING, ABORT = 2, 3, 8, 9, 10, 13, 14, 15, 20


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbg-landing"])
        import main
        import scoring_logic
        import tbg_c01_rig
        import pt_scene
        cls.main, cls.S, cls.R, cls.P = main, scoring_logic, tbg_c01_rig, pt_scene

    def real(self, n_after=3, **kw):
        """The REAL C-01 order (operational stops, the arrived StationIndex advances at the landing, the settlement absorbs the JUMP counter)."""
        kw.setdefault("operational", True)
        kw.setdefault("advance_arr", True)
        kw.setdefault("order", "complete_first")
        return self.R.Flow(self, **kw).run(n_after)

    def spy_count(self, name):
        calls = []
        original = getattr(self.S, name)

        def spy(*args, **kwargs):
            calls.append(args[1:] if len(args) > 1 else ())
            return original(*args, **kwargs)
        setattr(self.S, name, spy)
        self.addCleanup(setattr, self.S, name, original)
        return calls

    @staticmethod
    def row(f, name):
        return {r[0]: r for r in f.rows}[name]

    @staticmethod
    def history(o):
        return [(cp.get("station_index"), cp.get("origin", "-")) for cp in o.save_data]


class A_RealOrderContracts(Base):
    def test_TBG_01_exactly_one_B_checkpoint_and_it_is_the_turnback_one(self):
        f = self.real()
        b = [cp for cp in f.o.save_data if cp.get("station_index") == 2]
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0].get("origin"), "turnback")
        self.assertEqual(b[0]["score"], self.row(f, "settled")[SCORE], "the B checkpoint carries the score of the landing (no landing score added)")
        self.assertEqual(f.names().count("create_save_data"), 0, "the generic arrival path does not process the landing at B")
        self.assertEqual(f.names().count("create_turnback_b_checkpoint"), 1)

    def test_TBG_02_no_plus_500_and_no_double_scoring_at_the_landing(self):
        stops = self.spy_count("apply_stop_score")
        times = self.spy_count("apply_time_score")
        f = self.real(n_after=10)
        settled = self.row(f, "settled")
        self.assertEqual(self.row(f, "tick+3")[SCORE], settled[SCORE], "the score is the score of the A arrival")
        self.assertEqual(f.o.score_details["stop"], settled[STOP])
        self.assertEqual(len(stops), 1, "the stop score ran for A only (never for the landing)")
        self.assertEqual(len(times), 1, "the operating time ran for A only (B has no arrival time)")
        self.assertEqual(f.fail_reasons(), [])
        self.assertTrue(f.o.is_scoring_mode)
        self.assertEqual(f.o.internal_abort_reason, "")
        self.assertEqual(len(f.sent), 1, "one Jump, never a second")

    def test_TBG_03_the_scoring_stays_on_through_the_landing(self):
        f = self.real(n_after=10)
        self.assertTrue(all(r[SCORING_ON] for r in f.rows), "scoring ON at every recorded step")
        self.assertFalse(any(r[ABORT] for r in f.rows), "no abort reason at any step")

    def test_TBG_04_after_B_the_ordinary_scoring_of_the_next_station_returns_and_equals_the_reference_order(self):
        """B -> C after the landing: the arrival at C is scored in the ordinary way, once, and the result is the one of the reference order (the JUMP count seen BEFORE the completion = what the TB-C / TB-D / TB-E
        fixtures and E33 verified), for both stop kinds."""
        for operational in (True, False):
            with self.subTest(operational=operational):
                results = {}
                for order in ("detect_first", "complete_first"):
                    f = self.R.Flow(self, operational=operational, advance_arr=True, order=order).run(10)
                    before = f.o.score
                    f.depart_b_and_arrive_c()
                    o = f.o
                    self.assertTrue(o.is_scoring_mode)
                    self.assertEqual(f.fail_reasons(), [])
                    self.assertGreater(o.score_details["stop"], 0, "the stop position of C is scored")
                    results[order] = (o.score - before, dict(o.score_details), self.history(o), sorted(p["text"] for p in o.popups))
                self.assertEqual(results["complete_first"], results["detect_first"], "the real order ends exactly as the reference order")
                self.assertEqual([c[0] for c in results["complete_first"][2]], [0, 2, 3], "history: start, B (turnback), C - one each")
                self.assertEqual(results["complete_first"][2][1][1], "turnback")

    def test_TBG_05_the_B_departure_scores_no_operating_time_and_B_has_no_second_arrival_score(self):
        times = self.spy_count("apply_time_score")
        stops = self.spy_count("apply_stop_score")
        f = self.real(n_after=10)
        n_time, n_stop = len(times), len(stops)
        f.depart_b_and_arrive_c()
        self.assertEqual(n_time, 1, "operating time: A only until the landing is over")
        self.assertEqual(len(times) - n_time, 0, "the B departure and the arrival at C (no timing at C) add no operating time")
        self.assertEqual(n_stop, 1, "stop score: A only until the landing is over")
        self.assertEqual(len(stops) - n_stop, 1, "stop score: C once")

    def test_TBG_06_the_B_departure_scores_no_operating_time_in_both_switch_orders(self):
        """The NEXTLOC switch of B -> C comes while the train stands (close_then_go: jump_lock still holds) or after it moved (moving_switch: jump_lock is released first, only the 'scored' mark of B keeps the time out)."""
        for operational, order in itertools.product((True, False), ("close_then_go", "moving_switch")):
            with self.subTest(operational=operational, order=order):
                times = self.spy_count("apply_time_score")
                f = self.R.Flow(self, operational=operational, order="complete_first").run(10)
                n, detail = len(times), f.o.score_details["time"]
                f.depart_b_only(order)
                self.assertEqual(len(times) - n, 0, "no operating time at the departure from B")
                self.assertEqual(f.o.score_details["time"], detail)
                self.assertEqual(f.o.bve_tgt_idx, 3, "the target moved on to the next station")

    def test_TBG_07_a_door_open_edge_at_B_after_the_landing_scores_no_second_arrival_in_the_real_order(self):
        """The silent sibling of the abort (door stations B, e.g. the non-closed-door pairs 2 and 3 of C-01): no failure is raised, the arrival of B is simply scored a second time (+500) at the door edge."""
        f = self.R.Flow(self, operational=False, advance_arr=True, order="complete_first").run(10)
        o = f.o
        before, details = o.score, dict(o.score_details)
        f.scene.step(1, bve_door=1, bve_arr_idx=2, bve_arr_seq=o.bve_arr_seq + 1)
        f.scene.step(20)
        self.assertEqual(o.score, before)
        self.assertEqual(dict(o.score_details), details)
        self.assertEqual([cp.get("origin") for cp in o.save_data if cp.get("station_index") == 2], ["turnback"])
        self.assertTrue(o.is_scoring_mode)

    def test_TBG_08_all_eight_orders_end_without_failure_without_landing_score_and_with_one_B_checkpoint(self):
        """Both hosts reach the same Python entry; whichever order of the Jump count / the arrived index / the stop kind the host reports, the result is the same."""
        for operational, advance_arr, order in itertools.product((True, False), (True, False), ("complete_first", "detect_first")):
            with self.subTest(operational=operational, advance_arr=advance_arr, order=order):
                f = self.R.Flow(self, operational=operational, advance_arr=advance_arr, order=order)
                f.to_arrival_at_a()
                f.to_request()
                score0 = f.o.score
                f.land()
                f.after(5)
                o = f.o
                self.assertEqual(f.fail_reasons(), [])
                self.assertTrue(o.is_scoring_mode)
                self.assertEqual(o.score, score0, "no score from the landing")
                self.assertEqual([cp.get("origin") for cp in o.save_data if cp.get("station_index") == 2], ["turnback"])
                self.assertEqual(len(f.sent), 1)


class B_LockOwnership(Base):
    def test_TBG_09_the_lock_is_taken_at_the_request_and_not_before(self):
        for operational in (True, False):
            with self.subTest(operational=operational):
                f = self.R.Flow(self, operational=operational)
                f.to_arrival_at_a()
                f.to_request()
                self.assertFalse(self.row(f, "A-arrived")[LOCK], "the arrival at A is an ordinary arrival (no lock)")
                self.assertEqual(self.row(f, "A-arrived")[SCORE], 550, "A is scored in the ordinary way")
                self.assertTrue(self.row(f, "requested(+10.0s)")[LOCK], "taken with the request of the Jump")
                self.assertEqual(len(f.sent), 1)

    def test_TBG_10_the_lock_holds_through_the_landing_and_only_the_first_departure_from_B_releases_it(self):
        for operational in (True, False):
            with self.subTest(operational=operational):
                f = self.R.Flow(self, operational=operational, order="complete_first").run(10)
                self.assertTrue(all(r[LOCK] for r in f.rows if r[0] in ("settled",) or r[0].startswith("tick+")), "held at the settlement and at every tick after it")
                o, s = f.o, f.scene
                s.step(2, bve_door=0, bve_speed=0.0)
                self.assertTrue(o.jump_lock, "a standing train with closed doors has not departed")
                s.step(3, bve_speed=1.5, bve_location=s.sl[2]["location"] + 3.0, bve_brk_notch=0)
                self.assertFalse(o.jump_lock, "the first departure releases it (the existing rule)")

    def test_TBG_11_the_real_order_preconditions_of_the_landing(self):
        """Measured facts of the C-01 order that the fix has to hold under: arrived StationIndex and target are B at the settlement, the JUMP counter was absorbed (no jump rule), the Jump is sent once."""
        requests = self.spy_count("turnback_request")
        f = self.R.Flow(self, operational=True, advance_arr=True, order="complete_first")
        f.to_arrival_at_a()
        f.to_request()
        f.land()
        f.after(10)
        settled = self.row(f, "settled")
        self.assertEqual((settled[ARR], settled[TGT]), (2, 2), "arrived StationIndex and target are B at the settlement ('stidx arr=3 tgt=3')")
        self.assertFalse(settled[JUMPING])
        self.assertEqual(f.o.last_jump_count, f.o.bve_jump_count, "the settlement absorbed the sender's JUMP counter")
        self.assertEqual([l for l in f.scene.rig.log if "JUMP DETECT" in l], [])
        self.assertEqual(len(requests), 1, "one turnback request")
        self.assertEqual(len(f.sent), 1, "one Jump command, never a second")

    def test_TBG_12_the_B_checkpoint_is_the_turnback_checkpoint_of_the_actual_landing(self):
        for operational in (True, False):
            with self.subTest(operational=operational):
                f = self.R.Flow(self, operational=operational, order="complete_first")
                f.to_arrival_at_a()
                f.to_request()
                exp = f.exp
                f.land()
                f.after(10)
                o = f.o
                b = f.scene.sl[2]
                cps = [cp for cp in o.save_data if cp.get("station_index") == 2]
                self.assertEqual(len(cps), 1)
                cp = cps[0]
                self.assertEqual(cp["origin"], "turnback")
                self.assertEqual(cp["role"], "arrived_station", "the identity of an ARRIVED station (a Retry accepts it after the first place)")
                self.assertEqual(cp["loc"], b["location"], "the actual landing position")
                self.assertEqual(cp["station_location"], b["location"])
                self.assertEqual(cp["target_loc"], b["location"], "the target established after the landing")
                self.assertEqual(cp["time_ms"], exp.time_ms, "the time the Jump to B was planned with (START-at-B = turnback = B checkpoint)")
                self.assertEqual(cp["stop_error"], 0.0)
                self.assertEqual(cp["scope"], o.save_data[0]["scope"])
                self.assertEqual(cp["score"], self.row(f, "settled")[SCORE])
                self.assertEqual(o.prev_actual_stop_loc, b["location"], "the anchor of the close-range rule is the actual landing")
                self.assertEqual(o.bve_tgt_idx, 2)
                self.assertEqual(self.history(o), [(0, "-"), (2, "turnback")], "history: the start and B, nothing else")

    def test_TBG_13_a_request_that_is_refused_takes_no_lock(self):
        """turnback_request returns before begin_official_jump when another official Jump is open: the line of the fix is not reached and the lock stays as it was (a mutant that takes it first leaves the scoring locked)."""
        f = self.R.Flow(self, operational=True)
        f.to_arrival_at_a()
        o = f.o
        self.assertFalse(o.jump_lock)
        o.jump_expectation = object()
        self.S.turnback_request(o, {"target_index": 2})
        self.assertEqual(f.fail_reasons(), ["pseudo-turnback-jump-outstanding"])
        self.assertFalse(o.jump_lock, "no lock without a Jump")
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(f.sent, [])


class C_RetryF5Start(Base):
    def depart_and_retry(self, operational, depart_first, order):
        f = self.R.Flow(self, operational=operational, order=order).run(10)
        if depart_first:
            f.depart_b_only("close_then_go")
        before = f.o.score
        res = f.retry_to_b()
        self.assertTrue(res.accepted, res)
        f.after(10)
        return f, before

    def test_TBG_14_retry_to_B_before_the_departure_ends_as_the_reference_order_does(self):
        results = {}
        for operational in (True, False):
            for order in ("detect_first", "complete_first"):
                f, before = self.depart_and_retry(operational, False, order)
                o = f.o
                landed = (o.score, dict(o.score_details))
                f.depart_b_and_arrive_c()
                self.assertTrue(o.is_scoring_mode)
                self.assertEqual(f.fail_reasons(), [])
                results[(operational, order)] = (before, landed, o.score, dict(o.score_details), self.history(o))
            with self.subTest(operational=operational):
                self.assertEqual(results[(operational, "complete_first")], results[(operational, "detect_first")], "the real order ends exactly as the reference order")
                self.assertEqual(results[(operational, "complete_first")][4], [(0, "-"), (2, "turnback"), (3, "-")])

    def test_TBG_15_retry_to_B_after_the_departure_restores_B_and_leaves_no_second_chain_or_Jump(self):
        for operational in (True, False):
            with self.subTest(operational=operational):
                requests = self.spy_count("turnback_request")
                f, _ = self.depart_and_retry(operational, True, "complete_first")
                o, m = f.o, f.scene.machine
                self.assertEqual(o.score, o.save_data[1]["score"], "the score of the B checkpoint is restored")
                self.assertEqual(self.history(o), [(0, "-"), (2, "turnback")], "one B checkpoint")
                self.assertEqual(f.fail_reasons(), [])
                self.assertTrue(o.is_scoring_mode)
                self.assertEqual(o.internal_abort_reason, "")
                self.assertEqual(len(requests), 1, "exactly one TURNBACK Jump (the Retry's own Jump is not one)")
                self.assertEqual(len(f.sent), 2, "the turnback Jump and the Retry Jump")
                self.assertEqual((m.state, m.awaiting_b, m.landing_watch), ("idle", False, None), "no chain is left (the landing record of the finished chain is kept by the machine as ever)")
                self.assertEqual(o.last_jump_count, o.bve_jump_count, "the real order absorbed the counter of the Retry too")

    def test_TBG_16_F5_after_the_request_or_after_the_landing_drops_the_chain_and_the_lock_does_not_outlive_the_first_departure(self):
        for when, operational in itertools.product(("requested", "landed"), (True, False)):
            with self.subTest(when=when, operational=operational):
                f = self.R.Flow(self, operational=operational, order="complete_first")
                f.to_arrival_at_a()
                f.to_request()
                if when == "landed":
                    f.land()
                    f.after(3)
                o, m = f.o, f.scene.machine
                self.assertTrue(o.jump_lock)
                o.apply_telemetry_text("SCENARIO_ID:%d" % (o.current_scenario_id + 1))             # F5: a new scenario instance
                f.after(2)
                self.assertIn(m.state, ("idle", "discarded"))
                self.assertEqual((m.awaiting_b, m.settlement, m.landing, m.b_watch, m.landing_watch), (False, None, None, None, None), "no chain, record or watch of the old run")
                self.assertIsNone(o.jump_expectation)
                self.assertFalse(o.is_scoring_mode, "the old run is over")
                self.assertEqual(f.fail_reasons(), [], "dropped by the lifecycle, not failed")
                self.assertEqual(len(f.sent), 1, "nothing is resent")
                f.scene.step(3, bve_speed=5.0, bve_door=0, bve_location=f.scene.sl[2]["location"] + 5.0)
                self.assertFalse(o.jump_lock, "the existing departure rule releases the lock of the dropped chain")

    def test_TBG_17_the_next_START_after_an_F5_works_in_the_real_order_even_with_the_lock_left_by_the_dropped_chain(self):
        for when in ("requested", "landed"):
            with self.subTest(when=when):
                requests = self.spy_count("turnback_request")
                f = self.R.Flow(self, operational=True, order="complete_first")
                f.to_arrival_at_a()
                f.to_request()
                if when == "landed":
                    f.land()
                    f.after(3)
                o = f.o
                o.apply_telemetry_text("SCENARIO_ID:%d" % (o.current_scenario_id + 1))
                f.after(2)
                o.is_scoring_mode = False
                o.menu_state, o.menu_cursor = 10, 1
                o.scoring_start_gate = None
                o.was_advancing_before_menu = False
                self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
                o.bve_location, o.bve_speed = 0.0, 0.0
                o.handle_menu_enter(False)
                exp = o.jump_expectation
                self.assertIsNotNone(exp)
                self.assertEqual(exp.purpose, "start")
                f.telemetry_landing(exp, exp.station_index, arr_seq_step=0)
                f.after(5)
                self.assertTrue(o.is_scoring_mode, "the START path is unchanged")
                self.assertEqual([(cp.get("station_index"), cp.get("role")) for cp in o.save_data], [(0, "scoring_start")])
                self.assertEqual(f.fail_reasons(), [])
                self.assertEqual(len(requests), 1, "no turnback request after the START")


class D_FixtureGapAndStatic(Base):
    def test_TBG_18_the_existing_jump_tick_counts_the_jump_before_the_completion_and_never_advances_the_arrived_index(self):
        src = inspect.getsource(self.P.Scene.jump_tick)
        self.assertIn("bve_jump_count", src)
        self.assertNotIn("bve_arr_idx", src, "the arrived StationIndex is not moved at the landing by the TB-C / TB-D / TB-E rig")
        flow_src = open(os.path.join(HERE, "test_pt_tbd_real_flow.py"), encoding="utf-8").read()
        land = flow_src[flow_src.index("def land(self"):flow_src.index("def tail(self")]
        self.assertLess(land.index("s.jump_tick(late)"), land.index("s.complete()"), "RF flow: jump tick (JUMP count seen) first, then the completion")
        self.assertLess(land.index("s.complete()"), land.index("o.bve_arr_idx = 2"), "RF flow: the arrived index is set AFTER the completion and the establishment")
        self.assertNotIn("bve_doordir = 0", land, "no operational stop at A / B in the RF flow (a door-open edge at A)")

    def test_TBG_19_the_reference_order_hides_nothing_and_the_real_order_never_runs_the_jump_rule(self):
        old = self.R.Flow(self, operational=True, advance_arr=True, order="detect_first").run(3)
        self.assertEqual(old.fail_reasons(), [])
        self.assertTrue(self.row(old, "settled")[LOCK], "reference order: the jump rule sets the lock at the landing (JUMP DETECT)")
        self.assertEqual(len([l for l in old.scene.rig.log if "JUMP DETECT" in l]), 1)
        real = self.R.Flow(self, operational=True, advance_arr=True, order="complete_first")
        real.to_arrival_at_a()
        real.to_request()
        real.land()
        real.after(3)
        self.assertEqual([l for l in real.scene.rig.log if "JUMP DETECT" in l], [], "no [JUMP DETECT] line, as in the desktop log of the C-01 run")
        self.assertEqual(real.o.last_jump_count, real.o.bve_jump_count)

    def test_TBG_20_the_lock_is_taken_by_the_one_entry_of_the_turnback_Jump_that_both_hosts_share(self):
        path = os.path.join(ROOT, "scoring_logic.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "turnback_request"]
        self.assertEqual(len(funcs), 1)
        body = funcs[0].body

        def is_call(node, name):
            return isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == name

        begin = [i for i, n in enumerate(body) if is_call(n, "begin_official_jump")]
        self.assertEqual(len(begin), 1)
        lock = body[begin[0] + 1]
        self.assertTrue(isinstance(lock, ast.Assign) and len(lock.targets) == 1 and ast.unparse(lock.targets[0]) == "self.jump_lock" and isinstance(lock.value, ast.Constant) and lock.value.value is True,
                        "self.jump_lock = True directly after begin_official_jump, at the top level of the function (reached only by a request that is really sent)")
        send = body[begin[0] + 2]
        self.assertTrue(isinstance(send, ast.Assign) and "send_jump_command" in ast.dump(send), "and before the command is sent")
        for i, node in enumerate(body[:begin[0]]):
            self.assertFalse(any(isinstance(x, ast.Attribute) and x.attr == "jump_lock" for x in ast.walk(node)), "no earlier statement (the refusals) touches the lock")
        owners = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.py")) if "def turnback_request(" in open(p, encoding="utf-8").read()]
        self.assertEqual(owners, ["scoring_logic.py"], "one definition: the Current and the Legacy hosts both use it (no copy of the entry)")


if __name__ == "__main__":
    unittest.main()
