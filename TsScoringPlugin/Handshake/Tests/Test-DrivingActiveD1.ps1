# PHASE D1 - offline tests of the DrivingActive state of the Caller (Caller 0.8.0.0).
# DrivingActive = Enabled AND not disposed AND ScenarioReady published AND TickFresh AND a Tick seen AFTER the ScenarioReady publication was first seen.
# ON at a Tick age <= 250 ms, soft OFF only above 2000 ms, hard OFF at once (Dispose, disabled, ScenarioReady withdrawn).
# No BVE, no BveEX, no Python, no UDP, no hooks, no MessageBox (a notice test double is used), no Process.Start (except the optional 32-bit
# PowerShell probe that runs THIS script again). The DLLs are loaded from memory. Every log goes to a private file under logs\d1-tests (never to
# the fixed Downloads file). Fake process ids are used; the only side effects are named kernel objects of this PowerShell process, released at the end.
# Sessions that are driven by hand (Step) have no monitor thread, so every ordering below is deterministic. This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Baseline = '4c5dad48cbf90d5593e6f6e27f4b8d66e1b4a719',
    [switch]$Probe32
)

Add-Type -TypeDefinition @'
public class NoticeRecorder
{
    public int Count;
    public string Last;
    public void Show(string text)
    {
        System.Threading.Interlocked.Increment(ref Count);
        Last = text;
    }
}

public static class TickHammer
{
    // microseconds for n calls of the action (real .NET loop, no PowerShell overhead)
    public static long Run(System.Action a, int n)
    {
        System.Diagnostics.Stopwatch sw = System.Diagnostics.Stopwatch.StartNew();
        for (int i = 0; i < n; i++) { a(); }
        return sw.ElapsedTicks * 1000000L / System.Diagnostics.Stopwatch.Frequency;
    }
}

public class TickPump
{
    // several real threads calling the action n times each (the Tick of BVE against the monitor thread)
    private readonly System.Threading.Thread[] threads;
    public TickPump(System.Action a, int n, int count)
    {
        threads = new System.Threading.Thread[count];
        for (int i = 0; i < count; i++)
        {
            threads[i] = new System.Threading.Thread(() => { for (int k = 0; k < n; k++) { a(); } });
            threads[i].IsBackground = true;
        }
    }
    public void Start() { foreach (System.Threading.Thread t in threads) { t.Start(); } }
    public bool Done { get { foreach (System.Threading.Thread t in threads) { if (t.IsAlive) { return false; } } return true; } }
}
'@

$handler = [ResolveEventHandler]{
    param($s, $e)
    $name = ($e.Name -split ',')[0]
    foreach ($dir in @((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), (Join-Path $env:PUBLIC 'Documents\BveEx\2.0'))) {
        foreach ($ext in '.dll', '.DLL') {
            $p = Join-Path $dir ($name + $ext)
            if (Test-Path $p) { return [Reflection.Assembly]::LoadFrom($p) }
        }
    }
    return $null
}
[AppDomain]::CurrentDomain.add_AssemblyResolve($handler)

$callerPath = Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll'
$callerBytes = [IO.File]::ReadAllBytes($callerPath)
$callerAsm = [Reflection.Assembly]::Load($callerBytes)
$NS = 'TSScoringPlugin.Handshake.'
$sessT = $callerAsm.GetType($NS + 'HandshakeSession')
$stateT = $callerAsm.GetType($NS + 'DrivingActivityState')
$appT = $callerAsm.GetType($NS + 'AppProtocol')
$ssT = $callerAsm.GetType($NS + 'ScenarioState')
$logT = $callerAsm.GetType($NS + 'ObservationLog')
$phaseT = $callerAsm.GetType($NS + 'CallerPhase')
$deviceT = $callerAsm.GetType($NS + 'TsScoringCallerInputDevice')
$npi = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$nps = [Reflection.BindingFlags]'NonPublic,Public,Static'

$logDir = Join-Path $Root 'logs\d1-tests'
if (-not $Probe32) {
    if (Test-Path $logDir) { Remove-Item $logDir -Recurse -Force }
}
New-Item -ItemType Directory -Force $logDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

# ---------------------------------------------------------------- helpers
function SetLog([string]$file, [int]$fakePid, [long]$maxBytes = 0) {
    $logT.GetMethod('ResetForTests', $nps).Invoke($null, @()) | Out-Null
    $p = Join-Path $logDir $file
    if (Test-Path $p) { Remove-Item $p -Force }
    $logT.GetProperty('TestPath', $nps).SetValue($null, $p)
    $logT.GetProperty('TestPid', $nps).SetValue($null, $fakePid)
    $logT.GetProperty('TestMaxBytes', $nps).SetValue($null, $maxBytes)
    return $p
}
function Lines([string]$p) { if (Test-Path $p) { return @(Get-Content $p -Encoding UTF8) } else { return @() } }
function EventLines([string]$p, [string]$evt) { return @(Lines $p | Where-Object { $_ -match (' ' + [regex]::Escape($evt) + ' ') }) }

# the pure state machine
function NewMachine { return [Activator]::CreateInstance($stateT) }
function Ev($m, [bool]$en, [bool]$nd, [bool]$srp, [long]$seq, [double]$age, [int]$gen = 1) {
    $st = $stateT.GetMethod('Evaluate').Invoke($m, @($en, $nd, $srp, $gen, $seq, $age))
    $t = $st.GetType()
    return [pscustomobject]@{
        Active = [bool]$t.GetField('Active').GetValue($st)
        Changed = [bool]$t.GetField('Changed').GetValue($st)
        Reason = ([string]$t.GetField('OffReason').GetValue($st))
    }
}
function MActive($m) { return [bool]$stateT.GetProperty('Active').GetValue($m) }
function MArmed($m) { return [bool]$stateT.GetProperty('Armed').GetValue($m) }
function MArmSeq($m) { return [long]$stateT.GetProperty('ArmSequence').GetValue($m) }

# sessions driven by hand: no Start, no monitor thread. Step() is the monitor's step, called on this thread.
$sessionCtor = $sessT.GetConstructor($npi, $null, [Type[]]@([int], [Action[string]]), $null)
$stepM = $sessT.GetMethod('Step', $npi)
$allPids = New-Object System.Collections.Generic.List[int]
$liveSessions = New-Object System.Collections.Generic.List[object]
$cycleNo = 100
function NewSession([int]$fakePid, [bool]$manual = $true) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    $s = $sessionCtor.Invoke(@($fakePid, $del))
    $liveSessions.Add($s)
    $h = [pscustomobject]@{ Session = $s; Recorder = $rec; Pid = $fakePid }
    if ($manual) {
        $script:cycleNo++
        $now = [long][Diagnostics.Stopwatch]::GetTimestamp()
        $sessT.GetField('started', $npi).SetValue($s, $true)
        $sessT.GetField('phase', $npi).SetValue($s, [Enum]::Parse($phaseT, 'WaitingForBridge'))
        $sessT.GetField('enabledQpc', $npi).SetValue($s, $now)
        $sessT.GetField('absenceStartQpc', $npi).SetValue($s, $now)
        $sessT.GetField('cycleNo', $npi).SetValue($s, $script:cycleNo)
    }
    return $h
}
function StartS($h) { $sessT.GetMethod('Start').Invoke($h.Session, @()) | Out-Null }
function EndS($h) { try { $sessT.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { } }
function TickS($h) { $sessT.GetMethod('NotifyTick').Invoke($h.Session, @()) | Out-Null }
function Step($h) { $stepM.Invoke($h.Session, @()) | Out-Null }
function SProp($h, [string]$n) { return $sessT.GetProperty($n, $npi).GetValue($h.Session) }
function Active($h) { return [bool](SProp $h 'DrivingActive') }
function Wait([int]$ms) { Start-Sleep -Milliseconds $ms }
function ObjectExists([int]$fakePid, [string]$kind) {
    $x = $null
    $ok = [Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$fakePid.$kind", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$x)
    if ($ok -and $x) { $x.Dispose() }
    return $ok
}
function Test-BytesContain([byte[]]$bytes, [string]$text) {
    $a = [Text.Encoding]::GetEncoding(28591).GetString($bytes)
    $u = [Text.Encoding]::Unicode.GetString($bytes)
    return (($a.IndexOf($text, [StringComparison]::Ordinal) -ge 0) -or ($u.IndexOf($text, [StringComparison]::Ordinal) -ge 0))
}
# keep stepping (and optionally ticking) for ms; returns nothing
function Run($h, [int]$ms, [int]$stepEvery, [int]$tickEvery) {
    $sw = [Diagnostics.Stopwatch]::StartNew(); $lastTick = -1000; $lastStep = -1000
    while ($sw.ElapsedMilliseconds -lt $ms) {
        $t = $sw.ElapsedMilliseconds
        if ($tickEvery -gt 0 -and ($t - $lastTick) -ge $tickEvery) { TickS $h; $lastTick = $t }
        if (($t - $lastStep) -ge $stepEvery) { Step $h; $lastStep = $t }
        Start-Sleep -Milliseconds 2
    }
    Step $h
}

# fake Bridge objects of one fake process (what the Bridge publishes; the Caller reads them unchanged)
function NewBridgeObjs([int]$fakePid) {
    $ev = @{}
    foreach ($k in 'BridgeAvailable', 'Ready') { $ev[$k] = New-Object Threading.EventWaitHandle($true, [Threading.EventResetMode]::ManualReset, ('Local\TSScoringPlugin.v1.' + $fakePid + '.' + $k)) }
    $ev['ScenarioReady'] = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, ('Local\TSScoringPlugin.v1.' + $fakePid + '.ScenarioReady'))
    $mmf = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew(('Local\TSScoringPlugin.v1.' + $fakePid + '.ScenarioState'), 64)
    $view = $mmf.CreateViewAccessor(0, 64)
    return [pscustomobject]@{ Pid = $fakePid; Ev = $ev; Mmf = $mmf; View = $view }
}
function SetSR($b, [int]$gen, [bool]$ready) {
    $w = $ssT.GetMethod('Write')
    if ($ready) { $w.Invoke($null, @($b.View, $b.Pid, $gen, $true)) | Out-Null; $b.Ev['ScenarioReady'].Set() | Out-Null }
    else { $b.Ev['ScenarioReady'].Reset() | Out-Null; $w.Invoke($null, @($b.View, $b.Pid, $gen, $false)) | Out-Null }
}
function DisposeBridgeObjs($b) {
    foreach ($k in @($b.Ev.Keys)) { try { $b.Ev[$k].Dispose() } catch { } }
    try { $b.View.Dispose() } catch { }
    try { $b.Mmf.Dispose() } catch { }
}

# ================================================================================================================ 32-bit probe (runs in a 32-bit PowerShell)
if ($Probe32) {
    $fakePid = 950001
    $null = SetLog 'probe32.log' $fakePid
    $b = NewBridgeObjs $fakePid
    $h = NewSession $fakePid
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $tickM = [Delegate]::CreateDelegate([Action], $h.Session, 'NotifyTick')
    $pump = New-Object TickPump -ArgumentList $tickM, 1000000, 2
    $seqP = $sessT.GetProperty('TickSequence', $npi)
    $prev = 0L; $mono = $true; $max = 0L
    $pump.Start()
    while (-not $pump.Done) { $v = [long]$seqP.GetValue($h.Session); if ($v -lt $prev) { $mono = $false }; $prev = $v; if ($v -gt $max) { $max = $v } }
    $final = [long]$seqP.GetValue($h.Session)
    SetSR $b 1 $true
    Step $h
    TickS $h
    Step $h
    $on = Active $h
    EndS $h
    DisposeBridgeObjs $b
    ('PROBE32 ptr={0} seq={1} mono={2} on={3} ms={4}' -f [IntPtr]::Size, $final, $mono, $on, $sw.ElapsedMilliseconds)
    exit 0
}

# ================================================================================================================ A: the pure state machine
Write-Host '--- A: pure state machine (no clock, no I/O, no log)'
$m = NewMachine
$r = Ev $m $true $true $false 0 -1
Check 'A01 [1] initial state is OFF' ((-not (MActive $m)) -and (-not $r.Active) -and (-not (MArmed $m)))

$m = NewMachine
$a = $true
for ($i = 1; $i -le 30; $i++) { $x = Ev $m $true $true $false $i 5; if ($x.Active) { $a = $false } }
Check 'A02 [2] Ticks only (ScenarioReady never published): OFF' $a

$m = NewMachine
$x = Ev $m $true $true $true 0 -1
$y = Ev $m $true $true $true 0 -1
Check 'A03 [3] ScenarioReady only, no Tick ever: OFF' ((-not $x.Active) -and (-not $y.Active))

$m = NewMachine
[void](Ev $m $true $true $false 7 5)
[void](Ev $m $true $true $false 8 5)
$x = Ev $m $true $true $true 8 5
Check 'A04 [4] Ticks that came BEFORE the ScenarioReady publication do not turn it ON (even at age 5 ms)' ((-not $x.Active) -and (MArmed $m))
$x = Ev $m $true $true $true 8 5
Check 'A05 [5] the Tick sequence of the first published evaluation is recorded as the arm (armSeq = 8)' ((MArmSeq $m) -eq 8)
Check 'A06 [6] the same sequence after the publication: still OFF' (-not $x.Active)
$x = Ev $m $true $true $true 9 6
Check 'A07 [7] a NEW sequence after the publication: ON (no reason, Changed)' ($x.Active -and $x.Changed -and ($x.Reason -ceq 'None'))

$m = NewMachine
[void](Ev $m $true $true $true 1 10)
$x = Ev $m $true $true $true 2 250
Check 'A08 [8] OFF state, TickAge exactly 250 ms: ON (inclusive)' $x.Active
$m = NewMachine
[void](Ev $m $true $true $true 1 10)
$x = Ev $m $true $true $true 2 251
Check 'A09 [9] OFF state, TickAge 251 ms: OFF' (-not $x.Active)

$m = NewMachine
[void](Ev $m $true $true $true 1 10); [void](Ev $m $true $true $true 2 10)
$x = Ev $m $true $true $true 2 1999
Check 'A10 [10] ON state, TickAge 1999 ms: stays ON (no change)' ($x.Active -and (-not $x.Changed))
$x = Ev $m $true $true $true 2 2000
Check 'A11 [11] ON state, TickAge exactly 2000 ms: stays ON (OFF only ABOVE 2000)' ($x.Active -and (-not $x.Changed))
$x = Ev $m $true $true $true 2 2001
Check 'A12 [12] ON state, TickAge 2001 ms: OFF, reason TickStale (soft)' ((-not $x.Active) -and $x.Changed -and ($x.Reason -ceq 'TickStale'))

$m = NewMachine
[void](Ev $m $true $true $true 1 10); [void](Ev $m $true $true $true 2 10)
$x = Ev $m $true $true $false 3 5
Check 'A13 [13] ScenarioReady withdrawn while Ticks go on: OFF at once, reason ScenarioReadyOff (hard), arm discarded' ((-not $x.Active) -and $x.Changed -and ($x.Reason -ceq 'ScenarioReadyOff') -and (-not (MArmed $m)))
$m = NewMachine
[void](Ev $m $true $true $true 1 10); [void](Ev $m $true $true $true 2 10)
$x = Ev $m $true $false $true 3 5
Check 'A14 [14] Dispose began: OFF at once, reason Dispose (hard)' ((-not $x.Active) -and ($x.Reason -ceq 'Dispose'))
$m = NewMachine
[void](Ev $m $true $true $true 1 10); [void](Ev $m $true $true $true 2 10)
$x = Ev $m $false $true $true 3 5
Check 'A15 [15] Enabled false: OFF at once, reason Disabled (hard)' ((-not $x.Active) -and ($x.Reason -ceq 'Disabled') -and (-not (MArmed $m)))
$offReasons = $callerAsm.GetType($NS + 'DrivingOffReasons')
$isHard = $offReasons.GetMethod('IsHard'); $nameM = $offReasons.GetMethod('Name'); $reasonT = $callerAsm.GetType($NS + 'DrivingOffReason')
function Hard([string]$n) { return [bool]$isHard.Invoke($null, @([Enum]::Parse($reasonT, $n))) }
Check 'A16 hard OFF reasons are dispose, disabled, scenario-ready-off; the soft one is tick-stale (names and classes)' ((Hard 'Dispose') -and (Hard 'Disabled') -and (Hard 'ScenarioReadyOff') -and (-not (Hard 'TickStale')) -and ($nameM.Invoke($null, @([Enum]::Parse($reasonT, 'ScenarioReadyOff'))) -ceq 'scenario-ready-off') -and ($nameM.Invoke($null, @([Enum]::Parse($reasonT, 'TickStale'))) -ceq 'tick-stale') -and ($nameM.Invoke($null, @([Enum]::Parse($reasonT, 'Dispose'))) -ceq 'dispose') -and ($nameM.Invoke($null, @([Enum]::Parse($reasonT, 'Disabled'))) -ceq 'disabled'))

$m = NewMachine
[void](Ev $m $true $true $true 1 10); [void](Ev $m $true $true $true 2 10)
[void](Ev $m $true $true $false 5 5)
$x = Ev $m $true $true $true 5 5
Check 'A17 [16] ScenarioReady published again but no new Tick since: OFF' (-not $x.Active)
$x = Ev $m $true $true $true 5 5
$x = Ev $m $true $true $true 6 4
Check 'A18 [17] the next new Tick after the republication: ON' ($x.Active -and $x.Changed)

# [18] / [19] cycles: a new instance has nothing (the instance is the cycle)
$m2 = NewMachine
Check 'A19 [18] a new instance (new Caller cycle) starts OFF, unarmed, with no arm sequence' ((-not (MActive $m2)) -and (-not (MArmed $m2)) -and ((MArmSeq $m2) -eq 0))
$staticFields = @($stateT.GetFields([Reflection.BindingFlags]'NonPublic,Public,Static') | Where-Object { -not $_.IsLiteral })
Check 'A20 [18] the state class has no static field (nothing can leak from one cycle to the next)' ($staticFields.Count -eq 0)

# [20] / [21] generations
$m = NewMachine
[void](Ev $m $true $true $true 10 5 1); [void](Ev $m $true $true $true 11 5 1)
$x = Ev $m $true $true $true 12 5 2
Check 'A21 [20] ScenarioGeneration changes under a still-published ScenarioReady: OFF at once (reason ScenarioReadyOff), the Tick count so far (12) becomes the new arm' ((-not $x.Active) -and $x.Changed -and ($x.Reason -ceq 'ScenarioReadyOff') -and ((MArmSeq $m) -eq 12))
$x = Ev $m $true $true $true 12 5 2
Check 'A22 [20] a Tick of the old generation (sequence not beyond the new arm) is not used' (-not $x.Active)
$x = Ev $m $true $true $true 13 5 2
Check 'A23 [21] a Tick beyond the new arm: ON again (re-armed for the new generation)' ($x.Active -and $x.Changed)

# [22] overflow
$max = [long]::MaxValue; $min = [long]::MinValue
$m = NewMachine
[void](Ev $m $true $true $true ($max - 1) 5)
$x = Ev $m $true $true $true $max 5
Check 'A24 [22] sequence at Int64.MaxValue is newer than MaxValue-1' $x.Active
$m = NewMachine
[void](Ev $m $true $true $true $max 5)
$x = Ev $m $true $true $true $max 5
Check 'A25 [22] sequence equal to the arm at Int64.MaxValue is not newer' (-not $x.Active)
$x = Ev $m $true $true $true $min 5
Check 'A26 [22] the count wrapped around (MaxValue -> MinValue): that Tick is newer, ON' $x.Active
$newer = $stateT.GetMethod('NewerThan', $nps)
Check 'A27 [22] NewerThan is overflow safe: (MinValue,MaxValue) true, (MaxValue,MinValue) false, (5,5) false, (6,5) true, (0,-1) true' (($newer.Invoke($null, @($min, $max))) -and (-not $newer.Invoke($null, @($max, $min))) -and (-not $newer.Invoke($null, @([long]5, [long]5))) -and ($newer.Invoke($null, @([long]6, [long]5))) -and ($newer.Invoke($null, @([long]0, [long]-1))))

# [27] [28] [29] hysteresis and no oscillation
$m = NewMachine
[void](Ev $m $true $true $true 1 10)
$ch = 0; $act = $true
for ($i = 2; $i -lt 300; $i++) { $x = Ev $m $true $true $true $i ([double](5 + ($i % 11))); if ($x.Changed) { $ch++ }; if (-not $x.Active) { $act = $false } }
Check 'A28 [27] 298 evaluations with a Tick age of 5-15 ms: ON once, never an OFF, no change after the first' ($act -and ($ch -eq 1))
$m = NewMachine
[void](Ev $m $true $true $true 1 10); [void](Ev $m $true $true $true 2 10)
$ok = $true
foreach ($age in 300, 700, 1118, 1500, 1999, 2000) { $x = Ev $m $true $true $true 2 $age; if ((-not $x.Active) -or $x.Changed) { $ok = $false } }
Check 'A29 [28] ON, the Tick stops: 300 / 700 / 1118 / 1500 / 1999 / 2000 ms keep ON (the observed 1062-1118 ms stops do not toggle it)' $ok
$x = Ev $m $true $true $true 2 2001
Check 'A30 [29] then 2001 ms: soft OFF (tick-stale)' ((-not $x.Active) -and ($x.Reason -ceq 'TickStale'))
$x = Ev $m $true $true $true 3 6
Check 'A31 after a soft OFF the next new Tick (age <= 250) turns it ON again without any ScenarioReady change' ($x.Active -and $x.Changed)
$m = NewMachine
[void](Ev $m $true $true $true 1 10)
$a = Ev $m $true $true $true 2 400
$b = Ev $m $true $true $true 3 1200
Check 'A32 hysteresis: OFF stays OFF at 400 ms and 1200 ms (only <= 250 turns it ON)' ((-not $a.Active) -and (-not $b.Active))
$m = NewMachine
[void](Ev $m $true $true $true 1 10)
$stay = $true
for ($i = 2; $i -lt 60; $i++) { $x = Ev $m $true $true $false $i 5; if ($x.Active) { $stay = $false } }
Check 'A33 [30] ScenarioReady not published (BveEX OFF / withdrawn) while Ticks keep coming (58 evaluations): stays OFF' $stay
$cnt = [int]$appT.GetField('TickFreshOnMs').GetRawConstantValue() * 100000 + [int]$appT.GetField('TickStaleOffMs').GetRawConstantValue()
Check 'A34 thresholds in the DLL: AppProtocol.TickFreshOnMs = 250, TickStaleOffMs = 2000' ($cnt -eq 250 * 100000 + 2000)

# ================================================================================================================ C: the real session (deterministic stepping + fake Bridge objects)
Write-Host '--- C: Caller session, stepped by hand, fake Bridge objects'
$p = SetLog 'c1.log' 940001
$pid1 = 940001
$bridge = NewBridgeObjs $pid1
SetSR $bridge 1 $false
$h = NewSession $pid1
Step $h
Check 'C01 [3] Bridge present, no Tick, no ScenarioReady: OFF' (-not (Active $h))
for ($i = 0; $i -lt 5; $i++) { TickS $h; Step $h }
Check 'C02 [2] Ticks and a Bridge but ScenarioReady not published (Ready alone is not ScenarioReady): OFF' (-not (Active $h))
SetSR $bridge 1 $true
Step $h
$drv = $sessT.GetField('driving', $npi).GetValue($h.Session)
$seqNow = [long]$sessT.GetProperty('TickSequence', $npi).GetValue($h.Session)
Check 'C03 [5][6] ScenarioReady seen published right after a Tick (same monitor period): the arm is the Tick count at that moment, still OFF (C-1: a Tick just before the publication is not used)' ((-not (Active $h)) -and (MArmed $drv) -and ((MArmSeq $drv) -eq $seqNow))
Step $h
Check 'C04 [6] another step with no new Tick: OFF' (-not (Active $h))
TickS $h
Step $h
Check 'C05 [7] one new Tick after the publication was seen: ON' (Active $h)
Check 'C06 [24] exactly one DRIVING_ACTIVE_ON line, with cycle, ScenarioGeneration and tickAgeMs' ((@(EventLines $p 'DRIVING_ACTIVE_ON').Count -eq 1) -and (@(EventLines $p 'DRIVING_ACTIVE_ON')[0] -match ' S=Caller T=A th=\d+ DRIVING_ACTIVE_ON cycle=\d+ ScenarioGeneration=1 tickAgeMs=[\d.]+ onCount=1$'))
$linesBefore = @(Lines $p).Count
for ($i = 0; $i -lt 200; $i++) { TickS $h; Step $h }
Check ('C07 [23][27] 200 further (Tick, step) pairs while ON: no new log line (' + $linesBefore + ' -> ' + @(Lines $p).Count + '), still ON, one ON in total') ((@(Lines $p).Count -eq $linesBefore) -and (Active $h) -and ((SProp $h 'DrivingActiveOnCount') -eq 1))

# the Tick stops for 1.25 s (more than the observed 1118 ms stop): stays ON, nothing logged
Run $h 1250 100 0
Check 'C08 [28] the Tick stops for 1.25 s (real time): still ON, no OFF line' ((Active $h) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 0))
TickS $h; Step $h
Check 'C09 [28] the Tick resumes: still ON, still one ON line and no OFF line' ((Active $h) -and (@(EventLines $p 'DRIVING_ACTIVE_ON').Count -eq 1) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 0))
# the Tick stops for 2.2 s: soft OFF once
Run $h 2250 100 0
$off = @(EventLines $p 'DRIVING_ACTIVE_OFF')
Check 'C10 [26][29] the Tick stops for 2.25 s: soft OFF exactly once (reason=tick-stale class=soft), counters 0 hard / 1 soft' ((-not (Active $h)) -and ($off.Count -eq 1) -and ($off[0] -match 'reason=tick-stale class=soft ScenarioGeneration=1 tickAgeMs=2\d\d\d\.\d activeForMs=') -and ((SProp $h 'DrivingSoftOffCount') -eq 1) -and ((SProp $h 'DrivingHardOffCount') -eq 0))
Run $h 400 50 0
Check 'C11 [23] 400 ms more of steps with no Tick: still one OFF line (no repeated log for the same state)' (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 1)
TickS $h; Step $h
Check 'C12 the Tick resumes after a soft OFF: ON again in the same Caller cycle, ScenarioReady never changed (second ON line)' ((Active $h) -and (@(EventLines $p 'DRIVING_ACTIVE_ON').Count -eq 2))
# hard OFF by ScenarioReady withdrawal while Ticks continue
SetSR $bridge 1 $false
TickS $h; Step $h
$off = @(EventLines $p 'DRIVING_ACTIVE_OFF')
Check 'C13 [13][25] ScenarioReady withdrawn: OFF in that very step, one hard OFF line (reason=scenario-ready-off class=hard)' ((-not (Active $h)) -and ($off.Count -eq 2) -and ($off[1] -match 'reason=scenario-ready-off class=hard ') -and ((SProp $h 'DrivingHardOffCount') -eq 1))
for ($i = 0; $i -lt 60; $i++) { TickS $h; Step $h }
Check 'C14 [30] ScenarioReady stays withdrawn and the Caller Tick goes on (60 more Ticks): still OFF, no further OFF line' ((-not (Active $h)) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 2))
SetSR $bridge 1 $true
Step $h
Check 'C15 [16] ScenarioReady published again, no new Tick since: OFF' (-not (Active $h))
Step $h
TickS $h; Step $h
Check 'C16 [17] the next new Tick: ON (third ON line)' ((Active $h) -and (@(EventLines $p 'DRIVING_ACTIVE_ON').Count -eq 3))
EndS $h
$off = @(EventLines $p 'DRIVING_ACTIVE_OFF')
$ev = @(Lines $p | ForEach-Object { if ($_ -match ' (CALLER_DISPOSE_BEGIN|DRIVING_ACTIVE_OFF|SCN_READY_OFF|CALLER_DISPOSE_END) ') { $Matches[1] } })
Check 'C17 [14][25] Dispose: DRIVING_ACTIVE_OFF reason=dispose class=hard is logged once, after CALLER_DISPOSE_BEGIN and before CALLER_DISPOSE_END' (($off.Count -eq 3) -and ($off[2] -match 'reason=dispose class=hard ') -and ((SProp $h 'DrivingLastOffReason').ToString() -ceq 'Dispose') -and ((SProp $h 'DrivingHardOffCount') -eq 2) -and (-not (Active $h)))
EndS $h
TickS $h; Step $h
Check 'C18 a second Dispose and a late Tick/step after Dispose add no OFF line and keep it OFF' ((@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 3) -and (-not (Active $h)))
Check 'C19 no exception line in the whole log' (@(EventLines $p 'DRIVING_EXCEPTION').Count -eq 0)
DisposeBridgeObjs $bridge

# generations under a still-published ScenarioReady
$p = SetLog 'c2.log' 940002
$pid2 = 940002
$bridge = NewBridgeObjs $pid2
SetSR $bridge 1 $false
$h = NewSession $pid2
Step $h; SetSR $bridge 1 $true; Step $h; TickS $h; Step $h
$on1 = Active $h
TickS $h
SetSR $bridge 2 $true      # another scenario published under the same, never withdrawn, ScenarioReady
Step $h
Check 'C20 [20] ON in generation 1; the generation changes under a still-published ScenarioReady and the Tick that came just before is not used: OFF (hard, scenario-ready-off)' ($on1 -and (-not (Active $h)) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 1) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF')[0] -match 'reason=scenario-ready-off class=hard ScenarioGeneration=2'))
Step $h
Check 'C21 [20] no new Tick yet: OFF' (-not (Active $h))
TickS $h; Step $h
Check 'C22 [21] a new Tick in generation 2: ON again' ((Active $h) -and (@(EventLines $p 'DRIVING_ACTIVE_ON')[-1] -match 'ScenarioGeneration=2'))
EndS $h
DisposeBridgeObjs $bridge

# cycles: a new Caller instance inherits nothing
$p = SetLog 'c3.log' 940003
$pid3 = 940003
$bridge = NewBridgeObjs $pid3
SetSR $bridge 4 $true
$hA = NewSession $pid3
Step $hA; TickS $hA; Step $hA; TickS $hA; Step $hA
$seqA = [long]$sessT.GetProperty('TickSequence', $npi).GetValue($hA.Session)
$onA = Active $hA
EndS $hA
$hB = NewSession $pid3     # TS Scoring ON again: a new Caller instance while ScenarioReady is already published
$seqB = [long]$sessT.GetProperty('TickSequence', $npi).GetValue($hB.Session)
Step $hB
$drvB = $sessT.GetField('driving', $npi).GetValue($hB.Session)
Check 'C23 [18][19] the new Caller instance: Tick count 0 (not the old instance count), OFF, armed only by its own first reading' ($onA -and ($seqA -ge 2) -and ($seqB -eq 0) -and (-not (Active $hB)) -and (MArmed $drvB) -and ((MArmSeq $drvB) -eq 0))
Step $hB
Check 'C24 [18] still OFF until its own first Tick; then ON' ((-not (Active $hB)) -and ((TickS $hB) -eq $null) -and ((Step $hB) -eq $null) -and (Active $hB))
Check 'C25 [18][19] the DrivingActive fields of the session are instance fields (lastTickQpc, tickSeq, driving): nothing static carries a Tick count or a state across Caller cycles' ((-not $sessT.GetField('tickSeq', $npi).IsStatic) -and (-not $sessT.GetField('lastTickQpc', $npi).IsStatic) -and (-not $sessT.GetField('driving', $npi).IsStatic))
EndS $hB
DisposeBridgeObjs $bridge

# overflow of the real counter
$p = SetLog 'c4.log' 940004
$pid4 = 940004
$bridge = NewBridgeObjs $pid4
SetSR $bridge 1 $true
$h = NewSession $pid4
$sessT.GetField('tickSeq', $npi).SetValue($h.Session, [long]::MaxValue)
Step $h                # armed at Int64.MaxValue
TickS $h               # Interlocked.Increment wraps to Int64.MinValue
Step $h
Check 'C26 [22] the Tick count wraps around (MaxValue -> MinValue) after the arm: that Tick still turns it ON, no exception' ((Active $h) -and ([long]$sessT.GetProperty('TickSequence', $npi).GetValue($h.Session) -eq [long]::MinValue) -and (@(EventLines $p 'DRIVING_EXCEPTION').Count -eq 0))
EndS $h
DisposeBridgeObjs $bridge

# no ScenarioReady, no objects at all: nothing happens and nothing is logged
$p = SetLog 'c5.log' 940005
$h = NewSession 940005
for ($i = 0; $i -lt 30; $i++) { TickS $h; Step $h }
Check 'C27 [2] no Bridge at all (BveEX off) while the Caller Tick runs: OFF, no DRIVING line' ((-not (Active $h)) -and (@(Lines $p | Where-Object { $_ -match ' DRIVING_' }).Count -eq 0))
EndS $h

# ================================================================================================================ M: the real monitor thread
Write-Host '--- M: production path (Start, monitor thread, device Tick)'
$p = SetLog 'm1.log' 940010
$pidM = 940010
$bridge = NewBridgeObjs $pidM
$h = NewSession $pidM $false
StartS $h
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt 300) { TickS $h; Wait 8 }
$offFirst = -not (Active $h)
SetSR $bridge 1 $true
$tOn = -1; $sw.Restart()
while ($sw.ElapsedMilliseconds -lt 2000) { TickS $h; if (Active $h) { $tOn = $sw.ElapsedMilliseconds; break }; Wait 8 }
$sw.Restart()
while ($sw.ElapsedMilliseconds -lt 1500) { TickS $h; Wait 8 }
Check ('M01 [27] monitor thread: Ticks without ScenarioReady stay OFF; after the publication ON within ' + $tOn + ' ms; then 1.5 s of Ticks (~100 Hz) keep ON with exactly one ON line') ($offFirst -and ($tOn -ge 0) -and ($tOn -lt 500) -and (Active $h) -and (@(EventLines $p 'DRIVING_ACTIVE_ON').Count -eq 1) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 0))
SetSR $bridge 1 $false
$sw.Restart(); $tOff = -1
while ($sw.ElapsedMilliseconds -lt 1000) { TickS $h; if (-not (Active $h)) { $tOff = $sw.ElapsedMilliseconds; break }; Wait 5 }
Check ('M02 [13] ScenarioReady withdrawn while the Ticks go on: OFF within the monitor period (' + $tOff + ' ms), one hard OFF line') (($tOff -ge 0) -and ($tOff -lt 500) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF').Count -eq 1) -and (@(EventLines $p 'DRIVING_ACTIVE_OFF')[0] -match 'class=hard'))
EndS $h
DisposeBridgeObjs $bridge
Check 'M03 the monitor thread ended and no kernel object of the fake PID is left' (([int]$sessT.GetField('LiveMonitors', $nps).GetValue($null) -eq 0) -and (-not (ObjectExists $pidM 'Enabled')))

# the device: one million real Tick() calls
$p = SetLog 'm2.log' 940011
$dev = [Activator]::CreateInstance($deviceT)
$devTick = [Delegate]::CreateDelegate([Action], $dev, 'Tick')
$linesBefore = @(Lines $p).Count
$thBefore = [Diagnostics.Process]::GetCurrentProcess().Threads.Count
$us = [TickHammer]::Run($devTick, 1000000)
$thAfter = [Diagnostics.Process]::GetCurrentProcess().Threads.Count
$linesAfter = @(Lines $p).Count
$devSession = $deviceT.GetField('session', $npi).GetValue($dev)
Check ('M04 one million real device Tick() calls: ' + [math]::Round($us / 1000.0, 1) + ' ms in total, log untouched, no thread created, Tick count exact, monitor not running') (($us -lt 1000000) -and ($linesAfter -eq $linesBefore) -and ($thAfter -le $thBefore + 4) -and ([long]$sessT.GetProperty('TickSequence', $npi).GetValue($devSession) -eq 1000000) -and (-not [bool]$sessT.GetProperty('MonitorAlive', $npi).GetValue($devSession)))
try { $dev.Dispose() } catch { }

# 32-bit: BVE5 is a 32-bit process
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
if (Test-Path $ps32) {
    $out = & $ps32 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Root $Root -Probe32 2>&1 | Where-Object { $_ -match '^PROBE32' }
    $okProbe = ($out -match 'ptr=4 seq=2000000 mono=True on=True')
    Check ('M05 [31] 32-bit process (BVE5): two real threads call NotifyTick 1,000,000 times each; the 64-bit Tick count is exact (2,000,000), never read torn or backwards, and DrivingActive turns ON (' + ($out -join '') + ')') ([bool]$okProbe)
}
else {
    Check 'M05 [31] 32-bit PowerShell not available: the 32-bit atomic path is covered by the static check D07 only' $true
}

# ================================================================================================================ D: static checks on the sources and the DLL
Write-Host '--- D: static checks'
function RunGit([string[]]$gitArgs) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.Arguments = (($gitArgs | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $pr = [Diagnostics.Process]::Start($psi)
    $o = $pr.StandardOutput.ReadToEnd()
    $pr.WaitForExit()
    if ($pr.ExitCode -ne 0) { throw ('git failed: ' + ($gitArgs -join ' ')) }
    return $o
}
$prefix = (RunGit @('rev-parse', '--show-prefix')).Trim()
$top = (RunGit @('rev-parse', '--show-toplevel')).Trim()
function BaseText([string]$rel) { return ((RunGit @('show', ($Baseline + ':' + $prefix + $rel.Replace('\', '/')))) -replace "`r`n", "`n") }
function WorkText([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $Root $rel))) -replace "`r`n", "`n") }
function NoComments([string]$s) { return [regex]::Replace($s, '//[^\n]*', '') }
function BodyOf([string]$text, [string]$sig) {
    $mm = [regex]::Match($text, [regex]::Escape($sig) + '\s*\{(?<b>[\s\S]*?)\n        \}')
    if ($mm.Success) { return (NoComments $mm.Groups['b'].Value) }
    return $null
}
function MethodText([string]$text, [string]$name) { $mm = [regex]::Match($text, '(?ms)^        (private|internal|public) [^\n]*\b' + $name + '\([^\n]*\)\s*\n        \{.*?\n        \}\n'); return $mm.Value }

$hsNow = WorkText 'Caller\src\HandshakeSession.cs'
$hsBase = BaseText 'Caller\src\HandshakeSession.cs'
$devNow = WorkText 'Caller\src\TsScoringCallerInputDevice.cs'
$stSrc = WorkText 'Caller\src\DrivingActivityState.cs'
$notifyBody = BodyOf $hsNow 'public void NotifyTick()'
$devTickBody = BodyOf $devNow 'public void Tick()'
Check 'D01 [33] the Tick paths were found (device Tick, NotifyTick)' (($notifyBody -ne $null) -and ($devTickBody -ne $null))
$tickAll = ($notifyBody + "`n" + $devTickBody)
Check 'D02 [33] the Tick path has no file / log / stream I/O' ($tickAll -notmatch 'File|Stream|Directory|Obs\(|ObsA\(|ObservationLog|Console|Debug|Trace|Registry|Write\(')
Check 'D03 [34] the Tick path opens no kernel object (no Event / Mutex / Open / TryOpenExisting / MemoryMapped), reads no ScenarioReady block' ($tickAll -notmatch 'EventWaitHandle|Mutex|Semaphore|OpenExisting|TryOpenExisting|MemoryMapped|Open|ScenarioState|scenarioView|scenarioEvent')
Check 'D04 [35] the Tick path has no wait, lock, sleep, thread, task or join' ($tickAll -notmatch 'WaitOne|Wait\(|Sleep|lock\s*\(|Monitor\.|Join|Thread|Task|Invoke')
Check 'D05 [36] the Tick path has no MessageBox / dialog / notice' ($tickAll -notmatch 'MessageBox|showNotice|DefaultShowNotice')
Check 'D06 the Tick path starts nothing and has no UDP / Python (no Process, Start, Udp, Socket, python)' ($tickAll -notmatch 'Process|Start|Udp|Socket|(?i)python')
Check 'D07 [31] the Tick time and count are written with Interlocked.Exchange / Interlocked.Increment, and every other access to the two 64-bit fields is Interlocked.Read (BVE5 is a 32-bit process)' (($notifyBody -match 'Interlocked\.Exchange\(ref lastTickQpc, Stopwatch\.GetTimestamp\(\)\)') -and ($notifyBody -match 'Interlocked\.Increment\(ref tickSeq\)') -and (@([regex]::Matches((NoComments $hsNow), '\b(lastTickQpc|tickSeq)\b') | Where-Object { $true }).Count -eq @([regex]::Matches((NoComments $hsNow), 'Interlocked\.(Exchange|Increment|Read)\(ref (lastTickQpc|tickSeq)\b')).Count + 2))
Check 'D08 the first-Tick flag logic of Phase M1 is kept in NotifyTick (flag test, one timestamp, one volatile write)' (($notifyBody -match 'if \(tickSeen\)') -and ($notifyBody -match 'firstTickQpc = Stopwatch\.GetTimestamp\(\)') -and ($notifyBody -match 'tickSeen = true'))
Check 'D09 [37] no Process.Start / ProcessStartInfo / CreateProcess / ShellExecute in any Caller or shared source, nor a reference in the DLL' (((@(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs) + @(Get-ChildItem (Join-Path $Root 'Shared') -Filter *.cs) | Where-Object { (NoComments (WorkText $_.FullName.Substring($Root.Length + 1))) -match 'Process\.Start|ProcessStartInfo|CreateProcess|ShellExecute|WinExec|UseShellExecute' }).Count -eq 0) -and (-not (Test-BytesContain $callerBytes 'ProcessStartInfo')) -and (-not (Test-BytesContain $callerBytes 'CreateProcess')) -and (-not (Test-BytesContain $callerBytes 'ShellExecute')))
Check 'D10 [38] no Python in the Caller sources or the DLL, and no .py file is among the files of this phase (changes since the baseline inside the Handshake tree, and the committed history since the baseline)' ((@(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { (NoComments (WorkText ('Caller\src\' + $_.Name))) -match '(?i)python|\.py\b' }).Count -eq 0) -and (-not (Test-BytesContain $callerBytes 'python')) -and (@(((RunGit @('-C', $top, 'diff', '--name-only', $Baseline, '--', $prefix)) -split "`n") | Where-Object { $_ -match '\.py$' }).Count -eq 0) -and (@(((RunGit @('-C', $top, 'diff', '--name-only', $Baseline, '6018a5b')) -split "`n") | Where-Object { $_ -match '\.py$' }).Count -eq 0))
Check 'D11 no AppReady / Stop event for an application, no job object, no UDP / socket, no hook, no registry, no Mutex in the Caller sources or the DLL' ((@(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { (NoComments (WorkText ('Caller\src\' + $_.Name))) -match 'AppReady|JobObject|UdpClient|Socket|SetWindowsHook|RegisterHotKey|Registry|HttpClient|WebClient|Mutex' }).Count -eq 0) -and (-not (Test-BytesContain $callerBytes 'JobObject')) -and (-not (Test-BytesContain $callerBytes 'UdpClient')) -and (-not (Test-BytesContain $callerBytes 'Registry')) -and (-not (Test-BytesContain $callerBytes 'AppReady')))
$nonCommentSt = NoComments $stSrc
Check 'D12 DrivingActivityState.cs is pure: no clock (Stopwatch / DateTime), no I/O, no thread, no lock, no kernel object, no log call' ($nonCommentSt -notmatch 'Stopwatch|DateTime|File|Stream|Thread|lock\s*\(|Interlocked|EventWaitHandle|Mutex|Obs\(|ObsA\(|ObservationLog|MessageBox|Process')
$apSrc = NoComments (WorkText 'Shared\AppProtocol.cs')
$consts = @([regex]::Matches($apSrc, 'const\s+\w+\s+(\w+)\s*=\s*(\d+)') | ForEach-Object { $_.Groups[1].Value + '=' + $_.Groups[2].Value })
Check ('D13 AppProtocol.cs holds only the two thresholds (' + ($consts -join ', ') + '): no path, process, event, Mutex or job definition') ((($consts -join ',') -ceq 'TickFreshOnMs=250,TickStaleOffMs=2000') -and ($apSrc -notmatch 'string|Mutex|Event|Process|Job|Path|exe'))
Check 'D14 the OFF reasons are classified hard (dispose, disabled, scenario-ready-off) and soft (tick-stale) in the source' (($stSrc -match 'return reason == DrivingOffReason\.Dispose \|\| reason == DrivingOffReason\.Disabled \|\| reason == DrivingOffReason\.ScenarioReadyOff;') -and ($stSrc -match '"tick-stale"') -and ($stSrc -match '"scenario-ready-off"'))

# the unchanged contracts: compared with the baseline commit (the commit this phase started from)
$mbPattern = '^\s*(internal const string (NoticeText|ProductDisplayName|ProviderName)|private const uint MB_|\[DllImport\("user32\.dll", EntryPoint = "MessageBoxW"|private static extern int MessageBoxW|"TS Scoring|"[^"]*(BveEX|BveEx)[^"]*"|MessageBoxW\()'
$mbNow = @(($hsNow -split "`n") | Where-Object { $_ -match $mbPattern })
$mbBase = @(($hsBase -split "`n") | Where-Object { $_ -match $mbPattern })
Check ('D15 [39] M1 dependency notice unchanged: every MessageBox line (text, title, flags, P/Invoke, call) is identical to the baseline commit (' + $mbBase.Count + ' lines)') (($mbBase.Count -ge 8) -and (($mbNow -join "`n") -ceq ($mbBase -join "`n")))
$noticeMethods = 'JudgeFirstTickLocked', 'ShowNoticeIfStillNeeded', 'CheckBridgeTimeoutLocked', 'StartNoticeLocked', 'OnBridgeSeenLocked', 'OnBridgeLostLocked', 'OnReadyLocked', 'SignalledLocked', 'ProbeBridgeDirectLocked', 'StateLocked'
$noticeSame = @($noticeMethods | Where-Object { $b0 = MethodText $hsBase $_; ($b0.Length -gt 30) -and ($b0 -ceq (MethodText $hsNow $_)) })
Check ('D16 [39] the notice logic methods are byte-identical to the baseline commit (' + $noticeSame.Count + ' of ' + $noticeMethods.Count + ')') ($noticeSame.Count -eq $noticeMethods.Count)
$ctim = $callerAsm.GetType($NS + 'CallerNoticeTiming'); $timing = $callerAsm.GetType($NS + 'HandshakeTiming')
Check 'D17 [40] StartupBridgeDiagnosticMs = 1000, ConnectionLostNoticeMs = 500 = BridgeMissingTimeoutMs, CallerPollMs = 20 (DLL values; the Shared source is identical to the baseline)' (($ctim.GetField('StartupBridgeDiagnosticMs').GetRawConstantValue() -eq 1000) -and ($ctim.GetField('ConnectionLostNoticeMs').GetRawConstantValue() -eq 500) -and ([int]$timing.GetField('BridgeMissingTimeoutMs').GetValue($null) -eq 500) -and ([int]$timing.GetField('CallerPollMs').GetValue($null) -eq 20) -and ((BaseText 'Shared\HandshakeProtocol.cs') -ceq (WorkText 'Shared\HandshakeProtocol.cs')))
$noticeText = [string]$sessT.GetField('NoticeText', $nps).GetRawConstantValue()
Check 'D18 [39] the notice text constant keeps its two lines (CR LF between them, names BveEX) and the title constant is TS Scoring; the source lines are compared with the baseline in D15' (($noticeText.Contains([string][char]13 + [string][char]10)) -and ($noticeText.Contains('BveEX')) -and ($noticeText.Length -gt 20) -and ([string]$sessT.GetField('ProductDisplayName', $nps).GetRawConstantValue() -ceq 'TS Scoring'))
$scenarioFiles = 'Bridge\src\ScenarioReadyTracker.cs', 'Bridge\src\ScenarioReadyPublisher.cs', 'Bridge\src\ScenarioObserver.cs', 'Bridge\src\TsScoringBridgePrototype.cs', 'Shared\HandshakeProtocol.cs', 'Shared\ObservationLog.cs'
$scenarioDiff = @($scenarioFiles | Where-Object { (BaseText $_) -cne (WorkText $_) })
Check 'D19 [41] ScenarioReady / ScenarioGeneration contract unchanged: tracker, publisher, observer, Bridge entry, HandshakeProtocol and ObservationLog sources are identical to the baseline commit' ($scenarioDiff.Count -eq 0)
$srMethods = 'ObserveScenarioLocked', 'OpenScenarioObjectsLocked', 'ReleaseScenarioObjectsLocked'
$srSame = @($srMethods | Where-Object { $b0 = MethodText $hsBase $_; ($b0.Length -gt 200) -and ($b0 -ceq (MethodText $hsNow $_)) })
Check 'D20 [32] the Caller ScenarioReady reader is byte-identical to the baseline commit; it names only the shared objects (Current and Legacy publish the same ones) and the Caller has no BveEX / AtsEX host reference' (($srSame.Count -eq 3) -and (-not (Test-BytesContain $callerBytes 'BveEx.PluginHost')) -and (-not (Test-BytesContain $callerBytes 'AtsEx.PluginHost')) -and ($nonCommentSt -notmatch 'BveEx|AtsEx|BveTypes|PluginHost'))
$bridgeNow = @(Get-ChildItem (Join-Path $Root 'Bridge') -Recurse -File -Include *.cs, *.csproj | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' })
$bridgeBaseList = @((RunGit @('ls-tree', '-r', '--name-only', '--full-name', $Baseline, '--', 'Bridge')) -split "`n" | Where-Object { $_ -match '\.(cs|csproj)$' })
$bridgeDiff = @()
foreach ($bf in $bridgeBaseList) { $rel = $bf.Substring($prefix.Length).Replace('/', '\'); if ((-not (Test-Path (Join-Path $Root $rel))) -or ((BaseText $rel) -cne (WorkText $rel))) { $bridgeDiff += $rel } }
$curSha = (Get-FileHash (Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')).Hash
$curOutSha = (Get-FileHash (Join-Path $Root 'Bridge\out\TSScoringPlugin.BveEx.Bridge.Prototype.dll')).Hash
$legSha = (Get-FileHash (Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')).Hash
Check ('D21 [42] Bridge sources unchanged (' + $bridgeBaseList.Count + ' files identical to the baseline commit, none added) and both Bridge DLLs are the formal ones (Current 247F6724..., Legacy C2883E40...)') (($bridgeDiff.Count -eq 0) -and ($bridgeNow.Count -eq $bridgeBaseList.Count) -and ($curSha -eq '247F67243253E5AD3C98D1B04BF8C4C8F19399C8B91317A7744D5E12A901A5AA') -and ($curOutSha -eq $curSha) -and ($legSha -eq 'C2883E400B1DCC1E0720392B90EAAED7CD770F6EB8DC6CF4CBA06FF80598EB48'))
$hsDiff = @(Compare-Object ($hsBase -split "`n") ($hsNow -split "`n") | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject.Trim() })
$hsDiffCode = @($hsDiff | Where-Object { $_ -notmatch '^(//|///)' })
Check ('D22 HandshakeSession.cs vs the baseline commit: only additions plus the rewritten NotifyTick doc comment (' + $hsDiff.Count + ' baseline lines removed, ' + $hsDiffCode.Count + ' of them code)') (($hsDiffCode.Count -eq 0) -and ($hsDiff.Count -le 6))

# observation identifiers must not be in the product
Check 'D23 [43] no Phase D1-OBS identifier in the sources or the DLL: no fixed D1-OBS log name, no D1OBS_ event, no DrivingObsLog / DrivingActivityObserver, no Phase M0 identifier' ((-not (Test-BytesContain $callerBytes 'D1OBS')) -and (-not (Test-BytesContain $callerBytes 'PhaseD1OBS')) -and (-not (Test-BytesContain $callerBytes 'DrivingObsLog')) -and (-not (Test-BytesContain $callerBytes 'DrivingActivityObserver')) -and (-not (Test-BytesContain $callerBytes 'PhaseM0')) -and (-not (Test-BytesContain $callerBytes 'M0Observ')) -and (@(Get-ChildItem $Root -Recurse -Include *.cs, *.csproj | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' -and ((NoComments ([IO.File]::ReadAllText($_.FullName))) -match 'D1OBS|D1-OBS|DrivingObsLog|DrivingActivityObserver') }).Count -eq 0))
Check 'D24 the only log file name in the DLL is still the shared C1 observation log; it carries the DRIVING_ events' ((Test-BytesContain $callerBytes 'TSScoring-Phase-C1-Observation.log') -and (Test-BytesContain $callerBytes 'DRIVING_ACTIVE_ON') -and (Test-BytesContain $callerBytes 'DRIVING_ACTIVE_OFF') -and (Test-BytesContain $callerBytes 'DRIVING_EXCEPTION'))

# metadata
$vi = (Get-Item $callerPath).VersionInfo
Check 'D25 [45] provider Coruge-to (company, copyright, ProviderName constant); product TS Scoring; version 0.9.0.0 (Phase E1 build); description names Phase E1 and no observation / diagnostic / D1-OBS wording; DLL name unchanged' (($vi.CompanyName -eq 'Coruge-to') -and ($vi.LegalCopyright -match 'Coruge-to') -and ($vi.ProductName -eq 'TS Scoring') -and ([string]$sessT.GetField('ProviderName', $nps).GetRawConstantValue() -ceq 'Coruge-to') -and ($vi.FileVersion -eq '0.9.0.0') -and ($callerAsm.GetName().Version.ToString() -eq '0.9.0.0') -and ($vi.Comments -match 'Phase E1') -and ($vi.Comments -notmatch '(?i)observation|diagnostic|D1-OBS') -and ($callerAsm.GetName().Name -ceq 'TSScoringPlugin.Caller.InputDevice') -and ((Split-Path $callerPath -Leaf) -ceq 'TSScoringPlugin.Caller.InputDevice.dll'))
Check 'D26 no PDB anywhere in the tree and dist holds exactly the Caller and the Current Bridge DLL' ((@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0) -and ((@(Get-ChildItem (Join-Path $Root 'dist') -File | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'TSScoringPlugin.BveEx.Bridge.Prototype.dll,TSScoringPlugin.Caller.InputDevice.dll'))
$refs = ($callerAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object) -join ','
Check ('D27 the Caller references only mscorlib, System, System.Core, System.Windows.Forms, Mackoy.IInputDevice (' + $refs + '); no third-party DLL') ($refs -eq 'Mackoy.IInputDevice,mscorlib,System,System.Core,System.Windows.Forms')

# privacy
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$privFiles = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs) + @(Get-Item (Join-Path $Root 'Shared\AppProtocol.cs')) + @(Get-Item $callerPath) + @(Get-Item (Join-Path $Root 'Caller\TSScoringPlugin.Caller.InputDevice.csproj')) + @(Get-Item (Join-Path $Root 'Docs\Handshake-PhaseD1-DrivingActive.md'))
$privHits = 0
foreach ($f in $privFiles) {
    $bytes = [IO.File]::ReadAllBytes($f.FullName)
    $ascii = [Text.Encoding]::ASCII.GetString($bytes); $utf16 = [Text.Encoding]::Unicode.GetString($bytes); $utf8 = [Text.Encoding]::UTF8.GetString($bytes)
    foreach ($tok in $forbidden) { foreach ($text in @($ascii, $utf16, $utf8)) { $privHits += ([regex]::Matches($text, [regex]::Escape($tok), 'IgnoreCase')).Count } }
    foreach ($text in @($ascii, $utf16, $utf8)) { $privHits += ([regex]::Matches($text, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count }
}
$selfText = [IO.File]::ReadAllText($PSCommandPath)
$selfHits = ([regex]::Matches($selfText, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count
foreach ($rn in $runtimeNames) { $selfHits += ([regex]::Matches($selfText, [regex]::Escape($rn), 'IgnoreCase')).Count }
$logsText = ''
foreach ($lf in @(Get-ChildItem $logDir -Filter *.log)) { $logsText += [IO.File]::ReadAllText($lf.FullName) }
$logHits = 0
foreach ($tok in $forbidden) { $logHits += ([regex]::Matches($logsText, [regex]::Escape($tok), 'IgnoreCase')).Count }
Check ('D28 [44] no user name, machine name, drive path, repository name or e-mail in the Caller sources, project, document and DLL (' + $privFiles.Count + ' files, matches=' + $privHits + '), in the produced test logs (matches=' + $logHits + '), or in this test (matches=' + $selfHits + ')') (($privHits -eq 0) -and ($selfHits -eq 0) -and ($logHits -eq 0))

# scope: exactly the planned files differ from the baseline commit inside the Handshake tree
$changedRel = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline, '--', $prefix)) -split "`n" | Where-Object { $_ })
$untrackedRel = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard', '--', $prefix)) -split "`n" | Where-Object { $_ })
$touched = @($changedRel + $untrackedRel | Sort-Object -Unique)
$planned = @(
    'Caller/src/AssemblyInfo.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/TsScoringCallerInputDevice.cs', 'Caller/src/DrivingActivityState.cs',
    'Caller/TSScoringPlugin.Caller.InputDevice.csproj', 'Shared/AppProtocol.cs',
    'Tests/Test-DrivingActiveD1.ps1', 'Tests/Test-DependencyNoticeM1.ps1', 'Tests/Test-ObservationC1.ps1',
    'Tools/Verify-PhaseC3.ps1', 'Tools/Verify-PhaseL1.ps1', 'Docs/Handshake-PhaseD1-DrivingActive.md',
    'Caller/src/AppController.cs', 'Tests/Test-AppControllerE1.ps1', 'Docs/Handshake-PhaseE1-AppController.md'
) | ForEach-Object { $prefix + $_ } | Sort-Object
$extra = @($touched | Where-Object { $_ -notin $planned }); $missing = @($planned | Where-Object { $_ -notin $touched })
Check ('D29 only the planned Phase D1 and Phase E1 files differ from the baseline commit inside the Handshake tree (' + $touched.Count + ' files; unexpected: [' + ($extra -join ', ') + '], missing: [' + ($missing -join ', ') + '])') (($extra.Count -eq 0) -and ($missing.Count -eq 0))
Check 'D30 no build output, DLL, PDB or log among the files of this phase (obj / out / dist / logs stay ignored)' (@($touched | Where-Object { $_ -match '/out/|/obj/|/dist/|/logs/|build\.log|\.dll$|\.pdb$|\.log$' }).Count -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })

# release every handle of this run
foreach ($s in $liveSessions) { try { $sessT.GetMethod('End').Invoke($s, @()) | Out-Null } catch { } }
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { $failed | ForEach-Object { 'FAILED: ' + $_.Name }; exit 1 }
