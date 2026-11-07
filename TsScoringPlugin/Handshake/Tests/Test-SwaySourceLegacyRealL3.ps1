# Legacy sway SOURCE lookup against the REAL Legacy BveTypes wrappers and the REAL BVE5 types (BveTs.exe 5.8.7554.391 is only LOADED as an assembly: BVE is never started, no Main runs).
# The production host access (AtsExSwayHostAccess) and the finder run over real wrappers made from FAKE STATE (GetUninitializedObject of the real classes bz / ar / aw / ... / b4).
# It must run in a 32-bit PowerShell (BveTs.exe 5.8 is x86); a 64-bit start relaunches itself. Nothing is written outside logs\sway-source-real-tests. ASCII only.
param([string]$Root = (Split-Path $PSScriptRoot -Parent), [switch]$InnerX86)

$bve5 = 'C:\Program Files (x86)\mackoy\BveTs5'
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if (-not $InnerX86) {
    $x86 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path (Join-Path $bve5 'BveTs.exe')) -or -not (Test-Path $x86)) { "SWAY-SOURCE-REAL-L3 SKIPPED (BVE5 or the 32-bit PowerShell is not installed here) PASS=0 FAIL=0"; exit 0 }
    $out = & $x86 -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Root $Root -InnerX86 2>&1 | Out-String
    $out.TrimEnd()
    if ($out -match 'FAIL=0\s*$') { exit 0 } else { exit 1 }
}

$testDir = Join-Path $Root 'logs\sway-source-real-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null
$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$bveTypesDll = Join-Path $legacyHost 'BveTypes.dll'
$ok = $true
try {
    Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class RealSwayResolver
{
    public static void Install(string[] dirs)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string simple = new AssemblyName(e.Name).Name;
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies()) { if (string.Equals(a.GetName().Name, simple, StringComparison.OrdinalIgnoreCase)) { return a; } }
            foreach (string dir in dirs)
            {
                foreach (string ext in new string[] { ".dll", ".DLL", ".exe" })
                {
                    string p = Path.Combine(dir, simple + ext);
                    if (File.Exists(p)) { return Assembly.LoadFrom(p); }
                }
            }
            return null;
        };
    }
}
"@
    [RealSwayResolver]::Install(@($bve5, $legacyHost, $testDir))
    foreach ($n in 'SlimDX.dll', 'Mackoy.IInputDevice.DLL', 'Mackoy.XmlInterfaces.DLL', 'Irony.DLL') { $p = Join-Path $bve5 $n; if (Test-Path $p) { $null = [Reflection.Assembly]::LoadFrom($p) } }
    foreach ($n in 'FastCaching.dll', 'FastMember.dll', 'UnembeddedResources.dll', 'TypeWrapping.dll', 'BveTypes.dll') { $null = [Reflection.Assembly]::LoadFrom((Join-Path $legacyHost $n)) }
    $null = [Reflection.Assembly]::LoadFrom($dllCopy)
    $bve = [Reflection.Assembly]::LoadFrom((Join-Path $bve5 'BveTs.exe'))
    $factory = New-Object BveTypes.BveTypeSetFactory
    $factory.BveAssembly = $bve
    $null = $factory.Load()
    $fixture = [IO.File]::ReadAllText((Join-Path $Root 'Tests\SwayRealWrapperFakes.cs'))
    $fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
    Add-Type -TypeDefinition $fixture -ReferencedAssemblies @($dllCopy, $bveTypesDll) -OutputAssembly $fixtureDll -OutputType Library -ErrorAction Stop
    $null = [Reflection.Assembly]::LoadFrom($fixtureDll)
} catch {
    $ok = $false
    Check 'RW00 the real BveTypeSet loads against BveTs.exe 5.8 and the fixture compiles' $false
    ("setup error: " + $_.Exception.Message.Substring(0, [Math]::Min(400, $_.Exception.Message.Length)))
}

if ($ok) {
    $types = @{}
    foreach ($t in $bve.GetTypes()) { $types[$t.Name] = $t }
    function Uninit([string]$n) { return [Runtime.Serialization.FormatterServices]::GetUninitializedObject($types[$n]) }
    function MakeMainForm([bool]$withSway) {
        $drawer = Uninit 'ar'
        $listField = $null
        foreach ($f in $types['ar'].GetFields([Reflection.BindingFlags]'Instance,NonPublic,Public')) { if ($f.FieldType.IsGenericType -and $f.FieldType.GetGenericTypeDefinition().Name -like 'List*') { $listField = $f } }
        $list = [Activator]::CreateInstance($listField.FieldType)
        $fig = $null
        foreach ($n in 'aw', 'ci', 'e2', 'dz', 'ae', 'd2', 'd4', 'b4', 'fy', 'de') {
            if ($n -eq 'b4' -and -not $withSway) { continue }
            $o = Uninit $n
            if ($n -eq 'b4') { $fig = $o }
            [void]$list.Add($o)
        }
        $listField.SetValue($drawer, $list)
        $form = Uninit 'bz'
        foreach ($f in $types['bz'].GetFields([Reflection.BindingFlags]'Instance,NonPublic,Public')) { if ($f.FieldType -eq $types['ar']) { $f.SetValue($form, $drawer) } }
        return [pscustomobject]@{ Form = $form; Figure = $fig }
    }

    Check 'RW01 the real BveTypeSet (Legacy BveTypes 1.0.50314.2 over BveTs.exe 5.8.7554.391) loads' ($bve.GetName().Version.ToString() -eq '5.8.7554.391')
    $mf = MakeMainForm $true
    # the witness of the SHD-L-01 failure, in the same environment: the OLD loop throws, the exception is swallowed, no figure is found
    Check 'RW02 ClassWrapperBase.operator != throws NullReferenceException for a null left operand (the cause of SHD-L-01)' ([TsScoringRealWrapperFakes.RealBridge]::NullOperatorProbe() -eq 'CAUGHT System.NullReferenceException')
    Check 'RW03 the OLD loop of the SHD-L-01 build over the real wrappers finds NO figure (it catches System.NullReferenceException): this is pending:no-source' ([TsScoringRealWrapperFakes.RealBridge]::OriginalLoop([TsScoringRealWrapperFakes.RealBridge]::ItemsOf($mf.Form)) -eq 'CAUGHT System.NullReferenceException')
    # the production host access + finder
    $sel = $null; $stage = $null; $rawTried = $false
    $fig = [TsScoringRealWrapperFakes.RealBridge]::FindWrapper($mf.Form, $false, [ref]$sel, [ref]$stage, [ref]$rawTried)
    Check 'RW04 the PRODUCTION wrapper path over the real wrappers finds the b4 (selected_path wrapper, the very object, the raw path not run)' (($sel -eq 'wrapper') -and [object]::ReferenceEquals($fig, $mf.Figure) -and ($stage -eq 'none') -and (-not $rawTried))
    $sel = $null; $stage = $null; $rawTried = $false
    $fig = [TsScoringRealWrapperFakes.RealBridge]::FindWrapper($mf.Form, $true, [ref]$sel, [ref]$stage, [ref]$rawTried)
    Check 'RW05 when the wrapper path fails, the raw-list path finds the b4 through the REAL member names (bz.l, ar.a(), b4)' (($sel -eq 'raw-list') -and [object]::ReferenceEquals($fig, $mf.Figure) -and $rawTried)
    $mfNo = MakeMainForm $false
    $sel = $null; $stage = $null; $rawTried = $false
    $fig = [TsScoringRealWrapperFakes.RealBridge]::FindWrapper($mfNo.Form, $false, [ref]$sel, [ref]$stage, [ref]$rawTried)
    Check 'RW06 a real list WITHOUT the sway figure: nothing is found by either path (no-sway-item), never a made-up figure' (($sel -eq 'none') -and ($fig -eq $null) -and ($stage -eq 'no-sway-item') -and $rawTried)
    # the raw names exist in the real exe
    $bz = $types['bz']; $ar = $types['ar']; $b4 = $types['b4']
    $fl = $bz.GetField('l', [Reflection.BindingFlags]'Instance,NonPublic,Public,DeclaredOnly')
    $am = $ar.GetMethod('a', [Reflection.BindingFlags]'Instance,NonPublic,Public,DeclaredOnly', $null, [Type]::EmptyTypes, $null)
    Check 'RW07 the raw member names of the audited BVE5 exist exactly: bz.l is an ar, ar.a() returns an IList, the class b4 exists' (($fl -ne $null) -and ($fl.FieldType.Name -eq 'ar') -and ($am -ne $null) -and ([Collections.IList].IsAssignableFrom($am.ReturnType)) -and ($b4 -ne $null))
}

$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"SWAY-SOURCE-REAL-L3 PASS=$pass FAIL=$fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
