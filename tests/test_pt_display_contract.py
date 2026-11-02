"""The ARRIVAL DISPLAY contract of the pseudo-turnback A (Owner, 2026-10-31): TB-DISP-R1 .. R12.

  case 1  no special popup (no basic braking achieved, no 0 cm stop):   arrival -> 5.0 s nothing -> guidance 5.0 s -> Jump request          (10.0 s in total)   [Stage TB-H 5b, on purpose; it was 5.0 s of guidance]
  case 2  a special popup (basic braking achieved and / or 0 cm stop):  arrival -> result popup 5.0 s (its normal time) -> guidance 5.0 s -> Jump request   (10.0 s in total)   [Stage TB-H 5b, on purpose; it was 3.0 s + 2.0 s]

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
        s = self.P.Scene(self, drive=False, **kw)
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
    """Stage TB-H 5b (on purpose): the FIRST window is 10.0 s. The arrival result popups (basic braking achieved / 0 cm stop) keep their normal 5.0 s (the old 3.0 s exception is gone); the guidance is shown from 5.0 s to 10.0 s with or
    without them; the Jump request is at 10.0 s. (The old contract was: no result -> guidance 0-5 s; result -> 3.0 s + guidance 2.0 s; request at 5.0 s.)"""

    def test_TB_DISP_R1_no_special_popup_five_quiet_seconds_then_the_guidance_then_one_jump(self):
        s, t = self.arrived("plain", 0.3)
        self.assertEqual(self.specials(s), [])
        self.assertEqual(self.guides(s), [], "Stage TB-H 5b: no result popup -> nothing is shown for the first 5.0 s")
        self.assertIsNone(s.machine.display_state(t))
        self.at(s, t, 4999)
        self.assertEqual(self.guides(s), [])
        self.at(s, t, 5000)
        self.assertEqual(len(self.guides(s)), 1, "the guidance starts at 5.0 s")
        self.assertEqual(self.guides(s)[0]["expire_time"], t / 1000.0 + 10.0)
        self.assertEqual(s.machine.display_state(t + 5000), M.DISPLAY_GUIDANCE)
        self.at(s, t, 9999)
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.request_at(s, t + 9999), [])
        self.at(s, t, 10000)
        self.assertEqual(self.guides(s), [], "the guidance ends where the request is made")
        acts = self.request_at(s, t + 10000)
        self.assertEqual([a[0] for a in acts], ["request_jump"])

    def test_TB_DISP_R2_basic_braking_five_seconds_then_five_seconds_of_guidance(self):
        s, t = self.arrived("stepwise", 0.3)
        sp = self.specials(s)
        self.assertEqual([p["category"] for p in sp], ["基本制動"])
        self.assertEqual(sp[0]["expire_time"], t / 1000.0 + 5.0, "the normal 5.0 s of every popup (no 3.0 s exception)")
        self.assertEqual(self.guides(s), [], "the guidance waits for the result popup")
        self.assertEqual(s.machine.display_state(t), M.DISPLAY_ARRIVAL_RESULT)
        self.at(s, t, 3000)
        self.assertEqual(len(self.specials(s)), 1, "still shown at 3.0 s")
        self.assertEqual(self.guides(s), [])
        self.at(s, t, 5000)
        self.assertEqual(self.specials(s), [])
        self.assertEqual(len(self.guides(s)), 1)
        self.assertEqual(self.guides(s)[0]["expire_time"], t / 1000.0 + 10.0, "5.0 s of guidance")
        self.at(s, t, 10000)
        self.assertEqual(self.guides(s), [])
        self.assertEqual([a[0] for a in self.request_at(s, t + 10000)], ["request_jump"])

    def test_TB_DISP_R3_zero_cm_stop_five_seconds_then_five_seconds_of_guidance(self):
        s, t = self.arrived("plain", 0.0)
        sp = self.specials(s)
        self.assertEqual([(p["category"], p["text"]) for p in sp], [("ボーナス", "0cm停車成功!!!")])
        self.assertEqual(sp[0]["expire_time"], t / 1000.0 + 5.0)
        self.assertEqual(self.guides(s), [])
        self.at(s, t, 5000)
        self.assertEqual((self.specials(s), len(self.guides(s))), ([], 1))
        self.at(s, t, 10000)
        self.assertEqual([a[0] for a in self.request_at(s, t + 10000)], ["request_jump"])

    def test_TB_DISP_R4_basic_braking_and_zero_cm_together_share_one_five_second_window(self):
        s, t = self.arrived("stepwise", 0.0)
        sp = self.specials(s)
        self.assertEqual(sorted(p["category"] for p in sp), ["ボーナス", "基本制動"])
        self.assertEqual([p["expire_time"] for p in sp], [t / 1000.0 + 5.0] * 2, "5.0 s in total, not 10.0 s")
        self.at(s, t, 4999)
        self.assertEqual(len(self.specials(s)), 2)
        self.assertEqual(self.guides(s), [])
        self.at(s, t, 5000)
        self.assertEqual(self.specials(s), [])
        self.assertEqual(len(self.guides(s)), 1)
        self.at(s, t, 10000)
        self.assertEqual(len(self.request_at(s, t + 10000)), 1)

    def test_TB_DISP_R5_4_999_s_is_the_result_5_000_s_is_guidance(self):
        for braking, err in (("stepwise", 0.3), ("plain", 0.0), ("stepwise", 0.0)):
            with self.subTest(braking=braking, err=err):
                s, t = self.arrived(braking, err)
                self.at(s, t, 4999)
                self.assertTrue(self.specials(s) and not self.guides(s))
                self.assertEqual(s.machine.display_state(t + 4999), M.DISPLAY_ARRIVAL_RESULT)
                self.at(s, t, 5000)
                self.assertTrue(not self.specials(s) and self.guides(s))
                self.assertEqual(s.machine.display_state(t + 5000), M.DISPLAY_GUIDANCE)

    def test_TB_DISP_R6_9_999_s_no_jump_10_000_s_one_jump(self):
        for braking, err in (("plain", 0.3), ("stepwise", 0.3), ("plain", 0.0), ("stepwise", 0.0)):
            with self.subTest(braking=braking, err=err):
                s, t = self.arrived(braking, err)
                self.assertEqual(self.request_at(s, t + 9999), [])
                self.assertEqual(s.machine.display_state(t + 9999), M.DISPLAY_GUIDANCE)
                self.assertEqual(s.machine.display_state(t + 10000), M.DISPLAY_REQUEST_READY)
                acts = self.request_at(s, t + 10000)
                self.assertEqual([a[0] for a in acts], ["request_jump"])
                self.assertEqual(acts[0][1]["target_index"], 2)
                self.assertEqual(s.machine.display_state(t + 10000), M.DISPLAY_REQUESTED)
                for k in range(1, 50):
                    self.assertEqual(self.request_at(s, t + 10000 + k * 16), [])

    def test_TB_DISP_R7_while_the_bve_clock_stands_still_the_display_does_not_advance(self):
        for braking, err in (("plain", 0.3), ("stepwise", 0.3)):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, err)
                before = [(p["category"], p["text"], p["expire_time"]) for p in s.o.popups]
                for _ in range(300):
                    s.tick(advance_ms=0, wall_advance=0.1)                      # the clock of BVE stands still (pause / F1 menu)
                self.assertEqual([(p["category"], p["text"], p["expire_time"]) for p in s.o.popups], before)
                self.assertEqual(self.request_at(s, t, paused=True), [])
                self.assertEqual(self.request_at(s, t + 12000, paused=True), [], "a paused tick requests nothing, however late the time reads")
                self.assertEqual(len(self.request_at(s, t + 12000)), 1, "the request is held, not lost")

    def test_TB_DISP_R8_the_wall_clock_alone_never_triggers_the_jump(self):
        s, t = self.arrived("stepwise", 0.3)
        for _ in range(100):
            s.tick(advance_ms=0, wall_advance=60.0)                             # minutes of wall clock, no BVE time
        self.assertEqual(len(self.specials(s)), 1)
        self.assertEqual(self.request_at(s, s.o.bve_time_ms), [])
        self.assertEqual(s.machine.state, M.ARMED)

    def test_TB_DISP_R9_the_door_state_changes_neither_the_display_nor_the_jump(self):
        def run(door_script):
            s, t = self.arrived("stepwise", 0.3)
            seen = []
            for offset in (500, 1500, 2999, 3000, 4999, 5000, 7000, 9999, 10000):
                if offset in door_script:
                    s.o.bve_door, s.o.bve_doordir = door_script[offset]
                self.at(s, t, offset)
                seen.append((offset, sorted((p["category"], p["expire_time"] - t / 1000.0) for p in s.o.popups if p["type"] == "big"), bool(self.request_at(s, t + offset))))
            return seen
        baseline = run({})
        self.assertEqual(run({500: (0, 1), 1500: (1, 1), 7000: (0, 1)}), baseline, "doors closing and opening")
        self.assertEqual(run({500: (1, 0)}), baseline, "an operational-stop door direction")
        self.assertEqual(run({500: (1, 1), 1500: (1, 1)}), baseline, "a door that stays open")
        self.assertEqual([o for o, _p, req in baseline if req], [10000])

    def test_TB_DISP_R10_many_display_ticks_still_one_guidance_and_one_jump(self):
        for braking in ("plain", "stepwise"):
            with self.subTest(braking=braking):
                s, t = self.arrived(braking, 0.3)
                requests = 0
                max_guides = 0
                while s.o.bve_time_ms < t + 11000:
                    s.tick(advance_ms=16)
                    max_guides = max(max_guides, len(self.guides(s)))
                    requests += len(self.request_at(s, s.o.bve_time_ms))
                self.assertEqual(max_guides, 1)
                self.assertEqual(requests, 1)

    def test_TB_DISP_R11_jump_unavailable_sends_nothing_and_aborts_once_with_the_fixed_reason(self):
        s, t = self.arrived("stepwise", 0.3)
        self.assertEqual(self.request_at(s, t + 9999, jump_available=False), [])
        acts = self.request_at(s, t + 10000, jump_available=False)
        self.assertEqual(acts, [("abort_scoring_jump_unavailable", "pseudo-turnback-jump-unavailable")])
        self.assertEqual(M.JUMP_UNAVAILABLE_REASON, "pseudo-turnback-jump-unavailable")
        self.assertEqual(s.machine.state, M.FAILED)
        self.assertEqual(s.machine.display_state(t + 10000), M.DISPLAY_UNAVAILABLE_ABORT)
        for k in range(1, 100):
            self.assertEqual(self.request_at(s, t + 10000 + k * 16, jump_available=False), [], "no second abort, no request")
            self.assertEqual(self.request_at(s, t + 10000 + k * 16), [], "and an availability that comes back later does not resurrect the chain")
        self.assertNotIn("request_jump", [a[0] for a in self.request_at(s, t + 14000)])

    def test_TB_DISP_R12_the_guidance_is_never_split_and_never_re_added(self):
        s, t = self.arrived("plain", 0.3)
        self.at(s, t, 5000)
        first = self.guides(s)[0]
        for offset in (5001, 6000, 7500, 9000, 9999):
            self.at(s, t, offset)
            g = self.guides(s)
            self.assertEqual(len(g), 1, offset)
            self.assertIs(g[0], first, "the same guidance popup runs through the window: no swap, no re-add")
            self.assertEqual(g[0]["expire_time"], t / 1000.0 + 10.0)
        self.assertEqual([p for p in s.o.popups if p["expire_time"] in (t / 1000.0 + 3.0,)], [])


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
        s = self.P.Scene(self, drive=False)
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
        s = self.P.Scene(self, drive=False)
        s.o.is_scoring_mode = False
        s.approach("stepwise")
        s.stop_at(0.0)
        s.open_door()
        self.assertEqual((s.popups(), s.machine.state, len(s.o.save_data)), ([], M.IDLE, 1))

    def test_a_door_that_does_not_open_makes_no_arrival_event_so_no_chain_starts(self):
        """CHARACTERISATION (ledger E06, UNKNOWN): the arrival detection is the existing one (the door-open edge, or speed 0 with the door direction 0); a normal stop whose door never opens produces no
        arrival event, so no chain. The Owner's wording 'the door does not open: keep the recognition and the Jump' is reported as an open question (it needs an arrival trigger that does not exist)."""
        s = self.P.Scene(self, drive=False)
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

    def test_TB_DISP_R14_two_special_popups_never_make_a_ten_second_frame(self):
        s, t = self.arrived("stepwise", 0.0)
        self.assertEqual(len(self.specials(s)), 2)
        longest = 0
        while s.o.bve_time_ms < t + 12000:
            if self.specials(s):
                longest = s.o.bve_time_ms - t
            s.tick(advance_ms=16)
        self.assertLess(longest, 5000, "Stage TB-H 5b (on purpose): the last tick that still shows a result popup is before 5.000 s (it was 3.000 s)")
        self.assertGreaterEqual(longest, 4984 - 16)

    def test_TB_DISP_R15_the_display_switch_and_the_one_time_request_are_separate(self):
        # (a) a display that never happens (the update is a no-op) neither delays, nor skips, nor repeats the request
        for braking in ("plain", "stepwise"):
            with self.subTest(display="failed", braking=braking):
                s = self.P.Scene(self, drive=False)
                s.approach(braking)
                s.stop_at(0.3)
                original = self.S.turnback_display_update
                self.S.turnback_display_update = lambda self_, current_time: None
                try:
                    t = s.open_door()
                    n = 0
                    while s.o.bve_time_ms < t + 11000:
                        s.tick(advance_ms=16)
                        n += len(self.request_at(s, s.o.bve_time_ms))
                    self.assertEqual(self.guides(s), [], "the guidance never appeared")
                    self.assertEqual(n, 1, "the request is made once, at 10.0 s (Stage TB-H 5b, on purpose; it was 5.0 s), whatever the display did")
                finally:
                    self.S.turnback_display_update = original
        # (b) the display alone never requests: the request exists only where the machine's tick is called
        s, t = self.arrived("plain", 0.3)
        for _ in range(800):                                          # Stage TB-H 5b (on purpose): 12.8 s of display ticks (the request is at 10.0 s; it was 500 ticks = 8.0 s for 5.0 s)
            s.tick(advance_ms=16)
        self.assertEqual(s.machine.state, M.ARMED, "800 display ticks and no machine tick: nothing was requested")
        self.assertEqual(len(self.request_at(s, s.o.bve_time_ms)), 1)

    def test_OD_TB_16_the_guidance_names_none_of_the_internal_words(self):
        # Stage TB-H (A re-stop wait; on purpose): Owner ruling R7 (C-01 retest Close, 2026-11-01) changes the first guidance line from the old 'next departure position' text; the other words and the rules of this test are unchanged
        for word in ("jump", "ジャンプ", "transaction", "completion", "トランザクション", "完了通知"):
            self.assertNotIn(word, self.S.TURNBACK_GUIDANCE_TEXT.lower())
            self.assertNotIn(word, self.S.TURNBACK_GUIDANCE_CATEGORY.lower())
        self.assertEqual(self.S.TURNBACK_GUIDANCE_TEXT, "発車位置へ移動します。")
        self.assertEqual(self.S.TURNBACK_GUIDANCE_CATEGORY, "疑似折り返し")
        s, t = self.arrived("plain", 0.3)
        self.at(s, t, 5000)                                          # Stage TB-H 5b (on purpose): the guidance of the first window is shown from 5.0 s
        self.assertEqual([p["text"] for p in self.guides(s)], ["発車位置へ移動します。"])

    def test_TB_STYLE_the_guidance_ends_with_one_full_stop_and_has_the_colour_of_the_farewell(self):
        """Style commit (Owner OD-C01-FIX-2): the text ends with exactly one '。' and the popup is drawn as '運転お疲れ様でした。' is: COLOR_WHITE, 'big', the black outline of utils.get_outline_color."""
        import ast
        import config
        import utils
        text = self.S.TURNBACK_GUIDANCE_TEXT
        self.assertEqual(text, "発車位置へ移動します。")
        self.assertEqual(text.count("。"), 1)
        self.assertTrue(text.endswith("。"))
        s, t = self.arrived("plain", 0.3)
        self.at(s, t, 5000)                                          # Stage TB-H 5b (on purpose): the guidance of the first window is shown from 5.0 s
        guides = self.guides(s)
        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0]["color"], config.COLOR_WHITE)
        self.assertEqual(guides[0]["type"], "big")
        self.assertEqual(utils.get_outline_color(guides[0]["color"]), config.COLOR_OUTLINE_BLACK, "white letters with a black outline, not black letters")
        with open(os.path.join(ROOT, "scoring_logic.py"), encoding="utf-8") as f:
            source = f.read()
        calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "add_score_popup"
                 and any(isinstance(a, ast.Constant) and a.value == "運転お疲れ様でした。" for a in n.args)]
        self.assertEqual(len(calls), 1)
        farewell_colour = ast.unparse(calls[0].args[3])
        self.assertEqual(farewell_colour, "COLOR_WHITE")
        self.assertEqual(guides[0]["color"], getattr(config, farewell_colour), "the same colour setting as the farewell")
        self.assertNotIn('"次の発車位置へ移動します"', source, "no old wording without the full stop is left in the scoring source")

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
