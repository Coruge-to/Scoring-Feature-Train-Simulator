"""INITIAL-DEFAULTS Commit 6 (test only; Owner ruling 2026-11-10, C2U21): the path the window LOADS from is the path OK SAVES to (persistence path consistency)."""
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
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-initdef-path-")
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


def tree(root):
    out = set()
    for d, _, files in os.walk(root):
        for f in files:
            out.add(os.path.join(d, f))
    return out


class SavePath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["initdef-path"])
        import initial_defaults_ui
        import initial_defaults
        cls.U, cls.D = initial_defaults_ui, initial_defaults

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="p-", dir=_TMP["dir"].name)
        self.path = os.path.join(self.dir, "A dir", "initial-defaults.json")      # an explicit test path (with a space)
        self.other = os.path.join(self.dir, "B dir", "initial-defaults.json")
        self.replaced = []
        real_save = self.D.save
        self.real_save = real_save

        def recording_save(defaults, path=None, **kw):
            def recorder(src, dst):
                self.replaced.append((src, dst))
                return os.replace(src, dst)
            return real_save(defaults, path, replace=recorder)
        self.D.save = recording_save

    def tearDown(self):
        self.D.save = self.real_save

    def run_window(self, action, path):
        def exec_fn(dialog):
            action(dialog)
            return 0
        return self.U.run(["main.py", "--initial-defaults"], defaults_path=path, instance=None, exec_fn=exec_fn)

    def box(self, dialog, name):
        from PyQt6.QtWidgets import QWidget
        return dialog.findChild(QWidget, name)

    def test_ok_saves_to_the_path_that_was_loaded_and_nowhere_else(self):
        before_root = tree(ROOT)
        before_cwd = tree(os.getcwd())
        self.run_window(lambda d: (self.box(d, "a_rank").setValue(75), self.box(d, "ok").click()), self.path)
        self.assertEqual(json.load(open(self.path, encoding="utf-8"))["a_rank_percent"], 75, "ID6-RED: OK did not save to the loaded path")
        self.assertFalse(os.path.exists(self.other), "ID6-RED: a different path was written")
        self.assertFalse(os.path.exists(self.D.defaults_path()), "ID6-RED: the default path was written while an explicit path was loaded")
        self.assertEqual(tree(ROOT), before_root, "ID6-RED: a file appeared in the repository / clone")
        self.assertEqual(tree(os.getcwd()), before_cwd, "ID6-RED: a file appeared in the working directory")
        self.assertEqual([n for n in tree(self.dir)], [self.path], "ID6-RED: exactly one file must exist after OK (no temp left)")

    def test_the_replace_target_is_the_loaded_path_and_the_temp_is_in_its_directory(self):
        self.run_window(lambda d: self.box(d, "ok").click(), self.path)
        self.assertEqual(len(self.replaced), 1, "ID6-RED: OK must replace exactly one file")
        src, dst = self.replaced[0]
        self.assertEqual(os.path.abspath(dst), os.path.abspath(self.path), "ID6-RED: os.replace target is not the loaded path")
        self.assertEqual(os.path.dirname(os.path.abspath(src)), os.path.dirname(os.path.abspath(self.path)), "ID6-RED: the temp file is not in the directory of the formal file")
        self.assertTrue(src.endswith(".tmp"))

    def test_a_second_ok_in_a_second_process_window_updates_the_same_single_file(self):
        self.run_window(lambda d: (self.box(d, "a_rank").setValue(80), self.box(d, "ok").click()), self.path)
        self.run_window(lambda d: (self.assertEqual(self.box(d, "a_rank").value(), 80), self.box(d, "a_rank").setValue(55), self.box(d, "ok").click()), self.path)
        self.assertEqual(json.load(open(self.path, encoding="utf-8"))["a_rank_percent"], 55)
        self.assertEqual(tree(self.dir), {self.path})

    def test_closing_with_the_x_button_saves_to_no_path(self):
        before = tree(_TMP["dir"].name)
        self.run_window(lambda d: (self.box(d, "a_rank").setValue(90), d.show(), d.close()), self.path)
        self.assertEqual(tree(_TMP["dir"].name), before, "ID6-RED: the x button wrote a file")
        self.assertEqual(self.replaced, [])
        self.assertFalse(os.path.exists(self.path))

    def test_the_default_path_is_the_one_formal_file_and_the_process_uses_it(self):
        expected = os.path.join(os.environ["LOCALAPPDATA"], "Coruge-to", "TS Scoring", "initial-defaults.json")
        self.assertEqual(os.path.normcase(self.D.defaults_path()), os.path.normcase(expected))
        self.run_window(lambda d: (self.box(d, "a_rank").setValue(65), self.box(d, "ok").click()), None)
        self.assertEqual(json.load(open(expected, encoding="utf-8"))["a_rank_percent"], 65, "ID6-RED: the default run did not save to the formal path")
        self.assertEqual(self.replaced[-1][1] and os.path.normcase(os.path.abspath(self.replaced[-1][1])), os.path.normcase(expected))
        os.remove(expected)

    def test_bve5_bve6_current_legacy_share_one_default_path_without_host_branching(self):
        import inspect
        src = inspect.getsource(self.D.defaults_path) + inspect.getsource(self.U.run)
        for word in ("BVE", "bve", "Legacy", "Current", "legacy", "current", "host", "HOST", "tsid", "getcwd", "workingDirectory"):
            self.assertNotIn(word, src, "ID6-RED: the path code branches on %r" % word)
        self.assertEqual(len(inspect.signature(self.D.defaults_path).parameters), 1, "only an environ argument")
        a = self.D.defaults_path({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"})
        self.assertEqual(a, os.path.join(r"C:\Users\x\AppData\Local", "Coruge-to", "TS Scoring", "initial-defaults.json"))
        self.assertEqual(self.D.defaults_path({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}), a)

    def test_the_save_never_targets_the_clone_or_the_working_directory(self):
        self.assertFalse(os.path.abspath(self.D.defaults_path()).lower().startswith(os.path.abspath(ROOT).lower() + os.sep))
        source = open(os.path.join(ROOT, "initial_defaults.py"), encoding="utf-8").read()
        self.assertEqual(re.findall(r"os\.getcwd|__file__", source), [], "ID6-RED: the model derives a path from the cwd or the module location")


if __name__ == "__main__":
    unittest.main()
