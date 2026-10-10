# Phase SI-A — 管理起動 Python での採点・操作機能の復帰（BVE6 Current）

提供者: **Coruge-to** / 対象: **BVE6 + BveEX（Current）の Caller 管理起動** / 変更するのは **Python のみ**（Caller・Bridge・両テレメトリ送信・`launcher.json` は変更しない）。

SI-A は、手動起動（`python main.py`）で成立していた採点・操作機能を、Caller が起動した**同一の管理 Python プロセス**で動かす。Legacy 固有の入力・送信（`bp_initial`・JUMP・54322・TRAINLEN 以降）は SI-B 以降で、ここでは触れない。

## 1. 状態の分離

| 状態 | 正本 | SI-A での扱い |
|---|---|---|
| Python running | Caller（`AppProcessManager`）と `managed_mode` | 変更なし。終了は Stop／親 BVE 消失のみ。Esc・BVE ウィンドウ消失では終了しない |
| Session active | 状態ブロックの Session（ScenarioReady） | OFF で採点状態を世代ごと破棄し、入力を即時解放 |
| Driving active | 状態ブロックの Driving（DrivingActive） | OFF は **Pause／一時停止として扱い、採点セッションを破棄しない**（SI-A4・§10）。入力だけを即時解放し、ON に戻ると同じ採点が続く |
| Scoring active | **利用者の開始操作だけ**（`is_scoring_mode and not is_scoring_finished`） | Python 起動・HUD 表示では ON にならない |
| HUD active | `ManagedHudController`（変更なし） | |
| Input suppression active | キーフック（F7/P/F8/メニューキー/数値ルーター）と「時刻と位置」ウィンドウの無効化 | Session ON ∧ Driving ON ∧ 当世代のテレメトリ受信済み ∧ 採点中またはメニュー表示中、のときだけ。外れた同じ tick で全解放 |

## 2. 構成

* `main.py` — `Overlay.update_logic` を**文を変えずに**責務別メソッドへ分割（`_kick_start_first_press` / `_follow_bve_window` / `_run_input_and_scoring_step` と、その中の `_detect_and_release_fast_forward` / `_resolve_bve_advancing` / `_kick_start_second_press` / `_sync_system_key_suppression` / `_sync_f8_suppression` / `_sync_time_position_window_lock` / `_sync_menu_key_suppression` / `_sync_numeric_input` / `_handle_mouse` / `_handle_keys` / `_restore_standard_window` / `_advance_scoring_clock_and_score`）。手動起動は `update_logic` から同じ順序で呼ぶ。分割前後の同値は、`git show 9f25a26:main.py` を別モジュールとして読み込み、同じ乱数シナリオ 40 本 × 420 ステップを両方に与えて Overlay 全属性と外部作用の記録が一致することで証明（`tests/test_split_equivalence_sia2.py`）。
* `managed_input.py`（新規）— 世代／採点セッションの破棄表、破棄関数、採点開始ゲート、`ManagedInputController`（管理 HUD コントローラーとの接続）、結果保存ダイアログ。
* `managed_hud.py` — `attach_input`（入力コントローラーを 1 つ接続）、`linked_hwnd`、`telemetry_ready`、状態変化の通知。HUD 自体の挙動は変えない。
* `telemetry_gate.py` — `last_verdict`（accepted / held / stale / invalid）を追加。受理判定は不変。
* `utils.py` / `scoring_logic.py` — Desktop `debug.log` のスイッチのみ（§6）。点数・規則・定数は不変（AST 比較で証明）。

管理モードの 1 tick（ACTIVE 時）:
1. テレメトリ未受信（当世代）→ HUD は出さず、入力を解放し、P→P の第 1 の P だけを許す。
2. 受信済み → HUD コントローラーがリンクした BVE ウィンドウ（**BVE プロセスの PID 一致**。タイトル検索は使わない）を `Overlay.managed_window_step(hwnd)` へ渡し、手動起動と同じ共通ステップ（P→P、早送り検知と解除、F7/P/F8 抑止、「時刻と位置」窓、メニュー、F1/F2/F11/F12、採点クロックと採点）を実行する。

管理モードに**無い**もの: Esc 終了、BVE ウィンドウ消失での終了、タイトル検索による窓探索（寿命は Stop のみ）。

## 3. 世代境界・採点セッションの破棄

* **新世代**（`ScenarioGeneration` の変化、または Session OFF）: SI-0 の D-3 の **42 変数**（`manual_eb_*`、`smee_virtual_eb_active`、`hb_*`、`bb_*`、`last_jump_count`、`bve_jump_count`、`station_list`、`is_official_jumping`、`is_official_retry`、`jump_lock`、採点フラグ、`setting_*`、`prev_*`、`last_update_time`、`menu_state`、`is_linked`、`bve_hwnd`）に加え、点滅・制限候補（`strictest_flashed_*`、`limit_flash_counts`、`current_flashing_key`）、P→P の状態（`is_bve_loaded`、`initial_kickstart_done`、`auto_pause_pending`、`bve_actual_state`）、早送り検知、メタ情報、保留中の駅リスト等を破棄（`managed_input.generation_defaults()`／`GENERATION_DROP`）。最新テレメトリ値は従来どおり `reset_telemetry_state`。
* **保持するもの**: ユーザー設定（HUD 項目、採点スイッチ、ランク、F8_disable）、インフラ（タイマー、ソケット、ゲート）、BVE ウィンドウ状態（ハンドルが有効なときだけ。無効なら参照とフルスクリーン状態を捨てる）。
* **分類の網羅性**: Overlay の全属性（`__init__`・他メソッド・`scoring_logic` が設定するもの）は「破棄／破棄対象外／テレメトリ値」のちょうど 1 つに属する。新しい属性を足すと試験が失敗し、分類の判断を強制する（`tests/test_managed_input_sia3.py` A）。
* **Session OFF／状態ブロックの喪失／Stop**: 採点セッション（得点・内訳・セーブ・ポップアップ・EB／基本制動／初動緩和状態・公式ジャンプ・メニュー）を破棄し、駅リスト・選んだ区間・ユーザー設定は残す（Session OFF は世代ごと破棄）。BVE には何も押さない（P も注入しない）。**Driving OFF だけでは破棄しない**（§10）。
* **JUMP の基準**: Current の `JUMP` 値は送信側の累積値。世代の**最初に受理した行**の値を基準へ同期する（再利用プロセスで偽の「ジャンプ検知」を起こさない）。その後の本物のジャンプは従来どおり検知して採点を中断する。
* **STALIST**: どのシナリオ世代のものかを示す項目を持たないため、管理モードでは直後の受理テレメトリ行と対にして初めて駅リストにする。古い世代の行・保留中の行に続くものは捨てる（前世代の駅リストが残らない）。送信側が Caller より先行した行（held）に付いたものは、世代到着時に一緒に適用する。手動起動は従来どおり即時適用。

## 4. 採点開始ゲート（管理起動のみ）

利用者が「採点を開始する」を押したとき、次を満たさなければ開始せず、メニューを閉じて警告を 1 つ表示し、`scoring-start-refused reason=<固定語>` を 1 行出す: ACTIVE、当世代のテレメトリ受信済み、駅リストあり、`AVAIL` が明示された送信側では必須グループ（`time speed loc station door handle brake_type brake_cab prates jump`）、Smee 車は `bpp` と受信済みの `bp_initial`。`AVAIL` を送らない Current ではグループは常に「全て有り」なので、実質は「テレメトリ・駅リスト・Smee の `bp_initial`」のみ。採点規則・点数・Smee 仮想 EB の規則は変えない（現行の欠損時 fail-open は特性化試験で現状として固定）。

## 5. 診断（`[MANAGED] event=…`、固定語と数値のみ）

`scoring-start` / `scoring-finish` / `scoring-abort reason=user|jump|generation|session-off|state-lost`（`driving-off` は SI-A4 以降出さない）/ `input-pause scoring=yes|no`・`input-resume clock=synced|kept`（SI-A4・§10）/ `scoring-start-refused reason=…` / `input-hold state=set|release kinds=sys+f8+menu+router+diag reason=…` / `kickstart step=first|second` / `ff-release` / `window-fullscreen state=on|off` / `window-standard` / `input-summary`。駅名・パス・自由文は含めない。Caller が 1 Python プロセスにつき最大 200 行・1 行 160 文字までしか転記しないため、入力コントローラーは全体 90 行・イベント名ごと 12 行までに抑え、超えた分は `input-summary` の `in_suppressed` に数える。

## 6. Desktop `debug.log`

手動起動は従来どおり書く（既定 ON）。管理起動は開始時（`run_managed`）に既定 **OFF**。環境変数 `TS_SCORING_DESKTOP_LOG=1` を BVE のプロセス環境に与えたときだけ有効（駅名を含み得る）。書込みは `utils.write_desktop_log`（呼出し 33 箇所）と、既定 OFF の制限診断 `write_limit_debug_log`（同じスイッチを見る）だけ。

## 7. 結果保存ダイアログと Stop

管理モードの保存ダイアログはネイティブの静的ダイアログではなく **Qt のダイアログインスタンス**（`DontUseNativeDialog`）。Stop／親 BVE 消失のシグナルは先にダイアログを `reject()` して入れ子のイベントループを返してから `QApplication.quit()` する。ダイアログ表示中は管理ステップを再入させない（`is_capturing_screenshot`）。実 Qt ループで「Stop 後 1 秒以内に戻る」ことを試験済み。

## 8. 終了時

HUD コントローラーの `shutdown()`（Stop／親消失）で、結果ダイアログを閉じ、採点セッションを破棄し、全キーフックを解放し、無効化した「時刻と位置」ウィンドウを有効に戻し、F11 でボーダーレスにした BVE ウィンドウを元のスタイル・配置へ戻す（ウィンドウが既に無ければ何もしない）。

## 9. 確認済みの現状と判断

* **Esc**: 手動起動のみ。管理モードで Esc（BVE が他の用途で使う）に反応して Python が終了すると、Caller は 1 BVE につき Python を 1 つしか起動しないため HUD と採点が失われる。
* **F12**: 削除しない。現行挙動（元のスタイル・位置を保持したまま 1280×720 へ強制復帰）を特性化し、管理起動でも F11 と状態を共有して動く。廃止判断は SI-A 後。
* **F7／F8 の BVE 側の機能名は仮定しない**: コードにある「BVE へ渡さないキー」の抑止条件だけを移した。
* **既知の現状（変更していない）**: F11 を OS の最大化完了待ち中に 2 回押すと全画面要求が重なって復元されない／F12 の後の F11 は F12 後の窓を「元」として保存する／負の速度では F8 フックは掛からないが早送り解除は掛かる／管理モードでも `bve_actual_state` が空のときは時計から進行を推定する。いずれも `tests/test_characterization_sia1.py` が `CURRENT_` として固定している。
* **HUD 表示の前提**: Caller が当世代の `ScenarioGeneration` を、送信側の最初の行より前に公開すること（既存の L3 ゲートの設計）。先に行が届くとその SCENARIO_ID が旧世代に結び付いて退役する（`telemetry-drop reason=stale-epoch`）。実機試験 P-A02 でログ確認する。

## 10. SI-A4 — 実機受入れ（SA 合格・SB で判明）の 3 件の限定修正

変更は Python のみ（`managed_hud.py`／`managed_input.py`／`main.py`）。Caller・Bridge・両送信側・`launcher.json`・採点点数・採点規則・`ALLTXT` の送信形式は変更しない。

### 10.1 Pause（Driving OFF）で採点を破棄しない

* **原因**: BVE の Pause は Tick を止め、Caller は 2 秒を超える Tick 停止を Driving OFF（`tick-stale`、soft OFF）にする。SI-A の `ManagedHudController` は ACTIVE → Driving OFF で `ManagedInputController.on_inactive("driving-off")` を呼び、`discard_scoring_session` で採点を破棄していた。
* **分離できないこと（契約の前提）**: 状態ブロックの Driving OFF には Pause・短い Tick 停止・シナリオ選択画面・利用者の操作による停止の区別が無い。Caller を変えずに Python が見分ける手段は無い。したがって **Driving OFF は採点の終了ではない**とし、Pause を含む全ての Driving OFF で採点を保持する（利用者の「採点を中断する」操作は従来どおり採点側の規則）。
* **契約**: Driving OFF（Session ON）→ `on_pause`: プロセス・Overlay・採点セッション（得点・設定・駅リスト・時刻基準）を保持、入力抑止（F7／P／F8／メニューキー／「時刻と位置」ウィンドウ）は同じ tick で解除、HUD は待機で非表示、開いていたメニューは何も押さずに閉じる、`scoring-abort` は出さない。Driving ON → 次のステップで `_resync_clock`: BVE 時刻が進んでいれば採点クロック基準を現在時刻へ（そのステップの dt = 0。Pause 時間を 1 ステップとして数えない）、早送り測定を初期化（Pause 後の時刻差を早送りと誤認して F8 を送らない）。時刻が戻っていた場合・採点クロックが未開始（0.0）の場合は既存規則（`reset_transient_scoring_state`）に任せる。
* **従来どおり破棄するもの**: Session OFF、新しい ScenarioGeneration、状態ブロックの喪失（fail-safe）、Stop／親 BVE 消失、利用者の中断・ジャンプ検知。新世代では前世代の採点・42 変数・駅リスト・P→P 状態を破棄し、Driving OFF 後の再 ON で旧採点を捨てた状態から再開することはない。
* **この契約の変更で書き換えた SI-A の試験**: `soft_off_discards_the_scoring_session…`、`soft_on_does_not_resume_the_old_scoring…`、`no_kick_start_in_soft_off`、C（四つの組合せ）、K（真理値表）の Driving OFF 行。旧契約を固定していた期待を新契約に置き換えたもの（削除・弱体化ではなく反転）。

### 10.2 Pause 読込時の P→P 〔**SI-A6 で撤回・置換**: 下の WAITING の P→P は通常の読込でも誤発火したため削除した。現行の契約は `Handshake-PhaseSIA6-PauseRecovery.md`（具体的な操作ごとのトークン。いまの実装は「Pause 中の F5」だけ）〕

* **原因**: P→P 本体（`Overlay._kick_start_first_press`／`_kick_start_second_press`）は存在したが、管理入口が ACTIVE の「テレメトリ待ち」だけだった。一時停止で読み込むと Tick が一度も来ないので Driving は OFF のまま（Session ON／Driving OFF = WAITING）で、第 1 段に到達できなかった（実機 SB: telemetry-first が先に起き kickstart 0 件）。
* **修正**: WAITING でも `ManagedHudController._tick_waiting_kickstart` が `Overlay.kick_start_wanted()` が真のときだけ PID 一致の BVE ウィンドウを取得し、`Overlay.kick_start_managed_waiting(hwnd)` で P→P の第 1 段・第 2 段だけを実行する。HUD 表示・採点・通常メニュー・F7／F8 抑止・「時刻と位置」ウィンドウ・通常キー処理は行わない。BVE 内部 API は読まず、既存の `PostMessage` による P だけを使う。
* **条件**: Session active（WAITING）、当世代（世代境界で `is_bve_loaded`／`bve_actual_state`／`station_list`／`kick_bve_time`／`initial_kickstart_done`／`auto_pause_pending` は破棄済み）、`STATUS:LOADED:PAUSED`、駅リスト空、当世代で第 1 段未実行。第 2 段は駅リスト成立・BVE 時刻の進行・RUNNING・同じ BVE ウィンドウで 1 回だけ。世代ごとに 1 往復。HUD の有無に依存しない。

### 10.3 POW 側の抑速の表示幅

* **原因**: 現在表示（`powNotch < 0`）の文字列は `HoldingSpeedTexts` から取られるが、Python の `ALLTXT` 解析は第 3 群（BRK）までで第 4 群（抑速文字列）を読まず、`max_pow_w` が `PowerTexts` だけで決まっていた（実測: 表示「抑速3」で max_pow_w = 53、実描画幅 = 133）。
* **修正**: 第 4 群を後方互換に読み（無い・空の旧電文は従来どおり）、`max_pow_w = max(40, 力行文字列と抑速文字列の最大描画幅)`（既存の `QFontMetrics` のまま）。`max_brk_w`／`max_rev_w`、現在表示による動的拡張、パディング・縁取り・DPI は変えない。Current／Legacy の送信側（`Class1.cs`、`LegacyHandleContract.cs`）は第 4 群を既に送っており、変更不要。1 ハンドルでも `max(max_pow_w, max_brk_w)` の左辺に反映される。

### 10.4 β 版後の課題（今回は実装しない）

* 自由文字列と区切り文字（`_` `:` `,` `=`）が混在する旧電文の契約。作者定義文字列に区切り文字が含まれると可逆に扱えない。
* 将来のバージョン付き・可逆な送信方式（エスケープ、Base64／JSON など）。
* 極端に長い作者定義文字列の改行・省略。閾値を超えたらレガシーモード相当の汎用文字列へ切り替える構想。

## 11. 試験

* Python: `tests/test_characterization_sia1.py`（特性化 130）、`tests/test_split_equivalence_sia2.py`（分割同値・スコープ）、`tests/test_managed_input_sia3.py`（管理接続・状態契約・世代・P→P・結果ダイアログ Stop・実プロセス・Privacy・不変対象）、`tests/sia_rig.py`／`tests/sia_managed_rig.py`（偽物の注入）、`tests/test_pause_ptop_width_sia4.py`（SI-A4: Pause 保持・再同期・世代／Session OFF／喪失／Stop の破棄・WAITING の P→P・抑速幅・静的スコープ）。
* 既存の範囲ガード（E2／E4／L3／P1／SI-0／SI-1／LI0／LI1）は、同じ比較と厳しさのまま、基準を「作業ツリー対 HEAD」から「各フェーズのコミット対」へ付け替えた（SI-1 コミット後に陳腐化していた L07／L09 を含む）。
