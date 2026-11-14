"""采集端 HTTP / WebSocket 服务，同时托管管理端 Web 页面。

浏览器直接访问 ``http://<设备IP>:<端口>`` 即可管理该设备；也可以把
``manager/`` 单独部署到任意静态服务器，在页面里填写设备 IP + 端口连接
（服务端已开放 CORS，支持跨源管理多台设备）。
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import queue
import secrets
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent import __version__
from agent.compat import to_thread
from agent.config import (
    Config, TTS_VOICES, get_local_ip, has_password, set_password,
    verify_password,
)
from agent.markdown_render import strip_markdown, to_html
from agent.paths import manager_dir
from agent.platform_util import autostart_status, project_root, start_background
from agent.state import Client, Runtime

MANAGER_DIR = manager_dir()
MJPEG_BOUNDARY = "classconnector-frame"


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def create_app(
    cfg: Config,
    runtime: Runtime,
    *,
    shutdown_fn: Callable[[], None] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.set_loop(asyncio.get_running_loop())

        async def idle_watch() -> None:
            while True:
                await asyncio.sleep(1.0)
                runtime.check_idle()

        task = asyncio.create_task(idle_watch())
        runtime.log("info", f"采集端服务已启动，监听 {cfg.get('host')}:{cfg.get('port')}")
        try:
            yield
        finally:
            task.cancel()
            runtime.log("info", "采集端服务正在停止")

    app = FastAPI(
        title="ClassConnector 采集端",
        description="班级连接器 · 局域网采集端 API",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-CC-Fallback", "X-CC-Meta", "Content-Disposition"],
    )
    app.state.cc = {"cfg": cfg, "runtime": runtime, "shutdown": shutdown_fn}

    # ---------------------------------------------------------------- 认证
    def check_auth(request: Request, *, allow_internal: bool = False) -> bool:
        """返回是否为「内部令牌」调用。"""
        rt: Runtime = request.app.state.cc["runtime"]
        if not rt.token_required:
            token = request.headers.get("X-CC-Token", "")
            return allow_internal and secrets.compare_digest(token, rt.internal_token)
        token = request.headers.get("X-CC-Token") or request.query_params.get("token") or ""
        if not rt.valid_token(token, internal_ok=allow_internal):
            raise HTTPException(status_code=401, detail="需要管理密码登录")
        return allow_internal and secrets.compare_digest(token, rt.internal_token)

    def require_password(cfg_: Config, password: str | None) -> None:
        if not has_password(cfg_):
            raise HTTPException(
                status_code=409,
                detail="尚未设置安装密码，请先运行 python -m agent.install 完成安装",
            )
        if not verify_password(cfg_, password):
            raise HTTPException(status_code=403, detail="密码错误")

    # ---------------------------------------------------------------- 基础
    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "service": "classconnector-agent",
            "version": __version__,
            "name": cfg.get("device_name") or socket.gethostname(),
            "room": cfg.get("room_name"),
            "ip": get_local_ip(),
            "port": cfg.get("port"),
            "sleeping": runtime.sleeping,
            "auth_required": runtime.token_required,
            "has_password": has_password(cfg),
            "time": time.time(),
        }

    @app.get("/api/status")
    async def status(request: Request):
        check_auth(request)
        from agent import screen

        return {
            "ok": True,
            "version": __version__,
            "device": {
                "name": cfg.get("device_name") or socket.gethostname(),
                "hostname": socket.gethostname(),
                "room": cfg.get("room_name"),
                "ip": get_local_ip(),
                "port": cfg.get("port"),
                "system": platform.platform(),
                "os": platform.system(),
                "python": sys.version.split()[0],
            },
            "runtime": runtime.snapshot(),
            "camera": runtime.camera.status() if runtime.camera else None,
            "audio": runtime.audio.status() if runtime.audio else None,
            "screen": {
                "displays": screen.list_displays(),
                "mss": screen.MSS_OK,
                "pillow": screen.PIL_OK,
            },
            "banner": runtime.banner.status() if runtime.banner else None,
            "tts": runtime.tts.status() if runtime.tts else None,
            "autostart": autostart_status(),
            "config": cfg.public(),
            "capabilities": {
                "camera": runtime.camera is not None,
                "audio": bool(runtime.audio and runtime.audio.available),
                "screen": True,
                "banner": runtime.banner is not None,
                "tts": bool(runtime.tts and runtime.tts.status()["edge_tts_installed"]),
                "talk": runtime.audio is not None,
            },
        }

    @app.get("/api/logs")
    async def logs(request: Request, limit: int = 100):
        check_auth(request)
        return {"logs": list(runtime.logs)[-max(1, min(500, limit)):]}

    @app.post("/api/auth")
    async def auth(request: Request):
        body = await _body(request)
        require_password(cfg, body.get("password"))
        return {"ok": True, "token": runtime.issue_token(), "expires_in": 8 * 3600}

    @app.get("/api/platform")
    async def platform_info(request: Request):
        check_auth(request)
        return {
            "autostart": autostart_status(),
            "system": platform.system(),
            "release": platform.release(),
            "python": sys.executable,
            "project_root": str(project_root()),
            "background": os.environ.get("CLASSCONNECTOR_BACKGROUND") == "1",
        }

    # ---------------------------------------------------------------- 配置
    @app.get("/api/config")
    async def get_config(request: Request):
        check_auth(request)
        return cfg.public()

    @app.post("/api/config")
    async def update_config(request: Request):
        check_auth(request)
        payload = await _body(request)
        patch = payload.get("config") if isinstance(payload.get("config"), dict) else payload
        allowed = {
            "room_name", "device_name", "idle_timeout", "log_level",
            "camera", "audio", "banner", "tts", "require_auth",
        }
        clean = {k: v for k, v in patch.items() if k in allowed}
        if not clean:
            raise HTTPException(status_code=400, detail="没有可更新的配置项")
        if "require_auth" in clean:
            require_password(cfg, payload.get("password"))
        # 收敛子配置，避免未知键污染。
        # 注意 camera 里刻意不含 index / remote_select：摄像头设备选择是主机特权，
        # 网络侧既不能换设备，也不能把「允许远程选择」这个开关自己打开。
        for section, keys in {
            "camera": {"width", "height", "fps", "quality"},
            "audio": {"enabled", "sample_rate", "chunk"},
            "banner": {"auto_close", "need_ack_default", "tts_default"},
            "tts": {"enabled", "voice", "rate", "volume", "urgent_alert"},
        }.items():
            if isinstance(clean.get(section), dict):
                clean[section] = {k: v for k, v in clean[section].items() if k in keys}
        cfg.update(clean)
        cfg.save()
        if runtime.camera and "camera" in clean:
            runtime.camera.set_config(clean["camera"], remote=True)
        if "require_auth" in clean:
            runtime.revoke_tokens()
        runtime.broadcast_json({"type": "config", "config": cfg.public()})
        runtime.log("info", "管理端更新了设备配置")
        return {"ok": True, "config": cfg.public()}

    @app.post("/api/password/change")
    async def change_password(request: Request):
        body = await _body(request)
        require_password(cfg, body.get("old_password"))
        new_password = str(body.get("new_password") or "")
        if len(new_password) < 4:
            raise HTTPException(status_code=400, detail="新密码长度至少 4 位")
        set_password(cfg, new_password)
        runtime.revoke_tokens()
        runtime.log("warning", "安装密码已被修改，所有登录会话已失效")
        return {"ok": True, "token": runtime.issue_token()}

    # ---------------------------------------------------------------- 退出 / 重启
    def do_shutdown() -> None:
        runtime.log("warning", "收到带密码的退出指令，采集端即将关闭")
        fn = app.state.cc.get("shutdown")
        if fn:
            fn()
        else:
            os._exit(0)

    @app.post("/api/agent/stop")
    async def stop_agent(request: Request):
        body = await _body(request)
        require_password(cfg, body.get("password"))
        if runtime.banner:
            runtime.banner.shutdown()
        asyncio.get_running_loop().call_later(0.6, do_shutdown)
        return {"ok": True, "message": "密码校验通过，采集端正在退出"}

    @app.post("/api/agent/restart")
    async def restart_agent(request: Request):
        body = await _body(request)
        require_password(cfg, body.get("password"))
        runtime.log("warning", "收到带密码的重启指令")

        def relaunch() -> None:
            try:
                start_background(force=True)
            except Exception as exc:  # noqa: BLE001
                runtime.log("error", f"重启失败：{exc}")

        threading.Timer(1.5, relaunch).start()
        asyncio.get_running_loop().call_later(0.6, do_shutdown)
        return {"ok": True, "message": "采集端正在重启（约 2 秒后恢复）"}

    # ---------------------------------------------------------------- 摄像头
    @app.get("/api/camera/config")
    async def camera_config(request: Request):
        check_auth(request)
        return {
            "config": runtime.camera.config(),
            "status": runtime.camera.status(),
            "camera_select_locked": not runtime.camera.remote_select_allowed(),
        }

    @app.post("/api/camera/config")
    async def set_camera_config(request: Request):
        check_auth(request)
        payload = await _body(request)
        patch = payload.get("config") if isinstance(payload.get("config"), dict) else payload
        locked = not runtime.camera.remote_select_allowed()
        try:
            result = runtime.camera.set_config(patch, remote=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ignored = [k for k in ("index",) if locked and k in patch]
        runtime.broadcast_json({"type": "camera_config", "config": result})
        runtime.log("info", f"画质已调整：{result}")
        return {
            "ok": True,
            "config": result,
            "camera_select_locked": locked,
            "ignored_fields": ignored,
        }

    @app.get("/api/camera/devices")
    async def camera_devices(request: Request):
        check_auth(request)
        view = await to_thread(lambda: runtime.camera.devices_view(remote=True))
        return view

    @app.get("/api/camera/snapshot")
    async def camera_snapshot(request: Request):
        check_auth(request, allow_internal=True)
        runtime.touch()
        jpeg = await to_thread(runtime.camera.snapshot)
        return Response(content=jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store, no-cache"})

    @app.get("/api/camera/stream")
    async def camera_stream(request: Request):
        check_auth(request)
        q = runtime.camera.subscribe()
        runtime.add_stream()

        async def generate():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        jpeg = await to_thread(q.get, True, 2.0)
                    except queue.Empty:
                        jpeg = runtime.camera.last_jpeg  # 保活并维持画面
                    yield (
                        f"--{MJPEG_BOUNDARY}\r\n"
                        "Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode() + jpeg + b"\r\n"
                    await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                pass
            finally:
                runtime.camera.unsubscribe(q)
                runtime.remove_stream()

        return StreamingResponse(
            generate(),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ---------------------------------------------------------------- 屏幕
    @app.get("/api/screen/displays")
    async def screen_displays(request: Request):
        check_auth(request)
        from agent import screen
        return {"displays": await to_thread(screen.list_displays)}

    @app.get("/api/screen/shot")
    async def screen_shot(request: Request, display: int = 0, scale: float = 1.0):
        check_auth(request)
        from agent import screen
        runtime.touch()
        png, fallback, meta = await to_thread(screen.capture, cfg, display, scale)
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, no-cache",
                "X-CC-Fallback": "1" if fallback else "0",
                # HTTP 头只能包含 latin-1 字符，元信息中的中文需转义
                "X-CC-Meta": json.dumps(meta, ensure_ascii=True),
            },
        )

    # ---------------------------------------------------------------- 横幅
    @app.post("/api/banner/send")
    async def banner_send(request: Request):
        check_auth(request)
        payload = await _body(request)
        try:
            banner = runtime.banner.send(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "banner": banner}

    @app.get("/api/banner/history")
    async def banner_history(request: Request, limit: int = 50):
        check_auth(request)
        return {"items": runtime.banner.list_history(limit),
                "current": runtime.banner.status()["current"]}

    @app.get("/api/banner/status")
    async def banner_status(request: Request):
        check_auth(request)
        return runtime.banner.status()

    @app.post("/api/banner/ack")
    async def banner_ack(request: Request):
        internal = check_auth(request, allow_internal=True)
        payload = await _body(request)
        banner_id = str(payload.get("id") or runtime.banner.current_id or "")
        if not banner_id:
            raise HTTPException(status_code=400, detail="缺少横幅 id")
        try:
            banner = runtime.banner.ack(banner_id, "desktop" if internal else "web")
        except KeyError:
            raise HTTPException(status_code=404, detail="横幅不存在") from None
        return {"ok": True, "banner": banner}

    @app.post("/api/banner/dismiss")
    async def banner_dismiss(request: Request):
        check_auth(request)
        payload = await _body(request)
        return runtime.banner.dismiss(payload.get("id"), reason="web")

    @app.post("/api/markdown/render")
    async def markdown_render(request: Request):
        check_auth(request)
        payload = await _body(request)
        source = str(payload.get("markdown") or "")
        return {"html": to_html(source), "plain": strip_markdown(source)}

    # ---------------------------------------------------------------- TTS
    @app.get("/api/tts/status")
    async def tts_status(request: Request):
        check_auth(request)
        return runtime.tts.status()

    @app.get("/api/tts/voices")
    async def tts_voices():
        return {"voices": TTS_VOICES, "current": cfg.get("tts.voice")}

    @app.post("/api/tts/speak")
    async def tts_speak(request: Request):
        check_auth(request)
        payload = await _body(request)
        text = str(payload.get("text") or "")
        if not text.strip():
            raise HTTPException(status_code=400, detail="播报内容不能为空")
        return runtime.tts.speak(text, urgent=bool(payload.get("urgent")),
                                 voice=payload.get("voice"))

    # ---------------------------------------------------------------- WebSocket
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        client_id = secrets.token_hex(6)
        client = Client(
            id=client_id,
            queue=asyncio.Queue(maxsize=256),
            addr=f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown",
            authed=not runtime.token_required,
        )
        runtime.add_client(client)
        await ws.send_json({
            "type": "hello",
            "client_id": client_id,
            "version": __version__,
            "device": {"name": cfg.get("device_name") or socket.gethostname(),
                       "room": cfg.get("room_name"), "ip": get_local_ip(),
                       "port": cfg.get("port")},
            "token_required": runtime.token_required,
            "authed": client.authed,
            "state": runtime.snapshot(),
        })

        async def sender() -> None:
            while True:
                kind, payload = await client.queue.get()
                if kind == "text":
                    await ws.send_json(payload)
                elif kind == "bytes":
                    await ws.send_bytes(payload)

        send_task = asyncio.create_task(sender())

        async def handle_text(raw: str) -> None:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                return
            mtype = msg.get("type")
            if mtype == "ping":
                await ws.send_json({"type": "pong", "ts": time.time()})
                return
            if mtype == "auth":
                ok = runtime.valid_token(msg.get("token"))
                client.authed = client.authed or ok
                await ws.send_json({"type": "auth_result", "ok": client.authed})
                return
            if runtime.token_required and not client.authed:
                await ws.send_json({"type": "error", "message": "需要管理密码登录"})
                return
            if mtype == "talk":
                # AudioHub 会向所有管理端广播 talk_state，无需在此重复回复
                if runtime.audio:
                    runtime.audio.set_talk_mode(bool(msg.get("active")))
            elif mtype == "camera_config":
                try:
                    result = runtime.camera.set_config(msg.get("config") or msg,
                                                      remote=True)
                    runtime.broadcast_json({"type": "camera_config", "config": result})
                except ValueError as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})
            elif mtype == "banner":
                try:
                    runtime.banner.send(msg.get("banner") or msg)
                except ValueError as exc:
                    await ws.send_json({"type": "error", "message": str(exc)})
            elif mtype == "banner_dismiss":
                runtime.banner.dismiss(msg.get("id"))
            elif mtype == "tts":
                runtime.tts.speak(str(msg.get("text") or ""),
                                  urgent=bool(msg.get("urgent")),
                                  voice=msg.get("voice"))
            elif mtype == "status":
                await ws.send_json({"type": "status", **runtime.snapshot()})

        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") is not None:
                    await handle_text(message["text"])
                elif message.get("bytes") is not None and runtime.audio:
                    runtime.audio.play(message["bytes"])
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            send_task.cancel()
            runtime.remove_client(client_id)
            # 最后一个管理端断开后自动退出对讲，避免教室麦克风一直被静音
            if runtime.active_count == 0 and runtime.audio \
                    and runtime.audio.status()["talk_mode"]:
                runtime.audio.set_talk_mode(False)

    # ---------------------------------------------------------------- 静态页面
    if MANAGER_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(MANAGER_DIR), html=True), name="manager")
    else:  # pragma: no cover
        @app.get("/")
        async def root():
            return JSONResponse({"error": "管理端页面缺失：manager/ 目录不存在"})

    return app
