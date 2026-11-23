"""pytest 全局配置：发现并注入 YAI Agent Core 源码路径。

Core 是只读上游，不随本仓库分发。两种提供方式（任选其一）：

1. 设环境变量 ``YAI_CORE_SRC=<Core 根目录>``（该目录下应有 ``src/yai_core``）；
2. 把 Core 放在本仓库的兄弟目录或同盘上级目录中，由本文件自动发现。

这样公开代码里不出现任何开发机的绝对路径，测试仍能在本机跑通。
找不到时给出明确报错，而不是让 import 失败得莫名其妙。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_YOAI_ROOT = _HERE.parent


def _find_core_src() -> Path | None:
    env = os.environ.get("YAI_CORE_SRC")
    if env:
        candidate = Path(env).expanduser()
        for path in (candidate / "src", candidate):
            if (path / "yai_core").is_dir():
                return path

    # PYTHONPATH 已注入 Core/src 时直接复用（本机现有运行方式无需改）
    for entry in sys.path:
        if not entry:
            continue
        try:
            path = Path(entry)
            if (path / "yai_core").is_dir():
                return path
        except OSError:
            continue

    seen: set[Path] = set()
    # 向上两层 + 各层的直接子目录与孙目录，覆盖兄弟 / 堂兄弟布局
    bases = [_YOAI_ROOT, _YOAI_ROOT.parent, _YOAI_ROOT.parent.parent]
    for base in list(bases):
        try:
            bases.extend(p for p in base.iterdir() if p.is_dir())
        except OSError:
            continue
    for base in bases:
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child in seen:
                continue
            seen.add(child)
            name = child.name.lower()
            if "yai" not in name or "core" not in name:
                continue
            for path in (child / "src", child):
                if (path / "yai_core").is_dir():
                    return path
    return None


_CORE_SRC = _find_core_src()
if _CORE_SRC is None:
    raise RuntimeError(
        "找不到 YAI Agent Core 源码。请设置环境变量 "
        "YAI_CORE_SRC=<Core 根目录>（其下应有 src/yai_core），"
        "或把 Core 放到本仓库的兄弟目录 / 上级目录中。"
    )

sys.path.insert(0, str(_CORE_SRC))
