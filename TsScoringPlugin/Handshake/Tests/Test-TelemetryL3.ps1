# PHASE L3 - offline tests of the AtsEX LEGACY telemetry sender (the DATA plane): reads, units, AVAIL, failures, scenario life cycle, pause, dispose,
# stations, isolation from the Current API and from the Handshake control plane, and agreement with the Python reference reader of the contract.
# No BVE, no AtsEX runtime, no BveEX, no network, no hooks. The real built DLL is loaded from memory and driven through a FAKE of the Legacy API
# (tests\TelemetryTestFixture.cs, compiled here) exactly the way the host adapter drives it. Nothing is written outside logs\l3-tests.
# This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$testDir = Join-Path $Root 'logs\l3-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Near([double]$a, [double]$b, [double]$tol = 1e-6) { return [math]::Abs($a - $b) -le $tol }

# the DLL is copied to the test folder first (the fixture assembly must reference a file; the original out\ file stays untouched)
$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixtureSrc)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class L3Resolver
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
[L3Resolver]::Install(@($testDir, $legacyHost))
$telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
$fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)

function NewH { return (New-Object TsScoringLegacyTelemetryTests.Harness) }
function NewStation([string]$name, [double]$loc, [int]$arr = -1, [int]$dep = -1, [bool]$pass = $false, [bool]$term = $false, [int]$side = 1) {
    $s = New-Object TsScoringLegacyTelemetryTests.FakeStation
    $s.Name = $name; $s.Location = $loc; $s.ArrivalMs = $arr; $s.DepartureMs = $dep; $s.Pass = $pass; $s.IsTerminal = $term; $s.DoorSide = $side
    return $s
}
function P([string]$line) {
    $d = @{}
    foreach ($part in $line.Split(',')) { $i = $part.IndexOf(':'); if ($i -gt 0) { $d[$part.Substring(0, $i)] = $part.Substring($i + 1) } }
    return $d
}
function Tokens([string]$line) {
    $d = P $line
    $v = $d['AVAIL']
    if ($v -eq $null) { return @() }
    $rest = $v.Substring($v.IndexOf(':') + 1)
    if ($rest.Length -eq 0) { return @() }
    return @($rest.Split('+'))
}
function Last($h) { return $h.Sink.LastLine() }
$NEVER = @('REV', 'POW', 'BRK', 'HTYPE', 'ALLTXT', 'BCP', 'BPP', 'TRAINLEN', 'DOORTIME', 'MAPLIMITS', 'CLEARDIST', 'JUMP')
$NEVERTOK = @('handle', 'bcp', 'bpp', 'trainlen', 'doortime', 'maplimit_ahead', 'jump')

# ---------------------------------------------------------------------------------------------------------------------------------------------
# C - the contract (host independent)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$C = $fixAsm.GetType('TsScoringLegacyTelemetryTests.Contract')
Check 'C01 protocol version 1' ($C.GetProperty('Version').GetValue($null) -eq 1)
Check 'C02 UDP 127.0.0.1:54321' (($C.GetProperty('Port').GetValue($null) -eq 54321) -and ($C.GetProperty('Address').GetValue($null) -eq '127.0.0.1'))
Check 'C03 AVAIL is sorted and versioned' ($C.GetMethod('Avail').Invoke($null, @(, [string[]]@('speed', 'time', 'loc'))) -eq 'AVAIL:1:loc+speed+time')
Check 'C04 empty AVAIL list' ($C.GetMethod('Avail').Invoke($null, @(, [string[]]@())) -eq 'AVAIL:1:')
Check 'C05 signal limit: infinity and above 999 m/s are 1000, 0 is a real limit' ((Near ($C.GetMethod('Signal').Invoke($null, @([double]::PositiveInfinity))) 1000.0) -and (Near ($C.GetMethod('Signal').Invoke($null, @(1000.0))) 1000.0) -and (Near ($C.GetMethod('Signal').Invoke($null, @(0.0))) 0.0) -and (Near ($C.GetMethod('Signal').Invoke($null, @(25.0))) 90.0))
Check 'C06 ground limit: infinity, above 999 and not positive are 1000' ((Near ($C.GetMethod('Ground').Invoke($null, @([double]::PositiveInfinity))) 1000.0) -and (Near ($C.GetMethod('Ground').Invoke($null, @(0.0))) 1000.0) -and (Near ($C.GetMethod('Ground').Invoke($null, @(-1.0))) 1000.0) -and (Near ($C.GetMethod('Ground').Invoke($null, @(20.0))) 72.0))
Check 'C07 numbers are culture independent (round trip)' (($C.GetMethod('D').Invoke($null, @(1234.5)) -eq '1234.5') -and ($C.GetMethod('D').Invoke($null, @(0.1)) -eq '0.1'))
Check 'C08 META text cannot contain the separators' ($C.GetMethod('Meta').Invoke($null, @("a:b,c`r`nd")) -eq ("a" + [char]0xFF1A + "b" + [char]0x3001 + "c d"))
Check 'C09 an empty station name is the contract word for "no name"' ($C.GetMethod('Station').Invoke($null, @('')) -eq ([string]([char]0x4E0D) + [char]0x660E + [char]0x306A + [char]0x99C5))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# U - reads and units (the Legacy API values become the units of the contract)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewH
$h.Api.SpeedMps = 20.0; $h.Api.Location = 1234.5; $h.Api.TimeMs = 36000000; $h.Api.GradientRatio = -0.0125
$h.Api.SignalMps = 25.0; $h.Api.ForwardSignalMps = 11.0; $h.Api.NextSectionLoc = 1500.0; $h.Api.GroundMps = 20.0
$h.Api.DoorsClosed = $false; $h.Api.BrakeKind = 2; $h.Api.BrakeNotches = 5; $h.Api.Holding = $true
$h.Api.Rates = [double[]]@(0.0, 0.2, 0.4, 0.6, 0.8, 1.0); $h.Api.MaxPa = 490000.0
$h.Tick()
$line = Last $h
$d = P $line
Check 'U01 a line was sent for the first Tick' ($line -ne $null)
Check 'U02 SPEED is km/h (20 m/s = 72)' (Near ([double]$d['SPEED']) 72.0)
Check 'U03 TIME is the Legacy ms' ($d['TIME'] -eq '36000000')
Check 'U04 LOCATION is metres' (Near ([double]$d['LOCATION']) 1234.5)
Check 'U05 GRADIENT is per mille: the Legacy API ratio -0.0125 is written as -12.5' (Near ([double]$d['GRADIENT']) -12.5)
Check 'U06 SIGLIMIT is km/h (25 m/s = 90)' (Near ([double]$d['SIGLIMIT']) 90.0)
Check 'U07 FWDSIGLIMIT is km/h (11 m/s = 39.6) and FWDSIGLOC the next section' ((Near ([double]$d['FWDSIGLIMIT']) 39.6) -and (Near ([double]$d['FWDSIGLOC']) 1500.0))
Check 'U08 MAPHEAD and MAPTAIL are the ground limit in km/h (20 m/s = 72)' ((Near ([double]$d['MAPHEAD']) 72.0) -and (Near ([double]$d['MAPTAIL']) 72.0))
Check 'U09 DOOR is 1 when any door is open' ($d['DOOR'] -eq '1')
Check 'U10 BTYPE for Smee' ($d['BTYPE'] -eq 'Smee')
Check 'U11 CAB is notch count and holding flag' ($d['CAB'] -eq '5:1')
Check 'U12 PRATES are the ratios and the maximum in kPa (490000 Pa = 490.0)' ($d['PRATES'] -eq '0_0.2_0.4_0.6_0.8_1:490.0')
$m = $h.Sink.Starting('META:')
Check 'U13 META datagram carries the five texts' (($m.Count -eq 1) -and ($m[0] -eq 'META:Title:Route:Vehicle:Author:Comment'))
Check 'U14 the line order is SCENARIO_ID, AVAIL, SPEED, TIME, LOCATION first' ($line -match '^SCENARIO_ID:\d+,AVAIL:1:[a-z_+]+,SPEED:[^,]+,TIME:36000000,LOCATION:1234.5,')
$h.Api.SignalMps = 0.0; $h.Api.GroundMps = 0.0; $h.Api.ForwardSignalMps = [double]::PositiveInfinity
$h.Run(1, 16)
$d = P (Last $h)
Check 'U15 a stop signal (0 m/s) stays 0 km/h' (Near ([double]$d['SIGLIMIT']) 0.0)
Check 'U16 no ground limit (0) and no forward limit (infinity) are 1000' ((Near ([double]$d['MAPHEAD']) 1000.0) -and (Near ([double]$d['FWDSIGLIMIT']) 1000.0))
$h.Api.NextSectionFound = $false
$h.Run(1, 16)
$d = P (Last $h)
Check 'U17 no section ahead is the contract value -1' (Near ([double]$d['FWDSIGLOC']) -1.0)
$h.Api.SpeedMps = 20.0
$h.Api.Rates = [double[]]@(0.1)
$h.Run(1, 16)
$h.Api.SpeedMps = 21.0
$h.Run(1, 100)
$d = P (Last $h)
Check 'U18 CALCG is the acceleration in G from two samples of this scenario (1 m/s over 0.1 s)' (Near ([double]$d['CALCG']) (10.0 / 9.80665) 0.0001)

# ---------------------------------------------------------------------------------------------------------------------------------------------
# V - AVAIL: exactly what exists; never what does not
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewH
$h.Tick()
$first = Last $h
$expectedFirst = 'brake_cab,brake_type,door,grad,loc,maplimit,meta,prates,siglimit,siglimit_ahead,speed,station,time'
Check 'V01 the first line announces every readable group except calcg (no reference sample yet)' ((((Tokens $first) -join ',') -eq $expectedFirst))
$h.Run(1, 16)
$second = Last $h
Check 'V02 the second line adds calcg' (((Tokens $second) -join ',') -eq 'brake_cab,brake_type,calcg,door,grad,loc,maplimit,meta,prates,siglimit,siglimit_ahead,speed,station,time')
$ok = $true; foreach ($t in $NEVERTOK) { if ((Tokens $second) -contains $t) { $ok = $false } }
Check 'V03 no token for handle texts, BCP, BPP, vehicle length, door time, ground look-ahead or jump' $ok
$d = P $second
$ok = $true; foreach ($k in $NEVER) { if ($d.ContainsKey($k)) { $ok = $false } }
Check 'V04 none of their keys is ever written' $ok
$ok = $true
foreach ($line2 in $h.Sink.Lines()) { $dd = P $line2; foreach ($k in $NEVER) { if ($dd.ContainsKey($k)) { $ok = $false } } }
Check 'V05 not in any line of the run' $ok
$ok = $true
foreach ($t in (Tokens $second)) { $ok = $ok -and ($t -cmatch '^[a-z][a-z0-9_]{0,31}$') }
Check 'V06 every token is well formed' $ok
Check 'V07 the line is one datagram (no newline) and small' (($second.IndexOf("`n") -lt 0) -and ($second.Length -lt 1200))
$py = Join-Path $repo 'tests\telemetry_xcheck.py'
$dump = Join-Path $testDir 'v-dump.txt'
[IO.File]::WriteAllText($dump, (($h.Sink.Sent -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
$j = (& python -I $py $dump | Out-String) | ConvertFrom-Json
$tel = @($j | Where-Object { $_.kind -eq 'telemetry' })
Check 'V08 the Python reference reader accepts every line' ((@($tel | Where-Object { -not $_.valid }).Count -eq 0) -and ($tel.Count -ge 2))
Check 'V09 and reads exactly the tokens the sender wrote' ((($tel[1].tokens -join ',') -eq ((Tokens $second) -join ',')) -and ($tel[1].avail -eq 'ok'))
Check 'V10 with no unknown and no malformed token' (($tel[1].unknown -eq 0) -and ($tel[1].bad -eq 0))
Check 'V11 the other datagrams are STALIST-free here (no station) and META' ((@($j | Where-Object { $_.kind -eq 'META' }).Count -eq 1) -and (@($j | Where-Object { $_.kind -eq 'STALIST' }).Count -eq 0))
# the Python vocabulary knows every key the sender writes
$keysOk = $true
foreach ($k in $tel[1].keys) { if ($k -ne 'SCENARIO_ID' -and $k -ne 'AVAIL') { $keysOk = $keysOk -and ($k -cmatch '^[A-Z]+$') } }
Check 'V12 key names are the contract vocabulary' $keysOk

# ---------------------------------------------------------------------------------------------------------------------------------------------
# F - failures: an unreadable value is left out (and not announced), nothing else is affected
# ---------------------------------------------------------------------------------------------------------------------------------------------
$groupOf = @{
    'TryGradientRatio' = @('grad', @('GRADIENT'));
    'TrySignalLimitMps' = @('siglimit', @('SIGLIMIT'));
    'TryForwardSignalLimitMps' = @('siglimit_ahead', @('FWDSIGLIMIT', 'FWDSIGLOC'));
    'TryNextSectionLocation' = @('siglimit_ahead', @('FWDSIGLIMIT', 'FWDSIGLOC'));
    'TryGroundLimitMps' = @('maplimit', @('MAPHEAD', 'MAPTAIL'));
    'TryBrakeKind' = @('brake_type', @('BTYPE'));
    'TryBrakeNotches' = @('brake_cab', @('CAB'));
    'TryPressureRates' = @('prates', @('PRATES'));
    'TryScenarioMeta' = @('meta', @())
}
$n = 0
foreach ($name in ($groupOf.Keys | Sort-Object)) {
    $n++
    $tok = $groupOf[$name][0]; $keys = $groupOf[$name][1]
    $h = NewH; $h.Tick(); $h.Api.Fail.Add($name) | Out-Null; $h.Run(1, 16)
    $l = Last $h; $dd = P $l
    $others = (Tokens $l) | Where-Object { $_ -ne $tok }
    $absent = (-not ((Tokens $l) -contains $tok)); foreach ($k in $keys) { if ($dd.ContainsKey($k)) { $absent = $false } }
    Check ("F{0:00} {1} fails: its group is left out" -f $n, $name) ($absent -and ($l -ne $null))
    Check ("F{0:00}b ...and the rest of the line is intact" -f $n) ((@($others).Count -ge 8) -and $dd.ContainsKey('SPEED') -and $dd.ContainsKey('TIME') -and $dd.ContainsKey('LOCATION'))
    $h = NewH; $h.Tick(); $h.Api.ThrowIn = $name; $before = $h.Sink.Lines().Count; $h.Run(1, 16)
    $l = Last $h; $dd = P $l
    $absent = (-not ((Tokens $l) -contains $tok)); foreach ($k in $keys) { if ($dd.ContainsKey($k)) { $absent = $false } }
    Check ("F{0:00}c {1} throws: the exception stays inside, the group is left out, the line goes on" -f $n, $name) ($absent -and ($h.Sink.Lines().Count -eq $before + 1))
}
$h = NewH; $h.Tick(); $h.Api.Fail.Add('TryDoorsClosed') | Out-Null; $h.Run(1, 16)
$l = Last $h
Check 'F20 doors unreadable: neither door nor station is announced (the state machine needs the doors)' ((-not ((Tokens $l) -contains 'door')) -and (-not ((Tokens $l) -contains 'station')) -and ((Tokens $l) -contains 'speed'))
$h = NewH; $h.Tick(); $h.Api.Fail.Add('TryStationCount') | Out-Null; $h.Run(1, 16)
$l = Last $h
Check 'F21 station count unreadable: no station group, doors still announced' ((-not ((Tokens $l) -contains 'station')) -and ((Tokens $l) -contains 'door'))
foreach ($core in @('TryTimeMs', 'TryLocation', 'TrySpeedMps')) {
    $h = NewH; $h.Tick(); $c0 = $h.Sink.Lines().Count; $h.Api.Fail.Add($core) | Out-Null; $h.Run(3, 16)
    Check "F22 $core fails: no line at all (no placeholder core)" (($h.Sink.Lines().Count -eq $c0) -and ($h.LinesSkipped -ge 3))
    $h.Api.Fail.Clear(); $h.Run(1, 16)
    Check "F23 $core readable again: lines resume" ($h.Sink.Lines().Count -eq $c0 + 1)
    $h = NewH; $h.Tick(); $c0 = $h.Sink.Lines().Count; $h.Api.ThrowIn = $core; $h.Run(2, 16)
    Check "F24 $core throws: nothing is sent and nothing escapes" ($h.Sink.Lines().Count -eq $c0)
}
$h = NewH; $h.Api.SpeedMps = [double]::NaN; $h.Tick()
Check 'F25 a NaN speed is not a reading' ($h.Sink.Lines().Count -eq 0)
$h = NewH; $h.Api.Location = [double]::PositiveInfinity; $h.Tick()
Check 'F26 an infinite location is not a reading' ($h.Sink.Lines().Count -eq 0)
$h = NewH; $h.Api.GradientRatio = [double]::NaN; $h.Tick()
Check 'F27 a NaN gradient leaves the gradient out only' ((-not ((Tokens (Last $h)) -contains 'grad')) -and ((Tokens (Last $h)) -contains 'speed'))
$h = NewH; $h.Api.Rates = [double[]]@(); $h.Tick()
Check 'F28 no pressure rates (a system without them): no PRATES, not an empty one' (-not ((Tokens (Last $h)) -contains 'prates'))
$h = NewH; $h.Api.Rates = [double[]]@(0.0, [double]::NaN); $h.Tick()
Check 'F29 a NaN pressure rate leaves PRATES out' (-not ((Tokens (Last $h)) -contains 'prates'))
$h = NewH; $h.Api.BrakeKind = 0; $h.Tick()
Check 'F30 an undetermined brake system: no BTYPE (not a default Ecb)' (-not ((Tokens (Last $h)) -contains 'brake_type'))
$h = NewH; $h.Api.BrakeNotches = 0; $h.Tick()
Check 'F31 zero brake notches is not a reading: no CAB' (-not ((Tokens (Last $h)) -contains 'brake_cab'))
$h = NewH; $h.Api.Meta = $null; $h.Tick()
Check 'F32 no scenario info: no META datagram and no meta token' (($h.Sink.Starting('META:').Count -eq 0) -and (-not ((Tokens (Last $h)) -contains 'meta')))
$h = NewH; $h.Api.ThrowIn = 'IsScenarioCreated'; $h.Tick()
Check 'F33 IsScenarioCreated throws: treated as not created' (($h.Sink.Sent.Count -eq 0) -and (-not $h.Active))
$h = NewH; $h.Api.Fail.Add('TryScenarioIdentity') | Out-Null; $h.Tick()
Check 'F34 the Scenario object cannot be read (loading): nothing is sent' (($h.Sink.Sent.Count -eq 0) -and (-not $h.Active))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# L - the scenario life cycle: instances never mix
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewH; $h.Tick(); $id1 = $h.ScenarioId; $h.Run(5, 16)
Check 'L01 one scenario instance, one SCENARIO_ID' (($h.Epochs -eq 1) -and (@($h.Sink.Lines() | ForEach-Object { (P $_)['SCENARIO_ID'] } | Select-Object -Unique).Count -eq 1))
$h.Opened($true)
Check 'L02 ScenarioOpened ends the instance at once (heartbeat stops, nothing active)' ((-not $h.Active) -and ($h.Heartbeat() -eq $null))
$cnt = $h.Sink.Lines().Count; $h.Api.Created = $false; $h.Run(3, 16)
Check 'L03 nothing is sent while the scenario is being loaded (IsScenarioCreated false)' ($h.Sink.Lines().Count -eq $cnt)
$h.Api.Created = $true; $h.Api.Scenario = New-Object object; $h.Created(); $h.Run(1, 16)
Check 'L04 the new instance has a new SCENARIO_ID' (($h.Epochs -eq 2) -and ($h.ScenarioId -ne $id1))
$l = Last $h
Check 'L05 and starts from nothing: no CALCG (no reference), the station list is sent again' ((-not ((Tokens $l) -contains 'calcg')) -and ((Tokens $l) -contains 'speed'))
$h2 = NewH; $h2.Api.Stations.Add((NewStation 'A' 0.0)); $h2.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000)); $h2.Api.Stations.Add((NewStation 'C' 2000.0 -1 -1 $false $true))
$h2.Tick(); $sl1 = $h2.Sink.Starting('STALIST:').Count
$h2.Opened($false); $h2.Created(); $h2.Run(1, 16)
Check 'L06 a new instance sends STALIST again at once (not after the 1 s cadence)' (($sl1 -eq 1) -and ($h2.Sink.Starting('STALIST:').Count -eq 2))
$h = NewH; $h.Tick(); $idA = $h.ScenarioId
$h.Api.Scenario = New-Object object; $h.Run(1, 16)
Check 'L07 a different Scenario object is a new instance even without any event' (($h.Epochs -eq 2) -and ($h.ScenarioId -ne $idA))
$h = NewH; $h.Tick(); $h.Closed()
Check 'L08 ScenarioClosed ends the instance' ((-not $h.Active) -and ($h.Heartbeat() -eq $null))
$h.Run(1, 16)
Check 'L09 the same Scenario object after Closed is still a new instance (Closed ended the old one)' ($h.Epochs -eq 2)
$h = NewH; $h.Tick(); $idB = $h.ScenarioId; $h.Closed(); $h.Seed = $h.Seed; $h.Run(1, 16)
Check 'L10 two instances never share an id even when the id seed does not move' ($h.ScenarioId -ne $idB)
$h = NewH; $h.Api.Created = $false; $h.Tick()
Check 'L11 no scenario: nothing is sent, nothing is active' (($h.Sink.Sent.Count -eq 0) -and (-not $h.Active) -and ($h.Epochs -eq 0))
$h = NewH; $h.Api.Created = $false; $h.Tick(); $h.Api.Created = $true; $h.Tick()
Check 'L12 IsScenarioCreated turning true starts an instance' (($h.Epochs -eq 1) -and ($h.Sink.Lines().Count -eq 1))
$h = NewH; $h.Tick(); $h.Api.Created = $false; $h.Tick(); $h.Api.Created = $true; $h.Tick()
Check 'L13 IsScenarioCreated false in between ends the instance (a new one begins)' ($h.Epochs -eq 2)
$h = NewH; $h.Api.Stations.Add((NewStation 'A' 0.0)); $h.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000)); $h.Api.Location = 500.0
$h.Tick(); $h.Run(1, 16)
$dBefore = P (Last $h)
$h.Opened($false); $h.Api.Scenario = New-Object object; $h.Api.Location = 1500.0
$h.Api.Stations.Clear(); $h.Api.Stations.Add((NewStation 'X' 2000.0 36500000 36530000)); $h.Api.Stations.Add((NewStation 'Y' 3000.0)); $h.Run(1, 16)
$dAfter = P (Last $h)
Check 'L14 nothing of the previous scenario survives: the new line describes the new stations only' ((Near ([double]$dBefore['NEXTLOC']) 1000.0) -and (Near ([double]$dAfter['NEXTLOC']) 2000.0) -and ($dAfter['STATNAME'] -eq 'X'))
$h = NewH; $h.Run(3, 16)
$h.Api.TimeMs = $h.Api.TimeMs + 60000; $h.Run(1, 16)
$l = Last $h
Check 'L15 a jump of the simulation time is recognised, and the line after it has no acceleration reference' (($h.Discontinuities -eq 1) -and (-not ((Tokens $l) -contains 'calcg')))
$h.Run(1, 16)
Check 'L16 and the next one has again' ((Tokens (Last $h)) -contains 'calcg')
$h = NewH; $h.Run(3, 16); $h.Api.TimeMs = $h.Api.TimeMs - 5000; $h.Run(1, 16)
Check 'L17 a rewind of the simulation time is a discontinuity too' ($h.Discontinuities -eq 1)

# ---------------------------------------------------------------------------------------------------------------------------------------------
# G - the identity of a scenario instance (the L3-live defect): IBveHacker.Scenario returns a NEW wrapper on every access, so the wrapper must never
#     decide "same scenario". The old sender compared the wrapper by reference: every Tick was a new instance with a new SCENARIO_ID, the receiver
#     accepted one line and dropped the rest as "sender ahead".
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewH; $h.Api.FreshWrapperEachCall = $true; $h.Tick(); $w1 = $h.Api.LastWrapper; $h.Run(1, 16); $w2 = $h.Api.LastWrapper
Check 'G01 precondition (the defect): every Tick the host hands out a different wrapper object of the same scenario' ((-not [object]::ReferenceEquals($w1, $w2)) -and ($h.Api.WrappersIssued -eq 2))
$h = NewH; $h.Api.FreshWrapperEachCall = $true
$h.Api.Stations.Add((NewStation 'A' 0.0)); $h.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000)); $h.Api.Stations.Add((NewStation 'Z' 5000.0 -1 -1 $false $true))
$h.Tick(); $h.Run(999, 16)
$ids = @($h.Sink.Lines() | ForEach-Object { (P $_)['SCENARIO_ID'] } | Select-Object -Unique)
Check 'G02 1000 Ticks of one scenario with a new wrapper each Tick: ONE scenario instance and ONE SCENARIO_ID' (($h.Sink.Lines().Count -eq 1000) -and ($h.Epochs -eq 1) -and ($ids.Count -eq 1) -and ($h.Api.WrappersIssued -eq 1000))
$lines = $h.Sink.Lines()
$withG = @($lines | Select-Object -Skip 1 | Where-Object { (Tokens $_) -contains 'calcg' }).Count
Check 'G03 calcg appears from the second line on (the acceleration reference is no longer reset every Tick) and is not in the first' ((-not ((Tokens $lines[0]) -contains 'calcg')) -and ($withG -eq 999))
$sl = $h.Sink.Starting('STALIST:').Count; $mt = $h.Sink.Starting('META:').Count
Check 'G04 STALIST and META keep their 1 s cadence (about 16 in 16 s of simulation), not one per Tick' (($sl -ge 15) -and ($sl -le 18) -and ($mt -ge 15) -and ($mt -le 18))
Check 'G05 the diagnostic reports exactly one instance for the 1000 Ticks (no per-Tick log)' (($h.Diag.Named('TEL_EPOCH_BEGIN').Count -eq 1) -and ($h.Diag.Named('TEL_UDP_BEGIN').Count -eq 1) -and ($h.Diag.Events.Count -le 3))
$idG = $h.ScenarioId; $cnt = $h.Sink.Lines().Count; $h.Now += 60000
Check 'G06 a pause (no Ticks for a minute) reports PAUSED, sends nothing and keeps the instance' (($h.Heartbeat() -eq 'STATUS:LOADED:PAUSED') -and ($h.Sink.Lines().Count -eq $cnt) -and ($h.Active))
$h.Run(50, 16)
Check 'G07 after the pause: same SCENARIO_ID, still one instance, still calcg' (($h.ScenarioId -eq $idG) -and ($h.Epochs -eq 1) -and ((Tokens (Last $h)) -contains 'calcg') -and ($h.Discontinuities -eq 0))
# the same inputs through a stable-wrapper host and a new-wrapper host must produce the same datagrams (nothing but the identity was fixed)
function GRun([bool]$fresh) {
    $x = NewH; $x.Api.FreshWrapperEachCall = $fresh
    $x.Api.Stations.Add((NewStation 'A' 0.0)); $x.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000)); $x.Api.Stations.Add((NewStation 'Z' 5000.0 -1 -1 $false $true))
    $x.Tick(); $x.Run(120, 16)
    return $x
}
$gs = GRun $false; $gf = GRun $true
Check 'G08 UDP format unchanged: every datagram (SCENARIO_ID, AVAIL, values, STALIST, META) is identical for a stable-wrapper and a new-wrapper host' (($gs.Sink.Sent.Count -eq $gf.Sink.Sent.Count) -and ((@($gs.Sink.Sent) -join "`n") -ceq (@($gf.Sink.Sent) -join "`n")))
$gl = @($gf.Sink.Lines())
Check 'G09 AVAIL unchanged: the same announced groups as before (calcg only from the second line)' ((((Tokens $gl[1]) -join ',') -eq 'brake_cab,brake_type,calcg,door,grad,loc,maplimit,meta,prates,siglimit,siglimit_ahead,speed,station,time') -and (((Tokens $gl[0]) -join ',') -eq 'brake_cab,brake_type,door,grad,loc,maplimit,meta,prates,siglimit,siglimit_ahead,speed,station,time'))
$neverSeen = @($gl | ForEach-Object { Tokens $_ } | Where-Object { $_ -in $NEVERTOK })
$keysSeen = @($gl | ForEach-Object { (P $_).Keys } | Where-Object { $_ -in $NEVER })
Check 'G10 unobtainable items unchanged: no handle / bcp / bpp / trainlen / doortime / maplimit_ahead / jump token and none of their keys' (($neverSeen.Count -eq 0) -and ($keysSeen.Count -eq 0))
# a reload of IDENTICAL content: a new scenario object with every value equal
$h = NewH; $h.Api.FreshWrapperEachCall = $true; $h.Run(20, 16); $idR = $h.ScenarioId
$h.Opened($true); $h.Api.Scenario = New-Object object; $h.Created(); $h.Run(20, 16)
Check 'G11 a reload of the same content is a NEW instance (new SCENARIO_ID) even though every value is identical' (($h.Epochs -eq 2) -and ($h.ScenarioId -ne $idR))
Check 'G12 and the new instance starts from nothing (its first line has no calcg)' (-not ((Tokens @($h.Sink.Lines())[20]) -contains 'calcg'))
$endR = @($h.Diag.Named('TEL_EPOCH_END'))[0]; $begR = @($h.Diag.Named('TEL_EPOCH_BEGIN'))[1]
Check 'G13 the diagnostic names why: the first instance ended by the reload event, the second began for that reason' (($endR -match 'reason=scenario-opened-reload') -and ($begR -match 'reason=scenario-opened-reload'))
# a reload whose lifecycle events did not reach us: only the original object changed
$h = NewH; $h.Api.FreshWrapperEachCall = $true; $h.Run(10, 16); $idS = $h.ScenarioId; $h.Api.Scenario = New-Object object; $h.Run(10, 16)
Check 'G14 a different scenario (a different original object) without any event is a new instance, reason identity-changed' (($h.Epochs -eq 2) -and ($h.ScenarioId -ne $idS) -and ((@($h.Diag.Named('TEL_EPOCH_BEGIN'))[1]) -match 'reason=identity-changed'))
# the same original object, but the lifecycle events say the scenario was closed and loaded again: the events alone start a new instance
$h = NewH; $h.Api.FreshWrapperEachCall = $true; $h.Run(10, 16); $idT = $h.ScenarioId; $h.Closed(); $h.Opened($false); $h.Created(); $h.Run(10, 16)
Check 'G15 lifecycle events alone also start a new instance (Closed / Opened / Created); the old one never silently continues' (($h.Epochs -eq 2) -and ($h.ScenarioId -ne $idT))
# dispose and re-initialise (a new extension instance): a fresh session, a fresh sink
$h = NewH; $h.Api.FreshWrapperEachCall = $true; $h.Run(30, 16); $first = $h.Sink.Lines().Count; $h.Dispose()
$dd = @($h.Diag.Named('TEL_DISPOSE'))
Check 'G16 Dispose is logged once with the totals (epochs, lines)' (($dd.Count -eq 1) -and ($dd[0] -match 'epochs=1 lines=30 '))
$h.Reinitialize(); $h.Run(30, 16)
Check 'G17 re-initialisation after Dispose: a new session sends again; with a new-wrapper host still one instance and one SCENARIO_ID' (($h.Sink.Lines().Count -eq 30) -and ($h.Epochs -eq 1) -and (@($h.Sink.Lines() | ForEach-Object { (P $_)['SCENARIO_ID'] } | Select-Object -Unique).Count -eq 1) -and ($first -eq 30))
# the identity cannot be read: nothing is sent, nothing guessed, and it is reported once
$h = NewH; $h.Run(5, 16); $h.Api.SourceUnreadable = $true; $cnt = $h.Sink.Lines().Count; $h.Run(100, 16)
Check 'G18 an unreadable original object sends nothing and is reported once (not per Tick)' (($h.Sink.Lines().Count -eq $cnt) -and ($h.Diag.Named('TEL_IDENTITY_UNAVAILABLE').Count -eq 1) -and (-not $h.Active))
$h.Api.SourceUnreadable = $false; $h.Run(5, 16)
Check 'G19 when it can be read again a new instance begins' (($h.Epochs -eq 2) -and ($h.Sink.Lines().Count -eq ($cnt + 5)))
$h = NewH; $h.Diag.Throw = $true; $h.Run(10, 16); $h.Opened($false); $h.Created(); $h.Run(10, 16); $h.Dispose()
Check 'G20 a diagnostic that throws changes nothing in the telemetry (20 lines, 2 instances, disposed)' (($h.Sink.Lines().Count -eq 20) -and ($h.Epochs -eq 2) -and $h.IsDisposed)
$h = NewH; $h.Api.Meta = @('SecretTitle', 'SecretRoute', 'SecretVehicle', 'SecretAuthor', 'SecretComment'); $h.Api.FreshWrapperEachCall = $true; $h.Run(10, 16); $h.Opened($true); $h.Created(); $h.Run(10, 16); $h.Dispose()
$diagText = $h.Diag.Events -join "`n"
Check 'G21 the diagnostic carries no scenario text and no path' (($diagText -notmatch 'Secret') -and ($diagText -notmatch '[A-Za-z]:\\') -and ($diagText -notmatch 'Users'))

# the REAL file diagnostic (a path this test owns)
$dpath = Join-Path $testDir 'diag.log'
$D = $fixAsm.GetType('TsScoringLegacyTelemetryTests.DiagInfo')
Check 'G22 the dedicated log is TSScoring-L3-Telemetry.log in the Downloads folder of the user profile' (($D.GetProperty('FileName').GetValue($null) -eq 'TSScoring-L3-Telemetry.log') -and ($D.GetProperty('DefaultPathText').GetValue($null) -eq (Join-Path (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads') 'TSScoring-L3-Telemetry.log')))
[IO.File]::WriteAllText($dpath, "OLD RUN`r`n")
$h = NewH; $h.UseFileDiag($dpath); $h.Api.FreshWrapperEachCall = $true; $h.Run(1000, 16); $h.Opened($true); $h.Created(); $h.Run(10, 16); $h.Dispose()
$dl = @([IO.File]::ReadAllLines($dpath))
Check 'G23 the file log starts a fresh file for the run (the previous content is gone)' (($dl.Count -ge 1) -and (-not ($dl -contains 'OLD RUN')))
Check 'G24 1000 + 10 Ticks produce a handful of lines (state changes only; 2 instances = 2 gradient unit lines), each HH:mm:ss.fff P=pid I=n EVENT' (($dl.Count -le 10) -and (@($dl | Where-Object { $_ -notmatch '^\d\d:\d\d:\d\d\.\d{3} P=\d+ I=\d+ TEL_[A-Z_]+( |$)' }).Count -eq 0))
$dj = $dl -join "`n"
Check 'G25 the log shows instance 1 (first-tick, src-object), its UDP start, its end with 1000 lines, the reload instance and the totals' (($dj -match 'TEL_EPOCH_BEGIN n=1 scenarioId=\d+ reason=first-tick identity=src-object') -and ($dj -match 'TEL_UDP_BEGIN scenarioId=\d+') -and ($dj -match 'TEL_EPOCH_END scenarioId=\d+ lines=1000 reason=scenario-opened-reload') -and ($dj -match 'TEL_EPOCH_BEGIN n=2 .*reason=scenario-opened-reload') -and ($dj -match 'TEL_DISPOSE epochs=2 lines=1010 '))
Check 'G26 the log holds no path, user name or scenario text' (($dj -notmatch '[A-Za-z]:\\') -and ($dj -notmatch ('(?i)' + [regex]::Escape($env:USERNAME))))
$D.GetMethod('Write').Invoke($null, @([string]$dpath, [string]'TEL_PROBE', [string]'k=v')) | Out-Null
Check 'G27 a second writer in the same process appends (it does not truncate again)' (@([IO.File]::ReadAllLines($dpath)).Count -eq ($dl.Count + 1))

# R - the REAL BveTypes wrapper classes (what IBveHacker.Scenario really calls), no BVE needed
$IP = $fixAsm.GetType('TsScoringLegacyTelemetryTests.IdentityProbe')
if ($IP.GetProperty('Available').GetValue($null)) {
    $srcObj = New-Object object
    $wa = $IP.GetMethod('NewWrapper').Invoke($null, @($srcObj)); $wb = $IP.GetMethod('NewWrapper').Invoke($null, @($srcObj)); $wc = $IP.GetMethod('NewWrapper').Invoke($null, @((New-Object object)))
    Check 'R01 two REAL wrappers of one scenario are different objects (the defect), and the host calls them Equal' ((-not [object]::ReferenceEquals($wa, $wb)) -and $IP.GetMethod('WrapperEquals').Invoke($null, @($wa, $wb)) -and (-not $IP.GetMethod('WrapperEquals').Invoke($null, @($wa, $wc))))
    $ia = $IP.GetMethod('IdentityOf').Invoke($null, @(, $wa)); $ib = $IP.GetMethod('IdentityOf').Invoke($null, @(, $wb)); $ic = $IP.GetMethod('IdentityOf').Invoke($null, @(, $wc))
    Check 'R02 the adapter identity of both wrappers is the SAME original object (reference), not the wrapper' (([object]::ReferenceEquals($ia[0], $ib[0])) -and ([object]::ReferenceEquals($ia[0], $srcObj)) -and (-not [object]::ReferenceEquals($ia[0], $wa)) -and (-not [object]::ReferenceEquals($ia[1], $ib[1])) -and ($ia[2] -eq 'src-object'))
    Check 'R03 a different scenario (a different original object) has a different identity' (-not [object]::ReferenceEquals($ia[0], $ic[0]))
    Check 'R04 no wrapper, no identity (nothing is guessed)' ($null -eq $IP.GetMethod('IdentityOf').Invoke($null, [object[]]@($null)))
    $h = NewH; $IP.GetMethod('UseRealWrappers').Invoke($null, @(, $h.Api)) | Out-Null
    $h.Tick(); $h.Run(999, 16)
    Check 'R05 1000 Ticks through REAL wrapper objects: one instance, one SCENARIO_ID, calcg from the second line' (($h.Sink.Lines().Count -eq 1000) -and ($h.Epochs -eq 1) -and (@($h.Sink.Lines() | ForEach-Object { (P $_)['SCENARIO_ID'] } | Select-Object -Unique).Count -eq 1) -and ((Tokens $h.Sink.Lines()[1]) -contains 'calcg'))
    $h.Opened($true); $h.Api.Scenario = New-Object object; $h.Created(); $h.Run(5, 16)
    Check 'R06 a reload through REAL wrapper objects is a new instance' ($h.Epochs -eq 2)
}
else {
    Write-Host 'SKIP (not counted as a pass) R01-R06 real BveTypes wrappers: the AtsEX legacy host assemblies are not installed on this machine'
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# H - the C# datagrams through the REAL TelemetryGate of the application (strict / managed mode, no Qt, no socket): a sender that keeps ONE SCENARIO_ID per
#     scenario instance is never "ahead" of the Caller, so the HUD gate stays ready after the first accepted line
# ---------------------------------------------------------------------------------------------------------------------------------------------
$gatePy = Join-Path $repo 'tests\telemetry_gate_check.py'
if (Test-Path $gatePy) {
    function GateRun($sentLines, [string]$name) {
        $f = Join-Path $testDir $name
        [IO.File]::WriteAllText($f, (($sentLines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
        Push-Location $repo
        try { $raw = (& python -I $gatePy $f | Out-String) } finally { Pop-Location }
        return ($raw | ConvertFrom-Json)
    }
    $hg = NewH; $hg.Api.FreshWrapperEachCall = $true
    $hg.Api.Stations.Add((NewStation 'A' 0.0)); $hg.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000))
    $hg.Tick(); $hg.Run(999, 16)
    $r = GateRun $hg.Sink.Sent 'h-one-instance.txt'
    Check 'H01 1000 lines of one scenario (new wrapper every Tick) through the real strict gate: all accepted, tel_ahead=0, tel_stale=0, one epoch, ready' (($r.lines -eq 1000) -and ($r.accepted_all -eq $true) -and ($r.stats.tel_accepted -eq 1000) -and ($r.stats.tel_ahead -eq 0) -and ($r.stats.tel_stale -eq 0) -and ($r.stats.tel_epochs -eq 1) -and ($r.ready -eq $true))
    Check 'H02 the HUD gate never drops back after the first accepted line (no telemetry-drop, no sender-ahead, no wait reason)' (($r.not_ready_after_first -eq 0) -and ($r.wait_reason -eq $null) -and (-not (@($r.events) -contains 'telemetry-drop')))
    $hg.Opened($true); $hg.Api.Scenario = New-Object object; $hg.Created(); $first = $hg.Sink.Sent.Count; $hg.Run(300, 16)
    $sentR = @($hg.Sink.Sent[0..($first - 1)]) + @('@GEN:2') + @($hg.Sink.Sent[$first..($hg.Sink.Sent.Count - 1)])
    $r2 = GateRun $sentR 'h-reload.txt'
    Check 'H03 a reload of the same content: the Caller generation 2 binds the new SCENARIO_ID; 1300 lines accepted, two epochs, never ahead, ready' (($r2.stats.tel_accepted -eq 1300) -and ($r2.stats.tel_ahead -eq 0) -and ($r2.stats.tel_stale -eq 0) -and ($r2.stats.tel_epochs -eq 2) -and ($r2.ready -eq $true) -and ($r2.not_ready_after_first -eq 0))
    # control: the failure signature of L3-live (a new SCENARIO_ID on every line) is exactly what this check would show for the old sender
    $ctl = @(); $n = 1; foreach ($l in $hg.Sink.Lines() | Select-Object -First 200) { $ctl += ($l -replace '^SCENARIO_ID:\d+', ('SCENARIO_ID:' + (1000 + $n))); $n++ }
    $r3 = GateRun $ctl 'h-control-old-behaviour.txt'
    Check 'H04 control: a new SCENARIO_ID on every line (the L3-live defect) is seen by the same check as accepted=1, ahead=199, not ready (sender-ahead)' (($r3.stats.tel_accepted -eq 1) -and ($r3.stats.tel_ahead -eq 199) -and ($r3.ready -eq $false) -and ($r3.wait_reason -eq 'sender-ahead'))
}
else {
    Write-Host 'SKIP (not counted as a pass) H01-H04 the real strict gate: tests\telemetry_gate_check.py is missing'
}
# ---------------------------------------------------------------------------------------------------------------------------------------------
# P - pause and heartbeat
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewH
Check 'P01 no heartbeat before the first scenario' ($h.Heartbeat() -eq $null)
$h.Tick()
Check 'P02 RUNNING right after a Tick' ($h.Heartbeat() -eq 'STATUS:LOADED:RUNNING')
$h.Now += 100
Check 'P03 still RUNNING at 100 ms' ($h.Heartbeat() -eq 'STATUS:LOADED:RUNNING')
$h.Now += 1
Check 'P04 PAUSED above 100 ms without a Tick (the host stops ticking while paused)' ($h.Heartbeat() -eq 'STATUS:LOADED:PAUSED')
$cnt = $h.Sink.Sent.Count; $h.Now += 60000
Check 'P05 a pause sends no telemetry (the heartbeat is composed, not sent, by the core)' ($h.Sink.Sent.Count -eq $cnt)
$idP = $h.ScenarioId; $h.Run(1, 16)
Check 'P06 resuming continues the same instance with the same SCENARIO_ID (a pause is not a new scenario)' (($h.ScenarioId -eq $idP) -and ($h.Epochs -eq 1) -and ($h.Heartbeat() -eq 'STATUS:LOADED:RUNNING'))
Check 'P07 and no discontinuity is counted for the resume' ($h.Discontinuities -eq 0)
$h.Closed()
Check 'P08 no heartbeat after the scenario ended' ($h.Heartbeat() -eq $null)

# ---------------------------------------------------------------------------------------------------------------------------------------------
# D - dispose
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewH; $h.Run(3, 16); $cnt = $h.Sink.Sent.Count
$h.Dispose()
Check 'D01 Dispose closes the sink and ends the instance' ($h.Sink.Closed -and (-not $h.Active) -and $h.IsDisposed)
$h.Run(5, 16); $h.Opened($false); $h.Created()
Check 'D02 nothing is sent after Dispose, whatever arrives' (($h.Sink.Sent.Count -eq $cnt) -and ($h.Sink.SendsAfterClose -eq 0))
Check 'D03 no heartbeat after Dispose' ($h.Heartbeat() -eq $null)
$h.Dispose()
Check 'D04 Dispose twice is harmless' $h.IsDisposed

# ---------------------------------------------------------------------------------------------------------------------------------------------
# S - stations
# ---------------------------------------------------------------------------------------------------------------------------------------------
function StationRun {
    $h = NewH
    $h.Api.Stations.Add((NewStation 'A' 0.0))
    $h.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000))
    $h.Api.Stations.Add((NewStation 'C' 2000.0 -1 -1 $true))
    $h.Api.Stations.Add((NewStation 'D' 3000.0 36400000 -1 $false $true))
    return $h
}
$h = StationRun; $h.Api.Location = 900.0; $h.Api.SpeedMps = 10.0; $h.Tick()
$l = Last $h; $dd = P $l
Check 'S01 the next station is the first at or after the vehicle' ((Near ([double]$dd['NEXTLOC']) 1000.0) -and ($dd['STATNAME'] -eq 'B') -and ($dd['ISPASS'] -eq '0'))
Check 'S02 before the stop the time is the ARRIVAL time' ($dd['NEXTTIME'] -eq '36100000')
Check 'S03 the margins are positive metres (the Legacy API gives the rear margin negative)' ((Near ([double]$dd['MARGINB']) 5.0) -and (Near ([double]$dd['MARGINF']) 5.0))
Check 'S04 a timetable entry makes the station a timing station; the first station never is' (($dd['ISTIMING'] -eq '1') -and ($h.Sink.Starting('STALIST:')[0] -match '^STALIST:A=0=0='))
$sta = $h.Sink.Starting('STALIST:')[0]
Check 'S05 STALIST: name=timing=location=arr=dep=default=stop=pass=terminal, per station' (($sta.Split(',').Count -eq 4) -and ($sta.Split(',')[1] -eq 'B=1=1000=36100000=36130000=-1=15000=0=0') -and ($sta.Split(',')[2] -match '^C=0=2000=') -and ($sta.Split(',')[3] -match '=0=1$'))
$h.Api.Location = 995.0; $h.Api.SpeedMps = 0.0; $h.Api.DoorsClosed = $false; $h.Run(1, 16)
$dd = P (Last $h)
Check 'S06 with the doors open at the station the time becomes the DEPARTURE time' ($dd['NEXTTIME'] -eq '36130000')
$h.Api.DoorsClosed = $true; $h.Run(1, 16)
$dd = P (Last $h)
Check 'S07 doors closed again: the next station is the passing station C' (($dd['STATNAME'] -eq 'C') -and ($dd['ISPASS'] -eq '1') -and (Near ([double]$dd['NEXTLOC']) 2000.0))
Check 'S08 a passing station carries no stop: DOORDIR as given, TERM 0' ($dd['TERM'] -eq '0')
$h.Api.Location = 2010.0; $h.Run(1, 16)
$dd = P (Last $h)
Check 'S09 after the passing station the terminal D is next, and it is flagged' (($dd['STATNAME'] -eq 'D') -and ($dd['TERM'] -eq '1'))
$h.Api.Location = 3100.0; $h.Run(1, 16)
$dd = P (Last $h)
Check 'S10 the terminal is never left (no station after it)' (($dd['STATNAME'] -eq 'D') -and ($dd['TERM'] -eq '1'))
$h = StationRun; $h.Api.Location = 9000.0; $h.Tick()
$dd = P (Last $h)
Check 'S11 beyond the last station there is no next station: NEXTLOC -1 and NEXTTIME -1 (the contract words for none)' (($dd['NEXTLOC'] -eq '-1') -and ($dd['NEXTTIME'] -eq '-1'))
$h = NewH; $h.Tick(); $dd = P (Last $h)
Check 'S12 an empty route is a real answer: station group announced, NEXTLOC -1, no STALIST' (((Tokens (Last $h)) -contains 'station') -and ($dd['NEXTLOC'] -eq '-1') -and ($h.Sink.Starting('STALIST:').Count -eq 0))
$h = StationRun; $h.Tick(); $h.Run(10, 16)
Check 'S13 the stations are read once, not every Tick (only their number is)' (($h.Api.CallCount('TryStations') -eq 1) -and ($h.Api.CallCount('TryStationCount') -ge 11))
$h.Api.Stations.Add((NewStation 'E' 4000.0)); $h.Run(1, 16)
Check 'S14 a changed number of stations rebuilds the list' ($h.Api.CallCount('TryStations') -eq 2)
$h = StationRun; $h.Tick(); $h.Now += 998; $h.Run(1, 1); $a = $h.Sink.Starting('STALIST:').Count; $h.Now += 1; $h.Run(1, 1); $b = $h.Sink.Starting('STALIST:').Count
Check 'S15 STALIST goes out once, then every second (not every Tick)' (($a -eq 1) -and ($b -eq 2))
$h = StationRun; $h.Tick(); $h.Run(20, 16)
Check 'S16 META follows the same cadence' ($h.Sink.Starting('META:').Count -eq 1)
$h = NewH; $s = NewStation 'Op' 1000.0 36100000 36130000 $false $false 0; $h.Api.Stations.Add((NewStation 'A' 0.0)); $h.Api.Stations.Add($s); $h.Api.Stations.Add((NewStation 'Z' 5000.0 -1 -1 $false $true))
$h.Api.Location = 1000.0; $h.Api.SpeedMps = 0.0; $h.Tick()
$dd = P (Last $h)
Check 'S17 an operating stop (door side 0) at standstill inside the margin becomes ready to depart' (($dd['NEXTTIME'] -eq '36130000') -and ($dd['DOORDIR'] -eq '0'))
$h = NewH; $h.Api.Stations.Add((NewStation 'A' 0.0)); $h.Api.Stations.Add((NewStation 'B' 1000.0)); $h.Api.Location = 100.0; $h.Tick()
$dd = P (Last $h)
Check 'S18 a station without any time: NEXTTIME 0 (the contract value for no time) and not a timing station' (($dd['NEXTTIME'] -eq '0') -and ($dd['ISTIMING'] -eq '0'))
$h = NewH
$h.Api.Stations.Add((NewStation 'A' 0.0 36000000 36000000)); $h.Api.Stations.Add((NewStation 'M' 1000.0)); $h.Api.Stations.Add((NewStation 'Z' 2000.0 36200000 -1 $false $true))
$h.Api.Location = 500.0; $h.Tick()
$sta = $h.Sink.Starting('STALIST:')[0].Split(',')
Check 'S19 a middle station without a timetable entry gets a time interpolated along the distance' ($sta[1] -match '^M=0=1000=36092500=')

# ---------------------------------------------------------------------------------------------------------------------------------------------
# X - isolation: no Current API, no Handshake control plane, nothing guessed
# ---------------------------------------------------------------------------------------------------------------------------------------------
$srcDir = Join-Path $Root 'Telemetry'
$srcFiles = @(Get-ChildItem $srcDir -Recurse -Filter *.cs | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' })
$all = (($srcFiles | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n")
$allCode = [regex]::Replace($all, '//[^\r\n]*', '')      # comments are not code: the checks below look at code only
Check 'X01 the telemetry project has sources' ($srcFiles.Count -ge 6)
Check 'X02 no BveEX (Current) namespace or type is named' ($allCode -cnotmatch 'BveEx' -and $allCode -cnotmatch 'BveEX')
$refs = @($telAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name })
Check 'X03 the built DLL references no BveEX assembly' (-not ($refs | Where-Object { $_ -match 'BveEx' }))
Check 'X04 the built DLL references only AtsEX, BveTypes and the framework' (-not ($refs | Where-Object { $_ -notmatch '^(mscorlib|System|System\.Core|AtsEx\.PluginHost|BveTypes|FastCaching|FastMember|TypeWrapping)$' }))
Check 'X05 no Handshake source is linked into the telemetry project' (($allCode -notmatch 'HandshakeProtocol') -and ($allCode -notmatch 'ScenarioReady') -and ($allCode -notmatch 'ObservationLog') -and ($allCode -notmatch 'TSScoringPlugin\.Handshake'))
$proj = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
Check 'X06 the project file links no Handshake / Bridge / Caller file' ($proj -notmatch '\.\.\\Bridge|\.\.\\\.\.\\Shared|Caller|Handshake(Protocol|Control)')
$session = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyTelemetrySession.cs'))
$bad = @(); foreach ($k in @('REV', 'POW', 'BRK', 'HTYPE', 'ALLTXT', 'BCP', 'BPP', 'TRAINLEN', 'DOORTIME', 'MAPLIMITS', 'CLEARDIST', 'JUMP')) { if ($session -match ('"' + $k + '"')) { $bad += $k } }
Check 'X07 the sender source never names a key of data the Legacy API does not have' ($bad.Count -eq 0)
$ext = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyTelemetryExtension.cs'))
$hostNames = @($srcFiles | Where-Object { [IO.File]::ReadAllText($_.FullName) -match 'using AtsEx|using BveTypes' } | ForEach-Object { $_.Name })
Check 'X08 only the host adapter names AtsEX / BveTypes types' (($hostNames.Count -eq 1) -and ($hostNames[0] -eq 'LegacyTelemetryExtension.cs'))
Check 'X09 the sender has no random, constant fallback or "unknown" default for a value' (($session -notmatch 'new Random') -and ($session -notmatch 'catch\s*\{\s*(speed|location|timeMs)\s*='))
$hostCode = [regex]::Replace($ext, '//[^\r\n]*', '')
Check 'X10 the timer thread uses only the session heartbeat (no BveHacker / Scenario in OnHeartbeat)' (($hostCode -match 'private void OnHeartbeat[\s\S]*?session\.ComposeHeartbeat\(\)') -and (([regex]::Match($hostCode, 'private void OnHeartbeat[\s\S]*?\r?\n        \}')).Value -notmatch 'hacker|BveHacker|Scenario'))
$pluginAttr = $telAsm.GetType('TSScoringPlugin.Telemetry.TsScoringLegacyTelemetryExtension').GetCustomAttributes($false) | ForEach-Object { $_.GetType().Name }
Check 'X11 the extension carries the AtsEX Plugin attribute' ($pluginAttr -contains 'PluginAttribute')
$exts = @($telAsm.GetTypes() | Where-Object { $_.IsPublic })
Check 'X12 exactly one public type (the extension); the core is internal' (($exts.Count -eq 1) -and ($exts[0].Name -eq 'TsScoringLegacyTelemetryExtension'))
Check 'X13 the sink is the only network type (no listener, no 54322)' (($allCode -notmatch 'UdpClient\(\s*\d') -and ($allCode -notmatch '54322') -and ($allCode -notmatch 'TcpListener|Receive\('))
$asm = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\AssemblyInfo.cs'))
Check 'X14 public metadata carries no personal information' (($asm -notmatch '(?i)\\Users\\') -and ($asm -match 'Coruge-to'))
$sessCode = [regex]::Replace($session, '//[^\r\n]*', '')
$apiCode = [regex]::Replace([IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyApi.cs')), '//[^\r\n]*', '')
Check 'X15 the session decides "same scenario" by the reference identity of the ORIGINAL object (identity.Source) and never reads the wrapper' (($sessCode -match 'ReferenceEquals\(identity\.Source, scenarioToken\)') -and ($sessCode -notmatch 'identity\.Wrapper') -and ($sessCode -notmatch 'ReferenceEquals\(scenario,'))
Check 'X16 the host adapter takes the identity from ClassWrapperBase.Src and never uses the wrapper as the identity' (($hostCode -match 'object source = wrapper\.Src;') -and ($hostCode -match 'identity\.Source = source;') -and ($hostCode -notmatch 'identity\.Source = (wrapper|s)\b') -and ($hostCode -notmatch 'scenario = s;'))
Check 'X17 the interface has no wrapper-identity member any more (TryScenarioIdentity replaces TryScenario)' (($apiCode -match 'bool TryScenarioIdentity\(') -and ($apiCode -notmatch 'bool TryScenario\('))
Check 'X18 the diagnostic is dedicated to this DLL: its own file name, no Handshake log, no named kernel object' (($hostCode -match 'TSScoring-L3-Telemetry\.log') -and ($allCode -notmatch 'EventWaitHandle|new Mutex|MemoryMappedFile'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# W - the real Win32-free sink: loopback delivery to a socket this test owns
# ---------------------------------------------------------------------------------------------------------------------------------------------
$sinkType = $telAsm.GetType('TSScoringPlugin.Telemetry.UdpTelemetrySink')
$recv = New-Object System.Net.Sockets.UdpClient(0)
$port = ($recv.Client.LocalEndPoint).Port
$ep = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse('127.0.0.1'), $port)
$ctor = $sinkType.GetConstructor([Reflection.BindingFlags]'NonPublic,Public,Instance', $null, [Type[]]@([System.Net.IPEndPoint]), $null)
$sink = $ctor.Invoke([object[]]@(,[System.Net.IPEndPoint]$ep))
$recv.Client.ReceiveTimeout = 3000
$sendM = $sinkType.GetMethod('Send'); $closeM = $sinkType.GetMethod('Close')
$sendM.Invoke($sink, @("SCENARIO_ID:1,SPEED:1")) | Out-Null
$remote = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)
$bytes = $recv.Receive([ref]$remote)
Check 'W01 the UDP sink delivers a datagram as UTF-8 text' ([Text.Encoding]::UTF8.GetString($bytes) -eq 'SCENARIO_ID:1,SPEED:1')
$sendM.Invoke($sink, @(([string][char]0x99C5))) | Out-Null
$bytes = $recv.Receive([ref]$remote)
Check 'W02 non-ASCII text survives (UTF-8)' ([Text.Encoding]::UTF8.GetString($bytes) -eq ([string][char]0x99C5))
$closeM.Invoke($sink, @()) | Out-Null; $sendM.Invoke($sink, @('after close')) | Out-Null
Check 'W03 Send after Close does not throw and is counted as failed' (($sinkType.GetProperty('Failed', [Reflection.BindingFlags]'NonPublic,Public,Instance')).GetValue($sink) -ge 1)
$recv.Close()
$deadEp = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse('127.0.0.1'), 9)
$dead = $ctor.Invoke([object[]]@(,[System.Net.IPEndPoint]$deadEp))
for ($i = 0; $i -lt 50; $i++) { $sendM.Invoke($dead, @('x')) | Out-Null }
Check 'W04 sending to a port nobody listens on never throws (the application may not be running)' $true
$closeM.Invoke($dead, @()) | Out-Null

# ---------------------------------------------------------------------------------------------------------------------------------------------
# I - what the C# sender writes, byte for byte, into the REAL Overlay (Python, offscreen Qt, real UDP socket): real data updates the real HUD,
#     and only what was announced is drawn
# ---------------------------------------------------------------------------------------------------------------------------------------------
$ovPy = Join-Path $repo 'tests\telemetry_overlay_check.py'
$udpBusy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
$qtOk = $false
try { $qtOk = ((& python -c "import PyQt6.QtWidgets; print('ok')") -eq 'ok') } catch { $qtOk = $false }
if ((-not $udpBusy) -and $qtOk -and (Test-Path $ovPy)) {
    $h = NewH
    $h.Api.SpeedMps = 20.0; $h.Api.Location = 900.0; $h.Api.GradientRatio = -0.0125; $h.Api.SignalMps = 25.0; $h.Api.ForwardSignalMps = 11.0
    $h.Api.NextSectionLoc = 1500.0; $h.Api.GroundMps = 20.0; $h.Api.BrakeKind = 2; $h.Api.BrakeNotches = 5; $h.Api.Holding = $true
    $h.Api.Rates = [double[]]@(0.0, 0.2, 0.4, 0.6, 0.8, 1.0); $h.Api.MaxPa = 490000.0
    $h.Api.Stations.Add((NewStation 'A' 0.0)); $h.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000)); $h.Api.Stations.Add((NewStation 'C' 2000.0 -1 -1 $true)); $h.Api.Stations.Add((NewStation 'D' 3000.0 36400000 -1 $false $true))
    $h.Tick(); $h.Run(3, 16)
    $dump2 = Join-Path $testDir 'i-dump.txt'
    [IO.File]::WriteAllText($dump2, (($h.Sink.Sent -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
    Push-Location $repo
    try { $raw = (& python $ovPy $dump2 strict | Out-String) } finally { Pop-Location }       # not -I: the application's PyQt6 lives in the user site
    $r = $raw | ConvertFrom-Json
    Check 'I01 the real Overlay took the C# datagrams from the real UDP socket (no error)' (($r -ne $null) -and ($r.error -eq $null) -and ($r.values.current_scenario_id -eq 0))
    $v = $r.values
    Check 'I02 speed, time, location are the Legacy values in the contract units (72 km/h, 10:00:00.048, 900 m)' ((Near $v.bve_speed 72.0) -and ($v.bve_time_ms -eq 36000048) -and (Near $v.bve_location 900.0))
    Check 'I03 gradient, signal limit, forward signal limit and location, ground limit' ((Near $v.bve_gradient -12.5) -and (Near $v.bve_signal_limit 90.0) -and (Near $v.bve_fwd_sig_limit 39.6) -and (Near $v.bve_fwd_sig_loc 1500.0) -and (Near $v.map_head_limit 72.0) -and (Near $v.map_tail_limit 72.0))
    Check 'I04 next station, its time, the stations list and the scenario texts' ((Near $v.bve_next_loc 1000.0) -and ($v.bve_next_time -eq 36100000) -and ((@($v.station_names) -join ',') -eq 'A,B,C,D') -and ($v.meta_title -eq 'Title') -and ($v.bve_current_station_name -eq 'B'))
    Check 'I05 brake type, notches, holding, pressure rates and maximum' (($v.bve_btype -eq 'Smee') -and ($v.cab_brk_count -eq 5) -and ($v.has_holding_brake -eq $true) -and ((@($v.bve_pressure_rates | ForEach-Object { [double]$_ }) -join ',') -eq '0,0.2,0.4,0.6,0.8,1') -and (Near $v.bve_max_pressure 490.0))
    Check 'I06 what was never sent stays at the Overlay default (handle texts, BCP, BPP, vehicle length) and is not drawn' (($v.bve_rev_text -ne $null) -and ($v.bcPressure -eq 0) -and ($v.bpPressure -eq 0) -and ($v.bve_train_length -eq 20.0))
    $drawn = @($r.drawn)
    Check 'I07 the HUD draws time, speed and gradient from the real data' ((($drawn -join '|') -match '10:00:00') -and (($drawn -join '|') -match '72\.0 km/h') -and (($drawn -join '|') -match '-12\.5'))
    Check 'I08 the handle row is NOT drawn (no REV / POW / BRK text exists on Legacy) and its state is "unavailable"' ((-not ($drawn -contains $v.bve_rev_text)) -and ($r.states.handle -eq 'unavailable'))
    $okStates = $true; foreach ($k in 'time', 'time_left', 'speed', 'limit', 'dist', 'grad') { if ($r.states.$k -ne 'shown') { $okStates = $false } }
    Check 'I09 every other HUD item is shown' $okStates
    Check 'I10 the gate is ready (real telemetry of the generation received) and holds the sender announcement' ($r.ready -eq $true -and ((@($r.tokens) -join ',') -eq ((Tokens (Last $h)) -join ',')))
    Check 'I11 nothing was dropped as stale or invalid' (($r.stats.tel_stale -eq 0) -and ($r.stats.tel_invalid -eq 0) -and ($r.stats.tel_accepted -ge 3))
}
else {
    Write-Host ('SKIP (not counted as a pass) I01-I11 C# bytes into the real Overlay: UDP 54321 busy=' + $udpBusy + ' PyQt6=' + $qtOk)
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# Q - the unit of the gradient (L3-live finding: the HUD showed +0.0 / -0.0 because the Legacy API value is a RATIO, not per mille). The API value is read
#     raw (ILegacyApi.TryGradientRatio) and converted ONCE (x 1000) in the session; the contract key GRADIENT stays per mille.
# ---------------------------------------------------------------------------------------------------------------------------------------------
$GU = $fixAsm.GetType('TsScoringLegacyTelemetryTests.GradientUnit')
function GradLine([double]$ratio) { $x = NewH; $x.Api.GradientRatio = $ratio; $x.Tick(); return (Last $x) }
$dq = P (GradLine 0.01)
Check 'Q01 ratio 0.01 is written as GRADIENT 10 (10.0 per mille)' ((Near ([double]$dq['GRADIENT']) 10.0) -and ($dq['GRADIENT'] -eq '10'))
$dq = P (GradLine -0.0125)
Check 'Q02 ratio -0.0125 is written as GRADIENT -12.5 (sign and magnitude)' ((Near ([double]$dq['GRADIENT']) -12.5) -and ($dq['GRADIENT'] -eq '-12.5'))
$lq = GradLine 0.0
$dq = P $lq
Check 'Q03 ratio 0 is written as GRADIENT 0, and the group is still announced (a flat section is a real reading)' (($dq['GRADIENT'] -eq '0') -and ((Tokens $lq) -contains 'grad'))
$fracOk = $true
foreach ($pair in @(@(0.0003, 0.3), @(0.00125, 1.25), @(0.0000123, 0.0123), @(0.035, 35.0), @(-0.0004, -0.4), @(0.05, 50.0), @(1.0, 1000.0))) {
    $got = [double]((P (GradLine ([double]$pair[0])))['GRADIENT'])
    if (-not (Near $got ([double]$pair[1]) 1e-9)) { $fracOk = $false }
}
Check 'Q04 fractional ratios keep their precision (0.0003 -> 0.3, 0.00125 -> 1.25, 0.0000123 -> 0.0123, -0.0004 -> -0.4, 0.05 -> 50)' $fracOk
$ratioOne = [double](P (GradLine 0.01))['GRADIENT']
Check 'Q05 the per-mille value is what the HUD parser gets: not the raw ratio (0.01) and not 0' (($ratioOne -ne 0.01) -and ($ratioOne -ne 0.0) -and (Near $ratioOne 10.0))
$badOk = $true
foreach ($bad in @([double]::NaN, [double]::PositiveInfinity, [double]::NegativeInfinity, 1e306, -1e306)) {
    $lb = GradLine $bad
    $db = P $lb
    if ($db.ContainsKey('GRADIENT') -or ((Tokens $lb) -contains 'grad') -or (-not ((Tokens $lb) -contains 'speed'))) { $badOk = $false }
    if ($GU.GetMethod('IsValid').Invoke($null, @([double]$bad))) { $badOk = $false }
}
Check 'Q06 NaN, +/-Infinity and a ratio whose x1000 overflows leave the gradient out (key and token), the rest of the line intact' $badOk
$hq = NewH; $hq.Tick(); $hq.Api.Fail.Add('TryGradientRatio') | Out-Null; $hq.Run(1, 16)
$dq = P (Last $hq)
Check 'Q07 the API cannot be read: no GRADIENT key, no grad token (no default 0)' ((-not $dq.ContainsKey('GRADIENT')) -and (-not ((Tokens (Last $hq)) -contains 'grad')))
$hq = NewH; $hq.Tick(); $hq.Api.ThrowIn = 'TryGradientRatio'; $hq.Run(1, 16)
Check 'Q08 the API throws: nothing escapes, the line goes on without the gradient' ((-not (P (Last $hq)).ContainsKey('GRADIENT')) -and ($hq.Sink.Lines().Count -eq 2) -and ($hq.LinesSkipped -eq 0))
$conv = $GU.GetMethod('Convert')
Check 'Q09 the conversion is x 1000 and nothing else (0.01, -0.0125, 0, 0.0003)' ((Near ([double]$conv.Invoke($null, @(0.01))) 10.0 1e-12) -and (Near ([double]$conv.Invoke($null, @(-0.0125))) -12.5 1e-12) -and (([double]$conv.Invoke($null, @(0.0))) -eq 0.0) -and (Near ([double]$conv.Invoke($null, @(0.0003))) 0.3 1e-12))
# the datagram text: the converted value is in the line, in the invariant culture
$hq = NewH; $hq.Api.GradientRatio = 0.0125; $hq.Tick()
Check 'Q10 the UDP datagram carries GRADIENT:12.5 (the converted value), never GRADIENT:0.0125' (((Last $hq) -match ',GRADIENT:12\.5,') -and ((Last $hq) -notmatch 'GRADIENT:0\.0125'))
# the diagnostic of the unit: first valid gradient of each scenario instance only
$hq = NewH; $hq.Api.GradientRatio = 0.01; $hq.Tick(); $hq.Run(999, 16)
$gd = @($hq.Diag.Named('TEL_GRADIENT_FIRST'))
Check 'Q11 1000 Ticks write exactly one gradient diagnostic: raw API value, value after x 1000, reason' (($gd.Count -eq 1) -and ($gd[0] -ceq 'TEL_GRADIENT_FIRST raw=0.01 permille=10 reason=api-ratio-x1000') -and ($hq.Diag.Named('TEL_GRADIENT_NONZERO').Count -eq 0))
$hq.Opened($true); $hq.Api.Scenario = New-Object object; $hq.Api.GradientRatio = -0.0125; $hq.Created(); $hq.Run(500, 16)
$gd = @($hq.Diag.Named('TEL_GRADIENT_FIRST'))
Check 'Q12 a new scenario instance gets its own (one) diagnostic, with its own first value' (($gd.Count -eq 2) -and ($gd[1] -ceq 'TEL_GRADIENT_FIRST raw=-0.0125 permille=-12.5 reason=api-ratio-x1000'))
$hq = NewH; $hq.Api.GradientRatio = 0.0; $hq.Tick(); $hq.Run(200, 16); $hq.Api.GradientRatio = 0.02; $hq.Run(200, 16); $hq.Api.GradientRatio = 0.03; $hq.Run(200, 16)
Check 'Q13 a flat first reading is logged as such, and the first NON-zero one follows once (at most two lines per instance, never per Tick)' ((@($hq.Diag.Named('TEL_GRADIENT_FIRST')).Count -eq 1) -and (@($hq.Diag.Named('TEL_GRADIENT_FIRST'))[0] -ceq 'TEL_GRADIENT_FIRST raw=0 permille=0 reason=api-ratio-x1000') -and (@($hq.Diag.Named('TEL_GRADIENT_NONZERO')).Count -eq 1) -and (@($hq.Diag.Named('TEL_GRADIENT_NONZERO'))[0] -ceq 'TEL_GRADIENT_NONZERO raw=0.02 permille=20 reason=api-ratio-x1000'))
$hq = NewH; $hq.Api.GradientRatio = [double]::NaN; $hq.Tick(); $hq.Run(5, 16)
Check 'Q14 no valid gradient yet: no diagnostic' ($hq.Diag.Named('TEL_GRADIENT_FIRST').Count -eq 0)
$hq.Api.GradientRatio = 0.004; $hq.Run(3, 16)
Check 'Q15 the first VALID gradient is the one reported (raw 0.004 -> 4)' ((@($hq.Diag.Named('TEL_GRADIENT_FIRST')).Count -eq 1) -and (@($hq.Diag.Named('TEL_GRADIENT_FIRST'))[0] -ceq 'TEL_GRADIENT_FIRST raw=0.004 permille=4 reason=api-ratio-x1000'))
$hq = NewH; $hq.Diag.Throw = $true; $hq.Api.GradientRatio = 0.01; $hq.Run(5, 16)
Check 'Q16 a diagnostic that throws does not change the gradient on the line' (((P (Last $hq))['GRADIENT']) -eq '10')
$hq = NewH; $hq.Api.Meta = @('SecretTitle', 'SecretRoute', 'SecretVehicle', 'SecretAuthor', 'SecretComment'); $hq.Api.GradientRatio = 0.01; $hq.Run(5, 16)
$gtext = ($hq.Diag.Named('TEL_GRADIENT_FIRST')) -join "`n"
Check 'Q17 the gradient diagnostic carries numbers and fixed words only (no scenario text, no path)' (($gtext -match '^TEL_GRADIENT_FIRST raw=[-0-9.eE]+ permille=[-0-9.eE]+ reason=api-ratio-x1000$') -and ($gtext -notmatch 'Secret') -and ($gtext -notmatch '[A-Za-z]:\\'))
$dlq = Join-Path $testDir 'gradient-diag.log'
$hq = NewH; $hq.UseFileDiag($dlq); $hq.Api.GradientRatio = 0.01; $hq.Run(2000, 16); $hq.Dispose()
$gfl = @([IO.File]::ReadAllLines($dlq) | Where-Object { $_ -match 'TEL_GRADIENT' })
Check 'Q18 the file log: 2000 Ticks, exactly one gradient line in the TEL_ format of the log' (($gfl.Count -eq 1) -and ($gfl[0] -match '^\d\d:\d\d:\d\d\.\d{3} P=\d+ I=\d+ TEL_GRADIENT_FIRST raw=0\.01 permille=10 reason=api-ratio-x1000$'))
# nothing else moved: AVAIL, the other values, the scenario identity
$hq = NewH; $hq.Api.FreshWrapperEachCall = $true; $hq.Api.GradientRatio = 0.01; $hq.Tick(); $hq.Run(60, 16)
$qa = @($hq.Sink.Lines())
Check 'Q19 AVAIL is unchanged by the unit fix (same 14 tokens, calcg from the second line) and one instance / one SCENARIO_ID stays' ((((Tokens $qa[1]) -join ',') -eq 'brake_cab,brake_type,calcg,door,grad,loc,maplimit,meta,prates,siglimit,siglimit_ahead,speed,station,time') -and ($hq.Epochs -eq 1) -and (@($qa | ForEach-Object { (P $_)['SCENARIO_ID'] } | Select-Object -Unique).Count -eq 1))
$qd = P $qa[1]
Check 'Q20 the other values of the line are unchanged (speed 36 km/h of 10 m/s, location, time, signal limit 90)' ((Near ([double]$qd['SPEED']) 36.0) -and (Near ([double]$qd['LOCATION']) 1000.0) -and (Near ([double]$qd['SIGLIMIT']) 90.0))

# ---------------------------------------------------------------------------------------------------------------------------------------------
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"TELEMETRY-L3 PASS=$pass FAIL=$fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
