"""安装密码完整流程测试（自带独立服务实例，端口 18499）。

    python tests/password_flow_test.py

流程：安装器设置密码 -> 启动采集端 -> 验证错误/正确密码 -> 开启管理登录 ->
带令牌访问 -> 校验退出密码 -> 退出后进程确实终止 -> 验证开机自启注册/移除。
不会触碰真实用户配置，全部在临时目录中完成。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 18499
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "ClassConn@2026"


def request(path, payload=None, token=None, timeout=5):
    url = BASE + path
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-CC-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def wait_ready(proc, seconds=25):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"采集端进程提前退出，code={proc.returncode}")
        try:
            status, _ = request("/api/health", timeout=1)
            if status == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    raise RuntimeError("采集端启动超时")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    tmp = Path(tempfile.mkdtemp(prefix="cc-pwd-"))
    env = {
        **os.environ,
        "CLASSCONNECTOR_HOME": str(tmp / "data"),
        "CLASSCONNECTOR_CONFIG": str(tmp / "data" / "config.json"),
        "HOME": str(tmp / "home"),          # 自启文件写入临时 HOME
        "PYTHONPATH": str(ROOT),
    }
    (tmp / "home").mkdir(exist_ok=True)
    (tmp / "data").mkdir(exist_ok=True)
    ok = 0
    total = 0

    def check(name, condition, extra=""):
        nonlocal ok, total
        total += 1
        ok += 1 if condition else 0
        print(f"  [{'PASS' if condition else 'FAIL'}] {name} {extra}")
        return condition

    print("=" * 64)
    print("  ClassConnector · 安装密码流程测试")
    print("=" * 64)

    # 1. 安装器设置密码（不启动、不注册自启）
    install = subprocess.run(
        [sys.executable, "-m", "agent.install", "--yes", "--password", PASSWORD,
         "--room", "测试班级", "--port", str(PORT), "--no-autostart", "--no-start"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60,
    )
    check("安装器执行成功", install.returncode == 0,
          install.stderr.strip()[:160] if install.returncode else "")
    cfg_path = tmp / "data" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    check("密码以 PBKDF2 盐值存储", bool(cfg["password_hash"]) and bool(cfg["password_salt"])
          and PASSWORD not in cfg_path.read_text(encoding="utf-8"))

    # 2. 启动独立服务实例
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent", "--no-tray", "--port", str(PORT)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready(proc)
        check("采集端启动成功", True, f"PID {proc.pid}")
        status, health = request("/api/health")
        check("健康检查不泄露密码哈希",
              "password_hash" not in json.dumps(health)
              and "password_salt" not in json.dumps(health))

        # 3. 密码校验
        status, body = request("/api/auth", {"password": "wrong"})
        check("错误密码被拒绝", status == 403, f"HTTP {status}")
        status, body = request("/api/auth", {"password": PASSWORD})
        token = body.get("token", "")
        check("正确密码返回访问令牌", status == 200 and bool(token))

        # 4. 开启管理登录验证（修改开关本身需要密码）
        status, body = request("/api/config", {"require_auth": True})
        check("无密码不能开启登录验证", status == 403, f"HTTP {status}")
        status, body = request("/api/config",
                               {"require_auth": True, "password": PASSWORD})
        check("带密码可开启登录验证", status == 200 and body["config"]["require_auth"] is True)

        status, _ = request("/api/status")
        check("未登录访问被拦截", status == 401, f"HTTP {status}")
        status, _ = request("/api/status", token=token)
        check("切换安全设置后旧令牌失效", status == 401, f"HTTP {status}")
        # 服务端吊销旧会话后，管理端会立即用安装密码重新登录
        status, body = request("/api/auth", {"password": PASSWORD})
        token = body.get("token", "")
        check("重新登录获得新令牌", status == 200 and bool(token))
        status, _ = request("/api/status", token=token)
        check("带新令牌访问放行", status == 200, f"HTTP {status}")

        # 5. 退出必须密码
        status, _ = request("/api/agent/stop", {"password": "wrong"})
        check("错误密码不能退出采集端", status == 403, f"HTTP {status}")
        status, body = request("/api/agent/stop", {"password": PASSWORD})
        check("正确密码被接受", status == 200, body.get("message", ""))

        for _ in range(20):
            if proc.poll() is not None:
                break
            time.sleep(0.3)
        check("采集端确实已退出", proc.poll() is not None)

        # 6. 开机自启注册 / 移除（Linux XDG）
        from agent.platform_util import autostart_status, disable_autostart, enable_autostart
        os.environ["HOME"] = str(tmp / "home")
        target = enable_autostart()
        desktop = Path(target.split("-> ")[-1])
        check("开机自启注册成功", autostart_status()["enabled"] and desktop.exists(),
              str(desktop))
        disable_autostart()
        check("开机自启可移除", not autostart_status()["enabled"])
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("-" * 64)
    print(f"  结果：{ok}/{total} 项通过")
    print("=" * 64)
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
