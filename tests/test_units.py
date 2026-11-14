"""纯单元测试：不依赖运行中的服务，可直接 ``pytest tests/test_units.py``。"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from agent.config import (  # noqa: E402
    Config, hash_password, has_password, set_password, verify_password,
)
from agent.markdown_render import strip_markdown, to_html  # noqa: E402
from agent.tts import ensure_alert_wav  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """所有测试都使用临时配置目录，绝不触碰真实用户数据。"""
    monkeypatch.setenv("CLASSCONNECTOR_HOME", str(tmp_path))
    monkeypatch.setenv("CLASSCONNECTOR_CONFIG", str(tmp_path / "config.json"))


# ---------------------------------------------------------------- 配置与密码
def test_dotted_config_access():
    cfg = Config({"camera": {"quality": 42}})
    assert cfg.get("camera.quality") == 42
    assert cfg.get("camera.fps") == 15  # 默认值合并
    cfg.set("tts.voice", "zh-CN-YunxiNeural")
    assert cfg.get("tts.voice") == "zh-CN-YunxiNeural"
    assert cfg.get("not.exist", "fallback") == "fallback"


def test_password_hash_and_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSCONNECTOR_CONFIG", str(tmp_path / "config.json"))
    cfg = Config({})
    assert not has_password(cfg)
    assert not verify_password(cfg, "anything")

    set_password(cfg, "教室密码123")
    assert has_password(cfg)
    assert verify_password(cfg, "教室密码123")
    assert not verify_password(cfg, "教室密码124")
    assert not verify_password(cfg, "")
    assert not verify_password(cfg, None)

    # 相同密码 + 不同盐 -> 不同哈希（防彩虹表）
    salt2 = "ab" * 16
    assert hash_password("教室密码123", salt2) != cfg.get("password_hash")


def test_public_config_hides_secrets():
    cfg = Config({})
    set_password(cfg, "secret")
    public = cfg.public()
    assert "password_hash" not in public
    assert "password_salt" not in public
    assert public["has_password"] is True


def test_password_too_short():
    with pytest.raises(ValueError):
        set_password(Config({}), "123")


# ---------------------------------------------------------------- Markdown
def test_markdown_headings_lists_table():
    md = "# 标题\n\n**粗体** 与 *斜体* 和 ~~删除~~\n\n- [ ] 待办\n- [x] 完成\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"
    html = to_html(md)
    assert "<h1>标题</h1>" in html
    assert "<strong>粗体</strong>" in html
    assert "<em>斜体</em>" in html
    assert "<del>删除</del>" in html
    assert 'class="md-task"' in html
    assert "<table>" in html and "<th>A</th>" in html


def test_markdown_escapes_html():
    html = to_html("<script>alert(1)</script>\n\n[点我](javascript:alert(1))")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "javascript:" not in html


def test_markdown_code_fence():
    html = to_html("```python\nprint('hi')\n```")
    assert "<pre><code" in html
    assert "language-python" in html
    assert "print(" in html


def test_strip_markdown_for_tts():
    plain = strip_markdown(
        "# 通知\n\n**请** [查看](http://x.com) `code`\n\n- [ ] 待办\n\n```python\nprint(1)\n```"
    )
    assert "通知" in plain
    assert "**" not in plain and "`" not in plain
    assert "http://" not in plain
    assert "[" not in plain
    assert "python" not in plain  # 代码块语言标识不应被朗读
    assert "print(1)" in plain


# ---------------------------------------------------------------- 紧急警报音
def test_urgent_wav_generated(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSCONNECTOR_HOME", str(tmp_path))
    path = ensure_alert_wav()
    assert path.exists() and path.stat().st_size > 1000
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 44100
        assert wav.getnframes() > 44100  # 时长约 2 秒


# ---------------------------------------------------------------- 摄像头画质边界
def test_camera_config_clamped():
    from agent.camera import CameraHub
    cfg = Config({})
    hub = CameraHub(cfg)
    try:
        result = hub.set_config({
            "quality": 999, "fps": -5, "width": 10, "height": 99999,
            "index": 99, "unknown": 1,
        })
        assert result["quality"] == 100
        assert result["fps"] == 1
        assert result["width"] == 320
        assert result["height"] == 2160
        assert result["index"] == 15
        assert "unknown" not in result
        with pytest.raises(ValueError):
            hub.set_config({"quality": "abc"})
    finally:
        hub.stop()


# ---------------------------------------------------------------- 横幅与签收
class FakeRuntime:
    def __init__(self):
        self.messages = []
        self.logs = []
        self.tts = None
        self.internal_token = "internal-token"

    def log(self, level, message):
        self.logs.append((level, message))

    def broadcast_json(self, message):
        self.messages.append(message)


@pytest.fixture
def banner_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSCONNECTOR_HOME", str(tmp_path))
    monkeypatch.setenv("CLASSCONNECTOR_CONFIG", str(tmp_path / "config.json"))
    import agent.banner as banner_mod
    monkeypatch.setattr(banner_mod, "_has_display", lambda: False)
    cfg = Config({})
    runtime = FakeRuntime()
    return banner_mod.BannerManager(cfg, runtime), runtime


def test_banner_send_ack_history(banner_env):
    manager, runtime = banner_env
    banner = manager.send({
        "title": "集合通知", "markdown": "# 全体集合\n\n**14:30** 操场",
        "urgent": True, "need_ack": True, "tts": False,
    })
    assert banner["status"] == "showing"
    assert banner["display_mode"] == "headless"
    assert any(m["type"] == "banner" for m in runtime.messages)

    acked = manager.ack(banner["id"], "web")
    assert acked["status"] == "acked" and acked["acked_at"]
    assert any(m["type"] == "banner_ack" for m in runtime.messages)

    history = manager.list_history()
    assert history[0]["id"] == banner["id"]
    assert manager.status()["acked"] == 1

    manager.dismiss(banner["id"])
    assert manager.status()["current"] is None
    with pytest.raises(KeyError):
        manager.ack("not-exist")


def test_banner_replaces_previous(banner_env):
    manager, _ = banner_env
    first = manager.send({"title": "第一条", "markdown": "内容", "tts": False})
    second = manager.send({"title": "第二条", "markdown": "内容", "tts": False})
    history = {b["id"]: b for b in manager.list_history()}
    assert history[first["id"]]["status"] == "dismissed"
    assert history[second["id"]]["status"] == "showing"
    assert manager.current_id == second["id"]


def test_banner_requires_content(banner_env):
    manager, _ = banner_env
    with pytest.raises(ValueError):
        manager.send({"title": "", "markdown": "", "tts": False})


# ---------------------------------------------------------------- 截图降级
def test_screen_capture_never_crashes():
    from agent import screen
    cfg = Config({})
    png, fallback, meta = screen.capture(cfg, 0, 0.5)
    assert png[:4] == b"\x89PNG" or png == b""
    assert isinstance(fallback, bool)
    assert "captured_at" in meta
