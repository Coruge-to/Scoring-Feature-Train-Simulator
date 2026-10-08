# TS Scoring – Phase M1 依存案内の表示条件（Caller 0.7.0.0）

提供者: **Coruge-to** / Caller バージョン: **0.7.0.0** / 対象: Caller（`TSScoringPlugin.Caller.InputDevice.dll`）のみ。
Current Bridge・Legacy Bridge（0.6.0.0）、ScenarioReady、ScenarioGeneration、`HandshakeProtocol` は変更していません。**自動配置はしていません。**

## 1. 何を変えたか

BveEX が無いときの依存案内（MessageBox）を出す**タイミング**だけを変えました。
案内の本文・タイトル・MessageBox フラグ・500 ms 定数（`BridgeMissingTimeoutMs`）・Configure 画面・自動撤回は**変更していません**。

| | 変更前（0.6.0.0） | 変更後（0.7.0.0） |
|---|---|---|
| 起動直後（Caller 有効化から 500 ms、BridgeAvailable なし） | その場で案内を表示 | 診断ログに 1 行記録するだけ。**案内は出さない** |
| 案内が出る契機 | 500 ms の経過だけ | ① 現在の Caller インスタンスで BVE の **最初の Tick** が来たとき BridgeAvailable が無い ／ ② 一度 BridgeAvailable を確認した後、500 ms 以上消失 |
| 案内の回数 | 不在区間（連続した消失）ごとに 1 回 | **Caller インスタンスごとに最大 1 回** |

理由（Phase M0 実機観測）: BVE の Tick（= Caller の `IInputDevice.Tick`）は**シナリオを読み込んだときにだけ**呼ばれる。シナリオ一覧を見ているだけの利用者は、TS Scoring をまだ使い始めていないため、BveEX が無くても案内しない。BVE5・BVE6 とも初回 Tick は ScenarioCreated の約 17 ms 後で、BveEX が有効なら BridgeAvailable はそれより十数秒前に成立している。

## 2. 状態の意味

`HandshakeSession.State`（`DependencyState`、段階の状態機械 `CallerPhase` から導出する読み取り専用の値）。

| 状態 | 意味 |
|---|---|
| StartupWaiting | 有効化直後。最初の Tick も BridgeAvailable の確認もまだ。**警告しない**。500 ms 到達は診断ログのみ（`TIMEOUT_REACHED kind=startup-log-only`） |
| UseStarted | 最初の Tick を観測し、BridgeAvailable が無かった（一度だけの初回依存判定が済んだ） |
| Connected | BridgeAvailable を確認済み（または消失が 500 ms 未満）。初回の依存案内なし |
| ConnectionLost | 一度 BridgeAvailable を確認した後、500 ms 以上消失 |

## 3. 初回 Tick の判定

1. `Tick()` は `session.NotifyTick()` を呼ぶだけ。`NotifyTick()` は最初の 1 回だけ、タイムスタンプ 1 個とフラグ 1 個（volatile 書き込み）を書く。**ロックなし・ファイル I/O なし・ログなし・MessageBox なし・待機なし**。
2. 監視スレッド（既存の 1 本、20 ms 周期）がフラグを見つけて判定する。
3. **BridgeAvailable を直接確認**する。保持している古いハンドルを一度閉じ、名前付きイベントを開き直して「存在し、かつシグナル状態」を見る。キャッシュ状態は使わない。
4. Present → 何もしない（通知ラッチは消費しない）。Missing → 案内を要求（要求した時点ではまだ表示しない）。
5. 表示直前にもう一度 BridgeAvailable を直接確認する（Present に戻っていれば表示しない・ラッチは消費しない）。

**判定に使わないもの**: Ready、bridgeKind（ロード済みアセンブリ名）、SetAxisRanges、ScenarioCreated、ScenarioReady、ScenarioGeneration、Tick 回数・頻度、固定待機時間、前面ウィンドウ、シナリオ一覧ウィンドウ、ウィンドウタイトル。BveEX の自動撤回もしない。

## 4. 通知ラッチ（Caller インスタンスごとに 1 個）

- ラッチ `noticeShown` は、表示を**確定した瞬間**（表示直前の再確認を通過した時点）に取る。再確認で抑止された場合は取らない。
- 初回 Tick の案内と接続消失の案内は同じラッチを共有する。どちらが先でも、同じインスタンスで 2 回目は出ない。
- BridgeAvailable が Present の初回 Tick ではラッチを消費しない。
- BridgeAvailable の再出現・再消失ではラッチを戻さない（旧版の「不在区間ごとの再武装」は廃止）。
- TS Scoring を OFF にすると Caller は Dispose され、次の ON で新しい Caller インスタンスができる。新しいインスタンスは新しい通知サイクル（最大 1 回）。
- 旧 `noticedThisAbsence`（不在区間ごとのラッチ）は廃止し、このラッチ 1 個に置き換えた。`noticeInFlight`（案内スレッド実行中の重複起動防止）は残している。

## 5. 500 ms の役割

`BridgeMissingTimeoutMs = 500` は変更していない。

- BridgeAvailable を一度も確認していない間: 到達は診断ログのみ。初回 Tick が判定する。
- 一度確認した後の消失: 500 ms 以上続けば接続消失として案内（従来どおり、BVE 終了直前の短い消失で誤通知しない安全性を維持）。
- TS Scoring の手動 ON: 新しいインスタンスとして初回 Tick 判定に統合する。独立したタイマーは作らない。

## 6. BveEX の設定変更（実機仕様。テスト設計で混同しない）

- BveEX を OFF にすると警告画面が出る。「中断 / Abort」は現在の BVE を強制終了、「無視 / Ignore」は BveEX だけ OFF になり BVE は同じプロセスで継続。
- BveEX を ON にすると BVE 再起動を促すメッセージが出る。「はい」で現在の BVE を強制終了する（自動再起動はされない）。
- TS Scoring 単独の OFF／ON は Caller だけが Dispose／再生成される。BVE は終了せず、再起動もされない。

## 7. 診断ログに増えた行

`FIRST_TICK_SEEN`（最初の Tick を監視スレッドが見た）、`FIRST_TICK_JUDGE bridgeDirect=… bridgeCached=… decision=…`、`TIMEOUT_REACHED` に `kind=startup-log-only|connection-lost`、`NOTICE_JUDGE_BEGIN` に `trigger=first-use|connection-lost`。いずれも件数・フラグ・時間のみ（個人情報なし）。既存の行は項目名を含めて維持（`noticeShownThisAbsence` は「このインスタンスで案内済み」の意味）。

## 8. 検証

- `Tests\Test-DependencyNoticeM1.ps1`（M1 専用。実 Caller コードをモックの通知先で駆動し、MessageBox は一切表示しない）。
- 既存 `Test-HandshakeLogic.ps1`（Phase B）・`Test-ObservationC1.ps1`・`Test-ScenarioReadyC3.ps1`・`Test-LegacyL1.ps1` と `Tools\Verify-PhaseC3.ps1`・`Verify-PhaseL1.ps1`・`Audit-Privacy.ps1`。Phase B / C1 の試験は期待値だけを更新した（起動直後 500 ms は案内なし、最初の Tick で案内、1 インスタンス 1 回）。

## 9. 配置・復帰

自動配置はしません。配置は別承認で、Input Devices の Caller DLL を置き換える（BVE5・BVE6 の両方）。Bridge は変更がないため差し替え不要。復帰は 0.6.0.0 の Caller DLL を戻す。
