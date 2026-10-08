# TS Scoring – Phase L1（AtsEX レガシーモード用アダプター）

提供者: **Coruge-to** / バージョン: **0.6.0.0**（共通コアと同じ） / 対象: **AtsEX 互換の BveEX レガシーモード**。通常（Current）の BveEX モードは Phase C3 のまま変更していません。

この版は、Current 版と**同じ外部契約**（Enabled / Stop / BridgeAvailable / Ready / ScenarioReady / ScenarioGeneration）を AtsEX レガシーモードで提供する Bridge を追加します。
Python 起動・HUD・採点開始・500 ms の変更・MessageBox の自動撤回・UDP・レジストリ・キーフックは含みません。**DLL の自動配置はしていません。** 実機確認は Phase L2 です。

## 1. 外部契約（Current と同一）

| 名前 | 内容 |
|---|---|
| `Local\TSScoringPlugin.v1.<PID>.Enabled / .Stop` | Caller が作る（TS Scoring の ON / 停止） |
| `Local\TSScoringPlugin.v1.<PID>.BridgeAvailable` | Bridge が読み込まれたとき作る |
| `Local\TSScoringPlugin.v1.<PID>.Ready` | Enabled かつ Stop でない間だけ存在 |
| `Local\TSScoringPlugin.v1.<PID>.ScenarioReady` / `.ScenarioState` | Phase C3 と同じ Event と 64 バイトの状態ブロック（Ready が存在する間だけ公開） |

ScenarioReady の意味（候補 E）、ScenarioGeneration（ScenarioOpened ごとに +1、オーバーフローで 1 へ戻る）、解除条件（ScenarioClosed、次の ScenarioOpened の安全リセット、Bridge Dispose）、
解除しないもの（Pause、Tick 停止、タイトル帰還の推測、IsScenarioCreated 単独、isReload）は **Phase C3 と同一**です。PostTick は使いません（Legacy に存在しません）。

## 2. Legacy API 対応表

| 必要なもの | Current BveEX | AtsEX Legacy（この版） |
|---|---|---|
| ScenarioOpened | `IBveHacker.ScenarioOpened` | 同名 `IBveHacker.ScenarioOpened`（`IsReload` あり） |
| ScenarioClosed | `IBveHacker.ScenarioClosed` | 同名 |
| ScenarioCreated / PreviewScenarioCreated | `IBveHacker` のイベント | 同名 |
| IsScenarioCreated / Scenario | `IBveHacker` | 同名 |
| TimeManager / Vehicle | `Scenario.TimeManager` / `Scenario.Vehicle` | 同名 |
| VehicleLocation（位置） | `Scenario.VehicleLocation.Location` | **`Scenario.LocationManager.Location`**（`UserVehicleLocationManager`） |
| Tick | `void Tick(TimeSpan)` | **`TickResult Tick(TimeSpan)`**（`ExtensionTickResult` を返す） |
| PreviewTick / PostTick | あり（候補 F は診断専用） | **なし**（使用しない） |
| 名前空間 | `BveEx.PluginHost.*` | `AtsEx.PluginHost.*` |

Legacy 固有の名前（`AtsEx.*`、`LocationManager`、`TickResult`）は `Bridge\Legacy\src\TsScoringLegacyBridge.cs` だけにあります。Current 固有の名前は `Bridge\src\TsScoringBridgePrototype.cs` だけです。共通コアはどちらの名前も持ちません。

## 3. 構成

```
Bridge\src\            Current アダプター + 共通コア（ScenarioReadyTracker / ScenarioReadyPublisher / ScenarioObserver）  … 変更なし
Shared\                HandshakeProtocol / ObservationLog（共通）                                                      … 変更なし
Caller\                入力デバイス Caller（Current / Legacy 共用、ホスト API に依存しない）                           … 変更なし
Bridge\Legacy\         Legacy アダプターのプロジェクト（共通コアをソースリンク）
  src\TsScoringLegacyBridge.cs     AtsEX 固有部分（イベント購読・参照読取り・Tick・Dispose）
  src\HandshakeControlPlane.cs     ホスト非依存の制御プレーン（専用スレッド。BVE の物には触れない）
  src\AssemblyInfo.cs
```

成果物 DLL は `TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll`（Current は `TSScoringPlugin.BveEx.Bridge.Prototype.dll` のまま）。.NET Framework 4.8、AnyCPU、PDB なし、第三者 DLL は参照のみ（出力に含めず Git にも入れない）。

## 4. Pause と Tick 非依存の制御

AtsEX レガシーモードでは Pause 中に Extension の Tick が止まり得ます（DenGo の実機で確認済み）。そのため次を **専用のバックグラウンドスレッド（制御プレーン）** で扱います。

- Enabled / Stop の監視、Ready の作成と撤回、BridgeAvailable、BridgeInfo（Phase B の計測ブロック）、PID 単位の名前付きオブジェクト管理、Dispose 要求。
- このスレッドは名前付きカーネルオブジェクトだけに触れます。**BveHacker・Scenario・Vehicle・TimeManager などの BVE 内部へは別スレッドから一切アクセスしません。** それらは Tick 上（トラッカー内）だけで読みます。
- Tick は制御プレーンのロックを取らず、volatile の `HandshakeUp` フラグだけを読みます（ロック順序の逆転なし）。

| 状況 | 動作 |
|---|---|
| Pause 中に TS Scoring OFF | 外部の ScenarioReady（Event と状態ブロック）と Ready を**即座に**撤回。内部の ScenarioReady レベルと世代は保持 |
| Pause 中に TS Scoring ON | Ready を**即座に**復帰。BVE データ（ScenarioReady）の再公開は**次の Tick まで待つ**（診断 `LEGACY_TICK_AFTER_HANDSHAKE_UP`） |
| Tick 再開後の最初の Tick | 保持していた同じ世代・同じレベルを再公開（`SR_PUBLISHED why=handshake-back`）。再成立はしない |
| Bridge Dispose | ScenarioReady を解除・撤回 → Ready を撤回（制御スレッドを停止）→ BridgeAvailable を撤回 |

## 5. ScenarioReady（Legacy での候補 E）

成立条件は Current と同じです：同じ ScenarioGeneration で ScenarioOpened と ScenarioCreated を受信済み、`IsScenarioCreated == true`、Scenario / TimeManager / LocationManager（位置が有限値）/ Vehicle が読め、Bridge が Dispose されておらず、TS Scoring が有効で Ready が成立している最初の **Tick**。
null・NaN・Infinity・例外は成立させず、次の安全な Tick で再試行します。推測では成立させません。

## 6. 配置（手動。この版では何も配置しません）

> **Rule: never place a DLL in the folder of the other host. The two products are exclusive per host (one BVE process loads exactly one host).**
> **Nothing is deployed automatically by this phase.**

| DLL | 置き場所 | 読み込むホスト |
|---|---|---|
| `TSScoringPlugin.Caller.InputDevice.dll` | BVE6 と BVE5 の `Input Devices` フォルダ（Current / Legacy 共用。1 個だけ） | どちらのモードでも同じ |
| `TSScoringPlugin.BveEx.Bridge.Prototype.dll` | `%PUBLIC%\Documents\BveEx\2.0\Extensions` | 通常の BveEX（Current）のみ |
| `TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll` | `%PUBLIC%\Documents\BveEx\Legacy\Extensions` | AtsEX レガシーモードのみ |

- 2 つの Extensions フォルダーは別のホストが別々に走査します。**両方に自分用の DLL を置くのは安全**（DenGo も同じ配置で実機確認済み）ですが、**片方の DLL をもう片方のフォルダーへ置いてはいけません**（相手のホスト参照を解決できずロードに失敗する見込みです。この動作は未検証のため、試さずに禁止とします）。
- モードは BVE プロセス単位で決まり、同一プロセス内で切り替わりません（BVE 再起動で戻ります）。Bridge はプロセスごとに 1 つだけ動き、名前付きオブジェクトは PID 単位なので衝突しません。
- 将来の配置スクリプトの要件: ホストごとに配置先を固定、DLL の参照アセンブリ（`BveEx.PluginHost` か `AtsEx.PluginHost`）を確認してから置く、不一致なら拒否、Caller は 1 個だけ、既存 DLL を退避、BVE 実行中は拒否、第三者 DLL は一切コピーしない、戻す手順を持つ。

## 7. 試験

- `Tests\Test-LegacyL1.ps1`（オフライン。実 Caller・実 Legacy DLL・実イベント引数。BVE も AtsEX ランタイムも Python も不要）
- `Tools\Verify-PhaseL1.ps1`（静的検査。Current 契約が基準コミットと同一であること、API の漏れがないこと、依存・個人情報・配布物の検査）
- Current 版の既存試験（Phase B / C1 / C3 / C3 静的検査）はそのまま通ります。`Tools\Verify-PhaseC3.ps1` は Current 製品だけを対象にするよう、ソース走査の範囲を 1 行だけ限定しました。

## 8. 限界と Phase L2 で確認すること

- オフラインでは AtsEX 実機のイベント順序・Tick 頻度・値の妥当性は確認できません。**特に、AtsEX が Extension を ScenarioOpened より後に読み込む場合**（読み込みがシナリオ読込ごと）は、Current と同じ規則「ScenarioOpened と ScenarioCreated の両方を同じ世代で受信」を満たせず、ScenarioReady は成立しません（`SR_CREATED_WITHOUT_OPEN` / `LATE_ATTACH` が診断に出ます）。推測で成立させない方針のため、L2 の実機ログで順序を確認してから扱いを決めます。
- 第三者の DLL は同梱せず、再配布しません。500 ms の依存案内と MessageBox は変更していません（Phase M1 で別途対応）。
