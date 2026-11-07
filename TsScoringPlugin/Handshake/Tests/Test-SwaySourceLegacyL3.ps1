# Legacy sway SOURCE lookup - offline tests of LegacySwaySourceFinder / LegacySwayProvider (src\LegacySwaySource.cs). No BVE, no AtsEX, no BveEx, no network, no hooks.
# The real built Legacy telemetry DLL is loaded from memory and driven with FAKE hosts and FAKE raw structures (tests\SwaySourceFakes.cs + tests\SwayFakeTypes.cs, compiled here).
# Nothing is written outside logs\sway-source-tests. This script is ASCII-only on purpose.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$testDir = Join-Path $Root 'logs\sway-source-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }

$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
$compiled = $true
try {
    # the two fixture files are compiled together as ONE source: the using lines are collected at the top, the rest follows
    $usings = New-Object System.Collections.Generic.SortedSet[string]; $body = New-Object System.Text.StringBuilder
    foreach ($name in 'SwayFakeTypes.cs', 'SwaySourceFakes.cs') {
        foreach ($line in [IO.File]::ReadAllLines((Join-Path $Root ('Tests\' + $name)))) {
            if ($line -match '^using [A-Za-z0-9_.]+;\s*$') { [void]$usings.Add($line.Trim()) } else { [void]$body.AppendLine($line) }
        }
    }
    $combined = ((@($usings) -join "`r`n") + "`r`n" + $body.ToString())
    Add-Type -TypeDefinition $combined -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library -ErrorAction Stop
    Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class SwaySourceResolver
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
    [SwaySourceResolver]::Install(@($testDir, $legacyHost))
    $null = [Reflection.Assembly]::LoadFrom($dllCopy)
    $null = [Reflection.Assembly]::LoadFrom($fixtureDll)
} catch {
    $compiled = $false
    Check 'LS00 the fixture compiles against the telemetry DLL (LegacySwaySourceFinder, LegacySwayProvider and their API exist)' $false
    ("compile error: " + $_.Exception.Message.Substring(0, [Math]::Min(400, $_.Exception.Message.Length)))
}

$V5 = '5.8.7554.391'
$V6 = '6.0.7554.619'
function NewHost() { return (New-Object TsScoringSwayFakes.FakeSwayHost) }
function Figure() { return [TsScoringSwayFakes.SwayFake]::Ok(0.01, 0.02, 0.03, 0.04) }

if ($compiled) {
    # ---------------------------------------------------------------- the wrapper path, stage by stage
    $h = NewHost; $h.MainFormMode = 'null'; $h.RawForm = $null; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS01 wrapper MainForm null: stage mainform-null, mainform_null set, nothing found' (($f.WrapperStage -eq 'mainform-null') -and $f.WrapperMainFormNull -and ($f.Figure -eq $null) -and ($f.SelectedPath -eq 'none'))
    $h = NewHost; $h.DrawerMode = 'null'; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS02 wrapper AssistantDrawer null: stage assistantdrawer-null, assistantdrawer_null set' (($f.WrapperStage -eq 'assistantdrawer-null') -and $f.WrapperDrawerNull)
    $h = NewHost; $h.ItemsMode = 'null'; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS03 wrapper Items null: stage items-null, items_null set' (($f.WrapperStage -eq 'items-null') -and $f.WrapperItemsNull)
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $h.Items.FailMode = 'invalid-operation'; $h.Items.FailAt = 4; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS04 wrapper Items enumeration failure: stage items-enumeration-failure, the exception TYPE is recorded, the 4 items before the failure are counted, the figure is NOT used' (($f.WrapperStage -eq 'items-enumeration-failure') -and ($f.WrapperException -eq 'System.InvalidOperationException') -and ($f.WrapperCount -eq 4) -and ($f.SelectedPath -eq 'none' -or $f.SelectedPath -eq 'raw-list'))
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $h.Items.FailMode = 'invalid-cast'; $h.Items.FailAt = 2; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS05 wrapper type cast failure: stage type-cast-failure with System.InvalidCastException' (($f.WrapperStage -eq 'type-cast-failure') -and ($f.WrapperException -eq 'System.InvalidCastException'))
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $h.Items.FailMode = 'null-ref'; $h.Items.FailAt = 0; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS05b the SHD-L-01 failure shape (a NullReferenceException while the items are walked) is classified, recorded by type name and is not hidden' (($f.WrapperStage -eq 'items-enumeration-failure') -and ($f.WrapperException -eq 'System.NullReferenceException'))
    $h = NewHost; $fig = Figure; $h.FillWrapper($fig, $true, 10); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS06 wrapper item count and item type names are recorded (10 items, 10 names)' (($f.WrapperCount -eq 10) -and (($f.WrapperNames -split ',').Count -eq 10) -and ($f.WrapperNames -match 'WrapperItemFake'))
    Check 'LS07 wrapper SwayGauge found: selected_path wrapper, the very object, the RAW path was NOT run' (($f.SelectedPath -eq 'wrapper') -and [object]::ReferenceEquals($f.Figure, $fig) -and ($f.FailureStage -eq 'none') -and (-not $f.RawTried) -and ($h.RawCalls -eq 0) -and $f.WrapperSway)
    $h = NewHost; $h.FillWrapper((Figure), $false, 10); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS08 wrapper without a SwayGauge: stage no-sway-item, sway_found 0 (then the raw path is tried)' (($f.WrapperStage -eq 'no-sway-item') -and (-not $f.WrapperSway) -and $f.RawTried)

    # ---------------------------------------------------------------- the raw-list path (only when the wrapper path failed)
    $rawFig = Figure
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw($rawFig, $true, 10); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS09 wrapper failed, raw list succeeds: selected_path raw-list, the figure is the b4 of the raw list' (($f.SelectedPath -eq 'raw-list') -and [object]::ReferenceEquals($f.Figure, $rawFig) -and ($f.FailureStage -eq 'none') -and $f.RawSway)
    Check 'LS10 raw diagnostics: the runtime types of the main form, the drawer and the items, the count and the item type names' (($f.RawMainFormType -eq 'bz') -and ($f.RawDrawerType -eq 'ar') -and ($f.RawItemsType -match '^List') -and ($f.RawCount -eq 10) -and ($f.RawNames -match 'b4') -and ($f.RawNames -match 'aw'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS11 raw main form null: stage mainform-null, both failed = none, never a figure' (($f.RawStage -eq 'mainform-null') -and ($f.SelectedPath -eq 'none') -and ($f.Figure -eq $null) -and ($f.FailureStage -eq 'mainform-null'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = (New-Object TsScoringSwayFakes.bzNoDrawerField); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS12 raw: no field l on the main form is a field-signature mismatch (no member search)' (($f.RawStage -eq 'field-signature-mismatch') -and ($f.SelectedPath -eq 'none'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = (New-Object TsScoringSwayFakes.bzWrongFieldType); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS13 raw: field l of another type than ar is a field-signature mismatch' ($f.RawStage -eq 'field-signature-mismatch')
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = (New-Object TsScoringSwayFakes.bzWithArNoMethod); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS14 raw: a drawer without the method a() is a field-signature mismatch' ($f.RawStage -eq 'field-signature-mismatch')
    $bzx = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $true, 10); [TsScoringSwayFakes.FakeSwayHost]::DrawerOf($bzx).Mode = 'null'
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $bzx; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS15 raw: the items method returns null: stage items-null' ($f.RawStage -eq 'items-null')
    $bzx = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $true, 10); [TsScoringSwayFakes.FakeSwayHost]::DrawerOf($bzx).Mode = 'throw'
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $bzx; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS16 raw: an exception inside the items method is recorded by TYPE (SecretFailure, not its message) and is a reflection-exception' (($f.RawStage -eq 'reflection-exception') -and ($f.RawException -match 'SecretFailure') -and ($f.SelectedPath -eq 'none'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $false, 10); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS17 raw list without a b4: stage no-sway-item, raw_sway_found 0' (($f.RawStage -eq 'no-sway-item') -and (-not $f.RawSway))

    # ---------------------------------------------------------------- wrapper wins, raw is never mixed in
    $wrapperFig = Figure; $rawFig2 = Figure
    $h = NewHost; $h.FillWrapper($wrapperFig, $true, 10); $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw($rawFig2, $true, 10); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS18 wrapper succeeds while a raw list ALSO has a figure: the wrapper figure is used, the raw path is not run, no value is mixed' (([object]::ReferenceEquals($f.Figure, $wrapperFig)) -and (-not [object]::ReferenceEquals($f.Figure, $rawFig2)) -and ($h.RawCalls -eq 0) -and ($f.SelectedPath -eq 'wrapper'))
    $h = NewHost; $h.FillWrapper($wrapperFig, $true, 10); $h.Items.FailMode = 'invalid-operation'; $h.Items.FailAt = 9; $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw($rawFig2, $true, 10); $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS19 wrapper fails after it saw the figure (the walk did not complete), raw succeeds: the RAW figure is adopted, the wrapper figure is not' (([object]::ReferenceEquals($f.Figure, $rawFig2)) -and ($f.SelectedPath -eq 'raw-list'))

    # ---------------------------------------------------------------- the provider: reader, retry, cache, boundary, diagnostics, release
    $scn1 = New-Object object; $scn2 = New-Object object
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true)
    $ok = $p.Tick($scn1)
    Check 'LS20 wrapper success through the provider: the reader is Ok and the four raw states are delivered (SWAY would be sent)' ($ok -and ($p.Status -eq 'Ok') -and ($p.LastRead -eq '0.01|0.02|0.03|0.04') -and ($p.LastDiagnostic -eq 'ok:5.8.7554.391:legacy'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $ok = $p.Tick($scn1)
    Check 'LS21 both paths failed: unavailable stays (Pending, no read, no 0, the diagnostic stays pending:no-source)' ((-not $ok) -and ($p.Status -eq 'Pending') -and ($p.LastRead -eq 'none') -and ($p.LastDiagnostic -match '^pending:5\.8\.7554\.391:legacy:no-source'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $ok = $p.Tick($scn1)
    Check 'LS22 wrapper failed, raw succeeded: the provider uses the raw figure (reader Ok) and says selected_path=raw-list' ($ok -and ($p.Status -eq 'Ok') -and ($p.LineOf('summary', 0) -match 'selected_path=raw-list'))
    # 30-Tick retry
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true)
    $p.Ticks($scn1, 1); $a1 = $p.FindAttempts; $p.Ticks($scn1, 29); $a2 = $p.FindAttempts; $p.Ticks($scn1, 1); $a3 = $p.FindAttempts; $p.Ticks($scn1, 59); $a4 = $p.FindAttempts
    Check 'LS23 an unresolved source is looked for on the 1st Tick and then on every 30th Tick only (1, 1, 2, 3 attempts after 1, 30, 31, 90 Ticks)' (($a1 -eq 1) -and ($a2 -eq 1) -and ($a3 -eq 2) -and ($a4 -eq 3))
    # diagnostic once per scenario
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 300)
    Check 'LS24 the same failure is logged ONCE per scenario (300 Ticks, 10 attempts, one summary line, one line of each role)' (($p.FindAttempts -eq 10) -and ($p.CountLines('summary') -eq 1) -and ($p.CountLines('wrapper') -eq 1) -and ($p.CountLines('raw') -eq 1) -and ($p.CountLines('exception') -eq 1) -and ($p.CountLines('reader') -eq 1))
    $p.Ticks($scn2, 5)
    Check 'LS25 a new scenario instance (generation change, F5, reload) resolves again and logs its own diagnostic' (($p.Generation -eq 2) -and ($p.CountLines('summary') -eq 2) -and ($p.LineOf('summary', 1) -match 'gen=2'))
    # failure -> success logs the change, then the cache holds
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 31)
    $h.MainFormMode = 'ok'; $h.FillWrapper((Figure), $true, 10); $p.Ticks($scn1, 30)
    Check 'LS26 a failure that turns into a success is logged as a CHANGE (two summaries), then the source is cached (no further look-up)' (($p.Status -eq 'Ok') -and ($p.CountLines('summary') -eq 2) -and ($p.LineOf('summary', 1) -match 'selected_path=wrapper'))
    $att = $p.FindAttempts; $p.Ticks($scn1, 200)
    Check 'LS27 after a success the source is cached: 200 more Ticks do not look it up again (and read the states every Tick)' (($p.FindAttempts -eq $att) -and ($p.LastRead -eq '0.01|0.02|0.03|0.04'))
    $p.Ticks($scn2, 1)
    Check 'LS28 the cache is dropped at a scenario boundary (generation change looks the source up again)' (($p.FindAttempts -eq ($att + 1)) -and ($p.Generation -eq 2))
    # session regeneration
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $p1 = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p1.Ticks($scn1, 3)
    $p2 = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p2.Ticks($scn1, 1)
    Check 'LS29 a new provider (a regenerated session) starts without the cache of the old one and looks the source up itself' (($p2.FindAttempts -eq 1) -and ($p2.Generation -eq 1) -and ($p2.Status -eq 'Ok'))
    # release
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 3); $calls = $h.WrapperCalls; $p.Release(); $ok = $p.Tick($scn1); $p.Ticks($scn2, 40)
    Check 'LS30 Dispose/Release drops everything: no read, no host call after it, the reader binding is forgotten' ((-not $ok) -and $p.Released -and ($h.WrapperCalls -eq $calls) -and ($p.Status -eq 'Pending'))
    # unknown version
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe('5.9.0.1', $h, $true); $ok = $p.Tick($scn1)
    Check 'LS31 an unknown BVE version is disabled: no member of the host is touched (0 wrapper calls, 0 raw calls), no figure, the failure stage is version-mismatch' ((-not $ok) -and ($h.WrapperCalls -eq 0) -and ($h.RawCalls -eq 0) -and ($p.Status -eq 'VersionUnsupported') -and ($p.LineOf('summary', 0) -match 'failure_stage=version-mismatch'))
    $h = NewHost; $p = New-Object TsScoringSwayFakes.ProviderProbe('unknown', $h, $true); $null = $p.Tick($scn1)
    Check 'LS32 a version that could not be read is not an audited version either (nothing touched)' (($h.WrapperCalls -eq 0) -and ($h.RawCalls -eq 0) -and ($p.Status -eq 'VersionUnsupported'))
    # diagnostics contract
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $h.Items.FailMode = 'secret'; $h.Items.FailAt = 1; $h.RawMode = 'throw'; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 1)
    $all = $p.AllLines()
    Check 'LS33 the exception MESSAGE and the stack never appear (the secret text, "   at ", ToString-style text are absent; the TYPE names are present)' (($all -notmatch 'SECRET-MESSAGE') -and ($all -notmatch '   at ') -and ($all -notmatch 'StackTrace') -and ($all -match 'SecretFailure'))
    Check 'LS34 every diagnostic line is within 150 characters' ($p.MaxLineLength() -le 150)
    $h = NewHost; $big = Figure; $h.FillWrapper($big, $false, 40); $h.RawForm = $null; $h.MainFormMode = 'ok'; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 1)
    Check 'LS35 many type names: the line still fits under the cap and what was left out is COUNTED (names_cut=N), never cut silently' (($p.MaxLineLength() -le 150) -and ($p.LineOf('wrapper', 0) -match 'names_cut=\d+') -and ($p.LineOf('wrapper', 0) -match 'items_count=40'))
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 1)
    $needed = @('bve_version=5.8.7554.391', 'entry=legacy', 'selected_path=none', 'failure_stage=', 'exception_type=', 'mainform_null=', 'assistantdrawer_null=', 'items_null=', 'items_count=', 'sway_found=', 'mainform_type=', 'assistantdrawer_type=', 'items_type=')
    $miss = @($needed | Where-Object { $p.AllLines() -notmatch [regex]::Escape($_) })
    Check 'LS36 all the required diagnostic fields are present (bve_version, entry, wrapper_*, raw_*, selected_path, failure_stage, exception_type)' ($miss.Count -eq 0)
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $false); $ok = $p.Tick($scn1)
    Check 'LS37 without a diagnostic sink everything still works (null sink)' ($ok -and ($p.Status -eq 'Ok'))
    # fail-closed reader: a found object that is not the audited structure
    $h = NewHost; $bad = [TsScoringSwayFakes.SwayFake]::Make('bad-omega'); $h.FillWrapper($bad, $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $ok = $p.Tick($scn1)
    Check 'LS38 a figure with a wrong signature is refused by the reader (StructureMismatch): nothing is read, the stage is field-signature-mismatch' ((-not $ok) -and ($p.Status -eq 'StructureMismatch') -and ($p.LineOf('summary', 0) -match 'failure_stage=field-signature-mismatch'))
    # read only
    $o5 = [TsScoringSwayFakes.SwayFake]::Ok(0.01, 0.02, 0.03, 0.04); $before = [TsScoringSwayFakes.SwayFake]::Dump($o5)
    $h = NewHost; $h.FillWrapper($o5, $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 60)
    Check 'LS39 the lookup and the reads do not change the BVE state (the figure is byte-identical after 60 Ticks)' ([TsScoringSwayFakes.SwayFake]::Dump($o5) -eq $before)
    # a raw list that is read must not be modified
    $rawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $true, 10); $cnt = [TsScoringSwayFakes.FakeSwayHost]::DrawerOf($rawForm).Items.Count
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $rawForm; $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 40)
    Check 'LS40 the raw list is only read (same number of items after the look-ups)' ([TsScoringSwayFakes.FakeSwayHost]::DrawerOf($rawForm).Items.Count -eq $cnt)
    # the diagnostic must not lie: a failed look-up says sway_found=0 and the selected path none (a diagnostic that always says "found" would hide the failure again)
    $h = NewHost; $h.FillWrapper((Figure), $false, 10); $h.RawForm = [TsScoringSwayFakes.FakeSwayHost]::MakeRaw((Figure), $false, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 1)
    Check 'LS41 the diagnostic does not lie: both paths found no figure, so the lines say sway_found=0 (wrapper and raw), selected_path=none and the reader stays pending' (($p.LineOf('wrapper', 0) -match 'sway_found=0') -and ($p.LineOf('raw', 0) -match 'sway_found=0') -and ($p.LineOf('summary', 0) -match 'selected_path=none') -and ($p.Status -eq 'Pending'))
    $h = NewHost; $h.FillWrapper((Figure), $true, 10); $p = New-Object TsScoringSwayFakes.ProviderProbe($V5, $h, $true); $p.Ticks($scn1, 1)
    Check 'LS42 a success says so: sway_found=1 and selected_path=wrapper, the raw line says it was not run' (($p.LineOf('wrapper', 0) -match 'sway_found=1') -and ($p.LineOf('summary', 0) -match 'selected_path=wrapper') -and ($p.LineOf('raw', 0) -match 'stage=not-run'))    # the host reader: IBveHacker.MainFormSource read through the interface by name (no compile-time Forms reference, no reflection in the adapter)
    $formObj = New-Object object; $hk = New-Object TsScoringSwayFakes.FakeHacker; $hk.Form = $formObj
    Check 'LS43 the host reader returns the original main form object of an object that implements IBveHacker (the very object)' ([object]::ReferenceEquals([TsScoringSwayFakes.HostReaderProbe]::Read($hk), $formObj))
    Check 'LS44 the host reader returns null (and does not throw) for null, for an object without an IBveHacker interface and for an interface of another name' (([TsScoringSwayFakes.HostReaderProbe]::Read($null) -eq $null) -and ([TsScoringSwayFakes.HostReaderProbe]::Read((New-Object object)) -eq $null) -and ([TsScoringSwayFakes.HostReaderProbe]::Read((New-Object TsScoringSwayFakes.FakeHackerOtherName)) -eq $null))
    $hk2 = New-Object TsScoringSwayFakes.FakeHacker; $hk2.Throw = $true; $thrown = ''
    try { $null = [TsScoringSwayFakes.HostReaderProbe]::Read($hk2) } catch { $thrown = $_.Exception.InnerException.GetType().Name; if ($thrown -eq '') { $thrown = $_.Exception.GetType().Name } }
    Check 'LS45 a getter that throws is not swallowed by the host reader (the finder classifies it as a reflection exception and records its type)' ($thrown -match 'TargetInvocationException|SecretFailure')
    $h = NewHost; $h.MainFormMode = 'throw'; $h.RawForm = $null; $f = New-Object TsScoringSwayFakes.FinderProbe($h)
    Check 'LS46 the raw path takes the main form from the host access only (a host that returns null gives mainform-null, no member is searched)' ($f.RawStage -eq 'mainform-null')
}

$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"SWAY-SOURCE-LEGACY-L3 PASS=$pass FAIL=$fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
