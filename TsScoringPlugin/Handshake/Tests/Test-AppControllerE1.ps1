# PHASE E1 - offline tests of the AppController DRY-RUN of the Caller (Caller 0.9.0.0).
# The controller only DECIDES when a future application start / stop would be requested: ONE start request per ScenarioGeneration (at the first
# DrivingActive ON of that generation) and ONE stop request per Caller instance (when Dispose begins, if a start request had been made).
# Nothing is started, stopped, sent or controlled. No BVE, no BveEX, no application, no UDP, no hooks, no MessageBox (a notice test double is used).
# The only Process.Start is the optional 32-bit PowerShell probe that runs THIS script again (and git for the static checks). The DLLs are loaded
# from memory. Every log goes to a private file under logs\e1-tests (never to the fixed Downloads file). Fake process ids are used; the only
# side effects are named kernel objects of this PowerShell process, released at the end.
# Sessions that are driven by hand (Step) have no monitor thread, so every ordering below is deterministic. This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Baseline = 'b000a158cf2544614524bc73c12db0148e0f0a20',
    # Phase E3: the static (source / scope) checks of this test describe THE PHASE E1 COMMIT, not the moving working tree: later phases
    # (E2 Python, E3 process start) legitimately change files this test used to forbid. Phase E3 has its own scope test.
    [string]$E1Commit = 'a43f18efca37caf64d33bb7c7d5529efd5b7067b',
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

public static class Racer
{
    // n real threads released at the same moment, each calling the action once; returns the number of exceptions
    public static int Run(System.Action a, int n)
    {
        int errors = 0;
        System.Threading.ManualResetEvent go = new System.Threading.ManualResetEvent(false);
        System.Threading.Thread[] ts = new System.Threading.Thread[n];
        for (int i = 0; i < n; i++)
        {
            ts[i] = new System.Threading.Thread(() =>
            {
                go.WaitOne();
                try { a(); } catch { System.Threading.Interlocked.Increment(ref errors); }
            });
            ts[i].IsBackground = true;
            ts[i].Start();
        }
        go.Set();
        foreach (System.Threading.Thread t in ts) { t.Join(); }
        return errors;
    }
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
$appT = $callerAsm.GetType($NS + 'AppController')
$ssT = $callerAsm.GetType($NS + 'ScenarioState')
$logT = $callerAsm.GetType($NS + 'ObservationLog')
$phaseT = $callerAsm.GetType($NS + 'CallerPhase')
$deviceT = $callerAsm.GetType($NS + 'TsScoringCallerInputDevice')
# Phase E3: no test reads the user's real launcher.json (the production constructor would start the application if it existed)
$callerAsm.GetType($NS + 'LauncherConfigLoader').GetProperty('TestPath', [Reflection.BindingFlags]'NonPublic,Static').SetValue($null, ([IO.Path]::Combine([IO.Path]::GetTempPath(), 'tss-no-launcher-' + [Guid]::NewGuid().ToString('N') + '.json')))
$npi = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$nps = [Reflection.BindingFlags]'NonPublic,Public,Static'

$logDir = Join-Path $Root 'logs\e1-tests'
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
function AppLines([string]$p) { return @(Lines $p | Where-Object { $_ -match ' APP_[A-Z_]+ ' }) }
function Field([string]$line, [string]$name) { $m = [regex]::Match($line, '\b' + [regex]::Escape($name) + '=(\S+)'); if ($m.Success) { return $m.Groups[1].Value } else { return $null } }
function IndexOfLine([string[]]$all, [string]$evt, [string]$extra = '') {
    for ($i = 0; $i -lt $all.Count; $i++) { if (($all[$i] -match (' ' + [regex]::Escape($evt) + ' ')) -and ($all[$i] -match $extra)) { return $i } }
    return -1
}

# the pure controller. Action is returned as its enum name.
function NewCtl { return [Activator]::CreateInstance($appT) }
function Obs($c, [bool]$active, [bool]$published, [int]$gen) {
    $st = $appT.GetMethod('Observe').Invoke($c, @($active, $published, $gen))
    $t = $st.GetType()
    return [pscustomobject]@{ Action = ([string]$t.GetField('Action').GetValue($st)); No = [int]$t.GetField('RequestNumber').GetValue($st); Gen = [int]$t.GetField('ScenarioGeneration').GetValue($st) }
}
function Disp($c) {
    $st = $appT.GetMethod('OnDispose').Invoke($c, @())
    $t = $st.GetType()
    return [pscustomobject]@{ Action = ([string]$t.GetField('Action').GetValue($st)); No = [int]$t.GetField('RequestNumber').GetValue($st); Gen = [int]$t.GetField('ScenarioGeneration').GetValue($st) }
}
function CProp($c, [string]$n) { return $appT.GetProperty($n).GetValue($c) }

# sessions driven by hand: no Start, no monitor thread. Step() is the monitor's step, called on this thread.
$sessionCtor = $sessT.GetConstructor($npi, $null, [Type[]]@([int], [Action[string]]), $null)
$stepM = $sessT.GetMethod('Step', $npi)
$allPids = New-Object System.Collections.Generic.List[int]
$liveSessions = New-Object System.Collections.Generic.List[object]
$cycleNo = 200
function NewSession([int]$fakePid, [bool]$manual = $true) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    $s = $sessionCtor.Invoke(@($fakePid, $del))
    $liveSessions.Add($s)
    $h = [pscustomobject]@{ Session = $s; Recorder = $rec; Pid = $fakePid; Cycle = 0 }
    if ($manual) {
        $script:cycleNo++
        $now = [long][Diagnostics.Stopwatch]::GetTimestamp()
        $sessT.GetField('started', $npi).SetValue($s, $true)
        $sessT.GetField('phase', $npi).SetValue($s, [Enum]::Parse($phaseT, 'WaitingForBridge'))
        $sessT.GetField('enabledQpc', $npi).SetValue($s, $now)
        $sessT.GetField('absenceStartQpc', $npi).SetValue($s, $now)
        $sessT.GetField('cycleNo', $npi).SetValue($s, $script:cycleNo)
        $h.Cycle = $script:cycleNo
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
    $u2 = [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1) # the #US heap of the metadata can start at an odd offset
    return (($a.IndexOf($text, [StringComparison]::Ordinal) -ge 0) -or ($u.IndexOf($text, [StringComparison]::Ordinal) -ge 0) -or ($u2.IndexOf($text, [StringComparison]::Ordinal) -ge 0))
}
# the Tick of BVE stopped for ms: the last Tick time is moved into the past (the monitor sees a stale Tick)
function MakeStale($h, [double]$ms) {
    $past = [long]([Diagnostics.Stopwatch]::GetTimestamp() - [long]($ms * [Diagnostics.Stopwatch]::Frequency / 1000.0))
    $sessT.GetField('lastTickQpc', $npi).SetValue($h.Session, $past)
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

# The scenario of one Caller instance that is compared between 64-bit and 32-bit: three generations, soft OFF / ON (Pause, Tick stop, legacy
# selection screen), withdrawal, a generation change under a still published scenario, Dispose. Returns the summary and the log.
function RunMainScenario([int]$fakePid, [string]$logName) {
    $p = SetLog $logName $fakePid
    $b = NewBridgeObjs $fakePid
    $h = NewSession $fakePid
    for ($i = 0; $i -lt 30; $i++) { TickS $h; Step $h }                       # Ticks, nothing published
    SetSR $b 1 $true
    Step $h; Step $h                                                           # armed, no Tick since the publication
    TickS $h; Step $h                                                          # generation 1: first ON -> start request 1
    for ($i = 0; $i -lt 50; $i++) { TickS $h; Step $h }                        # Pause-like: Ticks go on
    MakeStale $h 2500; Step $h                                                 # soft OFF
    TickS $h; Step $h                                                          # ON again (suppressed)
    MakeStale $h 2500; Step $h; TickS $h; Step $h                              # again (not reported twice)
    SetSR $b 1 $false; Step $h; TickS $h; Step $h                              # withdrawn: hard OFF
    SetSR $b 2 $true; Step $h; TickS $h; Step $h                               # generation 2 -> start request 2
    SetSR $b 3 $true; Step $h; TickS $h; Step $h                               # generation 3 under a still published scenario -> start request 3
    EndS $h; EndS $h
    $ls = AppLines $p
    $res = [pscustomobject]@{
        Starts = @($ls | Where-Object { $_ -match ' APP_START_REQUEST ' }).Count
        Stops = @($ls | Where-Object { $_ -match ' APP_STOP_REQUEST ' }).Count
        SuppressedLines = @($ls | Where-Object { $_ -match ' APP_START_SUPPRESSED ' }).Count
        Gens = (@($ls | Where-Object { $_ -match ' APP_START_REQUEST ' } | ForEach-Object { Field $_ 'ScenarioGeneration' }) -join ',')
        Nos = (@($ls | Where-Object { $_ -match ' APP_START_REQUEST ' } | ForEach-Object { Field $_ 'requestNo' }) -join ',')
        CtlStarts = [int]$sessT.GetProperty('AppStartRequestCount', $npi).GetValue($h.Session)
        CtlStops = [int]$sessT.GetProperty('AppStopRequestCount', $npi).GetValue($h.Session)
        CtlSuppressed = [int]$sessT.GetProperty('AppSuppressedCount', $npi).GetValue($h.Session)
        Log = $p
        Lines = @(Lines $p)
        Cycle = $h.Cycle
        Handle = $h
    }
    DisposeBridgeObjs $b
    return $res
}
function Summary($r) { return ('starts={0} stops={1} suppressedLines={2} gens={3} nos={4} ctl={5}/{6}/{7}' -f $r.Starts, $r.Stops, $r.SuppressedLines, $r.Gens, $r.Nos, $r.CtlStarts, $r.CtlStops, $r.CtlSuppressed) }

# ================================================================================================================ 32-bit probe (runs in a 32-bit PowerShell)
if ($Probe32) {
    $r = RunMainScenario 950101 'probe32.log'
    foreach ($s in $liveSessions) { try { $sessT.GetMethod('End').Invoke($s, @()) | Out-Null } catch { } }
    ('PROBE32 ptr={0} {1}' -f [IntPtr]::Size, (Summary $r))
    exit 0
}

# ================================================================================================================ A: the pure controller
Write-Host '--- A: pure controller (no clock, no I/O, no log)'
$c = NewCtl
Check 'A01 initial state: no start request, no stop request, nothing suppressed, not closed' (((CProp $c 'StartRequestCount') -eq 0) -and ((CProp $c 'StopRequestCount') -eq 0) -and ((CProp $c 'SuppressedCount') -eq 0) -and (-not (CProp $c 'Closed')) -and ((CProp $c 'LastRequestedGeneration') -eq 0))

$c = NewCtl
$x = @(1..40 | ForEach-Object { (Obs $c $false $true 1).Action })
Check 'A02 the scenario is published but DrivingActive never turns ON (40 evaluations): no request' ((@($x | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StartRequestCount') -eq 0))
$x = @(1..40 | ForEach-Object { (Obs $c $true $false 1).Action })
Check 'A03 DrivingActive ON while the scenario is NOT published (contract not met): no request' ((@($x | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StartRequestCount') -eq 0))
$x = @((Obs $c $true $true 0).Action, (Obs $c $true $true -1).Action, (Obs $c $true $true ([int]::MinValue)).Action)
Check 'A04 DrivingActive ON with generation 0 / negative (no valid generation): no request' ((@($x | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StartRequestCount') -eq 0))
$x = Obs $c $true $true 1
Check 'A05 published + first DrivingActive ON: ONE start request (number 1, generation 1)' (($x.Action -eq 'StartRequested') -and ($x.No -eq 1) -and ($x.Gen -eq 1) -and ((CProp $c 'StartRequestCount') -eq 1) -and ((CProp $c 'LastRequestedGeneration') -eq 1))
$y = @(1..200 | ForEach-Object { (Obs $c $true $true 1).Action })
Check 'A06 the same ON repeated 200 times (a level, not an edge): no further request, nothing reported' ((@($y | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StartRequestCount') -eq 1) -and ((CProp $c 'SuppressedCount') -eq 0))
$x = Obs $c $false $true 1
Check 'A07 soft OFF (published, not active): no request of any kind, no stop' (($x.Action -eq 'None') -and ((CProp $c 'StopRequestCount') -eq 0) -and (-not (CProp $c 'Closed')))
$x = Obs $c $true $true 1
Check 'A08 ON again in the same generation: no new start request; the suppression is reported ONCE (still request number 1)' (($x.Action -eq 'StartSuppressed') -and ($x.No -eq 1) -and ($x.Gen -eq 1) -and ((CProp $c 'StartRequestCount') -eq 1) -and ((CProp $c 'SuppressedCount') -eq 1))
$acts = @()
for ($i = 0; $i -lt 20; $i++) { $acts += (Obs $c $false $true 1).Action; $acts += (Obs $c $true $true 1).Action }
Check 'A09 20 more OFF / ON oscillations in the same generation: start requests stay 1, every ON is counted (21), the suppression is NOT reported again' ((@($acts | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StartRequestCount') -eq 1) -and ((CProp $c 'SuppressedCount') -eq 21) -and ((CProp $c 'StopRequestCount') -eq 0))
$x = Obs $c $false $false 1
Check 'A10 the scenario is withdrawn (hard OFF): no stop request, the controller stays open and keeps its memory' (($x.Action -eq 'None') -and ((CProp $c 'StopRequestCount') -eq 0) -and (-not (CProp $c 'Closed')) -and ((CProp $c 'LastRequestedGeneration') -eq 1))
$x = Obs $c $true $true 2
Check 'A11 a NEW generation: its first ON is a new start request (number 2, generation 2)' (($x.Action -eq 'StartRequested') -and ($x.No -eq 2) -and ($x.Gen -eq 2) -and ((CProp $c 'StartRequestCount') -eq 2))
[void](Obs $c $false $true 2)
$x = Obs $c $true $true 2
Check 'A12 nothing is inherited from the old generation: the suppression of generation 2 is reported once for generation 2 although generation 1 had reported its own' (($x.Action -eq 'StartSuppressed') -and ($x.Gen -eq 2) -and ((CProp $c 'StartRequestCount') -eq 2))
$x = Obs $c $true $true 3
Check 'A13 the generation changes while DrivingActive is still reported ON (level): a new start request for generation 3 (number 3)' (($x.Action -eq 'StartRequested') -and ($x.No -eq 3) -and ($x.Gen -eq 3))
[void](Obs $c $false $true 1)
$x = Obs $c $true $true 1
Check 'A14 an earlier generation number comes back (generation overflow wraps to 1): it is a new generation, a new start request (number 4)' (($x.Action -eq 'StartRequested') -and ($x.No -eq 4) -and ($x.Gen -eq 1))
$x = Disp $c
Check 'A15 Dispose after four start requests: ONE stop request (number 1), the controller is closed' (($x.Action -eq 'StopRequested') -and ($x.No -eq 1) -and ($x.Gen -eq 1) -and ((CProp $c 'StopRequestCount') -eq 1) -and (CProp $c 'Closed'))
$x = @((Disp $c).Action, (Disp $c).Action, (Disp $c).Action)
Check 'A16 Dispose observed again (several paths): no second stop request' ((@($x | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StopRequestCount') -eq 1))
$x = @((Obs $c $true $true 7).Action, (Obs $c $false $true 7).Action, (Obs $c $true $true 8).Action)
Check 'A17 after Dispose began the controller never requests again (ON, OFF, a new generation)' ((@($x | Where-Object { $_ -ne 'None' }).Count -eq 0) -and ((CProp $c 'StartRequestCount') -eq 4) -and ((CProp $c 'StopRequestCount') -eq 1))

$c = NewCtl
$x = Disp $c
$y = Disp $c
Check 'A18 Dispose of a controller that never requested a start (0 generations): no stop request - only the one "not required" note, then nothing' (($x.Action -eq 'StopNotRequired') -and ($y.Action -eq 'None') -and ((CProp $c 'StopRequestCount') -eq 0) -and ((CProp $c 'StartRequestCount') -eq 0))
$c = NewCtl
[void](Obs $c $true $true 1); [void](Obs $c $false $true 1); [void](Obs $c $true $true 1)
$x = Disp $c
Check 'A19 one generation with several ON / OFF: one start request, one stop request' (((CProp $c 'StartRequestCount') -eq 1) -and ($x.Action -eq 'StopRequested') -and ((CProp $c 'StopRequestCount') -eq 1))

# five generations, three ON / OFF cycles each
$c = NewCtl
$startNos = @(); $supRep = 0
foreach ($g in 1..5) {
    for ($k = 0; $k -lt 3; $k++) {
        $a = Obs $c $true $true $g; if ($a.Action -eq 'StartRequested') { $startNos += $a.No }; if ($a.Action -eq 'StartSuppressed') { $supRep++ }
        [void](Obs $c $false $true $g)
    }
    [void](Obs $c $false $false $g)
}
Check 'A20 five generations x three ON / OFF cycles (withdrawn in between): exactly 5 start requests numbered 1..5, 5 reported suppressions, no stop' ((($startNos -join ',') -eq '1,2,3,4,5') -and ($supRep -eq 5) -and ((CProp $c 'StartRequestCount') -eq 5) -and ((CProp $c 'SuppressedCount') -eq 10) -and ((CProp $c 'StopRequestCount') -eq 0))

# 3000 random evaluations against an independent model of the rules
$rnd = New-Object Random 20261009
$bad = 0; $starts = 0; $modelStarts = 0
for ($trial = 0; $trial -lt 30; $trial++) {
    $c = NewCtl
    $has = $false; $lastReq = 0; $prev = $false; $repGen = 0; $modelStarts = 0
    for ($i = 0; $i -lt 100; $i++) {
        $act = ($rnd.Next(100) -lt 60); $pub = ($rnd.Next(100) -lt 85); $gen = $rnd.Next(0, 5)
        $r = Obs $c $act $pub $gen
        $elig = $act -and $pub -and ($gen -gt 0); $rising = $elig -and (-not $prev); $prev = $elig
        $exp = 'None'; $expNo = 0
        if ($elig) {
            if ($has -and ($gen -eq $lastReq)) { if ($rising -and ($repGen -ne $gen)) { $exp = 'StartSuppressed'; $repGen = $gen; $expNo = $modelStarts } }
            else { $modelStarts++; $has = $true; $lastReq = $gen; $exp = 'StartRequested'; $expNo = $modelStarts }
        }
        if (($r.Action -ne $exp) -or (($exp -ne 'None') -and ($r.No -ne $expNo))) { $bad++ }
    }
    if ((CProp $c 'StartRequestCount') -ne $modelStarts) { $bad++ }
    if ((CProp $c 'StopRequestCount') -ne 0) { $bad++ }
    $d = Disp $c
    $expDisp = if ($modelStarts -gt 0) { 'StopRequested' } else { 'StopNotRequired' }
    if (($d.Action -ne $expDisp) -or ((CProp $c 'StopRequestCount') -ne $(if ($modelStarts -gt 0) { 1 } else { 0 }))) { $bad++ }
    $starts += $modelStarts
}
Check ('A21 30 random sequences of 100 evaluations (' + $starts + ' start requests in total) agree with an independent model; a stop request only at Dispose, and only after a start request') ($bad -eq 0)

$c = NewCtl
$ok = $true
foreach ($g in @([int]::MaxValue, 1, [int]::MaxValue)) { try { [void](Obs $c $true $true $g); [void](Obs $c $false $true $g) } catch { $ok = $false } }
Check 'A22 extreme generation numbers (Int32.MaxValue, back to 1, Int32.MaxValue again) do not throw; each change is a new request (3)' ($ok -and ((CProp $c 'StartRequestCount') -eq 3))

# ================================================================================================================ S: the session (hand-driven monitor steps)
Write-Host '--- S: session (Step driven by hand, real DrivingActive state, real log)'
$pid1 = 960001
$r = RunMainScenario $pid1 's1-main.log'
$L = $r.Lines
$app = AppLines $r.Log
$startLines = @($app | Where-Object { $_ -match ' APP_START_REQUEST ' })
$stopLines = @($app | Where-Object { $_ -match ' APP_STOP_REQUEST ' })
Check ('S01 three generations, soft OFF / ON, Pause-like Ticks, withdrawal, generation change, Dispose: ' + (Summary $r)) (($r.Starts -eq 3) -and ($r.Stops -eq 1) -and ($r.Gens -eq '1,2,3') -and ($r.Nos -eq '1,2,3') -and ($r.CtlStarts -eq 3) -and ($r.CtlStops -eq 1))
$f = $startLines[0]
Check 'S02 the first start request names the Caller instance (cycle), the BVE PID, the generation, the request number, the reason and dry-run' (($f -match (' cycle=' + $r.Cycle + ' ')) -and ((Field $f 'pid') -eq [string]$pid1) -and ((Field $f 'ScenarioGeneration') -eq '1') -and ((Field $f 'requestNo') -eq '1') -and ((Field $f 'reason') -ceq 'first-driving-on') -and ((Field $f 'dryRun') -ceq 'yes') -and ($f -match ' T=A th=\d+ APP_START_REQUEST '))
$g = $stopLines[0]
Check 'S03 the stop request names instance, PID, request number 1, reason caller-dispose, the three start requests and dry-run' (($g -match (' cycle=' + $r.Cycle + ' ')) -and ((Field $g 'pid') -eq [string]$pid1) -and ((Field $g 'requestNo') -eq '1') -and ((Field $g 'reason') -ceq 'caller-dispose') -and ((Field $g 'startRequests') -eq '3') -and ((Field $g 'lastScenarioGeneration') -eq '3') -and ((Field $g 'dryRun') -ceq 'yes'))
$iOn1 = IndexOfLine $L 'DRIVING_ACTIVE_ON' 'ScenarioGeneration=1 '
$iStart1 = IndexOfLine $L 'APP_START_REQUEST' 'ScenarioGeneration=1 '
$iReadyOn1 = IndexOfLine $L 'SCN_READY_ON' 'ScenarioGeneration=1 '
Check 'S04 the first start request comes after the scenario publication and right with the first DrivingActive ON (never before them)' (($iReadyOn1 -ge 0) -and ($iOn1 -gt $iReadyOn1) -and ($iStart1 -gt $iOn1) -and ($iStart1 -eq $iOn1 + 1))
$firstStartIdx = $iStart1
$beforeStart = @($L[0..($firstStartIdx - 1)] | Where-Object { $_ -match ' APP_' })
Check 'S05 nothing APP_ was logged before it: 30 Ticks without a publication, the publication alone and the unarmed Steps produced no request' ($beforeStart.Count -eq 0)
$sup = @($app | Where-Object { $_ -match ' APP_START_SUPPRESSED ' })
Check 'S06 soft OFF (tick-stale) then ON again twice in generation 1 (Pause / Tick stop / legacy selection screen): no new start request, the suppression is reported ONCE (generation 1, request 1)' (($sup.Count -eq 1) -and ((Field $sup[0] 'ScenarioGeneration') -eq '1') -and ((Field $sup[0] 'requestNo') -eq '1') -and (@($L | Where-Object { $_ -match ' DRIVING_ACTIVE_OFF ' -and $_ -match 'reason=tick-stale' }).Count -eq 2))
$iOff = IndexOfLine $L 'DRIVING_ACTIVE_OFF' 'reason=scenario-ready-off class=hard ScenarioGeneration=1 '
$iGen2 = IndexOfLine $L 'SCN_GENERATION_CHANGED' 'to=2 '
$iStart2 = IndexOfLine $L 'APP_START_REQUEST' 'ScenarioGeneration=2 '
$iStopBetween = @($L[($iOff)..($iStart2)] | Where-Object { $_ -match ' APP_STOP_' }).Count
Check 'S07 the scenario is withdrawn (hard OFF, scenario-ready-off): NO stop request, the Caller instance keeps its controller' (($iOff -gt 0) -and ($iStopBetween -eq 0) -and (@($app | Where-Object { $_ -match ' APP_STOP_' }).Count -eq 1))
$iOn2 = IndexOfLine $L 'DRIVING_ACTIVE_ON' 'ScenarioGeneration=2 '
Check 'S08 the new generation 2: the start request follows its own first ON (generation change, ON, request) - not the old generation''s request' (($iGen2 -gt $iOff) -and ($iOn2 -gt $iGen2) -and ($iStart2 -eq $iOn2 + 1) -and ((Field $L[$iStart2] 'requestNo') -eq '2'))
$iGen3 = IndexOfLine $L 'SCN_GENERATION_CHANGED' 'to=3 '
$iOff3 = IndexOfLine $L 'DRIVING_ACTIVE_OFF' 'ScenarioGeneration=3 '
$iOn3 = IndexOfLine $L 'DRIVING_ACTIVE_ON' 'ScenarioGeneration=3 '
$iStart3 = IndexOfLine $L 'APP_START_REQUEST' 'ScenarioGeneration=3 '
$between = @($L[($iGen3)..($iOn3 - 1)] | Where-Object { $_ -match ' APP_' }).Count
Check 'S09 generation change under a still published scenario: order is generation change -> DrivingActive OFF (re-arm) -> ON -> start request 3; no request in between' (($iGen3 -gt $iOn2) -and ($iOff3 -gt $iGen3) -and ($iOn3 -gt $iOff3) -and ($iStart3 -eq $iOn3 + 1) -and ($between -eq 0))
$iDispOff = IndexOfLine $L 'DRIVING_ACTIVE_OFF' 'reason=dispose '
$iStop = IndexOfLine $L 'APP_STOP_REQUEST'
$iBegin = IndexOfLine $L 'CALLER_DISPOSE_BEGIN'
$iEnd = IndexOfLine $L 'CALLER_DISPOSE_END'
Check 'S10 Dispose: begin -> DrivingActive OFF (dispose) -> the stop request -> end; the second End() (a second path) wrote no second stop request' (($iBegin -ge 0) -and ($iDispOff -gt $iBegin) -and ($iStop -gt $iDispOff) -and ($iEnd -gt $iStop) -and ($stopLines.Count -eq 1))
Check 'S11 the soft OFF count is 2 and no stop request exists anywhere before Dispose (soft OFF and withdrawal never stop)' ((@($L[0..($iBegin)] | Where-Object { $_ -match ' APP_STOP_' }).Count -eq 0) -and ([int]$sessT.GetProperty('DrivingSoftOffCount', $npi).GetValue($r.Handle.Session) -eq 2))

# 0 requests, 1 request: instances that never / once start
$pid2 = 960002
$p = SetLog 's2-zero.log' $pid2
$b = NewBridgeObjs $pid2
$h = NewSession $pid2
for ($i = 0; $i -lt 40; $i++) { TickS $h; Step $h }
SetSR $b 1 $true
for ($i = 0; $i -lt 40; $i++) { Step $h }
Check 'S12 zero start requests: Ticks alone, then the publication alone (40 Steps each) - no APP_ line, DrivingActive OFF' (((AppLines $p).Count -eq 0) -and (-not (Active $h)))
EndS $h
$a2 = AppLines $p
Check 'S13 Dispose of that instance (nothing was requested): no APP_STOP_REQUEST; exactly one APP_STOP_NOT_REQUIRED note (reason no-start-request, dry-run)' ((@($a2 | Where-Object { $_ -match ' APP_STOP_REQUEST ' }).Count -eq 0) -and (@($a2 | Where-Object { $_ -match ' APP_STOP_NOT_REQUIRED ' }).Count -eq 1) -and ((Field (@($a2 | Where-Object { $_ -match 'NOT_REQUIRED' })[0]) 'reason') -ceq 'no-start-request'))
DisposeBridgeObjs $b

$pid3 = 960003
$p = SetLog 's3-one.log' $pid3
$b = NewBridgeObjs $pid3
$h = NewSession $pid3
SetSR $b 9 $true
Step $h; TickS $h; Step $h
EndS $h
$a3 = AppLines $p
Check 'S14 one generation, one ON: one start request and one stop request (generation 9)' ((@($a3 | Where-Object { $_ -match ' APP_START_REQUEST ' }).Count -eq 1) -and (@($a3 | Where-Object { $_ -match ' APP_STOP_REQUEST ' }).Count -eq 1) -and ((Field $a3[0] 'ScenarioGeneration') -eq '9'))
DisposeBridgeObjs $b

# Dispose observed from many threads at the same moment
$pid4 = 960004
$p = SetLog 's4-race.log' $pid4
$b = NewBridgeObjs $pid4
$h = NewSession $pid4
SetSR $b 1 $true
Step $h; TickS $h; Step $h
$endDel = [Delegate]::CreateDelegate([Action], $h.Session, 'End')
$errs = [Racer]::Run($endDel, 16)
$stepDel = [Delegate]::CreateDelegate([Action], $h.Session, $stepM)
$errs2 = [Racer]::Run($stepDel, 8)
$a4 = AppLines $p
Check 'S15 End() called by 16 threads at once, then Step() by 8 threads after it: exactly one stop request, no exception, no further start request' (($errs -eq 0) -and ($errs2 -eq 0) -and (@($a4 | Where-Object { $_ -match ' APP_STOP_REQUEST ' }).Count -eq 1) -and (@($a4 | Where-Object { $_ -match ' APP_START_REQUEST ' }).Count -eq 1) -and ([int](SProp $h 'AppStopRequestCount') -eq 1))
DisposeBridgeObjs $b

# the controller breaks: the Caller must not
$pid5 = 960005
$p = SetLog 's5-exception.log' $pid5
$b = NewBridgeObjs $pid5
$h = NewSession $pid5
$sessT.GetField('appController', $npi).SetValue($h.Session, $null)
SetSR $b 1 $true
$thrown = $false
try { Step $h; TickS $h; for ($i = 0; $i -lt 10; $i++) { Step $h } } catch { $thrown = $true }
$excLines = EventLines $p 'APP_EXCEPTION'
Check 'S16 the controller is broken (null): Step() does not throw, DrivingActive is still evaluated (ON), the exception is logged at most 3 times (type only), no request is made' ((-not $thrown) -and (Active $h) -and ($excLines.Count -eq 3) -and ((Field $excLines[0] 'type') -ceq 'NullReferenceException') -and (@(AppLines $p | Where-Object { $_ -match 'APP_(START|STOP)' }).Count -eq 0))
$endThrown = $false
try { $sessT.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { $endThrown = $true }
Check 'S17 End() with a broken controller still completes: phase Disposed, every kernel object released, the exception line cap holds (3), later Ticks and Steps are harmless' ((-not $endThrown) -and ((SProp $h 'Phase').ToString() -eq 'Disposed') -and (-not (ObjectExists $pid5 'Enabled')) -and (-not (ObjectExists $pid5 'Stop')) -and ((EventLines $p 'APP_EXCEPTION').Count -eq 3) -and ((TickS $h) -eq $null) -and ((Step $h) -eq $null))
DisposeBridgeObjs $b

# restored controller after an exception keeps working (the machine is not damaged by the failure of its caller)
$pid6 = 960006
$p = SetLog 's6-recover.log' $pid6
$b = NewBridgeObjs $pid6
$h = NewSession $pid6
$good = $sessT.GetField('appController', $npi).GetValue($h.Session)
$sessT.GetField('appController', $npi).SetValue($h.Session, $null)
SetSR $b 1 $true
Step $h; TickS $h; Step $h
$sessT.GetField('appController', $npi).SetValue($h.Session, $good)
Step $h; Step $h
EndS $h
$a6 = AppLines $p
Check 'S18 after the failed evaluations the original controller is put back: the (still ON) generation gets its one start request, and Dispose one stop request' ((@($a6 | Where-Object { $_ -match ' APP_START_REQUEST ' }).Count -eq 1) -and (@($a6 | Where-Object { $_ -match ' APP_STOP_REQUEST ' }).Count -eq 1))
DisposeBridgeObjs $b

# TS Scoring OFF -> ON: a new Caller instance inherits nothing
$pid7 = 960007
$p = SetLog 's7-offon.log' $pid7
$b = NewBridgeObjs $pid7
$h1 = NewSession $pid7
SetSR $b 1 $true
Step $h1; TickS $h1; Step $h1
EndS $h1
$h2 = NewSession $pid7
Step $h2
$mid = @(AppLines $p)
TickS $h2; Step $h2
EndS $h2
$a7 = @(AppLines $p)
$st7 = @($a7 | Where-Object { $_ -match ' APP_START_REQUEST ' }); $sp7 = @($a7 | Where-Object { $_ -match ' APP_STOP_REQUEST ' })
Check 'S19 TS Scoring OFF -> ON: instance 1 requested start + stop; instance 2 (new cycle) arms alone (no request), then makes its OWN start request number 1 and its own stop request number 1' (($st7.Count -eq 2) -and ($sp7.Count -eq 2) -and ($mid.Count -eq 2) -and ($st7[0] -match (' cycle=' + $h1.Cycle + ' ')) -and ($st7[1] -match (' cycle=' + $h2.Cycle + ' ')) -and ($h1.Cycle -ne $h2.Cycle) -and ((Field $st7[1] 'requestNo') -eq '1') -and ((Field $sp7[1] 'requestNo') -eq '1'))
DisposeBridgeObjs $b

# Enabled false: there is no path other than Dispose (and a Caller that was never started)
$pid8 = 960008
$p = SetLog 's8-disabled.log' $pid8
$hd = NewSession $pid8 $false
for ($i = 0; $i -lt 10; $i++) { Step $hd }
$beforeEnd = (AppLines $p).Count
EndS $hd
Check 'S20 Enabled never became true (Start was not called): Steps do nothing; End() without Start records only the "not required" note - Enabled=false alone never produces a stop request' (($beforeEnd -eq 0) -and (@(AppLines $p | Where-Object { $_ -match 'APP_STOP_REQUEST' }).Count -eq 0) -and ((AppLines $p).Count -eq 1))
$enabledAssign = @([regex]::Matches((Get-Content (Join-Path $Root 'Caller\src\HandshakeSession.cs') -Raw), 'phase = CallerPhase\.Disabled')).Count
Check 'S21 the Caller has exactly one place that makes the phase Disabled (its initial value): there is no runtime "Enabled=false" path that could be mistaken for a stop trigger' ($enabledAssign -eq 1)

# ================================================================================================================ M: production path (monitor thread, device)
Write-Host '--- M: production path (Start, monitor thread, device)'
$pidM = 960010
$p = SetLog 'm1.log' $pidM
$b = NewBridgeObjs $pidM
$h = NewSession $pidM $false
StartS $h
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt 300) { TickS $h; Wait 8 }
$noneBefore = (AppLines $p).Count
SetSR $b 1 $true
$tOn = -1; $sw.Restart()
while ($sw.ElapsedMilliseconds -lt 2000) { TickS $h; if ([int](SProp $h 'AppStartRequestCount') -ge 1) { $tOn = $sw.ElapsedMilliseconds; break }; Wait 8 }
$sw.Restart()
while ($sw.ElapsedMilliseconds -lt 1200) { TickS $h; Wait 8 }
$oneOnly = [int](SProp $h 'AppStartRequestCount')
SetSR $b 1 $false
$sw.Restart(); while ($sw.ElapsedMilliseconds -lt 400) { TickS $h; Wait 8 }
$stopsBeforeEnd = [int](SProp $h 'AppStopRequestCount')
EndS $h
DisposeBridgeObjs $b
$aM = AppLines $p
Check ('M01 monitor thread: nothing before the publication (' + $noneBefore + ' lines); the start request appears ' + $tOn + ' ms after it; 1.2 s of ~100 Hz Ticks add none; the withdrawal adds no stop; Dispose adds exactly one') (($noneBefore -eq 0) -and ($tOn -ge 0) -and ($tOn -lt 600) -and ($oneOnly -eq 1) -and ($stopsBeforeEnd -eq 0) -and (@($aM | Where-Object { $_ -match ' APP_START_REQUEST ' }).Count -eq 1) -and (@($aM | Where-Object { $_ -match ' APP_STOP_REQUEST ' }).Count -eq 1))
Check 'M02 the monitor thread ended and no kernel object of the fake PID is left' (([int]$sessT.GetField('LiveMonitors', $nps).GetValue($null) -eq 0) -and (-not (ObjectExists $pidM 'Enabled')) -and (-not (ObjectExists $pidM 'Stop')))

# the device: Dispose twice, Tick cost
$p = SetLog 'm2.log' 960011
$dev = [Activator]::CreateInstance($deviceT)
$devTick = [Delegate]::CreateDelegate([Action], $dev, 'Tick')
$linesBefore = @(Lines $p).Count
$thBefore = [Diagnostics.Process]::GetCurrentProcess().Threads.Count
$us = [TickHammer]::Run($devTick, 1000000)
$thAfter = [Diagnostics.Process]::GetCurrentProcess().Threads.Count
$linesAfter = @(Lines $p).Count
$devSession = $deviceT.GetField('session', $npi).GetValue($dev)
Check ('M03 one million real device Tick() calls: ' + [math]::Round($us / 1000.0, 1) + ' ms in total, log untouched (no APP_ line), no thread created, Tick count exact, monitor not running, no request') (($us -lt 1000000) -and ($linesAfter -eq $linesBefore) -and ($thAfter -le $thBefore + 4) -and ([long]$sessT.GetProperty('TickSequence', $npi).GetValue($devSession) -eq 1000000) -and (-not [bool]$sessT.GetProperty('MonitorAlive', $npi).GetValue($devSession)) -and ([int]$sessT.GetProperty('AppStartRequestCount', $npi).GetValue($devSession) -eq 0))
try { $dev.Dispose() } catch { }
try { $dev.Dispose() } catch { }
$notReq = @(EventLines $p 'APP_STOP_NOT_REQUIRED')
Check 'M04 the device is disposed twice (BVE / BveEX may call Dispose more than once): one "not required" note for a never started instance, never a stop request' (($notReq.Count -eq 1) -and ((EventLines $p 'APP_STOP_REQUEST').Count -eq 0))

# 32-bit: BVE5 is a 32-bit process
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
$r64 = RunMainScenario 960020 's9-bit-compare.log'
$sum64 = Summary $r64
if (Test-Path $ps32) {
    $out = & $ps32 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Root $Root -Probe32 2>&1 | Where-Object { $_ -match '^PROBE32' }
    $sum32 = (($out -join '') -replace '^PROBE32 ptr=4 ', '')
    Check ('M05 32-bit process (BVE5) and 64-bit process make identical decisions for the same scenario (' + $sum64 + ' | 32-bit: ' + $sum32 + ')') (($out -match 'ptr=4') -and ($sum32 -ceq $sum64))
}
else {
    Check 'M05 32-bit PowerShell not available: the controller has no pointer-size dependent code (checked by A and S)' $true
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
function WorkText([string]$rel) { return ((RunGit @('show', ($E1Commit + ':' + $prefix + $rel.Replace('\', '/')))) -replace "`r`n", "`n") }
function E1Names([string]$dir) { return @((RunGit @('ls-tree', '--name-only', $E1Commit, ($prefix + $dir + '/'))) -split "`n" | Where-Object { $_ } | ForEach-Object { Split-Path $_ -Leaf }) }
function NoComments([string]$s) { return [regex]::Replace($s, '//[^\n]*', '') }
function BodyOf([string]$text, [string]$sig) {
    $mm = [regex]::Match($text, [regex]::Escape($sig) + '\s*\{(?<b>[\s\S]*?)\n        \}')
    if ($mm.Success) { return (NoComments $mm.Groups['b'].Value) }
    return $null
}
function MethodText([string]$text, [string]$name) { $mm = [regex]::Match($text, '(?ms)^        (private|internal|public) [^\n]*\b' + $name + '\([^\n]*\)\s*\n        \{.*?\n        \}\n'); return $mm.Value }
function NumStat([string[]]$paths) { return @((RunGit (@('-C', $top, 'diff', '--numstat', $Baseline, $E1Commit, '--') + $paths)) -split "`n" | Where-Object { $_ }) }

$hsNow = WorkText 'Caller\src\HandshakeSession.cs'
$hsBase = BaseText 'Caller\src\HandshakeSession.cs'
$devNow = WorkText 'Caller\src\TsScoringCallerInputDevice.cs'
$acSrc = WorkText 'Caller\src\AppController.cs'
$acCode = NoComments $acSrc

$hsStat = @(NumStat @($prefix + 'Caller/src/HandshakeSession.cs'))
Check ('E01 HandshakeSession.cs vs the baseline commit: ONLY additions (' + ($hsStat -join '') + ')') (($hsStat.Count -eq 1) -and ($hsStat[0] -match '^\d+\s+0\s'))
$stepNow = MethodText $hsNow 'Step'; $stepBase = MethodText $hsBase 'Step'
$stepMinus = [regex]::Replace($stepNow, '(?m)^\s*ObserveAppControllerLocked\(\);\n', '')
Check 'E02 Step() equals the baseline Step() plus exactly one call line (ObserveAppControllerLocked, after EvaluateDrivingLocked, inside the lock)' (($stepBase.Length -gt 500) -and ($stepMinus -ceq $stepBase) -and ($stepNow -match 'EvaluateDrivingLocked\(now\);\n\s*ObserveAppControllerLocked\(\);\n\s*\}'))
$endNow = MethodText $hsNow 'End'; $endBase = MethodText $hsBase 'End'
$endMinus = [regex]::Replace($endNow, '(?m)^\s*DisposeAppControllerLocked\(\);[^\n]*\n', '')
Check 'E03 End() equals the baseline End() plus exactly one call line (DisposeAppControllerLocked, right after the DrivingActive hard OFF and before anything is released)' (($endBase.Length -gt 500) -and ($endMinus -ceq $endBase) -and ($endNow -match 'EvaluateDrivingLocked\(Stopwatch\.GetTimestamp\(\)\);[^\n]*\n\s*DisposeAppControllerLocked\(\);') -and ($endNow.IndexOf('DisposeAppControllerLocked();') -lt $endNow.IndexOf('ReleaseScenarioObjectsLocked();')))
$notifyNow = BodyOf $hsNow 'public void NotifyTick()'
Check 'E04 the Tick path is untouched: NotifyTick() and the device Tick() / Dispose() are byte-identical to the baseline and name no AppController, request, log or lock' (((MethodText $hsNow 'NotifyTick') -ceq (MethodText $hsBase 'NotifyTick')) -and ((NumStat @($prefix + 'Caller/src/TsScoringCallerInputDevice.cs')).Count -eq 0) -and ($notifyNow -notmatch 'AppController|appController|Request|Obs\(|ObsA\(|lock\s*\(|Process|\.Start'))
$callsObserve = @([regex]::Matches((NoComments $hsNow), 'ObserveAppControllerLocked\(\)'))
$callsDispose = @([regex]::Matches((NoComments $hsNow), 'DisposeAppControllerLocked\(\)'))
Check 'E05 the controller is reached from exactly two places: Step (monitor thread) and End; each method is defined once and called once' (($callsObserve.Count -eq 2) -and ($callsDispose.Count -eq 2) -and ((MethodText $hsNow 'ObserveAppControllerLocked').Length -gt 100) -and ((MethodText $hsNow 'DisposeAppControllerLocked').Length -gt 100))
$thrNow = @([regex]::Matches((NoComments $hsNow), 'new Thread\(')).Count; $thrBase = @([regex]::Matches((NoComments $hsBase), 'new Thread\(')).Count
Check ('E06 no new thread: HandshakeSession creates ' + $thrNow + ' thread sites (baseline ' + $thrBase + '), AppController none, and no timer / task / pool use') (($thrNow -eq $thrBase) -and ($acCode -notmatch 'Thread|Timer|Task|ThreadPool|Parallel|async|await'))
Check 'E07 AppController.cs is pure: no clock, no I/O, no thread, no lock, no Interlocked, no kernel object, no log call, no dialog, no using of System.Diagnostics / IO / Threading' ($acCode -notmatch 'Stopwatch|DateTime|Environment|File|Stream|Directory|lock\s*\(|Monitor\.|Interlocked|EventWaitHandle|Mutex|Semaphore|MemoryMapped|Obs\(|ObsA\(|ObservationLog|MessageBox|using System\.(Diagnostics|IO|Threading|Net|Runtime)|DllImport')
$procLinesNow = @(((WorkText 'Caller\src\HandshakeSession.cs') + "`n" + (WorkText 'Shared\HandshakeProtocol.cs') + "`n" + (WorkText 'Shared\ObservationLog.cs') + "`n" + $devNow) -split "`n" | Where-Object { $_.TrimStart() -notmatch '^//' -and $_ -match '\bProcess\b' } | ForEach-Object { $_.Trim() })
$procLinesBase = @(((BaseText 'Caller\src\HandshakeSession.cs') + "`n" + (BaseText 'Shared\HandshakeProtocol.cs') + "`n" + (BaseText 'Shared\ObservationLog.cs') + "`n" + (BaseText 'Caller\src\TsScoringCallerInputDevice.cs')) -split "`n" | Where-Object { $_.TrimStart() -notmatch '^//' -and $_ -match '\bProcess\b' } | ForEach-Object { $_.Trim() })
$e1CallerNames = E1Names 'Caller/src'
$allCs = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { $_.Name -in $e1CallerNames }) + @(Get-ChildItem (Join-Path $Root 'Shared') -Filter *.cs)
$procHits = @($allCs | Where-Object { (NoComments (WorkText $_.FullName.Substring($Root.Length + 1))) -match 'Process\.Start|ProcessStartInfo|CreateProcess|ShellExecute|WinExec|UseShellExecute|\bProcess\s+\w+\s*[=;]' -and $_.Name -ne 'HandshakeProtocol.cs' })
Check ('E08 no Process.Start / ProcessStartInfo / CreateProcess / ShellExecute and no Process-typed field or variable in any Caller source (the one existing Process.GetCurrentProcess() line of HandshakeProtocol is unchanged: ' + $procLinesBase.Count + ' line), nor a reference in the DLL') ((($procLinesNow -join "`n") -ceq ($procLinesBase -join "`n")) -and ($procHits.Count -eq 0))
$tokenFiles = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { $_.Name -in $e1CallerNames } | Where-Object { (NoComments (WorkText ('Caller\src\' + $_.Name))) -match '(?i)python|\.py\b|main\.py|\.exe\b|AppReady|StopEvent|SessionEvent|DrivingEvent|JobObject|Backoff|Restart|Respawn|Launch|HUD|Overlay|UdpClient|Socket|SetWindowsHookEx|RegisterHotKey|Registry|Kickstart|Mutex' })
Check 'E09 no application, Event, HUD, scoring, UDP, hook, restart or back-off vocabulary in any Caller source (code lines)' ($tokenFiles.Count -eq 0)
Check 'E10 the DLL still has the dry-run log events and reasons (the E1 "no application vocabulary" rule is pinned to the Phase E1 sources above; E3 has its own DLL checks)' ((Test-BytesContain $callerBytes 'APP_START_REQUEST') -and (Test-BytesContain $callerBytes 'APP_STOP_REQUEST') -and (Test-BytesContain $callerBytes 'APP_START_SUPPRESSED') -and (Test-BytesContain $callerBytes 'APP_STOP_NOT_REQUIRED') -and (Test-BytesContain $callerBytes 'first-driving-on') -and (Test-BytesContain $callerBytes 'caller-dispose'))
Check 'E11 every logged request line carries dryRun=yes (source) and the reasons are exactly first-driving-on / caller-dispose' ((@([regex]::Matches((WorkText 'Caller\src\HandshakeSession.cs'), 'ObsA\("APP_(START_REQUEST|START_SUPPRESSED|STOP_REQUEST|STOP_NOT_REQUIRED)", [^\n]*dryRun=yes"\)')).Count -eq 4) -and ($acSrc -match 'FirstDrivingOn = "first-driving-on"') -and ($acSrc -match 'CallerDispose = "caller-dispose"'))

# unchanged contracts, compared with the baseline commit
$sameList = @('Caller/src/DrivingActivityState.cs', 'Shared/AppProtocol.cs', 'Shared/HandshakeProtocol.cs', 'Shared/ObservationLog.cs', 'Bridge')
$sameStat = NumStat @($sameList | ForEach-Object { $prefix + $_ })
Check ('E12 DrivingActivityState.cs (conditions, 250 / 2000 ms, hard / soft OFF reasons), AppProtocol.cs, HandshakeProtocol.cs, ObservationLog.cs and every Current / Legacy Bridge source are identical to the baseline commit (' + $sameStat.Count + ' differences)') ($sameStat.Count -eq 0)
$ctim = $callerAsm.GetType($NS + 'CallerNoticeTiming'); $timing = $callerAsm.GetType($NS + 'HandshakeTiming'); $appP = $callerAsm.GetType($NS + 'AppProtocol')
Check 'E13 timings in the DLL: TickFreshOnMs 250, TickStaleOffMs 2000, StartupBridgeDiagnosticMs 1000, ConnectionLostNoticeMs 500, BridgeMissingTimeoutMs 500, CallerPollMs 20' (($appP.GetField('TickFreshOnMs').GetRawConstantValue() -eq 250) -and ($appP.GetField('TickStaleOffMs').GetRawConstantValue() -eq 2000) -and ($ctim.GetField('StartupBridgeDiagnosticMs').GetRawConstantValue() -eq 1000) -and ($ctim.GetField('ConnectionLostNoticeMs').GetRawConstantValue() -eq 500) -and ([int]$timing.GetField('BridgeMissingTimeoutMs').GetValue($null) -eq 500) -and ([int]$timing.GetField('CallerPollMs').GetValue($null) -eq 20))
$noticeMethods = 'JudgeFirstTickLocked', 'ShowNoticeIfStillNeeded', 'CheckBridgeTimeoutLocked', 'StartNoticeLocked', 'OnBridgeSeenLocked', 'OnBridgeLostLocked', 'OnReadyLocked', 'SignalledLocked', 'ProbeBridgeDirectLocked', 'StateLocked', 'ObserveScenarioLocked', 'OpenScenarioObjectsLocked', 'ReleaseScenarioObjectsLocked', 'EvaluateDrivingLocked', 'MonitorLoop', 'Start'
$noticeSame = @($noticeMethods | Where-Object { $b0 = MethodText $hsBase $_; ($b0.Length -gt 100) -and ($b0 -ceq (MethodText $hsNow $_)) })
Check ('E14 M1 dependency notice, ScenarioReady / ScenarioGeneration reading, DrivingActive evaluation, monitor loop and Start are byte-identical to the baseline (' + $noticeSame.Count + ' of ' + $noticeMethods.Count + ' methods)') ($noticeSame.Count -eq $noticeMethods.Count)
$mbPattern = '^\s*(internal const string (NoticeText|ProductDisplayName|ProviderName)|private const uint MB_|\[DllImport\("user32\.dll", EntryPoint = "MessageBoxW"|private static extern int MessageBoxW|"TS Scoring|"[^"]*(BveEX|BveEx)[^"]*"|MessageBoxW\()'
$mbNow = @(($hsNow -split "`n") | Where-Object { $_ -match $mbPattern }); $mbBase = @(($hsBase -split "`n") | Where-Object { $_ -match $mbPattern })
Check ('E15 every MessageBox line of the dependency notice (text, title, flags, P/Invoke, call) is identical to the baseline (' + $mbBase.Count + ' lines)') (($mbBase.Count -ge 8) -and (($mbNow -join "`n") -ceq ($mbBase -join "`n")))
$curSha = (Get-FileHash (Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')).Hash
$curOutSha = (Get-FileHash (Join-Path $Root 'Bridge\out\TSScoringPlugin.BveEx.Bridge.Prototype.dll')).Hash
$legSha = (Get-FileHash (Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')).Hash
Check 'E16 both Bridge DLLs are the formal ones (Current 247F6724..., Legacy C2883E40...)' (($curSha -eq '247F67243253E5AD3C98D1B04BF8C4C8F19399C8B91317A7744D5E12A901A5AA') -and ($curOutSha -eq $curSha) -and ($legSha -eq 'C2883E400B1DCC1E0720392B90EAAED7CD770F6EB8DC6CF4CBA06FF80598EB48'))

# scope: python, HUD, scoring, UDP, hooks, installer
$changedAll = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline, $E1Commit)) -split "`n" | Where-Object { $_ })
$touchedAll = @($changedAll | Sort-Object -Unique)
$planned = @(
    'Caller/src/AppController.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/AssemblyInfo.cs', 'Caller/TSScoringPlugin.Caller.InputDevice.csproj',
    'Tests/Test-AppControllerE1.ps1', 'Docs/Handshake-PhaseE1-AppController.md',
    'Tests/Test-DrivingActiveD1.ps1', 'Tests/Test-DependencyNoticeM1.ps1', 'Tests/Test-ObservationC1.ps1', 'Tools/Verify-PhaseC3.ps1', 'Tools/Verify-PhaseL1.ps1'
) | ForEach-Object { $prefix + $_ } | Sort-Object
$extra = @($touchedAll | Where-Object { $_ -notin $planned }); $missing = @($planned | Where-Object { $_ -notin $touchedAll })
Check ('E17 only the planned Phase E1 files differ from the baseline commit in the WHOLE repository (' + $touchedAll.Count + ' files; unexpected: [' + ($extra -join ', ') + '], missing: [' + ($missing -join ', ') + '])') (($extra.Count -eq 0) -and ($missing.Count -eq 0))
$mainBlob = (RunGit @('-C', $top, 'rev-parse', ($Baseline + ':main.py'))).Trim()
$mainNow = (RunGit @('-C', $top, 'rev-parse', ($E1Commit + ':main.py'))).Trim()
Check 'E18 main.py is byte-identical to the baseline commit (git blob hash), and no .py file, HUD / UDP / scoring / hook / installer / Class1 / project file changed' (($mainBlob -eq $mainNow) -and (@($touchedAll | Where-Object { $_ -match '\.py$|Class1\.cs|AtsLoggerPlugin\.cs|installer|\.iss$|\.vcxproj|\.slnx$|scoring_logic|menu_ui|config\.py|utils\.py' }).Count -eq 0))
Check 'E19 no build output, DLL, PDB or log among the files of this phase (obj / out / dist / logs stay ignored)' (@($touchedAll | Where-Object { $_ -match '/out/|/obj/|/dist/|/logs/|build\.log|\.dll$|\.pdb$|\.log$' }).Count -eq 0)

# metadata
$vi = (Get-Item $callerPath).VersionInfo
$e1Info = WorkText 'Caller\src\AssemblyInfo.cs'
Check 'E20 (Phase E1 commit) provider Coruge-to; product TS Scoring; version 0.9.0.0 (file and assembly); description names Phase E1 and no observation / diagnostic wording; DLL name unchanged' (($e1Info -match 'AssemblyCompany\("Coruge-to"\)') -and ($e1Info -match 'AssemblyProduct\("TS Scoring"\)') -and ($e1Info -match 'AssemblyVersion\("0\.9\.0\.0"\)') -and ($e1Info -match 'AssemblyFileVersion\("0\.9\.0\.0"\)') -and ($e1Info -match 'AssemblyDescription\("Phase E1') -and ($e1Info -notmatch '(?i)observation build|diagnostic build') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.ProductName -eq 'TS Scoring') -and ($callerAsm.GetName().Name -ceq 'TSScoringPlugin.Caller.InputDevice'))
Check 'E21 no PDB anywhere in the tree, dist holds exactly the Caller and the Current Bridge DLL, and the Caller references only mscorlib, System, System.Core, System.Windows.Forms, Mackoy.IInputDevice' ((@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0) -and ((@(Get-ChildItem (Join-Path $Root 'dist') -File | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'TSScoringPlugin.BveEx.Bridge.Prototype.dll,TSScoringPlugin.Caller.InputDevice.dll') -and ((($callerAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'Mackoy.IInputDevice,mscorlib,System,System.Core,System.Windows.Forms'))
$proj = WorkText 'Caller\TSScoringPlugin.Caller.InputDevice.csproj'
Check 'E22 (Phase E1 commit) the project compiles AppController.cs and nothing else new (Compile items: AppController, AssemblyInfo, DrivingActivityState, HandshakeSession, TsScoringCallerInputDevice + the three Shared files)' ((@([regex]::Matches($proj, '<Compile Include="([^"]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object) -join ',') -ceq ((@('src\AppController.cs', 'src\AssemblyInfo.cs', 'src\DrivingActivityState.cs', 'src\HandshakeSession.cs', 'src\TsScoringCallerInputDevice.cs', '..\Shared\AppProtocol.cs', '..\Shared\HandshakeProtocol.cs', '..\Shared\ObservationLog.cs') | Sort-Object) -join ','))
$docPath = Join-Path $Root 'Docs\Handshake-PhaseE1-AppController.md'
Check 'E23 the Phase E1 document exists and states the dry-run (start once per ScenarioGeneration, stop once at Dispose, nothing started)' ((Test-Path $docPath) -and (([IO.File]::ReadAllText($docPath, [Text.Encoding]::UTF8)) -match 'dry-run') -and (([IO.File]::ReadAllText($docPath, [Text.Encoding]::UTF8)) -match 'APP_START_REQUEST') -and (([IO.File]::ReadAllText($docPath, [Text.Encoding]::UTF8)) -match 'APP_STOP_REQUEST'))

# privacy
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$privFiles = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs) + @(Get-Item $callerPath) + @(Get-Item (Join-Path $Root 'Caller\TSScoringPlugin.Caller.InputDevice.csproj'))
if (Test-Path $docPath) { $privFiles += @(Get-Item $docPath) }
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
Check ('E24 no user name, machine name, drive path, repository name or e-mail in the Caller sources, project, document and DLL (' + $privFiles.Count + ' files, matches=' + $privHits + '), in the produced test logs (matches=' + $logHits + '), or in this test (matches=' + $selfHits + ')') (($privHits -eq 0) -and ($selfHits -eq 0) -and ($logHits -eq 0))

$failed = @($results | Where-Object { -not $_.Ok })

# release every handle of this run
foreach ($s in $liveSessions) { try { $sessT.GetMethod('End').Invoke($s, @()) | Out-Null } catch { } }
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { $failed | ForEach-Object { 'FAILED: ' + $_.Name }; exit 1 }
