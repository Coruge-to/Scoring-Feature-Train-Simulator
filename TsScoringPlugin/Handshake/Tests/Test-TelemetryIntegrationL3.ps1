# PHASE L3 - INTEGRATION test: pseudo Legacy API -> Legacy telemetry sender (the real DLL's core, the real UDP sink) -> UDP 127.0.0.1:54321 -> the REAL
# main.py --managed (real Python, real Overlay, real UDP bind) started by the REAL Caller code (HandshakeSession / AppProcessManager, Session and Driving
# state) for a stand-in BVE window. What is proven end to end: the HUD stays hidden although Session and Driving are ON until real telemetry of the
# generation arrives; it is shown on the same Overlay window; a new generation hides it until the new scenario's telemetry; telemetry of an old scenario
# instance is ignored; Session OFF hides it whatever arrives; the AVAIL of the sender reaches the application; Stop -> exit code 0, nothing left behind.
# No BVE, no BveEX, no AtsEX runtime. The only network traffic is loopback to 54321, and only when that port is free and no main.py runs (the user's own
# running TS Scoring is never touched). The application's debug log (Desktop) is redirected to a private folder through USERPROFILE for the processes started
# here. The user's launcher.json is never read (LauncherConfigLoader.TestPath). This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$PythonExe = '',
    [string]$Phase = 'L3'      # 'LI1': the sender also writes the handle group and the pressures (Phase LI1); the rest of the chain is the same
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

$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$withInput = ($Phase -eq 'LI1')
$testDir = Join-Path $Root ($(if ($withInput) { 'logs\li1-integration' } else { 'logs\l3-integration' }))
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null
$sandbox = Join-Path $testDir 'profile'
New-Item -ItemType Directory -Force (Join-Path $sandbox 'Desktop') | Out-Null

# the telemetry DLL (copied) and the fixture (compiled into an assembly that may see the internals)
$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item (Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll') $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $Root 'Tests\TelemetryTestFixture.cs'))) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class L3Resolver
{
    public static void Install(string[] dirs)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string name = e.Name.Split(',')[0];
            foreach (string dir in dirs)
            {
                string p = Path.Combine(dir, name + ".dll");
                if (File.Exists(p)) { return Assembly.LoadFrom(p); }
            }
            return null;
        };
    }
}
"@
[L3Resolver]::Install(@($testDir, $legacyHost))
[void][Reflection.Assembly]::LoadFrom($dllCopy)
[void][Reflection.Assembly]::LoadFrom($fixtureDll)

# the real Caller (unchanged by Phase L3)
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes((Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll')))
$NS = 'TSScoringPlugin.Handshake.'
$sessT = $callerAsm.GetType($NS + 'HandshakeSession')
$mgrT = $callerAsm.GetType($NS + 'AppProcessManager')
$optT = $callerAsm.GetType($NS + 'AppProcessOptions')
$ldrT = $callerAsm.GetType($NS + 'LauncherConfigLoader')
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
$repoRoot = ((& git -C $Root rev-parse --show-toplevel) -replace '/', '\')
$mainPy = Join-Path $repoRoot 'main.py'
$bveWinPy = Join-Path $repoRoot 'tests\fake_bve_window.py'
$cfgPath = Join-Path $testDir 'launcher.json'

function WaitFor([scriptblock]$cond, [int]$ms) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) { if (& $cond) { return $true }; Start-Sleep -Milliseconds 20 }
    return [bool](& $cond)
}
function PidAlive([int]$p) { return [bool](Get-Process -Id $p -ErrorAction SilentlyContinue) }
function EventLines($sink, [string]$evt) { return , @($sink.Snapshot() | Where-Object { $_ -like ($evt + ' *') -or $_ -eq $evt }) }
function Names($sink) { return , @($sink.Snapshot() | ForEach-Object { ($_ -split ' ', 2)[0] }) }
$started = New-Object System.Collections.Generic.List[int]
function KillStrays { foreach ($p in $started) { if (PidAlive $p) { try { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue } catch { } } } }

function NewOpts([int]$ready, [int]$grace, [int]$killWait) {
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
function Track($h) { $p = [int](Mg $h 'AppPid'); if ($p -gt 0 -and -not $started.Contains($p)) { $started.Add($p) } }
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
function NewSession([int]$fakePid, $mgr) {
    $rec2 = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec2, 'Show')
    $s = $ctor4.Invoke(@($fakePid, $del, $null, $mgr))
    $now = [long][Diagnostics.Stopwatch]::GetTimestamp()
    $sessT.GetField('started', $npi).SetValue($s, $true)
    $sessT.GetField('phase', $npi).SetValue($s, [Enum]::Parse($phaseT, 'WaitingForBridge'))
    $sessT.GetField('enabledQpc', $npi).SetValue($s, $now)
    $sessT.GetField('absenceStartQpc', $npi).SetValue($s, $now)
    $sessT.GetField('cycleNo', $npi).SetValue($s, 901)
    return $s
}
function Tick($s) { $sessT.GetMethod('NotifyTick').Invoke($s, @()) | Out-Null }
function Step($s) { $stepM.Invoke($s, @()) | Out-Null }
function End($s) { try { $sessT.GetMethod('End').Invoke($s, @()) | Out-Null } catch { } }
function MakeStale($s, [double]$ms) { $past = [long]([Diagnostics.Stopwatch]::GetTimestamp() - [long]($ms * [Diagnostics.Stopwatch]::Frequency / 1000.0)); $sessT.GetField('lastTickQpc', $npi).SetValue($s, $past) }

function NewStation([string]$name, [double]$loc, [int]$arr = -1, [int]$dep = -1, [bool]$pass = $false, [bool]$term = $false) {
    $st = New-Object TsScoringLegacyTelemetryTests.FakeStation
    $st.Name = $name; $st.Location = $loc; $st.ArrivalMs = $arr; $st.DepartureMs = $dep; $st.Pass = $pass; $st.IsTerminal = $term
    return $st
}

# ================================================================================================================================================
Write-Host '--- I: pseudo Legacy API -> telemetry sender -> UDP 54321 -> real main.py --managed (real Overlay) started by the real Caller code'
$qtOk = $false
try { $qtOk = ((& $py -c "import PyQt6.QtWidgets, win32gui, win32process; print('ok')") -eq 'ok') } catch { $qtOk = $false }
$udpBusy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
$mainRunning = $false
. (Join-Path $PSScriptRoot 'MainProcessGuard.ps1'); $mainRunning = Get-TsScoringMainRunning $mainPy      # only <repo>\main.py counts (another project's main.py is not ours); unknown / relative = safe side
$savedProfile = $env:USERPROFILE
$savedHome = $env:HOME
try {
    if ($qtOk -and (-not $udpBusy) -and (-not $mainRunning) -and (Test-Path $mainPy) -and (Test-Path $bveWinPy) -and (Test-Path (Join-Path $Root 'dist\TSScoringPlugin.Caller.InputDevice.dll'))) {
        $env:USERPROFILE = $sandbox
        $env:HOME = $sandbox
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
        $ldrT.GetProperty('TestPath', $nps).SetValue($null, $cfgPath)
        $cfg = [ordered]@{ schemaVersion = 1; mode = 'development'; pythonExecutable = $py; scriptPath = $mainPy; workingDirectory = $repoRoot }
        [IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
        $logT.GetMethod('ResetForTests', $nps).Invoke($null, @()) | Out-Null
        $logT.GetProperty('TestPath', $nps).SetValue($null, (Join-Path $testDir 'caller.log'))
        $logT.GetProperty('TestPid', $nps).SetValue($null, $bvePid)
        $logT.GetProperty('TestMaxBytes', $nps).SetValue($null, 0)

        $b = NewBridgeObjs $bvePid
        $m = NewMgr $bvePid (NewOpts 25000 6000 3000)
        $s = NewSession $bvePid $m.Mgr
        # the pseudo Legacy world: a scenario with four stations, driven by the real sender core, sending through the REAL UDP sink
        $lh = New-Object TsScoringLegacyTelemetryTests.LiveHarness -ArgumentList $withInput
        if ($withInput) { $lh.Input.CabName = 'TwoLeverCab'; $lh.Input.HandleTypeValue = 2; $lh.Input.BrakeKindValue = 2; $lh.Api.BrakeKind = 2; $lh.Input.PowN = 4; $lh.Input.BrkN = 9; $lh.Input.EbN = 10; $lh.Input.Rev = 1; $lh.Input.Pow = 2; $lh.Input.Brk = 0; $lh.Input.StoreBc = [double[]]@(120.5); $lh.Input.StoreBp = [double[]]@(490.0) }
        $lh.Api.FreshWrapperEachCall = $true      # the real host: IBveHacker.Scenario is a NEW wrapper object on every Tick (the L3-live defect needs this)
        $lh.Api.SpeedMps = 15.0; $lh.Api.Location = 900.0; $lh.Api.GradientRatio = 0.008
        $lh.Api.Stations.Add((NewStation 'A' 0.0)); $lh.Api.Stations.Add((NewStation 'B' 1000.0 36100000 36130000)); $lh.Api.Stations.Add((NewStation 'C' 2000.0 -1 -1 $true)); $lh.Api.Stations.Add((NewStation 'D' 3000.0 36400000 -1 $false $true))

        # Pump: the host's Tick (Driving stays ON) and, when asked, the sender's Tick (telemetry) for a number of milliseconds
        function Pump([int]$ms, [bool]$telemetry) {
            $sw = [Diagnostics.Stopwatch]::StartNew()
            while ($sw.ElapsedMilliseconds -lt $ms) {
                Tick $s; Step $s
                if ($telemetry) { $lh.Run(1, 16) }
                Start-Sleep -Milliseconds 16
            }
        }
        function Overlay { $w = [WinEnum]::OwnedBy($bveHwnd, [uint32]$app); return , $w }
        function OverlayVisible { $w = Overlay; return ($w.Count -ge 1 -and [WinEnum]::Visible($w[0])) }

        for ($i = 0; $i -lt 20; $i++) { Tick $s; Step $s }
        SetSR $b 1 $true; Step $s; Step $s; Tick $s; Step $s
        $rdy = WaitFor { Tick $s; Step $s; [string](Mg $m 'State') -eq 'Ready' } 40000
        Track $m
        $app = [int](Mg $m 'AppPid')
        # 1. Session ON and Driving ON, but no telemetry has been sent yet
        $everVisible = $false
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 2500) { Tick $s; Step $s; if (OverlayVisible) { $everVisible = $true }; Start-Sleep -Milliseconds 20 }
        Check 'T01 AppReady, Session ON and Driving ON - and still NO HUD window is shown while no telemetry has arrived (no placeholder HUD)' ($rdy -and (-not $everVisible) -and (PidAlive $app) -and ([int](Mg $m 'StopSignalCount') -eq 0))
        Check 'T02 the application and its Overlay are alive and waiting (one process started, no Stop)' ((PidAlive $app) -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ((Overlay).Count -le 1))

        # 2. telemetry starts
        $idOld = 0
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $vis1 = $false
        while ($sw.ElapsedMilliseconds -lt 12000 -and -not $vis1) { Tick $s; Step $s; $lh.Run(1, 16); Start-Sleep -Milliseconds 16; $vis1 = OverlayVisible }
        $ov = Overlay
        $h1 = if ($ov.Count -ge 1) { $ov[0] } else { 0 }
        $idOld = $lh.ScenarioId
        Check ('T03 with the first real telemetry of the generation the HUD appears: ONE Overlay window, owned by the BVE window (' + $ov.Count + ' window(s), ' + $lh.Sent + ' datagrams sent)') ($vis1 -and ($ov.Count -eq 1) -and ($h1 -ne 0) -and ($lh.Failed -eq 0))
        Pump 500 $true
        Check 'T04 and stays: the same window handle, no flicker' ((OverlayVisible) -and ((Overlay).Count -eq 1) -and ((Overlay)[0] -eq $h1))

        # 3. soft OFF (Legacy selection screen pattern): hidden, then back with the same data
        MakeStale $s 2500; Step $s
        $hid = WaitFor { Step $s; -not (OverlayVisible) } 6000
        Check 'T05 soft OFF (Driving OFF): the HUD is hidden, the window and the process stay' ($hid -and [WinEnum]::Exists($h1) -and (PidAlive $app) -and ([int](Mg $m 'StopSignalCount') -eq 0))
        $shown = $false
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 8000 -and -not $shown) { Tick $s; Step $s; $lh.Run(1, 16); Start-Sleep -Milliseconds 16; $shown = OverlayVisible }
        Check 'T06 Driving ON again: the SAME window handle is shown again (nothing re-created)' ($shown -and ((Overlay).Count -eq 1) -and ((Overlay)[0] -eq $h1))

        # 4. the scenario is reloaded: generation 2. Until the NEW scenario's telemetry arrives, nothing is shown
        $lh.Opened($true)
        SetSR $b 1 $false; Step $s
        $hid2 = WaitFor { Step $s; -not (OverlayVisible) } 6000
        Check 'T07 reload step 1 (ScenarioOpened / ScenarioReady withdrawn): the HUD is hidden, window and process stay' ($hid2 -and [WinEnum]::Exists($h1) -and (PidAlive $app))
        $lh.Api.Created = $false; $lh.Run(3, 16)
        SetSR $b 2 $true; Step $s; Step $s; Tick $s; Step $s
        $everVisible2 = $false
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 2500) { Tick $s; Step $s; if (OverlayVisible) { $everVisible2 = $true }; Start-Sleep -Milliseconds 20 }
        Check 'T08 generation 2 with Session ON and Driving ON but no telemetry of the new scenario yet: the HUD stays hidden (the old scenario''s values are not shown)' ((-not $everVisible2) -and (PidAlive $app))
        # 5. the new scenario starts sending
        $lh.Api.Created = $true; $lh.Api.Scenario = New-Object object; $lh.Api.Location = 100.0; $lh.Api.TimeMs = 36500000; $lh.Created()
        $shown3 = $false
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 10000 -and -not $shown3) { Tick $s; Step $s; $lh.Run(1, 16); Start-Sleep -Milliseconds 16; $shown3 = OverlayVisible }
        Check 'T09 the new scenario''s telemetry shows the HUD again: SAME process, SAME window handle, one Overlay window, Process.Start once' ($shown3 -and ((Overlay).Count -eq 1) -and ((Overlay)[0] -eq $h1) -and ([int](Mg $m 'ProcessStartCount') -eq 1) -and ((Mg $m 'AppPid') -eq $app) -and ($lh.ScenarioId -ne $idOld))
        # 6. a late datagram of the old scenario instance changes nothing
        for ($i = 0; $i -lt 20; $i++) { $lh.SendRaw("SCENARIO_ID:$idOld,AVAIL:1:loc+speed+time,SPEED:200,TIME:36000000,LOCATION:5"); Pump 30 $true }
        Check 'T10 datagrams of the OLD scenario instance arriving now are ignored: the HUD stays shown' ((OverlayVisible) -and ((Overlay).Count -eq 1))
        # 7. Session OFF while telemetry keeps flowing
        SetSR $b 2 $false; Step $s
        $hid3 = $false
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 6000 -and -not $hid3) { Step $s; $lh.Run(1, 16); Start-Sleep -Milliseconds 16; $hid3 = -not (OverlayVisible) }
        Pump 600 $true
        Check 'T11 Session OFF: the HUD is hidden and stays hidden although telemetry keeps flowing; window and process stay, no Stop' ($hid3 -and (-not (OverlayVisible)) -and [WinEnum]::Exists($h1) -and (PidAlive $app) -and ([int](Mg $m 'StopSignalCount') -eq 0))
        # 8. Session ON again for the same generation: the data of the generation is still current
        SetSR $b 2 $true; Step $s; Step $s; Tick $s; Step $s
        $shown4 = $false
        $sw = [Diagnostics.Stopwatch]::StartNew()
        while ($sw.ElapsedMilliseconds -lt 8000 -and -not $shown4) { Tick $s; Step $s; $lh.Run(1, 16); Start-Sleep -Milliseconds 16; $shown4 = OverlayVisible }
        Check 'T12 Session ON again: the HUD returns on the same window handle' ($shown4 -and ((Overlay)[0] -eq $h1) -and ((Overlay).Count -eq 1))

        # 9. the end: Dispose of the Caller -> Stop -> exit 0
        $lh.Dispose()
        $sw = [Diagnostics.Stopwatch]::StartNew()
        End $s
        $endMs = $sw.ElapsedMilliseconds
        $el = EventLines $m.Sink 'APP_STDERR'
        $text = ($el -join "`n")
        Check ('T13 Dispose: exit code 0 in ' + $endMs + ' ms, no Kill, no residual process, the HUD window is gone') (([int](Mg $m 'ExitCode') -eq 0) -and (-not (Mg $m 'Killed')) -and (-not (PidAlive $app)) -and (-not [WinEnum]::Exists($h1)) -and ((EventLines $m.Sink 'APP_STATE_CLOSED').Count -eq 1))
        $udpAfter = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
        Check 'T14 UDP 54321 is free again and the stand-in BVE window is untouched' ((-not $udpAfter) -and (PidAlive $bvePid))
        $firsts = [regex]::Matches($text, 'event=telemetry-first[^\r\n]*')
        if (-not $withInput) {
            Check ('T15 the application logged the first telemetry of each generation (' + $firsts.Count + ') with the sender''s announcement: explicit AVAIL; the first line has no acceleration reference yet, the next line adds it, and what is missing is exactly what the Legacy API cannot provide') (($firsts.Count -ge 2) -and ($firsts[0].Value -match 'avail=explicit') -and ($firsts[0].Value -match 'missing=bcp\+bpp\+calcg\+doortime\+handle\+jump\+maplimit_ahead\+trainlen') -and ($text -match 'event=telemetry-avail[^\r\n]*missing=bcp\+bpp\+doortime\+handle\+jump\+maplimit_ahead\+trainlen(\s|$)'))
            Check 'T16 the HUD reported the items the sender cannot provide: only the handle row' ($text -match 'event=hud-items[^\r\n]*unavailable=handle(\s|$)')
        }
        else {
            # Phase LI1: the sender writes the handle group and both pressures, so the handle row is no longer missing and bcp / bpp / handle are announced
            Check ('T15 (LI1) the first telemetry of each generation (' + $firsts.Count + ') is announced with explicit AVAIL; the first line lacks only the acceleration reference and what the Legacy API cannot provide - NOT handle, bcp or bpp - and the next line adds calcg') (($firsts.Count -ge 2) -and ($firsts[0].Value -match 'avail=explicit') -and ($firsts[0].Value -match 'missing=calcg\+doortime\+jump\+maplimit_ahead\+trainlen(\s|$)') -and ($text -match 'event=telemetry-avail[^\r\n]*missing=doortime\+jump\+maplimit_ahead\+trainlen(\s|$)') -and ($text -notmatch 'missing=[^\r\n]*(handle|bcp|bpp)'))
            Check 'T16 (LI1) the HUD reports no item the sender cannot provide: the handle row is available (unavailable=none)' (($text -match 'event=hud-items[^\r\n]*unavailable=none(\s|$)') -and ($text -notmatch 'event=hud-items[^\r\n]*unavailable=handle'))
        }
        Check 'T17 stale datagrams were dropped and counted: ONE telemetry-drop line for the burst (reason=stale-epoch), telemetry-summary tel_stale > 0' ((([regex]::Matches($text, 'event=telemetry-drop[^\r\n]*reason=stale-epoch')).Count -eq 1) -and ($text -match 'event=telemetry-summary[^\r\n]*tel_stale=([1-9]\d*)'))
        Check 'T18 the telemetry summary counts the accepted telemetry and no invalid line' (($text -match 'event=telemetry-summary[^\r\n]*tel_accepted=([1-9]\d*)') -and ($text -match 'event=telemetry-summary[^\r\n]*tel_invalid=0'))
        $managedLines = @($el | Where-Object { $_ -match '\[MANAGED\]' })
        Check ('T19 diagnostics are state changes only: ' + $el.Count + ' application lines in total (<= 200, none dropped), no path, no telemetry value') (($el.Count -le 200) -and ((EventLines $m.Sink 'APP_STREAMS')[0] -match 'stderrDropped=0') -and ($text -notmatch '[A-Za-z]:\\') -and ($text -notmatch 'SCENARIO_ID:|LOCATION:|SPEED:|GRADIENT:|NEXTLOC:') -and ($managedLines.Count -ge 10))
        Check 'T21 the sender is never ahead of the Caller although the host hands out a new wrapper every Tick: tel_ahead=0, no sender-ahead drop, no hud-hide for telemetry-wait' (($text -match 'event=telemetry-summary[^\r\n]*tel_ahead=0(\s|$)') -and ($text -notmatch 'sender-ahead') -and ($text -notmatch 'event=hud-hide[^\r\n]*reason=telemetry-wait'))
        $gens = [regex]::Matches($text, 'event=telemetry-generation[^\r\n]*')
        Check ('T20 each generation change was seen by the telemetry gate (' + $gens.Count + ')') ($gens.Count -ge 1)
        $deskLog = Join-Path $sandbox 'Desktop\debug.log'
        $deskInfo = if (Test-Path $deskLog) { (Get-Item $deskLog).Length } else { 0 }
        Write-Host ('INFO the application''s debug log (redirected to the private profile) holds ' + $deskInfo + ' bytes')
        DisposeBridgeObjs $b
        try { $bveProc.StandardInput.Close() } catch { }
        [void]$bveProc.WaitForExit(5000)
        if (-not $bveProc.HasExited) { try { $bveProc.Kill() } catch { } }
        $stderrFile = Join-Path $testDir 'application-stderr.txt'
        [IO.File]::WriteAllText($stderrFile, $text, (New-Object Text.UTF8Encoding($false)))
    }
    else {
        Skip ('T01-T20 live chain: not run (PyQt6/pywin32=' + $qtOk + ', UDP 54321 busy=' + $udpBusy + ', a main.py process present=' + $mainRunning + ')')
    }
}
finally {
    $env:USERPROFILE = $savedProfile
    $env:HOME = $savedHome
    KillStrays
    try { $ldrT.GetProperty('TestPath', $nps).SetValue($null, $null) } catch { }
}

$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"TELEMETRY-INTEGRATION-L3 PASS=$pass FAIL=$fail SKIP=$($script:skips)"
if ($fail -gt 0) { exit 1 } else { exit 0 }
