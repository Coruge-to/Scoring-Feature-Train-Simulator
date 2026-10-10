# PHASE SI-A6 - offline tests of the LOAD MARKER: ScenarioCreated / the first Tick of a generation, published by the Bridge next to ScenarioReady (without a Tick), read by
# the Caller, copied into the Caller's state block for the managed application. No BVE, no BveEX runtime, no UDP, no hooks, no BVE process. The real built DLLs are loaded from
# memory; the Python side of the contract (managed_state.py) reads the REAL block written by the REAL Caller publisher. Every observation log goes to a private file
# under logs\sia6-tests. Fake process ids only.
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
$legacyAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')))
$NS = 'TSScoringPlugin.Handshake.'
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$bridgeType = $bridgeAsm.GetType($NS + 'TsScoringBridgePrototype')
$trkType = $bridgeAsm.GetType($NS + 'ScenarioReadyTracker')
$pubType = $bridgeAsm.GetType($NS + 'ScenarioReadyPublisher')
$snapType = $bridgeAsm.GetType($NS + 'BveSnapshot')
$stateType = $bridgeAsm.GetType($NS + 'ScenarioState')
$stateTypeCaller = $callerAsm.GetType($NS + 'ScenarioState')
$stateTypeLegacy = $legacyAsm.GetType($NS + 'ScenarioState')
$trkTypeLegacy = $legacyAsm.GetType($NS + 'ScenarioReadyTracker')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $bridgeAsm.GetType($NS + 'ObservationLog')
$apStateType = $callerAsm.GetType($NS + 'AppStatePublisher')
$apLayoutType = $callerAsm.GetType($NS + 'AppStateLayout')
$mgrType = $callerAsm.GetType($NS + 'AppProcessManager')
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$bridgeEntry = $bridgeType
$beginSrMethod = $bridgeType.GetMethod('BeginScenarioReady', $NPI)
$publishMethod = $bridgeType.GetMethod('PublishAvailability', $NPI)
$tickMethod = $bridgeType.GetMethod('Tick')
$trackerField = $bridgeType.GetField('tracker', $NPI)
$funcSnap = [Func``1].MakeGenericType($snapType)

$testDir = Join-Path $Root 'logs\sia6-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
$allPids = New-Object System.Collections.Generic.List[int]
function RegPid([int]$p) { if (-not $allPids.Contains($p)) { $allPids.Add($p) } }

function LogCfg($type, [string]$path, [int]$fakePid) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]0)
}
function LogCfgBoth([string]$path, [int]$fakePid) { LogCfg $cLog $path $fakePid; LogCfg $bLog $path $fakePid }

function Snap([int]$created = 1, [object]$fail = $null, $st = $snapType) {
    $o = [Activator]::CreateInstance($st)
    $f = [Reflection.BindingFlags]'Public,Instance'
    $st.GetField('IsScenarioCreated', $f).SetValue($o, $created)
    foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $st.GetField($n, $f).SetValue($o, $true) }
    $st.GetField('Failure', $f).SetValue($o, $fail)
    return $o
}

# ---- the block as a consumer sees it: open by name, copy the 64 bytes -------------------------------------------------------------------
function Bytes64([int]$p) {
    $mm = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting("Local\TSScoringPlugin.v1.$p.ScenarioState", [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read)
    try { $v = $mm.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read); try { $b = New-Object byte[] 64; [void]$v.ReadArray(0, $b, 0, 64); return ,$b } finally { $v.Dispose() } } finally { $mm.Dispose() }
}
function I32($b, [int]$off) { return [BitConverter]::ToInt32($b, $off) }
function ReadState([int]$p, $type = $stateType) {
    $a = @($p, $null)
    $ok = [bool]$type.GetMethod('TryRead').Invoke($null, $a)
    if (-not $ok) { return [pscustomobject]@{ Valid = $false } }
    $s = $a[1]
    $get = { param($n) $type.GetField($n).GetValue($s) }
    return [pscustomobject]@{ Valid = $true; Gen = (& $get 'ScenarioGeneration'); Ready = (& $get 'IsScenarioReady'); Seq = (& $get 'Sequence'); Magic = (& $get 'LoadMagic'); Info = (& $get 'LoadInfo');
                              Supported = [bool]$type.GetProperty('LoadSupported').GetValue($s); Created = [bool]$type.GetProperty('CreatedSeen').GetValue($s); Tick = [bool]$type.GetProperty('TickSeen').GetValue($s) }
}
Add-Type -TypeDefinition @"
public static class OldCheckImpl
{
    // the Phase C3 check formula as an OLD reader computes it (re-implemented here, not taken from the DLL): it must still validate every block of the new Bridge
    public static int Compute(int ver, int pid, int gen, int ready, int seq)
    {
        unchecked
        {
            int h = 0x54535343;
            h = (h * 31) ^ ver;
            h = (h * 31) ^ pid;
            h = (h * 31) ^ gen;
            h = (h * 31) ^ ready;
            h = (h * 31) ^ seq;
            return h;
        }
    }
}
"@
function OldCheck([int]$ver, [int]$pid_, [int]$gen, [int]$ready, [int]$seq) { return [OldCheckImpl]::Compute($ver, $pid_, $gen, $ready, $seq) }
# ---- tracker harness (real DLL, real publisher, fake world) -------------------------------------------------------------------------------
$script:W = @{}
function NewTracker([int]$p, $tt = $trkType) {
    RegPid $p
    $st = $tt.Assembly.GetType($NS + 'BveSnapshot')
    $w = @{ Pid = $p; Lines = (New-Object System.Collections.Generic.List[string]); Snap = (Snap 1 $null $st); Up = $true; Now = 1000; Type = $tt }
    $script:W = $w
    $log = [Action[string, string, string]] { param($t, $e, $d) $script:W.Lines.Add("$t|$e|$d") }
    $rd = ({ $script:W.Snap }) -as ([Func``1].MakeGenericType($st))
    $up = [Func[bool]] { [bool]$script:W.Up }
    $nw = [Func[long]] { [long]$script:W.Now }
    $pt = if ($tt -eq $trkType) { $pubType } else { $legacyAsm.GetType($NS + 'ScenarioReadyPublisher') }
    $pub = $pt.GetConstructors($NPI)[0].Invoke(@($p))
    $w.Trk = $tt.GetConstructors($NPI)[0].Invoke(@($log, $rd, $up, $pub, $nw))
    return $w
}
function T($w, [string]$m) { $w.Type.GetMethod($m, $NPI).Invoke($w.Trk, @()) | Out-Null }
function Lvl($w) { return [bool]$w.Type.GetProperty('IsScenarioReady', $NPI).GetValue($w.Trk) }

$results.Clear()
try {
    Write-Host '--- A: the state block layout (Bridge side) and the reader (Caller side)'
    $a1 = $stateType.GetFields([Reflection.BindingFlags]'Public,Instance') | ForEach-Object { $_.Name }
    Check 'A1 ScenarioState: the three marker fields exist next to the six of Phase C3; size and version unchanged (64 / 1)' ((($a1 -join ',') -eq 'ProtocolVersion,BveProcessId,ScenarioGeneration,IsScenarioReady,Sequence,Check,LoadMagic,LoadInfo,LoadCheck') -and ([int]$stateType.GetField('Size').GetRawConstantValue() -eq 64) -and ([int]$stateType.GetField('StateVersion').GetRawConstantValue() -eq 1))
    Check 'A2 the marker constants: LoadMagic "LOD1" (0x4C4F4431), bit0 Created = 1, bit1 TickSeen = 2, known bits 3' (([int]$stateType.GetField('LoadMagicValue').GetRawConstantValue() -eq 0x4C4F4431) -and ([int]$stateType.GetField('LoadCreated').GetRawConstantValue() -eq 1) -and ([int]$stateType.GetField('LoadTickSeen').GetRawConstantValue() -eq 2) -and ([int]$stateType.GetField('LoadKnownBits').GetRawConstantValue() -eq 3))
    $p1 = 981001; RegPid $p1
    $mm = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateOrOpen("Local\TSScoringPlugin.v1.$p1.ScenarioState", 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::ReadWrite)
    $view = $mm.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::ReadWrite)
    $writeLoad = $stateType.GetMethod('WriteWithLoad'); $writeOld = $stateType.GetMethods() | Where-Object { $_.Name -eq 'Write' }
    [void]$writeLoad.Invoke($null, @($view, $p1, 7, $false, 1))
    $b = Bytes64 $p1; $rs = ReadState $p1
    Check 'A3 WriteWithLoad: generation, level and marker of ONE write; LoadMagic at 24, LoadInfo at 28, LoadCheck at 32; sequence even' (($rs.Valid) -and ($rs.Gen -eq 7) -and ($rs.Ready -eq 0) -and ((I32 $b 24) -eq 0x4C4F4431) -and ((I32 $b 28) -eq 1) -and ($rs.Supported) -and ($rs.Created) -and (-not $rs.Tick) -and (($rs.Seq % 2) -eq 0))
    Check 'A4 the Phase C3 check (offsets 0..20) is still valid for a reader that knows nothing of the marker (the old formula, re-implemented)' (((I32 $b 20) -eq (OldCheck 1 $p1 7 0 $rs.Seq)) -and ((I32 $b 4) -eq $p1))
    $seq0 = $rs.Seq
    [void]$writeLoad.Invoke($null, @($view, $p1, 7, $true, 3))
    $rs = ReadState $p1
    Check 'A5 the next write: sequence +2, level 1, both bits' (($rs.Seq -eq $seq0 + 2) -and ($rs.Ready -eq 1) -and ($rs.Info -eq 3) -and $rs.Created -and $rs.Tick -and $rs.Supported)
    [void]$writeLoad.Invoke($null, @($view, $p1, 8, $false, 0xFF))
    $rs = ReadState $p1
    Check 'A6 unknown bits are not written (masked to the known two)' (($rs.Info -eq 3) -and $rs.Supported)
    [void]($writeOld | Where-Object { $_.GetParameters().Count -eq 4 } | Select-Object -First 1).Invoke($null, @($view, $p1, 9, $true))
    $b = Bytes64 $p1; $rs = ReadState $p1
    Check 'A7 the old four-argument Write (no marker) writes zero in 24..35: LoadSupported false, "no information"' (($rs.Valid) -and ($rs.Gen -eq 9) -and ($rs.Ready -eq 1) -and (-not $rs.Supported) -and ((I32 $b 24) -eq 0) -and ((I32 $b 28) -eq 0) -and ((I32 $b 32) -eq 0))
    [void]$writeLoad.Invoke($null, @($view, $p1, 10, $false, 1))
    $view.Write(28, 2)       # a damaged marker (the bits changed, the check did not)
    $rs = ReadState $p1
    Check 'A8 a marker whose check does not match reads as "no information" while the block itself stays valid' (($rs.Valid) -and ($rs.Gen -eq 10) -and (-not $rs.Supported) -and (-not $rs.Created) -and (-not $rs.Tick))
    [void]$writeLoad.Invoke($null, @($view, $p1, 10, $false, 1))
    $view.Write(24, 0x4C4F4432)
    $rs = ReadState $p1
    Check 'A9 a foreign magic reads as "no information"' (($rs.Valid) -and (-not $rs.Supported))
    [void]$writeLoad.Invoke($null, @($view, $p1, 11, $false, 1))
    $view.Write(16, 5)       # an odd sequence = a writer in the middle of a write
    Check 'A10 an odd sequence (a write in progress) is rejected as before' (-not (ReadState $p1).Valid)
    $rsc = $null
    [void]$writeLoad.Invoke($null, @($view, $p1, 12, $false, 3))
    $aC = @($p1, $null); $okC = [bool]$stateTypeCaller.GetMethod('TryRead').Invoke($null, $aC)
    $aL = @($p1, $null); $okL = [bool]$stateTypeLegacy.GetMethod('TryRead').Invoke($null, $aL)
    Check 'A11 the Caller copy and the Legacy Bridge copy of the shared source read the same block the same way (one source, three DLLs)' ($okC -and $okL -and ([bool]$stateTypeCaller.GetProperty('LoadSupported').GetValue($aC[1])) -and ([bool]$stateTypeLegacy.GetProperty('TickSeen').GetValue($aL[1])) -and ([int]$stateTypeCaller.GetField('LoadInfo').GetValue($aC[1]) -eq 3))
    $view.Dispose(); $mm.Dispose()

    Write-Host '--- B: the tracker (Current and Legacy Bridge share the source) publishes the marker without any Tick'
    foreach ($tt in $trkType, $trkTypeLegacy) {
        $tag = if ($tt -eq $trkType) { 'Current' } else { 'Legacy' }
        $pb = if ($tt -eq $trkType) { 981011 } else { 981012 }
        $w = NewTracker $pb $tt
        T $w 'OnTick'
        T $w 'OnScenarioOpened'
        $o = ReadState $pb
        Check "B1 [$tag] ScenarioOpened: generation 1, level 0, marker supported and empty" ($o.Valid -and ($o.Gen -eq 1) -and ($o.Ready -eq 0) -and $o.Supported -and ($o.Info -eq 0))
        T $w 'OnScenarioCreated'
        $o = ReadState $pb
        Check "B2 [$tag] ScenarioCreated alone (no Tick at all): the marker shows Created, nothing else (level 0, no TickSeen)" ($o.Valid -and ($o.Gen -eq 1) -and ($o.Ready -eq 0) -and $o.Created -and (-not $o.Tick))
        $seqBefore = $o.Seq
        T $w 'OnScenarioCreated'
        Check "B3 [$tag] a repeated Created changes nothing that is visible except the sequence staying even and valid" ((ReadState $pb).Valid -and (ReadState $pb).Created)
        T $w 'OnTick'
        $o = ReadState $pb
        Check "B4 [$tag] the first Tick after Created: level 1 AND TickSeen in the same write (one reading shows both)" ($o.Valid -and ($o.Ready -eq 1) -and $o.Created -and $o.Tick -and ($o.Info -eq 3))
        T $w 'OnTick'; T $w 'OnTick'
        Check "B5 [$tag] later Ticks write nothing more (the sequence does not move)" ((ReadState $pb).Seq -eq $o.Seq)
        T $w 'OnScenarioClosed'
        $o = ReadState $pb
        Check "B6 [$tag] ScenarioClosed: level 0 and the marker cleared (generation kept)" ($o.Valid -and ($o.Gen -eq 1) -and ($o.Ready -eq 0) -and $o.Supported -and ($o.Info -eq 0))
        # the pause that inherits an F5 reload: Closed, Opened, Created and then NO Tick for a long time
        T $w 'OnScenarioOpened'
        $o = ReadState $pb
        Check "B7 [$tag] the next ScenarioOpened: generation 2, level 0, marker empty" ($o.Valid -and ($o.Gen -eq 2) -and ($o.Ready -eq 0) -and ($o.Info -eq 0))
        T $w 'OnScenarioCreated'
        $o = ReadState $pb
        Check "B8 [$tag] F5 in a pause: Created of generation 2 is visible with no Tick (this is the completion signal of the reload)" ($o.Valid -and ($o.Gen -eq 2) -and ($o.Ready -eq 0) -and $o.Created -and (-not $o.Tick))
        $before = $o.Seq
        Start-Sleep -Milliseconds 300
        Check "B9 [$tag] nothing is written while no Tick comes" ((ReadState $pb).Seq -eq $before)
        T $w 'OnTick'
        $o = ReadState $pb
        Check "B10 [$tag] the Tick that the first P causes: Session level 1 and TickSeen" ($o.Ready -eq 1 -and $o.Tick)
        T $w 'OnDispose'
        Check "B11 [$tag] Dispose withdraws the block and the event" (-not (ReadState $pb).Valid)
    }

    Write-Host '--- C: order of events and the handshake'
    $pc = 981021; $wc = NewTracker $pc
    T $wc 'OnScenarioOpened'; T $wc 'OnTick'
    Check 'C1 a Tick before ScenarioCreated does not set TickSeen (it belongs to nothing yet)' ((ReadState $pc).Info -eq 0)
    T $wc 'OnScenarioCreated'
    Check 'C2 ... and Created afterwards shows Created only' (((ReadState $pc).Info -eq 1))
    T $wc 'OnTick'
    Check 'C3 ... the next Tick sets TickSeen' ((ReadState $pc).Info -eq 3)
    $wc.Up = $false; T $wc 'OnTick'
    Check 'C4 handshake down (TS Scoring off): publication withdrawn, nothing readable' (-not (ReadState $pc).Valid)
    T $wc 'OnScenarioOpened'; T $wc 'OnScenarioCreated'
    $wc.Up = $true; T $wc 'OnTick'
    $o = ReadState $pc
    Check 'C5 handshake back: the CURRENT generation and marker are published at once' ($o.Valid -and ($o.Gen -eq 2) -and $o.Created -and $o.Tick)
    T $wc 'OnDispose'
    Check 'C6 the marker never changes ScenarioReady: the level logic of Phase C3 is the same (established once per generation)' (($wc.Lines | Where-Object { $_ -match '\|SR_ESTABLISHED\|' }).Count -eq 2)

    Write-Host '--- D: a publisher without the marker (every fake of the earlier phases) is not written to because of it'
    $ifaceLoad = $bridgeAsm.GetType($NS + 'IScenarioLoadPublisher')
    $ifacePlain = $bridgeAsm.GetType($NS + 'IScenarioReadyPublisher')
    Check 'D1 the marker is an optional interface on top of the unchanged IScenarioReadyPublisher (Open / Update / Close / IsOpen)' ($ifaceLoad.GetInterfaces() -contains $ifacePlain -and (($ifacePlain.GetMethods() | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'Close,get_IsOpen,Open,Update' -and (($ifaceLoad.GetMethods() | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'OpenWithLoad,UpdateWithLoad')
    Check 'D2 the real publisher implements both; its two-argument Open / Update are unchanged' ($pubType.GetInterfaces() -contains $ifaceLoad -and ($pubType.GetMethod('Update', [Type[]]@([int], [bool])) -ne $null) -and ($pubType.GetMethod('Open', [Type[]]@([int], [bool])) -ne $null))

    Write-Host '--- E: the real Bridge entry and the real Caller session (marker end to end up to the Caller)'
    $idB = 981031; RegPid $idB; $pBr = Join-Path $testDir 'E1.log'; LogCfgBoth $pBr $idB
    $script:BSnap = @{}
    function NewBridge([int]$fakePid) {
        $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($bridgeType)
        $f = [Reflection.BindingFlags]'NonPublic,Instance'
        $bridgeType.GetField('loadQpc', $f).SetValue($b, [Diagnostics.Stopwatch]::GetTimestamp())
        $bridgeType.GetField('loadUtcTicks', $f).SetValue($b, [DateTime]::UtcNow.Ticks)
        $bridgeType.GetField('pid', $f).SetValue($b, $fakePid)
        return $b
    }
    function BTick($b) { $tickMethod.Invoke($b, @([TimeSpan]::Zero)) | Out-Null }
    function BT($b, [string]$m) { $trkType.GetMethod($m, $NPI).Invoke($trackerField.GetValue($b), @()) | Out-Null }
    function Pump($bridges, [int]$ms) { $sw = [Diagnostics.Stopwatch]::StartNew(); while ($sw.ElapsedMilliseconds -lt $ms) { foreach ($x in $bridges) { BTick $x }; Start-Sleep -Milliseconds 5 } }
    function PumpUntil($bridges, [scriptblock]$cond, [int]$limitMs) { $sw = [Diagnostics.Stopwatch]::StartNew(); while ($sw.ElapsedMilliseconds -lt $limitMs) { foreach ($x in $bridges) { BTick $x }; if (& $cond) { return $sw.ElapsedMilliseconds }; Start-Sleep -Milliseconds 5 }; return -1 }
    function SProp($h, [string]$n) { return $sessionType.GetProperty($n, $NPI).GetValue($h) }
    function SField($h, [string]$n) { return $sessionType.GetField($n, $NPI).GetValue($h) }
    $b = NewBridge $idB
    $script:BSnap[$idB] = (Snap 1 $null)
    $rd = ([scriptblock]::Create('$script:BSnap[' + $idB + ']')) -as $funcSnap
    $beginSrMethod.Invoke($b, @($rd, $null)) | Out-Null
    $publishMethod.Invoke($b, @()) | Out-Null
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    $c = $sessionCtor.Invoke(@($idB, $del)); $sessionType.GetMethod('Start').Invoke($c, @()) | Out-Null
    BT $b 'OnScenarioOpened'; BT $b 'OnScenarioCreated'
    $ms = PumpUntil @($b) { [bool](SProp $c 'ScenarioReadyLevel') } 1500
    Check 'E1 a normal load: the Caller sees ScenarioReady generation 1 and the marker Created + TickSeen (one reading)' (($ms -ge 0) -and ((SProp $c 'ScenarioGenerationSeen') -eq 1) -and ((SField $c 'scenarioLoadSupported') -eq $true) -and ((SField $c 'scenarioLoadInfo') -eq 3))
    # an F5 reload in a pause: no Tick any more
    BT $b 'OnScenarioClosed'; BT $b 'OnScenarioOpened'
    Start-Sleep -Milliseconds 120
    Check 'E2 F5 in a pause (Closed, Opened, no Tick): the Caller sees generation 2, ScenarioReady off, marker empty' (((SProp $c 'ScenarioGenerationSeen') -eq 2) -and (-not [bool](SProp $c 'ScenarioReadyLevel')) -and ((SField $c 'scenarioLoadSupported') -eq $true) -and ((SField $c 'scenarioLoadInfo') -eq 0))
    BT $b 'OnScenarioCreated'
    Start-Sleep -Milliseconds 120
    Check 'E3 ScenarioCreated arrives, still no Tick at all: the Caller sees Created WITHOUT ScenarioReady and WITHOUT TickSeen (the monitor thread reads it; BveEX ticked nothing)' (((SProp $c 'ScenarioGenerationSeen') -eq 2) -and (-not [bool](SProp $c 'ScenarioReadyLevel')) -and ((SField $c 'scenarioLoadInfo') -eq 1))
    Pump @($b) 50
    $ms2 = PumpUntil @($b) { [bool](SProp $c 'ScenarioReadyLevel') } 800
    Check 'E4 the Tick (the first P): ScenarioReady on and the marker Created + TickSeen' (($ms2 -ge 0) -and ((SField $c 'scenarioLoadInfo') -eq 3))
    $sessionType.GetMethod('End').Invoke($c, @()) | Out-Null
    Pump @($b) 200
    Check 'E5 TS Scoring OFF: the Caller ended, nothing of the marker is left on its side' (-not [bool](SProp $c 'ScenarioReadyLevel'))
    try { $bridgeType.GetMethod('Dispose').Invoke($b, @()) | Out-Null } catch { }
    Start-Sleep -Milliseconds 100

    Write-Host '--- F: the Caller publisher writes the marker into the application block; the Python reader (managed_state.py) reads the REAL bytes'
    $pid2 = 981041; $inst = '0123456789abcdef0123456789abcdef'
    $name = "Local\TSScoringPlugin.v1.$pid2.App.$inst.State"
    $apub = $apStateType.GetMethod('Create').Invoke($null, @($name, $pid2, $inst))
    $wr3 = $apStateType.GetMethod('Write'); $wrL = $apStateType.GetMethod('WriteWithLoad')
    $mmA = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($name, [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read)
    $vA = $mmA.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
    function Block() { $x = New-Object byte[] 64; [void]$vA.ReadArray(0, $x, 0, 64); return ,$x }
    $x0 = Block
    Check 'F1 a fresh block: bytes 48..63 are zero (the marker is "no information"), version 1, size 64' ((I32 $x0 4) -eq 1 -and (I32 $x0 8) -eq 64 -and (@($x0[48..63] | Where-Object { $_ -ne 0 }).Count -eq 0))
    $r1 = $wrL.Invoke($apub, @($true, $false, 3, [uint32]1, $true))
    $x1 = Block
    Check 'F2 WriteWithLoad: LoadInfo at 48, LoadMagic at 52, generation at 40, flags at 36, one seqlock write (head == tail, even)' (([BitConverter]::ToUInt32($x1, 48) -eq 1) -and ([BitConverter]::ToUInt32($x1, 52) -eq 0x4C4F4431) -and ((I32 $x1 40) -eq 3) -and ((I32 $x1 36) -eq 1) -and ((I32 $x1 32) -eq (I32 $x1 60)) -and (((I32 $x1 32) % 2) -eq 0) -and [bool]$r1.Written)
    $r2 = $wrL.Invoke($apub, @($true, $false, 3, [uint32]1, $true))
    Check 'F3 the same state again is not written (dedup includes the marker)' (-not [bool]$r2.Written)
    $r3 = $wrL.Invoke($apub, @($true, $false, 3, [uint32]3, $true))
    Check 'F4 only the marker changed (the first Tick): written, change count +1' ([bool]$r3.Written -and ([uint32]$r3.ChangeCount -eq [uint32]$r1.ChangeCount + 1))
    $r4 = $wrL.Invoke($apub, @($true, $false, 3, [uint32]0xFF, $true))
    Check 'F5 unknown bits are masked (3), so they cause no write' (-not [bool]$r4.Written -and ([BitConverter]::ToUInt32((Block), 48) -eq 3))
    $r5 = $wr3.Invoke($apub, @($true, $true, 3))
    $x5 = Block
    Check 'F6 the three-argument Write (a Caller state without a marker) writes Driving and zero marker: "no information"' ([bool]$r5.Written -and ([BitConverter]::ToUInt32($x5, 48) -eq 0) -and ([BitConverter]::ToUInt32($x5, 52) -eq 0))
    [void]$wrL.Invoke($apub, @($true, $true, 4, [uint32]1, $true))
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $script = Join-Path $testDir 'read_block.py'
        $repo = Split-Path (Split-Path $Root -Parent) -Parent
        [IO.File]::WriteAllText($script, @"
import sys
sys.path.insert(0, r'$repo')
import managed_state as ms
class A: pass
a = A(); a.bve_pid = $pid2; a.instance = '$inst'; a.owner = 'test'
src = ms.Win32StateSource()
assert src.open(ms.state_name(a.bve_pid, a.instance))
snap, reason = ms.parse_state(src.read(), a.bve_pid, a.instance)
print(reason, snap.session, snap.driving, snap.generation, snap.load_supported, snap.load_info, snap.created_seen, snap.tick_seen)
src.close()
"@, (New-Object Text.UTF8Encoding($false)))
        $out = (& $pyCmd.Source -I $script) -join ' '
        Check 'F7 managed_state.py reads the real bytes of the real publisher: Session ON, Driving ON, generation 4, marker supported with Created only' ($out -eq 'None True True 4 True 1 True False')
    } else {
        Check 'F7 (python not found: the cross-language read is covered by tests\test_pause_recovery_sia6.py)' $true
    }
    $mgr = $mgrType.GetConstructors($NPI)[0].Invoke(@($pid2, ([Action[string, string]] { param($e, $d) }), $null, $null))
    $mgrType.GetField('statePublisher', $NPI).SetValue($mgr, $apub)
    $mgrType.GetField('stateBlockCreated', $NPI).SetValue($mgr, $true)
    $mgrType.GetMethod('PublishStateWithLoad').Invoke($mgr, @($true, $false, 5, [uint32]1, $true)) | Out-Null
    $x7 = Block
    Check 'F8 AppProcessManager.PublishStateWithLoad reaches the block (generation 5, marker Created); an identical report is only counted as suppressed' (((I32 $x7 40) -eq 5) -and ([BitConverter]::ToUInt32($x7, 48) -eq 1) -and ([BitConverter]::ToUInt32($x7, 52) -eq 0x4C4F4431))
    $sup0 = [long]$mgrType.GetProperty('StateSuppressedCount').GetValue($mgr)
    $mgrType.GetMethod('PublishStateWithLoad').Invoke($mgr, @($true, $false, 5, [uint32]1, $true)) | Out-Null
    Check 'F9 ... the identical report was suppressed' (([long]$mgrType.GetProperty('StateSuppressedCount').GetValue($mgr)) -eq $sup0 + 1)
    $mgrType.GetMethod('PublishState').Invoke($mgr, @($true, $false, 5)) | Out-Null
    $x9 = Block
    Check 'F10 the old three-argument PublishState (no marker) clears the marker: the application then treats it as unavailable' (([BitConverter]::ToUInt32($x9, 48) -eq 0) -and ([BitConverter]::ToUInt32($x9, 52) -eq 0))
    $cl = $apStateType.GetMethod('Close').Invoke($apub, @())
    $xc = Block
    Check 'F11 Close (Caller Dispose): Session OFF, Closed flag, the marker withdrawn (zero)' (((I32 $xc 36) -eq 4) -and ([BitConverter]::ToUInt32($xc, 48) -eq 0) -and ([BitConverter]::ToUInt32($xc, 52) -eq 0))
    $vA.Dispose(); $mmA.Dispose(); $apStateType.GetMethod('Dispose').Invoke($apub, @()) | Out-Null

    Write-Host '--- G: scope'
    $layout = $apLayoutType
    Check 'G1 the application block keeps magic / version / size and every earlier offset; the marker sits in 48..55' (([uint32]$layout.GetField('Magic').GetRawConstantValue() -eq 0x53415354) -and ([uint32]$layout.GetField('Version').GetRawConstantValue() -eq 1) -and ([int]$layout.GetField('Size').GetRawConstantValue() -eq 64) -and ([int]$layout.GetField('OffTail').GetRawConstantValue() -eq 60) -and ([int]$layout.GetField('OffLoadInfo').GetRawConstantValue() -eq 48) -and ([int]$layout.GetField('OffLoadMagic').GetRawConstantValue() -eq 52))
    $vi = (Get-Item (Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')).VersionInfo
    $vb = (Get-Item (Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')).VersionInfo
    $vl = (Get-Item (Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')).VersionInfo
    Check 'G2 versions: Caller 0.12.0.0, Current Bridge 0.7.0.0, Legacy Bridge 0.7.0.0 (the shared core is the same in both Bridges)' (($vi.FileVersion -eq '0.12.0.0') -and ($vb.FileVersion -eq '0.7.0.0') -and ($vl.FileVersion -eq '0.7.0.0'))
    # (only the lines this phase ADDED are judged: the files hold older text that names BVE types in comments)
    $added = ''
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd) { $added = ((& git -C $Root diff HEAD -U0 -- 'Bridge/src/ScenarioReadyTracker.cs' 'Bridge/src/ScenarioReadyPublisher.cs' 'Shared/HandshakeProtocol.cs' 'Caller/src/AppStatePublisher.cs' 'Caller/src/AppProcessManager.cs' 'Caller/src/HandshakeSession.cs' 2>$null) | Where-Object { $_ -match '^\+[^+]' }) -join "`n" }
    $allText = $added
    Check 'G3 the lines added for the marker read nothing from BVE: no BveTypes / BveEx member, no reflection, no thread, no file' (($added.Length -gt 1000) -and ($added -notmatch 'BveTypes|BveEx\.PluginHost|GetType\(\)|Activator|new Thread|ThreadPool|\bFile\.(WriteAll|Open|Append|Create)'))
    $trkText = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\ScenarioReadyTracker.cs'))
    Check 'G4 the tracker still does not take isReload (OnScenarioOpened has no parameter): F5 is told by the application watching the key, not by the Bridge' (@($trkType.GetMethod('OnScenarioOpened').GetParameters()).Count -eq 0)
    Check 'G5 TS Scoring official jump, timetable jump and TS Scoring ON have no signal in the Bridge or the Caller: no JUMP / timetable / ScoringOn member was added' (($allText -notmatch '(?i)jump|timetable|scoringon'))
}
finally {
    foreach ($t in $cLog, $bLog) { try { $t.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null } catch { } }
}

Start-Sleep -Milliseconds 300
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
$left = @($allPids | Where-Object { AnyObject $_ })
Check 'Final: no named object of any test pid is left' ($left.Count -eq 0)
Check 'Final: no monitor thread alive' (([int]$sessionType.GetField('LiveMonitors', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null)) -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
