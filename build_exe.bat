@echo off
REM ===========================================================================
REM Build the Windows desktop executable.
REM
REM Produces dist\SpotDL.exe (a native window, no console).
REM
REM IMPORTANT -- build launcher.py, never app.py.
REM   `pyinstaller app.py --onefile --windowed` executes app.py as a plain
REM   script: it logs "missing ScriptRunContext! running in bare mode" and exits
REM   without ever starting a Streamlit server, so there is no UI. The desktop
REM   launcher is what starts the server and opens the window.
REM
REM   streamlit-desktop-app build launcher.py --pyinstaller-options --onefile
REM ===========================================================================
setlocal enabledelayedexpansion

echo === Build prerequisites =========================================
where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] 'python' tidak ada di PATH.
    echo        Aktifkan venv dulu atau set PATH ke Python.
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   python    : !PYVER!

REM --- BOM check -------------------------------------------------------------
REM streamlit-desktop-app calls ast.parse() on the target, and a UTF-8 BOM
REM makes it fail with "invalid non-printable character U+FEFF". This is
REM invisible under a normal `import app`, so check it before spending 10
REM minutes on a build that cannot succeed.
python -c "import sys,pathlib; sys.exit(1 if pathlib.Path('app.py').read_bytes()[:3]==bytes([0xef,0xbb,0xbf]) else 0)"
if errorlevel 1 (
    echo [FAIL] app.py masih punya BOM UTF-8 ^(EF BB BF^) - build akan gagal.
    echo        Buang 3 byte pertama file itu, lalu ulangi.
    exit /b 1
)
echo   app.py    : tanpa BOM, OK

REM --- ffmpeg ---------------------------------------------------------------
REM Not fatal: without it the .exe still builds, but downloads fail on a
REM machine that has no ffmpeg on PATH. Warn loudly rather than silently
REM shipping a broken binary.
if exist "bin\ffmpeg.exe" (
    for %%f in ("bin\ffmpeg.exe") do echo   ffmpeg    : bin\ffmpeg.exe ^(%%~zf bytes^)
) else (
    echo [WARN] bin\ffmpeg.exe tidak ada.
    echo        .exe tetap bisa dibuat, tapi download gagal di PC tanpa ffmpeg.
    echo        Ambil dengan:
    echo          python -m pip install imageio-ffmpeg
    echo          python -c "import imageio_ffmpeg,shutil; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),'bin/ffmpeg.exe')"
)

echo.
echo === Installing build dependency ==================================
python -m pip install -q streamlit-desktop-app
if errorlevel 1 (
    echo [FAIL] pip install streamlit-desktop-app gagal.
    exit /b 1
)

echo.
echo === Building ======================================================
REM --onefile : single .exe, no folder of side-car files.
REM --noconfirm: overwrite a previous build without prompting.
REM --add-data: carry bin\ffmpeg.exe into the bundle. PyInstaller does NOT pick
REM   up a binary that is merely present on disk -- without this the .exe builds
REM   fine and then fails at download time on any machine without ffmpeg on PATH.
set /a ADDFFMPEG=0
if exist "bin\ffmpeg.exe" (
    echo   bundling  : bin\ffmpeg.exe
    set /a ADDFFMPEG=1
) else (
    echo   bundling  : (skip, bin\ffmpeg.exe missing)
)

if "%ADDFFMPEG%"=="1" (
    streamlit-desktop-app build launcher.py --name SpotDL --pyinstaller-options --onefile --noconfirm --add-data "bin\ffmpeg.exe;bin"
) else (
    streamlit-desktop-app build launcher.py --name SpotDL --pyinstaller-options --onefile --noconfirm
)
if errorlevel 1 (
    echo [FAIL] build gagal. Scroll ke atas untuk pesan PyInstaller.
    exit /b 1
)

echo.
echo === Result ========================================================
if not exist "dist\SpotDL.exe" (
    echo [FAIL] dist\SpotDL.exe tidak terbentuk.
    exit /b 1
)
for %%f in ("dist\SpotDL.exe") do echo   dist\SpotDL.exe = %%~zf bytes ^(~!f! MB^)
echo.
echo Jalankan dist\SpotDL.exe untuk membuka jendela aplikasi.
endlocal
