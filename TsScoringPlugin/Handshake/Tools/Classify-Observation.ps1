# PHASE C1 - offline classifier for the observation log. Read-only: it only READS the log file it is given and prints text.
# Default log: <user profile>\Downloads\TSScoring-Phase-C1-Observation.log  (the fixed file written by the Caller and the Bridge)
# Usage:  powershell -File Tools\Classify-Observation.ps1 [-LogPath <file>]
# This script is ASCII-only on purpose.
param([string]$LogPath = (Join-Path (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads') 'TSScoring-Phase-C1-Observation.log'))

if (-not (Test-Path -LiteralPath $LogPath)) { Write-Output "No log file at the given path."; exit 2 }

$lineRx = '^(?<clock>\d\d:\d\d:\d\d\.\d{3}) q=(?<q>[\d.]+) P=(?<pid>\d+) S=(?<src>Caller|Bridge) T=(?<track>A|B|AB) th=(?<th>\d+) (?<evt>\S+)(?: (?<rest>.*))?$'
$events = New-Object System.Collections.Generic.List[object]
$bad = 0
foreach ($raw in [IO.File]::ReadAllLines($LogPath, [Text.Encoding]::UTF8)) {
    if ($raw.StartsWith('#') -or $raw.Trim().Length -eq 0) { continue }
    $m = [regex]::Match($raw, $lineRx)
    if (-not $m.Success) { $bad++; continue }
    $kv = @{}
    foreach ($p in [regex]::Matches($m.Groups['rest'].Value, '(\w+)=(\S+)')) { $kv[$p.Groups[1].Value] = $p.Groups[2].Value }
    $events.Add([pscustomobject]@{ Clock = $m.Groups['clock'].Value; Q = [double]$m.Groups['q'].Value; Pid = [int]$m.Groups['pid'].Value; Src = $m.Groups['src'].Value; Track = $m.Groups['track'].Value; Evt = $m.Groups['evt'].Value; Kv = $kv; Raw = $raw })
}

"== Phase C1 observation log classification =="
"lines parsed: {0}   unparsable lines: {1}" -f $events.Count, $bad

# ---- generation / PID consistency -------------------------------------------------------------------------------------------
$pids = @($events | ForEach-Object { $_.Pid } | Sort-Object -Unique)
$vers = @($events | Where-Object { $_.Kv.ContainsKey('ver') } | ForEach-Object { $_.Src + ':' + $_.Kv['ver'] } | Sort-Object -Unique)
$verValues = @($events | Where-Object { $_.Kv.ContainsKey('ver') } | ForEach-Object { $_.Kv['ver'] } | Sort-Object -Unique)
$bridgeInst = @($events | Where-Object { $_.Evt -eq 'BRIDGE_CTOR_BEGIN' } | ForEach-Object { $_.Kv['inst'] } | Sort-Object -Unique)
$callerInst = @($events | Where-Object { $_.Evt -eq 'CALLER_CTOR_BEGIN' } | ForEach-Object { $_.Kv['inst'] } | Sort-Object -Unique)
"pids in log: {0}   dll versions seen: {1}   bridge instances: {2}   caller instances: {3}" -f ($pids -join ','), ($vers -join ','), ($bridgeInst -join ','), ($callerInst -join ',')
$generationMismatch = ($pids.Count -gt 1) -or ($verValues.Count -gt 1)
if ($pids.Count -gt 1) { "CLASS DllOrPidGenerationMismatch: more than one PID in one log (two BVE processes shared the file or the log was not re-initialised)" }
if ($verValues.Count -gt 1) { "CLASS DllOrPidGenerationMismatch: Caller and Bridge report different DLL versions: " + ($vers -join ', ') }
if (-not $generationMismatch) { "generation check: consistent (one PID, one DLL version)" }

# ---- Track B ----------------------------------------------------------------------------------------------------------------
"== Track B: start-up / dependency notice per Caller enabled cycle =="
$cycles = @($events | Where-Object { $_.Src -eq 'Caller' -and $_.Evt -eq 'CALLER_ENABLED_CREATED' })
if ($cycles.Count -eq 0) { "no Caller enabled cycle in the log" }
$bridgeCtors = @($events | Where-Object { $_.Evt -eq 'BRIDGE_CTOR_BEGIN' })
$availOks = @($events | Where-Object { $_.Evt -eq 'AVAIL_CREATE_OK' })
$classes = New-Object System.Collections.Generic.List[string]
foreach ($c in $cycles) {
    $cyc = $c.Kv['cycle']
    $mine = @($events | Where-Object { $_.Src -eq 'Caller' -and $_.Kv['cycle'] -eq $cyc })
    $q0 = $c.Q
    $firstPresent = $mine | Where-Object { $_.Evt -eq 'AVAIL_FIRST_PRESENT' } | Select-Object -First 1
    $timeout = $mine | Where-Object { $_.Evt -eq 'TIMEOUT_REACHED' } | Select-Object -First 1
    $judge = $mine | Where-Object { $_.Evt -eq 'NOTICE_JUDGE_BEGIN' } | Select-Object -First 1
    $call = $mine | Where-Object { $_.Evt -eq 'NOTICE_SHOW_CALL' } | Select-Object -First 1
    $supp = $mine | Where-Object { $_.Evt -eq 'NOTICE_SUPPRESSED' } | Select-Object -First 1
    $readyFirst = $mine | Where-Object { $_.Evt -eq 'READY_FIRST_PRESENT' } | Select-Object -First 1
    # the Bridge's BridgeAvailable creation nearest before the Caller first saw it (or the first one after this cycle started)
    $endQ = [double]::MaxValue
    $nextCycle = $cycles | Where-Object { $_.Q -gt $q0 } | Select-Object -First 1
    if ($nextCycle) { $endQ = $nextCycle.Q }
    $bridgeOk = $availOks | Where-Object { $_.Q -le $endQ } | Sort-Object { [math]::Abs($_.Q - $q0) } | Select-Object -First 1
    $ctor = $bridgeCtors | Where-Object { $_.Q -le $endQ } | Sort-Object { [math]::Abs($_.Q - $q0) } | Select-Object -First 1

    $line = "cycle $cyc : enabled@" + $c.Clock
    if ($ctor) { $line += "  bridgeCtor " + ([math]::Round($ctor.Q - $q0, 1)) + " ms after Enabled" }
    if ($bridgeOk) { $line += "  bridgeAvailableCreated " + ([math]::Round($bridgeOk.Q - $q0, 1)) + " ms after Enabled" }
    if ($firstPresent) { $line += "  callerSawAvailable " + $firstPresent.Kv['sinceEnabledMs'] + " ms" }
    if ($readyFirst) { $line += "  ready " + $readyFirst.Kv['sinceEnabledMs'] + " ms" }
    $line
    $initOrder = 'unknown'
    if ($ctor) { $initOrder = if ($ctor.Q -ge $q0) { 'CallerFirst' } else { 'BridgeFirst' } }
    "    init order: $initOrder" + $(if ($initOrder -eq 'BridgeFirst') { '  (CLASS InitOrderBridgeFirst: unlike the ~300 ms Bridge-after-Caller pattern of the Phase B field tests)' } else { '' })
    if ($initOrder -eq 'BridgeFirst') { $classes.Add("InitOrderBridgeFirst") }

    $shown = $null -ne $call
    if ($shown) {
        $bridgeEarly = $bridgeOk -and (($bridgeOk.Q - $q0) -lt 500) -and ($bridgeOk.Q -le $call.Q)
        if ($call.Kv['bridgeAtCall'] -eq 'Present') {
            "    CLASS BecamePresentAfterJudgementBeforeShow: judged Missing, but BridgeAvailable was present when the dialog was requested"; $classes.Add('BecamePresentAfterJudgement')
        } elseif ($bridgeEarly) {
            "    CLASS NoticedUnder500ms: the Bridge created BridgeAvailable " + ([math]::Round($bridgeOk.Q - $q0, 1)) + " ms after Enabled (< 500) yet the notice was shown (Caller missed it)"; $classes.Add('NoticedUnder500ms')
        } else {
            $late = if ($bridgeOk) { ([math]::Round($bridgeOk.Q - $q0, 1)).ToString() + ' ms' } else { 'never in this log' }
            "    CLASS BridgeAvailableExceeded500ms: notice shown; Bridge created BridgeAvailable $late after Enabled"; $classes.Add('Exceeded500ms')
        }
        "    notice: judgeLag=" + $(if ($judge) { $judge.Kv['lagSinceTimeoutMs'] } else { '?' }) + " ms, gap(recheck->call)=" + $call.Kv['gapSinceRecheckMs'] + " ms, bridgeAtCall=" + $call.Kv['bridgeAtCall']
    } elseif ($supp) {
        "    CLASS SuppressedAtRecheck: timeout reached, notice suppressed (" + $supp.Kv['reason'] + ")"; $classes.Add('SuppressedAtRecheck')
    } else {
        $timeoutText = if ($timeout) { 'timeout reached but no notice record' } else { 'no timeout, no notice' }
        "    CLASS NotReproduced: $timeoutText"; $classes.Add('NotReproduced')
    }
}

# ---- Track A ----------------------------------------------------------------------------------------------------------------
"== Track A: scenario life cycle and ScenarioReady candidates (log-only candidates; not a ScenarioReady implementation) =="
$aEvents = @($events | Where-Object { $_.Src -eq 'Bridge' -and $_.Track -in 'A', 'AB' })
$gens = @($aEvents | Where-Object { $_.Kv.ContainsKey('ScenarioGeneration') } | ForEach-Object { $_.Kv['inst'] + '/' + $_.Kv['ScenarioGeneration'] } | Sort-Object -Unique)
if ($gens.Count -eq 0) { "no scenario events in the log (the Bridge saw no ScenarioOpened / ScenarioCreated / Tick-with-scenario)" }
foreach ($g in $gens) {
    $parts = $g -split '/'
    $ge = @($aEvents | Where-Object { $_.Kv['inst'] -eq $parts[0] -and $_.Kv['ScenarioGeneration'] -eq $parts[1] })
    $t0 = ($ge | Select-Object -First 1).Q
    $seq = ($ge | Where-Object { $_.Evt -in 'GEN_BEGIN', 'SCN_OPENED', 'SCN_PREVIEW_CREATED', 'SCN_CREATED', 'CAND_A', 'CAND_B', 'CAND_C', 'CAND_D', 'CAND_E', 'CAND_F', 'CAND_D_NOT_MET', 'SCN_CLOSED', 'LATE_ATTACH' } | ForEach-Object { $_.Evt + '@+' + [math]::Round($_.Q - $t0, 1) }) -join '  '
    "bridge-instance $($parts[0]) generation $($parts[1]):"
    "    $seq"
    $sum = $ge | Where-Object { $_.Evt -eq 'GEN_SUMMARY' } | Select-Object -Last 1
    if ($sum) { "    summary: candidates=" + $sum.Kv['candidates'] + " ticks=" + $sum.Kv['ticks'] + " pre/post=" + $sum.Kv['preTicks'] + '/' + $sum.Kv['postTicks'] + " reason=" + $sum.Kv['reason'] }
    $fo = $ge | Where-Object { $_.Evt -eq 'FRAME_ORDER' } | Select-Object -First 1
    if ($fo) { "    frame order after ScenarioCreated: " + ($fo.Kv.Values -join ' ') }
}
$tg = @($aEvents | Where-Object { $_.Evt -eq 'TICK_GAP' })
"tick gaps reported: {0}" -f $tg.Count
$unavailable = @($events | Where-Object { $_.Evt -eq 'SUBSCRIBE' -and $_.Kv['result'] -eq 'fail' } | ForEach-Object { $_.Kv['event'] } | Sort-Object -Unique)
"event subscriptions that failed: " + $(if ($unavailable.Count -eq 0) { 'none' } else { $unavailable -join ', ' })

"== summary classes =="
if ($classes.Count -eq 0) { "(no Track B cycle classified)" } else { ($classes | Group-Object | ForEach-Object { $_.Name + ' x' + $_.Count }) -join ', ' }
