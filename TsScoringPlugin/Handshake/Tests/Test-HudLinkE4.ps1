# PHASE E4 - offline tests of the Session / Driving state publication of the Caller (Caller 0.11.0.0) and of the HUD link of the managed application.
# What is tested: AppStatePublisher.cs (the 64-byte block, written exactly as the contract says, read by the application's own Python reader in a 64-bit
# and a 32-bit Caller), AppProcessManager.PublishState / the Dispose withdrawal, the wiring in HandshakeSession (ScenarioReady and DrivingActive ->
# Session and Driving, per ScenarioGeneration), and the whole chain with the REAL main.py --managed: a stand-in for the BVE window (own process,
# own window title), the real Overlay, show / hide / resume on the SAME window handle, Dispose -> exit code 0.
# No BVE, no BveEX, no MessageBox. The processes started here are small stdlib-only children written to a private folder by this script, the stand-in
# window helper (tests\fake_bve_window.py) and - only when UDP 54321 is free and no main.py runs - the real application. The user's real launcher.json
# is never read (LauncherConfigLoader.TestPath). Every process is stopped through its Stop event / stdin, or as a last resort by the PID this test holds.
# Logs go to a private file under logs\e4-tests. This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$PythonExe = '',
    [string]$E3Commit = 'b9611dad47e2c95f8fa1c89a8bd0286896c75cea',
    [switch]$Probe32,
    [string]$Fixtures = ''
)

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

public class LogSink
{
    private readonly List<string> lines = new List<string>();
    public void Log(string evt, string detail) { lock (lines) { lines.Add(evt + " " + detail); } }
    public string[] Snapshot() { lock (lines) { return lines.ToArray(); } }
    public void Clear() { lock (lines) { lines.Clear(); } }
}

public class NoticeRecorder
{
    public int Count;
    public void Show(string text) { Interlocked.Increment(ref Count); }
}

public static class WinEnum
{
    private delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc p, IntPtr l);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr h);

    /// <summary>Handles of the top-level windows of process pid whose OWNER window is ownerHwnd (the HUD Overlay is owned by the BVE window).</summary>
    public static long[] OwnedBy(long ownerHwnd, uint pid)
    {
        List<long> found = new List<long>();
        EnumWindows(delegate (IntPtr h, IntPtr l)
        {
            uint p;
            GetWindowThreadProcessId(h, out p);
            if (p == pid && GetWindow(h, 4).ToInt64() == ownerHwnd) { found.Add(h.ToInt64()); }
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }

    public static bool Visible(long h) { return IsWindowVisible(new IntPtr(h)); }
    public static bool Exists(long h) { return IsWindow(new IntPtr(h)); }
}
'@

# No AssemblyResolve handler: nothing here loads Mackoy.IInputDevice (the input-device class is never instantiated), and a script-block handler recursed
# without end inside Get-CimInstance on this host.

$callerPath = Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll'
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($callerPath))
$NS = 'TSScoringPlugin.Handshake.'
$sessT = $callerAsm.GetType($NS + 'HandshakeSession')
$mgrT = $callerAsm.GetType($NS + 'AppProcessManager')
$optT = $callerAsm.GetType($NS + 'AppProcessOptions')
$ldrT = $callerAsm.GetType($NS + 'LauncherConfigLoader')
$namesT = $callerAsm.GetType($NS + 'AppObjectNames')
$pubT = $callerAsm.GetType($NS + 'AppStatePublisher')
$layoutT = $callerAsm.GetType($NS + 'AppStateLayout')
$ssT = $callerAsm.GetType($NS + 'ScenarioState')
$logT = $callerAsm.GetType($NS + 'ObservationLog')
$phaseT = $callerAsm.GetType($NS + 'CallerPhase')
$npi = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$nps = [Reflection.BindingFlags]'NonPublic,Public,Static'

$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }

function FindPython {
    if ($PythonExe -and (Test-Path $PythonExe)) { return (Resolve-Path $PythonExe).Path }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and ($c.Source -notmatch 'WindowsApps')) { return $c.Source }
    foreach ($cand in 'C:\Python314\python.exe', 'C:\Python313\python.exe', 'C:\Python312\python.exe') { if (Test-Path $cand) { return $cand } }
    return $null
}
[string]$py = FindPython
[string]$fixDir = if ($Fixtures) { $Fixtures } else { Join-Path $Root 'logs\e4-tests\fixtures' }
[string]$logDir = Join-Path $Root 'logs\e4-tests'
[string]$workDir = Join-Path $fixDir 'work'
[string]$cfgPath = Join-Path $fixDir 'launcher.json'
[string]$childScript = Join-Path $fixDir 'fake_state_child.py'
[string]$outFile = Join-Path $fixDir 'child-state.txt'
$repoRoot = ((& git -C $Root rev-parse --show-toplevel) -replace '/', '\')
$mainPy = Join-Path $repoRoot 'main.py'
$probePy = Join-Path $repoRoot 'tests\managed_state_probe.py'
$bveWinPy = Join-Path $repoRoot 'tests\fake_bve_window.py'

function WaitFor([scriptblock]$cond, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { if (& $cond) { return $true }; Start-Sleep -Milliseconds 20 }
    return [bool](& $cond)
}
function SetTestPath([string]$p) { $ldrT.GetProperty('TestPath', $nps).SetValue($null, $p) }
function PidAlive([int]$p) { return [bool](Get-Process -Id $p -ErrorAction SilentlyContinue) }
function EventLines($sink, [string]$evt) { return , @($sink.Snapshot() | Where-Object { $_ -like ($evt + ' *') -or $_ -eq $evt }) }
function Names($sink) { return , @($sink.Snapshot() | ForEach-Object { ($_ -split ' ', 2)[0] }) }
function Field([string]$line, [string]$name) { $m = [regex]::Match($line, '\b' + [regex]::Escape($name) + '=(\S+)'); if ($m.Success) { return $m.Groups[1].Value } else { return $null } }
$started = New-Object System.Collections.Generic.List[int]
function KillStrays { foreach ($p in $started) { if (PidAlive $p) { try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch { } } } }

# ---------------------------------------------------------------- fixtures: the stand-in application (follows the E2 contract and reads the E4 block)
New-Item -ItemType Directory -Force $logDir | Out-Null
if (-not $Probe32) {
    if (Test-Path $fixDir) { Remove-Item $fixDir -Recurse -Force }
    New-Item -ItemType Directory -Force $workDir | Out-Null
    $childText = @'
import ctypes, os, struct, sys, threading, time
threading.Thread(target=lambda: (time.sleep(60), os._exit(99)), daemon=True).start()   # orphan guard of the test
out = os.environ.get("TSS_E4_OUT")
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
mode = os.environ.get("TSS_E4_MODE", "ok")
f = open(out, "a") if out else None
def rec(tag, d):
    if f is None:
        return
    head, flags, gen, count = struct.unpack_from("<IIiI", d, 32)
    f.write("%s s=%d d=%d c=%d g=%d n=%d\n" % (tag, flags & 1, (flags >> 1) & 1, (flags >> 2) & 1, gen, count))
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
elif f is not None:
    f.write("NOSTATE\n"); f.flush()
ready = k.CreateEventW(None, 1, 0, base + "Ready")
k.SetEvent(ready)
last = None
while k.WaitForSingleObject(stop, 10) != 0:
    if view:
        d = snap()
        key = d[36:48]
        if key != last:
            last = key
            rec("CHG", d)
if view:
    rec("STOP", snap())
k.ResetEvent(ready)
sys.exit(0)
'@
    [IO.File]::WriteAllText($childScript, $childText, (New-Object Text.UTF8Encoding($false)))
}

# ---------------------------------------------------------------- helpers: config, manager, records
function ConfigJson([hashtable]$over = @{}) {
    $h = [ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $py; scriptPath = $childScript; workingDirectory = $workDir }
    foreach ($k in $over.Keys) { $h[$k] = $over[$k] }
    return ($h | ConvertTo-Json -Compress)
}
function WriteCfg([string]$text) { [IO.File]::WriteAllText($cfgPath, $text, (New-Object Text.UTF8Encoding($false))) }
function NewOpts([int]$ready = 8000, [int]$grace = 3000, [int]$killWait = 2000) {
    $o = [Activator]::CreateInstance($optT)
    $optT.GetField('ReadyTimeoutMs').SetValue($o, $ready)
    $optT.GetField('StopGraceMs').SetValue($o, $grace)
    $optT.GetField('KillWaitMs').SetValue($o, $killWait)
    return $o
}
function NewMgr([int]$fakePid, $opts) {
    $sink = New-Object LogSink
    $del = [Delegate]::CreateDelegate([Action[string, string]], $sink, 'Log')
    $m = [Activator]::CreateInstance($mgrT, @($fakePid, $del, $null, $opts))
    return [pscustomobject]@{ Mgr = $m; Sink = $sink; Pid = $fakePid }
}
function Mg($h, [string]$name) { return $mgrT.GetProperty($name).GetValue($h.Mgr) }
function Req($h, [int]$gen = 1, [int]$no = 1) { return [string]$mgrT.GetMethod('RequestStart').Invoke($h.Mgr, @($gen, $no)) }
function Down($h) { $mgrT.GetMethod('Shutdown').Invoke($h.Mgr, @()) | Out-Null }
function Pub($h, [bool]$session, [bool]$driving, [int]$gen) { $mgrT.GetMethod('PublishState').Invoke($h.Mgr, @($session, $driving, $gen)) | Out-Null }
function Track($h) { $p = [int](Mg $h 'AppPid'); if ($p -gt 0 -and -not $started.Contains($p)) { $started.Add($p) } }
function SetMode([string]$mode) { $env:TSS_E4_MODE = $mode; $env:TSS_E4_OUT = $outFile; if (Test-Path $outFile) { Remove-Item $outFile -Force } }
function Rec { if (Test-Path $outFile) { return , @(Get-Content $outFile) } else { return , @() } }
function RecLast { $r = Rec; if ($r.Count -gt 0) { return [string]$r[$r.Count - 1] } else { return '' } }
function StartChild($h, [int]$gen = 1) {
    SetTestPath $cfgPath
    WriteCfg (ConfigJson)
    [void](Req $h $gen 1)
    $ok = WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000
    Track $h
    return $ok
}

# ---------------------------------------------------------------- cross-language probe: the application's own Python reader
function StartProbe([int]$fakePid, [string]$inst) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $py
    $psi.Arguments = '"' + $probePy + '" ' + $fakePid + ' ' + $inst
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $repoRoot
    $p = [Diagnostics.Process]::Start($psi)
    $w = New-Object IO.StreamWriter($p.StandardInput.BaseStream, (New-Object Text.UTF8Encoding($false)))   # no BOM: the probe compares whole lines
    $open = $p.StandardOutput.ReadLine()
    return [pscustomobject]@{ P = $p; W = $w; Open = $open }
}
function ProbeRead($pr) { $pr.W.WriteLine('read'); $pr.W.Flush(); return $pr.P.StandardOutput.ReadLine() }
function StopProbe($pr) { try { $pr.W.WriteLine('quit'); $pr.W.Flush(); [void]$pr.P.WaitForExit(3000) } catch { }; if (-not $pr.P.HasExited) { try { $pr.P.Kill() } catch { } } }

# Writes a fixed sequence of states with the Caller's own publisher and returns what the Python reader saw after each step (used 64-bit and 32-bit).
function PublisherSequence([int]$fakePid, [string]$inst) {
    $name = $namesT.GetMethod('State').Invoke($null, @($fakePid, $inst))
    $pub = $pubT.GetMethod('Create').Invoke($null, @($name, $fakePid, $inst))
    $pr = StartProbe $fakePid $inst
    $seen = New-Object System.Collections.Generic.List[string]
    $seen.Add($pr.Open)
    $seen.Add((ProbeRead $pr))
    $steps = @(@($true, $false, 1), @($true, $true, 1), @($true, $true, 1), @($true, $false, 1), @($true, $true, 1), @($false, $true, 1), @($true, $true, 2), @($false, $false, 2))
    foreach ($s in $steps) { [void]$pubT.GetMethod('Write').Invoke($pub, @([bool]$s[0], [bool]$s[1], [int]$s[2])); $seen.Add((ProbeRead $pr)) }
    [void]$pubT.GetMethod('Close').Invoke($pub, @())
    $seen.Add((ProbeRead $pr))
    [void]$pubT.GetMethod('Write').Invoke($pub, @($true, $true, 9))
    $seen.Add((ProbeRead $pr))
    StopProbe $pr
    $pubT.GetMethod('Dispose').Invoke($pub, @()) | Out-Null
    return ($seen -join '|')
}

# one complete lifecycle with the stand-in application, summarised by what the application saw (used 64-bit and 32-bit)
function RunLifecycle([int]$fakePid) {
    SetMode 'ok'
    $h = NewMgr $fakePid (NewOpts)
    Pub $h $true $true 3
    $ok = StartChild $h 3
    [void](WaitFor { (Rec).Count -ge 1 } 5000)
    Pub $h $true $false 3
    [void](WaitFor { (RecLast) -match 'CHG s=1 d=0' } 5000)
    Pub $h $false $false 3
    [void](WaitFor { (RecLast) -match 'CHG s=0 d=0 c=0' } 5000)
    Pub $h $true $true 4
    [void](WaitFor { (RecLast) -match 'g=4' } 5000)
    Down $h
    # A change record that already says Closed may or may not be seen before the Stop record (the child polls every 10 ms; the Closed write and the Stop signal are microseconds apart): both are correct, so it is not part of the comparison. The STOP record itself must say Closed.
    $r = (Rec) | Where-Object { $_ -notmatch '^CHG s=0 d=0 c=1 ' } | ForEach-Object { ($_ -replace ' n=\d+', '') }
    $namesList = (Names $h.Sink) | Where-Object { $_ -in 'APP_STATE_OPEN', 'APP_STATE_PUBLISH', 'APP_STATE_CLOSED', 'APP_STOP_SIGNALLED', 'APP_PROCESS_STARTED' }
    return ('ready={0} exit={1} rec=[{2}] events={3}' -f $ok, (Mg $h 'ExitCode'), ($r -join ';'), ($namesList -join ','))
}

# ================================================================================================================ 32-bit probe
if ($Probe32) {
    SetTestPath $cfgPath
    WriteCfg (ConfigJson)
    $seq = PublisherSequence 960501 '0123456789abcdef0123456789abcdef'
    $life = RunLifecycle 960502
    KillStrays
    ('PROBE32 ptr={0} seq={1} life={2}' -f [IntPtr]::Size, $seq, $life)
    exit 0
}

if (-not $py) {
    Check 'Z00 a Python interpreter was found (set -PythonExe)' $false
    "TOTAL {0}  FAILED {1}" -f $results.Count, 1
    exit 1
}
"python for the children: " + (Split-Path $py -Leaf) + " (full path not printed)"
SetTestPath (Join-Path $fixDir 'no-such-launcher.json')

try {
# ================================================================================================================ P: the state block (publisher)
Write-Host '--- P: state block'
$instP = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
$pidP = 960400
$nameP = $namesT.GetMethod('State').Invoke($null, @($pidP, $instP))
Check 'P01 the object name is Local\TSScoringPlugin.v1.<BVE PID>.App.<INST>.State (the E2 family, session-local)' ($nameP -ceq ('Local\TSScoringPlugin.v1.' + $pidP + '.App.' + $instP + '.State'))
$pub = $pubT.GetMethod('Create').Invoke($null, @($nameP, $pidP, $instP))
$mmf = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($nameP, [IO.MemoryMappedFiles.MemoryMappedFileRights]::Read)
$view = $mmf.CreateViewAccessor(0, 64, [IO.MemoryMappedFiles.MemoryMappedFileAccess]::Read)
function Bytes { $b = New-Object byte[] 64; [void]$view.ReadArray(0, $b, 0, 64); return , $b }
function U32([byte[]]$b, [int]$o) { return [BitConverter]::ToUInt32($b, $o) }
function I32([byte[]]$b, [int]$o) { return [BitConverter]::ToInt32($b, $o) }
$b0 = Bytes
Check 'P02 a fresh block is complete and all OFF: magic "TSAS", version 1, size 64, the BVE PID, the first 16 instance digits, flags 0, generation 0, count 0, head = tail = 0, reserved zero' ((U32 $b0 0) -eq 0x53415354 -and ([Text.Encoding]::ASCII.GetString($b0, 0, 4) -ceq 'TSAS') -and (U32 $b0 4) -eq 1 -and (U32 $b0 8) -eq 64 -and (U32 $b0 12) -eq $pidP -and ([Text.Encoding]::ASCII.GetString($b0, 16, 16) -ceq $instP.Substring(0, 16)) -and (U32 $b0 32) -eq 0 -and (U32 $b0 36) -eq 0 -and (I32 $b0 40) -eq 0 -and (U32 $b0 44) -eq 0 -and (U32 $b0 60) -eq 0 -and (@($b0[48..59] | Where-Object { $_ -ne 0 }).Count -eq 0))
$w = $pubT.GetMethod('Write')
$r1 = $w.Invoke($pub, @($true, $false, 1))
$b1 = Bytes
Check 'P03 a first change is written: flags = Session, generation 1, change count 1, head = tail = 2 (even, equal)' ($r1.Written -and (U32 $b1 36) -eq 1 -and (I32 $b1 40) -eq 1 -and (U32 $b1 44) -eq 1 -and (U32 $b1 32) -eq 2 -and (U32 $b1 60) -eq 2)
$r2 = $w.Invoke($pub, @($true, $true, 1))
$b2 = Bytes
Check 'P04 Session + Driving: flags 3; the header (magic, version, size, pid, instance) is untouched by every write' ($r2.Written -and (U32 $b2 36) -eq 3 -and (U32 $b2 44) -eq 2 -and (U32 $b2 32) -eq 4 -and (U32 $b2 60) -eq 4 -and (@(0..31 | Where-Object { $b2[$_] -ne $b0[$_] }).Count -eq 0))
$r3 = $w.Invoke($pub, @($true, $true, 1))
$b3 = Bytes
Check 'P05 an identical state is NOT written (nothing changes in the block, the count stays)' ((-not $r3.Written) -and (U32 $b3 44) -eq 2 -and (U32 $b3 32) -eq 4 -and (@(0..63 | Where-Object { $b3[$_] -ne $b2[$_] }).Count -eq 0))
$r4 = $w.Invoke($pub, @($false, $true, 1))
$b4 = Bytes
Check 'P06 Driving is only ever ON together with Session: (Session OFF, Driving ON) is written as flags 0' ($r4.Written -and (U32 $b4 36) -eq 0 -and (I32 $b4 40) -eq 1)
$r5 = $w.Invoke($pub, @($true, $true, 2))
$b5 = Bytes
Check 'P07 a new ScenarioGeneration under the same levels is a change of its own (generation 2)' ($r5.Written -and (I32 $b5 40) -eq 2 -and (U32 $b5 36) -eq 3)
$cl = $pubT.GetMethod('Close').Invoke($pub, @())
$b6 = Bytes
Check 'P08 Close withdraws everything and sets Closed: flags = 4 (Session OFF, Driving OFF, Closed), the generation is kept, head = tail even' ($cl.Written -and (U32 $b6 36) -eq 4 -and (I32 $b6 40) -eq 2 -and (U32 $b6 32) -eq (U32 $b6 60) -and ((U32 $b6 32) % 2) -eq 0)
$cl2 = $pubT.GetMethod('Close').Invoke($pub, @())
$after = $w.Invoke($pub, @($true, $true, 3))
$b7 = Bytes
Check 'P09 after Close nothing is written any more (a second Close and a later Write change nothing)' ((-not $cl2.Written) -and (-not $after.Written) -and (@(0..63 | Where-Object { $b7[$_] -ne $b6[$_] }).Count -eq 0))
$dupFailed = $false
try { [void]$pubT.GetMethod('Create').Invoke($null, @($nameP, $pidP, $instP)) } catch { $dupFailed = $true }
Check 'P10 the same block name cannot be created twice (an instance id is never reused)' $dupFailed
$pubT.GetMethod('Dispose').Invoke($pub, @()) | Out-Null
$pub2 = $pubT.GetMethod('Create').Invoke($null, @(('Local\TSScoringPlugin.v1.960401.App.' + $instP + '.State'), 960401, $instP))
$pubT.GetField('head', $npi).SetValue($pub2, [uint32]4294967294)
[void]$pubT.GetMethod('Write').Invoke($pub2, @($true, $false, 1))
Check 'P11 the seqlock head wraps around the 32-bit range and stays even' (([uint32]$pubT.GetField('head', $npi).GetValue($pub2)) -eq 0)
$pubT.GetMethod('Dispose').Invoke($pub2, @()) | Out-Null
$view.Dispose(); $mmf.Dispose()

# --- contract constants: the Caller source (what was compiled) and the Python module say the same
$lay = @{}
foreach ($f in $layoutT.GetFields($nps)) { if ($f.IsLiteral) { $lay[$f.Name] = [uint64]$f.GetRawConstantValue() } }
$pyConst = & $py -c "import sys; sys.path.insert(0, r'$repoRoot'); import managed_state as m; print(m.STATE_SIZE, m.STATE_MAGIC, m.STATE_VERSION, m.INSTANCE_CHARS, m.OFF_MAGIC, m.OFF_VERSION, m.OFF_SIZE, m.OFF_PID, m.OFF_INSTANCE, m.OFF_HEAD, m.OFF_FLAGS, m.OFF_GENERATION, m.OFF_CHANGE_COUNT, m.OFF_TAIL, m.FLAG_SESSION, m.FLAG_DRIVING, m.FLAG_CLOSED)"
$cs = @($lay.Size, $lay.Magic, $lay.Version, $lay.InstanceChars, $lay.OffMagic, $lay.OffVersion, $lay.OffSize, $lay.OffPid, $lay.OffInstance, $lay.OffHead, $lay.OffFlags, $lay.OffGeneration, $lay.OffChangeCount, $lay.OffTail, $lay.FlagSession, $lay.FlagDriving, $lay.FlagClosed) -join ' '
Check ('P12 the compiled layout constants of the Caller DLL equal the constants of managed_state.py (' + $cs + ')') ($pyConst -ceq $cs)

# --- the application's own Python reader reads what the Caller wrote (cross-language)
$seq64 = PublisherSequence 960501 '0123456789abcdef0123456789abcdef'
$expectSeq = 'OPEN yes|S session=0 driving=0 closed=0 gen=0 changes=0|S session=1 driving=0 closed=0 gen=1 changes=1|S session=1 driving=1 closed=0 gen=1 changes=2|S session=1 driving=1 closed=0 gen=1 changes=2|S session=1 driving=0 closed=0 gen=1 changes=3|S session=1 driving=1 closed=0 gen=1 changes=4|S session=0 driving=0 closed=0 gen=1 changes=5|S session=1 driving=1 closed=0 gen=2 changes=6|S session=0 driving=0 closed=0 gen=2 changes=7|S session=0 driving=0 closed=1 gen=2 changes=8|S session=0 driving=0 closed=1 gen=2 changes=8'
Check ('P13 the Python reader (managed_state.StateReader, real mapping) sees every step the Caller published, including the unchanged step, Driving without Session, the generation change, Close and the ignored write after Close (' + $seq64.Length + ' chars)') ($seq64 -ceq $expectSeq)

# --- 32-bit Caller (BVE5 is a 32-bit process): the same bytes, the same reading
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
$script:probe32line = ''
if (Test-Path $ps32) {
    $out = & $ps32 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Root $Root -PythonExe $py -Probe32 -Fixtures $fixDir 2>&1 | Where-Object { $_ -match '^PROBE32' }
    $script:probe32line = (($out -join ''))
}

# ================================================================================================================ M: the manager publishes and withdraws
Write-Host '--- M: state publication by the process manager'
SetTestPath $cfgPath
WriteCfg (ConfigJson)

# no configuration: the state is only remembered
SetTestPath (Join-Path $fixDir 'no-such-launcher.json')
$h = NewMgr 960510 (NewOpts)
Pub $h $true $true 5
[void](Req $h 1 1)
[void](WaitFor { [string](Mg $h 'State') -eq 'None' -and -not (Mg $h 'WorkerAlive') } 5000)
Check 'M01 without a launcher.json the state is remembered (Session, Driving, generation), no block exists, no process was started' ((Mg $h 'LatestSession') -and (Mg $h 'LatestDriving') -and ([int](Mg $h 'LatestGeneration') -eq 5) -and (-not (Mg $h 'StateBlockCreated')) -and ([int](Mg $h 'ProcessStartCount') -eq 0) -and ((EventLines $h.Sink 'APP_STATE_OPEN').Count -eq 0))
Down $h
SetTestPath $cfgPath

# a state reported BEFORE the process exists is the first reading of the process
SetMode 'ok'
$h = NewMgr 960511 (NewOpts)
Pub $h $false $true 2
Pub $h $true $true 3
$ok = StartChild $h 3
[void](WaitFor { (Rec).Count -ge 1 } 5000)
$first = (Rec)[0]
$ev = Names $h.Sink
Check ('M02 a state reported before the launch is already in the block when the application starts: its FIRST reading is Session ON, Driving ON, generation 3 (' + $first + ')') ($ok -and ($first -match '^FIRST s=1 d=1 c=0 g=3 ') -and (Mg $h 'StateBlockCreated'))
Check 'M03 the block is created BEFORE Process.Start: APP_STATE_OPEN precedes APP_PROCESS_STARTED, once' (($ev.IndexOf('APP_STATE_OPEN') -ge 0) -and ($ev.IndexOf('APP_STATE_OPEN') -lt $ev.IndexOf('APP_PROCESS_STARTED')) -and ((EventLines $h.Sink 'APP_STATE_OPEN').Count -eq 1) -and ((EventLines $h.Sink 'APP_STATE_OPEN')[0] -match 'session=1 driving=1 ScenarioGeneration=3'))
$writes0 = [int](Mg $h 'StatePublishCount')
Check 'M04 only changes are logged: before any later change the log holds no APP_STATE_PUBLISH and the initial state was written once' (($writes0 -eq 1) -and ((EventLines $h.Sink 'APP_STATE_PUBLISH').Count -eq 0))
# identical reports: cost and effect
$sup0 = [long](Mg $h 'StateSuppressedCount')
$sw = [Diagnostics.Stopwatch]::StartNew()
for ($i = 0; $i -lt 20000; $i++) { Pub $h $true $true 3 }
$identMs = $sw.ElapsedMilliseconds
Check ('M05 20000 identical reports are suppressed: no write, no log line, the counter grows by 20000 (' + $identMs + ' ms through reflection)') (([int](Mg $h 'StatePublishCount') -eq $writes0) -and ([long](Mg $h 'StateSuppressedCount') -eq ($sup0 + 20000)) -and ((EventLines $h.Sink 'APP_STATE_PUBLISH').Count -eq 0))
# changes reach the running application
Pub $h $true $false 3
$a = WaitFor { (RecLast) -match '^CHG s=1 d=0 c=0 g=3 ' } 5000
Pub $h $false $false 3
$b = WaitFor { (RecLast) -match '^CHG s=0 d=0 c=0 g=3 ' } 5000
Pub $h $true $true 4
$c = WaitFor { (RecLast) -match '^CHG s=1 d=1 c=0 g=4 ' } 5000
Check 'M06 Driving OFF, Session OFF and a reload (generation 4) reach the running application, each as its own state; the process is untouched (still Ready, one Process.Start, no Stop)' ($a -and $b -and $c -and ([string](Mg $h 'State') -eq 'Ready') -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ([int](Mg $h 'StopSignalCount') -eq 0) -and ((EventLines $h.Sink 'APP_STATE_PUBLISH').Count -eq 3))
Pub $h $false $true 4
Check 'M07 (Session OFF, Driving ON) is published as Driving OFF (Driving never exists without Session)' ((WaitFor { (RecLast) -match '^CHG s=0 d=0 c=0 g=4 ' } 5000) -and -not (Mg $h 'LatestDriving'))
Pub $h $true $true 4
[void](WaitFor { (RecLast) -match '^CHG s=1 d=1 c=0 g=4 ' } 5000)
# Dispose: withdrawn and Closed BEFORE Stop
$cp = [int](Mg $h 'AppPid')
$sw.Restart()
Down $h
$endMs = $sw.ElapsedMilliseconds
$evn = Names $h.Sink
$stopRec = (Rec | Where-Object { $_ -like 'STOP *' })
$closedLine = (EventLines $h.Sink 'APP_STATE_CLOSED')
Check ('M08 Dispose withdraws Session / Driving and sets Closed BEFORE the Stop event: APP_STATE_CLOSED precedes APP_STOP_SIGNALLED, and the application read "Session OFF, Driving OFF, Closed" at the moment Stop arrived (' + $stopRec + ')') (($evn.IndexOf('APP_STATE_CLOSED') -ge 0) -and ($evn.IndexOf('APP_STATE_CLOSED') -lt $evn.IndexOf('APP_STOP_SIGNALLED')) -and ($stopRec -match '^STOP s=0 d=0 c=1 g=4 ') -and ($closedLine.Count -eq 1) -and ($closedLine[0] -match 'closed=yes'))
Check ('M09 after Dispose: the application left with exit code 0 in ' + $endMs + ' ms, no Kill, one Stop, the state block is gone from the system, the process is gone') (([int](Mg $h 'ExitCode') -eq 0) -and (-not (Mg $h 'Killed')) -and ([int](Mg $h 'StopSignalCount') -eq 1) -and (-not (PidAlive $cp)) -and (WaitFor { try { $x = [IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($namesT.GetMethod('State').Invoke($null, @($h.Pid, (Mg $h 'Instance')))); $x.Dispose(); $false } catch { $true } } 3000))
$wr = [int](Mg $h 'StatePublishCount')
Pub $h $true $true 9
Check 'M10 a report after Dispose does nothing (no write, no exception)' ([int](Mg $h 'StatePublishCount') -eq $wr)

# the application ends by itself (crash after Ready): later reports are still safe
SetMode 'ok'
$h = NewMgr 960512 (NewOpts)
Pub $h $true $true 1
[void](StartChild $h 1)
$cp = [int](Mg $h 'AppPid')
Stop-Process -Id $cp -Force
[void](WaitFor { [string](Mg $h 'State') -ne 'Ready' } 6000)
$threw = $false
try { Pub $h $true $false 1; Pub $h $false $false 1 } catch { $threw = $true }
Check 'M11 the application disappeared on its own: the block is released with it, later reports are only remembered (no exception, no second process)' ((-not $threw) -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and (-not (Mg $h 'LatestSession')))
Down $h

# ================================================================================================================ H: HandshakeSession wiring
Write-Host '--- H: session wiring (ScenarioReady / DrivingActive -> Session / Driving)'
function SetLog([string]$file, [int]$fakePid) {
    $logT.GetMethod('ResetForTests', $nps).Invoke($null, @()) | Out-Null
    $p = Join-Path $logDir $file
    if (Test-Path $p) { Remove-Item $p -Force }
    $logT.GetProperty('TestPath', $nps).SetValue($null, $p)
    $logT.GetProperty('TestPid', $nps).SetValue($null, $fakePid)
    $logT.GetProperty('TestMaxBytes', $nps).SetValue($null, 0)
    return $p
}
function Lines([string]$p) { if (Test-Path $p) { return @(Get-Content $p -Encoding UTF8) } else { return @() } }
function ELines([string]$p, [string]$evt) { return , @(Lines $p | Where-Object { $_ -match (' ' + [regex]::Escape($evt) + ' ') }) }
function NewBridgeObjs([int]$fakePid) {
    $ev = @{}
    foreach ($k in 'BridgeAvailable', 'Ready') { $ev[$k] = New-Object Threading.EventWaitHandle($true, [Threading.EventResetMode]::ManualReset, ('Local\TSScoringPlugin.v1.' + $fakePid + '.' + $k)) }
    $ev['ScenarioReady'] = New-Object Threading.EventWaitHandle($false, [Threading.EventResetMode]::ManualReset, ('Local\TSScoringPlugin.v1.' + $fakePid + '.ScenarioReady'))
    $mmf = [IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew(('Local\TSScoringPlugin.v1.' + $fakePid + '.ScenarioState'), 64)
    $view = $mmf.CreateViewAccessor(0, 64)
    return [pscustomobject]@{ Pid = $fakePid; Ev = $ev; Mmf = $mmf; View = $view }
}
function SetSR($b, [int]$gen, [bool]$ready) {
    $wr2 = $ssT.GetMethod('Write')
    if ($ready) { $wr2.Invoke($null, @($b.View, $b.Pid, $gen, $true)) | Out-Null; $b.Ev['ScenarioReady'].Set() | Out-Null }
    else { $b.Ev['ScenarioReady'].Reset() | Out-Null; $wr2.Invoke($null, @($b.View, $b.Pid, $gen, $false)) | Out-Null }
}
function DisposeBridgeObjs($b) {
    foreach ($k in @($b.Ev.Keys)) { try { $b.Ev[$k].Dispose() } catch { } }
    try { $b.View.Dispose() } catch { }
    try { $b.Mmf.Dispose() } catch { }
}
$ctor4 = $sessT.GetConstructor($npi, $null, [Type[]]@([int], [Action[string]], [Func[bool]], $mgrT), $null)
$stepM = $sessT.GetMethod('Step', $npi)
$cycle = 500
function NewSession([int]$fakePid, $mgr) {
    $rec2 = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec2, 'Show')
    $s = $ctor4.Invoke(@($fakePid, $del, $null, $mgr))
    $script:cycle++
    $now = [long][Diagnostics.Stopwatch]::GetTimestamp()
    $sessT.GetField('started', $npi).SetValue($s, $true)
    $sessT.GetField('phase', $npi).SetValue($s, [Enum]::Parse($phaseT, 'WaitingForBridge'))
    $sessT.GetField('enabledQpc', $npi).SetValue($s, $now)
    $sessT.GetField('absenceStartQpc', $npi).SetValue($s, $now)
    $sessT.GetField('cycleNo', $npi).SetValue($s, $script:cycle)
    return $s
}
function Tick($s) { $sessT.GetMethod('NotifyTick').Invoke($s, @()) | Out-Null }
function Step($s) { $stepM.Invoke($s, @()) | Out-Null }
function End($s) { try { $sessT.GetMethod('End').Invoke($s, @()) | Out-Null } catch { } }
function MakeStale($s, [double]$ms) { $past = [long]([Diagnostics.Stopwatch]::GetTimestamp() - [long]($ms * [Diagnostics.Stopwatch]::Frequency / 1000.0)); $sessT.GetField('lastTickQpc', $npi).SetValue($s, $past) }
function Latest($m) { return ('{0}/{1}/{2}' -f ([int](Mg $m 'LatestSession')), ([int](Mg $m 'LatestDriving')), ([int](Mg $m 'LatestGeneration'))) }

SetMode 'ok'
$fp = 960520
$log = SetLog 'h1.log' $fp
$b = NewBridgeObjs $fp
$m = NewMgr $fp (NewOpts)
$s = NewSession $fp $m.Mgr
for ($i = 0; $i -lt 20; $i++) { Tick $s; Step $s }
Check 'H01 before any scenario: Session OFF, Driving OFF, generation 0, nothing is written, no process' ((Latest $m) -ceq '0/0/0' -and ([int](Mg $m 'ProcessStartCount') -eq 0) -and -not (Mg $m 'StateBlockCreated'))
SetSR $b 1 $true; Step $s
Check 'H02 ScenarioReady published: Session ON at once (generation 1); Driving is still OFF until a Tick arrives AFTER the publication (the D1 rule)' ((Latest $m) -ceq '1/0/1')
Step $s; Tick $s; Step $s
$rdy = WaitFor { [string](Mg $m 'State') -eq 'Ready' } 15000
Track $m
[void](WaitFor { (Rec).Count -ge 1 } 5000)
Check ('H03 the first DrivingActive ON: Driving ON, the process starts, and its FIRST reading is already Session ON / Driving ON / generation 1 (' + (Rec)[0] + ')') ($rdy -and ((Latest $m) -ceq '1/1/1') -and ((Rec)[0] -match '^FIRST s=1 d=1 c=0 g=1 '))
for ($i = 0; $i -lt 60; $i++) { Tick $s; Step $s }
Check 'H04 Pause-like Ticks change nothing: no write, no new log line of the state' (([int](Mg $m 'StatePublishCount') -eq 1) -and ((EventLines $m.Sink 'APP_STATE_PUBLISH').Count -eq 0))
MakeStale $s 2500; Step $s
$softOff = WaitFor { (RecLast) -match '^CHG s=1 d=0 c=0 g=1 ' } 5000
Check 'H05 soft OFF (Tick stale, ScenarioReady still published): Session stays ON, Driving OFF, the generation is kept (the Legacy selection-screen pattern)' ($softOff -and ((Latest $m) -ceq '1/0/1'))
Tick $s; Step $s
$softOn = WaitFor { (RecLast) -match '^CHG s=1 d=1 c=0 g=1 ' } 5000
Check 'H06 Tick resumes: Driving ON again in the SAME generation; the process is neither restarted nor stopped' ($softOn -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ([int](Mg $m 'StopSignalCount') -eq 0))
MakeStale $s 2500; Step $s; Tick $s; Step $s; MakeStale $s 2500; Step $s; Tick $s; Step $s
SetSR $b 1 $false; Step $s
$hard = WaitFor { (RecLast) -match '^CHG s=0 d=0 c=0 g=1 ' } 5000
Check 'H07 ScenarioReady withdrawn (scenario closed): Session OFF and Driving OFF together, in ONE state change; generation kept; the process lives' ($hard -and ((Latest $m) -ceq '0/0/1') -and ([string](Mg $m 'State') -eq 'Ready'))
Tick $s; Step $s
SetSR $b 2 $true; Step $s; Step $s; Tick $s; Step $s
$reload = WaitFor { (RecLast) -match '^CHG s=1 d=1 c=0 g=2 ' } 5000
Check 'H08 reload: generation 2, Session ON, Driving ON; still the same process (one Process.Start, no Stop)' ($reload -and ((Latest $m) -ceq '1/1/2') -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ([int](Mg $m 'StopSignalCount') -eq 0))
SetSR $b 3 $true; Step $s; Step $s
$genOnly = WaitFor { (RecLast) -match '^CHG s=1 d=0 c=0 g=3 ' } 5000
Tick $s; Step $s
$genBack = WaitFor { (RecLast) -match '^CHG s=1 d=1 c=0 g=3 ' } 5000
Check 'H09 a new generation under a ScenarioReady that was never withdrawn: published with the generation, Driving re-arms (OFF, then ON after a fresh Tick)' ($genOnly -and $genBack -and ((Latest $m) -ceq '1/1/3'))
$writesBefore = [int](Mg $m 'StatePublishCount')
$cp = [int](Mg $m 'AppPid')
End $s
End $s
$stopRec = (Rec | Where-Object { $_ -like 'STOP *' })
Check ('H10 Dispose of the session: Session OFF / Driving OFF / Closed are visible to the application BEFORE Stop (' + $stopRec + '), one Stop, exit code 0, nothing left') (($stopRec -match '^STOP s=0 d=0 c=1 g=3 ') -and ([int](Mg $m 'StopSignalCount') -eq 1) -and ([int](Mg $m 'ExitCode') -eq 0) -and (-not (PidAlive $cp)) -and ((EventLines $m.Sink 'APP_STATE_CLOSED').Count -eq 1))
$pubLines = EventLines $m.Sink 'APP_STATE_PUBLISH'
Check ('H11 the whole run produced one APP_STATE_PUBLISH line per real change (' + $pubLines.Count + ' lines) and no line for an unchanged poll; the lines carry the instance and numbers only') (($pubLines.Count -eq ([int](Mg $m 'StatePublishCount') - 2)) -and (@($pubLines | Where-Object { $_ -notmatch '^APP_STATE_PUBLISH instance=[0-9a-f]{32} session=[01] driving=[01] ScenarioGeneration=\d+ changeNo=\d+$' }).Count -eq 0))
DisposeBridgeObjs $b

# a session without a process manager (every offline-test constructor) publishes nothing
$fp = 960521
$log = SetLog 'h2.log' $fp
$b = NewBridgeObjs $fp
$rec3 = New-Object NoticeRecorder
$s0 = $sessT.GetConstructor($npi, $null, [Type[]]@([int], [Action[string]]), $null).Invoke(@($fp, [Delegate]::CreateDelegate([Action[string]], $rec3, 'Show')))
$now = [long][Diagnostics.Stopwatch]::GetTimestamp()
$sessT.GetField('started', $npi).SetValue($s0, $true); $sessT.GetField('phase', $npi).SetValue($s0, [Enum]::Parse($phaseT, 'WaitingForBridge')); $sessT.GetField('enabledQpc', $npi).SetValue($s0, $now); $sessT.GetField('absenceStartQpc', $npi).SetValue($s0, $now)
for ($i = 0; $i -lt 10; $i++) { Tick $s0; Step $s0 }
SetSR $b 1 $true; Step $s0; Step $s0; Tick $s0; Step $s0
End $s0
Check 'H12 a session without a process manager (the offline-test constructors) publishes no state and logs no APP_STATE line' (($sessT.GetProperty('AppProcess', $npi).GetValue($s0) -eq $null) -and (@(Lines $log | Where-Object { $_ -match ' APP_STATE_' }).Count -eq 0))
DisposeBridgeObjs $b

# Current and Legacy look the same to the application: the Caller reads only the named objects both Bridges publish
$hsSrcRaw = [IO.File]::ReadAllText((Join-Path $Root 'Caller\src\HandshakeSession.cs'))
Check 'H13 the publication code knows no host: HandshakeSession.cs names neither "Legacy" nor "AtsEx" in any code line (the same Session / Driving contract for BVE6 Current, BVE5 Current and BVE5 Legacy)' (@(($hsSrcRaw -split "`n") | Where-Object { $_ -notmatch '^\s*//' -and $_ -match 'AtsEx|AtsEX|Legacy' }).Count -eq 0)

# ================================================================================================================ B: 32-bit
Write-Host '--- B: 32-bit process (BVE5 is a 32-bit process)'
$life64 = RunLifecycle 960530
KillStrays
$sum64 = ('PROBE32 ptr=4 seq={0} life={1}' -f $seq64, ($life64 -replace '960530', '960530'))
if ($script:probe32line) {
    $norm32 = $script:probe32line -replace 'ptr=\d+', 'ptr=4'
    Check ('B01 a 32-bit Caller writes the state block with the same bytes: the Python reader sees the same sequence as with the 64-bit Caller (' + ($norm32.Length) + ' chars)') (($script:probe32line -match 'ptr=4') -and ($norm32 -ceq $sum64))
    $m32 = [regex]::Match($script:probe32line, 'life=(.*)$').Groups[1].Value
    Check ('B02 a 32-bit Caller publishes, withdraws and closes through the manager exactly like the 64-bit one (first reading, changes, Closed before Stop, exit 0): ' + $m32) (($m32 -ceq $life64) -and ($m32 -match 'ready=True exit=0') -and ($m32 -match 'STOP s=0 d=0 c=1'))
}
else {
    Skip 'B01-B02 32-bit PowerShell not available'
}

# ================================================================================================================ I: the whole chain with the real main.py
Write-Host '--- I: Bridge objects -> session -> manager -> real main.py --managed -> HUD window'
$qtOk = $false
try { $qtOk = ((& $py -c "import PyQt6.QtWidgets, win32gui, win32process; print('ok')") -eq 'ok') } catch { $qtOk = $false }
$udpBusy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
$mainRunning = $false
try { $mainRunning = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop | Where-Object { $_.CommandLine -match 'main\.py' }).Count -gt 0 } catch { $mainRunning = $true }
if ($qtOk -and (-not $udpBusy) -and (-not $mainRunning) -and (Test-Path $mainPy) -and (Test-Path $bveWinPy)) {
    # the stand-in for the BVE window: its own process, a visible top-level window titled "BVE Trainsim ..."
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $py
    $psi.Arguments = '"' + $bveWinPy + '" 150'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $repoRoot
    $bveProc = [Diagnostics.Process]::Start($psi)
    $started.Add($bveProc.Id)
    $readyLine = $bveProc.StandardOutput.ReadLine()
    $bveHwnd = [long]([regex]::Match($readyLine, 'hwnd=(\d+)').Groups[1].Value)
    $bvePid = [int]([regex]::Match($readyLine, 'pid=(\d+)').Groups[1].Value)
    SetMode 'ok'
    $env:TSS_E4_OUT = $null
    SetTestPath $cfgPath
    WriteCfg (ConfigJson @{ scriptPath = $mainPy; workingDirectory = $repoRoot })
    $log = SetLog 'i1.log' $bvePid
    $b = NewBridgeObjs $bvePid
    $m = NewMgr $bvePid (NewOpts 25000 6000 3000)
    $s = NewSession $bvePid $m.Mgr
    for ($i = 0; $i -lt 20; $i++) { Tick $s; Step $s }
    SetSR $b 1 $true; Step $s; Step $s; Tick $s; Step $s
    $rdy = WaitFor { [string](Mg $m 'State') -eq 'Ready' } 40000
    Track $m
    $app = [int](Mg $m 'AppPid')
    # Phase L3: the HUD is only shown once real telemetry of the generation has arrived, so this chain now feeds a minimal valid telemetry line (the core keys only) to UDP 54321
    # whenever it looks at the window; a new scenario instance (new SCENARIO_ID) goes with every new generation.
    $telUdp = New-Object Net.Sockets.UdpClient
    $script:telSid = 1000
    function SendTel { $tb = [Text.Encoding]::UTF8.GetBytes(("SCENARIO_ID:" + $script:telSid + ",SPEED:0,TIME:36000000,LOCATION:0")); [void]$telUdp.Send($tb, $tb.Length, '127.0.0.1', 54321) }
    function Overlay { $w = [WinEnum]::OwnedBy($bveHwnd, [uint32]$app); return , $w }
    function OverlayVisible { SendTel; $w = Overlay; return ($w.Count -ge 1 -and [WinEnum]::Visible($w[0])) }
    $vis1 = WaitFor { OverlayVisible } 8000
    $ov = Overlay
    $h1 = if ($ov.Count -ge 1) { $ov[0] } else { 0 }
    Check ('I01 the REAL main.py --managed is started by the manager for a stand-in BVE process, reports AppReady, and - with Session ON and Driving ON - its Overlay window appears, OWNED by that BVE window (found by PID), exactly one Overlay window (' + $ov.Count + ')') ($rdy -and $vis1 -and ($ov.Count -eq 1) -and ($h1 -ne 0))
    Start-Sleep -Milliseconds 400
    $stillOne = ((Overlay).Count -eq 1) -and (OverlayVisible)
    Check 'I02 the HUD stays visible while the state is unchanged (no flicker: still one Overlay window, same handle)' ($stillOne -and ((Overlay)[0] -eq $h1))
    MakeStale $s 2500; Step $s
    $hid = WaitFor { -not (OverlayVisible) } 6000
    Check 'I03 soft OFF (Driving OFF, Session ON): the HUD is hidden but its window is NOT destroyed (same handle still exists); the application process keeps running' ($hid -and [WinEnum]::Exists($h1) -and (PidAlive $app) -and ([int](Mg $m 'StopSignalCount') -eq 0))
    Tick $s; Step $s
    $shown2 = WaitFor { OverlayVisible } 6000
    Check 'I04 Driving ON again: the SAME Overlay window handle is shown again (nothing re-created), still one Overlay window' ($shown2 -and ((Overlay).Count -eq 1) -and ((Overlay)[0] -eq $h1))
    SetSR $b 1 $false; Step $s
    $hid2 = WaitFor { -not (OverlayVisible) } 6000
    Check 'I05 ScenarioReady withdrawn (Session OFF): the HUD is hidden, the window and the process stay, no Stop was sent' ($hid2 -and [WinEnum]::Exists($h1) -and (PidAlive $app) -and ([int](Mg $m 'StopSignalCount') -eq 0) -and ([string](Mg $m 'State') -eq 'Ready'))
    $script:telSid++
    SetSR $b 2 $true; Step $s; Step $s; Tick $s; Step $s
    $shown3 = WaitFor { OverlayVisible } 6000
    Check 'I06 reload (generation 2): the HUD is shown again by the SAME process on the SAME window handle; Process.Start was called once in total' ($shown3 -and ((Overlay).Count -eq 1) -and ((Overlay)[0] -eq $h1) -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ((Mg $m 'AppPid') -eq $app))
    for ($i = 0; $i -lt 3; $i++) { MakeStale $s 2500; Step $s; [void](WaitFor { -not (OverlayVisible) } 4000); Tick $s; Step $s; [void](WaitFor { OverlayVisible } 4000) }
    Check 'I07 three more soft OFF / ON rounds (the Legacy pattern): same process, same window handle, still one Overlay window, HUD visible at the end' ((OverlayVisible) -and ((Overlay).Count -eq 1) -and ((Overlay)[0] -eq $h1) -and ([int](Mg $m 'ProcessStartCount') -eq 1))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    End $s
    $endMs = $sw.ElapsedMilliseconds
    $el = EventLines $m.Sink 'APP_STDERR'
    $stderrText = ($el -join "`n")
    Check ('I08 Dispose: the state is withdrawn, the HUD window is gone, the application leaves with exit code 0 in ' + $endMs + ' ms, no Kill, no residual process') (([int](Mg $m 'ExitCode') -eq 0) -and (-not (Mg $m 'Killed')) -and (-not (PidAlive $app)) -and (-not [WinEnum]::Exists($h1)) -and ((EventLines $m.Sink 'APP_STATE_CLOSED').Count -eq 1) -and ((Names $m.Sink).IndexOf('APP_STATE_CLOSED') -lt (Names $m.Sink).IndexOf('APP_STOP_SIGNALLED')))
    $shows = ([regex]::Matches($stderrText, 'event=hud-show')).Count
    $hides = ([regex]::Matches($stderrText, 'event=hud-hide')).Count
    Check ('I09 the application reported the HUD changes on stderr (state-change lines only, no path): hud-show=' + $shows + ' hud-hide=' + $hides + ' update-start>=3, one hud-summary, one exit line, lines=' + $el.Count + ' (<=200, none dropped)') (($shows -ge 5) -and ($hides -ge 5) -and ([regex]::Matches($stderrText, 'event=hud-update-start')).Count -ge 3 -and ([regex]::Matches($stderrText, 'event=hud-summary')).Count -eq 1 -and ([regex]::Matches($stderrText, 'event=exit ')).Count -eq 1 -and ($el.Count -le 200) -and ($stderrText -notmatch '[A-Za-z]:\\') -and ((EventLines $m.Sink 'APP_STREAMS')[0] -match 'stderrDropped=0'))
    $udpAfter = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
    Check 'I10 after Dispose UDP 54321 is free again and the stand-in BVE window is untouched (still alive)' ((-not $udpAfter) -and (PidAlive $bvePid))
    try { $telUdp.Close() } catch { }
    DisposeBridgeObjs $b
    try { $bveProc.StandardInput.Close() } catch { }
    [void]$bveProc.WaitForExit(5000)
    if (-not $bveProc.HasExited) { try { $bveProc.Kill() } catch { } }
}
else {
    Skip ('I01-I10 real main.py chain: not run (PyQt6/pywin32=' + $qtOk + ', UDP 54321 busy=' + $udpBusy + ', a main.py process present=' + $mainRunning + ')')
}
}
finally {
    KillStrays
    SetTestPath $null
    $env:TSS_E4_OUT = $null
    $env:TSS_E4_MODE = $null
}

# ================================================================================================================ S: static
Write-Host '--- S: static checks'
function RunGit([string[]]$gitArgs) {
    $psi2 = New-Object Diagnostics.ProcessStartInfo
    $psi2.FileName = 'git'
    $psi2.WorkingDirectory = $Root
    $psi2.UseShellExecute = $false
    $psi2.RedirectStandardOutput = $true
    $psi2.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi2.Arguments = (($gitArgs | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $pr = [Diagnostics.Process]::Start($psi2)
    $o2 = $pr.StandardOutput.ReadToEnd()
    $pr.WaitForExit()
    if ($pr.ExitCode -ne 0) { throw ('git failed: ' + ($gitArgs -join ' ')) }
    return $o2
}
$prefix = (RunGit @('rev-parse', '--show-prefix')).Trim()
$top = (RunGit @('rev-parse', '--show-toplevel')).Trim()
function Src([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $Root $rel))) -replace "`r`n", "`n") }
function NoComments([string]$s) { return [regex]::Replace($s, '//[^\n]*', '') }
$mgrCode = NoComments (Src 'Caller\src\AppProcessManager.cs')
$pubCode = NoComments (Src 'Caller\src\AppStatePublisher.cs')
$hsCode = NoComments (Src 'Caller\src\HandshakeSession.cs')
Check 'S01 the publisher is memory only: no file, no event, no process, no thread, no wait, no log in AppStatePublisher.cs' (($pubCode -replace 'MemoryMappedFile','MMF') -notmatch 'System\.IO\.File|\bFile\.|FileStream|Directory|EventWaitHandle|Mutex|\bProcess\b|ProcessStartInfo|Thread\.Sleep|new Thread|WaitOne|Log\(|ObservationLog|DllImport|Registry')
$pubBody = [regex]::Match($mgrCode, 'public void PublishState[\s\S]*?\n        \}\n').Value
Check 'S02 PublishState (monitor thread) holds a lock and a compare and one memory write: no file, process, wait, sleep, join and no kernel object creation; it logs only after the lock is released and only for a real write' (($pubBody.Length -gt 100) -and ($pubBody -notmatch 'File|Process\.|WaitOne|Sleep|Join|new EventWaitHandle|MemoryMappedFile|CreateNew') -and ($pubBody -match 'if \(w\.Written\)'))
Check 'S03 the state is published from the monitor step (after DrivingActive, BEFORE the controller) and once from End(); NotifyTick, the device Tick / Dispose / Load name no state, publisher or manager' ((([regex]::Matches($hsCode, 'PublishAppStateLocked\(\)')).Count -eq 3) -and (([regex]::Match($hsCode, 'private void Step\(\)[\s\S]*?\n        \}\n').Value) -match 'EvaluateDrivingLocked\(now\);\s+PublishAppStateLocked\(\);\s+ObserveAppControllerLocked\(\);') -and (([regex]::Match($hsCode, 'public void NotifyTick\(\)[\s\S]*?\n        \}\n').Value) -notmatch 'PublishState|appProcess|State') -and ((NoComments (Src 'Caller\src\TsScoringCallerInputDevice.cs')) -notmatch 'PublishState|StatePublisher|AppProcess'))
Check 'S04 the publication never starts or stops anything: PublishState / WithdrawState / CreateStateBlock contain no RequestStart, no process action; the Stop event is still set only in SignalStop (Dispose, Ready-timeout clean-up)' ((([regex]::Match($mgrCode, 'public void PublishState[\s\S]*?\n        \}\n').Value + [regex]::Match($mgrCode, 'private void WithdrawState[\s\S]*?\n        \}\n').Value) -notmatch 'RequestStart|SignalStop|stopEvent|Kill|Process\.Start') -and (([regex]::Matches($mgrCode, 'stopEvent\.Set\(\)')).Count -eq 1) -and (([regex]::Matches($mgrCode, 'SignalStop\("')).Count -eq 2) -and (([regex]::Matches($mgrCode, 'process\.Start\(\)')).Count -eq 1))
Check 'S05 the block is created before Process.Start and withdrawn before the Stop event is set' (($mgrCode.IndexOf('CreateStateBlock(inst)') -lt $mgrCode.IndexOf('process.Start()')) -and ($mgrCode.IndexOf('WithdrawState();') -ge 0) -and ($mgrCode.IndexOf('WithdrawState();') -lt $mgrCode.IndexOf('SignalStop("caller-dispose");')))
Check 'S06 the shared log grew by state CHANGES only: the new APP_STATE_* events are APP_STATE_OPEN, APP_STATE_PUBLISH (only inside "if (w.Written)"), APP_STATE_CLOSED, APP_STATE_CREATE_FAILED' ((@([regex]::Matches($mgrCode, 'Log\("(APP_STATE_[A-Z_]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique) -join ',') -ceq 'APP_STATE_CLOSED,APP_STATE_CREATE_FAILED,APP_STATE_OPEN,APP_STATE_PUBLISH')
$refNames = (($callerAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object) -join ',')
$vocab = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { (NoComments (Src ('Caller\src\' + $_.Name))) -match 'SessionEvent|DrivingEvent|\.Session"|\.Driving"|UdpClient|Socket|SetWindowsHookEx|RegisterHotKey|Registry|Backoff|BackOff|Respawn|CreateJobObject|Kickstart|Overlay|\bHUD\b' })
Check 'S07 no Session / Driving named event and no new reference: the DLL still references only mscorlib, System, System.Core, System.Windows.Forms, Mackoy.IInputDevice; vocabulary check on all Caller sources (no HUD, Overlay, hook, UDP, registry, job object, restart)' (($refNames -eq 'Mackoy.IInputDevice,mscorlib,System,System.Core,System.Windows.Forms') -and ($vocab.Count -eq 0))
$vi = (Get-Item $callerPath).VersionInfo
Check 'S08 version 0.11.0.0 (file and assembly), provider Coruge-to, product TS Scoring, description names Phase E4' (($vi.FileVersion -eq '0.11.0.0') -and ($callerAsm.GetName().Version.ToString() -eq '0.11.0.0') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.Comments -match 'Phase E4'))
Check 'S09 the E3 and E1 contracts are intact in the source: E1 decision lines unchanged (4), AppController.cs byte-identical to the E3 commit, DrivingActivityState.cs and Shared\* byte-identical to the E3 commit' ((([regex]::Matches((Src 'Caller\src\HandshakeSession.cs'), 'ObsA\("APP_(START_REQUEST|START_SUPPRESSED|STOP_REQUEST|STOP_NOT_REQUIRED)", [^\n]*dryRun=yes"\)')).Count -eq 4) -and ((@((RunGit @('-C', $top, 'diff', '--name-only', $E3Commit, '--', ($prefix + 'Caller/src/AppController.cs'), ($prefix + 'Caller/src/DrivingActivityState.cs'), ($prefix + 'Caller/src/LauncherConfig.cs'), ($prefix + 'Caller/src/TsScoringCallerInputDevice.cs'), ($prefix + 'Shared'))) -split "`n" | Where-Object { $_ })).Count -eq 0))
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', $E3Commit)) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
# Phase L3: hud_ui.py (item visibility by AVAIL) and the independent telemetry project (Handshake/Telemetry: the DATA plane, its own Shared folder) are the L3 changes; their guards are in test_telemetry_l3.py / Test-TelemetryL3.ps1
# Parent-exit fix: managed_mode.py gained the owner-process watch (additive; its guard is tests/test_parent_exit_p1.py), so it is no longer in the list below
$touchedS10 = @($touched | Where-Object { $_ -notmatch '/Telemetry/|Handshake-PhaseL3-' })
Check 'S10 both Bridges, the Bridge shared sources, the plugin projects, Class1.cs, the scoring / UI Python modules (hud_ui.py excepted: Phase L3) and the Docs of earlier phases are untouched since the E3 commit' (@($touchedS10 | Where-Object { $_ -match '/Bridge/|/Shared/|Class1\.cs|AtsLoggerPlugin|\.vcxproj|\.slnx|^scoring_logic\.py$|^menu_ui\.py$|^config\.py$|^utils\.py$|^network\.py$|/Docs/Handshake-Phase[A-DL-M]|Handshake-PhaseE[123]|launcher\.template' }).Count -eq 0)
Check 'S11 no build output, DLL, PDB, log, personal launcher.json or EXE among the files of this phase' (@($touched | Where-Object { $_ -match '/out/|/obj/|/dist/|/logs/|build\.log|\.dll$|\.pdb$|\.log$|\.exe$|\.spec$' -or $_ -match '(^|/)launcher\.json$' }).Count -eq 0)
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$privFiles = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs) + @(Get-Item $callerPath) + @(Get-Item (Join-Path $Root 'Caller\TSScoringPlugin.Caller.InputDevice.csproj'))
foreach ($rel in 'Docs\Handshake-PhaseE4-StatePublication.md') { if (Test-Path (Join-Path $Root $rel)) { $privFiles += @(Get-Item (Join-Path $Root $rel)) } }
foreach ($pyf in 'managed_state.py', 'managed_hud.py', 'main.py', 'tests\test_managed_hud_e4.py', 'tests\managed_hud_child.py', 'tests\fake_bve_window.py', 'tests\managed_state_probe.py') { if (Test-Path (Join-Path $repoRoot $pyf)) { $privFiles += @(Get-Item (Join-Path $repoRoot $pyf)) } }
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
$logHits = 0
foreach ($lf in @(Get-ChildItem $logDir -Filter *.log -ErrorAction SilentlyContinue)) { $lt2 = [IO.File]::ReadAllText($lf.FullName); foreach ($tok in $forbidden) { $logHits += ([regex]::Matches($lt2, [regex]::Escape($tok), 'IgnoreCase')).Count } }
Check ('S12 no personal path, user name, machine name or e-mail in the Caller sources, project, DLL, document, Python sources of this phase (' + $privFiles.Count + ' files, matches=' + $privHits + '), the produced test logs (matches=' + $logHits + ') or this test (matches=' + $selfHits + ')') (($privHits -eq 0) -and ($selfHits -eq 0) -and ($logHits -eq 0))
Check 'S13 no PDB anywhere, dist holds exactly the Caller and the Current Bridge DLL, and no process started by this test is left' ((@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0) -and ((@(Get-ChildItem (Join-Path $Root 'dist') -File | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'TSScoringPlugin.BveEx.Bridge.Prototype.dll,TSScoringPlugin.Caller.InputDevice.dll') -and (@($started | Where-Object { PidAlive $_ }).Count -eq 0))

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}  SKIPPED {2}" -f $results.Count, $failed.Count, $script:skips
if ($failed.Count -gt 0) { $failed | ForEach-Object { 'FAILED: ' + $_.Name }; exit 1 }
