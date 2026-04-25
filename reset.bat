@echo off
echo.
echo ===============================================
echo    GGF - Quick Reset (Clear Cache)
echo ===============================================
echo.

echo Killing all Python processes...
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python.exe 2>nul

echo.
echo Removing lock files...
cd /d "%~dp0ggf-menu"
if exist ".ggf_tray.lock" del ".ggf_tray.lock"
if exist ".ggf_menu.lock" del ".ggf_menu.lock"

echo.
echo Clearing Python cache files...
del /S /Q __pycache__ 2>nul
del /S /Q *.pyc 2>nul

echo.
echo ===============================================
echo    Cache cleared! Ready to test changes.
echo ===============================================
echo.
echo Run GGF-Tray.bat to start fresh
echo.
pause
