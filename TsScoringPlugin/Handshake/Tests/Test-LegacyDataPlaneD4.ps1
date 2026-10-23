# PHASE PID-D4 / SLICE 1 - offline tests of the AtsEX LEGACY telemetry sender on the per-PID DataPlane.
# What is proven: (A) managed transmission - SCENARIO_ID / STATUS / STALIST / META become envelope types 1 / 2 / 3 / 4 in Envelope v1 on the Directory-published dynamic port,
# zero fixed 54321 plain sends, fail closed for every Directory state and ownership mismatch, endpoint changes never reuse the old destination, nothing after shutdown;
# (B) normal mode - the fixed 54321 plain path is byte for byte what the old sink sent, the managed Directory is never adopted; (C) the heartbeat (STATUS:LOADED:PAUSED) and the timer
# thread racing endpoint switches and Dispose; (D) the per-process diagnostic log name; (E) the real Python receiver, strict gate and Overlay take the Legacy datagrams and the HUD values
# arrive in the normalised state; (F) invariants - the Current DLL, the Current product sources, the three shared files, the Python product code, the fixed port 54322 and
# "the Legacy jump plane executes nothing" hold (PID-D4 / Legacy Jump 2A-alpha: only current_jump_client.py and dataplane_contract.py may differ; the three LegacyJump*.cs sources may exist, link the Current jump source once as a shared Link, never call CurrentJumpEndpoint.Create and name the fixed ports only in the one comparison list of LegacyJumpEndpoint.cs).
# No BVE, no AtsEX runtime, no BveEX. The real built DLL is loaded and driven through the fake Legacy API of Tests\TelemetryTestFixture.cs. The only operating system objects are
# synthetic named events / mappings of an unused high PID and loopback sockets this test owns; fixed UDP 54321 / 54322 are never bound or sent to. ASCII-only on purpose.
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$DllPath = ''
)

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if ([string]::IsNullOrEmpty($DllPath)) { $DllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll' }
$fixtures = @((Join-Path $Root 'Tests\TelemetryTestFixture.cs'), (Join-Path $Root 'Tests\LegacyDataPlaneTestFixture.cs'), (Join-Path $Root 'Tests\LegacyIlCallScan.cs'))
$testDir = Join-Path $Root 'logs\d4-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null
$golden = Join-Path $testDir 'golden'

$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }
function Near([double]$a, [double]$b, [double]$tol = 1e-6) { return [math]::Abs($a - $b) -le $tol }
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
function Sha([string]$path) { if (Test-Path -LiteralPath $path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash } else { return 'absent' } }

# ---------------------------------------------------------------------------------------------------------------------------------------------
Write-Host '--- A-E: the compiled checks (the real DLL, the real session, the real sink and routing core)'
$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $DllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
Add-Type -Path $fixtures -ReferencedAssemblies @($dllCopy, 'System.dll', 'System.Core.dll') -OutputAssembly $fixtureDll -OutputType Library
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class D4Resolver
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
[D4Resolver]::Install(@($testDir, $legacyHost))
$telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
$fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)
$fx = $fixAsm.GetType('TsScoringLegacyTelemetryTests.LegacyDataPlaneTestFixture')
$sw = [Diagnostics.Stopwatch]::StartNew()
$res = $fx.GetMethod('Run').Invoke($null, [object[]]@([string]$golden))
$checks = [string]$res[0]
$bad = @($res | Select-Object -Skip 1)
Write-Host ('compiled checks: ' + $checks + ' in ' + [int]$sw.Elapsed.TotalSeconds + ' s')
Check ('A01 every compiled check passed (' + $checks + ')') ($bad.Count -eq 0)
foreach ($b in $bad) { Write-Host ('  FAILED: ' + $b) }
Check 'A02 the compiled run produced the golden datagrams for the Python interop' ((Test-Path (Join-Path $golden 'legacy_manifest.txt')) -and (@(Get-ChildItem $golden -Filter 'legacy_*.bin').Count -ge 6))

# ---------------------------------------------------------------------------------------------------------------------------------------------
Write-Host '--- E: the real Python receiver, strict gate and Overlay take the Legacy datagrams (Python product code unchanged)'
$chk = Join-Path $repo 'tests\legacy_dataplane_chain_check.py'
$unit = 'test_legacy_dataplane_interop_d4.py'
$qtOk = $false
try { $qtOk = ((& python -c "import PyQt6.QtWidgets; print('ok')") -eq 'ok') } catch { $qtOk = $false }
$env:LEGACY_DATAPLANE_D4_GOLDEN = $golden
Push-Location $repo
try {
    $uo = (& python -I -m unittest discover -s tests -p $unit 2>&1 | Out-String)
    $unitOk = ($LASTEXITCODE -eq 0) -and ($uo -match 'Ran 5 tests') -and ($uo -match '(?m)^OK\s*$') -and ($uo -notmatch 'skipped')
    Check 'E01 the real TelemetryDataPlaneReceiver accepts every Legacy datagram with the exact text; types 1-4 present; envelopes are valid v1 with a zero RequestId' $unitOk
    if (-not $unitOk) { Write-Host $uo }
}
finally { Pop-Location; Remove-Item Env:\LEGACY_DATAPLANE_D4_GOLDEN -ErrorAction SilentlyContinue }
if ($qtOk -and (Test-Path $chk)) {
    Push-Location $repo
    try { $raw = (& python $chk $golden | Out-String) } finally { Pop-Location }      # not -I: the application's PyQt6 lives in the user site
    $r = $null
    try { $r = $raw | ConvertFrom-Json } catch { $r = $null }
    Check 'E02 the real Overlay in managed mode took the datagrams from its own dynamic UDP port (not 54321), no error' (($r -ne $null) -and ($r.error -eq $null) -and ($r.udp_port_is_not_54321 -eq $true))
    if ($r -ne $null -and $r.error -eq $null) {
        $v = $r.values
        Check 'E03 the pre-migration plain texts of the same datagrams (the old wire) were all rejected by the managed receiver and changed nothing' (($r.plain_sent -ge 6) -and ($r.receiver.rejected -eq $r.plain_sent) -and ($r.hud_before_real_datagrams.scenario -eq -1) -and (Near $r.hud_before_real_datagrams.speed 0.0))
        Check 'E04 receivers of another BVE pid / generation / token / AppInstance reject every real datagram' (@($r.foreign_rejected | Where-Object { $_ -ne $true }).Count -eq 0 -and @($r.foreign_rejected).Count -eq 4)
        Check 'E05 all real datagrams were accepted (accepted == datagrams) and the four kinds were present' (($r.receiver.accepted -eq $r.datagrams) -and (@($r.types | Select-Object -Unique | Sort-Object) -join ',') -eq '1,2,3,4')
        Check 'E06 speed, time, location arrive in the normalised state in the contract units (72 km/h, 10:00:00.048, 900 m)' ((Near $v.bve_speed 72.0) -and ($v.bve_time_ms -eq 36000048) -and (Near $v.bve_location 900.0))
        Check 'E07 gradient, signal limit, forward signal limit / location, ground limit' ((Near $v.bve_gradient -12.5) -and (Near $v.bve_signal_limit 90.0) -and (Near $v.bve_fwd_sig_limit 39.6) -and (Near $v.bve_fwd_sig_loc 1500.0) -and (Near $v.map_head_limit 72.0) -and (Near $v.map_tail_limit 72.0))
        Check 'E08 next station and its time, the STALIST (A,B,C,D with the terminal flag on D) and the META texts' ((Near $v.bve_next_loc 1000.0) -and ($v.bve_next_time -eq 36100000) -and ((@($v.station_names) -join ',') -eq 'A,B,C,D') -and ($v.station_terminal[3] -eq $true) -and ($v.meta_title -eq 'Title') -and ($v.meta_route -eq 'Route') -and ($v.bve_current_station_name -eq 'B'))
        Check 'E09 the heartbeat STATUS:LOADED:PAUSED reached the Overlay (loaded, state PAUSED)' (($v.is_bve_loaded -eq $true) -and ($v.bve_actual_state -eq 'PAUSED'))
        Check 'E10 brake type, notches, holding, pressure rates and maximum' (($v.bve_btype -eq 'Smee') -and ($v.cab_brk_count -eq 5) -and ($v.has_holding_brake -eq $true) -and ((@($v.bve_pressure_rates | ForEach-Object { [double]$_ }) -join ',') -eq '0,0.2,0.4,0.6,0.8,1') -and (Near $v.bve_max_pressure 490.0))
        $drawn = @($r.drawn)
        Check 'E11 the HUD draws time, speed and gradient from the real data' ((($drawn -join '|') -match '10:00:00') -and (($drawn -join '|') -match '72\.0 km/h') -and (($drawn -join '|') -match '-12\.5'))
        $okStates = $true; foreach ($k in 'time', 'time_left', 'speed', 'limit', 'dist', 'grad') { if ($r.states.$k -ne 'shown') { $okStates = $false } }
        Check 'E12 every HUD item that the sender announces is shown (the handle row stays unavailable: no handle text exists on this Legacy configuration of the test)' ($okStates -and ($r.states.handle -eq 'unavailable'))
        Check 'E13 the strict gate is ready, holds the sender announcement, and dropped nothing as stale or invalid' (($r.ready -eq $true) -and ($r.stats.tel_stale -eq 0) -and ($r.stats.tel_invalid -eq 0) -and ($r.stats.tel_accepted -ge 3) -and ($r.stats.tel_ahead -eq 0))
    }
    else { Write-Host $raw }
}
else {
    Skip ('E02-E13 the real Overlay chain: PyQt6=' + $qtOk + ' script present=' + (Test-Path $chk))
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
Write-Host '--- F: invariants'
$currentPin = '7D4B97A97A5739C095B3518ED75587805F727A4631EF48AD096EE65E53953856'      # the PID-D6 historical baseline: F02 only (it is never replaced)
$deployedCurrentPin = '1F504B45E4EE0DD23098BCA74DA0EEFF6AC81362BE730C4B3BCBC9507A19EB02'      # the Current DLL that is DEPLOYED on this machine now (Phase ST-1B build): F01 audits the machine state, not a historical baseline
$deployedCurrent = Join-Path $env:PUBLIC 'Documents\BveEx\2.0\Extensions\TsScoringPlugin.dll'
$handoff = 'C:\Users\tsuru\Documents\TS-Scoring-Claude-Handoff\pre-claude-v6-20261014_191918\live-d6\package\TsScoringPlugin.dll'
Check 'F01 the CURRENTLY deployed Current DLL (an audit of the deployed state of this machine, not a historical baseline) is byte-identical to the Phase ST-1B Current build (1F504B45...EB02)' ((Sha $deployedCurrent) -eq $deployedCurrentPin)
if (Test-Path -LiteralPath $handoff) { Check 'F02 the packaged Current DLL of PID-D6 is byte-identical (7D4B97A9...3856)' ((Sha $handoff) -eq $currentPin) } else { Skip 'F02 the packaged Current DLL is not at the recorded path' }
$st1aCurrent = @('TsScoringPlugin/TsScoringPlugin/Class1.cs', 'TsScoringPlugin/TsScoringPlugin/TsScoringPlugin.csproj', 'TsScoringPlugin/TsScoringPlugin/CurrentJumpEndpoint.cs', 'TsScoringPlugin/TsScoringPlugin/CurrentJumpExecution.cs')      # Phase ST-1A (J3-G2, observation only): the only two files of the Current plugin folder the STIDX supply may change; Phase ST-3b (the Current jump wiring) adds CurrentJumpEndpoint.cs (the grammar gate over JumpWire) and the new CurrentJumpExecution.cs (0 changed files, e.g. after the commit, is a pass too)
$curSrcOutside = @((& git -C $repo status --porcelain -- TsScoringPlugin/TsScoringPlugin | Out-String) -split "`n" | Where-Object { $_.Trim() } | Where-Object { $st1aCurrent -cnotcontains $_.Substring(3).Trim().Trim('"') })
Check 'F03 Current product source (TsScoringPlugin\TsScoringPlugin) is unchanged against HEAD (no modified, staged or untracked file) except the two files of Phase ST-1A (Class1.cs, TsScoringPlugin.csproj) and the two of Phase ST-3b (CurrentJumpEndpoint.cs, CurrentJumpExecution.cs)' ($curSrcOutside.Count -eq 0)
$pins = [ordered]@{
    'TsScoringPlugin\Handshake\Telemetry\Shared\DataPlaneProtocol.cs' = '0F6DE268B785462BD2E32F7161F1BDA69FBFEC4515752A834FBE4DFD242AE13B'
    'TsScoringPlugin\Handshake\Telemetry\Shared\TelemetryDirectoryReader.cs' = '9D6C47493457FD840E8CA5186C8E16181F0B5CF85C10721087C9098DD6644680'
    'TsScoringPlugin\Handshake\Telemetry\Shared\GenericHandleTextContract.cs' = '00B35CFCB21DC6648E4D7D65E8EC14721B76C6896B3A690CA6200AE959841264'
    'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs' = '69E4C447357B9988363F14F87ED36A0BCC24934077821F8BD9BFD2DED81EDAEF'
    'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs' = 'E0D5992E5B4D3EE088BCCC5B06F9A48465A59401899EC72018E1A042FCD6F68D'      # Phase ST-3b (a current source pin, moved on purpose): the grammar gate reads the shared JumpWire; the PID-D6 revision was 3837A409AFB136F10322DD78B8D89C4831B871AEB87824D0709594916F6FCB6D
}
$pinOk = $true
foreach ($k in $pins.Keys) { if ((Sha (Join-Path $repo $k)) -ne $pins[$k]) { $pinOk = $false; Write-Host ('  pin differs: ' + $k) } }
Check 'F04 the three shared files and CurrentDataPlane.cs are byte-identical to the SHA-256 recorded at PID-D6, and CurrentJumpEndpoint.cs is the Phase ST-3b revision' $pinOk
$sharedGit = (& git -C $repo status --porcelain -- TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs TsScoringPlugin/Handshake/Telemetry/Shared/GenericHandleTextContract.cs | Out-String).Trim()
Check 'F05 and git sees no change in them against HEAD' ($sharedGit -eq '')
$pyChanged = @((& git -C $repo status --porcelain | Out-String) -split "`n" | Where-Object { $_ -match '\.py\s*$' } | ForEach-Object { $_.Substring(3).Trim() } | Where-Object { $_ -notmatch '/' })
$pyAllowed = @('current_jump_client.py', 'dataplane_contract.py', 'main.py', 'telemetry_contract.py', 'station_index_contract.py', 'managed_input.py', 'scoring_logic.py', 'jump_transaction.py')      # PID-D4 / Legacy Jump 2A-alpha: the only two Python product modules the slice may change; Phase ST-1A adds the three of the STIDX intake; Phase ST-1B Prep adds managed_input.py (F07 limits it to the one stidx cap); Phase ST-3d adds scoring_logic.py (F07 limits it to its imports and execute_retry) and the new pure module jump_transaction.py (0 changed files, e.g. after the commit, is a pass too)
$pyOutside = @($pyChanged | Where-Object { $pyAllowed -cnotcontains $_ })
Check ('F06 no Python product module (repository root) differs from HEAD except the two allowed ones (' + ($pyAllowed -join ', ') + ')' + $(if ($pyOutside.Count -gt 0) { ': ' + ($pyOutside -join ',') } else { '' })) ($pyOutside.Count -eq 0)
# Phase ST-1B Prep (owner decision G-1): managed_input.py may differ from HEAD only by the EVENT_LINE_CAPS statement (the one "stidx" cap); no change at all (e.g. after the commit) is a pass too
$miChanged = @((& git -C $repo diff -U0 HEAD -- managed_input.py) | Where-Object { $_ -match '^[+-]' -and $_ -notmatch '^(\+\+\+|---)' })
# Phase ST-3d (on purpose): managed_input.py also gains the "jump-settled" cap, the jump_expectation state (generation_defaults, discard_scoring_session) and the close of the open transaction in _cancel_outstanding_jump
$miOutside = @($miChanged | Where-Object { $_ -notmatch 'EVENT_LINE_CAPS|"stidx": 24|"jump-settled": 24|retry_pending|jump_expectation|Phase ST-3d|_jump_transaction_finish|if finish is not None|finish\(reason\)|try:|except Exception:|pass$|PID-D6: the official jump' })
# Phase ST-3d (on purpose): scoring_logic.py may differ from HEAD only in its import block (jump_transaction, jump_wire) and inside execute_retry (the request is built before anything changes, by the one builder of the Jump wire v2); no change at all (e.g. after the commit) is a pass too
$slLines = [IO.File]::ReadAllLines((Join-Path $repo 'scoring_logic.py'))
$fnStart = 0
$fnEnd = $slLines.Count
for ($i = 0; $i -lt $slLines.Count; $i++) { if ($slLines[$i] -match '^def execute_retry\(') { $fnStart = $i + 1; break } }
for ($i = $fnStart; $i -lt $slLines.Count; $i++) { if ($slLines[$i] -match '^def ') { $fnEnd = $i; break } }
$slOutside = @()
foreach ($h in @((& git -C $repo diff -U0 HEAD -- scoring_logic.py) | Where-Object { $_ -match '^@@ ' })) {
    if ($h -match '\+(\d+)(,(\d+))? @@') {
        $first = [int]$Matches[1]
        $count = 1
        if ($Matches[3]) { $count = [int]$Matches[3] }
        $last = $first + [Math]::Max($count, 1) - 1
        if (-not (($last -le 12) -or (($first -ge $fnStart) -and ($last -le $fnEnd)))) { $slOutside += $h }
    }
}
Check 'F07 scoring_logic.py differs from HEAD only in its imports and inside execute_retry, and managed_input.py only in the stidx / jump-settled caps, the jump_expectation state and the close of the open transaction' (($slOutside.Count -eq 0) -and ($miOutside.Count -eq 0) -and ($miChanged.Count -le 16))
$tel = Join-Path $Root 'Telemetry'
$legacySrc = @(Get-ChildItem (Join-Path $tel 'Legacy\src') -Filter *.cs)
$legacyCode = ($legacySrc | ForEach-Object { Code ([IO.File]::ReadAllText($_.FullName)) }) -join "`n"
$proj = [IO.File]::ReadAllText((Join-Path $tel 'Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
$projCode = [regex]::Replace($proj, '<!--[\s\S]*?-->', '')
Check 'F08 the fixed port 54322 is not used by the Legacy project (no listener, no send)' (($legacyCode -notmatch '54322') -and ((Code ([IO.File]::ReadAllText((Join-Path $tel 'Shared\TelemetryContract.cs')))) -notmatch '54322'))
# PID-D4 / Legacy Jump 2A-alpha: the Legacy jump plane (LegacyJumpEndpoint / LegacyJumpCommandQueue / LegacyJumpControlPlane) exists, but it executes and announces nothing. The Current jump source
# is linked exactly once (the shared Link), only the plane files name the shared jump types, only the plane files and the host adapter name a LegacyJump type, nobody names the endpoint class.
$projDoc = New-Object System.Xml.XmlDocument
$projDoc.Load((Join-Path $tel 'Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
$jumpLinks = @($projDoc.SelectNodes("//*[local-name()='Compile']") | Where-Object { $_.GetAttribute('Include') -match 'CurrentJumpEndpoint' })
$jumpLinkOk = ($jumpLinks.Count -eq 1) -and ($jumpLinks[0].GetAttribute('Include') -ceq '..\..\..\TsScoringPlugin\CurrentJumpEndpoint.cs') -and ($jumpLinks[0].SelectSingleNode("*[local-name()='Link']").InnerText -ceq 'Shared\CurrentJumpEndpoint.cs')
$planeFiles = @('LegacyJumpCommandQueue.cs', 'LegacyJumpControlPlane.cs', 'LegacyJumpEndpoint.cs')
$legacyNaming = { param([string]$pattern) @($legacySrc | Where-Object { (Code ([IO.File]::ReadAllText($_.FullName))) -cmatch $pattern } | ForEach-Object { $_.Name } | Sort-Object) -join ',' }
$namesLegacyJump = & $legacyNaming 'LegacyJump'
$namesSharedJump = & $legacyNaming 'RequestId|JumpCommandValidator|JumpDirectoryPublisher|CurrentJumpCommand|JumpCapabilities'
# Phase LJX-1 (pin moved, see 02-Change-Set of the LJX-1 stage): the execution vocabulary (JumpComplete / JUMP_ / JumpStationTime / JumpLocationTime) is confined to the sink, the plane and the executor; the shared jump types are named by the three plane files and the executor (the ticket carries the RequestId); LegacyJump by the seven sources that belong to the execution. The Legacy host's jump API is pinned by Test-LegacyJumpExecLJX1.ps1 (S01 / LJX-28).
Check 'F09 the Legacy jump plane: the Current jump source is linked once (shared Link), CurrentJumpEndpoint is named by no Legacy source, the execution vocabulary (JumpComplete, JUMP_, JumpStationTime, JumpLocationTime) is confined to the sink, the plane and the executor, and LegacyJump and the shared jump types are named only by the plane files, the executor and the sources that belong to the execution (LJX-1)' ($jumpLinkOk -and ($legacyCode -cnotmatch 'CurrentJumpEndpoint') -and ((@($legacySrc | Where-Object { (Code ([IO.File]::ReadAllText($_.FullName))) -cmatch 'JumpComplete|JUMP_|JumpStationTime|JumpLocationTime' } | ForEach-Object { $_.Name } | Sort-Object) -join ',') -ceq 'LegacyDataPlaneSink.cs,LegacyJumpControlPlane.cs,LegacyJumpExecutor.cs') -and ($namesSharedJump -ceq (($planeFiles + 'LegacyJumpExecutor.cs') | Sort-Object) -join ',') -and ($namesLegacyJump -ceq 'LegacyDataPlaneSink.cs,LegacyJumpCommandQueue.cs,LegacyJumpControlPlane.cs,LegacyJumpEndpoint.cs,LegacyJumpExecutor.cs,LegacyTelemetryExtension.cs,LegacyTelemetrySession.cs'))
$types = @(); try { $types = @($telAsm.GetTypes() | ForEach-Object { $_.Name }) } catch [Reflection.ReflectionTypeLoadException] { $types = @($_.Exception.Types | Where-Object { $_ } | ForEach-Object { $_.Name }) }
# PID-D4 / Legacy Jump 2A-alpha: the shared Link puts the type CurrentJumpEndpoint into the Legacy DLL, which is allowed. What is pinned is that nothing in the DLL calls it: the IL of every
# type except CurrentJumpEndpoint itself is scanned for a call or newobj of CurrentJumpEndpoint (Create, the constructor). A scan that saw no method or no call would be a vacuous pass and fails.
$ilScan = $fixAsm.GetType('TsScoringLegacyTelemetryTests.LegacyIlCallScan')
$ilResult = $ilScan.GetMethod('ScanAllExcept').Invoke($null, [object[]]@($telAsm, [string[]]@('TSScoringPlugin.DataPlane.CurrentJumpEndpoint')))
$endpointCalls = @($ilResult.Calls | Where-Object { $_.StartsWith('TSScoringPlugin.DataPlane.CurrentJumpEndpoint::', [StringComparison]::Ordinal) })
$class1Creates = ([regex]::Matches((Code ([IO.File]::ReadAllText((Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\Class1.cs')))), 'CurrentJumpEndpoint\s*\.\s*Create\s*\(')).Count
Check 'F10 the Legacy DLL may hold the type CurrentJumpEndpoint but nothing in it calls CurrentJumpEndpoint (IL scan: 0 calls to Create or the constructor), the Current plugin keeps its one Create call, and the router and the sink are there' (($ilResult.MethodsScanned -gt 0) -and ($ilResult.CallsSeen -gt 0) -and ($endpointCalls.Count -eq 0) -and ($class1Creates -eq 1) -and ($types -contains 'CurrentTelemetryRouter') -and ($types -contains 'LegacyDataPlaneSink'))
Check 'F11 the Legacy project links CurrentDataPlane.cs (a link, never a copy) and keeps the shared protocol and reader links' (($proj -match '<Compile Include="\.\.\\\.\.\\\.\.\\TsScoringPlugin\\CurrentDataPlane\.cs">\s*<Link>Shared\\CurrentDataPlane\.cs</Link>') -and ($proj -match 'Shared\\DataPlaneProtocol\.cs') -and ($proj -match 'Shared\\TelemetryDirectoryReader\.cs') -and (-not (Test-Path (Join-Path $tel 'Legacy\src\CurrentDataPlane.cs'))))
$sinkCode = Code ([IO.File]::ReadAllText((Join-Path $tel 'Legacy\src\LegacyDataPlaneSink.cs')))
Check 'F12 the sink never writes a datagram itself (only the router does) and never names a fixed port: no transport.Send call, no 54321 literal, no UdpClient with a port' (($sinkCode -notmatch 'transport\.Send\(') -and ($sinkCode -notmatch '54321') -and ($sinkCode -notmatch 'UdpClient\(\s*\d') -and ($sinkCode -match 'TelemetryContract\.Port') -and ($sinkCode -match 'FixedLegacyDestination'))
$otherUse = @($legacySrc | Where-Object { $_.Name -ne 'LegacyDataPlaneSink.cs' -and (Code ([IO.File]::ReadAllText($_.FullName))) -match 'TelemetryContract\.Port|54321' } | ForEach-Object { $_.Name } | Sort-Object)
# PID-D4 / Legacy Jump 2A-alpha (S4 F13 allow-list): besides the sink, EXACTLY ONE source (LegacyJumpEndpoint.cs, by exact name in Legacy\src) may name TelemetryContract.Port, and only to compare an
# OS assigned port with the two reserved ports (Port, Port + 1) so that a reserved port is discarded before publication. 0 or several such sources is a FAIL; the 54321 / 54322 literals, a bind
# or a send to a fixed port, and every other use of the list stay forbidden.
$jumpEndpointCode = Code ([IO.File]::ReadAllText((Join-Path $tel 'Legacy\src\LegacyJumpEndpoint.cs')))
$portNameCount = ([regex]::Matches($jumpEndpointCode, 'TelemetryContract\.Port')).Count
$neverBindForm = ([regex]::Matches($jumpEndpointCode, 'NeverBindPorts\s*=\s*new\s+int\[\]\s*\{\s*TelemetryContract\.Port\s*,\s*TelemetryContract\.Port\s*\+\s*1\s*\}')).Count
$neverBindRest = [regex]::Replace([regex]::Replace([regex]::Replace($jumpEndpointCode, 'NeverBindPorts\s*=\s*new\s+int\[\]', ''), 'NeverBindPorts\.Length', ''), 'NeverBindPorts\[i\]\s*==\s*port', '')
$jumpPlaneCode = (($planeFiles | ForEach-Object { Code ([IO.File]::ReadAllText((Join-Path $tel ('Legacy\src\' + $_)))) }) -join "`n")
Check 'F13 the fixed legacy destination is named only in the sink (the normal path), the shared contract constant and, as the one comparison list NeverBindPorts, in LegacyJumpEndpoint.cs alone (no literal, no bind, no send to a fixed port)' ((($otherUse -join ',') -ceq 'LegacyJumpEndpoint.cs') -and ($portNameCount -eq 2) -and ($neverBindForm -eq 1) -and ($neverBindRest -cnotmatch 'NeverBindPorts') -and ($jumpPlaneCode -notmatch '5432[12]') -and ($jumpPlaneCode -notmatch 'UdpClient\(\s*\d') -and ($jumpPlaneCode -notmatch '\.Send\(') -and ($jumpPlaneCode -notmatch 'FixedLegacyDestination'))
Check 'F14 the old plain sink class is no longer created by any Legacy product source' ($legacyCode -notmatch 'new UdpTelemetrySink')
Check 'F15 the old fixed diagnostic log name is not in any Legacy product source or in the project' (([IO.File]::ReadAllText((Join-Path $tel 'Legacy\src\LegacyTelemetryExtension.cs')) -notmatch 'L3-Telemetry\.log') -and ($legacyCode -notmatch 'L3-Telemetry'))
$ext = Code ([IO.File]::ReadAllText((Join-Path $tel 'Legacy\src\LegacyTelemetryExtension.cs')))
Check 'F16 only the host adapter names AtsEX / BveTypes types (the sink file is host independent)' (-not ($sinkCode -match 'AtsEx|BveTypes') -and ($ext -match 'using AtsEx') -and (@($legacySrc | Where-Object { (Code ([IO.File]::ReadAllText($_.FullName))) -match 'using AtsEx|using BveTypes' }).Count -eq 1))
Check 'F17 the heartbeat thread still touches no BVE object (OnHeartbeat uses the session heartbeat and the sink only)' (([regex]::Match($ext, 'private void OnHeartbeat[\s\S]*?\r?\n        \}').Value -notmatch 'hacker|BveHacker|Scenario') -and ($ext -match 'sink\.Send\(text\)'))
$vi = (Get-Item $dllCopy).VersionInfo
$asmInfoText = Code ([IO.File]::ReadAllText((Join-Path $tel 'Legacy\src\AssemblyInfo.cs')))
$asmInfoOk = (([regex]::Matches($asmInfoText, '\[assembly:\s*Assembly(?:File|Informational)?Version\("([^"]*)"\)\]') | ForEach-Object { $_.Groups[1].Value }) -join ',') -cin @('0.5.0.0,0.5.0.0,0.5.0.0', '0.6.0.0,0.6.0.0,0.6.0.0')
Check 'F18 the source is 0.5.0.0 (Legacy Jump 2A-alpha) or 0.6.0.0 (Phase LJX-1), all three version attributes; the built DLL is the deployed 0.4.2.0 until the Release build and exactly 0.5.0.0 or 0.6.0.0 after it (no other version), product TS Scoring, provider Coruge-to, and references only the framework, AtsEX (PluginHost) and BveTypes' ($asmInfoOk -and (@('0.4.2.0', '0.5.0.0', '0.6.0.0') -ccontains $vi.FileVersion) -and ($vi.ProductVersion -ceq $vi.FileVersion) -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.CompanyName -eq 'Coruge-to') -and (-not (@($telAsm.GetReferencedAssemblies() | ForEach-Object { $_.Name }) | Where-Object { $_ -notmatch '^(mscorlib|System|System\.Core|AtsEx\.PluginHost|BveTypes|FastCaching|FastMember|TypeWrapping)$' })))
$named = @(Get-ChildItem $tel -Recurse -Filter *.cs | Where-Object { $_.FullName -notmatch '\\(obj|out)\\' -and (Code ([IO.File]::ReadAllText($_.FullName))) -match 'EventWaitHandle|MemoryMappedFile' } | ForEach-Object { $_.Name } | Sort-Object)
Check ('F19 named kernel objects (events / mappings) are opened only by the linked, unchanged D0B-1 readers: ' + ($named -join ', ')) (($named -join ',') -eq 'TelemetryDirectoryReader.cs')
$linkedNamed = (Code ([IO.File]::ReadAllText((Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')))) -match 'EventWaitHandle\.TryOpenExisting'
Check 'F20 the control plane events are only OPENED (TryOpenExisting, Synchronize right) by the linked core; nothing is created, signalled or waited on' ($linkedNamed -and ((Code ([IO.File]::ReadAllText((Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')))) -notmatch 'new EventWaitHandle|\.Set\(\)|\.Reset\(\)|WaitOne'))

Write-Host ''
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"LEGACY-DATAPLANE-D4 PASS=$pass FAIL=$fail SKIP=$($script:skips)"
if ($fail -gt 0) { exit 1 } else { exit 0 }
