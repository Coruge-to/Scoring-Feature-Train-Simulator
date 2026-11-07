# Shadow sway diagnostics - offline tests of the shared read-only reflection reader (SwayStateReader.cs). No BVE, no AtsEX, no BveEx, no network, no hooks.
# The real built telemetry DLL (which links the shared source) is loaded from memory and driven with FAKE types that have the STRUCTURE of the audited BVE passenger-sway
# figure (b4 / u / t, tests\SwayFakeTypes.cs, compiled here). Nothing is written outside logs\sway-reader-tests.
# This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\SwayFakeTypes.cs'
$testDir = Join-Path $Root 'logs\sway-reader-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
$compiled = $true
try {
    Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixtureSrc)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library -ErrorAction Stop
    Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class SwayResolver
{
    public static void Install(string[] dirs)
    {
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
    [SwayResolver]::Install(@($testDir, $legacyHost))
    $null = [Reflection.Assembly]::LoadFrom($dllCopy)
    $null = [Reflection.Assembly]::LoadFrom($fixtureDll)
} catch {
    $compiled = $false
    Check 'SR00 the fixture compiles against the telemetry DLL (the reader SwayStateReader and its API exist)' $false
    ("compile error: " + $_.Exception.Message.Substring(0, [Math]::Min(300, $_.Exception.Message.Length)))
}

function NewProbe([string]$version, [string]$entry) { return (New-Object TsScoringSwayFakes.SwayProbe($version, $entry)) }
$V5 = '5.8.7554.391'
$V6 = '6.0.7554.619'

if ($compiled) {
    # ---- the two audited versions resolve ------------------------------------------------------------------------------------------------------
    $p = NewProbe $V5 'current'; $o = [TsScoringSwayFakes.SwayFake]::Ok(0.01, 0.02, 0.03, 0.04)
    Check 'SR01 BVE5 5.8.7554.391: a structure like the audited one resolves (Ok) and the four states are read as they are' (($p.Resolve($o) -eq 'Ok') -and ($p.Read() -eq '0.01|0.02|0.03|0.04'))
    $p = NewProbe $V6 'legacy'
    Check 'SR02 BVE6 6.0.7554.619 resolves as well' (($p.Resolve($o) -eq 'Ok') -and ($p.Read() -eq '0.01|0.02|0.03|0.04'))
    # ---- the declaring type t is named: x = t::b, v = t::c, never the same-named fields of u (zeta 1.0 and the offset 0.0) ---------------------------
    $p = NewProbe $V5 'current'; $o2 = [TsScoringSwayFakes.SwayFake]::Ok(-0.0666, 0.5, 0.25, -0.75); $null = $p.Resolve($o2)
    Check 'SR03 x and v come from the declaring type t (the u fields of the same names - zeta 1.0 and the offset - are not mistaken for them)' ($p.Read() -eq '-0.0666|0.5|0.25|-0.75')
    # ---- an unknown version is disabled and the members are NOT explored ----------------------------------------------------------------------------
    $p = NewProbe '5.9.0.1' 'current'
    Check 'SR04 an unknown version is disabled (VersionUnsupported), nothing is read, and the structure is NOT probed (no guessing of private members)' (($p.Resolve($o) -eq 'VersionUnsupported') -and ($p.Read() -eq 'none') -and ($p.StructureProbes -eq 0) -and ($p.Detail -match 'version'))
    $p = NewProbe 'unknown' 'legacy'
    Check 'SR05 a version that could not be read ("unknown") is not allowed either' (($p.Resolve($o) -eq 'VersionUnsupported') -and ($p.Read() -eq 'none'))
    $p = NewProbe '' 'legacy'
    Check 'SR06 an empty version is not allowed' ($p.Resolve($o) -eq 'VersionUnsupported')
    # ---- the structure signature -----------------------------------------------------------------------------------------------------------------------
    $bad = @('no-d', 'wrong-base', 'float-omega', 'different-springs', 'no-states', 'bad-omega', 'bad-zeta', 'bad-lateral-signature')
    $okAll = $true; $noRead = $true
    foreach ($kind in $bad) {
        $p = NewProbe $V5 'current'
        $st = $p.Resolve([TsScoringSwayFakes.SwayFake]::Make($kind))
        if ($st -ne 'StructureMismatch') { $okAll = $false; "  structure case $kind resolved as $st" }
        if ($p.Read() -ne 'none') { $noRead = $false }
    }
    Check 'SR07 every wrong structure (a field missing, a wrong base chain, omega of the wrong type, springs of different types, not a spring) is a StructureMismatch' $okAll
    Check 'SR08 a refused structure reads nothing: never a 0 in its place' $noRead
    $p = NewProbe $V5 'current'; $null = $p.Resolve([TsScoringSwayFakes.SwayFake]::Make('bad-omega'))
    Check 'SR09 omega 2.0 is a signature mismatch (not 1.9792033717615696)' ($p.Detail -match 'signature')
    $p = NewProbe $V5 'current'; $null = $p.Resolve([TsScoringSwayFakes.SwayFake]::Make('bad-zeta'))
    Check 'SR10 zeta 0.7 is a signature mismatch (not 1.0)' ($p.Detail -match 'signature')
    $p = NewProbe $V5 'current'; $null = $p.Resolve([TsScoringSwayFakes.SwayFake]::Make('bad-lateral-signature'))
    Check 'SR11 the signature is checked on BOTH springs (a wrong lateral zeta refuses the whole reader)' (($p.Status -eq 'StructureMismatch') -and ($p.Detail -match 'signature'))
    $p = NewProbe $V5 'current'; $null = $p.Resolve([TsScoringSwayFakes.SwayFake]::Make('no-d'))
    Check 'SR12 a missing member is named as such' ($p.Detail -match 'member-absent')
    # ---- not available is not zero -----------------------------------------------------------------------------------------------------------------------
    $p = NewProbe $V5 'current'
    Check 'SR13 no source object: Pending, nothing is read, no exception' (($p.Resolve($null) -eq 'Pending') -and ($p.Read() -eq 'none'))
    $o3 = [TsScoringSwayFakes.SwayFake]::Ok(0.01, 0.02, 0.03, 0.04); $p = NewProbe $V5 'current'; $null = $p.Resolve($o3)
    [TsScoringSwayFakes.SwayFake]::Set($o3, [double]::NaN, 0.0, 0.0, 0.0)
    Check 'SR14 a non-finite state is not available (no 0, no NaN written)' ($p.Read() -eq 'none')
    [TsScoringSwayFakes.SwayFake]::Set($o3, 0.0, [double]::PositiveInfinity, 0.0, 0.0)
    Check 'SR15 an infinite state is not available' ($p.Read() -eq 'none')
    [TsScoringSwayFakes.SwayFake]::Set($o3, 0.05, 0.0, 0.0, 0.0)
    Check 'SR16 a finite reading after a bad one works again (a non-finite value is not a reason to give up)' ($p.Read() -eq '0.05|0|0|0')
    # ---- a failure is a cached state and is not repeated every Tick -------------------------------------------------------------------------------------
    $p = NewProbe $V5 'current'; $bo = [TsScoringSwayFakes.SwayFake]::Make('no-d')
    $null = $p.Resolve($bo); $null = $p.Resolve($bo); $null = $p.Resolve($bo)
    Check 'SR17 the same refused source object is resolved ONCE (the failure is cached; it is not re-explored every Tick)' (($p.ResolveAttempts -eq 1) -and ($p.StructureProbes -eq 1))
    $o4 = [TsScoringSwayFakes.SwayFake]::Ok(0.01, 0.02, 0.03, 0.04); $p = NewProbe $V5 'current'; $null = $p.Resolve($o4); $null = $p.Read()
    [TsScoringSwayFakes.SwayFake]::Break($o4, $true)
    $r1 = $p.Read(); $r2 = $p.Read(); $r3 = $p.Read(); $attempts = $p.ReadAttempts; $r4 = $p.Read(); $r5 = $p.Read()
    Check 'SR18 a reader whose spring disappears returns nothing and, after 3 consecutive failures, is Unavailable and no longer touches the object (the same exception is not repeated every Tick)' ((@($r1, $r2, $r3, $r4, $r5) -notcontains '0|0|0|0') -and ($r4 -eq 'none') -and ($p.Status -eq 'Unavailable') -and ($p.ReadAttempts -eq $attempts))
    # ---- a new scenario instance is resolved again -------------------------------------------------------------------------------------------------------
    $p = NewProbe $V5 'current'; $a1 = [TsScoringSwayFakes.SwayFake]::Ok(0.1, 0.0, 0.0, 0.0); $a2 = [TsScoringSwayFakes.SwayFake]::Ok(0.2, 0.0, 0.0, 0.0)
    $null = $p.Resolve($a1); $v1 = $p.Read(); $null = $p.Resolve($a2); $v2 = $p.Read()
    Check 'SR19 a new source object (a new scenario instance) is resolved again and its values are read' (($v1 -eq '0.1|0|0|0') -and ($v2 -eq '0.2|0|0|0') -and ($p.ResolveAttempts -eq 2))
    $p.Reset()
    Check 'SR20 Reset (a scenario boundary) forgets the binding: nothing is read until the next Resolve' (($p.Status -eq 'Pending') -and ($p.Read() -eq 'none'))
    # ---- read only -----------------------------------------------------------------------------------------------------------------------------------------
    $o5 = [TsScoringSwayFakes.SwayFake]::Ok(0.01, 0.02, 0.03, 0.04); $before = [TsScoringSwayFakes.SwayFake]::Dump($o5)
    $p = NewProbe $V5 'current'; $null = $p.Resolve($o5); for ($i = 0; $i -lt 50; $i++) { $null = $p.Read() }
    Check 'SR21 the reader does not change the BVE state (every field and the signature are as before after resolving and 50 reads)' ([TsScoringSwayFakes.SwayFake]::Dump($o5) -eq $before)
    # ---- the diagnostic (the SWAYR value) ---------------------------------------------------------------------------------------------------------------------
    $p = NewProbe $V5 'current'; $null = $p.Resolve($o5)
    Check 'SR22 the diagnostic of a success is result:version:entry' ($p.Diagnostic -eq 'ok:5.8.7554.391:current')
    $p = NewProbe '5.9.0.1' 'legacy'; $null = $p.Resolve($o5)
    Check 'SR23 the diagnostic of an unsupported version names the reason and the version' ($p.Diagnostic -match '^version-unsupported:5\.9\.0\.1:legacy')
    $p = NewProbe $V6 'legacy'; $null = $p.Resolve([TsScoringSwayFakes.SwayFake]::Make('no-d'))
    Check 'SR24 the diagnostic of a structure mismatch has a detail without comma, colon or space (it travels inside a telemetry line)' (($p.Diagnostic -match '^structure-mismatch:6\.0\.7554\.619:legacy:[^,: ]+$'))
    $p = NewProbe $V5 'current'
    Check 'SR25 the diagnostic of a reader that has no source yet is pending' ($p.Diagnostic -match '^pending:')
}

$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"SWAY-READER-L3 PASS=$pass FAIL=$fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
