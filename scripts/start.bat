@echo off
setlocal
rem Start the INSTALLED agent in the foreground (Ctrl+C to stop).
rem For portable mode use scripts\start-portable.bat
cd /d "%~dp0.." || exit /b 1
python -m agent %*
pause
