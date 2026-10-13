#!/usr/bin/env bash
# Build the desktop executable (POSIX equivalent of build_exe.bat).
#
# Produces dist/SpotDL -- a native window, no console.
#
# IMPORTANT -- build launcher.py, never app.py.
#   `pyinstaller app.py --onefile --windowed` executes app.py as a plain
#   script: it logs "missing ScriptRunContext! running in bare mode" and exits
#   without ever starting a Streamlit server, so there is no UI.
set -euo pipefail

echo "=== Build prerequisites ========================================="
command -v python >/dev/null || { echo "[FAIL] python not on PATH"; exit 1; }
python --version

# --- BOM check ---------------------------------------------------------------
# streamlit-desktop-app runs ast.parse() over the target, and a UTF-8 BOM makes
# it fail with "invalid non-printable character U+FEFF". That is invisible under
# a plain `import app`, so catch it before spending ten minutes on a build that
# cannot succeed.
if python -c "import sys,pathlib; sys.exit(1 if pathlib.Path('app.py').read_bytes()[:3]==bytes([0xef,0xbb,0xbf]) else 0)"; then
    echo "  app.py    : no BOM, OK"
else
    echo "[FAIL] app.py still has a UTF-8 BOM (EF BB BF) - the build will fail."
    exit 1
fi

# --- ffmpeg ------------------------------------------------------------------
# Not fatal: the binary still builds, but downloads fail on any machine without
# ffmpeg on PATH.
if [ -x bin/ffmpeg.exe ] || [ -x bin/ffmpeg ]; then
    echo "  ffmpeg    : bundled in bin/ ($(du -h bin/ffmpeg* | cut -f1))"
else
    echo "[WARN] bin/ffmpeg not found."
    echo "        The binary still builds, but downloads fail without ffmpeg."
    echo "        Get one with:"
    echo "          python -m pip install imageio-ffmpeg"
    echo "          python -c \"import imageio_ffmpeg,shutil; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),'bin/ffmpeg')\""
fi

echo
echo "=== Installing build dependency =================================="
python -m pip install -q streamlit-desktop-app

echo
echo "=== Building ======================================================"
# --onefile   : single binary, no side-car folder
# --noconfirm : overwrite a previous build without prompting
# --add-data  : carry bin/ffmpeg into the bundle. PyInstaller does NOT pick up a
#               binary that merely sits on disk -- without this the executable
#               builds fine and then fails at download time on any machine that
#               has no ffmpeg on PATH.
if [ -f bin/ffmpeg.exe ]; then
    echo "  bundling  : bin/ffmpeg.exe"
    # PyInstaller wants ';' as the source:destination separator on Windows.
    SEP=';'
    [ "$(uname)" = "Darwin" ] && SEP=':'
    streamlit-desktop-app build launcher.py \
        --name SpotDL \
        --pyinstaller-options --onefile --noconfirm \
        --add-data "bin/ffmpeg.exe${SEP}bin"
else
    echo "  bundling  : (skipped, bin/ffmpeg.exe missing)"
    streamlit-desktop-app build launcher.py \
        --name SpotDL \
        --pyinstaller-options --onefile --noconfirm
fi

echo
echo "=== Result ========================================================"
[ -f dist/SpotDL ] || { echo "[FAIL] dist/SpotDL was not produced"; exit 1; }
ls -lh dist/SpotDL
echo
echo "Run dist/SpotDL to open the application window."
