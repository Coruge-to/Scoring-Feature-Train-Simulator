# PHASE LI1 - offline tests of the AtsEX LEGACY input telemetry: the handle group (REV POW BRK HTYPE ALLTXT) and the brake pressures (BCP, BPP) that the sender now writes in the
# format of the CURRENT sender, announced in AVAIL (handle / bcp / bpp), rebuilt from the host every Tick, dropped per scenario generation.
# No BVE, no AtsEX runtime, no BveEX, no hooks. The real built DLL (0.2.0.0) is loaded from a copy and driven through FAKES of the Legacy API (tests\TelemetryTestFixture.cs, compiled here).
# The generic display is compared with an independent statement of it (tests\legacy_input_reference.py); the lines the DLL writes are read by the REAL Python reader (offscreen Overlay)
# when UDP 54321 is free. Nothing is written outside logs\li1-tests. This script is ASCII-only on purpose (the Japanese words are built from code points).
param([string]$Root = (Split-Path $PSScriptRoot -Parent), [string]$PythonExe = '')

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$testDir = Join-Path $Root 'logs\li1-tests'
if (Test-Path $testDir) { Remove-Item $testDir -Recurse -Force }
New-Item -ItemType Directory -Force $testDir | Out-Null

$results = New-Object System.Collections.Generic.List[object]
$script:skips = 0
function Check([string]$name, [bool]$ok) { $results.Add([pscustomobject]@{ Name = $name; Ok = $ok }); ("{0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name) }
function Skip([string]$name) { $script:skips++; ('SKIP (not counted as a pass) ' + $name) }
function J([string[]]$parts) { return ($parts -join '|') }

$dllCopy = Join-Path $testDir 'TSScoringPlugin.AtsExLegacy.Telemetry.dll'
Copy-Item $dllPath $dllCopy
$fixtureDll = Join-Path $testDir 'TsScoringLegacyTelemetryTests.dll'
Add-Type -TypeDefinition ([IO.File]::ReadAllText($fixtureSrc)) -ReferencedAssemblies @($dllCopy) -OutputAssembly $fixtureDll -OutputType Library
Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class Li1Resolver
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
[Li1Resolver]::Install(@($testDir, $legacyHost))
$telAsm = [Reflection.Assembly]::LoadFrom($dllCopy)
$fixAsm = [Reflection.Assembly]::LoadFrom($fixtureDll)

function FindPython {
    if ($PythonExe -and (Test-Path $PythonExe)) { return (Resolve-Path $PythonExe).Path }
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c -and $c.Source -and ($c.Source -notmatch 'WindowsApps')) { return $c.Source }
    foreach ($cand in 'C:\Python314\python.exe', 'C:\Python313\python.exe', 'C:\Python312\python.exe') { if (Test-Path $cand) { return $cand } }
    return $null
}
[string]$py = FindPython

# the Japanese words of the generic display, from code points
function U([int[]]$cp) { return (-join ($cp | ForEach-Object { [string][char]$_ })) }
$W_BACK = U @(0x5F8C); $W_REVOFF = U @(0x5207); $W_FWD = U @(0x524D)
$W_HOLD = U @(0x6291, 0x901F); $W_RUN = U @(0x904B, 0x8EE2); $W_LAP = U @(0x91CD, 0x306A, 0x308A); $W_SVC = U @(0x5E38, 0x7528); $W_EMG = U @(0x975E, 0x5E38)

function NewH([bool]$withInput) { return (New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList $withInput) }
function NewIn { return (NewH $true) }
function NewInNoDiag { return (New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList @($true, $false)) }
function Ev($h, [string]$name) { return ,@($h.Diag.Named($name)) }
function Part([string]$line, [string]$key) { $m = [regex]::Match($line, '(^|,)' + [regex]::Escape($key) + ':([^,]*)'); if ($m.Success) { return $m.Groups[2].Value } else { return $null } }
function Has([string]$line, [string]$key) { return [regex]::IsMatch($line, '(^|,)' + [regex]::Escape($key) + ':') }
function Toks([string]$line) { $m = [regex]::Match($line, 'AVAIL:1:([^,]*)'); if ($m.Success -and $m.Groups[1].Value) { return @($m.Groups[1].Value -split '\+') } else { return @() } }
function HasTok([string]$line, [string]$t) { return (@(Toks $line) -contains $t) }
function Last($h) { return $h.Sink.LastLine() }
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
$nan = [double]::NaN; $inf = [double]::PositiveInfinity; $ninf = [double]::NegativeInfinity
$HKEYS = @('REV', 'POW', 'BRK', 'HTYPE', 'ALLTXT')
function NoHandleKeys([string]$line) { foreach ($k in $HKEYS) { if (Has $line $k) { return $false } }; return $true }

function Setup($h, [int]$htype, [int]$brake, $rev, $pow, $brk, $powN, $brkN, $ebN) {
    $h.Input.HandleTypeValue = $htype; $h.Input.BrakeKindValue = $brake
    $h.Input.CabName = $(if ($htype -eq 1) { 'OneLeverCab' } else { 'TwoLeverCab' })
    $h.Input.Rev = $rev; $h.Input.Pow = $pow; $h.Input.Brk = $brk; $h.Input.PowN = $powN; $h.Input.BrkN = $brkN; $h.Input.EbN = $ebN
    $h.Api.BrakeKind = $brake
}

# ---------------------------------------------------------------------------------------------------------------------------------------------
# A - the generic display contract: the C# contract against the independent reference table
# ---------------------------------------------------------------------------------------------------------------------------------------------
$casesFile = Join-Path $testDir 'cases.json'
$refPy = Join-Path $repo 'tests\legacy_input_reference.py'
$cases = @()
if ($py -and (Test-Path $refPy)) {
    & $py -I $refPy cases $casesFile
    $parsed = ConvertFrom-Json ([IO.File]::ReadAllText($casesFile, [Text.Encoding]::UTF8))
    $cases = New-Object System.Collections.Generic.List[object]
    foreach ($x in $parsed) { $cases.Add($x) }          # (Windows PowerShell 5.1 hands a JSON array back as ONE object)
}
$hi = $fixAsm.GetType('TsScoringLegacyTelemetryTests.HandleInfo')
$build = $hi.GetMethod('Build')
$table = @{}
$mismatch = 0; $firstBad = ''
foreach ($c in $cases) {
    $in = @($c.PSObject.Properties['in'].Value)
    $args10 = @($in[0], $in[1], $in[2], $in[3], $in[4], $in[5], $in[6], $in[7], $in[8], $in[9])
    $got = $build.Invoke($null, $args10)
    $want = @($c.out)
    $key = ($in -join ',')
    $table[$key] = $want
    if ((J $got) -cne (J $want)) { $mismatch++; if (-not $firstBad) { $firstBad = ($key + ' got=' + (J $got) + ' want=' + (J $want)) } }
}
Check ('A01 the C# handle contract equals the independent reference for all ' + $cases.Count + ' cases (' + $mismatch + ' differ) ' + $firstBad) (($cases.Count -gt 800) -and ($mismatch -eq 0))
$reasons = @($cases | Where-Object { $_.out[0] -eq 'drop' } | ForEach-Object { $_.out[1] } | Sort-Object -Unique)
Check 'A02 every reason word is exercised (16 fixed reason words since the LI2 final: one-lever-cl, holding-cl and holding-unconfirmed are gone because all 24 cab / brake / holding speed combinations are built; holdn-missing, hold-range and pow-brk-both are new)' ($reasons.Count -eq 16)
Check 'A03 the keys are written in the order of the Current line: REV POW BRK HTYPE ALLTXT (HTYPE before ALLTXT: the reader sizes the brake texts by the handle type)' ((J ($hi.GetMethod('Keys').Invoke($null, @()))) -ceq 'REV|POW|BRK|HTYPE|ALLTXT')
$one = $build.Invoke($null, @(1, 1, 1, 0, 0, 4, 5, 6, $false, 0))
Check 'A04 literal: one-lever Ecb 4/5/6 at rest is REV forward, POW N, BRK N with emergency notch 6, HTYPE 1, and the generic ALLTXT' ((J $one) -ceq (J @('ok', ($W_FWD + ':1'), 'N:0', 'N:0:6', '1', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':N_P1_P2_P3_P4:N_B1_B2_B3_B4_B5_EB:'))))
$cl = $build.Invoke($null, @(2, 3, 0, 0, 1, 5, 2, 3, $false, 0))
Check 'A05 literal: two-lever Cl brake position 1 is the lap word with emergency notch 3, position 0 is the run word; ALLTXT lists run / lap / service / emergency' ((J $cl) -ceq (J @('ok', ($W_REVOFF + ':0'), 'P0:0', ($W_LAP + ':1:3'), '2', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':P0_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_LAP + '_' + $W_SVC + '_' + $W_EMG + ':'))))
$hb = $build.Invoke($null, @(2, 1, 1, 0, 1, 5, 8, 9, $true, 0))
Check 'A06 literal (LI2): a holding speed BRAKE on a two-lever Ecb car is built - brake position 1 is the holding speed brake word (not H1); one-lever + holding speed brake and Cl + holding speed brake are built too (LI2 final: N / hold word / B1.. / EB and run / hold word / service / emergency), an unreadable hold flag is hold-missing' (((J $hb) -ceq (J @('ok', ($W_FWD + ':1'), 'P0:0', ($W_HOLD + ':1:9'), '2', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':P0_P1_P2_P3_P4_P5:B0_' + $W_HOLD + '_B1_B2_B3_B4_B5_B6_B7_EB:')))) -and ((J ($build.Invoke($null, @(1, 1, 1, 0, 1, 5, 8, 9, $true, 0)))) -ceq (J @('ok', ($W_FWD + ':1'), 'N:0', ($W_HOLD + ':1:9'), '1', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':N_P1_P2_P3_P4_P5:N_' + $W_HOLD + '_B1_B2_B3_B4_B5_B6_B7_EB:')))) -and ((J ($build.Invoke($null, @(2, 3, 1, 0, 1, 5, 2, 3, $true, 0)))) -ceq (J @('ok', ($W_FWD + ':1'), 'P0:0', ($W_HOLD + ':1:3'), '2', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':P0_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_HOLD + '_' + $W_SVC + '_' + $W_EMG + ':')))) -and ((J ($build.Invoke($null, @(2, 1, 1, 0, 0, 4, 7, 8, $null, 0)))) -ceq 'drop|hold-missing'))
Check 'A07 the emergency boundary is the host value: 2-lever Ecb 7/8 is EB at 8, never derived (8 -> EB:8:8), and a position beyond it is not a position (9 -> brk-range); an emergency notch that is not brake notches + 1 builds nothing (eb-layout)' (((J ($build.Invoke($null, @(2, 1, 1, 0, 8, 4, 7, 8, $false, 0)))) -match 'EB:8:8') -and ((J ($build.Invoke($null, @(2, 1, 1, 0, 9, 4, 7, 8, $false, 0)))) -ceq 'drop|brk-range') -and ((J ($build.Invoke($null, @(2, 1, 1, 0, 0, 4, 7, 9, $false, 0)))) -ceq 'drop|eb-layout'))
$revTexts = New-Object System.Collections.Generic.List[string]; foreach ($rv in @(-1, 0, 1)) { $revTexts.Add([string](($build.Invoke($null, @(2, 1, $rv, 0, 0, 4, 7, 8, $false, 0)))[1])) }
Check 'A08 the reverser words are the same for every cab type: -1 back, 0 off (not the old neutral word), 1 forward' ((J $revTexts) -ceq (J @(($W_BACK + ':-1'), ($W_REVOFF + ':0'), ($W_FWD + ':1'))))
$oneN = $build.Invoke($null, @(1, 1, 1, 0, 0, 4, 5, 6, $false, 0)); $oneP = $build.Invoke($null, @(1, 1, 1, 2, 0, 4, 5, 6, $false, 0)); $oneB = $build.Invoke($null, @(1, 1, 1, 0, 3, 4, 5, 6, $false, 0)); $oneE = $build.Invoke($null, @(1, 1, 1, 0, 6, 4, 5, 6, $false, 0))
Check 'A09 one-lever Ecb keeps N at the neutral: neutral N / P2 / B3 / EB, ALLTXT power N_P1..P4 and brake N_B1..B5_EB (the neutral N is not B0)' (($oneN[2] -ceq 'N:0') -and ($oneN[3] -ceq 'N:0:6') -and ($oneP[2] -ceq 'P2:2') -and ($oneB[3] -ceq 'B3:3:6') -and ($oneE[3] -ceq 'EB:6:6') -and ($oneN[5] -cmatch ':N_P1_P2_P3_P4:N_B1_B2_B3_B4_B5_EB:$'))
$twoE = $build.Invoke($null, @(2, 1, 1, 0, 0, 4, 7, 8, $false, 0)); $twoS = $build.Invoke($null, @(2, 2, 1, 0, 0, 4, 9, 10, $false, 0)); $twoS3 = $build.Invoke($null, @(2, 2, 1, 2, 3, 4, 9, 10, $false, 0)); $twoSE = $build.Invoke($null, @(2, 2, 1, 0, 10, 4, 9, 10, $false, 0))
Check 'A10 two-lever Ecb and Smee show B0 at brake position 0 (not N): BRK B0:0:e, ALLTXT brake B0_B1..B(e-1)_EB, power P0..Pn; B3 and EB as before' (($twoE[3] -ceq 'B0:0:8') -and ($twoS[3] -ceq 'B0:0:10') -and ($twoS3[2] -ceq 'P2:2') -and ($twoS3[3] -ceq 'B3:3:10') -and ($twoSE[3] -ceq 'EB:10:10') -and ($twoE[5] -cmatch ':P0_P1_P2_P3_P4:B0_B1_B2_B3_B4_B5_B6_B7_EB:$') -and ($twoS[5] -cmatch ':P0_P1_P2_P3_P4:B0_B1_B2_B3_B4_B5_B6_B7_B8_B9_EB:$'))
$clT = New-Object System.Collections.Generic.List[string]; foreach ($bk in @(0, 1, 2, 3)) { $clT.Add([string](($build.Invoke($null, @(2, 3, 1, 0, $bk, 5, 2, 3, $false, 0)))[3])) }
Check 'A11 two-lever Cl: brake 0 run, 1 lap, 2 service, 3 emergency, 4 is beyond the emergency notch (brk-range) (the reverser off word and the Cl run word are different words)' (((J $clT) -ceq (J @(($W_RUN + ':0:3'), ($W_LAP + ':1:3'), ($W_SVC + ':2:3'), ($W_EMG + ':3:3')))) -and ((J ($build.Invoke($null, @(2, 3, 1, 0, 4, 5, 2, 3, $false, 0)))) -ceq 'drop|brk-range') -and ($W_RUN -cne $W_REVOFF))
Check 'A12 (LI2 final) the one-lever Cl cab is built (the RUN word at rest, like the two-lever Cl brake position 0 - it used to be the off word); one-lever Cl + holding speed brake and two-lever Cl + holding speed brake are built too (position 1 is the holding speed word)' (((J ($build.Invoke($null, @(1, 3, 1, 0, 0, 5, 2, 3, $false, 0)))) -ceq (J @('ok', ($W_FWD + ':1'), ($W_RUN + ':0'), ($W_RUN + ':0:3'), '1', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':' + $W_RUN + '_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_LAP + '_' + $W_SVC + '_' + $W_EMG + ':')))) -and ((J ($build.Invoke($null, @(1, 3, 1, 0, 1, 5, 2, 3, $true, 0)))) -ceq (J @('ok', ($W_FWD + ':1'), ($W_RUN + ':0'), ($W_HOLD + ':1:3'), '1', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':' + $W_RUN + '_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_HOLD + '_' + $W_SVC + '_' + $W_EMG + ':')))) -and ((J ($build.Invoke($null, @(2, 3, 1, 0, 0, 5, 2, 3, $true, 0)))) -ceq (J @('ok', ($W_FWD + ':1'), 'P0:0', ($W_RUN + ':0:3'), '2', ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':P0_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_HOLD + '_' + $W_SVC + '_' + $W_EMG + ':')))))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# B - the pressure contract
# ---------------------------------------------------------------------------------------------------------------------------------------------
$pi = $fixAsm.GetType('TsScoringLegacyTelemetryTests.PressureInfo')
function Pr([double[]]$a) { return $pi.GetMethod('Try').Invoke($null, @(, $a)) }
Check 'B01 an array of exactly one finite element: its element 0, in kPa, one decimal (440 -> 440.0, 0 -> 0.0, 123.4 -> 123.4)' (((Pr ([double[]]@(440.0))) -ceq 'ok:440.0') -and ((Pr ([double[]]@(0.0))) -ceq 'ok:0.0') -and ((Pr ([double[]]@(123.4))) -ceq 'ok:123.4'))
Check 'B02 the unit is never scaled: 0.44 stays 0.4 (not x1000), 440000 stays 440000.0 (not /1000)' (((Pr ([double[]]@(0.44))) -ceq 'ok:0.4') -and ((Pr ([double[]]@(440000.0))) -ceq 'ok:440000.0'))
Check 'B03 null array -> array-null; empty -> array-empty' (((Pr $null) -ceq 'drop:array-null:-1') -and ((Pr (New-Object 'double[]' 0)) -ceq 'drop:array-empty:0'))
Check 'B04 two or more elements are NOT reduced to element 0 (array-multi, with the real length): 2 and 8 elements' (((Pr ([double[]]@(1.0, 2.0))) -ceq 'drop:array-multi:2') -and ((Pr ([double[]]@(1, 2, 3, 4, 5, 6, 7, 8))) -ceq 'drop:array-multi:8'))
Check 'B05 NaN / +Infinity / -Infinity in the single element -> nonfinite' (((Pr ([double[]]@($nan))) -ceq 'drop:nonfinite:1') -and ((Pr ([double[]]@($inf))) -ceq 'drop:nonfinite:1') -and ((Pr ([double[]]@($ninf))) -ceq 'drop:nonfinite:1'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# C - the session: the line the sender writes
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; $h.Run(3, 16)
$line = Last $h
$allToks = 'bcp+bpp+brake_cab+brake_type+calcg+door+grad+handle+loc+maplimit+meta+prates+siglimit+siglimit_ahead+speed+station+time'
Check 'C01 default fake (one-lever Ecb 5/8/9 at rest, store 0 / 490): the line carries REV POW BRK HTYPE ALLTXT BCP BPP with the generic texts' (($line -match ('(^|,)REV:' + $W_FWD + ':1,')) -and ((Part $line 'POW') -ceq 'N:0') -and ((Part $line 'BRK') -ceq 'N:0:9') -and ((Part $line 'HTYPE') -ceq '1') -and ((Part $line 'ALLTXT') -ceq ($W_BACK + '_' + $W_REVOFF + '_' + $W_FWD + ':N_P1_P2_P3_P4_P5:N_B1_B2_B3_B4_B5_B6_B7_B8_EB:')) -and ((Part $line 'BCP') -ceq '0.0') -and ((Part $line 'BPP') -ceq '490.0'))
Check 'C02 AVAIL names exactly the 14 tokens of Phase L3 plus handle, bcp, bpp (17), sorted; the first line (no acceleration reference yet) lacks calcg only' (((Part (Last $h) 'AVAIL') -ceq ('1:' + $allToks)) -and ((@(Toks ($h.Sink.Lines()[0]))).Count -eq 16) -and (-not (HasTok ($h.Sink.Lines()[0]) 'calcg')))
# every supported combination, every position: the line carries what the table says
$combos = @(@(1, 1, 4, 5, 6), @(1, 2, 4, 9, 10), @(1, 3, 5, 2, 3), @(2, 1, 4, 7, 8), @(2, 1, 6, 8, 9), @(2, 2, 4, 9, 10), @(2, 3, 5, 2, 3))
$bad = 0; $n = 0; $firstBad2 = ''
foreach ($cb in $combos) {
    $hh = NewIn
    foreach ($rev in -1, 0, 1) {
        foreach ($pow in @(0, 1, $cb[2])) {
            foreach ($brk in 0..($cb[4] + 1)) {
                Setup $hh $cb[0] $cb[1] $rev $pow $brk $cb[2] $cb[3] $cb[4]
                $hh.Run(1, 16)
                $l = Last $hh
                $want = $table[(@($cb[0], $cb[1], $rev, $pow, $brk, $cb[2], $cb[3], $cb[4], 'False', 0) -join ',')]
                $got = @((Part $l 'REV'), (Part $l 'POW'), (Part $l 'BRK'), (Part $l 'HTYPE'), (Part $l 'ALLTXT'))
                $n++
                if ($want[0] -ceq 'drop') { if (-not ((NoHandleKeys $l) -and (-not (HasTok $l 'handle')))) { $bad++; if (-not $firstBad2) { $firstBad2 = ((@($cb) -join '/') + ' r' + $rev + ' p' + $pow + ' b' + $brk + ' should be dropped (' + $want[1] + ')') } } }
                elseif ((J $got) -cne (J @($want[1..5]))) { $bad++; if (-not $firstBad2) { $firstBad2 = ((@($cb) -join '/') + ' r' + $rev + ' p' + $pow + ' b' + $brk + ' got=' + (J $got)) } }
            }
        }
    }
}
Check ('C03 the line the SESSION writes equals the reference for ' + $n + ' (layout x reverser x power x brake) states of the seven real layouts: one-lever Ecb / Smee / Cl, two-lever Ecb x2 / Smee / Cl (' + $bad + ' differ) ' + $firstBad2) (($n -gt 400) -and ($bad -eq 0))
$h = NewIn; Setup $h 1 1 1 0 0 5 8 9; $h.Input.Hold = $true; $h.Run(5, 16)
$ls = @($h.Sink.Lines()); $l = $ls[$ls.Count - 1]
Check 'C04 (LI2 final) a one-lever cab with the holding speed brake is built: N at rest, the holding speed word at brake position 1, HTYPE 1, handle announced; the pressures go out as before' ((@($ls | Where-Object { HasTok $_ 'handle' }).Count -eq $ls.Count) -and ((Part $l 'POW') -ceq 'N:0') -and ((Part $l 'BRK') -ceq 'N:0:9') -and ((Part $l 'HTYPE') -ceq '1') -and (HasTok $l 'bcp') -and (HasTok $l 'bpp') -and ((Part $l 'BTYPE') -ceq 'Ecb'))
$h = NewIn; Setup $h 2 1 1 0 1 5 8 9; $h.Input.Hold = $true; $h.Run(3, 16)
$hc = NewIn; Setup $hc 2 3 1 0 0 5 2 3; $hc.Input.Hold = $true; $hc.Run(3, 16); $clBuilt = (HasTok (Last $hc) 'handle') -and ((Part (Last $hc) 'BRK') -ceq ($W_RUN + ':0:3')) -and ((Part (Last $hc) 'HTYPE') -ceq '2')
Check 'C05 (LI2) a two-lever vehicle with the holding speed brake: the handle group IS written (brake position 1 is the holding speed brake word) and AVAIL announces handle; a Cl car with the holding speed brake is written too (run word at brake 0; LI2 final)' ((HasTok (Last $h) 'handle') -and ((Part (Last $h) 'BRK') -ceq ($W_HOLD + ':1:9')) -and ((Part (Last $h) 'POW') -ceq 'P0:0') -and ((Part (Last $h) 'HTYPE') -ceq '2') -and ((Part (Last $h) 'ALLTXT') -cmatch ('P0_P1_P2_P3_P4_P5:B0_' + $W_HOLD + '_B1_B2_B3_B4_B5_B6_B7_EB:$')) -and $clBuilt)
$h = NewIn; $h.Input.Hold = $null; $h.Run(3, 16)
Check 'C06 an unreadable hold flag: no handle group' ((NoHandleKeys (Last $h)) -and (-not (HasTok (Last $h) 'handle')))
foreach ($tc in @(@('HandleType unknown', { param($x) $x.Input.HandleTypeValue = 0 }), @('BrakeKind unknown', { param($x) $x.Input.BrakeKindValue = 0 }), @('Reverser unreadable', { param($x) $x.Input.Rev = $null }),
                  @('EmergencyBrakeNotch unreadable', { param($x) $x.Input.EbN = $null }), @('layout not brake+1', { param($x) $x.Input.EbN = 12 }), @('power above the layout', { param($x) $x.Input.Pow = 9 }),
                  @('negative brake', { param($x) $x.Input.Brk = -1 }), @('reverser out of range', { param($x) $x.Input.Rev = 5 }))) {
    $hx = NewIn; & $tc[1] $hx; $hx.Run(3, 16)
    Check ('C07 ' + $tc[0] + ': the group is not built - no handle key, no handle token (the rest of the line is unaffected: ' + $hx.LinesSent + ' lines sent, 0 skipped)') ((NoHandleKeys (Last $hx)) -and (-not (HasTok (Last $hx) 'handle')) -and ($hx.LinesSent -eq 3) -and ($hx.LinesSkipped -eq 0) -and (HasTok (Last $hx) 'speed'))
}
# pressures
$matrix = @(
    @('Bc null', $null, 'bcp', $false), @('Bc empty', (New-Object 'double[]' 0), 'bcp', $false), @('Bc one', [double[]]@(150.5), 'bcp', $true), @('Bc two', [double[]]@(1, 2), 'bcp', $false),
    @('Bc eight', [double[]]@(1, 2, 3, 4, 5, 6, 7, 8), 'bcp', $false), @('Bc NaN', [double[]]@($nan), 'bcp', $false), @('Bc Infinity', [double[]]@($inf), 'bcp', $false)
)
foreach ($m in $matrix) {
    $hx = NewIn; $hx.Input.StoreBc = $m[1]; $hx.Input.StoreBp = [double[]]@(490.0); $hx.Run(4, 16)
    $lx = Last $hx
    $okBc = ((Has $lx 'BCP') -eq $m[3]) -and ((HasTok $lx 'bcp') -eq $m[3])
    if ($m[3]) { $okBc = $okBc -and ((Part $lx 'BCP') -ceq '150.5') }
    Check ('C08 StateStore BcPressure ' + $m[0] + ': BCP is ' + $(if ($m[3]) { 'written (150.5, unchanged)' } else { 'not written and not announced' }) + '; BPP is independent and still written') ($okBc -and (Has $lx 'BPP') -and (HasTok $lx 'bpp') -and ((Part $lx 'BPP') -ceq '490.0'))
}
$hx = NewIn; $hx.Input.StoreBc = [double[]]@(0.0); $hx.Input.StoreBp = $null; $hx.Run(4, 16)
Check 'C09 only the BpPressure array missing: BCP goes out, BPP and its token do not' ((Has (Last $hx) 'BCP') -and (-not (Has (Last $hx) 'BPP')) -and (-not (HasTok (Last $hx) 'bpp')) -and (HasTok (Last $hx) 'bcp'))
$hx = NewIn; $hx.Input.StoreBc = [double[]]@(1, 2); $hx.Input.StoreBp = [double[]]@(3, 4); $hx.Run(4, 16)
Check 'C10 both arrays with two elements: neither pressure, neither token, and element 0 is not used (no 1 / 3 anywhere as a pressure)' ((-not (Has (Last $hx) 'BCP')) -and (-not (Has (Last $hx) 'BPP')) -and (-not (HasTok (Last $hx) 'bcp')) -and (-not (HasTok (Last $hx) 'bpp')) -and (HasTok (Last $hx) 'handle'))
$hx = NewIn; $hx.Input.StoreFail = $true; $hx.Run(4, 16)
Check 'C11 the store cannot be read at all: no pressure, the handle is unaffected' ((-not (Has (Last $hx) 'BCP')) -and (-not (Has (Last $hx) 'BPP')) -and (HasTok (Last $hx) 'handle'))
$h = NewIn; $h.Input.StoreBc = [double[]]@(440.0); $h.Input.StoreBp = [double[]]@(0.0); $h.Run(3, 16)
Check 'C12 Smee at emergency (BCP 440 kPa, BPP 0 kPa) is written as 440.0 and 0.0 (kPa, unchanged)' (((Part (Last $h) 'BCP') -ceq '440.0') -and ((Part (Last $h) 'BPP') -ceq '0.0'))
$l = Last $h
Check 'C13 what is NOT sent yet stays out: BPP carries the pressure only (no bp_initial second field), no TRAINLEN / MAPLIMITS / CLEARDIST / DOORTIME / JUMP, no token for them' ((-not ((Part $l 'BPP') -match ':')) -and (-not (Has $l 'TRAINLEN')) -and (-not (Has $l 'MAPLIMITS')) -and (-not (Has $l 'CLEARDIST')) -and (-not (Has $l 'DOORTIME')) -and (-not (Has $l 'JUMP')) -and (@('trainlen', 'doortime', 'maplimit_ahead', 'jump') | Where-Object { HasTok $l $_ }).Count -eq 0)

# every Tick is rebuilt from the host: nothing of an earlier Tick is re-used
$h = NewIn; $h.Run(2, 16)
$h.Input.Brk = 3; $h.Run(1, 16); $b3 = Part (Last $h) 'BRK'
$h.Input.Brk = 9; $h.Run(1, 16); $b9 = Part (Last $h) 'BRK'
$h.Input.HandlesFail = $true; $h.Run(2, 16); $lf = Last $h
$h.Input.HandlesFail = $false; $h.Input.Brk = 0; $h.Run(1, 16)
Check 'C14 the handle follows the host Tick by Tick (B3, then EB); while the host cannot give it, the group AND its token are gone (no stale REV); when it is back it is the current value' (($b3 -ceq 'B3:3:9') -and ($b9 -ceq 'EB:9:9') -and (NoHandleKeys $lf) -and (-not (HasTok $lf 'handle')) -and ((Part (Last $h) 'BRK') -ceq 'N:0:9') -and (HasTok (Last $h) 'handle'))
$h = NewIn; $h.Run(2, 16); $h.Input.StoreBc = $null; $h.Input.StoreBp = $null; $h.Run(2, 16); $lg = Last $h
$h.Input.StoreBc = [double[]]@(7.0); $h.Input.StoreBp = [double[]]@(8.0); $h.Run(1, 16)
Check 'C15 the pressures follow the host the same way (gone while unreadable, current when back)' ((-not (Has $lg 'BCP')) -and (-not (HasTok $lg 'bcp')) -and ((Part (Last $h) 'BCP') -ceq '7.0') -and ((Part (Last $h) 'BPP') -ceq '8.0'))

# scenario generations
$h = NewIn
Setup $h 2 2 1 4 10 4 9 10; $h.Input.StoreBc = [double[]]@(440.0); $h.Input.StoreBp = [double[]]@(0.0); $h.Api.BrakeKind = 2
$h.Run(5, 16); $idA = $h.ScenarioId; $allA = Part (Last $h) 'ALLTXT'
$h.Closed(); $h.Created()
$h.Api.Scenario = New-Object object; $h.Seed = $h.Seed + 12345
Setup $h 1 1 0 0 0 4 5 6; $h.Input.HandlesFail = $true; $h.Input.StoreBc = $null; $h.Input.StoreBp = [double[]]@(1, 2)
$h.Run(4, 16); $firstB = $h.Sink.Lines()[$h.Sink.Lines().Count - 4]
Check 'C16 a new scenario generation shows NOTHING of the previous one: with the handle unreadable and no usable pressure its first line has no handle / pressure key or token (not the old Smee EB, not the old 440 / 0)' (($h.ScenarioId -ne $idA) -and (NoHandleKeys $firstB) -and (-not (HasTok $firstB 'handle')) -and (-not (Has $firstB 'BCP')) -and (-not (Has $firstB 'BPP')) -and (@($h.Sink.Lines() | Where-Object { $_ -match ('SCENARIO_ID:' + $h.ScenarioId + ',') -and ($_ -match [regex]::Escape($allA)) }).Count -eq 0))
$h.Input.HandlesFail = $false; $h.Run(3, 16); $lb = Last $h
Check 'C17 ... and the new vehicle''s own layout replaces the old one when it becomes readable (one-lever Ecb: its ALLTXT, not the Smee one)' (((Part $lb 'HTYPE') -ceq '1') -and ((Part $lb 'ALLTXT') -cne $allA) -and ((Part $lb 'ALLTXT') -match 'N_P1_P2_P3_P4:N_B1_B2_B3_B4_B5_EB:$'))
$h2 = NewIn; $h2.Run(4, 16); $h2.Opened($true); $h2.Created(); $h2.Api.Scenario = New-Object object; $h2.Seed = $h2.Seed + 777; $h2.Input.Brk = 4; $h2.Run(3, 16)
Check 'C18 a reload (Opened reload, Created, a new scenario object) is a new generation: new SCENARIO_ID, the handle rebuilt from the host (B4)' (($h2.Epochs -eq 2) -and ((Part (Last $h2) 'BRK') -ceq 'B4:4:9'))

# one read of the input surface per Tick (the observation and the telemetry share it)
$h = NewIn; $h.Run(100, 16)
Check 'C19 the host is asked for the handles and for the store at most ONCE per Tick although the observation (diagnostic) and the telemetry both use them (100 Ticks -> 100 + 100)' (($h.Input.CallCount('TryHandles') -eq 100) -and ($h.Input.CallCount('TryStorePressure') -eq 100))
$h = NewInNoDiag; $h.Run(100, 16)
Check 'C20 without a diagnostic (no observation wired) the handle group and the pressures are still written, from one read per Tick' (($h.Input.CallCount('TryHandles') -eq 100) -and ($h.Input.CallCount('TryStorePressure') -eq 100) -and (HasTok (Last $h) 'handle') -and (HasTok (Last $h) 'bcp') -and ($h.Input.CallCount('TryNativePressure') -eq 0))
$h = NewH $false; $h.Run(20, 16)
Check 'C21 a session built without the input surface (the Phase L3 sender) writes no handle / pressure key and the 14 tokens of Phase L3' ((NoHandleKeys (Last $h)) -and (-not (Has (Last $h) 'BCP')) -and (-not (Has (Last $h) 'BPP')) -and ((Part (Last $h) 'AVAIL') -ceq '1:brake_cab+brake_type+calcg+door+grad+loc+maplimit+meta+prates+siglimit+siglimit_ahead+speed+station+time'))

# pause / soft OFF / scenario end / re-selection
$h = NewIn; $h.Run(6, 16); $calls = $h.Input.TotalCalls(); $idP = $h.ScenarioId; $nP = $h.Sink.Lines().Count
$h.Now += 5000; $null = $h.Heartbeat(); $h.Now += 5000
Check 'C22 Pause (the host stops calling Tick): nothing is sent, the input surface is not called, the heartbeat says PAUSED' (($h.Heartbeat() -eq 'STATUS:LOADED:PAUSED') -and ($h.Input.TotalCalls() -eq $calls) -and ($h.Sink.Lines().Count -eq $nP))
$h.Input.Brk = 2; $h.Run(2, 16)
Check 'C23 after the Pause the SAME generation goes on with the current handle (B2) - soft OFF / ON of the HUD is the application''s business and changes nothing here' (($h.ScenarioId -eq $idP) -and ((Part (Last $h) 'BRK') -ceq 'B2:2:9') -and ($h.Epochs -eq 1))
$sendsBefore = $h.Sink.Lines().Count
$h.Closed(); $h.Api.Created = $false; $h.Run(5, 16)
Check 'C24 the scenario ends (selection screen waiting): no datagram, no input read, the heartbeat has nothing to report' (($h.Sink.Lines().Count -eq $sendsBefore) -and ($null -eq $h.Heartbeat()) -and (-not $h.Active))
$h.Api.Created = $true; $h.Api.Scenario = New-Object object; $h.Created(); $h.Seed = $h.Seed + 31; $h.Input.Brk = 5; $h.Run(3, 16)
Check 'C25 the same scenario selected again: a new generation (new SCENARIO_ID), the handle read fresh (B5), the same sender object, no second sink' (($h.Epochs -eq 2) -and ((Part (Last $h) 'BRK') -ceq 'B5:5:9') -and (HasTok (Last $h) 'bcp'))
$h.Dispose(); $nBefore = $h.Sink.Sent.Count; $cBefore = $h.Input.TotalCalls(); $h.Run(5, 16)
Check 'C26 Dispose ends the generation and closes the sink; Ticks after it send nothing and read nothing' ($h.IsDisposed -and $h.Sink.Closed -and ($h.Sink.SendsAfterClose -eq 0) -and ($h.Sink.Sent.Count -eq $nBefore) -and ($h.Input.TotalCalls() -eq $cBefore))

# robustness
$h = NewIn; $h.Input.HandlesThrow = $true; $h.Input.StoreThrow = $true; $h.Input.SpecThrow = $true; $h.Input.NativeThrow = $true; $h.Run(60, 16)
Check 'C27 every input read throwing: a line for every Tick (60), none skipped, no handle / pressure, the core of the line intact' (($h.LinesSent -eq 60) -and ($h.LinesSkipped -eq 0) -and (NoHandleKeys (Last $h)) -and (-not (Has (Last $h) 'BCP')) -and (HasTok (Last $h) 'speed') -and (HasTok (Last $h) 'loc'))
$h = NewIn; $h.Run(10, 16)
$tickThread = [Threading.Thread]::CurrentThread.ManagedThreadId
$inCalls = $h.Input.TotalCalls(); $hb = $h.HeartbeatOnOtherThread(2000)
Check 'C28 every input read came from the Tick thread only; 2000 heartbeat calls from a second thread read nothing' (($hb -ne $tickThread) -and ($h.Input.TotalCalls() -eq $inCalls) -and ($h.Input.Threads.Count -eq 1) -and ($h.Input.Threads.Contains($tickThread)))
$h = NewIn; $h.Run(20, 16); $f = Last $h
Check 'C29 the line stays one small datagram (no newline, < 1200 characters) with the handle group and the pressures' (($f.IndexOf("`n") -lt 0) -and ($f.Length -lt 1200))

# diagnostics: state changes only, capped, one summary
$h = NewIn; $h.Run(1000, 16)
$li1Names = @('TEL_HANDLE_SEND', 'TEL_HANDLE_DROP', 'TEL_PRESSURE_SEND', 'TEL_PRESSURE_DROP', 'TEL_INPUT_PUBLISH')
function Li1Events($hh) { return ,@($hh.Diag.Events | Where-Object { $li1Names -contains $_.Split(' ')[0] }) }
Check 'D01 1000 steady Ticks write exactly 3 LI1 lines (handle sent, bcp sent, bpp sent) - nothing per Tick' ((Li1Events $h).Count -eq 3)
$h.Closed()
$sm = Ev $h 'TEL_INPUT_PUBLISH'
Check 'D02 the generation ends with exactly one summary with the counts' (($sm.Count -eq 1) -and ($sm[0] -match '^TEL_INPUT_PUBLISH gen=\d+ ticks=1000 handleSent=1000 handleDropped=0 bcpSent=1000 bcpDropped=0 bppSent=1000 bppDropped=0 suppressed=0$'))
$h = NewIn; $h.Run(2, 16)
for ($i = 0; $i -lt 300; $i++) { $h.Input.HandlesFail = (($i % 2) -eq 0); $h.Input.StoreBc = $(if (($i % 3) -eq 0) { $null } else { [double[]]@(1.0) }); $h.Run(1, 16) }
$h.Closed()
$flap = Li1Events $h; $smf = Ev $h 'TEL_INPUT_PUBLISH'
$capLines = [int]($fixAsm.GetType('TsScoringLegacyTelemetryTests.InputTelemetryInfo').GetProperty('MaxLines').GetValue($null))
Check ('D03 a flapping handle / pressure writes at most ' + $capLines + ' state lines + the summary per generation (' + $flap.Count + ' written); what the cap swallowed is counted (suppressed>0)') (($flap.Count -le ($capLines + 1)) -and ($smf.Count -eq 1) -and ($smf[0] -match 'suppressed=([1-9]\d*)$'))
$bad = @($flap | Where-Object { $_ -notmatch '^TEL_[A-Z_]+ gen=\d+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)+$' })
Check ('D04 every LI1 line has the fixed shape NAME gen=N key=value ... (letters, digits, _ . - only): no path, no free text, no exception text (' + $flap.Count + ' lines)') ($bad.Count -eq 0)
$h = NewIn; $h.Input.CabName = 'TwoLeverCab'; $h.Input.HandleTypeValue = 2; $h.Input.BrakeKindValue = 2; $h.Input.PowN = 4; $h.Input.BrkN = 9; $h.Input.EbN = 10; $h.Run(3, 16)
$hs = Ev $h 'TEL_HANDLE_SEND'
Check 'D05 the handle log line states the layout in fixed words and numbers' (($hs.Count -eq 1) -and ($hs[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-smee powN=4 brkN=9 ebN=10'))
$h = NewIn; $h.Input.StoreBc = [double[]]@(1, 2, 3); $h.Run(3, 16)
$pd = Ev $h 'TEL_PRESSURE_DROP'
Check 'D06 a pressure array of 3 elements is logged once as array-multi with its length (the meaning of such an array is not guessed)' (($pd.Count -eq 1) -and ($pd[0] -ceq 'TEL_PRESSURE_DROP gen=0 group=bcp reason=array-multi len=3'))
$h = NewIn; $h.Input.HandleTypeValue = 1; $h.Input.BrakeKindValue = 3; $h.Input.BrkN = 2; $h.Input.EbN = 3; $h.Run(3, 16)
$hd = Ev $h 'TEL_HANDLE_SEND'
$h2d = NewIn; $h2d.Input.HandleTypeValue = 1; $h2d.Input.BrakeKindValue = 3; $h2d.Run(3, 16); $hdd = Ev $h2d 'TEL_HANDLE_DROP'
Check 'D07 (LI2) the one-lever Cl cab is logged once as layout=one-lever-cl (sent); a Cl layout that is not 2 / 3 is logged once as reason=cl-layout; the LI0 observation line (combo=unexpected) is still written' (($hd.Count -eq 1) -and ($hd[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=one-lever-cl powN=5 brkN=2 ebN=3') -and ($hdd.Count -eq 1) -and ($hdd[0] -ceq 'TEL_HANDLE_DROP gen=0 reason=cl-layout') -and ((Ev $h 'TEL_HANDLE_FIRST')[0] -match 'combo=unexpected'))
$h = NewIn; $h.Run(5, 16)
Check 'D08 the LI0 observation is unchanged (CAPABILITY / HANDLE_FIRST / SPEC_FIRST / PRESSURE_FIRST x2 still written once)' (((Ev $h 'TEL_INPUT_CAPABILITY').Count -eq 1) -and ((Ev $h 'TEL_HANDLE_FIRST').Count -eq 1) -and ((Ev $h 'TEL_SPEC_FIRST').Count -eq 1) -and ((Ev $h 'TEL_PRESSURE_FIRST').Count -eq 2))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# E - the lines the DLL writes, read by the REAL Python reader and Overlay (offscreen, real UDP socket) - only when UDP 54321 is free
# ---------------------------------------------------------------------------------------------------------------------------------------------
$ovPy = Join-Path $repo 'tests\telemetry_overlay_check.py'
$xPy = Join-Path $repo 'tests\telemetry_xcheck.py'
$udpBusy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
$qtOk = $false
try { $qtOk = ((& $py -c "import PyQt6.QtWidgets; print('ok')") -eq 'ok') } catch { $qtOk = $false }
function Dump($hh, [string]$name) { $f = Join-Path $testDir $name; [IO.File]::WriteAllText($f, (($hh.Sink.Sent -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false))); return $f }
$h = NewIn; Setup $h 2 2 -1 3 10 4 9 10; $h.Api.BrakeKind = 2; $h.Input.StoreBc = [double[]]@(440.0); $h.Input.StoreBp = [double[]]@(0.0); $h.Run(4, 16)
$dumpX = Dump $h 'x-dump.txt'
if ($py -and (Test-Path $xPy)) {
    $j = (& $py -I $xPy $dumpX | Out-String) | ConvertFrom-Json
    $tel = @($j | Where-Object { $_.kind -eq 'telemetry' })
    Check 'E01 the Python reference reader accepts every line, reads exactly the 17 announced tokens, none unknown / malformed' (($tel.Count -ge 2) -and (@($tel | Where-Object { -not $_.valid }).Count -eq 0) -and ((($tel[1].tokens | Sort-Object) -join '+') -ceq $allToks) -and ($tel[1].unknown -eq 0) -and ($tel[1].bad -eq 0))
    Check 'E02 the keys of the line are inside the contract vocabulary (the Python vocabulary knows REV POW BRK HTYPE ALLTXT BCP BPP)' ((@('REV', 'POW', 'BRK', 'HTYPE', 'ALLTXT', 'BCP', 'BPP') | Where-Object { $tel[1].keys -notcontains $_ }).Count -eq 0)
}
else { Skip 'E01-E02 (python or tests\telemetry_xcheck.py missing)' }
if ($qtOk -and (-not $udpBusy) -and (Test-Path $ovPy)) {
    $expect = @(
        @('one-lever Ecb', @(1, 1, 1, 3, 0, 4, 5, 6)), @('one-lever Smee', @(1, 2, 0, 0, 9, 4, 9, 10)), @('two-lever Ecb', @(2, 1, 1, 2, 4, 6, 8, 9)),
        @('two-lever Smee', @(2, 2, -1, 0, 10, 4, 9, 10)), @('two-lever Cl', @(2, 3, 1, 5, 3, 5, 2, 3)), @('one-lever Cl', @(1, 3, 1, 0, 2, 5, 2, 3))
    )
    foreach ($e in $expect) {
        $v = $e[1]
        $hh = NewIn; Setup $hh $v[0] $v[1] $v[2] $v[3] $v[4] $v[5] $v[6] $v[7]; $hh.Api.BrakeKind = $v[1]; $hh.Input.StoreBc = [double[]]@(321.5); $hh.Input.StoreBp = [double[]]@(12.3); $hh.Run(4, 16)
        $want = $table[(@($v[0], $v[1], $v[2], $v[3], $v[4], $v[5], $v[6], $v[7], 'False', 0) -join ',')]
        $dump = Dump $hh ('o-' + ($e[0] -replace '\W', '') + '.txt')
        $o = (& $py $ovPy $dump | Out-String) | ConvertFrom-Json
        $wantRev = $want[1].Split(':')[0]; $wantPow = $want[2].Split(':')[0]; $wantBrk = $want[3].Split(':')[0]
        $stateOk = ($o.states.handle -eq 'shown') -and ($o.values.bve_rev_text -ceq $wantRev) -and ($o.values.bve_pow_text -ceq $wantPow) -and ($o.values.bve_brk_text -ceq $wantBrk) -and ($o.values.bcPressure -eq 321.5) -and ($o.values.bpPressure -eq 12.3)
        $drawn = @($o.drawn)
        $drawnOk = ($drawn -ccontains $wantRev) -and (($v[0] -eq 1) -or (($drawn -ccontains $wantPow) -and ($drawn -ccontains $wantBrk))) -and (($v[0] -eq 2) -or (($drawn -ccontains $wantPow) -or ($drawn -ccontains $wantBrk)))
        Check ('E03 ' + $e[0] + ': the REAL Overlay holds ' + $wantRev + ' / ' + $wantPow + ' / ' + $wantBrk + ' and 321.5 / 12.3 kPa, the handle row is shown and these texts are drawn') ($stateOk -and $drawnOk -and ($o.stats.tel_invalid -eq 0))
    }
    $hh = NewIn; Setup $hh 1 1 1 0 1 5 8 9; $hh.Input.Hold = $true; $hh.Run(4, 16)
    $o = (& $py $ovPy (Dump $hh 'o-onecl.txt') | Out-String) | ConvertFrom-Json
    Check 'E04 (LI2 final) a one-lever cab with the holding speed brake (brake position 1): the REAL Overlay holds the handle row as shown and draws the holding speed word' (($o.states.handle -eq 'shown') -and ($o.values.bve_brk_text -ceq $W_HOLD) -and (@($o.drawn | Where-Object { $_ -ceq $W_HOLD }).Count -ge 1) -and ($o.values.bcPressure -eq 0))
    $hh = NewIn; Setup $hh 1 3 1 0 0 5 2 3; $hh.Run(4, 16)
    $o = (& $py $ovPy (Dump $hh 'o-onecl.txt') | Out-String) | ConvertFrom-Json
    Check 'E05 (LI2 final) one-lever Cl: the REAL Overlay holds the handle row as shown, the single handle shows the RUN word at rest and the reverser word, bve_pow_text is the run word' (($o.states.handle -eq 'shown') -and ($o.values.bve_pow_text -ceq $W_RUN) -and ($o.values.bve_rev_text -ceq $W_FWD) -and (@($o.drawn | Where-Object { $_ -ceq $W_RUN }).Count -ge 1))
}
else { Skip ('E03-E04 real Overlay chain: not run (PyQt6=' + $qtOk + ', UDP 54321 busy=' + $udpBusy + ')') }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# F - the BVE5 32-bit path: the same DLL loaded by a 32-bit process writes the same bytes
# ---------------------------------------------------------------------------------------------------------------------------------------------
$probe = Join-Path $testDir 'probe.ps1'
$probeText = @'
param([string]$Dll, [string]$Fixture, [string]$Out)
Add-Type -TypeDefinition ([IO.File]::ReadAllText($Fixture)) -ReferencedAssemblies @($Dll) -OutputAssembly (Join-Path (Split-Path $Out) 'TsScoringLegacyTelemetryTests.dll') -OutputType Library
[void][Reflection.Assembly]::LoadFrom($Dll)
[void][Reflection.Assembly]::LoadFrom((Join-Path (Split-Path $Out) 'TsScoringLegacyTelemetryTests.dll'))
$lines = New-Object System.Collections.Generic.List[string]
$combos = @(@(1, 1, 4, 5, 6), @(1, 2, 4, 9, 10), @(2, 1, 6, 8, 9), @(2, 2, 4, 9, 10), @(2, 3, 5, 2, 3), @(1, 3, 5, 2, 3))
foreach ($c in $combos) {
    $h = New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList $true
    $h.Input.HandleTypeValue = $c[0]; $h.Input.BrakeKindValue = $c[1]; $h.Api.BrakeKind = $c[1]
    $h.Input.CabName = $(if ($c[0] -eq 1) { 'OneLeverCab' } else { 'TwoLeverCab' })
    $h.Input.PowN = $c[2]; $h.Input.BrkN = $c[3]; $h.Input.EbN = $c[4]; $h.Input.Rev = 1
    foreach ($b in 0, 1, $c[4]) { $h.Input.Brk = $b; $h.Input.StoreBc = [double[]]@(100.5 + $b); $h.Input.StoreBp = [double[]]@(490.0 - $b); $h.Run(2, 16) }
    foreach ($s in $h.Sink.Sent) { $lines.Add($s) }
}
$bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
$sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-', '')
[IO.File]::WriteAllText($Out, ('ptr=' + [IntPtr]::Size + ' lines=' + $lines.Count + ' sha=' + $sha), (New-Object Text.UTF8Encoding($false)))
'@
[IO.File]::WriteAllText($probe, $probeText, (New-Object Text.UTF8Encoding($false)))
$ps64 = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
if ((Test-Path $ps32) -and (Test-Path $ps64)) {
    $r64 = Join-Path $testDir 'probe64.txt'; $r32 = Join-Path $testDir 'probe32.txt'
    $d64 = Join-Path $testDir 'p64'; $d32 = Join-Path $testDir 'p32'
    New-Item -ItemType Directory -Force $d64, $d32 | Out-Null
    Copy-Item $dllCopy $d64; Copy-Item $dllCopy $d32
    & $ps64 -NoProfile -ExecutionPolicy Bypass -File $probe -Dll (Join-Path $d64 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -Fixture $fixtureSrc -Out (Join-Path $d64 'out.txt') | Out-Null
    & $ps32 -NoProfile -ExecutionPolicy Bypass -File $probe -Dll (Join-Path $d32 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -Fixture $fixtureSrc -Out (Join-Path $d32 'out.txt') | Out-Null
    $t64 = if (Test-Path (Join-Path $d64 'out.txt')) { [IO.File]::ReadAllText((Join-Path $d64 'out.txt')) } else { '' }
    $t32 = if (Test-Path (Join-Path $d32 'out.txt')) { [IO.File]::ReadAllText((Join-Path $d32 'out.txt')) } else { '' }
    Check ('F01 a 32-bit process (BVE5) loads the DLL and writes exactly the same bytes as the 64-bit one for five real layouts (' + $t64 + ' | ' + $t32 + ')') (($t64 -match '^ptr=8 ') -and ($t32 -match '^ptr=4 ') -and (($t64 -replace '^ptr=\d+ ', '') -ceq ($t32 -replace '^ptr=\d+ ', '')) -and ($t64 -match 'lines=\d{2,}'))
}
else { Skip 'F01 (no 32-bit Windows PowerShell here)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# G - sources, version, scope
# ---------------------------------------------------------------------------------------------------------------------------------------------
$srcDir = Join-Path $Root 'Telemetry\Legacy\src'
$hcCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyHandleContract.cs')))
$itCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyInputTelemetry.cs')))
$seCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetrySession.cs')))
$exCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetryExtension.cs')))
Check 'G01 the new files are host independent (no AtsEx / BveTypes name) and use no reflection, hook, DllImport, unsafe, Harmony or private member' ((($hcCode + $itCode) -cnotmatch 'AtsEx|BveTypes|BveEx') -and (($hcCode + $itCode) -notmatch 'BindingFlags|DllImport|\bunsafe\b|Harmony|\.GetField\(|\.GetProperty\(|\.GetMethod\(|\.Invoke\(|Marshal\.'))
Check 'G02 the session names no handle / pressure key as a literal (the keys live in the handle contract only) and never reduces an array itself' (($seCode -notmatch '"(REV|POW|BRK|HTYPE|ALLTXT|BCP|BPP)"') -and ($seCode -notmatch 'StoreBc|StoreBp|\.Bc\b|\.Bp\b'))
Check 'G03 only the Tick thread reaches the input surface: the heartbeat method of the session does not mention the input classes' (([regex]::Match($seCode, 'internal string ComposeHeartbeat\(\)[\s\S]*?\n        \}').Value) -notmatch 'input|Input')
$vi = (Get-Item $dllPath).VersionInfo
Check 'G04 the DLL is 0.3.0.0 (Phase LI2), the Phase SI-0 observation build 0.3.1.0 or the Phase SI-1 build 0.4.0.0 (assembly and file version), product TS Scoring, provider Coruge-to; the description still names Phase L3 and LI1' ((([TsScoringLegacyTelemetryTests.DiagInfo]::Version) -in @('0.3.0.0', '0.3.1.0', '0.4.0.0')) -and ($vi.FileVersion -in @('0.3.0.0', '0.3.1.0', '0.4.0.0')) -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.Comments -match 'Phase L3') -and ($vi.Comments -match 'LI1') -and ($vi.Comments -match 'LI2'))
$csproj = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'))
Check 'G05 the project compiles the two new files and still references only the read-only legacy host assemblies (Private=False)' (($csproj -match 'src\\LegacyHandleContract\.cs') -and ($csproj -match 'src\\LegacyInputTelemetry\.cs') -and (([regex]::Matches($csproj, '<Private>False</Private>')).Count -eq 5))
function RunGit([string[]]$gitArgs) { $out = & git @gitArgs 2>$null; if ($LASTEXITCODE -ne 0) { return '' }; return ($out -join "`n") }
$top = (RunGit @('-C', $Root, 'rev-parse', '--show-toplevel')).Trim() -replace '/', '\'
$frozen = @(
    'TsScoringPlugin/TsScoringPlugin/Class1.cs', 'TsScoringPlugin/TsScoringPlugin/AtsLoggerPlugin.cs', 'TsScoringPlugin/Handshake/Caller', 'TsScoringPlugin/Handshake/Bridge', 'TsScoringPlugin/Handshake/Shared',
    'telemetry_contract.py', 'telemetry_gate.py', 'network.py', 'main.py', 'hud_ui.py', 'scoring_logic.py', 'managed_hud.py', 'managed_mode.py', 'managed_state.py', 'menu_ui.py', 'config.py', 'utils.py',
    'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs', 
    'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs'
)
# (Phase LI1 is committed: the guard compares the LI1 commit with its parent, like G08. Phase SI-A changes the Python files in the working tree on purpose; its own tests pin that.)
$changedFrozen = @((RunGit (@('-C', $top, 'diff', '--name-only', '0010a8b^', '0010a8b', '--') + $frozen)) -split "`n" | Where-Object { $_ })
Check ('G06 the Current contract and everything the brief freezes are byte-identical to HEAD: Current sender Class1.cs, Caller, both Bridges, the Handshake shared protocol, telemetry_contract / telemetry_gate / network / main / hud_ui / scoring_logic / managed_* (' + $changedFrozen.Count + ' changed) ' + ($changedFrozen -join ',')) ($changedFrozen.Count -eq 0)
$tcDiff = RunGit @('-C', $top, 'diff', '-U0', 'HEAD', '--', 'TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs')
$tcPlus = @($tcDiff -split "`n" | Where-Object { $_ -match '^\+[^+]' })
$tcMinus = @($tcDiff -split "`n" | Where-Object { $_ -match '^-[^-]' })
Check 'G07 the shared telemetry contract is byte-identical to HEAD, or differs from it ONLY by the two token constants Phase SI-1 added (trainlen, maplimit_ahead; nothing removed, nothing else added); LI1 added the three token constants handle, bcp, bpp; it defines them' (((-not $tcDiff) -or (($tcMinus.Count -eq 0) -and (@($tcPlus | Where-Object { $_ -notmatch 'TokMapLimitAhead|TokTrainLen' }).Count -eq 0))) -and ([IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Shared\TelemetryContract.cs')) -match 'TokHandle[\s\S]*TokBcp[\s\S]*TokBpp'))
# G08 describes what THIS phase changed: the LI1 work is committed (0010a8b, parent d7f5d8f), so it is pinned to that commit pair in history (the same assertion as while the work was uncommitted, no longer dependent on a LATER phase's working tree).
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', 'd7f5d8f', '0010a8b')) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed | Sort-Object -Unique)
$li1Allowed = @($touched | Where-Object { $_ -match '^TsScoringPlugin/Handshake/(Telemetry/(Legacy/|Shared/TelemetryContract\.cs)|Tests/|Tools/|Docs/Handshake-PhaseLI[12]|Docs/Handshake-PhaseL3-LegacyTelemetry\.md)|^tests/(test_legacy_input_li[12]|legacy_input_reference)\.py$|^tests/legacy_input_matrix24\.json$' })
$outside = @($touched | Where-Object { $_ -notin $li1Allowed })
Check ('G08 scope: only the Legacy telemetry project, the shared contract constants, tests, verifiers, the LI1 document and the one-section note in the L3 document changed (' + $touched.Count + ' files; outside: ' + ($outside -join ',') + ')') ($outside.Count -eq 0)
$newBinary = @($untracked | Where-Object { $_ -match '\.(dll|pdb|log|exe)$' })
Check 'G09 no DLL, PDB, log or executable is added to Git by this phase (generated output stays ignored)' ($newBinary.Count -eq 0)
$priv = @()
foreach ($f in @('Telemetry\Legacy\src\LegacyHandleContract.cs', 'Telemetry\Legacy\src\LegacyInputTelemetry.cs', 'Tests\Test-LegacyInputLI1.ps1')) { $priv += @(Get-Item (Join-Path $Root $f)) }
$priv += @(Get-Item (Join-Path $repo 'tests\test_legacy_input_li1.py'), (Get-Item (Join-Path $repo 'tests\legacy_input_reference.py')))
$privText = ($priv | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"
Check 'G10 no personal path, user name or e-mail address in the new files' (($privText -notmatch '[A-Za-z]:\\Users\\[A-Za-z]') -and ($privText -notmatch ('@' + 'gmail|@' + 'users\.noreply')) -and ($privText -notmatch 'C:\\Users\\'))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# H - TEST HARNESS (separate from the product): the live-chain tests ask "is the user's own TS Scoring main.py running?" about the real path only
# ---------------------------------------------------------------------------------------------------------------------------------------------
. (Join-Path $PSScriptRoot 'MainProcessGuard.ps1')
$mp = 'C:\work\TsRepo\main.py'
$py64 = '"C:\Python314\pythonw.exe"'
function V([string]$cl, [string]$main = $mp) { return (Get-TsMainPyVerdict $cl $main) }
Check 'H01 the real path (quoted, unquoted, other case, forward slashes) is a match' (((V ($py64 + ' "C:\work\TsRepo\main.py" --managed --owner caller --bve-pid 4242')) -eq 'match') -and ((V ('python C:\work\TsRepo\main.py')) -eq 'match') -and ((V ($py64 + ' "c:\WORK\tsrepo\MAIN.PY"')) -eq 'match') -and ((V ($py64 + ' "C:/work/TsRepo/main.py"')) -eq 'match'))
Check 'H02 ANOTHER project''s main.py (a different folder, a sibling folder with a longer name, a longer file name, a deeper folder) is NOT a match' (((V ($py64 + ' "C:\work\OtherApp\main.py" --started-by bve --bve-pid 37216')) -eq 'other') -and ((V ($py64 + ' "C:\work\TsRepo-old\main.py"')) -eq 'other') -and ((V ($py64 + ' "C:\work\TsRepo\main.py.bak"')) -eq 'other') -and ((V ($py64 + ' "C:\work\TsRepo\sub\main.py"')) -eq 'other'))
Check 'H03 a relative main.py cannot be placed (its working folder is unknown): the safe side (ambiguous = treated as running); no main.py at all, an empty line and $null are not' (((V 'python main.py') -eq 'ambiguous') -and ((V 'pythonw ".\main.py" --x') -eq 'ambiguous') -and ((V 'python -m pytest tests') -eq 'other') -and ((V '') -eq 'other') -and ((V $null) -eq 'other'))
Check 'H04 a path with spaces is matched as one token' (((V '"C:\Python314\python.exe" "D:\My Apps\TsRepo\main.py"' 'D:\My Apps\TsRepo\main.py') -eq 'match') -and ((V '"C:\Python314\python.exe" "D:\My Apps\Other\main.py"' 'D:\My Apps\TsRepo\main.py') -eq 'other'))
Check 'H05 a mixed command line with an unrelated main.py first and the real one later is still a match' ((V ($py64 + ' "C:\work\OtherApp\main.py" "C:\work\TsRepo\main.py"')) -eq 'match')
$guardSrc = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'MainProcessGuard.ps1'))
$liveScripts = 'Test-AppProcessE3.ps1', 'Test-HudLinkE4.ps1', 'Test-TelemetryIntegrationL3.ps1'
$usesGuard = @($liveScripts | Where-Object { $s = [IO.File]::ReadAllText((Join-Path $PSScriptRoot $_)); ($s -match 'MainProcessGuard\.ps1') -and ($s -match 'Get-TsScoringMainRunning \$mainPy') -and ($s -notmatch "-match 'main\\\.py'") })
Check 'H06 the three live-chain tests (E3, E4, L3 integration) all ask the guard about $mainPy and none keeps the old "any main.py" test' ($usesGuard.Count -eq 3)
Check 'H07 the guard is read only (no Stop-Process, no process start) and ASCII only' (($guardSrc -notmatch 'Stop-Process|Start-Process|taskkill|Remove-Item') -and (($guardSrc.ToCharArray() | Where-Object { [int]$_ -gt 127 }).Count -eq 0))
$realRunning = Get-TsScoringMainRunning (Join-Path $repo 'main.py')
Check ('H08 on this machine right now: the answer for the real <repo>\main.py is ' + $realRunning + ' (informational: True only when the user''s own TS Scoring runs from this repository or a relative main.py is up)') ($realRunning -is [bool])

# ---------------------------------------------------------------------------------------------------------------------------------------------
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"LEGACY-INPUT-LI1 PASS=$pass FAIL=$fail SKIP=$($script:skips)"
if ($fail -gt 0) { exit 1 } else { exit 0 }
