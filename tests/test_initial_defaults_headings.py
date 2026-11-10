"""UI adjustment (Owner ruling 2026-11-10): headings without brackets, only bold, same size as the items, the system font (no fixed font, no heading-only size / decoration)."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HEADINGS = ("環境設定", "採時駅設定", "減点項目設定", "簡単設定")


class Headings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-headings"])
        import initial_defaults_ui
        import initial_defaults
        cls.U, cls.D = initial_defaults_ui, initial_defaults

    def labels(self, d):
        from PyQt6.QtWidgets import QLabel
        return {w.text(): w for w in d.findChildren(QLabel)}

    def test_the_four_headings_have_no_brackets_and_only_they_are_bold(self):
        d = self.U.build_dialog(self.D.builtin_defaults(), save=lambda v: None)
        labels = self.labels(d)
        for h in HEADINGS:
            self.assertIn(h, labels, "UI7-RED: heading %s missing" % h)
            self.assertTrue(labels[h].font().bold())
        for text, w in labels.items():
            if text not in HEADINGS:
                self.assertFalse(w.font().bold(), "a non-heading label is bold: %s" % text)
            self.assertNotRegex(text, "[《》【】「」]", "UI7-RED: a decoration bracket is shown")
        d.deleteLater()

    def test_heading_font_is_the_item_font_with_bold_only_and_no_decoration(self):
        from PyQt6.QtWidgets import QCheckBox
        d = self.U.build_dialog(self.D.builtin_defaults(), save=lambda v: None)
        item = d.findChild(QCheckBox, "pen_rolling").font()
        for h in HEADINGS:
            w = self.labels(d)[h]
            f = w.font()
            self.assertEqual(f.family(), item.family(), "UI7-RED: the heading uses another font family")
            self.assertEqual(f.pointSizeF(), item.pointSizeF(), "UI7-RED: the heading size differs")
            self.assertEqual(f.pixelSize(), item.pixelSize())
            self.assertFalse(f.underline())
            self.assertEqual(w.styleSheet(), "", "UI7-RED: the heading has a style sheet (background / size)")
        d.deleteLater()

    def test_no_fixed_font_is_named_in_the_window_module(self):
        src = open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8").read()
        for bad in ("MS ゴシック", "MS Gothic", "setFamily", "QFont(", "font-family", "font-size", "setPointSize", "setPixelSize"):
            self.assertNotIn(bad, src, "UI7-RED: %r in the window module" % bad)
        self.assertEqual(re.findall(r"font-size", src), [])


if __name__ == "__main__":
    unittest.main()
