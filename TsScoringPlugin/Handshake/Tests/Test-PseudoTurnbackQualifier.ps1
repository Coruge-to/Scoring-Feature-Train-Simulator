# PR-1a / PR-1b: compiles the shared Pair / Qualifier / PTPAIR codec sources in isolation (no host, no BVE) and runs tests/pt_vectors.json against them.
# ASCII only. Usage: powershell -File Test-PseudoTurnbackQualifier.ps1 [-Root <repo root>]
param([string]$Root = '')
$ErrorActionPreference = 'Stop'
if ($Root -eq '') { $Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path }
# Stage TB-A: the sources are staged OUTSIDE Shared\ (the package guard rejects a Shared source that no project compiles); Stage TB-E moves them to Shared\ and adds the Compile items
$shared = Join-Path $Root 'TsScoringPlugin\Handshake\Telemetry\PseudoTurnbackStaging'
$files = @('PseudoTurnbackQualifier.cs', 'PseudoTurnbackPairCodec.cs')
$fail = 0; $pass = 0
function Check([bool]$ok, [string]$name) { if ($ok) { $script:pass++ } else { $script:fail++; Write-Output ('FAIL ' + $name) } }
foreach ($f in $files) { if (-not (Test-Path (Join-Path $shared $f))) { Write-Output ('MISSING ' + $f); Write-Output 'RESULT FAIL missing-source'; exit 1 } }
$harness = @'
namespace TSScoringPlugin.Telemetry {
  public static class PtHarness {
    public static string Qualify(int[] flat, string listId) {
      System.Collections.Generic.List<PseudoTurnbackRecord> recs = new System.Collections.Generic.List<PseudoTurnbackRecord>();
      for (int i = 0; i + 3 < flat.Length; i += 4) recs.Add(new PseudoTurnbackRecord(flat[i] != 0, flat[i + 1] != 0, flat[i + 2] != 0, flat[i + 3] != 0));
      PseudoTurnbackPairSet s = PseudoTurnbackQualifier.Qualify(recs);
      return PseudoTurnbackPairCodec.Encode(s, listId);
    }
    public static string Decode(string text, int expected) {
      string id, reason;
      PseudoTurnbackPairSet s = PseudoTurnbackPairCodec.TryDecode(text, expected, out id, out reason);
      if (s == null) return "NG:" + reason;
      System.Text.StringBuilder sb = new System.Text.StringBuilder();
      for (int i = 0; i < s.Count; i++) { if (i > 0) sb.Append(';'); sb.Append(s[i].ArrivalStationIndex).Append('-').Append(s[i].DepartureStationIndex).Append('-').Append((int)s[i].CompletionMode); }
      return "OK:" + id + ":" + s.StationCount + ":" + sb.ToString();
    }
  }
}
'@
$hpath = Join-Path ([IO.Path]::GetTempPath()) ('PtHarness_' + [Guid]::NewGuid().ToString('N') + '.cs')
[IO.File]::WriteAllText($hpath, $harness, (New-Object Text.UTF8Encoding($false)))
$paths = @(); foreach ($f in $files) { $paths += (Join-Path $shared $f) }; $paths += $hpath
try { Add-Type -Path $paths } finally { Remove-Item $hpath -ErrorAction SilentlyContinue }
Add-Type -AssemblyName System.Web.Extensions
$ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
$ser.MaxJsonLength = 67108864
$vec = $ser.DeserializeObject([IO.File]::ReadAllText((Join-Path $Root 'tests\pt_vectors.json'), [Text.Encoding]::UTF8))
foreach ($c in $vec['qualifier']) {
    $flat = New-Object System.Collections.Generic.List[int]
    foreach ($r in $c['records']) { foreach ($x in $r) { $flat.Add([int]$x) } }
    $got = [TSScoringPlugin.Telemetry.PtHarness]::Qualify($flat.ToArray(), $vec['list_id'])
    Check ($got -ceq $c['ptpair']) ('qualifier ' + $c['id'] + ' got=' + $got + ' expect=' + $c['ptpair'])
}
foreach ($c in $vec['codec_valid']) {
    $got = [TSScoringPlugin.Telemetry.PtHarness]::Decode($c['text'], [int]$c['expect_count'])
    $parts = @(); foreach ($p in $c['pairs']) { $parts += ([string]$p[0] + '-' + [string]$p[1] + '-' + [string]$p[2]) }
    $n = $c['expect_count']; if ($n -lt 0) { $n = $c['text'].Split(':')[3] }
    $expect = 'OK:' + $c['list_id'] + ':' + $n + ':' + ($parts -join ';')
    Check ($got -ceq $expect) ('codec-valid ' + $c['text'] + ' got=' + $got + ' expect=' + $expect)
}
foreach ($c in $vec['codec_invalid']) {
    $got = [TSScoringPlugin.Telemetry.PtHarness]::Decode($c['text'], [int]$c['expect_count'])
    Check ($got -ceq ('NG:' + $c['reason'])) ('codec-invalid ' + $c['text'] + ' got=' + $got + ' expect=NG:' + $c['reason'])
}
# source pins: the Qualifier input type has exactly the five raw values; no forbidden identifiers anywhere in the shared sources
$bad = @('door', 'signal', 'distance', 'location', 'speed', 'Math.Abs', '\bnames?\b')
foreach ($f in $files) {
    $text = [IO.File]::ReadAllText((Join-Path $shared $f), [Text.Encoding]::UTF8)
    $code = ($text -split "`n" | Where-Object { $_.TrimStart() -notmatch '^//' -and $_.TrimStart() -notmatch '^///' }) -join "`n"
    foreach ($b in $bad) { Check (-not [regex]::IsMatch($code, $b, 'IgnoreCase')) ('pin ' + $f + ' has no ' + $b) }
}
Write-Output ('PASS ' + $pass + ' FAIL ' + $fail)
if ($fail -eq 0) { Write-Output 'RESULT PASS'; exit 0 } else { Write-Output 'RESULT FAIL'; exit 1 }
