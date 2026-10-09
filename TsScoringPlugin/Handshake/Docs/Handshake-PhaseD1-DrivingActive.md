# TS Scoring – Phase D1 DrivingActive 状態（Caller 0.8.0.0）

提供者: **Coruge-to** / Caller バージョン: **0.8.0.0** / 対象: Caller（`TSScoringPlugin.Caller.InputDevice.dll`）のみ。
Current Bridge・Legacy Bridge（0.6.0.0）、ScenarioReady、ScenarioGeneration、`HandshakeProtocol`、BveEX 依存案内（M1）は変更していません。**自動配置はしていません。**

## 目的と範囲

Caller の内部に、読み取り専用の **DrivingActive** 状態を追加します。この Phase では誰も DrivingActive を使いません（Python の起動、HUD、採点、AppReady、Stop イベント、Process.Start、UDP、キーフックは次 Phase 以降）。状態の変化だけを、既存の観測ログ（共有 C1 ログ）へ最小限の行で記録します。

用語: BVE の起動後はシナリオ選択画面が自動的に表示され、シナリオ選択 → シナリオ読込 → 運転画面になります。運転中にシナリオを閉じると（シナリオ終了）シナリオ選択画面で待機し、シナリオ再選択 → シナリオ再読込で運転画面へ戻ります。状態判定はウィンドウタイトル・前面ウィンドウ・ウィンドウクラスに依存しません。

## 契約

```
DrivingActive = CallerEnabled AND CallerNotDisposed AND ScenarioReadyPublished AND TickFresh
                AND ScenarioReady 公開後の新しい Tick を観測済み
```

| 項目 | 内容 |
|---|---|
| 初期状態 | OFF（新しい Caller インスタンスは何も継承しない） |
| ON 条件 | Enabled・未 Dispose・ScenarioReadyPublished・ScenarioReady を観測した時点より後の新しい Tick を観測済み・最後の Tick から 250 ms 以内（250 ms ちょうどは ON 可） |
| Hard OFF（即 OFF、Tick の age に無関係） | Dispose 開始（`dispose`）、Enabled が false（`disabled`）、ScenarioReadyPublished が false（`scenario-ready-off`） |
| Soft OFF | 最後の Tick から 2000 ms を超過（`tick-stale`）。2000 ms ちょうどは ON 維持 |
| ヒステリシス | OFF では ≤250 ms で ON 可、ON では 2000 ms を超えるまで維持。250 ms 超 2000 ms 以下は直前の状態を維持 |

Soft OFF は「BVE がフレームを回していない」（長いメニュー操作・ハングなど）ことだけを表し、シナリオ終了ではありません。後続 Phase は Soft OFF で Python／HUD を終了させないこと。Hard OFF が「Caller から見たシナリオ利用の終了」です。

## 閾値の根拠（Phase D1-OBS の実機観測）

- ON 成立時の Tick age は 1〜14 ms（250 ms に十分な余裕）。Tick は BVE5／BVE6 とも約 59〜60 Hz。
- BVE5／BVE6 とも Pause 中に Caller の Tick は継続する（Pause では OFF にならない）。
- 運転中または操作中に 1062〜1118 ms の Tick 停止を 3 例観測した（シナリオ終了の UI 操作の前）。1000 ms では OFF→ON の振動が起きたため、Soft OFF を 2000 ms にした。
- シナリオ終了後のシナリオ選択画面待機では Tick が長時間止まるが、その前に ScenarioReady が撤回されるため Hard OFF が先に成立する（最後の Tick から 40〜110 ms）。2000 ms 経過でも OFF になる。

定数は `Shared\AppProtocol.cs` の `TickFreshOnMs = 250`、`TickStaleOffMs = 2000` のみ。

## C-1 の修正（ScenarioReady 公開前の Tick を使わない）

D1-OBS では、ScenarioReady 公開の直前（監視周期 20 ms 以内）に着いた Tick で ON になる場合がありました。正式版では次の規則で禁止します。

1. ScenarioReady が OFF の間の Tick は ON 成立に使わない。
2. ScenarioReady を公開状態として観測した時点の Tick sequence を `armSeq` として記録する（その評価では ON にならない）。
3. `armSeq` を超える sequence の Tick だけが有効。公開の再観測だけでは ON にならない。
4. ScenarioReady の撤回・Dispose・Enabled false で arm を破棄する。
5. ScenarioGeneration が変わった（公開が撤回されないまま別シナリオになった）場合は、その時点の sequence で再 arm し、ON だった場合は OFF（`scenario-ready-off`）にする。
6. Tick sequence は Caller インスタンスごとの 64 ビットカウンタで、インスタンス間で継承しない。比較は `unchecked(a - b) > 0`（オーバーフローしても新しい Tick は新しいと判定される）。
7. 監視スレッドは **ScenarioReady を読んだ後に** Tick sequence を読み、その後に Tick 時刻を読む（BVE の Tick は時刻→sequence の順に書く）。公開と観測の間に着いた Tick は「公開後」とは数えない（安全側。最大でも 1 フレーム分だけ ON が遅れる）。

## Tick 経路

`NotifyTick()`（BVE の `Tick()` から呼ばれる）が行うのは、`Interlocked.Exchange`（最終 Tick 時刻）と `Interlocked.Increment`（Tick sequence）の 2 つの原子的書込みだけです（既存の M1 の最初の Tick フラグはそのまま）。ファイル I/O、名前付き Event の open、ロック、MessageBox、待機、スレッド生成、Process.Start、UDP、Python 操作、ScenarioReady 共有ブロックの読取りは行いません。2 つの 64 ビット値は 32 ビットの BVE5 でも `Interlocked` で読み書きします。判定は既存の監視スレッド（20 ms 周期）で行います。

## ログ（状態変化のみ、同じ状態の重複なし）

既存の観測ログ（Track A）へ次の行だけを追加します。固定の D1-OBS ログ名・大量の観測行は持ち込みません。

- `DRIVING_ACTIVE_ON cycle=… ScenarioGeneration=… tickAgeMs=… onCount=…`
- `DRIVING_ACTIVE_OFF cycle=… reason=dispose|disabled|scenario-ready-off|tick-stale class=hard|soft ScenarioGeneration=… tickAgeMs=… activeForMs=…`
- `DRIVING_EXCEPTION cycle=… type=<例外の型名>`（最大 3 行）

ログの失敗は BVE へ伝播しません。個人情報（パス、ユーザー名、シナリオ名、車両名）は書きません。

## 変更ファイル

| ファイル | 内容 |
|---|---|
| `Caller\src\DrivingActivityState.cs`（新規） | 純粋状態機械（時計・I/O・スレッド・ログなし）と OFF 理由の分類 |
| `Shared\AppProtocol.cs`（新規） | 250／2000 ms の定数のみ |
| `Caller\src\HandshakeSession.cs` | Tick の 2 つの原子的書込み、監視スレッドでの評価、状態変化のログ、Dispose での Hard OFF（追加のみ。M1 依存案内・ScenarioReady 読取りは無変更） |
| `Caller\src\TsScoringCallerInputDevice.cs` | コメントのみ |
| `Caller\src\AssemblyInfo.cs`、`Caller\TSScoringPlugin.Caller.InputDevice.csproj` | 0.8.0.0・説明文・ソース追加 |
| `Tests\Test-DrivingActiveD1.ps1`（新規） | 状態機械・セッション・32 ビット・静的検査 |
| `Tests\Test-DependencyNoticeM1.ps1`、`Tests\Test-ObservationC1.ps1`、`Tools\Verify-PhaseC3.ps1`、`Tools\Verify-PhaseL1.ps1` | 0.8.0.0 と Phase D1 の範囲へ更新（観測版の識別・範囲検査は残さない） |

## 変更していないもの

Python、`main.py`、HUD、採点、UDP、キーフック、更新通知、インストーラー、Current／Legacy Bridge、ScenarioReadyTracker／Publisher、ScenarioObserver、ScenarioGeneration、`HandshakeProtocol` の既存契約、M1 依存案内（`StartupBridgeDiagnosticMs = 1000`、`ConnectionLostNoticeMs = 500`、MessageBox の本文・タイトル・フラグ）。

## 配置と復帰

自動配置はしません。配置は別承認で、Input Devices の Caller DLL を置き換えます（BVE5・BVE6 の両方）。Bridge は変更がないため差し替え不要です。復帰は M1 の Caller 0.7.0.0 の DLL を戻します（D1-OBS 0.7.1.0 は復帰先にしません）。

## 受入試験（実機）

1. BVE6 Current 通常読込: OFF→ON、依存案内なし、正常終了。
2. BVE6 Pause 15 秒: ON 維持、`tick-stale` なし。
3. BVE6 シナリオ終了後のシナリオ選択画面待機と再読込: 約 1.1 秒の短い Tick 停止では OFF にならない。ScenarioReady 撤回または 2000 ms 超過で OFF。再読込後は ScenarioReady 公開後の新しい Tick で ON（C-1 の再発なし）。
4. BVE6 TS Scoring OFF／ON: Hard OFF、新しい cycle、状態を継承しない、再公開後の新しい Tick で ON。
5. BVE5 Current＋Pause: BVE6 と同じ契約（32 ビット経路）。
6. （統合）BVE6 BveEX OFF／無視: ScenarioReady 撤回で Hard OFF、Caller の Tick が続いても ON に戻らない。
7. （統合）BVE5 Legacy: ScenarioReady 成立、新しい Tick で ON、Pause、シナリオ終了で OFF（Legacy にテレメトリ送信側がない点は別契約）。
