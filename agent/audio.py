"""音频：教室麦克风监听 + 管理端麦克风对讲。

统一格式：16 kHz / 单声道 / 16-bit PCM（浏览器端负责重采样）。
对讲开启时采集端**立即停止向管理端推送监听音频**（避免啸叫与回声），
并把收到的管理端 PCM 写入本机扬声器播放。

PyAudio 为可选依赖：缺失或无音频设备时，服务照常运行，状态接口会明确
标记 ``available=false``，管理端会提示「本机音频设备不可用」。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from agent.config import Config

logger = logging.getLogger("cc.audio")

try:
    import pyaudio  # type: ignore
    PYAUDIO_OK = True
except Exception:  # noqa: BLE001
    PYAUDIO_OK = False


class AudioHub:
    def __init__(self, cfg: Config, runtime: Any):
        self.cfg = cfg
        self.runtime = runtime
        self._paused = False
        self._talk_mode = False
        self._stop_event = threading.Event()
        self._pa: Any = None
        self._in_stream: Any = None
        self._out_stream: Any = None
        self._out_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=40)
        self.available = False
        self.last_error = ""
        self.bytes_in = 0
        self.bytes_out = 0
        threading.Thread(target=self._play_loop, name="cc-audio-out", daemon=True).start()
        self._open()

    # ------------------------------------------------------------ 生命周期
    def _open(self) -> None:
        if not PYAUDIO_OK:
            self.last_error = "未安装 PyAudio，音频监听与对讲不可用"
            self.available = False
            return
        if not self.cfg.get("audio.enabled", True):
            self.last_error = "音频已在配置中禁用"
            self.available = False
            return
        rate = int(self.cfg.get("audio.sample_rate", 16000))
        chunk = int(self.cfg.get("audio.chunk", 1024))
        try:
            self._pa = pyaudio.PyAudio()
            self._in_stream = self._pa.open(
                format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                frames_per_buffer=chunk, stream_callback=self._in_callback,
            )
            self._out_stream = self._pa.open(
                format=pyaudio.paInt16, channels=1, rate=rate, output=True,
                frames_per_buffer=chunk,
            )
            self._in_stream.start_stream()
            self.available = True
            self.last_error = ""
            logger.info("音频设备已就绪：%dHz 单声道", rate)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"打开音频设备失败：{exc}"
            self.available = False
            self._close()

    def _close(self) -> None:
        for stream in (self._in_stream, self._out_stream):
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
        self._in_stream = self._out_stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:  # noqa: BLE001
                pass
            self._pa = None

    def pause(self) -> None:
        """休眠时释放麦克风/扬声器设备。"""
        self._paused = True
        self._close()
        self.available = False

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self._open()

    def stop(self) -> None:
        self._stop_event.set()
        self._close()

    # ------------------------------------------------------------ 数据通路
    def _in_callback(self, in_data: bytes, _frame_count: int,
                     _time_info: Any, _status: Any) -> tuple[None, int]:
        # PyAudio 回调线程：只做最轻量的入队操作
        if not self._paused and not self._talk_mode and self.runtime.active_count:
            self.bytes_in += len(in_data)
            self.runtime.broadcast_audio(in_data)
        return (None, pyaudio.paContinue if PYAUDIO_OK else 0)

    def play(self, pcm: bytes) -> None:
        """播放来自管理端的一段对讲音频。"""
        if not pcm or not self._talk_mode:
            return
        self.bytes_out += len(pcm)
        try:
            if self._out_queue.full():
                self._out_queue.get_nowait()
            self._out_queue.put_nowait(pcm)
        except (queue.Full, queue.Empty):
            pass

    def _play_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                pcm = self._out_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if not self._talk_mode:
                continue
            if self._out_stream is not None:
                try:
                    self._out_stream.write(pcm)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"播放对讲音频失败：{exc}"
            else:
                # 无音频设备时静默丢弃，避免队列堆积
                time.sleep(0.01)

    # ------------------------------------------------------------ 对讲开关
    def set_talk_mode(self, active: bool) -> bool:
        active = bool(active)
        if active == self._talk_mode:
            return self._talk_mode
        self._talk_mode = active
        self.runtime.talk_mode = active
        # 切换时清空缓冲，防止旧音频串音
        while not self._out_queue.empty():
            try:
                self._out_queue.get_nowait()
            except queue.Empty:
                break
        if active:
            self.runtime.log("info", "进入对讲模式：已关闭教室音频监听，开启扬声器")
            # 通知所有管理端停止播放监听音频
            self.runtime.broadcast_json({"type": "talk_state", "active": True})
        else:
            self.runtime.log("info", "退出对讲模式：已恢复教室音频监听")
            self.runtime.broadcast_json({"type": "talk_state", "active": False})
        self.runtime.broadcast_json({"type": "status", "talk_mode": active})
        return active

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "backend": "pyaudio" if PYAUDIO_OK else "unavailable",
            "pyaudio_installed": PYAUDIO_OK,
            "enabled": bool(self.cfg.get("audio.enabled", True)),
            "sample_rate": int(self.cfg.get("audio.sample_rate", 16000)),
            "talk_mode": self._talk_mode,
            "paused": self._paused,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "pending": self._out_queue.qsize(),
            "last_error": self.last_error,
        }
