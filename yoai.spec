# -*- mode: python ; coding: utf-8 -*-
"""YoAi 桌面 APP 的 PyInstaller spec。

产出单文件 YoAi.exe。把 yoai 与 yai_core 两个源码树都纳入 pathex，
PySide6 由 PyInstaller 官方 hook 自动收集平台插件。
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 - PyInstaller 注入


def _find_core_src() -> Path:
    """定位 Core 源码：YAI_CORE_SRC 优先，其次从 sys.path 反推，再按相邻目录探测。"""
    env = os.environ.get("YAI_CORE_SRC")
    if env:
        candidate = Path(env).expanduser() / "src"
        if (candidate / "yai_core").is_dir():
            return candidate
    for entry in sys.path:
        if entry:
            try:
                path = Path(entry)
                if (path / "yai_core").is_dir():
                    return path
            except OSError:
                continue
    for parent in ROOT.parents:
        for name in ("YAI Agent Core", "yai-agent-core", "yai_agent_core"):
            candidate = parent / name / "src"
            if (candidate / "yai_core").is_dir():
                return candidate
    raise RuntimeError("找不到 YAI Agent Core 源码，请设置环境变量 YAI_CORE_SRC=<Core 根目录>")


CORE_SRC = _find_core_src()
YOAI_SRC = ROOT / "src"

block_cipher = None

a = Analysis(
    [str(ROOT / "src" / "yoai" / "desktop" / "app.py")],
    pathex=[str(YOAI_SRC), str(CORE_SRC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "yai_core",
        "yai_core.core",
        "yai_core.types",
        "yai_core.discovery",
        "yai_core.discovery.introspect",
        "yoai.agent",
        "yoai.capabilities",
        "yoai.context",
        "yoai.goals",
        "yoai.demo_model",
        "yoai.demo_world",
        "yoai.desktop",
        "yoai.desktop.worker",
        "yoai.desktop.chat_worker",
        "yoai.desktop.chat_panel",
        "yoai.desktop.main_window",
        "yoai.chat",
        "yoai.chat.models",
        "yoai.chat.store",
        "yoai.chat.peer",
        "yoai.chat.channel",
        "yoai.adapters",
        "yoai.adapters.base",
        "yoai.adapters.cli_adapter",
        "yoai.adapters.launch_adapter",
        "yoai.adapters.external_peer",
        "yoai.adapters.zen_adapter",
        "yoai.adapters.registry",
        "yoai.models",
        "yoai.models.http_base",
        "yoai.models.deepseek_adapter",
        "yoai.models.suanli_adapter",
        "yoai.models.gateway_provider",
        "yoai.models.expert_provider",
        "yoai.evolution",
        "yoai.evolution.models",
        "yoai.evolution.archive",
        "yoai.evolution.fingerprint",
        "yoai.evolution.router",
        "yoai.evolution.candidate",
        "yoai.evolution.promotion",
        "yoai.evolution.engine",
        "yoai.session",
        "yoai.evidence",
        "yoai.evidence.models",
        "yoai.evidence.collector",
        "yoai.evidence.store",
        "yoai.evidence.attribution",
        "yoai.evidence.benchmark_lab",
        "yoai.verification",
        "yoai.verification.verifiers",
        "yoai.verification.context_assertion",
        "yoai.desktop.cosmic",
        "yoai.desktop.cosmic.theme",
        "yoai.desktop.cosmic.texture",
        "yoai.desktop.cosmic.starfield",
        "yoai.desktop.cosmic.planet",
        "yoai.desktop.cosmic.planet_scrollbar",
        "yoai.desktop.cosmic.dark_orb",
        "yoai.desktop.cosmic.galaxy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="YoAi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 应用：双击不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
