# Prompt OpenCode — Perbaiki Tombol Download yang Tidak Berfungsi di .exe

> Paste ke OpenCode. Bug ini **sudah terbukti dan diperbaiki di build percobaan** —
> tinggal dipindahkan ke repo.

---

## MASALAH

Di `dist/SpotDL.exe`, **semua tombol download tidak berfungsi**. User menekan
tombol Unduh / Download ZIP / Simpan cover / Unduh backup dan **tidak terjadi
apa-apa** — tanpa pesan error, tanpa dialog, tanpa file.

Tombolnya terlihat normal dan bisa diklik, tapi tidak menghasilkan apa pun.

---

## AKAR MASALAH — pywebview memblokir SEMUA download

`pywebview` (dipakai `streamlit-desktop-app` untuk jendela native) menolak setiap
download secara default. Dari `webview/platforms/edgechromium.py`:

```python
def on_download_starting(self, sender, args):
    if not webview_settings['ALLOW_DOWNLOADS']:
        args.Cancel = True          # <-- setiap download dibatalkan
        return
```

Dan defaultnya, dari `webview/__init__.py`:

```python
settings = ImmutableDict({
    'ALLOW_DOWNLOADS': False,       # <-- default
    ...
})
```

Aplikasi ini **sepenuhnya bergantung** pada `st.download_button` — dipakai di
**7 tempat** (`app.py` baris ~572, 1158, 1178, 1287, 1363, 1437, 1502) untuk MP3,
ZIP batch, cover, dan backup. Dengan `ALLOW_DOWNLOADS = False`, **ketujuhnya
mati**.

### Bukti A/B — sudah diukur

Jendela pywebview memuat halaman yang memicu download otomatis:

```
ALLOW_DOWNLOADS = False  -> 40 detik: TIDAK ADA dialog, TIDAK ADA file
ALLOW_DOWNLOADS = True   ->  2 detik: DIALOG "Save As" MUNCUL
```

Definitif. Bukan dugaan.

### Kenapa test suite tidak menangkapnya

`tests/test_app.py` memakai `streamlit.testing.v1.AppTest`, yang menjalankan
`app.py` headless dan mengaksesnya lewat HTTP langsung. Jalur itu **tidak
melewati pywebview sama sekali**, jadi `st.download_button` tampak baik-baik
saja. Celahnya: **tidak ada test yang menguji lewat jendela native.**

---

## YANG DIMINTA

### 1. Buat `runtime_hook_downloads.py` di root proyek

```python
"""Allow downloads in the pywebview window.

pywebview cancels every download unless ALLOW_DOWNLOADS is set:

    def on_download_starting(self, sender, args):
        if not webview_settings['ALLOW_DOWNLOADS']:
            args.Cancel = True

This app is built entirely around st.download_button (MP3, batch ZIP, cover
art, backup), so with the default of False every download control becomes
decorative: clickable, and silently doing nothing.

The setting has to be changed in the process that opens the window, which is the
PyInstaller bootstrap rather than the Streamlit script, so a runtime hook is the
only place that reliably runs before pywebview reads it.
"""

import sys

try:
    if getattr(sys, "frozen", False):
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
except Exception:  # noqa: BLE001 - never break startup over an optional setting
    pass
```

**Penjelasan yang harus tetap ada di file:**

- `sys.frozen` — hook juga jalan di proses anak yang menjalankan Streamlit.
  Di sana pywebview tidak dipakai, jadi penetapan ini tidak berpengaruh. Guard
  itu membuatnya eksplisit.
- `try/except` — kalau pywebview tidak ada atau strukturnya berubah, aplikasi
  tetap harus jalan. Jangan sampai startup gagal karena setting opsional.
- **Kenapa runtime hook, bukan `app.py`** — `app.py` dijalankan sebagai
  *proses terpisah* oleh `start_desktop_app()`; jendela pywebview hidup di
  proses utama. Menetapkan setting di `app.py` tidak akan sampai ke proses yang
  membuka jendela.

### 2. Tambahkan `--runtime-hook` ke kedua build script

`build_exe.sh` — tambahkan ke daftar `--pyinstaller-options`:

```bash
--pyinstaller-options --onefile --noconfirm --windowed \
    --runtime-hook runtime_hook_downloads.py \
```

`build_exe.bat` — hal yang sama, tambahkan `--runtime-hook runtime_hook_downloads.py`
ke daftar opsi.

Tambahkan komentar singkat di kedua script:

```bash
# --runtime-hook : enable pywebview downloads. Without it every
#                  st.download_button is dead in the .exe -- no error, no
#                  dialog, no file. See runtime_hook_downloads.py.
```

### 3. Tambahkan pemeriksaan ke verifikasi build

Setelah build, pastikan hook benar-benar masuk ke arsip. Kalau lupa, bug ini
kembali tanpa gejala.

```python
hook = [x for x in toc if 'runtime_hook' in x.lower()]
print('  hook      :', hook or 'TIDAK ADA')
if not hook:
    print('[FAIL] runtime_hook_downloads tidak ada di bundle - tombol download akan mati')
    sys.exit(1)
```

Letakkan di blok verifikasi arsip yang sudah ada (yang memeriksa `app.py`,
`providers`, `ui`, `core`, `ffmpeg`).

### 4. Dokumentasikan di README

Tambahkan ke bagian build/desktop, di dekat catatan trade-off log:

> Tombol download butuh `ALLOW_DOWNLOADS = True` di pywebview. Itu disetel lewat
> `runtime_hook_downloads.py`, yang diteruskan ke PyInstaller sebagai
> `--runtime-hook`. Tanpa hook itu semua tombol unduh tidak berfungsi di `.exe`,
> tanpa pesan error apa pun.

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN hapus** `--windowed` — itu menghilangkan terminal hitam.
2. **JANGAN hapus** `--add-data` untuk `providers`, `ui`, `core`, `ffmpeg`.
3. **JANGAN ubah target `app.py`** — itu memperbaiki bug blank.
4. **JANGAN sentuh** `app.py`, `providers/`, `ui/`, `core/` — **0 baris**.
   Bug ini murni soal konfigurasi build. Semua tombol download di `app.py`
   sudah benar.
5. **JANGAN bikin dari awal.** Tambah satu file baru + ubah dua build script.

---

## VERIFIKASI YANG DIMINTA

### Uji 1 — hook ada di dalam arsip

```bash
python -c "
from PyInstaller.archive.readers import CArchiveReader
toc = list(CArchiveReader('dist/SpotDL.exe').toc)
print('hook:', [x for x in toc if 'runtime_hook' in x.lower()] or 'TIDAK ADA')
"
```

**Kriteria:** `['runtime_hook_downloads']` — bukan `TIDAK ADA`.

### Uji 2 — setting benar-benar menyala di dalam proses

Bangun `.exe` kecil yang hanya mencetak nilai setting, dengan hook yang sama:

```bash
mkdir -p /tmp/hookcheck && cd /tmp/hookcheck
cat > mini.py <<'PY'
import sys, os, json
from pathlib import Path
out = {}
try:
    import webview
    out['allow_downloads'] = webview.settings['ALLOW_DOWNLOADS']
    out['frozen'] = getattr(sys, 'frozen', False)
except Exception as e:
    out['error'] = repr(e)
Path(os.environ['TEMP'], 'hook_result.json').write_text(json.dumps(out))
PY
python -m PyInstaller --onefile --noconsole --noconfirm \
    --runtime-hook <path-ke-runtime_hook_downloads.py> mini.py
./dist/mini.exe
cat "$TEMP/hook_result.json"
```

**Kriteria:** `{"allow_downloads": true, "frozen": true}`

Ini sudah dijalankan dan hasilnya persis itu. Kalau hasilnya `false`, hook tidak
terpasang.

### Uji 3 — tombol download BENARAN membuka dialog simpan

Ini uji yang paling penting, dan **tidak bisa** dilakukan dengan `AppTest` atau
`curl` — harus lewat jendela native.

Jalankan `.exe`, muat playlist, buka halaman **Backup** (datanya lokal, tidak
perlu jaringan), klik tombol download, lalu cek apakah muncul dialog
`#32770` / "Save As":

```python
import ctypes, ctypes.wintypes as wt, time

u = ctypes.windll.user32

def save_dialogs():
    hits = []
    E = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, l):
        cls = ctypes.create_unicode_buffer(256); u.GetClassNameW(h, cls, 256)
        n = u.GetWindowTextLengthW(h); t = ""
        if n:
            b = ctypes.create_unicode_buffer(n+1); u.GetWindowTextW(h, b, n+1); t = b.value
        if "#32770" in cls.value or "Save As" in t or "Simpan" in t:
            hits.append((cls.value, t))
        return True
    u.EnumWindows(E(cb), 0)
    return hits

print("dialog sebelum:", save_dialogs())
# <-- klik tombol download di jendela aplikasi di sini
time.sleep(3)
print("dialog sesudah:", save_dialogs())
```

**Kriteria:** daftar `sesudah` **tidak kosong** — ada dialog simpan.

**Kalau kosong, laporkan kosong.** Jangan mengklaim berhasil karena tombolnya
"ada di DOM" — tombol memang selalu ada; yang gagal adalah aksinya.

### Uji 4 — jangan regresi

```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_theme test_fetch_bytes test_oauth test_covers test_app; do
  printf "%-22s " "$t"; python tests/$t.py 2>&1 | tail -1
done
```

**Baseline:** 15 / 71 / 36 / 115 / 34 / 22 / 51 / 12 / 32 / 34 / PASSED (**422 cek**).

### Uji 5 — jendela masih render & tidak ada terminal hitam

- `body chars` > 200 (referensi 483), `markdown` > 20 (referensi 27)
- `subsystem` PE = **2** (GUI), bukan 3
- tutup jendela → **0 proses sisa**

---

## LAPORAN YANG DIMINTA

- File baru + file yang diubah
- Hasil **Uji 1** (hook di arsip)
- Hasil **Uji 2** (`hook_result.json` isinya apa)
- Hasil **Uji 3**: apakah dialog simpan muncul (ya/tidak, dengan bukti)
- Hasil Uji 4-5
- Ukuran `dist/SpotDL.exe`
- Apa yang belum selesai (jujur)

**Kalau tombol download masih tidak membuka dialog, bilang apa adanya.**
