# Phase E4 — Session / Driving の公開と HUD 連動（Caller 0.11.0.0）

Caller が持つシナリオの状態（Session）と活動の状態（Driving）を、E3 が起動した管理 Python へ公開し、既存 HUD の表示・更新・非表示を同じ Overlay のまま連動させます。
Python の寿命は E3 のまま（Caller の Dispose だけが Stop を出す）です。

## 範囲

* 含む: Session／Driving／ScenarioGeneration の公開（Caller）、受信（Python 管理モード）、Overlay との接続、HUD の表示／待機／非表示、再読込・soft OFF からの復帰、診断、試験。
* 含まない: 採点セッションの開始・確定・破棄、保安装置採点、Kickstart・ジャンプ・F8 のキー送信、入力抑止フック、Esc 終了、メニュー（F1）、更新通知、EXE 化、Job Object、クラッシュ時の再起動、Bridge の変更、実機配置。

## 意味

| 状態 | 意味 | 元 |
|---|---|---|
| Session | 現在の ScenarioGeneration について ScenarioReady が公開されている | Caller の ScenarioReady 読取り（C3）。Dispose が始まると OFF |
| Driving | D1 の DrivingActive。**Session が ON のときだけ ON** | `DrivingActivityState`（無変更） |
| ScenarioGeneration | 上の 2 つがどのシナリオ世代のものか（0 = まだ無い） | ScenarioReady の状態ブロック（C3） |
| Closed | Caller が管理インスタンスの状態を撤回した（Dispose） | E4 |

AppReady とは独立です（AppReady はプロセスの協調準備、Session／Driving は HUD の材料）。Python の寿命には使いません。

## 公開方式（E0 の「Event 2 本案」を採用しなかった理由）

E0 は `Session`／`Driving` の名前付き Event 2 本を案としました。E4 では**管理インスタンスごとの名前付き共有メモリ 1 個**にしました。

* Event は 1 ビットなので ScenarioGeneration を運べず、世代変更を Python が識別できない。
* Session と Driving を**一つの整合した組**として読めない（hard OFF が 2 つの Event の別々の変化になり、間に中間状態が見える）。Python 側にも 2 本の待機が要る。
* 共有メモリは E2／E3 と同じ族の名前（`Local\TSScoringPlugin.v1.<BVE PID>.App.<INST>.State`）で、C3 の ScenarioState と同じ seqlock の流儀で書け、**現在値を 1 回の読取りで得られる**。通知を取りこぼしても次の読取りで現在値に収束する。

レイアウト（64 バイト固定・リトルエンディアン・32／64 ビット共通。数値と instance の先頭 16 桁だけ。シナリオ名・パスは入らない）:

| offset | 型 | 内容 |
|---|---|---|
| 0 | u32 | Magic 0x53415354（"TSAS"） |
| 4 | u32 | Version = 1 |
| 8 | u32 | Size = 64 |
| 12 | u32 | BVE プロセス ID |
| 16 | char[16] | instance ID の先頭 16 桁（ASCII） |
| 32 | u32 | Head（seqlock。書込み中は奇数） |
| 36 | u32 | Flags（bit0 Session、bit1 Driving、bit2 Closed） |
| 40 | i32 | ScenarioGeneration |
| 44 | u32 | ChangeCount（完了した書込み回数。初期状態は 0） |
| 60 | u32 | Tail（完了時に Head と等しい） |

* 定義は `Caller\src\AppStatePublisher.cs`（`AppStateLayout`）と `managed_state.py` の 2 か所。試験が両者の定数の一致を確認する。
* BVE PID と instance は名前とヘッダーの両方に入る。別 BVE・別 instance のブロックは見えない（名前が違う）、見えても拒否される。

## Caller 側

* `AppProcessManager`:
  * `PublishState(session, driving, generation)` — 監視スレッド（20 ms ごと）から呼ばれる。同一状態は「ロック 1 回＋比較」で戻り、書込みもログもしない（件数だけ数える）。プロセスが無いあいだも**最新値を保持**する。
  * ブロックは Stop Event の直後・`Process.Start` の**前**に作り、その時点の最新値で初期化する。作れなければその試行は失敗（`APP_STATE_CREATE_FAILED`／`APP_LAUNCH_FAILED reason=state-block-create-failed`）。
  * `Shutdown`（Dispose）は Stop を出す**前**に Session OFF／Driving OFF／Closed を書く（`APP_STATE_CLOSED`）。
  * ブロックはワーカーの後始末で解放する。
* `HandshakeSession`: 監視ステップの `EvaluateDrivingLocked` の直後・`ObserveAppControllerLocked` の前、および `End()` から `PublishAppStateLocked()`。Tick 経路（`NotifyTick`）は無変更。
* Current／Legacy の区別は Caller のコードに存在しない（どちらの Bridge も同じ名前付きオブジェクトを公開する）。したがって Python から見える Session／Driving の契約は BVE6 Current、BVE5 Current、BVE5 Legacy で同一。

診断（共有観測ログ・状態変化のみ・パス無し）: `APP_STATE_OPEN`（初期値）、`APP_STATE_PUBLISH`（変化ごと。instance・session・driving・generation・changeNo）、`APP_STATE_CLOSED`（書込み回数と抑止した同一報告の件数）、`APP_STATE_CREATE_FAILED`。
Python の stderr 転記の上限は 1 プロセス 20 行から 200 行へ変更（Python が状態変化ごとに数行を出すため。依然として変化のみ）。

## Python 側（管理モード）

* `managed_state.py`（Qt 非依存）: `StateReader`（読取り専用で開き、64 バイトを 2 回読んで一致を確認、検証、torn は再読込、最後の良い値を保持）、`HudGate`（純粋な状態機械）。
* `managed_hud.py`: `ManagedHudController`。**Overlay と QTimer は main.py が渡した 1 個だけ**を使い、新しいウィンドウ・タイマーを作らない。
* `main.py`: `run_managed` が AppReady の**前**に状態ブロックを開いて最初の読取りを済ませ、Overlay のタイマーの接続先を `update_logic` から `controller.tick` へ付け替える（`update_logic`、`Overlay` クラスは無変更）。終了時は HUD を隠し、マッピングを解放する。

HUD の動作:

| 状態 | モード | Overlay | 更新 | タイマー間隔 |
|---|---|---|---|---|
| Session ON ∧ Driving ON | active | BVE の窓（**PID で特定**）の所有ウィンドウとして表示、クライアント領域に追従 | `update_physics_and_scoring` ＋再描画（通常モードと同じ順序） | 16 ms |
| Session ON ∧ Driving OFF（soft OFF） | waiting | **破棄せず**非表示 | 停止 | 100 ms |
| Session OFF／Closed／ブロック無し（hard OFF） | hidden | 破棄せず非表示 | 停止 | 100 ms |

* Pause は DrivingActive が維持される（D1 実機契約）ので HUD の挙動は変わらない。
* 再読込は新しい ScenarioGeneration。Session OFF→ON でも Session のまま世代だけ変わっても、**同じ Python・同じ Overlay・同じウィンドウハンドル**で復帰する。
* Legacy の選択画面（ScenarioReady が残ったまま Tick が止まる／再開する）: Session のまま Driving が OFF／ON を往復するだけ。再起動・再生成はない。選択画面そのものを識別する新しい信号は**追加していない**。
* BVE の窓が見つからない間は表示せず（0.5 秒間隔で探索）、データ更新は続ける。窓が消えたら隠して外し、再探索する。**終了はしない**。
* 最小化中は隠す。
* HUD の例外は握りつぶさず `hud-error`（型名＋ファイル名:行番号のみ、最大 5 行）として記録し、プロセスは継続する。
### 状態ブロックは必須の契約（補完）

状態ブロックは、Caller が `Process.Start` の前に作る**管理契約の必須部分**である。

* **起動時**: ブロックが開けない（`block-missing`／`open-error`）、形式が不正（`magic`／`version`／`size`／`flags`）、instance 不一致（`instance`）、BVE PID 不一致（`pid`）、短時間では解消しない torn（`torn`）のいずれかなら、**AppReady を公開しない**。診断 `state-contract-failed phase=init reason=<固定語> action=no-app-ready` を 1 回だけ出し、**管理初期化失敗として終了コード 4**（E2 の `init-failed`、終了行の理由は `state-contract-<reason>`）で終了する。マッピングは何も残さない。通常手動モード（`--managed` なし）には影響しない。
* **AppReady 成立後**に有効な読み取りができなくなった場合（ブロック内容の破壊・他 PID／instance への変化・読取り例外）は、プロセスを強制終了せず**フェイルセーフ**に入る: HUD を隠す／HUD 更新を止める（以後の読取り・更新・窓操作なし）／診断 `state-lost phase=run reason=<固定語> action=hud-failsafe` を 1 回だけ記録／新しい入力操作を禁止（`input_allowed` が閉じたまま。E4 の管理モードに入力操作はない）／**Caller の Stop を待つ**（Stop で終了コード 0）。Overlay は多重生成も破棄もしない。フェイルセーフは Stop まで解除しない（見た目が回復しても戻らない）。
* **正常な終了と異常消失を区別**する: `state-closed reason=caller-withdrew loss=no`（Caller の Dispose が Stop の前に書く Closed）、`state-lost`（異常消失）、Stop のみ（`hud-summary end=stop-without-closed`）。`hud-summary` の `end` は `init-failed`／`state-lost`／`caller-closed`／`stop-without-closed` のいずれか。
* Caller 側は変更なし（ブロック作成失敗は従来どおり `APP_LAUNCH_FAILED reason=state-block-create-failed`）。Python が AppReady 前に終了コード 4 で終わった場合は、E3 の `APP_EXIT_BEFORE_READY` の経路で扱われ、再起動はしない。
* 注: Caller が異常終了しても、Python が開いているマッピングは Closed なしで残るため、「Caller の消失」自体はこの契約では検出できない（E5 以降の耐障害性）。

診断（stderr、`[MANAGED] event=…`、状態変化のみ）: `state`（change＝session-on／off、driving-on／off、generation-changed、coalesced＝取りこぼし件数、mode）、`hud-update-start`／`hud-update-wait`、`hud-show`／`hud-hide`（reason）、`hud-window-linked`／`hud-window-unlinked`／`hud-window-wait`、`state-attached`／`state-contract-failed`／`state-lost`／`state-closed`／`state-detached`、`state-withdrawn`、`hud-error`、`hud-summary`（重複抑止件数・`end` などの総計）。

### 実データ経路（補完）

HUD の内容は既存の UDP 54321 のテレメトリで更新される。送信元は BveEX Current 用の `Class1.cs` だけで、**BVE5 Legacy にはない**（詳細と取得可否の表: `Handshake-PhaseE4-LegacyTelemetryAudit.md`）。したがって E4 の状態連動は Legacy でも動くが、Legacy の HUD は NOT live-updating であり、このコミットでは「対応済み」としない。

## 今回有効にしなかったもの（管理モード）

Esc 終了、BVE 窓消失での終了、キーフック全般、F1 メニュー、採点の開始・終了、Kickstart、ジャンプ・F8 のキー送信、「時刻と位置」窓の無効化。
HUD の内容に必要な物理・駅判定の更新（`update_physics_and_scoring`）は通常モードと同じ順序で動くが、`is_scoring_mode` は管理モードで ON にならないため採点は動かない（通常モードで採点 OFF のときと同じ）。

## 試験

* `tests\test_managed_hud_e4.py`（unittest）: 状態ブロック、ゲート、リーダー（疑似／実マッピング）、コントローラ（全シーケンス）、実プロセス（実 Qt ループ・実マッピング・疑似 Overlay）、実 Overlay の採点不変、静的検査。
* `Tests\Test-HudLinkE4.ps1`: 状態ブロックのバイト列、Python リーダーとの相互確認（64／32 ビット）、管理クラスの公開・撤回、HandshakeSession の配線、実 `main.py --managed` ＋疑似 BVE 窓による HUD の表示／非表示／復帰。UDP 54321 が空きで `main.py` が動いていないときだけ実 Overlay の節を実行し、それ以外は SKIP と表示する。

実機受入の手順は別途（配置後・別工程）。
