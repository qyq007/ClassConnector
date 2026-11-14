#!/usr/bin/env python3
"""构建 ClassConnector 的发行 zip 包（纯标准库，无第三方依赖）。

用法：
    python scripts/package.py
    python scripts/package.py --output /workspace/ClassConnector-v1.0.0.zip
    python scripts/package.py --top-dir ClassConnector

版本号取自 agent/__init__.py 的 __version__。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 需要打进发行包的目录与顶层文件
INCLUDE_DIRS = ("agent", "manager", "scripts", "docs", "tests", ".vscode")
INCLUDE_FILES = (
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    ".gitignore",
    ".editorconfig",
)

# 目录名黑名单（出现在路径任意一层即排除）
EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".git", ".classconnector",
    "dist", "build", "venv", ".venv", "env", "node_modules",
}
# 扩展名黑名单
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".wav", ".mp3", ".zip", ".pid", ".egg-info"}
# 允许保留的点文件（位于顶层）
ALLOW_DOT_FILES = {".gitignore", ".editorconfig"}

VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


def read_version() -> str:
    text = (ROOT / "agent" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise RuntimeError("无法从 agent/__init__.py 读取 __version__")
    return match.group(1)


def excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if path.name.startswith(".") and path.name not in ALLOW_DOT_FILES:
        # .vscode/ 下的配置文件名不以点开头，不受影响
        return True
    if path.name.endswith("~") or path.name in {"Thumbs.db", "desktop.ini", ".DS_Store"}:
        return True
    return False


def collect() -> list[Path]:
    files: list[Path] = []
    for dirname in INCLUDE_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not excluded(path):
                files.append(path)
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    # 去重并排序，保证 zip 内容稳定
    return sorted(set(files), key=lambda p: str(p.relative_to(ROOT)))


def zip_info(path: Path, arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    info.date_time = (mtime.year, mtime.month, mtime.day,
                      mtime.hour, mtime.minute, mtime.second)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix，保留可执行位
    mode = 0o755 if path.suffix in {".sh"} or path.stat().st_mode & stat.S_IXUSR else 0o644
    info.external_attr = (mode | stat.S_IFREG) << 16
    return info


def append_text(zf: zipfile.ZipFile, arcname: str, text: str) -> None:
    info = zipfile.ZipInfo(arcname)
    info.date_time = datetime.now().timetuple()[:6]
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o644 | stat.S_IFREG) << 16
    zf.writestr(info, text.encode("utf-8"))


def build(version: str, output: Path, top_dir: str) -> tuple[int, str]:
    files = collect()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            zf.writestr(zip_info(path, f"{top_dir}/{rel}"), path.read_bytes())
        append_text(zf, f"{top_dir}/VERSION.txt", (
            f"ClassConnector {version}\n"
            f"构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"包含: 采集端 / 管理端 / 安装脚本 / 文档 / 测试 / VS Code 配置\n"
            f"仓库: https://github.com/ssq0324/ClassConnector\n"
        ))
        append_text(zf, f"{top_dir}/README-先看.txt", (
            "ClassConnector 班级连接器 — 快速开始\n"
            "========================================\n\n"
            "【教室电脑 / 采集端】要求 Python 3.9+\n"
            "  Windows      : 双击 scripts/install.bat\n"
            "  Linux/macOS  : bash scripts/install.sh\n"
            "  任意系统     : python -m agent.install\n"
            "安装向导会设置退出密码、开机自启并后台启动。\n\n"
            "【管理端】浏览器打开 http://<设备IP>:8420\n"
            "或在连接面板填写设备 IP + 端口。\n\n"
            "【VS Code 开发】用 VS Code 打开本文件夹，\n"
            "安装推荐扩展后按 F5 即可调试采集端，详见 docs/DEVELOPMENT.md。\n\n"
            "完整说明见 README.md，接口见 docs/API.md，常见问题见 docs/FAQ.md。\n"
        ))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return len(files) + 2, digest


def main() -> int:
    version = read_version()
    parser = argparse.ArgumentParser(description="打包 ClassConnector 发行 zip")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "dist" / f"ClassConnector-v{version}.zip",
                        help="输出 zip 路径")
    parser.add_argument("--top-dir", default=f"ClassConnector-v{version}",
                        help="zip 内的顶层目录名")
    args = parser.parse_args()

    output: Path = args.output.expanduser().resolve()
    total, digest = build(version, output, args.top_dir)
    size_kb = output.stat().st_size / 1024
    print(f"版本      : {version}")
    print(f"输出      : {output}")
    print(f"大小      : {size_kb:.1f} KB")
    print(f"文件数    : {total}")
    print(f"SHA256    : {digest}")
    print(f"顶层目录  : {args.top_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
