# TB-E: offline parity of the Legacy PTPAIR supply. The REAL LegacyStationTimeline (Build seam + PtPairText) is compiled in memory with its minimal sources (no host, no BVE, no DLL written),
# driven with LegacyStationRaw lists made from the tests\pt_vectors.json "qualifier" vectors (the four flags -> ArrivalMs / DepartureMs > 0, IsTerminal, Pass), and PtPairText is compared with
# (a) PseudoTurnbackPairCodec.Publish of the same five-value records and the REAL list id the timeline computed, and (b) the vector ptpair with that list id substituted.
# The Current sender (Class1.cs) can not run offline: it is held by the source-shape checks of Test-PseudoTurnbackQualifier.ps1 and the shared Publish call (same text by construction).
# ASCII only. Usage: powershell -File Test-PseudoTurnbackAdapterParity.ps1 [-Root <repo root>]
param([string]$Root = '')
$ErrorActionPreference = 'Stop'
if ($Root -eq '') { $Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path }
$tel = Join-Path $Root 'TsScoringPlugin\Handshake\Telemetry'
$fail = 0; $pass = 0
function Check([bool]$ok, [string]$name) { if ($ok) { $script:pass++ } else { $script:fail++; Write-Output ('FAIL ' + $name) } }
$sources = @((Join-Path $tel 'Legacy\src\LegacyApi.cs'), (Join-Path $tel 'Legacy\src\LegacyStationTimeline.cs'))
$sources += (Get-ChildItem (Join-Path $tel 'Shared') -Filter *.cs | ForEach-Object { $_.FullName })
foreach ($s in $sources) { if (-not (Test-Path -LiteralPath $s)) { Write-Output ('MISSING ' + $s); Write-Output 'RESULT FAIL missing-source'; exit 1 } }
$harness = @'
namespace TSScoringPlugin.Telemetry {
  public static class PtParityHarness {
    // returns { PtPairText (or "<null>"), ListId, Publish(records after the first-terminal rule, ListId) (or "<null>") }
    public static string[] Run(int[] flat) {
      System.Collections.Generic.List<LegacyStationRaw> raw = new System.Collections.Generic.List<LegacyStationRaw>();
      int n = flat.Length / 4;
      for (int i = 0; i < n; i++) {
        LegacyStationRaw r = new LegacyStationRaw();
        r.Name = "S" + i;
        r.Location = 1000.0 * (i + 1);
        r.ArrivalMs = flat[i * 4] != 0 ? 36000000 + i * 600000 : -1;
        r.DepartureMs = flat[i * 4 + 1] != 0 ? 36000000 + i * 600000 + 30000 : -1;
        r.IsTerminal = flat[i * 4 + 2] != 0;
        r.Pass = flat[i * 4 + 3] != 0;
        r.DoorSide = 1; r.DefaultMs = -1; r.StoppageMs = 15000; r.MarginMin = 5.0; r.MarginMax = 5.0;
        raw.Add(r);
      }
      LegacyStationTimeline t = new LegacyStationTimeline();
      t.Step(raw, raw.Count, 0.0, 0.0, 0, true);
      // the expected records: the same five values, the first explicit terminal only (what the timeline's own dedupe leaves)
      System.Collections.Generic.List<PseudoTurnbackRecord> recs = new System.Collections.Generic.List<PseudoTurnbackRecord>();
      bool seen = false;
      for (int i = 0; i < n; i++) {
        bool term = flat[i * 4 + 2] != 0;
        if (term) { if (seen) term = false; else seen = true; }
        recs.Add(new PseudoTurnbackRecord(flat[i * 4] != 0, flat[i * 4 + 1] != 0, term, flat[i * 4 + 3] != 0));
      }
      string pub = PseudoTurnbackPairCodec.Publish(recs, t.ListId);
      return new string[] { t.PtPairText == null ? "<null>" : t.PtPairText, t.ListId, pub == null ? "<null>" : pub };
    }
  }
}
'@
$hpath = Join-Path ([IO.Path]::GetTempPath()) ('PtParity_' + [Guid]::NewGuid().ToString('N') + '.cs')
[IO.File]::WriteAllText($hpath, $harness, (New-Object Text.UTF8Encoding($false)))
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.GenerateInMemory = $true; $cp.TreatWarningsAsErrors = $false
[void]$cp.ReferencedAssemblies.Add('System.dll'); [void]$cp.ReferencedAssemblies.Add('System.Core.dll')
try { Add-Type -Path ($sources + $hpath) -CompilerParameters $cp } catch { Write-Output ('INCONCLUSIVE compile: ' + $_.Exception.Message); exit 2 } finally { Remove-Item $hpath -ErrorAction SilentlyContinue }
Add-Type -AssemblyName System.Web.Extensions
$ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
$ser.MaxJsonLength = 67108864
$vec = $ser.DeserializeObject([IO.File]::ReadAllText((Join-Path $Root 'tests\pt_vectors.json'), [Text.Encoding]::UTF8))
$checked = 0
foreach ($c in $vec['qualifier']) {
    $flat = New-Object System.Collections.Generic.List[int]
    $terms = 0
    foreach ($r in $c['records']) { foreach ($x in $r) { $flat.Add([int]$x) }; if ([int]$r[2] -ne 0) { $terms++ } }
    $res = [TSScoringPlugin.Telemetry.PtParityHarness]::Run($flat.ToArray())
    $text = $res[0]; $listId = $res[1]; $pub = $res[2]
    if ($flat.Count -eq 0) {
        Check ($text -ceq '<null>') ('parity ' + $c['id'] + ' empty list publishes no part, got=' + $text)
        continue
    }
    $checked++
    Check ($text -ceq $pub) ('parity ' + $c['id'] + ' PtPairText got=' + $text + ' expect=' + $pub)
    Check ($text -cne '<null>') ('parity ' + $c['id'] + ' a non-empty list always publishes a part')
    if ($terms -le 1) {
        # the vector text with the real list id (CRC-32 of the STALIST payload of this list)
        $parts = $c['ptpair'].Split(':')
        $parts[2] = $listId
        Check ($text -ceq ($parts -join ':')) ('parity ' + $c['id'] + ' vector text with the real list id, got=' + $text + ' vector=' + $c['ptpair'])
    }
}
Check ($checked -gt 0) 'parity checked at least one non-empty vector'
Write-Output ('PASS ' + $pass + ' FAIL ' + $fail)
if ($fail -eq 0) { Write-Output 'RESULT PASS'; exit 0 } else { Write-Output 'RESULT FAIL'; exit 1 }
