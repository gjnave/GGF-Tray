@if (@CodeSection == @Batch) @then
@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "INSTALL_SCRIPT=%~f0"
set "DEST=%LOCALAPPDATA%\Programs\Get Going Fast\Tray-0.16.2"
if /i "%~1"=="--from-setup" goto extracted
if /i "%~1"=="--from-setup-quiet" goto extracted
if /i "%~dp0"=="%DEST%\" if exist "%DEST%\GGF-Tray.exe" goto extracted
cd /d "%~dp0ggf-menu" || exit /b 1
if exist "GGF-Tray.exe" goto packaged
if not exist "requirements.txt" goto missing
if exist "venv\Scripts\python.exe" goto dependencies
where py.exe >nul 2>nul
if errorlevel 1 goto plainpython
py -3.11 -m venv venv
if not errorlevel 1 goto dependencies
:plainpython
python -m venv venv || goto failed
:dependencies
"venv\Scripts\python.exe" -m pip install -r requirements.txt || goto failed
start "" /d "%cd%" "%cd%\venv\Scripts\pythonw.exe" "%cd%\ggf-tray.py"
exit /b 0
:packaged
if not exist "%DEST%\" mkdir "%DEST%" || goto failed
if exist "%DEST%\GGF-Tray.exe" goto existing
copy /b /-y "GGF-Tray.exe" "%DEST%\GGF-Tray.exe" <nul >nul || goto failed
:existing
"%SystemRoot%\System32\fc.exe" /b "GGF-Tray.exe" "%DEST%\GGF-Tray.exe" >nul
if errorlevel 1 goto mismatch
goto register
:extracted
cd /d "%DEST%" || exit /b 1
if not exist "GGF-Tray.exe" exit /b 1
:register
set "MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
if not exist "%MENU%\" mkdir "%MENU%"
"%SystemRoot%\System32\cscript.exe" //nologo //E:JScript "%INSTALL_SCRIPT%" "%MENU%\Get Going Fast Tray.lnk" "%DEST%\GGF-Tray.exe"
if errorlevel 1 echo Start menu shortcut unavailable. You can open the EXE directly.
set "SETUP_MODE="
if /i "%~1"=="--no-launch" set "SETUP_MODE=--setup-unattended"
if /i "%~1"=="--from-setup-quiet" set "SETUP_MODE=--setup-unattended"
start "" /wait "%DEST%\GGF-Tray.exe" --register-startup %SETUP_MODE%
if errorlevel 1 (
  echo Windows startup could not be configured. See Start silently with Windows in the tray menu.
  exit /b 1
)
if /i "%~1"=="--no-launch" exit /b 0
if /i "%~1"=="--from-setup" exit /b 0
if /i "%~1"=="--from-setup-quiet" exit /b 0
echo GGF Tray is installed at "%DEST%\GGF-Tray.exe".
echo Starting GGF Tray. Look in the notification area by the clock.
start "" /d "%DEST%" "%DEST%\GGF-Tray.exe"
exit /b 0
:mismatch
echo A different EXE is already in "%DEST%". No existing program was replaced.
echo You can run the included ggf-menu\GGF-Tray.exe directly.
goto setupError
:missing
echo Extract the complete ZIP before running the installer.
goto setupError
:failed
echo Setup did not finish. See the error above.
:setupError
if /i "%~1"=="--from-setup-quiet" exit /b 1
if /i "%~1"=="--from-setup" exit /b 1
if /i "%~1"=="--no-launch" exit /b 1
pause
exit /b 1

@end
var shell = new ActiveXObject("WScript.Shell");
var fso = new ActiveXObject("Scripting.FileSystemObject");
var linkPath=WScript.Arguments(0), target=WScript.Arguments(1);
var link=shell.CreateShortcut(linkPath);
var oldManagedPath=fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(target)), "Tray-0.13.0\\GGF-Tray.exe");
var priorManagedPath=fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(target)), "Tray-0.14.0\\GGF-Tray.exe");
var lastManagedPath=fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(target)), "Tray-0.15.0\\GGF-Tray.exe");
var lastPatchPath=fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(target)), "Tray-0.15.1\\GGF-Tray.exe");
var lastReleasePath=fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(target)), "Tray-0.16.0\\GGF-Tray.exe");
var firstSetupPath=fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(target)), "Tray-0.16.1\\GGF-Tray.exe");
var existing=String(link.TargetPath).toLowerCase();
if (fso.FileExists(linkPath) && existing !== target.toLowerCase() && existing !== oldManagedPath.toLowerCase() && existing !== priorManagedPath.toLowerCase() && existing !== lastManagedPath.toLowerCase() && existing !== lastPatchPath.toLowerCase() && existing !== lastReleasePath.toLowerCase() && existing !== firstSetupPath.toLowerCase()) {
    WScript.Echo("An existing shortcut was preserved."); WScript.Quit(1);
}
link.TargetPath=target;
link.WorkingDirectory=fso.GetParentFolderName(target);
link.IconLocation=target+",0";
link.Description="GGF app catalog, Quick Launch and music";
link.Save();
