# PHASE L3 - static verification of the AtsEX Legacy telemetry sender and of the repository scope of the phase.
# What is checked: the built DLL (one file, metadata, references), the scope of the change relative to the E4 commit (only the L3 files differ; the control plane,
# the Bridges, the Caller, Class1.cs and the scoring / UI Python modules are byte-identical), the isolation of the telemetry project (no Current API, no Handshake
# source, AtsEx names in exactly one file), the agreement of the C# and the Python vocabulary, the document, privacy (no user / machine / path / e-mail in the
# files of the phase), and - read only - that nothing was deployed (the deployed DLLs and launcher.json keep the hashes recorded at the start of the phase).
# Nothing is written, deployed or started. This script is ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$Baseline = 'bc4c1160bf6755776d27525a4928a742c460825e',
    [switch]$SkipDeployedCheck
)

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function RunGit([string[]]$gitArgs) { $out = & git @gitArgs 2>$null; if ($LASTEXITCODE -ne 0) { return '' }; return ($out -join "`n") }
$top = (RunGit @('-C', $Root, 'rev-parse', '--show-toplevel')).Trim() -replace '/', '\'
$prefix = (RunGit @('-C', $Root, 'rev-parse', '--show-prefix')).Trim()      # TsScoringPlugin/Handshake/
$telDir = Join-Path $Root 'Telemetry'
$outDir = Join-Path $telDir 'Legacy\out'
$dllPath = Join-Path $outDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'

Write-Host '==== the built DLL ===='
$outFiles = @(Get-ChildItem $outDir -File -ErrorAction SilentlyContinue)
Check 'out holds exactly the one telemetry DLL (no PDB, no third-party DLL, no other file)' (($outFiles.Count -eq 1) -and ($outFiles[0].Name -eq 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -and (@(Get-ChildItem $Root -Recurse -File -Include *.pdb).Count -eq 0))
$vi = (Get-Item $dllPath).VersionInfo
Check 'file version 0.1.2.0 (Phase L3 gradient unit fix), product TS Scoring, provider Coruge-to, description names Phase L3' (($vi.FileVersion -eq '0.1.2.0') -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.Comments -match 'Phase L3'))
$proj = [IO.File]::ReadAllText((Join-Path $telDir 'Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
$projCode = [regex]::Replace($proj, '<!--[\s\S]*?-->', '')      # the comments of the project file may name the Bridge
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class L3VerifyResolver
{
    public static void Install(string dir)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string p = Path.Combine(dir, e.Name.Split(',')[0] + ".dll");
            return File.Exists(p) ? Assembly.LoadFrom(p) : null;
        };
    }
}
"@
[L3VerifyResolver]::Install((Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'))      # the AtsEX host assemblies, read only, to be able to enumerate the types
$bytes = [IO.File]::ReadAllBytes($dllPath)
$asm = [Reflection.Assembly]::Load($bytes)
$refs = @($asm.GetReferencedAssemblies() | ForEach-Object { $_.Name })
Check 'references only the framework, AtsEX (PluginHost) and BveTypes - no BveEX, no Mackoy, no Handshake assembly' (-not ($refs | Where-Object { $_ -notmatch '^(mscorlib|System|System\.Core|AtsEx\.PluginHost|BveTypes|FastCaching|FastMember|TypeWrapping)$' }))
Check 'AnyCPU and not 32-bit-only: runs in BVE5 (a 32-bit process) and in a 64-bit host' (($asm.GetName().ProcessorArchitecture -eq 'MSIL') -and ($proj -match '<PlatformTarget>AnyCPU</PlatformTarget>') -and ($proj -match '<Prefer32Bit>false</Prefer32Bit>'))
Check 'project: .NET Framework 4.8, no PDB, warnings are errors, deterministic, host assemblies Private=False from the PUBLIC folder' (($proj -match 'v4\.8') -and ($proj -match '<DebugType>none</DebugType>') -and ($proj -match '<TreatWarningsAsErrors>true') -and ($proj -match '<Deterministic>true') -and ((([regex]::Matches($proj, '<Private>False</Private>')).Count) -eq 5) -and ($proj -match '\$\(PUBLIC\)'))

Write-Host '==== isolation of the telemetry project ===='
$tel = @(Get-ChildItem $telDir -Recurse -Filter *.cs | Where-Object { $_.FullName -notlike '*\obj\*' -and $_.FullName -notlike '*\out\*' })
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
$codeAll = ($tel | ForEach-Object { Code ([IO.File]::ReadAllText($_.FullName)) }) -join "`n"
Check ('sources: ' + $tel.Count + ' files') ($tel.Count -ge 6)
Check 'no Current (BveEX) type or namespace in any source' ($codeAll -cnotmatch 'BveEx' -and $codeAll -cnotmatch 'BveEX')
Check 'no Handshake source, control-plane name or named kernel object' (($codeAll -notmatch 'HandshakeProtocol') -and ($codeAll -notmatch 'ScenarioReady') -and ($codeAll -notmatch 'ObservationLog') -and ($codeAll -notmatch 'EventWaitHandle|MemoryMappedFile|Mutex|Local\\\\TSScoringPlugin'))
$hostFiles = @($tel | Where-Object { (Code ([IO.File]::ReadAllText($_.FullName))) -cmatch 'using AtsEx|using BveTypes|AtsEx\.PluginHost|BveTypes\.ClassWrappers' } | ForEach-Object { $_.Name })
Check 'AtsEx / BveTypes appear in exactly one source (the host adapter)' (($hostFiles.Count -eq 1) -and ($hostFiles[0] -eq 'LegacyTelemetryExtension.cs'))
Check 'the project links no file outside Telemetry (only its own Shared\TelemetryContract.cs)' (($proj -match '\.\.\\Shared\\TelemetryContract\.cs') -and ($projCode -notmatch 'Bridge') -and ($projCode -notmatch 'Caller') -and ($projCode -notmatch 'Handshake') -and ($projCode -notmatch '\.\.\\\.\.'))
Check 'the only network code is the UDP sink in the contract file (no listener, no 54322, no receive)' (($codeAll -notmatch '54322') -and ($codeAll -notmatch 'TcpListener|TcpClient|\.Receive\(|new UdpClient\(\s*\d') -and ((Code ([IO.File]::ReadAllText((Join-Path $telDir 'Shared\TelemetryContract.cs')))) -match 'UdpClient'))
$allTypes = @(); try { $allTypes = @($asm.GetTypes()) } catch [Reflection.ReflectionTypeLoadException] { $allTypes = @($_.Exception.Types | Where-Object { $_ }) }      # the AtsEx types are not resolvable here; the rest is
$pub = @($allTypes | Where-Object { $_.IsPublic })
Check 'one public type (the extension); everything else is internal' (($pub.Count -eq 1) -and ($pub[0].Name -eq 'TsScoringLegacyTelemetryExtension'))
$session = Code ([IO.File]::ReadAllText((Join-Path $telDir 'Legacy\src\LegacyTelemetrySession.cs')))
$never = @(); foreach ($k in @('REV', 'POW', 'BRK', 'HTYPE', 'ALLTXT', 'BCP', 'BPP', 'TRAINLEN', 'DOORTIME', 'MAPLIMITS', 'CLEARDIST', 'JUMP')) { if ($session -match ('"' + $k + '"')) { $never += $k } }
Check 'the sender never names a key of data the Legacy API does not provide' ($never.Count -eq 0)
# the gradient unit (finding of the BVE5 live test): the host adapter reads the RAW API ratio, the session converts it to per mille in exactly one place
$extCode = Code ([IO.File]::ReadAllText((Join-Path $telDir 'Legacy\src\LegacyTelemetryExtension.cs')))
$apiCode = Code ([IO.File]::ReadAllText((Join-Path $telDir 'Legacy\src\LegacyApi.cs')))
$gradRead = [regex]::Match($extCode, 'TryGradientRatio\(double location, out double ratio\)[\s\S]*?\n        \}').Value
Check 'gradient unit: the adapter returns the raw Legacy API ratio (no scaling, no per-mille name); the interface is TryGradientRatio' (($gradRead -match 'Gradients\.GetValueAt\(location\)') -and ($gradRead -notmatch '1000') -and ($apiCode -match 'bool TryGradientRatio\(') -and ($apiCode -notmatch 'TryGradientPermille') -and ($extCode -notmatch 'TryGradientPermille'))
Check 'gradient unit: the ONE conversion (x 1000) lives in LegacyTelemetrySession.GradientRatioToPermille and the GRADIENT key is written from its result' (($session -match 'ratio \* 1000\.0') -and ([regex]::Matches($session, '\* 1000\.0')).Count -eq 1 -and ($session -match 'api\.TryGradientRatio\(location, out ratio\) && GradientRatioToPermille\(ratio, out gradient\)') -and ($session -match '"GRADIENT", TelemetryContract\.D\(gradient\)'))
Check 'gradient unit: the shared contract file and the Python telemetry modules convert nothing (the per-mille contract is the Current one)' (((Code ([IO.File]::ReadAllText((Join-Path $telDir 'Shared\TelemetryContract.cs')))) -notmatch 'RatioToPermille|Gradient|GRADIENT') -and ((Get-Content (Join-Path $top 'telemetry_contract.py') -Raw) -notmatch '(?i)grad[^\r\n]*1000|1000[^\r\n]*grad') -and ((Get-Content (Join-Path $top 'network.py') -Raw) -notmatch 'GRADIENT:.*1000'))

Write-Host '==== C# and Python speak the same vocabulary ===='
$contractCs = [IO.File]::ReadAllText((Join-Path $telDir 'Shared\TelemetryContract.cs'))
$csTokens = @([regex]::Matches($contractCs, 'internal const string Tok\w+ = "([a-z_]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object)
Push-Location $top
try { $pyTokens = @((& python -I -c "import sys; sys.path.insert(0, r'$top'); import telemetry_contract as t; print(' '.join(sorted(t.KNOWN_TOKENS)))") -split ' ') } finally { Pop-Location }
$unknown = @($csTokens | Where-Object { $_ -notin $pyTokens })
Check ('every token the C# sender can announce is in the Python vocabulary (' + $csTokens.Count + ' tokens)') (($unknown.Count -eq 0) -and ($csTokens.Count -ge 10))
Check 'protocol version 1 in both languages' (($contractCs -match 'ProtocolVersion = 1;') -and ((Get-Content (Join-Path $top 'telemetry_contract.py') -Raw) -match 'PROTOCOL_VERSION = 1'))
$notSent = @($pyTokens | Where-Object { $_ -notin $csTokens })
Check ('the tokens the Legacy sender never announces are exactly: ' + ($notSent -join ' ')) ((($notSent | Sort-Object) -join ',') -eq 'bcp,bpp,doortime,handle,jump,maplimit_ahead,trainlen')

Write-Host '==== repository scope ===='
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', $Baseline)) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
"files touched relative to the E4 commit (tracked changes + untracked): " + $touched.Count
$touched | ForEach-Object { "   " + $_ }
$allowedExact = @(
    'main.py', 'hud_ui.py', 'managed_hud.py', 'telemetry_contract.py', 'telemetry_gate.py',
    'tests/test_telemetry_l3.py', 'tests/telemetry_xcheck.py', 'tests/telemetry_overlay_check.py', 'tests/overlay_guard.py',
    'tests/test_managed_hud_e4.py', 'tests/test_managed_mode_e2.py', 'tests/test_hud_data_path_e4.py', 'tests/managed_hud_child.py', 'tests/zorder_real_check.py',
    ($prefix + 'Tests/Test-TelemetryL3.ps1'), ($prefix + 'Tests/Test-TelemetryIntegrationL3.ps1'), ($prefix + 'Tests/TelemetryTestFixture.cs'), 'tests/telemetry_gate_check.py',
    ($prefix + 'Tools/Verify-PhaseL3.ps1'), ($prefix + 'Docs/Handshake-PhaseL3-LegacyTelemetry.md'), ($prefix + 'Docs/Handshake-PhaseE4-HudZOrder.md'),
    ($prefix + 'Docs/Handshake-PhaseE4-LegacyTelemetryAudit.md'),
    ($prefix + 'Tests/Test-HudLinkE4.ps1'), ($prefix + 'Tests/Test-DependencyNoticeM1.ps1'), ($prefix + 'Tools/Verify-PhaseL1.ps1'), ($prefix + 'Tools/Verify-PhaseC3.ps1'),
    # parent-exit fix (P1): the owner-process watch in the managed lifecycle module, its tests, and the E3 test whose stand-in BVE is now a live process
    'managed_mode.py', 'tests/parent_exit_child.py', 'tests/test_parent_exit_p1.py', ($prefix + 'Tests/Test-AppProcessE3.ps1')
)
$outside = @($touched | Where-Object { -not ($_.StartsWith($prefix + 'Telemetry/') -or ($_ -in $allowedExact)) })
if ($outside.Count -gt 0) { "outside the allowance: " + ($outside -join ', ') }
Check 'only the L3 files differ from the E4 commit (telemetry project, telemetry_* modules, the HUD / main.py hooks, tests, one document + a note in the E4 audit)' ($outside.Count -eq 0)
$frozen = @($touched | Where-Object { $_ -match ('^' + [regex]::Escape($prefix) + '(Caller|Bridge|Shared)/') -or $_ -match 'Class1\.cs$|AtsLoggerPlugin\.cs$|/packages/|\.vcxproj|\.slnx$|^scoring_logic\.py$|^menu_ui\.py$|^config\.py$|^utils\.py$|^network\.py$|^managed_state\.py$|launcher\.template\.json$|Handshake-Phase(B|C1|C3|D1|E1|E3|L1|M1|E4-StatePublication)' })
Check 'the control plane is untouched: Caller, both Bridges, Shared, Class1.cs, packages, project files, managed_state (managed_mode.py only gained the P1 owner-process watch, allowed above), the scoring / UI modules and the documents of earlier phases' ($frozen.Count -eq 0)
Check 'no build output, DLL, PDB, log or personal launcher.json among the files of the phase' (@($touched | Where-Object { $_ -match '/out/|/obj/|/dist/|/logs/|build\.log|\.dll$|\.pdb$|\.log$|\.exe$' -or $_ -match '(^|/)launcher\.json$' }).Count -eq 0)
Check 'no push: the branch is only ahead of its upstream (this script does not push; the upstream still points at the E3 commit)' ((RunGit @('-C', $top, 'rev-parse', 'origin/refactor/state-transitions')).Trim() -eq 'b9611dad47e2c95f8fa1c89a8bd0286896c75cea')

Write-Host '==== the document ===='
$docPath = Join-Path $Root 'Docs\Handshake-PhaseL3-LegacyTelemetry.md'
$doc = [IO.File]::ReadAllText($docPath, [Text.Encoding]::UTF8)
$missingTok = @($pyTokens | Where-Object { $doc -notmatch ('`' + [regex]::Escape($_) + '`') })
Check 'the document names every token of the contract' ($missingTok.Count -eq 0)
Check 'the document states the unavailable items (handle texts, BCP, BPP, ground look-ahead, jump on 54322)' (($doc -match '`handle`') -and ($doc -match 'BCP') -and ($doc -match 'BPP') -and ($doc -match 'MAPLIMITS') -and ($doc -match '54322') -and ($doc -match '`maplimit_ahead`') -and ($doc -match '`jump`'))
Check 'the document names the telemetry DLL, the Legacy Extensions folder and the exclusive-host rule' (($doc -match 'TSScoringPlugin\.AtsExLegacy\.Telemetry\.dll') -and ($doc -match 'Legacy\\Extensions') -and ($doc -match '2\.0\\Extensions'))
Check 'the document names the L3-live acceptance, the host seam (ILegacyApi) and the control plane Bridge it is separate from' (($doc -match 'L3-live') -and ($doc -match 'ILegacyApi') -and ($doc -match 'AtsExLegacy\.Bridge\.Prototype') -and ($doc -match 'AVAIL'))
Check 'the document records the two items deliberately not sent (vehicle length, door close time)' (($doc -match '`trainlen`') -and ($doc -match '`doortime`') -and ($doc -match 'StandardCloseTime') -and ($doc -match 'CarLength'))
Write-Host '==== privacy ===='
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @('C:\Users\', 'Scoring-Feature-Train-Simulator', 'gmail', 'hotmail', 'outlook.com', 'ac.jp')
$emailPattern = '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
function CountForbidden([byte[]]$b) {
    $ascii = [Text.Encoding]::ASCII.GetString($b); $utf16 = [Text.Encoding]::Unicode.GetString($b); $utf8 = [Text.Encoding]::UTF8.GetString($b)
    $total = 0
    foreach ($tok in $forbidden) { foreach ($text in @($ascii, $utf16, $utf8)) { $total += ([regex]::Matches($text, [regex]::Escape($tok), 'IgnoreCase')).Count } }
    foreach ($text in @($ascii, $utf16, $utf8)) { $total += ([regex]::Matches($text, $emailPattern)).Count }
    return $total
}
$privFiles = @($tel) + @(Get-Item (Join-Path $telDir 'Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj')) + @(Get-Item $dllPath) + @(Get-Item $docPath)
foreach ($f in 'telemetry_contract.py', 'telemetry_gate.py', 'managed_hud.py') { $privFiles += @(Get-Item (Join-Path $top $f)) }
$privHits = 0; foreach ($f in $privFiles) { $privHits += CountForbidden ([IO.File]::ReadAllBytes($f.FullName)) }
Check ('no user name, machine name, drive path, user folder, repository name or e-mail in the sources, project, DLL, document or new Python modules (' + $privFiles.Count + ' files, matches=' + $privHits + ')') ($privHits -eq 0)

if (-not $SkipDeployedCheck) {
    Write-Host '==== nothing was deployed (read only) ===='
    function H8([string]$p) { if (Test-Path $p) { return (Get-FileHash $p -Algorithm SHA256).Hash.Substring(0, 8) } else { return 'absent' } }
    $pub = $env:PUBLIC
    Check 'deployed Caller (BVE6 and BVE5) is the E4 Caller 0.11.0.0 (1B2F7C1F) deployed for L3-live - this fix changes no Caller' ((H8 (Join-Path $env:ProgramW6432 'mackoy\BveTs6\Input Devices\TSScoringPlugin.Caller.InputDevice.dll')) -eq '1B2F7C1F' -and (H8 (Join-Path ${env:ProgramFiles(x86)} 'mackoy\BveTs5\Input Devices\TSScoringPlugin.Caller.InputDevice.dll')) -eq '1B2F7C1F')
    Check 'deployed Current Bridge (247F6724) and Legacy Bridge (C2883E40) are unchanged; the Legacy Extensions folder holds no telemetry DLL, the L3-live 0.1.0.0 (8BFD06AA) or this build, and the Current Extensions folder none' (((H8 (Join-Path $pub 'Documents\BveEx\2.0\Extensions\TSScoringPlugin.BveEx.Bridge.Prototype.dll')) -eq '247F6724') -and ((H8 (Join-Path $pub 'Documents\BveEx\Legacy\Extensions\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll')) -eq 'C2883E40') -and ((H8 (Join-Path $pub 'Documents\BveEx\Legacy\Extensions\TSScoringPlugin.AtsExLegacy.Telemetry.dll')) -in @('8BFD06AA', '10683A92', 'absent', (H8 $dllPath))) -and ((H8 (Join-Path $pub 'Documents\BveEx\2.0\Extensions\TSScoringPlugin.AtsExLegacy.Telemetry.dll')) -eq 'absent'))
    Check 'launcher.json is the E3 one (91471ACC)' ((H8 (Join-Path $env:LOCALAPPDATA 'Coruge-to\TS Scoring\launcher.json')) -eq '91471ACC')
}

$failed = @($results | Where-Object { -not $_.Ok })
"TOTAL {0}  FAILED {1}" -f $results.Count, $failed.Count
if ($failed.Count -gt 0) { $failed | ForEach-Object { "FAILED: " + $_.Name }; exit 1 } else { exit 0 }
