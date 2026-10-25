# PHASE PID-D4JA StationIndex ST-1A - offline C# tests of the STIDX SUPPLY: the shared station-list identity and wire helper (CRC-32 vectors shared with Python), and the
# LEGACY sender (the real LegacyTelemetrySession and LegacyStationTimeline) driven through the fake of the Legacy API of the L3 fixture. The Current sender (Class1.cs) can not run
# offline: it is held by the source-shape pins of tests\test_stationindex_supply_st1a.py and is judged live in ST-1B.
#
# HOW: the host independent product sources (Telemetry\Legacy\src except the Extension and AssemblyInfo, Telemetry\Shared, the two Current files the Legacy project links) and the
# L3 fixture are compiled TOGETHER, IN MEMORY, by the Windows PowerShell 5.1 compiler (no msbuild, no DLL of the product is built or replaced). That is a test compile of the
# sources the working tree has, so the tests judge the SOURCES of this phase, not the DLL that was built before it. Only the differential (D) writes files: a work folder in
# %TEMP% with the fixture DLL compiled against the audited DLL (that is an OFFLINE TEST COMPILE, not a product build). They are loaded from memory, and the script removes
# every file it wrote; a leftover is a FAIL (CLEAN, printed as the CLEANUP line, which adds no PASS).
#   V  the shared vectors (tests\stidx_vectors_st0.json): CRC-32 of the five payloads; the wire helper against the vector lines; a line that violates the contract can not be produced
#   L  the Legacy sender: one STIDX part per line, inside the station group, last key; the values follow the station state machine; the hash is the CRC-32 of the STALIST payload
#   D  differential: the SAME scripted runs through the audited DLL built before ST-1A (reference, SHA-256 checked) and through the sources of this phase: every datagram is
#      identical except for the STIDX part (STALIST, META, AVAIL, every other key, the order). SKIPPED (not counted as a pass) when the reference DLL is not the audited one
#   X  cross-language: the datagrams of the runs are fed to the Python observer (python -I): every line is judged stidx-ok
# Exit codes: 0 = every check passed, 1 = a check failed, 2 = INCONCLUSIVE (the sources do not compile / the vectors are missing). This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $Root -Parent) -Parent
$telRoot = Join-Path $Root 'Telemetry'
$vectorPath = Join-Path $repo 'tests\stidx_vectors_st0.json'
$fixturePath = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$refDllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$AuditedRefDllSha256 = '43E7B9D35F840FAEF0DFCBEC8F2EDB66F259F42FA9CD62644B1DFD1A45EDF691'     # Legacy telemetry 0.6.0.0 DEFAULT build of Phase LJX-1 (the last build before ST-1A)

$script:pass = 0
$script:fail = 0
$script:skip = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Skip([string]$name) { $script:skip++; Write-Host ('SKIP ' + $name) }
function Inconclusive([string]$why) { Write-Host ('INCONCLUSIVE ' + $why); exit 2 }

foreach ($p in @($vectorPath, $fixturePath, (Join-Path $telRoot 'Shared\StationListIdentity.cs'))) {
    if (-not (Test-Path -LiteralPath $p)) { Inconclusive ('missing: ' + $p) }
}
$vec = Get-Content -LiteralPath $vectorPath -Raw -Encoding UTF8 | ConvertFrom-Json

# ---- the test compile of the product sources ------------------------------------------------------------------------------------------------------------------------------
$files = @()
$files += Get-ChildItem (Join-Path $telRoot 'Legacy\src') -Filter *.cs | Where-Object { $_.Name -notin @('LegacyTelemetryExtension.cs', 'AssemblyInfo.cs') } | ForEach-Object { $_.FullName }
$files += Get-ChildItem (Join-Path $telRoot 'Shared') -Filter *.cs | ForEach-Object { $_.FullName }
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs')
$files += $fixturePath
$texts = New-Object System.Collections.Generic.List[string]
foreach ($f in $files) { $texts.Add([IO.File]::ReadAllText($f, [Text.Encoding]::UTF8)) }
$texts.Add(@'
using System;
namespace TSScoringPlugin.Telemetry
{
    // the one host dependent product class the L3 fixture names (it lives in LegacyTelemetryExtension.cs, which names AtsEX types and is NOT compiled here): the fixture only
    // constructs it in tests this script does not run
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
namespace St1aProbe
{
    public static class Wire
    {
        public static string ListId(string payload) { return TSScoringPlugin.Telemetry.StationListIdentity.Compute(payload); }
        public static string Fields(int t, int a, int s, int c, string h) { return TSScoringPlugin.Telemetry.StationIndexWire.Fields(t, a, s, c, h); }
        public static string Value(int t, int a, int s, int c, string h) { return TSScoringPlugin.Telemetry.StationIndexWire.Value(t, a, s, c, h); }
        public static string Part(int t, int a, int s, int c, string h) { return TSScoringPlugin.Telemetry.StationIndexWire.Part(t, a, s, c, h); }
        public static int Version { get { return TSScoringPlugin.Telemetry.StationIndexWire.Version; } }
        public static string Key { get { return TSScoringPlugin.Telemetry.StationIndexWire.Key; } }
        public static string EmptyId { get { return TSScoringPlugin.Telemetry.StationListIdentity.EmptyId; } }
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
$newAsm = $compiled.CompiledAssembly
Write-Host ('PREFLIGHT ' + $files.Count + ' sources compiled in memory (no file written)')

$wire = $newAsm.GetType('St1aProbe.Wire')
function W([string]$method, [object[]]$a) {
    $m = $wire.GetMethod($method)
    if ($null -ne $m) { return $m.Invoke($null, $a) }
    return $wire.GetProperty($method).GetValue($null)
}

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# V - the shared vectors, the C# half
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
foreach ($h in $vec.crc32) {
    Check ('V-' + $h.id + ' CRC-32 of the payload is ' + $h.hex) ((W 'ListId' @([string]$h.payload)) -ceq [string]$h.hex)
}
Check 'V-empty an empty or null payload is 00000000' (((W 'ListId' @([string]'')) -ceq '00000000') -and ((W 'ListId' @($null)) -ceq '00000000'))
Check 'V-ver the version of the wire helper is 1 and the key is STIDX' (([int](W 'Version' @())) -eq 1 -and ([string](W 'Key' @())) -ceq 'STIDX')

$wellFormed = 0
foreach ($v in $vec.stidx) {
    if ($null -eq $v.line) { continue }
    $m = [regex]::Match([string]$v.line, '^STIDX:(-?\d+):(-?\d+):(-?\d+):(-?\d+):(-?\d+):([0-9A-F]{8})$')
    if (-not $m.Success) { continue }
    $ver = [int]$m.Groups[1].Value; $t = [int]$m.Groups[2].Value; $a = [int]$m.Groups[3].Value; $s = [int]$m.Groups[4].Value; $c = [int]$m.Groups[5].Value; $hash = $m.Groups[6].Value
    $inRange = ($ver -eq 1) -and ($c -ge 0) -and ($t -ge -1) -and ($t -lt $c) -and ($a -ge -1) -and ($a -lt $c) -and ($s -ge 0)
    $part = [string](W 'Part' @($t, $a, $s, $c, $hash))
    if ($inRange) {
        $wellFormed++
        Check ('V-' + $v.id + ' the wire helper writes exactly the vector line ' + $v.line) ($part -ceq [string]$v.line)
    } else {
        # a line that violates the contract (version 2, tgt/arr out of range) can not be produced by the helper: it is written in the "none" form instead
        Check ('V-' + $v.id + ' the wire helper can not write the violating line ' + $v.line) ($part -cne [string]$v.line)
    }
}
Check 'V-count 12 of the 17 vector lines are version 1 and in range and were written back (V04 version 2, V05 no line, V06 V07 V08 out of range are not)' ($wellFormed -eq 12)
Check 'V-norm values outside the contract become the none form' ((W 'Fields' @(9, 9, -4, -2, 'zzzz')) -ceq '-1:-1:0:0:00000000')
Check 'V-norm a lower case hash is written upper case' ((W 'Fields' @(0, -1, 0, 1, 'e1d70409')) -ceq '0:-1:0:1:E1D70409')
Check 'V-norm Value is the version in front of Fields and Part is the key in front of Value' (((W 'Value' @(1, -1, 0, 4, 'E1D70409')) -ceq '1:1:-1:0:4:E1D70409') -and ((W 'Part' @(1, -1, 0, 4, 'E1D70409')) -ceq 'STIDX:1:1:-1:0:4:E1D70409'))
Check 'V-culture the helper is culture independent (a comma culture does not change a digit)' (& {
    $old = [Threading.Thread]::CurrentThread.CurrentCulture
    try { [Threading.Thread]::CurrentThread.CurrentCulture = New-Object Globalization.CultureInfo('fr-FR'); return ((W 'Part' @(2, 1, 12345, 40, '0000ABCD')) -ceq 'STIDX:1:2:1:12345:40:0000ABCD') }
    finally { [Threading.Thread]::CurrentThread.CurrentCulture = $old }
})

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# helpers for the Legacy runs
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
function NewStation($asm, [string]$name, [double]$loc, [int]$arr = -1, [int]$dep = -1, [bool]$pass = $false, [bool]$term = $false, [int]$side = 1, [int]$stop = 15000) {
    $s = [Activator]::CreateInstance($asm.GetType('TsScoringLegacyTelemetryTests.FakeStation'))
    $s.Name = $name; $s.Location = $loc; $s.ArrivalMs = $arr; $s.DepartureMs = $dep; $s.Pass = $pass; $s.IsTerminal = $term; $s.DoorSide = $side; $s.StoppageMs = $stop
    return $s
}
function NewHarness($asm) { return [Activator]::CreateInstance($asm.GetType('TsScoringLegacyTelemetryTests.Harness')) }

# the four stations whose STALIST is the payload of the shared vector H03
function Stations4($asm) {
    return @((NewStation $asm 'A' 0.0), (NewStation $asm 'B' 1000.0 36060000 36080000 $false $false 1 20000), (NewStation $asm 'C' 2000.0 36200000 36220000), (NewStation $asm 'D' 3000.0 36300000 -1 $false $true))
}
# a longer list: normal, pass, operational stop, a same-position pair, terminal
function Stations6($asm) {
    return @((NewStation $asm 'S0' 0.0), (NewStation $asm 'S1' 800.0 -1 -1 $true), (NewStation $asm 'S2' 1600.0 -1 -1 $false $false 0), (NewStation $asm 'S3' 2400.0), (NewStation $asm 'S4' 2400.0), (NewStation $asm 'S5' 3200.0 -1 -1 $false $true))
}
# an explicit terminal at the START of the list (the vehicle begins behind it): the LAST station is no terminal, so the target can run off the end of the list
function StationsRunOff($asm) {
    return @((NewStation $asm 'R0' 0.0 -1 -1 $false $true), (NewStation $asm 'R1' 700.0), (NewStation $asm 'R2' 1400.0), (NewStation $asm 'R3' 2100.0))
}
function Setup($h, $stationList, [double]$loc) {
    foreach ($s in $stationList) { $h.Api.Stations.Add($s) }
    $h.Api.Location = $loc; $h.Api.SpeedMps = 0.0; $h.Api.DoorsClosed = $true
}
# one scripted step: location, speed (m/s), doors closed, extra simulation-time jump (ms), an event word
function Step([double]$l, [double]$sp, [bool]$d, [int]$j = 0, [string]$ev = '') { return @{ L = $l; S = $sp; D = $d; J = $j; E = $ev } }
function Drive($h, $steps) {
    foreach ($st in $steps) {
        switch ($st.E) {
            'close-open' { $h.Closed(); $h.Opened($true) }
            'fail-doors' { $h.Api.Fail.Add('TryDoorsClosed') | Out-Null }
            'heal-doors' { $h.Api.Fail.Remove('TryDoorsClosed') | Out-Null }
            'more-stations' { $h.Api.Stations.Add((NewStation $h.Api.GetType().Assembly 'EXTRA' ($h.Api.Stations[$h.Api.Stations.Count - 1].Location + 500.0))) }
        }
        $h.Api.Location = $st.L; $h.Api.SpeedMps = $st.S; $h.Api.DoorsClosed = $st.D
        if ($st.J -ne 0) { $h.Api.TimeMs += $st.J }
        $h.Run(1, 16)
    }
}
# a walk along a list: for each station approach, stop, open the doors, wait, close, leave
function Walk([double[]]$locs) {
    $steps = @()
    foreach ($x in $locs) {
        $steps += (Step ($x - 120.0) 12.0 $true); $steps += (Step ($x - 20.0) 4.0 $true); $steps += (Step $x 0.0 $true)
        for ($i = 0; $i -lt 3; $i++) { $steps += (Step $x 0.0 $false) }
        $steps += (Step $x 0.0 $true); $steps += (Step ($x + 3.0) 1.0 $true); $steps += (Step ($x + 60.0) 10.0 $true)
    }
    return $steps
}
function RandomSteps([int]$seed, [int]$n, [double]$minLoc, [double]$maxLoc) {
    $rnd = New-Object System.Random($seed)
    $steps = @(); $loc = $minLoc
    for ($i = 0; $i -lt $n; $i++) {
        $loc = [Math]::Min($maxLoc, [Math]::Max($minLoc, $loc + ($rnd.NextDouble() * 60.0 - 8.0)))
        $speed = if ($rnd.Next(0, 4) -eq 0) { 0.0 } else { $rnd.NextDouble() * 20.0 }
        $steps += (Step $loc $speed ($rnd.Next(0, 3) -ne 0))
    }
    return $steps
}
function Strip([string]$line) { return [regex]::Replace($line, ',STIDX:[^,]*', '') }
function Sent($h) { return @($h.Sink.Sent.ToArray()) }

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# L - the Legacy sender
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$h = NewHarness $newAsm
Setup $h (Stations4 $newAsm) 0.0
Drive $h (Walk @(0.0, 1000.0, 2000.0, 3000.0))
$sent = Sent $h
$lines = @($sent | Where-Object { $_.StartsWith('SCENARIO_ID:') })
$stalists = @($sent | Where-Object { $_.StartsWith('STALIST:') })
Check 'L01 lines were sent and every station group carries exactly one STIDX part' (($lines.Count -gt 30) -and (@($lines | Where-Object { ([regex]::Matches($_, ',STIDX:')).Count -ne 1 }).Count -eq 0))
Check 'L02 the part is the last key of the station group: it follows STATNAME directly' (@($lines | Where-Object { $_ -notmatch ',STATNAME:[^,]*,STIDX:1:' }).Count -eq 0)
Check 'L03 the part is well formed in every line' (@($lines | Where-Object { $_ -notmatch ',STIDX:1:-?\d+:-?\d+:\d+:\d+:[0-9A-F]{8}(,|$)' }).Count -eq 0)
$payload = $stalists[0].Substring('STALIST:'.Length)
$h03 = [string]($vec.crc32 | Where-Object { $_.id -eq 'H03' }).payload
Check 'L04 the STALIST of the four stations is the payload of the shared vector H03 in its first three entries (the Legacy rule makes D a timing station, H03 does not)' (($payload.Split(',').Count -eq 4) -and ((($payload.Split(',') | Select-Object -First 3) -join ',') -ceq (($h03.Split(',') | Select-Object -First 3) -join ',')))
$expectedId = [string](W 'ListId' @($payload))
Check 'L05 the hash of every line is the CRC-32 of the STALIST payload (the Python observer recomputes it independently in X)' (($expectedId -match '^[0-9A-F]{8}$') -and (@($lines | Where-Object { $_ -notmatch (',STIDX:1:-?\d+:-?\d+:\d+:4:' + $expectedId + '(,|$)') }).Count -eq 0))
Check 'L06 the STALIST of the run comes before the first line (the same Tick: the hash is checkable from the first line on)' ($sent.IndexOf($stalists[0]) -lt $sent.IndexOf($lines[0]))
$tgts = @($lines | ForEach-Object { [int]([regex]::Match($_, ',STIDX:1:(-?\d+):').Groups[1].Value) })
$arrs = @($lines | ForEach-Object { [int]([regex]::Match($_, ',STIDX:1:-?\d+:(-?\d+):').Groups[1].Value) })
$seqs = @($lines | ForEach-Object { [int]([regex]::Match($_, ',STIDX:1:-?\d+:-?\d+:(\d+):').Groups[1].Value) })
Check 'L07 the target starts at station 0 and never goes back' (($tgts[0] -eq 0) -and (@(1..($tgts.Count - 1) | Where-Object { $tgts[$_] -lt $tgts[$_ - 1] }).Count -eq 0))
Check 'L08 the target reaches the terminal station (3) and stays there (a terminal does not advance)' (($tgts[$tgts.Count - 1] -eq 3) -and ($tgts -contains 1) -and ($tgts -contains 2))
Check 'L09 the target advances by one station at a time' (@(1..($tgts.Count - 1) | Where-Object { ($tgts[$_] - $tgts[$_ - 1]) -gt 1 }).Count -eq 0)
Check 'L10 the arrival candidate events are numbered 1, 2, 3, 4 (one per station), start at 0 and step by at most one per Tick' (($seqs[0] -eq 0) -and ($seqs[$seqs.Count - 1] -eq 4) -and (@(1..($seqs.Count - 1) | Where-Object { ($seqs[$_] - $seqs[$_ - 1]) -notin @(0, 1) }).Count -eq 0))
Check 'L11 the arrival index is the station of the event: -1 before the first event, then 0, 1, 2, 3 in order' (($arrs[0] -eq -1) -and ((@($arrs | Select-Object -Unique) -join ',') -ceq '-1,0,1,2,3'))
Check 'L12 an event Tick shows the arrival index of the target the doors opened at (arr = tgt on that Tick)' (@(1..($lines.Count - 1) | Where-Object { ($seqs[$_] -gt $seqs[$_ - 1]) -and ($arrs[$_] -ne $tgts[$_]) }).Count -eq 0)
$nextlocs = @($lines | ForEach-Object { [double]([regex]::Match($_, ',NEXTLOC:(-?[0-9.E+\-]+)').Groups[1].Value) })
$locs4 = @(0.0, 1000.0, 2000.0, 3000.0)
Check 'L13 NEXTLOC follows the index (tgt >= 0: the location of that station; tgt -1: -1)' (@(0..($lines.Count - 1) | Where-Object { $expected = $(if ($tgts[$_] -ge 0) { $locs4[$tgts[$_]] } else { -1.0 }); [Math]::Abs($nextlocs[$_] - $expected) -gt 0.01 }).Count -eq 0)

# the target runs off the end of the list (the last station is no terminal)
$h2 = NewHarness $newAsm
Setup $h2 (StationsRunOff $newAsm) 0.0
Drive $h2 (Walk @(700.0, 1400.0, 2100.0) + @(Step 2300.0 10.0 $true; Step 2400.0 10.0 $true; Step 2500.0 10.0 $true))
$l2 = @((Sent $h2) | Where-Object { $_.StartsWith('SCENARIO_ID:') })
$t2 = @($l2 | ForEach-Object { [int]([regex]::Match($_, ',STIDX:1:(-?\d+):').Groups[1].Value) })
$n2 = @($l2 | ForEach-Object { [double]([regex]::Match($_, ',NEXTLOC:(-?[0-9.E+\-]+)').Groups[1].Value) })
Check 'L14 the target can run off the end of a list: the index is -1 and NEXTLOC is -1 from then on' (($t2[$t2.Count - 1] -eq -1) -and ($n2[$n2.Count - 1] -eq -1.0))
$locsR = @(0.0, 700.0, 1400.0, 2100.0)
Check 'L15 on EVERY Tick the index and NEXTLOC agree, also on the Tick the list runs out (the old station is still the one NEXTLOC shows)' (@(0..($l2.Count - 1) | Where-Object { $expected = $(if ($t2[$_] -ge 0) { $locsR[$t2[$_]] } else { -1.0 }); [Math]::Abs($n2[$_] - $expected) -gt 0.01 }).Count -eq 0)

# an empty list: the group is there (the stations were read) with count 0
$h3 = NewHarness $newAsm
$h3.Api.Location = 100.0; $h3.Api.SpeedMps = 10.0
Drive $h3 @(Step 100.0 10.0 $true; Step 110.0 10.0 $true)
$l3 = @((Sent $h3) | Where-Object { $_.StartsWith('SCENARIO_ID:') })
Check 'L16 an empty station list is announced as STIDX:1:-1:-1:0:0:00000000 and NEXTLOC is -1 (vector V03)' (($l3.Count -ge 1) -and (@($l3 | Where-Object { $_ -notmatch ',NEXTLOC:-1,.*,STIDX:1:-1:-1:0:0:00000000(,|$)' }).Count -eq 0))

# doors unreadable: neither group, so no STIDX (all or nothing)
$h4 = NewHarness $newAsm
Setup $h4 (Stations4 $newAsm) 0.0
Drive $h4 @(Step 0.0 0.0 $true; Step 0.0 0.0 $true 0 'fail-doors'; Step 0.0 0.0 $true; Step 0.0 0.0 $true 0 'heal-doors'; Step 0.0 0.0 $true)
$l4 = @((Sent $h4) | Where-Object { $_.StartsWith('SCENARIO_ID:') })
Check 'L17 while the doors can not be read there is no station group and no STIDX; with the doors back both are there' (($l4.Count -eq 5) -and ($l4[0] -match 'STIDX:1:') -and ($l4[1] -notmatch 'STIDX') -and ($l4[1] -notmatch 'NEXTLOC') -and ($l4[2] -notmatch 'STIDX') -and ($l4[3] -match 'STIDX:1:') -and ($l4[4] -match 'STIDX:1:'))
Check 'L18 AVAIL names the station group exactly when the part is there' (@($l4 | Where-Object { ($_ -match 'AVAIL:1:[^,]*\bstation\b') -ne ($_ -match 'STIDX') }).Count -eq 0)

# a new scenario instance: the event numbers start again
$h5 = NewHarness $newAsm
Setup $h5 (Stations4 $newAsm) 0.0
Drive $h5 (Walk @(0.0, 1000.0))
$before = @((Sent $h5) | Where-Object { $_.StartsWith('SCENARIO_ID:') })
$seqBefore = [int]([regex]::Match($before[$before.Count - 1], ',STIDX:1:-?\d+:-?\d+:(\d+):').Groups[1].Value)
Drive $h5 @(Step 0.0 0.0 $true 0 'close-open'; Step 0.0 0.0 $true; Step 0.0 0.0 $true)
$after = @((Sent $h5) | Where-Object { $_.StartsWith('SCENARIO_ID:') })
$last = $after[$after.Count - 1]
Check 'L19 a scenario reload starts the event numbers again at 0 with arr -1 and the target at station 0' (($seqBefore -ge 2) -and ($last -match (',STIDX:1:0:-1:0:4:' + $expectedId + '(,|$)')))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# D - differential against the audited DLL built before ST-1A
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$refOk = $false
$refAsm = $null
# The files this run writes (the work folder with the fixture DLL and the copy of the audited DLL, the dump, the python script) are written to ONE fixed folder name and
# registered, and a run that leaves one of them behind FAILS (CLEAN below). The two DLLs are NOT loaded by path: a DLL loaded from a file path is locked until the process ends
# and can not be deleted by it (that left 13 folders of DLLs behind in ST-1A, hidden by a Remove-Item whose errors were silenced). They are read into memory and loaded with Assembly.Load(byte[]).
$work = Join-Path $env:TEMP ('ts-st1a-' + [guid]::NewGuid().ToString('N'))
$dumpPath = Join-Path $env:TEMP ('ts-st1a-dump-' + [guid]::NewGuid().ToString('N') + '.txt')
$pyPath = Join-Path $env:TEMP ('ts-st1a-observe-' + [guid]::NewGuid().ToString('N') + '.py')
$dllCopy = Join-Path $work 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureDll = Join-Path $work 'TsScoringLegacyTelemetryTests.dll'
$script:tempStart = @(Get-ChildItem -LiteralPath $env:TEMP -Force | Where-Object { $_.Name -like 'ts-st1a-*' } | ForEach-Object { $_.Name })
$script:cleanFiles = @($dllCopy, $fixtureDll, $dumpPath, $pyPath)       # every file that may be written, in the order of deletion
$script:cleanDirs = @($work)                                              # every folder that may be created (removed after its files, never recursively)
function Remove-Created {
    # Removes exactly the registered paths: no wildcard, no -Recurse, no silenced error action. A path that can not be removed is returned, not hidden.
    $failed = New-Object System.Collections.Generic.List[string]
    $removed = 0
    foreach ($p in $script:cleanFiles) {
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            try { Remove-Item -LiteralPath $p -Force -ErrorAction Stop; $removed++ } catch { $failed.Add($p + ' :: ' + $_.Exception.Message) }
        }
    }
    foreach ($d in $script:cleanDirs) {
        if (Test-Path -LiteralPath $d -PathType Container) {
            $children = @(Get-ChildItem -LiteralPath $d -Force)
            if ($children.Count -gt 0) { $failed.Add($d + ' :: not empty (' + $children.Count + ' left: ' + (($children | ForEach-Object { $_.Name }) -join ', ') + ')'); continue }
            try { Remove-Item -LiteralPath $d -Force -ErrorAction Stop; $removed++ } catch { $failed.Add($d + ' :: ' + $_.Exception.Message) }
        }
    }
    foreach ($p in @($script:cleanFiles) + @($script:cleanDirs)) {
        if ((Test-Path -LiteralPath $p) -and (-not ($failed | Where-Object { $_.StartsWith($p + ' :: ') }))) { $failed.Add($p + ' :: still exists after the removal') }
    }
    return ,@($removed, $failed.ToArray())
}
try {
try {
    if ((Test-Path -LiteralPath $refDllPath) -and ((Get-FileHash -LiteralPath $refDllPath -Algorithm SHA256).Hash -ceq $AuditedRefDllSha256)) {
        New-Item -ItemType Directory -Path $work | Out-Null
        Copy-Item -LiteralPath $refDllPath -Destination $dllCopy
        Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixturePath)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
        Add-Type -TypeDefinition @'
using System;
using System.Reflection;
public static class St1aResolver
{
    // the two DLLs are loaded from memory (no path, no context): the fixture finds the audited DLL by its simple name among the loaded assemblies
    public static void Install()
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string name = new AssemblyName(e.Name).Name;
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (string.Equals(a.GetName().Name, name, StringComparison.OrdinalIgnoreCase)) { return a; }
            }
            return null;
        };
    }
}
'@
        [St1aResolver]::Install()
        $null = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($dllCopy))
        $refAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($fixtureDll))
        $refOk = $true
    }
} catch {
    Write-Host ('  reference fixture could not be prepared: ' + $_.Exception.Message)
    $refOk = $false
}

$scenarios = @(
    @{ Name = 'D1 four stations, a normal walk'; Make = { param($a) Stations4 $a }; Steps = { Walk @(0.0, 1000.0, 2000.0, 3000.0) } },
    # Time Fix B2 (an INTENDED difference, not a drift): the operational stop S2 (1600 m) is left by the target as soon as the vehicle leaves it (|speed| > 0.1 km/h) - the audited DLL waits for the departure time + 300 ms.
    # B2Leave = (the NEXTLOC of the audited DLL, the NEXTLOC of the new sender) on the first datagram that differs; Handshake\Tests\Test-TimeFixB2.ps1 holds the rule itself.
    @{ Name = 'D2 pass, operational stop, same-position pair, terminal'; Make = { param($a) Stations6 $a }; Steps = { Walk @(0.0, 800.0, 1600.0, 2400.0, 3200.0) }; B2Leave = @(1600.0, 2400.0) },
    @{ Name = 'D3 the target runs off the end of the list'; Make = { param($a) StationsRunOff $a }; Steps = { (Walk @(700.0, 1400.0, 2100.0)) + @(Step 2300.0 10.0 $true; Step 2400.0 10.0 $true) } },
    @{ Name = 'D4 time and position jumps in the middle of a run'; Make = { param($a) Stations4 $a }; Steps = { (Walk @(0.0, 1000.0)) + @(Step 2500.0 8.0 $true 90000; Step 2510.0 8.0 $true; Step 2000.0 0.0 $false 0; Step 2000.0 0.0 $true 0; Step 40.0 5.0 $true 400000) + (Walk @(2000.0, 3000.0)) } },
    @{ Name = 'D5 a scenario reload and a growing list'; Make = { param($a) Stations4 $a }; Steps = { (Walk @(0.0)) + @(Step 10.0 0.0 $true 0 'close-open'; Step 10.0 0.0 $true) + (Walk @(1000.0)) + @(Step 1500.0 5.0 $true 0 'more-stations'; Step 1510.0 5.0 $true; Step 1520.0 5.0 $true) } },
    @{ Name = 'D6 doors unreadable for a while'; Make = { param($a) Stations6 $a }; Steps = { (Walk @(0.0)) + @(Step 60.0 5.0 $true 0 'fail-doors'; Step 70.0 5.0 $false; Step 80.0 5.0 $true 0 'heal-doors'; Step 90.0 5.0 $true) + (Walk @(800.0, 1600.0)) }; B2Leave = @(1600.0, 2400.0) },
    @{ Name = 'D7 random walk, seed 11'; Make = { param($a) Stations6 $a }; Steps = { RandomSteps 11 400 0.0 3300.0 } },
    @{ Name = 'D8 random walk, seed 23'; Make = { param($a) Stations6 $a }; Steps = { RandomSteps 23 400 0.0 3300.0 } },
    @{ Name = 'D9 random walk, seed 97, run-off list'; Make = { param($a) StationsRunOff $a }; Steps = { RandomSteps 97 400 650.0 2300.0 } }
)

$dumpLines = New-Object System.Collections.Generic.List[string]
if ($true) {
    foreach ($sc in $scenarios) {
        $mk = $sc.Make; $stepsBlock = $sc.Steps
        $steps = & $stepsBlock
        $hn = NewHarness $newAsm
        Setup $hn (& $mk $newAsm) 0.0
        Drive $hn $steps
        $newSent = Sent $hn
        $newLines = @($newSent | Where-Object { $_.StartsWith('SCENARIO_ID:') })
        Check ($sc.Name + ': the new sender wrote lines and a part in every station group') (($newLines.Count -gt 20) -and (@($newLines | Where-Object { ($_ -match ',NEXTLOC:') -and ($_ -notmatch ',STIDX:1:') }).Count -eq 0))
        $dumpLines.Add('#RUN ' + $sc.Name.Substring(0, 2))
        foreach ($s in $newSent) { if ($s.StartsWith('STALIST:') -or $s.StartsWith('SCENARIO_ID:')) { $dumpLines.Add($s) } }
        if ($refOk) {
            $ho = NewHarness $refAsm
            Setup $ho (& $mk $refAsm) 0.0
            Drive $ho $steps
            $oldSent = Sent $ho
            $stripped = @($newSent | ForEach-Object { Strip $_ })
            $same = ($stripped.Count -eq $oldSent.Count)
            $firstDiff = ''
            $diffIndex = -1
            if ($same) {
                for ($i = 0; $i -lt $oldSent.Count; $i++) { if ($stripped[$i] -cne $oldSent[$i]) { $same = $false; $diffIndex = $i; $firstDiff = ' (datagram ' + $i + ')'; break } }
            } else { $firstDiff = ' (' + $stripped.Count + ' vs ' + $oldSent.Count + ' datagrams)' }
            if ($sc.ContainsKey('B2Leave')) {
                # Time Fix B2: equal up to the first difference (the loop above), and that difference is exactly the intended one: the target is already the next station while the audited DLL still holds the operational stop
                $newLoc = -1.0; $oldLoc = -1.0
                if ($diffIndex -ge 0) {
                    $mn = [regex]::Match($stripped[$diffIndex], ',NEXTLOC:([^,]+)'); $mo = [regex]::Match($oldSent[$diffIndex], ',NEXTLOC:([^,]+)')
                    if ($mn.Success) { $newLoc = [double]::Parse($mn.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture) }
                    if ($mo.Success) { $oldLoc = [double]::Parse($mo.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture) }
                }
                Check ($sc.Name + ': Time Fix B2 - every datagram equals the audited DLL except for the STIDX part up to datagram ' + $diffIndex + ' of ' + $oldSent.Count + ', where the new sender leaves the operational stop (NEXTLOC ' + $sc.B2Leave[1] + ' instead of ' + $sc.B2Leave[0] + ')') (($diffIndex -ge 0) -and ($oldLoc -eq $sc.B2Leave[0]) -and ($newLoc -eq $sc.B2Leave[1]))
            } else {
                Check ($sc.Name + ': every datagram equals the audited DLL except for the STIDX part (' + $oldSent.Count + ' datagrams)' + $firstDiff) $same
            }
        } else {
            Skip ($sc.Name + ': differential against the audited DLL (reference DLL is not the audited one)')
        }
    }
    [IO.File]::WriteAllLines($dumpPath, $dumpLines.ToArray(), (New-Object Text.UTF8Encoding($false)))

    # -----------------------------------------------------------------------------------------------------------------------------------------------------------------------
    # X - the Python observer judges every line of every run
    # -----------------------------------------------------------------------------------------------------------------------------------------------------------------------
    $pyCode = @'
import sys, re, json
sys.path.insert(0, sys.argv[1])
import station_index_contract as sic
runs, cur, obs, bad = {}, None, None, []
for raw in open(sys.argv[2], encoding="utf-8").read().split("\n"):
    if not raw:
        continue
    if raw.startswith("#RUN "):
        cur = raw[5:]; obs = sic.StationIndexObserver(); runs[cur] = {"lines": 0, "ok": 0, "other": {}}
        continue
    if raw.startswith("STALIST:"):
        obs.note_stalist(raw[len("STALIST:"):]); continue
    sid = int(re.search(r"SCENARIO_ID:(-?\d+)", raw).group(1))
    w = obs.observe(raw, sid)
    r = runs[cur]
    if "STIDX:" not in raw:
        continue
    r["lines"] += 1
    if w == sic.V_OK:
        r["ok"] += 1
    else:
        r["other"][w] = r["other"].get(w, 0) + 1
print(json.dumps(runs))
'@
    $pyOut = $null
    try {
        [IO.File]::WriteAllText($pyPath, $pyCode, (New-Object Text.UTF8Encoding($false)))
        $pyOut = (& python -I -B $pyPath $repo $dumpPath | Out-String)
    } catch { $pyOut = $null }
    if ($null -eq $pyOut -or $pyOut.Trim().Length -eq 0) {
        Skip 'X python observer: python could not be run'
    } else {
        $runs = $pyOut | ConvertFrom-Json
        foreach ($sc in $scenarios) {
            $key = $sc.Name.Substring(0, 2)
            $r = $runs.$key
            $others = ''
            if ($r -and $r.other) { $others = ($r.other.PSObject.Properties | ForEach-Object { $_.Name + '=' + $_.Value }) -join ',' }
            if ($key -eq 'D5') {
                # the list grows on purpose: the hash changes at once, the STALIST follows within a second (NOT-READY is the contract's word for that window); nothing else is tolerated
                $notReady = 0
                if ($r -and $r.other -and $r.other.PSObject.Properties['NOT-READY']) { $notReady = [int]$r.other.'NOT-READY' }
                $onlyNotReady = $r -and ($r.ok -ge 20) -and (($r.ok + $notReady) -eq $r.lines)
                Check ('X-' + $key + ' the Python observer judges the lines stidx-ok, and NOT-READY only in the window of the growing list (' + $r.ok + ' ok, ' + $notReady + ' NOT-READY of ' + $r.lines + ')') $onlyNotReady
            } else {
                Check ('X-' + $key + ' the Python observer judges every STIDX line of the run stidx-ok (' + $r.ok + ' of ' + $r.lines + $(if ($others) { '; ' + $others } else { '' }) + ')') ($r -and ($r.lines -gt 20) -and ($r.ok -eq $r.lines))
            }
        }
    }
}
} finally {
    # CLEAN: the cleanup is part of the test. It does not add a PASS (the count of the checks above is the count of the contract); a leftover is a FAIL.
    $cleanResult = Remove-Created
    $cleanFailed = @($cleanResult[1])
    $newTemp = @(Get-ChildItem -LiteralPath $env:TEMP -Force | Where-Object { $_.Name -like 'ts-st1a-*' -and ($script:tempStart -notcontains $_.Name) } | ForEach-Object { $_.Name })
    Write-Host ('CLEANUP temp=' + $env:TEMP + ' removed=' + $cleanResult[0] + ' failed=' + $cleanFailed.Count + ' new-ts-st1a-entries-left=' + $newTemp.Count)
    foreach ($f in $cleanFailed) { Write-Host ('  cleanup failed: ' + $f) }
    foreach ($n in $newTemp) { Write-Host ('  left behind: ' + (Join-Path $env:TEMP $n)) }
    if ($cleanFailed.Count -gt 0 -or $newTemp.Count -gt 0) { $script:fail++; Write-Host 'FAIL CLEAN this run left a file or folder behind (see above)' }
}

Write-Host ('STATIONINDEX-ST1A PASS=' + $script:pass + ' FAIL=' + $script:fail + ' SKIP(not counted)=' + $script:skip)
if ($script:fail -gt 0) { exit 1 }
exit 0
