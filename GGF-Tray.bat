@echo off
REM Clean up any stuck lock files and cache
cd /d "%~dp0ggf-menu"

if exist ".ggf_tray.lock" del ".ggf_tray.lock"
if exist ".ggf_menu.lock" del ".ggf_menu.lock"

REM Clear Python cache for fresh load
del /S /Q __pycache__ >nul 2>nul
del /S /Q *.pyc >nul 2>nul

REM Start tray
REM Use the venv directly (avoid relying on PATH / activation quirks)
if not exist "venv\Scripts\pythonw.exe" (
  echo ERROR: venv is missing at "%~dp0ggf-menu\venv"
  echo Run install-ggf-menu.bat to recreate it.
  pause
  exit /b 1
)

REM Launch detached via PowerShell for reliability (avoids cmd.exe START edge cases)
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%~dp0ggf-menu\\venv\\Scripts\\pythonw.exe' -WorkingDirectory '%~dp0ggf-menu' -ArgumentList '%~dp0ggf-menu\\ggf-tray.py'"
