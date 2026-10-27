# PHASE SI-R2.2-S2b - the two HOST ADAPTERS run offline against stubs of the BveTypes wrapper classes, and write the same OFFTGT part.
# The Current adapter (Class1.cs CreateOfficialTargetHost) and the Legacy adapter (LegacyTelemetryExtension.cs ILegacyOfficialTargetApi.ReadOfficialTarget) can not be compiled with the
# product sources (they name BveTypes). This script takes THEIR SOURCE TEXT, cuts the two methods out of the files exactly as they stand, and compiles each of them IN MEMORY with the
# Windows PowerShell 5.1 compiler (C# 5) next to a minimal stub of the wrapper classes they read (Scenario, Vehicle, Conductor, MapObjectList, MapObjectBase, Station). The same stub world
# is then given to both: the OFFTGT part the two write must be the same text (byte for byte), must be the expected one, and the cursor of the stub list must never be written.
# What this does NOT prove: that the real BveTypes classes behave like the stubs (that is the scratch compile-check of the type names and, later, the live runs of SI-R2.5 / SI-R2.6).
# No file is written. Exit codes: 0 = every check passed, 1 = a check failed, 2 = INCONCLUSIVE (a source is missing / does not compile). This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $Root -Parent) -Parent
$telRoot = Join-Path $Root 'Telemetry'
$class1Path = Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\Class1.cs'
$extensionPath = Join-Path $telRoot 'Legacy\src\LegacyTelemetryExtension.cs'
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Inconclusive([string]$why) { Write-Host ('INCONCLUSIVE ' + $why); exit 2 }
foreach ($path in @($class1Path, $extensionPath)) { if (-not (Test-Path -LiteralPath $path)) { Inconclusive ('missing: ' + $path) } }

# the text of a member: from its header to the matching closing brace (the two adapters hold no brace inside a string or a comment)
function Cut-Member([string]$text, [string]$header) {
    $start = $text.IndexOf($header, [StringComparison]::Ordinal)
    if ($start -lt 0) { Inconclusive ('member not found: ' + $header) }
    if ($text.IndexOf($header, $start + 1, [StringComparison]::Ordinal) -ge 0) { Inconclusive ('member found twice: ' + $header) }
    $open = $text.IndexOf('{', $start)
    $depth = 0
    for ($i = $open; $i -lt $text.Length; $i++) {
        if ($text[$i] -eq '{') { $depth++ } elseif ($text[$i] -eq '}') { $depth--; if ($depth -eq 0) { return $text.Substring($start, $i - $start + 1) } }
    }
    Inconclusive ('unbalanced member: ' + $header)
}
$class1Text = [IO.File]::ReadAllText($class1Path, [Text.Encoding]::UTF8)
$extensionText = [IO.File]::ReadAllText($extensionPath, [Text.Encoding]::UTF8)
$currentMethod = Cut-Member $class1Text 'private TSScoringPlugin.Telemetry.OfficialTargetHost CreateOfficialTargetHost()'
$legacyMethod = Cut-Member $extensionText 'OfficialTargetReading ILegacyOfficialTargetApi.ReadOfficialTarget()'

$stubs = @'
using System;
using System.Collections.Generic;
namespace BveTypes.ClassWrappers
{
    public class SourceBox { public double Location; public double MarginMin; public double MarginMax; }
    public class MapObjectBase { public virtual double Location { get; set; } public object Src; }
    public class Station : MapObjectBase
    {
        public double MarginMin { get; set; }
        public double MarginMax { get; set; }
        public static Station FromSource(object src)
        {
            SourceBox box = (SourceBox)src;
            Station s = new Station();
            s.Location = box.Location; s.MarginMin = box.MarginMin; s.MarginMax = box.MarginMax;
            return s;
        }
    }
    public class MapObjectList
    {
        public int CursorWrites = 0;
        public bool ThrowCursor = false;
        public bool ThrowCount = false;
        public bool ThrowItem = false;
        public int CursorValue = -1;
        public int CountValue = 0;
        public List<MapObjectBase> Items = new List<MapObjectBase>();
        public int CurrentIndex
        {
            get { if (ThrowCursor) { throw new InvalidOperationException("cursor"); } return CursorValue; }
            set { CursorWrites++; CursorValue = value; }
        }
        public int Count { get { if (ThrowCount) { throw new InvalidOperationException("count"); } return CountValue; } }
        public MapObjectBase this[int index] { get { if (ThrowItem) { throw new ArgumentOutOfRangeException("index"); } return Items[index]; } }
    }
    public class Conductor { public MapObjectList Stations; }
    public class Vehicle { public Conductor Conductor; }
    public class Scenario { public Vehicle Vehicle; }
}
namespace BveHackerStub { public class Hacker { public BveTypes.ClassWrappers.Scenario Scenario; } }
'@

$adapters = @"
using System;
using TSScoringPlugin.Telemetry;
using BveTypes.ClassWrappers;
namespace Parity
{
    internal sealed class LegacyAdapter : ILegacyOfficialTargetApi
    {
        private Scenario current;
        internal void SetScenario(Scenario scenario) { current = scenario; }
        $legacyMethod
    }

    internal sealed class CurrentAdapter
    {
        internal BveHackerStub.Hacker BveHacker = new BveHackerStub.Hacker();
        $currentMethod
        internal OfficialTargetReading Read() { return OfficialTargetReader.Read(CreateOfficialTargetHost()); }
    }

    public static class ParityProbe
    {
        public static BveTypes.ClassWrappers.Scenario World(string mode, int cursor, int count, double loc, double min, double max, bool sourceOnly)
        {
            BveTypes.ClassWrappers.Scenario scenario = new BveTypes.ClassWrappers.Scenario();
            if (mode == "null-scenario") { return null; }
            if (mode == "null-vehicle") { return scenario; }
            scenario.Vehicle = new BveTypes.ClassWrappers.Vehicle();
            if (mode == "null-conductor") { return scenario; }
            scenario.Vehicle.Conductor = new BveTypes.ClassWrappers.Conductor();
            if (mode == "null-stations") { return scenario; }
            BveTypes.ClassWrappers.MapObjectList list = new BveTypes.ClassWrappers.MapObjectList();
            scenario.Vehicle.Conductor.Stations = list;
            list.CursorValue = cursor;
            list.CountValue = count;
            for (int i = 0; i < count; i++)
            {
                if (sourceOnly)
                {
                    BveTypes.ClassWrappers.MapObjectBase item = new BveTypes.ClassWrappers.MapObjectBase();
                    BveTypes.ClassWrappers.SourceBox box = new BveTypes.ClassWrappers.SourceBox();
                    box.Location = loc; box.MarginMin = min; box.MarginMax = max;
                    item.Src = box;
                    list.Items.Add(item);
                }
                else
                {
                    BveTypes.ClassWrappers.Station station = new BveTypes.ClassWrappers.Station();
                    station.Location = loc; station.MarginMin = min; station.MarginMax = max;
                    list.Items.Add(station);
                }
            }

            list.ThrowCursor = (mode == "throw-cursor");
            list.ThrowCount = (mode == "throw-count");
            list.ThrowItem = (mode == "throw-item");
            return scenario;
        }

        public static string[] Both(string mode, int cursor, int count, double loc, double min, double max, bool sourceOnly, string listId, out int cursorWrites)
        {
            BveTypes.ClassWrappers.Scenario scenario = World(mode, cursor, count, loc, min, max, sourceOnly);
            LegacyAdapter legacy = new LegacyAdapter();
            legacy.SetScenario(scenario);
            CurrentAdapter current = new CurrentAdapter();
            current.BveHacker.Scenario = scenario;
            string legacyPart = OfficialTargetWire.Part(((ILegacyOfficialTargetApi)legacy).ReadOfficialTarget(), listId);
            string currentPart = OfficialTargetWire.Part(current.Read(), listId);
            cursorWrites = 0;
            if (scenario != null && scenario.Vehicle != null && scenario.Vehicle.Conductor != null && scenario.Vehicle.Conductor.Stations != null) { cursorWrites = scenario.Vehicle.Conductor.Stations.CursorWrites; }
            return new string[] { legacyPart, currentPart };
        }
    }
}
"@

$files = @()
$files += Get-ChildItem (Join-Path $telRoot 'Legacy\src') -Filter *.cs | Where-Object { $_.Name -notin @('LegacyTelemetryExtension.cs', 'AssemblyInfo.cs') } | ForEach-Object { $_.FullName }
$files += Get-ChildItem (Join-Path $telRoot 'Shared') -Filter *.cs | ForEach-Object { $_.FullName }
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')
$files += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs')
$texts = New-Object System.Collections.Generic.List[string]
foreach ($file in $files) { $texts.Add([IO.File]::ReadAllText($file, [Text.Encoding]::UTF8)) }
$texts.Add($stubs)
$texts.Add($adapters)
Add-Type -AssemblyName Microsoft.CSharp
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.GenerateInMemory = $true
$cp.TreatWarningsAsErrors = $false
foreach ($r in @('System.dll', 'System.Core.dll')) { $cp.ReferencedAssemblies.Add($r) | Out-Null }
$compiled = $provider.CompileAssemblyFromSource($cp, [string[]]$texts.ToArray())
if ($compiled.Errors.HasErrors) {
    foreach ($e in $compiled.Errors) { if (-not $e.IsWarning) { Write-Host ('  compile error: ' + $e.ErrorNumber + ' line ' + $e.Line + ' ' + $e.ErrorText) } }
    Inconclusive 'the two adapters (as they stand in the product files) do not compile against the stubs'
}
$asm = $compiled.CompiledAssembly
Write-Host ('PREFLIGHT the two adapter methods were cut from the product files and compiled in memory (' + $files.Count + ' product sources + stubs; no file written)')
$probe = $asm.GetType('Parity.ParityProbe')

function Run-World([string]$mode, [int]$cursor, [int]$count, [double]$loc, [double]$min, [double]$max, [bool]$sourceOnly) {
    $writes = 0
    $args2 = New-Object 'object[]' 9
    $args2[0] = $mode; $args2[1] = $cursor; $args2[2] = $count; $args2[3] = $loc; $args2[4] = $min; $args2[5] = $max; $args2[6] = $sourceOnly; $args2[7] = 'E1D70409'; $args2[8] = $writes
    $parts = $probe.GetMethod('Both').Invoke($null, $args2)
    return @{ Legacy = [string]$parts[0]; Current = [string]$parts[1]; Writes = [int]$args2[8] }
}
$unavailable = 'OFFTGT:1:U:-1:-1:00000000:-1:-1:-1'
$failed = 'OFFTGT:1:F:-1:-1:00000000:-1:-1:-1'
$cases = @(
    @{ Id = 'K the station CurrentIndex + 1 is read (a Station in the list)'; Mode = 'ok'; Cursor = 0; Count = 4; Loc = 1000.0; Min = -5.0; Max = 10.0; Src = $false; Want = 'OFFTGT:1:K:1:4:E1D70409:1000:5:10' },
    @{ Id = 'K the item is only a MapObjectBase: the station comes from its source (FromSource)'; Mode = 'ok'; Cursor = 0; Count = 4; Loc = 570.04; Min = -4.5; Max = 5.55; Src = $true; Want = 'OFFTGT:1:K:1:4:E1D70409:570.04:4.5:5.55' },
    @{ Id = 'K the first station (CurrentIndex -1)'; Mode = 'ok'; Cursor = -1; Count = 2; Loc = 0.0; Min = 0.0; Max = 3.0; Src = $false; Want = 'OFFTGT:1:K:0:2:E1D70409:0:0:3' },
    @{ Id = 'K a negative location'; Mode = 'ok'; Cursor = 1; Count = 3; Loc = -12.5; Min = -4.5; Max = 6.0; Src = $false; Want = 'OFFTGT:1:K:2:3:E1D70409:-12.5:4.5:6' },
    @{ Id = 'T the last station is behind (CurrentIndex + 1 = Count)'; Mode = 'ok'; Cursor = 3; Count = 4; Loc = 1.0; Min = 1.0; Max = 1.0; Src = $false; Want = 'OFFTGT:1:T:-1:4:E1D70409:-1:-1:-1' },
    @{ Id = 'N an empty list'; Mode = 'ok'; Cursor = 0; Count = 0; Loc = 0.0; Min = 0.0; Max = 0.0; Src = $false; Want = 'OFFTGT:1:N:-1:0:00000000:-1:-1:-1' },
    @{ Id = 'U no scenario'; Mode = 'null-scenario'; Cursor = 0; Count = 0; Loc = 0.0; Min = 0.0; Max = 0.0; Src = $false; Want = $unavailable },
    @{ Id = 'U no vehicle'; Mode = 'null-vehicle'; Cursor = 0; Count = 0; Loc = 0.0; Min = 0.0; Max = 0.0; Src = $false; Want = $unavailable },
    @{ Id = 'U no conductor'; Mode = 'null-conductor'; Cursor = 0; Count = 0; Loc = 0.0; Min = 0.0; Max = 0.0; Src = $false; Want = $unavailable },
    @{ Id = 'U no station list'; Mode = 'null-stations'; Cursor = 0; Count = 0; Loc = 0.0; Min = 0.0; Max = 0.0; Src = $false; Want = $unavailable },
    @{ Id = 'F the cursor getter throws'; Mode = 'throw-cursor'; Cursor = 0; Count = 4; Loc = 1000.0; Min = 5.0; Max = 5.0; Src = $false; Want = $failed },
    @{ Id = 'F the Count getter throws'; Mode = 'throw-count'; Cursor = 0; Count = 4; Loc = 1000.0; Min = 5.0; Max = 5.0; Src = $false; Want = $failed },
    @{ Id = 'F the indexer throws'; Mode = 'throw-item'; Cursor = 0; Count = 4; Loc = 1000.0; Min = 5.0; Max = 5.0; Src = $false; Want = $failed },
    @{ Id = 'F a cursor beyond the list'; Mode = 'ok'; Cursor = 4; Count = 4; Loc = 1000.0; Min = 5.0; Max = 5.0; Src = $false; Want = $failed },
    @{ Id = 'F a cursor below -1'; Mode = 'ok'; Cursor = -2; Count = 4; Loc = 1000.0; Min = 5.0; Max = 5.0; Src = $false; Want = $failed },
    @{ Id = 'F a station location that is not a number'; Mode = 'ok'; Cursor = 0; Count = 4; Loc = [double]::NaN; Min = 5.0; Max = 5.0; Src = $false; Want = $failed },
    @{ Id = 'F a margin ahead below zero'; Mode = 'ok'; Cursor = 0; Count = 4; Loc = 1000.0; Min = 5.0; Max = -1.0; Src = $false; Want = $failed }
)
foreach ($case in $cases) {
    $result = Run-World $case.Mode $case.Cursor $case.Count $case.Loc $case.Min $case.Max $case.Src
    Check ('A-' + $case.Id + ': Current and Legacy write the same part, the expected one (' + $case.Want + ')') (($result.Legacy -ceq $case.Want) -and ($result.Current -ceq $case.Want))
    Check ('A-' + $case.Id + ': the cursor of the host list was not written') ($result.Writes -eq 0)
}
$mismatch = @($cases | Where-Object { $r = Run-World $_.Mode $_.Cursor $_.Count $_.Loc $_.Min $_.Max $_.Src; $r.Legacy -cne $r.Current }).Count
Check 'A-ALL the Current and the Legacy part are byte for byte the same in every world of the table' ($mismatch -eq 0)

# the cut text is what the product files hold (a copy of it in this script would not be a test of the product)
Check 'S01 the Current adapter text contains no write to the host and the Legacy adapter text contains none' (($currentMethod -notmatch 'CurrentIndex\s*=(?!=)') -and ($legacyMethod -notmatch 'CurrentIndex\s*=(?!=)'))
Check 'S02 each adapter reads the cursor exactly once' (([regex]::Matches($currentMethod, 'CurrentIndex')).Count -eq 1 -and ([regex]::Matches($legacyMethod, 'CurrentIndex')).Count -eq 1)

Write-Host ('SUMMARY pass=' + $script:pass + ' fail=' + $script:fail)
if ($script:fail -gt 0) { exit 1 }
exit 0
