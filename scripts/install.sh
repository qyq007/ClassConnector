#!/usr/bin/env bash
# ClassConnector 采集端安装（Linux / macOS）
set -e
cd "$(dirname "$0")/.."

echo "============================================================"
echo "  ClassConnector 班级连接器 · 采集端安装"
echo "============================================================"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "[错误] 未找到 $PY，请先安装 Python 3.9+"
    exit 1
fi

echo "[1/2] 安装依赖（可选依赖失败不影响核心功能）..."
"$PY" -m pip install -r requirements.txt || echo "[提示] 部分可选依赖安装失败，程序会自动降级"

echo "[2/2] 配置采集端..."
"$PY" -m agent.install "$@"
