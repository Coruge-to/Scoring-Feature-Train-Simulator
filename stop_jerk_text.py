"""停車時衝動の利用者向け文言（評価点設定ページ 1/3 の説明欄）。

Qt に依存しない純粋なデータ。1 行は (文字列, 種別) の並びで、種別は
  "normal"  通常色（白の文字＋黒の縁取り）
  "first"   第一境界（0.065G≒2.3km/h/s）の色（文字本体は STOP_JERK_FIRST_BOUNDARY_COLOR、縁取りは白）
  "second"  第二境界（0.100G≒3.5km/h/s）の色（文字本体は STOP_JERK_SECOND_BOUNDARY_COLOR、縁取りは白）
換算: 0.065 * 9.80665 * 3.6 = 2.2947561 km/h/s ≒ 2.3 km/h/s、0.100 * 9.80665 * 3.6 = 3.530394 km/h/s ≒ 3.5 km/h/s
"""
from config import (
    COLOR_OUTLINE_BLACK,
    COLOR_OUTLINE_WHITE,
    COLOR_WHITE,
    STOP_JERK_FIRST_BOUNDARY_COLOR,
    STOP_JERK_SECOND_BOUNDARY_COLOR,
)

STOP_JERK_DESCRIPTION_LINES = (
    (("【 停車時衝動 】", "normal"),),
    (("列車が完全に停止する際のショックの大きさを、停止直前の0.5秒におけるGの平均値により採点します。", "normal"),),
    (
        ("（※", "normal"),
        ("0.065G≒2.3km/h/s", "first"),
        ("以上で-100点、", "normal"),
        ("0.100G≒3.5km/h/s", "second"),
        ("以上で-200点）", "normal"),
    ),
)


def stop_jerk_description_text():
    """色を無視した、改行区切りの全文（従来の desc_dict と同じ形）。"""
    return "\n".join("".join(text for text, _kind in line) for line in STOP_JERK_DESCRIPTION_LINES)


def span_colors(kind):
    """(文字色, 縁取り色)。第一・第二境界は白の縁取り、通常は黒の縁取り。"""
    if kind == "first":
        return STOP_JERK_FIRST_BOUNDARY_COLOR, COLOR_OUTLINE_WHITE
    if kind == "second":
        return STOP_JERK_SECOND_BOUNDARY_COLOR, COLOR_OUTLINE_WHITE
    return COLOR_WHITE, COLOR_OUTLINE_BLACK
