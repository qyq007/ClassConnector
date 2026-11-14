"""ClassConnector 桌面应用：图形设置窗口 + 内嵌采集端服务。

双击编译出的 ``ClassConnector.exe`` 即可运行，**不需要命令行、不需要 .bat、
不需要用户自己安装 Python**。窗口只提供设置：摄像头、播报语音与音效、
网络与安全；底部一条状态栏显示服务状态与局域网地址。

设计要点：

- 服务跑在后台线程，tkinter 主线程只负责界面，互不阻塞；
- 摄像头枚举 / 选择是**主机特权**，只有本窗口能列出本机全部摄像头，
  网络侧管理端默认只能使用这里选定的那一路（可在窗口里显式放开）；
- 所有运行时数据落在 exe 同目录 ``data/``，不写注册表、不自启、
  不装系统 Python，删除文件夹即卸载；
- ``--cc-banner`` 参数供 PyInstaller 打包后的横幅子进程复用同一个 exe。

源码模式同样可用：``python -m agent.desktop``。
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from agent import __version__
from agent.paths import data_dir, icon_file

RESOLUTIONS = ["320x240", "640x480", "1280x720", "1920x1080"]
FPS_CHOICES = ["5", "10", "15", "20", "25", "30"]
RATE_CHOICES = ["-20%", "-10%", "+0%", "+10%", "+20%"]
VOLUME_CHOICES = ["-20%", "-10%", "+0%", "+10%", "+20%"]


# ---------------------------------------------------------------- 环境准备
def prepare_data_dir() -> Path:
    """把运行时数据锁定到绿色目录（exe 同目录 / 源码目录的 data/）。"""
    data = data_dir()
    data.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CLASSCONNECTOR_HOME", str(data))
    os.environ.setdefault("CLASSCONNECTOR_CONFIG", str(data / "config.json"))
    marker = data / "PORTABLE.txt"
    if not marker.exists():
        marker.write_text(
            "ClassConnector desktop / portable mode\n"
            "All runtime data stays in this folder (data/).\n"
            "No registry, autostart, system service or user-profile writes.\n"
            "Delete the whole folder to uninstall.\n",
            encoding="utf-8",
        )
    return data


def setup_desktop_logging(level: str = "INFO") -> None:
    """窗口程序可能没有 stdout（``--windowed``），日志只写文件。"""
    from agent.config import log_path

    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(log_path(), encoding="utf-8"))
    except OSError:
        pass
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
        force=True,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def lan_ips() -> list[str]:
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


# ---------------------------------------------------------------- 控制层
class DesktopController:
    """界面与采集端之间的逻辑层（不依赖 tkinter，便于单独测试）。"""

    def __init__(self, cfg: Any = None):
        from agent.audio import AudioHub
        from agent.banner import BannerManager
        from agent.camera import CameraHub
        from agent.config import TTS_VOICES, load_config
        from agent.state import Runtime
        from agent.tts import TTSHub

        self.cfg = cfg or load_config()
        self.runtime = Runtime(self.cfg)
        self.camera = CameraHub(self.cfg)
        self.audio = AudioHub(self.cfg, self.runtime)
        self.banner = BannerManager(self.cfg, self.runtime)
        self.tts = TTSHub(self.cfg, self.runtime)
        self.runtime.attach(camera=self.camera, audio=self.audio,
                            banner=self.banner, tts=self.tts)
        self.voices = TTS_VOICES

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._server_holder: dict[str, Any] = {}
        self.service_port: int = int(self.cfg.get("port", 8420))

    # ------------------------------------------------------------ 服务生命周期
    def start_service(self, host: str | None = None, port: int | None = None) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            host = host or str(self.cfg.get("host", "0.0.0.0"))
            port = int(port or self.cfg.get("port", 8420))
            self.service_port = port

            from agent.server import create_app
            holder: dict[str, Any] = {}

            def shutdown() -> None:
                server = holder.get("server")
                if server is not None:
                    server.should_exit = True

            app = create_app(self.cfg, self.runtime, shutdown_fn=shutdown)

            def run() -> None:
                import uvicorn
                config = uvicorn.Config(
                    app, host=host, port=port, log_level="warning",
                    access_log=False, ws_ping_interval=20, ws_ping_timeout=20,
                )
                server = uvicorn.Server(config)
                holder["server"] = server
                try:
                    server.run()
                except Exception as exc:  # noqa: BLE001
                    self.runtime.log("error", f"服务线程异常：{exc}")

            thread = threading.Thread(target=run, name="cc-desktop-server", daemon=True)
            self._thread = thread
            self._server_holder = holder
            thread.start()
            self.runtime.log("info", f"采集端服务已启动：{host}:{port}")
            return True

    def stop_service(self) -> None:
        with self._lock:
            server = self._server_holder.get("server")
            thread = self._thread
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=6)
        with self._lock:
            self._thread = None
            self._server_holder = {}

    def restart_service(self) -> bool:
        self.stop_service()
        return self.start_service()

    def is_running(self) -> bool:
        with self._lock:
            thread = self._thread
            server = self._server_holder.get("server")
        return bool(thread and thread.is_alive()
                    and server is not None and not server.should_exit)

    def shutdown(self) -> None:
        self.stop_service()
        self.camera.stop()
        self.audio.stop()
        self.banner.shutdown()

    # ------------------------------------------------------------ 设置读写
    def local_devices(self) -> list[dict[str, Any]]:
        """本机特权：枚举本机全部摄像头（网络侧不会得到这个列表）。"""
        return self.camera.devices_view(remote=False)["devices"]

    def apply_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        """保存设置并让运行中的组件即时生效。返回新配置与端口是否变化。"""
        from agent.config import has_password

        patch = dict(values or {})

        # 摄像头：只有本机设置窗口能改 index / remote_select
        cam = patch.get("camera") or {}
        self.cfg.set("camera.remote_select", bool(cam.get("remote_select", False)))
        cam_clean = {k: cam[k] for k in
                     ("index", "width", "height", "fps", "quality") if k in cam}
        if cam_clean:
            self.camera.set_config(cam_clean, remote=False)

        tts = patch.get("tts") or {}
        for key in ("enabled", "voice", "rate", "volume", "urgent_alert"):
            if key in tts:
                self.cfg.set("tts." + key, tts[key])

        for key in ("room_name", "log_level"):
            if key in patch:
                self.cfg.set(key, patch[key])
        if "idle_timeout" in patch:
            self.cfg.set("idle_timeout", max(0, int(patch["idle_timeout"])))

        port_changed = False
        if "port" in patch:
            port = max(1, min(65535, int(patch["port"])))
            port_changed = port != int(self.cfg.get("port", 8420))
            self.cfg.set("port", port)

        if "require_auth" in patch:
            want = bool(patch["require_auth"])
            if want and not has_password(self.cfg):
                raise ValueError("启用管理密码登录前，请先设置退出密码")
            self.cfg.set("require_auth", want)
            self.runtime.revoke_tokens()

        self.cfg.save()
        return {"config": self.cfg.public(), "port_changed": port_changed}

    def status(self) -> dict[str, Any]:
        cam = self.camera.status()
        return {
            "running": self.is_running(),
            "port": self.service_port,
            "clients": self.runtime.active_count,
            "sleeping": self.runtime.sleeping,
            "camera_backend": cam.get("backend", "unknown"),
            "camera_fps": cam.get("measured_fps", 0),
            "camera_error": cam.get("last_error", ""),
            "tts": self.tts.status(),
            "addresses": [f"http://{ip}:{self.service_port}/" for ip in lan_ips()],
        }

    def test_speak(self, text: str = "同学们请注意，这是一条测试播报") -> dict[str, Any]:
        return self.tts.speak(text)

    def test_alert(self) -> None:
        """仅试听紧急警报音（不触发语音合成）。"""
        from agent.tts import ensure_alert_wav

        def worker() -> None:
            try:
                self.tts._play(str(ensure_alert_wav()))
            except Exception as exc:  # noqa: BLE001
                self.runtime.log("warning", f"警报音试听失败：{exc}")

        threading.Thread(target=worker, name="cc-alert-test", daemon=True).start()


# ---------------------------------------------------------------- 图形界面
class SettingsWindow:
    """纯设置主窗口：三个设置页 + 底部状态条。"""

    def __init__(self, controller: DesktopController, *, open_browser: bool = True):
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.simpledialog = simpledialog
        self.controller = controller
        self.open_browser = open_browser
        self._device_map: dict[str, int] = {}
        self._voice_map: dict[str, str] = {}

        cfg = controller.cfg
        self.root = tk.Tk()
        self.root.title(f"ClassConnector · 设置  v{__version__}")
        self.root.geometry("720x700")
        self.root.minsize(560, 600)
        self._set_icon()

        # ---- 变量 ----
        self.var_device = tk.StringVar()
        self.var_resolution = tk.StringVar()
        self.var_fps = tk.StringVar()
        self.var_quality = tk.IntVar(value=int(cfg.get("camera.quality", 70)))
        self.var_remote_select = tk.BooleanVar(
            value=bool(cfg.get("camera.remote_select", False)))

        self.var_tts_enabled = tk.BooleanVar(value=bool(cfg.get("tts.enabled", True)))
        self.var_voice = tk.StringVar()
        self.var_rate = tk.StringVar(value=str(cfg.get("tts.rate", "+0%")))
        self.var_volume = tk.StringVar(value=str(cfg.get("tts.volume", "+0%")))
        self.var_urgent_alert = tk.BooleanVar(
            value=bool(cfg.get("tts.urgent_alert", True)))

        self.var_room = tk.StringVar(value=str(cfg.get("room_name", "未命名班级")))
        self.var_port = tk.StringVar(value=str(cfg.get("port", 8420)))
        self.var_idle = tk.StringVar(value=str(cfg.get("idle_timeout", 20)))
        self.var_require_auth = tk.BooleanVar(value=bool(cfg.get("require_auth", False)))

        self.var_service = tk.StringVar(value="■ 未启动")
        self.var_conn = tk.StringVar(value="连接 0")
        self.var_caminfo = tk.StringVar(value="摄像头：检测中")
        self.var_address = tk.StringVar(value="")

        self._build()
        self._load_from_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()

    # ------------------------------------------------------------ 构建界面
    def _set_icon(self) -> None:
        try:
            self.root.iconbitmap(str(icon_file("icon.ico")))
        except Exception:  # noqa: BLE001  Linux 的 Tk 不认 .ico
            try:
                self._icon_image = self.tk.PhotoImage(file=str(icon_file("icon.png")))
                self.root.iconphoto(True, self._icon_image)
            except Exception:  # noqa: BLE001
                pass

    def _build(self) -> None:
        ttk = self.ttk
        outer = ttk.Frame(self.root, padding=(14, 12, 14, 10))
        outer.pack(fill="both", expand=True)

        # pack 按调用顺序分配空间：先把顶部与底部固定区域占位，
        # 再让 Notebook 拿剩余空间，否则窗口较小时按钮会被挤出可视区域。
        head = ttk.Frame(outer)
        head.pack(side="top", fill="x", pady=(0, 10))
        ttk.Label(head, text="ClassConnector", font=("Segoe UI", 15, "bold")).pack(side="left")
        ttk.Label(head, text="  教室电脑设置 · 修改后点击「保存设置」生效",
                  foreground="#64748b").pack(side="left")

        buttons = ttk.Frame(outer)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(buttons, text="打开管理端", command=self._open_manager).pack(side="left")
        ttk.Button(buttons, text="重启服务", command=self._restart).pack(side="left", padx=6)
        ttk.Button(buttons, text="退出", command=self._on_close).pack(side="right")
        ttk.Button(buttons, text="保存设置", command=self._save).pack(side="right", padx=6)

        status = ttk.LabelFrame(outer, text="运行状态", padding=(10, 8))
        status.pack(side="bottom", fill="x", pady=(10, 0))
        row1 = ttk.Frame(status); row1.pack(fill="x")
        ttk.Label(row1, textvariable=self.var_service, width=16).pack(side="left")
        ttk.Label(row1, textvariable=self.var_conn, width=12).pack(side="left")
        ttk.Label(row1, textvariable=self.var_caminfo).pack(side="left")
        row2 = ttk.Frame(status); row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="局域网：").pack(side="left")
        ttk.Label(row2, textvariable=self.var_address, foreground="#2563eb").pack(side="left")

        notebook = ttk.Notebook(outer)
        notebook.pack(side="top", fill="both", expand=True)
        self._tab_camera(notebook)
        self._tab_voice(notebook)
        self._tab_network(notebook)

    def _tab_camera(self, nb: Any) -> None:
        ttk = self.ttk
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="  摄像头  ")

        box = ttk.LabelFrame(tab, text="摄像头设备（仅本机可见）", padding=12)
        box.pack(fill="x")
        row = ttk.Frame(box); row.pack(fill="x")
        ttk.Label(row, text="设备：", width=9).pack(side="left")
        self.combo_device = ttk.Combobox(row, textvariable=self.var_device,
                                         state="readonly", width=38)
        self.combo_device.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="刷新设备", command=self._refresh_devices).pack(side="left", padx=(8, 0))
        ttk.Label(box, wraplength=600, foreground="#64748b",
                  text="只有这台电脑的设置窗口能列出并选择摄像头。"
                       "管理端默认只能看到这里指定的那一路画面，无法访问本机其他摄像头。"
                  ).pack(fill="x", pady=(8, 0))

        pic = ttk.LabelFrame(tab, text="画面参数", padding=12)
        pic.pack(fill="x", pady=(12, 0))
        r1 = ttk.Frame(pic); r1.pack(fill="x")
        ttk.Label(r1, text="分辨率：", width=9).pack(side="left")
        ttk.Combobox(r1, textvariable=self.var_resolution, state="readonly",
                     values=RESOLUTIONS, width=16).pack(side="left")
        ttk.Label(r1, text="   帧率：").pack(side="left")
        ttk.Combobox(r1, textvariable=self.var_fps, state="readonly",
                     values=FPS_CHOICES, width=8).pack(side="left")
        r2 = ttk.Frame(pic); r2.pack(fill="x", pady=(12, 0))
        ttk.Label(r2, text="JPEG 画质：", width=9).pack(side="left")
        self.lbl_quality = ttk.Label(r2, text="70", width=4)
        self.lbl_quality.pack(side="left")
        ttk.Scale(r2, from_=10, to=100, variable=self.var_quality,
                  command=self._on_quality).pack(side="left", fill="x", expand=True)

        lock = ttk.LabelFrame(tab, text="网络访问权限", padding=12)
        lock.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(
            lock, text="允许管理端在 Web 上枚举 / 切换摄像头",
            variable=self.var_remote_select,
        ).pack(anchor="w")
        ttk.Label(lock, wraplength=600, foreground="#b45309",
                  text="默认关闭。开启后，任何能访问本服务的管理端都可以查看并切换本机全部摄像头，"
                       "请仅在可信局域网内使用。"
                  ).pack(fill="x", pady=(6, 0))

    def _tab_voice(self, nb: Any) -> None:
        ttk = self.ttk
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="  播报与音效  ")

        box = ttk.LabelFrame(tab, text="Edge TTS 语音播报", padding=12)
        box.pack(fill="x")
        ttk.Checkbutton(box, text="启用横幅内容语音播报",
                        variable=self.var_tts_enabled).pack(anchor="w")
        r1 = ttk.Frame(box); r1.pack(fill="x", pady=(10, 0))
        ttk.Label(r1, text="播报语音：", width=10).pack(side="left")
        self.combo_voice = ttk.Combobox(r1, textvariable=self.var_voice,
                                        state="readonly", width=34)
        self.combo_voice.pack(side="left")
        r2 = ttk.Frame(box); r2.pack(fill="x", pady=(10, 0))
        ttk.Label(r2, text="语速：", width=10).pack(side="left")
        ttk.Combobox(r2, textvariable=self.var_rate, state="readonly",
                     values=RATE_CHOICES, width=9).pack(side="left")
        ttk.Label(r2, text="   音量：").pack(side="left")
        ttk.Combobox(r2, textvariable=self.var_volume, state="readonly",
                     values=VOLUME_CHOICES, width=9).pack(side="left")

        alert = ttk.LabelFrame(tab, text="紧急事件音效", padding=12)
        alert.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(alert, text="紧急通知先播放独立警报音（与普通通知区分）",
                        variable=self.var_urgent_alert).pack(anchor="w")
        btns = ttk.Frame(alert); btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="试听播报", command=self._test_speak).pack(side="left")
        ttk.Button(btns, text="试听警报音", command=self._test_alert).pack(side="left", padx=8)
        self.lbl_player = ttk.Label(alert, foreground="#64748b", wraplength=600)
        self.lbl_player.pack(fill="x", pady=(10, 0))
        ttk.Label(tab, wraplength=600, foreground="#64748b",
                  text="提示：Edge TTS 合成需要联网；本机播放优先使用 pygame / ffplay，"
                       "两者都没有时可在设置窗口的「设备状态」中查看提示。"
                  ).pack(fill="x", pady=(12, 0))

    def _tab_network(self, nb: Any) -> None:
        ttk = self.ttk
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="  网络与安全  ")

        box = ttk.LabelFrame(tab, text="设备信息", padding=12)
        box.pack(fill="x")
        rows = [
            ("班级名称", self.var_room, 26),
            ("服务端口", self.var_port, 10),
            ("空闲休眠（秒，0 = 不休眠）", self.var_idle, 10),
        ]
        for label, var, width in rows:
            row = ttk.Frame(box); row.pack(fill="x", pady=4)
            ttk.Label(row, text=label + "：", width=24).pack(side="left")
            ttk.Entry(row, textvariable=var, width=width).pack(side="left")

        sec = ttk.LabelFrame(tab, text="访问与退出密码", padding=12)
        sec.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(sec, text="管理端需要密码登录（所有管理操作均需验证）",
                        variable=self.var_require_auth).pack(anchor="w")
        ttk.Button(sec, text="设置 / 修改退出密码",
                   command=self._set_password).pack(anchor="w", pady=(10, 0))
        ttk.Label(sec, wraplength=600, foreground="#64748b",
                  text="密码以 PBKDF2 加盐哈希保存在 data/config.json，不会明文存储或返回给管理端。"
                  ).pack(fill="x", pady=(8, 0))

        info = ttk.LabelFrame(tab, text="局域网访问地址", padding=12)
        info.pack(fill="x", pady=(12, 0))
        self.lbl_addresses = ttk.Label(info, foreground="#2563eb", wraplength=600,
                                       justify="left")
        self.lbl_addresses.pack(fill="x")
        ttk.Label(tab, wraplength=600, foreground="#64748b",
                  text="同一局域网内的电脑 / 手机浏览器打开上面的地址即可进入管理端。"
                       "本程序不写注册表、不注册开机自启、不安装系统服务，"
                       "删除整个文件夹即完成卸载。"
                  ).pack(fill="x", pady=(12, 0))

    # ------------------------------------------------------------ 数据装载
    def _load_from_config(self) -> None:
        cfg = self.controller.cfg
        cam = cfg.get("camera", {})
        wh = f'{cam.get("width", 1280)}x{cam.get("height", 720)}'
        self.var_resolution.set(wh if wh in RESOLUTIONS else "1280x720")
        fps = str(cam.get("fps", 15))
        self.var_fps.set(fps if fps in FPS_CHOICES else "15")
        self.var_quality.set(int(cam.get("quality", 70)))
        self._on_quality()
        self._refresh_devices()

        self._voice_map = {v["name"]: v["id"] for v in self.controller.voices}
        self.combo_voice["values"] = list(self._voice_map)
        current = str(cfg.get("tts.voice", "zh-CN-XiaoxiaoNeural"))
        for name, voice_id in self._voice_map.items():
            if voice_id == current:
                self.var_voice.set(name)
                break
        else:
            self.var_voice.set(current)
        self.var_rate.set(str(cfg.get("tts.rate", "+0%")))
        self.var_volume.set(str(cfg.get("tts.volume", "+0%")))
        self._update_voice_status()

    def _refresh_devices(self) -> None:
        try:
            devices = self.controller.local_devices()
        except Exception as exc:  # noqa: BLE001
            devices = [{"index": -1, "name": f"枚举失败：{exc}"}]
        self._device_map = {
            (d["name"] + (f'（{d["width"]}×{d["height"]}）' if d.get("width") else "")):
                int(d["index"]) for d in devices
        }
        self.combo_device["values"] = list(self._device_map)
        current = int(self.controller.cfg.get("camera.index", 0))
        for label, idx in self._device_map.items():
            if idx == current:
                self.var_device.set(label)
                break
        else:
            if self._device_map:
                self.var_device.set(next(iter(self._device_map)))

    def _update_voice_status(self) -> None:
        tts = self.controller.tts.status()
        self.lbl_player.configure(
            text=f'播放器：{tts["player"]}  ·  Edge TTS：'
                 f'{"已安装" if tts["edge_tts_installed"] else "未安装（横幅不会朗读）"}'
                 f'  ·  已播报 {tts["spoken"]} 次'
        )

    # ------------------------------------------------------------ 交互
    def _on_quality(self, *_: Any) -> None:
        try:
            self.lbl_quality.configure(text=str(int(self.var_quality.get())))
        except Exception:  # noqa: BLE001
            pass

    def _collect(self) -> dict[str, Any]:
        wh = self.var_resolution.get().split("x")
        return {
            "camera": {
                "index": self._device_map.get(self.var_device.get(), 0),
                "width": int(wh[0]), "height": int(wh[1]),
                "fps": int(self.var_fps.get()),
                "quality": int(self.var_quality.get()),
                "remote_select": bool(self.var_remote_select.get()),
            },
            "tts": {
                "enabled": bool(self.var_tts_enabled.get()),
                "voice": self._voice_map.get(self.var_voice.get(), self.var_voice.get()),
                "rate": self.var_rate.get(), "volume": self.var_volume.get(),
                "urgent_alert": bool(self.var_urgent_alert.get()),
            },
            "room_name": self.var_room.get().strip() or "未命名班级",
            "port": int(self.var_port.get()),
            "idle_timeout": int(self.var_idle.get()),
            "require_auth": bool(self.var_require_auth.get()),
        }

    def _save(self) -> None:
        try:
            values = self._collect()
            result = self.controller.apply_settings(values)
        except (ValueError, TypeError) as exc:
            self.messagebox.showerror("设置无效", str(exc), parent=self.root)
            return
        if result["port_changed"]:
            self.controller.restart_service()
            self.messagebox.showinfo("已保存", "设置已保存，服务已按新端口重启。",
                                     parent=self.root)
        else:
            self.messagebox.showinfo("已保存", "设置已保存并即时生效。", parent=self.root)
        self._update_voice_status()

    def _restart(self) -> None:
        self.controller.restart_service()
        self.messagebox.showinfo("服务", "采集端服务已重启。", parent=self.root)

    def _open_manager(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{self.controller.service_port}/")

    def _test_speak(self) -> None:
        result = self.controller.test_speak()
        if not result.get("queued"):
            self.messagebox.showwarning("无法试听", result.get("reason", "播报未排队"),
                                        parent=self.root)
        else:
            self.messagebox.showinfo("试听", "已加入播报队列，请听教室电脑的声音。",
                                     parent=self.root)

    def _test_alert(self) -> None:
        self.controller.test_alert()
        self.messagebox.showinfo("试听", "正在播放紧急警报音。", parent=self.root)

    def _set_password(self) -> None:
        from agent.config import has_password, set_password, verify_password

        cfg = self.controller.cfg
        if has_password(cfg):
            old = self.simpledialog.askstring("验证", "请输入当前退出密码：",
                                              show="*", parent=self.root)
            if old is None:
                return
            if not verify_password(cfg, old):
                self.messagebox.showerror("密码错误", "当前密码不正确，未作修改。",
                                          parent=self.root)
                return
        first = self.simpledialog.askstring("设置退出密码", "新密码（至少 4 位）：",
                                            show="*", parent=self.root)
        if not first or len(first) < 4:
            self.messagebox.showerror("无效", "密码至少 4 位，未作修改。", parent=self.root)
            return
        second = self.simpledialog.askstring("设置退出密码", "再次输入：",
                                             show="*", parent=self.root)
        if first != second:
            self.messagebox.showerror("不一致", "两次输入不一致，未作修改。", parent=self.root)
            return
        set_password(cfg, first)
        self.messagebox.showinfo("完成", "退出密码已保存到 data/config.json。",
                                 parent=self.root)

    def _on_close(self) -> None:
        from agent.config import has_password, verify_password

        cfg = self.controller.cfg
        if has_password(cfg):
            pwd = self.simpledialog.askstring("退出确认", "请输入安装时设置的退出密码：",
                                              show="*", parent=self.root)
            if pwd is None:
                return
            if not verify_password(cfg, pwd):
                self.messagebox.showerror("密码错误", "密码不正确，程序继续运行。",
                                          parent=self.root)
                return
        try:
            self.controller.shutdown()
        finally:
            self.root.destroy()

    def _tick(self) -> None:
        try:
            st = self.controller.status()
            self.var_service.set("● 运行中" if st["running"] else "■ 已停止")
            self.var_conn.set(f'连接 {st["clients"]}' + (" · 休眠中" if st["sleeping"] else ""))
            self.var_caminfo.set(
                f'摄像头：{st["camera_backend"]} · {st["camera_fps"]} fps'
            )
            self.var_address.set(st["addresses"][0] if st["addresses"]
                                 else f'http://127.0.0.1:{st["port"]}/')
            self.lbl_addresses.configure(
                text="\n".join(st["addresses"]) or f'http://127.0.0.1:{st["port"]}/')
        except Exception:  # noqa: BLE001  界面刷新绝不打断主流程
            pass
        self.root.after(1000, self._tick)

    def run(self) -> None:
        self.root.mainloop()


# ---------------------------------------------------------------- 入口
def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)

    # PyInstaller 打包后没有独立 Python 解释器，横幅子进程复用本 exe
    if args_list and args_list[0] == "--cc-banner":
        if len(args_list) < 2:
            return 2
        sys.argv = [sys.argv[0], args_list[1]]
        from agent.banner_window import main as banner_main
        return banner_main()

    parser = argparse.ArgumentParser(
        description=f"ClassConnector 桌面设置窗口 v{__version__}")
    parser.add_argument("--version", action="store_true", help="显示版本号")
    parser.add_argument("--port", type=int, default=None, help="覆盖服务端口")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开管理端")
    parser.add_argument("--no-service", action="store_true", help="只打开设置窗口，不启动服务")
    parser.add_argument("--headless-check", action="store_true",
                        help="仅初始化控制层并打印状态（供无显示器环境自检）")
    args = parser.parse_args(args_list)

    if args.version:
        print(__version__)
        return 0

    data = prepare_data_dir()
    setup_desktop_logging()
    logger = logging.getLogger("cc.desktop")
    logger.info("ClassConnector 桌面版 v%s 启动，数据目录 %s", __version__, data)

    controller = DesktopController()
    if args.port:
        controller.cfg.set("port", args.port)
        controller.cfg.save()

    if args.headless_check:
        controller.start_service(port=args.port)
        time.sleep(1.0)
        print("controller:", controller.status())
        controller.shutdown()
        return 0

    if not args.no_service:
        controller.start_service(port=args.port)

    window = SettingsWindow(controller, open_browser=not args.no_browser)
    if not args.no_browser:
        def open_later() -> None:
            time.sleep(1.5)
            try:
                webbrowser.open(f"http://127.0.0.1:{controller.service_port}/")
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=open_later, daemon=True).start()

    window.run()
    logger.info("设置窗口已关闭，程序退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
