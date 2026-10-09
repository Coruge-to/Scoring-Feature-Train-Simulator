# TS Scoring – Phase E1 AppController dry-run（Caller 0.9.0.0）

提供者: **Coruge-to** / Caller バージョン: **0.9.0.0** / 対象: Caller（`TSScoringPlugin.Caller.InputDevice.dll`）のみ。
Current Bridge・Legacy Bridge（0.6.0.0）、ScenarioReady、ScenarioGeneration、DrivingActive の成立条件、`HandshakeProtocol`、BveEX 依存案内（M1）は変更していません。**自動配置はしていません。**

## 目的と範囲

Caller の内部に **AppController の dry-run 状態機械**を追加します。将来のアプリ起動要求と停止要求が「正しいタイミングで各 1 回だけ」生成されることを、観測ログと自動試験で確認するための**判断ロジックだけ**の Phase です。

この Phase は何も起動・停止・送信しません。プロセスの起動、プロセス型の保持、Python、EXE、AppReady、Stop／Session／Driving の各 Event、Job Object、再起動、バックオフ、HUD、採点、UDP、キーフックは**導入していません**（導入は E3 以降）。

用語: シナリオ選択画面／シナリオ終了／シナリオ再選択／シナリオ再読込／運転画面。

## 承認された設計（E0 の判断）

| 項目 | 内容 |
|---|---|
| 起動要求の契機 | ScenarioReady 公開後の**最初の DrivingActive ON**（同じ ScenarioGeneration では 1 回だけ） |
| 抑止 | Pause、soft OFF 後の再 ON、短い Tick 停止後の再 ON、Legacy のシナリオ選択画面での再 ON、同一世代内の ON／OFF の振動では**新しい要求を出さない** |
| Python の寿命（将来） | Caller インスタンスに結びつける。ScenarioReady 撤回・シナリオ再読込・Pause・soft OFF では終了させない。終了の主経路は Caller Dispose |
| 単一 EXE 化 | 将来の配布準備 Phase（E1 は無関係） |

## 契約

| 事象 | 起動要求 | 停止要求 |
|---|---|---|
| 初期状態 | なし | なし |
| ScenarioReady 公開だけ（DrivingActive OFF） | なし | なし |
| DrivingActive ON だが ScenarioReady 公開の契約を満たさない（未公開・世代 0） | なし | なし |
| 公開後の初回 DrivingActive ON（その世代で初） | **1 回**（番号は Caller インスタンス内で 1, 2, 3 …） | なし |
| 同じ世代での DrivingActive の継続・再 ON・振動・Pause・Tick 停止 | なし（最初の抑止だけ `APP_START_SUPPRESSED` を 1 行） | なし |
| soft OFF（`tick-stale`） | なし | **なし** |
| ScenarioReady 撤回（hard OFF `scenario-ready-off`） | なし | **なし**（AppController は存続し、世代の記憶も保持） |
| 新しい ScenarioGeneration の初回 DrivingActive ON | **新しい 1 回**（古い世代の「起動済み」は継承しない） | なし |
| Caller Dispose 開始 | なし（以後は一切出さない） | **1 回**（起動要求が 1 回以上あった場合）。重複観測でも 1 回 |
| Dispose だが起動要求が一度もなかった | なし | **出さない**（`APP_STOP_NOT_REQUIRED` を 1 行だけ。停止すべき対象がない） |
| Enabled=false（Start されていない Caller） | なし | なし（実行中に Enabled が false になる経路は Dispose のみ。Dispose の扱いは上記） |

- 世代の比較は「直前に起動要求を出した世代と異なるか」です。世代番号が 1 へ折り返した場合（`ScenarioGenerationRule` のオーバーフロー規則）も新しい世代として扱います。
- DrivingActive の ON が観測された評価で、世代が変わっていた場合（撤回なしで別シナリオになる場合）は、DrivingActive 自身が先に OFF（`scenario-ready-off`）になり再 arm されるため、順序は「世代変更 → DrivingActive OFF → ON → 起動要求」になります。
- Python の生存状態は E1 では持ちません。E3 では「AppStopped であること」が別の起動条件になるため、再読込（新しい世代）で Python が生存していれば、E1 が出す世代ごとの要求は E3 で起動に結びつきません。

## ログ（Track A、既存の観測ログ）

すべて `dryRun=yes` を持ち、ログの行頭には既存の `cycle=`（Caller インスタンス番号）が付きます。毎 Tick の出力はありません。

- `APP_START_REQUEST cycle=… pid=… ScenarioGeneration=… requestNo=… reason=first-driving-on dryRun=yes`
- `APP_START_SUPPRESSED cycle=… pid=… ScenarioGeneration=… requestNo=… reason=already-requested-for-generation dryRun=yes`（世代ごとに最初の再 ON の 1 行だけ）
- `APP_STOP_REQUEST cycle=… pid=… requestNo=1 reason=caller-dispose startRequests=… lastScenarioGeneration=… dryRun=yes`
- `APP_STOP_NOT_REQUIRED cycle=… pid=… reason=no-start-request dryRun=yes`
- `APP_EXCEPTION cycle=… type=<例外の型名>`（最大 3 行。例外は Caller の動作と DrivingActive を壊さない）

個人情報（パス、ユーザー名、シナリオ名、車両名）は書きません。

## 実装

- `Caller\src\AppController.cs`（新規）: 純粋状態機械。時計・I/O・スレッド・ロック・ログ・カーネルオブジェクトなし。入力は DrivingActive の結果・シナリオの公開状態・ScenarioGeneration だけ。
- `Caller\src\HandshakeSession.cs`: 追加のみ（削除 0 行）。既存の監視スレッドの `Step()` 末尾（DrivingActive の評価の直後）に 1 行、`End()` の Hard OFF の直後に 1 行を追加し、結果をログへ書きます。BVE の Tick 経路（`NotifyTick`、デバイスの `Tick`）は**無変更**です。新しいスレッドは追加していません。
- DrivingActive は引き続き状態判定だけを担当します（`DrivingActivityState.cs` は無変更）。

## 変更ファイル

| ファイル | 内容 |
|---|---|
| `Caller\src\AppController.cs`（新規） | dry-run 状態機械 |
| `Caller\src\HandshakeSession.cs` | 追加のみ（フィールド、読取りプロパティ、呼出し 2 行、ログ出力） |
| `Caller\src\AssemblyInfo.cs`、`Caller\TSScoringPlugin.Caller.InputDevice.csproj` | 0.9.0.0・説明文・ソース追加 |
| `Tests\Test-AppControllerE1.ps1`（新規） | 状態機械・セッション・32 ビット・静的検査 |
| `Docs\Handshake-PhaseE1-AppController.md`（新規） | 本書 |
| `Tests\Test-DrivingActiveD1.ps1`、`Tests\Test-DependencyNoticeM1.ps1`、`Tests\Test-ObservationC1.ps1`、`Tools\Verify-PhaseC3.ps1`、`Tools\Verify-PhaseL1.ps1` | 静的ガードの更新のみ（0.9.0.0／Phase E1 の版識別、E1 の 3 ファイルを範囲に追加、コミット履歴の検査終端を D1 の最終コミット `6018a5b` に固定） |

`Shared\AppProtocol.cs` は無変更（250／2000 ms の 2 定数のまま）です。

### 既存ガードに関する注記

D1 の後に独立した `main.py` の修正コミット（`b000a15`）が入ったため、D1／M1／L1 の旧ベースラインとの「コミット履歴に `.py` が含まれない」検査が E1 以前から失敗していました。E1 の変更ではありませんが、検査の終端を `6018a5b`（Handshake 系の最終コミット）へ固定して修復しました。E1 自身が `main.py` を含め `.py` に触れていないことは `Test-AppControllerE1.ps1` が `b000a15` との blob 一致で検査します。

## 変更していないもの

DrivingActive の成立条件・250 ms／2000 ms・hard／soft OFF の理由と分類、ScenarioReady、ScenarioGeneration、Current／Legacy Bridge、M1 依存案内（1000／500／20 ms と本文・タイトル・フラグ）、`main.py`、`scoring_logic.py`、HUD、UDP、採点、入力フック、ジャンプ、Kickstart、Python 側のコード、インストーラー。

## 配置

行っていません。ビルド成果物（`out\`、`dist\`）はリポジトリ管理外です。実機への配置と実機受入は、利用者の指示がある別の工程です。

## 実機受入で確認する項目（配置後）

- 通常の読込: `APP_START_REQUEST` が世代ごとに 1 行（`requestNo=1`）。運転中の Pause で増えない。
- シナリオ再読込: 新しい世代で `APP_START_REQUEST` が 1 行増える（`requestNo=2`）。`APP_STOP_REQUEST` は出ない。
- シナリオ終了（ScenarioReady 撤回）: `DRIVING_ACTIVE_OFF reason=scenario-ready-off` のみで、`APP_STOP_*` は出ない。
- Legacy のシナリオ選択画面の soft OFF／再 ON: `APP_START_SUPPRESSED` が最大 1 行、`APP_START_REQUEST` は増えない。
- BVE の正常終了または TS Scoring OFF: `APP_STOP_REQUEST` が 1 行。TS Scoring OFF→ON では新しい `cycle` が `requestNo=1` から始まる。
- 起動要求のないまま終了: `APP_STOP_NOT_REQUIRED` が 1 行。
- タスクマネージャーに新しいプロセスが現れない。
