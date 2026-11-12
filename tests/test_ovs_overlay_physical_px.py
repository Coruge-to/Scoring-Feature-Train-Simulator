"""Phase OVS-1: the Overlay is placed and hit-tested in Win32 PHYSICAL pixels (OVS-R1 .. OVS-R18).

Root (OVS-0, confirmed on the real Windows 2026-11-13 at 100/125/150/175 %): the physical BVE client rectangle was handed to Qt's logical setGeometry, Qt applied the
display scale a second time, so the Overlay was client x DPR (HUD / F1 spilled out of the BVE window) and F1 clicks used a logical geometry with a physical cursor.

Real-Windows part: a REAL main.Overlay on the real Qt platform in a child process at QT_SCALE_FACTOR 1.0 / 1.25 / 1.5 / 1.75 (the same Qt DPR path as the OS scale).
The window is never shown. Run with python -B (python -I hides PyQt6); do not set QT_QPA_PLATFORM in the parent."""
import ast
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
CHILD = os.path.join(HERE, "ovs_dpr_child.py")
DPRS = ("1.0", "1.25", "1.5", "1.75")
BASE_W, BASE_H = 1920.0, 1080.0


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def segment(src, qualname):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and node.name + "." + item.name == qualname:
                    return ast.get_source_segment(src, item)
    raise AssertionError("no " + qualname)


def child(mode, rects, dpr, menu_state=0):
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    env["QT_SCALE_FACTOR"] = dpr
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    run = subprocess.run([sys.executable, "-B", CHILD, mode, json.dumps(rects), str(menu_state)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120, cwd=ROOT)
    lines = [l for l in run.stdout.splitlines() if l.startswith("{")]
    if not lines:
        raise AssertionError("child failed rc=%s: %s %s" % (run.returncode, run.stdout[-400:], run.stderr[-600:]))
    return json.loads(lines[-1])


# the BVE client rectangles: windowed (origin != 0), small, FHD, WQHD, 4K, 4:3, 21:9, a second monitor (x >= 1920)
RECTS = ([328, 187, 1264, 681], [0, 0, 1920, 1080], [10, 20, 918, 627], [100, 50, 2560, 1440], [0, 0, 3840, 2160], [200, 100, 1600, 1200], [1920, 0, 2560, 1080], [2300, 140, 1280, 720])


class Pure(unittest.TestCase):
    """OVS-R5 / R9 / R10 / R14: the pure transform, against the formulas that existed before OVS-1 (golden)."""

    @staticmethod
    def old_click(cursor, geom):
        """verbatim the pre-OVS-1 formula of Overlay._handle_mouse (geom = the widget geometry), the golden reference"""
        x, y, w, h = geom
        menu_scale = min(w / BASE_W, h / BASE_H)
        offset_x = (w - BASE_W * menu_scale) / 2
        offset_y = (h - BASE_H * menu_scale) / 2
        return (cursor[0] - x - offset_x) / menu_scale, (cursor[1] - y - offset_y) / menu_scale

    def test_r10_at_display_scale_100_the_new_click_mapping_equals_the_old_one_exactly(self):
        import overlay_transform as t
        for rect in RECTS:
            for dx, dy in ((0, 0), (1, 1), (rect[2] / 2.0, rect[3] / 2.0), (rect[2] - 1, rect[3] - 1), (333.5, 77.25)):
                cursor = (rect[0] + dx, rect[1] + dy)
                self.assertEqual(t.menu_local_point(cursor, rect), self.old_click(cursor, rect), "OVS-R10: %r %r" % (rect, cursor))

    def test_r9_the_hit_test_uses_the_same_physical_rectangle_whatever_the_display_scale(self):
        import overlay_transform as t
        rect = (328, 187, 1264, 681)
        cursor = (900.0, 500.0)
        first = t.menu_local_point(cursor, rect)
        for _dpr in (1.0, 1.25, 1.5, 1.75, 2.0):                    # the display scale is not an input at all
            self.assertEqual(t.menu_local_point(cursor, rect), first)

    def test_r5_logical_geometry_is_a_pure_conversion_and_only_a_helper(self):
        import overlay_transform as t
        self.assertEqual(t.logical_geometry((100, 100, 1600, 900), 1.0), (100, 100, 1600, 900))
        self.assertEqual(t.logical_geometry((100, 100, 1600, 900), 1.25), (80, 80, 1280, 720))
        self.assertEqual(t.logical_geometry((330, 168, 1580, 851), 1.25), (264, 134, 1264, 681))
        self.assertEqual(t.logical_geometry((0, 0, 1, 1), 2.0), (0, 0, 1, 1))
        self.assertEqual(t.logical_geometry((5, 5, 100, 100), 0), (5, 5, 100, 100))

    def test_rects_match_tolerance(self):
        import overlay_transform as t
        self.assertTrue(t.rects_match((1, 2, 3, 4), (1, 2, 3, 4)))
        self.assertTrue(t.rects_match((1, 2, 3, 4), (2, 1, 4, 3)))
        self.assertFalse(t.rects_match((1, 2, 3, 4), (3, 2, 3, 4)))
        self.assertFalse(t.rects_match(None, (1, 2, 3, 4)))

    def test_r14_the_hit_test_keeps_the_aspect_contract_letterbox_min_of_width_and_height_ratio(self):
        import overlay_transform as t
        # 4:3 window: the height ratio is smaller -> the menu is centred horizontally; the left edge of the menu (design x = 0) lies at (w - 1920*scale)/2
        w, h = 1600, 1200
        scale = min(w / BASE_W, h / BASE_H)
        self.assertAlmostEqual(scale, 1600 / 1920.0)
        lx, ly = t.menu_local_point((0 + (w - BASE_W * scale) / 2, 0 + (h - BASE_H * scale) / 2), (0, 0, w, h))
        self.assertAlmostEqual(lx, 0.0)
        self.assertAlmostEqual(ly, 0.0)
        # 21:9 window: the width ratio is not used for the scale
        w, h = 2560, 1080
        self.assertAlmostEqual(min(w / BASE_W, h / BASE_H), 1.0)


class Static(unittest.TestCase):
    """OVS-R1 / R11-R13 / R17 / R18 and the unchanged drawing."""

    @classmethod
    def setUpClass(cls):
        cls.main = read("main.py")
        cls.hud = read("managed_hud.py")
        cls.tr = read("overlay_transform.py")
        cls.place = segment(cls.main, "Overlay.set_client_rect_physical")
        cls.follow = segment(cls.main, "Overlay._follow_bve_window")
        cls.mouse = segment(cls.main, "Overlay._handle_mouse")
        cls.paint = segment(cls.main, "Overlay.paintEvent")

    def test_r1_the_physical_rectangle_is_never_handed_to_qt_set_geometry(self):
        self.assertNotIn("overlay.setGeometry(*rect)", self.hud)
        self.assertNotIn("setGeometry(", self.hud, "managed_hud never places the Overlay with Qt logical px")
        self.assertNotIn("self.setGeometry(client_x, client_y, w, h)", self.follow)
        self.assertNotIn("setGeometry(", self.follow)
        self.assertIn("self.set_client_rect_physical(client_x, client_y, w, h)", self.follow)
        self.assertIn("overlay.set_client_rect_physical(*rect)", self.hud)
        # inside the placement: Qt gets only the LOGICAL equivalent, the exact physical rectangle goes to SetWindowPos
        self.assertIn("self.setGeometry(*overlay_transform.logical_geometry(rect, self.devicePixelRatioF()))", self.place)
        self.assertIn("overlay_set_window_pos(int(self.winId()), 0, x, y, w, h, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)", self.place)
        self.assertIn("from win32gui import GetWindowRect as overlay_get_window_rect, SetWindowPos as overlay_set_window_pos", self.main)
        self.assertEqual(self.place.count("setGeometry("), 1)

    def test_r8_r9_the_click_handler_uses_the_physical_rectangle_not_the_logical_geometry(self):
        self.assertNotIn("self.geometry()", self.mouse)
        self.assertEqual(self.mouse.count("overlay_transform.menu_local_point(win32gui.GetCursorPos(), self.client_rect_physical())"), 2)
        for old in ("scale_x = geom.width()", "offset_x = (geom.width()", "cursor_pos[0] - geom.x()"):
            self.assertNotIn(old, self.mouse)

    def test_r12_the_drawing_formulas_are_unchanged(self):
        """the draw side (design coordinates, ratios of the widget's own logical size) is not touched by OVS-1 (on purpose: the display scale cancels out)"""
        self.assertIn("hud_scale = self.height() / BASE_SCREEN_H if self.height() > 0 else 1.0", self.paint)
        self.assertIn("hud_logical_width = self.width() / hud_scale if hud_scale > 0 else BASE_SCREEN_W", self.paint)
        self.assertIn("painter.scale(hud_scale, hud_scale)", self.paint)
        self.assertIn("draw_menu(self, painter, hud_logical_width)", self.paint)
        menu = read("menu_ui.py")
        self.assertIn("    scale_x = self.width() / BASE_SCREEN_W\n    scale_y = self.height() / BASE_SCREEN_H\n    menu_scale = min(scale_x, scale_y)\n", menu)
        self.assertIn("    offset_x = (self.width() - BASE_SCREEN_W * menu_scale) / 2\n    offset_y = (self.height() - BASE_SCREEN_H * menu_scale) / 2\n", menu)

    def test_r17_r18_no_clamp_no_push_back_no_clip_no_dpi_switch_no_per_scale_table(self):
        code = "\n".join((self.tr, self.place, self.follow))          # (_handle_mouse is excluded here: it legitimately calls initial_defaults.clamp_a_rank_ratio, the slider's percentage clamp)
        self.assertNotIn("clamp", self.mouse.replace("clamp_a_rank_ratio", ""), "no position clamp in the hit test")
        for bad in ("clamp", "clip", "setClipRect", "setMask", "WindowStaysOnTopHint", "SetProcessDpiAwareness", "SetProcessDPIAware", "QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING",
                    "AA_DisableHighDpiScaling", "HighDpiScaleFactorRoundingPolicy", "setHighDpi", "QT_AUTO_SCREEN_SCALE_FACTOR", "GetDpiForWindow", "GetDpiForSystem", "logicalDpi", "physicalDpi"):
            self.assertNotIn(bad, code, "forbidden: " + bad)
        self.assertNotRegex(code, r"1\.25|1\.5\b|1\.75|\b125\b|\b150\b|\b175\b", "no fixed correction for one display scale")
        self.assertNotRegex(code, r"dpr\s*(==|!=|<=?|>=?)\s*[1-9]", "no branch on the display scale (the ratio is only used for the logical conversion)")
        for src in (self.main, self.hud):
            for bad in ("SetProcessDpiAwareness", "SetProcessDPIAware", "QT_ENABLE_HIGHDPI_SCALING", "AA_DisableHighDpiScaling", "setHighDpiScaleFactorRoundingPolicy"):
                self.assertNotIn(bad, src)
        self.assertNotIn("QT_SCALE_FACTOR", self.main + self.hud)

    def test_r15_current_and_legacy_share_one_placement_no_mode_branch(self):
        for name, code in (("place", self.place), ("applied", segment(self.main, "Overlay.client_rect_applied")), ("physical", segment(self.main, "Overlay.client_rect_physical"))):
            self.assertNotRegex(code, r"(?i)legacy|is_legacy|\bmode\b|scenario_mode", name)
        self.assertNotRegex(self.tr, r"(?i)legacy|current")

    def test_r14_hud_and_menu_use_one_client_contract(self):
        """both the managed path and the normal-mode path place through the same method; the hit test reads what that method stored"""
        self.assertIn("self._client_phys = rect", self.place)
        self.assertIn("return self._client_phys", segment(self.main, "Overlay.client_rect_physical"))
        self.assertEqual(self.main.count("set_client_rect_physical("), 2, "def + the normal-mode call (the managed call lives in managed_hud)")
        self.assertIn("client_rect_applied(rect)", self.hud)

    def test_the_transform_module_is_pure(self):
        for bad in ("PyQt6", "win32", "import ctypes", "QApplication"):
            self.assertNotIn(bad, self.tr)


sys.path.insert(0, HERE)
import test_managed_hud_e4 as e4              # noqa: E402  (the controller rig of the E4 tests: fake Overlay, fake window API, fake clock)


class Controller(e4.ControllerCase):
    """OVS-R1 / R11 / R12 / R13 at the controller: the client rectangle read from Win32 (physical px) reaches the Overlay unchanged through set_client_rect_physical,
    every change of it (resize, maximise / restore, F11 / release) is applied once, and a window that no longer sits on the rectangle (the display scale or the monitor
    changed and Qt rescaled it) is applied again even though the BVE rectangle itself did not change."""

    def start_active(self):
        def no_logical_geometry(*a):
            raise AssertionError("OVS-R1: the controller must not call Qt's logical setGeometry")
        self.overlay.setGeometry = no_logical_geometry
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(10)

    def test_r1_the_physical_rectangle_is_applied_unchanged_and_only_through_the_physical_placement(self):
        self.api.rect = (328, 187, 1264, 681)
        self.start_active()
        self.assertEqual(self.overlay.geoms, [(328, 187, 1264, 681)])

    def test_r11_r12_r13_resize_maximise_restore_and_f11_are_each_applied_once_and_nothing_else(self):
        self.api.rect = (328, 187, 1264, 681)
        self.start_active()
        sequence = [(328, 187, 1600, 900), (0, 0, 1920, 1080), (328, 187, 1264, 681), (0, 0, 3840, 2160), (328, 187, 1264, 681)]      # resize, F11 / maximise, restore, a 4K client, restore
        for rect in sequence:
            self.api.rect = rect
            self.pump(10)
        self.assertEqual(self.overlay.geoms, [(328, 187, 1264, 681)] + sequence, "OVS-R11/12/13: each different client rectangle is applied exactly once, in order")

    def test_r13_an_unchanged_client_that_the_overlay_still_sits_on_is_not_applied_again(self):
        self.api.rect = (328, 187, 1264, 681)
        self.start_active()
        self.pump(50)
        self.assertEqual(len(self.overlay.geoms), 1)

    def test_r12_a_rescaled_overlay_window_is_put_back_on_the_unchanged_client_rectangle(self):
        """a change of the display scale / of the monitor: BVE's rectangle may stay, the Overlay window was rescaled by Qt -> applied again (no stale geometry)"""
        self.api.rect = (328, 187, 1264, 681)
        self.start_active()
        self.overlay.applied_rect = (413, 210, 1580, 851)               # what the real window looks like after the rescale
        self.pump(10)
        self.assertEqual(self.overlay.geoms, [(328, 187, 1264, 681), (328, 187, 1264, 681)])
        self.pump(10)
        self.assertEqual(len(self.overlay.geoms), 2, "and then it is left alone again")


class NormalMode(unittest.TestCase):
    """OVS-R12 / R13 in the normal (non-managed) mode: Overlay._follow_bve_window with a stand-in for self and a recording win32gui"""

    def run_follow(self, rects, applied_after_set=True, pretend_applied=None):
        import main

        class Gui(object):
            def __init__(self):
                self.rect = None

            def IsIconic(self, h):
                return False

            def GetClientRect(self, h):
                return (0, 0, self.rect[2], self.rect[3])

            def ClientToScreen(self, h, pt):
                return (self.rect[0], self.rect[1])

            def SetWindowLong(self, *a):
                pass

        gui = Gui()

        class Fake(object):
            is_linked = True
            bve_hwnd = 77
            placed = []
            current = None

            def isVisible(self):
                return True

            def show(self):
                pass

            def hide(self):
                pass

            def set_client_rect_physical(self, x, y, w, h):
                self.placed.append((x, y, w, h))
                self.current = (x, y, w, h)

            def client_rect_applied(self, rect):
                return self.current == rect

        fake = Fake()
        fake.placed = []
        saved = main.win32gui
        main.win32gui = gui
        try:
            for rect in rects:
                gui.rect = rect
                main.Overlay._follow_bve_window(fake)
        finally:
            main.win32gui = saved
        return fake.placed

    def test_r11_r12_r13_the_normal_mode_applies_each_client_change_once_in_physical_px(self):
        rects = [(328, 187, 1264, 681), (328, 187, 1264, 681), (0, 0, 1920, 1080), (0, 0, 1920, 1080), (328, 187, 1264, 681), (0, 0, 3840, 2160)]
        self.assertEqual(self.run_follow(rects), [(328, 187, 1264, 681), (0, 0, 1920, 1080), (328, 187, 1264, 681), (0, 0, 3840, 2160)])


class RealWindowsQt(unittest.TestCase):
    """OVS-R2 / R3 / R4 / R6 / R7 / R8 / R11 / R12 / R13 / R16: a real main.Overlay at a forced display scale."""

    @classmethod
    def setUpClass(cls):
        cls.hud = {}
        cls.f1 = {}
        for dpr in DPRS:
            cls.hud[dpr] = child("product", [[100, 100, 1600, 900]], dpr, 0)
            cls.f1[dpr] = child("product", [[100, 100, 1600, 900]], dpr, 1)

    def test_r2_r3_r4_r5_the_overlay_window_is_exactly_the_physical_client_rectangle_at_every_scale(self):
        for dpr in DPRS:
            self.assertAlmostEqual(self.hud[dpr]["dpr"], float(dpr))
            self.assertEqual(self.hud[dpr]["win32_rect_steps"][-1], [100, 100, 1600, 900], "OVS-R5 at display scale %s" % dpr)

    def test_r16_nothing_leaves_the_bve_client_because_the_transform_is_right(self):
        for dpr in DPRS:
            data = self.hud[dpr]
            l, t, w, h = data["win32_rect_steps"][-1]
            self.assertTrue(l >= 100 and t >= 100 and l + w <= 1700 and t + h <= 1000, "OVS-R16 at %s" % dpr)
            gw, gh = data["grab_phys_size"]
            self.assertTrue(abs(gw - 1600) <= 1 and abs(gh - 900) <= 1, "what is drawn is the client size in physical px at %s: %r" % (dpr, data["grab_phys_size"]))

    def test_r6_the_hud_physical_size_does_not_depend_on_the_display_scale(self):
        base = self.hud["1.0"]
        self.assertIsNotNone(base["ink_bbox_phys"])
        for dpr in DPRS[1:]:
            data = self.hud[dpr]
            for a, b in zip(base["ink_bbox_phys"], data["ink_bbox_phys"]):
                self.assertLessEqual(abs(a - b), 2, "OVS-R6 HUD ink box at %s: %r vs %r" % (dpr, data["ink_bbox_phys"], base["ink_bbox_phys"]))
            self.assertLessEqual(abs(base["first_band_phys"][1] - data["first_band_phys"][1]), 1, "OVS-R6 clock text height at %s" % dpr)

    def test_r7_the_f1_physical_size_does_not_depend_on_the_display_scale(self):
        base = self.f1["1.0"]
        for dpr in DPRS[1:]:
            for a, b in zip(base["ink_bbox_phys"], self.f1[dpr]["ink_bbox_phys"]):
                self.assertLessEqual(abs(a - b), 2, "OVS-R7 F1 ink box at %s" % dpr)

    def test_r8_r9_drawn_position_and_click_position_agree_at_every_scale(self):
        for dpr in DPRS:
            click = self.f1[dpr]["click"]
            self.assertGreater(click["zones"], 0)
            self.assertLess(click["worst_round_trip_error_design_units"], 1.0, "OVS-R9 at %s" % dpr)
            self.assertEqual(click["zones_with_ink_under_drawn_box"], click["zones"], "OVS-R8: every click zone lies over drawn ink at %s" % dpr)

    def test_r11_r12_r13_the_overlay_follows_every_change_of_the_client_without_keeping_an_old_geometry(self):
        """window resize, maximise / restore and F11 / release are all just a different client rectangle: each one must be reflected exactly, at every scale"""
        sequence = [[328, 187, 1264, 681], [0, 0, 1920, 1080], [328, 187, 1264, 681], [0, 0, 3840, 2160], [0, 0, 1920, 1080], [-1920, 0, 1920, 1080], [-300, -40, 1280, 720], [10, 20, 918, 627]]
        for dpr in DPRS:
            data = child("product", sequence, dpr, 0)
            for want, got in zip(sequence, data["win32_rect_steps"]):
                self.assertEqual(got, want, "OVS-R11/12/13/17 at display scale %s (negative origins included: no push back to the screen)" % dpr)
            self.assertEqual(data["client_phys"], [float(v) for v in sequence[-1]])

    def test_r12_the_real_client_rect_applied_follows_the_real_window(self):
        for dpr in DPRS:
            data = child("product", [[100, 100, 1600, 900]], dpr, 0)
            self.assertTrue(data["applied_after_place"], "true on the rectangle just placed, at %s" % dpr)
            self.assertFalse(data["applied_after_foreign_move"], "false once the real window was moved / rescaled by something else, at %s" % dpr)

    def test_r11_the_hud_scale_follows_the_client_height(self):
        """the existing contract (height / 1080) in physical px: a 1280x720 client draws the clock 2/3 as high as a 1920x1080 client, at every display scale"""
        for dpr in DPRS:
            full = child("product", [[0, 0, 1920, 1080]], dpr, 0)["first_band_phys"][1]
            small = child("product", [[0, 0, 1280, 720]], dpr, 0)["first_band_phys"][1]
            self.assertLessEqual(abs(small - full * 720 / 1080.0), 1.5, "OVS-R11 at %s: %s vs %s" % (dpr, small, full))

    def test_control_the_pre_ovs1_call_is_wrong_at_scales_above_100(self):
        """the harness can see the defect: Qt's setGeometry with the physical rectangle makes the window client x display scale (this is the RED of OVS-R2..R5)"""
        for dpr in DPRS:
            data = child("legacy_setgeometry", [[100, 100, 1600, 900]], dpr, 0)
            want = [round(100 * float(dpr)), round(100 * float(dpr)), round(1600 * float(dpr)), round(900 * float(dpr))]
            got = data["win32_rect_steps"][-1]
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(got, want)), "control at %s: %r vs %r" % (dpr, got, want))


if __name__ == "__main__":
    unittest.main()
