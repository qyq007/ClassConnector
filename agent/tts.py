"""语音播报：横幅内容使用 Edge TTS 朗读，紧急事件额外播放警报音。

- edge-tts 为可选依赖且需要联网；不可用时记录状态并跳过，绝不影响横幅显示。
- 播放优先级：ffplay → pygame → 系统命令（afplay / aplay / winsound）。
- 所有播报在独立线程串行执行，不阻塞 WebSocket 与 HTTP 服务。
- 把自定义音频放到 ``<数据目录>/urgent.wav`` 即可替换紧急警报音。
"""

from __future__ import annotations

import logging
import math
import os
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

from agent.config import Config, TTS_VOICES, app_dir
from agent.markdown_render import strip_markdown
from agent.platform_util import IS_MAC, IS_WIN

logger = logging.getLogger("cc.tts")

try:
    import edge_tts  # type: ignore
    EDGE_TTS_OK = True
except Exception:  # noqa: BLE001
    EDGE_TTS_OK = False


def ensure_alert_wav() -> Path:
    """生成（或复用）2 秒双音紧急警报，用户可用同名文件覆盖。"""
    path = app_dir() / "urgent.wav"
    if path.exists() and path.stat().st_size > 1000:
        return path
    rate = 44100
    duration = 2.0
    frames = bytearray()
    for i in range(int(rate * duration)):
        t = i / rate
        # 每 0.35 秒在 740Hz / 980Hz 之间切换，形成警笛效果
        freq = 740 if int(t / 0.35) % 2 == 0 else 980
        envelope = min(1.0, t * 8) * min(1.0, (duration - t) * 8)
        value = int(12000 * envelope * math.sin(2 * math.pi * freq * t))
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return path


class TTSHub:
    def __init__(self, cfg: Config, runtime: Any):
        self.cfg = cfg
        self.runtime = runtime
        self._queue: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=20)
        self.busy = False
        self.last_error = ""
        self.spoken = 0
        threading.Thread(target=self._run, name="cc-tts", daemon=True).start()

    # ------------------------------------------------------------ 对外
    def speak(self, text: str, *, urgent: bool = False, voice: str | None = None,
              rate: str | None = None, volume: str | None = None) -> dict[str, Any]:
        """加入播报队列（立即返回）。"""
        if not self.cfg.get("tts.enabled", True):
            return {"queued": False, "reason": "语音播报已在设置中关闭"}
        item = {
            "text": strip_markdown(text or "").strip(),
            "urgent": bool(urgent),
            "voice": voice or self.cfg.get("tts.voice", "zh-CN-XiaoxiaoNeural"),
            "rate": rate or self.cfg.get("tts.rate", "+0%"),
            "volume": volume or self.cfg.get("tts.volume", "+0%"),
        }
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            return {"queued": False, "reason": "播报队列已满"}
        return {"queued": True, "urgent": item["urgent"], "text": item["text"][:120]}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.cfg.get("tts.enabled", True)),
            "edge_tts_installed": EDGE_TTS_OK,
            "voice": self.cfg.get("tts.voice", "zh-CN-XiaoxiaoNeural"),
            "voices": TTS_VOICES,
            "busy": self.busy,
            "pending": self._queue.qsize(),
            "spoken": self.spoken,
            "ffplay": bool(shutil.which("ffplay")),
            "player": self.player_name(),
            "last_error": self.last_error,
            "urgent_alert": bool(self.cfg.get("tts.urgent_alert", True)),
        }

    @staticmethod
    def player_name() -> str:
        import importlib.util
        if importlib.util.find_spec("pygame") is not None:
            return "pygame"
        if shutil.which("ffplay"):
            return "ffplay"
        if IS_WIN:
            return "windows-media-player / winsound"
        if IS_MAC and shutil.which("afplay"):
            return "afplay"
        if shutil.which("aplay"):
            return "aplay"
        return "none"

    # ------------------------------------------------------------ 播报线程
    def _run(self) -> None:
        while True:
            item = self._queue.get()
            self.busy = True
            self.runtime.broadcast_json({"type": "tts_state", "busy": True,
                                         "urgent": item["urgent"]})
            try:
                if item["urgent"] and self.cfg.get("tts.urgent_alert", True):
                    self._play(str(ensure_alert_wav()))
                if item["text"]:
                    path = self._synthesize(item)
                    if path:
                        try:
                            self._play(path)
                            self.spoken += 1
                        finally:
                            Path(path).unlink(missing_ok=True)
                    else:
                        self.runtime.log("warning", "语音合成失败，横幅内容未播报")
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                self.runtime.log("warning", f"语音播报异常：{exc}")
            finally:
                self.busy = False
                self.runtime.broadcast_json({"type": "tts_state", "busy": False})
                self._queue.task_done()

    def _synthesize(self, item: dict[str, Any]) -> str | None:
        if not EDGE_TTS_OK:
            self.last_error = "未安装 edge-tts（pip install edge-tts）"
            self.runtime.log("warning", self.last_error)
            return None
        import asyncio

        # 绿色便携模式：临时音频也落在数据目录内，不写系统临时目录
        tmp_dir = app_dir() / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="cc-tts-", dir=str(tmp_dir))
        os.close(fd)
        try:
            async def _work() -> None:
                comm = edge_tts.Communicate(
                    item["text"], item["voice"],
                    rate=item["rate"], volume=item["volume"],
                )
                await comm.save(path)

            asyncio.run(_work())
            if Path(path).stat().st_size < 100:
                raise RuntimeError("合成结果为空，请检查网络或语音名称")
            self.last_error = ""
            return path
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"Edge TTS 合成失败：{exc}"
            self.runtime.log("warning", self.last_error)
            Path(path).unlink(missing_ok=True)
            return None

    # ------------------------------------------------------------ 播放
    def _play(self, path: str) -> None:
        """按可用性依次尝试播放器，全部失败才抛出明确错误。

        pygame 排在首位：Windows 教室电脑通常没有 ffmpeg，而 pygame 自带
        音频解码（支持 mp3 / wav），pip 安装即有预编译 wheel。
        """
        if not Path(path).exists():
            raise FileNotFoundError(path)
        errors: list[str] = []

        ok, error = self._play_pygame(path)
        if ok:
            return
        if error:
            errors.append(f"pygame: {error}")

        ffplay = shutil.which("ffplay")
        if ffplay:
            try:
                proc = subprocess.run(
                    [ffplay, "-nodisp", "-autoexit", "-loglevel", "error", path],
                    capture_output=True, timeout=180,
                )
                if proc.returncode == 0:
                    return
                errors.append("ffplay: returncode != 0")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ffplay: {exc}")

        if IS_WIN:
            ok, error = self._play_windows_media(path)
            if ok:
                return
            if error:
                errors.append(f"WMP: {error}")
            if path.lower().endswith(".wav"):
                try:
                    import winsound  # type: ignore
                    winsound.PlaySound(path, winsound.SND_FILENAME)
                    return
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"winsound: {exc}")
        elif IS_MAC and shutil.which("afplay"):
            try:
                subprocess.run(["afplay", path], check=False, timeout=180)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"afplay: {exc}")
        elif shutil.which("aplay") and path.lower().endswith(".wav"):
            try:
                subprocess.run(["aplay", "-q", path], check=False, timeout=180)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"aplay: {exc}")

        message = "无可用音频播放器：" + "; ".join(errors[:3]) if errors else "无可用音频播放器"
        message += "。建议 pip install pygame 或安装 ffmpeg（ffplay）"
        raise RuntimeError(message)

    @staticmethod
    def _play_pygame(path: str) -> tuple[bool, str]:
        try:
            import pygame  # type: ignore
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.quit()
            return True, ""
        except ImportError:
            return False, ""
        except Exception as exc:  # noqa: BLE001
            try:
                pygame.mixer.quit()
            except Exception:  # noqa: BLE001
                pass
            return False, str(exc)[:160]

    @staticmethod
    def _play_windows_media(path: str) -> tuple[bool, str]:
        """Windows 自带的 WPF MediaPlayer，可播放 mp3，无需额外安装。"""
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            return False, ""
        safe = path.replace("'", "''")
        script = (
            "Add-Type -AssemblyName presentationCore; "
            f"$p = New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open('{safe}'); "
            "Start-Sleep -Milliseconds 400; "
            "$d = $p.NaturalDuration.TimeSpan.TotalSeconds; "
            "if ($d -le 0) { $d = 10 }; "
            "$p.Play(); Start-Sleep -Seconds ($d + 0.4); $p.Close();"
        )
        try:
            proc = subprocess.run(
                [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True, timeout=180,
            )
            if proc.returncode == 0:
                return True, ""
            return False, (proc.stderr.decode("utf-8", "ignore") or "")[:160]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:160]
