"""运行时状态：管理端连接、空闲休眠/唤醒、消息广播、访问令牌、日志缓冲。

「没有设备连接时休眠」的实现：当管理端 WebSocket 连接数与视频流订阅数
之和为 0 且持续超过 ``idle_timeout`` 秒时，暂停摄像头与音频采集线程并
释放设备；一旦有新连接立即唤醒。横幅、TTS、对讲服务始终保持可用。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agent.config import Config

logger = logging.getLogger("cc.state")


@dataclass
class Client:
    id: str
    queue: "asyncio.Queue[tuple[str, Any]]"
    addr: str = ""
    authed: bool = False
    joined_at: float = field(default_factory=time.time)


class Runtime:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.clients: dict[str, Client] = {}
        self.stream_clients = 0
        self.sleeping = False
        self.talk_mode = False
        self.last_active = time.monotonic()
        self.started_at = time.time()
        self.internal_token = secrets.token_urlsafe(24)
        self._tokens: dict[str, float] = {}
        self.logs: deque[dict[str, Any]] = deque(maxlen=300)
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None

        # 由 main.py 注入，避免在状态模块内产生循环依赖
        self.camera: Any = None
        self.audio: Any = None
        self.banner: Any = None
        self.tts: Any = None

    # ---------------------------------------------------------------- 基础
    def attach(self, *, camera=None, audio=None, banner=None, tts=None) -> None:
        self.camera = camera if camera is not None else self.camera
        self.audio = audio if audio is not None else self.audio
        self.banner = banner if banner is not None else self.banner
        self.tts = tts if tts is not None else self.tts

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._loop_thread_id = threading.get_ident()

    @property
    def token_required(self) -> bool:
        return bool(self.cfg.get("require_auth", False))

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self.clients) + self.stream_clients

    def touch(self) -> None:
        self.last_active = time.monotonic()
        if self.sleeping:
            self.wake()

    # ---------------------------------------------------------------- 连接
    def add_client(self, client: Client) -> None:
        with self._lock:
            self.clients[client.id] = client
        self.touch()
        self.log("info", f"管理端接入 {client.addr}（当前 {self.active_count} 路）")

    def remove_client(self, client_id: str) -> None:
        with self._lock:
            self.clients.pop(client_id, None)
        self.last_active = time.monotonic()
        self.log("info", f"管理端断开 {client_id}（当前 {self.active_count} 路）")

    def add_stream(self) -> None:
        with self._lock:
            self.stream_clients += 1
        self.touch()

    def remove_stream(self) -> None:
        with self._lock:
            self.stream_clients = max(0, self.stream_clients - 1)
        self.last_active = time.monotonic()

    # ---------------------------------------------------------------- 广播
    def broadcast(self, kind: str, payload: Any) -> None:
        """线程安全广播：采集线程 / TTS 线程 / 子进程回调均可直接调用。

        asyncio.Queue 只能在事件循环线程中操作，因此跨线程调用统一通过
        ``call_soon_threadsafe`` 投递，避免唤醒丢失与竞态。
        """
        loop = self._loop
        if (loop is not None and loop.is_running()
                and self._loop_thread_id is not None
                and threading.get_ident() != self._loop_thread_id):
            loop.call_soon_threadsafe(self._broadcast_in_loop, kind, payload)
        else:
            self._broadcast_in_loop(kind, payload)

    def _broadcast_in_loop(self, kind: str, payload: Any) -> None:
        with self._lock:
            targets = list(self.clients.values())
        for client in targets:
            try:
                client.queue.put_nowait((kind, payload))
            except asyncio.QueueFull:
                # 慢客户端丢帧，避免拖垮采集线程
                try:
                    client.queue.get_nowait()
                    client.queue.put_nowait((kind, payload))
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def broadcast_json(self, message: dict) -> None:
        self.broadcast("text", message)

    def broadcast_audio(self, pcm: bytes) -> None:
        if not self.talk_mode:
            self.broadcast("bytes", pcm)

    # ---------------------------------------------------------------- 令牌
    def issue_token(self, ttl: int = 8 * 3600) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.time()
            self._tokens = {k: v for k, v in self._tokens.items() if v > now}
            self._tokens[token] = now + ttl
        return token

    def valid_token(self, token: str | None, *, internal_ok: bool = False) -> bool:
        if not token:
            return False
        if internal_ok and secrets.compare_digest(token, self.internal_token):
            return True
        with self._lock:
            expire = self._tokens.get(token, 0)
        return expire > time.time()

    def revoke_tokens(self) -> None:
        with self._lock:
            self._tokens.clear()

    # ---------------------------------------------------------------- 休眠
    def sleep(self) -> None:
        if self.sleeping:
            return
        self.sleeping = True
        if self.camera:
            self.camera.pause()
        if self.audio:
            self.audio.pause()
        self.log("info", "无管理端连接，采集端进入休眠（已释放摄像头/麦克风）")
        self._notify_status()

    def wake(self) -> None:
        if not self.sleeping:
            return
        self.sleeping = False
        if self.camera:
            self.camera.resume()
        if self.audio:
            self.audio.resume()
        self.log("info", "检测到管理端连接，采集端已唤醒")
        self._notify_status()

    def check_idle(self) -> None:
        timeout = int(self.cfg.get("idle_timeout", 20) or 0)
        if timeout <= 0:
            return
        if self.active_count == 0 and not self.sleeping:
            if time.monotonic() - self.last_active >= timeout:
                self.sleep()
        elif self.active_count > 0 and self.sleeping:
            self.wake()

    def idle_remaining(self) -> int:
        timeout = int(self.cfg.get("idle_timeout", 20) or 0)
        if timeout <= 0 or self.active_count > 0 or self.sleeping:
            return -1
        return max(0, int(timeout - (time.monotonic() - self.last_active)))

    def _notify_status(self) -> None:
        self.broadcast_json({"type": "status", "sleeping": self.sleeping,
                             "active": self.active_count})

    # ---------------------------------------------------------------- 日志
    def log(self, level: str, message: str) -> None:
        entry = {"ts": time.time(), "level": level, "message": message}
        self.logs.append(entry)
        getattr(logger, level if level in ("debug", "info", "warning", "error") else "info")(
            message
        )

    def uptime(self) -> int:
        return int(time.time() - self.started_at)

    def snapshot(self) -> dict[str, Any]:
        return {
            "connections": len(self.clients),
            "streams": self.stream_clients,
            "active": self.active_count,
            "sleeping": self.sleeping,
            "idle_remaining": self.idle_remaining(),
            "talk_mode": self.talk_mode,
            "uptime": self.uptime(),
            "started_at": self.started_at,
        }
