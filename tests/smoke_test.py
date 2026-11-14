"""端到端冒烟测试：需要先启动采集端。

    python -m agent --no-tray --port 8420          # 终端 A
    pytest tests/smoke_test.py -v                   # 终端 B
    CC_BASE_URL=http://192.168.1.50:8420 pytest tests/smoke_test.py -v

也可直接运行： ``python tests/smoke_test.py``
不会停止采集端、不会修改密码；画质设置会在测试结束后恢复。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

requests = pytest.importorskip("requests")
websockets = pytest.importorskip("websockets")

BASE = os.environ.get("CC_BASE_URL", "http://127.0.0.1:8420").rstrip("/")
WS = BASE.replace("http://", "ws://").replace("https://", "wss://") + "/ws"


@pytest.fixture(scope="module", autouse=True)
def require_service():
    try:
        r = requests.get(BASE + "/api/health", timeout=3)
        assert r.json().get("service") == "classconnector-agent"
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"采集端未运行于 {BASE}：{exc}")


def get(path, **kw):
    return requests.get(BASE + path, timeout=kw.pop("timeout", 10), **kw)


def post(path, payload):
    return requests.post(BASE + path, json=payload, timeout=10)


# ---------------------------------------------------------------- 基础接口
def test_health():
    data = get("/api/health").json()
    assert data["ok"] and data["version"] and data["port"]


def test_status_structure():
    d = get("/api/status").json()
    for key in ("device", "runtime", "camera", "audio", "screen", "banner",
                "tts", "autostart", "capabilities", "config"):
        assert key in d, key
    assert "password_hash" not in d["config"]


def test_config_is_public():
    d = get("/api/config").json()
    assert "has_password" in d
    assert "password_salt" not in d and "password_hash" not in d


def test_camera_config_set_and_restore():
    original = get("/api/camera/config").json()["config"]
    changed = post("/api/camera/config", {"quality": 66, "fps": 11}).json()
    assert changed["ok"] and changed["config"]["quality"] == 66
    post("/api/camera/config", original)  # 恢复


def test_camera_devices():
    d = get("/api/camera/devices", timeout=20).json()
    assert isinstance(d["devices"], list)


def test_camera_snapshot_is_jpeg():
    r = get("/api/camera/snapshot", timeout=15)
    assert r.status_code == 200
    assert r.content[:3] == b"\xff\xd8\xff"


def test_mjpeg_stream():
    r = requests.get(BASE + "/api/camera/stream", stream=True, timeout=10)
    buf = b""
    for chunk in r.iter_content(4096):
        buf += chunk
        if buf.count(b"--classconnector-frame") >= 2:
            break
    r.close()
    assert b"--classconnector-frame" in buf
    assert b"\xff\xd8\xff" in buf


def test_screen_displays():
    d = get("/api/screen/displays").json()
    assert len(d["displays"]) >= 1


def test_screen_shot_is_png():
    r = get("/api/screen/shot?scale=0.5", timeout=15)
    assert r.status_code == 200
    assert r.content[:4] == b"\x89PNG"
    assert r.headers.get("X-CC-Fallback") in ("0", "1")
    meta = json.loads(r.headers.get("X-CC-Meta", "{}"))
    assert "captured_at" in meta


def test_markdown_render():
    d = post("/api/markdown/render", {"markdown": "# 标题\n\n**加粗**\n\n- [ ] 待办"}).json()
    assert "<h1>标题</h1>" in d["html"] and "<strong>加粗</strong>" in d["html"]
    assert "**" not in d["plain"]


def test_tts_endpoints():
    assert len(get("/api/tts/voices").json()["voices"]) > 0
    assert "edge_tts_installed" in get("/api/tts/status").json()


def test_logs_and_platform():
    assert "logs" in get("/api/logs?limit=5").json()
    assert "autostart" in get("/api/platform").json()


def test_stop_requires_password():
    # 无论是否已安装，随便给一个密码都必须被拒绝
    r = post("/api/agent/stop", {"password": "definitely-wrong-password"})
    assert r.status_code in (403, 409)


# ---------------------------------------------------------------- 横幅全流程
def test_banner_send_ack_dismiss():
    payload = {
        "title": "冒烟测试通知",
        "markdown": "# 请全体同学注意\n\n**14:30** 到操场集合\n\n> 带好水杯\n\n1. 整队\n2. 保持安静",
        "urgent": True, "need_ack": True, "tts": False, "duration": 0,
    }
    sent = post("/api/banner/send", payload).json()
    banner_id = sent["banner"]["id"]
    assert sent["ok"] and sent["banner"]["urgent"]

    history = get("/api/banner/history").json()["items"]
    assert any(b["id"] == banner_id for b in history)

    ack = post("/api/banner/ack", {"id": banner_id}).json()
    assert ack["banner"]["status"] == "acked"

    post("/api/banner/dismiss", {"id": banner_id})
    after = get("/api/banner/history").json()["items"]
    assert next(b for b in after if b["id"] == banner_id)["status"] == "acked"


# ---------------------------------------------------------------- 静态资源
@pytest.mark.parametrize("path", ["/", "/style.css", "/app.js", "/markdown.js", "/audio.js"])
def test_static_assets(path):
    r = get(path)
    assert r.status_code == 200 and len(r.content) > 100


# ---------------------------------------------------------------- WebSocket
def test_websocket_roundtrip():
    async def run():
        async with websockets.connect(WS) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 5))
            assert hello["type"] == "hello"

            await ws.send(json.dumps({"type": "ping"}))
            got_pong = False
            for _ in range(4):
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
                    if msg.get("type") == "pong":
                        got_pong = True
                        break
                except asyncio.TimeoutError:
                    break
            assert got_pong

            await ws.send(json.dumps({"type": "talk", "active": True}))
            await ws.send(b"\x00\x01" * 512)  # 对讲 PCM
            await asyncio.sleep(0.2)
            await ws.send(json.dumps({"type": "talk", "active": False}))

            await ws.send(json.dumps({"type": "camera_config", "config": {"quality": 70}}))
            await asyncio.sleep(0.1)
    asyncio.run(run())


def test_ws_connection_wakes_device():
    async def run():
        async with websockets.connect(WS) as ws:
            await asyncio.wait_for(ws.recv(), 5)
            health = get("/api/health").json()
            assert health["sleeping"] is False
    asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
