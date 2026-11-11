"""INITIAL-DEFAULTS Commit 2 (Owner contract 2026-11-10): the 'initial defaults' window opened by `main.py --initial-defaults` (the process the Caller starts from the Input Device Properties). RED = fails on 98e4698; messages start with 'ID2-RED'.

Contract
  * `main.py --initial-defaults` opens ONE window titled 初期値設定 (nothing else: not managed mode, no Overlay). Any other combination of arguments with the flag is refused (exit 2). A second start while one is open exits at once (named mutex).
  * left: 環境設定 8 rows (現在時刻, 残り時間, 現在速度, 制限速度, 制限速度予告, 残距離, ハンドル・レバーサ位置, 勾配) and 採時駅設定 (変更可能な非採時駅を全て採時駅にする); right: 減点項目設定 6 rows (転動, 保安装置介入, 速度制限超過, 停車時衝動,
    非常ブレーキ, 初動・緩和ブレーキ) and the A boundary (Aランクは理論値の [50..90] %以上); bottom: the note ※この設定は次にシナリオを読み込んだときに適用されます。 and OK; top right: x.
  * the speed limit / advance dependency is the SHARED state function (initial_defaults.set_speed_limit / set_speed_limit_advance).
  * 保安装置介入 is an EMPTY checkbox at its normal place that can not be turned ON (mouse, keyboard, setChecked), whatever the saved file says.
  * 初動・緩和ブレーキ: checked = ON① ("on1"), unchecked = OFF ("off"). No ON② anywhere.
  * OK validates and saves atomically, then closes; if the save fails the window stays open, a short message is shown and the old file is untouched. x / Esc: nothing is saved. Opening alone saves nothing (no file is created).
  * no preset explanation text is shown (the preset buttons come with a later commit)."""
import json
import os
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
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-initdef-ui-")
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


ENV_LABELS = ["現在時刻", "残り時間", "現在速度", "制限速度", "制限速度予告", "残距離", "ハンドル・レバーサ位置", "勾配"]
PEN_LABELS = ["転動", "保安装置介入", "速度制限超過", "停車時衝動", "非常ブレーキ", "初動・緩和ブレーキ"]
NOTE = "※この設定は次にシナリオを読み込んだときに適用されます。"
TIMING = "変更可能な非採時駅を全て採時駅にする"


def ui_module():
    try:
        import initial_defaults_ui
    except ImportError as exc:
        raise AssertionError("ID2-RED: the module initial_defaults_ui does not exist (%s)" % exc)
    return initial_defaults_ui


class Ui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-ui"])

    def setUp(self):
        self.U = ui_module()
        import initial_defaults
        self.D = initial_defaults
        self.dir = tempfile.mkdtemp(prefix="idu-", dir=_TMP["dir"].name)
        self.path = os.path.join(self.dir, "TS Scoring", "initial-defaults.json")
        self.dialogs = []

    def tearDown(self):
        for d in self.dialogs:
            d.close()
            d.deleteLater()

    def make(self, defaults=None, save=None):
        d = self.U.build_dialog(defaults or self.D.builtin_defaults(), save=save or (lambda value: self.D.save(value, self.path)))
        self.dialogs.append(d)
        return d

    def find(self, dialog, name):
        from PyQt6.QtWidgets import QWidget
        w = dialog.findChild(QWidget, name)
        self.assertIsNotNone(w, "ID2-RED: no widget %r" % name)
        return w

    def texts(self, dialog):
        from PyQt6.QtWidgets import QAbstractButton, QLabel
        return [w.text() for w in dialog.findChildren(QLabel)] + [w.text() for w in dialog.findChildren(QAbstractButton)]

    # ---------------------------------------------------------------- the window
    def test_title_and_labels(self):
        d = self.make()
        self.assertEqual(d.windowTitle(), "初期値設定")
        t = self.texts(d)
        for label in ENV_LABELS + PEN_LABELS + [TIMING, NOTE, "OK", "環境設定", "採時駅設定", "減点項目設定"]:
            self.assertIn(label, t, "ID2-RED: the label %r is missing" % label)
        self.assertEqual([self.find(d, "env_%d" % i).text() for i in range(8)], ENV_LABELS)
        self.assertEqual([self.find(d, n).text() for n in ("pen_rolling", "pen_safety", "pen_speed", "pen_shock", "pen_eb", "pen_init")], PEN_LABELS)

    def test_no_old_label_and_no_preset_explanation_is_shown(self):
        d = self.make()
        joined = "\n".join(self.texts(d))
        self.assertNotIn("ATS信号無視", joined)
        for bad in ("初級は", "中級は", "上級は", "理論値50%", "理論値50％", "&"):
            self.assertNotIn(bad, joined, "ID2-RED: %r must not be shown" % bad)

    def test_the_builtin_state_is_shown(self):
        d = self.make()
        self.assertEqual([self.find(d, "env_%d" % i).isChecked() for i in range(8)], [True] * 8)
        self.assertFalse(self.find(d, "timing").isChecked())
        self.assertEqual([self.find(d, n).isChecked() for n in ("pen_rolling", "pen_safety", "pen_speed", "pen_shock", "pen_eb", "pen_init")], [True, False, True, True, True, False])
        self.assertEqual(self.find(d, "a_rank").value(), 60)

    def test_the_saved_values_are_shown(self):
        b = self.D.builtin_defaults()
        shown = b._replace(a_rank_percent=77, all_changeable_non_timed_to_timed=True,
                           penalties=b.penalties._replace(rolling=False, stop_shock=False, initial_release_brake="on1"),
                           environment=type(b.environment)(*([True, False] * 4)))
        d = self.make(shown)
        self.assertEqual(self.find(d, "a_rank").value(), 77, "ID2-RED: the saved A boundary is not shown")
        self.assertFalse(self.find(d, "pen_rolling").isChecked(), "ID2-RED: the saved rolling value is not shown")
        self.assertFalse(self.find(d, "pen_shock").isChecked())
        self.assertTrue(self.find(d, "pen_init").isChecked())
        self.assertTrue(self.find(d, "timing").isChecked())
        self.assertEqual([self.find(d, "env_%d" % i).isChecked() for i in range(8)][:2], [True, False])
        self.assertEqual(self.U.collect(d), shown._replace(environment=self.U.collect(d).environment), "ID2-RED: the window does not round-trip the values")

    def test_opening_alone_saves_nothing(self):
        self.make()
        self.assertFalse(os.path.exists(self.path), "ID2-RED: opening created the file")
        self.assertFalse(os.path.exists(os.path.dirname(self.path)))

    # ---------------------------------------------------------------- the dependency (the shared state function)
    def test_speed_limit_dependency(self):
        d = self.make()
        env = lambda i: self.find(d, "env_%d" % i)
        env(3).setChecked(False)                                  # limit OFF -> advance OFF
        self.assertEqual((env(3).isChecked(), env(4).isChecked()), (False, False), "ID2-RED: limit OFF did not turn the advance OFF")
        env(3).setChecked(True)                                   # limit ON does not turn the advance ON
        self.assertEqual((env(3).isChecked(), env(4).isChecked()), (True, False))
        env(4).setChecked(True)                                   # advance ON -> limit ON
        self.assertEqual((env(3).isChecked(), env(4).isChecked()), (True, True))
        env(4).setChecked(False)                                  # advance OFF keeps the limit ON
        self.assertEqual((env(3).isChecked(), env(4).isChecked()), (True, False))
        env(3).setChecked(False)
        env(4).setChecked(True)                                   # (OFF, ON) -> limit turns ON
        self.assertEqual((env(3).isChecked(), env(4).isChecked()), (True, True))

    def test_the_dependency_uses_the_shared_functions(self):
        src = open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, "initial_defaults_ui.py")) else ""
        self.assertIn("set_speed_limit_advance", src, "ID2-RED: the window does not use the shared state function")
        self.assertIn("set_speed_limit(", src)

    # ---------------------------------------------------------------- the safety intervention
    def test_the_safety_intervention_cannot_be_turned_on(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        d = self.make()
        d.show()
        box = self.find(d, "pen_safety")
        self.assertFalse(box.isChecked())
        box.setChecked(True)
        self.assertFalse(box.isChecked(), "ID2-RED: setChecked(True) turned the safety intervention ON")
        box.click()
        self.assertFalse(box.isChecked(), "ID2-RED: a click turned it ON")
        box.setFocus()
        QTest.keyClick(box, Qt.Key.Key_Space)
        self.assertFalse(box.isChecked(), "ID2-RED: the space key turned it ON")
        box.toggle()
        self.assertFalse(box.isChecked())
        self.assertFalse(box.isEnabled(), "the safety intervention checkbox is disabled (greyed by the Qt standard style): Owner contract 2026-11-10")

    def test_a_saved_true_never_shows_the_safety_intervention_on(self):
        d = self.make(self.builtin_with_safety_true())
        self.assertFalse(self.find(d, "pen_safety").isChecked())

    def builtin_with_safety_true(self):
        b = self.D.builtin_defaults()
        return b._replace(penalties=b.penalties._replace(safety_intervention=True))

    # ---------------------------------------------------------------- the initial / release brake and the A boundary
    def test_the_initial_release_brake_is_on1_or_off_only(self):
        d = self.make()
        box = self.find(d, "pen_init")
        self.assertFalse(box.isChecked())
        box.setChecked(True)
        self.assertEqual(self.U.collect(d).penalties.initial_release_brake, "on1")
        box.setChecked(False)
        self.assertEqual(self.U.collect(d).penalties.initial_release_brake, "off")
        self.assertNotIn("②", "\n".join(self.texts(d)))

    def test_the_a_boundary_spin_is_50_to_90(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        self.assertEqual((spin.minimum(), spin.maximum()), (50, 90))
        spin.setValue(49)
        self.assertEqual(spin.value(), 50)
        spin.setValue(91)
        self.assertEqual(spin.value(), 90)
        spin.setValue(75)
        self.assertEqual(self.U.collect(d).a_rank_percent, 75)

    # ---------------------------------------------------------------- OK / x
    def test_ok_saves_atomically_and_closes(self):
        d = self.make()
        d.show()
        self.find(d, "env_6").setChecked(False)
        self.find(d, "timing").setChecked(True)
        self.find(d, "pen_rolling").setChecked(False)
        self.find(d, "pen_init").setChecked(True)
        self.find(d, "a_rank").setValue(80)
        self.find(d, "ok").click()
        raw = json.load(open(self.path, encoding="utf-8"))
        self.assertEqual((raw["environment"]["handle_reverser"], raw["timing_stations"]["all_changeable_non_timed_to_timed"], raw["penalties"]["rolling"], raw["penalties"]["initial_release_brake"], raw["a_rank_percent"]),
                         (False, True, False, "on1", 80), "ID2-RED: OK did not save the values")
        self.assertIs(raw["penalties"]["safety_intervention"], False)
        self.assertFalse(d.isVisible(), "ID2-RED: the window did not close after a successful save")
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["initial-defaults.json"])

    def test_the_close_button_saves_nothing(self):
        self.D.save(self.D.builtin_defaults(), self.path)
        before = open(self.path, "rb").read()
        d = self.make()
        d.show()
        self.find(d, "a_rank").setValue(90)
        self.find(d, "env_0").setChecked(False)
        d.close()
        self.assertEqual(open(self.path, "rb").read(), before, "ID2-RED: the x button saved")

    def test_escape_saves_nothing(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        d = self.make()
        d.show()
        self.find(d, "a_rank").setValue(90)
        QTest.keyClick(d, Qt.Key.Key_Escape)
        self.assertFalse(os.path.exists(self.path), "ID2-RED: Escape saved")

    def test_a_failed_save_keeps_the_window_the_old_file_and_shows_a_short_message(self):
        self.D.save(self.D.builtin_defaults(), self.path)
        before = open(self.path, "rb").read()

        def failing(value):
            raise self.D.SaveError("disk full " + "x" * 400)
        d = self.make(save=failing)
        d.show()
        self.find(d, "a_rank").setValue(90)
        self.find(d, "ok").click()
        self.assertTrue(d.isVisible(), "ID2-RED: the window closed after a failed save")
        self.assertEqual(open(self.path, "rb").read(), before)
        msg = self.find(d, "message")
        self.assertTrue(msg.text(), "ID2-RED: the failure is not shown")
        self.assertLess(len(msg.text()), 80, "the message must be short (no raw error text)")
        self.assertNotIn("xxx", msg.text())

    def test_ok_never_saves_a_value_the_model_refuses(self):
        saved = []
        d = self.make(save=lambda v: saved.append(v))
        d.show()
        self.find(d, "ok").click()
        self.assertEqual(len(saved), 1)
        self.assertTrue(self.D.a_rank_percent_valid(saved[0].a_rank_percent))
        self.assertFalse(saved[0].penalties.safety_intervention)

    # ---------------------------------------------------------------- the process entry
    def test_run_loads_shows_and_returns_zero(self):
        shown = {}

        class FakeInstance:
            def acquire(self):
                return True

            def release(self):
                shown["released"] = True

        def exec_fn(dialog):
            shown["title"] = dialog.windowTitle()
            return 0
        self.D.save(self.D.builtin_defaults()._replace(a_rank_percent=77), self.path)
        def exec_fn(dialog):
            shown["title"] = dialog.windowTitle()
            shown["a"] = self.find(dialog, "a_rank").value()
            return 0
        code = self.U.run(["main.py", "--initial-defaults"], defaults_path=self.path, instance=FakeInstance(), exec_fn=exec_fn)
        self.assertEqual(code, 0)
        self.assertEqual(shown["a"], 77, "ID2-RED: the window did not load the saved file")
        self.assertEqual(shown["title"], "初期値設定")
        self.assertTrue(shown.get("released"))

    def test_a_second_instance_exits_at_once_without_a_window(self):
        calls = []

        class Busy:
            def acquire(self):
                return False

            def release(self):
                calls.append("release")
        code = self.U.run(["main.py", "--initial-defaults"], defaults_path=self.path, instance=Busy(), exec_fn=lambda d: calls.append("window"))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [], "ID2-RED: a second window was opened")

    def test_the_real_named_mutex_allows_one_holder(self):
        a, b = self.U.SingleInstance(), self.U.SingleInstance()
        self.assertTrue(a.acquire())
        try:
            self.assertFalse(b.acquire(), "ID2-RED: a second holder was allowed")
        finally:
            a.release()
        c = self.U.SingleInstance()
        self.assertTrue(c.acquire(), "ID2-RED: the mutex was not released")
        c.release()

    def test_other_arguments_with_the_flag_are_refused(self):
        for argv in (["main.py", "--initial-defaults", "--managed"], ["main.py", "--initial-defaults", "x"], ["main.py", "--managed", "--initial-defaults", "--owner", "caller"]):
            self.assertEqual(self.U.run(argv, defaults_path=self.path, instance=None, exec_fn=lambda d: self.fail("opened")), 2, "ID2-RED: %r" % (argv,))

    def test_a_damaged_file_opens_with_the_builtin_values(self):
        os.makedirs(os.path.dirname(self.path))
        open(self.path, "wb").write(b"{broken")
        got = {}
        self.U.run(["main.py", "--initial-defaults"], defaults_path=self.path, instance=None, exec_fn=lambda d: got.setdefault("a", self.find(d, "a_rank").value()) and 0)
        self.assertEqual(got["a"], 60)
        self.assertEqual(open(self.path, "rb").read(), b"{broken", "ID2-RED: opening rewrote the damaged file")


class Entry(unittest.TestCase):
    def test_main_routes_the_flag_to_the_window_and_not_to_managed_or_normal(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import main
        ui = ui_module()
        got = []
        saved = (ui.run, main.run_managed, main._run_normal)
        ui.run = lambda argv, **kw: got.append(("ui", list(argv))) or 7
        main.run_managed = lambda argv, **kw: got.append(("managed",)) or 8
        main._run_normal = lambda: got.append(("normal",)) or 9
        try:
            self.assertEqual(main.main(["main.py", "--initial-defaults"]), 7)
            self.assertEqual(main.main(["main.py", "--managed", "--owner", "caller", "--bve-pid", "1", "--instance", "a" * 16]), 8)
            self.assertEqual(main.main(["main.py"]), 9)
            self.assertEqual(main.main(["main.py", "--managed", "--initial-defaults", "--owner", "caller", "--bve-pid", "1", "--instance", "a" * 16]), 7, "ID2-RED: the flag must win (and be refused by the window) before the managed mode is looked at")
        finally:
            ui.run, main.run_managed, main._run_normal = saved
        self.assertEqual(got[0], ("ui", ["main.py", "--initial-defaults"]))

    def test_the_window_module_never_imports_the_overlay_or_the_managed_mode(self):
        src = open(os.path.join(ROOT, "initial_defaults_ui.py"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, "initial_defaults_ui.py")) else ""
        self.assertTrue(src, "ID2-RED: the module does not exist")
        for bad in ("import main", "from main", "managed_mode", "menu_ui", "scoring_logic"):
            self.assertNotIn(bad, src, "ID2-RED: the window module must not import %r" % bad)

    def test_no_public_dll_name_in_the_python_sources(self):
        import re
        for name in ("initial_defaults.py", "initial_defaults_ui.py"):
            p = os.path.join(ROOT, name)
            src = open(p, encoding="utf-8").read() if os.path.exists(p) else None
            self.assertIsNotNone(src, "ID2-RED: %s does not exist" % name)
            self.assertIsNone(re.search(r"TSScoringPlugin|TsScoringPlugin|\.dll\b|InputDevice\.dll", src, re.I), "ID2-RED: %s names a DLL" % name)


if __name__ == "__main__":
    unittest.main()
