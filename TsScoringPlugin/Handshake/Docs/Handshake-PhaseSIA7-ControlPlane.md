# Phase SI-A7 M1a — Extension の Tick 非依存制御プレーンと Ready epoch（観測先行）

状態: **実機受入れ確定（2026-10-11、O1〜O5 実施済み）。M1b は未実装。** 実機に配置されているのは M1a の観測用 DLL（Caller 0.13.0.0／両 Bridge 0.8.0.0）のまま。この文書を含むコミットでも配置・push は行わない（no automatic deployment）。
対象: Bridge（Current／Legacy）0.8.0.0、Caller 0.13.0.0、Python（`managed_state.py`／`managed_hud.py` の読取りと診断表示のみ）。

この文書は M1a の契約を固定する。M1b（Python の `scoring-on` token、自動 P-to-P、Pause 中再 ON の自動復旧）は**含まない**。

## 1. 位置づけ

| 項目 | M1a | M1b（今回は行わない） |
|---|---|---|
| Extension の Tick 非依存制御プレーン（Current に導入、Legacy と共通化） | する | — |
| 保持している ScenarioReady の Tick なし再公開 | する | — |
| epoch 2 値（`ReadyEpoch`／`TickSeenInEpoch`）を ScenarioState に公開 | する | — |
| Caller が epoch を読み、ログへ出し、TSAS `EpochInfo`（56〜59）へ写す | する（診断のみ） | — |
| Python が `EpochInfo` を読み、変化を 1 行ログに出す | する（診断のみ） | — |
| `KIND_SCORING_ON` の作成、scoring-on recovery token | **しない** | する |
| first P／second P、Pause 中再 ON の自動復旧、`PauseDataRecovery` への新経路 | **しない** | する |
| Cold（OFF のまま読み込んだシナリオ） | **しない**（D2） | 別フェーズで判断 |
| BVE5 Legacy の起動ゲート分割 | **不要と確定**（D3：O5 で BVE5 Legacy も Pause 中に Caller の Tick が継続した） | Current／Legacy は同じ M1b 契約へ接続できる |

SI-A7 M0 の決定: **D1** Current に Tick 非依存制御プレーンを導入する。**D2** TS Scoring OFF 中に読み込まれたシナリオ（Cold）は対象外。**D3** BVE5 Legacy の Python 起動ゲート分割は O5 の観測結果まで実装しない（→ 実機 O5 の結果、**分割は不要**。第 10 節）。**D4** 観測先行で進める。

## 2. 制御プレーン（`Bridge/src/HandshakeControlPlane.cs`）

SI-L1 で Legacy だけにあった `HandshakeControlPlane` を共通位置 `Bridge/src` へ移し、Current と Legacy が**同じソース 1 本**を使う（Current の csproj は直接、Legacy の csproj はソースリンク）。Legacy 側のコピーは削除した。

* ホスト非依存: ファイル内に BveEx／AtsEx／BveTypes／BVE 内部型を一切持たない（コメントを含めて静的検査で固定）。
* 専用背景スレッド 1 本（`TS Scoring control plane`、20 ms 周期）。アダプターはホスト固有のライフサイクル接続（ctor で作成・BridgeAvailable・スレッド開始、Dispose で停止、コールバックの転送、Tick でのスレッド再起動）だけを担当する。
* スレッドが扱ってよいもの（これだけ）: `Enabled`／`Stop`／`BridgeAvailable`／`Ready` の各名前付き Event、`BridgeInfo` の MemoryMappedFile、`Stopwatch`、`ObservationLog`、そして 2 つのコールバックで渡される**単純な数値**。
* スレッドが**絶対に触れない**もの: BveHacker、Scenario、Vehicle、TimeManager、現在位置、現在時刻、駅リスト、スレッド安全性が確認できていない BVE 内部オブジェクト、およびそれらを引数に取るコールバック。BVE の読取りはこれまでどおり Tick 上のトラッカーだけが行う。
* 1 ステップで例外が出てもスレッドは終わらない（Ready を撤回して次の周期からやり直す。Pause は数分続き得て、その間 Tick は再起動できない）。Tick はスレッドが終わっていた場合に限り再起動する（Dispose 後は再起動しない）。
* Dispose: トラッカーを先に閉じ（外部 ScenarioReady 撤回）、制御スレッドを `Join(1000)`（ゲートの外）で止めて Ready を撤回し、最後に BridgeAvailable を撤回する。二重 Dispose と Dispose 後の呼出しは無害で、`LiveWorkers` が 0 に戻る。

### 2.1 ロック順序（Lock order：固定、静的試験で検査）

> **control gate → owner（トラッカー）の gate**。この一方向だけ。

* 制御プレーンは自分のゲートを取り、**保持したまま**コールバック（`handshakeLost`／`handshakeUp`）を呼ぶ。コールバックはトラッカーのゲートを取る。コールバックは `TryConnectLocked`／`ReleaseLocked` の中（制御ゲート保持中）からだけ呼ばれる。
* トラッカーのゲートを保持している間に制御ゲートを取る経路は**無い**。トラッカーとアダプターの Tick が制御プレーンを見るのは、ロックなしの `volatile` 読取り（`HandshakeUp`／`ReadyEpoch`／`IsWorkerAlive`）だけ。トラッカーのソースは制御プレーンの型名もロック付きメンバーも持たない。
* ObservationLog のロックは両者より下位の葉。トラッカーは `lock (gate)` 1 つだけ、制御プレーンも `lock (gate)` 1 つだけ。アダプターは `lock` も `new Thread` も持たない。

### 2.2 Ready の外部契約（Current）

Current の Ready は「最初の Tick ＋最大 100 ms」ではなく「Enabled 後 20 ms 以内（制御スレッドの周期）」で出る。名前・規則（BridgeAvailable は ctor、Ready は Enabled∧¬Stop の間、撤回は ScenarioReady が先）は不変。Caller は Ready の遅延を前提にしていない。Phase B／C3／L1 の「Current 契約が基準コミットと同一」を固定する旧試験は、この意図した変更に合わせて再固定した（§9）。

## 3. Ready epoch

### 3.1 ScenarioState（Bridge → Caller、64 バイト、StateVersion=1 のまま）

| オフセット | 名前 | 内容 |
|---|---|---|
| 0〜35 | 既存 | **不変**（Version、Check＝0..16、LoadCheck＝24..35 の式も不変） |
| 36 | `EpochMagic` | `0x45504F31`（"EPO1"）。0＝情報なし（旧 Bridge） |
| 40 | `ReadyEpoch` | int32 ≥ 1。この Bridge インスタンスが Ready を作成した回数（制御プレーンの `readyCreateCount`）。1＝最初の Ready |
| 44 | `EpochFlags` | bit0 `TickSeenInEpoch`＝この epoch で Extension の Tick が 1 回以上走った |
| 48 | `EpochCheck` | `ReadyEpoch`・`EpochFlags`・世代・Sequence から導出（LoadCheck と同型）。別の書込みからの複写は検証に通らない |
| 52〜63 | 予約 | 将来用に空ける |

* 既存と同じ seqlock の**1 回の書込み**の中（奇数→全フィールド→偶数）。epoch を持たない書込み（旧 Bridge の形）は 36..51 をゼロへ書き戻す。
* 不正な `EpochMagic`／`EpochCheck`、未知のフラグビット、`ReadyEpoch`≤0 は「情報なし」と読む（ブロック自体・レベル・Load マーカーは有効のまま）。

### 3.2 TickSeenInEpoch の立て方（順序が契約）

1. 制御スレッドが Ready を作成すると、**`ReadyEpoch` を先に**更新し、その後 `up` を立てる（`volatile`）。
2. 制御スレッドは `tracker.OnHandshakeUp(epoch)` を呼ぶ: epoch を更新、**`TickSeenInEpoch=0`**、**保持している generation／level／loadInfo をそのまま再公開**（BVE を読まない）。Closed 後や Cold では level 0 のまま。**確立は決してしない**。
3. `OnTick` の**先頭**（`PublishLocked`／`EstablishLocked` より前）で `TickSeenInEpoch` を立てる。Ready を作成した制御スレッドの `OnHandshakeUp` がまだ届いていないうちに Tick が来た場合、Tick が `ReadyEpoch` を採用してフラグ 1 で始める（その Tick はその epoch に属する）。後から届いた `OnHandshakeUp` はフラグを戻さない。

結果: 「`ScenarioReady=1` かつ `TickSeenInEpoch=0`」は **Tick なしの再公開でしか成立しない**。通常起動の確立は同じ書込みでフラグも 1 になる（独立リーダーで 56 万回超の読取り中、確立 120 回の間に 0 回）。

### 3.3 TSAS（Caller → Python、64 バイト、Version=1 のまま）

| オフセット | 名前 | 内容 |
|---|---|---|
| 56 | `EpochInfo`（uint32） | 0＝情報なし。bit0 Supported、bit1 TickSeenInEpoch、bit8..23 `ReadyEpoch` の下位 16 bit |

* Caller は `ObserveScenarioLocked` の**同じ読出し**から写す。Ready 喪失・Dispose・情報なしの Bridge では 0。重複抑止（「ブロックが既に言っていることは書かない」）に含める。
* M1a では**診断のみ**。Caller の判断（DrivingActive、AppController の入力、通知、フェーズ）はエポックを一切参照しない（静的検査）。

## 4. Caller の診断ログ（Track A、`cycle=` つき、変化時 1 行）

| 行 | 意味 |
|---|---|
| `EPOCH_OBSERVED kind=first-ready-epoch\|resume-ready-epoch\|epoch-advanced ready_epoch=E tickSeenInEpoch=0/1 session=Y/N …` | このインスタンスが初めて読んだ epoch。`first-ready-epoch`＝ReadyEpoch 1（Bridge の最初の Ready）、`resume-ready-epoch`＝2 以上（Bridge が OFF をまたいで生きていた＝**再 ON**） |
| `EPOCH_SESSION_WITHOUT_TICK ready_epoch=E epochKind=first\|resume …` | ScenarioReady が ON なのに TickSeenInEpoch=0（**Pause 中再 ON の署名**）。epoch 内で 1 回 |
| `EPOCH_TICK_SEEN ready_epoch=E sinceEpochObservedMs=… sessionWithoutTickSeen=yes\|no` | TickSeenInEpoch が 0→1。`sinceEpochObservedMs` が「その epoch が Tick なしだった時間」 |
| `EPOCH_WITHDRAWN reason=ready-lost\|bridge-lost\|epoch-field-invalid\|caller-dispose …` | epoch が無くなった（OFF による撤回の Caller 側の観測／Dispose）。epoch 内で 1 回 |
| `APP_START_REQUEST_EPOCH`／`APP_START_SUPPRESSED_EPOCH`／`APP_LAUNCH_SUPPRESSED_EPOCH` | Python 起動要求・抑止の**伴走行**（`epochSupported= ready_epoch= tickSeenInEpoch=`）。既存の E1 行（`… dryRun=yes`）のテキストは**不変** |
| `CALLER_DISPOSE_BEGIN … epochSupported= ready_epoch= tickSeenInEpoch=` | Dispose 時の epoch |
| `CALLER_TICK_STATE state=flowing was=none\|silent …` ／ `state=silent was=flowing flowingMs= … silentAfterMs=500` | **Caller 自身の Tick（BVE の入力デバイス Tick）の状態**（O4／O5 用）。監視スレッドが、Tick が既に更新している Tick 数だけを見て、変化のときに 1 行書く。500 ms 新しい Tick が無ければ `silent`、戻れば `flowing`（`silentMs=` に無音の長さ）。`NotifyTick`（BVE のスレッド）は 1 バイトも変えていない。判断には使わない（DrivingActive は従来の 2 秒規則のまま） |

Bridge 側のログ: `READY_CREATE_OK … readyEpoch=E`、`READY_DISPOSED … readyEpoch=E`、`SR_EPOCH ready_epoch=E tickSeenInEpoch=0 why=handshake-up|adopted-at-tick`、`SR_EPOCH_TICK ready_epoch=E`、`SR_PUBLISHED … why=handshake-back-control`（再公開）、`CURRENT_TICK_AFTER_HANDSHAKE_UP`／`LEGACY_TICK_AFTER_HANDSHAKE_UP`（再 ON 後の最初の Tick）。

## 5. Python（観測のみ）

* `managed_state.py`: `OFF_EPOCH_INFO=56`、`StateSnapshot.epoch_supported`／`epoch_tick_seen`／`ready_epoch`。0 または解釈できない値（Supported ビット無し、未知ビット）は「情報なし」で、**エラーでもブロック喪失でもない**。`Version`／`Size` と既存オフセットは不変。
* `managed_hud.py`: epoch が変化したときだけ `[MANAGED] event=epoch-info …` を 1 行（情報の無いブロックでは 0 行）。`HudGate`、回復機構、入力、Overlay は epoch を見ない。
* **禁止事項の固定**: `KIND_SCORING_ON` の作成経路なし（`IMPLEMENTED_KINDS` は F5 のみ）、`press_p_for_recovery` の呼出しは SI-A6 の 2 箇所のまま、`FIRST_QUIET_S=0.3` と PauseIntent は不変（`pause_recovery.py` はバイト単位で不変）。epoch を作り得る全条件を真にしても token も key も出ない（試験で固定）。

## 6. 互換性

| 組合せ | 動作 |
|---|---|
| 旧 Bridge＋新 Caller／Python | 36..63 がゼロ → epoch 情報なし。`EPOCH_` ログ 0 行、`EpochInfo=0`、P 0 回（実在の旧 DLL で確認） |
| 新 Bridge＋旧 Caller | 旧 Caller は 0..35 しか読まない。通常動作。再 ON 時に保持 ScenarioReady が Tick なしで見えるようになるだけ |
| 新 Bridge＋新 Caller＋旧 Python | 旧 Python は 56..59 を読まない（旧 `managed_state.py` が新ブロックを同じ結果で読むことを確認） |
| Python 起動回数 | 不変。起動要求を決める `AppController.cs`・`DrivingActivityState.cs`・`AppProtocol.cs` はバイト単位で不変。OFF→ON ごとに新しい Caller インスタンスは従来どおり世代ごと 1 回。epoch の変化（Ready の撤回・再作成）では起動も再起動も起きない（連鎖試験で確認） |
| F5 復旧・FIRST_QUIET_S・PauseIntent | 不変。P の送信箇所は増えない |

## 7. 自動試験（この環境で実施済み）

* `Tests/Test-ExtensionControlPlaneSIA7.ps1`（Current と Legacy のアダプターを実 DLL で駆動。Legacy は別プロセス）: Enabled 検出が Tick 不要、OFF／ON でのスレッドのみによる撤回・再公開、再公開 epoch で TickSeenInEpoch=0・OnTick 先頭で 1、generation／loadInfo 維持、Closed／Cold で level 0、例外後のスレッド継続、Dispose（二重・後呼出し）、21 回の OFF→ON、ハンドル増加なし、Caller ログ語彙、起動要求 1 回、Bridge→Caller→TSAS→Python の連鎖、ScenarioState 36..51 の互換と破損、実在の旧 DLL との双方向互換、Current／Legacy の同一コードの同一結果。
* `Tools/Verify-PhaseSIA7.ps1`: 変更範囲、不変対象のバイト同一、制御プレーンの純度（BVE 型名混入なし）、ロック順序、アダプターの Tick・Dispose 順、DLL のバージョン・参照・禁止トークン、プライバシー。
* Python: `tests/test_epoch_info_sia7.py`（EpochInfo 読取り、後方互換、不正値、epoch／tick 変化、実マッピング、診断行、token・key が出ないこと、静的ガード）。

## 8. 配置とコミット

M1a の観測用 DLL は、利用者が観測 package のインストーラーで実機へ配置して O1〜O5 を実施した（リポジトリ側に自動配置の仕組みはない：no automatic deployment）。受入れ確定の作業（監査スクリプトの修正、既存検証の再固定、この文書、ローカルコミット）では、BVE の起動・配置・push を行っていない。Current 用の Bridge は `…\2.0\Extensions`、Legacy 用は `…\Legacy\Extensions` へ、片方のフォルダに他方の DLL を置かない規則のまま。M1b の DLL はまだ無い。

## 9. 再固定した既存試験（意図した変更）

Current の Ready タイミング契約と ScenarioReady の Tick なし再公開が意図して変わったため、以下の「前フェーズ時点の固定」を更新した。意味は維持し、弱体化していない: `Test-LegacyL1`（pause 中再 ON の C10／D2）、`Test-ScenarioReadyC3`（N5 フィールド一覧）、`Test-PauseRecoverySIA6`（A1 フィールド一覧、G2 バージョン）、`Test-DependencyNoticeM1`／`Test-AppControllerE1`／`Test-DrivingActiveD1`／`Test-AppProcessE3`／`Test-HudLinkE4`／`Test-ObservationC1`／`Test-LegacyInputLI0`（バージョン・DLL ハッシュ・変更範囲）、`Verify-PhaseC3`／`Verify-PhaseL1`（Current 契約＝基準コミット同一の範囲）、Python の `test_managed_hud_e4`（56..59 が EpochInfo）／`test_managed_input_sia3`（範囲）。

### 9.1 受入れ確定で再固定した Verify-PhaseL1／L3（旧い固定の記録）

M1a の実装時点で `Verify-PhaseL1`（3 項目）と `Verify-PhaseL3`（4 項目）は、**M1a の前から**（SI-A6 以降のコミットを想定しない範囲監査・配置ハッシュのため）失敗していた。削除も SKIP もせず、何を守る試験か・旧期待値・現行構造・新期待値を次のとおり記録して再固定した。検出力は落としていない（許可集合の拡張は完全一致または明示列挙で、列挙外のファイルが 1 つでも差分に入れば失敗する）。

| 試験 | 守るもの | 旧期待値 | 現行の構造 | 新期待値 |
|---|---|---|---|---|
| L1 基準（C3）との差分集合 | Current 契約は基準コミットから意図せず変わっていない | 差分 8 件、Bridge／Shared は 0 件 | SI-A6（読込マーカー）と M1a で Bridge／Shared の 6 ファイルが意図して変更。制御プレーンは `Bridge/src` へ移動 | 差分は**ちょうど 15 件**（L1 の 2＋M1 の 6＋Bridge／Shared の 6＋`Test-ScenarioReadyC3`）。Bridge／Shared の差分は列挙の 6 件のみで、`ScenarioObserver.cs`／`ObservationLog.cs` は基準とバイト同一 |
| L1 `Verify-PhaseC3` の差分量 | `Verify-PhaseC3` の変更が説明できる範囲 | 削除 15 行・追加 27 行 | M1a が Bridge の検査（バージョン、スレッド許可、状態ブロック、制御プレーン経由の呼出し順）を現行化 | 削除 19 行・追加 35 行、うち `SI-A7` を含む追加が 5 行以上、既存の識別パターン（L1 の絞り込み、M1／D1、E3）は維持 |
| L1 変更範囲リスト | 触ってよいファイルの列挙 | L1／M1／D1／E／LI／SI-0／SI-1 のファイルのみ | SI-A／SI-A6／SI-A7 のファイルが差分に入る | 上記に SI-A6／SI-A7 のファイル（Bridge／Shared の 7、試験 3、検証 1、文書 3）を**明示列挙して追加**。列挙外は失敗のまま |
| L1 制御プレーン（追加） | 制御プレーンが Current／Legacy 共通の 1 ソースである | （旧）Legacy 固有配置の `Bridge/Legacy/src/HandshakeControlPlane.cs` | 共通正本は `Bridge/src/HandshakeControlPlane.cs`。Current は直接、Legacy は `..\src\` のソースリンク | Legacy 側にコピーなし（ファイル不在、`Bridge/Legacy` 配下に制御プレーン名のファイルなし）、Legacy プロジェクトの自前 Compile は `AssemblyInfo.cs` と `TsScoringLegacyBridge.cs` のみ、共通ファイルはコメントを含めてホスト名・BVE 内部型名なし |
| L3 変更範囲（E4 コミット比） | L3 の変更が L3 のファイルに限られる | E4 コミット＋L3／LI／SI-0／SI-1 のファイルのみ | SI-A..SI-A7 の Python 採点・管理モード・制御プレーンの変更が差分に入る | 40 件を**明示列挙**（制御プレーン 15、Python 14、試験・文書・検証 11 の分類。列挙の各ファイルが本当に差分に入っていることも検査） |
| L3 制御プレーン凍結 | L3 は Caller／両 Bridge／Shared／採点 Python を変えていない | 凍結クラスの差分 0 件 | SI-A6／SI-A7 が制御プレーン、SI-A が `scoring_logic.py`／`utils.py`／`managed_state.py` を意図して変更 | 凍結クラスの差分は**上記の列挙ファイルのみ**。それ以外（`Class1.cs`、packages、旧フェーズ文書、`launcher.template.json` など）は 0 件のまま |
| L3 配置（Caller） | L3 は Caller を勝手に差し替えない | E4 の Caller 0.11.0.0（`1B2F7C1F`）のみ | 実機は SI-A6（Caller 0.12.0.0）→ M1a（Caller 0.13.0.0） | BVE6／BVE5 の Caller と両 Bridge が**同一世代**：SI-A6（`0F64654F`／`40376B11`／`E4F3F556`）または M1a（`8B677DCD`／`A310AB03`／`CC084CED`） |
| L3 配置（Bridge）と Telemetry | 配置の取り違え防止 | E4 の Bridge（`247F6724`／`C2883E40`）、Telemetry の既知ビルド一覧 | 上記と同じ。Telemetry は 0.4.0.0（`995486BE`）で M1a は変更しない | Bridge は上の世代検査へ統合。Telemetry は既知ビルド一覧に `995486BE` を追加し、さらに「ビルド済みは `995486BE`、配置済みは同一または未配置」を独立検査 |

### 9.2 観測監査スクリプトの修正（package 側、リポジトリ外）

* O4／O5：Extension の 3 秒以上の無 Tick 区間（`TICK_GAP`）は Pause だけでなくシナリオ選択・読込でも生じるため、`Mark-SIA7-Test.ps1` の目印で分類する。`pause` の目印の後 15 秒以内に始まる区間＝目印付き Pause（Pause の ANSWER はこれだけ）、`list` の目印に対応する区間＝シナリオ選択・読込（別表示）、どちらでもない区間＝unclassified（INFO、ANSWER に含めない）、区間に対応しなかった目印＝未解決（INFO）。目印のないログには Pause の ANSWER を出さず、従来の推定は参考（ESTIMATE）として残す。
* O3 End：Caller cycle ごとに `APP_PROCESS_STARTED`／`APP_STOP_REQUEST`／`APP_EXITED`／`APP_SHUTDOWN_END` を appPid で対応づけ、各 Python が自分の cycle 内で exitCode=0・killed=no で終了したことと、すべての cycle が Dispose まで完了したことを検査する。OFF→ON による複数の停止要求は失敗ではない。欠落した終了・非 0・killed=yes・PID 取り違え・重複した終了・停止要求のない残留・対応しない終了・最終 Dispose の欠落は失敗にする。

## 10. 実機観測（2026-10-11 実施・受入れ確定）

O1〜O5 の目的・操作・目視項目・ログ監査項目・保存コマンドは package の `README-SIA7-M1a.md` にある。実機ログ（`TSScoring-SIA7-O1-Observation.log` ほか 6 本）と目印ファイル（`TSScoring-SIA7-marks.txt`）を監査した結果。**Formal SI-A7 M1a accepted = YES。**

| ID | 判定 | 内容 |
|---|---|---|
| O1 | PASS | BVE6 Current、Pause 中 TS Scoring OFF→ON。Ready 撤回・epoch 2 で再成立、ScenarioReady を Tick なしで再公開、`TickSeenInEpoch=0` を Caller／Python が観測、手動で再開すると 1。自動 P 0 回、`scoring-on` token 0、例外 0 |
| O2 | PASS | 通常走行、通常 Pause／再開、Pause 中 F5（token 1・done 1・first P 1・second P 1）、シナリオ再選択・再読込。Python の実起動 1 回、Dispose 正常、例外 0 |
| O3 | 製品 PASS | Bridge Dispose の順序（ScenarioReady→Ready→BridgeAvailable の撤回）正常、Caller の epoch 撤回・Dispose 完了、各 cycle の Python は exitCode=0・killed=no（OFF→ON を含む 6 cycle）。再起動で Bridge inst=1、BridgeAvailable／Ready が `createdNew=Y`・epoch 1。終了直後の最初のプロセス確認は exit 1 だったが、再確認で BVE 0・対象 Python 0・UDP 待受なし（exit 0）。**永続的な残留はない** |
| O4 | 製品 PASS | BVE6 Current：目印付き Pause 3 区間（約 10／10／19 秒）はすべて Caller の Tick が**継続**（CONTINUED）。ダイジェスト上の STOPPED 区間は目印のないシナリオ選択・読込（Pause ではない） |
| O5 | 製品 PASS | BVE5 AtsEX Legacy：目印付き Pause 2 区間（約 10／21 秒）はどちらも Caller の Tick が**継続**。STOPPED は `list` の目印が付いた、Pause なしのシナリオ選択・読込。Pause 中のシナリオ選択・読込（2 回目の `list`）は独立した区間として現れず、未解決（決めない） |

**D3 = 分割不要。** Caller の Tick は BVE6 Current でも BVE5 Legacy でも Pause 中に継続した。BVE5 Legacy だけの起動ゲート分割は不要で、Current／Legacy は同じ M1b 契約へ接続できる。この観測は `Handshake-PhaseSIA-ManagedScoring.md` へは**反映していない**（第 11 節）。

**M1a と無関係の既存問題の分離：** O5 中に、既存の Legacy 採点開始不能（`scoring-start-refused reason=missing-jump`）を発見したが、M1a 起因ではなく別ブロッカーとして分離した。M1a の差分は共通ゲート・Telemetry・Legacy の jump を変更していない。

**不変の確認：** `FIRST_QUIET_S` は 0.3 秒のまま、自動 P を送る箇所は 2 か所のまま、`scoring-on` token の作成経路は存在しない。

## 11. 文書矛盾の扱い（`Handshake-PhaseSIA-ManagedScoring.md` §10.1）

§10.1 は「Pause で Caller の Tick が止まり、2 秒超で `tick-stale`」と書くが、BVE6 Current の SF 実機ログ（Extension の 5〜12 秒の無 Tick 区間に `DRIVING_ACTIVE_OFF reason=tick-stale` が 0 件）・D1 実機（Pause 15 秒で ON 維持）・`pause_recovery.py` 冒頭の記述とは矛盾する。**M1a では §10.1 を書き換えない。** 現時点の整理:

* **BVE6 Current**: O4 で明示的に再確認した（目印付き Pause 3 区間で Caller の Tick は継続）。
* **BVE5 Legacy**: O5 で観測した（目印付き Pause 2 区間で Caller の Tick は継続）。
* §10.1 の書き換えは、この観測を根拠に別途行う（M1a の範囲外）。O4／O5 は 1 回の実機観測であり、他の BVE の版・設定へは一般化しない。

## 12. 次の入口

M1a は受入れ確定。次の候補は、(a) Legacy 採点の開始不能（`missing-jump`）の解消（別フェーズ SI-B の β 版ブロッカー）、(b) M1b（Python の `scoring-on` token、first P → 成立確認 → second P。D3 が不要なので Current／Legacy 共通で接続できる）、(c) Cold（D2）。いずれも別フェーズで判断する。
