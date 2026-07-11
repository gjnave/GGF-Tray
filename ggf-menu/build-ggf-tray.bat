@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo   GGF Tray - verified local one-file build
echo ========================================
echo.

set "PY=venv\Scripts\python.exe"
set "NEXT=dist_onefile_next"
set "FINAL=dist_onefile"
set "BACKUP=_BACKUPS"

if not exist "%PY%" (
  echo ERROR: venv\Scripts\python.exe is missing.
  echo Create the local environment first, then run this file again.
  exit /b 1
)

tasklist /FI "IMAGENAME eq GGF-Tray-OneFile.exe" 2>nul | find /I "GGF-Tray-OneFile.exe" >nul
if not errorlevel 1 (
  echo ERROR: GGF-Tray-OneFile.exe is running. Quit it from the tray and retry.
  echo No unrelated Python processes were stopped.
  exit /b 1
)

echo [1/6] Checking local build dependencies...
"%PY%" -c "import PyInstaller, PIL, pystray, PyQt6, psutil, certifi, imageio_ffmpeg, numpy, pyaudiowpatch" 2>nul
if errorlevel 1 (
  echo Installing only the declared local dependencies...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)

echo [2/6] Running source checks...
"%PY%" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
"%PY%" -m py_compile ggf-tray.py app_search.py audio_visualizer_tray.py ggf_auth_token.py ggf_installer.py ggf_runtime.py
if errorlevel 1 exit /b 1

echo [3/6] Cleaning isolated staging folders...
if exist "build_onefile_next" rmdir /s /q "build_onefile_next"
if exist "%NEXT%" rmdir /s /q "%NEXT%"

echo [4/6] Building one-file executable...
"%PY%" -m PyInstaller --noconfirm --clean --distpath "%NEXT%" --workpath "build_onefile_next" GGF-Tray-OneFile.spec
if errorlevel 1 exit /b 1
if not exist "%NEXT%\GGF-Tray-OneFile.exe" (
  echo ERROR: PyInstaller returned without the expected executable.
  exit /b 1
)

echo [5/6] Running packaged self-test...
"%NEXT%\GGF-Tray-OneFile.exe" --self-test
if errorlevel 1 (
  echo ERROR: Packaged self-test failed. Existing release was not replaced.
  exit /b 1
)

echo [6/6] Promoting verified build...
if not exist "%BACKUP%" mkdir "%BACKUP%"
if exist "%BACKUP%\GGF-Tray-OneFile.previous.exe" copy /Y "%BACKUP%\GGF-Tray-OneFile.previous.exe" "%BACKUP%\GGF-Tray-OneFile.older.exe" >nul
if exist "%FINAL%\GGF-Tray-OneFile.exe" copy /Y "%FINAL%\GGF-Tray-OneFile.exe" "%BACKUP%\GGF-Tray-OneFile.previous.exe" >nul
if not exist "%FINAL%" mkdir "%FINAL%"
copy /Y "%NEXT%\GGF-Tray-OneFile.exe" "%FINAL%\GGF-Tray-OneFile.exe" >nul
if errorlevel 1 exit /b 1

echo.
echo BUILD VERIFIED:
echo   %CD%\%FINAL%\GGF-Tray-OneFile.exe
certutil -hashfile "%FINAL%\GGF-Tray-OneFile.exe" SHA256
exit /b 0
