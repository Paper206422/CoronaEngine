@echo off
:: ==============================================================================
:: CoronaEngine - RelWithDebInfo 构建脚本
:: 用途：在正确的 MSVC 环境下构建 corona_engine (cmake-build-relwithdebinfo)
:: 使用方法：在项目根目录或任意位置执行，路径均相对于脚本自身位置自动推导
:: ==============================================================================

setlocal

:: 脚本所在目录 → 推导项目根目录（scripts\build\ 上两级）
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..\

:: 构建目录 & 日志目录（相对项目根）
set BUILD_DIR=%PROJECT_ROOT%cmake-build-relwithdebinfo
set LOG_DIR=%SCRIPT_DIR%logs

:: 查找 MSVC vcvarsall.bat（通过 vswhere 自动定位，无需硬编码路径）
set VSWHERE="%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist %VSWHERE% set VSWHERE="%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"

for /f "usebackq delims=" %%i in (`%VSWHERE% -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do (
    set VS_INSTALL=%%i
)
if not defined VS_INSTALL (
    echo [ERROR] Visual Studio installation not found via vswhere
    exit /b 1
)
set VCVARSALL="%VS_INSTALL%\VC\Auxiliary\Build\vcvarsall.bat"

call %VCVARSALL% x64 -vcvars_ver=14.38
if errorlevel 1 (
    echo [ERROR] vcvarsall.bat failed
    exit /b 1
)

:: 查找 CLion 自带的 ninja（优先 PATH 中的 ninja，再尝试 CLion 默认位置）
where ninja >nul 2>&1
if %ERRORLEVEL% == 0 (
    set NINJA=ninja
) else (
    :: 通过注册表或常见路径找 CLion，这里用 where 查 clion64.exe 所在目录推导
    for /f "usebackq delims=" %%i in (`where clion64.exe 2^>nul`) do set CLION_EXE=%%i
    if defined CLION_EXE (
        :: clion64.exe 在 bin\ 下，ninja 在 bin\ninja\win\x64\
        for %%i in ("%CLION_EXE%") do set CLION_BIN=%%~dpi
        set NINJA="%CLION_BIN%ninja\win\x64\ninja.exe"
    ) else (
        echo [ERROR] ninja not found in PATH and CLion not found. Please add ninja to PATH.
        exit /b 1
    )
)

:: 日志文件名带时间戳
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set LOGFILE=%LOG_DIR%\build_%DT:~0,8%_%DT:~8,6%.txt

echo [BUILD] Target: corona_engine
echo [BUILD] Dir:    %BUILD_DIR%
echo [BUILD] Log:    %LOGFILE%
echo.

%NINJA% -C "%BUILD_DIR%" corona_engine > "%LOGFILE%" 2>&1
set BUILD_RC=%ERRORLEVEL%

if %BUILD_RC% == 0 (
    echo [SUCCESS] Build completed successfully.
) else (
    echo [FAILED]  Build failed. See log: %LOGFILE%
    echo.
    powershell -Command "Get-Content '%LOGFILE%' | Where-Object { $_ -match 'error|FAILED' } | Select-Object -Last 20"
)

exit /b %BUILD_RC%
