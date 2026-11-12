# INITIAL-DEFAULTS Commit 2 - offline tests of the Caller's Properties entry (InitialDefaultsLauncher.cs, TsScoringCallerInputDevice.Configure).
# What is tested: the launcher.json contract is the ONLY source of the start (python / script / working directory), the exact command line (--initial-defaults, quoted script path, Unicode and
# space paths), the working directory, no redirected pipes and no console window, one window at a time (a second request while the child lives starts nothing), a new start after the child exited,
# every failure (no launcher.json, invalid launcher.json, python missing, start error) is a short result (never an exception), the Properties callback returns at once (it never waits for the
# child), a failed start falls back to the status notice, and a started window shows no notice. No BVE, no BveEX, no MessageBox (the notice is recorded by a hook), no real Python application:
# the child is a small stdlib-only script written to a private folder. The user's real launcher.json and the fixed observation log are never touched. This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$CallerDll = '',
    [string]$PythonExe = ''
)

# a compiled resolver (a script block handler overflows the stack when the resolve event is raised re-entrantly)
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

if (-not $CallerDll) { $CallerDll = Join-Path $Root 'dist\TScoring.InputDevice.dll' }
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($CallerDll))
$NS = 'TSScoringPlugin.Handshake.'
$launcherT = $callerAsm.GetType($NS + 'InitialDefaultsLauncher')
$ldrT = $callerAsm.GetType($NS + 'LauncherConfigLoader')
$logT = $callerAsm.GetType($NS + 'ObservationLog')
$deviceT = $callerAsm.GetType($NS + 'TsScoringCallerInputDevice')
$nps = [Reflection.BindingFlags]'NonPublic,Public,Static'
$npi = [Reflection.BindingFlags]'NonPublic,Public,Instance'

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

if ($null -eq $launcherT) {
    Check 'ID2-RED: the type InitialDefaultsLauncher exists in the Caller' $false
    Write-Output ('RESULT: FAIL  pass=0 fail=1  (the Caller has no InitialDefaultsLauncher)')
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

function WaitFor([scriptblock]$cond, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { if (& $cond) { return $true }; Start-Sleep -Milliseconds 20 }
    return [bool](& $cond)
}
function SetTestPath([string]$p) { $ldrT.GetProperty('TestPath', $nps).SetValue($null, $p) }
function Launch { return $launcherT.GetMethod('TryLaunch', $nps).Invoke($null, @()) }
function Field($o, [string]$n) { return $o.GetType().GetField($n, [Reflection.BindingFlags]'Public,NonPublic,Instance').GetValue($o) }
function PidAlive([int]$p) { return [bool](Get-Process -Id $p -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------- fixtures (a Unicode name with a space on purpose)
$u = ([string][char]0x65E5 + [char]0x672C + [char]0x8A9E)
$fix = Join-Path ([IO.Path]::GetTempPath()) ('id2-launcher-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$work = Join-Path $fix ('work dir ' + $u)
$scriptDir = Join-Path $fix ('script dir ' + $u)
New-Item -ItemType Directory -Force $work, $scriptDir | Out-Null
[string]$script = Join-Path $scriptDir 'stub main.py'
$out = Join-Path $fix 'child.jsonl'
$release = Join-Path $fix 'release.flag'
[IO.File]::WriteAllText($script, @'
import json, os, sys, time
out = os.environ.get("TSS_ID_OUT")
rel = os.environ.get("TSS_ID_RELEASE")
with open(out, "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "script": sys.argv[0], "cwd": os.getcwd(), "pid": os.getpid()}) + "\n")
t0 = time.time()
while not os.path.exists(rel) and time.time() - t0 < 40:
    time.sleep(0.05)
'@, (New-Object Text.UTF8Encoding($false)))
$env:TSS_ID_OUT = $out
$env:TSS_ID_RELEASE = $release
$cfgPath = Join-Path $fix 'launcher.json'
function WriteConfig([string]$python, [string]$scriptPath, [string]$cwd) {
    $obj = [ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $python; scriptPath = $scriptPath; workingDirectory = $cwd }
    [IO.File]::WriteAllBytes($cfgPath, (New-Object Text.UTF8Encoding($false)).GetBytes(($obj | ConvertTo-Json)))
}
function Records { if (Test-Path $out) { return , @(Get-Content $out -Encoding UTF8 | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }) } else { return , @() } }
function Release { New-Item -ItemType File -Force $release | Out-Null }
function Rearm { Remove-Item $release -Force -ErrorAction SilentlyContinue }

$logT.GetProperty('TestPath', $nps).SetValue($null, (Join-Path $fix 'observation.log'))
$logT.GetProperty('TestPid', $nps).SetValue($null, 4242)

try {
    $ErrorActionPreference = 'Stop'
    # ---------------------------------------------------------------- the command line
    $args1 = $launcherT.GetMethod('BuildArguments', $nps).Invoke($null, @([string]$script))
    Check 'the arguments are the quoted script path and --initial-defaults only' ($args1 -ceq ('"' + $script + '" --initial-defaults'))
    Check 'no managed-mode argument is passed' (($args1 -notmatch '--managed') -and ($args1 -notmatch '--owner') -and ($args1 -notmatch '--bve-pid'))
    Check 'the argument constant is --initial-defaults' ($launcherT.GetField('Argument', $nps).GetValue($null) -ceq '--initial-defaults')

    # ---------------------------------------------------------------- a started window
    SetTestPath $cfgPath
    WriteConfig $py $script $work
    Rearm
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r1 = Launch
    $elapsed = $sw.ElapsedMilliseconds
    Check 'the first request starts the window' ([bool](Field $r1 'Started'))
    Check 'the request returns at once (does not wait for the child)' ($elapsed -lt 3000)
    Check 'the child received the script and the flag, with a Unicode / space path' (WaitFor { (Records).Count -ge 1 } 8000)
    $rec = (Records)[0]
    Check 'the child argv is exactly --initial-defaults' (($rec.argv.Count -eq 1) -and ($rec.argv[0] -ceq '--initial-defaults'))
    Check 'the child script path is the launcher.json scriptPath' ($rec.script -ceq $script)
    Check 'the working directory is the launcher.json workingDirectory' ($rec.cwd -ceq $work)
    $childPid = [int]$rec.pid
    Check 'the child is alive while the window is open' (PidAlive $childPid)

    # ---------------------------------------------------------------- one window at a time
    $r2 = Launch
    Check 'a second request while the window lives is refused (already running)' ((-not [bool](Field $r2 'Started')) -and [bool](Field $r2 'AlreadyRunning'))
    Start-Sleep -Milliseconds 400
    Check 'no second child was started' ((Records).Count -eq 1)
    $r3 = Launch
    Check 'a third request is refused too' ([bool](Field $r3 'AlreadyRunning'))

    # ---------------------------------------------------------------- a new start after the child exited
    Release
    Check 'the child ends after the window is closed' (WaitFor { -not (PidAlive $childPid) } 8000)
    Rearm
    $r4 = Launch
    Check 'after the child exited a new request starts a new window' ([bool](Field $r4 'Started'))
    Check 'the second window is a new process' (WaitFor { (Records).Count -ge 2 } 8000)
    $pid2 = [int](Records)[1].pid
    Check 'the new process has another pid' ($pid2 -ne $childPid)
    Release
    WaitFor { -not (PidAlive $pid2) } 8000 | Out-Null
    Rearm

    # ---------------------------------------------------------------- failures are short results, never exceptions
    $thrown = $false
    $notices = @()
    Remove-Item $cfgPath -Force
    try { $f1 = Launch } catch { $thrown = $true }
    Check 'no launcher.json: not started, a reason, no exception' ((-not $thrown) -and (-not [bool](Field $f1 'Started')) -and (-not [bool](Field $f1 'AlreadyRunning')) -and ([string](Field $f1 'Reason')).Length -gt 0)
    [IO.File]::WriteAllText($cfgPath, '{ broken', (New-Object Text.UTF8Encoding($false)))
    try { $f2 = Launch } catch { $thrown = $true }
    Check 'the reason of an absent launcher.json names the launcher (not a null reference)' (([string](Field $f1 'Reason')) -like 'launcher-*')
    Check 'an invalid launcher.json: not started, a reason, no exception' ((-not $thrown) -and (-not [bool](Field $f2 'Started')) -and ([string](Field $f2 'Reason')).Length -gt 0)
    WriteConfig (Join-Path $fix 'no such python.exe') $script $work
    try { $f3 = Launch } catch { $thrown = $true }
    Check 'the reason of an invalid launcher.json names the launcher' (([string](Field $f2 'Reason')) -like 'launcher-*')
    Check 'a python that does not exist: not started, no exception' ((-not $thrown) -and (-not [bool](Field $f3 'Started')))
    $fakePy = Join-Path $fix 'not python.exe'
    [IO.File]::WriteAllText($fakePy, 'this is not an executable', (New-Object Text.UTF8Encoding($false)))
    WriteConfig $fakePy $script $work
    try { $f4 = Launch } catch { $thrown = $true }
    Check 'a python that exists but can not be started: a start-failed reason, no exception' ((-not $thrown) -and (-not [bool](Field $f4 'Started')) -and (([string](Field $f4 'Reason')) -like 'start-failed*'))
    $noticeMethod = $launcherT.GetMethod('FailureNotice', $nps)
    foreach ($f in @($f1, $f2, $f3, $f4)) {
        $n = [string]$noticeMethod.Invoke($null, @($f))
        $notices += $n
    }
    Check 'every failure notice is short (no stack trace, no long path)' (($notices | Where-Object { $_.Length -le 160 -and $_.Length -gt 0 }).Count -eq 4)
    Check 'a notice never contains the launcher.json folder or a stack trace' (($notices | Where-Object { $_ -match [regex]::Escape($fix) -or $_ -match ' at ' -or $_ -match 'Exception' }).Count -eq 0)
    Check 'no child was started by a failure' ((Records).Count -eq 2)

    # ---------------------------------------------------------------- the Properties callback
    $noticeShown = New-Object System.Collections.Generic.List[string]
    $showProp = $deviceT.GetProperty('ShowNotice', $nps)
    Check 'the device has a notice hook for the fallback (so a test never shows a MessageBox)' ($null -ne $showProp)
    if ($null -ne $showProp) {
        $showProp.SetValue($null, ([Action[IntPtr, string, string]]{ param($h, $t, $c) $noticeShown.Add($t) }))
        $dev = [Activator]::CreateInstance($deviceT)
        $configure = $deviceT.GetMethod('Configure', $npi)
        # failure -> the status notice (one), no exception
        $thrown = $false
        try { $configure.Invoke($dev, @($null)) } catch { $thrown = $true }
        Check 'a failed start falls back to ONE status notice and throws nothing' ((-not $thrown) -and ($noticeShown.Count -eq 1) -and ($noticeShown[0].Length -gt 0))
        # success -> no notice, returns at once
        WriteConfig $py $script $work
        Rearm
        $before = (Records).Count
        $noticeShown.Clear()
        $sw = [Diagnostics.Stopwatch]::StartNew()
        try { $configure.Invoke($dev, @($null)) } catch { $thrown = $true }
        $took = $sw.ElapsedMilliseconds
        Check 'a started window shows no notice and Configure returns at once' ((-not $thrown) -and ($noticeShown.Count -eq 0) -and ($took -lt 3000))
        Check 'Configure started exactly one more child' (WaitFor { (Records).Count -eq ($before + 1) } 8000)
        # already running -> no notice, no second child
        $noticeShown.Clear()
        try { $configure.Invoke($dev, @($null)) } catch { $thrown = $true }
        Start-Sleep -Milliseconds 400
        Check 'a second Properties press shows nothing and starts nothing' ((-not $thrown) -and ($noticeShown.Count -eq 0) -and ((Records).Count -eq ($before + 1)))
        # BVE exit independence: disposing the device neither waits for nor kills the window
        $pid3 = [int](Records)[$before].pid
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $deviceT.GetMethod('Dispose', $npi).Invoke($dev, @()) | Out-Null
        Check 'Dispose does not wait for the window' ($sw.ElapsedMilliseconds -lt 4000)
        Check 'Dispose does not kill the window (it does not depend on the BVE exit)' (PidAlive $pid3)
        Release
        WaitFor { -not (PidAlive $pid3) } 8000 | Out-Null
    }
}
catch {
    Check ('unexpected error: ' + $_.Exception.Message) $false
}
finally {
    Release
    Start-Sleep -Milliseconds 300
    foreach ($r in (Records)) { if (PidAlive ([int]$r.pid)) { try { Stop-Process -Id ([int]$r.pid) -Force -ErrorAction SilentlyContinue } catch { } } }
    SetTestPath $null
    Remove-Item $fix -Recurse -Force -ErrorAction SilentlyContinue
}

$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
Write-Output ('RESULT: {0}  pass={1} fail={2}' -f $(if ($fail -eq 0) { 'PASS' } else { 'FAIL' }), $pass, $fail)
if ($fail -ne 0) { exit 1 }
