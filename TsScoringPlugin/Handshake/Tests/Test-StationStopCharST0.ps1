# PHASE PID-D4JA StationIndex ST-0 (file C3) - CHARACTERIZATION of the stop / door / operational-stop / pass / author-defined-range behaviour of the Legacy
# station state machine (LegacyStationTimeline.Step). It is the Legacy half of T13 / T14 / T15 / T17 of 11-Red-Test-Plan.md of the contract-gap audit
# (pid-stationindex-contract-gap-audit-v1); the Python half is tests\test_char_stop_door_arrival_st0.py, the source-shape half (Current Class1.cs cannot run offline)
# is tests\test_char_stop_door_source_pins_st0.py. It pins what the DLL does TODAY and nothing else. Every check carries one of the five meanings
# (the same words as the Python files): REQUIREMENT-BACKED / CURRENT-BEHAVIOR-ONLY / KNOWN-DEFECT-BEHAVIOR / CROSS-LAYER-DIFFERENCE / FUTURE-REPLACEMENT-TARGET.
# NOTHING here approves a current behaviour as a requirement: 0.1 km/h, 300 ms, 100 m, the inclusive range bounds are pinned as they are.
#
# HOW: exactly as Test-StationTimelineJF1.ps1: the BUILT Legacy telemetry DLL is loaded from memory and driven through a tiny public fixture class compiled here from a
# here-string (the DLL grants its internals to an assembly named TsScoringLegacyTelemetryTests). The fixture differs only in that it can set the two margins per
# station and exposes the margin / pass / terminal / door-side values of the Tick. No BVE, no AtsEX runtime, no BveEX, no network, no hook, no process. The only thing written
# is a temporary folder under the user TEMP (unique name), removed in a finally block; a leftover is a failure of this script.
#
# INCONCLUSIVE (exit 2, never a pass): the DLL is missing, or its SHA-256, or the SHA-256 of src\LegacyStationTimeline.cs, is not the audited one below; or the fixture can not be compiled / loaded.
# Exit codes: 0 = every check passed, 1 = a check failed, 2 = INCONCLUSIVE.
# This script is ASCII-only on purpose and runs on Windows PowerShell 5.1.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$AuditedDllSha256 = '43E7B9D35F840FAEF0DFCBEC8F2EDB66F259F42FA9CD62644B1DFD1A45EDF691'      # Legacy telemetry 0.6.0.0 DEFAULT build (flag OFF), the build Test-StationTimelineJF1.ps1 audits
$AuditedTimelineSourceSha256 = '948087E7F7A6581E72B2C15A79F1C91B6F29FC4CD706D5E2A712A7933A5E8C29'      # SI-R2.4 C5b (pin moved from 5A0DE805...): the changed lines were re-audited - SelectTarget only: the loop of the position search is gone, a re-initialisation that carries no StationIndex leaves target = list.Count (UNSET), and two comments were reworded; no other statement moved. The checks below describe the DLL pinned next to it (the build BEFORE ST-1A), which still chooses by position by itself, so none of them changed; Handshake\Tests\Test-TimeFixB3.ps1 and Handshake\Tests\LegacyJumpST3CTestCases.cs hold the UNSET contract of the source. Time Fix B3 (pin moved from 09E12B96...): the two comparisons of the operational stop in the state machine (Step) became the exact zero-speed contract (stopped = speedKmh == 0.0, leaving = speedKmh != 0.0, either sign); the hold, the customer stop, the pass station and the STIDX members are unchanged. The checks below describe the DLL pinned next to it (the build BEFORE Time Fix A, B2 and B3), so 'the hold is not cancelled by the vehicle moving' still describes that DLL; Test-TimeFixB2.ps1 / Test-TimeFixB3.ps1 hold the current rule. Time Fix B2 (pin moved from BB844037...): the source gained ONE branch of the state machine (Step): once the operational stop was made (hasDoorOpenedAtTarget) the vehicle leaving (|speedKmh| > 0.1, not the terminal) advances the target at once; the stop test, the departure-time hold, the customer stop, the pass station and the STIDX members are unchanged. The checks below describe the DLL pinned next to it (the build BEFORE Time Fix A and B2), so 'the hold is not cancelled by the vehicle moving' still describes that DLL; Test-TimeFixB2.ps1 holds the new rule for the next DLL pin move. Time Fix A (pin moved from A900FB13...): the source gained ONLY two value-based statements of Build (the departure reader no longer drops a usable departure because the API states the station terminal; the arrival fill-in no longer asks whether the station is the terminal) - the diff is in the Time Fix A artifact; no statement of the state machine (Step) changed, and the checks below describe the DLL pinned next to it (the build BEFORE Time Fix A), so the F23 check 'a terminal station ignores a departure time' still describes that DLL and is superseded by Test-TimeFixA.ps1 for the next DLL pin move. Phase ST-3c (pin moved from CCAB41A1..., see Test-StationTimelineJF1.ps1: additive jump-side members only, no state machine statement changed). Phase ST-1A (pin moved from 23ABFA29..., see Test-StationTimelineJF1.ps1): additive, observation-only members for the STIDX part; the DLL above is still the build BEFORE ST-1A

$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$srcPath = Join-Path $Root 'Telemetry\Legacy\src\LegacyStationTimeline.cs'

$script:pass = 0
$script:fail = 0
$Labels = @('REQUIREMENT-BACKED', 'CURRENT-BEHAVIOR-ONLY', 'KNOWN-DEFECT-BEHAVIOR', 'CROSS-LAYER-DIFFERENCE', 'FUTURE-REPLACEMENT-TARGET')
function Check([string]$id, [string]$label, [string]$name, [bool]$ok) {
    $labelOk = $Labels -contains $label
    if ($ok -and $labelOk) { $script:pass++; Write-Host ('PASS CHAR ' + $id + ' [' + $label + '] ' + $name) } else { $script:fail++; Write-Host ('FAIL CHAR ' + $id + ' [' + $label + '] ' + $name) }
}
function Inconclusive([string]$why) { Write-Host ('INCONCLUSIVE ' + $why); exit 2 }

# ---- preflight: the audited DLL and source ------------------------------------------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $dllPath)) { Inconclusive ('the built DLL is missing: ' + $dllPath) }
if (-not (Test-Path -LiteralPath $srcPath)) { Inconclusive ('the timeline source is missing: ' + $srcPath) }
$dllSha = (Get-FileHash -LiteralPath $dllPath -Algorithm SHA256).Hash
$srcSha = (Get-FileHash -LiteralPath $srcPath -Algorithm SHA256).Hash
if ($dllSha -ne $AuditedDllSha256) { Inconclusive ('the DLL is not the audited build (SHA-256 ' + $dllSha + '); re-audit before trusting these checks') }
if ($srcSha -ne $AuditedTimelineSourceSha256) { Inconclusive ('src\LegacyStationTimeline.cs is not the audited source (SHA-256 ' + $srcSha + ')') }
Write-Host ('PREFLIGHT the DLL (0.6.0.0 default build, ' + $dllSha.Substring(0, 8) + ') and src\LegacyStationTimeline.cs (' + $srcSha.Substring(0, 8) + ') are the audited ones')

$fixtureSource = @'
using System;
using System.Collections.Generic;
using TSScoringPlugin.Telemetry;

public sealed class StopProbe
{
    private LegacyStationTimeline t = new LegacyStationTimeline();
    private List<LegacyStationRaw> raw = new List<LegacyStationRaw>();
    private StationValues last;

    public void Add(string name, double loc, bool pass, bool terminal, int doorSide, int arrMs, int depMs, int stopMs, double marginMin, double marginMax)
    {
        LegacyStationRaw r = new LegacyStationRaw();
        r.Name = name; r.Location = loc; r.Pass = pass; r.IsTerminal = terminal; r.DoorSide = doorSide;
        r.ArrivalMs = arrMs; r.DepartureMs = depMs; r.DefaultMs = -1; r.StoppageMs = stopMs; r.MarginMin = marginMin; r.MarginMax = marginMax;
        raw.Add(r);
    }
    public void Step(double location, double speedKmh, int timeMs, bool doorsClosed)
    {
        last = t.Step(raw, raw.Count, location, speedKmh, timeMs, doorsClosed);
    }
    public int Target { get { return t.TargetIndex; } }
    public double NextLoc { get { return last.NextLoc; } }
    public int NextTime { get { return last.NextTime; } }
    public int IsPass { get { return last.IsPass; } }
    public double MarginBack { get { return last.MarginBack; } }
    public double MarginFront { get { return last.MarginFront; } }
    public int DoorDir { get { return last.DoorDir; } }
    public int Term { get { return last.Term; } }
    public string Name { get { return last.Name; } }
}

public static class StopResolver
{
    public static System.Reflection.Assembly Telemetry;
    public static void Install()
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            if (Telemetry != null && e.Name.StartsWith("TSScoringPlugin.AtsExLegacy.Telemetry", StringComparison.Ordinal)) { return Telemetry; }
            return null;
        };
    }
}
'@

$work = Join-Path $env:TEMP ('ts-st0-c3-' + [guid]::NewGuid().ToString('N'))
$exitCode = 0
try {
    New-Item -ItemType Directory -Path $work | Out-Null
    $dllCopy = Join-Path $work 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
    Copy-Item -LiteralPath $dllPath -Destination $dllCopy
    $fixtureDll = Join-Path $work 'TsScoringLegacyTelemetryTests.dll'
    try {
        Add-Type -TypeDefinition $fixtureSource -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
        $telAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($dllCopy))
    } catch {
        Write-Host ('INCONCLUSIVE the fixture could not be compiled: ' + $_.Exception.Message)
        $exitCode = 2
    }
    if ($exitCode -eq 0) {
        $fixAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($fixtureDll))
        $resolver = $fixAsm.GetType('StopResolver')
        $resolver.GetField('Telemetry').SetValue($null, $telAsm)
        $resolver.GetMethod('Install').Invoke($null, @())
        $probeType = $fixAsm.GetType('StopProbe')
        if ($null -eq $probeType) { Write-Host 'INCONCLUSIVE the fixture type is not visible'; $exitCode = 2 }
    }
    if ($exitCode -eq 0) {
        function NewProbe { return [Activator]::CreateInstance($probeType) }
        function AddS($p, [string]$n, [double]$loc, [bool]$pass = $false, [bool]$term = $false, [int]$door = 1, [int]$arr = -1, [int]$dep = -1, [int]$stop = 15000, [double]$mmin = 5.0, [double]$mmax = 5.0) {
            $p.Add($n, $loc, $pass, $term, $door, $arr, $dep, $stop, $mmin, $mmax)
        }
        function Near([double]$a, [double]$b) { return ([math]::Abs($a - $b) -lt 1e-9) }
        $T = 36000000
        $ARR = 36060000      # the arrival time of the station under test (what NextTime shows BEFORE the arrival flag)
        $DEP = 36120000      # its departure time (what NextTime shows AFTER the arrival flag)

        # a probe with A (0 m), B (1000 m, the station under test) and C (2000 m, terminal); B's door side and margins are the parameters
        function StopProbeOf([int]$doorSide, [double]$mmin = 5.0, [double]$mmax = 5.0, [bool]$bPass = $false) {
            $p = NewProbe
            AddS $p 'A' 0
            AddS $p 'B' 1000 -pass $bPass -door $doorSide -arr $ARR -dep $DEP -mmin $mmin -mmax $mmax
            AddS $p 'C' 2000 -term $true
            $p.Step(500.0, 50.0, $T, $true)        # build the list; the target is B (index 1), the vehicle is running with the doors closed
            return $p
        }

        # ---- T14 (Legacy): an operational stop (Pass == false, DoorSide == 0) arrives with the doors NEVER opened -----------------------------------------------------------------
        Write-Host '--- T14: the operational stop'
        $p = StopProbeOf 0
        $before = $p.NextTime
        $p.Step(1000.0, 0.0, $T + 1000, $true)
        Check 'T14' 'REQUIREMENT-BACKED' 'an operational stop (DoorSide 0) stopped inside the range with the doors closed shows the DEPARTURE time at once (the sender counts it as arrived); the target stays B' (($before -eq $ARR) -and ($p.NextTime -eq $DEP) -and ($p.Target -eq 1))
        $p = StopProbeOf 1
        $p.Step(1000.0, 0.0, $T + 1000, $true)
        Check 'T13' 'REQUIREMENT-BACKED' 'a normal stop (DoorSide 1) stopped inside the range with the doors CLOSED is not an arrival: NextTime stays the ARRIVAL time' (($p.NextTime -eq $ARR) -and ($p.Target -eq 1))
        $p.Step(1000.0, 0.0, $T + 2000, $false)
        Check 'T13' 'REQUIREMENT-BACKED' 'the same normal stop with the doors OPEN is the arrival: NextTime shows the departure time while they are open' (($p.NextTime -eq $DEP) -and ($p.Target -eq 1))
        $p.Step(1000.0, 0.0, $T + 3000, $true)
        Check 'T13' 'CURRENT-BEHAVIOR-ONLY' 'the target advances when the doors are all closed again (B -> C, index 2)' (($p.Target -eq 2) -and ($p.Name -eq 'C'))

        # the speed threshold: |speed| < 0.1 km/h is stopped (strictly below)
        $r = @()
        foreach ($v in @(0.0, 0.05, 0.099, 0.1, 0.101, -0.05, -0.1)) {
            $q = StopProbeOf 0
            $q.Step(1000.0, $v, $T + 1000, $true)
            $r += , @($v, ($q.NextTime -eq $DEP))
        }
        $expect = @($true, $true, $true, $false, $false, $true, $false)
        $okSpeed = $true; for ($i = 0; $i -lt $r.Count; $i++) { if ($r[$i][1] -ne $expect[$i]) { $okSpeed = $false } }
        Check 'T14' 'CROSS-LAYER-DIFFERENCE' 'the sender calls |speed| < 0.1 km/h stopped (0.099 and -0.05 arrive, 0.1 and -0.1 do not); Python calls only exactly 0.0 stopped (see the Python file)' $okSpeed

        # ---- T17 (Legacy): the author-defined range: -MarginMax <= (station - location) <= |MarginMin|, both bounds inclusive ---------------------------------------------------
        Write-Host '--- T17: the author-defined range'
        function Arrives([int]$door, [double]$loc, [double]$mmin, [double]$mmax) {
            $q = StopProbeOf $door $mmin $mmax
            $q.Step($loc, 0.0, $T + 1000, $true)
            return ($q.NextTime -eq $DEP)
        }
        $okRange = (Arrives 0 995.0 5.0 5.0) -and (-not (Arrives 0 994.99 5.0 5.0)) -and (Arrives 0 1005.0 5.0 5.0) -and (-not (Arrives 0 1005.01 5.0 5.0))
        Check 'T17' 'REQUIREMENT-BACKED' 'with 5 m / 5 m the operational stop arrives at exactly 5.0 m short and 5.0 m past and not at 5.01 m (both bounds inclusive)' $okRange
        $okSides = (Arrives 0 996.0 4.0 9.0) -and (-not (Arrives 0 995.9 4.0 9.0)) -and (Arrives 0 1009.0 4.0 9.0) -and (-not (Arrives 0 1009.1 4.0 9.0))
        Check 'T17' 'REQUIREMENT-BACKED' 'MarginMin is the SHORT side and MarginMax the PAST side: with 4 m / 9 m it arrives 4.0 m short and 9.0 m past, not 4.1 m short or 9.1 m past' $okSides
        $okAbs = (Arrives 0 996.0 -4.0 9.0) -and (-not (Arrives 0 995.9 -4.0 9.0))
        Check 'T17' 'REQUIREMENT-BACKED' 'a NEGATIVE MarginMin is used as its absolute value (-4 m behaves as 4 m)' $okAbs
        $q = StopProbeOf 0 -3.5 4.25
        $q.Step(1000.0, 0.0, $T + 1000, $true)
        Check 'T17' 'REQUIREMENT-BACKED' 'MARGINB is |MarginMin| and MARGINF is MarginMax of the TARGET station (3.5 / 4.25 for -3.5 / 4.25)' ((Near $q.MarginBack 3.5) -and (Near $q.MarginFront 4.25))
        $q = StopProbeOf 0 2.0 2.0
        $q.Step(1000.0, 0.0, $T + 1000, $true)
        $q.Step(1000.0, 0.0, $DEP, $true)
        $q.Step(1000.0, 0.0, $DEP + 300, $true)
        Check 'T17' 'CURRENT-BEHAVIOR-ONLY' 'on the Tick of a station change every value (here the range) is derived from the NEW target: after B (2 m / 2 m) -> C the Tick carries C''s 5 m / 5 m (the source of F-ST-1 on the Python side)' (($q.Target -eq 2) -and (Near $q.MarginBack 5.0) -and (Near $q.MarginFront 5.0) -and ($q.Name -eq 'C'))

        # ---- the operational stop leaves the station by the TIMETABLE (departure time + 300 ms), not by the real departure ----------------------------------------------------
        Write-Host '--- T14: when the operational stop leaves the target'
        $q = StopProbeOf 0
        $q.Step(1000.0, 0.0, $T + 1000, $true)                       # arrived (the flag is set)
        $q.Step(1000.0, 0.0, $DEP - 1, $true)
        $beforeDep = $q.Target
        $q.Step(1000.0, 0.0, $DEP, $true)                            # the departure time is reached: the 300 ms hold starts
        $q.Step(1000.0, 0.0, $DEP + 299, $true)
        $at299 = $q.Target
        $q.Step(1000.0, 0.0, $DEP + 300, $true)                      # 300 ms later (>=)
        Check 'T14' 'CURRENT-BEHAVIOR-ONLY' 'the target stays B before the departure time, at the departure time and 299 ms after it, and advances to C at +300 ms - with the vehicle STILL standing at speed 0 (no real departure is awaited)' (($beforeDep -eq 1) -and ($at299 -eq 1) -and ($q.Target -eq 2))
        $q = StopProbeOf 0
        $q.Step(1000.0, 0.0, $T + 1000, $true)
        $q.Step(1000.0, 0.0, $DEP, $true)
        $q.Step(1000.0, 5.0, $DEP + 100, $true)                      # the vehicle moves: it is no longer stopped, but the flag stays set
        $q.Step(1000.0, 0.0, $DEP + 300, $true)
        Check 'T14' 'CURRENT-BEHAVIOR-ONLY' 'the hold is not cancelled by the vehicle moving: the arrival flag stays set, the 300 ms count runs on the clock only' ($q.Target -eq 2)

        # ---- T15 (Legacy): a pass station advances by POSITION only ---------------------------------------------------------------------------------------------------------------
        Write-Host '--- T15: the pass station'
        $p = StopProbeOf 1 5.0 5.0 $true
        $p.Step(1000.0, 60.0, $T + 1000, $true)
        $atStation = $p.Target
        $isPassValue = $p.IsPass
        $p.Step(1000.001, 60.0, $T + 2000, $true)
        Check 'T15' 'REQUIREMENT-BACKED' 'a pass station (Pass) keeps the target while location <= its position (ISPASS 1) and advances to the next station once location > its position' (($atStation -eq 1) -and ($isPassValue -eq 1) -and ($p.Target -eq 2))
        $p = StopProbeOf 1 5.0 5.0 $true
        $p.Step(1000.0, 0.0, $T + 1000, $false)
        $p.Step(1000.0, 0.0, $T + 2000, $true)
        Check 'T15' 'CURRENT-BEHAVIOR-ONLY' 'a pass station never reacts to the doors or to a stop: opening and closing the doors while standing on it leaves the target on the pass station' (($p.Target -eq 1) -and ($p.NextTime -eq $ARR))
        $p = StopProbeOf 0 5.0 5.0 $true
        $p.Step(1000.0, 0.0, $T + 1000, $true)
        Check 'T15' 'CURRENT-BEHAVIOR-ONLY' 'Pass wins over DoorSide: a pass station with DoorSide 0 stopped inside the range is NOT an operational stop (NextTime stays the arrival time)' (($p.NextTime -eq $ARR) -and ($p.Target -eq 1) -and ($p.IsPass -eq 1))

        # ---- the values the sender states about the target (items 5, 6, 17) -----------------------------------------------------------------------------------------------------------------
        Write-Host '--- the stop kind and the terminal flag of the target'
        $p = StopProbeOf 0
        Check 'T14' 'REQUIREMENT-BACKED' 'DOORDIR is the DoorSide of the target (0 for the operational stop) and ISPASS is the Pass of the target' (($p.DoorDir -eq 0) -and ($p.IsPass -eq 0) -and ($p.Name -eq 'B'))
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000 -door 1 -arr $ARR -dep $DEP; AddS $p 'C' 2000 -term $true -door 1
        $p.Step(1900.0, 0.0, $T, $true)
        Check 'T14' 'CROSS-LAYER-DIFFERENCE' 'TERM is the terminal flag the Legacy API STATES (Station.IsTerminal), taken as it is; Current derives it from a departure-time sentinel (pinned in the Python source-pin file)' (($p.Term -eq 1) -and ($p.Name -eq 'C') -and ($p.Target -eq 2))
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000 -door 1 -arr $ARR -dep $DEP; AddS $p 'C' 2000 -door 1
        $p.Step(1900.0, 0.0, $T, $true)
        Check 'T14' 'CURRENT-BEHAVIOR-ONLY' 'when no station is stated terminal the LAST station is made terminal (TERM 1); the Current sender fills in the last station the same way (pinned in the Python source-pin file), so this rule is common' (($p.Term -eq 1) -and ($p.Name -eq 'C'))
    }
} finally {
    $leftover = $false
    if (Test-Path -LiteralPath $work) { try { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction Stop } catch { $leftover = $true } }
    if ($leftover -or (Test-Path -LiteralPath $work)) { $script:fail++; Write-Host 'FAIL TEMP the temporary folder of this run could not be removed' }
    else { $script:pass++; Write-Host 'PASS TEMP the temporary folder of this run was removed (nothing left behind)' }
}

Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($exitCode -ne 0) { exit $exitCode }
if ($script:fail -gt 0) { Write-Host 'ST-0 Legacy stop characterization: FAILED'; exit 1 }
Write-Host 'ST-0 Legacy stop characterization checks passed.'
exit 0
