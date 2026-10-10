# PHASE E3 - offline tests of the managed application PROCESS of the Caller (Caller 0.10.0.0).
# What is tested: the launcher.json contract (LauncherConfig.cs), and AppProcessManager.cs: one real process per Caller instance, a new instance id,
# the Stop event created BEFORE the launch, the exact command line, AppReady seen on the real named event, the finite waits, Stop at Dispose only,
# the exit code, the one Kill of an own process that ignores Stop, the release of every resource, and the wiring in HandshakeSession.
# No BVE, no BveEX, no HUD, no MessageBox. The processes that are started are NOT the application: they are small stdlib-only Python children
# written to a private folder by this script (they follow the E2 contract: Ready event set last, Stop event opened, Lock not needed). The optional
# integration sections also run the E2 child with the real Win32 lifecycle and, when UDP 54321 is free and no main.py is running, the real main.py.
# Nothing is installed or changed; the user's real launcher.json is never read (LauncherConfigLoader.TestPath). Every started process is
# identified by the PID the manager holds and is stopped through its Stop event or, as the last resort of the test, by that PID.
# Logs go to a private file under logs\e3-tests (never the fixed Downloads file). This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$PythonExe = '',
    [string]$E2Commit = '6d20650395262e62c10916a4bdb0653947149a8a',
    [string]$E3Commit = 'b9611dad47e2c95f8fa1c89a8bd0286896c75cea',
    [switch]$Probe32,
    [string]$Fixtures = ''
)

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Reflection;
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

public class Racer
{
    public static int Run(Action a, int n)
    {
        int errors = 0;
        ManualResetEvent go = new ManualResetEvent(false);
        Thread[] ts = new Thread[n];
        for (int i = 0; i < n; i++)
        {
            ts[i] = new Thread(() => { go.WaitOne(); try { a(); } catch { Interlocked.Increment(ref errors); } });
            ts[i].IsBackground = true;
            ts[i].Start();
        }
        go.Set();
        foreach (Thread t in ts) { t.Join(); }
        return errors;
    }
}

// Called on the manager's worker thread right after AppReady was seen: starts Shutdown on another thread and waits until the manager is closed.
public class ReadyHook
{
    public object Manager;
    public MethodInfo Shutdown;
    public MethodInfo ClosedGetter;
    public void Run()
    {
        Thread t = new Thread(() => { Shutdown.Invoke(Manager, null); });
        t.IsBackground = true;
        t.Start();
        int guard = 0;
        while (!(bool)ClosedGetter.Invoke(Manager, null) && guard++ < 5000) { Thread.Sleep(1); }
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
$mgrT = $callerAsm.GetType($NS + 'AppProcessManager')
$optT = $callerAsm.GetType($NS + 'AppProcessOptions')
$ldrT = $callerAsm.GetType($NS + 'LauncherConfigLoader')
$namesT = $callerAsm.GetType($NS + 'AppObjectNames')
$timingT = $callerAsm.GetType($NS + 'AppProcessTiming')
$jsonT = $callerAsm.GetType($NS + 'FlatJson')
$ssT = $callerAsm.GetType($NS + 'ScenarioState')
$logT = $callerAsm.GetType($NS + 'ObservationLog')
$phaseT = $callerAsm.GetType($NS + 'CallerPhase')
$deviceT = $callerAsm.GetType($NS + 'TsScoringCallerInputDevice')
$npi = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$nps = [Reflection.BindingFlags]'NonPublic,Public,Static'

$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }

# ---------------------------------------------------------------- environment
function FindPython {
    if ($PythonExe -and (Test-Path $PythonExe)) { return (Resolve-Path $PythonExe).Path }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and ($c.Source -notmatch 'WindowsApps')) { return $c.Source }
    foreach ($cand in 'C:\Python314\python.exe', 'C:\Python313\python.exe', 'C:\Python312\python.exe') { if (Test-Path $cand) { return $cand } }
    return $null
}
[string]$py = FindPython
[string]$fixDir = if ($Fixtures) { $Fixtures } else { Join-Path $Root 'logs\e3-tests\fixtures' }
[string]$logDir = Join-Path $Root 'logs\e3-tests'
[string]$workDir = Join-Path $fixDir 'work'
[string]$cfgPath = Join-Path $fixDir 'launcher.json'
[string]$childScript = Join-Path $fixDir 'fake_managed.py'
[string]$outFile = Join-Path $fixDir 'child-record.json'

function Wait([int]$ms) { Start-Sleep -Milliseconds $ms }
function WaitFor([scriptblock]$cond, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { if (& $cond) { return $true }; Start-Sleep -Milliseconds 20 }
    return [bool](& $cond)
}
function Field([string]$line, [string]$name) { $m = [regex]::Match($line, '\b' + [regex]::Escape($name) + '=(\S+)'); if ($m.Success) { return $m.Groups[1].Value } else { return $null } }
function SetTestPath([string]$p) { $ldrT.GetProperty('TestPath', $nps).SetValue($null, $p) }
function PidAlive([int]$p) { return [bool](Get-Process -Id $p -ErrorAction SilentlyContinue) }
function ObjectExists([string]$name) {
    $x = $null
    $ok = [Threading.EventWaitHandle]::TryOpenExisting($name, [Security.AccessControl.EventWaitHandleRights]::Synchronize, [ref]$x)
    if ($ok -and $x) { $x.Dispose() }
    return $ok
}
function EventLines($sink, [string]$evt) { return , @($sink.Snapshot() | Where-Object { $_ -like ($evt + ' *') -or $_ -eq $evt }) }   # the comma keeps a one-element result an array (so [0] is a line, not a character)
function Names($sink) { return , @($sink.Snapshot() | ForEach-Object { ($_ -split ' ', 2)[0] }) }

$started = New-Object System.Collections.Generic.List[int]
function KillStrays {
    foreach ($p in $started) { if (PidAlive $p) { try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch { } } }
}

# ---------------------------------------------------------------- fixtures
New-Item -ItemType Directory -Force $logDir | Out-Null
if (-not $Probe32) {
    if (Test-Path $fixDir) { Remove-Item $fixDir -Recurse -Force }
    New-Item -ItemType Directory -Force $workDir | Out-Null
    $childText = @'
import ctypes, json, os, sys, threading, time
t0 = time.time()
threading.Thread(target=lambda: (time.sleep(45), os._exit(99)), daemon=True).start()   # orphan guard of the test
mode = os.environ.get("TSS_E3_MODE", "ok")
code = int(os.environ.get("TSS_E3_EXIT", "5"))
delay = int(os.environ.get("TSS_E3_DELAY", "2000"))
out = os.environ.get("TSS_E3_OUT")
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateEventW.restype = ctypes.c_void_p
k.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
k.OpenEventW.restype = ctypes.c_void_p
k.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
k.SetEvent.argtypes = [ctypes.c_void_p]
k.ResetEvent.argtypes = [ctypes.c_void_p]
k.WaitForSingleObject.restype = ctypes.c_uint32
k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
args = sys.argv[1:]
opt = {}
for i in range(0, len(args) - 1):
    if args[i].startswith("--"):
        opt[args[i][2:]] = args[i + 1]
base = "Local\\TSScoringPlugin.v1.%s.App.%s." % (opt.get("bve-pid"), opt.get("instance"))
if out:
    import importlib.util, site
    rec = {"argv": sys.argv, "cwd": os.getcwd(), "executable": sys.executable, "ppid": os.getppid(), "isolated": sys.flags.isolated,
           "no_user_site": sys.flags.no_user_site, "user_site": bool(site.ENABLE_USER_SITE), "pyqt6": importlib.util.find_spec("PyQt6") is not None,
           "mode": mode, "pid": os.getpid()}
    with open(out, "w") as f:
        json.dump(rec, f)
if mode == "chatter":
    for n in range(230):
        sys.stderr.write("[MANAGED] event=chatter inst=%s n=%d\n" % (opt.get("instance"), n))
    sys.stderr.write("Traceback (most recent call last):\n  File \"C:\\secret\\place\\x.py\", line 1, in <module>\nModuleNotFoundError: No module named 'x'\n")
    sys.stderr.flush()
    sys.stdout.write("hello stdout\n" * 5)
    sys.stdout.flush()
if mode == "exit-now":
    sys.exit(code)
stop = k.OpenEventW(0x00100000, 0, base + "Stop")
if not stop:
    sys.exit(4)
ready = k.CreateEventW(None, 1, 0, base + "Ready")
if mode == "no-ready":
    while time.time() - t0 < 40:
        time.sleep(0.1)
    sys.exit(0)
if mode == "ready-delay":
    if k.WaitForSingleObject(stop, delay) == 0:
        sys.exit(0)
k.SetEvent(ready)
if mode == "crash-after-ready":
    time.sleep(0.4)
    sys.exit(7)
if mode == "ready-ignore-stop":
    while time.time() - t0 < 40:
        time.sleep(0.1)
    sys.exit(0)
while k.WaitForSingleObject(stop, 200) != 0:
    if time.time() - t0 > 40:
        sys.exit(98)
k.ResetEvent(ready)
sys.exit(code if mode == "stop-nonzero" else 0)
'@
    [IO.File]::WriteAllText($childScript, $childText, (New-Object Text.UTF8Encoding($false)))
}
$repoRoot = (git -C $Root rev-parse --show-toplevel) -replace '/', '\'
$e2Child = Join-Path $repoRoot 'tests\managed_smoke_child.py'
$mainPy = Join-Path $repoRoot 'main.py'

# ---------------------------------------------------------------- helpers: config, manager
function ConfigJson([hashtable]$over = @{}, [string[]]$drop = @()) {
    $h = [ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $py; scriptPath = $childScript; workingDirectory = $workDir }
    foreach ($k in $over.Keys) { $h[$k] = $over[$k] }
    foreach ($k in $drop) { $h.Remove($k) }
    return ($h | ConvertTo-Json -Compress)
}
function WriteCfg([string]$text) { [IO.File]::WriteAllText($cfgPath, $text, (New-Object Text.UTF8Encoding($false))) }
function LoadCfg([string]$text) {
    WriteCfg $text
    $r = $ldrT.GetMethod('Load').Invoke($null, @($cfgPath))
    return [pscustomobject]@{ Status = [string]$r.GetType().GetField('Status').GetValue($r); Reason = [string]$r.GetType().GetField('Reason').GetValue($r); Raw = $r }
}
function LoadBytes([byte[]]$bytes) {
    $r = $ldrT.GetMethod('Parse').Invoke($null, @(, $bytes))
    return [pscustomobject]@{ Status = [string]$r.GetType().GetField('Status').GetValue($r); Reason = [string]$r.GetType().GetField('Reason').GetValue($r) }
}
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
function SetMode([string]$mode, [int]$exit = 5, [int]$delay = 2000) {
    $env:TSS_E3_MODE = $mode; $env:TSS_E3_EXIT = [string]$exit; $env:TSS_E3_DELAY = [string]$delay
    if (Test-Path $outFile) { Remove-Item $outFile -Force }
}
function Track($h) { $p = [int](Mg $h 'AppPid'); if ($p -gt 0 -and -not $started.Contains($p)) { $started.Add($p) } }
function StopNameOf($h) { return $namesT.GetMethod('Stop').Invoke($null, @($h.Pid, (Mg $h 'Instance'))) }
function ReadyNameOf($h) { return $namesT.GetMethod('Ready').Invoke($null, @($h.Pid, (Mg $h 'Instance'))) }
function ReadRecord { if (Test-Path $outFile) { return (Get-Content $outFile -Raw | ConvertFrom-Json) } else { return $null } }

# one complete lifecycle with the plain child: used for the 64-bit / 32-bit comparison
function RunLifecycle([int]$fakePid) {
    SetTestPath $cfgPath
    WriteCfg (ConfigJson)
    SetMode 'ok'
    $h = NewMgr $fakePid (NewOpts)
    [void](Req $h 1 1)
    $ready = WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000
    Track $h
    $pidBefore = [int](Mg $h 'AppPid')
    Down $h
    $names = (Names $h.Sink) | Where-Object { $_ -notin 'APP_STREAMS' }
    return [pscustomobject]@{
        Ready = $ready; Starts = [int](Mg $h 'ProcessStartCount'); Stops = [int](Mg $h 'StopSignalCount'); Exit = [int](Mg $h 'ExitCode'); State = [string](Mg $h 'State')
        Gone = (-not (PidAlive $pidBefore)); Names = ($names -join ','); Handle = $h
    }
}
function Summary($r) { return ('ready={0} starts={1} stops={2} exit={3} state={4} gone={5} events={6}' -f $r.Ready, $r.Starts, $r.Stops, $r.Exit, $r.State, $r.Gone, $r.Names) }

# ================================================================================================================ 32-bit probe
if ($Probe32) {
    $cfg = LoadCfg (ConfigJson)
    $args32 = $mgrT.GetMethod('BuildArguments', $nps).Invoke($null, @('X:\a b\main.py', 4242, '0123456789abcdef0123456789abcdef'))
    $r = RunLifecycle 950201
    KillStrays
    ('PROBE32 ptr={0} cfg={1} args=[{2}] {3}' -f [IntPtr]::Size, $cfg.Status, $args32, (Summary $r))
    exit 0
}

if (-not $py) {
    Check 'Z00 a Python interpreter was found (set -PythonExe)' $false
    "TOTAL {0}  FAILED {1}" -f $results.Count, 1
    exit 1
}
"python for the child processes: " + (Split-Path $py -Leaf) + " (full path not printed)"
SetTestPath (Join-Path $fixDir 'no-such-launcher.json')   # the real %LOCALAPPDATA% file is never read by any test below

try {
# ================================================================================================================ C: launcher.json contract
Write-Host '--- C: launcher configuration'
$absentR = $ldrT.GetMethod('Load').Invoke($null, @([string](Join-Path $fixDir 'does-not-exist\launcher.json')))
Check 'C01 no launcher.json (also: its folder does not exist): Absent, no reason that is an error, nothing started' (([string]$absentR.GetType().GetField('Status').GetValue($absentR) -eq 'Absent') -and ([string]$absentR.GetType().GetField('Reason').GetValue($absentR) -eq 'file-absent'))
$nullR = $ldrT.GetMethod('Load').Invoke($null, @($null))
Check 'C02 no location at all (null path): Absent, no exception' ([string]$nullR.GetType().GetField('Status').GetValue($nullR) -eq 'Absent')
$def = $ldrT.GetMethod('DefaultPath').Invoke($null, @())
Check 'C03 the production location is %LOCALAPPDATA%\Coruge-to\TS Scoring\launcher.json (built from the OS folder at run time)' ($def -and ($def -ceq (Join-Path (Join-Path (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Coruge-to') 'TS Scoring') 'launcher.json')))
$ok = LoadCfg (ConfigJson)
Check 'C04 a correct file is Loaded and the three values are returned unchanged' (($ok.Status -eq 'Loaded') -and ($ok.Reason -eq '') -and ([string]$ok.Raw.GetType().GetField('Config').GetValue($ok.Raw).PythonExecutable -ceq $py) -and ([string]$ok.Raw.GetType().GetField('Config').GetValue($ok.Raw).ScriptPath -ceq $childScript) -and ([string]$ok.Raw.GetType().GetField('Config').GetValue($ok.Raw).WorkingDirectory -ceq $workDir))
$noVer = LoadCfg (ConfigJson @{} @('schemaVersion'))
Check 'C05 schemaVersion is optional (absent: Loaded); a trailing backslash on the working directory is accepted' (($noVer.Status -eq 'Loaded') -and ((LoadCfg (ConfigJson @{ workingDirectory = ($workDir + '\') })).Status -eq 'Loaded'))
$bom = [byte[]](@(0xEF, 0xBB, 0xBF) + [Text.Encoding]::UTF8.GetBytes((ConfigJson)))
Check 'C06 a UTF-8 BOM (written by Notepad / PowerShell) is tolerated' ((LoadBytes $bom).Status -eq 'Loaded')

$bad = @(
    @('C10 empty file', ''),
    @('C11 not JSON at all', 'hello'),
    @('C12 truncated JSON', '{"mode":"development"'),
    @('C13 JSON array instead of an object', '[1,2]'),
    @('C14 trailing text after the object', ((ConfigJson) + ' x')),
    @('C15 a nested object', '{"mode":{"a":1}}'),
    @('C16 comments are not JSON', ('{"mode":"development" /* c */}')),
    @('C17 single quotes are not JSON', "{'mode':'development'}"),
    @('C18 duplicate key', ((ConfigJson) -replace '^\{', '{"mode":"development",')),
    @('C19 unknown key (a token / password field has no place here)', (ConfigJson @{ apiKey = 'x' })),
    @('C20 mode is not "development"', (ConfigJson @{ mode = 'production' })),
    @('C21 mode with different case', (ConfigJson @{ mode = 'Development' })),
    @('C22 wrong schemaVersion', (ConfigJson @{ schemaVersion = 2 })),
    @('C23 wrong type (number as a path)', ('{"mode":"development","pythonExecutable":1,"scriptPath":"x","workingDirectory":"y"}'))
)
foreach ($b in $bad) {
    $r = LoadCfg $b[1]
    Check ($b[0] + ' -> Invalid (' + $r.Reason + ')') (($r.Status -eq 'Invalid') -and ($r.Reason -match '^[a-z0-9-]+$'))
}
foreach ($k in 'mode', 'pythonExecutable', 'scriptPath', 'workingDirectory') {
    $r = LoadCfg (ConfigJson @{} @($k))
    Check ('C30 required key missing: ' + $k + ' -> Invalid (' + $r.Reason + ')') (($r.Status -eq 'Invalid') -and ($r.Reason -eq ('missing-' + $k)))
}
$rel = @(
    @('C31 relative python path', @{ pythonExecutable = 'python.exe' }),
    @('C32 relative script path', @{ scriptPath = 'main.py' }),
    @('C33 relative working directory', @{ workingDirectory = '.' }),
    @('C34 drive-relative path', @{ scriptPath = 'C:main.py' }),
    @('C35 UNC path', @{ scriptPath = '\\server\share\main.py' }),
    @('C36 dot-dot segment', @{ scriptPath = ($workDir + '\..\work\main.py') }),
    @('C37 forward slashes', @{ scriptPath = ($childScript -replace '\\', '/') }),
    @('C38 environment variable syntax is NOT expanded', @{ pythonExecutable = '%SystemRoot%\python.exe' }),
    @('C39 PATH lookup is never used (bare name)', @{ pythonExecutable = 'python' })
)
foreach ($c in $rel) { $r = LoadCfg (ConfigJson $c[1]); Check ($c[0] + ' -> Invalid (' + $r.Reason + ')') ($r.Status -eq 'Invalid') }
$gone = Join-Path $fixDir 'gone'
$missing = @(
    @('C40 python file does not exist', @{ pythonExecutable = (Join-Path $gone 'python.exe') }, 'python-not-found'),
    @('C41 script file does not exist', @{ scriptPath = (Join-Path $gone 'main.py') }, 'script-not-found'),
    @('C42 working directory does not exist', @{ workingDirectory = $gone }, 'workdir-not-found'),
    @('C43 the working directory is a FILE', @{ workingDirectory = $childScript }, 'workdir-not-found'),
    @('C44 the script is a DIRECTORY named like a script', @{ scriptPath = $workDir }, 'script-not-py')
)
New-Item -ItemType Directory -Force (Join-Path $fixDir 'dir.py') | Out-Null
foreach ($c in $missing) { $r = LoadCfg (ConfigJson $c[1]); Check ($c[0] + ' -> Invalid (' + $r.Reason + ')') (($r.Status -eq 'Invalid') -and ($r.Reason -eq $c[2])) }
$r = LoadCfg (ConfigJson @{ scriptPath = (Join-Path $fixDir 'dir.py') })
Check ('C45 a directory that is named *.py is refused as a script (' + $r.Reason + ')') ($r.Status -eq 'Invalid')
foreach ($f in 'a.txt', 'a.bat', 'a.com', 'a.pyw', 'a.exe', 'pythonw.exe') { Set-Content -Path (Join-Path $fixDir $f) -Value 'x' -Encoding ASCII }
Check 'C46 python must be an .exe: .bat / .com / .py / no extension are refused' ((@('a.bat', 'a.com', 'a.txt') | ForEach-Object { (LoadCfg (ConfigJson @{ pythonExecutable = (Join-Path $fixDir $_) })).Status }) -notcontains 'Loaded')
Check 'C47 the script must be a .py: .txt / .pyw / .exe are refused' ((@('a.txt', 'a.pyw', 'a.exe') | ForEach-Object { (LoadCfg (ConfigJson @{ scriptPath = (Join-Path $fixDir $_) })).Status }) -notcontains 'Loaded')
$rw = LoadCfg (ConfigJson @{ pythonExecutable = (Join-Path $fixDir 'pythonw.exe') })
Check ('C48 pythonw.exe is refused (the diagnostics need stderr) (' + $rw.Reason + ')') (($rw.Status -eq 'Invalid') -and ($rw.Reason -eq 'python-is-pythonw'))
$ctl = @(
    @('C50 NUL character in a path (JSON escape)', '\u0000'), @('C51 TAB in a path', '\u0009'), @('C52 line feed in a path', '\u000a'),
    @('C53 DEL in a path', '\u007f'), @('C54 a double quote in a path', '\"'), @('C55 a pipe in a path', '|'), @('C56 an angle bracket in a path', '<'), @('C57 an asterisk in a path', '*')
)
foreach ($c in $ctl) {
    $text = (ConfigJson @{ scriptPath = 'X' }) -replace '"scriptPath":"X"', ('"scriptPath":"' + ($childScript -replace '\\', '\\') + $c[1] + '"')
    $r = LoadCfg $text
    Check ($c[0] + ' -> Invalid (' + $r.Reason + ')') ($r.Status -eq 'Invalid')
}
$r = LoadCfg ((ConfigJson) -replace '"scriptPath":"', ("`"scriptPath`":`"" + [char]9))
Check ('C58 a RAW control character inside a JSON string is not JSON -> Invalid (' + $r.Reason + ')') ($r.Status -eq 'Invalid')
Check 'C59 trailing / leading blank, a trailing dot, an alternate data stream colon, and a path longer than 259 characters are refused' ((@(
    (ConfigJson @{ scriptPath = ($childScript + ' ') }), (ConfigJson @{ scriptPath = (' ' + $childScript) }), (ConfigJson @{ workingDirectory = ($workDir + '.') }),
    (ConfigJson @{ scriptPath = ($childScript + ':evil') }), (ConfigJson @{ scriptPath = ('C:\' + ('a' * 260) + '.py') }), (ConfigJson @{ scriptPath = ($childScript + '\') })
) | ForEach-Object { (LoadCfg $_).Status }) -notcontains 'Loaded')
$big = '{"mode":"development","x":"' + ('a' * 9000) + '"}'
$r = LoadCfg $big
Check ('C60 a file larger than 8 KiB is refused without being parsed (' + $r.Reason + ')') (($r.Status -eq 'Invalid') -and ($r.Reason -eq 'file-too-large'))
$r = LoadBytes ([byte[]](0x7B, 0xFF, 0xFE, 0x7D))
Check ('C61 bytes that are not UTF-8 are refused (' + $r.Reason + ')') (($r.Status -eq 'Invalid') -and ($r.Reason -eq 'not-utf8'))
Remove-Item $cfgPath -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $cfgPath | Out-Null
$r = $ldrT.GetMethod('Load').Invoke($null, @($cfgPath))
Check 'C62 launcher.json is a DIRECTORY: Invalid (config-is-directory), no exception' (([string]$r.GetType().GetField('Status').GetValue($r) -eq 'Invalid') -and ([string]$r.GetType().GetField('Reason').GetValue($r) -eq 'config-is-directory'))
Remove-Item $cfgPath -Recurse -Force
WriteCfg (ConfigJson)
$lock = New-Object IO.FileStream($cfgPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$r = $ldrT.GetMethod('Load').Invoke($null, @($cfgPath))
$lock.Dispose()
Check ('C63 a file that cannot be read (exclusively locked by another process): Invalid (unreadable), no exception, not Absent (' + [string]$r.GetType().GetField('Reason').GetValue($r) + ')') (([string]$r.GetType().GetField('Status').GetValue($r) -eq 'Invalid') -and ([string]$r.GetType().GetField('Reason').GetValue($r) -eq 'unreadable'))
$reasons = New-Object System.Collections.Generic.List[string]
foreach ($b in $bad) { $reasons.Add((LoadCfg $b[1]).Reason) }
Check 'C64 no reason text carries a value from the file or a path (fixed vocabulary: lower case letters, digits, hyphens only)' (@($reasons | Where-Object { $_ -notmatch '^[a-z0-9-]{1,40}$' }).Count -eq 0)
Check 'C65 FlatJson: integers with a leading zero, fractions and exponents are refused; escapes are decoded' ((-not ($jsonT.GetMethod('TryParse').Invoke($null, @('{"a":01}', $null, $null)))) -and (-not ($jsonT.GetMethod('TryParse').Invoke($null, @('{"a":1.5}', $null, $null)))) -and (-not ($jsonT.GetMethod('TryParse').Invoke($null, @('{"a":1e3}', $null, $null)))))

# ================================================================================================================ P: command line, contract names, constants
Write-Host '--- P: start description'
$cfgObj = [Activator]::CreateInstance($callerAsm.GetType($NS + 'LauncherConfig'))
$cfgObj.GetType().GetField('PythonExecutable').SetValue($cfgObj, 'X:\py dir\python.exe')
$cfgObj.GetType().GetField('ScriptPath').SetValue($cfgObj, 'X:\app dir\main.py')
$cfgObj.GetType().GetField('WorkingDirectory').SetValue($cfgObj, 'X:\app dir')
$inst0 = '0123456789abcdef0123456789abcdef'
$psi = $mgrT.GetMethod('BuildStartInfo', $nps).Invoke($null, @($cfgObj, 4242, $inst0))
$expectArgs = '"X:\app dir\main.py" --managed --owner caller --bve-pid 4242 --instance ' + $inst0
Check 'P01 the command line is exactly: "<script>" --managed --owner caller --bve-pid <n> --instance <32 hex>' ($psi.Arguments -ceq $expectArgs)
Check 'P02 FileName is the absolute interpreter itself (no command line, no PATH lookup, no cmd.exe); WorkingDirectory is the configured one' (($psi.FileName -ceq 'X:\py dir\python.exe') -and ($psi.WorkingDirectory -ceq 'X:\app dir'))
Check 'P03 no shell (UseShellExecute false), no window, stderr and stdout redirected (read asynchronously), no stdin redirection, no verb' ((-not $psi.UseShellExecute) -and $psi.CreateNoWindow -and $psi.RedirectStandardError -and $psi.RedirectStandardOutput -and (-not $psi.RedirectStandardInput) -and ([string]::IsNullOrEmpty($psi.Verb)))
Check 'P04 python is NOT started with -I (the per-user site-packages must stay visible), nor -S / -E / -s / -c / -m' (($psi.Arguments -notmatch '(^|\s)-(I|S|E|s|c|m)(\s|$)') -and ($psi.Arguments -match '^"'))
$envCount = [Environment]::GetEnvironmentVariables().Count
Check 'P05 the environment is inherited unchanged (the start description sets no variable)' ($psi.EnvironmentVariables.Count -eq $envCount)
$nm = $namesT
Check 'P06 contract names mirror managed_mode.py: Local\TSScoringPlugin.v1.<PID>.App.<INST>.{Lock,Stop,Ready}' (($nm.GetMethod('Lock').Invoke($null, @(77, $inst0)) -ceq ('Local\TSScoringPlugin.v1.77.App.' + $inst0 + '.Lock')) -and ($nm.GetMethod('Stop').Invoke($null, @(77, $inst0)) -ceq ('Local\TSScoringPlugin.v1.77.App.' + $inst0 + '.Stop')) -and ($nm.GetMethod('Ready').Invoke($null, @(77, $inst0)) -ceq ('Local\TSScoringPlugin.v1.77.App.' + $inst0 + '.Ready')))
$pyNames = & $py -c "import sys; sys.path.insert(0, r'$repoRoot'); import managed_mode as m; a, why = m.parse_managed_args(['--managed','--owner','caller','--bve-pid','77','--instance','$inst0']); print(a.lock_name, a.stop_name, a.ready_name)" 2>$null
Check 'P07 the Python side (managed_mode.py) builds the same three names for the same PID and instance' (($pyNames -is [string]) -and ($pyNames -ceq (($nm.GetMethod('Lock').Invoke($null, @(77, $inst0))) + ' ' + ($nm.GetMethod('Stop').Invoke($null, @(77, $inst0))) + ' ' + ($nm.GetMethod('Ready').Invoke($null, @(77, $inst0))))))
Check 'P08 timing constants are in ONE place: ready 15000, poll 25, exit poll 100, grace 3000, kill wait 2000, drain 500, margin 1500; owner "caller"; stderr cap 200 lines (Phase E4: raised from 20) of 160 characters' ((((@('ReadyTimeoutMs', 'ReadyPollMs', 'ExitPollMs', 'StopGraceMs', 'KillWaitMs', 'StreamDrainMs', 'ShutdownMarginMs') | ForEach-Object { [int]$timingT.GetField($_).GetRawConstantValue() }) -join ',') -ceq '15000,25,100,3000,2000,500,1500') -and ([string]$timingT.GetField('Owner').GetRawConstantValue() -ceq 'caller') -and ([int]$timingT.GetField('MaxStderrLogLines').GetRawConstantValue() -eq 200) -and ([int]$timingT.GetField('MaxStderrLineChars').GetRawConstantValue() -eq 160))
$o = [Activator]::CreateInstance($optT)
Check 'P09 the default options equal the constants; the Dispose join bound is grace + kill wait + drain + margin' (([int]$optT.GetField('ReadyTimeoutMs').GetValue($o) -eq 15000) -and ([int]$optT.GetProperty('ShutdownJoinMs').GetValue($o) -eq 7000))

# ================================================================================================================ Q: the manager with real processes
Write-Host '--- Q: process start, AppReady, stop (real child processes)'
# --- no configuration: nothing is started, the situation is logged once
SetTestPath (Join-Path $fixDir 'still-absent.json')
$h = NewMgr 960301 (NewOpts)
$d1 = Req $h 1 1; $d2 = Req $h 1 2; $d3 = Req $h 2 3
Wait 400
Check 'Q01 no launcher.json: three start requests start nothing (0 Process.Start, state None, no Stop event created), the "absent" situation is logged ONCE' (([int](Mg $h 'ProcessStartCount') -eq 0) -and ([int](Mg $h 'AttemptCount') -eq 0) -and ([string](Mg $h 'State') -eq 'None') -and ((EventLines $h.Sink 'APP_LAUNCH_CONFIG_ABSENT').Count -eq 1) -and ((EventLines $h.Sink 'APP_LAUNCH_BEGIN').Count -eq 0) -and ([int](Mg $h 'StopSignalCount') -eq 0))
Down $h
$hNever = NewMgr 960300 (NewOpts)
Down $hNever
Check 'Q02 Dispose of an instance whose requests found no configuration (state None), and of an instance that never got a request: no Stop signal, no exception, one "end" line each (the second says processStarted=no)' (((EventLines $h.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and ((EventLines $h.Sink 'APP_SHUTDOWN_END')[0] -match 'state=None.*stopSignals=0') -and ([int](Mg $h 'StopSignalCount') -eq 0) -and (-not (Mg $h 'WorkerAlive')) -and ((EventLines $hNever.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and ((EventLines $hNever.Sink 'APP_SHUTDOWN_END')[0] -match 'processStarted=no') -and ([int](Mg $hNever 'StopSignalCount') -eq 0))
Down $h
Check 'Q03 a second Dispose adds no log line and a start request after Dispose is refused (Closed), nothing starts' (((EventLines $h.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and ((Req $h 9 9) -eq 'Closed') -and ([int](Mg $h 'ProcessStartCount') -eq 0))
SetTestPath $cfgPath
WriteCfg (ConfigJson @{ mode = 'production' })
$h = NewMgr 960302 (NewOpts)
[void](Req $h 1 1); [void](Req $h 1 2); Wait 300
Check 'Q04 an invalid launcher.json starts nothing and is logged once with its reason (mode-not-development); the attempt is NOT used' (([int](Mg $h 'ProcessStartCount') -eq 0) -and ([int](Mg $h 'AttemptCount') -eq 0) -and ((EventLines $h.Sink 'APP_LAUNCH_CONFIG_INVALID').Count -eq 1) -and ((EventLines $h.Sink 'APP_LAUNCH_CONFIG_INVALID')[0] -match 'reason=mode-not-development'))
WriteCfg (ConfigJson)
SetMode 'ok'
[void](Req $h 2 3)
$rdy = WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000
Track $h
Check 'Q05 the file is corrected and the next request starts the application (the failed validation had not used the attempt)' ($rdy -and ([int](Mg $h 'ProcessStartCount') -eq 1))
Down $h

# --- the first real start: exact command line, working directory, direct child, user site, PID, instance, Stop before launch
SetMode 'ok'
$env:TSS_E3_OUT = $outFile
$h = NewMgr 960310 (NewOpts)
$sw = [Diagnostics.Stopwatch]::StartNew()
$dec = Req $h 1 1
$reqMs = $sw.ElapsedMilliseconds
$stateEarly = [string](Mg $h 'State')
$rdy = WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000
$readyMs = $sw.ElapsedMilliseconds
Track $h
$childPid = [int](Mg $h 'AppPid'); $inst = [string](Mg $h 'Instance')
$stopOpen = ObjectExists (StopNameOf $h)
$readyOpen = ObjectExists (ReadyNameOf $h)
$rec = ReadRecord
Check ('Q10 the first request: decision Started, the call returned in ' + $reqMs + ' ms (it only queues the worker), state Starting then Ready after ' + $readyMs + ' ms, exactly ONE Process.Start, one attempt') (($dec -eq 'Started') -and ($reqMs -lt 250) -and ($stateEarly -eq 'Starting') -and $rdy -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ([int](Mg $h 'AttemptCount') -eq 1) -and (Mg $h 'ReadyAccepted'))
Check 'Q11 the PID is recorded and is a live process; the process is a direct child of this process (no cmd.exe / shell in between)' (($childPid -gt 0) -and (PidAlive $childPid) -and ($rec -ne $null) -and ([int]$rec.pid -eq $childPid) -and ([int]$rec.ppid -eq $PID))
Check 'Q12 the instance id is 32 lower-case hex digits; the Stop event existed (and still exists) while the child runs, the Ready event is the child''s own named event' (($inst -cmatch '^[0-9a-f]{32}$') -and $stopOpen -and $readyOpen)
$expArgv = @($childScript, '--managed', '--owner', 'caller', '--bve-pid', '960310', '--instance', $inst)
Check 'Q13 the child received EXACTLY the arguments  <script> --managed --owner caller --bve-pid <fake pid> --instance <inst>  and nothing else' (($rec -ne $null) -and ((@($rec.argv) -join '|') -ceq ($expArgv -join '|')))
Check 'Q14 the working directory of the child is the configured one; the interpreter is the configured one' (($rec.cwd -ieq $workDir) -and ($rec.executable -ieq $py))
Check 'Q15 the child runs WITHOUT isolated mode and with the user site enabled (so the per-user PyQt6 stays importable)' (($rec.isolated -eq 0) -and ($rec.no_user_site -eq 0) -and ($rec.user_site -eq $true))
$more = @(); 1..5 | ForEach-Object { $more += (Req $h 1 ($_ + 1)) }
Check 'Q16 five more requests for the SAME generation while the process lives: all suppressed (SuppressedAlive), still exactly one Process.Start, same PID, same instance' (((($more | Sort-Object -Unique) -join ',') -eq 'SuppressedAlive') -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ([int](Mg $h 'AppPid') -eq $childPid) -and ([string](Mg $h 'Instance') -ceq $inst) -and ((EventLines $h.Sink 'APP_LAUNCH_SUPPRESSED').Count -eq 5))
$more2 = @(); 2..4 | ForEach-Object { $more2 += (Req $h $_ ($_ + 10)) }
Check 'Q17 requests of NEW scenario generations (reload) while the process lives: suppressed, no second process, the process is not touched (alive, Stop not signalled)' (((($more2 | Sort-Object -Unique) -join ',') -eq 'SuppressedAlive') -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and (PidAlive $childPid) -and ([int](Mg $h 'StopSignalCount') -eq 0) -and ([string](Mg $h 'State') -eq 'Ready'))
Check 'Q18 diagnostics so far: launch begin, started (PID + instance), ready wait begin, ready - in this order, each once; the log carries no path' ((($h.Sink.Snapshot() | Where-Object { $_ -match '^APP_(LAUNCH_BEGIN|PROCESS_STARTED|READY_WAIT_BEGIN|READY) ' } | ForEach-Object { ($_ -split ' ')[0] }) -join ',' -ceq 'APP_LAUNCH_BEGIN,APP_PROCESS_STARTED,APP_READY_WAIT_BEGIN,APP_READY') -and ((EventLines $h.Sink 'APP_PROCESS_STARTED')[0] -match ('appPid=' + $childPid + ' instance=' + $inst)) -and (@($h.Sink.Snapshot() | Where-Object { $_ -match '[A-Za-z]:\\' }).Count -eq 0))
[GC]::Collect(); [GC]::WaitForPendingFinalizers(); [GC]::Collect()
$handlesBefore = [Diagnostics.Process]::GetCurrentProcess().HandleCount
# --- Dispose: Stop once, normal exit, released
$sw.Restart()
Down $h
$downMs = $sw.ElapsedMilliseconds
$exitLine = (EventLines $h.Sink 'APP_EXITED')
Check ('Q20 Dispose: Stop is set exactly once, the child leaves by itself (exit code 0, not killed) in ' + $downMs + ' ms, state Exited') (([int](Mg $h 'StopSignalCount') -eq 1) -and ((EventLines $h.Sink 'APP_STOP_SIGNALLED').Count -eq 1) -and (-not (PidAlive $childPid)) -and ([int](Mg $h 'ExitCode') -eq 0) -and (Mg $h 'ExitObserved') -and (-not (Mg $h 'Killed')) -and ([string](Mg $h 'State') -eq 'Exited') -and ($exitLine.Count -eq 1) -and ($exitLine[0] -match 'exitCode=0 exitName=normal killed=no') -and ($downMs -lt 2500))
Check 'Q21 after Dispose: the Stop event and the Ready event no longer exist (every handle was released), the worker thread ended, "end" logged once with exitCode=0' ((-not (ObjectExists (StopNameOf $h))) -and (-not (ObjectExists (ReadyNameOf $h))) -and (-not (Mg $h 'WorkerAlive')) -and ((EventLines $h.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and ((EventLines $h.Sink 'APP_SHUTDOWN_END')[0] -match 'exitCode=0'))
$sw.Restart(); Down $h; Down $h
Check 'Q22 Dispose twice more: no second Stop, no new log line, no exception' (([int](Mg $h 'StopSignalCount') -eq 1) -and ((EventLines $h.Sink 'APP_STOP_SIGNALLED').Count -eq 1) -and ($sw.ElapsedMilliseconds -lt 100))
Check 'Q23 after Dispose a start request is refused (Closed): no restart, ProcessStartCount stays 1' (((Req $h 5 50) -eq 'Closed') -and ([int](Mg $h 'ProcessStartCount') -eq 1))
Check 'Q24 stderr / stdout: the child wrote nothing in mode ok - both ends were reached, counters 0 (the readers are drained)' (((EventLines $h.Sink 'APP_STREAMS')[0] -match 'stderrLines=0 stderrLogged=0 stderrDropped=0 stdoutBytes=0 stderrEnd=yes stdoutEnd=yes') -and ([long](Mg $h 'StdoutByteCount') -eq 0))

# --- instance uniqueness and handle balance over several cycles
$ids = New-Object System.Collections.Generic.List[string]
SetMode 'ok'
for ($i = 0; $i -lt 10; $i++) {
    $x = NewMgr (960320 + $i) (NewOpts)
    [void](Req $x 1 1)
    [void](WaitFor { [string](Mg $x 'State') -eq 'Ready' } 15000)
    Track $x
    $ids.Add([string](Mg $x 'Instance'))
    Down $x
}
[GC]::Collect(); [GC]::WaitForPendingFinalizers(); [GC]::Collect()
$handlesAfter = [Diagnostics.Process]::GetCurrentProcess().HandleCount
Check ('Q30 ten more launches: ten DIFFERENT instance ids (and none equals the first), every one valid') ((($ids | Sort-Object -Unique).Count -eq 10) -and ($ids -notcontains $inst) -and (@($ids | Where-Object { $_ -cnotmatch '^[0-9a-f]{32}$' }).Count -eq 0))
Check ('Q31 handle balance: this process holds ' + $handlesBefore + ' handles before and ' + $handlesAfter + ' after ten more complete start / stop cycles (after a collection): less than one handle per cycle') ($handlesAfter -le $handlesBefore + 10)
$gids = New-Object System.Collections.Generic.HashSet[string]
1..300 | ForEach-Object { [void]$gids.Add(($mgrT.GetMethod('BuildStartInfo', $nps).Invoke($null, @($cfgObj, 1, ([Guid]::NewGuid().ToString('N')))).Arguments)) }
Check 'Q32 the command line of 300 start descriptions differs in every case only by the instance (all distinct)' ($gids.Count -eq 300)

# --- Process.Start failure
SetMode 'ok'
[IO.File]::WriteAllText((Join-Path $fixDir 'broken.exe'), 'this is not an executable', [Text.Encoding]::ASCII)
WriteCfg (ConfigJson @{ pythonExecutable = (Join-Path $fixDir 'broken.exe') })
$h = NewMgr 960340 (NewOpts)
[void](Req $h 1 1)
$failed = WaitFor { [string](Mg $h 'State') -eq 'Failed' } 8000
$again = Req $h 2 2
Check 'Q40 Process.Start fails (not an executable): state Failed, exactly one Process.Start, the failure is logged with type and Win32 code, no PID, no exception escapes' ($failed -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ((EventLines $h.Sink 'APP_PROCESS_START_FAILED').Count -eq 1) -and ((EventLines $h.Sink 'APP_PROCESS_START_FAILED')[0] -match 'type=Win32Exception win32=\d+') -and ([int](Mg $h 'AppPid') -eq 0))
Check 'Q41 after the failed start there is NO retry: the next request is suppressed (attempt already used), still one Process.Start' (($again -eq 'SuppressedAttemptUsed') -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ((EventLines $h.Sink 'APP_LAUNCH_SUPPRESSED')[0] -match 'reason=attempt-already-used'))
$stopN = StopNameOf $h
Down $h
Check 'Q42 Dispose after a failed start: no Stop signal needed (nothing runs), the Stop event created before the launch is released, "end" logged' (([int](Mg $h 'StopSignalCount') -eq 0) -and (-not (ObjectExists $stopN)) -and ((EventLines $h.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and (-not (Mg $h 'WorkerAlive')))

# --- exits at once (before Ready)
WriteCfg (ConfigJson)
SetMode 'exit-now' 2
$h = NewMgr 960341 (NewOpts)
[void](Req $h 1 1)
$failed = WaitFor { [string](Mg $h 'State') -eq 'Failed' } 15000
Track $h
$again = Req $h 2 2
Check 'Q50 the process exits at once with code 2 (UDP bind failed in the E2 table) BEFORE Ready: AppFailed, exit code and its name logged, never "Ready", no restart' ($failed -and ((EventLines $h.Sink 'APP_EXIT_BEFORE_READY').Count -eq 1) -and ((EventLines $h.Sink 'APP_EXIT_BEFORE_READY')[0] -match 'exitCode=2 exitName=udp-bind-failed') -and (-not (Mg $h 'ReadyAccepted')) -and ((EventLines $h.Sink 'APP_READY').Count -eq 0) -and ($again -eq 'SuppressedAttemptUsed') -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ([int](Mg $h 'ExitCode') -eq 2))
Down $h
Check 'Q51 Dispose after an early exit: Stop was never needed (0 signals), everything released' (([int](Mg $h 'StopSignalCount') -eq 0) -and (-not (ObjectExists (StopNameOf $h))) -and (-not (Mg $h 'WorkerAlive')))

# --- exit after Ready (crash)
SetMode 'crash-after-ready'
$h = NewMgr 960342 (NewOpts)
[void](Req $h 1 1)
$crashed = WaitFor { (EventLines $h.Sink 'APP_EXIT_AFTER_READY').Count -ge 1 } 15000
Track $h
$again = Req $h 2 2
Check 'Q55 the process crashes (code 7) AFTER Ready: seen as an exit after Ready, no automatic restart (one Process.Start, the next request is suppressed)' ($crashed -and ((EventLines $h.Sink 'APP_EXIT_AFTER_READY')[0] -match 'exitCode=7 exitName=other restart=no') -and ($again -eq 'SuppressedAttemptUsed') -and ([int](Mg $h 'ProcessStartCount') -eq 1) -and ([string](Mg $h 'State') -eq 'Exited'))
Down $h

# --- Ready timeout: the process never becomes Ready and ignores Stop -> Stop, grace, one Kill of the own process
SetMode 'no-ready'
$h = NewMgr 960343 (NewOpts 700 500 3000)
$sw = [Diagnostics.Stopwatch]::StartNew()
[void](Req $h 1 1)
$tmo = WaitFor { (EventLines $h.Sink 'APP_EXITED').Count -ge 1 } 15000
$tmoMs = $sw.ElapsedMilliseconds
Track $h
$cp = [int](Mg $h 'AppPid')
Check ('Q60 no Ready within the limit (700 ms in this test): APP_READY_TIMEOUT, the clean-up Stop is signalled once, the process (which ignores Stop) is killed after the grace (500 ms) - the whole story took ' + $tmoMs + ' ms') ($tmo -and ((EventLines $h.Sink 'APP_READY_TIMEOUT').Count -eq 1) -and ((EventLines $h.Sink 'APP_STOP_SIGNALLED').Count -eq 1) -and ((EventLines $h.Sink 'APP_STOP_SIGNALLED')[0] -match 'reason=ready-timeout-cleanup') -and ((EventLines $h.Sink 'APP_STOP_TIMEOUT').Count -eq 1) -and ((EventLines $h.Sink 'APP_KILLED').Count -eq 1) -and (-not (PidAlive $cp)) -and (Mg $h 'Killed') -and ([string](Mg $h 'State') -eq 'Failed') -and ($tmoMs -lt 7000))
Down $h
Check 'Q61 Dispose after a timed-out start: the Stop signal count stays 1, nothing is killed twice, the worker is gone, "end" logged once' (([int](Mg $h 'StopSignalCount') -eq 1) -and ((EventLines $h.Sink 'APP_KILLED').Count -eq 1) -and (-not (Mg $h 'WorkerAlive')) -and ((EventLines $h.Sink 'APP_SHUTDOWN_END').Count -eq 1))

# --- Dispose while waiting for Ready: the Ready that comes later is not adopted
SetMode 'ready-delay' 0 2500
$h = NewMgr 960344 (NewOpts)
[void](Req $h 1 1)
[void](WaitFor { [int](Mg $h 'AppPid') -gt 0 } 10000)
Track $h
$cp = [int](Mg $h 'AppPid')
Wait 200
$sw = [Diagnostics.Stopwatch]::StartNew()
Down $h
Check ('Q62 Dispose during the Ready wait: Stop is set, the process leaves by itself (exit 0, never Ready) in ' + $sw.ElapsedMilliseconds + ' ms, no APP_READY, Ready never accepted') (($sw.ElapsedMilliseconds -lt 3000) -and (-not (PidAlive $cp)) -and ([int](Mg $h 'StopSignalCount') -eq 1) -and ([int](Mg $h 'ExitCode') -eq 0) -and (-not (Mg $h 'Killed')) -and ((EventLines $h.Sink 'APP_READY').Count -eq 0) -and (-not (Mg $h 'ReadyAccepted')))
SetMode 'ok'
$h = NewMgr 960345 (NewOpts)
$hook = New-Object ReadyHook
$hook.Manager = $h.Mgr
$hook.Shutdown = $mgrT.GetMethod('Shutdown')
$hook.ClosedGetter = $mgrT.GetProperty('Closed').GetGetMethod()
$mgrT.GetProperty('ReadyObservedHook', $npi).SetValue($h.Mgr, [Delegate]::CreateDelegate([Action], $hook, 'Run'), $null)
[void](Req $h 1 1)
$done = WaitFor { (EventLines $h.Sink 'APP_SHUTDOWN_END').Count -ge 1 } 15000
Track $h
$cp = [int](Mg $h 'AppPid')
Check 'Q63 the Ready event IS seen but Dispose has begun at that moment: it is NOT adopted (APP_READY_IGNORED reason=caller-disposing, no APP_READY, state never Ready), the process still ends normally' ($done -and ((EventLines $h.Sink 'APP_READY_IGNORED').Count -eq 1) -and ((EventLines $h.Sink 'APP_READY_IGNORED')[0] -match 'reason=caller-disposing') -and ((EventLines $h.Sink 'APP_READY').Count -eq 0) -and (-not (Mg $h 'ReadyAccepted')) -and (-not (PidAlive $cp)) -and ([int](Mg $h 'ExitCode') -eq 0))

# --- concurrent Dispose
SetMode 'ok'
$h = NewMgr 960346 (NewOpts)
[void](Req $h 1 1)
[void](WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000)
Track $h
$cp = [int](Mg $h 'AppPid')
$act = [Delegate]::CreateDelegate([Action], $h.Mgr, $mgrT.GetMethod('Shutdown'))
$errs = [Racer]::Run($act, 12)
Check 'Q64 Dispose from 12 threads at once: no exception, exactly ONE Stop signal, exactly one "end" line, the process ended' (($errs -eq 0) -and ([int](Mg $h 'StopSignalCount') -eq 1) -and ((EventLines $h.Sink 'APP_STOP_SIGNALLED').Count -eq 1) -and ((EventLines $h.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and (-not (PidAlive $cp)))

# --- non-zero exit code on Stop
SetMode 'stop-nonzero' 3
$h = NewMgr 960347 (NewOpts)
[void](Req $h 1 1)
[void](WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000)
Track $h
Down $h
Check 'Q70 the process answers Stop with exit code 3 (duplicate instance in the E2 table): the code and its name are recorded, it is not killed, the stop was a normal one' (([int](Mg $h 'ExitCode') -eq 3) -and ((EventLines $h.Sink 'APP_EXITED')[0] -match 'exitCode=3 exitName=duplicate-instance killed=no') -and (-not (Mg $h 'Killed')) -and ([int](Mg $h 'StopSignalCount') -eq 1))

# --- stop timeout: the process ignores Stop after Ready
SetMode 'ready-ignore-stop'
$h = NewMgr 960348 (NewOpts 8000 600 3000)
[void](Req $h 1 1)
[void](WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000)
Track $h
$cp = [int](Mg $h 'AppPid')
$sw = [Diagnostics.Stopwatch]::StartNew()
Down $h
$ms = $sw.ElapsedMilliseconds
Check ('Q71 the process ignores Stop: Dispose is NOT blocked for ever - after the grace (600 ms in this test) the one own process is killed; Dispose returned after ' + $ms + ' ms (bound = grace + kill wait + drain + margin)') (($ms -lt 600 + 3000 + 500 + 1500 + 500) -and ($ms -ge 500) -and ((EventLines $h.Sink 'APP_STOP_TIMEOUT').Count -eq 1) -and ((EventLines $h.Sink 'APP_STOP_TIMEOUT')[0] -match 'action=kill-own-process') -and ((EventLines $h.Sink 'APP_KILLED').Count -eq 1) -and (Mg $h 'Killed') -and (-not (PidAlive $cp)) -and ((EventLines $h.Sink 'APP_EXITED')[0] -match 'exitName=killed killed=yes') -and ([int](Mg $h 'StopSignalCount') -eq 1))
Check 'Q72 after the kill nothing of the process remains: no Stop / Ready event, no worker thread, state Exited, "end" says killed=yes' ((-not (ObjectExists (StopNameOf $h))) -and (-not (ObjectExists (ReadyNameOf $h))) -and (-not (Mg $h 'WorkerAlive')) -and ([string](Mg $h 'State') -eq 'Exited') -and ((EventLines $h.Sink 'APP_SHUTDOWN_END')[0] -match 'killed=yes'))

# --- stderr policy
SetMode 'chatter'
$h = NewMgr 960349 (NewOpts)
[void](Req $h 1 1)
[void](WaitFor { [string](Mg $h 'State') -eq 'Ready' } 15000)
Track $h
Down $h
$errLines = EventLines $h.Sink 'APP_STDERR'
Check ('Q80 stderr policy: 230 E2 diagnostic lines + a traceback were written; at most 200 [MANAGED] lines (Phase E4 cap) are copied to the log (' + $errLines.Count + '), the rest is only counted, the traceback (it holds a path) is NEVER copied - only its exception TYPE is kept') (($errLines.Count -eq 200) -and (@($errLines | Where-Object { $_ -notmatch '^APP_STDERR line=\[MANAGED\] ' }).Count -eq 0) -and ((EventLines $h.Sink 'APP_STREAMS')[0] -match 'stderrLines=233 stderrLogged=200 stderrDropped=30') -and ((EventLines $h.Sink 'APP_STREAMS')[0] -match 'lastErrorType=ModuleNotFoundError') -and (@($h.Sink.Snapshot() | Where-Object { $_ -match 'secret|place|x\.py|Traceback' }).Count -eq 0))
Check 'Q81 stdout is drained and only counted (5 lines of 14 characters written -> 70 counted), never copied; nothing deadlocked' (([long](Mg $h 'StdoutByteCount') -gt 0) -and (@($h.Sink.Snapshot() | Where-Object { $_ -match 'hello stdout' }).Count -eq 0))
Check 'Q82 every copied line is printable ASCII and at most 160 characters long' (@($errLines | Where-Object { ($_.Length - 'APP_STDERR line='.Length) -gt 160 -or $_ -match '[^\x20-\x7e]' }).Count -eq 0)

# ================================================================================================================ R: HandshakeSession wiring
Write-Host '--- R: session wiring (start request -> process, Dispose -> Stop)'
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
    $w = $ssT.GetMethod('Write')
    if ($ready) { $w.Invoke($null, @($b.View, $b.Pid, $gen, $true)) | Out-Null; $b.Ev['ScenarioReady'].Set() | Out-Null }
    else { $b.Ev['ScenarioReady'].Reset() | Out-Null; $w.Invoke($null, @($b.View, $b.Pid, $gen, $false)) | Out-Null }
}
function DisposeBridgeObjs($b) {
    foreach ($k in @($b.Ev.Keys)) { try { $b.Ev[$k].Dispose() } catch { } }
    try { $b.View.Dispose() } catch { }
    try { $b.Mmf.Dispose() } catch { }
}
$ctor4 = $sessT.GetConstructor($npi, $null, [Type[]]@([int], [Action[string]], [Func[bool]], $mgrT), $null)
$stepM = $sessT.GetMethod('Step', $npi)
$cycle = 400
function NewSession([int]$fakePid, $mgr) {
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
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

SetMode 'ok'
$fp = 960360
$log = SetLog 'r1.log' $fp
$b = NewBridgeObjs $fp
$m = NewMgr $fp (NewOpts)
$s = NewSession $fp $m.Mgr
for ($i = 0; $i -lt 20; $i++) { Tick $s; Step $s }
SetSR $b 1 $true; Step $s; Step $s
Tick $s
$sw = [Diagnostics.Stopwatch]::StartNew(); Step $s; $stepMs = $sw.ElapsedMilliseconds
$rdy = WaitFor { [string](Mg $m 'State') -eq 'Ready' } 15000
Track $m
$cp = [int](Mg $m 'AppPid')
Check ('R01 the first DrivingActive ON of generation 1 raises ONE start request which starts ONE process; the monitor step that raised it took ' + $stepMs + ' ms (it never waits for the process)') (($stepMs -lt 250) -and $rdy -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ((ELines $log 'APP_START_REQUEST').Count -eq 1) -and ((EventLines $m.Sink 'APP_PROCESS_STARTED').Count -eq 1) -and ((EventLines $m.Sink 'APP_READY').Count -eq 1))
for ($i = 0; $i -lt 60; $i++) { Tick $s; Step $s }                    # Pause-like: Ticks go on
MakeStale $s 2500; Step $s                                              # soft OFF
Tick $s; Step $s                                                        # ON again
MakeStale $s 2500; Step $s; Tick $s; Step $s
SetSR $b 1 $false; Step $s; Tick $s; Step $s                            # ScenarioReady withdrawn (hard OFF)
SetSR $b 2 $true; Step $s; Tick $s; Step $s                             # reload: generation 2 -> a second logical request
SetSR $b 3 $true; Step $s; Tick $s; Step $s                             # generation 3
Check 'R02 Pause-like Ticks, soft OFF / ON twice, ScenarioReady withdrawn, two reloads: the process is untouched (alive, Ready, Stop NOT signalled, no kill, still ONE Process.Start) although three logical start requests were logged' ((PidAlive $cp) -and ([string](Mg $m 'State') -eq 'Ready') -and ([int](Mg $m 'StopSignalCount') -eq 0) -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ((ELines $log 'APP_START_REQUEST').Count -eq 3) -and ((EventLines $m.Sink 'APP_LAUNCH_SUPPRESSED').Count -eq 2) -and ((EventLines $m.Sink 'APP_STOP_SIGNALLED').Count -eq 0) -and ((ELines $log 'APP_STOP_REQUEST').Count -eq 0) -and ((ObjectExists (StopNameOf $m))))
$sw.Restart()
End $s
$endMs = $sw.ElapsedMilliseconds
End $s
Check ('R03 Dispose of the session: ONE logical stop request, ONE Stop signal, the process leaves by itself with exit code 0 (' + $endMs + ' ms), a second Dispose does nothing') (((ELines $log 'APP_STOP_REQUEST').Count -eq 1) -and ((EventLines $m.Sink 'APP_STOP_SIGNALLED').Count -eq 1) -and (-not (PidAlive $cp)) -and ([int](Mg $m 'ExitCode') -eq 0) -and ((EventLines $m.Sink 'APP_SHUTDOWN_END').Count -eq 1) -and ($endMs -lt 3500))
DisposeBridgeObjs $b

# a session built without a manager (every other test constructor) never starts anything
$fp = 960361
$log = SetLog 'r2.log' $fp
$b = NewBridgeObjs $fp
$rec = New-Object NoticeRecorder
$s0 = $sessT.GetConstructor($npi, $null, [Type[]]@([int], [Action[string]]), $null).Invoke(@($fp, [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')))
$now = [long][Diagnostics.Stopwatch]::GetTimestamp()
$sessT.GetField('started', $npi).SetValue($s0, $true); $sessT.GetField('phase', $npi).SetValue($s0, [Enum]::Parse($phaseT, 'WaitingForBridge')); $sessT.GetField('enabledQpc', $npi).SetValue($s0, $now); $sessT.GetField('absenceStartQpc', $npi).SetValue($s0, $now)
for ($i = 0; $i -lt 10; $i++) { Tick $s0; Step $s0 }
SetSR $b 1 $true; Step $s0; Step $s0; Tick $s0; Step $s0
$none = ($sessT.GetProperty('AppProcess', $npi).GetValue($s0) -eq $null)
End $s0
Check 'R05 a session without a process manager (the offline-test constructors): the start request is only a decision, no APP_LAUNCH / APP_PROCESS line, no process' ($none -and ((ELines $log 'APP_START_REQUEST').Count -eq 1) -and (@(Lines $log | Where-Object { $_ -match ' APP_(LAUNCH|PROCESS|READY|SHUTDOWN|STOP_SIGNALLED)' }).Count -eq 0))
DisposeBridgeObjs $b

# the Ready timeout / stop timeout through the session: Dispose is bounded
SetMode 'ready-ignore-stop'
$fp = 960362
$log = SetLog 'r3.log' $fp
$b = NewBridgeObjs $fp
$m = NewMgr $fp (NewOpts 8000 500 3000)
$s = NewSession $fp $m.Mgr
for ($i = 0; $i -lt 10; $i++) { Tick $s; Step $s }
SetSR $b 1 $true; Step $s; Step $s; Tick $s; Step $s
[void](WaitFor { [string](Mg $m 'State') -eq 'Ready' } 15000)
Track $m
$cp = [int](Mg $m 'AppPid')
$sw = [Diagnostics.Stopwatch]::StartNew()
End $s
$ms = $sw.ElapsedMilliseconds
Check ('R06 a process that ignores Stop: the session''s Dispose returns after ' + $ms + ' ms (grace 500 ms + one Kill), the process is gone, the Caller''s own kernel objects were released before the wait') (($ms -lt 500 + 3000 + 500 + 1500 + 500) -and (-not (PidAlive $cp)) -and (Mg $m 'Killed') -and ((ELines $log 'CALLER_DISPOSE_END').Count -eq 1))
DisposeBridgeObjs $b

# the production device: constructor, monitor thread, Load, Tick, Dispose - with the REAL process id of this PowerShell
SetMode 'ok'
$realPid = $PID
$log = SetLog 'r4.log' $realPid
SetTestPath $cfgPath
WriteCfg (ConfigJson)
$b = NewBridgeObjs $realPid
$dev = [Activator]::CreateInstance($deviceT)
$dev.Load('')
$tickD = [Delegate]::CreateDelegate([Action], $dev, 'Tick')
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt 400) { $tickD.Invoke(); Wait 8 }
SetSR $b 1 $true
$sw.Restart()
$gotReady = $false
while ($sw.ElapsedMilliseconds -lt 15000) { $tickD.Invoke(); if ((ELines $log 'APP_READY').Count -ge 1) { $gotReady = $true; break }; Wait 8 }
$startedPid = 0
$sl = ELines $log 'APP_PROCESS_STARTED'
if ($sl.Count -ge 1) { $startedPid = [int](Field $sl[0] 'appPid'); if (-not $started.Contains($startedPid)) { $started.Add($startedPid) } }
$sw.Restart(); while ($sw.ElapsedMilliseconds -lt 600) { $tickD.Invoke(); Wait 8 }
$alive = PidAlive $startedPid
$t0 = [Diagnostics.Stopwatch]::StartNew()
$dev.Dispose()
$devMs = $t0.ElapsedMilliseconds
$dev.Dispose()
DisposeBridgeObjs $b
Check ('R10 the production device (constructor, monitor thread, Load, Tick, Dispose) with this process''s real PID: the application starts after the first DrivingActive ON, becomes Ready, stays alive while Ticks go on, and the device''s Dispose (' + $devMs + ' ms) stops it with exit code 0; a second Dispose does nothing') ($gotReady -and ($startedPid -gt 0) -and $alive -and (-not (PidAlive $startedPid)) -and ((ELines $log 'APP_STOP_SIGNALLED').Count -eq 1) -and ((ELines $log 'APP_EXITED').Count -eq 1) -and ((ELines $log 'APP_EXITED')[0] -match 'exitCode=0') -and ((ELines $log 'APP_START_REQUEST').Count -eq 1) -and ((ELines $log 'APP_STOP_REQUEST').Count -eq 1))
$lt = Lines $log
$iReq = [array]::FindIndex($lt, [Predicate[string]]{ param($l) $l -match ' APP_STOP_REQUEST ' })
$iSig = [array]::FindIndex($lt, [Predicate[string]]{ param($l) $l -match ' APP_STOP_SIGNALLED ' })
$iExit = [array]::FindIndex($lt, [Predicate[string]]{ param($l) $l -match ' APP_EXITED ' })
$iEnd = [array]::FindIndex($lt, [Predicate[string]]{ param($l) $l -match ' APP_SHUTDOWN_END ' })
$e3Lines = @($lt | Where-Object { $_ -match ' APP_(LAUNCH|PROCESS|READY|STOP_SIGNALLED|EXITED|STREAMS|SHUTDOWN)' })
Check 'R12 order in the shared log at Dispose: APP_STOP_REQUEST (E1 decision) < APP_STOP_SIGNALLED < APP_EXITED < APP_SHUTDOWN_END; every E3 line is Track A, carries the Caller cycle number and the process id of the log, and no line holds a path' (($iReq -ge 0) -and ($iReq -lt $iSig) -and ($iSig -lt $iExit) -and ($iExit -lt $iEnd) -and ($e3Lines.Count -ge 7) -and (@($e3Lines | Where-Object { $_ -notmatch ' T=A ' -or $_ -notmatch ' cycle=\d+ ' -or $_ -notmatch (' P=' + $realPid + ' ') }).Count -eq 0) -and (@($lt | Where-Object { $_ -match '[A-Za-z]:\\' }).Count -eq 0))
Check 'R11 after the device is disposed no monitor thread and no named object of this run is left (Enabled, Stop, App Stop / Ready)' (([int]$sessT.GetField('LiveMonitors', $nps).GetValue($null) -eq 0) -and (-not (ObjectExists ('Local\TSScoringPlugin.v1.' + $realPid + '.Enabled'))) -and (-not (ObjectExists ('Local\TSScoringPlugin.v1.' + $realPid + '.Stop'))))
SetTestPath (Join-Path $fixDir 'no-such-launcher.json')

# ================================================================================================================ I: integration with the E2 child and the real main.py
Write-Host '--- I: integration (E2 managed child, real main.py)'
# The Mackoy resolver is not needed any more. It must go: while it is installed, any cmdlet that loads an assembly (Get-CimInstance below) re-enters it.
[AppDomain]::CurrentDomain.remove_AssemblyResolve($handler)
$qtOk = $false
try { $q = & $py -c "import PyQt6.QtCore" 2>$null; $qtOk = ($LASTEXITCODE -eq 0) } catch { $qtOk = $false }
if ($qtOk -and (Test-Path $e2Child)) {
    SetTestPath $cfgPath
    SetMode 'ok'
    $env:TSS_E2_FAKE = 'ok'
    WriteCfg (ConfigJson @{ scriptPath = $e2Child; workingDirectory = $repoRoot })
    # --owner caller makes the application watch the BVE process it names (parent-exit fix): the stand-in BVE must be a live process, older than the child
    $h = NewMgr $PID (NewOpts 20000 5000 3000)
    [void](Req $h 1 1)
    $rdy = WaitFor { [string](Mg $h 'State') -eq 'Ready' } 25000
    Track $h
    $cp = [int](Mg $h 'AppPid')
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Down $h
    Check ('I01 the E2 managed child (real Qt glue, real Lock / Stop / Ready objects, fake overlay) is started with the exact E2 command line, reports AppReady, and exits with code 0 after Stop in ' + $sw.ElapsedMilliseconds + ' ms') ($rdy -and ([int](Mg $h 'ExitCode') -eq 0) -and (-not (PidAlive $cp)) -and (-not (Mg $h 'Killed')) -and ((EventLines $h.Sink 'APP_STDERR').Count -ge 3) -and ((EventLines $h.Sink 'APP_STDERR')[0] -match 'event=') -and ([int](Mg $h 'StopSignalCount') -eq 1))
    $el = EventLines $h.Sink 'APP_STDERR'
    Check 'I02 the E2 diagnostics ([MANAGED] state-change lines on stderr) reached the Caller log through the redirected stderr (start / ready / stop / exit) and carry no path' ((@($el | Where-Object { $_ -match 'event=ready-published' }).Count -eq 1) -and (@($el | Where-Object { $_ -match 'event=stop-received' }).Count -eq 1) -and (@($el | Where-Object { $_ -match 'event=exit ' }).Count -eq 1) -and (@($el | Where-Object { $_ -match '[A-Za-z]:\\' }).Count -eq 0))
    $env:TSS_E2_FAKE = 'bind-fail'
    $h = NewMgr $PID (NewOpts 20000 5000 3000)
    [void](Req $h 1 1)
    [void](WaitFor { [string](Mg $h 'State') -eq 'Failed' } 25000)
    Track $h
    Check 'I03 the E2 child answers a busy UDP port (fake bind failure) with exit code 2 before Ready: AppFailed udp-bind-failed, no restart' (((EventLines $h.Sink 'APP_EXIT_BEFORE_READY').Count -eq 1) -and ((EventLines $h.Sink 'APP_EXIT_BEFORE_READY')[0] -match 'exitCode=2 exitName=udp-bind-failed') -and ([int](Mg $h 'ProcessStartCount') -eq 1))
    Down $h
    $env:TSS_E2_FAKE = $null
}
else {
    Skip 'I01-I03 need PyQt6 for the interpreter and tests\managed_smoke_child.py'
}
$udpBusy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
$mainRunning = $false
. (Join-Path $PSScriptRoot 'MainProcessGuard.ps1'); $mainRunning = Get-TsScoringMainRunning $mainPy      # only <repo>\main.py counts (another project's main.py is not ours); unknown / relative = safe side
if ($qtOk -and (-not $udpBusy) -and (-not $mainRunning) -and (Test-Path $mainPy)) {
    SetTestPath $cfgPath
    SetMode 'ok'
    WriteCfg (ConfigJson @{ scriptPath = $mainPy; workingDirectory = $repoRoot })
    $h = NewMgr $PID (NewOpts 25000 6000 3000)
    [void](Req $h 1 1)
    $rdy = WaitFor { [string](Mg $h 'State') -eq 'Ready' } 30000
    Track $h
    $cp = [int](Mg $h 'AppPid')
    $udpDuring = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Down $h
    $el = EventLines $h.Sink 'APP_STDERR'
    Check ('I10 the REAL main.py --managed (real Overlay, real UDP bind, hidden) is started by the manager, reports AppReady, binds UDP 54321 while managed, and leaves with exit code 0 after Stop in ' + $sw.ElapsedMilliseconds + ' ms') ($rdy -and $udpDuring -and ([int](Mg $h 'ExitCode') -eq 0) -and (-not (PidAlive $cp)) -and (-not (Mg $h 'Killed')) -and (@($el | Where-Object { $_ -match 'event=ready-published' }).Count -eq 1))
    $udpAfter = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
    Check 'I11 after Dispose UDP 54321 is free again (nothing of the real application remains)' (-not $udpAfter)
}
else {
    Skip ('I10-I11 real main.py: not run (PyQt6=' + $qtOk + ', UDP 54321 busy=' + $udpBusy + ', a main.py process present=' + $mainRunning + ')')
}
}
finally {
    KillStrays
    SetTestPath $null
}

# ================================================================================================================ B: 32-bit
Write-Host '--- B: 32-bit process (BVE5 is a 32-bit process)'
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
SetTestPath $cfgPath
WriteCfg (ConfigJson)
$r64 = RunLifecycle 960380
KillStrays
SetTestPath $null
$a64 = $mgrT.GetMethod('BuildArguments', $nps).Invoke($null, @('X:\a b\main.py', 4242, '0123456789abcdef0123456789abcdef'))
$sum64 = ('PROBE32 ptr=4 cfg=Loaded args=[{0}] {1}' -f $a64, (Summary $r64))
if (Test-Path $ps32) {
    $out = & $ps32 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Root $Root -PythonExe $py -Probe32 -Fixtures $fixDir 2>&1 | Where-Object { $_ -match '^PROBE32' }
    $line32 = (($out -join ''))
    Check ('B01 a 32-bit process (BVE5) starts the 64-bit interpreter, sees AppReady, stops it with exit 0 and logs the same events in the same order as the 64-bit process (' + $line32 + ')') (($line32 -match 'ptr=4') -and ($line32 -ceq $sum64))
}
else {
    Skip 'B01 32-bit PowerShell not available'
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
$mgrSrc = Src 'Caller\src\AppProcessManager.cs'
$cfgSrc = Src 'Caller\src\LauncherConfig.cs'
$hsSrc = Src 'Caller\src\HandshakeSession.cs'
$mgrCode = NoComments $mgrSrc
$hsCode = NoComments $hsSrc
Check 'S01 Process.Start / ProcessStartInfo exist ONLY in AppProcessManager.cs among the Caller sources; no shell, no cmd, no PATH lookup, no Verb, no Environment change' ((@(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { $_.Name -ne 'AppProcessManager.cs' -and ((NoComments (Src ('Caller\src\' + $_.Name))) -match 'Process\.Start|ProcessStartInfo|UseShellExecute') }).Count -eq 0) -and ($mgrCode -match 'UseShellExecute = false') -and ($mgrCode -notmatch 'cmd\.exe|powershell|Verb|EnvironmentVariables|"-I"|Environment\.SetEnvironmentVariable|ShellExecute\(|WaitForInputIdle'))
Check 'S02 Process.Start appears exactly once in the manager, inside its worker (not on the monitor thread, not in a Tick path)' (([regex]::Matches($mgrCode, 'process\.Start\(\)')).Count -eq 1)
Check 'S03 the monitor-thread entry (RequestStart) has no file, process, wait or sleep; Shutdown is called from End() AFTER the gate is released and from nowhere else' ((([regex]::Match($mgrCode, 'public AppLaunchDecision RequestStart[\s\S]*?\n        \}\n').Value) -notmatch 'File|Process\.|WaitOne|Sleep|Join|Load\(|Directory') -and (([regex]::Matches($hsCode, 'ShutdownAppProcess\(\)')).Count -eq 2) -and ($hsSrc -match 'CALLER_DISPOSE_END", string\.Empty\);\s*\}\s*\n\s*ShutdownAppProcess\(\);'))
Check 'S04 the Tick path is untouched: NotifyTick() and the device Tick() / Dispose() / Load() name no process, manager, launcher or log' (((([regex]::Match($hsCode, 'public void NotifyTick\(\)[\s\S]*?\n        \}\n').Value) -notmatch 'appProcess|AppProcess|Launcher|Process')) -and ((NoComments (Src 'Caller\src\TsScoringCallerInputDevice.cs')) -notmatch 'AppProcess|Launcher|Process\.Start'))
Check 'S05 every wait is finite: no WaitOne() / WaitForExit() / Join() / Thread.Sleep without a number or a variable limit in the manager' (($mgrCode -notmatch 'WaitOne\(\)|WaitForExit\(\)|Join\(\)|Timeout\.Infinite|INFINITE') -and ($mgrCode -match 'w\.Join\(options\.ShutdownJoinMs\)') -and ($mgrCode -match 'process\.WaitForExit\(options\.StopGraceMs\)') -and ($mgrCode -match 'process\.WaitForExit\(options\.KillWaitMs\)'))
Check 'S06 the Stop event is set only in SignalStop, which is called from Shutdown (Dispose) and from the Ready-timeout clean-up - nowhere else; no soft / hard OFF, Pause or ScenarioReady path reaches the manager' ((([regex]::Matches($mgrCode, 'stopEvent\.Set\(\)')).Count -eq 1) -and (([regex]::Matches($mgrCode, 'SignalStop\("')).Count -eq 2) -and ($mgrCode -match 'SignalStop\("caller-dispose"\)') -and ($mgrCode -match 'SignalStop\("ready-timeout-cleanup"\)') -and (([regex]::Matches($hsCode, 'appProcess\.')).Count -eq 3) -and ($hsCode -match 'appProcess\.PublishStateWithLoad\(session, session && driving\.Active, scenarioGenerationSeen, load \? scenarioLoadInfo : 0u, load\)') -and ($hsCode -match 'appProcess\.RequestStart\(step\.ScenarioGeneration, step\.RequestNumber\)') -and ($hsCode -match 'appProcess\.Shutdown\(\)'))
Check 'S07 Kill: exactly one call, on the Process object this class started, after the Stop grace; no name search, no taskkill, no Stop-Process, no GetProcessesByName, no WMI' (([regex]::Matches($mgrCode, 'process\.Kill\(\)')).Count -eq 1 -and ($mgrCode -notmatch 'GetProcessesByName|GetProcesses\(|taskkill|Stop-Process|Win32_Process|ManagementObject|TerminateProcess'))
Check 'S08 the Stop event is created BEFORE Process.Start, with a name that carries the BVE PID and a fresh instance id (Guid "N" = 32 lower-case hex)' (($mgrCode.IndexOf('new EventWaitHandle(false, EventResetMode.ManualReset, AppObjectNames.Stop(') -ge 0) -and ($mgrCode.IndexOf('AppObjectNames.Stop(') -lt $mgrCode.IndexOf('process.Start()')) -and ($mgrCode -match 'Guid\.NewGuid\(\)\.ToString\("N"\)'))
Check 'S09 no restart, back-off, job object, Session / Driving event, HUD, scoring, UDP, hook or registry vocabulary in the Caller sources' ((@(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { (NoComments (Src ('Caller\src\' + $_.Name))) -match 'Backoff|BackOff|Respawn|JobObject|CreateJobObject|SessionEvent|DrivingEvent|UdpClient|Socket|SetWindowsHookEx|RegisterHotKey|Registry|Kickstart|Overlay|\bHUD\b' }).Count -eq 0))
Check 'S10 the launcher reader holds no secret field: the only accepted keys are schemaVersion, mode, pythonExecutable, scriptPath, workingDirectory' (($cfgSrc -match 'key != "schemaVersion" && key != "mode" && key != "pythonExecutable" && key != "scriptPath" && key != "workingDirectory"') -and ((NoComments $cfgSrc) -notmatch '(?i)password|token|apikey|secret'))
Check 'S11 the reasons of the configuration are the only text the log gets from the file (no value, no path is formatted into a log line): the manager logs no config path, no script path, no Python path' (($mgrCode -notmatch 'PythonExecutable|ScriptPath|WorkingDirectory\)?\s*\+|config\.Config\.') -or (($mgrCode -split "`n" | Where-Object { $_ -match 'Log\(' -and $_ -match 'PythonExecutable|ScriptPath|WorkingDirectory' }).Count -eq 0))
Check 'S12 the E1 decision lines are unchanged: APP_START_REQUEST / APP_START_SUPPRESSED / APP_STOP_REQUEST / APP_STOP_NOT_REQUIRED keep their text (dryRun=yes marks the decision record)' (([regex]::Matches($hsSrc, 'ObsA\("APP_(START_REQUEST|START_SUPPRESSED|STOP_REQUEST|STOP_NOT_REQUIRED)", [^\n]*dryRun=yes"\)')).Count -eq 4)
$dllOk = (Test-Path $callerPath)
$vi = (Get-Item $callerPath).VersionInfo
Check 'S13 version 0.12.0.0 (file and assembly), provider Coruge-to, product TS Scoring, description names Phase E4 (the Phase E3 contract is what this file tests; the version moved on); the DLL references only mscorlib, System, System.Core, System.Windows.Forms, Mackoy.IInputDevice' (($vi.FileVersion -eq '0.12.0.0') -and ($callerAsm.GetName().Version.ToString() -eq '0.12.0.0') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.Comments -match 'Phase E4') -and ((($callerAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'Mackoy.IInputDevice,mscorlib,System,System.Core,System.Windows.Forms'))
# repository scope against the Phase E2 commit
# Phase E4: the scope of THIS phase is the E2 -> E3 commit pair (the working tree moves on with Phase E4, which has its own scope test)
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', $E2Commit, $E3Commit)) -split "`n" | Where-Object { $_ })
$untracked = @()
$touched = @($changed + $untracked | Sort-Object -Unique)
$p3 = $prefix
$planned = @(
    'Caller/src/AppProcessManager.cs', 'Caller/src/LauncherConfig.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/AppController.cs', 'Caller/src/AssemblyInfo.cs', 'Caller/TSScoringPlugin.Caller.InputDevice.csproj',
    'Tests/Test-AppProcessE3.ps1', 'Tests/Test-AppControllerE1.ps1', 'Tests/Test-DrivingActiveD1.ps1', 'Tests/Test-DependencyNoticeM1.ps1', 'Tests/Test-ObservationC1.ps1',
    'Tools/Verify-PhaseC3.ps1', 'Tools/Verify-PhaseL1.ps1', 'Docs/Handshake-PhaseE3-ProcessStart.md', 'Docs/launcher.template.json'
) | ForEach-Object { $p3 + $_ }
$planned += @('tests/test_managed_mode_e2.py', 'tests/Test-ManagedModeE2.ps1')
$extra = @($touched | Where-Object { $_ -notin $planned }); $miss = @($planned | Where-Object { $_ -notin $touched })
Check ('S20 only the planned Phase E3 files differ from the Phase E2 commit in the whole repository (' + $touched.Count + ' files; unexpected: [' + ($extra -join ', ') + '])') ($extra.Count -eq 0)
Check 'S21 main.py, managed_mode.py, every other Python module, both Bridges, Shared\*, DrivingActivityState.cs, Class1.cs, the Docs of earlier phases and the plugin projects are byte-identical to the Phase E2 commit' (@($touched | Where-Object { $_ -match '\.py$' -and $_ -notmatch '^tests/test_managed_mode_e2\.py$' }).Count -eq 0 -and @($touched | Where-Object { $_ -match '/Bridge/|/Shared/|DrivingActivityState|Class1\.cs|AtsLoggerPlugin|\.vcxproj|\.slnx|/Docs/Handshake-Phase[A-DL-M]|Handshake-PhaseE1' }).Count -eq 0)
Check 'S22 no build output, DLL, PDB, log, personal launcher.json or EXE among the files of this phase' (@($touched | Where-Object { $_ -match '/out/|/obj/|/dist/|/logs/|build\.log|\.dll$|\.pdb$|\.log$|\.exe$|\.spec$' -or $_ -match '(^|/)launcher\.json$' }).Count -eq 0)
$tmplPath = Join-Path $Root 'Docs\launcher.template.json'
$tmpl = if (Test-Path $tmplPath) { [IO.File]::ReadAllText($tmplPath) } else { '' }
Check 'S23 the committed template holds placeholders only: no drive letter of this machine, no user name, no real path; it is refused by the loader as written (placeholders do not exist)' (($tmpl.Length -gt 0) -and ($tmpl -match '<') -and ($tmpl -notmatch 'Users|Documents|Scoring-Feature|Program Files') -and ((LoadBytes ([Text.Encoding]::UTF8.GetBytes($tmpl))).Status -eq 'Invalid'))
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$privFiles = @(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs) + @(Get-Item $callerPath) + @(Get-Item (Join-Path $Root 'Caller\TSScoringPlugin.Caller.InputDevice.csproj'))
foreach ($rel in 'Docs\Handshake-PhaseE3-ProcessStart.md', 'Docs\launcher.template.json') { if (Test-Path (Join-Path $Root $rel)) { $privFiles += @(Get-Item (Join-Path $Root $rel)) } }
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
Check ('S24 no personal path, user name, machine name or e-mail in the Caller sources, project, DLL, document, template (' + $privFiles.Count + ' files, matches=' + $privHits + '), the produced test logs (matches=' + $logHits + ') or this test (matches=' + $selfHits + ')') (($privHits -eq 0) -and ($selfHits -eq 0) -and ($logHits -eq 0))
Check 'S25 no PDB anywhere, dist holds exactly the Caller and the Current Bridge DLL, and no python / cmd process started by this test is left' ((@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0) -and ((@(Get-ChildItem (Join-Path $Root 'dist') -File | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'TSScoringPlugin.BveEx.Bridge.Prototype.dll,TSScoringPlugin.Caller.InputDevice.dll') -and (@($started | Where-Object { PidAlive $_ }).Count -eq 0))

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}  SKIPPED {2}" -f $results.Count, $failed.Count, $script:skips
if ($failed.Count -gt 0) { $failed | ForEach-Object { 'FAILED: ' + $_.Name }; exit 1 }
