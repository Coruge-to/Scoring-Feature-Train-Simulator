# Test-PackageGuardST3.ps1 (Windows PowerShell 5.1, ASCII only) - the N-12 package guard as a PowerShell entry. Phase PID-D4JA StationIndex ST-3e0.
#
# It asks package\source_package.py (offline, standard library only) whether the package in -RepoRoot is the ONE official combination: the Python runtime set, the Current project, the
# Legacy project and the Shared sources carry the same TSJUMP2 bundle, every source is the one package\source-package-manifest.json names (SHA-256 of the Git blob), and the compile lists
# are the manifest's. Anything it can not read or understand is a refusal.
#
# READ ONLY: this entry writes no file, changes no setting, starts no program other than the given Python interpreter running the guard, and builds nothing. Every path is passed explicitly:
# nothing is taken from the folder of this script or from the current directory.
#
#   -RepoRoot     absolute path of the repository (or of a byte copy of it) that holds the package
#   -PythonExe    absolute path of python.exe
#   -ManifestPath absolute path of a manifest to check instead of the one in the repository (optional)
#   -Mode         worktree (default): the work tree is what is checked
#                 commit: the work tree must also be exactly what -Rev of the repository holds
#   -Rev          the revision for -Mode commit (default HEAD)
#   -VerifyCleanFilter  also ask git itself whether the blob the guard computes is the blob git stores
#
# Exit code 0 = ACCEPT, 1 = REJECT, 2 = bad arguments. The deployment of a package is not decided here: a verdict never allows a deployment before the ST-3e1 build manifest exists.
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [string]$ManifestPath = '',
    [ValidateSet('worktree', 'commit')][string]$Mode = 'worktree',
    [string]$Rev = 'HEAD',
    [switch]$VerifyCleanFilter
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Stop-WithUsage {
    param([string]$Message)
    [System.Console]::Error.WriteLine('USAGE: ' + $Message)
    exit 2
}

if (-not [System.IO.Path]::IsPathRooted($RepoRoot)) { Stop-WithUsage '-RepoRoot must be an absolute path' }
if (-not [System.IO.Path]::IsPathRooted($PythonExe)) { Stop-WithUsage '-PythonExe must be an absolute path' }
if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) { Stop-WithUsage ('-RepoRoot is not a folder: ' + $RepoRoot) }
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { Stop-WithUsage ('-PythonExe is not a file: ' + $PythonExe) }
$tool = Join-Path $RepoRoot 'package\source_package.py'
if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
    [System.Console]::Out.WriteLine('RESULT: REJECT  the guard is missing: package\source_package.py')
    exit 1
}
$toolArgs = @('-I', '-B', $tool, 'check', '--repo-root', $RepoRoot, '--mode', $Mode, '--rev', $Rev)
if ($ManifestPath -ne '') {
    if (-not [System.IO.Path]::IsPathRooted($ManifestPath)) { Stop-WithUsage '-ManifestPath must be an absolute path' }
    $toolArgs += @('--manifest', $ManifestPath)
}
if ($VerifyCleanFilter) { $toolArgs += '--verify-clean-filter' }

$env:PYTHONDONTWRITEBYTECODE = '1'
$lines = & $PythonExe @toolArgs
$code = $LASTEXITCODE
foreach ($line in $lines) { [System.Console]::Out.WriteLine([string]$line) }
if ($code -eq 0) { [System.Console]::Out.WriteLine('PASS  N-12 package guard: the package is the official combination (mode ' + $Mode + ')') }
else { [System.Console]::Out.WriteLine('FAIL  N-12 package guard: the package is refused (mode ' + $Mode + ', exit ' + $code + ')') }
exit $code
