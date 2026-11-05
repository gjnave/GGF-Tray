@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0ggf-menu" || exit /b 1
if exist "GGF-Tray.exe" (
  start "" /d "%cd%" "%cd%\GGF-Tray.exe"
  exit /b
)
if exist "venv\Scripts\pythonw.exe" (
  start "" /d "%cd%" "%cd%\venv\Scripts\pythonw.exe" "%cd%\ggf-tray.py"
  exit /b
)
echo GGF Tray is not installed. Run install-ggf-menu.bat first.
pause
exit /b 1
