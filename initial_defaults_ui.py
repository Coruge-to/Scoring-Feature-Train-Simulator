"""INITIAL-DEFAULTS: the 'initial defaults' window (Commit 2). Started by `main.py --initial-defaults`, which is the process the Caller launches from the Input Device Properties (a separate process: the Properties callback never waits for it).

One window (初期値設定) edits the saved_defaults (initial_defaults.py) and saves them with OK (atomic); x / Esc saves nothing. It is not the F1 screen and knows neither the Overlay nor the managed mode: the F1 settings are regenerated from the saved file at the next scenario load.
The speed limit / advance dependency is the shared state function of initial_defaults (the same rule as F1). The safety intervention (保安装置介入) is an empty checkbox that cannot be turned ON in the beta.
Single instance: a named mutex; a second start exits at once.
"""
import ctypes
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QStyleFactory, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

import config
import initial_defaults as D

FLAG = "--initial-defaults"
TITLE = "初期値設定"
NOTE = "※設定は次回のシナリオ読込時またはF5再読込時に適用されます。"
ENV_LABELS = ("現在時刻", "残り時間", "現在速度", "制限速度", "制限速度予告", "残距離", "ハンドル・レバーサ位置", "勾配")
TIMING_LABEL = "変更可能な非採時駅を全て採時駅にする"
PENALTY_LABELS = (("pen_rolling", "転動"), ("pen_safety", "保安装置介入"), ("pen_speed", "速度制限超過"), ("pen_shock", "停車時衝動"), ("pen_eb", "非常ブレーキ"), ("pen_init", "初動・緩和ブレーキ"))
PRESET_BUTTONS = (("beginner", "初級", config.COLOR_N), ("intermediate", "中級", config.COLOR_P), ("advanced", "上級", config.COLOR_B_EMG))
A_RANK_INVALID = "Aランク境界は50〜90の整数で入力してください。"
SAVE_FAILED = "保存できませんでした。"
MUTEX_NAME = "Local\\TSScoring.InitialDefaults.v1"
ERROR_ALREADY_EXISTS = 183


def is_requested(args):
    return FLAG in list(args)


class SingleInstance(object):
    """The one-window guard: a named mutex of the user session. acquire() is False when another process (or object) holds it; it fails open when the mutex can not be created at all."""

    def __init__(self, name=None):
        self.name = name or MUTEX_NAME
        self.handle = None

    def acquire(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, 0, self.name)
        error = ctypes.get_last_error()
        if not handle:
            return True
        if error == ERROR_ALREADY_EXISTS:
            kernel.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def release(self):
        if self.handle:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.handle)
            self.handle = None


class FixedOffCheckBox(QCheckBox):
    """An empty checkbox that cannot be turned ON by the mouse, the keyboard or the program (the beta has no safety device scoring)."""

    def __init__(self, *args):
        QCheckBox.__init__(self, *args)
        self.toggled.connect(self._back_to_off)          # the safety net for the calls that Qt makes without the overridable methods (toggle())

    def _back_to_off(self, checked):
        if checked:
            QCheckBox.setChecked(self, False)

    def nextCheckState(self):
        self.setCheckState(Qt.CheckState.Unchecked)

    def setChecked(self, checked):
        QCheckBox.setChecked(self, False)

    def setCheckState(self, state):
        QCheckBox.setCheckState(self, Qt.CheckState.Unchecked)


class FocusWheelSpinBox(QSpinBox):
    """The standard spin box (the up / down buttons are part of it); the mouse wheel changes the value only while it has the keyboard focus (a wheel over the box never gives the focus)."""

    def __init__(self, *args):
        QSpinBox.__init__(self, *args)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWrapping(False)
        self.setSingleStep(1)

    def wheelEvent(self, event):
        if self.hasFocus():
            QSpinBox.wheelEvent(self, event)
        else:
            event.ignore()


ROW_SPACING = 4                                                   # the one vertical spacing of every item row of both columns


def use_native_style():
    """The native Windows drawing of the standard widgets (check boxes, spin box) as the application style (Qt owns it); the other styles take the accent colour of the system theme (a dark slate here). Only the process of this window is affected."""
    app = QApplication.instance()
    if app is not None and "windowsvista" in [k.lower() for k in QStyleFactory.keys()] and app.style().objectName().lower() != "windowsvista":
        app.setStyle("windowsvista")


def _column_title(text):
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def build_dialog(defaults, save):
    """The window for `defaults` (an InitialDefaults). save(InitialDefaults) is called by OK; it raises on failure (the window then stays open)."""
    dialog = QDialog()
    dialog.setObjectName("initial_defaults_dialog")
    dialog.setWindowTitle(TITLE)
    use_native_style()
    root = QVBoxLayout(dialog)
    root.setContentsMargins(36, 28, 36, 16)
    root.setSpacing(8)
    frame = QFrame()                                               # ONE thin outer frame around both columns (not a QGroupBox per section)
    frame.setObjectName("outer_frame")
    frame.setFrameShape(QFrame.Shape.Box)
    frame.setFrameShadow(QFrame.Shadow.Plain)
    frame.setLineWidth(1)
    columns = QHBoxLayout(frame)
    columns.setContentsMargins(18, 14, 18, 14)
    columns.setSpacing(18)
    root.addWidget(frame, 1)

    left, right = QVBoxLayout(), QVBoxLayout()
    left.setSpacing(ROW_SPACING)
    right.setSpacing(ROW_SPACING)
    columns.addLayout(left, 11)
    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.VLine)
    columns.addWidget(divider)
    columns.addLayout(right, 10)

    left.addWidget(_column_title("環境設定"))
    env_boxes = []
    for index, label in enumerate(ENV_LABELS):
        box = QCheckBox(label)
        box.setObjectName("env_%d" % index)
        box.setChecked(bool(defaults.environment[index]))
        left.addWidget(box)
        env_boxes.append(box)
    left.addSpacing(18)
    left.addWidget(_column_title("採時駅設定"))
    timing = QCheckBox(TIMING_LABEL)
    timing.setObjectName("timing")
    timing.setChecked(bool(defaults.all_changeable_non_timed_to_timed))
    left.addWidget(timing)
    left.addStretch(1)

    right.addWidget(_column_title("減点項目設定"))
    p = defaults.penalties
    pen_state = {"pen_rolling": p.rolling, "pen_safety": False, "pen_speed": p.speed_limit_exceeded, "pen_shock": p.stop_shock, "pen_eb": p.emergency_brake, "pen_init": p.initial_release_brake == "on1"}
    for name, label in PENALTY_LABELS:
        box = FixedOffCheckBox(label) if name == "pen_safety" else QCheckBox(label)
        box.setObjectName(name)
        box.setChecked(bool(pen_state[name]))
        right.addWidget(box)
    right.addSpacing(18)
    right.addWidget(_column_title("簡単設定"))
    preset_row = QHBoxLayout()
    preset_buttons = []
    for key, label, colour in PRESET_BUTTONS:                      # the EXISTING colour constants of config.py (the colours of the F1 page and the HUD): no new RGB value
        button = QPushButton(label)
        button.setObjectName("preset_" + key)
        button.setStyleSheet("background-color: rgb(%d, %d, %d); color: white; font-weight: bold; padding: 6px 18px;" % tuple(colour[:3]))
        button.setMinimumSize(110, 52)
        preset_row.addWidget(button)
        preset_buttons.append((key, button))
    right.addLayout(preset_row)
    rank_row = QHBoxLayout()
    rank_row.addWidget(QLabel("Aランクは理論値の"))
    spin = FocusWheelSpinBox()
    spin.setObjectName("a_rank")
    spin.setMinimumWidth(64)
    spin.setRange(D.A_RANK_MIN_PERCENT, D.A_RANK_MAX_PERCENT)
    spin.setValue(defaults.a_rank_percent if D.a_rank_percent_valid(defaults.a_rank_percent) else D.A_RANK_BUILTIN_PERCENT)
    rank_row.addWidget(spin)
    rank_row.addWidget(QLabel("%以上"))
    rank_row.addStretch(1)
    right.addLayout(rank_row)
    right.addStretch(1)

    def apply_preset(key):
        """The six deductions and the A boundary of the preset (initial_defaults.apply_preset: the data of the model). The environment, the all-timing setting and the safety intervention are not touched."""
        penalties, percent = D.PRESETS[key]
        values = {"pen_rolling": penalties.rolling, "pen_speed": penalties.speed_limit_exceeded, "pen_shock": penalties.stop_shock, "pen_eb": penalties.emergency_brake, "pen_init": penalties.initial_release_brake == "on1"}
        for object_name, value in values.items():
            dialog.findChild(QWidget, object_name).setChecked(bool(value))
        spin.setValue(percent)

    for key, button in preset_buttons:
        button.clicked.connect(lambda checked=False, k=key: apply_preset(k))

    guard = {"busy": False}

    def sync_environment(changed, enabled):
        if guard["busy"]:
            return
        guard["busy"] = True
        try:
            settings = dict(zip(D.ENV_F1_KEYS, [b.isChecked() for b in env_boxes]))
            if changed == 3:
                D.set_speed_limit(settings, enabled)
            elif changed == 4:
                D.set_speed_limit_advance(settings, enabled)
            for index, key in enumerate(D.ENV_F1_KEYS):
                if env_boxes[index].isChecked() != settings[key]:
                    env_boxes[index].setChecked(settings[key])
        finally:
            guard["busy"] = False

    for index in (3, 4):
        env_boxes[index].toggled.connect(lambda enabled, i=index: sync_environment(i, enabled))

    note = QLabel(NOTE)
    note.setObjectName("note")
    root.addWidget(note)
    message = QLabel("")
    message.setObjectName("message")
    message.setStyleSheet("color: rgb(%d, %d, %d);" % tuple(config.COLOR_B_EMG[:3]))
    root.addWidget(message)
    ok = QPushButton("OK")
    ok.setObjectName("ok")
    ok.setDefault(True)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    buttons.addWidget(ok)
    root.addLayout(buttons)

    def on_ok():
        text = spin.lineEdit().text().strip() if spin.lineEdit() is not None else str(spin.value())
        if not (text.isascii() and text.isdigit() and D.a_rank_percent_valid(int(text))):         # an empty / non-integer / out-of-range input is refused: never clamped silently, nothing is saved
            message.setText(A_RANK_INVALID)
            spin.setFocus()
            spin.selectAll()
            return
        try:
            save(collect(dialog))
        except (ValueError, D.SaveError, OSError):
            message.setText(SAVE_FAILED)
            return
        message.setText("")
        dialog.accept()

    ok.clicked.connect(lambda checked=False: on_ok())
    dialog.setMinimumSize(860, 440)
    dialog.resize(860, 440)
    return dialog


def collect(dialog):
    """The InitialDefaults the window shows now (the safety intervention is always False; the initial / release brake is 'on1' or 'off')."""
    def box(name):
        return dialog.findChild(QWidget, name)
    environment = D.Environment(*[bool(box("env_%d" % i).isChecked()) for i in range(8)])
    penalties = D.Penalties(rolling=bool(box("pen_rolling").isChecked()), safety_intervention=False, speed_limit_exceeded=bool(box("pen_speed").isChecked()),
                            stop_shock=bool(box("pen_shock").isChecked()), emergency_brake=bool(box("pen_eb").isChecked()),
                            initial_release_brake="on1" if box("pen_init").isChecked() else "off")
    return D.InitialDefaults(environment, bool(box("timing").isChecked()), penalties, int(box("a_rank").value()))


def run(argv, defaults_path=None, instance=None, exec_fn=None):
    """The process entry: 0 when the window was shown (or another one is already open), 2 for any arguments other than the flag alone."""
    if list(argv[1:]) != [FLAG]:
        sys.stderr.write("usage: main.py %s\n" % FLAG)
        return 2
    holder = instance if instance is not None else SingleInstance()
    if not holder.acquire():
        return 0
    try:
        from PyQt6.QtWidgets import QApplication
        path = defaults_path or D.defaults_path()
        result = D.load(path)
        QApplication.instance() or QApplication(list(argv[:1]))
        dialog = build_dialog(result.defaults, save=lambda value: D.save(value, path))
        (exec_fn or (lambda d: d.exec()))(dialog)
        return 0
    finally:
        holder.release()
