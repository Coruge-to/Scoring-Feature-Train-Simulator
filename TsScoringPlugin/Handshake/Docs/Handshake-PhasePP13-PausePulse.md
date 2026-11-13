# Phase PP-13 — Pause 中の read-only pulse（P→P の撤去）

提供者: **Coruge-to** / 対象: Current（BveEX）の Telemetry（`Class1.cs`）と Bridge、Legacy（BVE5 + AtsEX）の Telemetry と Bridge、管理起動の Python / 状態: 実装・オフライン試験済み（実機受入れは正式 DLL 配置後）。

## 1. 何を置き換えたか

BVE の Pause 中は拡張の `Tick` が呼ばれない。Tick の上でしか BVE の状態を読めない前提だったため、Pause 中の操作（F5 再読込、位置・時刻表の変更、TS Scoring の OFF→ON）ではデータが再生成されず、HUD が消えるか更新されなかった。これを SI-A6 以降は Python が P を 2 回送る「P→P」で回避していた（`pause_recovery.py`、F5 トークン、PP-4 の ON トークン）。

実機（PP-5／PP-6、2026-11-13）で次が分かった。Pause 中も BVE の UI スレッドのメッセージループは動いており、`SynchronizationContext.Post` で積んだ処理だけが配られる（`WinForms.Timer` と `Application.Idle` は発火しない）。この処理は Tick と **同じスレッド**で走るため、Tick と同じ安全性で BVE の状態を読める。そこで P→P を撤去し、拡張側の pulse に置き換えた。

## 2. 契約

* **起動条件**: プールタイマー（`System.Threading.Timer`）が周期ごとに「直近の Tick から 150 ms 以上経っているか」を見て、経っている場合だけ UI スレッドへ `Post` する。通常の Tick が流れている間、pulse は何もしない。
* **周期**: Current Telemetry 16 ms、Legacy Telemetry 16 ms、Current Bridge 50 ms、Legacy Bridge 50 ms（Current = Legacy）。
* **送信**: pulse は Tick 本体と同じ読取りを経過時間 0 で行う。送る内容が前回と同じなら再送せず、変化があったときと 1 秒ごと（refresh）にだけ全体を送る。
* **pulse は Tick ではない**:
  * `lastTickTime` を更新しない（heartbeat は PAUSED のまま）。
  * `TickSeenInEpoch` を立てない。読込マーカーの `TickSeen` も立てない（`ScenarioReadyTracker.OnPulse` は `OnTickCore(true)`、Tick 数・epoch の Tick フラグ・読込 Tick ビットは `!pulse` のときだけ上げる）。
  * 最初の Tick の記録（`NoteTick`）を行わない。
  * Jump 命令を実行しない（Jump は Tick 経路のみ）。
* **ScenarioReady**: Bridge の pulse は、F5 再読込後・OFF→ON 後の ScenarioReady を Tick なしで再確立できる（`tickInGen=0`、`tick_seen=0`）。TS Scoring が OFF の間は確立しない（Tick と同じ規則）。本物の Tick が来て初めて Tick フラグが立つ。
* **後始末**: Dispose 後は Post しない。timer は所有者ごとに 1 つ。Input Device OFF／BVE 終了で止まる。
* **キーを一切送らない**: 管理起動では、Python・拡張・Caller のどれも BVE へキーを送らない（Caller が BVE へ送るのは終了要求の WM_CLOSE のみ）。recovery-token と recovery-summary の診断行は存在しない。OSK への依存も無い。

## 3. 撤去したもの

`pause_recovery.py`、`main.py` の `press_p_for_recovery` と `_attach_managed_hud` の recovery 配線、`managed_hud.py` の `attach_recovery`／token 監視／`recovery-summary`、これらの試験（`tests/test_pause_recovery_sia6.py`）。SI-A6／SI-A7 文書の P→P の節は旧暫定設計の履歴として残し、冒頭に置換の注を付けた。`Test-PauseRecoverySIA6.ps1` は P→P 専用ではなく、状態ブロックの読込マーカー（`LOD1`）の一般契約を持つため、名前を維持して残した。

## 4. 固定する試験

* `Test-ExtensionControlPlaneSIA7.ps1` C7／C7b（ソースの構造）と E5〜E10（`OnPulse` の挙動: Tick なしの確立、50 回の追加 pulse で不変、`SR_EPOCH_TICK` が出ない、2 回目の再読込、本物の Tick でフラグ、OFF 中は確立しない）。Current／Legacy の両アダプターで実行する。
* `Tools/Verify-PausePulsePP13.ps1`: P→P の不存在（Python、送信側、Caller）と pulse 契約（周期、150 ms 条件、Post、timer 1 個、Dispose、Tick でないこと）の静的検査。
* Python: `tests/test_epoch_info_sia7.py`（P→P の不存在）、`tests/test_stationindex_package_st3e0.py`（モジュール 33）、manifest。

## 5. 既知の事項

* **手動起動（`--managed` なし）の P→P も撤去した**（Owner 裁定 2026-11-13: 正式運用は管理起動で、手動起動にも P 送出を残さない）。`_kick_start_first_press`／`_kick_start_second_press`、`initial_kickstart_done`／`auto_pause_pending`／`kick_bve_time`、`kickstart` イベントを削除した。これらは P の送出と、その状態だけで、一般責務は混在していなかった（`is_bve_loaded`／`bve_actual_state` は STATUS の観測値なので残す）。代わりに `_diagnose_pause_without_data` が、BVE が PAUSED を 20 秒以上報告しても駅リストが届かないときに、一度だけ「送信側 DLL の pause pulse が無い（構成不一致）。キーは送らない」と診断する。P→P へ fallback しない。
* main.py が P を送るのは、F1 メニューを開く／閉じるときの一時停止・再開（`toggle_menu`、利用者の操作）だけで、回復や kick start ではない。これは本 Phase の対象外（Verify-PausePulsePP13.ps1 が `toggle_menu` だけであることを固定する）。
* Current の観測ログが、pulse で確立した世代の `SR_ESTABLISHED` 行を 1 度だけ出さなかった。状態は正しく確立していた（E5／E6 PASS）。ログのみの欠落として扱う。
