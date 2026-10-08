# PHASE C1 - offline tests of the OBSERVATION additions (log file, scenario observer, Bridge / Caller log lines, classifier).
# No BVE, no BveEX runtime, no Python, no UDP, no hooks. The real built DLLs are loaded from memory. Every log goes to a private file
# under logs\c1-tests (NEVER to the fixed Downloads file). The Caller session uses fake PIDs and a notice test double (no MessageBox).
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

Add-Type -TypeDefinition @'
using System.Reflection;
using System.Threading;
public static class LogHammer
{
    // real .NET threads (no PowerShell runspaces), each calling the internal ObservationLog.Write of one DLL
    public static void Run(MethodInfo callerWrite, MethodInfo bridgeWrite, int threadsPerDll, int perThread)
    {
        System.Collections.Generic.List<Thread> list = new System.Collections.Generic.List<Thread>();
        foreach (MethodInfo m in new MethodInfo[] { callerWrite, bridgeWrite })
        {
            for (int k = 0; k < threadsPerDll; k++)
            {
                MethodInfo mm = m;
                Thread t = new Thread(delegate () { for (int i = 1; i <= perThread; i++) { mm.Invoke(null, new object[] { "B", "L5_WRITE", "k=" + i }); } });
                list.Add(t);
                t.Start();
            }
        }

        foreach (Thread t in list) { t.Join(); }
    }
}
'@

# The assembly resolver is compiled C# on purpose: this script also uses scriptblock delegates, and a scriptblock-based
# AssemblyResolve handler would be re-entered by PowerShell's own lazy assembly loads (stack overflow).
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
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$bridgeType = $bridgeAsm.GetType($NS + 'TsScoringBridgePrototype')
$obsType = $bridgeAsm.GetType($NS + 'ScenarioObserver')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $bridgeAsm.GetType($NS + 'ObservationLog')
$NPS = [Reflection.BindingFlags]'NonPublic,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$tickMethod = $bridgeType.GetMethod('Tick')
$publishMethod = $bridgeType.GetMethod('PublishAvailability', $NPI)
$beginObsMethod = $bridgeType.GetMethod('BeginObservation', $NPI)

$testDir = Join-Path $Root 'logs\c1-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

# ---- log helpers ----
function LogCfg($type, [string]$path, [int]$fakePid, [long]$max = 0) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]$max)
}
function LogCfgBoth([string]$path, [int]$fakePid, [long]$max = 0) { LogCfg $cLog $path $fakePid $max; LogCfg $bLog $path $fakePid $max }
function LogW($type, [string]$track, [string]$evt, [string]$detail) { $type.GetMethod('Write', $NPS).Invoke($null, @($track, $evt, $detail)) | Out-Null }
function ReadLog([string]$path) { if (Test-Path -LiteralPath $path) { return @(Get-Content -LiteralPath $path -Encoding UTF8) } else { return @() } }
function EvtLines([string[]]$lines, [string]$evt) { return ,@($lines | Where-Object { $_ -match (' ' + [regex]::Escape($evt) + '( |$)') }) }
function EvtIndex([string[]]$lines, [string]$evt, [string]$extra = '') {
    for ($i = 0; $i -lt $lines.Count; $i++) { if (($lines[$i] -match (' ' + [regex]::Escape($evt) + '( |$)')) -and ($extra -eq '' -or $lines[$i].Contains($extra))) { return $i } }
    return -1
}
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
$allLogs = New-Object System.Collections.Generic.List[string]
function NewLogPath([string]$name) { $p = Join-Path $testDir ($name + '.log'); $allLogs.Add($p); return $p }

# ---- session / bridge helpers (same technique as the Phase B suite) ----
$allPids = New-Object System.Collections.Generic.List[int]
function NewSession([int]$fakePid) {
    if (-not $allPids.Contains($fakePid)) { $allPids.Add($fakePid) }
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    return [pscustomobject]@{ Session = $sessionCtor.Invoke(@($fakePid, $del)); Recorder = $rec; Pid = $fakePid }
}
function StartSession($h) { $sessionType.GetMethod('Start').Invoke($h.Session, @()) | Out-Null }
function EndSession($h) { try { $sessionType.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { } }
function Phase($h) { return $sessionType.GetProperty('Phase', $NPI).GetValue($h.Session).ToString() }
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
function MonitorsDown() { return ([int]$sessionType.GetField('LiveMonitors', $NPS).GetValue($null)) -eq 0 }

# ---- scenario observer harness (fake readers, injected clock) ----
$script:lines = New-Object System.Collections.Generic.List[string]
$script:fake = @{ Created = 0; Probe = 'scenario-null'; Now = 1000; Throw = $false; Ready = 'N' }
function NewObserver {
    $script:lines = New-Object System.Collections.Generic.List[string]
    $script:fake = @{ Created = 0; Probe = 'scenario-null'; Now = 1000; Throw = $false; Ready = 'N' }
    $log = [Action[string, string, string]] { param($t, $e, $d) $script:lines.Add("$t|$e|$d") }
    $rd = [Func[int]] { if ($script:fake.Throw) { throw 'reader failed' }; [int]$script:fake.Created }
    $pr = [Func[string]] { if ($script:fake.Throw) { throw 'probe failed' }; $script:fake.Probe }
    $ry = [Func[string]] { [string]$script:fake.Ready }
    $nw = [Func[long]] { [long]$script:fake.Now }
    return $obsType.GetConstructors($NPI)[0].Invoke(@($log, $rd, $pr, $ry, $nw))
}
function Call($o, [string]$method, [object[]]$args2 = @()) { $obsType.GetMethod($method).Invoke($o, $args2) | Out-Null }
function OEvt([string]$evt) { return ,@($script:lines | Where-Object { $_.Split('|')[1] -eq $evt }) }
function OCount([string]$evt) { return (OEvt $evt).Count }
function OOrder([string[]]$evts) {
    $last = -1
    foreach ($e in $evts) {
        $idx = -1
        for ($i = $last + 1; $i -lt $script:lines.Count; $i++) { if ($script:lines[$i].Split('|')[1] -eq $e) { $idx = $i; break } }
        if ($idx -lt 0) { return $false }
        $last = $idx
    }
    return $true
}
function CandCounts() { return ((@('A', 'B', 'C', 'D', 'E', 'F') | ForEach-Object { OCount ('CAND_' + $_) }) -join ',') }

try {
    # =================================================================================================================
    Write-Host '--- L: observation log file (shared by both DLLs)'
    # L1: first DLL initialises, second appends
    $pL1 = NewLogPath 'L1'; LogCfgBoth $pL1 930001
    LogW $cLog 'B' 'L1_FROM_CALLER' 'k=1'
    LogW $bLog 'A' 'L1_FROM_BRIDGE' 'k=2'
    LogW $cLog 'AB' 'L1_AGAIN' 'k=3'
    $l1 = ReadLog $pL1
    Check 'L1 file starts with the diagnostic header and exactly one run header' ((@($l1 | Where-Object { $_ -like '# TS Scoring Phase C1 observation log*' }).Count -eq 1) -and ($l1[0] -like '# TS Scoring Phase C1 observation log*'))
    Check 'L1 header names the initialising DLL and the version 0.6.0.0 (Phase C3 build; the log format is the unchanged C1 contract)' (($l1 -join "`n") -match 'initializedBy=Caller ver=0\.6\.0\.0')
    Check 'L1 second DLL appended (no second truncation): 3 event lines, sources Caller / Bridge / Caller' ((@($l1 | Where-Object { $_ -match '^\d\d:\d\d' }).Count -eq 3) -and (@($l1 | Where-Object { $_ -match '^\d' })[1] -match ' S=Bridge T=A ') -and (@($l1 | Where-Object { $_ -match '^\d' })[0] -match ' S=Caller T=B '))
    Check 'L1 line format: clock, q, P, S, T, th, EVENT' (@($l1 | Where-Object { $_ -match '^\d\d:\d\d:\d\d\.\d{3} q=\d+\.\d P=930001 S=(Caller|Bridge) T=(A|B|AB) th=\d+ [A-Z0-9_]+( .*)?$' }).Count -eq 3)

    # L2: a NEW run (new PID) replaces the file: runs are never mixed
    LogCfgBoth $pL1 930002
    LogW $bLog 'AB' 'L2_NEW_RUN' 'k=9'
    LogW $cLog 'B' 'L2_SECOND' 'k=10'
    $l2 = ReadLog $pL1
    Check 'L2 new run truncated the old run (no old lines)' ((-not (($l2 -join "`n") -match 'L1_')) -and (($l2 -join "`n") -match 'L2_NEW_RUN') -and (($l2 -join "`n") -match 'L2_SECOND'))
    Check 'L2 new run header says initialised by the Bridge and has a single header' ((@($l2 | Where-Object { $_ -like '# TS Scoring Phase C1*' }).Count -eq 1) -and (($l2 -join "`n") -match 'initializedBy=Bridge'))
    Check 'L2 only the new PID appears in event lines' (@($l2 | Where-Object { $_ -match '^\d\d:' -and $_ -notmatch ' P=930002 ' }).Count -eq 0)

    # L3: failure safety - nothing may throw
    $failures = 0
    $dirMissing = Join-Path $testDir 'no\such\folder\x.log'
    LogCfgBoth $dirMissing 930003
    try { 1..20 | ForEach-Object { LogW $cLog 'B' 'L3_MISSING_DIR' 'k=1'; LogW $bLog 'A' 'L3_MISSING_DIR' 'k=1' } } catch { $failures++ }
    $pLock = NewLogPath 'L3-locked'
    LogCfgBoth $pLock 930004
    LogW $cLog 'B' 'L3_BEFORE_LOCK' ''
    $lockStream = New-Object IO.FileStream($pLock, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try { 1..15 | ForEach-Object { LogW $cLog 'B' 'L3_WHILE_LOCKED' 'k=1'; LogW $bLog 'A' 'L3_WHILE_LOCKED' 'k=1' } } catch { $failures++ }
    $lockStream.Dispose()
    LogW $cLog 'B' 'L3_AFTER_LOCK' ''
    $l3 = ReadLog $pLock
    Check 'L3 missing folder: 40 writes, no exception, no file created' (($failures -eq 0) -and (-not (Test-Path (Join-Path $testDir 'no'))))
    Check 'L3 exclusively locked file: 30 writes, no exception' ($failures -eq 0)
    Check 'L3 after the lock is released logging resumes and reports how many lines were dropped' ((($l3 -join "`n") -match 'L3_AFTER_LOCK.*droppedBefore=\d+') -and (($l3 -join "`n") -notmatch 'L3_WHILE_LOCKED'))
    $dirPath = Join-Path $testDir 'a-directory.log'; New-Item -ItemType Directory -Force $dirPath | Out-Null
    LogCfgBoth $dirPath 930005
    try { LogW $cLog 'B' 'L3_DIR' ''; LogW $bLog 'A' 'L3_DIR' '' } catch { $failures++ }
    Check 'L3 path is a directory: no exception' ($failures -eq 0)

    # L4: size cap
    $pCap = NewLogPath 'L4-cap'; LogCfgBoth $pCap 930007 3000
    1..400 | ForEach-Object { LogW $cLog 'B' 'L4_FILL' ('k=' + $_) }
    $sizeAfter = (Get-Item $pCap).Length
    1..50 | ForEach-Object { LogW $bLog 'A' 'L4_AFTER_CAP' '' }
    $l4 = ReadLog $pCap
    Check 'L4 cap: one LOG_CAP_REACHED per DLL (2 here), then the file stops growing, bounded size' (((EvtLines $l4 'LOG_CAP_REACHED').Count -eq 2) -and ((Get-Item $pCap).Length -le ($sizeAfter + 300)) -and ($sizeAfter -lt 3500))

    # L5: concurrency from both DLLs
    $pCon = NewLogPath 'L5-concurrent'; LogCfgBoth $pCon 930008
    [LogHammer]::Run($cLog.GetMethod('Write', $NPS), $bLog.GetMethod('Write', $NPS), 2, 100)
    $l5 = ReadLog $pCon
    $ev5 = @($l5 | Where-Object { $_ -match '^\d' })
    Check 'L5 four threads across both DLLs: 400 intact lines, none interleaved, one header' (($ev5.Count -eq 400) -and (@($ev5 | Where-Object { $_ -notmatch '^\d\d:\d\d:\d\d\.\d{3} q=\d+\.\d P=930008 S=(Caller|Bridge) T=B th=\d+ L5_WRITE k=\d+$' }).Count -eq 0) -and (@($l5 | Where-Object { $_ -like '# TS Scoring*' }).Count -eq 1))

    # L6: default path is the fixed Downloads file (nothing is written here)
    $expectedDefault = Join-Path (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads') 'TSScoring-Phase-C1-Observation.log'
    $defC = $cLog.GetMethod('DefaultPath', $NPS).Invoke($null, @())
    $defB = $bLog.GetMethod('DefaultPath', $NPS).Invoke($null, @())
    Check 'L6 both DLLs resolve the fixed log path Downloads\TSScoring-Phase-C1-Observation.log' (($defC -eq $expectedDefault) -and ($defB -eq $expectedDefault) -and ($defC -like '*\Downloads\TSScoring-Phase-C1-Observation.log'))

    # =================================================================================================================
    Write-Host '--- O: scenario observer (Track A candidates)'
    # O1 normal order
    $o = NewObserver
    $script:fake.Created = 0; $script:fake.Probe = $null
    Call $o 'OnAllExtensionsLoaded'
    Call $o 'OnScenarioOpened' @($false)
    Call $o 'OnPreviewScenarioCreated'
    $script:fake.Created = 1
    Call $o 'OnScenarioCreated'
    Call $o 'OnPreviewTick'; Call $o 'OnTick'; Call $o 'OnPostTick'
    Call $o 'OnScenarioClosed'
    Set-Content -LiteralPath (NewLogPath 'O1-observer-lines') -Value $script:lines -Encoding UTF8
    Check 'O1 each candidate A-F fires exactly once' ((CandCounts) -eq '1,1,1,1,1,1')
    Check 'O1 order: A (event) < B (IsScenarioCreated) < C < D < E < F' (OOrder @('CAND_A', 'CAND_B', 'CAND_C', 'CAND_D', 'CAND_E', 'CAND_F'))
    Check 'O1 life-cycle events in order: GEN_BEGIN, SCN_OPENED, SCN_PREVIEW_CREATED, SCN_CREATED, GEN_SUMMARY, SCN_CLOSED' (OOrder @('ALL_EXT_LOADED', 'GEN_BEGIN', 'SCN_OPENED', 'SCN_PREVIEW_CREATED', 'SCN_CREATED', 'GEN_SUMMARY', 'SCN_CLOSED'))
    Check 'O1 summary reports candidates ABCDEF and ScenarioGeneration=1' (((OEvt 'GEN_SUMMARY')[0] -match 'candidates=ABCDEF') -and ((OEvt 'GEN_SUMMARY')[0] -match 'ScenarioGeneration=1 '))
    Check 'O1 frame order after ScenarioCreated is recorded as PreviewTick>Tick>PostTick' ((OEvt 'FRAME_ORDER')[0] -match 'PreviewTick>Tick>PostTick')
    Check 'O1 every line is Track A or AB and none is a ScenarioReady event' ((@($script:lines | Where-Object { $_.Split('|')[0] -notin 'A', 'AB' }).Count -eq 0) -and (@($script:lines | Where-Object { $_.Split('|')[1] -match 'SCENARIOREADY|ScenarioReady' }).Count -eq 0))

    # O2 IsScenarioCreated false at the first Tick, true later: D is NOT met
    $o = NewObserver; $script:fake.Probe = $null
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'
    Call $o 'OnTick'
    $c1 = CandCounts
    $script:fake.Created = 1
    Call $o 'OnTick'; Call $o 'OnPostTick'
    Check 'O2 first Tick with IsScenarioCreated=false: only A and C so far, D reported as not met' (($c1 -eq '1,0,1,0,0,0') -and ((OCount 'CAND_D_NOT_MET') -eq 1))
    Check 'O2 later Tick with IsScenarioCreated=true: B (where=Tick) and E fire, D never fires, F at PostTick' (((CandCounts) -eq '1,1,1,0,1,1') -and ((OEvt 'CAND_B')[0] -match 'where=Tick'))

    # O3 E pending reasons
    $o = NewObserver; $script:fake.Created = 1
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'
    $script:fake.Probe = 'reason-one'; 1..3 | ForEach-Object { Call $o 'OnTick' }
    $script:fake.Probe = 'reason-two'; 1..2 | ForEach-Object { Call $o 'OnTick' }
    $before = OCount 'CAND_E'
    $script:fake.Probe = $null; Call $o 'OnTick'
    Check 'O3 E waits while the BVE info is unreadable: one PENDING line per distinct reason, then E once' (($before -eq 0) -and ((OCount 'CAND_E_PENDING') -eq 2) -and ((OCount 'CAND_E') -eq 1))

    # O4 reload / second scenario
    $o = NewObserver; $script:fake.Probe = $null
    foreach ($round in 1, 2) {
        $script:fake.Created = 0
        Call $o 'OnScenarioOpened' @(($round -eq 2))
        $script:fake.Created = 1
        Call $o 'OnScenarioCreated'; Call $o 'OnTick'; Call $o 'OnPostTick'
        Call $o 'OnScenarioClosed'
    }
    Check 'O4 second load: ScenarioGeneration 2, every candidate fired once per generation (2 total), reload flagged' (((CandCounts) -eq '2,2,2,2,2,2') -and ($obsType.GetProperty('ScenarioGeneration', $NPI).GetValue($o) -eq 2) -and ((OEvt 'SCN_OPENED')[1] -match 'isReload=yes'))
    # opened twice without Closed
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'
    Call $o 'OnScenarioOpened' @($false)
    Check 'O4b Opened twice without Closed: previous generation summarised as replaced-by-open' (((OEvt 'GEN_SUMMARY')[0] -match 'reason=replaced-by-open') -and ((OEvt 'GEN_BEGIN').Count -eq 2))

    # O5 Tick after Closed
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'; Call $o 'OnTick'; Call $o 'OnScenarioClosed'
    $script:fake.Created = 0
    $n = $script:lines.Count
    1..50 | ForEach-Object { Call $o 'OnTick'; Call $o 'OnPostTick'; Call $o 'OnPreviewTick' }
    Check 'O5 150 Tick events after ScenarioClosed: no candidate; only the IsScenarioCreated change and one TICK_OUTSIDE_GENERATION line' (((CandCounts) -eq '1,1,1,1,1,0') -and ((OCount 'TICK_OUTSIDE_GENERATION') -eq 1) -and ($script:lines.Count -eq ($n + 2)))

    # O6 Created without Opened (implicit generation)
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnScenarioCreated'
    Check 'O6 ScenarioCreated without ScenarioOpened opens an implicit generation (1) and A still fires' (((OEvt 'GEN_BEGIN')[0] -match 'source=ScenarioCreated-without-open') -and ((OCount 'CAND_A') -eq 1))

    # O7 steady state is silent
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'; Call $o 'OnPreviewTick'; Call $o 'OnTick'; Call $o 'OnPostTick'
    $n = $script:lines.Count
    1..2000 | ForEach-Object { $script:fake.Now += 16; Call $o 'OnPreviewTick'; Call $o 'OnTick'; Call $o 'OnPostTick' }
    Check 'O7 2000 steady frames produce zero log lines' ($script:lines.Count -eq $n)

    # O8 tick gap
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'
    1..100 | ForEach-Object { $script:fake.Now += 16; Call $o 'OnTick' }
    $g0 = OCount 'TICK_GAP'
    $script:fake.Now += 1500; Call $o 'OnTick'
    1..20 | ForEach-Object { $script:fake.Now += 16; Call $o 'OnTick' }
    Check 'O8 a 1500 ms Tick stall is reported once when Ticks resume; normal 16 ms frames never' (($g0 -eq 0) -and ((OCount 'TICK_GAP') -eq 1) -and ((OEvt 'TICK_GAP')[0] -match 'gapMs=15\d\d'))

    # O9 failing readers
    $o = NewObserver; $script:fake.Throw = $true
    $threw = $false
    try { Call $o 'OnScenarioOpened' @($false); Call $o 'OnPreviewScenarioCreated'; Call $o 'OnScenarioCreated'; Call $o 'OnTick'; Call $o 'OnPostTick'; Call $o 'OnScenarioClosed'; Call $o 'OnDispose' } catch { $threw = $true }
    Check 'O9 throwing IsScenarioCreated / probe readers never throw out of the observer; value logged as unreadable' ((-not $threw) -and (($script:lines -join "`n") -match 'unreadable') -and ((OCount 'CAND_A') -eq 1))
    $script:lines.Clear()
    $badLog = [Action[string, string, string]] { param($t, $e, $d) throw 'sink failed' }
    $o2 = $obsType.GetConstructors($NPI)[0].Invoke(@($badLog, [Func[int]] { 1 }, [Func[string]] { $null }, [Func[string]] { 'N' }, [Func[long]] { 1 }))
    $threw = $false
    try { Call $o2 'OnScenarioOpened' @($false); Call $o2 'OnScenarioCreated'; Call $o2 'OnTick' } catch { $threw = $true }
    Check 'O9b throwing log sink never throws out of the observer' (-not $threw)

    # O10 late attach
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnTick'; Call $o 'OnPostTick'
    Check 'O10 Bridge attached after the scenario existed: LATE_ATTACH, B/C/D/E/F can fire (flagged), A cannot' (((OCount 'LATE_ATTACH') -eq 1) -and ((CandCounts) -eq '0,1,1,1,1,1') -and ((OEvt 'CAND_C')[0] -match 'lateAttach=yes'))

    # O11 dispose
    $o = NewObserver; $script:fake.Probe = $null; $script:fake.Created = 1
    Call $o 'OnScenarioOpened' @($false); Call $o 'OnScenarioCreated'; Call $o 'OnTick'; Call $o 'OnDispose'
    Check 'O11 Dispose with an open generation writes GEN_SUMMARY and OBSERVER_DISPOSE' (((OEvt 'GEN_SUMMARY')[0] -match 'reason=dispose-with-open-generation') -and ((OCount 'OBSERVER_DISPOSE') -eq 1))

    # O12 (C1: "no formal ScenarioReady anywhere"; C3: ScenarioReady now exists, but the OBSERVER must still own none of it)
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($t in $bridgeAsm.GetTypes()) { if ($t.Name -match 'ScenarioReady') { $names.Add($t.Name) } }
    $obsMembers = @($obsType.GetMembers([Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly') | Where-Object { $_.Name -match 'ScenarioReady' })
    Check 'O12 C3: ScenarioReady-named Bridge types are exactly the candidate vocabulary, the tracker, the publisher and its interface; ScenarioObserver itself has no ScenarioReady member (it still only logs)' (((($names | Sort-Object) -join ',') -eq 'IScenarioReadyPublisher,ScenarioReadyCandidates,ScenarioReadyPublisher,ScenarioReadyTracker') -and ($obsMembers.Count -eq 0))

    # =================================================================================================================
    Write-Host '--- B: Bridge log lines (Track B) through the real Bridge code'
    $idB = 940001
    $pBr = NewLogPath 'B1-bridge'; LogCfgBoth $pBr $idB
    $b = NewBridge $idB
    $beginObsMethod.Invoke($b, @([Func[int]] { 1 }, [Func[string]] { $null })) | Out-Null
    LoadBridge $b
    $c = NewSession $idB; StartSession $c
    $ms = PumpUntil @($b) { (Phase $c) -eq 'Connected' } 800
    Pump @($b) 300
    EndSession $c
    Pump @($b) 250
    $tickLinesBefore = (ReadLog $pBr).Count
    Pump @($b) 600
    $tickLinesAfter = (ReadLog $pBr).Count
    DisposeBridge $b
    Wait 100
    $lb = ReadLog $pBr
    Check 'B1 Bridge Track B order: AVAIL_CREATE_BEGIN < AVAIL_CREATE_OK < CALLER_ENABLED_CREATED < BRIDGE_FIRST_TICK < READY_CREATE_BEGIN < READY_CREATE_OK' (($ms -ge 0) -and (InOrder $lb @('AVAIL_CREATE_BEGIN', 'AVAIL_CREATE_OK', 'CALLER_ENABLED_CREATED', 'BRIDGE_FIRST_TICK', 'READY_CREATE_BEGIN', 'READY_CREATE_OK')))
    Check 'B1 BRIDGE_FIRST_TICK is logged exactly once for hundreds of Ticks' ((EvtLines $lb 'BRIDGE_FIRST_TICK').Count -eq 1)
    Check 'B1 after the Caller stopped: Ready is disposed (reason caller-stopped-or-disabled), then Bridge Dispose disposes BridgeAvailable in order' ((InOrder $lb @('CALLER_DISPOSE_BEGIN', 'READY_DISPOSED', 'BRIDGE_DISPOSE_BEGIN', 'AVAIL_DISPOSED', 'BRIDGE_DISPOSE_END')) -and ((EvtLines $lb 'READY_DISPOSED')[0] -match 'reason=caller-stopped-or-disabled'))
    Check 'B1 idle Ticks after the handshake are silent (no growth in 600 ms of Ticks)' ($tickLinesAfter -eq $tickLinesBefore)
    Check 'B1 Bridge lines carry inst=0 / Track tags A, B or AB only and never a path' (@($lb | Where-Object { $_ -match '^\d' -and $_ -notmatch ' S=(Caller|Bridge) T=(A|B|AB) ' }).Count -eq 0)

    # B2: Bridge Dispose while Ready is present
    $idB2 = 940002
    $pB2 = NewLogPath 'B2-dispose-with-ready'; LogCfgBoth $pB2 $idB2
    $b2 = NewBridge $idB2
    $beginObsMethod.Invoke($b2, @([Func[int]] { 0 }, [Func[string]] { 'scenario-null' })) | Out-Null
    LoadBridge $b2
    $c2 = NewSession $idB2; StartSession $c2
    [void](PumpUntil @($b2) { (Phase $c2) -eq 'Connected' } 800)
    DisposeBridge $b2
    EndSession $c2
    Wait 150
    $lb2 = ReadLog $pB2
    Check 'B2 Dispose with Ready present: READY_DISPOSED reason=bridge-dispose then AVAIL_DISPOSED' ((InOrder $lb2 @('BRIDGE_DISPOSE_BEGIN', 'READY_DISPOSED', 'AVAIL_DISPOSED', 'BRIDGE_DISPOSE_END')) -and ((EvtLines $lb2 'READY_DISPOSED')[0] -match 'reason=bridge-dispose'))

    # =================================================================================================================
    Write-Host '--- C: Caller log lines (Track B) through the real session code'
    # C1 no Bridge: notice path
    $idC1 = 950001; $pC1 = NewLogPath 'C1-no-bridge'; LogCfgBoth $pC1 $idC1
    $s1 = NewSession $idC1; StartSession $s1
    Wait 760
    $noticeCount1 = $s1.Recorder.Count
    EndSession $s1
    Wait 150
    $lc1 = ReadLog $pC1
    Check 'C1 notice path is fully logged in order (Enabled, monitor, first check, 500 ms reached, judge, pre-show, show call, closed, dispose)' (InOrder $lc1 @('CALLER_ENABLED_CREATED', 'MONITOR_LOOP_BEGIN', 'AVAIL_FIRST_CHECK', 'TIMEOUT_REACHED', 'NOTICE_JUDGE_BEGIN', 'NOTICE_PRESHOW', 'NOTICE_SHOW_CALL', 'NOTICE_DIALOG_CLOSED', 'CALLER_DISPOSE_BEGIN', 'CALLER_DISPOSE_END'))
    Check 'C1 Phase B behaviour kept: exactly one notice, and the log says first check Missing, timeout 500, decision show' (($noticeCount1 -eq 1) -and ((EvtLines $lc1 'AVAIL_FIRST_CHECK')[0] -match 'result=Missing') -and ((EvtLines $lc1 'TIMEOUT_REACHED')[0] -match 'timeoutMs=500') -and ((EvtLines $lc1 'NOTICE_PRESHOW')[0] -match 'decision=show reason=bridge-still-missing bridgeAtRecheck=Missing'))
    Check 'C1 NOTICE_SHOW_CALL records the Bridge state at the moment of the request' ((EvtLines $lc1 'NOTICE_SHOW_CALL')[0] -match 'bridgeAtCall=Missing')
    Check 'C1 the 500 ms point is logged at 500..650 ms after Enabled' (((EvtLines $lc1 'TIMEOUT_REACHED')[0] -match 'sinceEnabledMs=(5\d\d|6[0-4]\d)\.\d'))

    # C2 Bridge arrives in time
    $idC2 = 950002; $pC2 = NewLogPath 'C2-bridge-380'; LogCfgBoth $pC2 $idC2
    $s2 = NewSession $idC2; StartSession $s2
    Wait 380
    $b3 = NewBridge $idC2; LoadBridge $b3
    [void](PumpUntil @($b3) { (Phase $s2) -eq 'Connected' } 600)
    EndSession $s2; Pump @($b3) 200; DisposeBridge $b3
    $lc2 = ReadLog $pC2
    Check 'C2 Bridge in time: first Present has over500=no, Ready first Present logged, no timeout, no notice lines' (((EvtLines $lc2 'AVAIL_FIRST_PRESENT')[0] -match 'over500=no') -and ((EvtLines $lc2 'READY_FIRST_PRESENT').Count -eq 1) -and ((EvtLines $lc2 'TIMEOUT_REACHED').Count -eq 0) -and ((EvtLines $lc2 'NOTICE_JUDGE_BEGIN').Count -eq 0) -and ($s2.Recorder.Count -eq 0))

    # C3 Bridge arrives after the notice
    $idC3 = 950003; $pC3 = NewLogPath 'C3-bridge-late'; LogCfgBoth $pC3 $idC3
    $s3 = NewSession $idC3; StartSession $s3
    Wait 800
    $b4 = NewBridge $idC3; LoadBridge $b4
    [void](PumpUntil @($b4) { (Phase $s3) -eq 'Connected' } 600)
    EndSession $s3; Pump @($b4) 200; DisposeBridge $b4
    $lc3 = ReadLog $pC3
    Check 'C3 Bridge after 500 ms: first Present has over500=yes and noticeShownThisAbsence=yes, and BridgeAvailable creation is logged by the Bridge' (((EvtLines $lc3 'AVAIL_FIRST_PRESENT')[0] -match 'over500=yes noticeShownThisAbsence=yes') -and ((EvtLines $lc3 'AVAIL_CREATE_OK').Count -eq 1) -and ($s3.Recorder.Count -eq 1))

    # C4 Ready lost while the Bridge stays, then back
    $idC4 = 950004; $pC4 = NewLogPath 'C4-ready-lost'; LogCfgBoth $pC4 $idC4
    $b5 = NewBridge $idC4; LoadBridge $b5
    $s4 = NewSession $idC4; StartSession $s4
    [void](PumpUntil @($b5) { (Phase $s4) -eq 'Connected' } 600)
    $rh = [Threading.EventWaitHandle]::OpenExisting("Local\TSScoringPlugin.v1.$idC4.Ready")
    $rh.Reset() | Out-Null; Pump @($b5) 200
    $rh.Set() | Out-Null; Pump @($b5) 150
    $rh.Dispose()
    EndSession $s4; Pump @($b5) 200; DisposeBridge $b5
    $lc4 = ReadLog $pC4
    Check 'C4 Ready lost with the Bridge present is logged (bridgeStillPresent=Y) and reconnect is READY_CONNECTED' (((EvtLines $lc4 'READY_LOST')[0] -match 'bridgeStillPresent=Y') -and ((EvtLines $lc4 'READY_CONNECTED').Count -ge 1) -and ($s4.Recorder.Count -eq 0))

    # C5 one Caller cycle per Start: OFF -> ON
    $idC5 = 950005; $pC5 = NewLogPath 'C5-off-on'; LogCfgBoth $pC5 $idC5
    $b6 = NewBridge $idC5; LoadBridge $b6
    foreach ($i in 1, 2) { $sx = NewSession $idC5; StartSession $sx; [void](PumpUntil @($b6) { (Phase $sx) -eq 'Connected' } 600); EndSession $sx; Pump @($b6) 120 }
    DisposeBridge $b6
    $lc5 = ReadLog $pC5
    Check 'C5 TS Scoring OFF/ON: two consecutive cycle numbers with their own Enabled / Dispose lines' (((EvtLines $lc5 'CALLER_ENABLED_CREATED').Count -eq 2) -and (([int]([regex]::Match((EvtLines $lc5 'CALLER_ENABLED_CREATED')[1], 'cycle=(\d+)').Groups[1].Value)) -eq ([int]([regex]::Match((EvtLines $lc5 'CALLER_ENABLED_CREATED')[0], 'cycle=(\d+)').Groups[1].Value) + 1)) -and ((EvtLines $lc5 'CALLER_DISPOSE_END').Count -eq 2))

    # =================================================================================================================
    Write-Host '--- K: offline classifier'
    function Classify([string]$path) { return (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Tools\Classify-Observation.ps1') -LogPath $path) -join "`n" }
    $k1 = Classify $pC1; $k2 = Classify $pC2; $k3 = Classify $pC3
    Check 'K1 real log without a Bridge -> notice shown, Bridge never created: BridgeAvailableExceeded500ms' ($k1 -match 'CLASS BridgeAvailableExceeded500ms')
    Check 'K2 real log with the Bridge in time -> NotReproduced' ($k2 -match 'CLASS NotReproduced')
    Check 'K3 real log with the Bridge after the notice -> BridgeAvailableExceeded500ms with a measured delay' ($k3 -match 'CLASS BridgeAvailableExceeded500ms: notice shown; Bridge created BridgeAvailable [5-9]\d\d')
    $h = 'P=777 S='
    function SynthLog([string]$name, [string[]]$rows) { $p = NewLogPath $name; Set-Content -LiteralPath $p -Value (@('# synthetic') + $rows) -Encoding UTF8; return $p }
    function Row([string]$clock, [double]$q, [string]$src, [string]$evt, [string]$rest, [int]$p = 777) { return ("{0} q={1} P={2} S={3} T=B th=1 {4} {5}" -f $clock, $q.ToString('F1', [Globalization.CultureInfo]::InvariantCulture), $p, $src, $evt, $rest).TrimEnd() }
    $sUnder = SynthLog 'K4-under500' @(
        (Row '10:00:00.000' 1000.0 'Caller' 'CALLER_ENABLED_CREATED' 'cycle=1 pid=777 ver=0.5.0.0'),
        (Row '10:00:00.300' 1300.0 'Bridge' 'BRIDGE_CTOR_BEGIN' 'inst=1 ver=0.5.0.0'),
        (Row '10:00:00.310' 1310.0 'Bridge' 'AVAIL_CREATE_OK' 'inst=1 createdNew=Y'),
        (Row '10:00:00.510' 1510.0 'Caller' 'TIMEOUT_REACHED' 'cycle=1 timeoutMs=500 missingMs=510.0'),
        (Row '10:00:00.511' 1511.0 'Caller' 'NOTICE_JUDGE_BEGIN' 'cycle=1 lagSinceTimeoutMs=1.0'),
        (Row '10:00:00.512' 1512.0 'Caller' 'NOTICE_SHOW_CALL' 'cycle=1 bridgeAtCall=Missing gapSinceRecheckMs=0.2'))
    Check 'K4 synthetic: Bridge created at 310 ms but notice shown -> NoticedUnder500ms' ((Classify $sUnder) -match 'CLASS NoticedUnder500ms')
    $sPresent = SynthLog 'K5-present-before-show' @(
        (Row '10:00:00.000' 1000.0 'Caller' 'CALLER_ENABLED_CREATED' 'cycle=1 pid=777 ver=0.5.0.0'),
        (Row '10:00:00.510' 1510.0 'Caller' 'TIMEOUT_REACHED' 'cycle=1 timeoutMs=500'),
        (Row '10:00:00.511' 1511.0 'Caller' 'NOTICE_JUDGE_BEGIN' 'cycle=1 lagSinceTimeoutMs=1.0'),
        (Row '10:00:00.512' 1512.0 'Caller' 'NOTICE_SHOW_CALL' 'cycle=1 bridgeAtCall=Present gapSinceRecheckMs=0.4'))
    Check 'K5 synthetic: Bridge present when the dialog was requested -> BecamePresentAfterJudgementBeforeShow' ((Classify $sPresent) -match 'CLASS BecamePresentAfterJudgementBeforeShow')
    $sSupp = SynthLog 'K6-suppressed' @(
        (Row '10:00:00.000' 1000.0 'Caller' 'CALLER_ENABLED_CREATED' 'cycle=1 pid=777 ver=0.5.0.0'),
        (Row '10:00:00.510' 1510.0 'Caller' 'TIMEOUT_REACHED' 'cycle=1 timeoutMs=500'),
        (Row '10:00:00.512' 1512.0 'Caller' 'NOTICE_SUPPRESSED' 'cycle=1 reason=bridge-present-at-recheck'))
    Check 'K6 synthetic: suppressed at the re-check -> SuppressedAtRecheck' ((Classify $sSupp) -match 'CLASS SuppressedAtRecheck')
    $sOrder = SynthLog 'K7-bridge-first' @(
        (Row '10:00:00.000' 1000.0 'Bridge' 'BRIDGE_CTOR_BEGIN' 'inst=1 ver=0.5.0.0'),
        (Row '10:00:00.010' 1010.0 'Bridge' 'AVAIL_CREATE_OK' 'inst=1'),
        (Row '10:00:00.200' 1200.0 'Caller' 'CALLER_ENABLED_CREATED' 'cycle=1 pid=777 ver=0.5.0.0'),
        (Row '10:00:00.230' 1230.0 'Caller' 'AVAIL_FIRST_PRESENT' 'cycle=1 sinceEnabledMs=30.0 over500=no'))
    Check 'K7 synthetic: Bridge constructed before the Caller was enabled -> InitOrderBridgeFirst' ((Classify $sOrder) -match 'CLASS InitOrderBridgeFirst')
    $sGen = SynthLog 'K8-generation' @(
        (Row '10:00:00.000' 1000.0 'Caller' 'CALLER_ENABLED_CREATED' 'cycle=1 pid=777 ver=0.5.0.0'),
        (Row '10:00:00.100' 1100.0 'Bridge' 'BRIDGE_CTOR_BEGIN' 'inst=1 ver=0.4.1.0' 778))
    Check 'K8 synthetic: Caller 0.5.0.0 with Bridge 0.4.1.0 and a second PID -> DllOrPidGenerationMismatch' ((Classify $sGen) -match 'CLASS DllOrPidGenerationMismatch')
    $sTrackA = SynthLog 'K9-track-a' (@(
        (Row '10:00:00.000' 1000.0 'Bridge' 'SCN_OPENED' 'inst=1 ScenarioGeneration=1 isReload=no'),
        (Row '10:00:00.100' 1100.0 'Bridge' 'SCN_CREATED' 'inst=1 ScenarioGeneration=1 isCreated=1'),
        (Row '10:00:00.101' 1101.0 'Bridge' 'CAND_A' 'inst=1 ScenarioGeneration=1 name=x'),
        (Row '10:00:00.140' 1140.0 'Bridge' 'CAND_C' 'inst=1 ScenarioGeneration=1 name=x'),
        (Row '10:00:00.900' 1900.0 'Bridge' 'GEN_SUMMARY' 'inst=1 ScenarioGeneration=1 reason=closed candidates=A-C--- ticks=3 preTicks=3 postTicks=3')) | ForEach-Object { $_.Replace(' T=B ', ' T=A ') })
    Check 'K9 synthetic Track A: candidate timeline per generation is printed' ((Classify $sTrackA) -match 'generation 1:[\s\S]*CAND_A@\+101\b[\s\S]*summary: candidates=A-C---')

    # =================================================================================================================
    Write-Host '--- P: privacy of every log produced by these tests'
    $forbidden = New-Object System.Collections.Generic.List[string]
    foreach ($v in $env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf), 'C:\Users', '\Users\', 'Documents', 'AppData', 'Scoring-Feature', 'gmail') { if ($v) { $forbidden.Add([string]$v) } }
    $hits = 0
    foreach ($lp in $allLogs) { if (Test-Path -LiteralPath $lp) { $txt = [IO.File]::ReadAllText($lp); foreach ($f in $forbidden) { $hits += ([regex]::Matches($txt, [regex]::Escape($f), 'IgnoreCase')).Count }; $hits += ([regex]::Matches($txt, '[A-Za-z]:\\')).Count; $hits += ([regex]::Matches($txt, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count } }
    Check ('P1 no user name, machine name, drive path, user folder or e-mail in any log (' + $allLogs.Count + ' files)') ($hits -eq 0)
}
finally {
    foreach ($t in $cLog, $bLog) { try { $t.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null } catch { } }
}

Start-Sleep -Milliseconds 300
Check 'Final: no monitor thread alive' (MonitorsDown)
$leftovers = 0
foreach ($fp in $allPids) {
    foreach ($kind in 'Enabled', 'Stop', 'BridgeAvailable', 'Ready', 'ScenarioReady') {
        $hnd = $null
        if ([Threading.EventWaitHandle]::TryOpenExisting("Local\TSScoringPlugin.v1.$fp.$kind", [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$hnd)) { $leftovers++; if ($hnd) { $hnd.Dispose() } }
    }
}
Check 'Final: no handshake named object of any test pid is left' ($leftovers -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
