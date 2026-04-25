@echo off
setlocal EnableDelayedExpansion

REM Get script directory
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found!
    echo Please run install.bat first
    pause
    exit /b 1
)

REM Activate virtual environment and run
call venv\Scripts\activate.bat
python audio_visualizer_tray.py

REM If pythonw fails, try python (will show console)
if errorlevel 1 (
    python audio_visualizer_tray.py
)
