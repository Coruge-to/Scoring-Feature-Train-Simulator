"""INITIAL-DEFAULTS Stage F1/F2: the A boundary contract (Owner 2026-11-11, F2 confirmation). The tests assert the CONTRACT.

  edit      (window and F1) ASCII digits 0-9 only, 2 digits at most, 00..99 allowed while editing; the 3rd digit, a non-digit, '+', '-', a space, a decimal point, a full-width digit, an IME full-width input are refused;
            an ASCII paste of up to 2 digits is allowed
  window    OK with a valid 50..90: saved atomically, the window closes. OK with an out-of-range / empty field: the field goes back to 60, NOTHING is saved, the saved defaults are unchanged, the window stays open, the A boundary field has the
            focus again and a RED 「50～90の整数を入力してください。」 is shown; a second OK saves 60 and closes; a valid re-entry saves it and closes. The error is shown ONLY after such an OK (never idle / on focus).
            Clear conditions: a valid value confirmed / a preset / the window discarded / regenerated / a successful save. 保存できませんでした。 is a separate reason with the PRIORITY over the input error. The old wording and the
            retired notice never appear.
  F1        Enter: 00..49, 91..99 and a single digit are 60 SILENTLY, 50..90 is adopted, an EMPTY input is 60 as well (silently). F1 has no new row / notice / red text / guide: its drawn texts are those of an unedited page and
            the existing explanation of the A boundary stays. The saved defaults are never touched.
  F1 back   (Owner 2026-11-11, the PRE-F2 contract kept) while the A boundary is edited Backspace deletes the last typed character ONLY: the edit goes on, the page stays 3/3, nothing else changes (setting_stop_distance included; it used to be
            overwritten); an empty input stays empty (no cancel, no restore, no page change); Enter ends the edit (60 for 00..49 / 91..99 / one digit / empty); only a Backspace AFTER that Enter returns to page 2/3.

Interpretations (reported): 'confirmed' in the window = the typed value and the field left (editingFinished: Enter in the field is the default button = OK)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import idf1_red_support as X  # noqa: E402

FULLWIDTH_75 = "".join(chr(c) for c in (0xFF17, 0xFF15))
ARABIC_INDIC_50 = "".join(chr(c) for c in (0x0665, 0x0660))


def setUpModule():
    X.redirect_profile("ts-idf1-a-")


def tearDownModule():
    X.restore_profile()


def _generate(cls, prefix, values, body):
    """One test method per value (a failing value is one failure of its own)."""
    for typed, effective in values:
        name = "test_%s_%s" % (prefix, ("empty" if typed == "" else "v" + typed))

        def make(t=typed, e=effective):
            return lambda self: body(self, t, e)
        setattr(cls, name, make())


# ================================================================================================================ edit contract (the 'initial defaults' window: QSpinBox)
class DialogEdit(X.DialogBase):
    def paste(self, d, text):
        from PyQt6.QtGui import QGuiApplication
        spin = self.spin(d)
        le = spin.lineEdit()
        spin.setFocus()
        le.selectAll()
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        QTest.keyClick(le, Qt.Key.Key_Delete)
        QGuiApplication.clipboard().setText(text)
        le.paste()
        self.app_events()
        return le.text()

    def ime_commit(self, d, text):
        from PyQt6.QtGui import QGuiApplication, QInputMethodEvent
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        spin = self.spin(d)
        le = spin.lineEdit()
        spin.setFocus()
        le.selectAll()
        QTest.keyClick(le, Qt.Key.Key_Delete)
        event = QInputMethodEvent()
        event.setCommitString(text)
        QGuiApplication.sendEvent(le, event)
        self.app_events()
        return le.text()

    def test_a_third_digit_is_not_enterable(self):
        d = self.make()
        self.assertEqual(self.type_into_spin(d, "100"), "10", "IDF1-RED: a third digit was accepted")

    def test_non_digits_are_not_enterable(self):
        d = self.make()
        for typed, shown in (("a", ""), ("5a", "5"), ("-5", "5"), ("+5", "5"), (" 5", "5"), ("5 ", "5"), ("5.", "5"), ("5-", "5"), ("+", ""), (" ", ""), (".", "")):
            self.assertEqual(self.type_into_spin(d, typed), shown, "IDF1-RED: typing %r left %r in the field" % (typed, self.type_into_spin(d, typed)))

    def test_an_ascii_paste_of_up_to_two_digits_is_allowed(self):
        d = self.make()
        for pasted in ("75", "91", "99", "00", "49", "5", "9"):
            self.assertEqual(self.paste(d, pasted), pasted, "IDF1-RED: the ASCII paste %r was refused or changed" % pasted)

    def test_other_pastes_are_refused(self):
        d = self.make()
        for pasted in ("123", " 75 ", "+5", "-5", "7a", "5.5", FULLWIDTH_75, ARABIC_INDIC_50):
            shown = self.paste(d, pasted)
            self.assertEqual(shown, "", "IDF1-RED: the paste %r left %r in the field" % (pasted, shown))

    def test_an_ime_commit_of_ascii_digits_is_allowed_and_a_full_width_one_is_refused(self):
        d = self.make()
        self.assertEqual(self.ime_commit(d, "75"), "75", "IDF1-RED: an IME commit of ASCII digits was refused")
        self.assertEqual(self.ime_commit(d, "91"), "91", "IDF1-RED: an IME commit of 91 was refused")
        for committed in (FULLWIDTH_75, ARABIC_INDIC_50, "123", "+5"):
            self.assertEqual(self.ime_commit(d, committed), "", "IDF1-RED: the IME commit %r left text in the field" % committed)

    def test_direct_set_text_of_a_refused_text_is_corrected_at_ok(self):
        """setText bypasses the key validator: the OK still refuses every such text (nothing is saved, the field is 60, the error is shown)."""
        for text in (FULLWIDTH_75, ARABIC_INDIC_50, "+5", "-5", " 75 ", "7 5", "5.", "123", "007", "075", "050", "090", "a1"):
            with self.subTest(text=text):
                self.saves = []
                d = self.make()
                self.set_spin_text(d, text)
                self.press_ok(d)
                self.assertEqual(self.saves, [], "IDF1-RED: the OK saved the refused text %r" % text)
                self.assertEqual(self.shown_text(d), "60", "IDF1-RED: the field is %r after the OK on %r" % (self.shown_text(d), text))
                self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: no input error for %r" % text)
                self.assertTrue(self.is_open(d))


def _edit_body(self, typed, effective):
    d = self.make()
    shown = self.type_into_spin(d, typed)
    self.assertEqual(shown, typed, "IDF1-RED: typing %r leaves %r in the field; every 2-digit value 00..99 is allowed while editing" % (typed, shown))


_generate(DialogEdit, "two_digits_are_editable", X.A_TABLE + X.A_EXTRA_CORRECTED + X.ONE_DIGIT, _edit_body)


# ================================================================================================================ commit contract: the 'initial defaults' window (OK)
class DialogCommit(X.DialogBase):
    def test_a_valid_value_is_saved_atomically_and_closes(self):
        for typed in X.A_VALID_TEXTS:
            with self.subTest(typed=typed):
                self.saves = []
                d = self.make(save=self.real_save)
                self.set_spin_text(d, typed)
                self.press_ok(d)
                self.assertEqual(len(self.saves), 1, "IDF1-GUARD: a valid %s was not saved exactly once" % typed)
                self.assertEqual(self.D.load(self.path).defaults.a_rank_percent, int(typed), "IDF1-GUARD: the saved file does not hold %s" % typed)
                self.assertEqual(self.message(d), "", "IDF1-GUARD: a valid value shows a message")
                self.assertFalse(self.is_open(d), "IDF1-GUARD: a valid value did not close the window")

    def test_the_saved_file_is_written_by_the_atomic_save_only(self):
        d = self.make(save=self.real_save)
        self.set_spin_text(d, "70")
        self.press_ok(d)
        left = [n for n in os.listdir(os.path.dirname(self.path)) if n != os.path.basename(self.path)]
        self.assertEqual(left, [], "IDF1-GUARD: a temporary file was left beside the saved defaults")

    def test_a_valid_re_entry_after_the_error_is_saved_and_closes(self):
        d = self.make(save=self.real_save)
        self.set_spin_text(d, "49")
        self.press_ok(d)
        self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: precondition - the input error is not shown")
        self.type_into_spin(d, "75")
        self.press_ok(d)
        self.assertEqual(self.D.load(self.path).defaults.a_rank_percent, 75, "IDF1-RED: the valid re-entry was not saved")
        self.assertFalse(self.is_open(d), "IDF1-RED: the valid re-entry did not close the window")
        self.assertEqual(self.message(d), "", "IDF1-RED: the error stayed after a successful save")

    def test_the_input_error_is_red(self):
        d = self.make()
        self.set_spin_text(d, "49")
        self.press_ok(d)
        sheet = self.find(d, "message").styleSheet()
        r, g, b = self.C.COLOR_B_EMG[:3]
        self.assertIn("color: rgb(%d, %d, %d)" % (r, g, b), sheet, "IDF1-GUARD: the message is not drawn in the red of the application")
        self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: precondition - the input error is not shown")

    def test_the_wording_is_exactly_the_owner_text(self):
        self.assertEqual(self.U.A_RANK_INVALID, X.A_ERROR_MESSAGE, "IDF1-RED: the input error wording")
        self.assertEqual(self.U.SAVE_FAILED, X.SAVE_FAILED_MESSAGE, "IDF1-GUARD: the save failure wording")
        self.assertEqual([hex(ord(c)) for c in self.U.A_RANK_INVALID[2:3]], ["0xff5e"], "IDF1-GUARD: the range sign is the full-width tilde of the F1 explanation")

    def test_the_old_wording_and_the_retired_notice_are_nowhere(self):
        text = X.source("initial_defaults_ui.py")
        for bad in (X.OLD_A_ERROR_MESSAGE, X.RETIRED_NOTICE, "整数で入力"):
            self.assertNotIn(bad, text, "IDF1-RED: %r is still in initial_defaults_ui.py" % bad)
        d = self.make()
        for typed in ("49", "", "91"):
            self.set_spin_text(d, typed)
            self.press_ok(d)
            joined = "\n".join([w.text() for w in d.findChildren(self.U.QLabel)] + [self.message(d)])
            for bad in (X.OLD_A_ERROR_MESSAGE, X.RETIRED_NOTICE):
                self.assertNotIn(bad, joined, "IDF1-RED: %r is shown after OK with %r" % (bad, typed))


def _first_ok_body(self, typed, effective):
    before = X.file_snapshot(self.path)
    d = self.make(save=self.real_save)
    self.set_spin_text(d, typed)
    self.press_ok(d)
    self.assertEqual(self.shown_text(d), "60", "IDF1-RED: after OK with %r the field does not show 60 (shows %r)" % (typed, self.shown_text(d)))
    self.assertEqual(self.spin(d).value(), 60, "IDF1-RED: the spin value is not 60")
    self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: OK with %r did not show the input error (message %r)" % (typed, self.message(d)))
    self.assertEqual(self.saves, [], "IDF1-RED: the correcting OK saved")
    self.assertTrue(self.is_open(d), "IDF1-RED: the correcting OK closed the window")
    self.assertEqual(X.file_snapshot(self.path), before, "IDF1-RED: the correcting OK changed the saved defaults")
    self.assertIn(d.focusWidget(), (self.spin(d), self.spin(d).lineEdit()), "IDF1-RED: the focus did not return to the A boundary field")


def _second_ok_body(self, typed, effective):
    d = self.make(save=self.real_save)
    self.set_spin_text(d, typed)
    self.press_ok(d)
    self.assertEqual(self.saves, [], "IDF1-RED: the first (correcting) OK with %r saved" % typed)
    self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: precondition - the input error is not shown")
    self.press_ok(d)
    self.assertEqual(len(self.saves), 1, "IDF1-RED: the second OK did not save exactly once")
    self.assertEqual(self.D.load(self.path).defaults.a_rank_percent, 60, "IDF1-RED: the second OK did not save 60")
    self.assertFalse(self.is_open(d), "IDF1-RED: the second OK did not close the window")
    self.assertEqual(self.message(d), "", "IDF1-RED: the input error stayed after the successful save")


_CORRECTED = tuple((t, 60) for t in X.A_CORRECTED_TEXTS) + (("", 60),) + tuple(X.ONE_DIGIT)
_generate(DialogCommit, "first_ok_corrects_to_60_without_saving", _CORRECTED, _first_ok_body)
_generate(DialogCommit, "second_ok_saves_60_and_closes", _CORRECTED, _second_ok_body)


class DialogMessageStates(X.DialogBase):
    """Two different reasons: the input error (cleared by 5 conditions) and the save failure (priority); never one internal reason."""

    def corrected(self, text="49", save=None):
        d = self.make(save=save or self.record_save)
        self.set_spin_text(d, text)
        self.press_ok(d)
        return d

    def need_error(self, d):
        self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: precondition - the input error is not shown (message %r)" % self.message(d))

    # ---- never idle
    def test_nothing_is_shown_idle_or_on_focus_or_while_typing(self):
        d = self.make()
        self.assertEqual(self.message(d), "", "IDF1-GUARD: a message is shown idle")
        self.spin(d).setFocus()
        self.app_events()
        self.assertEqual(self.message(d), "", "IDF1-GUARD: a guide is shown on focus")
        self.type_into_spin(d, "4")
        self.assertEqual(self.message(d), "", "IDF1-GUARD: a guide is shown while typing")
        self.type_into_spin(d, "49")
        self.find(d, "pen_rolling").setFocus()
        self.app_events()
        self.assertEqual(self.message(d), "", "IDF1-GUARD: leaving the field with 49 shows the error (it appears only at OK)")

    # ---- the two states are different
    def test_save_failure_shows_the_save_failed_message_only(self):
        self.fail_save = True
        d = self.make()
        self.set_spin_text(d, "70")
        self.press_ok(d)
        self.assertEqual(self.message(d), X.SAVE_FAILED_MESSAGE, "IDF1-GUARD: a failed save does not show 保存できませんでした。")
        self.assertTrue(self.is_open(d), "IDF1-GUARD: a failed save closed the window")
        self.assertEqual(self.shown_text(d), "70", "IDF1-GUARD: a failed save changed the shown value")

    def test_the_input_error_is_not_the_save_failed_message(self):
        d = self.corrected("49")
        self.need_error(d)
        self.assertNotEqual(self.message(d), X.SAVE_FAILED_MESSAGE)

    def test_the_save_failure_has_the_priority_over_the_input_error(self):
        d = self.corrected("49")
        self.need_error(d)
        self.fail_save = True
        self.press_ok(d)                                              # the field is 60 (valid): the save fails while the input error is still pending
        self.assertEqual(self.message(d), X.SAVE_FAILED_MESSAGE, "IDF1-RED: the failure of the 60 save does not win over the input error")
        self.assertTrue(self.is_open(d), "IDF1-RED: the failed save closed the window")

    def test_a_save_failure_then_a_success_clears_everything(self):
        d = self.corrected("49")
        self.fail_save = True
        self.press_ok(d)
        self.fail_save = False
        self.press_ok(d)
        self.assertFalse(self.is_open(d), "IDF1-RED: the retry did not save and close")
        self.assertEqual(self.message(d), "", "IDF1-RED: a message stayed after the successful save")

    def test_the_input_error_is_not_shown_by_a_save_failure_of_a_valid_value(self):
        self.fail_save = True
        d = self.make()
        self.set_spin_text(d, "75")
        self.press_ok(d)
        self.assertNotEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-GUARD: a valid value that failed to save shows the input error")

    # ---- the clear conditions of the input error (each its own test)
    def test_clear_1_a_valid_50_to_90_confirmed(self):
        d = self.corrected("49")
        self.need_error(d)
        self.type_into_spin(d, "75")
        self.find(d, "pen_rolling").setFocus()
        self.app_events()
        self.assertEqual(self.message(d), "", "IDF1-RED: a confirmed valid value did not clear the error")

    def test_clear_1b_an_invalid_value_left_does_not_clear_the_error(self):
        d = self.corrected("49")
        self.need_error(d)
        self.type_into_spin(d, "4")
        self.find(d, "pen_rolling").setFocus()
        self.app_events()
        self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: an invalid value left cleared the error (or the error was never shown)")

    def test_clear_2_a_preset_pressed(self):
        for key in ("preset_beginner", "preset_intermediate", "preset_advanced"):
            with self.subTest(preset=key):
                d = self.corrected("49")
                self.need_error(d)
                self.find(d, key).click()
                self.app_events()
                self.assertEqual(self.message(d), "", "IDF1-RED: %s did not clear the error" % key)
                self.assertEqual(self.shown_text(d), str(self.D.PRESETS[key.replace("preset_", "")][1]), "IDF1-RED: the field does not show the preset value after %s" % key)

    def test_clear_3_the_window_is_discarded(self):
        d = self.corrected("49")
        self.need_error(d)
        d.reject()
        self.app_events()
        again = self.make()
        self.assertEqual(self.message(again), "", "IDF1-RED: a window opened after a discard shows a message")

    def test_clear_4b_a_save_failure_of_one_window_does_not_leak_into_a_regenerated_window(self):
        """The reasons belong to ONE window: after a failed save a new window, in which a valid value is typed and confirmed, shows nothing."""
        self.fail_save = True
        first = self.make()
        self.set_spin_text(first, "75")
        self.press_ok(first)
        self.assertEqual(self.message(first), X.SAVE_FAILED_MESSAGE, "IDF1-GUARD: precondition - the save failure is not shown")
        self.fail_save = False
        second = self.make()
        self.type_into_spin(second, "75")
        self.find(second, "pen_rolling").setFocus()
        self.app_events()
        self.assertEqual(self.message(second), "", "IDF1-RED: a regenerated window shows the message of the previous one (%r)" % self.message(second))

    def test_nothing_is_shown_while_a_valid_value_is_being_saved(self):
        """At the moment the save is called the window shows no message (an idle window carries no error)."""
        seen = []
        d = self.make(save=lambda value: seen.append(self.message(d)))
        self.set_spin_text(d, "75")
        self.press_ok(d)
        self.assertEqual(seen, [""], "IDF1-RED: the window showed %r while the valid value was saved" % seen)

    def test_a_typed_unconfirmed_value_is_replaced_by_the_preset_value(self):
        for key, percent in (("preset_beginner", 50), ("preset_intermediate", 60), ("preset_advanced", 70)):
            with self.subTest(preset=key):
                d = self.make()
                self.type_into_spin(d, "49")
                self.find(d, key).click()
                self.app_events()
                self.assertEqual(self.shown_text(d), str(percent), "IDF1-RED: the field shows %r after %s (typed 49 before)" % (self.shown_text(d), key))
    def test_clear_4_the_window_is_regenerated(self):
        first = self.corrected("49")
        self.need_error(first)
        second = self.make()
        self.assertEqual(self.message(second), "", "IDF1-RED: a regenerated window shows a message")

    def test_clear_5_a_successful_save(self):
        d = self.corrected("49")
        self.need_error(d)
        self.press_ok(d)
        self.assertEqual(self.message(d), "", "IDF1-RED: the error stayed after the successful save")
        self.assertFalse(self.is_open(d))

    # ---- layout
    def test_a_message_does_not_change_the_layout(self):
        for kind in ("input_error", "save_failed"):
            with self.subTest(kind=kind):
                self.fail_save = kind == "save_failed"
                d = self.make()
                before = (d.size().width(), d.size().height(), self.find(d, "ok").geometry().getRect(), self.find(d, "message").geometry().getRect())
                self.set_spin_text(d, "49" if kind == "input_error" else "75")
                self.press_ok(d)
                self.assertNotEqual(self.message(d), "", "IDF1-RED: precondition - the message is not shown")
                after = (d.size().width(), d.size().height(), self.find(d, "ok").geometry().getRect(), self.find(d, "message").geometry().getRect())
                self.assertEqual(after, before, "IDF1-RED: showing the %s changed the window layout" % kind)

    def test_the_reserved_message_width_includes_both_messages(self):
        d = self.make()
        message = self.find(d, "message")
        for text in (X.A_ERROR_MESSAGE, X.SAVE_FAILED_MESSAGE):
            need = message.fontMetrics().horizontalAdvance(text)
            self.assertGreaterEqual(message.minimumWidth(), need, "IDF1-GUARD: the reserved message width (%d) does not cover %r (%d)" % (message.minimumWidth(), text, need))


class DialogRealInteraction(X.DialogBase):
    """What the user really does: Qt writes the last valid value back into an out-of-range / empty field when the field is left or Enter is pressed; the OK must still see the typed text (at HEAD a real mouse click or Enter saved 60 silently)."""

    def attempt(self, typed, how):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        self.saves = []
        d = self.make(save=self.real_save)
        spin = self.spin(d)
        self.type_into_spin(d, typed)
        if how == "mouse_ok":
            QTest.mouseClick(self.find(d, "ok"), Qt.MouseButton.LeftButton)
        elif how == "enter":
            QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
        elif how == "tab_then_ok":
            self.find(d, "pen_rolling").setFocus()
            self.app_events()
            self.press_ok(d)
        self.app_events()
        return d

    def test_an_out_of_range_or_empty_field_is_refused_by_a_real_click_enter_and_tab(self):
        for typed in ("49", "40", "91", "99", "00", "5", ""):
            for how in ("mouse_ok", "enter", "tab_then_ok"):
                with self.subTest(typed=typed, how=how):
                    d = self.attempt(typed, how)
                    self.assertEqual(self.saves, [], "IDF1-RED: %r then %s saved" % (typed, how))
                    self.assertEqual(self.message(d), X.A_ERROR_MESSAGE, "IDF1-RED: %r then %s did not show the input error" % (typed, how))
                    self.assertEqual(self.shown_text(d), "60", "IDF1-RED: the field after %r then %s" % (typed, how))
                    self.assertTrue(self.is_open(d), "IDF1-RED: %r then %s closed the window" % (typed, how))

    def test_a_valid_value_is_saved_by_a_real_click_and_enter(self):
        for typed in ("50", "75", "90"):
            for how in ("mouse_ok", "enter"):
                with self.subTest(typed=typed, how=how):
                    d = self.attempt(typed, how)
                    self.assertEqual(self.D.load(self.path).defaults.a_rank_percent, int(typed), "IDF1-GUARD: %r then %s did not save the value" % (typed, how))
                    self.assertFalse(self.is_open(d), "IDF1-GUARD: %r then %s did not close" % (typed, how))

    def test_leaving_the_field_with_an_unfinished_value_keeps_what_was_typed(self):
        d = self.make()
        self.type_into_spin(d, "4")
        self.find(d, "pen_rolling").setFocus()
        self.app_events()
        self.assertEqual(self.shown_text(d), "4", "IDF1-RED: Qt wrote 60 over the typed text when the field was left")
        self.assertEqual(self.message(d), "", "IDF1-GUARD: leaving the field shows the error (it appears only at OK)")

# ================================================================================================================ commit contract: F1 (Enter)
class F1Commit(X.LinkBase):
    def start(self, saved_a=80):
        self.write_saved(self.base(a=saved_a))
        self.new_scenario()
        self.assertEqual(self.o.rank_a_ratio, round(saved_a / 100.0, 2), "IDF1-HARNESS: the scenario did not start from the saved A boundary")
        self.o.setting_stop_distance = 100
        self.o.bve_train_length = 20.0
        self.snapshot = X.file_snapshot(self.path)

    def test_the_input_takes_two_digits_at_most(self):
        self.start()
        X.f1_start_edit(self.o)
        X.f1_type(self.o, "100")
        self.assertEqual(self.o.input_buffer, "10", "IDF1-GUARD: F1 accepted a third digit")

    def test_only_ascii_digits_enter_the_input(self):
        self.start()
        X.f1_start_edit(self.o)
        X.f1_type(self.o, "7")
        for ch in ("+", "-", " ", ".", "a", chr(0xFF15), chr(0x0665), "", "55"):
            self.o.apply_numeric_char(ch)
            self.assertEqual(self.o.input_buffer, "7", "IDF1-RED: F1 accepted %r into the numeric input" % ch)

    def test_the_typed_text_is_shown_while_editing(self):
        self.start()
        X.f1_start_edit(self.o)
        X.f1_type(self.o, "7")
        texts, _ = X.render_f1(self.o, 10)
        self.assertIn("7%", X.drawn(texts), "IDF1-GUARD: the typed digit is not shown on F1 page 3/3")

    def test_an_empty_enter_is_60_silently(self):
        """Enter (start) + Enter (confirm) without typing: the empty input is 60 (Owner 2026-11-11), whatever the A boundary was; the edit ends, the page stays 3/3."""
        for saved in (80, 60, 50, 90):
            with self.subTest(saved=saved):
                self.start(saved_a=saved)
                X.f1_start_edit(self.o)
                X.f1_commit(self.o)
                self.assertEqual(self.o.rank_a_ratio, 0.6, "IDF1-RED: an empty F1 commit gave %.2f; the contract: 60" % self.o.rank_a_ratio)
                self.assertFalse(self.o.input_mode_active, "IDF1-GUARD: the edit did not end")
                self.assertEqual(self.o.menu_state, 10, "IDF1-GUARD: the page changed")
                self.assertEqual(self.o.setting_stop_distance, 100)
                self.assert_file_untouched(self.snapshot, "an empty F1 Enter")

    def test_the_buffer_is_empty_at_the_start_of_the_edit(self):
        self.start()
        X.f1_start_edit(self.o)
        self.assertEqual(self.o.input_buffer, "", "IDF1-GUARD: the buffer is not empty at the start of the edit")


def _f1_commit_body(self, typed, effective):
    self.start(saved_a=80)
    X.f1_edit_and_commit(self.o, typed)
    self.assertEqual(self.o.rank_a_ratio, round(effective / 100.0, 2), "IDF1-RED: F1 Enter with %r applies %.2f; the contract: %d%%" % (typed, self.o.rank_a_ratio, effective))
    self.assertFalse(self.o.input_mode_active, "IDF1-GUARD: the edit did not end at Enter")
    self.assert_file_untouched(self.snapshot, "an F1 Enter with %r" % typed)
    self.assertEqual(self.o.setting_stop_distance, 100, "IDF1-GUARD: an F1 A boundary Enter changed the stop distance")


def _f1_silent_body(self, typed, effective):
    """No new display: after the commit the page is drawn exactly like an unedited page showing the same value; no message text of any kind."""
    self.start(saved_a=60)
    self.o.show_help = False
    reference = X.render_f1(self.o, 10, menu_cursor=0, input_mode_active=False)
    self.o.rank_a_ratio = 0.8                                          # the value from before the edit (an unedited page of it is drawn the same way as the reference after the commit)
    X.f1_edit_and_commit(self.o, typed)
    result = X.render_f1(self.o, 10, menu_cursor=0)
    expected = X.render_f1(self.o, 10, menu_cursor=0, input_mode_active=False)
    self.assertEqual(result, expected, "IDF1-GUARD: the page after the commit differs from the unedited page")
    for bad in (X.RETIRED_NOTICE, X.A_ERROR_MESSAGE, X.OLD_A_ERROR_MESSAGE):
        self.assertNotIn(bad, X.drawn(result[0]), "IDF1-RED: F1 draws the message %r after the commit of %r" % (bad, typed))
    if round(effective / 100.0, 2) == 0.6:
        self.assertEqual(result, reference, "IDF1-RED: the page after the commit of %r differs from an unedited 60%% page: something new is drawn" % typed)
    self.assertIn(X.F1_DESCRIPTION, X.drawn(result[0]), "IDF1-GUARD: the existing explanation of the A boundary is gone")


_generate(F1Commit, "enter_applies", X.A_TABLE + X.A_EXTRA_CORRECTED + X.ONE_DIGIT + (("", 60),), _f1_commit_body)
_generate(F1Commit, "enter_draws_nothing_new", X.A_TABLE + X.ONE_DIGIT + (("", 60),), _f1_silent_body)


class F1Page(X.LinkBase):
    def test_the_existing_explanation_is_kept_and_no_message_is_drawn_before_any_edit(self):
        self.write_saved(self.base(a=60))
        self.scenario(5)
        texts, _ = X.render_f1(self.o, 10, menu_cursor=0)
        drawn = X.drawn(texts)
        self.assertIn(X.F1_DESCRIPTION, drawn, "IDF1-GUARD: the explanation of the A boundary changed")
        for bad in (X.RETIRED_NOTICE, X.A_ERROR_MESSAGE, X.OLD_A_ERROR_MESSAGE):
            self.assertNotIn(bad, drawn, "IDF1-GUARD: F1 draws %r" % bad)

    def test_the_f1_modules_contain_no_new_message(self):
        for name in ("menu_ui.py", "main.py"):
            text = X.source(name)
            for bad in (X.RETIRED_NOTICE, X.A_ERROR_MESSAGE, X.OLD_A_ERROR_MESSAGE):
                self.assertNotIn(bad, text, "IDF1-GUARD: %s contains %r" % (name, bad))

    def test_the_editing_page_draws_the_same_rows_as_the_idle_page(self):
        """F1 page 3/3 while editing: the only differences are the typed-value label; no extra row / red text."""
        self.write_saved(self.base(a=60))
        self.scenario(5)
        idle = X.drawn(X.render_f1(self.o, 10, menu_cursor=0, input_mode_active=False)[0])
        X.f1_start_edit(self.o)
        X.f1_type(self.o, "4")
        editing = X.drawn(X.render_f1(self.o, 10, menu_cursor=0)[0])
        extra = [t for t in editing if t not in idle]
        self.assertTrue(all("%" in t or t == "" for t in extra), "IDF1-GUARD: the editing page draws new rows: %r" % extra)


# ================================================================================================================ F1 Back (Backspace) pollution
class F1Back(X.LinkBase):
    """The Owner 2026-11-11 Backspace contract (the pre-F2 structure kept; only the misrouting into setting_stop_distance is fixed). Fixture: the A boundary is 60 before the edit, setting_stop_distance 100 (train length 20: the old
    misroute would write max(20, typed value) = 80), the input in progress is 80."""

    def start(self, a=60):
        self.write_saved(self.base(a=a))
        self.new_scenario()
        o = self.o
        o.setting_stop_distance = 100
        o.bve_train_length = 20.0
        o.pen_limit, o.pen_jerk = False, True
        o.penalty_init_rules = [{"end_idx": -1, "apply": "ON①", "release": "OFF"}]
        o.user_timing_overrides = {3: True}
        self.snapshot = X.file_snapshot(self.path)
        self.before = X.settings_state(o)
        X.f1_start_edit(o)
        X.f1_type(o, "80")

    def back(self):
        X.f1_cancel(self.o)

    def assert_editing(self, buffer, stage):
        o = self.o
        self.assertEqual(o.input_buffer, buffer, "IDF1-RED: stage %s: the input is %r, expected %r" % (stage, o.input_buffer, buffer))
        self.assertTrue(o.input_mode_active, "IDF1-RED: stage %s: the A boundary edit ended" % stage)
        self.assertEqual((o.menu_state, o.menu_cursor), (10, 0), "IDF1-RED: stage %s: the page changed (menu_state %r)" % (stage, o.menu_state))
        self.assertEqual(o.setting_stop_distance, 100, "IDF1-RED: stage %s: setting_stop_distance was overwritten (%r)" % (stage, o.setting_stop_distance))
        self.assertEqual(X.settings_state(o), self.before, "IDF1-RED: stage %s: a setting changed" % stage)
        self.assert_file_untouched(self.snapshot, "stage %s" % stage)

    def assert_edit_ended(self, stage, expected_ratio=0.6):
        o = self.o
        self.assertFalse(o.input_mode_active, "IDF1-RED: stage %s: the edit did not end" % stage)
        self.assertEqual((o.menu_state, o.menu_cursor), (10, 0), "IDF1-RED: stage %s: the page is not 3/3 (menu_state %r)" % (stage, o.menu_state))
        self.assertEqual(o.rank_a_ratio, expected_ratio, "IDF1-RED: stage %s: the A boundary is %.2f" % (stage, o.rank_a_ratio))
        self.assertEqual(o.setting_stop_distance, 100, "IDF1-RED: stage %s: setting_stop_distance was overwritten (%r)" % (stage, o.setting_stop_distance))
        self.assert_file_untouched(self.snapshot, "stage %s" % stage)

    # ---- the stages A..F, one by one
    def test_stage_a_80_backspace_is_8_and_the_edit_goes_on(self):
        self.start()
        self.assert_editing("80", "start")
        self.back()
        self.assert_editing("8", "A")

    def test_stage_b_8_backspace_is_empty_and_the_edit_goes_on(self):
        self.start()
        self.back()
        self.back()
        self.assert_editing("", "B")

    def test_stage_c_empty_backspace_stays_empty_no_cancel_no_restore_no_page_change(self):
        self.start(a=80)
        self.back()
        self.back()
        self.back()
        self.back()                                                   # several Backspaces on an empty input
        self.assert_editing("", "C")
        self.assertEqual(self.o.rank_a_ratio, 0.8, "IDF1-RED: the empty Backspace changed the A boundary")

    def test_stage_c_the_empty_input_is_drawn_as_the_empty_input(self):
        self.start()
        self.back()
        self.back()
        texts, _ = X.render_f1(self.o, 10, menu_cursor=0)
        self.assertIn("_%", X.drawn(texts), "IDF1-GUARD: the empty input is not drawn with the underscore")

    def test_stage_d_8_enter_is_60_the_edit_ends_the_page_stays(self):
        self.start(a=80)                                              # before the edit 80: the 60 of the Enter is visible
        self.back()
        self.assert_editing("8", "A")
        X.f1_commit(self.o)
        self.assert_edit_ended("D")

    def test_stage_d_with_the_owner_fixture_before_60(self):
        self.start(a=60)
        self.back()
        X.f1_commit(self.o)
        self.assert_edit_ended("D (before 60)")

    def test_stage_e_empty_enter_is_60_the_edit_ends_the_page_stays(self):
        self.start(a=80)
        self.back()
        self.back()
        self.assert_editing("", "B")
        X.f1_commit(self.o)
        self.assert_edit_ended("E")

    def test_stage_f_backspace_after_the_enter_returns_to_page_2_of_3_after_d(self):
        self.start(a=80)
        self.back()
        X.f1_commit(self.o)
        self.assert_edit_ended("D")
        self.back()
        self.assertEqual((self.o.menu_state, self.o.menu_cursor), (6, 6), "IDF1-RED: the Backspace after the Enter did not return to page 2/3")
        self.assertEqual(self.o.rank_a_ratio, 0.6, "IDF1-RED: the confirmed A boundary changed")
        self.assertEqual(self.o.setting_stop_distance, 100, "IDF1-RED: setting_stop_distance changed on the way back")
        self.assertEqual(X.settings_state(self.o)["attrs"]["rank_a_ratio"], 0.6)
        self.assert_file_untouched(self.snapshot, "the page back")

    def test_stage_f_backspace_after_the_enter_returns_to_page_2_of_3_after_e(self):
        self.start(a=80)
        self.back()
        self.back()
        X.f1_commit(self.o)
        self.assert_edit_ended("E")
        self.back()
        self.assertEqual((self.o.menu_state, self.o.menu_cursor), (6, 6), "IDF1-RED: the Backspace after the empty Enter did not return to page 2/3")
        self.assertEqual(self.o.rank_a_ratio, 0.6)
        self.assertEqual(self.o.setting_stop_distance, 100, "IDF1-RED: setting_stop_distance changed on the way back")

    # ---- the Owner examples 1..5 as sequences
    def test_example_1_80_backspace_8_the_edit_goes_on(self):
        self.start()
        self.back()
        self.assert_editing("8", "example 1")

    def test_example_2_80_backspace_8_enter_60_page_3_backspace_page_2(self):
        self.start(a=80)
        self.back()
        X.f1_commit(self.o)
        self.assert_edit_ended("example 2 Enter")
        self.back()
        self.assertEqual(self.o.menu_state, 6, "IDF1-RED: example 2: the second Backspace did not return to page 2/3")

    def test_example_3_80_backspace_8_backspace_empty_the_edit_goes_on(self):
        self.start()
        self.back()
        self.back()
        self.assert_editing("", "example 3")

    def test_example_4_to_5_empty_enter_60_then_backspace_page_2(self):
        self.start(a=80)
        self.back()
        self.back()
        X.f1_commit(self.o)
        self.assert_edit_ended("example 4")
        self.back()
        self.assertEqual(self.o.menu_state, 6, "IDF1-RED: example 5: the Backspace after the Enter did not return to page 2/3")

    def test_typing_goes_on_after_the_backspaces(self):
        self.start()
        self.back()
        self.back()
        self.back()
        X.f1_type(self.o, "75")
        self.assert_editing("75", "typing after the Backspaces")
        X.f1_commit(self.o)
        self.assertEqual(self.o.rank_a_ratio, 0.75)

    def test_no_stage_ever_touches_the_stop_distance_for_any_typed_start(self):
        for typed in ("1", "9", "50", "99", "100", "00"):
            with self.subTest(typed=typed):
                self.start()
                for _ in range(3):
                    self.back()                                      # the "80" of the fixture is deleted, then the typed value is entered
                X.f1_type(self.o, typed)
                for _ in range(4):
                    self.back()
                    self.assertEqual(self.o.setting_stop_distance, 100, "IDF1-RED: a Backspace overwrote the stop distance (typed %r)" % typed)
                    self.assertTrue(self.o.input_mode_active)
                    self.assertEqual(self.o.menu_state, 10)

    # ---- the other back contracts are the old ones
    def test_back_without_an_edit_returns_as_before(self):
        self.start(a=60)
        self.o.input_mode_active = False
        self.o.menu_state, self.o.menu_cursor = 10, 0
        X.f1_cancel(self.o)
        self.assertEqual((self.o.menu_state, self.o.menu_cursor), (6, 6), "IDF1-GUARD: the back key of page 3/3 without an edit changed")
        self.assertEqual(self.o.setting_stop_distance, 100)

    def test_other_back_contracts_are_unchanged(self):
        self.start(a=60)
        o = self.o
        o.input_mode_active = False
        o.menu_state, o.menu_cursor = 6, 0
        X.f1_cancel(o)
        self.assertEqual(o.menu_state, 5, "IDF1-GUARD: the back of page 2/3 changed")
        o.menu_state = 9
        X.f1_cancel(o)
        self.assertEqual(o.menu_state, 6, "IDF1-GUARD: the back of the initial / release page changed")
        o.menu_state = 5
        o.menu_cursor = 0
        X.f1_cancel(o)
        self.assertEqual((o.menu_state, o.menu_cursor), (1, 0), "IDF1-GUARD: the back of page 1/3 changed")

    def test_the_stop_distance_backspace_still_deletes_a_digit(self):
        """The stop distance (menu_state 5) keeps its own contract: Backspace deletes a digit while typing."""
        self.start(a=60)
        o = self.o
        o.menu_state, o.menu_cursor = 5, 1
        o.input_mode_active, o.input_fresh, o.input_buffer = True, False, "123"
        X.f1_cancel(o)
        self.assertEqual(o.input_buffer, "12", "IDF1-GUARD: Backspace no longer deletes a digit of the stop distance")
        self.assertEqual(o.menu_state, 5)


if __name__ == "__main__":
    unittest.main()
