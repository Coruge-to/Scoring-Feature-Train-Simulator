"""Phase UI-ALT-F4 (secondary defence): the controller's `_shown` flag must not outlive the real Overlay.

    C:\\Python314\\python.exe -B -m unittest discover -s tests -p "test_managed_hud_shown_reconcile.py" -v

OBS-3C (live): the Overlay became invisible and its native window was destroyed while `_shown` stayed True, so the HUD never came back. When the flag says "shown" and
the Overlay is not visible (or has no native window), the next ACTIVE tick shows it again by the usual steps. Never after the user's close request, never while the
process ends, bounded per ScenarioGeneration, nothing in the inactive modes.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import managed_hud as mh  # noqa: E402
import test_overlay_user_close_altf4 as uc  # noqa: E402


class A_Reconcile(uc.UserCase):
    def test_red09_a_shown_flag_over_an_invisible_overlay_is_shown_again_by_the_next_tick(self):
        shows = self.overlay.shows
        self.overlay.visible = False                                                  # the Overlay vanished (OBS-3C) - the flag still says "shown"
        self.assertTrue(self.hud.shown)
        self.pump(1)
        self.assertEqual(self.overlay.shows, shows + 1)
        self.assertTrue(self.overlay.visible)
        self.assertTrue(self.hud.shown)
        self.assertEqual(len(self.lines("hud-reconcile")), 1)
        self.assertIn("reason=overlay-not-visible", self.lines("hud-reconcile")[0])
        self.assertIn("n=1", self.lines("hud-reconcile")[0])
        self.assertEqual(self.hud.reconciles, 1)

    def test_red09b_the_usual_show_steps_run_owner_is_set_again_after_the_show(self):
        self.overlay.visible = False
        owner_calls = len(self.api.owner_calls)
        z_queries = self.api.z_queries
        self.pump(1)
        self.assertGreater(len(self.api.owner_calls), owner_calls)                    # _ensure_owner after the show (the fake show clears the owner like Qt)
        self.assertGreater(self.api.z_queries, z_queries)                             # _ensure_z_order for the hidden-to-visible transition
        self.assertEqual(len(self.lines("hud-show")), 2)

    def test_red09c_a_overlay_without_a_native_window_is_shown_again_too(self):
        shows = self.overlay.shows
        self.overlay.hwnd = 0
        self.pump(1)
        self.assertEqual(self.overlay.shows, shows + 1)
        self.assertEqual(len(self.lines("hud-reconcile")), 1)

    def test_a_healthy_overlay_is_never_touched(self):
        shows = self.overlay.shows
        self.pump(200)
        self.assertEqual((self.overlay.shows, self.hud.reconciles, self.lines("hud-reconcile")), (shows, 0, []))

    def test_red10_after_the_users_close_request_nothing_is_shown_again(self):
        self.hud.request_user_close()
        self.overlay.visible = False
        shows = self.overlay.shows
        self.pump(10)
        self.assertEqual((self.overlay.shows, self.hud.reconciles), (shows, 0))
        self.assertFalse(self.overlay.visible)

    def test_red10b_a_failed_request_is_still_the_users_close(self):
        self.overlay.post_works = False
        self.hud.request_user_close()
        self.overlay.visible = False
        self.pump(5)
        self.assertEqual(self.hud.reconciles, 0)

    def test_nothing_is_shown_again_while_the_process_ends(self):
        self.hud.set_stop_probe(lambda: True)
        self.overlay.visible = False
        self.pump(5)
        self.assertEqual(self.hud.reconciles, 0)

    def test_red11_inactive_modes_do_not_reconcile(self):
        for session, driving in ((True, False), (False, False)):
            self.setUp()
            self.publish(session, driving, 1)
            self.pump(2)
            self.assertFalse(self.hud.shown)
            shows = self.overlay.shows
            self.pump(20)
            self.assertEqual((self.overlay.shows, self.hud.reconciles), (shows, 0), (session, driving))

    def test_red11b_a_minimized_bve_does_not_reconcile(self):
        self.api.iconic = True
        self.pump(3)
        self.assertFalse(self.hud.shown)
        shows = self.overlay.shows
        self.pump(20)
        self.assertEqual((self.overlay.shows, self.hud.reconciles), (shows, 0))
        self.api.iconic = False
        self.pump(2)
        self.assertTrue(self.hud.shown)                                               # the ordinary show, not a reconcile
        self.assertEqual(self.hud.reconciles, 0)

    def test_red12_a_overlay_that_cannot_be_shown_is_retried_a_bounded_number_of_times_per_generation(self):
        self.overlay.show = lambda: setattr(self.overlay, "shows", self.overlay.shows + 1)        # show() that does not make it visible
        self.overlay.visible = False
        self.pump(100)
        self.assertEqual(self.hud.reconciles, mh.MAX_RECONCILES_PER_GENERATION)
        self.assertLessEqual(len(self.lines("hud-reconcile")), mh.INPUT_LINE_CAPS["hud-reconcile"])

    def test_red12b_a_new_generation_has_its_own_budget(self):
        self.overlay.show = lambda: setattr(self.overlay, "shows", self.overlay.shows + 1)
        self.overlay.visible = False
        self.pump(50)
        self.assertEqual(self.hud.reconciles, mh.MAX_RECONCILES_PER_GENERATION)
        self.publish(True, True, 2)                                                   # the next ScenarioGeneration
        self.pump(50)
        self.assertEqual(self.hud.reconciles, 2 * mh.MAX_RECONCILES_PER_GENERATION)

    def test_the_summary_line_only_when_something_was_reconciled(self):
        self.hud.shutdown()
        self.assertEqual(self.lines("hud-reconcile-summary"), [])
        self.setUp()
        self.overlay.visible = False
        self.pump(2)
        self.hud.shutdown()
        self.assertEqual(len(self.lines("hud-reconcile-summary")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
