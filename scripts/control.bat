@echo off
setlocal
rem Local control commands for the INSTALLED agent.
cd /d "%~dp0.." || exit /b 1
python -m agent.control %*
pause
