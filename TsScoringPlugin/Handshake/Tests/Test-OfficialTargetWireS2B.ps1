# PHASE SI-R2.2-S2b - offline C# tests of the OFFICIAL TARGET SUPPLY: the shared reader core and wire helper (OfficialTargetReader / OfficialTargetWire in Shared\StationListIdentity.cs)
# and the LEGACY sender (the real LegacyTelemetrySession over the fake of the Legacy API of the L3 fixture, with a FakeOfficialApi). The Current sender (Class1.cs) can not run offline:
# its host reads are held by the source-shape pins of tests\test_official_target_wire_s2b.py, by the scratch compile-check and, later, by the live runs of SI-R2.5 / SI-R2.6.
#
# HOW: the host independent product sources (Telemetry\Legacy\src except the Extension and AssemblyInfo, Telemetry\Shared, the two Current files the Legacy project links) and the
# fixtures (TelemetryTestFixture.cs, OfficialTargetS2bTestFixture.cs) are compiled TOGETHER, IN MEMORY, by the Windows PowerShell 5.1 compiler (C# 5; no msbuild, no DLL of the product
# is built or replaced). The only files this script writes are two small temporary files for the cross-language run (X); it removes them and a leftover is a FAIL (CLEAN).
#   G  golden table (tests\official_target_wire_golden.json): reading + list identity -> the exact OFFTGT part, for K T N U F and the boundaries
#   C  culture: the same parts, byte for byte, under six cultures
#   N  canonical numbers: a sweep of values never produces 2000.0 / 5.50 / +1 / -0 / 1e3 / NaN / Infinity and always round-trips
#   R  the reader core over a scripted host: classification, the one station read, an exception per read
#   L  the Legacy sender: key position, differential against the earlier sender, independence of every Tick, exception separation, no station group = no OFFTGT
#   X  cross-language: the parts of the golden table and of the Legacy runs are judged by the Python contract (python -I): the states are the expected ones
# Exit codes: 0 = every check passed, 1 = a check failed, 2 = INCONCLUSIVE (the sources do not compile / an input is missing). This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $Root -Parent) -Parent
$telRoot = Join-Path $Root 'Telemetry'
$goldenPath = Join-Path $repo 'tests\official_target_wire_golden.json'
$fixturePath = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$officialFixturePath = Join-Path $Root 'Tests\OfficialTargetS2bTestFixture.cs'

$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Inconclusive([string]$why) { Write-Host ('INCONCLUSIVE ' + $why); exit 2 }

foreach ($path in @($goldenPath, $fixturePath, $officialFixturePath, (Join-Path $telRoot 'Shared\StationListIdentity.cs'))) {
    if (-not (Test-Path -LiteralPath $path)) { Inconclusive ('missing: ' + $path) }
}
$golden = Get-Content -LiteralPath $goldenPath -Raw -Encoding UTF8 | ConvertFrom-Json

# ---- the test compile of the product sources --------------------------------------------------------------------------------------------------------------------------------
$files = @()
$files += Get-ChildItem (Join-Path $telRoot 'Legacy\src') -Filter *.cs | Where-Object { $_.Name -notin @('LegacyTelemetryExtension.cs', 'AssemblyInfo.cs') } | ForEach-Object { $_.FullName }
$files += Get-ChildItem (Join-Path $telRoot 'Shared') -Filter *.cs | ForEach-Object { $_.FullName }
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs')
$files += $fixturePath
$files += $officialFixturePath
$texts = New-Object System.Collections.Generic.List[string]
foreach ($file in $files) { $texts.Add([IO.File]::ReadAllText($file, [Text.Encoding]::UTF8)) }
$texts.Add(@'
using System;
namespace TSScoringPlugin.Telemetry
{
    // the one host dependent product class the L3 fixture names (it lives in LegacyTelemetryExtension.cs, which names AtsEX types and is NOT compiled here)
    internal sealed class FileTelemetryDiag : ITelemetryDiag
    {
        internal const string FileNamePrefix = "stub";
        internal const string Version = "stub";
        internal static string NameFor(int pid, string startStamp) { return "stub"; }
        internal static string DefaultPath() { return "stub"; }
        internal FileTelemetryDiag(string pathOverride) { }
        public void Event(string name, string detail) { }
    }
}
'@)
Add-Type -AssemblyName Microsoft.CSharp
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.GenerateInMemory = $true
$cp.TreatWarningsAsErrors = $false
foreach ($r in @('System.dll', 'System.Core.dll')) { $cp.ReferencedAssemblies.Add($r) | Out-Null }
$compiled = $provider.CompileAssemblyFromSource($cp, [string[]]$texts.ToArray())
if ($compiled.Errors.HasErrors) {
    foreach ($e in $compiled.Errors) { if (-not $e.IsWarning) { Write-Host ('  compile error: ' + $e.ErrorNumber + ' line ' + $e.Line + ' ' + $e.ErrorText) } }
    Inconclusive 'the product sources of this phase do not compile in memory'
}
$asm = $compiled.CompiledAssembly
Write-Host ('PREFLIGHT ' + $files.Count + ' sources compiled in memory (no file written)')

$probe = $asm.GetType('TsScoringLegacyTelemetryTests.OfficialWireProbe')
$invariant = [Globalization.CultureInfo]::InvariantCulture

function ParseReal([string]$text) {
    switch ($text) {
        'NaN' { return [double]::NaN }
        'Infinity' { return [double]::PositiveInfinity }
        '-Infinity' { return [double]::NegativeInfinity }
        'NegZero' { return [BitConverter]::Int64BitsToDouble([long]::MinValue) }
    }
    return [double]::Parse($text, [Globalization.NumberStyles]::Float, $invariant)
}
function GoldenPart($case) {
    $rd = $case.reading
    $listId = if ($null -eq $case.listId) { $null } else { [string]$case.listId }
    if ($rd.isNull) { return [string]$probe.GetMethod('Part').Invoke($null, @($true, $false, $false, 0, $false, 0, $false, [double]0.0, [double]0.0, [double]0.0, $listId)) }
    $args2 = @([bool]$false, [bool]$rd.hostNull, [bool]$rd.cursorOk, [int]$rd.cursor, [bool]$rd.countOk, [int]$rd.count, [bool]$rd.nextOk, (ParseReal ([string]$rd.loc)), (ParseReal ([string]$rd.marginMin)), (ParseReal ([string]$rd.marginMax)), $listId)
    return [string]$probe.GetMethod('Part').Invoke($null, $args2)
}
function Real([double]$value) { return $probe.GetMethod('Real').Invoke($null, @($value)) }
$canonicalPattern = '^-?(0|[1-9][0-9]{0,14})(\.[0-9]{0,16}[1-9])?$'

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# G - the golden table
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Check 'G00 the golden table has the five states and at least 40 cases' (($golden.cases.Count -ge 40) -and ((@($golden.cases | ForEach-Object { $_.state } | Sort-Object -Unique) -join '') -ceq 'FKNTU'))
$goldenParts = @{}
foreach ($case in $golden.cases) {
    $got = GoldenPart $case
    $goldenParts[[string]$case.id] = $got
    if ($case.canonicalOnly) {
        $m = [regex]::Match($got, '^OFFTGT:1:K:1:4:E1D70409:([^:]+):5:5$')
        $okForm = $m.Success -and ($m.Groups[1].Value -match $canonicalPattern) -and ([double]::Parse($m.Groups[1].Value, [Globalization.NumberStyles]::Float, $invariant) -eq (ParseReal ([string]$case.reading.loc)))
        Check ('G-' + $case.id + ' canonical form and the value is kept') $okForm
    } else {
        Check ('G-' + $case.id + ' ' + $case.expected) ($got -ceq [string]$case.expected)
    }
}

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# C - six cultures, byte for byte
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$referenceJoin = (($golden.cases | ForEach-Object { $goldenParts[[string]$_.id] }) -join "`n")
$cultureOk = @()
$oldCulture = [Threading.Thread]::CurrentThread.CurrentCulture
$oldUiCulture = [Threading.Thread]::CurrentThread.CurrentUICulture
try {
    foreach ($name in @('en-US', 'de-DE', 'fr-FR', 'tr-TR', 'ar-SA', 'ja-JP')) {
        [Threading.Thread]::CurrentThread.CurrentCulture = New-Object Globalization.CultureInfo($name)
        [Threading.Thread]::CurrentThread.CurrentUICulture = New-Object Globalization.CultureInfo($name)
        $join = (($golden.cases | ForEach-Object { GoldenPart $_ }) -join "`n")
        $cultureOk += ($join -ceq $referenceJoin)
    }
} finally {
    [Threading.Thread]::CurrentThread.CurrentCulture = $oldCulture
    [Threading.Thread]::CurrentThread.CurrentUICulture = $oldUiCulture
}
Check 'C01 the parts of the whole golden table are byte for byte the same under en-US de-DE fr-FR tr-TR ar-SA ja-JP' ((@($cultureOk | Where-Object { -not $_ }).Count -eq 0) -and ($cultureOk.Count -eq 6))
Check 'C02 the key is OFFTGT and the version is 1' ((([string]$probe.GetProperty('Key').GetValue($null)) -ceq 'OFFTGT') -and (([int]$probe.GetProperty('Version').GetValue($null)) -eq 1))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# N - canonical numbers
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$edge = @(0.0, 1.0, -1.0, 2000.0, 570.04, -12.5, 5.5, 0.1, 0.2, 0.30000000000000004, 1e-5, 1e-6, 1e-16, 1.5e-17, 123456789.123456789, 999999999999999.0, 999999999999999.9, 100000.0, 1e14, 12345678901234.5,
    0.000123, 1e-10, 4.35, 2.675, 1.0000000000000002, 570.0399780273438, [double][single]570.04, [double][single]0.1)
$sweepFail = 0
$nullBad = 0
$random = New-Object System.Random(20261028)
$values = New-Object System.Collections.Generic.List[double]
foreach ($e in $edge) { $values.Add($e); $values.Add(-$e) }
for ($i = 0; $i -lt 3000; $i++) {
    $mag = [Math]::Pow(10.0, $random.Next(-8, 15))
    $values.Add(($random.NextDouble() - 0.5) * 2.0 * $mag)
    $values.Add([Math]::Round(($random.NextDouble() - 0.5) * 2.0 * $mag, $random.Next(0, 6)))
}
foreach ($value in $values) {
    $text = Real $value
    if ($null -eq $text) {
        if (-not (([Math]::Abs($value) -lt 1e-16) -and ($value -ne 0.0))) { $nullBad++ }
        continue
    }
    if (($text -cnotmatch $canonicalPattern) -or ($text -ceq '-0')) { $sweepFail++; if ($sweepFail -le 5) { Write-Host ('  not canonical: ' + $value.ToString('R', $invariant) + ' -> ' + $text) }; continue }
    $back = [double]::Parse($text, [Globalization.NumberStyles]::Float, $invariant)
    # exact up to 17 significant digits; only a value that needs more than 17 fraction digits (about 0.1 or less with 16-17 significant digits) falls back to the 15 significant digits of the custom format
    if (($value -ne 0.0) -and ([Math]::Abs($back - $value) -gt [Math]::Max([Math]::Abs($value) * 1e-14, 1e-17))) { $sweepFail++; if ($sweepFail -le 5) { Write-Host ('  no read back: ' + $value.ToString('R', $invariant) + ' -> ' + $text) } }
}
Check ('N01 ' + $values.Count + ' sampled values: every text is canonical (no exponent, no trailing zero, no -0, no plus) and reads back as the value') ($sweepFail -eq 0)
Check 'N02 only a value without a canonical text (non-finite, 1e15 or more, or a non-zero value that rounds to zero) is refused' ($nullBad -eq 0)
Check 'N03 the named forms are never produced: 2000.0 5.50 +1 -0 1e3 NaN Infinity' (((Real 2000.0) -ceq '2000') -and ((Real 5.5) -ceq '5.5') -and ((Real 1.0) -ceq '1') -and ((Real ([BitConverter]::Int64BitsToDouble([long]::MinValue))) -ceq '0') -and ((Real 1000.0) -ceq '1000') -and ($null -eq (Real ([double]::NaN))) -and ($null -eq (Real ([double]::PositiveInfinity))) -and ($null -eq (Real ([double]::NegativeInfinity))))
Check 'N04 15 integer digits are the limit: 999999999999999 is written, 1e15 is refused' (((Real 999999999999999.0) -ceq '999999999999999') -and ($null -eq (Real 1e15)) -and ($null -eq (Real -1e15)))
Check 'N05 a small value is written as a fixed decimal, never with an exponent' (((Real 0.00001) -ceq '0.00001') -and ((Real -0.00001) -ceq '-0.00001'))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# R - the reader core over a scripted host
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
function ReadHost([string]$mode, [int]$cursor, [int]$count, [string]$listId = 'E1D70409') {
    return [string]$probe.GetMethod('Read').Invoke($null, @($mode, $cursor, $count, [double]1000.0, [double]-5.0, [double]10.0, $listId))
}
$zeroId = '00000000'
Check 'R01 the target is the station CurrentIndex + 1: one station read, for exactly that index' ((ReadHost 'ok' 0 4) -ceq 'OFFTGT:1:K:1:4:E1D70409:1000:5:10|1|1|-')
Check 'R02 CurrentIndex -1 reads station 0' ((ReadHost 'ok' -1 4) -ceq 'OFFTGT:1:K:0:4:E1D70409:1000:5:10|1|0|-')
Check 'R03 a terminal (CurrentIndex + 1 = Count) reads no station' ((ReadHost 'ok' 3 4) -ceq 'OFFTGT:1:T:-1:4:E1D70409:-1:-1:-1|0|-1|-')
Check 'R04 an empty list is N and reads no station' ((ReadHost 'ok' 0 0) -ceq ('OFFTGT:1:N:-1:0:' + $zeroId + ':-1:-1:-1|0|-1|-'))
Check 'R05 a cursor out of the range -1..Count-1 is F and reads no station (above and below)' (((ReadHost 'ok' 4 4) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|-')) -and ((ReadHost 'ok' -2 4) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|-')))
Check 'R06 a negative Count is F' ((ReadHost 'ok' 0 -1) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|-'))
Check 'R07 a host that is not ready (the station list is null) is U and nothing else is read' ((ReadHost 'null-stations' 0 4) -ceq ('OFFTGT:1:U:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|-'))
Check 'R08 an exception while reaching the list is F (the exception type is kept for the diagnostic only)' ((ReadHost 'throw-stations' 0 4) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|InvalidOperationException'))
Check 'R09 an exception in the cursor read is F' ((ReadHost 'throw-cursor' 0 4) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|ArgumentException'))
Check 'R10 an exception in the Count read is F' ((ReadHost 'throw-count' 0 4) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|0|-1|NotSupportedException'))
Check 'R11 an exception in the station read is F, never a K with a missing part' ((ReadHost 'throw-station' 0 4) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1|1|1|IndexOutOfRangeException'))
Check 'R12 the exception text never enters the wire' ((@('ok', 'throw-stations', 'throw-cursor', 'throw-count', 'throw-station') | Where-Object { ((ReadHost $_ 0 4).Split('|')[0]) -match 'Exception|Invalid|Argument|Supported|Range' }).Count -eq 0)
Check 'R13 an invalid identity is written as 00000000 and a lower case one in upper case' (((ReadHost 'ok' 0 4 'nothash') -ceq ('OFFTGT:1:K:1:4:' + $zeroId + ':1000:5:10|1|1|-')) -and ((ReadHost 'ok' 0 4 'e1d70409') -ceq 'OFFTGT:1:K:1:4:E1D70409:1000:5:10|1|1|-'))
Check 'R14 the placeholders are the fixed U and F forms; any other word is written as F' ((([string]$probe.GetMethod('Placeholder').Invoke($null, @('U'))) -ceq ('OFFTGT:1:U:-1:-1:' + $zeroId + ':-1:-1:-1')) -and (([string]$probe.GetMethod('Placeholder').Invoke($null, @('F'))) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1')) -and (([string]$probe.GetMethod('Placeholder').Invoke($null, @('K'))) -ceq ('OFFTGT:1:F:-1:-1:' + $zeroId + ':-1:-1:-1')))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# L - the Legacy sender
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
function NewStation([string]$name, [double]$loc, [int]$arr = -1, [int]$dep = -1, [bool]$pass = $false, [bool]$term = $false, [int]$side = 1, [int]$stop = 15000) {
    $station = [Activator]::CreateInstance($asm.GetType('TsScoringLegacyTelemetryTests.FakeStation'))
    $station.Name = $name; $station.Location = $loc; $station.ArrivalMs = $arr; $station.DepartureMs = $dep; $station.Pass = $pass; $station.IsTerminal = $term; $station.DoorSide = $side; $station.StoppageMs = $stop
    return $station
}
function NewOfficialHarness([bool]$wired) { return [Activator]::CreateInstance($asm.GetType('TsScoringLegacyTelemetryTests.OfficialHarness'), @($wired)) }
function Stations4() { return @((NewStation 'A' 0.0), (NewStation 'B' 1000.0 36060000 36080000 $false $false 1 20000), (NewStation 'C' 2000.0 36200000 36220000), (NewStation 'D' 3000.0 36300000 -1 $false $true)) }
function Setup($harness, $stationList, [double]$loc) {
    foreach ($station in $stationList) { $harness.Api.Stations.Add($station) }
    $harness.Api.Location = $loc; $harness.Api.SpeedMps = 0.0; $harness.Api.DoorsClosed = $true
}
function Lines($harness) { return @(@($harness.Sink.Sent.ToArray()) | Where-Object { $_.StartsWith('SCENARIO_ID:') }) }
function StripOfficial([string]$line) { return [regex]::Replace($line, ',OFFTGT:[^,]*', '') }
function SetOfficial($harness, [string]$state) {
    $api = $harness.Official
    $api.Null = $false; $api.HostNull = $false; $api.CursorOk = $true; $api.CountOk = $true; $api.NextOk = $true; $api.Throw = $false
    switch ($state) {
        'K' { $api.Cursor = 0; $api.Count = 4; $api.Location = 1000.0; $api.MarginMin = -5.0; $api.MarginMax = 10.0 }
        'K2' { $api.Cursor = 1; $api.Count = 4; $api.Location = 2000.5; $api.MarginMin = -4.5; $api.MarginMax = 6.0 }
        'T' { $api.Cursor = 3; $api.Count = 4 }
        'N' { $api.Cursor = 0; $api.Count = 0 }
        'U' { $api.HostNull = $true }
        'Unull' { $api.Null = $true }
        'F' { $api.Throw = $true }
        'Fcursor' { $api.CursorOk = $false }
    }
}

# the same scripted run through (a) a session with the official surface, (b) the earlier nine-argument session, (c) the ten-argument constructor with null
function Run-Script($harness, [bool]$setOfficial) {
    Setup $harness (Stations4) 0.0
    $steps = @(
        @(0.0, 0.0, $true, 'K'), @(10.0, 3.0, $true, 'K'), @(20.0, 5.0, $true, 'K2'), @(30.0, 5.0, $true, 'T'), @(40.0, 5.0, $true, 'U'), @(50.0, 5.0, $true, 'F'), @(60.0, 5.0, $true, 'K'),
        @(70.0, 5.0, $true, 'Unull'), @(80.0, 5.0, $true, 'Fcursor'), @(90.0, 5.0, $true, 'N'), @(100.0, 5.0, $true, 'K'), @(1000.0, 0.0, $false, 'K'), @(1000.0, 0.0, $true, 'K'))
    foreach ($step in $steps) {
        if ($setOfficial -and ($null -ne $harness.Official)) { SetOfficial $harness $step[3] }
        $harness.Api.Location = [double]$step[0]; $harness.Api.SpeedMps = [double]$step[1]; $harness.Api.DoorsClosed = [bool]$step[2]
        $harness.Run(1, 16)
    }
}
$wiredRun = NewOfficialHarness $true;  Run-Script $wiredRun $true
$plainRun = NewOfficialHarness $false; Run-Script $plainRun $false
$nineRun = $asm.GetType('TsScoringLegacyTelemetryTests.OfficialHarness').GetMethod('WithTheNineArgumentConstructor').Invoke($null, @())
Run-Script $nineRun $false
$wiredLines = Lines $wiredRun
$plainLines = Lines $plainRun
$nineLines = Lines $nineRun
Check 'L01 lines were sent in all three runs and every line of the wired run carries exactly one OFFTGT key' (($wiredLines.Count -ge 13) -and ($plainLines.Count -eq $wiredLines.Count) -and ($nineLines.Count -eq $wiredLines.Count) -and (@($wiredLines | Where-Object { ([regex]::Matches($_, ',OFFTGT:')).Count -ne 1 }).Count -eq 0))
Check 'L02 the key follows STIDX directly: it is the last key of the station group (STIDX, OFFTGT, then the next group)' (@($wiredLines | Where-Object { $_ -notmatch ',STIDX:1:-?\d+:-?\d+:\d+:\d+:[0-9A-F]{8},OFFTGT:1:[KTNUF]:' }).Count -eq 0)
Check 'L03 the earlier senders (no official surface; the nine-argument constructor) write no OFFTGT at all and write the same lines' ((@($plainLines | Where-Object { $_ -match 'OFFTGT' }).Count -eq 0) -and (@($nineLines | Where-Object { $_ -match 'OFFTGT' }).Count -eq 0) -and (($plainLines -join "`n") -ceq ($nineLines -join "`n")))
Check 'L04 differential: with the OFFTGT key removed, every line of the wired run is byte for byte the line of the earlier sender (AVAIL, every token, every key, the order)' ((($wiredLines | ForEach-Object { StripOfficial $_ }) -join "`n") -ceq ($plainLines -join "`n"))
$wiredTexts = @($wiredRun.Sink.Sent.ToArray())
$plainTexts = @($plainRun.Sink.Sent.ToArray())
Check 'L05 every other text (STALIST, META) of the wired run is the text of the earlier sender and carries no OFFTGT' ((@($wiredTexts | Where-Object { -not $_.StartsWith('SCENARIO_ID:') }) -join "`n") -ceq (@($plainTexts | Where-Object { -not $_.StartsWith('SCENARIO_ID:') }) -join "`n"))
Check 'L06 AVAIL announces the station group exactly as before (OFFTGT is a key of that group, not a token)' (@($wiredLines | Where-Object { ([regex]::Match($_, 'AVAIL:1:[^,]*').Value) -cne ([regex]::Match((StripOfficial $_), 'AVAIL:1:[^,]*').Value) }).Count -eq 0)

$listHash = [regex]::Match($wiredLines[0], ',STIDX:1:-?\d+:-?\d+:\d+:\d+:([0-9A-F]{8})').Groups[1].Value
$kPart = 'OFFTGT:1:K:1:4:' + $listHash + ':1000:5:10'
$partOf = @($wiredLines | ForEach-Object { [regex]::Match($_, 'OFFTGT:[^,]*').Value })
if ($env:TS_S2B_VERBOSE) { for ($i = 0; $i -lt $partOf.Count; $i++) { Write-Host ('  part ' + $i + ' ' + $partOf[$i]) } }
Check 'L07 each Tick is its own reading: K K K2 T U F K Unull Fcursor N K K K, in that order, one value per Tick' (
    ($partOf[0] -ceq $kPart) -and ($partOf[1] -ceq $kPart) -and ($partOf[2] -cmatch '^OFFTGT:1:K:2:4:[0-9A-F]{8}:2000\.5:4\.5:6$') -and ($partOf[3] -cmatch '^OFFTGT:1:T:-1:4:[0-9A-F]{8}:-1:-1:-1$') -and
    ($partOf[4] -ceq 'OFFTGT:1:U:-1:-1:00000000:-1:-1:-1') -and ($partOf[5] -ceq 'OFFTGT:1:F:-1:-1:00000000:-1:-1:-1') -and ($partOf[6] -ceq $kPart) -and
    ($partOf[7] -ceq 'OFFTGT:1:U:-1:-1:00000000:-1:-1:-1') -and ($partOf[8] -ceq 'OFFTGT:1:F:-1:-1:00000000:-1:-1:-1') -and ($partOf[9] -ceq 'OFFTGT:1:N:-1:0:00000000:-1:-1:-1') -and
    ($partOf[10] -ceq $kPart) -and ($partOf[11] -ceq $kPart) -and ($partOf[12] -ceq $kPart))
Check 'L08 an earlier K is never sent again: after U and after F the part is the U and the F form, then the next K is read afresh' (($partOf[4] -cmatch ':U:') -and ($partOf[5] -cmatch ':F:') -and ($partOf[6] -cmatch ':K:') -and ($partOf[7] -cmatch ':U:') -and ($partOf[8] -cmatch ':F:'))
$hashOk = @(0..($wiredLines.Count - 1) | Where-Object {
    $stidx = [regex]::Match($wiredLines[$_], ',STIDX:1:-?\d+:-?\d+:\d+:(\d+):([0-9A-F]{8})')
    $off = [regex]::Match($partOf[$_], '^OFFTGT:1:([KT]):-?\d+:(\d+):([0-9A-F]{8}):')
    $off.Success -and (($off.Groups[3].Value -cne $stidx.Groups[2].Value) -or ($off.Groups[2].Value -cne $stidx.Groups[1].Value))
})
Check 'L09 the identity of a K or T part is the identity of the list of the same line (the hash of STIDX), and its count is the host Count (4)' ($hashOk.Count -eq 0)
Check 'L10 the official surface is read once per line that has a station group' (($wiredRun.Official.Calls) -eq $wiredLines.Count)
Check 'L11 a read that throws writes the F form and changes no other key, no STALIST and no AVAIL (the differential of L04 includes that Tick)' (($partOf[5] -ceq 'OFFTGT:1:F:-1:-1:00000000:-1:-1:-1') -and ((StripOfficial $wiredLines[5]) -ceq $plainLines[5]))

# no station group -> no OFFTGT (the doors can not be read: neither group is announced); never F, never a repeated value
$noGroup = NewOfficialHarness $true
Setup $noGroup (Stations4) 0.0
SetOfficial $noGroup 'K'
$noGroup.Run(1, 16)
$noGroup.Api.Fail.Add('TryDoorsClosed') | Out-Null
$noGroup.Run(2, 16)
$noGroup.Api.Fail.Remove('TryDoorsClosed') | Out-Null
$noGroup.Run(1, 16)
$ngLines = Lines $noGroup
Check 'L12 while the doors can not be read there is no station group and no OFFTGT (no F, no earlier K); with the doors back the key is there again' (($ngLines.Count -eq 4) -and ($ngLines[0] -match 'OFFTGT:1:K:') -and ($ngLines[1] -notmatch 'OFFTGT') -and ($ngLines[2] -notmatch 'OFFTGT') -and ($ngLines[3] -match 'OFFTGT:1:K:') -and ($noGroup.Official.Calls -eq 2))
# an empty list: the group is there (count 0), so the key is there; the value is the host's
$emptyList = NewOfficialHarness $true
$emptyList.Api.Location = 100.0; $emptyList.Api.SpeedMps = 10.0
SetOfficial $emptyList 'N'
$emptyList.Run(2, 16)
$elLines = Lines $emptyList
Check 'L13 an empty station list still has the group: the key is the N form of the host reading' (($elLines.Count -ge 1) -and (@($elLines | Where-Object { $_ -notmatch ',STIDX:1:-1:-1:0:0:00000000,OFFTGT:1:N:-1:0:00000000:-1:-1:-1(,|$)' }).Count -eq 0))
Check 'L14 the key never reaches the STALIST or META texts, the heartbeat or the AVAIL value' (@(@($wiredRun.Sink.Sent.ToArray()) | Where-Object { (-not $_.StartsWith('SCENARIO_ID:')) -and ($_ -match 'OFFTGT') }).Count -eq 0)

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# X - cross-language: the Python contract judges the parts C# wrote
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$expectedState = @{ 'K' = 'KNOWN'; 'T' = 'NONE_TERMINAL'; 'N' = 'NONE_EMPTY'; 'U' = 'UNAVAILABLE'; 'F' = 'READ_FAILED' }
$dumpPath = Join-Path $env:TEMP ('ts-s2b-parts-' + [guid]::NewGuid().ToString('N') + '.tsv')
$pyPath = Join-Path $env:TEMP ('ts-s2b-judge-' + [guid]::NewGuid().ToString('N') + '.py')
$script:cleanFiles = @($dumpPath, $pyPath)
$rows = New-Object System.Collections.Generic.List[string]
foreach ($case in $golden.cases) { $rows.Add($goldenParts[[string]$case.id] + "`t" + $expectedState[[string]$case.state]) }
foreach ($line in $wiredLines) {
    $part = [regex]::Match($line, 'OFFTGT:[^,]*').Value
    $word = $part.Split(':')
    $rows.Add($part + "`t" + $(if (($word.Count -gt 2) -and $expectedState.ContainsKey($word[2])) { $expectedState[$word[2]] } else { 'MISSING' }))
}
$crossOk = $false
$crossRows = 0
try {
    [IO.File]::WriteAllLines($dumpPath, $rows.ToArray(), (New-Object Text.UTF8Encoding($false)))
    $pyText = @'
import sys
sys.path.insert(0, sys.argv[1])
import official_target_contract as C
bad = 0
count = 0
for row in open(sys.argv[2], encoding="ascii").read().splitlines():
    part, expect = row.split("\t")
    wire, why = C.decode(part)
    if wire is None:
        print("BAD-DECODE\t" + part + "\t" + str(why)); bad += 1; continue
    station_list = [{"location": wire["loc"] if i == wire["idx"] else 0.0} for i in range(max(wire["count"], 0))]
    result, scope_ok = C.evaluate(part, station_list, wire["hash"], 0)
    count += 1
    if result["official_state"] != expect or not scope_ok:
        print("BAD-STATE\t" + part + "\t" + result["official_state"] + "\t" + expect); bad += 1
    elif expect == "KNOWN" and (result["official_index"] != wire["idx"] or abs(result["official_location"] - wire["loc"]) > 0.01):
        print("BAD-VALUE\t" + part); bad += 1
print("ROWS\t%d\tBAD\t%d" % (count, bad))
'@
    [IO.File]::WriteAllText($pyPath, $pyText, (New-Object Text.UTF8Encoding($false)))
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $py) { Inconclusive 'python is not on the PATH' }
    $output = @(& python -I $pyPath $repo $dumpPath)
    $summary = @($output | Where-Object { $_ -match '^ROWS\t' })
    foreach ($bad in @($output | Where-Object { $_ -match '^BAD' })) { Write-Host ('  ' + $bad) }
    if ($summary.Count -eq 1) {
        $parts = $summary[0].Split("`t")
        $crossRows = [int]$parts[1]
        $crossOk = ($parts[3] -eq '0') -and ($crossRows -eq $rows.Count)
    }
} finally {
    foreach ($path in $script:cleanFiles) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } }
}
Check ('X01 the Python contract (python -I) decodes and judges all ' + $rows.Count + ' parts (golden table and Legacy runs) as the state the sender meant; a K keeps its index and location') $crossOk
Check 'CLEAN no temporary file of this run is left' (@($script:cleanFiles | Where-Object { Test-Path -LiteralPath $_ }).Count -eq 0)

Write-Host ('SUMMARY pass=' + $script:pass + ' fail=' + $script:fail)
if ($script:fail -gt 0) { exit 1 }
exit 0
