"""配置持久化与安装密码管理。

配置文件默认位于用户目录（不会进入版本库），结构见 ``DEFAULT_CONFIG``。
密码使用 PBKDF2-HMAC-SHA256 + 随机盐存储，任何接口都不会返回明文或哈希。
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import socket
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "ClassConnector"
DEFAULT_PORT = 8420
PBKDF2_ITERATIONS = 200_000
CONFIG_VERSION = 1

DEFAULT_CONFIG: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "host": "0.0.0.0",
    "port": DEFAULT_PORT,
    "room_name": "未命名班级",
    "device_name": "",  # 为空时自动使用主机名
    # 认证
    "password_salt": "",
    "password_hash": "",
    "require_auth": False,  # true = 所有管理操作都需要安装密码登录
    # 休眠
    "idle_timeout": 20,  # 无任何管理端连接多少秒后进入休眠（0 = 不休眠）
    # 摄像头
    "camera": {
        "index": 0,
        "width": 1280,
        "height": 720,
        "fps": 15,
        "quality": 70,
    },
    # 音频（16kHz / 单声道 / 16bit，浏览器端会重采样）
    "audio": {
        "enabled": True,
        "sample_rate": 16000,
        "channels": 1,
        "chunk": 1024,
    },
    # 横幅
    "banner": {
        "auto_close": 0,  # 秒；0 = 需手动关闭 / 签收
        "need_ack_default": True,
        "tts_default": True,
    },
    # 语音播报
    "tts": {
        "enabled": True,
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%",
        "volume": "+0%",
        "urgent_alert": True,
    },
    "log_level": "INFO",
}

# 管理端可选用的中文语音
TTS_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（女声）"},
    {"id": "zh-CN-YunxiNeural", "name": "云希（男声）"},
    {"id": "zh-CN-YunjianNeural", "name": "云健（男声·播报）"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊（女声）"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北（东北话）"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮（陕西话）"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻（中国台湾）"},
    {"id": "zh-HK-HiuMaanNeural", "name": "曉曼（中国香港）"},
]


def app_dir() -> Path:
    """运行时数据目录（配置、日志、PID、临时音频）。"""
    override = os.environ.get("CLASSCONNECTOR_HOME")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        path = Path.home() / ".classconnector"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    override = os.environ.get("CLASSCONNECTOR_CONFIG")
    return Path(override).expanduser() if override else app_dir() / "config.json"


def pid_path() -> Path:
    return app_dir() / "agent.pid"


def log_path() -> Path:
    return app_dir() / "agent.log"


def get_local_ip() -> str:
    """获取本机在局域网中的 IP（不产生实际网络流量）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            return "127.0.0.1"
    finally:
        s.close()


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()


def set_password(cfg: "Config", password: str) -> None:
    if len(password) < 4:
        raise ValueError("密码长度至少 4 位")
    salt = secrets.token_hex(16)
    cfg.set("password_salt", salt)
    cfg.set("password_hash", hash_password(password, salt))
    cfg.save()


def verify_password(cfg: "Config", password: str | None) -> bool:
    """恒定时间比较，防止计时侧信道。"""
    salt, expected = cfg.get("password_salt"), cfg.get("password_hash")
    if not salt or not expected or not password:
        return False
    try:
        actual = hash_password(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def has_password(cfg: "Config") -> bool:
    return bool(cfg.get("password_salt") and cfg.get("password_hash"))


def _merge(base: dict, incoming: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """线程安全的配置对象，支持 ``cfg.get("camera.quality")`` 形式的点路径。"""

    def __init__(self, data: dict[str, Any]):
        self._data = _merge(DEFAULT_CONFIG, data)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return config_path()

    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        with self._lock:
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
                if not isinstance(node, dict):
                    raise ValueError(f"配置路径冲突: {dotted}")
            node[parts[-1]] = value

    def update(self, patch: dict) -> None:
        with self._lock:
            self._data = _merge(self._data, patch)

    def raw(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def public(self) -> dict:
        """可安全返回给管理端的配置（剔除所有密钥字段）。"""
        data = self.raw()
        data.pop("password_salt", None)
        data.pop("password_hash", None)
        data["has_password"] = has_password(self)
        data["device_name"] = data.get("device_name") or _hostname()
        return data

    def save(self) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


_config: Config | None = None
_config_lock = threading.Lock()


def load_config() -> Config:
    """加载（必要时创建）全局配置单例。"""
    global _config
    with _config_lock:
        if _config is not None:
            return _config
        path = config_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}
        _config = Config(data)
        if not path.exists():
            _config.save()
        return _config


def reset_config_cache() -> None:
    global _config
    with _config_lock:
        _config = None
