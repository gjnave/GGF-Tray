@echo off
echo.
echo ===============================================
echo    GGF - Get Going Fast Menu Setup
echo ===============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from python.org
    pause
    exit /b 1
)

echo Python found!
python --version
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

REM Change to ggf-menu directory
cd /d "%~dp0ggf-menu"

REM Install Python dependencies
echo Installing Python dependencies...
echo.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

REM Create whisper venv but don't install whisper yet
echo.
echo Setting up Whisper environment (venv only)...
echo Whisper models will download on first use
echo.

if not exist whisper_venv (
    python -m venv whisper_venv
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
cd /d "%~dp0"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut($env:APPDATA + '\Microsoft\Windows\Start Menu\Programs\Startup\GGF Tray.lnk'); $s.TargetPath = '%~dp0GGF-Tray.bat'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0ggf-menu\logo.ico'; $s.WindowStyle = 7; $s.Save()"

if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\GGF Tray.lnk" (
    echo ✓ GGF Tray will start automatically on Windows boot
) else (
    echo ✗ Could not add to startup - you can manually run GGF-Tray.bat
)

echo.
echo Adding GGF-Tray to Windows Explorer context menus...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-GGF-ContextMenu.ps1"

echo.
echo To start now: Run GGF-Tray.bat
echo To open menu: Run ggf-menu\GGF.bat
echo.
echo NOTE: Whisper transcription will download models
echo       (~75MB for 'base') on first use.
echo       You can change the model in ggf-menu\config.txt
echo.
pause
