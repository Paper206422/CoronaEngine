param(
    [ValidateSet('Debug', 'Release', 'RelWithDebInfo', 'MinSizeRel')]
    [string]$Configuration = 'RelWithDebInfo',

    [string]$BuildTarget = 'corona_engine',

    [string]$BuildDir = 'cmake-build-relwithdebinfo',

    [switch]$SkipConfigure
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir '..\..')).Path
$buildDir = Join-Path $projectRoot $BuildDir

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) {
    $vswhere = Join-Path $env:ProgramFiles 'Microsoft Visual Studio\Installer\vswhere.exe'
}
if (-not (Test-Path $vswhere)) {
    throw 'vswhere.exe not found.'
}

$vsInstall = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsInstall) {
    throw 'Visual Studio installation with MSVC tools not found.'
}

$devShellModule = Join-Path $vsInstall 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll'
if (-not (Test-Path $devShellModule)) {
    throw "Visual Studio DevShell module not found: $devShellModule"
}

$clionExe = Get-Command clion64.exe -ErrorAction SilentlyContinue
if (-not $clionExe) {
    $clionRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LocalAppData) |
        Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $clionRoots) {
        $candidate = Get-ChildItem -Path $root -Filter clion64.exe -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($candidate) {
            $clionExe = $candidate
            break
        }
    }
}
if (-not $clionExe) {
    throw 'CLion executable not found. Install CLion or add clion64.exe to PATH.'
}

$clionPath = if ($clionExe.PSObject.Properties.Name -contains 'Source') {
    $clionExe.Source
} else {
    $clionExe.FullName
}
$clionBin = Split-Path -Parent $clionPath
$ninjaPath = Join-Path $clionBin 'ninja\win\x64\ninja.exe'
$cmakePath = Join-Path $clionBin 'cmake\win\x64\bin\cmake.exe'
if (-not (Test-Path $ninjaPath)) {
    throw "CLion bundled ninja not found: $ninjaPath"
}
if (-not (Test-Path $cmakePath)) {
    throw "CLion bundled cmake not found: $cmakePath"
}

$toolRoot = Join-Path $vsInstall 'VC\Tools\MSVC'
$linkerPath = Get-ChildItem -Path $toolRoot -Filter link.exe -Recurse |
    Where-Object { $_.FullName -like '*Hostx64\x64\link.exe' } |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $linkerPath) {
    throw 'MSVC link.exe not found.'
}

$libPath = Get-ChildItem -Path $toolRoot -Filter lib.exe -Recurse |
    Where-Object { $_.FullName -like '*Hostx64\x64\lib.exe' } |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $libPath) {
    throw 'MSVC lib.exe not found.'
}

Import-Module $devShellModule
Enter-VsDevShell -VsInstallPath $vsInstall -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
Set-Location $projectRoot

if (-not $SkipConfigure) {
    $configureArgs = @(
        '-S', $projectRoot,
        '-B', $buildDir,
        '-G', 'Ninja',
        "-DCMAKE_BUILD_TYPE=$Configuration",
        '-DCMAKE_C_COMPILER=cl',
        '-DCMAKE_CXX_COMPILER=cl',
        "-DCMAKE_MAKE_PROGRAM=$ninjaPath",
        "-DCMAKE_LINKER=$linkerPath",
        "-DCMAKE_AR=$libPath",
        '-DCMAKE_RANLIB=:'
    )
    & $cmakePath @configureArgs
}

$buildArgs = @(
    '--build',
    $buildDir,
    '--target', $BuildTarget
)
& $cmakePath @buildArgs