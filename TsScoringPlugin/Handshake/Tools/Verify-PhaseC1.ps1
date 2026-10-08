# PHASE C1 - read-only static verification of the built Caller and Bridge DLLs and of the sources (nothing is executed).
# Keeps the Phase B checks (contract, timings, notice text, forbidden dependencies) and adds the Phase C1 observation checks.
# Phase B reference sources are read from Git history (the commit that first added Shared\HandshakeProtocol.cs; read-only) to prove which lines changed.
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
$callerAbsent = $common + @('BveEx.', 'BveEX.', 'BveTypes', 'PluginHost')
$bridgeAbsent = $common + @('Sleep', 'System.Threading.Timer', 'System.Timers', 'MessageBox', 'user32', 'DllImport', 'GetMethod', 'GetProperty', 'GetField', 'Activator', 'GetTypes', 'BindingFlags', 'System.Reflection.Emit', 'Class1', 'AtsLoggerPlugin')

$dist = Join-Path $Root 'dist'
$cDll = Join-Path $dist 'TSScoringPlugin.Caller.InputDevice.dll'
$bDll = Join-Path $dist 'TSScoringPlugin.BveEx.Bridge.Prototype.dll'
$outC = @(Inspect $cDll $callerAbsent); $outC[0..($outC.Count - 2)]; $ci = $outC[-1]
$outB = @(Inspect $bDll $bridgeAbsent); $outB[0..($outB.Count - 2)]; $bi = $outB[-1]

Write-Host '==== distribution hygiene ===='
$distFiles = @(Get-ChildItem $dist -File)
Check 'dist holds exactly the two DLLs (no PDB, no other file)' (($distFiles.Count -eq 2) -and (@($distFiles | Where-Object { $_.Name -in 'TSScoringPlugin.Caller.InputDevice.dll', 'TSScoringPlugin.BveEx.Bridge.Prototype.dll' }).Count -eq 2) -and (@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0))
Check 'Version 0.5.0.0 in both DLL version resources and assembly versions' (($ci.Version.FileVersion -eq '0.5.0.0') -and ($bi.Version.FileVersion -eq '0.5.0.0') -and ($ci.Asm.GetName().Version.ToString() -eq '0.5.0.0') -and ($bi.Asm.GetName().Version.ToString() -eq '0.5.0.0'))
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
$srcFiles = @(Get-ChildItem $Root -Recurse -Include *.cs | Where-Object { $_.FullName -notlike '*\obj\*' })
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
foreach ($p in 'Process\.Start', 'ProcessStartInfo', 'UdpClient', 'TcpClient', 'Socket', 'Registry', 'Microsoft\.Win32', 'SetWindowsHookEx', 'Thread\.Sleep', 'System\.Timers', 'NamedPipe', 'Global\\\\', 'Python', 'python', 'main\.py') {
    $h = SrcHits $p
    Check ("source: '$p' absent from all sources") ($h.Count -eq 0)
}
$fio = OnlyIn 'FileStream|FileMode|\bFile\.|StreamWriter|AppendAllText' @('Shared\ObservationLog.cs')
Check 'file I/O exists ONLY in Shared\ObservationLog.cs (the observation log)' ($fio.Bad.Count -eq 0 -and $fio.Hits.Count -gt 0)
$mtx = OnlyIn 'new Mutex|Mutex ' @('Shared\ObservationLog.cs')
Check 'Mutex exists ONLY in Shared\ObservationLog.cs' ($mtx.Bad.Count -eq 0)
$dll = OnlyIn 'DllImport' @('Caller\src\HandshakeSession.cs', 'Caller\src\TsScoringCallerInputDevice.cs')
Check 'DllImport only in the two Caller files that already had it in Phase B (MessageBoxW)' ($dll.Bad.Count -eq 0)
$thr = OnlyIn 'new Thread\(' @('Caller\src\HandshakeSession.cs')
Check 'new Thread only in Caller\src\HandshakeSession.cs (monitor + notice threads, as in Phase B); none in the Bridge or the log' ($thr.Bad.Count -eq 0)

Write-Host '==== Phase B contract unchanged ===='
$hpBText = GitText 'Shared\HandshakeProtocol.cs' 'Shared\HandshakeProtocol.cs'
$hpNow = Sha (WorkText 'Shared\HandshakeProtocol.cs')
$hpB = if ($hpBText) { Sha $hpBText } else { 'PHASE-B-COMMIT-NOT-FOUND' }
"HandshakeProtocol.cs sha256 (LF-normalised) now / Phase B commit: $hpNow / $hpB"
Check 'Shared\HandshakeProtocol.cs is identical to the Phase B commit (event names, BridgeInfo v3, all timings; line endings ignored)' ($hpNow -eq $hpB)
$hp = [IO.File]::ReadAllText((Join-Path $Root 'Shared\HandshakeProtocol.cs'))
Check 'timings: BridgeMissingTimeoutMs = 500, TargetBridgeAvailableMs = 500, CallerPollMs = 20, BridgePollMs = 100' (($hp -match 'BridgeMissingTimeoutMs = 500;') -and ($hp -match 'TargetBridgeAvailableMs = 500;') -and ($hp -match 'CallerPollMs = 20;') -and ($hp -match 'BridgePollMs = 100;'))
$named = @(([regex]::Matches((($srcFiles | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"), 'Local\\\\TSScoringPlugin\.v1\."\s*\+\s*\w+\s*\+\s*"\.(\w+)')) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
"named kernel object kinds in sources: " + ($named -join ', ')
Check 'named objects are exactly the Phase B five plus the two private log guards (no ScenarioReady object)' (($named -join ',') -eq 'BridgeAvailable,BridgeInfo,Enabled,ObsLogLock,ObsLogRun,Ready,Stop')
$hsNow = (WorkText 'Caller\src\HandshakeSession.cs') -split "`n"
$hsBText = GitText 'Shared\HandshakeProtocol.cs' 'Caller\src\HandshakeSession.cs'
$hsB = if ($hsBText) { $hsBText -split "`n" } else { @() }
$removed = @(Compare-Object $hsB $hsNow | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject.Trim() })
$added = @(Compare-Object $hsB $hsNow | Where-Object { $_.SideIndicator -eq '=>' })
"HandshakeSession.cs vs Phase B: $($removed.Count) Phase B lines no longer present, $($added.Count) lines added. Removed lines:"
$removed | ForEach-Object { "   - " + $_ }
Check 'HandshakeSession.cs: NoticeText (both lines), MessageBox flags and the title constant are untouched' (@($removed | Where-Object { $_ -match 'NoticeText|TS Scoring|MessageBoxW|ProductDisplayName|MB_|BveEX|BveEx' }).Count -eq 0)
Check 'HandshakeSession.cs: no timeout / state-machine line was removed (only the notice condition and status text were rewritten)' (@($removed | Where-Object { $_ -match 'BridgeMissingTimeoutMs|TargetBridgeAvailableMs|CallerPollMs|case CallerPhase|phase = CallerPhase' }).Count -le 0)

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
$sr = SrcHits 'ScenarioReady'
$srOutside = @($sr | Where-Object { ($_ -split ':')[0] -notin 'Bridge\src\ScenarioObserver.cs', 'Caller\src\HandshakeSession.cs', 'Shared\HandshakeProtocol.cs' })
Check 'no ScenarioReady-named code outside the candidate vocabulary (ScenarioReadyCandidates) and the existing Phase B status text' ($srOutside.Count -eq 0)
Check 'ScenarioObserver creates no named object, thread, timer, file or notification' (($obs -notmatch 'EventWaitHandle|new Thread|Timer|FileStream|MemoryMappedFile|Mutex|ThreadPool|Task\.'))
Check 'Bridge constructor publishes BridgeAvailable BEFORE the observation wiring (observation can not delay it)' ($bridgeSrc.IndexOf('PublishAvailability();') -lt $bridgeSrc.IndexOf('SubscribeObservers();'))
Check 'log failures are swallowed: ObservationLog.Write has try/catch and never rethrows' ((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'internal static void Write\([\s\S]*?catch\s*\{[\s\S]*?\}')
Check 'log initialisation: per-PID run marker, FileMode.Create (truncate) only for the first writer of a run' ((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'createdNew' -and (Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'FileMode\.Create')
Check 'log path comes from the OS at run time (no user or path text in the source)' ((Get-Content (Join-Path $Root 'Shared\ObservationLog.cs') -Raw) -match 'SpecialFolder\.UserProfile')
$cnt = SrcHits '\bmain\.py\b|python'
Check 'Python is neither started nor named in any source line' ($cnt.Count -eq 0)

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
