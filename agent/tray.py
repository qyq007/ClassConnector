"""可选的系统托盘图标（pystray + Pillow）。

未安装 pystray 或处于无图形会话时自动跳过，不影响采集端主体功能。
托盘的「退出」会启动一个独立进程弹出密码输入框，验证通过后才会停止服务。
"""

from __future__ import annotations

import logging
import subprocess
import threading
import webbrowser
from typing import Any

from agent.config import Config
from agent.platform_util import IS_WIN, python_exe

logger = logging.getLogger("cc.tray")


def _make_image() -> Any:
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=14,
                           fill=(37, 99, 235, 255))
    draw.ellipse((14, 14, 50, 50), outline=(255, 255, 255, 235), width=4)
    draw.line((32, 14, 32, 50), fill=(255, 255, 255, 235), width=3)
    draw.line((14, 32, 50, 32), fill=(255, 255, 255, 235), width=3)
    return img


def start_tray(cfg: Config, port: int) -> bool:
    """启动托盘线程；返回是否成功启动。"""
    try:
        import pystray  # type: ignore
    except ImportError:
        logger.info("未安装 pystray，跳过系统托盘（可用管理端网页管理）")
        return False
    try:
        image = _make_image()
    except Exception as exc:  # noqa: BLE001 - 无图形环境下降级
        logger.info("托盘图标不可用：%s", exc)
        return False

    url = f"http://127.0.0.1:{port}/"

    def open_manager(_icon: Any, _item: Any) -> None:
        webbrowser.open(url)

    def request_exit(_icon: Any, _item: Any) -> None:
        # 独立进程负责弹密码框 + 校验 + 停止服务，避免 tkinter 线程限制
        try:
            subprocess.Popen(
                [python_exe(hidden=IS_WIN), "-m", "agent.control", "ask-stop"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=not IS_WIN,
                creationflags=0x08000000 if IS_WIN else 0,
            )
        except OSError as exc:
            logger.warning("无法启动退出确认窗口：%s", exc)

    menu = pystray.Menu(
        pystray.MenuItem("ClassConnector · 后台运行中", lambda i, it: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开管理端", open_manager, default=True),
        pystray.MenuItem("退出（需安装密码）", request_exit),
    )
    icon = pystray.Icon("classconnector", image, "ClassConnector", menu)

    def run() -> None:
        try:
            icon.run()
        except Exception as exc:  # noqa: BLE001
            logger.info("系统托盘退出：%s", exc)

    threading.Thread(target=run, name="cc-tray", daemon=True).start()
    logger.info("系统托盘已启动，可通过托盘安全退出")
    return True
