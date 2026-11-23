"""构建 YoAi.exe（单文件桌面应用）。

用法（Core venv 已装 PyInstaller 6.22.3）：
    "$CORE_PY" build_exe.py   # CORE_PY = Core venv 里的 Python 解释器

产物：dist/YoAi.exe —— 双击即可运行，无需 Python、无需 Core venv。
个人状态保存在 exe 同目录的 output/，跨启动持久。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYINSTALLER = Path(sys.executable).parent / "PyInstaller.exe"


def main() -> int:
    # 清理旧产物，避免拿缓存冒充新构建
    for name in ("build", "dist"):
        target = ROOT / name
        if target.exists():
            shutil.rmtree(target)

    cmd = [
        str(PYINSTALLER) if PYINSTALLER.exists() else sys.executable,
    ]
    if not PYINSTALLER.exists():
        cmd += ["-m", "PyInstaller"]
    cmd += ["--noconfirm", "--clean", "yoai.spec"]

    print("构建命令：", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        print(f"构建失败，退出码 {result.returncode}")
        return result.returncode

    exe = ROOT / "dist" / "YoAi.exe"
    if not exe.exists():
        print("构建声称成功，但未找到 dist/YoAi.exe")
        return 1
    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"构建完成：{exe}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
