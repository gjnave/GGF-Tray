@echo off
setlocal EnableExtensions

REM -------------------------------------------------------------------
REM GGF-Tray Installer (single-file bootstrap)
REM - Clones (or updates) the repo
REM - Runs the in-repo installer to create venv + install requirements
REM
REM Usage:
REM   GGF-Tray-Installer.bat
REM   GGF-Tray-Installer.bat --dir C:\GGF
REM   GGF-Tray-Installer.bat --context-menu
REM   GGF-Tray-Installer.bat --no-start
REM -------------------------------------------------------------------

set "REPO_URL=https://github.com/gjnave/GGF-Tray.git"
set "TARGET_DIR="
set "INSTALL_CONTEXT_MENU=0"
set "NO_START=0"
set "DEBUG=0"

:parse
if "%~1"=="" goto parsed
if /I "%~1"=="--dir" (
  set "TARGET_DIR=%~2"
  shift
  shift
  goto parse
)
if /I "%~1"=="--context-menu" (
  set "INSTALL_CONTEXT_MENU=1"
  shift
  goto parse
)
if /I "%~1"=="--no-start" (
  set "NO_START=1"
  shift
  goto parse
)
if /I "%~1"=="--debug" (
  set "DEBUG=1"
  shift
  goto parse
)
shift
goto parse

:parsed
if "%TARGET_DIR%"=="" set "TARGET_DIR=C:\GGF"

if "%DEBUG%"=="1" (
  echo on
)

echo.
echo ===============================================
echo    GGF-Tray Bootstrap Installer
echo ===============================================
echo.
echo Target: "%TARGET_DIR%"
echo Repo:   "%REPO_URL%"
echo.

REM Check git
git --version >nul 2>&1
if errorlevel 1 goto :no_git

REM Check Python
set "PYEXE="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3"
if "%PYEXE%"=="" (
  python --version >nul 2>&1
  if not errorlevel 1 set "PYEXE=python"
)
if "%PYEXE%"=="" goto :no_python

REM Create target dir (fallback if no permission for C:\)
mkdir "%TARGET_DIR%" >nul 2>&1
if exist "%TARGET_DIR%\NUL" goto :dir_ok
set "TARGET_DIR=%LOCALAPPDATA%\GGF-Tray"
echo NOTE: Could not write to C:\. Using "%TARGET_DIR%" instead.
mkdir "%TARGET_DIR%" >nul 2>&1
:dir_ok

REM Clone or update
if exist "%TARGET_DIR%\.git\config" (
  echo Updating existing repo...
  pushd "%TARGET_DIR%" >nul
  git fetch --all --prune
  git pull --ff-only
  if errorlevel 1 (
    echo ERROR: git pull failed. Fix git auth/merge state, then re-run.
    popd >nul
    pause
    exit /b 1
  )
  popd >nul
) else (
  echo Cloning repo...
  git clone "%REPO_URL%" "%TARGET_DIR%"
  if errorlevel 1 (
    echo ERROR: git clone failed.
    echo If this is a private repo, make sure you have access and are logged in.
    pause
    exit /b 1
  )
)

REM Run in-repo installer
set "INSTALLER=%TARGET_DIR%\install-ggf-menu.bat"
if not exist "%INSTALLER%" (
  echo ERROR: Missing installer at "%INSTALLER%"
  pause
  exit /b 1
)

set "ARGS="
if "%INSTALL_CONTEXT_MENU%"=="1" set "ARGS=%ARGS% --context-menu"
if "%NO_START%"=="1" set "ARGS=%ARGS% --no-start"

echo.
echo Running in-repo installer...
call "%INSTALLER%" %ARGS%

exit /b %errorlevel%

:no_git
echo ERROR: git is not installed or not in PATH.
echo Install Git for Windows, then re-run this installer.
pause
exit /b 1

:no_python
echo ERROR: Python is not installed (or not in PATH).
echo Install Python 3.10+ from python.org, then re-run this installer.
pause
exit /b 1
