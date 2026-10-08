# PHASE M1 - offline tests of the BveEX dependency notice at scenario use start (Caller 0.7.0.0).
# The REAL Caller session code is driven with fake PIDs and a notice test double: no MessageBox is ever shown, no BVE, no BveEX runtime,
# no Python, no UDP, no hooks. The first BVE Tick is simulated by calling the session's NotifyTick (what TsScoringCallerInputDevice.Tick does).
# Where the cached state must differ from the direct BridgeAvailable check, an injected probe (test constructor) or a real kernel object whose
# owner closed it without resetting it is used. Every log goes to a private file under logs\m1-tests (never the fixed Downloads file).
# This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Baseline = '0f4c841122d1ce1590ca897f742db09d2265d5ae'
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

public class ProbeSwitch
{
    public int Calls;
    public bool[] Script = new bool[0];
    public bool Fallback;
    public bool Probe()
    {
        int i = System.Threading.Interlocked.Increment(ref Calls) - 1;
        return i < Script.Length ? Script[i] : Fallback;
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
'@

Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class TestResolver
{
    public static void Install(string[] dirs)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string name = e.Name.Split(',')[0];
            foreach (string dir in dirs)
            {
                foreach (string ext in new string[] { ".dll", ".DLL" })
                {
                    string p = Path.Combine(dir, name + ext);
                    if (File.Exists(p)) { return Assembly.LoadFrom(p); }
                }
            }
            return null;
        };
    }
}
"@
[TestResolver]::Install(@((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), (Join-Path $env:PUBLIC 'Documents\BveEx\2.0')))

$callerPath = Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll'
$bridgePath = Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll'
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($callerPath))
$bridgeAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($bridgePath))
$NS = 'TSScoringPlugin.Handshake.'
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$deviceType = $callerAsm.GetType($NS + 'TsScoringCallerInputDevice')
$bridgeType = $bridgeAsm.GetType($NS + 'TsScoringBridgePrototype')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $bridgeAsm.GetType($NS + 'ObservationLog')
$NPS = [Reflection.BindingFlags]'NonPublic,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$sessionCtorProbe = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]], [Func[bool]]), $null)
$tickMethod = $bridgeType.GetMethod('Tick')
$publishMethod = $bridgeType.GetMethod('PublishAvailability', $NPI)

$testDir = Join-Path $Root 'logs\m1-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

# ---- helpers (same technique as the Phase B suite) ----
function LogCfg($type, [string]$path, [int]$fakePid) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]0)
}
function NewLog([string]$name, [int]$fakePid) { $p = Join-Path $testDir ($name + '.log'); LogCfg $cLog $p $fakePid; LogCfg $bLog $p $fakePid; return $p }
function ReadLog([string]$path) { if (Test-Path -LiteralPath $path) { return @(Get-Content -LiteralPath $path -Encoding UTF8) } else { return @() } }
function EvtLines([string[]]$lines, [string]$evt) { return ,@($lines | Where-Object { $_ -match (' ' + [regex]::Escape($evt) + '( |$)') }) }

$allPids = New-Object System.Collections.Generic.List[int]
$live = New-Object System.Collections.Generic.List[object]
function NewSession([int]$fakePid, $probe = $null) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    if ($probe -ne $null) {
        $pd = [Delegate]::CreateDelegate([Func[bool]], $probe, 'Probe')
        $s = $sessionCtorProbe.Invoke(@($fakePid, $del, $pd))
    } else {
        $s = $sessionCtor.Invoke(@($fakePid, $del))
    }
    $live.Add($s)
    return [pscustomobject]@{ Session = $s; Recorder = $rec; Pid = $fakePid }
}
function StartSession($h) { $sessionType.GetMethod('Start').Invoke($h.Session, @()) | Out-Null }
function EndSession($h) { try { $sessionType.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { } }
function TickSession($h) { $sessionType.GetMethod('NotifyTick').Invoke($h.Session, @()) | Out-Null }
function Phase($h) { return $sessionType.GetProperty('Phase', $NPI).GetValue($h.Session).ToString() }
function State($h) { return $sessionType.GetProperty('State', $NPI).GetValue($h.Session).ToString() }
function SessionBool($h, [string]$prop) { return [bool]$sessionType.GetProperty($prop, $NPI).GetValue($h.Session) }
function SessionInt($h, [string]$prop) { return [int]$sessionType.GetProperty($prop, $NPI).GetValue($h.Session) }
function Status($h) { return [string]$sessionType.GetMethod('BuildStatusText').Invoke($h.Session, @()) }
function LiveMonitors() { return [int]$sessionType.GetField('LiveMonitors', $NPS).GetValue($null) }
function NewBridge([int]$fakePid) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($bridgeType)
    $f = [Reflection.BindingFlags]'NonPublic,Instance'
    $bridgeType.GetField('loadQpc', $f).SetValue($b, [Diagnostics.Stopwatch]::GetTimestamp())
    $bridgeType.GetField('loadUtcTicks', $f).SetValue($b, [DateTime]::UtcNow.Ticks)
    $bridgeType.GetField('pid', $f).SetValue($b, $fakePid)
    return $b
}
function LoadBridge($b) { $publishMethod.Invoke($b, @()) | Out-Null }
function DisposeBridge($b) { try { $bridgeType.GetMethod('Dispose').Invoke($b, @()) | Out-Null } catch { } }
function Pump($bridges, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { foreach ($b in $bridges) { $tickMethod.Invoke($b, @([TimeSpan]::Zero)) | Out-Null }; Start-Sleep -Milliseconds 5 }
}
function PumpUntil($bridges, [scriptblock]$cond, [int]$limitMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $limitMs) {
        foreach ($b in $bridges) { $tickMethod.Invoke($b, @([TimeSpan]::Zero)) | Out-Null }
        if (& $cond) { return $sw.ElapsedMilliseconds }
        Start-Sleep -Milliseconds 5
    }
    return -1
}
function Wait([int]$ms) { Start-Sleep -Milliseconds $ms }
function ObjectExists([int]$fakePid, [string]$kind) {
    $h = $null
    $ok = [Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$fakePid.$kind", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$h)
    if ($ok -and $h) { $h.Dispose() }
    return $ok
}
function NoObjects([int]$fakePid) {
    foreach ($k in 'Enabled', 'Stop', 'BridgeAvailable', 'Ready', 'ScenarioReady') { if (ObjectExists $fakePid $k) { return $false } }
    return $true
}
function ManualEvent([int]$fakePid, [string]$kind, [bool]$signalled) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    return (New-Object Threading.EventWaitHandle($signalled, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$fakePid.$kind"))
}
function ConnectedWithBridge([int]$fakePid, $bridge, $session) {
    return (PumpUntil @($bridge) { (Phase $session) -eq 'Connected' } 800)
}
function BytesContain([byte[]]$bytes, [string]$token) {
    $a = [Text.Encoding]::ASCII.GetString($bytes); $u = [Text.Encoding]::Unicode.GetString($bytes); $u2 = [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2))
    return $a.Contains($token) -or $u.Contains($token) -or $u2.Contains($token)
}

# the agreed notice text, UTF-8 base64 (keeps this script ASCII-only)
$expectedNotice = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('VFMgU2NvcmluZ+OBq+OBr0J2ZUVY44GM5b+F6KaB44Gn44GZ44CCDQroqK3lrpog4oaSIOWFpeWKm+ODh+ODkOOCpOOCuSDjgadCdmVFWOOCkuacieWKueOBq+OBl+OAgUJWReOCkuWGjei1t+WLleOBl+OBpuOBj+OBoOOBleOBhOOAgg=='))

try {
    Write-Host '--- M1-01: enabled, 500 ms reached, no Bridge, NO first Tick -> diagnostic log only, no dialog'
    $P = 960001; $lp = NewLog 'M1-01-startup' $P
    $s = NewSession $P
    StartSession $s
    Wait 380
    Check 'M1-01 at 380 ms: StartupWaiting, no notice' (((State $s) -eq 'StartupWaiting') -and ($s.Recorder.Count -eq 0))
    Wait 420
    $log = ReadLog $lp
    Check 'M1-01 after 800 ms with no Tick: the 500 ms is reached (phase BridgeMissingTimedOut) but NO notice, state still StartupWaiting' (((Phase $s) -eq 'BridgeMissingTimedOut') -and ($s.Recorder.Count -eq 0) -and ((State $s) -eq 'StartupWaiting') -and (-not (SessionBool $s 'NoticeShown')))
    Check 'M1-01 the log says TIMEOUT_REACHED kind=startup-log-only noticeArmed=no and has no NOTICE_ line' (((EvtLines $log 'TIMEOUT_REACHED').Count -eq 1) -and ((EvtLines $log 'TIMEOUT_REACHED')[0] -match 'timeoutMs=500') -and ((EvtLines $log 'TIMEOUT_REACHED')[0] -match 'kind=startup-log-only') -and ((EvtLines $log 'TIMEOUT_REACHED')[0] -match 'noticeArmed=no') -and (@($log | Where-Object { $_ -match ' NOTICE_' }).Count -eq 0))
    Wait 1200
    Check 'M1-01 even 2 s later (still no Tick): no notice (a scenario list that lasts for minutes shows nothing)' ($s.Recorder.Count -eq 0)
    EndSession $s

    Write-Host '--- M1-02: BridgeAvailable established before the first Tick -> no notice at the first Tick'
    $P = 960002; $lp = NewLog 'M1-02-bridge-first' $P
    $b = NewBridge $P; LoadBridge $b
    $s = NewSession $P
    StartSession $s
    $ms = ConnectedWithBridge $P $b $s
    TickSession $s
    Pump @($b) 250
    $log = ReadLog $lp
    Check 'M1-02 Connected, first Tick judged Present: no notice, latch still free, state Connected' (($ms -ge 0) -and ($s.Recorder.Count -eq 0) -and (SessionBool $s 'FirstTickJudged') -and (SessionBool $s 'NoticeArmed') -and ((State $s) -eq 'Connected'))
    Check 'M1-02 the log records FIRST_TICK_SEEN and FIRST_TICK_JUDGE bridgeDirect=Present decision=no-notice-bridge-present' (((EvtLines $log 'FIRST_TICK_SEEN').Count -eq 1) -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'bridgeDirect=Present') -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'decision=no-notice-bridge-present'))
    EndSession $s; Pump @($b) 150; DisposeBridge $b

    Write-Host '--- M1-03: first Tick while BridgeAvailable is missing -> ONE notice, immediately (not after 500 ms)'
    $P = 960003; $lp = NewLog 'M1-03-first-tick-missing' $P
    $s = NewSession $P
    StartSession $s
    Wait 100
    Check 'M1-03 100 ms after Enable, before any Tick: nothing' ($s.Recorder.Count -eq 0)
    TickSession $s
    Wait 250
    $log = ReadLog $lp
    Check 'M1-03 the first Tick (well under 500 ms) with the Bridge missing: exactly one notice, text is the unchanged agreed text' (($s.Recorder.Count -eq 1) -and ($s.Recorder.Last -ceq $expectedNotice))
    Check 'M1-03 state UseStarted, latch taken, log: FIRST_TICK_JUDGE decision=request-notice, NOTICE_PRESHOW show, NOTICE_SHOW_CALL' (((State $s) -eq 'UseStarted') -and (SessionBool $s 'NoticeShown') -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'bridgeDirect=Missing') -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'decision=request-notice') -and ((EvtLines $log 'NOTICE_PRESHOW')[0] -match 'decision=show reason=bridge-still-missing') -and ((EvtLines $log 'NOTICE_JUDGE_BEGIN')[0] -match 'trigger=first-use') -and ((EvtLines $log 'NOTICE_SHOW_CALL').Count -eq 1))
    TickSession $s; TickSession $s
    Wait 900
    Check 'M1-03 more Ticks and the 500 ms point: still exactly one notice' ($s.Recorder.Count -eq 1)
    EndSession $s

    Write-Host '--- M1-04: Ready missing but BridgeAvailable present -> no notice (Ready is not used)'
    $P = 960004; $lp = NewLog 'M1-04-ready-missing' $P
    $avl = ManualEvent $P 'BridgeAvailable' $true
    $s = NewSession $P
    StartSession $s
    Wait 100
    TickSession $s
    Wait 800
    Check 'M1-04 BridgeAvailable Present, Ready object never exists: no notice, even past 500 ms; phase WaitingForHandshake' (($s.Recorder.Count -eq 0) -and ((Phase $s) -eq 'WaitingForHandshake') -and (-not (ObjectExists $P 'Ready')) -and ((Status $s) -match 'Ready            : Missing'))
    EndSession $s; $avl.Dispose()

    Write-Host '--- M1-05: bridgeKind unknown (no Bridge assembly or BridgeInfo of any kind) but BridgeAvailable present -> no notice'
    $P = 960005; $lp = NewLog 'M1-05-kind-unknown' $P
    $avl = ManualEvent $P 'BridgeAvailable' $true
    $rdy = ManualEvent $P 'Ready' $false
    $s = NewSession $P
    StartSession $s
    Wait 100
    TickSession $s
    Wait 700
    $cb = [IO.File]::ReadAllBytes($callerPath)
    Check 'M1-05 only the named BridgeAvailable event exists (no BridgeInfo, Ready unsignalled): no notice' (($s.Recorder.Count -eq 0) -and ((Status $s) -match 'BridgeInfo: Unavailable'))
    Check 'M1-05 the Caller DLL has no bridgeKind / loaded-assembly probing at all' ((-not (BytesContain $cb 'bridgeKind')) -and (-not (BytesContain $cb 'GetAssemblies')) -and (-not (BytesContain $cb 'AtsExLegacy')))
    EndSession $s; $avl.Dispose(); $rdy.Dispose()

    Write-Host '--- M1-06: cached BridgeAvailable = Present, direct check = Missing -> notice'
    $P = 960006; $lp = NewLog 'M1-06-cache-present-direct-missing' $P
    $avl = ManualEvent $P 'BridgeAvailable' $true
    $s = NewSession $P
    StartSession $s
    Wait 150
    $cachedBefore = ((Status $s) -match 'BridgeAvailable  : Present')
    $avl.Dispose()    # closed without Reset: the Caller's own cached handle keeps the dead object alive and signalled
    Wait 150
    $cachedStill = ((Status $s) -match 'BridgeAvailable  : Present')
    Check 'M1-06 setup: the cached state still says Present although its owner is gone (so cache and reality differ)' ($cachedBefore -and $cachedStill -and ($s.Recorder.Count -eq 0))
    TickSession $s
    Wait 300
    $log = ReadLog $lp
    Check 'M1-06 first Tick: the direct check finds the event gone -> exactly one notice (the cached Present was NOT trusted)' (($s.Recorder.Count -eq 1) -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'bridgeDirect=Missing bridgeCached=Present'))
    EndSession $s

    Write-Host '--- M1-07: cached BridgeAvailable = Missing, direct check = Present -> no notice'
    $P = 960007; $lp = NewLog 'M1-07-cache-missing-direct-present' $P
    $probe = New-Object ProbeSwitch; $probe.Fallback = $true
    $s = NewSession $P $probe
    StartSession $s
    Wait 150
    Check 'M1-07 setup: no BridgeAvailable object exists, the cached state says Missing' ((-not (ObjectExists $P 'BridgeAvailable')) -and ((Status $s) -match 'BridgeAvailable  : Missing'))
    TickSession $s
    Wait 300
    $log = ReadLog $lp
    Check 'M1-07 first Tick: direct check Present while the cache says Missing -> no notice, latch free' (($s.Recorder.Count -eq 0) -and (SessionBool $s 'NoticeArmed') -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'bridgeDirect=Present bridgeCached=Missing'))
    Wait 600
    Check 'M1-07 and the 500 ms start-up point does not notify either' ($s.Recorder.Count -eq 0)
    EndSession $s
    # real objects: the event appears at the very moment of the first Tick (cache may or may not have caught up): never a notice
    $okRace = $true
    for ($i = 0; $i -lt 8; $i++) {
        $Pr = 960070 + $i
        $sr = NewSession $Pr
        StartSession $sr
        Wait (7 * $i + 3)
        $ev = ManualEvent $Pr 'BridgeAvailable' $true
        TickSession $sr
        Wait 160
        if ($sr.Recorder.Count -ne 0) { $okRace = $false }
        EndSession $sr; $ev.Dispose()
    }
    Check 'M1-07 eight races (BridgeAvailable created at the instant of the first Tick, real objects): never a notice' $okRace

    Write-Host '--- M1-08: notice at the first Tick, then the Bridge appears and vanishes -> no second notice'
    $P = 960008; $lp = NewLog 'M1-08-first-tick-then-loss' $P
    $s = NewSession $P
    StartSession $s
    TickSession $s
    Wait 250
    $b = NewBridge $P; LoadBridge $b
    $ms = ConnectedWithBridge $P $b $s
    DisposeBridge $b
    Wait 900
    Check 'M1-08 notice at the first Tick (1), Bridge connected, Bridge lost for 900 ms: still exactly one notice' (($ms -ge 0) -and ($s.Recorder.Count -eq 1) -and ((Phase $s) -eq 'BridgeMissingTimedOut') -and ((State $s) -eq 'ConnectionLost'))
    EndSession $s

    Write-Host '--- M1-09: connection-lost notice first, then the first Tick -> no duplicate'
    $P = 960009; $lp = NewLog 'M1-09-lost-then-tick' $P
    $b = NewBridge $P; LoadBridge $b
    $s = NewSession $P
    StartSession $s
    $ms = ConnectedWithBridge $P $b $s
    DisposeBridge $b
    Wait 800
    Check 'M1-09 Bridge connected (no Tick yet), then gone 800 ms: the connection-lost notice, once' (($ms -ge 0) -and ($s.Recorder.Count -eq 1) -and ((State $s) -eq 'ConnectionLost'))
    TickSession $s
    Wait 400
    $log = ReadLog $lp
    Check 'M1-09 the first Tick afterwards (Bridge still gone): NO second notice, the judge log says already handled' (($s.Recorder.Count -eq 1) -and (SessionBool $s 'FirstTickJudged') -and ((EvtLines $log 'FIRST_TICK_JUDGE')[0] -match 'decision=no-notice-already-handled') -and ((EvtLines $log 'NOTICE_JUDGE_BEGIN').Count -eq 1))
    EndSession $s

    Write-Host '--- M1-10: first Tick with the Bridge present, later the Bridge is gone for 500 ms -> connection-lost notice once'
    $P = 960010; $lp = NewLog 'M1-10-present-then-lost' $P
    $b = NewBridge $P; LoadBridge $b
    $s = NewSession $P
    StartSession $s
    $ms = ConnectedWithBridge $P $b $s
    TickSession $s
    Pump @($b) 200
    Check 'M1-10 first Tick with the Bridge present: nothing' (($ms -ge 0) -and ($s.Recorder.Count -eq 0) -and (SessionBool $s 'FirstTickJudged'))
    DisposeBridge $b
    Wait 380
    Check 'M1-10 380 ms after the Bridge vanished: still nothing' (($s.Recorder.Count -eq 0) -and ((Phase $s) -eq 'WaitingForBridge'))
    Wait 340
    $log = ReadLog $lp
    Check 'M1-10 after 500 ms: exactly one connection-lost notice (trigger=connection-lost, same text)' (($s.Recorder.Count -eq 1) -and ($s.Recorder.Last -ceq $expectedNotice) -and ((State $s) -eq 'ConnectionLost') -and ((EvtLines $log 'NOTICE_JUDGE_BEGIN')[0] -match 'trigger=connection-lost') -and ((EvtLines $log 'TIMEOUT_REACHED')[0] -match 'kind=connection-lost'))
    EndSession $s

    Write-Host '--- M1-11: Bridge missing for less than 500 ms -> no notice'
    $P = 960011; $lp = NewLog 'M1-11-under500' $P
    $b = NewBridge $P; LoadBridge $b
    $s = NewSession $P
    StartSession $s
    [void](ConnectedWithBridge $P $b $s)
    TickSession $s
    Pump @($b) 120
    DisposeBridge $b
    Wait 250
    $b2 = NewBridge $P; LoadBridge $b2
    $ms = ConnectedWithBridge $P $b2 $s
    Pump @($b2) 800
    Check 'M1-11 Bridge gone for about 250 ms, then back: no notice, Connected again' (($ms -ge 0) -and ($s.Recorder.Count -eq 0) -and ((Phase $s) -eq 'Connected') -and (SessionBool $s 'NoticeArmed'))
    EndSession $s; Pump @($b2) 150; DisposeBridge $b2

    Write-Host '--- M1-12: the Bridge is back just before the dialog would be shown -> suppressed, latch stays free'
    $P = 960012; $lp = NewLog 'M1-12-recheck-first-use' $P
    $probe = New-Object ProbeSwitch; $probe.Script = [bool[]]@($false); $probe.Fallback = $true   # judge: Missing, every later look: Present
    $s = NewSession $P $probe
    StartSession $s
    TickSession $s
    Wait 350
    $log = ReadLog $lp
    Check 'M1-12 first-use path: judged Missing, re-check right before showing finds it Present -> NOTICE_SUPPRESSED, no dialog, latch free' (($s.Recorder.Count -eq 0) -and (SessionBool $s 'NoticeArmed') -and ((EvtLines $log 'NOTICE_PRESHOW')[0] -match 'decision=suppress reason=bridge-present-at-recheck') -and ((EvtLines $log 'NOTICE_SUPPRESSED').Count -eq 1))
    EndSession $s
    $P = 960013; $lp = NewLog 'M1-12-recheck-lost' $P
    $avl = ManualEvent $P 'BridgeAvailable' $true
    $rdy = ManualEvent $P 'Ready' $true
    $probe2 = New-Object ProbeSwitch; $probe2.Fallback = $true
    $s = NewSession $P $probe2
    StartSession $s
    Wait 150
    $rdy.Reset() | Out-Null; $avl.Reset() | Out-Null
    Wait 800
    $log = ReadLog $lp
    Check 'M1-12 connection-lost path: lost for 500 ms, but the direct re-check before showing says Present -> suppressed, no dialog' (($s.Recorder.Count -eq 0) -and ((EvtLines $log 'NOTICE_PRESHOW')[0] -match 'decision=suppress reason=bridge-present-at-recheck') -and (SessionBool $s 'NoticeArmed'))
    EndSession $s; $avl.Dispose(); $rdy.Dispose()

    Write-Host '--- M1-13/14/15: TS Scoring OFF -> ON : every Caller instance has its own notice cycle'
    $P = 960014; $lp = NewLog 'M1-13-off-on' $P
    $sa = NewSession $P
    StartSession $sa
    TickSession $sa
    Wait 250
    Check 'M1-13 instance A: first Tick, no Bridge -> its one notice' (($sa.Recorder.Count -eq 1) -and (SessionBool $sa 'NoticeShown'))
    EndSession $sa
    Wait 150
    $b = NewBridge $P; LoadBridge $b
    $sb = NewSession $P
    Check 'M1-13 a NEW instance starts with a free latch, no Tick seen, StartupWaiting' ((SessionBool $sb 'NoticeArmed') -and (-not (SessionBool $sb 'NoticeShown')) -and (-not (SessionBool $sb 'FirstTickSeen')) -and ((State $sb) -eq 'StartupWaiting'))
    StartSession $sb
    $ms = ConnectedWithBridge $P $b $sb
    TickSession $sb
    Pump @($b) 300
    Check 'M1-14 new instance B, first Tick with BridgeAvailable present: no notice' (($ms -ge 0) -and ($sb.Recorder.Count -eq 0) -and ($sa.Recorder.Count -eq 1))
    EndSession $sb; Pump @($b) 150; DisposeBridge $b
    Wait 150
    $sc = NewSession $P
    StartSession $sc
    TickSession $sc
    Wait 250
    Check 'M1-15 new instance C, first Tick with the Bridge missing: its own one notice (instance A already had one: a new cycle may notify once again)' (($sc.Recorder.Count -eq 1) -and ($sa.Recorder.Count -eq 1) -and ($sb.Recorder.Count -eq 0))
    EndSession $sc

    Write-Host '--- M1-16: BVE shutting down: short Bridge loss followed by Dispose -> no false notice'
    $P = 960016; $lp = NewLog 'M1-16-shutdown' $P
    $b = NewBridge $P; LoadBridge $b
    $s = NewSession $P
    StartSession $s
    [void](ConnectedWithBridge $P $b $s)
    TickSession $s
    Pump @($b) 120
    DisposeBridge $b
    Wait 120
    EndSession $s
    Wait 1000
    Check 'M1-16 Bridge vanishes, Caller disposed 120 ms later: no notice, not even later; monitor ended, objects gone' (($s.Recorder.Count -eq 0) -and ((Phase $s) -eq 'Disposed') -and (-not (SessionBool $s 'MonitorAlive')) -and (NoObjects $P))
    $P = 960017; $lp = NewLog 'M1-16-shutdown-tick-after' $P
    $b = NewBridge $P; LoadBridge $b
    $s = NewSession $P
    StartSession $s
    [void](ConnectedWithBridge $P $b $s)
    DisposeBridge $b
    Wait 100
    EndSession $s
    TickSession $s     # a Tick that still arrives after Dispose (BVE is closing)
    Wait 800
    Check 'M1-16 a late Tick after Dispose does nothing (no notice, no judge)' (($s.Recorder.Count -eq 0) -and (-not (SessionBool $s 'FirstTickJudged')) -and (NoObjects $P))

    Write-Host '--- M1-17: the Tick method does nothing but raise a flag'
    $tickSrc = [IO.File]::ReadAllText((Join-Path $Root 'Caller\src\TsScoringCallerInputDevice.cs'))
    $m = [regex]::Match($tickSrc, 'public void Tick\(\)\s*\{(?<b>[\s\S]*?)\n        \}')
    $devTickBody = [regex]::Replace($m.Groups['b'].Value, '//.*', '')
    $hsSrc = [IO.File]::ReadAllText((Join-Path $Root 'Caller\src\HandshakeSession.cs'))
    $m2 = [regex]::Match($hsSrc, 'public void NotifyTick\(\)\s*\{(?<b>[\s\S]*?)\n        \}')
    $notifyBody = [regex]::Replace($m2.Groups['b'].Value, '//.*', '')
    $bad = 'Obs\(|ObsA\(|ObservationLog|MessageBox|showNotice|File|Stream|Directory|lock\s*\(|Monitor\.|Sleep|WaitOne|Wait\(|Join|Thread|Task|Invoke|Open|EventWaitHandle|Registry|Process|Console|Debug|Trace'
    Check 'M1-17 Tick() body only calls session.NotifyTick() (inside try/catch): no I/O, log, dialog, lock, wait, thread' (($m.Success) -and ($devTickBody -match 'session\.NotifyTick\(\)') -and ($devTickBody -notmatch $bad))
    Check 'M1-17 NotifyTick() body: a flag test, one timestamp, one volatile write; no I/O, log, dialog, lock, wait, thread, kernel object' (($m2.Success) -and ($notifyBody -match 'Stopwatch\.GetTimestamp\(\)') -and ($notifyBody -match 'tickSeen = true') -and ($notifyBody -notmatch $bad))
    $P = 960018; $lp = NewLog 'M1-17-tick-cost' $P
    $dev = [Activator]::CreateInstance($deviceType)
    $devTick = [Delegate]::CreateDelegate([Action], $dev, 'Tick')
    $linesBefore = (ReadLog $lp).Count
    $thBefore = [Diagnostics.Process]::GetCurrentProcess().Threads.Count
    $us = [TickHammer]::Run($devTick, 1000000)
    $thAfter = [Diagnostics.Process]::GetCurrentProcess().Threads.Count
    $linesAfter = (ReadLog $lp).Count
    $sessField = $deviceType.GetField('session', [Reflection.BindingFlags]'NonPublic,Instance')
    $devSession = $sessField.GetValue($dev)
    Check ("M1-17 one million real Tick() calls: {0} ms in total, flag raised, log file untouched, no thread created, MonitorAlive false" -f [math]::Round($us / 1000.0, 1)) (($us -lt 1000000) -and ([bool]$sessionType.GetProperty('FirstTickSeen', $NPI).GetValue($devSession)) -and ($linesAfter -eq $linesBefore) -and ($thAfter -le $thBefore + 4) -and (-not [bool]$sessionType.GetProperty('MonitorAlive', $NPI).GetValue($devSession)))
    try { $dev.Dispose() } catch { }

    Write-Host '--- M1-30: at most ONE notice per Caller instance, however the Bridge comes and goes'
    $P = 960030; $lp = NewLog 'M1-30-max-one' $P
    $s = NewSession $P
    StartSession $s
    TickSession $s
    Wait 250
    $bs = @()
    for ($i = 1; $i -le 3; $i++) {
        $bx = NewBridge $P; LoadBridge $bx
        [void](ConnectedWithBridge $P $bx $s)
        DisposeBridge $bx
        Wait 700    # a full absence stretch each time (> 500 ms)
    }
    Check 'M1-30 first-use notice, then three connect/lose cycles with 700 ms absences: exactly one notice in total' (($s.Recorder.Count -eq 1) -and ((SessionInt $s 'BridgeLostCount') -eq 3) -and (SessionBool $s 'NoticeShown'))
    EndSession $s
    $P = 960031; $lp = NewLog 'M1-30-max-one-lost-first' $P
    $s = NewSession $P
    StartSession $s
    for ($i = 1; $i -le 2; $i++) {
        $bx = NewBridge $P; LoadBridge $bx
        [void](ConnectedWithBridge $P $bx $s)
        DisposeBridge $bx
        Wait 700
    }
    TickSession $s
    Wait 300
    Check 'M1-30 connection-lost first, a second absence stretch and then the first Tick: still exactly one notice' (($s.Recorder.Count -eq 1) -and ((SessionInt $s 'BridgeLostCount') -eq 2))
    EndSession $s
}
finally {
    foreach ($h in $live) { try { $sessionType.GetMethod('End').Invoke($h, @()) | Out-Null } catch { } }
}

Start-Sleep -Milliseconds 300
$leftovers = @($allPids | Where-Object { -not (NoObjects $_) })
Check 'Final: no named object of any test pid is left' ($leftovers.Count -eq 0)
Check 'Final: no monitor thread alive' ((LiveMonitors) -eq 0)

# =====================================================================================================================
# static / contract checks (nothing is executed)
Write-Host '--- static: constants, texts, artifacts'
function RunGit([string[]]$gitArgs) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.Arguments = (($gitArgs | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $p = [Diagnostics.Process]::Start($psi)
    $o = $p.StandardOutput.ReadToEnd()
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw ('git failed: ' + ($gitArgs -join ' ')) }
    return $o
}
$prefix = (RunGit @('rev-parse', '--show-prefix')).Trim()
function BaseText([string]$rel) { return ((RunGit @('show', ($Baseline + ':' + $prefix + $rel.Replace('\', '/')))) -replace "`r`n", "`n") }
function WorkText([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $Root $rel))) -replace "`r`n", "`n") }

$hp = WorkText 'Shared\HandshakeProtocol.cs'
$timing = $callerAsm.GetType($NS + 'HandshakeTiming')
Check 'M1-18 BridgeMissingTimeoutMs is 500 (value in the built DLL and in the source), TargetBridgeAvailableMs 500, CallerPollMs 20' (([int]$timing.GetField('BridgeMissingTimeoutMs').GetValue($null) -eq 500) -and ($hp -match 'BridgeMissingTimeoutMs = 500;') -and ($hp -match 'TargetBridgeAvailableMs = 500;') -and ($hp -match 'CallerPollMs = 20;') -and ((BaseText 'Shared\HandshakeProtocol.cs') -ceq $hp))
$noticeField = $sessionType.GetField('NoticeText', $NPS).GetRawConstantValue()
Check 'M1-19 MessageBox text is the unchanged agreed text (two lines, DLL constant and source identical to the baseline)' (($noticeField -ceq $expectedNotice) -and ($noticeField -notmatch 'TSScoringPlugin'))
$titleOk = ([string]$sessionType.GetField('ProductDisplayName', $NPS).GetRawConstantValue() -ceq 'TS Scoring')
Check 'M1-20 MessageBox title is exactly TS Scoring' $titleOk
$hsNow = WorkText 'Caller\src\HandshakeSession.cs'
$hsBase = BaseText 'Caller\src\HandshakeSession.cs'
$mbPattern = '^\s*(internal const string (NoticeText|ProductDisplayName|ProviderName)|private const uint MB_|\[DllImport\("user32\.dll", EntryPoint = "MessageBoxW"|private static extern int MessageBoxW|"TS Scoring|"[^"]*(BveEX|BveEx)[^"]*"|MessageBoxW\()'
$mbNow = @(($hsNow -split "`n") | Where-Object { $_ -match $mbPattern })
$mbBase = @(($hsBase -split "`n") | Where-Object { $_ -match $mbPattern })
Check ('M1-19/20 every MessageBox line (notice text, title, flags, P/Invoke, the call itself) is identical to the baseline commit (' + $mbBase.Count + ' lines)') (($mbBase.Count -ge 8) -and (($mbNow -join "`n") -ceq ($mbBase -join "`n")) -and ($hsNow -match 'MessageBoxW\(IntPtr\.Zero, text, ProductDisplayName, MB_OK \| MB_ICONINFORMATION \| MB_SETFOREGROUND \| MB_TOPMOST\)') -and ($hsNow -match 'MB_OK = 0x00000000') -and ($hsNow -match 'MB_ICONINFORMATION = 0x00000040') -and ($hsNow -match 'MB_SETFOREGROUND = 0x00010000') -and ($hsNow -match 'MB_TOPMOST = 0x00040000'))

$curSha = (Get-FileHash (Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll') -Algorithm SHA256).Hash
$curOutSha = (Get-FileHash (Join-Path $Root 'Bridge\out\TSScoringPlugin.BveEx.Bridge.Prototype.dll') -Algorithm SHA256).Hash
$legSha = (Get-FileHash (Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll') -Algorithm SHA256).Hash
Check 'M1-21 Current Bridge DLL (dist and out) and Legacy Bridge DLL are byte-identical to the formal artifacts (SHA-256)' (($curSha -eq '247F67243253E5AD3C98D1B04BF8C4C8F19399C8B91317A7744D5E12A901A5AA') -and ($curOutSha -eq $curSha) -and ($legSha -eq 'C2883E400B1DCC1E0720392B90EAAED7CD770F6EB8DC6CF4CBA06FF80598EB48'))
$top = (RunGit @('rev-parse', '--show-toplevel')).Trim()
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline)) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
Check 'M1-21 no source of the Current Bridge, the Legacy Bridge or the shared protocol / log differs from the baseline' (@($touched | Where-Object { $_ -like ($prefix + 'Bridge/*') -or $_ -like ($prefix + 'Shared/*') }).Count -eq 0)
$scenarioFiles = 'Bridge\src\ScenarioReadyTracker.cs', 'Bridge\src\ScenarioReadyPublisher.cs', 'Bridge\src\ScenarioObserver.cs', 'Bridge\src\TsScoringBridgePrototype.cs', 'Shared\HandshakeProtocol.cs', 'Shared\ObservationLog.cs'
$scenarioSame = @($scenarioFiles | Where-Object { (BaseText $_) -cne (WorkText $_) })
Check 'M1-22 ScenarioReady contract unchanged: tracker, publisher, observer, Bridge entry and protocol sources are identical to the baseline' ($scenarioSame.Count -eq 0)
function MethodText([string]$text, [string]$name) { $mm = [regex]::Match($text, '(?ms)^        (private|internal|public) [^\n]*\b' + $name + '\([^\n]*\)\s*\n        \{.*?\n        \}\n'); return $mm.Value }
function CodeOf([string]$s) { return [regex]::Replace($s, '//[^\n]*', '') }
$srMethods = 'ObserveScenarioLocked', 'OpenScenarioObjectsLocked', 'ReleaseScenarioObjectsLocked'
$srSame = @($srMethods | Where-Object { $b0 = MethodText $hsBase $_; ($b0.Length -gt 200) -and ($b0 -ceq (MethodText $hsNow $_)) })
Check 'M1-23 ScenarioGeneration / ScenarioReady reading in the Caller (ObserveScenarioLocked, OpenScenarioObjectsLocked, ReleaseScenarioObjectsLocked) is byte-identical to the baseline, and nothing in the notice code reads them' (($srSame.Count -eq 3) -and ((CodeOf (MethodText $hsNow 'JudgeFirstTickLocked')) -notmatch 'scenario|Scenario') -and ((CodeOf (MethodText $hsNow 'ShowNoticeIfStillNeeded')) -notmatch 'scenario|Scenario') -and ((CodeOf (MethodText $hsNow 'CheckBridgeTimeoutLocked')) -notmatch 'scenario|Scenario'))
Check 'M1-24 no Python file and no UDP / HUD / scoring / updater file is touched' (@($touched | Where-Object { $_ -match '\.py$|menu_ui|config\.py|utils\.py|Class1\.cs|AtsLoggerPlugin\.cs|installer|\.iss$|\.vcxproj|\.slnx$' }).Count -eq 0)
$proj = [IO.File]::ReadAllText((Join-Path $Root 'Caller\TSScoringPlugin.Caller.InputDevice.csproj'))
Check 'M1-25 no observation source in the product: no M0Observation.cs in the tree, the project, or the Caller DLL' ((-not (Test-Path (Join-Path $Root 'Caller\src\M0Observation.cs'))) -and ($proj -notmatch 'M0') -and (-not (BytesContain ([IO.File]::ReadAllBytes($callerPath)) 'M0Observ')) -and (@(Get-ChildItem $Root -Recurse -Include *.cs | Where-Object { $_.FullName -notlike '*\obj\*' -and ([IO.File]::ReadAllText($_.FullName) -match 'M0Observ|class M0') }).Count -eq 0))
$cbytes = [IO.File]::ReadAllBytes($callerPath)
Check 'M1-26 the Caller DLL contains none of the observation-build identifiers (fixed M0 log name, Tick-rate / SetAxisRanges aggregation, NOTICE_WOULD_SHOW, CALLER_FIRST_TICK)' ((@('TSScoring-PhaseM0', 'PhaseM0', 'Caller-Observation', 'NOTICE_WOULD_SHOW', 'CALLER_FIRST_TICK', 'SETAXIS', 'OBSERVATION build', 'diagnostic, not the beta') | Where-Object { BytesContain $cbytes $_ }).Count -eq 0)
$vi = (Get-Item $callerPath).VersionInfo
$casm = $callerAsm
Check 'M1-28 provider Coruge-to (company, copyright, ProviderName constant); product TS Scoring; version 0.7.0.0; description names Phase M1 and no observation wording' (($vi.CompanyName -eq 'Coruge-to') -and ($vi.LegalCopyright -match 'Coruge-to') -and ($vi.ProductName -eq 'TS Scoring') -and ([string]$sessionType.GetField('ProviderName', $NPS).GetRawConstantValue() -ceq 'Coruge-to') -and ($vi.FileVersion -eq '0.7.0.0') -and ($casm.GetName().Version.ToString() -eq '0.7.0.0') -and ($vi.Comments -match 'Phase M1') -and ($vi.Comments -notmatch '(?i)observation|diagnostic'))
Check 'M1-29 no PDB anywhere in the tree or in dist / out, and dist holds exactly the two DLLs' ((@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0) -and ((@(Get-ChildItem (Join-Path $Root 'dist') -File | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'TSScoringPlugin.BveEx.Bridge.Prototype.dll,TSScoringPlugin.Caller.InputDevice.dll'))
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$privFiles = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs) + @(Get-Item $callerPath) + @(Get-Item (Join-Path $Root 'Caller\TSScoringPlugin.Caller.InputDevice.csproj'))
$privHits = 0
foreach ($f in $privFiles) {
    $bytes = [IO.File]::ReadAllBytes($f.FullName)
    $ascii = [Text.Encoding]::ASCII.GetString($bytes); $utf16 = [Text.Encoding]::Unicode.GetString($bytes); $utf8 = [Text.Encoding]::UTF8.GetString($bytes)
    foreach ($tok in $forbidden) { foreach ($text in @($ascii, $utf16, $utf8)) { $privHits += ([regex]::Matches($text, [regex]::Escape($tok), 'IgnoreCase')).Count } }
    foreach ($text in @($ascii, $utf16, $utf8)) { $privHits += ([regex]::Matches($text, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count }
}
# this test file itself names the forbidden tokens in its own list, so it is scanned for the runtime names and e-mail addresses only
$selfText = [IO.File]::ReadAllText((Join-Path $Root 'Tests\Test-DependencyNoticeM1.ps1'))
$selfHits = ([regex]::Matches($selfText, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count
foreach ($rn in $runtimeNames) { $selfHits += ([regex]::Matches($selfText, [regex]::Escape($rn), 'IgnoreCase')).Count }
Check ('M1-27 no user name, machine name, drive path, repository name or e-mail in the Caller sources, project and DLL (' + $privFiles.Count + ' files, matches=' + $privHits + '), and none of the runtime names or e-mail in this test (matches=' + $selfHits + ')') (($privHits -eq 0) -and ($selfHits -eq 0))

# repository scope: only the Caller, its tests / verification scripts and its document may differ from the baseline commit
$m1Allowed = @(
    'Caller/src/AssemblyInfo.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/TsScoringCallerInputDevice.cs', 'Caller/TSScoringPlugin.Caller.InputDevice.csproj',
    'Tests/Test-HandshakeLogic.ps1', 'Tests/Test-ObservationC1.ps1', 'Tests/Test-DependencyNoticeM1.ps1',
    'Tools/Verify-PhaseC3.ps1', 'Tools/Verify-PhaseL1.ps1', 'Docs/Handshake-PhaseM1-DependencyNotice.md'
) | ForEach-Object { $prefix + $_ }
$m1Outside = @($touched | Where-Object { $_ -notin $m1Allowed })
Check ('M1-31 only the Phase M1 Caller / test / verification / document files differ from the baseline commit (' + $touched.Count + ' files)') (($m1Outside.Count -eq 0) -and ($touched.Count -ge 8))
if ($m1Outside.Count -gt 0) { $m1Outside | ForEach-Object { '   outside scope: ' + $_ } }
$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
