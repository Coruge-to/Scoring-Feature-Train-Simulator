"""INITIAL-DEFAULTS Stage F1 (Owner contract 2026-11-11): RED-only test support. TEST CODE ONLY - no product file is touched.

Message conventions (used by the result classifier in the deliverables):
  * 'IDF1-RED: ...'     an AssertionError that states a missing Owner contract -> PRODUCT-RED (expected to fail until Stage F2)
  * 'IDF1-GUARD: ...'   an AssertionError on a contract that already holds -> must stay GREEN (a failure is a regression)
  * 'IDF1-HARNESS: ...' the fixture / anchor itself is broken -> HARNESS-RED (never acceptable)
  * any other exception (ImportError, AttributeError, TypeError ...) is FIXTURE-RED / HARNESS-RED and must be repaired before the RED is accepted.

The F1 operations are driven through the REAL Overlay of sia_rig (offscreen Qt, every outside effect faked): handle_menu_enter / handle_menu_left / handle_menu_right / handle_menu_backspace, apply_numeric_char and the REAL
menu_ui.draw_menu. The 'initial defaults' window is the REAL initial_defaults_ui.build_dialog (offscreen). Nothing here binds a port, touches the keyboard, BVE, the Caller, a DLL or the real %LOCALAPPDATA% (redirected to a temp dir)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sia_rig as R  # noqa: E402

# ---------------------------------------------------------------------------------------------------------------------------------------- the Owner contract (Stage F1 instruction, section 3)
# typed text -> the effective value after the commit (50..90 kept, 00..49 / 91..99 / empty = 60)
#
# Stage F2 contract (Owner 2026-11-11, supersedes the F1 draft): the F1 side has NO notice / guide / state message at all; the empty F1 Enter keeps the value from before the edit; Back (Backspace) keeps the value and leaves the page;
# the 'initial defaults' window shows the red input error 50～90の整数を入力してください。 only after an OK with an out-of-range / empty field.
A_TABLE = (("00", 60), ("40", 60), ("49", 60), ("50", 50), ("60", 60), ("70", 70), ("90", 90), ("91", 60), ("99", 60))
ONE_DIGIT = tuple((str(n), 60) for n in range(10))             # a single digit 0..9 is 60
A_EXTRA_CORRECTED = (("09", 60),)                                # leading zero: still 00..49 -> 60
A_CORRECTED_TEXTS = ("00", "40", "49", "91", "99")               # (the dialog adds the empty field and the single digits)
A_VALID_TEXTS = ("50", "60", "70", "90")
A_ERROR_MESSAGE = "50～90の整数を入力してください。"
OLD_A_ERROR_MESSAGE = "50〜90の整数で入力してください。"
RETIRED_NOTICE = "範囲外のため60に戻しました。"
F1_DESCRIPTION = "Rank A は理論値の 50～90％ の間で調整が可能です。"
SAVE_FAILED_MESSAGE = "保存できませんでした。"
SAFETY_NAME = "保安装置介入"
OLD_SAFETY_NAME = "ATS信号無視"

_TMP = {}


def redirect_profile(prefix):
    """setUpModule helper: every profile / LOCALAPPDATA path of the process points into a temp dir; returns the cleanup for tearDownModule."""
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix=prefix)
    _TMP["saved"] = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "USERPROFILE", "HOME")}
    for k in _TMP["saved"]:
        os.environ[k] = _TMP["dir"].name
    return _TMP["dir"].name


def restore_profile():
    for k, v in _TMP.get("saved", {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    if "dir" in _TMP:
        _TMP["dir"].cleanup()


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


_APP = []


def qt_app():
    """The QApplication, kept referenced for the whole process (a QApplication with no Python reference is destroyed by the garbage collector and the next widget aborts the process: FIXTURE-RED found while building this support)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["idf1-red"])
    if app not in _APP:
        _APP.append(app)
    return app


# ---------------------------------------------------------------------------------------------------------------------------------------- file snapshot of the saved defaults
def file_snapshot(path):
    if not os.path.exists(path):
        return (False, None, None)
    st = os.stat(path)
    with open(path, "rb") as f:
        return (True, f.read(), st.st_mtime_ns)


# ---------------------------------------------------------------------------------------------------------------------------------------- F1 rendering (the REAL menu_ui.draw_menu)
def render_f1(o, state, **attrs):
    """Draws the F1 page `state` of the Overlay `o` with the REAL menu_ui.draw_menu; returns (texts, zones). texts = [(text, x, y, align)] of every draw_text_with_outline call; zones = menu_click_zones."""
    from PyQt6.QtGui import QColor, QImage, QPainter
    import menu_ui
    for k, v in attrs.items():
        setattr(o, k, v)
    o.menu_state = state
    texts = []
    original = menu_ui.draw_text_with_outline

    def record(painter, t, font, tc, oc, x, y, align="left", passes=8):
        texts.append((str(t), round(float(x)), round(float(y)), align))
        return original(painter, t, font, tc, oc, x, y, align, passes)

    menu_ui.draw_text_with_outline = record
    o.menu_click_zones = []
    image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    image.fill(QColor(58, 66, 78))
    painter = QPainter(image)
    try:
        menu_ui.draw_menu(o, painter, 1920.0)
    finally:
        painter.end()
        menu_ui.draw_text_with_outline = original
    return texts, list(o.menu_click_zones)


def drawn(texts):
    return [t[0] for t in texts]


def a_pct_shown(texts):
    """The A boundary percentage of F1 page 3/3 (the centre-aligned 'NN%' of the slider labels; the A label is the last)."""
    cands = [t for t in texts if t[0].endswith("%") and len(t[0]) <= 4 and t[3] == "center"]
    return cands


# ---------------------------------------------------------------------------------------------------------------------------------------- F1 operations
def f1_start_edit(o):
    o.menu_state, o.menu_cursor, o.menu_cursor_x = 10, 0, 0
    o.input_mode_active = False
    o.handle_menu_enter(False)                  # the existing F1 path: Enter on the A boundary starts the direct input
    assert o.input_mode_active, "IDF1-HARNESS: Enter on page 3/3 row 0 did not start the direct input"


def f1_type(o, text):
    for ch in text:
        o.apply_numeric_char(ch)


def f1_commit(o):
    o.handle_menu_enter(False)                  # the existing F1 confirm path (Enter)


def f1_cancel(o):
    """The F1 'back / cancel' operation. NOTE: the F1 key map has no Esc: Esc quits the application (update_logic) and Backspace is the back key (handle_menu_backspace) - the 'Esc' of the Owner contract is this operation."""
    o.handle_menu_backspace(False)


def f1_edit_and_commit(o, typed):
    f1_start_edit(o)
    f1_type(o, typed)
    f1_commit(o)


# ---------------------------------------------------------------------------------------------------------------------------------------- the base classes
TRACKED_SETTINGS = ("pen_roll", "pen_limit", "pen_jerk", "pen_eb", "pen_ats", "setting_stop_distance", "setting_start_idx", "setting_end_idx", "setting_initial_brake", "rank_a_ratio")


def settings_state(o):
    """Everything of the scenario settings the A boundary edit must not touch (a deep copy)."""
    import copy
    return {
        "attrs": {k: copy.deepcopy(getattr(o, k, None)) for k in TRACKED_SETTINGS},
        "disp_settings": copy.deepcopy(o.disp_settings),
        "penalty_init_rules": copy.deepcopy(o.penalty_init_rules),
        "brake_rules": copy.deepcopy(getattr(o, "brake_rules", None)),
        "user_timing_overrides": copy.deepcopy(getattr(o, "user_timing_overrides", None)),
    }


class LinkBase(unittest.TestCase):
    """A real Overlay + a REAL saved-defaults file in the redirected profile. The Overlay reads the file with the default initial_defaults.load at every scenario load."""

    @classmethod
    def setUpClass(cls):
        qt_app()
        import main
        import scoring_logic
        import scoring_settings
        import initial_defaults
        cls.main, cls.S, cls.SS, cls.D = main, scoring_logic, scoring_settings, initial_defaults

    def setUp(self):
        self.path = self.D.defaults_path()
        if os.path.exists(self.path):
            os.remove(self.path)
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        self.o = self.rig.o
        self.save_calls = []
        self._real_save = self.D.save

        def spy(*a, **k):
            self.save_calls.append((a, k))
            return self._real_save(*a, **k)

        self.D.save = spy
        self.addCleanup(lambda: setattr(self.D, "save", self._real_save))

    def write_saved(self, defaults):
        self._real_save(defaults, self.path)           # the fixture write is not a product call: it bypasses the spy
        return file_snapshot(self.path)

    def saved(self):
        return self.D.load(self.path).defaults

    def scenario(self, sid):
        self.o.apply_telemetry_text("SCENARIO_ID:%d,SPEED:0" % sid)

    _sid_counter = [100]

    def new_scenario(self):
        """A scenario id never used before in this process (a repeated id is not a reload): for tests that start more than once."""
        LinkBase._sid_counter[0] += 1
        self.scenario(LinkBase._sid_counter[0])

    def base(self, a=60, **changes):
        b = self.D.builtin_defaults()
        return b._replace(a_rank_percent=a, **changes)

    def assert_file_untouched(self, before, why):
        self.assertEqual(file_snapshot(self.path), before, "IDF1-GUARD: %s changed the saved defaults file (bytes or mtime)" % why)
        self.assertEqual(self.save_calls, [], "IDF1-GUARD: %s called the save function" % why)


class DialogBase(unittest.TestCase):
    """The REAL 'initial defaults' window (build_dialog) with a recording save."""

    @classmethod
    def setUpClass(cls):
        qt_app()
        import initial_defaults_ui
        import initial_defaults
        import config
        cls.U, cls.D, cls.C = initial_defaults_ui, initial_defaults, config

    def setUp(self):
        self.path = self.D.defaults_path()
        if os.path.exists(self.path):
            os.remove(self.path)
        self.dialogs = []
        self.saves = []
        self.fail_save = False

    def tearDown(self):
        for d in self.dialogs:
            d.close()
            d.deleteLater()

    def record_save(self, value):
        if self.fail_save:
            raise self.D.SaveError("forced")
        self.saves.append(value)

    def real_save(self, value):
        self.saves.append(value)
        return self.D.save(value, self.path)

    def make(self, defaults=None, save=None):
        d = self.U.build_dialog(defaults or self.D.builtin_defaults(), save=save or self.record_save)
        self.dialogs.append(d)
        d.show()
        self.app_events()
        return d

    def app_events(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    def find(self, d, name):
        from PyQt6.QtWidgets import QWidget
        w = d.findChild(QWidget, name)
        self.assertIsNotNone(w, "IDF1-HARNESS: no widget %r in the window" % name)
        return w

    def spin(self, d):
        return self.find(d, "a_rank")

    def message(self, d):
        return self.find(d, "message").text()

    def type_into_spin(self, d, text):
        """Real key events into the line edit (what the user does): select all, delete, then one key per character."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        spin = self.spin(d)
        le = spin.lineEdit()
        spin.setFocus()
        le.selectAll()
        QTest.keyClick(le, Qt.Key.Key_Delete)
        for ch in text:
            QTest.keyClicks(le, ch)
        self.app_events()
        return le.text()

    def set_spin_text(self, d, text):
        """Puts a text into the field WITHOUT the key validator (isolates the commit contract from the keystroke contract)."""
        spin = self.spin(d)
        spin.lineEdit().setText(text)
        self.app_events()

    def press_ok(self, d):
        self.find(d, "ok").click()
        self.app_events()

    def shown_text(self, d):
        return self.spin(d).lineEdit().text()

    def is_open(self, d):
        return d.isVisible() and d.result() == 0
