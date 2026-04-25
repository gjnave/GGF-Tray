@echo off
echo.
echo ===============================================
echo    GGF - Cleanup Stuck Processes
echo ===============================================
echo.

cd /d "%~dp0ggf-menu"

echo Removing lock files...
if exist ".ggf_tray.lock" (
    del ".ggf_tray.lock"
    echo ✓ Removed tray lock
)

if exist ".ggf_menu.lock" (
    del ".ggf_menu.lock"
    echo ✓ Removed menu lock
)

echo.
echo Killing any stuck Python processes...
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python.exe 2>nul

echo.
echo Clearing Python cache...
del /S /Q __pycache__ 2>nul
del /S /Q *.pyc 2>nul

echo.
echo Cleanup complete! You can now restart GGF-Tray.bat
echo.
pause
