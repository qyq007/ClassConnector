@echo off
setlocal
rem ============================================================
rem  ClassConnector PORTABLE launcher
rem  ASCII only + CRLF on purpose. Do NOT put Chinese text here:
rem  cmd.exe parses .bat by bytes and UTF-8 text breaks commands.
rem  No registry, no autostart, no service, no user-profile writes.
rem ============================================================
set "CC_ROOT=%~dp0.."
cd /d "%CC_ROOT%" || goto :fail
set "CC_DATA=%CC_ROOT%\data"
if not exist "%CC_DATA%" mkdir "%CC_DATA%"
set "CLASSCONNECTOR_HOME=%CC_DATA%"
set "CLASSCONNECTOR_CONFIG=%CC_DATA%\config.json"

rem --- locate a Python interpreter -------------------------------
set "PYCMD="
where python >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if not defined PYCMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD goto :nopython

rem --- core deps: if missing, create a venv INSIDE this folder ----
%PYCMD% -c "import fastapi, uvicorn, multipart, PIL" >nul 2>nul
if not errorlevel 1 goto :run_system

echo First run: creating .\runtime\venv and installing core packages.
echo Everything stays inside this folder (no system changes).
if not exist "%CC_ROOT%\runtime" mkdir "%CC_ROOT%\runtime"
if not exist "%CC_ROOT%\runtime\venv\Scripts\python.exe" (
    %PYCMD% -m venv "%CC_ROOT%\runtime\venv" || goto :fail
)
"%CC_ROOT%\runtime\venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "%CC_ROOT%\requirements-portable.txt" || goto :fail
set RUNCMD="%CC_ROOT%\runtime\venv\Scripts\python.exe"
goto :run

:run_system
set "RUNCMD=%PYCMD%"

:run
echo.
%RUNCMD% -m agent.portable %*
echo.
echo ClassConnector stopped. Press any key to close.
pause >nul
exit /b 0

:nopython
echo [ERROR] Python 3.8+ not found in PATH.
echo Install from https://www.python.org/downloads/ and tick "Add Python to PATH".
pause
exit /b 1

:fail
echo [ERROR] Setup failed. See the messages above.
pause
exit /b 1
