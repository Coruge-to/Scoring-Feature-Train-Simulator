# PHASE B suite, kept in Phase C1 and C3. Phase C3 changes exactly two things here: the one status-text check that said "ScenarioReady not implemented"
# (T1) and NoObjects(), which now also proves the two new ScenarioReady objects are gone. Everything else is the Phase B suite verbatim.
# (The observation log is redirected to a private file) - offline logic test of the REAL Caller session and Bridge code (no BVE, no BveEX runtime, no Python, no UDP, no hooks).
# The DLLs are loaded from memory (no file lock on dist\). The Bridge is created WITHOUT its constructor (BveEX's PluginBuilder is
# not available here); the test calls its internal PublishAvailability() (what the constructor does) and then drives Tick/Dispose.
# The Caller session is created through its internal test constructor with FAKE process ids and a test double for the notice (no
# MessageBox is ever shown). The only side effects are named kernel objects of this PowerShell process and the temporary compile of
# the tiny recorder class; everything is released at the end. This script is ASCII-only on purpose.
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

$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')))
$bridgeAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')))
$sessionType = $callerAsm.GetType('TSScoringPlugin.Handshake.HandshakeSession')
$bridgeType = $bridgeAsm.GetType('TSScoringPlugin.Handshake.TsScoringBridgePrototype')
$nonPublicInstance = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionCtor = $sessionType.GetConstructor($nonPublicInstance, $null, [Type[]]@([int], [Action[string]]), $null)
$tickMethod = $bridgeType.GetMethod('Tick')
$publishMethod = $bridgeType.GetMethod('PublishAvailability', $nonPublicInstance)

# Phase C1: the observation log must never touch the fixed Downloads file during tests - give both DLLs a private file.
New-Item -ItemType Directory -Force (Join-Path $Root 'logs') | Out-Null
$obsPrivate = Join-Path $Root 'logs\phase-b-suite-observation.log'
foreach ($a in @($callerAsm, $bridgeAsm)) { $ot = $a.GetType('TSScoringPlugin.Handshake.ObservationLog'); $ot.GetProperty('TestPath', [Reflection.BindingFlags]'NonPublic,Static').SetValue($null, $obsPrivate) }

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

$allPids = New-Object System.Collections.Generic.List[int]
$live = New-Object System.Collections.Generic.List[object]

function NewSession([int]$fakePid) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    $s = $sessionCtor.Invoke(@($fakePid, $del))
    $live.Add($s)
    return [pscustomobject]@{ Session = $s; Recorder = $rec; Pid = $fakePid }
}
function StartSession($h) { try { $sessionType.GetMethod('Start').Invoke($h.Session, @()) | Out-Null } catch { } }
# Phase M1: BVE's first Tick, as seen by the Caller (a flag only; the monitor thread acts on it)
function TickSession($h) { $sessionType.GetMethod('NotifyTick').Invoke($h.Session, @()) | Out-Null }
function EndSession($h) { try { $sessionType.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { } }
function Phase($h) { return $sessionType.GetProperty('Phase', $nonPublicInstance).GetValue($h.Session).ToString() }
function SessionInt($h, [string]$prop) { return [int]$sessionType.GetProperty($prop, $nonPublicInstance).GetValue($h.Session) }
function SessionBool($h, [string]$prop) { return [bool]$sessionType.GetProperty($prop, $nonPublicInstance).GetValue($h.Session) }
function Status($h) { return [string]$sessionType.GetMethod('BuildStatusText').Invoke($h.Session, @()) }
function LiveMonitors() { return [int]$sessionType.GetField('LiveMonitors', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null) }

# A Bridge object that was NOT yet loaded by BveEX (nothing published). Call LoadBridge to do what the constructor does.
function NewBridge([int]$fakePid) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($bridgeType)
    $flags = [Reflection.BindingFlags]'NonPublic,Instance'
    $bridgeType.GetField('loadQpc', $flags).SetValue($b, [Diagnostics.Stopwatch]::GetTimestamp())
    $bridgeType.GetField('loadUtcTicks', $flags).SetValue($b, [DateTime]::UtcNow.Ticks)
    $bridgeType.GetField('pid', $flags).SetValue($b, $fakePid)
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
function InfoExists([int]$fakePid) {
    try { $m = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting("Local\TSScoringPlugin.v1.$fakePid.BridgeInfo", [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read); $m.Dispose(); return $true } catch { return $false }
}
function ScenarioStateExists([int]$fakePid) {
    try { $m = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting("Local\TSScoringPlugin.v1.$fakePid.ScenarioState", [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read); $m.Dispose(); return $true } catch { return $false }
}
function NoObjects([int]$fakePid) {
    foreach ($k in 'Enabled', 'Stop', 'BridgeAvailable', 'Ready', 'ScenarioReady') { if (ObjectExists $fakePid $k) { return $false } }
    return (-not (InfoExists $fakePid)) -and (-not (ScenarioStateExists $fakePid))
}

# Expected notice text (UTF-8 base64 keeps this script ASCII-only, so any code page reads it the same way)
$expectedNotice = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('VFMgU2NvcmluZ+OBq+OBr0J2ZUVY44GM5b+F6KaB44Gn44GZ44CCDQroqK3lrpog4oaSIOWFpeWKm+ODh+ODkOOCpOOCuSDjgadCdmVFWOOCkuacieWKueOBq+OBl+OAgUJWReOCkuWGjei1t+WLleOBl+OBpuOBj+OBoOOBleOBhOOAgg=='))
$oldLeadA = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('VFMgU2NvcmluZ+OCkuS9v+eUqA=='))   # first words of the old line 1 (must be absent)
$oldLeadB = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('44CM6Kit5a6a44CN'))   # the old bracketed settings word (must be absent)

try {
    Write-Host '--- Test 0: loading the Bridge has exactly one effect: BridgeAvailable'
    $P0 = 910100
    $b0 = NewBridge $P0
    Check 'T0 before load nothing exists' (NoObjects $P0)
    LoadBridge $b0
    Check 'T0 after load: BridgeAvailable exists' (ObjectExists $P0 'BridgeAvailable')
    Check 'T0 after load: no Enabled/Stop/Ready/BridgeInfo was created' ((-not (ObjectExists $P0 'Enabled')) -and (-not (ObjectExists $P0 'Stop')) -and (-not (ObjectExists $P0 'Ready')) -and (-not (InfoExists $P0)))
    Pump @($b0) 300
    Check 'T0 ticking without a Caller creates nothing more (dormant)' ((-not (ObjectExists $P0 'Ready')) -and (-not (InfoExists $P0)) -and (ObjectExists $P0 'BridgeAvailable'))
    DisposeBridge $b0
    Check 'T0 Dispose removes BridgeAvailable' (NoObjects $P0)

    Write-Host '--- Test 1: Bridge first, Caller afterwards'
    $P1 = 910101
    $b1 = NewBridge $P1; LoadBridge $b1
    $c1 = NewSession $P1
    StartSession $c1
    $ms = PumpUntil @($b1) { (Phase $c1) -eq 'Connected' } 600
    Check ("T1 BridgeAvailable existed, Ready established, Connected ({0} ms)" -f $ms) (($ms -ge 0) -and ($ms -lt 500))
    Wait 400
    Check 'T1 no false notice' (($c1.Recorder.Count -eq 0) -and ((Phase $c1) -eq 'Connected'))
    Check 'T1 status: Combined state Connected; ScenarioReady is shown separately and is No (no scenario in this Phase B test)' (((Status $c1) -match 'Combined state   : Connected') -and ((Status $c1) -match 'ScenarioReady    : No'))
    EndSession $c1; Pump @($b1) 200; DisposeBridge $b1
    Check 'T1 cleaned up' (NoObjects $P1)

    Write-Host '--- Test 2: Caller first, Bridge about 450 ms later'
    $P2 = 910102
    $c2 = NewSession $P2
    StartSession $c2
    Wait 450
    $b2 = NewBridge $P2; LoadBridge $b2
    $ms = PumpUntil @($b2) { (Phase $c2) -eq 'Connected' } 500
    Check ("T2 Connected ({0} ms after the Bridge loaded)" -f $ms) ($ms -ge 0)
    Check 'T2 no false notice' ($c2.Recorder.Count -eq 0)
    "      (info) 500 ms target missed flag = {0}" -f (SessionBool $c2 'MissedBridgeTarget')
    EndSession $c2; Pump @($b2) 200; DisposeBridge $b2

    Write-Host '--- Test 3: Caller first, Bridge about 380 ms later (clearly before the 500 ms notice timeout, jitter margin)'
    $P3 = 910103
    $c3 = NewSession $P3
    StartSession $c3
    Wait 380
    $b3 = NewBridge $P3; LoadBridge $b3
    $ms = PumpUntil @($b3) { (Phase $c3) -eq 'Connected' } 500
    Check ("T3 Connected ({0} ms after the Bridge loaded)" -f $ms) ($ms -ge 0)
    Check 'T3 BridgeAvailable seen before the 500 ms timeout: NO notice' (($c3.Recorder.Count -eq 0) -and ((SessionInt $c3 'BridgeSeenCount') -eq 1))
    Check 'T3 status shows no 500 ms timeout' ((Status $c3) -match 'timeout \(500 ms\) occurred: no')
    EndSession $c3; Pump @($b3) 200; DisposeBridge $b3

    Write-Host '--- Test 4: no Bridge at all'
    $P4 = 910104
    $c4 = NewSession $P4
    StartSession $c4
    Wait 380
    Check 'T4 at 380 ms: still WaitingForBridge, no notice' (((Phase $c4) -eq 'WaitingForBridge') -and ($c4.Recorder.Count -eq 0))
    Wait 320
    Check 'T4 after 500 ms with no Tick (Phase M1: the 500 ms is a log line only): BridgeMissingTimedOut and NO notice; the first Tick then brings exactly one notice' (((Phase $c4) -eq 'BridgeMissingTimedOut') -and ($c4.Recorder.Count -eq 0) -and (-not (SessionBool $c4 'NoticeShown')))
    TickSession $c4
    Wait 250
    Check 'T16 notice text is exactly the agreed two lines (old wording absent)' (($c4.Recorder.Last -eq $expectedNotice) -and (-not $c4.Recorder.Last.Contains($oldLeadA)) -and (-not $c4.Recorder.Last.Contains($oldLeadB)) -and ($c4.Recorder.Last -notmatch 'TSScoringPlugin'))
    Check 'T17 MessageBox title is exactly TS Scoring' ([string]$sessionType.GetField('ProductDisplayName', [Reflection.BindingFlags]'NonPublic,Static').GetRawConstantValue() -ceq 'TS Scoring')
    Wait 1200
    Check 'T4 no second notice (one notice per Caller instance)' ($c4.Recorder.Count -eq 1)
    Check 'T4 status: Bridge missing, timed out' (((Status $c4) -match 'Combined state   : Bridge missing, timed out') -and ((Status $c4) -match 'timeout \(500 ms\) occurred: yes'))
    EndSession $c4

    Write-Host '--- Test 5 + 15: Bridge loaded but no Ready for a long time (no Tick = no scenario being driven)'
    $P5 = 910105
    $b5 = NewBridge $P5; LoadBridge $b5      # BveEX loaded the Bridge, but Tick is never called (menus / no scenario)
    $c5 = NewSession $P5
    StartSession $c5
    Wait 2300
    Check 'T5 2.3 s without Ready: NO BveEX notice' ($c5.Recorder.Count -eq 0)
    Check 'T5 phase WaitingForHandshake, status Bridge loaded, waiting for handshake' (((Phase $c5) -eq 'WaitingForHandshake') -and ((Status $c5) -match 'Combined state   : Bridge loaded, waiting for handshake') -and ((Status $c5) -match 'BridgeAvailable  : Present') -and ((Status $c5) -match 'Ready            : Missing'))
    $ms = PumpUntil @($b5) { (Phase $c5) -eq 'Connected' } 600
    Check ("T15 when the scenario finally runs (Tick starts) the handshake completes with no notice ({0} ms)" -f $ms) (($ms -ge 0) -and ($c5.Recorder.Count -eq 0))
    EndSession $c5; Pump @($b5) 200; DisposeBridge $b5

    Write-Host '--- Test 6: Connected, then only Ready disappears (Bridge stays)'
    $P6 = 910106
    $b6 = NewBridge $P6; LoadBridge $b6
    $c6 = NewSession $P6
    StartSession $c6
    [void](PumpUntil @($b6) { (Phase $c6) -eq 'Connected' } 600)
    $rh = [Threading.EventWaitHandle]::OpenExisting("Local\TSScoringPlugin.v1.$P6.Ready")
    $rh.Reset() | Out-Null
    Pump @($b6) 1400
    Check 'T6 Ready gone but BridgeAvailable present for 1.4 s: WaitingForHandshake, NO notice' (((Phase $c6) -eq 'WaitingForHandshake') -and ($c6.Recorder.Count -eq 0) -and ((SessionInt $c6 'ReadyLostCount') -eq 1) -and ((SessionInt $c6 'BridgeLostCount') -eq 0))
    $rh.Set() | Out-Null
    Pump @($b6) 150
    Check 'T6 Ready back: Connected again' ((Phase $c6) -eq 'Connected')
    $rh.Dispose()

    Write-Host '--- Test 7/8/9: Connected, then Ready and BridgeAvailable both vanish; later the Bridge returns; vanishes again'
    DisposeBridge $b6
    Wait 380
    Check 'T7 at 380 ms after both vanished: WaitingForBridge, no notice' (((Phase $c6) -eq 'WaitingForBridge') -and ($c6.Recorder.Count -eq 0))
    Wait 320
    Check 'T7 after 500 ms: exactly one notice, Bridge missing, timed out' (((Phase $c6) -eq 'BridgeMissingTimedOut') -and ($c6.Recorder.Count -eq 1))
    $b6b = NewBridge $P6; LoadBridge $b6b
    $ms = PumpUntil @($b6b) { (Phase $c6) -eq 'Connected' } 600
    Check ("T8 Bridge back: handshake and Connected ({0} ms), no extra notice, the one-per-instance latch stays taken" -f $ms) (($ms -ge 0) -and ($c6.Recorder.Count -eq 1) -and (-not (SessionBool $c6 'NoticeArmed')) -and (SessionBool $c6 'NoticeShown'))
    DisposeBridge $b6b
    Wait 800
    Check 'T9 second absence stretch: NO second notice (total stays 1, one per Caller instance), Bridge missing, timed out' (($c6.Recorder.Count -eq 1) -and ((Phase $c6) -eq 'BridgeMissingTimedOut'))
    Check 'T9 counters: Bridge seen 2, lost 2' (((SessionInt $c6 'BridgeSeenCount') -eq 2) -and ((SessionInt $c6 'BridgeLostCount') -eq 2))
    EndSession $c6
    Wait 200
    Check 'T7-9 session ended cleanly' (((Phase $c6) -eq 'Disposed') -and (NoObjects $P6))

    Write-Host '--- Test 10: Bridge vanishes, the Caller is disposed right away'
    $P10 = 910110
    $b10 = NewBridge $P10; LoadBridge $b10
    $c10 = NewSession $P10
    StartSession $c10
    [void](PumpUntil @($b10) { (Phase $c10) -eq 'Connected' } 600)
    DisposeBridge $b10
    Wait 80
    EndSession $c10
    Wait 1300
    Check 'T10 no notice after Dispose, phase Disposed, monitor ended' (($c10.Recorder.Count -eq 0) -and ((Phase $c10) -eq 'Disposed') -and (-not (SessionBool $c10 'MonitorAlive')))
    Check 'T10 every object released' (NoObjects $P10)

    Write-Host '--- Test 11: OFF -> ON repeated with a Bridge that stays loaded'
    $P11 = 910111
    $b11 = NewBridge $P11; LoadBridge $b11
    $ok11 = $true
    for ($i = 1; $i -le 5; $i++) {
        $s11 = NewSession $P11
        StartSession $s11
        $ms = PumpUntil @($b11) { (Phase $s11) -eq 'Connected' } 600
        if (($ms -lt 0) -or ($s11.Recorder.Count -ne 0)) { $ok11 = $false }
        EndSession $s11
        Pump @($b11) 150
        if (SessionBool $s11 'MonitorAlive') { $ok11 = $false }
        if (-not (ObjectExists $P11 'BridgeAvailable')) { $ok11 = $false }
    }
    Check 'T11 five cycles: new Enabled, BridgeAvailable detected, Ready, no notice, old monitors ended' $ok11
    Check 'T11 live monitor threads back to zero' ((LiveMonitors) -eq 0)
    $sd = NewSession $P11
    StartSession $sd; StartSession $sd
    Wait 100
    Check 'T11 calling Start twice never creates a second monitor thread' ((LiveMonitors) -eq 1)
    EndSession $sd; EndSession $sd
    Wait 200
    Check 'T11 End twice is harmless and the monitor ends' ((LiveMonitors) -eq 0)
    DisposeBridge $b11
    Check 'T11 nothing left' (NoObjects $P11)

    Write-Host '--- Test 12: two BVE process ids side by side'
    $PA = 910120; $PB = 910121
    $ba = NewBridge $PA; $bb = NewBridge $PB; LoadBridge $ba; LoadBridge $bb
    $ca = NewSession $PA; $cb = NewSession $PB
    StartSession $ca; StartSession $cb
    $ms = PumpUntil @($ba, $bb) { ((Phase $ca) -eq 'Connected') -and ((Phase $cb) -eq 'Connected') } 600
    Check ("T12 both connected independently ({0} ms)" -f $ms) ($ms -ge 0)
    DisposeBridge $bb
    Pump @($ba) 1350
    Check 'T12 B timed out with one notice, A untouched (Connected, no notice)' (((Phase $cb) -eq 'BridgeMissingTimedOut') -and ($cb.Recorder.Count -eq 1) -and ((Phase $ca) -eq 'Connected') -and ($ca.Recorder.Count -eq 0))
    EndSession $ca; EndSession $cb
    Pump @($ba) 150
    DisposeBridge $ba
    Check 'T12 both pairs cleaned up' ((NoObjects $PA) -and (NoObjects $PB))

    Write-Host '--- Test 13: no BridgeInfo at all'
    $P13 = 910130
    $c13 = NewSession $P13
    StartSession $c13
    $avl = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$P13.BridgeAvailable")
    $rdy = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$P13.Ready")
    $avl.Set() | Out-Null; $rdy.Set() | Out-Null
    Wait 200
    Check 'T13 handshake succeeds without BridgeInfo' ((Phase $c13) -eq 'Connected')
    Check 'T13 status says BridgeInfo: Unavailable' ((Status $c13) -match 'BridgeInfo: Unavailable')
    EndSession $c13
    $avl.Dispose(); $rdy.Dispose()

    Write-Host '--- Test 14: corrupt / old-version / short BridgeInfo'
    foreach ($variant in 'garbage', 'oldversion', 'short') {
        $pv = 910140 + @('garbage', 'oldversion', 'short').IndexOf($variant)
        $c14 = NewSession $pv
        StartSession $c14
        $size = if ($variant -eq 'short') { 8 } else { 128 }
        $mmf = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew("Local\TSScoringPlugin.v1.$pv.BridgeInfo", $size)
        $view = $mmf.CreateViewAccessor(0, $size)
        for ($o = 0; $o -lt $size; $o++) { $view.Write($o, [byte]0xFF) }
        if ($variant -eq 'oldversion') { $view.Write(0, [int]2); $view.Write(4, [int]64) }
        $avl = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$pv.BridgeAvailable")
        $rdy = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$pv.Ready")
        $avl.Set() | Out-Null; $rdy.Set() | Out-Null
        Wait 200
        Check ("T14 [{0}] handshake still succeeds" -f $variant) ((Phase $c14) -eq 'Connected')
        Check ("T14 [{0}] only the timing is Unavailable" -f $variant) ((Status $c14) -match 'BridgeInfo: Unavailable')
        EndSession $c14
        $avl.Dispose(); $rdy.Dispose(); $view.Dispose(); $mmf.Dispose()
    }
}
finally {
    foreach ($h in $live) { try { $sessionType.GetMethod('End').Invoke($h, @()) | Out-Null } catch { } }
}

Start-Sleep -Milliseconds 300
$leftovers = @($allPids | Where-Object { -not (NoObjects $_) })
Check 'Final: no named object of any test pid is left' ($leftovers.Count -eq 0)
Check 'Final: no monitor thread alive' ((LiveMonitors) -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
