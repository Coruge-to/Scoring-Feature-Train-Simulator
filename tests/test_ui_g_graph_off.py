"""Stage UI-2: the Decel G / Notch telemetry GRAPH of the F2 diagnostics is not drawn (a provisional Owner setting, 2026-11-05: the chart covered the cab desk and the door pilot lamp in the live photos of S-02 / S-01).

Owner contract: the F2 diagnostic TEXT stays; the chart (the bottom-left telemetry graph: its background, its lines, its two zone lines, its caption) is gone. F2 itself is unchanged: it still toggles debug_all_penalties AND show_graph together
(main.py), and the diagnostic text is drawn while show_graph is on.
Update 2026-11-08 (formal LastStop BveG): the chart plotted the CalcG history, which is retired, so the chart CODE and its constant (hud_ui.G_GRAPH_ENABLED) are removed too (UG_04 / UG_05 now guard that).
The REAL draw_hud runs on the real Overlay (offscreen) with a recording painter."""
import os
import socket
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from PyQt6.QtGui import QImage, QPainter
    HAS_QT = True
except Exception:                       # pragma: no cover
    HAS_QT = False


def port_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 54321))
        return True
    except OSError:
        return False
    finally:
        s.close()


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


if HAS_QT:
    class Recorder(QPainter):
        def __init__(self, image):
            super().__init__(image)
            self.texts, self.paths, self.rects = [], 0, []       # paths: the chart lines only (green G, blue notch); the text stroke of the HUD uses drawPath too

        def drawText(self, *args):
            self.texts.append(str(args[-1]))
            return super().drawText(*args)

        def drawPath(self, path):
            c = self.pen().color()
            if (c.red(), c.green(), c.blue()) in ((0, 255, 100), (100, 150, 255)):
                self.paths += 1
            return super().drawPath(path)

        def drawRect(self, *args):
            self.rects.append(tuple(args))
            return super().drawRect(*args)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class GraphOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if not port_free():
            raise unittest.SkipTest("UDP 54321 is in use (a running TS Scoring is never touched): INCONCLUSIVE")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["ui2"])
        import main
        import hud_ui
        cls.main, cls.hud_ui = main, hud_ui

    def setUp(self):
        self._wdl = self.main.write_desktop_log
        self.main.write_desktop_log = lambda *a, **k: None
        self.o = self.main.Overlay()
        self.o.timer.stop()
        self.addCleanup(self.cleanup_overlay)

    def cleanup_overlay(self):
        self.main.write_desktop_log = self._wdl
        self.o.udp_socket.close()
        self.o.close()
        self.o.deleteLater()

    def render(self, show_graph=True, history=True, graph_enabled=None):
        o = self.o
        o.show_graph = show_graph
        o.bve_time_ms = 100000
        existed = hasattr(self.hud_ui, "G_GRAPH_ENABLED")
        original = getattr(self.hud_ui, "G_GRAPH_ENABLED", None)
        if graph_enabled is not None:
            self.hud_ui.G_GRAPH_ENABLED = graph_enabled
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        painter = Recorder(image)
        try:
            self.hud_ui.draw_hud(o, painter, 1920)
        finally:
            painter.end()
            if existed:
                self.hud_ui.G_GRAPH_ENABLED = original
            elif hasattr(self.hud_ui, "G_GRAPH_ENABLED"):
                del self.hud_ui.G_GRAPH_ENABLED
        return painter

    def test_UG_01_RED_the_chart_is_not_drawn_with_F2_on_and_a_history(self):
        p = self.render()
        self.assertEqual(p.paths, 0, "RED on the baseline: the G / notch lines are drawn with drawPath")
        for text in p.texts:
            self.assertFalse(text.startswith("[TELEMETRY - 10 Seconds]"), text)
            self.assertNotIn("ZONE1", text)
            self.assertNotIn("ZONE2", text)
        self.assertNotIn((5, 1080 - 250 - 40, 800, 250), [tuple(int(v) for v in r) for r in p.rects], "the chart background (800 x 250 at the bottom left) is not drawn")

    def test_UG_02_GUARD_the_F2_diagnostic_text_stays(self):
        p = self.render()
        joined = "\n".join(p.texts)
        for fragment in ("[TIMING] Mode:", "[STATE] 1st_Sta:", "[DEBUG X-RAY]", "BrakeType:", "Target_Cap_Val:"):
            self.assertIn(fragment, joined, fragment)
        self.assertTrue(any(len(r) == 4 and int(r[2]) == 950 for r in p.rects), "the dark background of the diagnostic text (950 wide) is still drawn")

    def test_UG_03_GUARD_with_F2_off_neither_the_text_nor_the_chart(self):
        p = self.render(show_graph=False)
        self.assertEqual(p.paths, 0)
        self.assertFalse([t for t in p.texts if t.startswith("[TIMING]") or t.startswith("[TELEMETRY")])

    def test_UG_04_the_chart_is_retired_with_the_calcg_history_no_constant_no_caption(self):
        self.assertFalse(hasattr(self.hud_ui, "G_GRAPH_ENABLED"), "the chart constant is gone with the chart")
        p = self.render()
        self.assertEqual(p.paths, 0)
        self.assertFalse([t for t in p.texts if t.startswith("[TELEMETRY - 10 Seconds]") or "ZONE1" in t or "ZONE2" in t])

    def test_UG_05_the_source_has_no_chart_code_and_the_text_block_is_still_switched_by_show_graph_only(self):
        text = read("hud_ui.py")
        for banned in ("G_GRAPH_ENABLED", "g_history", "TELEMETRY - 10 Seconds", "ZONE1", "path_notch"):
            self.assertNotIn(banned, text)
        self.assertEqual(text.count("    if self.show_graph:\n        painter.setPen(Qt.PenStyle.NoPen)"), 1, "the diagnostic text block is still switched by show_graph only")

    def test_UG_06_GUARD_F2_still_toggles_the_text_switch_and_the_chart_switch_together(self):
        text = read("main.py")
        i = text.index("elif key == 'f2':")
        block = text[i:i + 400]
        self.assertIn("self.debug_all_penalties = not getattr(self, 'debug_all_penalties', False)", block)
        self.assertIn("self.show_graph = not getattr(self, 'show_graph', False)", block)


if __name__ == "__main__":
    unittest.main()
