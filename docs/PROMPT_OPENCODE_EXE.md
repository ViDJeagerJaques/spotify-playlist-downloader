# Prompt OpenCode — Bikin .exe Jendela Native (Windows)

> Paste ke OpenCode. **JANGAN bikin dari awal** — tambahkan file baru + satu
> perbaikan kecil.

---

## CARA INI SUDAH DIUJI, BUKAN TEORI

Semua angka di bawah ini **terukur dari build nyata** yang sudah dijalankan di
mesin user. Ikuti persis; jangan cari cara lain.

```
Tool     : streamlit-desktop-app 0.3.4
Command  : streamlit-desktop-app build app.py --name SpotDL \
             --pyinstaller-options --onefile --noconfirm
Hasil    : SpotDL.exe = 90 MB
Bukti    : jendela "SpotDL" 1024x768 muncul
           server Streamlit nyala, http://localhost:58803 -> HTTP 200
```

**Catatan penting soal percobaan yang GAGAL** (jangan diulang):

```
pyinstaller app.py --onefile --windowed      <-- SALAH
```
Itu cuma mengeksekusi `app.py` sebagai script biasa. Log menunjukkan
`missing ScriptRunContext! running in bare mode` dan **tidak ada server
Streamlit yang nyala** — tidak ada UI. Harus lewat `streamlit-desktop-app`.

---

## BAGIAN 1 — Perbaikan wajib: buang BOM dari `app.py`

### Masalah

`app.py` diawali **BOM UTF-8** (`EF BB BF`). Terverifikasi:

```bash
$ head -c 3 app.py | od -An -tx1
 ef bb bf

$ python -c "import ast, pathlib; ast.parse(pathlib.Path('app.py').read_text('utf-8'))"
SyntaxError: invalid non-printable character U+FEFF
  File "app.py", line 1
```

**Kenapa ini penting:**

| Pemakai | BOM bikin masalah? |
|---|---|
| Python biasa (`import app`) | **Tidak** — jalan normal |
| `ast.parse` (dipakai `streamlit-desktop-app`) | **YA — build GAGAL** |

Jadi ini bug yang **tidak kelihatan sekarang** tapi **menggagalkan build .exe**.
Build pertama benar-benar gagal karena ini.

### Yang diminta

Buang 3 byte BOM dari awal `app.py`. Hanya file itu — **cek dulu**, dari 62 file
yang di-track git hanya `app.py` yang punya BOM.

```python
import pathlib
p = pathlib.Path("app.py")
raw = p.read_bytes()
if raw.startswith(b"\xef\xbb\xbf"):
    p.write_bytes(raw[3:])
```

**Jangan ubah isi file selain 3 byte itu.** Verifikasi:

```bash
head -c 3 app.py | od -An -tx1        # harus TIDAK lagi 'ef bb bf'
python -c "import ast, pathlib; ast.parse(pathlib.Path('app.py').read_text('utf-8')); print('ast OK')"
```

### Cegah terulang

Tambahkan `.gitattributes` (file baru) supaya editor/git tidak menulis ulang BOM:

```
*.py text eol=lf
```

---

## BAGIAN 2 — Launcher jendela native

Buat file baru **`launcher.py`** di root proyek:

```python
"""Entry point for the desktop build: opens app.py in a native window.

Windows requires the ``__main__`` guard plus ``freeze_support()``. Without them
Streamlit raises "An attempt has been made to start a new process before the
current process has finished its bootstrapping phase" and the build starts a
server but never opens a window. Verified by running the built .exe.
"""
import sys
from multiprocessing import freeze_support
from pathlib import Path

TITLE = "Spotify Playlist Downloader"
WINDOW = (1280, 860)


def main() -> None:
    from streamlit_desktop_app import start_desktop_app

    app = Path(__file__).resolve().parent / "app.py"
    start_desktop_app(str(app), title=TITLE, width=WINDOW[0], height=WINDOW[1])


if __name__ == "__main__":
    freeze_support()
    main()
```

**Alasan tiap bagian:**
- `freeze_support()` + guard `__main__` — **wajib di Windows**, kalau tidak
  Streamlit error saat start (sudah terbukti: percobaan pertama gagal karena ini)
- `Path(__file__).resolve().parent` — supaya `app.py` ketemu baik dijalankan dari
  source maupun dari dalam `.exe`
- Ukuran jendela 1280x860 — cocok dengan layout fluid yang sudah diperbaiki

---

## BAGIAN 3 — Bundle ffmpeg (opsional tapi diminta)

### Kondisi sekarang

`providers/youtube.py` baris ~103:

```python
def ffmpeg_path() -> Optional[str]:
    """Return the ffmpeg executable path, or None when it is not installed."""
    return shutil.which("ffmpeg")
```

Ini **hanya** mencari ffmpeg di PATH sistem. Di PC user ada (222 MB, versi
"full build" — berlebihan), **tapi di PC orang lain belum tentu ada**. Kalau
tidak ada, aplikasi gagal download.

### Yang diminta

Ubah `ffmpeg_path()` supaya **mencari di dalam bundle dulu**, baru PATH:

```python
def ffmpeg_path() -> Optional[str]:
    """Locate ffmpeg: bundled copy first, then whatever is on PATH.

    The desktop build ships a trimmed ffmpeg so the app works on a machine with
    nothing installed. A system ffmpeg is still honoured, so a developer running
    from source keeps using their own.
    """
    bundled = Path(__file__).resolve().parent.parent / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg")
```

Simpan binary di **`bin/ffmpeg.exe`** (folder baru di root proyek).

### ffmpeg mana yang dipakai — INI PENTING

Sudah diukur, jangan salah pilih:

| Sumber | Ukuran | Bisa bikin MP3? |
|---|---|---|
| ffmpeg user sekarang ("full build") | 222 MB | ✅ (kelebihan besar) |
| **imageio-ffmpeg** (dari pip) | **87 MB** | ✅ **teruji bikin MP3** |
| build "minimal" (Ghost Downloader) | 4 MB | ❌ **TIDAK ada encoder MP3** |

**Pakai imageio-ffmpeg.** Cara ambil:

```bash
pip install imageio-ffmpeg
python -c "import imageio_ffmpeg, shutil, pathlib; \
  pathlib.Path('bin').mkdir(exist_ok=True); \
  shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), 'bin/ffmpeg.exe')"
```

**JANGAN** pakai yang 4 MB — sudah diuji, `-encoders` tidak punya `libmp3lame`
dan perintah konversi MP3 gagal total.

Tambahkan `bin/` ke `.gitignore` (binary besar, jangan masuk repo).

---

## BAGIAN 4 — Script build

Buat **`build_exe.sh`** (atau `build_exe.bat`) di root, supaya build bisa
diulang tanpa menebak:

```bash
#!/usr/bin/env bash
set -e
python -m pip install -q streamlit-desktop-app
streamlit-desktop-app build launcher.py \
    --name SpotDL \
    --pyinstaller-options --onefile --noconfirm
ls -lh dist/SpotDL.exe
```

**Perhatikan: `launcher.py`, bukan `app.py`.** Ini bedanya dengan percobaan
yang gagal.

Dokumentasikan di README: cara build, ukuran hasil, dan bahwa `bin/ffmpeg.exe`
harus ada sebelum build kalau mau ffmpeg ikut.

---

## VERIFIKASI YANG DIMINTA — WAJIB SEMUA

Jangan lapor "berhasil" tanpa menjalankan ini.

### Uji 1 — BOM hilang & ast.parse jalan

```bash
head -c 3 app.py | od -An -tx1
python -c "import ast, pathlib; ast.parse(pathlib.Path('app.py').read_text('utf-8')); print('ast.parse OK')"
```

**Kriteria:** tidak ada `ef bb bf`; `ast.parse OK`.

### Uji 2 — aplikasi masih jalan dari source (jangan regresi)

```bash
python -c "import sys; sys.path.insert(0,'.'); import app; print('import OK')"
python tests/smoke.py
```

**Kriteria:** import OK, `smoke.py` **PASS=15 FAIL=0**.

### Uji 3 — semua test lain tidak regresi

```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_theme test_fetch_bytes test_oauth test_covers test_app; do
  printf "%-22s " "$t"; python tests/$t.py 2>&1 | tail -1
done
```

**Baseline yang harus tetap sama:** 15 / 71 / 36 / 115 / 34 / 22 / 51 / 12 / 32 / 34 / PASSED
(**422 cek total**).

### Uji 4 — ffmpeg ditemukan (bundle dulu, PATH kedua)

```bash
python -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import ffmpeg_path
p = ffmpeg_path()
print('ffmpeg:', p)
print('dari bundle?', 'bin' in str(p))
"
```

**Kriteria:** mengembalikan path `bin/ffmpeg.exe` kalau ada; kalau `bin/` kosong,
tetap mengembalikan path sistem (bukan `None`).

### Uji 5 — ffmpeg yang dibundle BENERAN bisa bikin MP3

Ini yang membedakan 87 MB dari 4 MB yang tidak berguna:

```bash
./bin/ffmpeg.exe -hide_banner -encoders 2>/dev/null | grep -i mp3
./bin/ffmpeg.exe -hide_banner -f lavfi -i "sine=frequency=440:duration=1" \
    -c:a libmp3lame -b:a 128k -y /tmp/uji.mp3
ls -lh /tmp/uji.mp3
```

**Kriteria:** `libmp3lame` muncul di daftar encoder, dan file MP3 terbentuk.

### Uji 6 — BUILD & JALANKAN .exe (ini yang paling penting)

```bash
./build_exe.sh
```

Lalu **jalankan `dist/SpotDL.exe`** dan buktikan ketiganya:

1. **Jendela native muncul** — cek dengan Windows API:
   ```bash
   python -c "
   import ctypes, ctypes.wintypes as wt
   u = ctypes.windll.user32; found=[]
   E = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
   def cb(h,l):
       n=u.GetWindowTextLengthW(h)
       if n:
           b=ctypes.create_unicode_buffer(n+1); u.GetWindowTextW(h,b,n+1)
           if 'SpotDL' in b.value or 'Spotify' in b.value:
               r=wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
               found.append((b.value, f'{r.right-r.left}x{r.bottom-r.top}'))
       return True
   u.EnumWindows(E(cb),0)
   print('JENDELA:', found)
   "
   ```
2. **Server Streamlit nyala** — log harus memuat
   `You can now view your Streamlit app` dan sebuah `URL: http://localhost:...`
3. **Halaman render** — `curl` URL itu harus balas **HTTP 200**

**Kriteria:** ketiganya terpenuhi. Kalau jendela tidak muncul, **jangan lapor
berhasil** — laporkan apa adanya beserta isi log.

**Catatan dari percobaan nyata:** kalau log memuat
`missing ScriptRunContext! running in bare mode` dan **tidak ada** pesan
`You can now view`, berarti `.exe` tidak menjalankan server — cek apakah
`freeze_support()` dan guard `__main__` sudah ada di `launcher.py`.

### Uji 7 — laporkan ukuran

```bash
ls -lh dist/SpotDL.exe
```

**Kriteria:** laporkan angka sebenarnya. Referensi terukur: **90 MB tanpa
ffmpeg**. Dengan ffmpeg (87 MB) perkiraan ~150 MB — **ukur, jangan mengarang**.

---

## YANG TIDAK BOLEH DILAKUKAN

1. **JANGAN pakai `pyinstaller app.py` langsung** — sudah terbukti gagal
   (script mode, tidak ada server, tidak ada UI).
2. **JANGAN pakai ffmpeg build "minimal" 4 MB** — tidak punya encoder MP3.
3. **JANGAN ubah logika aplikasi** — `providers/youtube.py` hanya bagian
   `ffmpeg_path()` yang boleh disentuh. Logika channel resmi, cache, sidecar,
   dan layout sudah terverifikasi; jangan diganggu.
4. **JANGAN commit `bin/ffmpeg.exe` atau `dist/`** — tambahkan ke `.gitignore`.
5. **JANGAN bikin dari awal.** Tambah file baru + satu perbaikan kecil.

---

## LAPORAN YANG DIMINTA

- File **baru** dan file **diubah**
- Hasil **Uji 1-7** dengan angka nyata
- **Ukuran `dist/SpotDL.exe`** (angka sebenarnya)
- Apakah **jendela muncul** + apakah **HTTP 200** (ya/tidak, jangan dikaburkan)
- Tabel test sebelum vs sesudah
- Apa yang belum selesai (jujur)

Kalau ada yang gagal, **bilang apa adanya beserta log-nya** — jangan mengarang.
