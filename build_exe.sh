#!/usr/bin/env bash
# Build the desktop executable (POSIX equivalent of build_exe.bat).
#
# Produces dist/SpotDL -- a native window, no console.
#
# WHY THE TARGET IS app.py
# -----------------------
# streamlit-desktop-app serves EXACTLY the file you hand to `build`:
#     core.py -> args = ["streamlit", "run", script_path]
# So the target must be the actual UI page. Pointing it at a launcher/shell
# script produces a blank window: Streamlit runs that file, it calls no st.*
# function, and the page renders nothing but the "Deploy" spinner forever.
# The desktop shell itself is supplied by the package -- it generates its own
# wrapper that calls start_desktop_app() for you.
#
# WHY --add-data FOR EACH PROJECT PACKAGE
# ---------------------------------------
# The package only adds the single target file. Our providers/, ui/ and core/
# are imported by app.py at runtime, so without copying them in the frozen
# executable dies with ImportError on the first page render.
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

# --- project packages -------------------------------------------------------
for d in providers ui core; do
    [ -d "$d" ] || { echo "[FAIL] folder '$d' not found"; exit 1; }
done
echo "  packages  : providers/, ui/, core/ OK"

# PyInstaller separates source from destination with ';' on Windows, ':' elsewhere.
SEP=';'
[ "$(uname)" != "Windows_NT" ] && SEP=':'

# --- ffmpeg ------------------------------------------------------------------
# Not fatal: the binary still builds, but downloads fail on any machine without
# ffmpeg on PATH.
ADD_DATA=(--add-data "providers${SEP}providers"
          --add-data "ui${SEP}ui"
          --add-data "core${SEP}core")
if [ -f bin/ffmpeg.exe ] || [ -f bin/ffmpeg ]; then
    FF="$(ls bin/ffmpeg* 2>/dev/null | head -1)"
    echo "  ffmpeg    : $FF (will be bundled)"
    ADD_DATA+=(--add-data "${FF}${SEP}bin")
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
streamlit-desktop-app build app.py \
    --name SpotDL \
    --pyinstaller-options --onefile --noconfirm \
    "${ADD_DATA[@]}"

echo
echo "=== Verifying the bundle ========================================="
# Size alone proves nothing -- a bundle missing app.py still builds fine and then
# renders a blank window. Read the archive and confirm the real files.
python - <<'PY'
import sys
from PyInstaller.archive.readers import CArchiveReader

toc = list(CArchiveReader('dist/SpotDL.exe').toc)
bad = []
if 'app.py' not in toc:
    bad.append('app.py')
for m in ('providers', 'ui', 'core'):
    n = len([x for x in toc if x.lower().startswith(m + '\\')])
    print(f'  {m:10s}: {n} entries')
    if n == 0:
        bad.append(m)
ff = [x for x in toc if 'ffmpeg' in x.lower()]
print('  ffmpeg    :', ff or 'absent')
print('  bundle    :', 'OK' if not bad else 'MISSING ' + ', '.join(bad))
sys.exit(1 if bad else 0)
PY

echo
echo "=== Result ========================================================"
[ -f dist/SpotDL ] || { echo "[FAIL] dist/SpotDL was not produced"; exit 1; }
ls -lh dist/SpotDL
echo
echo "Run dist/SpotDL to open the application window."
