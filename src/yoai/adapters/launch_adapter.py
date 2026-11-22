"""L1 Launch-only 适配器 — 只能拉起 GUI 应用，不能自动拿回答。

诚实原则：这类 IDE / 桌面助手（Qoder、Trae、MiniMax Code、ZCode、WorkBuddy、
ChatGPT Desktop 等）本机没有消息级 API，只有 URL 协议或可执行文件路径。
适配器做两件真实的事：
  1) 把消息写到约定的"投递文件"（用户可在应用里粘贴/打开）；
  2) 通过协议/命令拉起应用窗口。
返回 ok=False + level=L1 + detail 明确"需人工转发"，绝不冒充自动回复。
"""

from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path
from typing import Any

from yoai.adapters.base import AdapterResult, PeerAdapter


class LaunchOnlyAdapter(PeerAdapter):
    """通过 URL 协议或可执行文件拉起应用 + 写投递文件。"""

    level = "L1"

    def __init__(
        self,
        name: str,
        *,
        url_scheme: str = "",
        executable: str = "",
        drop_dir: str | Path | None = None,
        enabled: bool = True,
        open_app: bool = False,   # 默认不自动弹窗，避免测试时乱跳窗口
    ) -> None:
        super().__init__(name, enabled=enabled, timeout_s=10.0)
        self.url_scheme = url_scheme
        self.executable = executable
        self.drop_dir = Path(drop_dir) if drop_dir else None
        self.open_app = open_app
        self.last_drop: Path | None = None

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self.executable:
            return Path(self.executable).exists()
        if self.url_scheme:
            return bool(self.url_scheme.strip())
        return False

    def capabilities(self) -> list[str]:
        return ["launch", "delivery_file", "manual_relay"]

    def send(self, message: str) -> AdapterResult:
        if not self.available():
            return AdapterResult(False, level=self.level, detail="应用未安装或已禁用")

        # 1) 写投递文件（真实副作用）
        detail_parts: list[str] = []
        if self.drop_dir:
            self.drop_dir.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.name)[:30]
            import uuid
            path = self.drop_dir / f"{safe}-{uuid.uuid4().hex[:6]}.md"
            path.write_text(f"# YoAi 投递给 {self.name}\n\n{message}\n", encoding="utf-8")
            self.last_drop = path
            detail_parts.append(f"投递文件：{path}")

        # 2) 拉起应用（可选，默认关）
        if self.open_app:
            try:
                if self.url_scheme:
                    webbrowser.open(self.url_scheme)
                    detail_parts.append(f"已拉起协议：{self.url_scheme}")
                elif self.executable:
                    subprocess.Popen([self.executable], shell=False)
                    detail_parts.append("已拉起应用")
            except (OSError, ValueError) as exc:
                detail_parts.append(f"拉起失败：{type(exc).__name__}: {exc}")

        detail_parts.append("需人工把消息转发进该应用，并把回答贴回 YoAi（本机无消息级 API）")
        return AdapterResult(
            False, level=self.level,
            detail="；".join(detail_parts),
            meta={"drop_file": str(self.last_drop) if self.last_drop else ""},
        )
