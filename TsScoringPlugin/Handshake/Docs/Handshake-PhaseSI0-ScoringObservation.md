# TS Scoring – Phase SI-0（採点統合のための AtsEX Legacy 読み取り専用観測）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード** / バージョン: Legacy テレメトリ DLL **0.3.1.0**（LI2 の 0.3.0.0 に観測だけを追加した**観測専用ビルド**）。

SI-0 は **観測だけ**を行う。採点への接続、管理モードの `update_logic` 有効化、Python 本番挙動の変更、JUMP の実行、時刻・位置の変更、54322 への送信は行わない。観測結果は診断ログ（`SI0_*` 行）にだけ出る。テレメトリ（UDP 54321）の内容、AVAIL、ハートビートは 0.3.0.0 と**バイト単位で同一**である（試験 `Test-ScoringObservationSI0.ps1` A 節）。

## 1. 何を観測するか（O-A〜O-E）

| ID | 問い | 観測する値（ログ行） | 読み取り元（公開 API のみ） |
|---|---|---|---|
| O-A | Legacy 公開 API から `bp_initial` を取得できるか | `SI0_BPINIT_FIRST/CHANGE`: 種別、生値 Pa、kPa（÷1000）、方式、欠損・非有限の理由。Ecb は `not-applicable` | `BrakeSystem.BrakeController`（実行時の型が Smee / Cl のときの `BpInitialPressure`）、併せて Current が使う経路 `BrakeSystem.Smee / .Cl` の `BpInitialPressure` |
| O-B | 車両長を一意に取得できる公開 API があるか | `SI0_VEHLEN_FIRST/CHANGE`: `CarLength`（1 両の長さ）、`FirstCar/MotorCar/TrailerCar.Count`、導出**候補** 2 通り、前世代との同一性 | `Vehicle.Dynamics.CarLength`、`CarInfo.Count` |
| O-C | MAPLIMITS／CLEARDIST 相当を取得できるか。ホストの現在制限は頭か尻か | `SI0_LIMITS_LIST`（要素数、値を持つ要素数、並び順、先頭 3 件、読み取り時間）、`SI0_LIMITS_AHEAD`（先行 3000 m の件数と先頭 3 件、その Tick のホスト現在制限とリスト上の頭の値の比較）、`SI0_LIMIT_CHANGE`（現在制限が変わった位置、頭／尻候補との一致、直近の境界要素からの距離 `deltaM`） | `Route.SpeedLimits` の `Count`・添字・`MapObjectBase.Location`・`ValueNode<double>.Value`、`SpeedLimits.CurrentLimit`（従来の読み取り） |
| O-D | Heartbeat／Ready／ScenarioReady／Telemetry の成立順序 | `SI0_ORDER seq= t= th= ev=`: `init`、`evt-opened/closed/created`、`tick-first-process`、`created-changed`、`epoch-begin/end`、`line-first`、`hb-idle`（有効な世代が無いのでハートビートは何も送らない）、`hb-first-running`、`hb-paused`、`hb-running-again`、`tick-resume`、`dispose` | ホストのイベント、Tick、ハートビートスレッド（自分のフィールドだけ） |
| O-E | ジャンプ API のメタデータ | ログには出さない。**呼び出さない。**公開メタデータを試験と監査文書で固定 | `BveTypes` のメタデータ（読み取りのみ） |

Ready／ScenarioReady は制御プレーン（Bridge／Caller）の観測ログ `TSScoring-Phase-C1-Observation.log` にあり、両方のログは同じ時計（`HH:mm:ss.fff`）を持つ。パッケージの `Merge-SI0Timeline.ps1` が 2 つのログを時刻順に 1 本へ並べる（読み取り専用）。

## 2. 安全性

* **読み取りだけ**: ホストの値を変える・移動する・時刻を変える・初期化するメソッドは**どこからも呼ばない**（`Scenario.Initialize`、`InitializeTimeAndLocation`、`TimeManager.SetTime`、`SetSpeed`、リストの `GoTo`／`CurrentIndex` など）。試験 G02／G03 が配置ファイル全体の静的検査で固定する。
* **スレッド**: ホスト API は Tick スレッドだけが読む（Tick 経路）。ハートビートのスレッドは、自分のフィールドを読んで順序記録に 1 行書くだけで、ホストのオブジェクトに触れない（試験 E06／G05）。
* **負荷**: 先行制限リストは 1 Tick あたり 400 要素ずつ読む（最大 5000 要素）。車両値は 30 Tick に 1 回再確認する。
* **ログ**: 種類別の上限、世代あたり 64 行、プロセスあたりの順序行 400 行。固定語と数値だけ（パス、シナリオ名、駅名、車両名、例外文は書かない。NaN／Infinity は数値として書かない）。
* **配置しない**: このビルドは利用者が実機で配置・復元する（パッケージ `Install-PhaseSI0.ps1` の Check／Install／Restore）。

## 3. 静的監査で確定した事項（実機観測の前提）

1. **`bp_initial`**: `BveTypes`（Legacy 1.0.50314.2）の `Smee.BpInitialPressure` と `Cl.BpInitialPressure` は公開の `double`（取得・設定、単位 Pa、説明「ブレーキ緩解時のブレーキ管圧力」）。`Ecb` に相当するプロパティは無い。Smee の説明は「電磁直通空気ブレーキおよび自動空気ブレーキの場合に限り認識されます」。
2. **先行制限リスト（Phase 0 の訂正）**: Phase 0 は「`SpeedLimitList` の要素に `Value` が無い」と記録したが、`SpeedLimitList` は `MapFunctionList → MapObjectList → WrappedList<MapObjectBase>` で、公開 API の説明は「通常、要素は `ValueNode<double>`」、`ValueNode<T>.Value` は公開である。Current 送信側が実行時リフレクションで読む `Location`／`Value` と同じメンバーを、キャストで読める**可能性が高い**。要素の実際の型は実機で確認する（`SI0_LIMITS_LIST` の `valueNodes`／`type`）。
3. **車両長**: Legacy の `SpeedLimitList` に `VehicleLength` は無い（Current にはある、「自列車の長さ [m]」）。Legacy で使えるのは `VehicleDynamics.CarLength`（1 両）と `CarInfo.Count`（**double**）。先頭車を総数に含めるかは不明のため、2 通りの候補を並べて記録し、どちらも採用しない。
4. **ジャンプ API（O-E）**:
   * `Scenario.Initialize(int stationIndex)`、`Scenario.InitializeTimeAndLocation(double location, int timeMilliseconds)`、`TimeManager.SetTime(int timeMilliseconds)` はいずれも公開インスタンスメソッド（戻り値なし）。
   * ホストの埋め込みマッピング（BVE 5.8.7554.391／6.0.7554.619 の両方）で、`Initialize(int)` は元クラス `er` の**公開** `a(int)`、`InitializeTimeAndLocation(double, int)` は**非公開** `a(double, int)`、`SetTime(int)` は元クラス `cn` の公開 `a(int)`。
   * 元クラス `er` には `void(int)` メソッドが 1 つ、`void(double, int)` メソッドが 1 つしか無い（BVE5／BVE6 とも、リフレクション専用ロードで確認）。したがって Current 送信側の「最初の `void(int)`／`void(double,int)` を探して Invoke」は、公開ラッパーと**同じ元メソッド**に当たる。
   * Current の 54322 契約との対応: `JUMP_STA_TIME:<駅番号>:<ミリ秒>` ＝ `Initialize(駅番号)` の後に時刻フィールド `c` へ書込み、`JUMP_LOC_TIME:<位置>:<ミリ秒>` ＝ `(double,int)` に `(位置, 0)` を渡した後に時刻フィールド `c` へ書込み、いずれも完了後に `JUMP_COMPLETE`。公開 API では時刻を `SetTime(int)`（または `InitializeTimeAndLocation` の引数）で与える。**`SetTime` がフィールド `c` への直接書込みと同値かは未確認**であり、Initialize(int) が位置まで動かすことの確認とともに、SI-B の実機受入で `TIME`／`LOCATION` の事後値で確かめる。
   * 呼び出し条件はメタデータからは読み取れない（シナリオ作成後に限るはずだが未確認）。呼ぶのは Tick スレッドだけにする。
5. **MAPLIMITS／CLEARDIST は採点点数に使われない**（試験 `test_scoring_observation_si0.py` B 節）: 速度制限超過の減点は `effective_limit = min(MAPTAIL, SIGLIMIT)` と速度とユーザー設定 `pen_limit`（既定 ON）だけを読む。`MAPLIMITS`／`CLEARDIST`／`MAPHEAD`／`TRAINLEN` は予告表示（`disp_limit` の色と点滅）にだけ効く。`TRAINLEN` は停車駅採点範囲（`setting_stop_distance` が未設定のとき `列車長 + 200 m`）に効く。
6. **BCP は採点に使われない**: `scoring_logic.py` に `bcPressure`／`BCP` は無く、`bcPressure` の読み手はテレメトリ受信と HUD の診断行だけ（A 節）。
7. **`debug.log` の書込み箇所**（C 節）: `write_desktop_log` は `main.py` 11、`scoring_logic.py` 22 箇所。無条件に `Desktop\debug.log` へ追記し、駅名を含み得るのは `[SAVE]` と `[TIMING FALLBACK]` の 2 箇所。`write_limit_debug_log` は既定 OFF で同じファイルへ書く。`network.py` は誰も import しない。管理モードのモジュールは書かない（採点を管理モードへ接続すると書き始める）。
8. **結果保存ダイアログ中の Stop**（D 節）: ダイアログ呼び出しは `take_result_screenshot` の 1 箇所、そこへ至る道は `handle_menu_enter` → `update_logic` だけで、管理モードでは今は到達不能。ダイアログの前に外されるフックは 2 群（メニュー用、システムキー用）で、F8 用と数値ルーターは残る。Stop は `QApplication.quit()` を UI スレッドへ投げるだけなので、ネイティブのモーダルダイアログが開いたままだと `app.exec()` から戻らない可能性が残る（実機で確認する課題）。
9. **世代境界で今は破棄されないもの**（G 節）: 新しい `SCENARIO_ID` が破棄するのは採点フラグ、結果表示、得点、採点設定（開始・終了駅、停止距離、初動ブレーキ）、メニューだけ。`manual_eb_*`、`smee_virtual_eb_active`、`hb_*`、`bb_*`、`last_jump_count`／`bve_jump_count`、`station_list`、`is_official_jumping`、`jump_lock`、前 Tick 値（`prev_*`、`last_update_time`）、窓状態は**残る**。管理モードのテレメトリ状態リセット（`reset_telemetry_state`）はこれらを 1 つも破棄しない。

## 4. 特性化試験のための分離点（実装はしていない）

`Overlay.update_logic` の外部依存は `keyboard`、`win32gui`、`win32api`、`win32con`、`time`、`QApplication`、`write_desktop_log`、`reset_transient_scoring_state`、`update_physics_and_scoring`、`BASE_SCREEN_W/H` だけである。このうち前 6 つを記録用の偽物へ差し替えれば、**本番コードを 1 行も変えずに** F7／P／F8（抑止フック）、早送り検知と F8 注入、「時刻と位置」窓の無効化、P→P、F11、F12、Esc、窓消失を実行して固定できる。`test_scoring_observation_si0.py` F 節がそれを実証している（UDP 54321 は束縛しない）。`update_logic` の部分は次の順で並ぶ（E 節で固定）: Esc → 窓検索・消失 → P→P → 窓追従 → 早送り検知 → F8 注入 → P→P 2 回目 → F7/P 抑止 → F8 抑止 → 「時刻と位置」窓 → メニューキー・数値ルーター → マウス → キー分岐（F1/F2/F11/F12/…） → 時計 → `update_physics_and_scoring`。

## 5. 変更したファイル

| 区分 | ファイル |
|---|---|
| 観測 | `Telemetry\Legacy\src\LegacyScoringProbe.cs`（新規）、`LegacyTelemetrySession.cs`（観測と順序記録の配線）、`LegacyTelemetryExtension.cs`（アダプターの読み取り）、`AssemblyInfo.cs`（0.3.1.0）、`TSScoringPlugin.AtsExLegacy.Telemetry.csproj`（新規ソース 1 件） |
| 試験 | `Tests\Test-ScoringObservationSI0.ps1`（新規）、`Tests\TelemetryTestFixture.cs`（偽物の追加）、`tests\test_scoring_observation_si0.py`（新規） |
| 既存試験の更新 | バージョン検査（0.3.0.0 または 0.3.1.0）: LI0／LI1／LI2／`Verify-PhaseL3.ps1`。スコープ許可リストへ SI-0 のファイルを追加: M1／L1／`Verify-PhaseL3.ps1`。LI2 の G04〜G08 は LI2 コミット（`0010a8b` → `3158ce2`）の履歴に固定（内容は不変、作業ツリーの後続変更に依存しなくなった） |
| 文書 | 本書 |

Caller、両 Bridge、Current 送信側、`Shared`、Python 本番ファイル、`LegacyApi.cs`、`LegacyInputProbe.cs`、ハンドル契約、入力テレメトリは変更しない。
