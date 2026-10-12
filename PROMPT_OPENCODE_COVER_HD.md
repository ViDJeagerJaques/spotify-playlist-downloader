# Prompt untuk OpenCode — Cover Resolusi Tinggi (640x640)

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## MASALAH

User membandingkan cover hasil app kita dengan cover dari SpotiDown:

```
Punya kita : 300x300   (~45 KB)
SpotiDown  : 640x640   (~158 KB)   <- user mau ini
```

Cover kita **kelihatan pecah/blur** kalau dibuka besar.

---

## AKAR MASALAH — sudah didiagnosis, jangan cari lagi

URL cover Spotify punya **prefix yang menentukan resolusi**. Hash-nya sama,
cuma prefix yang beda:

```
ab67616d00001e02  ->  300x300  (45 KB)     <-- yang kita pakai sekarang
ab67616d0000b273  ->  640x640  (158 KB)    <-- TARGET
ab67616d00004851  ->  64x64    (3.7 KB)
```

Contoh nyata (Cinnamon Girl, hash `879e9318cb9f4e05ee552ac9`):

```
300x300 : https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02879e9318cb9f4e05ee552ac9
640x640 : https://image-cdn-ak.spotifycdn.com/image/ab67616d0000b273879e9318cb9f4e05ee552ac9
```

**Yang kita pakai sekarang 300x300** karena `thumbnail_url` dari oEmbed
mengembalikan prefix `ab67616d00001e02`.

---

## PERBAIKAN

Ganti prefix `ab67616d00001e02` → `ab67616d0000b273` pada URL cover album.

```python
COVER_SMALL_PREFIX = "ab67616d00001e02"   # 300x300 — yang dikirim oEmbed
COVER_LARGE_PREFIX = "ab67616d0000b273"   # 640x640 — yang kita mau

def upgrade_cover_url(url: str) -> str:
    """Naikkan resolusi cover album 300x300 -> 640x640.

    Hanya berlaku untuk cover ALBUM (prefix ab67616d...). Cover playlist
    memakai prefix berbeda (ab67706f...) dan akan 404 kalau diganti.
    """
    if not url:
        return url
    return url.replace(COVER_SMALL_PREFIX, COVER_LARGE_PREFIX)
```

**Terapkan di:**

1. **`providers/spotify_spclient.py` → `track_cover_oembed()`**
   Naikkan resolusi sebelum URL dikembalikan.

2. **`providers/spotify_embed.py` → cover album** (jalur 100 pertama)
   Kalau cover berasal dari oEmbed, naikkan juga.

3. **`providers/tags.py` → `download_cover()`**
   Sebagai jaring pengaman, naikkan resolusi di sini juga kalau URL-nya
   masih prefix kecil.

**JANGAN** naikkan resolusi untuk:
- **Cover playlist** (prefix `ab67706f...`) — akan 404
- Cover yang bukan dari Spotify CDN

---

## YANG SUDAH DIVERIFIKASI (jangan ubah asumsinya)

- Prefix `ab67616d0000b273` → **640x640**, ~158 KB, HTTP 200
- Prefix `ab67616d00001e02` → 300x300, ~45 KB
- Prefix `ab67616d00004851` → 64x64
- **Dua domain sama-sama jalan** dan memberi hasil identik:
  - `https://i.scdn.co/image/...`
  - `https://image-cdn-ak.spotifycdn.com/image/...`
- Uji 4 lagu berbeda → **4/4 berhasil** jadi 640x640
- Hash album **sama** di semua resolusi (cuma prefix yang beda)

---

## VERIFIKASI YANG DIMINTA

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from providers.spotify_spclient import track_cover_oembed
u = track_cover_oembed('2mdEsXPu8ZmkHRRtAdC09e')
print('URL:', u)
assert 'ab67616d0000b273' in u, 'masih prefix kecil!'
print('OK: prefix 640x640')
"
```

Lalu uji nyata — download cover, cek dimensinya:

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from providers.spotify_spclient import track_cover_oembed
from providers.tags import download_cover
import subprocess, tempfile, pathlib, json
u = track_cover_oembed('2mdEsXPu8ZmkHRRtAdC09e')
data = download_cover(u)
p = pathlib.Path(tempfile.gettempdir())/'c.jpg'; p.write_bytes(data)
r = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_streams',str(p)],
                   capture_output=True, text=True)
st = json.loads(r.stdout)['streams'][0]
print('dimensi:', st.get('width'), 'x', st.get('height'), '|', len(data), 'bytes')
"
```

**Kriteria:**
- `width == 640` dan `height == 640`
- ukuran file ~150-160 KB (bukan ~45 KB)

Uji juga **cover di dalam MP3** (yang ditanam oleh R4):
```bash
ffprobe -v quiet -print_format json -show_streams <file.mp3>
```
Stream `mjpeg` harus 640x640.

---

## BATASAN

1. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
2. **JANGAN ubah audio** — cuma URL cover.
3. **JANGAN** naikkan resolusi cover playlist (prefix `ab67706f`) — akan 404.
4. **JANGAN** pakai `api.spotify.com` — cukup ganti prefix.
5. Test lama harus tetap lolos.

---

## TEST YANG HARUS TETAP LOLOS

```bash
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_covers.py        # PASS=34 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=32 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=51 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=91 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- Dimensi cover **sebelum vs sesudah** (angka nyata dari `ffprobe`)
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)
