"""The ARRIVAL DISPLAY contract of the pseudo-turnback A (Owner, 2026-10-31): TB-DISP-R1 .. R12.

  case 1  no special popup (no basic braking achieved, no 0 cm stop):   arrival -> guidance 5.0 s -> Jump request
  case 2  a special popup (basic braking achieved and / or 0 cm stop):  arrival -> special popup 3.0 s -> guidance 2.0 s -> Jump request     (5.0 s in total; two special popups share the ONE 3.0 s)

The base is the BVE time of the tick that ran evaluate_arrival (current_time = bve_time_ms / 1000). The '+500' style score lines are 5.0 s as at every other station and are not part of this contract.
Scope: the REAL update_physics_and_scoring (the popups) + the pure machine (the request time and the unavailable abort). The wiring of the machine's request to the Overlay's Jump sender is Stage TB-C; here a host stub
calls machine.tick() with the BVE time, exactly as the Overlay will.
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
GUIDE = "疑似折り返し"


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-pt-display-")
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
        raise AssertionError("the display module wrote into the redirected profile: %r" % (left,))


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAS_QT:
            raise unittest.SkipTest("PyQt6 is not importable by this interpreter")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["pt-display"])
        import main
        import scoring_logic
        import pt_scene
        cls.main, cls.S, cls.P = main, scoring_logic, pt_scene

    def arrived(self, braking, error_m, **kw):
        s = self.P.Scene(self, **kw)
        s.approach(braking)
        s.stop_at(error_m)
        t = s.open_door()
        return s, t

    def at(self, s, t_arrival, offset_ms):
        """Advance the BVE clock so that it reads exactly t_arrival + offset_ms (one tick)."""
        s.tick(advance_ms=t_arrival + offset_ms - s.o.bve_time_ms)
        assert s.o.bve_time_ms == t_arrival + offset_ms

    def specials(self, s):
        return [p for p in s.o.popups if self.S.is_arrival_special_popup(p)]

    def guides(self, s):
        return [p for p in s.o.popups if p["category"] == GUIDE]

    def request_at(self, s, now_ms, **kw):
        return s.machine.tick(now_ms, s.o.current_scenario_id, True, **kw)


# ==============================================================================================================================================
# the Owner's twelve (TB-DISP-R1 .. R12)
# ==============================================================================================================================================
class D_Display(Base):
    def test_TB_DISP_R1_no_special_popup_the_guidance_fills_the_five_seconds_then_one_jump(self):
        s, t = self.arrived("plain", 0.3)
        self.assertEqual(self.specials(s), [])
        self.assertEqual(len(self.guides(s)), 1, "the guidance is on at the arrival tick itself")
        self.assertEqual(self.guides(s)[0]["expire_time"], t / 1000.0 + 5.0)
        self.assertEqual(s.machine.display_state(t), M.DISPLAY_GUIDANCE)
        self.at(s, t, 4999)
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.request_at(s, t + 4999), [])
        self.at(s, t, 5000)
        self.assertEqual(self.guides(s), [], "the guidance ends where the request is made")
        acts = self.request_at(s, t + 5000)
        self.assertEqual([a[0] for a in acts], ["request_jump"])

    def test_TB_DISP_R2_basic_braking_three_seconds_then_two_seconds_of_guidance(self):
        s, t = self.arrived("stepwise", 0.3)
        sp = self.specials(s)
        self.assertEqual([p["category"] for p in sp], ["基本制動"])
        self.assertEqual(sp[0]["expire_time"], t / 1000.0 + 3.0)
        self.assertEqual(self.guides(s), [], "the guidance waits for the special popup")
        self.assertEqual(s.machine.display_state(t), M.DISPLAY_SPECIAL_3S)
        self.at(s, t, 3000)
        self.assertEqual(self.specials(s), [])
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.guides(s)[0]["expire_time"], t / 1000.0 + 5.0, "2.0 s of guidance, not 5.0 s more")
        self.at(s, t, 5000)
        self.assertEqual(self.guides(s), [])
        self.assertEqual([a[0] for a in self.request_at(s, t + 5000)], ["request_jump"])

    def test_TB_DISP_R3_zero_cm_stop_three_seconds_then_two_seconds_of_guidance(self):
        s, t = self.arrived("plain", 0.0)
        sp = self.specials(s)
        self.assertEqual([(p["category"], p["text"]) for p in sp], [("ボーナス", "0cm停車成功!!!")])
        self.assertEqual(sp[0]["expire_time"], t / 1000.0 + 3.0)
        self.assertEqual(self.guides(s), [])
        self.at(s, t, 3000)
        self.assertEqual((self.specials(s), len(self.guides(s))), ([], 1))
        self.at(s, t, 5000)
        self.assertEqual([a[0] for a in self.request_at(s, t + 5000)], ["request_jump"])

    def test_TB_DISP_R4_basic_braking_and_zero_cm_together_share_one_three_second_window(self):
        s, t = self.arrived("stepwise", 0.0)
        sp = self.specials(s)
        self.assertEqual(sorted(p["category"] for p in sp), ["ボーナス", "基本制動"])
        self.assertEqual([p["expire_time"] for p in sp], [t / 1000.0 + 3.0] * 2, "3.0 s in total, not 6.0 s")
        self.at(s, t, 2999)
        self.assertEqual(len(self.specials(s)), 2)
        self.assertEqual(self.guides(s), [])
        self.at(s, t, 3000)
        self.assertEqual(self.specials(s), [])
        self.assertEqual(len(self.guides(s)), 1)
        self.at(s, t, 5000)
        self.assertEqual(len(self.request_at(s, t + 5000)), 1)

    def test_TB_DISP_R5_2_999_s_is_special_3_000_s_is_guidance(self):
        for braking, err in (("stepwise", 0.3), ("plain", 0.0), ("stepwise", 0.0)):
            with self.subTest(braking=braking, err=err):
                s, t = self.arrived(braking, err)
                self.at(s, t, 2999)
                self.assertTrue(self.specials(s) and not self.guides(s))
                self.assertEqual(s.machine.display_state(t + 2999), M.DISPLAY_SPECIAL_3S)
                self.at(s, t, 3000)
                self.assertTrue(not self.specials(s) and self.guides(s))
                self.assertEqual(s.machine.display_state(t + 3000), M.DISPLAY_GUIDANCE)

    def test_TB_DISP_R6_4_999_s_no_jump_5_000_s_one_jump(self):
        for braking, err in (("plain", 0.3), ("stepwise", 0.3), ("plain", 0.0), ("stepwise", 0.0)):
            with self.subTest(braking=braking, err=err):
                s, t = self.arrived(braking, err)
                self.assertEqual(self.request_at(s, t + 4999), [])
                self.assertEqual(s.machine.display_state(t + 4999), M.DISPLAY_GUIDANCE)
                self.assertEqual(s.machine.display_state(t + 5000), M.DISPLAY_REQUEST_READY)
                acts = self.request_at(s, t + 5000)
                self.assertEqual([a[0] for a in acts], ["request_jump"])
                self.assertEqual(acts[0][1]["target_index"], 2)
                self.assertEqual(s.machine.display_state(t + 5000), M.DISPLAY_REQUESTED)
                for k in range(1, 50):
                    self.assertEqual(self.request_at(s, t + 5000 + k * 16), [])

    def test_TB_DISP_R7_while_the_bve_clock_stands_still_the_display_does_not_advance(self):
        for braking, err in (("plain", 0.3), ("stepwise", 0.3)):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, err)
                before = [(p["category"], p["text"], p["expire_time"]) for p in s.o.popups]
                for _ in range(300):
                    s.tick(advance_ms=0, wall_advance=0.1)                      # the clock of BVE stands still (pause / F1 menu)
                self.assertEqual([(p["category"], p["text"], p["expire_time"]) for p in s.o.popups], before)
                self.assertEqual(self.request_at(s, t, paused=True), [])
                self.assertEqual(self.request_at(s, t + 7000, paused=True), [], "a paused tick requests nothing, however late the time reads")
                self.assertEqual(len(self.request_at(s, t + 7000)), 1, "the request is held, not lost")

    def test_TB_DISP_R8_the_wall_clock_alone_never_triggers_the_jump(self):
        s, t = self.arrived("plain", 0.3)
        for _ in range(100):
            s.tick(advance_ms=0, wall_advance=60.0)                             # minutes of wall clock, no BVE time
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.request_at(s, s.o.bve_time_ms), [])
        self.assertEqual(s.machine.state, M.ARMED)

    def test_TB_DISP_R9_the_door_state_changes_neither_the_display_nor_the_jump(self):
        def run(door_script):
            s, t = self.arrived("stepwise", 0.3)
            seen = []
            for offset in (500, 1500, 2999, 3000, 4000, 4999, 5000):
                if offset in door_script:
                    s.o.bve_door, s.o.bve_doordir = door_script[offset]
                self.at(s, t, offset)
                seen.append((offset, sorted((p["category"], p["expire_time"] - t / 1000.0) for p in s.o.popups if p["type"] == "big"), bool(self.request_at(s, t + offset))))
            return seen
        baseline = run({})
        self.assertEqual(run({500: (0, 1), 1500: (1, 1), 4000: (0, 1)}), baseline, "doors closing and opening")
        self.assertEqual(run({500: (1, 0)}), baseline, "an operational-stop door direction")
        self.assertEqual(run({500: (1, 1), 1500: (1, 1)}), baseline, "a door that stays open")
        self.assertEqual([o for o, _p, req in baseline if req], [5000])

    def test_TB_DISP_R10_many_display_ticks_still_one_guidance_and_one_jump(self):
        for braking in ("plain", "stepwise"):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, 0.3)
                requests = 0
                max_guides = 0
                while s.o.bve_time_ms < t + 6000:
                    s.tick(advance_ms=16)
                    max_guides = max(max_guides, len(self.guides(s)))
                    requests += len(self.request_at(s, s.o.bve_time_ms))
                self.assertEqual(max_guides, 1)
                self.assertEqual(requests, 1)

    def test_TB_DISP_R11_jump_unavailable_sends_nothing_and_aborts_once_with_the_fixed_reason(self):
        s, t = self.arrived("stepwise", 0.3)
        self.assertEqual(self.request_at(s, t + 4999, jump_available=False), [])
        acts = self.request_at(s, t + 5000, jump_available=False)
        self.assertEqual(acts, [("abort_scoring_jump_unavailable", "pseudo-turnback-jump-unavailable")])
        self.assertEqual(M.JUMP_UNAVAILABLE_REASON, "pseudo-turnback-jump-unavailable")
        self.assertEqual(s.machine.state, M.FAILED)
        self.assertEqual(s.machine.display_state(t + 5000), M.DISPLAY_UNAVAILABLE_ABORT)
        for k in range(1, 100):
            self.assertEqual(self.request_at(s, t + 5000 + k * 16, jump_available=False), [], "no second abort, no request")
            self.assertEqual(self.request_at(s, t + 5000 + k * 16), [], "and an availability that comes back later does not resurrect the chain")
        self.assertNotIn("request_jump", [a[0] for a in self.request_at(s, t + 9000)])

    def test_TB_DISP_R12_the_no_special_route_is_never_split_into_three_plus_two(self):
        s, t = self.arrived("plain", 0.3)
        first = self.guides(s)[0]
        for offset in (1, 1000, 2999, 3000, 3001, 4999):
            self.at(s, t, offset)
            g = self.guides(s)
            self.assertEqual(len(g), 1, offset)
            self.assertIs(g[0], first, "the same guidance popup runs through the 3.0 s mark: no swap, no re-add")
            self.assertEqual(g[0]["expire_time"], t / 1000.0 + 5.0)
        self.assertEqual([p for p in s.o.popups if p["expire_time"] == t / 1000.0 + 3.0], [])


# ==============================================================================================================================================
# what the contract does NOT touch, and the identification of the special popup
# ==============================================================================================================================================
class E_Scope(Base):
    def test_the_plus_500_score_lines_keep_the_normal_five_seconds(self):
        s, t = self.arrived("stepwise", 0.0)
        pos = [p for p in s.o.popups if p["type"] == "pos"]
        self.assertTrue(pos)
        for p in pos:
            self.assertEqual(p["expire_time"], t / 1000.0 + 5.0, p["text"])

    def test_only_the_basic_braking_and_the_zero_cm_big_popups_are_special(self):
        S = self.S
        self.assertTrue(S.is_arrival_special_popup({"type": "big", "category": "基本制動", "text": "x"}))
        self.assertTrue(S.is_arrival_special_popup({"type": "big", "category": "ボーナス", "text": "x"}))
        for p in ({"type": "pos", "category": "基本制動"}, {"type": "pos", "category": "ボーナス"}, {"type": "big", "category": "警告"}, {"type": "big", "category": "終了"},
                  {"type": "big", "category": GUIDE}, {"type": "neg", "category": "初動ブレーキ"}, {"type": "big", "category": "停止位置"}):
            self.assertFalse(S.is_arrival_special_popup(p), p)

    def test_a_warning_is_never_clamped_by_the_arrival(self):
        s = self.P.Scene(self)
        s.approach("plain")
        s.stop_at(0.3)
        self.S.add_score_popup(s.o, 0, "警告", None, "big", "警告", s.o.bve_time_ms / 1000.0, force=True)
        warning = s.o.popups[-1]
        before = warning["expire_time"]
        s.open_door()
        self.assertEqual(warning["expire_time"], before)

    def test_a_station_that_is_not_a_pair_a_is_exactly_the_current_scoring(self):
        """No PairSet (the adapter of Stage TB-E has not published one): the special popup is the normal 5.0 s, there is no guidance, the checkpoint of the arrival is created."""
        s, t = self.arrived("stepwise", 0.0, with_pairs=False)
        for p in self.specials(s):
            self.assertEqual(p["expire_time"], t / 1000.0 + 5.0)
        self.assertEqual(self.guides(s), [])
        self.assertEqual(len(s.o.save_data), 2, "the normal arrival checkpoint of A")
        self.assertEqual(s.machine.state, M.IDLE)

    def test_scoring_off_the_display_does_not_intervene(self):
        s = self.P.Scene(self)
        s.o.is_scoring_mode = False
        s.approach("stepwise")
        s.stop_at(0.0)
        s.open_door()
        self.assertEqual((s.popups(), s.machine.state, len(s.o.save_data)), ([], M.IDLE, 1))

    def test_a_door_that_does_not_open_makes_no_arrival_event_so_no_chain_starts(self):
        """CHARACTERISATION (ledger E06, UNKNOWN): the arrival detection is the existing one (the door-open edge, or speed 0 with the door direction 0); a normal stop whose door never opens produces no
        arrival event, so no chain. The Owner's wording 'the door does not open: keep the recognition and the Jump' is reported as an open question (it needs an arrival trigger that does not exist)."""
        s = self.P.Scene(self)
        s.approach("plain")
        s.stop_at(0.3)
        s.step(400)
        self.assertEqual((s.machine.state, [p for p in s.o.popups if p["category"] == GUIDE]), (M.IDLE, []))

    def test_pause_does_not_move_the_chain_and_a_generation_change_ends_it(self):
        s, t = self.arrived("plain", 0.3)
        self.assertEqual(s.machine.tick(t + 9000, s.o.current_scenario_id + 1, True), [("discard_pending", "generation")])
        self.assertEqual(s.machine.tick(t + 9001, s.o.current_scenario_id, True), [])

    def test_the_end_of_the_scoring_after_the_arrival_ends_the_chain_without_a_request(self):
        s, t = self.arrived("plain", 0.3)
        self.assertEqual(s.machine.tick(t + 5000, s.o.current_scenario_id, False), [("discard_pending", "scoring-ended")])
        s, t = self.arrived("plain", 0.3)
        self.assertEqual(s.machine.on_scenario_close(), [("discard_pending", "world-reset")])
        self.assertEqual(s.machine.tick(t + 5000, s.o.current_scenario_id, True), [])

# ==============================================================================================================================================
# TB-DISP-R13 .. R15 and the wording of the guidance (Owner, 2026-10-31 second approval)
# ==============================================================================================================================================
class G_Extra(Base):
    def test_TB_DISP_R13_the_plus_500_pos_lines_keep_the_five_second_contract(self):
        for braking, err in (("plain", 0.3), ("stepwise", 0.3), ("plain", 0.0), ("stepwise", 0.0)):
            with self.subTest(braking=braking, err=err):
                s, t = self.arrived(braking, err)
                pos = [p for p in s.o.popups if p["type"] == "pos"]
                self.assertTrue(pos)
                for p in pos:
                    self.assertEqual(p["expire_time"], t / 1000.0 + 5.0, p["text"])
                self.at(s, t, 4999)
                self.assertTrue([p for p in s.o.popups if p["type"] == "pos"], "still shown at 4.999 s")
                self.at(s, t, 5000)
                self.assertEqual([p for p in s.o.popups if p["type"] == "pos" and p["expire_time"] > t / 1000.0 + 5.0], [])

    def test_TB_DISP_R14_two_special_popups_never_make_a_six_second_frame(self):
        s, t = self.arrived("stepwise", 0.0)
        self.assertEqual(len(self.specials(s)), 2)
        longest = 0
        while s.o.bve_time_ms < t + 7000:
            if self.specials(s):
                longest = s.o.bve_time_ms - t
            s.tick(advance_ms=16)
        self.assertLess(longest, 3000, "the last tick that still shows a special popup is before 3.000 s")
        self.assertGreaterEqual(longest, 2984 - 16)

    def test_TB_DISP_R15_the_display_switch_and_the_one_time_request_are_separate(self):
        # (a) a display that never happens (the update is a no-op) neither delays, nor skips, nor repeats the request
        for braking in ("plain", "stepwise"):
            with self.subTest(display="failed", braking=braking):
                s = self.P.Scene(self)
                s.approach(braking)
                s.stop_at(0.3)
                original = self.S.turnback_display_update
                self.S.turnback_display_update = lambda self_, current_time: None
                try:
                    t = s.open_door()
                    n = 0
                    while s.o.bve_time_ms < t + 6000:
                        s.tick(advance_ms=16)
                        n += len(self.request_at(s, s.o.bve_time_ms))
                    self.assertEqual(self.guides(s), [], "the guidance never appeared")
                    self.assertEqual(n, 1, "the request is made once, at 5.0 s, whatever the display did")
                finally:
                    self.S.turnback_display_update = original
        # (b) the display alone never requests: the request exists only where the machine's tick is called
        s, t = self.arrived("plain", 0.3)
        for _ in range(500):
            s.tick(advance_ms=16)
        self.assertEqual(s.machine.state, M.ARMED, "500 display ticks and no machine tick: nothing was requested")
        self.assertEqual(len(self.request_at(s, s.o.bve_time_ms)), 1)

    def test_OD_TB_16_the_guidance_names_none_of_the_internal_words(self):
        for word in ("jump", "ジャンプ", "transaction", "completion", "トランザクション", "完了通知"):
            self.assertNotIn(word, self.S.TURNBACK_GUIDANCE_TEXT.lower())
            self.assertNotIn(word, self.S.TURNBACK_GUIDANCE_CATEGORY.lower())
        self.assertEqual(self.S.TURNBACK_GUIDANCE_TEXT, "次の発車位置へ移動します")
        self.assertEqual(self.S.TURNBACK_GUIDANCE_CATEGORY, "疑似折り返し")
        s, t = self.arrived("plain", 0.3)
        self.assertEqual([p["text"] for p in self.guides(s)], ["次の発車位置へ移動します"])

class F_Static(unittest.TestCase):
    def test_the_machine_takes_no_door_signal_or_distance_parameter(self):
        import inspect
        import re
        for name in ("on_arrival", "a_scoring_complete", "tick", "display_phase", "display_state", "qualifying_pair"):
            fn = getattr(M.TurnbackMachine, name, None) or getattr(M, name)
            params = " ".join(inspect.signature(fn).parameters)
            self.assertIsNone(re.search(r"door|signal|flag|dist|name|loc(?!k)", params, re.I), (name, params))


if __name__ == "__main__":
    unittest.main()
