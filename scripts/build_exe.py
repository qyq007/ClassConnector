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


def _force_utf8_stdio() -> None:
    """Windows 中文控制台默认 cp1252 / gbk，中文输出会抛 UnicodeEncodeError。

    本脚本的提示文字全部使用 ASCII（见下方），这里再兜一层，确保任何
    第三方库 / 子进程写出的非 ASCII 文本也不会让构建中断。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(description="Build the ClassConnector executable")
    parser.add_argument("--dist", default="dist", help="输出目录")
    parser.add_argument("--work", default="build/pyinstaller", help="临时构建目录")
    parser.add_argument("--lite", action="store_true", help="跳过可选依赖（快速自检）")
    parser.add_argument("--python", default=sys.executable, help="用于构建的 Python")
    args = parser.parse_args()

    spec = ROOT / "ClassConnector.spec"
    if not spec.is_file():
        print(f"[ERROR] spec not found: {spec}")
        return 2
    icon = ROOT / "assets" / "icon.ico"
    if not icon.is_file():
        print("[ERROR] icon missing, run: python scripts/make_icons.py")
        return 2

    dist = (ROOT / args.dist).resolve()
    work = (ROOT / args.work).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if args.lite:
        env["CC_LITE"] = "1"

    cmd = [
        args.python, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(work), str(spec),
    ]
    print("COMMAND:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ROOT), env=env)
    if rc != 0:
        print(f"[ERROR] PyInstaller failed with exit code {rc}")
        return rc

    found = [p for p in sorted(dist.iterdir())
             if p.is_file() and p.name.startswith("ClassConnector")
             and not p.name.endswith((".zip", ".txt"))]
    if not found:
        print("[ERROR] No executable found in the dist directory")
        return 3
    for path in found:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"OUTPUT: {path}  {path.stat().st_size} bytes  SHA256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
