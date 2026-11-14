"""屏幕截图。

优先使用 mss（支持多显示器），其次 Pillow 的 ImageGrab；无图形会话时
返回一张说明性占位图并通过响应头 ``X-CC-Fallback`` 告知管理端，
保证接口永远可用、便于在无显示器的服务器上联调。
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from agent.config import Config

logger = logging.getLogger("cc.screen")

try:
    import mss  # type: ignore
    MSS_OK = True
except Exception:  # noqa: BLE001
    MSS_OK = False


def _mss_factory():
    """兼容 mss 新旧版本：新版本推荐 MSS()，旧版本只有 mss()。"""
    return getattr(mss, "MSS", None) or mss.mss

try:
    from PIL import Image, ImageDraw, ImageFont, ImageGrab  # type: ignore
    PIL_OK = True
except Exception:  # noqa: BLE001
    PIL_OK = False


def _font(size: int) -> Any:
    if not PIL_OK:
        return None
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        from pathlib import Path
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def list_displays() -> list[dict[str, Any]]:
    if MSS_OK:
        try:
            with _mss_factory()() as sct:
                result = []
                for i, mon in enumerate(sct.monitors):
                    result.append({
                        "index": i,
                        "name": "全部显示器（拼接）" if i == 0 else f"显示器 {i}",
                        "width": mon["width"], "height": mon["height"],
                        "left": mon["left"], "top": mon["top"],
                    })
                return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("枚举显示器失败：%s", exc)
    return [{"index": 0, "name": "主显示器", "width": 0, "height": 0,
             "left": 0, "top": 0}]


def _fallback_image(cfg: Config, reason: str) -> bytes:
    width, height = 1280, 720
    if not PIL_OK:
        return b""
    img = Image.new("RGB", (width, height), (15, 23, 42))
    draw = ImageDraw.Draw(img)
    for x in range(0, width, 40):
        draw.line((x, 0, x, height), fill=(30, 41, 59))
    draw.rounded_rectangle((width // 8, height // 4, width * 7 // 8, height * 3 // 4),
                           radius=20, fill=(30, 41, 59), outline=(59, 130, 246), width=2)
    big, small = _font(34), _font(20)

    def label(x: int, y: int, value: str, font: Any, color: tuple) -> None:
        try:
            draw.text((x, y), value, font=font, fill=color)
        except (UnicodeEncodeError, OSError):
            # 某些系统缺少中文字体，退化为 ASCII 说明，保证接口永不失败
            draw.text((x, y), value.encode("ascii", "ignore").decode() or "N/A",
                      font=None, fill=color)

    label(width // 8 + 40, height // 4 + 50, "屏幕截图不可用", big, (248, 250, 252))
    label(width // 8 + 40, height // 4 + 110, reason, small, (250, 204, 21))
    label(width // 8 + 40, height // 4 + 160,
          f"{cfg.get('room_name', '班级')} · {time.strftime('%Y-%m-%d %H:%M:%S')}",
          small, (148, 163, 184))
    label(width // 8 + 40, height // 4 + 210,
          "请在有桌面会话的教室电脑上启动采集端", small, (148, 163, 184))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def capture(cfg: Config, display: int = 0, scale: float = 1.0) -> tuple[bytes, bool, dict]:
    """返回 (PNG 字节, 是否为降级占位图, 元信息)。"""
    scale = max(0.2, min(1.0, float(scale or 1.0)))
    meta: dict[str, Any] = {"display": display, "scale": scale,
                            "captured_at": time.time()}
    reason = ""

    img = None
    if MSS_OK:
        try:
            with _mss_factory()() as sct:
                monitors = sct.monitors
                if display < 0 or display >= len(monitors):
                    display = 0
                shot = sct.grab(monitors[display])
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                meta["backend"] = "mss"
                meta["width"], meta["height"] = shot.size
        except Exception as exc:  # noqa: BLE001
            reason = f"mss 截图失败：{exc}"
            logger.warning(reason)
    if img is None and PIL_OK:
        try:
            img = ImageGrab.grab(all_screens=display == 0)
            meta["backend"] = "pillow"
            meta["width"], meta["height"] = img.size
        except Exception as exc:  # noqa: BLE001
            reason = f"屏幕截图失败：{exc}"
            logger.warning(reason)
    if img is None:
        if not reason:
            reason = "未安装 mss / Pillow，或当前会话没有图形界面"
        return _fallback_image(cfg, reason), True, {**meta, "fallback": True,
                                                      "reason": reason}

    if scale < 1.0:
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))), Image.LANCZOS)
    bio = io.BytesIO()
    img.convert("RGB").save(bio, format="PNG", optimize=True)
    meta.update({"fallback": False, "bytes": len(bio.getvalue()),
                 "out_width": img.width, "out_height": img.height})
    return bio.getvalue(), False, meta
