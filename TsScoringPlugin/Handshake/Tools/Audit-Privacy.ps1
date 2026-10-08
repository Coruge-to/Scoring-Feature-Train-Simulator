# PHASE B - privacy audit. NOT part of any distribution candidate (it holds the forbidden-string list).
# Prints COUNTS ONLY. Read-only.
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

# No personal name is written in this script: the account / machine / profile-folder names of the machine running the audit are read at run time.
$runtimeNames = @($env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN, (Split-Path $env:USERPROFILE -Leaf)) | Where-Object { $_ -and $_.Length -ge 3 } | Sort-Object -Unique
$forbidden = @($runtimeNames) + @(
    'C:\Users\', 'Scoring-Feature-Train-Simulator',
    'TSScoringPlugin-Handshake-Prototype', 'TSScoringPlugin-Caller-Prototype',
    'gmail', 'hotmail', 'outlook.com', 'ac.jp'
)
$emailPattern = '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'

function Count-InBytes([byte[]]$bytes) {
    $ascii = [Text.Encoding]::ASCII.GetString($bytes)
    $utf16 = [Text.Encoding]::Unicode.GetString($bytes)
    $utf16b = if ($bytes.Length -gt 1) { [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2)) } else { '' }
    $utf8 = [Text.Encoding]::UTF8.GetString($bytes)
    $total = 0
    foreach ($tok in $forbidden) {
        $e = [regex]::Escape($tok)
        foreach ($text in @($ascii, $utf16, $utf16b, $utf8)) {
            $total += ([regex]::Matches($text, $e, 'IgnoreCase')).Count
        }
    }
    foreach ($text in @($ascii, $utf16, $utf16b, $utf8)) {
        $total += ([regex]::Matches($text, $emailPattern)).Count
    }
    return $total
}

function Audit-Group([string]$label, [object[]]$files) {
    $hits = 0
    $filesWithHits = 0
    foreach ($f in $files) {
        $c = Count-InBytes ([IO.File]::ReadAllBytes($f.FullName))
        $nameC = 0
        foreach ($tok in $forbidden) { if ($f.Name -like ('*' + $tok + '*')) { $nameC++ } }
        if (($c + $nameC) -gt 0) { $filesWithHits++ }
        $hits += $c + $nameC
    }
    "{0,-46} files={1,3}  filesWithHits={2,3}  matches={3}" -f $label, $files.Count, $filesWithHits, $hits
}

$tools = Join-Path $Root 'Tools'
$tests = Join-Path $Root 'Tests'
$all = Get-ChildItem $Root -Recurse -File | Where-Object { ($_.FullName -notlike ($tools + '*')) -and ($_.FullName -notlike ($tests + '*')) }

Write-Host '== PUBLIC CANDIDATES (expected: 0 matches) =='
Audit-Group 'dist\ (distribution candidates)'            @($all | Where-Object { $_.FullName -like (Join-Path $Root 'dist\*') })
Audit-Group 'Caller\out (Caller build output)'            @($all | Where-Object { $_.FullName -like (Join-Path $Root 'Caller\out\*') })
Audit-Group 'Bridge\out (Bridge build output)'            @($all | Where-Object { $_.FullName -like (Join-Path $Root 'Bridge\out\*') })
Audit-Group 'sources (*.cs, *.csproj, Shared)'            @($all | Where-Object { $_.Extension -in '.cs', '.csproj' -and $_.FullName -notlike '*\obj\*' })
Audit-Group 'documents (README)'                          @($all | Where-Object { $_.Extension -in '.md', '.txt' -and $_.FullName -notlike '*\obj\*' })

Write-Host '== NOT candidates (build intermediates / logs; local paths are expected here) =='
Audit-Group 'obj\ and build.log (not shipped)'            @($all | Where-Object { $_.FullName -like '*\obj\*' -or $_.Name -eq 'build.log' })

Write-Host '== candidate hygiene =='
$dist = Get-ChildItem (Join-Path $Root 'dist') -File -ErrorAction SilentlyContinue
"dist file count                : " + $dist.Count
"PDB files in dist              : " + @($dist | Where-Object { $_.Extension -eq '.pdb' }).Count
"non-DLL files in dist          : " + @($dist | Where-Object { $_.Extension -ne '.dll' }).Count
"third-party DLL names in dist  : " + @($dist | Where-Object { $_.Name -notlike 'TSScoringPlugin.*' }).Count
foreach ($d in ($dist | Where-Object { $_.Extension -eq '.dll' })) {
    $v = $d.VersionInfo
    "{0}: Company='{1}' Product='{2}' Description='{3}' Copyright='{4}' FileVersion={5}" -f $d.Name, $v.CompanyName, $v.ProductName, $v.FileDescription, $v.LegalCopyright, $v.FileVersion
    "   provider is Coruge-to: " + ($v.CompanyName -eq 'Coruge-to')
}

Write-Host '== human-facing product name (old name must not appear in human-facing text; counts) =='
$oldName = 'TSScoringPlugin'
$allowedInternal = @('Local\\TSScoringPlugin\.v1\.', 'TSScoringPlugin\.(Caller|BveEx|Handshake)[A-Za-z0-9_.]*', 'tsscoringplugin\.caller\.inputdevice', 'TSScoringPlugin\.v1', 'TSScoringPlugin\.Caller\.ReadyMonitor', 'TSScoringPlugin\.Caller\.Notice', 'TsScoringPlugin\.dll')   # the existing production-style DLL file name
function Count-OldName([string]$text) {
    $rest = $text
    foreach ($a in $allowedInternal) { $rest = [regex]::Replace($rest, $a, '', 'IgnoreCase') }
    return ([regex]::Matches($rest, [regex]::Escape($oldName), 'IgnoreCase')).Count
}
foreach ($d in (Get-ChildItem (Join-Path $Root 'dist') -Filter *.dll -File)) {
    $v = $d.VersionInfo
    $resourceHits = 0
    foreach ($field in @($v.ProductName, $v.FileDescription, $v.CompanyName, $v.Comments, $v.LegalCopyright, $v.FileVersion, $v.ProductVersion)) { if ($field -and $field -match $oldName) { $resourceHits++ } }
    $bytes = [IO.File]::ReadAllBytes($d.FullName)
    $u0 = [Text.Encoding]::Unicode.GetString($bytes)
    $u1 = [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2))
    $stringHits = (Count-OldName $u0) + (Count-OldName $u1)
    "{0,-46} version-resource fields with old name={1}  human/UI strings with old name={2}" -f $d.Name, $resourceHits, $stringHits
}
$docs = Get-ChildItem (Join-Path $Root 'Docs') -File | Where-Object { $_.Extension -eq '.md' }
foreach ($d in $docs) { "{0,-46} README outside DLL/protocol identifiers={1}" -f $d.Name, (Count-OldName ([IO.File]::ReadAllText($d.FullName, [Text.Encoding]::UTF8))) }

Write-Host '== old 2000 ms value (must not remain in sources, README or tools; counts) =='
$old2000 = 0
foreach ($f in (Get-ChildItem $Root -Recurse -File | Where-Object { $_.Extension -in '.cs', '.csproj', '.md', '.ps1' -and $_.FullName -notlike '*\obj\*' })) {
    if ($f.Name -eq 'Audit-Privacy.ps1') { continue }
    $old2000 += ([regex]::Matches([IO.File]::ReadAllText($f.FullName, [Text.Encoding]::UTF8), '\b2000\b')).Count
}
"occurrences of the old value: $old2000"
Write-Host '== old 1000 ms notice timeout (must not remain in sources, README or tools; counts) =='
$old1000 = 0
foreach ($f in (Get-ChildItem $Root -Recurse -File | Where-Object { $_.Extension -in '.cs', '.csproj', '.md', '.ps1' -and $_.FullName -notlike '*\obj\*' })) {
    if ($f.Name -eq 'Audit-Privacy.ps1') { continue }
    $old1000 += ([regex]::Matches([IO.File]::ReadAllText($f.FullName, [Text.Encoding]::UTF8), '\b1000\b(?![.\d])')).Count
}
"occurrences of the old value: $old1000"

Write-Host '== old notice wording (must not remain in DLLs, sources, README, tools; counts) =='
function FromCodes([string[]]$hex) { return -join ($hex | ForEach-Object { [char][Convert]::ToInt32($_, 16) }) }
$oldFragments = @(
    ('TS Scoring' + (FromCodes '3092', '4F7F', '7528', '3059', '308B', '306B', '306F')),      # old line 1 lead
    (FromCodes '5C0E', '5165', '3068', '6709', '52B9', '5316'),                              # old "introduction and activation"
    (FromCodes '300C', '8A2D', '5B9A', '300D', '2192', '300C'),                              # old bracketed menu path
    ((FromCodes '3067') + 'BveEX' + (FromCodes '3092', '6709', '52B9', '306B', '3057', '3066', '3001'))   # old "...enable BveEX and,"
)
$oldWording = 0
foreach ($f in (Get-ChildItem $Root -Recurse -File | Where-Object { $_.FullName -notlike '*\obj\*' -and $_.Name -ne 'build.log' -and $_.Name -ne 'Audit-Privacy.ps1' })) {
    $bytes = [IO.File]::ReadAllBytes($f.FullName)
    $texts = @([Text.Encoding]::UTF8.GetString($bytes), [Text.Encoding]::Unicode.GetString($bytes))
    if ($bytes.Length -gt 2) { $texts += [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2)) }
    foreach ($frag in $oldFragments) { foreach ($text in $texts) { $oldWording += ([regex]::Matches($text, [regex]::Escape($frag))).Count } }
}
"occurrences of the old wording: $oldWording"