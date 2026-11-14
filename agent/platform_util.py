"""跨平台系统能力：开机自启、后台常驻、进程管理。

支持 Windows（注册表 Run + 隐藏启动脚本）、Linux（XDG autostart / systemd user）、
macOS（launchd LaunchAgent）。所有操作都可安全重复执行。
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent.config import app_dir, get_local_ip, log_path, pid_path

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC

AUTOSTART_KEY = "ClassConnector"


def project_root() -> Path:
    """仓库根目录（agent 包的上一级）。"""
    return Path(__file__).resolve().parent.parent


def python_exe(hidden: bool = True) -> str:
    """Windows 下优先返回 pythonw.exe，实现真正的无窗口后台运行。"""
    if IS_WIN and hidden:
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def launch_argv(hidden: bool = True) -> list[str]:
    return [python_exe(hidden), "-m", "agent"]


def _detached_kwargs() -> dict[str, Any]:
    if IS_WIN:
        flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
        return {"creationflags": flags, "close_fds": True}
    return {"start_new_session": True, "close_fds": True}


def read_pid() -> int | None:
    path = pid_path()
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if IS_WIN:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def is_running() -> bool:
    return pid_alive(read_pid())


def start_background(force: bool = False) -> int:
    """在后台启动采集端，返回 PID。已运行时默认直接返回现有 PID。"""
    existing = read_pid()
    if existing and not force and pid_alive(existing):
        return existing

    log_path().parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path(), "a", encoding="utf-8", buffering=1)
    argv = launch_argv()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root()) + os.pathsep + env.get("PYTHONPATH", "")
    env["CLASSCONNECTOR_BACKGROUND"] = "1"

    proc = subprocess.Popen(
        argv,
        cwd=str(project_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        **_detached_kwargs(),
    )
    pid_path().write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def stop_background() -> bool:
    """停止后台进程（仅供本地控制命令使用；远程退出必须走密码校验 API）。"""
    pid = read_pid()
    if not pid_alive(pid):
        pid_path().unlink(missing_ok=True)
        return False
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 15)  # SIGTERM -> uvicorn 优雅退出
        except OSError:
            pass
    try:
        pid_path().unlink()
    except OSError:
        pass
    return True


# ---------------------------------------------------------------------------
# 开机自启
# ---------------------------------------------------------------------------

def _win_autostart_script() -> Path:
    return app_dir() / "autostart.vbs"


def _enable_windows() -> str:
    import winreg  # type: ignore

    script = _win_autostart_script()
    exe = python_exe()
    root = str(project_root())
    # VBS 中双引号需写成 ""；0 = 隐藏窗口，False = 不等待
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\n'
        f'sh.CurrentDirectory = "{root}"\n'
        f'sh.Run """{exe}"" -m agent", 0, False\n'
    )
    script.write_text(vbs, encoding="utf-8")
    value = f'wscript.exe "{script}"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        winreg.SetValueEx(key, AUTOSTART_KEY, 0, winreg.REG_SZ, value)
    return f"注册表 Run -> {script}"


def _disable_windows() -> None:
    import winreg  # type: ignore
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOSTART_KEY)
    except FileNotFoundError:
        pass
    _win_autostart_script().unlink(missing_ok=True)


def _linux_desktop() -> Path:
    return Path.home() / ".config" / "autostart" / "classconnector.desktop"


def _enable_linux() -> str:
    desktop = _linux_desktop()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    exe = python_exe(hidden=False)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=ClassConnector 班级连接器\n"
        "Comment=教室采集端（后台运行）\n"
        f'Exec={exe} -m agent\n'
        f"Path={project_root()}\n"
        "Terminal=false\n"
        "Hidden=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    desktop.write_text(content, encoding="utf-8")
    return f"XDG autostart -> {desktop}"


def _disable_linux() -> None:
    _linux_desktop().unlink(missing_ok=True)
    _systemd_unit().unlink(missing_ok=True)


def _systemd_unit() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "classconnector.service"


def enable_systemd() -> str:
    """无图形会话（服务器版 Linux）可选用 systemd user service 实现自启。"""
    unit = _systemd_unit()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(
        "[Unit]\nDescription=ClassConnector Agent\nAfter=network-online.target\n\n"
        "[Service]\nType=simple\n"
        f"WorkingDirectory={project_root()}\n"
        f"Environment=PYTHONPATH={project_root()}\n"
        f"ExecStart={python_exe(hidden=False)} -m agent\n"
        "Restart=on-failure\nRestartSec=5\n\n"
        "[Install]\nWantedBy=default.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "classconnector.service"],
                   capture_output=True)
    return f"systemd user unit -> {unit}"


def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.classconnector.agent.plist"


def _enable_mac() -> str:
    plist = _mac_plist()
    plist.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": "com.classconnector.agent",
        "ProgramArguments": [python_exe(hidden=False), "-m", "agent"],
        "WorkingDirectory": str(project_root()),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
        "EnvironmentVariables": {"PYTHONPATH": str(project_root())},
    }
    with plist.open("wb") as fh:
        plistlib.dump(data, fh)
    subprocess.run(["launchctl", "load", "-w", str(plist)], capture_output=True)
    return f"LaunchAgent -> {plist}"


def _disable_mac() -> None:
    plist = _mac_plist()
    subprocess.run(["launchctl", "unload", "-w", str(plist)], capture_output=True)
    plist.unlink(missing_ok=True)


def enable_autostart() -> str:
    if IS_WIN:
        return _enable_windows()
    if IS_MAC:
        return _enable_mac()
    return _enable_linux()


def disable_autostart() -> None:
    if IS_WIN:
        _disable_windows()
    elif IS_MAC:
        _disable_mac()
    else:
        _disable_linux()


def autostart_status() -> dict[str, Any]:
    if IS_WIN:
        try:
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                value, _ = winreg.QueryValueEx(key, AUTOSTART_KEY)
            return {"enabled": True, "method": "registry-run", "target": value}
        except (OSError, ImportError):
            return {"enabled": False, "method": "registry-run"}
    if IS_MAC:
        return {"enabled": _mac_plist().exists(), "method": "launchd",
                "target": str(_mac_plist())}
    return {"enabled": _linux_desktop().exists(), "method": "xdg-autostart",
            "target": str(_linux_desktop())}


def local_url(port: int) -> str:
    return f"http://{get_local_ip()}:{port}"
