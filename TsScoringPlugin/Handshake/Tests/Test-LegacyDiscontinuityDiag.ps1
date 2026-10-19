# PHASE PID-D4 / LEGACY JUMP 2A-ALPHA - offline tests of the TEL_DISCONTINUITY structured diagnostic of the AtsEX LEGACY telemetry session (C17 evidence).
# One line per discontinuity that LegacyTelemetrySession already counts (the judgement, the 300 ms threshold and the counter are unchanged), at most 64 lines per process, then one
# TEL_DISCONTINUITY_LIMIT line; never per Tick. 14 keys, fixed order, no empty value, invariant culture, F3 decimals. There is NO hb key (heartbeatStatus depends on the SI-0 order
# recorder; it would make the line differ with and without the observation: Test-ScoringObservationSI0.ps1 A02).
# No BVE, no AtsEX runtime, no network. The built DLL (-DllPath, default Telemetry\Legacy\out) is copied to a temp folder and driven through the FAKES of
# tests\TelemetryTestFixture.cs (compiled here, unchanged). Nothing is written to the repository; the temp folder is removed at the end. ASCII-only on purpose. Windows PowerShell 5.1.
#   -Mode All  : every check (default)        -Mode Dump : internal, writes a dump of one scripted run for the differential check against -ReferenceDll
#   -ReferenceDll : path of the S5-A reference DLL for the differential check PD-20 (its SHA-256 must equal -ReferenceSha256). There is no default and no search: when it is
#   not given, PD-20 is reported as SKIP (not counted as a pass) and the other checks run unchanged.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$DllPath = '',
    [string]$ReferenceDll = '',            # optional: the S5-A reference DLL (pinned by -ReferenceSha256); not given = PD-20 is reported as SKIP
    [string]$ReferenceSha256 = '3943DF3F42ACB16F39AC9005FAC0B3E4151EAF4A28FCFEA2F6635C110A974D23',
    [string]$BaselineCommit = '87cf543',
    [string]$BaselineSessionFile = '',     # optional: a byte copy of the baseline Session (for a copy of the tree outside the repository); default = git show of -BaselineCommit
    [ValidateSet('All', 'Dump')][string]$Mode = 'All',
    [string]$OutFile = ''
)
$ErrorActionPreference = 'Stop'
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if ([string]::IsNullOrEmpty($DllPath)) { $DllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll' }
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$srcDir = Join-Path $Root 'Telemetry\Legacy\src'
$testDir = Join-Path $env:TEMP ('tsscoring-discdiag-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, $ok) { $okb = ($ok -is [bool]) -and $ok; $results.Add([pscustomobject]@{ Name = $name; Ok = $okb }); ("{0} {1}" -f $(if ($okb) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }

try {
    $dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
    Copy-Item $DllPath $dllCopy
    $fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
    Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixtureSrc)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
    Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class DiscDiagResolver
{
    public static void Install(string[] dirs)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string name = e.Name.Split(',')[0];
            foreach (string dir in dirs)
            {
                string p = Path.Combine(dir, name + ".dll");
                if (File.Exists(p)) { return Assembly.LoadFrom(p); }
            }
            return null;
        };
    }
}
"@
    [DiscDiagResolver]::Install(@($testDir, $legacyHost))
    $telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
    $fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)

    $NS = 'TsScoringLegacyTelemetryTests'
    function NewH([bool]$withInput, [bool]$withDiag, [bool]$withScoring) { return (New-Object "$NS.Harness" -ArgumentList @($withInput, $withDiag, $withScoring)) }
    function NewP { return (NewH $true $true $true) }          # as the product wires it: input surface + diagnostic + SI-0 order recorder
    function NewN { return (NewH $true $true $false) }         # no SI-0 order recorder
    function Named($h, [string]$name) { return ,@($h.Diag.Events | Where-Object { $_ -eq $name -or $_.StartsWith($name + ' ') }) }
    function Disc($h) { return ,@($h.Diag.Events | Where-Object { $_.StartsWith('TEL_DISCONTINUITY ') }) }
    function Lim($h) { return ,@($h.Diag.Events | Where-Object { $_.StartsWith('TEL_DISCONTINUITY_LIMIT ') }) }
    function Kv([string]$line, [string]$key) { $m = [regex]::Match($line, '(^| )' + [regex]::Escape($key) + '=([^ ]*)'); if ($m.Success) { return $m.Groups[2].Value } else { return $null } }
    function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
    $script:jumps = 0
    function Jump($h, [int]$ms = 60000) { $h.Api.TimeMs += $ms; $h.Run(1, 16); $script:jumps++ }          # one BVE time jump in one Tick: one discontinuity is expected
    $KEYS = @('n', 'epoch', 'scenarioId', 'epochLines', 'epochReason', 'mono', 'prevMono', 'wallGapMs', 'bveMs', 'prevBveMs', 'bveDeltaMs', 'elapsedMs', 'residualMs', 'skippedSince')
    $SHAPE = '^TEL_DISCONTINUITY n=\d+ epoch=\d+ scenarioId=\d+ epochLines=\d+ epochReason=[a-z]+(-[a-z]+)* mono=\d+ prevMono=\d+ wallGapMs=\d+ bveMs=-?\d+ prevBveMs=-?\d+ bveDeltaMs=-?\d+ elapsedMs=-?\d+\.\d{3} residualMs=-?\d+\.\d{3} skippedSince=\d+$'
    $LIMSHAPE = '^TEL_DISCONTINUITY_LIMIT emitted=64 totalAtLimit=65 epoch=\d+ scenarioId=\d+ mono=\d+$'
    $REASONS = @('first-tick', 'scenario-opened-reload', 'scenario-opened', 'scenario-closed', 'scenario-created', 'identity-changed', 'not-created', 'scenario-unreadable')
    function Keys([string]$line) { return ,@([regex]::Matches($line, '(?<![^\s])([A-Za-z0-9_]+)=') | ForEach-Object { $_.Groups[1].Value }) }

    # the scripted run of the SI-0 A02 test (2 generations, a reload, a pause, a time jump); used for the observation on / off comparison and for the differential dump
    function Scripted($hh) {
        $hh.Api.GradientRatio = 0.0125; $hh.Api.BrakeKind = 3; $hh.Api.FreshWrapperEachCall = $true
        $hh.Opened($false); $hh.Created()
        $hh.Run(30, 16); [void]$hh.Heartbeat()
        $hh.Api.GradientRatio = 0.02; $hh.Api.Holding = $true; $hh.Api.GroundMps = 16.6
        $hh.Run(30, 16)
        $hh.Now += 3000; [void]$hh.Heartbeat(); $hh.Run(5, 16); [void]$hh.Heartbeat()
        $hh.Api.TimeMs += 60000; $hh.Run(5, 16)
        $hh.Closed(); $hh.Created(); $hh.Seed += 777; $hh.Run(20, 16); [void]$hh.Heartbeat()
        $hh.Api.TimeMs += 90000; $hh.Run(3, 16)
        $hh.Dispose(); [void]$hh.Heartbeat()
    }

    if ($Mode -eq 'Dump') {
        $d = NewP; Scripted $d
        $o = New-Object System.Collections.Generic.List[string]
        foreach ($s in $d.Sink.Sent) { $o.Add('SENT|' + $s) }
        foreach ($e in $d.Diag.Events) { $o.Add('DIAG|' + $e) }
        $o.Add('CNT|epochs=' + $d.Epochs + ' lines=' + $d.LinesSent + ' skipped=' + $d.LinesSkipped + ' disc=' + $d.Discontinuities)
        [IO.File]::WriteAllLines($OutFile, $o.ToArray(), (New-Object Text.UTF8Encoding($false)))
        $script:dumpDone = $true
    }

    if (-not $script:dumpDone) {
    Write-Host ('DISCDIAG dll=' + $DllPath + ' version=' + $fixAsm.GetType($NS + '.DiagInfo').GetProperty('Version').GetValue($null, $null))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # A - zero, one, several; the line itself
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $script:jumps = 0
    $h = NewP; $h.Run(100, 16)
    Check 'PD-01 no discontinuity in a steady run of 100 Ticks: no TEL_DISCONTINUITY line, no LIMIT line, Discontinuities = 0' (((Disc $h).Count -eq 0) -and ((Lim $h).Count -eq 0) -and ($h.Discontinuities -eq 0))

    $script:jumps = 0
    $h = NewP; $h.Run(10, 16); $idE1 = $h.ScenarioId; $beforeNow = $h.Now; $beforeTime = $h.Api.TimeMs; Jump $h; $dl = (Disc $h); $l = $dl[0]
    Check 'PD-02a one jump: exactly the number of jumps made (counted from the calls) lines, Discontinuities equal to it' (($dl.Count -eq $script:jumps) -and ($h.Discontinuities -eq $script:jumps) -and ($script:jumps -eq 1))
    Check 'PD-02b the line has exactly the 14 keys in the fixed order and no hb key' ((((Keys $l) -join ',') -ceq ($KEYS -join ',')) -and ($l -cnotmatch 'hb='))
    Check 'PD-02c the line matches the strict shape (no empty value, integers plain, decimals F3 with a dot)' ($l -cmatch $SHAPE)
    Check 'PD-02d n=1 epoch=1 scenarioId = the instance id, epochLines = the 10 lines sent before, epochReason=first-tick' (((Kv $l 'n') -ceq '1') -and ((Kv $l 'epoch') -ceq '1') -and ((Kv $l 'scenarioId') -ceq [string]$idE1) -and ((Kv $l 'epochLines') -ceq '10') -and ((Kv $l 'epochReason') -ceq 'first-tick'))
    $expBve = $h.Api.TimeMs
    Check 'PD-02e bveMs / prevBveMs / bveDeltaMs are the BVE time of this and of the previous sample and their difference' (([int](Kv $l 'bveMs') -eq $expBve) -and ([int](Kv $l 'prevBveMs') -eq $beforeTime) -and ([int](Kv $l 'bveDeltaMs') -eq ($expBve - $beforeTime)))
    Check 'PD-02f mono = the monotonic clock of this Tick, prevMono = that of the previous sample, wallGapMs = their difference (16)' (([long](Kv $l 'mono') -eq $h.Now) -and ([long](Kv $l 'prevMono') -eq $beforeNow) -and ([long](Kv $l 'wallGapMs') -eq 16))
    Check 'PD-02g elapsedMs = 16.000 and residualMs = bveDeltaMs - elapsedMs = 60000.000 (F3, dot)' (((Kv $l 'elapsedMs') -ceq '16.000') -and ((Kv $l 'residualMs') -ceq '60000.000'))
    Check 'PD-02h skippedSince = 0 for a run without a skipped Tick' ((Kv $l 'skippedSince') -ceq '0')

    $script:jumps = 0
    $h = NewP; $h.Run(10, 16); Jump $h; $h.Run(5, 16); Jump $h; $h.Run(5, 16); Jump $h; $dl = (Disc $h)
    Check 'PD-03a several jumps: one line each (count from the calls), n = 1,2,3 strictly increasing, Discontinuities = 3' (($dl.Count -eq $script:jumps) -and ($script:jumps -eq 3) -and (((@($dl | ForEach-Object { Kv $_ 'n' })) -join ',') -ceq '1,2,3') -and ($h.Discontinuities -eq 3))
    $h.Dispose(); $disp = (Named $h 'TEL_DISPOSE')
    Check 'PD-03b TEL_DISPOSE keeps its total: discontinuities=3 equals the number of lines and the last n, and its prefix is unchanged' (($disp.Count -eq 1) -and ($disp[0] -cmatch '^TEL_DISPOSE epochs=1 lines=\d+ skipped=0 discontinuities=3$') -and ((Kv $dl[2] 'n') -ceq '3'))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # B - the judgement is unchanged: 300 ms
    # ------------------------------------------------------------------------------------------------------------------------------------------
    function Edge([int]$deltaMs, [int]$elapsedMs) { $e = NewP; $e.Run(5, 16); $e.Now += $deltaMs; $e.Api.TimeMs += $deltaMs; $e.Tick([double]$elapsedMs); return $e }
    $e299 = Edge 16 315; $e300 = Edge 16 316; $e301 = Edge 16 317; $p300 = Edge 316 16; $p301 = Edge 317 16
    Check 'PD-04a |delta - elapsed| = 299 ms is not a discontinuity (no counter, no line)' (($e299.Discontinuities -eq 0) -and ((Disc $e299).Count -eq 0))
    Check 'PD-04b exactly 300 ms (negative side) is not a discontinuity' (($e300.Discontinuities -eq 0) -and ((Disc $e300).Count -eq 0))
    Check 'PD-04c 301 ms (negative side) is a discontinuity: one line, residualMs=-301.000, bveDeltaMs=16, elapsedMs=317.000' (($e301.Discontinuities -eq 1) -and ((Disc $e301).Count -eq 1) -and ((Kv (Disc $e301)[0] 'residualMs') -ceq '-301.000') -and ((Kv (Disc $e301)[0] 'elapsedMs') -ceq '317.000') -and ((Kv (Disc $e301)[0] 'bveDeltaMs') -ceq '16'))
    Check 'PD-04d exactly 300 ms (positive side) is not a discontinuity, 301 ms is (residualMs=301.000)' (($p300.Discontinuities -eq 0) -and ($p301.Discontinuities -eq 1) -and ((Kv (Disc $p301)[0] 'residualMs') -ceq '301.000'))
    $rw = NewP; $rw.Run(5, 16); $rw.Now += 16; $rw.Api.TimeMs -= 50000; $rw.Tick(16.0)
    Check 'PD-04e a rewind is a discontinuity: bveDeltaMs negative, residualMs negative, a plain minus sign' (((Disc $rw).Count -eq 1) -and ([int](Kv (Disc $rw)[0] 'bveDeltaMs') -lt 0) -and ((Kv (Disc $rw)[0] 'residualMs') -cmatch '^-\d+\.\d{3}$'))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # C - generation (epoch) boundary, initialization gap, reload, pause, selection screen, shutdown
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $h = NewP; $h.Api.FreshWrapperEachCall = $true; $h.Run(10, 16); $id1 = $h.ScenarioId; $h.Closed(); $h.Opened($false); $h.Created(); $h.Seed += 777
    $h.Api.TimeMs += 60000; $h.Run(1, 16)
    Check 'PD-05a initialization gap: the first sample of a new epoch is never counted, even when BVE time moved between the epochs (no line, no count)' (($h.Epochs -eq 2) -and ($h.Discontinuities -eq 0) -and ((Disc $h).Count -eq 0))
    $h.Run(3, 16); Jump $h; $l = (Disc $h)[0]
    Check 'PD-05b a jump inside epoch 2: epoch=2, scenarioId = the new instance (not epoch 1), epochReason=scenario-closed, epochLines = lines of epoch 2 only, n=1' (((Kv $l 'epoch') -ceq '2') -and ((Kv $l 'scenarioId') -ceq [string]$h.ScenarioId) -and ($h.ScenarioId -ne $id1) -and ((Kv $l 'epochReason') -ceq 'scenario-closed') -and ((Kv $l 'epochLines') -ceq '4') -and ((Kv $l 'n') -ceq '1'))
    $h = NewP; $h.Run(10, 16); Jump $h; $h.Closed(); $h.Opened($false); $h.Created(); $h.Seed += 777; $h.Run(5, 16); Jump $h; $dl = (Disc $h)
    Check 'PD-05c n continues across epochs (never reset): 1 then 2, with epoch 1 then 2' ((((@($dl | ForEach-Object { Kv $_ 'n' })) -join ',') -ceq '1,2') -and (((@($dl | ForEach-Object { Kv $_ 'epoch' })) -join ',') -ceq '1,2') -and ($h.Discontinuities -eq 2))
    $h = NewP; $h.Run(10, 16); $h.Opened($true); $h.Created(); $h.Seed += 777; $h.Run(5, 16); $nF5 = (Disc $h).Count; Jump $h; $l = (Disc $h)[0]
    Check 'PD-06 F5 (reload): the reload itself is not counted; a later jump in the new epoch says epochReason=scenario-opened-reload' (($nF5 -eq 0) -and ((Kv $l 'epochReason') -ceq 'scenario-opened-reload') -and ((Kv $l 'epoch') -ceq '2'))
    $h = NewP; $h.Run(10, 16); $h.Now += 5000; $hbp = $h.Heartbeat(); $h.Run(5, 16); $nP = (Disc $h).Count
    Check 'PD-07a a Pause (5 s without a Tick) and the resume with a normal BVE advance is not a discontinuity: no line' (($hbp -ceq 'STATUS:LOADED:PAUSED') -and ($nP -eq 0) -and ($h.Discontinuities -eq 0))
    $h = NewP; $h.Run(10, 16); $h.Now += 5000; Jump $h; $l = (Disc $h)[0]
    Check 'PD-07b a jump on the resume Tick is recorded with its own wall gap (wallGapMs = 5016) and no pause word is invented' (((Kv $l 'wallGapMs') -ceq '5016') -and ($l -cnotmatch 'hb=|pause|paused'))
    $h = NewP; $h.Run(10, 16); $h.Api.Created = $false; $h.Api.TimeMs += 60000; $h.Run(5, 16); $nSel = (Disc $h).Count; $h.Api.Created = $true; $h.Run(1, 16)
    Check 'PD-08 selection screen (scenario not created): Ticks end the epoch and write nothing; the first sample of the next epoch is not counted' (($nSel -eq 0) -and ((Disc $h).Count -eq 0) -and ($h.Discontinuities -eq 0))
    $h = NewP; $h.Run(10, 16); Jump $h; $h.Dispose(); $nBefore = $h.Diag.Events.Count; $h.Api.TimeMs += 60000; $h.Run(5, 16); $dispIdx = $h.Diag.Events.FindIndex([Predicate[string]] { param($x) $x.StartsWith('TEL_DISPOSE') })
    Check 'PD-09 after Dispose a Tick does nothing: no new diagnostic line at all, nothing after TEL_DISPOSE, the total stays 1' (($h.Diag.Events.Count -eq $nBefore) -and ($dispIdx -eq ($h.Diag.Events.Count - 1)) -and ($h.Discontinuities -eq 1))
    $h = NewP; $h.Run(10, 16); $h.Api.Fail.Add('TryTimeMs') | Out-Null; $h.Now += 16; $h.Tick(16.0); $h.Now += 16; $h.Tick(16.0); $h.Api.Fail.Remove('TryTimeMs') | Out-Null; Jump $h; $l = (Disc $h)[0]
    Check 'PD-10 skippedSince counts the Ticks skipped since the previous valid sample (2), not an earlier history' (((Kv $l 'skippedSince') -ceq '2') -and ($h.LinesSkipped -eq 2))
    $h = NewP; $h.Run(10, 16); $h.Api.Fail.Add('TryTimeMs') | Out-Null; $h.Now += 16; $h.Tick(16.0); $h.Api.Fail.Remove('TryTimeMs') | Out-Null; $h.Run(5, 16); Jump $h; $l = (Disc $h)[0]
    Check 'PD-10b a skip BEFORE an intact sample is not counted again: skippedSince=0 (LinesSkipped itself is 1)' (((Kv $l 'skippedSince') -ceq '0') -and ($h.LinesSkipped -eq 1) -and ($h.Discontinuities -eq 1))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # D - never per Tick; the limit of 64
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $h = NewP; $h.Run(10000, 16); $hBase = NewP; $hBase.Run(10000, 16)
    Check 'PD-11 10,000 normal Ticks: 0 TEL_DISCONTINUITY / LIMIT lines and the diagnostic is no longer than the first 100-Tick run plus nothing per Tick' (((Disc $h).Count -eq 0) -and ((Lim $h).Count -eq 0) -and ($h.Diag.Events.Count -eq $hBase.Diag.Events.Count) -and ($h.Diag.Events.Count -lt 400))
    function Storm([int]$count) { $s = NewP; $s.Run(5, 16); $script:jumps = 0; for ($i = 0; $i -lt $count; $i++) { Jump $s }; return $s }
    $s64 = Storm 64; $s65 = Storm 65; $s66 = Storm 66; $s100 = Storm 100; $dl = (Disc $s100); $ll = (Lim $s100)
    Check 'PD-12a 64 jumps: 64 lines and no LIMIT line, Discontinuities = 64' (((Disc $s64).Count -eq 64) -and ((Lim $s64).Count -eq 0) -and ($s64.Discontinuities -eq 64))
    Check 'PD-12b the 65th discontinuity writes the LIMIT line once and no 65th individual line' (((Disc $s65).Count -eq 64) -and ((Lim $s65).Count -eq 1) -and ($s65.Discontinuities -eq 65))
    Check 'PD-12c the 66th and later write nothing more: 66 jumps and 100 jumps both have 64 lines and exactly one LIMIT line' (((Disc $s66).Count -eq 64) -and ((Lim $s66).Count -eq 1) -and ($dl.Count -eq 64) -and ($ll.Count -eq 1))
    Check 'PD-12d the total stays the real number: Discontinuities = 66 and 100 (the number of jumps counted from the calls)' (($s66.Discontinuities -eq 66) -and ($s100.Discontinuities -eq 100) -and ($script:jumps -eq 100))
    Check 'PD-12e the LIMIT line is exactly emitted=64 totalAtLimit=65 epoch scenarioId mono, in the 14-key-compatible vocabulary, and stands after the 64th line' (($ll[0] -cmatch $LIMSHAPE) -and ((Kv $ll[0] 'epoch') -ceq '1') -and ((Kv $ll[0] 'scenarioId') -ceq [string]$s100.ScenarioId) -and ($s100.Diag.Events.IndexOf($ll[0]) -gt $s100.Diag.Events.IndexOf($dl[63])))
    Check 'PD-12f the 64 lines are n = 1..64 in order and every line has the strict shape' ((((@($dl | ForEach-Object { [int](Kv $_ 'n') })) -join ',') -ceq ((1..64) -join ',')) -and (@($dl | Where-Object { $_ -cnotmatch $SHAPE }).Count -eq 0))
    $s100.Dispose(); $disp = (Named $s100 'TEL_DISPOSE')
    Check 'PD-12g TEL_DISPOSE keeps the real total after the limit (discontinuities=100) and the log ends there' (($disp.Count -eq 1) -and ($disp[0] -cmatch 'discontinuities=100$') -and ($s100.Diag.Events[$s100.Diag.Events.Count - 1] -ceq $disp[0]))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # E - the line is a fact: consistency, domain, culture, throwing diagnostic, no diagnostic
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $h = NewP; $h.Run(10, 16); Jump $h; $h.Run(5, 16); $h.Now += 400; $h.Api.TimeMs += 16; $h.Tick(400.0); $h.Api.TimeMs -= 40000; $h.Run(1, 16); $dl = (Disc $h); $okc = $true; $okd = $true
    foreach ($x in $dl) {
        if (([long](Kv $x 'mono') - [long](Kv $x 'prevMono')) -ne [long](Kv $x 'wallGapMs')) { $okc = $false }
        if (([long](Kv $x 'bveMs') - [long](Kv $x 'prevBveMs')) -ne [long](Kv $x 'bveDeltaMs')) { $okc = $false }
        $res = [double]::Parse((Kv $x 'residualMs'), [Globalization.CultureInfo]::InvariantCulture); $el = [double]::Parse((Kv $x 'elapsedMs'), [Globalization.CultureInfo]::InvariantCulture)
        if ([math]::Abs(([double](Kv $x 'bveDeltaMs') - $el) - $res) -gt 0.0015) { $okc = $false }
        if ([math]::Abs($res) -le 300.0) { $okc = $false }
        if ($REASONS -notcontains (Kv $x 'epochReason')) { $okd = $false }
        if ($x -cnotmatch $SHAPE) { $okd = $false }
    }
    Check 'PD-13a every line is self-consistent: wallGapMs = mono - prevMono, bveDeltaMs = bveMs - prevBveMs, residualMs = bveDeltaMs - elapsedMs, |residualMs| > 300 (3 lines of different kinds)' (($dl.Count -eq 3) -and $okc)
    Check 'PD-13b every line has the strict shape and a fixed-word epochReason; no key other than the 14 appears' (($dl.Count -eq 3) -and $okd -and (@($dl | Where-Object { ((Keys $_.Substring('TEL_DISCONTINUITY '.Length)) -join ',') -cne ($KEYS -join ',') }).Count -eq 0))
    $inv = $null; $cult = New-Object System.Collections.Generic.List[string]
    $saved = [Threading.Thread]::CurrentThread.CurrentCulture
    try {
        foreach ($cn in @('en-US', 'de-DE', 'fr-FR', 'ar-SA', 'tr-TR')) {
            [Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo($cn)
            $c = NewP; $c.Run(10, 16); $c.Now += 400; $c.Api.TimeMs += 16; $c.Tick(400.0); Jump $c
            $cult.Add(((Disc $c) -join "`n") + "`n" + ((Lim $c) -join "`n"))
        }
    } finally { [Threading.Thread]::CurrentThread.CurrentCulture = $saved }
    Check 'PD-14 culture independent: en-US, de-DE, fr-FR, ar-SA and tr-TR runs give byte-identical lines (decimal point is a dot, no digit substitution)' ((@($cult | Select-Object -Unique).Count -eq 1) -and ($cult[0] -cmatch 'elapsedMs=\d+\.\d{3}') -and ($cult.Count -eq 5))
    $h = NewP; $h.Diag.Throw = $true; $h.Run(10, 16); Jump $h; $h.Run(5, 16); Jump $h; $h.Dispose()
    $hRef = NewP; $hRef.Run(10, 16); Jump $hRef; $hRef.Run(5, 16); Jump $hRef; $hRef.Dispose()
    Check 'PD-15 a diagnostic that throws changes nothing: counter, lines sent and skipped, and the datagrams equal a session with a working diagnostic' (($h.Discontinuities -eq 2) -and ($h.LinesSkipped -eq 0) -and ($h.LinesSent -eq $hRef.LinesSent) -and (($h.Sink.Sent -join "`n") -ceq ($hRef.Sink.Sent -join "`n")))
    $hn = New-Object "$NS.Harness" -ArgumentList @($true, $false); $hn.Run(10, 16); Jump $hn; $hn.Run(5, 16); Jump $hn; $hn.Dispose()
    Check 'PD-16 without any diagnostic wired: no exception, the counter and the datagrams are the same as with one' (($hn.Discontinuities -eq 2) -and ($hn.LinesSent -eq $hRef.LinesSent) -and (($hn.Sink.Sent -join "`n") -ceq ($hRef.Sink.Sent -join "`n")))
    $hdup = NewP; $hdup.Run(10, 16); Jump $hdup
    Check 'PD-17 one jump never writes two lines and counts once (no double counting)' (((Disc $hdup).Count -eq 1) -and ($hdup.Discontinuities -eq 1) -and (@($hdup.Diag.Events | Where-Object { $_ -like 'TEL_DISCONTINUITY*' }).Count -eq 1))
    $hEnd = NewP; $hEnd.Run(5, 16); Jump $hEnd; $hEnd.Closed(); $hEnd.Dispose()
    $ii = $hEnd.Diag.Events.FindIndex([Predicate[string]] { param($x) $x.StartsWith('TEL_DISCONTINUITY ') }); $ie = $hEnd.Diag.Events.FindIndex([Predicate[string]] { param($x) $x.StartsWith('TEL_EPOCH_END') }); $ib = $hEnd.Diag.Events.FindIndex([Predicate[string]] { param($x) $x.StartsWith('TEL_EPOCH_BEGIN') })
    Check 'PD-18 order near the end: TEL_EPOCH_BEGIN, then the TEL_DISCONTINUITY line, then TEL_EPOCH_END, then TEL_DISPOSE (nothing is written for the normal end of the series)' (($ib -ge 0) -and ($ib -lt $ii) -and ($ii -lt $ie) -and ((Disc $hEnd).Count -eq 1))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # F - A02: the observation (SI-0 order recorder) does not change the TEL_DISCONTINUITY lines
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $wn = NewN; Scripted $wn
    $wp = NewP; Scripted $wp
    $dn = (Disc $wn); $dp = (Disc $wp)
    Check 'PD-19a the scripted run (reload, pause, jump, new generation, a second jump) counts the same with and without the order recorder, and has lines' (($wn.Discontinuities -eq $wp.Discontinuities) -and ($wp.Discontinuities -ge 2) -and ($dn.Count -eq $wn.Discontinuities) -and ($dp.Count -eq $wp.Discontinuities))
    Check 'PD-19b the TEL_DISCONTINUITY lines are byte-identical with and without the SI-0 order recorder' (($dn.Count -ge 2) -and (($dn -join "`n") -ceq ($dp -join "`n")))
    Check 'PD-19c A02 reproduced: every diagnostic line that is not an SI0 line is identical with and without the observation' ((@($wn.Diag.Events | Where-Object { $_ -notlike 'SI0_*' }) -join "`n") -ceq (@($wp.Diag.Events | Where-Object { $_ -notlike 'SI0_*' }) -join "`n"))
    Check 'PD-19d only the SI0 lines depend on the observation: none without the order recorder, some with it' ((@($wn.Diag.Events | Where-Object { $_ -like 'SI0_*' }).Count -eq 0) -and (@($wp.Diag.Events | Where-Object { $_ -like 'SI0_*' }).Count -gt 10))
    Check 'PD-19e the datagrams are byte-identical with and without the order recorder' (($wn.Sink.Sent -join "`n") -ceq ($wp.Sink.Sent -join "`n"))

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # G - differential against the S5-A DLL (no diagnostic): the telemetry and every other line are exactly what they were
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $refOk = $false
    if ((-not [string]::IsNullOrEmpty($ReferenceDll)) -and (Test-Path $ReferenceDll) -and ((Get-FileHash $ReferenceDll -Algorithm SHA256).Hash -eq $ReferenceSha256.ToUpper()) -and ((Get-FileHash $DllPath -Algorithm SHA256).Hash -ne $ReferenceSha256.ToUpper())) { $refOk = $true }
    if (-not $refOk) { Write-Host (Skip 'PD-20 differential against the S5-A DLL: the reference DLL was not given (-ReferenceDll), is missing, differs from its pin, or the DLL under test IS the reference') }
    else {
        $refDump = Join-Path $testDir 'ref.dump'; $newDump = Join-Path $testDir 'new.dump'
        $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        & $psExe -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Mode Dump -DllPath $ReferenceDll -OutFile $refDump -Root $Root | Out-Null
        & $psExe -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Mode Dump -DllPath $DllPath -OutFile $newDump -Root $Root | Out-Null
        $rd = @([IO.File]::ReadAllLines($refDump)); $nd = @([IO.File]::ReadAllLines($newDump))
        $rdSent = @($rd | Where-Object { $_.StartsWith('SENT|') }); $ndSent = @($nd | Where-Object { $_.StartsWith('SENT|') })
        $rdOther = @($rd | Where-Object { $_.StartsWith('DIAG|') } | ForEach-Object { ($_ -replace ' th=\d+ ', ' th=N ') -replace 'scanMs=[0-9.]+', 'scanMs=N' }); $ndOther = @($nd | Where-Object { $_.StartsWith('DIAG|') -and (-not $_.StartsWith('DIAG|TEL_DISCONTINUITY')) } | ForEach-Object { ($_ -replace ' th=\d+ ', ' th=N ') -replace 'scanMs=[0-9.]+', 'scanMs=N' })
        $rdCnt = @($rd | Where-Object { $_.StartsWith('CNT|') }); $ndCnt = @($nd | Where-Object { $_.StartsWith('CNT|') })
        $ndDisc = @($nd | Where-Object { $_.StartsWith('DIAG|TEL_DISCONTINUITY ') })
        Check 'PD-20a differential: the datagrams of the scripted run are byte-identical to the S5-A DLL (and not empty)' (($rdSent.Count -gt 80) -and (($rdSent -join "`n") -ceq ($ndSent -join "`n")))
        Check 'PD-20b differential: every diagnostic line except TEL_DISCONTINUITY* is identical to the S5-A DLL, in the same order' (($rdOther.Count -gt 20) -and (($rdOther -join "`n") -ceq ($ndOther -join "`n")))
        Check 'PD-20c differential: epochs, lines, skipped and the discontinuity total equal the S5-A DLL, and the new DLL wrote one line per counted discontinuity' (($rdCnt.Count -eq 1) -and ($rdCnt[0] -ceq $ndCnt[0]) -and ($ndDisc.Count -eq [int]([regex]::Match($rdCnt[0], 'disc=(\d+)').Groups[1].Value)) -and ($ndDisc.Count -ge 2))
    }

    # ------------------------------------------------------------------------------------------------------------------------------------------
    # H - source audit (comments excluded): the counter, the threshold, the judgement and TEL_DISPOSE are the ones of the baseline; the change is diagnostic only
    # ------------------------------------------------------------------------------------------------------------------------------------------
    $sesPath = Join-Path $srcDir 'LegacyTelemetrySession.cs'
    $sesRaw = [IO.File]::ReadAllText($sesPath); $ses = Code $sesRaw
    Check 'PD-21a the counter is still incremented in exactly ONE place and nowhere else assigned (no reset, no second increment, no +=)' (([regex]::Matches($ses, 'Discontinuities\+\+')).Count -eq 1 -and ([regex]::Matches($ses, 'Discontinuities\s*(\+=|-=|=[^=>])')).Count -eq 0 -and ([regex]::Matches($ses, 'Discontinuities\s*--')).Count -eq 0)
    Check 'PD-21b the property and its initial value are unchanged (internal int Discontinuities { get; private set; }, no initializer)' ($ses -match 'internal int Discontinuities \{ get; private set; \}')
    Check 'PD-21c the threshold is still 300.0 ms and the judgement expression is the baseline one' (($ses -match 'private const double JumpToleranceMs = 300\.0;') -and ($ses -match 'bool discontinuity = lastTimeMs != 0 && Math\.Abs\(timeMs - lastTimeMs - elapsed\.TotalMilliseconds\) > JumpToleranceMs;'))
    Check 'PD-21d the counted branch is exactly: increment, timeline mark, haveLastSample = false, then the one diagnostic call' ($ses -match 'if \(discontinuity\)\s*\{\s*Discontinuities\+\+;\s*timeline\.MarkDiscontinuity\(\);\s*haveLastSample = false;\s*LogDiscontinuity\(sampleMono, timeMs, elapsed\);\s*\}')
    Check 'PD-21e TEL_DISPOSE is written exactly as before (epochs lines skipped discontinuities), once' (($ses -match 'Log\("TEL_DISPOSE", "epochs=" \+ Epochs \+ " lines=" \+ LinesSent \+ " skipped=" \+ LinesSkipped \+ " discontinuities=" \+ Discontinuities\);') -and ([regex]::Matches($ses, '"TEL_DISPOSE"')).Count -eq 1)
    $mStart = $ses.IndexOf('private void LogDiscontinuity('); $mEnd = $ses.IndexOf('private void ObserveScoring(')
    $mBody = if (($mStart -ge 0) -and ($mEnd -gt $mStart)) { $ses.Substring($mStart, $mEnd - $mStart) } else { '' }
    Check 'PD-21f the diagnostic method reads no heartbeat state and has no hb key (the field was removed by the owner decision)' (($mBody.Length -gt 200) -and ($mBody -cnotmatch 'heartbeatStatus|hb=|PausedAfterMs|order\b') -and ($sesRaw -cnotmatch '" hb="'))
    Check 'PD-21g the diagnostic has no lock, thread, timer, task, volatile or Interlocked of its own and names no host type (host independent, no jump / 54322 / hook vocabulary)' (($mBody -cnotmatch 'lock \(|new Thread|Timer|Task|volatile|Interlocked|ThreadPool') -and ($ses -cnotmatch 'AtsEx|BveTypes|BveEx') -and ($ses -cnotmatch '54322|JUMP_|"MAPLIMITS"|"CLEARDIST"|"TRAINLEN"') -and ($ses -cnotmatch '(?i)"jump"'))
    $hbA = $sesRaw.IndexOf('internal string ComposeHeartbeat'); $hbB = $sesRaw.IndexOf('internal void OnTick'); $mAt = $sesRaw.IndexOf('private void LogDiscontinuity(')
    Check 'PD-21h the new method lies outside the ComposeHeartbeat .. OnTick region that the SI-0 test slices' (($hbA -ge 0) -and ($hbB -gt $hbA) -and ($mAt -gt $hbB))
    # the diff against the baseline commit: only additions, and only the allowed ones
    $top = ''
    try { $prevEap0 = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; $top = ((& git -C $Root rev-parse --show-toplevel 2>$null) -join '').Trim() -replace '/', '\'; $ErrorActionPreference = $prevEap0 } catch { $top = '' }
    if (($top -eq '') -and [string]::IsNullOrEmpty($BaselineSessionFile)) { Write-Host (Skip 'PD-22 the Session diff against the baseline commit (git not available)') }
    else {
        $rel = 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs'
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        if ([string]::IsNullOrEmpty($BaselineSessionFile)) { $diff = @(& git -C $top -c core.autocrlf=false -c core.safecrlf=false diff -U0 --no-color $BaselineCommit -- $rel 2>$null) }
        else { $diff = @(& git -c core.autocrlf=false -c core.safecrlf=false diff --no-index -U0 --no-color $BaselineSessionFile $sesPath 2>$null) }
        $ErrorActionPreference = $prevEap
        $plus = New-Object System.Collections.Generic.List[object]; $minus = 0; $newLn = 0
        foreach ($d in $diff) {
            if ($d -match '^@@ -\d+(,\d+)? \+(\d+)(,\d+)? @@') { $newLn = [int]$Matches[2]; continue }
            if ($d -match '^\+\+\+|^---') { continue }
            if ($d.StartsWith('+')) { $plus.Add([pscustomobject]@{ N = $newLn; T = $d.Substring(1) }); $newLn++ }
            elseif ($d.StartsWith('-')) { $minus++ }
        }
        $allLines = $sesRaw -split "`n"
        $docStart = -1; for ($i = 0; $i -lt $allLines.Count; $i++) { if ($allLines[$i] -match 'private void LogDiscontinuity\(') { $docStart = $i; break } }
        $mFirst = $docStart; while (($mFirst -gt 0) -and ($allLines[$mFirst - 1] -match '^\s*///')) { $mFirst-- }
        $mLast = $docStart; $depth = 0; $seen = $false
        for ($i = $docStart; $i -lt $allLines.Count; $i++) { foreach ($ch in $allLines[$i].ToCharArray()) { if ($ch -eq '{') { $depth++; $seen = $true } elseif ($ch -eq '}') { $depth-- } }; if ($seen -and $depth -eq 0) { $mLast = $i; break } }
        $mFirst1 = $mFirst + 1; $mLast1 = $mLast + 2     # 1-based, plus the blank line after the method
        $outside = @($plus | Where-Object { $_.N -lt $mFirst1 -or $_.N -gt $mLast1 })
        $allowed = @(
            '^\s*private const int MaxDiscontinuityLines = 64;\s*$',
            '^\s*private long lastSampleMonoMs;',
            '^\s*private int skippedAtLastSample;',
            '^\s*private string epochBeginReason = "first-tick";',
            '^\s*private int discLogged;',
            '^\s*private bool discLimitNoted;',
            '^\s*epochBeginReason = reason;\s*$',
            '^\s*long sampleMono = nowMs\(\);\s*$',
            '^\s*LogDiscontinuity\(sampleMono, timeMs, elapsed\);\s*$',
            '^\s*lastSampleMonoMs = sampleMono;\s*$',
            '^\s*skippedAtLastSample = LinesSkipped;\s*$'
        )
        $unmatched = @($outside | Where-Object { $t = $_.T; (@($allowed | Where-Object { $t -cmatch $_ }).Count -eq 0) })
        $eachOnce = $true; foreach ($a in $allowed) { if (@($outside | Where-Object { $_.T -cmatch $a }).Count -ne 1) { $eachOnce = $false } }
        Check ('PD-22a the Session differs from the baseline commit by ADDED lines only (removed lines = ' + $minus + ')') (($minus -eq 0) -and ($plus.Count -gt 0))
        Check ('PD-22b every added line outside the new method is one of the 11 allowed diagnostic lines, each exactly once (outside lines = ' + $outside.Count + ', not allowed = ' + $unmatched.Count + ')') (($unmatched.Count -eq 0) -and ($outside.Count -eq 11) -and $eachOnce)
        Check 'PD-22c the added lines inside the new method are only the method (its comment, body and one blank line)' (($plus.Count - $outside.Count) -gt 20 -and (($plus.Count - $outside.Count) -le ($mLast1 - $mFirst1 + 1)))
    }
    }      # end of the Mode All checks
}
finally {
    Remove-Item $testDir -Recurse -Force -ErrorAction SilentlyContinue
    # the copied DLL and the fixture are loaded into THIS process and stay locked until it exits: a detached helper removes the folder a moment after the exit (nothing is left behind)
    if (Test-Path -LiteralPath $testDir) { try { Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\cmd.exe') -ArgumentList @('/c', ('ping -n 4 127.0.0.1 >nul & rmdir /s /q "' + $testDir + '"')) -WindowStyle Hidden } catch { } }
}
if ($script:dumpDone) { exit 0 }

$bad = @($results | Where-Object { -not $_.Ok })
Write-Host ''
Write-Host ('DISCDIAG RESULT pass=' + @($results | Where-Object { $_.Ok }).Count + ' fail=' + $bad.Count + ' skip=' + $script:skips)
if ($bad.Count -gt 0) { exit 1 }
exit 0
