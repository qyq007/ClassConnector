#!/usr/bin/env python3
"""生成 ClassConnector 的统一图标资源（桌面 exe 与 Web 管理端共用同一图形）。

图形为深蓝圆角方底 + 两个白色「C」弧 + 中间一条连接线，象征
Class <-> Connector 的连接关系；纯几何绘制，不依赖任何字体文件。

产物：
    assets/icon.svg                 矢量源文件
    assets/icon.png                 512 px（文档 / 预览）
    assets/icon.ico                 Windows exe 图标（16~256 多尺寸）
    manager/icon.png                512 px（Web 顶栏 logo、PWA）
    manager/favicon.ico             浏览器标签页
    manager/apple-touch-icon.png    180 px（iOS 主屏）

用法：python scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
MANAGER = ROOT / "manager"

SIZE = 1024
TOP = (37, 99, 235)       # #2563eb
BOTTOM = (13, 36, 92)     # #0d245c
WHITE = (255, 255, 255, 255)
LINK = (147, 197, 253, 255)  # #93c5fd


def _gradient(size: int) -> Image.Image:
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(size):
            px[x, y] = color
    return grad


def draw(size: int = SIZE) -> Image.Image:
    """按指定边长渲染图标（内部始终以 1024 画布绘制再缩放，保证细节）。"""
    grad = _gradient(SIZE)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, SIZE - 1, SIZE - 1), radius=224, fill=255)

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # 两个「C」：开口朝右，中间用短线相连
    d.arc((150, 300, 510, 660), start=50, end=310, fill=WHITE, width=96)
    d.arc((560, 300, 920, 660), start=50, end=310, fill=WHITE, width=96)
    d.line((505, 480, 565, 480), fill=LINK, width=30)
    d.ellipse((513, 458, 557, 502), fill=LINK)

    if size != SIZE:
        img = img.resize((size, size), Image.LANCZOS)
    return img


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <defs>
    <linearGradient id="cc-bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2563eb"/>
      <stop offset="1" stop-color="#0d245c"/>
    </linearGradient>
  </defs>
  <rect width="1024" height="1024" rx="224" fill="url(#cc-bg)"/>
  <g fill="none" stroke="#ffffff" stroke-width="96" stroke-linecap="round">
    <path d="M 445.7 617.9 A 180 180 0 1 1 445.7 342.1"/>
    <path d="M 855.7 617.9 A 180 180 0 1 1 855.7 342.1"/>
  </g>
  <line x1="505" y1="480" x2="565" y2="480" stroke="#93c5fd" stroke-width="30" stroke-linecap="round"/>
  <circle cx="535" cy="480" r="22" fill="#93c5fd"/>
</svg>
"""

MANIFEST = """{
  "name": "ClassConnector 班级连接器",
  "short_name": "班级连接器",
  "description": "局域网班级连接器管理端",
  "icons": [
    { "src": "./icon.png", "sizes": "512x512", "type": "image/png" },
    { "src": "./apple-touch-icon.png", "sizes": "180x180", "type": "image/png" }
  ],
  "start_url": "./",
  "display": "standalone",
  "background_color": "#0b1220",
  "theme_color": "#0b1220",
  "lang": "zh-CN"
}
"""


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    MANAGER.mkdir(parents=True, exist_ok=True)

    (ASSETS / "icon.svg").write_text(SVG, encoding="utf-8")
    big = draw(512)
    big.save(ASSETS / "icon.png")
    big.save(MANAGER / "icon.png")

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw(256)
    base.save(ASSETS / "icon.ico", format="ICO",
              sizes=[(s, s) for s in ico_sizes])
    base.save(MANAGER / "favicon.ico", format="ICO",
              sizes=[(s, s) for s in ico_sizes])
    draw(180).save(MANAGER / "apple-touch-icon.png")
    (MANAGER / "manifest.webmanifest").write_text(MANIFEST, encoding="utf-8")

    for path in sorted(list(ASSETS.iterdir()) + list(MANAGER.glob("*icon*"))
                       + list(MANAGER.glob("*.webmanifest"))):
        if path.is_file():
            print(f"  {path.relative_to(ROOT)}  {path.stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
