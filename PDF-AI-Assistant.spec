# -*- mode: python ; coding: utf-8 -*-
# Build this on Windows to produce dist/PDF-AI-Assistant.exe.
# A Windows executable cannot be produced from macOS or Linux.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [("assets", "assets")]
datas += collect_data_files("fastembed")
binaries = collect_dynamic_libs("onnxruntime")
hiddenimports = (
    collect_submodules("fastembed")
    + collect_submodules("onnxruntime")
    + [
        "keyring.backends.Windows",
        "keyring.backends.macOS",
        "pymupdf",
        "fitz",
    ]
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PDF-AI-Assistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
