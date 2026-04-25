@echo off
echo.
echo ========================================
echo   Building GGF Tray EXE (from venv)
echo ========================================
echo.
echo This builds using the venv environment
echo Your main Python stays clean!
echo.

REM Save current directory
set "BUILD_DIR=%CD%"

REM Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: venv not found!
    echo.
    echo Please create a venv first with:
    echo   python -m venv venv
    echo   venv\Scripts\activate
    echo   pip install pyinstaller pystray pillow PyQt6
    echo.
    pause
    exit /b 1
)

echo Activating venv...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate venv!
    pause
    exit /b 1
)

REM Return to build directory
cd /d "%BUILD_DIR%"

REM Check if PyInstaller is in venv
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found in venv. Installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo Failed to install PyInstaller!
        call venv\Scripts\deactivate.bat 2>nul
        pause
        exit /b 1
    )
)

echo.
echo Checking for required packages...
python -c "import pystray" 2>nul
if errorlevel 1 (
    echo Installing pystray...
    pip install pystray
)

python -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo Installing PyQt6...
    pip install PyQt6
)

echo.
echo ========================================
echo   IMPORTANT: Close the tray first!
echo ========================================
echo.
echo If GGF Tray is running, RIGHT-CLICK the tray icon
echo and select QUIT before continuing.
echo.
echo Otherwise the dist folder will be locked!
echo.
pause

REM Try to kill any running pythonw processes
echo Attempting to close any running Python processes...
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul

REM Clean previous build
echo Cleaning previous build...
if exist build rmdir /s /q build 2>nul
if exist dist rmdir /s /q dist 2>nul
if exist GGF-Tray.spec del /f GGF-Tray.spec 2>nul

if exist dist (
    echo.
    echo ERROR: Could not delete dist folder - it's still locked!
    echo.
    echo Please:
    echo 1. Close any running GGF Tray
    echo 2. Close Windows Explorer if browsing dist folder
    echo 3. Try running this script again
    echo.
    call venv\Scripts\deactivate.bat 2>nul
    pause
    exit /b 1
)

REM Verify files exist
if not exist "ggf-tray.py" (
    echo ERROR: ggf-tray.py not found in current directory!
    echo Current directory: %CD%
    echo.
    echo Make sure you run this script from the folder containing:
    echo   - ggf-tray.py
    echo   - app_search.py
    echo   - ggf_auth_token.py
    echo   - audio_visualizer_tray.py
    echo   - logo.ico
    echo   - config.txt
    echo   - etc.
    echo.
    call venv\Scripts\deactivate.bat 2>nul
    pause
    exit /b 1
)

if not exist "app_search.py" (
    echo ERROR: app_search.py not found!
    echo This is required for the app search window.
    call venv\Scripts\deactivate.bat 2>nul
    pause
    exit /b 1
)

if not exist "ggf_auth_token.py" (
    echo ERROR: ggf_auth_token.py not found!
    echo This is required for authentication.
    call venv\Scripts\deactivate.bat 2>nul
    pause
    exit /b 1
)

if not exist "audio_visualizer_tray.py" (
    echo WARNING: audio_visualizer_tray.py not found!
    echo Audio visualizer feature will not work.
    echo.
)

echo ✓ Found all required files in: %CD%
echo.
echo Building EXE...
echo This may take 5-10 minutes...
echo.

REM Build with PyInstaller
REM NOTE: Config files (txt/json) are NOT bundled - they'll be external
pyinstaller --clean ^
    --onedir ^
    --windowed ^
    --icon=logo.ico ^
    --add-data "logo.ico;." ^
    --add-data "app_search.py;." ^
    --add-data "ggf_auth_token.py;." ^
    --add-data "audio_visualizer_tray.py;." ^
    --name GGF-Tray ^
    --hidden-import pystray ^
    --hidden-import PIL ^
    --hidden-import ctypes ^
    --hidden-import ctypes.wintypes ^
    --hidden-import PyQt6 ^
    --hidden-import PyQt6.QtWidgets ^
    --hidden-import PyQt6.QtCore ^
    --hidden-import PyQt6.QtGui ^
    ggf-tray.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED! Check the error messages above.
    echo.
    call venv\Scripts\deactivate.bat 2>nul
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Copying External Config Files
echo ========================================
echo.
echo Config files will be OUTSIDE the bundle so users can edit them.
echo.

REM Copy config files to dist folder (NOT inside GGF-Tray folder)
if exist "config.txt" (
    copy "config.txt" "dist\GGF-Tray\" >nul
    echo ✓ Copied config.txt
)

if exist "shortcuts.txt" (
    copy "shortcuts.txt" "dist\GGF-Tray\" >nul
    echo ✓ Copied shortcuts.txt
)

if exist "installed_apps.txt" (
    copy "installed_apps.txt" "dist\GGF-Tray\" >nul
    echo ✓ Copied installed_apps.txt
)

if exist "install_whisper.bat" (
    copy "install_whisper.bat" "dist\GGF-Tray\" >nul
    echo ✓ Copied install_whisper.bat
)

REM Create default config files if they don't exist
if not exist "dist\GGF-Tray\config.txt" (
    echo [Settings] > "dist\GGF-Tray\config.txt"
    echo auto_start=false >> "dist\GGF-Tray\config.txt"
    echo ✓ Created default config.txt
)

if not exist "dist\GGF-Tray\shortcuts.txt" (
    echo. > "dist\GGF-Tray\shortcuts.txt"
    echo ✓ Created empty shortcuts.txt
)

if not exist "dist\GGF-Tray\installed_apps.txt" (
    echo. > "dist\GGF-Tray\installed_apps.txt"
    echo ✓ Created empty installed_apps.txt
)

REM Deactivate venv
call venv\Scripts\deactivate.bat 2>nul

echo.
echo ========================================
echo   BUILD COMPLETE!
echo ========================================
echo.
echo Your EXE is in: dist\GGF-Tray\GGF-Tray.exe
echo.
echo Config files are EXTERNAL (in dist\GGF-Tray\):
echo   - config.txt
echo   - shortcuts.txt
echo   - installed_apps.txt
echo   - (auth_cache.json will be created on first login)
echo.
echo To test: 
echo   cd dist\GGF-Tray
echo   GGF-Tray.exe
echo.
echo The EXE is standalone and includes everything!
echo Config files can be edited directly!
echo.
pause
