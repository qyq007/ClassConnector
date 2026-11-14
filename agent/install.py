"""采集端安装器：设置退出密码、注册开机自启、后台启动。

交互安装::

    python -m agent.install

无人值守安装（便于批量部署 / 自动化测试）::

    python -m agent.install --yes --password MyPass123 --room "高三(1)班" --port 8420

卸载（需要安装密码）::

    python -m agent.install --uninstall --password MyPass123 --purge
"""

from __future__ import annotations

import argparse
import getpass
import sys
import time

from agent.config import (
    Config, has_password, load_config, log_path, set_password, verify_password,
)
from agent.platform_util import (
    autostart_status, disable_autostart, enable_autostart, is_running,
    local_url, project_root, start_background, stop_background,
)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消安装")
        sys.exit(1)
    return value or default


def _ask_yes(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        value = input(f"{prompt} ({hint}): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消安装")
        sys.exit(1)
    if not value:
        return default
    return value in ("y", "yes", "是", "1")


def _optional_dependency_report() -> None:
    import importlib
    import importlib.util
    checks = [
        ("opencv-python", "cv2", "摄像头画面"),
        ("Pillow", "PIL", "测试画面 / 截图"),
        ("mss", "mss", "多显示器截图"),
        ("PyAudio", "pyaudio", "音频监听与对讲播放"),
        ("edge-tts", "edge_tts", "横幅语音播报（需联网）"),
        ("pygame", "pygame", "语音/警报音播放（推荐）"),
        ("pystray", "pystray", "系统托盘"),
    ]
    missing = []
    for pkg, module, feature in checks:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(f"{pkg}（{feature}）")
    import shutil
    if not shutil.which("ffplay") and not importlib.util.find_spec("pygame"):
        missing.append("音频播放器：请安装 pygame 或 ffmpeg（否则横幅语音无法播放）")
    if missing:
        print("\n[可选依赖] 以下组件未安装，相关功能会自动降级：")
        for item in missing:
            print("   -", item)
        print("   需要时可执行： pip install -r requirements.txt")
    else:
        print("\n[可选依赖] 全部就绪 ✓")


def _print_summary(cfg: Config, started: bool) -> None:
    port = int(cfg.get("port", 8420))
    print("\n" + "=" * 62)
    print("  ClassConnector 采集端安装完成")
    print("=" * 62)
    print(f"  班级名称   : {cfg.get('room_name')}")
    print(f"  管理地址   : {local_url(port)}")
    print(f"  本机访问   : http://127.0.0.1:{port}")
    print("  退出密码   : 已设置（PBKDF2 加盐存储，退出/改密时校验）")
    print(f"  开机自启   : {'已启用' if autostart_status()['enabled'] else '未启用'}")
    print(f"  后台运行   : {'运行中' if is_running() else ('已启动' if started else '未启动')}")
    print(f"  配置文件   : {cfg.path}")
    print(f"  运行日志   : {log_path()}")
    print("\n  在管理端浏览器打开上面的「管理地址」，输入设备 IP + 端口即可连接。")
    print("  卸载：python -m agent.install --uninstall --password <安装密码>")
    print("=" * 62)


def do_install(args: argparse.Namespace) -> int:
    cfg = load_config()
    print("=" * 62)
    print("  ClassConnector 班级连接器 · 采集端安装")
    print("=" * 62)
    print(f"  安装目录：{project_root()}\n")

    if args.yes:
        room = args.room or cfg.get("room_name", "未命名班级")
        port = args.port or int(cfg.get("port", 8420))
        password = args.password
        autostart = not args.no_autostart
        start = not args.no_start
    else:
        room = _ask("班级 / 教室名称", str(cfg.get("room_name", "未命名班级")))
        port = int(_ask("监听端口", str(cfg.get("port", 8420))))
        autostart = _ask_yes("是否开机自启并后台运行？", True)
        start = _ask_yes("是否立即后台启动采集端？", True)
        password = args.password or ""
        if has_password(cfg) and args.keep_password:
            print("  保留原有退出密码")
        elif password and len(password) >= 4:
            print("  使用命令行提供的退出密码")
        else:
            while True:
                password = getpass.getpass("设置退出密码（至少 4 位）: ")
                if len(password) < 4:
                    print("  密码太短，请重新输入")
                    continue
                confirm = getpass.getpass("再次输入退出密码: ")
                if password != confirm:
                    print("  两次输入不一致，请重新输入")
                    continue
                break

    if not (1 <= port <= 65535):
        print("错误：端口必须在 1-65535 之间")
        return 1
    cfg.set("room_name", room)
    cfg.set("port", port)
    if password:
        try:
            set_password(cfg, password)
        except ValueError as exc:
            print(f"错误：{exc}")
            return 1
    elif not has_password(cfg):
        print("错误：必须设置退出密码（无人值守安装请使用 --password）")
        return 1
    cfg.save()

    if autostart:
        try:
            if args.systemd:
                from agent.platform_util import enable_systemd
                target = enable_systemd()
            else:
                target = enable_autostart()
            print(f"\n[开机自启] 已注册：{target}")
        except Exception as exc:  # noqa: BLE001
            print(f"[开机自启] 注册失败：{exc}")
    else:
        disable_autostart()
        print("\n[开机自启] 已关闭")

    started = False
    if start:
        if is_running():
            print("[后台运行] 检测到采集端已在运行，正在重启以应用新配置…")
            stop_background()
            time.sleep(1.0)
        try:
            pid = start_background(force=True)
            started = True
            print(f"[后台运行] 采集端已启动（PID {pid}），无控制台窗口")
        except Exception as exc:  # noqa: BLE001
            print(f"[后台运行] 启动失败：{exc}")
            return 1
        # 简单等待端口就绪
        import urllib.request
        for _ in range(15):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",
                                           timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:  # noqa: BLE001
                time.sleep(0.4)

    _optional_dependency_report()
    _print_summary(cfg, started)
    return 0


def do_uninstall(args: argparse.Namespace) -> int:
    cfg = load_config()
    password = args.password
    if has_password(cfg):
        if not password:
            try:
                password = getpass.getpass("请输入安装密码以卸载: ")
            except (EOFError, KeyboardInterrupt):
                return 1
        if not verify_password(cfg, password):
            print("错误：密码不正确，卸载已取消（防止被随意关闭采集端）")
            return 1
    elif not args.force:
        print("错误：未设置安装密码，如确认卸载请加 --force")
        return 1

    stopped = stop_background()
    disable_autostart()
    print(f"[卸载] 后台进程：{'已停止' if stopped else '未在运行'}")
    print("[卸载] 开机自启：已移除")
    if args.purge:
        try:
            cfg.path.unlink(missing_ok=True)
            print(f"[卸载] 配置文件已删除：{cfg.path}")
        except OSError as exc:
            print(f"[卸载] 删除配置失败：{exc}")
    else:
        print(f"[卸载] 配置文件已保留：{cfg.path}（如需彻底删除请加 --purge）")
    print("[卸载] 完成。程序文件本身未删除，可随时重新安装。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ClassConnector 采集端安装器")
    parser.add_argument("--yes", "-y", action="store_true", help="无人值守安装")
    parser.add_argument("--password", help="安装/退出密码（无人值守安装必填）")
    parser.add_argument("--room", help="班级 / 教室名称")
    parser.add_argument("--port", type=int, help="监听端口")
    parser.add_argument("--no-autostart", action="store_true", help="不注册开机自启")
    parser.add_argument("--no-start", action="store_true", help="安装后不立即启动")
    parser.add_argument("--keep-password", action="store_true", help="交互安装时保留原密码")
    parser.add_argument("--uninstall", action="store_true", help="卸载（需安装密码）")
    parser.add_argument("--purge", action="store_true", help="卸载时删除配置文件")
    parser.add_argument("--force", action="store_true", help="无密码时强制卸载")
    parser.add_argument("--systemd", action="store_true",
                        help="Linux 无图形会话时使用 systemd user service 实现自启")
    args = parser.parse_args()

    if args.uninstall:
        return do_uninstall(args)
    return do_install(args)


if __name__ == "__main__":
    sys.exit(main())
