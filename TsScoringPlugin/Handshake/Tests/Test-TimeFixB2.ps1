param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# TIME FIX B2 (operational stop contract) - offline BEHAVIOUR test of the target switch of an operational stop (DoorDir == 0), Current AND Legacy.
#
# The rule under test (the SENDER half of the contract; the scoring half is tests\test_timefix_b2_operational_stop_contract.py):
#   * the stop is established ONCE: |speed| < 0.1 km/h inside the author-defined range of the target station (MarginMin short side, MarginMax past side, both bounds inclusive) - unchanged;
#     that is the arrival candidate event (arr / arrseq +1);
#   * after it the target is switched to the next station by the first of
#       (a) the scheduled departure time reached (the existing 300 ms hold), or
#       (b) the vehicle leaving: |speed| > 0.1 km/h in either direction, AT ONCE (the same Tick); exactly 0.1 km/h is not leaving;
#   * a vehicle that never stopped inside the range keeps the target (it is not switched by passing the far boundary of the range or by the time);
#   * a normal (door) stop, a pass station and the terminal keep their rules; arr / arrseq are not touched by the switch.
#
# HOW: as Test-TimeFixA.ps1. Class1.cs can not run offline (it needs the BveEX host), so the statement block of the station part of its Tick is cut out of the SOURCE of Class1.cs (the text itself, not a copy)
# and compiled in memory (CodeDom, C# 5) with fake fields. The Legacy side compiles the REAL sources of LegacyStationTimeline.cs and its shared files with a small fixture in the same assembly. Both run the
# SAME scenarios. No BVE, no BveEx, no AtsEX, no port, no product build, nothing is written to the repository (the fixture lives in a unique TEMP folder that is removed).
# Cases tagged [RED-B2] fail on the code before Time Fix B2 and pass after it; every other case is a guard that passes before and after.
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

Write-Host '--- the statement block is cut out of Class1.cs'
$source = [IO.File]::ReadAllText($class1, [Text.Encoding]::UTF8)
$stationPart = Get-StationPartStatement $source
$stationDataClass = Get-BlockText $source 'public class StationData'
Check 'S01 the station part of the Current Tick is found exactly once' ($null -ne $stationPart)
Check 'S02 the StationData class is found' ($null -ne $stationDataClass)
if (($null -eq $stationPart) -or ($null -eq $stationDataClass)) {
    Write-Host ''
    Write-Host ('TIMEFIX-B2 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

$currentFixture = @'
using System;
using System.Collections.Generic;

namespace B2Current
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
    Write-Host ('TIMEFIX-B2 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

Write-Host '--- the real Legacy sources are compiled with a fixture'
$work = Join-Path $env:TEMP ('ts-timefix-b2-' + [guid]::NewGuid().ToString('N'))
$legacyFixture = @'
using System;
using System.Collections.Generic;
using TSScoringPlugin.Telemetry;

public sealed class B2LegacyProbe
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
    public void Begin(int index) { Step(500.0, 50.0, 36000000, true); }
    public void Step(double location, double speedKmh, int timeMs, bool doorsClosed)
    {
        last = t.Step(raw, raw.Count, location, speedKmh, timeMs, doorsClosed);
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
    $fixturePath = Join-Path $work 'B2LegacyProbe.cs'
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
    Write-Host ('TIMEFIX-B2 PASS=' + $script:pass + ' FAIL=' + $script:fail)
    exit 1
}

# A idx0 @0 (customer), B idx1 @1000 (the station under test), C idx2 @1100 (a customer station right behind B), D idx3 @3000 (terminal)
function NewProbe([string]$kind, [int]$bDoor = 0, [bool]$bPass = $false, [bool]$bTerminal = $false, [double]$mmin = 5.0, [double]$mmax = 5.0, [bool]$withCd = $true, [bool]$preset = $false) {
    if ($kind -eq 'Legacy') { $p = New-Object B2LegacyProbe } else { $p = New-Object B2Current.Probe }
    $p.Add('A', 0.0, $false, $false, 1, -1, -1, 15000, 5.0, 5.0)
    $p.Add('B', 1000.0, $bPass, $bTerminal, $bDoor, $ARR, $DEP, 15000, $mmin, $mmax)
    if ($withCd) {
        $p.Add('C', 1100.0, $false, $false, 1, ($DEP + 30000), ($DEP + 60000), 15000, 5.0, 5.0)
        $p.Add('D', 3000.0, $false, $true, 1, ($DEP + 400000), -1, 15000, 5.0, 5.0)
    }
    if ($preset) {
        # the target is selected with the doors OPEN 10 m short of B (outside its range): the door flag is preset, no stop is made
        if ($kind -eq 'Legacy') { $p.Step(990.0, 0.0, $T, $false) } else { $p.BeginPreset(1); $p.Step(990.0, 0.0, $T, $false) }
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

    # B2-S00 the stop itself (unchanged): the stop inside the range is the arrival candidate event, NEXTTIME shows the departure time, the target stays B
    $p = NewLatched $k
    Check ($k + ' S00 the stop inside the range: target B, NEXTTIME = departure, arr = B, arrseq = 1') (($p.Target -eq 1) -and ($p.NextTime -eq $DEP) -and ($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))

    # C-T01 the scheduled time reached while standing: the target stays B before the time, at the time and 299 ms after it; it advances at +300 ms; arr / arrseq unchanged
    $p = NewLatched $k
    $p.Step(1000.0, 0.0, ($DEP - 1), $true); $a = $p.Target
    $p.Step(1000.0, 0.0, $DEP, $true); $b = $p.Target
    $p.Step(1000.0, 0.0, ($DEP + 299), $true); $c = $p.Target
    $p.Step(1000.0, 0.0, ($DEP + 300), $true)
    Check ($k + ' C-T01 standing: the target stays B until the departure time + 299 ms and advances to C at +300 ms (existing hold)') (($a -eq 1) -and ($b -eq 1) -and ($c -eq 1) -and ($p.Target -eq 2) -and ($p.NextLoc -eq 1100.0))
    Check ($k + ' C-T12 the switch leaves arr and arrseq as they are (B, 1)') (($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))

    # C-T02 leaving 29 s before the departure time: the target is C on that very Tick
    $p = NewLatched $k
    $p.Step(1000.0, 0.2, ($DEP - 29000), $true)
    Check ($k + ' C-T02 [RED-B2] leaving at 0.2 km/h 29 s before the departure time: the target is C at once, NEXTLOC = C, NEXTTIME = C arrival') (($p.Target -eq 2) -and ($p.NextLoc -eq 1100.0) -and ($p.NextTime -eq ($DEP + 30000)))
    Check ($k + ' C-T12 [RED-B2] the early switch leaves arr and arrseq as they are (B, 1)') (($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1) -and ($p.Target -eq 2))

    # C-T03 leaving exactly at the departure time (and inside the hold): the target is C on that Tick
    $p = NewLatched $k
    $p.Step(1000.0, 0.2, $DEP, $true)
    Check ($k + ' C-T03 [RED-B2] leaving at 0.2 km/h on the Tick of the departure time: the target is C on that Tick (one switch)') ($p.Target -eq 2)
    $p = NewLatched $k
    $p.Step(1000.0, 0.0, $DEP, $true)
    $p.Step(1000.0, 0.2, ($DEP + 100), $true)
    Check ($k + ' C-T03 [RED-B2] leaving during the 300 ms hold does not wait for the end of the hold') ($p.Target -eq 2)

    # C-T04 / C-T05 / C-T07 leaving in either direction
    foreach ($v in @(0.2, 12.0, 0.1001)) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, ($DEP - 20000), $true)
        Check ($k + ' C-T04/T07 [RED-B2] forward ' + $v + ' km/h is leaving: the target is C at once') ($p.Target -eq 2)
    }
    foreach ($v in @(-0.2, -12.0, -0.1001)) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, ($DEP - 20000), $true)
        Check ($k + ' C-T05/T07 [RED-B2] backward ' + $v + ' km/h is leaving: the target is C at once') ($p.Target -eq 2)
    }

    # C-T06 exactly 0.1 km/h (and below) is not leaving
    foreach ($v in @(0.1, -0.1, 0.0999, -0.0999, 0.05, 0.0)) {
        $p = NewLatched $k
        $p.Step(1000.0, $v, ($DEP - 20000), $true)
        $p.Step(1000.0, $v, ($DEP - 10000), $true)
        Check ($k + ' C-T06 ' + $v + ' km/h is not leaving: the target stays B, NEXTTIME = departure') (($p.Target -eq 1) -and ($p.NextTime -eq $DEP))
    }

    # C-T08 the first stop inside the range comes after the departure time: the stop is the arrival event, the target follows after the hold (the actual time is the Python side's record of the stop)
    $p = NewProbe $k
    $p.Step(990.0, 30.0, ($DEP + 19000), $true)
    $before = $p.Target
    $p.Step(1000.0, 0.0, ($DEP + 20000), $true)
    $atStop = @($p.Target, $p.ArrIdx, $p.ArrSeq)
    $p.Step(1000.0, 0.0, ($DEP + 20299), $true); $t299 = $p.Target
    $p.Step(1000.0, 0.0, ($DEP + 20300), $true)
    Check ($k + ' C-T08 a stop made after the departure time is the arrival event (B, 1); the target stays B before the stop and until the hold (300 ms) has run') (($before -eq 1) -and ($atStop[0] -eq 1) -and ($atStop[1] -eq 1) -and ($atStop[2] -eq 1) -and ($t299 -eq 1) -and ($p.Target -eq 2))

    # C-T09 passing B without ever standing inside its range: no arrival event, the target stays B
    $p = NewProbe $k
    foreach ($loc in @(900.0, 996.0, 1000.0, 1004.0, 1010.0, 1050.0, 1200.0, 1500.0)) { $p.Step($loc, 30.0, ($DEP - 20000 + [int]$loc), $true) }
    $p.Step(1500.0, 30.0, ($DEP + 600000), $true)
    Check ($k + ' C-T09 a pass-through without a stop keeps the target B (even past the far boundary and long after the departure time), no arrival event') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0) -and ($p.ArrIdx -eq -1))

    # C-T10 an overrun stop outside the range: no arrival event; the far boundary and the time do not switch the target
    $p = NewProbe $k
    $p.Step(1006.0, 0.0, ($DEP + 5000), $true)
    $p.Step(1006.0, 0.0, ($DEP + 60000), $true)
    $p.Step(1006.0, 0.0, ($DEP + 600000), $true)
    Check ($k + ' C-T10 a stop 6 m past B (range 5 m): no arrival event and the target stays B') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))
    $p.Step(1006.0, 5.0, ($DEP + 610000), $true)
    Check ($k + ' C-T10 leaving at 5 km/h without a stop inside the range does not switch the target') ($p.Target -eq 1)

    # C-T09b leaving (> 0.1 km/h) before the stop inside the range was made does not switch the target either
    $p = NewProbe $k
    $p.Step(999.0, 5.0, ($DEP - 20000), $true)
    $p.Step(1001.0, 5.0, ($DEP - 19000), $true)
    Check ($k + ' C-T09b moving inside the range (never stopped) keeps the target B') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))

    # C-T09c the door flag PRESET by a target selection (doors open within 50 m) is no stop: moving > 0.1 km/h must not switch the target; a real stop afterwards works as usual
    $p = NewProbe $k 0 $false $false 5.0 5.0 $true $true
    $p.Step(990.0, 5.0, ($T + 1000), $false)
    $p.Step(995.0, 20.0, ($T + 2000), $true)
    $p.Step(1002.0, 20.0, ($T + 3000), $true)
    Check ($k + ' C-T09c [RED-B2] a preset door flag with no stop made: moving at 5 / 20 km/h keeps the target B, no arrival event') (($p.Target -eq 1) -and ($p.ArrSeq -eq 0))
    $p.Step(1000.0, 0.0, ($T + 4000), $true)
    $p.Step(1000.0, 0.3, ($T + 5000), $true)
    Check ($k + ' C-T09c a real stop inside the range afterwards makes leaving switch the target (the preset flag already counted as the arrival, so no new arrival event: unchanged behaviour)') ($p.Target -eq 2)

    # C-T11 an early leaving, then the next customer station C is arrived at before the departure time of B: the target is already C, its doors-open arrival is an event of C
    $p = NewLatched $k
    $p.Step(1000.0, 0.2, ($DEP - 50000), $true)
    $p.Step(1050.0, 20.0, ($DEP - 40000), $true)
    $p.Step(1099.6, 0.0, ($DEP - 30000), $true)
    $p.Step(1099.6, 0.0, ($DEP - 29000), $false)
    Check ($k + ' C-T11 [RED-B2] the next customer station C is arrived at before the departure time of B: target C, arr = C (2), arrseq = 2') (($p.Target -eq 2) -and ($p.ArrIdx -eq 2) -and ($p.ArrSeq -eq 2))

    # C-T13 after a retry (the target is chosen again, the stop is made again) the same contract
    $p = NewProbe $k
    $p.Step(1000.0, 0.0, ($DEP - 40000), $true)
    $p.Step(1000.0, 0.3, ($DEP - 30000), $true)
    Check ($k + ' C-T13 [RED-B2] a second stop (as after a retry) is a new event and leaving switches the target at once') (($p.Target -eq 2) -and ($p.ArrIdx -eq 1) -and ($p.ArrSeq -eq 1))

    # C-T14 one switch only: once on C, further movement does not advance past C (a customer station waits for its doors)
    $p = NewLatched $k
    $p.Step(1000.0, 0.2, ($DEP - 20000), $true)
    foreach ($v in @(0.2, 5.0, 30.0, -5.0, 0.0)) { $p.Step(1010.0, $v, ($DEP - 19000), $true) }
    Check ($k + ' C-T14 one switch only: the target is C and stays C') ($p.Target -eq 2)

    # C-T15 a customer (door) stop keeps its rule: the stop with the doors open, leaving with them open does not switch; closing them does
    $p = NewProbe $k 1
    $p.Step(1000.0, 0.0, ($T + 1000), $false)
    $p.Step(1000.0, 5.0, ($T + 2000), $false)
    $open = $p.Target
    $p.Step(1000.0, 0.0, ($T + 3000), $true)
    Check ($k + ' C-T15 a customer stop: speed does not switch the target (doors open: stays B), the doors closing does') (($open -eq 1) -and ($p.Target -eq 2))

    # C-T16 a pass station keeps its rule (by position only)
    $p = NewProbe $k 1 $true
    $p.Step(1000.0, 0.0, ($T + 1000), $true)
    $p.Step(1000.0, 5.0, ($T + 2000), $true)
    $at = $p.Target
    $p.Step(1000.001, 5.0, ($T + 3000), $true)
    Check ($k + ' C-T16 a pass station advances by position only (stopped inside, leaving: stays; past its position: advances)') (($at -eq 1) -and ($p.Target -eq 2))

    # C-T17 the terminal operational stop never advances (the scoring finishes there)
    $p = NewProbe $k 0 $false $true 5.0 5.0 $false
    $p.Step(1000.0, 0.0, ($T + 1000), $true)
    $p.Step(1000.0, 5.0, ($T + 2000), $true)
    $p.Step(1000.0, 5.0, ($DEP + 600000), $true)
    Check ($k + ' C-T17 the terminal operational stop keeps the target B whatever the speed or the time') ($p.Target -eq 1)

    # C-T19 / C-T20 the range of the target station decides the stop (author-defined, both bounds inclusive, MarginMin short side / MarginMax past side)
    $p = NewProbe $k 0 $false $false 4.0 9.0
    $p.Step(996.0, 0.0, ($T + 1000), $true)
    Check ($k + ' C-T19 stopped 4.0 m short with MarginMin 4: the stop is made (arr = B)') (($p.ArrSeq -eq 1) -and ($p.ArrIdx -eq 1))
    $p = NewProbe $k 0 $false $false 4.0 9.0
    $p.Step(995.9, 0.0, ($T + 1000), $true)
    Check ($k + ' C-T20 stopped 4.1 m short with MarginMin 4: the stop is not made, and leaving does not switch') (($p.ArrSeq -eq 0) -and ($p.Target -eq 1))
    $p.Step(995.9, 5.0, ($T + 2000), $true)
    Check ($k + ' C-T20 ... the target stays B') ($p.Target -eq 1)
    $p = NewProbe $k 0 $false $false 4.0 9.0
    $p.Step(1009.0, 0.0, ($T + 1000), $true)
    Check ($k + ' C-T19 stopped 9.0 m past with MarginMax 9: the stop is made') ($p.ArrSeq -eq 1)
}

try {
    Run-Suite 'Current'
    Run-Suite 'Legacy'
} finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}
Check 'E01 the temporary fixture folder is gone' (-not (Test-Path -LiteralPath $work))

Write-Host ''
Write-Host ('TIMEFIX-B2 PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'Time Fix B2 behaviour tests passed.'
