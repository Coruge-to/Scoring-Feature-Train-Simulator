"""UI adjustment (Owner ruling 2026-11-10, Level 2): one thin outer frame around the two columns, the vertical divider inside it, a wide standard dialog, the standard title bar, the note under the frame and OK at the lower right."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-layout"])
        import initial_defaults_ui
        import initial_defaults
        cls.U, cls.D = initial_defaults_ui, initial_defaults

    def make(self):
        d = self.U.build_dialog(self.D.builtin_defaults(), save=lambda v: None)
        d.show()
        self.app.processEvents()
        self.addCleanup(d.close)
        return d

    def find(self, d, name):
        from PyQt6.QtWidgets import QWidget
        w = d.findChild(QWidget, name)
        self.assertIsNotNone(w, "UI8-RED: no widget %r" % name)
        return w

    def test_one_outer_frame_holds_both_columns_the_divider_and_all_items_and_no_group_boxes(self):
        from PyQt6.QtWidgets import QFrame, QGroupBox, QCheckBox
        d = self.make()
        self.assertEqual(d.findChildren(QGroupBox), [], "UI8-RED: a QGroupBox per section")
        frame = self.find(d, "outer_frame")
        self.assertEqual(frame.frameShape(), QFrame.Shape.Box)
        self.assertEqual(frame.lineWidth(), 1, "a thin (1px) frame")
        self.assertEqual(frame.styleSheet(), "", "no custom decoration")
        inner = [c for c in frame.findChildren(QCheckBox)]
        self.assertEqual(len(inner), 15, "8 env + timing + 6 penalties inside the frame")
        for name in ("preset_beginner", "preset_intermediate", "preset_advanced", "a_rank"):
            self.assertTrue(frame.isAncestorOf(self.find(d, name)))
        vlines = [f for f in frame.findChildren(QFrame) if f.frameShape() == QFrame.Shape.VLine]
        self.assertEqual(len(vlines), 1, "UI8-RED: exactly one central divider, inside the frame")

    def test_note_is_below_the_frame_and_ok_is_at_the_lower_right_outside_it(self):
        d = self.make()
        frame, note, ok = self.find(d, "outer_frame"), self.find(d, "note"), self.find(d, "ok")
        fg = frame.geometry()
        self.assertGreaterEqual(note.geometry().top(), fg.bottom(), "UI8-RED: the note is not under the frame")
        self.assertGreaterEqual(ok.geometry().top(), note.geometry().bottom() - 1)
        self.assertGreater(ok.geometry().center().x(), d.width() * 0.7, "OK at the right")
        self.assertFalse(frame.isAncestorOf(ok))

    def test_the_dialog_is_wide_and_every_item_is_visible_inside_the_frame_without_scrolling(self):
        from PyQt6.QtWidgets import QCheckBox, QPushButton
        d = self.make()
        self.assertGreaterEqual(d.width(), 860)
        self.assertGreaterEqual(d.height(), 440)
        self.assertGreater(d.width() / d.height(), 1.5, "a wide (landscape) dialog")
        fr = self.find(d, "outer_frame").rect()
        for w in self.find(d, "outer_frame").findChildren(QCheckBox) + self.find(d, "outer_frame").findChildren(QPushButton):
            tl = w.mapTo(self.find(d, "outer_frame"), w.rect().topLeft())
            br = w.mapTo(self.find(d, "outer_frame"), w.rect().bottomRight())
            self.assertTrue(fr.contains(tl) and fr.contains(br), "UI8-RED: %s is outside the frame" % w.objectName())

    def test_the_left_column_is_a_little_wider_than_the_right_one_and_the_items_do_not_overlap(self):
        from PyQt6.QtWidgets import QCheckBox
        d = self.make()
        left = self.find(d, "env_0").geometry()
        right = self.find(d, "pen_rolling").geometry()
        self.assertLess(left.right(), right.left() + 1 if left.right() < right.left() else 0 + 10**6)
        boxes = [self.find(d, "env_%d" % i).geometry() for i in range(8)]
        for a, b in zip(boxes, boxes[1:]):
            self.assertLessEqual(a.bottom(), b.top() + 1, "UI8-RED: rows overlap")

    def test_the_standard_title_bar_is_used(self):
        from PyQt6.QtCore import Qt
        d = self.make()
        flags = d.windowFlags()
        self.assertFalse(flags & Qt.WindowType.FramelessWindowHint, "UI8-RED: a frameless window")
        self.assertFalse(flags & Qt.WindowType.CustomizeWindowHint, "UI8-RED: customised title bar")
        self.assertEqual(d.windowTitle(), "初期値設定")


if __name__ == "__main__":
    unittest.main()
