# ==========================================
# ★ 採点システム カスタマイズ設定 ★
# ==========================================
BASIC_BRAKE_APPLY_LIMIT = 0   
BASIC_BRAKE_RELEASE_LIMIT = 0 

STATION_MARGIN = 200.0

IGNORE_INITIAL_BRAKE = "NONE"
IGNORE_RELEASE_BRAKE = "NONE"

ECB_EB_ACCUM_THRESHOLD = 0.3    
ECB_EB_COOLING_THRESHOLD = 1.0  
# ==========================================

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

MARGIN_LEFT = 50          
MARGIN_TOP_BIG = 122      
MARGIN_TOP_NORMAL = 294   
MARGIN_RIGHT = 50         
MARGIN_TOP_UI = 100       
LABEL_WIDTH = 380         

VISIBLE_LIST_COUNT = 5 # ★ 駅リストの表示件数を5件に統一

CATEGORY_ORDER = {
    "システム": 0, "停止位置": 1, "基本制動": 2, "運転時分": 3, "ボーナス": 4,
    "ATS信号無視": 5, "速度制限超過": 6, "初動ブレーキ": 7, "非常ブレーキ": 8,
    "緩和ブレーキ": 9, "停車時衝動": 10, "転動": 11
}