param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# TIME FIX A (remaining time "--:--" at a terminal station) - offline BEHAVIOUR test of the arrival fill-in of the station list, Current AND Legacy.
#
# The rule under test: a station whose arrival time is undefined (-1) gets arrival = departure - effective stopping time WHEN the departure time is a usable normal time.
# Whether the station is the terminal is a ROLE and does not decide that; a departure time that is undefined (-1) or the terminal sentinel (BVE6 = Int32.MaxValue ms,
# BVE5 = Int32.MaxValue + 1 ms, carried as a wrapped or saturated Int32 by the Legacy API) is NOT a usable time and never produces an arrival.
#
# HOW: Class1.cs can not run offline (it needs the BveEX host), so the two statement spans that decide the times are cut out of the SOURCE of Class1.cs (the text itself, not a copy):
#   S1 = the per-station reader of the departure time / default time / stopping time (it also decides the terminal sentinel), S2 = the terminal selection, the arrival / departure fill-in and the
#   default time anchors. They are compiled in memory (CodeDom, C# 5) next to fake host stations. The Legacy side compiles the REAL sources of LegacyStationTimeline.cs and its shared files with
#   a small fixture in the same assembly. No BVE, no BveEx, no AtsEX, no port, no product build, nothing is written to the repository (the fixture lives in a unique TEMP folder that is removed).
# Cases tagged [RED-A] fail on the code before Time Fix A and pass after it; every other case is a guard that passes before and after.
# ASCII only, Windows PowerShell 5.1.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$class1 = Join-Path $RepositoryRoot 'TsScoringPlugin\TsScoringPlugin\Class1.cs'
$tele = Join-Path $RepositoryRoot 'TsScoringPlugin\Handshake\Telemetry'
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}

function Get-BlockText([string]$text, [string]$signature) {
    $start = $text.IndexOf($signature, [StringComparison]::Ordinal)
    if ($start -lt 0) { return $null }
    $open = $text.IndexOf('{', $start)
    if ($open -lt 0) { return $null }
    $depth = 0
    for ($p = $open; $p -lt $text.Length; $p++) {
        $c = $text[$p]
        if ($c -eq '{') { $depth++ }
        elseif ($c -eq '}') {
            $depth--
            if ($depth -eq 0) { return $text.Substring($start, $p - $start + 1) }
        }
    }
    return $null
}

function Get-Span([string]$text, [string]$startMarker, [string]$endMarker, [bool]$includeEnd) {
    $s = $text.IndexOf($startMarker, [StringComparison]::Ordinal)
    if ($s -lt 0) { return $null }
    if ($text.IndexOf($startMarker, $s + 1, [StringComparison]::Ordinal) -ge 0) { return $null }
    $e = $text.IndexOf($endMarker, $s, [StringComparison]::Ordinal)
    if ($e -lt 0) { return $null }
    if ($includeEnd) { $e = $e + $endMarker.Length }
    return $text.Substring($s, $e - $s)
}

# the times of the cases (ms of the day)
$T0 = 28800000        # 08:00:00
$DEP_A = 28830000     # 08:00:30  departure of the first station
$ARR_T03 = 29045000   # 08:04:05  = departure - 30 s
$DEP_T03 = 29075000   # 08:04:35
$ARR_DEF = 29000000   # 08:03:20
$STOP30 = 30000
$BVE6 = 2147483647    # Int32.MaxValue
$BVE5 = 2147483648    # Int32.MaxValue + 1 (does not fit an Int32)

Write-Host '--- A: the spans are cut out of Class1.cs'
$source = [IO.File]::ReadAllText($class1, [Text.Encoding]::UTF8)
$s1 = Get-Span $source 'sd.IsTerminal = false;' 'sd.IsScoring = sd.HasTimeDef;' $true
$s2 = Get-Span $source 'bool explicitTerminalFound = false;' 'int lastTimingIdx = -1;' $false
$stationDataClass = Get-BlockText $source 'public class StationData'
$constMatches = [regex]::Matches($source, 'private const long TerminalDepartureTimeBve[56]Ms\s*=\s*[^;]+;')
Check 'A01 S1 (the per-station time reader) is found exactly once' ($null -ne $s1)
Check 'A02 S2 (terminal selection, arrival / departure fill-in, default time anchors) is found exactly once' ($null -ne $s2)
Check 'A03 the StationData class is found' ($null -ne $stationDataClass)
Check 'A04 both terminal sentinel constants (BVE5 / BVE6) are found' ($constMatches.Count -eq 2)
if (($null -eq $s1) -or ($null -eq $s2) -or ($null -eq $stationDataClass) -or ($constMatches.Count -ne 2)) {
    Write-Host ''
    Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}
$consts = (($constMatches | ForEach-Object { $_.Value }) -join [Environment]::NewLine)

$currentFixture = @'
using System;
using System.Collections.Generic;

namespace TimeFixCurrent
{
//STATIONDATA//

    public class FakeHostStation
    {
        public TimeSpan DepartureTime;
        public TimeSpan DefaultTime;
        public int StoppageTimeMilliseconds;
    }

    public class FakeHostStationDouble
    {
        public double DepartureTime;
        public double DefaultTime;
        public int StoppageTimeMilliseconds;
    }

    public static class CurrentUnderTest
    {
//CONSTS//

        public static StationData[] Run(long[] arrMs, long[] depHostMs, long[] defMs, int[] stopMs, bool[] hostIsDouble)
        {
            List<StationData> stationList = new List<StationData>();
            for (int i = 0; i < arrMs.Length; i++)
            {
                object host;
                if (hostIsDouble[i])
                {
                    FakeHostStationDouble d = new FakeHostStationDouble();
                    d.DepartureTime = depHostMs[i] / 1000.0;
                    d.DefaultTime = defMs[i] / 1000.0;
                    d.StoppageTimeMilliseconds = stopMs[i];
                    host = d;
                }
                else
                {
                    FakeHostStation h = new FakeHostStation();
                    h.DepartureTime = TimeSpan.FromMilliseconds(depHostMs[i]);
                    h.DefaultTime = TimeSpan.FromMilliseconds(defMs[i]);
                    h.StoppageTimeMilliseconds = stopMs[i];
                    host = h;
                }

                dynamic st = host;
                StationData sd = new StationData();
                sd.RawArrTime = (int)arrMs[i];
                sd.RawDepTime = -1;
                sd.DefaultTime = -1;
//S1//
                stationList.Add(sd);
            }

//S2//
            return stationList.ToArray();
        }
    }
}
'@
$currentFixture = $currentFixture.Replace('//STATIONDATA//', $stationDataClass).Replace('//CONSTS//', $consts).Replace('//S1//', $s1).Replace('//S2//', $s2)

$compileError = $null
try {
    Add-Type -TypeDefinition $currentFixture -ReferencedAssemblies @('System.dll', 'System.Core.dll', 'Microsoft.CSharp.dll')
} catch {
    $compileError = $_.Exception.Message
}
Check 'A05 the cut-out Current spans compile in memory (C# 5)' ($null -eq $compileError)
if ($null -ne $compileError) {
    Write-Host ('  compile error: ' + $compileError)
    Write-Host ''
    Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

# one station of a Current case: arrival ms (-1 = undefined), host departure ms (-1 = undefined, sentinel values as they are), default ms (-1), stopping time ms, double host?
function St([long]$arr, [long]$dep, [long]$stop, [long]$def = -1, [bool]$dbl = $false) { return @{ arr = $arr; dep = $dep; def = $def; stop = [int]$stop; dbl = $dbl } }
function RunCurrent($stations) {
    $n = @($stations).Count
    $arr = New-Object 'long[]' $n; $dep = New-Object 'long[]' $n; $def = New-Object 'long[]' $n; $stop = New-Object 'int[]' $n; $dbl = New-Object 'bool[]' $n
    for ($i = 0; $i -lt $n; $i++) {
        $arr[$i] = $stations[$i].arr; $dep[$i] = $stations[$i].dep; $def[$i] = $stations[$i].def; $stop[$i] = $stations[$i].stop; $dbl[$i] = $stations[$i].dbl
    }
    return ,([TimeFixCurrent.CurrentUnderTest]::Run($arr, $dep, $def, $stop, $dbl))
}

Write-Host '--- B: Current (the real spans of Class1.cs)'
$first = St $T0 $DEP_A $STOP30

# A-T3 (Test03 type): last station = terminal by the list end, arrival undefined, departure a normal time, stopping time 30 s
$r = RunCurrent @($first, (St -1 $DEP_T03 $STOP30))
Check 'B01 [RED-A] A-T3 Test03 type: the terminal gets arrival = departure - 30 s = 08:04:05' (($r[1].IsTerminal) -and ($r[1].ArrTime -eq $ARR_T03))
Check 'B02 A-T3 the terminal keeps its departure 08:04:35 and the raw values are untouched (RawArr -1, RawDep = departure)' (($r[1].DepTime -eq $DEP_T03) -and ($r[1].RawArrTime -eq -1) -and ($r[1].RawDepTime -eq $DEP_T03))
Check 'B03 A-T3 the terminal is a timing station (HasTimeDef / IsScoring) and the stopping time is the 30 s of the host' (($r[1].HasTimeDef) -and ($r[1].IsScoring) -and ($r[1].StoppageTime -eq $STOP30))
$nextTimeSource = $r[1].InterpolatedTime
if ($r[1].ArrTime -gt 0) { $nextTimeSource = $r[1].ArrTime }
Check 'B04 [RED-A] A-T3 NEXTTIME source: the value the terminal state machine reads (ArrTime > 0 ? ArrTime : InterpolatedTime) is 08:04:05, not 0' ($nextTimeSource -eq $ARR_T03)
Check 'B05 A-T3 the first station is never a timing station and keeps its times' ((-not $r[0].IsScoring) -and ($r[0].ArrTime -eq $T0) -and ($r[0].DepTime -eq $DEP_A))

# A-T1: a normal terminal: arrival a normal time, departure "t" (BVE6 and BVE5 sentinel)
foreach ($sent in @(@('BVE6', $BVE6), @('BVE5', $BVE5))) {
    $r = RunCurrent @($first, (St $ARR_DEF $sent[1] $STOP30))
    Check ('B06 A-T1 ' + $sent[0] + ' sentinel terminal with an arrival: the arrival is kept, no departure, terminal flag set') (($r[1].IsTerminal) -and ($r[1].ArrTime -eq $ARR_DEF) -and ($r[1].DepTime -eq -1) -and ($r[1].RawDepTime -eq -1))
}

# A-T2 / A-T6 / A-T7: arrival undefined and the departure is the terminal sentinel: nothing is made up
foreach ($sent in @(@('A-T6 BVE5', $BVE5), @('A-T7 BVE6', $BVE6))) {
    $r = RunCurrent @($first, (St -1 $sent[1] $STOP30))
    Check ('B07 ' + $sent[0] + ' sentinel with an undefined arrival: arrival stays -1, departure -1, no giant time, not a timing station') (($r[1].IsTerminal) -and ($r[1].ArrTime -eq -1) -and ($r[1].DepTime -eq -1) -and (-not $r[1].HasTimeDef))
    $r = RunCurrent @($first, (St -1 $sent[1] $STOP30), (St -1 -1 $STOP30))
    Check ('B08 ' + $sent[0] + ' sentinel in the MIDDLE of the list (the first "t" is the terminal): no arrival is made up for it or for the station behind it') (($r[1].IsTerminal) -and ($r[1].ArrTime -eq -1) -and ($r[1].DepTime -eq -1) -and ($r[2].ArrTime -eq -1))
}

# A-T4: an ordinary stop in the middle (not the terminal): unchanged fill-in
$r = RunCurrent @($first, (St -1 $DEP_T03 $STOP30), (St 29400000 $BVE6 $STOP30))
Check 'B09 A-T4 a middle station with an undefined arrival: arrival = departure - stop time (unchanged)' ((-not $r[1].IsTerminal) -and ($r[1].ArrTime -eq $ARR_T03) -and ($r[1].DepTime -eq $DEP_T03) -and ($r[2].IsTerminal))
# the other direction: arrival only on a middle station gives departure = arrival + stop time
$r = RunCurrent @($first, (St $ARR_DEF -1 $STOP30), (St 29400000 $BVE6 $STOP30))
Check 'B10 a middle station with an arrival only: departure = arrival + stop time (unchanged)' (($r[1].ArrTime -eq $ARR_DEF) -and ($r[1].DepTime -eq ($ARR_DEF + $STOP30)))
# the terminal never gets a departure made up from an arrival
$r = RunCurrent @($first, (St $ARR_DEF -1 $STOP30))
Check 'B11 a terminal (list end) with an arrival only: no departure is made up (unchanged)' (($r[1].IsTerminal) -and ($r[1].ArrTime -eq $ARR_DEF) -and ($r[1].DepTime -eq -1))

# A-T5: nothing defined at all
$r = RunCurrent @($first, (St -1 -1 $STOP30), (St -1 -1 $STOP30))
Check 'B12 A-T5 arrival -1 and departure -1: nothing is made up, no exception, not a timing station' (($r[1].ArrTime -eq -1) -and ($r[1].DepTime -eq -1) -and (-not $r[1].HasTimeDef) -and ($r[2].ArrTime -eq -1) -and ($r[2].IsTerminal))
# departure 0 is not a usable time
$r = RunCurrent @($first, (St -1 0 $STOP30))
Check 'B13 a departure of 0 ms is not a usable time: no arrival is made up' (($r[1].ArrTime -eq -1) -and (-not $r[1].HasTimeDef))

# A-T8: a defined arrival is never overwritten from the departure
$r = RunCurrent @($first, (St $ARR_DEF $DEP_T03 $STOP30))
Check 'B14 A-T8 terminal with a defined arrival AND a normal departure: the arrival stays 08:03:20 (not 08:04:05)' (($r[1].IsTerminal) -and ($r[1].ArrTime -eq $ARR_DEF) -and ($r[1].DepTime -eq $DEP_T03))
$r = RunCurrent @($first, (St $ARR_DEF $DEP_T03 $STOP30), (St 29400000 $BVE6 $STOP30))
Check 'B15 A-T8 middle station with both times defined: nothing is changed' (($r[1].ArrTime -eq $ARR_DEF) -and ($r[1].DepTime -eq $DEP_T03))

# A-T9: departure - stop time below zero: the existing clamp to 0, no made-up time
$r = RunCurrent @($first, (St -1 10000 $STOP30))
Check 'B16 [RED-A] A-T9 terminal, departure 10 s and stop time 30 s: the arrival is clamped to 0 by the existing range rule (not negative, not made up)' (($r[1].ArrTime -eq 0) -and ($r[1].DepTime -eq 10000))
$r = RunCurrent @($first, (St -1 10000 $STOP30), (St 29400000 $BVE6 $STOP30))
Check 'B17 A-T9 middle station, same input: the same clamp (unchanged)' (($r[1].ArrTime -eq 0) -and ($r[1].DepTime -eq 10000))

# stop time contract: the fill-in uses the stop time the host gives (30 s here, 15 s default of the reader is only a fallback)
$r = RunCurrent @($first, (St -1 $DEP_T03 15000))
Check 'B18 [RED-A] the arrival of a terminal is departure minus the stop time of the host, whatever it is (15 s -> 08:04:20)' ($r[1].ArrTime -eq ($DEP_T03 - 15000))

# default time anchors are unchanged
$r = RunCurrent @($first, (St -1 -1 $STOP30 29100000))
Check 'B19 default time anchor on a terminal without any time: arrival = default time, no departure (unchanged)' (($r[1].IsTerminal) -and ($r[1].ArrTime -eq 29100000) -and ($r[1].DepTime -eq -1) -and ($r[1].HasTimeDef))
$r = RunCurrent @($first, (St -1 -1 $STOP30 29100000), (St 29400000 $BVE6 $STOP30))
Check 'B20 default time anchor on a middle station between two anchors: not applied by this step (interpolation is a later step)' (($r[1].ArrTime -eq -1) -and (-not $r[1].HasTimeDef))

# the double route of the reader (a host that gives seconds as double)
$r = RunCurrent @($first, (St -1 $DEP_T03 $STOP30 -1 $true))
Check 'B21 [RED-A] Test03 type through the double reader: the terminal gets arrival 08:04:05' (($r[1].IsTerminal) -and ($r[1].ArrTime -eq $ARR_T03) -and ($r[1].DepTime -eq $DEP_T03))
foreach ($sent in @(@('BVE6', $BVE6), @('BVE5', $BVE5))) {
    $r = RunCurrent @($first, (St -1 $sent[1] $STOP30 -1 $true))
    Check ('B22 ' + $sent[0] + ' sentinel through the double reader with an undefined arrival: no arrival, no departure') (($r[1].ArrTime -eq -1) -and ($r[1].DepTime -eq -1) -and ($r[1].RawDepTime -eq -1))
}

Write-Host '--- C: Legacy (the real sources of LegacyStationTimeline.cs)'
$work = Join-Path $env:TEMP ('ts-timefix-a-' + [guid]::NewGuid().ToString('N'))
$legacyFixture = @'
using System;
using System.Collections.Generic;
using TSScoringPlugin.Telemetry;

public sealed class TimeFixLegacyProbe
{
    private LegacyStationTimeline t = new LegacyStationTimeline();
    private List<LegacyStationRaw> raw = new List<LegacyStationRaw>();
    private StationValues last;

    public void Add(string name, double loc, bool terminal, int arrMs, int depMs, int stopMs, int defMs)
    {
        LegacyStationRaw r = new LegacyStationRaw();
        r.Name = name; r.Location = loc; r.Pass = false; r.IsTerminal = terminal; r.DoorSide = 1;
        r.ArrivalMs = arrMs; r.DepartureMs = depMs; r.DefaultMs = defMs; r.StoppageMs = stopMs; r.MarginMin = 5.0; r.MarginMax = 5.0;
        raw.Add(r);
    }
    // Phase SI-R2.4 C5a: the explicit seed. The target is the given index because the timeline is asked for it (RequestTarget, one shot, consumed by the first selection); nothing reads the vehicle position to choose it.
    public void Seed(int index) { t.RequestTarget(index, raw[index].Location); }
    public void Step(double location, double speedKmh, int timeMs, bool doorsClosed)
    {
        last = t.Step(raw, raw.Count, location, speedKmh, timeMs, doorsClosed);
    }
    public int Count { get { return t.Count; } }
    public int Arr(int i) { return t.Entries[i].ArrTime; }
    public int Dep(int i) { return t.Entries[i].DepTime; }
    public int RawArr(int i) { return t.Entries[i].RawArrTime; }
    public int RawDep(int i) { return t.Entries[i].RawDepTime; }
    public bool Term(int i) { return t.Entries[i].IsTerminal; }
    public bool HasTimeDef(int i) { return t.Entries[i].HasTimeDef; }
    public bool Scoring(int i) { return t.Entries[i].IsScoring; }
    public int Interpolated(int i) { return t.Entries[i].InterpolatedTime; }
    public int NextTime { get { return last.NextTime; } }
    public string StaList() { return t.ComposeStaList(); }
}
'@

# one Legacy station: name, terminal flag the API states, arrival ms, departure ms (as the Int32 the API gives), stop ms, default ms
function LSt([string]$name, [bool]$term, [int]$arr, [int]$dep, [int]$stop, [int]$def = -1) { return @{ name = $name; term = $term; arr = $arr; dep = $dep; stop = $stop; def = $def } }
$script:legacyReady = $false
function RunLegacy($stations, [double]$location = 500.0) {
    $p = New-Object TimeFixLegacyProbe
    $i = 0
    foreach ($s in $stations) {
        $p.Add($s.name, [double](1000 * $i), $s.term, $s.arr, $s.dep, $s.stop, $s.def)
        $i++
    }
    if ($i -gt 1) { $p.Seed(1) }     # the explicit seed: the target is station 1 (the stations stand every 1000 m and the vehicle is at 500 m); a list of one station has no station 1
    $p.Step($location, 0.0, $T0, $true)
    return $p
}

$legacyError = $null
try {
    New-Item -ItemType Directory -Path $work | Out-Null
    $fixturePath = Join-Path $work 'TimeFixLegacyProbe.cs'
    [IO.File]::WriteAllText($fixturePath, $legacyFixture, (New-Object Text.UTF8Encoding($false)))
    $sources = @(
        (Join-Path $tele 'Legacy\src\LegacyStationTimeline.cs'),
        (Join-Path $tele 'Legacy\src\LegacyApi.cs'),
        (Join-Path $tele 'Shared\TelemetryContract.cs'),
        (Join-Path $tele 'Shared\StationListIdentity.cs'),
        (Join-Path $tele 'Shared\JumpWire.cs'),
        $fixturePath)
    Add-Type -Path $sources -ReferencedAssemblies @('System.dll', 'System.Core.dll') -IgnoreWarnings
    $script:legacyReady = $true
} catch {
    $legacyError = $_.Exception.Message
    if ($_.Exception.PSObject.Properties['LoaderExceptions']) { $legacyError = $legacyError + ' ' + (($_.Exception.LoaderExceptions | ForEach-Object { $_.Message }) -join ' | ') }
}
Check 'C00 the real Legacy sources compile in memory with the fixture' $script:legacyReady
if (-not $script:legacyReady) {
    Write-Host ('  compile error: ' + $legacyError)
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host ''
    Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

try {
    $firstL = LSt 'Test02' $false $T0 $DEP_A $STOP30

    # A-T3 Test03 type, the API does NOT state the terminal (the list end makes it) and the API STATES it: both must read the same
    foreach ($stated in @($false, $true)) {
        $label = 'terminal stated by the API = ' + $stated
        $p = RunLegacy @($firstL, (LSt 'Test03' $stated -1 $DEP_T03 $STOP30)) 500.0
        Check ('C01 [RED-A] A-T3 Test03 type (' + $label + '): arrival = departure - 30 s = 08:04:05') (($p.Term(1)) -and ($p.Arr(1) -eq $ARR_T03) -and ($p.Dep(1) -eq $DEP_T03))
        Check ('C02 [RED-A] A-T3 Test03 type (' + $label + '): the NEXTTIME of the Tick that targets the terminal is 08:04:05, not 0') ($p.NextTime -eq $ARR_T03)
        Check ('C03 ' + $(if ($stated) { '[RED-A] ' } else { '' }) + 'A-T3 Test03 type (' + $label + '): the raw values are untouched, the terminal is a timing station, the first station is not') (($p.RawArr(1) -eq -1) -and ($p.RawDep(1) -eq $DEP_T03) -and ($p.HasTimeDef(1)) -and ($p.Scoring(1)) -and (-not $p.Scoring(0)))
    }

    # A-T1: a normal terminal with an arrival and the sentinel departure
    foreach ($sent in @(@('BVE6 Int32.MaxValue', [int]2147483647), @('BVE5 wrapped Int32.MinValue', [int]-2147483648))) {
        foreach ($stated in @($false, $true)) {
            $p = RunLegacy @($firstL, (LSt 'T' $stated $ARR_DEF $sent[1] $STOP30)) 500.0
            Check ('C04 A-T1 ' + $sent[0] + ' departure, terminal stated = ' + $stated + ': the arrival is kept, the departure is -1') (($p.Term(1)) -and ($p.Arr(1) -eq $ARR_DEF) -and ($p.Dep(1) -eq -1) -and ($p.RawDep(1) -eq -1))
            $p = RunLegacy @($firstL, (LSt 'T' $stated -1 $sent[1] $STOP30)) 500.0
            Check ('C05 A-T2/T6/T7 ' + $sent[0] + ' departure, terminal stated = ' + $stated + ', arrival undefined: no arrival, no departure, not a timing station, NEXTTIME 0') (($p.Term(1)) -and ($p.Arr(1) -eq -1) -and ($p.Dep(1) -eq -1) -and (-not $p.HasTimeDef(1)) -and ($p.NextTime -le 0))
        }
    }

    # a saturated or odd Int32 below the sentinel is a normal time by the existing range rule; the largest accepted value is Int32.MaxValue - 1
    $p = RunLegacy @($firstL, (LSt 'T' $false $ARR_DEF ([int]2147483646) $STOP30)) 500.0
    Check 'C06 the range rule is unchanged: Int32.MaxValue - 1 is below the sentinel and is read as a time (the arrival defined there is kept)' (($p.Arr(1) -eq $ARR_DEF) -and ($p.RawDep(1) -eq 2147483646))

    # A-T4 a middle stop
    $p = RunLegacy @($firstL, (LSt 'M' $false -1 $DEP_T03 $STOP30), (LSt 'Z' $true 29400000 ([int]2147483647) $STOP30)) 500.0
    Check 'C07 A-T4 a middle station with an undefined arrival: arrival = departure - stop time (unchanged)' ((-not $p.Term(1)) -and ($p.Arr(1) -eq $ARR_T03) -and ($p.Dep(1) -eq $DEP_T03) -and ($p.Term(2)))
    $p = RunLegacy @($firstL, (LSt 'M' $false $ARR_DEF -1 $STOP30), (LSt 'Z' $true 29400000 ([int]2147483647) $STOP30)) 500.0
    Check 'C08 a middle station with an arrival only: departure = arrival + stop time (unchanged)' (($p.Arr(1) -eq $ARR_DEF) -and ($p.Dep(1) -eq ($ARR_DEF + $STOP30)))
    $p = RunLegacy @($firstL, (LSt 'T' $false $ARR_DEF -1 $STOP30)) 500.0
    Check 'C09 a terminal with an arrival only: no departure is made up (unchanged)' (($p.Term(1)) -and ($p.Arr(1) -eq $ARR_DEF) -and ($p.Dep(1) -eq -1))

    # A-T5
    $p = RunLegacy @($firstL, (LSt 'M' $false -1 -1 $STOP30), (LSt 'T' $false -1 -1 $STOP30)) 500.0
    Check 'C10 A-T5 arrival -1 and departure -1: nothing is made up, no exception' (($p.Arr(1) -eq -1) -and ($p.Dep(1) -eq -1) -and (-not $p.HasTimeDef(1)) -and ($p.Arr(2) -eq -1) -and ($p.Term(2)))
    $p = RunLegacy @($firstL, (LSt 'T' $false -1 0 $STOP30)) 500.0
    Check 'C11 a departure of 0 ms is not a usable time: no arrival is made up' (($p.Arr(1) -eq -1) -and (-not $p.HasTimeDef(1)))

    # A-T8 / A-T9
    $p = RunLegacy @($firstL, (LSt 'T' $false $ARR_DEF $DEP_T03 $STOP30)) 500.0
    Check 'C12 A-T8 terminal with a defined arrival AND a normal departure: the arrival stays 08:03:20' (($p.Term(1)) -and ($p.Arr(1) -eq $ARR_DEF) -and ($p.Dep(1) -eq $DEP_T03))
    $p = RunLegacy @($firstL, (LSt 'T' $false -1 10000 $STOP30)) 500.0
    Check 'C13 [RED-A] A-T9 terminal, departure 10 s and stop time 30 s: the arrival is clamped to 0 by the existing range rule' (($p.Arr(1) -eq 0) -and ($p.Dep(1) -eq 10000))
    $p = RunLegacy @($firstL, (LSt 'M' $false -1 10000 $STOP30), (LSt 'Z' $true 29400000 ([int]2147483647) $STOP30)) 500.0
    Check 'C14 A-T9 middle station, same input: the same clamp (unchanged)' (($p.Arr(1) -eq 0) -and ($p.Dep(1) -eq 10000))

    # default time anchors
    $p = RunLegacy @($firstL, (LSt 'T' $false -1 -1 $STOP30 29100000)) 500.0
    Check 'C15 default time anchor on a terminal without any time: arrival = default time, no departure (unchanged)' (($p.Term(1)) -and ($p.Arr(1) -eq 29100000) -and ($p.Dep(1) -eq -1) -and ($p.HasTimeDef(1)))

    # the STALIST keeps its structure: 9 fields per station, the terminal flag in field 9
    $p = RunLegacy @($firstL, (LSt 'Test03' $false -1 $DEP_T03 $STOP30)) 500.0
    $sta = $p.StaList()
    $rows = @(($sta.Substring('STALIST:'.Length)) -split ',')
    $f = @($rows[1] -split '=')
    Check 'C16 the STALIST keeps its structure: 2 stations, 9 fields each, the terminal flag in field 9' (($rows.Count -eq 2) -and ($f.Count -eq 9) -and ($f[8] -eq '1') -and (@($rows[0] -split '=').Count -eq 9))
    Check 'C17 [RED-A] the STALIST of the Test03 type states arrival 29045000 and departure 29075000 (the fill-in is what the HUD side reads)' (($f[3] -eq '29045000') -and ($f[4] -eq '29075000') -and ($f[6] -eq '30000'))

    Write-Host '--- D: Current and Legacy mean the same'
    $pairs = @(
        @('Test03 type', @((St -1 $DEP_T03 $STOP30)), @((LSt 'Test03' $false -1 $DEP_T03 $STOP30)), $ARR_T03, $true),
        @('terminal with arrival and BVE6 sentinel', @((St $ARR_DEF $BVE6 $STOP30)), @((LSt 'T' $false $ARR_DEF ([int]2147483647) $STOP30)), $ARR_DEF, $false),
        @('terminal with arrival and BVE5 sentinel', @((St $ARR_DEF $BVE5 $STOP30)), @((LSt 'T' $false $ARR_DEF ([int]-2147483648) $STOP30)), $ARR_DEF, $false),
        @('terminal without arrival and BVE6 sentinel', @((St -1 $BVE6 $STOP30)), @((LSt 'T' $false -1 ([int]2147483647) $STOP30)), -1, $false),
        @('terminal without arrival and BVE5 sentinel', @((St -1 $BVE5 $STOP30)), @((LSt 'T' $false -1 ([int]-2147483648) $STOP30)), -1, $false),
        @('terminal with both times', @((St $ARR_DEF $DEP_T03 $STOP30)), @((LSt 'T' $false $ARR_DEF $DEP_T03 $STOP30)), $ARR_DEF, $false),
        @('terminal clamp (departure 10 s, stop 30 s)', @((St -1 10000 $STOP30)), @((LSt 'T' $false -1 10000 $STOP30)), 0, $true),
        @('nothing defined', @((St -1 -1 $STOP30)), @((LSt 'T' $false -1 -1 $STOP30)), -1, $false),
        @('arrival only', @((St $ARR_DEF -1 $STOP30)), @((LSt 'T' $false $ARR_DEF -1 $STOP30)), $ARR_DEF, $false))
    foreach ($pair in $pairs) {
        $cur = RunCurrent (@($first) + @($pair[1]))
        $leg = RunLegacy (@($firstL) + @($pair[2])) 500.0
        $same = ($cur[1].ArrTime -eq $leg.Arr(1)) -and ($cur[1].DepTime -eq $leg.Dep(1)) -and ($cur[1].IsTerminal -eq $leg.Term(1)) -and ($cur[1].HasTimeDef -eq $leg.HasTimeDef(1)) -and ($cur[1].RawDepTime -eq $leg.RawDep(1))
        $tag = ''
        if ($pair[4]) { $tag = '[RED-A] ' }
        Check ('D01 ' + $tag + 'Current == Legacy == expected arrival ' + $pair[3] + ' (arrival, departure, terminal, timing, raw departure equal) for: ' + $pair[0] + ' [Current ' + $cur[1].ArrTime + '/' + $cur[1].DepTime + ' Legacy ' + $leg.Arr(1) + '/' + $leg.Dep(1) + ']') ($same -and ($cur[1].ArrTime -eq $pair[3]))
    }
} finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}
Check 'E01 the temporary fixture folder is gone' (-not (Test-Path -LiteralPath $work))

Write-Host ''
Write-Host ('TIMEFIX-A PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'Time Fix A behaviour tests passed.'
