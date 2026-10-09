# Phase E4 補完 — 既存HUDのデータ経路監査（Legacy HUD functional status）

E4 は「いつHUDを出し、更新し、隠すか」（状態連動）を実装した。この文書は、もう一つの問い「HUD は実データで更新されるか」を、Current と BVE5 Legacy について監査した結果である。**結論: 状態連動は両方で動くが、BVE5 Legacy では HUD に実データを送る経路が存在しない。**

> **Phase L3 追記（この文書は E4 時点の監査として残す）**: §7 の最小アダプター案を Phase L3 で実装した（独立した Legacy テレメトリ DLL、`AVAIL` 契約、Python の項目別表示、実テレメトリ受信までの HUD 非表示）。取得元・単位・取得不能項目の最終的な確定は `Handshake-PhaseL3-LegacyTelemetry.md` を正本とする。BVE5 の実機では未確認のため、下の状態表（NOT live-updating）はこの文書の時点の記録であり、実機での受入は Phase L3-live で行う。

## 1. Legacy HUD functional status

| 環境 | 状態連動（E4） | HUD の実データ更新 |
|---|---|---|
| BVE6 Current（BveEX 2.x ホスト） | 実装・試験済み | テレメトリ送信元（`Class1.cs`）が `2.0\Extensions` に配置されている。形式は監査済み。実機での値の正しさは E4 では未確認 |
| BVE5 Current（BveEX 2.x ホスト） | 同上 | 送信元は同じ Extension。このPCで BVE5 を Current ホストで動かすかは未確認 |
| **BVE5 Legacy（AtsEX Legacy ホスト）** | 実装・試験済み | **NOT live-updating。送信側が存在しない。** HUD の値は起動時の既定値のまま固定される |

「対応済み」とは扱わない。Legacy で HUD の窓が出ても、表示値（00:00:00、0.0 km/h、`--- m`、ハンドル「切 N N」など）はプレースホルダーであり BVE の値ではない。

## 2. 送信主体（根拠）

* UDP 54321 へ送信するソースは、リポジトリ内で **`TsScoringPlugin/TsScoringPlugin/Class1.cs`（`ScoringPlugin`）だけ**。`using BveEx.PluginHost;`、`[Plugin(PluginType.Extension)]`、BveEX 2.x 用API（`BveHacker.Scenario.VehicleLocation` など）に依存する。
* 同一アセンブリの `AtsLoggerPlugin.cs` は 54321 へ送信しない（診断用）。
* Handshake の Caller、Current Bridge、Legacy Bridge は **ソケットを一切使わない**（`UdpClient`、`System.Net.Sockets`、54321／54322 の記述なし。`Tests\test_hud_data_path_e4.py` が静的に確認する）。
* Legacy Bridge（`TSScoringPlugin.AtsExLegacy.Bridge.Prototype`）は `AtsEx.PluginHost` を参照し、ScenarioReady と Ready だけを扱う。`Class1.cs` は Legacy のどのプロジェクトにも含まれない。
* 配置状況（2026-10-09、`%PUBLIC%\Documents\BveEx` の読み取り）: `2.0\Extensions` に `TsScoringPlugin.dll` がある。`Legacy\Extensions` には `TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll` と他製品のDLLだけで、**テレメトリ送信DLLはない**。Legacy ホストは `Legacy\Extensions` だけを読む。
* 受信側（Python の `Overlay.read_udp_data`）はホストの名前を一切持たない。同じ形式の送信元があれば、どのホストでも同じ経路で更新される（B群の統合試験で確認）。

## 3. HUD が使う入力と Legacy での取得可否

凡例: **OK** = Legacy の公開ラッパーAPIで取得できる / **差** = 取得元が Current と異なる（実機で意味と単位の確認が必要）/ **NO** = Legacy の公開ラッパーAPIでは取得できない / **ホスト非依存** = 送信側の計算（BVE API 不要）。Legacy 側のAPI調査は、このPCにある Legacy ホストの `BveTypes.dll`（1.0.50314.2）と Current ホストの `BveTypes.dll`（2.1.51225.1）を読み取り専用で比較した結果。BVE5（5.8.7554.391）の実行は行っていない。

### 3.1 毎Tickのテレメトリ行（`KEY:値,` の並び）

| Key | HUD での用途 | Current の取得元 | Legacy の取得元（公開API） | Legacy |
|---|---|---|---|---|
| `SCENARIO_ID` | シナリオ切替の検出 | 送信側が Scenario 変化で採番 | 同左（送信側） | ホスト非依存 |
| `SPEED` | 速度行 | `VehicleLocation.Speed` | `LocationManager.SpeedMeterPerSecond` | OK |
| `TIME` | 時刻行、全ロジックの時計 | `TimeManager.Time` | `TimeManager.TimeMilliseconds` | OK |
| `LOCATION` | 距離、通過判定 | `VehicleLocation.Location` | `LocationManager.Location` | OK |
| `GRADIENT` | 勾配行 | `Dynamics.TrackAlignment.Gradient`（無ければ `MyTrack.Gradients.GetValueAt`） | `Route.MyTrack.Gradients.GetValueAt`（`TrackAlignment` は無い） | 差 |
| `NEXTLOC` | 距離行 | 駅リスト＋送信側の状態機械 | `Route.Stations`（`Location`）＋同じ状態機械 | OK |
| `NEXTTIME` | 残り時間行 | 同上（`ArrivalTime`／`DepartureTime`） | `Station.ArrivalTimeMilliseconds`／`DepartureTimeMilliseconds` | OK |
| `ISPASS` | 通過／停車の表示 | `Station.Pass` | `Station.Pass` | OK |
| `ISTIMING` | 採時の表示 | 送信側の補間結果 | 同左 | ホスト非依存 |
| `MARGINB`、`MARGINF` | 停止位置の許容 | `Station.MarginMin／Max` | `Station.MarginMin／Max` | OK |
| `REV`（テキスト：数値） | ハンドル行 | `Cab.ReverserTexts[…]`＋`Handles.ReverserPosition` | 数値は `Handles.ReverserPosition` で **OK**。**テキストは公開APIに無い**（`CabBase` は `Handles` のみ） | **NO**（テキスト） |
| `POW` | 同上 | `Cab.PowerTexts`／`HoldingSpeedTexts`＋`Handles.PowerNotch` | 数値 OK、テキスト **NO** | **NO**（テキスト） |
| `BRK`（テキスト：数値：最大） | 同上、EB色判定 | `Cab.BrakeTexts`＋`Handles.BrakeNotch` | 数値 OK、テキストと最大（`BrakeTexts.Length-1`）**NO**（`NotchInfo.EmergencyBrakeNotch` で近似できる可能性あり、未確認） | **NO**（テキスト） |
| `HTYPE` | 1ハンドル／2ハンドル | `OneLeverCab` の型名 | `OneLeverCab`／`TwoLeverCab` は存在する | OK |
| `ALLTXT` | ハンドル欄の幅、ブレーキ段のラベル | `Cab` の4つのテキスト配列 | 公開APIに無い | **NO** |
| `SIGLIMIT` | 制限行（信号） | `SectionManager.CurrentSectionSpeedLimit` | 同じ | OK |
| `FWDSIGLIMIT`、`FWDSIGLOC` | 先行の信号制限 | `SectionManager.ForwardSectionSpeedLimit`、`Sections[i].Location` | 同じ | OK |
| `TRAINLEN` | 停止距離の既定、制限の解除位置 | `SpeedLimitList.VehicleLength` | 無い。`VehicleDynamics.CarLength`＋`CarInfo.Count` から導出できる可能性（未確認） | 差 |
| `MAPLIMITS` | 制限行（地上の先行制限） | `SpeedLimits` の各要素の `Location`／`Value` を実行時リフレクションで読む | `SpeedLimitList` の要素は `MapObjectBase`（`Location` のみ）。`Value` の公開APIは Current にも Legacy にも無い。現在値は `SpeedLimitList.CurrentLimit` | **NO**（先行リスト）／現在値のみ OK |
| `MAPHEAD`、`MAPTAIL`、`CLEARDIST` | 編成が跨ぐ制限の判定 | `MAPLIMITS` と同じ元データ | 同じ制約 | **NO** |
| `DOOR` | ドア開閉 | `Vehicle.Doors.AreAllClosed` | 同じ | OK |
| `DOORDIR`、`TERM`、`STATNAME` | 停車・終着の判定、駅名 | 駅リスト | `Station.DoorSide`／`IsTerminal`／`Name` | OK |
| `CALCG` | 加速度（G） | 送信側で速度差分から計算 | 同左 | ホスト非依存 |
| `BTYPE` | ブレーキ方式 | `BrakeController` と `Ecb／Smee／Cl` の同一性 | `BrakeSystem` に同じ4つのプロパティ | OK |
| `JUMP` | ジャンプ回数 | 送信側のカウンター | 同左 | ホスト非依存 |
| `CAB` | ブレーキ段数、抑速の有無 | `NotchInfo.BrakeNotchCount`、`HasHoldingSpeedBrake` | 同じ | OK |
| `BCP` | デバッグ表示、採点（制動の検出） | `FirstCarBrake.BcValve.Pressure.Value` | `BcValve` に `Pressure` が無い（`TargetPressure`／`MrPressure` は別の量） | **NO** |
| `PRATES` | ブレーキ段の有効判定 | `BrakeController.PressureRates／MaximumPressure` | 同じ | OK |
| `BPP`（現在：初期） | デバッグ表示、Smee の仮想EB | `Smee.Bp.Pressure.Value`、`Smee.BpInitialPressure` | 初期値 `BpInitialPressure` は OK。現在値 `Bp` は無い | **NO**（現在値） |
| `DOORTIME` | ドア閉め時間 | 内部名のフィールド（`Src` 経由） | `DoorSet.StandardCloseTime`（公開）。同じ量かは未確認 | 差 |

### 3.2 毎Tick行以外のデータグラム

| Kind | 内容 | Legacy |
|---|---|---|
| `STALIST` | 駅リスト（1秒ごと） | OK（`Route.Stations`） |
| `META` | シナリオのタイトル等 | OK（`IBveHacker.ScenarioInfo`） |
| `STATUS` | `STATUS:LOADED:RUNNING／PAUSED`（ハートビート） | ホスト非依存（タイマー） |
| `JUMP_COMPLETE` | ジャンプ完了通知（Python → 54322 の命令への応答） | NO（受信側54322も、ジャンプ実行が BVE 内部の難読化名を使うため、公開APIでは実現できない） |

## 4. Current と Legacy の差（要約）

* 公開APIで不足: ハンドルの表示テキスト、ブレーキシリンダー圧、BP現在圧、地上速度制限の先行リスト、車両長、`TrackAlignment`。
* 取得元が違う: 速度（`LocationManager`）、駅リスト（`Route`）、勾配、ドア時間。
* 同じ: 時刻、位置、信号制限、ドア開閉、駅関連、ブレーキ方式、ブレーキ段数、`PRATES`。
* Python 側の更新・値の意味・パース規則は同じ。ホストの違いは送信側だけに閉じている。

## 5. 値が固定される／古くなる可能性

1. **BVE5 Legacy（送信側なし）**: 全値が起動時の既定値のまま（時刻 0、速度 0.0、次駅 -1、ハンドル「切 N N」、信号制限 1000）。`STATUS` のハートビートも来ないため `is_bve_loaded` も False のまま。
2. Current: 一時停止中は Tick が止まり、テレメトリも止まる（`STATUS:LOADED:PAUSED` だけが続く）。HUD は直前の値を表示し続ける（意図どおり）。
3. Current: 選択画面（Legacy では Tick 停止）や再読込の直後、HUD が復帰してから最初のテレメトリが届くまでの短時間（Tick 数回分）は、前のシナリオの値が残る可能性がある。
4. HUD の窓を出す条件は Session／Driving の状態であり、テレメトリを受けたかどうかは見ていない（E4 の仕様）。

## 6. HUD として最低限成立する範囲（Legacy）

公開APIだけで成立する行: 時刻、残り時間、速度、制限（信号制限と現在の地上制限）、距離（次駅）、勾配（取得元が差）。成立しない行: ハンドル（表示テキストが取れない）。採点（制動の検出に BCP を使う）は E5 以降の別問題。

プレースホルダーを本物の値として流さないために、取得できない項目は「取得不能」と明示する経路が必要になる（5. の1 を参照）。

## 7. 最小アダプター案（実装していない）

1. Legacy 専用の送信DLLを新設する（例: `TSScoringPlugin.AtsExLegacy.Telemetry`）。`AtsEx.PluginHost` だけを参照し、Current API を混在させない。既存の Legacy Bridge、Current Bridge、`Class1.cs` は変更しない。
2. 形式は既存のテレメトリ行（3.1 の Key と区切り）とする。ホスト非依存の部分（駅の状態機械、`CALCG`、`SCENARIO_ID`、`JUMP`、ハートビート）は同じ規則で複製または共有ソースとして切り出す。
3. 取得不能な項目は送らず、さらに「この行で本物の値を持つキー」の宣言（例: `AVAIL:` キー）を契約へ追加する。Python の HUD は、宣言されていない入力に依存する行を隠す。→ 既存のテレメトリ契約の拡張であり、E4 の責務を超える。
4. 実機（BVE5 Legacy）での受入が必須: 速度・時刻・位置・駅・信号制限・勾配の単位と意味の確認。

## 8. BLOCKER

1. BVE5 Legacy にテレメトリ送信側が存在しない。
2. ハンドル表示テキスト（`REV`／`POW`／`BRK`／`ALLTXT`）が公開APIで取得できない。推測・合成（ノッチ番号から文字を作る）は禁止。
3. `BCP`、現在の `BPP`、`MAPLIMITS` の先行リストが取得できない。
4. 送信DLLは BVE5 の実行なしには値の正しさを証明できない（オフライン試験は形式と状態機械まで）。
5. 取得不能項目を示す契約（`AVAIL:`）が未定義。

## 9. 推奨するPhase構成

1. **E4b（Python のみ・小）**: HUD は、このセッションで実テレメトリ（`SCENARIO_ID` を含む行）を1回以上受けるまで表示しない。Legacy で「固定プレースホルダーのHUD」が出る状態を防ぐ。
2. **L3（設計＋オフライン実装）**: Legacy 専用送信DLL、`AVAIL:` 契約、Python 側の行の非表示。オフライン試験と形式の同値性。
3. **L3-live（実機受入）**: BVE5 Legacy で値の意味と単位を確認する。
4. その後に E5（採点統合）。

## 10. 試験

`tests\test_hud_data_path_e4.py`: A群（リポジトリの静的監査：送信元の一意性、Legacy 側にソケット無し、キー語彙の一致、この文書の網羅）と B群（実 `Overlay`＋実UDPで、送信元なしでは値が固定され、既存形式のデータグラムでは全値が更新されること）。UDP 54321 が使用中ならB群はSKIPする（動作中のアプリは停止しない）。
