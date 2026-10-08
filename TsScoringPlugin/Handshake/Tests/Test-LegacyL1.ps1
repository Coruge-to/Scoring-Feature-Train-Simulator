# PHASE L1 - offline tests of the AtsEX LEGACY adapter (control plane thread, ScenarioReady on Tick, pause contract, Current/Legacy core equality).
# No BVE, no AtsEX runtime, no Python, no UDP, no hooks. The real built DLLs are loaded from memory: the Caller and the Current Bridge from dist\,
# the Legacy Bridge from Bridge\Legacy\out\. The AtsEX host assemblies are referenced read-only from the installed legacy host (never copied, never in Git).
# Every observation log goes to a private file under logs\l1-tests (NEVER to the fixed Downloads file). Fake process ids and a notice test double
# are used (no MessageBox). The AtsEX handlers are driven with real event-argument objects; BVE objects (Scenario, Vehicle ...) cannot be built
# offline, so the BVE reads are replaced by a fake reader (the evaluation logic BveSnapshotBuilder itself is tested).
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
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
[TestResolver]::Install(@((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), $legacyHost))
$hostAsm = [Reflection.Assembly]::LoadFrom((Join-Path $legacyHost 'AtsEx.PluginHost.dll'))
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')))
$curAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')))
$legAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')))
$NS = 'TSScoringPlugin.Handshake.'
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$adType = $legAsm.GetType($NS + 'TsScoringLegacyBridgePrototype')
$ctlType = $legAsm.GetType($NS + 'HandshakeControlPlane')
$trkType = $legAsm.GetType($NS + 'ScenarioReadyTracker')
$snapType = $legAsm.GetType($NS + 'BveSnapshot')
$builderType = $legAsm.GetType($NS + 'BveSnapshotBuilder')
$stateType = $legAsm.GetType($NS + 'ScenarioState')
$protoType = $legAsm.GetType($NS + 'HandshakeProtocol')
$timingType = $legAsm.GetType($NS + 'HandshakeTiming')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$lLog = $legAsm.GetType($NS + 'ObservationLog')
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$funcSnap = [Func``1].MakeGenericType($snapType)
$funcObj = [Func``1].MakeGenericType([object])
$funcObjObj = [Func``2].MakeGenericType([object], [object])
$funcObjDouble = [Func``2].MakeGenericType([object], [double])
$evOpenedType = $hostAsm.GetType('AtsEx.PluginHost.ScenarioOpenedEventArgs')
$evCreatedType = $hostAsm.GetType('AtsEx.PluginHost.ScenarioCreatedEventArgs')

$testDir = Join-Path $Root 'logs\l1-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
$allPids = New-Object System.Collections.Generic.List[int]
function RegPid([int]$p) { if (-not $allPids.Contains($p)) { $allPids.Add($p) } }
$allLogs = New-Object System.Collections.Generic.List[string]

function LogCfg($type, [string]$path, [int]$fakePid) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]0)
}
function LogCfgBoth([string]$path, [int]$fakePid) { LogCfg $cLog $path $fakePid; LogCfg $lLog $path $fakePid }
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

function Snap([int]$created = 1, [object]$fail = $null) {
    $o = [Activator]::CreateInstance($snapType)
    $f = [Reflection.BindingFlags]'Public,Instance'
    $snapType.GetField('IsScenarioCreated', $f).SetValue($o, $created)
    $good = ($created -eq 1) -and ($fail -eq $null)
    foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $snapType.GetField($n, $f).SetValue($o, [bool]($created -eq 1)) }
    $snapType.GetField('Failure', $f).SetValue($o, $fail)
    return $o
}
function GoodSnap() { return Snap 1 $null }

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
function NamedEvent([int]$p, [string]$kind) {
    $h = $null
    if ([Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$p.$kind", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$h)) { $set = $h.WaitOne(0); $h.Dispose(); return [pscustomobject]@{ Exists = $true; Set = $set } }
    return [pscustomobject]@{ Exists = $false; Set = $false }
}
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
function Wait([int]$ms) { Start-Sleep -Milliseconds $ms }
function WaitFor([scriptblock]$cond, [int]$limitMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $limitMs) { if (& $cond) { return $sw.ElapsedMilliseconds }; Start-Sleep -Milliseconds 5 }
    return -1
}

# ---- Caller session (real Caller DLL) ----
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

# ---- Legacy adapter (constructed without AtsEX's PluginBuilder, like the Current tests do) ----
$script:ReadThreads = New-Object System.Collections.Generic.List[int]
$script:SnapCur = @{}
$script:ReadFail = @{}
$script:TickCount = 0
function NewLegacy([int]$fakePid) {
    RegPid $fakePid
    $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($adType)
    $f = [Reflection.BindingFlags]'NonPublic,Instance'
    $adType.GetField('loadQpc', $f).SetValue($b, [Diagnostics.Stopwatch]::GetTimestamp())
    $adType.GetField('loadUtcTicks', $f).SetValue($b, [DateTime]::UtcNow.Ticks)
    $adType.GetField('pid', $f).SetValue($b, $fakePid)
    $adType.GetField('instNo', $f).SetValue($b, 1)
    return $b
}
function BeginControl($b, [bool]$thread) { $adType.GetMethod('BeginControl', $NPI).Invoke($b, @($thread)) | Out-Null }
function BeginSr($b, [int]$p) {
    $script:SnapCur[$p] = (GoodSnap)
    $rd = ([scriptblock]::Create('$script:ReadThreads.Add([Threading.Thread]::CurrentThread.ManagedThreadId); if ($script:ReadFail[' + $p + ']) { throw (New-Object System.IO.IOException ''boom'') }; $script:SnapCur[' + $p + ']')) -as $funcSnap
    $adType.GetMethod('BeginScenarioReady', $NPI).Invoke($b, @($rd, $null)) | Out-Null
}
function BeginObs($b) {
    $f1 = ({ 1 }) -as [Func[int]]
    $f2 = ({ $null }) -as [Func[string]]
    $adType.GetMethod('BeginObservation', $NPI).Invoke($b, @($f1, $f2)) | Out-Null
}
function FullLegacy([int]$p, [bool]$thread = $true) {
    $b = NewLegacy $p
    BeginControl $b $false
    BeginObs $b
    BeginSr $b $p
    if ($thread) { $ctlType.GetMethod('Start', $NPI).Invoke($adType.GetField('control', [Reflection.BindingFlags]'NonPublic,Instance').GetValue($b), @()) | Out-Null }
    return $b
}
function CtlOf($b) { return $adType.GetField('control', [Reflection.BindingFlags]'NonPublic,Instance').GetValue($b) }
function CtlProp($b, [string]$n) { return $ctlType.GetProperty($n, $NPI).GetValue((CtlOf $b)) }
function TrkOf($b) { return $adType.GetField('tracker', [Reflection.BindingFlags]'NonPublic,Instance').GetValue($b) }
function TProp($b, [string]$n) { return $trkType.GetProperty($n, $NPI).GetValue((TrkOf $b)) }
function LTick($b) { $script:TickCount++; return $adType.GetMethod('Tick').Invoke($b, @([TimeSpan]::Zero)) }
function LTicks($b, [int]$n) { for ($i = 0; $i -lt $n; $i++) { [void](LTick $b) } }
function LDispose($b) { try { $adType.GetMethod('Dispose').Invoke($b, @()) | Out-Null } catch { } }
function Handler($b, [string]$name, $arg) { $adType.GetMethod($name, $NPI).Invoke($b, @($arg)) | Out-Null }
function Opened($b, [bool]$reload = $false) { Handler $b 'OnHackerScenarioOpened' ([Activator]::CreateInstance($evOpenedType, @($null, $reload))) }
function Created($b) { Handler $b 'OnHackerScenarioCreated' ([Activator]::CreateInstance($evCreatedType, @($null))) }
function PreviewCreated($b) { Handler $b 'OnHackerPreviewScenarioCreated' ([Activator]::CreateInstance($evCreatedType, @($null))) }
function Closed($b) { Handler $b 'OnHackerScenarioClosed' ([EventArgs]::Empty) }
function Lvl($b) { return [bool](TProp $b 'IsScenarioReady') }
function Gen($b) { return [int](TProp $b 'ScenarioGeneration') }
function Est($b) { return [int](TProp $b 'EstablishedCount') }
function LiveWorkers() { return [int]$ctlType.GetField('LiveWorkers', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null) }

try {
    # =================================================================================================================
    Write-Host '--- A: shape of the Legacy adapter and separation from the Current adapter'
    $plugAttr = @($adType.GetCustomAttributes($false) | Where-Object { $_.GetType().Name -eq 'PluginAttribute' })
    Check 'A1 adapter is a public class, an AtsEX AssemblyPluginBase and IExtension, marked [Plugin(PluginType.Extension)]' ($adType.IsPublic -and ($adType.BaseType.Name -eq 'AssemblyPluginBase') -and (@($adType.GetInterfaces() | Where-Object { $_.FullName -eq 'AtsEx.PluginHost.Plugins.Extensions.IExtension' }).Count -eq 1) -and ($plugAttr.Count -eq 1) -and ($plugAttr[0].PluginType.ToString() -eq 'Extension'))
    Check 'A2 adapter has the AtsEX public constructor (PluginBuilder), Tick returns TickResult (not void), Dispose exists' ((@($adType.GetConstructors() | Where-Object { ($_.GetParameters().Count -eq 1) -and ($_.GetParameters()[0].ParameterType.Name -eq 'PluginBuilder') }).Count -eq 1) -and ($adType.GetMethod('Tick').ReturnType.Name -eq 'TickResult') -and ($adType.GetMethod('Dispose') -ne $null))
    Check 'A3 PostTick independence: the adapter has no PostTick / PreviewTick handler or member at all' (@($adType.GetMembers($NPI + [Reflection.BindingFlags]'Static') | Where-Object { $_.Name -match 'PostTick|PreviewTick' }).Count -eq 0)
    $legRefs = @($legAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object)
    $curRefs = @($curAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object)
    Check 'A4 Legacy DLL references AtsEx.PluginHost (and no BveEx assembly); Current DLL references BveEx.PluginHost (and no AtsEx assembly)' (($legRefs -contains 'AtsEx.PluginHost') -and (@($legRefs | Where-Object { $_ -like 'BveEx*' }).Count -eq 0) -and ($curRefs -contains 'BveEx.PluginHost') -and (@($curRefs | Where-Object { $_ -like 'AtsEx*' }).Count -eq 0))
    Check 'A5 Legacy DLL references only mscorlib, System, System.Core, AtsEx.PluginHost, BveTypes' (@($legRefs | Where-Object { $_ -notin 'mscorlib', 'System', 'System.Core', 'AtsEx.PluginHost', 'BveTypes' }).Count -eq 0)
    $curBytesText = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')))
    Check 'A6 Legacy adapter type name differs from the Current adapter (the Current adapter cannot be loaded without the BveEX host, so its name is checked in the metadata); same namespace for the shared core' (($adType.FullName -eq 'TSScoringPlugin.Handshake.TsScoringLegacyBridgePrototype') -and ($legAsm.GetType($NS + 'TsScoringBridgePrototype') -eq $null) -and $curBytesText.Contains('TsScoringBridgePrototype') -and (-not $curBytesText.Contains('TsScoringLegacyBridgePrototype')))
    Check 'A7 timings are the shared ones and unchanged: BridgeMissingTimeoutMs 500, TargetBridgeAvailableMs 500, CallerPollMs 20, BridgePollMs 100' ((($timingType.GetField('BridgeMissingTimeoutMs').GetValue($null)) -eq 500) -and (($timingType.GetField('TargetBridgeAvailableMs').GetValue($null)) -eq 500) -and (($timingType.GetField('CallerPollMs').GetValue($null)) -eq 20) -and (($timingType.GetField('BridgePollMs').GetValue($null)) -eq 100))

    # =================================================================================================================
    Write-Host '--- G: shared core is the same in the Current and the Legacy DLL (names, state block, generation rule, tracker behaviour)'
    $curProto = $curAsm.GetType($NS + 'HandshakeProtocol')
    $namesEq = $true
    foreach ($n in 'EnabledName', 'StopName', 'BridgeAvailableName', 'ReadyName', 'InfoName', 'ScenarioReadyName', 'ScenarioStateName') { if ($curProto.GetMethod($n).Invoke($null, @(777)) -cne $protoType.GetMethod($n).Invoke($null, @(777))) { $namesEq = $false } }
    Check 'G1 every named object of the contract is identical (Enabled, Stop, BridgeAvailable, Ready, BridgeInfo, ScenarioReady, ScenarioState)' $namesEq
    $curState = $curAsm.GetType($NS + 'ScenarioState')
    $mA = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew('Local\TSScoringPlugin.v1.980901.G2a', 64); $vA = $mA.CreateViewAccessor(0, 64)
    $mB = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew('Local\TSScoringPlugin.v1.980901.G2b', 64); $vB = $mB.CreateViewAccessor(0, 64)
    $curState.GetMethod('Write').Invoke($null, @($vA, 4321, 5, $true)) | Out-Null
    $stateType.GetMethod('Write').Invoke($null, @($vB, 4321, 5, $true)) | Out-Null
    $bytesA = New-Object byte[] 64; $bytesB = New-Object byte[] 64
    [void]$vA.ReadArray(0, $bytesA, 0, 64); [void]$vB.ReadArray(0, $bytesB, 0, 64)
    Check 'G2 the 64-byte ScenarioState block written by the Current core and by the Legacy core is byte-identical' ((-join $bytesA) -eq (-join $bytesB))
    $vA.Dispose(); $mA.Dispose(); $vB.Dispose(); $mB.Dispose()
    Check 'G3 ScenarioState layout and generation rule are the same (size 64, fields, wrap to 1)' (([int]$curState.GetField('Size').GetRawConstantValue() -eq [int]$stateType.GetField('Size').GetRawConstantValue()) -and ((($curState.GetFields([Reflection.BindingFlags]'Public,Instance') | ForEach-Object { $_.Name }) -join ',') -eq (($stateType.GetFields([Reflection.BindingFlags]'Public,Instance') | ForEach-Object { $_.Name }) -join ',')) -and (($curAsm.GetType($NS + 'ScenarioGenerationRule').GetMethod('Next').Invoke($null, @([int]::MaxValue))) -eq ($legAsm.GetType($NS + 'ScenarioGenerationRule').GetMethod('Next').Invoke($null, @([int]::MaxValue)))))

    function RunCore($asm, [int]$p) {
        $tt = $asm.GetType($NS + 'ScenarioReadyTracker'); $pt = $asm.GetType($NS + 'ScenarioReadyPublisher'); $st = $asm.GetType($NS + 'BveSnapshot')
        $fs = [Func``1].MakeGenericType($st)
        $lines = New-Object System.Collections.Generic.List[string]
        $world = @{ Up = $true }
        $snap = [Activator]::CreateInstance($st)
        $ff = [Reflection.BindingFlags]'Public,Instance'
        $st.GetField('IsScenarioCreated', $ff).SetValue($snap, 1)
        foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $st.GetField($n, $ff).SetValue($snap, $true) }
        $log = [Action[string, string, string]] ({ param($t, $e, $d) $lines.Add($e + '|' + ($d -replace 'atUtc=\S+', 'atUtc=X' -replace 'sinceOpenedMs=\d+', 'sinceOpenedMs=X')) }.GetNewClosure())
        $rd = ({ $snap }.GetNewClosure()) -as $fs
        $up = [Func[bool]] ({ [bool]$world.Up }.GetNewClosure())
        $nw = [Func[long]] { [long]1000 }
        $pub = $pt.GetConstructors($NPI)[0].Invoke(@($p))
        $trk = $tt.GetConstructors($NPI)[0].Invoke(@($log, $rd, $up, $pub, $nw))
        $calls = @('OnScenarioOpened', 'OnScenarioCreated', 'OnTick', 'OnTick', 'OnHandshakeLost:x', 'OnTick', 'UP', 'OnTick', 'OnScenarioClosed', 'OnScenarioOpened', 'OnScenarioCreated', 'OnTick', 'OnScenarioOpened', 'OnScenarioCreated', 'OnTick', 'OnDispose')
        $states = New-Object System.Collections.Generic.List[string]
        foreach ($c in $calls) {
            if ($c -eq 'UP') { $world.Up = $true; continue }
            if ($c -like 'OnHandshakeLost:*') { $world.Up = $false; $tt.GetMethod('OnHandshakeLost', $NPI).Invoke($trk, @('x')) | Out-Null }
            else { $tt.GetMethod($c, $NPI).Invoke($trk, @()) | Out-Null }
            $e = $null; $ex = [Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$p.ScenarioReady", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$e)
            $set = $false; if ($ex -and $e) { $set = $e.WaitOne(0); $e.Dispose() }
            $states.Add($c + ':' + $tt.GetProperty('ScenarioGeneration', $NPI).GetValue($trk) + ':' + $tt.GetProperty('IsScenarioReady', $NPI).GetValue($trk) + ':' + $ex + ':' + $set)
        }
        return [pscustomobject]@{ Lines = ($lines -join "`n"); States = ($states -join ';') }
    }
    RegPid 980911; RegPid 980912
    $rc = RunCore $curAsm 980911
    $rl = RunCore $legAsm 980912
    Check 'G4 the same scripted life (open, create, tick, handshake lost, back, close, reopen x2, dispose) gives the SAME tracker log lines in the Current and the Legacy DLL' ($rc.Lines -ceq $rl.Lines -and $rc.Lines.Length -gt 200)
    Check 'G5 ... and the same generation / level / external Event states after every step' (($rc.States -ceq $rl.States) -and ($rc.States.Length -gt 100))

    # =================================================================================================================
    Write-Host '--- E: evaluation of a BVE read with the Legacy accessors (Scenario.LocationManager.Location): null / NaN / Infinity / exception never count as readable'
    function Build([int]$created, [scriptblock]$sc, [scriptblock]$tm, [scriptblock]$lm, [scriptblock]$pos, [scriptblock]$veh) {
        $a1 = $sc -as $funcObj; $a2 = $tm -as $funcObjObj; $a3 = $lm -as $funcObjObj; $a4 = $pos -as $funcObjDouble; $a5 = $veh -as $funcObjObj
        return $builderType.GetMethod('Build', $NPS).Invoke($null, @($created, $a1, $a2, $a3, $a4, $a5))
    }
    function Fail($s) { return [string]$snapType.GetField('Failure').GetValue($s) }
    $o = New-Object object
    $sGood = Build 1 { $o } { param($s) $o } { param($s) $o } { param($l) [double]12.5 } { param($s) $o }
    Check 'E1 all references readable and the position finite: no failure, usable (candidate E data)' ((Fail $sGood) -eq '' -and [bool]$snapType.GetProperty('Usable').GetValue($sGood))
    Check 'E2 IsScenarioCreated false: no BVE accessor is touched at all' ((& { $touched = $false; $s = Build 0 { $script:touched = $true; $o } { param($s) $o } { param($s) $o } { param($l) 1.0 } { param($s) $o }; -not $script:touched -and (Fail $s) -eq '' -and -not [bool]$snapType.GetProperty('Usable').GetValue($s) }))
    Check 'E3 Scenario null -> scenario-null' ((Fail (Build 1 { $null } { param($s) $o } { param($s) $o } { param($l) 1.0 } { param($s) $o })) -eq 'scenario-null')
    Check 'E4 TimeManager null -> timemanager-null' ((Fail (Build 1 { $o } { param($s) $null } { param($s) $o } { param($l) 1.0 } { param($s) $o })) -eq 'timemanager-null')
    Check 'E5 LocationManager (the Legacy VehicleLocation) null -> vehiclelocation-null' ((Fail (Build 1 { $o } { param($s) $o } { param($s) $null } { param($l) 1.0 } { param($s) $o })) -eq 'vehiclelocation-null')
    Check 'E6 position NaN -> vehiclelocation-nonfinite' ((Fail (Build 1 { $o } { param($s) $o } { param($s) $o } { param($l) [double]::NaN } { param($s) $o })) -eq 'vehiclelocation-nonfinite')
    Check 'E7 position +Infinity and -Infinity -> vehiclelocation-nonfinite' (((Fail (Build 1 { $o } { param($s) $o } { param($s) $o } { param($l) [double]::PositiveInfinity } { param($s) $o })) -eq 'vehiclelocation-nonfinite') -and ((Fail (Build 1 { $o } { param($s) $o } { param($s) $o } { param($l) [double]::NegativeInfinity } { param($s) $o })) -eq 'vehiclelocation-nonfinite'))
    Check 'E8 Vehicle null -> vehicle-null' ((Fail (Build 1 { $o } { param($s) $o } { param($s) $o } { param($l) 1.0 } { param($s) $null })) -eq 'vehicle-null')
    Check 'E9 an exception in any accessor -> exc-<TYPE name only>, nothing thrown' ((Fail (Build 1 { throw (New-Object System.IO.IOException 'secret text') } { param($s) $o } { param($s) $o } { param($l) 1.0 } { param($s) $o })) -match '^exc-\w*Exception$|^exc-\w+$')

    # =================================================================================================================
    Write-Host '--- B: control plane (Tick independent): Enabled / Stop / BridgeAvailable / Ready'
    $idC = 981001; $pC = NewLogPath 'B-control'; LogCfgBoth $pC $idC
    $bc = NewLegacy $idC; BeginControl $bc $false
    $av = NamedEvent $idC 'BridgeAvailable'
    Check 'B1 BridgeAvailable is created and set at load (constructor side), before anything else' ($av.Exists -and $av.Set)
    Check 'B2 no Caller yet: no Ready, handshake not up' ((-not (NamedEvent $idC 'Ready').Exists) -and (-not [bool](CtlProp $bc 'HandshakeUp')))
    $cc = NewSession $idC; StartSession $cc
    $ctl = CtlOf $bc
    $okStep = WaitFor { $ctlType.GetMethod('Step', $NPI).Invoke($ctl, @()) | Out-Null; [bool](CtlProp $bc 'HandshakeUp') } 1500
    Check 'B3 Caller enabled: one control step creates Ready (no Tick has ever been called)' (($okStep -ge 0) -and (NamedEvent $idC 'Ready').Set)
    $okC = WaitFor { (Phase $cc) -eq 'Connected' } 1000
    Check 'B4 the real Caller session reaches Connected against the Legacy control plane' ($okC -ge 0)
    $info = $null; $infoArgs = @($idC, $null)
    $cInfoType = $callerAsm.GetType($NS + 'BridgeInfo')
    Check 'B5 BridgeInfo measurement block is published and valid for the Caller (as in Phase B)' ([bool]$cInfoType.GetMethod('TryRead').Invoke($null, $infoArgs))
    EndSession $cc
    $okOff = WaitFor { $ctlType.GetMethod('Step', $NPI).Invoke($ctl, @()) | Out-Null; -not [bool](CtlProp $bc 'HandshakeUp') } 1500
    Check 'B6 Caller ended (TS Scoring OFF): one control step withdraws Ready; BridgeAvailable stays; still no Tick' (($okOff -ge 0) -and (-not (NamedEvent $idC 'Ready').Exists) -and (NamedEvent $idC 'BridgeAvailable').Set -and ($script:TickCount -eq 0))
    $adType.GetMethod('Dispose').Invoke($bc, @()) | Out-Null
    Check 'B7 Dispose: BridgeAvailable withdrawn and every object of the PID gone' (-not (AnyObject $idC))

    # control thread: everything again but only the thread works (no Step, no Tick)
    $idT = 981002; $pT = NewLogPath 'B-thread'; LogCfgBoth $pT $idT
    $w0 = LiveWorkers
    $bt = NewLegacy $idT; BeginControl $bt $true
    Check 'B8 the control thread is running (one more live worker) and BridgeAvailable exists' (((WaitFor { (LiveWorkers) -eq ($w0 + 1) } 1500) -ge 0) -and [bool](CtlProp $bt 'IsWorkerAlive') -and (NamedEvent $idT 'BridgeAvailable').Set)
    $ct = NewSession $idT; StartSession $ct
    $ms = WaitFor { [bool](CtlProp $bt 'HandshakeUp') } 1500
    Check ("B9 Tick independent: Ready is created by the control thread alone ({0} ms), Tick was never called" -f $ms) (($ms -ge 0) -and (NamedEvent $idT 'Ready').Set -and ($script:TickCount -eq 0))
    Check 'B10 the Caller reaches Connected with no Tick' ((WaitFor { (Phase $ct) -eq 'Connected' } 1000) -ge 0)
    EndSession $ct
    $ms = WaitFor { -not (NamedEvent $idT 'Ready').Exists } 1500
    Check ("B11 TS Scoring OFF without any Tick (pause): the control thread withdraws Ready ({0} ms)" -f $ms) (($ms -ge 0) -and (-not [bool](CtlProp $bt 'HandshakeUp')))
    $ct = NewSession $idT; StartSession $ct
    $ms = WaitFor { (NamedEvent $idT 'Ready').Set } 1500
    Check ("B12 TS Scoring ON again without any Tick: Ready is back ({0} ms)" -f $ms) (($ms -ge 0) -and [bool](CtlProp $bt 'HandshakeUp') -and ((CtlProp $bt 'ReadyCreateCount') -eq 2) -and ((CtlProp $bt 'ReadyDestroyCount') -eq 1))
    EndSession $ct; Wait 100
    LDispose $bt
    Check 'B13 Dispose joins the control thread (live workers back to the start value) and releases every object of the PID' (((LiveWorkers) -eq $w0) -and (-not (AnyObject $idT)))
    LDispose $bt
    Check 'B14 Dispose twice is harmless' (-not (AnyObject $idT))

    # =================================================================================================================
    Write-Host '--- C: ScenarioReady (candidate E) and the pause contract through the real AtsEX event handlers'
    $idP = 981003; $pP = NewLogPath 'C-pause'; LogCfgBoth $pP $idP
    $script:ReadThreads.Clear(); $script:TickCount = 0
    $bp = FullLegacy $idP
    $cp = NewSession $idP; StartSession $cp
    [void](WaitFor { (Phase $cp) -eq 'Connected' } 1500)
    Opened $bp; PreviewCreated $bp; Created $bp
    Check 'C1 ScenarioOpened + ScenarioCreated received but no Tick yet: generation 1, not ScenarioReady, nothing published as ready' ((Gen $bp) -eq 1 -and (-not (Lvl $bp)) -and (-not (OutsideIs $idP 1 1)))
    $tr = LTick $bp
    Check 'C2 the first Tick returns an ExtensionTickResult' (($tr -ne $null) -and ($tr.GetType().Name -eq 'ExtensionTickResult'))
    Check 'C3 candidate E: ScenarioReady established at that first Tick, generation 1; the Event and the state block agree' ((Lvl $bp) -and (Est $bp) -eq 1 -and (OutsideIs $idP 1 1))
    [void](WaitFor { [bool](SProp $cp 'ScenarioReadyLevel') } 800)
    Check 'C4 the real Caller sees ScenarioReady, generation 1' (([bool](SProp $cp 'ScenarioReadyLevel')) -and ((SProp $cp 'ScenarioGenerationSeen') -eq 1))
    LTicks $bp 200
    Check 'C5 200 more Ticks in the same generation: established exactly once (no second establishment)' ((Est $bp) -eq 1 -and (OutsideIs $idP 1 1))

    # pause: Ticks stop for 1.3 s
    $ticksBefore = $script:TickCount
    Wait 1300
    Check 'C6 Pause (no Tick for 1.3 s): ScenarioReady, generation and Ready unchanged on both sides' ((Lvl $bp) -and (OutsideIs $idP 1 1) -and ([bool](SProp $cp 'ScenarioReadyLevel')) -and ((Phase $cp) -eq 'Connected'))
    # TS Scoring OFF during the pause
    EndSession $cp
    $ms = WaitFor { (OutsideNone $idP) -and (-not (NamedEvent $idP 'Ready').Exists) } 1500
    Check ("C7 TS Scoring OFF during the pause (no Tick): external ScenarioReady AND Ready are withdrawn by the control plane ({0} ms)" -f $ms) (($ms -ge 0) -and ($script:TickCount -eq $ticksBefore) -and (NamedEvent $idP 'BridgeAvailable').Exists)
    Check 'C8 ... while the internal ScenarioReady level and the generation are kept' ((Lvl $bp) -and (Gen $bp) -eq 1)
    # TS Scoring ON again during the pause
    $cp = NewSession $idP; StartSession $cp
    $ms = WaitFor { [bool](CtlProp $bp 'HandshakeUp') -and (NamedEvent $idP 'Ready').Set } 1500
    Check ("C9 TS Scoring ON again during the pause: Ready is restored by the control plane at once ({0} ms), Tick still silent" -f $ms) (($ms -ge 0) -and ($script:TickCount -eq $ticksBefore))
    Wait 400
    Check 'C10 ... but BVE data (ScenarioReady) is NOT published until the next Tick (still no Event, no block)' ((OutsideNone $idP) -and (Lvl $bp) -and ($script:TickCount -eq $ticksBefore))
    [void](LTick $bp)
    Check 'C11 the first Tick after the pause republishes the SAME generation 1 as ScenarioReady (no re-establishment)' ((OutsideIs $idP 1 1) -and (Est $bp) -eq 1 -and (Gen $bp) -eq 1)
    $ms = WaitFor { [bool](SProp $cp 'ScenarioReadyLevel') } 800
    Check 'C12 the new Caller cycle sees generation 1 ScenarioReady' (($ms -ge 0) -and ((SProp $cp 'ScenarioGenerationSeen') -eq 1))
    LTicks $bp 3
    $lg = ReadLog $pP
    Check 'C13 diagnostics: the Tick after the restore is recorded (LEGACY_TICK_AFTER_HANDSHAKE_UP) and SR_PUBLISHED shows why=handshake-back' (((EvtLines $lg 'LEGACY_TICK_AFTER_HANDSHAKE_UP').Count -ge 1) -and (@($lg | Where-Object { $_ -match ' SR_PUBLISHED ' -and $_ -match 'why=handshake-back' }).Count -ge 1))
    Check 'C14 after the pause the first Tick after a gap writes TICK_GAP once; the level was not touched by it' (((EvtLines $lg 'TICK_GAP').Count -ge 1) -and (Lvl $bp))

    # title return / IsScenarioCreated false is not a ScenarioClosed
    $script:SnapCur[$idP] = (Snap 0 $null); LTicks $bp 20
    Check 'C15 IsScenarioCreated false while Ticks continue (title-screen style): ScenarioReady is NOT cleared (never guessed)' ((Lvl $bp) -and (OutsideIs $idP 1 1))
    $script:SnapCur[$idP] = (GoodSnap)
    Closed $bp
    Check 'C16 ScenarioClosed clears ScenarioReady at once, generation kept (1, level 0)' ((-not (Lvl $bp)) -and (OutsideIs $idP 1 0))
    Opened $bp; Created $bp
    Check 'C17 next ScenarioOpened: generation 2, level 0 until the Tick' ((Gen $bp) -eq 2 -and (OutsideIs $idP 2 0))
    LTick $bp | Out-Null
    Check 'C18 ... established at the next Tick, generation 2' ((Lvl $bp) -and (OutsideIs $idP 2 1) -and (Est $bp) -eq 2)
    Opened $bp -reload $true
    $lg = ReadLog $pP
    Check 'C19 ScenarioOpened without a ScenarioClosed (reload): the level is cleared FIRST (opened-reset), then the generation moves to 3' ((Gen $bp) -eq 3 -and (-not (Lvl $bp)) -and (OutsideIs $idP 3 0) -and (InOrder $lg @('SR_CLEARED', 'SR_OPENED')) -and (@($lg | Where-Object { $_ -match ' SR_CLEARED ' -and $_ -match 'reason=opened-reset' }).Count -eq 1))
    Created $bp; LTick $bp | Out-Null
    Check 'C20 reload: established again for generation 3' ((Lvl $bp) -and (OutsideIs $idP 3 1) -and (Est $bp) -eq 3)
    $sameThread = $true; foreach ($t in $script:ReadThreads) { if ($t -ne [Threading.Thread]::CurrentThread.ManagedThreadId) { $sameThread = $false } }
    Check ('C21 thread safety: all {0} BVE reads happened on the Tick (calling) thread, none on the control thread' -f $script:ReadThreads.Count) ($sameThread -and $script:ReadThreads.Count -gt 0)
    Check 'C22 PostTick independence: the tracker diagnostic OnPostTick can never establish or change the level' (& {
            $before = Lvl $bp; $g = Gen $bp
            $trkType.GetMethod('OnPostTick', $NPI).Invoke((TrkOf $bp), @()) | Out-Null
            ($before -eq (Lvl $bp)) -and ($g -eq (Gen $bp)) })
    Check 'C22b before Dispose: TS Scoring is ON, Ready is up and ScenarioReady is published (generation 3)' ((NamedEvent $idP 'Ready').Set -and (OutsideIs $idP 3 1))
    LDispose $bp
    $lg = ReadLog $pP
    EndSession $cp; Wait 150
    Check 'C23 Bridge Dispose: ScenarioReady cleared (bridge-dispose) and withdrawn BEFORE Ready is disposed, then BridgeAvailable' (InOrder $lg @('BRIDGE_DISPOSE_BEGIN', 'SR_CLEARED', 'SR_WITHDRAWN', 'READY_DISPOSED', 'AVAIL_DISPOSED', 'BRIDGE_DISPOSE_END'))
    Check 'C24 after Dispose nothing is left (objects gone, control thread ended) and Ticks never publish again' ((-not (AnyObject $idP)) -and ((LiveWorkers) -eq $w0))
    $tickAfter = LTick $bp
    Check 'C25 a Tick after Dispose is harmless and publishes nothing' (($tickAfter -ne $null) -and (-not (AnyObject $idP)))

    # =================================================================================================================
    Write-Host '--- D: SR_WAIT (TS Scoring off at establishment time), null / NaN / exception reads retried on later Ticks'
    $idW = 981004; $pW = NewLogPath 'D-wait'; LogCfgBoth $pW $idW
    $bw = FullLegacy $idW
    Opened $bw; Created $bw; LTicks $bw 5
    $lg = ReadLog $pW
    Check 'D1 TS Scoring off while the scenario loads: not ScenarioReady, nothing published, exactly one SR_WAIT' ((-not (Lvl $bw)) -and (OutsideNone $idW) -and ((EvtLines $lg 'SR_WAIT').Count -eq 1))
    $cw = NewSession $idW; StartSession $cw
    [void](WaitFor { [bool](CtlProp $bw 'HandshakeUp') } 1500)
    Check 'D2 TS Scoring switched on: still not published before the next Tick' ((OutsideNone $idW) -and (-not (Lvl $bw)))
    LTick $bw | Out-Null
    $lg = ReadLog $pW
    Check 'D3 the next Tick establishes (candidate E) for the already open generation 1' ((Lvl $bw) -and (OutsideIs $idW 1 1) -and ((EvtLines $lg 'SR_ESTABLISHED').Count -eq 1))
    Closed $bw; Opened $bw; Created $bw
    $script:SnapCur[$idW] = (Snap 1 'scenario-null')
    LTicks $bw 4
    Check 'D4 reference null: not established, retried on every Tick, nothing published as ready' ((-not (Lvl $bw)) -and (OutsideIs $idW 2 0) -and ((EvtLines (ReadLog $pW) 'SR_PENDING').Count -eq 1))
    $script:SnapCur[$idW] = (Snap 1 'vehiclelocation-nonfinite'); LTicks $bw 2
    Check 'D5 position NaN / Infinity: still not established (reason change is logged once)' ((-not (Lvl $bw)) -and ((EvtLines (ReadLog $pW) 'SR_PENDING').Count -eq 2))
    $script:ReadFail[$idW] = $true; LTicks $bw 2
    Check 'D6 reader throws: not established, no exception reaches the host (Tick still returns)' ((-not (Lvl $bw)) -and ((LTick $bw) -ne $null))
    $script:ReadFail[$idW] = $false; $script:SnapCur[$idW] = (GoodSnap)
    LTick $bw | Out-Null
    Check 'D7 the next safe Tick establishes generation 2 (retry works)' ((Lvl $bw) -and (OutsideIs $idW 2 1) -and (Est $bw) -eq 2)
    EndSession $cw; Wait 100; LDispose $bw

    # =================================================================================================================
    Write-Host '--- F: two BVE processes (PID separation) and the Caller notice contract'
    $idX = 981005; $idY = 981006; $pXY = NewLogPath 'F-two-pids'; LogCfgBoth $pXY $idX
    $bx = FullLegacy $idX; $by = FullLegacy $idY
    $cx = NewSession $idX; $cy = NewSession $idY; StartSession $cx; StartSession $cy
    Opened $bx; Created $bx
    Opened $by; Created $by; Closed $by; Opened $by; Created $by
    [void](WaitFor { (Phase $cx) -eq 'Connected' -and (Phase $cy) -eq 'Connected' } 1500)
    LTick $bx | Out-Null; LTick $by | Out-Null
    [void](WaitFor { [bool](SProp $cx 'ScenarioReadyLevel') -and [bool](SProp $cy 'ScenarioReadyLevel') } 800)
    Check 'F1 each Caller sees only its own generation (X=1, Y=2) and the outside blocks agree' (((SProp $cx 'ScenarioGenerationSeen') -eq 1) -and ((SProp $cy 'ScenarioGenerationSeen') -eq 2) -and (OutsideIs $idX 1 1) -and (OutsideIs $idY 2 1))
    Closed $bx
    Check 'F2 closing X does not change Y' ((OutsideIs $idX 1 0) -and (OutsideIs $idY 2 1))
    EndSession $cx; [void](WaitFor { -not (NamedEvent $idX 'Ready').Exists } 1000)
    Check 'F3 TS Scoring OFF in X withdraws only X (Y keeps Ready and ScenarioReady)' ((-not (NamedEvent $idX 'Ready').Exists) -and (NamedEvent $idY 'Ready').Set -and (OutsideIs $idY 2 1))
    LDispose $bx
    Check 'F4 Dispose of X leaves Y untouched' ((-not (AnyObject $idX)) -and (OutsideIs $idY 2 1))
    Check 'F5 with the Legacy Bridge present the Caller never shows the dependency notice (BridgeAvailable seen), MessageBox contract untouched' (($cx.Recorder.Count -eq 0) -and ($cy.Recorder.Count -eq 0))
    EndSession $cy; Wait 100; LDispose $by
    Check 'F6 both PIDs cleaned up, no control thread alive' ((-not (AnyObject $idX)) -and (-not (AnyObject $idY)) -and ((LiveWorkers) -eq $w0))

    # =================================================================================================================
    Write-Host '--- P: privacy of every log produced by these tests'
    $forbidden = New-Object System.Collections.Generic.List[string]
    foreach ($v in $env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf), 'C:\Users', '\Users\', 'Documents', 'AppData', 'Scoring-Feature', 'gmail') { if ($v) { $forbidden.Add([string]$v) } }
    $hits = 0
    foreach ($lp in $allLogs) { if (Test-Path -LiteralPath $lp) { $txt = [IO.File]::ReadAllText($lp); foreach ($f in $forbidden) { $hits += ([regex]::Matches($txt, [regex]::Escape($f), 'IgnoreCase')).Count }; $hits += ([regex]::Matches($txt, '[A-Za-z]:\\')).Count; $hits += ([regex]::Matches($txt, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count } }
    Check ('P1 no user name, machine name, drive path, user folder or e-mail in any log (' + $allLogs.Count + ' files)') ($hits -eq 0)
    $allText = ($allLogs | ForEach-Object { if (Test-Path -LiteralPath $_) { [IO.File]::ReadAllText($_) } }) -join "`n"
    Check 'P2 Legacy lines carry host=AtsExLegacy only as a fixed word; no scenario / vehicle name and no position or time value' (($allText -notmatch '\b(path|vehicle|scenario|position)=|\blocation=\d') -and ($allText -cnotmatch 'BveEx\.PluginHost|BveTypes|AtsEx\.PluginHost'))
}
finally {
    foreach ($t in $cLog, $lLog) { try { $t.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null } catch { } }
}

Start-Sleep -Milliseconds 300
$left = @($allPids | Where-Object { AnyObject $_ })
Check 'Final: no named object of any test pid is left' ($left.Count -eq 0)
Check 'Final: no Caller monitor thread alive' (([int]$sessionType.GetField('LiveMonitors', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null)) -eq 0)
Check 'Final: no Legacy control thread alive' ((LiveWorkers) -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
