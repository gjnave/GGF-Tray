@echo off
rem Compatibility entry point. The canonical, local-only build is kept in one batch file.
call "%~dp0build-ggf-tray.bat"
exit /b %errorlevel%
