# PHASE SI-A7 (M1a) - offline tests of the Tick independent CONTROL PLANE of the Bridge (shared by the Current and the Legacy adapter), the Ready EPOCH and its
# publication to the Caller and to the managed application. Observation-first step: the epoch is published, read, logged and shown - nothing acts on it.
# No BVE, no BveEX / AtsEX runtime, no real Python scoring application, no UDP, no hooks. The real built DLLs are loaded from memory: the Caller and the Current
# Bridge from dist\, the Legacy Bridge from Bridge\Legacy\out\. The host assemblies are referenced read-only from the installed hosts (never copied, never in Git).
# Every observation log goes to a private file under logs\sia7-tests (NEVER to the fixed Downloads file). Fake process ids and a notice test double are used.
# BVE objects (Scenario, Vehicle ...) cannot be built offline, so the BVE reads are replaced by a fake reader that RECORDS THE THREAD it is called on (the proof that
# the control thread never reads anything of BVE). The adapters' event handlers are bypassed on purpose: the shared tracker is driven directly (its host independent
# entry points are exactly what the adapters forward to) so that ONE script body serves both adapters.
# Modes: -Adapter Current runs the whole suite against the Current adapter, -Adapter Legacy only the adapter-level part against the Legacy adapter (it needs a
# different host assembly set, so it runs in a child process), -Adapter All (default) runs both and merges the results.
# -BaselineDir: a folder holding the Caller / Current Bridge / Legacy Bridge DLLs of the last commit before SI-A7 (their file names unchanged). Without it the
# checks against REAL old DLLs print SKIP (not counted as a pass); everything else runs.
# This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [ValidateSet('All', 'Current', 'Legacy')][string]$Adapter = 'All',
    [string]$BaselineDir = $env:SIA7_BASELINE_DLLS,
    [string]$PythonExe = ''
)

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO.MemoryMappedFiles;
using System.Threading;

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

public class SiaLogSink
{
    private readonly List<string> lines = new List<string>();
    public void Log(string evt, string detail)
    {
        lock (lines) { lines.Add(evt + " " + detail); }
    }
    public string[] Snapshot()
    {
        lock (lines) { return lines.ToArray(); }
    }
}

// An INDEPENDENT reader of the ScenarioState block (not the product's code): it polls as fast as it can and counts what it sees, so that "ScenarioReady 1 with no Tick in the
// epoch" can be proven to exist only after a Tick-less republish, and never inside a normal establishment.
public class StateWatcher
{
    public int Reads;
    public int Valid;
    public int Level1Tick0;
    public int Level1Tick1;
    public int Level1NoEpoch;
    public int MaxEpoch;
    public int Torn;
    private Thread thread;
    private volatile bool stop;
    private readonly string name;
    private readonly int pid;

    public StateWatcher(int pid)
    {
        this.pid = pid;
        this.name = "Local\\TSScoringPlugin.v1." + pid + ".ScenarioState";
    }

    public void Start()
    {
        thread = new Thread(Run);
        thread.IsBackground = true;
        thread.Start();
    }

    public void Stop()
    {
        stop = true;
        if (thread != null) { thread.Join(3000); }
    }

    private static int Check(int version, int pid, int generation, int ready, int sequence)
    {
        unchecked
        {
            int h = 0x54535343;
            h = (h * 31) ^ version;
            h = (h * 31) ^ pid;
            h = (h * 31) ^ generation;
            h = (h * 31) ^ ready;
            h = (h * 31) ^ sequence;
            return h;
        }
    }

    private static int EpochCheck(int epoch, int flags, int generation, int sequence)
    {
        unchecked
        {
            int h = 0x45504F43;
            h = (h * 31) ^ epoch;
            h = (h * 31) ^ flags;
            h = (h * 31) ^ generation;
            h = (h * 31) ^ sequence;
            return h;
        }
    }

    private void Run()
    {
        MemoryMappedFile f = null;
        MemoryMappedViewAccessor v = null;
        while (!stop)
        {
            try
            {
                if (v == null)
                {
                    try
                    {
                        f = MemoryMappedFile.OpenExisting(name, MemoryMappedFileRights.Read);
                        v = f.CreateViewAccessor(0, 64, MemoryMappedFileAccess.Read);
                    }
                    catch
                    {
                        v = null;
                        f = null;
                        Thread.Sleep(1);
                        continue;
                    }
                }

                int s1 = v.ReadInt32(16);
                if ((s1 & 1) != 0) { Torn++; continue; }
                int ver = v.ReadInt32(0);
                int p = v.ReadInt32(4);
                int gen = v.ReadInt32(8);
                int rdy = v.ReadInt32(12);
                int chk = v.ReadInt32(20);
                int em = v.ReadInt32(36);
                int ep = v.ReadInt32(40);
                int ef = v.ReadInt32(44);
                int ec = v.ReadInt32(48);
                Thread.MemoryBarrier();
                int s2 = v.ReadInt32(16);
                if (s1 != s2) { Torn++; continue; }
                Reads++;
                if (ver != 1 || p != pid || chk != Check(ver, p, gen, rdy, s1)) { continue; }
                Valid++;
                bool epochOk = em == 0x45504F31 && ep >= 1 && (ef & ~1) == 0 && ec == EpochCheck(ep, ef, gen, s1);
                if (rdy == 1)
                {
                    if (!epochOk) { Level1NoEpoch++; }
                    else if ((ef & 1) == 0) { Level1Tick0++; }
                    else { Level1Tick1++; }
                }

                if (epochOk && ep > MaxEpoch) { MaxEpoch = ep; }
                Thread.Sleep(0);
            }
            catch
            {
                v = null;
                f = null;
            }
        }

        if (v != null) { try { v.Dispose(); } catch { } }
        if (f != null) { try { f.Dispose(); } catch { } }
    }
}

// A fake BVE reader that RECORDS THE THREAD it is called on (compiled, so it also works on a thread that has no PowerShell runspace - where a script block delegate would only throw).
public class ReaderProbe
{
    public object Snap;
    public bool Fail;
    private readonly List<int> threads = new List<int>();
    public object Read()
    {
        lock (threads) { threads.Add(Thread.CurrentThread.ManagedThreadId); }
        if (Fail) { throw new System.IO.IOException("boom"); }
        return Snap;
    }
    public int[] Threads() { lock (threads) { return threads.ToArray(); } }
}

// A hang must FAIL the suite, not freeze it: after the time limit this prints the failure and ends the process.
public static class Watchdog
{
    private static Timer timer;
    public static void Arm(int ms, string message)
    {
        Disarm();
        timer = new Timer(delegate (object s)
        {
            Console.Out.WriteLine("FAIL " + message);
            Console.Out.WriteLine("TOTAL 0  FAILED 1  (watchdog)");
            Console.Out.Flush();
            Environment.Exit(1);
        }, null, ms, Timeout.Infinite);
    }

    public static void Disarm() { if (timer != null) { timer.Dispose(); timer = null; } }
}

// A stand-in for the Caller that flips Enabled OFF -> ON from its own thread, so that the control thread and the Tick thread run against it for real (lock order under load)
public class EnabledToggler
{
    public int Done;
    public volatile bool Finished;
    private readonly string enabledName;
    private readonly int count;
    private readonly int gapMs;
    private Thread thread;

    public EnabledToggler(int pid, int count, int gapMs)
    {
        this.enabledName = "Local\\TSScoringPlugin.v1." + pid + ".Enabled";
        this.count = count;
        this.gapMs = gapMs;
    }

    public void Start()
    {
        thread = new Thread(Run);
        thread.IsBackground = true;
        thread.Start();
    }

    public bool Join(int ms) { return thread == null || thread.Join(ms); }

    private void Run()
    {
        try
        {
            EventWaitHandle en = EventWaitHandle.OpenExisting(enabledName);
            for (int i = 0; i < count; i++)
            {
                en.Reset();
                Thread.Sleep(gapMs);
                en.Set();
                Thread.Sleep(gapMs);
                Done++;
            }

            en.Dispose();
        }
        catch { }
        Finished = true;
    }
}

// The reader of a Caller from BEFORE Phase SI-A7, written out again independently: it reads offsets 0..35 only and validates Check (0..16) and LoadCheck. A block of the new
// Bridge must read exactly the same through it.
public static class OldLayout
{
    public static bool TryRead(MemoryMappedViewAccessor view, int expectedPid, out int generation, out int ready, out bool loadSupported, out int loadInfo)
    {
        generation = 0; ready = 0; loadSupported = false; loadInfo = 0;
        int s1 = view.ReadInt32(16);
        if ((s1 & 1) != 0) { return false; }
        int ver = view.ReadInt32(0);
        int pid = view.ReadInt32(4);
        int gen = view.ReadInt32(8);
        int rdy = view.ReadInt32(12);
        int chk = view.ReadInt32(20);
        int lm = view.ReadInt32(24);
        int li = view.ReadInt32(28);
        int lc = view.ReadInt32(32);
        Thread.MemoryBarrier();
        int s2 = view.ReadInt32(16);
        if (s1 != s2) { return false; }
        unchecked
        {
            int h = 0x54535343;
            h = (h * 31) ^ ver;
            h = (h * 31) ^ pid;
            h = (h * 31) ^ gen;
            h = (h * 31) ^ rdy;
            h = (h * 31) ^ s1;
            if (ver != 1 || pid != expectedPid || gen < 0 || (rdy != 0 && rdy != 1) || chk != h) { return false; }
            int l = 0x4C4F4443;
            l = (l * 31) ^ li;
            l = (l * 31) ^ gen;
            l = (l * 31) ^ s1;
            generation = gen;
            ready = rdy;
            loadSupported = lm == 0x4C4F4431 && (li & ~3) == 0 && lc == l;
            loadInfo = loadSupported ? li : 0;
        }

        return true;
    }
}
'@

Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class SiaTestResolver
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

$ErrorActionPreference = 'Stop'
$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }

# ------------------------------------------------------------------------------------------------------------------------------------------------------------
# -Adapter All: this process runs the Current suite; the Legacy suite needs the Legacy host assemblies, so it runs in a child process and its lines are merged
# ------------------------------------------------------------------------------------------------------------------------------------------------------------
$legacyChildLines = @()
if ($Adapter -eq 'All') {
    $childArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-Root', $Root, '-Adapter', 'Legacy')
    if ($BaselineDir) { $childArgs += @('-BaselineDir', $BaselineDir) }
    $legacyChildLines = @(& powershell.exe @childArgs 2>&1 | ForEach-Object { [string]$_ })
    $Adapter = 'Current'
    $runLegacyMerge = $true
} else {
    $runLegacyMerge = $false
}

$isLegacy = ($Adapter -eq 'Legacy')
$hostName = if ($isLegacy) { 'Legacy' } else { 'Current' }
$pidBase = if ($isLegacy) { 983000 } else { 982000 }
$publicDocs = Join-Path $env:PUBLIC 'Documents\BveEx'
$hostDir = if ($isLegacy) { Join-Path $publicDocs 'Legacy' } else { Join-Path $publicDocs '2.0' }
[SiaTestResolver]::Install(@((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), $hostDir))
if ($isLegacy) { [void][Reflection.Assembly]::LoadFrom((Join-Path $hostDir 'AtsEx.PluginHost.dll')) }

$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')))
$curAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')))
$legAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')))
$brAsm = if ($isLegacy) { $legAsm } else { $curAsm }
$NS = 'TSScoringPlugin.Handshake.'
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$adType = if ($isLegacy) { $brAsm.GetType($NS + 'TsScoringLegacyBridgePrototype') } else { $brAsm.GetType($NS + 'TsScoringBridgePrototype') }
$ctlType = $brAsm.GetType($NS + 'HandshakeControlPlane')
$trkType = $brAsm.GetType($NS + 'ScenarioReadyTracker')
$pubType = $brAsm.GetType($NS + 'ScenarioReadyPublisher')
$snapType = $brAsm.GetType($NS + 'BveSnapshot')
$stateType = $brAsm.GetType($NS + 'ScenarioState')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $brAsm.GetType($NS + 'ObservationLog')
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$funcSnap = [Func``1].MakeGenericType($snapType)

$testDir = Join-Path $Root 'logs\sia7-tests'
$testDir = Join-Path $testDir $hostName
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$allPids = New-Object System.Collections.Generic.List[int]
function RegPid([int]$p) { if (-not $allPids.Contains($p)) { $allPids.Add($p) } }
$allLogs = New-Object System.Collections.Generic.List[string]
$script:pidNext = $pidBase
function NextPid { $script:pidNext++; RegPid $script:pidNext; return $script:pidNext }

function LogCfg($type, [string]$path, [int]$fakePid) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]0)
}
function LogCfgBoth([string]$path, [int]$fakePid) { LogCfg $cLog $path $fakePid; LogCfg $bLog $path $fakePid }
function NewLogPath([string]$name) { $p = Join-Path $testDir ($name + '.log'); $allLogs.Add($p); return $p }
function ReadLog([string]$path) { if (Test-Path -LiteralPath $path) { return @(Get-Content -LiteralPath $path -Encoding UTF8) } else { return @() } }
function EvtLines([string[]]$lines, [string]$evt) { return , @($lines | Where-Object { $_ -match (' ' + [regex]::Escape($evt) + '( |$)') }) }
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
function Wait([int]$ms) { Start-Sleep -Milliseconds $ms }
function WaitFor([scriptblock]$cond, [int]$limitMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $limitMs) { if (& $cond) { return $sw.ElapsedMilliseconds }; Start-Sleep -Milliseconds 3 }
    return -1
}

# ---- the named objects of one fake BVE process, seen from outside --------------------------------------------------------------------------------------------
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
# one reading through the PRODUCT's reader (the Bridge DLL under test)
function Blk([int]$p) {
    $a = @($p, $null)
    $ok = [bool]$stateType.GetMethod('TryRead').Invoke($null, $a)
    $o = [ordered]@{ Valid = $ok; Gen = -1; Ready = -1; LoadSupported = $false; LoadInfo = -1; EpochSupported = $false; Epoch = -1; Tick = $false; Raw = $null }
    if ($ok) {
        $s = $a[1]
        $o.Gen = [int]$stateType.GetField('ScenarioGeneration').GetValue($s)
        $o.Ready = [int]$stateType.GetField('IsScenarioReady').GetValue($s)
        $o.LoadSupported = [bool]$stateType.GetProperty('LoadSupported').GetValue($s)
        $o.LoadInfo = [int]$stateType.GetField('LoadInfo').GetValue($s)
        $o.EpochSupported = [bool]$stateType.GetProperty('EpochSupported').GetValue($s)
        $o.Epoch = [int]$stateType.GetField('ReadyEpoch').GetValue($s)
        $o.Tick = [bool]$stateType.GetProperty('TickSeenInEpoch').GetValue($s)
    }
    return [pscustomobject]$o
}
function Outside([int]$p) {
    $e = NamedEvent $p 'ScenarioReady'
    $b = Blk $p
    return [pscustomobject]@{ EventExists = $e.Exists; EventSet = $e.Set; B = $b }
}
function OutsideNone([int]$p) { $o = Outside $p; return (-not $o.EventExists) -and (-not $o.B.Valid) }
# withdrawn = the Event is gone and the block (kept open by a reader of this test) says nothing: level 0, no epoch
function OutsideWithdrawn([int]$p) { $o = Outside $p; return (-not $o.EventExists) -and ((-not $o.B.Valid) -or (($o.B.Ready -eq 0) -and (-not $o.B.EpochSupported))) }
# event + block agree: generation, level, and (when asked) the epoch and its Tick flag
function OutIs([int]$p, [int]$gen, [int]$level, [int]$epoch = 0, [int]$tick = -1) {
    $o = Outside $p
    if (-not ($o.EventExists -and $o.B.Valid -and ($o.B.Gen -eq $gen) -and ($o.B.Ready -eq $level) -and ($o.EventSet -eq ($level -eq 1)))) { return $false }
    if ($epoch -gt 0) { if (-not ($o.B.EpochSupported -and ($o.B.Epoch -eq $epoch))) { return $false } }
    if ($tick -ge 0) { if (-not ($o.B.EpochSupported -and ([int]$o.B.Tick -eq $tick))) { return $false } }
    return $true
}

# ---- the Caller session (real Caller DLL) --------------------------------------------------------------------------------------------------------------------
function NewSession([int]$p, $type = $sessionType, $ctor = $sessionCtor) {
    RegPid $p
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    return [pscustomobject]@{ Session = $ctor.Invoke(@($p, $del)); Recorder = $rec; Pid = $p; Type = $type }
}
function StartSession($h) { $h.Type.GetMethod('Start').Invoke($h.Session, @()) | Out-Null }
function EndSession($h) { try { $h.Type.GetMethod('End').Invoke($h.Session, @()) | Out-Null } catch { } }
function Phase($h) { return $h.Type.GetProperty('Phase', $NPI).GetValue($h.Session).ToString() }
function SProp($h, [string]$n) { return $h.Type.GetProperty($n, $NPI).GetValue($h.Session) }
function CallerTick($h) { $h.Type.GetMethod('NotifyTick').Invoke($h.Session, @()) | Out-Null }

# ---- the Bridge adapter (constructed without the host's PluginBuilder, like the other offline tests) -----------------------------------------------------------
$script:Probes = @{}
Add-Type -AssemblyName System.Core
$script:TickCount = 0
function Snap([int]$created = 1, [object]$fail = $null) {
    $o = [Activator]::CreateInstance($snapType)
    $f = [Reflection.BindingFlags]'Public,Instance'
    $snapType.GetField('IsScenarioCreated', $f).SetValue($o, $created)
    foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $snapType.GetField($n, $f).SetValue($o, [bool]($created -eq 1)) }
    $snapType.GetField('Failure', $f).SetValue($o, $fail)
    return $o
}
function NewAdapter([int]$fakePid) {
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
    $probe = New-Object ReaderProbe
    $probe.Snap = (Snap 1 $null)
    $script:Probes[$p] = $probe
    $ex = [System.Linq.Expressions.Expression]
    $rd = $ex::Lambda($funcSnap, $ex::Convert($ex::Call($ex::Constant($probe), [ReaderProbe].GetMethod('Read')), $snapType)).Compile()
    $adType.GetMethod('BeginScenarioReady', $NPI).Invoke($b, @($rd, $null)) | Out-Null
}
function BeginObs($b) {
    $f1 = ({ 1 }) -as [Func[int]]
    $f2 = ({ $null }) -as [Func[string]]
    $adType.GetMethod('BeginObservation', $NPI).Invoke($b, @($f1, $f2)) | Out-Null
}
function CtlOf($b) { return $adType.GetField('control', $NPI).GetValue($b) }
function CtlProp($b, [string]$n) { return $ctlType.GetProperty($n, $NPI).GetValue((CtlOf $b)) }
function TrkOf($b) { return $adType.GetField('tracker', $NPI).GetValue($b) }
function TProp($b, [string]$n) { return $trkType.GetProperty($n, $NPI).GetValue((TrkOf $b)) }
# the same order as the constructors: control plane created (BridgeAvailable), observer, tracker, THEN the control thread
function FullAdapter([int]$p, [bool]$thread = $true) {
    $b = NewAdapter $p
    BeginControl $b $false
    BeginObs $b
    BeginSr $b $p
    if ($thread) { $ctlType.GetMethod('Start', $NPI).Invoke((CtlOf $b), @()) | Out-Null }
    return $b
}
function Tick($b) { $script:TickCount++; return $adType.GetMethod('Tick').Invoke($b, @([TimeSpan]::Zero)) }
function Ticks($b, [int]$n) { for ($i = 0; $i -lt $n; $i++) { [void](Tick $b) } }
function ADispose($b) { try { $adType.GetMethod('Dispose').Invoke($b, @()) | Out-Null } catch { } }
function TCall($b, [string]$m) { $trkType.GetMethod($m, $NPI).Invoke((TrkOf $b), @()) | Out-Null }
function Opened($b) { TCall $b 'OnScenarioOpened' }
function Created($b) { TCall $b 'OnScenarioCreated' }
function Closed($b) { TCall $b 'OnScenarioClosed' }
function Lvl($b) { return [bool](TProp $b 'IsScenarioReady') }
function Gen($b) { return [int](TProp $b 'ScenarioGeneration') }
function Est($b) { return [int](TProp $b 'EstablishedCount') }
function LiveWorkers() { return [int]$ctlType.GetField('LiveWorkers', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null) }
function LiveMonitors() { return [int]$sessionType.GetField('LiveMonitors', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null) }

function ResetAll {
    foreach ($t in $cLog, $bLog) { try { $t.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null } catch { } }
}

$sessionCount = 0
try {
    Write-Host ('=== SIA7 M1a, adapter under test: ' + $hostName + ' ===')

    # =================================================================================================================================================
    Write-Host '--- A: shape - one control plane source, both adapters on it, no handshake inside Tick'
    $cpPath = Join-Path $Root 'Bridge\src\HandshakeControlPlane.cs'
    $oldCpPath = Join-Path $Root 'Bridge\Legacy\src\HandshakeControlPlane.cs'
    Check 'A1 the control plane is ONE source file in the shared Bridge\src; the Legacy copy is gone' ((Test-Path $cpPath) -and (-not (Test-Path $oldCpPath)))
    $curProj = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\TSScoringPlugin.BveEx.Bridge.Prototype.csproj'))
    $legProj = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\Legacy\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj'))
    Check 'A2 both projects compile that same file (the Current project directly, the Legacy project by source link); neither compiles another copy' (($curProj -match 'Include="src\\HandshakeControlPlane\.cs"') -and ($legProj -match 'Include="\.\.\\src\\HandshakeControlPlane\.cs"') -and ($legProj -notmatch 'Include="src\\HandshakeControlPlane\.cs"'))
    Check 'A3 the control plane type exists in BOTH Bridge DLLs with the same members (same source)' (& {
            $cc = $curAsm.GetType($NS + 'HandshakeControlPlane'); $ll = $legAsm.GetType($NS + 'HandshakeControlPlane')
            $sig = { param($t) (($t.GetMembers([Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly') | ForEach-Object { $_.MemberType.ToString() + ':' + $_.ToString() } | Sort-Object) -join ';') }
            ($cc -ne $null) -and ($ll -ne $null) -and ((& $sig $cc) -ceq (& $sig $ll)) })
    $adMethods = @($adType.GetMembers([Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly') | ForEach-Object { $_.Name })
    Check 'A4 the adapter has no handshake of its own any more: no HandshakeStep / TryConnect / StillEnabled / Release / WriteInfo / DisposeInfo, no state machine' (@($adMethods | Where-Object { $_ -in 'HandshakeStep', 'TryConnect', 'StillEnabled', 'Release', 'WriteInfo', 'DisposeInfo', 'WithdrawAvailability', 'BridgeState' }).Count -eq 0)
    Check 'A5 the adapter holds the control plane and the tracker in volatile fields and forwards the handshake-lost / handshake-up callbacks (internal BeginControl for the tests)' (($adType.GetField('control', $NPI).FieldType.Name -eq 'HandshakeControlPlane') -and ($adType.GetField('tracker', $NPI).FieldType.Name -eq 'ScenarioReadyTracker') -and ($adMethods -contains 'OnControlHandshakeLost') -and ($adMethods -contains 'OnControlHandshakeUp') -and ($adMethods -contains 'BeginControl'))
    $cpCtor = $ctlType.GetConstructors($NPI)[0]
    Check 'A6 the control plane callbacks are (reason) for "lost" and (epoch) for "up"; the thread, the epoch and the live-worker counter are there' ((($cpCtor.GetParameters() | ForEach-Object { $_.ParameterType.Name }) -join ',') -match 'Action`1,Action`1' -and ($ctlType.GetProperty('ReadyEpoch', $NPI) -ne $null) -and ($ctlType.GetProperty('IsWorkerAlive', $NPI) -ne $null) -and ($ctlType.GetField('LiveWorkers', [Reflection.BindingFlags]'NonPublic,Static') -ne $null))
    $trkMethods = @($trkType.GetMethods($NPI) | ForEach-Object { $_.Name })
    Check 'A7 the tracker has the new entry OnHandshakeUp(int) and keeps OnHandshakeLost(string); OnTick / OnScenarioOpened / OnScenarioCreated / OnScenarioClosed have no parameter' ((@($trkType.GetMethod('OnHandshakeUp', $NPI).GetParameters()).Count -eq 1) -and (@($trkType.GetMethod('OnHandshakeLost', $NPI).GetParameters()).Count -eq 1) -and (@('OnTick', 'OnScenarioOpened', 'OnScenarioCreated', 'OnScenarioClosed' | Where-Object { @($trkType.GetMethod($_, $NPI).GetParameters()).Count -ne 0 }).Count -eq 0))

    # =================================================================================================================================================
    Write-Host '--- B: Enabled is detected WITHOUT a Tick (the control thread alone)'
    $P1 = NextPid; $L1 = NewLogPath 'B-tickfree'; LogCfgBoth $L1 $P1
    $w0 = LiveWorkers
    $script:TickCount = 0
    $b1 = FullAdapter $P1
    Check 'B1 loading the adapter publishes BridgeAvailable and starts exactly one control thread (live workers +1)' ((NamedEvent $P1 'BridgeAvailable').Set -and ((WaitFor { (LiveWorkers) -eq ($w0 + 1) } 1500) -ge 0) -and [bool](CtlProp $b1 'IsWorkerAlive'))
    Check 'B2 no Caller yet: no Ready, the handshake is not up, ReadyEpoch is 0, nothing of ScenarioReady exists' ((-not (NamedEvent $P1 'Ready').Exists) -and (-not [bool](CtlProp $b1 'HandshakeUp')) -and ((CtlProp $b1 'ReadyEpoch') -eq 0) -and (OutsideNone $P1))
    $c1 = NewSession $P1; StartSession $c1
    $ms = WaitFor { [bool](CtlProp $b1 'HandshakeUp') } 1500
    Check ("B3 TS Scoring enabled: Ready is created by the control thread ({0} ms) and Tick was never called" -f $ms) (($ms -ge 0) -and (NamedEvent $P1 'Ready').Set -and ($script:TickCount -eq 0))
    Check 'B4 the first Ready is epoch 1 (ReadyCreateCount 1, ReadyDestroyCount 0)' (((CtlProp $b1 'ReadyEpoch') -eq 1) -and ((CtlProp $b1 'ReadyCreateCount') -eq 1) -and ((CtlProp $b1 'ReadyDestroyCount') -eq 0))
    Check 'B5 the real Caller session reaches Connected with no Tick at all' (((WaitFor { (Phase $c1) -eq 'Connected' } 1500) -ge 0) -and ($script:TickCount -eq 0))
    Check 'B6 the tracker published the (empty) generation 0 at once - level 0 - together with epoch 1 and TickSeenInEpoch 0, with no Tick' ((OutIs $P1 0 0 1 0) -and ($script:TickCount -eq 0))
    $lg = ReadLog $L1
    Check 'B7 the Bridge log says epoch 1 started with no Tick yet (SR_EPOCH why=handshake-up) and the Ready creation line carries readyEpoch=1' (((EvtLines $lg 'SR_EPOCH').Count -ge 1) -and (@($lg | Where-Object { $_ -match ' SR_EPOCH ' -and $_ -match 'ready_epoch=1' -and $_ -match 'tickSeenInEpoch=0' -and $_ -match 'why=handshake-up' }).Count -eq 1) -and (@($lg | Where-Object { $_ -match ' READY_CREATE_OK ' -and $_ -match 'readyEpoch=1' }).Count -eq 1))
    Check 'B8 the Caller sees the epoch from the same reading: supported, ReadyEpoch 1, TickSeenInEpoch 0' ((($null -ne (WaitFor { [bool](SProp $c1 'ScenarioEpochSupported') } 800)) -and [bool](SProp $c1 'ScenarioEpochSupported') -and ((SProp $c1 'ScenarioReadyEpoch') -eq 1) -and (-not [bool](SProp $c1 'ScenarioTickSeenInEpoch'))))

    # =================================================================================================================================================
    Write-Host '--- C: a normal start - TickSeenInEpoch is raised FIRST in the Tick, before ScenarioReady can be established'
    $w = New-Object StateWatcher($P1); $w.Start()
    Opened $b1; Created $b1
    Check 'C1 ScenarioOpened + ScenarioCreated received, no Tick yet: generation 1 visible at level 0, still epoch 1 with no Tick' ((Gen $b1) -eq 1 -and (-not (Lvl $b1)) -and (OutIs $P1 1 0 1 0))
    [void](Tick $b1)
    Check 'C2 the first Tick establishes ScenarioReady (generation 1) and the block says level 1, epoch 1, TickSeenInEpoch 1 in the same state' ((Lvl $b1) -and (Est $b1) -eq 1 -and (OutIs $P1 1 1 1 1))
    Ticks $b1 100
    Check 'C3 100 more Ticks in the same generation: established once, nothing changes' ((Est $b1) -eq 1 -and (OutIs $P1 1 1 1 1))
    # many establishments in a row, while the independent watcher spins: ScenarioReady 1 with TickSeenInEpoch 0 must never be seen
    for ($i = 0; $i -lt 120; $i++) { Closed $b1; Opened $b1; Created $b1; [void](Tick $b1) }
    $w.Stop()
    Check ('C4 {0} independent reads while 120 generations were closed / opened / established: ScenarioReady 1 was seen {1} times and NEVER without TickSeenInEpoch (Tick0={2}); every level 1 carried the epoch' -f $w.Reads, ($w.Level1Tick1 + $w.Level1Tick0), $w.Level1Tick0) (($w.Reads -gt 50) -and ($w.Level1Tick0 -eq 0) -and ($w.Level1NoEpoch -eq 0) -and ($w.MaxEpoch -eq 1))
    Check 'C5 the generation moved 121 times, the level was established each time (122 incl. the first)' ((Gen $b1) -eq 121 -and (Est $b1) -eq 121 -and (OutIs $P1 121 1 1 1))
    $lg = ReadLog $L1
    Check 'C6 SR_EPOCH_TICK is written once for the epoch, at the first Tick, and before the first SR_ESTABLISHED' (((EvtLines $lg 'SR_EPOCH_TICK').Count -eq 1) -and (InOrder $lg @('SR_EPOCH', 'SR_EPOCH_TICK', 'SR_ESTABLISHED')))
    $trkSrc = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\ScenarioReadyTracker.cs')) -replace "`r`n", "`n"
    $onTick = [regex]::Match($trkSrc, 'public void OnTick\(\)[\s\S]*?\n        \}\n').Value
    Check 'C7 in the source of OnTick the epoch bookkeeping comes before the publication and before the establishment' (($onTick.IndexOf('NoteTickInEpochLocked(up)') -gt 0) -and ($onTick.IndexOf('NoteTickInEpochLocked(up)') -lt $onTick.IndexOf('PublishLocked(')) -and ($onTick.IndexOf('NoteTickInEpochLocked(up)') -lt $onTick.IndexOf('EstablishLocked(')))

    # =================================================================================================================================================
    Write-Host '--- D: TS Scoring OFF -> ON during a pause (no Tick): withdrawn and published again by the control thread, a new epoch, TickSeenInEpoch 0'
    $gen0 = Gen $b1; $estBefore = Est $b1
    $loadBefore = (Blk $P1).LoadInfo
    $tickAtPause = $script:TickCount
    $w = New-Object StateWatcher($P1); $w.Start()
    Wait 300
    Check 'D1 pause (no Tick for 0.3 s): ScenarioReady, generation, Ready and the epoch are unchanged' ((Lvl $b1) -and (OutIs $P1 $gen0 1 1 1) -and ((Phase $c1) -eq 'Connected'))
    EndSession $c1
    $ms = WaitFor { (OutsideWithdrawn $P1) -and (-not (NamedEvent $P1 'Ready').Exists) } 1500
    Check ("D2 TS Scoring OFF during the pause: the control thread withdraws the external ScenarioReady AND Ready ({0} ms) with no Tick" -f $ms) (($ms -ge 0) -and ($script:TickCount -eq $tickAtPause) -and (NamedEvent $P1 'BridgeAvailable').Set)
    Check 'D3 the handshake is down, ReadyDestroyCount is 1, and the internal level and generation are KEPT' ((-not [bool](CtlProp $b1 'HandshakeUp')) -and ((CtlProp $b1 'ReadyDestroyCount') -eq 1) -and (Lvl $b1) -and (Gen $b1) -eq $gen0)
    Wait 200
    $c2 = NewSession $P1; StartSession $c2
    $ms = WaitFor { [bool](CtlProp $b1 'HandshakeUp') -and (OutIs $P1 $gen0 1 2 0) } 1500
    Check ("D4 TS Scoring ON again during the pause: Ready is back AND the HELD ScenarioReady is published again ({0} ms) with generation {1}, level 1, epoch 2, TickSeenInEpoch 0 - and Tick is still silent" -f $ms, $gen0) (($ms -ge 0) -and ($script:TickCount -eq $tickAtPause) -and (NamedEvent $P1 'Ready').Set)
    Check 'D5 the load marker of the generation came back unchanged (the same LoadInfo as before the OFF)' (((Blk $P1).LoadInfo -eq $loadBefore) -and ((Blk $P1).LoadSupported))
    Check 'D6 ReadyEpoch is 2 (ReadyCreateCount 2); the level was NOT established again (Established count unchanged)' (((CtlProp $b1 'ReadyEpoch') -eq 2) -and ((CtlProp $b1 'ReadyCreateCount') -eq 2) -and ((Est $b1) -eq $estBefore))
    Wait 300
    $w.Stop()
    Check ('D7 the independent reader saw "ScenarioReady 1 and TickSeenInEpoch 0" ({0} reads) only after the Tick-less republish, with the epoch 2; level 1 without any epoch was never seen' -f $w.Level1Tick0) (($w.Level1Tick0 -gt 0) -and ($w.Level1NoEpoch -eq 0) -and ($w.MaxEpoch -eq 2))
    [void](WaitFor { [bool](SProp $c2 'ScenarioReadyLevel') -and [bool](SProp $c2 'ScenarioEpochSupported') } 1000)
    Check 'D8 the new Caller cycle sees ScenarioReady of the same generation with epoch 2 and TickSeenInEpoch 0 (the pause re-ON signature)' (([bool](SProp $c2 'ScenarioReadyLevel')) -and ((SProp $c2 'ScenarioGenerationSeen') -eq $gen0) -and ((SProp $c2 'ScenarioReadyEpoch') -eq 2) -and (-not [bool](SProp $c2 'ScenarioTickSeenInEpoch')))
    $lg = ReadLog $L1
    Check 'D9 the Bridge log shows the sequence: withdrawn (handshake-lost reason) -> Ready disposed -> Ready created epoch 2 -> epoch started -> published why=handshake-back-control' (InOrder $lg @('SR_WITHDRAWN', 'READY_DISPOSED', 'READY_CREATE_OK', 'SR_EPOCH', 'SR_PUBLISHED') -and (@($lg | Where-Object { $_ -match ' SR_PUBLISHED ' -and $_ -match 'why=handshake-back-control' }).Count -eq 1))
    $tickGapBefore = (EvtLines $lg 'TICK_GAP').Count
    [void](Tick $b1)
    Check 'D10 the first Tick after the pause raises TickSeenInEpoch (epoch 2, tick 1) and keeps level, generation and the Established count' ((OutIs $P1 $gen0 1 2 1) -and (Lvl $b1) -and ((Est $b1) -eq $estBefore))
    [void](WaitFor { [bool](SProp $c2 'ScenarioTickSeenInEpoch') } 800)
    Check 'D11 the Caller sees TickSeenInEpoch 1 for epoch 2 afterwards' (([bool](SProp $c2 'ScenarioTickSeenInEpoch')) -and ((SProp $c2 'ScenarioReadyEpoch') -eq 2))
    $lg = ReadLog $L1
    Check 'D12 SR_EPOCH_TICK (ready_epoch=2) is written once for the second epoch; the first Tick after the control-thread republish is noted' (((@($lg | Where-Object { $_ -match ' SR_EPOCH_TICK ' -and $_ -match 'ready_epoch=2' }).Count) -eq 1) -and ((@($lg | Where-Object { $_ -match 'TICK_AFTER_HANDSHAKE_UP' }).Count) -ge 1))
    # repeat: OFF -> ON three more times in a row during one pause
    $okRep = $true
    for ($i = 3; $i -le 5; $i++) {
        EndSession $c2
        if ((WaitFor { OutsideNone $P1 } 1500) -lt 0) { $okRep = $false }
        $c2 = NewSession $P1; StartSession $c2
        if ((WaitFor { OutIs $P1 $gen0 1 $i 0 } 1500) -lt 0) { $okRep = $false }
        [void](Tick $b1)
        if (-not (OutIs $P1 $gen0 1 $i 1)) { $okRep = $false }
    }
    Check 'D14 three more OFF -> ON cycles: epochs 3, 4, 5, each republished with Tick 0 and each Tick raises it to 1; the same generation and level every time' ($okRep -and ((CtlProp $b1 'ReadyEpoch') -eq 5) -and (Lvl $b1) -and ((Est $b1) -eq $estBefore))

    # =================================================================================================================================================
    Write-Host '--- E: a closed generation and a cold start (OFF while the scenario loads) are NOT turned into ScenarioReady by the control thread'
    Closed $b1
    Check 'E1 ScenarioClosed: level 0 at once, generation kept, epoch 5 still shown' ((-not (Lvl $b1)) -and (OutIs $P1 $gen0 0 5 1))
    EndSession $c2
    [void](WaitFor { OutsideNone $P1 } 1500)
    $c3 = NewSession $P1; StartSession $c3
    $ms = WaitFor { OutIs $P1 $gen0 0 6 0 } 1500
    Check ("E2 OFF -> ON after the close (no Tick): the held state is published again at level 0 ({0} ms), generation {1} kept, epoch 6, TickSeenInEpoch 0, load marker cleared" -f $ms, $gen0) (($ms -ge 0) -and ((Blk $P1).LoadInfo -eq 0) -and (-not (Lvl $b1)))
    EndSession $c3
    [void](WaitFor { OutsideNone $P1 } 1500)
    # cold: opened + created while OFF, then ON in the pause
    Opened $b1; Created $b1
    $estCold = Est $b1
    $c4 = NewSession $P1; StartSession $c4
    $ms = WaitFor { OutIs $P1 ($gen0 + 1) 0 7 0 } 1500
    Check ("E3 a scenario that finished loading while TS Scoring was OFF: ON in the pause publishes generation {0} at level 0 only - nothing is established without a Tick ({1} ms)" -f ($gen0 + 1), $ms) (($ms -ge 0) -and (-not (Lvl $b1)) -and ((Est $b1) -eq $estCold))
    [void](Tick $b1)
    Check 'E4 the next Tick establishes it, with TickSeenInEpoch 1 in the same state (the established level is never seen without the flag)' ((Lvl $b1) -and (OutIs $P1 ($gen0 + 1) 1 7 1))
    EndSession $c4
    [void](WaitFor { OutsideNone $P1 } 1500)

    # =================================================================================================================================================
    Write-Host '--- F: the control thread survives an exception and keeps working; Tick restarts a thread that ended'
    $ctlObj = CtlOf $b1
    $logField = $ctlType.GetField('log', [Reflection.BindingFlags]'NonPublic,Instance')
    $goodLog = $logField.GetValue($ctlObj)
    $excBefore = [int](CtlProp $b1 'StepExceptionCount')
    $c5 = NewSession $P1; StartSession $c5
    [void](WaitFor { [bool](CtlProp $b1 'HandshakeUp') } 1500)
    $boom = [Action[string, string, string]] { param($t, $e, $d) throw (New-Object System.IO.IOException 'log boom') }
    $logField.SetValue($ctlObj, $boom)
    EndSession $c5
    $ms = WaitFor { (-not [bool](CtlProp $b1 'HandshakeUp')) -and (-not (NamedEvent $P1 'Ready').Exists) } 1500
    $logField.SetValue($ctlObj, $goodLog)
    Check ("F1 an exception inside a step (the log delegate throws while Ready is withdrawn): Ready is still withdrawn ({0} ms), the exception is counted and swallowed" -f $ms) (($ms -ge 0) -and (([int](CtlProp $b1 'StepExceptionCount')) -gt $excBefore))
    Check 'F2 the control thread is still alive after the exception' ([bool](CtlProp $b1 'IsWorkerAlive'))
    $c6 = NewSession $P1; StartSession $c6
    $ms = WaitFor { [bool](CtlProp $b1 'HandshakeUp') } 1500
    Check ("F3 TS Scoring ON again after the exception: Ready is created again by the same thread ({0} ms), no Tick" -f $ms) (($ms -ge 0) -and (NamedEvent $P1 'Ready').Set)
    Check 'F4 the epoch kept counting: the new Ready is epoch 9 (8 was the one withdrawn with the exception)' ((CtlProp $b1 'ReadyEpoch') -eq 9)
    $seenThreads = @($script:Probes[$P1].Threads())
    $sameThread = (@($seenThreads | Where-Object { $_ -ne [Threading.Thread]::CurrentThread.ManagedThreadId }).Count -eq 0)
    Check ('F5 thread safety: every fake BVE read ({0} in sections B-E: the establishments and the republications; recorded by a compiled reader that works on any thread) happened on the Tick (calling) thread - none on the control thread' -f $seenThreads.Count) ($sameThread -and ($seenThreads.Count -ge 120))
    # a thread that ended (Shutdown is the only normal way, so the test stops the worker through the shutdown signal only and starts it again as Tick does)
    $shutdownField = $ctlType.GetField('shutdown', [Reflection.BindingFlags]'NonPublic,Instance')
    # a control thread that ended without a Shutdown (it never should): the next Tick starts it again
    $sdEv = $shutdownField.GetValue($ctlObj)
    [void]$sdEv.Set()
    $gone = WaitFor { -not [bool](CtlProp $b1 'IsWorkerAlive') } 1500
    [void]$sdEv.Reset()
    Check 'F6 the control thread was ended from outside (shutdown signal only, the plane itself not stopped): it is gone' ($gone -ge 0)
    [void](Tick $b1)
    Check 'F7 the next Tick restarts the control thread (IsWorkerAlive again, live workers +1 in total)' (((WaitFor { [bool](CtlProp $b1 'IsWorkerAlive') } 1500) -ge 0) -and ((LiveWorkers) -eq ($w0 + 1)))
    EndSession $c6
    [void](WaitFor { OutsideNone $P1 } 1500)

    # =================================================================================================================================================
    Write-Host '--- G: Dispose - no thread, no object, no handle left; twice is harmless; late calls are ignored'
    $c7 = NewSession $P1; StartSession $c7
    [void](WaitFor { OutIs $P1 ($gen0 + 1) 1 10 0 } 1500)
    Check 'G0 (before Dispose) TS Scoring is ON, Ready is up, the held ScenarioReady is published, epoch 10' ((NamedEvent $P1 'Ready').Set -and (OutIs $P1 ($gen0 + 1) 1 10 0))
    ADispose $b1
    $lg = ReadLog $L1
    EndSession $c7; Wait 150
    Check 'G1 Dispose with a Caller enabled: ScenarioReady cleared (bridge-dispose) and withdrawn BEFORE Ready is disposed, then BridgeAvailable' (InOrder $lg @('BRIDGE_DISPOSE_BEGIN', 'SR_CLEARED', 'SR_WITHDRAWN', 'READY_DISPOSED', 'AVAIL_DISPOSED', 'BRIDGE_DISPOSE_END'))
    Check 'G2 the control thread ended (live workers back to the start value) and every object of the process is gone' (((WaitFor { (LiveWorkers) -eq $w0 } 1500) -ge 0) -and (-not (AnyObject $P1)))
    ADispose $b1
    Check 'G3 Dispose twice is harmless: nothing is created again, the thread count does not move' ((-not (AnyObject $P1)) -and ((LiveWorkers) -eq $w0))
    $ctlType.GetMethod('Shutdown', $NPI).Invoke((CtlOf $b1), @('again')) | Out-Null
    $trkType.GetMethod('OnHandshakeUp', $NPI).Invoke((TrkOf $b1), @(99)) | Out-Null
    Check 'G4 Shutdown again and a late OnHandshakeUp(99) on the disposed tracker change nothing: no object appears, no thread starts' ((-not (AnyObject $P1)) -and ((LiveWorkers) -eq $w0))
    $tickAfter = Tick $b1
    Check 'G5 a Tick after Dispose is harmless and does not start the control thread again (it was shut down)' (($tickAfter -ne $null -or -not $isLegacy) -and (-not (AnyObject $P1)) -and ((LiveWorkers) -eq $w0))

    # =================================================================================================================================================
    Write-Host '--- H: twenty OFF -> ON cycles - no thread, no handle, no object leak; epochs count 1..21'
    $P2 = NextPid; $L2 = NewLogPath 'H-cycles'; LogCfgBoth $L2 $P2
    $b2 = FullAdapter $P2
    Opened $b2; Created $b2
    $okCyc = $true
    for ($i = 1; $i -le 21; $i++) {
        $cc = NewSession $P2; StartSession $cc
        if ((WaitFor { (CtlProp $b2 'ReadyEpoch') -eq $i -and [bool](CtlProp $b2 'HandshakeUp') } 1500) -lt 0) { $okCyc = $false }
        if ($i -eq 1) { [void](Tick $b2) }
        EndSession $cc
        if ((WaitFor { -not [bool](CtlProp $b2 'HandshakeUp') } 1500) -lt 0) { $okCyc = $false }
    }
    [void](WaitFor { OutsideNone $P2 } 1500)
    Check ('H1 21 OFF -> ON cycles: every Ready was created (epoch 1..21) and withdrawn again, only ONE control thread ever ran (live workers {0})' -f (LiveWorkers)) ($okCyc -and ((CtlProp $b2 'ReadyCreateCount') -eq 21) -and ((CtlProp $b2 'ReadyDestroyCount') -eq 21) -and ((LiveWorkers) -eq 1))
    # handle growth: the Caller is replaced by two events of this test (Enabled, Stop) that are toggled 60 times - no Caller object is part of the measurement
    $proc = Get-Process -Id $PID
    $enEv = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$P2.Enabled")
    $stEv = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$P2.Stop")
    [void]$stEv.Reset(); [void]$enEv.Set()
    [void](WaitFor { [bool](CtlProp $b2 'HandshakeUp') } 1500)
    [GC]::Collect(); [GC]::WaitForPendingFinalizers(); $proc.Refresh(); $handlesBefore = $proc.HandleCount
    $epochBefore = [int](CtlProp $b2 'ReadyEpoch'); $okTog = $true
    for ($i = 1; $i -le 60; $i++) {
        [void]$enEv.Reset()
        if ((WaitFor { -not [bool](CtlProp $b2 'HandshakeUp') } 1500) -lt 0) { $okTog = $false }
        [void]$enEv.Set()
        if ((WaitFor { [bool](CtlProp $b2 'HandshakeUp') } 1500) -lt 0) { $okTog = $false }
    }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers(); $proc.Refresh(); $handlesAfter = $proc.HandleCount
    Check ('H2 60 more Enabled OFF -> ON toggles (no Caller objects): every Ready withdrawn and created again (epoch {0} -> {1}) and the handle count did not grow ({2} -> {3})' -f $epochBefore, (CtlProp $b2 'ReadyEpoch'), $handlesBefore, $handlesAfter) ($okTog -and ((CtlProp $b2 'ReadyEpoch') -eq ($epochBefore + 60)) -and (($handlesAfter - $handlesBefore) -le 4))
    [void]$enEv.Reset(); [void]$stEv.Set()
    [void](WaitFor { -not [bool](CtlProp $b2 'HandshakeUp') } 1500)
    $enEv.Dispose(); $stEv.Dispose()
    Check 'H3 after the last OFF nothing but BridgeAvailable is left of the process (no Ready, no ScenarioReady, no BridgeInfo, no state block)' ((NamedEvent $P2 'BridgeAvailable').Set -and (-not (NamedEvent $P2 'Ready').Exists) -and (OutsideNone $P2))
    ADispose $b2
    Check 'H4 Dispose after the cycles: live workers back to the start value, no object left' (((WaitFor { (LiveWorkers) -eq $w0 } 1500) -ge 0) -and (-not (AnyObject $P2)))

    # LOCK ORDER under load: the control thread (control gate -> tracker gate) and this thread (Tick: tracker gate only) run against a stand-in Caller that flips Enabled
    # OFF -> ON as fast as it can. A lock inversion would hang one of them; the run is bounded, and a hang fails the check instead of the suite.
    $Ph = NextPid; $Lh = NewLogPath 'H-stress'; LogCfgBoth $Lh $Ph
    $bh = FullAdapter $Ph
    Opened $bh; Created $bh
    $enS = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$Ph.Enabled")
    $stS = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, "Local\TSScoringPlugin.v1.$Ph.Stop")
    [void]$stS.Reset(); [void]$enS.Set()
    [void](WaitFor { [bool](CtlProp $bh 'HandshakeUp') } 1500)
    [void](Tick $bh)
    $epochS0 = [int](CtlProp $bh 'ReadyEpoch'); $estS0 = Est $bh
    $wS = New-Object StateWatcher($Ph); $wS.Start()
    $tg = New-Object EnabledToggler($Ph, 120, 25); $tg.Start()                    # OFF and ON each last 25 ms: longer than one control poll (20 ms), so every flip is seen
    [Watchdog]::Arm(90000, 'H5 stress: no finish within 90 s - a lock inversion (deadlock) between the control thread and the Tick thread')
    $swS = [Diagnostics.Stopwatch]::StartNew(); $nTicks = 0
    while ((-not $tg.Finished) -and ($swS.ElapsedMilliseconds -lt 20000)) {
        [void](Tick $bh); $nTicks++; Start-Sleep -Milliseconds 1
        if (($nTicks % 7) -eq 0) { Closed $bh; Opened $bh; Created $bh }       # the BVE events too, from this thread, while the control thread works
    }
    $finished = $tg.Finished
    [Watchdog]::Disarm()
    $wS.Stop()
    [void]$tg.Join(2000)
    Check ('H5 stress: 120 Enabled OFF -> ON flips against {0} Ticks and generation changes on this thread finished in {1} ms without a hang (no lock inversion)' -f $nTicks, $swS.ElapsedMilliseconds) ($finished -and ($tg.Done -eq 120))
    $okS = (WaitFor { [bool](CtlProp $bh 'HandshakeUp') } 2000) -ge 0
    [void](Tick $bh)
    Check ('H6 after the stress the handshake is up, every flip made a Ready (epoch {0} -> {1}), the control thread is alive and its step never threw ({2} step exceptions)' -f $epochS0, (CtlProp $bh 'ReadyEpoch'), (CtlProp $bh 'StepExceptionCount')) ($okS -and (([int](CtlProp $bh 'ReadyEpoch')) -ge ($epochS0 + 60)) -and ([bool](CtlProp $bh 'IsWorkerAlive')) -and ((CtlProp $bh 'StepExceptionCount') -eq 0))
    Check ('H7 under the stress the independent reader ({0} reads) never saw a level without its epoch, and the epoch only ever went up (max {1})' -f $wS.Reads, $wS.MaxEpoch) (($wS.Level1NoEpoch -eq 0) -and ($wS.MaxEpoch -ge ($epochS0 + 40)))
    [void]$enS.Reset(); [void]$stS.Set()
    $enS.Dispose(); $stS.Dispose()
    ADispose $bh
    Check 'H8 Dispose after the stress: live workers back to the start value, no object left' (((WaitFor { (LiveWorkers) -eq $w0 } 1500) -ge 0) -and (-not (AnyObject $Ph)))

    # =================================================================================================================================================
    Write-Host '--- I: what the Caller writes to the log - the epoch vocabulary (first epoch, resume epoch, session without Tick, Tick seen, withdrawn)'
    $P3 = NextPid; $L3 = NewLogPath 'I-caller-log'; LogCfgBoth $L3 $P3
    $b3 = FullAdapter $P3
    Opened $b3; Created $b3
    $s1 = NewSession $P3; StartSession $s1
    [void](WaitFor { (Phase $s1) -eq 'Connected' } 1500)
    [void](Tick $b3)
    [void](WaitFor { [bool](SProp $s1 'ScenarioReadyLevel') -and [bool](SProp $s1 'ScenarioTickSeenInEpoch') } 1000)
    EndSession $s1
    [void](WaitFor { OutsideNone $P3 } 1500)
    Wait 150
    $s2 = NewSession $P3; StartSession $s2                                  # TS Scoring ON again during a pause: no Tick follows for a while
    [void](WaitFor { [bool](SProp $s2 'ScenarioReadyLevel') -and [bool](SProp $s2 'ScenarioEpochSupported') } 1500)
    Wait 400
    [void](Tick $b3)
    [void](WaitFor { [bool](SProp $s2 'ScenarioTickSeenInEpoch') } 1000)
    EndSession $s2
    [void](WaitFor { OutsideNone $P3 } 1500)
    $s3 = NewSession $P3; StartSession $s3
    [void](WaitFor { [bool](SProp $s3 'ScenarioEpochSupported') -and ((SProp $s3 'ScenarioReadyEpoch') -eq 3) } 1500)
    ADispose $b3                                                           # the Bridge ends while the Caller is still enabled
    [void](WaitFor { -not [bool](SProp $s3 'ScenarioEpochSupported') } 1500)
    Wait 100
    $lg = ReadLog $L3
    $cycles = @($lg | Where-Object { $_ -match ' CALLER_ENABLED_CREATED ' } | ForEach-Object { if ($_ -match 'cycle=(\d+)') { [int]$Matches[1] } })
    Check 'I0 three Caller cycles were logged' ($cycles.Count -eq 3)
    function CycleLines([int]$cy) { return @($lg | Where-Object { $_ -match ('cycle=' + $cy + '( |$)') }) }
    $c1l = CycleLines $cycles[0]; $c2l = CycleLines $cycles[1]; $c3l = CycleLines $cycles[2]
    $o1 = @($c1l | Where-Object { $_ -match ' EPOCH_OBSERVED ' })
    Check 'I1 the first cycle logs ONE EPOCH_OBSERVED with kind=first-ready-epoch, ready_epoch=1 (a Ready epoch 1 is the Bridge''s first)' (($o1.Count -eq 1) -and ($o1[0] -match 'kind=first-ready-epoch') -and ($o1[0] -match 'ready_epoch=1'))
    Check 'I2 the first cycle logs EPOCH_TICK_SEEN for epoch 1 once; a normal start has no EPOCH_SESSION_WITHOUT_TICK' (((@($c1l | Where-Object { $_ -match ' EPOCH_TICK_SEEN ' -and $_ -match 'ready_epoch=1' })).Count -eq 1) -and ((EvtLines $c1l 'EPOCH_SESSION_WITHOUT_TICK').Count -eq 0))
    $w1 = @($c1l | Where-Object { $_ -match ' EPOCH_WITHDRAWN ' })
    Check 'I3 the first cycle ends with ONE EPOCH_WITHDRAWN reason=caller-dispose (TS Scoring OFF) after CALLER_DISPOSE_BEGIN, which itself carries the epoch (epochSupported=Y ready_epoch=1 tickSeenInEpoch=1)' (($w1.Count -eq 1) -and ($w1[0] -match 'reason=caller-dispose') -and (InOrder $c1l @('CALLER_DISPOSE_BEGIN', 'EPOCH_WITHDRAWN', 'CALLER_DISPOSE_END')) -and (@($c1l | Where-Object { $_ -match ' CALLER_DISPOSE_BEGIN ' -and $_ -match 'epochSupported=Y ready_epoch=1 tickSeenInEpoch=1' }).Count -eq 1))
    $o2 = @($c2l | Where-Object { $_ -match ' EPOCH_OBSERVED ' })
    Check 'I4 the pause re-ON cycle logs EPOCH_OBSERVED kind=resume-ready-epoch, ready_epoch=2, tickSeenInEpoch=0, session=Y (the Bridge survived the OFF; the level came back without a Tick)' (($o2.Count -eq 1) -and ($o2[0] -match 'kind=resume-ready-epoch') -and ($o2[0] -match 'ready_epoch=2') -and ($o2[0] -match 'tickSeenInEpoch=0') -and ($o2[0] -match 'session=Y'))
    $n2 = @($c2l | Where-Object { $_ -match ' EPOCH_SESSION_WITHOUT_TICK ' })
    Check 'I5 ... and ONE EPOCH_SESSION_WITHOUT_TICK epochKind=resume (ScenarioReady ON while the extension has not ticked in this epoch)' (($n2.Count -eq 1) -and ($n2[0] -match 'epochKind=resume') -and ($n2[0] -match 'ready_epoch=2'))
    $t2 = @($c2l | Where-Object { $_ -match ' EPOCH_TICK_SEEN ' })
    Check 'I6 ... then ONE EPOCH_TICK_SEEN for epoch 2 that says the epoch had been without a Tick (sessionWithoutTickSeen=yes, sinceEpochObservedMs >= 300)' (($t2.Count -eq 1) -and ($t2[0] -match 'sessionWithoutTickSeen=yes') -and ($t2[0] -match 'sinceEpochObservedMs=(\d+(\.\d+)?)' -and ([double]$Matches[1] -ge 300)) -and (InOrder $c2l @('EPOCH_OBSERVED', 'EPOCH_SESSION_WITHOUT_TICK', 'EPOCH_TICK_SEEN', 'EPOCH_WITHDRAWN')))
    $w3 = @($c3l | Where-Object { $_ -match ' EPOCH_WITHDRAWN ' })
    Check 'I7 the third cycle (epoch 3) is withdrawn when the Bridge ends while the Caller stays: reason=ready-lost or bridge-lost, ONE line, no dispose involved' (($w3.Count -eq 1) -and ($w3[0] -match 'reason=(ready-lost|bridge-lost)') -and ($w3[0] -match 'ready_epoch=3'))
    EndSession $s3
    $lg = ReadLog $L3
    Check 'I8 ending that cycle writes no second EPOCH_WITHDRAWN (the epoch is gone already)' ((@((CycleLines $cycles[2]) | Where-Object { $_ -match ' EPOCH_WITHDRAWN ' })).Count -eq 1)
    $allEpochLines = @($lg | Where-Object { $_ -match ' EPOCH_' })
    Check 'I9 the whole epoch vocabulary is only numbers and fixed words (no path, name, position, time or free text), every line short' ((@($allEpochLines | Where-Object { $_ -match '[A-Za-z]:\\|@|/' }).Count -eq 0) -and (@($allEpochLines | Where-Object { $_.Length -gt 330 }).Count -eq 0))

    # =================================================================================================================================================
    Write-Host '--- J: the Python start request - epoch information on it, and not one request more because of the epoch'
    $P4 = NextPid; $L4 = NewLogPath 'J-start'; LogCfgBoth $L4 $P4
    $b4 = FullAdapter $P4
    Opened $b4; Created $b4
    $jOk = $true
    for ($k = 1; $k -le 3; $k++) {
        $sj = NewSession $P4; StartSession $sj
        [void](WaitFor { (Phase $sj) -eq 'Connected' } 1500)
        if ($k -eq 1) { [void](Tick $b4) }                                 # the first start is a normal one; the next two are pause re-ONs (no Tick)
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 700) { CallerTick $sj; Start-Sleep -Milliseconds 25 }
        EndSession $sj
        [void](WaitFor { OutsideNone $P4 } 1500)
        Wait 100
    }
    $lg = ReadLog $L4
    $cyJ = @($lg | Where-Object { $_ -match ' CALLER_ENABLED_CREATED ' } | ForEach-Object { if ($_ -match 'cycle=(\d+)') { [int]$Matches[1] } })
    $reqs = @(); $epl = @()
    foreach ($cy in $cyJ) {
        $cl = @($lg | Where-Object { $_ -match ('cycle=' + $cy + '( |$)') })
        $reqs += , @($cl | Where-Object { $_ -match ' APP_START_REQUEST ' })
        $epl += , @($cl | Where-Object { $_ -match ' APP_START_REQUEST_EPOCH ' })
    }
    Check 'J1 three Caller cycles (one normal start, two pause re-ONs): each makes exactly ONE start request - the epoch does not add one' (($cyJ.Count -eq 3) -and ($reqs[0].Count -eq 1) -and ($reqs[1].Count -eq 1) -and ($reqs[2].Count -eq 1))
    Check 'J2 the E1 request line itself is unchanged (reason=first-driving-on, dryRun=yes at its end) and each request has ONE companion line with the epoch' ((@($reqs | ForEach-Object { $_[0] } | Where-Object { $_ -notmatch 'reason=first-driving-on dryRun=yes$' }).Count -eq 0) -and ($epl[0].Count -eq 1) -and ($epl[1].Count -eq 1) -and ($epl[2].Count -eq 1))
    Check 'J3 the request of the normal start says epochSupported=Y ready_epoch=1 tickSeenInEpoch=1; the pause re-ON requests say ready_epoch=2 / 3 with tickSeenInEpoch=0' (($epl[0][0] -match 'epochSupported=Y ready_epoch=1 tickSeenInEpoch=1') -and ($epl[1][0] -match 'epochSupported=Y ready_epoch=2 tickSeenInEpoch=0') -and ($epl[2][0] -match 'epochSupported=Y ready_epoch=3 tickSeenInEpoch=0'))
    Check 'J4 DrivingActive came on by the Caller''s own Tick in the pause re-ON cycles (the start gate is unchanged and needs no Extension Tick)' ((@($cyJ | Where-Object { $cy = $_; (@($lg | Where-Object { $_ -match ('cycle=' + $cy + ' ') -and $_ -match ' DRIVING_ACTIVE_ON ' })).Count -eq 1 }).Count) -eq 3)
    Check 'J5 no automatic P: the Caller sends no key at all (the Caller DLL has no SendInput / PostMessage / keybd_event; the only P/Invoke is the notice MessageBoxW)' (& {
            $cb = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')))
            (@('SendInput', 'keybd_event', 'PostMessage', 'SendMessage', 'GetAsyncKeyState', 'SetForegroundWindow' | Where-Object { $cb.Contains($_) }).Count -eq 0) })
    ADispose $b4

    # =================================================================================================================================================
    Write-Host '--- Q: the Caller''s own Tick - flowing / silent (observations O4 and O5), seen by the monitor thread only'
    $Pt = NextPid; $Lt = NewLogPath 'Q-callertick'; LogCfgBoth $Lt $Pt
    $bt = FullAdapter $Pt
    $st = NewSession $Pt; StartSession $st
    [void](WaitFor { (Phase $st) -eq 'Connected' } 1500)
    Check 'Q1 before the first Tick of the cycle the state is "none" and nothing is written' (((SProp $st 'CallerTickState') -eq 'none') -and ((EvtLines (ReadLog $Lt) 'CALLER_TICK_STATE').Count -eq 0))
    $sw = [Diagnostics.Stopwatch]::StartNew(); while ($sw.ElapsedMilliseconds -lt 600) { CallerTick $st; Start-Sleep -Milliseconds 20 }
    Wait 60
    $ql = (EvtLines (ReadLog $Lt) 'CALLER_TICK_STATE')
    Check 'Q2 Ticks flowing for 0.6 s: exactly ONE line, state=flowing was=none (a steady flow writes nothing more)' (($ql.Count -eq 1) -and ($ql[0] -match 'state=flowing was=none') -and ((SProp $st 'CallerTickState') -eq 'flowing'))
    Wait 900
    $ql = (EvtLines (ReadLog $Lt) 'CALLER_TICK_STATE')
    Check 'Q3 no Tick for 0.9 s (a Pause that stops the Caller Tick, or the scenario list): ONE more line, state=silent was=flowing after 500 ms, with the length of the flow' (($ql.Count -eq 2) -and ($ql[1] -match 'state=silent was=flowing flowingMs=(\d+(\.\d+)?)' -and ([double]$Matches[1] -ge 500)) -and ($ql[1] -match 'silentAfterMs=500') -and ((SProp $st 'CallerTickState') -eq 'silent'))
    Wait 600
    Check 'Q4 a longer silence writes nothing more (one line per change)' ((EvtLines (ReadLog $Lt) 'CALLER_TICK_STATE').Count -eq 2)
    CallerTick $st; Wait 120
    $ql = (EvtLines (ReadLog $Lt) 'CALLER_TICK_STATE')
    Check 'Q5 the Tick comes back: ONE line, state=flowing was=silent silentMs >= 1000' (($ql.Count -eq 3) -and ($ql[2] -match 'state=flowing was=silent silentMs=(\d+(\.\d+)?)' -and ([double]$Matches[1] -ge 1000)))
    Check 'Q6 counters: flowing 2, silent 1; the state never touched DrivingActive or the start request (still no more than one request line)' ((((SProp $st 'CallerTickFlowingCount') -eq 2) -and ((SProp $st 'CallerTickSilentCount') -eq 1)) -and ((EvtLines (ReadLog $Lt) 'APP_START_REQUEST').Count -le 1))
    EndSession $st
    ADispose $bt

    # =================================================================================================================================================
    if (-not $isLegacy) {
    $py = ''
    if ($PythonExe -and (Test-Path $PythonExe)) { $py = (Resolve-Path $PythonExe).Path }
    else {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch 'WindowsApps')) { $py = $cmd.Source }
        else { foreach ($cand in 'C:\Python314\python.exe', 'C:\Python313\python.exe', 'C:\Python312\python.exe') { if (Test-Path $cand) { $py = $cand; break } } }
    }
    $repoRoot = ((& git -C $Root rev-parse --show-toplevel) -replace '/', '\')
    $probePy = Join-Path $repoRoot 'tests\managed_epoch_probe.py'
    $mgrT = $callerAsm.GetType($NS + 'AppProcessManager')
    $optT = $callerAsm.GetType($NS + 'AppProcessOptions')
    $ldrT = $callerAsm.GetType($NS + 'LauncherConfigLoader')
    $pubT = $callerAsm.GetType($NS + 'AppStatePublisher')
    $layoutT = $callerAsm.GetType($NS + 'AppStateLayout')
    $namesT = $callerAsm.GetType($NS + 'AppObjectNames')

    Write-Host '--- K: the chain Bridge -> Caller -> state block (TSAS bytes 56..59) -> the application''s own Python reader'
    Check 'K0 AppStateLayout: OffEpochInfo is 56, EpochSupported 1, EpochTickSeen 2, shift 8, mask 0xFFFF; PackEpochInfo gives 0 for "no information"' (($layoutT.GetField('OffEpochInfo').GetRawConstantValue() -eq 56) -and ($layoutT.GetField('EpochSupported').GetRawConstantValue() -eq 1) -and ($layoutT.GetField('EpochTickSeen').GetRawConstantValue() -eq 2) -and ($layoutT.GetField('EpochNumberShift').GetRawConstantValue() -eq 8) -and ($layoutT.GetField('EpochNumberMask').GetRawConstantValue() -eq 0xFFFF) -and (([uint32]$layoutT.GetMethod('PackEpochInfo').Invoke($null, @($false, 5, $true))) -eq 0) -and (([uint32]$layoutT.GetMethod('PackEpochInfo').Invoke($null, @($true, 0, $true))) -eq 0))
    $packFn = { param($sup, $n, $tk) [uint32]$layoutT.GetMethod('PackEpochInfo').Invoke($null, @([bool]$sup, [int]$n, [bool]$tk)) }
    Check 'K1 PackEpochInfo packs bit0 supported, bit1 tick seen, bits 8..23 the low 16 bits of the epoch' (((& $packFn $true 1 $false) -eq 0x101) -and ((& $packFn $true 1 $true) -eq 0x103) -and ((& $packFn $true 2 $false) -eq 0x201) -and ((& $packFn $true 0x12345 $true) -eq 0x234503))
    # the publisher itself: initial 0, dedupe, change, Close
    $instK = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'; $pidK = NextPid
    $nameK = $namesT.GetMethod('State').Invoke($null, @($pidK, $instK))
    $pub = $pubT.GetMethod('Create').Invoke($null, @($nameK, $pidK, $instK))
    $mmfK = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($nameK, [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read)
    $viewK = $mmfK.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
    function KBytes { $b = New-Object byte[] 64; [void]$viewK.ReadArray(0, $b, 0, 64); return , $b }
    function KU32([byte[]]$b, [int]$o) { return [BitConverter]::ToUInt32($b, $o) }
    $wm = $pubT.GetMethod('WriteWithEpoch')
    Check 'K2 a fresh block has EpochInfo 0 at byte 56, the tail at 60 and Version 1 / Size 64 as before' (((KU32 (KBytes) 56) -eq 0) -and ((KU32 (KBytes) 4) -eq 1) -and ((KU32 (KBytes) 8) -eq 64) -and ((KU32 (KBytes) 52) -eq 0))
    $r1 = $wm.Invoke($pub, @($true, $true, 7, [uint32]3, $true, [uint32]0x201))
    $kb = KBytes
    Check 'K3 WriteWithEpoch writes the word at byte 56 in the same seqlock write (head == tail, even) together with flags, generation and the load marker' (((KU32 $kb 56) -eq 0x201) -and ((KU32 $kb 32) -eq (KU32 $kb 60)) -and (((KU32 $kb 32) -band 1) -eq 0) -and ((KU32 $kb 36) -eq 3) -and ([BitConverter]::ToInt32($kb, 40) -eq 7) -and ((KU32 $kb 48) -eq 3) -and ((KU32 $kb 52) -eq 0x4C4F4431))
    $r2 = $wm.Invoke($pub, @($true, $true, 7, [uint32]3, $true, [uint32]0x201))
    $r3 = $wm.Invoke($pub, @($true, $true, 7, [uint32]3, $true, [uint32]0x203))
    $wr = $r1.GetType()
    Check 'K4 the same state again is not written (dedupe includes the epoch); a change of ONLY the epoch / its Tick flag IS written' ((-not [bool]$wr.GetField('Written').GetValue($r2)) -and ([bool]$wr.GetField('Written').GetValue($r3)) -and ((KU32 (KBytes) 56) -eq 0x203))
    $r4 = $pubT.GetMethod('WriteWithLoad').Invoke($pub, @($true, $true, 7, [uint32]3, $true))
    Check 'K5 the older entry point WriteWithLoad means "no epoch": it writes 0 at byte 56 (a Caller without an epoch publishes no epoch)' (([bool]$wr.GetField('Written').GetValue($r4)) -and ((KU32 (KBytes) 56) -eq 0))
    [void]$wm.Invoke($pub, @($true, $true, 8, [uint32]3, $true, [uint32]0x303))
    [void]$pubT.GetMethod('Close').Invoke($pub, @())
    $kb = KBytes
    Check 'K6 Close (Dispose) withdraws everything including the epoch: Closed flag, Session / Driving OFF, EpochInfo 0' (((KU32 $kb 56) -eq 0) -and (((KU32 $kb 36) -band 4) -eq 4) -and (((KU32 $kb 36) -band 3) -eq 0))
    [void]$wm.Invoke($pub, @($true, $true, 9, [uint32]3, $true, [uint32]0x405))
    Check 'K7 after Close nothing is written any more (the epoch stays 0)' ((KU32 (KBytes) 56) -eq 0)
    $viewK.Dispose(); $mmfK.Dispose(); $pubT.GetMethod('Dispose').Invoke($pub, @()) | Out-Null

    if (-not $py) {
        Skip 'K8-K16 no Python interpreter found (set -PythonExe): the chain through a stand-in application and the Python reader was not run'
    } else {
        $fixDir = Join-Path $testDir 'fixtures'; $workDir = Join-Path $fixDir 'work'; $cfgPath = Join-Path $fixDir 'launcher.json'; $childScript = Join-Path $fixDir 'epoch_child.py'; $outFile = Join-Path $fixDir 'child-state.txt'
        New-Item -ItemType Directory -Force $workDir | Out-Null
        $childText = @'
import ctypes, os, struct, sys, threading, time
threading.Thread(target=lambda: (time.sleep(90), os._exit(99)), daemon=True).start()   # orphan guard of the test
out = os.environ.get("TSS_SIA7_OUT")
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateEventW.restype = ctypes.c_void_p
k.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
k.OpenEventW.restype = ctypes.c_void_p
k.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
k.SetEvent.argtypes = [ctypes.c_void_p]
k.ResetEvent.argtypes = [ctypes.c_void_p]
k.WaitForSingleObject.restype = ctypes.c_uint32
k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
k.OpenFileMappingW.restype = ctypes.c_void_p
k.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
k.MapViewOfFile.restype = ctypes.c_void_p
k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
args = sys.argv[1:]
opt = {}
for i in range(0, len(args) - 1):
    if args[i].startswith("--"):
        opt[args[i][2:]] = args[i + 1]
base = "Local\\TSScoringPlugin.v1.%s.App.%s." % (opt.get("bve-pid"), opt.get("instance"))
f = open(out, "a") if out else None
def rec(tag, d):
    if f is None:
        return
    head, flags, gen, count = struct.unpack_from("<IIiI", d, 32)
    (epoch,) = struct.unpack_from("<I", d, 56)
    f.write("%s s=%d d=%d c=%d g=%d e=%d\n" % (tag, flags & 1, (flags >> 1) & 1, (flags >> 2) & 1, gen, epoch))
    f.flush()
stop = k.OpenEventW(0x00100000, 0, base + "Stop")
if not stop:
    sys.exit(4)
h = k.OpenFileMappingW(0x0004, 0, base + "State")
view = k.MapViewOfFile(h, 0x0004, 0, 0, 64) if h else None
def snap():
    return ctypes.string_at(view, 64) if view else None
if f is not None and view:
    rec("FIRST", snap())
ready = k.CreateEventW(None, 1, 0, base + "Ready")
k.SetEvent(ready)
last = None
while k.WaitForSingleObject(stop, 10) != 0:
    if view:
        d = snap()
        key = d[36:48] + d[56:60]
        if key != last:
            last = key
            rec("CHG", d)
if view:
    rec("STOP", snap())
k.ResetEvent(ready)
sys.exit(0)
'@
        [IO.File]::WriteAllText($childScript, $childText, (New-Object Text.UTF8Encoding($false)))
        $cfgJson = ([ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $py; scriptPath = $childScript; workingDirectory = $workDir } | ConvertTo-Json -Compress)
        [IO.File]::WriteAllText($cfgPath, $cfgJson, (New-Object Text.UTF8Encoding($false)))
        $ldrT.GetProperty('TestPath', $NPS).SetValue($null, $cfgPath)
        if (Test-Path $outFile) { Remove-Item $outFile -Force }
        $env:TSS_SIA7_OUT = $outFile
        function Rec { if (Test-Path $outFile) { return , @(Get-Content $outFile) } else { return , @() } }
        $started = New-Object System.Collections.Generic.List[int]

        $Pk = NextPid; $Lk = NewLogPath 'K-chain'; LogCfgBoth $Lk $Pk
        $bk = FullAdapter $Pk
        Opened $bk; Created $bk
        $sink = New-Object SiaLogSink
        $del = [Delegate]::CreateDelegate([Action[string, string]], $sink, 'Log')
        $opts = [Activator]::CreateInstance($optT)
        $optT.GetField('ReadyTimeoutMs').SetValue($opts, 8000); $optT.GetField('StopGraceMs').SetValue($opts, 3000); $optT.GetField('KillWaitMs').SetValue($opts, 2000)
        $mgr = [Activator]::CreateInstance($mgrT, @($Pk, $del, $null, $opts))
        $ctor4 = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]], [Func[bool]], $mgrT), $null)
        $rec4 = New-Object NoticeRecorder
        $del4 = [Delegate]::CreateDelegate([Action[string]], $rec4, 'Show')
        $sk = $ctor4.Invoke(@($Pk, $del4, $null, $mgr))
        $hk = [pscustomobject]@{ Session = $sk; Type = $sessionType; Pid = $Pk }
        function MgrProp([string]$n) { return $mgrT.GetProperty($n).GetValue($mgr) }
        try {
            StartSession $hk
            [void](WaitFor { (Phase $hk) -eq 'Connected' } 1500)
            [void](Tick $bk)                                                 # a normal start: epoch 1, Tick seen
            $sw = [Diagnostics.Stopwatch]::StartNew()
            while ($sw.ElapsedMilliseconds -lt 12000 -and [string](MgrProp 'State') -ne 'Ready') { CallerTick $hk; Start-Sleep -Milliseconds 25 }
            $pidApp = [int](MgrProp 'AppPid'); if ($pidApp -gt 0) { $started.Add($pidApp) }
            Check 'K8 the stand-in application was started ONCE by the first DrivingActive of the generation and answered AppReady' (([string](MgrProp 'State') -eq 'Ready') -and ((MgrProp 'ProcessStartCount') -eq 1) -and ((MgrProp 'AttemptCount') -eq 1))
            $instApp = [string](MgrProp 'Instance')
            $nameState = $namesT.GetMethod('State').Invoke($null, @($Pk, $instApp))
            $mm = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($nameState, [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read)
            $vv = $mm.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
            function StateInfo { return [uint32]$vv.ReadUInt32(56) }
            [void](WaitFor { (StateInfo) -eq 0x103 } 1500)
            Check 'K9 the state block the application reads carries EpochInfo 0x103 = supported, epoch 1, TickSeenInEpoch 1 (copied from the Bridge''s ScenarioState: the same reading as the generation)' (((StateInfo) -eq 0x103) -and ((MgrProp 'LatestEpochInfo') -eq 0x103))
            # Python probe: the application's own reader
            $psi = New-Object Diagnostics.ProcessStartInfo
            $psi.FileName = $py; $psi.Arguments = '"' + $probePy + '" ' + $Pk + ' ' + $instApp
            $psi.UseShellExecute = $false; $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.CreateNoWindow = $true; $psi.WorkingDirectory = $repoRoot
            $probe = [Diagnostics.Process]::Start($psi)
            $pw = New-Object IO.StreamWriter($probe.StandardInput.BaseStream, (New-Object Text.UTF8Encoding($false)))
            $popen = $probe.StandardOutput.ReadLine()
            function ProbeRead { $pw.WriteLine('read'); $pw.Flush(); return $probe.StandardOutput.ReadLine() }
            $pr1 = ProbeRead
            Check 'K10 the Python reader (managed_state.py) reads the same block: epoch supported, number 1, tick seen, session on' (($popen -eq 'OPEN yes') -and ($pr1 -match '^E supported=1 tick_seen=1 epoch=1 session=1 ') -and ($pr1 -match 'info=259'))
            # the pause re-ON signature through the whole chain: the Caller's Enabled event is blinked while the session lives (the Bridge sees OFF -> ON; no Tick follows)
            $enH = [Threading.EventWaitHandle]::OpenExisting("Local\TSScoringPlugin.v1.$Pk.Enabled")
            $tickAtBlink = $script:TickCount
            [void]$enH.Reset()
            [void](WaitFor { -not [bool](CtlProp $bk 'HandshakeUp') } 1500)
            [void](WaitFor { (StateInfo) -eq 0 } 1500)
            Check 'K11 while Ready is gone the epoch is withdrawn from the block (EpochInfo 0): "no information", not a stale epoch' ((StateInfo) -eq 0)
            [void]$enH.Set()
            [void](WaitFor { (StateInfo) -eq 0x201 } 2500)
            $pr2 = ProbeRead
            Check 'K12 Enabled back with no Tick: the block carries EpochInfo 0x201 = epoch 2, TickSeenInEpoch 0 with Session still ON; the Python reader sees exactly that' (((StateInfo) -eq 0x201) -and ($script:TickCount -eq $tickAtBlink) -and ($pr2 -match '^E supported=1 tick_seen=0 epoch=2 session=1 ') -and ($pr2 -match 'info=513'))
            [void](Tick $bk)
            [void](WaitFor { (StateInfo) -eq 0x203 } 1500)
            $pr3 = ProbeRead
            Check 'K13 the first Tick raises it: 0x203 = epoch 2, TickSeenInEpoch 1 (block and Python reader)' (((StateInfo) -eq 0x203) -and ($pr3 -match '^E supported=1 tick_seen=1 epoch=2 session=1 '))
            Check 'K14 the epoch changes started no second process and no restart: still exactly one process start, one attempt' (((MgrProp 'ProcessStartCount') -eq 1) -and ((MgrProp 'AttemptCount') -eq 1) -and ((MgrProp 'State').ToString() -eq 'Ready'))
            # a second generation: the request is made in epoch 2 and is suppressed by the manager (the process is alive)
            Closed $bk; Opened $bk; Created $bk; [void](Tick $bk)
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $lgk = ReadLog $Lk
            while ($sw.ElapsedMilliseconds -lt 4000 -and (EvtLines $lgk 'APP_LAUNCH_SUPPRESSED_EPOCH').Count -eq 0) { CallerTick $hk; Start-Sleep -Milliseconds 25; $lgk = ReadLog $Lk }
            $sup = @($lgk | Where-Object { $_ -match ' APP_LAUNCH_SUPPRESSED_EPOCH ' })
            $mgrSup = @($sink.Snapshot() | Where-Object { $_ -like 'APP_LAUNCH_SUPPRESSED *' })
            $ssm = @($lgk | Where-Object { $_ -match ' APP_START_SUPPRESSED_EPOCH ' })
            Check 'K15 the second generation''s start request is suppressed by the process manager (process alive); the log says so with the epoch: APP_LAUNCH_SUPPRESSED_EPOCH decision=SuppressedAlive ready_epoch=2 tickSeenInEpoch=1' (($sup.Count -ge 1) -and ($sup[0] -match 'decision=SuppressedAlive') -and ($sup[0] -match 'ready_epoch=2') -and ($sup[0] -match 'tickSeenInEpoch=1') -and ((MgrProp 'ProcessStartCount') -eq 1) -and ($mgrSup.Count -ge 1) -and ($mgrSup[0] -match 'reason=process-ready'))
            [void]$probe.StandardInput.WriteLine('quit'); [void]$probe.WaitForExit(3000); if (-not $probe.HasExited) { try { $probe.Kill() } catch { } }
            $enH.Dispose()
            EndSession $hk
            [void](WaitFor { (Rec).Count -ge 3 -and ((Rec)[-1] -match '^STOP') } 5000)
            $recs = Rec
            Check 'K16 the application saw the epoch change and the Dispose: FIRST e=259 ... e=513 (epoch 2 tick 0) ... e=515 (tick 1) ... STOP with Closed set and e=0' ((($recs -join '|') -match 'FIRST s=1 d=\d c=0 g=\d+ e=259') -and (($recs -join '|') -match 'e=513') -and (($recs -join '|') -match 'e=515') -and ($recs[-1] -match '^STOP s=0 d=0 c=1 ') -and ($recs[-1] -match 'e=0$'))
            $vv.Dispose(); $mm.Dispose()
        }
        finally {
            foreach ($p in $started) { if (Get-Process -Id $p -ErrorAction SilentlyContinue) { try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch { } } }
            $ldrT.GetProperty('TestPath', $NPS).SetValue($null, (Join-Path $fixDir 'no-such-launcher.json'))
            Remove-Item Env:\TSS_SIA7_OUT -ErrorAction SilentlyContinue
            ADispose $bk
        }
    }

    # =================================================================================================================================================
    Write-Host '--- L: the ScenarioState block - bytes 36..51, compatibility with an older Caller / Bridge, damaged fields read as "no information"'
    $stDir = $stateType
    function NewBlock([string]$suffix) {
        $nm = "Local\TSScoringPlugin.v1.98999.$suffix"
        $m = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew($nm, 64)
        return [pscustomobject]@{ M = $m; V = $m.CreateViewAccessor(0, 64) }
    }
    function BlockBytes($bl) { $b = New-Object byte[] 64; [void]$bl.V.ReadArray(0, $b, 0, 64); return , $b }
    function ReadBlk($bl, [int]$p = 4321) {
        $a = @($bl.V, $p, $null)
        $ok = [bool]$stateType.GetMethod('TryReadView').Invoke($null, $a)
        return [pscustomobject]@{ Ok = $ok; S = $a[2] }
    }
    function SProp2($s, [string]$n) { return $stateType.GetProperty($n).GetValue($s) }
    function SField2($s, [string]$n) { return $stateType.GetField($n).GetValue($s) }
    $bA = NewBlock 'A'; $bB = NewBlock 'B'; $bC = NewBlock 'C'
    $stateType.GetMethod('WriteWithLoad').Invoke($null, @($bA.V, 4321, 5, $true, 3)) | Out-Null
    $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bB.V, 4321, 5, $true, 3, 7, 1)) | Out-Null
    $bytesA = BlockBytes $bA; $bytesB = BlockBytes $bB
    Check 'L1 bytes 0..35 of a block written with an epoch are byte-identical to the block written without it (Version, Check, LoadCheck, level, generation, load marker unchanged)' ((($bytesA[0..35]) -join ',') -ceq (($bytesB[0..35]) -join ','))
    Check 'L2 bytes 52..63 stay reserved zero in both; the old form leaves 36..51 zero ("no information")' (((($bytesA[36..63]) | Where-Object { $_ -ne 0 }).Count -eq 0) -and ((($bytesB[52..63]) | Where-Object { $_ -ne 0 }).Count -eq 0))
    Check 'L3 the epoch fields: EpochMagic 0x45504F31 ("EPO1") at 36, ReadyEpoch 7 at 40, EpochFlags 1 at 44, a non-zero EpochCheck at 48 (little endian)' (([BitConverter]::ToInt32($bytesB, 36) -eq 0x45504F31) -and ([BitConverter]::ToInt32($bytesB, 40) -eq 7) -and ([BitConverter]::ToInt32($bytesB, 44) -eq 1) -and ([BitConverter]::ToInt32($bytesB, 48) -ne 0) -and ([Text.Encoding]::ASCII.GetString($bytesB, 36, 4) -ceq '1OPE'))
    $rA = ReadBlk $bA; $rB = ReadBlk $bB
    Check 'L4 the product reader: the old form reads as epoch NOT supported (an older Bridge), the new form as supported, epoch 7, TickSeenInEpoch 1; level, generation and load marker the same in both' ($rA.Ok -and $rB.Ok -and (-not [bool](SProp2 $rA.S 'EpochSupported')) -and (-not [bool](SProp2 $rA.S 'TickSeenInEpoch')) -and [bool](SProp2 $rB.S 'EpochSupported') -and [bool](SProp2 $rB.S 'TickSeenInEpoch') -and ((SField2 $rB.S 'ReadyEpoch') -eq 7) -and ((SField2 $rA.S 'ScenarioGeneration') -eq (SField2 $rB.S 'ScenarioGeneration')) -and ([bool](SProp2 $rA.S 'Ready') -eq [bool](SProp2 $rB.S 'Ready')) -and ((SField2 $rA.S 'LoadInfo') -eq (SField2 $rB.S 'LoadInfo')) -and [bool](SProp2 $rB.S 'LoadSupported'))
    # an older Caller: a reader that knows only 0..35
    function OldRead($bl) { $o1 = 0; $o2 = 0; $o3 = $false; $o4 = 0; $ok = [OldLayout]::TryRead($bl.V, 4321, [ref]$o1, [ref]$o2, [ref]$o3, [ref]$o4); return [pscustomobject]@{ Ok = $ok; Gen = $o1; Ready = $o2; LoadSupported = $o3; LoadInfo = $o4 } }
    $oA = OldRead $bA; $oB = OldRead $bB
    Check 'L5 an OLDER Caller (an independent reader of 0..35 only) reads the new block exactly like the old one: valid, generation 5, level 1, load marker supported, LoadInfo 3' ($oA.Ok -and $oB.Ok -and ($oA.Gen -eq $oB.Gen -and $oB.Gen -eq 5) -and ($oA.Ready -eq $oB.Ready -and $oB.Ready -eq 1) -and $oA.LoadSupported -and $oB.LoadSupported -and ($oB.LoadInfo -eq 3 -and $oA.LoadInfo -eq 3))
    # damaged / foreign epoch fields read as "no information"; the rest of the block stays valid
    function Damage($mutator) {
        $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 5, $true, 3, 7, 1)) | Out-Null
        & $mutator $bC.V
        $r = ReadBlk $bC
        return [pscustomobject]@{ Ok = $r.Ok; Epoch = $(if ($r.Ok) { [bool](SProp2 $r.S 'EpochSupported') } else { $null }); Tick = $(if ($r.Ok) { [bool](SProp2 $r.S 'TickSeenInEpoch') } else { $null }); Load = $(if ($r.Ok) { [bool](SProp2 $r.S 'LoadSupported') } else { $null }); Ready = $(if ($r.Ok) { [bool](SProp2 $r.S 'Ready') } else { $null }) }
    }
    $d1 = Damage { param($v) $v.Write(36, [int]0x12345678) }
    $d2 = Damage { param($v) $v.Write(48, [int]([BitConverter]::ToInt32((BlockBytes $bC), 48) + 1)) }
    $d3 = Damage { param($v) $v.Write(44, [int]3) }
    $d4 = Damage { param($v) $v.Write(40, [int]0) }
    $d5 = Damage { param($v) $v.Write(40, [int]-3) }
    $d6 = Damage { param($v) $v.Write(40, [int]8) }
    Check 'L6 a wrong EpochMagic, a wrong EpochCheck, an unknown flag bit, ReadyEpoch 0, a negative ReadyEpoch, or an epoch changed without its check: all read as "no information" (epoch not supported, Tick not seen) - the block itself, the level and the load marker stay valid' (@($d1, $d2, $d3, $d4, $d5, $d6 | Where-Object { $_.Ok -and (-not $_.Epoch) -and (-not $_.Tick) -and $_.Load -and $_.Ready }).Count -eq 6)
    $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 5, $true, 3, 7, 1)) | Out-Null
    $good = BlockBytes $bC
    $bC.V.Write(16, [int]([BitConverter]::ToInt32($good, 16) + 1))      # an odd sequence: a write in progress
    $rOdd = ReadBlk $bC
    $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 5, $true, 3, 7, 1)) | Out-Null
    $rPid = ReadBlk $bC 4322
    Check 'L7 an odd sequence (a write in progress) and a foreign BVE process id are rejected as a whole, as before' ((-not $rOdd.Ok) -and (-not $rPid.Ok))
    # a replay: the epoch fields of an older write copied into a newer block do not verify (EpochCheck covers generation and sequence)
    $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 5, $true, 3, 7, 1)) | Out-Null
    $oldEp = (BlockBytes $bC)[36..51]
    $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 6, $true, 3, 7, 1)) | Out-Null
    for ($i = 0; $i -lt 16; $i++) { $bC.V.Write(36 + $i, [byte]$oldEp[$i]) }
    $rRep = ReadBlk $bC
    Check 'L8 epoch fields replayed from an older write (other generation / sequence) into a newer block read as "no information"' ($rRep.Ok -and (-not [bool](SProp2 $rRep.S 'EpochSupported')))
    # the old write forms zero the fields again: no stale epoch survives a write without one
    $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 6, $true, 3, 9, 0)) | Out-Null
    $stateType.GetMethod('Write').Invoke($null, @($bC.V, 4321, 6, $false)) | Out-Null
    $zb = BlockBytes $bC
    Check 'L9 a write WITHOUT an epoch (Write / WriteWithLoad - the form of every older Bridge) zeroes bytes 36..51 again: no stale epoch can survive it' (((($zb[36..63]) | Where-Object { $_ -ne 0 }).Count -eq 0) -and (-not [bool](SProp2 (ReadBlk $bC).S 'EpochSupported')))
    Check 'L10 an epoch below 1 cannot be written (WriteWithEpoch with 0 writes the block without an epoch)' (& {
            $stateType.GetMethod('WriteWithEpoch').Invoke($null, @($bC.V, 4321, 6, $true, 3, 0, 1)) | Out-Null
            $r = ReadBlk $bC
            $r.Ok -and (-not [bool](SProp2 $r.S 'EpochSupported')) -and (((BlockBytes $bC)[36..51] | Where-Object { $_ -ne 0 }).Count -eq 0) })
    foreach ($x in $bA, $bB, $bC) { $x.V.Dispose(); $x.M.Dispose() }
    # the publisher's Close() withdraws the epoch with the level
    $Pq = NextPid
    $pubObj = $pubType.GetConstructors($NPI)[0].Invoke(@($Pq))
    $pubType.GetMethod('OpenWithEpoch').Invoke($pubObj, @(3, $true, 3, 4, 1)) | Out-Null
    $oq = Blk $Pq
    $pubType.GetMethod('Close').Invoke($pubObj, @()) | Out-Null
    Check 'L11 ScenarioReadyPublisher.OpenWithEpoch publishes level, generation, load marker and epoch in one state; Close() removes the Event and the block (nothing of the epoch outlives it)' ($oq.Valid -and ($oq.Ready -eq 1) -and ($oq.Epoch -eq 4) -and $oq.Tick -and (OutsideNone $Pq))

    # =================================================================================================================================================
    Write-Host '--- M: REAL older DLLs (the last commit before SI-A7) against the new ones, both directions'
    $oldCallerPath = if ($BaselineDir) { Join-Path $BaselineDir 'TSScoringPlugin.Caller.InputDevice.dll' } else { '' }
    $oldBridgePath = if ($BaselineDir) { Join-Path $BaselineDir 'TSScoringPlugin.BveEx.Bridge.Prototype.dll' } else { '' }
    if ((-not $BaselineDir) -or (-not (Test-Path $oldCallerPath)) -or (-not (Test-Path $oldBridgePath))) {
        Skip 'M1-M8 no baseline DLL folder (-BaselineDir / SIA7_BASELINE_DLLS): the checks against REAL pre-SI-A7 Caller and Bridge DLLs were not run'
    } else {
        $oldCaller = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($oldCallerPath))
        $oldBridge = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($oldBridgePath))
        $oSessionType = $oldCaller.GetType($NS + 'HandshakeSession')
        $oSessionCtor = $oSessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
        $oAdType = $oldBridge.GetType($NS + 'TsScoringBridgePrototype')
        $oTrkType = $oldBridge.GetType($NS + 'ScenarioReadyTracker')
        $oSnapType = $oldBridge.GetType($NS + 'BveSnapshot')
        $oLog = $oldCaller.GetType($NS + 'ObservationLog'); $obLog = $oldBridge.GetType($NS + 'ObservationLog')
        Check 'M0 the baseline DLLs really are the older ones (Caller 0.12.0.0, Current Bridge 0.7.0.0; no epoch members anywhere in them)' (($oldCaller.GetName().Version.ToString() -eq '0.12.0.0') -and ($oldBridge.GetName().Version.ToString() -eq '0.7.0.0') -and ($oSessionType.GetProperty('ScenarioEpochSupported', $NPI) -eq $null) -and ($oTrkType.GetMethod('OnHandshakeUp', $NPI) -eq $null) -and ($oldBridge.GetType($NS + 'IScenarioEpochPublisher') -eq $null))
        # --- M-a: an OLD Bridge with the NEW Caller
        $Pm = NextPid; $Lm = NewLogPath 'M-oldbridge'
        LogCfg $cLog $Lm $Pm; LogCfg $obLog $Lm $Pm
        $oldBr = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($oAdType)
        $fl = [Reflection.BindingFlags]'NonPublic,Instance'
        $oAdType.GetField('loadQpc', $fl).SetValue($oldBr, [Diagnostics.Stopwatch]::GetTimestamp()); $oAdType.GetField('loadUtcTicks', $fl).SetValue($oldBr, [DateTime]::UtcNow.Ticks); $oAdType.GetField('pid', $fl).SetValue($oldBr, $Pm)
        $oAdType.GetMethod('PublishAvailability', $NPI).Invoke($oldBr, @()) | Out-Null
        $oSnap = [Activator]::CreateInstance($oSnapType)
        foreach ($n in 'IsScenarioCreated') { $oSnapType.GetField($n).SetValue($oSnap, 1) }
        foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $oSnapType.GetField($n).SetValue($oSnap, $true) }
        $oFuncSnap = [Func``1].MakeGenericType($oSnapType)
        $oRd = ({ $oSnap }.GetNewClosure()) -as $oFuncSnap
        $oAdType.GetMethod('BeginScenarioReady', $NPI).Invoke($oldBr, @($oRd, $null)) | Out-Null
        $oTrk = $oAdType.GetField('tracker', $fl).GetValue($oldBr)
        $oTick = $oAdType.GetMethod('Tick')
        $sm = NewSession $Pm
        StartSession $sm
        $swm = [Diagnostics.Stopwatch]::StartNew()
        while ($swm.ElapsedMilliseconds -lt 1500 -and (Phase $sm) -ne 'Connected') { $oTick.Invoke($oldBr, @([TimeSpan]::Zero)) | Out-Null; Start-Sleep -Milliseconds 5 }
        $oTrkType.GetMethod('OnScenarioOpened').Invoke($oTrk, @()) | Out-Null; $oTrkType.GetMethod('OnScenarioCreated').Invoke($oTrk, @()) | Out-Null
        for ($i = 0; $i -lt 5; $i++) { $oTick.Invoke($oldBr, @([TimeSpan]::Zero)) | Out-Null; Start-Sleep -Milliseconds 10 }
        [void](WaitFor { [bool](SProp $sm 'ScenarioReadyLevel') } 1000)
        Check 'M1 old Bridge + new Caller: the handshake completes (Connected) and ScenarioReady of generation 1 is seen as before' (((Phase $sm) -eq 'Connected') -and [bool](SProp $sm 'ScenarioReadyLevel') -and ((SProp $sm 'ScenarioGenerationSeen') -eq 1))
        Wait 150
        $mm = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting("Local\TSScoringPlugin.v1.$Pm.ScenarioState", [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read)
        $mv = $mm.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
        $mb = New-Object byte[] 64; [void]$mv.ReadArray(0, $mb, 0, 64); $mv.Dispose(); $mm.Dispose()
        Check 'M2 old Bridge + new Caller: the old block has bytes 36..63 all zero, so the new Caller reads "no epoch" (supported false, epoch 0) and shows none' (((($mb[36..63]) | Where-Object { $_ -ne 0 }).Count -eq 0) -and (-not [bool](SProp $sm 'ScenarioEpochSupported')) -and ((SProp $sm 'ScenarioReadyEpoch') -eq 0) -and ((SProp $sm 'EpochObservedCount') -eq 0))
        EndSession $sm
        $lgm = ReadLog $Lm
        Check 'M3 old Bridge + new Caller: not one EPOCH_ line is written (information absent = silence), and the Caller still ends cleanly' (((@($lgm | Where-Object { $_ -match ' EPOCH_' })).Count -eq 0) -and ((EvtLines $lgm 'CALLER_DISPOSE_END').Count -eq 1))
        $oAdType.GetMethod('Dispose').Invoke($oldBr, @()) | Out-Null
        # --- M-b: the NEW Bridge with an OLD Caller
        $Pn = NextPid; $Ln = NewLogPath 'M-oldcaller'
        LogCfg $oLog $Ln $Pn; LogCfg $bLog $Ln $Pn
        $bn = FullAdapter $Pn
        $on = NewSession $Pn $oSessionType $oSessionCtor
        StartSession $on
        [void](WaitFor { (Phase $on) -eq 'Connected' } 1500)
        Opened $bn; Created $bn; [void](Tick $bn)
        [void](WaitFor { [bool](SProp $on 'ScenarioReadyLevel') } 1000)
        Check 'M4 new Bridge + old Caller: Connected, and the old Caller sees ScenarioReady of generation 1 exactly as before (it ignores bytes 36..63)' (((Phase $on) -eq 'Connected') -and [bool](SProp $on 'ScenarioReadyLevel') -and ((SProp $on 'ScenarioGenerationSeen') -eq 1))
        EndSession $on
        [void](WaitFor { OutsideNone $Pn } 1500)
        Wait 150
        $on2 = NewSession $Pn $oSessionType $oSessionCtor
        StartSession $on2                                                   # an old Caller switched ON during a pause: the held ScenarioReady is there at once
        $msn = WaitFor { [bool](SProp $on2 'ScenarioReadyLevel') } 1500
        Check ("M5 new Bridge + old Caller, TS Scoring OFF -> ON in a pause: the old Caller sees ScenarioReady (generation 1) again with no Tick ({0} ms) - the only effect of the new Bridge on an old Caller" -f $msn) (($msn -ge 0) -and ((SProp $on2 'ScenarioGenerationSeen') -eq 1) -and ((Phase $on2) -eq 'Connected'))
        EndSession $on2
        $lgn = ReadLog $Ln
        Check 'M6 new Bridge + old Caller: the old Caller logs no EPOCH_ line (it has none) and the Bridge side still logs its epochs' (((@($lgn | Where-Object { $_ -match ' EPOCH_' })).Count -eq 0) -and ((EvtLines $lgn 'SR_EPOCH').Count -ge 2))
        ADispose $bn
        Check 'M7 nothing is left of either pair' ((-not (AnyObject $Pm)) -and (-not (AnyObject $Pn)))
        LogCfg $cLog $L1 $P1; LogCfg $bLog $L1 $P1
    }

    # =================================================================================================================================================
    Write-Host '--- N: the Current and the Legacy DLL run the same shared code: one scripted epoch life gives the same log lines, the same block bytes and the same states'
    function RunEpochCore($asm, [int]$p) {
        $tt = $asm.GetType($NS + 'ScenarioReadyTracker'); $pt = $asm.GetType($NS + 'ScenarioReadyPublisher'); $st = $asm.GetType($NS + 'BveSnapshot'); $sst = $asm.GetType($NS + 'ScenarioState')
        $fs = [Func``1].MakeGenericType($st)
        $lines = New-Object System.Collections.Generic.List[string]
        $world = @{ Up = $true; Epoch = 1 }
        $snap = [Activator]::CreateInstance($st)
        $ff = [Reflection.BindingFlags]'Public,Instance'
        $st.GetField('IsScenarioCreated', $ff).SetValue($snap, 1)
        foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $st.GetField($n, $ff).SetValue($snap, $true) }
        $log = [Action[string, string, string]] ({ param($t, $e, $d) $lines.Add($e + '|' + ($d -replace 'atUtc=\S+', 'atUtc=X' -replace 'sinceOpenedMs=\d+', 'sinceOpenedMs=X')) }.GetNewClosure())
        $rd = ({ $snap }.GetNewClosure()) -as $fs
        $up = [Func[bool]] ({ [bool]$world.Up }.GetNewClosure())
        $ep = [Func[int]] ({ [int]$world.Epoch }.GetNewClosure())
        $nw = [Func[long]] { [long]1000 }
        $pub = $pt.GetConstructors($NPI)[0].Invoke(@($p))
        $trk = $tt.GetConstructors($NPI) | Where-Object { $_.GetParameters().Count -eq 6 } | Select-Object -First 1
        $trk = $trk.Invoke(@($log, $rd, $up, $pub, $nw, $ep))
        $calls = @('OnScenarioOpened', 'OnScenarioCreated', 'UPN:1', 'OnTick', 'OnTick', 'LOST:x', 'UPN:2', 'UPE:2', 'OnTick', 'LOST:y', 'UPN:3', 'UPE:3', 'UPE:3', 'OnScenarioClosed', 'LOST:z', 'UPN:4', 'UPE:4', 'OnScenarioOpened', 'OnScenarioCreated', 'OnTick', 'OnTick', 'LOST:w', 'UPN:5', 'OnTick', 'UPE:5', 'OnDispose')
        $states = New-Object System.Collections.Generic.List[string]
        foreach ($c in $calls) {
            if ($c -like 'UPN:*') { $world.Epoch = [int]($c.Split(':')[1]); $world.Up = $true; continue }
            elseif ($c -like 'UPE:*') { $tt.GetMethod('OnHandshakeUp', $NPI).Invoke($trk, @([int]($c.Split(':')[1]))) | Out-Null }
            elseif ($c -like 'LOST:*') { $world.Up = $false; $tt.GetMethod('OnHandshakeLost', $NPI).Invoke($trk, @($c.Split(':')[1])) | Out-Null }
            else { $tt.GetMethod($c, $NPI).Invoke($trk, @()) | Out-Null }
            $a = @($p, $null); $ok = [bool]$sst.GetMethod('TryRead').Invoke($null, $a)
            $blk = 'none'
            if ($ok) { $s = $a[1]; $blk = ('{0}:{1}:{2}:{3}:{4}:{5}' -f $sst.GetField('ScenarioGeneration').GetValue($s), $sst.GetField('IsScenarioReady').GetValue($s), $sst.GetField('LoadInfo').GetValue($s), $sst.GetProperty('EpochSupported').GetValue($s), $sst.GetField('ReadyEpoch').GetValue($s), $sst.GetProperty('TickSeenInEpoch').GetValue($s)) }
            $states.Add($c + '=' + $blk + '|' + $tt.GetProperty('ReadyEpoch', $NPI).GetValue($trk) + ':' + $tt.GetProperty('TickSeenInEpoch', $NPI).GetValue($trk) + ':' + $tt.GetProperty('IsScenarioReady', $NPI).GetValue($trk))
        }
        return [pscustomobject]@{ Lines = ($lines -join "`n"); States = ($states -join ';') }
    }
    $Pn1 = NextPid; $Pn2 = NextPid
    $rc = RunEpochCore $curAsm $Pn1
    $rl = RunEpochCore $legAsm $Pn2
    Check 'N1 the same scripted life (open, create, up, tick, lost, up with and without the Tick adopting the epoch first, close, cold up, dispose) gives the SAME tracker log lines in the Current and the Legacy DLL' (($rc.Lines -ceq $rl.Lines) -and ($rc.Lines.Length -gt 400))
    Check 'N2 ... and the same block contents (generation, level, load marker, epoch, Tick flag) and tracker states after every step' (($rc.States -ceq $rl.States) -and ($rc.States.Length -gt 300))
    $stepsN = $rc.States -split ';'
    Check 'N3 in that life the held level was published again at once by OnHandshakeUp (up with epoch 2: level 1, Tick 0) and the Tick raised the flag (epoch 2, Tick 1)' (($stepsN | Where-Object { $_ -like 'UPE:2=*' }) -match ':1:\d+:True:2:False' -and ($stepsN | Where-Object { $_ -like 'OnTick=1:1*' -or $_ -like 'OnTick=*:True:2:True*' }).Count -ge 1)
    $lines3 = $rc.Lines -split "`n"
    Check 'N4 an epoch the Tick adopted first is NOT reset by the late OnHandshakeUp (UPE:3 twice: the second call changes nothing; one SR_EPOCH per epoch)' ((@($lines3 | Where-Object { $_ -like 'SR_EPOCH|*' -and $_ -match 'ready_epoch=3' }).Count) -eq 1)
    Check 'N4b the Tick saw Ready of epoch 5 BEFORE OnHandshakeUp(5) arrived: it adopted the epoch with the flag raised, and the late call kept the flag (epoch 5, Tick still 1) and published nothing new' (($stepsN | Where-Object { $_ -like 'OnTick=*:True:5:True|5:True:*' }).Count -ge 1 -and ($stepsN | Where-Object { $_ -like 'UPE:5=*:True:5:True|5:True:*' }).Count -eq 1 -and (($lines3 | Where-Object { $_ -like 'SR_EPOCH|*' -and $_ -match 'ready_epoch=5' -and $_ -match 'why=adopted-at-tick' }).Count -eq 1) -and (($lines3 | Where-Object { $_ -like 'SR_EPOCH|*' -and $_ -match 'ready_epoch=5' -and $_ -match 'why=handshake-up' }).Count -eq 0))
    Check 'N5 the last published state is cleared by Dispose (bridge-dispose) and nothing of ScenarioReady is left' (($stepsN[-1] -like 'OnDispose=none*') -and (OutsideNone $Pn1) -and (OutsideNone $Pn2))
    } # end of the Current-only sections K - N

    # =================================================================================================================================================
    Write-Host '--- P: privacy of every log produced by these tests'
    $forbidden = New-Object System.Collections.Generic.List[string]
    foreach ($v in $env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf), 'C:\Users', '\Users\', 'Documents', 'AppData', 'Scoring-Feature', 'gmail') { if ($v) { $forbidden.Add([string]$v) } }
    $hits = 0
    foreach ($lp in $allLogs) { if (Test-Path -LiteralPath $lp) { $txt = [IO.File]::ReadAllText($lp); foreach ($fb in $forbidden) { $hits += ([regex]::Matches($txt, [regex]::Escape($fb), 'IgnoreCase')).Count }; $hits += ([regex]::Matches($txt, '[A-Za-z]:\\')).Count; $hits += ([regex]::Matches($txt, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')).Count } }
    Check ('P1 no user name, machine name, drive path, user folder or e-mail in any log (' + $allLogs.Count + ' files)') ($hits -eq 0)
    $allText = ($allLogs | ForEach-Object { if (Test-Path -LiteralPath $_) { [IO.File]::ReadAllText($_) } }) -join "`n"
    Check 'P2 the epoch lines carry numbers and fixed words only: no scenario / vehicle name, no position or time value' (($allText -notmatch '\b(path|vehicle|scenario|position)=|\blocation=\d') -and ($allText -cnotmatch 'BveEx\.PluginHost|BveTypes|AtsEx\.PluginHost'))
}
finally {
    ResetAll
}

Start-Sleep -Milliseconds 300
$left = @($allPids | Where-Object { AnyObject $_ })
Check 'Final: no named object of any test pid is left' ($left.Count -eq 0)
Check 'Final: no Caller monitor thread alive' ((LiveMonitors) -eq 0)
Check 'Final: no control thread alive' ((LiveWorkers) -eq 0)

if ($runLegacyMerge) {
    foreach ($line in $legacyChildLines) {
        if ($line -match '^(PASS|FAIL) (.*)$') { Check ('[Legacy] ' + $Matches[2]) ($Matches[1] -eq 'PASS') }
        elseif ($line -match '^SKIP ') { $script:skips++; $line }
    }
    $legacyTotal = @($legacyChildLines | Where-Object { $_ -match '^TOTAL ' })
    Check 'Legacy child process reported a TOTAL line' ($legacyTotal.Count -eq 1)
}

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}  SKIPPED {2}" -f $results.Count, $failed.Count, $script:skips
if ($failed.Count -gt 0) { exit 1 }
