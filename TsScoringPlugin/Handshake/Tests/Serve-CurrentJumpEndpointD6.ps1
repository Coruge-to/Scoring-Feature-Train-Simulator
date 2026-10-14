param(
    [Parameter(Mandatory = $true)][string]$Folder,
    [Parameter(Mandatory = $true)][int]$BvePid,
    [Parameter(Mandatory = $true)][string]$Instance,
    [Parameter(Mandatory = $true)][uint32]$AppPid,
    [int]$Seconds = 30,
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# PID-D6 test helper (not a product file, installs nothing): serves ONE real Current jump endpoint - the production CurrentJumpEndpoint with its named mapping
# (Local\TSScoringPlugin.v1.<BvePid>.CurrentJump) and its loopback UDP socket - for a real Python client of tests\test_current_jump_endpoint_live_d6.py.
# BvePid must be an unused synthetic PID. Ends when <Folder>\stop.flag exists or after -Seconds.
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
Add-Type -Path $sources -ReferencedAssemblies @('System.dll', 'System.Core.dll')
[CurrentJumpD6TestFixture]::Serve($Folder, $BvePid, $Instance, $AppPid, $Seconds)
