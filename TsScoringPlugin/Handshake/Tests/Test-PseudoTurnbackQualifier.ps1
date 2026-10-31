# PR-1a / PR-1b: compiles the shared Pair / Qualifier / PTPAIR codec sources in isolation (no host, no BVE) and runs tests/pt_vectors.json against them.
# ASCII only. Usage: powershell -File Test-PseudoTurnbackQualifier.ps1 [-Root <repo root>]
param([string]$Root = '')
$ErrorActionPreference = 'Stop'
if ($Root -eq '') { $Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path }
# Stage TB-E: the two sources live in Telemetry\Shared (compiled by BOTH the Current and the Legacy project; they were staged outside Shared\ in TB-A..TB-D)
$shared = Join-Path $Root 'TsScoringPlugin\Handshake\Telemetry\Shared'
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
    public static string Publish(int[] flat, string listId) {
      System.Collections.Generic.List<PseudoTurnbackRecord> recs = new System.Collections.Generic.List<PseudoTurnbackRecord>();
      for (int i = 0; i + 3 < flat.Length; i += 4) recs.Add(new PseudoTurnbackRecord(flat[i] != 0, flat[i + 1] != 0, flat[i + 2] != 0, flat[i + 3] != 0));
      return PseudoTurnbackPairCodec.Publish(recs, listId);
    }
    public static string PublishNull(string listId) { return PseudoTurnbackPairCodec.Publish(null, listId); }
    // a list whose indexer throws: Publish must swallow it and answer null (no part)
    private sealed class ThrowingList : System.Collections.Generic.IList<PseudoTurnbackRecord> {
      public PseudoTurnbackRecord this[int index] { get { throw new System.InvalidOperationException("boom"); } set { } }
      public int Count { get { return 3; } }
      public bool IsReadOnly { get { return true; } }
      public void Add(PseudoTurnbackRecord item) { }
      public void Clear() { }
      public bool Contains(PseudoTurnbackRecord item) { return false; }
      public void CopyTo(PseudoTurnbackRecord[] array, int arrayIndex) { }
      public System.Collections.Generic.IEnumerator<PseudoTurnbackRecord> GetEnumerator() { throw new System.InvalidOperationException("boom"); }
      System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() { throw new System.InvalidOperationException("boom"); }
      public int IndexOf(PseudoTurnbackRecord item) { return -1; }
      public void Insert(int index, PseudoTurnbackRecord item) { }
      public bool Remove(PseudoTurnbackRecord item) { return false; }
      public void RemoveAt(int index) { }
    }
    public static string PublishThrowing(string listId) { return PseudoTurnbackPairCodec.Publish(new ThrowingList(), listId); }
    public static string PublishEmpty(string listId) { return PseudoTurnbackPairCodec.Publish(new System.Collections.Generic.List<PseudoTurnbackRecord>(), listId); }
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
    $pub = [TSScoringPlugin.Telemetry.PtHarness]::Publish($flat.ToArray(), $vec['list_id'])
    Check ($pub -ceq $c['ptpair']) ('publish ' + $c['id'] + ' got=' + $pub + ' expect=' + $c['ptpair'])
}
# TB-E: Publish is the adapter entry (Encode(Qualify(records), listId)); any failure is null = no PTPAIR part
Check ($null -eq [TSScoringPlugin.Telemetry.PtHarness]::PublishNull($vec['list_id'])) 'publish null records is null'
Check (([TSScoringPlugin.Telemetry.PtHarness]::PublishEmpty($vec['list_id'])) -ceq 'PTPAIR:1:00000000:0:0:') 'publish empty list is PTPAIR:1:00000000:0:0:'
$thrown = $false; $thrownValue = 'x'
try { $thrownValue = [TSScoringPlugin.Telemetry.PtHarness]::PublishThrowing($vec['list_id']) } catch { $thrown = $true }
Check (-not $thrown) 'publish never throws on a throwing list'
Check ($null -eq $thrownValue) 'publish of a throwing list is null'
$thrown = $false
try { [void][TSScoringPlugin.Telemetry.PtHarness]::Publish((New-Object 'int[]' 3), 'zz') } catch { $thrown = $true }
Check (-not $thrown) 'publish never throws on a degenerate flat array and a bad list id'
Check (([TSScoringPlugin.Telemetry.PtHarness]::Publish((New-Object 'int[]' 3), 'zz')) -ceq 'PTPAIR:1:00000000:0:0:') 'publish with an invalid list id falls back to the empty id (Encode rule)'
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
# TB-E source-shape pins of the two adapters (the Current sender can not run offline): the seam position, the five values only, one Publish call, the same condition as STIDX
function Read-Src([string]$rel) { [IO.File]::ReadAllText((Join-Path $Root $rel), [Text.Encoding]::UTF8) }
function Count-Of([string]$text, [string]$literal) { [regex]::Matches($text, [regex]::Escape($literal)).Count }
$cur = Read-Src 'TsScoringPlugin\TsScoringPlugin\Class1.cs'
$five = 'new TSScoringPlugin.Telemetry.PseudoTurnbackRecord(stationList[i].RawArrTime > 0, stationList[i].RawDepTime > 0, stationList[i].IsTerminal, stationList[i].IsPass)'
Check ((Count-Of $cur 'PseudoTurnbackPairCodec.Publish(') -eq 1) 'Current: exactly one Publish call'
Check ((Count-Of $cur 'new TSScoringPlugin.Telemetry.PseudoTurnbackRecord(') -eq 1) 'Current: exactly one record construction'
Check ((Count-Of $cur $five) -eq 1) 'Current: the record reads only RawArrTime, RawDepTime, IsTerminal, IsPass'
$iLoop = $cur.IndexOf('stationList[i].IsTerminal = false;'); $iSeam = $cur.IndexOf('ptRecords = new List<'); $iNoT = $cur.IndexOf('stationList[stationList.Count - 1].IsTerminal = true;')
Check (($iLoop -gt 0) -and ($iSeam -gt $iLoop) -and ($iNoT -gt $iSeam)) 'Current: the records are taken after the first-terminal loop and before the last-station-is-terminal fill'
$iPub = $cur.IndexOf('PseudoTurnbackPairCodec.Publish(ptRecords, stidxListId)'); $iId = $cur.IndexOf('stidxListId = staInfoList.Count > 0 ?')
Check (($iId -gt 0) -and ($iPub -gt $iId) -and (($iPub - $iId) -lt 400)) 'Current: Publish follows the stidxListId assignment (STALIST block, with the same list id)'
$iStidx = $cur.IndexOf('data += ",STIDX:1:"'); $iAdd = $cur.IndexOf('if (ptpairText != null) data += "," + ptpairText;'); $iOff = $cur.IndexOf('OfficialTargetWire.Key')
Check (($iStidx -gt 0) -and ($iAdd -gt $iStidx) -and ($iOff -gt $iAdd) -and (($iOff - $iStidx) -lt 1500)) 'Current: the PTPAIR part is appended right after STIDX and before OFFTGT'
$iCond = $cur.LastIndexOf('if (isInitialized && stidxListReady && stidxListCount == stationList.Count)', $iStidx)
Check (($iCond -gt 0) -and (($iStidx - $iCond) -lt 200) -and ($iAdd -gt $iCond)) 'Current: the PTPAIR part is under the same condition as STIDX'
Check ((Count-Of $cur 'ptRecords = null; ptpairText = null;') -eq 2) 'Current: both stidxListId resets also clear ptRecords and ptpairText'
$leg = Read-Src 'TsScoringPlugin\Handshake\Telemetry\Legacy\src\LegacyStationTimeline.cs'
$fiveLeg = 'new PseudoTurnbackRecord(list[i].RawArrTime > 0, list[i].RawDepTime > 0, list[i].IsTerminal, list[i].IsPass)'
Check ((Count-Of $leg 'PseudoTurnbackPairCodec.Publish(') -eq 1) 'Legacy: exactly one Publish call'
Check ((Count-Of $leg 'new PseudoTurnbackRecord(') -eq 1) 'Legacy: exactly one record construction'
Check ((Count-Of $leg $fiveLeg) -eq 1) 'Legacy: the record reads only RawArrTime, RawDepTime, IsTerminal, IsPass'
$lLoop = $leg.IndexOf('list[i].IsTerminal = false;'); $lSeam = $leg.IndexOf('ptRecords = new List<'); $lNoT = $leg.IndexOf('list[list.Count - 1].IsTerminal = true;')
Check (($lLoop -gt 0) -and ($lSeam -gt $lLoop) -and ($lNoT -gt $lSeam)) 'Legacy: the records are taken after the first-terminal loop and before the last-station-is-terminal fill'
$lId = $leg.IndexOf('listId = payload == null'); $lPub = $leg.IndexOf('PseudoTurnbackPairCodec.Publish(ptRecords, listId)')
Check (($lId -gt 0) -and ($lPub -gt $lId)) 'Legacy: Publish follows the listId computation (end of Build)'
Check ((Count-Of $leg 'ptRecords = null; ptPairText = null;') -eq 1) 'Legacy: Reset clears ptRecords and ptPairText'
Check ($leg -match 'internal string PtPairText \{ get \{ return ptPairText; \} \}') 'Legacy: PtPairText accessor'
$ses = Read-Src 'TsScoringPlugin\Handshake\Telemetry\Legacy\src\LegacyTelemetrySession.cs'
$sStidx = $ses.IndexOf('"STIDX", StationIndexWire.Value('); $sKey = $ses.IndexOf('if (timeline.PtPairText != null) lb.Key("PTPAIR", timeline.PtPairText.Substring("PTPAIR:".Length));'); $sOff = $ses.IndexOf('if (official != null)', $sStidx)
Check (($sStidx -gt 0) -and ($sKey -gt $sStidx) -and ($sOff -gt $sKey)) 'Legacy: the PTPAIR key is written right after the STIDX key of the station group and before OFFTGT, only when PtPairText is not null'
Write-Output ('PASS ' + $pass + ' FAIL ' + $fail)
if ($fail -eq 0) { Write-Output 'RESULT PASS'; exit 0 } else { Write-Output 'RESULT FAIL'; exit 1 }
