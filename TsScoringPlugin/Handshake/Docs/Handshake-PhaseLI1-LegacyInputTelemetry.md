# TS Scoring – Phase LI1（AtsEX Legacy 入力テレメトリ本接続）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード** / バージョン: Legacy テレメトリ DLL **0.2.0.0**（LI0 の 0.1.3.0 は読み取り専用観測版）。

LI1 は、LI0 の実機観測で確定した入力（ハンドル位置、ハンドル形式、ノッチ構成、ブレーキ管圧力）を、**Current（BveEX）の既存テレメトリ契約**でそのまま送信し、既存の Python 受信と HUD まで成立させる。**採点ロジックには接続しない。**

## 1. 方針

* Current の行名（`REV` `POW` `BRK` `HTYPE` `ALLTXT` `BCP` `BPP`）、Python の parser、`telemetry_contract`、HUD、AVAIL、世代ゲート、Session / Driving、ハンドル表示ロジックを**そのまま**使う。Legacy 専用の HUD・Python 処理は作らない。Python（本番ファイル）は 1 行も変更していない。
* 差異は Legacy アダプター側（`Telemetry\Legacy\src`）で正規化する。Legacy では車両定義の文字列が公開 API から取得できないため、**数値から汎用表示を生成**する。
* 生成できないものは送らず、AVAIL にも載せない（既存の「全部あるか、全くないか」規則）。既定値や前 Tick・前世代の値は使わない。

## 2. 実装の構成

| ファイル | 内容 |
|---|---|
| `Telemetry\Legacy\src\LegacyHandleContract.cs`（新規） | ハンドル群（REV POW BRK HTYPE ALLTXT）を `LegacyHandleSnapshot` から生成。ホスト非依存。固定理由語で「作らない」を返す。 |
| `Telemetry\Legacy\src\LegacyInputTelemetry.cs`（新規） | Tick ごとの読み取り、ハンドル群と BCP / BPP の組み立て、状態変化だけの診断、世代ごとの集計。`LegacyInputTickCache`（Tick あたり 1 回の読み取りを観測と共有）、`LegacyPressureContract`（配列の縮約規則）。 |
| `Telemetry\Legacy\src\LegacyTelemetrySession.cs` | 入力群を行へ追加する数行（`Compose`）。世代の開始・終了への接続。 |
| `Telemetry\Shared\TelemetryContract.cs` | トークン定数 3 個（`handle` `bcp` `bpp`）の追加のみ。Python 側語彙に既存のトークン名。 |
| `Telemetry\Legacy\src\AssemblyInfo.cs` / `.csproj` | 版 0.2.0.0、新規 2 ファイルの追加。 |

`LegacyApi.cs` / `LegacyInputProbe.cs` / `LegacyTelemetryExtension.cs`（ホストアダプター）は**変更なし**。AtsEX / BveTypes の型を名指すのは従来どおりアダプター 1 ファイルだけ。BVE の API は Tick スレッドからだけ読む（ハートビートのスレッドは触らない）。非公開 API・Harmony・unsafe・リフレクションは使わない。

## 3. ハンドルの汎用表示

入力は LI0 で確定した値だけ: 逆転器 `-1 / 0 / 1`、力行ノッチ、ブレーキノッチ、`PowerNotchCount`（n）、`BrakeNotchCount`、`EmergencyBrakeNotch`（e）、`HasHoldingSpeedBrake`。**EB の境界は常にホストが報告する `EmergencyBrakeNotch` を使い、ノッチ数から導かない。**

| 形式 | REV | POW | BRK | ALLTXT（逆転器 : 力行 : 制動 : 抑速） |
|---|---|---|---|---|
| 1 ハンドル Ecb / Smee | 後 / 切 / 前 | 位置 0 は `N`、位置 k は `Pk` | 0 は `N`（1 ハンドルの中立）、k は `Bk`、e 以上は `EB` | `後_切_前 : N_P1…Pn : N_B1…B(e-1)_EB :`（末尾は空の抑速） |
| 2 ハンドル Ecb / Smee | 同上 | `P0`…`Pn` | `B0` / `B1`…`B(e-1)` / `EB` | `後_切_前 : P0_P1…Pn : B0_B1…B(e-1)_EB :` |
| 2 ハンドル Cl（powN=5 brkN=2 ebN=3） | 同上 | `P0`…`P5` | 0 運転 / 1 重なり / 2 常用 / 3 以上 非常 | `後_切_前 : P0…P5 : 運転_重なり_常用_非常 :` |

* 書式は Current と同一: `REV:<text>:<-1|0|1>`、`POW:<text>:<notch>`、`BRK:<text>:<notch>:<e>`、`HTYPE:<1|2>`、`ALLTXT:…`。`HTYPE` は `ALLTXT` より前に書く（Python は `HTYPE` を見て 1 ハンドルの制動文字列幅を決める）。
* 逆転器は全形式共通で `-1` 後 / `0` 切 / `1` 前。1 ハンドルの中立 `N` と 2 ハンドル Ecb / Smee の制動 0 `B0`、Cl の制動 0 `運転` と逆転器の `切` は別の語。（表示語の受入れ前修正: 逆転器 0 は旧「中」→「切」、2 ハンドル Ecb / Smee の制動 0 は旧 `N`→`B0`、2 ハンドル Cl の制動 0 は旧「切」→「運転」。DLL 版は 0.2.0.0 のまま。）
* 日本語の語は `\u` エスケープで保持（文字コードに依存しない）。

**ハンドル群を作らない（AVAIL に `handle` を載せない）条件**（固定理由語）:

| 理由語 | 条件 |
|---|---|
| `type-unknown` / `brake-unknown` | 1 / 2 ハンドルまたは Ecb / Smee / Cl が判別できない |
| `one-lever-cl` | **1 ハンドル Cl（製品対応対象外）** |
| `rev-missing` `pow-missing` `brk-missing` `layout-missing` | 値が読めない |
| `hold-missing` / `holding-unconfirmed` | 抑速ブレーキが読めない / **ある車両**（抑速の段名・文字列が本ホストで未確認のため作らない） |
| `layout-range` | 段数が 0〜99 の範囲外 |
| `eb-layout` | Ecb / Smee で `EmergencyBrakeNotch` が `BrakeNotchCount + 1` でない（B1…Bn と EB が並ばない） |
| `cl-layout` | Cl で brkN=2 / ebN=3 以外 |
| `rev-range` `pow-range` `brk-range` | 逆転器が -1〜1 外、力行が 0〜n 外、制動が負 |

## 4. 圧力（BCP / BPP）

* 取得元: `Scenario.Vehicle.Panel.StateStore.BcPressure / BpPressure`（`Double[]`、実機の長さは 1、要素 0 が kPa）。
* **長さ 1 かつ有限値のときだけ**要素 0 を送る。`null` / 長さ 0 / 長さ 2 以上 / NaN / Infinity は送らず、トークンも載せない。**長さ 2 以上を要素 0 へ縮約しない**（意味が未確認）。
* 単位は kPa のまま変換しない（1000 倍・1000 分の 1 をしない）。書式は Current と同じ小数 1 桁（`BCP:440.0`）。`BPP` は圧力のみ（`BPP:490.0`）。
* `bcp` と `bpp` は別トークンで、片方だけ成立してもよい。
* **まだ送らない**: `bp_initial`（`BPP` の第 2 フィールド）、`BpInitialPressure`、圧力レート、Smee 仮想 EB 状態、採点結果、車両長、MAPLIMITS、車両設定ファイルのパス・内容。

## 5. AVAIL と世代

* 毎 Tick、ホストから読み直して組み立てる。前 Tick・前世代の値と可用性は持ち越さない（診断用の状態は世代開始で破棄）。
* 完全に作れた群だけが行とトークンに現れる。全部成立の行は 14 トークン（L3）に `handle` `bcp` `bpp` を加えた 17 トークン。最初の 1 行は `calcg`（加速度の基準なし）がないので 16。
* 新世代の最初のテレメトリ前は HUD を表示しない（既存の世代ゲート）。Python の新シナリオ検知でハンドル・圧力・レイアウト（ALLTXT 由来の幅）は既定値へ戻る。

## 6. ライフサイクル（変更なし）

1 BVE プロセスにつき管理 Python 1 回。soft OFF・Pause・シナリオ終了後のシナリオ選択画面待機では Python を止めない。再選択・再読込は同じ Python で新世代。Dispose で正常終了、親 BVE 消失時は Python が自律終了し UDP 54321 を解放する（P1）。Caller / Bridge は変更していない。

## 7. 採点の分離（監査結果）

* 管理モード（Legacy の製品経路）では `is_scoring_mode` は一度も `True` にならない（キーフックもメニューもない）。`add_score_popup` は `is_scoring_mode` が偽なら `force` なしでは何もしない。得点・内訳・ポップアップ・結果の更新はすべてこれを通る。
* ただし HUD 用の物理処理（`update_physics_and_scoring`）は管理モードでも常に動き、ハンドル・圧力を**簿記用の内部状態**（手動 EB 累積、Smee 仮想 EB フラグ、前回ノッチ、基本制動の状態）へ読み込む。これは Current が従来から行っている経路と同一で、得点・ポップアップは変わらない。試験（`tests\test_legacy_input_li1.py` C 群）で、同じ走行をハンドル・圧力あり／なしで行い、得点状態が完全に一致し 0 のままであること、EB 保持時に -500 の要求が出ても全て拒否されることを確認している。
* 通常モード（`python main.py`、キーフックあり）に Legacy の送信を流せば、採点は実データで動く。Legacy の製品経路は管理モードであり、通常モードでの Legacy 採点は本 Phase の対象外。採点接続は別 Phase で行う。

## 8. 診断（専用診断ログ `TSScoring-L3-Telemetry.log`）

状態変化だけを書く（Tick ごとには書かない）。世代あたり 24 行まで、超過分は集計行の `suppressed` に数える。数値と固定語だけ（パス・自由文・例外文なし）。

```
TEL_HANDLE_SEND   gen=<id> layout=<one|two>-lever-<ecb|smee|cl> powN=<n> brkN=<n> ebN=<n>
TEL_HANDLE_DROP   gen=<id> reason=<固定語>
TEL_PRESSURE_SEND gen=<id> group=<bcp|bpp>
TEL_PRESSURE_DROP gen=<id> group=<bcp|bpp> reason=<array-null|array-empty|array-multi|nonfinite|…> [len=<N>]
TEL_INPUT_PUBLISH gen=<id> ticks=<N> handleSent=<N> handleDropped=<N> bcpSent=<N> bcpDropped=<N> bppSent=<N> bppDropped=<N> suppressed=<N>   （世代の終わりに 1 行）
```

LI0 の観測行（`TEL_INPUT_CAPABILITY` `TEL_HANDLE_FIRST` `TEL_PRESSURE_FIRST` など）は従来どおり書かれる。入力面の読み取りは **Tick あたり 1 回**（観測とテレメトリが共有）。

## 9. バージョン

0.1.3.0 は読み取り専用観測版で、本 Phase で handle / pressure を製品契約として正式公開するため **0.2.0.0**（マイナー更新）。Caller / Current Bridge / Legacy Bridge / Current Telemetry は変更なし。

## 10. 試験

* `tests\test_legacy_input_li1.py`（Python）: 汎用表示の契約、実 Overlay（offscreen）での全組合せの受信と描画、未宣言の群は描かれないこと、新世代で残らないこと、採点分離、Python に Legacy 分岐がないこと。`tests\legacy_input_reference.py` は同じ規則を独立に記述した参照表。
* `Tests\Test-LegacyInputLI1.ps1`: 実 DLL を偽の Legacy API で駆動。C# 契約と参照表 1350 件の一致、全レイアウトのセッション出力、配列 null / 0 / 1 / 2 以上 / NaN / Infinity、単位無変換、AVAIL、世代切替、Pause・再選択・再読込、診断、実 Python reader と実 Overlay、**32 ビット**プロセスでの同一バイト出力、凍結ファイルの不変。
* 既存の E1〜E4 / L1〜L3 / LI0 / P1 / 実 `main.py` 統合は回帰として維持（LI0 の「観測だけで配信は不変」を証明していた G01〜G03・H03・H05・D08 は、本 Phase の契約変更に合わせて更新した）。

## 11. 実機試験計画

別紙（作業報告）に A〜G を記載。内部状態の目視確認は求めず、HUD の表示（読める文字）とログ監査で判定する。管理モードにはキーフックがないため、BCP / BPP は HUD ではなくログ（`TEL_PRESSURE_SEND`、LI0 の `TEL_PRESSURE_CHANGE`）で確認する。

## 12. 未確認事項

* 抑速ブレーキ付き車両の段名・文字列、1 ハンドル Smee の実車、`StateStore` 配列長 2 以上の意味。
* 通常モード + Legacy の採点（本 Phase の対象外）。
* HUD のデバッグ表示（F2、通常モードのみ）の `BPP: x / <しきい値>` は、`bp_initial` を送らないため Python の既定値（490）から計算される。管理モードでは表示されない。
