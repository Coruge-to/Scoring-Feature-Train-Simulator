# Phase SI-A6 — Pause 中に失われる BVE データの回復（トークン制御）

提供者: **Coruge-to** / 対象: 管理起動の Python、Caller 0.12.0.0、Current Bridge 0.7.0.0、Legacy Bridge 0.7.0.0（コアのソースは両 Bridge で同一）/ 状態: **SI-A6.2 まで実機受入れ済み（2026-10-11、§13）**。

## 1. 問題と、実機で確定した事実

BVE の内部状態を安全に取得・送信できるのは **Tick の上だけ**で、Tick は BVE が動いている間しか流れない。Pause 中に BVE の内部が変わっても、TS Scoring は新しいデータを受け取れない。回復は「P で Pause を一度解除して Tick を流し、データを取り、もう一度 P で元の Pause に戻す」。

SI-A4 は「Session ON ∧ Driving OFF ∧ PAUSED ∧ 駅リスト空」だけでこれを行い、**通常の読込**（最初の Tick の後 350〜500 ms の PAUSED 窓がある）で誤発火した（実機 SR: first ×3・second ×1）。SI-A6 は**具体的な操作ごとのトークン**を要求する。

| 場面 | 実機の挙動（SR セッション 2026-10-10 で確定） | SI-A6 |
|---|---|---|
| 初回読込 / 走行中の F5 / 走行中の標準時刻表ジャンプ | Pause にならない。自力で更新 | P 0 回 |
| Pause 中に一覧から別／同じシナリオ | Pause を引き継がない。通常開始 | P 0 回 |
| **Pause 中の F5（同一シナリオ再読込）** | Pause を引き継ぐ。Tick なし。データなし | **実装（§3）** |
| **Pause 中の標準時刻表ジャンプ** | Pause 維持。BVE の時刻は変わる。TS Scoring は取得不能 | **未実装（§5.1）** |
| **Pause 中の TS Scoring ON** | Tick なし。現在のデータなし | **未実装（§5.2）** |
| TS Scoring 公式ジャンプ | 採点中の機能。採点中は P が抑止され Pause に入らない | 対象外（トークンなし） |

## 2. 制御プレーンとデータプレーン

* **制御プレーン（Tick 非依存）**: 操作の検出、トークン、操作完了の確認、失効。F5 は Python が**物理キーのエッジ**として観測する（`GetAsyncKeyState`。フックなし・抑止なし・再注入なし。F5 は BVE へ通常どおり届く）。操作の完了は **Bridge が BVE の `ScenarioCreated` イベントを受けたこと**で、これを Tick なしで Python まで届ける（§4）。
* **データプレーン**: 第 1 の P（Pause 解除 → Tick）→ 当世代のテレメトリ・駅リスト・進行する BVE 時刻・STATUS RUNNING の成立 → 第 2 の P（元の Pause へ）。**1 トークンにつき第 1 の P は最大 1 回、第 2 の P は最大 1 回。**

## 3. F5 トークン（`pause_recovery.py`）

```
        F5 エッジ ∧ BVE(PID 一致)が前面 ∧ Session ON ∧ 最新の STATUS=PAUSED ∧ is_bve_loaded ∧ ロードマーカーあり    （SI-A6.1: 「PAUSED が 1 秒以上」は外した。§10）
 ARMED ───────────────────────────────────────────────────────────────────────────────►  世代がちょうど +1
                                                                     (F5_TO_GENERATION_MAX_S 以内)
 LOADING ── 当世代に Session/Tick/テレメトリ/駅リストが「P なしで」現れたら失効 ──┐
    │ マーカーの Created ∧ FIRST_QUIET_S 以上 Tick なし ∧ PID 一致ウィンドウあり ∧ 利用者が P を押していない
    ▼
 FIRST_SENT  (P を 1 回)  ── 当世代のテレメトリ ∧ 駅リスト ∧ STATUS RUNNING ∧ BVE 時刻が進行 ──►  P を 1 回 → done
```

* **作らない場面**: 走行中の F5（STATUS RUNNING）、他のプログラムが前面、Session OFF、状態ブロックが Closed、旧 Bridge／旧 Caller（マーカーなし。`recovery-token state=unavailable` を 1 回だけ記録して以後何もしない）。F5 は Pause 中で Driving が ON のまま（Caller の Tick は Pause 中も継続: D1）でも OFF でも対象。
* **失効（P を送らない）**: 利用者の手動 P、再度の F5（新しいトークンに置換）、Session OFF（立ち上がった後）、状態ブロックの Closed／喪失、Stop、世代が +1 以外／途中で変化、P なしで自力にデータが成立、PID 一致ウィンドウの消失、`F5_TO_GENERATION_MAX_S` 内に世代が動かない（F5 が再読込にならなかった）、第 2 の P が `SECOND_MAX_S` 内に来ない。
* **時間定数は 3 つだけ**（SI-A6.1 で `PAUSE_SETTLED_S`=1.0 を撤去）: `F5_TO_GENERATION_MAX_S`=2.0（BVE は F5 のハンドラ内で Close/Open する。SR では Python が世代変化を 28 ms 後に観測。利用者の次の操作＝一覧選択は秒単位。実測値は `f5_to_gen_ms` に出る）、`FIRST_QUIET_S`=0.3（走行中の再読込は ScenarioCreated の 12〜63 ms 後に Tick する。トリガーではなく Pause を引き継がなかったときの安全ガード）、`SECOND_MAX_S`=10（実測は第 1 の P の 0.3〜0.5 s 後にテレメトリ、その 0.1 s 後に第 2 の P）。**読込時間（SR で 6.4 s）はどこにも入っていない**: 読込の完了は時間ではなく ScenarioCreated で決まる。
* **P の送出**は `Overlay.press_p_for_recovery(hwnd)` ただ 1 か所（既存の `PostMessage`）。管理モードのほかの経路は P を送らない。IsReload は使わない（トラッカーの契約 `OnScenarioOpened()` はパラメーターなしのまま）。

## 4. 共有状態の追加（Bridge → Caller → Python）

* **Bridge → Caller**: `ScenarioState`（64 バイト、Version 1、サイズ、既存フィールドと Check の式は不変）の**バイト 24〜35**（従来は予約・ゼロ）。`LoadMagic`(24)=`0x4C4F4431`（"LOD1"）、`LoadInfo`(28)= bit0 `CreatedSeen`（この世代の `ScenarioCreated` を受けた）・bit1 `TickSeen`（この世代の最初の Tick を受けた）、`LoadCheck`(32)=LoadInfo・世代・シーケンスから導出。**同じ seqlock の 1 回の書込み**の中に世代・レベル・マーカーがある（奇数 → 全フィールド → 偶数）。旧 Caller は 0〜23 だけを読み、Check の式も不変なので影響なし。
* **書込みタイミング**: `ScenarioOpened`・`ScenarioClosed` で 0 に戻す／`ScenarioCreated`（BVE のイベントスレッド上、**Tick 不要**）で bit0／世代の最初の Tick で bit1。ScenarioReady の確立・解除には影響しない。BVE 内部オブジェクトは読まない。
* **Caller → Python**（状態ブロック `TSAS`、64 バイト、Version 1）の**バイト 48〜55**: `LoadInfo`(48)、`LoadMagic`(52)。Caller は同じ読出しから世代とマーカーを写す（`HandshakeSession.ObserveScenarioLocked`）。Closed／Dispose／マーカーなしの Bridge では 0。書込みの重複判定にマーカーを含める。
* **互換**: 旧 Bridge → LoadMagic 0 →「情報なし」。旧 Caller → 48〜55 がゼロ →「情報なし」。旧 Python → 48〜55 を読まない。いずれも**自動 P→P は無効（P を 1 回も送らない）**。API 名はリフレクション試験の曖昧さを避けるため `...WithLoad` の別名（既存のオーバーロードは作らない）。
* 追加のプロセス間通信は無い（Bridge → Python の直接経路なし）。

## 5. 実装していない 2 経路と、その理由（停止条件）

### 5.1 Pause 中の BVE 標準時刻表ジャンプ

* BveEX の公開 `IBveHacker` のイベントは `ScenarioOpened/Closed/PreviewScenarioCreated/ScenarioCreated/PreviewTick/PostTick` のみ（`BveEx.PluginHost.xml`）。時刻表ジャンプに対応するイベントは無い。
* 送信側の JUMP カウンタは Tick の中で時刻の不連続（>300 ms）から計算される（`Class1.cs`）。Pause 中は Tick が無いので更新されない。`JUMP_COMPLETE` は TS Scoring 公式ジャンプ専用。
* BVE 内部の `Conductor.OnJumped` はラッパーにあるが、それを通知に使うには未観測の BVE 内部フックが要る（背景スレッドからの読取り・推測・固定時間の待ちは禁止）。
* **不足する最小信号**: 「BVE 標準の時刻表ジャンプが完了した」ことを、Tick を介さず BVE スレッド上で 1 回通知する仕組み（BveEX の公開イベントとして、または実機で挙動を確認したフック）。それが無い限り識別できない。トークンの種類 `timetable-jump` は定義済みだが作成経路は無い（試験で固定）。

### 5.2 Pause 中の TS Scoring ON（Warm／Cold）

* TS Scoring OFF は `IInputDevice.Dispose` ＝ Caller の `End()` ＝ 管理 Python への Stop で、**Python は OFF 中に維持されない**。したがって「Python が起動済みのまま Pause 中に ON」（Warm）は現在の構造では存在しない。ON は常に新しい Caller サイクルと新しい Python。
* Bridge は Caller の `Enabled` を**自分の Tick からしか**見ない（`TsScoringBridgePrototype.Tick`）。Pause 中は Tick が無いので Ready も ScenarioReady も成立せず、Caller は「シナリオが存在すること」を知る手段が無い。Cold ON で Python を起動する条件（Session active）は Tick 前には成立しない。
* **不足する最小信号**: Tick に依存せず Bridge が Caller の Enabled を検知してシナリオの存在（ScenarioCreated 済み・Tick なし）を公開する経路（Bridge の背景スレッドでの Enabled 監視と公開。BVE 内部は読まない）と、それを使って Caller が管理 Python を 1 回だけ起動する条件。これは Bridge のスレッド構造と Phase B の「Tick 駆動」契約の変更を伴うため、独立した設計判断が要る。

## 6. SI-A4 の誤経路の撤去

* 削除: `ManagedHudController._tick_waiting_kickstart`、`ManagedInputController.kick_start_wanted/tick_waiting_kickstart`、`Overlay.kick_start_managed/kick_start_wanted/kick_start_managed_waiting`、`managed_window_step` と `tick_waiting` の第 1 段（ACTIVE の「テレメトリ待ち」からの P も含む）。
* 手動起動（`update_logic` → `_kick_start_first_press`）は不変。第 2 段 `_kick_start_second_press` は共有ステップに残るが、管理モードでは `auto_pause_pending` が立たないので動かない。
* 旧経路の試験（`test_managed_input_sia3` の F、`test_pause_ptop_width_sia4` の B・D_Scope）は**同じ状況を保ったまま「P 0 回」を要求する形に反転**した（削除ではなく強化）。

## 7. 維持した SI-A4 の修正

ALLTXT 第 4 群 HoldingSpeedTexts の解析と `max_pow_w`、Pause／TickStale 時の採点保持、Pause 中の入力抑止解除、Pause 復帰時の採点クロック再同期、早送り測定再同期、Session OFF／世代変更での採点破棄、明示的 OFF 後の旧採点非再開、`input-pause`／`input-resume`、Package Smoke の `System.Diagnostics.Process`、F11／F12、採点点数・規則。

## 8. 診断（固定語と数値のみ）

`recovery-token state=armed|loading|done|expired|unavailable kind=f5 ...`（loading に `f5_to_gen_ms`、expired に `reason=`）、`kickstart step=first|second token=f5 gen=N`、終了時 `recovery-summary`（トークンが作られたときだけ）。1 トークンで高々 5 行。

## 9. 試験

* Python `tests/test_pause_recovery_sia6.py`（93 件: 状態ブロックのマーカー、トークンの作成条件と作らない条件、往復、失効の全経路、P 0 回の全場面、旧経路の撤去、時間定数、SI-A6.1 の H クラス 16 件、変異 19 件が全滅）。
* PowerShell `Tests/Test-PauseRecoverySIA6.ps1`（64 件: ScenarioState／AppState の配置と互換、Current／Legacy トラッカー、Tick なしの ScenarioCreated 公開、実 Bridge ＋実 Caller、実 Caller 公開器のバイトを `managed_state.py` が読む）。
* 再固定した旧ガード（意味は維持）: M1-18/21/22/23/28/31、D1 D21、E1 E16、E3 S06/S13、E4 S02/S08/S09/S10、C1 L1、C3 N5、SI1 L08、LI0 H05、Python の P1・SI-A2・SI-A3 のスコープ。
* package: Smoke 85/0/0（SI-A6 の 70 ＋ SI-A6.1 のダイジェスト試験 15）、DLL 配置 Smoke 25/0/0。

## 10. SI-A6.1 — Pause 直後の F5 を通常の操作速度で成立させる（`pause_recovery.py` のみ）

* **実機で確定した原因**（Caller 0.12.0.0 ＋ Bridge 0.7.0.0 の新版実配置）: Pause 直後に F5 を押すと、BVE には F5 が届き `isReload=yes` で世代が +1 したが、トークンは 0 件・第 1／第 2 の P も 0 件で HUD は復帰しなかった。同じ実装で Pause の 5 秒後に F5 を押すと、自動 P→P が目視確認でき HUD も復帰した（機構・共有マーカー・PostMessage 経路は正常）。直接原因は §3 の `PAUSE_SETTLED_S`=1.0（トークン作成前に「PAUSED を受信してから 1.0 秒以上」を必須にしていた。未満なら診断も出さず return）。**利用者に見えない待ち時間を操作条件にしていた**。
* **契約の変更**: トークンの作成条件から「PAUSED 受信後の経過 1 秒」を外した（定数 `PAUSE_SETTLED_S` と `_status_since`／`_follow_status` を撤去。時間定数は 3 つ）。開始判定は F5 の物理押下エッジ ∧ **最新の** STATUS=PAUSED ∧ `is_bve_loaded` ∧ 対象 BVE PID が前面 ∧ Session ON ∧ ロードマーカー対応。これに続く **世代がちょうど +1** ∧ **新世代の ScenarioCreated** ∧ **新世代の Tick／Session／テレメトリ／駅リストが自力で成立しない（`FIRST_QUIET_S`=0.3）** が、通常読込との区別を与える。
* **1 秒を 0 に変えただけではない理由と、通常読込との区別**:
  * 通常読込・一覧からの別／同じシナリオ・初回読込は **F5 のエッジが無い**のでトークンが作られない（読込直後の一時 PAUSED 窓だけではトークンなし）。
  * 走行中の F5 は STATUS が RUNNING なのでトークンなし。F5 以外の世代変更は F5 エッジが無いのでトークンなし。世代が +1 以外なら失効。
  * 一時 PAUSED 窓（読込後 0.35〜0.5 s）の中で F5 を押したときだけは、旧条件では除外されていたがトークンが作られる。その再読込は Pause を引き継がず自力で Tick するため、`self-recovered` で失効し **P は 0 回**（試験で固定）。引き継いでいたなら、それはまさに回復が必要な Pause である。
  * ScenarioCreated 前の P は 0 回、第 1 の P は 1 トークンにつき最大 1 回、第 2 の P も最大 1 回、手動 P で失効、旧 Bridge／Caller（マーカーなし）は P 0 回。F5 は抑止も再注入もしない。
* **残る限界**: 送信側は 50 ms ごとに STATUS を送り、最後の Tick から 100 ms を超えて PAUSED とする（`Class1.cs`）。P の直後 約 150 ms 以内の F5 は最新の STATUS が RUNNING のままなのでトークンが作られない。人の操作（P → F5 の持ち替え）では起こらない短さだが、実機で確認していない（再試験 P-A41）。
* **ダイジェスト**（package の `Summarize-SIA.ps1`）: P-A41 は「印があるのに armed トークンが 0 件」を `AUTO-FAIL`（以前は `recovery-f5` が NA、`no-second-start` だけが PASS で `AUTO-PASS` と誤表示）。first／second が 0 回または複数回、順序違反も FAIL。印が無くトークンも kickstart も無ければ `AUTO-INCONCLUSIVE`。P-A42〜P-A44 は P 0 回が合格（`no-press`）で別規則。印が無い試験の `no-press`（NA）も AUTO-PASS にしない。
* **変えていないもの**: C#（Caller 0.12.0.0／Bridge 0.7.0.0）、共有状態の配置、Telemetry、`main.py`、`managed_hud.py`、`managed_state.py`。

## 11. SI-A6.2 — P の直後の高速 F5 でも F5 トークンを作る（`pause_recovery.py` のみ）

* **実機で確定した原因**（SI-A6.1 配置後）: 少し間を置いた P→F5 は 2 回とも正常（armed → loading → first → second → done が各 1 回、重複なし）。しかし人が非常に素早く P→F5 した最初の操作では、F5 は BVE に届き世代が +1・ScenarioCreated も成立したのに `recovery-token state=armed` が無く、P も 0 回で HUD は自力復帰しなかった。P を押した時点で BVE は Pause に入るが、Python が `STATUS:PAUSED` を受けるまで最大約 150 ms（送信側は 50 ms ごとに STATUS を送り、最後の Tick から 100 ms を超えて PAUSED。`Class1.cs`）遅れ、反映前の F5 では最新 STATUS がまだ RUNNING で、`_maybe_arm` が診断なしでトークン作成を拒否していた。
* **契約**: 物理 P の押下エッジを F5 と同じ方法（`GetAsyncKeyState` の観測のみ。P も F5 も抑止・再注入しない）で見て、短命な **PauseIntent**（「利用者がこの BVE を Pause に入れようとした」という証拠）を作る。PauseIntent は P を送る理由ではなく、**F5 エッジで STATUS=PAUSED の代わり**に使うだけである（トークンは `via=pause-intent`）。以後の条件（世代がちょうど +1、新世代の ScenarioCreated、新データが自力で成立しない、第 1 の P 最大 1 回、新 Telemetry・駅リスト・時刻進行のあとに第 2 の P 最大 1 回）は不変。
* **作成条件**: トークン無し ∧ Session ON（HUD モードが waiting／active）∧ 対象 BVE の PID が前面 ∧ 物理 P のエッジ ∧ **P の直前の最新 STATUS が RUNNING**（Pause 中の P は解除操作なので作らない）∧ `is_bve_loaded` ∧ P が BVE に届く（TS Scoring が P を抑止していない: `sys_keys_blocked`／メニュー表示／採点中のいずれでもない）。保持するのは PID・世代・状態変更カウント・作成時刻・P 直前の STATUS・消費済み。
* **失効**: F5 エッジで使い切る（トークンになってもならなくても）／Session OFF／Closed／状態ブロック喪失／Stop／Python 終了（`close`）／PID 不一致／前面が別ウィンドウ（BVE ウィンドウ消失を含む）／世代の変化／2 回目の P（Pause を取り消した）／STATUS=PAUSED の到着（以後は STATUS が証拠）／`PAUSE_INTENT_TTL_S`。失効は無言（操作ではなく STATUS の代用品）。
* **TTL の値と根拠**: `PAUSE_INTENT_TTL_S`=0.3 s。STATUS の最大遅れ約 150 ms（送信タイマー 50 ms ＋ PAUSED 判定 100 ms）＋ Python のタイマースロット 16 ms ＋ UDP とイベントループの遅れ。F5 がそれより遅ければ STATUS=PAUSED がすでに届いており（既存経路）、TTL はそれ以上を要さない。「P を押したのに Pause にならず走行を続ける」場合の失効も TTL が担う（走行中の BVE が見せる進行より短い）。時間定数は 3 つ → 4 つ。
* **P を送る場面は増えていない**: P だけ／P のあと F5 無し／Pause 中の P／採点中・メニュー中に抑止された P／走行中の F5 だけ／F5 無しの世代変更／F5 後の世代が +1 以外／初回読込／一覧読込／旧 Bridge／Caller／別 PID／BVE が前面でない／自力でデータが成立、のどれでも P は 0 回。`press_p_for_recovery` の呼び出しは `_advance_loading`（第 1）と `_advance_first_sent`（第 2）の 2 か所のみ（試験で固定）。
* **診断**: `recovery-token state=armed` に `via=status|pause-intent` を追加。`recovery-summary` に `rec_intent`（作成数）と `rec_intent_used`（トークンになった数）。PauseIntent 単体の行は出さない（ログ行数の予算）。
* **試験**: `tests/test_pause_recovery_sia6.py` の `I_MechanicalMinimumPF5`（機械的最短 P→F5 の 10 順序）と `J_PauseIntentContract`（作成・失効・安全・構造）。完成条件は「機械的な最短条件で PASS すれば人の通常操作速度を含む」。
* **ダイジェスト**（package の `Summarize-SIA.ps1`）: 正常なトークンが複数あるとき、セッション全体の first×2／second×2 を 1 トークンの重複と数えて `AUTO-FAIL` にしていた誤りを修正。**トークンごと**（armed〜done／expired）に判定し、FAIL は同一トークンでの first／second の重複と順序不正のみ。分離できない（armed が閉じる前の次の armed、armed の無い loading／kickstart、世代の不一致）は `AUTO-INCONCLUSIVE`。印なしでトークン 0 件は `AUTO-INCONCLUSIVE`。
* **補助スクリプト**（package の `Invoke-SIA61-Minimum-PF5.ps1`、P-A41 専用）: BVE6（`C:\Program Files\mackoy\BveTs6\BveTs.exe`）がちょうど 1 件で、その PID のウィンドウが前面のときだけ、`SendInput` で P（45 ms）→ 10 ms → F5（45 ms）を 1 回送って終了する。製品コードに試験用の入口は無い。BVE を使わない専用テスト窓で、送った P と F5 が製品と同じ 16 ms の `GetAsyncKeyState` ポーリングと WM_KEYDOWN の両方に観測されることを確認した。BVE 自身がこの入力で Pause／再読込するかは実機でのみ分かる（効かなければ手で最速に行う）。
* **変えていないもの**: C#（Caller 0.12.0.0／Bridge 0.7.0.0）、共有状態、Telemetry、`main.py`、`managed_hud.py`、`managed_state.py`、sender、`launcher.json`、採点点数・規則。

## 12. 既知の未再現事象

BVE 終了時に 1 回だけ未処理の NullReference 例外（ウィンドウ位置が右下寄り）。スタック未取得・再現せず。**製品コードは変更していない**。再発したらスタック全文を保存する（実機 P-A50 で毎回確認）。

## 13. 実機受入れ（SF、2026-10-11、BVE6 Current）

* **結果**: SI-A6.2 を正式に受入れた。ブロッカーなし。セッション SF は AUTO-PASS 5／AUTO-FAIL 0／AUTO-INCONCLUSIVE 0／警告 0。P-A41（F5 復旧）・P-A42（走行中の F5 で自動 P 0 回）・P-A43（Pause 中に別シナリオを一覧から読込、世代変化 1 回、自動 P 0 回）・P-A44（Pause 中に同じシナリオを再選択、同上）・P-A51（P だけ、自動 P 0 回）。目視でも HUD 復帰・元の Pause への復帰・連打なし・違和感なしを確認。
* **P-A41 のトークン**: 3 件、各 `armed → loading → first×1 → second×1 → done`（順序正常、重複なし）。`f5_to_gen_ms` 34／33／18、`total_ms` 2566／2579／2645。内訳は 1 件目 `via=status`（通常の操作速度）、2 件目 `via=pause-intent`（補助スクリプトの機械的 P→F5。P down 5 ms／P up 61 ms／F5 down 78 ms／F5 up 124 ms、すべて accepted=1）、3 件目 `via=pause-intent`（手で最速）。`recovery-summary`: `rec_created=3 rec_done=3 rec_expired=0 rec_first=3 rec_second=3 rec_intent=8 rec_intent_used=2`。つまり PauseIntent の分岐は自動試験に加えて**実機でも 2 回成立した**。ダイジェストの 1 行（`each: armed via=status, …`）は先頭トークンの文面だけを表示するので、`via` の内訳は生ログで確認すること。
* **セッション全体**: APP_READY ×1、Python 二重起動なし、kill／stop timeout／残留プロセスなし、`hud-error` なし、stale-epoch の破棄なし、`stderrDropped=0`、`input-summary` 正常（`in_suppressed=0`）、終了コード 0（`killed=no`）。
* **`FIRST_QUIET_S` = 0.3 秒をβ版の正式値として確定する**。ScenarioCreated の後に自然な Tick が来る走行中の再読込（これまでの観測は 12〜63 ms）へ P を先回りで送らないための値で、0.3 秒版は実機受入れ済み。短縮の効果より誤 Pause の防止を優先する。変更しない。
* **将来の任意課題（β版必須ではない）**: 各種実機試験で ScenarioCreated から最初の自然な Tick までの時間を、Current／Legacy・PC・シナリオ・負荷条件とともに記録し続け、最大値・上位分布・外れ値を将来の静穏ガード最適化に使う。`TickSequence`／`TelemetrySequence` の変化を直接観測する方式も候補。作者定義のハンドル文字列が極端に長い場合の汎用表示切替案と同程度の優先度で、余裕があれば検討する。
* **未実装のまま**: Pause 中の標準時刻表ジャンプ、Pause 中の TS Scoring ON（§5）、Extension 制御プレーン。
