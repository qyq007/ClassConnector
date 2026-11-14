"""采集端本地控制命令（在教室电脑上运行）。

    python -m agent.control status            查看运行状态
    python -m agent.control open              打开管理端网页
    python -m agent.control stop              安全退出（需安装密码）
    python -m agent.control restart           重启（需安装密码）
    python -m agent.control set-password      修改安装密码
    python -m agent.control autostart on|off  开关开机自启
    python -m agent.control logs              查看最近日志
    python -m agent.control ask-stop          弹窗输入密码后退出（供托盘调用）
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from agent.config import load_config, log_path, verify_password
from agent.platform_util import (
    autostart_status, disable_autostart, enable_autostart, is_running,
    local_url, pid_path, project_root,
)


def _http(path: str, payload: dict | None = None, timeout: float = 6) -> dict:
    cfg = load_config()
    url = f"http://127.0.0.1:{int(cfg.get('port', 8420))}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _error(exc: Exception) -> None:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = json.loads(exc.read().decode()).get("detail", str(exc))
        except Exception:  # noqa: BLE001
            detail = str(exc)
        print(f"失败：{detail}")
    else:
        print(f"失败：{exc}")


def _password(prompt: str, gui: bool = False) -> str:
    if gui:
        try:
            import tkinter as tk
            from tkinter import simpledialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            value = simpledialog.askstring("ClassConnector", prompt,
                                           show="*", parent=root)
            root.destroy()
            return value or ""
        except Exception:  # noqa: BLE001
            pass
    try:
        return getpass.getpass(prompt + "：")
    except (EOFError, KeyboardInterrupt):
        return ""


def cmd_status(_args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"配置文件 : {cfg.path}")
    print(f"安装目录 : {project_root()}")
    print(f"后台进程 : {'运行中 (PID %s)' % pid_path().read_text().strip() if is_running() else '未运行'}")
    print(f"开机自启 : {'已启用' if autostart_status()['enabled'] else '未启用'} ({autostart_status()['method']})")
    print(f"管理地址 : {local_url(int(cfg.get('port', 8420)))}")
    try:
        health = _http("/api/health")
        print(f"服务状态 : 在线 · 教室「{health['room']}」· "
              f"{'休眠中' if health['sleeping'] else '活跃'} · v{health['version']}")
        detail = _http("/api/status")
        rt, cam, aud = detail["runtime"], detail["camera"], detail["audio"]
        print(f"连接数   : {rt['active']}   运行时长: {rt['uptime']} 秒")
        print(f"摄像头   : {cam['backend']} · {cam['measured_fps']} fps · 画质 {cam['quality']}")
        print(f"音频     : {'可用' if aud['available'] else '不可用'} · "
              f"{'对讲中' if aud['talk_mode'] else '待机'}")
    except Exception as exc:  # noqa: BLE001
        print(f"服务状态 : 无法连接（{exc}）")
    return 0


def cmd_open(_args: argparse.Namespace) -> int:
    url = local_url(int(load_config().get("port", 8420)))
    print("打开", url)
    webbrowser.open(url)
    return 0


def _agent_action(action: str, gui: bool = False) -> int:
    password = _password(f"请输入安装密码以{action}采集端", gui)
    if not password:
        print("已取消")
        return 1
    try:
        result = _http(f"/api/agent/{action}", {"password": password})
        print(result.get("message", "指令已发送"))
        return 0
    except Exception as exc:  # noqa: BLE001
        _error(exc)
        if gui:
            try:
                import tkinter.messagebox as mb
                mb.showerror("ClassConnector", f"无法{action}采集端，请检查密码")
            except Exception:  # noqa: BLE001
                pass
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    return _agent_action("stop")


def cmd_restart(args: argparse.Namespace) -> int:
    return _agent_action("restart")


def cmd_ask_stop(_args: argparse.Namespace) -> int:
    return _agent_action("stop", gui=True)


def cmd_set_password(_args: argparse.Namespace) -> int:
    old = _password("当前安装密码")
    new = _password("新安装密码（至少 4 位）")
    if not old or not new:
        print("已取消")
        return 1
    try:
        _http("/api/password/change", {"old_password": old, "new_password": new})
        print("安装密码已修改，所有管理端登录会话已失效")
        return 0
    except Exception as exc:  # noqa: BLE001
        _error(exc)
        return 1


def cmd_autostart(args: argparse.Namespace) -> int:
    if args.value == "on":
        print("已启用开机自启：", enable_autostart())
        return 0
    if args.value == "off":
        cfg = load_config()
        password = _password("请输入安装密码以关闭开机自启")
        if not verify_password(cfg, password):
            print("密码错误，操作已取消")
            return 1
        disable_autostart()
        print("已关闭开机自启")
        return 0
    print(autostart_status())
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    path: Path = log_path()
    if not path.exists():
        print("暂无日志文件：", path)
        return 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-int(args.lines):]:
        print(line)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ClassConnector 采集端本地控制")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="查看运行状态")
    sub.add_parser("open", help="打开管理端网页")
    sub.add_parser("stop", help="安全退出（需安装密码）")
    sub.add_parser("restart", help="重启（需安装密码）")
    sub.add_parser("ask-stop", help="弹窗输入密码后退出")
    sub.add_parser("set-password", help="修改安装密码")
    p_auto = sub.add_parser("autostart", help="开关开机自启")
    p_auto.add_argument("value", nargs="?", choices=["on", "off", "status"], default="status")
    p_logs = sub.add_parser("logs", help="查看最近日志")
    p_logs.add_argument("--lines", type=int, default=30)
    args = parser.parse_args()

    handlers: dict[str, Any] = {
        "status": cmd_status, "open": cmd_open, "stop": cmd_stop,
        "restart": cmd_restart, "ask-stop": cmd_ask_stop,
        "set-password": cmd_set_password, "autostart": cmd_autostart,
        "logs": cmd_logs,
    }
    if args.command not in handlers:
        parser.print_help()
        return 0
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
