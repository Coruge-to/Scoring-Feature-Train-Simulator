"""Phase LC-4 (Legacy scoring integration) - a Retry after the scoring finished, REVERSED by Post-Finish Retry Recovery (PFR-R, Owner ruling 2026-11-12).

HISTORY (the contract ledger of the reversal)
  LC-4 (commit 0957634, C-SIDX-4 / LC-A13) made execute_retry refuse EVERY Retry once is_scoring_finished was set (reason `scoring-finished`), changed nothing, and left the confirmation page on the screen
  (RF01..RF09). That was a REQUIREMENT REGRESSION - the original contract (execute_retry has cleared is_scoring_finished since 2026-04-05; the menu offers 「選択した駅からやり直す」 next to 「採点結果を表示する」
  after the finish) is: after the finish - the result may be shown and SAVED - a Retry rewinds the same Run to the chosen check point and the scoring runs on from there.
  Owner ruling: OWNER REQUIREMENT DRIFT CAUSED BY INCOMPLETE CONTEXT (the LC-4 start instruction asked for the refusal; the context that was missing is in docs 02/03/10 of the investigation).

  old RF01  every Retry after the finish was refused (`scoring-finished`)                 -> RF01 a Retry after the finish is ACCEPTED like one before it (the ST-2 refusals stay for the rest)
  old RF02  the refusal changed and sent nothing                                          -> RF02 the accepted Retry sends ONE Jump request and rewinds the state (docs 04/06)
  old RF03  the scoring did not restart, the HUD kept the result state                    -> RF03 the finish state is released and the scoring owns the HUD target again
  old RF04  from the menu: ONE refusal line, the confirmation page stays                  -> RF04 from the menu: the page closes, retry-accepted + retry-request-created, no refusal
  old RF05  the refusal keeps no state, a new session can Retry                           -> RF05 (kept) a Retry after an explicit abort and a new start is accepted; RF05b (kept) after F5 nothing is left
  old RF06  a Retry before the finish is untouched                                        -> RF06 (kept)
  old RF07  Pause does not change the (refused) answer                                    -> RF07 a Pause does not change the (accepted) answer
  old RF08  the word `scoring-finished` is a literal of execute_retry                     -> RF08 the word is GONE; the ST-2 words of station_identity are untouched
  old RF09  the refusal is the FIRST statement of execute_retry                           -> RF09 the first statement of execute_retry is NOT a finish refusal
The full contract of the restored behaviour (PR-1..PR-30) is tests/test_pfr_r_post_finish_retry.py. Needs PyQt6 (skipped otherwise).
"""
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lc_legacy_feed as F  # noqa: E402
from pfr_rig import PfrManaged, read, scoring_snapshot  # noqa: E402

OLD_WORD = "scoring-finished"


class RetryAfterFinish(PfrManaged):
    shape = "legacy"

    def test_RF01_a_retry_after_the_finish_is_accepted_and_the_st2_refusals_stay(self):
        self.to_finish()
        o = self.o
        n_cmd = len(self.commands())
        res = self.main.execute_retry(o, 0, False)
        self.assertIsInstance(res, self.SI.RetryResult)
        self.assertTrue(res.accepted, "refused after the finish (reason=%r)" % (res.reason,))
        self.assertIsNotNone(res.request_id)
        self.assertEqual(len(self.commands()), n_cmd + 1)

    def test_RF01b_a_position_that_does_not_exist_is_refused_for_the_st2_reason_not_for_the_finish(self):
        self.to_finish()
        for position in (99, -1):
            res = self.main.execute_retry(self.o, position, False)
            self.assertFalse(res.accepted)
            self.assertEqual(res.reason, "no-checkpoint", "position %r" % position)

    def test_RF02_the_accepted_retry_sends_one_jump_request_and_rewinds_the_state(self):
        self.to_finish()
        o = self.o
        cp = o.save_data[1]
        n_cmd = len(self.commands())
        self.main.execute_retry(o, 1, True)
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertEqual(o.score, cp["score"])
        self.assertEqual(o.score_details, cp["score_details"])
        self.assertTrue(o.is_official_jumping)
        self.assertIsNotNone(o.retry_pending)

    def test_RF03_the_finish_state_is_released_and_the_scoring_owns_the_hud_target_again(self):
        self.to_finish()
        o = self.o
        self.assertFalse(self.HT.owner_is_scoring(o.is_scoring_mode, o.is_scoring_finished), "PREMISE the finished scoring does not own the HUD target")
        self.main.execute_retry(o, 0, True)
        self.assertFalse(o.is_scoring_finished)
        self.assertTrue(self.HT.owner_is_scoring(o.is_scoring_mode, o.is_scoring_finished))

    def test_RF04_from_the_menu_the_page_closes_and_the_retry_is_traced(self):
        self.to_finish()
        o = self.o
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        n_cmd = len(self.commands())
        o.handle_menu_enter(True)
        self.assertEqual(o.menu_state, 0, "the confirmation page stayed")
        self.assertEqual(len(self.commands()), n_cmd + 1)
        self.assertEqual(len(self.lines_of("retry-accepted")), 1)
        self.assertEqual(len(self.lines_of("retry-request-created")), 1)
        self.assertEqual(self.lines_of("retry-rejected"), [])

    def test_RF05_after_an_explicit_abort_and_a_new_start_a_retry_is_accepted(self):
        self.to_finish()
        o, r = self.o, self.r
        r.tap("f1")
        o.menu_cursor = o.current_menu_items.index("採点を中断する")
        r.tap("enter")
        o.menu_cursor = 0
        r.tap("enter")
        self.assertEqual((o.is_scoring_mode, o.is_scoring_finished, o.menu_state), (False, False, 0))
        r.start_scoring_via_menu()
        cmd = r.last_command()
        t = self.land(cmd, jump=2)
        self.leg(t, 100.0, 1000.0, 1000.0, 1, 1, 1, jump=2)
        self.assertFalse(o.is_scoring_finished)
        n_cmd = len(self.commands())
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(len(self.commands()), n_cmd + 1)

    def test_RF05b_after_a_new_generation_there_is_nothing_to_retry(self):
        self.to_finish()
        self.r.publish(True, True, 2)
        self.r.tick(4)
        o = self.o
        self.assertFalse(o.is_scoring_mode)
        self.assertFalse(o.is_scoring_finished)
        self.assertEqual(len(o.save_data), 0)
        res = self.main.execute_retry(o, 0, False)
        self.assertEqual((res.accepted, res.reason), (False, "no-checkpoint"))

    def test_RF06_a_retry_before_the_finish_is_untouched(self):
        self.to_b()
        o = self.o
        self.assertFalse(o.is_scoring_finished)
        n_cmd, n_hist = len(self.commands()), len(o.save_data)
        res = self.main.execute_retry(o, 99, False)
        self.assertFalse(res.accepted)
        self.assertNotEqual(res.reason, OLD_WORD)
        res = self.main.execute_retry(o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual((len(self.commands()), len(o.save_data), o.is_official_jumping), (n_cmd + 1, n_hist, True))
        self.assertIsNotNone(o.retry_pending)

    def test_RF07_a_pause_does_not_change_the_answer(self):
        self.to_finish()
        self.r.publish(True, False)                                   # Pause
        self.r.tick(5, 1.0)
        n_cmd = len(self.commands())
        res = self.main.execute_retry(self.o, 0, False)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(len(self.commands()), n_cmd + 1)


class RetryAfterFinishCurrent(RetryAfterFinish):
    shape = "current"


class StaticContract(unittest.TestCase):
    def test_RF08_the_old_word_is_gone_and_the_st2_words_are_untouched(self):
        import station_identity as SI
        self.assertEqual(SI.RETRY_REASONS, ("no-checkpoint", "old-form", "retry-pending", "jump-unavailable", "time-invalid"))
        self.assertNotIn(OLD_WORD, read("scoring_logic.py"))
        self.assertNotIn(OLD_WORD, read("station_identity.py"))
        self.assertNotIn(OLD_WORD, SI.REASONS)

    def test_RF09_the_first_statement_of_execute_retry_is_not_a_finish_refusal(self):
        tree = ast.parse(read("scoring_logic.py"))
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry"][0]
        body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        first = body[0]
        refuses = isinstance(first, ast.If) and "is_scoring_finished" in ast.unparse(first.test) and any(isinstance(n, ast.Return) for n in first.body)
        self.assertFalse(refuses, "execute_retry refuses a finished scoring before anything else")


if __name__ == "__main__":
    unittest.main()
