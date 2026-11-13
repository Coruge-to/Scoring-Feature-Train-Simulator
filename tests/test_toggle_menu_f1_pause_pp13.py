"""Phase PP-13 - the ONE P that Python still posts is the F1 MENU's own pause / resume (Overlay.toggle_menu). It is a user-initiated operation screen control, nothing to
do with the removed P-to-P recovery (F5 / Input Device ON / kick start / Telemetry-ScenarioReady recovery). Pinned here:

  * toggle_menu is reached only from the menu's own entry points (the F1 key, the menu items, backspace, the refused scoring start, a retry from the menu) and from the
    result screen that opens when a scoring run has finished; never from a telemetry / state / epoch / pulse path;
  * opening posts at most one P, and only while BVE is running (BVE that was paused is never pressed); closing resumes only when the menu itself paused BVE;
  * F1 repeated quickly never posts two pausing Ps in a row, and a page change inside the menu posts nothing;
  * the managed end paths (session OFF, scenario end, Stop) close the menu quietly - no P (tests/test_managed_input_sia3.py, test_pause_ptop_width_sia4.py);
  * no other Python production function posts a P.
"""
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import test_characterization_sia1 as S1  # noqa: E402


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as stream:
        return stream.read()


class A_WhoMayReachIt(unittest.TestCase):
    ENTRY_POINTS = {
        ("main.py", "_on_f1"),                      # the F1 key
        ("main.py", "handle_menu_enter"),           # Enter on a menu item (resume, start, ...)
        ("main.py", "handle_menu_backspace"),       # Backspace in the menu
        ("main.py", "_refuse_scoring_start"),       # the user chose to start a scoring run and it was refused: the menu closes
        ("scoring_logic.py", "execute_retry"),      # a retry chosen in the menu
        ("scoring_logic.py", "update_result_display"),   # the result screen that opens after a scoring run has finished
    }

    def test_toggle_menu_is_called_only_from_the_menu_entry_points(self):
        found = set()
        for name in sorted(n for n in os.listdir(ROOT) if n.endswith(".py")):
            tree = ast.parse(read(name))
            for func in ast.walk(tree):
                if isinstance(func, ast.FunctionDef):
                    for call in ast.walk(func):
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "toggle_menu":
                            found.add((name, func.name))
        self.assertEqual(found, self.ENTRY_POINTS)

    def test_no_recovery_path_can_reach_it(self):
        # telemetry / state / epoch / HUD / receiver modules neither call it nor post a key
        for name in ("managed_hud.py", "managed_state.py", "managed_mode.py", "telemetry_gate.py", "telemetry_contract.py", "telemetry_dataplane_receiver.py", "network.py"):
            text = read(name)
            self.assertNotIn("toggle_menu", text, name)
            self.assertNotIn("PostMessage", text, name)

    def test_the_only_function_that_posts_a_p_is_toggle_menu(self):
        owners = set()
        for name in sorted(n for n in os.listdir(ROOT) if n.endswith(".py")):
            text = read(name)
            for func in ast.walk(ast.parse(text)):
                if isinstance(func, ast.FunctionDef) and "WM_KEYDOWN, 0x50" in (ast.get_source_segment(text, func) or ""):
                    owners.add((name, func.name))
        self.assertEqual(owners, {("main.py", "toggle_menu")})


class B_TheMenuPause(S1.Base):
    def test_a_running_bve_is_paused_by_one_p_and_resumed_by_one_p(self):
        self.tap("f1")
        self.assertEqual(len(self.posted_p()), 1)
        self.tap("f1")
        self.assertEqual(len(self.posted_p()), 2)

    def test_a_bve_that_was_paused_already_is_never_pressed(self):
        self.o.bve_actual_state = "PAUSED"
        self.tap("f1")
        self.assertEqual(self.posted_p(), [])
        self.tap("f1")
        self.assertEqual(self.posted_p(), [])                              # the menu did not pause it, so closing does not resume it

    def test_quick_repeated_f1_never_posts_two_pausing_ps_in_a_row(self):
        counts = []
        for _ in range(6):
            before = len(self.posted_p())
            self.tap("f1")
            counts.append(len(self.posted_p()) - before)
        self.assertTrue(all(c <= 1 for c in counts), counts)               # at most one P per F1
        self.assertEqual(self.o.menu_state, 0)                             # 6 taps: open, close, open, close, open, close
        self.assertEqual(len(self.posted_p()), 6)                          # alternating pause / resume, balanced

    def test_a_page_change_inside_the_menu_posts_nothing_more(self):
        self.tap("f1")
        before = len(self.posted_p())
        for key in ("down", "up", "down"):
            self.tap(key)
        self.assertEqual(len(self.posted_p()), before)

    def test_f1_is_user_only_a_telemetry_state_change_never_opens_the_menu(self):
        self.o.apply_telemetry_text("SCENARIO_ID:1,SPEED:0")
        self.o.bve_actual_state = "PAUSED"
        self.tick(5)
        self.assertEqual(self.o.menu_state, 0)
        self.assertEqual(self.posted_p(), [])


if __name__ == "__main__":
    unittest.main()
