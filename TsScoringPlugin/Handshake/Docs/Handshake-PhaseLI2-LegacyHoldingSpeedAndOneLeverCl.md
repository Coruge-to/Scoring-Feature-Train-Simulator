# TS Scoring – Phase LI2（AtsEX Legacy 抑速ハンドルと 1 ハンドル Cl）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード** / バージョン: Legacy テレメトリ DLL **0.3.0.0**（LI1 の 0.2.0.0 は抑速車と 1 ハンドル Cl を送らない版）。

LI2 は LI1 のハンドル表示契約の拡張で、次の 3 つを **Current（BveEX）の既存テレメトリ契約**（`REV` `POW` `BRK` `HTYPE` `ALLTXT`、AVAIL `handle`）のまま送る。**採点には接続しない。** `bp_initial`・Smee 仮想 EB・P→P 処理・`main.py` 管理起動時期・Python 本番コード・Caller・Bridge・Current Telemetry は変更しない。

## 1. 二つの「抑速」は別機能、そして 24 通りの契約表（正本）

| | A. ブレーキ 1 段目の抑速 | B. 独立抑速ノッチ H1〜Hn |
|---|---|---|
| 判定 | `NotchInfo.HasHoldingSpeedBrake == true` | `NotchInfo.HoldingSpeedNotchCount`（車両設定 n > 0。**ホストは符号反転して `-n` を返す**） |
| 位置 | ブレーキ側 `brk = 1` | 力行側 `pow = -1 … -n`（**2 ハンドルだけ**） |
| 表示 | BRK 欄に「**抑速**」 | POW 欄に **H1〜Hn** |
| 有効な組合せ | 全ハンドル形式・全ブレーキ方式 | 2 ハンドルの全ブレーキ方式（Cl を含む）、A と同時に有効 |

実機（BVE5 本体）で、公開車両パラメーターの直積 **ハンドル形式（OneLeverCab / TwoLeverCab）× ブレーキ方式（Ecb / Smee / Cl）× HoldingSpeedNotchCount（0 / 正値）× HoldingSpeedBrake（false / true）= 24 通り**（人工車両を含む）がすべてエラーなく受理されることを確認した。この 24 通りの実測規則が正本で、**24 通りすべてを送信する**（拒否理由 `holding-unconfirmed` / `holding-cl` は廃止）。機械可読な参照表は `tests\legacy_input_matrix24.json`（`tests\legacy_input_reference.py` の `matrix_rows()` が出力）。

実機観測の例:

* A（2 ハンドル Ecb、`powN=5 brkN=8 ebN=9 hold=1`）: `brk=0 B0 → 1 抑速 → 2 B1 … 8 B7 → 9 EB`。
* B（2 ハンドル Smee、独立抑速 5 段）: `HoldingSpeedNotchCount` は **`-5`**（候補 0.3.0.0 は `+5` を前提にして全 Tick を落とした。§2）。`P0〜P5 → pow=0〜5`、`H1〜H5 → pow=-1〜-5`。独立抑速中は `brk` が直前値を保持することがある。
* 1 ハンドル（`[OneLeverCab]`）車は、独立抑速の設定があっても H 段が操作範囲に現れない（`pow >= 0`、`brk = 0〜EmergencyBrakeNotch`。`pow < 0` は一度も出ない）。抑速ブレーキありの人工 1 ハンドル Smee は `pow=0〜5 brk=0〜9`（`holdBrake=1`）。

### 24 通りの表示（n = PowerNotchCount、b = BrakeNotchCount、e = EmergencyBrakeNotch、h = 独立抑速の段数 = −HoldingSpeedNotchCount）

| ハンドル | ブレーキ | 抑速ブレーキ false | 抑速ブレーキ true |
|---|---|---|---|
| 1 ハンドル（設定の有無は結果に影響しない: 各 2 通り） | Ecb / Smee（別ケース） | POW `N`(pow 0) / `P1…Pn`、BRK `N`(brk 0) / `B1…Bb` / `EB` | POW 同左、BRK `N` / **`抑速`**(brk 1) / `B1…B(b-1)` / `EB` |
| 1 ハンドル | Cl | POW `運転`(pow 0) / `P1…Pn`、BRK `運転` / `重なり` / `常用` / `非常` | BRK `運転` / **`抑速`**(brk 1) / `常用` / `非常` |
| 2 ハンドル（独立抑速なし / あり: 各 2 通り） | Ecb / Smee（別ケース） | POW `P0…Pn`（あり: `H1…Hh` も）、BRK `B0` / `B1…Bb` / `EB` | BRK `B0` / **`抑速`** / `B1…B(b-1)` / `EB` |
| 2 ハンドル | Cl | POW 同上、BRK `運転` / `重なり` / `常用` / `非常` | BRK `運転` / **`抑速`** / `常用` / `非常` |

* ALLTXT = 逆転器 `後_切_前` : 力行（`P0…Pn` または 1 ハンドルの `N`/`運転`＋`P1…Pn`） : 制動（`brk` 位置 0〜e の語、1 ハンドルは e+1 個、Cl は 4 個） : 独立抑速 `H1_…_Hh`（2 ハンドルで h > 0 のときだけ。他は空）。
* 位置: 2 ハンドルの `pow` は `-h … n`、1 ハンドルは `0 … n`。`brk` は `0 … e`（`e` が EB / 非常）。**2 ハンドルは力行とブレーキが同時に正でよい。1 ハンドルは同時に正を作らない。**
* 1 ハンドル Cl の静止位置の語は「運転」（以前の候補は「切」。逆転器の「切」と別語になった）。

実機観測（LI0 / LI2 ログ）の補足: 候補 0.3.0.0 の 2 ハンドル Smee 独立抑速 5 段が `-5` を返したため、個数は符号反転して読む（§2）。

## 2. 表示契約の要点

`HoldingSpeedNotchCount` は公開 API（`BveTypes.ClassWrappers.NotchInfo.HoldingSpeedNotchCount`）から読む。**`PowerNotchCount` で代用しない。**

**符号（LI2 実機再試験で確定）**: ホストは抑速ノッチの個数 n を **`-n`** で保持し返す。BVE5 の車両定義読込（`holdingspeednotchcount` / `holdingnotchcount` キー）が値を `neg` して格納し、力行ハンドル入力は `Min(Max(入力, 格納値), PowerNotchCount)` で下限として使うため（BveTs.exe 5.8.7554.391 の IL で確認。公開 API のラッパーは値を加工しない）。アダプターは値を**そのまま**スナップショットへ渡し、符号の解釈は契約（`LegacyHandleContract`）だけが行う: `0` = 独立抑速なし、`-1…-99` = その段数 n（`h = -値`）、`+1 以上` / `-100 以下` / 読めない = 個数ではない（`hold-range` / `holdn-missing`、推測しない）。

個数として使えない場合でも、`pow >= 0` の位置と制動は個数に依存しないので、**その位置では通常どおりハンドル群を作る**（抑速テキスト欄は空）。作らないのは `pow < 0`（H 段）の位置だけ（位置単位のフォールバック）。

* 書式は Current と同一。`POW:H3:-3` のように負の段も Current の `int(...)` でそのまま読める。HUD は `pow < 0` を既存の色（抑速側）で描く。
* EB の境界は常にホストの `EmergencyBrakeNotch`（Ecb / Smee は `BrakeNotchCount + 1` を前提とし、違えば `eb-layout`。Cl は `BrakeNotchCount=2`・`EmergencyBrakeNotch=3` 以外は `cl-layout`）。`brk` が EmergencyBrakeNotch を**超える**値は位置ではないので `brk-range`（以前は EB 扱い）。
* 1 ハンドルで独立抑速の設定があるだけではハンドル群を拒否しない。`pow < 0` が来た未知のケースだけ `pow-range`。1 ハンドル専用の H 表示は実装しない。1 ハンドルは力行・制動が同時に正なら `pow-brk-both`（以前は 1 ハンドル Cl だけ。単一ハンドルでは起こらない状態）。

**ハンドル群を作らない条件**（固定理由語）:

| 理由語 | 条件 |
|---|---|
| `type-unknown` `brake-unknown` `rev-missing` `pow-missing` `brk-missing` `layout-missing` `hold-missing` | 判別・読取り不能（LI1 と同じ） |
| `holdn-missing` / `hold-range` | 2 ハンドルの **`pow < 0` の位置だけ**: `HoldingSpeedNotchCount` が読めない / `-99…0` の範囲外（`+1` 以上、`-100` 以下） |
| `layout-range` `eb-layout` `cl-layout` `rev-range` | LI1 と同じ |
| `brk-range` | `brk < 0`、または `brk > EmergencyBrakeNotch` |
| `pow-range` | `pow > n`、2 ハンドルで `pow < -h`、1 ハンドルで `pow < 0` |
| `pow-brk-both` | 1 ハンドルで力行・制動が同時に正 |

**廃止した理由語（歴史）**: `one-lever-cl`（LI2 で 1 ハンドル Cl に対応）、`holding-unconfirmed`（1 ハンドル + 抑速ブレーキ）、`holding-cl`（Cl + 抑速ブレーキ）— 24 通りの実測により LI2 最終版で解除。過去のログにこれらが現れることがある。

## 3. 実装の構成

| ファイル | 変更 |
|---|---|
| `Telemetry\Legacy\src\LegacyHandleContract.cs` | 契約の拡張（上表）。`LegacyHandleLine` に独立抑速テキスト欄と診断用の値。 |
| `Telemetry\Legacy\src\LegacyInputProbe.cs` | `LegacyHandleSnapshot.HoldingSpeedNotchCount` を 1 メンバー追加。`TEL_HANDLE_FIRST` の静的部に診断語 `holdN` `holdBrake` `holdSource` `holdValidity` を追記（観測ロジック・行数・イベントは不変）。 |
| `Telemetry\Legacy\src\LegacyTelemetryExtension.cs` | ホストアダプターに公開プロパティの読取り 1 行（`info.HoldingSpeedNotchCount`）。 |
| `Telemetry\Legacy\src\LegacyInputTelemetry.cs` | `TEL_HANDLE_SEND` 行に `holdN=` / `holdPos=1` を追記（該当しないレイアウトは LI1 と同じ行）。`TEL_HANDLE_DROP` の `holdn-missing` / `hold-range` に値・取得元・妥当性の診断語。 |
| `Telemetry\Legacy\src\AssemblyInfo.cs` | 版 **0.3.0.0**。 |

`LegacySession` / `LegacyApi` / `.csproj` / `Shared\TelemetryContract.cs` / Python 本番ファイル / Caller / Bridge / Current Telemetry は変更なし。BVE の API は Tick スレッドからだけ読む。非公開 API・Harmony・unsafe・リフレクション・別スレッド読取り・車両設定ファイルの直接読込みは使わない。

## 4. 診断（`TSScoring-L3-Telemetry.log`、状態変化だけ）

```
TEL_HANDLE_FIRST gen=<id> cab=… hold=<0|1> b67=<n> holdN=<ホスト値|missing> holdBrake=<0|1|na> holdSource=notchinfo holdValidity=<ok|missing|range> rev=… pow=… brk=…
TEL_HANDLE_SEND gen=<id> layout=<one|two>-lever-<ecb|smee|cl>[-holdbrake] powN=<n> brkN=<n> ebN=<n> [holdN=<ホスト値>] [holdPos=1] [holdN=<missing|値> holdValidity=<missing|range>]
TEL_HANDLE_DROP gen=<id> reason=<上表の固定語> [holdN=<ホスト値|missing> holdSource=notchinfo holdValidity=<ok|missing|range>]   ← holdn-missing / hold-range のときだけ
```

* `holdN=` は **ホストが返した値そのもの**（符号付き。5 段なら `-5`）。`holdValidity` は値の妥当性（`ok` = `-99…0`）。`holdSource=notchinfo` は読取り元が公開 API `NotchInfo.HoldingSpeedNotchCount` であること（`PowerNotchCount` ではない）。`holdBrake` は `HasHoldingSpeedBrake`（`hold=` と同値。`holdPos` は SEND で「pow < 0 の位置」の意味なので使わない）。
* `TEL_HANDLE_SEND` の `holdN=` は 0 以外の妥当な値のときの記録（1 ハンドルなど表示に使わない形式でも「設定は読めたが無視した」ことを監査できる）。個数として使えない値は `holdN=<値> holdValidity=<...>` を付ける。
* `holdPos=1` は 2 ハンドル独立抑速車で `pow < 0` の間（H 段に入る・出るごとに 1 行）。
* 例: 独立抑速車 `layout=two-lever-smee powN=5 brkN=8 ebN=9 holdN=-5` → H 段で `… holdN=-5 holdPos=1` → 戻って P で再び `… holdN=-5`。

## 5. 試験

* `tests\legacy_input_reference.py`: 独立記述の参照表。規則関数 `expected_handle`（10 値入力）と、24 通りを 1 件ずつ全文展開した `matrix_rows()`（`legacy_input_matrix24.json` と同一であることを試験で確認）。Ecb と Smee は別ケース。
* `tests\test_legacy_input_li2.py`（Python）: 24 通りの全列挙（`I_The24Combinations`: 全位置・不正値・同時正値・独立抑速・1 ハンドルの設定・ホスト値の別の値）、実 Overlay（offscreen）で 24 通りを 1 世代ずつ受信・描画、`-5` の実機系列（`H_RealMachineSign`）、Python 本番に抑速分岐がないこと。
* `Tests\Test-LegacyInputLI2.ps1`: 実 DLL を偽の Legacy API で駆動。リテラル期待値、**M 節: 24 通りを `legacy_input_matrix24.json` と C# 契約・セッション出力で突き合わせ（正規系列 handleDropped=0、不正値は群なし＋復帰、24 世代連続切替、使えない個数のフォールバック）**、R 節（実機 `-5`）、実 Python reader / Overlay、**32 ビット**同一バイト（24 通り + 使えない個数）、凍結ファイル・差分範囲の検査。
* `Tests\Test-LegacyInputLI1.ps1`: 参照表（全 24 通りを含む 10 値入力の全ケース）との一致。旧契約（`holding-*` 拒否、Cl の「切」、brk > EB を EB 扱い）を前提にした箇所は新契約に更新した。バージョン検査は LI0 / LI1 / Verify-PhaseL3 とも 0.3.0.0。

## 6. 未確認事項

* 24 通りの **HUD 実機表示**（人工車両のうち、実機で HUD まで確認していない組合せ）。
* `HasHoldingSpeedBrake` 車の `HoldingSpeedNotchCount` の実測値（実機ログ `TEL_HANDLE_FIRST` の `holdN=` で確認する）。
* 候補 0.3.0.0 の失敗原因: 個数の符号を「正」と仮定し、テスト（フィクスチャ・参照表とも）にも正の値を入れていたため、実機の `-5` を `hold-range` として全 Tick 落とした。ホスト値の符号はホスト側 IL で確認し、実機値（`-5`）をテストに固定した。
* 1 ハンドル Smee の実車、`StateStore` 配列長 2 以上の意味。
