# PHASE E2 - Windows PowerShell 5.1 integration test of the Python managed mode (main.py --managed).
# PowerShell plays the future Caller: it creates the Stop event, starts Python by hand, watches the Ready event and sets Stop.
# No BVE, no BveEX, no Caller DLL. The fake-Overlay helper (tests\managed_smoke_child.py) is used for the success path so a running TS Scoring
# (UDP port 54321) is never disturbed; the real main.py is used for argument errors and, when the port is free, for the full path.
# ASCII-only on purpose. Usage: powershell -NoProfile -File tests\Test-ManagedModeE2.ps1 [-PythonExe C:\Python314\python.exe]
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$PythonExe = 'C:\Python314\python.exe',
    [string]$Baseline = 'a43f18efca37caf64d33bb7c7d5529efd5b7067b'
)
$ErrorActionPreference = 'Stop'
$script:fail = 0
$script:pass = 0
function Check([string]$name, [bool]$ok, [string]$detail = '') {
    if ($ok) { $script:pass++; Write-Host ("PASS  " + $name) } else { $script:fail++; Write-Host ("FAIL  " + $name + "  " + $detail) }
}

if (-not (Test-Path $PythonExe)) { Write-Host "INCONCLUSIVE: python not found: $PythonExe"; exit 2 }
$child = Join-Path $Root 'tests\managed_smoke_child.py'
$mainPy = Join-Path $Root 'main.py'
$pidFake = 777002

function NewInst { [guid]::NewGuid().ToString('N') }
function Nm([int]$bvePid, [string]$inst, [string]$kind) { "Local\TSScoringPlugin.v1.$bvePid.App.$inst.$kind" }
function NewStop([int]$bvePid, [string]$inst) {
    New-Object System.Threading.EventWaitHandle($false, [System.Threading.EventResetMode]::ManualReset, (Nm $bvePid $inst 'Stop'))
}
function ReadyState([int]$bvePid, [string]$inst) {
    # 'absent' | 'unset' | 'set'
    $h = $null
    try { $h = [System.Threading.EventWaitHandle]::OpenExisting((Nm $bvePid $inst 'Ready')) } catch { return 'absent' }
    try { if ($h.WaitOne(0)) { return 'set' } else { return 'unset' } } finally { $h.Dispose() }
}
function WaitReady([int]$bvePid, [string]$inst, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { if ((ReadyState $bvePid $inst) -eq 'set') { return $true }; Start-Sleep -Milliseconds 25 }
    return $false
}
function StartPy([string]$script, [string[]]$pyArgs, [hashtable]$env) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonExe
    $psi.Arguments = ('"' + $script + '" ' + ($pyArgs -join ' '))
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    if ($env) { foreach ($k in $env.Keys) { $psi.EnvironmentVariables[$k] = $env[$k] } }
    $p = [System.Diagnostics.Process]::Start($psi)
    $errTask = $p.StandardError.ReadToEndAsync()
    return @{ Proc = $p; Err = $errTask }
}
function ManagedArgs([int]$bvePid, [string]$inst) { @('--managed', '--owner', 'ps-test', '--bve-pid', "$bvePid", '--instance', $inst) }
function Finish($run, [int]$ms) {
    if (-not $run.Proc.WaitForExit($ms)) { $run.Proc.Kill(); $run.Proc.WaitForExit(); return @{ Code = -999; Err = 'timeout' } }
    return @{ Code = $run.Proc.ExitCode; Err = $run.Err.Result }
}
function PortFree {
    $s = New-Object System.Net.Sockets.Socket([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp)
    try { $s.Bind((New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Loopback, 54321))); return $true } catch { return $false } finally { $s.Close() }
}

Write-Host ("PowerShell " + $PSVersionTable.PSVersion + " / python " + (& $PythonExe -c "import sys;print(sys.version.split()[0])"))

# 1. Ready -> Stop -> exit 0 within 3 s, Ready withdrawn
$inst = NewInst; $stop = NewStop $pidFake $inst
Check 'no Ready before launch' ((ReadyState $pidFake $inst) -eq 'absent')
$run = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = 'ok' }
Check 'Ready published' (WaitReady $pidFake $inst 20000)
$sw = [Diagnostics.Stopwatch]::StartNew(); [void]$stop.Set()
$r = Finish $run 3000
Check 'stop request -> exit 0' ($r.Code -eq 0) ("code=" + $r.Code + " " + $r.Err)
Check 'stop request -> exit within 3 s' ($sw.ElapsedMilliseconds -lt 3000) ("ms=" + $sw.ElapsedMilliseconds)
Check 'Ready withdrawn after exit' ((ReadyState $pidFake $inst) -ne 'set')
Check 'exit diagnostics carry reason' ($r.Err -match 'event=exit' -and $r.Err -match 'reason=stop-requested' -and $r.Err -match 'code=0')
$stop.Dispose()

# 2. Stop of another instance / another BVE pid is ignored; stale Stop of an old instance is not received
$inst = NewInst; $stop = NewStop $pidFake $inst
$other = NewStop $pidFake (NewInst); [void]$other.Set()
$otherPid = NewStop ($pidFake + 1) $inst; [void]$otherPid.Set()
$run = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = 'ok' }
Check 'Ready published with foreign / stale Stop events around' (WaitReady $pidFake $inst 20000)
Start-Sleep -Milliseconds 600
Check 'foreign and stale Stop ignored (still running, Ready set)' ((-not $run.Proc.HasExited) -and ((ReadyState $pidFake $inst) -eq 'set'))
[void]$stop.Set(); [void]$stop.Set()
$r = Finish $run 3000
Check 'own Stop (set twice) -> exit 0' ($r.Code -eq 0) ("code=" + $r.Code)
$stop.Dispose(); $other.Dispose(); $otherPid.Dispose()

# 3. duplicate instance -> 3 without touching the first Ready
$inst = NewInst; $stop = NewStop $pidFake $inst
$first = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = 'ok' }
Check 'first instance Ready' (WaitReady $pidFake $inst 20000)
$second = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = 'ok' }
$r2 = Finish $second 20000
Check 'duplicate instance -> exit 3' ($r2.Code -eq 3) ("code=" + $r2.Code + " " + $r2.Err)
Check 'duplicate left the first Ready set' ((ReadyState $pidFake $inst) -eq 'set')
[void]$stop.Set()
$r = Finish $first 3000
Check 'first instance still stops with 0' ($r.Code -eq 0)
$stop.Dispose()

# 4. contract object missing / init failures / bind failure / exception
$inst = NewInst
$run = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = 'ok' }
$r = Finish $run 20000
Check 'Stop event missing -> exit 4, no Ready' ($r.Code -eq 4 -and $r.Err -notmatch 'ready-published' -and (ReadyState $pidFake $inst) -ne 'set') ("code=" + $r.Code)
foreach ($case in @(@('bind-fail', 2), @('raise-in-init', 4), @('raise-after-ready', 1))) {
    $inst = NewInst; $stop = NewStop $pidFake $inst
    $run = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = $case[0] }
    $r = Finish $run 20000
    Check ("mode " + $case[0] + " -> exit " + $case[1] + ", Ready not left") ($r.Code -eq $case[1] -and (ReadyState $pidFake $inst) -ne 'set') ("code=" + $r.Code + " " + $r.Err)
    $stop.Dispose()
}

# 5. stop requested before the launch: exits 0 and never publishes Ready
$inst = NewInst; $stop = NewStop $pidFake $inst; [void]$stop.Set()
$run = StartPy $child (ManagedArgs $pidFake $inst) @{ TSS_E2_FAKE = 'ok' }
$r = Finish $run 20000
Check 'pre-set Stop -> exit 0 without Ready' ($r.Code -eq 0 -and $r.Err -notmatch 'ready-published') ("code=" + $r.Code)
$stop.Dispose()

# 6. real main.py: argument errors -> 5 ; managed start -> full path when the UDP port is free, otherwise exit 2
foreach ($bad in @(@('--managed'), @('--managed', '--owner', 'ps-test', '--bve-pid', '0', '--instance', (NewInst)), @('--managed', '--owner', 'ps-test', '--bve-pid', '5', '--instance', 'NOT-HEX'))) {
    $run = StartPy $mainPy $bad $null
    $r = Finish $run 30000
    Check ("main.py invalid arguments -> exit 5 (" + ($bad -join ' ').Substring(0, [Math]::Min(30, ($bad -join ' ').Length)) + ")") ($r.Code -eq 5 -and $r.Err -match 'args-invalid') ("code=" + $r.Code)
}
$free = PortFree
$inst = NewInst; $stop = NewStop $pidFake $inst
$run = StartPy $mainPy (ManagedArgs $pidFake $inst) $null
if ($free) {
    Check 'real main.py managed: Ready published' (WaitReady $pidFake $inst 30000)
    [void]$stop.Set()
    $r = Finish $run 5000
    Check 'real main.py managed: Stop -> exit 0' ($r.Code -eq 0) ("code=" + $r.Code + " " + $r.Err)
} else {
    $r = Finish $run 30000
    Check 'real main.py managed: UDP port busy -> exit 2, no Ready (success path INCONCLUSIVE)' ($r.Code -eq 2 -and (ReadyState $pidFake $inst) -ne 'set') ("code=" + $r.Code)
}
$stop.Dispose()

# 7. Caller / Bridge / DLL unchanged against the baseline; no Process.Start in the Caller
Push-Location $Root
try {
    # Phase E3: the working tree moves on, so the Phase E2 COMMIT is what is compared
    $e2 = '6d20650395262e62c10916a4bdb0653947149a8a'
    $changed = @(git diff --name-only $Baseline $e2 -- TsScoringPlugin)
    Check 'TsScoringPlugin (Caller, Bridge, DLL) identical to baseline in the E2 commit' ($changed.Count -eq 0) ($changed -join ',')
    $hit = @(git grep -n -E 'Process\.Start|ProcessStartInfo' $e2 -- 'TsScoringPlugin/Handshake/Caller/src')
    Check 'Process.Start not introduced in the Caller (E2 commit)' ($hit.Count -eq 0)
} finally { Pop-Location }

Write-Host ("RESULT pass=" + $script:pass + " fail=" + $script:fail)
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
