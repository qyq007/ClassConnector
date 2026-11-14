@echo off
setlocal
rem ClassConnector INSTALLER (registers autostart + writes user profile).
rem For a no-install / portable run use scripts\start-portable.bat instead.
rem ASCII only + CRLF: cmd.exe parses .bat by bytes.
cd /d "%~dp0.." || goto :fail
where python >nul 2>nul
if errorlevel 1 goto :nopython
echo [1/2] Installing Python dependencies ...
python -m pip install -r requirements.txt
echo [2/2] Running install wizard ...
python -m agent.install %*
echo.
pause
exit /b 0

:nopython
echo [ERROR] Python 3.8+ not found in PATH.
pause
exit /b 1

:fail
echo [ERROR] Cannot enter the project folder.
pause
exit /b 1
