# PHASE C3 - read-only static verification of the built Caller and Bridge DLLs and of the sources (nothing is executed).
# Keeps the Phase B checks (contract, timings, notice text, forbidden dependencies), the Phase C1 observation checks and adds the
# Phase C3 ScenarioReady checks. Phase B / Phase C1 reference sources are read from Git history (read-only; the commits that first added Shared\HandshakeProtocol.cs and Bridge\src\ScenarioObserver.cs) to prove which lines changed.
# This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
# Reference sources come from Git history: the commit that first added the anchor file. Text is read as UTF-8 and line endings are normalised to LF.
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
    if ($p.ExitCode -ne 0) { throw 'git failed' }
    return $o
}
function GitText([string]$anchorRel, [string]$rel) {
    try {
        $prefix = (RunGit @('rev-parse', '--show-prefix')).Trim()
        $commit = (RunGit @('log', '--diff-filter=A', '--format=%H', '-1', '--', $anchorRel.Replace('\', '/'))).Trim()
        if (-not $commit) { return $null }
        return ((RunGit @('show', ($commit + ':' + $prefix + $rel.Replace('\', '/')))) -replace "`r`n", "`n")
    }
    catch { return $null }
}
function WorkText([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $Root $rel))) -replace "`r`n", "`n") }
function Sha([string]$text) { return (-join ([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($text)) | ForEach-Object { $_.ToString('X2') })) }

$handler = [ResolveEventHandler]{
    param($s, $e)
    $name = ($e.Name -split ',')[0]
    $an = New-Object Reflection.AssemblyName($e.Name)
    if ($an.Version -and $an.Version.Major -eq 2 -and $name -in @('mscorlib', 'System', 'System.Windows.Forms', 'System.Drawing')) {
        $token = ($an.GetPublicKeyToken() | ForEach-Object { $_.ToString('x2') }) -join ''
        return [Reflection.Assembly]::ReflectionOnlyLoad("$name, Version=4.0.0.0, Culture=neutral, PublicKeyToken=$token")
    }
    foreach ($dir in @((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), (Join-Path $env:PUBLIC 'Documents\BveEx\2.0'), (Join-Path $env:PUBLIC 'Documents\BveEx'))) {
        foreach ($ext in '.dll', '.DLL') {
            $p = Join-Path $dir ($name + $ext)
            if (Test-Path $p) { return [Reflection.Assembly]::ReflectionOnlyLoadFrom($p) }
        }
    }
    return [Reflection.Assembly]::ReflectionOnlyLoad($e.Name)
}
[AppDomain]::CurrentDomain.add_ReflectionOnlyAssemblyResolve($handler)

function TokenHits([string]$dll, [string[]]$tokens) {
    $bytes = [IO.File]::ReadAllBytes($dll)
    $ascii = [Text.Encoding]::ASCII.GetString($bytes)
    $utf16 = [Text.Encoding]::Unicode.GetString($bytes)
    $utf16b = [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2))
    $present = @()
    foreach ($tok in $tokens) {
        $c = ([regex]::Matches($ascii, [regex]::Escape($tok))).Count + ([regex]::Matches($utf16, [regex]::Escape($tok))).Count + ([regex]::Matches($utf16b, [regex]::Escape($tok))).Count
        if ($c -gt 0) { $present += ($tok + ' x' + $c) }
    }
    return $present
}

function Inspect([string]$dll, [string[]]$mustBeAbsent) {
    Write-Host ("==== " + (Split-Path $dll -Leaf) + " ====")
    $item = Get-Item $dll
    "size   : {0} bytes" -f $item.Length
    "sha256 : " + (Get-FileHash $dll -Algorithm SHA256).Hash
    $v = $item.VersionInfo
    "version resource: FileDescription='{0}' ProductName='{1}' CompanyName='{2}' LegalCopyright='{3}' FileVersion={4} ProductVersion={5}" -f $v.FileDescription, $v.ProductName, $v.CompanyName, $v.LegalCopyright, $v.FileVersion, $v.ProductVersion
    $asm = [Reflection.Assembly]::ReflectionOnlyLoadFrom($dll)
    $kind = [Reflection.PortableExecutableKinds]0
    $machine = [Reflection.ImageFileMachine]::I386
    $asm.ManifestModule.GetPEKind([ref]$kind, [ref]$machine)
    "PE     : $kind / $machine  (ILOnly + I386 without Required32Bit/Preferred32Bit = AnyCPU)"
    foreach ($ca in [Reflection.CustomAttributeData]::GetCustomAttributes($asm)) { if ($ca.AttributeType.Name -like '*TargetFramework*') { "target : " + $ca.ToString() } }
    "references: " + (($asm.GetReferencedAssemblies() | ForEach-Object { $_.Name + ' ' + $_.Version }) -join '; ')
    $flags = [Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly'
    try { $types = $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ }; "(partial type load: " + $_.Exception.LoaderExceptions.Count + " loader exception(s))" }
    foreach ($t in $types) {
        $ctors = $t.GetConstructors([Reflection.BindingFlags]'Public,NonPublic,Instance') | ForEach-Object { $vis = if ($_.IsPublic) { 'public' } else { 'nonpublic' }; "$vis(" + (($_.GetParameters() | ForEach-Object { $_.ParameterType.Name }) -join ',') + ")" }
        $attrs = ([Reflection.CustomAttributeData]::GetCustomAttributes($t) | Where-Object { $_.AttributeType.Name -notmatch 'CompilerGenerated' } | ForEach-Object { $_.ToString() }) -join ' '
        "type {0} | public={1} | base={2} | interfaces=[{3}] | ctors=[{4}] {5}" -f $t.FullName, $t.IsPublic, $(if ($t.BaseType) { $t.BaseType.Name } else { '' }), (($t.GetInterfaces() | ForEach-Object { $_.Name }) -join ','), ($ctors -join ' '), $attrs
        foreach ($m in $t.GetMethods($flags)) { if (($m.Attributes -band [Reflection.MethodAttributes]::PinvokeImpl) -ne 0) { "   P/Invoke: " + $t.Name + "." + $m.Name } }
    }
    $present = TokenHits $dll $mustBeAbsent
    "forbidden tokens searched: " + $mustBeAbsent.Count + "  present: " + $(if ($present.Count -eq 0) { 'none' } else { $present -join ', ' })
    return [pscustomobject]@{ Present = $present; Version = $v; Asm = $asm }
}

# File I/O (FileStream, Mutex) is NOT in these lists on purpose: since Phase C1 it exists, but only in Shared\ObservationLog.cs (checked at source level below).
$common = 'AtsLogger', 'AtsEx', 'Python', 'python', 'UdpClient', 'Sockets', 'System.Net', 'TcpClient', 'HttpClient', 'WebClient', 'Registry', 'Microsoft.Win32', 'StreamWriter', 'StreamReader', 'WriteAllText', 'AppendAllText', 'ReadAllText', 'Preferences', 'InputPlugins', 'SetWindowsHookEx', 'keyboard', 'BveDllInventory', 'RuntimeProfile', 'SHA256', 'HashAlgorithm', 'FindWindow', 'SetWindowLong', 'NamedPipe', 'Global\', 'ProcessStartInfo', 'ShellExecute', 'CreateProcess', 'Launcher', 'main.py'
# Phase E3: the Caller now starts the application, so these five are allowed in the Caller DLL only (the Bridge list keeps them; the source checks below name the two Caller files that may use them)
$e3CallerAllowed = 'Python', 'python', 'ProcessStartInfo', 'Launcher', 'main.py', 'ShellExecute' # ShellExecute = the member name UseShellExecute, which the code sets to false
$callerAbsent = @($common | Where-Object { $_ -notin $e3CallerAllowed }) + @('BveEx.', 'BveEX.', 'BveTypes', 'PluginHost')
$bridgeAbsent = $common + @('Sleep', 'System.Threading.Timer', 'System.Timers', 'MessageBox', 'user32', 'DllImport', 'GetMethod', 'GetProperty', 'GetField', 'Activator', 'GetTypes', 'BindingFlags', 'System.Reflection.Emit', 'Class1', 'AtsLoggerPlugin')

$dist = Join-Path $Root 'dist'
$cDll = Join-Path $dist 'TSScoringPlugin.Caller.InputDevice.dll'
$bDll = Join-Path $dist 'TSScoringPlugin.BveEx.Bridge.Prototype.dll'
$outC = @(Inspect $cDll $callerAbsent); $outC[0..($outC.Count - 2)]; $ci = $outC[-1]
$outB = @(Inspect $bDll $bridgeAbsent); $outB[0..($outB.Count - 2)]; $bi = $outB[-1]

Write-Host '==== distribution hygiene ===='
$distFiles = @(Get-ChildItem $dist -File)
Check 'dist holds exactly the two DLLs (no PDB, no other file)' (($distFiles.Count -eq 2) -and (@($distFiles | Where-Object { $_.Name -in 'TSScoringPlugin.Caller.InputDevice.dll', 'TSScoringPlugin.BveEx.Bridge.Prototype.dll' }).Count -eq 2) -and (@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0))
Check 'Version: Caller 0.10.0.0 (Phase E3) and Bridge 0.6.0.0 (Phase C3 core, unchanged) in the version resources and assembly versions' (($ci.Version.FileVersion -eq '0.10.0.0') -and ($bi.Version.FileVersion -eq '0.6.0.0') -and ($ci.Asm.GetName().Version.ToString() -eq '0.10.0.0') -and ($bi.Asm.GetName().Version.ToString() -eq '0.6.0.0'))
Check 'Provider Coruge-to in both DLLs' (($ci.Version.CompanyName -eq 'Coruge-to') -and ($bi.Version.CompanyName -eq 'Coruge-to'))
Check 'No forbidden dependency token in either DLL' (($ci.Present.Count -eq 0) -and ($bi.Present.Count -eq 0))
Check 'Caller references only mscorlib, System, System.Core, System.Windows.Forms, Mackoy.IInputDevice' ((($ci.Asm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object) -join ',') -eq 'Mackoy.IInputDevice,mscorlib,System,System.Core,System.Windows.Forms')
$bRefs = ($bi.Asm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object) -join ','
"Bridge references: $bRefs"
Check 'Bridge references only mscorlib, System, System.Core, BveEx.PluginHost, BveTypes (BveTypes only to read three references in the E / F probe)' (@($bRefs -split ',' | Where-Object { $_ -notin 'mscorlib', 'System', 'System.Core', 'BveEx.PluginHost', 'BveTypes' }).Count -eq 0)
function PInvokeNames($asm) {
    $names = @()
    foreach ($t in $asm.GetTypes()) {
        foreach ($m in $t.GetMethods([Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly')) {
            if (($m.Attributes -band [Reflection.MethodAttributes]::PinvokeImpl) -ne 0) { $names += $m.Name }
        }
    }
    return @($names | Sort-Object -Unique)
}
$cPinvoke = PInvokeNames $ci.Asm
$bPinvoke = PInvokeNames $bi.Asm
Check 'Caller P/Invoke is user32 MessageBoxW only; Bridge has none' ((($cPinvoke -join ',') -eq 'MessageBoxW') -and ($bPinvoke.Count -eq 0))

Write-Host '==== source checks (comment lines are skipped) ===='
# Phase L1: this script verifies the CURRENT BveEX product only. The AtsEX legacy adapter (Bridge\Legacy\) has its own verification (Tools\Verify-PhaseL1.ps1).
$srcFiles = @(Get-ChildItem $Root -Recurse -Include *.cs | Where-Object { $_.FullName -notlike '*\obj\*' -and $_.FullName -notlike '*\Bridge\Legacy\*' })
function SrcHits([string]$pattern) {
    $out = @()
    foreach ($f in $srcFiles) {
        $n = 0
        foreach ($line in [IO.File]::ReadAllLines($f.FullName)) { $n++; if ($line.TrimStart().StartsWith('//')) { continue }; if ($line -match $pattern) { $out += ($f.FullName.Substring($Root.Length + 1) + ':' + $n) } }
    }
    return $out
}
function OnlyIn([string]$pattern, [string[]]$allowedRelative) {
    $hits = SrcHits $pattern
    $bad = @($hits | Where-Object { $rel = ($_ -split ':')[0]; $rel -notin $allowedRelative })
    return [pscustomobject]@{ Hits = $hits; Bad = $bad }
}
foreach ($p in 'UdpClient', 'TcpClient', 'Socket', 'Registry', 'Microsoft\.Win32', 'SetWindowsHookEx', 'Thread\.Sleep', 'System\.Timers', 'NamedPipe', 'Global\\\\') {
    $h = SrcHits $p
    Check ("source: '$p' absent from all sources") ($h.Count -eq 0)
}
# Phase E3: starting the application is the job of exactly two Caller files (AppProcessManager.cs, LauncherConfig.cs); the Bridge and every other file stay free of it.
$e3Files = @('Caller\src\AppProcessManager.cs', 'Caller\src\LauncherConfig.cs')
foreach ($p in 'Process\.Start', 'ProcessStartInfo', 'Python', 'python', 'main\.py') {
    $h = OnlyIn $p $e3Files
    Check ("source: '$p' only in the two Phase E3 Caller files") ($h.Bad.Count -eq 0)
}
$fio = OnlyIn 'FileStream|FileMode|\bFile\.|StreamWriter|AppendAllText' @('Shared\ObservationLog.cs', 'Caller\src\LauncherConfig.cs')
Check 'file I/O exists ONLY in Shared\ObservationLog.cs (the observation log) and, since Phase E3, Caller\src\LauncherConfig.cs (reads the launcher configuration)' ($fio.Bad.Count -eq 0 -and $fio.Hits.Count -gt 0)
$mtx = OnlyIn 'new Mutex|Mutex ' @('Shared\ObservationLog.cs')
Check 'Mutex exists ONLY in Shared\ObservationLog.cs' ($mtx.Bad.Count -eq 0)
$dll = OnlyIn 'DllImport' @('Caller\src\HandshakeSession.cs', 'Caller\src\TsScoringCallerInputDevice.cs')
Check 'DllImport only in the two Caller files that already had it in Phase B (MessageBoxW)' ($dll.Bad.Count -eq 0)
$thr = OnlyIn 'new Thread\(' @('Caller\src\HandshakeSession.cs', 'Caller\src\AppProcessManager.cs')
Check 'new Thread only in Caller\src\HandshakeSession.cs (monitor + notice threads, as in Phase B) and Caller\src\AppProcessManager.cs (Phase E3 worker); none in the Bridge or the log' ($thr.Bad.Count -eq 0)

Write-Host '==== Phase B contract unchanged ===='
$hpFile = Join-Path $Root 'Shared\HandshakeProtocol.cs'
$hpBText = GitText 'Shared\HandshakeProtocol.cs' 'Shared\HandshakeProtocol.cs'
$hpLinesNow = (WorkText 'Shared\HandshakeProtocol.cs') -split "`n"
$hpLinesB = if ($hpBText) { $hpBText -split "`n" } else { @() }
$hpRemoved = @(Compare-Object $hpLinesB $hpLinesNow | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject.Trim() })
$hpAdded = @(Compare-Object $hpLinesB $hpLinesNow | Where-Object { $_.SideIndicator -eq '=>' })
"HandshakeProtocol.cs vs Phase B: $($hpRemoved.Count) Phase B line(s) no longer present, $($hpAdded.Count) lines added. Removed lines:"
$hpRemoved | ForEach-Object { "   - " + $_ }
Check 'Shared\HandshakeProtocol.cs vs Phase B: ONLY ADDITIONS except one header comment line (the old "ScenarioReady ... NOT in Phase B" sentence); every Phase B line of code, name, BridgeInfo v3 and timing is still there' (($hpLinesB.Count -gt 0) -and ($hpRemoved.Count -eq 1) -and ($hpRemoved[0] -match '^//\s+ScenarioReady\s+the scenario is loaded'))
$hp = [IO.File]::ReadAllText($hpFile)
Check 'timings: BridgeMissingTimeoutMs = 500, TargetBridgeAvailableMs = 500, CallerPollMs = 20, BridgePollMs = 100' (($hp -match 'BridgeMissingTimeoutMs = 500;') -and ($hp -match 'TargetBridgeAvailableMs = 500;') -and ($hp -match 'CallerPollMs = 20;') -and ($hp -match 'BridgePollMs = 100;'))
$named = @(([regex]::Matches((($srcFiles | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"), 'Local\\\\TSScoringPlugin\.v1\."\s*\+\s*\w+\s*\+\s*"\.(\w+)')) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
"named kernel object kinds in sources: " + ($named -join ', ')
Check 'named objects are exactly the Phase B five, the two private log guards and the two Phase C3 objects (ScenarioReady event, ScenarioState block)' (($named -join ',') -eq 'BridgeAvailable,BridgeInfo,Enabled,ObsLogLock,ObsLogRun,Ready,ScenarioReady,ScenarioState,Stop')
$hsNow = (WorkText 'Caller\src\HandshakeSession.cs') -split "`n"
$hsBText = GitText 'Shared\HandshakeProtocol.cs' 'Caller\src\HandshakeSession.cs'
$hsB = if ($hsBText) { $hsBText -split "`n" } else { @() }
$removed = @(Compare-Object $hsB $hsNow | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject.Trim() })
$added = @(Compare-Object $hsB $hsNow | Where-Object { $_.SideIndicator -eq '=>' })
"HandshakeSession.cs vs Phase B: $($removed.Count) Phase B lines no longer present, $($added.Count) lines added. Removed lines:"
$removed | ForEach-Object { "   - " + $_ }
# Phase M1: only CODE lines count here (comment lines and log-text Obs( lines are rewritten by M1; the MessageBox contract is proven line by line in Tests\Test-DependencyNoticeM1.ps1)
$removedCode = @($removed | Where-Object { $_ -notmatch '^//' -and $_ -notmatch '^Obs\(' })
Check 'HandshakeSession.cs: NoticeText (both lines), MessageBox flags and the title constant are untouched' (@($removedCode | Where-Object { $_ -match 'NoticeText|TS Scoring|MessageBoxW|ProductDisplayName|MB_|BveEX|BveEx' }).Count -eq 0)
Check 'HandshakeSession.cs: no timeout / state-machine line was removed (only the notice condition and status text were rewritten; Phase M1 moved the notice latch, no phase transition)' (@($removedCode | Where-Object { $_ -match 'TargetBridgeAvailableMs|CallerPollMs|case CallerPhase|phase = CallerPhase|BridgeMissingTimeoutMs = ' }).Count -le 0)

Write-Host '==== Phase C1 observation checks ===='
$obs = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\ScenarioObserver.cs'))
$bridgeSrc = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\TsScoringBridgePrototype.cs'))
$callerSrc = [IO.File]::ReadAllText((Join-Path $Root 'Caller\src\HandshakeSession.cs')) + [IO.File]::ReadAllText((Join-Path $Root 'Caller\src\TsScoringCallerInputDevice.cs'))
Check 'ScenarioGeneration exists (counter, in every Track A line)' (($obs -match 'scenarioGeneration') -and ($obs -match '"ScenarioGeneration="'))
Check 'candidates A to F all defined and all logged (CAND_<id>)' (($obs -match 'const string A') -and ($obs -match 'const string B') -and ($obs -match 'const string C') -and ($obs -match 'const string D') -and ($obs -match 'const string E') -and ($obs -match 'const string F') -and ($obs -match '"CAND_" \+ id'))
Check 'Track A and Track B identified in the log format (T=A|B|AB) and used by Bridge and Caller' (((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match ' T=') -and ($obs -match 'TrackA = "A"') -and ($bridgeSrc -match '"AB"') -and ($bridgeSrc -match '"B"') -and ($callerSrc -match 'Write\("B"') -and ($callerSrc -match 'Write\("A"'))
Check 'Caller Track B points present: ctor, Enabled, monitor, first check, first Present, Ready first Present, 500 ms, judge, pre-show, show call, dispose' (@('CALLER_CTOR_BEGIN', 'CALLER_CTOR_END', 'CALLER_ENABLED_CREATED', 'MONITOR_LOOP_BEGIN', 'AVAIL_FIRST_CHECK', 'AVAIL_FIRST_PRESENT', 'READY_FIRST_PRESENT', 'TIMEOUT_REACHED', 'NOTICE_JUDGE_BEGIN', 'NOTICE_PRESHOW', 'NOTICE_SHOW_CALL', 'NOTICE_SUPPRESSED', 'CALLER_DISPOSE_BEGIN', 'CALLER_DISPOSE_END' | Where-Object { $callerSrc -notmatch $_ }).Count -eq 0)
Check 'Bridge Track B points present: ctor, AvailableCreate begin/ok, ReadyCreate begin/ok, subscriptions, first Tick, Dispose, Ready / Available disposed' (@('BRIDGE_CTOR_BEGIN', 'BRIDGE_CTOR_END', 'AVAIL_CREATE_BEGIN', 'AVAIL_CREATE_OK', 'READY_CREATE_BEGIN', 'READY_CREATE_OK', 'SUBSCRIBE_DONE', 'BRIDGE_FIRST_TICK', 'BRIDGE_DISPOSE_BEGIN', 'BRIDGE_DISPOSE_END', 'READY_DISPOSED', 'AVAIL_DISPOSED' | Where-Object { $bridgeSrc -notmatch $_ }).Count -eq 0)
Check 'only real BveEX events are subscribed (ScenarioOpened, ScenarioClosed, PreviewScenarioCreated, ScenarioCreated, PreviewTick, PostTick, AllExtensionsLoaded)' (@('h.ScenarioOpened +=', 'h.ScenarioClosed +=', 'h.PreviewScenarioCreated +=', 'h.ScenarioCreated +=', 'h.PreviewTick +=', 'h.PostTick +=', 'Extensions.AllExtensionsLoaded +=' | Where-Object { $bridgeSrc -notmatch [regex]::Escape($_) }).Count -eq 0)
Check 'ScenarioObserver creates no named object, thread, timer, file or notification (still a log-only observer)' (($obs -notmatch 'EventWaitHandle|new Thread|Timer|FileStream|MemoryMappedFile|Mutex|ThreadPool|Task\.'))
Check 'Bridge constructor publishes BridgeAvailable BEFORE the observation wiring (observation can not delay it)' ($bridgeSrc.IndexOf('PublishAvailability();') -lt $bridgeSrc.IndexOf('SubscribeObservers();'))
Check 'log failures are swallowed: ObservationLog.Write has try/catch and never rethrows' ((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'internal static void Write\([\s\S]*?catch\s*\{[\s\S]*?\}')
Check 'log initialisation: per-PID run marker, FileMode.Create (truncate) only for the first writer of a run' ((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'createdNew' -and (Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'FileMode\.Create')
Check 'log path comes from the OS at run time (no user or path text in the source)' ((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'SpecialFolder\.UserProfile')
$cnt = OnlyIn '\bmain\.py\b|python' $e3Files
Check 'Python is neither started nor named in any source line outside the two Phase E3 Caller files' ($cnt.Bad.Count -eq 0)

Write-Host '==== Phase C3 ScenarioReady checks ===='
# the C1 observation contract: the observer and the log writer are byte-identical to Phase C1
foreach ($rel in 'Bridge\src\ScenarioObserver.cs', 'Shared\ObservationLog.cs') {
    $c1Text = GitText 'Bridge\src\ScenarioObserver.cs' $rel
    $h1 = if ($c1Text) { Sha $c1Text } else { 'PHASE-C1-COMMIT-NOT-FOUND' }
    $h3 = Sha (WorkText $rel)
    "$rel sha256 (LF-normalised) now / Phase C1 commit: $h3 / $h1"
    Check "$rel is identical to the Phase C1 commit (observation contract: Track A/B lines, candidates A-F, TICK_GAP, log file name and format)" ($h1 -eq $h3)
}
$sr = SrcHits 'ScenarioReady'
$srAllowed = 'Bridge\src\ScenarioObserver.cs', 'Bridge\src\ScenarioReadyTracker.cs', 'Bridge\src\ScenarioReadyPublisher.cs', 'Bridge\src\TsScoringBridgePrototype.cs', 'Bridge\src\AssemblyInfo.cs', 'Caller\src\AssemblyInfo.cs', 'Caller\src\HandshakeSession.cs', 'Caller\src\DrivingActivityState.cs', 'Shared\HandshakeProtocol.cs'
$srOutside = @($sr | Where-Object { ($_ -split ':')[0] -notin $srAllowed })
"ScenarioReady-named lines outside the allowed files: " + ($srOutside -join ', ')
Check 'ScenarioReady-named code exists only in the tracker, the publisher, the Current adapter (Bridge), the Caller reader, the Caller DrivingActive state (Phase D1), the shared protocol, the candidate vocabulary and the two assembly descriptions' ($srOutside.Count -eq 0)
# Current-specific BveEX API must not leak into the shared / host independent layer (string literals and comments are stripped first; case-sensitive)
$leakHits = @()
foreach ($f in $srcFiles) {
    $n = 0
    foreach ($line in [IO.File]::ReadAllLines($f.FullName)) {
        $n++
        $code = [regex]::Replace($line, '"(?:[^"\\]|\\.)*"', '""')
        $code = [regex]::Replace($code, '//.*$', '')
        if ($code -cmatch 'BveEx|BveTypes|IBveHacker|PluginBuilder|ClassWrappers|AssemblyPluginBase|IExtension|PluginAttribute|AtsEx') { $leakHits += ($f.FullName.Substring($Root.Length + 1) + ':' + $n) }
    }
}
$leakBad = @($leakHits | Where-Object { ($_ -split ':')[0] -ne 'Bridge\src\TsScoringBridgePrototype.cs' })
"BveEX-specific API in code outside the Current adapter: " + ($leakBad -join ', ')
Check 'Current-only API (BveEx / BveTypes / IBveHacker / PluginBuilder / ClassWrappers / AtsEx) appears in code ONLY in Bridge\src\TsScoringBridgePrototype.cs (the Current adapter); tracker, publisher, observer, shared protocol and the whole Caller are host independent' (($leakBad.Count -eq 0) -and ($leakHits.Count -gt 0))
$trk = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\ScenarioReadyTracker.cs'))
$estCalls = ([regex]::Matches($trk, 'EstablishLocked\(')).Count
$postBody = [regex]::Match($trk, 'public void OnPostTick\(\)[\s\S]*?\n        \}\r?\n').Value
Check 'establishment (level = true) has exactly one place and one call site (the Tick); PostTick can not set it' (([regex]::Matches($trk, 'level = true;')).Count -eq 1 -and $estCalls -eq 2 -and $postBody.Length -gt 100 -and $postBody -notmatch 'EstablishLocked|level = true')
Check 'tracker: ScenarioClosed / ScenarioOpened / Dispose clear; Pause, TICK_GAP, isReload and IsScenarioCreated are not inputs (no clock read in the decision, OnScenarioOpened takes no argument)' (($trk -match 'ClearLocked\("closed"\)') -and ($trk -match 'ClearLocked\("opened-reset"\)') -and ($trk -match 'ClearLocked\("bridge-dispose"\)') -and ($trk -match 'public void OnScenarioOpened\(\)') -and (([regex]::Matches($trk, 'nowMs\(\)')).Count -le 2))
Check 'tracker: the reset happens BEFORE the generation number moves (ClearLocked("opened-reset") precedes ScenarioGenerationRule.Next in OnScenarioOpened)' ($trk.IndexOf('ClearLocked("opened-reset")') -ge 0 -and $trk.IndexOf('ClearLocked("opened-reset")') -lt $trk.IndexOf('ScenarioGenerationRule.Next(generation)'))
$st = [regex]::Match($hp, 'internal struct ScenarioState[\s\S]*?public bool Ready').Value
$stFields = @([regex]::Matches($st, 'public (\w+) (\w+);') | ForEach-Object { $_.Groups[1].Value + ' ' + $_.Groups[2].Value })
"ScenarioState fields: " + ($stFields -join ', ')
Check 'shared state block holds int32 numbers only (ProtocolVersion, BveProcessId, ScenarioGeneration, IsScenarioReady, Sequence, Check): no string, path, scenario or vehicle name' (($stFields -join ',') -eq 'int ProtocolVersion,int BveProcessId,int ScenarioGeneration,int IsScenarioReady,int Sequence,int Check')
Check 'generation overflow policy is explicit (wrap to 1, never 0 / negative) and documented in the shared protocol' (($hp -match 'Overflow policy') -and ($hp -match 'return First;') -and ($hp -match 'current == int\.MaxValue'))
$bridgeSrc2 = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\TsScoringBridgePrototype.cs'))
Check 'Bridge: Release() withdraws ScenarioReady first (handshake lost) and Dispose clears ScenarioReady before Release; tracker runs AFTER the Phase B handshake step in Tick' (($bridgeSrc2.IndexOf('tracker.OnHandshakeLost(reason)') -ge 0) -and ($bridgeSrc2.IndexOf('tracker.OnDispose()') -lt $bridgeSrc2.IndexOf('Release("bridge-dispose")')) -and ($bridgeSrc2.IndexOf('HandshakeStep();') -lt $bridgeSrc2.IndexOf('tracker.OnTick()')))
Check 'Bridge: the PostTick handler only calls the diagnostic tracker.OnPostTick (no direct state change)' ($bridgeSrc2 -match 'tracker\.OnPostTick\(\)')
# Phase B / C1 files: what changed in the Caller vs Phase C1
$hsC1Text = GitText 'Bridge\src\ScenarioObserver.cs' 'Caller\src\HandshakeSession.cs'
if ($hsC1Text) {
    $r3 = @(Compare-Object ($hsC1Text -split "`n") ((WorkText 'Caller\src\HandshakeSession.cs') -split "`n") | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject.Trim() })
    "HandshakeSession.cs vs Phase C1: lines of C1 no longer present:"
    $r3 | ForEach-Object { "   - " + $_ }
    $r3Code = @($r3 | Where-Object { $_ -notmatch '^//' -and $_ -notmatch '^Obs\(' })
    Check 'HandshakeSession.cs vs Phase C1: the two status-text lines (Phase text, ScenarioReady line) were rewritten; no timing, phase-transition, NoticeText, title or MessageBox line was removed (Phase M1 only rewrote the notice trigger and latch)' (@($r3 | Where-Object { $_ -match 'Phase   : C1 observation build|ScenarioReady    : Not implemented in Phase B' }).Count -eq 2 -and @($r3Code | Where-Object { $_ -match 'TargetBridgeAvailableMs|CallerPollMs|case CallerPhase|phase = CallerPhase|NoticeText|ProductDisplayName|MessageBoxW|MB_' }).Count -eq 0)
}
Check 'notice wording and title are untouched: NoticeText (two lines), ProductDisplayName "TS Scoring", MB flags' ((([IO.File]::ReadAllText((Join-Path $Root 'Caller\src\HandshakeSession.cs'))) -match [regex]::Escape('internal const string ProductDisplayName = "TS Scoring";')) -and (([IO.File]::ReadAllText((Join-Path $Root 'Caller\src\HandshakeSession.cs'))) -match 'MessageBoxW\(IntPtr\.Zero, text, ProductDisplayName, MB_OK \| MB_ICONINFORMATION \| MB_SETFOREGROUND \| MB_TOPMOST\)'))

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
