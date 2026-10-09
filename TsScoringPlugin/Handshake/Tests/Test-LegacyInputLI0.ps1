# PHASE LI0 - offline tests of the AtsEX LEGACY scoring-input OBSERVATION (read only, diagnostic log only): handle / notch / pressure candidates, one- and two-lever
# detection, INative reachable or not, StateStore arrays of 0 / 1 / many elements, NaN / Infinity, line limits, generation reset, thread rules, and the proof that
# the telemetry stream, AVAIL and the gradient x 1000 contract of Phase L3 are unchanged.
# No BVE, no AtsEX runtime, no BveEX, no network, no hooks. The real built DLL is loaded from memory-safe copy and driven through FAKES of the Legacy API
# (tests\TelemetryTestFixture.cs, compiled here). Nothing is written outside logs\li0-tests. This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$testDir = Join-Path $Root 'logs\li0-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixtureSrc)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class Li0Resolver
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
[Li0Resolver]::Install(@($testDir, $legacyHost))
$telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
$fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)

function NewH([bool]$withInput) { return (New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList $withInput) }
function NewIn { return (NewH $true) }
$InputNames = @('TEL_INPUT_CAPABILITY', 'TEL_HANDLE_FIRST', 'TEL_HANDLE_CHANGE', 'TEL_SPEC_FIRST', 'TEL_SPEC_CHANGE', 'TEL_PRESSURE_FIRST', 'TEL_PRESSURE_CHANGE', 'TEL_INPUT_UNAVAILABLE', 'TEL_INPUT_SUMMARY')
function Ev($h, [string]$name) { return ,@($h.Diag.Named($name)) }
function InputEvents($h) { return ,@($h.Diag.Events | Where-Object { $InputNames -contains $_.Split(' ')[0] }) }
function Kv([string]$line, [string]$key) { $m = [regex]::Match($line, '(^| )' + [regex]::Escape($key) + '=([^ ]*)'); if ($m.Success) { return $m.Groups[2].Value } else { return $null } }
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
function Dbl([double[]]$a) { return ,$a }
$NEVERKEY = '(^|,)(REV|POW|BRK|ALLTXT|HTYPE|BCP|BPP):'
$NEVERTOK = @('handle', 'bcp', 'bpp')
$TI = 'TsScoringLegacyTelemetryTests.InputInfo'
$infoType = $fixAsm.GetType($TI)
function Info([string]$method, $args1) { return $infoType.GetMethod($method).Invoke($null, $args1) }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# A - one lever / two lever / unknown (the classification by the class name of the cab)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$tOne = $fixAsm.GetType('TsScoringLegacyTelemetryTests.OneLeverCab'); $tTwo = $fixAsm.GetType('TsScoringLegacyTelemetryTests.TwoLeverCab')
$tTwoSub = $fixAsm.GetType('TsScoringLegacyTelemetryTests.MyTwoLeverCab'); $tOther = $fixAsm.GetType('TsScoringLegacyTelemetryTests.UnrelatedCab')
Check 'A01 one-lever cab type is classified as one-lever (1)' ((Info 'Classify' @(, $tOne)) -eq 1)
Check 'A02 two-lever cab type, and a class derived from it, are classified as two-lever (2)' (((Info 'Classify' @(, $tTwo)) -eq 2) -and ((Info 'Classify' @(, $tTwoSub)) -eq 2))
Check 'A03 any other cab type, and no type at all, are unknown (0)' (((Info 'Classify' @(, $tOther)) -eq 0) -and ((Info 'Classify' @(, $null)) -eq 0))
$realOk = $false; $realOne = $null; $realTwo = $null
try {
    $bve = [Reflection.Assembly]::LoadFrom((Join-Path $legacyHost 'BveTypes.dll'))
    $realOne = $bve.GetType('BveTypes.ClassWrappers.OneLeverCab', $false); $realTwo = $bve.GetType('BveTypes.ClassWrappers.TwoLeverCab', $false)
    $realOk = ($realOne -ne $null) -and ($realTwo -ne $null)
} catch { $realOk = $false }
if ($realOk) {
    Check 'A04 the REAL BveTypes OneLeverCab / TwoLeverCab wrappers are classified one-lever / two-lever (class names exist in the installed host)' (((Info 'Classify' @(, $realOne)) -eq 1) -and ((Info 'Classify' @(, $realTwo)) -eq 2))
} else { 'SKIP A04 (the installed Legacy host assemblies are not available here)' }
Check 'A05 the class name written to the log is letters / digits / underscore only, otherwise "other"' (((Info 'SafeName' @(, $tOne)) -eq 'OneLeverCab') -and ((Info 'SafeName' @(, [string])) -eq 'String') -and ((Info 'SafeName' @(, $null)) -eq 'other'))

$h = NewIn; $h.Input.CabName = 'OneLeverCab'; $h.Input.HandleTypeValue = 1; $h.Input.BrakeKindValue = 1; $h.Run(3, 16)
$f1 = Ev $h 'TEL_HANDLE_FIRST'
Check 'A06 one-lever Ecb: one HANDLE_FIRST line with cab, htype=one-lever, brake=Ecb, the layout and the positions' (($f1.Count -eq 1) -and ($f1[0] -eq 'TEL_HANDLE_FIRST gen=0 cab=OneLeverCab htype=one-lever brake=Ecb combo=supported powN=5 brkN=8 ebN=9 hold=0 b67=-1 rev=1 pow=0 brk=0'))
$h = NewIn; $h.Input.CabName = 'TwoLeverCab'; $h.Input.HandleTypeValue = 2; $h.Input.BrakeKindValue = 2; $h.Input.Rev = -1; $h.Input.Pow = 4; $h.Input.Brk = 2; $h.Input.PowN = 14; $h.Input.BrkN = 7; $h.Input.EbN = 8; $h.Run(3, 16)
$f2 = Ev $h 'TEL_HANDLE_FIRST'
Check 'A07 two-lever Smee: htype=two-lever, brake=Smee, power / brake / reverser positions and the layout are logged as read' (($f2.Count -eq 1) -and ($f2[0] -eq 'TEL_HANDLE_FIRST gen=0 cab=TwoLeverCab htype=two-lever brake=Smee combo=supported powN=14 brkN=7 ebN=8 hold=0 b67=-1 rev=-1 pow=4 brk=2'))
$h = NewIn; $h.Input.CabName = 'UnrelatedCab'; $h.Input.HandleTypeValue = 0; $h.Input.BrakeKindValue = 0; $h.Run(3, 16)
$f3 = Ev $h 'TEL_HANDLE_FIRST'
Check 'A08 unknown cab and unknown brake: htype=unknown, brake=unknown, combo=unknown (diagnosable, nothing derived)' (($f3.Count -eq 1) -and ($f3[0] -match ' htype=unknown brake=unknown combo=unknown '))
$h = NewIn; $h.Input.HandleTypeValue = 2; $h.Input.CabName = 'TwoLeverCab'; $h.Input.BrakeKindValue = 3; $h.Run(3, 16)
Check 'A09 two-lever Cl is observed as brake=Cl (supported combination)' ((Ev $h 'TEL_HANDLE_FIRST')[0] -match ' htype=two-lever brake=Cl combo=supported ')
$h = NewIn; $h.Input.HandleTypeValue = 1; $h.Input.BrakeKindValue = 3; $h.Run(3, 16)
Check 'A10 one-lever Cl is only OBSERVED as combo=unexpected: no special display, no special scoring' ((Ev $h 'TEL_HANDLE_FIRST')[0] -match ' htype=one-lever brake=Cl combo=unexpected ')
Check 'A11 combination table: one-lever Cl unexpected; every other known pair supported; anything unknown is unknown' (((Info 'Combo' @(1, 3)) -eq 'unexpected') -and ((Info 'Combo' @(2, 3)) -eq 'supported') -and ((Info 'Combo' @(1, 1)) -eq 'supported') -and ((Info 'Combo' @(2, 2)) -eq 'supported') -and ((Info 'Combo' @(0, 1)) -eq 'unknown') -and ((Info 'Combo' @(1, 0)) -eq 'unknown'))

# the emergency brake notch is what the host says; it is never derived from the brake notch count
$h = NewIn; $h.Input.BrkN = 8; $h.Input.EbN = $null; $h.Run(3, 16)
$e1 = (Ev $h 'TEL_HANDLE_FIRST')[0]
Check 'A12 EmergencyBrakeNotch unreadable: ebN=na (NOT brkN+1 = 9)' (($e1 -match ' brkN=8 ebN=na ') -and ($e1 -notmatch 'ebN=9'))
$h = NewIn; $h.Input.BrkN = 8; $h.Input.EbN = 10; $h.Run(3, 16)
Check 'A13 EmergencyBrakeNotch 10 with brake notch count 8: ebN=10 as the host reports it (no inference from the count)' ((Ev $h 'TEL_HANDLE_FIRST')[0] -match ' brkN=8 ebN=10 ')
$probeCode = Code ([IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyInputProbe.cs')))
$extCode = Code ([IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyTelemetryExtension.cs')))
Check 'A14 no source line derives an emergency notch from the notch count' (($probeCode + $extCode) -notmatch 'BrakeNotchCount\s*\+|BrkN\s*\+|BrakeNotches\s*\+')

# ---------------------------------------------------------------------------------------------------------------------------------------------
# B - INative reachable / not reachable
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; $h.Run(3, 16)
$cap = Ev $h 'TEL_INPUT_CAPABILITY'
Check 'B01 INative reachable: one CAPABILITY line says native=1 handles=1 spec=1 nativeState=1 store=1' (($cap.Count -eq 1) -and ($cap[0] -eq 'TEL_INPUT_CAPABILITY gen=0 native=1 handles=1 spec=1 nativeState=1 store=1'))
Check 'B02 SPEC_FIRST carries the native VehicleSpec values (powN, brkN, b67)' ((Ev $h 'TEL_SPEC_FIRST')[0] -eq 'TEL_SPEC_FIRST gen=0 powN=5 brkN=8 b67=-1')
$pf = Ev $h 'TEL_PRESSURE_FIRST'
Check 'B03 PRESSURE_FIRST src=native carries the single BcPressure / BpPressure values as read (no unit conversion)' (($pf | Where-Object { $_ -eq 'TEL_PRESSURE_FIRST gen=0 src=native bc=0 bp=490' }).Count -eq 1)
$h = NewIn; $h.Input.NativeReach = $false; $h.Run(100, 16)
$cap = Ev $h 'TEL_INPUT_CAPABILITY'; $un = Ev $h 'TEL_INPUT_UNAVAILABLE'
Check 'B04 INative not reachable: CAPABILITY native=0 spec=0 nativeState=0; handles and store still observed' (($cap[0] -eq 'TEL_INPUT_CAPABILITY gen=0 native=0 handles=1 spec=0 nativeState=0 store=1') -and ((Ev $h 'TEL_HANDLE_FIRST').Count -eq 1))
Check 'B05 INative not reachable: each missing native group is reported ONCE with the fixed reason native-null (100 Ticks)' (($un.Count -eq 2) -and (@($un | Where-Object { $_ -eq 'TEL_INPUT_UNAVAILABLE gen=0 group=spec reason=native-null' }).Count -eq 1) -and (@($un | Where-Object { $_ -eq 'TEL_INPUT_UNAVAILABLE gen=0 group=nativeState reason=native-null' }).Count -eq 1))
Check 'B06 INative not reachable: no SPEC_FIRST and no native PRESSURE line' (((Ev $h 'TEL_SPEC_FIRST').Count -eq 0) -and (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=native' }).Count -eq 0))
$h = NewIn; $h.Input.NativeReach = $false; $h.Run(100, 16)
$hr = NewIn; $hr.Input.NativeReach = $true; $hr.Run(100, 16)
Check 'B07 INative reachable or not, the telemetry stream is the same (the observation is not part of it)' ((($h.Sink.Sent -join "`n") -eq ($hr.Sink.Sent -join "`n")))
$adapter = $null
try { $adapter = $fixAsm.GetType('TsScoringLegacyTelemetryTests.AdapterProbe').GetMethod('Run').Invoke($null, @()) } catch { $adapter = $null }
if ($adapter -ne $null) {
    Check 'B08 the REAL adapter with nothing attached never throws: NativeReachable False and fixed reasons (scenario-null / native-null)' (($adapter[0] -eq 'False') -and ($adapter[1] -eq 'False:scenario-null') -and ($adapter[2] -eq 'False:native-null') -and ($adapter[3] -eq 'False:native-null') -and ($adapter[4] -eq 'False:scenario-null'))
} else { 'SKIP B08 (the installed Legacy host assemblies could not be loaded here)' }
Check 'B09 the native object is reached only through the public PluginBase.Native property (AttachNative(Native)); no reflection, hook, DllImport, unsafe or private member in the adapter or the probe' (($extCode -match 'api\.AttachNative\(Native\)') -and (($extCode + $probeCode) -notmatch 'BindingFlags|DllImport|\bunsafe\b|Harmony|\.GetField\(|\.GetProperty\(|\.GetMethod\(|\.Invoke\(|Marshal\.'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# C - StateStore arrays: 0, 1, many elements; none chosen, none reduced
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; $h.Input.StoreBc = (New-Object 'double[]' 0); $h.Input.StoreBp = (New-Object 'double[]' 0); $h.Run(50, 16)
$st = @((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=store' })
Check 'C01 StateStore arrays of 0 elements: observed as bcN=0 bpN=0 with an empty head (no exception, no unavailable)' (($st.Count -eq 1) -and ($st[0] -eq 'TEL_PRESSURE_FIRST gen=0 src=store bcN=0 bcHead=- bpN=0 bpHead=-') -and ((Ev $h 'TEL_INPUT_UNAVAILABLE').Count -eq 0))
$h = NewIn; $h.Input.StoreBc = [double[]]@(150.5); $h.Input.StoreBp = [double[]]@(490.0); $h.Run(5, 16)
$st = @((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=store' })
Check 'C02 StateStore arrays of 1 element: bcN=1 with that value, bpN=1 with that value' (($st.Count -eq 1) -and ($st[0] -eq 'TEL_PRESSURE_FIRST gen=0 src=store bcN=1 bcHead=150.5 bpN=1 bpHead=490'))
$h = NewIn; $h.Input.StoreBc = [double[]]@(1, 2, 3, 4, 5, 6, 7, 8); $h.Input.StoreBp = [double[]]@(10, 20, 30, 40, 50, 60, 70, 80); $h.Run(5, 16)
$st = @((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=store' })
Check 'C03 StateStore arrays of 8 elements: the real length and ONLY the first 3 values; no element is chosen, no single bc= / bp= value is made from them' (($st.Count -eq 1) -and ($st[0] -eq 'TEL_PRESSURE_FIRST gen=0 src=store bcN=8 bcHead=1_2_3 bpN=8 bpHead=10_20_30') -and ($st[0] -notmatch ' bc=| bp='))
$h = NewIn; $h.Input.StoreBc = $null; $h.Input.StoreBp = [double[]]@(490.0); $h.Run(5, 16)
Check 'C04 only one array missing: that array is bcN=na bcHead=na, the other is still observed' (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -eq 'TEL_PRESSURE_FIRST gen=0 src=store bcN=na bcHead=na bpN=1 bpHead=490' }).Count -eq 1)
$h = NewIn; $h.Input.StoreBc = $null; $h.Input.StoreBp = $null; $h.Run(200, 16)
$un = @((Ev $h 'TEL_INPUT_UNAVAILABLE') | Where-Object { $_ -match 'group=store' })
Check 'C05 both arrays missing: unavailable ONCE with the fixed reason array-null over 200 Ticks; no store PRESSURE line' (($un.Count -eq 1) -and ($un[0] -eq 'TEL_INPUT_UNAVAILABLE gen=0 group=store reason=array-null') -and (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=store' }).Count -eq 0))
$h = NewIn; $h.Input.StoreBc = [double[]]@(1, 2); $h.Input.StoreBp = [double[]]@(5, 6); $h.Run(3, 16); $h.Input.StoreBc = [double[]]@(1, 2, 3); $h.Run(3, 16)
Check 'C06 a change of the array LENGTH is a semantic change (one PRESSURE_CHANGE line), the same values again are not' ((@((Ev $h 'TEL_PRESSURE_CHANGE') | Where-Object { $_ -match 'src=store bcN=3 ' }).Count -eq 1) -and ((Ev $h 'TEL_PRESSURE_CHANGE').Count -eq 1))
$nan = [double]::NaN; $inf = [double]::PositiveInfinity; $ninf = [double]::NegativeInfinity
$h = NewIn; $h.Input.StoreBc = [double[]]@($nan, $inf, 5.0); $h.Input.StoreBp = [double[]]@($ninf, 6.0, $nan); $h.Run(3, 16)
Check 'C07 NaN / Infinity in the StateStore head are never written as numbers: they are x, finite values stay' (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -eq 'TEL_PRESSURE_FIRST gen=0 src=store bcN=3 bcHead=x_x_5 bpN=3 bpHead=x_6_x' }).Count -eq 1)
$h = NewIn; $h.Input.NativeBc = $nan; $h.Input.NativeBp = 490.0; $h.Run(3, 16)
Check 'C08 native BcPressure NaN with a finite BpPressure: bc=x bp=490 (the NaN is not a value)' (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -eq 'TEL_PRESSURE_FIRST gen=0 src=native bc=x bp=490' }).Count -eq 1)
$h = NewIn; $h.Input.NativeBc = $nan; $h.Input.NativeBp = $inf; $h.Run(100, 16)
$un = @((Ev $h 'TEL_INPUT_UNAVAILABLE') | Where-Object { $_ -match 'group=nativeState' })
Check 'C09 native pressures both NaN / Infinity: not available (reason nonfinite, once); no native PRESSURE_FIRST' (($un.Count -eq 1) -and ($un[0] -eq 'TEL_INPUT_UNAVAILABLE gen=0 group=nativeState reason=nonfinite') -and (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=native' }).Count -eq 0))
Check 'C10 head text: finite as is, non-finite x, empty -, null na; at most 3 values' (([TsScoringLegacyTelemetryTests.InputInfo]::Head([double[]]@(1, 2, 3, 4)) -eq '1_2_3') -and ([TsScoringLegacyTelemetryTests.InputInfo]::Head((New-Object 'double[]' 0)) -eq '-') -and ([TsScoringLegacyTelemetryTests.InputInfo]::Head($null) -eq 'na') -and ([TsScoringLegacyTelemetryTests.InputInfo]::Head([double[]]@($nan, 7)) -eq 'x_7'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# D - when a line is written: first success, semantic change only, never per Tick
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; $h.Run(1000, 16)
$ie = InputEvents $h
Check 'D01 1000 Ticks of constant values: exactly 5 input lines (capability, handle first, spec first, native + store pressure first) - nothing per Tick' ($ie.Count -eq 5)
$h = NewIn; $h.Run(5, 16); $h.Input.Brk = 1; $h.Run(20, 16); $h.Input.Brk = 2; $h.Run(20, 16)
$hc = Ev $h 'TEL_HANDLE_CHANGE'
Check 'D02 handle moves: one HANDLE_CHANGE per new position (brk 1, brk 2), none for the same position repeated' (($hc.Count -eq 2) -and ($hc[0] -eq 'TEL_HANDLE_CHANGE gen=0 what=position rev=1 pow=0 brk=1') -and ($hc[1] -eq 'TEL_HANDLE_CHANGE gen=0 what=position rev=1 pow=0 brk=2'))
$h = NewIn; $h.Run(5, 16); $h.Input.BrkN = 9; $h.Input.EbN = 10; $h.Run(20, 16)
$hc = Ev $h 'TEL_HANDLE_CHANGE'
Check 'D03 a change of the notch layout is one HANDLE_CHANGE what=layout line with the new layout' (($hc.Count -eq 1) -and ($hc[0] -match '^TEL_HANDLE_CHANGE gen=0 what=layout cab=OneLeverCab .* brkN=9 ebN=10 '))
$h = NewIn; $h.Run(3, 16)
foreach ($v in @(0.2, 0.6, 100.0, 120.0, 50.0, 0.0)) { $h.Input.NativeBc = $v; $h.Run(2, 16) }
$pc = @((Ev $h 'TEL_PRESSURE_CHANGE') | Where-Object { $_ -match 'src=native' })
Check 'D04 native pressure: a change line only when it moved by about half (0.2 no, 0.6 yes, 100 yes, 120 no, 50 yes, 0 yes) = 4 lines' (($pc.Count -eq 4) -and ($pc[0] -match 'bc=0\.6 ') -and ($pc[1] -match 'bc=100 ') -and ($pc[2] -match 'bc=50 ') -and ($pc[3] -match 'bc=0 '))
$h = NewIn; $h.Run(3, 16)
for ($i = 1; $i -le 300; $i++) { $h.Input.NativeBc = [double]$i; $h.Run(1, 16) }
for ($i = 299; $i -ge 0; $i--) { $h.Input.NativeBc = [double]$i; $h.Run(1, 16) }
$pcr = @((Ev $h 'TEL_PRESSURE_CHANGE') | Where-Object { $_ -match 'src=native' })
Check 'D05 a 600-Tick pressure ramp up and down writes a handful of lines (not one per Tick) and never more than the cap' (($pcr.Count -ge 8) -and ($pcr.Count -le [int](Info 'get_CapPressureChange' @())))
Check 'D06 the pressure change rule is symmetric and unit free (halving counts like doubling; NaN transitions count; two NaN do not)' ((Info 'Moved' @(100.0, 50.0)) -and (Info 'Moved' @(50.0, 100.0)) -and (-not (Info 'Moved' @(100.0, 120.0))) -and (Info 'Moved' @(1.0, $nan)) -and (-not (Info 'Moved' @($nan, $nan))))
$h = NewIn; $h.Run(5, 16); $h.Input.NativeFail = $true; $h.Input.NativeReason = 'state-null'; $h.Run(200, 16)
$ua = @((Ev $h 'TEL_INPUT_UNAVAILABLE') | Where-Object { $_ -match 'group=nativeState' })
Check 'D07 a group that fails later is reported once with its fixed reason (state-null), not per Tick; the earlier first line stays' (($ua.Count -eq 1) -and ($ua[0] -eq 'TEL_INPUT_UNAVAILABLE gen=0 group=nativeState reason=state-null') -and (@((Ev $h 'TEL_PRESSURE_FIRST') | Where-Object { $_ -match 'src=native' }).Count -eq 1))
$h = NewIn; $h.Input.HandlesFail = $true; $h.Input.HandlesReason = 'cab-null'; $h.Run(200, 16)
Check 'D08 an unreadable group is reported once by the observation (not per Tick) and the rest of the observation goes on; since Phase LI1 the telemetry needs the handles EVERY Tick, so the host is asked once per Tick (200 calls in 200 Ticks, never more) and the observation shares that read' (($h.Input.CallCount('TryHandles') -eq 200) -and ((Ev $h 'TEL_INPUT_UNAVAILABLE').Count -eq 1) -and ((Ev $h 'TEL_INPUT_UNAVAILABLE')[0] -eq 'TEL_INPUT_UNAVAILABLE gen=0 group=handles reason=cab-null') -and ((Ev $h 'TEL_PRESSURE_FIRST').Count -eq 2))
$h = NewIn; $h.Input.HandlesFail = $true; $h.Run(40, 16); $h.Input.HandlesFail = $false; $h.Run(60, 16)
$idxU = $h.Diag.Events.FindIndex([Predicate[string]]{ param($s) $s.StartsWith('TEL_INPUT_UNAVAILABLE') }); $idxF = $h.Diag.Events.FindIndex([Predicate[string]]{ param($s) $s.StartsWith('TEL_HANDLE_FIRST') })
Check 'D09 a group that becomes readable later gets its HANDLE_FIRST then (after the unavailable line)' (($idxU -ge 0) -and ($idxF -gt $idxU) -and ((Ev $h 'TEL_HANDLE_FIRST').Count -eq 1))
$h = NewIn; $h.Input.HandlesThrow = $true; $h.Input.SpecThrow = $true; $h.Input.NativeThrow = $true; $h.Input.StoreThrow = $true; $h.Run(100, 16)
$ue = Ev $h 'TEL_INPUT_UNAVAILABLE'
Check 'D10 every group throwing: four unavailable lines with reason read-exception (no exception text), telemetry lines still sent for every Tick, none skipped' (($ue.Count -eq 4) -and (@($ue | Where-Object { $_ -match 'reason=read-exception$' }).Count -eq 4) -and ($h.LinesSent -eq 100) -and ($h.LinesSkipped -eq 0))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# E - line limits and scenario generations
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; $h.Run(2, 16)
for ($i = 1; $i -le 200; $i++) { $h.Input.Brk = $i % 9; $h.Run(1, 16) }
$h.Closed()
$hc = Ev $h 'TEL_HANDLE_CHANGE'; $sm = Ev $h 'TEL_INPUT_SUMMARY'
$capHc = [int](Info 'get_CapHandleChange' @())
Check 'E01 200 handle moves write exactly the per-kind cap of HANDLE_CHANGE lines; the rest is counted in the summary' (($hc.Count -eq $capHc) -and ($sm.Count -eq 1) -and ((Kv $sm[0] 'handleChanges') -eq '200') -and ((Kv $sm[0] 'suppressed') -eq [string](200 - $capHc)))
Check 'E02 the whole generation never exceeds the total line limit, the summary included' ((InputEvents $h).Count -le [int](Info 'get_MaxLines' @()))
Check 'E03 the summary line states ticks, lines and suppressed as numbers' (($sm[0] -match '^TEL_INPUT_SUMMARY gen=0 ticks=202 handleChanges=200 pressureChanges=0 suppressed=\d+ lines=\d+$'))
$h = NewIn; $h.Run(10, 16); $h.Closed(); $h.Created(); $h.Seed = $h.Seed + 777; $h.Run(10, 16)
$g2 = Ev $h 'TEL_INPUT_CAPABILITY'
Check 'E04 a new scenario generation resets the observation: a second CAPABILITY, HANDLE_FIRST, SPEC_FIRST and two PRESSURE_FIRST with the new generation id' (($g2.Count -eq 2) -and ($g2[0] -match 'gen=0 ') -and ($g2[1] -match 'gen=777 ') -and ((Ev $h 'TEL_HANDLE_FIRST').Count -eq 2) -and ((Ev $h 'TEL_SPEC_FIRST').Count -eq 2) -and ((Ev $h 'TEL_PRESSURE_FIRST').Count -eq 4))
$h.Dispose()
$smAll = Ev $h 'TEL_INPUT_SUMMARY'
Check 'E05 each generation ends with exactly one summary (close, then dispose): 2 summaries for 2 generations' (($smAll.Count -eq 2) -and ($smAll[0] -match 'gen=0 ') -and ($smAll[1] -match 'gen=777 '))
$h = NewIn; $h.Run(2, 16)
for ($i = 1; $i -le 100; $i++) { $h.Input.Brk = $i % 9; $h.Run(1, 16) }
$h.Closed(); $h.Created(); $h.Run(2, 16)
for ($i = 1; $i -le 100; $i++) { $h.Input.Brk = ($i + 3) % 9; $h.Run(1, 16) }
Check 'E06 the caps are per generation: the second generation writes its own HANDLE_CHANGE lines again (2 x cap)' ((Ev $h 'TEL_HANDLE_CHANGE').Count -eq (2 * $capHc))
$h = NewIn; $h.Run(5, 16); $h.Dispose()
$smD = Ev $h 'TEL_INPUT_SUMMARY'
Check 'E07 dispose ends the generation with its summary; nothing more is written after it' (($smD.Count -eq 1) -and ($h.Diag.Events[$h.Diag.Events.Count - 1].StartsWith('TEL_FINAL') -or $h.Diag.Events[$h.Diag.Events.Count - 1].StartsWith('TEL_DISPOSE')))
$h = NewIn; $h.Run(5, 16); $h.Input.Brk = 3; $h.Input.NativeBc = 5.0; $h.Run(3, 16); $h.Created(); $h.Run(3, 16)
$before = (InputEvents $h).Count
$h.Run(3, 16)
Check 'E08 a Created event without a new scenario object still ends the generation (a new CAPABILITY follows) but identical values add no more lines afterwards' (((Ev $h 'TEL_INPUT_CAPABILITY').Count -eq 2) -and ((InputEvents $h).Count -eq $before))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# F - threads and pause
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; $h.Run(10, 16)
$tickThread = [Threading.Thread]::CurrentThread.ManagedThreadId
$inCalls = $h.Input.TotalCalls(); $apiCalls = ($h.Api.Calls.Values | Measure-Object -Sum).Sum
$hbThread = $h.HeartbeatOnOtherThread(2000)
Check 'F01 the heartbeat thread never touches the Legacy API or the input API (call counts unchanged after 2000 heartbeat calls from a second thread)' (($hbThread -ne $tickThread) -and ($h.Input.TotalCalls() -eq $inCalls) -and ((($h.Api.Calls.Values | Measure-Object -Sum).Sum) -eq $apiCalls))
Check 'F02 every input API call came from the Tick thread only' (($h.Input.Threads.Count -eq 1) -and ($h.Input.Threads.Contains($tickThread)))
$h = NewIn; $h.Run(5, 16); $inCalls = $h.Input.TotalCalls(); $h.Now += 5000; $null = $h.Heartbeat(); $h.Now += 5000; $null = $h.Heartbeat()
Check 'F03 pause (no Tick): the heartbeat reports PAUSED and the input API is not called at all' (($h.Heartbeat() -eq 'STATUS:LOADED:PAUSED') -and ($h.Input.TotalCalls() -eq $inCalls))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# G - the telemetry stream, AVAIL and the gradient contract of Phase L3 are unchanged
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Scripted($hh) {
    $hh.Api.GradientRatio = 0.0125; $hh.Api.BrakeKind = 3; $hh.Api.FreshWrapperEachCall = $true
    $hh.Run(30, 16)
    $hh.Api.GradientRatio = 0.02; $hh.Api.Holding = $true
    $hh.Run(30, 16)
    $hh.Closed(); $hh.Created(); $hh.Run(20, 16); $hh.Dispose()
}
$wo = NewH $false; Scripted $wo
$wi = NewIn
$wi.Input.HandleTypeValue = 1; $wi.Input.BrakeKindValue = 3; $wi.Input.NativeBc = 77.0     # one-lever Cl, the unexpected combination, with moving values
Scripted $wi
$wn = New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList @($true, $false)      # the same input values, but NO diagnostic: the observation is not wired
$wn.Input.HandleTypeValue = 1; $wn.Input.BrakeKindValue = 3; $wn.Input.NativeBc = 77.0
Scripted $wn
# (Phase LI1 sends the handle group and the pressures, so a session with the input surface is no longer identical to one without it; what stays true is that the OBSERVATION adds nothing)
Check 'G01 the datagrams of a session WITH the observation are byte-identical to one with the same input values but WITHOUT the observation (60 Ticks, a gradient change, a reload, one-lever Cl)' (($wi.Sink.Sent.Count -gt 50) -and (($wi.Sink.Sent -join "`n") -eq ($wn.Sink.Sent -join "`n")))
$lines = @($wi.Sink.Lines())
$linesOld = @($wo.Sink.Lines())
Check 'G02 the sender WITHOUT an input surface (Phase L3) writes no handle / pressure key and no handle / bcp / bpp token; with one, a one-lever Cl (outside the supported set) still writes no handle group but the pressures' ((@($linesOld | Where-Object { $_ -match $NEVERKEY }).Count -eq 0) -and (@($linesOld | Where-Object { $a = $_; (@($NEVERTOK | Where-Object { $a -match ('[:+]' + $_ + '([+,]|$)') })).Count -gt 0 }).Count -eq 0) -and (@($lines | Where-Object { $_ -match '(^|,)(REV|POW|BRK|ALLTXT|HTYPE):' }).Count -eq 0) -and (@($lines | Where-Object { $_ -notmatch '(^|,)BCP:' }).Count -eq 0))
Check 'G03 AVAIL without an input surface is the same 14 tokens as before (calcg from the second line); with the input surface and a one-lever Cl it is those 14 plus bcp and bpp (no handle)' (([regex]::Match($linesOld[1], 'AVAIL:1:([^,]*)').Groups[1].Value -eq 'brake_cab+brake_type+calcg+door+grad+loc+maplimit+meta+prates+siglimit+siglimit_ahead+speed+station+time') -and ([regex]::Match($lines[1], 'AVAIL:1:([^,]*)').Groups[1].Value -eq 'bcp+bpp+brake_cab+brake_type+calcg+door+grad+loc+maplimit+meta+prates+siglimit+siglimit_ahead+speed+station+time'))
Check 'G04 the gradient stays the x 1000 value (0.0125 -> GRADIENT:12.5, 0.02 -> GRADIENT:20) and BTYPE:Cl is the only brake word on the line' (($lines[0] -match 'GRADIENT:12\.5(,|$)') -and ($lines[40] -match 'GRADIENT:20(,|$)') -and ($lines[0] -match 'BTYPE:Cl'))
Check 'G05 the existing gradient diagnostic is unchanged: TEL_GRADIENT_FIRST once per scenario generation (2 generations -> 2 lines)' ((Ev $wi 'TEL_GRADIENT_FIRST').Count -eq 2)
Check 'G06 a session built the old way (no input wired) writes no input line at all' ((InputEvents $wo).Count -eq 0)

# ---------------------------------------------------------------------------------------------------------------------------------------------
# H - what the log may contain, the real file log, the version, the scope of the change
# ---------------------------------------------------------------------------------------------------------------------------------------------
$all = @()
foreach ($mk in @(
    { $x = NewIn; $x.Run(20, 16); $x },
    { $x = NewIn; $x.Input.NativeReach = $false; $x.Input.StoreBc = $null; $x.Input.StoreBp = $null; $x.Input.HandlesThrow = $true; $x.Run(100, 16); $x },
    { $x = NewIn; $x.Input.StoreBc = [double[]]@($nan, 1.5e-5, -3); $x.Input.StoreBp = (New-Object 'double[]' 0); $x.Input.CabName = 'UnrelatedCab'; $x.Run(20, 16); $x.Dispose(); $x }
)) { $all += (InputEvents (& $mk)) }
$bad = @($all | Where-Object { $_ -notmatch '^TEL_[A-Z_]+ gen=\d+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)+$' })
Check ('H01 every input line has the fixed shape NAME gen=N key=value ... with letters, digits, _ . - only (' + $all.Count + ' lines checked): no path, no free text, no exception text') ($bad.Count -eq 0)
$hf = NewIn; $hf.Api.Meta = @('SecretTitle', 'SecretRoute', 'SecretVehicle', 'SecretAuthor', 'SecretComment'); $fileLog = Join-Path $testDir 'li0-diag.log'; $hf.UseFileDiag($fileLog); $hf.Run(50, 16); $hf.Dispose()
$fl = @([IO.File]::ReadAllLines($fileLog))
$fi = @($fl | Where-Object { ($_ -match ' TEL_(INPUT|HANDLE|SPEC|PRESSURE)_') -and ($_ -notmatch ' TEL_(HANDLE_SEND|HANDLE_DROP|PRESSURE_SEND|PRESSURE_DROP|INPUT_PUBLISH) ') })     # (the Phase LI1 lines are tested by Test-LegacyInputLI1.ps1)
Check 'H02 the real file log carries the input lines in the TEL_ log format (HH:mm:ss.fff P= I= NAME gen=...), no scenario text, no path' (($fi.Count -eq 5 + 1) -and (@($fi | Where-Object { $_ -notmatch '^\d\d:\d\d:\d\d\.\d{3} P=\d+ I=\d+ TEL_[A-Z_]+ gen=\d+ ' }).Count -eq 0) -and (($fl -join "`n") -notmatch 'Secret') -and (($fi -join "`n") -notmatch '[A-Za-z]:\\'))
Check 'H03 the DLL is 0.2.0.0 (assembly and file version; Phase LI1 builds on the LI0 observation, which this test still covers), product TS Scoring, provider Coruge-to' (([TsScoringLegacyTelemetryTests.DiagInfo]::Version -eq '0.2.0.0') -and ((Get-Item $dllPath).VersionInfo.FileVersion -eq '0.2.0.0') -and ((Get-Item $dllPath).VersionInfo.ProductName -eq 'TS Scoring') -and ((Get-Item $dllPath).VersionInfo.CompanyName -eq 'Coruge-to'))
Check 'H04 the probe file names no AtsEx / BveTypes type (host independent); the adapter file is still the only one that does' (($probeCode -cnotmatch 'AtsEx|BveTypes') -and ($extCode -cmatch 'AtsEx\.PluginHost') -and ((Code ([IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyTelemetrySession.cs')))) -cnotmatch 'AtsEx|BveTypes'))
function RunGit([string[]]$gitArgs) { $out = & git @gitArgs 2>$null; if ($LASTEXITCODE -ne 0) { return '' }; return ($out -join "`n") }
$top = (RunGit @('-C', $Root, 'rev-parse', '--show-toplevel')).Trim() -replace '/', '\'
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', 'HEAD')) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
# (Phase LI1 builds on top of this phase. The LI0 commit is HEAD now, so the guard says what must NOT move: the observation itself and everything the observation never touched.)
$li0Frozen = @('TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputProbe.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs')
$li0Moved = @($touched | Where-Object { $_ -in $li0Frozen })
$productMoved = @($touched | Where-Object { $_ -match '^(main|hud_ui|network|scoring_logic|menu_ui|config|utils|managed_[a-z]+|telemetry_[a-z]+)\.py$|/Caller/|/Bridge/|/Handshake/Shared/|Class1\.cs$|AtsLoggerPlugin\.cs$' })
Check ('H05 scope: the observation (LegacyInputProbe.cs), the Legacy API seam (LegacyApi.cs) and the host adapter are unchanged since the LI0 commit; no production Python, HUD, Caller, Bridge, Current sender or Handshake shared file changed (' + $touched.Count + ' files touched by the working tree)') (($li0Moved.Count -eq 0) -and ($productMoved.Count -eq 0))

# ---------------------------------------------------------------------------------------------------------------------------------------------
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"LEGACY-INPUT-LI0 PASS=$pass FAIL=$fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
