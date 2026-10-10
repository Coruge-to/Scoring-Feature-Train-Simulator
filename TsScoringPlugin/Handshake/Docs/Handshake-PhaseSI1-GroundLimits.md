# Phase SI-1 — Legacy 送信側の地上制限契約（TRAINLEN / MAPLIMITS / CLEARDIST / 頭の MAPHEAD）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード** / バージョン: Legacy テレメトリ DLL **0.4.0.0**（SI-0 の観測専用ビルド 0.3.1.0 の次。**テレメトリ（UDP 54321）の内容が変わる製品ビルド**）。

SI-1 は **送信側だけ**を直す。Python 本番コード、採点接続、JUMP、54322、`bp_initial` 送信、Smee 仮想 EB、`update_logic`、F7/F8/F11/F12、P→P には触れない。BVE の公開 API を従来どおり Tick スレッドの安全な入口で**読むだけ**で、ホストを動かす・時刻を変える・ジャンプさせる呼び出しは無い。

## 1. 実機で確定している事実（SI-0 の実機ログ監査）

| 事実 | 根拠 |
|---|---|
| Legacy に Current の `VehicleLength` 相当の直接値は無い。編成長は `CarLength × (MotorCar + TrailerCar)` | 3 車両（18×1、18×8、13×1）でホストの尻の遷移距離が式の値と ±0.1 m で一致。`FirstCar` を足す案は 3 車両すべてで外れた |
| `CarInfo.Count` は double（0.5 が実在する） | 13 m 車両で 0.5/0.5/0.5 |
| 先行制限は `Scenario.Route.SpeedLimits`（整列済み、要素は `ValueNode<double>`、`Location` と `Value[m/s]` が公開）。5 リスト（5〜331 件）で読取り失敗 0、非整列 0、非 ValueNode 0 | `SI0_LIMITS_LIST` |
| ホストの現在制限は**尻基準**（`(尻, 頭]` の最小値）。下がる遷移は頭の通過で即時、上がる遷移は編成長ぶん遅れる | 連続走行で起きた遷移 7 件。決定的な 1 件: 45→70 の位置でリストの頭の値は 1000 なのにホストは 70 |
| したがってホストの現在制限は Current の `MAPTAIL` と同じ意味。Legacy が今まで送っていた `MAPHEAD`（`MAPTAIL` と同値）は**頭の制限ではなかった** | 同上 |

## 2. 契約

### 2.1 TRAINLEN（トークン `trainlen`）

`TRAINLEN = CarLength × (MotorCar + TrailerCar)`。毎 Tick 読む。次をすべて満たすときだけ送る: 3 つの数が読めて有限、`CarLength > 0`、`MotorCar ≥ 0`、`TrailerCar ≥ 0`、和 `> 0`、積が有限（桁あふれは不成立）。**`FirstCar` は読まない。固定の 20 m で補完しない。** 不成立の Tick はキーもトークンも書かない（前の Tick の値も書かない）。

Python は `max(TRAINLEN, 20)` で 20 m 未満を 20 に切り上げる（Current も同じ）。送信側は変えない。

### 2.2 MAPTAIL（トークン `maplimit`）

**変更しない。** ホストの現在制限 `Scenario.Route.SpeedLimits.CurrentLimit` をそのまま km/h にして送る。意味は Current の `MAPTAIL`（`(尻, 頭]` の最小値）と同じ。

### 2.3 MAPHEAD（トークン `maplimit`、キーは `MAPTAIL` と同じ群）

公開 API の `SpeedLimits` から計算した**頭の位置で有効な制限**: リストで位置以下の最後の要素の値（等しい位置では後の要素が勝つ）、該当要素が無ければ 1000（制限なし）。位置が要素に一致するときは頭側（`≤`）。

頭の制限を一意に求められない Tick（リストを読めない、整列されていない、要素が壊れている、位置が有限でない）は、**従来どおり `MAPHEAD = MAPTAIL`** へ戻す。推定値は送らない。この状態は Python では「尻待ちなし」になるため、青は点かない。

MAPHEAD だけの専用トークンは追加しない（Python の語彙 `telemetry_contract.TOKEN_KEYS` を変えられないため）。`MAPHEAD` が本物かどうかは、実際には同じ Tick で `maplimit_ahead` が成立しているかで見分けられる（同じリスト由来）。

### 2.4 MAPLIMITS と CLEARDIST（トークン `maplimit_ahead`、2 つで 1 群）

Current 送信側（`Class1.cs`）の式を**そのまま**移した（試験では Current 部分の文字どおりの移植 `CurrentReference` と 400 リスト × 4 位置で比較）。

* `MAPLIMITS`: `位置 > 現在位置` かつ `位置 ≤ 現在位置 + 3000` の要素を**リストの順**に `位置F1=km/hF1`（不変カルチャー）で `_` 連結。重複は Current と同じく**そのまま残す**。空の窓・空のリストは**空文字**（`MAPLIMITS:,CLEARDIST:0`、Current と同じ）。km/h は `Value × 3.6`、`Value` が無限・999 超・0 以下なら 1000。
* `CLEARDIST`: 尻位置 = 位置 − `TRAINLEN`。`(尻, 頭]` の最小値（尻の位置で有効な値を含む）が頭の制限より低いときだけ、頭の制限と等しい値が尻側へ続く最後の要素の位置と尻位置との差。それ以外は 0。書式は Current と同じ往復表記（微小な正の値が `6.8E-12` と書かれることがあるが、Current も同じで、Python の `float()` が読める）。

**成立条件**（すべて）: リストが完全に読めて検証済み、`TRAINLEN` が成立（`CLEARDIST` が編成長に依存するため）、同じ Tick に `maplimit` 群（`MAPTAIL`）が成立、窓内の要素が 500 件以下。成立しないときは `MAPLIMITS` も `CLEARDIST` も書かず、トークンも付けない（部分的な窓は送らない）。

### 2.5 リストの読み方（ホストに優しく、壊れたら使わない）

* 世代（シナリオ実行）ごとに 1 回、400 件／Tick の分割で読み、読み終わるまで `maplimit_ahead` と頭の MAPHEAD は成立しない（部分リストは使わない）。以降は**メモリ上の検証済みリスト**から計算する（BVE への読取りは要素数の確認だけ）。
* 1 件でも次に当てはまるとリスト全体を使わない: 要素を読めない／例外／位置が有限でない／値が NaN／`ValueNode<double>` でない／位置が前の要素より小さい（未整列）。無限値は「制限なし」で有効。20000 件超は使わない。
* 使わないと決めたリストは 60 Tick ごとに最初から読み直す（途中から続けない）。要素数が Tick の途中で変わったら、その Tick からリストを捨てて読み直す。

## 3. Availability とフォールバック（群ごとに独立）

| 状況 | `trainlen` | `maplimit_ahead` | `MAPHEAD` | `MAPTAIL` |
|---|---|---|---|---|
| すべて成立 | ○ | ○ | 頭の値 | ホスト値 |
| 車両の数が読めない／不正 | ✕ | ✕（`CLEARDIST` が作れない） | 頭の値 | ホスト値 |
| リストが読めない／壊れている／読込み中 | ○ | ✕ | `= MAPTAIL` | ホスト値 |
| 窓内が 500 件超 | ○ | ✕ | 頭の値 | ホスト値 |
| ホストの現在制限が読めない | ○ | ✕（`MAPTAIL` が無い） | `maplimit` 群ごと無し | 無し |

「世代境界」: シナリオ実行が変わる（Closed／Created／Opened／別の Scenario オブジェクト／Dispose）と、リスト・車両長・ログの状態を**すべて捨てる**。次の世代は、自分のリストと車両長が成立するまで、前の世代の `TRAINLEN` / `MAPLIMITS` / `CLEARDIST` / 頭の `MAPHEAD` を**一切書かない**。

## 4. 点滅の互換性（Python は無変更）

Python（`scoring_logic.update_physics_and_scoring`）は次のとき点滅する。Legacy の電文でそれが成立することを、**実物の Overlay／scoring_logic に実際の DLL の電文を流して**確認する（`tests/si1_flash_probe.py`）。

* **赤（地上）**: `MAPLIMITS` の候補が `effective_limit` より低く、警告距離（既存 Python の `decel_dist + v0×5 秒`）内。送信側は Python の計算を再実装しない。
* **青**: `MAPTAIL < MAPHEAD`、赤候補なし、`min(MAPHEAD, SIGLIMIT) > effective_limit`、頭が上昇境界を越え尻が未通過の間。
* 信号の赤（`FWDSIGLIMIT/LOC`）は変わらない（`MAPLIMITS` の有無に依存しない）。
* `MAPLIMITS` が無ければ地上の赤は出ない（候補が空）。`MAPHEAD` が本物でなければ（`= MAPTAIL`）青は出ない。どちらも捏造しない。

## 5. 診断ログ（Downloads の `TSScoring-L3-Telemetry.log`、状態の変化だけ。Tick ごとには書かない）

* `TEL_GROUND_LIST gen= state=ready count= scanTicks=` — リストを読み終えた
* `TEL_GROUND_UNAVAILABLE gen= group=list|trainlen|ahead reason=` — 成立しない理由（固定語。世代あたり理由ごとに 1 回）
* `TEL_GROUND_TRAINLEN gen= lengthM= carLenM= motor= trailer=` — 編成長（最初と変化時）
* `TEL_GROUND_CHANGE gen= loc= trainLen= head= tail= ahead= clearM=` — 頭の値・ホスト値（尻）・窓内件数・`CLEARDIST` の組が変わった位置（世代あたり 40 行まで）。**実機で head と tail の食い違い（青の区間）を確認するための行**。

数値と固定語だけ。経路・シナリオ・車両・駅の文字列は書かない。SI-0 の `SI0_LIMIT_CHANGE`（`headMatch`、`tailAMatch/BMatch`）も従来どおり同じログに出る。

## 6. 変更したもの

| 区分 | ファイル |
|---|---|
| 送信側（新規） | `Telemetry\Legacy\src\LegacyGroundLimits.cs`（読取り面 `ILegacyGroundApi`、純粋な契約 `LegacyGroundContract`、世代ごとの状態 `LegacyGroundTelemetry`） |
| 送信側（変更） | `LegacyTelemetrySession.cs`（配線。MAPHEAD の頭化、4 キーは上記ファイルの関数が書く）、`LegacyTelemetryExtension.cs`（`TryCarSpec` と、SI-0 のリスト読取りの再利用）、`AssemblyInfo.cs`（0.4.0.0）、`TSScoringPlugin.AtsExLegacy.Telemetry.csproj`（新規ソース 1 件）、共通契約 `Shared\TelemetryContract.cs`（トークン名 2 件の追加のみ） |
| 試験 | `Tests\Test-GroundLimitsSI1.ps1`（新規）、`Tests\TelemetryTestFixture.cs`（偽物と Current の文字どおりの移植を追加）、`tests\test_ground_limits_si1.py`、`tests\si1_flash_probe.py`（新規） |
| 既存試験の更新（弱めない） | 版数の許容に 0.4.0.0 を追加: LI0／LI1／LI2／SI-0／`Verify-PhaseL3.ps1`。LI1 の共有契約ガードは「HEAD と同一、または SI-1 の 2 トークンの追加だけ」。SI-0 の G09／G10 は SI-0 コミット（`3158ce2` → `f9b2ed5`）の履歴に固定。「送信しないトークン」の期待は `doortime,jump` へ（`trainlen` と `maplimit_ahead` が送信側の語彙に入った）。スコープ許可リストに SI-1 のファイルを追加: M1／`Verify-PhaseL1.ps1`／`Verify-PhaseL3.ps1` |
| 不変 | Current 送信側、Caller、両 Bridge、Handshake の共有プロトコル、Python 本番コード全部、`LegacyApi.cs`、ハンドル契約、入力テレメトリ、SI-0 の観測（`LegacyScoringProbe.cs`）、駅タイムライン |

## 7. 設計判断（確認してほしいもの）

1. **`CLEARDIST` が編成長に依存するため、`trainlen` が不成立なら `maplimit_ahead` ごと外す。** `MAPLIMITS` だけ送ると `maplimit_ahead` トークンが虚偽になる（2 キーで 1 群）。固定 20 m での補完もしない。この車両で実機では起きていない（読取り失敗 0）。
2. **`maplimit_ahead` はホストの現在制限（`MAPTAIL`）が読めた Tick にだけ付ける。** `MAPTAIL` が無いまま候補だけ送ると、候補が「現在の制限より低い」と誤判定されうる。
3. **未整列・非 ValueNode・NaN はリスト全体を不使用にする。** 一部だけ使う・並べ替えて使う、は Current の式（整列済みを前提）と食い違うため採らない。実機の 5 リストはすべて整列済みで 0 件。
4. **窓内 500 件超は送らない（切らない）。** 実機の最大リストは 331 件（路線全体）で、3000 m の窓では桁違いに小さい。
5. **Python 側の既存の性質（変更しない）**: ある群が**同じ世代の途中で**成立しなくなったとき、Python は受け取らなかったキーを更新しないので、最後に受け取った値（例: 最後の `MAPLIMITS`）が残る。世代が変わると（管理モードの厳格ゲートが）既定値へ戻す。送信側は不成立の Tick にキーを書かず（中立値の偽の送信もしない）、リストは世代の途中で壊れにくい（要素数の変化と読取り失敗のときだけ）。
6. **位置ジャンプ直後**はホストの現在制限がジャンプ先の値へ切り替わるため、リスト由来の頭の値と一時的に食い違いうる（SI-0 の C／D3 で確認した不連続）。`MAPTAIL` はホストの値のまま使い続ける。

## 8. 実機で必要な再試験（BVE5 Legacy。Claude は配置・起動しない）

* **R-A（赤・地上）**: 地上制限が下がる手前（例: 70→50）で、約 150〜300 m 手前から赤く点滅すること。`TEL_GROUND_CHANGE` の `ahead>0`。
* **R-B（青・尻待ち）**: 制限が**上がる**境界（例: 45→70、50→90）を頭が越えたあと、尻が越えるまで青く点滅し、尻が越えると消えること。`TEL_GROUND_CHANGE` に `head > tail` の行があること。
* **R-C（信号の赤が壊れていない）**: 従来どおり信号制限の手前で赤。
* **R-D（TRAINLEN）**: ログの `lengthM` が実編成長（18×8 = 144 など）と一致。HUD の停止範囲が Current と同じ考え方で出ること。
* **R-E（世代）**: 別シナリオ・別車両の再選択後、最初の行から新しい `lengthM` と新しいリスト（`TEL_GROUND_LIST` が再度出る）。
