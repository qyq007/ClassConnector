# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建配置：产出单文件、无控制台的 ClassConnector.exe。

用法（在 Windows + Python 3.11 上）：
    python scripts/build_exe.py

``CC_LITE=1`` 时跳过可选依赖收集，供 CI / 无图形环境快速自检打包链路。
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)  # noqa: F821  PyInstaller 注入
LITE = os.environ.get("CC_LITE") == "1"

datas = [
    (str(ROOT / "manager"), "manager"),   # 管理端静态页面（含图标）
    (str(ROOT / "assets"), "assets"),     # 应用图标 / ico
]
binaries = []

# 函数内 import 与可选依赖需要显式声明，保证冻结后的 exe 里都能找到
hiddenimports = [
    "agent.audio", "agent.banner", "agent.banner_window", "agent.camera",
    "agent.compat", "agent.config", "agent.control", "agent.desktop",
    "agent.install", "agent.main", "agent.markdown_render", "agent.paths",
    "agent.platform_util", "agent.portable", "agent.screen", "agent.server",
    "agent.state", "agent.tray", "agent.tts",
    "fastapi", "starlette", "pydantic", "multipart", "PIL", "tkinter",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.websockets_sansio_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "websockets", "websockets.server", "websockets.http11",
]

# 可选依赖：装了就打进 exe（摄像头 / 音频 / TTS / 截图 / 播放），
# 没装也不会让构建失败，程序会自动降级。
if not LITE:
    for package in ("cv2", "numpy", "mss", "pyaudio", "edge_tts",
                    "pygame", "pystray", "websockets"):
        try:
            extra_datas, extra_binaries, extra_hidden = collect_all(package)
            datas += extra_datas
            binaries += extra_binaries
            hiddenimports += extra_hidden
        except Exception:  # noqa: BLE001  未安装该可选包时静默跳过
            pass

a = Analysis(  # noqa: F821
    [str(ROOT / "app_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

# Windows 才能把 .ico 写进可执行文件；其它平台留空（用于本地自检构建）
ICON = str(ROOT / "assets" / "icon.ico") if os.name == "nt" else None

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ClassConnector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # 无控制台窗口，双击即图形界面
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
