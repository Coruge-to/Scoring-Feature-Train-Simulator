# TEST HARNESS helper (not part of the product): "is the user's own TS Scoring main.py running right now?"
#
# The live-chain sections of the E3 / E4 / L3-integration tests start the REAL main.py --managed and bind UDP 54321, so they must not run while the user's own
# TS Scoring is up. They used to ask "is ANY python process running a file called main.py?", which also matched an unrelated application that happens to use the
# same file name (another project's main.py) and skipped the live chain for nothing.
#
# The question is now asked about the one real path: <repo>\main.py (the script the tests would start). A command line counts only when one of its tokens IS that
# path (full path, case-insensitive, either slash). A token that names some other full path is another program. A token that is only a RELATIVE main.py cannot be
# placed (its working folder is unknown) and counts as a match: the safe side. Windows PowerShell 5.1, ASCII only.

function Split-TsCommandLine([string]$CommandLine) {
    $tokens = New-Object System.Collections.Generic.List[string]
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return @() }
    foreach ($m in [regex]::Matches($CommandLine, '"([^"]*)"|(\S+)')) {
        if ($m.Groups[1].Success) { $tokens.Add($m.Groups[1].Value) } else { $tokens.Add($m.Groups[2].Value) }
    }
    return $tokens.ToArray()
}

# One command line against the real main.py path: 'match' (it runs THAT file), 'ambiguous' (a relative main.py: unknown folder), 'other' (some other file or no main.py at all).
function Get-TsMainPyVerdict([string]$CommandLine, [string]$MainPy) {
    $want = [IO.Path]::GetFullPath($MainPy).Replace('/', '\')
    $verdict = 'other'
    foreach ($t in (Split-TsCommandLine $CommandLine)) {
        $norm = $t.Replace('/', '\')
        if ($norm -notmatch '(^|\\)main\.py$') { continue }
        $rooted = $false
        try { $rooted = [IO.Path]::IsPathRooted($norm) -and ($norm -match '^[A-Za-z]:\\|^\\\\') } catch { $rooted = $false }
        if ($rooted) {
            $full = $norm
            try { $full = [IO.Path]::GetFullPath($norm) } catch { }
            if ([string]::Equals($full, $want, [StringComparison]::OrdinalIgnoreCase)) { return 'match' }
        }
        else { $verdict = 'ambiguous' }
    }
    return $verdict
}

# True when a python / pythonw process runs <repo>\main.py or cannot be told apart from it. When the process list cannot be read at all: True (the safe side).
function Get-TsScoringMainRunning([string]$MainPy) {
    try {
        $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop)
    }
    catch { return $true }
    foreach ($p in $procs) {
        if ((Get-TsMainPyVerdict ([string]$p.CommandLine) $MainPy) -ne 'other') { return $true }
    }
    return $false
}
