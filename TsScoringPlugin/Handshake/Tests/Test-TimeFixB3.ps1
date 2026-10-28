param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# TIME FIX B3 (zero-speed contract) - offline BEHAVIOUR test of the SENDER half: "stopped" and "moving" of an operational stop (DoorDir == 0), Current AND Legacy.
#
# The contract under test:
#   * BVE supplies exactly 0.0 km/h while the train stands, so there is no noise band:  speed == 0.0 (+0.0 and -0.0) is STOPPED, speed != 0.0 (either sign) is MOVING;
#     0.0001, -0.0001, 0.1, -0.1 and the smallest double are all moving; there is no intermediate state between 0.0 and 0.1 km/h;
#   * the operational stop is MADE once: stopped (== 0.0) inside the author-defined range (MarginMin short side, MarginMax past side, both bounds inclusive) = the arrival candidate event;
#   * after it the target is switched to the next station by the first of (a) the scheduled departure time reached (the existing 300 ms hold) or (b) the vehicle moving (!= 0.0),
#     AT ONCE (the same Tick); the position is not judged again;
#   * a vehicle that never stopped inside the range keeps the target; a normal (door) stop, a pass station and the terminal keep their rules; arr / arrseq are not touched by the switch;
#   * an official jump re-selects the target and forgets the stop that was made before it (the stop has to be made again).
#
# HOW: as Test-TimeFixB2.ps1. Class1.cs can not run offline (it needs the BveEX host), so the statement block of the station part of its Tick is cut out of the SOURCE of Class1.cs and compiled in
# memory (CodeDom, C# 5) with fake fields. The Legacy side compiles the REAL sources of LegacyStationTimeline.cs and its shared files with a small fixture in the same assembly. Both run the SAME
# scenarios. No BVE, no BveEx, no AtsEX, no port, no product build, nothing is written to the repository (the fixture lives in a unique TEMP folder that is removed).
# Cases tagged [RED-B3] fail on the code of Time Fix B2 and pass after B3; every other case is a guard that passes before and after.
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

# the whole `if (targetStationIndex < stationList.Count) { ... }` statement of the station part of the Tick (the one that holds the line `int stationIndexBeforeAdvance = targetStationIndex;`)
function Get-StationPartStatement([string]$text) {
    $marker = 'int stationIndexBeforeAdvance = targetStationIndex;'
    $m = $text.IndexOf($marker, [StringComparison]::Ordinal)
    if ($m -lt 0) { return $null }
    if ($text.IndexOf($marker, $m + 1, [StringComparison]::Ordinal) -ge 0) { return $null }
    $head = 'if (targetStationIndex < stationList.Count)'
    $s = $text.LastIndexOf($head, $m, [StringComparison]::Ordinal)
    if ($s -lt 0) { return $null }
    return (Get-BlockText $text.Substring($s) $head)
}

$T = 36000000           # the Tick the list is built on
$ARR = 36060000         # B arrival time (what NEXTTIME shows before the stop is made)
$DEP = 36120000         # B scheduled departure time (what NEXTTIME shows once the stop is made)
$NEGZERO = [BitConverter]::Int64BitsToDouble([long]::MinValue)     # -0.0
$MINPOS = [double]::Epsilon                                         # the smallest positive double
$MINNEG = -[double]::Epsilon                                        # the smallest negative double
$MOVING = @($MINPOS, $MINNEG, 0.0001, -0.0001, 0.05, -0.05, 0.09, -0.09, 0.1, -0.1, 0.1001, -0.1001, 5.0, -5.0, 30.0)
$STOPPED = @(0.0, $NEGZERO)
function Show([double]$v) { return $v.ToString('R', [Globalization.CultureInfo]::InvariantCulture) }

Write-Host '--- the statement block is cut out of Class1.cs'
$source = [IO.File]::ReadAllText($class1, [Text.Encoding]::UTF8)
$stationPart = Get-StationPartStatement $source
$stationDataClass = Get-BlockText $source 'public class StationData'
Check 'S01 the station part of the Current Tick is found exactly once' ($null -ne $stationPart)
Check 'S02 the StationData class is found' ($null -ne $stationDataClass)
if (($null -eq $stationPart) -or ($null -eq $stationDataClass)) {
    Write-Host ''
    Write-Host ('TIMEFIX-B3 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

$currentFixture = @'
using System;
using System.Collections.Generic;

namespace B3Current
{
//STATIONDATA//

    public sealed class Probe
    {
        private List<StationData> stationList = new List<StationData>();
        private int targetStationIndex = 0;
        private bool hasDoorOpenedAtTarget = false;
        private int opStopDelayStartMs = -1;
        private int opStopMadeIndex = -1;
        private int terminalFrozenDiffSeconds = -999;
        private bool wasTerminalDoorOpened = false;
        private int stidxArrivalIndex = -1;
        private int stidxArrivalSeq = 0;
        private double outLoc = -1;
        private int outTime = -1;

        public void Add(string name, double loc, bool pass, bool terminal, int doorDir, int arrMs, int depMs, int stopMs, double marginMin, double marginMax)
        {
            StationData sd = new StationData();
            sd.Name = name; sd.Location = loc; sd.IsPass = pass; sd.IsTerminal = terminal; sd.DoorDir = doorDir;
            sd.ArrTime = arrMs; sd.DepTime = depMs; sd.RawArrTime = arrMs; sd.RawDepTime = depMs; sd.DefaultTime = -1; sd.InterpolatedTime = -1;
            sd.StoppageTime = stopMs; sd.MarginMin = Math.Abs(marginMin); sd.MarginMax = marginMax; sd.IsScoring = true; sd.HasTimeDef = true;
            stationList.Add(sd);
        }

        // the target the position search of the real code would choose for a vehicle before the first station that is ahead (B, index 1); the door flag is not set by it
        public void Begin(int index) { targetStationIndex = index; hasDoorOpenedAtTarget = false; opStopDelayStartMs = -1; opStopMadeIndex = -1; }
        // a target selection with the doors OPEN within 50 m of the station presets the flag (SelectTargetBy*), with no stop made
        public void BeginPreset(int index) { targetStationIndex = index; hasDoorOpenedAtTarget = true; opStopDelayStartMs = -1; opStopMadeIndex = -1; }

        public void Step(double location, double speed, int timeMs, bool areDoorsClosed)
        {
            int stidxTarget = -1;
            double nextStationLoc = -1;
            int nextStationTime = -1;
            int isPass = 0;
            int isTiming = 0;
            double marginBack = 5.0;
            double marginFront = 5.0;
//STATIONPART//
            outLoc = nextStationLoc;
            outTime = nextStationTime;
            if (isPass < 0 || isTiming < 0 || marginBack < 0 || marginFront < 0 || stidxTarget < -5) { outLoc = -999; }
        }

        public int Target { get { return targetStationIndex; } }
        public double NextLoc { get { return outLoc; } }
        public int NextTime { get { return outTime; } }
        public int ArrIdx { get { return stidxArrivalIndex; } }
        public int ArrSeq { get { return stidxArrivalSeq; } }
    }
}
'@
$currentFixture = $currentFixture.Replace('//STATIONDATA//', $stationDataClass).Replace('//STATIONPART//', $stationPart)
$compileError = $null
try {
    Add-Type -TypeDefinition $currentFixture -ReferencedAssemblies @('System.dll', 'System.Core.dll', 'Microsoft.CSharp.dll') -IgnoreWarnings
} catch {
    $compileError = $_.Exception.Message
}
Check 'S03 the cut-out Current station part compiles in memory (C# 5)' ($null -eq $compileError)
if ($null -ne $compileError) {
    Write-Host ('  compile error: ' + $compileError)
    Write-Host ''
    Write-Host ('TIMEFIX-B3 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

Write-Host '--- the real Legacy sources are compiled with a fixture'
$work = Join-Path $env:TEMP ('ts-timefix-b3-' + [guid]::NewGuid().ToString('N'))
$legacyFixture = @'
using System;
using System.Collections.Generic;
using TSScoringPlugin.Telemetry;

public sealed class B3LegacyProbe
{
    private LegacyStationTimeline t = new LegacyStationTimeline();
    private List<LegacyStationRaw> raw = new List<LegacyStationRaw>();
    private StationValues last;

    public void Add(string name, double loc, bool pass, bool terminal, int doorDir, int arrMs, int depMs, int stopMs, double marginMin, double marginMax)
    {
        LegacyStationRaw r = new LegacyStationRaw();
        r.Name = name; r.Location = loc; r.Pass = pass; r.IsTerminal = terminal; r.DoorSide = doorDir;
        r.ArrivalMs = arrMs; r.DepartureMs = depMs; r.DefaultMs = -1; r.StoppageMs = stopMs; r.MarginMin = marginMin; r.MarginMax = marginMax;
        raw.Add(r);
    }
    // Phase SI-R2.4 C5a: the explicit seed. The target is the given index because the timeline is asked for it (RequestTarget, one shot, consumed by the first selection); nothing reads the vehicle position to choose it.
    public void Seed(int index) { t.RequestTarget(index, raw[index].Location); }
    public void Begin(int index) { Seed(index); Step(500.0, 50.0, 36000000, true); }
    public void Step(double location, double speedKmh, int timeMs, bool doorsClosed)
    {
        last = t.Step(raw, raw.Count, location, speedKmh, timeMs, doorsClosed);
    }
    // an official jump: the next Tick re-selects the target by the ADOPTED index (the one-shot request) after the time discontinuity
    public void Jump(int index, double location)
    {
        t.MarkDiscontinuity();
        t.RequestTarget(index, location);
    }
    // a new scenario instance: nothing of the previous one is kept (the host list is built again by the next Step)
    public void NewScenario()
    {
        t.Reset();
        raw.Clear();
    }
    public int Target { get { return t.TargetIndex; } }
    public double NextLoc { get { return last.NextLoc; } }
    public int NextTime { get { return last.NextTime; } }
    public int ArrIdx { get { return t.ArrivalIndex; } }
    public int ArrSeq { get { return t.ArrivalSeq; } }
}
'@
$legacyReady = $false
$legacyError = $null
try {
    New-Item -ItemType Directory -Path $work | Out-Null
    $fixturePath = Join-Path $work 'B3LegacyProbe.cs'
    [IO.File]::WriteAllText($fixturePath, $legacyFixture, (New-Object Text.UTF8Encoding($false)))
    $sources = @(
        (Join-Path $tele 'Legacy\src\LegacyStationTimeline.cs'),
        (Join-Path $tele 'Legacy\src\LegacyApi.cs'),
        (Join-Path $tele 'Shared\TelemetryContract.cs'),
        (Join-Path $tele 'Shared\StationListIdentity.cs'),
        (Join-Path $tele 'Shared\JumpWire.cs'),
        $fixturePath)
    Add-Type -Path $sources -ReferencedAssemblies @('System.dll', 'System.Core.dll') -IgnoreWarnings
    $legacyReady = $true
} catch {
    $legacyError = $_.Exception.Message
    if ($_.Exception.PSObject.Properties['LoaderExceptions']) { $legacyError = $legacyError + ' ' + (($_.Exception.LoaderExceptions | ForEach-Object { $_.Message }) -join ' | ') }
}
Check 'S04 the real Legacy sources compile in memory with the fixture' $legacyReady
if (-not $legacyReady) {
    Write-Host ('  compile error: ' + $legacyError)
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host ''
    Write-Host ('TIMEFIX-B3 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

# A idx0 @0 (customer), B idx1 @1000 (the station under test), C idx2 @1100 (a customer station right behind B), D idx3 @3000 (terminal)
function NewProbe([string]$kind, [int]$bDoor = 0, [bool]$bPass = $false, [bool]$bTerminal = $false, [double]$mmin = 5.0, [double]$mmax = 5.0, [bool]$withCd = $true, [bool]$preset = $false) {
    if ($kind -eq 'Legacy') { $p = New-Object B3LegacyProbe } else { $p = New-Object B3Current.Probe }
    $p.Add('A', 0.0, $false, $false, 1, -1, -1, 15000, 5.0, 5.0)
    $p.Add('B', 1000.0, $bPass, $bTerminal, $bDoor, $ARR, $DEP, 15000, $mmin, $mmax)
    if ($withCd) {
        $p.Add('C', 1100.0, $false, $false, 1, ($DEP + 30000), ($DEP + 60000), 15000, 5.0, 5.0)
        $p.Add('D', 3000.0, $false, $true, 1, ($DEP + 400000), -1, 15000, 5.0, 5.0)
    }
    if ($preset) {
        # the target is selected with the doors OPEN 10 m short of B (outside its range): the door flag is preset, no stop is made
        if ($kind -eq 'Legacy') { $p.Seed(1); $p.Step(990.0, 0.0, $T, $false) } else { $p.BeginPreset(1); $p.Step(990.0, 0.0, $T, $false) }
        return $p
    }
    $p.Begin(1)
    $p.Step(500.0, 50.0, $T, $true)         # the list is built, the target is B, the vehicle is running with the doors closed
    return $p
}
function NewLatched([string]$kind) {
    $p = NewProbe $kind
    $p.Step(1000.0, 0.0, ($T + 1000), $true)
    return $p
}

function Run-Suite([string]$kind) {
    Write-Host ('--- ' + $kind)
    $k = $kind

    # Z-T01 / Z-T02 / Z-T08 the stop: exactly 0.0 (+0.0 and -0.0) inside the range is the arrival candidate event (arr = B, arrseq 1), NEXTTIME shows the departure time, the target stays B
    foreach ($v in $STOPPED) {
        $p = NewProbe $k
        $p.Step(1000.0, $v, ($T + 1000), $true)
        Check ($k + ' Z-T01/T02/T08 speed ' + (Show $v) + ' inside the range makes the stop: target B, NEXTTIME = departure, arr = B, arrseq = 1') (($p.Target -eq 1) -and ($p.NextTime -eq $DEP) -and ($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))
    }

    # Z-T03 .. Z-T06 no non-zero speed makes the stop (the 0.0 .. 0.1 km/h band is moving, not stopped)
    foreach ($v in $MOVING) {
        $p = NewProbe $k
        $p.Step(1000.0, $v, ($T + 1000), $true)
        $p.Step(1000.0, $v, ($T + 2000), $true)
        $tag = ''
        if ([Math]::Abs($v) -lt 0.1) { $tag = '[RED-B3] ' }
        Check ($k + ' Z-T03..T06 ' + $tag + 'speed ' + (Show $v) + ' inside the range makes NO stop: no arrival event, NEXTTIME = arrival, the target stays B') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0) -and ($p.ArrIdx -eq -1) -and ($p.NextTime -eq $ARR))
    }

    # Z-T07 moving through the range before any stop was made starts nothing
    foreach ($v in $MOVING) {
        $p = NewProbe $k
        foreach ($loc in @(996.0, 1000.0, 1004.0, 1010.0, 1050.0)) { $p.Step($loc, $v, ($DEP - 20000 + [int]$loc), $true) }
        $tag = ''
        if ([Math]::Abs($v) -lt 0.1) { $tag = '[RED-B3] ' }
        Check ($k + ' Z-T07 ' + $tag + 'moving at ' + (Show $v) + ' through the range without a stop: target B, no arrival event') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))
    }

    # Z-T09 / Z-T10 after the stop ANY non-zero speed (either sign) is leaving: the target is C on that very Tick, arr / arrseq unchanged
    foreach ($v in $MOVING) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, ($DEP - 20000), $true)
        $tag = ''
        if ([Math]::Abs($v) -le 0.1) { $tag = '[RED-B3] ' }
        Check ($k + ' Z-T09/T10 ' + $tag + 'leaving at ' + (Show $v) + ' km/h after the stop: the target is C at once, NEXTLOC = C, arr / arrseq stay (B, 1)') (($p.Target -eq 2) -and ($p.NextLoc -eq 1100.0) -and ($p.NextTime -eq ($DEP + 30000)) -and ($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))
    }

    # Z-T09b the stop holds at 0.0 and -0.0: standing does not switch before the time
    foreach ($v in $STOPPED) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, ($DEP - 20000), $true)
        $p.Step(1000.0, $v, ($DEP - 10000), $true)
        Check ($k + ' Z-T09b speed ' + (Show $v) + ' after the stop is not leaving: the target stays B until the time') (($p.Target -eq 1) -and ($p.NextTime -eq $DEP))
    }

    # Z-T11 standing until the scheduled time: the target stays B until the departure time + 299 ms and advances to C at +300 ms (the existing hold); arr / arrseq unchanged
    foreach ($v in $STOPPED) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, ($DEP - 1), $true); $a = $p.Target
        $p.Step(1000.0, $v, $DEP, $true); $b = $p.Target
        $p.Step(1000.0, $v, ($DEP + 299), $true); $c = $p.Target
        $p.Step(1000.0, $v, ($DEP + 300), $true)
        Check ($k + ' Z-T11 standing (' + (Show $v) + '): B until the departure time + 299 ms, C at +300 ms (existing hold), NEXTLOC = C') (($a -eq 1) -and ($b -eq 1) -and ($c -eq 1) -and ($p.Target -eq 2) -and ($p.NextLoc -eq 1100.0))
        Check ($k + ' Z-T11 the switch leaves arr and arrseq as they are (B, 1)') (($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))
    }

    # Z-T12 the position at the departure is not judged again: leaving from far outside the range still switches
    foreach ($loc in @(1030.0, 970.0, 1005.001, 994.999)) {
        $p = NewLatched $k
        $p.Step($loc, 0.0001, ($DEP - 20000), $true)
        Check ($k + ' Z-T12 [RED-B3] leaving at 0.0001 km/h from ' + $loc + ' (outside the range, the stop was made inside): the target is C') ($p.Target -eq 2)
        $p = NewLatched $k
        $p.Step($loc, 5.0, ($DEP - 20000), $true)
        Check ($k + ' Z-T12 leaving at 5 km/h from ' + $loc + ' (outside the range, the stop was made inside): the target is C') ($p.Target -eq 2)
    }

    # Z-T13 passing B without ever standing inside its range: no arrival event, the target stays B (even at tiny speeds, past the far boundary and long after the departure time)
    foreach ($v in @(30.0, 0.0001, -0.0001, 0.05, 0.1, -0.1)) {
        $p = NewProbe $k
        foreach ($loc in @(900.0, 996.0, 1000.0, 1004.0, 1010.0, 1050.0, 1200.0, 1500.0)) { $p.Step($loc, $v, ($DEP - 20000 + [int]$loc), $true) }
        $p.Step(1500.0, $v, ($DEP + 600000), $true)
        $tag = ''
        if ([Math]::Abs($v) -lt 0.1) { $tag = '[RED-B3] ' }
        Check ($k + ' Z-T13 ' + $tag + 'a pass-through at ' + (Show $v) + ' km/h keeps the target B, no arrival event') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0) -and ($p.ArrIdx -eq -1))
    }

    # Z-T13b an overrun stop outside the range: no arrival event; the far boundary and the time do not switch the target; moving later does not either
    $p = NewProbe $k
    $p.Step(1006.0, 0.0, ($DEP + 5000), $true)
    $p.Step(1006.0, 0.0, ($DEP + 60000), $true)
    $p.Step(1006.0, 0.0, ($DEP + 600000), $true)
    Check ($k + ' Z-T13b a stop 6 m past B (range 5 m): no arrival event and the target stays B') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))
    $p.Step(1006.0, 0.0001, ($DEP + 610000), $true)
    Check ($k + ' Z-T13b moving at 0.0001 km/h without a stop inside the range does not switch the target') ($p.Target -eq 1)

    # Z-T14 the first stop inside the range comes after the departure time: the stop is the arrival event, the target follows after the hold (the actual time is the Python side's record of the stop)
    $p = NewProbe $k
    $p.Step(990.0, 30.0, ($DEP + 19000), $true)
    $before = $p.Target
    $p.Step(1000.0, 0.0, ($DEP + 20000), $true)
    $atStop = @($p.Target, $p.ArrIdx, $p.ArrSeq)
    $p.Step(1000.0, 0.0, ($DEP + 20299), $true); $t299 = $p.Target
    $p.Step(1000.0, 0.0, ($DEP + 20300), $true)
    Check ($k + ' Z-T14 a stop made after the departure time is the arrival event (B, 1); the target stays B until the hold (300 ms) has run') (($before -eq 1) -and ($atStop[0] -eq 1) -and ($atStop[1] -eq 1) -and ($atStop[2] -eq 1) -and ($t299 -eq 1) -and ($p.Target -eq 2))

    # Z-T15 the scheduled time and a non-zero speed on the same Tick: one switch, on that Tick
    foreach ($v in @(0.0001, -0.0001, 0.1, 12.0)) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, $DEP, $true)
        $tag = ''
        if ([Math]::Abs($v) -le 0.1) { $tag = '[RED-B3] ' }
        Check ($k + ' Z-T15 ' + $tag + 'moving at ' + (Show $v) + ' on the Tick of the departure time: the target is C on that Tick') ($p.Target -eq 2)
        foreach ($w in @(0.0, 5.0, -5.0, 0.0001)) { $p.Step(1010.0, $w, ($DEP + 1000), $true) }
        Check ($k + ' Z-T15 one switch only: the target is C and stays C however the vehicle moves afterwards') ($p.Target -eq 2)
    }
    $p = NewLatched $k
    $p.Step(1000.0, 0.0, $DEP, $true)
    $p.Step(1000.0, 0.0001, ($DEP + 100), $true)
    Check ($k + ' Z-T15 [RED-B3] moving at 0.0001 km/h during the 300 ms hold does not wait for the end of the hold') ($p.Target -eq 2)

    # the preset door flag (a target selected with the doors open within 50 m) is no stop: moving at any speed must not switch the target; a real stop afterwards works as usual
    $p = NewProbe $k 0 $false $false 5.0 5.0 $true $true
    $p.Step(990.0, 0.0001, ($T + 1000), $false)
    $p.Step(995.0, 20.0, ($T + 2000), $true)
    $p.Step(1002.0, -0.0001, ($T + 3000), $true)
    Check ($k + ' Z-T07b a preset door flag with no stop made: moving at 0.0001 / 20 / -0.0001 km/h keeps the target B, no arrival event') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))
    $p.Step(1000.0, 0.0, ($T + 4000), $true)
    $p.Step(1000.0, -0.0001, ($T + 5000), $true)
    Check ($k + ' Z-T07b [RED-B3] a real stop inside the range afterwards makes moving (-0.0001 km/h) switch the target') ($p.Target -eq 2)

    # an early leaving, then the next customer station C is arrived at before the departure time of B: the target is already C, its doors-open arrival is an event of C
    $p = NewLatched $k
    $p.Step(1000.0, 0.0001, ($DEP - 50000), $true)
    $p.Step(1050.0, 20.0, ($DEP - 40000), $true)
    $p.Step(1099.6, 0.0, ($DEP - 30000), $true)
    $p.Step(1099.6, 0.0, ($DEP - 29000), $false)
    Check ($k + ' Z-T09c [RED-B3] after leaving at 0.0001 km/h the next customer station C is arrived at before the departure time of B: target C, arr = C (2), arrseq = 2') (($p.Target -eq 2) -and ($p.ArrIdx -eq 2) -and ($p.ArrSeq -eq 2))

    # a customer (door) stop keeps its rule: the stop with the doors open, moving with them open does not switch; closing them does
    $p = NewProbe $k 1
    $p.Step(1000.0, 0.0, ($T + 1000), $false)
    $p.Step(1000.0, 5.0, ($T + 2000), $false)
    $p.Step(1000.0, 0.0001, ($T + 2500), $false)
    $open = $p.Target
    $p.Step(1000.0, 0.0, ($T + 3000), $true)
    Check ($k + ' a customer stop: speed does not switch the target (doors open: stays B), the doors closing does') (($open -eq 1) -and ($p.Target -eq 2))

    # a pass station keeps its rule (by position only)
    $p = NewProbe $k 1 $true
    $p.Step(1000.0, 0.0, ($T + 1000), $true)
    $p.Step(1000.0, 0.0001, ($T + 2000), $true)
    $at = $p.Target
    $p.Step(1000.001, 5.0, ($T + 3000), $true)
    Check ($k + ' a pass station advances by position only (stopped inside, moving: stays; past its position: advances)') (($at -eq 1) -and ($p.Target -eq 2))

    # the terminal operational stop never advances (the scoring finishes there)
    $p = NewProbe $k 0 $false $true 5.0 5.0 $false
    $p.Step(1000.0, 0.0, ($T + 1000), $true)
    $p.Step(1000.0, 0.0001, ($T + 2000), $true)
    $p.Step(1000.0, 5.0, ($DEP + 600000), $true)
    Check ($k + ' the terminal operational stop keeps the target B whatever the speed or the time') ($p.Target -eq 1)

    # the range of the target station decides the stop (author-defined, both bounds inclusive, MarginMin short side / MarginMax past side)
    $p = NewProbe $k 0 $false $false 4.0 9.0
    $p.Step(996.0, 0.0, ($T + 1000), $true)
    Check ($k + ' stopped 4.0 m short with MarginMin 4: the stop is made (arr = B)') (($p.ArrSeq -eq 1) -and ($p.ArrIdx -eq 1))
    $p = NewProbe $k 0 $false $false 4.0 9.0
    $p.Step(995.9, 0.0, ($T + 1000), $true)
    Check ($k + ' stopped 4.1 m short with MarginMin 4: the stop is not made, and moving does not switch') (($p.ArrSeq -eq 0) -and ($p.Target -eq 1))
    $p.Step(995.9, 0.0001, ($T + 2000), $true)
    Check ($k + ' ... the target stays B') ($p.Target -eq 1)
    $p = NewProbe $k 0 $false $false 4.0 9.0
    $p.Step(1009.0, 0.0, ($T + 1000), $true)
    Check ($k + ' stopped 9.0 m past with MarginMax 9: the stop is made') ($p.ArrSeq -eq 1)
}

try {
    Run-Suite 'Current'
    Run-Suite 'Legacy'

    # Z-T17 / Z-T18 / Z-T19 the JUMP boundary of the sender, on the REAL Legacy source: an official jump re-selects the target by the adopted index and forgets the stop that was made before it
    Write-Host '--- Legacy jump boundary (real source)'
    $p = NewLatched 'Legacy'
    $p.Jump(1, 1000.0)
    $p.Step(1000.0, 5.0, ($DEP - 40000), $true)
    $p.Step(1000.0, -3.0, ($DEP - 39000), $true)
    Check 'Legacy Z-T17 after an official jump to B the stop made before the jump is forgotten: moving at 5 / -3 km/h keeps the target B (the stop has to be made again)' ($p.Target -eq 1)
    $p = NewLatched 'Legacy'
    $p.Jump(1, 1000.0)
    $p.Step(1000.0, 0.0001, ($DEP - 40000), $true)
    $p.Step(1000.0, -0.0001, ($DEP - 39000), $true)
    Check 'Legacy Z-T17 [RED-B3] ... also at 0.0001 / -0.0001 km/h (neither is a stop, neither is a stop that was made again)' ($p.Target -eq 1)
    $p = NewLatched 'Legacy'
    $p.Jump(1, 1000.0)
    $p.Step(1000.0, 0.0, ($DEP - 40000), $true)
    $p.Step(1000.0, 12.0, ($DEP - 30000), $true)
    Check 'Legacy Z-T18 after the jump the stop is made again at 0.0 km/h and moving at 12 km/h then switches the target at once, arr = B' (($p.Target -eq 2) -and ($p.ArrIdx -eq 1))
    $p = NewLatched 'Legacy'
    $p.Jump(1, 1000.0)
    $p.Step(1000.0, 0.0, ($DEP - 40000), $true)
    $p.Step(1000.0, -0.0001, ($DEP - 30000), $true)
    Check 'Legacy Z-T18 [RED-B3] ... and moving at -0.0001 km/h switches it as well' ($p.Target -eq 2)
    $p = NewLatched 'Legacy'
    $p.NewScenario()
    $p.Add('A', 0.0, $false, $false, 1, -1, -1, 15000, 5.0, 5.0)
    $p.Add('B', 1000.0, $false, $false, 0, $ARR, $DEP, 15000, 5.0, 5.0)
    $p.Add('C', 1100.0, $false, $false, 1, ($DEP + 30000), ($DEP + 60000), 15000, 5.0, 5.0)
    $p.Add('D', 3000.0, $false, $true, 1, ($DEP + 400000), -1, 15000, 5.0, 5.0)
    $p.Seed(1)     # the new scenario instance targets B because it is asked to (the seed), not because the vehicle stands at B
    $p.Step(1000.0, 5.0, ($T + 5000), $true)
    Check 'Legacy Z-T19 a new scenario instance forgets the stop of the old one: moving inside the range of B keeps the target B, arrseq restarts' (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))
} finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}

# Z-T17 on Current: the (re)initialisation block clears the stop record before the target is declared initialised, and every path that forgets the target goes through it
$reinit = Get-BlockText $source 'int requestedStationIndex = -1;'
Check 'Current Z-T17 the re-initialisation block is found' ($null -ne $reinit)
$posSelect = $source.IndexOf('else if (!requestedTargetRefused) SelectTargetByPosition(location, areDoorsClosed);', [StringComparison]::Ordinal)
$posClear = $source.IndexOf('opStopMadeIndex = -1;', $posSelect, [StringComparison]::Ordinal)
$posInit = $source.IndexOf('isInitialized = true;', $posSelect, [StringComparison]::Ordinal)
Check 'Current Z-T17 opStopMadeIndex is cleared after the target is (re)selected and before isInitialized becomes true' (($posSelect -gt 0) -and ($posClear -gt $posSelect) -and ($posInit -gt $posClear) -and (($posInit - $posSelect) -lt 400))
$reinitFn = Get-BlockText $source 'private void ReinitializeTargetStateAfterJump()'
Check 'Current Z-T17 a jump re-initialisation makes the next Tick rebuild (isInitialized = false) and drops the door flag' (($null -ne $reinitFn) -and $reinitFn.Contains('isInitialized = false;') -and $reinitFn.Contains('hasDoorOpenedAtTarget = false;'))
$selectFns = (Get-BlockText $source 'private void SelectTargetByRequestedIndex') + (Get-BlockText $source 'private void SelectTargetByPosition')
Check 'Current Z-T17 the Select* functions do not set the stop record (a selection is never a stop)' (-not $selectFns.Contains('opStopMadeIndex'))
Check 'Current Z-T18 the stop record is written in exactly one place: the stop made inside the range' (([regex]::Matches($source, 'opStopMadeIndex = targetStationIndex;')).Count -eq 1)

# the Legacy source: the same shape
$legacySource = [IO.File]::ReadAllText((Join-Path $tele 'Legacy\src\LegacyStationTimeline.cs'), [Text.Encoding]::UTF8)
Check 'Legacy Z-T18 the stop record is written in exactly one place: the stop made inside the range' (([regex]::Matches($legacySource, 'opStopMadeIndex = target;')).Count -eq 1)
Check 'Legacy Z-T17 the rebuild clears the stop record before the timeline is initialised' ($legacySource.Contains('SelectTarget(location, areDoorsClosed);' + [Environment]::NewLine + '                opStopMadeIndex = -1;') -or $legacySource.Contains("SelectTarget(location, areDoorsClosed);`n                opStopMadeIndex = -1;"))

Check 'E01 the temporary fixture folder is gone' (-not (Test-Path -LiteralPath $work))

Write-Host ''
Write-Host ('TIMEFIX-B3 PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'Time Fix B3 behaviour tests passed.'
