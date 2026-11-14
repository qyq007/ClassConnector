#!/usr/bin/env python3
"""构建 ClassConnector 的发行 zip 包（纯标准库，无第三方依赖）。

用法：
    python scripts/package.py
    python scripts/package.py --output /workspace/ClassConnector-v1.2.0.zip
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
INCLUDE_DIRS = (
    "agent", "manager", "scripts", "docs", "tests", ".vscode",
    "assets", ".github",
)
INCLUDE_FILES = (
    "README.md",
    "PORTABLE.txt",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-portable.txt",
    "requirements-build.txt",
    "app_main.py",
    "ClassConnector.spec",
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
            f"包含: 采集端 / 管理端 / 桌面 GUI 设置窗口 / exe 构建配置\n"
            f"      统一图标 / 文档 / 测试 / Visual Studio 与 VS Code 配置\n"
            f"源码运行要求: Python 3.8+（编译好的 exe 不需要 Python）\n"
            f"仓库: https://github.com/ssq0324/ClassConnector\n"
        ))
        append_text(zf, f"{top_dir}/README-FIRST.txt", (
            "ClassConnector — 快速开始（推荐桌面版 exe）\n"
            "========================================\n\n"
            "【推荐：双击 exe，无需 Python、无需 .bat、无需命令行】\n"
            "  从 GitHub Release 或 PR 的 Actions 产物下载 ClassConnector.exe。\n"
            "  （本 zip 是纯净源码包，exe 由 .github/workflows/build-exe.yml\n"
            "    在 Windows runner 上自动构建；也可本地运行 build_exe.py 生成。）\n"
            "  双击 exe -> 打开「ClassConnector · 设置」图形窗口 -> 服务自动后台启动。\n"
            "  窗口里可以设置：摄像头（本机枚举 / 画质 / 分辨率 / 帧率）、\n"
            "  播报语音与音效、班级名称、端口、休眠、访问密码、摄像头网络权限。\n"
            "  底部状态栏显示局域网地址，用浏览器打开即进入管理端。\n"
            "  退出需输入安装时设置的密码；删除文件夹即卸载。\n"
            "  详见 docs/DESKTOP.md。\n\n"
            "【重要：摄像头权限】默认只有本机的设置窗口能枚举并选择摄像头，\n"
            "  Web 管理端只能使用主机指定的那一路画面，看不到本机其他摄像头。\n"
            "  如需放开，在设置窗口「摄像头 -> 网络访问权限」勾选即可。\n\n"
            "【源码 / 脚本方式（可选，需要 Python 3.8+）】\n"
            "  图形窗口  : python -m agent.desktop   （与 exe 同一个设置窗口）\n"
            "  Windows   : 双击 scripts/start-portable.bat\n"
            "  Linux/mac : bash scripts/start-portable.sh\n"
            "  正式安装  : python -m agent.install（需要开机自启时）\n"
            "  绿色版数据全部在 data/，不写注册表 / 自启 / 系统 Python。\n\n"
            "【自己编译 exe（Windows）】\n"
            "  pip install -r requirements-build.txt\n"
            "  python scripts/make_icons.py\n"
            "  python scripts/build_exe.py          -> dist/ClassConnector.exe\n\n"
            "【用 Visual Studio / VS Code 编辑】\n"
            "  双击 ClassConnector.sln（需 VS + Python 开发工作负载），或用 VS Code\n"
            "  打开本文件夹按 F5。详见 docs/VISUAL_STUDIO.md、docs/DEVELOPMENT.md。\n\n"
            "完整说明见 README.md，接口见 docs/API.md，常见问题见 docs/FAQ.md。\n"
            "注意：全部 .bat 均为纯 ASCII + CRLF，请勿改成 UTF-8 中文或 LF 换行。\n"
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
