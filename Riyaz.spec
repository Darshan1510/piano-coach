# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Riyaz. The Makefile calls this file (one place for the build flags).
# Same as these flags:
#   --onedir --windowed --add-data static:static
#   --collect-all uvicorn fastapi starlette webview websockets mido rtmidi
#   --hidden-import mido.backends.rtmidi --copy-metadata mido
import os
import sys

# Keep the PyInstaller cache inside the project, also for a direct `uv run pyinstaller Riyaz.spec`
# (the Makefile and env.sh export the same value). PyInstaller reads this variable before it runs
# this file, so also set CONF["cachedir"], the value it computed from it.
if not os.environ.get("PYINSTALLER_CONFIG_DIR"):
    os.environ["PYINSTALLER_CONFIG_DIR"] = os.path.join(SPECPATH, ".cache", "pyinstaller")
    from PyInstaller.config import CONF

    CONF["cachedir"] = os.path.join(os.environ["PYINSTALLER_CONFIG_DIR"], "pyinstaller")

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = [("static", "static")]
binaries = []
hiddenimports = ["mido.backends.rtmidi"]

for pkg in ("uvicorn", "fastapi", "starlette", "webview", "websockets", "mido", "rtmidi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += copy_metadata("mido")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Riyaz",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name="Riyaz")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Riyaz.app",
        icon=None,  # no icon yet (see IDEAS.md)
        bundle_identifier="local.riyaz.app",
        info_plist={"NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.music"},
    )
