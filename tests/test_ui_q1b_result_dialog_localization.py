"""Phase UI-Q1-B: the result save dialog (managed mode: a Qt instance dialog, DontUseNativeDialog, owner = parent = Overlay) showed the standard strings of Qt in English
because nothing loaded the Qt translation that PyQt6 ships (qtbase_<lang>.qm). The product now installs it with a QTranslator that follows the locale; with no translation
it stays English; the file filters are named in Japanese like the title.

    C:\\Python314\\python.exe -B -m unittest discover -s tests -p "test_ui_q1b_result_dialog_localization.py" -v

  B1 the translator, B2 the dialog texts (isolated child processes: one translator state per process), B3 the contracts that must not change (owner / parent / modal / reject),
  B4 the sources that must not change (the normal mode's static dialog call, the file formats, no translation file in the tree)

The dialog texts are read from the real Qt objects (labels, buttons, the model's header, the name filters) in a child process with the offscreen platform.

Phase UI-Q1-A (the cursor that stays on the operation screen) is NOT part of this file: its candidate fix (a cursor of the Overlay) did not change the real behaviour and was
not implemented (see the UI-Q1 report).
"""
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def code_only(src):
    """The source without comments and docstring-like text lines is not needed here: the guards below look for tokens in the whole text on purpose."""
    return src


DIALOG_SCRIPT = r'''
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PyQt6.QtCore import QLocale, QTimer, Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton
from PyQt6.QtGui import QFileSystemModel
import gc
mode = sys.argv[2]            # "product" | "product-no-translations" | "plain"
locale_name = sys.argv[3]
app = QApplication(sys.argv[:1])
QLocale.setDefault(QLocale(locale_name))
import main as ts_main
import managed_input
overlay = ts_main.Overlay(0)
overlay.timer.stop()
seen = {}
def capture(dialog):
    seen["title"] = dialog.windowTitle()
    seen["labels"] = sorted({l.text() for l in dialog.findChildren(QLabel) if l.text()})
    seen["buttons"] = sorted({b.text() for b in dialog.findChildren(QPushButton) if b.text()})
    seen["filters"] = dialog.nameFilters()
    model = dialog.findChild(QFileSystemModel)
    seen["headers"] = [str(model.headerData(i, Qt.Orientation.Horizontal)) for i in range(4)] if model else None
    seen["non_native"] = bool(dialog.testOption(QFileDialog.Option.DontUseNativeDialog))
    seen["parent_is_overlay"] = dialog.parent() is overlay
    seen["accept_mode_save"] = dialog.acceptMode() == QFileDialog.AcceptMode.AcceptSave
    seen["class"] = type(dialog).__name__
if mode == "plain":
    dialog = QFileDialog(overlay, "x", r"C:\temp\x.jpg", "JPEG Image (*.jpg);;PNG Image (*.png)")
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.show(); app.processEvents()
    capture(dialog)
    seen["result"] = None
else:
    if mode == "product-no-translations":
        ask = managed_input.attach_result_dialog(overlay, translations_path=r"C:\ts_scoring_no_such_dir\translations")
    else:
        ask = managed_input.attach_result_dialog(overlay)
    gc.collect()
    def grab():
        capture(overlay.result_dialog)
        seen["modal_application"] = bool(overlay.result_dialog.isModal())
        overlay.close_result_dialog()
    QTimer.singleShot(300, grab)
    seen["result"] = ask(r"C:\temp\x.jpg")
    seen["dialog_cleared_after"] = getattr(overlay, "result_dialog", "missing") is None
    seen["held_translators"] = len(getattr(managed_input, "_HELD_QT_TRANSLATORS", []))
sys.stdout.buffer.write((json.dumps(seen, ensure_ascii=False) + "\n").encode("utf-8"))
'''


def dialog_texts(mode, locale_name="ja_JP"):
    out = subprocess.run([sys.executable, "-B", "-c", DIALOG_SCRIPT, ROOT, mode, locale_name], capture_output=True, timeout=120, cwd=ROOT)
    text = out.stdout.decode("utf-8", "replace").strip().splitlines()
    if out.returncode != 0 or not text:
        raise AssertionError("child process failed (%s): %s" % (out.returncode, out.stderr.decode("utf-8", "replace")[-1500:]))
    return json.loads(text[-1])


class B1_TheTranslator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, ROOT)
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_the_qt_base_translation_of_the_locale_is_installed_and_kept(self):
        from PyQt6.QtCore import QCoreApplication, QLocale
        import managed_input
        translator = managed_input.install_qt_translator(self.app, QLocale("ja_JP"))
        self.assertIsNotNone(translator)
        self.assertIn(translator, managed_input._HELD_QT_TRANSLATORS)
        self.assertEqual(QCoreApplication.translate("QFileSystemModel", "Name"), "名前")
        self.assertEqual(QCoreApplication.translate("QPlatformTheme", "Cancel"), "キャンセル")

    def test_a_missing_translation_directory_is_not_an_error(self):
        from PyQt6.QtCore import QLocale
        import managed_input
        self.assertIsNone(managed_input.install_qt_translator(self.app, QLocale("ja_JP"), r"C:\ts_scoring_no_such_dir\translations"))

    def test_no_application_is_not_an_error(self):
        import managed_input
        self.assertIsNone(managed_input.install_qt_translator(None, None, r"C:\ts_scoring_no_such_dir\translations"))


class B2_TheDialogTexts(unittest.TestCase):
    ENGLISH = {"labels": ["&Look in:", "File &name:", "Files of &type:"], "buttons": ["&Save", "Cancel"], "headers": ["Name", "Size", "Type", "Date Modified"]}

    def test_without_any_translator_the_known_english_texts_are_what_qt_shows(self):
        """Characterization of the defect (a plain Qt dialog in a process that never installs a translator)."""
        seen = dialog_texts("plain")
        self.assertEqual(seen["labels"], self.ENGLISH["labels"])
        self.assertEqual(seen["buttons"], self.ENGLISH["buttons"])
        self.assertEqual(seen["headers"], self.ENGLISH["headers"])

    def test_the_managed_dialog_is_japanese_with_the_japanese_locale(self):
        seen = dialog_texts("product", "ja_JP")
        self.assertEqual(seen["title"], "採点結果を保存")
        self.assertIn("ファイル名(&N):", seen["labels"])
        self.assertEqual(seen["buttons"], ["キャンセル", "保存"])
        self.assertEqual(seen["headers"], ["名前", "サイズ", "タイプ", "更新日"])
        # the two labels that the shipped ja catalog translates only under their OLD source strings: no English is left among the three labels
        self.assertFalse([t for t in seen["labels"] if re.search(r"[A-Za-z]{3}", t) and "(" not in t], seen["labels"])

    def test_the_jpeg_and_png_filter_texts_are_japanese_and_the_patterns_are_the_same(self):
        seen = dialog_texts("product", "ja_JP")
        self.assertEqual(seen["filters"], ["JPEG画像 (*.jpg)", "PNG画像 (*.png)"])

    def test_with_the_english_locale_the_texts_stay_english(self):
        seen = dialog_texts("product", "en_US")
        self.assertEqual(seen["labels"], self.ENGLISH["labels"])
        self.assertEqual(seen["buttons"], self.ENGLISH["buttons"])
        self.assertEqual(seen["headers"], self.ENGLISH["headers"])

    def test_a_missing_translation_directory_falls_back_to_english_without_an_error(self):
        seen = dialog_texts("product-no-translations", "ja_JP")
        self.assertEqual(seen["labels"], self.ENGLISH["labels"])
        self.assertEqual(seen["buttons"], self.ENGLISH["buttons"])
        self.assertEqual(seen["result"], "")

    def test_the_translator_outlives_the_garbage_collection(self):
        seen = dialog_texts("product", "ja_JP")                     # (the child collects garbage right after attach)
        self.assertEqual(seen["headers"], ["名前", "サイズ", "タイプ", "更新日"])
        self.assertGreaterEqual(seen["held_translators"], 1)


class B3_TheContractsThatMustNotChange(unittest.TestCase):
    def test_owner_parent_non_native_modal_and_reject(self):
        seen = dialog_texts("product", "ja_JP")
        self.assertTrue(seen["non_native"])
        self.assertTrue(seen["parent_is_overlay"])
        self.assertTrue(seen["accept_mode_save"])
        self.assertEqual(seen["class"], "QFileDialog")
        self.assertEqual(seen["result"], "")                         # Stop request / Alt+F4: reject() closes the dialog, no path
        self.assertTrue(seen["dialog_cleared_after"])


class FakeDialog(object):
    def __init__(self):
        self.calls = []

    def setLabelText(self, label, text):
        self.calls.append((label, text))


class B5_TheLimitedFallbackToTheOlderKeys(unittest.TestCase):
    """Owner decision OD-Q1-1: for the two labels that Qt 6.11 asks for under new source strings (\"&Look in:\", \"Files of &type:\"), and only for them, the OFFICIAL translation
    of the current key wins; only when there is none, the translation of the OLDER key of the same catalog is used; with none, Qt's English stays. Nothing is hard coded."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, ROOT)

    def run_helper(self, table, extra_raise=False):
        """table: {(context, source): translation}; a source that is not in the table is returned untranslated, like QCoreApplication.translate does."""
        from unittest import mock
        from PyQt6.QtCore import QCoreApplication
        from PyQt6.QtWidgets import QFileDialog
        import managed_input
        asked = []

        def fake_translate(context, source, *rest):
            asked.append((context, source))
            if extra_raise:
                raise RuntimeError("translate failed")
            return table.get((context, source), source)
        dialog = FakeDialog()
        with mock.patch.object(QCoreApplication, "translate", staticmethod(fake_translate)):
            managed_input._use_previous_label_translations(dialog)
        return dialog.calls, asked, QFileDialog.DialogLabel

    def test_the_official_translation_of_the_current_key_wins_and_the_older_key_is_not_used(self):
        calls, asked, _ = self.run_helper({("QFileDialog", "&Look in:"): "OFFICIAL-A", ("QFileDialog", "Files of &type:"): "OFFICIAL-B", ("QFileDialog", "Look in:"): "OLD-A", ("QFileDialog", "Files of type:"): "OLD-B"})
        self.assertEqual(calls, [])
        self.assertNotIn(("QFileDialog", "Look in:"), asked)
        self.assertNotIn(("QFileDialog", "Files of type:"), asked)

    def test_without_the_current_key_translation_the_older_key_translation_is_used(self):
        calls, _, labels = self.run_helper({("QFileDialog", "Look in:"): "OLD-A", ("QFileDialog", "Files of type:"): "OLD-B"})
        self.assertEqual(calls, [(labels.LookIn, "OLD-A"), (labels.FileType, "OLD-B")])

    def test_with_neither_translation_qt_english_stays(self):
        calls, _, _ = self.run_helper({})
        self.assertEqual(calls, [])

    def test_look_in_alone_is_handled_independently(self):
        calls, _, labels = self.run_helper({("QFileDialog", "Look in:"): "OLD-A", ("QFileDialog", "Files of &type:"): "OFFICIAL-B", ("QFileDialog", "Files of type:"): "OLD-B"})
        self.assertEqual(calls, [(labels.LookIn, "OLD-A")])

    def test_files_of_type_alone_is_handled_independently(self):
        calls, _, labels = self.run_helper({("QFileDialog", "&Look in:"): "OFFICIAL-A", ("QFileDialog", "Look in:"): "OLD-A", ("QFileDialog", "Files of type:"): "OLD-B"})
        self.assertEqual(calls, [(labels.FileType, "OLD-B")])

    def test_no_other_label_and_no_other_key_is_touched(self):
        everything = {("QFileDialog", "Look in:"): "OLD-A", ("QFileDialog", "Files of type:"): "OLD-B", ("QFileDialog", "File &name:"): "X1", ("QFileDialog", "File name:"): "X2",
                      ("QFileDialog", "Save"): "X3", ("QFileDialog", "Cancel"): "X4", ("QPlatformTheme", "Cancel"): "X5"}
        calls, asked, labels = self.run_helper(everything)
        self.assertEqual({c[0] for c in calls}, {labels.LookIn, labels.FileType})
        self.assertEqual(set(asked), {("QFileDialog", "&Look in:"), ("QFileDialog", "Look in:"), ("QFileDialog", "Files of &type:"), ("QFileDialog", "Files of type:")})

    def test_a_failing_translate_does_not_raise(self):
        calls, _, _ = self.run_helper({}, extra_raise=True)
        self.assertEqual(calls, [])

    def test_no_japanese_text_is_hard_coded_in_the_helpers(self):
        import inspect
        import managed_input
        for fn in (managed_input._use_previous_label_translations, managed_input.install_qt_translator):
            self.assertEqual([ch for ch in inspect.getsource(fn) if ord(ch) > 127], [], fn.__name__)

    def test_a_locale_without_a_catalog_installs_nothing(self):
        from PyQt6.QtCore import QLocale
        from PyQt6.QtWidgets import QApplication
        import managed_input
        app = QApplication.instance() or QApplication(sys.argv[:1])
        self.assertIsNone(managed_input.install_qt_translator(app, QLocale("tlh"), None))


class B6_TheLocaleIsFollowed(unittest.TestCase):
    def test_another_locale_gets_its_own_catalog_not_the_japanese_one(self):
        seen = dialog_texts("product", "de_DE")
        self.assertNotEqual(seen["buttons"], ["&Save", "Cancel"])
        self.assertFalse([t for t in seen["labels"] + seen["buttons"] + seen["headers"] if re.search(r"[぀-ヿ一-鿿]", t)])


class B4_TheSourcesThatMustNotChange(unittest.TestCase):
    def test_the_normal_modes_static_dialog_call_is_the_same_statement(self):
        main_src = read("main.py")
        self.assertIn('save_path, _ = QFileDialog.getSaveFileName(self, "採点結果を保存", default_path, "JPEG Image (*.jpg);;PNG Image (*.png)")', main_src)
        self.assertIn('fhd_pixmap.save(save_path, "JPG", 100)', main_src)
        self.assertIn('default_name = datetime.now().strftime("Result_%Y%m%d_%H%M%S.jpg")', main_src)

    def test_the_managed_dialog_keeps_the_instance_the_owner_and_the_native_option(self):
        src = read("managed_input.py")
        self.assertIn('dialog = QFileDialog(overlay, "採点結果を保存", default_path, ', src)
        self.assertIn("dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)", src)
        self.assertIn("dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)", src)
        self.assertIn("overlay.result_dialog = dialog", src)
        self.assertIn("accepted = dialog.exec()", src)
        self.assertNotIn("getSaveFileName", src)

    def test_no_translation_file_is_part_of_the_product_tree(self):
        import subprocess as sp
        tracked = sp.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True).stdout.split()
        self.assertEqual([p for p in tracked if p.lower().endswith(".qm")], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
