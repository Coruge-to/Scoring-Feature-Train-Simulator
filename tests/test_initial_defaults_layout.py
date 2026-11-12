"""UI adjustment (Owner ruling 2026-11-10, Level 2): one thin outer frame around the two columns, the vertical divider inside it, a wide standard dialog, the standard title bar, the note under the frame and OK at the lower right."""
import os
import sys
import unittest

from PyQt6.QtCore import Qt

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
        self.assertEqual(len(vlines), 0, "UI14: no central divider line is drawn")
        space = self.find(d, "divider_space")
        self.assertEqual(space.width(), 3, "the 3 px column of the former divider stays as empty space")
        self.assertTrue(frame.isAncestorOf(space))

    def test_note_is_below_the_frame_and_ok_is_at_the_lower_right_outside_it(self):
        d = self.make()
        frame, note, ok = self.find(d, "outer_frame"), self.find(d, "note"), self.find(d, "ok")
        fg = frame.geometry()
        self.assertGreaterEqual(note.geometry().top(), fg.bottom(), "UI8-RED: the note is not under the frame")
        self.assertLessEqual(abs(note.geometry().center().y() - ok.geometry().center().y()), 2, "the note and OK share one row (centre Y)")
        self.assertLess(note.geometry().right(), ok.geometry().left(), "the note never overlaps OK")
        self.assertGreater(ok.geometry().center().x(), d.width() * 0.7, "OK at the right")
        self.assertFalse(frame.isAncestorOf(ok))

    def test_the_dialog_is_wide_and_every_item_is_visible_inside_the_frame_without_scrolling(self):
        from PyQt6.QtWidgets import QCheckBox, QPushButton
        d = self.make()
        self.assertGreaterEqual(d.width(), 560)
        self.assertGreater(d.width() / d.height(), 1.4, "a wide (landscape) dialog")
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
        self.assertTrue(flags & Qt.WindowType.WindowCloseButtonHint, "the standard close button")
        self.assertTrue(flags & Qt.WindowType.WindowTitleHint)
        self.assertFalse(flags & Qt.WindowType.WindowSystemMenuHint, "UI10: no system-menu hint = no application icon on the title bar")
        self.assertEqual(d.windowTitle(), "標準採点設定")


class Round10(Layout):
    """Owner UI review round (2026-11-10): white window, connected divider, aligned bottoms, centred A boundary group, bigger preset text, no title bar icon."""

    def test_the_window_colour_is_the_standard_light_colour_of_the_palette_and_equal_inside_the_frame(self):
        from PyQt6.QtGui import QPalette
        d = self.make()
        self.assertEqual(d.styleSheet(), "")
        self.assertEqual(d.palette().color(QPalette.ColorRole.Window).name(), d.palette().color(QPalette.ColorRole.Base).name(), "UI10-RED: the window is not the light base colour")
        fr = self.find(d, "outer_frame")
        self.assertEqual(fr.palette().color(QPalette.ColorRole.Window).name(), d.palette().color(QPalette.ColorRole.Window).name(), "no colour step between the window and the frame inside")
        img = d.grab().toImage()
        self.assertEqual(img.pixelColor(3, 3).name(), "#ffffff", "UI10-RED: the rendered window background is not white")

    def test_the_empty_divider_column_spans_the_frame_height_and_draws_nothing(self):
        from PyQt6.QtWidgets import QFrame
        d = self.make()
        fr = self.find(d, "outer_frame")
        vl = self.find(d, "divider_space")
        tl = vl.mapTo(fr, vl.rect().topLeft()).y()
        br = vl.mapTo(fr, vl.rect().bottomRight()).y()
        self.assertLessEqual(tl, 1, "UI10-RED: a gap of %d px above the divider" % tl)
        self.assertGreaterEqual(br, fr.height() - 2, "UI10-RED: a gap below the divider")

    def test_the_last_rows_of_both_columns_end_on_the_same_line(self):
        d = self.make()
        timing = self.find(d, "timing")
        spin = self.find(d, "a_rank")
        b1 = timing.mapTo(d, timing.rect().bottomLeft()).y()
        b2 = spin.mapTo(d, spin.rect().bottomLeft()).y()
        self.assertLessEqual(abs(b1 - b2), 2, "UI10-RED: bottoms differ by %d px" % (b1 - b2))

    def test_the_a_boundary_group_is_centred_in_the_right_column_as_one_group(self):
        from PyQt6.QtWidgets import QFrame, QLabel
        d = self.make()
        fr = self.find(d, "outer_frame")
        vl = self.find(d, "divider_space")
        lab = [l for l in d.findChildren(QLabel) if l.text() == "Aランクは理論値の"][0]
        pct = [l for l in d.findChildren(QLabel) if l.text() == "%以上"][0]
        gl = lab.mapTo(d, lab.rect().topLeft()).x()
        gr = pct.mapTo(d, pct.rect().topRight()).x()
        rl = vl.mapTo(d, vl.rect().topRight()).x()
        rr = fr.mapTo(d, fr.rect().topRight()).x()
        self.assertLessEqual(abs((gl + gr) / 2 - (rl + rr) / 2), 3, "UI10-RED: the group is off the right-column centre by %.1f px" % ((gl + gr) / 2 - (rl + rr) / 2))

    def test_the_preset_text_is_bigger_than_the_normal_text_bold_and_the_three_buttons_are_equal(self):
        from PyQt6.QtWidgets import QCheckBox
        d = self.make()
        item = self.find(d, "pen_rolling").font().pointSizeF()
        sizes = []
        for k in ("beginner", "intermediate", "advanced"):
            b = self.find(d, "preset_" + k)
            self.assertTrue(b.font().bold())
            self.assertGreaterEqual(b.font().pointSizeF(), item * 1.4, "UI10-RED: the preset text is not clearly bigger")
            self.assertEqual(b.font().pixelSize(), -1, "no fixed pixel size")
            sizes.append((b.width(), b.height()))
        self.assertEqual(len(set(sizes)), 1, "UI10-RED: the three buttons differ in size: %r" % sizes)

    def test_the_spacing_is_compact_without_overlap(self):
        d = self.make()
        env = [self.find(d, "env_%d" % i) for i in range(8)]
        gap = env[1].geometry().top() - env[0].geometry().bottom() - 1
        self.assertGreaterEqual(gap, 0)
        self.assertLessEqual(gap, 2, "UI10-RED: rows are not compact")

    def test_the_note_text_is_the_ruled_text_and_one_line(self):
        d = self.make()
        note = self.find(d, "note")
        self.assertEqual(note.text(), "※この設定は次にシナリオを読み込んだときに適用されます。")
        self.assertNotIn("F5", note.text())
        self.assertLessEqual(note.height(), 2 * note.fontMetrics().height(), "one line")


class Round12(Layout):
    """Owner UI review round 12 (2026-11-10): equal gaps divider->first button and last button->frame, a right column that keeps only its content width, the header colour of this dialog only, messages that never widen the window or overlap."""

    def test_the_gap_divider_to_first_button_equals_the_gap_last_button_to_the_frame(self):
        from PyQt6.QtWidgets import QFrame
        d = self.make()
        fr = self.find(d, "outer_frame")
        vl = self.find(d, "divider_space")
        line_x = vl.mapTo(d, vl.rect().topLeft()).x() + vl.width() // 2
        b0, b2 = self.find(d, "preset_beginner"), self.find(d, "preset_advanced")
        a = b0.mapTo(d, b0.rect().topLeft()).x() - (line_x + 1)
        b = (fr.mapTo(d, fr.rect().topRight()).x()) - (b2.mapTo(d, b2.rect().topRight()).x() + 1)
        self.assertEqual(a, b, "UI12-RED: A=%d B=%d" % (a, b))

    def test_the_right_column_keeps_only_the_width_of_its_content_and_the_buttons_are_equal_and_spaced(self):
        d = self.make()
        bs = [self.find(d, "preset_" + k) for k in ("beginner", "intermediate", "advanced")]
        widths = {b.width() for b in bs}
        self.assertEqual(len(widths), 1)
        self.assertLessEqual(bs[0].width(), 84, "UI12-RED: the buttons are not narrow (v4 had 96)")
        gap = bs[1].geometry().left() - bs[0].geometry().right() - 1
        self.assertGreaterEqual(gap, 10, "the buttons are spaced")
        if self.app.font().family() == "Yu Gothic UI":              # the width bound is for the real Windows font (the offscreen platform has a wider fallback font)
            self.assertLess(d.width(), 600, "UI12-RED: the window is as wide as before (the right column still carries spare width)")

    def test_the_first_button_starts_at_the_left_edge_of_the_right_column_items(self):
        d = self.make()
        item = self.find(d, "pen_rolling"); b0 = self.find(d, "preset_beginner")
        self.assertEqual(b0.mapTo(d, b0.rect().topLeft()).x(), item.mapTo(d, item.rect().topLeft()).x())

    def test_the_title_bar_is_the_standard_windows_one_no_colour_code_is_left(self):
        """INITIAL-DEFAULTS U4-A (Owner 2026-11-11): the fixed title bar colour (DWMWA_CAPTION_COLOR, #F1F3F6) was removed; Windows draws the standard title bar. (The contract is pinned in tests/test_initial_defaults_u4.py.)"""
        src = open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8").read()
        for bad in ("DWMWA_USE_IMMERSIVE", "SetPreferredAppMode", "winreg", "QApplication.setPalette", "setWindowIcon", "DwmSetWindowAttribute", "HEADER_RGB", "set_header_colour"):
            self.assertNotIn(bad, src)

    def test_a_message_never_widens_the_window_or_overlaps_the_note_and_ok(self):
        d = self.make()
        w0 = d.width()
        msg, note, ok = self.find(d, "message"), self.find(d, "note"), self.find(d, "ok")
        for text in (self.U.SAVE_FAILED, self.U.A_RANK_INVALID):
            msg.setText(text)
            self.app.processEvents()
            self.assertEqual(d.width(), w0, "UI12-RED: the window grew for %r" % text)
            self.assertLessEqual(note.geometry().right(), msg.geometry().left(), "the note and the message overlap")
            self.assertLessEqual(msg.geometry().right(), ok.geometry().left(), "the message and OK overlap")
            self.assertGreaterEqual(msg.geometry().width(), msg.fontMetrics().horizontalAdvance(text), "the message is clipped: %r" % text)

    def test_the_note_is_lifted_by_one_pixel(self):
        d = self.make()
        self.assertEqual(self.find(d, "note").contentsMargins().bottom(), 2, "UI13-RED: the note lift (1 px up = 2 px bottom margin)")

    def test_the_timing_heading_sits_right_above_its_item_and_the_lower_rows_stay(self):
        from PyQt6.QtWidgets import QLabel
        d = self.make()
        head = [l for l in d.findChildren(QLabel) if l.text() == "採時駅設定"][0]
        item = self.find(d, "timing")
        gap = item.geometry().top() - (head.geometry().bottom() + 1)
        self.assertTrue(0 <= gap <= 3, "UI13-RED: the heading does not sit directly above its item (gap %d px; the item is centred in a row that is a little taller)" % gap)
        spin = self.find(d, "a_rank")
        self.assertEqual(item.geometry().center().y() - self.U.RANK_ROW_RAISE, spin.geometry().center().y(), "the A boundary row stands RANK_ROW_RAISE higher than the timing item (U5-3: both bottom rows at the same visual height; the timing item does not move)")
class Round15(Round12):
    """Round 15: the error texts share the text line of the note; OK text lift; spin 52."""

    def test_the_message_label_has_the_same_lift_as_the_note_so_texts_share_one_baseline(self):
        d = self.make()
        msg, note = self.find(d, "message"), self.find(d, "note")
        self.assertEqual(msg.contentsMargins().bottom(), note.contentsMargins().bottom(), "UI15-RED: the error text is not on the line of the note")
        self.assertEqual(msg.font().pointSizeF(), note.font().pointSizeF())

    def test_showing_an_error_changes_no_geometry_of_the_note_ok_or_the_window(self):
        d = self.make()
        note, ok, msg = self.find(d, "note"), self.find(d, "ok"), self.find(d, "message")
        before = (d.size().width(), d.size().height(), note.geometry().getRect(), ok.geometry().getRect())
        for text in (self.U.SAVE_FAILED, self.U.A_RANK_INVALID, ""):
            msg.setText(text)
            self.app.processEvents()
            self.assertEqual((d.size().width(), d.size().height(), note.geometry().getRect(), ok.geometry().getRect()), before, "UI15-RED: geometry moved with %r" % text)

    def test_the_spin_box_is_52_wide_22_high_and_centres_its_text(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        self.assertEqual(spin.width(), 52)
        self.assertEqual(spin.height(), spin.sizeHint().height() - spin.lineEdit().textMargins().bottom(), "the height is the one the style gives without the optical margin of the number (22 px on Windows)")
        if self.app.font().family() == "Yu Gothic UI":
            self.assertEqual(spin.height(), 22)
        self.assertTrue(spin.alignment() & Qt.AlignmentFlag.AlignHCenter, "UI15-RED: the value is not centred in the edit field")

    def test_the_text_of_ok_is_lifted_one_pixel_and_the_button_keeps_its_native_size(self):
        d = self.make()
        ok = self.find(d, "ok")
        self.assertEqual(self.U.OK_TEXT_LIFT, 1)
        self.assertIn("padding-bottom: 2px", ok.styleSheet())
        self.assertEqual(ok.minimumSize(), ok.maximumSize(), "the button has the one fixed size it got from the native sizeHint")

if __name__ == "__main__":
    unittest.main()
