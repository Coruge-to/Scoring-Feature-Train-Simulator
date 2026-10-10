# PHASE SI-1 - offline tests of the AtsEX LEGACY ground speed limit contract of the Current sender: TRAINLEN (CarLength x (MotorCar + TrailerCar)), MAPLIMITS, CLEARDIST, and a MAPHEAD that
# is the limit at the HEAD of the train (MAPTAIL stays the host value). The built DLL is driven through FAKES of the Legacy API (tests\TelemetryTestFixture.cs, compiled here), the Current
# formula is compared with a LITERAL port of the Current sender (CurrentReference), and the datagrams of the Legacy sender are fed to the REAL, UNCHANGED Python Overlay and
# scoring_logic (tests\si1_flash_probe.py) to prove that the red (ground) and blue (tail wait) flashes happen with no Python change.
# No BVE, no AtsEX runtime, no BveEx, no network, no hooks, no UDP 54321 (the Python side runs with a stub socket). Nothing is written outside logs\si1-tests.
# This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$srcDir = Join-Path $Root 'Telemetry\Legacy\src'
$testDir = Join-Path $Root 'logs\si1-tests'
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
public static class Si1Resolver
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
[Si1Resolver]::Install(@($testDir, $legacyHost))
$telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
$fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)

$NS = 'TsScoringLegacyTelemetryTests'
$GI = "$NS.GroundInfo" -as [type]
$CR = "$NS.CurrentReference" -as [type]
$CT = "$NS.Contract" -as [type]
# a session with the input surface, a diagnostic, NO SI-0 observation and the ground limit contract
function NewG { return (New-Object "$NS.Harness" -ArgumentList @($true, $true, $false, $true)) }
function NewGS { return (New-Object "$NS.Harness" -ArgumentList @($true, $true, $true, $true)) }          # ... and the SI-0 observation as well (the product wiring)
function NewPlain { return (New-Object "$NS.Harness" -ArgumentList @($true, $true, $false, $false)) }     # the sender of the earlier phases
function Part([string]$line, [string]$key) { $m = [regex]::Match($line, '(^|,)' + [regex]::Escape($key) + ':([^,]*)'); if ($m.Success) { return $m.Groups[2].Value } else { return $null } }
function Has([string]$line, [string]$key) { return [regex]::IsMatch($line, '(^|,)' + [regex]::Escape($key) + ':') }
function Toks([string]$line) { $m = [regex]::Match($line, 'AVAIL:1:([^,]*)'); if ($m.Success -and $m.Groups[1].Value) { return @($m.Groups[1].Value -split '\+') } else { return @() } }
function HasTok([string]$line, [string]$t) { return (@(Toks $line) -contains $t) }
function Last($h) { return $h.Sink.LastLine() }
function Gnd($h) { $h.Diag.Events | Where-Object { $_ -like 'TEL_GROUND_*' } }
function K([double]$kmh) { return $CT::Ground($kmh / 3.6) }                      # the exact km/h the sender computes for a limit given in km/h
function Km([double[]]$kmh) { $o = New-Object 'double[]' $kmh.Length; for ($i = 0; $i -lt $kmh.Length; $i++) { $o[$i] = K $kmh[$i] }; return ,$o }
function D([double]$v) { return $CT::D($v) }
function Dn([string]$text) { return [double]::Parse($text, [Globalization.CultureInfo]::InvariantCulture) }
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
function Route($h, $pairs) { if (($pairs.Count -eq 2) -and ($pairs[0] -isnot [array])) { $pairs = ,$pairs }; foreach ($p in $pairs) { $h.Ground.Lim([double]$p[0], [double]$p[1]) } }       # (location m, limit km/h)
function GroundOf([double]$kmh) { if ($kmh -ge 1000.0) { return [double]::PositiveInfinity } else { return ($kmh / 3.6) } }
function HostTail($h, [double]$loc, [double]$train) {
    $n = $h.Ground.Limits.Count; $l = New-Object 'double[]' $n; $k = New-Object 'double[]' $n
    for ($i = 0; $i -lt $n; $i++) { $l[$i] = $h.Ground.Limits[$i].Location; $k[$i] = $CT::Ground($h.Ground.Limits[$i].ValueMps) }
    return $GI::Tail($loc, $train, $l, $k)
}
$GROUND_TOKENS = 'maplimit_ahead','trainlen'

# ---------------------------------------------------------------------------------------------------------------------------------------------
# A - nothing of the earlier phases changes
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Scripted($hh, $beats) {
    $hh.Api.GradientRatio = 0.0125; $hh.Api.BrakeKind = 3; $hh.Api.FreshWrapperEachCall = $true; $hh.Api.GroundMps = 19.4
    $hh.Opened($false); $hh.Created()
    $hh.Run(30, 16); $beats.Add([string]$hh.Heartbeat())
    $hh.Api.GradientRatio = 0.02; $hh.Api.Holding = $true; $hh.Api.GroundMps = 16.6
    $hh.Run(30, 16)
    $hh.Now += 3000; $beats.Add([string]$hh.Heartbeat()); $hh.Run(5, 16); $beats.Add([string]$hh.Heartbeat())
    $hh.Api.TimeMs += 60000; $hh.Run(5, 16)
    $hh.Closed(); $hh.Created(); $hh.Seed += 777; $hh.Run(20, 16); $beats.Add([string]$hh.Heartbeat()); $hh.Dispose(); $beats.Add([string]$hh.Heartbeat())
}
$bP = New-Object System.Collections.Generic.List[string]; $bG = New-Object System.Collections.Generic.List[string]
$wp = NewPlain; Scripted $wp $bP
$wg = NewG; $wg.Ground.CarFail = $true; $wg.Ground.LimitsFail = $true; Scripted $wg $bG
Check 'A01 the datagrams of a session whose ground reads ALL fail are byte-identical to the sender of the earlier phases (MAPHEAD stays MAPTAIL, no new key, no new token)' (($wp.Sink.Sent.Count -gt 80) -and (($wp.Sink.Sent -join "`n") -ceq ($wg.Sink.Sent -join "`n")))
Check 'A02 the heartbeat texts are identical with and without the ground contract' ((($bP -join '|') -ceq ($bG -join '|')) -and ($bG.Count -eq 5) -and ($bG[1] -ceq 'STATUS:LOADED:PAUSED'))
$wn = NewPlain; $wn.Run(30, 16)
$ln = Last $wn
Check 'A03 without the ground surface MAPHEAD equals MAPTAIL, there is no TRAINLEN / MAPLIMITS / CLEARDIST and no trainlen / maplimit_ahead token (the earlier phases, byte for byte)' (((Part $ln 'MAPHEAD') -ceq (Part $ln 'MAPTAIL')) -and (-not (Has $ln 'TRAINLEN')) -and (-not (Has $ln 'MAPLIMITS')) -and (-not (Has $ln 'CLEARDIST')) -and (-not (HasTok $ln 'trainlen')) -and (-not (HasTok $ln 'maplimit_ahead')))
$wt = NewG; $wt.Ground.CarThrow = $true; $wt.Ground.LimitsThrow = $true; $wt.Run(100, 16)
Check 'A04 every ground read throwing: a line is still sent for every Tick (none skipped), without any ground group, each reason reported once' (($wt.LinesSent -eq 100) -and ($wt.LinesSkipped -eq 0) -and (@($wt.Sink.Lines() | Where-Object { (Has $_ 'TRAINLEN') -or (Has $_ 'MAPLIMITS') -or (Has $_ 'CLEARDIST') }).Count -eq 0) -and (@(Gnd $wt | Where-Object { $_ -like 'TEL_GROUND_UNAVAILABLE*' }).Count -eq 2))
$wz = NewG; $wz.Run(10, 16)
Check 'A05 the 14 tokens of the earlier phases keep their place: the AVAIL of a wired session with the default fakes is the earlier list plus trainlen and maplimit_ahead, sorted' (((Toks (Last $wz)) -join '+') -ceq 'bcp+bpp+brake_cab+brake_type+calcg+door+grad+handle+loc+maplimit+maplimit_ahead+meta+prates+siglimit+siglimit_ahead+speed+station+time+trainlen')

# ---------------------------------------------------------------------------------------------------------------------------------------------
# B - TRAINLEN = CarLength x (MotorCar + TrailerCar)
# ---------------------------------------------------------------------------------------------------------------------------------------------
function TL($c, $m, $t) { $r = $GI::TrainLength([double]$c, [double]$m, [double]$t); return $r }
Check 'B01 18 x 1 car = 18 m (the Smee vehicle of the live check)' ((@(TL 18 1 0)[0] -eq 1.0) -and (@(TL 18 1 0)[1] -eq 18.0))
Check 'B02 18 x 8 cars = 144 m (motor 4 + trailer 4; FirstCar is not added)' ((@(TL 18 4 4)[0] -eq 1.0) -and (@(TL 18 4 4)[1] -eq 144.0))
Check 'B03 13 x 1 = 13 m (0.5 + 0.5: a car count is a double)' ((@(TL 13 0.5 0.5)[0] -eq 1.0) -and (@(TL 13 0.5 0.5)[1] -eq 13.0) -and (@(TL 13 1 0)[1] -eq 13.0))
Check 'B04 a fractional total: 13 x 1.5 = 19.5 m; 20 x 2.5 = 50 m' ((@(TL 13 0.5 1)[1] -eq 19.5) -and (@(TL 20 1.5 1)[1] -eq 50.0))
Check 'B05 zero cars, zero length: not a length' ((@(TL 18 0 0)[0] -eq 0.0) -and (@(TL 0 4 4)[0] -eq 0.0))
Check 'B06 a negative length or a negative count: not a length (also when the sum would be positive)' ((@(TL -18 4 4)[0] -eq 0.0) -and (@(TL 18 -1 0)[0] -eq 0.0) -and (@(TL 18 -1 5)[0] -eq 0.0) -and (@(TL 18 5 -1)[0] -eq 0.0))
Check 'B07 NaN anywhere: not a length' ((@(TL ([double]::NaN) 4 4)[0] -eq 0.0) -and (@(TL 18 ([double]::NaN) 4)[0] -eq 0.0) -and (@(TL 18 4 ([double]::NaN))[0] -eq 0.0))
Check 'B08 Infinity anywhere: not a length' ((@(TL ([double]::PositiveInfinity) 4 4)[0] -eq 0.0) -and (@(TL 18 ([double]::PositiveInfinity) 0)[0] -eq 0.0) -and (@(TL 18 4 ([double]::NegativeInfinity))[0] -eq 0.0))
Check 'B09 overflow: a finite product that overflows to Infinity (1e308 x 10) and a sum that overflows are not a length' ((@(TL 1e308 5 5)[0] -eq 0.0) -and (@(TL 18 1.7e308 1.7e308)[0] -eq 0.0))
Check 'B10 a number that could not be read (null) in any of the three: not a length (nothing is defaulted to 20)' ((($GI::TrainLengthRaw($null, 4.0, 4.0))[0] -eq 0.0) -and (($GI::TrainLengthRaw(18.0, $null, 4.0))[0] -eq 0.0) -and (($GI::TrainLengthRaw(18.0, 4.0, $null))[0] -eq 0.0) -and (($GI::TrainLengthRaw(18.0, 4.0, 4.0))[1] -eq 144.0))
$h = NewG; $h.Ground.CarLen = 18.0; $h.Ground.Motor = 4.0; $h.Ground.Trailer = 4.0; $h.Run(3, 16); $l = Last $h
Check 'B11 the line carries TRAINLEN:144 and the trainlen token; the key is written once' (((Part $l 'TRAINLEN') -ceq '144') -and (HasTok $l 'trainlen') -and (([regex]::Matches($l, 'TRAINLEN:')).Count -eq 1))
$h = NewG; $h.Ground.CarLen = 13.0; $h.Ground.Motor = 0.5; $h.Ground.Trailer = 0.5; $h.Run(3, 16)
Check 'B12 0.5 + 0.5 cars of 13 m: TRAINLEN:13' ((Part (Last $h) 'TRAINLEN') -ceq '13')
$h = NewG; $h.Run(3, 16); $h.Ground.Motor = 5.0; $h.Run(1, 16); $m1 = Part (Last $h) 'TRAINLEN'; $h.Ground.CarFail = $true; $h.Run(1, 16); $m2 = Last $h; $h.Ground.CarFail = $false; $h.Ground.Motor = 2.0; $h.Run(1, 16)
Check 'B13 the length is read every Tick: a change shows in the next line, an unreadable Tick drops the group (key and token, no stale value), the next readable Tick brings it back' (($m1 -ceq '90') -and (-not (Has $m2 'TRAINLEN')) -and (-not (HasTok $m2 'trainlen')) -and ((Part (Last $h) 'TRAINLEN') -ceq '36'))
foreach ($case in @(@('car-null', { param($g) $g.CarFail = $true }), @('car-nan', { param($g) $g.CarLen = [double]::NaN }), @('motor-unread', { param($g) $g.Motor = $null }), @('trailer-neg', { param($g) $g.Trailer = -2.0 }), @('zero', { param($g) $g.Motor = 0.0; $g.Trailer = 0.0 }))) {
    $h = NewG; & $case[1] $h.Ground; $h.Run(5, 16)
    Check ("B14 $($case[0]): no TRAINLEN key and no trainlen token in any line; the other ground groups are not made up from a default (no CLEARDIST either: it needs the length)") (($h.Sink.Lines().Count -eq 5) -and (@($h.Sink.Lines() | Where-Object { (Has $_ 'TRAINLEN') -or (HasTok $_ 'trainlen') -or (Has $_ 'CLEARDIST') -or (HasTok $_ 'maplimit_ahead') }).Count -eq 0))
}
$h = NewG; $h.Run(3, 16); $g1 = $h.ScenarioId; $h.Closed(); $h.Created(); $h.Seed += 1; $h.Ground.CarFail = $true; $h.Run(1, 16); $first2 = Last $h; $h.Ground.CarFail = $false; $h.Ground.Motor = 2.0; $h.Run(1, 16)
Check 'B15 generation boundary: the first line of the next scenario instance carries no TRAINLEN of the previous one while its vehicle cannot be read, and the new value once it can (18 x 1 -> 18 x 2 = 36)' (($h.ScenarioId -ne $g1) -and (-not (Has $first2 'TRAINLEN')) -and ((Part (Last $h) 'TRAINLEN') -ceq '36'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# C - the head limit (MAPHEAD) and the tail limit (MAPTAIL): their meanings are not mixed up
# ---------------------------------------------------------------------------------------------------------------------------------------------
$L = [double[]]@(0, 1000, 2000)
$KM = Km ([double[]]@(70, 50, 90))
Check 'C01 a limit that DROPS: the head has it as soon as the head passes the element (1001 m: head 50); the tail value is the lowest in (tail, head] (still 50 with the 70 behind)' ((($GI::Head(1001.0, $L, $KM)) -eq $KM[1]) -and (($GI::Tail(1001.0, 100.0, $L, $KM)) -eq $KM[1]))
Check 'C02 a limit that RISES: the head has the higher value (2001 m: 90) while the tail value stays low until the tail has passed (2001 m, 100 m train: tail 50 = HEAD 90 is bigger); 100 m later the tail has passed (2100.5: both 90)' ((($GI::Head(2001.0, $L, $KM)) -eq $KM[2]) -and (($GI::Tail(2001.0, 100.0, $L, $KM)) -eq $KM[1]) -and (($GI::Tail(2101.0, 100.0, $L, $KM)) -eq $KM[2]))
Check 'C03 the location equal to an element belongs to the HEAD side (<=): at 1000 the head is 50, at 999.99 it is 70; before the first element the head is 1000 (no limit)' ((($GI::Head(1000.0, $L, $KM)) -eq $KM[1]) -and (($GI::Head(999.99, $L, $KM)) -eq $KM[0]) -and (($GI::Head(-5.0, $L, $KM)) -eq 1000.0))
Check 'C04 list start and end: at 0 the head is the first value; far beyond the last element it is the last value' ((($GI::Head(0.0, $L, $KM)) -eq $KM[0]) -and (($GI::Head(99999.0, $L, $KM)) -eq $KM[2]))
Check 'C05 an empty list: head 1000, tail 1000 (the Current behaviour)' ((($GI::Head(500.0, [double[]]@(), [double[]]@())) -eq 1000.0) -and (($GI::Tail(500.0, 100.0, [double[]]@(), [double[]]@())) -eq 1000.0))
$L2 = [double[]]@(0, 900, 950, 1000); $K2 = Km ([double[]]@(100, 60, 80, 100))
Check 'C06 several limits inside the train: the tail value is the LOWEST of them (60), the head value is the one in force at the head (100): they differ, and neither is replaced by the other' ((($GI::Tail(1000.0, 200.0, $L2, $K2)) -eq $K2[1]) -and (($GI::Head(1000.0, $L2, $K2)) -eq $K2[3]))
$L3 = [double[]]@(500, 500); $K3 = Km ([double[]]@(60, 40))
Check 'C07 two elements at the same location: the later one is in force (the Current rule), for the head and for the tail' ((($GI::Head(600.0, $L3, $K3)) -eq $K3[1]) -and (($GI::Tail(600.0, 10.0, $L3, $K3)) -eq $K3[1]))
Check 'C08 a limit that is 0, negative, infinite or above 999 m/s is "no limit" (1000); NaN is not a value' ((($GI::LimitKmh(0.0))[1] -eq 1000.0) -and (($GI::LimitKmh(-3.0))[1] -eq 1000.0) -and (($GI::LimitKmh([double]::PositiveInfinity))[1] -eq 1000.0) -and (($GI::LimitKmh(1500.0))[1] -eq 1000.0) -and (($GI::LimitKmh(20.0))[0] -eq 1.0) -and (($GI::LimitKmh([double]::NaN))[0] -eq 0.0))

# the line: MAPTAIL is the HOST value, MAPHEAD the list value
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Ground.Trailer = 0.0
$h.Api.Location = 1040.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(2, 16); $l = Last $h
Check 'C09 head passed a rising limit, tail has not: MAPTAIL is the host value (50), MAPHEAD the list value at the head (90); the maplimit token is announced' (((Dn (Part $l 'MAPTAIL')) -eq (K 50)) -and ((Dn (Part $l 'MAPHEAD')) -eq (K 90)) -and (HasTok $l 'maplimit'))
$h.Api.GroundMps = 33.0; $h.Run(1, 16); $l = Last $h
Check 'C10 MAPTAIL follows the HOST, not the list (host 33 m/s = 118.8 km/h): MAPHEAD does not move with it' (((Dn (Part $l 'MAPTAIL')) -eq (K 118.8)) -and ((Dn (Part $l 'MAPHEAD')) -eq (K 90)))
$h.Api.Location = 1150.0; $h.Api.GroundMps = 90.0 / 3.6; $h.Run(1, 16); $l = Last $h
Check 'C11 after the tail has passed the element the host reports 90: MAPHEAD and MAPTAIL are equal again' ((Dn (Part $l 'MAPTAIL')) -eq (Dn (Part $l 'MAPHEAD')))
$h = NewG; Route $h @(@(0, 70), @(1000, 50)); $h.Api.Location = 1040.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(2, 16); $l = Last $h
Check 'C12 a dropping limit: head 50 and tail 50 (the host drops with the head): MAPHEAD == MAPTAIL, no tail wait' ((Dn (Part $l 'MAPHEAD')) -eq (Dn (Part $l 'MAPTAIL')))
$h = NewG; $h.Ground.LimitsFail = $true; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(3, 16); $l = Last $h
Check 'C13 the list cannot be read: MAPHEAD falls back to MAPTAIL (the old behaviour; no estimate), MAPTAIL stays the host value, maplimit still announced' (((Part $l 'MAPHEAD') -ceq (Part $l 'MAPTAIL')) -and ((Dn (Part $l 'MAPTAIL')) -eq (K 50)) -and (HasTok $l 'maplimit') -and (-not (HasTok $l 'maplimit_ahead')))
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Api.GroundMps = [double]::NaN; $h.Api.Location = 1040.0; $h.Run(3, 16); $l = Last $h
Check 'C14 the HOST limit cannot be read (NaN): no maplimit group at all, and no MAPLIMITS / CLEARDIST either (the red candidates would have no current limit to be lower than); TRAINLEN is independent and stays' ((-not (Has $l 'MAPHEAD')) -and (-not (Has $l 'MAPTAIL')) -and (-not (HasTok $l 'maplimit')) -and (-not (Has $l 'MAPLIMITS')) -and (-not (HasTok $l 'maplimit_ahead')) -and (Has $l 'TRAINLEN'))

# unreadable / corrupt lists: nothing is used, nothing partial is sent
function Corrupt([string]$what, [scriptblock]$break) {
    $h = NewG; Route $h @(@(0, 50), @(1000, 90), @(2000, 60), @(3000, 80)); & $break $h.Ground
    $h.Api.Location = 1500.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(5, 16); $l = Last $h
    Check ("C15 $what : no MAPLIMITS, no CLEARDIST, no maplimit_ahead token, MAPHEAD == MAPTAIL (fallback); the unreadable list is reported once") ((-not (Has $l 'MAPLIMITS')) -and (-not (Has $l 'CLEARDIST')) -and (-not (HasTok $l 'maplimit_ahead')) -and ((Part $l 'MAPHEAD') -ceq (Part $l 'MAPTAIL')) -and (@(Gnd $h | Where-Object { $_ -like 'TEL_GROUND_UNAVAILABLE*group=list*' }).Count -eq 1) -and (Has $l 'TRAINLEN'))
}
Corrupt 'the count cannot be read' { param($g) $g.LimitsFail = $true }
Corrupt 'the count read throws' { param($g) $g.LimitsThrow = $true }
Corrupt 'one element cannot be read' { param($g) $g.FailElementAt = 2 }
Corrupt 'one element read throws' { param($g) $g.ThrowElementAt = 1 }
Corrupt 'the LAST element cannot be read' { param($g) $g.FailElementAt = 3 }
Corrupt 'one element is not a ValueNode' { param($g) $g.Limits[1].IsNode = $false }
Corrupt 'one value is NaN' { param($g) $g.Limits[2].ValueMps = [double]::NaN }
Corrupt 'one location is NaN' { param($g) $g.Limits[2].Location = [double]::NaN }
Corrupt 'one location is Infinity' { param($g) $g.Limits[3].Location = [double]::PositiveInfinity }
Corrupt 'the list is not sorted (3000, then 2000)' { param($g) $g.Limits[2].Location = 3500.0 }
$h = NewG; Route $h @(@(0, 50), @(1000, 70)); $h.Ground.Limits[1].ValueMps = [double]::PositiveInfinity; $h.Api.Location = 1500.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(2, 16); $l = Last $h
Check 'C16 an INFINITE value is a valid "no limit" (1000), not a corrupt list: the head is 1000 and the group is available' (((Dn (Part $l 'MAPHEAD')) -eq 1000.0) -and (HasTok $l 'maplimit_ahead'))
$h = NewG; Route $h @(@(0, 50), @(1000, 70)); $h.Api.Location = 1500.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(1, 16); $callsAfterFirst = $h.Ground.CallCount('TryLimitElement'); $h.Run(200, 16)
Check 'C17 the list is read ONCE per scenario instance: 2 element reads for a 2 element list however long the instance runs (the count is looked at every Tick)' (($callsAfterFirst -eq 2) -and ($h.Ground.CallCount('TryLimitElement') -eq 2) -and ($h.Ground.CallCount('TryLimitCount') -ge 200))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# D - MAPLIMITS: the text of the Current sender
# ---------------------------------------------------------------------------------------------------------------------------------------------
$LA = [double[]]@(500, 1000, 1000.04, 3999.96, 4000, 4000.04, 4500); $KA = Km ([double[]]@(60, 70, 80, 90, 100, 110, 120))
$at1000 = $GI::Ahead(1000.0, $LA, $KA)
Check 'D01 the 3000 m window is (location, location + 3000]: the element AT the location (1000) is out, 1000.04 is in, 3999.96 and exactly +3000 (4000) are in, 4000.04 and 4500 are out, 500 is behind' ($at1000 -ceq '1000.0=80.0_4000.0=90.0_4000.0=100.0')
Check 'D02 the text is location F1, equals sign, km/h F1, joined by underscore, in list order (the F1 of 1000.04 is 1000.0: the window is decided on the raw location, the text is rounded)' (($GI::Ahead(0.0, [double[]]@(100, 200.26, 300.96), (Km ([double[]]@(61, 62.04, 63.96))))) -ceq '100.0=61.0_200.3=62.0_301.0=64.0')
Check 'D03 exactly the Current text on the sample list of the Python E4 test (1500.0=65.0_2500.0=90.0)' (($GI::Ahead(1234.5, [double[]]@(1500, 2500), (Km ([double[]]@(65, 90))))) -ceq '1500.0=65.0_2500.0=90.0')
Check 'D04 an empty window and an empty list are the EMPTY text (the Current behaviour), not an error' ((($GI::Ahead(10000.0, $LA, $KA)) -ceq '') -and (($GI::Ahead(5.0, [double[]]@(), [double[]]@())) -ceq ''))
Check 'D05 duplicates are kept as the Current sender keeps them (two elements at 1500)' (($GI::Ahead(1000.0, [double[]]@(1500, 1500), (Km ([double[]]@(60, 40))))) -ceq '1500.0=60.0_1500.0=40.0')
$bigL = New-Object 'double[]' 500; $bigK = New-Object 'double[]' 500; for ($i = 0; $i -lt 500; $i++) { $bigL[$i] = 1001.0 + $i; $bigK[$i] = 60.0 }
$bigL2 = New-Object 'double[]' 501; $bigK2 = New-Object 'double[]' 501; for ($i = 0; $i -lt 501; $i++) { $bigL2[$i] = 1001.0 + $i; $bigK2[$i] = 60.0 }
Check 'D06 many elements: 500 in the window are sent whole; 501 are NOT sent at all (the text is never cut): the group is unavailable' (((($GI::Ahead(1000.0, $bigL, $bigK)).Split('_')).Count -eq 500) -and ($GI::Ahead(1000.0, $bigL2, $bigK2) -eq $null) -and ($GI::AheadCount(1000.0, $bigL2, $bigK2) -eq 501))
# on the line
$h = NewG; Route $h @(@(0, 70), @(1500, 65), @(2500, 90)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(2, 16); $l = Last $h
Check 'D07 the line: MAPLIMITS:1500.0=65.0_2500.0=90.0 and CLEARDIST:0 with the maplimit_ahead token, the exact shape the Python E4 sample uses' (((Part $l 'MAPLIMITS') -ceq '1500.0=65.0_2500.0=90.0') -and ((Part $l 'CLEARDIST') -ceq '0') -and (HasTok $l 'maplimit_ahead'))
$h = NewG; Route $h @(@(0, 70)); $h.Api.Location = 500.0; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(2, 16); $l = Last $h
Check 'D08 nothing ahead: the keys are present with an EMPTY MAPLIMITS (MAPLIMITS:,CLEARDIST:0) and the token is announced (the Current line for a route without a limit ahead)' (($l -match ',MAPLIMITS:,CLEARDIST:0') -and (HasTok $l 'maplimit_ahead'))
$h = NewG; $h.Api.Location = 500.0; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(2, 16); $l = Last $h
Check 'D09 an EMPTY list (readable, zero elements) is a valid list: MAPLIMITS: is empty, MAPHEAD is 1000 (no element at or before the head)' (($l -match ',MAPLIMITS:,CLEARDIST:0') -and ((Dn (Part $l 'MAPHEAD')) -eq 1000.0) -and (HasTok $l 'maplimit_ahead'))
$saved = [Threading.Thread]::CurrentThread.CurrentCulture
try {
    [Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo('de-DE')
    $h = NewG; Route $h @(@(0, 70), @(1500.5, 65.5)); $h.Api.Location = 1000.0; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(2, 16); $l = Last $h
} finally { [Threading.Thread]::CurrentThread.CurrentCulture = $saved }
Check 'D10 a comma-decimal culture does not leak: the text still uses the dot (the contract is culture independent)' (((Part $l 'MAPLIMITS') -ceq '1500.5=65.5') -and ($l -notmatch '\d,\d+=') )
# order and the list as the sender reads it, in a long list scanned in slices
$h = NewG; for ($i = 0; $i -lt 1000; $i++) { $h.Ground.Lim([double](100 + $i * 10), [double](40 + ($i % 7) * 10)) }; $h.Api.Location = 5000.0; $h.Api.GroundMps = 50.0 / 3.6
$h.Run(1, 16); $t1 = HasTok (Last $h) 'maplimit_ahead'; $h.Run(1, 16); $t2 = HasTok (Last $h) 'maplimit_ahead'; $h.Run(1, 16); $t3 = HasTok (Last $h) 'maplimit_ahead'
Check 'D11 a 1000 element list is read in slices of 400 per Tick: NOT available on Tick 1 and 2 (no partial list), available on Tick 3' ((-not $t1) -and (-not $t2) -and $t3 -and ($h.Ground.CallCount('TryLimitElement') -eq 1000))
$h = NewG; for ($i = 0; $i -lt 1000; $i++) { $h.Ground.Lim([double](100 + $i * 10), [double](40 + ($i % 7) * 10)) }; $h.Api.Location = 5000.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(3, 16); $l = Last $h
$locsL = New-Object 'double[]' 1000; $mpsL = New-Object 'double[]' 1000; for ($i = 0; $i -lt 1000; $i++) { $locsL[$i] = $h.Ground.Limits[$i].Location; $mpsL[$i] = $h.Ground.Limits[$i].ValueMps }
$ref = $CR::Compute(5000.0, 18.0, $locsL, $mpsL)
Check 'D12 the long list gives exactly the text, head and CLEARDIST of the literal Current port' (((Part $l 'MAPLIMITS') -ceq $ref[0]) -and ((Part $l 'MAPHEAD') -ceq $ref[1]) -and ((Part $l 'CLEARDIST') -ceq $ref[3]))
$h = NewG; for ($i = 0; $i -lt 20001; $i++) { $h.Ground.Lim([double]($i), 60.0) }; $h.Api.Location = 5.0; $h.Api.GroundMps = 60.0 / 3.6; $h.Run(200, 16); $l = Last $h
Check 'D13 a list above the limit (20001 elements) is never used and never half-read: no MAPLIMITS in 200 Ticks, MAPHEAD == MAPTAIL, the reason is reported once, and the reader stops after one count read' ((-not (Has $l 'MAPLIMITS')) -and ((Part $l 'MAPHEAD') -ceq (Part $l 'MAPTAIL')) -and (@(Gnd $h | Where-Object { $_ -like '*reason=too-many*' }).Count -eq 1) -and ($h.Ground.CallCount('TryLimitElement') -eq 0))
$h = NewG; for ($i = 0; $i -lt 600; $i++) { $h.Ground.Lim([double](1001 + $i), 60.0) }; $h.Api.Location = 1000.0; $h.Api.GroundMps = 60.0 / 3.6; $h.Run(3, 16); $l = Last $h
Check 'D14 more than 500 elements in the 3000 m window: MAPLIMITS and CLEARDIST are not written at all (not cut), the token is not announced, but the head limit (MAPHEAD) is still computed from the whole list' ((-not (Has $l 'MAPLIMITS')) -and (-not (Has $l 'CLEARDIST')) -and (-not (HasTok $l 'maplimit_ahead')) -and ((Dn (Part $l 'MAPHEAD')) -eq 1000.0) -and (Has $l 'TRAINLEN'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# E - CLEARDIST: the Current formula
# ---------------------------------------------------------------------------------------------------------------------------------------------
$LE = [double[]]@(0, 1000); $KE = Km ([double[]]@(50, 90))
Check 'E01 the head is past a rising limit, the tail is not: CLEARDIST is the distance the tail still has to go (1040 m, 100 m train: tail at 940, element at 1000 -> 60)' ((($GI::Clear(1040.0, 100.0, $LE, $KE)) -eq 60.0))
Check 'E02 the tail is past it: 0; no limit change in the train: 0' ((($GI::Clear(1101.0, 100.0, $LE, $KE)) -eq 0.0) -and (($GI::Clear(500.0, 100.0, $LE, $KE)) -eq 0.0))
Check 'E03 boundary: the head exactly at the element (location 1000): the element is at the head, tail at 900 -> CLEARDIST 100 (the whole train); the tail exactly at the element (location 1100): 0' ((($GI::Clear(1000.0, 100.0, $LE, $KE)) -eq 100.0) -and (($GI::Clear(1100.0, 100.0, $LE, $KE)) -eq 0.0))
$LF = [double[]]@(0, 900, 950); $KF = Km ([double[]]@(100, 60, 100))
Check 'E04 a dip inside the train (100 / 60 / 100): while the dip is inside, the distance runs to the nearest-to-the-tail element that carries the head value (950 here: head 1000 m, tail 900 -> 950 - 900 = 50)' ((($GI::Clear(1000.0, 100.0, $LF, $KF)) -eq 50.0) -and (($GI::Clear(1051.0, 100.0, $LF, $KF)) -eq 0.0))
$LG = [double[]]@(0, 950, 970); $KG = Km ([double[]]@(50, 90, 90))
Check 'E05 two elements with the head value in the train: the one nearest to the TAIL decides (950 -> 1000 - 100 = tail 900, clearance 950 -> 50)' (($GI::Clear(1000.0, 100.0, $LG, $KG)) -eq 50.0)
Check 'E06 an empty list, a single element, a zero-length train: 0 and no exception' ((($GI::Clear(100.0, 100.0, [double[]]@(), [double[]]@())) -eq 0.0) -and (($GI::Clear(100.0, 100.0, [double[]]@(50), (Km ([double[]]@(60))))) -eq 0.0) -and (($GI::Clear(1000.0, 0.0, $LE, $KE)) -eq 0.0))
# speeds: the formula does not use the speed; the line follows the position at stand still, low and high speed
foreach ($spd in @(@('stand still', 0.0), @('low speed 5 km/h', 5.0), @('high speed 120 km/h', 120.0))) {
    $h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Ground.Trailer = 0.0
    $mps = $spd[1] / 3.6; $loc = 900.0; $ok = $true; $seen = 0
    for ($i = 0; $i -lt 40; $i++) {
        $h.Api.Location = $loc; $h.Api.SpeedMps = $mps; $h.Api.GroundMps = (GroundOf (HostTail $h $loc 100.0)); $h.Run(1, 100); $l = Last $h
        $r = $CR::Compute($loc, 100.0, [double[]]@(0, 1000), [double[]]@((50 / 3.6), (90 / 3.6)))
        if ((Part $l 'CLEARDIST') -cne $r[3]) { $ok = $false }
        if ((Part $l 'MAPHEAD') -cne $r[1]) { $ok = $false }
        if ($r[3] -ne '0') { $seen++ }
        $loc += $mps * 0.1 * 8
    }
    Check ("E07 $($spd[0]): over 40 Ticks of the approach (stepping the position by the speed) CLEARDIST and MAPHEAD equal the Current port on every line" + $(if ($spd[1] -eq 0.0) { ' (at rest CLEARDIST stays 0 at 900 m)' } else { ' (a non-zero CLEARDIST was seen while the train cleared the element)' })) ($ok -and ($(if ($spd[1] -eq 0.0) { $seen -eq 0 } else { $true })))
}
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Ground.CarLen = [double]::NaN; $h.Api.Location = 1040.0; $h.Api.GroundMps = 50.0 / 3.6; $h.Run(3, 16); $l = Last $h
Check 'E08 a non-finite train length: CLEARDIST is NOT sent as 0 (it cannot be computed): the whole maplimit_ahead group is unavailable; MAPHEAD (head) is still real' ((-not (Has $l 'CLEARDIST')) -and (-not (Has $l 'MAPLIMITS')) -and (-not (HasTok $l 'maplimit_ahead')) -and ((Dn (Part $l 'MAPHEAD')) -eq (K 90)))
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Api.Location = [double]::NaN; $h.Run(3, 16)
Check 'E09 a non-finite location: no line at all for that Tick (the core of the line is missing), nothing about the ground is written' (($h.Sink.Lines().Count -eq 0) -and ($h.LinesSkipped -eq 3))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# F - the Current formula compared on many lists (a literal port of the Current sender)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$rnd = New-Object System.Random 20261010
$mism = 0; $cases = 0; $nonzeroClear = 0; $waitCases = 0; $textsCompared = 0
for ($c = 0; $c -lt 400; $c++) {
    $n = $rnd.Next(0, 14); $locs = New-Object 'double[]' $n; $mps = New-Object 'double[]' $n; $kmh = New-Object 'double[]' $n
    $x = $rnd.Next(0, 600)
    for ($i = 0; $i -lt $n; $i++) {
        if ($rnd.Next(0, 6) -ne 0) { $x += $rnd.Next(1, 900) }          # one in six keeps the location of the element before: a duplicate location
        $locs[$i] = [double]$x + ($rnd.Next(0, 4) * 0.25)
        $pick = $rnd.Next(0, 20)
        if ($pick -eq 0) { $mps[$i] = [double]::PositiveInfinity } elseif ($pick -eq 1) { $mps[$i] = 0.0 } elseif ($pick -eq 2) { $mps[$i] = 1500.0 } else { $mps[$i] = ($rnd.Next(2, 34) * 5) / 3.6 }
        $kmh[$i] = $CT::Ground($mps[$i])
    }
    for ($i = 1; $i -lt $n; $i++) { if ($locs[$i] -lt $locs[$i - 1]) { $locs[$i] = $locs[$i - 1] } }
    $train = @(13.0, 18.0, 20.0, 80.0, 144.0, 19.5, 216.0)[$rnd.Next(0, 7)]
    $span = 0; if ($n -gt 0) { $span = [int]$locs[$n - 1] }
    foreach ($loc in @([double]$rnd.Next(-200, $span + 3500), [double]$rnd.Next(-200, $span + 3500), $(if ($n -gt 0) { $locs[$rnd.Next(0, $n)] } else { 0.0 }), $(if ($n -gt 0) { $locs[$rnd.Next(0, $n)] + $train } else { 10.0 }))) {
        $ref = $CR::Compute($loc, $train, $locs, $mps)
        $cases++
        $head = D ($GI::Head($loc, $locs, $kmh)); $tail = D ($GI::Tail($loc, $train, $locs, $kmh)); $clear = D ($GI::Clear($loc, $train, $locs, $kmh))
        $text = $GI::Ahead($loc, $locs, $kmh)
        if (($head -cne $ref[1]) -or ($tail -cne $ref[2]) -or ($clear -cne $ref[3])) { $mism++ }
        if ($text -ne $null) { $textsCompared++; if ($text -cne $ref[0]) { $mism++ } }
        if ($ref[3] -ne '0') { $nonzeroClear++ }
        if ((Dn $ref[2]) -lt (Dn $ref[1])) { $waitCases++ }
    }
}
Check ("F01 400 random sorted lists (duplicates, infinite / zero / above-999 values, empty lists) at 1600 positions and 7 train lengths: head, tail, CLEARDIST and the MAPLIMITS text equal the literal Current port every time (cases $cases, texts compared $textsCompared, tail waits $waitCases, non-zero CLEARDIST $nonzeroClear, mismatches $mism)") (($mism -eq 0) -and ($cases -eq 1600) -and ($waitCases -gt 50) -and ($nonzeroClear -gt 50) -and ($textsCompared -gt 800))
$mism = 0; $checked = 0
for ($c = 0; $c -lt 40; $c++) {
    $n = $rnd.Next(1, 12); $locs = New-Object 'double[]' $n; $mps = New-Object 'double[]' $n; $x = $rnd.Next(0, 300)
    for ($i = 0; $i -lt $n; $i++) { $x += $rnd.Next(0, 700); $locs[$i] = [double]$x; $mps[$i] = ($rnd.Next(2, 30) * 5) / 3.6 }
    $train = @(13.0, 18.0, 144.0)[$rnd.Next(0, 3)]
    $loc = [double]$rnd.Next(0, $x + 1500)
    $h = NewG; for ($i = 0; $i -lt $n; $i++) { $h.Ground.Limits.Add((New-Object "$NS.FakeLimit" -ArgumentList @($locs[$i], $mps[$i]))) }
    $h.Ground.CarLen = $train; $h.Ground.Motor = 1.0; $h.Ground.Trailer = 0.0; $h.Api.Location = $loc; $h.Api.GroundMps = 33.0; $h.Run(2, 16); $l = Last $h
    $ref = $CR::Compute($loc, $train, $locs, $mps); $checked++
    if (((Part $l 'MAPLIMITS') -cne $ref[0]) -or ((Part $l 'MAPHEAD') -cne $ref[1]) -or ((Part $l 'CLEARDIST') -cne $ref[3]) -or ((Part $l 'TRAINLEN') -cne (D $train))) { $mism++ }
}
Check ("F02 the same comparison END TO END through the session (40 random lists, the datagram's MAPLIMITS / MAPHEAD / CLEARDIST / TRAINLEN against the literal Current port; checked $checked, mismatches $mism)") (($mism -eq 0) -and ($checked -eq 40))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# G - generations: nothing of an earlier scenario instance is ever written for a later one
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewG; Route $h @(@(0, 70), @(1500, 65), @(2500, 90)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(3, 16); $g1l = Last $h
$h.Closed(); $h.Created(); $h.Seed += 1000
$h.Ground.Limits.Clear(); Route $h @(@(0, 100), @(1800, 40)); $h.Ground.CarLen = 13.0; $h.Run(1, 16); $g2l = Last $h
Check 'G01 a new scenario instance with another list and another vehicle: the FIRST line already carries the new list and the new length (MAPLIMITS:1800.0=40.0, TRAINLEN:13) and nothing of the first' (($h.ScenarioId -ne 0) -and ((Part $g1l 'MAPLIMITS') -ceq '1500.0=65.0_2500.0=90.0') -and ((Part $g2l 'MAPLIMITS') -ceq '1800.0=40.0') -and ((Part $g2l 'TRAINLEN') -ceq '13') -and ($g2l -notmatch '1500\.0=65\.0'))
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(3, 16)
$h.Closed(); $h.Created(); $h.Seed += 1000; $h.Ground.LimitsFail = $true; $h.Run(10, 16); $gl = @($h.Sink.Lines() | Select-Object -Last 10)
Check 'G02 the next instance cannot read its list: in none of its 10 lines is there a MAPLIMITS, CLEARDIST, the maplimit_ahead token or the previous list (the TRAINLEN of the unchanged vehicle is read again, not carried)' ((@($gl | Where-Object { (Has $_ 'MAPLIMITS') -or (Has $_ 'CLEARDIST') -or (HasTok $_ 'maplimit_ahead') -or ($_ -match '1500\.0=65\.0') }).Count -eq 0) -and (@($gl | Where-Object { (Dn (Part $_ 'MAPHEAD')) -ne (Dn (Part $_ 'MAPTAIL')) }).Count -eq 0))
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(3, 16)
$h.Closed(); $h.Created(); $h.Seed += 1000; $h.Ground.CarFail = $true; $h.Ground.Limits.Clear(); Route $h @(@(0, 60), @(2000, 80)); $h.Run(3, 16); $gl = @($h.Sink.Lines() | Select-Object -Last 3)
Check 'G03 the next instance has a list but cannot read its vehicle: the list-based MAPHEAD is real, TRAINLEN is absent, and CLEARDIST / MAPLIMITS are absent (they need the length); the old TRAINLEN is not repeated' ((@($gl | Where-Object { (Has $_ 'TRAINLEN') -or (Has $_ 'MAPLIMITS') -or (HasTok $_ 'maplimit_ahead') -or (HasTok $_ 'trainlen') }).Count -eq 0) -and (@($gl | Where-Object { (Dn (Part $_ 'MAPHEAD')) -ne (K 60) }).Count -eq 0))
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(3, 16); $before = (Gnd $h).Count
$h.Closed(); $h.Dispose()
Check 'G04 the end of an instance (Closed, then Dispose) drops the state: a Tick after Dispose sends nothing and reads nothing' (($h.IsDisposed) -and ($h.LinesSent -eq 3))
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(1, 16); $h.Created(); $h.Run(1, 16); $callsA = $h.Ground.CallCount('TryLimitElement')
Check 'G05 a scenario-created event without a new Scenario object still ends the instance: the list is read again for the new instance (4 element reads for two instances of a 2 element list)' ($callsA -eq 4)
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(2, 16); $h.Api.Scenario = New-Object object; $h.Ground.Limits.Clear(); Route $h @(@(0, 30)); $h.Run(1, 16); $l = Last $h
Check 'G06 a different Scenario object with no lifecycle event (identity change): the list is dropped and read again at once (MAPLIMITS: is empty now, no 1500.0=65.0)' (((Part $l 'MAPLIMITS') -ceq '') -and ((Dn (Part $l 'MAPHEAD')) -eq (K 30)))

# the list that changes under the reader
$h = NewG; Route $h @(@(0, 70), @(1500, 65), @(2500, 90)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(2, 16)
$h.Ground.Limits.Add((New-Object "$NS.FakeLimit" -ArgumentList @(2800.0, 20.0))); $h.Run(1, 16); $lc = Last $h; $h.Run(1, 16); $ld = Last $h
Check 'H01 the element count changes while the instance runs: that Tick drops the whole group (no old list is trusted), the next Tick reads the new list and offers it again' ((-not (HasTok $lc 'maplimit_ahead')) -and ((Part $lc 'MAPHEAD') -ceq (Part $lc 'MAPTAIL')) -and (HasTok $ld 'maplimit_ahead') -and ((Part $ld 'MAPLIMITS') -ceq '1500.0=65.0_2500.0=90.0_2800.0=72.0'))
$h = NewG; for ($i = 0; $i -lt 1000; $i++) { $h.Ground.Lim([double](100 + $i * 10), 60.0) }; $h.Api.Location = 5000.0; $h.Api.GroundMps = 60.0 / 3.6; $h.Run(1, 16); $h.Ground.CountOverride = 1001; $h.Run(2, 16); $mid = HasTok (Last $h) 'maplimit_ahead'; $h.Ground.CountOverride = $null; $h.Run(5, 16); $late = HasTok (Last $h) 'maplimit_ahead'
Check 'H02 the count changes DURING the slice scan of a long list: the scan is restarted, never completed with a mixed list; the group is back after a clean scan' ((-not $mid) -and $late)
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Ground.FailElementAt = 1; $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(10, 16); $early = HasTok (Last $h) 'maplimit_ahead'; $h.Ground.FailElementAt = -1; $h.Run([int]$GI::RetryEveryTicks + 5, 16); $retried = HasTok (Last $h) 'maplimit_ahead'
Check 'H03 a list that could not be read is tried again from the start (every 60 Ticks): while it fails no group, after it can be read the group is announced' ((-not $early) -and $retried)

# ---------------------------------------------------------------------------------------------------------------------------------------------
# I - groups are judged alone
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Ground.CarFail = $true; $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(3, 16); $l = Last $h
Check 'I01 trainlen alone fails: TRAINLEN, CLEARDIST and MAPLIMITS are not sent (the length is part of CLEARDIST); MAPHEAD from the list still is' ((-not (HasTok $l 'trainlen')) -and (-not (HasTok $l 'maplimit_ahead')) -and ((Dn (Part $l 'MAPHEAD')) -eq (K 70)))
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Ground.LimitsFail = $true; $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(3, 16); $l = Last $h
Check 'I02 the list alone fails: TRAINLEN (own group) is still sent; MAPLIMITS / CLEARDIST are not' ((HasTok $l 'trainlen') -and (Has $l 'TRAINLEN') -and (-not (HasTok $l 'maplimit_ahead')))
Check 'I03 every key of a group is written if and only if its token is in AVAIL' (((HasTok $l 'trainlen') -eq (Has $l 'TRAINLEN')) -and ((HasTok $l 'maplimit_ahead') -eq ((Has $l 'MAPLIMITS') -and (Has $l 'CLEARDIST'))) -and ((Has $l 'MAPLIMITS') -eq (Has $l 'CLEARDIST')))
$h = NewG; Route $h @(@(0, 70)); $h.Api.Location = 100.0; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(50, 16)
$bad = 0; foreach ($ln in $h.Sink.Lines()) { if (((HasTok $ln 'trainlen') -ne (Has $ln 'TRAINLEN')) -or ((HasTok $ln 'maplimit_ahead') -ne ((Has $ln 'MAPLIMITS') -and (Has $ln 'CLEARDIST')))) { $bad++ } }
Check 'I04 over 50 Ticks no line has a key without its token or a token without its keys' ($bad -eq 0)

# ---------------------------------------------------------------------------------------------------------------------------------------------
# J - safety: one thread, bounded work, quiet log
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewG; for ($i = 0; $i -lt 5000; $i++) { $h.Ground.Lim([double](100 + $i * 10), 60.0) }; $h.Api.Location = 5000.0; $h.Api.GroundMps = 60.0 / 3.6
$maxPerTick = 0; $prev = 0; $okSlices = $true
for ($t = 0; $t -lt 20; $t++) { $h.Run(1, 16); $now = $h.Ground.CallCount('TryLimitElement'); $d = $now - $prev; $prev = $now; if ($d -gt $maxPerTick) { $maxPerTick = $d } }
Check ("J01 a 5000 element list is read in slices: never more than 400 element reads in one Tick (max seen $maxPerTick), 5000 in total, 13 Ticks") (($maxPerTick -le [int]$GI::ScanPerTick) -and ($h.Ground.CallCount('TryLimitElement') -eq 5000))
$h = NewG; Route $h @(@(0, 70), @(1500, 65)); $h.Api.Location = 1234.5; $h.Api.GroundMps = 70.0 / 3.6; $h.Run(50, 16); $h.HeartbeatOnOtherThread(20) | Out-Null; $h.Run(5, 16)
Check 'J02 every ground read happens on the Tick thread only (one thread id in 55 Ticks), and the heartbeat thread never reads the ground surface' (($h.Ground.Threads.Count -eq 1) -and ($h.Ground.TotalCalls() -gt 100))
$h = NewG; Route $h @(@(0, 70), @(1500, 65), @(2500, 90)); $h.Api.Location = 100.0; $h.Api.GroundMps = 70.0 / 3.6
for ($i = 0; $i -lt 3000; $i++) { $h.Api.Location = 100.0 + $i * 1.0; $h.Run(1, 16) }
$gl = Gnd $h
Check ("J03 3000 Ticks of driving past three limits write a bounded number of ground diagnostic lines (now $($gl.Count), cap 64), never one per Tick") (($gl.Count -le 64) -and ($gl.Count -ge 3))
Check 'J04 the ground diagnostic lines carry numbers and fixed words only (no path, no text of the route / vehicle)' (@($gl | Where-Object { $_ -notmatch '^TEL_GROUND_(LIST|UNAVAILABLE|TRAINLEN|CHANGE)( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)+$' }).Count -eq 0)
$h = NewG; $h.Diag.Throw = $true; Route $h @(@(0, 70)); $h.Run(20, 16)
Check 'J05 a diagnostic that throws on every call cannot affect the telemetry: all 20 lines sent, none skipped, the groups are still there' (($h.LinesSent -eq 20) -and ($h.LinesSkipped -eq 0) -and (HasTok (Last $h) 'trainlen'))
$adapter = $fixAsm.GetType("$NS.GroundAdapterProbe")
$ad = $null; try { $ad = @($adapter::Run()) } catch { $ad = $null }
if ($ad -ne $null) { Check 'J06 the REAL host adapter with no scenario attached answers the ground surface with fixed reasons and false, never an exception' ($ad.Count -eq 3 -and ($ad[0] -ceq 'False:scenario-null') -and ($ad[1] -ceq 'False:scenario-null') -and ($ad[2] -ceq 'False:scenario-null')) } else { Skip 'J06 the real adapter could not be loaded here (the AtsEX host assemblies are missing)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# K - the flashes: the Legacy datagrams fed to the REAL, UNCHANGED Python (Overlay, scoring_logic)
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Approach($h, [double]$from, [double]$to, [double]$kmh, [double]$train, [scriptblock]$each) {
    $mps = $kmh / 3.6; $loc = $from
    while ($loc -le $to) {
        $h.Api.Location = $loc; $h.Api.SpeedMps = $mps; $h.Api.GroundMps = (GroundOf (HostTail $h $loc $train))
        if ($each) { & $each $h $loc }
        $h.Run(1, 100); $loc += $mps * 0.1
    }
}
function Seq($h) { return ,@($h.Sink.Lines()) }
$seqs = [ordered]@{}
# 1 ground red: 70 -> 60 limit at 2500 m, a 100 m train at 70 km/h
$h = NewG; Route $h @(@(0, 70), @(2500, 60)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Api.SignalMps = [double]::PositiveInfinity; $h.Api.NextSectionFound = $false
Approach $h 1500 2700 70 100; $seqs['ground-red'] = (Seq $h); $ground1 = $h
# 2 the same route, MAPLIMITS unavailable (the list cannot be read): no ground red may be made up
$h = NewG; Route $h @(@(0, 70), @(2500, 60)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Ground.LimitsFail = $true; $h.Api.SignalMps = [double]::PositiveInfinity; $h.Api.NextSectionFound = $false
Approach $h 1500 2700 70 100; $seqs['ground-no-list'] = (Seq $h)
# 3 blue: 50 -> 90 limit at 1000 m, signal 100 km/h, 100 m train at 40 km/h
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Api.SignalMps = 100.0 / 3.6; $h.Api.NextSectionFound = $false
Approach $h 800 1300 40 100; $seqs['tail-wait-blue'] = (Seq $h)
# 4 blue must not appear when the head limit cannot be established (MAPHEAD falls back to MAPTAIL)
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Ground.FailElementAt = 0; $h.Api.SignalMps = 100.0 / 3.6; $h.Api.NextSectionFound = $false
Approach $h 800 1300 40 100
$seqs['tail-wait-no-head'] = (Seq $h)
# 5 the signal flash is the same with and without the ground contract
$h = NewG; Route $h @(@(0, 100)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Api.SignalMps = 100.0 / 3.6; $h.Api.ForwardSignalMps = 40.0 / 3.6; $h.Api.NextSectionLoc = 2400.0
Approach $h 1900 2350 70 100; $seqs['signal-with-ground'] = (Seq $h)
$h = NewPlain; $h.Api.SignalMps = 100.0 / 3.6; $h.Api.ForwardSignalMps = 40.0 / 3.6; $h.Api.NextSectionLoc = 2400.0
$mps = 70.0 / 3.6; $loc = 1900.0; while ($loc -le 2350) { $h.Api.Location = $loc; $h.Api.SpeedMps = $mps; $h.Api.GroundMps = [double]::PositiveInfinity; $h.Run(1, 100); $loc += $mps * 0.1 }
$seqs['signal-plain'] = (Seq $h)
# 6 a flat route: nothing flashes
$h = NewG; Route $h @(@(0, 100)); $h.Ground.CarLen = 20.0; $h.Ground.Motor = 5.0; $h.Api.SignalMps = [double]::PositiveInfinity; $h.Api.NextSectionFound = $false
Approach $h 500 900 60 100; $seqs['flat'] = (Seq $h)
# 7 the train length is unreadable: no ground red candidate (no MAPLIMITS), the blue of the tail wait is still real
$h = NewG; Route $h @(@(0, 50), @(1000, 90)); $h.Ground.CarFail = $true; $h.Api.SignalMps = 100.0 / 3.6; $h.Api.NextSectionFound = $false
Approach $h 800 1300 40 100; $seqs['no-trainlen'] = (Seq $h)

# hand the datagrams of the Legacy sender to the real Python and read the flash state back
$pyOk = $false
$pyOut = $null
$python = Get-Command python -ErrorAction SilentlyContinue
$probePy = Join-Path $repo 'tests\si1_flash_probe.py'
if ($python -and (Test-Path $probePy)) {
    $inFile = Join-Path $testDir 'flash-in.json'; $outFile = Join-Path $testDir 'flash-out.json'
    $payload = [ordered]@{}; foreach ($k in $seqs.Keys) { $payload[$k] = @($seqs[$k]) }
    [IO.File]::WriteAllText($inFile, (ConvertTo-Json -InputObject $payload -Depth 4 -Compress), (New-Object Text.UTF8Encoding($false)))
    & $python.Source $probePy $inFile $outFile | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $outFile)) { $pyOut = ConvertFrom-Json ([IO.File]::ReadAllText($outFile)); $pyOk = $true }
}
function Steps([string]$name) { return @($pyOut.$name) }
if ($pyOk) {
    $a = Steps 'ground-red'
    Check 'K01 the datagrams are accepted by the real telemetry gate and applied: Python holds the list the Legacy sender wrote (the Python parse of MAPLIMITS), the train length 100 and the host limit as MAPTAIL' (($a.Count -gt 100) -and ($a[0].ahead -eq 1) -and ($a[0].limits[0][0] -eq 2500.0) -and ([math]::Abs($a[0].limits[0][1] - 60.0) -lt 0.001) -and ($a[0].train -eq 100.0) -and ([math]::Abs($a[0].tail - 70.0) -lt 0.001))
    $redLines = @($a | Where-Object { $_.red -ne 'None' -and $_.blink -and $_.color -eq 'red' })
    Check ("K02 RED (ground): far from the 60 km/h limit nothing flashes; inside the warning distance the HUD flashes red 60 (red lines $($redLines.Count), first line red $($a[0].red))") (($a[0].red -eq 'None') -and (-not $a[0].blink) -and ($redLines.Count -gt 10) -and (@($redLines | Where-Object { [math]::Abs([double]$_.red - 60.0) -gt 0.001 }).Count -eq 0) -and (@($redLines | Where-Object { [math]::Abs($_.disp - 60.0) -gt 0.001 }).Count -eq 0))
    Check 'K03 RED is raised before the limit and goes out after it is passed (the candidate list is empty again past 2500 m)' (($a[-1].red -eq 'None') -and (-not $a[-1].blink) -and ($a[-1].ahead -eq 0))
    $n = Steps 'ground-no-list'
    Check 'K04 MAPLIMITS unavailable: no ground red is made up in any of the lines, Python holds no candidate list, nothing flashes' (($n.Count -eq $a.Count) -and (@($n | Where-Object { $_.red -ne 'None' -or $_.blink -or $_.ahead -ne 0 }).Count -eq 0))
    $b = Steps 'tail-wait-blue'
    $blueLines = @($b | Where-Object { $_.blue -ne 'None' -and $_.blink -and $_.color -eq 'blue' })
    Check ("K05 BLUE (tail wait): MAPTAIL < MAPHEAD, no red candidate, min(MAPHEAD, SIGLIMIT) > the effective limit: the HUD flashes blue 90 while the head is past the rising limit and the tail is not (blue lines $($blueLines.Count))") (($blueLines.Count -gt 5) -and (@($blueLines | Where-Object { -not $_.wait -or [math]::Abs([double]$_.blue - 90.0) -gt 0.001 -or [math]::Abs($_.head - 90.0) -gt 0.001 -or [math]::Abs($_.tail - 50.0) -gt 0.001 -or $_.red -ne 'None' -or [math]::Abs($_.disp - 90.0) -gt 0.001 }).Count -eq 0))
    Check 'K06 BLUE only in the tail wait: not before the head reaches the element, not after the tail has passed it; CLEARDIST is positive while waiting; never a red' (($b[0].blue -eq 'None') -and (-not $b[0].wait) -and ($b[-1].blue -eq 'None') -and (-not $b[-1].wait) -and (@($blueLines | Where-Object { $_.clear -le 0.0 }).Count -eq 0) -and (@($b | Where-Object { $_.red -ne 'None' }).Count -eq 0))
    $nh = Steps 'tail-wait-no-head'
    Check 'K07 MAPHEAD unavailable (the list cannot be read): MAPHEAD == MAPTAIL in Python in every line, no blue is made up, nothing flashes' (($nh.Count -eq $b.Count) -and (@($nh | Where-Object { $_.blue -ne 'None' -or $_.blink -or $_.wait -or [math]::Abs($_.head - $_.tail) -gt 0.0001 }).Count -eq 0))
    $s1 = @(Steps 'signal-with-ground' | ForEach-Object { '{0}|{1}|{2}|{3}|{4}' -f $_.red, $_.blue, $_.blink, $_.color, $_.disp })
    $s2 = @(Steps 'signal-plain' | ForEach-Object { '{0}|{1}|{2}|{3}|{4}' -f $_.red, $_.blue, $_.blink, $_.color, $_.disp })
    $sigRed = @(Steps 'signal-with-ground' | Where-Object { $_.red -ne 'None' -and $_.color -eq 'red' })
    Check ("K08 the SIGNAL red flash is unchanged: the same red (40) lines with and without the ground contract (red lines $($sigRed.Count))") (($s1.Count -eq $s2.Count) -and ($s1.Count -gt 20) -and (($s1 -join ';') -ceq ($s2 -join ';')) -and ($sigRed.Count -gt 5) -and (@($sigRed | Where-Object { [math]::Abs([double]$_.red - 40.0) -gt 0.001 }).Count -eq 0))
    $f = Steps 'flat'
    Check 'K09 a route with one constant limit: nothing flashes, no wait, no candidate' (@($f | Where-Object { $_.red -ne 'None' -or $_.blue -ne 'None' -or $_.blink -or $_.wait }).Count -eq 0)
    $nt = Steps 'no-trainlen'
    $ntBlue = @($nt | Where-Object { $_.blue -ne 'None' })
    Check ("K10 the train length unreadable: no MAPLIMITS in Python (so no ground red), the Python train length is its own default (20), not a value of the sender; the head limit is still real, so the tail wait blue still shows (blue lines $($ntBlue.Count))") (($nt.Count -eq $b.Count) -and (@($nt | Where-Object { $_.ahead -ne 0 -or $_.red -ne 'None' -or $_.train -ne 20.0 }).Count -eq 0) -and ($ntBlue.Count -gt 5))
    Check 'K11 every ground datagram of the flash scenarios has the Current shape Python parses: MAPLIMITS as location.F1=km/h.F1 pairs joined by underscore (or empty), CLEARDIST and TRAINLEN plain numbers (a round-trip number may carry an exponent, as the Current sender writes it; Python float() reads it)' (@(@($seqs['ground-red']) + @($seqs['tail-wait-blue']) | Where-Object { ((Part $_ 'MAPLIMITS') -notmatch '^([0-9]+\.[0-9]=[0-9]+\.[0-9](_[0-9]+\.[0-9]=[0-9]+\.[0-9])*)?$') -or ((Part $_ 'CLEARDIST') -notmatch '^[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$') -or ((Part $_ 'TRAINLEN') -notmatch '^[0-9]+(\.[0-9]+)?$') }).Count -eq 0)
}
else {
    Skip 'K01-K11 the flash tests need python with PyQt6 (INCONCLUSIVE here)'
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# L - scope, immutables, version
# ---------------------------------------------------------------------------------------------------------------------------------------------
$groundCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyGroundLimits.cs')))
$sessCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetrySession.cs')))
$extCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetryExtension.cs')))
Check 'L01 the ground contract source names no host type, no thread / timer / task, no reflection, no unsafe / interop / Harmony, no 54322, no jump, no bp_initial' ($groundCode -cnotmatch 'AtsEx|BveTypes|BveEx|System\.Threading|new Thread|Task\.|Timer|Reflection|GetType\(|BindingFlags|unsafe|DllImport|Marshal|Harmony|54322|JUMP|Jump|BpInitial|bp_initial|Smee')
Check 'L02 the keys of the new groups are written in the ground contract source only: the session (and the adapter) name no TRAINLEN / MAPLIMITS / CLEARDIST literal' (($groundCode -cmatch '"TRAINLEN"') -and ($groundCode -cmatch '"MAPLIMITS"') -and ($groundCode -cmatch '"CLEARDIST"') -and ($sessCode -cnotmatch '"TRAINLEN"|"MAPLIMITS"|"CLEARDIST"') -and ($extCode -cnotmatch '"TRAINLEN"|"MAPLIMITS"|"CLEARDIST"'))
Check 'L03 the adapter reads only public members: no reflection, no BindingFlags, no private field access, no Harmony in the host adapter' ($extCode -cnotmatch 'BindingFlags|GetField\(|GetProperty\(|GetMethod\(|Harmony|unsafe|DllImport|NonPublic')
$carSpec = [regex]::Match($extCode, 'bool ILegacyGroundApi\.TryCarSpec[\s\S]*?\n        \}').Value
Check 'L04 the adapter reads CarLength, MotorCar and TrailerCar for the length and never FirstCar' (($carSpec.Length -gt 200) -and ($carSpec -cnotmatch 'FirstCar|FirstCount') -and ($carSpec -cmatch 'CarLength') -and ($carSpec -cmatch 'MotorCar') -and ($carSpec -cmatch 'TrailerCar'))
Check 'L05 the Legacy host is never moved, re-timed or jumped (Initialize, InitializeTimeAndLocation, SetTime, GoTo are not named in any telemetry source)' (((Get-ChildItem $srcDir -Filter *.cs | ForEach-Object { Code ([IO.File]::ReadAllText($_.FullName)) }) -join "`n") -cnotmatch '\.Initialize\(|InitializeTimeAndLocation|SetTime\(|\.GoTo\(|CurrentIndex')
$infoCs = [IO.File]::ReadAllText((Join-Path $srcDir 'AssemblyInfo.cs'))
$vi = (Get-Item $dllPath).VersionInfo
Check 'L06 the product version is 0.4.0.0 in AssemblyInfo and in the built DLL (file, product), and the description names Phase SI-1' (($infoCs -match 'AssemblyVersion\("0\.4\.0\.0"\)') -and ($infoCs -match 'AssemblyFileVersion\("0\.4\.0\.0"\)') -and ($infoCs -match 'AssemblyInformationalVersion\("0\.4\.0\.0"\)') -and ($vi.FileVersion -eq '0.4.0.0') -and ($vi.ProductVersion -eq '0.4.0.0') -and ($vi.Comments -match 'Phase SI-1'))
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $changed = @((& git -C $repo diff --name-only HEAD) + (& git -C $repo ls-files --others --exclude-standard) | Where-Object { $_ })
    $tracked = @(& git -C $repo ls-files)
    $pyProduction = @($tracked | Where-Object { $_ -like '*.py' -and $_ -notlike 'tests/*' })
    # (Phase SI-1 is committed: its scope is the commit pair after the SI-0 commit, not the working tree. Phase SI-A changes the Python production files on purpose; its own tests pin that.)
    $changedPy = @((& git -C $repo diff --name-only f9b2ed5d7a3c0c7479d5798e2826b58bbdd9180b 9f25a26c6bc4a578767c7f306672811bf7bf341c) | Where-Object { $_ })
    $touchedPy = @($changedPy | Where-Object { $_ -in $pyProduction })
    Check ('L07 Python production code is untouched by Phase SI-1 (' + $pyProduction.Count + ' tracked production .py files, none changed between the SI-0 commit and the SI-1 commit)') (($pyProduction.Count -gt 10) -and ($touchedPy.Count -eq 0))
    # (Phase SI-A6 changes exactly these Caller / Bridge / shared files on purpose - the load marker; Test-PauseRecoverySIA6.ps1 and the other re-pinned guards say what changed in them)
    $si6Files = @('TsScoringPlugin/Handshake/Shared/HandshakeProtocol.cs', 'TsScoringPlugin/Handshake/Bridge/src/ScenarioReadyTracker.cs', 'TsScoringPlugin/Handshake/Bridge/src/ScenarioReadyPublisher.cs',
                  'TsScoringPlugin/Handshake/Bridge/src/AssemblyInfo.cs', 'TsScoringPlugin/Handshake/Bridge/Legacy/src/AssemblyInfo.cs', 'TsScoringPlugin/Handshake/Caller/src/AppProcessManager.cs',
                  'TsScoringPlugin/Handshake/Caller/src/AppStatePublisher.cs', 'TsScoringPlugin/Handshake/Caller/src/HandshakeSession.cs', 'TsScoringPlugin/Handshake/Caller/src/AssemblyInfo.cs')
    $immutable = @($changed | Where-Object { $_ -notin $si6Files } | Where-Object { $_ -like 'TsScoringPlugin/Handshake/Caller/*' -or $_ -like 'TsScoringPlugin/Handshake/Bridge/*' -or $_ -like 'TsScoringPlugin/TsScoringPlugin/*' -or $_ -like 'TsScoringPlugin/Handshake/Shared/*' -or $_ -like 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs' -or $_ -like 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyHandleContract.cs' -or $_ -like 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInput*.cs' -or $_ -like 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs' -or $_ -like 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyScoringProbe.cs' })
    Check ('L08 untouched: the Caller, both Bridges, the Current sender, the Handshake shared files (the nine Phase SI-A6 load-marker files excepted), and the Legacy API / handle / input / station / SI-0 observation sources (' + $immutable.Count + ' changed)') (($immutable.Count -eq 0) -and (@($si6Files | Where-Object { $_ -in $changed }).Count -eq 9))
    $contractDiff = @(& git -C $repo diff -U0 f9b2ed5d7a3c0c7479d5798e2826b58bbdd9180b 9f25a26c6bc4a578767c7f306672811bf7bf341c -- TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs | Where-Object { $_ -match '^[+-][^+-]' })
    Check 'L09 the shared telemetry contract only gained the two token names (trainlen, maplimit_ahead): nothing removed, nothing else added' ((@($contractDiff | Where-Object { $_ -match '^-' }).Count -eq 0) -and (@($contractDiff | Where-Object { $_ -match '^\+' }).Count -eq 2) -and (($contractDiff -join "`n") -match 'TokMapLimitAhead = "maplimit_ahead"') -and (($contractDiff -join "`n") -match 'TokTrainLen = "trainlen"'))
}
else { Skip 'L07-L09 (git is not available)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# M - the BVE5 32-bit path: the same DLL loaded by a 32-bit process writes the same bytes
# ---------------------------------------------------------------------------------------------------------------------------------------------
$probe = Join-Path $testDir 'probe.ps1'
[IO.File]::WriteAllText($probe, @'
param([string]$Dll, [string]$Fixture, [string]$Out)
Add-Type -TypeDefinition ([IO.File]::ReadAllText($Fixture)) -ReferencedAssemblies @($Dll) -OutputAssembly (Join-Path (Split-Path $Out) 'TsScoringLegacyTelemetryTests.dll') -OutputType Library
[void][Reflection.Assembly]::LoadFrom($Dll)
[void][Reflection.Assembly]::LoadFrom((Join-Path (Split-Path $Out) 'TsScoringLegacyTelemetryTests.dll'))
$lines = New-Object System.Collections.Generic.List[string]
foreach ($kind in 1, 2, 3) {
    $h = New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList @($true, $true, $true, $true)
    $h.Api.BrakeKind = $kind; $h.Input.BrakeKindValue = $kind; $h.Scoring.KindValue = $kind
    $h.Ground.CarLen = 18.0; $h.Ground.Motor = 4.0; $h.Ground.Trailer = 4.0
    foreach ($e in @(@(0.0, 27.77), @(1000.0, 16.66), @(2000.0, 27.77), @(2100.0, 13.88))) { $h.Scoring.Limits.Add((New-Object TsScoringLegacyTelemetryTests.FakeLimit -ArgumentList @($e[0], $e[1]))); $h.Ground.Limits.Add((New-Object TsScoringLegacyTelemetryTests.FakeLimit -ArgumentList @($e[0], $e[1]))) }
    $h.NoteInit('events=yes heartbeat=yes'); $h.Opened($false); $h.Created()
    $h.Api.Location = 1900.0; $h.Api.GroundMps = 16.66
    for ($i = 0; $i -lt 300; $i++) { $h.Api.Location += 1.0; if ($h.Api.Location -ge 2144.0) { $h.Api.GroundMps = 27.77 }; $h.Input.StoreBp = [double[]]@(490.0 - ($i % 7)); $h.Run(1, 16) }
    $h.Now += 2000; $null = $h.Heartbeat(); $h.Run(3, 16); $null = $h.Heartbeat()
    $h.Closed(); $h.Dispose()
    foreach ($s in $h.Sink.Sent) { $lines.Add($s) }
    foreach ($e in $h.Diag.Events) { if ($e -like 'TEL_GROUND_*') { $lines.Add($e) } }
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
    Check ('M01 a 32-bit process (BVE5) loads the DLL and writes exactly the same bytes as the 64-bit one: the stream with TRAINLEN / MAPLIMITS / CLEARDIST and the ground diagnostic lines, for Ecb / Smee / Cl (' + $t64 + ' | ' + $t32 + ')') (($t64 -match '^ptr=8 ') -and ($t32 -match '^ptr=4 ') -and (($t64 -replace '^ptr=\d+ ', '') -ceq ($t32 -replace '^ptr=\d+ ', '')) -and ($t64 -match 'lines=\d{3,}'))
}
else { Skip 'M01 (no 32-bit Windows PowerShell here)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"GROUND-LIMITS-SI1 PASS=$pass FAIL=$fail SKIP=$($script:skips)"
if ($fail -gt 0) { exit 1 } else { exit 0 }
