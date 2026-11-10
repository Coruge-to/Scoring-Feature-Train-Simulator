"""UI adjustment (Owner ruling 2026-11-10, Level 2): the standard Windows widgets (check boxes, spin box), a dense row pitch, the A boundary spin box with a focus-only mouse wheel, and the standard DPI following (no own layout per DPI). RED = fails on 8436eb1; messages start with 'UI9-RED'."""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def source():
    with open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8") as f:
        return f.read()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-win"])
        import initial_defaults_ui
        import initial_defaults
        cls.U, cls.D = initial_defaults_ui, initial_defaults

    def make(self, defaults=None, save=None):
        d = self.U.build_dialog(defaults or self.D.builtin_defaults(), save=save or (lambda v: None))
        d.show()
        self.app.processEvents()
        self.addCleanup(d.close)
        return d

    def find(self, d, name):
        from PyQt6.QtWidgets import QWidget
        w = d.findChild(QWidget, name)
        self.assertIsNotNone(w, "UI9-RED: no widget %r" % name)
        return w


class Checkboxes(Base):
    def test_no_custom_dark_checkbox_style_anywhere(self):
        from PyQt6.QtWidgets import QCheckBox
        d = self.make()
        self.assertEqual(d.styleSheet(), "")
        self.assertEqual(self.app.styleSheet(), "")
        for box in d.findChildren(QCheckBox):
            self.assertEqual(box.styleSheet(), "", "UI9-RED: a style sheet on %s" % box.objectName())
        src = source()
        self.assertNotRegex(src, r"indicator|QCheckBox\s*\{|#454e5e|setPalette", "UI9-RED: an own check indicator / palette")

    def test_the_standard_native_windows_check_box_style_is_used(self):
        d = self.make()
        style = self.find(d, "env_0").style().objectName().lower()
        self.assertEqual(style, "windowsvista", "UI9-RED: the check boxes are drawn by the %r style (the accent colour of the system theme, a dark slate here), not the Windows standard blue" % style)
        self.assertEqual(self.find(d, "a_rank").style().objectName().lower(), "windowsvista", "UI9-RED: the spin box is not drawn natively")

    def test_the_safety_intervention_is_a_normal_empty_standard_checkbox(self):
        from PyQt6.QtWidgets import QCheckBox
        d = self.make()
        box = self.find(d, "pen_safety")
        self.assertIsInstance(box, QCheckBox)
        self.assertTrue(box.isEnabled(), "not greyed out")
        self.assertFalse(box.isChecked())
        self.assertEqual(box.styleSheet(), "")


class RowPitch(Base):
    def test_rows_form_one_dense_list_and_both_columns_have_the_same_pitch(self):
        d = self.make()
        env = [self.find(d, "env_%d" % i) for i in range(8)]
        pen = [self.find(d, n) for n in ("pen_rolling", "pen_safety", "pen_speed", "pen_shock", "pen_eb", "pen_init")]

        def pitches(boxes):
            return [b2.geometry().top() - b1.geometry().top() for b1, b2 in zip(boxes, boxes[1:])]
        pe, pp = pitches(env), pitches(pen)
        self.assertEqual(len(set(pe + pp)), 1, "UI9-RED: the row pitch differs between rows / columns: %r %r" % (pe, pp))
        height = env[0].sizeHint().height()
        gap = pe[0] - height
        self.assertLessEqual(gap, 6, "UI9-RED: the gap between two rows is %d px (target: a continuous list, at most 6)" % gap)
        self.assertGreaterEqual(gap, 0, "rows never overlap")

    def test_no_stretch_or_fixed_row_height_between_the_items(self):
        src = source()
        self.assertNotRegex(src, r"setFixedHeight|setMinimumHeight|setRowMinimumHeight", "UI9-RED: a fixed row height")


class SpinBox(Base):
    def test_the_a_boundary_is_a_standard_spin_box_with_the_contract_values(self):
        from PyQt6.QtWidgets import QSpinBox, QAbstractSpinBox
        d = self.make()
        spin = self.find(d, "a_rank")
        self.assertIsInstance(spin, QSpinBox)
        self.assertEqual((spin.minimum(), spin.maximum(), spin.singleStep(), spin.wrapping()), (50, 90, 1, False), "UI9-RED: the spin box contract")
        self.assertEqual(spin.buttonSymbols(), QAbstractSpinBox.ButtonSymbols.UpDownArrows, "UI9-RED: not the integrated up/down buttons")
        self.assertEqual(spin.styleSheet(), "", "no custom triangles")
        self.assertEqual(spin.value(), 60)
        self.assertEqual(spin.suffix(), "", "%以上 is outside the spin box")

    def test_the_up_down_buttons_are_part_of_the_spin_box(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        spin.setValue(60)
        spin.stepUp()
        self.assertEqual(spin.value(), 61)
        spin.stepDown()
        spin.stepDown()
        self.assertEqual(spin.value(), 59)

    def _wheel(self, spin, delta):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(spin, ev)

    def test_the_wheel_changes_the_value_only_while_the_spin_box_has_the_focus(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        self.find(d, "env_0").setFocus()
        self.app.processEvents()
        spin.setValue(60)
        self._wheel(spin, 120)
        self.assertEqual(spin.value(), 60, "UI9-RED: the wheel changed the value without the focus")
        self._wheel(spin, -120)
        self.assertEqual(spin.value(), 60)
        spin.setFocus()
        spin.activateWindow()
        self.app.processEvents()
        if not spin.hasFocus():
            self.skipTest("the offscreen platform gave no focus")
        self._wheel(spin, 120)
        self.assertEqual(spin.value(), 61, "UI9-RED: the wheel up does not add 1 with the focus")
        self._wheel(spin, -120)
        self._wheel(spin, -120)
        self.assertEqual(spin.value(), 59, "UI9-RED: the wheel down does not subtract 1 with the focus")

    def test_the_wheel_never_leaves_50_to_90_and_never_wraps(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        spin.setFocus()
        spin.activateWindow()
        self.app.processEvents()
        if not spin.hasFocus():
            self.skipTest("the offscreen platform gave no focus")
        spin.setValue(50)
        self._wheel(spin, -120)
        self.assertEqual(spin.value(), 50, "UI9-RED: below 50")
        spin.setValue(90)
        self._wheel(spin, 120)
        self.assertEqual(spin.value(), 90, "UI9-RED: above 90 / wrapped")

    def test_the_focus_policy_does_not_take_the_focus_from_the_wheel(self):
        from PyQt6.QtCore import Qt
        d = self.make()
        self.assertEqual(self.find(d, "a_rank").focusPolicy(), Qt.FocusPolicy.StrongFocus, "UI9-RED: the wheel must not give the focus")

    def test_ok_refuses_every_invalid_text_keeps_the_file_and_returns_the_focus(self):
        import tempfile
        for text in ("", "49", "91", "5x", "６０", "abc", "60.5", " "):
            saved = []
            d = self.make(save=lambda v: saved.append(v))
            spin = self.find(d, "a_rank")
            spin.lineEdit().setText(text)
            self.find(d, "ok").click()
            self.app.processEvents()
            valid = bool(re.fullmatch(r"[0-9]+", text)) and 50 <= int(text or 0) <= 90 if text.isascii() else False
            self.assertEqual(len(saved), 1 if valid else 0, "UI9-RED: text %r valid=%s saved=%s" % (text, valid, saved))
            if not valid:
                self.assertTrue(self.find(d, "message").text(), "an error is shown for %r" % text)
                self.assertTrue(d.isVisible())
                self.assertTrue(spin.hasFocus() or spin.lineEdit().hasFocus() or not d.isActiveWindow(), "UI9-RED: the focus did not return to the A boundary input")


class Dpi(Base):
    def test_no_own_layout_per_dpi_and_no_fixed_physical_size_in_the_window_module(self):
        src = source()
        for bad in ("devicePixelRatio", "logicalDotsPerInch", "physicalDotsPerInch", "setFamily", "QFont(", "font-size", "setPointSize", "setPixelSize", "QGuiApplication", "screen()", "dpi", "DPI"):
            self.assertNotIn(bad, src, "UI9-RED: %r in the window module" % bad)

    def _probe(self, scale):
        code = (
            "import os,sys,json\n"
            "os.environ['QT_QPA_PLATFORM']='offscreen'\n"
            "os.environ['QT_SCALE_FACTOR']='%s'\n"
            "sys.path.insert(0,%r)\n"
            "from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton, QWidget\n"
            "app=QApplication(['p'])\n"
            "import initial_defaults_ui as U, initial_defaults as D\n"
            "d=U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()\n"
            "fr=d.findChild(QWidget,'outer_frame')\n"
            "boxes=fr.findChildren(QCheckBox)+fr.findChildren(QPushButton)\n"
            "bad_clip=[b.objectName() for b in boxes if b.width()<b.sizeHint().width()]\n"
            "geo=[(b.objectName(),b.mapTo(d,b.rect().topLeft()).y(),b.mapTo(d,b.rect().bottomRight()).y(),b.mapTo(d,b.rect().topLeft()).x()) for b in boxes]\n"
            "overlap=[]\n"
            "for i,a in enumerate(geo):\n"
            "    for b in geo[i+1:]:\n"
            "        if a[3]==b[3] and not (a[2]<b[1] or b[2]<a[1]): overlap.append((a[0],b[0]))\n"
            "from PyQt6.QtCore import QRect\n"
            "out=[b.objectName() for b in boxes if not d.rect().contains(b.mapTo(d,b.rect().topLeft())) or not d.rect().contains(b.mapTo(d,b.rect().bottomRight()))]\n"
            "print(json.dumps({'clip':bad_clip,'overlap':overlap,'outside':out,'size':[d.width(),d.height()],'hint':[d.sizeHint().width(),d.sizeHint().height()],'min':[d.minimumSizeHint().width(),d.minimumSizeHint().height()]}))\n"
        ) % (scale, ROOT)
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_125_150_175_percent_have_no_clipped_text_overlap_or_item_outside_the_dialog(self):
        base = None
        for pct in (100, 125, 150, 175):
            got = self._probe(pct / 100.0)
            self.assertEqual(got["clip"], [], "UI9-RED: clipped text at %d%%: %r" % (pct, got))
            self.assertEqual(got["overlap"], [], "UI9-RED: overlapping items at %d%%: %r" % (pct, got))
            self.assertEqual(got["outside"], [], "UI9-RED: items outside the dialog at %d%%" % pct)
            self.assertLessEqual(got["min"][0], got["size"][0], "the minimum width fits the logical dialog at %d%%" % pct)
            self.assertLessEqual(got["min"][1], got["size"][1], "the minimum height fits the logical dialog at %d%%" % pct)
            if base is None:
                base = got["size"]
            self.assertEqual(got["size"], base, "UI9-RED: the logical layout differs at %d%% (100%% is the logical master)" % pct)


if __name__ == "__main__":
    unittest.main()
