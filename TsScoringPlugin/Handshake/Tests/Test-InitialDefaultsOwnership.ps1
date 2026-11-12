# INITIAL-DEFAULTS Stage IO-1 - offline tests of the OWNERSHIP half of the Caller's Properties entry (InitialDefaultsLauncher.cs, InitialDefaultsWindow.cs).
# What is tested (REAL windows, no BVE, no BveEX, no real Python application): the owner information is validated against the pid before it is passed (an HWND of another pid is never passed), it reaches the child
# through the environment while argv stays exactly --initial-defaults, a second Properties press finds the child's window (only the child's own pid), restores it when minimised, re-owns it to the settings dialog in front,
# brings it to the front or flashes it, starts no second process, a window of ANOTHER BVE is neither taken over nor duplicated, a child without a window is handled, every step has its log line, and nothing throws.
# The fake BVE is tests\ownership_fake_bve.py (a helper process that owns real windows); the child is a small stdlib-only stub that creates a real top-level window and holds the same named mutex as the product.
# The user's real launcher.json and the fixed observation log are never touched. This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$CallerDll = '',
    [string]$PythonExe = ''
)

Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class ResolveHelper
{
    public static void Install(string[] dirs)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object s, ResolveEventArgs e)
        {
            string name = e.Name.Split(',')[0];
            foreach (string d in dirs)
            {
                foreach (string ext in new string[] { ".dll", ".DLL" })
                {
                    string p = Path.Combine(d, name + ext);
                    if (File.Exists(p)) { return Assembly.LoadFrom(p); }
                }
            }
            return null;
        };
    }
}
"@
[ResolveHelper]::Install(@((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), (Join-Path $env:PUBLIC 'Documents\BveEx\2.0')))

Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class TestWin
{
    private delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] private static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] private static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    public static int ZIndex(IntPtr target)
    {
        List<IntPtr> order = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr l) { order.Add(h); return true; }, IntPtr.Zero);
        return order.IndexOf(target);
    }
    public static IntPtr FirstVisibleWindowOf(int pid)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr l)
        {
            uint p; GetWindowThreadProcessId(h, out p);
            if ((int)p == pid && IsWindowVisible(h) && found == IntPtr.Zero) { found = h; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static int PidOfWindow(IntPtr h) { uint p; GetWindowThreadProcessId(h, out p); return (int)p; }
    public static int WindowCountOf(int pid)
    {
        int n = 0;
        EnumWindows(delegate(IntPtr h, IntPtr l)
        {
            uint p; GetWindowThreadProcessId(h, out p);
            if ((int)p == pid && IsWindowVisible(h)) { n++; }
            return true;
        }, IntPtr.Zero);
        return n;
    }
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern IntPtr GetLongPtr(IntPtr h, int index);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder text, int max);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    public static long ExStyle(IntPtr h) { return GetLongPtr(h, -20).ToInt64() & 0xFFFFFFFFL; }
    public static long Style(IntPtr h) { return GetLongPtr(h, -16).ToInt64() & 0xFFFFFFFFL; }
    public static string Title(IntPtr h) { System.Text.StringBuilder sb = new System.Text.StringBuilder(256); GetWindowTextW(h, sb, 256); return sb.ToString(); }
    public static void Close(IntPtr h) { PostMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero); }
    public static IntPtr FindTitledWindowOf(int pid, string title)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr l)
        {
            uint p; GetWindowThreadProcessId(h, out p);
            if ((int)p == pid && Title(h) == title && found == IntPtr.Zero) { found = h; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    // a test-side activation like a click on the window: AttachThreadInput to the foreground thread, never an ALT tap
    public static bool Activate(IntPtr target)
    {
        IntPtr fg = GetForegroundWindow();
        uint pidIgnored; uint fgThread = fg == IntPtr.Zero ? 0 : GetWindowThreadProcessId(fg, out pidIgnored);
        uint targetThread = GetWindowThreadProcessId(target, out pidIgnored);
        uint me = GetCurrentThreadId();
        bool a1 = false, a2 = false;
        try
        {
            if (fgThread != 0 && fgThread != me) { a1 = AttachThreadInput(me, fgThread, true); }
            if (targetThread != 0 && targetThread != me && targetThread != fgThread) { a2 = AttachThreadInput(me, targetThread, true); }
            BringWindowToTop(target);
            SetForegroundWindow(target);
        }
        finally
        {
            if (a1) { AttachThreadInput(me, fgThread, false); }
            if (a2) { AttachThreadInput(me, targetThread, false); }
        }
        System.Threading.Thread.Sleep(250);
        return GetForegroundWindow() == target;
    }
}
public class FakeOwnerWindow : System.Windows.Forms.IWin32Window
{
    public IntPtr Handle { get; set; }
}
"@ -ReferencedAssemblies System.Windows.Forms

if (-not $CallerDll) { $CallerDll = Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll' }
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($CallerDll))
$NS = 'TSScoringPlugin.Handshake.'
$launcherT = $callerAsm.GetType($NS + 'InitialDefaultsLauncher')
$winT = $callerAsm.GetType($NS + 'InitialDefaultsWindow')
$ownerT = $callerAsm.GetType($NS + 'InitialDefaultsOwner')
$ldrT = $callerAsm.GetType($NS + 'LauncherConfigLoader')
$logT = $callerAsm.GetType($NS + 'ObservationLog')
$deviceT = $callerAsm.GetType($NS + 'TsScoringCallerInputDevice')
$nps = [Reflection.BindingFlags]'NonPublic,Public,Static'
$npi = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$npField = [Reflection.BindingFlags]'NonPublic,Public,Static,Instance'

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

if ($null -eq $launcherT -or $null -eq $ownerT -or $null -eq $launcherT.GetMethod('TryLaunchOwned', $nps)) {
    Check 'IO1-RED: the Caller has InitialDefaultsOwner and InitialDefaultsLauncher.TryLaunchOwned' $false
    Write-Output ('RESULT: FAIL  pass=0 fail=1  (the Caller has no ownership entry)')
    exit 1
}

function FindPython {
    if ($PythonExe -and (Test-Path $PythonExe)) { return (Resolve-Path $PythonExe).Path }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and ($c.Source -notmatch 'WindowsApps')) { return $c.Source }
    foreach ($cand in 'C:\Python314\python.exe', 'C:\Python313\python.exe', 'C:\Python312\python.exe') { if (Test-Path $cand) { return $cand } }
    return $null
}
[string]$py = FindPython
if (-not $py) { Check 'a python.exe is available for the stub child' $false; exit 1 }
$repoRoot = (Resolve-Path (Join-Path $Root '..\..')).Path
$helper = Join-Path $repoRoot 'tests\ownership_fake_bve.py'
if (-not (Test-Path $helper)) { Check 'the fake-BVE helper tests\ownership_fake_bve.py exists' $false; exit 1 }

function WaitFor([scriptblock]$cond, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { if (& $cond) { return $true }; Start-Sleep -Milliseconds 25 }
    return [bool](& $cond)
}
function PidAlive([int]$p) { return [bool](Get-Process -Id $p -ErrorAction SilentlyContinue) }
function Field($o, [string]$n) { return $o.GetType().GetField($n, [Reflection.BindingFlags]'Public,NonPublic,Instance').GetValue($o) }

# a window of the product (or of another BVE) that is open would make every launch of this test refuse: that is an INCONCLUSIVE environment, not a result
$mutexHeld = $false
try { $mx = [Threading.Mutex]::OpenExisting('Local\TSScoring.InitialDefaults.v1'); $mx.Dispose(); $mutexHeld = $true } catch { }
if ($mutexHeld) { Write-Output 'INCONCLUSIVE: an initial-defaults window is open (the named mutex exists); close it and run again'; exit 2 }

function StartFake([string]$mode) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $py
    $psi.Arguments = '-B "' + $helper + '" ' + $mode
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $proc = [Diagnostics.Process]::Start($psi)
    $line = $proc.StandardOutput.ReadLine()
    $info = $line | ConvertFrom-Json
    return [pscustomobject]@{ Proc = $proc; Pid = [int]$info.pid; Main = [IntPtr][int64]$info.main; Settings = [IntPtr][int64]$info.settings }
}
function FakeCommand($fake, [string]$text) { $fake.Proc.StandardInput.WriteLine($text); $fake.Proc.StandardInput.Flush() }
function NewOwnerObject([int]$bvePid, [IntPtr]$ownerHwnd, [IntPtr]$mainHwnd) {
    $o = [Activator]::CreateInstance($ownerT)
    $ownerT.GetField('BvePid').SetValue($o, $bvePid)
    $ownerT.GetField('OwnerHwnd').SetValue($o, $ownerHwnd)
    $ownerT.GetField('MainHwnd').SetValue($o, $mainHwnd)
    return $o
}
function Resolve3([IntPtr]$cand, [int]$bvePid, [IntPtr]$main) {
    $m = $launcherT.GetMethod('ResolveOwner', $nps, $null, [Type[]]@([IntPtr], [int], [IntPtr]), $null)
    return $m.Invoke($null, @($cand, $bvePid, $main))
}
function Press($owner) { return $launcherT.GetMethod('TryLaunchOwned', $nps).Invoke($null, @($owner)) }

# ---------------------------------------------------------------- fixtures
$fix = Join-Path ([IO.Path]::GetTempPath()) ('io1-owner-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force $fix | Out-Null
[string]$script = Join-Path $fix 'stub main.py'
$out = Join-Path $fix 'child.jsonl'
$release = Join-Path $fix 'release.flag'
$obsLog = Join-Path $fix 'observation.log'
[IO.File]::WriteAllText($script, @'
import ctypes, ctypes.wintypes as wt, json, os, sys, time
u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32")
k.CreateMutexW.restype = ctypes.c_void_p; k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
mutex = k.CreateMutexW(None, 0, "Local\\TSScoring.InitialDefaults.v1")
u.CreateWindowExW.restype = wt.HWND
u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
hwnd = 0
if not os.environ.get("TSS_ID_NOWINDOW"):
    hwnd = int(u.CreateWindowExW(0, "STATIC", "STUB-INITDEF", 0x00CF0000 | 0x10000000, 500, 300, 300, 200, None, None, None, None) or 0)
env = {n: os.environ.get(n) for n in ("TSSCORING_INITDEF_BVE_PID", "TSSCORING_INITDEF_OWNER_HWND", "TSSCORING_INITDEF_BVE_MAIN_HWND")}
with open(os.environ["TSS_ID_OUT"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "pid": os.getpid(), "hwnd": hwnd, "env": env}) + "\n")
rel = os.environ["TSS_ID_RELEASE"]
msg = wt.MSG()
t0 = time.time()
while not os.path.exists(rel) and time.time() - t0 < 90:
    while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        u.DispatchMessageW(ctypes.byref(msg))
    time.sleep(0.03)
'@, (New-Object Text.UTF8Encoding($false)))
$env:TSS_ID_OUT = $out
$env:TSS_ID_RELEASE = $release
Remove-Item Env:TSS_ID_NOWINDOW -ErrorAction SilentlyContinue
$cfgPath = Join-Path $fix 'launcher.json'
$cfgObj = [ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $py; scriptPath = $script; workingDirectory = $fix }
[IO.File]::WriteAllBytes($cfgPath, (New-Object Text.UTF8Encoding($false)).GetBytes(($cfgObj | ConvertTo-Json)))
function Records { if (Test-Path $out) { return , @(Get-Content $out -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }) } else { return , @() } }
function Release { New-Item -ItemType File -Force $release | Out-Null }
function Rearm { Remove-Item $release -Force -ErrorAction SilentlyContinue }
function LogText { if (Test-Path $obsLog) { return [IO.File]::ReadAllText($obsLog) } else { return '' } }

$ldrT.GetProperty('TestPath', $nps).SetValue($null, $cfgPath)
$logT.GetProperty('TestPath', $nps).SetValue($null, $obsLog)
$logT.GetProperty('TestPid', $nps).SetValue($null, 4243)
$runningField = $launcherT.GetField('running', [Reflection.BindingFlags]'NonPublic,Static')
$fakeA = $null
$fakeB = $null
$fakeApp = $null

try {
    $ErrorActionPreference = 'Stop'
    $fakeA = StartFake 'bve'
    $fakeB = StartFake 'bve'
    $fakeApp = StartFake 'app'
    Check 'the fake BVE A, the fake BVE B and the other application have real windows' (($fakeA.Pid -ne $fakeB.Pid) -and ($fakeA.Settings -ne [IntPtr]::Zero) -and ($fakeB.Settings -ne [IntPtr]::Zero) -and ($fakeApp.Main -ne [IntPtr]::Zero))

    # ---------------------------------------------------------------- the owner information is validated against the pid
    $ownerA = Resolve3 $fakeA.Settings $fakeA.Pid $fakeA.Main
    Check 'R9: a valid owner and main window of this pid are accepted' (($null -ne $ownerA) -and ((Field $ownerA 'OwnerHwnd') -eq $fakeA.Settings) -and ((Field $ownerA 'MainHwnd') -eq $fakeA.Main) -and ((Field $ownerA 'BvePid') -eq $fakeA.Pid))
    $mixed = Resolve3 $fakeB.Settings $fakeA.Pid $fakeA.Main
    Check 'R8: an owner HWND of ANOTHER pid is never used (the main window of the right pid remains)' (($null -ne $mixed) -and ((Field $mixed 'OwnerHwnd') -ne $fakeB.Settings) -and ((Field $mixed 'MainHwnd') -eq $fakeA.Main))
    $onlyForeign = Resolve3 $fakeB.Settings $fakeA.Pid $fakeB.Main
    Check 'R8: HWNDs of another pid only: no owner information at all (null), no exception' ($null -eq $onlyForeign)
    $garbage = Resolve3 ([IntPtr]12345) $fakeA.Pid ([IntPtr]0)
    Check 'R9: an invalid HWND and no main window: null, no exception' ($null -eq $garbage)
    $zeroPid = Resolve3 $fakeA.Settings 0 $fakeA.Main
    Check 'R9: pid 0 is refused (null)' ($null -eq $zeroPid)

    # ---------------------------------------------------------------- R1: the first Properties press starts ONE window with the owner information
    Rearm
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    $r1 = Press $ownerA
    Check 'R1: the first press starts the window' ([bool](Field $r1 'Started'))
    Check 'R1: the child started once and has its window' (WaitFor { ((Records).Count -ge 1) -and ((Records)[0].hwnd -ne 0) } 10000)
    $rec1 = (Records)[0]
    $childPid = [int]$rec1.pid
    $childHwnd = [IntPtr][int64]$rec1.hwnd
    Check 'R1: argv of the child is exactly --initial-defaults (the owner travels in the environment)' (($rec1.argv.Count -eq 1) -and ($rec1.argv[0] -ceq '--initial-defaults'))
    Check 'R1: the environment carries the bve pid, the owner HWND and the main HWND (plain decimal numbers)' (($rec1.env.TSSCORING_INITDEF_BVE_PID -ceq [string]$fakeA.Pid) -and ($rec1.env.TSSCORING_INITDEF_OWNER_HWND -ceq [string]([int64]$fakeA.Settings)) -and ($rec1.env.TSSCORING_INITDEF_BVE_MAIN_HWND -ceq [string]([int64]$fakeA.Main)))
    Check 'R1: the log has INITDEF_STARTED and INITDEF_OWNER_SET' (((LogText) -match 'INITDEF_STARTED pid=') -and ((LogText) -match 'INITDEF_OWNER_SET bvePid='))

    # ---------------------------------------------------------------- R4 / R5 / R7: another application in front, then Properties again
    $frontOk = [TestWin]::Activate($fakeApp.Main)
    Check 'harness: the other application is in front of the child window' ($frontOk -and ([TestWin]::ZIndex($fakeApp.Main) -lt [TestWin]::ZIndex($childHwnd)))
    $r2 = Press $ownerA
    $act2 = [string](Field $r2 'Activation')
    Check 'R5: the second press starts nothing (already running) and no second child exists' ((-not [bool](Field $r2 'Started')) -and [bool](Field $r2 'AlreadyRunning') -and ((Records).Count -eq 1))
    Check 'R4/R7: the existing window (same HWND, same pid) is found and brought to the front (Reactivated: the system allowed the test thread, so it must allow the Caller thread)' (($act2 -eq 'Reactivated') -and ([TestWin]::FirstVisibleWindowOf($childPid) -ne [IntPtr]::Zero))
    Check 'R4: the window is in front of the other application after the press' ([bool](WaitFor { [TestWin]::ZIndex($childHwnd) -lt [TestWin]::ZIndex($fakeApp.Main) } 1500))
    Check 'R10: the window was re-owned to the BVE settings dialog in front (a child window that had no owner)' ([TestWin]::GetWindow($childHwnd, 4) -eq $fakeA.Settings)
    Check 'the log has INITDEF_ALREADY_RUNNING, INITDEF_HWND_FOUND, INITDEF_OWNER_REBOUND and REACTIVATED or FLASHED' (((LogText) -match 'INITDEF_ALREADY_RUNNING') -and ((LogText) -match 'INITDEF_HWND_FOUND') -and ((LogText) -match 'INITDEF_OWNER_REBOUND') -and (((LogText) -match 'INITDEF_REACTIVATED') -or ((LogText) -match 'INITDEF_FLASHED')))

    # ---------------------------------------------------------------- the system refuses to bring the window forward: it is flashed, never forced
    $flashSeen = New-Object System.Collections.Generic.List[string]
    $winT.GetProperty('TestForegroundRefused', $nps).SetValue($null, $true)
    $winT.GetProperty('FlashObserver', $nps).SetValue($null, ([Action[IntPtr]]{ param($h) $flashSeen.Add([string][int64]$h) }))
    [TestWin]::Activate($fakeApp.Main) | Out-Null
    $rf = Press $ownerA
    $winT.GetProperty('TestForegroundRefused', $nps).SetValue($null, $false)
    $winT.GetProperty('FlashObserver', $nps).SetValue($null, $null)
    Check 'R4: when the system refuses to bring the window forward the Caller flashes it (activation Flashed, the flashed window is the child window), starts no process' (([string](Field $rf 'Activation') -eq 'Flashed') -and ($flashSeen.Count -eq 1) -and ($flashSeen[0] -ceq [string][int64]$childHwnd) -and ((Records).Count -eq 1) -and ((LogText) -match 'INITDEF_FLASHED'))
    # ---------------------------------------------------------------- R6: minimised window is restored
    [TestWin]::ShowWindow($childHwnd, 6) | Out-Null
    Start-Sleep -Milliseconds 300
    Check 'harness: the window is minimised' ([TestWin]::IsIconic($childHwnd))
    $r3 = Press $ownerA
    Check 'R6: Properties again restores the minimised window' ((-not [TestWin]::IsIconic($childHwnd)) -and ((Records).Count -eq 1) -and ((LogText) -match 'INITDEF_RESTORED'))

    # ---------------------------------------------------------------- R10: the settings dialog is destroyed, a new one is in front
    FakeCommand $fakeA 'destroy-settings'
    Start-Sleep -Milliseconds 400
    FakeCommand $fakeA 'new-settings'
    $newLine = $fakeA.Proc.StandardOutput.ReadLine() | ConvertFrom-Json
    $newSettings = [IntPtr][int64]$newLine.settings
    $ownerA2 = Resolve3 $newSettings $fakeA.Pid $fakeA.Main
    $r4 = Press $ownerA2
    Check 'R10: after the settings dialog was replaced, the next press re-owns the window to the new dialog' (([TestWin]::GetWindow($childHwnd, 4) -eq $newSettings) -and ((Records).Count -eq 1))

    # ---------------------------------------------------------------- R8: a window of ANOTHER BVE is neither taken over nor duplicated
    $ownerB = Resolve3 $fakeB.Settings $fakeB.Pid $fakeB.Main
    $savedRunning = $runningField.GetValue($null)
    $runningField.SetValue($null, $null)                                         # what a second BVE (its own Caller, its own static) sees: no child of its own
    $ownerBefore = [TestWin]::GetWindow($childHwnd, 4)
    $r5 = Press $ownerB
    $runningField.SetValue($null, $savedRunning)
    Check 'R8: a second BVE starts no second window (already running / foreign rejected) and starts no process' ((-not [bool](Field $r5 'Started')) -and [bool](Field $r5 'AlreadyRunning') -and ([string](Field $r5 'Activation') -eq 'ForeignRejected') -and ((Records).Count -eq 1))
    Check 'R8: the window of the first BVE keeps its owner (the second BVE did not take it over)' ([TestWin]::GetWindow($childHwnd, 4) -eq $ownerBefore)
    Check 'R8: the log has INITDEF_FOREIGN_BVE_REJECTED' ((LogText) -match 'INITDEF_FOREIGN_BVE_REJECTED')
    $activateM = $callerAsm.GetType($NS + 'InitialDefaultsWindow').GetMethod('ActivateExisting', $nps)
    $foreignAct = $activateM.Invoke($null, @($savedRunning, $fakeA.Pid, $ownerB))
    Check 'R8: ActivateExisting with the owner information of another pid is rejected and touches nothing' (([string]$foreignAct -eq 'ForeignRejected') -and ([TestWin]::GetWindow($childHwnd, 4) -eq $ownerBefore))

    # ---------------------------------------------------------------- the child ends: one log line, a new press starts a new window
    Release
    Check 'the child ends after the window is closed' (WaitFor { -not (PidAlive $childPid) } 10000)
    Check 'the log has INITDEF_EXITED' (WaitFor { (LogText) -match 'INITDEF_EXITED pid=' } 5000)
    Rearm
    $env:TSS_ID_NOWINDOW = '1'
    $r6 = Press $ownerA2
    Check 'R7: a new press after the exit starts a new child (here without a window)' ([bool](Field $r6 'Started') -and (WaitFor { (Records).Count -ge 2 } 10000))
    $childPid2 = [int](Records)[1].pid
    $r7 = Press $ownerA2
    Check 'R7: a child that has no window: already running, activation NoWindow, no exception, no process' ((-not [bool](Field $r7 'Started')) -and [bool](Field $r7 'AlreadyRunning') -and ([string](Field $r7 'Activation') -eq 'NoWindow') -and ((Records).Count -eq 2))
    Check 'the log has INITDEF_NO_WINDOW' ((LogText) -match 'INITDEF_NO_WINDOW')
    Release
    WaitFor { -not (PidAlive $childPid2) } 10000 | Out-Null
    Remove-Item Env:TSS_ID_NOWINDOW -ErrorAction SilentlyContinue
    Rearm

    # ---------------------------------------------------------------- no owner information (an invalid owner): the window is still started, as before this stage
    $noOwner = Press $null
    Check 'an unusable owner (null) still starts the window (no owner in the environment)' ([bool](Field $noOwner 'Started') -and (WaitFor { (Records).Count -ge 3 } 10000))
    $rec3 = (Records)[2]
    Check 'no owner information: the environment carries none of the three values' (($null -eq $rec3.env.TSSCORING_INITDEF_BVE_PID) -and ($null -eq $rec3.env.TSSCORING_INITDEF_OWNER_HWND) -and ($null -eq $rec3.env.TSSCORING_INITDEF_BVE_MAIN_HWND))
    Release
    WaitFor { -not (PidAlive ([int]$rec3.pid)) } 10000 | Out-Null
    Rearm

    # ---------------------------------------------------------------- R13 with the REAL product (real Qt dialog) started by the REAL Caller code (owner ruling 2026-11-12: standard owned-window behaviour, no taskbar button, minimise, re-press restores the SAME window)
    $titleChars = [char[]](0x521D, 0x671F, 0x5024, 0x8A2D, 0x5B9A)
    $dialogTitle = -join $titleChars
    $realCfgPath = Join-Path $fix 'launcher-real.json'
    $realCfg = [ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $py; scriptPath = (Join-Path $repoRoot 'main.py'); workingDirectory = $repoRoot }
    [IO.File]::WriteAllBytes($realCfgPath, (New-Object Text.UTF8Encoding($false)).GetBytes(($realCfg | ConvertTo-Json)))
    $profileDir = Join-Path $fix 'profile'
    New-Item -ItemType Directory -Force $profileDir | Out-Null
    $ldrT.GetProperty('TestPath', $nps).SetValue($null, $realCfgPath)
    $savedLocal = $env:LOCALAPPDATA
    $env:LOCALAPPDATA = $profileDir
    try { $rr1 = Press $ownerA } finally { $env:LOCALAPPDATA = $savedLocal }
    $realChild = $runningField.GetValue($null)
    $realPid = $(if ($null -ne $realChild) { [int]$realChild.Id } else { 0 })
    $realWin = [IntPtr]::Zero
    if ($realPid -ne 0) { [void](WaitFor { $script:realWin = [TestWin]::FindTitledWindowOf($realPid, $dialogTitle); $script:realWin -ne [IntPtr]::Zero } 25000) }
    Check 'R13 real product: the Caller started the real initial-defaults dialog (one window with the dialog title)' (([bool](Field $rr1 'Started')) -and ($realWin -ne [IntPtr]::Zero))
    function CountInitDefaultsProcesses { return @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*--initial-defaults*' -and $_.CommandLine -like ('*' + $repoRoot + '*') }).Count }
    if ($realWin -ne [IntPtr]::Zero) {
        $ex = [TestWin]::ExStyle($realWin); $st = [TestWin]::Style($realWin)
        Check 'R13-D real product: owned by the BVE settings dialog of the announced BVE pid' ([TestWin]::GetWindow($realWin, 4) -eq $fakeA.Settings)
        Check 'R13-A/B/C real product: no WS_EX_APPWINDOW, no WS_EX_TOOLWINDOW (owned window standard behaviour: no own taskbar button, no Alt+Tab entry)' ((($ex -band 0x40000) -eq 0) -and (($ex -band 0x80) -eq 0))
        Check 'R13-E real product: not global top-most; the standard title bar and close button remain' ((($ex -band 0x8) -eq 0) -and (($st -band 0x00C00000) -eq 0x00C00000) -and (($st -band 0x00080000) -ne 0))
        Check 'R13-I real product: exactly one initial-defaults python process' ((CountInitDefaultsProcesses) -eq 1)
        [TestWin]::ShowWindow($realWin, 6) | Out-Null
        [void](WaitFor { [TestWin]::IsIconic($realWin) } 3000)
        Check 'R13-H real product: minimised - the process lives, the HWND is valid, still one process, still owned' ([TestWin]::IsIconic($realWin) -and (PidAlive $realPid) -and ([TestWin]::PidOfWindow($realWin) -eq $realPid) -and ((CountInitDefaultsProcesses) -eq 1) -and ([TestWin]::GetWindow($realWin, 4) -eq $fakeA.Settings))
        [TestWin]::Activate($fakeApp.Main) | Out-Null
        $rr2 = Press $ownerA
        Check 'R13-G/H real product: Properties again restores the minimised window (SW_RESTORE) and brings it back - same HWND, same pid' (([string](Field $rr2 'Activation') -eq 'Reactivated') -and (-not [TestWin]::IsIconic($realWin)) -and ([TestWin]::PidOfWindow($realWin) -eq $realPid) -and ([TestWin]::FindTitledWindowOf($realPid, $dialogTitle) -eq $realWin))
        Check 'R13-I real product: the second press started nothing (still exactly one python process, no new dialog)' ((-not [bool](Field $rr2 'Started')) -and [bool](Field $rr2 'AlreadyRunning') -and ((CountInitDefaultsProcesses) -eq 1))
        Check 'R13-A real product: restoring did not add an extended style or change the owner' ((([TestWin]::ExStyle($realWin) -band 0x40000) -eq 0) -and ([TestWin]::GetWindow($realWin, 4) -eq $fakeA.Settings))
        [TestWin]::Close($realWin)
        Check 'R13 real product: closing the dialog ends the process (exit code 0) and leaves no process' ((WaitFor { -not (PidAlive $realPid) } 10000) -and ((CountInitDefaultsProcesses) -eq 0))
    }
    elseif ($realPid -ne 0) { Stop-Process -Id $realPid -Force -ErrorAction SilentlyContinue }
    Check 'R13 real product: nothing was saved by the test (temporary profile only)' (-not (Test-Path (Join-Path $profileDir 'Coruge-to\TS Scoring\initial-defaults.json')))
    $ldrT.GetProperty('TestPath', $nps).SetValue($null, $cfgPath)
    # ---------------------------------------------------------------- Configure never throws (the owner object is an IWin32Window with a handle of another pid)
    $showProp = $deviceT.GetProperty('ShowNotice', $nps)
    $noticeShown = New-Object System.Collections.Generic.List[string]
    $showProp.SetValue($null, ([Action[IntPtr, string, string]]{ param($h, $t, $c) $noticeShown.Add($t) }))
    $dev = [Activator]::CreateInstance($deviceT)
    $fo = New-Object FakeOwnerWindow
    $fo.Handle = $fakeB.Settings
    $thrown = $false
    $before = (Records).Count
    $why = ''
    try { $deviceT.GetMethod('Configure', $npi).Invoke($dev, [object[]]@($fo.PSObject.BaseObject)) } catch { $thrown = $true; $why = $_.Exception.Message }
    Check 'Configure with an owner window of another pid throws nothing and starts the window without that owner' ((-not $thrown) -and ($noticeShown.Count -eq 0) -and (WaitFor { (Records).Count -eq ($before + 1) } 10000))
    $recC = (Records)[$before]
    Check 'Configure never passes an HWND of another pid' (($recC.env.TSSCORING_INITDEF_OWNER_HWND -ne [string]([int64]$fakeB.Settings)))
    $deviceT.GetMethod('Dispose', $npi).Invoke($dev, @()) | Out-Null
    Release
    WaitFor { -not (PidAlive ([int]$recC.pid)) } 10000 | Out-Null
}
catch {
    Check ('unexpected error: ' + $_.Exception.Message) $false
}
finally {
    Release
    Start-Sleep -Milliseconds 300
    foreach ($r in (Records)) { if (PidAlive ([int]$r.pid)) { try { Stop-Process -Id ([int]$r.pid) -Force -ErrorAction SilentlyContinue } catch { } } }
    foreach ($f in @($fakeA, $fakeB, $fakeApp)) { if ($null -ne $f) { try { if (-not $f.Proc.HasExited) { $f.Proc.Kill() } } catch { } } }
    $ldrT.GetProperty('TestPath', $nps).SetValue($null, $null)
    Remove-Item $fix -Recurse -Force -ErrorAction SilentlyContinue
}

$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
Write-Output ('RESULT: {0}  pass={1} fail={2}' -f $(if ($fail -eq 0) { 'PASS' } else { 'FAIL' }), $pass, $fail)
if ($fail -ne 0) { exit 1 }
