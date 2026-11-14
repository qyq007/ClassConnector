#!/usr/bin/env python3
"""构建 ClassConnector 的发行 zip 包（纯标准库，无第三方依赖）。

用法：
    python scripts/package.py
    python scripts/package.py --output /workspace/ClassConnector-v1.1.0.zip
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
    "PORTABLE.txt",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-portable.txt",
    "ClassConnector.sln",
    "ClassConnector.pyproj",
    ".gitignore",
    ".editorconfig",
)

# 目录名黑名单（出现在路径任意一层即排除）
EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".git", ".classconnector",
    "data", "runtime", "dist", "build", "venv", ".venv", "env", "node_modules",
}

# cmd.exe / Visual Studio 要求 CRLF；打包时强制转换，避免编辑器改动换行后出错
CRLF_SUFFIXES = {".bat", ".cmd", ".sln", ".pyproj"}
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


def payload(path: Path) -> bytes:
    """读取文件字节，必要时强制转成 CRLF 并去掉 BOM。"""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if path.suffix.lower() in CRLF_SUFFIXES:
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
        data = text.encode("utf-8")
    return data


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


def append_text(zf: zipfile.ZipFile, arcname: str, text: str,
                crlf: bool = True) -> None:
    info = zipfile.ZipInfo(arcname)
    info.date_time = datetime.now().timetuple()[:6]
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o644 | stat.S_IFREG) << 16
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    zf.writestr(info, text.encode("utf-8"))


def build(version: str, output: Path, top_dir: str) -> tuple[int, str]:
    files = collect()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            zf.writestr(zip_info(path, f"{top_dir}/{rel}"), payload(path))
        append_text(zf, f"{top_dir}/VERSION.txt", (
            f"ClassConnector {version}\n"
            f"构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"包含: 采集端 / 管理端 / 绿色便携启动脚本 / 文档 / 测试\n"
            f"      Visual Studio 解决方案 (.sln/.pyproj) 与 VS Code 配置\n"
            f"要求: Python 3.8+\n"
            f"仓库: https://github.com/ssq0324/ClassConnector\n"
        ))
        append_text(zf, f"{top_dir}/README-FIRST.txt", (
            "ClassConnector — 快速开始（推荐绿色版，无需安装）\n"
            "========================================\n\n"
            "【绿色版：不写注册表 / 不自启 / 不改系统 Python】要求 Python 3.8+\n"
            "  Windows      : 双击 scripts/start-portable.bat\n"
            "  Linux/macOS  : bash scripts/start-portable.sh\n"
            "首次运行会在本文件夹内建 runtime/venv 并装核心依赖，\n"
            "随后自动启动服务并打开 http://127.0.0.1:8420/\n"
            "退出按 Ctrl+C；卸载直接删除整个文件夹。\n"
            "全部说明见 PORTABLE.txt 与 docs/PORTABLE.md。\n\n"
            "【正式安装版：需要开机自启时】\n"
            "  Windows      : 双击 scripts/install.bat\n"
            "  Linux/macOS  : bash scripts/install.sh\n"
            "  任意系统     : python -m agent.install\n\n"
            "【退出密码（可选）】双击 scripts/set-password.bat\n\n"
            "【用 Visual Studio 编辑】双击 ClassConnector.sln\n"
            "  需 VS 2019/2022 +「Python 开发」工作负载，F5 即调试。\n"
            "  详见 docs/VISUAL_STUDIO.md；VS Code 见 docs/DEVELOPMENT.md。\n\n"
            "完整说明见 README.md，接口见 docs/API.md，常见问题见 docs/FAQ.md。\n"
            "注意：全部 .bat 均为纯 ASCII + CRLF，请勿改成 UTF-8 中文或 LF 换行，\n"
            "否则中文 Windows 的 cmd 会把命令拆碎导致启动失败。\n"
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
