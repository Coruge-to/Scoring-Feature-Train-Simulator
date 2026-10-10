# PHASE SI-0 - offline tests of the AtsEX LEGACY scoring-integration OBSERVATION (read only, diagnostic log only): bp_initial (O-A), vehicle length candidates (O-B), the ground
# speed limit list and the head / tail question (O-C), the order of events / first Tick / heartbeat / first line (O-D), and the proof that the telemetry stream, AVAIL and the heartbeat
# of the earlier phases are unchanged. The jump methods of the host (O-E) are NOT called anywhere; this test audits their metadata and the sources for the absence of any call.
# No BVE, no AtsEX runtime, no BveEx, no network, no hooks. The real built DLL is loaded from a copy and driven through FAKES of the Legacy API (tests\TelemetryTestFixture.cs, compiled here).
# Nothing is written outside logs\si0-tests. This script is ASCII-only on purpose (the Japanese words are built from code points).
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$srcDir = Join-Path $Root 'Telemetry\Legacy\src'
$testDir = Join-Path $Root 'logs\si0-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }

$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixtureSrc)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class Si0Resolver
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
[Si0Resolver]::Install(@($testDir, $legacyHost))
$telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
$fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)

$NS = 'TsScoringLegacyTelemetryTests'
function NewH([bool]$withInput, [bool]$withDiag, [bool]$withScoring) { return (New-Object "$NS.Harness" -ArgumentList @($withInput, $withDiag, $withScoring)) }
function NewS { return (NewH $true $true $true) }                      # input surface + diagnostic + scoring observation
function Lim($h, [double]$loc, [double]$kmh) { $mps = $kmh / 3.6; $h.Scoring.Limits.Add((New-Object "$NS.FakeLimit" -ArgumentList @($loc, $mps))) }
function Si0($h) { return ,@($h.Diag.Events | Where-Object { $_ -like 'SI0_*' }) }
function Named($h, [string]$name) { return ,@($h.Diag.Events | Where-Object { $_ -eq $name -or $_.StartsWith($name + ' ') }) }
function Orders($h) { return ,@($h.Diag.Events | Where-Object { $_.StartsWith('SI0_ORDER ') }) }
function Kv([string]$line, [string]$key) { $m = [regex]::Match($line, '(^| )' + [regex]::Escape($key) + '=([^ ]*)'); if ($m.Success) { return $m.Groups[2].Value } else { return $null } }
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
function Ev($h, [string]$word) { return ,@((Orders $h) | Where-Object { $_ -match (' ev=' + [regex]::Escape($word) + '( |$)') }) }
function Seq([string]$line) { return [int](Kv $line 'seq') }
$SHAPE = '^SI0_[A-Z_]+ gen=\d+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)+$'
$SHAPE_ORDER = '^SI0_ORDER seq=\d+ t=\d+ th=\d+ ev=[a-z\-]+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)*$'
function Probe($h) { return ,@($h.Diag.Events | Where-Object { ($_ -like 'SI0_*') -and (-not $_.StartsWith('SI0_ORDER ')) }) }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# A - the observation changes nothing that was there before
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Scripted($hh, $beats) {
    $hh.Api.GradientRatio = 0.0125; $hh.Api.BrakeKind = 3; $hh.Api.FreshWrapperEachCall = $true
    if ($hh.Scoring) { Lim $hh 0 100; Lim $hh 1000 60; Lim $hh 2000 100 }
    $hh.Opened($false); $hh.Created()
    $hh.Run(30, 16); $beats.Add([string]$hh.Heartbeat())
    $hh.Api.GradientRatio = 0.02; $hh.Api.Holding = $true; $hh.Api.GroundMps = 16.6
    $hh.Run(30, 16)
    $hh.Now += 3000; $beats.Add([string]$hh.Heartbeat()); $hh.Run(5, 16); $beats.Add([string]$hh.Heartbeat())      # a pause and a resume
    $hh.Api.TimeMs += 60000; $hh.Run(5, 16)                                                                          # a jump of the simulation time (a discontinuity)
    $hh.Closed(); $hh.Created(); $hh.Seed += 777; $hh.Run(20, 16); $beats.Add([string]$hh.Heartbeat()); $hh.Dispose(); $beats.Add([string]$hh.Heartbeat())
}
$bPlain = New-Object System.Collections.Generic.List[string]; $bScore = New-Object System.Collections.Generic.List[string]
$wp = NewH $true $true $false; Scripted $wp $bPlain
$ws = NewS; Scripted $ws $bScore
Check 'A01 the datagrams of a session WITH the scoring observation are byte-identical to one without it (same inputs: 2 generations, a reload, a pause, a time jump, the input surface wired)' (($wp.Sink.Sent.Count -gt 80) -and (($wp.Sink.Sent -join "`n") -ceq ($ws.Sink.Sent -join "`n")))
Check 'A02 every diagnostic line that is not an SI0 line is identical with and without the observation (the earlier phases write exactly what they wrote)' ((@($wp.Diag.Events | Where-Object { $_ -notlike 'SI0_*' }) -join "`n") -ceq (@($ws.Diag.Events | Where-Object { $_ -notlike 'SI0_*' }) -join "`n"))
Check 'A03 the heartbeat texts are identical with and without the observation (running / paused / after the dispose)' ((($bPlain -join '|') -ceq ($bScore -join '|')) -and ($bScore.Count -eq 5) -and ($bScore[1] -ceq 'STATUS:LOADED:PAUSED') -and ($bScore[0] -ceq 'STATUS:LOADED:RUNNING'))
$lines = @($ws.Sink.Lines())
Check 'A04 no SI0 word reaches the stream: AVAIL has no new token, and no BPINIT / VEHLEN / TRAINLEN / MAPLIMITS / CLEARDIST / JUMP key is ever written' ((@($ws.Sink.Sent | Where-Object { $_ -match 'TRAINLEN|MAPLIMITS|CLEARDIST|JUMP|BPINIT|VEHLEN|SI0' }).Count -eq 0) -and ([regex]::Match($lines[5], 'AVAIL:1:([^,]*)').Groups[1].Value -ceq 'bcp+bpp+brake_cab+brake_type+calcg+door+grad+handle+loc+maplimit+meta+prates+siglimit+siglimit_ahead+speed+station+time'))
$wo = New-Object "$NS.Harness" -ArgumentList @($true); $wo.Run(20, 16)
$wnd = NewH $true $false $true; $wnd.Run(20, 16)
Check 'A05 a session built without the scoring surface, or with it but without a diagnostic, writes no SI0 line at all' (((Si0 $wo).Count -eq 0) -and ((Si0 $wnd).Count -eq 0) -and ($wnd.Scoring.TotalCalls() -eq 0))
$wt = NewS; $wt.Scoring.BpThrow = $true; $wt.Scoring.VehThrow = $true; $wt.Scoring.LimitsThrow = $true; $wt.Run(100, 16)
$wc = NewH $true $true $false; $wc.Run(100, 16)
Check 'A06 every scoring read throwing: lines are still sent for every Tick (none skipped), the stream is the same as without the observation, and each group is reported unavailable once with read-exception' (($wt.LinesSent -eq 100) -and ($wt.LinesSkipped -eq 0) -and (($wt.Sink.Sent -join "`n") -ceq ($wc.Sink.Sent -join "`n")) -and ((Named $wt 'SI0_UNAVAILABLE').Count -eq 3) -and (@((Named $wt 'SI0_UNAVAILABLE') | Where-Object { $_ -match 'reason=read-exception$' }).Count -eq 3))
$wx = NewS; $wx.Diag.Throw = $true; $wx.Run(20, 16); $wx.Closed(); $wx.Dispose()
Check 'A07 a diagnostic that throws on every call cannot affect the telemetry: all 20 lines sent, none skipped' (($wx.LinesSent -eq 20) -and ($wx.LinesSkipped -eq 0))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# B - O-A: bp_initial (BpInitialPressure of a Smee / Cl, Pa -> kPa, never estimated)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewS; $h.Run(3, 16)
$b = Named $h 'SI0_BPINIT_FIRST'
Check 'B01 Smee 490000 Pa: one FIRST line with the raw Pa, the kPa (490), the method and status ok' (($b.Count -eq 1) -and ($b[0] -ceq 'SI0_BPINIT_FIRST gen=0 kind=Smee status=ok rawPa=490000 kPa=490 method=controller-smee smeeProp=490000 clProp=null bpNowKpa=490'))
$h = NewS; $h.Scoring.KindValue = 3; $h.Scoring.ControllerPa = 400000.0; $h.Scoring.SmeeProp = $false; $h.Scoring.SmeePa = $null; $h.Scoring.ClProp = $true; $h.Scoring.ClPa = 400000.0; $h.Run(3, 16)
Check 'B02 Cl 400000 Pa: kPa 400 by the Cl controller; the property route shows smeeProp=null and clProp=400000' ((Named $h 'SI0_BPINIT_FIRST')[0] -ceq 'SI0_BPINIT_FIRST gen=0 kind=Cl status=ok rawPa=400000 kPa=400 method=controller-cl smeeProp=null clProp=400000 bpNowKpa=490')
$h = NewS; $h.Scoring.KindValue = 1; $h.Scoring.ControllerPa = $null; $h.Scoring.ControllerReason = 'not-applicable'; $h.Scoring.SmeeProp = $false; $h.Scoring.SmeePa = $null; $h.Run(3, 16)
Check 'B03 Ecb: out of scope for bp_initial - status=not-applicable, method=none, no kPa, nothing invented' ((Named $h 'SI0_BPINIT_FIRST')[0] -ceq 'SI0_BPINIT_FIRST gen=0 kind=Ecb status=not-applicable rawPa=na kPa=na method=none smeeProp=null clProp=null bpNowKpa=490')
$h = NewS; $h.Scoring.KindValue = 1; $h.Scoring.ControllerPa = $null; $h.Scoring.SmeeProp = $true; $h.Scoring.SmeePa = 123456.0; $h.Run(3, 16)
Check 'B04 an Ecb vehicle whose Smee property route still answers is OBSERVED (smeeProp=123456) but the Ecb stays not-applicable: the property route is never trusted for the kind' (((Named $h 'SI0_BPINIT_FIRST')[0] -match 'kind=Ecb status=not-applicable rawPa=na kPa=na method=none smeeProp=123456 ') -and ((Named $h 'SI0_SUMMARY').Count -eq 0))
$h = NewS; $h.Scoring.ControllerPa = $null; $h.Scoring.ControllerReason = 'read-exception'; $h.Run(3, 16)
Check 'B05 a Smee whose value cannot be read: status=unreadable with the fixed reason, no kPa' ((Named $h 'SI0_BPINIT_FIRST')[0] -match 'kind=Smee status=unreadable reason=read-exception rawPa=na kPa=na method=controller-smee ')
$h = NewS; $h.Scoring.ControllerPa = [double]::NaN; $h.Run(3, 16)
Check 'B06 NaN is never written as a number: status=nonfinite rawPa=x kPa=na' ((Named $h 'SI0_BPINIT_FIRST')[0] -match 'status=nonfinite rawPa=x kPa=na ')
$h = NewS; $h.Scoring.ControllerPa = [double]::PositiveInfinity; $h.Scoring.SmeePa = [double]::NegativeInfinity; $h.Run(3, 16)
Check 'B07 Infinity: nonfinite, rawPa=x, and the property route shows x too' ((Named $h 'SI0_BPINIT_FIRST')[0] -match 'status=nonfinite rawPa=x kPa=na method=controller-smee smeeProp=x ')
$h = NewS; $h.Scoring.KindValue = 0; $h.Run(3, 16)
Check 'B08 an unknown brake kind: status=kind-unknown, method=none' ((Named $h 'SI0_BPINIT_FIRST')[0] -match 'kind=unknown status=kind-unknown ')
$tbl = @(@(0.0, '0'), @(1.0, '0.001'), @(101325.0, '101.325'), @(440000.0, '440'), @(490000.0, '490'), @(500000.5, '500.0005'))
$tblOk = $true
foreach ($t in $tbl) { $x = NewS; $x.Scoring.ControllerPa = $t[0]; $x.Run(2, 16); if ((Kv (Named $x 'SI0_BPINIT_FIRST')[0] 'kPa') -cne $t[1]) { $tblOk = $false } }
Check 'B09 Pa to kPa is exactly /1000 (0, 1, 101325, 440000, 490000, 500000.5 Pa)' $tblOk
$h = NewS; $h.Scoring.BpFail = $true; $h.Scoring.BpReason = 'brakesystem-null'; $h.Input.StoreBp = [double[]]@(490.0); $h.Run(200, 16)
$un = @((Named $h 'SI0_UNAVAILABLE') | Where-Object { $_ -match 'group=bpInit' })
Check 'B10 bp_initial unreadable: reported ONCE with the fixed reason over 200 Ticks; NO value is estimated from the running brake pipe pressure (BPP 490 is on the line, but no kPa is written)' (($un.Count -eq 1) -and ($un[0] -ceq 'SI0_UNAVAILABLE gen=0 group=bpInit reason=brakesystem-null') -and ((Named $h 'SI0_BPINIT_FIRST').Count -eq 0) -and ((Named $h 'SI0_CAPABILITY')[0] -match ' bpInit=0 '))
$h.Scoring.BpFail = $false; $h.Run(60, 16)
Check 'B11 a group that becomes readable later gets its FIRST line then (retry every 30 Ticks)' ((Named $h 'SI0_BPINIT_FIRST').Count -eq 1)
$h = NewS; $h.Run(5, 16); $h.Scoring.ControllerPa = 500000.0; $h.Run(35, 16); $h.Run(35, 16)
$bc = Named $h 'SI0_BPINIT_CHANGE'
Check 'B12 a change of the vehicle parameter (another plugin may set it) is ONE CHANGE line with the new value; the same value again adds nothing' (($bc.Count -eq 1) -and ($bc[0] -match 'kPa=500 ') -and ($bc[0] -notmatch 'bpNowKpa'))
$h = NewS; $h.Run(2, 16)
for ($i = 1; $i -le 12; $i++) { $h.Scoring.ControllerPa = 400000.0 + $i * 1000; $h.Run(31, 16) }
Check 'B13 12 changes write at most the per-kind cap of CHANGE lines; the rest is counted as suppressed in the summary' (((Named $h 'SI0_BPINIT_CHANGE').Count -eq [TsScoringLegacyTelemetryTests.ScoringInfo]::CapBpChange) )
$h.Closed()
Check 'B14 the summary states the last bp_initial kPa and the highest brake pipe pressure seen in the generation (a cross-check of the unit and the meaning)' ((Named $h 'SI0_SUMMARY')[0] -match ' bpInit=seen .* bpInitKpa=412 bpNowMaxKpa=490 ')
$h = NewS; $h.Input.StoreBp = [double[]]@(0.0); $h.Run(3, 16); $h.Input.StoreBp = [double[]]@(300.0); $h.Run(3, 16); $h.Input.StoreBp = [double[]]@(489.5); $h.Run(3, 16); $h.Input.StoreBp = [double[]]@(10.0); $h.Run(3, 16); $h.Closed()
Check 'B15 bpNowMaxKpa is the highest present brake pipe pressure (489.5), not the last' ((Named $h 'SI0_SUMMARY')[0] -match ' bpNowMaxKpa=489\.5 ')

# ---------------------------------------------------------------------------------------------------------------------------------------------
# C - O-B: the numbers a vehicle length could be derived from (candidates, never a decision)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewS; $h.Run(3, 16)
Check 'C01 car length 20 m with 1 + 4 + 3 cars: both candidates are logged (160 m for all cars, 140 m for motor + trailer) next to the raw numbers' ((Named $h 'SI0_VEHLEN_FIRST')[0] -ceq 'SI0_VEHLEN_FIRST gen=0 carLenM=20 first=1 motor=4 trailer=3 candTotalM=160 candMotorTrailerM=140 sameAsPrevGen=na')
$h = NewS; $h.Scoring.Trailer = $null; $h.Run(3, 16)
Check 'C02 one count missing: that count is na and neither candidate is built (no guess for the missing car type)' ((Named $h 'SI0_VEHLEN_FIRST')[0] -match 'carLenM=20 first=1 motor=4 trailer=na candTotalM=na candMotorTrailerM=na ')
$h = NewS; $h.Scoring.CarLen = [double]::NaN; $h.Run(3, 16)
Check 'C03 a NaN car length is na, never a number; no candidate' ((Named $h 'SI0_VEHLEN_FIRST')[0] -match 'carLenM=na first=1 motor=4 trailer=3 candTotalM=na candMotorTrailerM=na ')
$h = NewS; $h.Scoring.CarLen = 20.0; $h.Scoring.First = 1.0; $h.Scoring.Motor = 1.5; $h.Scoring.Trailer = 0.0; $h.Run(3, 16)
Check 'C04 the counts are doubles in the host: 1.5 is kept as 1.5 (candidates 50 / 30), 0 is a real value' ((Named $h 'SI0_VEHLEN_FIRST')[0] -match 'motor=1\.5 trailer=0 candTotalM=50 candMotorTrailerM=30 ')
$h = NewS; $h.Run(3, 16); $h.Closed(); $h.Created(); $h.Seed += 1; $h.Run(3, 16); $h.Scoring.CarLen = 21.0; $h.Closed(); $h.Created(); $h.Seed += 1; $h.Run(3, 16)
$vf = Named $h 'SI0_VEHLEN_FIRST'
Check 'C05 stability over generations: the first generation says na, an identical second generation 1, a changed third generation 0' (($vf.Count -eq 3) -and ($vf[0] -match 'sameAsPrevGen=na$') -and ($vf[1] -match 'sameAsPrevGen=1$') -and ($vf[2] -match 'sameAsPrevGen=0$'))
$h = NewS; $h.Run(3, 16); $h.Scoring.Motor = 5.0; $h.Run(35, 16)
Check 'C06 a change inside a generation is one CHANGE line with the new candidates' (((Named $h 'SI0_VEHLEN_CHANGE').Count -eq 1) -and ((Named $h 'SI0_VEHLEN_CHANGE')[0] -match 'motor=5 trailer=3 candTotalM=180 candMotorTrailerM=160$'))
$h = NewS; $h.Scoring.VehFail = $true; $h.Scoring.VehReason = 'dynamics-null'; $h.Run(100, 16)
Check 'C07 vehicle numbers unreadable: reported once with the fixed reason; TRAINLEN is never written to the stream' ((((Named $h 'SI0_UNAVAILABLE') | Where-Object { $_ -match 'group=vehLen reason=dynamics-null$' }).Count -eq 1) -and (@($h.Sink.Sent | Where-Object { $_ -match 'TRAINLEN' }).Count -eq 0))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# D - O-C: the ground limit list and the head / tail question
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewS; Lim $h 0 100; Lim $h 1000 60; Lim $h 2000 100; $h.Api.Location = 500.0; $h.Api.GroundMps = 100 / 3.6; $h.Run(3, 16)
$ll = Named $h 'SI0_LIMITS_LIST'
Check 'D01 a three element list: count, how many carry a value, sorted, the first elements as L<location>V<km/h>' (($ll.Count -eq 1) -and ($ll[0] -match '^SI0_LIMITS_LIST gen=0 count=3 scanned=3 valueNodes=3 other=0 readFail=0 sorted=1 truncated=0 type=ValueNode_1 first=L0V100_L1000V60_L2000V100 scanMs=\d+\.\d$'))
Check 'D02 the list line comes right after the capability line of the same Tick (then the bp_initial and vehicle lines)' (((Probe $h)[0] -match '^SI0_CAPABILITY ') -and ((Probe $h)[1] -match '^SI0_LIMITS_LIST ') -and ((Probe $h)[2] -match '^SI0_BPINIT_FIRST '))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; $h.Scoring.Limits[1].IsNode = $false; $h.Scoring.Limits[1].TypeName = 'MapObjectBase'; $h.Run(3, 16)
Check 'D03 an element that is not a value carrying wrapper is counted as other (not read as a limit) and its class name is logged for the first element' (((Named $h 'SI0_LIMITS_LIST')[0] -match 'count=2 scanned=2 valueNodes=1 other=1 ') -and ((Named $h 'SI0_LIMITS_LIST')[0] -match 'type=ValueNode_1 '))
$h = NewS; Lim $h 0 100; $h.Scoring.Limits[0].TypeName = 'MapObjectBase'; $h.Scoring.Limits[0].IsNode = $false; $h.Run(3, 16)
Check 'D04 the class name of the first element is what the host gave (MapObjectBase here), so a list of plain wrappers is visible as such' ((Named $h 'SI0_LIMITS_LIST')[0] -match 'valueNodes=0 other=1 .*type=MapObjectBase first=-')
$h = NewS; Lim $h 1000 60; Lim $h 0 100; Lim $h 2000 100; $h.Run(3, 16)
Check 'D05 an unsorted list is reported sorted=0' ((Named $h 'SI0_LIMITS_LIST')[0] -match ' sorted=0 ')
$h = NewS; for ($i = 0; $i -lt 6000; $i++) { Lim $h ($i * 10.0) (60 + ($i % 5)) }
$h.Run(1, 16); $afterOne = $h.Scoring.CallCount('TryLimitElement'); $lineAfterOne = (Named $h 'SI0_LIMITS_LIST').Count
$h.Run(40, 16)
$fl = Named $h 'SI0_LIMITS_LIST'
Check 'D06 a list of 6000 is read in slices (never more than the slice size in one Tick), stops at the scan limit and says truncated=1' (($afterOne -eq [TsScoringLegacyTelemetryTests.ScoringInfo]::ScanPerTick) -and ($lineAfterOne -eq 0) -and ($fl.Count -eq 1) -and ($fl[0] -match 'count=6000 scanned=5000 valueNodes=5000 .* truncated=1 ') -and ($h.Scoring.CallCount('TryLimitElement') -eq 5000))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; Lim $h 2000 100; Lim $h 3000 80; $h.Scoring.FailElementAt = 1; $h.Scoring.ThrowElementAt = 2; $h.Run(3, 16)
Check 'D07 elements that cannot be read or throw are counted in readFail and the walk goes on with the rest' ((Named $h 'SI0_LIMITS_LIST')[0] -match 'count=4 scanned=4 valueNodes=2 other=0 readFail=2 ')
$h = NewS; $h.Scoring.LimitsFail = $true; $h.Scoring.LimitsReason = 'limits-null'; $h.Run(100, 16)
Check 'D08 an unreadable list: reported once (limits-null) in 100 Ticks, no LIST line; readable later (30 Ticks) it appears' ((@((Named $h 'SI0_UNAVAILABLE') | Where-Object { $_ -match 'group=limitList reason=limits-null$' }).Count -eq 1) -and ((Named $h 'SI0_LIMITS_LIST').Count -eq 0))
$h.Scoring.LimitsFail = $false; Lim $h 0 100; $h.Run(40, 16)
Check 'D09 ... and then the list line is written' ((Named $h 'SI0_LIMITS_LIST').Count -eq 1)
# the Current sender's own algorithm (Class1.cs MAPHEAD / MAPTAIL), hand computed
$L = [double[]]@(0, 1000, 2000); $K = [double[]]@(100, 60, 100)
$HT = [TsScoringLegacyTelemetryTests.ScoringInfo]
$r1 = $HT::HeadTail(2100.0, 160.0, $L, $K); $r2 = $HT::HeadTail(2100.0, 20.0, $L, $K); $r3 = $HT::HeadTail(500.0, 100.0, $L, $K); $r4 = $HT::HeadTail(2000.0, 160.0, $L, $K); $r5 = $HT::HeadTail(100.0, 0.0, [double[]]@(), [double[]]@())
Check 'D10 HeadTail reproduces the Current sender: (2100 m, 160 m train) head 100 / tail 60; (2100, 20) 100 / 100; (500, 100) 100 / 100; (2000, 160) head 100 tail 60; an empty list 1000 / 1000' ((($r1 -join '/') -ceq '100/60') -and (($r2 -join '/') -ceq '100/100') -and (($r3 -join '/') -ceq '100/100') -and (($r4 -join '/') -ceq '100/60') -and (($r5 -join '/') -ceq '1000/1000'))
Check 'D11 Ahead reproduces MAPLIMITS: window 3000 m, notation L<F1>V<F1>, at most three samples, the count is of all' (((($HT::Ahead(1990.0, $L, $K))) -ceq '1:L2000.0V100.0') -and (($HT::Ahead(5000.0, $L, $K)) -ceq '0:-') -and (($HT::Ahead(-10.0, [double[]]@(10, 20, 30, 40, 50), [double[]]@(1, 2, 3, 4, 5))) -ceq '5:L10.0V1.0_L20.0V2.0_L30.0V3.0'))
# the head / tail observation: a rising limit (60 -> 100 at the element at 2000 m) is where head and tail differ
function Drive($h, [double]$switchAt, [double]$from, [double]$to) {
    $h.Api.Location = $from; $h.Api.GroundMps = 60 / 3.6; $h.Run(3, 16)
    for ($i = 0; $i -lt 400; $i++) { $h.Api.Location += 1.0; if ($h.Api.Location -ge $switchAt) { $h.Api.GroundMps = 100 / 3.6 }; $h.Run(1, 16) }
}
$h = NewS; Lim $h 0 100; Lim $h 1000 60; Lim $h 2000 100; Drive $h 2000.0 1900.0 0
$lc = Named $h 'SI0_LIMIT_CHANGE'
Check 'D12 the host switches when the HEAD passes the element (2000 m): from 60 to 100 at loc 2000, deltaM 0, head matches, neither tail candidate matches' (($lc.Count -eq 1) -and ($lc[0] -ceq 'SI0_LIMIT_CHANGE gen=0 loc=2000 from=60 to=100 head=100 headMatch=1 tailA=60 tailAMatch=0 tailB=60 tailBMatch=0 deltaM=0'))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; Lim $h 2000 100; Drive $h 2160.0 1900.0 0
$lc = Named $h 'SI0_LIMIT_CHANGE'
Check 'D13 the host switches when the TAIL (160 m = candidate A) has passed: at loc 2160, deltaM 160, tail A matches' (($lc.Count -eq 1) -and ($lc[0] -match ' loc=2160 from=60 to=100 ') -and ($lc[0] -match ' tailA=100 tailAMatch=1 ') -and ($lc[0] -match ' deltaM=160$'))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; Lim $h 2000 100; Drive $h 2140.0 1900.0 0
$lc = Named $h 'SI0_LIMIT_CHANGE'
Check 'D14 the host switches 140 m after the element (candidate B = motor + trailer): tail B matches and tail A does not (it would still be at 60)' (($lc.Count -eq 1) -and ($lc[0] -match ' tailA=60 tailAMatch=0 tailB=100 tailBMatch=1 ') -and ($lc[0] -match ' deltaM=140$'))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; $h.Api.Location = 990.0; $h.Api.GroundMps = 100 / 3.6; $h.Run(3, 16)
for ($i = 0; $i -lt 30; $i++) { $h.Api.Location += 1.0; if ($h.Api.Location -ge 1000.0) { $h.Api.GroundMps = 60 / 3.6 }; $h.Run(1, 16) }
Check 'D15 a falling limit (100 -> 60) is logged too, with head matching at deltaM 0' (((Named $h 'SI0_LIMIT_CHANGE').Count -eq 1) -and ((Named $h 'SI0_LIMIT_CHANGE')[0] -match ' loc=1000 from=100 to=60 head=60 headMatch=1 .* deltaM=0$'))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; $h.Api.Location = 100.0; $h.Api.GroundMps = [double]::PositiveInfinity; $h.Run(3, 16); $h.Api.GroundMps = 60 / 3.6; $h.Run(2, 16); $h.Api.GroundMps = [double]::NaN; $h.Run(2, 16)
Check 'D16 "no limit" (infinity) is the sentinel 1000 and a change to 60 is logged; a NaN limit is ignored (no line, no crash)' (((Named $h 'SI0_LIMIT_CHANGE').Count -eq 1) -and ((Named $h 'SI0_LIMIT_CHANGE')[0] -match ' from=1000 to=60 '))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; $h.Api.Location = 100.0
for ($i = 0; $i -lt 60; $i++) { $h.Api.GroundMps = $(if ($i % 2 -eq 0) { 60 / 3.6 } else { 80 / 3.6 }); $h.Run(1, 16) }
$h.Closed()
Check 'D17 60 changes of the limit write exactly the per-kind cap of LIMIT_CHANGE lines; the summary counts all 59 of them and the generation never exceeds the total line limit' (((Named $h 'SI0_LIMIT_CHANGE').Count -eq [TsScoringLegacyTelemetryTests.ScoringInfo]::CapLimitChange) -and ((Named $h 'SI0_SUMMARY')[0] -match ' limitChanges=59 ') -and ((Si0 $h | Where-Object { $_ -notmatch '^SI0_ORDER ' }).Count -le [TsScoringLegacyTelemetryTests.ScoringInfo]::MaxLines))
$h = NewS; for ($i = 0; $i -lt 6000; $i++) { Lim $h ($i * 10.0) 60 }
$h.Api.Location = 500.0
for ($i = 0; $i -lt 8; $i++) { $h.Api.GroundMps = $(if ($i % 2 -eq 0) { 60 / 3.6 } else { 80 / 3.6 }); $h.Run(1, 16) }
$midChanges = (Named $h 'SI0_LIMIT_CHANGE').Count; $midList = (Named $h 'SI0_LIMITS_LIST').Count; $midAhead = (Named $h 'SI0_LIMITS_AHEAD').Count
$h.Run(10, 16)
Check 'D18 while the list is still being read in slices nothing is judged against a half list: no LIMIT_CHANGE, no LIMITS_AHEAD and no LIST line at Tick 8; after the walk the LIST line and the AHEAD line exist' (($midChanges -eq 0) -and ($midList -eq 0) -and ($midAhead -eq 0) -and ((Named $h 'SI0_LIMITS_LIST').Count -eq 1) -and ((Named $h 'SI0_LIMITS_AHEAD').Count -eq 1))
$h = NewS; Lim $h 0 100; Lim $h 1000 60; Lim $h 2000 100; $h.Api.Location = 1990.0; $h.Api.GroundMps = 60 / 3.6; $h.Run(3, 16)
Check 'D19 the first Tick with a position writes ONE LIMITS_AHEAD line: the location, how many entries lie within 3000 m ahead, the first three in the notation of MAPLIMITS, and the host limit next to the list value at the head' (((Named $h 'SI0_LIMITS_AHEAD').Count -eq 1) -and ((Named $h 'SI0_LIMITS_AHEAD')[0] -ceq 'SI0_LIMITS_AHEAD gen=0 loc=1990 n=1 sample=L2000.0V100.0 cur=60 head=60 headMatch=1'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# E - O-D: the order of events, the first Tick, the heartbeat and the first line
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewS; $h.NoteInit('events=yes heartbeat=yes'); $h.Api.Created = $false
$h.Opened($false); $h.Run(3, 16); $h.Api.Created = $true; $h.Created(); $h.Run(3, 16)
$o = Orders $h
$words = @($o | ForEach-Object { Kv $_ 'ev' })
Check 'E01 order of words with the host not yet created: init, evt-opened (created=0), a first Tick that sees created=0, then created, epoch-begin and the first line' ((($words -join ',') -ceq 'init,evt-opened,tick-first-process,evt-created,created-changed,epoch-begin,line-first') -and ($o[1] -match ' reload=0 created=0$') -and ($o[2] -match ' created=0 epochs=0$') -and ($o[3] -match ' created=1$'))
$seqs = @($o | ForEach-Object { Seq $_ })
Check 'E02 seq is 1, 2, 3 ... in the order things happened (strictly increasing, no gaps for written lines)' ((($seqs -join ',') -ceq '1,2,3,4,5,6,7'))
Check 'E03 every ORDER line has the fixed shape (seq, t, th, ev, key=value ...) and t is the monotonic millisecond clock of the sender' ((@($o | Where-Object { $_ -notmatch $SHAPE_ORDER }).Count -eq 0) -and ($o[0] -match ' t=1000 '))
$h = NewS; $h.Opened($true); $h.Run(3, 16)
Check 'E04 a reload is told by reload=1' ((Ev $h 'evt-opened')[0] -match ' reload=1 created=1$')
$h = NewS; $h.Run(20, 16); $tick = [Threading.Thread]::CurrentThread.ManagedThreadId
$hb0 = $h.Heartbeat(); $h.Now += 1000; $hb1 = $h.Heartbeat(); $hb1b = $h.Heartbeat(); $h.Run(2, 16); $hb2 = $h.Heartbeat()
Check 'E05 the heartbeat notes its status changes: first running, then paused (once, however often it is asked), then running again after the next Tick' (((Ev $h 'hb-first-running').Count -eq 1) -and ((Ev $h 'hb-paused').Count -eq 1) -and ((Ev $h 'hb-running-again').Count -eq 1) -and ((Ev $h 'tick-resume').Count -eq 1) -and ((Ev $h 'tick-resume')[0] -match ' gapMs=1016 created=1$'))
$h = NewS; $h.Run(10, 16); $apiCalls = ($h.Api.Calls.Values | Measure-Object -Sum).Sum; $sc = $h.Scoring.TotalCalls(); $inCalls = $h.Input.TotalCalls()
$hbThread = $h.HeartbeatOnOtherThread(2000)
Check 'E06 the heartbeat thread touches no host object: after 2000 heartbeats from a second thread the Legacy API, the input API and the scoring API were not called once more' (($hbThread -ne $tick) -and ((($h.Api.Calls.Values | Measure-Object -Sum).Sum) -eq $apiCalls) -and ($h.Scoring.TotalCalls() -eq $sc) -and ($h.Input.TotalCalls() -eq $inCalls))
$h = NewS; $h.Run(10, 16); $h.Now += 5000; $null = $h.HeartbeatOnOtherThread(1)
$hp = Ev $h 'hb-paused'
Check 'E07 the pause status is written from the heartbeat thread (th differs from the Tick thread) and every scoring read came from the Tick thread only' (($hp.Count -eq 1) -and ((Kv $hp[0] 'th') -ne [string]$tick) -and ($h.Scoring.Threads.Count -eq 1) -and ($h.Scoring.Threads.Contains($tick)))
$h = NewS; $h.Run(10, 16); $null = $h.Heartbeat(); $h.Closed(); $h.Created(); $h.Seed += 5; $h.Run(5, 16); $null = $h.Heartbeat()
Check 'E08 the heartbeat status starts again with every scenario instance (hb-first-running once per instance: 2)' ((Ev $h 'hb-first-running').Count -eq 2)
$h = NewS; $h.Run(5, 16); $h.Now += 200; $h.Run(3, 16); $noGap = (Ev $h 'tick-resume').Count
$h.Now += 251; $h.Run(1, 16); $withGap = (Ev $h 'tick-resume').Count
Check 'E09 a gap of 200 ms between Ticks is not a pause (no tick-resume), a gap of 251 ms is (one tick-resume)' (($noGap -eq 0) -and ($withGap -eq 1))
$h = NewS; $h.Run(5, 16); $h.Dispose()
Check 'E10 dispose is noted once, and the epoch-end of the last instance (reason dispose) follows it' (((Ev $h 'dispose').Count -eq 1) -and ((Seq (Ev $h 'dispose')[0]) -lt (Seq (Ev $h 'epoch-end')[0])) -and ((Ev $h 'epoch-end')[0] -match 'reason=dispose$'))
$h = NewS; $hbBefore = $h.Heartbeat(); $null = $h.HeartbeatOnOtherThread(100)
$idleBefore = (Ev $h 'hb-idle').Count; $h.Run(3, 16); $hbAfter = $h.Heartbeat(); $h.Closed(); $null = $h.HeartbeatOnOtherThread(100)
Check 'E10b the heartbeat before the first Tick is silent (null, as before) but noted ONCE as hb-idle (the timer is alive, no instance is active); the first running status follows, and a second idle period after the close is noted again' (($hbBefore -eq $null) -and ($idleBefore -eq 1) -and ($hbAfter -ceq 'STATUS:LOADED:RUNNING') -and ((Ev $h 'hb-first-running').Count -eq 1) -and ((Ev $h 'hb-idle').Count -eq 2) -and ((Seq (Ev $h 'hb-idle')[0]) -lt (Seq (Ev $h 'hb-first-running')[0])))
$rb = New-Object "$NS.RecorderBox"
for ($i = 0; $i -lt 1000; $i++) { $rb.Note('same-word', 'k=1') }
$perWord = [TsScoringLegacyTelemetryTests.ScoringInfo]::OrderMaxPerWord
Check 'E11 one word is written at most MaxPerWord times; the rest is counted' (($rb.Lines.Count -eq $perWord) -and ($rb.Suppressed -eq 1000 - $perWord))
$rb = New-Object "$NS.RecorderBox"
for ($i = 0; $i -lt 100; $i++) { for ($j = 0; $j -lt 8; $j++) { $rb.Note('w' + $i, 'k=1') } }
$maxAll = [TsScoringLegacyTelemetryTests.ScoringInfo]::OrderMaxLines
Check 'E12 the whole process never writes more than MaxLinesPerProcess order lines (800 notes of 100 words)' (($rb.Lines.Count -eq $maxAll) -and ($rb.Written -eq $maxAll))
$rb = New-Object "$NS.RecorderBox"
$rb.NoteFromThreads(4, 50)

$sq = @($rb.Lines | ForEach-Object { Seq $_ })
Check 'E13 four threads noting at once: every seq is unique and the lines are all well formed' (($sq.Count -gt 0) -and ($sq.Count -eq @($sq | Sort-Object -Unique).Count) -and (@($rb.Lines | Where-Object { $_ -notmatch '^SI0_ORDER seq=\d+ t=\d+ th=\d+ ev=[a-z0-9\-]+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)*$' }).Count -eq 0))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# F - what the log may contain, generations, the real file log
# ---------------------------------------------------------------------------------------------------------------------------------------------
$jp = ([string][char]0x30c6) + ([string][char]0x30b9) + ([string][char]0x30c8)
$tw = [TsScoringLegacyTelemetryTests.ScoringInfo]
Check 'F01 TypeWord: a generic marker becomes _, a path, Japanese text, spaces and a 41 character name are other, a plain name stays' (($tw::TypeWord([Collections.Generic.List[double]]) -ceq 'List_1') -and ($tw::TypeWord($null) -ceq 'other') -and ($tw::SafeWord('C:\x\y', 'z') -ceq 'z') -and ($tw::SafeWord($jp, 'z') -ceq 'z') -and ($tw::SafeWord('a b', 'z') -ceq 'z') -and ($tw::SafeWord(('a' * 41), 'z') -ceq 'z') -and ($tw::SafeWord('ok-word_1', 'z') -ceq 'ok-word_1') -and ($tw::SafeVersion('1.0.50314.2') -ceq '1.0.50314.2') -and ($tw::SafeVersion('1.0 beta') -ceq 'na'))
Check 'F02 Num: fixed notation, no exponent, no plus sign; NaN / Infinity are x; absurd values are big' (($tw::Num(490.0) -ceq '490') -and ($tw::Num(0.000001) -ceq '0.000001') -and ($tw::Num([double]::NaN) -ceq 'x') -and ($tw::Num([double]::PositiveInfinity) -ceq 'x') -and ($tw::Num(1e30) -ceq 'big') -and ($tw::Num(-12.5) -ceq '-12.5'))
$all = @()
foreach ($mk in @(
    { $x = NewS; Lim $x 0 100; Lim $x 1000 60; $x.Run(60, 16); $x.Closed(); $x },
    { $x = NewS; $x.Scoring.BpFail = $true; $x.Scoring.VehFail = $true; $x.Scoring.LimitsFail = $true; $x.Run(100, 16); $x.Dispose(); $x },
    { $x = NewS; $x.Scoring.Version = $jp; $x.Scoring.ControllerPa = [double]::NaN; $x.Scoring.CarLen = [double]::PositiveInfinity; Lim $x 0 100; $x.Scoring.Limits[0].TypeName = 'C:\secret\name'; $x.Run(20, 16); $x.Dispose(); $x },
    { $x = NewS; $x.Scoring.Version = 'x'; $x.Scoring.KindValue = 3; $x.Scoring.ClProp = $true; $x.Scoring.ClPa = 450000.0; $x.Run(20, 16); $x.Closed(); $x.Created(); $x.Seed += 3; $x.Run(20, 16); $x.Dispose(); $x }
)) { $all += (Si0 (& $mk)) }
$bad = @($all | Where-Object { ($_ -notmatch $SHAPE) -and ($_ -notmatch $SHAPE_ORDER) })
Check ('F03 every SI0 line has the fixed shape (NAME gen=N key=value ... or the ORDER shape) with letters, digits, _ . - only (' + $all.Count + ' lines of four different runs checked): no path, no free text, no exception text, no Japanese') ($bad.Count -eq 0)
$un = @($all | Where-Object { $_ -match 'C:|secret|name' })
Check 'F04 a class name or version that is a path or Japanese text is replaced by a fixed word (other / na), nothing of it is written' (($un.Count -eq 0) -and (@($all | Where-Object { $_ -match 'type=other' }).Count -ge 1) -and (@($all | Where-Object { $_ -match 'hostTypes=na' }).Count -ge 1))
$h = NewS; Lim $h 0 100; $h.Run(10, 16); $h.Closed(); $h.Created(); $h.Seed += 9; $h.Run(10, 16); $h.Dispose()
$sm = Named $h 'SI0_SUMMARY'
Check 'F05 each scenario generation ends with exactly one summary (close, then dispose): 2 summaries for 2 generations, the second with its own id' (($sm.Count -eq 2) -and ($sm[0] -match 'gen=0 ') -and ($sm[1] -match 'gen=9 '))
Check 'F06 a new generation starts the observation again: a second CAPABILITY, BPINIT_FIRST, VEHLEN_FIRST, LIMITS_LIST and LIMITS_AHEAD with the new id' (((Named $h 'SI0_CAPABILITY').Count -eq 2) -and ((Named $h 'SI0_BPINIT_FIRST').Count -eq 2) -and ((Named $h 'SI0_VEHLEN_FIRST').Count -eq 2) -and ((Named $h 'SI0_LIMITS_LIST').Count -eq 2) -and ((Named $h 'SI0_LIMITS_AHEAD').Count -eq 2) -and ((Named $h 'SI0_BPINIT_FIRST')[1] -match 'gen=9 '))
$hf = NewS; $hf.Api.Meta = @('SecretTitle', 'SecretRoute', 'SecretVehicle', 'SecretAuthor', 'SecretComment'); Lim $hf 0 100; $fileLog = Join-Path $testDir 'si0-diag.log'; $hf.UseFileDiag($fileLog); $hf.NoteInit('events=yes heartbeat=yes'); $hf.Run(30, 16); $hf.Dispose()
$fl = @([IO.File]::ReadAllLines($fileLog)); $fi = @($fl | Where-Object { $_ -match ' SI0_' })
Check 'F07 the real file log carries the SI0 lines in the TEL_ log format (HH:mm:ss.fff P= I= NAME ...), no scenario text and no path' (($fi.Count -ge 8) -and (@($fi | Where-Object { $_ -notmatch '^\d\d:\d\d:\d\d\.\d{3} P=\d+ I=\d+ SI0_[A-Z_]+ ' }).Count -eq 0) -and (($fl -join "`n") -notmatch 'Secret') -and (($fi -join "`n") -notmatch '[A-Za-z]:\\'))
$priv = Join-Path $Root 'Tools\Audit-Privacy.ps1'
$ap = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $priv 2>&1 | Out-String
$apHits = ([regex]::Matches($ap, 'matches=(\d+)') | ForEach-Object { [int]$_.Groups[1].Value })
Check 'F08 the privacy audit (Audit-Privacy.ps1) finds 0 matches in every public candidate group (sources, documents, observation logs of the tests)' ((@($apHits | Select-Object -First 6 | Where-Object { $_ -ne 0 }).Count -eq 0) -and ($apHits.Count -ge 6))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# G - sources, version, scope
# ---------------------------------------------------------------------------------------------------------------------------------------------
$probeCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyScoringProbe.cs')))
$sessCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetrySession.cs')))
$extRaw = [IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetryExtension.cs')); $extCode = Code $extRaw
Check 'G01 the probe is host independent (no AtsEx / BveTypes / BveEx name, also in the session) and uses no reflection, hook, DllImport, unsafe, Harmony, private member, thread, timer or task' ((($probeCode + $sessCode) -cnotmatch 'AtsEx|BveTypes|BveEx') -and ($probeCode -notmatch 'BindingFlags|DllImport|\bunsafe\b|Harmony|\.GetField\(|\.GetProperty\(|\.GetMethod\(|\.Invoke\(|Marshal\.|new Thread|ThreadPool|System\.Threading\.Tasks|Task\.Run|new Timer|Timers\.'))
$i0 = $extCode.IndexOf('ILegacyScoringApi.HostTypesVersion'); $i1 = $extCode.IndexOf('public bool TryBrakeNotches')
$si0Region = if (($i0 -ge 0) -and ($i1 -gt $i0)) { $extCode.Substring($i0, $i1 - $i0) } else { '' }
Check 'G02 the host adapter calls NONE of the host methods that move, re-time, initialise or jump anything (Scenario.Initialize, InitializeTimeAndLocation, TimeManager.SetTime, SetSpeed, list GoTo / GoToByIndex / CurrentIndex, Insert / Add / Remove / Clear) anywhere in the file' (($si0Region.Length -gt 1000) -and ($extCode -notmatch '\.Initialize\(|InitializeTimeAndLocation|\.SetTime\(|\.SetSpeed\(|\.GoTo\(|\.GoToByIndex\(|CurrentIndex|\.Draw\('))
Check 'G03 the SI-0 part of the adapter only READS: no assignment to any host member (BpInitialPressure, CarLength, Count, Value, Location, Smee, Cl ...) and no call of Add / Insert / Remove / Clear on a host list' (($si0Region -notmatch '\b(smee|cl|smeeProperty|clProperty|dynamics|first|motor|trailer|list|item|node|system|controller|vehicle|route|instruments)\.\w+\s*=[^=]') -and ($si0Region -notmatch '\.(Add|Insert|Remove|RemoveAt|Clear)\('))
Check 'G04 the adapter reaches the limit list only through the public Count, the public indexer, MapObjectBase.Location and ValueNode<double>.Value (a cast, no FromSource, no Src) and builds no host object' (($si0Region -match 'list\.Count') -and ($si0Region -match 'list\[index\]') -and ($si0Region -match 'item as ValueNode<double>') -and ($si0Region -notmatch 'FromSource|\.Src\b|new (Scenario|Smee|Cl|CarInfo|ValueNode|SpeedLimitList)'))
$cb = $sessCode.IndexOf('internal string ComposeHeartbeat'); $ce = $sessCode.IndexOf('internal void OnTick')
$hbRegion = if (($cb -ge 0) -and ($ce -gt $cb)) { $sessCode.Substring($cb, $ce - $cb) } else { '' }
Check 'G05 the heartbeat path (ComposeHeartbeat and NoteHeartbeat) uses no api, input, probe or cache member: it can only read its own fields and write a counter and a log line' (($hbRegion.Length -gt 300) -and ($hbRegion -notmatch 'api\.|inputCache|inputProbe|scoringProbe|inputTelemetry|timeline') -and ($hbRegion -match 'order\.Note'))
Check 'G06 no exception text can reach a log line (the probe and the order recorder never use a caught exception: no .Message, no ex.ToString, no catch (Exception e))' (($probeCode -notmatch '\.Message|catch\s*\(\s*Exception') -and ($sessCode -notmatch 'order\.Note\([^;]*\.Message'))
$vi = (Get-Item $dllPath).VersionInfo
Check 'G07 the DLL is 0.3.1.0 (assembly and file version), product TS Scoring, provider Coruge-to; the description names Phase L3, LI1, LI2 and SI-0 and says it is an observation build' (([TsScoringLegacyTelemetryTests.DiagInfo]::Version -eq '0.3.1.0') -and ($vi.FileVersion -eq '0.3.1.0') -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.Comments -match 'Phase L3') -and ($vi.Comments -match 'LI1') -and ($vi.Comments -match 'LI2') -and ($vi.Comments -match 'SI-0') -and ($vi.Comments -match 'OBSERVATION'))
$cs = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
Check 'G08 the project compiles the new source and adds no reference (the same five host assemblies as before)' (($cs -match 'src\\LegacyScoringProbe\.cs') -and ([regex]::Matches($cs, '<Reference Include=').Count -eq 7))
function RunGit([string[]]$gitArgs) { $out = & git @gitArgs 2>$null; if ($LASTEXITCODE -ne 0) { return '' }; return ($out -join "`n") }
$top = (RunGit @('-C', $Root, 'rev-parse', '--show-toplevel')).Trim() -replace '/', '\'
$frozen = @(
    'TsScoringPlugin/TsScoringPlugin', 'TsScoringPlugin/Handshake/Caller', 'TsScoringPlugin/Handshake/Bridge', 'TsScoringPlugin/Handshake/Shared', 'TsScoringPlugin/Handshake/Telemetry/Shared',
    'telemetry_contract.py', 'telemetry_gate.py', 'network.py', 'main.py', 'hud_ui.py', 'scoring_logic.py', 'managed_hud.py', 'managed_mode.py', 'managed_state.py', 'menu_ui.py', 'config.py', 'utils.py',
    'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputProbe.cs',
    'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyHandleContract.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputTelemetry.cs', 'tests/legacy_input_matrix24.json', 'tests/legacy_input_reference.py'
)
$changedFrozen = @((RunGit (@('-C', $top, 'diff', '--name-only', 'HEAD', '--') + $frozen)) -split "`n" | Where-Object { $_ })
Check ('G09 frozen and byte-identical to HEAD: the Current sender, the Caller, both Bridges, the Handshake protocol and shared contract, every production Python file (no Legacy branch, no update_logic change), the Legacy API seam, the station timeline, the input probe, the handle contract and the input telemetry (' + $changedFrozen.Count + ' changed) ' + ($changedFrozen -join ',')) ($changedFrozen.Count -eq 0)
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', 'HEAD')) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
$allowed = @($touched | Where-Object { $_ -match '^TsScoringPlugin/Handshake/(Telemetry/Legacy/(src/|TSScoringPlugin\.AtsExLegacy\.Telemetry\.csproj$)|Tests/|Tools/|Docs/Handshake-PhaseSI0)|^tests/test_scoring_observation_si0\.py$' })
$outside = @($touched | Where-Object { $_ -notin $allowed })
Check ('G10 scope: only the Legacy telemetry sources and project, the tests, the verifiers and the SI-0 document / test changed (' + $touched.Count + ' files; outside: ' + ($outside -join ',') + ')') ($outside.Count -eq 0)
$newBinary = @($untracked | Where-Object { $_ -match '\.(dll|pdb|log|exe|zip)$' })
Check 'G11 no DLL, PDB, log, executable or archive is added to Git by this phase (generated output stays ignored)' ($newBinary.Count -eq 0)
Check 'G12 nothing of the later phases is implemented: no bp_initial / vehicle length / limit list / jump / 54322 / TRAINLEN / MAPLIMITS key in any sender source (comments excluded)' ((($probeCode + $sessCode + $extCode) -cnotmatch '54322|JUMP_|TRAINLEN|"MAPLIMITS"|"CLEARDIST"|"BPP"|"JUMP"|UdpClient\(54322'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# H - the host's own metadata (O-E, and the facts O-A / O-B / O-C rest on); skipped where the Legacy host is not installed
# ---------------------------------------------------------------------------------------------------------------------------------------------
$bveTypesPath = Join-Path $legacyHost 'BveTypes.dll'
if (Test-Path $bveTypesPath) {
    $bt = [Reflection.Assembly]::LoadFrom($bveTypesPath)
    function WT([string]$n) { return $bt.GetType('BveTypes.ClassWrappers.' + $n, $false) }
    function Meth($t, [string]$name, [Type[]]$ps) { return $t.GetMethod($name, [Type[]]$ps) }
    $mInit = Meth (WT 'Scenario') 'Initialize' @([int]); $mInitTL = Meth (WT 'Scenario') 'InitializeTimeAndLocation' @([double], [int]); $mSet = Meth (WT 'TimeManager') 'SetTime' @([int])
    Check 'H01 O-E: Scenario.Initialize(int), Scenario.InitializeTimeAndLocation(double, int) and TimeManager.SetTime(int) are PUBLIC instance methods returning void in the installed host wrapper library (and are called nowhere in this phase)' (($mInit -ne $null) -and ($mInitTL -ne $null) -and ($mSet -ne $null) -and $mInit.IsPublic -and $mInitTL.IsPublic -and $mSet.IsPublic -and (-not $mInit.IsStatic) -and ($mInit.ReturnType -eq [void]) -and ($mInitTL.ReturnType -eq [void]) -and ($mSet.ReturnType -eq [void]) -and ($mInit.GetParameters()[0].Name -ceq 'stationIndex') -and ($mInitTL.GetParameters()[0].Name -ceq 'location') -and ($mInitTL.GetParameters()[1].Name -ceq 'timeMilliseconds') -and ($mSet.GetParameters()[0].Name -ceq 'timeMilliseconds'))
    $pS = (WT 'Smee').GetProperty('BpInitialPressure'); $pC = (WT 'Cl').GetProperty('BpInitialPressure'); $pE = (WT 'Ecb').GetProperty('BpInitialPressure')
    Check 'H02 O-A: Smee and Cl have a public double BpInitialPressure (get and set); Ecb has none (inherited or own) - the Ecb is out of scope by the library itself' (($pS -ne $null) -and ($pC -ne $null) -and ($pS.PropertyType -eq [double]) -and ($pC.PropertyType -eq [double]) -and $pS.CanRead -and $pS.CanWrite -and $pC.CanRead -and ($pE -eq $null))
    $vn = WT 'ValueNode`1'; $sl = WT 'SpeedLimitList'; $dyn = WT 'VehicleDynamics'; $ci = WT 'CarInfo'
    Check 'H03 O-C: ValueNode<T>.Value is public (so a list element CAN carry a limit), SpeedLimitList derives from the wrapped MapObjectBase list and has CurrentLimit but NO VehicleLength (the Current library has it)' (($vn.GetProperty('Value') -ne $null) -and ($vn.BaseType.Name -ceq 'MapObjectBase') -and ($sl.GetProperty('CurrentLimit') -ne $null) -and ($sl.GetProperty('VehicleLength') -eq $null) -and ($sl.GetProperty('Count') -ne $null) -and ($sl.GetProperty('Item') -ne $null))
    Check 'H04 O-B: VehicleDynamics.CarLength is a double (one car, metres per its documentation) and CarInfo.Count is a DOUBLE; FirstCar, MotorCar, TrailerCar are CarInfo' (($dyn.GetProperty('CarLength').PropertyType -eq [double]) -and ($ci.GetProperty('Count').PropertyType -eq [double]) -and ($dyn.GetProperty('FirstCar').PropertyType -eq $ci) -and ($dyn.GetProperty('MotorCar').PropertyType -eq $ci) -and ($dyn.GetProperty('TrailerCar').PropertyType -eq $ci))
    $mapOk = $true; $mapSeen = 0
    foreach ($rn in $bt.GetManifestResourceNames()) {
        if ($rn -notmatch '^BveTypes\.WrapTypes\.') { continue }
        $mapSeen++
        $sr = New-Object IO.StreamReader($bt.GetManifestResourceStream($rn), [Text.Encoding]::UTF8); $xml = $sr.ReadToEnd(); $sr.Close()
        $scn = [regex]::Match($xml, '(?s)<Class Wrapper="Scenario" Original="(\w+)">.*?</Class>')
        $tm = [regex]::Match($xml, '(?s)<Class Wrapper="TimeManager" Original="(\w+)">.*?</Class>')
        $okInit = [regex]::IsMatch($scn.Value, '<Method Wrapper="Initialize" WrapperParams="System\.Int32" Original="a"/>')
        $okTL = [regex]::IsMatch($scn.Value, '<Method Wrapper="InitializeTimeAndLocation" WrapperParams="System\.Double; System\.Int32" Original="a" IsOriginalNonPublic="true"/>')
        $okSet = [regex]::IsMatch($tm.Value, '<Method Wrapper="SetTime" WrapperParams="System\.Int32" Original="a"/>')
        if (-not ($scn.Success -and $tm.Success -and $okInit -and $okTL -and $okSet)) { $mapOk = $false }
    }
    Check 'H05 O-E: in both embedded host mappings (BVE 5.8 and 6.0) Initialize(int) is the PUBLIC original method a(int), InitializeTimeAndLocation(double, int) the NON-public original a(double, int), TimeManager.SetTime(int) the public original a(int)' (($mapSeen -ge 2) -and $mapOk)
    $adapter = $null
    try { $adapter = $fixAsm.GetType('TsScoringLegacyTelemetryTests.ScoringAdapterProbe').GetMethod('Run').Invoke($null, @()) } catch { $adapter = $null }
    Check 'H06 the REAL host adapter with nothing attached never throws: a version text and the fixed reasons scenario-null for all four scoring reads' (($adapter -ne $null) -and ($adapter[0] -match '^\d+\.\d+\.\d+\.\d+$') -and ($adapter[1] -ceq 'False:scenario-null') -and ($adapter[2] -ceq 'False:scenario-null') -and ($adapter[3] -ceq 'False:scenario-null') -and ($adapter[4] -ceq 'False:scenario-null'))
}
else { Skip 'H01-H06 (the installed Legacy host assemblies are not available here)' }

# the original BVE assemblies, metadata only (reflection-only load in a child process; nothing is executed): the Current sender picks "the first void(int) / void(double, int) method of the original Scenario class"
$bveProbe = Join-Path $testDir 'bve-original.ps1'
[IO.File]::WriteAllText($bveProbe, @'
param([string]$Exe)
$dir = Split-Path $Exe
[AppDomain]::CurrentDomain.add_ReflectionOnlyAssemblyResolve({ param($s, $e) $n = $e.Name.Split(',')[0]; $p = Join-Path $dir ($n + '.dll'); if (Test-Path $p) { return [Reflection.Assembly]::ReflectionOnlyLoadFrom($p) }; return [Reflection.Assembly]::ReflectionOnlyLoad($e.Name) })
$a = [Reflection.Assembly]::ReflectionOnlyLoadFrom($Exe)
$t = $a.GetType('er', $false)
$flags = [Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly'
$vi = 0; $vdi = 0; $names = @()
foreach ($m in $t.GetMethods($flags)) {
    $ps = $null; try { $ps = $m.GetParameters() } catch { continue }
    $sig = ($ps | ForEach-Object { $_.ParameterType.Name }) -join ','
    $ret = $null; try { $ret = $m.ReturnType.Name } catch { continue }
    if ($ret -ne 'Void') { continue }
    if ($sig -eq 'Int32') { $vi++; $names += ('int:' + $m.Name + ':public=' + $m.IsPublic) }
    if ($sig -eq 'Double,Int32') { $vdi++; $names += ('double-int:' + $m.Name + ':public=' + $m.IsPublic) }
}
'voidInt=' + $vi + ' voidDoubleInt=' + $vdi + ' ' + (($names | Sort-Object) -join ' ')
'@, (New-Object Text.UTF8Encoding($false)))
$bveFound = 0
foreach ($ex in @(@('5', 'C:\Program Files (x86)\mackoy\BveTs5\BveTs.exe'), @('6', 'C:\Program Files\mackoy\BveTs6\BveTs.exe'))) {
    if (Test-Path $ex[1]) {
        $bveFound++
        $o = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bveProbe -Exe $ex[1] 2>&1 | Out-String).Trim()
        Check ('H07 O-E, BVE ' + $ex[0] + ': the original Scenario class has exactly ONE void(int) method (the public a) and exactly ONE void(double, int) method (the non-public a) - so the search of the Current sender for the first void(int) / void(double, int) method can only find the very methods the public wrappers Initialize / InitializeTimeAndLocation map to (' + $o + ')') ($o -match '^voidInt=1 voidDoubleInt=1 double-int:a:public=False int:a:public=True$')
    }
}
if ($bveFound -eq 0) { Skip 'H07 (BVE is not installed here)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# I - the BVE5 32-bit path: the same DLL loaded by a 32-bit process writes the same bytes (the SI0 lines without their timing and thread numbers included)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$probe = Join-Path $testDir 'probe.ps1'
[IO.File]::WriteAllText($probe, @'
param([string]$Dll, [string]$Fixture, [string]$Out)
Add-Type -TypeDefinition ([IO.File]::ReadAllText($Fixture)) -ReferencedAssemblies @($Dll) -OutputAssembly (Join-Path (Split-Path $Out) 'TsScoringLegacyTelemetryTests.dll') -OutputType Library
[void][Reflection.Assembly]::LoadFrom($Dll)
[void][Reflection.Assembly]::LoadFrom((Join-Path (Split-Path $Out) 'TsScoringLegacyTelemetryTests.dll'))
$lines = New-Object System.Collections.Generic.List[string]
foreach ($kind in 1, 2, 3) {
    $h = New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList @($true, $true, $true)
    $h.Api.BrakeKind = $kind; $h.Input.BrakeKindValue = $kind; $h.Scoring.KindValue = $kind
    foreach ($e in @(@(0.0, 27.77), @(1000.0, 16.66), @(2000.0, 27.77))) { $h.Scoring.Limits.Add((New-Object TsScoringLegacyTelemetryTests.FakeLimit -ArgumentList @($e[0], $e[1]))) }
    $h.NoteInit('events=yes heartbeat=yes'); $h.Opened($false); $h.Created()
    $h.Api.Location = 1900.0; $h.Api.GroundMps = 16.66
    for ($i = 0; $i -lt 300; $i++) { $h.Api.Location += 1.0; if ($h.Api.Location -ge 2000.0) { $h.Api.GroundMps = 27.77 }; $h.Input.StoreBp = [double[]]@(490.0 - ($i % 7)); $h.Run(1, 16) }
    $h.Now += 2000; $null = $h.Heartbeat(); $h.Run(3, 16); $null = $h.Heartbeat()
    $h.Closed(); $h.Dispose()
    foreach ($s in $h.Sink.Sent) { $lines.Add($s) }
    foreach ($e in $h.Diag.Events) { if ($e -like 'SI0_*') { $lines.Add(($e -replace ' scanMs=[0-9.]+', '' -replace ' th=\d+', '')) } }
}
$bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
$sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-', '')
[IO.File]::WriteAllText($Out, ('ptr=' + [IntPtr]::Size + ' lines=' + $lines.Count + ' sha=' + $sha), (New-Object Text.UTF8Encoding($false)))
'@, (New-Object Text.UTF8Encoding($false)))
$ps64 = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
if ((Test-Path $ps32) -and (Test-Path $ps64)) {
    $d64 = Join-Path $testDir 'p64'; $d32 = Join-Path $testDir 'p32'
    New-Item -ItemType Directory -Force $d64, $d32 | Out-Null
    Copy-Item $dllCopy $d64; Copy-Item $dllCopy $d32
    & $ps64 -NoProfile -ExecutionPolicy Bypass -File $probe -Dll (Join-Path $d64 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -Fixture $fixtureSrc -Out (Join-Path $d64 'out.txt') | Out-Null
    & $ps32 -NoProfile -ExecutionPolicy Bypass -File $probe -Dll (Join-Path $d32 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -Fixture $fixtureSrc -Out (Join-Path $d32 'out.txt') | Out-Null
    $t64 = if (Test-Path (Join-Path $d64 'out.txt')) { [IO.File]::ReadAllText((Join-Path $d64 'out.txt')) } else { '' }
    $t32 = if (Test-Path (Join-Path $d32 'out.txt')) { [IO.File]::ReadAllText((Join-Path $d32 'out.txt')) } else { '' }
    Check ('I01 a 32-bit process (BVE5) loads the DLL and writes exactly the same bytes as the 64-bit one: the stream and the SI0 lines (without scan timing and thread numbers) for Ecb / Smee / Cl (' + $t64 + ' | ' + $t32 + ')') (($t64 -match '^ptr=8 ') -and ($t32 -match '^ptr=4 ') -and (($t64 -replace '^ptr=\d+ ', '') -ceq ($t32 -replace '^ptr=\d+ ', '')) -and ($t64 -match 'lines=\d{3,}'))
}
else { Skip 'I01 (no 32-bit Windows PowerShell here)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"SCORING-OBSERVATION-SI0 PASS=$pass FAIL=$fail SKIP=$($script:skips)"
if ($fail -gt 0) { exit 1 } else { exit 0 }
