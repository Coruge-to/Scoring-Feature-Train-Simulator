# TS Scoring – Phase LI0（AtsEX Legacy の採点入力互換性の読み取り専用観測）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード** / バージョン: Legacy テレメトリ DLL **0.1.3.0**（L3 の 0.1.2.0 に観測だけを追加）。

LI0 は **観測だけ**を行う。HUD、Python、採点、UDP の内容、契約（トークン、AVAIL）は変更しない。観測結果は診断ログ（`TEL_*` 行）にだけ出る。

## 1. 実装

* `Telemetry\Legacy\src\LegacyInputProbe.cs`（ホスト非依存）。`ILegacyInputApi`（Try 系 4 メソッド、理由コードは固定語）越しに、Tick スレッドだけから 1 Tick 1 回呼ばれる。`ILegacyApi` は無変更。
* AtsEX / BveTypes の型を名指すのは従来どおり `LegacyTelemetryExtension.cs` の 1 ファイルだけ（アダプター側が `ILegacyInputApi` を実装）。
* ログ行: `TEL_INPUT_CAPABILITY` / `TEL_HANDLE_FIRST` / `TEL_HANDLE_CHANGE` / `TEL_SPEC_FIRST` / `TEL_SPEC_CHANGE` / `TEL_PRESSURE_FIRST` / `TEL_PRESSURE_CHANGE` / `TEL_INPUT_UNAVAILABLE` / `TEL_INPUT_SUMMARY`（すべて `gen=<scenarioId>` 付き）。
* 種類別の上限（HANDLE_CHANGE 36、PRESSURE_CHANGE 24、UNAVAILABLE 8）と世代あたり 80 行。値が変わらない間は行を増やさない。NaN / Infinity は取得不能として扱う。パス、自由文、例外文は出さない。
* ハートビートのスレッドからは到達しない。UDP の内容は観測有無にかかわらずバイト単位で同一（試験 `Test-LegacyInputLI0.ps1`）。

## 2. 実機で確認した内容（BVE5 + AtsEX）

| 項目 | 結果 |
|---|---|
| 1 ハンドル Ecb | `OneLeverCab` / `one-lever` / `Ecb`。逆転器、力行、制動、EB 境界を取得 |
| 2 ハンドル Ecb | `TwoLeverCab` / `two-lever` / `Ecb`。力行と制動を独立に取得 |
| 2 ハンドル Cl | `TwoLeverCab` / `Cl`、`powN=5 brkN=2 ebN=3 b67=1`、制動 0〜3 を観測 |
| 2 ハンドル Smee | `TwoLeverCab` / `Smee`、`powN=4 brkN=9 ebN=10 b67=8`。P0〜P4、N、B1〜B9、EB、逆転器 -1 / 0 / 1 |
| `PluginBase.Native` | 実機では **`native-null`**（`VehicleSpec` / `VehicleState` は読めない） |
| StateStore 経路 | 成立。観測した車両では `bcN=1`、`bpN=1` |
| 取りこぼし | `skipped=0`、不連続 `discontinuities=0`、`udpFailed=0` |
| 世代変更 | 世代が変わると観測状態が再初期化される |

### 2.1 Smee の圧力

* EB 状態では BCP 約 440 kPa、BPP 約 0 kPa。緩解後は BCP 約 0 kPa、BPP 約 490 kPa。常用制動の投入に伴い BCP が上昇する。
* 値の動きは BVE 公式の `BcPressure` / `BpPressure`（kPa）の契約、`MaximumPressure` 440000 Pa、`BpInitialPressure` 490000 Pa と整合する。
* 配列の長さが 0 / null は取得不能とする。**2 以上の場合の意味は推測しない**（観測した車両は長さ 1）。

## 3. 記録だけして実装しない方針（次 Phase の入力）

* Current の BveEX 契約を正本として最大限流用し、Legacy アダプターの中で **取得元、単位、汎用文字列**を正規化する。
* 車両定義の文字列を取得できない場合の汎用表示:
  * 1 ハンドル Ecb / Smee: 逆転器 後 / 中 / 前、ハンドル P0〜Pn / N / B1〜Bn / EB
  * 2 ハンドル Ecb / Smee: 逆転器 後 / 中 / 前、力行 P0〜Pn、制動 N / B1〜Bn / EB
  * 2 ハンドル Cl: 逆転器 後 / 中 / 前、力行 P0〜Pn、制動 切 / 重なり / 常用 / 非常
* **1 ハンドル Cl は対象外**。`unexpected` として安全側（取得不能）に扱う。
* 本 Phase ではこの接続を実装していない。

## 4. 検証と配置

* 試験: `Tests\Test-LegacyInputLI0.ps1`。既存の L3 / L1 / 統合試験は回帰として維持。
* 配置はこの文書の範囲外（DLL、PDB、ログはリポジトリに含めない）。
