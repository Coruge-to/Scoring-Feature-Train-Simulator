param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,
    [string]$GoldenRoot = ''
)
# PID-D3 offline tests of the Current Telemetry sender's DataPlane side. No BVE, no BveEX, no network traffic (a fake transport collects the datagrams);
# the only operating system objects are synthetic named mappings under an unused high PID and a temporary log folder.
# Optional -GoldenRoot: also writes the C# -> Python interop datagrams (validated by tests\test_current_dataplane_d3_interop.py).
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$plugin = Join-Path $RepositoryRoot 'TsScoringPlugin'
$shared = Join-Path $plugin 'Handshake\Telemetry\Shared'
$sources = @(
    (Join-Path $shared 'DataPlaneProtocol.cs'),
    (Join-Path $shared 'TelemetryDirectoryReader.cs'),
    (Join-Path $plugin 'TsScoringPlugin\CurrentDataPlane.cs'),
    (Join-Path $plugin 'Handshake\Tests\CurrentDataPlaneTestFixture.cs')
)
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Code([string]$path) {
    # source text without comments, for the static checks
    $t = [IO.File]::ReadAllText($path)
    $t = [regex]::Replace($t, '(?s)/\*.*?\*/', '')
    return ([regex]::Replace($t, '(?m)//.*$', ''))
}

Write-Host '--- A: compiled tests (CurrentDataPlaneTestFixture)'
Add-Type -Path $sources -ReferencedAssemblies @('System.dll', 'System.Core.dll')
$results = [CurrentDataPlaneTestFixture]::Run($GoldenRoot)
$checks = $results[0]
$bad = @($results | Select-Object -Skip 1)
Check ('A01 every compiled check passed (' + $checks + ')') ($bad.Count -eq 0)
foreach ($b in $bad) { Write-Host ('  FAILED: ' + $b) }

Write-Host '--- B: static checks (Current-only, separation, no mode marker, no fixed-port fallback in the managed path)'
$dp = Join-Path $plugin 'TsScoringPlugin\CurrentDataPlane.cs'
$class1 = Join-Path $plugin 'TsScoringPlugin\Class1.cs'
$csproj = Join-Path $plugin 'TsScoringPlugin\TsScoringPlugin.csproj'
$dpCode = Code $dp
$class1Code = Code $class1
Check 'B01 CurrentDataPlane.cs holds no fixed 54321 / 54322 and no UdpClient' (($dpCode -notmatch '54321') -and ($dpCode -notmatch '54322') -and ($dpCode -notmatch 'UdpClient'))
Check 'B02 CurrentDataPlane.cs references no Caller / Handshake / BveEx / AtsEx / Legacy type' (($dpCode -cnotmatch 'TSScoringPlugin\.Handshake') -and ($dpCode -cnotmatch 'BveEx') -and ($dpCode -cnotmatch 'AtsEx') -and ($dpCode -cnotmatch 'Legacy(?!TextPayload)'))
Check 'B03 the new file is a Compile item of the Current project only' ((Get-Content $csproj -Raw) -match 'CurrentDataPlane\.cs')
$legacyProj = Get-Content (Join-Path $plugin 'Handshake\Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj') -Raw
# PID-D4 Slice 1 (owner decision J3), re-pinned on purpose: the Legacy Telemetry project LINKS this file (a Link item, never a copy; the file itself stays byte-identical, see B06 and Test-LegacyDataPlaneD4 F04).
Check 'B04 the Legacy Telemetry project reaches the Current DataPlane file only through one Compile Link item (J3), never a copy' ((([regex]::Matches(([regex]::Replace($legacyProj, '<!--[\s\S]*?-->', '')), 'CurrentDataPlane\.cs')).Count -eq 2) -and ($legacyProj -match '<Compile Include="\.\.\\\.\.\\\.\.\\TsScoringPlugin\\CurrentDataPlane\.cs">\s*<Link>Shared\\CurrentDataPlane\.cs</Link>'))
$legacySrc = @(Get-ChildItem (Join-Path $plugin 'Handshake\Telemetry') -Recurse -Filter *.cs | Where-Object { $_.FullName -notmatch '\\obj\\' })
# ... and exactly one Legacy source (the host independent sink LegacyDataPlaneSink.cs, the adapter of J3) uses the Current routing types
Check 'B05 only the Legacy sink adapter (LegacyDataPlaneSink.cs) uses a Current DataPlane type' ((@($legacySrc | Where-Object { (Get-Content $_.FullName -Raw) -match 'CurrentTelemetryRouter|CurrentModeLatch|CallerControlPlaneProbe' } | ForEach-Object { $_.Name }) -join ',') -eq 'LegacyDataPlaneSink.cs')
Check 'B06 the shared protocol and reader files are unchanged by this slice' ((git -C $RepositoryRoot status --short -- TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs | Measure-Object).Count -eq 0)
$hp = [IO.File]::ReadAllText((Join-Path $plugin 'Handshake\Shared\HandshakeProtocol.cs'))
Check 'B07 the Enabled / Ready names equal those of HandshakeProtocol.cs' (($hp -match 'EnabledName\(int pid\) \{ return "Local\\\\TSScoringPlugin\.v1\." \+ pid \+ "\.Enabled"; \}') -and ($hp -match 'ReadyName\(int pid\) \{ return "Local\\\\TSScoringPlugin\.v1\." \+ pid \+ "\.Ready"; \}'))
Check 'B08 the sender never opens the AppDirectory itself to decide the mode (only the shared reader resolves endpoints)' ($dpCode -notmatch 'AppDirectory"')
$sendSites = [regex]::Matches($class1Code, 'udpClient\.Send\(')
Check 'B09 Class1.cs has no direct udpClient.Send left (all sends go through the router / transport)' ($sendSites.Count -eq 0)
$ctor = [regex]::Match($class1Code, '(?s)public ScoringPlugin\(PluginBuilder builder\).*?private void HeartbeatTimer_Elapsed')
$tryCount = ([regex]::Matches($ctor.Value, '\btry\b')).Count
Check 'B10 the constructor is split into independent try blocks (diagnostics, sender, heartbeat, jump receiver)' ($tryCount -ge 4)
$jumpIdx = $ctor.Value.IndexOf('new UdpClient(54322)')
$hbIdx = $ctor.Value.IndexOf('new Timer(50)')
Check 'B11 the heartbeat is started before, and independently of, the 54322 bind' (($jumpIdx -gt 0) -and ($hbIdx -gt 0) -and ($hbIdx -lt $jumpIdx))
Check 'B12 the jump receiver port, protocol and command handling are unchanged (54322, JUMP_STA_TIME / JUMP_LOC_TIME)' (($class1Code -match 'new UdpClient\(54322\)') -and ($class1Code -match 'JUMP_STA_TIME:') -and ($class1Code -match 'JUMP_LOC_TIME:'))
Check 'B13 JUMP_COMPLETE text and the payload builders are unchanged' (($class1Code -match '\$"JUMP_COMPLETE:\{pendingJumpType\}"') -and ($class1Code -match 'SCENARIO_ID:\{scenarioId\},SPEED:'))
Check 'B14 no new mode marker object: only the existing Enabled / Ready events are probed' (([regex]::Matches($dpCode, 'Local\\\\TSScoringPlugin')).Count -eq 2)

Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'PID-D3 Current DataPlane offline tests passed.'
