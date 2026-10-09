# TS Scoring – E4 補足: HUD の Z オーダー（BVE 運転画面とシナリオ選択ウィンドウ）

提供者: **Coruge-to** / 対象: 管理モード（Caller が起動する Python）の HUD。Current（BVE6）と Legacy（BVE5）で共通。Python のみの変更で、配置するファイルは無い（`launcher.json` の `scriptPath` が指すリポジトリの `managed_hud.py`）。

## 1. 要求する並び

BVE の運転画面と「シナリオの選択」ウィンドウは同時に存在する。上から順に:

1. BVE のシナリオ選択ウィンドウ（最前面）
2. TS Scoring HUD
3. BVE 運転画面

HUD はグローバル最前面（TOPMOST）にしない。シナリオ選択ウィンドウはタイトル・クラス名・ScenarioGeneration で識別しない。

## 2. 不具合の原因

HUD の `Overlay` は `FramelessWindowHint | WindowTransparentForInput | Tool` の Qt ウィンドウで、BVE 運転画面を **Win32 owner** にして追従させている（最前面指定は無い）。

1. `overlay.show()` は、新しく表示されたトップレベル窓を Z オーダーの通常帯の最上位へ入れる。Qt は表示の過程で owner を外すため、owner は表示後に付け直している（ログの `hud-owner-set` が `hud-show` ごとに 1 回）。`SetWindowLong(GWL_HWNDPARENT)` は Z オーダーを並べ替えない。表示後に位置を直す処理が無かったため、**選択ウィンドウが開いている間の再表示（Tick が止まる soft OFF → ON など）で HUD が選択ウィンドウの手前に出た**。
2. 再表示の時点で HUD に BVE 運転画面の owner が残っていると、Windows は **owner（運転画面）を一緒に最前面へ持ち上げる**（実ウィンドウでの検証: 選択ウィンドウ・運転画面・HUD の 3 枚で、`[選択, 運転画面]` に owner 付きの HUD を再表示すると `[HUD, 運転画面, 選択]` になる）。owner を外してから表示すると `[HUD, 選択, 運転画面]` になる。

## 3. 修正（`managed_hud.py`）

* `_release_owner_before_show()`: 再表示の直前に owner を外す（owner が付いている時だけ。初回表示は何もしない）。直後に既存の `_ensure_owner()` が付け直す。
* `_ensure_z_order()`: active な各 tick で `GetWindow(運転画面, GW_HWNDPREV)` を 1 回見て、**HUD が運転画面の直上でなければ** `SetWindowPos(HUD, 運転画面の直上の窓, NOMOVE|NOSIZE|NOACTIVATE)` で、その窓の直下へ置く。既に直上なら何もしない。
  * 選択ウィンドウが運転画面より上にあれば、その直下に HUD が入る。無ければ HUD は運転画面の直上。
  * 運転画面の直上の窓が TOPMOST の場合は、`HWND_TOP`（通常帯の最上位。TOPMOST 帯には入らない）を使う。HUD が TOPMOST になることは無い。
  * 他アプリの窓との関係は、運転画面より上にある窓の相対順を変えない（HUD が運転画面の直上へ入るだけ）。
  * 失敗は数えて数行ログに出すだけで、HUD の表示・リンクには影響しない。
* 追加のイベント: `hud-zorder-set n=…`（補正した回、最大 5 行）、`hud-zorder-error`、終了時 `hud-zorder-summary sets=… releases=… errors=…`（一度でも動作した時のみ）。
* 使わないもの: `HWND_TOPMOST`、`WindowStaysOnTopHint`、`raise_`、`activateWindow`、`SetForegroundWindow`、`BringWindowToTop`、`SWP_SHOWWINDOW`。Overlay・QTimer・Python プロセスは再生成しない。通常（手動）モードの `main.py` は無変更。

## 4. 試験

* `tests/test_managed_hud_e4.py` の `I_ZOrder`（偽 Z オーダー）: `[HUD, Select, BVE]`→`[Select, HUD, BVE]`、`[Select, HUD, BVE]` 変更なし、`[HUD, BVE]` 直上、`[HUD, Other, Select, BVE]`、TOPMOST 窓、HUD 非表示／BVE 最小化／BVE HWND 消失／HUD HWND 未生成、show 後・soft OFF 後・再読込後の補正、owner 解放、繰り返しでも Overlay・QTimer・リンクが増えない、Current/Legacy 共通、静的ガード。
* `J_Win32ZOrderApi`: `SetWindowPos` の引数（フラグ）。`K_RealWindowsZOrder` + `tests/zorder_real_check.py`: 実際の Qt ウィンドウ 3 枚（選択ウィンドウが BVE 窓の owned / 無所有）で不具合の再現と修正、フォアグラウンド不変。
* 修正を外す変異（補正呼び出しの削除、owner 解放の削除、TOPMOST ガードの削除、常時補正）でそれぞれ試験が失敗することを確認済み。

## 5. 実機で確認すること

Legacy / Current それぞれ: 運転中にシナリオ一覧を開く → 選択ウィンドウが最前面、HUD がその下で運転画面の上 → 閉じると同じ HUD が見える。Python の PID・Overlay・QTimer は不変（`APP_LAUNCH_BEGIN` と `hud-window-linked` が増えない）。
