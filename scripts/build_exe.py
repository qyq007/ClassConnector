#!/usr/bin/env python3
"""构建 ClassConnector.exe。

在 Windows + Python 3.11 上运行（GitHub Actions 已配置好）：

    pip install -r requirements-build.txt
    python scripts/make_icons.py
    python scripts/build_exe.py

产物为 ``dist/ClassConnector.exe``：单文件、无控制台、双击即打开设置窗口。
``--lite`` 只用于无图形环境快速自检打包链路，不收集可选依赖。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 ClassConnector 可执行文件")
    parser.add_argument("--dist", default="dist", help="产物目录")
    parser.add_argument("--work", default="build/pyinstaller", help="临时构建目录")
    parser.add_argument("--lite", action="store_true", help="跳过可选依赖（快速自检）")
    parser.add_argument("--python", default=sys.executable, help="用于构建的 Python")
    args = parser.parse_args()

    spec = ROOT / "ClassConnector.spec"
    if not spec.is_file():
        print(f"[ERROR] 找不到 {spec}")
        return 2
    icon = ROOT / "assets" / "icon.ico"
    if not icon.is_file():
        print("图标不存在，先生成：python scripts/make_icons.py")
        return 2

    dist = (ROOT / args.dist).resolve()
    work = (ROOT / args.work).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    if args.lite:
        env["CC_LITE"] = "1"

    cmd = [
        args.python, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(work), str(spec),
    ]
    print("构建命令:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ROOT), env=env)
    if rc != 0:
        print(f"[ERROR] PyInstaller 失败，退出码 {rc}")
        return rc

    found = [p for p in sorted(dist.iterdir())
             if p.is_file() and p.name.startswith("ClassConnector")
             and not p.name.endswith((".zip", ".txt"))]
    if not found:
        print("[ERROR] 未在产物目录找到可执行文件")
        return 3
    for path in found:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"产物: {path}  {path.stat().st_size} B  SHA256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
