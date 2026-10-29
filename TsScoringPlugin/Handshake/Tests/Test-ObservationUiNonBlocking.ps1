# PHASE SI-R5.3 R53-04A fix design, Stage 0 - dynamic RED / GUARD of the "no message pump on the UI (STA) thread" contract of the observation log
# and of the ScenarioReady tracker.
# Background: R53-04A (NRE 2f48547f49ed5650): ObservationLog.Write -> Mutex.WaitOne(30) on the STA UI thread, inside lock(gate), dispatched WM_PAINT into BVE.
# No BVE, no BveEX runtime, no Python. The real built DLLs are loaded from memory (dist\ Current Bridge + Caller). Every log goes to a private file under
# logs\ui-nonblocking-tests (NEVER to the fixed Downloads file). Fake process ids only.
# Rows:  RESULT <id> RED|GUARD PASS|FAIL <detail>.  RED = fails on the current code and must pass after the fix. GUARD = passes now and after.
# Optional prototype mode (Stage 0 validation only):  -ProtoScript <file>  dot-sources a validation script that compiles scratch copies of Shared\ObservationLog.cs
# variants in memory (never a product DLL) and runs the same rows against them.
# This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$ResultsFile = '',
    [string]$ProtoScript = '',
    [string]$FixScript = '',
    [string]$WorkDir = '',
    [string]$FixWorkDir = '',
    [int]$WatchdogSec = 240
)

if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne [Threading.ApartmentState]::STA) {
    $argList = @('-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-Root', $Root)
    if ($ResultsFile) { $argList += @('-ResultsFile', $ResultsFile) }
    if ($ProtoScript) { $argList += @('-ProtoScript', $ProtoScript) }
    if ($FixScript) { $argList += @('-FixScript', $FixScript) }
    if ($WorkDir) { $argList += @('-WorkDir', $WorkDir) }
    if ($FixWorkDir) { $argList += @('-FixWorkDir', $FixWorkDir) }
    $argList += @('-WatchdogSec', $WatchdogSec)
    & powershell.exe @argList
    exit $LASTEXITCODE
}

. (Join-Path $PSScriptRoot 'UiPumpProbe.ps1')
$extraSource = @'
namespace UiPumpProbe
{
    /// <summary>A log sink that blocks its first call after Arm() until Release() (a stalled diagnostic log).</summary>
    public sealed class BlockingLog
    {
        private readonly ManualResetEventSlim gate = new ManualResetEventSlim(false);
        private readonly ManualResetEventSlim entered = new ManualResetEventSlim(false);
        private int armed;
        public int Calls;
        public int BlockedCalls;
        public void Arm() { entered.Reset(); gate.Reset(); Interlocked.Exchange(ref armed, 1); }
        public void Log(string track, string evt, string detail)
        {
            Interlocked.Increment(ref Calls);
            if (Interlocked.CompareExchange(ref armed, 0, 1) == 1) { Interlocked.Increment(ref BlockedCalls); entered.Set(); gate.Wait(8000); }
        }
        public bool WaitEntered(int ms) { return entered.Wait(ms); }
        public void Release() { gate.Set(); }
        public Action<string, string, string> AsAction() { return Log; }
    }

    /// <summary>A log sink that records the event name and whether the calling thread holds the given gate (Monitor.IsEntered).</summary>
    public sealed class GateProbeLog
    {
        public object Gate;
        public readonly List<string> Events = new List<string>();
        public readonly List<bool> GateHeld = new List<bool>();
        public void Log(string track, string evt, string detail)
        {
            Events.Add(evt);
            GateHeld.Add(Gate != null && Monitor.IsEntered(Gate));
        }
        public Action<string, string, string> AsAction() { return Log; }
        public int Count { get { return Events.Count; } }
    }

    /// <summary>A stamped log sink that is slow (30 ms per line): a time stamp taken at DELIVERY would be spread over many ms, a snapshot taken inside the gate is not.</summary>
    public sealed class StampRecorder
    {
        public readonly List<long> Qpc = new List<long>();
        public readonly List<string> Events = new List<string>();
        public void Log(string track, string evt, string detail, DateTime now, long qpc) { Events.Add(evt); Qpc.Add(qpc); Thread.Sleep(30); }
        public Action<string, string, string, DateTime, long> AsAction() { return Log; }
    }
    /// <summary>A log sink that, on its FIRST call, runs a callback on the same thread (a re-entrant call from inside the log).</summary>
    public sealed class ReentrantLog
    {
        public readonly List<string> Events = new List<string>();
        public readonly List<string> Details = new List<string>();
        public Action First;
        private bool done;
        public void Log(string track, string evt, string detail)
        {
            Events.Add(evt); Details.Add(detail);
            if (!done) { done = true; if (First != null) { First(); } }
        }
        public Action<string, string, string> AsAction() { return Log; }
    }

    public static class OwnershipProbe
    {
        /// <summary>True when ANOTHER thread can take the named mutex at once (so the previous owner released it exactly once).</summary>
        public static bool FreeFromOtherThread(string name)
        {
            bool got = false;
            Thread t = new Thread(delegate ()
            {
                using (Mutex m = new Mutex(false, name))
                {
                    got = m.WaitOne(0);
                    if (got) { m.ReleaseMutex(); }
                }
            });
            t.IsBackground = true; t.Start(); t.Join();
            return got;
        }
    }
    /// <summary>Finite timeout of the whole run: the process ends by itself (exit code 97) if a wait ever hangs.</summary>
    public static class Watchdog
    {
        public static void Start(int seconds)
        {
            Thread t = new Thread(delegate () { Thread.Sleep(seconds * 1000); Console.Error.WriteLine("WATCHDOG: the test run exceeded " + seconds + " s"); Environment.Exit(97); });
            t.IsBackground = true;
            t.Start();
        }
    }

    /// <summary>E1 / E2 / E3 of Stage 0, fixed as facts about the CLR: n contended calls on one thread, how many window messages were dispatched during them.</summary>
    public static class PumpExperiments
    {
        [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

        public static ProbeResult Trials(string kind, ApartmentState apt, int n)
        {
            return Probe.OnThread("TRIALS." + kind, apt, delegate (ProbeWindow w, ProbeResult r)
            {
                string name = "Local\\TSScoringPlugin.u0." + Guid.NewGuid().ToString("N");
                object o = new object();
                int dispatched = 0; int unexpected = 0; double worst = 0;
                MonitorHolder mon = null; MutexHolder mtx = null; Mutex m = null;
                try
                {
                    if (kind == "Monitor.TryEnter0") { mon = new MonitorHolder(o); mon.Start(); }
                    else { mtx = new MutexHolder(name, false); mtx.Start(); m = new Mutex(false, name); }
                    for (int i = 0; i < n; i++)
                    {
                        w.Post();
                        Thread sender = w.SendFromOtherThread();
                        w.WaitSentPending(1000);
                        int before = w.Total;
                        Stopwatch sw = Stopwatch.StartNew();
                        if (kind == "Monitor.TryEnter0") { if (Monitor.TryEnter(o, 0)) { unexpected++; Monitor.Exit(o); } }
                        else if (kind == "Mutex.WaitOne0") { if (m.WaitOne(0)) { unexpected++; m.ReleaseMutex(); } }
                        else if (kind == "Mutex.WaitOne30") { if (m.WaitOne(30)) { unexpected++; m.ReleaseMutex(); } }
                        else if (kind == "WaitForSingleObject0") { if (WaitForSingleObject(m.SafeWaitHandle.DangerousGetHandle(), 0) == 0) { unexpected++; m.ReleaseMutex(); } }
                        sw.Stop();
                        if (sw.Elapsed.TotalMilliseconds > worst) { worst = sw.Elapsed.TotalMilliseconds; }
                        dispatched += w.Total - before;
                        w.Drain();
                        sender.Join(3000);
                    }
                }
                finally
                {
                    if (mon != null) { mon.Dispose(); }
                    if (m != null) { m.Dispose(); }
                    if (mtx != null) { mtx.Dispose(); }
                }
                r.ElapsedMs = worst; r.Dispatched = dispatched; r.Value = "unexpectedTrue=" + unexpected + " calls=" + n;
            });
        }
    }
    public static class StaticFuncs
    {
        public static Func<bool> True() { return delegate () { return true; }; }
        public static Func<long> Now() { return delegate () { return 1000L; }; }
        public static Func<int> IsCreatedOne() { return delegate () { return 1; }; }
        public static Func<string> NullText() { return delegate () { return null; }; }
        public static Func<string> Yes() { return delegate () { return "Y"; }; }
        public static Action<string, string, string> NullLog() { return delegate (string a, string b, string c) { }; }
    }

    public sealed class WorkerCall
    {
        public Exception Error;
        public bool Done;
        private Thread thread;
        public void Start(MethodInfo method, object target, object[] args)
        {
            thread = new Thread(delegate ()
            {
                try { method.Invoke(target, args); }
                catch (Exception ex) { Error = ex; }
                finally { Done = true; }
            });
            thread.IsBackground = true;
            thread.Start();
        }
        public bool Join(int ms) { return thread == null || thread.Join(ms); }
    }

    public static class ProductCalls
    {
        /// <summary>One reflected call on a NEW thread of the given apartment, optionally while a named Mutex / a Monitor is held by another thread for holdMs.</summary>
        public static ProbeResult InvokeOnThread(string name, ApartmentState apt, MethodInfo method, object target, object[] args, string mutexName, object syncToHold, int holdMs)
        {
            return Probe.OnThread(name, apt, delegate (ProbeWindow w, ProbeResult r)
            {
                MutexHolder mh = null;
                MonitorHolder sh = null;
                Thread releaser = null;
                try
                {
                    if (mutexName != null) { mh = new MutexHolder(mutexName, false); mh.Start(); }
                    if (syncToHold != null) { sh = new MonitorHolder(syncToHold); sh.Start(); }
                    if (mh != null || sh != null)
                    {
                        MutexHolder mh2 = mh; MonitorHolder sh2 = sh;
                        releaser = new Thread(delegate () { Thread.Sleep(holdMs); if (sh2 != null) { sh2.Release(); } if (mh2 != null) { mh2.Release(); } });
                        releaser.IsBackground = true;
                        releaser.Start();
                    }
                    Probe.MeasureMethod(w, r, method, target, args);
                }
                finally
                {
                    if (releaser != null) { releaser.Join(); }
                    if (mh != null) { mh.Dispose(); }
                    if (sh != null) { sh.Dispose(); }
                }
            });
        }

        /// <summary>n reflected calls on one new thread while the named Mutex is held for holdMs. Stops after 3 calls slower than budgetMs (the old code would take n * 30 ms).</summary>
        public static ProbeResult Burst(string name, ApartmentState apt, MethodInfo method, string[] argsTemplate, string mutexName, int holdMs, int n, double budgetMs)
        {
            return Probe.OnThread(name, apt, delegate (ProbeWindow w, ProbeResult r)
            {
                MutexHolder mh = new MutexHolder(mutexName, false);
                mh.Start();
                MutexHolder mh2 = mh;
                Thread releaser = new Thread(delegate () { Thread.Sleep(holdMs); mh2.Release(); });
                releaser.IsBackground = true;
                releaser.Start();
                double worst = 0; int dispatched = 0; int calls = 0; int breaches = 0;
                Thread sender = w.SendFromOtherThread();
                w.WaitSentPending(1000);
                try
                {
                    for (int i = 0; i < n; i++)
                    {
                        w.Post();
                        int before = w.Total;
                        Stopwatch sw = Stopwatch.StartNew();
                        try { method.Invoke(null, new object[] { argsTemplate[0], argsTemplate[1], "k=" + i }); } catch (Exception) { }
                        sw.Stop();
                        calls++;
                        double ms = sw.Elapsed.TotalMilliseconds;
                        if (ms > worst) { worst = ms; }
                        dispatched += w.Total - before;
                        if (ms > budgetMs) { breaches++; if (breaches >= 3) { break; } }
                    }
                }
                finally { releaser.Join(); mh.Dispose(); }
                r.ElapsedMs = worst; r.Dispatched = dispatched;
                r.Value = "calls=" + calls + " breaches=" + breaches;
            });
        }

        public static void HammerMta(MethodInfo callerWrite, MethodInfo bridgeWrite, int threadsPerDll, int perThread)
        {
            List<Thread> list = new List<Thread>();
            foreach (MethodInfo m in new MethodInfo[] { callerWrite, bridgeWrite })
            {
                for (int k = 0; k < threadsPerDll; k++)
                {
                    MethodInfo mm = m;
                    Thread t = new Thread(delegate () { for (int i = 1; i <= perThread; i++) { mm.Invoke(null, new object[] { "B", "G5_WRITE", "k=" + i }); } });
                    t.SetApartmentState(ApartmentState.MTA);
                    list.Add(t);
                    t.Start();
                }
            }
            foreach (Thread t in list) { t.Join(); }
        }
    }
}
'@
Install-UiPumpProbe -ExtraSource $extraSource -ExtraMarkerType 'UiPumpProbe.ProductCalls'
[UiPumpProbe.Watchdog]::Start($WatchdogSec)

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
if ($FixScript) {
    # Stage 0 validation: the integrated scratch prototype replaces BOTH dist assemblies (its ObservationLog serves the Bridge and the Caller rows)
    . $FixScript
    $fixAsm = New-FixBridgeAssembly -Root $Root -WorkDir $(if ($FixWorkDir) { $FixWorkDir } else { Join-Path $Root 'logs\ui-nonblocking-fix-src' })
    $bridgeAsm = $fixAsm; $callerAsm = $fixAsm
}
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$bridgeType = $bridgeAsm.GetType($NS + 'TsScoringBridgePrototype')
$trkType = $bridgeAsm.GetType($NS + 'ScenarioReadyTracker')
$obsType = $bridgeAsm.GetType($NS + 'ScenarioObserver')
$pubType = $bridgeAsm.GetType($NS + 'ScenarioReadyPublisher')
$stateType = $bridgeAsm.GetType($NS + 'ScenarioState')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $bridgeAsm.GetType($NS + 'ObservationLog')

$testDir = $(if ($WorkDir) { $WorkDir } else { Join-Path $Root 'logs\ui-nonblocking-tests' })
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null
$rows = New-Object System.Collections.Generic.List[string]
function Row([string]$id, [string]$kind, [bool]$ok, [string]$detail) {
    $line = 'RESULT {0} {1} {2} {3}' -f $id, $kind, $(if ($ok) { 'PASS' } else { 'FAIL' }), $detail
    $rows.Add($line); $line
}
$BudgetMs = 15.0        # one Write on the UI thread (old code: >= 30 ms when the mutex is busy)
$FlowBudgetMs = 50.0    # one lifecycle handler (old code: several waits of 30 ms)

function LogCfg($type, [string]$path, [int]$fakePid, [long]$max = 0) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]$max)
}
function MutexName([int]$fakePid) { return 'Local\TSScoringPlugin.v1.' + $fakePid + '.ObsLogLock' }
function ReadLog([string]$path) { if (Test-Path -LiteralPath $path) { return @(Get-Content -LiteralPath $path -Encoding UTF8) } else { return @() } }
function WriteMethod($type) { return $type.GetMethod('Write', $NPS) }
function Fmt($r) { return ('ms={0:F1} dispatched={1} {2}' -f $r.ElapsedMs, $r.Dispatched, $r.Value) }

# ---------------- R1 / R1b / V1 / V2: ObservationLog.Write on STA (Bridge copy and Caller copy of the shared source) ----------------
$targets = @(@{ Name = 'Bridge'; Type = $bLog }, @{ Name = 'Caller'; Type = $cLog })
$pidCounter = 941000
foreach ($t in $targets) {
    $pidCounter++
    $p = $pidCounter
    $path = Join-Path $testDir ('r1-' + $t.Name + '.log')
    LogCfg $t.Type $path $p
    $write = WriteMethod $t.Type
    $write.Invoke($null, @('B', 'R1_INIT', 'k=0')) | Out-Null    # run initialisation outside the measured call
    $mname = MutexName $p
    # R1: Mutex busy on another thread, STA caller
    $r = [UiPumpProbe.ProductCalls]::InvokeOnThread('R1', [Threading.ApartmentState]::STA, $write, $null, @('A', 'R1_PROBE', 'k=1'), $mname, $null, 400)
    Row ('R1-' + $t.Name) 'RED' (($r.Dispatched -eq 0) -and ($r.ElapsedMs -le $BudgetMs)) ('STA Write, mutex busy: ' + (Fmt $r))
    # V1: nothing busy -> no dispatch, fast, line written
    $r = [UiPumpProbe.ProductCalls]::InvokeOnThread('V1', [Threading.ApartmentState]::STA, $write, $null, @('A', 'V1_FREE', 'k=1'), $null, $null, 0)
    $wrote = (@(ReadLog $path | Where-Object { $_ -match ' V1_FREE ' }).Count -eq 1)
    Row ('V1-' + $t.Name) 'GUARD' (($r.Dispatched -eq 0) -and ($r.ElapsedMs -le $BudgetMs) -and $wrote) ('STA Write, nothing busy: ' + (Fmt $r) + ' lineWritten=' + $wrote)
    # V2: MTA caller with the mutex busy: no window pump (probe is not blind to the apartment), the old wait-and-drop contract is unchanged
    $r = [UiPumpProbe.ProductCalls]::InvokeOnThread('V2', [Threading.ApartmentState]::MTA, $write, $null, @('A', 'V2_MTA', 'k=1'), $mname, $null, 400)
    Row ('V2-' + $t.Name) 'GUARD' (($r.Dispatched -eq 0) -and ($r.ElapsedMs -ge 25.0)) ('MTA Write, mutex busy waits (contract): ' + (Fmt $r))
    # R1b: the in-process lock (sync) busy on another thread, STA caller
    $syncField = $t.Type.GetField('sync', [Reflection.BindingFlags]'NonPublic,Static')
    $syncObj = $syncField.GetValue($null)
    $r = [UiPumpProbe.ProductCalls]::InvokeOnThread('R1b', [Threading.ApartmentState]::STA, $write, $null, @('A', 'R1B_PROBE', 'k=1'), $null, $syncObj, 150)
    Row ('R1b-' + $t.Name) 'RED' (($r.Dispatched -eq 0) -and ($r.ElapsedMs -le $BudgetMs)) ('STA Write, lock(sync) busy: ' + (Fmt $r))
}

# ---------------- R6(a): a long contention burst on STA: every call stays inside the budget and never dispatches ----------------
$pidCounter++
$p6 = $pidCounter
$path6 = Join-Path $testDir 'r6-Bridge.log'
LogCfg $bLog $path6 $p6
(WriteMethod $bLog).Invoke($null, @('B', 'R6_INIT', 'k=0')) | Out-Null
$r = [UiPumpProbe.ProductCalls]::Burst('R6', [Threading.ApartmentState]::STA, (WriteMethod $bLog), @('A', 'R6_BURST'), (MutexName $p6), 1500, 300, $BudgetMs)
Row 'R6a-Bridge' 'RED' (($r.Dispatched -eq 0) -and ($r.ElapsedMs -le $BudgetMs)) ('STA burst, mutex busy: worst ' + (Fmt $r))

# ---------------- helpers for the observer / tracker / adapter cases ----------------
function Outside([int]$p) {
    $a = @($p, $null)
    $ok = [bool]$stateType.GetMethod('TryRead').Invoke($null, $a)
    $gen = -1; $rdy = -1
    if ($ok) { $gen = [int]$stateType.GetField('ScenarioGeneration').GetValue($a[1]); $rdy = [int]$stateType.GetField('IsScenarioReady').GetValue($a[1]) }
    return [pscustomobject]@{ Valid = $ok; Gen = $gen; Ready = $rdy }
}
function WaitGen([int]$p, [int]$gen, [int]$timeoutMs) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $timeoutMs) { if ((Outside $p).Gen -ge $gen) { return $true }; Start-Sleep -Milliseconds 5 }
    return ((Outside $p).Gen -ge $gen)
}
function NewTracker($logAction, [int]$p) {
    $pub = $pubType.GetConstructors($NPI)[0].Invoke(@($p))
    $ctor = @($trkType.GetConstructors($NPI) | Where-Object { $_.GetParameters().Count -eq 5 })[0]
    return $ctor.Invoke(@($logAction, $null, [UiPumpProbe.StaticFuncs]::True(), $pub, [UiPumpProbe.StaticFuncs]::Now()))
}
function NewObserver($logAction) {
    $ctor = $obsType.GetConstructors($NPI)[0]
    return $ctor.Invoke(@($logAction, [UiPumpProbe.StaticFuncs]::IsCreatedOne(), [UiPumpProbe.StaticFuncs]::NullText(), [UiPumpProbe.StaticFuncs]::Yes(), [UiPumpProbe.StaticFuncs]::Now()))
}
function Call($obj, $type, [string]$name, [object[]]$callArgs = @()) { $type.GetMethod($name, $NPI).Invoke($obj, $callArgs) | Out-Null }
function NewBridge($observer, $tracker) {
    $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($bridgeType)
    $bridgeType.GetField('observer', $NPI).SetValue($b, $observer)
    $bridgeType.GetField('tracker', $NPI).SetValue($b, $tracker)
    return $b
}
function BridgeObsAction($bridge) { return [Delegate]::CreateDelegate([Action[string, string, string]], $bridge, $bridgeType.GetMethod('Obs', $NPI)) }

# ---------------- R3a: no log call is made while the caller holds the component's own gate ----------------
$gateRows = @()
$probeObs = New-Object UiPumpProbe.GateProbeLog
$observer = NewObserver ($probeObs.AsAction())
$probeObs.Gate = $obsType.GetField('gate', $NPI).GetValue($observer)
$entry = @(
    @('OnAllExtensionsLoaded', @()), @('OnScenarioOpened', @($false)), @('OnPreviewScenarioCreated', @()), @('OnScenarioCreated', @()),
    @('OnTick', @()), @('OnPostTick', @()), @('OnScenarioClosed', @()), @('OnDispose', @())
)
foreach ($e in $entry) {
    $before = $probeObs.Count
    Call $observer $obsType $e[0] $e[1]
    $emitted = $probeObs.Count - $before
    $held = 0; for ($i = $before; $i -lt $probeObs.Count; $i++) { if ($probeObs.GateHeld[$i]) { $held++ } }
    if ($emitted -gt 0) { $gateRows += ('observer.{0}: emits={1} insideOwnGate={2}' -f $e[0], $emitted, $held) }
}
$obsHeld = ($gateRows | Where-Object { $_ -notmatch 'insideOwnGate=0$' }).Count
Row 'R3a-observer' 'RED' ($gateRows.Count -gt 0 -and $obsHeld -eq 0) (($gateRows -join '; '))

$pidCounter++
$p3 = $pidCounter
$probeTrk = New-Object UiPumpProbe.GateProbeLog
$tracker = NewTracker ($probeTrk.AsAction()) $p3
$probeTrk.Gate = $trkType.GetField('gate', $NPI).GetValue($tracker)
$gateRows = @()
$entry = @(
    @('OnScenarioOpened', @()), @('OnTick', @()), @('OnScenarioCreated', @()), @('OnTick', @()), @('OnPostTick', @()), @('OnHandshakeLost', @('probe')),
    @('OnHandshakeUp', @(1)), @('OnScenarioClosed', @()), @('OnScenarioOpened', @()), @('OnDispose', @())
)
foreach ($e in $entry) {
    $before = $probeTrk.Count
    Call $tracker $trkType $e[0] $e[1]
    $emitted = $probeTrk.Count - $before
    $held = 0; for ($i = $before; $i -lt $probeTrk.Count; $i++) { if ($probeTrk.GateHeld[$i]) { $held++ } }
    if ($emitted -gt 0) { $gateRows += ('tracker.{0}: emits={1} insideOwnGate={2}' -f $e[0], $emitted, $held) }
}
$trkHeld = ($gateRows | Where-Object { $_ -notmatch 'insideOwnGate=0$' }).Count
Row 'R3a-tracker' 'RED' ($gateRows.Count -gt 0 -and $trkHeld -eq 0) (($gateRows -join '; '))

# ---------------- R2a: a stalled log never holds back the generation published by the tracker ----------------
$pidCounter++
$p2 = $pidCounter
$blockLog = New-Object UiPumpProbe.BlockingLog
$tracker = NewTracker ($blockLog.AsAction()) $p2
Call $tracker $trkType 'OnScenarioOpened'
Call $tracker $trkType 'OnTick'                       # the publisher opens: generation 1, level 0 is visible
$visibleBefore = (Outside $p2).Gen
$blockLog.Arm()
$worker = New-Object UiPumpProbe.WorkerCall
$worker.Start($trkType.GetMethod('OnScenarioOpened', $NPI), $tracker, @())
$null = $blockLog.WaitEntered(2000)
$reflected = WaitGen $p2 2 400
$blockLog.Release(); $null = $worker.Join(5000)
Row 'R2a-tracker' 'RED' ($visibleBefore -eq 1 -and $reflected) ("log stalled inside OnScenarioOpened: generation visible before=$visibleBefore reflectedWhileStalled=$reflected")
Call $tracker $trkType 'OnDispose'

# ---------------- C'-stamp: log lines keep the time stamp taken INSIDE the gate (needs the StampedLog hook, which the current code does not have) ----------------
$stampField = $obsType.GetField('StampedLog', $NPI)
if ($stampField) {
    $stampRec = New-Object UiPumpProbe.StampRecorder
    $stampObs = NewObserver ([UiPumpProbe.StaticFuncs]::NullLog())
    $stampField.SetValue($stampObs, $stampRec.AsAction())
    Call $stampObs $obsType 'OnScenarioOpened' @($false)
    $spreadMs = 0.0
    if ($stampRec.Qpc.Count -ge 2) { $spreadMs = ($stampRec.Qpc[$stampRec.Qpc.Count - 1] - $stampRec.Qpc[0]) * 1000.0 / [Diagnostics.Stopwatch]::Frequency }
    Row 'C-stamp-core' 'RED' ($stampRec.Qpc.Count -ge 3 -and $spreadMs -lt 10.0) ('events=' + $stampRec.Qpc.Count + ' stamp spread=' + ('{0:F2}' -f $spreadMs) + ' ms (delivery took >= 30 ms per line)')
} else {
    Row 'C-stamp-core' 'RED' $false 'no StampedLog hook: the time stamp of a log line is not part of an immutable payload taken inside the gate'
}
# ---------------- R2b-dynamic: the adapter keeps the tracker moving when the observer's log is stalled / contended / failing ----------------
function AdapterCase([string]$label, [string]$mode) {
    $script:pidCounter++
    $p = $script:pidCounter
    $path = Join-Path $testDir ('adapter-' + $label + '.log')
    $blockAction = New-Object UiPumpProbe.BlockingLog
    $maxBytes = 0
    if ($mode -eq 'cap') { $maxBytes = 400 }
    LogCfg $bLog $path $p $maxBytes
    $bridge = NewBridge $null $null
    $obsAction = $null
    if ($mode -eq 'stall') { $obsAction = $blockAction.AsAction() } else { $obsAction = BridgeObsAction $bridge }
    $observer = NewObserver $obsAction
    $tracker = NewTracker (BridgeObsAction $bridge) $p
    $bridgeType.GetField('observer', $NPI).SetValue($bridge, $observer)
    $bridgeType.GetField('tracker', $NPI).SetValue($bridge, $tracker)
    $open = $bridgeType.GetMethod('OnHackerScenarioOpened', $NPI)
    # first load, nothing busy: generation 1 published
    $open.Invoke($bridge, @($null)) | Out-Null
    Call $tracker $trkType 'OnTick'
    $g1 = (Outside $p).Gen
    if ($mode -eq 'cap') { for ($i = 0; $i -lt 40; $i++) { (WriteMethod $bLog).Invoke($null, @('A', 'CAP_FILL', ('k=' + $i))) | Out-Null } }
    $stream = $null
    if ($mode -eq 'iofail') { $stream = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    $result = $null
    try {
        if ($mode -eq 'stall') {
            $blockAction.Arm()
            $w = New-Object UiPumpProbe.WorkerCall
            $w.Start($open, $bridge, @($null))
            $null = $blockAction.WaitEntered(2000)
            $moved = WaitGen $p 2 400
            $blockAction.Release(); $null = $w.Join(5000)
            $result = [pscustomobject]@{ Moved = $moved; Ms = 0.0; Dispatched = 0 }
        }
        else {
            $mutexName = $null
            if ($mode -eq 'contend') { $mutexName = MutexName $p }
            $r = [UiPumpProbe.ProductCalls]::InvokeOnThread($label, [Threading.ApartmentState]::STA, $open, $bridge, @($null), $mutexName, $null, 600)
            $result = [pscustomobject]@{ Moved = ((Outside $p).Gen -ge 2); Ms = $r.ElapsedMs; Dispatched = $r.Dispatched }
        }
    }
    finally { if ($stream) { $stream.Dispose() } }
    Call $tracker $trkType 'OnDispose'
    return [pscustomobject]@{ G1 = $g1; Moved = $result.Moved; Ms = $result.Ms; Dispatched = $result.Dispatched }
}
$a = AdapterCase 'stall' 'stall'
Row 'B1-stall' 'RED' ($a.G1 -eq 1 -and $a.Moved) ("observer log stalled: tracker generation reflected while stalled=" + $a.Moved)
$a = AdapterCase 'contend' 'contend'
Row 'R5-contend' 'RED' ($a.G1 -eq 1 -and $a.Moved -and $a.Ms -le $FlowBudgetMs -and $a.Dispatched -eq 0) ('STA OnScenarioOpened, mutex busy: ' + ('ms={0:F1} dispatched={1} generationReflected={2}' -f $a.Ms, $a.Dispatched, $a.Moved))
$a = AdapterCase 'iofail' 'iofail'
Row 'B1-io-failure' 'GUARD' ($a.G1 -eq 1 -and $a.Moved -and $a.Dispatched -eq 0) ('log file locked (I/O failure): ' + ('ms={0:F1} dispatched={1} generationReflected={2}' -f $a.Ms, $a.Dispatched, $a.Moved))
$a = AdapterCase 'cap' 'cap'
Row 'B1-capped' 'GUARD' ($a.G1 -eq 1 -and $a.Moved -and $a.Dispatched -eq 0) ('log capped: ' + ('ms={0:F1} dispatched={1} generationReflected={2}' -f $a.Ms, $a.Dispatched, $a.Moved))

# ---------------- P: the non-pumping acquire helper (Owner-approved P/Invoke contract: one declaration, WAIT_* mapping, handle lifetime, release only after a successful acquire) ----------------
function PInvokeNamesOf($type) { return @($type.GetMethods([Reflection.BindingFlags]'NonPublic,Public,Static,Instance,DeclaredOnly') | Where-Object { ($_.Attributes -band [Reflection.MethodAttributes]::PinvokeImpl) -ne 0 } | ForEach-Object { $_.Name } | Sort-Object -Unique) }
foreach ($t in $targets) {
    $classify = $t.Type.GetMethod('ClassifyWaitResult', $NPS)
    $acquire = $t.Type.GetMethod('TryAcquireNoWait', $NPS)
    # P-wait-codes: WAIT_OBJECT_0 -> Acquired, WAIT_ABANDONED -> Abandoned (we own it), WAIT_TIMEOUT -> Busy, WAIT_FAILED and anything else -> Failed
    if ($classify) {
        $map = @{ 0 = 'Acquired'; 128 = 'Abandoned'; 258 = 'Busy'; 4294967295 = 'Failed'; 2147483647 = 'Failed'; 3 = 'Failed' }
        $bad = @(); foreach ($k in $map.Keys) { $got = $classify.Invoke($null, @([uint32]$k)).ToString(); if ($got -ne $map[$k]) { $bad += ('{0}->{1} (want {2})' -f $k, $got, $map[$k]) } }
        Row ('P-wait-codes-' + $t.Name) 'RED' ($bad.Count -eq 0) ('WAIT_OBJECT_0/ABANDONED/TIMEOUT/FAILED mapping ' + $(if ($bad.Count) { $bad -join '; ' } else { 'ok' }))
    } else { Row ('P-wait-codes-' + $t.Name) 'RED' $false 'ClassifyWaitResult helper does not exist' }
    # P-handle-lifetime-and-codes: live mutexes: free -> Acquired, held by another thread -> Busy, abandoned -> Abandoned, disposed handle -> Failed (no exception)
    if ($acquire) {
        $pidCounter++; $nameP = 'Local\TSScoringPlugin.stage0.p.' + $pidCounter
        $detail = @(); $ok = $true
        $m = [Threading.Mutex]::new($false, $nameP)
        $r1 = $acquire.Invoke($null, @($m)).ToString(); if ($r1 -eq 'Acquired') { $m.ReleaseMutex() } else { $ok = $false }; $detail += "free=$r1"
        $holder = New-Object UiPumpProbe.MutexHolder($nameP, $false); $holder.Start()
        $r2 = $acquire.Invoke($null, @($m)).ToString(); if ($r2 -ne 'Busy') { $ok = $false }; $detail += "busy=$r2"; $holder.Release(); $holder.Dispose()
        $nameA = $nameP + '.ab'; $mAb = [Threading.Mutex]::new($false, $nameA); $hAb = New-Object UiPumpProbe.MutexHolder($nameA, $true); $hAb.Start()
        $r3 = 'Busy'; for ($retry = 0; $retry -lt 100 -and $r3 -eq 'Busy'; $retry++) { $r3 = $acquire.Invoke($null, @($mAb)).ToString(); if ($r3 -eq 'Busy') { Start-Sleep -Milliseconds 10 } } # the OS marks the mutex abandoned a moment after the owner thread ended
        if ($r3 -eq 'Abandoned') { $mAb.ReleaseMutex() } else { $ok = $false }; $detail += "abandoned=$r3"; $hAb.Dispose(); $mAb.Dispose()
        $mDead = [Threading.Mutex]::new($false, ($nameP + '.dead')); $mDead.Dispose()
        $r4 = 'threw'; try { $r4 = $acquire.Invoke($null, @($mDead)).ToString() } catch { $r4 = 'threw' }; if ($r4 -ne 'Failed') { $ok = $false }; $detail += "disposed=$r4"
        $m.Dispose()
        Row ('P-handle-lifetime-' + $t.Name) 'RED' $ok ($detail -join ' ')
    } else { Row ('P-handle-lifetime-' + $t.Name) 'RED' $false 'TryAcquireNoWait helper does not exist' }
    # P-pinvoke-inventory: exactly one P/Invoke declaration in the log type, and it is WaitForSingleObject (Bridge assembly: the only one in the whole DLL)
    $names = @(PInvokeNamesOf $t.Type)
    $asmWide = -1
    if ($t.Name -eq 'Bridge') { $asmWide = 0; foreach ($ty in $bridgeAsm.GetTypes()) { $asmWide += @(PInvokeNamesOf $ty).Count } }
    Row ('P-pinvoke-inventory-' + $t.Name) 'RED' (($names.Count -eq 1) -and ($names[0] -eq 'WaitForSingleObject') -and ($t.Name -ne 'Bridge' -or $asmWide -eq 1)) ('log type P/Invokes=[' + ($names -join ',') + '] assemblyWide=' + $asmWide)
    # P-release-once: a successful STA write leaves the mutex free for other threads (ownership released exactly once)
    $pidCounter++; $pRel = $pidCounter; $pathRel = Join-Path $testDir ('p-release-' + $t.Name + '.log'); LogCfg $t.Type $pathRel $pRel
    (WriteMethod $t.Type).Invoke($null, @('B', 'REL_INIT', 'k=0')) | Out-Null
    $null = [UiPumpProbe.ProductCalls]::InvokeOnThread('rel', [Threading.ApartmentState]::STA, (WriteMethod $t.Type), $null, @('A', 'REL_STA', 'k=1'), $null, $null, 0)
    $freeAfter = [UiPumpProbe.OwnershipProbe]::FreeFromOtherThread((MutexName $pRel))
    Row ('P-release-once-' + $t.Name) 'GUARD' ($freeAfter -and (@(ReadLog $pathRel | Where-Object { $_ -match ' REL_STA ' }).Count -eq 1)) ("after a successful STA write another thread can take the mutex at once: $freeAfter")
}

# ---------------- C-drop: the minimal STA contention contract (do not wait, do not write, count, show the count on the next successful write) ----------------
$pidCounter++
$pD = $pidCounter
$pathD = Join-Path $testDir 'c-drop-Bridge.log'
LogCfg $bLog $pathD $pD
(WriteMethod $bLog).Invoke($null, @('B', 'DROP_INIT', 'k=0')) | Out-Null
$r = [UiPumpProbe.ProductCalls]::InvokeOnThread('drop', [Threading.ApartmentState]::STA, (WriteMethod $bLog), $null, @('A', 'DROP_LOST', 'k=1'), (MutexName $pD), $null, 300)
$droppedNow = [int64]$bLog.GetField('dropped', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null)
$null = [UiPumpProbe.ProductCalls]::InvokeOnThread('next', [Threading.ApartmentState]::MTA, (WriteMethod $bLog), $null, @('B', 'DROP_NEXT', 'k=2'), $null, $null, 0)
$null = [UiPumpProbe.ProductCalls]::InvokeOnThread('next2', [Threading.ApartmentState]::MTA, (WriteMethod $bLog), $null, @('B', 'DROP_NEXT2', 'k=3'), $null, $null, 0)
$linesD = ReadLog $pathD
$lostAbsent = (@($linesD | Where-Object { $_ -match ' DROP_LOST ' }).Count -eq 0)
$shown = (@($linesD | Where-Object { $_ -match ' DROP_NEXT k=2 droppedBefore=1$' }).Count -eq 1) -and (@($linesD | Where-Object { $_ -match ' DROP_NEXT2 k=3$' }).Count -eq 1)
Row 'C-drop-Bridge' 'RED' (($r.Dispatched -eq 0) -and ($r.ElapsedMs -le $BudgetMs) -and $lostAbsent -and $shown -and $droppedNow -eq 1) ('STA busy: ' + (Fmt $r) + " lineWritten=$(-not $lostAbsent) counterAfterDrop=$droppedNow shownOnNextWrite=$shown")
Row 'C-drop-never-late-Bridge' 'GUARD' ($lostAbsent) 'a dropped line never appears later'
# the documented diagnostic limit: a drop with no later successful write is not visible in the log at all
$pidCounter++; $pU = $pidCounter; $pathU = Join-Path $testDir 'c-drop-unreported.log'; LogCfg $bLog $pathU $pU
(WriteMethod $bLog).Invoke($null, @('B', 'UNREP_INIT', 'k=0')) | Out-Null
$null = [UiPumpProbe.ProductCalls]::InvokeOnThread('unrep', [Threading.ApartmentState]::STA, (WriteMethod $bLog), $null, @('A', 'UNREP_LOST', 'k=1'), (MutexName $pU), $null, 300)
$cnt = [int64]$bLog.GetField('dropped', [Reflection.BindingFlags]'NonPublic,Static').GetValue($null)
Row 'C-drop-unreported-limit' 'GUARD' (($cnt -eq 1) -and (@(ReadLog $pathU | Where-Object { $_ -match 'UNREP_LOST|droppedBefore' }).Count -eq 0)) "known diagnostic limit: last drop is counted ($cnt) but not visible in the log until a later successful write"

# ---------------- C'-snapshot: the payload of a log line is built inside the gate; a re-entrant call made from inside the log callback cannot change it ----------------
$reLog = New-Object UiPumpProbe.ReentrantLog
$reObs = NewObserver ($reLog.AsAction())
$reLog.First = [Action]{ Call $reObs $obsType 'OnScenarioClosed'; Call $reObs $obsType 'OnScenarioOpened' @($false) }
Call $reObs $obsType 'OnScenarioOpened' @($false)
$gen1 = 0; for ($i = 0; $i -lt $reLog.Events.Count; $i++) { if ($reLog.Events[$i] -eq 'SCN_OPENED' -and $reLog.Details[$i] -match 'ScenarioGeneration=1 ') { $gen1++ } }
Row 'C-snapshot-observer' 'RED' ($gen1 -eq 1) ("outer SCN_OPENED keeps ScenarioGeneration=1 although the log callback re-entered (lines with generation 1: $gen1)")
# ---------------- E1 / E2 / E3 (Stage 0): facts about the CLR that the contract rests on. GUARD rows: they pass now and must keep passing. ----------------
# E1  Monitor.TryEnter(x, 0): no message dispatched on STA (the in-process lock may be tried without waiting)
# E2  Mutex.WaitOne(0):       STA dispatches a message at EVERY contended call (200 of 200) => it must never be used on the STA path
# E3  WaitForSingleObject(h, 0): no message dispatched on STA or MTA => the one admissible way to try the cross-DLL mutex without waiting (limited helper candidate)
$nTrials = 200
$sta = [Threading.ApartmentState]::STA; $mta = [Threading.ApartmentState]::MTA
$e = [UiPumpProbe.PumpExperiments]::Trials('Monitor.TryEnter0', $sta, $nTrials); Row 'E1-TryEnter0-STA' 'GUARD' (($e.Dispatched -eq 0) -and ($e.Value -match 'unexpectedTrue=0') -and ($e.ElapsedMs -le 50.0)) ("dispatched $($e.Dispatched)/$nTrials worst $('{0:F1}' -f $e.ElapsedMs) ms $($e.Value)")
$e = [UiPumpProbe.PumpExperiments]::Trials('Monitor.TryEnter0', $mta, $nTrials); Row 'E1-TryEnter0-MTA' 'GUARD' (($e.Dispatched -eq 0) -and ($e.Value -match 'unexpectedTrue=0')) ("dispatched $($e.Dispatched)/$nTrials $($e.Value)")
$e = [UiPumpProbe.PumpExperiments]::Trials('Mutex.WaitOne0', $sta, $nTrials); Row 'E2-MutexWaitOne0-STA-pumps' 'GUARD' (($e.Dispatched -eq $nTrials) -and ($e.Value -match 'unexpectedTrue=0')) ("dispatched $($e.Dispatched)/$nTrials => Mutex.WaitOne(0) is FORBIDDEN on the STA path $($e.Value)")
$e = [UiPumpProbe.PumpExperiments]::Trials('Mutex.WaitOne0', $mta, $nTrials); Row 'E2-MutexWaitOne0-MTA' 'GUARD' (($e.Dispatched -eq 0) -and ($e.Value -match 'unexpectedTrue=0')) ("dispatched $($e.Dispatched)/$nTrials $($e.Value)")
$e = [UiPumpProbe.PumpExperiments]::Trials('WaitForSingleObject0', $sta, $nTrials); Row 'E3-WaitForSingleObject0-STA' 'GUARD' (($e.Dispatched -eq 0) -and ($e.Value -match 'unexpectedTrue=0') -and ($e.ElapsedMs -le 50.0)) ("dispatched $($e.Dispatched)/$nTrials worst $('{0:F1}' -f $e.ElapsedMs) ms $($e.Value)")
$e = [UiPumpProbe.PumpExperiments]::Trials('WaitForSingleObject0', $mta, $nTrials); Row 'E3-WaitForSingleObject0-MTA' 'GUARD' (($e.Dispatched -eq 0) -and ($e.Value -match 'unexpectedTrue=0')) ("dispatched $($e.Dispatched)/$nTrials $($e.Value)")
# validity control of the probe itself: the incident's call (a contended Mutex.WaitOne(30)) MUST dispatch on STA and must not on MTA
$e = [UiPumpProbe.PumpExperiments]::Trials('Mutex.WaitOne30', $sta, 20); Row 'CONTROL-WaitOne30-STA-pumps' 'GUARD' ($e.Dispatched -ge 20) ("positive control: dispatched $($e.Dispatched)/20 (the probe can see the pump)")
$e = [UiPumpProbe.PumpExperiments]::Trials('Mutex.WaitOne30', $mta, 20); Row 'CONTROL-WaitOne30-MTA' 'GUARD' ($e.Dispatched -eq 0) ("negative control: dispatched $($e.Dispatched)/20 (MTA never dispatches)")
# ---------------- GUARD: contracts that must not change ----------------
# G-L3: an I/O failure line is dropped, never resent; the next written line reports droppedBefore
$pidCounter++
$pathL3 = Join-Path $testDir 'g-l3.log'
LogCfg $bLog $pathL3 $pidCounter
(WriteMethod $bLog).Invoke($null, @('B', 'L3_BEFORE', '')) | Out-Null
$lock = New-Object IO.FileStream($pathL3, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
try { 1..10 | ForEach-Object { (WriteMethod $bLog).Invoke($null, @('A', 'L3_WHILE_LOCKED', 'k=1')) | Out-Null } } finally { $lock.Dispose() }
(WriteMethod $bLog).Invoke($null, @('B', 'L3_AFTER', '')) | Out-Null
$l3 = ReadLog $pathL3
Row 'G-L3' 'GUARD' ((($l3 -join "`n") -match 'L3_AFTER.*droppedBefore=\d+') -and (($l3 -join "`n") -notmatch 'L3_WHILE_LOCKED')) 'I/O failure lines are not resent; the next line carries droppedBefore'
# G-L5: four MTA threads (both DLLs) x 100 lines: nothing lost, nothing interleaved
$pidCounter++
$pathL5 = Join-Path $testDir 'g-l5.log'
LogCfg $cLog $pathL5 $pidCounter; LogCfg $bLog $pathL5 $pidCounter
[UiPumpProbe.ProductCalls]::HammerMta((WriteMethod $cLog), (WriteMethod $bLog), 2, 100)
$l5 = @(ReadLog $pathL5 | Where-Object { $_ -match '^\d' })
$bad = @($l5 | Where-Object { $_ -notmatch ('^\d\d:\d\d:\d\d\.\d{3} q=\d+\.\d P=' + $pidCounter + ' S=(Caller|Bridge) T=B th=\d+ G5_WRITE k=\d+$') }).Count
Row 'G-L5' 'GUARD' (($l5.Count -eq 400) -and ($bad -eq 0)) ("MTA 4 threads x 100: lines=" + $l5.Count + " malformed=" + $bad)
# G-format: one line format
$pidCounter++
$pathFmt = Join-Path $testDir 'g-format.log'
LogCfg $bLog $pathFmt $pidCounter
(WriteMethod $bLog).Invoke($null, @('A', 'FMT_PROBE', 'k=1')) | Out-Null
$fmt = @(ReadLog $pathFmt)
Row 'G-format' 'GUARD' ((($fmt | Where-Object { $_ -like '# TS Scoring Phase C1 observation log*' }).Count -eq 1) -and (@($fmt | Where-Object { $_ -match '^\d\d:\d\d:\d\d\.\d{3} q=\d+\.\d P=\d+ S=Bridge T=A th=\d+ FMT_PROBE k=1$' }).Count -eq 1)) 'header once, line format unchanged'

# ---------------- prototype validation (Stage 0 only): scratch variants of the shared log source, never a product DLL ----------------
if ($ProtoScript) {
    . $ProtoScript
    Invoke-ProtoValidation -Root $Root -TestDir $testDir -Rows $rows -BudgetMs $BudgetMs
}

$summary = @('# Test-ObservationUiNonBlocking  ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), '# dist Bridge/Caller byte SHA-256 (first 8): ' + ((Get-FileHash (Join-Path $Root 'dist\TSScoringPlugin.BveEx.Bridge.Prototype.dll')).Hash.Substring(0, 8)) + ' / ' + ((Get-FileHash (Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')).Hash.Substring(0, 8))) + $rows
if ($ResultsFile) { $summary | Set-Content -LiteralPath $ResultsFile -Encoding UTF8 }
$redFail = @($rows | Where-Object { $_ -match '^RESULT \S+ RED FAIL' }).Count
$redPass = @($rows | Where-Object { $_ -match '^RESULT \S+ RED PASS' }).Count
$guardFail = @($rows | Where-Object { $_ -match '^RESULT \S+ GUARD FAIL' }).Count
$guardPass = @($rows | Where-Object { $_ -match '^RESULT \S+ GUARD PASS' }).Count
"SUMMARY RED fail=$redFail pass=$redPass ; GUARD fail=$guardFail pass=$guardPass"
