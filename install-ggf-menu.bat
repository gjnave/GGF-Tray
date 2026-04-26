@echo off
setlocal
cd /d "%~dp0"

echo.
echo ===============================================
echo    GGF - Get Going Fast Menu Setup
echo ===============================================
echo.

if exist "disclaimer.md" (
    type "disclaimer.md"
    echo.
    pause
)

if exist "about.nfo" type "about.nfo"
echo.

echo WARNING: For this installer to work you need Python 3.10.11, Git and FFmpeg installed.
echo.

cd /d "%~dp0ggf-menu"

py --version >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo Python launcher found. Creating Python 3.10 venv.
    py -3.10 -m venv venv
) else (
    echo Python launcher not found. Creating venv with default Python.
    python -m venv venv
)

if not "%ERRORLEVEL%"=="0" (
    echo Failed to create venv.
    pause
    exit /b 1
)

call .\venv\Scripts\activate.bat

python -m pip install --upgrade pip
if not "%ERRORLEVEL%"=="0" (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

pip install -r requirements.txt
if not "%ERRORLEVEL%"=="0" (
    echo Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo GGF Menu installed successfully.
echo Run GGF-Tray.bat to start it.
echo.
pause
