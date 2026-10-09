# Phase E3 — 管理対象 Python プロセスの起動と停止（Caller 0.10.0.0）

E1 の論理的な起動要求（`APP_START_REQUEST`）を、実際の Python プロセス 1 個の起動へ接続します。シナリオ終了・Pause・DrivingActive の OFF・
ScenarioReady の撤回では Python を終了させません。終了させるのは Caller の Dispose だけです。

## 範囲

* 含む: 開発用 launcher 設定の読込み、Stop Event の事前作成、instance ID、`Process.Start`、AppReady 待ち、PID 保持、Dispose での Stop と終了コード観測、stderr 診断。
* 含まない: 単一 EXE 化、Session／Driving Event、HUD・採点の統合、Job Object、クラッシュ時の自動再起動・バックオフ、インストーラー、Current／Legacy Bridge の変更、実機配置。

## 構成

| 層 | ファイル | 役割 |
|---|---|---|
| 判断 | `AppController.cs`（E1・無変更） | 世代ごとに 1 回の起動要求、Dispose で 1 回の停止要求。純粋状態機械 |
| 設定 | `LauncherConfig.cs` | `launcher.json` の読込みと検証（実行はしない） |
| プロセス | `AppProcessManager.cs` | 起動要求を最大 1 個の実プロセスにし、Event・PID・Process・診断・解放を所有する |
| 配線 | `HandshakeSession.cs` | 起動要求を `RequestStart` に渡す（監視スレッド・軽量）。Dispose の最後（ゲート解放後）に `Shutdown` |

`NotifyTick`／デバイスの `Tick`／`Load`／`Dispose` の既存経路は変えていません（Dispose は `End()` を呼ぶだけ）。

## launcher.json

場所: `%LOCALAPPDATA%\Coruge-to\TS Scoring\launcher.json`（OS のフォルダーから実行時に決定。リポジトリには置かない）。**無ければ何も起動せず、現在の手動運用のまま**です。

```json
{
  "schemaVersion": 1,
  "mode": "development",
  "pythonExecutable": "<python.exe の絶対パス>",
  "scriptPath": "<main.py の絶対パス>",
  "workingDirectory": "<main.py のあるフォルダーの絶対パス>"
}
```

テンプレートは `Docs\launcher.template.json`（プレースホルダーのみ。そのままでは読込みが拒否される）。

検証（すべて満たさない限り起動しない。設定不正は診断して見送るだけで、BVE も Caller も落とさない）:

* 単一の平坦な JSON オブジェクト、UTF-8（BOM 可）、8 KiB 以下、キーの重複・未知キー・入れ子・配列なし。パスワード・トークンの項目は存在しない。
* `mode` は `development`。
* 3 つのパスはすべて `X:\dir\file` 形式の絶対パス（UNC・ドライブ相対・`/`・`.`／`..`・空要素・`%`・引用符・`<>|*?`・制御文字（NUL 含む）・先頭末尾の空白・末尾のドット・`:` の追加・259 文字超は拒否）。環境変数や相対パスの展開はしない。PATH の `python` は使わない。
* `pythonExecutable` は実在する `.exe`（`pythonw.exe` は拒否: stderr 診断が要る）、`scriptPath` は実在する `.py` ファイル、`workingDirectory` は実在するディレクトリ。
* ログに出る理由は固定の語彙（`file-absent`、`python-not-found` など）だけで、ファイルの値やパスは一切ログに出ません。

## プロセス契約

* **起動条件**: E1 の `APP_START_REQUEST`。`RequestStart` は監視スレッドで呼ばれるためロックとスレッド開始だけで戻る（ファイル・プロセス・待機なし）。以降はすべて専用ワーカースレッドが行い、ワーカーが `Process` の唯一の所有者。
* **1 Caller インスタンスにつき最大 1 回の `Process.Start`**:
  * プロセスが起動中・Ready・停止中のときの要求は実起動抑止（`APP_LAUNCH_SUPPRESSED reason=process-…`）。再読込で論理要求が増えても Python は 1 個のまま。
  * 一度 `Process.Start` の手前（Stop Event 作成）まで進んだ試行は、結果にかかわらず消費済み（終了済み・クラッシュ・起動失敗・Ready 不成立）。同じ Caller インスタンスでは再起動しない（`reason=attempt-already-used`）。自動再起動は後続 Phase。
  * 設定なし／不正は試行を消費しない（次の要求で再度読み込む。同じ状況のログは 1 回だけ）。
* **instance ID**: 試行ごとの `Guid.NewGuid().ToString("N")`（32 桁小文字 hex）。再利用しない。
* **Stop Event**: `Local\TSScoringPlugin.v1.<BVE PID>.App.<INST>.Stop` を Python 起動前に Caller が作成。Set するのは `Shutdown`（Dispose）の 1 回だけ。例外として、Ready にならなかったプロセスの後始末（E0 §3.4「AppFailed のタイムアウト後始末」）でも 1 回 Set する。ScenarioReady 撤回・シナリオ終了・再読込・DrivingActive の soft／hard OFF・Pause・BveEX の一時的な状態変化では Set しない。
* **起動**: `FileName` = 設定の絶対パス、`Arguments` = `"<script>" --managed --owner caller --bve-pid <n> --instance <inst>`、`WorkingDirectory` = 設定値、`UseShellExecute=false`、`CreateNoWindow`。シェル・PATH 検索なし。`-I` は付けない（ユーザー site-packages の PyQt6 が必要）。環境変数は変更しない。.NET Framework には `ArgumentList` が無いため、固定トークンと検証済み 3 値（スクリプトの絶対パス・10 進の BVE PID・32 桁 hex）だけで文字列を組み立てる。
* **AppReady**: `Local\…App.<INST>.Ready` を毎回開き直して Signaled を確認（古いハンドルを持たない）。Ready 前の終了、Ready 後の終了、15 秒のタイムアウトを検出。Dispose が始まっていれば、Ready が見えても採用しない（`APP_READY_IGNORED`）。
* **Dispose**: 新しい起動を禁止 → Stop を Set → ワーカーを有限時間 Join。プロセスは Stop 後 3 秒の猶予で自分で終了することを期待し、終了しなければ **この Caller が起動した Process オブジェクトに対してのみ** `Kill` を 1 回（E0 §4.1／注意 3 の設計。名前検索・`taskkill`・`Stop-Process` は使わない）。その後 2 秒だけ終了を待つ。Dispose 全体の上限は約 7 秒（猶予 3 + Kill 後 2 + ストリーム 0.5 + 余裕 1.5）。通常は数十 ms。Kill 後も残った場合は `APP_PROCESS_RESIDUAL` を記録して戻る（無期限に待たない）。
* **解放**: Stop／Ready のハンドル、Process、stdout／stderr の読取り、待機用ハンドルを解放。

## 診断ログ（共有観測ログ、Track A、状態変化のみ、パス・個人情報なし）

E1 の `APP_START_REQUEST`／`APP_START_SUPPRESSED`／`APP_STOP_REQUEST`／`APP_STOP_NOT_REQUIRED`（`dryRun=yes` は「判断の記録行」を表す）は無変更です。E3 が追加する行:

`APP_LAUNCH_CONFIG_ABSENT`／`APP_LAUNCH_CONFIG_INVALID reason=…`、`APP_LAUNCH_BEGIN`（instance）、`APP_PROCESS_STARTED`（appPid・instance）、`APP_PROCESS_START_FAILED`（例外型・Win32 コード）、`APP_READY_WAIT_BEGIN`、`APP_READY`、`APP_READY_IGNORED`、`APP_READY_TIMEOUT`、`APP_EXIT_BEFORE_READY`／`APP_EXIT_AFTER_READY`（終了コードと名前）、`APP_LAUNCH_SUPPRESSED`、`APP_STOP_SIGNALLED`、`APP_STOP_TIMEOUT`、`APP_KILLED`、`APP_EXITED`、`APP_PROCESS_RESIDUAL`、`APP_STREAMS`、`APP_STDERR`、`APP_PROCESS_EXCEPTION`、`APP_SHUTDOWN_BEGIN`／`APP_SHUTDOWN_END`。

終了コードの名前は E2 の表（0 normal、1 runtime-error、2 udp-bind-failed、3 duplicate-instance、4 init-failed、5 args-invalid）に従います。

stderr／stdout:

* 両方をリダイレクトして非同期に読む（`main.py` は stdout を使わないが、ハンドル継承とパイプ詰まりを避けるため読み捨てる。バイト数だけ数える）。`pythonw.exe` は使わない。
* stderr のうち E2 の `[MANAGED] …` 行（状態変化・ASCII・パスなし）だけを、1 プロセスあたり最大 20 行・1 行 160 文字（印字可能 ASCII のみ）まで共有ログへ転記し、残りは件数だけ記録する。トレースバック等（パスを含み得る）は転記せず、直近の例外の**型名だけ**を `APP_STREAMS lastErrorType=` に残す。
* Desktop 固定の `debug.log` には書かない。

## 時間定数（`AppProcessTiming`、1 か所）

| 名前 | 値 | 根拠 |
|---|---|---|
| `ReadyTimeoutMs` | 15000 | E0 §3.3（初期 15 秒）。E2 の実測は Qt＋UDP bind で約 1〜3 秒 |
| `ReadyPollMs` | 25 | ワーカー専用。BVE のスレッドでは待たない |
| `ExitPollMs` | 100 | 同上 |
| `StopGraceMs` | 3000 | E0 §5.1（3 秒以内に終了） |
| `KillWaitMs` | 2000 | Kill 後の終了確認 |
| `StreamDrainMs` | 500 | 終了後の出力読取り |
| `ShutdownMarginMs` | 1500 | Dispose の Join に足す余裕 |

## 試験

`Tests\Test-AppProcessE3.ps1`（設定契約、起動記述、実プロセスでの Ready／Stop／終了コード／Kill／タイムアウト／資源解放、HandshakeSession の配線、実デバイスの Load→Tick→Dispose、E2 管理 child、32 ビット、静的検査）。実 `main.py` の限定スモークは、UDP 54321 が空き、かつ `main.py` が動いていないときだけ実行し、それ以外は SKIP と表示する（合格には数えない）。試験は利用者の本物の `launcher.json` を読まない（`LauncherConfigLoader.TestPath`）。

既存の静的ガード（E1／D1／M1／C1／C3／L1／E2）は「Caller は何も起動しない」前提だったため、各 Phase のコミットを基準にした記述へ更新し、E3 の許可範囲（`AppProcessManager.cs`・`LauncherConfig.cs`）を明示しました。

## 実機受入（配置後・別工程）

1. `launcher.json` が無い状態: BVE を起動・シナリオ読込み・終了。Python は起動されず、`APP_LAUNCH_CONFIG_ABSENT` が 1 行だけ。
2. `launcher.json` を置く（`TS Scoring` が通常起動中でないこと）: シナリオの最初の走行で `APP_LAUNCH_BEGIN` → `APP_PROCESS_STARTED` → `APP_READY`。タスクマネージャーに管理 Python が 1 個（BVE の子）。
3. Pause・再読込・シナリオ終了・選択画面の往復: Python が増えず、終了もしない（`APP_LAUNCH_SUPPRESSED` が再読込ごとに 1 行）。
4. TS Scoring を OFF／BVE を終了: `APP_STOP_SIGNALLED` → `APP_EXITED exitCode=0`、残留 Python なし。
5. 手動で `main.py` を先に起動してから管理起動: `APP_EXIT_BEFORE_READY exitCode=2`（UDP bind 失敗）。再起動しない。
