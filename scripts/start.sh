#!/usr/bin/env bash
# 前台运行采集端（调试用）。正式使用请执行 install.sh 安装为后台自启服务。
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" -m agent "$@"
