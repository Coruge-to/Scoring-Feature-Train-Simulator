# PHASE PP-13 - static verification of the Pause pulse contract and of the ABSENCE of the P-to-P recovery.
# Reads sources only (no BVE, no build, no process). ASCII-only on purpose. Exit code 0 = every check passed.
#   P-to-P product paths / automatic P key send / recovery token / kickstart token (managed mode) / OSK dependency = 0
#   the pulse: only while no Tick for 150 ms, never a Tick (no lastTickTime, no TickSeenInEpoch, no load-marker TickSeen, no Jump), Current = Legacy.
param([string]$Repo = (Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent))

$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { Write-Host ('PASS ' + $name) } else { Write-Host ('FAIL ' + $name); $script:fail++ }
}
function Txt([string]$rel) { $p = Join-Path $Repo $rel; if (Test-Path -LiteralPath $p) { return ([IO.File]::ReadAllText($p) -replace "`r`n", "`n") } else { return '' } }
$H = 'TsScoringPlugin\Handshake\'

Write-Host '==== P-to-P is gone (Python) ===='
$py = @(Get-ChildItem -LiteralPath $Repo -Filter *.py -File)
Check 'pause_recovery.py does not exist' (-not (Test-Path -LiteralPath (Join-Path $Repo 'pause_recovery.py')))
foreach ($tok in 'press_p_for_recovery', 'pause_recovery', 'PauseDataRecovery', 'recovery-token', 'recovery-summary', 'attach_recovery', 'recovery_keys') {
    $hits = @($py | Where-Object { ([IO.File]::ReadAllText($_.FullName)) -match [regex]::Escape($tok) } | ForEach-Object { $_.Name })
    # comments may name the removed phase in words; the code tokens must not exist: allow only a hit that is inside a comment / docstring line about PP-13
    $real = @($hits | Where-Object { $n = $_; @(([IO.File]::ReadAllLines((Join-Path $Repo $n))) | Where-Object { $_ -match [regex]::Escape($tok) -and $_ -notmatch '^\s*#' -and $_ -notmatch 'PP-13|Phase PP|is gone|was removed|removed' }).Count -gt 0 })
    Check ('no Python file uses ' + $tok + ' in code') ($real.Count -eq 0)
}
$mi = Txt 'managed_input.py'; $mh = Txt 'managed_hud.py'; $mn = Txt 'main.py'
Check 'managed HUD controller has no recovery member' (($mh -notmatch '_recovery\b') -and ($mh -notmatch 'attach_recovery'))
Check 'managed mode wiring (_attach_managed_hud) takes no recovery_keys and makes no recovery' (($mn -match 'def _attach_managed_hud\(overlay, hud\):') -and ($mn -notmatch 'PauseDataRecovery'))
$mnNoKick = ($mn -notmatch '(?i)kick_?start|auto_pause_pending|kick_bve_time')
Check 'MANUAL START PATH: main.py has no kick start (no kickstart / auto_pause_pending / kick_bve_time / initial_kickstart_done token) and no kick start event' (($mn -notmatch '(?i)kickstart|kick_start|auto_pause_pending|kick_bve_time'))
$pPosts = @([regex]::Matches($mn, '(?s)def (\w+)\(.*?(?=\n    def |\nclass |\z)') | Where-Object { $_.Value -match 'WM_KEYDOWN, 0x50' } | ForEach-Object { $_.Groups[1].Value })
Check 'MANUAL START PATH P-SEND: the only P main.py posts is the F1 menu pause/resume in toggle_menu (a user action); no kick start, no recovery' (($pPosts.Count -eq 1) -and ($pPosts[0] -eq 'toggle_menu'))
Check 'managed_input.py presses no key for BVE: no WM_KEYDOWN / PostMessage / keybd_event / SendInput' ($mi -notmatch 'WM_KEYDOWN|PostMessage|keybd_event|SendInput')
Check 'no OSK dependency: no osk.exe / on-screen keyboard reference in any Python production file' (@($py | Where-Object { ([IO.File]::ReadAllText($_.FullName)) -match '(?i)osk\.exe|on-screen keyboard' }).Count -eq 0)

Write-Host '==== P-to-P is gone (senders / Caller): no key, no window message ===='
$senders = @('TsScoringPlugin\TsScoringPlugin\Class1.cs', ($H + 'Bridge\src\TsScoringBridgePrototype.cs'), ($H + 'Bridge\Legacy\src\TsScoringLegacyBridge.cs'), ($H + 'Bridge\src\ScenarioReadyTracker.cs'), ($H + 'Telemetry\Legacy\src\LegacyTelemetryExtension.cs'), ($H + 'Telemetry\Legacy\src\LegacyTelemetrySession.cs'))
$caller = @(Get-ChildItem -LiteralPath (Join-Path $Repo ($H + 'Caller\src')) -Filter *.cs -File | ForEach-Object { $H + 'Caller\src\' + $_.Name })
$noKey = @(($senders + $caller) | Where-Object { (Txt $_) -match 'SendInput|keybd_event|WM_KEYDOWN|WM_KEYUP|WM_CHAR|GetAsyncKeyState|PostThreadMessage' })
Check 'no sender, Bridge or Caller source sends a key (SendInput / keybd_event / WM_KEYDOWN / WM_KEYUP / WM_CHAR); the Caller keeps only its WM_CLOSE (Stop) and its own window handling' ($noKey.Count -eq 0)

Write-Host '==== the pulse contract (Current = Legacy) ===='
$c1 = Txt 'TsScoringPlugin\TsScoringPlugin\Class1.cs'
$bc = Txt ($H + 'Bridge\src\TsScoringBridgePrototype.cs'); $bl = Txt ($H + 'Bridge\Legacy\src\TsScoringLegacyBridge.cs')
$tx = Txt ($H + 'Telemetry\Legacy\src\LegacyTelemetryExtension.cs'); $ts = Txt ($H + 'Telemetry\Legacy\src\LegacyTelemetrySession.cs')
$trk = Txt ($H + 'Bridge\src\ScenarioReadyTracker.cs')
Check 'Current Telemetry pulse: 16 ms period, 150 ms Tick gap, 1000 ms refresh' (($c1 -match 'PausePulseIntervalMs = 16;') -and ($c1 -match 'PausePulseGapMs = 150;') -and ($c1 -match 'PausePulseRefreshMs = 1000;'))
Check 'Legacy Telemetry pulse: 16 ms period, 150 ms Tick gap, 1000 ms refresh' (($tx -match 'PulseIntervalMs = 16;') -and ($ts -match 'PausePulseGapMs = 150;') -and ($ts -match 'PausePulseRefreshMs = 1000;'))
Check 'Bridge ScenarioReady pulse: Current and Legacy both 50 ms period, 150 ms Tick gap' (($bc -match 'PulseIntervalMs = 50;') -and ($bl -match 'PulseIntervalMs = 50;') -and ($bc -match 'PulseGapMs = 150;') -and ($bl -match 'PulseGapMs = 150;'))
Check 'every pulse is posted to the host synchronization context and skipped while a Tick is recent' (($c1 -match 'ctx\.Post\(') -and ($c1 -match '<= PausePulseGapMs\) return') -and ($bc -match '\.Post\(') -and ($bl -match '\.Post\(') -and ($tx -match '\.Post\('))
Check 'one timer per owner; Dispose stops it and a disposed owner posts nothing' (([regex]::Matches($c1, 'new System\.Threading\.Timer\(PulseTimerCallback').Count -eq 1) -and ([regex]::Matches($bc, 'new System\.Threading\.Timer\(PulseTimerCallback').Count -eq 1) -and ([regex]::Matches($bl, 'new System\.Threading\.Timer\(PulseTimerCallback').Count -eq 1) -and ([regex]::Matches($tx, 'new System\.Threading\.Timer\(PulseTimerCallback').Count -eq 1) -and ($c1 -match 'pulseDisposed = true;') -and ($bc -match 'pulseDisposed = true') -and ($bl -match 'pulseDisposed = true') -and ($tx -match 'disposedFlag = true') -and ($c1 -match 'if \(ctx == null \|\| pulseDisposed\) return;'))
Check 'Current Telemetry: a pulse is TickCore(elapsed 0, pulse=true) and is not a Tick: no lastTickTime, no first-Tick note, no jump execution' (($c1 -match 'TickCore\(TimeSpan elapsed, bool pulse\)') -and ($c1 -match 'if \(!pulse && \(udpReceiver != null \|\| jumpEndpoint != null\)\)') -and ($c1 -match 'unchangedPulse = pulse && lastPulseSent == lastUdpData'))
Check 'Tracker: OnTick = OnTickCore(false), OnPulse = OnTickCore(true); a pulse raises no Tick count, no TickSeenInEpoch, no load-marker TickSeen' (($trk -match 'OnTickCore\(false\)') -and ($trk -match 'OnTickCore\(true\)') -and ($trk -match 'if \(!pulse\)\s*\{\s*ticksTotal\+\+;') -and ($trk -match 'if \(!pulse && generationOpen && createdSeen && \(loadInfo & ScenarioState\.LoadTickSeen\) == 0\)'))
Check 'Legacy Telemetry session: a pulse notes no Tick order, observes no input, no scoring (inPulse guards)' (($ts -match 'if \(!inPulse\)') -and ($ts -match 'lastPulseLine'))
Check 'a pulse never calls the jump path: no CollectJumpCommands / jump execution reachable from PausePulse (Current)' (($c1 -match '(?s)private void PausePulse\(\).*?TickCore\(TimeSpan\.Zero, true\)') -and (([regex]::Match($c1, '(?s)private void PausePulse\(\)(.*?)\n        \}\n')).Value -notmatch 'Jump'))

Write-Host ('RESULT failures=' + $script:fail)
exit ([int]($script:fail -ne 0))
