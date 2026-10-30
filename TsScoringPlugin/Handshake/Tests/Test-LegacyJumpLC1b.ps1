# PHASE LC-1b - runner of the C# RED / characterization cases of the Legacy Jump executor (LegacyJumpLcTestCases.cs). ASCII-only on purpose. Windows PowerShell 5.1.
#
# Builds the SAME fixture as the LJX-1 runner (the 8 LJX-1 sources) plus LegacyJumpLcTestCases.cs, loads the DLL under test and runs ONLY the LC-J cases. Nothing is installed or
# edited; it writes under -LogDir only. No BVE, no AtsEX runtime (the fakes of the LJX-1 harness). Loopback sockets and mappings of synthetic PIDs only.
#   -Expect red   (the state of cab7dce): RED rows must FAIL with their declared check text; GUARD rows must PASS.
#   -Expect green (after the LC-4 fix):   every row must PASS.
# Exit codes: 0 every row as expected; 1 a row differs; 2 inconclusive (DLL absent).
param(
    [ValidateSet('red', 'green')][string]$Expect = 'red',
    [Parameter(Mandatory = $true)][string]$DllPath,
    [Parameter(Mandatory = $true)][string]$LogDir,
    [string]$TestsDir = '',
    [string]$Only = ''
)
Set-StrictMode -Version 2.0
if ([string]::IsNullOrEmpty($TestsDir)) { $TestsDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ErrorActionPreference = 'Stop'
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if (-not (Test-Path -LiteralPath $DllPath)) { Write-Host ('INCONCLUSIVE: product DLL absent: ' + $DllPath); exit 2 }
New-Item -ItemType Directory -Force $LogDir | Out-Null

# id -> kind, declared failing check (RED rows only)
$plan = [ordered]@{
    'LC-J01' = @('RED', 'the completion of the executed jump was sent exactly once')
    'LC-J02' = @('RED', 'a moved host leaves the official jump note pending')
    'LC-J03' = @('RED', 'a moved host leaves the official jump note pending')
    'LC-J04' = @('GUARD', '')
    'LC-J05' = @('GUARD', '')
    'LC-J06' = @('RED', 'C-LJ-1 contract: Completed with exactly one completion')
    'LC-J07' = @('RED', 'after the release the command completes with exactly one completion')
    'LC-J08' = @('RED', 'C-LJ-1 contract (v2): Completed with exactly one completion')
    'LC-J09' = @('RED', 'the command ended Abandoned(completion-scenario-changed)')
    'LC-J10' = @('GUARD', '')
    'LC-J02v2' = @('RED', 'a moved host leaves the official jump note pending')
    'LC-J03v2' = @('RED', 'a moved host leaves the official jump note pending')
    'LC-J05v2' = @('GUARD', '')
}

Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class LcResolver
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

$work = Join-Path $LogDir 'work'
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force $work | Out-Null
$dllCopy = Join-Path $work (Split-Path $DllPath -Leaf)
Copy-Item $DllPath $dllCopy
$fixDll = Join-Path $work 'TsScoringLegacyTelemetryTests.dll'
$sources = @('LegacyJumpPlaneTestKit.cs', 'LegacyJumpPlaneTestFixture.cs', 'LegacyIlCallScan.cs', 'TelemetryTestFixture.cs', 'LegacyDataPlaneTestFixture.cs',
    'LegacyJumpExecTestFixture.cs', 'LegacyJumpExecTestCases.cs', 'LegacyJumpExecGolden.cs', 'LegacyJumpLcTestCases.cs') | ForEach-Object { Join-Path $TestsDir $_ }
Add-Type -Path $sources -ReferencedAssemblies @($dllCopy, 'System.dll', 'System.Core.dll') -OutputAssembly $fixDll -OutputType Library -IgnoreWarnings
[LcResolver]::Install(@($work, $legacyHost))
$prod = [Reflection.Assembly]::LoadFrom($dllCopy)
$fix = [Reflection.Assembly]::LoadFrom($fixDll)
$type = $fix.GetType('TsScoringLegacyTelemetryTests.LegacyJumpExecTestFixture')
$type.GetField('ExpectCompiledIn').SetValue($null, $true)

$ids = @($plan.Keys)
if ($Only -ne '') { $ids = @($Only -split ',' | Where-Object { $_ }) }
[string[]]$onlyIds = [string[]]@($ids | ForEach-Object { [string]$_ })
$repoRoot = [string](Split-Path (Split-Path (Split-Path $TestsDir -Parent) -Parent) -Parent)
$callArgs = New-Object 'object[]' 4
$callArgs[0] = $prod
$callArgs[1] = [string]('lc' + (Get-Date -Format 'HHmmss'))
$callArgs[2] = $repoRoot
$callArgs[3] = $onlyIds
$rr = $type.GetMethod('Run').Invoke($null, $callArgs)

$lines = New-Object System.Collections.Generic.List[string]
$bad = 0
$lines.Add('ID | kind | outcome | predicted | detail')
foreach ($t in $rr.Tests) {
    $kind = 'GUARD'; $decl = ''
    if ($plan.Contains($t.Id)) { $kind = $plan[$t.Id][0]; $decl = $plan[$t.Id][1] }
    $detail = ('checks ' + $t.Checks + ' failed ' + $t.Failed + ' ' + ([string]$t.FailText) + ' ' + $t.Label) -replace "[\r\n\t]+", ' '
    if ($Expect -eq 'green') { $ok = ($t.Outcome -eq 'PASS'); $pred = 'PASS' }
    elseif ($kind -eq 'RED') { $ok = ($t.Outcome -eq 'FAIL' -and ([string]$t.FailText).Contains($decl)); $pred = 'FAIL(' + $decl + ')' }
    else { $ok = ($t.Outcome -eq 'PASS'); $pred = 'PASS' }
    if (-not $ok) { $bad++ }
    $lines.Add(('{0} | {1} | {2} | {3} | {4}{5}' -f $t.Id, $kind, $t.Outcome, $pred, $(if ($ok) { '' } else { 'MISMATCH: ' }), $detail.Substring(0, [Math]::Min(300, $detail.Length))))
    [IO.File]::WriteAllText((Join-Path $LogDir ($t.Id + '.log')), [string]$t.Log, (New-Object Text.UTF8Encoding($false)))
}
$lines.Add(('rows=' + @($rr.Tests).Count + ' mismatches=' + $bad + ' expect=' + $Expect + ' ' + $rr.Header))
$lines | ForEach-Object { Write-Host $_ }
[IO.File]::WriteAllLines((Join-Path $LogDir 'results.txt'), $lines.ToArray(), (New-Object Text.UTF8Encoding($false)))
if ($bad -gt 0) { exit 1 }
exit 0
