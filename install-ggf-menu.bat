@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo.
echo ===============================================
echo    GGF - Get Going Fast Menu Setup
echo ===============================================
echo.

set "ROOT_DIR=%~dp0"
set "MENU_DIR=%ROOT_DIR%ggf-menu"
set "VENV_DIR=%MENU_DIR%\venv"
set "WHISPER_VENV_DIR=%MENU_DIR%\whisper_venv"

set "INSTALL_CONTEXT_MENU=0"
set "AUTO_START=1"

if /I "%~1"=="--context-menu" set "INSTALL_CONTEXT_MENU=1"
if /I "%~1"=="--no-start" set "AUTO_START=0"
if /I "%~2"=="--context-menu" set "INSTALL_CONTEXT_MENU=1"
if /I "%~2"=="--no-start" set "AUTO_START=0"

REM Choose Python (prefer py launcher if available)
set "PYEXE="
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=python"
    )
)

if "%PYEXE%"=="" (
    echo ERROR: Python is not installed (or not in PATH)
    echo Install Python 3.10+ from python.org, then re-run this installer.
    pause
    exit /b 1
)

echo Python found:
%PYEXE% --version
echo.

REM Check if ffmpeg is installed
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo WARNING: ffmpeg not found in PATH
    echo Video conversion features will not work
    echo Download ffmpeg from: https://ffmpeg.org/download.html
    echo.
) else (
    echo ffmpeg found!
    ffmpeg -version | findstr "ffmpeg version"
    echo.
)

if not exist "%MENU_DIR%" (
    echo ERROR: Could not find "%MENU_DIR%"
    pause
    exit /b 1
)

cd /d "%MENU_DIR%"

REM Create venv for the tray + tools (required by GGF-Tray.bat)
echo Setting up Python virtual environment...
if not exist "%VENV_DIR%\Scripts\python.exe" (
    %PYEXE% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create venv at "%VENV_DIR%"
        pause
        exit /b 1
    )
) else (
    echo venv already exists
)

set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

echo.
echo Installing Python dependencies into venv...
echo.
%VENV_PY% -m pip install --upgrade pip
%VENV_PY% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Create whisper venv but don't install whisper yet
echo.
echo Setting up Whisper environment (venv only)...
echo Whisper models will download on first use.
echo.

if not exist "%WHISPER_VENV_DIR%\Scripts\python.exe" (
    %PYEXE% -m venv "%WHISPER_VENV_DIR%"
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to create whisper venv at "%WHISPER_VENV_DIR%"
        pause
        exit /b 1
    )
    echo Whisper venv created!
) else (
    echo Whisper venv already exists
)

echo.
echo ===============================================
echo    Setup Complete!
echo ===============================================
echo.
echo GGF Menu is ready to use!
echo.
echo Adding GGF Tray to Windows Startup...
cd /d "%ROOT_DIR%"

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'; " ^
  "$lnk = Join-Path $startup 'GGF Tray.lnk'; " ^
  "$s = $ws.CreateShortcut($lnk); " ^
  "$s.TargetPath = '%ROOT_DIR%GGF-Tray.bat'; " ^
  "$s.WorkingDirectory = '%ROOT_DIR%'; " ^
  "$s.IconLocation = '%ROOT_DIR%ggf-menu\\logo.ico'; " ^
  "$s.WindowStyle = 7; " ^
  "$s.Save()"

if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\GGF Tray.lnk" (
    echo OK: GGF Tray will start automatically on Windows boot
) else (
    echo WARNING: Could not add to startup - you can manually run GGF-Tray.bat
)

echo.
if "%INSTALL_CONTEXT_MENU%"=="1" (
    if exist "%ROOT_DIR%Install-GGF-ContextMenu.ps1" (
        echo Adding GGF-Tray to Windows Explorer context menus...
        powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%Install-GGF-ContextMenu.ps1"
    ) else (
        echo Skipping context menu: Install-GGF-ContextMenu.ps1 not found
    )
) else (
    echo Skipping context menus. Re-run with --context-menu to enable.
)

echo.
echo To start now: Run GGF-Tray.bat
echo.
echo NOTE: Whisper transcription will download models on first use.
echo You can change the model in ggf-menu\config.txt
echo.

if "%AUTO_START%"=="1" (
    echo Starting tray...
    start "" "%ROOT_DIR%GGF-Tray.bat"
)

pause
