"""INITIAL-DEFAULTS U4 (Owner 2026-11-11): the standard Windows look of the 'initial defaults' window.

U4-A  the fixed title bar colour (#F1F3F6 through DWMWA_CAPTION_COLOR) is gone: the window is a plain QDialog and Windows draws its standard title bar (active / inactive colours, the close button, the move) - nothing
      replaces it (no Mica / Acrylic / gradient / transparency / blur / background reading / BVE colour code / per-position branch). The dialog keeps: × / Alt+F4 / Esc cancel without saving, the OK save, the re-opening.
U4-B  the indicator of the check boxes of this window is ONE logical size, 13 (PM_IndicatorWidth / PM_IndicatorHeight), given by the OpticalStyle (the style of these check boxes only); every other metric and every drawing
      is delegated to the native style (the checked blue tick, the white box, the grey disabled box, hover and focus come from windowsvista); no scale branch; CHECKBOX_OPTICAL_LIFT stays 0.5.
RED = fails on the tree of fe668d2. Messages start with 'U4-RED' (a missing contract) or 'U4-GUARD' (a contract that already holds and must stay). The REAL Windows scales (100 / 125 / 150 / 175 %) are measured by the
external probe of the deliverable (a deterministic offscreen test can not change the Windows scale)."""
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import idf1_red_support as X  # noqa: E402

ROOT = X.ROOT
FORBIDDEN_TITLE_CODE = ("DWMWA", "DwmSetWindowAttribute", "dwmapi", "HEADER_RGB", "set_header_colour", "F1F3F6", "0xF1, 0xF3, 0xF6", "Mica", "Acrylic", "SYSTEMBACKDROP", "WA_TranslucentBackground",
                        "setGraphicsEffect", "QGraphicsBlurEffect", "grabWindow", "backdrop")
# IO-1 (2026-11-12): "winId" used to be listed here because the title bar colour code needed the HWND. The window-ownership code needs the HWND too (Qt's transient parent / WS_EX_APPWINDOW), and the colour code is still caught by every
# DWM / colour token above, so a bare winId is no longer a title-bar signal. The title bar stays the Windows standard one (no DWM attribute, no colour, no backdrop).


def setUpModule():
    X.redirect_profile("ts-u4-")


def tearDownModule():
    X.restore_profile()


def module_source():
    return X.source("initial_defaults_ui.py")


def optical_style_methods():
    tree = ast.parse(module_source())
    cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "OpticalStyle"][0]
    return cls, {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


# ================================================================================================================ U4-A
class TitleBar(X.DialogBase):
    def test_a_no_fixed_title_bar_colour_code_exists(self):
        for name in ("DWMWA_CAPTION_COLOR", "HEADER_RGB", "set_header_colour"):
            self.assertFalse(hasattr(self.U, name), "U4-RED: initial_defaults_ui still defines %s" % name)

    def test_a_the_source_has_no_title_bar_colour_or_backdrop_code(self):
        text = module_source()
        found = [bad for bad in FORBIDDEN_TITLE_CODE if bad.lower() in text.lower()]
        self.assertEqual(found, [], "U4-RED: the source still contains title bar colour / backdrop code: %r" % found)

    def test_a_no_fixed_colour_value_f1f3f6_anywhere_in_the_module(self):
        text = module_source().lower()
        self.assertNotIn("f1f3f6", text, "U4-RED: #F1F3F6 is still written")
        self.assertNotIn("0xf6f3f1", text, "U4-RED: the COLORREF of #F1F3F6 is still written")

    def test_a_the_dialog_is_a_plain_qdialog_and_the_title_bar_is_left_to_windows(self):
        from PyQt6.QtWidgets import QDialog
        d = self.make()
        self.assertIs(type(d), QDialog, "U4-RED: the window is %s, not a plain QDialog (the derived class only coloured the title bar)" % type(d).__name__)

    def test_a_showing_the_window_calls_no_dwm_attribute(self):
        import ctypes
        if sys.platform != "win32":
            self.skipTest("Windows only")
        calls = []
        dwm = ctypes.windll.dwmapi
        real = dwm.DwmSetWindowAttribute
        setattr(dwm, "DwmSetWindowAttribute", lambda *a: calls.append(a) or 0)
        self.addCleanup(lambda: setattr(dwm, "DwmSetWindowAttribute", real))
        d = self.make()
        d.close()
        d2 = self.make()
        self.assertEqual(calls, [], "U4-RED: showing the window called DwmSetWindowAttribute %d time(s)" % len(calls))

    def test_a_the_window_title_flags_and_object_name_are_unchanged(self):
        from PyQt6.QtCore import Qt
        d = self.make()
        self.assertEqual(d.windowTitle(), "初期値設定", "U4-GUARD: the title changed")
        self.assertEqual(d.objectName(), "initial_defaults_dialog")
        flags = d.windowFlags()
        for flag in (Qt.WindowType.WindowTitleHint, Qt.WindowType.WindowCloseButtonHint, Qt.WindowType.CustomizeWindowHint):
            self.assertTrue(flags & flag, "U4-GUARD: the window flag %s is gone" % flag)
        self.assertFalse(flags & Qt.WindowType.WindowSystemMenuHint, "U4-GUARD: the system menu hint came back (the application icon)")

    def test_a_nothing_else_is_touched_by_the_module_application_palette_style_or_theme(self):
        text = module_source()
        for bad in ("QApplication.setPalette", "DWMWA_USE_IMMERSIVE", "SetPreferredAppMode", "winreg", "setWindowIcon", "setStyleSheet(\"QDialog", "setAttribute(Qt.WidgetAttribute.WA_"):
            self.assertNotIn(bad, text, "U4-GUARD: %s" % bad)

    # ---- the operations are kept
    def test_a_the_x_button_alt_f4_close_cancels_without_saving(self):
        d = self.make()
        self.set_spin_text(d, "75")
        d.close()
        self.assertEqual(self.saves, [], "U4-GUARD: closing the window saved")
        self.assertFalse(d.isVisible())

    def test_a_escape_cancels_without_saving(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        d = self.make()
        self.find(d, "preset_advanced").click()
        QTest.keyClick(d, Qt.Key.Key_Escape)
        self.app_events()
        self.assertEqual(self.saves, [], "U4-GUARD: Escape saved")
        self.assertFalse(d.isVisible(), "U4-GUARD: Escape did not close the window")

    def test_a_the_window_can_be_shown_again_after_a_cancel_and_after_a_save(self):
        d = self.make(save=self.real_save)
        d.close()
        d.show()
        self.app_events()
        self.assertTrue(d.isVisible(), "U4-GUARD: the window can not be shown again")
        self.set_spin_text(d, "70")
        self.press_ok(d)
        self.assertEqual(self.D.load(self.path).defaults.a_rank_percent, 70, "U4-GUARD: OK did not save")
        self.assertFalse(d.isVisible())
        again = self.make(defaults=self.D.load(self.path).defaults)
        self.assertEqual(self.spin(again).value(), 70, "U4-GUARD: the re-opened window does not show the saved value")

    def test_a_the_window_can_be_moved(self):
        d = self.make()
        d.move(120, 140)
        self.app_events()
        self.assertEqual((d.x(), d.y()), (120, 140), "U4-GUARD: the window can not be moved")

    def test_a_other_widgets_and_the_application_are_not_affected(self):
        from PyQt6.QtWidgets import QApplication, QDialog, QCheckBox
        before = QApplication.palette().color(QApplication.palette().ColorRole.Window).name()
        d = self.make()
        other = QDialog()
        other.show()
        self.app_events()
        self.assertIs(type(other), QDialog)
        self.assertEqual(QApplication.palette().color(QApplication.palette().ColorRole.Window).name(), before, "U4-GUARD: the application palette changed")
        self.assertNotEqual(QCheckBox().style().__class__.__name__, "OpticalStyle", "U4-GUARD: a check box outside the window got the optical style")
        other.close()


# ================================================================================================================ U4-B
class CheckboxIndicator(X.DialogBase):
    PM = ("PM_IndicatorWidth", "PM_IndicatorHeight")

    def spy_style(self):
        """OpticalStyle over a base that answers 99 for EVERY pixel metric: what the OpticalStyle itself returns is then visible."""
        from PyQt6.QtWidgets import QProxyStyle, QStyleFactory

        class Spy(QProxyStyle):
            def pixelMetric(self, metric, option=None, widget=None):
                return 99

        spy = Spy(QStyleFactory.create("windowsvista"))
        self._keep = [spy]
        return self.U.OpticalStyle(spy)

    def test_b_the_optical_style_gives_the_logical_13_for_the_indicator_width_and_height(self):
        from PyQt6.QtWidgets import QStyle
        style = self.spy_style()
        for name in self.PM:
            got = style.pixelMetric(getattr(QStyle.PixelMetric, name))
            self.assertEqual(got, 13, "U4-RED: %s is %r (the native value is used); the contract: the logical 13" % (name, got))

    def test_b_every_other_pixel_metric_is_delegated_to_the_native_style(self):
        from PyQt6.QtWidgets import QStyle
        style = self.spy_style()
        for metric in (QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, QStyle.PixelMetric.PM_ButtonMargin, QStyle.PixelMetric.PM_DefaultFrameWidth, QStyle.PixelMetric.PM_SpinBoxFrameWidth,
                       QStyle.PixelMetric.PM_CheckBoxLabelSpacing, QStyle.PixelMetric.PM_LayoutLeftMargin, QStyle.PixelMetric.PM_FocusFrameHMargin):
            self.assertEqual(style.pixelMetric(metric), 99, "U4-GUARD: the metric %s is not delegated" % metric)

    def test_b_the_13_is_one_logical_number_without_a_scale_dependent_branch(self):
        _, methods = optical_style_methods()
        self.assertIn("pixelMetric", methods, "U4-RED: OpticalStyle has no pixelMetric")
        src = ast.get_source_segment(module_source(), methods["pixelMetric"])
        for bad in ("devicePixelRatio", "logicalDpi", "physicalDpi", "dpr", "scale", "125", "150", "175", "screen()", "QGuiApplication", "windll", "GetDpi"):
            self.assertNotIn(bad, src, "U4-RED: the pixelMetric code depends on the scale (%r)" % bad)
        self.assertEqual(getattr(self.U, "CHECKBOX_INDICATOR_LOGICAL", None), 13, "U4-RED: no module constant CHECKBOX_INDICATOR_LOGICAL = 13")

    def test_b_the_answer_does_not_depend_on_the_option_or_the_widget(self):
        from PyQt6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton
        style = self.spy_style()
        box = QCheckBox("x")
        opt = QStyleOptionButton()
        for name in self.PM:
            metric = getattr(QStyle.PixelMetric, name)
            answers = {style.pixelMetric(metric), style.pixelMetric(metric, opt), style.pixelMetric(metric, opt, box), style.pixelMetric(metric, None, None)}
            self.assertEqual(answers, {13}, "U4-RED: %s depends on the option / widget: %r" % (name, answers))

    def test_b_only_the_optical_style_is_extended_and_it_overrides_nothing_that_draws(self):
        cls, methods = optical_style_methods()
        self.assertEqual(set(methods), {"__init__", "drawControl", "pixelMetric"}, "U4-RED: the OpticalStyle methods are %r (expected __init__, drawControl for the label shift, pixelMetric)" % sorted(methods))
        self.assertNotIn("drawPrimitive", methods)
        self.assertNotIn("subElementRect", methods)
        draw_src = ast.get_source_segment(module_source(), methods["drawControl"]) if "drawControl" in methods else ""
        self.assertIn("CE_CheckBoxLabel", draw_src, "U4-GUARD: drawControl no longer shifts only the label")

    def test_b_no_custom_check_mark_image_or_unicode_box_is_drawn(self):
        text = module_source()
        for bad in ("☑", "☐", "☒", "QPixmap(", "drawPixmap", "drawImage(", "QIcon("):
            self.assertNotIn(bad, text, "U4-GUARD: %r in the module" % bad)

    def test_b_the_checkbox_optical_lift_is_half_a_logical_pixel(self):
        self.assertEqual(self.U.CHECKBOX_OPTICAL_LIFT, 0.5, "U4-GUARD: CHECKBOX_OPTICAL_LIFT")

    def test_b_the_other_optical_numbers_are_untouched(self):
        self.assertEqual(self.U.PRESET_OPTICAL_LIFT, 1.0)
        self.assertEqual(self.U.A_RANK_TEXT_LIFT_MARGIN, 1)

    # ---- the real widgets of the window (default scale 1.0): the indicator, the geometry, the interaction
    def boxes(self, d):
        from PyQt6.QtWidgets import QCheckBox
        return {b.objectName(): b for b in d.findChildren(QCheckBox)}

    def test_b_the_fifteen_check_boxes_use_the_optical_style_and_nothing_outside_does(self):
        d = self.make()
        boxes = self.boxes(d)
        self.assertEqual(len(boxes), 15, "U4-GUARD: the window has %d check boxes" % len(boxes))
        for name, b in boxes.items():
            self.assertEqual(type(b.style()).__name__, "OpticalStyle", "U4-GUARD: %s style" % name)
        from PyQt6.QtWidgets import QSpinBox, QPushButton
        self.assertNotEqual(type(self.spin(d).style()).__name__, "OpticalStyle", "U4-GUARD: the spin box got the check box style")
        self.assertNotEqual(type(self.find(d, "ok").style()).__name__, "OpticalStyle", "U4-GUARD: the OK button got the check box style")

    def test_b_the_indicator_rect_is_13_logical_and_inside_the_widget_and_the_click_area_follows(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QStyle, QStyleOptionButton
        d = self.make()
        for name, b in self.boxes(d).items():
            opt = QStyleOptionButton()
            opt.initFrom(b)
            opt.text = b.text()
            ind = b.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, b)
            self.assertEqual((ind.width(), ind.height()), (13, 13), "U4-RED: %s indicator rect %dx%d (logical, scale 1.0)" % (name, ind.width(), ind.height()))
            self.assertTrue(b.rect().contains(ind), "U4-GUARD: %s indicator outside the widget" % name)
            con = b.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, b)
            self.assertGreaterEqual(con.x(), ind.right(), "U4-GUARD: %s text overlaps the indicator" % name)
            self.assertEqual(b.hitButton(ind.center()), True, "U4-GUARD: %s indicator is not clickable" % name)
            self.assertTrue(b.hitButton(QPoint(con.x() + 2, con.center().y())), "U4-GUARD: %s start of the text is not clickable" % name)

    def test_b_rows_keep_their_pitch_and_do_not_overlap(self):
        d = self.make()
        boxes = self.boxes(d)
        env = [boxes["env_%d" % i] for i in range(8)]
        tops = [b.geometry().top() for b in env]
        pitch = {tops[i + 1] - tops[i] for i in range(7)}
        self.assertEqual(len(pitch), 1, "U4-GUARD: the environment rows have different pitches %r" % pitch)
        pen = [boxes[n] for n in ("pen_rolling", "pen_safety", "pen_speed", "pen_shock", "pen_eb", "pen_init")]
        pitch2 = {pen[i + 1].geometry().top() - pen[i].geometry().top() for i in range(5)}
        self.assertEqual(len(pitch2), 1, "U4-GUARD: the deduction rows have different pitches %r" % pitch2)
        for group in (env, pen):
            for a, b in zip(group, group[1:]):
                self.assertEqual(b.geometry().top() - a.geometry().top(), a.geometry().height(), "U4-GUARD: the rows are not packed without a gap (%s / %s)" % (a.objectName(), b.objectName()))
                self.assertLessEqual(a.geometry().bottom(), b.geometry().top() + 0, "U4-GUARD: two rows overlap (%s / %s)" % (a.objectName(), b.objectName()))

    def test_b_tab_and_shift_tab_order_is_kept(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        d = self.make()
        d.activateWindow()
        self.app_events()
        order = [("env_%d" % i) for i in range(8)] + ["timing", "pen_rolling", "pen_speed", "pen_shock", "pen_eb", "pen_init"]
        first = self.find(d, "env_0")
        first.setFocus(Qt.FocusReason.TabFocusReason)
        self.app_events()
        seen = [d.focusWidget().objectName()]
        for _ in range(len(order) - 1):
            QTest.keyClick(d.focusWidget(), Qt.Key.Key_Tab)
            self.app_events()
            seen.append(d.focusWidget().objectName())
        self.assertEqual(seen, order, "U4-GUARD: the Tab order changed (the safety intervention item is not a Tab stop)")
        QTest.keyClick(d.focusWidget(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        self.app_events()
        self.assertEqual(d.focusWidget().objectName(), "pen_eb", "U4-GUARD: Shift+Tab")

    def test_b_space_and_the_mouse_toggle_a_check_box_and_the_safety_item_stays_off_and_disabled(self):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtTest import QTest
        d = self.make()
        boxes = self.boxes(d)
        env3 = boxes["env_2"]
        env3.setFocus(Qt.FocusReason.TabFocusReason)
        before = env3.isChecked()
        QTest.keyClick(env3, Qt.Key.Key_Space)
        self.assertNotEqual(env3.isChecked(), before, "U4-GUARD: Space does not toggle")
        QTest.keyClick(env3, Qt.Key.Key_Space)
        self.assertEqual(env3.isChecked(), before)
        QTest.mouseClick(env3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(6, env3.height() // 2))
        self.assertNotEqual(env3.isChecked(), before, "U4-GUARD: a click on the indicator does not toggle")
        safe = boxes["pen_safety"]
        self.assertFalse(safe.isEnabled(), "U4-GUARD: the safety intervention item is enabled")
        self.assertFalse(safe.isChecked())
        QTest.mouseClick(safe, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(6, safe.height() // 2))
        QTest.keyClick(safe, Qt.Key.Key_Space)
        self.assertFalse(safe.isChecked(), "U4-GUARD: the safety intervention item was changed")

    def test_b_the_labels_are_not_clipped(self):
        from PyQt6.QtGui import QFontMetrics
        d = self.make()
        for name, b in self.boxes(d).items():
            self.assertGreaterEqual(b.width(), b.sizeHint().width(), "U4-GUARD: %s label is clipped (%d < %d)" % (name, b.width(), b.sizeHint().width()))


if __name__ == "__main__":
    unittest.main()
