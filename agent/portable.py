"""绿色便携模式入口：``python -m agent.portable``。

保证「不安装到电脑里」：

- 不写注册表 / 启动文件夹 / systemd / LaunchAgent，不创建系统服务或托盘；
- 不往用户目录或系统 Python 的 site-packages 写任何东西（依赖由启动脚本装到
  解压目录内的 ``runtime/venv``）；
- 配置、日志、横幅、TTS 缓存、PID 全部落在解压目录的 ``data/`` 下；
- 直接删除整个 ClassConnector 文件夹即完成卸载。

用法：
    python -m agent.portable                 # 启动并自动打开管理端
    python -m agent.portable --port 8420     # 指定端口
    python -m agent.portable --no-browser    # 不自动打开浏览器
    python -m agent.portable --set-password  # 设置/修改退出密码（只写 data/）
"""

from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def prepare() -> Path:
    """把所有运行时路径锁定到解压目录内的 data/。"""
    data = ROOT / "data"
    data.mkdir(parents=True, exist_ok=True)
    os.environ["CLASSCONNECTOR_HOME"] = str(data)
    os.environ.setdefault("CLASSCONNECTOR_CONFIG", str(data / "config.json"))
    marker = data / "PORTABLE.txt"
    if not marker.exists():
        marker.write_text(
            "ClassConnector portable mode\n"
            "All runtime data is stored in this folder (data/).\n"
            "No registry / autostart / system service / user profile writes.\n"
            "Delete the whole ClassConnector folder to uninstall.\n",
            encoding="utf-8",
        )
    return data


def lan_ips() -> list[str]:
    """列出可用于局域网访问的 IPv4 地址。"""
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.connect(("223.5.5.5", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip not in ips and not ip.startswith("127."):
            ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    return ips


def open_browser_later(url: str) -> None:
    def worker() -> None:
        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=worker, daemon=True).start()


def change_password() -> int:
    """交互式设置退出密码，仅写入 data/config.json。"""
    from agent.config import (
        has_password, load_config, set_password as _set_password, verify_password,
    )

    cfg = load_config()
    if has_password(cfg):
        old = getpass.getpass("当前退出密码: ")
        if not verify_password(cfg, old):
            print("密码错误，未作修改。")
            return 1
    else:
        print("首次设置退出密码。直接回车可跳过（跳过时远程退出功能保持锁定）。")

    while True:
        first = getpass.getpass("新退出密码（至少 4 位）: ")
        if not first:
            print("已取消，未设置密码。")
            return 0
        if len(first) < 4:
            print("密码太短，请重新输入。")
            continue
        second = getpass.getpass("再次输入: ")
        if first != second:
            print("两次输入不一致，请重新输入。")
            continue
        break

    _set_password(cfg, first)
    cfg.save()
    print("已保存到 data/config.json（仅保存在本文件夹内）。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ClassConnector 绿色便携模式（不写入系统）")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--host", default=None, help="监听地址")
    parser.add_argument("--log-level", default=None, help="日志级别")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--set-password", action="store_true", help="设置/修改退出密码")
    parser.add_argument("--version", action="store_true", help="显示版本号")
    args = parser.parse_args()

    data = prepare()

    if args.version:
        from agent import __version__
        print(__version__)
        return 0
    if args.set_password:
        return change_password()

    from agent.config import load_config
    cfg = load_config()
    port = args.port or int(cfg.get("port", 8420))
    host = args.host or str(cfg.get("host", "0.0.0.0"))

    print("=" * 62)
    print("  ClassConnector 绿色便携模式（不写入系统）")
    print("=" * 62)
    print(f"  数据目录 : {data}")
    print(f"  管理地址 : http://127.0.0.1:{port}/")
    for ip in lan_ips():
        print(f"  局域网   : http://{ip}:{port}/")
    print("  退出方式 : Ctrl+C 或关闭窗口；删除整个文件夹即卸载")
    print("  退出密码 : 双击 scripts/set-password.bat 设置（可选）")
    print("=" * 62)

    if not args.no_browser:
        open_browser_later(f"http://127.0.0.1:{port}/")

    # 绿色模式强制禁用托盘（托盘属于系统驻留），其余参数透传给采集端
    argv = [sys.argv[0], "--no-tray", "--port", str(port), "--host", host]
    if args.log_level:
        argv += ["--log-level", args.log_level]
    sys.argv = argv

    from agent.main import main as agent_main
    agent_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
