@echo off
chcp 65001 >nul
title ClassConnector 采集端（前台调试）
cd /d "%~dp0.."
echo 前台运行采集端，按 Ctrl+C 退出。
echo 正式使用请执行 install.bat 安装为开机自启后台服务。
echo.
python -m agent %*
pause
