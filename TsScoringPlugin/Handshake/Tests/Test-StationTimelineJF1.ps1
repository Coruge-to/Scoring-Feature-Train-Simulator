# PHASE JF-1 (file F4) - CHARACTERIZATION of the Legacy station timeline (LegacyStationTimeline: the next-station state machine and the STALIST of the AtsEX LEGACY
# telemetry sender) - JF-0 v2 group C, Legacy side (C01-C05, C14, C15, C17), the same-position A/B pair, the 50 m and 100 m boundaries, the end of the station list, the STALIST
# fill-in (F-23) and the order of the list (F-14). It pins what the DLL does TODAY and nothing else.
#
# THE NAMES MEAN (JF-0 v2 test specification, section 0.2):
#   CURRENT         today's neutral behaviour
#   CURRENT_DANGER  a behaviour that exists today and is KNOWN to be dangerous. Passing it does NOT mean it is safe or an approved contract. Each carries four facts, printed
#                   with the check: the JF-0 v2 id, what is dangerous, the phase that turns it into its TARGET, and when the check is reversed or deleted.
#   TARGET          the future contract. They are listed as SKIP lines, with the contract id; a skip is never counted as a pass.
#   MANUAL          needs the real BVE (L-9: whether Current's station build equals this build). Listed as SKIP; no expectation is recorded.
# The Current side of the same cases (Class1.cs cannot run offline) is pinned by SOURCE SHAPE in tests\test_jf1_current_csharp_source_pins.py. Where Legacy and Current differ
# (F-15: Legacy sets the target index to Count when no station is in range, Current leaves it unchanged) the check message says so.
#
# HOW: the BUILT Legacy telemetry DLL (Telemetry\Legacy\out\...dll) is loaded from memory and driven through a tiny public fixture class that is compiled here from a here-string
# (no .cs file exists for it). The DLL grants its internals to an assembly named TsScoringLegacyTelemetryTests, which is the name given to the fixture assembly. No BVE, no AtsEX
# runtime, no BveEX, no network, no hook, no process. The only thing written is a temporary folder under the user TEMP (unique name), removed in a finally block; a leftover
# is a failure of this script.
#
# INCONCLUSIVE (exit 2, never a pass): the DLL is missing, or its SHA-256, or the SHA-256 of src\LegacyStationTimeline.cs, is not the audited one below (the checks would then
# describe another build than the one JF-1 audited); or the fixture can not be compiled / loaded.
# Exit codes: 0 = every check passed, 1 = a check failed, 2 = INCONCLUSIVE.
# This script is ASCII-only on purpose and runs on Windows PowerShell 5.1.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$AuditedDllSha256 = '43E7B9D35F840FAEF0DFCBEC8F2EDB66F259F42FA9CD62644B1DFD1A45EDF691'      # Legacy telemetry 0.6.0.0 DEFAULT build (flag OFF) of Phase LJX-1 (pin moved from 08CE368C..., the 2A-alpha build): the checks were run again against it; the station timeline source is unchanged
$AuditedTimelineSourceSha256 = '23ABFA293D0D15D0978562873B383C85F0C7B81630871B7EDFE3AB61ED437BAE'

$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$srcPath = Join-Path $Root 'Telemetry\Legacy\src\LegacyStationTimeline.cs'

$script:pass = 0
$script:fail = 0
$script:skip = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function CheckDanger([string]$id, [string]$what, [string]$phase, [string]$flip, [string]$name, [bool]$ok) {
    $complete = ($what.Length -ge 21) -and ($phase.Length -ge 8) -and ($flip.Length -ge 21)
    Write-Host ('  [CURRENT_DANGER ' + $id + '] danger: ' + $what)
    Write-Host ('  [CURRENT_DANGER ' + $id + '] becomes TARGET in: ' + $phase)
    Write-Host ('  [CURRENT_DANGER ' + $id + '] reversed or deleted when: ' + $flip)
    Check ('CURRENT_DANGER ' + $id + ' ' + $name) ($ok -and $complete)
}
function Skip([string]$kind, [string]$text) { $script:skip++; Write-Host ('SKIP ' + $kind + ' ' + $text) }
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

public sealed class TimelineProbe
{
    private LegacyStationTimeline t = new LegacyStationTimeline();
    private List<LegacyStationRaw> raw = new List<LegacyStationRaw>();
    private StationValues last;

    public void Add(string name, double loc, bool pass, bool terminal, int doorSide, int arrMs, int depMs, int stopMs)
    {
        LegacyStationRaw r = new LegacyStationRaw();
        r.Name = name; r.Location = loc; r.Pass = pass; r.IsTerminal = terminal; r.DoorSide = doorSide;
        r.ArrivalMs = arrMs; r.DepartureMs = depMs; r.DefaultMs = -1; r.StoppageMs = stopMs; r.MarginMin = 5.0; r.MarginMax = 5.0;
        raw.Add(r);
    }
    public void Step(double location, double speedKmh, int timeMs, bool doorsClosed)
    {
        last = t.Step(raw, raw.Count, location, speedKmh, timeMs, doorsClosed);
    }
    public void Reset() { t.Reset(); }
    public void MarkDiscontinuity() { t.MarkDiscontinuity(); }
    public void ReplaceRaw() { raw = new List<LegacyStationRaw>(); }
    public int Target { get { return t.TargetIndex; } }
    public int Count { get { return t.Count; } }
    public bool Initialized { get { return t.IsInitialized; } }
    public double NextLoc { get { return last.NextLoc; } }
    public int NextTime { get { return last.NextTime; } }
    public string Name { get { return last.Name; } }
    public string StaList() { return t.ComposeStaList(); }
}

public static class Jf1Resolver
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

$work = Join-Path $env:TEMP ('ts-jf1-f4-' + [guid]::NewGuid().ToString('N'))
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
        # the resolver lives in the fixture assembly itself; it hands the already loaded (from memory) telemetry assembly to the binder
        $fixAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($fixtureDll))
        $resolver = $fixAsm.GetType('Jf1Resolver')
        $resolver.GetField('Telemetry').SetValue($null, $telAsm)
        $resolver.GetMethod('Install').Invoke($null, @())
        $probeType = $fixAsm.GetType('TimelineProbe')
        if ($null -eq $probeType) { Write-Host 'INCONCLUSIVE the fixture type is not visible'; $exitCode = 2 }
    }
    if ($exitCode -eq 0) {
        function NewProbe { return [Activator]::CreateInstance($probeType) }
        function AddS($p, [string]$n, [double]$loc, [bool]$pass = $false, [bool]$term = $false, [int]$door = 1, [int]$arr = -1, [int]$dep = -1, [int]$stop = 15000) {
            $p.Add($n, $loc, $pass, $term, $door, $arr, $dep, $stop)
        }
        function Near([double]$a, [double]$b) { return ([math]::Abs($a - $b) -lt 1e-9) }
        # the STALIST as a list of field arrays: name, scoring, location, arrival, departure, default, stoppage, pass, terminal
        function StaFields($p) {
            $text = $p.StaList()
            $items = $text.Substring('STALIST:'.Length).Split(',')
            $out = @()
            foreach ($i in $items) { $out += , ($i.Split('=')) }
            return , $out
        }
        $T = 36000000

        # ---- C01 / C02 / C03 / C17 / X06 : which station is the target after the list is built or the time jumped --------------------------------------------------------
        Write-Host '--- C: target selection (the Legacy side of the same table as Class1.cs)'
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000; AddS $p 'C' 2000 -term $true
        $p.Step(900.0, 0.0, $T, $true)
        Check 'CURRENT C01 a single station ahead at 900 m: the target is B (index 1) and A, 900 m behind, is skipped' (($p.Target -eq 1) -and ($p.Name -eq 'B') -and (Near $p.NextLoc 1000.0) -and ($p.Count -eq 3))

        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B1' 1000; AddS $p 'B2' 1000; AddS $p 'C' 3000 -term $true
        $p.Step(1000.0, 0.0, $T, $true)
        CheckDanger 'C02' 'at the SAME position the first of two stations (B1) is the target and B2 can never be selected by position: a jump meant for B2 ends with B1 as the target' 'JF-2 (TARGET-A V-4: refused in advance) / JF-3 (TARGET-B B2: the requested index is kept)' 'the requested index is the target; this check is replaced by the TARGET-B C02 check' 'the target is B1 (index 1), name B1, although B2 has the same location' (($p.Target -eq 1) -and ($p.Name -eq 'B1'))

        $p = NewProbe; AddS $p 'A' 0; AddS $p 'P' 950; AddS $p 'Q' 1000; AddS $p 'E' 3000 -term $true
        $p.Step(1000.0, 0.0, $T, $true)
        $atBoundary = $p.Target
        $p2 = NewProbe; AddS $p2 'A' 0; AddS $p2 'P' 949.99; AddS $p2 'Q' 1000; AddS $p2 'E' 3000 -term $true
        $p2.Step(1000.0, 0.0, $T, $true)
        CheckDanger 'C03' 'a station exactly 50 m behind the position is still in range (>=), so it becomes the target instead of the station the jump was meant for' 'JF-2 (TARGET-A V-4 extended: refused in advance, boundary included) / JF-3 (TARGET-B B2)' 'the requested index is the target; this check is replaced by the TARGET-B C03 check' 'P at 950.0 is the target (index 1), P at 949.99 is not (the target is Q, index 2)' (($atBoundary -eq 1) -and ($p2.Target -eq 2))

        $p = NewProbe; AddS $p 'A' 0; AddS $p 'P' 960; AddS $p 'Q' 1000; AddS $p 'E' 3000 -term $true
        $p.Step(1000.0, 0.0, $T, $true)
        CheckDanger 'C17' 'a station 40 m behind (not at the same position) also wins: the later station Q, the one meant, is not the target while P is within 50 m' 'JF-2 (TARGET-A V-4 extended) / JF-3 (TARGET-B B2)' 'the requested index is the target; this check is replaced by the TARGET-B C17 check' 'the target is P (index 1), 960 m, although the position is Q (1000 m)' (($p.Target -eq 1) -and ($p.Name -eq 'P') -and (Near $p.NextLoc 960.0))

        # X06 (Legacy half): after a time discontinuity the target is chosen again from the position, whatever was requested
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'P' 960; AddS $p 'Q' 1000; AddS $p 'E' 3000 -term $true
        $p.Step(100.0, 0.0, $T, $true)
        $p.MarkDiscontinuity()
        $p.Step(1000.0, 0.0, $T + 60000, $true)
        CheckDanger 'X06' 'after a jump to Q the timeline picks its target again by position (MarkDiscontinuity -> SelectTarget) and the choice is P: nothing in the Python completion check can see it' 'JF-2 (TARGET-A V-4) / JF-3 (TARGET-B B2, B3 / K7)' 'the sender keeps the requested index and reports the next index; this check is replaced' 'the target after the discontinuity at 1000 m is P (index 1)' (($p.Target -eq 1) -and ($p.Name -eq 'P'))

        # ---- C04 : the 100 m door-open detection and the initial 50 m ------------------------------------------------------------------------------------------------------
        Write-Host '--- C04: door detection distances'
        function DoorCase([double]$openLoc) {
            $q = NewProbe; AddS $q 'A' 0; AddS $q 'B' 1000; AddS $q 'C' 2000 -term $true
            $q.Step(500.0, 0.0, $T, $true)               # build + select: the target is B (index 1)
            $q.Step($openLoc, 0.0, $T + 1000, $false)    # doors open at this position
            $q.Step($openLoc, 0.0, $T + 9000, $true)     # doors closed again
            return $q.Target
        }
        Check 'CURRENT C04 doors opened 99.999 m before the target station, then closed: the target advances to C (index 2)' ((DoorCase 900.001) -eq 2)
        Check 'CURRENT C04 doors opened exactly 100.0 m before the target station, then closed: the target stays B (index 1) - the distance is strictly below 100' ((DoorCase 900.0) -eq 1)
        $q = NewProbe; AddS $q 'A' 0; AddS $q 'B' 1000; AddS $q 'C' 2000 -term $true
        $q.Step(960.0, 0.0, $T, $false)
        $q.Step(960.0, 0.0, $T + 1000, $true)
        $q2 = NewProbe; AddS $q2 'A' 0; AddS $q2 'B' 1000; AddS $q2 'C' 2000 -term $true
        $q2.Step(949.999, 0.0, $T, $false)
        $q2.Step(949.999, 0.0, $T + 1000, $true)
        Check 'CURRENT C04 built with the doors open 40 m and 50.001 m before B the door counts as opened in BOTH cases (closing advances to C): the 50 m of the initial state is not visible from outside, because the 100 m rule runs in the same Step. (The 50 m literal itself is pinned in test_jf1_current_csharp_source_pins.py and in the Legacy source)' (($q.Target -eq 2) -and ($q2.Target -eq 2))

        # ---- C05 : the end of the list --------------------------------------------------------------------------------------------------------------------------------------
        Write-Host '--- C05: the end of the station list'
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000 -term $true
        $p.Step(1051.0, 0.0, $T, $true)
        Check 'CURRENT C05 no station within 50 m behind the position: the target index is the Count (2), NEXTLOC and NEXTTIME are -1 and the name is empty. (Current, by contrast, leaves its target index UNCHANGED: F-15, pinned in test_jf1_current_csharp_source_pins.py)' (($p.Target -eq 2) -and ($p.Count -eq 2) -and ($p.NextLoc -eq -1) -and ($p.NextTime -eq -1) -and ($null -eq $p.Name))
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000 -term $true
        $p.Step(1050.0, 0.0, $T, $true)
        Check 'CURRENT C05 exactly 50 m past the last station it is still the target (the range is inclusive)' (($p.Target -eq 1) -and ($p.Name -eq 'B'))
        $p = NewProbe
        $p.Step(100.0, 0.0, $T, $true)
        Check 'CURRENT C05 an empty list is a real answer: Count 0, target 0 = Count, NEXTLOC -1, no STALIST (null)' (($p.Count -eq 0) -and ($p.Target -eq 0) -and ($p.NextLoc -eq -1) -and ($null -eq $p.StaList()))

        # ---- C14 / C15 : Reset and MarkDiscontinuity ---------------------------------------------------------------------------------------------------------------------------
        Write-Host '--- C14 / C15: Reset and MarkDiscontinuity'
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000; AddS $p 'C' 2000 -term $true
        $p.Step(100.0, 0.0, $T, $true)
        $before = $p.Target
        $p.MarkDiscontinuity()
        $uninit = (-not $p.Initialized)
        $keptList = ($p.Count -eq 3)
        $p.Step(1900.0, 0.0, $T + 600000, $true)
        Check 'CURRENT C14 MarkDiscontinuity keeps the list, clears the initialised flag and the next Step chooses the target again from the new position (B -> C)' (($before -eq 1) -and $uninit -and $keptList -and ($p.Target -eq 2) -and $p.Initialized)
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000; AddS $p 'C' 2000; AddS $p 'D' 3000 -term $true
        $p.Step(2900.0, 0.0, $T, $true)
        $stale = $p.Target
        $p.Reset()
        $resetOk = ($p.Count -eq 0) -and ($p.Target -eq 0) -and (-not $p.Initialized)
        $p.ReplaceRaw(); AddS $p 'X' 0; AddS $p 'Y' 500 -term $true
        $p.Step(5000.0, 0.0, $T, $true)
        Check 'CURRENT C15 (Legacy side) no stale target after a scenario change: before the Reset the target was 3, after Reset + a new 2-station list at 5000 m it is the Count (2), never the stale 3. (Current keeps its old index across a scenario change: F-27 / C15, pinned as CURRENT_DANGER in test_jf1_current_csharp_source_pins.py)' (($stale -eq 3) -and $resetOk -and ($p.Target -eq 2) -and ($p.Count -eq 2))
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000; AddS $p 'C' 2000 -term $true
        $p.Step(1900.0, 0.0, $T, $true)
        $p.ReplaceRaw(); AddS $p 'A' 0; AddS $p 'B' 1000 -term $true
        $p.Step(1900.0, 0.0, $T + 1000, $true)
        Check 'CURRENT C15 a station list of another length rebuilds the timeline without a Reset and selects again (target = Count of the new list when none is in range)' (($p.Count -eq 2) -and ($p.Target -eq 2))

        # ---- the order of the list and the same-position pair -------------------------------------------------------------------------------------------------------------
        Write-Host '--- F-14: the STALIST order is the list order, also for a same-position pair'
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B1' 1000; AddS $p 'B2' 1000; AddS $p 'C' 3000 -term $true
        $p.Step(500.0, 0.0, $T, $true)
        $f = StaFields $p
        $names = @($f | ForEach-Object { $_[0] })
        Check 'CURRENT F14 the STALIST names are in the order of the station list (A, B1, B2, C) and a same-position pair keeps both entries with the same location' ((($names -join ',') -eq 'A,B1,B2,C') -and ($f[1][2] -eq $f[2][2]) -and ($f[1][2] -eq '1000') -and ($f.Count -eq 4))

        # ---- F-23 : the fill-in of the STALIST (Legacy side of L-9) ------------------------------------------------------------------------------------------------------------
        Write-Host '--- F-23: the STALIST fill-in (the original blanks are not recoverable from it)'
        $p = NewProbe
        AddS $p 'A' 0
        AddS $p 'B' 1000 -arr 36060000 -dep -1 -stop 20000
        AddS $p 'C' 2000 -arr 36200000 -dep 36250000 -term $true
        $p.Step(500.0, 0.0, $T, $true)
        $f = StaFields $p
        Check 'CURRENT F23 arrival only (B): the departure is filled in as arrival + stop time (36060000 + 20000 = 36080000)' (($f[1][3] -eq '36060000') -and ($f[1][4] -eq '36080000') -and ($f[1][6] -eq '20000') -and ($f[1][1] -eq '1'))
        Check 'CURRENT F23 a terminal station ignores a departure time: the departure field is -1 and the terminal flag is 1' (($f[2][4] -eq '-1') -and ($f[2][8] -eq '1') -and ($f[2][3] -eq '36200000'))
        Check 'CURRENT F23 the first station is never a timing station (field 1 is 0) and has no times' (($f[0][1] -eq '0') -and ($f[0][3] -eq '-1') -and ($f[0][4] -eq '-1'))
        $p = NewProbe
        AddS $p 'A' 0
        AddS $p 'B' 1000 -arr -1 -dep 36100000 -stop 20000
        AddS $p 'C' 2000 -arr -1 -dep 10000 -stop 20000
        AddS $p 'D' 3000 -arr 36300000 -term $true
        $p.Step(500.0, 0.0, $T, $true)
        $f = StaFields $p
        Check 'CURRENT F23 departure only (B): the arrival is filled in as departure - stop time (36100000 - 20000 = 36080000)' (($f[1][3] -eq '36080000') -and ($f[1][4] -eq '36100000'))
        Check 'CURRENT F23 departure only with a stop time longer than the departure (C): the arrival is clamped to 0, not negative' (($f[2][3] -eq '0') -and ($f[2][4] -eq '10000'))
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000; AddS $p 'C' 2000
        $p.Step(500.0, 0.0, $T, $true)
        $f = StaFields $p
        Check 'CURRENT F23 no terminal stated: only the LAST station becomes the terminal' (($f[0][8] -eq '0') -and ($f[1][8] -eq '0') -and ($f[2][8] -eq '1'))
        $p = NewProbe; AddS $p 'A' 0; AddS $p 'B' 1000 -term $true; AddS $p 'C' 2000 -term $true
        $p.Step(500.0, 0.0, $T, $true)
        $f = StaFields $p
        Check 'CURRENT F23 several terminals stated: only the FIRST one stays the terminal' (($f[1][8] -eq '1') -and ($f[2][8] -eq '0'))

        # ---- what is NOT claimed ------------------------------------------------------------------------------------------------------------------------------------------------
        Write-Host '--- TARGET and MANUAL (not run, not counted as passes)'
        Skip 'TARGET-B' 'B2 (JF-3) C02 / C03 / C17: after a jump to the requested index the target is that index, not the first station in range'
        Skip 'TARGET-B' 'B6 (JF-3) C05 / C15: the "no next station" value and the scenario-change reset are the same on Current and Legacy (NEXTIDX = -1 convention, U-8)'
        Skip 'TARGET-B' 'S3 (JF-3) NEXTIDX: the timeline target index (TargetIndex, already exposed internally) is delivered as the authoritative station index'
        Skip 'MANUAL' 'L-9 requires BVE observation: whether the Current station build (Class1.cs) equals this build for the same input; only this Legacy side is run here'
    }
} finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
}

$left = Test-Path -LiteralPath $work
Check 'TEMP the temporary folder of this run was removed (nothing left behind)' (-not $left)
Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail + ' SKIP(not counted)=' + $script:skip)
if ($exitCode -eq 2) { Write-Host 'INCONCLUSIVE'; exit 2 }
if ($script:fail -ne 0) { exit 1 }
Write-Host 'JF-1 station timeline (Legacy) checks passed.'
exit 0
