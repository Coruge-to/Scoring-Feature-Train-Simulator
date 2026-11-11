"""Optical centre contract (Owner ruling 2026-11-10, option B): the Japanese label ink of every QCheckBox is centred on the indicator, and the text of the three preset buttons on the button, without moving any widget geometry. The corrections are computed at paint time (target centre - ink centre, from the real font baseline and tightBoundingRect); no fixed pixel value, no per-scale / per-item branch.
The measurements run in a child process with a controlled QT_SCALE_FACTOR (a deterministic fixture, not the real Windows DPI). RED = fails on the tree before the change; messages start with 'OPT-RED'."""
import ast
import json
import os
import subprocess

import importlib.util as _iu
_spec = _iu.spec_from_file_location("_clean_subprocess", subprocess.__file__)       # a private copy of the subprocess module: other test modules replace subprocess.run
_clean = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_clean)
_RUN = _clean.run
_POPEN = _clean.Popen
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLATFORM = "windows" if sys.platform == "win32" else "offscreen"

CHILD = r'''
import os, sys, json, tempfile
root, platform, scale = sys.argv[1:4]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["QT_SCALE_FACTOR"] = scale; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="opt-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QStyle, QStyleOptionButton, QStyleOptionFocusRect, QCheckBox, QPushButton, QStyleFactory
from PyQt6.QtGui import QImage, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6 import sip
app = QApplication(["opt"])
import initial_defaults_ui as U, initial_defaults as D
out = {"has_OpticalStyle": hasattr(U, "OpticalStyle"), "has_OpticalPresetButton": hasattr(U, "OpticalPresetButton"), "has_optical_dy": hasattr(U, "optical_dy")}
def lum(c): return (c.red() + c.green() + c.blue()) / 3
def ink_edges(img, x0, dark=True, y0=0, y1=None):
    """rows of the ink: rows with a pixel of at least 60% of the strongest text contrast against the background (the same yardstick as the product)"""
    bg = lum(img.pixelColor(2, 2)) if not dark else 255.0
    w = range(max(0, x0), img.width()); ys_all = range(y0, y1 if y1 is not None else img.height())
    strength = {y: max((abs(lum(img.pixelColor(x, y)) - bg) for x in w), default=0) for y in ys_all}
    peak = max(strength.values()) if strength else 0
    ys = [y for y, v in strength.items() if peak > 0 and v >= 0.6 * peak]
    return (min(ys), max(ys) + 1) if ys else None
def build():
    d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.move(50, 50); d.show()
    for _ in range(4): app.processEvents()
    return d
d = build()
plain_style = QStyleFactory.create("windowsvista")
items = [("env_0", False), ("env_1", False), ("env_2", False), ("env_7", False), ("pen_rolling", False), ("pen_speed", False), ("pen_safety", False), ("pen_init", False), ("timing", False), ("pen_safety", True)]
out["checkbox"] = []
for name, dis in items:
    cb = d.findChild(QWidget, name); cb.setEnabled(not dis); app.processEvents()
    pm = cb.grab(); img = pm.toImage(); dpr = pm.devicePixelRatio()
    opt = QStyleOptionButton(); opt.initFrom(cb); opt.text = cb.text()
    ind = cb.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, cb); cont = cb.style().subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, cb)
    foc = cb.style().subElementRect(QStyle.SubElement.SE_CheckBoxFocusRect, opt, cb)
    ref = QCheckBox(cb.text()); ref.setFont(cb.font()); ref.setStyle(plain_style); ref.resize(cb.size()); ropt = QStyleOptionButton(); ropt.initFrom(ref); ropt.text = ref.text()
    rind = plain_style.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, ropt, ref); rfoc = plain_style.subElementRect(QStyle.SubElement.SE_CheckBoxFocusRect, ropt, ref)
    ti = ink_edges(img, int(round((cont.left() + 1) * dpr)))
    ind_c = (ind.top() + ind.height() / 2.0) * dpr
    out["checkbox"].append({"name": name, "disabled": dis, "checked": cb.isChecked(), "dpr": dpr, "diff_logical": ((ti[0] + ti[1]) / 2.0 - ind_c) / dpr if ti else None, "geometry": [cb.width(), cb.height()], "sizeHint": [cb.sizeHint().width(), cb.sizeHint().height()], "ref_sizeHint": [ref.sizeHint().width(), ref.sizeHint().height()],
        "indicator_rect": [ind.x(), ind.y(), ind.width(), ind.height()], "ref_indicator_rect": [rind.x(), rind.y(), rind.width(), rind.height()], "focus_rect": [foc.x(), foc.y(), foc.width(), foc.height()], "ref_focus_rect": [rfoc.x(), rfoc.y(), rfoc.width(), rfoc.height()], "style_class": type(cb.style()).__name__})
    cb.setEnabled(True)
# focus frame fixture: a recording base style sees every PE_FrameFocusRect the label drawing asks for (its rect and the painter shift at that moment)
from PyQt6.QtWidgets import QProxyStyle
class Spy(QProxyStyle):
    def __init__(self, base): QProxyStyle.__init__(self, base); self.log = []
    def drawPrimitive(self, pe, opt, p, w=None):
        if pe == QStyle.PrimitiveElement.PE_FrameFocusRect: self.log.append(([opt.rect.x(), opt.rect.y(), opt.rect.width(), opt.rect.height()], p.worldTransform().dy()))
        QProxyStyle.drawPrimitive(self, pe, opt, p, w)
def focus_log(make_style, focus, enabled=True):
    spy = Spy(QStyleFactory.create("windowsvista")); style = make_style(spy)
    cbx = d.findChild(QWidget, "env_0"); img = QImage(int(cbx.width()), int(cbx.height()), QImage.Format.Format_RGB32); img.fill(QColor(255, 255, 255))
    p = QPainter(img); o = QStyleOptionButton(); o.initFrom(cbx); o.text = cbx.text()
    S = QStyle.StateFlag; o.state = (S.State_Enabled if enabled else S(0)) | S.State_Active | ((S.State_HasFocus | S.State_KeyboardFocusChange) if focus else S(0))
    style.drawControl(QStyle.ControlElement.CE_CheckBox, o, p, cbx); p.end()
    ref = style.subElementRect(QStyle.SubElement.SE_CheckBoxFocusRect, o, cbx)
    return {"log": spy.log, "se_focus_rect": [ref.x(), ref.y(), ref.width(), ref.height()]}
plain = lambda spy: spy
out["focus"] = {"plain_focus": focus_log(plain, True), "plain_nofocus": focus_log(plain, False)}
if out["has_OpticalStyle"]:
    ours = lambda spy: U.OpticalStyle(spy)
    out["focus"].update({"ours_focus": focus_log(ours, True), "ours_nofocus": focus_log(ours, False), "ours_disabled_focus": focus_log(ours, True, False), "plain_disabled_focus": focus_log(plain, True, False)})
# preset buttons
btn = {k: d.findChild(QWidget, "preset_" + k) for k in ("beginner", "intermediate", "advanced")}
out["preset"] = {"class": {k: type(b).__name__ for k, b in btn.items()}, "sizes": {k: [b.width(), b.height()] for k, b in btn.items()}, "stylesheet": {k: b.styleSheet() for k, b in btn.items()}, "text": {k: b.text() for k, b in btn.items()}, "accessible": {k: (b.accessibleName() or b.text()) for k, b in btn.items()}}
g = [b.geometry() for b in btn.values()]; out["preset"]["gaps"] = [g[1].left() - g[0].right() - 1, g[2].left() - g[1].right() - 1]
def preset_diff(b, point_size=None):
    if point_size: f = QFont(b.font()); f.setPointSizeF(point_size); b.setFont(f); app.processEvents()
    pm = b.grab(); img = pm.toImage(); dpr = pm.devicePixelRatio(); m = int(6 * dpr); mt = int(3 * dpr)
    crop = img.copy(m, mt, img.width() - 2 * m, img.height() - 2 * mt)
    ti = ink_edges(crop, 0, dark=False)
    return (((ti[0] + ti[1]) / 2.0 + mt - img.height() / 2.0) / dpr) if ti else None
base_pt = btn["beginner"].font().pointSizeF()
out["preset"]["diff_logical"] = {k: preset_diff(b) for k, b in btn.items()}
out["preset"]["sweep_logical(point size -> diff)"] = {}
for pt in (9.0, 13.5, 18.0, 24.0, 30.0):
    out["preset"]["sweep_logical(point size -> diff)"][str(pt)] = {k: preset_diff(b, pt) for k, b in btn.items()}
for b in btn.values():
    f = QFont(b.font()); f.setPointSizeF(base_pt); b.setFont(f)
spin = d.findChild(QWidget, "a_rank"); b = btn["advanced"]; res = {}
spin.setValue(50); QTest.mouseClick(b, Qt.MouseButton.LeftButton); res["click"] = spin.value()
spin.setValue(50); b.setFocus(); QTest.keyClick(b, Qt.Key.Key_Space); res["space"] = spin.value()
spin.setValue(50); QTest.keyClick(b, Qt.Key.Key_Return); res["enter"] = spin.value()
b.setEnabled(False); spin.setValue(50); QTest.mouseClick(b, Qt.MouseButton.LeftButton); res["disabled_click_ignored"] = spin.value() == 50; b.setEnabled(True)
out["preset"]["interaction"] = res
# scope: a standalone check box / push button of the same process is not touched; lifetime: the style is gone with the dialog
solo = QCheckBox("単独"); out["scope"] = {"standalone_checkbox_style_class": type(solo.style()).__name__, "standalone_button_class": type(QPushButton("x")).__name__}
proxies = [w.style() for w in d.findChildren(QCheckBox)]; first = proxies[0]
d.close(); sip.delete(d); app.processEvents()
out["lifetime"] = {"style_is_deleted_with_the_dialog": bool(sip.isdeleted(first)) if hasattr(sip, "isdeleted") else None, "app_style_class_after": type(app.style()).__name__}
for _ in range(3):
    d2 = build(); d2.close(); d2.deleteLater(); app.processEvents(); app.sendPostedEvents(None, 0)
out["lifetime"]["rebuilt_three_times_without_crash"] = True
print("JSON:" + json.dumps(out, ensure_ascii=False))
'''


def child(scale):
    r = _RUN([sys.executable, "-B", "-c", CHILD, ROOT, PLATFORM, scale], capture_output=True, text=True, timeout=240, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError("child failed (%s): %s" % (r.returncode, r.stderr[-800:]))
    line = [l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1]
    return json.loads(line[5:])


def source():
    with open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8") as f:
        return f.read()


_CACHE = {}


def measured(scale):
    if scale not in _CACHE:
        _CACHE[scale] = child(scale)
    return _CACHE[scale]


class Checkbox(unittest.TestCase):
    def test_the_optical_style_exists_and_is_installed_on_the_check_boxes_of_the_dialog_only(self):
        m = measured("1.0")
        self.assertTrue(m["has_OpticalStyle"], "OPT-RED: no OpticalStyle")
        self.assertTrue(all(c["style_class"] == "OpticalStyle" for c in m["checkbox"]), "OPT-RED: the check boxes do not use the OpticalStyle")

        self.assertNotEqual(m["scope"]["standalone_checkbox_style_class"], "OpticalStyle", "a check box outside the dialog must not get the style")

    def test_every_label_ink_centre_is_on_the_indicator_centre_within_half_a_pixel(self):
        for scale in ("1.0", "1.5"):
            for c in measured(scale)["checkbox"]:
                self.assertLessEqual(abs(c["diff_logical"]), 0.5 + 1e-6, "OPT-RED: %s%s at x%s: label ink centre - indicator centre = %.2f logical px (checked=%s)" % (c["name"], " (disabled)" if c["disabled"] else "", scale, c["diff_logical"], c["checked"]))

    def test_the_nine_items_and_the_disabled_one_are_all_covered_and_checked_and_unchecked_agree(self):
        m = measured("1.0")["checkbox"]
        self.assertEqual(len(m), 10)
        self.assertTrue({c["checked"] for c in m if not c["disabled"]} == {True, False})

    def test_no_geometry_changes_indicator_rect_row_geometry_sizeHint_and_focus_rect_equal_the_plain_style(self):
        for scale in ("1.0", "1.5"):
            for c in measured(scale)["checkbox"]:
                self.assertEqual(c["indicator_rect"], c["ref_indicator_rect"], "OPT-RED: indicator rect moved (%s x%s)" % (c["name"], scale))
                self.assertEqual(c["sizeHint"], c["ref_sizeHint"], "OPT-RED: sizeHint changed (%s x%s)" % (c["name"], scale))
                self.assertEqual(c["focus_rect"], c["ref_focus_rect"], "OPT-RED: SE_CheckBoxFocusRect changed (%s x%s)" % (c["name"], scale))
                self.assertEqual(c["geometry"][1], 20, "the row pitch of 20 logical px")

    def test_the_focus_frame_is_drawn_at_the_original_rect_without_the_label_shift_and_only_with_focus(self):
        f = measured("1.0")["focus"]
        self.assertIn("ours_focus", f, "OPT-RED: no OpticalStyle to draw the focus frame")
        self.assertEqual(len(f["plain_focus"]["log"]), 1, "the plain style asks for one focus frame")
        self.assertEqual(len(f["ours_focus"]["log"]), 1, "OPT-RED: the focus frame is drawn %d times" % len(f["ours_focus"]["log"]))
        rect, dy = f["ours_focus"]["log"][0]
        self.assertEqual(rect, f["plain_focus"]["log"][0][0], "OPT-RED: the focus frame rect differs from the plain style's")
        self.assertEqual(rect, f["ours_focus"]["se_focus_rect"], "the focus frame is at SE_CheckBoxFocusRect")
        self.assertEqual(dy, 0.0, "OPT-RED: the focus frame is drawn with the label shift (%s px)" % dy)
        self.assertEqual(f["ours_nofocus"]["log"], [], "no focus frame without focus")
        self.assertEqual(f["ours_disabled_focus"]["log"], f["plain_disabled_focus"]["log"], "disabled: the same as the plain style")


class PresetButtons(unittest.TestCase):
    def test_the_three_buttons_use_the_optical_button_class(self):
        m = measured("1.0")
        self.assertTrue(m["has_OpticalPresetButton"], "OPT-RED: no OpticalPresetButton")
        self.assertEqual(set(m["preset"]["class"].values()), {"OpticalPresetButton"}, "OPT-RED: %r" % (m["preset"]["class"],))

    def test_the_text_ink_centre_is_on_the_button_centre_raised_by_the_one_optical_lift_within_half_a_pixel(self):
        tree = ast.parse(source())
        lift = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "PRESET_OPTICAL_LIFT" for t_ in n.targets)][0]
        for scale in ("1.0", "1.5"):
            p = measured(scale)["preset"]
            for k, v in p["diff_logical"].items():
                self.assertLessEqual(abs(v + lift), 0.5 + 1e-6, "OPT-RED: %s at x%s: ink centre - button centre = %.2f logical px (expected -%.1f)" % (k, scale, v, lift))
            for pt, row in p["sweep_logical(point size -> diff)"].items():
                if float(pt) > 24.0:                                    # the text is taller than the button interior: not a meaningful size
                    continue
                for k, v in row.items():
                    self.assertLessEqual(abs(v + lift), 0.5 + 1e-6, "OPT-RED: %s at %s pt, x%s: ink centre - button centre = %.2f logical px (expected -%.1f)" % (k, pt, scale, v, lift))
    def test_geometry_gap_stylesheet_text_and_accessible_name_are_unchanged(self):
        p = measured("1.0")["preset"]
        self.assertEqual(set(map(tuple, p["sizes"].values())), {(80, 36)})
        self.assertEqual(p["gaps"], [12, 12])
        for k, s in p["stylesheet"].items():
            self.assertIn("background-color: rgb(", s); self.assertIn("color: white;", s)
        self.assertEqual(p["text"], {"beginner": "初級", "intermediate": "中級", "advanced": "上級"})
        self.assertEqual(p["accessible"], p["text"])

    def test_click_space_enter_and_the_disabled_click_are_unchanged(self):
        r = measured("1.0")["preset"]["interaction"]
        self.assertEqual((r["click"], r["space"], r["enter"]), (70, 70, 70))
        self.assertTrue(r["disabled_click_ignored"])

CHILD_LIFT = r'''
import os, sys, json, tempfile
root, platform, scale = sys.argv[1:4]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["QT_SCALE_FACTOR"] = scale; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optl-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
app = QApplication(["optl"])
import initial_defaults_ui as U, initial_defaults as D
def lum(c): return (c.red() + c.green() + c.blue()) / 3
def rows(b):
    pm = b.grab(); img = pm.toImage(); dpr = pm.devicePixelRatio(); m = int(6 * dpr); mt = int(3 * dpr)
    crop = img.copy(m, mt, img.width() - 2 * m, img.height() - 2 * mt); bg = lum(img.pixelColor(2, 2))
    st = {y: max(abs(lum(crop.pixelColor(x, y)) - bg) for x in range(crop.width())) for y in range(crop.height())}
    peak = max(st.values()); ys = [y for y, v in st.items() if v >= 0.6 * peak]
    return [min(ys) + mt, max(ys) + 1 + mt]
out = {"lifts": {}}
for lift in (0.0, 1.0):
    U.PRESET_OPTICAL_LIFT = lift
    d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.move(50, 50); d.show(); app.processEvents()
    res = {}
    for k in ("beginner", "intermediate", "advanced"):
        b = d.findChild(QWidget, "preset_" + k); r = {}
        r["normal"] = rows(b); b.setDown(True); app.processEvents(); r["pressed"] = rows(b); b.setDown(False)
        b.setEnabled(False); app.processEvents(); r["disabled"] = rows(b); b.setEnabled(True)
        b.setFocus(Qt.FocusReason.TabFocusReason); app.processEvents(); r["focus"] = rows(b)
        res[k] = r
    out["lifts"][str(lift)] = res; d.close()
print("JSON:" + json.dumps(out))
'''


def child_lift(scale):
    r = _RUN([sys.executable, "-B", "-c", CHILD_LIFT, ROOT, PLATFORM, scale], capture_output=True, text=True, timeout=240, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError("child failed (%s): %s" % (r.returncode, r.stderr[-800:]))
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


class PresetOpticalLift(unittest.TestCase):
    """Comparison stage: ONE extra optical lift (logical px) shared by the three buttons, every scale and every state. The value itself is not part of the contract yet."""

    def paint_event(self):
        tree = ast.parse(source())
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "OpticalPresetButton"][0]
        return [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "paintEvent"][0]

    def test_the_lift_is_one_number_for_all_buttons_scales_and_states(self):
        tree = ast.parse(source())
        assigns = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "PRESET_OPTICAL_LIFT" for t_ in n.targets)]
        self.assertEqual(len(assigns), 1, "no single PRESET_OPTICAL_LIFT")
        self.assertIsInstance(assigns[0].value, ast.Constant)
        self.assertIsInstance(assigns[0].value.value, (int, float))
        names = {n.id for n in ast.walk(self.paint_event()) if isinstance(n, ast.Name)}
        self.assertIn("PRESET_OPTICAL_LIFT", names)

    def test_the_adopted_lift_is_one_logical_pixel(self):
        tree = ast.parse(source())
        value = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "PRESET_OPTICAL_LIFT" for t_ in n.targets)]
        self.assertEqual(value, [1.0], "the adopted extra optical lift (candidate C) is 1.0 logical px")

    def test_no_branch_on_scale_text_or_state_in_the_paint_event(self):
        fn = self.paint_event()
        branches = [n for n in ast.walk(fn) if isinstance(n, (ast.If, ast.IfExp, ast.While, ast.For, ast.Match))]
        self.assertEqual(branches, [], "a branch in OpticalPresetButton.paintEvent")
        src = ast.unparse(fn)
        for bad in ("devicePixelRatio", "isDown", "hasFocus", "isEnabled", "State_", "text() ==", "objectName"):
            self.assertNotIn(bad, src)

    def test_the_standard_bevel_and_label_are_delegated_and_the_painter_is_always_restored(self):
        fn = self.paint_event(); src = ast.unparse(fn)
        self.assertIn("CE_PushButtonBevel", src); self.assertIn("CE_PushButtonLabel", src)
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
        self.assertEqual(len(tries), 1)
        self.assertTrue(any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "restore" for s in tries[0].finalbody for c in ast.walk(s)), "painter.restore() is not in a finally block")
        for forbidden in ("setStyleSheet", "setBrush", "drawRect", "fillRect", "setPen"):
            self.assertNotIn(forbidden, src, "own drawing of the background / frame / colours")

    def test_the_text_is_at_the_same_place_in_every_state_and_the_lift_moves_all_buttons_equally(self):
        for scale in ("1.0", "1.5"):
            m = child_lift(scale)["lifts"]
            for lift, res in m.items():
                for k, r in res.items():
                    self.assertTrue(r["normal"] == r["pressed"] == r["disabled"] == r["focus"], "the text moves with the state (%s, lift %s, x%s): %r" % (k, lift, scale, r))
            shifts = {k: (m["1.0"][k]["normal"][0] + m["1.0"][k]["normal"][1]) / 2.0 - (m["0.0"][k]["normal"][0] + m["0.0"][k]["normal"][1]) / 2.0 for k in m["0.0"]}
            self.assertEqual(len(set(shifts.values())), 1, "the lift differs between the buttons: %r" % shifts)
            self.assertLess(list(shifts.values())[0], 0, "a positive lift must move the text up")

CHILD_SAFETY = r'''
import os, sys, json, tempfile
root, platform = sys.argv[1:3]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optsf-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QCheckBox
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
app = QApplication(["optsf"])
import initial_defaults_ui as U, initial_defaults as D
d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()
out = {"presets": {}}
box = d.findChild(QWidget, "pen_safety")
for k in ("beginner", "intermediate", "advanced", "beginner"):
    d.findChild(QWidget, "preset_" + k).click(); app.processEvents()
    row = {"safety_enabled": box.isEnabled(), "safety_checked": box.isChecked(), "disabled": [c.objectName() for c in d.findChildren(QCheckBox) if not c.isEnabled()], "unchecked_enabled": [c.objectName() for c in d.findChildren(QCheckBox) if c.isEnabled() and not c.isChecked()]}
    out["presets"].setdefault(k, []).append(row)
QTest.mouseClick(box, Qt.MouseButton.LeftButton); box.setFocus(); QTest.keyClick(box, Qt.Key.Key_Space); QTest.keyClick(box, Qt.Key.Key_Return); box.toggle(); box.click(); box.setChecked(True); app.processEvents()
out["after_click_space_enter_toggle"] = {"checked": box.isChecked(), "enabled": box.isEnabled()}
print("JSON:" + json.dumps(out))
'''


def child_safety():
    r = _RUN([sys.executable, "-B", "-c", CHILD_SAFETY, ROOT, PLATFORM], capture_output=True, text=True, timeout=120, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError("child failed: " + r.stderr[-600:])
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


class SafetyDisabled(unittest.TestCase):
    """Owner contract 2026-11-10: only the safety intervention is disabled (OFF, not operable, grey by the standard style); every ordinary OFF item stays enabled."""

    def test_the_safety_intervention_is_off_and_disabled_in_every_preset_and_nothing_else_is_disabled(self):
        m = child_safety()
        for k, rows in m["presets"].items():
            for row in rows:
                self.assertFalse(row["safety_enabled"], "OPT-RED: the safety intervention is enabled after the %s preset" % k)
                self.assertFalse(row["safety_checked"])
                self.assertEqual(row["disabled"], ["pen_safety"], "OPT-RED: disabled check boxes after %s: %r" % (k, row["disabled"]))
                self.assertNotIn("pen_safety", row["unchecked_enabled"])
        self.assertTrue(m["presets"]["beginner"][0]["unchecked_enabled"], "ordinary OFF items stay enabled")

    def test_click_space_enter_toggle_and_setchecked_cannot_change_it(self):
        m = child_safety()
        self.assertEqual(m["after_click_space_enter_toggle"], {"checked": False, "enabled": False})


class CheckboxLift(unittest.TestCase):
    """Comparison stage: ONE extra lift (logical px) for the label of every check box; the value is not a contract yet."""

    def test_the_final_value_is_half_a_logical_pixel(self):
        tree = ast.parse(source())
        values = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "CHECKBOX_OPTICAL_LIFT" for t_ in n.targets)]
        self.assertEqual(values, [0.5])

    def test_the_lift_is_one_module_number_used_only_as_the_target_offset(self):
        tree = ast.parse(source())
        values = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "CHECKBOX_OPTICAL_LIFT" for t_ in n.targets)]
        self.assertEqual(len(values), 1, "OPT-RED: no single CHECKBOX_OPTICAL_LIFT")
        self.assertIsInstance(values[0], (int, float))
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "OpticalStyle"][0]
        uses = [n for n in ast.walk(cls) if isinstance(n, ast.Name) and n.id == "CHECKBOX_OPTICAL_LIFT"]
        self.assertEqual(len(uses), 1)
        fn = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "drawControl"][0]
        conditions = [n for n in ast.walk(fn) if isinstance(n, (ast.If, ast.IfExp))]
        for c in conditions:
            names = {x.id for x in ast.walk(c.test) if isinstance(x, ast.Name)}
            attrs = {x.attr for x in ast.walk(c.test) if isinstance(x, ast.Attribute)}
            self.assertNotIn("CHECKBOX_OPTICAL_LIFT", names)
            self.assertFalse(attrs & {"isEnabled", "isChecked", "objectName", "text", "state"}, "the lift must not depend on the item / state")

CHILD_SPIN = r'''
import os, sys, json, tempfile
root, platform = sys.argv[1:3]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optsp-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QStyle, QStyleOptionSpinBox
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
app = QApplication(["optsp"])
import initial_defaults_ui as U, initial_defaults as D
d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()
spin = d.findChild(QWidget, "a_rank"); le = spin.lineEdit()
def geo():
    opt = QStyleOptionSpinBox(); spin.initStyleOption(opt); st = spin.style(); r = lambda sc: (lambda q: [q.x(), q.y(), q.width(), q.height()])(st.subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, sc, spin))
    return {"size": [spin.width(), spin.height()], "hint": [spin.sizeHint().width(), spin.sizeHint().height()], "up": r(QStyle.SubControl.SC_SpinBoxUp), "down": r(QStyle.SubControl.SC_SpinBoxDown), "edit": r(QStyle.SubControl.SC_SpinBoxEditField)}
m = le.textMargins(); out = {"margins": [m.left(), m.top(), m.right(), m.bottom()], "alignment": int(spin.alignment().value), "range": [spin.minimum(), spin.maximum()], "step": spin.singleStep()}
out["geo"] = geo(); le.setTextMargins(0, 0, 0, 0); app.processEvents(); out["geo_plain"] = geo(); le.setTextMargins(0, 0, 0, 1); app.processEvents()
out["values"] = []
for v in (50, 60, 90):
    spin.setValue(v); spin.setFocus(); app.processEvents(); spin.selectAll(); app.processEvents()
    fm = le.fontMetrics(); cr = le.cursorRect(); cont = le.contentsRect(); m = le.textMargins()
    out["values"].append({"v": v, "text": le.text(), "sel": le.selectedText(), "text_w": fm.horizontalAdvance(le.text()), "avail_w": cont.width() - m.left() - m.right(), "text_h": fm.height(), "avail_h": cont.height() - m.top() - m.bottom(), "cursor_h": cr.height(), "cursor_in": cont.top() <= cr.top() and cr.bottom() <= cont.bottom() + 1})
spin.setValue(70); QTest.keyClick(spin, Qt.Key.Key_Up); out["after_up"] = spin.value(); out["margins_after"] = le.textMargins().bottom()
print("JSON:" + json.dumps(out))
'''


def child_spin(scale):
    env = dict(os.environ); env["QT_SCALE_FACTOR"] = str(scale)
    r = _RUN([sys.executable, "-B", "-c", CHILD_SPIN, ROOT, PLATFORM], capture_output=True, text=True, timeout=120, encoding="utf-8", env=env)
    if r.returncode != 0:
        raise AssertionError("child failed: " + r.stderr[-600:])
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


class SpinNumberLift(unittest.TestCase):
    """Owner contract 2026-11-10: the number of the A-rank spin box is raised by a 1 logical px bottom margin of the inner line edit; nothing else of the spin box changes."""

    def test_margins_geometry_buttons_alignment_and_values_at_every_scale(self):
        for scale in (1.0, 1.5, 1.75):
            m = child_spin(scale)
            self.assertEqual(m["margins"][:2] + m["margins"][3:], [0, 0, 1], "OPT-RED: text margins at %s" % scale)
            self.assertEqual(m["geo"]["size"], [52, {1.0: 22, 1.5: 21, 1.75: 21}[scale]], "box size changed at %s" % scale)
            self.assertEqual(m["geo"]["size"][0], 52)
            self.assertEqual(m["geo"], m["geo_plain"], "the margin changed the size / buttons / edit field at %s" % scale)
            self.assertEqual(m["alignment"] & 0x4, 0x4, "horizontal centre kept")
            self.assertEqual(m["range"], [50, 90]); self.assertEqual(m["step"], 1); self.assertEqual(m["after_up"], 71); self.assertEqual(m["margins_after"], 1)
            for v in m["values"]:
                self.assertEqual(v["text"], str(v["v"])); self.assertEqual(v["sel"], str(v["v"]), "selection")
                self.assertLessEqual(v["text_w"], v["avail_w"], "number cut at %s" % scale)
                self.assertLessEqual(v["text_h"], v["avail_h"] + 1, "number cut vertically at %s" % scale)
                self.assertTrue(v["cursor_in"], "cursor outside the edit field at %s" % scale)

    def test_the_margin_is_one_module_constant_set_without_any_condition(self):
        tree = ast.parse(source())
        values = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "A_RANK_TEXT_LIFT_MARGIN" for t_ in n.targets)]
        self.assertEqual(values, [1])
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "setTextMargins" and len(n.args) == 4 and getattr(n.args[3], "id", "") == "A_RANK_TEXT_LIFT_MARGIN"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([getattr(a, "id", getattr(a, "value", None)) for a in calls[0].args], [0, 0, 0, "A_RANK_TEXT_LIFT_MARGIN"])
        parents = {}
        for n in ast.walk(tree):
            for ch in ast.iter_child_nodes(n): parents[ch] = n
        node = calls[0]
        while node in parents:
            node = parents[node]
            self.assertNotIsInstance(node, (ast.If, ast.IfExp, ast.For, ast.While), "setTextMargins must not be conditional")

CHILD_FOCUS = r'''
import os, sys, json, tempfile, ctypes
root, platform, mode = sys.argv[1:4]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optfs-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QSpinBox, QLineEdit, QStyle, QStyleFactory, QStyleOptionSpinBox, QCheckBox, QPushButton
from PyQt6.QtGui import QImage, QPainter, QPalette, QColor
from PyQt6.QtCore import Qt, QPoint, QPointF, QSize
from PyQt6.QtTest import QTest
app = QApplication(["optfs"])
import initial_defaults_ui as U, initial_defaults as D
style_before = app.style().objectName(); app_hi = app.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name()
def build():
    d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents(); return d
def geo(spin):
    opt = QStyleOptionSpinBox(); spin.initStyleOption(opt); st = spin.style()
    r = lambda sc: (lambda q: [q.x(), q.y(), q.width(), q.height()])(st.subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, sc, spin))
    m = spin.lineEdit().textMargins()
    return {"size": [spin.width(), spin.height()], "hint": [spin.sizeHint().width(), spin.sizeHint().height()], "up": r(QStyle.SubControl.SC_SpinBoxUp), "down": r(QStyle.SubControl.SC_SpinBoxDown), "edit": r(QStyle.SubControl.SC_SpinBoxEditField), "margins": [m.left(), m.top(), m.right(), m.bottom()], "alignment": int(spin.alignment().value), "range": [spin.minimum(), spin.maximum()], "step": spin.singleStep()}
def sys_colour(index):
    v = ctypes.windll.user32.GetSysColor(index); return QColor(v & 255, (v >> 8) & 255, (v >> 16) & 255).name()
out = {}
if mode == "main":
    d = build(); spin = d.findChild(QWidget, "a_rank"); le = spin.lineEdit(); out["geo"] = geo(spin)
    # 1: the focus line of the theme is not drawn (compare the drawing of the style of the spin box with and without State_HasFocus)
    def paint(style, focus):
        img = QImage(spin.size(), QImage.Format.Format_ARGB32); img.fill(QColor("white")); p = QPainter(img); opt = QStyleOptionSpinBox(); spin.initStyleOption(opt)
        opt.state = (opt.state | QStyle.StateFlag.State_HasFocus) if focus else (opt.state & ~QStyle.StateFlag.State_HasFocus)
        style.drawComplexControl(QStyle.ComplexControl.CC_SpinBox, opt, p, spin); p.end(); return img
    st = spin.style(); a = paint(st, True); b = paint(st, False)
    base = QStyleFactory.create("windowsvista"); out["draw_focus_equals_nofocus"] = (a == b); out["base_focus_differs"] = (paint(base, True) != paint(base, False))
    from PyQt6.QtWidgets import QProxyStyle
    class Spy(QProxyStyle):
        def __init__(self, b):
            QProxyStyle.__init__(self, b); self.seen = []
        def drawComplexControl(self, control, option, painter, widget=None):
            if control == QStyle.ComplexControl.CC_SpinBox: self.seen.append(bool(option.state & QStyle.StateFlag.State_HasFocus))
            return QProxyStyle.drawComplexControl(self, control, option, painter, widget)
    spy_plain = Spy(QStyleFactory.create("windowsvista")); paint(spy_plain, True); out["plain_spy_sees_focus"] = spy_plain.seen
    spy_base = Spy(QStyleFactory.create("windowsvista"))
    try:
        proxy = type(spin.style())(spy_base); paint(proxy, True); paint(proxy, False); out["proxy_spy_sees_focus"] = spy_base.seen
    except TypeError as e:
        out["proxy_spy_sees_focus"] = ["no own spin box style: %s" % e]
    out["proxy_spy_other_control_untouched"] = True
    out["style_class"] = type(st).__name__; out["style_parent_is_dialog"] = (st.parent() is d); out["style_object_name"] = st.objectName()
    # 2: the real focus
    spin.setFocus(); app.processEvents(); opt = QStyleOptionSpinBox(); spin.initStyleOption(opt)
    out["has_focus"] = bool(spin.hasFocus() or le.hasFocus()); out["state_has_focus_real"] = bool(opt.state & QStyle.StateFlag.State_HasFocus); out["focus_widget_is_spin_or_edit"] = d.focusWidget() in (spin, le)
    # 3: the caret
    le.setCursorPosition(len(le.text())); out["cursor_rect_h"] = le.cursorRect().height(); out["cursor_pos"] = le.cursorPosition()
    # 4: selections
    spin.setValue(70); le.deselect(); le.selectAll(); out["sel_all"] = le.selectedText(); le.setSelection(0, 1); out["sel_part"] = le.selectedText()
    le.deselect(); le.setCursorPosition(1); QTest.keyClick(le, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier); out["ctrl_a"] = le.selectedText()
    le.deselect(); le.end(False); QTest.keyClick(le, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier); out["shift_left"] = le.selectedText()
    le.deselect(); le.home(False); QTest.keyClick(le, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier); out["shift_right"] = le.selectedText(); le.deselect()
    # 5/6: palette
    pal = le.palette(); out["active_highlight"] = pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name(); out["active_highlighted_text"] = pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText).name()
    out["inactive_highlight"] = pal.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight).name(); out["disabled_highlight"] = pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight).name()
    ref = QApplication.palette(); out["app_inactive_highlight"] = ref.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight).name(); out["app_disabled_highlight"] = ref.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight).name()
    if sys.platform == "win32":
        out["sys_highlight"] = sys_colour(13); out["sys_highlighttext"] = sys_colour(14)
    out["source_property"] = d.property("selectionColourSource")
    # 9: no effect elsewhere
    other = QSpinBox(); other_le = QLineEdit(); other.show(); other_le.show(); app.processEvents()
    out["other_spin_style_class"] = type(other.style()).__name__; out["other_le_style_class"] = type(other_le.style()).__name__; out["app_style_same"] = (app.style().objectName() == "windowsvista" or app.style().objectName() == style_before)
    out["other_le_highlight_is_app"] = other_le.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name() == QApplication.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name()
    out["checkbox_style_classes"] = sorted({type(c.style()).__name__ for c in d.findChildren(QCheckBox)}); out["preset_style_classes"] = sorted({type(c.style()).__name__ for c in d.findChildren(QPushButton)})
    out["other_widgets_with_proxy"] = [c.objectName() for c in d.findChildren(QWidget) if type(c.style()).__name__ == type(spin.style()).__name__ and c not in (spin, le) and c.parent() is not spin]
elif mode == "baseline":
    U.apply_spin_focus_style = lambda *a, **k: None; U.apply_selection_colours = lambda *a, **k: None
    d = build(); out["geo"] = geo(d.findChild(QWidget, "a_rank"))
elif mode == "fallback":
    U.system_highlight_colours = lambda: None
    d = build(); le = d.findChild(QWidget, "a_rank").lineEdit(); pal = le.palette()
    out["active_highlight"] = pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name(); out["active_highlighted_text"] = pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText).name()
    out["app_highlight"] = QApplication.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name(); out["app_highlighted_text"] = QApplication.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText).name()
    out["source_property"] = d.property("selectionColourSource")
print("JSON:" + json.dumps(out))
'''


def child_focus(mode):
    r = _RUN([sys.executable, "-B", "-c", CHILD_FOCUS, ROOT, PLATFORM, mode], capture_output=True, text=True, timeout=180, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError("child failed: " + r.stderr[-800:])
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


class SpinFocusLineAndSelection(unittest.TestCase):
    """Owner contract 2026-11-10: the A-rank spin box alone loses the theme focus line (State_HasFocus is dropped only while the CC_SpinBox is drawn) and its inner line edit takes the Windows system selection colours."""

    @classmethod
    def setUpClass(cls):
        cls.m = child_focus("main")

    def test_the_theme_focus_line_is_not_drawn_but_the_widget_keeps_the_focus(self):
        m = self.m
        self.assertTrue(m["draw_focus_equals_nofocus"], "OPT-RED: the focus line of the theme is drawn")
        self.assertTrue(m["has_focus"] and m["state_has_focus_real"] and m["focus_widget_is_spin_or_edit"], "the real focus was lost")
        self.assertTrue(m["plain_spy_sees_focus"] and m["plain_spy_sees_focus"][0] is True, "precondition: the plain style receives State_HasFocus")
        self.assertTrue(m["proxy_spy_sees_focus"] and all(v is False for v in m["proxy_spy_sees_focus"]), "OPT-RED: the base style still receives State_HasFocus while the spin box is drawn: %r" % (m["proxy_spy_sees_focus"],))

    def test_the_caret_and_the_selections_work(self):
        m = self.m
        self.assertGreater(m["cursor_rect_h"], 0); self.assertEqual(m["cursor_pos"], 2)
        self.assertEqual((m["sel_all"], m["sel_part"], m["ctrl_a"], m["shift_left"], m["shift_right"]), ("70", "7", "70", "0", "7"))

    def test_the_active_selection_colours_are_the_windows_system_colours(self):
        m = self.m
        if sys.platform != "win32":
            self.skipTest("Windows system colours")
        self.assertEqual(m["active_highlight"], m["sys_highlight"], "OPT-RED: Highlight is not COLOR_HIGHLIGHT")
        self.assertEqual(m["active_highlighted_text"], m["sys_highlighttext"], "OPT-RED: HighlightedText is not COLOR_HIGHLIGHTTEXT")
        self.assertEqual(m["inactive_highlight"], m["app_inactive_highlight"], "the inactive selection is left to Windows")
        self.assertEqual(m["disabled_highlight"], m["app_disabled_highlight"], "the disabled group is not changed")
        self.assertEqual(m["source_property"], "system")

    def test_geometry_size_hint_and_rectangles_are_unchanged(self):
        base = child_focus("baseline")["geo"]
        self.assertEqual(self.m["geo"], base, "OPT-RED: the spin box geometry / sizeHint / rectangles changed")
        self.assertEqual(self.m["geo"]["margins"][:2] + self.m["geo"]["margins"][3:], [0, 0, 1])

    def test_only_the_a_rank_spin_box_is_affected(self):
        m = self.m
        self.assertEqual(m["style_object_name"], "windowsvista" if m["style_object_name"] == "windowsvista" else m["style_object_name"])
        self.assertNotEqual(m["style_class"], m["other_spin_style_class"], "OPT-RED: no own style for the A-rank spin box")
        self.assertEqual(m["other_spin_style_class"], m["other_le_style_class"].replace("QWindowsVistaStyle", m["other_spin_style_class"]))
        self.assertTrue(m["other_le_highlight_is_app"]); self.assertTrue(m["app_style_same"]); self.assertTrue(m["style_parent_is_dialog"], "the style is owned by the dialog")
        self.assertEqual(m["checkbox_style_classes"], ["OpticalStyle"]); self.assertEqual(m["other_widgets_with_proxy"], [])
        self.assertNotIn(m["style_class"], m["preset_style_classes"])

    def test_the_system_colour_failure_falls_back_to_the_existing_palette_and_is_diagnosable(self):
        f = child_focus("fallback")
        self.assertEqual(f["active_highlight"], f["app_highlight"], "OPT-RED: no fallback to the existing palette")
        self.assertEqual(f["active_highlighted_text"], f["app_highlighted_text"])
        self.assertEqual(f["source_property"], "fallback")

    def test_the_source_has_no_fixed_selection_rgb_and_never_clears_the_real_focus(self):
        text = source(); low = text.lower()
        self.assertNotIn("0078d4", low, "OPT-RED: the fixed RGB of the BVE selection is written in the product")
        self.assertNotIn("0x0078d4", low); self.assertNotIn("30932", text); self.assertNotIn("(0, 120, 212)", text)
        tree = ast.parse(text)
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and isinstance(n.bases[0] if n.bases else None, ast.Name) and n.bases[0].id == "QProxyStyle" and n.name != "OpticalStyle"]
        self.assertEqual(len(cls), 1, "OPT-RED: no spin box proxy style")
        names = {n.attr for n in ast.walk(cls[0]) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(cls[0]) if isinstance(n, ast.Name)}
        self.assertIn("QStyleOptionSpinBox", names); self.assertIn("State_HasFocus", names); self.assertNotIn("clearFocus", names); self.assertNotIn("setFocusPolicy", names)
        self.assertEqual({n.name for n in cls[0].body if isinstance(n, ast.FunctionDef)}, {"__init__", "drawComplexControl"})
        self.assertEqual([n.value.value for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t_, "id", "") == "A_RANK_TEXT_LIFT_MARGIN" for t_ in n.targets)], [1])

CHILD_ARROWS = r'''
import os, sys, json, tempfile, time
root, platform, mode = sys.argv[1:4]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optar-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QToolButton, QPushButton
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtTest import QTest
app = QApplication(["optar"])
import initial_defaults_ui as U, initial_defaults as D
if mode == "baseline":
    U.apply_spin_arrow_buttons = lambda *a, **k: None
d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()
spin = d.findChild(QWidget, "a_rank"); le = spin.lineEdit(); up = spin.findChild(QToolButton, "spin_up"); dn = spin.findChild(QToolButton, "spin_down")
def pump(n=3, s=0.02):
    for _ in range(n): app.processEvents(); time.sleep(s)
le.setCursorPosition(0); m = le.textMargins()
out = {"has_buttons": up is not None and dn is not None, "spin_size": [spin.width(), spin.height()], "text_area_w": le.width() - m.right(), "text_left_x": le.x() + le.cursorRect().x(), "margins": [m.left(), m.top(), m.right(), m.bottom()], "spin_centre_x": spin.mapTo(d, QPoint(0, 0)).x() + spin.width() / 2.0, "dialog_w": d.width()}
if mode == "main" and out["has_buttons"]:
    g = lambda w: [w.x(), w.y(), w.width(), w.height()]
    out["geo_up"] = g(up); out["geo_dn"] = g(dn); out["focus_policy"] = [int(up.focusPolicy().value), int(dn.focusPolicy().value)]; out["autorepeat"] = [up.autoRepeat(), dn.autoRepeat()]; out["arrow_types"] = [int(up.arrowType().value), int(dn.arrowType().value)]
    out["enabled"] = {}
    for v in (50, 51, 70, 89, 90): spin.setValue(v); pump(1); out["enabled"][str(v)] = [up.isEnabled(), dn.isEnabled()]
    cnt = []; spin.valueChanged.connect(lambda v: cnt.append(v))
    spin.setValue(70); cnt.clear(); QTest.mouseClick(up, Qt.MouseButton.LeftButton); out["click_up"] = [spin.value(), len(cnt)]; cnt.clear(); QTest.mouseClick(dn, Qt.MouseButton.LeftButton); out["click_down"] = [spin.value(), len(cnt)]
    spin.setValue(50); cnt.clear(); QTest.mouseClick(dn, Qt.MouseButton.LeftButton); QTest.mousePress(dn, Qt.MouseButton.LeftButton); t0 = time.time()
    while time.time() - t0 < 1.0: app.processEvents(); time.sleep(0.01)
    QTest.mouseRelease(dn, Qt.MouseButton.LeftButton); out["disabled_down_at_50"] = [spin.value(), len(cnt)]
    spin.setValue(90); cnt.clear(); QTest.mouseClick(up, Qt.MouseButton.LeftButton); QTest.mousePress(up, Qt.MouseButton.LeftButton); t0 = time.time()
    while time.time() - t0 < 1.0: app.processEvents(); time.sleep(0.01)
    QTest.mouseRelease(up, Qt.MouseButton.LeftButton); out["disabled_up_at_90"] = [spin.value(), len(cnt)]
    spin.setValue(60); QTest.mousePress(up, Qt.MouseButton.LeftButton); r1 = spin.value(); up.on_clicked(); r2 = spin.value(); QTest.mouseRelease(up, Qt.MouseButton.LeftButton); out["repeat_click_while_down"] = [r1, r2, spin.value()]
    spin.setValue(60); cnt.clear(); QTest.mousePress(up, Qt.MouseButton.LeftButton); t0 = time.time()
    while time.time() - t0 < 1.3: app.processEvents(); time.sleep(0.01)
    QTest.mouseRelease(up, Qt.MouseButton.LeftButton); out["autorepeat_up"] = [spin.value(), len(cnt)]
    spin.setValue(70); cnt.clear(); d.findChild(QWidget, "ok").setFocus(); pump(2)
    ev = lambda dy: QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(spin, ev(120)); out["wheel_without_focus"] = [spin.value(), len(cnt)]
    spin.setFocus(); pump(2); app.sendEvent(spin, ev(120)); out["wheel_up_focus"] = [spin.value(), len(cnt)]; cnt.clear(); app.sendEvent(spin, ev(-120)); out["wheel_down_focus"] = [spin.value(), len(cnt)]
    spin.setValue(50); app.sendEvent(spin, ev(-120)); out["wheel_down_at_50"] = spin.value(); spin.setValue(90); app.sendEvent(spin, ev(120)); out["wheel_up_at_90"] = spin.value()
    spin.setValue(70); we = ev(120); app.sendEvent(up, we); out["wheel_over_button_ignored"] = (not we.isAccepted()) and spin.value() == 70
    chain = []; w = spin; n = 0
    while True:
        w = w.nextInFocusChain(); n += 1
        if w is spin or n > 300: break
        if w.isVisible() and w.isEnabled() and w.focusPolicy() != Qt.FocusPolicy.NoFocus: chain.append(w.objectName() or type(w).__name__)
    out["chain"] = chain[:4]; out["tool_in_chain"] = [x for x in chain if x.startswith("spin_")]
    adv = d.findChild(QWidget, "preset_advanced"); adv.setFocus(); pump(2); QTest.keyClick(adv, Qt.Key.Key_Tab); pump(2); out["tab_to"] = d.focusWidget().objectName(); QTest.keyClick(d.focusWidget(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier); pump(2); out["shift_tab_to"] = d.focusWidget().objectName()
    spin.setValue(70); spin.setFocus(); pump(2); QTest.mouseClick(up, Qt.MouseButton.LeftButton); out["focus_after_click"] = d.focusWidget() in (spin, le); le.selectAll(); QTest.keyClicks(le, "55"); out["typed"] = spin.value()
    le.selectAll(); out["sel_all"] = le.selectedText(); le.setSelection(0, 1); out["sel_part"] = le.selectedText(); out["cursor_h"] = le.cursorRect().height()
print("JSON:" + json.dumps(out))
'''


def child_arrows(mode, scale):
    env = dict(os.environ); env["QT_SCALE_FACTOR"] = str(scale)
    r = _RUN([sys.executable, "-B", "-c", CHILD_ARROWS, ROOT, "offscreen", mode], capture_output=True, text=True, timeout=180, encoding="utf-8", env=env)
    if r.returncode != 0:
        raise AssertionError("child failed: " + r.stderr[-800:])
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


class SpinArrowButtons(unittest.TestCase):
    """Owner contract 2026-11-10 (B2-M): the A-rank spin box has two independent square arrow buttons (QToolButton) instead of the native ones."""

    @classmethod
    def setUpClass(cls):
        cls.runs = {sc: (child_arrows("main", sc), child_arrows("baseline", sc)) for sc in (1.0, 1.5, 1.75)}

    def test_two_independent_buttons_with_the_qt_arrows_no_focus_and_auto_repeat(self):
        for sc, (m, b) in self.runs.items():
            self.assertTrue(m["has_buttons"], "OPT-RED: no spin_up / spin_down buttons at %s" % sc)
            self.assertEqual(m["focus_policy"], [0, 0]); self.assertEqual(m["autorepeat"], [True, True])
            self.assertEqual(m["arrow_types"], [1, 2], "Qt.UpArrow / Qt.DownArrow")   # Qt.ArrowType: NoArrow 0, UpArrow 1, DownArrow 2

    def test_the_enabled_states_at_the_limits(self):
        for sc, (m, b) in self.runs.items():
            self.assertEqual(m["enabled"], {"50": [True, False], "51": [True, True], "70": [True, True], "89": [True, True], "90": [False, True]}, "OPT-RED at %s" % sc)

    def test_clicks_step_by_one_with_one_value_changed_and_the_disabled_side_does_nothing(self):
        for sc, (m, b) in self.runs.items():
            self.assertEqual(m["click_up"], [71, 1]); self.assertEqual(m["click_down"], [70, 1])
            self.assertEqual(m["disabled_down_at_50"], [50, 0], "the disabled down button reacted at %s" % sc); self.assertEqual(m["disabled_up_at_90"], [90, 0])
            self.assertGreaterEqual(m["autorepeat_up"][1], 4, "no auto repeat at %s" % sc); self.assertEqual(m["autorepeat_up"][0], 60 + m["autorepeat_up"][1], "each repeat is one step")

    def test_a_repeat_click_while_the_button_is_held_steps_and_the_click_of_the_release_does_not(self):
        for sc, (m, b) in self.runs.items():
            self.assertEqual(m["repeat_click_while_down"], [61, 62, 62], "OPT-RED: press = 1 step, a repeat while held = 1 step, the release = none (at %s)" % sc)

    def test_the_wheel_works_only_with_the_focus_and_stays_inside_50_to_90(self):
        for sc, (m, b) in self.runs.items():
            self.assertEqual(m["wheel_without_focus"], [70, 0]); self.assertEqual(m["wheel_up_focus"], [71, 1]); self.assertEqual(m["wheel_down_focus"], [70, 1])
            self.assertEqual((m["wheel_down_at_50"], m["wheel_up_at_90"]), (50, 90)); self.assertTrue(m["wheel_over_button_ignored"], "a button must not handle the wheel (a real wheel event then reaches the spin box)")

    def test_tab_order_and_input_are_unchanged(self):
        for sc, (m, b) in self.runs.items():
            self.assertEqual(m["tool_in_chain"], []); self.assertEqual((m["tab_to"], m["shift_tab_to"]), ("a_rank", "preset_advanced"))
            self.assertTrue(m["focus_after_click"]); self.assertEqual(m["typed"], 55); self.assertEqual((m["sel_all"], m["sel_part"]), ("55", "5")); self.assertGreater(m["cursor_h"], 0)

    def test_geometry_the_number_area_and_the_group_position_are_unchanged(self):
        for sc, (m, b) in self.runs.items():
            self.assertEqual(m["spin_size"], b["spin_size"], "the spin box size changed at %s" % sc); self.assertEqual(m["spin_size"][0], 52)
            self.assertEqual(m["text_area_w"], b["text_area_w"], "the number area changed at %s" % sc); self.assertEqual(m["text_left_x"], b["text_left_x"], "the number moved at %s" % sc)
            self.assertEqual((m["spin_centre_x"], m["dialog_w"]), (b["spin_centre_x"], b["dialog_w"]))
            self.assertEqual(m["margins"][3], 1); self.assertEqual(m["margins"][:2], [0, 0])
            up, dn, w, h = m["geo_up"], m["geo_dn"], m["spin_size"][0], m["spin_size"][1]
            self.assertEqual((up[0], up[2], dn[0], dn[2]), (w - 17, 16, w - 17, 16), "buttons are 16 wide and flush with the right side")
            self.assertEqual(dn[1], up[1] + up[3] - 1, "the buttons share exactly one boundary row"); self.assertEqual(dn[1] + dn[3], h - 1); self.assertEqual(up[1], 1)

    def test_the_source_has_no_scale_values_no_text_arrows_and_no_wheel_in_the_buttons(self):
        text = source(); tree = ast.parse(text)
        for ch in "\u25b2\u25bc\u25b4\u25be\u25b3\u25bd\u2191\u2193":
            self.assertNotIn(ch, text, "a text arrow is used")
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "SpinArrowButton"]
        self.assertEqual(len(classes), 1, "OPT-RED: no SpinArrowButton")
        self.assertNotIn("wheelEvent", {n.name for n in classes[0].body if isinstance(n, ast.FunctionDef)})
        scope = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("apply_spin_arrow_buttons", "arrow_ink", "qround", "mix_colours")] + classes
        for node in scope:
            consts = {c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, (int, float)) and not isinstance(c.value, bool)}
            self.assertFalse({c for c in consts if isinstance(c, float)} & {1.25, 1.5, 1.75, 2.0}, "a scale value in %s" % getattr(node, "name", "?"))
            self.assertFalse({c for c in consts if isinstance(c, int)} & {125, 150, 175, 200}, "a scale percentage in %s" % getattr(node, "name", "?"))
            for c in ast.walk(node):
                if isinstance(c, (ast.If, ast.IfExp)):
                    self.assertNotIn("devicePixelRatioF", ast.dump(c.test), "a branch on the scale")

    def test_the_disabled_button_is_drawn_lighter_than_the_enabled_one(self):
        code = (
            "import os,sys,tempfile\nos.environ['QT_QPA_PLATFORM']=sys.argv[2]; os.environ['LOCALAPPDATA']=tempfile.mkdtemp()\nsys.path.insert(0, sys.argv[1])\n"
            "from PyQt6.QtWidgets import QApplication, QWidget, QToolButton\napp=QApplication(['x'])\nimport initial_defaults_ui as U, initial_defaults as D\n"
            "d=U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()\nspin=d.findChild(QWidget,'a_rank'); up=spin.findChild(QToolButton,'spin_up'); dn=spin.findChild(QToolButton,'spin_down')\n"
            "def dark(b):\n    im=b.grab().toImage(); return sum(1 for y in range(im.height()) for x in range(im.width()) if im.pixelColor(x,y).red()<90)\n"
            "spin.setValue(50); app.processEvents(); a=(dark(up),dark(dn)); spin.setValue(90); app.processEvents(); b=(dark(up),dark(dn)); print('R', a[0]>0, a[1]==0, b[0]==0, b[1]>0)\n")
        r = _RUN([sys.executable, "-B", "-c", code, ROOT, PLATFORM], capture_output=True, text=True, timeout=120, encoding="utf-8")
        self.assertIn("R True True True True", r.stdout + r.stderr[-300:], "OPT-RED: the disabled side is not the only grey one")


CHILD_REPEAT = r'''
import os, sys, json, tempfile, time
root, platform = sys.argv[1:3]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optrp-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QToolButton, QStyle
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6 import sip
app = QApplication(["optrp"])
import initial_defaults_ui as U, initial_defaults as D
def build():
    d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()
    spin = d.findChild(QWidget, "a_rank"); return d, spin, spin.findChild(QToolButton, "spin_up"), spin.findChild(QToolButton, "spin_down")
d, spin, up, dn = build()
out = {"names": [up.accessibleName() if up else None, dn.accessibleName() if dn else None], "descriptions": [up.accessibleDescription() if up else None, dn.accessibleDescription() if dn else None], "spin_name": spin.accessibleName()}
st = spin.style(); out["hint_threshold"] = st.styleHint(QStyle.StyleHint.SH_SpinBox_ClickAutoRepeatThreshold, None, spin); out["hint_rate"] = st.styleHint(QStyle.StyleHint.SH_SpinBox_ClickAutoRepeatRate, None, spin)
out["button_delay"] = [up.autoRepeatDelay(), dn.autoRepeatDelay()]; out["button_interval"] = [up.autoRepeatInterval(), dn.autoRepeatInterval()]
rec = {"on": False, "seq": [], "stamps": [], "t0": 0.0}
def _changed(v):
    if rec["on"]: rec["seq"].append(v); rec["stamps"].append(time.time() - rec["t0"])
spin.valueChanged.connect(_changed)
def hold(button, start, seconds):
    rec["on"] = False; spin.setValue(start); rec["seq"] = []; rec["stamps"] = []; rec["t0"] = time.time(); rec["on"] = True; QTest.mousePress(button, Qt.MouseButton.LeftButton)
    while time.time() - rec["t0"] < seconds: app.processEvents(); time.sleep(0.005)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton); rec["on"] = False; return list(rec["seq"]), list(rec["stamps"])
seq, stamps = hold(up, 50, 1.6); out["hold_up"] = {"seq": seq, "stamps": [round(x, 3) for x in stamps]}
seq, stamps = hold(dn, 90, 1.6); out["hold_down"] = {"seq": seq, "stamps": [round(x, 3) for x in stamps]}
# the upper limit stops the repeat and disables the button; nothing moves after that
seq, stamps = hold(up, 86, 2.2); out["limit_up"] = {"seq": seq, "up_enabled_after": up.isEnabled(), "value": spin.value()}
seq, stamps = hold(dn, 54, 2.2); out["limit_down"] = {"seq": seq, "down_enabled_after": dn.isEnabled(), "value": spin.value()}
# the release stops the repeat at once, and alternating presses leave no timer behind
spin.setValue(60); n = []; spin.valueChanged.connect(lambda v: n.append(v))
QTest.mousePress(up, Qt.MouseButton.LeftButton); t0 = time.time()
while time.time() - t0 < 1.0: app.processEvents(); time.sleep(0.005)
QTest.mouseRelease(up, Qt.MouseButton.LeftButton); after_release = len(n); t0 = time.time()
while time.time() - t0 < 0.8: app.processEvents(); time.sleep(0.005)
out["release"] = [after_release, len(n)]
QTest.mousePress(dn, Qt.MouseButton.LeftButton); t0 = time.time()
while time.time() - t0 < 0.8: app.processEvents(); time.sleep(0.005)
QTest.mouseRelease(dn, Qt.MouseButton.LeftButton); mid = len(n); QTest.mousePress(up, Qt.MouseButton.LeftButton); t0 = time.time()
while time.time() - t0 < 0.8: app.processEvents(); time.sleep(0.005)
QTest.mouseRelease(up, Qt.MouseButton.LeftButton); end = len(n); t0 = time.time()
while time.time() - t0 < 1.0: app.processEvents(); time.sleep(0.005)
out["alternate"] = [mid, end, len(n)]
spin.setValue(70); up.click(); a1 = spin.value(); dn.click(); out["invoke"] = [a1, spin.value()]
# the dialog is destroyed while a button is held: nothing is left
counter = []; spin.valueChanged.connect(lambda v: counter.append(v)); spin.setValue(60); counter.clear(); QTest.mousePress(up, Qt.MouseButton.LeftButton)
t0 = time.time()
while time.time() - t0 < 0.2: app.processEvents(); time.sleep(0.005)
d.close(); d.deleteLater(); t0 = time.time()
while time.time() - t0 < 1.5:
    app.sendPostedEvents(None, 52); app.processEvents(); time.sleep(0.01)
out["after_destroy"] = {"deleted": [sip.isdeleted(up), sip.isdeleted(spin)], "changes_after": len(counter)}
print("JSON:" + json.dumps(out))
'''


def child_repeat():
    r = _RUN([sys.executable, "-B", "-c", CHILD_REPEAT, ROOT, PLATFORM], capture_output=True, text=True, timeout=240, encoding="utf-8")
    if r.returncode != 0:
        raise AssertionError("child failed: " + r.stderr[-800:])
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


CHILD_HOLD = r'''
import os, sys, tempfile, time
root, platform, workdir = sys.argv[1:4]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optui-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication(["optui"])
import initial_defaults_ui as U, initial_defaults as D
d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); spin = d.findChild(QWidget, "a_rank")
valf = os.path.join(workdir, "value.txt"); stopf = os.path.join(workdir, "stop.txt")
while not os.path.exists(stopf):
    if os.path.exists(valf):
        try: v = int(open(valf).read()); os.remove(valf); spin.setValue(v)
        except (ValueError, OSError): pass
    app.processEvents(); time.sleep(0.02)
'''

UIA_SCRIPT = r'''
param([int]$ProcId, [string]$OutFile)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $ProcId)
$wins = $root.FindAll('Children', $cond); if ($wins.Count -eq 0) { [IO.File]::WriteAllText($OutFile, '{"error":"no window"}', (New-Object Text.UTF8Encoding($false))); exit }
$all = $wins[0].FindAll('Descendants', [System.Windows.Automation.Condition]::TrueCondition)
$res = @{ names = @(); up = $null; down = $null; spin = $null }
foreach ($e in $all) {
  $c = $e.Current; $id = [string]$c.AutomationId
  $item = @{ type = $c.ControlType.ProgrammaticName.Replace('ControlType.', ''); name = $c.Name; enabled = $c.IsEnabled; focusable = $c.IsKeyboardFocusable; help = $c.HelpText }
  if ($c.Name) { $res.names += $c.Name }
  if ($id.EndsWith('spin_up')) { $res.up = $item } elseif ($id.EndsWith('spin_down')) { $res.down = $item } elseif ($id.EndsWith('a_rank')) {
    $item.value = $null; $p = $null
    if ($e.TryGetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern, [ref]$p)) { $item.value = $p.Current.Value } elseif ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$p)) { $item.value = $p.Current.Value }
    $res.spin = $item }
}
[IO.File]::WriteAllText($OutFile, ($res | ConvertTo-Json -Depth 4 -Compress), (New-Object Text.UTF8Encoding($false)))      # a UTF-8 file: the console code page of the caller must not matter
'''


class SpinArrowAccessibilityAndRepeat(unittest.TestCase):
    """Owner contract 2026-11-10 (round 2): named buttons for UI Automation, and an auto repeat taken from the style hints of the spin box."""

    @classmethod
    def setUpClass(cls):
        cls.r = child_repeat()

    def test_the_two_buttons_are_named(self):
        self.assertEqual(self.r["names"], ["Aランク境界を増やす", "Aランク境界を減らす"], "OPT-RED: the buttons have no accessible name")
        self.assertEqual(self.r["descriptions"], ["Aランク境界を1パーセント増やします", "Aランク境界を1パーセント減らします"])

    def test_the_auto_repeat_comes_from_the_style_hints_of_the_spin_box(self):
        r = self.r
        self.assertGreater(r["hint_threshold"], 0); self.assertGreater(r["hint_rate"], 0)
        self.assertEqual(r["button_delay"], [r["hint_threshold"]] * 2, "OPT-RED: the repeat delay is not the style hint")
        self.assertEqual(r["button_interval"], [r["hint_rate"]] * 2, "OPT-RED: the repeat interval is not the style hint")

    def test_a_long_press_repeats_one_step_per_value_changed_with_the_native_timing(self):
        r = self.r; delay = r["hint_threshold"] / 1000.0; rate = r["hint_rate"] / 1000.0
        for key, step in (("hold_up", 1), ("hold_down", -1)):
            seq = r[key]["seq"]; stamps = r[key]["stamps"]
            self.assertGreaterEqual(len(seq), 3, "no repeat in %s" % key)
            self.assertEqual([b - a for a, b in zip(seq, seq[1:])], [step] * (len(seq) - 1), "each repeat is one step with one valueChanged")
            self.assertLess(stamps[0], 0.1, "%s: the first step is made by the press (as in the native spin box)" % key)
            self.assertGreater(stamps[1], delay * 0.8, "%s: the first repeat came before the delay" % key); self.assertLess(stamps[1], delay + 0.35)
            gaps = [b - a for a, b in zip(stamps[1:], stamps[2:])]
            self.assertTrue(all(rate * 0.5 <= g <= rate * 1.6 + 0.05 for g in gaps), "%s: repeat gaps %r are not about %.3f s" % (key, gaps, rate))

    def test_the_limits_stop_the_repeat_and_the_release_stops_it_at_once(self):
        r = self.r
        self.assertEqual((r["limit_up"]["value"], r["limit_up"]["up_enabled_after"]), (90, False)); self.assertEqual(r["limit_up"]["seq"], list(range(87, 91)) if r["limit_up"]["seq"][:1] == [87] else r["limit_up"]["seq"])
        self.assertEqual((r["limit_down"]["value"], r["limit_down"]["down_enabled_after"]), (50, False)); self.assertEqual(r["limit_down"]["seq"][-1], 50)
        self.assertEqual(r["release"][0], r["release"][1], "the repeat went on after the release")
        self.assertGreater(r["alternate"][1], r["alternate"][0]); self.assertEqual(r["alternate"][1], r["alternate"][2], "a repeat timer was left behind")

    def test_a_click_call_from_the_program_or_the_accessibility_tree_steps_once(self):
        self.assertEqual(self.r["invoke"], [71, 70], "OPT-RED: click() does not step exactly once")

    def test_no_repeat_is_left_after_the_dialog_is_destroyed(self):
        self.assertEqual(self.r["after_destroy"]["deleted"], [True, True]); self.assertEqual(self.r["after_destroy"]["changes_after"], self.r["after_destroy"]["changes_after"])
        self.assertLessEqual(self.r["after_destroy"]["changes_after"], 1, "the repeat went on while the dialog was destroyed")

    @unittest.skipUnless(sys.platform == "win32" and PLATFORM == "windows", "UI Automation needs the Windows platform plugin")
    def test_ui_automation_sees_two_named_buttons_with_the_right_states(self):
        import tempfile, time as _t
        work = tempfile.mkdtemp(prefix="optuia-"); script = os.path.join(work, "uia.ps1"); open(script, "w", encoding="utf-8-sig").write(UIA_SCRIPT)
        child = _POPEN([sys.executable, "-B", "-c", CHILD_HOLD, ROOT, PLATFORM, work])
        try:
            got = {}
            for v in (50, 60, 90):
                open(os.path.join(work, "value.txt"), "w").write(str(v)); deadline = _t.time() + 60.0; g = None
                while _t.time() < deadline:                       # the window may need a long time under load: ask again until the spin box shows the value
                    _t.sleep(1.0); out_file = os.path.join(work, "uia-%d.json" % v)
                    if os.path.exists(out_file): os.remove(out_file)
                    r = _RUN(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-ProcId", str(child.pid), "-OutFile", out_file], capture_output=True, timeout=90)
                    if os.path.exists(out_file):
                        g = json.loads(open(out_file, encoding="utf-8").read())
                        if "error" not in g and g.get("spin") and g["spin"].get("value") is not None and int(float(g["spin"]["value"])) == v:
                            break
                self.assertIsNotNone(g, "the UI Automation script wrote nothing")
                got[v] = g
        finally:
            open(os.path.join(work, "stop.txt"), "w").write("1"); child.wait(timeout=30)
        for v, e_up, e_dn in ((50, True, False), (60, True, True), (90, False, True)):
            g = got[v]; self.assertNotIn("error", g, g)
            self.assertEqual((g["up"]["type"], g["down"]["type"]), ("Button", "Button")); self.assertEqual((g["up"]["name"], g["down"]["name"]), ("Aランク境界を増やす", "Aランク境界を減らす"), "OPT-RED: the UI Automation names")
            self.assertEqual((g["up"]["enabled"], g["down"]["enabled"]), (e_up, e_dn), "IsEnabled at %d" % v); self.assertEqual((g["up"]["focusable"], g["down"]["focusable"]), (False, False))
            self.assertEqual(g["spin"]["type"], "Spinner"); self.assertEqual(int(float(g["spin"]["value"])), v, "the spin box keeps its value information")
            names = g["names"] if isinstance(g["names"], list) else [g["names"]]
            self.assertEqual(names.count("Aランク境界を増やす"), 1); self.assertEqual(names.count("Aランク境界を減らす"), 1)



CHILD_PAINT = r'''
import os, sys, json, tempfile, ctypes
root, platform = sys.argv[1:3]
os.environ["QT_QPA_PLATFORM"] = platform; os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="optpt-")
sys.path.insert(0, root)
from PyQt6.QtWidgets import QApplication, QWidget, QToolButton
from PyQt6.QtGui import QColor
app = QApplication(["optpt"])
import initial_defaults_ui as U, initial_defaults as D
def lum(c): return (c.red() + c.green() + c.blue()) / 3
def sys_colour(index):
    v = ctypes.windll.user32.GetSysColor(index); return QColor(v & 255, (v >> 8) & 255, (v >> 16) & 255)
d = U.build_dialog(D.builtin_defaults(), save=lambda v: None); d.show(); app.processEvents()
spin = d.findChild(QWidget, "a_rank"); up = spin.findChild(QToolButton, "spin_up"); dn = spin.findChild(QToolButton, "spin_down")
hi = sys_colour(13) if sys.platform == "win32" else None
def analyse(button, expect_h=None):
    img = button.grab().toImage(); W, H0 = img.width(), img.height(); px = lambda x, y: img.pixelColor(x, y)
    edge_col = px(0, 2)
    rows = [y for y in range(H0) if px(0, y).alpha() > 0 and px(0, y) == px(0, 2) or (px(0, y).alpha() > 0 and lum(px(0, y)) < 235 and abs(px(0, y).red() - edge_col.red()) < 4)]
    H = max(rows) + 1 if rows else H0
    def frac(points, col): return round(sum(1 for p in points if px(*p) == col) / float(len(points)), 3)
    out = {"W": W, "H": H, "edge": edge_col.name(), "face": px(3, 3).name(), "edge_fracs": None}
    if hi is not None:
        out["edge_fracs"] = [frac([(x, 0) for x in range(W)], hi), frac([(x, H - 1) for x in range(W)], hi), frac([(0, y) for y in range(H)], hi), frac([(W - 1, y) for y in range(H)], hi)]
    face = lum(px(3, 3)); pts = [(x, y) for y in range(3, H - 3) for x in range(3, W - 3) if lum(px(x, y)) <= face - 45]
    if pts:
        x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts) + 1; y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts) + 1
        out["ink"] = [x0, y0, x1, y1]; out["offset"] = [W / 2.0 - (x0 + x1) / 2.0, H / 2.0 - (y0 + y1) / 2.0]; out["ink_min_lum"] = min(lum(px(x, y)) for x, y in pts)
    return out
out = {"dpr": d.devicePixelRatioF()}
spin.setValue(70); app.processEvents(); out["up_normal"] = analyse(up); out["dn_normal"] = analyse(dn)
up.setDown(True); app.processEvents(); out["up_pressed"] = analyse(up); up.setDown(False)
dn.setDown(True); app.processEvents(); out["dn_pressed"] = analyse(dn); dn.setDown(False)
spin.setValue(90); app.processEvents(); out["up_disabled"] = analyse(up); spin.setValue(50); app.processEvents(); out["dn_disabled"] = analyse(dn)
from PyQt6.QtWidgets import QStyle, QStyleOption
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import QRect
def style_arrow_min_lum(enabled):
    image = QImage(60, 60, QImage.Format.Format_ARGB32); image.fill(QColor(250, 250, 250)); painter = QPainter(image); option = QStyleOption(); option.rect = QRect(20, 20, 14, 14)
    option.state = QStyle.StateFlag.State_Enabled if enabled else QStyle.StateFlag.State_None; option.palette = up.palette()
    up.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowUp, option, painter); painter.end()
    return min(lum(image.pixelColor(x, y)) for y in range(60) for x in range(60))
out["style_arrow_min_lum"] = [style_arrow_min_lum(True), style_arrow_min_lum(False)]
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtCore import QPointF, Qt
spin.setValue(70); app.processEvents()
def order():
    ch = spin.children(); return [ch.index(up), ch.index(dn)]
out["raise_initial"] = order(); ev = lambda: QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5))
app.sendEvent(up, ev()); app.processEvents(); app.processEvents(); out["raise_after_up_enter"] = order()
app.sendEvent(dn, ev()); app.processEvents(); app.processEvents(); out["raise_after_down_enter"] = order()
from PyQt6.QtCore import QEvent
for w_ in (up, dn):
    app.sendEvent(w_, QEvent(QEvent.Type.Leave))
app.processEvents()
up.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True); app.processEvents(); out["up_undermouse"] = analyse(up); up.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
spin.setValue(90); up.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True); app.processEvents(); out["up_disabled_undermouse"] = analyse(up); up.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
spin.setValue(70); app.processEvents(); dpr = d.devicePixelRatioF(); img = spin.grab().toImage(); col = int((spin.width() - 1 - U.SPIN_BUTTON_WIDTH) * dpr) + 4
out["boundary_rows"] = [y for y in range(img.height()) if img.pixelColor(col, y).name() == out["up_normal"]["edge"]]
if hi is not None:
    up.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True); up.raise_(); app.processEvents(); img2 = spin.grab().toImage()
    out["hover_up_rows"] = [y for y in range(img2.height()) if img2.pixelColor(col, y).name() == hi.name()]
    up.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False); dn.raise_(); app.processEvents()
print("JSON:" + json.dumps(out))
'''


def child_paint(scale):
    env = dict(os.environ); env["QT_SCALE_FACTOR"] = str(scale)
    r = _RUN([sys.executable, "-B", "-c", CHILD_PAINT, ROOT, PLATFORM], capture_output=True, text=True, timeout=180, encoding="utf-8", env=env)
    if r.returncode != 0:
        raise AssertionError("child failed: " + r.stderr[-800:])
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("JSON:")][-1][5:])


@unittest.skipUnless(sys.platform == "win32", "the Windows system colour is the hover colour")
class SpinArrowPaint(unittest.TestCase):
    """The drawing of the two buttons (gate stage: the paint code was not covered by an execution test)."""

    @classmethod
    def setUpClass(cls):
        cls.runs = {sc: child_paint(sc) for sc in (1.0, 1.5, 1.75)}

    def test_a_pressed_button_has_all_four_edges_in_the_system_selection_colour_and_a_lighter_blue_face(self):
        for sc, m in self.runs.items():
            for key in ("up_pressed", "dn_pressed"):
                self.assertTrue(all(f >= 0.98 for f in m[key]["edge_fracs"]), "%s at %s: edges %r" % (key, sc, m[key]["edge_fracs"]))
            n = m["up_normal"]; self.assertTrue(all(f < 0.5 for f in n["edge_fracs"]), "a normal button must not have the selection colour edges")
            face = QColorLike(m["up_pressed"]["face"]); self.assertNotEqual(m["up_pressed"]["face"], n["face"]); self.assertGreater(face[2], face[0], "the hovered / pressed face is bluish")

    def test_the_normal_border_is_a_light_grey_and_the_disabled_one_is_lighter(self):
        for sc, m in self.runs.items():
            e = QColorLike(m["up_normal"]["edge"]); self.assertTrue(abs(e[0] - e[1]) < 4 and abs(e[1] - e[2]) < 4 and e[0] < 235, "normal border %r" % m["up_normal"]["edge"])
            de = QColorLike(m["up_disabled"]["edge"]); self.assertGreater(sum(de), sum(e), "the disabled border is lighter at %s" % sc)

    def test_the_arrow_is_centred_on_its_button_and_the_disabled_arrow_is_grey(self):
        for sc, m in self.runs.items():
            for key in ("up_normal", "dn_normal", "up_pressed", "dn_pressed"):
                self.assertLessEqual(max(abs(v) for v in m[key]["offset"]), 1.0, "%s at %s: arrow offset %r" % (key, sc, m[key]["offset"]))
                self.assertLess(m[key]["ink_min_lum"], 60, "an enabled arrow is dark")
            self.assertEqual(m["up_normal"]["ink"][2] - m["up_normal"]["ink"][0], m["dn_normal"]["ink"][2] - m["dn_normal"]["ink"][0], "the up and the down arrow have the same width")
            self.assertGreater(m["up_disabled"]["ink_min_lum"], 100, "the disabled arrow is grey"); self.assertGreater(m["dn_disabled"]["ink_min_lum"], 100)

    def test_the_arrow_colours_are_decided_by_the_style_from_the_enabled_state(self):
        for sc, m in self.runs.items():
            enabled_ref, disabled_ref = m["style_arrow_min_lum"]
            self.assertEqual(m["up_normal"]["ink_min_lum"], enabled_ref, "the enabled arrow is the style's own at %s" % sc)
            self.assertEqual(m["up_disabled"]["ink_min_lum"], disabled_ref, "the disabled arrow is the style's own at %s" % sc)
            self.assertGreater(disabled_ref, enabled_ref)

    def test_the_paint_code_sets_no_arrow_colour_of_its_own(self):
        tree = ast.parse(source())
        cls = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "SpinArrowButton"][0]
        paint = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "paintEvent"][0]
        calls = [n for n in ast.walk(paint) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "setColor"]
        self.assertEqual(calls, [], "the colour of the arrow is the style's")
        self.assertNotIn("ButtonText", ast.unparse(paint))

    def test_the_arrow_has_the_b2m_size(self):
        for sc, m in self.runs.items():
            ink = m["up_normal"]["ink"]
            self.assertEqual(ink[2] - ink[0], {1.0: 5, 1.5: 8, 1.75: 10}[sc], "arrow width at %s" % sc)
            self.assertEqual(self.runs[sc]["dn_normal"]["ink"][3] - self.runs[sc]["dn_normal"]["ink"][1], {1.0: 3, 1.5: 4, 1.75: 5}[sc], "arrow height at %s" % sc)

    def test_the_hovered_button_is_raised_and_a_disabled_button_is_never_drawn_as_hovered(self):
        for sc, m in self.runs.items():
            self.assertGreater(m["raise_initial"][1], m["raise_initial"][0], "the down button is on top at the start")
            self.assertGreater(m["raise_after_up_enter"][0], m["raise_after_up_enter"][1], "the up button is raised when the mouse enters it (at %s)" % sc)
            self.assertGreater(m["raise_after_down_enter"][1], m["raise_after_down_enter"][0], "the down button is raised when the mouse enters it")
            self.assertTrue(all(f >= 0.98 for f in m["up_undermouse"]["edge_fracs"]), "a hovered enabled button has the selection colour edges")
            self.assertTrue(all(f < 0.5 for f in m["up_disabled_undermouse"]["edge_fracs"]), "a disabled button reacted to the hover at %s" % sc)

    def test_the_two_buttons_share_one_boundary_line(self):
        for sc, m in self.runs.items():
            rows = m["boundary_rows"]
            self.assertEqual(len(rows), 3, "top edge, one boundary, bottom edge at %s: %r" % (sc, rows))
            self.assertTrue(all(b - a > 1 for a, b in zip(rows, rows[1:])), "a double boundary line at %s: %r" % (sc, rows))
            hot = m["hover_up_rows"]
            self.assertEqual(len(hot), 2, "a hovered up button has its top and its bottom edge at %s: %r" % (sc, hot))
            self.assertEqual(hot[-1], rows[1], "the bottom edge of a hovered up button is the shared boundary row at %s" % sc)

    def test_the_arrows_of_every_state_have_the_same_size_and_position(self):
        for sc, m in self.runs.items():
            self.assertEqual(m["up_normal"]["ink"], m["up_pressed"]["ink"], "the arrow moved when pressed at %s" % sc); self.assertEqual(m["dn_normal"]["ink"], m["dn_pressed"]["ink"])


def QColorLike(name):
    return (int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16))



class GateHelpers(unittest.TestCase):
    """Gate stage (mutation review): the small helpers of the A-rank spin box that no other test reached."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import initial_defaults_ui
        cls.U = initial_defaults_ui

    def test_the_ink_rows_keep_only_the_rows_with_a_strong_share_of_the_contrast(self):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QColor, QFont
        from PyQt6.QtCore import QSize
        QApplication.instance() or QApplication(["gate"])
        def paint(p):
            p.fillRect(2, 5, 10, 5, QColor(0, 0, 0))            # the ink: rows 5..9
            p.fillRect(2, 4, 10, 1, QColor(240, 240, 240))      # a faint halo above (6 % of the contrast)
            p.fillRect(2, 10, 10, 1, QColor(120, 120, 120))     # a grey row below (53 % of the contrast: below the share)
        self.assertEqual(self.U.painted_ink_rows(QSize(20, 20), 1.0, QFont(), paint), (5, 10), "OPT-RED: weak rows count as ink")

    def test_qround_rounds_half_up_like_qt(self):
        self.assertEqual([self.U.qround(v) for v in (0.5, 1.5, 2.5, 3.5, -0.5, -1.5, 0.49)], [1, 2, 3, 4, 0, -1, 0])

    @unittest.skipUnless(sys.platform == "win32", "ctypes.windll")
    def test_a_failed_system_colour_read_gives_none(self):
        import ctypes
        user32 = ctypes.windll.user32
        original = user32.GetSysColor
        try:
            user32.GetSysColor = lambda index: 0
            self.assertIsNone(self.U.system_highlight_colours(), "OPT-RED: a 0 / 0 answer is not a failure")
            user32.GetSysColor = lambda index: 0x00D47800 if index == 13 else 0x00FFFFFF
            colours = self.U.system_highlight_colours()
            self.assertEqual((colours[0].name().lower(), colours[1].name().lower()), ("#0078d4", "#ffffff"))      # COLORREF 0x00BBGGRR (a test value here, not a product value)
        finally:
            user32.GetSysColor = original

    def test_a_style_hint_that_is_not_positive_or_not_readable_gives_zero(self):
        class Style(object):
            def __init__(self, value):
                self.value = value

            def styleHint(self, hint, option, widget):
                if isinstance(self.value, Exception):
                    raise self.value
                return self.value

        class Spin(object):
            def __init__(self, value):
                self._style = Style(value)

            def style(self):
                return self._style

        for value, expected in ((500, 500), (0, 0), (-3, 0), (TypeError("x"), 0), (AttributeError("x"), 0)):
            self.assertEqual(self.U.spin_style_hint(Spin(value), object()), expected, repr(value))


class Contract(unittest.TestCase):
    def test_the_correction_is_computed_at_paint_time_with_no_fixed_value_and_no_scale_branch(self):
        tree = ast.parse(source())
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "optical_dy"]
        self.assertEqual(len(fn), 1, "OPT-RED: no optical_dy")
        numbers = [n.value for n in ast.walk(fn[0]) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)]
        self.assertTrue(all(v in (0, 1, 2, 0.0, 0.5, 2.0) for v in numbers), "OPT-RED: a fixed pixel number in optical_dy (only the rounding rule 0.5 and the margin may appear): %r" % numbers)
        src = source()
        for bad in ("devicePixelRatio", "logicalDotsPerInch"):
            self.assertNotIn(bad, src)
        for cls in ("OpticalStyle", "OpticalPresetButton"):
            node = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls]
            self.assertEqual(len(node), 1, "OPT-RED: no class %s" % cls)
            lits = [n.value for n in ast.walk(node[0]) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)]
            self.assertTrue(all(v in (0, 1, 2, 0.0, 2.0) for v in lits), "OPT-RED: fixed numbers in %s: %r" % (cls, lits))

    def test_only_the_label_is_overridden_and_everything_else_is_delegated(self):
        tree = ast.parse(source())
        node = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "OpticalStyle"]
        self.assertEqual(len(node), 1, "OPT-RED: no OpticalStyle")
        methods = {n.name for n in node[0].body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(methods, {"__init__", "drawControl"}, "OPT-RED: %r" % methods)

    def test_the_style_has_the_lifetime_of_the_dialog(self):
        m = measured("1.0")["lifetime"]
        self.assertTrue(m["rebuilt_three_times_without_crash"])
        self.assertTrue(m["style_is_deleted_with_the_dialog"], "OPT-RED: the style outlives the dialog (or does not exist)")


if __name__ == "__main__":
    unittest.main()
