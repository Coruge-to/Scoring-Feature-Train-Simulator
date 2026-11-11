"""INITIAL-DEFAULTS Commit 5 (Owner contract 2026-11-10): the easy settings (簡単設定) of the 'initial defaults' window. RED = fails on e2294bd; messages start with 'ID5-RED'.

Contract
  * three buttons 初級 / 中級 / 上級 (objectName preset_beginner / preset_intermediate / preset_advanced), coloured with the EXISTING colour constants of config.py (green COLOR_N, blue COLOR_P, red COLOR_B_EMG: the colours the F1 page
    and the HUD already use); no new RGB value; no preset explanation text (only the note about when the settings apply).
  * a preset changes the six deductions and the A boundary ONLY: rolling ON, safety intervention OFF (never on), speed limit / stop shock / emergency brake / initial-release brake / A boundary as the table:
    初級: speed limit OFF, stop shock OFF, emergency brake ON, initial-release OFF, A 50; 中級: ON, ON, ON, OFF, 60; 上級: ON, ON, ON, ON① (on1), 70.
    The 8 environment items and the all-timing setting are never changed (whatever their current value).
  * after a preset the A boundary can still be changed (50..90); out of range is refused at the save (never clamped silently).
  * x / Esc discards a preset change; OK saves the result; a reopened window shows the saved values."""
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-initdef-preset-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "USERPROFILE", "HOME")}
    for k in _TMP["saved"]:
        os.environ[k] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


PRESET_IDS = (("beginner", "初級", "preset_beginner", "COLOR_N"), ("intermediate", "中級", "preset_intermediate", "COLOR_P"), ("advanced", "上級", "preset_advanced", "COLOR_B_EMG"))
TABLE = {
    "beginner": dict(rolling=True, speed=False, shock=False, eb=True, init=False, a=50),
    "intermediate": dict(rolling=True, speed=True, shock=True, eb=True, init=False, a=60),
    "advanced": dict(rolling=True, speed=True, shock=True, eb=True, init=True, a=70),
}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-preset"])
        import initial_defaults_ui
        import initial_defaults
        import config
        cls.U, cls.D, cls.C = initial_defaults_ui, initial_defaults, config

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="idp-", dir=_TMP["dir"].name)
        self.path = os.path.join(self.dir, "TS Scoring", "initial-defaults.json")
        self.dialogs = []

    def tearDown(self):
        for d in self.dialogs:
            d.close()
            d.deleteLater()

    def make(self, defaults=None, save=None):
        d = self.U.build_dialog(defaults or self.D.builtin_defaults(), save=save or (lambda v: self.D.save(v, self.path)))
        self.dialogs.append(d)
        return d

    def find(self, dialog, name):
        from PyQt6.QtWidgets import QWidget
        w = dialog.findChild(QWidget, name)
        self.assertIsNotNone(w, "ID5-RED: no widget %r" % name)
        return w

    def shown(self, d):
        return dict(rolling=self.find(d, "pen_rolling").isChecked(), speed=self.find(d, "pen_speed").isChecked(), shock=self.find(d, "pen_shock").isChecked(), eb=self.find(d, "pen_eb").isChecked(),
                    init=self.find(d, "pen_init").isChecked(), a=self.find(d, "a_rank").value())


class Presets(Base):
    def test_the_three_buttons_exist_with_their_names(self):
        d = self.make()
        for key, label, oid, _ in PRESET_IDS:
            self.assertEqual(self.find(d, oid).text(), label)
        from PyQt6.QtWidgets import QLabel
        self.assertIn("簡単設定", [w.text() for w in d.findChildren(QLabel)])

    def test_each_preset_shows_and_collects_its_table(self):
        for key, label, oid, _ in PRESET_IDS:
            d = self.make(self.D.builtin_defaults()._replace(a_rank_percent=85))
            self.find(d, "pen_speed").setChecked(not TABLE[key]["speed"])
            self.find(d, oid).click()
            self.assertEqual(self.shown(d), TABLE[key], "ID5-RED: the %s preset" % label)
            got = self.U.collect(d)
            self.assertEqual((got.penalties.rolling, got.penalties.speed_limit_exceeded, got.penalties.stop_shock, got.penalties.emergency_brake, got.penalties.initial_release_brake, got.a_rank_percent),
                             (True, TABLE[key]["speed"], TABLE[key]["shock"], True, "on1" if TABLE[key]["init"] else "off", TABLE[key]["a"]))
            self.assertIs(got.penalties.safety_intervention, False)

    def test_the_safety_intervention_is_off_after_every_preset(self):
        d = self.make()
        for _, _, oid, _ in PRESET_IDS:
            self.find(d, oid).click()
            self.assertFalse(self.find(d, "pen_safety").isChecked(), "ID5-RED: a preset turned the safety intervention ON")

    def test_a_preset_never_changes_the_environment_or_the_timing_setting(self):
        for timing in (True, False):
            b = self.D.builtin_defaults()
            odd = b._replace(all_changeable_non_timed_to_timed=timing, environment=type(b.environment)(True, False, True, True, False, False, True, False))
            for _, _, oid, _ in PRESET_IDS:
                d = self.make(odd)
                before = ([self.find(d, "env_%d" % i).isChecked() for i in range(8)], self.find(d, "timing").isChecked())
                self.find(d, oid).click()
                after = ([self.find(d, "env_%d" % i).isChecked() for i in range(8)], self.find(d, "timing").isChecked())
                self.assertEqual(after, before, "ID5-RED: preset %s changed the environment / timing-station setting (timing=%s)" % (oid, timing))
                self.assertEqual(self.U.collect(d).environment, odd.environment)
                self.assertIs(self.U.collect(d).all_changeable_non_timed_to_timed, timing)

    def test_the_colours_are_the_existing_constants_and_no_new_rgb(self):
        d = self.make()
        for _, _, oid, const in PRESET_IDS:
            r, g, b = tuple(getattr(self.C, const))[:3]
            self.assertIn("rgb(%d, %d, %d)" % (r, g, b), self.find(d, oid).styleSheet().replace(" ", "").replace("rgb(%d,%d,%d)" % (r, g, b), "rgb(%d, %d, %d)" % (r, g, b)), "ID5-RED: %s is not %s" % (oid, const))
        src = source("initial_defaults_ui.py")
        for const in ("COLOR_N", "COLOR_P", "COLOR_B_EMG"):
            self.assertIn("config.%s" % const, src, "ID5-RED: the window does not use config.%s" % const)
        self.assertEqual(re.findall(r"rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+", src), [], "ID5-RED: a literal RGB value in the window module")

    def test_no_explanation_text_only_the_labels_and_the_note(self):
        d = self.make()
        from PyQt6.QtWidgets import QAbstractButton, QLabel
        texts = [w.text() for w in d.findChildren(QLabel)] + [w.text() for w in d.findChildren(QAbstractButton)]
        for bad in ("初級は", "中級は", "上級は", "理論値50", "理論値60", "理論値70", "初動と緩和以外"):
            self.assertFalse([t for t in texts if bad in t], "ID5-RED: an explanation text is shown (%s)" % bad)
        self.assertIn("※この設定は次にシナリオを読み込んだときに適用されます。", texts)

    def test_the_a_boundary_can_still_be_changed_after_a_preset(self):
        d = self.make()
        self.find(d, "preset_advanced").click()
        self.find(d, "a_rank").setValue(55)
        got = self.U.collect(d)
        self.assertEqual(got.a_rank_percent, 55)
        self.assertEqual((got.penalties.speed_limit_exceeded, got.penalties.initial_release_brake), (True, "on1"), "the advanced deductions stay")

    def test_an_a_boundary_out_of_range_is_not_saved_by_the_correcting_ok(self):
        """INITIAL-DEFAULTS Stage F2 (Owner 2026-11-11): the OK on an out-of-range value goes back to 60, shows the red input error and saves NOTHING (a second OK saves 60); it was a plain refusal before."""
        d = self.make()
        d.show()
        spin = self.find(d, "a_rank")
        spin.setRange(0, 100)                                            # (a window that let a wrong value through)
        spin.setValue(49)
        self.find(d, "ok").click()
        self.assertFalse(os.path.exists(self.path), "ID5-RED: an out-of-range A boundary was saved by the correcting OK")
        self.assertTrue(d.isVisible(), "the window stays open")
        self.assertEqual(self.find(d, "message").text(), self.U.A_RANK_INVALID)
        self.assertEqual(spin.value(), 60, "the field went back to 60")

    def test_close_discards_a_preset_and_ok_saves_the_result(self):
        d = self.make()
        d.show()
        self.find(d, "preset_beginner").click()
        d.close()
        self.assertFalse(os.path.exists(self.path), "ID5-RED: the x button saved the preset")
        d2 = self.make()
        d2.show()
        self.find(d2, "preset_advanced").click()
        self.find(d2, "ok").click()
        raw = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual((raw["penalties"]["initial_release_brake"], raw["a_rank_percent"], raw["penalties"]["safety_intervention"], raw["penalties"]["speed_limit_exceeded"]), ("on1", 70, False, True), "ID5-RED: OK did not save the preset result")
        d3 = self.make(self.D.load(self.path).defaults)
        self.assertEqual(self.shown(d3), TABLE["advanced"], "ID5-RED: the reopened window does not show the saved values")

    def test_no_preset_can_store_on2_or_the_safety_intervention(self):
        for name in self.D.PRESET_NAMES:
            p, a = self.D.PRESETS[name]
            self.assertIn(p.initial_release_brake, ("off", "on1"))
            self.assertIs(p.safety_intervention, False)
            self.assertTrue(self.D.a_rank_percent_valid(a))
        d = self.make()
        d.show()
        self.find(d, "preset_advanced").click()
        self.find(d, "ok").click()
        self.assertEqual(json.load(open(self.path, encoding="utf-8"))["penalties"]["initial_release_brake"], "on1")


if __name__ == "__main__":
    unittest.main()
