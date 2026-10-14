# Prompt OpenCode — Tombol Download Mati di .exe

> Paste ke OpenCode. Bug sudah terbukti dan perbaikannya sudah diuji.

---

## MASALAH

Di `dist/SpotDL.exe` yang dibuild dari repo ini, **semua tombol download tidak
berfungsi** — diklik, tidak ada dialog, tidak ada file, **tanpa pesan error**.

Padahal aplikasi memakai `st.download_button` di **7 tempat** (`app.py` baris
~572, 1158, 1178, 1287, 1363, 1437, 1502) untuk MP3, ZIP batch, cover, backup.

## AKAR MASALAH

`pywebview` membatalkan setiap download kecuali `ALLOW_DOWNLOADS` diset.
Dari `webview/platforms/edgechromium.py`:

```python
def on_download_starting(self, sender, args):
    if not webview_settings['ALLOW_DOWNLOADS']:
        args.Cancel = True          # <-- semua download dibatalkan
```

Defaultnya `False` (`webview/__init__.py`). Diukur A/B: `False` → 40 detik
tanpa dialog; `True` → dialog "Save As" muncul dalam 2 detik.

**Kenapa test suite lolos:** `AppTest` menjalankan `app.py` headless lewat HTTP,
tidak melewati pywebview sama sekali.

---

## YANG DIMINTA

### 1. Buat `runtime_hook_downloads.py` di root

```python
"""Allow downloads in the pywebview window.

pywebview cancels every download unless ALLOW_DOWNLOADS is set. This app is
built around st.download_button (MP3, batch ZIP, cover art, backup), so with the
default of False every download control is decorative: clickable, silently doing
nothing, with no error to explain why.

The setting must be applied in the process that opens the window -- the
PyInstaller bootstrap, not the Streamlit script, which runs in a child process.
A runtime hook is the only place that reliably runs before pywebview reads it.
"""

import sys

try:
    if getattr(sys, "frozen", False):
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
except Exception:  # noqa: BLE001 - never break startup over an optional setting
    pass
```

### 2. Tambahkan `--runtime-hook` ke kedua build script

`build_exe.sh` baris ~89, tambahkan ke daftar opsi:
```bash
    --pyinstaller-options --onefile --noconfirm --windowed \
        --runtime-hook runtime_hook_downloads.py \
```

`build_exe.bat` baris ~120, tambahkan sebelum `--add-data`:
```
--runtime-hook runtime_hook_downloads.py
```

Beri komentar di kedua script:
```bash
# --runtime-hook : enables pywebview downloads. Without it every
#   st.download_button is dead in the .exe -- no error, no dialog, no file.
```

### 3. Tambahkan pemeriksaan hook ke verifikasi build

Di blok verifikasi arsip yang sudah ada (`build_exe.sh` baris ~106,
`build_exe.bat` baris ~118), tambahkan:

```python
hook = [x for x in toc if 'runtime_hook' in x.lower()]
print('  hook      :', hook or 'TIDAK ADA')
if not hook:
    print('[FAIL] runtime_hook_downloads tidak ada - tombol download akan mati')
    sys.exit(1)
```

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN sentuh** `app.py`, `providers/`, `ui/`, `core/` — **0 baris**. Tombol
   download di `app.py` sudah benar; ini murni konfigurasi build.
2. **JANGAN hapus** `--windowed` (itu yang menghilangkan terminal hitam) atau
   `--add-data` (itu yang membuat `app.py` + modul ikut ke bundle).
3. **JANGAN ubah target `app.py`.**
4. **JANGAN bikin dari awal.**

---

## VERIFIKASI

### Uji 1 — hook ada di arsip

```bash
python -c "
from PyInstaller.archive.readers import CArchiveReader
t = list(CArchiveReader('dist/SpotDL.exe').toc)
print('hook:', [x for x in t if 'runtime_hook' in x.lower()] or 'TIDAK ADA')
"
```
**Kriteria:** `['runtime_hook_downloads']`

### Uji 2 — setting benar-benar menyala di dalam proses frozen

Build `.exe` mini yang hanya mencetak nilainya, dengan hook yang sama:

```bash
mkdir -p /tmp/hk && cd /tmp/hk
printf 'import sys,os,json\nfrom pathlib import Path\no={}\ntry:\n    import webview\n    o["allow_downloads"]=webview.settings["ALLOW_DOWNLOADS"]\n    o["frozen"]=getattr(sys,"frozen",False)\nexcept Exception as e:\n    o["error"]=repr(e)\nPath(os.environ["TEMP"],"hk.json").write_text(json.dumps(o))\n' > mini.py
python -m PyInstaller --onefile --noconsole --noconfirm \
    --runtime-hook <path-ke-runtime_hook_downloads.py> mini.py
./dist/mini.exe && cat "$TEMP/hk.json"
```
**Kriteria:** `{"allow_downloads": true, "frozen": true}`
(Sudah dijalankan sekali, hasilnya persis itu.)

### Uji 3 — tombol download benar-benar membuka dialog simpan

**Ini uji yang menentukan, dan tidak bisa pakai AppTest atau curl** — harus
lewat jendela native.

Jalankan `.exe`, muat playlist, buka halaman **Backup** (datanya lokal, tidak
perlu jaringan), klik tombol download, lalu cek munculnya dialog `#32770`:

```python
import ctypes, time
u = ctypes.windll.user32
def dialogs():
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
print("sebelum:", dialogs())
# <-- klik tombol download di jendela aplikasi
time.sleep(4)
print("sesudah:", dialogs())
```

**Kriteria:** `sesudah` **tidak kosong**.

> **Jangan mengklaim berhasil hanya karena tombolnya "ada di DOM".** Tombolnya
> selalu ada — yang gagal adalah aksinya.

### Uji 4 — tidak regresi

```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_theme test_fetch_bytes test_oauth test_covers test_app; do
  printf "%-22s " "$t"; python tests/$t.py 2>&1 | tail -1
done
```
**Baseline:** 15 / 71 / 36 / 115 / 34 / 22 / 51 / 12 / 32 / 34 / PASSED (**422 cek**).

### Uji 5 — jendela masih normal

- `subsystem` PE = **2** (GUI, bukan 3) → tidak ada terminal hitam
- `body chars` > 200 (referensi 483), `markdown` > 20
- tutup jendela → **0 proses sisa**

---

## LAPORAN

- File baru + file diubah
- Uji 1: isi daftar hook
- Uji 2: isi `hk.json`
- Uji 3: **apakah dialog simpan muncul** (ya/tidak + bukti)
- Uji 4-5 + ukuran `dist/SpotDL.exe`
- Apa yang belum selesai (jujur)

**Kalau tombol download masih tidak membuka dialog, bilang apa adanya.**
