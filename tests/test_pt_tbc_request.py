"""Stage TB-C, slice C2 - the pseudo-turnback Jump REQUEST wiring (JUMP_TURNBACK, the one entry, capability / group check, pre-send fail-closed, no double Jump, ENT-R20 with three entries) and the
F1 input while an OFFICIAL Jump is in flight (OD-TB-27). Drives the REAL update_physics_and_scoring / begin_official_jump / _open_jump_transaction / _settle_jump_complete of main.Overlay through the offscreen rig."""
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

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-pt-tbc-request-")
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


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pt-tbc-request"])
        import main
        import scoring_logic
        import jump_transaction
        import jump_wire
        import station_identity
        import managed_input
        import pt_scene
        cls.main, cls.S, cls.JT, cls.JW, cls.SI, cls.MI, cls.P = main, scoring_logic, jump_transaction, jump_wire, station_identity, managed_input, pt_scene

    def scene(self, **kw):
        s = self.P.Scene(self, **kw)
        o = s.o
        self.sent = []
        o.send_jump_command = lambda cmd: (self.sent.append(cmd), None)[1]
        self.events = []
        o._emit_input_event = lambda event, **f: self.events.append((event, f))
        self.menu_toggles = []
        o.toggle_menu = lambda adv: self.menu_toggles.append(adv)
        return s

    def warnings(self, s):
        return [p["text"] for p in s.o.popups if p.get("category") == "警告"]


class A_TheRequest(Base):
    def test_the_request_is_made_once_at_arrival_plus_5_seconds_of_BVE_time(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.tick(advance_ms=t_a + 4900 - o.bve_time_ms)
        self.assertIsNone(o.jump_expectation)
        self.assertEqual(self.sent, [])
        s.tick(advance_ms=100)
        exp = o.jump_expectation
        self.assertIsNotNone(exp)
        self.assertEqual(exp.purpose, self.JT.JUMP_TURNBACK)
        self.assertEqual(exp.station_index, 2, "B of the pair")
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(o.is_official_jumping)
        self.assertEqual(s.machine.state, M.REQUESTED)
        for _ in range(50):
            s.tick(16)
        self.assertEqual(len(self.sent), 1, "never a second Jump for the same arrival")

    def test_the_purpose_is_a_formal_purpose(self):
        self.assertEqual(self.JT.JUMP_TURNBACK, "turnback")
        self.assertIn(self.JT.JUMP_TURNBACK, self.JT.JUMPS)
        self.assertEqual(M.PURPOSE_TURNBACK, self.JT.JUMP_TURNBACK)

    def test_a_Pause_of_the_BVE_time_moves_neither_the_display_nor_the_request(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.tick(advance_ms=2000)
        before = s.texts()
        for _ in range(600):                        # 60 s of the wall clock: BVE time stands still, the Python ticks go on
            s.rig.advance(0.1)
            s.tick(advance_ms=0)
        self.assertIsNone(o.jump_expectation)
        self.assertEqual(self.sent, [])
        self.assertEqual(s.texts(), before)
        s.tick(advance_ms=2900)
        self.assertIsNone(o.jump_expectation)
        s.tick(advance_ms=100)
        self.assertIsNotNone(o.jump_expectation, "the rest of the BVE time: 5.0 s in total")
        self.assertEqual(len(self.sent), 1)

    def test_an_open_menu_holds_the_request_until_it_is_closed(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        o.menu_state = 1
        s.tick(advance_ms=t_a + 6000 - o.bve_time_ms)
        self.assertIsNone(o.jump_expectation)
        o.menu_state = 0
        s.tick(16)
        self.assertIsNotNone(o.jump_expectation)

    def test_the_request_resets_the_station_state_and_begins_the_official_jump_of_B(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        exp = s.run_to_request(t_a)
        b = s.sl[2]
        self.assertEqual(o.expected_target_loc, b["location"])
        self.assertEqual(o.expected_target_time, exp.time_ms)
        self.assertEqual(exp.time_ms, b["raw_dep"] - b["stop_time"])
        self.assertFalse(o.has_scored_time_this_station, "the A mark was reset by the request block")


class B_FailClosedBeforeSending(Base):
    class Client(object):
        def __init__(self):
            self.cancelled = []

        def cancel(self, reason):
            self.cancelled.append(reason)

        def poll(self):
            pass

        def take_unreleased(self):
            return None

    def managed(self, s, announced):
        o = s.o
        o.dataplane_strict = True
        o.jump_client = self.Client() if announced is not None else None
        o.jump_group_available = (lambda: announced) if announced is not None else (lambda: True)

    def check_unavailable(self, s, aux):
        o = s.o
        t_a = s.arrive_a()
        history = len(o.save_data)
        s.run_to_request(t_a)
        self.assertEqual(self.sent, [], "nothing is sent")
        self.assertIsNone(o.jump_expectation, "no transaction")
        self.assertFalse(o.is_official_jumping)
        self.assertFalse(o.is_scoring_mode, "the scoring stops on the safe side")
        self.assertEqual(len(o.save_data), history, "no checkpoint")
        self.assertEqual(self.warnings(s), [], "no warning popup (OD-TB-30)")
        self.assertEqual([p["text"] for p in o.popups if "ジャンプ" in p["text"]], [])
        fails = [f for e, f in self.events if e == "turnback-fail"]
        self.assertEqual([f["reason"] for f in fails], ["pseudo-turnback-jump-unavailable"])
        self.assertIn(("turnback-unavailable", {"aux": aux}), self.events)
        for _ in range(100):
            s.tick(16)
        self.assertEqual(self.sent, [], "no automatic resend, the chain does not come back")
        self.assertEqual(len([e for e, f in self.events if e == "turnback-fail"]), 1, "one diagnostic")

    def test_a_jump_group_that_is_not_announced_stops_the_scoring_without_a_send(self):
        s = self.scene()
        self.managed(s, announced=False)
        self.check_unavailable(s, "group-unannounced")

    def test_a_missing_jump_client_stops_the_scoring_without_a_send(self):
        s = self.scene()
        self.managed(s, announced=None)
        self.check_unavailable(s, "sender-unavailable")

    def test_the_group_coming_back_does_not_revive_the_chain(self):
        s = self.scene()
        self.managed(s, announced=False)
        o = s.o
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        o.jump_group_available = lambda: True
        o.is_scoring_mode = True                     # even with the scoring switched on by hand the chain is gone
        for _ in range(100):
            s.tick(16)
        self.assertEqual(self.sent, [])
        self.assertIsNone(o.jump_expectation)

    def test_an_announced_group_sends(self):
        s = self.scene()
        o = s.o
        o.dataplane_strict = True
        o.jump_client = self.Client()
        o.jump_group_available = lambda: True
        o.send_jump_command = lambda cmd: (self.sent.append(cmd), b"\x01" * 16)[1]
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        self.assertEqual(len(self.sent), 1)
        self.assertIsNotNone(o.jump_expectation)

    def test_a_B_without_any_scheduled_time_is_requested_like_a_scoring_start_at_B_not_stopped(self):
        """OD-TB-33: the time of the Jump to B is the one of a scoring START at B (the current BVE time when the station has no time at all): no rule of the turnback's own, no stop."""
        s = self.scene()
        s.sl[2]["raw_dep"] = -1
        o = s.o
        t_a = s.arrive_a()
        exp = s.run_to_request(t_a)
        self.assertEqual(len(self.sent), 1)
        self.assertIsNotNone(exp)
        self.assertEqual(exp.time_ms, max(0, o.bve_time_ms))
        self.assertTrue(o.is_scoring_mode)
        self.assertNotIn("pseudo-turnback-b-time-unavailable", [f["reason"] for e, f in self.events if e == "turnback-fail"])

    def test_another_official_jump_in_flight_refuses_the_new_request_and_keeps_the_transaction(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        planned, why = self.JT.build_jump_request(self.JW.KIND_STA, 2, 36000000, self.SI.scope_of(o.current_scenario_id, o.bve_list_id, o.station_list), s.sl[2]["location"])
        self.S.begin_official_jump(o, s.sl[2]["location"], 36000000)
        o._open_jump_transaction(self.JT.JUMP_RETRY, planned, None)
        existing = o.jump_expectation
        s.run_to_request(t_a)
        self.assertIs(o.jump_expectation, existing, "the existing transaction is kept")
        self.assertEqual(self.sent, [])
        self.assertIn("pseudo-turnback-jump-outstanding", [f["reason"] for e, f in self.events if e == "turnback-fail"])


class C_F1WhileAnOfficialJumpIsInFlight(Base):
    def f1(self, s):
        before = len(self.menu_toggles)
        s.o._on_f1(True)
        return len(self.menu_toggles) - before

    def test_F1_is_allowed_in_the_5_second_window_after_the_A_arrival(self):
        s = self.scene()
        t_a = s.arrive_a()
        s.tick(advance_ms=1000)
        self.assertEqual(self.f1(s), 1, "the Pause is allowed before the request")

    def test_F1_is_ignored_from_the_turnback_request_and_nothing_is_sent_to_BVE_or_held(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        self.assertEqual(self.f1(s), 0, "no menu, no P to BVE")
        self.assertIn(("input-ignored", {"reason": "official-jump-in-progress", "key": "F1"}), self.events)
        self.assertEqual(self.warnings(s), [])
        s.jump_tick(late_target=True)
        s.complete()
        s.tick(16)
        self.assertEqual(self.f1(s), 0, "the completion alone does not release it: B is being established")
        s.target_to_b()
        s.tick(16)
        self.assertEqual(self.f1(s), 1, "released when B is established (target, anchor, mark and checkpoint done)")
        self.assertEqual(len([c for c in o.save_data if c.get("origin") == "turnback"]), 1)
        self.assertEqual(self.menu_toggles, [True], "only the F1 that was allowed toggled the menu: nothing was held and replayed, no automatic Pause")

    def test_the_hold_is_derived_from_the_live_state_and_ends_with_every_way_the_Jump_ends(self):
        for how in ("timeout", "completion-failure", "scenario-change", "shutdown", "session-off", "soft-off"):
            with self.subTest(how=how):
                s = self.scene()
                o = s.o
                t_a = s.arrive_a()
                s.run_to_request(t_a)
                self.assertTrue(self.S.official_jump_f1_hold(o))
                if how == "timeout":
                    s.rig.advance(11.0)
                    o._poll_jump_client()
                elif how == "completion-failure":
                    s.jump_tick()
                    s.complete(idx=3)
                elif how == "scenario-change":
                    o.apply_telemetry_text("SCENARIO_ID:%d" % (o.current_scenario_id + 1))
                elif how == "shutdown":
                    o._jump_transaction_finish("shutdown")
                elif how == "session-off":
                    o.reset_generation_state()
                elif how == "soft-off":
                    self.MI.discard_scoring_session(o)
                try:
                    s.tick(16)
                except IndexError:
                    pass
                self.assertFalse(self.S.official_jump_f1_hold(o), how)
                self.assertEqual(self.f1(s), 1, how)

    def test_F1_is_ignored_during_the_START_and_the_Retry_jump_and_allowed_after_the_end_word(self):
        for purpose in (self.JT.JUMP_START, self.JT.JUMP_RETRY):
            with self.subTest(purpose=purpose):
                s = self.scene()
                o = s.o
                s.arrive_a()
                planned, why = self.JT.build_jump_request(self.JW.KIND_STA, 2, 36000000, self.SI.scope_of(o.current_scenario_id, o.bve_list_id, o.station_list), s.sl[2]["location"])
                self.S.begin_official_jump(o, s.sl[2]["location"], 36000000)
                o._open_jump_transaction(purpose, planned, None)
                self.assertEqual(self.f1(s), 0)
                s.complete()
                self.assertFalse(o.is_official_jumping)
                self.assertEqual(self.f1(s), 1, "released when the end word was written")

    def test_an_open_menu_can_still_be_closed_by_F1(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        o.menu_state = 1
        self.assertEqual(self.f1(s), 1)


class D_NoUserFacingPopupForInternalFailures(Base):
    def test_W2_the_abort_of_an_unreleased_jump_is_a_diagnostic_and_the_safe_stop_only(self):
        s = self.scene()
        o = s.o
        t_a = s.arrive_a()
        s.run_to_request(t_a)
        s.rig.advance(11.0)
        o._poll_jump_client()
        self.assertFalse(o.is_scoring_mode)
        self.assertTrue(o.jump_lock)
        self.assertEqual(self.warnings(s), [])
        self.assertEqual(o.internal_abort_reason, "jump")
        self.assertIn(("jump-abort", {"reason": "timeout"}), self.events)

    def test_W3_the_refusal_of_the_start_is_a_diagnostic_only(self):
        s = self.scene()
        o = s.o
        snapshot = self.SI.start_snapshot(o.current_scenario_id, o.bve_list_id, o.station_list, 0)
        o._refuse_scoring_start(snapshot._replace(valid=False, reason="no-station"), True)
        self.assertEqual(self.warnings(s), [])

    def test_the_owner_approved_popups_are_unchanged_W1_the_illegal_jump(self):
        s = self.scene()
        o = s.o
        s.arrive_a(end=4)
        s.step(2, bve_jump_count=7)                  # a JUMP count change that is no official Jump (a timetable jump)
        self.assertFalse(o.is_scoring_mode)
        self.assertEqual(self.warnings(s), ["不正なジャンプを検知しました。", "採点を中断します。"])

    def test_no_new_warning_text_exists_in_the_turnback_code(self):
        text = src("scoring_logic.py")
        body = text[text.index("def turnback_diag"):text.index("def turnback_pair_a_of")]
        self.assertNotIn("add_score_popup", body)
        self.assertNotIn("popups.append", body)


class E_TheEntries(Base):
    """ENT-R20 with THREE entries (START / RETRY / PSEUDO_TURNBACK): a missing or an extra entry fails here."""
    def test_ENT_R20_three_official_entries(self):
        main_src, sl_src = src("main.py"), src("scoring_logic.py")
        self.assertEqual(len(re.findall(r"\bis_scoring_mode\s*=\s*True\b", main_src)) + len(re.findall(r"\bis_scoring_mode\s*=\s*True\b", sl_src)), 1)
        self.assertEqual(len(re.findall(r"(?<!def )\bbegin_official_jump\(self,", main_src)), 1)
        self.assertEqual(len(re.findall(r"(?<!def )\bbegin_official_jump\(self,", sl_src)), 2, "execute_retry and turnback_request")
        self.assertEqual(len(re.findall(r"_open_jump_transaction\(jump_transaction\.JUMP_START,", main_src)), 1)
        self.assertEqual(len(re.findall(r"_open_jump_transaction\(jump_transaction\.JUMP_RETRY,", sl_src)), 1)
        self.assertEqual(len(re.findall(r"_open_jump_transaction\(jump_transaction\.JUMP_TURNBACK,", sl_src)), 1)
        self.assertEqual(len(re.findall(r"\bsend_jump_command\(", sl_src)), 2, "execute_retry and turnback_request")
        for other in ("managed_input.py", "managed_mode.py", "pause_recovery.py", "pseudo_turnback_machine.py"):
            self.assertNotIn("begin_official_jump", src(other), other)

    def test_the_turnback_entry_is_called_from_the_driver_only(self):
        sl_src = src("scoring_logic.py")
        self.assertEqual(len(re.findall(r"\bturnback_request\(", sl_src)), 2, "its definition and the one call of turnback_drive")
        self.assertNotIn("turnback_request(", src("main.py"))
        import ast
        tree = ast.parse(sl_src)
        drive = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "turnback_drive")
        calls = [n for n in ast.walk(drive) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "turnback_request"]
        self.assertEqual(len(calls), 1)

    def test_the_driver_is_called_once_at_the_end_of_the_scoring_step_and_the_machine_never_sends(self):
        sl_src = src("scoring_logic.py")
        self.assertEqual(len(re.findall(r"(?<!def )\bturnback_drive\(self, current_time\)", sl_src)), 1)
        for word in ("send_jump_command", "_open_jump_transaction", "begin_official_jump", "time.", "monotonic"):
            self.assertNotIn(word, src("pseudo_turnback_machine.py"), word)

    def test_the_key_is_handled_in_one_place_and_does_not_hold_input(self):
        text = src("main.py")
        self.assertEqual(len(re.findall(r"official_jump_f1_hold\(self\)", text)), 1)
        body = text[text.index("def _on_f1"):text.index("def _handle_keys")]
        self.assertNotIn("PostMessage", body)
        self.assertNotIn("keyboard.on_press_key", body)


if __name__ == "__main__":
    unittest.main()
