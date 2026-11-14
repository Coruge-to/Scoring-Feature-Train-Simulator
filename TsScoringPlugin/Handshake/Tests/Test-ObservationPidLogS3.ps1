# PID-S3 offline test of the per-PID observation log (LOG-R1..R6) and of the recovery tool (LOG-R4).
# Compiles Shared\ObservationLog.cs + Shared\HandshakeProtocol.cs with the harness (Roslyn csc, LangVersion 9) into a temp folder and runs it against a private temp
# log folder. No BVE, no Downloads, no network. ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:pass = 0; $script:fail = 0
function Check([string]$name, [bool]$ok) { if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) } }

$csc = @('C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\Roslyn\csc.exe', 'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe') | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $csc) { throw 'Roslyn csc.exe not found' }
$work = Join-Path ([IO.Path]::GetTempPath()) ('pidlog-s3-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $work | Out-Null
try {
    $exe = Join-Path $work 'harness.exe'
    $out = & $csc /nologo /target:exe /langversion:9 /nullable:disable /out:$exe (Join-Path $Root 'Shared\ObservationLog.cs') (Join-Path $Root 'Shared\HandshakeProtocol.cs') (Join-Path $Root 'Tests\ObservationPidLogS3\Harness.cs') 2>&1
    Check 'S01 the harness compiles' (($LASTEXITCODE -eq 0) -and (Test-Path $exe))
    if ($LASTEXITCODE -ne 0) { $out | ForEach-Object { Write-Host $_ } }
    $logs = Join-Path $work 'logs'
    $run = & $exe $logs 2>&1
    $run | ForEach-Object { Write-Host $_ }
    Check 'S02 every runtime check of the harness passed (LOG-R1, R2, R3, R5, R6)' (($LASTEXITCODE -eq 0) -and (@($run | Where-Object { $_ -like 'FAIL *' }).Count -eq 0))

    # LOG-R4: the recovery tool reads EVERY per-PID file (-All) and the one of a PID (-BvePid); the old single fixed name is not special any more
    $tool = Join-Path $Root 'Tools\Classify-Observation.ps1'
    $files = @(Get-ChildItem $logs -Filter 'TSScoring-Phase-C1-Observation-P*.log')
    Check 'S03 the harness left one file per PID (3 PIDs)' ($files.Count -eq 3)
    $all = (& powershell -NoProfile -ExecutionPolicy Bypass -File $tool -LogDir $logs -All 2>&1) -join "`n"
    $heads = [regex]::Matches($all, '(?m)^== log file: (.+)$')
    Check 'S04 LOG-R4 -All classifies every per-PID file (none missed)' (($heads.Count -eq $files.Count) -and (@($files | Where-Object { $all -match [regex]::Escape($_.Name) }).Count -eq $files.Count))
    $one = (& powershell -NoProfile -ExecutionPolicy Bypass -File $tool -LogDir $logs -BvePid 52003 2>&1) -join "`n"
    Check 'S05 LOG-R4 -BvePid classifies only that PID file' (($one -match 'Observation-P52003\.log') -and ($one -notmatch 'Observation-P41001\.log'))
    $none = (& powershell -NoProfile -ExecutionPolicy Bypass -File $tool -LogDir $logs -BvePid 99999 2>&1) -join "`n"
    Check 'S06 an absent PID reports no log (exit 2), nothing else is read' (($none -match 'No log file') -and ($LASTEXITCODE -eq 2))
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'PID-S3 per-PID observation log tests passed.'
