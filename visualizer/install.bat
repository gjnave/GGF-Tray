@echo off
setlocal EnableDelayedExpansion

echo ========================================
echo Audio Visualizer System Tray Installer
echo ========================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8 or higher from python.org
    pause
    exit /b 1
)

echo [OK] Python found
echo.

REM Get script directory
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)
echo.

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)
echo.

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet
echo.

REM Install requirements
echo Installing required packages...
echo This may take a few minutes...
pip install -r requirements.txt --break-system-packages
if errorlevel 1 (
    echo [ERROR] Failed to install requirements
    pause
    exit /b 1
)
echo.
echo [OK] All packages installed successfully
echo.

REM Create startup shortcut (optional)
echo.
set /p CREATE_SHORTCUT="Create startup shortcut? (Y/N): "
if /i "%CREATE_SHORTCUT%"=="Y" (
    echo Creating startup shortcut...
    
    REM Create VBS script to generate shortcut
    echo Set oWS = WScript.CreateObject("WScript.Shell") > CreateShortcut.vbs
    echo sLinkFile = "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AudioVisualizer.lnk" >> CreateShortcut.vbs
    echo Set oLink = oWS.CreateShortcut(sLinkFile) >> CreateShortcut.vbs
    echo oLink.TargetPath = "%SCRIPT_DIR%run_visualizer.bat" >> CreateShortcut.vbs
    echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> CreateShortcut.vbs
    echo oLink.Description = "Audio Visualizer System Tray" >> CreateShortcut.vbs
    echo oLink.Save >> CreateShortcut.vbs
    
    cscript //nologo CreateShortcut.vbs
    del CreateShortcut.vbs
    
    echo [OK] Startup shortcut created
)

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo To run the visualizer:
echo 1. Double-click run_visualizer.bat
echo 2. Look for the cyan icon in your system tray
echo 3. Right-click the icon and select "Activate Visualizer"
echo.
echo Settings are saved in visualizer_config.json
echo.
pause
