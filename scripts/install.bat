@echo off
chcp 65001 >nul
title ClassConnector 采集端安装
cd /d "%~dp0.."

echo ============================================================
echo   ClassConnector 班级连接器 · 采集端安装
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.9+ 并勾选 Add to PATH
    pause
    exit /b 1
)

echo [1/2] 安装依赖（可选依赖失败不影响核心功能）...
python -m pip install -r requirements.txt
echo.

echo [2/2] 配置采集端...
python -m agent.install %*
echo.
pause
