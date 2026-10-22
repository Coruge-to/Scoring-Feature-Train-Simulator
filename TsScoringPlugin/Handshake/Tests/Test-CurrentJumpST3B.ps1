param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
# PHASE PID-D4JA StationIndex ST-3b - offline tests of the Current jump decision (CurrentJumpExecution.cs), of the grammar gate of the Current jump endpoint (ValidGrammar over the
# shared JumpWire.cs) and of the numbers the Current plugin writes. No BVE, no BveEX, no fixed port, no product build: the sources are compiled in memory by the same CodeDom
# route as Test-CurrentJumpD6.ps1 / Test-JumpWireST3A.ps1 (C# 5; CodeDom keeps its temporary files under %TEMP% and removes them; nothing is written to the repository).
# Class1.cs can not run offline: what it does around these functions is held by tests\test_stationindex_current_st3b.py (source pins) and judged live in ST-3e2.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$plugin = Join-Path $RepositoryRoot 'TsScoringPlugin'
$shared = Join-Path $plugin 'Handshake\Telemetry\Shared'
$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok) {
    if ($ok) { $script:pass++; Write-Host ('PASS ' + $name) } else { $script:fail++; Write-Host ('FAIL ' + $name) }
}
function Code([string]$path) {
    $t = [IO.File]::ReadAllText($path)
    $t = [regex]::Replace($t, '(?s)/\*.*?\*/', '')
    return ([regex]::Replace($t, '(?m)//.*$', ''))
}

Write-Host '--- A: compiled tests (CurrentJumpST3BTestFixture)'
$sources = @(
    (Join-Path $shared 'DataPlaneProtocol.cs'),
    (Join-Path $shared 'TelemetryDirectoryReader.cs'),
    (Join-Path $shared 'JumpWire.cs'),
    (Join-Path $plugin 'TsScoringPlugin\CurrentDataPlane.cs'),
    (Join-Path $plugin 'TsScoringPlugin\CurrentJumpEndpoint.cs'),
    (Join-Path $plugin 'TsScoringPlugin\CurrentJumpExecution.cs'),
    (Join-Path $plugin 'Handshake\Tests\CurrentJumpST3BTestFixture.cs')
)
Add-Type -Path $sources -ReferencedAssemblies @('System.dll', 'System.Core.dll')
$results = [CurrentJumpST3BTestFixture]::Run()
$checks = $results[0]
$bad = @($results | Select-Object -Skip 1)
Check ('A01 every compiled check passed (' + $checks + ')') ($bad.Count -eq 0)
foreach ($b in $bad) { Write-Host ('  FAILED: ' + $b) }

Write-Host '--- B: the pure unit stays pure (no host, no file, no socket, no clock, no thread, no mutable state, C# 5)'
$unitPath = Join-Path $plugin 'TsScoringPlugin\CurrentJumpExecution.cs'
$unit = Code $unitPath
Check 'B01 CurrentJumpExecution.cs names no BveEx / AtsEx / BveTypes / Legacy / Handshake type' (($unit -cnotmatch 'BveEx') -and ($unit -cnotmatch 'AtsEx') -and ($unit -cnotmatch 'BveTypes') -and ($unit -cnotmatch 'Legacy') -and ($unit -cnotmatch 'Handshake'))
Check 'B02 it uses no file, socket, process, thread, clock, random or environment API' (($unit -notmatch 'System\.IO') -and ($unit -notmatch 'System\.Net') -and ($unit -notmatch 'System\.Threading') -and ($unit -notmatch 'System\.Diagnostics') -and ($unit -notmatch '\bDateTime\b') -and ($unit -notmatch '\bEnvironment\b') -and ($unit -notmatch '\bRandom\b') -and ($unit -notmatch '\bStopwatch\b') -and ($unit -notmatch '\bThread\b') -and ($unit -notmatch '\bFile\b'))
$mutableStatics = @($unit -split "`n" | Where-Object { $_ -match '^\s*(internal|private|public)\s+static\s+' -and $_ -notmatch '\bstatic\s+(readonly|class)\b' -and $_ -notmatch '\(' })
Check 'B03 it has no mutable static state (every static field is const or readonly)' ($mutableStatics.Count -eq 0)
Check 'B04 it is written in C# 5 syntax (no string interpolation, ?., out var, expression bodies, nameof, pattern matching)' (($unit -notmatch '\$"') -and ($unit -notmatch '\?\.') -and ($unit -notmatch 'out\s+var\b') -and ($unit -notmatch '=>') -and ($unit -notmatch 'nameof\(') -and ($unit -notmatch '\bis\s+\w+\s+\w+\b'))
Check 'B05 it reads the wire only through the shared JumpWire (no Split, no TryParse, no Parse, no ToString("R") / default ToString of a double)' (($unit -notmatch '\.Split\(') -and ($unit -notmatch 'TryParse') -and ($unit -notmatch '\.Parse\(') -and ($unit -notmatch '"R"'))
$resolve = [regex]::Match($unit, '(?s)internal static int ResolveRequestedTarget\(.*?\n        \}')
Check 'B06 ResolveRequestedTarget takes no position and has no search (no Math, no loop, no 50, no vehicle location)' ($resolve.Success -and ($resolve.Value -notmatch 'Math\.') -and ($resolve.Value -notmatch '\bfor\b') -and ($resolve.Value -notmatch '\bforeach\b') -and ($resolve.Value -notmatch '\bwhile\b') -and ($resolve.Value -notmatch '50') -and ($resolve.Value -notmatch '(?i)vehicle'))
$judge = [regex]::Match($unit, '(?s)private static CurrentJumpDecision JudgeCore\(.*?\n        \}')
Check 'B07 the judgement has no loop and no search either (it compares the named index with the plugin''s own list and nothing else)' ($judge.Success -and ($judge.Value -notmatch '\bfor\b') -and ($judge.Value -notmatch '\bforeach\b') -and ($judge.Value -notmatch '\bwhile\b') -and ($judge.Value -notmatch 'Math\.') -and ($judge.Value -notmatch 'Array\.(IndexOf|BinarySearch|Find)'))

# G-RC-1 (Commit Prep): the diagnostic extraction of the refusal line is isolated from the decision. It is set once by Judge after the verdict and printed once by RefusedLine; no decision function names it, it does not call the reader.
$judgeFn = [regex]::Match($unit, '(?s)internal static CurrentJumpDecision Judge\(.*?\n        \}').Value
$refusedFn = [regex]::Match($unit, '(?s)internal static string RefusedLine\(.*?\n        \}').Value
$describeFn = [regex]::Match($unit, '(?s)internal static CurrentJumpDiagnostic Describe\(.*?(?=\n        internal static string IdText)').Value
$formatFn = [regex]::Match($unit, '(?s)internal static string FormatCompletion\(.*?\n        \}').Value
$stationFn = [regex]::Match($unit, '(?s)internal static string StationLocationText\(.*?\n        \}').Value
$decisionFns = $judge.Value + $resolve.Value + $formatFn + $stationFn
Check 'B08 the diagnostic is set in one place (Judge, after the verdict) and read in one place (RefusedLine); the judgement, the target, the completion and the station text never name it' (($judgeFn.Length -gt 0) -and ($refusedFn.Length -gt 0) -and ($formatFn.Length -gt 0) -and ($stationFn.Length -gt 0) -and ([regex]::Matches($unit, '\.Diagnostic\b').Count -eq 3) -and ([regex]::Matches($judgeFn, '\.Diagnostic\b').Count -eq 1) -and ([regex]::Matches($refusedFn, '\.Diagnostic\b').Count -eq 2) -and ($decisionFns -notmatch 'Diagnostic') -and ($decisionFns -notmatch 'Describe') -and ($decisionFns -notmatch 'Diag[A-Z]') -and ([regex]::Matches($unit, '\bDescribe\(').Count -eq 2))
Check 'B09 the extraction is not a second reader: it does not call the shared reader, the host, the plugin view beyond the list length, and it reads no value (no Parse, no Convert, no Split, no regular expression)' (($describeFn.Length -gt 0) -and ($describeFn -notmatch 'JumpWire\.(Parse|Format|Validate|Is)') -and ($describeFn -notmatch 'Parse') -and ($describeFn -notmatch 'Convert\.') -and ($describeFn -notmatch '\.Split\(') -and ($describeFn -notmatch 'Regex') -and ($describeFn -notmatch 'ListCount') -and ($describeFn -notmatch 'Locations\['))
Check 'B10 the refusal line prints every diagnostic value through the number guard (DiagNumber), and the judgement text is not printed (the line builder never takes the command text)' (([regex]::Matches($refusedFn, 'DiagNumber\(diag\.').Count -eq 3) -and ($refusedFn -notmatch '\btext\b') -and ($refusedFn -notmatch 'Substring') -and ($unit -match 'internal static string RefusedLine\(byte\[\] requestId, CurrentJumpDecision d, string reason, string detail\)'))

Write-Host '--- C: the Current-only unit is not part of the Legacy DLL, and the Legacy source set still compiles with the compile-only JumpWire link (G-PC-1, no BveEx / AtsEx part)'
$legacyProject = Join-Path $plugin 'Handshake\Telemetry\Legacy\TSScoringPlugin.AtsExLegacy.Telemetry.csproj'
$legacyDoc = New-Object System.Xml.XmlDocument
$legacyDoc.Load($legacyProject)
$legacyIncludes = @($legacyDoc.SelectNodes("//*[local-name()='Compile']") | ForEach-Object { $_.GetAttribute('Include') })
Check 'C01 the Legacy project does not compile CurrentJumpExecution.cs' (@($legacyIncludes | Where-Object { $_ -match 'CurrentJumpExecution' }).Count -eq 0)
$legacyDir = Split-Path $legacyProject -Parent
$legacyFiles = @($legacyIncludes | Where-Object { $_ -notmatch 'LegacyTelemetryExtension\.cs$' -and $_ -notmatch 'AssemblyInfo\.cs$' } | ForEach-Object { [IO.Path]::GetFullPath((Join-Path $legacyDir $_)) })
$legacyTexts = New-Object System.Collections.Generic.List[string]
foreach ($f in $legacyFiles) { $legacyTexts.Add([IO.File]::ReadAllText($f, [Text.Encoding]::UTF8)) }
Add-Type -AssemblyName Microsoft.CSharp
$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$cp = New-Object System.CodeDom.Compiler.CompilerParameters
$cp.GenerateInMemory = $true
$cp.TreatWarningsAsErrors = $false
foreach ($r in @('System.dll', 'System.Core.dll')) { $cp.ReferencedAssemblies.Add($r) | Out-Null }
$compiled = $provider.CompileAssemblyFromSource($cp, [string[]]$legacyTexts.ToArray())
$errorText = @()
if ($compiled.Errors.HasErrors) { foreach ($e in $compiled.Errors) { if (-not $e.IsWarning) { $errorText += ($e.ErrorNumber + ' line ' + $e.Line + ' ' + $e.ErrorText) } } }
Check ('C02 the ' + $legacyFiles.Count + ' sources of the Legacy project that need no AtsEx (the files its project compiles, JumpWire.cs included) compile together in memory') ($errorText.Count -eq 0)
foreach ($e in ($errorText | Select-Object -First 5)) { Write-Host ('  compile error: ' + $e) }
Check 'C03 the shared sources are present once each in that set (no duplicate file)' ($legacyFiles.Count -eq @($legacyFiles | Select-Object -Unique).Count)

# Plan A for G-3B-2 (review of ST-3b): the Legacy plane keeps the grammar of before ST-3b. The IL of the compiled Legacy set shows who builds the validator: the Legacy plane (LegacyJumpEndpoint.Open) with the FIVE argument
# constructor (the old three field gate), and only the shared CurrentJumpEndpoint.Create with the SIX argument one (the shared JumpWire gate). A scan of the opcode 'newobj' (0x73) with the token resolved; a byte that only looks like it fails to resolve and is skipped.
$memberFlags = [Reflection.BindingFlags]'Instance,Static,Public,NonPublic,DeclaredOnly'
$ctorCalls = New-Object System.Collections.Generic.List[string]
if (-not $compiled.Errors.HasErrors) {
    foreach ($type in $compiled.CompiledAssembly.GetTypes()) {
        $members = @($type.GetMethods($memberFlags)) + @($type.GetConstructors($memberFlags))
        foreach ($member in $members) {
            $body = $member.GetMethodBody()
            if ($null -eq $body) { continue }
            $il = $body.GetILAsByteArray()
            for ($i = 0; $i -lt ($il.Length - 4); $i++) {
                if ($il[$i] -ne 0x73) { continue }
                $target = $null
                try { $target = $member.Module.ResolveMethod([BitConverter]::ToInt32($il, $i + 1)) } catch { $target = $null }
                if ($null -ne $target -and $target.IsConstructor -and $target.DeclaringType.Name -ceq 'JumpCommandValidator') { $ctorCalls.Add($type.Name + '.' + $member.Name + '->' + $target.GetParameters().Count) }
            }
        }
    }
}
$ctorCallText = (($ctorCalls | Sort-Object -Unique) -join ' ')
Check ('C04 the Legacy plane builds the validator with the five argument constructor (the grammar of before ST-3b) and only the shared Current endpoint builds the six argument one: ' + $ctorCallText) ($ctorCallText -ceq 'CurrentJumpEndpoint.Create->6 LegacyJumpEndpoint.Open->5')

Write-Host ''
Write-Host ('PASS=' + $script:pass + ' FAIL=' + $script:fail)
if ($script:fail -ne 0) { exit 1 }
Write-Host 'ST-3b Current jump offline tests passed.'
