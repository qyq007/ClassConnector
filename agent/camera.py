"""摄像头采集与 MJPEG 广播。

- 单个采集线程 + 多订阅者广播：多个管理端同时观看只占用一次摄像头。
- 画质可调：分辨率 / JPEG 质量 / 帧率，修改后自动重新打开设备。
- 优雅降级：无 OpenCV、无摄像头或读取失败时，输出带时间戳与设备信息的
  「测试画面」，保证局域网联调与演示始终可用。
- 休眠：无管理端连接时暂停线程并释放摄像头，唤醒后自动重连。
"""

from __future__ import annotations

import base64
import io
import logging
import math
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.config import Config, get_local_ip
from agent.platform_util import IS_WIN

logger = logging.getLogger("cc.camera")

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    CV2_OK = True
except Exception:  # noqa: BLE001
    CV2_OK = False

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
    PIL_OK = True
except Exception:  # noqa: BLE001
    PIL_OK = False

# 1x1 深蓝像素 JPEG，作为最后的兜底（连 Pillow 都没有的极简环境）
_FALLBACK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikx"
    "MC4pLSwzOko+MzZGNywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01"
    "T09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAAC"
    "AAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgED"
    "AwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhc"
    "YGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4"
    "iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5"
    "ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goO"
    "EhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4u"
    "Pk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDz6iiitiD/2Q=="
)

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int) -> Any:
    if not PIL_OK:
        return None
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


class CameraHub:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._reload_event = threading.Event()
        self._paused = False
        self._cap: Any = None
        self._cap_failed = False  # 打开失败后不逐帧重试，避免拖垮帧率
        self.last_jpeg: bytes = _FALLBACK_JPEG
        self.last_error = ""
        self.backend = "unknown"
        self.actual_size: tuple[int, int] = (0, 0)
        self.frames = 0
        self.bytes_sent = 0
        self.measured_fps = 0.0
        self._thread = threading.Thread(target=self._loop, name="cc-camera", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ 对外接口
    def subscribe(self) -> "queue.Queue[bytes]":
        q: queue.Queue = queue.Queue(maxsize=2)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: "queue.Queue[bytes]") -> None:
        with self._lock:
            self._subscribers.discard(q)

    def config(self) -> dict[str, Any]:
        return self.cfg.get("camera", {})

    def set_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        # 修改配置（尤其是设备索引）后允许重新探测摄像头
        allowed = {"index", "width", "height", "fps", "quality"}
        clean: dict[str, Any] = {}
        for key, value in patch.items():
            if key not in allowed:
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"参数 {key} 必须是整数") from None
            limits = {
                "index": (0, 15), "width": (320, 3840), "height": (240, 2160),
                "fps": (1, 30), "quality": (10, 100),
            }
            low, high = limits[key]
            clean[key] = max(low, min(high, value))
        if clean:
            current = self.config()
            current.update(clean)
            self.cfg.set("camera", current)
            self.cfg.save()
            self._cap_failed = False
            self._reload_event.set()
            self._wake_event.set()
        return self.config()

    def pause(self) -> None:
        self._paused = True
        self._release_cap()

    def resume(self) -> None:
        self._paused = False
        self._cap_failed = False  # 唤醒后重新探测一次设备
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._release_cap()

    def status(self) -> dict[str, Any]:
        cfg = self.config()
        return {
            "backend": self.backend,
            "available": self.backend == "opencv",
            "device_index": cfg.get("index", 0),
            "width": cfg.get("width", 1280),
            "height": cfg.get("height", 720),
            "fps": cfg.get("fps", 15),
            "quality": cfg.get("quality", 70),
            "actual_width": self.actual_size[0],
            "actual_height": self.actual_size[1],
            "measured_fps": round(self.measured_fps, 1),
            "frames": self.frames,
            "subscribers": len(self._subscribers),
            "paused": self._paused,
            "last_error": self.last_error,
            "opencv": CV2_OK,
        }

    def list_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        if CV2_OK:
            for index in range(4):
                cap = None
                try:
                    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW if IS_WIN else cv2.CAP_ANY)
                    if cap.isOpened():
                        devices.append({
                            "index": index,
                            "name": f"摄像头 {index}",
                            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                        })
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    if cap is not None:
                        cap.release()
        if not devices:
            devices.append({"index": -1, "name": "测试画面（未检测到摄像头）",
                            "width": 0, "height": 0})
        return devices

    def snapshot(self, wait: float = 2.0) -> bytes:
        """返回最新一帧；必要时短暂等待新帧。"""
        if self._paused:
            self.resume()
        deadline = time.monotonic() + wait
        before = self.frames
        while time.monotonic() < deadline:
            if self.frames > before:
                break
            time.sleep(0.05)
        return self.last_jpeg

    # ------------------------------------------------------------ 采集线程
    def _release_cap(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass

    def _open(self) -> Any:
        if not CV2_OK:
            self.last_error = "未安装 opencv-python，正在使用测试画面"
            self.backend = "test-pattern"
            self._cap_failed = True
            return None
        cfg = self.config()
        try:
            cap = cv2.VideoCapture(int(cfg.get("index", 0)),
                                   cv2.CAP_DSHOW if IS_WIN else cv2.CAP_ANY)
            if not cap.isOpened():
                cap.release()
                self.last_error = f"摄像头 {cfg.get('index', 0)} 不可用，正在使用测试画面"
                self.backend = "test-pattern"
                self._cap_failed = True
                return None
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg.get("width", 1280)))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg.get("height", 720)))
            cap.set(cv2.CAP_PROP_FPS, int(cfg.get("fps", 15)))
            self.actual_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
            self.backend = "opencv"
            self.last_error = ""
            self._cap_failed = False
            return cap
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"打开摄像头失败：{exc}"
            self.backend = "test-pattern"
            self._cap_failed = True
            return None

    def _test_frame(self) -> Any:
        """生成会随时间变化的测试画面（便于确认推流确实在刷新）。"""
        cfg = self.config()
        width = max(320, min(1920, int(cfg.get("width", 1280))))
        height = max(240, min(1080, int(cfg.get("height", 720))))
        if PIL_OK:
            img = Image.new("RGB", (width, height), (15, 23, 42))
            draw = ImageDraw.Draw(img)
            t = time.time()
            for i in range(0, width, 40):
                x = (i + int(t * 30)) % width
                draw.line((x, 0, x, height), fill=(30, 41, 59), width=1)
            radius = max(20, height // 12)
            cx = width // 2 + int((width // 3) * math.sin(t * 0.8))
            cy = height // 2 + int((height // 4) * math.cos(t * 0.6))
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                         fill=(37, 99, 235))
            f_big, f_mid, f_small = _font(max(24, height // 14)), _font(max(16, height // 26)), _font(max(13, height // 34))
            lines = [
                ("ClassConnector · 测试画面", f_big, (255, 255, 255)),
                (self.cfg.get("room_name", "未命名班级"), f_mid, (148, 197, 255)),
                (self.last_error or "未检测到真实摄像头，请在设置中选择设备索引", f_small, (250, 204, 21)),
                (f"{get_local_ip()}:{self.cfg.get('port', 8420)}   {datetime.now():%Y-%m-%d %H:%M:%S}",
                 f_small, (148, 163, 184)),
            ]
            y = height // 8
            for text, font, color in lines:
                draw.text((width // 16, y), text, font=font, fill=color)
                y += (font.size if hasattr(font, "size") else 20) + max(10, height // 30)
            return img
        if CV2_OK:
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:] = (30, 23, 15)
            cv2.putText(frame, "ClassConnector TEST PATTERN", (30, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            cv2.putText(frame, datetime.now().strftime("%H:%M:%S"), (30, 110),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 99, 37), 2)
            return frame
        return None

    def _encode(self, frame: Any) -> bytes | None:
        quality = int(self.config().get("quality", 70))
        if CV2_OK and isinstance(frame, np.ndarray):
            ok, buf = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            return buf.tobytes() if ok else None
        if PIL_OK and isinstance(frame, Image.Image):
            bio = io.BytesIO()
            frame.convert("RGB").save(bio, format="JPEG", quality=quality)
            return bio.getvalue()
        return _FALLBACK_JPEG

    def _publish(self, jpeg: bytes) -> None:
        self.last_jpeg = jpeg
        self.frames += 1
        self.bytes_sent += len(jpeg)
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                if q.full():
                    q.get_nowait()
                q.put_nowait(jpeg)
            except (queue.Full, queue.Empty):
                pass

    def _loop(self) -> None:
        window_start, window_frames = time.monotonic(), 0
        while not self._stop_event.is_set():
            if self._paused:
                self._wake_event.wait(0.4)
                self._wake_event.clear()
                continue
            if self._reload_event.is_set():
                self._reload_event.clear()
                self._release_cap()
                self._cap_failed = False
            if self._cap is None and not self._cap_failed:
                self._cap = self._open()
            frame = None
            if self._cap is not None:
                try:
                    ok, frame = self._cap.read()
                    if not ok:
                        frame = None
                        self.last_error = "摄像头读取中断，正在使用测试画面"
                        self.backend = "test-pattern"
                        self._cap_failed = True
                        self._release_cap()
                except Exception as exc:  # noqa: BLE001
                    self.last_error = f"读取异常：{exc}"
                    self.backend = "test-pattern"
                    self._cap_failed = True
                    self._release_cap()
            if frame is None:
                frame = self._test_frame()
                self.backend = "test-pattern"
            jpeg = self._encode(frame)
            if jpeg:
                self._publish(jpeg)
            window_frames += 1
            now = time.monotonic()
            if now - window_start >= 1.0:
                self.measured_fps = window_frames / (now - window_start)
                window_start, window_frames = now, 0
            fps = max(1, int(self.config().get("fps", 15)))
            time.sleep(1.0 / fps)
        self._release_cap()
