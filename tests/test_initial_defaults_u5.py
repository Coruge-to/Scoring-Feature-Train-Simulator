"""INITIAL-DEFAULTS U5, REVISED CONTRACT (Owner 2026-11-11, after the preview of the first U5): outer margins, section heights and the two bottom rows of the 'initial defaults' window.

M'  (inner margin, top)    the natural top margin of the window BEFORE U5 (inner top edge of the frame -> ink top of 「環境設定」 = 「減点項目設定」; measured on the baseline: 11 / 14 / 16 / 18 device px at 100 / 125 / 150 / 175 %, logical 11).
                            The upper blocks therefore stand where they stood before U5 (QCheckBox pixel phase unchanged). The first U5 rule 'top margin = M (the horizontal margin 12)' is WITHDRAWN.
B   (inner margin, bottom) the VISIBLE bottom of the timing QCheckBox row (union of the indicator ink and the text ink, not the widget rect) -> inner bottom edge of the frame = M'. The timing item stands where it stood before U5; only the bottom of the frame moves.
N1 = N2 = N3 (outer margins) N1 title bar bottom -> top line of the frame / N2 bottom line of the frame -> painted top of the OK button / N3 painted bottom of the OK button -> bottom of the window. The note text and the 「OK」 text share their ink centre Y (OK internals untouched).
L / R                      indicator left edge of the left column (8 environment items + timing item, one X) -> inner left edge = right edge of the 上級 button INCLUDING its shadow -> inner right edge. L = R (or within 1 device px): the width is not touched.
U5-2                       ink centre of 「勾配」 = ink centre of 「簡単設定」 (heading, three buttons and the A-rank row move together; their internal gaps stay).
U5-3                       the timing row and the A-rank row stand at the same visual height (the A-rank row moves up by RANK_ROW_RAISE, the timing item does not); the baselines are within 1 device px (priority), the visual (bounding box) centres within 2 (measured at the four real scales: baseline +1/0/0/0, centre +1.5/+1/+1/+2).
Spin                       the up / down button geometry is NOT changed in this stage (centred within 0..0.5 device px already).
RED = fails on the tree of the FIRST U5 (variant B, 315c9d5 + the first U5 diff). Messages start with 'U5-RED' (a missing contract) or 'U5-GUARD' (a contract that already holds and must stay).
The ink measurements render the REAL window (QWidget.grab) at the scale of the test process; the four REAL Windows scales (100 / 125 / 150 / 175 %) are measured by the external probe of the deliverable.
Numbers marked NATIVE FONT are measured with Yu Gothic UI 9 pt on Windows at 100 % (the Owner's machine); they are skipped when another font is in use."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import idf1_red_support as X  # noqa: E402

ROOT = X.ROOT

M_PRIME = 11            # logical px, the natural top margin before U5 (ink top of the headings below the inner top edge of the frame)
BASELINE_ENV_0_TOP = 37     # dialog coordinates at 100 % before U5
BASELINE_SLOPE_TOP = 177
BASELINE_TIMING_TOP = 242
BASELINE_DIALOG_WIDTH = 562




def R(widget):
    """the rect of a widget in the coordinates of its window (all the widgets of the grid are children of the frame)"""
    from PyQt6.QtCore import QRect, QPoint
    return QRect(widget.mapTo(widget.window(), QPoint(0, 0)), widget.size())


def setUpModule():
    X.redirect_profile("ts-u5-")


def tearDownModule():
    X.restore_profile()


def module_source():
    return X.source("initial_defaults_ui.py")


class Ink(object):
    """The rendered window (grab) and its ink measurements in DEVICE pixels (bounding boxes are inclusive)."""

    def __init__(self, dialog):
        from PyQt6.QtGui import QImage
        pixmap = dialog.grab()
        self.dpr = pixmap.devicePixelRatio()
        self.image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
        self.bg = self.image.pixel(1, 1) & 0xFFFFFF

    def dev(self, value):
        return int(round(value * self.dpr))

    def bbox(self, rect, thresh=70, grow=0):
        """rect = QRect in logical dialog coordinates; returns (x0, y0, x1, y1) of the pixels that differ from the background by more than thresh, or None."""
        x0, y0 = self.dev(rect.left()) - grow, self.dev(rect.top()) - grow
        x1, y1 = self.dev(rect.right() + 1) + grow, self.dev(rect.bottom() + 1) + grow
        bgr, bgg, bgb = (self.bg >> 16) & 255, (self.bg >> 8) & 255, self.bg & 255
        xs, ys = [], []
        for y in range(max(0, y0), min(self.image.height(), y1)):
            for x in range(max(0, x0), min(self.image.width(), x1)):
                p = self.image.pixel(x, y)
                if max(abs(((p >> 16) & 255) - bgr), abs(((p >> 8) & 255) - bgg), abs((p & 255) - bgb)) > thresh:
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class Layout(X.DialogBase):
    def native_font_only(self):
        from PyQt6.QtWidgets import QApplication
        family = QApplication.font().family()
        platform = QApplication.platformName()
        if not (platform == "windows" and family == "Yu Gothic UI"):
            self.skipTest("NATIVE FONT: needs Windows with Yu Gothic UI (this run: %s / %s)" % (platform, family))

    def widgets(self, d):
        from PyQt6.QtWidgets import QCheckBox, QLabel
        by_name = {w.objectName(): w for w in d.findChildren(QCheckBox)}
        labels = {w.text(): w for w in d.findChildren(QLabel) if w.text()}
        return by_name, labels

    def frame_inner(self, d):
        r = self.find(d, "outer_frame").geometry()
        return r.left() + 1, r.top() + 1, r.right() - 1, r.bottom() - 1            # inclusive logical px (the frame line is 1 px)

    def metrics(self, d):
        boxes, labels = self.widgets(d)
        ink = Ink(d)
        il, it, ir, ib = [ink.dev(v) for v in self.frame_inner(d)]
        env = ink.bbox(R(labels["環境設定"]))
        pen = ink.bbox(R(labels["減点項目設定"]))
        advanced = R(self.find(d, "preset_advanced"))
        return {"ink": ink, "inner": (il, it, ir, ib), "env": env, "pen": pen, "R": ir - ink.dev(advanced.right()),
                "top_env": env[1] - it, "top_pen": pen[1] - it}

    def indicator_left_ink(self, d, ink, name):
        from PyQt6.QtCore import QRect
        g = R(self.widgets(d)[0][name])
        b = ink.bbox(QRect(g.left(), g.top(), 18, g.height()), thresh=20)
        return b[0]

    # ================================================================ L / R and the width (guards)
    def test_l_the_indicators_of_the_left_column_share_one_x_and_l_equals_r(self):
        self.native_font_only()
        d = self.make()
        m = self.metrics(d)
        ink = m["ink"]
        xs = {name: self.indicator_left_ink(d, ink, name) for name in ["env_%d" % i for i in range(8)] + ["timing"]}
        self.assertEqual(len(set(xs.values())), 1, "U5-GUARD: the indicator left edges differ %r" % xs)
        left = list(xs.values())[0] - m["inner"][0]
        self.assertLessEqual(abs(left - m["R"]), 1, "U5-GUARD: L %d / R %d" % (left, m["R"]))

    def test_l_the_width_of_the_window_and_of_the_frame_is_unchanged(self):
        self.native_font_only()
        d = self.make()
        self.assertEqual(d.width(), BASELINE_DIALOG_WIDTH, "U5-GUARD: the window width changed (%d)" % d.width())
        grid = self.find(d, "outer_frame").layout()
        U = self.U
        self.assertEqual((grid.columnMinimumWidth(0), grid.columnMinimumWidth(6), grid.columnMinimumWidth(2), grid.columnMinimumWidth(4)), (U.COLUMN_MARGIN_X, U.COLUMN_MARGIN_X, U.COLUMN_MARGIN_X - 1, U.COLUMN_MARGIN_X - 1), "U5-GUARD: column paddings")
        self.assertEqual(R(self.find(d, "outer_frame")).width(), d.width() - 2 * U.WINDOW_MARGIN, "U5-GUARD: the frame spans the window width")

    def test_m_the_headings_of_the_two_columns_stand_at_the_same_height(self):
        d = self.make()
        m = self.metrics(d)
        self.assertEqual(m["env"][1], m["pen"][1], "U5-GUARD: heading ink top env %d / pen %d" % (m["env"][1], m["pen"][1]))
        self.assertEqual(m["env"][3], m["pen"][3], "U5-GUARD: heading ink bottom")

    # ================================================================ M' : the top margin and the upper blocks (restored to the baseline)
    def test_mprime_the_top_margin_of_the_environment_heading_is_the_natural_one(self):
        self.native_font_only()
        d = self.make()
        m = self.metrics(d)
        self.assertEqual(m["top_env"], M_PRIME, "U5-RED: inner top -> ink top of 環境設定 = %d px, M' = %d px" % (m["top_env"], M_PRIME))

    def test_mprime_the_top_margin_of_the_deduction_heading_is_the_natural_one(self):
        self.native_font_only()
        d = self.make()
        m = self.metrics(d)
        self.assertEqual(m["top_pen"], M_PRIME, "U5-RED: inner top -> ink top of 減点項目設定 = %d px, M' = %d px" % (m["top_pen"], M_PRIME))

    def test_mprime_the_upper_blocks_stand_where_they_stood_before_u5(self):
        self.native_font_only()
        d = self.make()
        boxes, _ = self.widgets(d)
        got = (R(boxes["env_0"]).top(), R(boxes["pen_rolling"]).top(), R(boxes["env_7"]).top())
        self.assertEqual(got, (BASELINE_ENV_0_TOP, BASELINE_ENV_0_TOP, BASELINE_SLOPE_TOP), "U5-RED: tops of env_0 / pen_rolling / env_7 = %r (the QCheckBox pixel phase of the baseline needs %r)" % (got, (BASELINE_ENV_0_TOP, BASELINE_ENV_0_TOP, BASELINE_SLOPE_TOP)))

    def test_mprime_the_top_pad_row_is_the_natural_one(self):
        d = self.make()
        grid = self.find(d, "outer_frame").layout()
        self.assertEqual(grid.rowMinimumHeight(0), M_PRIME - 3, "U5-RED: top pad row %d (the baseline pad is %d, the heading ink starts 3 px below the label top)" % (grid.rowMinimumHeight(0), M_PRIME - 3))

    def test_mprime_the_upper_rows_keep_their_pitch_and_height(self):
        d = self.make()
        boxes, _ = self.widgets(d)
        env = [boxes["env_%d" % i] for i in range(8)]
        pen = [boxes[n] for n in ("pen_rolling", "pen_safety", "pen_speed", "pen_shock", "pen_eb", "pen_init")]
        for group in (env, pen):
            heights = {b.geometry().height() for b in group}
            self.assertEqual(len(heights), 1, "U5-GUARD: row heights %r" % heights)
            for a, b in zip(group, group[1:]):
                self.assertEqual(b.geometry().top() - a.geometry().top(), a.geometry().height(), "U5-GUARD: pitch of %s / %s" % (a.objectName(), b.objectName()))
        self.assertEqual(env[0].geometry().height(), env[0].sizeHint().height(), "U5-GUARD: a row is stretched")

    # ================================================================ B : the bottom of the timing row -> the inner bottom edge = M'
    def test_b_the_visible_bottom_of_the_timing_row_is_the_natural_margin_above_the_frame_bottom(self):
        """NATIVE FONT: the union of the indicator ink and the text ink of the timing item (not the widget rect) -> inner bottom of the frame = M'."""
        self.native_font_only()
        d = self.make()
        boxes, _ = self.widgets(d)
        ink = Ink(d)
        _, _, _, ib = [ink.dev(v) for v in self.frame_inner(d)]
        vis = ink.bbox(R(boxes["timing"]), thresh=30, grow=1)
        gap = ib - vis[3]
        self.assertEqual(gap, M_PRIME - 1, "U5-RED: visible bottom of the timing row -> inner bottom of the frame = %d px; the whole lower structure is lifted by 1 logical px: M' - 1 = %d px" % (gap, M_PRIME - 1))

    def test_b_the_timing_item_stands_where_it_stood_before_u5(self):
        self.native_font_only()
        d = self.make()
        boxes, _ = self.widgets(d)
        self.assertEqual(R(boxes["timing"]).top(), BASELINE_TIMING_TOP, "U5-RED: timing top %d (the baseline QCheckBox phase needs %d)" % (R(boxes["timing"]).top(), BASELINE_TIMING_TOP))

    def test_b_there_is_no_bottom_row_drop_any_more(self):
        self.assertFalse(hasattr(self.U, "BOTTOM_ROW_DROP"), "U5-GUARD: BOTTOM_ROW_DROP is back (the timing item must not be moved)")

    # ================================================================ N : the outer margins
    def outer_margins(self, d):
        ink = Ink(d)
        frame = self.find(d, "outer_frame").geometry()
        n1 = ink.dev(frame.top())                                                     # blank rows between the title bar (client top = 0) and the top line of the frame
        n2_frame_bottom_line = ink.dev(frame.bottom() + 1) - 1
        ok = ink.bbox(R(self.find(d, "ok")), thresh=6, grow=3)                          # the painted OK button (one row inside its widget rect)
        n2 = ok[1] - n2_frame_bottom_line - 1                                          # blank rows between the bottom line of the frame and the painted top of the OK button
        n3 = ink.image.height() - 1 - ok[3]                                            # blank rows between the painted bottom of the OK button and the bottom of the window
        return n1, n2, n3, ok, ink

    def test_n_the_three_outer_vertical_margins_are_equal(self):
        self.native_font_only()
        d = self.make()
        n1, n2, n3, _, _ = self.outer_margins(d)
        self.assertEqual((n2, n3), (n1, n1), "U5-RED: N1 (title bar -> frame) %d / N2 (frame -> OK button) %d / N3 (OK button -> window bottom) %d px" % (n1, n2, n3))

    def test_n_the_lower_structure_is_lifted_by_one_logical_px(self):
        """NATIVE FONT: frame bottom, the note / OK row, the OK button and the window bottom all move up by 1 logical px (the dialog is 315 high, it was 316; the OK button stands at y = 280, it stood at 281); the width does not change."""
        self.native_font_only()
        d = self.make()
        ok = R(self.find(d, "ok"))
        self.assertEqual((d.height(), ok.top(), d.width()), (315, 280, BASELINE_DIALOG_WIDTH), "U5-RED: dialog height / OK top / width = %r (needs (315, 280, %d))" % ((d.height(), ok.top(), d.width()), BASELINE_DIALOG_WIDTH))

    def test_n_the_ok_button_and_its_text_are_untouched(self):
        """NATIVE FONT: the OK button is 75x24 logical (73x22 painted at 100 %), its text ink stands 6..14 rows below the painted top, its X is the one before U5."""
        self.native_font_only()
        d = self.make()
        n1, n2, n3, ok, ink = self.outer_margins(d)
        r = R(self.find(d, "ok"))
        self.assertEqual((r.left(), r.width(), r.height()), (475, 75, 24), "U5-GUARD: OK rect x / width / height %r" % ((r.left(), r.width(), r.height()),))
        ys = [y for y in range(ok[1] + 4, ok[3] - 3) for x in range(ok[0] + 4, ok[2] - 3) if (ink.image.pixel(x, y) & 255) < 120]
        self.assertEqual((min(ys) - ok[1], max(ys) - ok[1]), (6, 14), "U5-GUARD: the OK text ink rows inside the button")
        self.assertEqual((ok[2] - ok[0] + 1, ok[3] - ok[1] + 1), (73, 22), "U5-GUARD: painted OK size")

    def test_n_the_note_text_and_the_ok_text_share_their_ink_centre(self):
        self.native_font_only()
        d = self.make()
        n1, n2, n3, ok, ink = self.outer_margins(d)
        ys = [y for y in range(ok[1] + 4, ok[3] - 3) for x in range(ok[0] + 4, ok[2] - 3) if (ink.image.pixel(x, y) & 255) < 120]
        ok_c = (min(ys) + max(ys)) / 2.0
        nb = ink.bbox(R(self.find(d, "note")), thresh=70)
        note_c = (nb[1] + nb[3]) / 2.0
        self.assertLessEqual(abs(note_c - ok_c), 1.0, "U5-RED: note ink centre %.1f / OK text ink centre %.1f (difference %.1f device px)" % (note_c, ok_c, note_c - ok_c))

    def test_n_the_note_keeps_its_place_and_overlaps_nothing(self):
        d = self.make()
        note, ok, frame = R(self.find(d, "note")), R(self.find(d, "ok")), R(self.find(d, "outer_frame"))
        self.assertEqual(note.left(), self.U.WINDOW_MARGIN, "U5-GUARD: the note left edge")
        self.assertFalse(note.intersects(frame), "U5-GUARD: the note overlaps the frame")
        self.assertFalse(note.intersects(ok), "U5-GUARD: the note overlaps the OK button")
        self.assertTrue(note.width() >= self.find(d, "note").sizeHint().width(), "U5-GUARD: the note is clipped")

    # ================================================================ U5-2 勾配 / 簡単設定
    def test_u52_the_ink_centre_of_slope_equals_the_ink_centre_of_easy_settings(self):
        from PyQt6.QtCore import QRect
        self.native_font_only()
        d = self.make()
        boxes, labels = self.widgets(d)
        ink = Ink(d)
        slope = R(boxes["env_7"])
        text = ink.bbox(QRect(slope.left() + 18, slope.top(), slope.width() - 18, slope.height()))
        easy = ink.bbox(R(labels["簡単設定"]))
        diff = (text[1] + text[3]) / 2.0 - (easy[1] + easy[3]) / 2.0
        self.assertLessEqual(abs(diff), 0.5, "U5-RED: ink centre 勾配 %.1f / 簡単設定 %.1f (difference %.1f device px)" % ((text[1] + text[3]) / 2.0, (easy[1] + easy[3]) / 2.0, diff))

    def test_u52_the_easy_settings_block_keeps_its_internal_relations(self):
        d = self.make()
        U = self.U
        buttons = [R(self.find(d, "preset_" + k)) for k in ("beginner", "intermediate", "advanced")]
        for r in buttons:
            self.assertEqual((r.width(), r.height()), (80, 36), "U5-GUARD: preset button size")
        self.assertEqual(buttons[1].left() - buttons[0].right() - 1, U.PRESET_SPACING, "U5-GUARD: the 12 px spacing")
        self.assertEqual(buttons[2].left() - buttons[1].right() - 1, U.PRESET_SPACING, "U5-GUARD: the 12 px spacing")
        self.assertEqual(len({r.top() for r in buttons}), 1, "U5-GUARD: the buttons share one row")
        spin = R(self.find(d, "a_rank"))
        self.assertEqual(spin.top() - (buttons[0].bottom() + 1), U.LOWER_GAP, "U5-RED: the gap between the button row and the A-rank row %d (the A-rank row rises as much as the buttons: LOWER_GAP %d)" % (spin.top() - (buttons[0].bottom() + 1), U.LOWER_GAP))
        self.assertEqual(U.PRESET_OPTICAL_LIFT, 1.0)

    def test_u52_the_gap_between_the_heading_ink_and_the_buttons_is_unchanged(self):
        """NATIVE FONT: the blank rows between the ink of 簡単設定 and the top of the buttons are 6 at 100 % (measured before U5)."""
        self.native_font_only()
        d = self.make()
        _, labels = self.widgets(d)
        ink = Ink(d)
        easy = ink.bbox(R(labels["簡単設定"]))
        top = ink.dev(R(self.find(d, "preset_beginner")).top())
        self.assertEqual(top - easy[3] - 1, 6, "U5-GUARD: heading ink -> button top gap %d" % (top - easy[3] - 1))

    # ================================================================ U5-3 the two bottom rows
    def probe_texts(self, d):
        """The three bottom texts are replaced by the SAME glyphs: their ink rows are then directly comparable (baseline) whatever the real strings are."""
        from PyQt6.QtWidgets import QLabel
        boxes, labels = self.widgets(d)
        boxes["timing"].setText("国国国国国")
        spin = self.find(d, "a_rank")
        for lab in d.findChildren(QLabel):
            if lab.parent() is not spin and lab.text() in ("Aランクは理論値の", "%以上"):
                lab.setText("国国国国国")
        self.app_events()
        found = sorted([lab for lab in d.findChildren(QLabel) if lab.text() == "国国国国国"], key=lambda w: w.geometry().left())
        return boxes["timing"], found

    def test_u53_the_baselines_of_the_left_and_the_right_bottom_texts_are_equal(self):
        self.native_font_only()
        from PyQt6.QtCore import QRect
        d = self.make()
        timing, labels = self.probe_texts(d)
        ink = Ink(d)
        g = R(timing)
        left = ink.bbox(QRect(g.left() + 18, g.top(), g.width() - 18, g.height()))
        a = ink.bbox(R(labels[0]))
        pct = ink.bbox(R(labels[1]))
        self.assertEqual(a[3], pct[3], "U5-GUARD: the two right labels share the baseline")
        self.assertEqual(left[3] - a[3], 0, "U5-RED: the A-rank row is ONE row again (the place of E): the two labels stand at the height of the spin box row: timing baseline - label baseline = %d (needs 0 at 100 %%)" % (left[3] - a[3]))
        spin_ink = ink.bbox(R(self.find(d, "a_rank")), thresh=20)
        label_centre = (a[1] + a[3]) / 2.0 - (spin_ink[1] + spin_ink[3]) / 2.0
        self.assertEqual(label_centre, 0.5, "U5-RED: label ink centre - spin box centre = %.1f device px (the place of E: +0.5; candidate F had -0.5)" % label_centre)
        self.assertLessEqual(abs(left[3] - a[3]), 1, "U5-GUARD: baseline (ink bottom) timing text %d / Aランクは理論値の %d / %%以上 %d" % (left[3], a[3], pct[3]))

    def test_u53_the_a_rank_row_stands_one_logical_px_above_its_place_before_u5(self):
        """NATIVE FONT: the whole row (label + spin box + label) -> the spin box top is 240 (it was 241 before U5); the three parts move by the same amount."""
        self.native_font_only()
        d = self.make()
        _, labels = self.widgets(d)
        spin = R(self.find(d, "a_rank"))
        a, pct = R(labels["Aランクは理論値の"]), R(labels["%以上"])
        self.assertEqual(spin.top(), 240, "U5-RED: spin top %d (before U5 241; the A-rank row stands 1 logical px above it)" % spin.top())
        self.assertEqual((a.top(), pct.top()), (spin.top(), spin.top()), "U5-GUARD: the labels share the row with the spin box")

    def test_u53_the_visual_centre_of_the_timing_row_equals_the_one_of_the_a_rank_row(self):
        self.native_font_only()
        d = self.make()
        boxes, labels = self.widgets(d)
        ink = Ink(d)
        left = ink.bbox(R(boxes["timing"]), grow=1)
        parts = [ink.bbox(R(labels["Aランクは理論値の"]), grow=1), ink.bbox(R(self.find(d, "a_rank")), thresh=20, grow=1), ink.bbox(R(labels["%以上"]), grow=1)]
        right = (min(p[0] for p in parts), min(p[1] for p in parts), max(p[2] for p in parts), max(p[3] for p in parts))
        diff = (left[1] + left[3]) / 2.0 - (right[1] + right[3]) / 2.0
        self.assertLessEqual(abs(diff), 2.0, "U5-GUARD: visual centre difference %.1f device px (left %r right %r)" % (diff, left, right))

    # ================================================================ the QCheckBox rows (internals unchanged)
    def test_check_the_check_box_internals_are_identical_for_all_fifteen_items(self):
        """indicator centre -> text ink centre (device px) is the same for every item and the indicator is 13 logical px: nothing inside a check box moved (only whole rows move). NATIVE FONT."""
        self.native_font_only()
        from PyQt6.QtCore import QRect
        from PyQt6.QtWidgets import QStyle, QStyleOptionButton
        d = self.make()
        boxes, _ = self.widgets(d)
        self.assertEqual(len(boxes), 15)
        ink = Ink(d)
        relations = {}
        for name, b in boxes.items():
            opt = QStyleOptionButton()
            opt.initFrom(b)
            opt.text = b.text()
            ind = b.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, b)
            self.assertEqual((ind.width(), ind.height()), (13, 13), "U5-GUARD: %s indicator" % name)
            g = R(b)
            text_rect = QRect(g.left() + ind.right() + 3, g.top(), g.width() - ind.right() - 3, g.height())
            t = ink.bbox(text_rect)
            self.assertIsNotNone(t, "U5-GUARD: %s has no ink" % name)
            ind_centre = ink.dev(g.top() + ind.top()) + (ink.dev(ind.height()) - 1) / 2.0
            relations[name] = (t[1] + t[3]) / 2.0 - ind_centre
        enabled = {k: v for k, v in relations.items() if k != "pen_safety"}
        self.assertLessEqual(max(enabled.values()) - min(enabled.values()), 1.0, "U5-GUARD: the indicator -> text centre relation differs between the items: %r" % relations)

    def test_check_the_checked_indicator_is_what_the_native_style_draws_with_the_13_px_metric(self):
        """characterization (not a RED): the checked indicator of the product (OpticalStyle) is pixel-identical to a minimal QCheckBox whose style only answers PM_IndicatorWidth/Height = 13 on the native windowsvista style (the white check mark included). NATIVE FONT."""
        self.native_font_only()
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QCheckBox, QProxyStyle, QStyle, QStyleFactory, QStyleOptionButton

        class Plain13(QProxyStyle):
            def pixelMetric(self, metric, option=None, widget=None):
                if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight):
                    return 13
                return QProxyStyle.pixelMetric(self, metric, option, widget)

        d = self.make()
        boxes, _ = self.widgets(d)
        product = boxes["env_1"]
        style = Plain13(QStyleFactory.create("windowsvista"))
        scratch = QCheckBox("残り時間")
        scratch.setChecked(True)
        scratch.setStyle(style)
        scratch.resize(product.size())
        scratch.show()
        self.app_events()
        self.dialogs.append(scratch)
        opt = QStyleOptionButton()
        opt.initFrom(product)
        ind = product.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, product)
        a = product.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        b = scratch.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        scale = a.devicePixelRatio() or 1.0

        def box_of(image):
            """the indicator = the blue box: bounding box of the blue pixels left of the label"""
            xs, ys = [], []
            for y in range(image.height()):
                for x in range(int((ind.right() + 3) * scale)):
                    c = image.pixel(x, y)
                    if (c & 255) - ((c >> 16) & 255) > 60:
                        xs.append(x)
                        ys.append(y)
            return min(xs), min(ys), max(xs), max(ys)
        ba, bb = box_of(a), box_of(b)
        self.assertEqual((ba[2] - ba[0], ba[3] - ba[1]), (bb[2] - bb[0], bb[3] - bb[1]), "U5-GUARD: the indicator sizes differ %r / %r" % (ba, bb))
        w, h = ba[2] - ba[0] + 1, ba[3] - ba[1] + 1
        cut = int(4 * scale + 0.999)                                                  # the anti-aliased corners blend with the window colour behind the box (white in the dialog, the system grey in the scratch window): compared without them
        diffs = [(x, y) for y in range(h) for x in range(w) if not ((x < cut or x >= w - cut) and (y < cut or y >= h - cut)) and a.pixel(ba[0] + x, ba[1] + y) != b.pixel(bb[0] + x, bb[1] + y)]
        self.assertEqual(diffs, [], "U5-GUARD: the checked indicator of the product (box + white check mark) differs from the native style drawing in %d pixels" % len(diffs))

    def test_check_the_timing_item_internal_relation_equals_the_one_of_the_environment_items(self):
        self.native_font_only()
        from PyQt6.QtCore import QRect
        from PyQt6.QtWidgets import QStyle, QStyleOptionButton
        d = self.make()
        boxes, _ = self.widgets(d)
        ink = Ink(d)
        rel = {}
        for name in ("env_0", "env_7", "timing"):
            b = boxes[name]
            opt = QStyleOptionButton()
            opt.initFrom(b)
            opt.text = b.text()
            ind = b.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, b)
            g = R(b)
            t = ink.bbox(QRect(g.left() + ind.right() + 3, g.top(), g.width() - ind.right() - 3, g.height()))
            rel[name] = (t[1] + t[3]) / 2.0 - (ink.dev(g.top() + ind.top()) + (ink.dev(ind.height()) - 1) / 2.0)
        self.assertLessEqual(abs(rel["timing"] - rel["env_7"]), 0.5, "U5-GUARD: indicator -> text centre %r" % rel)

    # ================================================================ the spin box (untouched) and its button union
    def test_spin_the_button_union_is_centred_in_the_spin_box(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        up, down = spin.arrow_buttons
        top_gap = up.geometry().top() - 0
        bottom_gap = spin.height() - 1 - down.geometry().bottom()
        self.assertLessEqual(abs(top_gap - bottom_gap), 1, "U5-GUARD: spin button union gaps top %d / bottom %d" % (top_gap, bottom_gap))
        union_centre = (up.geometry().top() + down.geometry().bottom()) / 2.0
        self.assertLessEqual(abs(union_centre - (spin.height() - 1) / 2.0), 0.5, "U5-GUARD: union centre %.1f / spin centre %.1f" % (union_centre, (spin.height() - 1) / 2.0))

    def test_spin_the_spin_box_keeps_its_size_buttons_and_number_contract(self):
        d = self.make()
        U = self.U
        spin = self.find(d, "a_rank")
        self.assertEqual(spin.width(), U.A_RANK_SPIN_WIDTH, "U5-GUARD: spin width")
        self.assertEqual(U.A_RANK_SPIN_WIDTH, 52)
        self.assertEqual(U.SPIN_BUTTON_WIDTH, 16)
        self.assertEqual(U.A_RANK_TEXT_LIFT_MARGIN, 1)
        self.assertEqual(spin.height(), spin.maximumHeight(), "U5-GUARD: the style's own height")
        up, down = spin.arrow_buttons
        self.assertEqual((up.geometry().width(), down.geometry().width()), (U.SPIN_BUTTON_WIDTH, U.SPIN_BUTTON_WIDTH), "U5-GUARD: button width")
        self.assertEqual((spin.minimum(), spin.maximum()), (50, 90))
        le = spin.lineEdit().geometry()
        self.assertEqual((le.left(), le.top()), (1, 1), "U5-GUARD: edit field rect origin")

    def test_spin_the_arrow_glyphs_stay_centred_in_their_buttons(self):
        d = self.make()
        spin = self.find(d, "a_rank")
        for button in spin.arrow_buttons:
            image = button.grab().toImage()
            ys = [y for y in range(image.height()) for x in range(image.width()) if (image.pixel(x, y) & 255) < 90]
            self.assertTrue(ys, "U5-GUARD: no arrow ink in %s" % button.objectName())
            centre = (min(ys) + max(ys)) / 2.0
            self.assertLessEqual(abs(centre - (image.height() - 1) / 2.0), 1.0, "U5-GUARD: %s glyph centre %.1f / button centre %.1f" % (button.objectName(), centre, (image.height() - 1) / 2.0))

    def test_spin_the_internal_geometry_and_the_number_are_unchanged(self):
        """NATIVE FONT, behaviour of the untouched A-rank spin box at 100 %: edit field rect, the two arrow button rects and the ink rect of the number (relative to the spin box) are the ones measured before U5."""
        self.native_font_only()
        from PyQt6.QtGui import QImage
        d = self.make()
        spin = self.find(d, "a_rank")
        up, down = spin.arrow_buttons
        self.assertEqual(spin.lineEdit().geometry().getRect(), (1, 1, 50, 20), "U5-GUARD: edit field rect")
        self.assertEqual((up.geometry().getRect(), down.geometry().getRect()), ((35, 1, 16, 11), (35, 11, 16, 10)), "U5-GUARD: arrow button rects")
        image = spin.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        ink = [(x, y) for y in range(2, image.height() - 2) for x in range(2, 34) if min((image.pixel(x, y) >> 16) & 255, (image.pixel(x, y) >> 8) & 255, image.pixel(x, y) & 255) < 140]
        rect = (min(p[0] for p in ink), min(p[1] for p in ink), max(p[0] for p in ink), max(p[1] for p in ink))
        self.assertEqual(rect, (11, 7, 22, 15), "U5-GUARD: the ink rect of the number %r" % (rect,))

    def test_preset_the_buttons_and_their_text_are_unchanged(self):
        """NATIVE FONT: the three preset buttons are 80x36 and the ink of the white text stands on rows 9..24 (PRESET_OPTICAL_LIFT = 1.0)."""
        self.native_font_only()
        from PyQt6.QtGui import QImage
        d = self.make()
        for name in ("preset_beginner", "preset_intermediate", "preset_advanced"):
            button = self.find(d, name)
            self.assertEqual((button.width(), button.height()), (80, 36), "U5-GUARD: %s size" % name)
            image = button.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
            rows = [y for y in range(3, image.height() - 5) for x in range(3, image.width() - 5) if min((image.pixel(x, y) >> 16) & 255, (image.pixel(x, y) >> 8) & 255, image.pixel(x, y) & 255) > 200]
            self.assertEqual((min(rows), max(rows)), (9, 24), "U5-GUARD: %s text ink rows" % name)

    # ================================================================ constants and untouched classes
    def test_const_the_invariant_numbers(self):
        U = self.U
        self.assertEqual(U.CHECKBOX_INDICATOR_LOGICAL, 13, "U5-GUARD")
        self.assertEqual(U.CHECKBOX_OPTICAL_LIFT, 0.5, "U5-GUARD")
        self.assertEqual(U.PRESET_OPTICAL_LIFT, 1.0, "U5-GUARD")
        self.assertEqual(U.PRESET_SPACING, 12, "U5-GUARD")
        self.assertEqual(U.WINDOW_MARGIN, 12, "U5-GUARD")
        self.assertEqual(U.COLUMN_MARGIN_X, 12, "U5-GUARD")
        self.assertFalse(hasattr(U, "RANK_LABEL_RAISE"), "U5-RED: RANK_LABEL_RAISE exists (candidate F raises the two labels alone; Owner 2026-11-11: not adopted, the A-rank row is one row)")
        self.assertEqual(U.FRAME_BOTTOM_RAISE, 1, "U5-GUARD: the lower structure is raised by 1 logical px")
        self.assertEqual((U.EASY_SECTION_RAISE, U.RANK_ROW_RAISE), (1, 1), "U5-RED: the raises of the easy section / the A-rank row = %r (Owner 2026-11-11: the A-rank row stands 1 logical px above its place before U5)" % ((U.EASY_SECTION_RAISE, U.RANK_ROW_RAISE),))

    def test_const_the_layout_is_built_from_logical_numbers_only(self):
        src = module_source()
        for forbidden in ("devicePixelRatio", "logicalDpi", "physicalDpi", "screen()", "QGuiApplication.primaryScreen", "QT_SCALE_FACTOR"):
            self.assertNotIn(forbidden, src, "U5-GUARD: %s in the module (the layout stays logical)" % forbidden)


if __name__ == "__main__":
    unittest.main()
