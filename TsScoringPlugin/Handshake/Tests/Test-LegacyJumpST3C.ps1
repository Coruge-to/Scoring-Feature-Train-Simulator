# PHASE PID-D4JA StationIndex ST-3c - runner of the compiled tests of the Legacy jump transaction (v2 over the shared JumpWire) and of the STALIST acknowledgement (R1-B).
# Written FIRST: RED before the product.
#
# What it does: compiles the AtsEx-free sources of the Legacy telemetry project (the files its project compiles, LegacyTelemetryExtension.cs left out) into a TEST assembly
# (LegacyOfflineSourceSet.dll, in the run folder under -LogDir; it is NOT the product DLL: no Extension class, never deployed, removed with the run folder), compiles the LJX-1 rig
# and the ST-3c cases (LegacyJumpST3CTestCases.cs) against it, and runs the cases. No BVE, no AtsEX runtime, no fixed port, no product build.
#
# -Expect green (default): every case must be PASS.
# -Expect red: the RED stage - every RED case must fail with a DECLARED code (PASS is an UNEXPECTED PASS = stop), every GUARD case must be PASS, INVALID is never accepted.
# Exit codes: 0 every result is as expected; 1 at least one unexpected result; 2 inconclusive (BVE / python running, no compiler).
# ASCII-only on purpose. Windows PowerShell 5.1.
param(
    [ValidateSet('green', 'red')][string]$Expect = 'green',
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$SourceDir = '',
    [string]$LogDir = '',
    [string]$Tag = '',
    [string]$Only = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = [string](Split-Path (Split-Path $Root -Parent) -Parent)
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if ([string]::IsNullOrEmpty($Tag)) { $Tag = (Get-Date -Format 'yyyyMMdd-HHmmss') }
if ([string]::IsNullOrEmpty($LogDir)) { $LogDir = Join-Path $Root ('logs\jump-st3c-tests\' + $Tag) }
New-Item -ItemType Directory -Force $LogDir | Out-Null
$testsDir = Join-Path $Root 'Tests'
$legacyProject = Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'
if ([string]::IsNullOrEmpty($SourceDir)) { $SourceDir = Split-Path $legacyProject -Parent }

$results = New-Object System.Collections.Generic.List[object]
function Report([string]$id, [string]$kind, [string]$outcome, [string]$detail, [string]$redCode = '') {
    $isExpected = $false
    if ($Expect -eq 'green') { $isExpected = ($outcome -eq 'PASS') }
    elseif ($kind -eq 'RED') { $isExpected = ($outcome -eq 'RED') }
    else { $isExpected = ($outcome -eq 'PASS') }
    $r = [pscustomobject]@{ Id = $id; Kind = $kind; Outcome = $outcome; RedCode = $redCode; Expected = $isExpected; Detail = $detail }
    $results.Add($r)
    $mark = if ($isExpected) { 'ok ' } else { 'BAD' }
    $line = ('{0} {1,-8} {2,-6} {3,-8} {4,-26} {5}' -f $mark, $id, $kind, $outcome, $redCode, ($detail -replace "[\r\n]+", ' '))
    if ($line.Length -gt 380) { $line = $line.Substring(0, 380) }
    $line
}

Write-Host ('LEGACYJUMP-ST3C expect=' + $Expect + ' tag=' + $Tag)
$running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(BveTs|BveTs5|BveTs6|python|pythonw)$' -or $_.ProcessName -match 'AtsEx' })
if ($running.Count -gt 0) {
    Write-Host ('INCONCLUSIVE: BVE / python is running (' + (($running | ForEach-Object { $_.ProcessName + ':' + $_.Id }) -join ',') + '); the tests do not start while they run.')
    exit 2
}

# ---- stage 1: the product source set (AtsEx free) --------------------------------------------------------------------------------------------
$work = Join-Path $LogDir 'work-st3c'
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force $work | Out-Null
$doc = New-Object System.Xml.XmlDocument
$doc.Load($legacyProject)
$includes = @($doc.SelectNodes("//*[local-name()='Compile']") | ForEach-Object { $_.GetAttribute('Include') })
$files = @($includes | Where-Object { $_ -notmatch 'LegacyTelemetryExtension\.cs$' } | ForEach-Object { [IO.Path]::GetFullPath((Join-Path (Split-Path $legacyProject -Parent) $_)) })
if ($SourceDir -ne (Split-Path $legacyProject -Parent)) {
    # a different source folder (the pristine tree for the RED stage): the same file list, resolved against that folder
    $files = @($includes | Where-Object { $_ -notmatch 'LegacyTelemetryExtension\.cs$' } | ForEach-Object { [IO.Path]::GetFullPath((Join-Path $SourceDir $_)) })
}
$missing = @($files | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) { Write-Host ('INCONCLUSIVE: source file(s) absent: ' + ($missing -join ', ')); exit 2 }
Add-Type -AssemblyName Microsoft.CSharp
$prodDll = Join-Path $work 'LegacyOfflineSourceSet.dll'
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.GenerateInMemory = $false
$cp.OutputAssembly = $prodDll
$cp.TreatWarningsAsErrors = $false
$cp.CompilerOptions = '/d:LEGACY_JUMP_EXEC /nowarn:1591'
foreach ($r in @('System.dll', 'System.Core.dll')) { $cp.ReferencedAssemblies.Add($r) | Out-Null }
$prodResult = $provider.CompileAssemblyFromFile($cp, [string[]]$files)
$prodErrors = @()
foreach ($e in $prodResult.Errors) { if (-not $e.IsWarning) { $prodErrors += ($e.ErrorNumber + ' ' + [IO.Path]::GetFileName($e.FileName) + ' line ' + $e.Line + ' ' + $e.ErrorText) } }
if ($prodErrors.Count -gt 0) {
    Report 'A01' 'GUARD' 'FAIL' ('the product source set does not compile: ' + (($prodErrors | Select-Object -First 5) -join ' | '))
    exit 1
}
Report 'A01' 'GUARD' 'PASS' ('the ' + $files.Count + ' sources of the Legacy project that need no AtsEx compile into a test assembly')

# ---- stage 2: the rig and the cases ----------------------------------------------------------------------------------------------------------
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class S3cResolver
{
    private static string[] dirs = new string[0];
    private static bool installed;
    public static void Install(string[] d)
    {
        dirs = d;
        if (installed) { return; }
        installed = true;
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string name = e.Name.Split(',')[0];
            foreach (string dir in dirs)
            {
                string p = Path.Combine(dir, name + ".dll");
                if (File.Exists(p)) { return Assembly.LoadFrom(p); }
            }
            return null;
        };
    }
}
"@
$fixDll = Join-Path $work 'TsScoringLegacyTelemetryTests.dll'
$sources = @('LegacyJumpPlaneTestKit.cs', 'LegacyJumpPlaneTestFixture.cs', 'LegacyIlCallScan.cs', 'TelemetryTestFixture.cs', 'LegacyDataPlaneTestFixture.cs',
    'LegacyJumpExecTestFixture.cs', 'LegacyJumpST3CTestCases.cs') | ForEach-Object { Join-Path $testsDir $_ }
try {
    Add-Type -Path $sources -ReferencedAssemblies @($prodDll, 'System.dll', 'System.Core.dll') -OutputAssembly $fixDll -OutputType Library -IgnoreWarnings
}
catch {
    Report 'A02' 'GUARD' 'FAIL' ('the rig and the cases do not compile: ' + $_.Exception.Message)
    exit 1
}
Report 'A02' 'GUARD' 'PASS' 'the LJX-1 rig and the ST-3c cases compile against the source set'
[S3cResolver]::Install(@($work, $legacyHost))
$prod = [Reflection.Assembly]::LoadFrom($prodDll)
$fix = [Reflection.Assembly]::LoadFrom($fixDll)
$type = $fix.GetType('TsScoringLegacyTelemetryTests.LegacyJumpST3CTestFixture')

# the vector table gives the formal and the ambiguous v1 inputs
$vec = Get-Content (Join-Path $repo 'tests\jump_wire_vectors.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$formal = @($vec.equivalence | Where-Object { $_.current_accepts -and $_.jumpwire_accepts } | ForEach-Object { [string]$_.raw })
$ambiguous = @($vec.equivalence | Where-Object { $_.current_accepts -and -not $_.jumpwire_accepts } | ForEach-Object { [string]$_.raw })
$type.GetMethod('SetVectors').Invoke($null, @([string[]]$formal, [string[]]$ambiguous)) | Out-Null

[string[]]$onlyIds = @($Only -split ',' | Where-Object { $_ })
$found = @($type.GetMethod('DiscoverIds').Invoke($null, $null))
Write-Host ('discovered ' + $found.Count + ' cases: ' + ($found -join ' '))
$rr = $type.GetMethod('Run').Invoke($null, @($prod, ('s' + (Get-Date -Format 'HHmmss')), $repo, $onlyIds))

$tsv = New-Object System.Collections.Generic.List[string]
$tsv.Add("id`tkind`toutcome`tred_code`tchecks`tfailed`tseconds`tfail_text`ttitle")
foreach ($t in $rr.Tests) {
    $ft = ([string]$t.FailText) -replace "[`t`r`n]", ' '
    $tsv.Add(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6:N1}`t{7}`t{8}" -f $t.Id, $t.Kind, $t.Outcome, $t.RedCode, $t.Checks, $t.Failed, $t.Seconds, $ft, $t.Label))
    [IO.File]::WriteAllText((Join-Path $LogDir ('case-' + $t.Id + '.log')), [string]$t.Log, (New-Object Text.UTF8Encoding($false)))
}
[IO.File]::WriteAllLines((Join-Path $LogDir 'results.tsv'), $tsv.ToArray(), (New-Object Text.UTF8Encoding($false)))
$expectInvoked = if ($onlyIds.Count -gt 0) { $onlyIds.Count } else { $found.Count }
Report 'A03' 'GUARD' $(if ($rr.Discovered -eq $found.Count -and $rr.Invoked -eq $expectInvoked) { 'PASS' } else { 'FAIL' }) ('discovered ' + $rr.Discovered + ' = invoked ' + $rr.Invoked)
foreach ($t in $rr.Tests) {
    $detail = ('checks ' + $t.Checks + ' failed ' + $t.Failed + ' ' + $t.Label)
    if ($t.Outcome -ne 'PASS') { $detail = ('checks ' + $t.Checks + ' failed ' + $t.Failed + ' :: ' + $t.FailText) }
    Report $t.Id $t.Kind $t.Outcome $detail $t.RedCode
}

# ---- verdict ---------------------------------------------------------------------------------------------------------------------------------
$bad = @($results | Where-Object { -not $_.Expected })
$unexpectedPass = @($results | Where-Object { $Expect -eq 'red' -and $_.Kind -eq 'RED' -and $_.Outcome -eq 'PASS' })
Write-Host ''
Write-Host ('RESULTS=' + $results.Count + ' EXPECTED=' + ($results.Count - $bad.Count) + ' UNEXPECTED=' + $bad.Count + ' UNEXPECTED_PASS=' + $unexpectedPass.Count + ' expect=' + $Expect)
if ($bad.Count -gt 0) { exit 1 }
Write-Host 'ST-3c Legacy jump compiled tests: all results as expected.'
