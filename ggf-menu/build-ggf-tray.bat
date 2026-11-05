@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "PY=build-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=venv\Scripts\python.exe"
if not exist "%PY%" goto failed
set "OUT=%~dp0..\release\build-%RANDOM%-%RANDOM%"
if exist "%OUT%" goto failed
mkdir "%OUT%" || goto failed
set "PYINSTALLER_CONFIG_DIR=%OUT%\cache"
"%PY%" -m unittest discover -s tests -v || goto failed
"%PY%" -m PyInstaller --distpath "%OUT%\dist" --workpath "%OUT%\work" GGF-Tray-Release.spec || goto failed
set "LOCALAPPDATA=%OUT%\test-profile"
start "" /wait "%OUT%\dist\GGF-Tray.exe" --self-test
if errorlevel 1 goto failed
echo Verified: "%OUT%\dist\GGF-Tray.exe"
certutil -hashfile "%OUT%\dist\GGF-Tray.exe" SHA256
exit /b 0
:failed
echo Build failed. Existing releases were preserved.
exit /b 1
