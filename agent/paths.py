"""路径解析：源码运行与 PyInstaller 打包后的 exe 共用。

PyInstaller ``--onefile`` 运行时会把只读资源解压到 ``sys._MEIPASS``，
而 exe 本体位于用户放置的目录。两者必须分开：

- :func:`resource_root` —— 只读资源（``manager/``、``assets/``），exe 内为 ``_MEIPASS``；
- :func:`writable_root` —— 可写数据（``data/``、``config.json``），始终在 exe 所在目录，
  保证「绿色」：删除文件夹即卸载，不写用户目录、注册表或系统 Python。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行于 PyInstaller 打包出的可执行文件中。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        base = getattr(sys, "_MEIPASS", "")
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def writable_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return resource_root()


def manager_dir() -> Path:
    return resource_root() / "manager"


def assets_dir() -> Path:
    return resource_root() / "assets"


def icon_file(name: str = "icon.ico") -> Path:
    return assets_dir() / name


def data_dir() -> Path:
    return writable_root() / "data"


def banner_argv(spec_path: Path, python: str) -> list[str]:
    """横幅子进程命令行。

    exe 模式下不存在可调用的 Python 解释器，因此复用同一个 exe，
    以 ``--cc-banner`` 参数进入横幅窗口模式。
    """
    if is_frozen():
        return [sys.executable, "--cc-banner", str(spec_path)]
    return [python, "-m", "agent.banner_window", str(spec_path)]
