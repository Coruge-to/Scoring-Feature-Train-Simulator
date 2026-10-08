# TS Scoring – Phase C1 観測版（診断用・バージョン 0.5.0.0）

製品ではなく、診断用の観測版です。**自動配置はしていません**。BVE も Python も、この作業では一度も起動していません。
提供者: **Coruge-to** / バージョン: **0.5.0.0** / 対象: **通常の BveEX モード**（AtsEX レガシーモードは対象外）。

この版が行うのは「ログを書くこと」だけです。ScenarioReady は実装していません（名前付き Event も状態も通知もありません）。
Phase B の挙動（Enabled / Stop / BridgeAvailable / Ready、500 ms の依存案内、案内の本文とタイトル）は変えていません。

## 1. 中身

| 部品 | `dist\` のファイル | 置き場所 |
|---|---|---|
| 入力デバイス Caller | `TSScoringPlugin.Caller.InputDevice.dll` | BVE6 の `Input Devices` フォルダ（`%ProgramFiles%\mackoy\BveTs6\Input Devices`、管理者権限） |
| BveEX Bridge | `TSScoringPlugin.BveEx.Bridge.Prototype.dll` | `%PUBLIC%\Documents\BveEx\2.0\Extensions` |

`dist\` には DLL 2 個だけがあります（PDB なし）。DLL 名は Phase B と同じです。

## 2. 手動配置（BVE を完全に終了してから）

1. BVE と BveEX が動いていないことを確認する（タスクマネージャーで BVE が無いこと）。
2. **Phase B 安定版の退避**: 今入っている 2 個の DLL を別の安全な場所へコピーして残す（復帰用）。
   今入っているのが Phase B 第 4 改訂（0.4.1.0）なら SHA-256 は次のとおり。

   | DLL | SHA-256（Phase B 安定版 0.4.1.0） |
   |---|---|
   | Caller | `AC9E26F309FB130A9C2C07AE73DF996F91BACB59C31448823185B15D20AA0642` |
   | Bridge | `670E64CA30271A704F47B9F4F03C00DA3C7A69B85B5FF9769026E24558D653F2` |

3. 上の 2 か所の古い DLL を削除し、`dist\` の新しい DLL をそれぞれコピーする（同名なので上書きでも可）。
4. BVE を起動する。入力デバイス一覧に「TS Scoring Input Device Caller」（0.5.0.0）が出る。TS Scoring を ON にする。

## 3. 観測ログ

- 場所: `%USERPROFILE%\Downloads\TSScoring-Phase-C1-Observation.log`（固定。Caller と Bridge が同じファイルへ追記する）
- **新しい BVE プロセスの最初の書き込みで初期化（上書き）**されるので、別の実行は混ざらない。同じ BVE の中での BveEX／TS Scoring の OFF→ON は同じ実行として続けて記録される。
- 2 つの BVE を同時に動かすと互いのログを消し合うので、観測中は BVE を 1 つだけ起動する。
- 4 MB を超えると各 DLL が `LOG_CAP_REACHED` を 1 行書いて以降は書かない。
- 書けない（フォルダが無い、ファイルが他で開かれている等）場合は何も起きない。落ちるのではなく黙って捨てる。次に書けた行に `droppedBefore=N` が付く。
- 毎フレームは書かない。状態が変わった時だけ。通常走行中はログが増えない。
- 個人情報なし: ユーザー名、パス、シナリオ名、車両名、マシン名、例外メッセージは書かない（例外は型名のみ）。

### 行の形式

`HH:mm:ss.fff q=<QPC ms> P=<PID> S=<Caller|Bridge> T=<A|B|AB> th=<スレッド> EVENT key=value ...`

- `T=A` Track A（シナリオのライフサイクル）、`T=B` Track B（起動時系列と依存案内）、`T=AB` 両方に関係。
- `q` は 2 つの DLL で共通の単調時計（ms）。DLL 間の順序比較は `q` で行う。`HH:mm:ss.fff` は操作のメモと突き合わせる用。
- `cycle=` は Caller の有効化 1 回ごとの番号、`inst=` は Bridge の読込 1 回ごとの番号、`ScenarioGeneration=` はシナリオ読込ごとの番号。

## 4. Track B（BVE6 再起動直後の「BveEXを有効にしてください」誤表示）

主なイベント（Caller → Bridge の順で並ぶのが通常）:

| イベント | 意味 |
|---|---|
| `CALLER_CTOR_BEGIN/END`, `CALLER_LOAD_BEGIN` | Caller の生成と Load |
| `CALLER_ENABLED_CREATED` | Enabled 作成。この `q` が「0 ms」の基準 |
| `MONITOR_LOOP_BEGIN` | 監視ループ開始 |
| `AVAIL_FIRST_CHECK` | BridgeAvailable の初回確認（Present / Missing） |
| `AVAIL_FIRST_PRESENT` / `AVAIL_SEEN` | 初回／再度 Present になった（`absentMs`, `over500`, `noticeShownThisAbsence`） |
| `READY_FIRST_PRESENT` / `READY_CONNECTED` / `READY_LOST` | Ready の遷移 |
| `AVAIL_LOST` | BridgeAvailable が消えた |
| `TIMEOUT_REACHED` | 500 ms 到達（`timeoutMs=500`） |
| `NOTICE_JUDGE_BEGIN` | MessageBox 判定開始（`lagSinceTimeoutMs`） |
| `NOTICE_PRESHOW` | 表示直前の再確認の結果（`decision=show/suppress`, `reason`, `bridgeAtRecheck`） |
| `NOTICE_SHOW_CALL` | 表示を要求した瞬間（`bridgeAtCall` は診断専用の再観測。判定は変えない） |
| `NOTICE_SUPPRESSED` / `NOTICE_DIALOG_CLOSED` | 抑止／閉じられた（`openMs`） |
| `CALLER_DISPOSE_BEGIN/END` | Caller の Dispose |
| `BRIDGE_CTOR_BEGIN/END` | Bridge の生成（`ver=`, `sinceCtorBeginMs`） |
| `AVAIL_CREATE_BEGIN/OK/FAIL`, `AVAIL_DISPOSED` | BridgeAvailable の作成・破棄 |
| `READY_CREATE_BEGIN/OK`, `READY_DISPOSED` | Ready の作成・破棄（`reason`） |
| `SUBSCRIBE`, `SUBSCRIBE_DONE` | BveEX イベント購読の結果 |
| `BRIDGE_FIRST_TICK`, `BRIDGE_DISPOSE_BEGIN/END` | 最初の Tick、Dispose |

**現行コードの MessageBox 直前再確認**: 既に存在する（`ShowNoticeIfStillNeeded` が表示直前に「Disposed でない・まだ TimedOut・BridgeAvailable がまだ無い」を再確認する）。
ただし再確認と実際の `MessageBoxW` 呼び出しの間にはロックを外した短い隙間があり、そこでの Present 化は防げない（`NOTICE_SHOW_CALL` の `bridgeAtCall` と `gapSinceRecheckMs` で観測する）。今回は変更していない。

### 後から分類する（`Tools\Classify-Observation.ps1`）

```
powershell -NoProfile -ExecutionPolicy Bypass -File "<作業フォルダ>\Tools\Classify-Observation.ps1"
```

| 分類 | 意味 |
|---|---|
| `BridgeAvailableExceeded500ms` | BridgeAvailable が 500 ms を超えて遅れ、正しく案内された（案内は仕様どおり） |
| `NoticedUnder500ms` | Bridge は 500 ms 未満で BridgeAvailable を作っていたのに案内が出た（Caller の見落とし） |
| `BecamePresentAfterJudgementBeforeShow` | 判定は Missing だったが、表示を要求した瞬間には Present だった |
| `SuppressedAtRecheck` | 500 ms 到達後、再確認で抑止された |
| `InitOrderBridgeFirst` | Bridge が Caller の有効化より先に生成された（Phase B 実機の「Bridge が約 300 ms 後」と逆順） |
| `DllOrPidGenerationMismatch` | Caller と Bridge の DLL バージョン不一致、または 1 つのログに複数 PID |
| `NotReproduced` | 案内は出なかった（再現せず） |

## 5. Track A（シナリオのライフサイクルと ScenarioReady 候補）

利用した BveEX の実在 API（`BveEx.PluginHost.dll` の実物と同梱 XML で確認済み）:
`IBveHacker.ScenarioOpened`（`IsReload`）、`ScenarioClosed`、`PreviewScenarioCreated`、`ScenarioCreated`、`IsScenarioCreated`、`PreviewTick`、`PostTick`、
`IExtensionSet.AllExtensionsLoaded`、拡張の `Tick` / `Dispose`。

実在しない／取得手段が無いもの（ログからの推定になる）: タイトル画面帰還の専用イベント、公式ジャンプの専用イベント、ポーズ状態の通知。
→ タイトル帰還は「`SCN_CLOSED` の後に `SCN_OPENED` が続かない」、ポーズは「`TICK_GAP`（1 秒超の Tick 停止の再開時に 1 回）」、ジャンプは「イベントが出ないこと」で見る。

| 候補 | 成立条件（ログ `CAND_<id>`、1 世代につき 1 回） |
|---|---|
| A | `ScenarioCreated` を受信した時 |
| B | `IsScenarioCreated` が true になった時（Preview／Created／Tick のどこで初めて見えたかを `where=` に記録） |
| C | `ScenarioCreated` 後の最初の Tick |
| D | その最初の Tick で `IsScenarioCreated` が true（false なら `CAND_D_NOT_MET`） |
| E | `ScenarioCreated` 後の Tick で、必要な BVE の参照（Scenario／時刻管理／車両位置／車両）を安全に取得できた最初の Tick（取得できない間は理由コード付きの `CAND_E_PENDING` を理由が変わった時だけ） |
| F | API 調査で見つけた候補: `ScenarioCreated` 後の最初の `PostTick`（その 1 フレームの全拡張の Tick が終わった後）で E と同じ条件が成立した時 |

- `ScenarioGeneration` はシナリオ読込（`ScenarioOpened`）ごとに +1。同一シナリオの再読込は `isReload=yes`。
- `GEN_SUMMARY` に世代ごとの成立候補（例 `candidates=ABCDEF`）、Tick／PreviewTick／PostTick の回数。`FRAME_ORDER` に最初の 3 フレームイベントの並び。
- Bridge が `ScenarioCreated` より後に読み込まれた場合は `LATE_ATTACH`（A は成立しない）。
- 候補を成立させても何も通知しない。ログに 1 行書くだけ。

## 6. 観測チェックリスト（操作の時刻をメモして、ログの `HH:mm:ss.fff` と突き合わせる）

1. BVE を**完全終了→起動**（BveEX ON、TS Scoring ON）。メニューのまま 1 分待つ。Track B を見る。再現狙いは「再起動直後」を何度か（数回〜十数回）。
2. シナリオ選択→読込→走行開始。`SCN_OPENED`→`SCN_PREVIEW_CREATED`→`SCN_CREATED`→各 `CAND_*`。
3. 走行中にポーズ→数十秒→解除。`TICK_GAP`。
4. 公式ジャンプ（時刻と位置）。イベントが出るか、`TICK_GAP` が出るか。
5. 別のシナリオを読込。`ScenarioGeneration` が増える。
6. 同じシナリオを再読込。`isReload=yes`。
7. タイトル画面へ戻る。`SCN_CLOSED`。
8. TS Scoring を OFF→ON（入力デバイス設定）。Caller の `CALLER_DISPOSE_*` → 新しい `cycle` の `CALLER_ENABLED_CREATED`、Bridge の `READY_DISPOSED`／`READY_CREATE_*`。
9. BveEX を OFF→ON（通常は BVE の再起動が必要）。`BRIDGE_DISPOSE_*`／`BRIDGE_CTOR_*`（再起動なら新しい実行としてログが初期化される）。
10. 設定→入力デバイス→TS Scoring→設定（Configure）。`CONFIGURE_OPENED/CLOSED`。
11. BVE を終了。`BRIDGE_DISPOSE_*`、`CALLER_DISPOSE_*`。

## 7. Phase B 安定版（0.4.1.0）への復帰

1. BVE を完全に終了する。
2. `Input Devices` と BveEX の `Extensions` から、この 0.5.0.0 の 2 個の DLL を削除する。
3. 手順 2 で退避した Phase B の DLL（SHA-256 は上の表）を同じ場所へ戻す。
4. 観測ログ `TSScoring-Phase-C1-Observation.log` は不要なら削除してよい（次回は自動で初期化される）。

## 8. 限界と注意

- ログの書き込みは BVE／BveEX のスレッド上で行う（オフライン試験では 1 行あたり概ね 1 ms 前後。BVE 実機では未計測）。Bridge のコンストラクタでは **BridgeAvailable を先に作ってから**観測の購読を行うので、購読が BridgeAvailable を遅らせることはない。ただし最初のログ書き込み（ファイル初期化）の数 ms は BridgeAvailable 作成の前に入る。
- 静的解析・オフラインテストでは BveEX 実機のイベント順序、Tick の頻度、ポーズ中の挙動は確認できない。実機ログで確認する。
- AtsEX レガシーモードでは Bridge は読み込まれず（`AtsEx.PluginHost` は別系統）、BridgeAvailable が出ないため案内が出るのが現行 Phase B の仕様。C1 の観測対象外。
- 第三者の DLL（`BveEx.PluginHost.dll`、`BveTypes.dll` など）は同梱せず、再配布しない。

## 9. 配置に関する注意

手動配置のみを想定しています（配置スクリプトはこのリポジトリに含めていません）。BVE5 と BVE6 は任意のフォルダーにインストールできるため、配置先は利用者が実際のインストール先を確認して決めてください。

### 9.1 最終 β 版インストーラーの将来要件（固定パスに依存してはならない）

BVE5 と BVE6 は任意のフォルダーにインストールできる。最終インストーラーは次を満たすこと。

1. BVE5 と BVE6 の実際のインストール先を検出する。
2. 標準配置を既定の候補として確認する。
3. 任意配置を検出できない場合は、利用者に選択してもらう。
4. BVE 本体と Input Devices の構造を検証する。
5. BVE5 と BVE6 を個別に選択できる。
6. 実際に配置したパスを記録し、更新・アンインストールでも同じパスを使う。
7. 存在しない標準パスを勝手に作成しない。
8. 誤ったフォルダーに DLL を配置しない。

### 9.2 実機観測のあと

観測ログ `%USERPROFILE%\Downloads\TSScoring-Phase-C1-Observation.log` は、**次の BVE プロセスの最初のログ書き込みで初期化（上書き）される**。残したいログは、**次に BVE を起動する前に**別名でコピーして退避する。