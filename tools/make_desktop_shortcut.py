"""生成 YoAi 宇宙星球图标（.ico）并在桌面创建快捷方式。

- 图标：复用 cosmic.planet.draw_planet 画青色带环恒星，128x128 ico。
- 快捷方式：pywin32 IShellLink，指向 dist/YoAi.exe，工作目录=dist，描述=宇宙星球系个人智能体。
- 安全：不覆盖已存在的同名 .lnk（除非 --force）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from yoai.desktop.cosmic.planet import draw_planet  # noqa: E402
from yoai.desktop.cosmic.theme import Palette  # noqa: E402


def build_ico(output: Path) -> None:
    QApplication.instance() or QApplication([])
    size = 128
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_planet(p, size / 2, size / 2, size * 0.26,
                Palette.dark().vermilion, ring=True, glow=0.9, spin=0.5,
                paper=True, kind="sun")   # 暖橙太阳 + 朱红细环，与新 UI 一致
    p.end()
    if not img.save(str(output), "ICO"):
        raise RuntimeError("图标生成失败")


def create_shortcut(lnk: Path, exe: Path, ico: Path, *, force: bool = False) -> str:
    if lnk.exists() and not force:
        return f"已存在，未覆盖：{lnk}"
    import pythoncom
    from win32com.shell import shell
    pythoncom.CoInitialize()
    try:
        link = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink, None,
            pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
        )
        link.SetPath(str(exe))
        link.SetWorkingDirectory(str(exe.parent))
        link.SetDescription("YoAi · 宇宙星球系个人智能体")
        link.SetIconLocation(str(ico), 0)
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(lnk), 0)
    finally:
        pythoncom.CoUninitialize()
    return f"已创建：{lnk}"


def main() -> int:
    import os
    exe = ROOT / "dist" / "YoAi.exe"
    ico = ROOT / "dist" / "yoai-planet.ico"
    desktop = Path(os.environ.get("USERPROFILE", r"C:\Users\sheng")) / "Desktop"
    force = "--force" in sys.argv
    if not exe.exists():
        print(f"EXE 不存在：{exe}")
        return 1
    build_ico(ico)
    print(f"图标：{ico}")
    print(create_shortcut(desktop / "YoAi.lnk", exe, ico, force=force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
