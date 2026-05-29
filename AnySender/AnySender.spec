# -*- mode: python ; coding: utf-8 -*-
"""
AnySender PyInstaller spec — 自动扫描插件，处理动态 import
用法：pyinstaller AnySender.spec
"""
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(SPECPATH).resolve()  # SPECPATH 是 PyInstaller 内置变量，指向 spec 所在目录

# ── 自动扫描所有插件的 Python 模块 ──────────────────
def collect_plugin_hidden_imports():
    imports = []
    for src_dir in ("plugins", "custom_plugins"):
        base = PROJECT_DIR / src_dir
        if not base.is_dir():
            continue
        for py_file in base.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            rel = py_file.relative_to(PROJECT_DIR).with_suffix("")
            mod = str(rel).replace(os.sep, ".")
            imports.append(mod)
    return imports

hidden_imports = collect_plugin_hidden_imports()

# ── 自动收集数据目录 ────────────────────────────────
def collect_data_dirs():
    dirs = []
    for d in ("config", "presets", "schemas"):
        path = PROJECT_DIR / d
        if path.is_dir():
            dirs.append((str(path), d))
    for d in ("screenshots", "logs"):
        path = PROJECT_DIR / d
        if path.is_dir():
            dirs.append((str(path), d))
    return dirs

datas = collect_data_dirs()

# ── PyInstaller Analysis ─────────────────────────────
a = Analysis(
    [str(PROJECT_DIR / "main.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AnySender",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # 显示控制台窗口，方便看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
