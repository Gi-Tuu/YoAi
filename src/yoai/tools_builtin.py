"""YoAi 内置实操工具：文件读写 + 联网（2026-11-24）。

设计原则：
- **用 Core 现成电池**（filesystem_capabilities / filesystem_gate / build_spec），
  不重复造轮子；全部通过 Core 公开 API 注册，内核零改动、升级天然兼容。
- **安全边界由宿主声明**：根目录 项目内 workspace/ 目录，读全根目录、
  写只在 workspace/ 子目录内；符号链接不跟随、大小上限用 Core 保守默认值。
- 联网工具无 key：web_search 用公开的 freeserp.ai，web_fetch 用标准库、
  限 https + 长度 + 超时；失败如实返回错误文本（不静默）。

返回的是 ToolSpec 列表，由 YoAiAgent 构造时注册进 registry。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any

from yai_core import build_spec
from yai_core.batteries.filesystem import filesystem_capabilities, filesystem_gate
from yai_core.governance import ToolGovernance

DEFAULT_WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"

# 写工具的作用域：相对根目录的前缀。空串=整个根目录，这里明确限定子目录。
WRITE_PREFIXES: tuple[str, ...] = ()


def web_search(q: str, size: int = 5) -> str:
    """搜索公开网页（Global 索引），返回标题/链接/摘要的 JSON。无需 API Key。

    q 是查询词；size 是结果条数（1-20）。适合查资料、找链接、核实事实。
    """
    size = max(1, min(20, int(size)))
    url = "https://freeserp.ai/api.php?" + urllib.parse.urlencode(
        {"index": "web", "q": q, "size": size}
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - 联网失败必须如实返回，不能静默
        return json.dumps({"error": f"搜索失败：{type(exc).__name__}: {exc}"},
                          ensure_ascii=False)
    results = data.get("results") or data.get("data") or []
    # 只保留小字段，避免把一大坨元数据塞进模型上下文
    slim = []
    for item in results[:size]:
        if isinstance(item, dict):
            slim.append({k: item.get(k) for k in ("title", "url", "snippet", "description")
                         if item.get(k)})
    return json.dumps({"ok": bool(data.get("ok", True)), "count": len(slim),
                       "results": slim}, ensure_ascii=False)


def web_fetch(url: str, max_chars: int = 12000) -> str:
    """抓取一个网页的正文（纯文本），用于阅读具体页面。仅支持 https。

    url 必须是完整的 https 地址；max_chars 限制返回长度（上限 30000）。
    """
    if not url.lower().startswith("https://"):
        return "仅支持 https 地址（防止访问本地/内网资源）"
    max_chars = max(500, min(30000, int(max_chars)))
    req = urllib.request.Request(url, headers={"User-Agent": "YoAi/1.0 (web_fetch)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(300_000).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"抓取失败：{type(exc).__name__}: {exc}"
    # 极简 HTML 去标签（够用；不引入 bs4 依赖）
    import re
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def builtin_tool_specs(root: str | Path | None = None) -> list[Any]:
    """构建文件+联网工具 specs。root 是文件根目录，缺省 DEFAULT_WORKSPACE。"""
    root = Path(root or DEFAULT_WORKSPACE).resolve()
    root.mkdir(parents=True, exist_ok=True)

    specs: list[Any] = []

    # 文件工具：Core 电池 + 写作用域闸。
    # 用户选择"读全根目录、写限白名单子目录"——白名单子目录即根目录下各一级子目录，
    # 用 filesystem_gate 的前缀机制表达：写前缀取根目录下已存在/允许的子目录名。
    # 默认给 "workspace/" 这一层（与根同名是为了兼容把 root 设成项目根的用法）。
    write_prefixes = WRITE_PREFIXES or tuple(
        p.name + "/" for p in root.iterdir() if p.is_dir()
    )
    # 若根目录还没有子目录，给一个明确的默认写区，避免"白名单为空=拒绝一切写"。
    if not write_prefixes:
        (root / "notes").mkdir(exist_ok=True)
        write_prefixes = ("notes/",)

    # 读操作不挂 gate：file_read/list 受 filesystem 自身的 root + 符号链接防护约束，
    # Core 的 filesystem_gate 禁止空串前缀（会把"整个根目录"变成歧义），
    # 用户选的是"读全根目录"，所以读工具零额外 gate。
    write_gate = filesystem_gate(prefixes=write_prefixes, write=True)

    for fn in filesystem_capabilities(root):
        spec = build_spec(fn)
        if fn.__name__ in ("file_create", "file_patch"):
            spec = replace(spec, governance=ToolGovernance(gate=write_gate))
        specs.append(spec)

    # 联网工具：两个纯函数，用 build_spec 自动出 schema。
    specs.append(build_spec(web_search))
    specs.append(build_spec(web_fetch))
    # 基础能力（2026-11-24）：受限终端 + 系统浏览器。
    # shell_run 不进 auto 白名单（每次弹窗确认）；open_url 只读打开 http/https。
    from yoai.tools_shell import browser_tool_specs, shell_tool_specs
    specs.extend(shell_tool_specs(root))
    specs.extend(browser_tool_specs())
    return specs


def readonly_tool_specs(roots: list[str | Path]) -> list[Any]:
    """只读挂载扩展目录（2026-11-24，YoAi 自检反馈）。

    场景：AI 调试宿主项目时需要读项目源码，而 file_* 工具
    的根是 workspace/，Core 电池按设计拒绝盘符绝对路径（PathEscapeError）。
    这里在 **YoAi 侧**提供第二个只读入口：file_ro_read / file_ro_list，
    路径 resolve 后必须落在白名单根内（跟随符号链接也会被 resolve 排除），
    写类操作不存在（没有 create/patch），不改 Core 内核、升级兼容。

    roots 为空或全部不存在时不挂载，返回空列表（行为与旧版一致）。
    """
    allowed = [Path(r).expanduser().resolve() for r in roots or []]
    allowed = [r for r in allowed if r.is_dir()]
    if not allowed:
        return []

    def _resolve_in_roots(path: str) -> Path:
        raw = Path(str(path)).expanduser()
        if not raw.is_absolute():
            # 相对路径按白名单根逐个尝试（模型通常以根内相对路径表述）
            for root in allowed:
                candidate = (root / raw).resolve()
                if candidate.exists() and (candidate == root or candidate.is_relative_to(root)):
                    return candidate
        p = raw.resolve()
        for root in allowed:
            if p == root or p.is_relative_to(root):
                return p
        raise PermissionError(
            f"路径不在只读白名单内（允许的根：{', '.join(str(r) for r in allowed)}）：{path}"
        )

    def file_ro_list(path: str = "") -> str:
        """列出只读挂载目录下的一级内容（子目录名/ 与文件名）。
        path 为空时列各白名单根的顶层。只读，不能写。"""
        import json as _json
        if not str(path).strip():
            listing = {}
            for root in allowed:
                listing[str(root)] = sorted(
                    (c.name + ("/" if c.is_dir() else "")) for c in root.iterdir()
                )
            return _json.dumps(listing, ensure_ascii=False)
        p = _resolve_in_roots(path)
        if not p.is_dir():
            return f"不是目录：{path}"
        return _json.dumps(
            sorted((c.name + ("/" if c.is_dir() else "")) for c in p.iterdir()),
            ensure_ascii=False,
        )

    def file_ro_read(path: str, max_chars: int = 20000) -> str:
        """读取只读挂载目录内一个文本文件的内容（源码/文档/配置）。
        max_chars 限制返回长度（上限 50000）；二进制文件会如实报错。只读，不能写。"""
        max_chars = max(500, min(50000, int(max_chars)))
        p = _resolve_in_roots(path)
        if not p.is_file():
            return f"不是文件：{path}"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"读取失败：{type(exc).__name__}: {exc}"
        return text[:max_chars]

    return [build_spec(file_ro_list), build_spec(file_ro_read)]
