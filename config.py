BASIC_BRAKE_APPLY_LIMIT = 0   
BASIC_BRAKE_RELEASE_LIMIT = 0 

STATION_MARGIN = 200.0

IGNORE_INITIAL_BRAKE = "NONE"
IGNORE_RELEASE_BRAKE = "NONE"

MANUAL_EB_ACCUM_THRESHOLD = 0.3
MANUAL_EB_COOLING_THRESHOLD = 1.0
SMEE_VIRTUAL_EB_BP_RATIO = 0.95

FONT_PATH = r"C:\WINDOWS\FONTS\UDDIGIKYOKASHON-R.TTC"
FONT_SIZE_NORMAL = 35  
FONT_SIZE_BIG = 55
FONT_SIZE_UI = 40

COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_OUTLINE_BLACK = (0, 0, 0)
COLOR_OUTLINE_WHITE = (255, 255, 255)
COLOR_BG = (40, 40, 40, 100) 
COLOR_N = (0, 180, 80)      
COLOR_P = (0, 120, 220)     
COLOR_B_SVC = (220, 120, 0) 
COLOR_B_EMG = (200, 20, 20) 

OUTLINE_WIDTH = 6 
BASE_SCREEN_W = 1920.0
BASE_SCREEN_H = 1080.0

# ATS信号無視の採点機能を現在提供できるかを表す唯一の正本。
# False: β版では未対応。設定UIはOFF固定・トグル不可、採点不可、リザルトは薄いOFF表示。
# True : 保安装置対応後に、既存のpen_atsによるON/OFF切替を復活できる。
ATS_SIGNAL_IGNORE_AVAILABLE = False

def is_ats_signal_ignore_effective(pen_ats):
    # 実効状態は ATS_SIGNAL_IGNORE_AVAILABLE and pen_ats
    return bool(ATS_SIGNAL_IGNORE_AVAILABLE and pen_ats)

MARGIN_LEFT = 50          
MARGIN_TOP_BIG = 122      
MARGIN_TOP_NORMAL = 294   
MARGIN_RIGHT = 50         
MARGIN_TOP_UI = 100       
LABEL_WIDTH = 380         

VISIBLE_LIST_COUNT = 5 # ★ 駅リストの表示件数を5件に統一

# ---- 停車時衝動（正式採点）----
# 入力は BVE 公式の Vehicle.Vibration.AccelerationZ（m/s^2）だけ。正式指標は LastStop BveG
# ＝停止直前 STOP_JERK_WINDOW_SECONDS 秒の窓平均の絶対値（G）。減点は丸め前の値で判定する。
STANDARD_GRAVITY_MPS2 = 9.80665
STOP_JERK_WINDOW_SECONDS = 0.5
STOP_JERK_FIRST_BOUNDARY_G = 0.065    # この値以上で -100 点
STOP_JERK_SECOND_BOUNDARY_G = 0.100   # この値以上で -200 点

# 利用者向け文言の境界の色（文字本体の色。縁取りは白）。初回は BVE の「乗客の揺れ」図形の材質色を機械的に算出した値で、
# 独自の色相補正はしない。実機で見てから、この 2 つの定数だけを調整できる。
#   材質色（BVE の b4.a）: n=(int)(12.5*|num|*64)、R=min(max(128+n//2,96),160)、G=min(max(160-n,96),160)、B=96
#   停止＝階段としての |num| = 0.0669 × 減速度[m/s^2]（tests の GUARD が算出式を再計算して一致を固定する）
#   0.065 G → n=34 → (145, 126, 96)、0.100 G → n=52 → (154, 108, 96)
STOP_JERK_FIRST_BOUNDARY_COLOR = (145, 126, 96)
STOP_JERK_SECOND_BOUNDARY_COLOR = (154, 108, 96)

CATEGORY_ORDER = {
    "システム": 0, "運転時分": 1, "停止位置": 2, "基本制動": 3, "ボーナス": 4,
    "ATS信号無視": 5, "速度制限超過": 6, "初動ブレーキ": 7, "非常ブレーキ": 8,
    "緩和ブレーキ": 9, "停車時衝動": 10, "転動": 11
}