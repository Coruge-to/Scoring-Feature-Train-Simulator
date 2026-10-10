# PHASE C3 - offline tests of the ScenarioReady life-cycle (tracker, publisher, state block, Current adapter pieces, Caller reader).
# No BVE, no BveEX runtime, no Python, no UDP, no hooks. The real built DLLs are loaded from memory. Every observation log goes to a private
# file under logs\c3-tests (NEVER to the fixed Downloads file). Fake process ids and a notice test double are used (no MessageBox).
# The BveEX event types cannot be built offline, so the tests call the tracker / bridge entry points that the BveEX handlers call.
# This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

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
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')))
$bridgeAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')))
$NS = 'TSScoringPlugin.Handshake.'
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$bridgeType = $bridgeAsm.GetType($NS + 'TsScoringBridgePrototype')
$trkType = $bridgeAsm.GetType($NS + 'ScenarioReadyTracker')
$pubType = $bridgeAsm.GetType($NS + 'ScenarioReadyPublisher')
$snapType = $bridgeAsm.GetType($NS + 'BveSnapshot')
$builderType = $bridgeAsm.GetType($NS + 'BveSnapshotBuilder')
$stateType = $bridgeAsm.GetType($NS + 'ScenarioState')
$stateTypeCaller = $callerAsm.GetType($NS + 'ScenarioState')
$ruleType = $bridgeAsm.GetType($NS + 'ScenarioGenerationRule')
$protoType = $bridgeAsm.GetType($NS + 'HandshakeProtocol')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $bridgeAsm.GetType($NS + 'ObservationLog')
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$tickMethod = $bridgeType.GetMethod('Tick')
$publishMethod = $bridgeType.GetMethod('PublishAvailability', $NPI)
$beginSrMethod = $bridgeType.GetMethod('BeginScenarioReady', $NPI)
$trackerField = $bridgeType.GetField('tracker', $NPI)
$funcSnap = [Func``1].MakeGenericType($snapType)
$funcObj = [Func``1].MakeGenericType([object])
$funcObjObj = [Func``2].MakeGenericType([object], [object])
$funcObjDouble = [Func``2].MakeGenericType([object], [double])

$testDir = Join-Path $Root 'logs\c3-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
$allPids = New-Object System.Collections.Generic.List[int]
function RegPid([int]$p) { if (-not $allPids.Contains($p)) { $allPids.Add($p) } }
$allLogs = New-Object System.Collections.Generic.List[string]

# ---- logging helpers (Caller / Bridge observation log -> private file) ----
function LogCfg($type, [string]$path, [int]$fakePid) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]0)
}
function LogCfgBoth([string]$path, [int]$fakePid) { LogCfg $cLog $path $fakePid; LogCfg $bLog $path $fakePid }
function NewLogPath([string]$name) { $p = Join-Path $testDir ($name + '.log'); $allLogs.Add($p); return $p }
function ReadLog([string]$path) { if (Test-Path -LiteralPath $path) { return @(Get-Content -LiteralPath $path -Encoding UTF8) } else { return @() } }
function EvtLines([string[]]$lines, [string]$evt) { return ,@($lines | Where-Object { $_ -match (' ' + [regex]::Escape($evt) + '( |$)') }) }
function InOrder([string[]]$lines, [string[]]$evts) {
    $last = -1
    foreach ($e in $evts) {
        $idx = -1
        for ($i = $last + 1; $i -lt $lines.Count; $i++) { if ($lines[$i] -match (' ' + [regex]::Escape($e) + '( |$)')) { $idx = $i; break } }
        if ($idx -lt 0) { return $false }
        $last = $idx
    }
    return $true
}

# ---- snapshot helpers ----
function Snap([int]$created = 1, [object]$fail = $null, [bool]$sc = $true, [bool]$tm = $true, [bool]$vlr = $true, [bool]$fin = $true, [bool]$veh = $true) {
    $o = [Activator]::CreateInstance($snapType)
    $f = [Reflection.BindingFlags]'Public,Instance'
    $snapType.GetField('IsScenarioCreated', $f).SetValue($o, $created)
    $snapType.GetField('ScenarioRef', $f).SetValue($o, $sc)
    $snapType.GetField('TimeManagerRef', $f).SetValue($o, $tm)
    $snapType.GetField('VehicleLocationRef', $f).SetValue($o, $vlr)
    $snapType.GetField('VehicleLocationFinite', $f).SetValue($o, $fin)
    $snapType.GetField('VehicleRef', $f).SetValue($o, $veh)
    $snapType.GetField('Failure', $f).SetValue($o, $fail)
    return $o
}
function GoodSnap() { return Snap 1 $null }

# ---- the outside world as a consumer sees it: open by name, read, close at once (never keeps an object alive) ----
function Outside([int]$p) {
    $e = $null
    $exists = [Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$p.ScenarioReady", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$e)
    $set = $false
    if ($exists -and $e) { $set = $e.WaitOne(0); $e.Dispose() }
    $a = @($p, $null)
    $ok = [bool]$stateType.GetMethod('TryRead').Invoke($null, $a)
    $gen = -1; $rdy = -1
    if ($ok) { $gen = [int]$stateType.GetField('ScenarioGeneration').GetValue($a[1]); $rdy = [int]$stateType.GetField('IsScenarioReady').GetValue($a[1]) }
    return [pscustomobject]@{ EventExists = [bool]$exists; EventSet = $set; StateValid = $ok; Gen = $gen; Ready = $rdy }
}
function OutsideNone([int]$p) { $o = Outside $p; return (-not $o.EventExists) -and (-not $o.StateValid) }
function OutsideIs([int]$p, [int]$gen, [int]$ready) { $o = Outside $p; return $o.EventExists -and $o.StateValid -and ($o.Gen -eq $gen) -and ($o.Ready -eq $ready) -and ($o.EventSet -eq ($ready -eq 1)) }

# ---- tracker harness: scriptblock delegates, controllable world ----
$script:W = @{}
function NewTracker([int]$p) {
    RegPid $p
    $w = @{ Pid = $p; Lines = (New-Object System.Collections.Generic.List[string]); Snap = (GoodSnap); Up = $true; Now = 1000; Reads = 0; ReadThrows = $false; Probe = $null }
    $script:W = $w
    $log = [Action[string, string, string]] { param($t, $e, $d) $script:W.Lines.Add("$t|$e|$d"); if ($script:W.Probe) { & $script:W.Probe $e } }
    $rd = ({ $script:W.Reads++; if ($script:W.ReadThrows) { throw (New-Object System.IO.IOException 'boom') }; $script:W.Snap }) -as $funcSnap
    $up = [Func[bool]] { [bool]$script:W.Up }
    $nw = [Func[long]] { [long]$script:W.Now }
    $pub = $pubType.GetConstructors($NPI)[0].Invoke(@($p))
    $trk = $trkType.GetConstructors($NPI)[0].Invoke(@($log, $rd, $up, $pub, $nw))
    $w.Trk = $trk
    return $w
}
function T($w, [string]$m) { $trkType.GetMethod($m, $NPI).Invoke($w.Trk, @()) | Out-Null }
function TOpen($w) { T $w 'OnScenarioOpened' }
function TCreated($w) { T $w 'OnScenarioCreated' }
function TClosed($w) { T $w 'OnScenarioClosed' }
function TTick($w, [int]$n = 1) { for ($i = 0; $i -lt $n; $i++) { T $w 'OnTick' } }
function TPost($w) { T $w 'OnPostTick' }
function TDispose($w) { T $w 'OnDispose' }
function TLost($w, [string]$why = 'caller-stopped-or-disabled') { $trkType.GetMethod('OnHandshakeLost', $NPI).Invoke($w.Trk, @($why)) | Out-Null }
function TProp($w, [string]$n) { return $trkType.GetProperty($n, $NPI).GetValue($w.Trk) }
function Lvl($w) { return [bool](TProp $w 'IsScenarioReady') }
function Gen($w) { return [int](TProp $w 'ScenarioGeneration') }
function WLines($w, [string]$evt) { return ,@($w.Lines | Where-Object { $_.Split('|')[1] -eq $evt }) }
function WCount($w, [string]$evt) { return (WLines $w $evt).Count }
function WOrder($w, [string[]]$evts) {
    $last = -1
    foreach ($e in $evts) {
        $idx = -1
        for ($i = $last + 1; $i -lt $w.Lines.Count; $i++) { if ($w.Lines[$i].Split('|')[1] -eq $e) { $idx = $i; break } }
        if ($idx -lt 0) { return $false }
        $last = $idx
    }
    return $true
}
function Ready1($w) { TOpen $w; TCreated $w; TTick $w }       # a normal load up to the first Tick (E) with everything good

# ---- bridge / session helpers (same technique as the Phase B / C1 suites) ----
function NewSession([int]$fakePid) {
    RegPid $fakePid
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    return [pscustomobject]@{ Session = $sessionCtor.Invoke(@($fakePid, $del)); Recorder = $rec; Pid = $fakePid }
}
function StartSession($h) { $sessionType.GetMethod('Start').Invoke($h.Session, @()) | Out-Null }
function EndSession($h) { try { $sessionType.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { } }
function Phase($h) { return $sessionType.GetProperty('Phase', $NPI).GetValue($h.Session).ToString() }
function SProp($h, [string]$n) { return $sessionType.GetProperty($n, $NPI).GetValue($h.Session) }
function NewBridge([int]$fakePid) {
    RegPid $fakePid
    $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($bridgeType)
    $f = [Reflection.BindingFlags]'NonPublic,Instance'
    $bridgeType.GetField('loadQpc', $f).SetValue($b, [Diagnostics.Stopwatch]::GetTimestamp())
    $bridgeType.GetField('loadUtcTicks', $f).SetValue($b, [DateTime]::UtcNow.Ticks)
    $bridgeType.GetField('pid', $f).SetValue($b, $fakePid)
    return $b
}
function LoadBridge($b) { $publishMethod.Invoke($b, @()) | Out-Null }
function DisposeBridge($b) { try { $bridgeType.GetMethod('Dispose').Invoke($b, @()) | Out-Null } catch { } }
function BTick($b) { $tickMethod.Invoke($b, @([TimeSpan]::Zero)) | Out-Null }
function Pump($bridges, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { foreach ($b in $bridges) { BTick $b }; Start-Sleep -Milliseconds 5 }
}
function PumpUntil($bridges, [scriptblock]$cond, [int]$limitMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $limitMs) {
        foreach ($b in $bridges) { BTick $b }
        if (& $cond) { return $sw.ElapsedMilliseconds }
        Start-Sleep -Milliseconds 5
    }
    return -1
}
function BTracker($b) { return $trackerField.GetValue($b) }
function BT($b, [string]$m) { $trkType.GetMethod($m, $NPI).Invoke((BTracker $b), @()) | Out-Null }
$script:BSnap = @{}
function BeginSr($b, [int]$p) {
    $script:BSnap[$p] = (GoodSnap)
    $rd = ([scriptblock]::Create('$script:BSnap[' + $p + ']')) -as $funcSnap
    $beginSrMethod.Invoke($b, @($rd, $null)) | Out-Null
}
function Wait([int]$ms) { Start-Sleep -Milliseconds $ms }
function AnyObject([int]$p) {
    foreach ($k in 'Enabled', 'Stop', 'BridgeAvailable', 'Ready', 'ScenarioReady') {
        $h = $null
        if ([Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$p.$k", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$h)) { if ($h) { $h.Dispose() }; return $true }
    }
    foreach ($m in 'BridgeInfo', 'ScenarioState') {
        try { $x = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting("Local\TSScoringPlugin.v1.$p.$m", [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read); $x.Dispose(); return $true } catch { }
    }
    return $false
}

try {
    # =================================================================================================================
    Write-Host '--- N: names, state block, generation rule'
    $nm = $protoType.GetMethod('ScenarioReadyName').Invoke($null, @(4242))
    $ns = $protoType.GetMethod('ScenarioStateName').Invoke($null, @(4242))
    Check 'N1 names carry the BVE PID and follow the Phase B scheme' (($nm -ceq 'Local\TSScoringPlugin.v1.4242.ScenarioReady') -and ($ns -ceq 'Local\TSScoringPlugin.v1.4242.ScenarioState') -and ($protoType.GetMethod('ReadyName').Invoke($null, @(4242)) -ceq 'Local\TSScoringPlugin.v1.4242.Ready'))
    Check 'N2 names differ for two PIDs' (($protoType.GetMethod('ScenarioReadyName').Invoke($null, @(4243)) -ne $nm) -and ($protoType.GetMethod('ScenarioStateName').Invoke($null, @(4243)) -ne $ns))
    $next = $ruleType.GetMethod('Next')
    Check 'N3 generation rule: 0 -> 1, +1 each step' ((($next.Invoke($null, @(0))) -eq 1) -and (($next.Invoke($null, @(1))) -eq 2) -and (($next.Invoke($null, @(1000))) -eq 1001))
    Check 'N4 generation overflow: int.MaxValue wraps to 1 (never 0, never negative); a negative input is treated as nothing opened yet' ((($next.Invoke($null, @([int]::MaxValue))) -eq 1) -and (($next.Invoke($null, @([int]::MaxValue - 1))) -eq [int]::MaxValue) -and (($next.Invoke($null, @(-5))) -eq 1))
    $sz = [int]$stateType.GetField('Size').GetRawConstantValue()
    Check 'N5 state block is 64 bytes and holds ProtocolVersion, BveProcessId, ScenarioGeneration, IsScenarioReady, Sequence, Check and (Phase SI-A6) the load marker LoadMagic, LoadInfo, LoadCheck only' (($sz -eq 64) -and ((@($stateType.GetFields([Reflection.BindingFlags]'Public,Instance') | ForEach-Object { $_.Name }) -join ',') -eq 'ProtocolVersion,BveProcessId,ScenarioGeneration,IsScenarioReady,Sequence,Check,LoadMagic,LoadInfo,LoadCheck'))

    # state block write / read / corruption
    $pB = 960001; RegPid $pB
    $mmf = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew("Local\TSScoringPlugin.v1.$pB.ScenarioState", 64)
    $view = $mmf.CreateViewAccessor(0, 64)
    $write = $stateType.GetMethod('Write'); $tryView = $stateType.GetMethod('TryReadView')
    $argsR = @($view, $pB, $null)
    Check 'N6 a zeroed (never written) block reads as invalid' (-not [bool]$tryView.Invoke($null, $argsR))
    $write.Invoke($null, @($view, $pB, 7, $true)) | Out-Null
    $argsR = @($view, $pB, $null); $okR = [bool]$tryView.Invoke($null, $argsR)
    $st = $argsR[2]
    Check 'N7 written block reads back: version 1, PID, generation 7, ready 1, even sequence' ($okR -and ($stateType.GetField('ProtocolVersion').GetValue($st) -eq 1) -and ($stateType.GetField('BveProcessId').GetValue($st) -eq $pB) -and ($stateType.GetField('ScenarioGeneration').GetValue($st) -eq 7) -and ($stateType.GetField('IsScenarioReady').GetValue($st) -eq 1) -and (($stateType.GetField('Sequence').GetValue($st) % 2) -eq 0))
    $seq1 = [int]$stateType.GetField('Sequence').GetValue($st)
    $write.Invoke($null, @($view, $pB, 7, $false)) | Out-Null
    $argsR = @($view, $pB, $null); [void]$tryView.Invoke($null, $argsR)
    Check 'N8 every completed write changes the (even) sequence' (([int]$stateType.GetField('Sequence').GetValue($argsR[2]) -ne $seq1) -and (([int]$stateType.GetField('Sequence').GetValue($argsR[2]) % 2) -eq 0))
    $argsW = @($view, ($pB + 1), $null)
    Check 'N9 a block read for another PID is rejected (PID isolation)' (-not [bool]$tryView.Invoke($null, $argsW))
    $write.Invoke($null, @($view, $pB, 9, $true)) | Out-Null
    $view.Write(16, [int]([int]$view.ReadInt32(16) + 1))     # make the sequence odd = a writer is (or died) in the middle
    $argsR = @($view, $pB, $null)
    Check 'N10 odd sequence (writer in progress) is rejected' (-not [bool]$tryView.Invoke($null, $argsR))
    $write.Invoke($null, @($view, $pB, 9, $true)) | Out-Null
    $argsR = @($view, $pB, $null)
    Check 'N11 a writer that finds an odd sequence (died half-way) recovers: the next write is valid again' ([bool]$tryView.Invoke($null, $argsR))
    $view.Write(8, [int]10)                                   # change the generation without fixing Check
    $argsR = @($view, $pB, $null)
    Check 'N12 a torn / tampered block (Check mismatch) is rejected' (-not [bool]$tryView.Invoke($null, $argsR))
    $write.Invoke($null, @($view, $pB, 3, $true)) | Out-Null; $view.Write(0, [int]2)
    $argsR = @($view, $pB, $null)
    Check 'N13 a block with another protocol version is rejected' (-not [bool]$tryView.Invoke($null, $argsR))
    $write.Invoke($null, @($view, $pB, 3, $true)) | Out-Null; $view.Write(12, [int]5)
    $argsR = @($view, $pB, $null)
    Check 'N14 a level that is neither 0 nor 1 is rejected' (-not [bool]$tryView.Invoke($null, $argsR))
    $view.Dispose(); $mmf.Dispose()
    $shortMmf = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew("Local\TSScoringPlugin.v1.$($pB + 2).ScenarioState", 8)
    RegPid ($pB + 2)
    $a = @(($pB + 2), $null)
    Check 'N15 a block that is too short reads as invalid, no exception' (-not [bool]$stateType.GetMethod('TryRead').Invoke($null, $a))
    $shortMmf.Dispose()
    Check 'N16 a missing block reads as invalid, no exception' (-not [bool]$stateType.GetMethod('TryRead').Invoke($null, @(($pB + 3), $null)))

    # =================================================================================================================
    Write-Host '--- S: current-adapter evaluation (BveSnapshotBuilder): null / NaN / Infinity / exception never count as readable'
    function Build([int]$created, [scriptblock]$sc, [scriptblock]$tm, [scriptblock]$vl, [scriptblock]$pos, [scriptblock]$veh) {
        $a1 = $sc -as $funcObj; $a2 = $tm -as $funcObjObj; $a3 = $vl -as $funcObjObj; $a4 = $pos -as $funcObjDouble; $a5 = $veh -as $funcObjObj
        return $builderType.GetMethod('Build', $NPS).Invoke($null, @($created, $a1, $a2, $a3, $a4, $a5))
    }
    function SF($s, [string]$n) { return $snapType.GetField($n).GetValue($s) }
    $objA = New-Object object
    $okSc = { $objA }; $okTm = { param($x) $objA }; $okVl = { param($x) $objA }; $okPos = { param($x) [double]123.5 }; $okVeh = { param($x) $objA }
    $s0 = Build 1 $okSc $okTm $okVl $okPos $okVeh
    Check 'S1 all four references present and a finite position: usable, every fact yes, no failure' (((SF $s0 'Failure') -eq $null) -and (SF $s0 'ScenarioRef') -and (SF $s0 'TimeManagerRef') -and (SF $s0 'VehicleLocationRef') -and (SF $s0 'VehicleLocationFinite') -and (SF $s0 'VehicleRef') -and ((SF $s0 'IsScenarioCreated') -eq 1))
    $cnt = @{ N = 0 }
    $s1 = Build 0 { $cnt.N++; $objA } $okTm $okVl $okPos $okVeh
    $s1b = Build -1 { $cnt.N++; $objA } $okTm $okVl $okPos $okVeh
    Check 'S2 IsScenarioCreated false / unreadable: BVE objects are not touched at all (no accessor call), no failure code' (($cnt.N -eq 0) -and ((SF $s1 'IsScenarioCreated') -eq 0) -and ((SF $s1b 'IsScenarioCreated') -eq -1) -and ((SF $s1 'Failure') -eq $null))
    Check 'S3 Scenario null -> scenario-null' ((SF (Build 1 { $null } $okTm $okVl $okPos $okVeh) 'Failure') -eq 'scenario-null')
    Check 'S4 TimeManager null -> timemanager-null' ((SF (Build 1 $okSc { param($x) $null } $okVl $okPos $okVeh) 'Failure') -eq 'timemanager-null')
    Check 'S5 VehicleLocation null -> vehiclelocation-null' ((SF (Build 1 $okSc $okTm { param($x) $null } $okPos $okVeh) 'Failure') -eq 'vehiclelocation-null')
    $sNan = Build 1 $okSc $okTm $okVl { param($x) [double]::NaN } $okVeh
    $sPi = Build 1 $okSc $okTm $okVl { param($x) [double]::PositiveInfinity } $okVeh
    $sNi = Build 1 $okSc $okTm $okVl { param($x) [double]::NegativeInfinity } $okVeh
    $fails6 = @((SF $sNan 'Failure'), (SF $sPi 'Failure'), (SF $sNi 'Failure'))
    Check 'S6 NaN, +Infinity and -Infinity positions -> vehiclelocation-nonfinite, VehicleLocationFinite false' ((@($fails6 | Where-Object { $_ -eq 'vehiclelocation-nonfinite' }).Count -eq 3) -and (-not (SF $sNan 'VehicleLocationFinite')) -and (-not (SF $sPi 'VehicleLocationFinite')) -and (-not (SF $sNi 'VehicleLocationFinite')))
    Check 'S7 Vehicle null -> vehicle-null' ((SF (Build 1 $okSc $okTm $okVl $okPos { param($x) $null }) 'Failure') -eq 'vehicle-null')
    $sEx = Build 1 { throw (New-Object System.InvalidOperationException 'secret message text') } $okTm $okVl $okPos $okVeh
    Check 'S8 an exception while reading never escapes; the code carries the exception TYPE only (no message text)' ((SF $sEx 'Failure') -match '^exc-' -and ((SF $sEx 'Failure') -notmatch 'secret'))
    $z9 = SF (Build 1 $okSc $okTm $okVl { param($x) [double]-0.0 } $okVeh) 'Failure'
    $m9 = SF (Build 1 $okSc $okTm $okVl { param($x) [double]::MaxValue } $okVeh) 'Failure'
    Check 'S9 negative zero and a very large finite position are usable' (($z9 -eq $null) -and ($m9 -eq $null))

    # =================================================================================================================
    Write-Host '--- E: candidate E (the formal condition) through the tracker'
    $P = 961000
    # E1 normal
    $w = NewTracker $P
    Check 'E0 before anything: generation 0, not ready, nothing published' (((Gen $w) -eq 0) -and (-not (Lvl $w)) -and (OutsideNone $P))
    TOpen $w; TCreated $w
    Check 'E1 Opened + Created (candidate A) alone: NOT ScenarioReady' (-not (Lvl $w))
    TTick $w
    Check 'E2 first Tick with every condition: ScenarioReady, generation 1' ((Lvl $w) -and ((Gen $w) -eq 1))
    Check 'E3 the named Event is SET and the state block says generation 1 / level 1 (readable as a LEVEL from outside)' (OutsideIs $P 1 1)
    $est = (WLines $w 'SR_ESTABLISHED')
    Check 'E4 SR_ESTABLISHED logged once with the agreed facts, tick number and time (no value, no name)' (($est.Count -eq 1) -and ($est[0] -match 'candidate=E') -and ($est[0] -match 'scenarioRef=ok timeManagerRef=ok vehicleLocationFinite=yes vehicleRef=ok isScenarioCreated=1') -and ($est[0] -match 'ScenarioGeneration=1') -and ($est[0] -match 'tick=1 ') -and ($est[0] -match 'atUtc=\d\d:\d\d:\d\d\.\d{3}') -and ($est[0] -match 'sinceOpenedMs='))
    TTick $w 2000
    Check 'E5 2000 more Ticks: established exactly once per generation (no duplicate), log silent' (((TProp $w 'EstablishedCount') -eq 1) -and ((WCount $w 'SR_ESTABLISHED') -eq 1) -and (OutsideIs $P 1 1))
    $readsAfter = $w.Reads
    TTick $w 50
    Check 'E6 once established nothing is read from BVE any more (no per-frame cost, no flapping on a later failure)' ($w.Reads -eq $readsAfter)
    TDispose $w

    # E2 insufficient combinations
    $w = NewTracker $P; $w.Snap = (GoodSnap)
    TOpen $w; TTick $w 5
    Check 'E7 Opened + Ticks but no ScenarioCreated (B/C/D-like moments before Created): NOT ready even with every reference readable' (-not (Lvl $w))
    TCreated $w; $w.Snap = (Snap 0 $null)
    TTick $w 5
    Check 'E8 Created + Ticks while IsScenarioCreated is false: NOT ready' (-not (Lvl $w))
    $w.Snap = (Snap 1 'scenario-null' $false $false $false $false $false)
    TTick $w 5
    Check 'E9 IsScenarioCreated true but Scenario reference missing: NOT ready' (-not (Lvl $w))
    $w.Snap = (Snap 1 'timemanager-null' $true $false $false $false $false); TTick $w
    $w.Snap = (Snap 1 'vehiclelocation-null' $true $true $false $false $false); TTick $w
    $w.Snap = (Snap 1 'vehiclelocation-nonfinite' $true $true $true $false $false); TTick $w
    $w.Snap = (Snap 1 'vehicle-null' $true $true $true $true $false); TTick $w
    Check 'E10 not-created, Scenario, TimeManager, VehicleLocation, non-finite position, Vehicle missing: NOT ready, one SR_PENDING per distinct reason (6)' ((-not (Lvl $w)) -and ((WCount $w 'SR_PENDING') -eq 6))
    $w.Snap = (GoodSnap); TTick $w
    Check 'E11 as soon as everything is readable the very next Tick establishes (failure before establishment is retried)' ((Lvl $w) -and ((WCount $w 'SR_ESTABLISHED') -eq 1))
    TDispose $w

    # E3 Created without Opened (late attach)
    $w = NewTracker $P
    TCreated $w; TTick $w 10
    Check 'E12 ScenarioCreated without our ScenarioOpened (late attach): NOT ready, logged, generation stays 0' ((-not (Lvl $w)) -and ((WCount $w 'SR_CREATED_WITHOUT_OPEN') -eq 1) -and ((Gen $w) -eq 0))
    TOpen $w; TCreated $w; TTick $w
    Check 'E13 the next normal ScenarioOpened/Created/Tick establishes generation 1' ((Lvl $w) -and ((Gen $w) -eq 1))
    TDispose $w

    # E4 throwing reader
    $w = NewTracker $P; $w.ReadThrows = $true
    TOpen $w; TCreated $w
    $thrown = $false; try { TTick $w 5 } catch { $thrown = $true }
    Check 'E14 a throwing BVE reader never throws out of the tracker; NOT ready; reason exc-<type> only' ((-not $thrown) -and (-not (Lvl $w)) -and ((WLines $w 'SR_PENDING')[0] -match 'reason=exc-\w+') -and ((WCount $w 'SR_PENDING') -eq 1))
    $w.ReadThrows = $false; TTick $w
    Check 'E15 after the reader works again: retried on the next Tick and established' (Lvl $w)
    TDispose $w

    # E5 the handshake condition (TS Scoring enabled + Ready up)
    $w = NewTracker $P; $w.Up = $false
    TOpen $w; TCreated $w; TTick $w 5
    Check 'E16 TS Scoring off / Ready not up at E: NOT ready, nothing published, one SR_WAIT' ((-not (Lvl $w)) -and (OutsideNone $P) -and ((WCount $w 'SR_WAIT') -eq 1))
    $w.Up = $true; TTick $w
    Check 'E17 TS Scoring switched on mid-scenario: established on the first Tick with the handshake up (same generation, once)' ((Lvl $w) -and (OutsideIs $P 1 1) -and ((Gen $w) -eq 1))
    TDispose $w

    # =================================================================================================================
    Write-Host '--- C: clear conditions'
    $w = NewTracker $P
    $w.Probe = { param($e) if ($e -eq 'SR_CLEARED') { $script:W.AtCleared = (Outside $script:W.Pid) }; if ($e -eq 'SR_OPENED') { $script:W.AtOpened = (Outside $script:W.Pid) } }
    Ready1 $w
    TClosed $w
    Check 'C1 ScenarioClosed: ScenarioReady false, Event reset, block level 0 with the generation kept (1)' ((-not (Lvl $w)) -and (OutsideIs $P 1 0) -and ((Gen $w) -eq 1) -and ((WLines $w 'SR_CLEARED')[0] -match 'reason=closed'))
    TTick $w 100
    Check 'C2 Ticks after Closed (BVE keeps ticking at the title screen) do not re-establish the closed generation' ((-not (Lvl $w)) -and ((WCount $w 'SR_ESTABLISHED') -eq 1))
    TOpen $w; TCreated $w; TTick $w
    Check 'C3 next ScenarioOpened/Created/Tick: generation 2 established' ((Lvl $w) -and ((Gen $w) -eq 2) -and (OutsideIs $P 2 1))
    # Opened without Closed (Closed missed): reset FIRST, then the number moves
    $w.AtCleared = $null; $w.AtOpened = $null
    TOpen $w
    $lc = (WLines $w 'SR_CLEARED'); $lo = (WLines $w 'SR_OPENED')
    Check 'C4 ScenarioOpened while ready (Closed missed): safe reset FIRST (SR_CLEARED reason=opened-reset logged for generation 2 before SR_OPENED for generation 3)' (($lc[$lc.Count - 1] -match 'ScenarioGeneration=2 reason=opened-reset') -and ($lo[$lo.Count - 1] -match 'ScenarioGeneration=3 previous=2 levelClearedFirst=yes') -and (WOrder $w @('SR_CLEARED', 'SR_OPENED')))
    Check 'C5 at the moment of the reset the outside already shows level 0 for the OLD generation (2); at SR_OPENED it still shows the old generation with level 0; only afterwards the new generation 3 (level 0) appears' ((($w.AtCleared.Gen -eq 2) -and ($w.AtCleared.Ready -eq 0) -and (-not $w.AtCleared.EventSet)) -and (($w.AtOpened.Gen -eq 2) -and ($w.AtOpened.Ready -eq 0)) -and (OutsideIs $P 3 0))
    Check 'C6 after Opened and before Created / E the generation is not ready' (-not (Lvl $w))
    TDispose $w
    Check 'C7 Bridge Dispose: ScenarioReady cleared, Event and block gone, later calls ignored' (OutsideNone $P)
    TOpen $w; TCreated $w; TTick $w 3
    Check 'C8 after Dispose nothing is ever published again' ((OutsideNone $P) -and (-not (Lvl $w)))

    # =================================================================================================================
    Write-Host '--- R: retained conditions (must NOT clear)'
    $w = NewTracker $P; Ready1 $w
    $w.Now += 600000   # ten minutes of "pause": no Tick at all, then Ticks resume
    TTick $w 3
    Check 'R1 Pause (no Tick for a long time, then Ticks resume): level, generation, Event and block unchanged, nothing cleared' ((Lvl $w) -and ((Gen $w) -eq 1) -and (OutsideIs $P 1 1) -and ((WCount $w 'SR_CLEARED') -eq 0) -and ((TProp $w 'ClearedCount') -eq 0))
    $w.Snap = (Snap 0 $null); TTick $w 500
    Check 'R2 title-screen style change (IsScenarioCreated reads false, Ticks continue): ScenarioReady is NOT cleared by IsScenarioCreated alone' ((Lvl $w) -and (OutsideIs $P 1 1) -and ((WCount $w 'SR_CLEARED') -eq 0))
    $w.Snap = (Snap -1 'exc-InvalidOperationException' $false $false $false $false $false); TTick $w 3
    Check 'R3 one (or many) transient reference-read failures after establishment do not clear it' ((Lvl $w) -and (OutsideIs $P 1 1))
    TTick $w 100
    Check 'R4 the Phase B Ready staying up is not a clear trigger either (level stays across 100 more Ticks, generation unchanged)' ((Lvl $w) -and ((Gen $w) -eq 1))
    $w.Snap = (GoodSnap)
    # isReload: the tracker has no input for it at all
    Check 'R5 isReload is not an input of the tracker (only the Opened event itself matters)' (@($trkType.GetMethod('OnScenarioOpened').GetParameters()).Count -eq 0)
    TDispose $w

    # same scenario reload and another scenario: both are just "Opened"
    $w = NewTracker $P
    $gens = New-Object System.Collections.Generic.List[int]
    for ($i = 1; $i -le 40; $i++) { TOpen $w; TCreated $w; TTick $w 3; $o = Outside $P; $gens.Add($o.Gen); if ($o.Ready -ne 1) { $gens.Add(-99) }; TClosed $w; TTick $w 2 }
    $mono = $true; for ($i = 1; $i -lt $gens.Count; $i++) { if ($gens[$i] -ne ($gens[$i - 1] + 1)) { $mono = $false } }
    Check 'R6 40 loads (same scenario reloaded or another scenario - indistinguishable): generation 1..40, strictly +1 each, each established once' ($mono -and ($gens[0] -eq 1) -and ($gens[$gens.Count - 1] -eq 40) -and ((TProp $w 'EstablishedCount') -eq 40) -and ((TProp $w 'ClearedCount') -eq 40))
    Check 'R7 Pause or title return does not increase the generation: only Opened does' ((Gen $w) -eq 40)
    # overflow
    $genField = $trkType.GetField('generation', [Reflection.BindingFlags]'NonPublic,Instance')
    $genField.SetValue($w.Trk, [int]([int]::MaxValue - 1))
    TOpen $w; TCreated $w; TTick $w
    $gMax = Gen $w
    TClosed $w; TOpen $w; TCreated $w; TTick $w
    $gWrap = Gen $w
    Check 'R8 overflow: int.MaxValue is reached, the next Opened wraps to 1 (not 0, not negative), is still a different generation, is logged, and is established normally' (($gMax -eq [int]::MaxValue) -and ($gWrap -eq 1) -and ((WCount $w 'SR_GENERATION_WRAPPED') -eq 1) -and (Lvl $w) -and (OutsideIs $P 1 1))
    TDispose $w

    # =================================================================================================================
    Write-Host '--- H: TS Scoring OFF / ON (the handshake) - ScenarioReady is a level'
    $w = NewTracker $P; Ready1 $w
    $w.Up = $false; TLost $w
    Check 'H1 TS Scoring OFF (handshake lost): external publication stops at once (Event and block gone), the level itself is kept' ((OutsideNone $P) -and (Lvl $w) -and ((WLines $w 'SR_WITHDRAWN')[0] -match 'levelKept=yes'))
    TTick $w 20
    Check 'H2 while OFF nothing is published and nothing is established again' ((OutsideNone $P) -and ((WCount $w 'SR_ESTABLISHED') -eq 1))
    $w.Up = $true; TTick $w
    Check 'H3 TS Scoring ON again: the CURRENT level is published at once on the first Tick (same generation, no new establishment)' ((OutsideIs $P 1 1) -and ((WCount $w 'SR_ESTABLISHED') -eq 1) -and ((TProp $w 'EstablishedCount') -eq 1))
    $w.Up = $false; TLost $w; TClosed $w; $w.Up = $true; TTick $w
    Check 'H4 scenario closed while TS Scoring was OFF: after ON the level is false (generation kept) - no stale ScenarioReady' ((-not (Lvl $w)) -and (OutsideIs $P 1 0))
    TDispose $w

    # =================================================================================================================
    Write-Host '--- D: diagnostics (E stall / candidate F) - F never sets ScenarioReady'
    $w = NewTracker $P
    TOpen $w; TCreated $w; $w.Snap = (Snap 1 'vehiclelocation-null' $true $true $false $false $false)
    TTick $w 299
    $c299 = WCount $w 'SR_E_STALLED'
    TTick $w 1
    TPost $w
    Check 'D1 E not established for 300 Ticks: SR_E_STALLED once (not before), then the first PostTick writes SR_F_DIAG once with the same facts' (($c299 -eq 0) -and ((WCount $w 'SR_E_STALLED') -eq 1) -and ((WCount $w 'SR_F_DIAG') -eq 1) -and ((WLines $w 'SR_F_DIAG')[0] -match 'vehicleLocationFinite=no') -and ((WLines $w 'SR_F_DIAG')[0] -match 'usable=no'))
    TPost $w; TPost $w
    Check 'D2 SR_F_DIAG is written only once per generation' ((WCount $w 'SR_F_DIAG') -eq 1)
    $w2 = NewTracker ($P + 1)
    TOpen $w2; TCreated $w2; $w2.Snap = (Snap 1 'vehicle-null' $true $true $true $true $false); TTick $w2 300
    $w2.Snap = (GoodSnap)           # F would see everything readable...
    TPost $w2
    Check 'D3 even when the PostTick read is fully usable, ScenarioReady is NOT set from PostTick (F is diagnostics only); the publication shows generation 1 with level 0' ((-not (Lvl $w2)) -and ((WLines $w2 'SR_F_DIAG')[0] -match 'usable=yes') -and (OutsideIs ($P + 1) 1 0))
    TTick $w2
    Check 'D4 the next Tick (candidate E) is what establishes it' (Lvl $w2)
    $w3 = NewTracker ($P + 2)
    TOpen $w3; TCreated $w3; TTick $w3 5; TPost $w3
    Check 'D5 PostTick without a stall writes nothing (diagnostics only after 300 stalled Ticks)' (((WCount $w3 'SR_F_DIAG') -eq 0) -and (Lvl $w3))
    TDispose $w; TDispose $w2; TDispose $w3

    # =================================================================================================================
    Write-Host '--- X: PID separation and publisher failure'
    $PA = 962001; $PB2 = 962002
    $wa = NewTracker $PA; $wb = NewTracker $PB2
    Ready1 $wa; Ready1 $wb
    TClosed $wb; TOpen $wb; TCreated $wb; TTick $wb
    Check 'X1 two BVE processes side by side: A generation 1 ready, B generation 2 ready, independent objects' ((OutsideIs $PA 1 1) -and (OutsideIs $PB2 2 1))
    TClosed $wa
    Check 'X2 clearing A does not touch B' ((OutsideIs $PA 1 0) -and (OutsideIs $PB2 2 1))
    TDispose $wb
    Check 'X3 disposing B leaves A (and its generation) intact' ((OutsideIs $PA 1 0) -and (OutsideNone $PB2))
    TDispose $wa

    $PF = 962003; RegPid $PF
    $blocker = New-Object Threading.Mutex($false, "Local\TSScoringPlugin.v1.$PF.ScenarioReady")   # a foreign object of another type under the event name
    $wf = NewTracker $PF
    $thrown = $false; try { Ready1 $wf; TTick $wf 20 } catch { $thrown = $true }
    Check 'X4 publisher cannot be opened: no exception reaches the caller; the level is true but not published; exactly one SR_PUBLISH_FAIL' ((-not $thrown) -and (Lvl $wf) -and (-not [bool](TProp $wf 'IsPublished')) -and ((WCount $wf 'SR_PUBLISH_FAIL') -eq 1))
    $blocker.Dispose()
    TTick $wf
    Check 'X5 once the obstacle is gone the next Tick publishes the kept level (retry)' ((OutsideIs $PF 1 1) -and ([bool](TProp $wf 'IsPublished')))
    TDispose $wf

    # =================================================================================================================
    Write-Host '--- B: real Bridge + real Caller session (Phase B handshake, ScenarioReady on top)'
    $idB = 970001; $pBr = NewLogPath 'B1'; LogCfgBoth $pBr $idB
    $b = NewBridge $idB; BeginSr $b $idB; LoadBridge $b
    $c = NewSession $idB; StartSession $c
    BT $b 'OnScenarioOpened'; BT $b 'OnScenarioCreated'
    $ms = PumpUntil @($b) { (Phase $c) -eq 'Connected' } 800
    Check 'B1 Phase B handshake still completes first (Ready) with a tracker attached' ($ms -ge 0)
    $ms2 = PumpUntil @($b) { [bool](SProp $c 'ScenarioReadyLevel') } 600
    Check ("B2 Caller sees ScenarioReady (generation 1) after the Bridge's Tick ({0} ms)" -f $ms2) (($ms2 -ge 0) -and ((SProp $c 'ScenarioGenerationSeen') -eq 1) -and (OutsideIs $idB 1 1))
    Check 'B3 ScenarioReady was established in the very Tick that created Ready (E needs the handshake; no extra frame)' (((BTracker $b) -ne $null) -and (([int]$trkType.GetProperty('EstablishedCount', $NPI).GetValue((BTracker $b))) -eq 1))
    $up0 = [int](SProp $c 'ScenarioReadyOnCount')
    Pump @($b) 1500
    Check 'B4 Pause (no Tick for 1.5 s) and a long run of Ticks afterwards: ScenarioReady and generation unchanged on both sides' (([bool](SProp $c 'ScenarioReadyLevel')) -and ((SProp $c 'ScenarioGenerationSeen') -eq 1) -and ([int](SProp $c 'ScenarioReadyOnCount') -eq $up0))
    $script:BSnap[$idB] = (Snap 0 $null); Pump @($b) 300
    Check 'B5 title-screen style (IsScenarioCreated false, Ticks continue): Caller still sees ScenarioReady (no ScenarioClosed happened)' ([bool](SProp $c 'ScenarioReadyLevel'))
    $script:BSnap[$idB] = (GoodSnap)
    BT $b 'OnScenarioClosed'
    $ms3 = PumpUntil @($b) { -not [bool](SProp $c 'ScenarioReadyLevel') } 400
    Check 'B6 ScenarioClosed: Caller sees ScenarioReady off, generation unchanged' (($ms3 -ge 0) -and ((SProp $c 'ScenarioGenerationSeen') -eq 1) -and (OutsideIs $idB 1 0))
    BT $b 'OnScenarioOpened'; BT $b 'OnScenarioCreated'
    $ms4 = PumpUntil @($b) { [bool](SProp $c 'ScenarioReadyLevel') } 400
    Check 'B7 next load: Caller sees generation 2 and ScenarioReady on again' (($ms4 -ge 0) -and ((SProp $c 'ScenarioGenerationSeen') -eq 2))
    # TS Scoring OFF -> ON
    EndSession $c
    Pump @($b) 250
    Check 'B8 TS Scoring OFF: Caller ended; Bridge withdrew Ready AND ScenarioReady (Event and block gone), no handshake object left except BridgeAvailable' ((OutsideNone $idB) -and (-not [bool](SProp $c 'ScenarioReadyLevel')))
    $c = NewSession $idB; StartSession $c
    $t0 = [Diagnostics.Stopwatch]::StartNew()
    $ms5 = PumpUntil @($b) { [bool](SProp $c 'ScenarioReadyLevel') } 800
    Check ("B9 TS Scoring ON again: the existing level is republished and the new Caller sees generation 2 ScenarioReady ({0} ms)" -f $ms5) (($ms5 -ge 0) -and ((SProp $c 'ScenarioGenerationSeen') -eq 2) -and (OutsideIs $idB 2 1))
    Check 'B10 the new Caller cycle has its own counters and the Bridge did not re-establish (still one establishment per generation)' (([int]$trkType.GetProperty('EstablishedCount', $NPI).GetValue((BTracker $b)) -eq 2))
    # BveEX OFF = Bridge Dispose while ready
    DisposeBridge $b
    Wait 150
    Check 'B11 BveEX OFF (Bridge Dispose): Caller sees ScenarioReady off and BridgeAvailable lost, no ScenarioClosed involved' ((-not [bool](SProp $c 'ScenarioReadyLevel')) -and ((Phase $c) -eq 'WaitingForBridge' -or (Phase $c) -eq 'BridgeMissingTimedOut') -and (OutsideNone $idB))
    EndSession $c
    Wait 100
    $lb = ReadLog $pBr
    Check 'B12 Bridge Dispose order in the log: ScenarioReady cleared (bridge-dispose) and withdrawn BEFORE Ready is disposed' (InOrder $lb @('BRIDGE_DISPOSE_BEGIN', 'SR_CLEARED', 'SR_WITHDRAWN', 'READY_DISPOSED', 'AVAIL_DISPOSED', 'BRIDGE_DISPOSE_END'))
    Check 'B13 Caller log: SCN_GENERATION_CHANGED and SCN_READY_ON/OFF transitions are written (Track A), no scenario or user name anywhere' (((EvtLines $lb 'SCN_READY_ON').Count -ge 3) -and ((EvtLines $lb 'SCN_READY_OFF').Count -ge 3) -and ((EvtLines $lb 'SCN_GENERATION_CHANGED').Count -ge 2) -and (@($lb | Where-Object { $_ -match ' SCN_READY_O' -and $_ -notmatch ' T=A ' }).Count -eq 0))
    Check 'B14 nothing of this PID is left (all named objects released)' (-not (AnyObject $idB))

    # Caller enabled AFTER the scenario is already open (BVE5-like late enabling)
    $idL = 970002; $pL = NewLogPath 'B2-late-enable'; LogCfgBoth $pL $idL
    $bl = NewBridge $idL; BeginSr $bl $idL; LoadBridge $bl
    BT $bl 'OnScenarioOpened'; BT $bl 'OnScenarioCreated'
    Pump @($bl) 300
    Check 'B15 TS Scoring not enabled yet: scenario open and ticking, ScenarioReady not established, nothing published' (-not ([bool]$trkType.GetProperty('IsScenarioReady', $NPI).GetValue((BTracker $bl))) -and (OutsideNone $idL))
    $cl = NewSession $idL; StartSession $cl
    $msl = PumpUntil @($bl) { [bool](SProp $cl 'ScenarioReadyLevel') } 800
    Check ("B16 TS Scoring switched on mid-scenario: Ready, then ScenarioReady generation 1 for the Caller ({0} ms)" -f $msl) (($msl -ge 0) -and ((SProp $cl 'ScenarioGenerationSeen') -eq 1))
    EndSession $cl; Pump @($bl) 150; DisposeBridge $bl

    # two BVE processes
    $idX = 970003; $idY = 970004; $pXY = NewLogPath 'B3-two-pids'; LogCfgBoth $pXY $idX
    $bx = NewBridge $idX; BeginSr $bx $idX; LoadBridge $bx
    $by = NewBridge $idY; BeginSr $by $idY; LoadBridge $by
    $cx = NewSession $idX; $cy = NewSession $idY; StartSession $cx; StartSession $cy
    BT $bx 'OnScenarioOpened'; BT $bx 'OnScenarioCreated'
    BT $by 'OnScenarioOpened'; BT $by 'OnScenarioCreated'; BT $by 'OnScenarioClosed'; BT $by 'OnScenarioOpened'; BT $by 'OnScenarioCreated'
    [void](PumpUntil @($bx, $by) { [bool](SProp $cx 'ScenarioReadyLevel') -and [bool](SProp $cy 'ScenarioReadyLevel') } 900)
    Check 'B17 two BVE processes: each Caller sees only its own generation (X=1, Y=2)' (((SProp $cx 'ScenarioGenerationSeen') -eq 1) -and ((SProp $cy 'ScenarioGenerationSeen') -eq 2))
    BT $bx 'OnScenarioClosed'; Pump @($bx, $by) 150
    Check 'B18 closing X does not change Y' ((-not [bool](SProp $cx 'ScenarioReadyLevel')) -and ([bool](SProp $cy 'ScenarioReadyLevel')))
    EndSession $cx; EndSession $cy; Pump @($bx, $by) 150; DisposeBridge $bx; DisposeBridge $by
    Check 'B19 both PIDs cleaned up' ((-not (AnyObject $idX)) -and (-not (AnyObject $idY)))

    # =================================================================================================================
    Write-Host '--- P: privacy of every log produced by these tests'
    $forbidden = New-Object System.Collections.Generic.List[string]
    foreach ($v in $env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf), 'C:\Users', '\Users\', 'Documents', 'AppData', 'Scoring-Feature', 'gmail') { if ($v) { $forbidden.Add([string]$v) } }
    $hits = 0
    foreach ($lp in $allLogs) { if (Test-Path -LiteralPath $lp) { $txt = [IO.File]::ReadAllText($lp); foreach ($f in $forbidden) { $hits += ([regex]::Matches($txt, [regex]::Escape($f), 'IgnoreCase')).Count }; $hits += ([regex]::Matches($txt, '[A-Za-z]:\\')).Count; $hits += ([regex]::Matches($txt, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count } }
    Check ('P1 no user name, machine name, drive path, user folder or e-mail in any log (' + $allLogs.Count + ' files)') ($hits -eq 0)
    $trackerText = ($script:W.Lines -join "`n")
    Check 'P2 tracker lines contain only ids, counters and yes/no facts (no scenario / vehicle name, no position or time value)' ($trackerText -notmatch 'name=|path=|vehicle=|scenario=|position=|location=\d')
}
finally {
    foreach ($t in $cLog, $bLog) { try { $t.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null } catch { } }
}

Start-Sleep -Milliseconds 300
$left = @($allPids | Where-Object { AnyObject $_ })
Check 'Final: no named object of any test pid is left' ($left.Count -eq 0)
Check 'Final: no monitor thread alive' (([int]$sessionType.GetField('LiveMonitors', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null)) -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
