param([Parameter(Mandatory=$true)][string]$RepositoryRoot,[Parameter(Mandatory=$true)][string]$GoldenRoot)
Set-StrictMode -Version 2.0;$ErrorActionPreference='Stop'
$protocol=Join-Path $RepositoryRoot 'TsScoringPlugin\Handshake\Telemetry\Shared\DataPlaneProtocol.cs'
$fixture=Join-Path $RepositoryRoot 'TsScoringPlugin\Handshake\Tests\DataPlaneProtocolTestFixture.cs'
Add-Type -Path @($protocol,$fixture)
[DataPlaneProtocolTestFixture]::WriteGolden($GoldenRoot)
Write-Host 'PID-D1 C# golden generation passed.'
