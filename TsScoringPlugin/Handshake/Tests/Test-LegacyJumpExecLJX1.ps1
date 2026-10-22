# PHASE PID-D4 / LEGACY JUMP LJX-1 (the minimal execution slice) - runner of the LJX-1 tests (written FIRST: RED before the product).
#
# Modes (nothing is built, installed or edited by this script; it reads the repository and writes under the git-ignored Handshake\logs\ folder, or under -LogDir):
#   Static   S01..S14: source pins of the LJX-1 elements (the Legacy API allow-list, host independence of the plane files, the TTL, the build flag, the Current side and the
#            shared sources untouched, the Tick order of the extension, the vocabulary)
#   Product  compiles the LJX-1 tests against the product DLL and runs the 33 cases LJX-01..32 and LJX-99 (reflection bound: a missing product element is an expected RED)
#   Golden   runs the scripted OFF session of the earlier phases and compares the SHA-256 of everything it sends and logs with -GoldenBaseline (the Stage 0 value)
#   All      Static + Product + Golden
# -Expect green (default): every result must be PASS.  -Expect red: the RED stage - the NEW results must be RED for a missing product element, the GUARD results must be PASS.
# -CompiledIn: the DLL under test is the acceptance build (the LJX-1 compile symbol): LJX-04 / LJX-30 then expect the symbol compiled in.
# Exit codes: 0 every result is as expected; 1 at least one unexpected result; 2 inconclusive (BVE or the managed application is running, no compiler, no DLL).
#
# No BVE, no AtsEX runtime. Named mappings and loopback sockets of synthetic, unused, odd and huge BVE PIDs only; the fixed UDP ports 54321 / 54322 are never bound and
# never written to. ASCII-only on purpose. Windows PowerShell 5.1.
param(
    [ValidateSet('All', 'Static', 'Product', 'Golden')][string]$Mode = 'All',
    [ValidateSet('green', 'red')][string]$Expect = 'green',
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$DllPath = '',
    [string]$ProductSrcDir = '',
    [string]$LogDir = '',
    [string]$Tag = '',
    [string]$Only = '',
    [string]$GoldenBaseline = '',
    [switch]$CompiledIn
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = [string](Split-Path (Split-Path $Root -Parent) -Parent)
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if ([string]::IsNullOrEmpty($DllPath)) { $DllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll' }
if ([string]::IsNullOrEmpty($ProductSrcDir)) { $ProductSrcDir = Join-Path $Root 'Telemetry\Legacy\src' }
if ([string]::IsNullOrEmpty($Tag)) { $Tag = (Get-Date -Format 'yyyyMMdd-HHmmss') }
if ([string]::IsNullOrEmpty($LogDir)) { $LogDir = Join-Path $Root ('logs\jump-ljx1-tests\' + $Tag) }
New-Item -ItemType Directory -Force $LogDir | Out-Null
$testsDir = Join-Path $Root 'Tests'
$projFile = Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'
$python = 'C:\Python314\python.exe'
if (-not (Test-Path $python)) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($null -ne $c) { $python = $c.Source } }

$results = New-Object System.Collections.Generic.List[object]
function Report([string]$section, [string]$id, [string]$kind, [string]$outcome, [string]$detail, [string]$redCode = '') {
    # kind: NEW (new functionality: RED while the product is absent), GUARD (existing behaviour: PASS always)
    $isExpected = $false
    if ($Expect -eq 'green') { $isExpected = ($outcome -eq 'PASS') }
    else { if ($kind -eq 'NEW') { $isExpected = ($outcome -eq 'RED') } else { $isExpected = ($outcome -eq 'PASS') } }
    $r = [pscustomobject]@{ Section = $section; Id = $id; Kind = $kind; Outcome = $outcome; RedCode = $redCode; Expected = $isExpected; Detail = $detail }
    $results.Add($r)
    $mark = if ($isExpected) { 'ok ' } else { 'BAD' }
    $line = ('{0} {1,-8} {2,-9} {3,-5} {4,-12} {5} {6}' -f $mark, $section, $id, $kind, $outcome, $redCode, ($detail -replace "[\r\n]+", ' '))
    if ($line.Length -gt 360) { $line = $line.Substring(0, 360) }
    $line
}
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
function Sha([string]$path) { if (Test-Path -LiteralPath $path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash } else { return 'absent' } }
function ReadText([string]$path) { return [IO.File]::ReadAllText($path) }
function SrcCode([string]$name) { $p = Join-Path $ProductSrcDir $name; if (Test-Path $p) { return (Code (ReadText $p)) } else { return $null } }
function GitFingerprint {
    $h = (& git -C $repo rev-parse HEAD | Out-String).Trim()
    $s = (& git -C $repo status --porcelain --untracked-files=all | Out-String).Replace("`r", '').Trim()
    $st = @(& git -C $repo stash list).Count
    return ($h + '|stash=' + $st + '|' + $s)
}
function Guard { return @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(BveTs|BveTs5|BveTs6|python|pythonw)$' -or $_.ProcessName -match 'AtsEx' }) }

Write-Host ('LEGACYJUMP-LJX1 mode=' + $Mode + ' expect=' + $Expect + ' tag=' + $Tag + ' compiledIn=' + [bool]$CompiledIn)
$running = @(Guard)
if ($running.Count -gt 0 -and $Mode -ne 'Static') {
    Write-Host ('INCONCLUSIVE: BVE / python is running (' + (($running | ForEach-Object { $_.ProcessName + ':' + $_.Id }) -join ',') + '); the Windows tests do not start while they run.')
    exit 2
}
$gitBefore = GitFingerprint

# ---------------------------------------------------------------------------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Brace-Body([string]$code, [string]$header) {
    # the text between the first '{' after $header and its matching '}', or $null
    $i = $code.IndexOf($header)
    if ($i -lt 0) { return $null }
    $o = $code.IndexOf('{', $i)
    if ($o -lt 0) { return $null }
    $depth = 0
    for ($k = $o; $k -lt $code.Length; $k++) {
        $ch = $code[$k]
        if ($ch -eq '{') { $depth++ }
        elseif ($ch -eq '}') { $depth--; if ($depth -eq 0) { return $code.Substring($o, $k - $o + 1) } }
    }
    return $null
}
function SCheck([string]$id, [scriptblock]$body) {
    try {
        $r = & $body
        $isRed = ($r.ContainsKey('Red') -and $r.Red)
        $out = if ($r.Ok) { 'PASS' } elseif ($isRed) { 'RED' } else { 'FAIL' }
        $kind = if ($r.ContainsKey('Guard') -and $r.Guard) { 'GUARD' } else { 'NEW' }
        Report 'Static' $id $kind $out $r.Detail $(if ($isRed) { $r.RedCode } else { '' })
    }
    catch { Report 'Static' $id 'NEW' 'FAIL' ('exception ' + $_.Exception.GetType().Name + ' ' + $_.Exception.Message.Replace("`r`n", ' ')) }
}
function Absent([string]$why, [string]$code) { return @{ Ok = $false; Red = $true; RedCode = $code; Detail = $why } }

function Run-Static {
    Write-Host '--- Static: S pins of the LJX-1 elements'
    $planeFiles = @('LegacyJumpCommandQueue.cs', 'LegacyJumpControlPlane.cs', 'LegacyJumpEndpoint.cs', 'LegacyJumpExecutor.cs')
    $extCode = SrcCode 'LegacyTelemetryExtension.cs'

    SCheck 'S01' {
        # requirement 1 / 2: the three Legacy jump API names are called in ONE type (AtsExLegacyJumpHost) and nowhere else, once each
        $hostBody = Brace-Body $extCode 'class AtsExLegacyJumpHost'
        if ($null -eq $hostBody) { return (Absent 'type AtsExLegacyJumpHost is absent' 'type-absent') }
        $names = @('Initialize', 'InitializeTimeAndLocation', 'SetTime')
        $inside = @{}; $outside = 0
        foreach ($n in $names) { $inside[$n] = ([regex]::Matches($hostBody, '\.' + $n + '\s*\(')).Count }
        foreach ($f in (Get-ChildItem $ProductSrcDir -Filter *.cs)) {
            $c = Code (ReadText $f.FullName)
            if ($f.Name -eq 'LegacyTelemetryExtension.cs') { $c = $c.Replace($hostBody, '') }
            foreach ($n in $names) { $outside += ([regex]::Matches($c, '\.' + $n + '\s*\(')).Count }
        }
        @{ Ok = ($inside['Initialize'] -eq 1 -and $inside['InitializeTimeAndLocation'] -eq 1 -and $inside['SetTime'] -eq 1 -and $outside -eq 0); Detail = "calls inside AtsExLegacyJumpHost: Initialize $($inside['Initialize']), InitializeTimeAndLocation $($inside['InitializeTimeAndLocation']), SetTime $($inside['SetTime']); anywhere else: $outside" }
    }
    SCheck 'S02' {
        # the plane, queue, endpoint and executor are host independent: no host word, no Legacy API name
        $missing = @($planeFiles | Where-Object { -not (Test-Path (Join-Path $ProductSrcDir $_)) })
        if ($missing.Count -gt 0) { return (Absent ('file(s) absent: ' + ($missing -join ',')) 'files-absent') }
        $n = 0
        foreach ($f in $planeFiles) { $n += ([regex]::Matches((SrcCode $f), 'BveHacker|AtsEx|BveTypes|BveEx|Handshake|\bCaller\b|IInputDevice|LegacyApi|\bInitialize\(|InitializeTimeAndLocation|\bSetTime\(|TimeManager|\bScenario\b')).Count }
        @{ Ok = ($n -eq 0); Detail = "host / Legacy API words in the four host independent files: $n" }
    }
    SCheck 'S03' {
        $cp = SrcCode 'LegacyJumpControlPlane.cs'
        $m = [regex]::Match($cp, 'ExecutionTtlMs\s*=\s*(\d+)\s*;')
        $pyText = ReadText (Join-Path $repo 'current_jump_client.py')
        $py = [regex]::Match($pyText, '(?m)^OUTSTANDING_TIMEOUT_S\s*=\s*([0-9.]+)')
        if (-not $m.Success) { return (Absent 'ExecutionTtlMs is absent' 'member-absent') }
        $ttl = [int]$m.Groups[1].Value
        @{ Ok = ($ttl -eq 5000 -and $py.Success -and [double]$py.Groups[1].Value -eq 10.0 -and $ttl -gt 0 -and $ttl -lt 10000); Detail = "ExecutionTtlMs $ttl; Python OUTSTANDING_TIMEOUT_S $($py.Groups[1].Value)" }
    }
    SCheck 'S04' {
        $p = Join-Path $ProductSrcDir 'LegacyJumpExecutor.cs'
        if (-not (Test-Path $p)) { return (Absent 'LegacyJumpExecutor.cs is absent (the build flag lives there)' 'files-absent') }
        $raw = ReadText $p
        $flag = [regex]::Match($raw, '#if\s+LEGACY_JUMP_EXEC[\s\S]*?ExecutionCompiledIn\s*=\s*true\s*;[\s\S]*?#else[\s\S]*?ExecutionCompiledIn\s*=\s*false\s*;[\s\S]*?#endif')
        $proj = ReadText $projFile
        $define = [regex]::Match($proj, '<DefineConstants>([^<]*)</DefineConstants>')
        $defaultDefine = $define.Groups[1].Value
        $cond = $proj -match "\`$\(LegacyJumpExec\)'\s*==\s*'true'"
        @{ Ok = ($flag.Success -and $defaultDefine -notmatch 'LEGACY_JUMP_EXEC' -and $cond); Detail = "#if LEGACY_JUMP_EXEC / #else false: $($flag.Success); default DefineConstants '$defaultDefine' has no symbol: $($defaultDefine -notmatch 'LEGACY_JUMP_EXEC'); the symbol is added only by /p:LegacyJumpExec=true: $cond" }
    }
    SCheck 'S05' {
        $missing = @($planeFiles | Where-Object { -not (Test-Path (Join-Path $ProductSrcDir $_)) })
        if ($missing.Count -gt 0) { return (Absent ('file(s) absent: ' + ($missing -join ',')) 'files-absent') }
        $lits = 0
        foreach ($f in $planeFiles) { $lits += ([regex]::Matches((SrcCode $f), '5432[12]')).Count }
        $hostBody = Brace-Body $extCode 'class AtsExLegacyJumpHost'
        $hl = if ($null -ne $hostBody) { ([regex]::Matches($hostBody, '5432[12]')).Count } else { 0 }
        $nb = [regex]::Match((SrcCode 'LegacyJumpEndpoint.cs'), 'NeverBindPorts[^;]*;')
        @{ Ok = ($lits -eq 0 -and $hl -eq 0 -and $nb.Success -and $nb.Value -match 'TelemetryContract\.Port\s*\+\s*1'); Detail = "fixed port literals in the plane files: $lits; in the host adapter: $hl; NeverBindPorts keeps both fixed ports: $($nb.Success)" }
    }
    SCheck 'S06' {
        # requirement 23 / 32: the Current product, the shared sources and the layout are untouched (git diff against HEAD is empty) and pinned by hash
        # (Phase ST-1A, J3-G2, observation only: Class1.cs and TsScoringPlugin.csproj are the two files of the Current plugin folder that carry the STIDX supply; they may differ from HEAD until the commit - tests\test_stationindex_supply_st1a.py pins what changed)
        $st1aCurrent = @('TsScoringPlugin/TsScoringPlugin/Class1.cs', 'TsScoringPlugin/TsScoringPlugin/TsScoringPlugin.csproj', 'TsScoringPlugin/TsScoringPlugin/CurrentJumpEndpoint.cs', 'TsScoringPlugin/TsScoringPlugin/CurrentJumpExecution.cs')      # Phase ST-3b adds the grammar gate and the new Current-only unit
        $diff = @(& git -C $repo diff --name-only HEAD -- 'TsScoringPlugin/TsScoringPlugin' 'TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs' 'TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs' 'TsScoringPlugin/Handshake/Telemetry/Shared/GenericHandleTextContract.cs' 'TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.l3build.log' | Where-Object { $st1aCurrent -cnotcontains $_ })
        $pins = [ordered]@{
            'TsScoringPlugin\Handshake\Telemetry\Shared\DataPlaneProtocol.cs'         = '0F6DE268B785462BD2E32F7161F1BDA69FBFEC4515752A834FBE4DFD242AE13B'
            'TsScoringPlugin\Handshake\Telemetry\Shared\TelemetryDirectoryReader.cs'  = '9D6C47493457FD840E8CA5186C8E16181F0B5CF85C10721087C9098DD6644680'
            'TsScoringPlugin\Handshake\Telemetry\Shared\GenericHandleTextContract.cs' = '00B35CFCB21DC6648E4D7D65E8EC14721B76C6896B3A690CA6200AE959841264'
            'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs'                     = '69E4C447357B9988363F14F87ED36A0BCC24934077821F8BD9BFD2DED81EDAEF'
            'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs'                  = 'E0D5992E5B4D3EE088BCCC5B06F9A48465A59401899EC72018E1A042FCD6F68D'      # Phase ST-3b (a current source pin, moved on purpose; the PID-D6 revision was 3837A409AFB136F10322DD78B8D89C4831B871AEB87824D0709594916F6FCB6D)
        }
        $bad = @()
        foreach ($k in $pins.Keys) { if ((Sha (Join-Path $repo $k)) -ne $pins[$k]) { $bad += $k } }
        $c1 = Sha (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\Class1.cs')
        $c1Head = (& git -C $repo diff --name-only HEAD -- 'TsScoringPlugin/TsScoringPlugin/Class1.cs' | Where-Object { $st1aCurrent -cnotcontains $_ })
        $curDll = Join-Path $env:PUBLIC 'Documents\BveEx\2.0\Extensions\TsScoringPlugin.dll'
        $curSha = Sha $curDll
        $diffVal = @(@($diff) + @($bad) | Where-Object { $_ }).Count
        # this check is a GUARD of existing files: it must be PASS in the RED stage too (it reports as NEW, so the RED stage accepts RED or PASS here)
        $ok = ($diffVal -eq 0 -and -not $c1Head -and $curSha.StartsWith('7D4B97A9'))
        @{ Ok = $ok; Guard = $true; Detail = "git diff of the Current side and the shared sources: $($diff.Count) files; hash pins off: $($bad.Count); Class1.cs unchanged: $(-not $c1Head); deployed Current DLL $($curSha.Substring(0, 8))" }
    }
    SCheck 'S07' {
        # the Tick of the extension: TickPre, session.OnTick, TickPost, OnHostTick - each in its own try, the runner exists only when the execution is active
        if ($null -eq $extCode) { return (Absent 'extension absent' 'files-absent') }
        $tick = Brace-Body $extCode 'public override TickResult Tick('
        if ($null -eq $tick) { return (Absent 'Tick not found' 'member-absent') }
        $iPre = $tick.IndexOf('TickPre'); $iOn = $tick.IndexOf('session.OnTick'); $iPost = $tick.IndexOf('TickPost'); $iHost = $tick.IndexOf('OnHostTick')
        if ($iPre -lt 0 -or $iPost -lt 0) { return (Absent 'TickPre / TickPost are not called from Tick' 'member-absent') }
        $tries = ([regex]::Matches($tick, '\btry\b')).Count
        $gated = $extCode -match 'ExecutionActive'
        @{ Ok = ($iPre -lt $iOn -and $iOn -lt $iPost -and $iPost -lt $iHost -and $tries -ge 4 -and $gated); Detail = "order TickPre $iPre < session.OnTick $iOn < TickPost $iPost < OnHostTick $iHost; try blocks in Tick: $tries; execution gate in the extension: $gated" }
    }
    SCheck 'S08' {
        $cl = Brace-Body (SrcCode 'LegacyDataPlaneSink.cs') 'class LegacyMessageClassifier'
        if ($null -eq $cl) { return @{ Ok = $false; Detail = 'classifier not found' } }
        $sink = SrcCode 'LegacyDataPlaneSink.cs'
        $has = $sink -match 'SendJumpComplete'
        if (-not $has) { return (Absent 'LegacyDataPlaneSink.SendJumpComplete is absent' 'member-absent') }
        @{ Ok = ($cl -notmatch 'JUMP_COMPLETE'); Detail = "the classifier does not know JUMP_COMPLETE: $($cl -notmatch 'JUMP_COMPLETE')" }
    }
    SCheck 'S09' {
        $tc = Code (ReadText (Join-Path $Root 'Telemetry\Shared\TelemetryContract.cs'))
        $sess = SrcCode 'LegacyTelemetrySession.cs'
        if ($tc -notmatch 'TokJump\s*=\s*"jump"') { return (Absent 'TokJump is absent' 'member-absent') }
        $guarded = $sess -match 'jumpAvail\s*!=\s*null[\s\S]{0,200}TokJump'
        $only = ([regex]::Matches($sess, 'TokJump')).Count
        @{ Ok = ($guarded -and $only -eq 1); Detail = "TokJump is used once and only behind the availability: $guarded ($only uses)" }
    }
    SCheck 'S10' {
        $ai = ReadText (Join-Path $ProductSrcDir 'AssemblyInfo.cs')
        $vs = @([regex]::Matches($ai, '\[assembly: Assembly(?:File|Informational)?Version\("([^"]+)"\)\]') | ForEach-Object { $_.Groups[1].Value })
        @{ Ok = ($vs.Count -eq 3 -and @($vs | Where-Object { $_ -ne '0.6.0.0' }).Count -eq 0); Red = $true; RedCode = 'version-not-0.6.0.0'; Detail = "AssemblyInfo versions: $($vs -join ',') (the LJX-1 build is 0.6.0.0)" }
    }
    SCheck 'S11' {
        # the Legacy project still has exactly the four Current links of 2A-alpha and no new link outside Telemetry
        $proj = ReadText $projFile
        $links = @([regex]::Matches($proj, '<Compile Include="(\.\.\\[^"]+)"') | ForEach-Object { $_.Groups[1].Value })
        # (Phase ST-1A adds the one shared link of the STIDX supply: ..\Shared\StationListIdentity.cs)
        $okLinks = @('..\..\..\TsScoringPlugin\CurrentDataPlane.cs', '..\..\..\TsScoringPlugin\CurrentJumpEndpoint.cs', '..\Shared\GenericHandleTextContract.cs', '..\Shared\DataPlaneProtocol.cs', '..\Shared\TelemetryDirectoryReader.cs', '..\Shared\TelemetryContract.cs', '..\Shared\StationListIdentity.cs', '..\Shared\JumpWire.cs')      # Phase ST-3b / G-PC-1: the compile-only link of the wire codec
        $extra = @($links | Where-Object { $okLinks -notcontains $_ })
        $hasExec = $proj -match 'LegacyJumpExecutor\.cs'
        if (-not $hasExec) { return (Absent 'LegacyJumpExecutor.cs is not in the project' 'files-absent') }
        @{ Ok = ($extra.Count -eq 0 -and $links.Count -eq 8); Detail = "linked files: $($links.Count); unexpected links: $($extra -join ',')" }
    }
    SCheck 'S12' {
        # the executor never creates a thread, a timer or a task; the plane keeps its one worker thread
        $missing = @($planeFiles | Where-Object { -not (Test-Path (Join-Path $ProductSrcDir $_)) })
        if ($missing.Count -gt 0) { return (Absent ('file(s) absent: ' + ($missing -join ',')) 'files-absent') }
        $n = 0
        foreach ($f in $planeFiles) { $n += ([regex]::Matches((SrcCode $f), 'System\.Timers|\bTimer\b|ThreadPool|\bTask\b|\basync\b|\bawait\b|Thread\.Abort|\.Abort\(')).Count }
        $threads = 0
        foreach ($f in $planeFiles) { $threads += ([regex]::Matches((SrcCode $f), 'new Thread\(')).Count }
        @{ Ok = ($n -eq 0 -and $threads -eq 1); Detail = "timer / pool / task / abort words: $n; new Thread( in the plane files: $threads" }
    }
    SCheck 'S13' {
        # no StationIndex source of truth, no checkpoint, no cancel: the slice keeps its scope
        $missing = @($planeFiles | Where-Object { -not (Test-Path (Join-Path $ProductSrcDir $_)) })
        if ($missing.Count -gt 0) { return (Absent ('file(s) absent: ' + ($missing -join ',')) 'files-absent') }
        $n = 0
        foreach ($f in $planeFiles) { $n += ([regex]::Matches((SrcCode $f), 'StationList|Checkpoint|CANCEL|Cancel\(|JUMP_FAILED|JumpTransition|PseudoLoop|PTO')).Count }
        @{ Ok = ($n -eq 0); Detail = "out-of-scope words in the plane files: $n" }
    }
    SCheck 'S14' {
        # the new test sources obey the lint of the earlier test sources: ASCII, LF, no BOM, no host words in code
        $files = @('LegacyJumpExecTestFixture.cs', 'LegacyJumpExecTestCases.cs', 'LegacyJumpExecGolden.cs', 'Test-LegacyJumpExecLJX1.ps1') | ForEach-Object { Join-Path $testsDir $_ }
        $bad = @()
        foreach ($f in $files) {
            if (-not (Test-Path $f)) { $bad += (Split-Path $f -Leaf) + ':absent'; continue }
            $b = [IO.File]::ReadAllBytes($f)
            if (@($b | Where-Object { $_ -gt 127 }).Count -gt 0) { $bad += (Split-Path $f -Leaf) + ':non-ASCII' }
            if (@($b | Where-Object { $_ -eq 13 }).Count -gt 0) { $bad += (Split-Path $f -Leaf) + ':CR' }
            if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { $bad += (Split-Path $f -Leaf) + ':BOM' }
        }
        $errs = $null; $tokens = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $testsDir 'Test-LegacyJumpExecLJX1.ps1'), [ref]$tokens, [ref]$errs)
        if ($errs.Count -gt 0) { $bad += 'parse-errors:' + $errs.Count }
        @{ Ok = ($bad.Count -eq 0); Guard = $true; Detail = "lint findings: $($bad -join ', ')" }
    }
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# compile + load
# ---------------------------------------------------------------------------------------------------------------------------------------------
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class LjxResolver
{
    private static string[] dirs = new string[0];
    private static bool installed;
    public static void Install(string[] d)
    {
        dirs = d;
        if (installed) { return; }
        installed = true;
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

function Build-Fixture([string]$dll, [string]$workName) {
    $work = Join-Path $LogDir $workName
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
    New-Item -ItemType Directory -Force $work | Out-Null
    $dllCopy = Join-Path $work (Split-Path $dll -Leaf)
    Copy-Item $dll $dllCopy
    $fixDll = Join-Path $work 'TsScoringLegacyTelemetryTests.dll'
    $sources = @('LegacyJumpPlaneTestKit.cs', 'LegacyJumpPlaneTestFixture.cs', 'LegacyIlCallScan.cs', 'TelemetryTestFixture.cs', 'LegacyDataPlaneTestFixture.cs',
        'LegacyJumpExecTestFixture.cs', 'LegacyJumpExecTestCases.cs', 'LegacyJumpExecGolden.cs') | ForEach-Object { Join-Path $testsDir $_ }
    Add-Type -Path $sources -ReferencedAssemblies @($dllCopy, 'System.dll', 'System.Core.dll') -OutputAssembly $fixDll -OutputType Library -IgnoreWarnings
    [LjxResolver]::Install(@($work, $legacyHost))
    $prod = [Reflection.Assembly]::LoadFrom($dllCopy)
    $fix = [Reflection.Assembly]::LoadFrom($fixDll)
    return [pscustomobject]@{ Prod = $prod; Fix = $fix; Type = $fix.GetType('TsScoringLegacyTelemetryTests.LegacyJumpExecTestFixture'); Work = $work }
}

function Save-RunResult([string]$name, $rr) {
    $tsv = New-Object System.Collections.Generic.List[string]
    $tsv.Add("id`tkind`toutcome`tred_code`tchecks`tfailed`tseconds`tfail_text`ttitle")
    foreach ($t in $rr.Tests) {
        $ft = ([string]$t.FailText) -replace "[`t`r`n]", ' '
        $tsv.Add(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6:N1}`t{7}`t{8}" -f $t.Id, $t.Kind, $t.Outcome, $t.RedCode, $t.Checks, $t.Failed, $t.Seconds, $ft, $t.Label))
        [IO.File]::WriteAllText((Join-Path $LogDir ($name + '-' + $t.Id + '.log')), [string]$t.Log, (New-Object Text.UTF8Encoding($false)))
    }
    [IO.File]::WriteAllLines((Join-Path $LogDir ($name + '-results.tsv')), $tsv.ToArray(), (New-Object Text.UTF8Encoding($false)))
}

function Run-Product {
    Write-Host '--- Product: the LJX-1 cases against the product DLL'
    if (-not (Test-Path $DllPath)) { Write-Host ('INCONCLUSIVE: product DLL absent: ' + $DllPath); $script:inconclusive = $true; return }
    $b = Build-Fixture $DllPath 'work-product'
    $b.Type.GetField('ExpectCompiledIn').SetValue($null, [bool]$CompiledIn)
    $found = @($b.Type.GetMethod('DiscoverIds').Invoke($null, $null))
    Report 'Product' 'count' 'GUARD' $(if ($found.Count -eq 33) { 'PASS' } else { 'FAIL' }) ("discovered " + $found.Count + " case methods by reflection; the plan has 33 (LJX-01..32, LJX-99)")
    [string[]]$onlyIds = @($Only -split ',' | Where-Object { $_ })
    $rr = $b.Type.GetMethod('Run').Invoke($null, @($b.Prod, ('l' + (Get-Date -Format 'HHmmss')), $repo, $onlyIds))
    Save-RunResult 'product' $rr
    $expectInvoked = if ($onlyIds.Count -gt 0) { $onlyIds.Count } else { $found.Count }
    Report 'Product' 'invoked' 'GUARD' $(if ($rr.Discovered -eq $found.Count -and $rr.Invoked -eq $expectInvoked) { 'PASS' } else { 'FAIL' }) ("discovered " + $rr.Discovered + " = invoked " + $rr.Invoked + " (" + $rr.Header + ")")
    foreach ($t in $rr.Tests) {
        $detail = "checks $($t.Checks) failed $($t.Failed) $($t.Label)"
        if ($t.Outcome -eq 'FAIL') { $detail = "checks $($t.Checks) failed $($t.Failed) $($t.FailText)" }
        Report 'Product' $t.Id $t.Kind $t.Outcome $detail $t.RedCode
    }
}

function Run-Golden {
    Write-Host '--- Golden: the scripted OFF session (the earlier phases) must not change by one byte'
    if (-not (Test-Path $DllPath)) { Write-Host ('INCONCLUSIVE: product DLL absent: ' + $DllPath); $script:inconclusive = $true; return }
    $b = Build-Fixture $DllPath 'work-golden'
    $text = [string]$b.Type.GetMethod('GoldenOffText').Invoke($null, $null)
    $sha = [string]$b.Type.GetMethod('GoldenOffSha256').Invoke($null, $null)
    [IO.File]::WriteAllText((Join-Path $LogDir 'golden-off.txt'), $text, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $LogDir 'golden-off.sha256'), $sha, (New-Object Text.UTF8Encoding($false)))
    $lines = ($text -split "`n").Count
    Report 'Golden' 'G01-captured' 'GUARD' $(if ($text.Length -gt 5000 -and $lines -gt 100) { 'PASS' } else { 'FAIL' }) ("scripted OFF output: $($text.Length) chars, $lines lines, sha256 $sha")
    if (-not [string]::IsNullOrEmpty($GoldenBaseline)) {
        $base = (ReadText $GoldenBaseline).Trim()
        Report 'Golden' 'G02-equals-baseline' 'GUARD' $(if ($sha -eq $base) { 'PASS' } else { 'FAIL' }) ("sha256 now $sha, baseline $base")
        $rows = @(($text -split "`n") | Where-Object { $_ -like 'S SCENARIO_ID:*' })
        $jump = @($rows | Where-Object { $_ -match 'JUMP' -or $_ -match 'jump' })
        Report 'Golden' 'G03-no-jump-in-OFF-rows' 'GUARD' $(if ($rows.Count -gt 0 -and $jump.Count -eq 0) { 'PASS' } else { 'FAIL' }) ("telemetry rows $($rows.Count); rows with a JUMP key or jump token: $($jump.Count)")
    }
}

$script:inconclusive = $false
if ($Mode -in 'All', 'Static') { Run-Static }
if ($Mode -in 'All', 'Product') { Run-Product }
if ($Mode -in 'All', 'Golden') { Run-Golden }

$gitAfter = GitFingerprint
if ($gitBefore -ne $gitAfter) { Report 'Runner' 'repository-unchanged' 'GUARD' 'FAIL' 'git HEAD, stash or status changed during the run' }
else { Report 'Runner' 'repository-unchanged' 'GUARD' 'PASS' 'git HEAD, stash and status are identical before and after this run (the run writes only under the git-ignored logs folder)' }

$tsv = New-Object System.Collections.Generic.List[string]
$tsv.Add("section`tid`tkind`toutcome`tred_code`texpected`tdetail")
foreach ($r in $results) { $tsv.Add(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f $r.Section, $r.Id, $r.Kind, $r.Outcome, $r.RedCode, $r.Expected, ($r.Detail -replace "[\t\r\n]+", ' '))) }
[IO.File]::WriteAllLines((Join-Path $LogDir 'results.tsv'), $tsv.ToArray(), (New-Object Text.UTF8Encoding($false)))
$pass = @($results | Where-Object { $_.Outcome -eq 'PASS' }).Count
$fail = @($results | Where-Object { $_.Outcome -eq 'FAIL' }).Count
$red = @($results | Where-Object { $_.Outcome -eq 'RED' }).Count
$unexpected = @($results | Where-Object { -not $_.Expected }).Count
Write-Host ("LEGACYJUMP-LJX1 mode=$Mode expect=$Expect PASS=$pass FAIL=$fail RED=$red UNEXPECTED=$unexpected log=$LogDir")
if ($script:inconclusive) { exit 2 }
if ($unexpected -gt 0) { exit 1 }
exit 0
