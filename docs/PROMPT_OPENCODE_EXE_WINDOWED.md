# Prompt OpenCode — Hilangkan Terminal Hitam di .exe

> Paste ke OpenCode. Ini perbaikan **satu flag** yang sudah terbukti.

---

## MASALAH

User menjalankan `dist/SpotDL.exe`. Aplikasinya jalan, **tapi ada jendela
terminal hitam** yang ikut terbuka. Ketika user menutup jendela aplikasi,
**terminal itu tidak ikut tertutup** — jadi user harus menutup dua-duanya
secara manual lewat Task Manager.

**Sudah diukur, bukan dugaan:**

```
dist/SpotDL.exe  ->  PE32+ executable for MS Windows (console)
                                                      ^^^^^^^
```

`--windowed` **tidak diteruskan** ke PyInstaller. Tanpa flag itu, PyInstaller
membuat **console application**, dan Windows menempelkan jendela terminal
padanya.

**Bukti flag ini menyelesaikan masalah** — build percobaan dengan
`--windowed`, dijalankan lalu ditutup:

```
subsystem  : GUI (bukan console)   <- tidak ada terminal
jendela    : SpotDLW 1024x768
proses     : 3  -> kirim WM_CLOSE -> +2s: 2  -> +4s: 0
HASIL      : SEMUA PROSES MATI (tutup jendela saja cukup)
```

---

## IRONI YANG HARUS DIPERBAIKI

Kedua script **sudah menulis "no console" di komentarnya**, tapi flag-nya tidak
pernah diberikan:

`build_exe.sh` baris 4:
```bash
# Produces dist/SpotDL -- a native window, no console.
```

`build_exe.bat` baris 5:
```
REM Produces dist\SpotDL.exe -- a native window, no console.
```

Komentar itu **salah** — perbaikannya sekaligus membuatnya benar.

---

## YANG DIMINTA

### 1. Tambahkan `--windowed` di kedua script

`build_exe.sh` baris ~75-78:
```bash
streamlit-desktop-app build app.py \
    --name SpotDL \
    --pyinstaller-options --onefile --noconfirm --windowed \
    "${ADD_DATA[@]}"
```

`build_exe.bat` baris ~108 — tambahkan `--windowed` ke daftar
`--pyinstaller-options`:
```
"%SDA%" build app.py --name SpotDL --pyinstaller-options --onefile --noconfirm --windowed --add-data "providers;providers" --add-data "ui;ui" --add-data "core;core" %ADDFFMPEG%
```

**Penjelasan yang perlu ditulis di komentar** (biar tidak terhapus di masa depan):

```bash
# --windowed  : no console window. Without it PyInstaller builds a console
#               application, so Windows attaches a black terminal that does not
#               close when the app window does -- the user has to kill both by
#               hand. Verified: with the flag the window closing takes the whole
#               process tree with it (0 processes left after ~4s).
```

### 2. Perbaiki jalur verifikasi di `build_exe.sh`

Baris ~105 memeriksa `dist/SpotDL`, sedangkan `build_exe.bat` memeriksa
`dist/SpotDL.exe`. Di Windows hasilnya `SpotDL.exe`. Samakan supaya tidak ada
skrip yang memeriksa file yang salah:

```bash
# PyInstaller appends .exe on Windows only.
EXE=dist/SpotDL
[ -f dist/SpotDL.exe ] && EXE=dist/SpotDL.exe
[ -f "$EXE" ] || { echo "[FAIL] $EXE was not produced"; exit 1; }
ls -lh "$EXE"
```

Sesuaikan juga blok pembaca arsip (`CArchiveReader('dist/SpotDL.exe')`) supaya
memakai variabel yang sama.

### 3. Tambahkan pemeriksaan subsystem ke verifikasi build

Ini yang menangkap bug "terminal hitam" secara otomatis, supaya tidak kembali:

```python
import struct
d = open(EXE, 'rb').read(0x200)
off = struct.unpack_from('<I', d, 0x3C)[0]
subsystem = struct.unpack_from('<H', d, off + 0x5C)[0]
# 2 = GUI (no console), 3 = console (black terminal appears)
print('  subsystem :', 'GUI' if subsystem == 2 else 'CONSOLE')
if subsystem != 2:
    print('[FAIL] built as a console app -- --windowed is missing')
    sys.exit(1)
```

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN ubah target `app.py`** — itu sudah benar dan memperbaiki bug blank.
2. **JANGAN hapus `--add-data`** untuk `providers`, `ui`, `core`, dan ffmpeg.
3. **JANGAN sentuh `app.py`, `providers/`, `ui/`, `core/`** — 0 baris. Bug ini
   murni soal flag build.
4. **JANGAN bikin dari awal.** Ubah script yang ada.

---

## VERIFIKASI YANG DIMINTA

### Uji 1 — subsystem harus GUI

```bash
python -c "
import struct
d = open('dist/SpotDL.exe','rb').read(0x200)
off = struct.unpack_from('<I', d, 0x3C)[0]
s = struct.unpack_from('<H', d, off+0x5C)[0]
print('subsystem:', s, '->', 'GUI' if s==2 else 'CONSOLE')
"
```

**Kriteria:** `subsystem: 2 -> GUI`. Kalau `3 -> CONSOLE`, `--windowed` belum masuk.

Alternatif cepat: `file dist/SpotDL.exe` harus menyebut **`(GUI)`**, bukan `(console)`.

### Uji 2 — tutup jendela = semua proses mati

Ini inti keluhan user. Jalankan `.exe`, tunggu jendela muncul, lalu tutup
jendelanya **normal** (klik X) dan hitung sisa proses:

```bash
# sebelum ditutup
tasklist | grep -c SpotDL

# tutup jendela (klik X), tunggu 5 detik, lalu:
tasklist | grep -c SpotDL
netstat -ano | grep LISTENING | grep -cE ':5[0-9]{4}'
```

**Kriteria:**
```
proses setelah ditutup : 0
tidak ada port 5xxxx yang masih LISTENING milik proses itu
```

**Kalau masih ada sisa, laporkan berapa** — jangan diklaim bersih.

### Uji 3 — tidak ada terminal hitam

Subyektif tapi mudah: saat `.exe` dijalankan, **hanya boleh ada satu jendela**
(aplikasi). Kalau ada jendela konsol hitam, `--windowed` belum bekerja.

Bisa juga diperiksa secara objektif: hitung jendela milik proses `.exe` —
harus hanya ada jendela aplikasi (judul `SpotDL`) plus satu
`GDI+ Window (SpotDL.exe)` berukuran 1x1 yang merupakan internal pywebview.
**Tidak boleh ada** jendela `ConsoleWindowClass`.

### Uji 4 — halaman masih render (jangan regresi bug blank)

`--windowed` tidak boleh merusak render. Periksa isi `<body>` dengan browser
sungguhan (bukan `curl`):

```bash
python -c "
import sys, time
from playwright.sync_api import sync_playwright
url = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); pg = b.new_page()
    pg.goto(url, wait_until='networkidle', timeout=60000)
    txt = ''
    for _ in range(8):
        time.sleep(5)
        txt = pg.inner_text('body') or ''
        if len(txt.strip()) > 200: break
    print('body chars:', len(txt))
    print('markdown  :', pg.locator(\"[data-testid='stMarkdownContainer']\").count())
    print('sidebar   :', pg.locator(\"[data-testid='stSidebar']\").count())
    b.close()
" http://localhost:<PORT>
```

**Kriteria:** `body chars` > 200 (referensi: 483), `markdown` > 20 (referensi: 27),
`sidebar` = 1. Teks harus memuat `Spotify Playlist Downloader`.

### Uji 5 — test suite tidak regresi

```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_theme test_fetch_bytes test_oauth test_covers test_app; do
  printf "%-22s " "$t"; python tests/$t.py 2>&1 | tail -1
done
```

**Baseline:** 15 / 71 / 36 / 115 / 34 / 22 / 51 / 12 / 32 / 34 / PASSED (**422 cek**).

### Uji 6 — laporkan ukuran

**Referensi:** 120 MB dengan `--windowed` (vs 121,8 MB tanpa). Laporkan angka
sebenarnya.

---

## LAPORAN YANG DIMINTA

- File yang diubah
- Hasil **Uji 1**: subsystem (GUI atau CONSOLE)
- Hasil **Uji 2** dengan angka: berapa proses sisa setelah jendela ditutup
- Hasil Uji 3-6
- Ukuran `dist/SpotDL.exe`
- Apa yang belum selesai (jujur)

**Kalau prosesnya masih nyangkut atau masih ada terminal, bilang apa adanya**
beserta angkanya — jangan mengklaim bersih.
