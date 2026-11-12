"""F2 Rollback Message Lifetime (Owner ruling of 2026-11-12; SEPARATE UI MESSAGE-LIFETIME DEFECT, NON-BLOCKING FOR POST-FINISH RETRY).

THE DEFECT: the F2 (developer) line "★ >>> <station> へロールバック完了 <<<" kept its deadline as BVE time (the BVE time of the Retry + 5 s). A new Run of the same scenario starts at an EARLIER BVE time, so the old
deadline was in the future again and the message of the previous Run was drawn again.

THE CONTRACT
  1  the message is shown for 5.0 REAL seconds from the moment it is set;
  2  the deadline is a time.monotonic() value (scoring_logic.rollback_clock), never BVE time / datetime / time.time;
  3  BVE time going back (a Jump, F5, a scenario reload, a new Run) never brings an expired message back, and BVE time going forward never removes it early;
  4  at a Run boundary the message is cleared AT ONCE: a new scoring Run, the abort of the scoring, a scenario change, a session change, a ScenarioGeneration change, Input Device OFF, the end of TS Scoring;
  5  a newer message REPLACES the older one and is shown 5.0 s from ITS own start; there is only ever one message (no queue);
  6  nothing else is added (no queue, history, fade, animation, close button, setting);
  7  F2 only: no new text in the ordinary HUD, F1 or the result screen. Retry, Jump, score, history, the result file and the frozen settings are not touched. The product log keeps its lines.
The 5 s are never slept: the monotonic clock is injected (scoring_logic.rollback_clock). Needs PyQt6 (skipped otherwise).
"""
import os
import re
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lc_legacy_feed as F  # noqa: E402
from pfr_rig import HAS_QT, PfrManaged, ROOT, read, scoring_snapshot  # noqa: E402

DEADLINE = "rollback_msg_deadline_monotonic"
MSG_KEYS = ("rollback_msg", DEADLINE, "rollback_msg_timer")


class RecordingPainter(object):
    """A real QPainter on an image whose drawText calls are recorded (the F2 lines are the strings of drawText)."""

    def __init__(self, painter):
        self._p = painter
        self.texts = []

    def drawText(self, *args):
        self.texts.append(args[-1])
        return self._p.drawText(*args)

    def __getattr__(self, name):
        return getattr(self._p, name)


class RollbackMessageCases:
    """The cases (a mixin: the two shapes below are the TestCases)."""
    capture_sink = False

    def setUp(self):
        super().setUp()
        self.now = [1000.0]
        patcher = mock.patch.object(self.S, "rollback_clock", lambda: self.now[0], create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- helpers ------------------------------------------------------------------------------------------------------------------------------------------------------
    def fresh(self):
        self.doCleanups()
        self.setUp()

    def f2_texts(self, show_graph=True):
        from PyQt6.QtGui import QImage, QPainter
        import hud_ui
        o = self.o
        o.show_graph = show_graph
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        recorder = RecordingPainter(painter)
        try:
            hud_ui.draw_hud(o, recorder, 1920)
        finally:
            painter.end()
        return recorder.texts

    def shown(self, name=None):
        lines = [t for t in self.f2_texts() if "ロールバック完了" in t]
        if name is not None:
            lines = [t for t in lines if name in t]
        return lines

    def say(self, name):
        """A message as execute_retry sets it (the same helper)."""
        self.S.set_rollback_message(self.o, ">>> %s へロールバック完了 <<<" % name)

    def finished(self):
        self.to_finish()

    def abort_via_menu(self):
        o, r = self.o, self.r
        r.tap("f1")
        o.menu_cursor = o.current_menu_items.index("採点を中断する")
        r.tap("enter")
        o.menu_cursor = 0
        r.tap("enter")

    def retry(self, position):
        o = self.o
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, position
        n = len(self.commands())
        o.handle_menu_enter(True)
        self.assertEqual(len(self.commands()), n + 1, "PREMISE the Retry was accepted")

    # -- RM-1 .. RM-3: the five real seconds --------------------------------------------------------------------------------------------------------------------------
    def test_RM01_the_message_is_shown_right_after_the_rollback_completed(self):
        self.finished()
        o = self.o
        self.now[0] = 1000.0
        self.retry(0)                                                     # a real Retry: execute_retry sets the message
        name = o.save_data[0]["station_name"]
        lines = self.shown()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("ロールバック完了", o.rollback_msg)
        self.assertIn(str(name), o.rollback_msg)
        self.assertEqual(getattr(o, DEADLINE), 1005.0, "the deadline is the monotonic clock + 5.0")

    def test_RM02_it_is_still_shown_at_4_999_seconds(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("B")
        self.now[0] = 1004.999
        self.assertEqual(len(self.shown("B")), 1)

    def test_RM03_it_is_not_shown_from_5_000_seconds_on_and_its_state_is_cleared(self):
        for dt in (5.0, 5.001, 60.0):
            with self.subTest(dt=dt):
                self.fresh()
                self.finished()
                self.now[0] = 1000.0
                self.say("B")
                self.now[0] = 1000.0 + dt
                self.assertEqual(self.shown(), [])
                self.assertEqual(self.o.rollback_msg, "", "an expired message must be cleared")
                self.assertEqual(getattr(self.o, DEADLINE), 0.0)

    # -- RM-4, RM-5, RM-14: BVE time does not matter -------------------------------------------------------------------------------------------------------------
    def test_RM04_bve_time_going_back_never_brings_an_expired_message_back(self):
        self.finished()
        o = self.o
        o.bve_time_ms = 36123000
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1006.0                                              # expired in real time
        for bve_ms in (36123000, 1000, 0, 36100000):                      # the same time, an earlier time (a new Run, F5, a Jump back)
            o.bve_time_ms = bve_ms
            self.assertEqual(self.shown(), [], "the message came back at BVE time %s" % bve_ms)

    def test_RM04b_an_expired_message_does_not_come_back_even_when_it_was_never_drawn_in_between(self):
        self.finished()
        o = self.o
        o.bve_time_ms = 36123000
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1100.0                                              # long expired, no draw
        o.bve_time_ms = 1000                                              # BVE time went back before the first draw
        self.assertEqual(self.shown(), [])

    def test_RM05_bve_time_going_forward_does_not_remove_it_early(self):
        self.finished()
        o = self.o
        o.bve_time_ms = 36123000
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1002.0
        for bve_ms in (36123000 + 3_600_000, 10 ** 9):
            o.bve_time_ms = bve_ms
            self.assertEqual(len(self.shown("CI03")), 1, "a BVE time jump removed the message early (%s)" % bve_ms)

    def test_RM14_an_old_message_is_never_drawn_again(self):
        self.finished()
        o = self.o
        self.now[0] = 1000.0
        self.say("CI02")
        self.now[0] = 1002.0
        self.say("CI03")
        self.now[0] = 1008.0                                              # both expired
        o.bve_time_ms = 0
        for _ in range(3):
            self.assertEqual(self.shown(), [])
            self.now[0] += 1.0

    # -- RM-6 .. RM-12: the boundaries clear AT ONCE ------------------------------------------------------------------------------------------------------------------
    def assert_cleared(self, what):
        o = self.o
        self.assertEqual(o.rollback_msg, "", what)
        self.assertEqual(getattr(o, DEADLINE), 0.0, what)
        self.assertEqual(self.shown(), [], what)

    def test_RM06_a_new_scoring_run_clears_it_at_once(self):
        r, o = self.r, self.o
        r.go_active(generation=1, **({"avail": F.LEGACY_AVAIL} if self.shape == "legacy" else {}))
        o.setting_end_idx = 2
        self.now[0] = 1000.0
        self.say("CI03")
        self.assertEqual(len(self.shown("CI03")), 1, "PREMISE the message is shown")
        self.now[0] = 1001.0                                              # 1 s, far from the 5 s
        r.start_scoring_via_menu()
        self.assertTrue(o.is_scoring_mode, "PREMISE the new Run started")
        self.assert_cleared("a new scoring Run")

    def test_RM07_the_abort_of_the_scoring_clears_it_at_once(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        self.abort_via_menu()
        self.assertFalse(self.o.is_scoring_mode, "PREMISE the scoring was aborted")
        self.assert_cleared("the abort of the scoring")

    def test_RM07b_an_unrecoverable_jump_failure_that_ends_the_scoring_clears_it_at_once(self):
        self.finished()
        o = self.o
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        o.is_official_jumping = True                                      # the abort path of an OPEN official jump (a stale one is no Run end)
        o._abort_unreleased_official_jump("timeout")
        self.assert_cleared("the abort of an unreleased official jump")

    def test_RM08_a_scenario_change_clears_it_at_once(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        self.o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")
        self.assert_cleared("a scenario change")

    def test_RM09_a_session_change_clears_it_at_once(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        self.r.input.on_inactive("state-lost")
        self.assert_cleared("a session change")

    def test_RM10_a_scenario_generation_change_clears_it_at_once(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        self.r.publish(True, True, 2)
        self.r.tick(4)
        self.assert_cleared("a ScenarioGeneration change")

    def test_RM11_input_device_off_clears_it_at_once(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        self.r.publish(False, False)
        self.r.tick(4)
        self.assert_cleared("Input Device OFF")

    def test_RM12_the_end_of_ts_scoring_leaves_no_state(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1001.0
        self.r.input.on_shutdown()
        self.assert_cleared("the end of TS Scoring")

    def test_RM12b_a_message_outside_a_boundary_keeps_its_five_seconds(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.now[0] = 1003.0
        self.r.tick(3, 0.1)                                               # ordinary ticks are no boundary
        self.assertEqual(len(self.shown("CI03")), 1)
        self.assertEqual(getattr(self.o, DEADLINE), 1005.0)

    # -- RM-13: a newer message replaces the older one ---------------------------------------------------------------------------------------------------------------
    def test_RM13_a_newer_message_replaces_the_older_and_gets_its_own_five_seconds(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI02")
        self.now[0] = 1002.0
        self.say("CI03")
        self.assertEqual(getattr(self.o, DEADLINE), 1007.0, "the new deadline is the start of the NEW message + 5.0")
        lines = self.shown()
        self.assertEqual(len(lines), 1, "only the latest message is shown (no queue): %r" % lines)
        self.assertIn("CI03", lines[0])
        self.assertNotIn("CI02", lines[0])
        self.now[0] = 1006.9
        self.assertEqual(len(self.shown("CI03")), 1, "the new message is shown for ITS five seconds")
        self.now[0] = 1007.0
        self.assertEqual(self.shown(), [])

    # -- RM-15: Current and Legacy are the same ------------------------------------------------------------------------------------------------------------------------
    def test_RM15_the_clock_and_the_helpers_are_one_for_both_shapes(self):
        S = self.S
        for name in ("set_rollback_message", "clear_rollback_message", "rollback_message_visible", "ROLLBACK_MESSAGE_SECONDS"):
            self.assertTrue(hasattr(S, name), name)
        self.assertEqual(S.ROLLBACK_MESSAGE_SECONDS, 5.0)
        src = read("scoring_logic.py")
        self.assertNotIn("shape", "".join(re.findall(r"def (?:set|clear)_rollback_message\(.*?\n(?=\ndef )", src, re.S)))

    # -- RM-16: nothing else is touched ----------------------------------------------------------------------------------------------------------------------------------
    def test_RM16_the_message_changes_no_retry_jump_score_or_history(self):
        self.finished()
        o = self.o
        self.now[0] = 1000.0
        self.retry(0)
        n_cmd = len(self.commands())
        snap = scoring_snapshot(o)
        cp = o.save_data[0]
        self.assertEqual(o.score, cp["score"])
        self.assertEqual(len(o.save_data), 2, "the history is cut by the completed Jump only")
        for t in (1001.0, 1004.999, 1005.0, 1500.0):                      # the message expires: the scoring state does not change
            self.now[0] = t
            self.shown()
        after = scoring_snapshot(o)
        changed = sorted(k for k in set(snap) | set(after) if snap.get(k) != after.get(k) and k not in MSG_KEYS + ("show_graph",))
        self.assertEqual(changed, [], "the lifetime of the message changed the state of the scoring")
        self.assertEqual(len(self.commands()), n_cmd)
        self.assertIsNotNone(o.retry_pending)
        src = read("scoring_logic.py")
        helpers = "".join(re.findall(r"def (?:set_rollback_message|clear_rollback_message|rollback_message_visible)\(.*?\n(?=\ndef )", src, re.S))
        self.assertTrue(helpers, "PREMISE the helpers exist")
        for forbidden in ("save_data", "score", "retry", "jump", "bve_time", "datetime", "time.time"):
            self.assertNotIn(forbidden, helpers, "the helpers touch %s" % forbidden)

    # -- RM-17: F2 only ---------------------------------------------------------------------------------------------------------------------------------------------------
    def test_RM17_only_the_f2_line_shows_it(self):
        self.finished()
        self.now[0] = 1000.0
        self.say("CI03")
        self.assertEqual(len(self.shown("CI03")), 1, "F2 on: shown")
        self.assertEqual([t for t in self.f2_texts(show_graph=False) if "ロールバック" in t], [], "F2 off: not shown in the ordinary HUD")
        users = {}
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".py"):
                text = read(name)
                if "rollback_msg" in text:
                    users[name] = text.count("rollback_msg")
        self.assertEqual(sorted(users), ["hud_ui.py", "main.py", "managed_input.py", "scoring_logic.py"], "a new place reads or writes the message: %r" % users)
        hud = read("hud_ui.py")
        self.assertEqual(len(re.findall(r"rollback", hud)), 3, "hud_ui draws the message in ONE place only")
        self.assertIn("rollback_message_visible(self)", hud)
        for name in ("menu_ui.py", "main.py"):
            self.assertNotIn("ロールバック完了", read(name).replace("# 前シナリオのロールバック通知を破棄", ""), name)

    # -- RM-18: the product log keeps its lines --------------------------------------------------------------------------------------------------------------------------
    def test_RM18_the_log_lines_of_the_rollback_stay_when_the_screen_message_ends(self):
        self.finished()
        self.now[0] = 1000.0
        self.retry(0)
        before = list(self.r.log.lines)
        self.assertTrue(self.lines_of("retry-accepted"), "PREMISE the retry-accepted line exists")
        self.now[0] = 1006.0
        self.shown()
        self.o.apply_telemetry_text("SCENARIO_ID:2,SPEED:0")                  # a boundary of the Run clears the screen message at once
        self.assertEqual(self.o.rollback_msg, "")
        self.assertEqual([l for l in self.r.log.lines if l in before], before, "a line of the log was removed")
        self.assertTrue(self.lines_of("retry-accepted"))

    # -- the clock itself ------------------------------------------------------------------------------------------------------------------------------------------------------
    def test_RM19_the_default_clock_is_time_monotonic(self):
        self.assertTrue(hasattr(self.S, "rollback_clock"))
        original = self.S.__dict__["rollback_clock"]
        # setUp replaced it by the injected clock: the module source names the monotonic clock
        self.assertRegex(read("scoring_logic.py"), r"(?m)^rollback_clock\s*=\s*time\.monotonic\s*$")
        self.assertNotRegex(read("hud_ui.py"), r"bve_time_ms\s*/\s*1000\.0\)\s*<\s*self\.rollback")
        self.assertTrue(callable(original))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class RollbackMessageLifetimeLegacy(RollbackMessageCases, PfrManaged):
    __test__ = True
    shape = "legacy"


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class RollbackMessageLifetimeCurrent(RollbackMessageCases, PfrManaged):
    __test__ = True
    shape = "current"


if __name__ == "__main__":
    unittest.main()
