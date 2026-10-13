@echo off
REM ===========================================================================
REM Build the Windows desktop executable.
REM
REM Produces dist\SpotDL.exe -- a native window, no console.
REM
REM WHY THE TARGET IS app.py
REM -----------------------
REM streamlit-desktop-app serves EXACTLY the file you hand to `build`:
REM     core.py -> args = ["streamlit", "run", script_path]
REM So the target must be the actual UI page. Pointing it at a launcher/shell
REM script produces a blank window: Streamlit runs that file, it calls no st.*
REM function, and the page renders nothing but the "Deploy" spinner forever.
REM The desktop shell itself is supplied by the package, which generates its own
REM wrapper that calls start_desktop_app() for you.
REM
REM WHY --add-data FOR EACH PROJECT PACKAGE
REM ---------------------------------------
REM The package only adds the single target file. Our providers/, ui/ and core/
REM are imported by app.py at runtime, so without copying them in the frozen
REM executable dies with ImportError on the first page render.
REM
REM NOTE ON TOOLING
REM ---------------
REM   * We call the venv interpreter and its console script by absolute path.
REM     A bare `python` / `streamlit-desktop-app` can resolve to a different
REM     interpreter whose Scripts folder is not on PATH, which fails with
REM     "'streamlit-desktop-app' is not recognized".
REM   * `python -m streamlit_desktop_app` is NOT a substitute: that module's
REM     __main__ ignores arguments and just launches its bundled example.
REM ===========================================================================
setlocal enabledelayedexpansion

REM --- locate the venv -------------------------------------------------------
set "PY="
set "SDA="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    set "SDA=.venv\Scripts\streamlit-desktop-app.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [FAIL] Tidak menemukan python. Aktifkan venv atau set PATH.
        exit /b 1
    )
    set "PY=python"
    set "SDA=streamlit-desktop-app"
)
for /f "tokens=*" %%v in ('"%PY%" --version 2^>^&1') do set PYVER=%%v
echo   python    : !PYVER!
echo   interpreter: %PY%

REM --- BOM check -------------------------------------------------------------
REM streamlit-desktop-app runs ast.parse() over the target, and a UTF-8 BOM makes
REM it fail with "invalid non-printable character U+FEFF". That is invisible under
REM a plain `import app`, so catch it before spending ten minutes on a build that
REM cannot succeed.
"%PY%" -c "import sys,pathlib; sys.exit(1 if pathlib.Path('app.py').read_bytes()[:3]==bytes([0xef,0xbb,0xbf]) else 0)"
if errorlevel 1 (
    echo [FAIL] app.py masih punya BOM UTF-8 ^(EF BB BF^) - build akan gagal.
    echo        Buang 3 byte pertama file itu, lalu ulangi.
    exit /b 1
)
echo   app.py    : tanpa BOM, OK

REM --- project packages ------------------------------------------------------
for %%d in (providers ui core) do (
    if not exist "%%d\" (
        echo [FAIL] folder %%d tidak ditemukan.
        exit /b 1
    )
)
echo   packages  : providers\, ui\, core\ OK

REM --- ffmpeg ----------------------------------------------------------------
REM Not fatal: without it the .exe still builds, but downloads fail on any
REM machine with no ffmpeg on PATH. Note: no parentheses inside these echo lines
REM -- cmd closes an if-block on the first unbalanced ")".
set "ADDFFMPEG="
if exist "bin\ffmpeg.exe" (
    echo   ffmpeg    : bin\ffmpeg.exe akan ikut di-bundle
    set "ADDFFMPEG=--add-data bin\ffmpeg.exe;bin"
) else (
    echo   [WARN] bin\ffmpeg.exe tidak ada
    echo          .exe tetap bisa dibuat, tapi download gagal di PC tanpa ffmpeg.
    echo          Ambil dengan:
    echo            python -m pip install imageio-ffmpeg
    echo            python -c "import imageio_ffmpeg,shutil; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),'bin/ffmpeg.exe')"
)

echo.
echo === Installing build dependency ==================================
"%PY%" -m pip install -q streamlit-desktop-app
if errorlevel 1 (
    echo [FAIL] pip install streamlit-desktop-app gagal.
    exit /b 1
)
if not exist "%SDA%" (
    echo [FAIL] console script tidak ditemukan: %SDA%
    exit /b 1
)

echo.
echo === Building ======================================================
REM --onefile  : single .exe, no folder of side-car files.
REM --noconfirm: overwrite a previous build without prompting.
REM PyInstaller separates source from destination with a semicolon on Windows.
"%SDA%" build app.py --name SpotDL --pyinstaller-options --onefile --noconfirm --add-data "providers;providers" --add-data "ui;ui" --add-data "core;core" %ADDFFMPEG%
if errorlevel 1 (
    echo [FAIL] build gagal. Scroll ke atas untuk pesan PyInstaller.
    exit /b 1
)

echo.
echo === Verifying the bundle =========================================
REM Size alone proves nothing: a bundle missing app.py builds fine and then
REM renders a blank window. Read the archive and confirm the real files.
"%PY%" -c "from PyInstaller.archive.readers import CArchiveReader as R; import sys; t=list(R('dist/SpotDL.exe').toc); b=[] if 'app.py' in t else b+['app.py']; [b.append(m) for m in ('providers','ui','core') if not [x for x in t if x.lower().startswith(m+chr(92))]]; print('  bundle    :', 'OK' if not b else 'HILANG '+','.join(b)); sys.exit(1 if b else 0)"
if errorlevel 1 (
    echo [FAIL] bundle tidak lengkap - executable akan tampil kosong.
    exit /b 1
)

echo.
echo === Result ========================================================
if not exist "dist\SpotDL.exe" (
    echo [FAIL] dist\SpotDL.exe tidak terbentuk.
    exit /b 1
)
for %%f in ("dist\SpotDL.exe") do echo   dist\SpotDL.exe = %%~zf bytes
echo.
echo Jalankan dist\SpotDL.exe untuk membuka jendela aplikasi.
endlocal
