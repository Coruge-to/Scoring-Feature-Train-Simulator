# Phase SI-B1 — B1-probe（Legacy の公式ジャンプ相当 API を観測するための観測専用ビルド）

提供者: **Coruge-to** / 対象: **BVE5 + AtsEX レガシーモード** / バージョン: Legacy テレメトリ DLL **0.4.1.1（観測専用・リリースではない）**。実機で動かしたのは **0.4.1.0**（SHA-256 `0D2947E4…CC63`）で、0.4.1.1 は実機観測で分かった 2 つの誤前提（§6b）を probe 自身の判定から直しただけのビルド（API 呼出しの内容は同一）。

**これは SI-B2 ではない。** 製品のジャンプ機能（54322 受信、JUMP カウンタ供給、`jump` の AVAIL 宣言、`JUMP_COMPLETE`、採点開始ゲートの緩和）は一つも入れていない。製品の Legacy テレメトリ DLL（0.4.0.0、SHA-256 `995486BE…`）は**バイト単位で無変更**で、probe は別 DLL としてビルドし、観測の間だけ同じファイル名の位置へ置き、終わったら戻す。

## 1. 何を確かめるか（SI-B1 監査の未確定事項）

SI-B1 の静的監査（読み取り専用）で、Current の公式ジャンプは Legacy の公開 API `Scenario.Initialize(int)`／`InitializeTimeAndLocation(double,int)`／`TimeManager.SetTime(int)` と**同じ元メソッド**だと分かった。能力不足は無い。未確定なのは**呼出し文脈**だけである: Legacy の Extension の Tick は AtsEX の `InputDeviceMain.PostElapse` 経由、つまり ATS の `Elapse` の直後に走る。この入口から `Initialize` を呼んだときの再入・ハング・ATS／AtsEX 状態・ドア・保安装置への影響、読み戻しの一致、1 Tick 内で完了判定に使える条件が成立するかを、実機で 1 回ずつ観測する。

## 2. 構成（本番ソースは編集しない）

probe のソースとツールは **Tests/B1Probe/** に置く（観測専用ツールであり、製品の Telemetry プロジェクトの一部ではない。製品プロジェクトは Telemetry/Legacy/src と Telemetry/Shared だけをコンパイルし、このフォルダを知らない）。

| ファイル | 役割 |
|---|---|
| `Tests/B1Probe/src/B1ProbeCore.cs` | **ホスト非依存のコア**（AtsEx 型を名指ししない）。要求ファイルの厳格パーサ、write-ahead 台帳、1 要求 1 回の状態機械、完了判定の候補、Dispose 競合の扱い、ログ。BVE に触れるのは `IB1ProbeHost` 経由だけ |
| `Tests/B1Probe/src/B1ProbeHost.cs` | **AtsEX アダプター**。唯一 `Scenario.Initialize`／`InitializeTimeAndLocation`／`TimeManager.SetTime` を呼ぶファイル。スナップショット（時刻・位置・速度・ドア・ハンドル・駅・信号・ATS 側の見え方）と、イベントの**計数だけ**をするハンドラ |
| `Tests/B1Probe/src/AssemblyInfo.B1Probe.cs` | 版 0.4.1.1（実機で動かしたのは 0.4.1.0）、`0.4.1.1-b1-probe-observation-only`、表題に「NOT A RELEASE」 |
| `Tests/B1Probe/*.B1Probe.csproj` | probe のプロジェクト。**製品のソース（`src`、Extension と AssemblyInfo を除く）をそのままコンパイル**し、Extension だけは生成コピーを使う |
| `Tests/B1Probe/New-B1ProbeExtension.ps1` | 製品の `LegacyTelemetryExtension.cs` を**読み**、5 か所のアンカー付き挿入をした probe 用コピーを生成する（アンカーが 1 か所でも「ちょうど 1 回」でなければ何も書かない）。`-Verify` で挿入を戻して製品ファイルと一致することを確かめる |
| `Tests/B1Probe/Build-B1Probe.ps1` | probe DLL（と、比較用に製品 DLL）をリポジトリの**外**へビルドする。配置はしない |
| `Tests/B1ProbeTestFixture.cs`、`Tests/Test-JumpProbeB1.ps1` | 偽ホスト・偽 IO での挙動試験、ソース静的ガード、ビルド再現性、変異試験 |

生成コピーに入る挿入は 5 つ: ① フィールド `b1probe`、② セッションに渡す sink を `b1probe.TapSink(sink)`（テレメトリ行を**読み取るだけ**で素通しする）、③ `TEL_INIT` の直前の `b1probe.Attach(hacker, Native, session)`、④ Tick: `session.OnTick` の**前**に `BeginTick`（要求があれば実行）、**後**に `EndTick`（同じ Tick のセッションの反応を読む）、⑤ Dispose: `session.OnDispose` の**前**に `b1probe.OnDispose()`。

## 3. 要求の投入方法（本番 54322 契約とは無関係）

観測専用のファイル方式: `Downloads\TSScoring-B1Probe-request.txt`（`key=value`、1 件）。投入は package の `New-B1ProbeRequest.ps1` だけが行う（一時ファイルへ書いて改名＝途中まで読まれない）。UDP は使わない。

```
B1PROBE-REQUEST 1
TestId=B1-O2
RequestId=tsb1-20261011-123456-ab12
Operation=InitializeStationThenSetTime     (SetTime | InitializeStationThenSetTime | InitializeLocationThenSetTime)
StationIndex=3                              (駅の操作だけ)
LocationM=2750.5                            (位置の操作だけ)
TimeMs=36500000
CreatedAtUtc=2026-10-11T12:34:56.789Z
ExecuteOnce=true
ExpectGeneration=2                          (任意。probe が数える現在のシナリオ世代と違えば拒否)
```

パーサは厳格: ヘッダ必須、未知キー・重複キー・欠落・範囲外・書式違いは固定語の理由で拒否（要求の自由文はログへ出ない）。拒否理由: `unreadable too-large bad-format unknown-key duplicate-key missing-key bad-value bad-operation operation-args not-execute-once created-in-future created-before-process-start too-old generation-mismatch generation-changed execution-cap not-ready-timeout station-out-of-range snapshot-unreadable ledger-failed`。

## 4. 実行規則（1 要求につき最大 1 回、Tick の中だけ）

* BVE の API に触れるのは `BeginTick`（Extension の Tick、`session.OnTick` の前）からだけ。要求ファイルの有無確認は毎 Tick `File.Exists` 1 回。**要求が無ければ他に何もしない**（スナップショットも読まない）。専用スレッドも Timer も無い。
* 実行の条件: シナリオ作成済み、セッションが有効、その世代で 10 Tick 以上、前回の Tick 終了から世代イベント（Opened／Closed／Created）が無い。満たさなければ待つ（`PROBE_PENDING`、最大 600 Tick で `not-ready-timeout`）。世代が変われば `generation-changed` で拒否。
* **write-ahead**: 実行の**前**に RequestId を台帳 `TSScoring-B1Probe-consumed.txt` へ追記（書けなければ拒否＝呼ばない）。クラッシュしても再実行されない。同じ RequestId は `PROBE_DUPLICATE_IGNORED`。1 プロセスの実行は最大 8 回。
* 呼出し順: `SetTime` → `SetTime(ms)` のみ。駅 → `Initialize(station)` → `SetTime(ms)`。位置 → `InitializeTimeAndLocation(loc, ms)` → `SetTime(ms)`。`Initialize` が例外なら `SetTime` は呼ばない。**各呼出しの直前に Dispose 開始を確認**し、始まっていれば呼ばない。
* 要求ファイルは実行後に `TSScoring-B1Probe-request.consumed-<RequestId>.<時刻>.txt` へ改名（残る＝監査の証跡）。改名できなくても同じ要求は二度と読まれない。
* 古い要求の拒否: `CreatedAtUtc` が現在より 10 秒超先、このプローブ（Extension のインスタンス）の開始より前（**BVE を終了して、またはシナリオを終えて残った要求は、次のプロセス／次のインスタンスでは必ず拒否**。理由語は created-before-process-start）、1800 秒より古い。

## 5. ログ（`Downloads\TSScoring-B1Probe.log`、追記・2 MiB 上限）

全行が `HH:mm:ss.fff P=<pid> T=<tid> <EVENT> test=<TestId> req=<RequestId> host=AtsExLegacy gen=<probe 世代> scn=<SCENARIO_ID> tick=<Tick 通し番号> …`。必須イベント: `PROBE_REQUEST_ACCEPTED`／`REJECTED`、`PROBE_EXECUTE_BEGIN`、`PROBE_BEFORE`、`PROBE_INITIALIZE_BEGIN/END`、`PROBE_SET_TIME_BEGIN/END`、`PROBE_AFTER_CALL`（呼出し直後の読み戻し）、`PROBE_AFTER_SAME_TICK`（セッションの Tick 後）、`PROBE_COMPLETION_CANDIDATE`、`PROBE_AFTER_NEXT_TICK`、`PROBE_STABILITY`（k=2..5）、`PROBE_STABILITY_SUMMARY`、`PROBE_OBSERVATION_END`、`PROBE_DUPLICATE_IGNORED`、`PROBE_DISPOSE_REJECTED`、`PROBE_EXCEPTION`、`PROBE_DISPOSE_BEGIN/END`。ほかに `PROBE_INIT`、`PROBE_TICK_THREAD`、`PROBE_GENERATION`、`PROBE_PENDING`、`PROBE_REENTRANT_TICK`、`PROBE_RETIRE_FAILED`。

読み戻す項目: 時刻、位置、速度、ドア、ハンドル（出力＝Cab、ATS 側＝Native）、前後の駅（位置から求めた添字、要求駅の位置）、信号制限・先行信号制限・地上制限、ATS 側の見え方（`INative.VehicleState` の時刻・位置・速度・BC・BP）、シナリオ作成/終了イベントと ATS の `Started`／ドア開閉／信号更新／ビーコンの**計数**、プロセスのスレッド数・ハンドル数、各呼出しの所要時間、例外の型と（パス・メールを除いた）メッセージ。個人パス・メール・氏名は書かない。

## 6. 完了判定の候補（SI-B2 の入力。ここでは判定を「記録」するだけ）

`PROBE_COMPLETION_CANDIDATE result=MET` は次がすべて成り立つとき: ① 呼出し直後の読み戻しの時刻＝要求（完全一致）、② 位置が期待値から 0.01 m 以内（駅＝その駅の位置、位置＝要求位置、SetTime＝実行前の位置）、③ セッションの Tick 終了後の読み戻しも同じ、④ **同じ Tick で**テレメトリ行が送られ、その `TIME`／`LOCATION` が要求どおり、⑤ 実行前にあったテレメトリ群（AVAIL トークン）が、**想定外には**消えていない（不連続を数えた Tick の `calcg` の欠落だけは製品仕様どおりで正常＝§6b）、⑥ 世代イベントも再入も例外もない、⑦ 速度の期待（`SetTime`＝不変、停車駅＝0）。`discontinuitySameTick` はセッションが 300 ms 超の飛びを**同じ Tick で**検知したか（JUMP カウンタの供給元）を示す。

## 6b. 実機観測で分かった誤前提と訂正（SI-B1 最終）

実機観測（BVE5 Legacy、probe 0.4.1.0、8 実行）では BVE API の実障害は無かった（Tick スレッド上の呼出し、例外・再入・ハング無し、最長 8.6 ms、時刻は要求と完全一致、位置誤差 0、同じ Tick に要求の TIME／LOCATION を含む行を送信）。当初 FAIL になった項目は、probe／監査の前提の誤りだった:

| 項目 | 誤前提 | 実際（訂正） |
|---|---|---|
| K10／K11（`groupsKept`） | 同じ Tick で全群が保持される | `calcg` は API から読む値ではなく、セッションが**連続 2 サンプルから計算**する値。不連続を検知した Tick の行には付かず、次の Tick で戻る（`LegacyTelemetrySession`）。そのため不連続 Tick の `calcg` の欠落は**正常**。`calcg` 以外の欠落、不連続が無い Tick での欠落、次の Tick で戻らないことは異常のまま。K11 は K10 の `groupsKept` だけから派生した FAIL だった |
| K12（`timeAdvancing`） | 呼出し直後の読み戻しより次の Tick の時刻が厳密に大きい | BVE は呼出し直後の**次の 1 Tick は同じ時刻・位置・速度**を返す（8 件全て）。その後は厳密に進む。正しい判定は「Tick N+1 は呼出し値と同じか後（戻らない）、N+2〜N+5 は厳密に進む、5 サンプルは別々の Tick」 |
| O5-c | 要求が Pause の前に作られる（要求の年齢 ≧ Tick の間隔） | 手順は「Pause → Pause 中に要求を作る → 待つ → 再開」なので、要求は最後の Tick より後に作られ `0 < createdAgeMs < gapSincePrevTickMs` が正常（実測 13975／20985 と 14280／22067） |
| 停車駅のドア | 「ドアが開かない」 | 停車駅へ `Initialize` すると**ドアは開く**のが BVE の正常動作（BVE 本体の時刻表ジャンプでも同じ）。通過駅では閉。開閉の反復・継続する警報・操作不能は異常として残す |

訂正の範囲は probe 自身の判定（`B1ProbeCore.cs`: `groupsKept`、`Summarize`、`availLostUnexpected`／`nextTickRepeat`／`distinctTicks` の追加）、package の監査（保存ログの生の値から K10／K11／K12／O5-c を再計算するので 0.4.1.0 のログも 0.4.1.1 のログも同じ規則で判定される）、fixture（偽ホストが実機どおりに `calcg` を落とし、呼出し直後の Tick で時刻を据え置く）、試験、README。BVE API の呼出し内容、製品、Current、Caller、両 Bridge、共有契約、Python は変更していない。

**不連続の回数は固定しない**: SetTime 単独では 3／3 で不連続が 2 回数えられた（呼出し Tick で 1、次の Tick で 1。`Initialize` を伴う場合は 5／5 で 1 回）。次の Tick の時刻は前の行と同じなので、検出は AtsEX の `elapsed` が 300 ms 超のときだけ起こるが、`elapsed` はログに無く算出基準も文書化されていない（原因は未確定）。この挙動は隠さず、監査は「同じ Tick で 1 回以上検知」だけを PASS 条件にし、回数は情報（O1-d）として残す。JUMP カウンタを SetTime 単独で +2 と数えるか操作単位で +1 に正規化するかは SI-B2 の設計判断。

**環境制約**: Legacy の `INative` が null のため ATS 側の観測値は開始時から `na`（呼出しによる欠落ではない）。ATS の安全性は目視（警報・パネル・操作に異常なし）でしか見ておらず、測れたとは言わない。

## 7. Dispose

`OnDispose` は最初に `disposing` を立て、以後 BVE を読まず呼ばない。`Monitor.TryEnter(500 ms)` で Tick の実行中の完了を待つだけ（Tick が応答しなくても Dispose は 500 ms で戻る）。未実行の要求は `PROBE_DISPOSE_REJECTED reason=pending-request-dropped` で捨て、**要求ファイルは触らない**（次のプロセスで古い要求として拒否される）。`apiCallsAfterDispose` は常に 0 でなければならない。

## 8. 不変のもの

製品の Legacy テレメトリのソース、`TelemetryContract.cs`、Current 送信側、Caller、両 Bridge、M1a 制御プレーン（`HandshakeControlPlane`）、`HandshakeProtocol.cs`、Python 全部（採点開始ゲート、`FIRST_QUIET_S = 0.3`、自動 P の 2 か所）。probe は 54321／54322 に何も足さず、`jump` を AVAIL に載せず、`JUMP_COMPLETE` に答えず、採点を開始しない。M1a の `HandshakeControlPlane`／Caller の Tick から BVE API は呼ばない（呼ぶのは Extension の Tick だけ）。

## 9. 試験

`Tests/Test-JumpProbeB1.ps1`（162 項目 + 変異 23 ＝ 185）。P（パーサ）、B（呼出し順とスレッド）、I（要求なしでは何もしない）、X（1 回だけ）、R（拒否）、O5（Pause）、F（ログと完了判定）、D（Dispose）、H／E（再入と例外）、S（ソース静的ガード、生成コピーの検証、ビルドの再現、製品 DLL 995486BE の再現、スコープ）。変異: 順序逆転、重複実行、Dispose 後実行、Tick 外の API 呼出し、許容誤差の無視、消費済み RequestId の再実行、ほか（M19〜M23: 欠落群をすべて想定内にする／`calcg` を不連続の無い Tick でも想定内にする／Tick N+2 以降の停止を許す／Tick N+1 の後退を許す／同じ Tick の 2 サンプルを受理する）。F28〜F34 が §6b の実機事実（`calcg` の欠落と復帰、呼出し直後の Tick の据え置き、SetTime 単独の不連続 2 回、ドア）を偽ホストで再現して固定する。

## 9b. 既存の固定の再固定（許可リストへの追加だけ）

既存の範囲固定のうち 5 本が probe のファイルを数えて失敗したため、許可リストに probe の置き場所を足した。チェックは一つも減らしていない（Test-JumpProbeB1.ps1 の S15b が「Check の数が HEAD より減っていない・変えた既存行は各 2 行以内」を固定している）: Test-DependencyNoticeM1.ps1（M1-31 の許可リスト）、Verify-PhaseL1.ps1（許可リストと、.cs 走査から Tests\B1Probe を除く）、Verify-PhaseC3.ps1（同じく .cs 走査から除く）、Verify-PhaseL3.ps1（許可リスト）、Verify-PhaseSIA7.ps1（許可リスト）。Python のファイル（テスト含む）には触れていない: tests/test_managed_input_sia3.py の範囲固定は Tests／Docs を除く TsScoringPlugin 配下の新規・変更だけを数えるため、probe を Tests/B1Probe/ に置くことで追加の再固定が要らない。

## 10. 実機観測と SI-B2 の判断

実機観測は package（リポジトリ外）の README に一括して記載している。B1-O1／O2／O4L／O5／O8／O10（O7 は条件付き）。**SI-B2 の GO は、観測が SI-B1 の GO 条件を満たし、利用者が明示的に承認したときだけ。** Smee 車の `bp_initial` 不足は別ブロッカーとして残る。
