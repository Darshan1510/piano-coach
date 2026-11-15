# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Riyaz. The Makefile calls this file (one place for the build flags).
# Same as these flags:
#   --onedir --windowed --add-data static:static --add-data data/songs:data/songs --add-data data/course:data/course
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

datas = [("static", "static"), ("data/songs", "data/songs"), ("data/course", "data/course")]
binaries = []
hiddenimports = ["mido.backends.rtmidi"]

for pkg in ("uvicorn", "fastapi", "starlette", "webview", "websockets", "mido", "rtmidi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += copy_metadata("mido")

# Audio import (Phase 5a, DECISIONS.md): the light audio stack (basic-pitch with its CoreML model,
# librosa, numpy, scipy ...) is bundled when RIYAZ_AUDIO is not "0" and the packages are in .venv.
# The worker runs as "Riyaz --audio-worker" (main.py). RIYAZ_AUDIO=0 builds the base app only.
import importlib.util

AUDIO = os.environ.get("RIYAZ_AUDIO", "1") != "0" and importlib.util.find_spec("basic_pitch") is not None
hiddenimports += ["riyaz.importers.audio_worker"]
if AUDIO:
    for pkg in ("basic_pitch", "librosa", "coremltools", "resampy", "soundfile", "audioread", "soxr", "pretty_midi",
                "mir_eval", "lazy_loader"):
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    for pkg in ("librosa", "basic-pitch", "numba", "llvmlite", "scipy", "numpy", "coremltools", "soundfile",
                "resampy", "pretty_midi", "mir_eval", "scikit-learn", "audioread", "soxr", "lazy_loader", "pooch"):
        try:
            datas += copy_metadata(pkg)
        except Exception:
            pass
    # Not needed by the worker: the pretty_midi sound font (6 MB).
    datas = [d for d in datas if not d[0].endswith(".sf2")]
# music21 is a dev-only test oracle (DECISIONS.md, Phase 3a): it and the packages that only it needs
# stay out. scikit-learn: only coremltools' model converter and some librosa parts use it (not the
# worker). Without the audio stack, numpy, scipy ... stay out too (other packages import them when
# they exist).
EXCLUDES = ["pytest", "tkinter", "music21", "PIL", "matplotlib", "contourpy", "kiwisolver", "fontTools", "cycler",
            "jsonpickle", "webcolors", "chardet", "charset_normalizer", "pyparsing", "IPython", "pandas", "sklearn"]
if not AUDIO:
    EXCLUDES += ["numpy", "scipy", "numba", "llvmlite", "librosa", "basic_pitch", "coremltools", "sympy", "joblib",
                 "cloudpickle", "requests", "urllib3", "dateutil", "more_itertools"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,  # see above
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
