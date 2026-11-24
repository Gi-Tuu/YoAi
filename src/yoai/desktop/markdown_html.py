"""把模型返回的 Markdown 转成 QTextBrowser 可显示的 HTML（轻量、无第三方依赖）。

设计原则：
- **先转义再解析**：任何文本先 html.escape，之后只生成我们自己的标签，
  模型输出里的 `<script>` / `onerror=` 等无法注入；
- **链接只认 http/https**：其它协议（`file://`、`javascript:`）降级为纯文本；
- **块的边界明确**：代码块优先消费，内部不再解析 markdown；
- 只支持 QTextBrowser 能渲染的 HTML 子集，不引入 QtWebEngine / mistune 等依赖，
  exe 不增重。

用于对话视图中 **assistant 消息**；用户消息仍按纯文本转义显示（用户输入不该被当指令渲染）。
"""
from __future__ import annotations

import html
import re

_PLACEHOLDER = "\x00MD{}CODE\x00"


def _inline(text: str, *, link_color: str) -> str:
    """行内 markdown：行内代码 → 链接 → 粗体 → 斜体（text 必须已转义）。"""
    codes: list[str] = []

    def _stash_code(m: re.Match[str]) -> str:
        codes.append(f'<code style="background:{_CODE_BG}; padding:1px 4px; '
                     f'font-family:Consolas,Monaco,monospace;">{m.group(1)}</code>')
        return _PLACEHOLDER.format(len(codes) - 1)

    out = re.sub(r"`([^`\n]+)`", _stash_code, text)
    # 链接：目标必须是 http(s)；显示文本就是已转义的原文
    def _link(m: re.Match[str]) -> str:
        # 文本已整体 html.escape（& → &amp;），URL 里若含 & 也已是 &amp;，
        # 不再二次 escape；引号已被转义为 &quot;，不会逃出 href 属性。
        url = m.group(2)
        if not re.match(r"^https?://[^\s\"']+$", url, re.IGNORECASE):
            return m.group(0)
        return (f'<a href="{url}" style="color:{link_color}; '
                f'text-decoration:underline;">{m.group(1)}</a>')

    out = re.sub(r"\[([^\]\n]+)\]\(([^)\n]+)\)", _link, out)
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    for idx, code_html in enumerate(codes):
        out = out.replace(_PLACEHOLDER.format(idx), code_html)
    return out


_CODE_BG = "rgba(127,127,127,0.12)"


def md_to_html(text: str, *, link_color: str = "#a53b2b",
               inline: bool = False) -> str:
    """Markdown 文本 → HTML 片段。支持代码块/标题/列表/水平线/粗斜体/行内码/链接。

    inline=True：普通段落用 span（不换行），用于「[标签] 内容」需要同行的场景。
    """
    # 先整体转义（引号也转）——后续所有分支处理的都是安全文本，
    # 模型输出里的 <script> / onerror= 等绝无可能变成真实标签。
    raw = html.escape(str(text or ""), quote=True)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    parts: list[str] = []
    i = 0

    def _flush_paragraph(buf: list[str]) -> None:
        if not buf:
            return
        body = "<br>".join(_inline(line, link_color=link_color) for line in buf)
        if inline:
            parts.append(f'<span>{body}</span>')
        else:
            parts.append(f'<p style="margin:0 0 8px 0;">{body}</p>')
        buf.clear()

    paragraph: list[str] = []
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 代码块（三反引号）：内部原样转义，不解析 markdown
        if stripped.startswith("```"):
            _flush_paragraph(paragraph)
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # 跳过结束 fence（没有结束符也到这里）
            parts.append(
                f'<pre style="background:{_CODE_BG}; padding:8px 10px; margin:0 0 10px 0; '
                f'font-family:Consolas,Monaco,monospace; white-space:pre-wrap;">'
                f'<code>{chr(10).join(code)}</code></pre>'   # 每行已整体转义
            )
            continue

        # 空行：段落分隔
        if not stripped:
            _flush_paragraph(paragraph)
            i += 1
            continue

        # 水平线
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            _flush_paragraph(paragraph)
            parts.append(f'<hr style="border:none; border-top:1px solid {link_color}; '
                         f'opacity:0.35; margin:10px 0;">')
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            _flush_paragraph(paragraph)
            level = len(m.group(1))
            size = {1: 15, 2: 13.5, 3: 12.5}.get(level, 11)
            parts.append(
                f'<p style="margin:10px 0 6px 0; font-size:{size}pt; font-weight:600; '
                f'color:{link_color};">{_inline(m.group(2), link_color=link_color)}</p>'
            )
            i += 1
            continue

        # 表格：当前行含 | 且下一行是分隔行（|---|:---:|）→ 整段表格
        # 注意必须在水平线判断之后：单独的 --- 仍是 hr，不是表格分隔。
        if "|" in line and i + 1 < len(lines) and re.fullmatch(
            r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", lines[i + 1]
        ):
            _flush_paragraph(paragraph)

            def _cells(row: str) -> list[str]:
                s = row.strip()
                if s.startswith("|"):
                    s = s[1:]
                if s.endswith("|"):
                    s = s[:-1]
                return [c.strip() for c in s.split("|")]

            header = _cells(line)
            i += 2   # 跳过表头 + 分隔行
            body: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                body.append(_cells(lines[i]))
                i += 1
            th = "".join(
                f'<th style="border:1px solid rgba(127,127,127,0.3); padding:5px 9px; '
                f'text-align:left; background:{_CODE_BG}; font-weight:600;">'
                f'{_inline(c, link_color=link_color)}</th>' for c in header
            )
            trs = "".join(
                "<tr>" + "".join(
                    f'<td style="border:1px solid rgba(127,127,127,0.3); padding:5px 9px;">'
                    f'{_inline(c, link_color=link_color)}</td>' for c in row
                ) + "</tr>"
                for row in body
            )
            parts.append(
                f'<table cellspacing="0" cellpadding="0" '
                f'style="border-collapse:collapse; margin:0 0 10px 0; font-size:10.5pt;">'
                f'<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'
            )
            continue

        # 列表（连续同类型行合成一个 ul/ol）
        lm = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", line)
        if lm:
            _flush_paragraph(paragraph)
            ordered = bool(re.match(r"^\s*\d+", line))
            items: list[str] = []
            while i < len(lines):
                im = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if not im or bool(re.match(r"^\s*\d+", lines[i])) != ordered:
                    break
                items.append(f"<li>{_inline(im.group(2), link_color=link_color)}</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            parts.append(
                f'<{tag} style="margin:0 0 10px 0; padding-left:22px;">'
                + "".join(items) + f"</{tag}>"
            )
            continue

        paragraph.append(stripped)
        i += 1

    _flush_paragraph(paragraph)
    return "".join(parts)
