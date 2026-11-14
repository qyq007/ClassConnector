"""采集端启动入口：``python -m agent``。

按顺序初始化摄像头、音频、横幅、TTS，注入运行时状态，启动 uvicorn，
并可选地启动系统托盘。Windows 下由安装器使用 pythonw.exe 调用，无控制台窗口。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from agent import __version__
from agent.audio import AudioHub
from agent.banner import BannerManager
from agent.camera import CameraHub
from agent.config import Config, has_password, load_config, log_path
from agent.server import create_app
from agent.state import Runtime
from agent.tray import start_tray
from agent.tts import TTSHub


def setup_logging(level: str = "INFO") -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(log_path(), encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"ClassConnector 采集端 v{__version__}")
    parser.add_argument("--host", default=None, help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认 8420）")
    parser.add_argument("--no-tray", action="store_true", help="禁用系统托盘")
    parser.add_argument("--log-level", default=None, help="日志级别")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    cfg: Config = load_config()
    setup_logging(args.log_level or cfg.get("log_level", "INFO"))
    logger = logging.getLogger("cc.main")

    if args.host:
        cfg.set("host", args.host)
    if args.port:
        cfg.set("port", args.port)

    host = str(cfg.get("host", "0.0.0.0"))
    port = int(cfg.get("port", 8420))
    logger.info("=" * 62)
    logger.info("ClassConnector 采集端 v%s 启动中", __version__)
    logger.info("管理地址: http://<本机IP>:%d   （配置文件: %s）", port, cfg.path)
    logger.info("=" * 62)

    if not has_password(cfg):
        logger.warning(
            "尚未设置安装密码：远程退出/改密功能已锁定。请运行 "
            "`python -m agent.install` 完成安装并设置密码。"
        )

    runtime = Runtime(cfg)
    camera = CameraHub(cfg)
    audio = AudioHub(cfg, runtime)
    banner = BannerManager(cfg, runtime)
    tts = TTSHub(cfg, runtime)
    runtime.attach(camera=camera, audio=audio, banner=banner, tts=tts)

    server_holder: dict[str, object] = {}

    def request_shutdown() -> None:
        server = server_holder.get("server")
        if server is not None:
            setattr(server, "should_exit", True)
        else:  # pragma: no cover - 仅测试环境
            os._exit(0)

    app = create_app(cfg, runtime, shutdown_fn=request_shutdown)

    if not args.no_tray:
        start_tray(cfg, port)

    try:
        import uvicorn
        config = uvicorn.Config(
            app, host=host, port=port,
            log_level=str(cfg.get("log_level", "INFO")).lower(),
            access_log=False, ws_ping_interval=20, ws_ping_timeout=20,
        )
        server = uvicorn.Server(config)
        server_holder["server"] = server
        server.run()
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")
    finally:
        logger.info("采集端已停止")
        camera.stop()
        audio.stop()
        banner.shutdown()


if __name__ == "__main__":
    main()
