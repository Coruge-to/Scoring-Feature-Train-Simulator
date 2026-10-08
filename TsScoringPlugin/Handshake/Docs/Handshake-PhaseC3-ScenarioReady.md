# TS Scoring – Phase C3（ScenarioReady 正式実装・Current BveEX モード）

提供者: **Coruge-to** / バージョン: **0.6.0.0** / 対象: **通常の BveEX モード（BVE5・BVE6）**。AtsEX レガシーモードは対象外（未実装）。

この版は Phase B のハンドシェイク（Enabled / Stop / BridgeAvailable / Ready）と Phase C1 の観測ログをそのまま残し、
**ScenarioReady** と **ScenarioGeneration** を追加します。Python 起動・HUD・採点・UDP・レジストリ・キーフックは含みません。
500 ms の依存案内（BridgeMissingTimeoutMs）と案内の本文・タイトルは変更していません。**自動配置はしていません。**

## 1. ScenarioReady の意味

「BVE の内部で有効なシナリオが構築済みで、TS Scoring が必要とする BVE 参照を Tick 上で安全に読める状態」です。
**運転画面が表示されているかどうかではありません。** タイトル画面へ戻っても ScenarioClosed が出ず参照が保持されていれば、ScenarioReady のままです。
タイトル帰還は TICK_GAP・Tick の速さ・経過時間・IsScenarioCreated だけから推測しません（将来の HUD・採点の休止判定が必要なら、別の状態として Phase D で扱います）。

### 成立（Phase C2 の候補 E）
同じ ScenarioGeneration の中で、次をすべて満たした**最初の Tick** で 1 回だけ成立します。

- ScenarioOpened と ScenarioCreated を受信済み
- IsScenarioCreated が true
- Scenario / TimeManager / VehicleLocation / Vehicle の参照が読め、VehicleLocation の位置が有限値（null・NaN・Infinity・例外は不成立）
- Bridge が Dispose されていない
- TS Scoring が有効（Enabled）で、Phase B の Ready が成立している

PostTick は条件ではありません（AtsEX Legacy に PostTick が無いため）。候補 F は診断専用で、ScenarioReady を設定しません。
成立前の読取り失敗は次の Tick で再試行します。成立後は BVE の参照を読み直さないので、一時的な失敗では解除されません。

### 解除
- ScenarioClosed
- 次の ScenarioOpened の安全リセット（**先に解除してから** ScenarioGeneration を増やす）
- Bridge の Dispose（BveEX OFF / BVE 終了）
- TS Scoring 無効化（Caller 停止）では**外部公開を停止**します（レベル自体は保持し、再有効化の最初の Tick で現在のレベルを即再公開します）

### 解除しないもの
Pause、Tick の停止や TICK_GAP、タイトル帰還の推測、IsScenarioCreated 単独の変化、Phase B の Ready が維持されていること、isReload、成立後の一時的な参照読取り失敗。

## 2. ScenarioGeneration

- int32。プロセス内で単調増加し、**ScenarioOpened ごとに +1**。0 は「まだ何も開かれていない」。
- 初回読込・同一シナリオの再読込・別シナリオを区別しません。シナリオ名やフルパスは使いません。
- Pause・タイトル帰還・ScenarioClosed では増えません。BveEX OFF は BVE の再起動なので、新しい Bridge で 0 から始まります。
- オーバーフロー時は 1 に戻ります（0 にも負数にもなりません）。直前の値とは必ず異なるので、「前回と違う世代を見たらシナリオ状態を捨てる」という消費側の規則がそのまま成り立ちます。

## 3. 共有契約（BVE の PID を名前に含む）

| 名前 | 内容 |
|---|---|
| `Local\TSScoringPlugin.v1.<PID>.ScenarioReady` | 手動リセット Event。Set = 現在の世代が ScenarioReady。Reset または存在しない = そうでない |
| `Local\TSScoringPlugin.v1.<PID>.ScenarioState` | 64 バイトのメモリ専用ブロック。ProtocolVersion、BveProcessId、ScenarioGeneration、IsScenarioReady、Sequence（偶数=安定）、Check |

どちらも Ready が存在する間だけ存在します（完全休止契約）。値は整数のみで、パス・シナリオ名・車両名・個人情報は入りません。
読み手は Event と Check 付きのブロックの両方が一致したときだけ ScenarioReady と見なします。壊れた・短い・版違い・PID 違いのブロックは常に「ScenarioReady ではない」と読みます。

## 4. 診断ログ

固定ログ `Downloads\TSScoring-Phase-C1-Observation.log`（C1 と同じ名前・同じ形式。観測契約を維持するため名前は変えていません）に、Track A の行が増えます。

| 行 | 意味 |
|---|---|
| `SR_OPENED / SR_CREATED / SR_CLEARED / SR_CLOSED_NO_LEVEL` | 世代の開始、作成、解除（理由 closed / opened-reset / bridge-dispose） |
| `SR_ESTABLISHED` | 候補 E の成立。世代・Tick 番号・Opened からの ms・時刻・参照の可否（yes/no のみ。値は記録しない） |
| `SR_PENDING` | 成立前の取得失敗（理由コードが変わったときだけ。例外は型名のみ） |
| `SR_WAIT` | TS Scoring 無効 / Ready 未成立のため待機 |
| `SR_PUBLISHED / SR_WITHDRAWN / SR_PUBLISH_FAIL` | 外部公開の開始・停止・失敗 |
| `SR_E_STALLED / SR_F_DIAG` | E が 300 Tick 成立しないときだけ。その後の最初の PostTick 時点の取得結果（診断専用） |
| `SR_GENERATION_WRAPPED / SR_DISPOSED` | オーバーフロー、Dispose |
| `SCN_READY_ON / SCN_READY_OFF / SCN_GENERATION_CHANGED` | Caller 側が読んだ ScenarioReady の遷移（ログのみ。他の動作は変わりません） |

C1 の Track A / B の行（候補 A〜F、TICK_GAP、起動時系列、案内の判定）は変更していません。

## 5. 手動配置（BVE と BveEX を完全に終了してから）

`dist\` の DLL は 2 個だけです（PDB なし）。SHA-256 は成果レポートにあります。

| DLL | 置き場所 |
|---|---|
| `TSScoringPlugin.Caller.InputDevice.dll` | BVE6 と BVE5 の `Input Devices` フォルダ |
| `TSScoringPlugin.BveEx.Bridge.Prototype.dll` | BveEX の `Extensions` フォルダ（`%PUBLIC%\Documents\BveEx\2.0\Extensions`） |

1. 今入っている DLL（Phase C1 の 0.5.0.0 または Phase B）を別の安全な場所へコピーして残す（復帰用）。
2. 同名の DLL を上書きするか、古い DLL を削除して新しい DLL を置く。
3. BVE を **1 つだけ**起動する（2 つ同時に動かすと観測ログが混ざります）。TS Scoring を ON にする。
4. 戻すときは、2 個の DLL を退避したものへ戻す。

## 6. 実機確認の流れ（BVE6、BVE5 それぞれ・BVE は 1 プロセスずつ）

1. 起動 → タイトル 15 秒 → シナリオ S1 読込・走行 10 秒（`SR_ESTABLISHED`、`SCN_READY_ON ScenarioGeneration=1`）
2. Pause 10 秒 → 解除（ScenarioReady と世代が変わらない）
3. タイトルへ戻って 20 秒そのまま（ScenarioReady のまま。`SR_CLEARED` が出ない）
4. S1 を再読込 → 走行（`SR_CLEARED reason=closed` の後に世代 2）
5. 別の S2 を読込 → 走行（世代 3）
6. 走行中に TS Scoring を OFF → ON（OFF で公開停止、ON で同じ世代を即再公開）
7. 走行中に BveEX を OFF（`SR_CLEARED reason=bridge-dispose`、依存案内 1 回、BVE は継続）
8. 終了。ログを**次の BVE を起動する前に**別名でコピー（次のプロセスの最初の書込みで上書きされます）

## 7. 限界

- 静的解析とオフライン試験では、BveEX 実機のイベント順序・Tick の頻度・値の妥当性は確認できません。実機ログで確認します。
- BveEX が Bridge を ScenarioCreated より後に読み込んだ場合（後付けロード）は、次の ScenarioOpened まで ScenarioReady になりません（`SR_CREATED_WITHOUT_OPEN`）。
- AtsEX レガシーモードは未観測・未実装です。共有契約・ScenarioReady の意味・状態機械はホスト非依存に分けてあります。Current 専用の部分は `TsScoringBridgePrototype.cs`（イベント購読と参照読取り）だけです。
- 第三者の DLL は同梱せず、再配布しません。
