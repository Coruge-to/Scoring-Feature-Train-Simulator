# PHASE PID-D4 / LEGACY JUMP 2A-ALPHA - runner of the product tests of the Legacy Jump control plane (written FIRST, Stage S1; the product comes in Stage S3).
#
# Modes (explicit; nothing is built, installed or edited by this script - it only reads the repository and writes under the git-ignored Handshake\logs\ folder):
#   Static    K01..K17: source pins of the three new product files (K), the version / wiring / parity pins, and the lint of the 2A-alpha test sources themselves
#   Self      the kit self tests (SELF-01..19; SELF-11..19 are the deterministic controls of the ITR-15 / WIN-99 judges, of Ready() and of the outcome INCONCLUSIVE) and the IL scanner proofs (positive and negative controls) - they need no product at all
#   Product   compiles the 2A-alpha tests (A4a + A4b + A10) against the product DLL and runs the 33 cases ITR-01..16, EX-01..03, WIN-01..04, PT-01..09, WIN-99
#   Python    the Reader / interop / contract tests (tests\test_jump_directory_reader_2a.py, tests\test_legacy_jump_plane_interop_2a.py, tests\test_dataplane_contract_pid_d1.py)
#   Mutation  runs the cases against the mutants of a -MutantsDir and requires that every mutant is detected (the reference DLL of that directory must stay GREEN)
#   Regress   runs the existing suites (the Stage S0 job list, without Test-JumpProbeB1) and separates the known failures of the S0 baseline from new ones
#   All       Static + Self + Product + Python
# -Expect green (default): every result must be PASS (the state after Stage S3).
# -Expect red: the Stage S1 state - the new-functionality (NEW) results must be RED for the recorded reason, the regression guards (GUARD) must be GREEN.
# A RED is "a pinned product element does not exist yet" (ProductAbsentException / a missing product file / a [contract:...] tag). Any other failure is a FAIL.
# Exit codes: 0 every result is as expected; 1 at least one unexpected result; 2 inconclusive (a prerequisite is missing: BVE or python running, no compiler, no baseline).
#
# No BVE, no AtsEX runtime. The only operating system objects are named mappings and loopback sockets on synthetic, unused, odd and huge BVE PIDs; fixed UDP 54321 / 54322
# are never bound and never written to. ASCII-only on purpose. Windows PowerShell 5.1.
param(
    [ValidateSet('All', 'Static', 'Self', 'Product', 'Python', 'Mutation', 'Regress')][string]$Mode = 'All',
    [ValidateSet('green', 'red')][string]$Expect = 'green',
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$DllPath = '',
    [string]$ProductSrcDir = '',
    [string]$PyRoot = '',
    [string]$LogDir = '',
    [string]$MutantsDir = '',
    [string]$BaselineChecksTsv = '',
    [string]$Tag = '',
    [string]$Only = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repo = [string](Split-Path (Split-Path $Root -Parent) -Parent)
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if ([string]::IsNullOrEmpty($DllPath)) { $DllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll' }
if ([string]::IsNullOrEmpty($ProductSrcDir)) { $ProductSrcDir = Join-Path $Root 'Telemetry\Legacy\src' }
if ([string]::IsNullOrEmpty($PyRoot)) { $PyRoot = $repo }
if ([string]::IsNullOrEmpty($Tag)) { $Tag = (Get-Date -Format 'yyyyMMdd-HHmmss') }
if ([string]::IsNullOrEmpty($LogDir)) { $LogDir = Join-Path $Root ('logs\jump-2a-tests\' + $Tag) }
New-Item -ItemType Directory -Force $LogDir | Out-Null
$env:PYTHONDONTWRITEBYTECODE = '1'
$testsDir = Join-Path $Root 'Tests'
$python = 'C:\Python314\python.exe'
if (-not (Test-Path $python)) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($null -ne $c) { $python = $c.Source } }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# result bookkeeping
# ---------------------------------------------------------------------------------------------------------------------------------------------
$results = New-Object System.Collections.Generic.List[object]
function Report([string]$section, [string]$id, [string]$kind, [string]$outcome, [string]$detail, [string]$redCode = '', [string]$expectedRed = '') {
    # kind: NEW (new functionality), GUARD (regression guard of existing behaviour), SELF (proof of the tests themselves)
    $isExpected = $false
    if ($Expect -eq 'green') { $isExpected = ($outcome -eq 'PASS') }
    else {
        if ($kind -eq 'NEW') { $isExpected = ($outcome -eq 'RED') -and (($expectedRed -eq '') -or ($redCode -eq $expectedRed)) }
        else { $isExpected = ($outcome -eq 'PASS') }
    }
    $r = [pscustomobject]@{ Section = $section; Id = $id; Kind = $kind; Outcome = $outcome; RedCode = $redCode; Expected = $isExpected; Detail = $detail }
    $results.Add($r)
    $mark = if ($isExpected) { 'ok ' } else { 'BAD' }
    $line = ('{0} {1,-8} {2,-9} {3,-5} {4,-4} {5} {6}' -f $mark, $section, $id, $kind, $outcome, $redCode, ($detail -replace "[\r\n]+", ' '))
    if ($line.Length -gt 330) { $line = $line.Substring(0, 330) }
    $line
}
$inconclusive = New-Object System.Collections.Generic.List[string]
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
function Sha([string]$path) { if (Test-Path -LiteralPath $path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash } else { return 'absent' } }
function ReadText([string]$path) { return [IO.File]::ReadAllText($path) }
function GitFingerprint {
    $h = (& git -C $repo rev-parse HEAD | Out-String).Trim()
    $s = (& git -C $repo status --porcelain --untracked-files=all | Out-String).Replace("`r", '').Trim()
    $st = @(& git -C $repo stash list).Count
    return ($h + '|stash=' + $st + '|' + $s)
}
function Guard {
    $p = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(BveTs|BveTs5|BveTs6|python|pythonw)$' -or $_.ProcessName -match 'AtsEx' })
    return $p
}

$gitBefore = GitFingerprint
Write-Host ('LEGACYJUMP-2A mode=' + $Mode + ' expect=' + $Expect + ' tag=' + $Tag + ' HEAD=' + $gitBefore.Split('|')[0].Substring(0, 7))
$running = @(Guard)
if ($running.Count -gt 0 -and $Mode -ne 'Static') {
    Write-Host ('INCONCLUSIVE: BVE / python is running (' + (($running | ForEach-Object { $_.ProcessName + ':' + $_.Id }) -join ',') + '); the Windows tests do not start while they run.')
    exit 2
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# the three new product files and the version / wiring pins (Static)
# ---------------------------------------------------------------------------------------------------------------------------------------------
$newFiles = @('LegacyJumpEndpoint.cs', 'LegacyJumpCommandQueue.cs', 'LegacyJumpControlPlane.cs')
# K11: the Session pin moved from the 2A-alpha baseline (DFDBF759...47AC9) to the audited TEL_DISCONTINUITY diagnostic edit (owner decision C-1, option C: 14 keys, no hb). The edit is diagnostic only:
# Test-LegacyDiscontinuityDiag.ps1 PD-21 / PD-22 prove the single increment site, the 300 ms judgement, TEL_DISPOSE and that the diff against 87cf543 is additions of the allowed lines only.
$k11Pins = [ordered]@{
    'LegacyTelemetrySession.cs' = 'DD7AD42CB834EE03DB56DD71D2B5BC86AD96D4D0F89B462DD0BAF974BF45AF7B'      # Phase ST-1A (pin moved): was B4693D64... (the LJX-1 edit); the ST-1A edit is ONE key at the end of the station group (STIDX), audited by Test-StationIndexSupplyST1A.ps1 (every datagram equals the audited DLL except for the STIDX part). Phase LJX-1 (pin moved): was 1D796C60... (the audited TEL_DISCONTINUITY edit); the LJX-1 edit of the Session is audited by Test-LegacyJumpExecLJX1.ps1 (S09, LJX-12/16/17/32, golden OFF output)
    'LegacyDataPlaneSink.cs'    = 'C597672FDD5AC62B6CABAF0A94CCEE6C30C94D5C7B5CDB3B123A0C126AC89EC8'      # Phase LJX-1 (pin moved): was 112E6B7B...; the new SendJumpComplete is audited by LJX-29 and S08
    'LegacyApi.cs'              = 'F9202D8FEB0F9B619C6F788D5B85E330700FAF115812A516B911B3EA9E7F8661'
}
$extUsingsBaseline = 9
$extHostIdentBaseline = 14      # Phase LJX-1 (pin moved): +4 = the name AtsExLegacyJumpHost (declaration, constructor, creation); the host jump API itself is pinned by Test-LegacyJumpExecLJX1.ps1 S01 / LJX-28

function NewFilesState {
    $missing = @($newFiles | Where-Object { -not (Test-Path (Join-Path $ProductSrcDir $_)) })
    return $missing
}
function NewCode([string]$name) { return (Code (ReadText (Join-Path $ProductSrcDir $name))) }
function KCheck([string]$id, [scriptblock]$body) {
    $missing = @(NewFilesState)
    if ($missing.Count -gt 0) { Report 'Static' $id 'NEW' 'RED' ('product file(s) absent: ' + ($missing -join ',')) 'files-absent' 'files-absent'; return }
    try {
        $r = & $body
        Report 'Static' $id 'NEW' $(if ($r.Ok) { 'PASS' } else { 'FAIL' }) $r.Detail
    }
    catch { Report 'Static' $id 'NEW' 'FAIL' ('exception ' + $_.Exception.GetType().Name + ' at ' + $_.InvocationInfo.PositionMessage.Replace("`r`n", ' ')) }
}
function CountMatches([string]$pattern, [string[]]$names) {
    $n = 0
    foreach ($f in $names) { $n += ([regex]::Matches((NewCode $f), $pattern)).Count }
    return $n
}

function Run-Static {
    Write-Host '--- Static: K pins of the three new product files'
    KCheck 'K01' { $n = CountMatches '\bHook\b|Synthetic|StartManual|Isolat|Iso2Aalpha|LegacyJumpIso|RequestRecreate|Trace\(' $newFiles;      # Phase LJX-1 (pin moved): the word Executing is the new state of the execution slice and is no longer an isolation-only word
     @{ Ok = ($n -eq 0); Detail = "isolation-only words: $n" } }
    KCheck 'K02' { $n = CountMatches 'BveHacker|AtsEx|BveTypes|BveEx|Handshake|\bCaller\b|IInputDevice|\bInitialize\(|InitializeTimeAndLocation|\bSetTime\(|LegacyApi|\bILegacy(?!Jump)|\bAVAIL\b|JUMP_COMPLETE' $newFiles; @{ Ok = ($n -eq 0); Detail = "BVE / AtsEX / Handshake / Legacy API / AVAIL / JUMP_COMPLETE words: $n (Phase LJX-1 pin moved: the seam names ILegacyJumpCompleteSender / SendJumpComplete are the plane's own vocabulary)" } }
    KCheck 'K03' {
        $all = ($newFiles | ForEach-Object { NewCode $_ }) -join "`n"
        $uses = [regex]::Matches($all, 'JumpCapabilities\.(\w+)')
        $bad = @($uses | Where-Object { $_.Groups[1].Value -ne 'RequestId' })
        $bits = ([regex]::Matches($all, '\b0x1U\b|\b0x2U\b')).Count
        $published = @($uses | Where-Object { $_.Groups[1].Value -eq 'Published' }).Count      # Phase LJX-1 (pin moved): Published (STA | LOC | REQUEST_ID) appears once, in PublishedCapabilities, which returns it only when the execution is active (LJX-14 / LJX-15 / LJX-16)
        @{ Ok = ($uses.Count -ge 1 -and ($bad.Count - $published) -eq 0 -and $published -eq 1 -and $bits -eq 0); Detail = "capability uses: $($uses.Count), not RequestId: $($bad.Count) (of which Published: $published), raw command bits: $bits" }
    }
    KCheck 'K04' { $n = CountMatches 'StationIndex|StationList|\bLocation\b|Math\.Abs|\b50\.0\b|\b100\.0\b|Distance|Tolerance' $newFiles; @{ Ok = ($n -eq 0); Detail = "distance / position / StationIndex words: $n" } }
    KCheck 'K05' {
        $n = CountMatches 'System\.Timers|\bTimer\b|ThreadPool|\bTask\b|\basync\b|\bawait\b' $newFiles
        $threads = @{}
        foreach ($f in $newFiles) { $threads[$f] = ([regex]::Matches((NewCode $f), 'new Thread\(')).Count }
        @{ Ok = ($n -eq 0 -and $threads['LegacyJumpControlPlane.cs'] -eq 1 -and $threads['LegacyJumpEndpoint.cs'] -eq 0 -and $threads['LegacyJumpCommandQueue.cs'] -eq 0); Detail = "timer / pool / task words: $n; new Thread( in the plane: $($threads['LegacyJumpControlPlane.cs'])" }
    }
    KCheck 'K06' {
        $n = CountMatches 'EventWaitHandle|MemoryMappedFile|new Mutex' $newFiles
        $blocks = 0
        foreach ($f in $newFiles) { $blocks += ([regex]::Matches((ReadText (Join-Path $ProductSrcDir $f)), '/\*')).Count }
        @{ Ok = ($n -eq 0 -and $blocks -eq 0); Detail = "kernel object words: $n; block comments: $blocks" }
    }
    KCheck 'K16' {
        $rx = @($newFiles | Where-Object { (NewCode $_) -match 'Receive\(' })
        $n = CountMatches 'TcpListener|TcpClient|UdpClient\(\s*\d' $newFiles
        @{ Ok = ((($rx -join ',') -eq 'LegacyJumpEndpoint.cs') -and $n -eq 0); Detail = "Receive( only in: $($rx -join ','); listener / fixed bind: $n" }
    }
    KCheck 'K07' {
        $all = ($newFiles | ForEach-Object { NewCode $_ }) -join "`n"
        $cur = ([regex]::Matches($all, '\.CurrentJump')).Count
        $lit = @($newFiles | Where-Object { (NewCode $_) -match '"[^"]*\.LegacyJump"' })
        $viaNames = (NewCode 'LegacyJumpControlPlane.cs') -match 'LegacyJumpNames\.For'
        @{ Ok = ($cur -eq 0 -and ($lit -join ',') -eq 'LegacyJumpEndpoint.cs' -and $viaNames); Detail = ".CurrentJump: $cur; .LegacyJump literal only in: $($lit -join ','); the plane names its mapping through LegacyJumpNames: $viaNames" }
    }
    KCheck 'K10' {
        $shared = @('Telemetry\Shared\DataPlaneProtocol.cs', 'Telemetry\Shared\TelemetryDirectoryReader.cs', 'Telemetry\Shared\TelemetryContract.cs') | ForEach-Object { Join-Path $Root $_ }
        $shared += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentDataPlane.cs')
        $shared += (Join-Path $repo 'TsScoringPlugin\TsScoringPlugin\CurrentJumpEndpoint.cs')
        $own = ($newFiles + 'LegacyJumpExecutor.cs') | ForEach-Object { Join-Path $ProductSrcDir $_ }      # Phase LJX-1 (pin moved): the executor file is part of the host independent plane
        $out = Join-Path $LogDir 'k10-bcl-only.dll'
        Add-Type -Path ($shared + $own) -ReferencedAssemblies @('System.dll', 'System.Core.dll') -OutputAssembly $out -OutputType Library -IgnoreWarnings
        $asm = [Reflection.Assembly]::LoadFrom($out)
        $refs = @($asm.GetReferencedAssemblies() | ForEach-Object { $_.Name })
        $bad = @($refs | Where-Object { $_ -notin 'mscorlib', 'System', 'System.Core' })
        @{ Ok = ($bad.Count -eq 0); Detail = "compiled with System / System.Core only (no BVE, no AtsEX reference); references: $($refs -join ',')" }
    }
    KCheck 'K12' {
        $ext = ReadText (Join-Path $ProductSrcDir 'LegacyTelemetryExtension.cs')
        $code = Code $ext
        $iJump = $code.IndexOf('jump.Dispose()')
        $iSess = $code.IndexOf('session.OnDispose()')
        $usings = @($ext -split "`n" | Where-Object { $_ -match '^\s*using\s' }).Count
        $hostIdent = ([regex]::Matches($code, 'AtsEx|BveTypes')).Count
        # every line that touches the plane sits inside a try block (a brace-aware walk: the block that opened with try)
        $depthKinds = New-Object System.Collections.Generic.List[string]
        $bareJump = 0
        $lines = $code -split "`n"
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $l = $lines[$i]
            if ($l -match 'jump\.|LegacyJumpControlPlane' -and $l -notmatch '^\s*private\s') {
                $inTry = ($l -match '\btry\b') -or ($depthKinds.Contains('try'))
                if (-not $inTry) { $bareJump++ }
            }
            $kind = 'other'
            if ($l -match '\btry\b') { $kind = 'try' }
            elseif ($l -match '\bcatch\b') { $kind = 'catch' }
            elseif ($i -gt 0 -and $lines[$i - 1] -match '^\s*try\s*$' -and $l -match '^\s*\{') { $kind = 'try' }
            foreach ($ch in $l.ToCharArray()) {
                if ($ch -eq '{') { $depthKinds.Add($kind); $kind = 'other' }
                elseif ($ch -eq '}' -and $depthKinds.Count -gt 0) { $depthKinds.RemoveAt($depthKinds.Count - 1) }
            }
        }
        $ok = ($iJump -ge 0 -and $iSess -ge 0 -and $iJump -lt $iSess -and $bareJump -eq 0 -and $usings -eq $extUsingsBaseline -and $hostIdent -eq $extHostIdentBaseline)
        @{ Ok = $ok; Detail = "jump.Dispose() before session.OnDispose(): $($iJump -ge 0 -and $iJump -lt $iSess); plane lines outside a try: $bareJump; using lines $usings (baseline $extUsingsBaseline); AtsEx / BveTypes identifiers $hostIdent (baseline $extHostIdentBaseline)" }
    }
    KCheck 'K14' {
        $c = NewCode 'LegacyJumpEndpoint.cs'
        $m = [regex]::Match($c, 'NeverBindPorts[^;]*;')
        $lits = CountMatches '5432[12]' $newFiles
        @{ Ok = ($m.Success -and $m.Value -match 'TelemetryContract\.Port\s*\+\s*1' -and $m.Value -match 'TelemetryContract\.Port' -and $lits -eq 0); Detail = "NeverBindPorts declaration: $($m.Value); fixed port literals in the three files: $lits" }
    }
    KCheck 'K15' {
        $c = NewCode 'LegacyJumpEndpoint.cs'
        $cs = [regex]::Match($c, 'class LegacyJumpNames[\s\S]*?"(Local\\\\TSScoringPlugin\.v1\.)"\s*\+\s*\w+(?:\.ToString\(\))?\s*\+\s*"(\.LegacyJump)"')
        $pyText = ReadText (Join-Path $PyRoot 'dataplane_contract.py')
        $py = [regex]::Match($pyText, 'def legacy_jump_name\(pid\):[^\r\n]*f"(Local\\\\TSScoringPlugin\.v1\.)\{pid\}(\.LegacyJump)"')
        @{ Ok = ($cs.Success -and $py.Success -and $cs.Groups[1].Value -eq $py.Groups[1].Value -and $cs.Groups[2].Value -eq $py.Groups[2].Value); Detail = "C# prefix/suffix: $($cs.Groups[1].Value) $($cs.Groups[2].Value); Python: $($py.Groups[1].Value) $($py.Groups[2].Value)" }
    }
    # K13: the version of the build that has the plane
    $ai = Join-Path $ProductSrcDir 'AssemblyInfo.cs'
    if (Test-Path $ai) {
        $t = ReadText $ai
        $vs = @([regex]::Matches($t, '\[assembly: Assembly(?:File|Informational)?Version\("([^"]+)"\)\]') | ForEach-Object { $_.Groups[1].Value })
        $ok = ($vs.Count -eq 3 -and @($vs | Where-Object { $_ -ne '0.5.0.0' -and $_ -ne '0.6.0.0' }).Count -eq 0)      # Phase LJX-1 (pin moved): 0.5.0.0 or 0.6.0.0
        Report 'Static' 'K13' 'NEW' $(if ($ok) { 'PASS' } else { 'RED' }) ('AssemblyInfo versions: ' + ($vs -join ',') + ' (the build with the plane is 0.5.0.0)') $(if ($ok) { '' } else { 'version-not-0.5.0.0' }) 'version-not-0.5.0.0'
    }
    else { Report 'Static' 'K13' 'NEW' 'RED' 'AssemblyInfo.cs absent' 'files-absent' 'files-absent' }

    Write-Host '--- Static: regression guards (GUARD)'
    foreach ($k in $k11Pins.Keys) {
        $sha = Sha (Join-Path $ProductSrcDir $k)
        Report 'Static' ('K11:' + $k) 'GUARD' $(if ($sha -eq $k11Pins[$k]) { 'PASS' } else { 'FAIL' }) ("sha256 " + $sha)
    }
    if (Test-Path $DllPath) {
        $types = @(); $pub = @()
        $copy = Join-Path $LogDir 'k08-copy.dll'
        Copy-Item $DllPath $copy -Force
        [JumpTestResolver]::Install(@($LogDir, $legacyHost))
        $asm = [Reflection.Assembly]::LoadFrom($copy)
        try { $types = @($asm.GetTypes()) } catch [Reflection.ReflectionTypeLoadException] { $types = @($_.Exception.Types | Where-Object { $_ }) }
        $names = @($types | ForEach-Object { $_.FullName })
        $dups = @($names | Group-Object | Where-Object { $_.Count -gt 1 })
        $pub = @($types | Where-Object { $_.IsPublic -and -not $_.IsNested } | ForEach-Object { $_.Name })
        $hasHost = ($names -contains 'TSScoringPlugin.Telemetry.LegacyTelemetrySession')
        $pubOk = if ($hasHost) { ($pub -join ',') -eq 'TsScoringLegacyTelemetryExtension' } else { $pub.Count -le 1 }
        Report 'Static' 'K08' 'GUARD' $(if ($dups.Count -eq 0 -and $pubOk) { 'PASS' } else { 'FAIL' }) ("types " + $types.Count + "; duplicates " + $dups.Count + "; public: " + ($pub -join ','))
    }
    else { Report 'Static' 'K08' 'GUARD' 'FAIL' ('product DLL absent: ' + $DllPath) }

    Write-Host '--- Static: lint of the 2A-alpha test sources (K17)'
    Run-Lint
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# lint of the test sources: what Verify-PhaseC3 / Verify-PhaseL1 would say about them, plus this slice's own rules
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Run-Lint {
    $c3Words = 'UdpClient', 'TcpClient', 'Socket', 'Registry', 'Microsoft\.Win32', 'SetWindowsHookEx', 'Thread\.Sleep', 'System\.Timers', 'NamedPipe', 'Global\\\\', 'Process\.Start', 'ProcessStartInfo', 'Python', 'python', 'main\.py', 'FileStream|FileMode|\bFile\.|StreamWriter|AppendAllText', 'new Mutex|Mutex ', 'DllImport', 'ScenarioReady'
    $leakWords = 'BveEx|BveTypes|IBveHacker|PluginBuilder|ClassWrappers|AssemblyPluginBase|IExtension|PluginAttribute|AtsEx|LocationManager|UserVehicleLocationManager|ExtensionTickResult|TickResult'
    $a4a = Join-Path $testsDir 'LegacyJumpPlaneTestFixture.cs'
    $a4b = Join-Path $testsDir 'LegacyJumpPlaneTestKit.cs'
    $a10 = Join-Path $testsDir 'LegacyIlCallScan.cs'
    function LineHits([string]$path, [string]$pattern, [bool]$skipLineComments) {
        $n = 0
        foreach ($line in [IO.File]::ReadAllLines($path)) {
            if ($skipLineComments -and $line.TrimStart().StartsWith('//')) { continue }
            if ($line -match $pattern) { $n++ }
        }
        return $n
    }
    function CodeHits([string]$path, [string]$pattern) {
        $n = 0
        foreach ($line in [IO.File]::ReadAllLines($path)) {
            if ($line.TrimStart().StartsWith('//')) { continue }
            $code = [regex]::Replace($line, '"(?:[^"\\]|\\.)*"', '""')
            $code = [regex]::Replace($code, '//.*$', '')
            if ($code -cmatch $pattern) { $n++ }
        }
        return $n
    }
    # the files that Verify-PhaseC3 still scans after the exact-path exclusion of A4b (X6): A4a and A10
    foreach ($f in @($a4a, $a10)) {
        $bad = @()
        foreach ($w in $c3Words) { $h = LineHits $f $w $true; if ($h -gt 0) { $bad += ($w + 'x' + $h) } }
        Report 'Lint' ('K17:C3-scan:' + (Split-Path $f -Leaf)) 'GUARD' $(if ($bad.Count -eq 0) { 'PASS' } else { 'FAIL' }) ('C3 source scan words (the file is not excluded by exact path): ' + ($bad -join ', '))
    }
    foreach ($f in @($a4a, $a4b, $a10)) {
        $leaf = Split-Path $f -Leaf
        $ok = $true; $why = @()
        if ((CodeHits $f $leakWords) -gt 0) { $ok = $false; $why += 'BveEx / AtsEx / TickResult word in code' }
        if ((LineHits $f '\bReceive\b' $false) -gt 0) { $ok = $false; $why += 'the word Receive' }
        if ((LineHits $f 'new Thread\(' $false) -gt 0) { $ok = $false; $why += 'new Thread( (Verify-PhaseL1 allows it in three files only)' }
        if ((LineHits $f '\.Message\b|MachineName|UserName|GetFolderPath|C:\\Users' $false) -gt 0) { $ok = $false; $why += 'privacy audit word' }
        $bytes = [IO.File]::ReadAllBytes($f)
        if (@($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) { $ok = $false; $why += 'non-ASCII bytes' }
        if (@($bytes | Where-Object { $_ -eq 13 }).Count -gt 0) { $ok = $false; $why += 'CR bytes (the repository uses LF)' }
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { $ok = $false; $why += 'BOM' }
        Report 'Lint' ('K17:rules:' + $leaf) 'GUARD' $(if ($ok) { 'PASS' } else { 'FAIL' }) ($why -join '; ')
    }
    $ok = $true; $why = @()
    foreach ($f in @($a4a, $a10)) { if ((LineHits $f '\bSocket\b|ILegacyJumpSocket' $false) -gt 0) { $ok = $false; $why += (Split-Path $f -Leaf) } }
    Report 'Lint' 'K17:A4a-names-no-port-type' 'GUARD' $(if ($ok) { 'PASS' } else { 'FAIL' }) ('A4a / A10 name no port seam type: ' + ($why -join ','))
    # script lint: parser, non-ASCII, backtick continuation, unresolvable type literals
    foreach ($s in @((Join-Path $testsDir 'Test-LegacyJumpPlane2A.ps1'), (Join-Path $testsDir 'Serve-LegacyJumpPlane2A.ps1'))) {
        $leaf = Split-Path $s -Leaf
        $errs = $null; $tokens = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($s, [ref]$tokens, [ref]$errs)
        $bytes = [IO.File]::ReadAllBytes($s)
        $nonAscii = @($bytes | Where-Object { $_ -gt 127 }).Count
        $btLines = @([IO.File]::ReadAllLines($s) | Where-Object { $_ -match '`\s*$' }).Count
        $badTypes = @()
        $typeNodes = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.TypeExpressionAst] -or $n -is [System.Management.Automation.Language.TypeConstraintAst] }, $true))
        foreach ($tn in $typeNodes) {
            $name = $tn.TypeName.Name
            try { $t = $tn.TypeName.GetReflectionType() } catch { $t = $null }
            if ($null -eq $t -and $name -notmatch '^(JumpTestResolver|ServeResolver|ordered)$') { $badTypes += $name }
        }
        $ok = ($errs.Count -eq 0 -and $nonAscii -eq 0 -and $btLines -eq 0 -and $badTypes.Count -eq 0)
        Report 'Lint' ('K17:script:' + $leaf) 'GUARD' $(if ($ok) { 'PASS' } else { 'FAIL' }) ("parse errors " + $errs.Count + "; non-ASCII " + $nonAscii + "; backtick continuations " + $btLines + "; unresolvable type literals: " + ($badTypes -join ','))
    }
    foreach ($p in @((Join-Path $repo 'tests\test_jump_directory_reader_2a.py'), (Join-Path $repo 'tests\test_legacy_jump_plane_interop_2a.py'), (Join-Path $repo 'tests\test_dataplane_contract_pid_d1.py'))) {
        $leaf = Split-Path $p -Leaf
        $bytes = [IO.File]::ReadAllBytes($p)
        $nonAscii = @($bytes | Where-Object { $_ -gt 127 }).Count
        $cr = @($bytes | Where-Object { $_ -eq 13 }).Count
        $compile = & $python -I -B -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read()); print('ok')" $p
        Report 'Lint' ('K17:python:' + $leaf) 'GUARD' $(if ($compile -eq 'ok' -and $nonAscii -eq 0 -and $cr -eq 0) { 'PASS' } else { 'FAIL' }) ("syntax " + $compile + "; non-ASCII " + $nonAscii + "; CR " + $cr)
    }
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# compile the tests against a product DLL, run them
# ---------------------------------------------------------------------------------------------------------------------------------------------
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class JumpTestResolver
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
    $sources = @((Join-Path $testsDir 'LegacyJumpPlaneTestKit.cs'), (Join-Path $testsDir 'LegacyJumpPlaneTestFixture.cs'), (Join-Path $testsDir 'LegacyIlCallScan.cs'))
    Add-Type -Path $sources -ReferencedAssemblies @($dllCopy, 'System.dll', 'System.Core.dll') -OutputAssembly $fixDll -OutputType Library -IgnoreWarnings
    [JumpTestResolver]::Install(@($work, $legacyHost))
    $prod = [Reflection.Assembly]::LoadFrom($dllCopy)
    $fix = [Reflection.Assembly]::LoadFrom($fixDll)
    return [pscustomobject]@{ Prod = $prod; Fix = $fix; Type = $fix.GetType('TsScoringLegacyTelemetryTests.LegacyJumpPlaneTestFixture'); Work = $work }
}

# the Stage S1 state: every NEW case reaches the first pinned product element and finds it absent. The code names that element.
$productCases = [ordered]@{
    'ITR-01' = 'type:LegacyJumpEnvironment'; 'ITR-02' = 'type:LegacyJumpEnvironment'; 'ITR-03' = 'shared-type:JumpDirectoryPublisher'; 'ITR-04' = 'type:LegacyJumpEnvironment'
    'ITR-05' = 'type:LegacyJumpEnvironment'; 'ITR-06' = 'type:LegacyJumpEnvironment'; 'ITR-07' = 'type:LegacyJumpEnvironment'; 'ITR-08' = 'type:LegacyJumpEnvironment'
    'ITR-09' = 'type:LegacyJumpEnvironment'; 'ITR-10' = 'type:LegacyJumpCommandState'; 'ITR-11' = 'type:LegacyJumpEnvironment'; 'ITR-12' = 'type:LegacyJumpEnvironment'
    'ITR-13' = 'type:LegacyJumpControlPlane'; 'ITR-14' = 'type:LegacyJumpEnvironment'; 'ITR-15' = 'type:LegacyJumpEnvironment'; 'ITR-16' = 'type:LegacyJumpEnvironment'
    'EX-01' = 'type:LegacyJumpEnvironment'; 'EX-02' = 'type:LegacyJumpEnvironment'; 'EX-03' = 'type:LegacyJumpNames'
    'WIN-01' = 'type:LegacyJumpEnvironment'; 'WIN-02' = 'type:LegacyJumpEnvironment'; 'WIN-03' = 'type:LegacyJumpEnvironment'; 'WIN-04' = 'type:LegacyJumpEnvironment'
    'PT-01' = 'type:LegacyJumpEnvironment'; 'PT-02' = 'type:LegacyJumpEnvironment'; 'PT-03' = 'type:LegacyJumpControlPlane'; 'PT-04' = 'type:LegacyJumpEnvironment'
    'PT-05' = 'type:LegacyJumpEnvironment'; 'PT-06' = 'type:LegacyJumpEnvironment'; 'PT-07' = 'type:LegacyJumpEnvironment'; 'PT-08' = 'type:LegacyJumpEnvironment'
    'PT-09' = 'type:LegacyJumpEnvironment'; 'WIN-99' = 'type:LegacyJumpEnvironment'
}
$selfIds = @('SELF-01', 'SELF-02', 'SELF-03', 'SELF-04', 'SELF-05', 'SELF-06', 'SELF-07', 'SELF-08', 'SELF-09', 'SELF-10', 'SELF-11', 'SELF-12', 'SELF-13', 'SELF-14', 'SELF-15', 'SELF-16', 'SELF-17', 'SELF-18', 'SELF-19')

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

function Run-Self {
    Write-Host '--- Self: the kit self tests and the IL scanner proofs (no product needed)'
    if (-not (Test-Path $DllPath)) { $inconclusive.Add('product DLL absent: ' + $DllPath); return }
    $b = Build-Fixture $DllPath 'work-self'
    $rr = $b.Type.GetMethod('RunSelf').Invoke($null, @($b.Prod, ('self' + (Get-Date -Format 'HHmmss')), $repo))
    Save-RunResult 'self' $rr
    $found = @($rr.Tests | ForEach-Object { $_.Id } | Sort-Object)
    Report 'Self' 'SELF-count' 'SELF' $(if (($found -join ',') -eq ($selfIds -join ',') -and $rr.Discovered -eq $rr.Invoked) { 'PASS' } else { 'FAIL' }) ("discovered " + $rr.Discovered + " = invoked " + $rr.Invoked + "; ids " + ($found -join ','))
    foreach ($t in $rr.Tests) { Report 'Self' $t.Id 'SELF' $(if ($t.Outcome -eq 'PASS') { 'PASS' } elseif ($t.Outcome -eq 'INCONCLUSIVE') { 'INCONCLUSIVE' } else { 'FAIL' }) ($t.Label + ' ' + $t.FailText) }
    # the IL scanner proves itself on probes with known contents (positive controls) and on an empty selection (negative control)
    $probeSrc = @'
namespace Probe
{
    public class CurrentJumpEndpoint { public CurrentJumpEndpoint() { } public static object Create(int a) { return new object(); } }
    public class Api { public void SetTime(int t) { } public void Initialize() { } public void InitializeTimeAndLocation() { } }
    public class LegacyJumpGood { public int Add(int a, int b) { return a + b; } public string Name() { return string.Concat("a", "b"); } }
    public class LegacyJumpBadCreate { public object Go() { return CurrentJumpEndpoint.Create(1); } }
    public class LegacyJumpBadCtor { public object Go() { return new CurrentJumpEndpoint(); } }
    public class LegacyJumpBadApi { public void Go(Api a) { a.SetTime(1); a.Initialize(); a.InitializeTimeAndLocation(); } }
    public class LegacyJumpBadTimer { public void Go() { System.Timers.Timer t = new System.Timers.Timer(5); t.Dispose(); } }
    public class LegacyJumpGeneric { public int Go() { System.Collections.Generic.List<int> l = new System.Collections.Generic.List<int>(); l.Add(3); try { return l[0]; } catch (System.Exception) { return 0; } } }
}
'@
    $probe = Join-Path $LogDir 'ilprobe.dll'
    Add-Type -TypeDefinition $probeSrc -OutputAssembly $probe -OutputType Library -IgnoreWarnings
    $pa = [Reflection.Assembly]::LoadFrom($probe)
    $scan = $b.Fix.GetType('TsScoringLegacyTelemetryTests.LegacyIlCallScan')
    $good = $scan::ScanPrefix($pa, 'Probe.LegacyJumpGood')
    Report 'Self' 'IL-1' 'SELF' $(if ($good.TypesScanned -eq 1 -and $good.MethodsScanned -ge 3 -and $good.CallsSeen -ge 2 -and -not $scan::CallsAnyOf($good, 'Probe.')) { 'PASS' } else { 'FAIL' }) ("clean type: types " + $good.TypesScanned + ", methods " + $good.MethodsScanned + ", calls " + $good.CallsSeen)
    $bc = $scan::ScanPrefix($pa, 'Probe.LegacyJumpBadCreate')
    Report 'Self' 'IL-2' 'SELF' $(if ($scan::CallsAnyOf($bc, 'Probe.CurrentJumpEndpoint::Create')) { 'PASS' } else { 'FAIL' }) 'a call to CurrentJumpEndpoint.Create is found'
    $bk = $scan::ScanPrefix($pa, 'Probe.LegacyJumpBadCtor')
    Report 'Self' 'IL-3' 'SELF' $(if ($scan::CallsAnyOf($bk, 'Probe.CurrentJumpEndpoint::.ctor')) { 'PASS' } else { 'FAIL' }) 'a newobj of CurrentJumpEndpoint is found'
    $ba = $scan::ScanPrefix($pa, 'Probe.LegacyJumpBadApi')
    $names = @($ba.Calls | ForEach-Object { $scan::MethodNameOf($_) })
    Report 'Self' 'IL-4' 'SELF' $(if (($names -contains 'SetTime') -and ($names -contains 'Initialize') -and ($names -contains 'InitializeTimeAndLocation')) { 'PASS' } else { 'FAIL' }) ('Legacy API style calls are found: ' + ($names -join ','))
    $bt = $scan::ScanPrefix($pa, 'Probe.LegacyJumpBadTimer')
    Report 'Self' 'IL-5' 'SELF' $(if (($bt.ReferencedTypes -contains 'System.Timers.Timer') -and ($bt.ExternalAssemblies -contains 'System')) { 'PASS' } else { 'FAIL' }) ('a timer type and its assembly are found: ' + ($bt.ExternalAssemblies -join ','))
    $bg = $scan::ScanPrefix($pa, 'Probe.LegacyJumpGeneric')
    Report 'Self' 'IL-6' 'SELF' $(if ($bg.MethodsScanned -ge 1 -and $scan::CallsAnyOf($bg, 'System.Collections.Generic.List`1::Add') -and ($bg.ReferencedTypes -contains 'System.Exception')) { 'PASS' } else { 'FAIL' }) ('generic and catch-clause tokens are read: ' + (($bg.Calls) -join ','))
    $none = $scan::ScanPrefix($pa, 'Nothing.Matches.This')
    Report 'Self' 'IL-7' 'SELF' $(if ($none.TypesScanned -eq 0 -and $none.MethodsScanned -eq 0) { 'PASS' } else { 'FAIL' }) 'an empty selection reports 0 types (the "vacuous pass" guard works: users must assert non-zero counts)'
    $all = $scan::ScanAllExcept($pa, [string[]]@('Probe.CurrentJumpEndpoint'))
    $selfCalls = @($all.Calls | Where-Object { $_.StartsWith('Probe.CurrentJumpEndpoint::') })
    Report 'Self' 'IL-8' 'SELF' $(if ($all.TypesScanned -ge 7 -and $selfCalls.Count -eq 2) { 'PASS' } else { 'FAIL' }) ('ScanAllExcept sees the two foreign calls (Create, ctor) outside the excluded type: ' + $selfCalls.Count)
    $rawProd = $scan::ScanPrefix($b.Prod, 'TSScoringPlugin.DataPlane.DataPlaneProtocol')
    Report 'Self' 'IL-9' 'SELF' $(if ($rawProd.TypesScanned -ge 1 -and $rawProd.MethodsScanned -ge 10 -and $rawProd.CallsSeen -ge 20) { 'PASS' } else { 'FAIL' }) ('the scanner reads a real product type: ' + $rawProd.MethodsScanned + ' methods, ' + $rawProd.CallsSeen + ' calls')
}

function Run-Product {
    Write-Host '--- Product: the 33 cases against the product DLL'
    if (-not (Test-Path $DllPath)) { $inconclusive.Add('product DLL absent: ' + $DllPath); return }
    $b = Build-Fixture $DllPath 'work-product'
    $found = @($b.Type.GetMethod('DiscoverIds').Invoke($null, $null))
    $expectedIds = @($productCases.Keys | Sort-Object)
    Report 'Product' 'count' 'SELF' $(if (($found -join ',') -eq ($expectedIds -join ',')) { 'PASS' } else { 'FAIL' }) ("discovered " + $found.Count + " case methods by reflection; the planned set has " + $expectedIds.Count)
    [string[]]$onlyIds = @($Only -split ',' | Where-Object { $_ })
    $rr = $b.Type.GetMethod('Run').Invoke($null, @($b.Prod, ('p' + (Get-Date -Format 'HHmmss')), $repo, $onlyIds))
    Save-RunResult 'product' $rr
    $expectInvoked = if ($onlyIds.Count -gt 0) { $onlyIds.Count } else { $found.Count }
    Report 'Product' 'invoked' 'SELF' $(if ($rr.Discovered -eq $found.Count -and $rr.Invoked -eq $expectInvoked) { 'PASS' } else { 'FAIL' }) ("discovered " + $rr.Discovered + " = invoked " + $rr.Invoked + " (" + $rr.Header + ")")
    foreach ($t in $rr.Tests) {
        $detail = $t.Label
        if ($t.Outcome -eq 'FAIL') { $detail = $t.FailText }
        Report 'Product' $t.Id 'NEW' $t.Outcome ("checks " + $t.Checks + " failed " + $t.Failed + " " + $detail) $t.RedCode $productCases[$t.Id]
    }
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------------------------------------------------------------------------
# the Stage S1 state of the new Python tests: the expected [contract:...] tag of every test that must be RED now; the existing tests of the file stay GREEN
$pyExpect = [ordered]@{
    'test_jump_directory_reader_2a' = [ordered]@{
        'test_pr1_no_handle_after_send_complete_idle_and_outstanding' = 'reader-holds-handle'
        'test_pr2_every_exit_of_the_read_closes_the_mapping' = 'reader-holds-handle'
        'test_pr3_withdrawn_and_closed_leave_no_handle_and_a_new_endpoint_is_a_new_one' = 'reader-holds-handle'
        'test_pr4_outstanding_request_reads_open_read_close_each_watch_and_only_its_own_name' = 'name-resolution-api-missing'
        'test_pr4_outstanding_request_ends_when_its_directory_disappears' = 'reader-holds-handle'
        'test_pr4_timeout_is_unchanged_and_releases' = 'reader-holds-handle'
        'test_pr5_name_resolution' = 'name-resolution-api-missing'
        'test_pr6_request_id_only_legacy_directory_sends_nothing' = 'name-resolution-api-missing'
        'test_read_directories_is_read_only_and_closes' = 'name-resolution-api-missing'
        'test_pr8_reader_cycle_time_is_recorded' = 'read-directories-missing'
        'test_pr11_client_code_static_guards' = 'attached-flag'
    }
    'test_legacy_jump_plane_interop_2a' = [ordered]@{
        'test_itr12_request_id_only_the_product_client_refuses_and_the_plane_receives_nothing' = 'plane-absent'
        'test_pr7_each_poll_then_dispose_and_create_succeeds_at_the_first_attempt' = 'plane-absent'
        'test_pr7_negative_control_a_retained_handle_blocks_the_recreation' = 'plane-absent'
        'test_recreation_publishes_new_values_and_the_reader_never_uses_the_old_ones' = 'plane-absent'
        'test_zz_after_the_plane_finished_the_mapping_name_and_the_port_are_free' = 'plane-absent'
    }
    'test_dataplane_contract_pid_d1' = [ordered]@{
        'test_legacy_jump_names_pid_d4_2a' = 'name-resolution-api-missing'
        'test_legacy_and_current_jump_names_differ_only_in_the_suffix_pid_d4_2a' = 'name-resolution-api-missing'
    }
}
$pyGuardCounts = @{ 'test_dataplane_contract_pid_d1' = 10 }       # the tests of that file that existed before this slice and must stay GREEN

function Parse-Unittest([string]$text) {
    $res = @{ Ran = 0; Tests = @{} }
    $m = [regex]::Match($text, '(?m)^Ran (\d+) tests?')
    if ($m.Success) { $res.Ran = [int]$m.Groups[1].Value }
    $blocks = [regex]::Split($text, '(?m)^={70}\r?$')
    foreach ($blk in $blocks) {
        $h = [regex]::Match($blk, '(?m)^(FAIL|ERROR): (\w+) \(([\w.]+)\)')
        if (-not $h.Success) { continue }
        $name = $h.Groups[2].Value
        $tag = ''
        $tm = [regex]::Match($blk, '\[contract:([a-z-]+)\]')
        if ($tm.Success) { $tag = $tm.Groups[1].Value }
        $kind = $h.Groups[1].Value
        if (-not $res.Tests.ContainsKey($name)) { $res.Tests[$name] = @{ Kind = $kind; Tag = $tag; Count = 1 } }
        else { $res.Tests[$name].Count++; if ($res.Tests[$name].Tag -eq '' -and $tag -ne '') { $res.Tests[$name].Tag = $tag } }
    }
    return $res
}

function Run-Python {
    Write-Host '--- Python: Reader, interop and contract tests'
    if (-not (Test-Path $python)) { $inconclusive.Add('python not found'); return }
    $env:LEGACYJUMP_2A_PYROOT = $PyRoot
    if (Test-Path $DllPath) { $env:LEGACYJUMP_2A_PRODUCT_DLL = $DllPath }
    Push-Location $repo
    try {
        foreach ($mod in $pyExpect.Keys) {
            $o = Join-Path $LogDir ('py-' + $mod + '.out.txt')
            $e = Join-Path $LogDir ('py-' + $mod + '.err.txt')
            $wd = $repo
            if ($mod -eq 'test_dataplane_contract_pid_d1' -and ([IO.Path]::GetFullPath($PyRoot).TrimEnd('\') -ne [IO.Path]::GetFullPath($repo).TrimEnd('\'))) {
                # that test file has no root override: run a copy of it next to the other contract module
                $tree = Join-Path $LogDir 'c8tree'
                New-Item -ItemType Directory -Force (Join-Path $tree 'tests') | Out-Null
                Copy-Item (Join-Path $PyRoot 'dataplane_contract.py') $tree -Force
                Copy-Item (Join-Path $repo 'tests\test_dataplane_contract_pid_d1.py') (Join-Path $tree 'tests') -Force
                $wd = $tree
            }
            $p = Start-Process -FilePath $python -ArgumentList @('-I', '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', ($mod + '.py'), '-v') -WorkingDirectory $wd -NoNewWindow -PassThru -RedirectStandardOutput $o -RedirectStandardError $e
            $null = $p.Handle
            if (-not $p.WaitForExit(900000)) { try { Stop-Process -Id $p.Id -Force } catch { }; Report 'Python' $mod 'NEW' 'FAIL' 'timed out'; continue }
            $p.WaitForExit()
            $text = (ReadText $e) + "`n" + (ReadText $o)
            $parsed = Parse-Unittest $text
            $table = $pyExpect[$mod]
            $expectedFailing = @($table.Keys)
            $failed = @($parsed.Tests.Keys)
            $untagged = @($failed | Where-Object { $parsed.Tests[$_].Tag -eq '' })
            if ($Expect -eq 'green') {
                Report 'Python' $mod 'NEW' $(if ($failed.Count -eq 0 -and $parsed.Ran -gt 0) { 'PASS' } else { 'FAIL' }) ("ran " + $parsed.Ran + ", failed " + $failed.Count + ": " + ($failed -join ','))
            }
            else {
                foreach ($t in $expectedFailing) {
                    $got = if ($parsed.Tests.ContainsKey($t)) { $parsed.Tests[$t].Tag } else { '' }
                    $outcome = if ($parsed.Tests.ContainsKey($t) -and $got -ne '') { 'RED' } elseif ($parsed.Tests.ContainsKey($t)) { 'FAIL' } else { 'PASS' }
                    Report 'Python' ($mod + '::' + $t) 'NEW' $outcome ("tag [" + $got + "]") $got $table[$t]
                }
                $unexpectedFails = @($failed | Where-Object { $expectedFailing -notcontains $_ })
                Report 'Python' ($mod + '::others') 'GUARD' $(if ($unexpectedFails.Count -eq 0 -and $untagged.Count -eq 0) { 'PASS' } else { 'FAIL' }) ("ran " + $parsed.Ran + "; failures outside the expected-RED list: " + ($unexpectedFails -join ',') + "; failures without a [contract:...] tag: " + ($untagged -join ','))
                if ($pyGuardCounts.ContainsKey($mod)) {
                    $guards = $parsed.Ran - $expectedFailing.Count
                    Report 'Python' ($mod + '::guards') 'GUARD' $(if ($guards -eq $pyGuardCounts[$mod]) { 'PASS' } else { 'FAIL' }) ("pre-existing tests that stay GREEN: " + $guards + " (expected " + $pyGuardCounts[$mod] + ")")
                }
            }
        }
    }
    finally {
        Pop-Location
        Remove-Item Env:\LEGACYJUMP_2A_PYROOT -ErrorAction SilentlyContinue
        Remove-Item Env:\LEGACYJUMP_2A_PRODUCT_DLL -ErrorAction SilentlyContinue
    }
    $stray = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and $_.CommandLine -match 'Serve-LegacyJumpPlane2A' })
    Report 'Python' 'residue' 'GUARD' $(if ($stray.Count -eq 0) { 'PASS' } else { 'FAIL' }) ("served-plane processes left behind: " + $stray.Count)
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# Mutation: every mutant must be detected, the reference must stay green
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Run-Mutation {
    Write-Host '--- Mutation: the cases must detect every mutant'
    if ([string]::IsNullOrEmpty($MutantsDir) -or -not (Test-Path (Join-Path $MutantsDir 'mutants.tsv'))) { $inconclusive.Add('-MutantsDir with mutants.tsv is required'); return }
    $rows = @(Import-Csv -Delimiter "`t" -Path (Join-Path $MutantsDir 'mutants.tsv'))
    $ref = $rows | Where-Object { $_.id -eq 'REFERENCE' } | Select-Object -First 1
    if ($null -eq $ref) { $inconclusive.Add('mutants.tsv has no REFERENCE row'); return }
    foreach ($r in $rows) {
        $dll = Join-Path $MutantsDir $r.dll
        $sub = Join-Path $LogDir ('mut-' + $r.id)
        $childArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-Mode', 'Product', '-Expect', 'green', '-DllPath', $dll, '-LogDir', $sub, '-Tag', ('m-' + $r.id))
        if ($r.id -ne 'REFERENCE') { $childArgs += @('-Only', [string]$r.detectors) }
        $out = & powershell @childArgs 2>&1 | Out-String
        [IO.File]::WriteAllText((Join-Path $LogDir ('mut-' + $r.id + '.console.txt')), $out)
        $tsv = Join-Path $sub 'results.tsv'
        if (-not (Test-Path $tsv)) { Report 'Mutation' $r.id 'SELF' 'FAIL' 'the child run produced no results.tsv'; continue }
        $cases = @(Import-Csv -Delimiter "`t" -Path $tsv | Where-Object { $_.section -eq 'Product' -and $_.id -match '^(ITR|EX|WIN|PT)-' })
        if ($r.id -eq 'REFERENCE') {
            $bad = @($cases | Where-Object { $_.outcome -ne 'PASS' })
            Report 'Mutation' 'REFERENCE' 'SELF' $(if ($bad.Count -eq 0 -and $cases.Count -eq 33) { 'PASS' } else { 'FAIL' }) ("the unmutated reference: " + $cases.Count + " cases, not PASS: " + (($bad | ForEach-Object { $_.id }) -join ','))
        }
        else {
            $hit = @($cases | Where-Object { $_.outcome -eq 'FAIL' } | ForEach-Object { $_.id })
            $still = @($cases | Where-Object { $_.outcome -eq 'PASS' } | ForEach-Object { $_.id })
            Report 'Mutation' $r.id 'SELF' $(if ($hit.Count -ge 1) { 'PASS' } else { 'FAIL' }) ($r.description + " | detected by: " + ($hit -join ',') + " | still PASS: " + ($still -join ','))
        }
    }
}
# ---------------------------------------------------------------------------------------------------------------------------------------------
# Regress: the existing suites against the Stage S0 baseline
# ---------------------------------------------------------------------------------------------------------------------------------------------
function Run-Regress {
    Write-Host '--- Regress: existing suites (Stage S0 job list, Test-JumpProbeB1 is never run here) against the baseline'
    if ([string]::IsNullOrEmpty($BaselineChecksTsv) -or -not (Test-Path $BaselineChecksTsv)) { $inconclusive.Add('-BaselineChecksTsv (the S0 baseline-check-results.tsv) is required'); return }
    $hs = 'TsScoringPlugin\Handshake'
    $ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $jobs = @(
        @{ Id = 'ps-TelemetryL3'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-TelemetryL3.ps1" },
        @{ Id = 'ps-LegacyDataPlaneD4'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-LegacyDataPlaneD4.ps1" },
        @{ Id = 'ps-GroundLimitsSI1'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-GroundLimitsSI1.ps1" },
        @{ Id = 'ps-StationTimelineJF1'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-StationTimelineJF1.ps1" },
        @{ Id = 'ps-CurrentJumpD6'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-CurrentJumpD6.ps1" },
        @{ Id = 'ps-CurrentDataPlaneD3'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-CurrentDataPlaneD3.ps1" },
        @{ Id = 'ps-VerifyPhaseL3'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tools\Verify-PhaseL3.ps1" },
        @{ Id = 'ps-LegacyInputLI0'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-LegacyInputLI0.ps1" },
        @{ Id = 'ps-LegacyInputLI1'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-LegacyInputLI1.ps1" },
        @{ Id = 'ps-LegacyInputLI2'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-LegacyInputLI2.ps1" },
        @{ Id = 'ps-ScoringObservationSI0'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tests\Test-ScoringObservationSI0.ps1" },
        @{ Id = 'ps-VerifyPhaseB'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tools\Verify-PhaseB.ps1" },
        @{ Id = 'ps-VerifyPhaseC3'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tools\Verify-PhaseC3.ps1" },
        @{ Id = 'ps-VerifyPhaseL1'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tools\Verify-PhaseL1.ps1" },
        @{ Id = 'ps-VerifyPhaseSIA7'; Exe = $ps; Args = "-NoProfile -ExecutionPolicy Bypass -File $hs\Tools\Verify-PhaseSIA7.ps1" },
        @{ Id = 'py-jf1_csharp_source_pins'; Exe = $python; Args = '-I -B -m unittest discover -s tests -p test_jf1_current_csharp_source_pins.py -v' },
        @{ Id = 'py-jump_complete_d6'; Exe = $python; Args = '-I -B -m unittest discover -s tests -p test_jump_complete_d6.py -v' },
        @{ Id = 'py-current_jump_interop_d6'; Exe = $python; Args = '-I -B -m unittest discover -s tests -p test_current_jump_interop_d6.py -v' },
        @{ Id = 'py-current_jump_endpoint_live_d6'; Exe = $python; Args = '-I -B -m unittest discover -s tests -p test_current_jump_endpoint_live_d6.py -v' },
        @{ Id = 'py-jf1_jump_completion_chain'; Exe = $python; Args = '-I -B -m unittest discover -s tests -p test_jf1_jump_completion_and_chain_current.py -v' },
        @{ Id = 'py-dataplane_contract_pid_d1'; Exe = $python; Args = '-I -B -m unittest discover -s tests -p test_dataplane_contract_pid_d1.py -v' },
        @{ Id = 'py-ALL'; Exe = $python; Args = '-I -B -m unittest discover -s tests -v' },
        @{ Id = 'pyU-ALL'; Exe = $python; Args = '-B -m unittest discover -s tests -v' }
    )
    $current = @{}
    $suiteRows = New-Object System.Collections.Generic.List[string]
    $suiteRows.Add("id`texit`tpass`tfail`tskip`tinconclusive`tseconds")
    foreach ($j in $jobs) {
        $g = @(Guard)
        if ($g.Count -gt 0) { $inconclusive.Add('BVE / python is running before ' + $j.Id); break }
        $o = Join-Path $LogDir ($j.Id + '.out.txt'); $e = Join-Path $LogDir ($j.Id + '.err.txt')
        $t0 = Get-Date
        $p = Start-Process -FilePath $j.Exe -ArgumentList $j.Args -WorkingDirectory $repo -NoNewWindow -PassThru -RedirectStandardOutput $o -RedirectStandardError $e
        $null = $p.Handle
        if (-not $p.WaitForExit(1500000)) { try { Stop-Process -Id $p.Id -Force } catch { } }
        $p.WaitForExit()
        $sec = [int]((Get-Date) - $t0).TotalSeconds
        $txt = ReadText $o
        $lines = @($txt -split "`r?`n")
        $pass = @($lines | Where-Object { $_ -match '^PASS ' }).Count
        $fail = @($lines | Where-Object { $_ -match '^FAIL ' }).Count
        $skip = @($lines | Where-Object { $_ -match '^SKIP' }).Count
        $inc = @($lines | Where-Object { $_ -match '^INCONCLUSIVE' }).Count
        $suiteRows.Add(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f $j.Id, $p.ExitCode, $pass, $fail, $skip, $inc, $sec))
        Write-Host ("  {0} exit={1} pass={2} fail={3} skip={4} inc={5} sec={6}" -f $j.Id, $p.ExitCode, $pass, $fail, $skip, $inc, $sec)
        if ($j.Id -like 'py*') {
            foreach ($l in ((ReadText $e) -split "`r?`n")) { if ($l -match '^(FAIL|ERROR): (.+)$') { $kind = $Matches[1]; $nm = $Matches[2] -replace '^setUpClass \((.+)\)$', 'setUpClass $1'; $current[$j.Id + '|' + $nm] = $kind } }
        }
        else {
            foreach ($l in $lines) {
                if ($l -match '^(PASS|FAIL) (.*)$') { $key = $j.Id + '|' + (CheckKey $Matches[2]); if (-not $current.ContainsKey($key) -or $Matches[1] -eq 'FAIL') { $current[$key] = $Matches[1] } }
            }
        }
    }
    [IO.File]::WriteAllLines((Join-Path $LogDir 'regress-suites.tsv'), $suiteRows.ToArray(), (New-Object Text.UTF8Encoding($false)))
    $base = @{}
    foreach ($r in (Import-Csv -Delimiter "`t" -Path $BaselineChecksTsv)) {
        if ($r.suite -like 'pyU-*' -and $r.suite -ne 'pyU-ALL') { continue }
        if ($r.suite -eq 'ps-JumpProbeB1') { continue }
        if ($r.suite -like 'py*') { if ($r.status -in 'FAIL', 'ERROR') { $base[$r.suite + '|' + ($r.id_or_name -replace '^setUpClass \((.+)\)$', 'setUpClass $1')] = $r.status } }      # the S0 table holds an ERROR twice, once with and once without the parentheses
        else {
            $name = $r.id_or_name
            $key = $r.suite + '|' + (CheckKey $name)
            if (-not $base.ContainsKey($key) -or $r.status -eq 'FAIL') { $base[$r.suite + '|' + (CheckKey $name)] = $r.status }
        }
    }
    $predicted = @(
        'ps-VerifyPhaseC3|source: ''Socket'' absent from all sources', 'ps-VerifyPhaseC3|source: ''System\.Timers'' absent from all sources', 'ps-VerifyPhaseC3|source: ''UdpClient'' absent from all sources')   # Stage S0 X6: the exact-path exclusion of the test kit (S4)
    $expectedNew = @(); foreach ($mod in $pyExpect.Keys) { $expectedNew += @($pyExpect[$mod].Keys) }
    $rows = New-Object System.Collections.Generic.List[string]
    $rows.Add("class`tkey`tbaseline`tnow")
    $known = 0; $resolved = 0; $newFail = 0; $new = 0; $unpredicted = 0; $unexpectedNew = 0
    foreach ($k in $current.Keys) {
        $now = $current[$k]
        $was = if ($base.ContainsKey($k)) { $base[$k] } else { '(absent)' }
        if ($now -in 'FAIL', 'ERROR') {
            if ($was -in 'FAIL', 'ERROR') { $known++; $rows.Add("KNOWN-FAIL`t$k`t$was`t$now") }
            elseif ($was -eq 'PASS') {
                $newFail++
                if ($predicted -contains $k) { $rows.Add("PLANNED-S4-PENDING-X6`t$k`t$was`t$now") } else { $unpredicted++; $rows.Add("NEW-FAIL-UNPREDICTED`t$k`t$was`t$now") }
            }
            else {
                $new++
                $short = ($k -split '\|', 2)[1]
                $nm = ([regex]::Match($short, '^(\w+)')).Groups[1].Value
                if ($expectedNew -contains $nm) { $rows.Add("NEW-TEST-EXPECTED-RED`t$k`t$was`t$now") } else { $unexpectedNew++; $rows.Add("NEW-TEST-UNEXPECTED`t$k`t$was`t$now") }
            }
        }
    }
    foreach ($k in $base.Keys) {
        if ($base[$k] -in 'FAIL', 'ERROR') {
            if (-not $current.ContainsKey($k)) { $resolved++; $rows.Add("RESOLVED-OR-MISSING`t$k`t$($base[$k])`t(absent)") }
            elseif ($current[$k] -eq 'PASS') { $resolved++; $rows.Add("RESOLVED`t$k`t$($base[$k])`tPASS") }
        }
    }
    [IO.File]::WriteAllLines((Join-Path $LogDir 'regress-compare.tsv'), $rows.ToArray(), (New-Object Text.UTF8Encoding($false)))
    Report 'Regress' 'known-fail-set' 'GUARD' $(if ($resolved -eq 0) { 'PASS' } else { 'FAIL' }) ("known failures still failing: $known; resolved or missing: $resolved")
    Report 'Regress' 'new-fail-predicted' 'GUARD' 'PASS' ("checks that were PASS in the baseline and FAIL now and were predicted by Stage S0 (planned, pending the exact-path exclusion X6 of Stage S4; they must turn PASS again there): $($newFail - $unpredicted)")
    Report 'Regress' 'new-fail-unpredicted' 'GUARD' $(if ($unpredicted -eq 0) { 'PASS' } else { 'FAIL' }) ("checks that were PASS in the baseline and FAIL now and were NOT predicted: $unpredicted (see regress-compare.tsv)")
    Report 'Regress' 'new-tests-expected-red' 'GUARD' $(if ($unexpectedNew -eq 0) { 'PASS' } else { 'FAIL' }) ("failing checks without a baseline entry: $new, of which not one of the new Stage S1 tests: $unexpectedNew")
}
function CheckKey([string]$name) {
    if ($name -match '^([A-Z]+[0-9]+[a-z]?)\b') { return $Matches[1] }
    return ([regex]::Replace($name.Substring(0, [Math]::Min(150, $name.Length)).Trim(), '\d+', '#'))
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------------------------------------------------------------------------
try {
    if ($Mode -in 'All', 'Static') { Run-Static }
    if ($Mode -in 'All', 'Self') { Run-Self }
    if ($Mode -in 'All', 'Product') { Run-Product }
    if ($Mode -in 'All', 'Python') { Run-Python }
    if ($Mode -eq 'Mutation') { Run-Mutation }
    if ($Mode -eq 'Regress') { Run-Regress }
}
catch {
    Write-Host ('EXCEPTION ' + $_.Exception.GetType().FullName + ': ' + $_.Exception.Message)
    Write-Host ($_.InvocationInfo.PositionMessage)
    Write-Host ($_.ScriptStackTrace)
    $results.Add([pscustomobject]@{ Section = 'Runner'; Id = 'exception'; Kind = 'SELF'; Outcome = 'FAIL'; RedCode = ''; Expected = $false; Detail = $_.Exception.GetType().Name })
}

$gitAfter = GitFingerprint
Report 'Runner' 'repository-unchanged' 'SELF' $(if ($gitBefore -eq $gitAfter) { 'PASS' } else { 'FAIL' }) 'git HEAD, stash and status are identical before and after this run (the run writes only under the git-ignored logs folder)'
$tsvOut = New-Object System.Collections.Generic.List[string]
$tsvOut.Add("section`tid`tkind`toutcome`tred_code`texpected`tdetail")
foreach ($r in $results) { $tsvOut.Add(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}" -f $r.Section, $r.Id, $r.Kind, $r.Outcome, $r.RedCode, $r.Expected, (($r.Detail -replace "[`t`r`n]", ' ')))) }
[IO.File]::WriteAllLines((Join-Path $LogDir 'results.tsv'), $tsvOut.ToArray(), (New-Object Text.UTF8Encoding($false)))
$nPass = @($results | Where-Object { $_.Outcome -eq 'PASS' }).Count
$nFail = @($results | Where-Object { $_.Outcome -eq 'FAIL' }).Count
$nRed = @($results | Where-Object { $_.Outcome -eq 'RED' }).Count
$nInc = @($results | Where-Object { $_.Outcome -eq 'INCONCLUSIVE' }).Count
$nBad = @($results | Where-Object { -not $_.Expected }).Count
Write-Host ''
foreach ($i in $inconclusive) { Write-Host ('INCONCLUSIVE: ' + $i) }
Write-Host ("LEGACYJUMP-2A mode=$Mode expect=$Expect PASS=$nPass FAIL=$nFail RED=$nRed UNEXPECTED=$nBad INCONCLUSIVE=" + ($inconclusive.Count + $nInc) + " log=" + $LogDir)
if ($nBad -gt 0) { exit 1 }
if ($inconclusive.Count -gt 0) { exit 2 }
exit 0
