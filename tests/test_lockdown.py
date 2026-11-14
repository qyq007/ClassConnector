"""v1.2.0 新增能力测试：摄像头主机侧锁定、桌面控制层、冻结路径。

这些测试不依赖运行中的服务，也不需要图形显示器。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import Config, reset_config_cache  # noqa: E402


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """把配置 / 运行时数据隔离到临时目录，避免污染真实用户目录。"""
    monkeypatch.setenv("CLASSCONNECTOR_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("CLASSCONNECTOR_CONFIG", str(tmp_path / "data" / "config.json"))
    reset_config_cache()
    yield tmp_path
    reset_config_cache()


def new_camera(cfg: Config):
    from agent.camera import CameraHub
    return CameraHub(cfg)


# ---------------------------------------------------------------- 默认配置
def test_remote_select_is_off_by_default():
    cfg = Config({})
    assert cfg.get("camera.remote_select") is False
    assert "index" in cfg.get("camera")


def test_public_config_never_leaks_password():
    cfg = Config({"password_hash": "abc", "password_salt": "def"})
    public = cfg.public()
    assert "password_hash" not in public
    assert "password_salt" not in public
    assert "has_password" in public


# ---------------------------------------------------------------- 设备视图
def test_locked_devices_view_exposes_only_host_selected(isolated):
    cfg = Config({"camera": {"index": 2}})
    hub = new_camera(cfg)
    try:
        view = hub.devices_view(remote=True)
        assert view["locked"] is True
        assert len(view["devices"]) == 1
        assert view["devices"][0]["index"] == 2
        assert view["current"] == 2
        # 不暴露本机其它设备 / 设备总数
        assert "total" not in view and "count" not in view
        assert hub.status()["camera_select_locked"] is True
    finally:
        hub.stop()


def test_local_devices_view_is_not_restricted(isolated):
    cfg = Config({})
    hub = new_camera(cfg)
    try:
        view = hub.devices_view(remote=False)
        assert view["locked"] is False
        assert isinstance(view["devices"], list) and view["devices"]
        # 本地枚举结果可能只有测试画面一项，但结构必须完整
        assert "name" in view["devices"][0]
    finally:
        hub.stop()


def test_unlocked_remote_devices_view_allowed(isolated):
    cfg = Config({"camera": {"remote_select": True}})
    hub = new_camera(cfg)
    try:
        assert hub.devices_view(remote=True)["locked"] is False
        assert hub.status()["camera_select_locked"] is False
    finally:
        hub.stop()


# ---------------------------------------------------------------- 配置写入
def test_remote_config_cannot_change_camera_index(isolated):
    cfg = Config({"camera": {"index": 1}})
    hub = new_camera(cfg)
    try:
        result = hub.set_config({"index": 3, "quality": 55}, remote=True)
        assert result["index"] == 1          # 设备索引被丢弃
        assert result["quality"] == 55       # 画质仍可调
        assert cfg.get("camera.index") == 1
    finally:
        hub.stop()


def test_local_config_can_change_camera_index(isolated):
    cfg = Config({"camera": {"index": 0}})
    hub = new_camera(cfg)
    try:
        result = hub.set_config({"index": 2}, remote=False)
        assert result["index"] == 2
        assert cfg.get("camera.index") == 2
    finally:
        hub.stop()


def test_remote_config_cannot_unlock_itself(isolated):
    cfg = Config({})
    hub = new_camera(cfg)
    try:
        hub.set_config({"index": 1, "remote_select": True}, remote=True)
        assert cfg.get("camera.remote_select") is False
        assert cfg.get("camera.index") == 0
    finally:
        hub.stop()


def test_values_are_clamped(isolated):
    cfg = Config({})
    hub = new_camera(cfg)
    try:
        result = hub.set_config({"quality": 999, "fps": 0}, remote=True)
        assert result["quality"] == 100 and result["fps"] == 1
        with pytest.raises(ValueError):
            hub.set_config({"quality": "abc"}, remote=True)
    finally:
        hub.stop()


# ---------------------------------------------------------------- HTTP 层
def _client(cfg, runtime):
    from fastapi.testclient import TestClient
    from agent.server import create_app
    return TestClient(create_app(cfg, runtime, shutdown_fn=lambda: None))


def test_http_lockdown(isolated):
    from agent.desktop import DesktopController

    ctrl = DesktopController(Config({}))
    try:
        with _client(ctrl.cfg, ctrl.runtime) as client:
            r = client.get("/api/camera/devices")
            assert r.status_code == 200
            body = r.json()
            assert body["locked"] is True and len(body["devices"]) == 1

            r = client.post("/api/camera/config",
                            json={"index": 3, "quality": 62})
            assert r.status_code == 200
            body = r.json()
            assert body["camera_select_locked"] is True
            assert body["ignored_fields"] == ["index"]
            assert body["config"]["index"] == 0
            assert body["config"]["quality"] == 62

            # /api/config 也不能改 index，更不能自己把开关打开
            r = client.post("/api/config", json={
                "camera": {"index": 4, "remote_select": True, "width": 640},
            })
            assert r.status_code == 200
            assert ctrl.cfg.get("camera.index") == 0
            assert ctrl.cfg.get("camera.remote_select") is False
            assert ctrl.cfg.get("camera.width") == 640
    finally:
        ctrl.shutdown()


def test_http_unlocked_after_host_changes_setting(isolated):
    from agent.desktop import DesktopController

    ctrl = DesktopController(Config({}))
    try:
        ctrl.apply_settings({"camera": {"remote_select": True, "index": 0}})
        with _client(ctrl.cfg, ctrl.runtime) as client:
            body = client.get("/api/camera/devices").json()
            assert body["locked"] is False
            r = client.post("/api/camera/config", json={"index": 1})
            assert r.json()["config"]["index"] == 1
            assert r.json()["ignored_fields"] == []
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------- 控制层
def test_controller_apply_settings(isolated):
    from agent.desktop import DesktopController

    ctrl = DesktopController(Config({}))
    try:
        ctrl.apply_settings({
            "camera": {"index": 1, "width": 640, "height": 480,
                       "fps": 10, "quality": 50, "remote_select": False},
            "tts": {"enabled": False, "voice": "zh-CN-YunxiNeural",
                    "rate": "+10%", "volume": "-10%", "urgent_alert": False},
            "room_name": "高三(1)班", "port": 9001, "idle_timeout": 0,
        })
        assert ctrl.cfg.get("camera.index") == 1
        assert ctrl.cfg.get("camera.quality") == 50
        assert ctrl.cfg.get("tts.voice") == "zh-CN-YunxiNeural"
        assert ctrl.cfg.get("tts.urgent_alert") is False
        assert ctrl.cfg.get("room_name") == "高三(1)班"
        assert ctrl.cfg.get("port") == 9001
        assert ctrl.cfg.get("idle_timeout") == 0
        assert ctrl.local_devices()  # 本机枚举不受限制
    finally:
        ctrl.shutdown()


def test_controller_refuses_auth_without_password(isolated):
    from agent.desktop import DesktopController

    ctrl = DesktopController(Config({}))
    try:
        with pytest.raises(ValueError):
            ctrl.apply_settings({"require_auth": True})
        assert ctrl.cfg.get("require_auth") is False
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------- 路径
def test_resource_and_writable_paths():
    from agent.paths import (banner_argv, data_dir, manager_dir,
                             resource_root, writable_root)

    assert manager_dir().is_dir()
    assert (manager_dir() / "index.html").is_file()
    assert (manager_dir() / "icon.png").is_file()
    assert (resource_root() / "assets" / "icon.ico").is_file()
    assert data_dir() == writable_root() / "data"
    argv = banner_argv(Path("spec.json"), "python")
    assert argv[-1] == "spec.json" and "-m" in argv


def test_icons_are_consistent_between_desktop_and_web():
    from agent.paths import resource_root

    assets = resource_root() / "assets"
    manager = resource_root() / "manager"
    assert (assets / "icon.png").read_bytes() == (manager / "icon.png").read_bytes()
    assert (assets / "icon.ico").read_bytes() == (manager / "favicon.ico").read_bytes()
