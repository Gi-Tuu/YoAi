"""把桌面 runtime 源码同步到所有副本（改了 apps/desktop-tauri/runtime 之后运行）。

为什么需要：runtime 有 5 份（源码 + Tauri resources + target 两份 + dist），
tests/test_runtime_copies.py 要求它们完全一致；dist 那份是 YoAi.exe 实际运行的代码。

做三件事：
1. 先编译检查源码，语法错误直接中止，不会把坏文件复制出去；
2. yoai_runtime.py 的行尾统一成 CRLF（仓库原有约定）；
3. 复制到所有**已存在的**副本目录，打印 sha256 供核对。

用法（在 YoAi 根目录）：
    python tools/sync_runtime_copies.py           # 同步
    python tools/sync_runtime_copies.py --check   # 只检查，不写
"""

from __future__ import annotations

import hashlib
import shutil
import sys
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
CRLF_FILES = ("yoai_runtime.py",)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    drift = 0
    for name in FILES:
        src = SOURCE / name
        data = src.read_bytes()
        try:
            compile(data.decode("utf-8"), str(src), "exec")
        except SyntaxError as exc:
            print(f"✗ {name} 有语法错误，已中止：{exc}")
            return 2
        if name in CRLF_FILES and b"\n" in data.replace(b"\r\n", b""):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if not check_only:
                src.write_bytes(data)
                print(f"· {name} 行尾已统一为 CRLF")
        expected = digest(data)
        print(f"{name}: 源码 {expected}")
        for target in TARGETS:
            dst = target / name
            if not dst.exists():
                continue
            current = digest(dst.read_bytes())
            if current == expected:
                print(f"  ✓ {dst.relative_to(ROOT)}")
                continue
            drift += 1
            if check_only:
                print(f"  ✗ {dst.relative_to(ROOT)}（{current}，与源码不一致）")
            else:
                shutil.copyfile(src, dst)
                print(f"  → 已同步 {dst.relative_to(ROOT)}")
    if check_only and drift:
        print(f"\n有 {drift} 个副本与源码不一致，运行不带 --check 的命令同步。")
        return 1
    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
