# PHASE SI-A7 (M1a) - read-only static verification of the Tick independent control plane, the Ready epoch and their publication (built DLLs + sources + git scope).
# Nothing is executed except git (read-only) and a metadata load of the built DLLs. Proves: the control plane is ONE host independent source shared by both adapters, its thread
# touches no BVE object, the lock order is fixed and nothing takes it backwards, the ScenarioState / state block grew only in the reserved bytes, the Python side only READS the epoch
# (no token, no key, no new press path), the start-request machinery is byte-identical to the baseline, and only the files of this phase changed.
# This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Baseline = '42850d1b897493bef10afc5130ae3d790fb4d5ea',
    [string]$ExpectedStash = 'b5f0174'
)

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function RunGit([string[]]$gitArgs) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.Arguments = (($gitArgs | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $p = [Diagnostics.Process]::Start($psi)
    $o = $p.StandardOutput.ReadToEnd()
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw ('git failed: ' + ($gitArgs -join ' ')) }
    return $o
}
$top = (RunGit @('rev-parse', '--show-toplevel')).Trim() -replace '/', '\'
$prefix = (RunGit @('rev-parse', '--show-prefix')).Trim()
function BaseText([string]$rel) { return ((RunGit @('show', ($Baseline + ':' + $prefix + $rel.Replace('\', '/')))) -replace "`r`n", "`n") }
function WorkText([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $Root $rel))) -replace "`r`n", "`n") }
function TopText([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $top $rel))) -replace "`r`n", "`n") }
function TopBaseText([string]$rel) { return ((RunGit @('show', ($Baseline + ':' + $rel.Replace('\', '/')))) -replace "`r`n", "`n") }
# comments and string literals removed (code only), line by line
function CodeOf([string]$text) {
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($text -split "`n")) {
        if ($line.TrimStart().StartsWith('//')) { continue }
        $c = [regex]::Replace($line, '"(?:[^"\\]|\\.)*"', '""')
        $c = [regex]::Replace($c, '//.*$', '')
        $out.Add($c)
    }
    return ($out -join "`n")
}
function MethodText([string]$text, [string]$name) {
    $m = [regex]::Match($text, '(?ms)^        (?:private|internal|public)[^\n]*\b' + [regex]::Escape($name) + '\([^\n]*\)\s*\n        \{.*?\n        \}\n')
    return $m.Value
}

# =====================================================================================================================================================
Write-Host '==== git state (read-only) ===='
$head = (RunGit @('rev-parse', 'HEAD')).Trim()
$staged = @((RunGit @('diff', '--cached', '--name-only')) -split "`n" | Where-Object { $_ })
$stash = @((RunGit @('stash', 'list', '--format=%h')) -split "`n" | Where-Object { $_ })
"HEAD     : $head"
Check 'nothing is staged (this phase never stages)' ($staged.Count -eq 0)
Check ('the only stash is still ' + $ExpectedStash + '... (untouched)') (($stash.Count -eq 1) -and ($stash[0] -like ($ExpectedStash + '*')))
Check 'the baseline commit exists and HEAD is the baseline or a descendant of it' (((RunGit @('merge-base', '--is-ancestor', $Baseline, 'HEAD')) -ne $null))

# =====================================================================================================================================================
Write-Host '==== scope: only the files of this phase differ from the baseline ===='
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline)) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
"files touched relative to the baseline (tracked changes + untracked): " + $touched.Count
$H = $prefix
$allowed = @(
    'Bridge/src/HandshakeControlPlane.cs', 'Bridge/src/TsScoringBridgePrototype.cs', 'Bridge/src/ScenarioReadyTracker.cs', 'Bridge/src/ScenarioReadyPublisher.cs', 'Bridge/src/AssemblyInfo.cs',
    'Bridge/Legacy/src/HandshakeControlPlane.cs', 'Bridge/Legacy/src/TsScoringLegacyBridge.cs', 'Bridge/Legacy/src/AssemblyInfo.cs',
    'Bridge/TSScoringPlugin.BveEx.Bridge.Prototype.csproj', 'Bridge/Legacy/TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj',
    'Shared/HandshakeProtocol.cs',
    'Caller/src/AppProcessManager.cs', 'Caller/src/AppStatePublisher.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/AssemblyInfo.cs',
    'Tests/Test-ExtensionControlPlaneSIA7.ps1', 'Tools/Verify-PhaseSIA7.ps1', 'Docs/Handshake-PhaseSIA7-ControlPlane.md',
    # tests re-pinned on purpose (their scope / hash / version guards describe the previous phase)
    'Tests/Test-LegacyL1.ps1', 'Tests/Test-AppControllerE1.ps1', 'Tests/Test-AppProcessE3.ps1', 'Tests/Test-DependencyNoticeM1.ps1', 'Tests/Test-DrivingActiveD1.ps1', 'Tests/Test-HudLinkE4.ps1',
    'Tests/Test-LegacyInputLI0.ps1', 'Tests/Test-ObservationC1.ps1', 'Tests/Test-PauseRecoverySIA6.ps1', 'Tests/Test-ScenarioReadyC3.ps1', 'Tests/Test-HandshakeLogic.ps1',
    'Tools/Verify-PhaseC3.ps1', 'Tools/Verify-PhaseL1.ps1',
    # re-pinned at the acceptance of M1a (their scope / hash pins described the history up to Phase SI-1 and the E4 deployment)
    'Tools/Verify-PhaseL3.ps1',
    # Phase SI-B1 (B1-probe, observation only, NOT part of M1a and NOT a product phase): its test, fixture and document; its sources and tools are the folder Tests/B1Probe/ (allowed below)
    'Tests/Test-JumpProbeB1.ps1', 'Tests/B1ProbeTestFixture.cs', 'Docs/Handshake-PhaseSIB1-JumpProbe.md'
) | ForEach-Object { $H + $_ }
$allowed += @('managed_state.py', 'managed_hud.py', 'tests/test_epoch_info_sia7.py', 'tests/managed_epoch_probe.py', 'tests/sia_managed_rig.py', 'tests/test_managed_hud_e4.py', 'tests/test_managed_input_sia3.py')
$outside = @($touched | Where-Object { ($_ -notin $allowed) -and (-not $_.StartsWith($H + 'Tests/B1Probe/')) })
if ($outside.Count -gt 0) { $outside | ForEach-Object { '   outside scope: ' + $_ } }
Check 'every touched file is one of the files of Phase SI-A7 M1a (the listed sources, the re-pinned older tests, the new test / verification / document)' ($outside.Count -eq 0)
Check 'the key files are part of it: the shared control plane (new), both adapters, the tracker, the protocol, the Caller session and the state-block writer' (@('Bridge/src/HandshakeControlPlane.cs', 'Bridge/src/TsScoringBridgePrototype.cs', 'Bridge/Legacy/src/TsScoringLegacyBridge.cs', 'Bridge/src/ScenarioReadyTracker.cs', 'Shared/HandshakeProtocol.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/AppStatePublisher.cs' | Where-Object { ($H + $_) -notin $touched }).Count -eq 0)
Check 'no build output, third-party DLL, PDB or log among the touched files' (@($touched | Where-Object { $_ -match '/out/|/obj/|/dist/|\.dll$|\.pdb$|\.log$|\.bak$' }).Count -eq 0)
Check 'no Class1.cs / AtsLoggerPlugin.cs / C++ project / solution / launcher template / Telemetry project is touched' (@($touched | Where-Object { $_ -match 'Class1\.cs$|AtsLoggerPlugin\.cs$|\.vcxproj|\.slnx$|launcher\.template|/Telemetry/|\.cpp$|\.h$' }).Count -eq 0)

Write-Host '==== unchanged contracts (byte-identical to the baseline, LF-normalised) ===='
$frozen = 'Caller\src\AppController.cs', 'Caller\src\DrivingActivityState.cs', 'Caller\src\LauncherConfig.cs', 'Caller\src\TsScoringCallerInputDevice.cs', 'Shared\AppProtocol.cs', 'Shared\ObservationLog.cs', 'Bridge\src\ScenarioObserver.cs'
$frozenDiff = @($frozen | Where-Object { (BaseText $_) -cne (WorkText $_) })
Check 'the start decision (AppController), DrivingActive, the launcher reader, the input device entry, the thresholds, the log writer and the scenario observer are byte-identical: the start gate, the start count and the log format are not touched' ($frozenDiff.Count -eq 0)
Check 'Python: pause_recovery.py, managed_input.py, managed_mode.py, main.py, scoring_logic.py, telemetry_gate.py, telemetry_contract.py, hud_ui.py, menu_ui.py, config.py, network.py, utils.py are byte-identical (no recovery token, no key, no press path)' (@('pause_recovery.py', 'managed_input.py', 'managed_mode.py', 'main.py', 'scoring_logic.py', 'telemetry_gate.py', 'telemetry_contract.py', 'hud_ui.py', 'menu_ui.py', 'config.py', 'network.py', 'utils.py' | Where-Object { (TopBaseText $_) -cne (TopText $_) }).Count -eq 0)
$pr = TopText 'pause_recovery.py'
Check 'pause_recovery.py: P is pressed from exactly the two SI-A6 call sites; FIRST_QUIET_S is 0.3 s; IMPLEMENTED_KINDS is the F5 kind only; KIND_SCORING_ON has no creation path; the module never names the epoch' (([regex]::Matches($pr, 'self\._o\.press_p_for_recovery\(')).Count -eq 2 -and ($pr -match 'FIRST_QUIET_S = 0\.3 ') -and ($pr -match 'IMPLEMENTED_KINDS = frozenset\(\(KIND_F5_RELOAD,\)\)') -and (([regex]::Matches($pr, 'KIND_SCORING_ON')).Count -eq 2) -and ($pr -notmatch '(?i)epoch'))
$hp = WorkText 'Shared\HandshakeProtocol.cs'; $hpBase = BaseText 'Shared\HandshakeProtocol.cs'
Check 'HandshakeProtocol: StateVersion 1, Size 64, the Check / LoadCheck formulas and the timings are the baseline text' (($hp -match 'public const int StateVersion = 1;') -and ($hp -match 'public const int Size = 64;') -and ([regex]::Match($hp, '(?s)internal static int ComputeCheck.*?\n        \}\n').Value -ceq [regex]::Match($hpBase, '(?s)internal static int ComputeCheck.*?\n        \}\n').Value) -and ([regex]::Match($hp, '(?s)internal static int ComputeLoadCheck.*?\n        \}\n').Value -ceq [regex]::Match($hpBase, '(?s)internal static int ComputeLoadCheck.*?\n        \}\n').Value) -and ([regex]::Match($hp, '(?s)internal static class HandshakeTiming.*?\n    \}\n').Value -ceq [regex]::Match($hpBase, '(?s)internal static class HandshakeTiming.*?\n    \}\n').Value))
$hpAdded = @(Compare-Object ($hpBase -split "`n") ($hp -split "`n") | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject.Trim() })
Check ('HandshakeProtocol: of the baseline lines only the four WriteCore / Write call forms are replaced (' + $hpAdded.Count + ' lines gone); every old field, offset and constant is still there') ($hpAdded.Count -le 6 -and (@($hpAdded | Where-Object { $_ -notmatch '^(WriteCore\(|private static void WriteCore\(|WriteCore\(view|public int Check;|/// <summary>Writes one consistent state)' }).Count -le 1))
$ssText = $hp.Substring($hp.IndexOf('internal struct ScenarioState'))
Check 'ScenarioState: the epoch fields sit at 36 / 40 / 44 / 48 inside the same seqlock write (between the sequence going odd and even); 52..63 stay reserved' (($ssText -match 'view\.Write\(36, withEpoch \? EpochMagicValue : 0\);') -and ($ssText -match 'view\.Write\(40, withEpoch \? readyEpoch : 0\);') -and ($ssText -match 'view\.Write\(44, withEpoch \? epochFlags : 0\);') -and ($ssText -match 'view\.Write\(48, withEpoch \? ComputeEpochCheck') -and ($ssText.IndexOf('view.Write(16, writing);') -lt $ssText.IndexOf('view.Write(36,')) -and ($ssText.IndexOf('view.Write(48,') -lt $ssText.IndexOf('view.Write(16, finalSeq);')) -and ($ssText -notmatch 'view\.Write\((5[2-9]|6[0-3]),'))
Check 'ScenarioState: EpochMagic is "EPO1" 0x45504F31, the only known flag bit is 1 (TickSeenInEpoch), ReadyEpoch must be >= 1 and EpochCheck covers epoch, flags, generation and sequence' (($hp -match 'EpochMagicValue = 0x45504F31') -and ($hp -match 'EpochKnownBits = EpochTickSeen') -and ($hp -match 'ReadyEpoch >= 1') -and ($hp -match 'ComputeEpochCheck\(ReadyEpoch, EpochFlags, ScenarioGeneration, Sequence\)'))
$asp = WorkText 'Caller\src\AppStatePublisher.cs'
Check 'TSAS: EpochInfo is the uint32 at 56..59 (reserved zero before), Version 1 / Size 64 and every earlier offset are the baseline; it is written inside the seqlock and part of the dedupe' (($asp -match 'public const int OffEpochInfo = 56;') -and ($asp -match 'public const uint Version = 1;') -and ($asp -match 'public const int Size = 64;') -and ($asp -match 'public const int OffTail = 60;') -and ($asp.IndexOf('view.Write(AppStateLayout.OffHead, writing);') -lt $asp.IndexOf('view.Write(AppStateLayout.OffEpochInfo, newEpochInfo);')) -and ($asp.IndexOf('view.Write(AppStateLayout.OffEpochInfo, newEpochInfo);') -lt $asp.IndexOf('view.Write(AppStateLayout.OffTail, finalHead);')) -and ($asp -match 'loadInfo == info && epochInfo == newEpochInfo'))

# =====================================================================================================================================================
Write-Host '==== the control plane: one host independent source, no BVE object ===='
$cpRel = 'Bridge\src\HandshakeControlPlane.cs'
$cp = WorkText $cpRel
$cpCode = CodeOf $cp
Check 'exactly one control plane source exists in the tree (Bridge\src); the Legacy copy is gone' (@(Get-ChildItem $Root -Recurse -Filter HandshakeControlPlane.cs | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' }).Count -eq 1 -and (-not (Test-Path (Join-Path $Root 'Bridge\Legacy\src\HandshakeControlPlane.cs'))))
Check 'the file names no host and no BVE type anywhere, comments included: no BveEx / BveEX / AtsEx / BveTypes / PluginHost / PluginBuilder / BveHacker / ClassWrappers / IExtension' ($cp -cnotmatch 'BveEx|BveEX|AtsEx|BveTypes|PluginHost|PluginBuilder|BveHacker|ClassWrappers|IExtension|AssemblyPluginBase')
Check 'its CODE touches no BVE object and no tracker: no Scenario / Vehicle / TimeManager / Hacker / Location / Station / position / time vocabulary, no BveSnapshot, no ScenarioReadyTracker (it only calls the two callbacks it was given)' ($cpCode -cnotmatch 'Scenario|Vehicle|TimeManager|Hacker|Location|Station|BveSnapshot|IsScenarioCreated|ScenarioReadyTracker|Func<BveSnapshot>')
$cpUsing = @([regex]::Matches($cp, '(?m)^using ([\w.]+);') | ForEach-Object { $_.Groups[1].Value })
Check ('its using list is plain .NET only (' + ($cpUsing -join ', ') + ')') ((@($cpUsing | Where-Object { $_ -notin 'System', 'System.Diagnostics', 'System.IO.MemoryMappedFiles', 'System.Security.AccessControl', 'System.Threading' }).Count -eq 0))
Check 'the thread: one background thread (new Thread once, IsBackground), joined with a time limit OUTSIDE the gate on Shutdown, the loop survives a step exception, LiveWorkers counts it' (([regex]::Matches($cpCode, 'new Thread\(')).Count -eq 1 -and ($cp -match 'IsBackground = true') -and ($cp -match 'Join\(1000\)') -and ($cp -match 'Interlocked\.Increment\(ref LiveWorkers\)') -and ($cp -match 'Interlocked\.Decrement\(ref LiveWorkers\)') -and ($cp -match '(?s)while \(!shutdown\.WaitOne\(pollMs\)\)\s*\{\s*try\s*\{\s*Step\(\);\s*\}\s*catch'))
Check 'no Process, file, socket, UDP, registry, Sleep, timer, window or reflection use in the control plane' ($cpCode -cnotmatch 'Process\.|(?<![A-Za-z])File\.|FileStream|Socket|Udp|Registry|Thread\.Sleep|System\.Timers|Timer\b|DllImport|Activator|BindingFlags|Form\b|Window')
$lockLines = @([regex]::Matches($cpCode, 'lock \(([^)]*)\)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
Check ('the control plane has ONE lock object (gate); the observation log is the only other lock below it (' + ($lockLines -join ',') + ')') (($lockLines -join ',') -ceq 'gate')
# the callbacks are invoked only from the *Locked methods of this file (control gate held), nowhere else
$cbSites = @([regex]::Matches($cpCode, '(handshakeLost|handshakeUp)\(') | ForEach-Object { $_.Index })
$cbMethods = @('TryConnectLocked', 'ReleaseLocked' | ForEach-Object { MethodText $cpCode $_ })
$cbInsideOk = $true
foreach ($m in [regex]::Matches($cpCode, '(handshakeLost|handshakeUp)\(')) {
    $ctx = $cpCode.Substring(0, $m.Index)
    $lastMethod = [regex]::Matches($ctx, '(?m)^        (?:private|internal|public)[^\n]*\b(\w+)\([^\n]*\)\s*$') | Select-Object -Last 1
    if ((-not $lastMethod) -or ($lastMethod.Groups[1].Value -notin 'TryConnectLocked', 'ReleaseLocked', 'HandshakeControlPlane')) { $cbInsideOk = $false }
}
Check 'LOCK ORDER (control gate -> owner gate): handshakeLost / handshakeUp are called only inside TryConnectLocked / ReleaseLocked, i.e. with the control gate held; the order is documented at the top of the file' (($cbSites.Count -ge 2) -and $cbInsideOk -and ($cp -match 'LOCK ORDER') -and ($cp -match 'control gate\s+->\s+owner''s gate'))
Check 'the lock free members the owner and the Tick read are volatile and take no lock: HandshakeUp, ReadyEpoch (set BEFORE up), IsWorkerAlive' (($cp -match 'private volatile bool up;') -and ($cp -match 'private volatile int readyEpoch;') -and ($cp -match 'internal bool HandshakeUp \{ get \{ return up; \} \}') -and ($cp -match 'internal int ReadyEpoch \{ get \{ return readyEpoch; \} \}') -and ($cp.IndexOf('readyEpoch = readyCreateCount;') -gt 0) -and ($cp.IndexOf('readyEpoch = readyCreateCount;') -lt $cp.IndexOf('up = true;')) -and ($cp -match 'internal bool IsWorkerAlive \{ get \{ Thread w = worker; return w != null && w\.IsAlive; \} \}'))
Check 'ReadyEpoch counts Ready creations (readyCreateCount); the epoch is in the READY_CREATE_OK / READY_DISPOSED log lines' (($cp -match 'readyEpoch = readyCreateCount;') -and ($cp -match 'createCount=" \+ readyCreateCount \+ " readyEpoch=" \+ readyEpoch') -and ($cp -match 'destroyCount=" \+ readyDestroyCount \+ " readyEpoch=" \+ readyEpoch'))

Write-Host '==== both adapters on the same source ===='
$curProj = WorkText 'Bridge\TSScoringPlugin.BveEx.Bridge.Prototype.csproj'
$legProj = WorkText 'Bridge\Legacy\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj'
Check 'the Current project compiles src\HandshakeControlPlane.cs; the Legacy project links ..\src\HandshakeControlPlane.cs; neither lists another copy' (($curProj -match '<Compile Include="src\\HandshakeControlPlane\.cs" />') -and ($legProj -match '<Compile Include="\.\.\\src\\HandshakeControlPlane\.cs">') -and ($legProj -notmatch 'Include="src\\HandshakeControlPlane'))
$curAd = WorkText 'Bridge\src\TsScoringBridgePrototype.cs'; $legAd = WorkText 'Bridge\Legacy\src\TsScoringLegacyBridge.cs'
$curAdCode = CodeOf $curAd; $legAdCode = CodeOf $legAd
foreach ($pair in @(@('Current', $curAd, $curAdCode), @('Legacy', $legAd, $legAdCode))) {
    $nm = $pair[0]; $txt = $pair[1]; $code = $pair[2]
    $tickM = MethodText $code 'Tick'
    Check ("$nm adapter: Tick restarts the control thread only when it ended (IsWorkerAlive / Start) and feeds the observer and the tracker; it creates no kernel object, runs no handshake and touches no ScenarioReady publication directly") (($tickM -match 'c\.IsWorkerAlive') -and ($tickM -match 'c\.Start\(\)') -and ($tickM -match 't\.OnTick\(\)') -and ($tickM -cnotmatch 'EventWaitHandle|TryOpenExisting|MemoryMappedFile|HandshakeStep|TryConnect|Release\(|Step\(\)|Shutdown|Withdraw'))
    Check ("$nm adapter: no lock of its own, no thread of its own, no handshake code (no EventWaitHandle / MemoryMappedFile / Stopwatch-driven poll)") (($code -cnotmatch 'lock \(|new Thread\(|EventWaitHandle|MemoryMappedFile|TryOpenExisting|BridgePollMs'))
    $ctlUse = @([regex]::Matches($code, '\bc\.(\w+)|\bcontrol\.(\w+)') | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } } | Sort-Object -Unique)
    Check ("$nm adapter: it uses only these members of the control plane: " + ($ctlUse -join ', ')) (@($ctlUse | Where-Object { $_ -notin 'Start', 'PublishAvailability', 'HandshakeUp', 'ReadyEpoch', 'IsWorkerAlive', 'IsAvailablePublished', 'Shutdown', 'WithdrawAvailability' }).Count -eq 0)
    $disp = $txt.IndexOf('public override void Dispose()')
    $dBody = $txt.Substring($disp, 900)
    Check ("$nm adapter: Dispose clears ScenarioReady (tracker.OnDispose) BEFORE the control plane releases Ready (Shutdown), and BridgeAvailable is withdrawn last") (($dBody.IndexOf('t.OnDispose()') -ge 0) -and ($dBody.IndexOf('t.OnDispose()') -lt $dBody.IndexOf('c.Shutdown("bridge-dispose")')) -and ($dBody.IndexOf('c.Shutdown("bridge-dispose")') -lt $dBody.IndexOf('c.WithdrawAvailability()')))
    Check ("$nm adapter: the constructor publishes BridgeAvailable first (BeginControl(false)), then wires the observation / tracker, and the control thread starts LAST") (($txt.IndexOf('BeginControl(false);') -ge 0) -and ($txt.IndexOf('BeginControl(false);') -lt $txt.IndexOf('SubscribeObservers(); }')) -and ($txt.IndexOf('SubscribeObservers(); }') -lt $txt.IndexOf('control.Start();')))
    Check ("$nm adapter: the callbacks forward plain numbers to the tracker only (OnHandshakeLost(reason) / OnHandshakeUp(epoch)); the tracker reads the epoch through a lock free delegate") (($txt -match 't\.OnHandshakeLost\(reason\)') -and ($txt -match 't\.OnHandshakeUp\(readyEpoch\)') -and ($txt -match 'new ScenarioReadyTracker\(Obs, readSnapshot, HandshakeUp, publisher, null, ControlReadyEpoch\)'))
}
$hostTok = 'AtsEx|BveTypes|IBveHacker|PluginBuilder|AssemblyPluginBase|IExtension|PluginAttribute|TickResult|ClassWrappers'
Check 'the host API stays out of the shared files: AtsEX only in the Legacy adapter, BveEx only in the Current adapter, nothing in the tracker / publisher / protocol / control plane' ((($legAdCode -cmatch 'AtsEx') -and ($legAdCode -cnotmatch 'BveEx|BveEX')) -and (($curAdCode -cmatch 'BveEx') -and ($curAdCode -cnotmatch 'AtsEx')) -and ((@('Bridge\src\ScenarioReadyTracker.cs', 'Bridge\src\ScenarioReadyPublisher.cs', 'Shared\HandshakeProtocol.cs', 'Bridge\src\HandshakeControlPlane.cs' | Where-Object { (CodeOf (WorkText $_)) -cmatch ($hostTok + '|BveEx|BveEX') }).Count -eq 0)))
$thr = @(Get-ChildItem $Root -Recurse -Include *.cs | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' -and $_.FullName -notmatch '\\(Telemetry|Tests)\\' } | Where-Object { (CodeOf (([IO.File]::ReadAllText($_.FullName)) -replace "`r`n", "`n")) -match 'new Thread\(' } | ForEach-Object { $_.FullName.Substring($Root.Length + 1) } | Sort-Object)
Check ('threads are created only in the Caller session (monitor), the Caller process manager (worker) and the shared control plane: ' + ($thr -join ', ')) (($thr -join ',') -ceq 'Bridge\src\HandshakeControlPlane.cs,Caller\src\AppProcessManager.cs,Caller\src\HandshakeSession.cs')

Write-Host '==== the tracker: the epoch, the order, the BVE reads ===='
$trk = WorkText 'Bridge\src\ScenarioReadyTracker.cs'; $trkCode = CodeOf $trk
Check 'the tracker knows nothing of the control plane object: no HandshakeControlPlane, no IsAvailablePublished / ReadyCreateCount / Shutdown / PublishAvailability / WithdrawAvailability / IsWorkerAlive (it only has the lock-free handshakeUp and readEpoch delegates)' ($trkCode -cnotmatch 'HandshakeControlPlane|IsAvailablePublished|ReadyCreateCount|ReadyDestroyCount|Shutdown\(|PublishAvailability|WithdrawAvailability|IsWorkerAlive')
$trkLocks = @([regex]::Matches($trkCode, 'lock \(([^)]*)\)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
Check ('LOCK ORDER: the tracker has ONE lock object (gate) and never takes another lock while holding it (' + ($trkLocks -join ',') + '); nothing here can take the control gate') (($trkLocks -join ',') -ceq 'gate')
$onUp = MethodText $trkCode 'OnHandshakeUp'
$onTick = MethodText $trkCode 'OnTick'
$noteTick = MethodText $trkCode 'NoteTickInEpochLocked'
Check 'OnHandshakeUp (control thread) reads nothing of BVE: no read() / ReadSafe / BveSnapshot / Facts, no establishment (EstablishLocked), only the epoch, the held values and PublishLocked / PushStateLocked' (($onUp.Length -gt 400) -and ($onUp -cnotmatch 'ReadSafe|\bread\(|BveSnapshot|Facts\(|EstablishLocked|level = true') -and ($onUp -match 'PublishLocked\(') -and ($onUp -match 'PushStateLocked\(\)'))
Check 'NoteTickInEpochLocked raises the Tick flag and is the first thing OnTick does after reading the handshake (before PublishLocked and EstablishLocked); establishment (level = true) still has exactly one place' (($noteTick.Length -gt 300) -and ($onTick.IndexOf('bool up = SafeHandshake();') -lt $onTick.IndexOf('NoteTickInEpochLocked(up);')) -and ($onTick.IndexOf('NoteTickInEpochLocked(up);') -lt $onTick.IndexOf('PublishLocked(')) -and ($onTick.IndexOf('NoteTickInEpochLocked(up);') -lt $onTick.IndexOf('EstablishLocked(')) -and (([regex]::Matches($trkCode, 'level = true;')).Count -eq 1))
Check 'the establishment and clearing rules are unchanged: every baseline line of OnScenarioOpened / OnScenarioCreated / OnScenarioClosed / ClearLocked / EstablishLocked is still there (the tracker only grew)' (& {
        $b = BaseText 'Bridge\src\ScenarioReadyTracker.cs'; $bc = CodeOf $b
        $have = @{}; foreach ($x in ($trkCode -split "`n")) { $have[$x.Trim()] = 1 }
        $gone = @(); foreach ($m in 'OnScenarioOpened', 'OnScenarioCreated', 'OnScenarioClosed', 'ClearLocked', 'EstablishLocked', 'OnHandshakeLost', 'OnDispose') { foreach ($ln in ((MethodText $bc $m) -split "`n")) { $tl = $ln.Trim(); if ($tl -and (-not $have.ContainsKey($tl))) { $gone += $tl } } }
        $gone.Count -eq 0 })
Check 'the publisher interface for the epoch (IScenarioEpochPublisher) extends the load publisher; the 5-argument tracker constructor of every earlier test still exists' (($trk -match 'internal interface IScenarioEpochPublisher : IScenarioLoadPublisher') -and ($trk -match 'internal ScenarioReadyTracker\(Action<string, string, string> log, Func<BveSnapshot> read, Func<bool> handshakeUp, IScenarioReadyPublisher publisher, Func<long> nowMs\)\s*:\s*this\(log, read, handshakeUp, publisher, nowMs, null\)'))

Write-Host '==== the Caller: the epoch is read, logged and copied - nothing decides from it ===='
$hs = WorkText 'Caller\src\HandshakeSession.cs'; $hsCode = CodeOf $hs
$epochIds = 'scenarioEpochSupported|scenarioReadyEpoch|scenarioTickSeenInEpoch|epochLogged|epochTickLogged|epochNoTickSessionLogged|epochObservedQpc|epochObservedCount|epochWithdrawnCount|EpochTextLocked|ObserveEpochLocked|NoteEpochWithdrawnLocked|PackEpochInfo'
$decisionMethods = 'EvaluateDrivingLocked', 'ObserveAppControllerLocked', 'JudgeFirstTickLocked', 'StartNoticeLocked', 'ShowNoticeIfStillNeeded', 'CheckBridgeTimeoutLocked', 'OnBridgeSeenLocked', 'OnBridgeLostLocked', 'OnReadyLocked', 'MonitorLoop', 'NotifyTick', 'Start', 'DisposeAppControllerLocked'
$leak = @($decisionMethods | Where-Object { (MethodText $hsCode $_) -match ($epochIds + '|tickProbe|ObserveCallerTickLocked') })
Check ('no decision method of the session (DrivingActive, the AppController input, the notice, the phases, the Tick hand-over) names the epoch (' + ($leak -join ',') + ')') ($leak.Count -eq 0)
$stepM = MethodText $hsCode 'Step'
Check 'NotifyTick (BVE''s Tick path of the Caller) is byte-identical to the baseline in code: the Caller Tick state is observed by the monitor thread from the Tick count that already exists; the Tick path gained nothing' ((CodeOf (MethodText (BaseText 'Caller\src\HandshakeSession.cs') 'NotifyTick')) -ceq (CodeOf (MethodText $hs 'NotifyTick')))
Check 'CALLER_TICK_STATE: one method (ObserveCallerTickLocked) called from Step only, writes only on a change, 500 ms silence rule' ((([regex]::Matches($hsCode, 'ObserveCallerTickLocked\(now\)')).Count -eq 1) -and ((MethodText $hsCode 'Step') -match 'ObserveCallerTickLocked\(now\)') -and ($hs -match 'TickProbeSilentMs = 500') -and ((MethodText $hs 'ObserveCallerTickLocked') -match 'ObsA\("CALLER_TICK_STATE"') -and (([regex]::Matches((MethodText $hs 'ObserveCallerTickLocked'), 'ObsA\(')).Count -eq 2))
Check 'Step feeds DrivingActive and the AppController with the same arguments as before (scenarioReadyLevel, scenarioGenerationSeen); the epoch only reaches PublishAppStateLocked (the state block) and the log' (($hsCode -match 'driving\.Evaluate\(isEnabled, phase != CallerPhase\.Disposed, scenarioReadyLevel, scenarioGenerationSeen, seq, ageMs\)') -and ($hsCode -match 'appController\.Observe\(driving\.Active, scenarioReadyLevel, scenarioGenerationSeen\)') -and ($stepM -cnotmatch $epochIds))
Check 'the Caller sends no key and no window message and calls no process API for the epoch: no SendInput / keybd_event / PostMessage / SendMessage / GetAsyncKeyState / SetForegroundWindow in any Caller source' (@(Get-ChildItem (Join-Path $Root 'Caller\src') -Filter *.cs | Where-Object { (CodeOf (WorkText ('Caller\src\' + $_.Name))) -cmatch 'SendInput|keybd_event|PostMessage|SendMessage|GetAsyncKeyState|SetForegroundWindow|mouse_event' }).Count -eq 0)
Check 'APP_START_REQUEST / APP_START_SUPPRESSED / APP_STOP_REQUEST / APP_STOP_NOT_REQUIRED keep their exact text (dryRun=yes at the end); the epoch is on companion lines (APP_START_REQUEST_EPOCH, APP_START_SUPPRESSED_EPOCH, APP_LAUNCH_SUPPRESSED_EPOCH)' ((([regex]::Matches($hs, 'ObsA\("APP_(START_REQUEST|START_SUPPRESSED|STOP_REQUEST|STOP_NOT_REQUIRED)", [^\n]*dryRun=yes"\);')).Count -eq 4) -and ($hs -match 'ObsA\("APP_START_REQUEST_EPOCH"') -and ($hs -match 'ObsA\("APP_START_SUPPRESSED_EPOCH"') -and ($hs -match 'ObsA\("APP_LAUNCH_SUPPRESSED_EPOCH"'))
Check 'the process manager gained only the state forwarding of the epoch: RequestStart, the worker, Shutdown, SignalStop and the Process.Start site are byte-identical to the baseline' (& {
        $a = WorkText 'Caller\src\AppProcessManager.cs'; $b = BaseText 'Caller\src\AppProcessManager.cs'
        $same = $true
        foreach ($m in 'RequestStart', 'Shutdown', 'SignalStop', 'RunWorker', 'Supervise', 'WithdrawState') { if ((MethodText $a $m) -cne (MethodText $b $m)) { $same = $false } }
        $same -and (([regex]::Matches($a, 'process\.Start\(\)')).Count -eq 1) -and (([regex]::Matches($a, 'stopEvent\.Set\(\)')).Count -eq 1) })

Write-Host '==== Python: the epoch is parsed and shown, nothing more ===='
$ms = TopText 'managed_state.py'; $mh = TopText 'managed_hud.py'
Check 'managed_state.py: STATE_VERSION 1, STATE_SIZE 64, every earlier offset and the load marker are unchanged; OFF_EPOCH_INFO = 56; a malformed word is "no information", never an error' (($ms -match 'STATE_VERSION = 1') -and ($ms -match 'STATE_SIZE = 64') -and ($ms -match 'OFF_HEAD, OFF_FLAGS, OFF_GENERATION, OFF_CHANGE_COUNT, OFF_TAIL = 32, 36, 40, 44, 60') -and ($ms -match 'OFF_LOAD_INFO, OFF_LOAD_MAGIC = 48, 52') -and ($ms -match 'OFF_EPOCH_INFO = 56') -and ($ms -match 'anything else is "no information"'))
$numstat = @((RunGit @('-C', $top, 'diff', '--numstat', $Baseline, '--', 'managed_state.py', 'managed_hud.py')) -split "`n" | Where-Object { $_ })
$removedPy = 0; foreach ($l in $numstat) { $removedPy += [int](($l -split "`t")[1]) }
Check ('managed_state.py + managed_hud.py: ' + $removedPy + ' baseline lines changed or removed in total (signature / return forms of StateSnapshot, the gate call site); everything else is added') ($removedPy -le 10)
$noteEpoch = [regex]::Match($mh, '(?s)    def _note_epoch\(self, snapshot\):.*?\n    def _on_generation').Value
Check 'managed_hud.py: the epoch is read in _note_epoch only (one diagnostic line on change); recovery, gate, input and Overlay never see it' (($noteEpoch.Length -gt 300) -and ((@([regex]::Matches(($mh.Replace($noteEpoch, '')), 'snapshot\.(epoch_\w+|ready_epoch)'))).Count -eq 0) -and (([regex]::Matches($mh, 'self\._note_epoch\(snapshot\)')).Count -eq 2))

Write-Host '==== built DLLs ===='
$dist = Join-Path $Root 'dist'
$callerDll = Join-Path $dist 'TSScoringPlugin.Caller.InputDevice.dll'
$curDll = Join-Path $dist 'TSScoringPlugin.BveEx.Bridge.Prototype.dll'
$curOut = Join-Path $Root 'Bridge\out\TSScoringPlugin.BveEx.Bridge.Prototype.dll'
$legDll = Join-Path $Root 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll'
foreach ($d in $callerDll, $curDll, $curOut, $legDll) { "{0}  {1}  {2} bytes" -f (Get-FileHash $d -Algorithm SHA256).Hash, $d.Substring($Root.Length + 1), (Get-Item $d).Length }
Check 'dist holds exactly the Caller and the Current Bridge DLL; Bridge\out equals dist; the Legacy out folder holds exactly the Legacy DLL; no PDB anywhere' ((@(Get-ChildItem $dist -File | ForEach-Object { $_.Name } | Sort-Object) -join ',') -ceq 'TSScoringPlugin.BveEx.Bridge.Prototype.dll,TSScoringPlugin.Caller.InputDevice.dll' -and ((Get-FileHash $curDll).Hash -eq (Get-FileHash $curOut).Hash) -and (@(Get-ChildItem (Split-Path $legDll -Parent) -File).Count -eq 1) -and (@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0))
$vc = (Get-Item $callerDll).VersionInfo; $vb = (Get-Item $curDll).VersionInfo; $vl = (Get-Item $legDll).VersionInfo
Check 'versions: Caller 0.13.0.0, Current Bridge 0.8.0.0, Legacy Bridge 0.8.0.0; product TS Scoring; provider Coruge-to' (($vc.FileVersion -eq '0.13.0.0') -and ($vb.FileVersion -eq '0.8.0.0') -and ($vl.FileVersion -eq '0.8.0.0') -and ($vc.ProductName -eq 'TS Scoring') -and ($vb.CompanyName -eq 'Coruge-to') -and ($vl.CompanyName -eq 'Coruge-to') -and ($vc.CompanyName -eq 'Coruge-to'))
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($callerDll))
$curAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($curDll))
$legAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($legDll))
$cr = @($callerAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object); $br = @($curAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object); $lr = @($legAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object)
Check 'references: the Caller only mscorlib, System, System.Core, System.Windows.Forms, Mackoy.IInputDevice; the Legacy Bridge only mscorlib, System, System.Core, AtsEx.PluginHost, BveTypes; the Current Bridge references no AtsEx assembly' ((($cr -join ',') -ceq 'Mackoy.IInputDevice,mscorlib,System,System.Core,System.Windows.Forms') -and (@($lr | Where-Object { $_ -notin 'mscorlib', 'System', 'System.Core', 'AtsEx.PluginHost', 'BveTypes' }).Count -eq 0) -and ($lr -contains 'AtsEx.PluginHost') -and (@($br | Where-Object { $_ -like 'AtsEx*' }).Count -eq 0) -and ($br -contains 'BveEx.PluginHost'))
function TokenHits([string]$dll, [string[]]$tokens) {
    $bytes = [IO.File]::ReadAllBytes($dll)
    $ascii = [Text.Encoding]::ASCII.GetString($bytes); $utf16 = [Text.Encoding]::Unicode.GetString($bytes); $utf16b = [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2))
    $present = @()
    foreach ($tok in $tokens) { $c = ([regex]::Matches($ascii, [regex]::Escape($tok))).Count + ([regex]::Matches($utf16, [regex]::Escape($tok))).Count + ([regex]::Matches($utf16b, [regex]::Escape($tok))).Count; if ($c -gt 0) { $present += $tok } }
    return $present
}
# SI-R5.3 (PIN): OLD token 'Microsoft.Win32' -> NEW 'Microsoft.Win32.Registry' + 'Microsoft.Win32.SystemEvents' (the shared log uses the SafeHandle namespace Microsoft.Win32.SafeHandles; the registry is still banned by 'Registry'). The P/Invoke ban itself is unchanged here:
# the one limited WaitForSingleObject helper has no DllImport token in the metadata and is pinned by Verify-PhaseC3 / Verify-PhaseL1.
$bridgeBad = 'Python', 'UdpClient', 'TcpClient', 'Sockets', 'Registry', 'Microsoft.Win32.Registry', 'Microsoft.Win32.SystemEvents', 'SetWindowsHookEx', 'MessageBox', 'DllImport', 'ProcessStartInfo', 'SendInput', 'keybd_event', 'PostMessage', 'GetAsyncKeyState', 'NamedPipe', 'Global\', 'AtsLoggerPlugin', 'main.py', 'System.Reflection.Emit', 'Activator', 'GetTypes'
Check 'neither Bridge DLL contains a process, socket, UDP, registry, hook, key, P/Invoke, reflection or Python token' ((@(TokenHits $curDll $bridgeBad).Count -eq 0) -and (@(TokenHits $legDll $bridgeBad).Count -eq 0))
Check 'the Caller DLL contains no key-sending API (SendInput / keybd_event / PostMessage / SendMessage / GetAsyncKeyState / SetForegroundWindow)' (@(TokenHits $callerDll @('SendInput', 'keybd_event', 'PostMessage', 'SendMessage', 'GetAsyncKeyState', 'SetForegroundWindow', 'mouse_event')).Count -eq 0)
Check 'both Bridge DLLs carry the control plane type (HandshakeControlPlane) with the same member list' (& {
        $sig = { param($t) (($t.GetMembers([Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly') | ForEach-Object { $_.ToString() } | Sort-Object) -join ';') }
        $a = $curAsm.GetType('TSScoringPlugin.Handshake.HandshakeControlPlane'); $b = $legAsm.GetType('TSScoringPlugin.Handshake.HandshakeControlPlane')
        ($a -ne $null) -and ($b -ne $null) -and ((& $sig $a) -ceq (& $sig $b)) })

Write-Host '==== documents, privacy, hygiene ===='
$doc = WorkText 'Docs\Handshake-PhaseSIA7-ControlPlane.md'
Check 'the document exists and states: M1a is observation first (no scoring-on token, no automatic P-to-P), the lock order, the thread rules, the epoch contract, nothing deployed, O1-O5 not run, and the SIA 10.1 contradiction is NOT rewritten' (($doc.Length -gt 6000) -and ($doc -match 'scoring-on') -and ($doc -match '(?i)lock order') -and ($doc -match 'O1') -and ($doc -match 'O5') -and ($doc -match '10\.1') -and ($doc -match '(?i)not deployed|nothing is deployed|no automatic deployment') -and ($doc -match 'TickSeenInEpoch'))
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$emailPattern = '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
$privFiles = @('Bridge\src\HandshakeControlPlane.cs', 'Bridge\src\TsScoringBridgePrototype.cs', 'Bridge\Legacy\src\TsScoringLegacyBridge.cs', 'Bridge\src\ScenarioReadyTracker.cs', 'Bridge\src\ScenarioReadyPublisher.cs', 'Shared\HandshakeProtocol.cs', 'Caller\src\HandshakeSession.cs', 'Caller\src\AppStatePublisher.cs', 'Caller\src\AppProcessManager.cs', 'Docs\Handshake-PhaseSIA7-ControlPlane.md') | ForEach-Object { Join-Path $Root $_ }
$privFiles += @($callerDll, $curDll, $legDll)
$privHits = 0
foreach ($f in $privFiles) {
    $bytes = [IO.File]::ReadAllBytes($f)
    $ascii = [Text.Encoding]::ASCII.GetString($bytes); $utf16 = [Text.Encoding]::Unicode.GetString($bytes); $utf8 = [Text.Encoding]::UTF8.GetString($bytes)
    foreach ($tok in $forbidden) { foreach ($text in @($ascii, $utf16, $utf8)) { $privHits += ([regex]::Matches($text, [regex]::Escape($tok), 'IgnoreCase')).Count } }
    foreach ($text in @($ascii, $utf16, $utf8)) { $privHits += ([regex]::Matches($text, $emailPattern)).Count }
}
Check ('no user name, machine name, drive path, user folder, repository name or e-mail in the changed sources, the document and the three DLLs (' + $privFiles.Count + ' files, matches=' + $privHits + ')') ($privHits -eq 0)
$nonAscii = @($touched | Where-Object { $_ -like '*.ps1' } | Where-Object { $p = Join-Path $top $_; (Test-Path $p) -and ([IO.File]::ReadAllBytes($p) | Where-Object { $_ -gt 127 } | Select-Object -First 1) })
Check 'the new and edited PowerShell scripts are ASCII-only (the older ones that were already not are not counted)' (@($nonAscii | Where-Object { $_ -in ($H + 'Tests/Test-ExtensionControlPlaneSIA7.ps1'), ($H + 'Tools/Verify-PhaseSIA7.ps1') }).Count -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
