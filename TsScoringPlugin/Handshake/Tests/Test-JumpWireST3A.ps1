# PHASE PID-D4JA StationIndex ST-3a - offline C# tests of the JUMP WIRE codec: Telemetry\Shared\JumpWire.cs (the twin of jump_wire.py), held to the SAME vector table
# (tests\jump_wire_vectors.json) as the Python half (tests\test_stationindex_canon_st3.py). N-20 JUMP-WIRE-VECTOR-PARITY, C# half.
#
# HOW: the host independent product sources (Telemetry\Legacy\src except the Extension and AssemblyInfo, Telemetry\Shared - which now holds JumpWire.cs - and the two Current
# files the Legacy project links) are compiled TOGETHER, IN MEMORY, by the Windows PowerShell 5.1 compiler (no msbuild, no DLL of the product is built or replaced, nothing is
# written). That is a test compile of the sources the working tree has, and it also proves that JumpWire.cs compiles next to every file it will be linked with. The script writes
# ONE work folder in %TEMP% only for the cross-language run (X) and removes it at the end; a leftover is a FAIL (CLEAN).
#   V  the table, C# half: every message / location text / format input / number vector gets the table verdict (reason word, version, kind, index, time, location bits, scope)
#   N  numbers: -0.0, the range edges, the culture independence, the splitmix64 corpus (the generator is checked against the words recorded in the table), exact round trip
#   E  equivalence with the C# readers that exist (CurrentJumpEndpoint.ValidGrammar, LegacyJumpClaim.From) on v1 input, classified by the table
#   B  boundary: JumpWire.cs is linked into NO project (ST-3a leaves both DLLs unchanged), host independent, the existing parser file is byte-identical
#   X  cross-language: Python (python -I) reads what C# wrote and C# reads what Python wrote, for the same corpus, bit for bit
# Exit codes: 0 = every check passed, 1 = a check failed, 2 = INCONCLUSIVE (the sources do not compile / the table is missing). This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $Root -Parent) -Parent
$telRoot = Join-Path $Root 'Telemetry'
$vectorPath = Join-Path $repo 'tests\jump_wire_vectors.json'
$jwPath = Join-Path $telRoot 'Shared\JumpWire.cs'
$endpointPath = Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs'
$endpointSha = '3837A409AFB136F10322DD78B8D89C4831B871AEB87824D0709594916F6FCB6D'

$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Inconclusive([string]$why) { Write-Host ('INCONCLUSIVE ' + $why); exit 2 }
function Finish() {
    Write-Host ''
    Write-Host ('RESULT PASS=' + $script:pass + ' FAIL=' + $script:fail)
    if ($script:fail -gt 0) { exit 1 }
    exit 0
}

# ---- the declared RED: the C# half does not exist yet ---------------------------------------------------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $vectorPath)) { Check 'N-20 C# half: tests\jump_wire_vectors.json exists' $false; Finish }
if (-not (Test-Path -LiteralPath $jwPath)) { Check 'N-20 C# half: Telemetry\Shared\JumpWire.cs exists (the shared JumpWire is not implemented)' $false; Finish }
$vec = Get-Content -LiteralPath $vectorPath -Raw -Encoding UTF8 | ConvertFrom-Json

# ---- the probe: public wrappers of the internal API, the corpus generators and the two existing readers -------------------------------------------------------------------
$probe = @'
using System;
using System.Globalization;
using System.Reflection;
using System.Text;
using TSScoringPlugin.DataPlane;
using TSScoringPlugin.Telemetry;
namespace St3aProbe
{
    public static class Jw
    {
        static string Bits(double d) { return BitConverter.DoubleToInt64Bits(d).ToString("X16", CultureInfo.InvariantCulture); }
        static double FromBits(string h) { return BitConverter.Int64BitsToDouble(Convert.ToInt64(h, 16)); }

        public static object[] ParseRequest(string text)
        {
            string reason; JumpWireRequest r = JumpWire.ParseRequest(text, out reason);
            if (r == null) return new object[] { reason };
            return new object[] { null, r.Version, r.Kind, r.HasStationIndex, r.StationIndex, r.TimeMs, r.HasLocation, r.HasLocation ? Bits(r.Location) : null,
                r.Scope != null, r.Scope == null ? 0 : r.Scope.ScenarioId, r.Scope == null ? null : r.Scope.ListId, r.Scope == null ? 0 : r.Scope.Count };
        }
        public static object[] ParseCompletion(string text)
        {
            string reason; JumpWireCompletion c = JumpWire.ParseCompletion(text, out reason);
            if (c == null) return new object[] { reason };
            return new object[] { null, c.Version, c.Kind, c.SelectedIndex, Bits(c.Location), c.TimeMs, c.JumpCount,
                c.Scope != null, c.Scope == null ? 0 : c.Scope.ScenarioId, c.Scope == null ? null : c.Scope.ListId, c.Scope == null ? 0 : c.Scope.Count };
        }
        public static object[] ParseLocation(string text)
        {
            double v; string reason = JumpWire.ParseLocation(text, out v);
            return new object[] { reason, reason == null ? Bits(v) : null };
        }
        public static object[] NormalizeLocation(string bitsHex)
        {
            double n; string reason = JumpWire.NormalizeLocation(FromBits(bitsHex), out n);
            return new object[] { reason, reason == null ? Bits(n) : null };
        }
        public static string Quotient(ulong mantissa, int k)
        {
            MethodInfo m = typeof(JumpWire).GetMethod("ExactQuotient", BindingFlags.NonPublic | BindingFlags.Static);
            return Bits((double)m.Invoke(null, new object[] { mantissa, k }));
        }
        public static object[] FormatLocation(string bitsHex)
        {
            string reason; string t = JumpWire.FormatLocation(FromBits(bitsHex), out reason);
            return new object[] { reason, t };
        }
        public static object[] FormatRequest(string kind, int idx, int time, bool hasScope, int scen, string list, int count, string locBits)
        {
            string reason; string t = JumpWire.FormatRequestV2(kind, idx, time, hasScope ? new JumpWireScope(scen, list, count) : null, FromBits(locBits), out reason);
            return new object[] { reason, t };
        }
        public static object[] FormatCompletion(string kind, int sel, string locBits, int time, int jump, bool hasScope, int scen, string list, int count)
        {
            string reason; string t = JumpWire.FormatCompletionV2(kind, sel, FromBits(locBits), time, jump, hasScope ? new JumpWireScope(scen, list, count) : null, out reason);
            return new object[] { reason, t };
        }
        public static object[] ValidateScope(int scen, string list, int count)
        {
            string reason; JumpWireScope s = JumpWire.ValidateScope(scen, list, count, out reason);
            return new object[] { reason, s != null };
        }
        public static string[] Reasons() { return (string[])JumpWire.Reasons.Clone(); }
        public static int Int32Max { get { return JumpWire.Int32Max; } }
        public static int MaxDigits { get { return JumpWire.MaxSignificantDigits; } }
        public static string MaxAbsBits { get { return Bits(JumpWire.LocationMaxAbs); } }
        public static string MinAbsBits { get { return Bits(JumpWire.LocationMinAbs); } }

        // ---- the corpus (splitmix64, the spec is in the table)
        static ulong state;
        static ulong Next()
        {
            unchecked
            {
                state += 0x9E3779B97F4A7C15UL;
                ulong z = state;
                z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
                z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
                return z ^ (z >> 31);
            }
        }
        public static string[] Splitmix(string seedHex, int n)
        {
            state = Convert.ToUInt64(seedHex, 16);
            string[] r = new string[n];
            for (int i = 0; i < n; i++) r[i] = Next().ToString("X16", CultureInfo.InvariantCulture);
            return r;
        }
        public static string[] FamilyA(string seedHex, int draws)
        {
            state = Convert.ToUInt64(seedHex, 16);
            System.Collections.Generic.List<string> r = new System.Collections.Generic.List<string>();
            for (int i = 0; i < draws; i++)
            {
                ulong z1 = Next(); ulong z2 = Next(); ulong z3 = Next();
                int k = (int)((z2 >> 32) % 60UL) - 29;
                ulong sign = (z3 >> 63) & 1UL;
                ulong bits = (sign << 63) | ((ulong)(k + 1023) << 52) | (z1 & ((1UL << 52) - 1UL));
                double x = BitConverter.Int64BitsToDouble((long)bits);
                if (Math.Abs(x) > 1.0e9) continue;
                r.Add(bits.ToString("X16", CultureInfo.InvariantCulture));
            }
            return r.ToArray();
        }
        public static string[] FamilyB(string seedHex, int draws)
        {
            state = Convert.ToUInt64(seedHex, 16) ^ 0x5555555555555555UL;
            string[] r = new string[draws];
            for (int i = 0; i < draws; i++)
            {
                ulong z1 = Next(); ulong z2 = Next(); ulong z3 = Next();
                int d = 1 + (int)((z1 >> 20) % 17UL);
                ulong p = 1; for (int j = 0; j < d; j++) p *= 10UL;
                ulong n = z2 % p;
                int frac = (int)((z3 >> 24) % (ulong)(d + 1));
                string s = n.ToString(CultureInfo.InvariantCulture);
                if (frac > 0)
                {
                    s = s.PadLeft(frac + 1, '0');
                    s = s.Substring(0, s.Length - frac) + "." + s.Substring(s.Length - frac);
                }
                if (((z3 >> 63) & 1UL) == 1UL) s = "-" + s;
                r[i] = s;
            }
            return r;
        }

        // ---- the readers that exist
        public static bool CurrentValidGrammar(bool station, string text)
        {
            MethodInfo m = typeof(JumpCommandValidator).GetMethod("ValidGrammar", BindingFlags.NonPublic | BindingFlags.Static);
            return (bool)m.Invoke(null, new object[] { station ? DataPlaneMessageTypes.JumpStationTime : DataPlaneMessageTypes.JumpLocationTime, text });
        }
        public static object[] LegacyClaim(bool station, string text)
        {
            LegacyJumpReceipt r = new LegacyJumpReceipt();
            r.Text = text;
            r.MessageType = station ? DataPlaneMessageTypes.JumpStationTime : DataPlaneMessageTypes.JumpLocationTime;
            LegacyJumpClaim c = LegacyJumpClaim.From(r);
            return new object[] { c.Kind == LegacyJumpKind.Station ? "STA" : (c.Kind == LegacyJumpKind.Location ? "LOC" : "NONE"), c.StaIndex, Bits(c.Location), c.TimeMs };
        }
        public static string DotNetBits(string text)
        {
            double v;
            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return "FAIL";
            return Bits(v);
        }
        public static string DotNetR(string bitsHex) { return FromBits(bitsHex).ToString("R", CultureInfo.InvariantCulture); }
    }
}
'@

$files = @()
$files += Get-ChildItem (Join-Path $telRoot 'Legacy\src') -Filter *.cs | Where-Object { $_.Name -notin @('LegacyTelemetryExtension.cs', 'AssemblyInfo.cs') } | ForEach-Object { $_.FullName }
$files += Get-ChildItem (Join-Path $telRoot 'Shared') -Filter *.cs | ForEach-Object { $_.FullName }
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs')
$texts = New-Object System.Collections.Generic.List[string]
foreach ($f in $files) { $texts.Add([IO.File]::ReadAllText($f, [Text.Encoding]::UTF8)) }
$texts.Add($probe)
Add-Type -AssemblyName Microsoft.CSharp
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.GenerateInMemory = $true
$cp.TreatWarningsAsErrors = $false
foreach ($r in @('System.dll', 'System.Core.dll')) { $cp.ReferencedAssemblies.Add($r) | Out-Null }
$compiled = $provider.CompileAssemblyFromSource($cp, [string[]]$texts.ToArray())
if ($compiled.Errors.HasErrors) {
    foreach ($e in $compiled.Errors) { if (-not $e.IsWarning) { Write-Host ('  compile error: ' + $e.ErrorNumber + ' line ' + $e.Line + ' ' + $e.ErrorText) } }
    Inconclusive 'the product sources of this phase (with JumpWire.cs) do not compile in memory'
}
$asm = $compiled.CompiledAssembly
$jw = $asm.GetType('St3aProbe.Jw')
Write-Host ('PREFLIGHT ' + $files.Count + ' sources + the probe compiled in memory (no file written)')
function J([string]$method, [object[]]$a) { $r = $jw.GetMethod($method).Invoke($null, $a); return ,$r }       # the comma keeps a one element array an array
function Prop([string]$name) { return $jw.GetProperty($name).GetValue($null) }
function HexBits([double]$d) { return ('{0:X16}' -f [BitConverter]::DoubleToInt64Bits($d)) }

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# V - the table, C# half
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Check 'V-limits the reason words, Int32 maximum, digit limit and range constants are the ones of the table' ((($vec.reasons -join ',') -ceq ((J 'Reasons' @()) -join ',')) -and ([int](Prop 'Int32Max')) -eq [int]$vec.limits.int32_max -and ([int](Prop 'MaxDigits')) -eq [int]$vec.limits.location_max_significant_digits -and ([string](Prop 'MaxAbsBits')) -ceq [string]$vec.limits.location_max_abs_bits -and ([string](Prop 'MinAbsBits')) -ceq [string]$vec.limits.location_min_abs_bits)

function ScopeEq($r, [int]$base, $f) {
    # $r = the probe result; $base = the index of the 'has scope' flag
    if ($null -eq $f.scenario_id) { return (-not [bool]$r[$base]) }
    return ([bool]$r[$base] -and ([int]$r[$base + 1] -eq [int]$f.scenario_id) -and ([string]$r[$base + 2] -ceq [string]$f.list_id) -and ([int]$r[$base + 3] -eq [int]$f.count))
}
$badReq = @(); $badCmp = @(); $nReq = 0; $nCmp = 0; $badCanon = @()
foreach ($v in $vec.parse) {
    if ($v.dir -eq 'request') {
        $nReq++
        $r = J 'ParseRequest' @([string]$v.raw)
        $ok = $false
        if ($v.valid) {
            $f = $v.fields
            $ok = ($null -eq $r[0]) -and ([int]$r[1] -eq [int]$v.version) -and ([string]$r[2] -ceq [string]$v.kind) -and ([int]$r[5] -eq [int]$f.time_ms)
            if ($ok) { if ($null -eq $f.station_index) { $ok = (-not [bool]$r[3]) } else { $ok = ([bool]$r[3] -and [int]$r[4] -eq [int]$f.station_index) } }
            if ($ok) { if ($null -eq $f.location_bits) { $ok = (-not [bool]$r[6]) } else { $ok = ([bool]$r[6] -and [string]$r[7] -ceq [string]$f.location_bits) } }
            if ($ok) { $ok = ScopeEq $r 8 $f }
            if ($ok -and $null -ne $v.canonical) {
                $loc = $(if ($r[6]) { [string]$r[7] } else { '0000000000000000' })
                $c = J 'FormatRequest' @([string]$r[2], [int]$r[4], [int]$r[5], [bool]$r[8], [int]$r[9], [string]$r[10], [int]$r[11], $loc)
                if (([string]$c[1]) -cne [string]$v.canonical) { $badCanon += $v.id }
            }
        } else {
            $ok = ($r.Count -eq 1) -and ([string]$r[0] -ceq [string]$v.reason)
        }
        if (-not $ok) { $badReq += $v.id }
    } else {
        $nCmp++
        $r = J 'ParseCompletion' @([string]$v.raw)
        $ok = $false
        if ($v.valid) {
            $f = $v.fields
            $ok = ($null -eq $r[0]) -and ([int]$r[1] -eq [int]$v.version) -and ([string]$r[2] -ceq [string]$v.kind) -and ([int]$r[3] -eq [int]$f.selected_idx) -and ([string]$r[4] -ceq [string]$f.location_bits) -and ([int]$r[5] -eq [int]$f.time_ms) -and ([int]$r[6] -eq [int]$f.jump_count)
            if ($ok) { $ok = ScopeEq $r 7 $f }
            if ($ok -and $null -ne $v.canonical) {
                $c = J 'FormatCompletion' @([string]$r[2], [int]$r[3], [string]$r[4], [int]$r[5], [int]$r[6], [bool]$r[7], [int]$r[8], [string]$r[9], [int]$r[10])
                if (([string]$c[1]) -cne [string]$v.canonical) { $badCanon += $v.id }
            }
        } else {
            $ok = ($r.Count -eq 1) -and ([string]$r[0] -ceq [string]$v.reason)
        }
        if (-not $ok) { $badCmp += $v.id }
    }
}
Check ('V-req every request vector gets the table verdict (' + $nReq + ' vectors)' + $(if ($badReq.Count) { ' - wrong: ' + (($badReq | Select-Object -First 8) -join ',') } else { '' })) (($nReq -gt 100) -and ($badReq.Count -eq 0))
Check ('V-cmp every completion vector gets the table verdict (' + $nCmp + ' vectors)' + $(if ($badCmp.Count) { ' - wrong: ' + (($badCmp | Select-Object -First 8) -join ',') } else { '' })) (($nCmp -gt 50) -and ($badCmp.Count -eq 0))
Check ('V-canon every valid v2 vector is written back as its canonical text, byte for byte' + $(if ($badCanon.Count) { ' - wrong: ' + (($badCanon | Select-Object -First 8) -join ',') } else { '' })) ($badCanon.Count -eq 0)

$badLoc = @()
foreach ($v in $vec.locations) {
    $r = J 'ParseLocation' @([string]$v.text)
    if ($v.valid) { if (-not (($null -eq $r[0]) -and ([string]$r[1] -ceq [string]$v.bits))) { $badLoc += $v.id } }
    else { if (-not (([string]$r[0] -ceq [string]$v.reason) -and ($null -eq $r[1]))) { $badLoc += $v.id } }
}
Check ('V-loc every location text gets the table verdict and the correctly rounded bits (' + @($vec.locations).Count + ' texts)' + $(if ($badLoc.Count) { ' - wrong: ' + (($badLoc | Select-Object -First 8) -join ',') } else { '' })) ($badLoc.Count -eq 0)

$badFmt = @(); $nFmt = 0
foreach ($v in $vec.format) {
    if ($v.note -ceq 'int32_unrepresentable') { continue }     # a C# int can not hold the input (the Python half checks it)
    $nFmt++
    $i = $v.input
    if ($v.dir -eq 'request') {
        $r = J 'FormatRequest' @([string]$i.kind, [int]$i.station_index, [int]$i.time_ms, [bool]($null -ne $i.scope), $(if ($i.scope) { [int]$i.scope.scenario_id } else { 0 }), $(if ($i.scope) { [string]$i.scope.list_id } else { $null }), $(if ($i.scope) { [int]$i.scope.count } else { 0 }), [string]$i.location_bits)
    } else {
        $r = J 'FormatCompletion' @([string]$i.kind, [int]$i.selected_idx, [string]$i.location_bits, [int]$i.time_ms, [int]$i.jump_count, [bool]($null -ne $i.scope), $(if ($i.scope) { [int]$i.scope.scenario_id } else { 0 }), $(if ($i.scope) { [string]$i.scope.list_id } else { $null }), $(if ($i.scope) { [int]$i.scope.count } else { 0 }))
    }
    if ($v.valid) { if (-not (($null -eq $r[0]) -and ([string]$r[1] -ceq [string]$v.text))) { $badFmt += $v.id } }
    else { if (-not (([string]$r[0] -ceq [string]$v.reason) -and ($null -eq $r[1]))) { $badFmt += $v.id } }
}
Check ('V-fmt every format input gets the table verdict and the exact text (' + $nFmt + ' inputs)' + $(if ($badFmt.Count) { ' - wrong: ' + (($badFmt | Select-Object -First 8) -join ',') } else { '' })) (($nFmt -gt 30) -and ($badFmt.Count -eq 0))

$badNum = @()
foreach ($v in $vec.numbers) {
    $r = J 'FormatLocation' @([string]$v.bits)
    $x = [BitConverter]::Int64BitsToDouble([Convert]::ToInt64([string]$v.bits, 16))
    $expectBits = $(if ($x -eq 0.0) { '0000000000000000' } else { [string]$v.bits })
    $back = $(if ($null -eq $r[0]) { J 'ParseLocation' @([string]$r[1]) } else { @('x', $null) })
    $ok = ($null -eq $r[0]) -and ([string]$r[1] -ceq [string]$v.text) -and ($null -eq $back[0]) -and ([string]$back[1] -ceq $expectBits)
    if (-not $ok) { $badNum += ($v.id + '[' + [string]$r[1] + ']') }
}
Check ('V-num every number vector is written as the exact canonical text and read back to the same double (' + @($vec.numbers).Count + ' values)' + $(if ($badNum.Count) { ' - wrong: ' + (($badNum | Select-Object -First 8) -join ',') } else { '' })) ($badNum.Count -eq 0)

$scopeCases = @(
    @(0, '00000000', 1, $null), @(2147483647, 'FFFFFFFF', 2147483647, $null), @(-1, 'E1D70409', 4, 'scenario-id-range'), @(1, 'E1D70409', 0, 'count-range'), @(1, 'E1D70409', -1, 'count-range'),
    @(1, 'e1d70409', 4, 'list-id-syntax'), @(1, 'E1D7040', 4, 'list-id-syntax'), @(1, 'E1D704090', 4, 'list-id-syntax'), @(1, 'E1D7040G', 4, 'list-id-syntax'), @(1, '', 4, 'list-id-syntax'), @(1, $null, 4, 'list-id-syntax'))
$badScope = @()
foreach ($c in $scopeCases) {
    $r = J 'ValidateScope' @([int]$c[0], [string]$c[1], [int]$c[2])
    $expect = $c[3]
    if (-not ((($null -eq $expect) -and ($null -eq $r[0]) -and ([bool]$r[1])) -or (($null -ne $expect) -and ([string]$r[0] -ceq [string]$expect) -and (-not [bool]$r[1])))) { $badScope += ('' + $c[0] + '/' + $c[1] + '/' + $c[2]) }
}
Check ('V-scope the scope boundaries (' + $scopeCases.Count + ' cases)' + $(if ($badScope.Count) { ' - wrong: ' + ($badScope -join ',') } else { '' })) ($badScope.Count -eq 0)

# same-location and nearby stations: the codec keeps the index it was given
$sa = J 'ParseRequest' @('JUMP_STA_TIME:1:36060000:7:2BF6D1AE:4:1000')
$sb = J 'ParseRequest' @('JUMP_STA_TIME:2:36060000:7:2BF6D1AE:4:1000')
Check 'V-same two stations at the same position keep the index they were asked for (1 and 2, one position)' (([int]$sa[4] -eq 1) -and ([int]$sb[4] -eq 2) -and ([string]$sa[7] -ceq [string]$sb[7]))
$na = J 'ParseRequest' @('JUMP_STA_TIME:1:36060000:3:0A0B0C0D:3:1000')
$nb = J 'ParseRequest' @('JUMP_STA_TIME:2:36060000:3:0A0B0C0D:3:1040.5')
Check 'V-near two stations 40.5 m apart keep the index they were asked for (1 and 2)' (([int]$na[4] -eq 1) -and ([int]$nb[4] -eq 2) -and ([string]$na[7] -cne [string]$nb[7]))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# N - numbers
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$negZero = '8000000000000000'
$rz = J 'FormatLocation' @($negZero)
$pz = J 'ParseLocation' @('-0.0')
Check 'N-negzero -0.0 is written as 0 and read as +0.0 (bits 0)' (($null -eq $rz[0]) -and ([string]$rz[1] -ceq '0') -and ([string]$pz[1] -ceq '0000000000000000'))
$nan = J 'FormatLocation' @('7FF8000000000000'); $pinf = J 'FormatLocation' @('7FF0000000000000'); $ninf = J 'FormatLocation' @('FFF0000000000000')
Check 'N-nonfinite NaN, +Infinity and -Infinity can not be written (location-range)' (([string]$nan[0] -ceq 'location-range') -and ([string]$pinf[0] -ceq 'location-range') -and ([string]$ninf[0] -ceq 'location-range'))
$above = J 'FormatLocation' @((HexBits 1000000001.0)); $below = J 'FormatLocation' @((HexBits 1e-10)); $dmax = J 'FormatLocation' @('7FEFFFFFFFFFFFFF')
$e1 = J 'FormatLocation' @((HexBits 1e9)); $e2 = J 'FormatLocation' @((HexBits 1e-9)); $e3 = J 'FormatLocation' @((HexBits -1e9))
Check 'N-range the range is inclusive at 1e9 and 1e-9 and closed beyond (1000000001, 1e-10, double max)' (($null -eq $e1[0]) -and ($null -eq $e2[0]) -and ($null -eq $e3[0]) -and ([string]$above[0] -ceq 'location-range') -and ([string]$below[0] -ceq 'location-range') -and ([string]$dmax[0] -ceq 'location-range'))

# culture independence: a comma culture and a dot culture give the same text and the same bits for everything the table holds
function RunUnderCulture([string]$name) {
    $old = [Threading.Thread]::CurrentThread.CurrentCulture
    try {
        [Threading.Thread]::CurrentThread.CurrentCulture = New-Object Globalization.CultureInfo($name)
        $out = @()
        foreach ($v in $vec.numbers) {
            $r = J 'FormatLocation' @([string]$v.bits)
            $b = J 'ParseLocation' @([string]$r[1])
            $out += ([string]$r[1] + '|' + [string]$b[1])
        }
        foreach ($v in $vec.locations) { $r = J 'ParseLocation' @([string]$v.text); $out += ([string]$r[0] + '|' + [string]$r[1]) }
        return ($out -join ';')
    } finally { [Threading.Thread]::CurrentThread.CurrentCulture = $old }
}
$cultures = @('en-US', 'de-DE', 'fr-FR', 'ja-JP', 'tr-TR')
$cultureResults = @{}
$cultureOk = $true
foreach ($c in $cultures) {
    try { $cultureResults[$c] = RunUnderCulture $c } catch { $cultureOk = $false; Write-Host ('  culture ' + $c + ' not available: ' + $_.Exception.Message) }
}
$distinct = @($cultureResults.Values | Sort-Object -Unique)
Check ('N-culture the text and the bits are the same under ' + $cultureResults.Count + ' cultures (de-DE and fr-FR write a decimal comma for the BCL)') ($cultureOk -and ($cultureResults.Count -eq $cultures.Count) -and ($distinct.Count -eq 1))
$deNative = (& { $old = [Threading.Thread]::CurrentThread.CurrentCulture; try { [Threading.Thread]::CurrentThread.CurrentCulture = New-Object Globalization.CultureInfo('de-DE'); return ((J 'DotNetR' @((HexBits 1234.5))) ) } finally { [Threading.Thread]::CurrentThread.CurrentCulture = $old } })
Check 'N-culture-control the control: the BCL under de-DE writes 1234,5 for an R format WITHOUT the invariant culture, so the test above is not vacuous' (($deNative -ceq '1234.5') -or ($deNative -ceq '1234,5'))

# the normaliser on its own (the writer would reject a NaN later anyway, so it must be held directly), and the rounding of the exact quotient at a tie
$nm = @{}
foreach ($c in @(@('nan', '7FF8000000000000'), @('pinf', '7FF0000000000000'), @('ninf', 'FFF0000000000000'), @('negzero', '8000000000000000'), @('zero', '0000000000000000'), @('max', (HexBits 1e9)), @('min', (HexBits 1e-9)),
                 @('nextabove', (HexBits ([BitConverter]::Int64BitsToDouble([BitConverter]::DoubleToInt64Bits(1e9) + 1)))), @('below', (HexBits 1e-10)), @('plain', (HexBits 1234.5678)), @('neg', (HexBits -50.5)))) { $nm[$c[0]] = J 'NormalizeLocation' @([string]$c[1]) }
Check 'N-normalize NormalizeLocation rejects NaN, +-Infinity and what is outside the range, turns -0.0 into +0.0 and passes the rest unchanged' (([string]$nm['nan'][0] -ceq 'location-range') -and ([string]$nm['pinf'][0] -ceq 'location-range') -and ([string]$nm['ninf'][0] -ceq 'location-range') -and ([string]$nm['nextabove'][0] -ceq 'location-range') -and ([string]$nm['below'][0] -ceq 'location-range') -and ($null -eq $nm['negzero'][0]) -and ([string]$nm['negzero'][1] -ceq '0000000000000000') -and ($null -eq $nm['zero'][0]) -and ($null -eq $nm['max'][0]) -and ($null -eq $nm['min'][0]) -and ([string]$nm['plain'][1] -ceq (HexBits 1234.5678)) -and ([string]$nm['neg'][1] -ceq (HexBits -50.5)))
# (2^53 + 1) / 2 and (2^53 + 3) / 2 are exact ties between two doubles: they must go to the EVEN neighbour (outside the position range, so only a direct call reaches the rule)
$tieDown = J 'Quotient' @([uint64]45035996273704965, 1)
$tieUp = J 'Quotient' @([uint64]45035996273704975, 1)
Check 'N-ties the exact quotient rounds a tie to even: (2^53+1)/2 -> 2^52 and (2^53+3)/2 -> 2^52+2' (([string]$tieDown -ceq (HexBits 4503599627370496.0)) -and ([string]$tieUp -ceq (HexBits 4503599627370498.0)))
# the corpus
$wordsRef = @($vec.corpus.reference)
$wordsCs = [string[]](J 'Splitmix' @([string]$vec.corpus.seed, $wordsRef.Count))
Check 'N-corpus-gen the splitmix64 generator of C# gives the words recorded in the table' (($wordsCs -join ',') -ceq ($wordsRef -join ','))
$famA = [string[]](J 'FamilyA' @([string]$vec.corpus.seed, [int]$vec.corpus.family_a.count))
$famB = [string[]](J 'FamilyB' @([string]$vec.corpus.seed, [int]$vec.corpus.family_b.count))
$badA = @(); $csTextA = New-Object System.Collections.Generic.List[string]
foreach ($b in $famA) {
    $r = J 'FormatLocation' @($b)
    $back = $(if ($null -eq $r[0]) { J 'ParseLocation' @([string]$r[1]) } else { @('x', $null) })
    if (($null -ne $r[0]) -or ($null -ne $back[0]) -or ([string]$back[1] -cne $b)) { if ($badA.Count -lt 5) { $badA += ($b + ' ' + [string]$r[1]) } else { $badA += 'x' } }
    $csTextA.Add($b + "`t" + [string]$r[1])
}
Check ('N-corpus-a ' + $famA.Count + ' binary doubles survive C# format and C# exact parse bit for bit' + $(if ($badA.Count) { ' - wrong: ' + (($badA | Select-Object -First 3) -join ';') } else { '' })) (($famA.Count -gt 15000) -and ($badA.Count -eq 0))
$badB = @(); $validB = 0; $csLinesB = New-Object System.Collections.Generic.List[string]
foreach ($t in $famB) {
    $r = J 'ParseLocation' @($t)
    if ($null -eq $r[0]) {
        $validB++
        $f = J 'FormatLocation' @([string]$r[1])
        $back = $(if ($null -eq $f[0]) { J 'ParseLocation' @([string]$f[1]) } else { @('x', $null) })
        if (($null -ne $f[0]) -or ($null -ne $back[0]) -or ([string]$back[1] -cne [string]$r[1])) { if ($badB.Count -lt 5) { $badB += $t } }
    } elseif (@('location-range', 'location-precision') -cnotcontains [string]$r[0]) { $badB += ('verdict ' + $t) }
    $csLinesB.Add($t + "`t" + [string]$r[0] + "`t" + [string]$r[1])
}
Check ('N-corpus-b ' + $famB.Count + ' decimal texts: ' + $validB + ' valid are read, written and read again to the same double' + $(if ($badB.Count) { ' - wrong: ' + (($badB | Select-Object -First 3) -join ';') } else { '' })) (($validB -gt 3000) -and ($badB.Count -eq 0))

# the .NET Framework facts that motivate the exact parser (measured, recorded in the table): if the BCL ever became exact these two checks would fail and the note must be revisited
$bclWrong = 0
foreach ($id in @('NUM-NET-PARSE-1', 'NUM-NET-PARSE-2', 'NUM-NET-PARSE-3')) {
    $v = @($vec.numbers | Where-Object { $_.id -ceq $id })[0]
    if ((J 'DotNetBits' @([string]$v.text)) -cne [string]$v.bits) { $bclWrong++ }
}
Write-Host ('INFO on this machine Double.Parse of the 3 recorded texts is not the correctly rounded double in ' + $bclWrong + ' of 3 (the reason JumpWire reads the text itself)')
$codecRight = $true
foreach ($id in @('NUM-NET-PARSE-1', 'NUM-NET-PARSE-2', 'NUM-NET-PARSE-3', 'NUM-NET-R-1', 'NUM-NET-R-2', 'NUM-NET-R-3', 'NUM-NET-R-4')) {
    $v = @($vec.numbers | Where-Object { $_.id -ceq $id })[0]
    $p = J 'ParseLocation' @([string]$v.text)
    if (([string]$p[1]) -cne [string]$v.bits) { $codecRight = $false }
}
Check 'N-codec-exact the 7 recorded texts where the BCL is off by one unit in the last place are read exactly by JumpWire' $codecRight

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# E - the readers that exist
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Write-Host ('EQUIVALENCE-TABLE id | text | current | legacy | jumpwire | class')
$eqList = @(); if ($vec.PSObject.Properties['equivalence']) { $eqList = @($vec.equivalence) }
$badEq = @(); $classCount = @{}
foreach ($e in $eqList) {
    $station = ([string]$e.raw).StartsWith('JUMP_STA_TIME:')
    $cur = [bool](J 'CurrentValidGrammar' @($station, [string]$e.raw))
    $lc = J 'LegacyClaim' @($station, [string]$e.raw)
    $leg = ([string]$lc[0] -cne 'NONE')
    $pj = J 'ParseRequest' @([string]$e.raw)
    $jwOk = ($null -eq $pj[0]) -and ([int]$pj[1] -eq 1)
    Write-Host ('  ' + $e.id + ' | ' + ([string]$e.raw -replace "`r", '\r' -replace "`n", '\n') + ' | ' + $cur + ' | ' + $leg + ' | ' + $jwOk + ' | ' + $e.class)
    $same = $true
    if ($cur -and $leg -and $jwOk) {
        # the three accept: do they mean the same thing? (the table records the answer)
        $timeJw = [int]$pj[5]
        $sameMeaning = ([int]$lc[3] -eq $timeJw)
        if ($station) { $sameMeaning = $sameMeaning -and ([int]$lc[1] -eq [int]$pj[4]) }
        else {
            $oldLoc = [BitConverter]::Int64BitsToDouble([Convert]::ToInt64([string]$lc[2], 16))
            $newLoc = [BitConverter]::Int64BitsToDouble([Convert]::ToInt64([string]$pj[7], 16))
            $sameMeaning = $sameMeaning -and ($oldLoc -eq $newLoc)
        }
        if ($e.PSObject.Properties['same_meaning']) { $same = ($sameMeaning -eq [bool]$e.same_meaning) }
        else { Write-Host ('  INFO ' + $e.id + ' same meaning on this platform: ' + $sameMeaning + ' (platform dependent, not enforced)') }
    }
    $ok = ($cur -eq [bool]$e.current_accepts) -and ($leg -eq [bool]$e.legacy_accepts) -and ($jwOk -eq [bool]$e.jumpwire_accepts) -and $same
    if (-not $ok) { $badEq += $e.id }
    $classCount[[string]$e.class] = 1 + [int]$classCount[[string]$e.class]
}
Check ('E-eq the existing C# readers (CurrentJumpEndpoint.ValidGrammar, LegacyJumpClaim.From) and JumpWire give the verdicts the table records on ' + $eqList.Count + ' v1 texts, and mean the same wherever all three accept' + $(if ($badEq.Count) { ' - wrong: ' + (($badEq | Select-Object -First 8) -join ',') } else { '' })) (($eqList.Count -gt 25) -and ($badEq.Count -eq 0))
$newAccepts = @($eqList | Where-Object { [bool]$_.jumpwire_accepts -and (-not ([bool]$_.current_accepts -and [bool]$_.legacy_accepts)) })
Check 'E-never JumpWire v1 never accepts a text that one of the existing readers rejects' ($newAccepts.Count -eq 0)
Write-Host ('  classes: ' + (($classCount.Keys | Sort-Object | ForEach-Object { $_ + '=' + $classCount[$_] }) -join ' '))

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# B - boundary
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$projects = @(Get-ChildItem $Root -Recurse -Filter *.csproj | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' }) + @(Get-ChildItem (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin') -Filter *.csproj)
$linked = @($projects | Where-Object { ([IO.File]::ReadAllText($_.FullName)) -match 'JumpWire' })
Check ('B-link JumpWire.cs is a Compile item of none of the ' + $projects.Count + ' projects (ST-3a leaves both DLLs unchanged; ST-3b / ST-3c add the link)') ($linked.Count -eq 0)
$sha = (Get-FileHash -LiteralPath $endpointPath -Algorithm SHA256).Hash
Check 'B-sha CurrentJumpEndpoint.cs (the existing v1 reader, shared with the Legacy DLL) is byte-identical to the SHA-256 recorded at PID-D6' ($sha -ceq $endpointSha)
$jwText = [IO.File]::ReadAllText($jwPath)
$jwCode = [regex]::Replace([regex]::Replace($jwText, '(?s)/\*.*?\*/', ''), '(?m)//.*$', '')
Check 'B-host JumpWire.cs names no BVE / BveEX / AtsEX / Legacy / Caller / Handshake type, no file, socket, thread or reflection API, and no fixed port' (($jwCode -cnotmatch 'BveEx|BveEX|AtsEx|AtsEX|Legacy|Caller|Handshake|BveHacker|System\.IO|System\.Net|System\.Threading|System\.Reflection|System\.Diagnostics|File\.|Directory\.|54321|54322'))
Check 'B-syntax JumpWire.cs is ASCII only and uses no C# 6 syntax (no interpolated string, no ?. , no expression bodied member, no nameof, no out var)' (($jwText -cnotmatch '[^\x00-\x7f]') -and ($jwCode -cnotmatch '\$"') -and ($jwCode -cnotmatch '\?\.') -and ($jwCode -cnotmatch '\)\s*=>') -and ($jwCode -cnotmatch 'nameof\(') -and ($jwCode -cnotmatch 'out var '))
Check 'B-format JumpWire.cs writes a position only with the invariant culture (G15 / G16 / G17, each verified by the exact parse), never with the current culture and never with R' (($jwCode -cmatch '"G15"') -and ($jwCode -cmatch '"G16"') -and ($jwCode -cmatch '"G17"') -and ($jwCode -cnotmatch '"R"') -and (@([regex]::Matches($jwCode, '(?<!\ball)(?<!\bsb)\.ToString\(\)')).Count -eq 0) -and ((@([regex]::Matches($jwCode, '\.ToString\([^)]+\)')).Count) -eq (@([regex]::Matches($jwCode, '\.ToString\([^)]*CultureInfo\.InvariantCulture\)')).Count)))
Check 'B-parse JumpWire.cs calls no Double.Parse / TryParse / Convert.ToDouble (the BCL parse is not correctly rounded)' ($jwCode -cnotmatch 'Double\.Parse|double\.Parse|TryParse|Convert\.ToDouble|Convert\.ToSingle')

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# X - cross-language: Python reads what C# wrote, C# reads what Python wrote
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
$workDir = Join-Path $env:TEMP ('ts-st3a-jumpwire-' + [Diagnostics.Process]::GetCurrentProcess().Id)
$pythonExe = (Get-Command python -ErrorAction SilentlyContinue)
if ($null -eq $pythonExe) { Check 'X python could not be found on the PATH (the cross-language run needs it)' $false }
else {
    New-Item -ItemType Directory -Force $workDir | Out-Null
    try {
        $aPath = Join-Path $workDir 'cs-a.tsv'; $bPath = Join-Path $workDir 'cs-b.tsv'; $pyPath = Join-Path $workDir 'check.py'
        [IO.File]::WriteAllLines($aPath, $csTextA.ToArray(), (New-Object Text.UTF8Encoding($false)))
        [IO.File]::WriteAllLines($bPath, $csLinesB.ToArray(), (New-Object Text.UTF8Encoding($false)))
        $py = @'
import struct
import sys
repo, a_path, b_path = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)
import jump_wire as jw


def bits_of(x):
    return "%016X" % struct.unpack(">Q", struct.pack(">d", x))[0]


def float_of(h):
    return struct.unpack(">d", struct.pack(">Q", int(h, 16)))[0]


# A: C# wrote a text for each binary double; Python must read the same double. Python also writes its own text for the same double: it is printed for C# to read.
bad_a = 0
same_text = 0
n_a = 0
py_a = []
for line in open(a_path, encoding="ascii"):
    bits, cs_text = line.rstrip("\n").split("\t")
    n_a += 1
    x = float_of(bits)
    got, reason = jw.parse_location(cs_text)
    if reason is not None or bits_of(got) != bits:
        bad_a += 1
    own, _r = jw.format_location(x)
    if own == cs_text:
        same_text += 1
    py_a.append("%s\t%s" % (bits, own))
# B: C# read each decimal text; Python must give the same verdict and the same bits
bad_b = 0
n_b = 0
for line in open(b_path, encoding="ascii"):
    text, reason_cs, bits_cs = line.rstrip("\n").split("\t")
    n_b += 1
    got, reason = jw.parse_location(text)
    if (reason or "") != reason_cs or (got is not None and bits_of(got) != bits_cs):
        bad_b += 1
print("A n=%d bad=%d identical_text=%d" % (n_a, bad_a, same_text))
print("B n=%d bad=%d" % (n_b, bad_b))
for row in py_a:
    print("P\t" + row)
'@
        [IO.File]::WriteAllText($pyPath, $py, (New-Object Text.UTF8Encoding($false)))
        $pyOut = @(& python -I -B $pyPath $repo $aPath $bPath)
        $lineA = @($pyOut | Where-Object { $_ -like 'A n=*' })[0]
        $lineB = @($pyOut | Where-Object { $_ -like 'B n=*' })[0]
        Check ('X-cs-to-py Python reads every text C# wrote for the binary corpus as the same double: ' + $lineA) (($null -ne $lineA) -and ($lineA -match 'bad=0 '))
        Check ('X-cs-to-py-b Python gives the same verdict and the same bits for every decimal text C# read: ' + $lineB) (($null -ne $lineB) -and ($lineB -match 'bad=0$'))
        $badP = 0; $nP = 0
        foreach ($row in @($pyOut | Where-Object { $_ -like "P`t*" })) {
            $p = $row.Split("`t")
            $nP++
            $r = J 'ParseLocation' @([string]$p[2])
            if (($null -ne $r[0]) -or ([string]$r[1] -cne [string]$p[1])) { $badP++ }
        }
        Check ('X-py-to-cs C# reads every text Python wrote for the binary corpus as the same double (' + $nP + ' texts)') (($nP -eq $famA.Count) -and ($badP -eq 0))
    } finally {
        Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Check 'CLEAN the work folder this run made in %TEMP% is gone' (-not (Test-Path -LiteralPath $workDir))
Finish
