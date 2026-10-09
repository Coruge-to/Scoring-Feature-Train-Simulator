# PHASE L1 - read-only static verification of the AtsEX LEGACY Bridge (built DLL + sources) and of the Current/Legacy boundary (nothing is executed).
# Proves: the Legacy adapter is the only place that names AtsEX types, the Current product files are byte-identical to the Phase C3 baseline commit
# (except the one scoping line of Verify-PhaseC3.ps1), no forbidden dependency exists, MessageBox / 500 ms / provider / privacy / hygiene rules hold.
# This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Baseline = 'fe2b223ee20db1a682468e6b75168f39ed7e9942',
    [string]$LegacyDll = (Join-Path (Split-Path $PSScriptRoot -Parent) 'Bridge\Legacy\out\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')
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
$prefix = (RunGit @('rev-parse', '--show-prefix')).Trim()
function BaseText([string]$rel) { return ((RunGit @('show', ($Baseline + ':' + $prefix + $rel.Replace('\', '/')))) -replace "`r`n", "`n") }
function WorkText([string]$rel) { return (([IO.File]::ReadAllText((Join-Path $Root $rel))) -replace "`r`n", "`n") }

$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$handler = [ResolveEventHandler]{
    param($s, $e)
    $name = ($e.Name -split ',')[0]
    $an = New-Object Reflection.AssemblyName($e.Name)
    if ($an.Version -and $an.Version.Major -eq 2 -and $name -in @('mscorlib', 'System', 'System.Windows.Forms', 'System.Drawing')) {
        $token = ($an.GetPublicKeyToken() | ForEach-Object { $_.ToString('x2') }) -join ''
        return [Reflection.Assembly]::ReflectionOnlyLoad("$name, Version=4.0.0.0, Culture=neutral, PublicKeyToken=$token")
    }
    foreach ($dir in @((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), $legacyHost)) {
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

# ---------------------------------------------------------------------------------------------------------------------------------
Write-Host '==== Legacy DLL ===='
$item = Get-Item $LegacyDll
"size   : {0} bytes" -f $item.Length
"sha256 : " + (Get-FileHash $LegacyDll -Algorithm SHA256).Hash
$v = $item.VersionInfo
"version resource: FileDescription='{0}' ProductName='{1}' CompanyName='{2}' LegalCopyright='{3}' FileVersion={4}" -f $v.FileDescription, $v.ProductName, $v.CompanyName, $v.LegalCopyright, $v.FileVersion
$asm = [Reflection.Assembly]::ReflectionOnlyLoadFrom($LegacyDll)
$kind = [Reflection.PortableExecutableKinds]0
$machine = [Reflection.ImageFileMachine]::I386
$asm.ManifestModule.GetPEKind([ref]$kind, [ref]$machine)
"PE     : $kind / $machine"
$targetFw = ''
foreach ($ca in [Reflection.CustomAttributeData]::GetCustomAttributes($asm)) { if ($ca.AttributeType.Name -like '*TargetFramework*') { $targetFw = $ca.ToString(); "target : " + $targetFw } }
$refs = @($asm.GetReferencedAssemblies() | ForEach-Object { $_.Name } | Sort-Object)
"references: " + ($refs -join ', ')
try { $types = $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ } }
foreach ($t in $types) { "type {0} | public={1} | base={2}" -f $t.FullName, $t.IsPublic, $(if ($t.BaseType) { $t.BaseType.Name } else { '' }) }

$common = 'AtsLogger', 'Python', 'python', 'UdpClient', 'Sockets', 'System.Net', 'TcpClient', 'HttpClient', 'WebClient', 'Registry', 'Microsoft.Win32', 'StreamWriter', 'StreamReader', 'WriteAllText', 'AppendAllText', 'ReadAllText', 'Preferences', 'InputPlugins', 'SetWindowsHookEx', 'keyboard', 'BveDllInventory', 'RuntimeProfile', 'SHA256', 'HashAlgorithm', 'FindWindow', 'SetWindowLong', 'NamedPipe', 'Global\', 'ProcessStartInfo', 'ShellExecute', 'CreateProcess', 'Launcher', 'main.py'
$legacyAbsent = $common + @('Sleep', 'System.Threading.Timer', 'System.Timers', 'MessageBox', 'user32', 'DllImport', 'GetMethod', 'GetProperty', 'GetField', 'Activator', 'GetTypes', 'BindingFlags', 'System.Reflection.Emit', 'Class1', 'AtsLoggerPlugin', 'BveEx.PluginHost', 'BveEX.PluginHost', 'BveEx.Caller')
$present = TokenHits $LegacyDll $legacyAbsent
"forbidden tokens searched: " + $legacyAbsent.Count + "  present: " + $(if ($present.Count -eq 0) { 'none' } else { $present -join ', ' })
$pinvoke = @()
foreach ($t in $types) { foreach ($m in $t.GetMethods([Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly')) { if (($m.Attributes -band [Reflection.MethodAttributes]::PinvokeImpl) -ne 0) { $pinvoke += $m.Name } } }

Write-Host '==== Legacy distribution hygiene ===='
$outDir = Split-Path $LegacyDll -Parent
$outFiles = @(Get-ChildItem $outDir -File)
Check 'Legacy out holds exactly the one Legacy DLL (no PDB, no third-party DLL, no other file)' (($outFiles.Count -eq 1) -and ($outFiles[0].Name -eq 'TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll') -and (@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0))
Check 'DLL name is TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll (the Current name TSScoringPlugin.BveEx.Bridge.Prototype.dll is unchanged and different)' (($item.Name -eq 'TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll') -and ($item.Name -ne 'TSScoringPlugin.BveEx.Bridge.Prototype.dll'))
Check 'Version 0.6.0.0 (the shared core version) in the version resource and assembly version' (($v.FileVersion -eq '0.6.0.0') -and ($asm.GetName().Version.ToString() -eq '0.6.0.0'))
Check 'Provider Coruge-to, product TS Scoring' (($v.CompanyName -eq 'Coruge-to') -and ($v.ProductName -eq 'TS Scoring') -and ($v.LegalCopyright -match 'Coruge-to'))
Check 'Target .NET Framework 4.8, AnyCPU (ILOnly, no Required32Bit / Preferred32Bit), managed code only' (($targetFw -match 'v4\.8') -and ($kind.ToString() -eq 'ILOnly') -and ($machine.ToString() -eq 'I386'))
Check 'No forbidden dependency token in the Legacy DLL (Python, UDP, sockets, registry, hooks, file API outside the log, MessageBox, P/Invoke, BveEx host)' ($present.Count -eq 0)
Check 'Legacy DLL references only mscorlib, System, System.Core, AtsEx.PluginHost, BveTypes' ((@($refs | Where-Object { $_ -notin 'mscorlib', 'System', 'System.Core', 'AtsEx.PluginHost', 'BveTypes' }).Count -eq 0) -and ($refs -contains 'AtsEx.PluginHost') -and ($refs -contains 'BveTypes'))
Check 'Legacy DLL has no P/Invoke at all (the Caller keeps the only MessageBoxW)' ($pinvoke.Count -eq 0)
$tn = @($types | ForEach-Object { $_.Name })
Check 'Legacy DLL types: the adapter, the control plane and the shared core only' ((($tn -contains 'TsScoringLegacyBridgePrototype') -and ($tn -contains 'HandshakeControlPlane') -and ($tn -contains 'ScenarioReadyTracker') -and ($tn -contains 'ScenarioReadyPublisher') -and ($tn -contains 'ScenarioObserver') -and ($tn -contains 'HandshakeProtocol') -and ($tn -contains 'ObservationLog')) -and (-not ($tn -contains 'TsScoringBridgePrototype')) -and (-not ($tn -contains 'HandshakeSession')))
$ctor = @($types | Where-Object { $_.Name -eq 'TsScoringLegacyBridgePrototype' })[0]
Check 'Adapter: public, derives from AssemblyPluginBase, implements IExtension, [Plugin] attribute present, public ctor(PluginBuilder)' (($ctor.IsPublic) -and ($ctor.BaseType.Name -eq 'AssemblyPluginBase') -and (@($ctor.GetInterfaces() | Where-Object { $_.Name -eq 'IExtension' }).Count -eq 1) -and (@([Reflection.CustomAttributeData]::GetCustomAttributes($ctor) | Where-Object { $_.AttributeType.Name -eq 'PluginAttribute' }).Count -eq 1) -and (@($ctor.GetConstructors() | Where-Object { $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'PluginBuilder' }).Count -eq 1))

# ---------------------------------------------------------------------------------------------------------------------------------
Write-Host '==== source checks: Legacy scope (comment lines skipped) ===='
$legacyDir = Join-Path $Root 'Bridge\Legacy'
$legacySrc = @(Get-ChildItem (Join-Path $legacyDir 'src') -Filter *.cs)
$allSrc = @(Get-ChildItem $Root -Recurse -Include *.cs | Where-Object { $_.FullName -notlike '*\obj\*' })
$currentSrc = @($allSrc | Where-Object { $_.FullName -notlike '*\Bridge\Legacy\*' })
$sharedNames = 'ScenarioObserver.cs', 'ScenarioReadyTracker.cs', 'ScenarioReadyPublisher.cs', 'HandshakeProtocol.cs', 'ObservationLog.cs'
$sharedSrc = @($allSrc | Where-Object { $_.Name -in $sharedNames -and $_.FullName -notlike '*\Bridge\Legacy\*' })
function CodeLines($f) {
    $n = 0
    foreach ($line in [IO.File]::ReadAllLines($f.FullName)) {
        $n++
        $code = [regex]::Replace($line, '"(?:[^"\\]|\\.)*"', '""')
        $code = [regex]::Replace($code, '//.*$', '')
        if ($line.TrimStart().StartsWith('//')) { continue }
        [pscustomobject]@{ File = $f.FullName.Substring($Root.Length + 1); N = $n; Code = $code; Raw = $line }
    }
}
function Hits($files, [string]$pattern, [switch]$IncludeStrings) {
    $out = @()
    foreach ($f in $files) { foreach ($l in (CodeLines $f)) { $text = if ($IncludeStrings) { $l.Raw } else { $l.Code }; if ($text -cmatch $pattern) { $out += ($l.File + ':' + $l.N) } } }
    return $out
}
foreach ($p in 'Process\.Start', 'ProcessStartInfo', 'UdpClient', 'TcpClient', 'Socket', 'Registry', 'Microsoft\.Win32', 'SetWindowsHookEx', 'Thread\.Sleep', 'System\.Timers', 'NamedPipe', 'Global\\\\', 'Python', 'python', 'main\.py', 'MessageBox', 'DllImport') {
    $h = Hits $legacySrc $p -IncludeStrings
    Check ("Legacy source: '$p' absent") ($h.Count -eq 0)
}
$thr = Hits $allSrc 'new Thread\(' -IncludeStrings
Check 'new Thread exists only in Caller\src\HandshakeSession.cs (Phase B monitor) and Bridge\Legacy\src\HandshakeControlPlane.cs (the Legacy control thread); none in the Current Bridge' (@($thr | Where-Object { ($_ -split ':')[0] -notin 'Caller\src\HandshakeSession.cs', 'Bridge\Legacy\src\HandshakeControlPlane.cs' }).Count -eq 0 -and (@($thr | Where-Object { ($_ -split ':')[0] -eq 'Bridge\Legacy\src\HandshakeControlPlane.cs' }).Count -eq 1))
$fio = Hits $legacySrc 'FileStream|FileMode|\bFile\.|StreamWriter|AppendAllText'
Check 'Legacy scope has no file I/O (the only file writer is the shared Shared\ObservationLog.cs)' ($fio.Count -eq 0)

# API separation
$hostTok = 'AtsEx|BveTypes|IBveHacker|PluginBuilder|AssemblyPluginBase|IExtension|PluginAttribute|TickResult|ClassWrappers'
$legacyHostFiles = @($legacySrc | Where-Object { (Hits @($_) $hostTok).Count -gt 0 } | ForEach-Object { $_.Name })
Check 'AtsEX / BveTypes API appears in code ONLY in Bridge\Legacy\src\TsScoringLegacyBridge.cs (the control plane and the shared core are host independent)' (($legacyHostFiles -join ',') -eq 'TsScoringLegacyBridge.cs')
$sharedHost = Hits $sharedSrc ($hostTok + '|BveEx|BveEX')
Check 'The shared core files (tracker, publisher, observer, protocol, log) name no host API in code' ($sharedHost.Count -eq 0)
$leakToCurrent = Hits $currentSrc 'AtsEx|LocationManager|UserVehicleLocationManager|ExtensionTickResult|TickResult'
Check 'Legacy-only API (AtsEx, LocationManager, TickResult) does not appear in any Current / Caller / Shared code' ($leakToCurrent.Count -eq 0)
$leakToLegacy = Hits $legacySrc 'BveEx|BveEX|\bVehicleLocation\b|PostTick|PreviewTick|void Tick\('
Check 'Current-only API (BveEx, Scenario.VehicleLocation, PostTick / PreviewTick, void Tick) does not appear in any Legacy code' ($leakToLegacy.Count -eq 0)
$adapterText = [IO.File]::ReadAllText((Join-Path $legacyDir 'src\TsScoringLegacyBridge.cs'))
Check 'Legacy adapter maps VehicleLocation to Scenario.LocationManager.Location and subscribes exactly ScenarioOpened, ScenarioClosed, PreviewScenarioCreated, ScenarioCreated, AllExtensionsLoaded' (($adapterText -match '\(\(Scenario\)scenario\)\.LocationManager') -and ($adapterText -match '\(\(UserVehicleLocationManager\)location\)\.Location') -and (@('h.ScenarioOpened +=', 'h.ScenarioClosed +=', 'h.PreviewScenarioCreated +=', 'h.ScenarioCreated +=', 'Extensions.AllExtensionsLoaded +=' | Where-Object { $adapterText -notmatch [regex]::Escape($_) }).Count -eq 0) -and ((([regex]::Matches($adapterText, '\+= On')).Count) -eq 5))

# control plane: no BVE object, thread discipline
$cp = [IO.File]::ReadAllText((Join-Path $legacyDir 'src\HandshakeControlPlane.cs'))
$cpCode = ((CodeLines (Get-Item (Join-Path $legacyDir 'src\HandshakeControlPlane.cs'))) | ForEach-Object { $_.Code }) -join "`n"
$adapterCode = ((CodeLines (Get-Item (Join-Path $legacyDir 'src\TsScoringLegacyBridge.cs'))) | ForEach-Object { $_.Code }) -join "`n"
Check 'Control plane (code only) touches no BVE object: no Scenario / Vehicle / TimeManager / BveHacker / LocationManager / IsScenarioCreated, no tracker type (it only calls the handshake-lost / handshake-up callbacks it was given)' (($cpCode -notmatch 'Scenario|Vehicle|TimeManager|BveHacker|LocationManager|IsScenarioCreated|ScenarioReadyTracker'))
Check 'Control plane: one background thread, joined with a time limit on Shutdown; Tick never takes the control gate (HandshakeUp is a lock free volatile flag)' (($cp -match 'IsBackground = true') -and ($cp -match 'Join\(1000\)') -and ($cp -match 'private volatile bool up;') -and ($cp -match 'internal bool HandshakeUp \{ get \{ return up; \} \}'))
# tracker call order in the adapter
Check 'Adapter: Dispose clears ScenarioReady (tracker.OnDispose) BEFORE the control plane releases Ready (Shutdown), and BridgeAvailable is withdrawn last' (($adapterText.IndexOf('t.OnDispose()') -ge 0) -and ($adapterText.IndexOf('t.OnDispose()') -lt $adapterText.IndexOf('c.Shutdown("bridge-dispose")')) -and ($adapterText.IndexOf('c.Shutdown("bridge-dispose")') -lt $adapterText.IndexOf('c.WithdrawAvailability()')))
Check 'Adapter: BridgeAvailable is published BEFORE the observation wiring; the control thread starts last; the tracker runs only inside Tick and the host event handlers' (($adapterText.IndexOf('BeginControl(false);') -ge 0) -and ($adapterText.IndexOf('BeginControl(false);') -lt $adapterText.IndexOf('SubscribeObservers(); }')) -and ($adapterText.IndexOf('SubscribeObservers(); }') -lt $adapterText.IndexOf('control.Start();')) -and ($adapterText -match 't\.OnTick\(\)'))
$trk = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\src\ScenarioReadyTracker.cs'))
Check 'Establishment (level = true) has exactly one place; the Legacy adapter never calls OnPostTick (PostTick does not exist in Legacy)' ((([regex]::Matches($trk, 'level = true;')).Count -eq 1) -and ($adapterCode -notmatch 'OnPostTick|PostTick'))

# project file
$proj = [IO.File]::ReadAllText((Join-Path $legacyDir 'TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj'))
$curProj = [IO.File]::ReadAllText((Join-Path $Root 'Bridge\TSScoringPlugin.BveEx.Bridge.Prototype.csproj'))
Check 'Legacy project: .NET Framework 4.8, AnyCPU, warnings as errors, no PDB, host references are Private=False read-only HintPaths built from the PUBLIC environment property (no absolute user path)' (($proj -match '<TargetFrameworkVersion>v4\.8</TargetFrameworkVersion>') -and ($proj -match '<PlatformTarget>AnyCPU</PlatformTarget>') -and ($proj -match '<TreatWarningsAsErrors>true</TreatWarningsAsErrors>') -and ($proj -match '<DebugType>none</DebugType>') -and ($proj -match '\$\(PUBLIC\)\\Documents\\BveEx\\Legacy\\') -and ($proj -notmatch '[A-Za-z]:\\Users') -and (([regex]::Matches($proj, '<Private>False</Private>')).Count -eq 5))
$linked = @($sharedNames | Where-Object { $proj -match [regex]::Escape($_) -and $curProj -match [regex]::Escape($_) })
Check 'Both projects compile the same shared core sources (tracker, publisher, observer, protocol, log) by source link; the Legacy project adds only src\TsScoringLegacyBridge.cs, src\HandshakeControlPlane.cs, src\AssemblyInfo.cs' (($linked.Count -eq 5) -and ($proj -match 'src\\TsScoringLegacyBridge\.cs') -and ($proj -match 'src\\HandshakeControlPlane\.cs') -and ($curProj -notmatch 'Legacy'))

# ---------------------------------------------------------------------------------------------------------------------------------
Write-Host '==== Current contract unchanged (vs Phase C3 baseline commit) ===='
$baseFiles = @((RunGit @('ls-tree', '-r', '--name-only', '--full-name', $Baseline, '--', '.')) -split "`n" | Where-Object { $_ })
$changedBase = @()
foreach ($bf in $baseFiles) {
    $rel = $bf.Substring($prefix.Length).Replace('/', '\')
    if (-not (Test-Path (Join-Path $Root $rel))) { $changedBase += ($rel + ' (missing)'); continue }
    if ((BaseText $rel) -cne (WorkText $rel)) { $changedBase += $rel }
}
"files of the Handshake tree in the baseline: " + $baseFiles.Count + "; differing from the baseline: " + ($changedBase -join ', ')
# Phase M1 (Caller 0.7.0.0) deliberately changed the Caller notice code and the tests / checks that describe it; the Current Bridge, the Legacy boundary and the shared protocol / log stay identical.
$m1Changed = 'Caller\src\AssemblyInfo.cs', 'Caller\src\HandshakeSession.cs', 'Caller\src\TsScoringCallerInputDevice.cs', 'Caller\TSScoringPlugin.Caller.InputDevice.csproj', 'Tests\Test-HandshakeLogic.ps1', 'Tests\Test-ObservationC1.ps1'
Check 'Every Handshake file of the Phase C3 baseline is byte-identical (LF-normalised) EXCEPT the two L1 tool scripts (Tools\Verify-PhaseC3.ps1, Tools\Audit-Privacy.ps1) and the six Phase M1 Caller / test files; no Bridge or Shared file differs' (($changedBase.Count -eq 8) -and ($changedBase -contains 'Tools\Verify-PhaseC3.ps1') -and ($changedBase -contains 'Tools\Audit-Privacy.ps1') -and (@($m1Changed | Where-Object { $changedBase -notcontains $_ }).Count -eq 0) -and (@($changedBase | Where-Object { $_ -match '^(Bridge|Shared)\\' }).Count -eq 0))
$apBase = (BaseText 'Tools\Audit-Privacy.ps1') -split "`n"
$apNow = (WorkText 'Tools\Audit-Privacy.ps1') -split "`n"
$apRem = @(Compare-Object $apBase $apNow | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject })
$apAdd = @(Compare-Object $apBase $apNow | Where-Object { $_.SideIndicator -eq '=>' } | ForEach-Object { $_.InputObject })
Check 'Audit-Privacy.ps1 differs only by allowing the new DLL identifier TSScoringPlugin.AtsExLegacy in its allowed-identifier pattern (1 line replaced)' (($apRem.Count -eq 1) -and ($apAdd.Count -eq 1) -and ($apAdd[0] -match 'AtsExLegacy') -and ($apAdd[0].Replace('|AtsExLegacy', '') -ceq $apRem[0]))
$c3Base = (BaseText 'Tools\Verify-PhaseC3.ps1') -split "`n"
$c3Now = (WorkText 'Tools\Verify-PhaseC3.ps1') -split "`n"
$rem = @(Compare-Object $c3Base $c3Now | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject })
$add = @(Compare-Object $c3Base $c3Now | Where-Object { $_.SideIndicator -eq '=>' } | ForEach-Object { $_.InputObject })
$addText = @($add | Where-Object { $_.Trim() -ne '' })
Check 'Verify-PhaseC3.ps1 differs only by the L1 scoping of its source scan to the Current product (1 line replaced, 1 comment line added) and the Phase M1 / Phase D1 Caller-contract updates (version line, comment-aware removed-line filters, the ScenarioReady-named-code allow-list; 6 more lines replaced)' (($rem.Count -eq 7) -and ($addText.Count -eq 11) -and (@($rem | Where-Object { $_ -match '^\$srcFiles = ' }).Count -eq 1) -and (@($addText | Where-Object { $_ -match "notlike '\*\\Bridge\\Legacy\\\*'" }).Count -eq 1) -and (@($addText | Where-Object { $_ -match 'Phase L1:' }).Count -eq 1) -and (@($rem | Where-Object { $_ -match 'Version 0\.6\.0\.0 in both|NoticeText \(both lines\)|no timeout / state-machine line|only the two status-text lines|srAllowed = |ScenarioReady-named code exists' }).Count -eq 6) -and (@($addText | Where-Object { $_ -match 'Phase M1|removedCode|r3Code|Version: Caller 0\.8\.0\.0|srAllowed = .*DrivingActivityState|ScenarioReady-named code exists.*Phase D1' }).Count -eq 9))
$hp = WorkText 'Shared\HandshakeProtocol.cs'
Check 'Timings unchanged: BridgeMissingTimeoutMs = 500 (and 500 / 20 / 100 for the others)' (($hp -match 'BridgeMissingTimeoutMs = 500;') -and ($hp -match 'TargetBridgeAvailableMs = 500;') -and ($hp -match 'CallerPollMs = 20;') -and ($hp -match 'BridgePollMs = 100;'))
$hsNow = WorkText 'Caller\src\HandshakeSession.cs'
$mbPattern = '^\s*(internal const string (NoticeText|ProductDisplayName|ProviderName)|private const uint MB_|\[DllImport\("user32\.dll", EntryPoint = "MessageBoxW"|private static extern int MessageBoxW|"TS Scoring|"[^"]*(BveEX|BveEx)[^"]*"|MessageBoxW\()'
$mbNow = @(($hsNow -split "`n") | Where-Object { $_ -match $mbPattern })
$mbBase = @(((BaseText 'Caller\src\HandshakeSession.cs') -split "`n") | Where-Object { $_ -match $mbPattern })
Check 'MessageBox contract unchanged: every MessageBox line of Caller\src\HandshakeSession.cs (notice text, title, flags, P/Invoke, the call) is identical to the baseline; the 500 ms constants are checked above' (($mbBase.Count -ge 8) -and (($mbNow -join "`n") -ceq ($mbBase -join "`n")))
Check 'Named objects of the contract are the same set (Enabled, Stop, BridgeAvailable, Ready, BridgeInfo, ScenarioReady, ScenarioState); no new named object kind was introduced by the Legacy sources' ((@(([regex]::Matches((($allSrc | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"), 'Local\\\\TSScoringPlugin\.v1\."\s*\+\s*\w+\s*\+\s*"\.(\w+)')) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique) -join ',') -eq 'BridgeAvailable,BridgeInfo,Enabled,ObsLogLock,ObsLogRun,Ready,ScenarioReady,ScenarioState,Stop')

Write-Host '==== repository scope ===='
$top = (RunGit @('rev-parse', '--show-toplevel')).Trim()
$changedTracked = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline, '--', $prefix)) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard', '--', $prefix)) -split "`n" | Where-Object { $_ })
$committedAll = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline, 'HEAD')) -split "`n" | Where-Object { $_ })   # whole repository, committed history only (a dirty file of someone else is not this phase)
$touched = @($changedTracked + $untracked | Sort-Object -Unique)
"files touched relative to the baseline (tracked changes + untracked): " + $touched.Count
$touched | ForEach-Object { "   " + $_ }
$allowedPrefix = $prefix + 'Bridge/Legacy/'
$allowedExact = @(($prefix + 'Tests/Test-LegacyL1.ps1'), ($prefix + 'Tools/Verify-PhaseL1.ps1'), ($prefix + 'Tools/Verify-PhaseC3.ps1'), ($prefix + 'Tools/Audit-Privacy.ps1'), ($prefix + 'Docs/Handshake-PhaseL1-LegacyAdapter.md'))
# Phase M1 files (the Caller notice change, its tests and its document) and Phase D1 files (DrivingActive state, thresholds, test, document)
$allowedExact += @('Caller/src/AssemblyInfo.cs', 'Caller/src/HandshakeSession.cs', 'Caller/src/TsScoringCallerInputDevice.cs', 'Caller/TSScoringPlugin.Caller.InputDevice.csproj', 'Tests/Test-HandshakeLogic.ps1', 'Tests/Test-ObservationC1.ps1', 'Tests/Test-DependencyNoticeM1.ps1', 'Docs/Handshake-PhaseM1-DependencyNotice.md', 'Caller/src/DrivingActivityState.cs', 'Shared/AppProtocol.cs', 'Tests/Test-DrivingActiveD1.ps1', 'Docs/Handshake-PhaseD1-DrivingActive.md' | ForEach-Object { $prefix + $_ })
$outside = @($touched | Where-Object { -not ($_.StartsWith($allowedPrefix) -or ($_ -in $allowedExact)) })
Check 'Only the Legacy adapter (Bridge\Legacy\), its test, its verification, the Verify-PhaseC3.ps1 / Audit-Privacy.ps1 edits, one L1 document, the Phase M1 Caller / test / document files and the Phase D1 DrivingActive files are touched in the Handshake tree' ($outside.Count -eq 0)
Check 'No Python, Class1.cs, AtsLoggerPlugin.cs, packages or project file of the existing plugin is touched' (@($touched + $committedAll | Where-Object { $_ -match '\.py$|Class1\.cs$|AtsLoggerPlugin\.cs$|/packages/|\.vcxproj|\.slnx$|\.dll$|\.pdb$|\.log$|\.bak' }).Count -eq 0)
Check 'No build output, third-party DLL, PDB or log among the files to be committed (obj / out / build.log stay ignored)' (@($touched | Where-Object { $_ -match '/out/|/obj/|/dist|build\.log|\.dll$|\.pdb$|\.log$' }).Count -eq 0)

Write-Host '==== privacy / provider / documentation ===='
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$emailPattern = '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
function CountForbidden([byte[]]$bytes) {
    $ascii = [Text.Encoding]::ASCII.GetString($bytes); $utf16 = [Text.Encoding]::Unicode.GetString($bytes); $utf8 = [Text.Encoding]::UTF8.GetString($bytes)
    $total = 0
    foreach ($tok in $forbidden) { foreach ($text in @($ascii, $utf16, $utf8)) { $total += ([regex]::Matches($text, [regex]::Escape($tok), 'IgnoreCase')).Count } }
    foreach ($text in @($ascii, $utf16, $utf8)) { $total += ([regex]::Matches($text, $emailPattern)).Count }
    return $total
}
$privFiles = @($legacySrc) + @(Get-Item (Join-Path $legacyDir 'TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj')) + @(Get-Item $LegacyDll) + @(Get-Item (Join-Path $Root 'Docs\Handshake-PhaseL1-LegacyAdapter.md'))
$privHits = 0; foreach ($f in $privFiles) { $privHits += CountForbidden ([IO.File]::ReadAllBytes($f.FullName)) }
Check ('No user name, machine name, drive path, user folder, repository name or e-mail in the Legacy sources, project, DLL or document (' + $privFiles.Count + ' files, matches=' + $privHits + ')') ($privHits -eq 0)
$doc = WorkText 'Docs\Handshake-PhaseL1-LegacyAdapter.md'
Check 'Document states the deployment folders, the Current/Legacy exclusivity rule and that nothing is deployed automatically' (($doc -match 'Legacy\\Extensions') -and ($doc -match '2\.0\\Extensions') -and ($doc -match '(?i)never[^\n]*other host|exclusive') -and ($doc -match '(?i)not deployed|no automatic deployment|nothing is deployed'))

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { exit 1 }
