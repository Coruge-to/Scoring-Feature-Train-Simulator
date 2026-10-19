# PHASE PID-D4 / LEGACY JUMP 2A-ALPHA (Stage S1, tests first) - serves ONE product Legacy Jump plane to an external process (the Python interop test).
#
# What it does: compiles the 2A-alpha test sources (Tests\LegacyJumpPlaneTestKit.cs, LegacyJumpPlaneTestFixture.cs, LegacyIlCallScan.cs) against a COPY of the product DLL,
# opens one plane of the product on a synthetic BVE PID with the production seams (a real named mapping, a real loopback UDP port, the dedicated worker), and then obeys
# commands that the Python test drops into the control directory as files:
#     cmd-<n>.txt  containing one word:  status | cycle | cycle-nowait | await-ready | arm-fault | finish
#     reply-<n>.json                      the answer (the plane's status as JSON, or {"ok":true})
#     ready.json                          written once the plane is READY;  error.json = the start failed (product absent => exit code 3, anything else => 4)
# A command is answered once; commands are taken in file-name order. The script ends on `finish` (or after -TimeoutSec) and disposes the plane in every case.
#
# No BVE, no AtsEX runtime. The only operating system objects are the named mapping of an unused high synthetic PID and loopback sockets of the plane; the fixed UDP ports
# 54321 / 54322 are never bound and never written to. The product DLL is only COPIED (never modified, never deployed). ASCII-only on purpose. Windows PowerShell 5.1.
param(
    [Parameter(Mandatory = $true)][string]$ControlDir,
    [string]$ProductDll = '',
    [int]$BvePid = 0,
    [int]$TimeoutSec = 180,
    [string]$RunId = ('serve' + (Get-Date -Format 'HHmmss'))
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path $here -Parent
$legacyHost = Join-Path $env:PUBLIC 'Documents\BveEx\Legacy'
if ([string]::IsNullOrEmpty($ProductDll)) { $ProductDll = Join-Path $root 'Telemetry\Legacy\out\TSScoringPlugin.AtsExLegacy.Telemetry.dll' }
New-Item -ItemType Directory -Force $ControlDir | Out-Null

function WriteJson([string]$name, [string]$text) {
    $tmp = Join-Path $ControlDir ($name + '.tmp')
    [IO.File]::WriteAllText($tmp, $text, (New-Object Text.UTF8Encoding($false)))
    $dst = Join-Path $ControlDir $name
    if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Force }
    Move-Item -LiteralPath $tmp -Destination $dst
}

$session = $null
$exit = 0
try {
    $work = Join-Path $ControlDir 'work'
    New-Item -ItemType Directory -Force $work | Out-Null
    $prodCopy = Join-Path $work (Split-Path $ProductDll -Leaf)
    Copy-Item -LiteralPath $ProductDll -Destination $prodCopy -Force
    $fixDll = Join-Path $work 'TsScoringLegacyTelemetryTests.dll'
    $sources = @((Join-Path $here 'LegacyJumpPlaneTestKit.cs'), (Join-Path $here 'LegacyJumpPlaneTestFixture.cs'), (Join-Path $here 'LegacyIlCallScan.cs'))
    Add-Type -Path $sources -ReferencedAssemblies @($prodCopy, 'System.dll', 'System.Core.dll') -OutputAssembly $fixDll -OutputType Library -IgnoreWarnings
    Add-Type -TypeDefinition @"
using System;
using System.IO;
using System.Reflection;
public static class ServeResolver
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
    [ServeResolver]::Install(@($work, $legacyHost))
    $prod = [Reflection.Assembly]::LoadFrom($prodCopy)
    $fix = [Reflection.Assembly]::LoadFrom($fixDll)
    $serveType = $fix.GetType('TsScoringLegacyTelemetryTests.ServeSession')
    try {
        $session = $serveType.GetMethod('Open').Invoke($null, @($prod, $RunId, $BvePid))
    }
    catch {
        $full = $_.Exception.ToString()
        $absent = $full.Contains('product-absent:')
        $code = ''
        if ($absent) { $code = [regex]::Match($full, 'product-absent:([^\r\n ]+)').Groups[1].Value }
        WriteJson 'error.json' ('{"kind":"' + $(if ($absent) { 'product-absent' } else { 'start-failed' }) + '","code":"' + ($code -replace '[\\"]', ' ') + '","text":"' + (($full -replace '[\\"]', ' ' -replace "[\r\n]+", ' ')) + '"}')
        if ($absent) { $exit = 3 } else { $exit = 4 }
        exit $exit
    }
    WriteJson 'ready.json' $session.Status()
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    $done = @{}
    $finished = $false
    while (-not $finished -and [DateTime]::UtcNow -lt $deadline) {
        $cmds = @(Get-ChildItem -LiteralPath $ControlDir -Filter 'cmd-*.txt' -File | Sort-Object Name)
        foreach ($c in $cmds) {
            if ($done.ContainsKey($c.Name)) { continue }
            $word = $null
            try { $word = ([IO.File]::ReadAllText($c.FullName)).Trim() } catch { $word = $null }      # a scanner may hold the new file for a moment: try again on the next round
            if ([string]::IsNullOrEmpty($word)) { continue }
            $n = $c.BaseName.Substring(4)
            $reply = '{"ok":true}'
            try {
                switch ($word) {
                    'status' { $reply = $session.Status() }
                    'cycle' { $reply = $session.Cycle() }
                    'cycle-nowait' { $reply = $session.CycleNoWait(700) }
                    'await-ready' { $reply = $session.AwaitReady(5000) }
                    'arm-fault' { $session.ArmReceiveFault() }
                    'finish' { $reply = $session.Finish(); $finished = $true }
                    default { $reply = '{"ok":false,"error":"unknown command"}' }
                }
            }
            catch { $reply = '{"ok":false,"error":"' + ($_.Exception.GetType().Name) + '"}' }
            WriteJson ('reply-' + $n + '.json') $reply
            $done[$c.Name] = $true
            if ($finished) { break }
        }
        Start-Sleep -Milliseconds 15
    }
}
catch {
    WriteJson 'error.json' ('{"kind":"script","type":"' + $_.Exception.GetType().Name + '","text":"' + (($_.Exception.ToString() -replace '[\\"]', ' ' -replace "[\r\n]+", ' ')) + '"}')
    $exit = 4
}
finally {
    if ($null -ne $session) { try { $session.Dispose() } catch { } }
}
exit $exit
