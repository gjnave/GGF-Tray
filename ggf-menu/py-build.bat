@echo off
setlocal

cd /d C:\GGF\ggf-menu

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name GGF-Tray-OneFile ^
  --distpath dist_onefile ^
  --workpath build_onefile ^
  --icon "logo.ico" ^
  --add-data "logo.ico;." ^
  --collect-all pyaudiowpatch ^
  --hidden-import app_search ^
  --hidden-import audio_visualizer_tray ^
  --hidden-import ggf_auth_token ^
  --hidden-import PyQt6.QtWebEngineWidgets ^
  "ggf-tray.py"

echo.
echo Build complete.
echo EXE should be here:
echo C:\GGF\ggf-menu\dist_onefile\GGF-Tray-OneFile.exe
pause
