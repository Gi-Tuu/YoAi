"""守护 runtime 副本一致性：避免改了源码却跑到旧脚本。

只检查存在的副本（target/dist 在干净仓库可能不存在）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps" / "desktop-tauri" / "runtime"
TARGETS = (
    ROOT / "apps" / "desktop-tauri" / "src-tauri" / "resources" / "runtime",
    ROOT / "apps" / "desktop-tauri" / "src-tauri" / "target" / "release" / "resources" / "runtime",
    ROOT / "apps" / "desktop-tauri" / "src-tauri" / "target" / "release" / "runtime",
    ROOT / "dist" / "runtime",
)
FILES = ("protocol.py", "yoai_runtime.py", "yai_core_sidecar_channel.py")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runtime_copies_match_source():
    for name in FILES:
        expected = _digest(SOURCE / name)
        for target in TARGETS:
            candidate = target / name
            if candidate.exists():
                assert _digest(candidate) == expected, (
                    f"runtime 副本漂移：{candidate} != {SOURCE / name}")
