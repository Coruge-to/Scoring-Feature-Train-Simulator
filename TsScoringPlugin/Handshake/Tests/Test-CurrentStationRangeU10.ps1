param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# PHASE PID-D4JA StationIndex U10 - offline BEHAVIOUR test of the stop range reader of the Current sender. Class1.cs can not run offline (it needs the BveEX host), so this test cuts the one
# method that decides the range out of the SOURCE of Class1.cs (ReadStationRange: the text itself, not a copy) and compiles it in memory next to fake host stations (CodeDom, C# 5, same route
# as Test-CurrentJumpST3B.ps1; no BVE, no BveEx, no port, no product build, nothing is written to the repository). What Class1.cs does AROUND the reader (reject the whole list, latch, publish
# nothing, one line) is held by tests\test_stationindex_station_range_u10.py (source pins) and judged live in ST-3e2.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$class1 = Join-Path $RepositoryRoot 'TsScoringPlugin\TsScoringPlugin\Class1.cs'
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}

function Get-MethodText([string]$text, [string]$signature) {
    $start = $text.IndexOf($signature, [StringComparison]::Ordinal)
    if ($start -lt 0) { return $null }
    $open = $text.IndexOf('{', $start)
    if ($open -lt 0) { return $null }
    $depth = 0
    for ($p = $open; $p -lt $text.Length; $p++) {
        $c = $text[$p]
        if ($c -eq '{') { $depth++ }
        elseif ($c -eq '}') {
            $depth--
            if ($depth -eq 0) { return $text.Substring($start, $p - $start + 1) }
        }
    }
    return $null
}

Write-Host '--- A: the reader is cut out of Class1.cs'
$source = [IO.File]::ReadAllText($class1, [Text.Encoding]::UTF8)
$method = Get-MethodText $source 'private static string ReadStationRange(object station, StationData sd, out string exceptionType)'
Check 'A01 Class1.cs has ReadStationRange(object station, StationData sd, out string exceptionType)' ($null -ne $method)
if ($null -eq $method) {
    Write-Host ''
    Write-Host 'PASS=0 FAIL=1'
    exit 1
}
Check 'A02 the method is the only reader of the stop range in the builder (the loop calls it; no second read of MarginMin / MarginMax elsewhere)' (([regex]::Matches($source, '\(double\)st\.Margin(Min|Max)')).Count -eq 2)

$fixture = @'
using System;
using System.Collections.Generic;

namespace TsScoringPlugin
{
    public class StationData
    {
        public double MarginMin;
        public double MarginMax;
    }

    public class FakeStation
    {
        public object Min;
        public object Max;
        public bool MinThrows;
        public bool MaxThrows;
        public object MarginMin { get { if (MinThrows) { throw new InvalidOperationException("secret D:\\private\\x.map"); } return Min; } }
        public object MarginMax { get { if (MaxThrows) { throw new InvalidOperationException("secret D:\\private\\y.map"); } return Max; } }
    }

    public class NoRangeStation { public string Name { get { return "x"; } } }

    public class OnlyMinStation { public object MarginMin { get { return -6.25; } } }

    public static class RangeUnderTest
    {
//METHOD//

        public static string Read(object st, StationData sd, out string ex)
        {
            return ReadStationRange(st, sd, out ex);
        }
    }

    public static class RangeFixture
    {
        private static List<string> bad;
        private static int checks;

        private static void Expect(string name, bool ok)
        {
            checks++;
            if (!ok) { bad.Add(name); }
        }

        private static FakeStation Station(object min, object max)
        {
            FakeStation s = new FakeStation();
            s.Min = min;
            s.Max = max;
            return s;
        }

        private static void Normal(string name, object min, object max, double expectMin, double expectMax)
        {
            StationData sd = new StationData();
            string ex;
            string stage = RangeUnderTest.Read(Station(min, max), sd, out ex);
            Expect(name + ": stage is null", stage == null);
            Expect(name + ": MarginMin == " + expectMin, sd.MarginMin == expectMin);
            Expect(name + ": MarginMax == " + expectMax, sd.MarginMax == expectMax);
            Expect(name + ": no exception type", ex == "-");
        }

        private static void Failed(string name, object station, string expectStage, string expectEx)
        {
            StationData sd = new StationData();
            string ex;
            string stage = RangeUnderTest.Read(station, sd, out ex);
            Expect(name + ": stage is " + expectStage + " (was " + (stage ?? "null") + ")", stage == expectStage);
            Expect(name + ": exception type is " + expectEx + " (was " + ex + ")", ex == expectEx);
            Expect(name + ": no 5.0 stand-in in MarginMin", sd.MarginMin != 5.0);
            Expect(name + ": no 5.0 stand-in in MarginMax", sd.MarginMax != 5.0);
            Expect(name + ": the exception text is never part of the answer", ex.IndexOf("secret", StringComparison.Ordinal) < 0 && ex.IndexOf("private", StringComparison.Ordinal) < 0);
        }

        public static string[] Run()
        {
            bad = new List<string>();
            checks = 0;

            // normal stations: |MarginMin| and MarginMax exactly as before (the host gives the rear margin negative)
            Normal("N1 -5 / 5", -5.0, 5.0, 5.0, 5.0);
            Normal("N2 -3.5 / 4.25", -3.5, 4.25, 3.5, 4.25);
            Normal("N3 0 / 0", 0.0, 0.0, 0.0, 0.0);
            Normal("N4 +7 / 9 (a positive MarginMin is used as it is)", 7.0, 9.0, 7.0, 9.0);
            Normal("N5 int values (-4 / 6)", -4, 6, 4.0, 6.0);
            Normal("N6 float values (-2.5f / 3.5f)", -2.5f, 3.5f, 2.5, 3.5);
            Normal("N7 MarginMax negative is the host's value, not a failure (-5 / -1)", -5.0, -1.0, 5.0, -1.0);
            Normal("N8 MarginMin larger than MarginMax is the host's value, not a failure (-20 / 1)", -20.0, 1.0, 20.0, 1.0);
            Normal("N9 very large finite (-1e300 / 1e300)", -1e300, 1e300, 1e300, 1e300);

            // read failures: the stage names the member, the answer carries the TYPE of the exception only
            FakeStation e1 = Station(-6.25, 7.5); e1.MinThrows = true;
            Failed("R1 MarginMin throws", e1, "min-read", "InvalidOperationException");
            FakeStation e2 = Station(-6.25, 7.5); e2.MaxThrows = true;
            Failed("R2 MarginMax throws", e2, "max-read", "InvalidOperationException");
            FakeStation e3 = Station(-6.25, 7.5); e3.MinThrows = true; e3.MaxThrows = true;
            Failed("R3 both throw: the first member names the stage", e3, "min-read", "InvalidOperationException");
            Failed("R4 neither member exists", new NoRangeStation(), "min-read", "RuntimeBinderException");
            Failed("R5 only MarginMin exists", new OnlyMinStation(), "max-read", "RuntimeBinderException");
            Failed("R6 MarginMin is not a number", Station("x", 7.5), "min-read", "RuntimeBinderException");
            Failed("R7 MarginMax is not a number", Station(-6.25, "x"), "max-read", "RuntimeBinderException");
            Failed("R8 MarginMin is null", Station(null, 7.5), "min-read", "RuntimeBinderException");
            Failed("R9 MarginMax is null", Station(-6.25, null), "max-read", "RuntimeBinderException");
            Failed("R10 the station itself is null", null, "min-read", "RuntimeBinderException");

            // values that were read but are not finite
            Failed("V1 MarginMin NaN", Station(double.NaN, 7.5), "min-invalid", "-");
            Failed("V2 MarginMin +Infinity", Station(double.PositiveInfinity, 7.5), "min-invalid", "-");
            Failed("V3 MarginMin -Infinity (|-Inf| is +Inf)", Station(double.NegativeInfinity, 7.5), "min-invalid", "-");
            Failed("V4 MarginMax NaN", Station(-6.25, double.NaN), "max-invalid", "-");
            Failed("V5 MarginMax +Infinity", Station(-6.25, double.PositiveInfinity), "max-invalid", "-");
            Failed("V6 MarginMax -Infinity", Station(-6.25, double.NegativeInfinity), "max-invalid", "-");
            Failed("V7 both NaN: the first member names the stage", Station(double.NaN, double.NaN), "min-invalid", "-");

            // a read failure wins over a value check of the other member (the MarginMax read is not reached when MarginMin throws)
            FakeStation e4 = Station(double.NaN, double.NaN); e4.MinThrows = true;
            Failed("W1 read failure before value check", e4, "min-read", "InvalidOperationException");

            string[] result = new string[bad.Count + 1];
            result[0] = checks.ToString();
            for (int i = 0; i < bad.Count; i++) { result[i + 1] = bad[i]; }
            return result;
        }
    }
}
'@
$fixture = $fixture.Replace('//METHOD//', $method)

Write-Host '--- B: compiled behaviour of the reader (RangeFixture)'
$compileError = $null
try {
    Add-Type -TypeDefinition $fixture -ReferencedAssemblies @('System.dll', 'System.Core.dll', 'Microsoft.CSharp.dll')
} catch {
    $compileError = $_.Exception.Message
}
Check 'B01 the cut-out reader compiles in memory (C# 5)' ($null -eq $compileError)
if ($null -ne $compileError) {
    Write-Host ('  compile error: ' + $compileError)
} else {
    $results = [TsScoringPlugin.RangeFixture]::Run()
    $checks = $results[0]
    $badRows = @($results | Select-Object -Skip 1)
    Check ('B02 every compiled check passed (' + $checks + ')') ($badRows.Count -eq 0)
    foreach ($b in $badRows) { Write-Host ('  FAILED: ' + $b) }
}

Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'U10 Current station range tests passed.'
