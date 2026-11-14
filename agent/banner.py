"""横幅通知管理（服务端）。

管理端发送 Markdown 长文本横幅 -> 采集端弹出全屏置顶窗口 -> 学生签收 ->
签收状态实时回传所有管理端。支持紧急事件（红色样式 + 独立警报音）、
Edge TTS 播报、自动关闭、历史记录与撤回。

横幅窗口运行在**独立子进程**中：即使窗口崩溃/无图形界面，也不会影响
采集端服务；签收通过本地 HTTP 接口（内部令牌）回传。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from agent.config import Config, app_dir
from agent.platform_util import IS_LINUX, IS_MAC, IS_WIN, project_root, python_exe

logger = logging.getLogger("cc.banner")


def _new_id() -> str:
    return f"bn-{time.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"


class BannerManager:
    def __init__(self, cfg: Config, runtime: Any):
        self.cfg = cfg
        self.runtime = runtime
        self.history: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.current_id: str | None = None
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._spec_dir = app_dir() / "banners"
        self._spec_dir.mkdir(parents=True, exist_ok=True)
        self._timers: dict[str, threading.Timer] = {}

    # ------------------------------------------------------------ 发送
    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        markdown = str(payload.get("markdown") or payload.get("content") or "").strip()
        if not markdown and not str(payload.get("title") or "").strip():
            raise ValueError("横幅标题与内容不能同时为空")
        banner: dict[str, Any] = {
            "id": str(payload.get("id") or _new_id()),
            "title": str(payload.get("title") or "班级通知").strip()[:120],
            "markdown": markdown[:20000],
            "urgent": bool(payload.get("urgent", False)),
            "need_ack": bool(payload.get("need_ack",
                                         self.cfg.get("banner.need_ack_default", True))),
            "tts": bool(payload.get("tts", self.cfg.get("banner.tts_default", True))),
            "voice": str(payload.get("voice") or self.cfg.get("tts.voice", "")),
            "duration": max(0, min(3600, int(payload.get("duration")
                                             or self.cfg.get("banner.auto_close", 0) or 0))),
            "created_at": time.time(),
            "status": "showing",
            "acked_at": None,
            "ack_source": None,
            "display_mode": "pending",
        }
        with self._lock:
            self._dismiss_current(reason="replaced", broadcast=True)
            self.history[banner["id"]] = banner
            while len(self.history) > 100:
                self.history.popitem(last=False)
            self.current_id = banner["id"]

        banner["display_mode"] = self._spawn(banner)
        self.runtime.log("info",
                         f"收到横幅「{banner['title']}」"
                         f"（{'紧急' if banner['urgent'] else '普通'}，"
                         f"{'需签收' if banner['need_ack'] else '免签收'}）")
        self.runtime.broadcast_json({"type": "banner", "banner": self.public(banner)})

        if banner["tts"] and self.runtime.tts is not None:
            self.runtime.tts.speak(
                f"{banner['title']}。{banner['markdown']}" if banner["markdown"] else banner["title"],
                urgent=banner["urgent"], voice=banner["voice"] or None,
            )
        if banner["duration"] > 0:
            timer = threading.Timer(banner["duration"], self._auto_close,
                                    args=(banner["id"],))
            timer.daemon = True
            self._timers[banner["id"]] = timer
            timer.start()
        return self.public(banner)

    @staticmethod
    def public(banner: dict[str, Any]) -> dict[str, Any]:
        """广播给管理端时不必携带全文以外的敏感信息（当前无敏感字段）。"""
        return dict(banner)

    # ------------------------------------------------------------ 签收 / 关闭
    def ack(self, banner_id: str, source: str = "desktop") -> dict[str, Any]:
        with self._lock:
            banner = self.history.get(banner_id)
            if not banner:
                raise KeyError("横幅不存在")
            if banner["status"] != "acked":
                banner["status"] = "acked"
                banner["acked_at"] = time.time()
                banner["ack_source"] = source
        self.runtime.log("info", f"横幅「{banner['title']}」已签收（来源：{source}）")
        self.runtime.broadcast_json({
            "type": "banner_ack", "id": banner_id,
            "acked_at": banner["acked_at"], "status": "acked",
        })
        return self.public(banner)

    def dismiss(self, banner_id: str | None = None, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            target = banner_id or self.current_id
            banner = self.history.get(target) if target else None
            self._dismiss_current(reason=reason, broadcast=False)
            if banner and banner["status"] == "showing":
                banner["status"] = "dismissed"
            timer = self._timers.pop(target, None) if target else None
        if timer:
            timer.cancel()
        if banner:
            self.runtime.log("info", f"横幅「{banner['title']}」已关闭（{reason}）")
            self.runtime.broadcast_json({
                "type": "banner_dismissed", "id": banner["id"],
                "reason": reason, "status": banner["status"],
            })
        return {"ok": True, "id": target, "status": banner["status"] if banner else "none"}

    def _auto_close(self, banner_id: str) -> None:
        self._timers.pop(banner_id, None)
        if self.current_id == banner_id:
            self.dismiss(banner_id, reason="timeout")

    def _dismiss_current(self, reason: str, broadcast: bool = True) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        old_id, self.current_id = self.current_id, None
        if old_id and broadcast:
            banner = self.history.get(old_id)
            if banner and banner["status"] == "showing":
                banner["status"] = "dismissed"
            self.runtime.broadcast_json({"type": "banner_dismissed",
                                         "id": old_id, "reason": reason})

    def list_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(reversed(list(self.history.values())))[:limit]
        return [self.public(item) for item in items]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current": self.current_id,
                "showing": self.current_id is not None,
                "total": len(self.history),
                "acked": sum(1 for b in self.history.values() if b["status"] == "acked"),
            }

    def shutdown(self) -> None:
        with self._lock:
            self._dismiss_current(reason="shutdown", broadcast=False)
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    # ------------------------------------------------------------ 子进程
    def _spawn(self, banner: dict[str, Any]) -> str:
        # 无图形会话（例如 Linux 服务器）不弹窗，改由管理端网页预览
        if IS_LINUX and not (_has_display()):
            self.runtime.log(
                "warning",
                "当前无图形桌面会话，横幅窗口未弹出；可在管理端「网页预览」查看效果，"
                "签收状态仍会记录",
            )
            self.runtime.broadcast_json({
                "type": "banner_headless", "id": banner["id"],
                "message": "采集端无图形界面，横幅以网页预览方式呈现",
            })
            return "headless"

        spec = {
            **banner,
            "room": self.cfg.get("room_name", "班级"),
            "api_base": f"http://127.0.0.1:{int(self.cfg.get('port', 8420))}",
            "token": self.runtime.internal_token,
        }
        spec_path = self._spec_dir / f"{banner['id']}.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        env = {**dict(os.environ), "PYTHONPATH": str(project_root())}
        kwargs: dict[str, Any] = {
            "cwd": str(project_root()), "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        }
        if IS_WIN:
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            kwargs["close_fds"] = False
        else:
            kwargs["start_new_session"] = True
            kwargs["close_fds"] = True
        try:
            proc = subprocess.Popen(
                [python_exe(hidden=IS_WIN), "-m", "agent.banner_window", str(spec_path)],
                **kwargs,
            )
        except OSError as exc:
            self.runtime.log("warning", f"横幅窗口启动失败：{exc}")
            spec_path.unlink(missing_ok=True)
            return "failed"

        self._proc = proc
        threading.Thread(target=self._watch, args=(proc, banner["id"], spec_path),
                         name="cc-banner-watch", daemon=True).start()
        return "desktop"

    def _watch(self, proc: subprocess.Popen, banner_id: str, spec_path: Path) -> None:
        proc.wait()
        spec_path.unlink(missing_ok=True)
        with self._lock:
            if self._proc is proc:
                self._proc = None
            if self.current_id == banner_id:
                self.current_id = None
            banner = self.history.get(banner_id)
            if banner and banner["status"] == "showing":
                banner["status"] = "closed"
                self.runtime.broadcast_json({
                    "type": "banner_dismissed", "id": banner_id,
                    "reason": "window-closed", "status": "closed",
                })


def _has_display() -> bool:
    import os
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) or IS_WIN or IS_MAC
