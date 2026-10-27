# Checks Maku's install hooks (hooks.nsh): an update replaces the engine whole, a stopped install
# puts the old one back, and a running engine is dealt with. Builds hooks-test.nsi with the NSIS
# that `pnpm build:installer` downloads, and installs into app/src-tauri/target/hooks-test.
# Run it after changing hooks.nsh or upgrading Tauri: powershell -File windows/hooks-test.ps1
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$makensis = Join-Path $env:LOCALAPPDATA 'tauri\NSIS\makensis.exe'
if (-not (Test-Path $makensis)) { throw "No NSIS at ${makensis}; run pnpm build:installer once first." }
$work = Join-Path (Split-Path $here) 'target\hooks-test'
$inst = Join-Path $work 'inst'
$failed = 0

function Build([string]$name, [switch]$Stop) {
    $out = Join-Path $work "$name.exe"
    $arguments = @('/V2', "/DHOOKS=$here\hooks.nsh", "/DOUT=$out", "/DDIR=$inst")
    if ($Stop) { $arguments += '/DSTOP' }
    $arguments += (Join-Path $here 'hooks-test.nsi')
    $said = & $makensis @arguments 2>&1
    if ($LASTEXITCODE -ne 0) { $said | Out-Host; throw "makensis couldn't build $name" }
    $out
}

function Old-Engine {
    if (Test-Path $inst) { Remove-Item $inst -Recurse -Force }
    foreach ($version in '0.1.0', '0.2.0') {
        $record = "$inst\engine\_internal\maku-$version.dist-info"
        New-Item -ItemType Directory -Force $record | Out-Null
        Set-Content "$record\METADATA" "Version: $version"
    }
    # A program to stand in for a running engine.
    Copy-Item "$env:WINDIR\System32\PING.EXE" "$inst\engine\maku-engine.exe"
}

function Install([string]$exe) { (Start-Process $exe -Wait -PassThru).ExitCode }

function Listing {
    if (-not (Test-Path $inst)) { return '' }
    (Get-ChildItem $inst -Recurse -Name | ForEach-Object { $_ -replace '\\', '/' } | Sort-Object) -join ' | '
}

function Expect([string]$case, [string]$got, [string]$want) {
    if ($got -eq $want) { "PASS $case" }
    else { "FAIL $case`n  got:  $got`n  want: $want"; $script:failed++ }
}

New-Item -ItemType Directory -Force $work | Out-Null
$install = Build 'install'
$stopping = Build 'stopping' -Stop
$new = 'engine | engine/_internal | engine/_internal/maku-0.3.0.dist-info | engine/_internal/maku-0.3.0.dist-info/METADATA | engine/new-engine.txt'
$old = 'engine | engine/_internal | engine/_internal/maku-0.1.0.dist-info | engine/_internal/maku-0.1.0.dist-info/METADATA | engine/_internal/maku-0.2.0.dist-info | engine/_internal/maku-0.2.0.dist-info/METADATA | engine/maku-engine.exe'

Old-Engine
$code = Install $install
Expect "an update replaces the engine whole (exit $code)" (Listing) $new

Remove-Item $inst -Recurse -Force
$code = Install $install
Expect "a first install (exit $code)" (Listing) $new

Old-Engine
New-Item -ItemType Directory -Force "$inst\engine-old\_internal" | Out-Null
Set-Content "$inst\engine-old\_internal\left.txt" 'left'
$code = Install $install
Expect "what an earlier install left goes first (exit $code)" (Listing) $new

Old-Engine
$code = Install $stopping
Expect "a stopped install puts the old engine back (exit $code)" (Listing) $old

Old-Engine
$running = Start-Process "$inst\engine\maku-engine.exe" -ArgumentList '-n', '30', '127.0.0.1' -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 500
$code = Install $install
Stop-Process -Id $running.Id -Force
$running.WaitForExit()
Expect "a running engine is set aside, keeping only what it holds (exit $code)" (Listing) "$new | engine-old | engine-old/maku-engine.exe"
$code = Install $install
Expect "the next install clears that (exit $code)" (Listing) $new

Old-Engine
$running = Start-Process "$inst\engine\maku-engine.exe" -ArgumentList '-n', '3', '127.0.0.1' -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 300
$code = Install $install
Expect "an engine stopping meanwhile is waited for (exit $code)" (Listing) $new

Remove-Item $work -Recurse -Force
if ($failed) { throw "$failed failed" }
'All passed.'
