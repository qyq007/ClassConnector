#!/usr/bin/env bash
# 卸载采集端（需要安装密码）
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" -m agent.install --uninstall "$@"
