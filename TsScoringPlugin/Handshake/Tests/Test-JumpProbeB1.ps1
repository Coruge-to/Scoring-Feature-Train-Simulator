# PHASE SI-B1 (B1-probe) - offline tests of the OBSERVATION-ONLY probe for the AtsEX Legacy host (Scenario.Initialize / InitializeTimeAndLocation + TimeManager.SetTime on the Extension Tick).
# This is NOT a test of Phase SI-B2 (there is no production jump, no 54322 receiver, no JUMP counter, no COMPLETE, no AVAIL "jump"): it proves that the probe
#   * does nothing without a request file,
#   * parses a request strictly and runs it AT MOST ONCE (write-ahead ledger), only on the Tick, never after Dispose began, in the right call order,
#   * logs every required event with the required fields (and no personal path / mail),
#   * evaluates the completion CANDIDATE with the tolerances (location 0.01 m, time exact) and the six side conditions,
#   * is wired into the product only through a GENERATED copy of the Extension, and the product sources / product DLL (0.4.0.0, 995486BE) are unchanged,
#   * touches nothing of Current, Caller, Bridge, the Python scoring gate or the M1a control plane.
# The behaviour is tested by compiling probe\B1ProbeCore.cs with Tests\B1ProbeTestFixture.cs (Add-Type) and driving a FAKE host / io: no BVE, no AtsEX runtime, no network, no UDP.
# Mutation tests (18) run this script in a child process on a mutated copy of the core (-CoreOverride -BehaviorOnly) and require at least one failing check.
# This script is ASCII-only on purpose.
param(
    [string]$Root = '',
    [string]$CoreOverride = '',
    [switch]$BehaviorOnly,
    [switch]$SkipMutations,
    [string]$WorkDir = ''          # only for the mutation children: a folder inside the parent's temp folder (the parent removes it)
)

$ErrorActionPreference = 'Stop'
if ($Root -eq '') { $Root = Split-Path $PSScriptRoot -Parent }
$top = Split-Path (Split-Path $Root -Parent) -Parent
$probeDir = Join-Path $Root 'Tests\B1Probe'
$corePath = $(if ($CoreOverride -ne '') { $CoreOverride } else { Join-Path $probeDir 'src\B1ProbeCore.cs' })
$hostPath = Join-Path $probeDir 'src\B1ProbeHost.cs'
$fixturePath = Join-Path $Root 'Tests\B1ProbeTestFixture.cs'
$AcceptedProductSha = '995486BECD10BB0CF37F97B360DF819514272BBB4A32F1BC07BA244C23E127F3'

$results = New-Object System.Collections.Generic.List[object]
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ('{0} {1}' -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function U16([string]$s) { return (($s.ToCharArray() | ForEach-Object { [string]$_ + [char]0 }) -join '') }
function Norm([string]$text) { return ($text -replace "`r`n", "`n") }
function ReadText([string]$path) { return (Norm ([IO.File]::ReadAllText($path))) }
function CodeOf([string]$text) {
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in ((Norm $text) -split "`n")) {
        if ($line.TrimStart().StartsWith('//')) { continue }
        $c = [regex]::Replace($line, '"(?:[^"\\]|\\.)*"', '""')
        $c = [regex]::Replace($c, '//.*$', '')
        $out.Add($c)
    }
    return ($out -join "`n")
}
function MethodText([string]$text, [string]$name) {
    $m = [regex]::Match($text, '(?ms)^        (?:private|internal|public)[^\n]*\b' + [regex]::Escape($name) + '\([^\n]*\)\s*\n        \{.*?\n        \}\n')
    return $m.Value
}
function RunGit([string[]]$gitArgs) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'; $psi.WorkingDirectory = $top; $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true; $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $psi.Arguments = (($gitArgs | ForEach-Object { '"' + $_ + '"' }) -join ' ')
    $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEnd(); $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw ('git failed: ' + ($gitArgs -join ' ')) }
    return $o
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# compile the core + fixture (C# 5, Windows PowerShell's compiler) and load them
# ---------------------------------------------------------------------------------------------------------------------------------------------
$testDir = $(if ($WorkDir -ne '') { $WorkDir } else { Join-Path ([IO.Path]::GetTempPath()) ('tsscoring-b1probe-' + [guid]::NewGuid().ToString('N')) })
New-Item -ItemType Directory -Force $testDir | Out-Null
# whatever happens (an exception included), the temp folder of this run does not stay behind; a mutation child leaves its folder to the parent
trap { if ($WorkDir -eq '') { Remove-Item $testDir -Recurse -Force -ErrorAction SilentlyContinue }; break }
$dll = Join-Path $testDir 'B1ProbeTests.dll'
try {
    Add-Type -Path @($corePath, $fixturePath) -OutputAssembly $dll -OutputType Library
} catch {
    Write-Host ('COMPILE FAILED: ' + $_.Exception.Message)
    if ($WorkDir -eq '') { Remove-Item $testDir -Recurse -Force -ErrorAction SilentlyContinue }
    exit 3
}
[void][Reflection.Assembly]::LoadFrom($dll)

function NewH { return (New-Object B1Tests.Harness) }
function Ready($h) { $h.Ticks(15) }
function Ev($h, [string]$name) { return ,@($h.Events($name)) }
function N($h, [string]$name) { return (@($h.Events($name))).Count }
function Op([string]$op, [int]$st, [string]$loc, [int]$ms, $arm) {
    $h = NewH; Ready $h
    if ($arm) { & $arm $h }
    $h.Place('B1-T', 'rq-000001', $op, $st, $loc, $ms); $h.Tick(); $h.Ticks(6)
    return $h
}
$SET = 'SetTime'; $STA = 'InitializeStationThenSetTime'; $LOC = 'InitializeLocationThenSetTime'
function Cand($h) { $c = Ev $h 'PROBE_COMPLETION_CANDIDATE'; if ($c.Count -eq 0) { return 'none' } ; if ($c[0] -match 'result=MET') { return 'MET' } else { return 'NOT_MET' } }
function Calls($h) { return (@($h.Host.Calls) -join ',') }
function Flag($h, [string]$ev, [string]$key) { $l = Ev $h $ev; if ($l.Count -eq 0) { return 'none' }; $m = [regex]::Match($l[0], ' ' + $key + '=(\S+)'); if ($m.Success) { return $m.Groups[1].Value } else { return 'nokey' } }

# =============================================================================================================================================
Write-Host '==== P: the request parser ===='
$ts = '2026-10-11T11:59:55.000Z'
function Req2([string]$extra) { return ("B1PROBE-REQUEST 1`nTestId=B1-O1`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=true`n" + $extra) }
$P = [B1Tests.Harness]
Check 'P01 a valid SetTime request parses' (($P::ParseReason((Req2 "Operation=SetTime`nTimeMs=36000000`n"))) -ceq 'OK:SetTime:-1:na:36000000')
Check 'P02 a valid station request parses (station index kept)' (($P::ParseReason((Req2 "Operation=InitializeStationThenSetTime`nStationIndex=3`nTimeMs=1`n"))) -ceq 'OK:InitializeStationThenSetTime:3:na:1')
Check 'P03 a valid location request parses (negative and fractional location)' (($P::ParseReason((Req2 "Operation=InitializeLocationThenSetTime`nLocationM=-12.5`nTimeMs=0`n"))) -ceq 'OK:InitializeLocationThenSetTime:-1:-12.5:0')
Check 'P04 comments, blank lines and CRLF are accepted' (($P::ParseReason(("# note`r`nB1PROBE-REQUEST 1`r`n`r`n# c`r`nTestId=B1-O1`r`nRequestId=rq-00000001`r`nCreatedAtUtc=$ts`r`nExecuteOnce=true`r`nOperation=SetTime`r`nTimeMs=5`r`n"))) -ceq 'OK:SetTime:-1:na:5')
Check 'P05 no header / wrong header / key before header: bad-format' ((($P::ParseReason("TestId=B1-O1`nB1PROBE-REQUEST 1`n")) -like 'bad-format*') -and (($P::ParseReason("B1PROBE-REQUEST 2`n")) -like 'bad-format*') -and (($P::ParseReason('')) -like 'bad-format*'))
Check 'P06 an unknown key: unknown-key' (($P::ParseReason((Req2 "Operation=SetTime`nTimeMs=5`nFoo=1`n"))) -like 'unknown-key*')
Check 'P07 a duplicate key: duplicate-key' (($P::ParseReason((Req2 "Operation=SetTime`nTimeMs=5`nTimeMs=6`n"))) -like 'duplicate-key*')
$missingOk = $true
foreach ($drop in @('TestId', 'RequestId', 'Operation', 'TimeMs', 'CreatedAtUtc', 'ExecuteOnce')) {
    $lines = @("TestId=B1-O1", "RequestId=rq-00000001", "Operation=SetTime", "TimeMs=5", "CreatedAtUtc=$ts", "ExecuteOnce=true") | Where-Object { -not $_.StartsWith($drop + '=') }
    if (-not (($P::ParseReason(("B1PROBE-REQUEST 1`n" + ($lines -join "`n") + "`n"))) -like 'missing-key*')) { $missingOk = $false }
}
Check 'P08 each of the six required keys missing: missing-key' $missingOk
Check 'P09 an unknown operation: bad-operation' (($P::ParseReason((Req2 "Operation=Jump`nTimeMs=5`n"))) -like 'bad-operation*')
Check 'P10 SetTime with a station or a location: operation-args' ((($P::ParseReason((Req2 "Operation=SetTime`nStationIndex=1`nTimeMs=5`n"))) -like 'operation-args*') -and (($P::ParseReason((Req2 "Operation=SetTime`nLocationM=1`nTimeMs=5`n"))) -like 'operation-args*'))
Check 'P11 the station operation without a station, or with a location: operation-args' ((($P::ParseReason((Req2 "Operation=InitializeStationThenSetTime`nTimeMs=5`n"))) -like 'operation-args*') -and (($P::ParseReason((Req2 "Operation=InitializeStationThenSetTime`nStationIndex=1`nLocationM=1`nTimeMs=5`n"))) -like 'operation-args*'))
Check 'P12 the location operation without a location, or with a station: operation-args' ((($P::ParseReason((Req2 "Operation=InitializeLocationThenSetTime`nTimeMs=5`n"))) -like 'operation-args*') -and (($P::ParseReason((Req2 "Operation=InitializeLocationThenSetTime`nLocationM=1`nStationIndex=1`nTimeMs=5`n"))) -like 'operation-args*'))
$badTime = $true
foreach ($v in @('-1', '1.5', '172800001', '', 'abc', '+5', '5 6', '0x10', '1e3')) {
    if (-not (($P::ParseReason((Req2 ("Operation=SetTime`nTimeMs=" + $v + "`n")))) -like 'bad-value*')) { $badTime = $false }
}
Check 'P13 TimeMs must be plain digits within 0..172800000 (negative, decimal, too large, empty, signed, hex, exponent: bad-value)' $badTime
Check 'P14 TimeMs boundaries 0 and 172800000 are accepted' ((($P::ParseReason((Req2 "Operation=SetTime`nTimeMs=0`n"))) -like 'OK*') -and (($P::ParseReason((Req2 "Operation=SetTime`nTimeMs=172800000`n"))) -like 'OK*'))
$badSt = $true
foreach ($v in @('-1', '10000', 'a', '1.0', '')) { if (-not (($P::ParseReason((Req2 ("Operation=InitializeStationThenSetTime`nStationIndex=" + $v + "`nTimeMs=5`n")))) -like 'bad-value*')) { $badSt = $false } }
Check 'P15 a bad StationIndex (negative, 10000, letters, decimal, empty): bad-value' $badSt
$badLoc = $true
foreach ($v in @('NaN', 'Infinity', '-Infinity', '1e999', '10000001', '-100001', 'x', '')) { if (-not (($P::ParseReason((Req2 ("Operation=InitializeLocationThenSetTime`nLocationM=" + $v + "`nTimeMs=5`n")))) -like 'bad-value*')) { $badLoc = $false } }
Check 'P16 a bad LocationM (NaN, Infinity, overflow, out of range, text, empty): bad-value' $badLoc
Check 'P17 ExecuteOnce must be exactly true' ((($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=B1-O1`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=false`nOperation=SetTime`nTimeMs=5`n"))) -like 'not-execute-once*') -and (($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=B1-O1`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=True`nOperation=SetTime`nTimeMs=5`n"))) -like 'not-execute-once*'))
$badId = $true
foreach ($v in @('short', 'has space 1234', 'bad/char-1234', ('x' * 49), '')) { if (-not (($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=B1-O1`nRequestId=" + $v + "`nCreatedAtUtc=$ts`nExecuteOnce=true`nOperation=SetTime`nTimeMs=5`n"))) -like 'bad-value*')) { $badId = $false } }
Check 'P18 a RequestId that is too short / long / has other characters: bad-value' $badId
Check 'P19 a TestId with a space, a slash or 25 characters: bad-value' ((($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=B1 O1`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=true`nOperation=SetTime`nTimeMs=5`n"))) -like 'bad-value*') -and (($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=" + ('a' * 25) + "`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=true`nOperation=SetTime`nTimeMs=5`n"))) -like 'bad-value*'))
$badAt = $true
foreach ($v in @('2026-10-11 11:59:55.000Z', '2026-10-11T11:59:55Z', '2026-10-11T11:59:55.000', 'yesterday', '')) { if (-not (($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=B1-O1`nRequestId=rq-00000001`nCreatedAtUtc=" + $v + "`nExecuteOnce=true`nOperation=SetTime`nTimeMs=5`n"))) -like 'bad-value*')) { $badAt = $false } }
Check 'P20 CreatedAtUtc must be exactly yyyy-MM-ddTHH:mm:ss.fffZ' $badAt
Check 'P21 a request larger than 2048 characters: too-large' (($P::ParseReason((Req2 ("Operation=SetTime`nTimeMs=5`n#" + ('x' * 2100) + "`n")))) -like 'too-large*')
Check 'P22 an unreadable request (null): unreadable' (($P::ParseReason([NullString]::Value)) -like 'unreadable*')
$r = $P::ParseReason(("B1PROBE-REQUEST 1`nTestId=B1-O1`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=true`nOperation=Bogus`nTimeMs=5`n"))
Check 'P23 on a rejection the ids are returned only when they are valid themselves (no free text reaches the log)' (($r -ceq 'bad-operation|B1-O1|rq-00000001') -and (($P::ParseReason(("B1PROBE-REQUEST 1`nTestId=evil text C:\Users\x`nRequestId=rq-00000001`nCreatedAtUtc=$ts`nExecuteOnce=true`nOperation=Bogus`nTimeMs=5`n")) -ceq 'bad-value|-|rq-00000001')))
$cl = $P::CleanText('boom at C:\Users\someone\secret.txt by someone@example.com ' + ('x' * 200))
Check 'P24 Clean() removes drive paths and mail addresses, replaces non-ASCII and caps at 120 characters' (($cl -notmatch 'someone') -and ($cl -notmatch '[A-Za-z]:\\') -and ($cl.Length -le 120) -and ($P::CleanText($null) -ceq '-') -and (($P::CleanText([string][char]0x65E5 + 'ab')) -ceq '_ab'))

# =============================================================================================================================================
Write-Host '==== B: the call order and where the calls run ===='
$h = Op $SET -1 '' 36500000 $null
Check 'B01 SetTime: exactly one host call, SetTime(ms); Initialize is never called' ((Calls $h) -ceq 'SetTime:36500000')
$h = Op $STA 3 '' 36500000 $null
Check 'B02 station: Initialize(station) THEN SetTime(ms), nothing else' ((Calls $h) -ceq 'InitializeStation:3,SetTime:36500000')
$h = Op $LOC -1 '2750.5' 36500000 $null
Check 'B03 location: InitializeTimeAndLocation(loc, ms) THEN SetTime(ms), nothing else' ((Calls $h) -ceq 'InitializeLocation:2750.5:36500000,SetTime:36500000')
$h = Op $STA 1 '' 36500000 $null
Check 'B04 the world after the sequence is the requested one (time exact, location = the station; the Tick right after the call repeats it, the 5 Ticks after that advance)' (($h.World.TimeMs - 5 * 16 -eq 36500000) -and ([math]::Abs($h.World.Loc - 1000.0) -lt 0.01))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 2, '', 36500000); $h.StartTickOnNewThread(); $h.JoinTick()
$mainTid = [Threading.Thread]::CurrentThread.ManagedThreadId
$allOnTick = (@($h.Host.CallThreads | Where-Object { $_ -ne $h.TickThreadId })).Count -eq 0
Check 'B05 every host call ran on the thread that ran BeginTick (the Tick thread), none on another' ($allOnTick -and ($h.Host.CallThreads.Count -eq 2) -and ($h.TickThreadId -ne $mainTid))
$h = Op $SET -1 '' 36500000 $null
Check 'B06 each call is logged BEGIN / END with elapsedMs; the SetTime-only run has no INITIALIZE line' (((N $h 'PROBE_SET_TIME_BEGIN') -eq 1) -and ((N $h 'PROBE_SET_TIME_END') -eq 1) -and ((N $h 'PROBE_INITIALIZE_BEGIN') -eq 0) -and ((Ev $h 'PROBE_SET_TIME_END')[0] -match 'ok=yes elapsedMs=\d'))
$h = Op $STA 2 '' 36500000 $null
Check 'B07 INITIALIZE_BEGIN / INITIALIZE_END come before SET_TIME_BEGIN / SET_TIME_END' (($h.Joined.IndexOf('PROBE_INITIALIZE_END') -ge 0) -and ($h.Joined.IndexOf('PROBE_INITIALIZE_END') -lt $h.Joined.IndexOf('PROBE_SET_TIME_BEGIN')) -and ($h.Joined.IndexOf('PROBE_INITIALIZE_BEGIN') -lt $h.Joined.IndexOf('PROBE_INITIALIZE_END')))

# =============================================================================================================================================
Write-Host '==== I: nothing happens without a request file ===='
$h = NewH; $h.LogInit(); $h.Ticks(200)
Check 'I01 200 Ticks without a request: no host call, no snapshot, no scenario-created read' (($h.HostCalls -eq 0) -and ($h.Host.SnapshotCalls -eq 0) -and ($h.Host.CreatedChecks -eq 0) -and ($h.Host.Calls.Count -eq 0))
Check 'I02 the only per-Tick work is one existence check of the request file' ($h.Io.ExistsChecks -eq 200)
Check 'I03 an idle probe writes only its start line, the Tick thread note and the generation note (no per-Tick line)' (((Ev $h 'PROBE_INIT').Count -eq 1) -and ((N $h 'PROBE_TICK_THREAD') -eq 1) -and ((N $h 'PROBE_GENERATION') -eq 1) -and ($h.Io.Lines.Count -eq 3))
Check 'I04 the start line says OBSERVATION-ONLY and idle-until-request-file' ((Ev $h 'PROBE_INIT')[0] -match 'build=B1-PROBE-OBSERVATION-ONLY .*mode=idle-until-request-file')

# =============================================================================================================================================
Write-Host '==== X: at most once ===='
$h = NewH; Ready $h; $h.Io.FailRetire = $true; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Ticks(40)
Check 'X01 a request file that cannot be renamed is still executed ONCE (40 Ticks, the file stays)' (($h.Executed -eq 1) -and ($h.Host.Calls.Count -eq 2) -and ($h.Accepted -eq 1))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Ticks(8)
$h.Place('B1-T', 'rq-000001', $STA, 2, '', 36600000); $h.Ticks(3)
Check 'X02 the same RequestId again (a new file): PROBE_DUPLICATE_IGNORED, no further call, file retired as duplicate' (($h.Duplicates -eq 1) -and ((N $h 'PROBE_DUPLICATE_IGNORED') -eq 1) -and ($h.Host.Calls.Count -eq 2) -and ($h.Io.Retired -contains 'duplicate'))
$h.RestartEngine(); $h.Place('B1-T', 'rq-000001', $STA, 2, '', 36600000); $h.Ticks(3)
Check 'X03 after an engine restart (a new BVE process) the consumed ledger still refuses the RequestId' (($h.Duplicates -eq 1) -and ($h.Host.Calls.Count -eq 2))
$h = NewH; Ready $h; $h.Host.LedgerMustContain = $true; $h.Host.LedgerIdToCheck = 'rq-000001'; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Ticks(8)
Check 'X04 write-ahead: the RequestId is in the ledger BEFORE the first host call (and before the second)' (($h.Host.Calls.Count -eq 2) -and ($h.Host.LedgerViolations -eq 0))
$h = NewH; Ready $h; $h.Io.FailLedger = $true; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Ticks(5)
Check 'X05 a ledger that cannot be written: rejected (ledger-failed), NO host call' (($h.Host.Calls.Count -eq 0) -and ($h.Rejected -eq 1) -and ((Ev $h 'PROBE_REQUEST_REJECTED')[0] -match 'reason=ledger-failed'))
$h = NewH; $h.SetMaxExecutions(3); Ready $h
for ($i = 1; $i -le 4; $i++) { $h.Place('B1-T', ('rq-00000' + $i), $SET, -1, '', 36500000 + $i); $h.Ticks(10) }
Check 'X06 the execution cap (3): the 4th request is rejected (execution-cap), 3 SetTime calls in all' (($h.Executed -eq 3) -and ($h.Host.Calls.Count -eq 3) -and ((Ev $h 'PROBE_REQUEST_REJECTED')[0] -match 'reason=execution-cap'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $SET, -1, '', 36500000); $h.Ticks(8); $h.Place('B1-T', 'rq-000002', $SET, -1, '', 36700000); $h.Ticks(8)
Check 'X07 a second request with a NEW RequestId runs after the first observation ended' (($h.Executed -eq 2) -and ($h.Host.Calls.Count -eq 2) -and ($h.Host.Calls[1] -ceq 'SetTime:36700000'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick(); $h.Place('B1-T', 'rq-000002', $SET, -1, '', 36700000); $h.Ticks(2)
$mid = $h.Host.Calls.Count
$h.Ticks(8)
Check 'X08 single flight: a request placed DURING an observation is not read until it ended, then runs once' (($mid -eq 2) -and ($h.Host.Calls.Count -eq 3) -and ($h.Executed -eq 2) -and ($h.Host.Calls[2] -ceq 'SetTime:36700000'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick()
Check 'X09 the consumed request file is renamed after the calls (consumed-<requestId>)' (($h.Io.Retired.Count -eq 1) -and ($h.Io.Retired[0] -ceq 'consumed-rq-000001') -and ($h.Io.RequestText -eq $null))

# =============================================================================================================================================
Write-Host '==== R: rejections (no host call, the request is consumed, the file is retired) ===='
function RejectCase([string]$reasonWord, $mutate) {
    $h = NewH; Ready $h
    & $mutate $h
    $h.Ticks(6)
    $ok = ($h.Rejected -eq 1) -and ($h.Host.Calls.Count -eq 0) -and ($h.Accepted -le 1) -and ((Ev $h 'PROBE_REQUEST_REJECTED').Count -ge 1) -and ((Ev $h 'PROBE_REQUEST_REJECTED')[0] -match ('reason=' + [regex]::Escape($reasonWord) + '( |$)'))
    return $ok
}
Check 'R01 created before the process started: created-before-process-start' (RejectCase 'created-before-process-start' { param($h) $h.Io.RequestText = [B1Tests.Harness]::Request('B1-T', 'rq-000001', $SET, -1, '', 5, $h.Created(660.0), '') })
Check 'R02 created in the future (> 10 s): created-in-future' (RejectCase 'created-in-future' { param($h) $h.Io.RequestText = [B1Tests.Harness]::Request('B1-T', 'rq-000001', $SET, -1, '', 5, $h.Created(-30.0), '') })
Check 'R03 older than 1800 s (process started long ago): too-old' (RejectCase 'too-old' { param($h) $h.Io.Start = $h.Io.Now.AddHours(-5); $h.Io.RequestText = [B1Tests.Harness]::Request('B1-T', 'rq-000001', $SET, -1, '', 5, $h.Created(1801.0), '') })
$h = NewH; Ready $h; $h.Io.Start = $h.Io.Now.AddHours(-5); $h.Io.RequestText = [B1Tests.Harness]::Request('B1-T', 'rq-000001', $SET, -1, '', 5, $h.Created(1799.0), ''); $h.Ticks(3)
Check 'R04 1799 s old is still accepted (the age limit is exact)' (($h.Accepted -eq 1) -and ($h.Executed -eq 1))
Check 'R05 ExpectGeneration that is not the current generation: generation-mismatch' (RejectCase 'generation-mismatch' { param($h) $h.Io.RequestText = [B1Tests.Harness]::Request('B1-T', 'rq-000001', $SET, -1, '', 5, $h.Created(5.0), "ExpectGeneration=5`n") })
$h = NewH; Ready $h; $h.Io.RequestText = [B1Tests.Harness]::Request('B1-T', 'rq-000001', $SET, -1, '', 5, $h.Created(5.0), "ExpectGeneration=1`n"); $h.Ticks(3)
Check 'R06 ExpectGeneration equal to the current generation is accepted' (($h.Accepted -eq 1) -and ($h.Executed -eq 1))
Check 'R07 a station index equal to the station count: station-out-of-range (Initialize is never called with it)' (RejectCase 'station-out-of-range' { param($h) $h.Place('B1-T', 'rq-000001', $STA, 4, '', 5) })
Check 'R08 a time that cannot be read: snapshot-unreadable' (RejectCase 'snapshot-unreadable' { param($h) $h.Host.TimeUnreadable = $true; $h.Place('B1-T', 'rq-000001', $SET, -1, '', 5) })
Check 'R09 a malformed file: bad-format, retired as rejected' (RejectCase 'bad-format' { param($h) $h.Io.RequestText = "hello`n" })
$h = NewH; Ready $h; $h.Io.RequestText = "hello`n"; $h.Ticks(2)
Check 'R10 a rejected file is retired (word rejected) and the RequestId is NOT consumed when it could not be parsed' (($h.Io.Retired -contains 'rejected') -and ($h.Io.Ledger.Count -eq 0))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 9, '', 5); $h.Ticks(3)
Check 'R11 a request rejected after it was parsed IS consumed (the id cannot come back)' ($h.Io.Ledger.Contains('rq-000001'))
$h = NewH; Ready $h; $h.Io.FailRetire = $true; $h.Io.RequestText = "hello`n"; $h.Ticks(25)
Check 'R12 a rejected file that cannot be renamed is rejected ONCE, not on every Tick' (((N $h 'PROBE_REQUEST_REJECTED') -eq 1) -and ((N $h 'PROBE_RETIRE_FAILED') -eq 1))
$h = NewH; Ready $h; $h.Io.RequestText = ('x' * 5000); $h.Ticks(2)
Check 'R13 an oversized file: too-large' (((Ev $h 'PROBE_REQUEST_REJECTED')[0]) -match 'reason=too-large')
$h = NewH; $h.SessionActive = $false; $h.Ticks(3); $h.Place('B1-T', 'rq-000001', $SET, -1, '', 36500000); $h.Ticks(5)
$pendingBefore = $h.HasPending; $callsBefore = $h.Host.Calls.Count
$h.SessionActive = $true; $h.Ticks(9)
$stillPending = $h.HasPending
$h.Ticks(3)
Check 'R14 a request placed before any scenario was active waits (PROBE_PENDING once), binds to the first generation and runs only after 10 Ticks of it' ($pendingBefore -and ($callsBefore -eq 0) -and ((N $h 'PROBE_PENDING') -eq 1) -and $stillPending -and ($h.Executed -eq 1) -and ($h.Host.Calls.Count -eq 1))
$h = NewH; $h.SetMaxPendingTicks(5); $h.SessionActive = $false; $h.Ticks(3); $h.Place('B1-T', 'rq-000001', $SET, -1, '', 5); $h.Ticks(12)
Check 'R15 a request that never becomes ready is rejected (not-ready-timeout), no call' (($h.Host.Calls.Count -eq 0) -and ((Ev $h 'PROBE_REQUEST_REJECTED')[0] -match 'reason=not-ready-timeout'))
$h = NewH; Ready $h; $h.SessionActive = $false; $h.Place('B1-T', 'rq-000001', $SET, -1, '', 5); $h.Ticks(2)
$h.SessionActive = $true; $h.SessionScenarioId = 7002; $h.Ticks(15)
Check 'R16 the scenario generation changed while the request waited (scenario closed and a new one opened): generation-changed, no call' (($h.Host.Calls.Count -eq 0) -and ((Ev $h 'PROBE_REQUEST_REJECTED')[0] -match 'reason=generation-changed'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $SET, -1, '', 5); $h.Host.Closed = 1; $h.Tick()
Check 'R17 a scenario lifecycle event since the last Tick end: not executed on that Tick (waits)' (($h.Host.Calls.Count -eq 0) -and $h.HasPending)
$h = NewH; $h.SetMinTicks(10); $h.Ticks(9); $h.Place('B1-T', 'rq-000001', $SET, -1, '', 36500000); $h.Tick()
$h = NewH; $h.SetMinTicks(10); $h.Ticks(9); $h.Place('B1-T', 'rq-000001', $SET, -1, '', 36500000); $h.Tick()
Check 'R18 fewer than MinTicksInGeneration (10) Ticks of the generation: waits' (($h.Host.Calls.Count -eq 0) -and $h.HasPending)
$h.Ticks(3)
Check 'R19 ... and runs once the 10 Ticks are there' (($h.Host.Calls.Count -eq 1) -and ($h.Executed -eq 1))

# =============================================================================================================================================
Write-Host '==== O5: Pause - a request placed in a Pause runs on the FIRST Tick after the resume ===='
$h = NewH; Ready $h
# the README order: Pause (no Tick) -> the request is written DURING the Pause -> wait -> resume. So the request is younger than the silence before the first Tick.
$h.Pause(7000)
$h.Io.RequestText = [B1Tests.Harness]::Request('B1-O5', 'rq-0000o501', $STA, 2, '', 36800000, $h.Created(0.0), '')
$h.Pause(14000)
$silent = ($h.Host.Calls.Count -eq 0) -and ($h.Accepted -eq 0) -and ($h.Host.SnapshotCalls -eq 0)
$h.Tick()
$ac = (Ev $h 'PROBE_REQUEST_ACCEPTED')[0]
$gap = [regex]::Match($ac, 'gapSincePrevTickMs=(\d+)').Groups[1].Value
$age = [regex]::Match($ac, 'createdAgeMs=(\d+)').Groups[1].Value
Check 'O501 during the Pause (no Tick) nothing happens: no accept, no host call, no snapshot' $silent
Check 'O502 the first Tick after the resume accepts AND executes in that same Tick (2 calls), tick number = the accept tick' (($h.Host.Calls.Count -eq 2) -and ($ac -match ' tick=16 ') -and ((Ev $h 'PROBE_EXECUTE_BEGIN')[0] -match ' tick=16 '))
Check 'O503 the log shows the Pause and a request written during it: gapSincePrevTickMs >= 20000 and 0 < createdAgeMs < gapSincePrevTickMs (the request is younger than the silence)' (([int]$gap -ge 20000) -and ([int]$age -gt 0) -and ([int]$age -lt [int]$gap))
$h.Ticks(20)
Check 'O504 exactly one execution afterwards (no repeat on the following Ticks)' (($h.Executed -eq 1) -and ($h.Host.Calls.Count -eq 2))

# =============================================================================================================================================
Write-Host '==== F: the log and the completion candidate ===='
$h = Op $STA 2 '' 36500000 $null
$need = @('PROBE_REQUEST_ACCEPTED', 'PROBE_EXECUTE_BEGIN', 'PROBE_BEFORE', 'PROBE_INITIALIZE_BEGIN', 'PROBE_INITIALIZE_END', 'PROBE_SET_TIME_BEGIN', 'PROBE_SET_TIME_END', 'PROBE_AFTER_CALL', 'PROBE_AFTER_SAME_TICK', 'PROBE_AFTER_NEXT_TICK', 'PROBE_COMPLETION_CANDIDATE', 'PROBE_STABILITY_SUMMARY', 'PROBE_OBSERVATION_END')
$missing = @($need | Where-Object { (N $h $_) -lt 1 })
Check 'F01 every required PROBE event is present for a station request' ($missing.Count -eq 0)
$order = @('PROBE_REQUEST_ACCEPTED', 'PROBE_EXECUTE_BEGIN', 'PROBE_BEFORE', 'PROBE_INITIALIZE_BEGIN', 'PROBE_INITIALIZE_END', 'PROBE_SET_TIME_BEGIN', 'PROBE_SET_TIME_END', 'PROBE_AFTER_CALL', 'PROBE_AFTER_SAME_TICK', 'PROBE_COMPLETION_CANDIDATE', 'PROBE_AFTER_NEXT_TICK', 'PROBE_STABILITY_SUMMARY', 'PROBE_OBSERVATION_END')
$pos = @($order | ForEach-Object { $h.Joined.IndexOf($_ + ' ') })
$inOrder = $true; for ($i = 1; $i -lt $pos.Count; $i++) { if (($pos[$i] -lt 0) -or ($pos[$i] -le $pos[$i - 1])) { $inOrder = $false } }
Check 'F02 the events appear in the order accepted, begin, before, initialize, set-time, after-call, after-same-tick, candidate, after-next-tick, summary, end' $inOrder
$fieldRx = '^\d\d:\d\d:\d\d\.\d{3} P=\d+ T=\d+ PROBE_[A-Z_]+ test=\S+ req=\S+ host=AtsExLegacy gen=\d+ scn=\S+ tick=\d+'
$badLines = @($h.Joined -split "`n" | Where-Object { $_ -and ($_ -notmatch $fieldRx) })
Check 'F03 EVERY line has time, process id, thread id, test, request id, host=AtsExLegacy, generation, scenario id and tick sequence' (($badLines.Count -eq 0) -and ($h.Io.Lines.Count -gt 15))
$bef = (Ev $h 'PROBE_BEFORE')[0]; $aft = (Ev $h 'PROBE_AFTER_SAME_TICK')[0]
Check 'F04 BEFORE and AFTER carry position, time, speed, doors, handle, current / next station, signal and ground limit, the ATS side view and the event counters' (($bef -match 'bLoc=') -and ($bef -match 'bTimeMs=') -and ($bef -match 'bSpdKmh=') -and ($bef -match 'bDoorsClosed=') -and ($bef -match 'bHandle=') -and ($bef -match 'bStPrev=') -and ($bef -match 'bStNext=') -and ($bef -match 'bSigKmh=') -and ($bef -match 'bGndKmh=') -and ($bef -match 'bAts=t') -and ($bef -match 'bEvt=open') -and ($aft -match 'sLoc=') -and ($aft -match 'sessionDiscontinuitiesDelta=') -and ($aft -match 'sessionLineTime='))
$ac = (Ev $h 'PROBE_AFTER_CALL')[0]
Check 'F05 AFTER_CALL carries the requested values, the tolerance and the verdicts (timeOk, locOk, tolM, expectLoc, locDelta, elapsed callMs)' (($ac -match 'reqTimeMs=36500000') -and ($ac -match 'station=2') -and ($ac -match 'tolM=0.01') -and ($ac -match 'timeOk=yes') -and ($ac -match 'locOk=yes') -and ($ac -match 'expectLoc=') -and ($ac -match 'locDelta=') -and ($ac -match 'callMs='))
Check 'F06 the process thread / handle counters are logged at the start, at the read-back and at the end' (($h.Joined -split "`n" | Where-Object { $_ -match 'procThreads=\d+ procHandles=\d+' }).Count -ge 4)
Check 'F07 station request: candidate MET (time exact, location = the station within 0.01 m, line sent in the same Tick with the same TIME / LOCATION, no group lost)' ((Cand $h) -ceq 'MET')
$h = Op $SET -1 '' 36500000 $null
Check 'F08 SetTime request: candidate MET (location unchanged within 0.01 m, speed unchanged)' ((Cand $h) -ceq 'MET')
$h = Op $LOC -1 '2750.5' 36500000 $null
Check 'F09 location request: candidate MET' ((Cand $h) -ceq 'MET')
$h = Op $STA 3 '' 36500000 $null
Check 'F10 a jump of more than 300 ms is seen by the session in the SAME Tick (discontinuitySameTick=yes)' ((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'discontinuitySameTick') -ceq 'yes')
Check 'F11 the stability summary: stable=yes, 5 samples, time advancing, location not backwards, ATS started delta 0' (((Ev $h 'PROBE_STABILITY_SUMMARY')[0]) -match 'stable=yes samples=5 timeAdvancing=yes locationNotBackwards=yes noLifecycleEvent=yes atsStartedDelta=0')
$h = Op $SET -1 '' 36500000 { param($x) $x.Host.NoopSetTime = $true }
Check 'F12 a SetTime that did nothing (time not reached): candidate NOT_MET, timeOk=no' (((Cand $h) -ceq 'NOT_MET') -and ((Flag $h 'PROBE_AFTER_CALL' 'timeOk') -ceq 'no'))
$h = Op $STA 1 '' 36500000 { param($x) $x.Host.LocError = 0.02 }
Check 'F13 a location 0.02 m off: locOk=no and candidate NOT_MET (the tolerance is 0.01 m)' (((Flag $h 'PROBE_AFTER_CALL' 'locOk') -ceq 'no') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 { param($x) $x.Host.LocError = 0.009 }
Check 'F14 a location 0.009 m off is within the tolerance: candidate MET' (((Flag $h 'PROBE_AFTER_CALL' 'locOk') -ceq 'yes') -and ((Cand $h) -ceq 'MET'))
$h = Op $STA 1 '' 36500000 { param($x) $x.SessionSendsNoLine = $true }
Check 'F15 the session sent no telemetry line in the Tick: candidate NOT_MET (lineSentSameTick=no)' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'lineSentSameTick') -ceq 'no') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 { param($x) $x.DropGroupAfterJump = $true }
Check 'F16 a telemetry group other than calcg disappeared after the jump: candidate NOT_MET (groupsKept=no, availLostUnexpected names it; the expected calcg loss is listed in availLost too)' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'groupsKept') -ceq 'no') -and ((Ev $h 'PROBE_AFTER_SAME_TICK')[0] -match 'availLost=calcg\+door availLostUnexpected=door ') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 { param($x) $x.ArmLifecycleDuringInitialize() }
Check 'F17 a scenario lifecycle event during the call: candidate NOT_MET (noLifecycleEvent=no), stability stable=no' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'noLifecycleEvent') -ceq 'no') -and ((Cand $h) -ceq 'NOT_MET') -and ((Flag $h 'PROBE_STABILITY_SUMMARY' 'stable') -ceq 'no'))
$h = Op $STA 1 '' 36500000 { param($x) $x.ArmAtsStartedDuringInitialize() }
Check 'F18 the ATS Initialize relayed by AtsEX during the call is COUNTED (atsStartedDelta=1) and is information, not a failure' (((Ev $h 'PROBE_STABILITY_SUMMARY')[0] -match 'atsStartedDelta=1') -and ((Cand $h) -ceq 'MET'))
$h = Op $SET -1 '' 36500000 { param($x) $x.ArmSpeedChangeDuringSetTime() }
Check 'F19 SetTime that changed the speed: speedOk=no, candidate NOT_MET' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'speedOk') -ceq 'no') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 $null
Check 'F20 a stopping station: speed expectation zero, speedOk=yes' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'speedExpectation') -ceq 'zero') -and ((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'speedOk') -ceq 'yes'))
$h = Op $STA 2 '' 36500000 $null
Check 'F21 a passing station: no speed expectation (na), candidate MET' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'speedExpectation') -ceq 'na') -and ((Cand $h) -ceq 'MET'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick(); $h.Ticks(1); $h.FrameMs = 0; $h.Ticks(5)
Check 'F22 time that stops advancing after the jump: stable=no, timeAdvancing=no' (((Flag $h 'PROBE_STABILITY_SUMMARY' 'stable') -ceq 'no') -and ((Flag $h 'PROBE_STABILITY_SUMMARY' 'timeAdvancing') -ceq 'no'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick(); $h.Ticks(1); $h.SessionScenarioId = 7002; $h.Ticks(3)
Check 'F23 the scenario changed during the observation: PROBE_OBSERVATION_END reason=generation-changed' (((Ev $h 'PROBE_OBSERVATION_END')[0]) -match 'reason=generation-changed')
$h = NewH; Ready $h; $h.Host.ThrowOn = 'snapshot'; $h.Place('B1-T', 'rq-000001', $SET, -1, '', 36500000); $h.Ticks(3)
Check 'F24 no personal path or mail address reaches the log, even from an exception message that has them' (($h.Joined -notmatch 'someone') -and ($h.Joined -notmatch '[A-Za-z]:\\') -and ($h.Joined -match 'PROBE_EXCEPTION .* where=snapshot type=InvalidOperationException') -and ($h.Joined -match '<path>') -and ($h.Joined -match '<mail>'))
$h = NewH; Ready $h; $h.SessionScenarioId = 8001; $h.Ticks(2); $h.SessionScenarioId = 8002; $h.Ticks(2)
Check 'F25 PROBE_GENERATION counts a new generation with every new scenario id (3 so far)' (((N $h 'PROBE_GENERATION') -eq 3) -and ($h.Generation -eq 3))
$h = Op $SET -1 '' 36500000 $null
Check 'F26 the tick thread is logged once (PROBE_TICK_THREAD first=yes) and not repeated on the same thread' (((N $h 'PROBE_TICK_THREAD') -eq 1) -and ((Ev $h 'PROBE_TICK_THREAD')[0] -match 'first=yes'))
$h = Op $STA 2 '' 36500000 $null
$allLines = @($h.Joined -split "`n" | Where-Object { $_ })
$ctxLines = @($allLines | Where-Object { $_ -match ' PROBE_(INIT|TICK_THREAD|GENERATION) ' })
$tiedLines = @($allLines | Where-Object { $_ -notmatch ' PROBE_(INIT|TICK_THREAD|GENERATION) ' })
Check 'F27 EVERY line about the request carries the operation, the station, the requested location and the requested time; a line about nothing in particular (start, Tick thread, generation) has test=- req=-' (($tiedLines.Count -gt 12) -and (@($tiedLines | Where-Object { ($_ -notmatch ' req=rq-000001 ') -or ($_ -notmatch ' op=InitializeStationThenSetTime station=2 reqLoc=na reqTimeMs=36500000') }).Count -eq 0) -and (@($ctxLines | Where-Object { $_ -notmatch ' test=- req=- ' }).Count -eq 0))

# --- what the real machine showed (SI-B1 physical audit): calcg, the repeated Tick N+1, the second discontinuity of a SetTime-only call, doors ------------------------
$h = Op $STA 2 '' 36500000 $null
Check 'F28 calcg is not sent in the Tick that carries the discontinuity: it is listed in availLost but is an EXPECTED loss (availLostUnexpected=-, groupsKept=yes, candidate MET), and it is back in Tick N+1 (lastAvailKept=yes)' (((Ev $h 'PROBE_AFTER_SAME_TICK')[0] -match 'availLost=calcg availLostUnexpected=- ') -and ((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'groupsKept') -ceq 'yes') -and ((Cand $h) -ceq 'MET') -and ((Flag $h 'PROBE_AFTER_NEXT_TICK' 'lastAvailKept') -ceq 'yes'))
$h = NewH; Ready $h; $h.DropCalcgInCallTick = $true; $h.Place('B1-T', 'rq-000001', $SET, -1, '', ([int]$h.World.TimeMs + 16)); $h.Tick(); $h.Ticks(6)
Check 'F29 calcg lost in a Tick WITHOUT a discontinuity (a 16 ms SetTime) is NOT expected: discontinuitySameTick=no, availLostUnexpected=calcg, groupsKept=no, candidate NOT_MET' (((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'discontinuitySameTick') -ceq 'no') -and ((Ev $h 'PROBE_AFTER_SAME_TICK')[0] -match 'availLostUnexpected=calcg ') -and ((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'groupsKept') -ceq 'no') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 $null
$nx = (Ev $h 'PROBE_AFTER_NEXT_TICK')[0]; $ac2 = (Ev $h 'PROBE_AFTER_CALL')[0]
Check 'F30 the Tick right after the call repeats the time and location of the call (as the real BVE does); stable=yes, nextTickRepeat=yes, distinctTicks=yes; the 5 samples are 5 different Ticks' (([regex]::Match($nx, 'nTimeMs=(\d+)').Groups[1].Value -ceq [regex]::Match($ac2, 'aTimeMs=(\d+)').Groups[1].Value) -and ([regex]::Match($nx, 'nLoc=(\S+)').Groups[1].Value -ceq [regex]::Match($ac2, 'aLoc=(\S+)').Groups[1].Value) -and ((Ev $h 'PROBE_STABILITY_SUMMARY')[0] -match 'stable=yes samples=5 timeAdvancing=yes locationNotBackwards=yes .* nextTickRepeat=yes distinctTicks=yes') -and (((Ev $h 'PROBE_STABILITY') | ForEach-Object { [regex]::Match($_, ' tick=(\d+) ').Groups[1].Value }) -join ',') -ceq '18,19,20,21')
$h = Op $STA 1 '' 36500000 { param($x) $x.BackstepAfterCall = $true }
Check 'F31 time that goes BACKWARDS in the Tick right after the call is still a failure: stable=no, timeAdvancing=no' (((Flag $h 'PROBE_STABILITY_SUMMARY' 'stable') -ceq 'no') -and ((Flag $h 'PROBE_STABILITY_SUMMARY' 'timeAdvancing') -ceq 'no'))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick(); $h.Ticks(2); $h.World.TimeMs += 16; $h.ExtraEndTick(); $h.Ticks(4)
Check 'F32 two samples that belong to the SAME Tick (time still moves between them) are not 5 different Ticks: distinctTicks=no, timeAdvancing=yes, stable=no' (((Flag $h 'PROBE_STABILITY_SUMMARY' 'distinctTicks') -ceq 'no') -and ((Flag $h 'PROBE_STABILITY_SUMMARY' 'timeAdvancing') -ceq 'yes') -and ((Flag $h 'PROBE_STABILITY_SUMMARY' 'stable') -ceq 'no'))
$h = Op $SET -1 '' 36300000 { param($x) $x.RepeatDiscontinuityNextTick = $true }
Check 'F33 SetTime alone can count the discontinuity twice (Tick N and N+1, as on BVE5 Legacy): sessionDiscontinuitiesDelta=2 is recorded as it is, the candidate stays MET, calcg is still absent in N+1 (lastAvailKept=no)' (((Ev $h 'PROBE_AFTER_SAME_TICK')[0] -match 'sessionDiscontinuitiesDelta=1 ') -and ((Ev $h 'PROBE_AFTER_NEXT_TICK')[0] -match 'sessionDiscontinuitiesDelta=2 ') -and ((Ev $h 'PROBE_STABILITY_SUMMARY')[0] -match 'sessionDiscontinuitiesDelta=2 ') -and ((Cand $h) -ceq 'MET') -and ((Flag $h 'PROBE_AFTER_NEXT_TICK' 'lastAvailKept') -ceq 'no') -and ((Flag $h 'PROBE_STABILITY_SUMMARY' 'stable') -ceq 'yes'))
$h = Op $STA 1 '' 36500000 $null; $hp = Op $STA 2 '' 36500000 $null
Check 'F34 the doors: a STOPPING station leaves the doors open (BVE normal), a PASSING station leaves them closed' (((Ev $h 'PROBE_AFTER_CALL')[0] -match 'aDoorsClosed=0 ') -and ((Ev $hp 'PROBE_AFTER_CALL')[0] -match 'aDoorsClosed=1 '))

# =============================================================================================================================================
Write-Host '==== D: Dispose ===='
$h = NewH; Ready $h; $h.DisposeNow()
Check 'D01 Dispose when idle: DISPOSE_BEGIN and DISPOSE_END, no host call, apiCallsAfterDispose=0' (((N $h 'PROBE_DISPOSE_BEGIN') -eq 1) -and ((N $h 'PROBE_DISPOSE_END') -eq 1) -and ($h.Host.Calls.Count -eq 0) -and ($h.Host.CallsAfterDispose -eq 0) -and ((Ev $h 'PROBE_DISPOSE_END')[0] -match 'apiCallsAfterDispose=0'))
$h = NewH; $h.SessionActive = $false; $h.Ticks(3); $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Ticks(2); $h.DisposeNow()
Check 'D02 a request still pending at Dispose is dropped: DISPOSE_REJECTED pending-request-dropped, NO host call, the file is left as it is (stale for the next process)' (((Ev $h 'PROBE_DISPOSE_REJECTED')[0] -match 'reason=pending-request-dropped') -and ($h.Host.Calls.Count -eq 0) -and ($h.Io.RequestText -ne $null) -and ((Ev $h 'PROBE_DISPOSE_BEGIN')[0] -match 'pending=yes'))
$h = NewH; Ready $h; $h.DisposeNow(); $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Ticks(5)
Check 'D03 a request that appears after Dispose began is never accepted or executed; one DISPOSE_REJECTED where=tick' (($h.Host.Calls.Count -eq 0) -and ($h.Accepted -eq 0) -and ($h.Host.CallsAfterDispose -eq 0) -and ((N $h 'PROBE_DISPOSE_REJECTED') -eq 1) -and ((Ev $h 'PROBE_DISPOSE_REJECTED')[0] -match 'where=tick'))
$h = NewH; Ready $h; $h.ArmDisposeDuringInitialize(); $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick()
Check 'D04 Dispose started INSIDE Initialize (same thread): SetTime is NOT called, partial=yes, no call after Dispose' (((Calls $h) -ceq 'InitializeStation:1') -and ($h.Host.CallsAfterDispose -eq 0) -and ($h.ApiAfterDispose -eq 0) -and ((Flag $h 'PROBE_AFTER_CALL' 'partial') -ceq 'yes') -and ((Ev $h 'PROBE_DISPOSE_BEGIN')[0] -match 'inCall=yes sameThreadAsCall=yes') -and ($h.Joined -match 'PROBE_DISPOSE_REJECTED .* where=before-set-time'))
$h = NewH; Ready $h; $h.SetDisposeWaitMs(100); $h.ArmHoldInitialize(500); $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000)
$h.StartTickOnNewThread(); Start-Sleep -Milliseconds 150; $h.DisposeOnOtherThreadAndJoin(); $h.JoinTick()
Check 'D05 Dispose on ANOTHER thread while the Tick is inside Initialize: Dispose waits only its bound (gateEntered=no), the second call (SetTime) is not made' (((Calls $h) -ceq 'InitializeStation:1') -and ($h.Host.CallsAfterDispose -eq 0) -and ((Ev $h 'PROBE_DISPOSE_END')[0] -match 'gateEntered=no') -and ((Ev $h 'PROBE_DISPOSE_BEGIN')[0] -match 'inCall=yes sameThreadAsCall=no'))
$h = NewH; Ready $h; $h.DisposeNow(); $h.DisposeNow()
Check 'D06 Dispose twice writes one BEGIN and one END' (((N $h 'PROBE_DISPOSE_BEGIN') -eq 1) -and ((N $h 'PROBE_DISPOSE_END') -eq 1))
$h = NewH; Ready $h; $h.Place('B1-T', 'rq-000001', $STA, 1, '', 36500000); $h.Tick(); $h.Tick(); $h.DisposeNow()
$snaps = $h.Host.SnapshotCalls; $h.Ticks(10)
Check 'D07 Dispose during the observation: no further snapshot or call, DISPOSE_REJECTED observation-dropped' (($h.Host.SnapshotCalls -eq $snaps) -and ((Ev $h 'PROBE_DISPOSE_REJECTED')[0] -match 'reason=observation-dropped') -and ($h.Host.CallsAfterDispose -eq 0))

# =============================================================================================================================================
Write-Host '==== H / E: re-entrancy and exceptions ===='
$h = Op $STA 1 '' 36500000 { param($x) $x.ArmReenterDuringInitialize() }
Check 'H01 a Tick re-entered from inside Initialize is ignored (PROBE_REENTRANT_TICK), the sequence still runs once (2 calls), candidate NOT_MET (noReentry=no)' (($h.ReentrantTicks -ge 1) -and ((N $h 'PROBE_REENTRANT_TICK') -ge 1) -and ($h.Host.Calls.Count -eq 2) -and ((Flag $h 'PROBE_COMPLETION_CANDIDATE' 'noReentry') -ceq 'no') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 { param($x) $x.Host.ThrowOn = 'initialize' }
Check 'E01 Initialize throws: SetTime is NOT called, PROBE_EXCEPTION with the type, the request stays consumed, candidate NOT_MET' (((Calls $h) -ceq 'InitializeStation:1') -and ((Ev $h 'PROBE_EXCEPTION')[0] -match 'where=initialize type=InvalidOperationException') -and $h.Io.Ledger.Contains('rq-000001') -and ((Cand $h) -ceq 'NOT_MET'))
$h = Op $STA 1 '' 36500000 { param($x) $x.Host.ThrowOn = 'settime' }
Check 'E02 SetTime throws: logged, candidate NOT_MET, the Tick is not affected (the observation still ends)' ((((Ev $h 'PROBE_EXCEPTION')[0]) -match 'where=set-time') -and ((Cand $h) -ceq 'NOT_MET') -and ((N $h 'PROBE_OBSERVATION_END') -eq 1))
$h = Op $SET -1 '' 36500000 { param($x) $x.Host.ThrowOn = 'snapshot' }
Check 'E03 the snapshot throws: the request is rejected (snapshot-unreadable) with no host call, and the Tick survives' (($h.Host.Calls.Count -eq 0) -and ((Ev $h 'PROBE_REQUEST_REJECTED')[0] -match 'reason=snapshot-unreadable'))

# =============================================================================================================================================
Write-Host '==== Y: the real file io (a throw-away folder) ===='
$yd = Join-Path $testDir 'realio'; New-Item -ItemType Directory -Force $yd | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$t0 = [DateTime]::UtcNow.AddSeconds(-1)
$d = New-Object B1Tests.RealIoDriver $yd
$t1 = [DateTime]::UtcNow.AddSeconds(1)
$e0 = $d.Exists()
[IO.File]::WriteAllText($d.RequestPath, "B1PROBE-REQUEST 1`nTestId=B1-O1`n", $utf8)
$sig1 = $d.Signature()
Check 'Y01 the request file is seen when it appears and read exactly (UTF-8, no BOM needed); its signature changes when it changes' ((-not $e0) -and $d.Exists() -and ($d.Read() -ceq "B1PROBE-REQUEST 1`nTestId=B1-O1`n") -and ($sig1 -ne $null))
[IO.File]::WriteAllText($d.RequestPath, "B1PROBE-REQUEST 1`r`nTestId=B1-O1`r`nMore=1`r`n", $utf8)
Check 'Y02 a rewritten request file has another signature and CRLF text is read as it is' (($d.Signature() -ne $sig1) -and ($d.Read() -like "*More=1*"))
$ok = $d.Retire('consumed-rq-real-01')
$renamed = @(Get-ChildItem -LiteralPath $yd -File | Where-Object { $_.Name -like 'TSScoring-B1Probe-request.consumed-rq-real-01.*.txt' })
Check 'Y03 Retire renames the request file (the original name is gone, the content is kept under the new name); a second Retire with no file is true' ($ok -and (-not $d.Exists()) -and ($renamed.Count -eq 1) -and ([IO.File]::ReadAllText($renamed[0].FullName) -like "*More=1*") -and $d.Retire('x'))
[IO.File]::WriteAllText($d.RequestPath, 'x', $utf8)
$null = $d.Retire('../../evil')
$names = @(Get-ChildItem -LiteralPath $yd -File | ForEach-Object { $_.Name })
$parentFiles = @(Get-ChildItem -LiteralPath (Split-Path $yd -Parent) -File)
Check 'Y04 a Retire word with path characters cannot leave the folder (sanitised into the file name)' (($names | Where-Object { $_ -like '*evil*' }).Count -eq 1 -and (($names | Where-Object { $_ -like '*evil*' })[0] -notmatch '[\\/]') -and (($parentFiles | Where-Object { $_.Name -like '*evil*' }).Count -eq 0))
$a1 = $d.LedgerAppend('rq-aaaa1111'); $a2 = $d.LedgerAppend('rq-bbbb2222')
$d2 = New-Object B1Tests.RealIoDriver $yd
Check 'Y05 the ledger keeps ids (an exact match only, not a prefix) and a second instance on the same folder sees them' ($a1 -and $a2 -and $d.LedgerContains('rq-aaaa1111') -and (-not $d.LedgerContains('rq-aaaa')) -and $d2.LedgerContains('rq-bbbb2222') -and (-not $d2.LedgerContains('rq-cccc3333')) -and ([IO.File]::ReadAllLines($d.LedgerPath).Count -eq 2))
$d.Write('line one'); $rd = New-Object IO.FileStream($d.LogPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite); $d.Write('line two'); $rd.Close()
Check 'Y06 the log is append-only, ordered, and can be written while another process reads it' (([IO.File]::ReadAllLines($d.LogPath) -join '|') -ceq 'line one|line two')
$big = 'x' * 98
for ($i = 0; $i -lt 22000; $i++) { $d.Write($big) }
$len1 = (Get-Item $d.LogPath).Length
for ($i = 0; $i -lt 500; $i++) { $d.Write($big) }
$len2 = (Get-Item $d.LogPath).Length
$capLines = @([IO.File]::ReadAllLines($d.LogPath) | Where-Object { $_ -like '*PROBE_LOG_CAP_REACHED*' })
Check 'Y07 the log stops at 2 MiB with ONE PROBE_LOG_CAP_REACHED line and does not grow afterwards' (($len1 -le (2 * 1024 * 1024 + 400)) -and ($len2 -eq $len1) -and ($capLines.Count -eq 1))
[IO.File]::WriteAllText($d2.RequestPath, ('y' * 3000), $utf8)
Check 'Y08 an oversized request file is not read in full: the parser refuses it as too-large' (($P::ParseReason($d2.Read())) -like 'too-large*')
$null = $d2.Retire('rejected')
$nd = New-Object B1Tests.RealIoDriver (Join-Path $testDir 'does-not-exist')
$nd.Write('x')
Check 'Y09 a missing folder never throws: no request, ledger append false, write ignored' ((-not $nd.Exists()) -and (-not $nd.LedgerAppend('rq-dddd4444')) -and (-not $nd.LedgerContains('rq-dddd4444')) -and ($nd.Retire('x')))
$st = [DateTime]::ParseExact($d.StartUtcIso, 'yyyy-MM-ddTHH:mm:ss.fffZ', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal)
Check 'Y10 the probe start is the construction time of the instance (not the process start), the pid is this process, the metrics have the logged form' (($st -ge $t0) -and ($st -le $t1) -and ($d.Pid -eq $PID) -and ($d.Metrics() -match '^procThreads=\d+ procHandles=\d+$'))

# end to end: engine + fake host + the REAL io
$ed = Join-Path $testDir 'e2e'; New-Item -ItemType Directory -Force $ed | Out-Null
$rh = New-Object B1Tests.RealHarness $ed
$rh.Ticks(15)
[IO.File]::WriteAllText((Join-Path $ed 'TSScoring-B1Probe-request.txt'), [B1Tests.RealHarness]::RequestNow('B1-T', 'rq-real-0001', $STA, 1, '', 36500000, 0.0), $utf8)
$rh.Ticks(10)
$logText = [IO.File]::ReadAllText((Join-Path $ed 'TSScoring-B1Probe.log'))
$consumedFiles = @(Get-ChildItem -LiteralPath $ed -File | Where-Object { $_.Name -like 'TSScoring-B1Probe-request.consumed-rq-real-0001.*.txt' })
Check 'Y11 end to end on the real io: the request file is executed ONCE (2 calls), renamed to consumed-<id>, the id is in the ledger on disk, the log file has every required event' (($rh.Executed -eq 1) -and ($rh.Host.Calls.Count -eq 2) -and ($consumedFiles.Count -eq 1) -and (-not (Test-Path (Join-Path $ed 'TSScoring-B1Probe-request.txt'))) -and ([IO.File]::ReadAllLines((Join-Path $ed 'TSScoring-B1Probe-consumed.txt')) -contains 'rq-real-0001') -and ($logText -match 'PROBE_INIT') -and ($logText -match 'PROBE_EXECUTE_BEGIN') -and ($logText -match 'PROBE_COMPLETION_CANDIDATE test=B1-T req=rq-real-0001 .*result=MET') -and ($logText -match 'PROBE_OBSERVATION_END'))
[IO.File]::WriteAllText((Join-Path $ed 'TSScoring-B1Probe-request.txt'), [B1Tests.RealHarness]::RequestNow('B1-T', 'rq-real-0001', $STA, 2, '', 36600000, 0.0), $utf8)
$rh.Ticks(3)
Check 'Y12 end to end: the same RequestId again is a duplicate (no call), its file is renamed duplicate' (($rh.Duplicates -eq 1) -and ($rh.Host.Calls.Count -eq 2) -and (@(Get-ChildItem -LiteralPath $ed -File | Where-Object { $_.Name -like 'TSScoring-B1Probe-request.duplicate.*.txt' }).Count -eq 1))
[IO.File]::WriteAllText((Join-Path $ed 'TSScoring-B1Probe-request.txt'), [B1Tests.RealHarness]::RequestNow('B1-T', 'rq-real-0002', $SET, -1, '', 36700000, 120.0), $utf8)
$rh.Ticks(3)
Check 'Y13 end to end: a request created before this probe instance started is refused (created-before-process-start), renamed rejected, never executed' (($rh.Rejected -eq 1) -and ($rh.Host.Calls.Count -eq 2) -and ([IO.File]::ReadAllText((Join-Path $ed 'TSScoring-B1Probe.log')) -match 'PROBE_REQUEST_REJECTED test=B1-T req=rq-real-0002 .*reason=created-before-process-start') -and (@(Get-ChildItem -LiteralPath $ed -File | Where-Object { $_.Name -like 'TSScoring-B1Probe-request.rejected.*.txt' }).Count -eq 1))
[IO.File]::WriteAllText((Join-Path $ed 'TSScoring-B1Probe-request.txt'), [B1Tests.RealHarness]::RequestNow('B1-T', 'rq-real-0003', $SET, -1, '', 36700000, 0.0), $utf8)
$rh.Dispose()
$rh.Ticks(5)
$logText = [IO.File]::ReadAllText((Join-Path $ed 'TSScoring-B1Probe.log'))
Check 'Y14 end to end: a request still unread at Dispose is left in place (not renamed, not executed); DISPOSE_BEGIN / END are in the log file' ((Test-Path (Join-Path $ed 'TSScoring-B1Probe-request.txt')) -and ($rh.Host.Calls.Count -eq 2) -and ($logText -match 'PROBE_DISPOSE_BEGIN') -and ($logText -match 'PROBE_DISPOSE_END') -and ($logText -notmatch 'req=rq-real-0003 .*PROBE_EXECUTE'))
$badReal = @($logText -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch '^\d\d:\d\d:\d\d\.\d{3} P=\d+ T=\d+ PROBE_[A-Z_]+ test=\S+ req=\S+ host=AtsExLegacy gen=\d+ scn=\S+ tick=\d+') })
Check 'Y15 every line of the real log file has the required fields, and it contains no path or mail address' (($badReal.Count -eq 0) -and ($logText -notmatch '[A-Za-z]:\\') -and ($logText -notmatch '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'))
Write-Host '==== S: static guards on the sources ===='
$coreText = ReadText $corePath
$coreCode = CodeOf $coreText
$tryExec = MethodText $coreCode 'TryExecute'
$allMut = [regex]::Matches($coreCode, 'host\.(SetTime|InitializeStation|InitializeLocation)\(').Count
$mutInTry = [regex]::Matches($tryExec, 'host\.(SetTime|InitializeStation|InitializeLocation)\(').Count
Check 'S01 the core names no AtsEx / BveTypes type' (($coreCode -notmatch 'AtsEx|BveTypes|IBveHacker|ClassWrappers|INative'))
Check 'S02 the three mutating host calls (SetTime, InitializeStation, InitializeLocation) appear 3 times in the core, ALL inside TryExecute' (($tryExec.Length -gt 200) -and ($allMut -eq 3) -and ($mutInTry -eq 3))
$members = @([regex]::Matches($coreCode, '\bhost\.([A-Za-z]+)\(') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
Check 'S03 the core uses exactly the six IB1ProbeHost members and no other' (($members -join ',') -ceq 'Counters,InitializeLocation,InitializeStation,IsScenarioCreated,SetTime,Snapshot')
$snapM = MethodText $coreCode 'SafeSnapshot'; $cntM = MethodText $coreCode 'SafeCounters'
Check 'S04 host.Snapshot only in SafeSnapshot, host.Counters only in SafeCounters, host.IsScenarioCreated only in TryExecute' (([regex]::Matches($coreCode, 'host\.Snapshot\(').Count -eq 1) -and ($snapM -match 'host\.Snapshot\(') -and ([regex]::Matches($coreCode, 'host\.Counters\(').Count -eq 1) -and ($cntM -match 'host\.Counters\(') -and ([regex]::Matches($coreCode, 'host\.IsScenarioCreated\(').Count -eq 1) -and ($tryExec -match 'host\.IsScenarioCreated\('))
$disposeM = MethodText $coreCode 'OnDispose'
Check 'S05 OnDispose reads nothing from the host and makes no call (no host., no Safe*)' (($disposeM.Length -gt 100) -and ($disposeM -notmatch 'host\.') -and ($disposeM -notmatch 'Safe(Snapshot|Counters|View)') -and ($disposeM -notmatch 'TryExecute|RunCall'))
$endM = MethodText $coreCode 'EndTick'
Check 'S06 EndTick (after the session) makes no mutating call' (($endM.Length -gt 100) -and ($endM -notmatch 'host\.(SetTime|Initialize)') -and ($endM -notmatch 'TryExecute|RunCall'))
$beginM = MethodText $coreCode 'BeginTick'
Check 'S07 TryExecute is called from BeginTick only' (([regex]::Matches($coreCode, '\bTryExecute\(\)').Count -eq 2) -and ($beginM -match 'TryExecute\(\)'))
Check 'S08 write-ahead is in the source order: the ledger append comes before the first RunCall' (($tryExec.IndexOf('io.LedgerAppend') -ge 0) -and ($tryExec.IndexOf('io.LedgerAppend') -lt $tryExec.IndexOf('RunCall(a')))
Check 'S09 the guard (no start of a host call after Dispose began) is checked before EVERY call and the read-back snapshot' (([regex]::Matches((MethodText $coreCode 'RunCall'), 'Guard\(a').Count -eq 1) -and ((MethodText $coreCode 'SafeSnapshot') -match 'if \(disposing\)'))
$forbidden = 'new Thread|ThreadPool|System\.Timers|Task\.|Task<|async |BeginInvoke|Parallel\.|UdpClient|TcpClient|Socket|HttpClient|WebClient|54321|54322|TokJump|JUMP_|COMPLETE|FormatAvail|lb\.Token'
$probeFiles = @($corePath, $hostPath, (Join-Path $probeDir 'src\AssemblyInfo.B1Probe.cs'))
$hits = @(); foreach ($pf in $probeFiles) { $c = CodeOf (ReadText $pf); foreach ($m in [regex]::Matches($c, $forbidden)) { $hits += ($pf + ':' + $m.Value) } }
Check 'S10 no thread, timer, task, network type, port 54321 / 54322, jump token, JUMP_ / COMPLETE or AVAIL writer in any probe source (code, comments removed)' ($hits.Count -eq 0)
if (-not $BehaviorOnly) {
    $hostText = ReadText $hostPath; $hostCode = CodeOf $hostText
    $stM = MethodText $hostCode 'SetTime'; $iaM = MethodText $hostCode 'InitializeStation'; $ilM = MethodText $hostCode 'InitializeLocation'
    Check 'S11 in the AtsEx adapter the three real host calls exist exactly once each, each in its own adapter method' (([regex]::Matches($hostCode, '\.SetTime\(').Count -eq 1) -and ($stM -match 'TimeManager\.SetTime\(timeMs\)') -and ([regex]::Matches($hostCode, '\.Initialize\(').Count -eq 1) -and ($iaM -match 'Scenario\.Initialize\(stationIndex\)') -and ([regex]::Matches($hostCode, '\.InitializeTimeAndLocation\(').Count -eq 1) -and ($ilM -match 'Scenario\.InitializeTimeAndLocation\(location, timeMs\)'))
    Check 'S12 the adapter event handlers only count (Interlocked.Increment), they read no BVE object' ((@([regex]::Matches($hostCode, 'private void On[A-Za-z]+\([^)]*\) \{ Interlocked\.Increment\(ref [a-zA-Z]+\); \}')).Count -eq 8) -and ([regex]::Matches($hostCode, 'private void On').Count -eq 8))
    $hookDispose = $hostCode.Substring($hostCode.IndexOf('internal void OnDispose()'))
    Check 'S13 B1ProbeHook.OnDispose only calls engine.OnDispose and host.Unsubscribe' (($hookDispose -match 'e\.OnDispose\(\)') -and ($hookDispose -match 'host\.Unsubscribe\(\)') -and ($hookDispose -notmatch 'SetTime|Initialize'))

    Write-Host '==== S: the product is unchanged; the probe is wired only through the generated copy ===='
    # Phase PID-D4 Slice 1 (a later, accepted-in-progress phase) changes exactly these four product paths on purpose; they are removed from this probe-phase pin and nothing else is
    $slice1Product = @('TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyDataPlaneSink.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/AssemblyInfo.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.csproj')
    $prodStatus = @((RunGit @('status', '--porcelain', '--untracked-files=all', '--', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src', 'TsScoringPlugin/Handshake/Telemetry/Shared', 'TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.csproj')) -split "`n" | Where-Object { $_ } | Where-Object { $s1 = $_.Substring(3).Trim('"'); $s1 -notin $slice1Product })
    Check 'S14 the product Legacy telemetry sources, the shared contract and the product csproj are byte-identical to HEAD (no modification, no new file)' ($prodStatus.Count -eq 0)
    $outside = @((RunGit @('status', '--porcelain', '--untracked-files=all')) -split "`n" | Where-Object { $_ } | ForEach-Object { $_.Substring(3).Trim('"') })
    $allowedRx = @(
        '^TsScoringPlugin/Handshake/Tests/B1Probe/(src/(B1ProbeCore|B1ProbeHost|AssemblyInfo\.B1Probe)\.cs|TSScoringPlugin\.AtsExLegacy\.Telemetry\.B1Probe\.csproj|(New-B1ProbeExtension|Build-B1Probe)\.ps1)$',
        '^TsScoringPlugin/Handshake/Tests/(B1ProbeTestFixture\.cs|Test-JumpProbeB1\.ps1)$',
        '^TsScoringPlugin/Handshake/Docs/Handshake-PhaseSIB1-JumpProbe\.md$',
        '^TsScoringPlugin/Handshake/Tests/Test-DependencyNoticeM1\.ps1$',        # existing guards re-pinned for the probe folder / files (allow-list additions only; S15b proves nothing was weakened)
        '^TsScoringPlugin/Handshake/Tools/Verify-Phase(C3|L1|L3|SIA7)\.ps1$'
    )
    $extra = @($outside | Where-Object { $p = $_; -not (@($allowedRx | Where-Object { $p -match $_ }).Count -gt 0) })
    Check 'S15 the working tree contains only the probe files of this phase (no Current, Caller, Bridge, Shared, Python, product telemetry or test file outside the list)' ($extra.Count -eq 0)
    if ($extra.Count -gt 0) { Write-Host ('   outside the list: ' + ($extra -join ', ')) }

    # the five existing guards that were re-pinned: allow-list additions only, no check removed
    $repinned = @('Tests/Test-DependencyNoticeM1.ps1', 'Tools/Verify-PhaseC3.ps1', 'Tools/Verify-PhaseL1.ps1', 'Tools/Verify-PhaseL3.ps1', 'Tools/Verify-PhaseSIA7.ps1')
    $weak = @()
    foreach ($rp in $repinned) {
        $rel = 'TsScoringPlugin/Handshake/' + $rp
        $old = (RunGit @('show', ('HEAD:' + $rel))) -replace "`r`n", "`n"
        $new = ReadText (Join-Path $Root $rp.Replace('/', '\'))
        $co = [regex]::Matches($old, '(?m)^\s*Check\b').Count; $cn = [regex]::Matches($new, '(?m)^\s*Check\b').Count
        $numstat = (RunGit @('diff', '--numstat', 'HEAD', '--', $rel)).Trim().Split("`t")
        $del = $(if ($numstat.Count -ge 2) { [int]$numstat[1] } else { 0 })
        $delLimit = 2
        if ($rp -eq 'Tools/Verify-PhaseL3.ps1') { $delLimit = 3 }      # Phase PID-D4 Slice 1 (J2/J3) re-pins THREE isolation lines of Verify-PhaseL3 (version list, named kernel objects, the one linked Current core); allow-list additions only, no check removed
        if (($cn -lt $co) -or ($del -gt $delLimit)) { $weak += ($rp + ' checks ' + $co + '->' + $cn + ' deleted lines ' + $del) }
    }
    Check 'S15b the five re-pinned guards lost no check (Check count not lower than at HEAD) and changed at most 2 existing lines each' ($weak.Count -eq 0)
    if ($weak.Count -gt 0) { Write-Host ('   ' + ($weak -join '; ')) }    $m1a = @((RunGit @('status', '--porcelain', '--untracked-files=all', '--', 'TsScoringPlugin/Handshake/Bridge', 'TsScoringPlugin/Handshake/Caller', 'TsScoringPlugin/Handshake/Shared', '*.py')) -split "`n" | Where-Object { $_ } | Where-Object { $_.Substring(3).Trim('"') -notin @('tests/legacy_dataplane_chain_check.py', 'tests/test_legacy_dataplane_interop_d4.py', 'tests/test_hud_data_path_e4.py') })      # Phase PID-D4 Slice 1: its two NEW test modules and the one static audit test it re-pinned (test code only, no product Python)
    Check 'S16 the M1a control plane, both Bridges, the Caller, the Handshake shared protocol and every Python file are unchanged' ($m1a.Count -eq 0)
    $cur = @((RunGit @('status', '--porcelain', '--untracked-files=all', '--', 'TsScoringPlugin', ':(exclude)TsScoringPlugin/Handshake')) -split "`n" | Where-Object { $_ })
    Check 'S17 the Current (BveEX) sender and everything else under TsScoringPlugin outside Handshake are unchanged' ($cur.Count -eq 0)
    $pr = ReadText (Join-Path $top 'pause_recovery.py')
    Check 'S18 the scoring gate / pause recovery constants are the accepted ones: FIRST_QUIET_S = 0.3 and exactly two automatic P call sites' (($pr -match '(?m)^FIRST_QUIET_S = 0\.3\b') -and ([regex]::Matches($pr, 'self\._o\.press_p_for_recovery\(').Count -eq 2))
    $mi = ReadText (Join-Path $top 'managed_input.py')
    Check 'S19 the managed gate still requires "jump" and the probe adds no jump token: managed_input.py has the jump requirement, TelemetryContract.cs has no TokJump' (($mi -match 'jump') -and ((ReadText (Join-Path $Root 'Telemetry\Shared\TelemetryContract.cs')) -notmatch 'TokJump'))

    $gen = New-Object System.Collections.Generic.List[string]
    $genPath = Join-Path $testDir 'gen\LegacyTelemetryExtension.B1Probe.g.cs'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $probeDir 'New-B1ProbeExtension.ps1') -Root $Root -Output $genPath | Out-Null
    $genOk = ($LASTEXITCODE -eq 0) -and (Test-Path $genPath)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $probeDir 'New-B1ProbeExtension.ps1') -Root $Root -Output $genPath -Verify | Out-Null
    $verOk = ($LASTEXITCODE -eq 0)
    Check 'S20 the generated probe Extension = the product Extension + exactly the five anchored insertions (reversing them gives the product file back)' ($genOk -and $verOk)
    $gt = ReadText $genPath
    $tickBody = [regex]::Match($gt, '(?ms)public override TickResult Tick\(TimeSpan elapsed\)\s*\{.*?\n        \}\n').Value
    $dispBody = [regex]::Match($gt, '(?ms)public override void Dispose\(\)\s*\{.*?\n        \}\n').Value
    Check 'S21 in the generated Tick the probe runs BEFORE the session Tick (BeginTick) and EndTick after it; in Dispose the probe is disposed BEFORE the session' (($tickBody.IndexOf('b1probe.BeginTick') -ge 0) -and ($tickBody.IndexOf('b1probe.BeginTick') -lt $tickBody.IndexOf('session.OnTick')) -and ($tickBody.IndexOf('session.OnTick') -lt $tickBody.IndexOf('b1probe.EndTick')) -and ($dispBody.IndexOf('b1probe.OnDispose') -ge 0) -and ($dispBody.IndexOf('b1probe.OnDispose') -lt $dispBody.IndexOf('session.OnDispose')))
    Check 'S22 the generated Extension calls the hook exactly 5 times (TapSink, Attach, BeginTick, EndTick, OnDispose) and creates it once' (([regex]::Matches($gt, 'b1probe\.').Count -eq 5) -and ([regex]::Matches($gt, 'new TSScoringPlugin\.Telemetry\.B1Probe\.B1ProbeHook\(\)').Count -eq 1))
    $pc = [regex]::Replace((ReadText (Join-Path $probeDir 'TSScoringPlugin.AtsExLegacy.Telemetry.B1Probe.csproj')), '(?s)<!--.*?-->', ''); $dc = [regex]::Replace((ReadText (Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj')), '(?s)<!--.*?-->', '')
    $ai = (ReadText (Join-Path $probeDir 'src\AssemblyInfo.B1Probe.cs')); $aiCode = CodeOf $ai; $pai = ReadText (Join-Path $Root 'Telemetry\Legacy\src\AssemblyInfo.cs')
    Check 'S23 the probe project keeps the product assembly name, defines B1_PROBE, compiles the generated Extension and NOT src\LegacyTelemetryExtension.cs / src\AssemblyInfo.cs' (($pc -match '<AssemblyName>TSScoringPlugin\.AtsExLegacy\.Telemetry</AssemblyName>') -and ($pc -match 'B1_PROBE') -and ($pc -match 'Compile Include="\$\(GeneratedExtension\)"') -and ($pc -notmatch 'src\\LegacyTelemetryExtension\.cs') -and ($pc -notmatch 'src\\AssemblyInfo\.cs'))
    Check 'S24 the product project does not know the probe (no probe, no B1 in the product csproj)' (($dc -cnotmatch 'B1|b1probe|\\probe\\'))
    Check 'S25 the probe version is 0.4.1.1 (0.4.1.0 = the build that ran on the real machine), marked probe-observation-only, and is neither the product 0.4.0.0 nor the SI-B2 version 0.5.0.0' (($ai -match 'AssemblyVersion\("0\.4\.1\.1"\)') -and ($ai -match 'AssemblyInformationalVersion\("0\.4\.1\.1-b1-probe-observation-only"\)') -and ($pai -match 'AssemblyVersion\("0\.4\.[02]\.0"\)') -and ($aiCode -notmatch '0\.5\.0\.0') -and ($ai -match 'NOT A RELEASE'))

    Write-Host '==== S: the built DLLs ===='
    $b1 = Join-Path $testDir 'build1'; $b2 = Join-Path $testDir 'build2'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $probeDir 'Build-B1Probe.ps1') -WorkDir $b1 -Root $Root -AlsoProduct | Out-Null
    $built1 = ($LASTEXITCODE -eq 0)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $probeDir 'Build-B1Probe.ps1') -WorkDir $b2 -Root $Root | Out-Null
    $built2 = ($LASTEXITCODE -eq 0)
    $pd1 = Join-Path $b1 'probe-out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'; $pd2 = Join-Path $b2 'probe-out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'; $prd = Join-Path $b1 'product-out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
    Check 'S26 the probe DLL builds (warnings are errors) and the build is deterministic (two builds, same SHA-256)' ($built1 -and $built2 -and (Test-Path $pd1) -and (Test-Path $pd2) -and ((Get-FileHash $pd1 -Algorithm SHA256).Hash -ceq (Get-FileHash $pd2 -Algorithm SHA256).Hash))
    Check 'S27 the PRODUCT DLL rebuilt from the working tree is byte-identical to the accepted 0.4.0.0 (SHA-256 995486BE...): the product is unchanged' ((Test-Path $prd) -and ((Get-FileHash $prd -Algorithm SHA256).Hash -ceq $AcceptedProductSha) -and ((Get-Item $prd).VersionInfo.FileVersion -ceq '0.4.0.0'))
    $pbytes = [IO.File]::ReadAllBytes($pd1); $prbytes = [IO.File]::ReadAllBytes($prd)
    $ptext = [Text.Encoding]::GetEncoding(28591).GetString($pbytes); $prtext = [Text.Encoding]::GetEncoding(28591).GetString($prbytes)
    Check 'S28 the probe DLL contains the probe types and is version 0.4.1.1; the product DLL contains none of them' (($ptext.Contains('B1ProbeHook')) -and ($ptext.Contains((U16 'PROBE_REQUEST_ACCEPTED'))) -and ((Get-Item $pd1).VersionInfo.FileVersion -ceq '0.4.1.1') -and (-not $prtext.Contains('B1Probe')) -and (-not $prtext.Contains((U16 'PROBE_'))))
    Check 'S29 the probe DLL keeps the product file name and the product telemetry classes (TsScoringLegacyTelemetryExtension, LegacyTelemetrySession)' ((Split-Path $pd1 -Leaf) -ceq 'TSScoringPlugin.AtsExLegacy.Telemetry.dll' -and $ptext.Contains('TsScoringLegacyTelemetryExtension') -and $ptext.Contains('LegacyTelemetrySession'))
    Check 'S30 the probe DLL does not reference the Current / Handshake control plane (no BveEx, no Handshake type)' ((-not $ptext.Contains('Handshake')) -and (-not $ptext.Contains((U16 'Handshake'))) -and (-not $ptext.Contains('BveEx.PluginHost')))
    $cp = @('Bridge\src\HandshakeControlPlane.cs', 'Caller\src\HandshakeSession.cs', 'Caller\src\TsScoringCallerInputDevice.cs')
    $cpHits = @(); foreach ($c in $cp) { $cc = CodeOf (ReadText (Join-Path $Root $c)); foreach ($m in [regex]::Matches($cc, 'BveHacker|TimeManager|SetTime\(|InitializeTimeAndLocation|\.Initialize\(|LocationManager|ClassWrappers|BveTypes|AtsEx\.PluginHost')) { $cpHits += ($c + ':' + $m.Value) } }
    Check 'S31 the M1a HandshakeControlPlane (one shared source, linked into both adapters), the Caller session and the Caller input device name no BVE API (no BveHacker, TimeManager, SetTime, Initialize*, LocationManager, BveTypes, AtsEx)' (($cpHits.Count -eq 0) -and ((CodeOf (ReadText (Join-Path $Root 'Bridge\src\HandshakeControlPlane.cs'))).Length -gt 500))
    $pcn = @([regex]::Matches($pc, 'Compile Include="\.\.\\\.\.\\Telemetry\\Legacy\\src\\([A-Za-z]+\.cs)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object)
    $dcn = @([regex]::Matches($dc, 'Compile Include="src\\([A-Za-z]+\.cs)"') | ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -notin @('AssemblyInfo.cs', 'LegacyTelemetryExtension.cs') } | Sort-Object)
    Check 'S23b the probe project compiles exactly the product sources (src\*.cs) except the Extension and AssemblyInfo, plus the shared contract: the telemetry behaviour is the product behaviour' ((($pcn -join ',') -ceq ($dcn -join ',')) -and ($pcn.Count -ge 7) -and ($pc -match 'Shared\\TelemetryContract\.cs'))

    # the tap: a pass-through of every datagram, recording only the telemetry line
    $tapDir = Join-Path $testDir 'tap'; New-Item -ItemType Directory -Force $tapDir | Out-Null
    $tapProbe = Join-Path $tapDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'; Copy-Item $pd1 $tapProbe
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
namespace TapTests
{
    public sealed class Cap : TSScoringPlugin.Telemetry.ITelemetrySink
    {
        public List<string> Sent = new List<string>();
        public bool Closed;
        public void Send(string text) { Sent.Add(text); }
        public void Close() { Closed = true; }
    }
    public static class TapDriver
    {
        public static string[] Run(string[] texts)
        {
            Cap cap = new Cap();
            TSScoringPlugin.Telemetry.B1Probe.B1TapSink tap = new TSScoringPlugin.Telemetry.B1Probe.B1TapSink(cap);
            foreach (string t in texts) { tap.Send(t); }
            tap.Close();
            return new string[] { string.Join("\n", cap.Sent.ToArray()), tap.LastLine ?? "<null>", tap.LineSeq.ToString(), cap.Closed ? "closed" : "open" };
        }
    }
}
"@ -ReferencedAssemblies @($tapProbe) -OutputAssembly (Join-Path $tapDir 'TsScoringLegacyTelemetryTests.dll') -OutputType Library
    [void][Reflection.Assembly]::LoadFrom($tapProbe)
    [void][Reflection.Assembly]::LoadFrom((Join-Path $tapDir 'TsScoringLegacyTelemetryTests.dll'))
    $in = [string[]]@('STALIST:a=1', 'META:x', 'SCENARIO_ID:5,AVAIL:1:speed+time,SPEED:1,TIME:2,LOCATION:3', 'STATUS:LOADED:PAUSED', 'SCENARIO_ID:5,AVAIL:1:speed+time,SPEED:1,TIME:9,LOCATION:4')
    $tr = [TapTests.TapDriver]::Run($in)
    Check 'T01 the tap passes every datagram to the real sink unchanged and in order, records only the SCENARIO_ID telemetry line (last line, count), and closes the real sink' (($tr[0] -ceq ($in -join "`n")) -and ($tr[1] -ceq $in[4]) -and ($tr[2] -ceq '2') -and ($tr[3] -ceq 'closed'))
    $tr2 = [TapTests.TapDriver]::Run([string[]]@('STATUS:LOADED:PAUSED'))
    Check 'T02 a tap that saw no telemetry line has no last line and a count of 0' (($tr2[1] -ceq '<null>') -and ($tr2[2] -ceq '0'))
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# mutations (the behaviour suite on a mutated core must fail)
# ---------------------------------------------------------------------------------------------------------------------------------------------
function ReplaceOnce([string]$t, [string]$old, [string]$new) {
    $n = 0; $i = 0
    while (($i = $t.IndexOf($old, $i, [StringComparison]::Ordinal)) -ge 0) { $n++; $i += $old.Length }
    if ($n -ne 1) { throw ('mutation anchor found ' + $n + ' times: ' + $old.Substring(0, [math]::Min(60, $old.Length))) }
    return $t.Replace($old, $new)
}
if ((-not $BehaviorOnly) -and (-not $SkipMutations)) {
    Write-Host '==== M: mutations of the core (each must be caught by at least one check) ===='
    $orig = ReadText $corePath
    $setCall = 'RunCall(a, "set-time", "PROBE_SET_TIME", delegate { host.SetTime(r.TimeMs); });'
    $mutations = @(
        @{ Name = 'M01 SetTime before Initialize (order reversed)'; Apply = { param($t)
            $t = ReplaceOnce $t ("`n                " + $setCall + "`n            }") "`n            }"
            return (ReplaceOnce $t "                if (r.Operation == B1Op.InitStation)`n                {`n                    if (!RunCall(a, `"initialize`"" ("                " + $setCall + "`n                if (r.Operation == B1Op.InitStation)`n                {`n                    if (!RunCall(a, `"initialize`"")) } },
        @{ Name = 'M02 duplicate RequestId not detected'; Apply = { param($t) return (ReplaceOnce $t 'if (consumed.Contains(r.RequestId) || SafeLedgerContains(r.RequestId))' 'if (cfg == null)') } },
        @{ Name = 'M03 a consumed RequestId is not remembered (no set, no ledger)'; Apply = { param($t)
            $t = ReplaceOnce $t "            consumed.Add(r.RequestId);`n            status.Executed++;" "            status.Executed++;"
            return (ReplaceOnce $t 'try { ledgerOk = io.LedgerAppend(r.RequestId); } catch { ledgerOk = false; }' 'ledgerOk = true;') } },
        @{ Name = 'M04 the Dispose guard before a host call is removed'; Apply = { param($t) return (ReplaceOnce $t "            if (disposing)`n            {`n                Emit(`"PROBE_DISPOSE_REJECTED`", a, `"reason=`" + B1Reason.DisposeStarted + `" where=`" + where);`n                return false;`n            }`n" '') } },
        @{ Name = 'M05 BeginTick ignores that Dispose began'; Apply = { param($t)
            $t = ReplaceOnce $t "                if (disposing)`n                {`n                    if (!disposeAfterTickLogged)" "                if (cfg == null)`n                {`n                    if (!disposeAfterTickLogged)"
            return (ReplaceOnce $t "                Monitor.Enter(execGate);`n                taken = true;`n                if (disposing)`n                {`n                    return;`n                }`n`n                tickSeq++;" "                Monitor.Enter(execGate);`n                taken = true;`n                tickSeq++;") } },
        @{ Name = 'M06 an API call outside the Tick (a SetTime inside OnDispose)'; Apply = { param($t) return (ReplaceOnce $t "            disposing = true;       // FIRST: from here on no host call is started`n" "            disposing = true;       // FIRST: from here on no host call is started`n            host.SetTime(0);`n") } },
        @{ Name = 'M07 the location tolerance is ignored'; Apply = { param($t)
            $t = ReplaceOnce $t 'a.LocOk = after.Location.HasValue && Math.Abs(after.Location.Value - a.ExpectLoc) <= cfg.LocationToleranceM;' 'a.LocOk = after.Location.HasValue;'
            return (ReplaceOnce $t 'bool hostLocOk = s != null && s.Location.HasValue && Math.Abs(s.Location.Value - a.ExpectLoc) <= cfg.LocationToleranceM;' 'bool hostLocOk = s != null && s.Location.HasValue;') } },
        @{ Name = 'M08 SetTime-only request also calls Initialize'; Apply = { param($t) return (ReplaceOnce $t ("                " + $setCall) ("                if (r.Operation == B1Op.SetTime) { RunCall(a, `"initialize`", `"PROBE_INITIALIZE`", delegate { host.InitializeStation(0); }); }`n                " + $setCall)) } },
        @{ Name = 'M09 the station index is not range checked'; Apply = { param($t) return (ReplaceOnce $t 'if (!before.StationCount.HasValue || r.StationIndex >= before.StationCount.Value)' 'if (cfg == null)') } },
        @{ Name = 'M10 the ledger is written AFTER the call, not before (write-ahead removed)'; Apply = { param($t)
            $t = ReplaceOnce $t 'try { ledgerOk = io.LedgerAppend(r.RequestId); } catch { ledgerOk = false; }' 'ledgerOk = true;'
            return (ReplaceOnce $t "            a.State = Phase.Observing;`n            B1Snapshot after" "            a.State = Phase.Observing;`n            io.LedgerAppend(r.RequestId);`n            B1Snapshot after") } },
        @{ Name = 'M11 a re-entered Tick is not refused'; Apply = { param($t) return (ReplaceOnce $t "                if (inCall)`n                {`n                    status.ReentrantTicks++;" "                if (cfg == null)`n                {`n                    status.ReentrantTicks++;") } },
        @{ Name = 'M12 Dispose does not set the flag (it stays false)'; Apply = { param($t) return (ReplaceOnce $t "            disposing = true;       // FIRST: from here on no host call is started`n" "            disposing = false;`n") } },
        @{ Name = 'M13 a request created before the process started is accepted'; Apply = { param($t) return (ReplaceOnce $t 'if (r.CreatedUtc < io.ProcessStartUtc.AddSeconds(-cfg.ProcessStartSkewSeconds))' 'if (cfg == null)') } },
        @{ Name = 'M14 a generation change while pending is ignored'; Apply = { param($t) return (ReplaceOnce $t "            if (a.AcceptGeneration != generation && a.AcceptGeneration != 0)`n            {`n                FinishRejected(a, B1Reason.GenerationChanged);" "            if (cfg == null)`n            {`n                FinishRejected(a, B1Reason.GenerationChanged);") } },
        @{ Name = 'M15 the completion candidate is always MET'; Apply = { param($t) return (ReplaceOnce $t 'bool candidate = a.TimeOk && a.LocOk && hostTimeOk && hostLocOk && lineSent && lineTimeOk && lineLocOk && groupsKept && noLifecycle && noReentry && noException && speedOk;' 'bool candidate = true;') } },
        @{ Name = 'M16 the unchanged-speed expectation of SetTime is dropped'; Apply = { param($t) return (ReplaceOnce $t 'return a.Before.SpeedMps.HasValue && Math.Abs(now.SpeedMps.Value - a.Before.SpeedMps.Value) <= 1e-6;' 'return true;') } },
        @{ Name = 'M17 an unreadable time is not refused'; Apply = { param($t) return (ReplaceOnce $t 'if (before == null || !before.TimeMs.HasValue || !before.Location.HasValue)' 'if (before == null)') } },
        @{ Name = 'M18 an exception in Initialize does not stop the sequence (SetTime still runs)'; Apply = { param($t) return (ReplaceOnce $t "                a.CallFailed = true;`n                status.Exceptions++;" "                a.CallFailed = true;`n                status.Exceptions++;`n                if (step == `"initialize`") { try { host.SetTime(0); } catch { } }") } },
        @{ Name = 'M19 every lost AVAIL token is treated as expected (a lost door group is not reported)'; Apply = { param($t) return (ReplaceOnce $t 'if (!(discDelta > 0 && before[i] == ExpectedLossToken))' 'if (cfg == null)') } },
        @{ Name = 'M20 calcg is expected even in a Tick without a discontinuity'; Apply = { param($t) return (ReplaceOnce $t 'if (!(discDelta > 0 && before[i] == ExpectedLossToken))' 'if (!(before[i] == ExpectedLossToken))') } },
        @{ Name = 'M21 time may stand still from the second Tick after the call on'; Apply = { param($t) return (ReplaceOnce $t 'else if (s.TimeMs.Value <= prevT.Value)' 'else if (s.TimeMs.Value < prevT.Value)') } },
        @{ Name = 'M22 time may go backwards in the Tick right after the call'; Apply = { param($t) return (ReplaceOnce $t 'if (s.TimeMs.Value < prevT.Value) { timeAdvances = false; }' 'if (cfg == null) { timeAdvances = false; }') } },
        @{ Name = 'M23 two samples of the same Tick are accepted as the stability window'; Apply = { param($t) return (ReplaceOnce $t 'locNotBack && noLifecycle && distinctTicks && !a.CallFailed' 'locNotBack && noLifecycle && !a.CallFailed') } }
    )
    $mutDir = Join-Path $testDir 'mut'
    New-Item -ItemType Directory -Force $mutDir | Out-Null
    foreach ($m in $mutations) {
        $mname = $m.Name
        $slug = ($mname.Substring(0, 3))
        try { $mt = & $m.Apply $orig } catch { Check ($mname + ' - mutation could not be applied: ' + $_.Exception.Message) $false; continue }
        $mp = Join-Path $mutDir ($slug + '.cs')
        [IO.File]::WriteAllText($mp, $mt, (New-Object Text.UTF8Encoding($false)))
        $outFile = Join-Path $mutDir ($slug + '.out.txt')
        $p = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'), '-Root', ('"' + $Root + '"'), '-CoreOverride', ('"' + $mp + '"'), '-BehaviorOnly', '-WorkDir', ('"' + (Join-Path $mutDir ($slug + '-work')) + '"')) -RedirectStandardOutput $outFile -NoNewWindow -Wait -PassThru
        $lines = @(Get-Content $outFile -ErrorAction SilentlyContinue)
        $failed = @($lines | Where-Object { $_ -like 'FAIL *' } | ForEach-Object { ($_ -split ' ')[1] })
        if ($p.ExitCode -eq 3) { Check ($mname + ' - the mutant did not compile (invalid mutation)') $false }
        else { Check ($mname + ' -> detected by ' + $(if ($failed.Count -gt 0) { ($failed | Select-Object -First 6) -join ',' } else { 'NOTHING' })) ($p.ExitCode -eq 1 -and $failed.Count -gt 0) }
    }
}

if ($WorkDir -eq '') {
    Remove-Item $testDir -Recurse -Force -ErrorAction SilentlyContinue
    # the compiled test assemblies are loaded in THIS process and stay locked until it ends: the rest is removed by a detached helper a few seconds later
    if (Test-Path -LiteralPath $testDir) { Start-Process -FilePath $env:ComSpec -ArgumentList ('/c ping 127.0.0.1 -n 6 >nul & rmdir /s /q "' + $testDir + '"') -WindowStyle Hidden }
}
$pass = @($results | Where-Object { $_.Ok }).Count
$fail = @($results | Where-Object { -not $_.Ok }).Count
Write-Host ''
Write-Host ("RESULT: {0} PASS / {1} FAIL" -f $pass, $fail)
if ($fail -gt 0) { exit 1 }
exit 0
