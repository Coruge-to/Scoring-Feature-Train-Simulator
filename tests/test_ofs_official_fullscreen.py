"""Phase OFS-1 - the HUD in BVE's official fullscreen (Windowed=false, desktop or fixed resolution).

Owner ruling (2026-11-13, OFS-0 report): in the official fullscreen the HUD looks like BVE in a window + TScoring's F11. OFS-0 found the cause: BVE's own window
(WS_EX_TOPMOST) and its D3DProxyWindow (class "D3DProxyWindow", TOPMOST | TRANSPARENT | NOACTIVATE, same process, whole screen) are topmost, the Overlay is
not, so it lay UNDER both although it was placed, visible and painted. The rule of this phase (python only; no DLL, IPC, launcher, Caller change; no injection):

  R1  is_native_fullscreen(style, exstyle): the BVE window is TOPMOST and has no caption (a window of a normal desktop is never both; TScoring's F11
      state is not topmost).
  R2  when the BVE window is topmost the HUD joins the TOPMOST band DIRECTLY ABOVE the BVE window's own group (the window and its D3DProxyWindow(s)), below any
      other window that lies over them (the scenario selection window, BVE's menus and dialogs): the Phase E4 rule "directly above the driving window, never
      over what lies over it" is kept; only the band changes. A BVE window that is not topmost (window mode, F11) is handled exactly as before (HUD never topmost).
  R3  F11 and F12 do nothing while BVE is in the official fullscreen (OFS-0: F11 there left the proxy window over the HUD and hid BVE's own dialogs).
  R4  the Win32 calls are a pure Z operation (no activation, no move, no resize), the class name is read only in the Win32 layer, the controller has no host branch.
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import managed_hud as mh  # noqa: E402
import managed_state as ms  # noqa: E402
import overlay_transform as ot  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None

WS_EX_TOPMOST = 0x00000008
WS_CAPTION = 0x00C00000
WINDOWED_STYLE, WINDOWED_EX = 0x16CF0000, 0x00050100       # BVE6 in a window (OFS-0 measurement)
F11_STYLE, F11_EX = 0x17000000, 0x00050000                 # BVE6 after TScoring's F11
FULLSCREEN_STYLE, FULLSCREEN_EX = 0x16000000, 0x00050008   # BVE6 / BVE5 official fullscreen

BVE, PROXY, SELECT, OTHER, HUD = 5000, 5500, 7000, 7100, 1000


class A_TheRule(unittest.TestCase):
    def test_official_fullscreen_is_topmost_without_a_caption(self):
        self.assertTrue(ot.is_native_fullscreen(FULLSCREEN_STYLE, FULLSCREEN_EX))

    def test_window_mode_and_f11_are_not_the_official_fullscreen(self):
        self.assertFalse(ot.is_native_fullscreen(WINDOWED_STYLE, WINDOWED_EX))
        self.assertFalse(ot.is_native_fullscreen(F11_STYLE, F11_EX))

    def test_a_topmost_window_with_a_caption_is_not(self):
        self.assertFalse(ot.is_native_fullscreen(WINDOWED_STYLE, WINDOWED_EX | WS_EX_TOPMOST))

    def test_a_captionless_window_that_is_not_topmost_is_not(self):
        self.assertFalse(ot.is_native_fullscreen(FULLSCREEN_STYLE, FULLSCREEN_EX & ~WS_EX_TOPMOST))

    def test_signed_values_from_getwindowlong_are_accepted(self):
        signed = FULLSCREEN_STYLE - (1 << 32) if FULLSCREEN_STYLE & 0x80000000 else FULLSCREEN_STYLE
        self.assertTrue(ot.is_native_fullscreen(signed, FULLSCREEN_EX))
        self.assertFalse(ot.is_native_fullscreen(-0x69300000, WINDOWED_EX))          # 0x96CF0000 as a signed 32 bit value: a window with a caption

    def test_the_rule_has_no_qt_or_win32_dependency(self):
        with open(os.path.join(ROOT, "overlay_transform.py"), encoding="utf-8") as handle:
            src = handle.read()
        for token in ("PyQt6", "win32", "ctypes"):
            self.assertNotIn(token, src)


class B_Win32Layer(unittest.TestCase):
    """Win32WindowApi against a recording pywin32 stand-in."""

    def setUp(self):
        class Con(object):
            GW_HWNDPREV = 3
            HWND_TOP = 0
            HWND_TOPMOST = -1
            SWP_NOSIZE = 1
            SWP_NOMOVE = 2
            SWP_NOZORDER = 4
            SWP_NOACTIVATE = 16
            SWP_SHOWWINDOW = 64
            WS_EX_TOPMOST = 8
            GWL_EXSTYLE = -20

        class Gui(object):
            def __init__(inner):
                inner.calls = []
                inner.classes = {PROXY: "D3DProxyWindow", 5600: "D3DProxyWindow", SELECT: "WindowsForms10.Window.8.app.0.23f19a8_r10_ad1"}

            def SetWindowPos(inner, *a):
                inner.calls.append(("SetWindowPos",) + a)

            def GetClassName(inner, hwnd):
                return inner.classes.get(hwnd, "")

        class Proc(object):
            pids = {PROXY: 880001, 5600: 999, SELECT: 880001}

            def GetWindowThreadProcessId(inner, hwnd):
                return (1, inner.pids.get(hwnd, 0))

        self.con, self.gui = Con, Gui()
        self.api = mh.Win32WindowApi.__new__(mh.Win32WindowApi)
        self.api._con, self.api._gui, self.api._proc = Con, self.gui, Proc()

    def test_place_below_is_unchanged_for_the_normal_band(self):
        self.api.place_below(HUD, SELECT)
        self.api.place_below(HUD, 0)
        self.assertEqual(self.gui.calls, [("SetWindowPos", HUD, SELECT, 0, 0, 0, 0, 2 | 1 | 16), ("SetWindowPos", HUD, self.con.HWND_TOP, 0, 0, 0, 0, 2 | 1 | 16)])

    def test_topmost_band_below_a_window_is_the_same_call(self):
        self.api.place_below(HUD, SELECT, topmost=True)
        self.assertEqual(self.gui.calls, [("SetWindowPos", HUD, SELECT, 0, 0, 0, 0, 2 | 1 | 16)])

    def test_topmost_band_with_nothing_above_goes_to_the_top_of_the_topmost_band(self):
        self.api.place_below(HUD, 0, topmost=True)
        self.assertEqual(self.gui.calls, [("SetWindowPos", HUD, -1, 0, 0, 0, 0, 2 | 1 | 16)])

    def test_flags_stay_a_pure_z_operation(self):
        self.api.place_below(HUD, 0, topmost=True)
        flags = self.gui.calls[0][-1]
        self.assertTrue(flags & self.con.SWP_NOACTIVATE and flags & self.con.SWP_NOMOVE and flags & self.con.SWP_NOSIZE)
        self.assertFalse(flags & (self.con.SWP_NOZORDER | self.con.SWP_SHOWWINDOW))

    def test_a_proxy_window_is_the_d3d_proxy_class_of_the_bve_process(self):
        self.assertTrue(self.api.is_bve_proxy(PROXY, 880001))

    def test_another_class_or_another_process_is_not_a_proxy(self):
        self.assertFalse(self.api.is_bve_proxy(SELECT, 880001))        # BVE's own selection window: same process, other class
        self.assertFalse(self.api.is_bve_proxy(5600, 880001))          # a proxy window of another process (another game)
        self.assertFalse(self.api.is_bve_proxy(1234, 880001))

    def test_a_failing_query_is_not_a_proxy(self):
        def boom(hwnd):
            raise OSError("gone")
        self.gui.GetClassName = boom
        self.assertFalse(self.api.is_bve_proxy(PROXY, 880001))


class OfsApi(e4.FakeWindowApi):
    """The fake Z order of the E4 suite plus: topmost-band placement and the proxy windows of BVE."""

    def __init__(self):
        super().__init__()
        self.proxies = set()

    def is_bve_proxy(self, hwnd, bve_pid):
        return hwnd in self.proxies

    def z_on_show(self, overlay_hwnd):
        self.topmost.discard(overlay_hwnd)                        # a (re)created native window is not topmost
        super().z_on_show(overlay_hwnd)

    def place_below(self, overlay_hwnd, above_hwnd, topmost=False):
        self.z_calls.append((overlay_hwnd, above_hwnd, True) if topmost else (overlay_hwnd, above_hwnd))
        if self.z_fail is not None:
            raise self.z_fail
        if overlay_hwnd in self.z:
            self.z.remove(overlay_hwnd)
        if above_hwnd:
            self.z.insert(self.z.index(above_hwnd) + 1, overlay_hwnd)
            if above_hwnd in self.topmost:
                self.topmost.add(overlay_hwnd)                    # Windows: after a topmost window = topmost
            else:
                self.topmost.discard(overlay_hwnd)
        elif topmost:
            self.z.insert(0, overlay_hwnd)
            self.topmost.add(overlay_hwnd)
        else:
            self.topmost.discard(overlay_hwnd)
            self.z.insert(self._normal_band_top(), overlay_hwnd)


class C_Controller(e4.ControllerCase):
    def setUp(self):
        super().setUp()
        self.api = OfsApi()
        self.overlay.z_api = self.api
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: self.steps.append(1),
                                           timer=self.timer, clock=self.clock)

    def activate(self, z, topmost=(), proxies=()):
        self.api.z = list(z)
        self.api.topmost = set(topmost)
        self.api.proxies = set(proxies)
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(1)

    def test_official_fullscreen_hud_goes_directly_above_the_proxy_window(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        self.assertEqual(self.api.z, [HUD, PROXY, BVE])
        self.assertIn(HUD, self.api.topmost)
        self.assertEqual(self.api.z_calls, [(HUD, 0, True)])

    def test_a_window_that_lies_over_the_proxy_stays_over_the_hud(self):
        self.activate([SELECT, PROXY, BVE], topmost={SELECT, PROXY, BVE}, proxies={PROXY})
        self.assertEqual(self.api.z, [SELECT, HUD, PROXY, BVE])
        self.assertIn(HUD, self.api.topmost)
        self.assertEqual(self.api.z_calls, [(HUD, SELECT, True)])

    def test_two_proxy_windows_are_both_passed(self):
        self.activate([5600, PROXY, BVE], topmost={5600, PROXY, BVE}, proxies={5600, PROXY})
        self.assertEqual(self.api.z, [HUD, 5600, PROXY, BVE])

    def test_a_topmost_bve_window_without_a_proxy_gets_the_hud_directly_above_it(self):
        self.activate([OTHER, BVE], topmost={OTHER, BVE})
        self.assertEqual(self.api.z, [OTHER, HUD, BVE])
        self.assertIn(HUD, self.api.topmost)

    def test_a_proxy_below_the_bve_window_does_not_matter(self):
        self.activate([BVE, PROXY], topmost={BVE, PROXY}, proxies={PROXY})
        self.assertEqual(self.api.z, [HUD, BVE, PROXY])

    def test_a_proxy_window_above_another_window_is_still_passed(self):
        self.activate([PROXY, OTHER, BVE], topmost={PROXY, OTHER, BVE}, proxies={PROXY})
        self.assertEqual(self.api.z, [HUD, PROXY, OTHER, BVE])      # the HUD lies over every window of BVE's group, wherever the proxy is

    def test_a_foreign_topmost_window_over_the_group_does_not_move_the_hud(self):
        self.activate([OTHER, PROXY, BVE], topmost={OTHER, PROXY, BVE}, proxies={PROXY})
        self.assertEqual(self.api.z, [OTHER, HUD, PROXY, BVE])
        self.api.z_calls.clear()
        self.pump(50)
        self.assertEqual(self.api.z_calls, [])

    def new_proxy(self, hwnd=5600, at=0):
        """BVE re-creates its D3D proxy window (a change of the display scale): a NEW topmost window, at the top of the topmost band, over the HUD."""
        self.api.z.insert(at, hwnd)
        self.api.topmost.add(hwnd)
        self.api.proxies.add(hwnd)

    def test_a_proxy_window_created_after_the_hud_is_brought_back_under_the_hud(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        self.assertEqual(self.api.z, [HUD, PROXY, BVE])
        self.new_proxy()                                               # the OFS-1 live observation: [new proxy, HUD, old proxy, BVE]
        self.api.z_calls.clear()
        sets = self.hud.z_sets
        self.pump(1)
        self.assertEqual(self.api.z, [HUD, 5600, PROXY, BVE])
        self.assertEqual(self.api.z_calls, [(HUD, 0, True)])
        self.assertEqual(self.hud.z_sets, sets + 1)
        self.pump(100)
        self.assertEqual(self.api.z_calls, [(HUD, 0, True)])           # once, not every Tick

    def test_every_new_proxy_window_is_followed(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        for hwnd in (5600, 5601, 5602):
            self.new_proxy(hwnd)
            self.pump(2)
            self.assertEqual(self.api.z[0], HUD)

    def test_the_hud_was_hidden_under_a_proxy_that_existed_before_the_tick_after_a_reshow_without_show_transition(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        self.api.z = [PROXY, HUD, BVE]                                 # the state the Owner saw: the proxy over the HUD, the HUD still topmost
        self.pump(1)
        self.assertEqual(self.api.z, [HUD, PROXY, BVE])

    def test_steady_state_costs_one_z_query_per_tick(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        queries = self.api.z_queries
        self.pump(100)
        self.assertEqual(self.api.z_queries, queries + 100)

    def test_window_mode_still_never_polls_the_z_order(self):
        self.activate([SELECT, BVE])
        queries = self.api.z_queries
        self.api.z_calls.clear()
        self.pump(1000)
        self.assertEqual((self.api.z_queries, self.api.z_calls), (queries, []))

    def test_window_mode_is_unchanged_the_hud_never_becomes_topmost(self):
        self.activate([SELECT, BVE])
        self.assertEqual(self.api.z, [SELECT, HUD, BVE])
        self.assertNotIn(HUD, self.api.topmost)
        self.assertEqual(self.api.z_calls, [(HUD, SELECT)])           # the 2-tuple of the E4 contract: no topmost argument in window mode

    def test_a_foreign_topmost_window_over_a_window_mode_bve_does_not_make_the_hud_topmost(self):
        self.activate([OTHER, BVE], topmost={OTHER})
        self.assertEqual(self.api.z, [OTHER, HUD, BVE])
        self.assertNotIn(HUD, self.api.topmost)

    def test_in_place_nothing_is_set_again(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        self.api.z_calls.clear()
        for _ in range(50):
            self.hud._ensure_z_order()
        self.assertEqual(self.api.z_calls, [])

    def test_every_reshow_finalises_again(self):
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        self.publish(True, False, 1)
        self.pump(5)
        self.publish(True, True, 1)
        self.pump(5)
        self.assertEqual(self.api.z, [HUD, PROXY, BVE])
        self.assertIn(HUD, self.api.topmost)

    def test_a_failing_order_is_contained_and_retried_at_most_once_a_second(self):
        self.api.z_fail = OSError("boom")
        self.activate([PROXY, BVE], topmost={PROXY, BVE}, proxies={PROXY})
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.hud.z_errors, 1)
        self.pump(500)                                                 # 500 Ticks of 20 ms = 10 s of the fake clock
        self.assertLessEqual(self.hud.z_errors, 12)
        self.assertLessEqual(len(self.log.events("hud-zorder-error")), mh.MAX_ZORDER_LINES)
        self.assertEqual(len(self.steps), 501)                         # the HUD went on updating

    def test_current_and_legacy_hosts_give_the_same_result(self):
        for pid, hwnd in ((6001, 5000), (5001, 8800)):
            with self.subTest(pid=pid):
                args = e4.args_for(pid=pid)
                source = e4.FakeSource(e4.make_block(args.bve_pid, args.instance))
                api = OfsApi()
                api.hwnd = hwnd
                api.z = [PROXY, hwnd]
                api.topmost = {PROXY, hwnd}
                api.proxies = {PROXY}
                overlay = e4.FakeOverlay()
                overlay.z_api = api
                hud = mh.ManagedHudController(overlay, ms.StateReader(args, source, e4.Log()), api, args, e4.Log(), update_step=lambda o: None,
                                              timer=e4.FakeTimer(), clock=e4.Clock())
                hud.start()
                source.data = e4.make_block(args.bve_pid, args.instance, True, True, False, 1, 1)
                for _ in range(100):
                    hud.tick()
                self.assertEqual(api.z, [HUD, PROXY, hwnd])
                self.assertEqual(api.z_calls, [(HUD, 0, True)])


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class D_F11AndF12(unittest.TestCase):
    """The real Overlay (offscreen) with the recorders of the SI-0 characterization: F11 / F12 do nothing in the official fullscreen."""
    HWND = 4242

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["ofs1"])
        import main
        import test_scoring_observation_si0 as si0
        cls.main, cls.si0 = main, si0

    def setUp(self):
        m, si0 = self.main, self.si0
        test = self

        class Gui(si0.FakeGui):
            def GetWindowLong(inner, h, index):
                if index == m.win32con.GWL_STYLE:
                    return test.style
                if index == m.win32con.GWL_EXSTYLE:
                    return test.exstyle
                return 0

        self.style, self.exstyle = WINDOWED_STYLE, WINDOWED_EX
        self.saved = {n: getattr(m, n) for n in ("keyboard", "win32gui", "win32api", "time", "QApplication", "QTimer", "QUdpSocket", "write_desktop_log")}
        self.kb, self.gui, self.api, self.clock = si0.FakeKeyboard(), Gui(self.HWND), si0.FakeApi(), si0.FakeTime()
        self.log = []
        si0.FakeApp.quits = 0
        m.keyboard, m.win32gui, m.win32api, m.time, m.QApplication, m.QUdpSocket = self.kb, self.gui, self.api, self.clock, si0.FakeApp, si0.StubUdp
        m.write_desktop_log = lambda msg, *a, **k: self.log.append(msg)
        self.o = m.Overlay()
        self.o.timer.stop()
        self.o.bve_hwnd = self.HWND
        self.o.is_linked = True
        self.o.was_bve_found = True
        self.o.menu_state = 0
        self.o.bve_actual_state = "RUNNING"

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(self.main, n, v)
        try:
            self.o.udp_socket.close()
            self.o.close()
            self.o.deleteLater()
        except Exception:
            pass

    def press(self, key):
        self.kb.pressed.add(key)
        self.o.update_logic()
        self.kb.pressed.discard(key)
        self.o.update_logic()

    def window_calls(self):
        return [c for c in self.gui.calls if c[0] in ("SetWindowLong", "SendMessage", "SetWindowPos", "SetWindowPlacement")]

    def test_f11_in_the_official_fullscreen_changes_nothing(self):
        self.style, self.exstyle = FULLSCREEN_STYLE, FULLSCREEN_EX
        self.press("f11")
        self.assertEqual(self.window_calls(), [])
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertIsNone(self.o.bve_original_style)

    def test_f12_in_the_official_fullscreen_changes_nothing(self):
        self.style, self.exstyle = FULLSCREEN_STYLE, FULLSCREEN_EX
        self.press("f12")
        self.assertEqual(self.window_calls(), [])

    def test_f11_in_window_mode_still_goes_borderless(self):
        self.main.QTimer = type("T", (), {"singleShot": staticmethod(lambda ms, fn: fn())})
        self.main.win32api.MonitorFromWindow = lambda h, flag: 1
        self.main.win32api.GetMonitorInfo = lambda mon: {"Monitor": (0, 0, 1920, 1080)}
        self.press("f11")
        self.assertTrue(self.o.is_borderless_fullscreen)

    def test_f12_in_window_mode_still_restores_the_standard_window(self):
        self.o.is_borderless_fullscreen = True
        self.press("f12")
        self.assertFalse(self.o.is_borderless_fullscreen)
        self.assertTrue(self.window_calls())

    def test_an_unreadable_window_is_not_taken_for_the_native_fullscreen(self):
        def boom(h, index):
            raise OSError("window gone")
        self.gui.GetWindowLong = boom
        self.assertIs(self.o._bve_in_native_fullscreen(), False)

    def test_the_native_fullscreen_is_read_from_the_bve_window_style_and_exstyle(self):
        self.assertIs(self.o._bve_in_native_fullscreen(), False)
        self.style, self.exstyle = FULLSCREEN_STYLE, FULLSCREEN_EX
        self.assertIs(self.o._bve_in_native_fullscreen(), True)

    def test_the_skip_is_logged(self):
        self.style, self.exstyle = FULLSCREEN_STYLE, FULLSCREEN_EX
        self.press("f11")
        self.assertTrue([m for m in self.log if "[WINDOW]" in m and "F11" in m], self.log)

    def test_the_f11_state_of_the_window_mode_can_be_left_by_f11_again(self):
        self.main.QTimer = type("T", (), {"singleShot": staticmethod(lambda ms, fn: fn())})
        self.main.win32api.MonitorFromWindow = lambda h, flag: 1
        self.main.win32api.GetMonitorInfo = lambda mon: {"Monitor": (0, 0, 1920, 1080)}
        self.press("f11")
        self.style, self.exstyle = F11_STYLE, F11_EX                  # what BVE reports in the F11 state: no caption, NOT topmost
        self.press("f11")
        self.assertFalse(self.o.is_borderless_fullscreen)


class ShowResetsGeometryOverlay(e4.FakeOverlay):
    """An Overlay whose native window comes up at another size when it is shown (OFS-1 live observation: (0,0,1600,900) for ~60 ms after a re-show)."""

    def show(self):
        super().show()
        self.applied_rect = None


class F2_ReShowGeometry(e4.ControllerCase):
    def setUp(self):
        super().setUp()
        self.overlay = ShowResetsGeometryOverlay()
        self.overlay.z_api = self.api
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: self.steps.append(1),
                                           timer=self.timer, clock=self.clock)

    def test_the_rectangle_is_applied_again_in_the_tick_that_shows_the_window(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(1)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.applied_rect, (100, 100, 800, 600))                 # the rectangle of the fake BVE window
        self.assertEqual(self.overlay.geoms.count((100, 100, 800, 600)), 2)               # before the show and again right after it

    def test_a_reshow_after_a_real_pause_is_corrected_in_the_same_tick(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.publish(True, False, 1)
        self.pump(40)                                                                    # longer than HIDE_GRACE_S: really hidden
        self.assertFalse(self.overlay.visible)
        self.publish(True, True, 1)
        self.pump(1)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.applied_rect, (100, 100, 800, 600))

    def test_no_second_application_while_the_window_is_already_in_place(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(1)
        count = len(self.overlay.geoms)
        self.pump(100)
        self.assertEqual(len(self.overlay.geoms), count)


class G_SizesMatch(unittest.TestCase):
    def test_equal_sizes_match(self):
        self.assertTrue(ot.sizes_match((1536, 864), (1536, 864)))

    def test_rounding_of_one_pixel_matches(self):
        self.assertTrue(ot.sizes_match((1097, 617), (1098, 616)))

    def test_two_pixels_or_more_do_not(self):
        self.assertFalse(ot.sizes_match((1097, 617), (1099, 617)))
        self.assertFalse(ot.sizes_match((1920, 1080), (1536, 864)))

    def test_each_dimension_is_checked(self):
        self.assertFalse(ot.sizes_match((1920, 1080), (1920, 864)))          # the height alone
        self.assertFalse(ot.sizes_match((1920, 1080), (1536, 1080)))         # the width alone

    def test_missing_values_do_not_match(self):
        self.assertFalse(ot.sizes_match(None, (1, 1)))
        self.assertFalse(ot.sizes_match((1, 1), None))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class H_LiveScaleChangeInTheOfficialFullscreen(unittest.TestCase):
    """OFS-1 live observation (Owner, Windows settings: 100 -> 125 -> 150 -> 175 -> 150 -> 100): in BVE's official fullscreen the PHYSICAL rectangle of the BVE window
    does not change with the display scale, Qt's device pixel ratio does. client_rect_applied looked only at the physical window rectangle, so the logical geometry
    stayed at the old scale and the HUD was drawn dpr times too big and displaced (HUD left edge at x=1862 of 1920 at 125%). It must notice the stale logical size."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["ofs1-live-scale"])
        import main
        cls.main = main

    class FakeGeometry(object):
        def __init__(self, w, h):
            self._w, self._h = w, h

        def width(self):
            return self._w

        def height(self):
            return self._h

    def fake_overlay(self, window_rect, qt_size, dpr):
        test = self

        class Fake(object):
            _client_phys = window_rect

            def winId(inner):
                return 4711

            def geometry(inner):
                return test.FakeGeometry(*qt_size)

            def devicePixelRatioF(inner):
                return dpr
        return Fake()

    def applied(self, window_rect, qt_size, dpr, rect=(0, 0, 1920, 1080)):
        main = self.main
        saved = main.overlay_get_window_rect
        main.overlay_get_window_rect = lambda hwnd: (window_rect[0], window_rect[1], window_rect[0] + window_rect[2], window_rect[1] + window_rect[3])
        try:
            return main.Overlay.client_rect_applied(self.fake_overlay(window_rect, qt_size, dpr), rect)
        finally:
            main.overlay_get_window_rect = saved

    def test_at_100_percent_a_placed_overlay_is_applied(self):
        self.assertTrue(self.applied((0, 0, 1920, 1080), (1920, 1080), 1.0))

    def test_after_a_change_to_125_with_the_old_logical_size_it_is_not_applied(self):
        self.assertFalse(self.applied((0, 0, 1920, 1080), (1920, 1080), 1.25))          # the live defect: physical rectangle right, logical size stale

    def test_at_125_with_the_logical_size_of_the_rectangle_it_is_applied(self):
        self.assertTrue(self.applied((0, 0, 1920, 1080), (1536, 864), 1.25))

    def test_every_scale_of_the_settings_dialog_needs_its_own_logical_size(self):
        for dpr, logical in ((1.25, (1536, 864)), (1.5, (1280, 720)), (1.75, (1097, 617))):
            with self.subTest(dpr=dpr):
                self.assertTrue(self.applied((0, 0, 1920, 1080), logical, dpr))
                self.assertFalse(self.applied((0, 0, 1920, 1080), (1920, 1080), dpr))

    def test_the_old_physical_check_still_applies(self):
        self.assertFalse(self.applied((5, 5, 300, 200), (1920, 1080), 1.0))
        self.assertFalse(self.applied((0, 0, 2400, 1350), (1920, 1080), 1.25))

    def test_a_scale_back_to_100_is_noticed_too(self):
        self.assertFalse(self.applied((0, 0, 1920, 1080), (1536, 864), 1.0))

    def test_an_unreadable_geometry_does_not_force_a_reapply_loop(self):
        main = self.main
        saved = main.overlay_get_window_rect
        main.overlay_get_window_rect = lambda hwnd: (0, 0, 1920, 1080)

        class Broken(object):
            _client_phys = (0, 0, 1920, 1080)

            def winId(inner):
                return 1

            def geometry(inner):
                raise RuntimeError("no geometry")
        try:
            self.assertTrue(main.Overlay.client_rect_applied(Broken(), (0, 0, 1920, 1080)))
        finally:
            main.overlay_get_window_rect = saved

    def test_the_real_overlay_is_applied_after_the_product_placement(self):
        main = self.main
        overlay = main.Overlay(udp_port=0)
        try:
            overlay.timer.stop()
            overlay.set_client_rect_physical(0, 0, 1920, 1080)
            self.app.processEvents()
            self.assertTrue(overlay.client_rect_applied((0, 0, 1920, 1080)))
        finally:
            overlay.close()
            overlay.deleteLater()


HINT_CHILD = os.path.join(ROOT, "tests", "ofs_hinting_child.py")


class I_FontHinting(unittest.TestCase):
    """OFS-1 (Owner: 'the HUD looks narrower at a display scale other than 100%'): clock 218 px at 100%, 214 px at 125-175% with the default hinting. The HUD fonts use
    full hinting: the same advances at 125% / 150% (and at most 1 px less at 175%), and exactly the old pixels at 100%."""

    # the digest of the pixels of the HUD (menu_state 0) and of the F1 menu (menu_state 1) at 100% BEFORE this change (default hinting, measured with the same child)
    OLD_PIXELS_100 = {0: "c51aff63179f6124", 1: "1f9854ae520fa95d"}

    def run_child(self, scale, menu_state=0):
        if not HAS_QT or importlib.util.find_spec("win32gui") is None:
            self.skipTest("PyQt6 / pywin32 not importable (INCONCLUSIVE)")
        import json
        import subprocess
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)                      # the real Windows platform: the font engine of the product
        env["QT_SCALE_FACTOR"] = str(scale)
        r = subprocess.run([sys.executable, "-B", HINT_CHILD, str(menu_state)], capture_output=True, timeout=120, cwd=ROOT, env=env, creationflags=0x08000000)
        out = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out + r.stderr.decode("utf-8", "replace"))
        return json.loads(out.strip().splitlines()[-1])

    def test_all_hud_fonts_use_full_hinting(self):
        result = self.run_child(1)
        self.assertEqual(result["hinting"], [3, 3, 3, 3, 3], result)          # QFont.HintingPreference.PreferFullHinting == 3 (Default 0, No 1, Vertical 2)

    def test_the_pixels_at_100_percent_are_exactly_the_old_ones(self):
        for state, digest in self.OLD_PIXELS_100.items():
            with self.subTest(menu_state=state):
                self.assertEqual(self.run_child(1, state)["digest"], digest)

    def test_the_clock_is_as_wide_at_125_and_150_percent_as_at_100_percent(self):
        widths = {scale: self.run_child(scale)["clock_w"] for scale in (1, 1.25, 1.5)}
        self.assertEqual(widths[1.25], widths[1], widths)
        self.assertEqual(widths[1.5], widths[1], widths)

    def test_at_175_percent_the_clock_is_at_most_one_pixel_narrower(self):
        w100, w175 = self.run_child(1)["clock_w"], self.run_child(1.75)["clock_w"]
        self.assertLessEqual(w100 - w175, 1, (w100, w175))
        self.assertGreaterEqual(w175, w100 - 1)

    def test_the_hud_box_is_the_same_at_every_scale(self):
        boxes = {scale: self.run_child(scale)["hud_bbox"] for scale in (1, 1.25, 1.5, 1.75)}
        for scale in (1.25, 1.5, 1.75):
            for a, b in zip(boxes[scale], boxes[1]):
                self.assertLessEqual(abs(a - b), 1, boxes)


REAL_CHECK = os.path.join(ROOT, "tests", "zorder_real_check_ofs.py")


class F_RealWindowsZOrder(unittest.TestCase):
    """REAL top-level windows (a topmost BVE stand-in, a real window of the class D3DProxyWindow, a later topmost dialog stand-in, the Overlay's flags) and the
    REAL Win32WindowApi: the HUD ends directly above the proxy window, in the topmost band, below the dialog. Needs a desktop; no BVE, no BveEX."""

    def test_the_hud_joins_the_topmost_band_directly_above_the_proxy_window(self):
        if not HAS_QT or importlib.util.find_spec("win32gui") is None:
            self.skipTest("PyQt6 / pywin32 not importable (INCONCLUSIVE)")
        import json
        import subprocess
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)                      # REAL windows: not the offscreen platform the other suites run with
        r = subprocess.run([sys.executable, REAL_CHECK], capture_output=True, timeout=120, cwd=ROOT, env=env, creationflags=0x08000000)
        out = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out + r.stderr.decode("utf-8", "replace"))
        result = json.loads(out.strip().splitlines()[-1])
        self.assertTrue(result["api_sees_the_proxy"], result)
        self.assertTrue(result["api_ignores_the_dialog"], result)
        self.assertTrue(result["api_ignores_other_pid"], result)
        self.assertTrue(result["bve_is_topmost"], result)
        self.assertFalse(result["hud_topmost_before_fix"], result)
        self.assertEqual(result["after_fix"], ["dialog", "hud", "proxy", "bve"], result)
        self.assertTrue(result["hud_topmost_after_fix"], result)
        self.assertTrue(result["hud_owner_is_bve"], result)
        self.assertEqual((result["in_place_sets"], result["in_place_sets_after_repeat"]), (1, 1), result)       # in place: nothing is done again
        self.assertEqual(result["reshow_without_dialog"], ["hud", "proxy", "bve"], result)
        self.assertTrue(result["hud_topmost_reshow"], result)
        self.assertEqual(result["after_new_proxy"], ["proxy2", "hud", "proxy", "bve"], result)     # a re-created proxy window lies over the HUD (the live defect) ...
        self.assertEqual(result["after_keep"], ["hud", "proxy2", "proxy", "bve"], result)          # ... and the keep step brings the HUD back over it
        self.assertTrue(result["hud_topmost_after_keep"], result)
        self.assertEqual((result["keep_sets"], result["keep_sets_after_repeat"]), (1, 1), result)
        self.assertIs(type(result["foreground_unchanged"]), bool, result)


class E_StaticPins(unittest.TestCase):
    @staticmethod
    def code_only(text):
        import re
        return re.sub(r"#.*", "", re.sub(r'"""[\s\S]*?"""', "", text))

    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            return self.code_only(handle.read())

    def test_topmost_is_named_only_inside_place_below(self):
        hud = self.read("managed_hud.py")
        self.assertEqual(hud.count("HWND_TOPMOST"), 1)
        body = hud[hud.index("def place_below"):hud.index("def is_bve_proxy")]
        self.assertIn("HWND_TOPMOST", body)

    def test_main_py_still_has_no_topmost_and_no_stay_on_top_hint(self):
        main = self.read("main.py")
        for token in ("WindowStaysOnTopHint", "HWND_TOPMOST", "raise_(", "activateWindow"):
            self.assertNotIn(token, main, token)

    def test_the_class_name_is_read_only_in_the_win32_layer(self):
        hud = self.read("managed_hud.py")
        self.assertEqual(hud.count("GetClassName"), 1)
        self.assertEqual(hud.count("D3DProxyWindow"), 1)
        ctl = hud[hud.index("class ManagedHudController"):]
        self.assertNotIn("GetClassName", ctl)
        self.assertNotIn("D3DProxyWindow", ctl)

    def test_the_controller_has_no_host_branch(self):
        hud = self.read("managed_hud.py")
        for token in ("Legacy", "AtsEx", "BveEx", "BveEX", "Current", "BVE5", "BVE6"):
            self.assertNotIn(token, hud, token)

    def test_the_f11_guard_is_in_both_window_functions_and_only_there(self):
        main = self.read("main.py")
        self.assertEqual(main.count("is_native_fullscreen("), 1)          # one reader of the rule ...
        self.assertEqual(main.count("self._bve_in_native_fullscreen()"), 2)   # ... asked by F11 and by F12


if __name__ == "__main__":
    unittest.main(verbosity=2)
