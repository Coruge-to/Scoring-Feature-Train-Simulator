"""Stage TB-C, OD-TB-33 (plan 1) - the official Jump to the B of a pseudo-turnback is planned by THE scoring-start plan of the Overlay (Overlay._scoring_start_plan(snapshot, index)), so that

    START-at-B Jump time = turnback-to-B Jump time = B checkpoint time = Retry-to-B request time   (and the command, the position, the scope are the same)

for the six audited conditions; the score / details / history of the B checkpoint stay the LATEST state of the B establishment (only the TIME is the Jump's). Drives the REAL Overlay through the offscreen rig
(START = the real scoring-start button handler, the turnback = the real update_physics_and_scoring driver, Retry = the real execute_retry)."""
import os
import re
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

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-pt-tbc-od33-")
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


def src(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def function_source(text, name):
    """The source text of a top-level function (up to the next top-level def / class)."""
    m = re.search(r"^def %s\(.*?(?=^(?:def |class )|\Z)" % re.escape(name), text, re.S | re.M)
    assert m, name
    return m.group(0)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pt-tbc-od33"])
        import main
        import scoring_logic
        import jump_transaction
        import jump_wire
        import station_identity
        import pt_scene
        cls.main, cls.S, cls.JT, cls.JW, cls.SI, cls.P = main, scoring_logic, jump_transaction, jump_wire, station_identity, pt_scene

    def scene(self, fields=None, **kw):
        s = self.P.Scene(self, **kw)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + 500.0
        for k, v in (fields or {}).items():
            s.sl[2][k] = v
        self.sent = []
        o.send_jump_command = lambda cmd: (self.sent.append(cmd), None)[1]
        o._emit_input_event = lambda event, **f: None
        o.toggle_menu = lambda adv: None
        return s

    def start_at_b(self, fields):
        """The real scoring-start button handler with B (index 2) as the start station. Returns (time, command, location, scope, first checkpoint time, bve time at the press)."""
        s = self.scene(fields)
        o = s.o
        s.arrive_a(start=2)
        s.auto_fix = False
        o.is_scoring_mode = False
        o.menu_state, o.menu_cursor = 10, 1
        o.scoring_start_gate = None
        o.was_advancing_before_menu = False
        self.P.R.bind_identity(o, arr_idx=1, tgt_idx=2)
        self.sent[:] = []
        pressed_at = o.bve_time_ms
        o.handle_menu_enter(False)
        exp = o.jump_expectation
        self.assertIsNotNone(exp, "the START at B must send its Jump")
        result = (exp.time_ms, exp.command, exp.location, exp.scope, o.save_data[0]["time_ms"], pressed_at, exp.station_index)
        s.close()
        return result

    def turnback_chain(self, fields, retry=True):
        """The pseudo-turnback chain to the same B: request, Jump, completion, establishment, (Retry to the B checkpoint). Returns a dict."""
        s = self.scene(fields)
        o = s.o
        t_a = s.arrive_a()
        exp = s.run_to_request(t_a)
        self.assertIsNotNone(exp, "the turnback Jump must be requested")
        out = {"time": exp.time_ms, "command": exp.command, "location": exp.location, "scope": exp.scope, "index": exp.station_index, "request_bve_time": o.bve_time_ms}
        s.jump_tick()
        s.complete()
        s.tick(16)
        out["establish_bve_time"] = o.bve_time_ms
        cps = [c for c in o.save_data if c.get("origin") == "turnback"]
        self.assertEqual(len(cps), 1, "exactly one B checkpoint")
        out["cp"] = cps[0]
        if retry:
            res = self.main.execute_retry(o, len(o.save_data) - 1, False)
            self.assertTrue(res.accepted, getattr(res, "reason", None))
            e2 = o.jump_expectation
            out["retry"] = (e2.time_ms, e2.command, e2.location, e2.scope, e2.station_index)
        out["scene"] = s
        return out


T0 = 36000000
CONDITIONS = [
    ("1 raw_dep present, no def_time", {}, T0 + 135000, "STA"),
    ("2 stop_time=30000", {"stop_time": 30000}, T0 + 120000, "STA"),
    ("3 def_time smaller than calc_t", {"def_time": T0 + 100000}, T0 + 100000, "STA"),
    ("4 def_time later than calc_t", {"def_time": T0 + 200000}, T0 + 135000, "LOC"),
    ("5 raw_dep missing, raw_arr present", {"raw_dep": -1, "raw_arr": T0 + 140000}, T0 + 140000, "STA"),
    ("6 raw_dep and raw_arr missing", {"raw_dep": -1, "raw_arr": -1}, None, "STA"),
]


class A_SixConditions(Base):
    def test_START_at_B_turnback_B_checkpoint_and_Retry_agree_in_all_six_conditions(self):
        for name, fields, expected_time, expected_cmd_name in CONDITIONS:
            with self.subTest(name):
                st = self.start_at_b(fields)
                tb = self.turnback_chain(fields)
                try:
                    command = {"STA": self.JW.KIND_STA, "LOC": self.JW.KIND_LOC}[expected_cmd_name]
                    if expected_time is None:
                        # no time at all: both fall back to the CURRENT BVE time of their own moment (the same rule), which is not the same moment
                        self.assertEqual(st[0], max(0, st[5]), "START falls back to the BVE time of the press")
                        self.assertEqual(tb["time"], max(0, tb["request_bve_time"]), "the turnback falls back to the BVE time of the request, as START does")
                    else:
                        self.assertEqual(st[0], expected_time, "START time (the audited value)")
                        self.assertEqual(tb["time"], st[0], "turnback time = START time")
                    self.assertEqual(st[1], command)
                    self.assertEqual(tb["command"], st[1], "turnback command = START command")
                    self.assertEqual(tb["location"], st[2], "same position")
                    self.assertEqual(tuple(tb["scope"]), tuple(st[3]), "same scope")
                    self.assertEqual(tb["index"], st[6], "same station")
                    self.assertEqual(st[4], st[0], "START's first checkpoint is the planned time")
                    self.assertEqual(tb["cp"]["time_ms"], tb["time"], "B checkpoint time = the Jump time (not the BVE time of the checkpoint creation)")
                    self.assertNotEqual(tb["cp"]["time_ms"], tb["establish_bve_time"], "the checkpoint was created a few ticks after the Jump: its time is the Jump's, not the clock's")
                    self.assertEqual(tb["retry"][0], tb["cp"]["time_ms"], "Retry request time = checkpoint time")
                    self.assertEqual(tb["retry"][1], command, "Retry command = START command")
                    self.assertEqual(tb["retry"][2], tb["location"])
                    self.assertEqual(tuple(tb["retry"][3]), tuple(st[3]))
                    self.assertEqual(tb["retry"][4], tb["index"])
                finally:
                    tb["scene"].close()


class B_TheLatestStateIsNotFrozenAtTheJump(Base):
    def test_only_the_time_is_the_Jump_time_score_details_and_history_are_the_latest(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        exp = s.run_to_request(t_a)
        jump_time = exp.time_ms
        s.jump_tick(late_target=True)
        s.complete()
        o.score -= 70                                          # changes AFTER the Jump settled and BEFORE B is established
        o.score_details["roll"] = o.score_details.get("roll", 0) - 70
        history_marker = {"marker": "after-jump"}
        o.save_data.append(history_marker)
        s.target_to_b()
        cps = [c for c in o.save_data if c.get("origin") == "turnback"]
        self.assertEqual(len(cps), 1)
        cp = cps[0]
        self.assertEqual(cp["time_ms"], jump_time)
        self.assertNotEqual(cp["time_ms"], o.bve_time_ms)
        self.assertEqual(cp["score"], o.score, "the score is the latest one")
        self.assertEqual(cp["score_details"]["roll"], o.score_details["roll"], "the details are the latest ones")
        self.assertIn(history_marker, o.save_data[:o.save_data.index(cp)], "the history before the checkpoint is the latest history")
        self.assertIs(o.save_data[-1], cp)


class C_ThePlanIsOneFunction(Base):
    def snapshot(self, o, index):
        scope = self.SI.scope_of(o.current_scenario_id, o.bve_list_id, o.station_list)
        return self.SI.build_snapshot(index, scope, o.station_list, self.SI.ROLE_ARRIVED_STATION)

    def test_index_None_is_the_unchanged_START_plan_of_setting_start_idx(self):
        for name, fields, _t, _c in CONDITIONS:
            with self.subTest(name):
                s = self.scene(fields)
                o = s.o
                for k in (0, 2, 3):
                    o.setting_start_idx = k
                    snap = self.snapshot(o, k)
                    plain = o._scoring_start_plan(snap)
                    explicit = o._scoring_start_plan(snap, index=k)
                    self.assertEqual(plain[:3], explicit[:3])
                    self.assertEqual(plain[3], explicit[3])
                    self.assertEqual(plain[4], explicit[4])
                s.close()

    def test_a_given_index_does_not_depend_on_setting_start_idx(self):
        for name, fields, _t, _c in CONDITIONS:
            with self.subTest(name):
                s = self.scene(fields)
                o = s.o
                snap = self.snapshot(o, 2)
                results = []
                for k in (0, 1, 2, 3, 4):
                    o.setting_start_idx = k
                    results.append(o._scoring_start_plan(snap, index=2))
                for r in results[1:]:
                    self.assertEqual(r[:3], results[0][:3])
                    self.assertEqual(r[3], results[0][3])
                s.close()

    def test_an_index_outside_the_list_is_refused_and_nothing_is_changed(self):
        s = self.scene()
        o = s.o
        snap = self.snapshot(o, 2)
        before = (o.setting_start_idx, len(o.save_data), o.is_scoring_mode, o.jump_expectation)
        for bad in (-1, 5, 99, True, 1.0, "2", object()):
            with self.subTest(bad=bad):
                loc, name, t, planned, why = o._scoring_start_plan(snap, index=bad)
                self.assertIsNone(planned)
                self.assertEqual(why, "invalid-index")
                self.assertEqual(t, -1)
        self.assertEqual(before, (o.setting_start_idx, len(o.save_data), o.is_scoring_mode, o.jump_expectation))
        self.assertEqual(self.sent, [])
        s.close()

    def test_the_turnback_request_has_no_time_formula_of_its_own(self):
        text = function_source(src("scoring_logic.py"), "turnback_request")
        self.assertIn("_scoring_start_plan(snapshot, index=b_index)", text)
        for forbidden in ("raw_dep", "raw_arr", "stop_time", "def_time", "KIND_STA", "KIND_LOC", "build_jump_request", "bve_time_ms", "min("):
            self.assertNotIn(forbidden, text, "the turnback must not copy the START time formula (%s)" % forbidden)

    def test_the_START_handler_and_the_plan_stay_the_one_path_of_the_start(self):
        text = src("main.py")
        self.assertEqual(text.count("self._scoring_start_plan(start_identity)"), 1, "the START button still calls the plan without an index")
        plan = re.search(r"def _scoring_start_plan\(self, snapshot, index=None\):.*?(?=\n    def )", text, re.S)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.group(0).count("self.setting_start_idx"), 1, "setting_start_idx is read only to default the index")

    def test_the_checkpoint_time_comes_from_the_Jump_record_never_the_clock(self):
        text = function_source(src("scoring_logic.py"), "turnback_establish_b")
        self.assertIn("create_turnback_b_checkpoint(self, b_index, jump_time)", text)
        self.assertIn("record.time_ms", text)
        self.assertIn("expectation.time_ms", function_source(src("scoring_logic.py"), "note_jump_settlement"))

    def test_a_settlement_without_the_planned_time_is_a_product_failure_not_a_silent_fallback(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.jump_tick()
        original = self.S.note_jump_settlement

        def without_time(owner, expectation, end, selected, actual, pending):
            original(owner, expectation, end, selected, actual, pending)
            machine = self.S.turnback_machine_of(owner)
            if machine.settlement is not None:
                machine.settlement = machine.settlement._replace(time_ms=None)
        self.S.note_jump_settlement = without_time
        self.main.note_jump_settlement = without_time
        self.addCleanup(lambda: (setattr(self.S, "note_jump_settlement", original), setattr(self.main, "note_jump_settlement", original)))
        s.complete()
        s.tick(16)
        self.assertEqual([c for c in o.save_data if c.get("origin") == "turnback"], [])
        self.assertFalse(o.is_scoring_mode)
        s.close()


if __name__ == "__main__":
    unittest.main()
