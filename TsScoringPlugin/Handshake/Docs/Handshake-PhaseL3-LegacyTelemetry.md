# TS Scoring – Phase L3（AtsEX Legacy の HUD テレメトリ）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード**（BVE6 の Current 経路は無変更）/ バージョン: テレメトリ DLL **0.1.1.0**（0.1.0.0 は L3-live で下記 §9 の不具合が判明したため置換）、Caller は無変更（0.11.0.0）。

この版で、E4 監査（`Handshake-PhaseE4-LegacyTelemetryAudit.md`）が指摘した「Legacy には HUD へ実データを送る経路が無い」を、**オフラインで検証できる範囲で**解消した。
BVE5 の実機では 0.1.0.0 で L3-live を行い、シナリオ同一性の不具合（§9）が見つかって修正した。0.1.1.0 の L3-B 再試験は未実施。**修正版 DLL の配置、push、実機起動は行っていない。**

## 1. 構成（制御プレーンとデータプレーンの分離）

| プレーン | 役割 | Legacy の実体 | 状態 |
|---|---|---|---|
| 制御プレーン（Handshake） | Ready / ScenarioReady / ScenarioGeneration、Session・Driving の公開、Python の起動と停止 | `TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll`（L1）+ Caller | **無変更** |
| データプレーン（HUD テレメトリ） | BVE の値を UDP 127.0.0.1:54321 で Python へ送る | **`TSScoringPlugin.AtsExLegacy.Telemetry.dll`（新規、独立）** | 新規 |
| 受信側 | 契約の検証、世代との対応、項目別の表示可否、HUD | `telemetry_contract.py` / `telemetry_gate.py` / `managed_hud.py` / `hud_ui.py` / `main.py` | 追加・最小変更 |

### 1.1 なぜ既存 Legacy Bridge に混ぜず、独立 DLL にしたか（監査結果）

* **ライフサイクルが違う。** Bridge は TS Scoring の ON/OFF（Enabled / Stop）に従って Ready を出し入れする。テレメトリは BVE のシナリオと Tick にだけ従い、TS Scoring の状態を知らない。混ぜると「TS Scoring OFF でも送るか」を Bridge の状態機械に持ち込むことになる。
* **責務が違う。** Bridge のソースは「ソケットを一切使わない」ことを静的に保証している（E4 の監査試験）。ソケットを使う送信側を同じ DLL に入れるとこの保証が壊れる。
* **回帰の範囲。** Bridge（C3/L1）と Caller（E4）は実機受入済みまたは受入待ちで、ハッシュを固定している。DLL を分ければ両者は**1 バイトも変わらない**（Caller 1B2F7C1F…、Current Bridge 247F6724…、Legacy Bridge C2883E40…）。
* **配置の安全性。** 独立 DLL は 1 個足すだけで、外せば元に戻る。失敗しても制御プレーン（Ready / ScenarioReady / Python の起動）は影響を受けない。逆に Bridge が無くてもテレメトリは送られる（Python が無ければ単に捨てられる）。
* **コードの共有はしない。** テレメトリ DLL は Handshake のソースを 1 つもリンクしない（`HandshakeProtocol` / `ObservationLog` / `ScenarioReady*` を含まない）。名前付きオブジェクトも使わない。

### 1.2 Current / Legacy の分離

* Legacy 固有（`AtsEx.*`、`BveTypes.*`、`LocationManager` …）は **`Telemetry\Legacy\src\LegacyTelemetryExtension.cs` の 1 ファイルだけ**。
* それ以外（契約、単位変換、駅の状態機械、ライフサイクル）はホスト非依存で、`ILegacyApi`（素の値だけの読取り面）越しに動く。オフライン試験は `ILegacyApi` の偽物で駆動する。
* **Current API（`BveEx.*`）はテレメトリプロジェクトのどこにも現れない**（試験 X02/X03）。Current 送信側（`TsScoringPlugin\Class1.cs`）は**無変更**で、AVAIL を送らない（Python は「AVAIL 無し＝全項目あり」として従来どおり扱う）。
* 契約の C# 側（`Telemetry\Shared\TelemetryContract.cs`）は将来の Current 送信アダプターがそのままリンクできる位置に置いてある。

## 2. 通信契約（Python 向け共通）

形式は従来のまま（1 Tick = 1 データグラム、`KEY:値` をカンマで連ねる）。**追加は任意の 1 パートだけ。**

```
SCENARIO_ID:<id>,AVAIL:1:<token>+<token>+...,SPEED:..,TIME:..,LOCATION:..,...
```

### 2.1 AVAIL 契約 v1

* `AVAIL:<version>:<tokens>`。トークンは「この行が**実際に持っているデータ群**」の正リスト（小文字英数字と `_`、最大 64 個）。リストに無い群の**キーは送らない**。プレースホルダー・既定値・古い値は送らない。
* **AVAIL を送らない送信側（既存の Current）は「全項目あり」**として従来どおり動く。
* 版が 1 以外の AVAIL は解釈しない（その行は無効。`unsupported-version`）。形式が壊れた AVAIL は信用しない（`avail-malformed`）。
* **未知のトークンは無視**（数えるだけ。エラーにしない）。新しい送信側が群を足しても古い受信側は壊れない。
* AVAIL は**毎行**に載る。途中から起動した Python、取りこぼし、シナリオ再読込（車両が変わる）でも、次の 1 行で可用性が更新される。別便のデータグラムは使わない（順序や取りこぼしの問題が無い）。
* 必須キー（`SCENARIO_ID`、`TIME`、`LOCATION`、`SPEED`）が無い、または有限の数値でない行は**テレメトリではない**。

### 2.2 トークンと対応するキー

| トークン | キー / データグラム | HUD での用途 | Legacy |
|---|---|---|---|
| `time` | `TIME` | 時刻、残り時間 | ○ |
| `speed` | `SPEED` | 速度 | ○ |
| `loc` | `LOCATION` | 距離 | ○ |
| `grad` | `GRADIENT` | 勾配 | ○ |
| `station` | `NEXTLOC` `NEXTTIME` `ISPASS` `ISTIMING` `MARGINB` `MARGINF` `DOORDIR` `TERM` `STATNAME`、`STALIST` | 残り時間、距離 | ○ |
| `door` | `DOOR` | ドア状態 | ○ |
| `siglimit` | `SIGLIMIT` | 制限（信号） | ○ |
| `siglimit_ahead` | `FWDSIGLIMIT` `FWDSIGLOC` | 制限の予告（信号） | ○ |
| `maplimit` | `MAPHEAD` `MAPTAIL` | 制限（地上・現在値） | ○ |
| `maplimit_ahead` | `MAPLIMITS` `CLEARDIST` | 制限の予告（地上） | **×** |
| `handle` | `REV` `POW` `BRK` `HTYPE` `ALLTXT` | ハンドル行 | **×** |
| `brake_type` | `BTYPE` | ブレーキ方式 | ○ |
| `brake_cab` | `CAB` | ブレーキ段数 | ○ |
| `prates` | `PRATES` | ブレーキ段の有効判定 | ○ |
| `bcp` / `bpp` | `BCP` / `BPP` | 診断表示 | **×** |
| `trainlen` | `TRAINLEN` | 車両長 | **×**（§4 参照） |
| `doortime` | `DOORTIME` | ドア閉め時間 | **×**（§4 参照） |
| `calcg` | `CALCG` | 加速度（G） | ○（最初の 1 行を除く） |
| `meta` | `META` | シナリオ情報 | ○ |
| `jump` | `JUMP`、`JUMP_COMPLETE`（54322 の命令） | ジャンプ | **×** |

### 2.3 HUD 項目と必要なトークン（Python）

| HUD 項目（`disp_settings` のキー） | 必要なトークン |
|---|---|
| `time` | `time` |
| `time_left` | `time` `station` |
| `speed` | `speed` |
| `limit` | `siglimit` `maplimit` |
| `dist` | `loc` `station` |
| `handle` | `handle` |
| `grad` | `grad` |

**ユーザーの HUD 設定（`disp_settings`）と、API 取得不能による非表示は別物**で、`hud_ui.hud_item_state()` が `shown` / `user-hidden` / `unavailable` を返す（両方に該当するときは `unavailable`）。ユーザーの設定は可用性で書き換えない。

## 3. Python の動作

### 3.1 HUD を表示する条件（管理モード）

次を**すべて**満たしたときだけ HUD を表示する。

1. AppReady 成立、状態ブロック正常（E4）
2. Session ON かつ Driving ON（E4）
3. **現在の ScenarioGeneration に対する有効なテレメトリを 1 件以上受信**（必須キーの形式検証に成功）
4. その世代の最新のシナリオインスタンスが Caller の世代と一致している（送信側が先に次のシナリオへ進んでいない）

満たさない間は Python と Overlay を維持したまま HUD を非表示にし、**プレースホルダー HUD は出さない**。毎 Tick のログは出さない。テレメトリが途絶えても（Pause）**閾値で隠さない**（既存のデータ鮮度契約は無く、根拠のない閾値は足さない）。

### 3.2 世代との対応（時計も閾値も使わない）

テレメトリは `SCENARIO_ID`（シナリオインスタンスごとに 1 つ）を、Caller は ScenarioGeneration（状態ブロック）を持つ。両者を `telemetry_gate.TelemetryGate` で結ぶ。

* **stale**: 最新より古い `SCENARIO_ID`、または前の世代に属した `SCENARIO_ID` → 捨てる。
* **bound**: 世代が変わった後に最初に届いた、stale でない `SCENARIO_ID` が、その世代のデータになる。
* **ahead**: 送信側が Caller より先に次のシナリオへ進んだ（新しい `SCENARIO_ID` が来たが世代はまだ変わっていない）→ 古いデータはもう現在ではないので HUD は待つ。**最新の 1 データグラムは保持**し、世代の変更が届いたときにそれを適用する（直後に Pause しても HUD が出る）。
* 世代が変わると、前のデータの可用性も**捨てる**。新しいシナリオインスタンスの最初の行で、テレメトリ由来の Overlay 状態は構築時の既定値へ戻る（`reset_telemetry_state`）。送られない項目は上書きされず、前のシナリオの値も残らない。
* 駅一覧（`STALIST`）とシナリオ情報（`META`）は専用のデータグラムで置き換わる（新しいシナリオインスタンスの最初の Tick に送られる）。駅が 0 件のシナリオでは `STALIST` が送られないため、同じ Python が続く場合は前の駅一覧が残るが、`NEXTLOC` が -1 の間は HUD はそれを参照しない。
* ログは状態の**変化**だけ: 世代ごとの最初のテレメトリ、可用性の変化、世代ごとの最初の破棄理由、HUD 項目の変化、終了時の集計。

### 3.3 通常手動モード

`python main.py`（通常モード）の挙動は変えていない。AVAIL の追従だけを行い（`TelemetryGate(strict=False)`）、データグラムは一切捨てない。HUD は従来どおり常に表示される。Current の送信（AVAIL 無し）は従来と同一に動く。

## 4. 項目別の確定（Legacy の取得元・単位・更新・初期値・リセット・Pause・正規化）

共通: **更新頻度**は Tick ごと（ホストの Tick に従う）。**未初期化値**は存在しない（読めない値は送らない）。**シナリオ変更時**は新しい `SCENARIO_ID` で全状態を最初から。**Pause 中**はホストが Tick を止めるため何も送らず、Python は最後の値を保持する（時間も止まっているので矛盾しない）。

| 項目 | Legacy の取得元 | Current の取得元 | 単位・正規化 |
|---|---|---|---|
| 速度 | `Scenario.LocationManager.SpeedMeterPerSecond` | `VehicleLocation.Speed` | m/s → ×3.6 で km/h |
| BVE 時刻 | `Scenario.TimeManager.TimeMilliseconds` | `TimeManager.Time` | ms（そのまま） |
| 現在位置 | `Scenario.LocationManager.Location` | `VehicleLocation.Location` | m |
| 勾配 | `Route.MyTrack.Gradients.GetValueAt(位置)` | `TrackAlignment.Gradient`、0 なら同じ `GetValueAt` | ‰（地図に書かれた値）。Current の代替経路と同一 |
| 駅情報 | `Route.Stations`（`Name` `Location` `Pass` `IsTerminal` `DoorSide` `Arrival/Departure/Default/StoppageTimeMilliseconds` `MarginMin/Max`） | 同じ内容を動的に読む | ms、m。`MarginMin` は API が負で返すため絶対値（Current と同じ）。駅一覧の整形と「次駅」の状態機械は Current と同じ規則（`LegacyStationTimeline`） |
| 信号制限 | `SectionManager.CurrentSectionSpeedLimit` / `ForwardSectionSpeedLimit` / `Sections[i].Location` | 同じ | m/s → km/h。無限大・999 m/s 超は 1000（制限なし）。0 は 0 km/h（停止現示） |
| 地上制限（現在値） | `Route.SpeedLimits.CurrentLimit`（API の定義: 「現在の制限速度 [m/s]」） | `SpeedLimits` の各要素から計算 | m/s → km/h。無限大・999 超・0 以下は 1000。`MAPHEAD` と `MAPTAIL` に**同じ実値**を送る（先行リストは存在しない） |
| ドア状態 | `Vehicle.Doors.AreAllClosed` | 同じ | 閉=0 / 開=1 |
| ブレーキ方式 | `BrakeSystem.BrakeController` の型（`Ecb` / `Smee` / `Cl`） | `Src` の同一性 | 判定不能なら送らない（Ecb を既定にしない） |
| ブレーキ段数 | `Cab.Handles.NotchInfo.BrakeNotchCount` / `HasHoldingSpeedBrake` | 同じ | 段数、抑速の有無。0 段は読取りとみなさない |
| PRATES | `BrakeController.PressureRates` / `MaximumPressure` | 同じ | 比、Pa → kPa（÷1000）。無い方式（空配列）は送らない |
| シナリオ情報 | `IBveHacker.ScenarioInfo`（Title / RouteTitle / VehicleTitle / Author / Comment） | 同じ | 区切り文字を全角へ置換 |
| 加速度（G） | 送信側が連続 2 サンプルから計算 | 同じ | m/s² ÷ 9.80665。**シナリオインスタンスの最初の 1 行と、時間の不連続の直後は参照サンプルが無いので送らない** |
| 力行段数 | `NotchInfo.PowerNotchCount`（取得可能） | — | 契約にキーが無く HUD も使わないので送らない |
| ハンドル位置（数値） | `Handles.ReverserPosition` / `PowerNotch` / `BrakeNotch`（取得可能） | 同じ | 契約のキー（`REV` `POW` `BRK`）は**表示テキストを含む**ため、テキストが無い Legacy では送れない。数値だけを空テキストで送る案は、`BRK` の最大段数（`BrakeTexts.Length-1`）が公開 API に無いため採らなかった |
| **車両長** | `VehicleDynamics.CarLength` と `FirstCar` / `MotorCar` / `TrailerCar` の `Count` から導出できる可能性 | `SpeedLimitList.VehicleLength` | **L3 では送らない（`trainlen` を宣言しない）。** 3 種の `CarInfo` の合算規則（先頭車が動力車・付随車と重複するか）を公開 API から確定できず、導出は推測になる。HUD は使わない。L3-live で実車の既知の編成と照合して確定できれば、1 行で有効化できる |
| **ドア閉め時間** | `DoorSet.StandardCloseTime`（API の定義: 閉まるのに要する時間の**基準** [ms]。各ドアはその 0.95〜1.05 倍） | 先頭ドアの実際の `CloseTime` | **L3 では送らない（`doortime` を宣言しない）。** 同じキーに「基準値」を入れると別の量になる。HUD は使わない（採点の保存時刻補正のみ） |

### 取得不能な項目（AVAIL で宣言し、Python が対応項目を隠す）

| 項目 | 理由 | 扱い |
|---|---|---|
| ハンドル表示テキスト（`REV` `POW` `BRK` `ALLTXT`） | 公開 API の `CabBase` は `Handles` のみで、`ReverserTexts` 等が無い | `handle` を宣言しない → **ハンドル行を描かない**。ノッチ番号から文字を作ることもしない |
| ブレーキシリンダー圧 `BCP` | `BcValve` に `Pressure` が無い | `bcp` を宣言しない。F2 診断表示の BCP 行も出さない |
| ブレーキ管圧の現在値 `BPP` | `Smee` / `Cl` に `Bp`（現在圧）が無い（初期圧だけある） | `bpp` を宣言しない。診断表示の BPP / Virtual_EB 行も出さない |
| 地上速度制限の先行リスト（`MAPLIMITS` `CLEARDIST`） | `SpeedLimitList` の要素は `Location` のみで `Value` の公開 API が無い | `maplimit_ahead` を宣言しない。地上制限の予告点滅は出ない（信号の予告は出る） |
| ジャンプの実行・完了通知（54322） | BVE 内部の難読化名が必要で、公開 API では実現できない | 54322 を受信しない。`jump` を宣言しない |

**利用不能項目があっても、取得可能な HUD 全体は表示される。**

## 5. ライフサイクル（Legacy 送信側）

| 契機 | 動作 |
|---|---|
| 拡張の初期化 | UDP ソケットを作り、ハートビート用タイマー（50 ms）を開始。シナリオが無い間は何も送らない |
| `ScenarioOpened` / `ScenarioClosed` / `ScenarioCreated` | 現在のインスタンスを即座に終了（状態機械・加速度の参照・STALIST/META の周期・ハートビートを破棄）。次の Tick で新しい `SCENARIO_ID` |
| `IsScenarioCreated` が false / `Scenario` が読めない（読込中） | インスタンスを終了。何も送らない |
| 元の `Scenario` オブジェクト（`Src`）が変わった（イベントが無くても） | 新しいインスタンス。新しい `SCENARIO_ID`（直前と同じ値にはならない）。**ラッパーの同一性は使わない**（§9） |
| 世代変更（Caller） | 送信側は関与しない。Python のゲートが対応づける（§3.2） |
| Pause | ホストが Tick を止める → 送信なし。ハートビート（`STATUS:LOADED:PAUSED`）はタイマーが自分のフィールドだけから作る（BVE オブジェクトに触れない）。再開後は同じインスタンス（`SCENARIO_ID` 不変） |
| 時間の不連続（ジャンプ・巻き戻し） | 駅の「次駅」を位置から選び直し、加速度の参照を捨てる |
| シナリオ終了 | 上記 `ScenarioClosed` |
| 再読込 | `ScenarioOpened`（`IsReload`）→ 新インスタンス |
| TS Scoring OFF / ON | テレメトリは関与しない（送り続ける。Python が居なければ捨てられる）。ON で Python が起動し、次の 1 行から世代に結びつく |
| Dispose / BVE 終了 | タイマー停止 → イベント解除 → インスタンス終了 → ソケットを閉じる。以後は何も送らない |

例外は構築、Tick、Dispose、イベント、タイマーのどこからも外へ出ない。任意項目はグループ単位で全部入るか全部入らないかで、1 つの読取り失敗が他の項目に及ばない。

## 6. 配置（この版では何も配置しない）

> **ルール: 他方のホストのフォルダーへ DLL を置かない。** Current と Legacy は排他。

| DLL | 置き場所 | 読み込むホスト |
|---|---|---|
| `TSScoringPlugin.AtsExLegacy.Telemetry.dll`（新規） | `%PUBLIC%\Documents\BveEx\Legacy\Extensions` | AtsEX レガシーモードのみ |
| `TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll` | 同上（L1、無変更） | 同上 |
| Current Bridge / `TsScoringPlugin.dll`（Current 送信） | `%PUBLIC%\Documents\BveEx\2.0\Extensions`（従来どおり、Legacy には置かない） | Current のみ（無変更） |
| Caller | BVE6 / BVE5 の `Input Devices`（従来どおり 1 個） | どちらでも（無変更） |

テレメトリ DLL は Bridge と独立で、Bridge が無くても/あっても単独で読み込める。戻すときは DLL を外すだけ。第三者の DLL には触れず、再配布もしない。

## 7. 試験

`tests\test_telemetry_l3.py`（契約、ゲート、コントローラ、実 Overlay、静的ガード）、`Tests\Test-TelemetryL3.ps1`（実 DLL のコアを偽の Legacy API で駆動、単位、AVAIL、失敗、ライフサイクル、Pause、Dispose、駅、隔離、Python 参照リーダーとの一致、C# の出力バイトを実 Overlay へ）、`Tests\Test-TelemetryIntegrationL3.ps1`（偽 Legacy API → 送信コア → 実 UDP 54321 → 実 `main.py --managed` + 実 Overlay + 実 Caller コード）。既存の E1〜E4、D1、M1、C1、C3、L1、Bridge、通常モードの回帰も通っている。結果は実施報告にある。

## 8. 限界と L3-live で確認すること

* **BVE5 の実機では未確認。** `AtsExLegacyApi`（実 API の読取り）はコンパイルでメンバーの存在と型を確認しただけで、実行はオフラインでは不可能。読取りが失敗した項目は送られず、AVAIL から外れて HUD から隠れるだけ（安全側）。
* 確認すべきこと: ① 速度・時刻・位置・駅・信号制限・勾配の値と単位、② `Route.Stations` の要素が `Station` として取れるか、③ `Station.IsTerminal` が `departureTime="t"` と一致するか、④ `SpeedLimitList.CurrentLimit` が頭か尻か（HUD の制限行の意味）、⑤ `BrakeController` が `Ecb` / `Smee` / `Cl` のどれかの型で返るか、⑥ 世代の変更とテレメトリの先行の順序（hold が働くか）、⑦ 車両長・ドア閉め時間を有効にできるか。
* 通常モードで Legacy のテレメトリを使うと採点は動かせるが、`BCP` `BPP` `MAPLIMITS` `JUMP` が無いため**採点の入力が不足する**（AVAIL で宣言済み）。採点の本格連動（E5 以降）で、`bcp` / `jump` が無い環境の採点を許可しない判断が必要。
* 世代をまたいで同じ `SCENARIO_ID` を使い回す送信側（Current は新しい Scenario ごとに採番するので該当しない見込み）では、新しい世代の HUD が出ない（安全側に倒れ、`telemetry-drop reason=stale-epoch` が 1 行出る）。
## 9. L3-live の不具合修正: シナリオ同一性（0.1.1.0）

### 9.1 不具合

L3-live（BVE5 Legacy）で、HUD が表示された約 37 ms 後に非表示へ戻った。Python のゲートは 1 行目だけ受理し、以後の全行を `sender-ahead`（送信側が Caller より先のシナリオへ進んだ）として破棄していた（`tel_accepted=1 tel_ahead=1273`、`tel_stale=0`）。
原因は 0.1.0.0 の送信側が、**毎 Tick 新しい `SCENARIO_ID` を採番していた**こと。「同じシナリオか」を `IBveHacker.Scenario` が返すラッパーオブジェクトの**参照同一性**で判定していた。

### 9.2 根拠（Legacy 公開 API とホストの実装の確認）

* `IBveHacker.Scenario` は `ScenarioHacker.CurrentScenario` → `MainForm.CurrentScenario` の値を返す。クラスラッパーの取得は `Scenario.FromSource(src)` で、**呼ぶたびに `new Scenario(src)`** を作る。同じシナリオでもラッパーは毎回別オブジェクトになる。
* `ClassWrapperBase`（全ラッパーの基底）は公開メンバー **`Src`**（ラップされている BVE 本体のオリジナル オブジェクト）を持ち、`Equals` / `GetHashCode` は `Src` に委譲する。つまりホスト自身も「同一性」は `Src` で決めている。
* BveTypes の実クラスで確認済み（試験 R01〜R06）: 同じ `Src` の 2 つのラッパーは別参照で `Equals` が真、`Src` は同一参照、別の `Src` は別参照。
* `ClassWrapperBase` は `==` を再定義し左辺を参照するため、`wrapper == null` は null で `NullReferenceException` になる。同一性の取得は `ReferenceEquals(wrapper, null)` を使う（試験 R04）。

### 9.3 安定したシナリオ識別契約

| 項目 | 内容 |
|---|---|
| 同一性の正体 | `LegacyScenarioIdentity.Source` = `Scenario.Src`（BVE 本体のオリジナル `Scenario` オブジェクト）。参照で比較。種類名は診断ログの `identity=src-object` |
| 同一シナリオの Tick 間 | 不変（ラッパーが毎回新しくても `Src` は同じ）。**ラッパーは同一性判定に一切使わない**（セッション側は `Wrapper` を読まない） |
| 再読込 | 新しい `Src`（BVE がシナリオを読み直すと新しいオブジェクト）→ 新世代。さらに `ScenarioOpened` / `ScenarioClosed` / `ScenarioCreated` が現在のインスタンスを即座に終了させるため、**同じ内容のシナリオを読み直しても必ず新世代**（`Src` が仮に再利用されても、イベントが先に終了させる）。文字列内容の比較は使わない |
| 別シナリオ | 別の `Src` → 新世代（イベントが届かなくても） |
| Pause / Tick 停止 | 世代を更新しない（Tick が来ないだけで状態は変わらない。`SCENARIO_ID` 不変） |
| 読めないとき | `Src` が読めない（null / 例外）ときは**何も送らない**（同一性を推測しない）。診断に `TEL_IDENTITY_UNAVAILABLE` を 1 回記録し、読めるようになったら新世代 |
| 使わないもの | 参照できる公開 API だけ。Current API は参照しない。Current 側の `SCENARIO_ID` 契約は無変更。Handshake の `ScenarioGeneration` とは結合しない（結合は Python のゲート側のみ） |
| 限界 | `Src` が「呼ぶたびに別オブジェクト」になる実装は想定しない（実機の診断ログ `TEL_EPOCH_BEGIN` が 1 シナリオに 1 回であることで L3-B 再試験時に確認する） |

副作用だった「駅の状態機械・加速度基準（`calcg`）・STALIST/META 周期が毎 Tick リセットされる」問題も同時に解消する（同一インスタンス内では継続）。

### 9.4 診断（専用ログ）

共有観測ログ（`TSScoring-Phase-C1-Observation.log`）は Handshake の制御プレーンが名前付き Mutex と実行マーカーで排他する仕組みで、テレメトリ DLL は §1.1 のとおりそれらを一切リンクしない。統合すると分離が壊れるため、**専用ログ**を使う。

* ファイル: `<ユーザープロファイル>\Downloads\TSScoring-L3-Telemetry.log`（OS から実行時に決定。パスはバイナリに含まない）。プロセス内で最初に書く行がファイルを作り直す（新しい BVE プロセスは古い実行に追記しない）。1 MiB で打ち切り。
* 形式: `HH:mm:ss.fff P=<pid> I=<拡張の連番> EVENT key=value …`。状態変化と最終集計だけ（毎 Tick は書かない）。パス・シナリオ名・路線名・車両名は書かない。
* 書き込みの失敗や診断の例外は BVE にもテレメトリにも影響しない。

| イベント | 内容 |
|---|---|
| `TEL_INIT` | 拡張の初期化: `ver` `bitness` `host=AtsExLegacy` `identity=src-object` `events=yes/no`（ライフサイクルイベント購読の成否）`heartbeat` |
| `TEL_EPOCH_BEGIN` | 新しいテレメトリ世代: `n` `scenarioId`（= `SCENARIO_ID`）`reason` `identity` |
| `TEL_UDP_BEGIN` | その世代の最初のデータグラムを送信 |
| `TEL_EPOCH_END` | 世代の終了: `scenarioId` `lines`（その世代の送信行数）`reason` |
| `TEL_IDENTITY_UNAVAILABLE` | `Src` が読めず送信を止めた（遷移時に 1 回） |
| `TEL_DISPOSE` / `TEL_FINAL` | Dispose 時の集計（`epochs` `lines` `skipped` `discontinuities`、`udpSent` `udpFailed`） |

`reason`（世代の始まり・終わりの理由）: `first-tick`、`scenario-opened` / `scenario-opened-reload`、`scenario-closed`、`scenario-created`、`not-created`、`scenario-unreadable`、`identity-changed`（イベント無しで `Src` だけが変わった）、`dispose`。

L3-B 再試験の合格確認: 1 シナリオに `TEL_EPOCH_BEGIN` が 1 回（再読込で 2 回目）、`TEL_EPOCH_END` の `lines` が実際の Tick 数に比例、Python 側ログに `telemetry-drop` が出ない（`tel_ahead=0`）。

### 9.5 試験

`Tests\Test-TelemetryL3.ps1` の G01〜G27（偽 API が毎 Tick 別ラッパーを返す; 1000 Tick で世代 1、Pause 後も同一、同内容の再読込・別シナリオで新世代、Dispose 後の再初期化、UDP 形式・AVAIL・取得不能項目が不変、診断が状態変化だけ）、R01〜R06（**実際の BveTypes のラッパークラス**を使用）、H01〜H04（C# のデータグラムを実 `TelemetryGate` strict に通し、`sender-ahead` が出ないことと、旧不具合の署名が検出されること）、X15〜X18（静的検査）。旧実装（ラッパー参照比較）へ一時的に戻すと、G02〜G05・G07〜G09・G11・G13〜G17・G24・G25・R05・R06・X15 の 18 件が失敗することを確認済み（実行記録は試験証拠に保存）。