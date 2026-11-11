"""INITIAL-DEFAULTS: the 'initial defaults' window (Commit 2). Started by `main.py --initial-defaults`, which is the process the Caller launches from the Input Device Properties (a separate process: the Properties callback never waits for it).

One window (初期値設定) edits the saved_defaults (initial_defaults.py) and saves them with OK (atomic); x / Esc saves nothing. It is not the F1 screen and knows neither the Overlay nor the managed mode: the F1 settings are regenerated from the saved file at the next scenario load.
The speed limit / advance dependency is the shared state function of initial_defaults (the same rule as F1). The safety intervention (保安装置介入) is an empty checkbox that cannot be turned ON in the beta.
Single instance: a named mutex; a second start exits at once.
"""
import ctypes
import logging
import math
import sys

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter, QPalette, QValidator
from PyQt6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory, QStyleOptionButton, QStyleOption, QStyleOptionSpinBox, QStylePainter, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget

import config
import initial_defaults as D

FLAG = "--initial-defaults"
TITLE = "初期値設定"
NOTE = "※この設定は次にシナリオを読み込んだときに適用されます。"
ENV_LABELS = ("現在時刻", "残り時間", "現在速度", "制限速度", "制限速度予告", "残距離", "ハンドル・レバーサ位置", "勾配")
TIMING_LABEL = "変更可能な非採時駅を全て採時駅にする"
PENALTY_LABELS = (("pen_rolling", "転動"), ("pen_safety", "保安装置介入"), ("pen_speed", "速度制限超過"), ("pen_shock", "停車時衝動"), ("pen_eb", "非常ブレーキ"), ("pen_init", "初動・緩和ブレーキ"))
PRESET_BUTTONS = (("beginner", "初級", config.COLOR_N), ("intermediate", "中級", config.COLOR_P), ("advanced", "上級", config.COLOR_B_EMG))
A_RANK_INVALID = "50～90の整数を入力してください。"
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


COLOR_HIGHLIGHT = 13                                              # GetSysColor indexes of the Windows selection colours
COLOR_HIGHLIGHTTEXT = 14


class SpinFocusLessStyle(QProxyStyle):
    """The style of the A-rank spin box only: the theme (windowsvista) draws a blue focus line under a focused spin box; it is not drawn here. The real focus is untouched: State_HasFocus is dropped only from a copy of the option that is handed to the drawing of CC_SpinBox."""

    def __init__(self, base):
        QProxyStyle.__init__(self, base)
        self.setObjectName("windowsvista")                          # it is still the native Windows style for every check on the style name

    def drawComplexControl(self, control, option, painter, widget=None):
        if control == QStyle.ComplexControl.CC_SpinBox and isinstance(option, QStyleOptionSpinBox):
            drawn = QStyleOptionSpinBox(option)
            drawn.state &= ~QStyle.StateFlag.State_HasFocus
            return QProxyStyle.drawComplexControl(self, control, drawn, painter, widget)
        return QProxyStyle.drawComplexControl(self, control, option, painter, widget)


def system_highlight_colours():
    """(selection background, selection text) of Windows, or None when the system colours can not be read."""
    try:
        user32 = ctypes.windll.user32
        background = user32.GetSysColor(COLOR_HIGHLIGHT)
        text = user32.GetSysColor(COLOR_HIGHLIGHTTEXT)
    except (AttributeError, OSError):
        return None
    if background == 0 and text == 0:                                # GetSysColor answers 0 for a failure
        return None
    return (QColor(background & 255, (background >> 8) & 255, (background >> 16) & 255), QColor(text & 255, (text >> 8) & 255, (text >> 16) & 255))


def apply_selection_colours(dialog, line_edit):
    """The Active selection colours of the inner line edit of the A-rank spin box are the Windows system colours (the other groups stay as they are). A failure keeps the existing palette and says so (property selectionColourSource + log)."""
    colours = system_highlight_colours()
    if colours is None:
        dialog.setProperty("selectionColourSource", "fallback")
        logging.getLogger(__name__).warning("initial defaults: the Windows selection colours are not available; the existing palette is used")
        return
    palette = line_edit.palette()
    palette.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight, colours[0])
    palette.setColor(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText, colours[1])
    line_edit.setPalette(palette)
    dialog.setProperty("selectionColourSource", "system")


def apply_spin_focus_style(dialog, spin):
    """Own style of the A-rank spin box (owned by the dialog); the application style and every other widget are not touched."""
    base = QStyleFactory.create("windowsvista")
    if base is None:
        return
    style = SpinFocusLessStyle(base)
    style.setParent(dialog)
    spin.setStyle(style)


SPIN_BUTTON_WIDTH = 16                                            # logical px of the two arrow buttons of the A-rank spin box (Qt converts it with the Windows scale)
SPIN_ARROW_SIZE = 7                                               # logical px of the square the Qt arrow primitive is drawn in (candidate B2-M, Owner 2026-11-10)
SPIN_UP_NAME = "Aランク境界を増やす"                               # the accessible names / descriptions of the two buttons (UI Automation shows them as Button elements)
SPIN_DOWN_NAME = "Aランク境界を減らす"
SPIN_UP_DESCRIPTION = "Aランク境界を1パーセント増やします"
SPIN_DOWN_DESCRIPTION = "Aランク境界を1パーセント減らします"
SPIN_FACE_BLEND = 0.35                                            # face = Base towards Window
SPIN_BORDER_BLEND = 0.18                                          # border = Base towards WindowText (0.10 when disabled)
SPIN_ACTIVE_BLEND = 0.15                                          # hovered / pressed face = face towards the selection colour


def qround(value):
    """Round half up, as Qt does (Python's round() rounds half to even)."""
    return int(math.floor(value + 0.5))


def mix_colours(first, second, amount):
    return QColor(*[int(qround(a * (1 - amount) + b * amount)) for a, b in ((first.red(), second.red()), (first.green(), second.green()), (first.blue(), second.blue()))])


_ARROW_INK = {}


def arrow_ink(widget, up, size, ratio):
    """(left, top, right, bottom) in whole device pixels of the ink of the Qt arrow primitive drawn at the origin of a square of `size` logical px: measured, never assumed."""
    key = (up, size, round(ratio, 3))
    if key not in _ARROW_INK:
        margin = 4
        side = int((size + 2 * margin) * ratio) + 4
        image = QImage(side, side, QImage.Format.Format_ARGB32)
        image.fill(QColor(250, 250, 250))
        image.setDevicePixelRatio(ratio)
        painter = QPainter(image)
        option = QStyleOption()
        option.rect = QRect(margin, margin, size, size)
        option.state = QStyle.StateFlag.State_Enabled
        option.palette = widget.palette()
        for role in (QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            option.palette.setColor(role, QColor(0, 0, 0))
        widget.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowUp if up else QStyle.PrimitiveElement.PE_IndicatorArrowDown, option, painter)
        painter.end()
        dark = [(x, y) for y in range(image.height()) for x in range(image.width()) if (image.pixelColor(x, y).red() + image.pixelColor(x, y).green() + image.pixelColor(x, y).blue()) / 3 <= 205]
        origin = qround(margin * ratio)
        _ARROW_INK[key] = (min(x for x, y in dark) - origin, min(y for x, y in dark) - origin, max(x for x, y in dark) + 1 - origin, max(y for x, y in dark) + 1 - origin)
    return _ARROW_INK[key]


class SpinArrowButton(QToolButton):
    """One of the two square arrow buttons of the A-rank spin box. Face, border and arrow colours come from the palette (the hover colour is the Windows selection colour); the arrow is the Qt primitive, centred on the button by its measured ink. The up button is one logical row taller than its half: its last row is the boundary row that both buttons share."""

    def __init__(self, parent, up):
        QToolButton.__init__(self, parent)
        self.up = up
        self.peer = None
        self.step = None                                            # the step of the spin box this button makes
        self.press_stepped = False
        self.setArrowType(Qt.ArrowType.UpArrow if up else Qt.ArrowType.DownArrow)
        self.setAutoRepeat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, event):
        QToolButton.enterEvent(self, event)
        QTimer.singleShot(0, self.raise_)                           # the hovered button draws its whole border over the shared boundary row
        self.update()

    def leaveEvent(self, event):
        QToolButton.leaveEvent(self, event)
        self.update()

    def mousePressEvent(self, event):
        self.raise_()
        self.press_stepped = False
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled() and self.step is not None:
            self.step()                                             # like the native spin box: the first step is made by the press, the auto repeat follows
            self.press_stepped = True
        QToolButton.mousePressEvent(self, event)

    def on_clicked(self, checked=False):
        if self.step is None:
            return
        if self.isDown():
            self.step()                                             # an auto repeat (the button is still held)
        elif self.press_stepped:
            self.press_stepped = False                              # the click that ends a press which already stepped: no second step
        else:
            self.step()                                             # click() from the accessibility tree or from the program

    def paintEvent(self, event):
        palette = self.palette()
        enabled = self.isEnabled()
        active = enabled and (self.underMouse() or self.isDown())
        base = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Base)
        window = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText)
        system = system_highlight_colours()
        highlight = system[0] if system else palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        face = mix_colours(base, window, SPIN_FACE_BLEND)
        border = mix_colours(base, text, SPIN_BORDER_BLEND if enabled else SPIN_BORDER_BLEND / 2)
        if active:
            face = mix_colours(face, highlight, SPIN_ACTIVE_BLEND)
            border = highlight
        painter = QPainter(self)
        transform = painter.deviceTransform()                       # the real (fractional) device origin of this widget: everything below is drawn on whole device pixels
        ratio = transform.m11()                                     # logical -> device scale of this drawing (taken from the painter, not from the screen)
        origin_x, origin_y = transform.dx(), transform.dy()
        left, top = qround(origin_x), qround(origin_y)
        width = qround(origin_x + self.width() * ratio) - left
        height = qround(origin_y + self.height() * ratio) - top
        if self.up:
            height = qround(origin_y + (self.peer.y() - self.y()) * ratio) - top + 1
        painter.translate((left - origin_x) / ratio, (top - origin_y) / ratio)
        painter.scale(1.0 / ratio, 1.0 / ratio)
        painter.fillRect(0, 0, width, height, face)
        for rect in ((0, 0, width, 1), (0, height - 1, width, 1), (0, 0, 1, height), (width - 1, 0, 1, height)):
            painter.fillRect(*rect, border)
        ink_left, ink_top, ink_right, ink_bottom = arrow_ink(self, self.up, SPIN_ARROW_SIZE, ratio)
        offset_x = qround(width / 2.0 - (ink_left + ink_right) / 2.0)
        offset_y = qround(height / 2.0 - (ink_top + ink_bottom) / 2.0)
        option = QStyleOption()
        option.rect = QRect(0, 0, SPIN_ARROW_SIZE, SPIN_ARROW_SIZE)
        option.state = QStyle.StateFlag.State_Enabled if enabled else QStyle.StateFlag.State_None
        option.palette = palette
        painter.translate(offset_x, offset_y)
        painter.scale(ratio, ratio)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowUp if self.up else QStyle.PrimitiveElement.PE_IndicatorArrowDown, option, painter)
        painter.end()


def spin_style_hint(spin, hint):
    """A positive integer style hint of the spin box, or 0 when the style does not give one."""
    try:
        value = int(spin.style().styleHint(hint, None, spin))
    except (AttributeError, TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def apply_spin_arrow_buttons(dialog, spin):
    """The two independent arrow buttons of the A-rank spin box (the native ones are not shown). The number area stays what it was: the right text margin of the inner line edit is the width of the buttons."""
    line_edit = spin.lineEdit()
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    margins = line_edit.textMargins()
    line_edit.setTextMargins(margins.left(), margins.top(), SPIN_BUTTON_WIDTH, margins.bottom())
    up = SpinArrowButton(spin, True)
    down = SpinArrowButton(spin, False)
    up.setObjectName("spin_up")
    down.setObjectName("spin_down")
    up.peer, down.peer = down, up
    up.setAccessibleName(SPIN_UP_NAME)
    up.setAccessibleDescription(SPIN_UP_DESCRIPTION)
    down.setAccessibleName(SPIN_DOWN_NAME)
    down.setAccessibleDescription(SPIN_DOWN_DESCRIPTION)
    threshold = spin_style_hint(spin, QStyle.StyleHint.SH_SpinBox_ClickAutoRepeatThreshold)      # the auto repeat of the native spin box: the same hints, no value of our own
    rate = spin_style_hint(spin, QStyle.StyleHint.SH_SpinBox_ClickAutoRepeatRate)
    for button in (up, down):
        if threshold:
            button.setAutoRepeatDelay(threshold)
        if rate:
            button.setAutoRepeatInterval(rate)
    up.step, down.step = spin.stepUp, spin.stepDown
    up.clicked.connect(up.on_clicked)
    down.clicked.connect(down.on_clicked)

    def refresh(value=None):
        up.setEnabled(spin.value() < spin.maximum())                # only the side that can not move is disabled
        down.setEnabled(spin.value() > spin.minimum())

    spin.valueChanged.connect(refresh)
    refresh()
    spin.arrow_buttons = (up, down)
    spin.place_arrow_buttons()
    up.show()
    down.show()
    down.raise_()


class FocusWheelSpinBox(QSpinBox):
    """The standard spin box (the up / down buttons are part of it); the mouse wheel changes the value only while it has the keyboard focus (a wheel over the box never gives the focus)."""

    def __init__(self, *args):
        QSpinBox.__init__(self, *args)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWrapping(False)
        self.setSingleStep(1)
        self.arrow_buttons = None
        self.finishing_text = None

    def place_arrow_buttons(self):
        """The up button covers the upper half plus one row, the down button the lower half: no gap, one shared boundary row."""
        if not self.arrow_buttons:
            return
        up, down = self.arrow_buttons
        inner = self.height() - 2
        half = inner // 2
        up.setGeometry(self.width() - 1 - SPIN_BUTTON_WIDTH, 1, SPIN_BUTTON_WIDTH, half + 1)
        down.setGeometry(self.width() - 1 - SPIN_BUTTON_WIDTH, 1 + half, SPIN_BUTTON_WIDTH, inner - half)

    def validate(self, text, pos):
        """The editable text of the A boundary (the shared rule of initial_defaults.a_rank_text_allowed): ASCII digits, 2 at most, 00..99 while typing / pasting / committing from an IME; anything else (sign, space, point, a full-width digit, a 3rd digit)
        is refused. The value range 50..90 is judged at the OK (D.normalize_a_rank_percent), never while typing."""
        if not D.a_rank_text_allowed(text):
            return QValidator.State.Invalid, text, pos
        return (QValidator.State.Acceptable if text and D.a_rank_percent_valid(int(text)) else QValidator.State.Intermediate), text, pos

    def keep_refused_text(self, call):
        """Qt writes the last valid value back into the field when the field is left or Enter is pressed (an out-of-range / empty text is not a value). The OK of this window must still SEE what the user typed (49 / empty -> the input error),
        so the typed text is remembered in `finishing_text` while Qt interprets it (editingFinished is emitted inside) and put back afterwards. A valid value is not touched."""
        edit = self.lineEdit()
        raw = edit.text()
        self.finishing_text = raw
        try:
            call()
        finally:
            self.finishing_text = None
        if edit.text() != raw and D.a_rank_text_allowed(raw) and not (raw and D.a_rank_percent_valid(int(raw))):
            blocked = edit.blockSignals(True)
            edit.setText(raw)
            edit.blockSignals(blocked)

    def focusOutEvent(self, event):
        self.keep_refused_text(lambda: QSpinBox.focusOutEvent(self, event))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.keep_refused_text(lambda: QSpinBox.keyPressEvent(self, event))
        else:
            QSpinBox.keyPressEvent(self, event)

    def resizeEvent(self, event):
        QSpinBox.resizeEvent(self, event)
        self.place_arrow_buttons()

    def wheelEvent(self, event):
        if self.hasFocus():
            QSpinBox.wheelEvent(self, event)
        else:
            event.ignore()


CHECKBOX_INDICATOR_LOGICAL = 13                                    # logical px: the ONE size of the indicator of every check box of this window (PM_IndicatorWidth / PM_IndicatorHeight); Qt converts it to device pixels at every scale (Owner contract 2026-11-11)
CHECKBOX_OPTICAL_LIFT = 0.5                                        # logical px: one extra lift of the label of every check box (every item, state and scale); Owner contract 2026-11-10: 0.5, shared by every item / state / scale / column
PRESET_OPTICAL_LIFT = 1.0                                          # logical px: the one extra lift of the text of the three preset buttons (the buttons have a shadow on the right and below); the same for every button, scale and state (Owner choice: candidate C of the comparison)
TIE_MARGIN = 1e-6                                                 # float noise margin of the tie rule in optical_dy
INK_SHARE = 0.6                                                   # a row belongs to the ink when it has a pixel with at least this share of the strongest text contrast
                                                  # a pixel with at least this alpha counts as ink when the label is measured
ROW_SPACING = 0                                                   # the one vertical spacing of every item row of both columns


def use_native_style():
    """The native Windows drawing of the standard widgets (check boxes, spin box) as the application style (Qt owns it); the other styles take the accent colour of the system theme (a dark slate here). Only the process of this window is affected."""
    app = QApplication.instance()
    if app is not None and "windowsvista" in [k.lower() for k in QStyleFactory.keys()] and app.style().objectName().lower() != "windowsvista":
        app.setStyle("windowsvista")


WINDOW_MARGIN = 12                                                # margins of the window / the columns (Qt layout units; they follow the Windows scale)
OK_INSET = 1                                                      # the native OK button is painted one row inside its widget rect (top and bottom)
OUTER_GAP = WINDOW_MARGIN - OK_INSET                               # N2 / N3: the layout gap frame -> OK button and OK button -> window bottom; with the inset the painted gaps equal the one above the frame (N1 = WINDOW_MARGIN)
ROW_INK_BELOW = 4                                                 # logical px from the visible bottom (indicator / text ink) of a check box row to the bottom of its widget rect (measured: 4 at the four Windows scales): the bottom margin M' is counted to the VISIBLE bottom
COLUMN_MARGIN_X = 12
COLUMN_MARGIN_Y = 8                                               # the top pad row of the grid (as before U5): the ink of the headings stands HEADING_INK_OFFSET lower
HEADING_INK_OFFSET = 3                                           # logical px from the top of a bold heading label to the top of its ink (measured, Yu Gothic UI 9 pt)
INNER_MARGIN = COLUMN_MARGIN_Y + HEADING_INK_OFFSET               # M': the natural margin inside the frame, measured before U5 (inner top edge of the frame -> ink top of the headings = 11 logical px). The bottom of the timing row stands M' above the bottom of the frame
EASY_SECTION_RAISE = 1                                            # logical px: the heading of the easy settings and the three buttons stand this much higher than the grid row of the last environment row, so that the ink centres of 勾配 and 簡単設定 are one (U5-2; the upper blocks stay where they stood)
RANK_ROW_RAISE = 1                                                # logical px: the A-rank row (label + spin box + label, as ONE row) stands this much higher than the row of the timing item, so that both bottom rows stand at the same visual height; the timing item itself does not move (its pixel phase stays)
FRAME_BOTTOM_RAISE = 1                                            # logical px: the whole lower structure (bottom of the frame, the note / OK row, the OK button, the bottom of the window) stands this much higher: the dialog is this much lower; the outer margins N2 / N3 keep their relation
LOWER_GAP = 6                                                    # the gap between the buttons row and the lower row (timing item / A boundary)
A_RANK_TEXT_LIFT_MARGIN = 1                                        # logical px of bottom margin of the inner line edit: raises the number by half of it; Owner contract 2026-11-10, shared by every scale / value / state
A_RANK_SPIN_WIDTH = 52                                             # candidate nearest to the proposal image 5 (preview comparison: 48 / 52 / 56 / 64); not a final contract
OK_TEXT_LIFT = 1                                                  # px the text of OK is lifted (preview comparison: 0 / 1 / 2); not a final contract
NOTE_LIFT = 2                                                     # px of bottom margin = the text moves up by half of it
PRESET_SPACING = 12
PRESET_TOP_GAP = 2                                                # between the text of the heading of the easy settings and the buttons
PRESET_RIGHT_GAP = 0
SECTION_GAP = 10                                                  # the gap between the upper and the lower region of a column
PRESET_FONT_SCALE = 1.5                                           # the text of the three preset buttons relative to the system font


def optical_dy(target_centre, ink_edges, scale):
    """How far (logical px, a whole number of device pixels) a label has to move so that the centre of its ink lies on target_centre. ink_edges = (first, last + 1) pixel row of the ink in device pixels; scale = device pixels per logical pixel. Computed at every paint from what is really drawn: no fixed value."""
    if ink_edges is None:
        return 0.0
    shift = (target_centre - (ink_edges[0] + ink_edges[1]) / 2.0 / scale) * scale          # device pixels
    whole = math.ceil(abs(shift) - 0.5 - TIE_MARGIN)                                         # round to the nearest whole device pixel; an exact half is rounded towards zero (never past the measured offset)
    return math.copysign(max(whole, 0), shift) / scale


def painted_ink_rows(size, scale, font, paint):
    """The rows (device pixels) that the label really covers. paint(painter) draws the label with the unchanged native drawing on an opaque probe image of the widget size, once on white and once on black (the text may be dark or light); the image with the stronger text is used and the ink rows are the rows with a pixel of at least INK_SHARE of that strongest contrast. The probe is opaque so that the text is rasterised like on the real widget."""
    best = None
    for background in (Qt.GlobalColor.white, Qt.GlobalColor.black):
        image = QImage(int(math.ceil(size.width() * scale)), int(math.ceil(size.height() * scale)), QImage.Format.Format_RGB32)
        image.setDevicePixelRatio(scale)                            # the probe image has the scale of the real device, so that the text is rasterised like the real one
        image.fill(background)
        painter = QPainter(image)
        painter.setFont(font)
        paint(painter)
        painter.end()
        reference = QColor(background).lightness()
        rows = [max((abs(QColor(image.pixel(x, y)).lightness() - reference) for x in range(image.width())), default=0) for y in range(image.height())]
        if best is None or max(rows) > max(best):
            best = rows
    peak = max(best)
    if peak <= 0:
        return None
    covered = [y for y, strength in enumerate(best) if strength >= INK_SHARE * peak]
    return (covered[0], covered[-1] + 1)


class OpticalStyle(QProxyStyle):
    """The native style with two changes for the check boxes of this window: (1) the indicator is ONE logical size (CHECKBOX_INDICATOR_LOGICAL, through PM_IndicatorWidth / PM_IndicatorHeight; the native style keeps the
    theme glyph table and truncates the metric at some scales), (2) the label is moved so that the ink of the text is centred on the indicator. Nothing is drawn here except that label shift: the indicator, its states (checked, unchecked,
    disabled, hover), the focus frame and every other metric come from the native style."""

    def __init__(self, base):
        QProxyStyle.__init__(self, base)
        self.setObjectName("windowsvista")
        self.known = {}

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight):
            return CHECKBOX_INDICATOR_LOGICAL
        return QProxyStyle.pixelMetric(self, metric, option, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element != QStyle.ControlElement.CE_CheckBoxLabel or widget is None:
            return QProxyStyle.drawControl(self, element, option, painter, widget)
        scale = painter.deviceTransform().m11()
        whole = QStyleOptionButton()
        whole.initFrom(widget)
        indicator = self.subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, whole, widget)
        key = (option.text, widget.font().key(), option.rect.getRect(), widget.size().width(), widget.size().height(), scale)
        if key not in self.known:
            self.known[key] = painted_ink_rows(widget.size(), scale, widget.font(), lambda p: QProxyStyle.drawControl(self, element, option, p, widget))
        shift = optical_dy(indicator.top() + indicator.height() / 2.0 - CHECKBOX_OPTICAL_LIFT, self.known[key], scale)      # the centre of the indicator, raised by the one extra optical lift shared by every check box
        painter.save()
        painter.translate(0, shift)
        QProxyStyle.drawControl(self, element, option, painter, widget)
        painter.restore()


class OpticalPresetButton(QPushButton):
    """A preset button: the background, the frame and the colours are painted by the current style (and its style sheet) as before; only the label is painted shifted so that the ink of the text is centred on the button."""

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        label = QStyleOptionButton(option)
        label.rect = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        scale = painter.deviceTransform().m11()
        ink = painted_ink_rows(self.size(), scale, self.font(), lambda p: self.style().drawControl(QStyle.ControlElement.CE_PushButtonLabel, label, p, self))
        shift = optical_dy(self.rect().height() / 2.0 - PRESET_OPTICAL_LIFT, ink, scale)      # the centre of the button, raised by the one extra optical lift (the buttons have a shadow on the right and below)
        painter.drawControl(QStyle.ControlElement.CE_PushButtonBevel, option)
        painter.save()
        try:
            painter.translate(0, shift)
            painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, label)
        finally:
            painter.restore()


def _column_title(text):
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def build_dialog(defaults, save):
    """The window for `defaults` (an InitialDefaults). save(InitialDefaults) is called by OK; it raises on failure (the window then stays open)."""
    dialog = QDialog()                                             # a plain dialog: Windows draws its standard title bar (no colour is set for it)
    dialog.setObjectName("initial_defaults_dialog")
    dialog.setWindowTitle(TITLE)
    # title text and the standard close button only: without the system-menu hint Windows shows no application icon on the title bar (this dialog only; no other window / the application icon is touched)
    dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.CustomizeWindowHint)
    use_native_style()
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, palette.color(QPalette.ColorRole.Base))   # the standard light window colour of the Windows UI (the BVE settings window), taken from the palette: no RGB value is written here
    dialog.setPalette(palette)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(WINDOW_MARGIN, WINDOW_MARGIN, WINDOW_MARGIN, OUTER_GAP)
    root.setSpacing(OUTER_GAP)
    frame = QFrame()                                               # ONE thin outer frame around both columns (not a QGroupBox per section)
    frame.setObjectName("outer_frame")
    frame.setFrameShape(QFrame.Shape.Box)
    frame.setFrameShadow(QFrame.Shadow.Plain)
    frame.setLineWidth(1)
    root.addWidget(frame)
    grid = QGridLayout(frame)                                      # ONE grid for both columns: the rows that must line up (the last environment row and the heading of the easy settings, the timing item and the A boundary row) share a grid row
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)
    # columns: 0 pad | 1 left | 2 pad | 3 divider | 4 pad | 5 right | 6 pad ; rows: 0 top pad | 1 headings | 2..9 item rows | 10 buttons / timing heading | 11 gap | 12 timing item / A boundary | 13 bottom pad
    LAST_ROW = 13
    for col in (0, 6):
        grid.setColumnMinimumWidth(col, COLUMN_MARGIN_X)
    for col in (2, 4):                                            # the divider line takes one pixel of the 3-pixel divider on each side: so the visible gap divider -> first button equals the gap last button -> frame (both 12)
        grid.setColumnMinimumWidth(col, COLUMN_MARGIN_X - 1)
    grid.setColumnStretch(1, 1)                                    # the right column keeps only the width its content needs (the three buttons): the extra width of the window goes to the left column
    grid.setColumnStretch(5, 0)
    grid.setRowMinimumHeight(0, COLUMN_MARGIN_Y)
    grid.setRowMinimumHeight(11, LOWER_GAP)
    divider = QWidget()                                            # no centre divider line is drawn; its 3 px column is kept as empty space so that no other geometry moves
    divider.setObjectName("divider_space")
    divider.setFixedWidth(3)
    grid.addWidget(divider, 0, 3, LAST_ROW + 1, 1)

    vcenter = Qt.AlignmentFlag.AlignVCenter
    grid.addWidget(_column_title("環境設定"), 1, 1, vcenter)
    env_boxes = []
    for index, label in enumerate(ENV_LABELS):
        box = QCheckBox(label)
        box.setObjectName("env_%d" % index)
        box.setChecked(bool(defaults.environment[index]))
        grid.addWidget(box, 2 + index, 1, vcenter)
        env_boxes.append(box)
    grid.addWidget(_column_title("採時駅設定"), 10, 1, 2, 1, Qt.AlignmentFlag.AlignBottom)   # spans the buttons row and the gap row: its text sits right above the item (measured: the gap below the heading equals the gap below the heading of the environment settings as far as the layout allows)
    timing = QCheckBox(TIMING_LABEL)
    timing.setObjectName("timing")
    timing.setChecked(bool(defaults.all_changeable_non_timed_to_timed))
    grid.addWidget(timing, 12, 1, vcenter)

    grid.addWidget(_column_title("減点項目設定"), 1, 5, vcenter)
    p = defaults.penalties
    pen_state = {"pen_rolling": p.rolling, "pen_safety": False, "pen_speed": p.speed_limit_exceeded, "pen_shock": p.stop_shock, "pen_eb": p.emergency_brake, "pen_init": p.initial_release_brake == "on1"}
    for index, (name, label) in enumerate(PENALTY_LABELS):
        box = FixedOffCheckBox(label) if name == "pen_safety" else QCheckBox(label)
        box.setObjectName(name)
        box.setChecked(bool(pen_state[name]))
        if name == "pen_safety":
            box.setEnabled(False)                                  # the beta has no safety device scoring: OFF and not operable, drawn by the style as disabled (grey); no preset enables it
        grid.addWidget(box, 2 + index, 5, vcenter)
    easy_title = _column_title("簡単設定")
    easy_title.setContentsMargins(0, 0, 0, 2 * EASY_SECTION_RAISE)   # the text moves up by half of the bottom margin (like NOTE_LIFT); the heading stays in the same grid row as the last environment row (勾配)
    grid.addWidget(easy_title, 9, 5, vcenter)
    preset_row = QHBoxLayout()
    preset_row.setSpacing(PRESET_SPACING)
    preset_row.setContentsMargins(0, PRESET_TOP_GAP - EASY_SECTION_RAISE, PRESET_RIGHT_GAP, EASY_SECTION_RAISE)    # the first button starts at the left edge of the right column content; the buttons rise with the heading (the row keeps its height: nothing below moves), so the heading -> button gap is unchanged
    preset_buttons = []
    for key, label, colour in PRESET_BUTTONS:                      # the EXISTING colour constants of config.py (the colours of the F1 page and the HUD): no new RGB value
        button = OpticalPresetButton(label)
        button.setObjectName("preset_" + key)
        font = button.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * PRESET_FONT_SCALE)     # relative to the system font: it follows the Windows scale like every other text
        button.setFont(font)
        button.setStyleSheet("background-color: rgb(%d, %d, %d); color: white;" % tuple(colour[:3]))
        button.setMinimumSize(80, 36)
        preset_row.addWidget(button, 1)
        preset_buttons.append((key, button))
    grid.addLayout(preset_row, 10, 5)
    rank_row = QHBoxLayout()                                       # one horizontal group, centred in the right column
    rank_row.setSpacing(4)
    rank_row.addStretch(1)
    rank_row.addWidget(QLabel("Aランクは理論値の"))
    spin = FocusWheelSpinBox()
    spin.setObjectName("a_rank")
    spin.setFixedWidth(A_RANK_SPIN_WIDTH)                          # a two-digit field (the value is always 50..90); the height stays the style's 22 px
    spin.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)   # standard alignment: centred in the edit field (without the up/down buttons)
    spin.setMaximumHeight(spin.sizeHint().height())                 # the style's own height, read before the margin below (which would otherwise make the box one pixel taller); an upper bound only
    spin.lineEdit().setTextMargins(0, 0, 0, A_RANK_TEXT_LIFT_MARGIN)   # the optical lift of the number (the native buttons and the box size are not affected)
    spin.setRange(D.A_RANK_MIN_PERCENT, D.A_RANK_MAX_PERCENT)
    spin.setValue(defaults.a_rank_percent if D.a_rank_percent_valid(defaults.a_rank_percent) else D.A_RANK_BUILTIN_PERCENT)
    rank_row.addWidget(spin)
    rank_row.addWidget(QLabel("%以上"))
    rank_row.addStretch(1)
    rank_row.setContentsMargins(0, 0, 0, RANK_ROW_RAISE)           # the row is bottom aligned in the gap row + the bottom row: its bottom margin raises the whole row (label, spin box, label) by RANK_ROW_RAISE
    grid.addLayout(rank_row, 11, 5, 2, 1, Qt.AlignmentFlag.AlignBottom)
    below_timing = (spin.maximumHeight() - timing.sizeHint().height()) - (spin.maximumHeight() - timing.sizeHint().height()) // 2    # the space under the timing item when it is centred in a row as high as the spin box
    grid.setRowMinimumHeight(12, spin.maximumHeight())               # the bottom row keeps the height it had when the A-rank row lived in it: the timing item stays centred (its place and pixel phase do not change)
    grid.setRowMinimumHeight(LAST_ROW, INNER_MARGIN - below_timing - ROW_INK_BELOW - FRAME_BOTTOM_RAISE)  # the VISIBLE bottom (indicator / text ink) of the timing row -> inner bottom of the frame = M'

    def apply_preset(key):
        """The six deductions and the A boundary of the preset (initial_defaults.apply_preset: the data of the model). The environment, the all-timing setting and the safety intervention are not touched."""
        penalties, percent = D.PRESETS[key]
        values = {"pen_rolling": penalties.rolling, "pen_speed": penalties.speed_limit_exceeded, "pen_shock": penalties.stop_shock, "pen_eb": penalties.emergency_brake, "pen_init": penalties.initial_release_brake == "on1"}
        for object_name, value in values.items():
            dialog.findChild(QWidget, object_name).setChecked(bool(value))
        spin.setValue(percent)
        spin.lineEdit().setText(str(percent))                      # the field shows the preset value even when its text was an unconfirmed input (setValue alone keeps the text when the value did not change)
        set_reason("input_error", False)                         # a preset ends the input error (the A boundary is a valid value again)

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

    bottom = QHBoxLayout()                                         # the note (left) and OK (right) on ONE row
    bottom.setSpacing(8)                                           # the horizontal spacing this row always had (it inherited the 8 of the root layout, which is now the vertical gap OUTER_GAP): the window width does not change
    note = QLabel(NOTE)
    note.setObjectName("note")
    note.setContentsMargins(0, 0, 0, NOTE_LIFT)                    # the CJK text of the note looks lower than the Latin "OK" of the button: lift it by the measured amount
    message = QLabel("")
    message.setObjectName("message")
    message.setContentsMargins(0, 0, 0, NOTE_LIFT)                 # the error text sits on the same text line as the note (measured by ink centre / baseline); only this label moves, not the row
    message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)   # a message never widens the window: it uses the free space of the bottom row (between the note and OK)
    message.setMinimumWidth(max(message.fontMetrics().horizontalAdvance(text) for text in (SAVE_FAILED, A_RANK_INVALID)))   # room for the longest message, reserved from the start: showing a message never changes the layout
    message.setStyleSheet("color: rgb(%d, %d, %d);" % tuple(config.COLOR_B_EMG[:3]))
    ok = QPushButton("OK")
    ok.setObjectName("ok")
    ok.setDefault(True)
    if OK_TEXT_LIFT:                                               # only the text of OK moves up: the padding changes the content rect, the native look stays; the button keeps the size the style gave it
        native_size = ok.sizeHint()
        ok.setStyleSheet("QPushButton { padding-bottom: %dpx; }" % (2 * OK_TEXT_LIFT))
        ok.setFixedSize(native_size)
    bottom.addWidget(note)
    bottom.addWidget(message, 1)
    bottom.addWidget(ok)
    root.addLayout(bottom)

    # TWO independent reasons share the one lower-left message area; they are never one internal reason. The save failure has the priority over the input error.
    reasons = {"input_error": False, "save_failed": False}

    def refresh_message():
        message.setText(SAVE_FAILED if reasons["save_failed"] else (A_RANK_INVALID if reasons["input_error"] else ""))

    def set_reason(name, on):
        reasons[name] = bool(on)
        refresh_message()

    def on_spin_finished():
        """A valid 50..90 typed and confirmed (the field left / Enter) ends the input error. Leaving the field with anything else shows nothing: the error appears only at OK."""
        text = spin.finishing_text if spin.finishing_text is not None else spin.lineEdit().text()      # what was typed (Qt has already written the last valid value back when it emits this signal)
        if text and D.a_rank_text_allowed(text) and D.a_rank_percent_valid(int(text)):
            set_reason("input_error", False)

    spin.editingFinished.connect(on_spin_finished)

    def on_ok():
        set_reason("save_failed", False)                           # a new attempt: the previous save failure is judged again
        text = spin.lineEdit().text() if spin.lineEdit() is not None else str(spin.value())
        percent, corrected = D.normalize_a_rank_percent(text) if text else (D.A_RANK_BUILTIN_PERCENT, True)
        if corrected:                                              # out of range / empty / not an ASCII integer: the field goes back to 60, NOTHING is saved, the window stays open, the field has the focus again
            spin.setValue(percent)
            spin.lineEdit().setText(str(percent))
            spin.setFocus()
            spin.selectAll()
            set_reason("input_error", True)
            return
        spin.setValue(percent)
        try:
            save(collect(dialog))
        except (ValueError, D.SaveError, OSError):
            set_reason("save_failed", True)
            return
        reasons["input_error"] = reasons["save_failed"] = False
        refresh_message()
        dialog.accept()

    ok.clicked.connect(lambda checked=False: on_ok())
    native_base = QStyleFactory.create("windowsvista")             # the optical style of the check boxes: owned by the dialog, created last so that it is destroyed after the widgets that use it
    if native_base is not None:
        optical = OpticalStyle(native_base)
        optical.setParent(dialog)
        for box in dialog.findChildren(QCheckBox):
            box.setStyle(optical)
    apply_spin_focus_style(dialog, spin)
    apply_selection_colours(dialog, spin.lineEdit())
    apply_spin_arrow_buttons(dialog, spin)
    dialog.resize(dialog.sizeHint())                              # the size the content needs (Qt layout); nothing is fixed in pixels
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
        app = QApplication.instance() or QApplication(list(argv[:1]))      # kept until run() returns: a dropped QApplication is destroyed at once (Qt fail-fast 0xC0000409 at the next widget)
        dialog = build_dialog(result.defaults, save=lambda value: D.save(value, path))
        (exec_fn or (lambda d: d.exec()))(dialog)
        return 0
    finally:
        holder.release()
