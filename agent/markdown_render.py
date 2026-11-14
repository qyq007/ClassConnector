"""轻量 Markdown 渲染（零依赖）。

提供三种输出，覆盖本项目全部使用场景：
- ``to_html``      : 管理端预览 / REST 接口，自动转义 HTML 防注入
- ``render_tk``    : 采集端全屏横幅窗口（tkinter Text，按标签着色排版）
- ``strip_markdown``: 转成适合 Edge TTS 朗读的纯文本
"""

from __future__ import annotations

import html
import re
import sys
from typing import Any

INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|__.+?__|~~.+?~~|`[^`]+`|\*[^*\n]+?\*|_[^_\n]+?_|"
    r"!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\))"
)
LINK_RE = re.compile(r"^!?\[([^\]]*)\]\(([^)]+)\)$")
FENCE_RE = re.compile(r"^\s*```")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
UL_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
OL_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
TASK_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _inline(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """行内标记 -> [(纯文本, 标签元组)]"""
    out: list[tuple[str, tuple[str, ...]]] = []
    for part in INLINE_RE.split(text):
        if not part:
            continue
        matched = INLINE_RE.fullmatch(part)
        if not matched:
            out.append((part, ()))
            continue
        if part.startswith("**") or part.startswith("__"):
            out.append((part[2:-2], ("bold",)))
        elif part.startswith("~~"):
            out.append((part[2:-2], ("strike",)))
        elif part.startswith("`"):
            out.append((part[1:-1], ("code",)))
        elif part.startswith("*"):
            out.append((part[1:-1], ("italic",)))
        elif part.startswith("_"):
            out.append((part[1:-1], ("italic",)))
        elif part.startswith("!"):
            m = LINK_RE.match(part)
            out.append((m.group(1) or "图片", ("muted",)) if m else (part, ()))
        elif part.startswith("["):
            m = LINK_RE.match(part)
            if m:
                out.append((m.group(1), ("link",)))
            else:
                out.append((part, ()))
        else:
            out.append((part, ()))
    return out


def _inline_html(text: str) -> str:
    pieces = []
    for content, tags in _inline(text):
        value = html.escape(content)
        if "bold" in tags:
            value = f"<strong>{value}</strong>"
        if "italic" in tags:
            value = f"<em>{value}</em>"
        if "strike" in tags:
            value = f"<del>{value}</del>"
        if "code" in tags:
            value = f"<code>{value}</code>"
        if "muted" in tags:
            value = f'<span class="md-muted">{value}</span>'
        if "link" in tags:
            value = f'<span class="md-link">{value}</span>'
        pieces.append(value)
    return "".join(pieces)


def to_html(source: str) -> str:
    """Markdown -> HTML 片段（已转义，可安全插入页面）。"""
    lines = (source or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if FENCE_RE.match(line):
            lang = line.strip().lstrip("`").strip()
            i += 1
            code: list[str] = []
            while i < len(lines) and not FENCE_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        if HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline_html(m.group(2))}</h{level}>")
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(
                f"<th>{_inline_html(c)}</th>" for c in header) + "</tr></thead><tbody>")
            for row in rows:
                out.append("<tr>" + "".join(f"<td>{_inline_html(c)}</td>"
                                            for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue
        if QUOTE_RE.match(line):
            buf: list[str] = []
            while i < len(lines) and QUOTE_RE.match(lines[i]):
                buf.append(QUOTE_RE.match(lines[i]).group(1))  # type: ignore[union-attr]
                i += 1
            out.append(f"<blockquote>{_inline_html(' '.join(buf))}</blockquote>")
            continue
        if UL_RE.match(line) or OL_RE.match(line):
            ordered = bool(OL_RE.match(line))
            items: list[str] = []
            while i < len(lines):
                m2 = OL_RE.match(lines[i]) if ordered else UL_RE.match(lines[i])
                if not m2:
                    break
                items.append(m2.group(1))
                i += 1
            tag = "ol" if ordered else "ul"
            body = ""
            for item in items:
                task = TASK_RE.match(item)
                if task:
                    mark = "☑" if task.group(1).lower() == "x" else "☐"
                    body += f'<li class="md-task">{mark} {_inline_html(task.group(2))}</li>'
                else:
                    body += f"<li>{_inline_html(item)}</li>"
            out.append(f"<{tag}>{body}</{tag}>")
            continue
        if not line.strip():
            i += 1
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not (
            HEADING_RE.match(lines[i]) or HR_RE.match(lines[i])
            or QUOTE_RE.match(lines[i]) or UL_RE.match(lines[i])
            or OL_RE.match(lines[i]) or FENCE_RE.match(lines[i])
        ):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{_inline_html(' '.join(p.strip() for p in para))}</p>")
    return "\n".join(out)


def strip_markdown(source: str) -> str:
    """转为适合语音朗读的纯文本。"""
    def _fence(match: re.Match) -> str:
        lines = match.group(0).split("\n")
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]  # 丢弃 ```lang 中的语言标识，避免被朗读
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)

    text = (source or "").replace("\r\n", "\n")
    text = re.sub(r"```.*?```", _fence, text, flags=re.S)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+\[([ xX])\]\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\[[ xX]\]\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", "", text, flags=re.M)
    text = re.sub(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", "", text, flags=re.M)
    text = re.sub(r"[*_~`|]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# tkinter 渲染（全屏横幅窗口使用）
# ---------------------------------------------------------------------------

def configure_tags(widget: Any, *, urgent: bool = False) -> None:
    """为 Text 组件配置 Markdown 标签样式。"""
    if sys.platform == "win32":
        base = "Microsoft YaHei"
    elif sys.platform == "darwin":
        base = "PingFang SC"
    else:
        base = "Noto Sans CJK SC"
    fg = "#f8fafc"
    accent = "#fecaca" if urgent else "#bfdbfe"
    widget.tag_configure("h1", font=(base, 40, "bold"), foreground=fg,
                         spacing1=18, spacing3=14, justify="center")
    widget.tag_configure("h2", font=(base, 30, "bold"), foreground=accent,
                         spacing1=14, spacing3=8)
    widget.tag_configure("h3", font=(base, 23, "bold"), foreground=fg,
                         spacing1=10, spacing3=6)
    widget.tag_configure("p", font=(base, 19), foreground=fg,
                         spacing1=4, spacing3=10, wrap="word")
    widget.tag_configure("li", font=(base, 19), foreground=fg,
                         lmargin1=60, lmargin2=90, spacing3=6)
    widget.tag_configure("quote", font=(base, 19, "italic"),
                         foreground=accent, lmargin1=60, spacing3=10)
    widget.tag_configure("code", font=("Consolas", 17), foreground="#a5b4fc",
                         background="#1e293b", lmargin1=40, spacing3=10)
    widget.tag_configure("hr", foreground="#475569", spacing1=10, spacing3=10)
    widget.tag_configure("bold", font=(base, 19, "bold"))
    widget.tag_configure("italic", font=(base, 19, "italic"))
    widget.tag_configure("strike", overstrike=True)
    widget.tag_configure("inline_code", font=("Consolas", 18),
                         foreground="#fbbf24", background="#1e293b")
    widget.tag_configure("link", foreground="#93c5fd", underline=True)
    widget.tag_configure("muted", foreground="#94a3b8")


def render_tk(widget: Any, source: str) -> None:
    """把 Markdown 渲染进 tkinter Text（需先调用 configure_tags）。"""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    lines = (source or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if FENCE_RE.match(line):
            i += 1
            code: list[str] = []
            while i < len(lines) and not FENCE_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            widget.insert("end", "\n".join(code) + "\n", "code")
            continue
        if HR_RE.match(line):
            widget.insert("end", "─" * 60 + "\n", "hr")
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m:
            level = min(3, len(m.group(1)))
            widget.insert("end", strip_markdown(m.group(2)) + "\n", f"h{level}")
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                widget.insert("end", "   ".join(strip_markdown(c) for c in cells) + "\n", "code")
                i += 1
            continue
        if QUOTE_RE.match(line):
            buf: list[str] = []
            while i < len(lines) and QUOTE_RE.match(lines[i]):
                buf.append(QUOTE_RE.match(lines[i]).group(1))  # type: ignore[union-attr]
                i += 1
            widget.insert("end", "│ " + " ".join(buf) + "\n", "quote")
            continue
        if UL_RE.match(line) or OL_RE.match(line):
            ordered = bool(OL_RE.match(line))
            n = 1
            while i < len(lines):
                m2 = OL_RE.match(lines[i]) if ordered else UL_RE.match(lines[i])
                if not m2:
                    break
                item = m2.group(1)
                task = TASK_RE.match(item)
                if task:
                    prefix = "☑ " if task.group(1).lower() == "x" else "☐ "
                    item = task.group(2)
                else:
                    prefix = f"{n}. " if ordered else "• "
                    n += 1
                widget.insert("end", prefix, "li")
                _insert_inline(widget, item, "li")
                widget.insert("end", "\n", "li")
                i += 1
            continue
        if not line.strip():
            i += 1
            continue
        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not (
            HEADING_RE.match(lines[i]) or HR_RE.match(lines[i])
            or QUOTE_RE.match(lines[i]) or UL_RE.match(lines[i])
            or OL_RE.match(lines[i]) or FENCE_RE.match(lines[i])
        ):
            para.append(lines[i].strip())
            i += 1
        _insert_inline(widget, " ".join(para), "p")
        widget.insert("end", "\n", "p")
    widget.configure(state="disabled")


def _insert_inline(widget: Any, text: str, base_tag: str) -> None:
    for content, tags in _inline(text):
        if not content:
            continue
        tag_map = {
            "bold": "bold", "italic": "italic", "strike": "strike",
            "code": "inline_code", "link": "link", "muted": "muted",
        }
        extra = next((tag_map[t] for t in tags if t in tag_map), base_tag)
        # tkinter 支持多标签叠加
        widget.insert("end", content, (base_tag, extra) if extra != base_tag else base_tag)
