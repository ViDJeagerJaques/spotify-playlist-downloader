# Prompt OpenCode — Hapus Provider Legacy, Sisakan YouTube + Mock

> Paste ke OpenCode. **JANGAN bikin dari awal** — modifikasi file yang ada.

---

## TUJUAN

Hapus semua provider pihak ketiga yang sudah tidak dipakai (SpotiDown,
SoundLoaders), sisakan **YouTube (yt-dlp)** sebagai satu-satunya backend
download. Mock tetap dipertahankan karena dipakai test offline.

**Alasan sebenarnya BUKAN ukuran file.** Sudah diukur: .exe turun hanya
**61 MB → 54 MB (7 MB)**. Alasan yang benar:

1. **Kejujuran aplikasi** — sekarang user bisa memilih "SpotiDown.co" dan
   "SoundLoaders" dari dropdown, padahal backend itu sudah mati. Pilihan yang
   tidak berfungsi itu menyesatkan.
2. **`pip install` jauh lebih cepat** — `playwright` (112 MB) tidak perlu lagi.
3. **1.745 baris kode mati dibuang.**

---

## YANG DIHAPUS

### File provider (hapus seluruh file)

| File | Baris | Isi |
|---|---|---|
| `providers/spotidown_co.py` | 465 | Chrome + CDP, browser-driven |
| `providers/spotidown.py` | 170 | SpotiDown.app, token reCAPTCHA |
| `providers/soundloaders.py` | 153 | SoundLoaders, token Turnstile |
| `providers/parsing.py` | 236 | HTML parsing **khusus** kedua provider di atas |
| `providers/_http.py` | 35 | session helper, hanya dipakai 2 provider di atas |

### Test & tools

| File | Baris |
|---|---|
| `tests/test_spotidown_co.py` | 300 |
| `tools/spotidown_grab.py` | 386 |

### Dependency

Hapus `playwright` dari `requirements.txt`.

---

## ⚠️ JEBAKAN — `parsing.py` juga dipakai `tests/smoke.py`

Ini yang paling gampang bikin rusak. `smoke.py` mengimpor dari `parsing.py`:

```python
from providers.parsing import (
    decode_track_data,
    first_mp3_link,
    parse_track_rows,
    track_from_row,
)
```

Dipakai oleh **3 test** di dalamnya:

- `test_parser_soundloaders()` — baris ~79-88
- `test_parser_spotidown()` — baris ~91-118
- `test_first_mp3()` — baris ~121-124

Ketiga test ini menguji **HTML parsing provider legacy** — jadi memang ikut
dihapus bersama `parsing.py`. Tapi **hapus juga 3 fungsi test itu**, jangan
cuma hapus importnya (kalau tidak, `smoke.py` akan `NameError`).

**`smoke.py` harus tetap jalan** — sisanya (test mock, orchestrator, i18n,
error handling) **wajib tetap lolos**.

### `smoke.py` juga mengimpor `MockProvider` — JANGAN hapus mock

```python
from providers.mock import MockProvider     # dipakai 5 tempat di smoke.py
```

Dipakai untuk test orchestrator + ZIP + retry. **`providers/mock.py` tetap ada.**

---

## ⚠️ JEBAKAN KEDUA — `ResilientFileFetcher`

`core/orchestrator.py` baris ~127 punya class `ResilientFileFetcher`, dibuat
**khusus** untuk CDN SpotiDown (`.123tokyo.xyz`) yang menolak sebagian request
secara acak.

Setelah legacy dibuang, class ini **tidak lagi terpakai** (hanya dirujuk di
baris 236 yang di-guard oleh `prefetched_urls`).

**Cek dulu sebelum hapus.** Kalau setelah pembersihan `prefetched_urls` tidak
lagi ada di mana pun, hapus `ResilientFileFetcher` **dan** blok `elif` di
baris ~226-236. Kalau ragu, **biarkan** — kode mati yang tidak diimpor tidak
menambah ukuran .exe.

Yang **harus** dibuang dari orchestrator: 3 import di `make_provider()`
(baris ~484-486) dan entri mapping-nya (baris ~489-492).

---

## YANG HARUS DIPERTAHANKAN — JANGAN SENTUH

| File | Alasan |
|---|---|
| `providers/mock.py` | Dipakai 5 tempat di `smoke.py` (orchestrator, ZIP, retry test) |
| `providers/youtube.py` | Backend sekarang |
| `providers/spotify_embed.py` | Metadata Spotify |
| `providers/spotify_spclient.py` | Daftar lagu tanpa login |
| `providers/spotify_meta.py` | OAuth opsional + parse URL |
| `providers/tags.py` | ID3 + cover |
| `providers/base.py` | Tipe dasar (**kecuali** enum, lihat bawah) |

---

## YANG HARUS DIUBAH (bukan dihapus)

### 1. `providers/base.py` — enum `ProviderId`

Sekarang (baris ~37-44):
```python
class ProviderId(str, Enum):
    SOUNDLOADERS = "soundloaders"
    SPOTIDOWN = "spotidown"
    SPOTIDOWN_CO = "spotidown_co"
    YOUTUBE = "youtube"
    MOCK = "mock"
```

**Sisakan hanya:**
```python
class ProviderId(str, Enum):
    YOUTUBE = "youtube"
    MOCK = "mock"
```

### 2. `core/orchestrator.py`

- `make_provider()` — hapus 3 import legacy + mapping-nya, sisakan YOUTUBE & MOCK
- Hapus docstring yang menyebut SoundLoaders/SpotiDown (baris ~14-29)
- Lihat catatan `ResilientFileFetcher` di atas

### 3. `ui/data.py`

Baris ~192-195:
```python
def download_headers() -> dict:
    """MP3 endpoint headers (Origin/Referer) taken from the active provider."""
    from providers.spotidown_co import DOWNLOAD_HEADERS
    return dict(DOWNLOAD_HEADERS)
```

`DOWNLOAD_HEADERS` **hilang** bersama `spotidown_co.py`. Ganti dengan header
YouTube yang wajar (User-Agent browser biasa), atau kembalikan `{}` kalau
`app.py` sudah punya default sendiri. **Cek pemakainya dulu** — jangan
sampai `ImportError` saat runtime.

Docstring `BATCH_LIMIT` di baris ~7-13 menyebut cap 100 lagu spotidown.co —
sudah tidak relevan, perbarui atau hapus.

### 4. `app.py`

| Baris | Yang dilakukan |
|---|---|
| ~41 | `from providers.mock import _mock_mp3_bytes` — **PERTAHANKAN** |
| ~55-59 | Daftar pilihan backend — sisakan YouTube + Mock |
| ~235-253 | Field captcha/token di sidebar — **hapus** (tidak ada yang butuh) |
| ~284-294 | Blok khusus SOUNDLOADERS/SPOTIDOWN — hapus |
| ~366-370 | Cabang `SPOTIDOWN_CO` / legacy — hapus |
| ~500 | Cabang `SPOTIDOWN_CO` — hapus |

**Pertahankan** cabang `MOCK` (baris ~488, ~1496, ~1501) dan `YOUTUBE`
(baris ~350, ~502, ~512, ~677, ~926).

**Pertahankan** `CaptchaRequiredError` di `render_errors()` (baris ~183) —
class-nya ada di `base.py` dan tidak ada ruginya; menghapusnya berarti
menyentuh jalur error yang sudah teruji.

### 5. `core/i18n.py`

Ada **20 baris** yang menyebut SoundLoaders/SpotiDown/captcha. Hapus kunci
yang jadi yatim, **tapi pertahankan `mock_note`** (baris ~115, ~224) karena
mode Demo masih ada.

Teks yang menyebut "Streamlit wrapper untuk layanan pihak ketiga —
SoundLoaders / SpotiDown" harus diganti: aplikasi ini sekarang **langsung**
ke YouTube + Spotify, tanpa pihak ketiga.

### 6. `requirements.txt`

Hapus `playwright`. Perbarui komentar yang menyebutnya.

---

## VERIFIKASI YANG DIMINTA

### Uji 1 — tidak ada sisa referensi legacy

```bash
grep -rn "spotidown\|soundloaders\|SpotiDown\|SoundLoaders\|playwright" \
  --include="*.py" --include="*.txt" --include="*.md" . \
  | grep -v ".venv" | grep -v "^./docs/"
```

**Kriteria:** kosong, **kecuali** penyebutan historis di `README.md` bagian
sejarah/migrasi (boleh dipertahankan sebagai catatan) dan `docs/`.

### Uji 2 — import bersih (ini yang menangkap ImportError)

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
import app
from core.orchestrator import make_provider
from providers.base import ProviderId
print('import app: OK')
print('provider tersedia:', [p.value for p in ProviderId])
print('youtube:', type(make_provider('youtube')).__name__)
print('mock   :', type(make_provider('mock')).__name__)
"
```

**Kriteria:** tidak ada `ImportError`; `provider tersedia: ['youtube', 'mock']`.

### Uji 3 — mock masih hidup (jangan ikut terhapus)

```bash
.venv/Scripts/python.exe tests/smoke.py
```

**Kriteria:** **PASS=22 FAIL=0**. (Baseline sekarang 25; 3 test parser legacy
memang ikut dihapus. Kalau hasilnya 25, berarti test legacy belum dibuang.
Kalau < 22, ada test lain yang kena.)

### Uji 4 — semua test lain tidak regresi

```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_theme test_fetch_bytes test_oauth test_covers test_app; do
  printf "%-22s " "$t"; .venv/Scripts/python.exe tests/$t.py 2>&1 | tail -1
done
```

**Baseline sebelum (yang harus tetap sama setelah):**

| Test | Sebelum | Sesudah |
|---|---|---|
| smoke | 25 | **22** (3 test parser legacy dibuang) |
| test_youtube | 71 | **71** |
| test_spotify_embed | 35 | **35** |
| test_spclient | 115 | **115** |
| test_tags | 34 | **34** |
| test_cover_size | 22 | **22** |
| test_spotidown_co | 67 | **file dihapus** |
| test_theme | 51 | **51** |
| test_fetch_bytes | 12 | **12** |
| test_oauth | 32 | **32** |
| test_covers | 34 | **34** |
| test_app | PASSED | **PASSED** |

**Jumlah total: 418 cek** (dari 485 sebelumnya) harus tetap lolos.

### Uji 5 — UI masih jalan tanpa field captcha

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from streamlit.testing.v1 import AppTest
from pathlib import Path
at = AppTest.from_file(str(Path('app.py').resolve()), default_timeout=180)
at.run()
print('exception:', at.exception)
print('radio backend:', [r.options for r in at.radio] if at.radio else 'tidak ada')
"
```

**Kriteria:** `exception: []` (tidak ada error), dan pilihan backend hanya
YouTube + Demo.

### Uji 6 — .exe masih bisa dibangun (opsional tapi berguna)

Kalau `pyinstaller` tersedia, bangun dan laporkan ukurannya. Sebelumnya
**61 MB dengan playwright**. Setelah dibuang, target **≤ 54 MB**.

---

## YANG TIDAK BOLEH DILAKUKAN

1. **JANGAN hapus `providers/mock.py`** — 5 test di `smoke.py` bergantung padanya.
2. **JANGAN hapus test mock di `smoke.py`** (`test_orchestrator_mock_zip`,
   test retry, dll) — hanya 3 test parser legacy yang dibuang.
3. **JANGAN sentuh** `youtube.py`, `spotify_*.py`, `tags.py` — itu bagian
   yang sudah benar dan terverifikasi (14/14 channel resmi, 498 test lolos).
4. **JANGAN ubah** logika cache, sidecar, atau layout CSS.
5. **JANGAN hapus** `CaptchaRequiredError` dari `base.py` — jalur error itu
   sudah teruji dan dipakai `render_errors()`.
6. **JANGAN bikin dari awal.** Modifikasi file yang ada.

---

## LAPORAN YANG DIMINTA

- File yang **dihapus** (dengan jumlah baris)
- File yang **diubah** (apa yang berubah)
- Hasil **Uji 1-5** dengan angka nyata
- Tabel test sebelum vs sesudah
- Kalau `ResilientFileFetcher` ikut dihapus, jelaskan alasannya
- Apa yang belum selesai (jujur)

Kalau ada yang tidak bisa dicapai, **bilang apa adanya** — jangan mengarang.
