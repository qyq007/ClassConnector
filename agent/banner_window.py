"""横幅窗口（独立子进程入口，不要在主服务中直接 import）。

用法：``python -m agent.banner_window <spec.json>``

全屏置顶、Markdown 长文本可滚动、支持签收按钮、紧急红色样式与倒计时。
签收结果通过本地 HTTP 接口回传采集端服务，进程退出即视为窗口关闭。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


def _post(url: str, payload: dict[str, Any], token: str) -> bool:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-CC-Token": token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001
        print(f"[banner] 签收上报失败：{exc}", file=sys.stderr)
        return False


def _font_family() -> str:
    if sys.platform == "win32":
        return "Microsoft YaHei"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python -m agent.banner_window <spec.json>", file=sys.stderr)
        return 2
    spec_path = Path(sys.argv[1])
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[banner] 无法读取横幅数据：{exc}", file=sys.stderr)
        return 1
    try:
        import tkinter as tk
        from tkinter import Scrollbar, Text
    except ImportError:
        print("[banner] 当前环境没有 tkinter，无法弹出横幅窗口", file=sys.stderr)
        return 1

    from agent.markdown_render import configure_tags, render_tk

    urgent = bool(spec.get("urgent"))
    need_ack = bool(spec.get("need_ack"))
    duration = int(spec.get("duration") or 0)
    banner_id = spec.get("id", "")
    api_base = spec.get("api_base", "http://127.0.0.1:8420")
    token = spec.get("token", "")
    family = _font_family()

    bg = "#450a0a" if urgent else "#0f172a"
    panel = "#7f1d1d" if urgent else "#1e293b"
    accent = "#fca5a5" if urgent else "#93c5fd"
    title_fg = "#fff1f2" if urgent else "#f8fafc"

    root = tk.Tk()
    root.title("ClassConnector 班级通知")
    root.configure(bg=bg)
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    try:
        root.overrideredirect(True)
    except tk.TclError:
        pass
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()

    alive = {"value": True}
    acked = {"value": False}
    remaining = {"value": duration}

    # ---------------- 顶部状态条 ----------------
    top = tk.Frame(root, bg=panel, height=64)
    top.pack(fill="x", side="top")
    tk.Label(top, text=f"ClassConnector · {spec.get('room', '班级')}",
             font=(family, 15), fg="#cbd5e1", bg=panel).pack(side="left", padx=28, pady=14)
    badge = tk.Label(top,
                     text="⚠  紧急通知" if urgent else "📢  班级通知",
                     font=(family, 16, "bold"),
                     fg="#ffffff" if urgent else accent,
                     bg="#dc2626" if urgent else panel,
                     padx=16, pady=6)
    badge.pack(side="left", padx=8)
    clock = tk.Label(top, font=(family, 15), fg="#cbd5e1", bg=panel)
    clock.pack(side="right", padx=28)

    # ---------------- 标题 ----------------
    tk.Label(root, text=spec.get("title", "班级通知"),
             font=(family, max(30, min(52, screen_w // 30)), "bold"),
             fg=title_fg, bg=bg, wraplength=int(screen_w * 0.9),
             justify="center").pack(pady=(max(24, screen_h // 16), 12))

    # ---------------- 正文（可滚动 Markdown） ----------------
    body = tk.Frame(root, bg=bg)
    body.pack(fill="both", expand=True, padx=int(screen_w * 0.1))
    scroll = Scrollbar(body, width=14, troughcolor=bg, bg=panel)
    scroll.pack(side="right", fill="y")
    text = Text(body, bg=bg, fg="#f8fafc", bd=0, highlightthickness=0,
                insertbackground=bg, yscrollcommand=scroll.set,
                wrap="word", padx=24, pady=10, cursor="arrow")
    text.pack(side="left", fill="both", expand=True)
    scroll.configure(command=text.yview)
    configure_tags(text, urgent=urgent)
    # 长文本自动缩小字号
    length = len(spec.get("markdown", ""))
    size = 19 if length < 1200 else (17 if length < 4000 else 15)
    text.tag_configure("p", font=(family, size))
    text.tag_configure("li", font=(family, size), lmargin1=60, lmargin2=90)
    text.tag_configure("quote", font=(family, size, "italic"))
    render_tk(text, spec.get("markdown", "（无正文）"))
    text.bind("<MouseWheel>", lambda e: text.yview_scroll(-1 if e.delta > 0 else 1, "units"))
    text.bind("<Button-4>", lambda e: text.yview_scroll(-3, "units"))
    text.bind("<Button-5>", lambda e: text.yview_scroll(3, "units"))

    # ---------------- 底部操作区 ----------------
    bottom = tk.Frame(root, bg=panel, height=110)
    bottom.pack(fill="x", side="bottom")
    countdown = tk.Label(bottom, font=(family, 14), fg="#94a3b8", bg=panel)
    countdown.pack(side="left", padx=28)

    def close_window() -> None:
        if not alive["value"]:
            return
        alive["value"] = False
        try:
            root.destroy()
        except tk.TclError:
            pass

    def do_ack() -> None:
        if acked["value"]:
            return
        acked["value"] = True
        ok = _post(f"{api_base}/api/banner/ack",
                   {"id": banner_id, "source": "desktop"}, token)
        ack_btn.configure(text="✓ 已签收，谢谢！" if ok else "✓ 已签收（上报失败）",
                          state="disabled", bg="#166534" if ok else "#4d7c0f")
        root.after(1200, close_window)

    ack_btn = tk.Button(bottom, text="我已知悉，点击签收", command=do_ack,
                        font=(family, 20, "bold"), fg="#ffffff",
                        bg="#dc2626" if urgent else "#2563eb",
                        activebackground="#b91c1c" if urgent else "#1d4ed8",
                        relief="flat", padx=48, pady=12, cursor="hand2")
    if need_ack:
        ack_btn.pack(side="right", padx=20, pady=18)
    close_btn = tk.Button(bottom, text="关闭", command=close_window,
                          font=(family, 16), fg="#cbd5e1", bg=panel,
                          relief="flat", padx=24, pady=10, cursor="hand2")
    if not need_ack:
        close_btn.pack(side="right", padx=20, pady=18)

    def on_key(event: Any) -> None:
        if event.keysym == "Escape" and not need_ack:
            close_window()
        elif event.keysym == "Escape" and need_ack:
            countdown.configure(text="请先点击「签收」后窗口才会关闭", fg="#fbbf24")

    root.bind("<Escape>", on_key)

    # ---------------- 定时刷新 ----------------
    def tick() -> None:
        if not alive["value"]:
            return
        clock.configure(text=time.strftime("%Y-%m-%d  %H:%M:%S"))
        if remaining["value"] > 0:
            remaining["value"] -= 1
            countdown.configure(text=f"本通知将在 {remaining['value']} 秒后自动关闭")
            if remaining["value"] <= 0:
                close_window()
                return
        elif duration == 0 and need_ack and not acked["value"]:
            countdown.configure(text="请阅读后点击右侧按钮签收", fg="#cbd5e1")
        # 保持置顶，防止被其它全屏窗口覆盖
        try:
            root.lift()
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        if urgent:
            current = badge.cget("bg")
            badge.configure(bg="#ef4444" if current == "#dc2626" else "#dc2626")
        root.after(1000, tick)

    tick()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
