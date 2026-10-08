# PHASE B - read-only verification of the built Caller and Bridge DLLs (reflection-only load, nothing executed).
param([string]$Root = (Split-Path $PSScriptRoot -Parent))

$handler = [ResolveEventHandler]{
    param($s, $e)
    $name = ($e.Name -split ',')[0]
    $an = New-Object Reflection.AssemblyName($e.Name)
    if ($an.Version -and $an.Version.Major -eq 2 -and $name -in @('mscorlib', 'System', 'System.Windows.Forms', 'System.Drawing')) {
        $token = ($an.GetPublicKeyToken() | ForEach-Object { $_.ToString('x2') }) -join ''
        return [Reflection.Assembly]::ReflectionOnlyLoad("$name, Version=4.0.0.0, Culture=neutral, PublicKeyToken=$token")
    }
    foreach ($dir in @((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), (Join-Path $env:PUBLIC 'Documents\BveEx\2.0'), (Join-Path $env:PUBLIC 'Documents\BveEx'))) {
        foreach ($ext in '.dll', '.DLL') {
            $p = Join-Path $dir ($name + $ext)
            if (Test-Path $p) { return [Reflection.Assembly]::ReflectionOnlyLoadFrom($p) }
        }
    }
    return [Reflection.Assembly]::ReflectionOnlyLoad($e.Name)
}
[AppDomain]::CurrentDomain.add_ReflectionOnlyAssemblyResolve($handler)

function Inspect([string]$dll, [string[]]$mustBeAbsent) {
    Write-Host ("==== " + (Split-Path $dll -Leaf) + " ====")
    $item = Get-Item $dll
    "size   : {0} bytes" -f $item.Length
    "sha256 : " + (Get-FileHash $dll -Algorithm SHA256).Hash
    $v = $item.VersionInfo
    "version resource: FileDescription='{0}' ProductName='{1}' CompanyName='{2}' LegalCopyright='{3}' Comments='{4}' FileVersion={5} ProductVersion={6}" -f $v.FileDescription, $v.ProductName, $v.CompanyName, $v.LegalCopyright, $v.Comments, $v.FileVersion, $v.ProductVersion

    $asm = [Reflection.Assembly]::ReflectionOnlyLoadFrom($dll)
    $kind = [Reflection.PortableExecutableKinds]0
    $machine = [Reflection.ImageFileMachine]::I386
    $asm.ManifestModule.GetPEKind([ref]$kind, [ref]$machine)
    "PE     : $kind / $machine  (ILOnly + I386 without Required32Bit/Preferred32Bit = AnyCPU)"
    foreach ($ca in [Reflection.CustomAttributeData]::GetCustomAttributes($asm)) {
        if ($ca.AttributeType.Name -like '*TargetFramework*') { "target : " + $ca.ToString() }
    }
    "references: " + (($asm.GetReferencedAssemblies() | ForEach-Object { $_.Name + ' ' + $_.Version }) -join '; ')

    $flags = [Reflection.BindingFlags]'Public,NonPublic,Instance,Static,DeclaredOnly'
    try { $types = $asm.GetTypes() } catch [Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ }; "(partial type load: " + $_.Exception.LoaderExceptions.Count + " loader exception(s))" }
    foreach ($t in $types) {
        $ctors = $t.GetConstructors([Reflection.BindingFlags]'Public,NonPublic,Instance') | ForEach-Object {
            $vis = if ($_.IsPublic) { 'public' } else { 'nonpublic' }
            "$vis(" + (($_.GetParameters() | ForEach-Object { $_.ParameterType.Name }) -join ',') + ")"
        }
        $attrs = ([Reflection.CustomAttributeData]::GetCustomAttributes($t) | Where-Object { $_.AttributeType.Name -notmatch 'CompilerGenerated' } | ForEach-Object { $_.ToString() }) -join ' '
        "type {0} | public={1} | base={2} | interfaces=[{3}] | ctors=[{4}] {5}" -f $t.FullName, $t.IsPublic, $(if ($t.BaseType) { $t.BaseType.Name } else { '' }), (($t.GetInterfaces() | ForEach-Object { $_.Name }) -join ','), ($ctors -join ' '), $attrs
        foreach ($m in $t.GetMethods($flags)) {
            if (($m.Attributes -band [Reflection.MethodAttributes]::PinvokeImpl) -ne 0) { "   P/Invoke: " + $t.Name + "." + $m.Name }
        }
    }

    $bytes = [IO.File]::ReadAllBytes($dll)
    $ascii = [Text.Encoding]::ASCII.GetString($bytes)
    $utf16 = [Text.Encoding]::Unicode.GetString($bytes)
    $utf16b = [Text.Encoding]::Unicode.GetString($bytes, 1, $bytes.Length - 1 - (($bytes.Length - 1) % 2))
    $present = @()
    foreach ($tok in $mustBeAbsent) {
        $c = ([regex]::Matches($ascii, [regex]::Escape($tok))).Count + ([regex]::Matches($utf16, [regex]::Escape($tok))).Count + ([regex]::Matches($utf16b, [regex]::Escape($tok))).Count
        if ($c -gt 0) { $present += ($tok + ' x' + $c) }
    }
    "forbidden tokens searched: " + $mustBeAbsent.Count + "  present: " + $(if ($present.Count -eq 0) { 'none' } else { $present -join ', ' })
    "System namespaces referenced: " + (([regex]::Matches($ascii, 'System(\.[A-Za-z]+)+') | ForEach-Object { $_.Value } | Sort-Object -Unique) -join ', ')
}

$common = 'AtsLogger', 'AtsEx', 'Python', 'python', 'UdpClient', 'Sockets', 'System.Net', 'TcpClient', 'HttpClient', 'WebClient', 'Registry', 'Microsoft.Win32', 'FileStream', 'StreamWriter', 'StreamReader', 'WriteAllText', 'AppendAllText', 'ReadAllText', 'File.', 'Preferences', 'InputPlugins', 'SetWindowsHookEx', 'keyboard', 'BveDllInventory', 'RuntimeProfile', 'SHA256', 'HashAlgorithm', 'FindWindow', 'SetWindowLong', 'NamedPipe', 'Global\'
$callerAbsent = $common + @('BveEx.', 'BveEX.', 'BveTypes', 'PluginHost', 'Launcher')   # the user-visible notice text mentions BveEX in prose only
$bridgeAbsent = $common + @('Sleep', 'System.Threading.Timer', 'System.Timers', 'MessageBox', 'user32', 'DllImport', 'GetMethod', 'GetProperty', 'GetField', 'Activator', 'GetTypes', 'BindingFlags', 'System.Reflection.Emit', 'Class1', 'AtsLoggerPlugin')

$dist = Join-Path $Root 'dist'
Inspect (Join-Path $dist 'TSScoringPlugin.Caller.InputDevice.dll') $callerAbsent
Inspect (Join-Path $dist 'TSScoringPlugin.BveEx.Bridge.Prototype.dll') $bridgeAbsent

Write-Host '==== source checks ===='
$src = Get-ChildItem $Root -Recurse -Include *.cs | Where-Object { $_.FullName -notlike '*\obj\*' }
foreach ($pattern in 'Thread.Sleep', 'MessageBoxW', 'EventWaitHandle', 'TryOpenExisting', 'MemoryMappedFile', 'Global\\', '\bFile\.', 'Registry', 'UdpClient', 'Process\.Start') {
    $hits = $src | Select-String -Pattern $pattern | Where-Object { $_.Line.TrimStart() -notmatch '^//' }
    "{0,-18} {1}" -f $pattern, (($hits | ForEach-Object { $_.Path.Substring($Root.Length + 1) + ':' + $_.LineNumber }) -join ', ')
}
