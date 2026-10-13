# Prompt OpenCode — Perbaiki .exe yang BLANK

> Paste ke OpenCode. Ini perbaikan bug yang **sudah terbukti** — bukan dugaan.

---

## MASALAH: .exe-nya blank

User menjalankan `dist/SpotDL.exe` dan jendela **kosong** — hanya spinner
"Deploy" yang berputar tanpa henti. Tidak ada UI sama sekali.

**Sudah diukur dengan browser headless (Playwright), bukan ditebak:**

```
.exe LAMA (sekarang)   : body = 11 karakter  → hanya "Stop" + "Deploy"
                         markdown=0  sidebar=0  button=0  text_input=0
                         -> BLANK

.exe PERBAIKAN (probe) : body = penuh        → "Spotify Playlist Downloader",
                         "Load Playlist", sidebar, 27 markdown
                         markdown=27  sidebar=1  button=1  text_input=1
                         -> RENDER
```

---

## AKAR MASALAH — dua bug, keduanya di cara build

### Bug 1 — `launcher.py` di-*serve* sebagai UI, padahal dia bukan UI

`streamlit-desktop-app` menyajikan **file yang diberikan ke `build`** sebagai
script Streamlit. Dibuktikan dari source paketnya
(`streamlit_desktop_app/core.py`):

```python
def run_streamlit(script_path: str, options: Dict[str, str]) -> None:
    args = ["streamlit", "run", script_path]     # <-- file itu di-serve
    ...
```

Kita memanggil `streamlit-desktop-app build launcher.py`, jadi **`launcher.py`
yang di-serve**. Padahal `launcher.py` bukan halaman: dia shell yang memanggil
`start_desktop_app`, dan pada eksekusi sebagai script dia langsung keluar:

```python
def main() -> int:
    if _running_under_streamlit():
        return 0          # <-- nol elemen dirender
```

Streamlit menjalankan file itu, tidak ada satu pun `st.*` dipanggil, jadi
halaman kosong dan spinner "Deploy" berputar selamanya. **Itu blank yang user
lihat.**

**Perbaikan: `build` harus menunjuk `app.py`, bukan `launcher.py`.**

### Bug 2 — modul proyek tidak ikut ke-bundle

Dibuktikan dengan membaca isi arsip `.exe` (`CArchiveReader`):

```
.exe LAMA:
  launcher.py : ADA
  app.py      : TIDAK ADA      <-- tidak ikut
  providers/  : 0 entri        <-- tidak ikut
  ui/         : 0 entri        <-- tidak ikut
  core/       : 0 entri        <-- tidak ikut
```

`streamlit-desktop-app` hanya menambahkan **file target** lewat
`--add-data {script_path}:.` (lihat `build_executable` di paketnya). Paket
`providers/`, `ui/`, `core/` tidak pernah ditambahkan, jadi `app.py` akan
`ImportError` walaupun Bug 1 diperbaiki.

**Perbaikan: tambahkan `--add-data` untuk setiap direktori proyek.**

### Kenapa `launcher.py` masih perlu ada

`streamlit-desktop-app` membuat wrapper-nya sendiri yang memanggil
`start_desktop_app(get_script_path(), ...)`. Jadi **shell-nya sudah disediakan
paket itu** — kita tidak perlu menulisnya sendiri. `launcher.py` yang kita
punya **tidak dipakai** dan justru menyebabkan Bug 1.

**Hapus `launcher.py`.** Kalau ingin menyimpannya sebagai cara menjalankan dari
source, itu di luar scope — yang penting **build tidak menunjuk ke situ**.

---

## YANG DIMINTA

### 1. Ubah target build menjadi `app.py`

Di `build_exe.sh` **dan** `build_exe.bat`, ganti:

```bash
streamlit-desktop-app build launcher.py ...
```
menjadi
```bash
streamlit-desktop-app build app.py ...
```

Perbarui juga komentar yang berbunyi `IMPORTANT -- build launcher.py, never
app.py`. Komentar itu **terbalik** dan harus diganti dengan penjelasan yang
benar: yang di-serve adalah file target, jadi targetnya harus halaman UI.

### 2. Tambahkan `--add-data` untuk modul proyek

Ketiga direktori ini **wajib** ikut, kalau tidak `app.py` gagal import:

```bash
--add-data "providers;providers"
--add-data "ui;ui"
--add-data "core;core"
```

`--add-data` ffmpeg yang sudah ada tetap dipertahankan:

```bash
--add-data "bin/ffmpeg.exe;bin"
```

Di `.bat` gunakan `;` sebagai pemisah; di `.sh` pakai variabel `SEP` yang sudah
ada di script itu (PyInstaller di Windows memakai `;`).

### 3. Hapus `launcher.py`

File itu tidak dipakai lagi dan keberadaannya yang menyesatkan. Kalau ragu,
pindahkan ke `docs/` sebagai catatan — **jangan biarkan di root** karena
`build_exe.*` bisa salah menunjuk ke situ lagi.

### 4. Jangan ubah `app.py` atau provider apa pun

Bug ini **murni soal cara build**. Logika aplikasi sudah terverifikasi:
422 test lolos, channel resmi 14/14, cache + sidecar bekerja, layout fluid.
`providers/youtube.py` hanya bagian `ffmpeg_path()` yang sudah diubah sebelumnya
— jangan disentuh lagi.

---

## VERIFIKASI YANG DIMINTA — INI YANG PALING PENTING

### Uji 1 — isi bundle benar

Setelah build, **baca isi arsip** (jangan cuma lihat ukuran file):

```bash
python -c "
from PyInstaller.archive.readers import CArchiveReader
r = CArchiveReader('dist/SpotDL.exe'); toc = list(r.toc)
print('app.py    :', 'ADA' if 'app.py' in toc else 'TIDAK ADA')
for m in ['providers','ui','core']:
    n = len([x for x in toc if x.lower().startswith(m + chr(92))])
    print(f'{m:10s}: {n} entri')
print('ffmpeg    :', [x for x in toc if 'ffmpeg' in x.lower()] or 'TIDAK ADA')
"
```

**Kriteria:**
```
app.py    : ADA
providers : > 0 entri
ui        : > 0 entri
core      : > 0 entri
ffmpeg    : ['bin\\ffmpeg.exe']
```

### Uji 2 — halaman BENERAN render (bukan cuma HTTP 200)

**`HTTP 200` TIDAK CUKUP.** Streamlit adalah SPA: HTML cangkangnya selalu
mengembalikan 200 walaupun aplikasinya blank — itulah kesalahan verifikasi yang
membuat bug ini lolos sebelumnya. Isi halaman hanya muncul setelah WebSocket
terhubung dan script dijalankan.

Jalankan `.exe`, lalu periksa **teks di dalam `<body>`** dengan browser
sungguhan (headless boleh):

```bash
python -c "
import sys, time
from playwright.sync_api import sync_playwright
url = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.goto(url, wait_until='networkidle', timeout=60000)
    txt = ''
    for _ in range(6):
        time.sleep(5)
        txt = pg.inner_text('body') or ''
        if len(txt.strip()) > 60:
            break
    print('body chars:', len(txt))
    print('cuplikan  :', txt[:200].replace(chr(10), ' | '))
    print('markdown  :', pg.locator(\"[data-testid='stMarkdownContainer']\").count())
    print('sidebar   :', pg.locator(\"[data-testid='stSidebar']\").count())
    print('spinner   :', pg.locator(\"[data-testid='stSpinner']\").count())
    b.close()
" http://localhost:<PORT>
```

**Kriteria (angka ini dari probe yang berhasil):**
```
body chars : > 200   (bukan 11)
markdown   : > 20
sidebar    : 1
spinner    : 0
```
Dan teks harus memuat `Spotify Playlist Downloader` serta `Load Playlist`.

**Kalau `body chars` kecil (belasan) dan `markdown` = 0, itu masih BLANK —
jangan lapor berhasil.**

### Uji 3 — tidak ada error saat script dijalankan

```bash
grep -icE "traceback|error|exception" <log-hasil-run>
```

**Kriteria:** `0`. Log harus bersih — tanpa `WebViewException`,
`ImportError`, `ModuleNotFoundError`, atau `missing ScriptRunContext`.

### Uji 4 — test suite tidak regresi

```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_theme test_fetch_bytes test_oauth test_covers test_app; do
  printf "%-22s " "$t"; python tests/$t.py 2>&1 | tail -1
done
```

**Baseline:** 15 / 71 / 36 / 115 / 34 / 22 / 51 / 12 / 32 / 34 / PASSED
(**422 cek**).

### Uji 5 — laporkan ukuran

**Referensi terukur:** probe yang berhasil = **120 MB** (dengan app.py + 3
modul + ffmpeg). Laporkan angka sebenarnya.

---

## YANG TIDAK BOLEH DILAKUKAN

1. **JANGAN pakai `launcher.py` sebagai target build** — itu penyebab blank.
2. **JANGAN anggap `HTTP 200` sebagai bukti berhasil** — SPA selalu balas 200.
   Harus periksa isi `<body>`.
3. **JANGAN lupa `--add-data` untuk `providers`, `ui`, `core`** — tanpa itu
   `app.py` gagal import di dalam `.exe`.
4. **JANGAN ubah logika aplikasi** — ini murni soal build.
5. **JANGAN bikin dari awal.** Ubah build script yang ada.

---

## LAPORAN YANG DIMINTA

- File yang diubah/dihapus
- Hasil **Uji 1** (isi arsip: app.py + 3 modul + ffmpeg)
- Hasil **Uji 2** dengan **angka nyata**: `body chars`, `markdown`, `sidebar`,
  `spinner` — dan cuplikan teks yang terlihat
- Hasil Uji 3, 4, 5
- Ukuran `dist/SpotDL.exe` sebenarnya
- Apa yang belum selesai (jujur)

**Kalau halamannya masih blank, bilang blank** beserta angkanya — jangan
mengklaim berhasil karena HTTP 200.
