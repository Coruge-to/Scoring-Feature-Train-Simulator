# PHASE SI-B1 (B1-probe) - builds the OBSERVATION-ONLY probe DLL (version 0.4.1.1, product file name) OUTSIDE the repository tree and, with -AlsoProduct, rebuilds the product DLL
# (src, 0.4.0.0) the same way so that the two can be compared. Nothing is deployed, copied into BVE / BveEX folders, started or committed.
#   .\Build-B1Probe.ps1 -WorkDir <folder> [-AlsoProduct]
# Output: <WorkDir>\probe-out\TSScoringPlugin.AtsExLegacy.Telemetry.dll  (and <WorkDir>\product-out\... with -AlsoProduct). The generated Extension copy is <WorkDir>\gen\.
# This script is ASCII-only on purpose.
param(
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [string]$Root = '',
    [switch]$AlsoProduct
)

$ErrorActionPreference = 'Stop'
if ($Root -eq '') { $Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent }      # Tests\B1Probe -> Tests -> Handshake
$repoFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$work = [IO.Path]::GetFullPath($WorkDir).TrimEnd('\')
if ($work.StartsWith($repoFull, [StringComparison]::OrdinalIgnoreCase)) { Write-Host 'REFUSED: -WorkDir must be outside the repository tree.'; exit 2 }
$deployRoots = @('C:\Program Files', 'C:\Program Files (x86)', 'C:\Users\Public', 'C:\Windows')
foreach ($d in $deployRoots) { if ($work.StartsWith($d, [StringComparison]::OrdinalIgnoreCase)) { Write-Host ('REFUSED: -WorkDir may not be inside ' + $d + ' (nothing is ever built into an installed folder).'); exit 2 } }

$msbuild = $null
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (Test-Path -LiteralPath $vswhere) { $msbuild = (& $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1) }
if (-not $msbuild -or -not (Test-Path -LiteralPath $msbuild)) { Write-Host 'REFUSED: MSBuild was not found.'; exit 2 }

New-Item -ItemType Directory -Force (Join-Path $work 'gen') | Out-Null
$gen = Join-Path $work 'gen\LegacyTelemetryExtension.B1Probe.g.cs'
& (Join-Path $PSScriptRoot 'New-B1ProbeExtension.ps1') -Root $Root -Output $gen
if ($LASTEXITCODE -ne 0) { Write-Host 'FAILED: the probe Extension copy could not be generated.'; exit 1 }

$proj = Join-Path $PSScriptRoot 'TSScoringPlugin.AtsExLegacy.Telemetry.B1Probe.csproj'
& $msbuild $proj /t:Rebuild /p:Configuration=Release ('/p:OutputPath=' + (Join-Path $work 'probe-out') + '\') ('/p:IntermediateOutputPath=' + (Join-Path $work 'probe-obj') + '\') ('/p:GeneratedExtension=' + $gen) /v:minimal /nologo /nr:false /m:1 /p:UseSharedCompilation=false
if ($LASTEXITCODE -ne 0) { Write-Host 'FAILED: the probe build failed.'; exit 1 }
$dll = Join-Path $work 'probe-out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Write-Host ('PROBE DLL: ' + $dll + ' ' + (Get-Item -LiteralPath $dll).VersionInfo.FileVersion + ' SHA256 ' + (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash)

if ($AlsoProduct) {
    $pproj = Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'
    & $msbuild $pproj /t:Rebuild /p:Configuration=Release ('/p:OutputPath=' + (Join-Path $work 'product-out') + '\') ('/p:IntermediateOutputPath=' + (Join-Path $work 'product-obj') + '\') /v:minimal /nologo /nr:false /m:1 /p:UseSharedCompilation=false
    if ($LASTEXITCODE -ne 0) { Write-Host 'FAILED: the product build failed.'; exit 1 }
    $pdll = Join-Path $work 'product-out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
    Write-Host ('PRODUCT DLL: ' + $pdll + ' ' + (Get-Item -LiteralPath $pdll).VersionInfo.FileVersion + ' SHA256 ' + (Get-FileHash -LiteralPath $pdll -Algorithm SHA256).Hash)
}
exit 0
