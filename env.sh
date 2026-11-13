# Project-local environment for Riyaz. Load it in a shell with:  . ./env.sh
# The Makefile sets the same values. Nothing here changes your shell profile.
# All downloads (Python, packages, PyInstaller cache) stay inside this folder.

RIYAZ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export UV_CACHE_DIR="$RIYAZ_ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$RIYAZ_ROOT/.cache/python"
export UV_PYTHON_PREFERENCE=only-managed
export UV_PYTHON_DOWNLOADS=manual
export PYINSTALLER_CONFIG_DIR="$RIYAZ_ROOT/.cache/pyinstaller"
