# PHASE LI2 - offline tests of the AtsEX LEGACY holding speed handles and the one-lever Cl handle: the handle group (REV POW BRK HTYPE ALLTXT) of the telemetry line now
#   * shows the holding speed BRAKE (HasHoldingSpeedBrake: brake position 1 of a two-lever Ecb / Smee cab) as its own word, never as H1,
#   * shows the INDEPENDENT holding speed notches (HoldingSpeedNotchCount = -n of a two-lever Ecb / Smee cab - the host reports the count NEGATED: POW = -1..-n) as H1..Hn on the power side,
#   * sends a one-lever cab with a HoldingSpeedNotchCount only as an ordinary one-lever handle (the H notches are not operable there),
#   * shows the one-lever Cl handle (P1..Pn, off, lap, service, emergency).
# The two holding speed features are different and are kept apart everywhere in this file.
# No BVE, no AtsEX runtime, no BveEx, no hooks. The real built DLL (0.3.0.0) is loaded from a copy and driven through FAKES of the Legacy API (tests\TelemetryTestFixture.cs, compiled here).
# The C# contract is compared with literal anchors from the phase brief and the real-machine logs, and (A, in Test-LegacyInputLI1.ps1) with the independent reference table.
# Nothing is written outside logs\li2-tests. This script is ASCII-only on purpose (the Japanese words are built from code points).
param([string]$Root = (Split-Path $PSScriptRoot -Parent), [string]$PythonExe = '')

$repo = Split-Path (Split-Path $Root -Parent) -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
$dllPath = Join-Path $Root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll'
$fixtureSrc = Join-Path $Root 'Tests\TelemetryTestFixture.cs'
$testDir = Join-Path $Root 'logs\li2-tests'
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
public static class Li2Resolver
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
[Li2Resolver]::Install(@($testDir, $legacyHost))
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

# the Japanese words, from code points
function U([int[]]$cp) { return (-join ($cp | ForEach-Object { [string][char]$_ })) }
$W_BACK = U @(0x5F8C); $W_OFF = U @(0x5207); $W_FWD = U @(0x524D)
$W_HOLD = U @(0x6291, 0x901F); $W_RUN = U @(0x904B, 0x8EE2); $W_LAP = U @(0x91CD, 0x306A, 0x308A); $W_SVC = U @(0x5E38, 0x7528); $W_EMG = U @(0x975E, 0x5E38)
$REVS = $W_BACK + '_' + $W_OFF + '_' + $W_FWD

function NewIn { return (New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList $true) }
function Ev($h, [string]$name) { return ,@($h.Diag.Named($name)) }
function Part([string]$line, [string]$key) { $m = [regex]::Match($line, '(^|,)' + [regex]::Escape($key) + ':([^,]*)'); if ($m.Success) { return $m.Groups[2].Value } else { return $null } }
function Has([string]$line, [string]$key) { return [regex]::IsMatch($line, '(^|,)' + [regex]::Escape($key) + ':') }
function Toks([string]$line) { $m = [regex]::Match($line, 'AVAIL:1:([^,]*)'); if ($m.Success -and $m.Groups[1].Value) { return @($m.Groups[1].Value -split '\+') } else { return @() } }
function HasTok([string]$line, [string]$t) { return (@(Toks $line) -contains $t) }
function Last($h) { return $h.Sink.LastLine() }
function Code([string]$text) { return [regex]::Replace([regex]::Replace($text, '/\*[\s\S]*?\*/', ''), '//[^\r\n]*', '') }
$HKEYS = @('REV', 'POW', 'BRK', 'HTYPE', 'ALLTXT')
function NoHandleKeys([string]$line) { foreach ($k in $HKEYS) { if (Has $line $k) { return $false } }; return $true }

# one fake vehicle: handle type (1 one lever, 2 two lever), brake kind (1 Ecb, 2 Smee, 3 Cl), layout, holding speed brake flag, HoldingSpeedNotchCount
function Setup($h, [int]$htype, [int]$brake, [int]$powN, [int]$brkN, [int]$ebN, $hold, $holdN) {
    $h.Input.HandleTypeValue = $htype; $h.Input.BrakeKindValue = $brake
    $h.Input.CabName = $(if ($htype -eq 1) { 'OneLeverCab' } else { 'TwoLeverCab' })
    $h.Input.Rev = 1; $h.Input.Pow = 0; $h.Input.Brk = 0; $h.Input.PowN = $powN; $h.Input.BrkN = $brkN; $h.Input.EbN = $ebN
    $h.Input.Hold = $hold; $h.Input.HoldN = $holdN
    $h.Api.BrakeKind = $brake
}
# the handle part of the line after one Tick at the given positions
function Pos($h, $pow, $brk, $rev = 1) { $h.Input.Pow = $pow; $h.Input.Brk = $brk; $h.Input.Rev = $rev; $h.Run(1, 16); return (Last $h) }
function HParts([string]$l) { return @((Part $l 'REV'), (Part $l 'POW'), (Part $l 'BRK'), (Part $l 'HTYPE'), (Part $l 'ALLTXT')) }

$hi = $fixAsm.GetType('TsScoringLegacyTelemetryTests.HandleInfo')
$build = $hi.GetMethod('Build')
function B([int]$ht, [int]$bk, [Nullable[int]]$rev, [Nullable[int]]$pow, [Nullable[int]]$brk, [Nullable[int]]$pn, [Nullable[int]]$bn, [Nullable[int]]$en, [Nullable[bool]]$hold, [Nullable[int]]$hn) { return $build.Invoke($null, @($ht, $bk, $rev, $pow, $brk, $pn, $bn, $en, $hold, $hn)) }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# A - the C# contract: literal anchors
# ---------------------------------------------------------------------------------------------------------------------------------------------
# A. the holding speed BRAKE: cab=TwoLeverCab brake=Ecb powN=5 brkN=8 ebN=9 hold=1 (real machine)
$hbWords = New-Object System.Collections.Generic.List[string]; foreach ($k in 0..9) { $hbWords.Add([string](((B 2 1 1 0 $k 5 8 9 $true 0)[3]).Split(':')[0])) }
Check 'A01 holding speed brake (hold=1, 5/8/9): brake position 0 B0, 1 the holding speed word, 2 B1, 3 B2 ... 8 B7, 9 EB; 10 is beyond the emergency notch (brk-range)' (((J $hbWords) -ceq (J @('B0', $W_HOLD, 'B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'EB'))) -and ((J (B 2 1 1 0 10 5 8 9 $true 0)) -ceq 'drop|brk-range'))
$hb1 = B 2 1 1 0 1 5 8 9 $true 0
Check 'A02 holding speed brake literal: REV / POW P0 / BRK <hold word>:1:9 / HTYPE 2 / ALLTXT P0..P5 and B0, hold word, B1..B7, EB with no holding speed texts (it is the BRAKE feature)' ((J $hb1) -ceq (J @('ok', ($W_FWD + ':1'), 'P0:0', ($W_HOLD + ':1:9'), '2', ($REVS + ':P0_P1_P2_P3_P4_P5:B0_' + $W_HOLD + '_B1_B2_B3_B4_B5_B6_B7_EB:'))))
$neverH = $true; foreach ($k in 0..12) { if (((B 2 1 1 0 $k 5 8 9 $true 0)[3]) -cmatch '^H') { $neverH = $false } }
Check 'A03 the holding speed brake is never H1 (no brake text starts with H for any brake position)' ($neverH -and ($W_HOLD -cne 'H1'))
Check 'A04 the holding speed BRAKE side does not depend on HoldingSpeedNotchCount: unreadable, 0, -1, -5, +5 give the same ok / REV / POW / BRK / HTYPE at POW 0 (the count only adds the H texts of the power side)' (((J ((B 2 1 1 0 1 5 8 9 $true $null)[0..4])) -ceq (J $hb1[0..4])) -and ((J ((B 2 1 1 0 1 5 8 9 $true -1)[0..4])) -ceq (J $hb1[0..4])) -and ((J ((B 2 1 1 0 1 5 8 9 $true -5)[0..4])) -ceq (J $hb1[0..4])) -and ((J ((B 2 1 1 0 1 5 8 9 $true 5)[0..4])) -ceq (J $hb1[0..4])))
Check 'A05 the formerly refused holding speed brake combinations are built (LI2 final: Cl + hold on one and two lever, one lever Ecb / Smee + hold); an unreadable flag is hold-missing; the hold brake with POW -1 is pow-range without notches and H1 with a host count of -5' (((B 2 3 1 0 1 5 2 3 $true 0)[3] -ceq ($W_HOLD + ':1:3')) -and ((B 1 3 1 0 1 5 2 3 $true 0)[3] -ceq ($W_HOLD + ':1:3')) -and ((B 1 1 1 0 1 5 8 9 $true 0)[3] -ceq ($W_HOLD + ':1:9')) -and ((B 1 2 1 0 1 4 9 10 $true 0)[3] -ceq ($W_HOLD + ':1:10')) -and ((J (B 2 1 1 0 0 5 8 9 $null 0)) -ceq 'drop|hold-missing') -and ((J (B 2 1 1 -1 0 5 8 9 $true 0)) -ceq 'drop|pow-range') -and ((B 2 1 1 -1 0 5 8 9 $true -5)[2] -ceq 'H1:-1'))
# B. the INDEPENDENT holding speed notches: cab=TwoLeverCab brake=Smee powN=5 brkN=8 ebN=9 hold=0, HoldingSpeedNotchCount=5 (real machine)
$hw = New-Object System.Collections.Generic.List[string]; foreach ($p in -5..5) { $hw.Add([string]((B 2 2 1 $p 0 5 8 9 $false -5)[2])) }
Check 'B01 independent holding speed (count 5): POW -5..-1 are H5:-5 .. H1:-1, 0 P0:0, 1..5 P1:1 .. P5:5' ((J $hw) -ceq (J @('H5:-5', 'H4:-4', 'H3:-3', 'H2:-2', 'H1:-1', 'P0:0', 'P1:1', 'P2:2', 'P3:3', 'P4:4', 'P5:5')))
Check 'B02 below the formal count is unavailable (pow-range): -6 and -100 with count 5, -3 with count 2; the formal count is the limit, not PowerNotchCount' (((J (B 2 2 1 -6 0 5 8 9 $false -5)) -ceq 'drop|pow-range') -and ((J (B 2 2 1 -100 0 5 8 9 $false -5)) -ceq 'drop|pow-range') -and ((J (B 2 2 1 -3 0 5 8 9 $false -2)) -ceq 'drop|pow-range') -and ((B 2 2 1 -2 0 5 8 9 $false -2)[2] -ceq 'H2:-2') -and ((J (B 2 2 1 6 0 5 8 9 $false -5)) -ceq 'drop|pow-range'))
$bk = New-Object System.Collections.Generic.List[string]; foreach ($k in 0, 1, 4, 8, 9) { $bk.Add([string]((B 2 2 1 -2 $k 5 8 9 $false -5)[3])) }
Check 'B03 the brake column stays B0..Bn / EB while a holding speed notch is held (a kept previous brake value is shown as it is): B0:0:9 B1:1:9 B4:4:9 B8:8:9 EB:9:9; 10 is beyond the emergency notch' ((J $bk) -ceq (J @('B0:0:9', 'B1:1:9', 'B4:4:9', 'B8:8:9', 'EB:9:9'))) -and ((J (B 2 2 1 -2 10 5 8 9 $false -5)) -ceq 'drop|brk-range')
$notHold = $true; foreach ($k in 0..10) { if (((B 2 2 1 -1 $k 5 8 9 $false -5)[3]) -cmatch $W_HOLD) { $notHold = $false } }
Check 'B04 an independent holding speed notch is never shown as the holding speed BRAKE word in the brake column' $notHold
Check 'B05 literal ALLTXT: P0..P5, B0..B8 and EB, and the holding speed texts H1..H5 in the fourth part; HTYPE 2; the same texts at every handle position (a static layout)' (((B 2 2 1 -1 0 5 8 9 $false -5)[5] -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:H1_H2_H3_H4_H5')) -and ((B 2 2 1 3 0 5 8 9 $false -5)[5] -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:H1_H2_H3_H4_H5')) -and ((B 2 2 1 -1 0 5 8 9 $false -5)[4] -ceq '2'))
Check 'B06 the formal count (the host value, NEGATED: -5 = five notches) is never replaced by the power notch count: unreadable -> holdn-missing only for POW below zero (POW 0 and above are built, without holding speed texts); count 0 -> no H1 (pow-range) and no holding speed texts; above 0 or below -99 -> hold-range for POW below zero' (((J (B 2 2 1 -1 0 5 8 9 $false $null)) -ceq 'drop|holdn-missing') -and ((B 2 2 1 0 0 5 8 9 $false $null)[2] -ceq 'P0:0') -and ((B 2 2 1 0 0 5 8 9 $false $null)[5] -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:')) -and ((J (B 2 2 1 -1 0 5 8 9 $false 0)) -ceq 'drop|pow-range') -and ((B 2 2 1 0 0 5 8 9 $false 0)[5] -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:')) -and ((J (B 2 2 1 -1 0 5 8 9 $false 1)) -ceq 'drop|hold-range') -and ((J (B 2 2 1 -1 0 5 8 9 $false 100)) -ceq 'drop|hold-range') -and ((J (B 2 2 1 -1 0 5 8 9 $false -100)) -ceq 'drop|hold-range') -and ((B 2 2 1 -99 0 5 8 9 $false -99)[2] -ceq 'H99:-99'))
Check 'B07 Ecb is the same as Smee (count 3, powN 6): -3 is H3:-3, -4 is unavailable' (((B 2 1 1 -3 0 6 8 9 $false -3)[2] -ceq 'H3:-3') -and ((J (B 2 1 1 -4 0 6 8 9 $false -3)) -ceq 'drop|pow-range'))
Check 'B08 a two-lever Cl car uses the independent notches too (LI2 final): POW -1 is H1 with the host count -5, unavailable below -5 and without notches; ALLTXT carries the Cl brake words and H1..H5 only when there are notches' (((B 2 3 1 -1 0 5 2 3 $false -5)[2] -ceq 'H1:-1') -and ((J (B 2 3 1 -6 0 5 2 3 $false -5)) -ceq 'drop|pow-range') -and ((J (B 2 3 1 -1 0 5 2 3 $false 0)) -ceq 'drop|pow-range') -and ((B 2 3 1 0 0 5 2 3 $false -5)[5] -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_LAP + '_' + $W_SVC + '_' + $W_EMG + ':H1_H2_H3_H4_H5')) -and ((B 2 3 1 0 0 5 2 3 $false 0)[5] -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_LAP + '_' + $W_SVC + '_' + $W_EMG + ':')))
# C. one-lever + HoldingSpeedNotchCount > 0: an ordinary one-lever handle (artificial car, BVE ignores the H notches there)
$same = $true; foreach ($hn in $null, -1, -5, -99, 5) { foreach ($p in 0..6) { foreach ($k in 0..10) { if ((J (B 1 2 1 $p $k 5 8 9 $false $hn)) -cne (J (B 1 2 1 $p $k 5 8 9 $false 0))) { $same = $false } } } }
Check 'C01 one lever with HoldingSpeedNotchCount (unreadable, -1, -5, -99, +5) gives exactly the group of the same car without the setting for every power / brake position - the setting alone is never a reason to refuse' $same
$o1 = B 1 2 1 0 0 5 8 9 $false -5
Check 'C02 literal one-lever Smee 5/8/9 count 5: P3, N, B5, EB as an ordinary one-lever handle; ALLTXT has no holding speed texts; HTYPE 1' (((B 1 2 1 3 0 5 8 9 $false -5)[2] -ceq 'P3:3') -and ($o1[2] -ceq 'N:0') -and ((B 1 2 1 0 5 5 8 9 $false -5)[3] -ceq 'B5:5:9') -and ((B 1 2 1 0 9 5 8 9 $false -5)[3] -ceq 'EB:9:9') -and ($o1[4] -ceq '1') -and ($o1[5] -ceq ($REVS + ':N_P1_P2_P3_P4_P5:N_B1_B2_B3_B4_B5_B6_B7_B8_EB:')))
$oneNeg = $true; foreach ($p in -1, -2, -5, -6) { if ((J (B 1 2 1 $p 0 5 8 9 $false -5)) -cne 'drop|pow-range') { $oneNeg = $false } }
Check 'C03 one lever with POW below zero is an unknown case: unavailable (pow-range), nothing is guessed (Smee and Ecb, count 5 and 0)' ($oneNeg -and ((J (B 1 2 1 -1 0 5 8 9 $false 0)) -ceq 'drop|pow-range') -and ((J (B 1 1 1 -1 0 5 8 9 $false -5)) -ceq 'drop|pow-range'))
$noH = $true; foreach ($p in 0..5) { foreach ($k in 0..10) { $x = B 1 2 1 $p $k 5 8 9 $false -5; if (($x[2] -cmatch '^H') -or ($x[3] -cmatch '^H')) { $noH = $false } } }
Check 'C04 no one-lever H display exists (no power or brake text starts with H for any position)' $noH
# D. one-lever Cl: cab=OneLeverCab brake=Cl powN=5 brkN=2 ebN=3 (real machine)
$clp = New-Object System.Collections.Generic.List[string]; foreach ($p in 1..5) { $x = B 1 3 1 $p 0 5 2 3 $false 0; $clp.Add($x[2] + '/' + $x[3]) }
Check 'D01 one-lever Cl: pow 1..5 with brake 0 are P1..P5 and the brake text is the run word' ((J $clp) -ceq (J @(('P1:1/' + $W_RUN + ':0:3'), ('P2:2/' + $W_RUN + ':0:3'), ('P3:3/' + $W_RUN + ':0:3'), ('P4:4/' + $W_RUN + ':0:3'), ('P5:5/' + $W_RUN + ':0:3'))))
$clb = New-Object System.Collections.Generic.List[string]; foreach ($k in 0, 1, 2, 3) { $x = B 1 3 1 0 $k 5 2 3 $false 0; $clb.Add($x[2] + '/' + $x[3]) }
Check 'D02 one-lever Cl: (pow 0) brake 0 run, 1 lap, 2 service, 3 emergency; 4 and 1000 are beyond the emergency notch (brk-range)' (((J $clb) -ceq (J @(($W_RUN + ':0/' + $W_RUN + ':0:3'), ($W_RUN + ':0/' + $W_LAP + ':1:3'), ($W_RUN + ':0/' + $W_SVC + ':2:3'), ($W_RUN + ':0/' + $W_EMG + ':3:3')))) -and ((J (B 1 3 1 0 4 5 2 3 $false 0)) -ceq 'drop|brk-range') -and ((J (B 1 3 1 0 1000 5 2 3 $false 0)) -ceq 'drop|brk-range'))
Check 'D03 one-lever Cl literal: HTYPE 1, ALLTXT P0 is the run word then P1..P5, brake texts run / lap / service / emergency; the two-lever Cl is unchanged (HTYPE 2, P0, run word)' (((B 1 3 1 0 0 5 2 3 $false 0)[5] -ceq ($REVS + ':' + $W_RUN + '_P1_P2_P3_P4_P5:' + $W_RUN + '_' + $W_LAP + '_' + $W_SVC + '_' + $W_EMG + ':')) -and ((B 1 3 1 0 0 5 2 3 $false 0)[4] -ceq '1') -and ((B 2 3 1 0 0 5 2 3 $false 0)[4] -ceq '2') -and ((B 2 3 1 0 0 5 2 3 $false 0)[2] -ceq 'P0:0') -and ((B 2 3 1 0 0 5 2 3 $false 0)[3] -ceq ($W_RUN + ':0:3')))
$both = $true; foreach ($p in 1, 3, 5) { foreach ($k in 1, 2, 3) { if ((J (B 1 3 1 $p $k 5 2 3 $false 0)) -cne 'drop|pow-brk-both') { $both = $false } } }
Check 'D04 one-lever Cl with power and brake both positive is unavailable (pow-brk-both) for every pair up to the emergency notch; beyond it brk-range' ($both -and ((J (B 1 3 1 3 4 5 2 3 $false 0)) -ceq 'drop|brk-range'))
Check 'D05 one-lever Cl out of range or unreadable is unavailable: pow 6 / -1 (pow-range), brake -1 (brk-range), reverser 2 (rev-range), missing values (rev / pow / brk / layout / hold flag)' (((J (B 1 3 1 6 0 5 2 3 $false 0)) -ceq 'drop|pow-range') -and ((J (B 1 3 1 -1 0 5 2 3 $false 0)) -ceq 'drop|pow-range') -and ((J (B 1 3 1 0 -1 5 2 3 $false 0)) -ceq 'drop|brk-range') -and ((J (B 1 3 2 0 0 5 2 3 $false 0)) -ceq 'drop|rev-range') -and ((J (B 1 3 $null 0 0 5 2 3 $false 0)) -ceq 'drop|rev-missing') -and ((J (B 1 3 1 $null 0 5 2 3 $false 0)) -ceq 'drop|pow-missing') -and ((J (B 1 3 1 0 $null 5 2 3 $false 0)) -ceq 'drop|brk-missing') -and ((J (B 1 3 1 0 0 5 $null 3 $false 0)) -ceq 'drop|layout-missing') -and ((J (B 1 3 1 0 0 5 2 $null $false 0)) -ceq 'drop|layout-missing') -and ((J (B 1 3 1 0 0 5 2 3 $null 0)) -ceq 'drop|hold-missing'))
Check 'D06 an unexpected Cl layout is unavailable: brakeN 3 / ebN 4, brakeN 2 / ebN 4, brakeN 1 / ebN 2 (cl-layout), brakeN 0 (layout-range); a Cl layout is never guessed' (((J (B 1 3 1 0 0 5 3 4 $false 0)) -ceq 'drop|cl-layout') -and ((J (B 1 3 1 0 0 5 2 4 $false 0)) -ceq 'drop|cl-layout') -and ((J (B 1 3 1 0 0 5 1 2 $false 0)) -ceq 'drop|cl-layout') -and ((J (B 1 3 1 0 0 5 0 1 $false 0)) -ceq 'drop|layout-range'))
Check 'D07 the Cl count of holding speed notches is not used: unreadable, 0 and 5 give the same one-lever Cl group; POW -1 stays unavailable' (((J (B 1 3 1 0 0 5 2 3 $false $null)) -ceq (J (B 1 3 1 0 0 5 2 3 $false 0))) -and ((J (B 1 3 1 0 0 5 2 3 $false -5)) -ceq (J (B 1 3 1 0 0 5 2 3 $false 0))) -and ((J (B 1 3 1 -1 0 5 2 3 $false -5)) -ceq 'drop|pow-range'))
Check 'D08 the reverser words are the same for every handle (back / off / forward) and the Cl off word is the same character as the reverser off word in a different column' ((((B 1 3 -1 0 0 5 2 3 $false 0)[1]) -ceq ($W_BACK + ':-1')) -and (((B 1 3 0 0 0 5 2 3 $false 0)[1]) -ceq ($W_OFF + ':0')) -and (((B 1 3 1 0 0 5 2 3 $false 0)[1]) -ceq ($W_FWD + ':1')))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# S - the session: the lines the sender writes
# ---------------------------------------------------------------------------------------------------------------------------------------------
$allToks = 'bcp+bpp+brake_cab+brake_type+calcg+door+grad+handle+loc+maplimit+meta+prates+siglimit+siglimit_ahead+speed+station+time'
# S01-S03 the holding speed brake car, every brake position
$h = NewIn; Setup $h 2 1 5 8 9 $true 0; $h.Run(2, 16)
$w = New-Object System.Collections.Generic.List[string]; $okAll = $true
foreach ($k in 0..9) { $l = Pos $h 0 $k; $w.Add(((Part $l 'BRK').Split(':')[0])); if (-not ((HasTok $l 'handle') -and ((Part $l 'HTYPE') -ceq '2') -and ((Part $l 'ALLTXT') -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_' + $W_HOLD + '_B1_B2_B3_B4_B5_B6_B7_EB:')))) { $okAll = $false } }
Check 'S01 the line of a holding speed brake car carries the group at every brake position: B0, hold word, B1..B7, EB (positions 0..9), handle announced, ALLTXT as the contract says' (((J $w) -ceq (J @('B0', $W_HOLD, 'B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'EB'))) -and $okAll)
$l = Pos $h 3 1
Check 'S02 the holding speed brake with power applied: POW P3, BRK hold word 1/9 (the brake side is its own column), BCP / BPP still there, AVAIL has the 17 tokens' (((Part $l 'POW') -ceq 'P3:3') -and ((Part $l 'BRK') -ceq ($W_HOLD + ':1:9')) -and (Has $l 'BCP') -and (Has $l 'BPP') -and ((Part $l 'AVAIL') -ceq ('1:' + $allToks)))
$h.Closed(); $sm = (Ev $h 'TEL_INPUT_PUBLISH')
Check 'S03 no group was dropped over the whole drive (handleDropped=0) and the log names the layout once: layout=two-lever-ecb-holdbrake' (($sm.Count -eq 1) -and ($sm[0] -match 'handleDropped=0 ') -and ((Ev $h 'TEL_HANDLE_SEND').Count -eq 1) -and ((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-ecb-holdbrake powN=5 brkN=8 ebN=9'))
# S04-S09 the independent holding speed car
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Run(2, 16)
$pw = New-Object System.Collections.Generic.List[string]; $bkOk = $true; $tokOk = $true
foreach ($p in -5..5) { $l = Pos $h $p 3; $pw.Add((Part $l 'POW')); if ((Part $l 'BRK') -cne 'B3:3:9') { $bkOk = $false }; if (-not (HasTok $l 'handle')) { $tokOk = $false } }
Check 'S04 the line of an independent holding speed car follows POW -5..5: H5 .. H1, P0 .. P5; the brake column is untouched (B3:3:9 throughout); handle announced throughout' (((J $pw) -ceq (J @('H5:-5', 'H4:-4', 'H3:-3', 'H2:-2', 'H1:-1', 'P0:0', 'P1:1', 'P2:2', 'P3:3', 'P4:4', 'P5:5'))) -and $bkOk -and $tokOk)
$l = Pos $h -3 0
Check 'S05 ALLTXT of the line carries the holding speed texts in the fourth part (H1..H5) and POW is H3:-3 with BRK B0:0:9' (((Part $l 'ALLTXT') -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:H1_H2_H3_H4_H5')) -and ((Part $l 'POW') -ceq 'H3:-3') -and ((Part $l 'BRK') -ceq 'B0:0:9'))
$l = Pos $h -6 0
Check 'S06 POW -6 (below the formal count): the whole group AND its token are gone from the line (no stale H text), the rest of the line is intact; the next valid position brings the group back' ((NoHandleKeys $l) -and (-not (HasTok $l 'handle')) -and (HasTok $l 'speed') -and (Has $l 'BCP') -and ((Part (Pos $h -1 0) 'POW') -ceq 'H1:-1'))
$h.Closed(); $sm = (Ev $h 'TEL_INPUT_PUBLISH')
Check 'S07 the log: the layout line with holdN=-5 (the host value), then one line on entering a holding speed notch (holdPos=1); the drop is logged as reason=pow-range' (((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-smee powN=5 brkN=8 ebN=9 holdN=-5') -and ((Ev $h 'TEL_HANDLE_SEND')[1] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-smee powN=5 brkN=8 ebN=9 holdN=-5 holdPos=1') -and (@(Ev $h 'TEL_HANDLE_DROP').Count -ge 1) -and ((Ev $h 'TEL_HANDLE_DROP')[0] -ceq 'TEL_HANDLE_DROP gen=0 reason=pow-range'))
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Run(2, 16)
$null = Pos $h 0 0; $null = Pos $h -1 0; $null = Pos $h -2 0; $null = Pos $h -5 0; $null = Pos $h 0 0; $null = Pos $h 3 0
$hs = Ev $h 'TEL_HANDLE_SEND'
Check 'S08 diagnostics are state changes only: P0 -> H (holdPos=1) -> P0 -> P3 writes 3 lines (P, H, P again), never one per Tick' (($hs.Count -eq 3) -and ($hs[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-smee powN=5 brkN=8 ebN=9 holdN=-5') -and ($hs[1] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-smee powN=5 brkN=8 ebN=9 holdN=-5 holdPos=1') -and ($hs[2] -ceq $hs[0]))
$h.Closed(); $sm = (Ev $h 'TEL_INPUT_PUBLISH')
Check 'S09 a drive over every valid POW / brake position of the independent car drops nothing: handleDropped=0 in the summary' (($sm.Count -eq 1) -and ($sm[0] -match 'handleDropped=0 '))
# S10-S12 the formal count missing
$h = NewIn; Setup $h 2 2 5 8 9 $false $null; $h.Run(3, 16)
Check 'S10 HoldingSpeedNotchCount unreadable on a two-lever Ecb / Smee car: POW 0 and above keep the group (position-level fallback, no holding speed texts, no count guessed from PowerNotchCount); POW below zero: no group, no token, the rest of the line intact; back to POW 0 the group returns' ((HasTok (Last $h) 'handle') -and ((Part (Last $h) 'POW') -ceq 'P0:0') -and ((Part (Last $h) 'ALLTXT') -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:')) -and (NoHandleKeys (Pos $h -1 0)) -and (-not (HasTok (Last $h) 'handle')) -and (HasTok (Last $h) 'speed') -and ((Part (Pos $h 3 0) 'POW') -ceq 'P3:3'))
$h.Closed()
Check 'S11 ... the drop is logged once as reason=holdn-missing with the diagnostic words holdN=missing holdSource=notchinfo holdValidity=missing' ((@(Ev $h 'TEL_HANDLE_DROP').Count -eq 1) -and ((Ev $h 'TEL_HANDLE_DROP')[0] -ceq 'TEL_HANDLE_DROP gen=0 reason=holdn-missing holdN=missing holdSource=notchinfo holdValidity=missing') -and ((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-smee powN=5 brkN=8 ebN=9 holdN=missing holdValidity=missing'))
$h = NewIn; Setup $h 1 2 5 8 9 $false $null; $h.Run(3, 16)
Check 'S12 the same unreadable count on a ONE-lever car does not matter (the count is not used there): the ordinary one-lever group is written' ((HasTok (Last $h) 'handle') -and ((Part (Last $h) 'HTYPE') -ceq '1') -and ((Part (Last $h) 'POW') -ceq 'N:0'))
# S13-S16 one lever + count
$h = NewIn; Setup $h 1 2 5 8 9 $false -5; $h.Run(2, 16)
$ol = New-Object System.Collections.Generic.List[string]; foreach ($p in 0, 1, 5) { $ol.Add((Part (Pos $h $p 0) 'POW')) }; $ol.Add((Part (Pos $h 0 4) 'BRK')); $ol.Add((Part (Pos $h 0 9) 'BRK'))
Check 'S13 one-lever Smee 5/8/9 with HoldingSpeedNotchCount=5: the ordinary one-lever group is written (N, P1, P5, B4, EB), HTYPE 1, ALLTXT without holding speed texts, handle announced' (((J $ol) -ceq (J @('N:0', 'P1:1', 'P5:5', 'B4:4:9', 'EB:9:9'))) -and ((Part (Last $h) 'HTYPE') -ceq '1') -and ((Part (Last $h) 'ALLTXT') -ceq ($REVS + ':N_P1_P2_P3_P4_P5:N_B1_B2_B3_B4_B5_B6_B7_B8_EB:')) -and (HasTok (Last $h) 'handle'))
$l = Pos $h -1 0
Check 'S14 one lever with POW -1 (never seen on the host): no group, no token - unavailable, nothing guessed; back to POW 0 the group returns' ((NoHandleKeys $l) -and (-not (HasTok $l 'handle')) -and ((Part (Pos $h 0 0) 'POW') -ceq 'N:0'))
$h.Closed()
Check 'S15 the one-lever log names the setting (holdN=-5) without a holding speed position; the drop is reason=pow-range' (((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=one-lever-smee powN=5 brkN=8 ebN=9 holdN=-5') -and ((Ev $h 'TEL_HANDLE_DROP')[0] -ceq 'TEL_HANDLE_DROP gen=0 reason=pow-range'))
# S16-S19 one-lever Cl and Cl + hold
$h = NewIn; Setup $h 1 3 5 2 3 $false 0; $h.Run(2, 16)
$cl = New-Object System.Collections.Generic.List[string]
foreach ($st in @(@(0, 0), @(3, 0), @(5, 0), @(0, 1), @(0, 2), @(0, 3))) { $l = Pos $h $st[0] $st[1]; $cl.Add((Part $l 'POW') + '/' + (Part $l 'BRK')) }
Check 'S16 the line of a one-lever Cl car: run / P3 / P5 / lap / service / emergency, HTYPE 1, handle announced, BCP / BPP still there' (((J $cl) -ceq (J @(($W_RUN + ':0/' + $W_RUN + ':0:3'), ('P3:3/' + $W_RUN + ':0:3'), ('P5:5/' + $W_RUN + ':0:3'), ($W_RUN + ':0/' + $W_LAP + ':1:3'), ($W_RUN + ':0/' + $W_SVC + ':2:3'), ($W_RUN + ':0/' + $W_EMG + ':3:3')))) -and ((Part (Last $h) 'HTYPE') -ceq '1') -and (HasTok (Last $h) 'handle') -and (Has (Last $h) 'BCP'))
$l = Pos $h 2 2
Check 'S17 one-lever Cl with power and brake both positive: no group, no token; the next valid state brings it back' ((NoHandleKeys $l) -and (-not (HasTok $l 'handle')) -and (HasTok $l 'speed') -and ((Part (Pos $h 0 0) 'POW') -ceq ($W_RUN + ':0')))
$h.Closed()
Check 'S18 the one-lever Cl log: layout=one-lever-cl sent, the both-positive drop logged once as pow-brk-both' (((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=one-lever-cl powN=5 brkN=2 ebN=3') -and (@(Ev $h 'TEL_HANDLE_DROP' | Where-Object { $_ -ceq 'TEL_HANDLE_DROP gen=0 reason=pow-brk-both' }).Count -eq 1))
$h = NewIn; Setup $h 2 3 5 2 3 $true 0; $h.Run(3, 16)
Check 'S19 a two-lever Cl car with the holding speed brake is built (LI2 final): handle announced, run word at brake 0, HTYPE 2, layout=two-lever-cl-holdbrake logged once, no drop; pressures still go out' ((HasTok (Last $h) 'handle') -and ((Part (Last $h) 'BRK') -ceq ($W_RUN + ':0:3')) -and ((Part (Last $h) 'HTYPE') -ceq '2') -and (HasTok (Last $h) 'bcp') -and ((Ev $h 'TEL_HANDLE_DROP').Count -eq 0) -and ((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=two-lever-cl-holdbrake powN=5 brkN=2 ebN=3'))
$h = NewIn; Setup $h 1 3 5 2 3 $true 0; $h.Run(3, 16)
Check 'S20 a one-lever Cl car with the holding speed brake is built too: HTYPE 1, run word, the holding speed word at brake position 1, layout=one-lever-cl-holdbrake' ((HasTok (Last $h) 'handle') -and ((Part (Last $h) 'HTYPE') -ceq '1') -and ((Part (Last $h) 'POW') -ceq ($W_RUN + ':0')) -and ((Part (Pos $h 0 1) 'BRK') -ceq ($W_HOLD + ':1:3')) -and ((Ev $h 'TEL_HANDLE_SEND')[0] -ceq 'TEL_HANDLE_SEND gen=0 layout=one-lever-cl-holdbrake powN=5 brkN=2 ebN=3'))
# S21-S24 scenario generations
$h = NewIn; Setup $h 2 1 5 8 9 $true 0; $h.Run(3, 16); $null = Pos $h 0 1; $idA = $h.ScenarioId; $allA = Part (Last $h) 'ALLTXT'
$h.Closed(); $h.Created(); $h.Api.Scenario = New-Object object; $h.Seed = $h.Seed + 4321
Setup $h 2 3 5 2 3 $null 0; $h.Run(3, 16); $firstB = $h.Sink.Lines()[$h.Sink.Lines().Count - 1]
Check 'S21 supported -> unsupported: a new generation whose car cannot be built (unreadable holding speed brake flag) shows NOTHING of the previous car (no hold word, no ALLTXT of the holding speed brake car), no handle token' (($h.ScenarioId -ne $idA) -and (NoHandleKeys $firstB) -and (-not (HasTok $firstB 'handle')) -and (@($h.Sink.Lines() | Where-Object { ($_ -match ('SCENARIO_ID:' + $h.ScenarioId + ',')) -and ($_ -match [regex]::Escape($W_HOLD)) }).Count -eq 0))
$h.Closed(); $h.Created(); $h.Api.Scenario = New-Object object; $h.Seed = $h.Seed + 99
Setup $h 2 2 5 8 9 $false -5; $h.Run(2, 16); $l = Pos $h -4 0
Check 'S22 unsupported -> supported: the new car (independent notches, POW -4) is shown with its own layout (H4:-4, holding texts H1..H5), nothing of the earlier cars' (((Part $l 'POW') -ceq 'H4:-4') -and ((Part $l 'ALLTXT') -cne $allA) -and ((Part $l 'ALLTXT') -cmatch ':H1_H2_H3_H4_H5$') -and (HasTok $l 'handle'))
$h.Closed(); $h.Created(); $h.Api.Scenario = New-Object object; $h.Seed = $h.Seed + 7
Setup $h 1 3 5 2 3 $false 0; $h.Run(2, 16); $l = Pos $h 0 2
Check 'S23 independent car -> one-lever Cl car in the next generation: the one-lever Cl layout replaces it (no H texts left, HTYPE 1, service word)' (((Part $l 'HTYPE') -ceq '1') -and ((Part $l 'ALLTXT') -cnotmatch 'H1') -and ((Part $l 'BRK') -ceq ($W_SVC + ':2:3')) -and ((Part $l 'POW') -ceq ($W_RUN + ':0')))
$h2 = NewIn; Setup $h2 2 2 5 8 9 $false -5; $h2.Run(2, 16); $null = Pos $h2 -2 0; $h2.Opened($true); $h2.Created(); $h2.Api.Scenario = New-Object object; $h2.Seed = $h2.Seed + 333
$h2.Input.HandlesFail = $true; $h2.Run(2, 16); $fl = $h2.Sink.Lines()[$h2.Sink.Lines().Count - 1]
Check 'S24 a reload is a new generation: while the handles cannot be read the new generation has no handle group (not the old H2)' (($h2.Epochs -eq 2) -and (NoHandleKeys $fl) -and (-not (HasTok $fl 'handle')))

# every Tick is rebuilt from the host
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Run(2, 16)
$a1 = Part (Pos $h -2 0) 'POW'; $h.Input.HoldN = -1; $a2 = Part (Pos $h -2 0) 'POW'; $h.Input.HoldN = -5; $a3 = Part (Pos $h -2 0) 'POW'
Check 'S25 the formal count is read every Tick (no cached layout): count -5 -> H2, count changed to -1 -> POW -2 is unavailable, back to -5 -> H2 again' (($a1 -ceq 'H2:-2') -and ($a2 -eq $null) -and ($a3 -ceq 'H2:-2'))
$h.Input.Hold = $true; $h.Input.HoldN = 0; $b1 = Part (Pos $h 0 1) 'BRK'; $h.Input.Hold = $false; $b2 = Part (Pos $h 0 1) 'BRK'
Check 'S26 and the holding speed brake flag likewise: flag on -> the brake position 1 is the hold word, flag off -> B1' (($b1 -ceq ($W_HOLD + ':1:9')) -and ($b2 -ceq 'B1:1:9'))
# the input is read once per Tick and only on the Tick thread
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Run(100, 16)
Check 'S27 the host is asked for the handles once per Tick (100 Ticks -> 100 reads) and only from the Tick thread' (($h.Input.CallCount('TryHandles') -eq 100) -and ($h.Input.Threads.Count -eq 1))
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Run(10, 16); $f = Last $h
Check 'S28 the line stays one small datagram (no newline, < 1200 characters) with the holding speed texts' (($f.IndexOf("`n") -lt 0) -and ($f.Length -lt 1200))
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; for ($i = 0; $i -lt 400; $i++) { $null = Pos $h (($i % 11) - 5) ($i % 5) }
$h.Closed(); $fl = New-Object System.Collections.Generic.List[string]; foreach ($n in 'TEL_HANDLE_SEND', 'TEL_HANDLE_DROP') { foreach ($x in (Ev $h $n)) { $fl.Add([string]$x) } }
$badShape = @($fl | Where-Object { $_ -notmatch '^TEL_[A-Z_]+ gen=\d+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)+$' })
Check ('S29 every handle log line keeps the fixed shape NAME gen=N key=value ... (no path, no free text, no vehicle text) and a 400-Tick sweep stays inside the per-generation cap (' + $fl.Count + ' lines)') (($badShape.Count -eq 0) -and ($fl.Count -le 25))
# the pressure and the other groups are not influenced
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Input.StoreBc = [double[]]@(321.5); $h.Input.StoreBp = [double[]]@(12.3); $h.Run(3, 16); $l = Pos $h -2 5
Check 'S30 BCP / BPP and the 14 tokens of Phase L3 are unchanged by the holding speed handle (321.5 / 12.3 kPa, 17 tokens)' (((Part $l 'BCP') -ceq '321.5') -and ((Part $l 'BPP') -ceq '12.3') -and ((Part $l 'AVAIL') -ceq ('1:' + $allToks)) -and (-not (Has $l 'TRAINLEN')) -and (-not ((Part $l 'BPP') -match ':')))

# ---------------------------------------------------------------------------------------------------------------------------------------------
# R - the real-machine retest of the independent holding speed car (LI2 candidate 0.3.0.0 FAILED it): the host reports HoldingSpeedNotchCount NEGATED (-5 for five notches).
#     Real log: cab=TwoLeverCab brake=Smee powN=5 brkN=8 ebN=9 hold=0 b67=7, first Tick rev=0 pow=0 brk=9, then POW -1..-5. The earlier tests fed +5 (the sign was assumed, never taken from the host).
# ---------------------------------------------------------------------------------------------------------------------------------------------
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Input.Rev = 0; $h.Input.Pow = 0; $h.Input.Brk = 9; $h.Run(2, 16)
Check 'R01 the first Tick of the real car (host count -5, rev 0, pow 0, brk 9 = EB) builds the group and announces it: P0, EB:9:9, ALLTXT with H1..H5 - it is NOT dropped as hold-range' ((HasTok (Last $h) 'handle') -and ((Part (Last $h) 'POW') -ceq 'P0:0') -and ((Part (Last $h) 'BRK') -ceq 'EB:9:9') -and ((Part (Last $h) 'ALLTXT') -ceq ($REVS + ':P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:H1_H2_H3_H4_H5')) -and ((Ev $h 'TEL_HANDLE_DROP').Count -eq 0))
$pw = New-Object System.Collections.Generic.List[string]; foreach ($p in -5..5) { $pw.Add((Part (Pos $h $p 0 0) 'POW')) }
Check 'R02 the real car, host count -5: POW -5..-1 are H5..H1, 0 is P0, 1..5 are P1..P5 (every position a group, none dropped)' ((J $pw) -ceq (J @('H5:-5', 'H4:-4', 'H3:-3', 'H2:-2', 'H1:-1', 'P0:0', 'P1:1', 'P2:2', 'P3:3', 'P4:4', 'P5:5')))
Check 'R03 POW -6 on the real car (host count -5) is unavailable (pow-range): no group, no token' ((NoHandleKeys (Pos $h -6 0 0)) -and (-not (HasTok (Last $h) 'handle')))
$h.Closed(); $sm = (Ev $h 'TEL_INPUT_PUBLISH')
Check 'R04 the real-car drive (EB at the first Tick, then every valid position) drops exactly the one out-of-range position: handleDropped=1 (-6); the earlier candidate dropped every Tick' (($sm.Count -eq 1) -and ($sm[0] -match 'handleDropped=1 ') -and ($sm[0] -match 'handleSent=\d+') -and ([int]([regex]::Match($sm[0], 'handleSent=(\d+)').Groups[1].Value) -ge 12))
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Input.Rev = 0; $h.Input.Brk = 9; $h.Run(2, 16)
$first = Ev $h 'TEL_HANDLE_FIRST'
Check 'R05 TEL_HANDLE_FIRST names the host value and its validity: holdN=-5 holdBrake=0 holdSource=notchinfo holdValidity=ok (hold= stays the holding speed BRAKE flag)' (($first.Count -eq 1) -and ($first[0] -cmatch ' hold=0 b67=-?\d+ holdN=-5 holdBrake=0 holdSource=notchinfo holdValidity=ok rev=-?\d+ pow=-?\d+ brk=-?\d+$'))
$fl = @{}
foreach ($v in @(@('missing', $null), @('range-pos', 5), @('range-neg', -100), @('zero', 0), @('one', -1), @('max', -99))) {
    $hh = NewIn; Setup $hh 2 2 5 8 9 $false $v[1]; $hh.Input.Rev = 0; $hh.Input.Brk = 9; $hh.Run(2, 16); $fl[$v[0]] = [string](Ev $hh 'TEL_HANDLE_FIRST')[0]
}
Check 'R06 TEL_HANDLE_FIRST for an unreadable / abnormal / zero / minimal / maximal value: holdN=missing validity missing; 5 and -100 validity range; 0, -1, -99 validity ok' (($fl['missing'] -cmatch ' holdN=missing holdBrake=0 holdSource=notchinfo holdValidity=missing rev=-?\d+ pow=-?\d+ brk=-?\d+$') -and ($fl['range-pos'] -cmatch ' holdN=5 holdBrake=0 holdSource=notchinfo holdValidity=range rev=-?\d+ pow=-?\d+ brk=-?\d+$') -and ($fl['range-neg'] -cmatch ' holdN=-100 holdBrake=0 holdSource=notchinfo holdValidity=range rev=-?\d+ pow=-?\d+ brk=-?\d+$') -and ($fl['zero'] -cmatch ' holdN=0 holdBrake=0 holdSource=notchinfo holdValidity=ok rev=-?\d+ pow=-?\d+ brk=-?\d+$') -and ($fl['one'] -cmatch ' holdN=-1 holdBrake=0 holdSource=notchinfo holdValidity=ok rev=-?\d+ pow=-?\d+ brk=-?\d+$') -and ($fl['max'] -cmatch ' holdN=-99 holdBrake=0 holdSource=notchinfo holdValidity=ok rev=-?\d+ pow=-?\d+ brk=-?\d+$'))
$hh = NewIn; Setup $hh 2 1 5 8 9 $true 0; $hh.Input.Brk = 9; $hh.Run(2, 16)
Check 'R07 the holding speed BRAKE car (hold=1) says holdBrake=1 in the same line and its group does not depend on the count: no confusion between the two features' (((Ev $hh 'TEL_HANDLE_FIRST')[0] -cmatch ' hold=1 b67=-?\d+ holdN=0 holdBrake=1 holdSource=notchinfo holdValidity=ok rev=-?\d+ pow=-?\d+ brk=-?\d+$') -and ((Part (Last $hh) 'BRK') -ceq 'EB:9:9'))
foreach ($c in @(@('missing', $null, 'holdn-missing', 'missing', 'missing'), @('range-pos', 7, 'hold-range', '7', 'range'), @('range-neg', -100, 'hold-range', '-100', 'range'))) {
    $hh = NewIn; Setup $hh 2 2 5 8 9 $false $c[1]; $hh.Run(2, 16); $null = Pos $hh 0 0; $d0 = (Ev $hh 'TEL_HANDLE_DROP').Count; $null = Pos $hh -2 0
    $dl = Ev $hh 'TEL_HANDLE_DROP'; $good = ($d0 -eq 0) -and ($dl.Count -eq 1) -and ($dl[0] -ceq ('TEL_HANDLE_DROP gen=0 reason=' + $c[2] + ' holdN=' + $c[3] + ' holdSource=notchinfo holdValidity=' + $c[4])) -and (NoHandleKeys (Last $hh)) -and (-not (HasTok (Last $hh) 'handle')) -and (HasTok (Last $hh) 'speed') -and ((Part (Pos $hh 2 0) 'POW') -ceq 'P2:2')
    Check ('R08 holdN ' + $c[0] + ': the group is built at POW 0 and above (no drop there), POW -2 alone is unavailable with the diagnostic words in the drop line, POW 2 brings the group back') $good
}
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Run(2, 16); $a1 = Part (Pos $h -4 0) 'POW'
$h.Closed(); $h.Created(); $h.Api.Scenario = New-Object object; $h.Seed = $h.Seed + 11
Setup $h 2 2 5 8 9 $false -2; $h.Run(2, 16); $a2 = Part (Pos $h -4 0) 'POW'; $a3 = Part (Pos $h -2 0) 'POW'; $a4 = Part (Pos $h -2 0) 'ALLTXT'
Check 'R09 a new generation with another count shows only its own: -5 then -2 notches - POW -4 is H4 in the first car and unavailable in the second (no cached count), -2 is H2 with holding texts H1_H2' (($a1 -ceq 'H4:-4') -and ($a2 -eq $null) -and ($a3 -ceq 'H2:-2') -and ($a4 -cmatch ':H1_H2$'))
$h = NewIn; Setup $h 2 2 5 8 9 $false -2; $h.Run(2, 16)
Check 'R10 PowerNotchCount is never substituted: powN 5 with host count -2 allows H1 H2 only (POW -3 unavailable); powN 5 with count 0 allows no H at all' (((Part (Pos $h -2 0) 'POW') -ceq 'H2:-2') -and ((Part (Pos $h -3 0) 'POW') -eq $null) -and ((J (B 2 2 1 -1 0 5 8 9 $false 0)) -ceq 'drop|pow-range'))
$exRaw = [IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyTelemetryExtension.cs'))
Check 'R11 the host adapter hands the host value to the snapshot UNCHANGED (one plain assignment, no sign change, abs, conversion or PowerNotchCount on that line); the sign is interpreted only in the contract' ((@([regex]::Matches($exRaw, 's\.HoldingSpeedNotchCount\s*=\s*info\.HoldingSpeedNotchCount;')).Count -eq 1) -and ($exRaw -notmatch 'HoldingSpeedNotchCount\s*=\s*[-(]|Math\.Abs\(\s*info\.HoldingSpeedNotchCount') -and ((Code ([IO.File]::ReadAllText((Join-Path $Root 'Telemetry\Legacy\src\LegacyHandleContract.cs')))) -match 'holdN = -h\.HoldingSpeedNotchCount\.Value'))
$h = NewIn; Setup $h 2 2 5 8 9 $false -5; for ($i = 0; $i -lt 300; $i++) { $null = Pos $h (($i % 13) - 6) ($i % 11) }
$h.Closed(); $fl = New-Object System.Collections.Generic.List[string]; foreach ($n in 'TEL_HANDLE_SEND', 'TEL_HANDLE_DROP', 'TEL_HANDLE_FIRST') { foreach ($x in (Ev $h $n)) { $fl.Add([string]$x) } }
$bad = @($fl | Where-Object { $_ -notmatch '^TEL_[A-Z_]+ gen=\d+( [A-Za-z0-9]+=[A-Za-z0-9_.\-]+)+$' })
Check ('R12 the diagnostics of the real car keep the fixed shape NAME gen=N key=value ... (no path, no exception text, no vehicle text) over a sweep including out-of-range positions (' + $fl.Count + ' lines)') (($bad.Count -eq 0) -and ($fl.Count -le 30))
# ---------------------------------------------------------------------------------------------------------------------------------------------
# M - the 24 combinations (cab x brake x HoldingSpeedNotchCount x HoldingSpeedBrake), all observed on the real BVE5: the C# contract and the session against the machine readable
#     reference table tests\legacy_input_matrix24.json (spelled out by tests\legacy_input_reference.py). Ecb and Smee are separate rows; hold_n is the HOST value (0 / -5).
# ---------------------------------------------------------------------------------------------------------------------------------------------
$matrixFile = Join-Path $repo 'tests\legacy_input_matrix24.json'
$mx = @()
foreach ($x in (ConvertFrom-Json ([IO.File]::ReadAllText($matrixFile, [Text.Encoding]::UTF8)))) { $mx += $x }
function PT($row, [int]$k) { return [string]$row.pow_texts.PSObject.Properties[[string]$k].Value }
function BT($row, [int]$k) { return [string]$row.brk_texts.PSObject.Properties[[string]$k].Value }
$names = @($mx | ForEach-Object { $_.name })
Check 'M01 the reference table holds exactly the 24 combinations (2 cabs x 3 brake kinds x 2 host counts x 2 holding speed brake flags), 24 distinct names, Ecb and Smee as separate rows' (($mx.Count -eq 24) -and (@($names | Sort-Object -Unique).Count -eq 24) -and (@($mx | Where-Object { $_.in[1] -eq 1 }).Count -eq 8) -and (@($mx | Where-Object { $_.in[1] -eq 2 }).Count -eq 8) -and (@($mx | Where-Object { $_.in[1] -eq 3 }).Count -eq 8))
$bad = New-Object System.Collections.Generic.List[string]; $nPos = 0
foreach ($r in $mx) {
    $ht = [int]$r.in[0]; $bk = [int]$r.in[1]; $hb = [bool]$r.in[2]; $hn = [int]$r.in[3]; $pn = [int]$r.in[4]; $bn = [int]$r.in[5]; $en = [int]$r.in[6]
    for ($p = [int]$r.pow_min; $p -le $pn; $p++) {
        $o = B $ht $bk 1 $p 0 $pn $bn $en $hb $hn; $nPos++
        if (($o[0] -cne 'ok') -or ($o[2] -cne ((PT $r $p) + ':' + $p)) -or ($o[4] -cne [string]$r.htype) -or ($o[5] -cne ($REVS + ':' + (($r.alltxt -split ':')[1]) + ':' + (($r.alltxt -split ':')[2]) + ':' + (($r.alltxt -split ':')[3])))) { $bad.Add($r.name + ' pow ' + $p) }
    }
    for ($k = 0; $k -le $en; $k++) {
        $o = B $ht $bk 1 0 $k $pn $bn $en $hb $hn; $nPos++
        if (($o[0] -cne 'ok') -or ($o[3] -cne ((BT $r $k) + ':' + $k + ':' + $en))) { $bad.Add($r.name + ' brk ' + $k) }
    }
}
Check ('M02 the C# contract equals the spelled out table at every POW (down to the host count) and every BRK position (0..emergency notch) of all 24 combinations: REV-less texts, HTYPE and ALLTXT (' + $nPos + ' positions, ' + $bad.Count + ' differ) ' + (($bad | Select-Object -First 3) -join ';')) (($bad.Count -eq 0) -and ($nPos -gt 300))
# the session: a drive over every regular position of every combination drops nothing; the unsafe positions are gone and the group comes back
$sessBad = New-Object System.Collections.Generic.List[string]; $nLines = 0
foreach ($r in $mx) {
    $ht = [int]$r.in[0]; $bk = [int]$r.in[1]; $hb = [bool]$r.in[2]; $hn = [int]$r.in[3]; $pn = [int]$r.in[4]; $bn = [int]$r.in[5]; $en = [int]$r.in[6]
    $h = NewIn; Setup $h $ht $bk $pn $bn $en $hb $hn; $h.Run(2, 16)
    for ($p = [int]$r.pow_min; $p -le $pn; $p++) {
        $l = Pos $h $p 0; $nLines++
        if (-not ((HasTok $l 'handle') -and ((Part $l 'POW') -ceq ((PT $r $p) + ':' + $p)) -and ((Part $l 'HTYPE') -ceq [string]$r.htype) -and ((Part $l 'ALLTXT') -ceq ($REVS + ':' + (($r.alltxt -split ':', 4)[1]) + ':' + (($r.alltxt -split ':', 4)[2]) + ':' + (($r.alltxt -split ':', 4)[3]))))) { $sessBad.Add($r.name + ' pow ' + $p) }
    }
    for ($k = 0; $k -le $en; $k++) {
        $l = Pos $h 0 $k; $nLines++
        if (-not ((HasTok $l 'handle') -and ((Part $l 'BRK') -ceq ((BT $r $k) + ':' + $k + ':' + $en)))) { $sessBad.Add($r.name + ' brk ' + $k) }
    }
    if ($ht -eq 2) { $l = Pos $h $pn $en; $nLines++; if (-not (HasTok $l 'handle')) { $sessBad.Add($r.name + ' both positive') } }
    $h.Closed(); $sm = Ev $h 'TEL_INPUT_PUBLISH'
    if (-not (($sm.Count -eq 1) -and ($sm[0] -match 'handleDropped=0 '))) { $sessBad.Add($r.name + ' dropped: ' + $sm[0]) }
}
Check ('M03 the session writes the regular series of every combination with the handle announced at every Tick and handleDropped=0 in the summary (' + $nLines + ' Ticks over 24 cars, ' + $sessBad.Count + ' wrong) ' + (($sessBad | Select-Object -First 3) -join ';')) (($sessBad.Count -eq 0) -and ($nLines -gt 300))
$unsBad = New-Object System.Collections.Generic.List[string]
foreach ($r in $mx) {
    $ht = [int]$r.in[0]; $bk = [int]$r.in[1]; $hb = [bool]$r.in[2]; $hn = [int]$r.in[3]; $pn = [int]$r.in[4]; $bn = [int]$r.in[5]; $en = [int]$r.in[6]
    $h = NewIn; Setup $h $ht $bk $pn $bn $en $hb $hn; $h.Run(2, 16)
    $cases = @(@(($pn + 1), 0), @(([int]$r.pow_min - 1), 0), @(0, ($en + 1)), @(0, -1))
    if ($ht -eq 1) { $cases += , @(1, 1) }
    foreach ($c in $cases) {
        $l = Pos $h $c[0] $c[1]
        if (-not ((NoHandleKeys $l) -and (-not (HasTok $l 'handle')) -and (HasTok $l 'speed') -and (Has $l 'BCP'))) { $unsBad.Add($r.name + ' ' + $c[0] + '/' + $c[1]) }
        $back = Pos $h 0 0
        if (-not (HasTok $back 'handle')) { $unsBad.Add($r.name + ' no return after ' + $c[0] + '/' + $c[1]) }
    }
    if ($ht -eq 2) { $l = Pos $h 1 1; if (-not (HasTok $l 'handle')) { $unsBad.Add($r.name + ' two-lever both positive refused') } }
}
Check ('M04 the unsafe positions of every combination (POW above the notches, below the lowest position / the host count, BRK beyond the emergency notch or negative, one lever with power and brake both positive) give no group and no token while the rest of the line stays, and the next valid position brings the group back; a two-lever cab may hold both (' + $unsBad.Count + ' wrong) ' + (($unsBad | Select-Object -First 3) -join ';')) ($unsBad.Count -eq 0)
# generation switch through all 24 combinations in ONE scenario host: each new generation shows only its own car
$genBad = New-Object System.Collections.Generic.List[string]; $h = NewIn; $first = $true; $gi = 0
foreach ($r in $mx) {
    $ht = [int]$r.in[0]; $bk = [int]$r.in[1]; $hb = [bool]$r.in[2]; $hn = [int]$r.in[3]; $pn = [int]$r.in[4]; $bn = [int]$r.in[5]; $en = [int]$r.in[6]
    if (-not $first) { $h.Closed(); $h.Created(); $h.Api.Scenario = New-Object object; $h.Seed = $h.Seed + 17 + $gi }
    $first = $false; $gi++
    Setup $h $ht $bk $pn $bn $en $hb $hn; $h.Run(2, 16); $l = Pos $h 0 0
    $want = $REVS + ':' + (($r.alltxt -split ':', 4)[1]) + ':' + (($r.alltxt -split ':', 4)[2]) + ':' + (($r.alltxt -split ':', 4)[3])
    if (-not ((Part $l 'ALLTXT') -ceq $want)) { $genBad.Add($r.name) }
}
Check ('M05 a generation switch through all 24 combinations in one host: every new generation writes the ALLTXT of its own car only (' + $genBad.Count + ' wrong) ' + (($genBad | Select-Object -First 3) -join ';')) ($genBad.Count -eq 0)
# an unusable host count on every two-lever combination: only the H positions go away
$cntBad = New-Object System.Collections.Generic.List[string]
foreach ($r in @($mx | Where-Object { ([int]$_.in[0] -eq 2) -and ([int]$_.in[3] -ne 0) })) {
    $ht = [int]$r.in[0]; $bk = [int]$r.in[1]; $hb = [bool]$r.in[2]; $pn = [int]$r.in[4]; $bn = [int]$r.in[5]; $en = [int]$r.in[6]
    foreach ($bad in $null, 5, 100, -100) {
        $o0 = B $ht $bk 1 0 0 $pn $bn $en $hb $bad; $o1 = B $ht $bk 1 -1 0 $pn $bn $en $hb $bad
        if (($o0[0] -cne 'ok') -or ($o1[0] -cne 'drop')) { $cntBad.Add($r.name + ' ' + $bad) }
    }
}
Check ('M06 an unreadable / abnormal host count (missing, +5, +100, -100) on every two-lever combination with notches takes only the POW < 0 positions away; POW 0 and above are built (' + $cntBad.Count + ' wrong)') ($cntBad.Count -eq 0)
Check 'M07 holdN=-2 and holdN=-5 give H1..H2 / H1..H5 on every two-lever brake kind (Ecb, Smee, Cl) with and without the holding speed brake; holdN=0 gives none' ((@(foreach ($bk in 1, 2, 3) { foreach ($hb in $false, $true) { $pn = 5; $bn = $(if ($bk -eq 3) { 2 } else { 8 }); $en = $bn + 1; "$(((B 2 $bk 1 -2 0 $pn $bn $en $hb -2)[2])) $(((B 2 $bk 1 -5 0 $pn $bn $en $hb -5)[2])) $((J (B 2 $bk 1 -3 0 $pn $bn $en $hb -2))) $((J (B 2 $bk 1 -1 0 $pn $bn $en $hb 0)))" } }) | Sort-Object -Unique) -ceq 'H2:-2 H5:-5 drop|pow-range drop|pow-range')
# ---------------------------------------------------------------------------------------------------------------------------------------------
# E - the lines the DLL writes, read by the REAL Python reader and Overlay (offscreen, real UDP socket) - only when UDP 54321 is free
# ---------------------------------------------------------------------------------------------------------------------------------------------
$ovPy = Join-Path $repo 'tests\telemetry_overlay_check.py'
$xPy = Join-Path $repo 'tests\telemetry_xcheck.py'
$udpBusy = @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveUdpListeners() | Where-Object { $_.Port -eq 54321 }).Count -gt 0
$qtOk = $false
try { $qtOk = ((& $py -c "import PyQt6.QtWidgets; print('ok')") -eq 'ok') } catch { $qtOk = $false }
function Dump($hh, [string]$name) { $f = Join-Path $testDir $name; [IO.File]::WriteAllText($f, (($hh.Sink.Sent -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false))); return $f }
if ($py -and (Test-Path $xPy)) {
    $h = NewIn; Setup $h 2 2 5 8 9 $false -5; $h.Input.StoreBc = [double[]]@(100.0); $h.Input.StoreBp = [double[]]@(490.0); $h.Run(2, 16); $null = Pos $h -3 2
    $j = (& $py -I $xPy (Dump $h 'x-dump.txt') | Out-String) | ConvertFrom-Json
    $tel = @($j | Where-Object { $_.kind -eq 'telemetry' })
    Check 'E01 the Python reference reader accepts every line of the independent holding speed car, reads exactly the 17 announced tokens, none unknown / malformed' (($tel.Count -ge 2) -and (@($tel | Where-Object { -not $_.valid }).Count -eq 0) -and ((($tel[$tel.Count - 1].tokens | Sort-Object) -join '+') -ceq $allToks) -and ($tel[$tel.Count - 1].unknown -eq 0) -and ($tel[$tel.Count - 1].bad -eq 0))
}
else { Skip 'E01 (python or tests\telemetry_xcheck.py missing)' }
if ($qtOk -and (-not $udpBusy) -and (Test-Path $ovPy)) {
    # name, handle type, brake, powN, brkN, ebN, hold, holdN, pow, brk, expected POW text, expected BRK text, expected brake list head
    $cases = @(
        @('hold brake brake 0', 2, 1, 5, 8, 9, $true, 0, 0, 0, 'P0', 'B0'),
        @('hold brake position 1', 2, 1, 5, 8, 9, $true, 0, 0, 1, 'P0', $W_HOLD),
        @('hold brake position 2', 2, 1, 5, 8, 9, $true, 0, 2, 2, 'P2', 'B1'),
        @('hold brake EB', 2, 1, 5, 8, 9, $true, 0, 0, 9, 'P0', 'EB'),
        @('independent H1', 2, 2, 5, 8, 9, $false, -5, -1, 0, 'H1', 'B0'),
        @('independent H5', 2, 2, 5, 8, 9, $false, -5, -5, 3, 'H5', 'B3'),
        @('independent P0', 2, 2, 5, 8, 9, $false, -5, 0, 0, 'P0', 'B0'),
        @('one-lever with count P3', 1, 2, 5, 8, 9, $false, -5, 3, 0, 'P3', 'N'),
        @('one-lever Cl P4', 1, 3, 5, 2, 3, $false, 0, 4, 0, 'P4', $W_RUN),
        @('one-lever Cl off', 1, 3, 5, 2, 3, $false, 0, 0, 0, $W_RUN, $W_RUN),
        @('one-lever Cl lap', 1, 3, 5, 2, 3, $false, 0, 0, 1, 'P0', $W_LAP),
        @('one-lever Cl service', 1, 3, 5, 2, 3, $false, 0, 0, 2, 'P0', $W_SVC),
        @('one-lever Cl emergency', 1, 3, 5, 2, 3, $false, 0, 0, 3, 'P0', $W_EMG)
    )
    foreach ($e in $cases) {
        $hh = NewIn; Setup $hh $e[1] $e[2] $e[3] $e[4] $e[5] $e[6] $e[7]; $hh.Input.StoreBc = [double[]]@(321.5); $hh.Input.StoreBp = [double[]]@(12.3); $hh.Run(2, 16); $null = Pos $hh $e[8] $e[9]
        $dump = Dump $hh ('o-' + ($e[0] -replace '\W', '') + '.txt')
        $o = (& $py $ovPy $dump | Out-String) | ConvertFrom-Json
        $wantPow = [string]$e[10]; $wantBrk = [string]$e[11]
        if (($e[1] -eq 1) -and ($e[3] -ge 0)) { $wantPow = $(if (($e[2] -eq 3) -and ($e[8] -eq 0)) { $W_RUN } elseif ($e[8] -eq 0) { 'N' } else { 'P' + $e[8] }) }
        $drawn = @($o.drawn)
        $stateOk = ($o.states.handle -eq 'shown') -and ($o.values.bve_brk_text -ceq $wantBrk) -and ($o.values.bcPressure -eq 321.5) -and ($o.values.bpPressure -eq 12.3)
        if ($e[1] -eq 2) { $stateOk = $stateOk -and ($o.values.bve_pow_text -ceq $wantPow) }
        # the handle row shows the power word for a one-lever handle while a power position is held, else the brake word; for two levers both
        $shownText = $(if ($e[1] -eq 1) { $(if ($e[8] -ne 0) { 'P' + $e[8] } elseif ($e[9] -gt 0) { $wantBrk } else { $o.values.bve_pow_text }) } else { $null })
        $drawnOk = $(if ($e[1] -eq 2) { ($drawn -ccontains $wantPow) -and ($drawn -ccontains $wantBrk) } else { $drawn -ccontains $shownText })
        Check ('E02 ' + $e[0] + ': the REAL Overlay holds POW ' + $wantPow + ' / BRK ' + $wantBrk + ' (kPa 321.5 / 12.3), the handle row is shown and the text is drawn') ($stateOk -and $drawnOk -and ($o.stats.tel_invalid -eq 0))
    }
    $hh = NewIn; Setup $hh 2 2 5 8 9 $false -5; $hh.Run(2, 16); $null = Pos $hh -6 0
    $o = (& $py $ovPy (Dump $hh 'o-below.txt') | Out-String) | ConvertFrom-Json
    Check 'E03 POW below the formal count: the REAL Overlay reports the handle row unavailable and draws no H text and none of its default handle words' (($o.states.handle -eq 'unavailable') -and (@($o.drawn | Where-Object { $_ -cmatch '^H[0-9]' }).Count -eq 0) -and (@($o.drawn | Where-Object { $_ -ceq $W_OFF }).Count -eq 0))
    $hh = NewIn; Setup $hh 2 3 5 2 3 $true 0; $hh.Run(2, 16); $null = Pos $hh 0 1
    $o = (& $py $ovPy (Dump $hh 'o-clhold.txt') | Out-String) | ConvertFrom-Json
    Check 'E04 a two-lever Cl car with the holding speed brake (LI2 final): the REAL Overlay holds the handle row as shown and draws the holding speed word at brake position 1' (($o.states.handle -eq 'shown') -and ($o.values.bve_brk_text -ceq $W_HOLD) -and (@($o.drawn | Where-Object { $_ -ceq $W_HOLD }).Count -ge 1))
}
else { Skip ('E02-E04 real Overlay chain: not run (PyQt6=' + $qtOk + ', UDP 54321 busy=' + $udpBusy + ')') }

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
# handle type, brake kind, powN, brkN, ebN, hold brake, holding speed notch count
$combos = @(%%COMBOS%%)
foreach ($c in $combos) {
    $h = New-Object TsScoringLegacyTelemetryTests.Harness -ArgumentList $true
    $h.Input.HandleTypeValue = $c[0]; $h.Input.BrakeKindValue = $c[1]; $h.Api.BrakeKind = $c[1]
    $h.Input.CabName = $(if ($c[0] -eq 1) { 'OneLeverCab' } else { 'TwoLeverCab' })
    $h.Input.PowN = $c[2]; $h.Input.BrkN = $c[3]; $h.Input.EbN = $c[4]; $h.Input.Hold = $c[5]; $h.Input.HoldN = $c[6]; $h.Input.Rev = 1
    foreach ($p in -6, -3, -1, 0, 2, 5) {
        foreach ($b in 0, 1, 2, $c[4]) { $h.Input.Pow = $p; $h.Input.Brk = $b; $h.Input.StoreBc = [double[]]@(100.5 + $b); $h.Input.StoreBp = [double[]]@(490.0 - $b); $h.Run(2, 16) }
    }
    foreach ($s in $h.Sink.Sent) { $lines.Add($s) }
}
$bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
$sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-', '')
[IO.File]::WriteAllText($Out, ('ptr=' + [IntPtr]::Size + ' lines=' + $lines.Count + ' sha=' + $sha), (New-Object Text.UTF8Encoding($false)))
'@
# every one of the 24 combinations (host count 0 / -5) plus the earlier hand-written ones (unusable +5 / -100, other counts, powN 6)
$comboText = (@($mx | ForEach-Object { '@(' + $_.in[0] + ', ' + $_.in[1] + ', ' + $_.in[4] + ', ' + $_.in[5] + ', ' + $_.in[6] + ', ' + $(if ($_.in[2]) { '$true' } else { '$false' }) + ', ' + $_.in[3] + ')' }) -join ', ') + ', ' + '@(2, 1, 5, 8, 9, $true, 0), @(2, 2, 5, 8, 9, $false, -5), @(1, 2, 5, 8, 9, $false, -5), @(2, 2, 5, 8, 9, $false, 5), @(2, 2, 5, 8, 9, $false, -100), @(2, 2, 5, 8, 9, $false, -1), @(2, 1, 6, 8, 9, $false, -3), @(1, 3, 5, 2, 3, $false, 0), @(2, 3, 5, 2, 3, $false, 0), @(2, 1, 6, 8, 9, $false, 0)'
$probeText = $probeText.Replace('%%COMBOS%%', $comboText)
[IO.File]::WriteAllText($probe, $probeText, (New-Object Text.UTF8Encoding($false)))
$ps64 = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$ps32 = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
if ((Test-Path $ps32) -and (Test-Path $ps64)) {
    $d64 = Join-Path $testDir 'p64'; $d32 = Join-Path $testDir 'p32'
    New-Item -ItemType Directory -Force $d64, $d32 | Out-Null
    Copy-Item $dllCopy $d64; Copy-Item $dllCopy $d32
    & $ps64 -NoProfile -ExecutionPolicy Bypass -File $probe -Dll (Join-Path $d64 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -Fixture $fixtureSrc -Out (Join-Path $d64 'out.txt') | Out-Null
    & $ps32 -NoProfile -ExecutionPolicy Bypass -File $probe -Dll (Join-Path $d32 'TSScoringPlugin.AtsExLegacy.Telemetry.dll') -Fixture $fixtureSrc -Out (Join-Path $d32 'out.txt') | Out-Null
    $t64 = if (Test-Path (Join-Path $d64 'out.txt')) { [IO.File]::ReadAllText((Join-Path $d64 'out.txt')) } else { '' }
    $t32 = if (Test-Path (Join-Path $d32 'out.txt')) { [IO.File]::ReadAllText((Join-Path $d32 'out.txt')) } else { '' }
    Check ('F01 a 32-bit process (BVE5) loads the DLL and writes exactly the same bytes as the 64-bit one for all 24 cab / brake / count / holding speed brake combinations and the unusable counts (' + $t64 + ' | ' + $t32 + ')') (($t64 -match '^ptr=8 ') -and ($t32 -match '^ptr=4 ') -and (($t64 -replace '^ptr=\d+ ', '') -ceq ($t32 -replace '^ptr=\d+ ', '')) -and ($t64 -match 'lines=\d{3,}'))
}
else { Skip 'F01 (no 32-bit Windows PowerShell here)' }

# ---------------------------------------------------------------------------------------------------------------------------------------------
# G - sources, version, scope
# ---------------------------------------------------------------------------------------------------------------------------------------------
$srcDir = Join-Path $Root 'Telemetry\Legacy\src'
$hcCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyHandleContract.cs')))
$itCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyInputTelemetry.cs')))
$exCode = Code ([IO.File]::ReadAllText((Join-Path $srcDir 'LegacyTelemetryExtension.cs')))
Check 'G01 the contract and the telemetry core stay host independent (no AtsEx / BveTypes name) and use no reflection, hook, DllImport, unsafe, Harmony or private member' ((($hcCode + $itCode) -cnotmatch 'AtsEx|BveTypes|BveEx') -and (($hcCode + $itCode) -notmatch 'BindingFlags|DllImport|\bunsafe\b|Harmony|\.GetField\(|\.GetProperty\(|\.GetMethod\(|\.Invoke\(|Marshal\.'))
Check 'G02 the formal count is read from the public API property NotchInfo.HoldingSpeedNotchCount and is never filled from PowerNotchCount (no assignment from it anywhere)' (($exCode -match 's\.HoldingSpeedNotchCount\s*=\s*info\.HoldingSpeedNotchCount') -and (($exCode + $hcCode + $itCode) -notmatch 'HoldingSpeedNotchCount\s*=[^=;]*PowerNotchCount') -and ($hcCode -notmatch 'holdN\s*=[^;]*(PowerNotchCount|powN)'))
$vi = (Get-Item $dllPath).VersionInfo
Check 'G03 the DLL is 0.3.0.0 (assembly and file version), product TS Scoring, provider Coruge-to; the description names Phase L3, LI1 and LI2' (([TsScoringLegacyTelemetryTests.DiagInfo]::Version -eq '0.3.0.0') -and ($vi.FileVersion -eq '0.3.0.0') -and ($vi.ProductName -eq 'TS Scoring') -and ($vi.CompanyName -eq 'Coruge-to') -and ($vi.Comments -match 'Phase L3') -and ($vi.Comments -match 'LI1') -and ($vi.Comments -match 'LI2'))
function RunGit([string[]]$gitArgs) { $out = & git @gitArgs 2>$null; if ($LASTEXITCODE -ne 0) { return '' }; return ($out -join "`n") }
$top = (RunGit @('-C', $Root, 'rev-parse', '--show-toplevel')).Trim() -replace '/', '\'
$frozen = @(
    'TsScoringPlugin/TsScoringPlugin', 'TsScoringPlugin/Handshake/Caller', 'TsScoringPlugin/Handshake/Bridge', 'TsScoringPlugin/Handshake/Shared', 'TsScoringPlugin/Handshake/Telemetry/Shared',
    'telemetry_contract.py', 'telemetry_gate.py', 'network.py', 'main.py', 'hud_ui.py', 'scoring_logic.py', 'managed_hud.py', 'managed_mode.py', 'managed_state.py', 'menu_ui.py', 'config.py', 'utils.py',
    'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs'
)
$changedFrozen = @((RunGit (@('-C', $top, 'diff', '--name-only', 'HEAD', '--') + $frozen)) -split "`n" | Where-Object { $_ })
Check ('G04 frozen by the brief and byte-identical to HEAD: Current sender, Caller, both Bridges, the Handshake protocol, the shared telemetry contract, the Python reader / HUD / scoring / managed mode (Python production code has NO Legacy or holding speed branch), the Legacy session (' + $changedFrozen.Count + ' changed) ' + ($changedFrozen -join ',')) ($changedFrozen.Count -eq 0)
$probeDiff = RunGit @('-C', $top, 'diff', '-U0', 'HEAD', '--', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputProbe.cs')
$probePlus = @($probeDiff -split "`n" | Where-Object { $_ -match '^\+[^+]' }); $probeMinus = @($probeDiff -split "`n" | Where-Object { $_ -match '^-[^-]' })
Check 'G05 LegacyInputProbe.cs (the LI0 observation) changed only by the snapshot member HoldingSpeedNotchCount (a comment line of HasHoldingSpeedBrake) and, after the LI2 retest, the diagnostic words appended to the static part of TEL_HANDLE_FIRST (holdN, holdBrake, holdSource, holdValidity): no observation logic, no new line, no new event' (($probePlus.Count -eq 5) -and ($probeMinus.Count -eq 2) -and (@($probePlus | Where-Object { $_ -match 'HoldingSpeedNotchCount|HasHoldingSpeedBrake|holdN=|holdSource|holdValidity|b67=' }).Count -eq 5) -and (@($probeMinus | Where-Object { $_ -match 'HasHoldingSpeedBrake|b67=' }).Count -eq 2))
$extDiff = RunGit @('-C', $top, 'diff', '-U0', 'HEAD', '--', 'TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs')
$extPlus = @($extDiff -split "`n" | Where-Object { $_ -match '^\+[^+]' }); $extMinus = @($extDiff -split "`n" | Where-Object { $_ -match '^-[^-]' })
Check 'G06 LegacyTelemetryExtension.cs (the host adapter) changed by exactly ONE added line: the public read of NotchInfo.HoldingSpeedNotchCount into the snapshot (no other host member, no new API, no thread)' (($extPlus.Count -eq 1) -and ($extMinus.Count -eq 0) -and ($extPlus[0] -match 'HoldingSpeedNotchCount = info\.HoldingSpeedNotchCount'))
$csprojDiff = RunGit @('-C', $top, 'diff', '--name-only', 'HEAD', '--', 'TsScoringPlugin/Handshake/Telemetry/Legacy/TSScoringPlugin.AtsExLegacy.Telemetry.csproj')
Check 'G07 the project file is unchanged (no new source, no new reference)' ($csprojDiff -eq '')
$changed = @((RunGit @('-C', $top, 'diff', '--name-only', 'HEAD')) -split "`n" | Where-Object { $_ })
$untracked = @((RunGit @('-C', $top, 'ls-files', '--others', '--exclude-standard')) -split "`n" | Where-Object { $_ })
$touched = @($changed + $untracked | Sort-Object -Unique)
$allowed = @($touched | Where-Object { $_ -match '^TsScoringPlugin/Handshake/(Telemetry/Legacy/src/|Tests/|Tools/|Docs/Handshake-PhaseLI[12]|Docs/Handshake-PhaseL3-LegacyTelemetry\.md)|^tests/(test_legacy_input_li[12]|legacy_input_reference)\.py$|^tests/legacy_input_matrix24\.json$' })
$outside = @($touched | Where-Object { $_ -notin $allowed })
Check ('G08 scope: only the Legacy telemetry sources, tests, verifiers and the LI1 / LI2 documents changed (' + $touched.Count + ' files; outside: ' + ($outside -join ',') + ')') ($outside.Count -eq 0)
$newBinary = @($untracked | Where-Object { $_ -match '\.(dll|pdb|log|exe|zip)$' })
Check 'G09 no DLL, PDB, log, executable or archive is added to Git by this phase (generated output stays ignored)' ($newBinary.Count -eq 0)
$priv = @()
foreach ($f in @('Telemetry\Legacy\src\LegacyHandleContract.cs', 'Telemetry\Legacy\src\LegacyInputTelemetry.cs', 'Tests\Test-LegacyInputLI2.ps1')) { $priv += @(Get-Item (Join-Path $Root $f)) }
$priv += @(Get-Item (Join-Path $repo 'tests\test_legacy_input_li2.py'), (Get-Item (Join-Path $repo 'tests\legacy_input_reference.py')))
$docs = Join-Path $Root 'Docs\Handshake-PhaseLI2-LegacyHoldingSpeedAndOneLeverCl.md'
if (Test-Path $docs) { $priv += @(Get-Item $docs) }
$privText = ($priv | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"
Check 'G10 no personal path, user name or e-mail address in the new and changed files' (($privText -notmatch '[A-Za-z]:\\Users\\[A-Za-z]') -and ($privText -notmatch ('@' + 'gmail|@' + 'users\.noreply')) -and ($privText -notmatch 'C:\\Users\\'))
Check 'G11 not implemented in this phase (comment-only mentions at most): bp_initial, the Smee virtual EB, scoring, P-to-P handling, vehicle files' (($hcCode + $itCode) -notmatch 'bp_initial|VirtualEb|virtual_eb|add_score|is_scoring_mode|P2P|ReadAllText|File\.Open')

# ---------------------------------------------------------------------------------------------------------------------------------------------
$fail = @($results | Where-Object { -not $_.Ok }).Count
$pass = @($results | Where-Object { $_.Ok }).Count
"LEGACY-INPUT-LI2 PASS=$pass FAIL=$fail SKIP=$($script:skips)"
if ($fail -gt 0) { exit 1 } else { exit 0 }
