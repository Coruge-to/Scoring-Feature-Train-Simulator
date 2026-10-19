param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,
    [string]$InteropFolder = ''
)
# PID-D6 (necessary minimum slice) offline tests of the Current jump endpoint and of the RequestId echo of the JUMP_COMPLETE. No BVE, no BveEX, no fixed port:
# the only operating system objects are synthetic named mappings under an unused high PID and loopback UDP sockets of this process.
# Optional -InteropFolder: the C# <-> Python round trip (tests\test_current_jump_interop_d6.py writes identity.txt / commands.txt, this writes results.txt).
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$plugin = Join-Path $RepositoryRoot 'TsScoringPlugin'
$shared = Join-Path $plugin 'Handshake\Telemetry\Shared'
$sources = @(
    (Join-Path $shared 'DataPlaneProtocol.cs'),
    (Join-Path $shared 'TelemetryDirectoryReader.cs'),
    (Join-Path $plugin 'TsScoringPlugin\CurrentDataPlane.cs'),
    (Join-Path $plugin 'TsScoringPlugin\CurrentJumpEndpoint.cs'),
    (Join-Path $plugin 'Handshake\Tests\CurrentJumpD6TestFixture.cs')
)
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Code([string]$path) {
    $t = [IO.File]::ReadAllText($path)
    $t = [regex]::Replace($t, '(?s)/\*.*?\*/', '')
    return ([regex]::Replace($t, '(?m)//.*$', ''))
}

Write-Host '--- A: compiled tests (CurrentJumpD6TestFixture)'
Add-Type -Path $sources -ReferencedAssemblies @('System.dll', 'System.Core.dll')
$results = [CurrentJumpD6TestFixture]::Run($InteropFolder)
$checks = $results[0]
$bad = @($results | Select-Object -Skip 1)
Check ('A01 every compiled check passed (' + $checks + ')') ($bad.Count -eq 0)
foreach ($b in $bad) { Write-Host ('  FAILED: ' + $b) }

Write-Host '--- B: static checks (Current-only, no fixed port in the managed path, separation)'
$jump = Join-Path $plugin 'TsScoringPlugin\CurrentJumpEndpoint.cs'
$dp = Join-Path $plugin 'TsScoringPlugin\CurrentDataPlane.cs'
$class1 = Join-Path $plugin 'TsScoringPlugin\Class1.cs'
$csproj = Join-Path $plugin 'TsScoringPlugin\TsScoringPlugin.csproj'
$jumpCode = Code $jump
$dpCode = Code $dp
$class1Code = Code $class1
Check 'B01 CurrentJumpEndpoint.cs holds no fixed 54321 / 54322' (($jumpCode -notmatch '54321') -and ($jumpCode -notmatch '54322'))
Check 'B02 CurrentDataPlane.cs still holds no fixed 54321 / 54322 and no UdpClient' (($dpCode -notmatch '54321') -and ($dpCode -notmatch '54322') -and ($dpCode -notmatch 'UdpClient'))
Check 'B03 CurrentJumpEndpoint.cs references no Caller / Handshake / BveEx / AtsEx / Legacy type' (($jumpCode -cnotmatch 'TSScoringPlugin\.Handshake') -and ($jumpCode -cnotmatch 'BveEx') -and ($jumpCode -cnotmatch 'AtsEx') -and ($jumpCode -cnotmatch 'Legacy'))
Check 'B04 the new file is a Compile item of the Current project' ((Get-Content $csproj -Raw) -match 'CurrentJumpEndpoint\.cs')
# PID-D4 / LEGACY JUMP 2A-ALPHA (Stage S4): the Legacy Telemetry project links the Current jump file ONCE (one shared Link) only to get the shared types; the type
# CurrentJumpEndpoint therefore exists in the Legacy DLL, and what is pinned is that no Legacy source names it or calls its Create method.
$legacyDoc = New-Object System.Xml.XmlDocument
$legacyDoc.Load((Join-Path $plugin 'Handshake\Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
$legacyJumpLinks = @($legacyDoc.SelectNodes("//*[local-name()='Compile']") | Where-Object { $_.GetAttribute('Include') -match 'CurrentJumpEndpoint' })
$legacyJumpLinkOk = ($legacyJumpLinks.Count -eq 1) -and ($legacyJumpLinks[0].GetAttribute('Include') -ceq '..\..\..\TsScoringPlugin\CurrentJumpEndpoint.cs') -and ($legacyJumpLinks[0].SelectSingleNode("*[local-name()='Link']").InnerText -ceq 'Shared\CurrentJumpEndpoint.cs')
Check 'B05 the Legacy Telemetry project compiles the Current jump file only as the one shared Link (exact Include and Link, exactly once)' $legacyJumpLinkOk
$legacySrc = @(Get-ChildItem (Join-Path $plugin 'Handshake\Telemetry') -Recurse -Filter *.cs | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' })
$legacyUsers = @($legacySrc | Where-Object { (Code $_.FullName) -match 'JumpCommandValidator|JumpDirectoryPublisher|CurrentJumpCommand|JumpCapabilities' } | ForEach-Object { $_.Name } | Sort-Object)
Check 'B06 no Legacy / Telemetry source names CurrentJumpEndpoint or calls its Create method, no Current BveEx API flows in, and the shared types are used only by the three Legacy jump plane files' ((@($legacySrc | Where-Object { (Code $_.FullName) -match 'CurrentJumpEndpoint|BveEx' }).Count -eq 0) -and (($legacyUsers -join ',') -ceq 'LegacyJumpCommandQueue.cs,LegacyJumpControlPlane.cs,LegacyJumpEndpoint.cs'))
Check 'B07 the shared protocol and reader files are unchanged by this slice' ((git -C $RepositoryRoot status --short -- TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs | Measure-Object).Count -eq 0)
Check 'B08 the fixed jump receiver (54322) still exists for the normal mode' ($class1Code -match 'new UdpClient\(54322\)')
Check 'B09 plain commands from the fixed port are executed in the normal mode ONLY (no fixed-port fallback in the managed mode)' ($class1Code -match 'if \(normal\) commands\.Add\(')
Check 'B10 the managed commands come from the validated endpoint only' (($class1Code -match 'jumpEndpoint\.Drain\(validated\)') -and ($class1Code -match 'new JumpInput\(c\.Text, c\.RequestId\)'))
Check 'B11 the RequestId of the pending jump reaches the JUMP_COMPLETE (SendJumpComplete(completeBytes, pendingJumpRequestId))' ($class1Code -match 'batch\.SendJumpComplete\(completeBytes, pendingJumpRequestId\)')
Check 'B12 JUMP_COMPLETE text and the payload builders are unchanged' (($class1Code -match '\$"JUMP_COMPLETE:\{pendingJumpType\}"') -and ($class1Code -match 'SCENARIO_ID:\{scenarioId\},SPEED:'))
Check 'B13 the jump endpoint is created in its own try block and disposed with the plugin' (($class1Code -match 'CurrentJumpEndpoint\.Create\(') -and ($class1Code -match 'jumpEndpoint\.Dispose\(\)'))
Check 'B14 the jump command grammar of the plugin (JUMP_STA_TIME / JUMP_LOC_TIME handling) is unchanged' (($class1Code -match 'msg\.StartsWith\("JUMP_STA_TIME:"\)') -and ($class1Code -match 'msg\.StartsWith\("JUMP_LOC_TIME:"\)'))

Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'PID-D6 Current jump offline tests passed.'
