"""Post-Finish Retry Recovery, Stage PFR-D - the Retry diagnostics get a budget of their own (Owner ruling OD-PF-2, option D2).

THE PROBLEM
  ManagedInputController.note writes at most TOTAL_LINE_BUDGET = 70 `[MANAGED]` lines per Python process (and at most EVENT_LINE_CAP per event name). A long run uses the 70 up (the field run of
  2026-11-12: 182 lines suppressed from 20:00), so the line of a refused Retry (`retry-rejected why=...`) never reached the log and the cause of a Retry that did nothing was invisible.

THE CONTRACT
  1. The Retry events retry-confirm-entered, retry-accepted, retry-rejected (why=<reason>), retry-request-created and retry-exception (type=<exception type>) are IMPORTANT: they are written
     even when the 70 lines of the normal budget are spent, and they do not use any of them;
  2. they have a budget of their own: IMPORTANT_LINE_CAP = 40 lines per process (every name, together); the 41st is dropped and ONE `important-summary` line says so; never unbounded;
  3. the normal budget is untouched (70, EVENT_LINE_CAPS and EVENT_LINE_CAP are the same) and the closing input-summary counts the important lines (imp=, imp_dropped=);
  4. a Retry that raises is reported (retry-exception type=...) and the exception is NOT swallowed (the behaviour of the application does not change);
  5. entering the confirmation page writes retry-confirm-entered; an accepted Retry writes retry-accepted and retry-request-created; the jump client's own lines (jump-command-sent,
     jump-complete-accepted/-rejected, jump-send-refused, jump-timeout, jump-request-cancelled; they never used the 70) are not changed;
  6. every line fits the 160 characters the Caller keeps and names no path; the same code runs for the Current and the Legacy shape of the feed (no sender name is read);
  7. the sum of the lines of this controller (70 + 40 + the summary) leaves room in the 200 lines the Caller copies per process.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pfr_rig import PfrManaged, read  # noqa: E402

IMPORTANT = ("retry-confirm-entered", "retry-accepted", "retry-rejected", "retry-request-created", "retry-exception")


class RetryDiagnostics(PfrManaged):
    def spend_the_normal_budget(self):
        c = self.r.input
        for name in ("stidx", "input-hold", "stidx-sum", "stidx-identity", "routepairset", "window-fullscreen", "input-pause", "input-resume"):
            for _ in range(30):
                c.note(name, n=1)
        self.assertEqual(c._total, c.TOTAL_LINE_BUDGET, "PREMISE the 70 lines of the normal budget are spent")
        self.assertGreater(c.suppressed, 0)

    def test_D01_a_refusal_is_logged_after_the_70_lines_are_spent(self):
        self.r.go_active()
        self.spend_the_normal_budget()
        self.r.input.note("retry-rejected", why="scoring-finished", pos=22)
        self.assertEqual(len(self.lines_of("retry-rejected")), 1)
        self.assertIn("why=scoring-finished", self.lines_of("retry-rejected")[0])

    def test_D02_every_important_event_bypasses_the_normal_budget_and_the_per_name_cap(self):
        self.r.go_active()
        self.spend_the_normal_budget()
        for name in IMPORTANT:
            n = 12 if name == "retry-rejected" else 5                # (the per-name cap of the normal lines is EVENT_LINE_CAP = 10; 12 + 4 * 5 = 32 <= 40)
            for k in range(n):
                self.r.input.note(name, n=k)
            self.assertEqual(len(self.lines_of(name)), n, name)

    def test_D03_the_important_budget_is_40_and_one_summary_says_so(self):
        self.r.go_active()
        c = self.r.input
        self.assertEqual(c.IMPORTANT_LINE_CAP, 40)
        for k in range(55):
            c.note("retry-rejected", why="x", n=k)
        self.assertEqual(len(self.lines_of("retry-rejected")), 40)
        summary = self.lines_of("important-summary")
        self.assertEqual(len(summary), 1, summary)
        self.assertIn("cap=40", summary[0])
        for k in range(20):
            c.note("retry-accepted", n=k)
        self.assertEqual(len(self.lines_of("retry-accepted")), 0)
        self.assertEqual(len(self.lines_of("important-summary")), 1, "the summary is written once")

    def test_D04_the_important_lines_use_none_of_the_normal_budget(self):
        self.r.go_active()
        c = self.r.input
        base = c._total
        for k in range(30):
            c.note("retry-rejected", why="x", n=k)
        self.assertEqual(c._total, base, "an important line used the normal budget")
        for name in ("stidx", "input-hold", "stidx-sum", "stidx-identity", "routepairset", "window-fullscreen", "input-pause", "input-resume"):
            for _ in range(30):
                c.note(name, n=1)
        self.assertEqual(c._total, c.TOTAL_LINE_BUDGET, "the normal budget lost lines to the important ones")

    def test_D05_the_normal_budget_is_unchanged(self):
        MI = self.MI
        self.assertEqual((MI.ManagedInputController.EVENT_LINE_CAP, MI.ManagedInputController.TOTAL_LINE_BUDGET), (10, 70))
        self.assertEqual(MI.ManagedInputController.EVENT_LINE_CAPS, {"input-hold": 24, "input-pause": 6, "input-resume": 6, "stidx": 24, "jump-settled": 24})
        for name in IMPORTANT:
            self.assertNotIn(name, MI.ManagedInputController.EVENT_LINE_CAPS)

    def test_D06_the_lines_fit_the_caller_and_name_no_path(self):
        self.r.go_active()
        c = self.r.input
        c.note("retry-rejected", why="location-mismatch", pos=22, idx=22, h="23/23", c="0/0", pend="none", cur="6180992:BE6488BB:24", loc="25338.00/25338.00")
        c.note("retry-exception", type="RuntimeError")
        for name in ("retry-rejected", "retry-exception"):
            line = self.lines_of(name)[0]
            self.assertLessEqual(len(line), 160, line)
            self.assertNotIn("\\", line)
            self.assertNotIn(":/", line)

    def test_D07_the_input_summary_counts_the_important_lines(self):
        self.r.go_active()
        c = self.r.input
        for k in range(43):
            c.note("retry-rejected", why="x", n=k)
        self.r.hud.shutdown()
        line = self.r.events("input-summary")[0]
        self.assertIn("imp=40", line)
        self.assertIn("imp_dropped=3", line)
        self.assertLessEqual(len(line), 160, line)

    def test_D08_the_budget_sum_leaves_room_in_the_callers_200_lines(self):
        c = self.MI.ManagedInputController
        self.assertLessEqual(c.TOTAL_LINE_BUDGET + c.IMPORTANT_LINE_CAP + 1, 200 - 24 - 8)        # (+ the summary line; 24 jump lines of the client; 8 of the closing/summary lines)

    # -- the application side -------------------------------------------------------------------------------------------------------------------------------
    def test_D10_entering_the_confirmation_page_writes_retry_confirm_entered(self):
        self.to_b()
        o = self.o
        self.spend_the_normal_budget()
        o.menu_state, o.menu_cursor = 2, 0
        self.assertGreaterEqual(len(o.save_data), 1)
        o.handle_menu_enter(True)
        self.assertEqual(o.menu_state, 3)
        lines = self.lines_of("retry-confirm-entered")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("pos=0", lines[0])

    def test_D11_an_accepted_retry_writes_accepted_and_request_created_after_the_70_lines(self):
        self.to_b()
        o = self.o
        self.spend_the_normal_budget()
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        n_cmd = len(self.commands())
        o.handle_menu_enter(True)
        self.assertEqual(len(self.commands()), n_cmd + 1, "PREMISE the Retry was accepted")
        self.assertEqual(len(self.lines_of("retry-accepted")), 1)
        created = self.lines_of("retry-request-created")
        self.assertEqual(len(created), 1, created)
        self.assertIn("pos=0", created[0])
        self.assertLessEqual(len(created[0]), 160)

    def test_D12_a_refused_retry_writes_the_reason_after_the_70_lines(self):
        self.to_b()
        o = self.o
        self.spend_the_normal_budget()
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 99
        o.handle_menu_enter(True)
        lines = self.lines_of("retry-rejected")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("why=no-checkpoint", lines[0])

    def test_D13_an_exception_of_the_retry_is_reported_and_not_swallowed(self):
        self.to_b()
        o, main = self.o, self.main
        o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 0
        original = main.execute_retry

        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        main.execute_retry = boom
        try:
            with self.assertRaises(RuntimeError):
                o.handle_menu_enter(True)
        finally:
            main.execute_retry = original
        lines = self.lines_of("retry-exception")
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("type=RuntimeError", lines[0])
        self.assertNotIn("boom", lines[0])

    def test_D14_the_jump_clients_lines_are_issued_outside_the_70_and_are_not_changed(self):
        """GUARD: _managed_jump_log (PID-D6) writes the jump client's lines straight to the log, a bounded number (24); they never passed through the note budget."""
        out = []

        class Args(object):
            instance, owner, bve_pid = "abc", "caller", 4242
        emit = self.main._managed_jump_log(out.append, Args)
        emit("[JUMP] event=command-sent id=ab12cd34 type=0x100 port=41000 gen=11")
        emit("[JUMP] event=send-refused reason=jump-directory-missing")
        emit("[JUMP] event=complete-accepted id=ab12cd34")
        names = [l.split()[1] for l in out]
        self.assertEqual(names, ["event=jump-command-sent", "event=jump-send-refused", "event=jump-complete-accepted"])
        for _ in range(40):
            emit("[JUMP] event=timeout id=ab12cd34")
        self.assertLessEqual(len(out), 25, "the client's lines are bounded")

class RetryDiagnosticsCurrent(RetryDiagnostics):
    shape = "current"


class StaticContract(unittest.TestCase):
    def test_D20_the_important_names_are_listed_in_the_controller_and_no_sender_name_is_read(self):
        text = read("managed_input.py")
        for name in IMPORTANT:
            self.assertIn('"%s"' % name, text, name)
        self.assertIn("IMPORTANT_LINE_CAP = 40", text)
        self.assertNotIn("legacy", text.lower().split("class managedinputcontroller")[1].split("def step")[0], "a sender name is read by the diagnostics")


if __name__ == "__main__":
    unittest.main()
