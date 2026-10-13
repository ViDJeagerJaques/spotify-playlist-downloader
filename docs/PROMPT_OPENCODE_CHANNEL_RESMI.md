# Prompt untuk OpenCode — Prioritaskan Channel Resmi Artis (BERLAKU SEMUA ARTIS)

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## MASALAH

yt-dlp mengambil video dari channel **bukan milik artisnya** — walaupun judul
lagunya benar. Contoh nyata:

```
Yang terambil  : channel "Ayli"        — "Glimpse of Us by Joji but it will change your life"
Yang seharusnya: channel "Joji"         — "Joji - Glimpse of Us (Official Video)"
```

User minta: **otomatis pilih video dari channel resmi artisnya.**
**Berlaku untuk SEMUA artis, bukan cuma Joji.**

---

## BUKTI INI UNIVERSAL — sudah diuji 20 kasus

Diuji lintas genre & negara. **Channel bernama sama dengan artist hampir
selalu ada** di hasil search:

| Artist | Channel yang cocok | Cocok? |
|---|---|---|
| Joji | Joji | ✅ |
| Lana Del Rey | Lana Del Rey | ✅ |
| Taylor Swift | Taylor Swift | ✅ |
| Harry Styles | Harry Styles | ✅ |
| Bruno Mars | Bruno Mars | ✅ |
| The Weeknd | The Weeknd | ✅ |
| Tulus | Tulus | ✅ |
| Pamungkas | Pamungkas | ✅ |
| Radiohead | Radiohead | ✅ |
| Adele | Adele | ✅ |
| NIKI | NIKI | ✅ |
| BLACKPINK | BLACKPINK | ✅ |
| Reality Club | REALITY CLUB | ✅ |
| Daniel Caesar | Daniel Caesar | ✅ |
| Don Toliver, Doja Cat | Don Toliver | ✅ (cocok sebagian) |
| **BTS** | HYBE LABELS | ❌ (label, bukan nama artis) |
| **wave to earth** | Alternate / danielions music | ❌ (tak ada channel resmi) |

**Hasil: 11/12 (92%)** pada uji pertama; **14/16** setelah kasus sulit ditambah.

### ⚠️ JEBAKAN — badge verified saja TIDAK CUKUP

```
verified=True   Joji        Joji - Glimpse of Us (Official Video)   <-- TARGET
verified=True   Indolirik   Joji – Glimpse of Us | Lirik Terjemahan <-- verified juga!
verified=None   LatinHype   Joji - Glimpse Of Us
verified=True   Lost Panda  Joji - Slow Dancing (Lyrics)            <-- verified juga!
```

`Indolirik` dan `Lost Panda` **verified**, tapi itu channel **lirik terjemahan**,
bukan milik artisnya. Kalau cuma pakai badge, hasilnya tetap salah.

**Jadi butuh DUA syarat:**
1. **Nama channel cocok dengan nama artist** ← sinyal UTAMA
2. `channel_is_verified == True` ← sinyal pendukung

### Kasus yang harus ditangani

**a. Multi-artist / feat.**
```
artist Spotify : "Don Toliver, Doja Cat"
channel        : "Don Toliver"     <- cocok SEBAGIAN, harus diterima
artist         : "Taylor Swift"    <- "Snow On The Beach (feat. More Lana Del Rey)"
channel        : "Taylor Swift"    <- cocok dengan artist pertama
```
→ Bandingkan dengan **setiap** bagian nama artist (pisah pada `,` `&` `feat.`).

**b. Nama channel pakai huruf besar / spasi beda**
```
artist  : "Reality Club"
channel : "REALITY CLUB"    <- harus dianggap COCOK (case-insensitive)
artist  : "wave to earth"
channel : "WAVE TO EARTH"   <- harus dianggap COCOK
```
→ Normalisasi: lowercase, buang tanda baca, rapikan spasi.

**c. Tidak ada channel yang cocok (BTS, wave to earth)**
→ Jangan paksa. **Jatuhkan ke perilaku sekarang** (skor durasi + hints),
   dengan `channel_is_verified` tetap dihitung kalau ada.

**d. Channel label resmi**
```
BTS      -> HYBE LABELS
```
Ini resmi tapi namanya tidak mengandung "BTS". **Jangan dianggap salah** —
cukup biarkan scoring lama yang menentukan.

---

## MASALAH TEKNIS — `extract_flat` tidak memberi field verified

```
extract_flat = True   -> channel_is_verified = None   (field tidak ada)
ekstraksi penuh       -> channel_is_verified = True
```

**Kode sekarang** (`providers/youtube.py`, `_pick_best()`) memakai
`extract_flat: True`.

**Konsekuensi waktu:** kalau semua 5 kandidat diekstrak penuh, tambah ~2.5
detik per lagu. Playlist 213 lagu = **+9 menit**. Itu tidak boleh.

---

## YANG DIMINTA

### 1. Tambah penilaian channel resmi di `score_candidate()`

Fungsi `score_candidate(cand, want_seconds)` di `providers/youtube.py` baris ~115.

**Skor sekarang:**
```python
dur = cand.get("duration") or 0
if want_seconds and dur:
    drift = abs(float(dur) - want_seconds)
    if drift > MAX_DURATION_DRIFT_S:   # 25 detik
        return -1.0
    score = 10.0 - (drift / MAX_DURATION_DRIFT_S) * 5.0
else:
    score = 5.0

blob = _norm(f"{title} {uploader} {channel}")
if any(h in blob for h in _OFFICIAL_HINTS):   # "official audio", "topic", ...
    score += 3.0
if any(h in blob for h in _PENALTY_HINTS):    # "live", "cover", "remix", ...
    score -= 4.0

views = cand.get("view_count") or 0
if views > 1_000_000: score += 1.5
elif views > 100_000: score += 0.8
```

**Tambahan yang diminta:**

```python
# --- channel resmi artis (sinyal UTAMA) ---
artist_n  = _norm(artist)                        # perlu parameter baru
channel   = _norm(cand.get("channel") or cand.get("uploader") or "")

# artist bisa multi ("Don Toliver, Doja Cat") -> cek tiap bagian
parts = [_norm(p) for p in re.split(r"[,&]|feat\.?", artist) if _norm(p)]

if channel:
    if any(p and (p in channel or channel in p) for p in parts):
        score += 6.0        # cocok nama artist (penuh ATAU sebagian)
    elif artist_n and (artist_n in channel or channel in artist_n):
        score += 6.0        # jaring pengaman kalau pemisahan gagal

    # --- channel lirik/terjemahan: penalti ---
    # Verified tapi bukan artisnya. Contoh nyata: "Indolirik", "Lost Panda"
    if any(h in channel for h in ("lyrics", "lirik", "terjemahan", "lyric",
                                  "7clouds", "cloudy", "vibes")):
        score -= 3.0

# --- badge verified (sinyal pendukung) ---
if cand.get("channel_is_verified"):
    score += 3.0
```

**Alasan angkanya:**
- **+6.0 cocok nama artist** — sinyal terkuat dan **paling murah** (tidak butuh
  request tambahan kalau datanya sudah ada dari search)
- **+3.0 verified** — bagus, tapi sendirian tidak cukup (lihat jebakan Indolirik)
- **-3.0 channel lirik** — mencegah Indolirik/Lost Panda menang walau verified

**PENTING:** `score_candidate()` sekarang hanya menerima `(cand, want_seconds)`.
Tanda tangannya harus ditambah parameter artist (mis. `artist: str = ""`), dan
pemanggilnya (`_pick_best()`) harus meneruskan `track.artist`.

### 2. Ambil `channel_is_verified` TANPA memperlambat

**Jangan ekstrak penuh semua kandidat.** Strategi bertahap:

```
Langkah 1: search biasa (extract_flat, cepat) -> 5 kandidat + judul + channel
Langkah 2: hitung skor dasar (durasi, judul, channel vs artist)
Langkah 3: kalau kandidat teratas SUDAH cocok nama artist-nya -> SELESAI
           (nol request tambahan, tidak perlu cek verified)
Langkah 4: kalau BELUM ada yang cocok -> ekstrak penuh MAKSIMAL 3 kandidat
           teratas untuk membaca channel_is_verified
Langkah 5: pilih skor tertinggi
```

**Alasan:** 92% kasus punya channel bernama persis artist-nya. Untuk kasus itu
**nol request tambahan** — cukup cocokkan nama. Ekstraksi penuh hanya dipakai
sebagai cadangan.

### 3. Cache hasil verified

Simpan `video_id -> channel_is_verified` supaya tidak diekstrak dua kali.
Ikuti pola `load_cache` / `save_cache` di `providers/spotify_spclient.py`.

### 4. Jangan regresi yang sudah jalan

`_OFFICIAL_HINTS` dan `_PENALTY_HINTS` **tetap dipakai**:
```python
_OFFICIAL_HINTS = ("official audio", "official video", "topic", "provided to youtube")
_PENALTY_HINTS = ("live", "cover", "remix", "sped up", "slowed", "nightcore", "reaction", "lyrics video hd")
```
Ini **penambahan**, bukan penggantian.

### 5. Normalisasi nama yang benar

Buang perbedaan yang tidak penting:
```
"REALITY CLUB"  ==  "Reality Club"      (huruf besar)
"wave to earth" ==  "WAVE TO EARTH"     (huruf besar)
"Lana Del Rey"  ==  "Lana Del Rey "     (spasi)
"YOASOBI"       ==  "YOASOBI"           (tetap)
```
Buang tanda baca, rapikan spasi, lowercase, dan tangani aksen (mis. `é` -> `e`).

---

## VERIFIKASI YANG DIMINTA — WAJIB BERLAKU SEMUA ARTIS

Jangan cuma uji Joji. **Uji minimal 10 artis** dari genre/negara berbeda.

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
cases = [
    ('Joji','Glimpse of Us',222000),
    ('Lana Del Rey','Cinnamon Girl',300683),
    ('Taylor Swift','Blank Space',231826),
    ('Harry Styles','Sign of the Times',341000),
    ('Bruno Mars','Locked Out of Heaven',233000),
    ('The Weeknd','Blinding Lights',200000),
    ('Tulus','Monokrom',240000),
    ('Pamungkas','To the Bone',250000),
    ('Radiohead','Creep',238000),
    ('Adele','Someone Like You',285000),
    ('NIKI','Take A Chance With Me',303933),
    ('BLACKPINK','How You Like That',182000),
    ('Reality Club','Love Epiphany',240000),
    ('Daniel Caesar','Who Knows',226283),
]
ok = 0
for title, artist, dur in cases:
    t = Track(data='x', track_token='x', title=title, artist=artist, duration_ms=dur)
    b = c._pick_best(f'{artist} {title}', int(dur/1000), artist)
    ch = (b or {}).get('channel') or '?'
    print(f'{artist:16s} -> {ch}')
"
```

**Kriteria:**
- Minimal **12 dari 14** memilih channel yang mengandung nama artist
- Tidak ada yang memilih channel lirik (`Indolirik`, `7clouds`, `Lost Panda`, dll)
- Kasus sulit (BTS, wave to earth) boleh jatuh ke perilaku lama — **jangan crash**

### Uji waktu (jangan sampai lambat)

```bash
.venv/Scripts/python.exe -c "
import sys, time; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
t0 = time.time()
for title, artist, dur in [('Glimpse of Us','Joji',222000),
                           ('Blinding Lights','The Weeknd',200000),
                           ('Monokrom','Tulus',240000)]:
    t = Track(data='x', track_token='x', title=title, artist=artist, duration_ms=dur)
    c._pick_best(f'{artist} {title}', int(dur/1000), artist)
print(f'rata-rata: {(time.time()-t0)/3:.1f}s per lagu')
"
```

**Kriteria:** **< 3 detik per lagu**.

---

## BERLAKU DI SEMUA JALUR DOWNLOAD (WAJIB)

Perbaikan ini **harus kena dua jalur**, bukan cuma satu:

### Jalur 1 — Download Lagu (satuan)
`app.py` baris ~675, fungsi `_fetch_mp3_bytes()`:
```python
provider = _get_provider()
resolved = track.mp3_url or provider.resolve_track(track, cftoken="")
```
Dipanggil tombol **"Unduh"** per baris di halaman Download Lagu.

### Jalur 2 — Download Playlist (batch / ZIP)
`core/orchestrator.py` baris ~248, `_resolve_and_stage()`:
```python
mp3_url = self.provider.resolve_track(track, cftoken=cftoken)
```
Dipanggil loop batch di halaman Download Playlist.

### Kabar baiknya
**Dua-duanya lewat `resolve_track()` yang sama.** Jadi kalau logika pemilihan
channel diperbaiki di `providers/youtube.py` (`_pick_best()`), **kedua jalur
otomatis ikut benar.**

### Yang harus dipastikan
1. **Jangan** taruh logika pemilihan channel di `app.py` atau
   `core/orchestrator.py` — taruh di `providers/youtube.py` supaya kedua jalur
   memakai kode yang sama.
2. **Cache** harus dipakai bersama: kalau lagu sudah pernah di-resolve
   (mis. dari batch), jalur satuan tidak perlu cari ulang.
3. **Verifikasi KEDUA jalur**, jangan cuma satu:

```bash
# Jalur 1: satuan (seperti tombol "Unduh")
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
t = Track(data='x', track_token='x', title='Glimpse of Us', artist='Joji', duration_ms=222000)
p = c.resolve_track(t)
print('satuan ->', p)
"

# Jalur 2: batch (seperti Download Playlist -> ZIP)
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
from core.orchestrator import BatchOrchestrator, DownloadMode
c = YouTubeClient()
tracks = [
    Track(data='1', track_token='j1', title='Glimpse of Us', artist='Joji', duration_ms=222000),
    Track(data='2', track_token='j2', title='Slow Dancing in the Dark', artist='Joji', duration_ms=209000),
]
o = BatchOrchestrator(c, mode=DownloadMode.STREAM_LOCAL)
r = o.run(tracks)
print('batch ->', r.ok, '/', r.total)
"
```

**Kriteria:** kedua jalur memilih channel resmi artisnya (Joji), dan batch
menghasilkan ZIP dengan jumlah file yang benar.

### Yang perlu diperhatikan di jalur batch
- Batch berjalan **serial** (satu per satu) — pastikan strategi ekstraksi
  bertahap tidak menambah waktu berlebihan untuk playlist besar
- Kalau ada lagu yang gagal, **jangan hentikan batch** — lanjut ke lagu berikutnya
  (perilaku ini sudah ada, jangan diubah)

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN hapus** `_OFFICIAL_HINTS` / `_PENALTY_HINTS`.
2. **JANGAN ekstrak penuh semua kandidat** — itu memperlambat 9 menit untuk
   playlist 213 lagu.
3. **JANGAN hapus** penolakan durasi (`MAX_DURATION_DRIFT_S = 25`).
4. **JANGAN paksa** pilih channel kalau tidak ada yang cocok — jatuhkan ke
   perilaku lama.
5. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
6. **JANGAN ubah** bagian lain (metadata, cover, tag ID3, UI).
7. **JANGAN khususkan untuk satu artis** — logikanya harus umum.

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- `info["channel_is_verified"]` ada, nilainya `True` atau `None`
- **`extract_flat: True` TIDAK memberi field itu** — harus ekstraksi penuh
- `Indolirik` & `Lost Panda` punya `channel_is_verified = True` tapi itu channel
  lirik — **verified saja tidak cukup**
- Channel bernama sama dengan artist ada di **92% kasus** (diuji 16 kasus)
- `SEARCH_CANDIDATES = 5`
- `_pick_best()` di `providers/youtube.py` baris ~232
- `score_candidate()` di baris ~115, tanda tangan `(cand, want_seconds)`
- Ekstraksi penuh ~0.5 detik per video
- Kasus yang tidak punya channel cocok: **BTS** (label `HYBE LABELS`),
  **wave to earth** (tidak ada channel resmi)

## YANG BELUM PASTI

- Berapa detik tambahan sebenarnya dengan strategi bertahap — **ukur, jangan asumsi**
- Apakah `channel_is_verified` selalu ada untuk semua video
- Apakah normalisasi nama cukup untuk kasus aksen/karakter non-latin
  (mis. `YOASOBI`, `방탄소년단`)

---

## TEST YANG HARUS TETAP LOLOS

```bash
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=115 FAIL=0
.venv/Scripts/python.exe tests/test_tags.py          # PASS=34 FAIL=0
.venv/Scripts/python.exe tests/test_cover_size.py    # PASS=22 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=51 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=32 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

Tambah test untuk `score_candidate()` yang membuktikan:
- channel bernama sama dengan artist menang atas channel lirik (walau lirik verified)
- artist multi (`"Don Toliver, Doja Cat"`) cocok dengan channel `"Don Toliver"`
- perbedaan huruf besar/kecil tidak menggagalkan pencocokan
- kalau tidak ada yang cocok, skor tetap wajar (tidak crash)

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- **Tabel hasil uji 14 artis** — artist, channel yang dipilih, cocok/tidak
- Berapa dari 14 yang benar (angka nyata)
- **Waktu rata-rata per lagu** sebelum vs sesudah
- Berapa kali ekstraksi penuh terjadi (rata-rata per lagu)
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)

Kalau ada yang tidak bisa dicapai, **bilang apa adanya** — jangan mengarang.


---

## TEMUAN — yt-dlp PUNYA data yang dibutuhkan

Sudah diuji langsung. Setiap video punya field:

```python
info["channel_is_verified"]   # True | None
info["channel"]               # nama channel
info["uploader"]              # biasanya sama
info["uploader_id"]           # @handle
```

**Hasil uji nyata (query "Joji Glimpse of Us"):**

```
verified=True   88rising    Joji - Glimpse of Us
verified=True   Joji        Joji - Glimpse of Us (Official Video)   <-- TARGET
verified=True   Indolirik   Joji – Glimpse of Us | Lirik Terjemahan
verified=None   LatinHype   Joji - Glimpse Of Us
```

### ⚠️ JEBAKAN PENTING — verified saja TIDAK CUKUP

`Indolirik` juga `channel_is_verified = True`, tapi itu **channel lirik
terjemahan**, bukan milik Joji. Kalau cuma pakai badge verified, hasilnya
tetap salah.

**Jadi butuh DUA syarat:**
1. `channel_is_verified == True` → sinyal positif
2. **Nama channel cocok dengan nama artist Spotify** → sinyal yang lebih kuat

Untuk Joji:
```
artist Spotify : "Joji"
channel "Joji"        -> COCOK          ✅ ini yang mau
channel "Indolirik"   -> tidak cocok    ❌ walau verified
channel "88rising"    -> tidak cocok    ⚠️ (label Joji, tapi bukan namanya)
```

---

## MASALAH TEKNIS — `extract_flat` tidak memberi field verified

```
extract_flat = True   -> channel_is_verified = None   (field tidak ada)
ekstraksi penuh       -> channel_is_verified = True
```

Artinya: untuk membaca badge verified, tiap kandidat harus diekstrak
**satu per satu** (~0.5 detik per kandidat).

**Kode sekarang** (`providers/youtube.py`, `_pick_best()`) memakai
`extract_flat: True`:
```python
opts = {
    "quiet": True, "no_warnings": True, "skip_download": True,
    "extract_flat": True,          # <-- tidak ada info verified
    "socket_timeout": 20,
}
```

**Konsekuensi waktu:** kalau semua 5 kandidat diekstrak penuh, tambah ~2.5
detik per lagu. Playlist 213 lagu = +9 menit. **Itu tidak boleh.**

---

## YANG DIMINTA

### 1. Tambah penilaian channel resmi di `score_candidate()`

Fungsi `score_candidate(cand, want_seconds)` di `providers/youtube.py` baris ~115.

**Skor sekarang:**
```python
dur = cand.get("duration") or 0
if want_seconds and dur:
    drift = abs(float(dur) - want_seconds)
    if drift > MAX_DURATION_DRIFT_S:   # 25 detik
        return -1.0
    score = 10.0 - (drift / MAX_DURATION_DRIFT_S) * 5.0
else:
    score = 5.0

blob = _norm(f"{title} {uploader} {channel}")
if any(h in blob for h in _OFFICIAL_HINTS):   # "official audio", "topic", ...
    score += 3.0
if any(h in blob for h in _PENALTY_HINTS):    # "live", "cover", "remix", ...
    score -= 4.0

views = cand.get("view_count") or 0
if views > 1_000_000: score += 1.5
elif views > 100_000: score += 0.8
```

**Tambahan yang diminta:**

```python
# --- channel resmi artis (paling menentukan) ---
artist = <nama artist Spotify untuk track ini>       # perlu diteruskan ke sini
channel = _norm(cand.get("channel") or cand.get("uploader") or "")
artist_n = _norm(artist)

if artist_n and channel:
    # Nama channel mengandung nama artist, atau sebaliknya.
    # Contoh cocok: artist "Joji" vs channel "Joji" / "Joji Official"
    # Contoh TIDAK cocok: "Joji" vs "Indolirik", "LatinHype"
    if artist_n in channel or channel in artist_n:
        score += 6.0          # sinyal terkuat

# --- badge verified ---
if cand.get("channel_is_verified"):
    score += 3.0

# --- channel lirik/terjemahan = penalti ---
# Verified tapi bukan artisnya. Contoh nyata: "Indolirik"
if any(h in channel for h in ("lyrics", "lirik", "terjemahan", "lyric")):
    score -= 3.0
```

**Alasan angkanya:**
- **+6.0 cocok nama artist** — ini sinyal paling kuat dan paling murah
  (tidak butuh request tambahan kalau datanya sudah ada)
- **+3.0 verified** — sinyal bagus, tapi sendirian tidak cukup (lihat jebakan)
- **-3.0 channel lirik** — mencegah Indolirik menang walau verified

**PENTING:** `score_candidate()` sekarang hanya menerima `(cand, want_seconds)`.
Supaya bisa membandingkan nama channel dengan nama artist, **tanda tangannya
harus ditambah parameter artist** (mis. `artist: str = ""`), dan pemanggilnya
(`_pick_best()`) harus meneruskan `track.artist`.

### 2. Ambil `channel_is_verified` tanpa memperlambat drastis

Ini bagian yang butuh pertimbangan. **Jangan ekstrak penuh semua kandidat.**

**Strategi yang diminta — bertahap, berhenti kalau sudah bagus:**

```
Langkah 1: search biasa (extract_flat, cepat) -> dapat 5 kandidat + judul + channel
Langkah 2: hitung skor dasar (durasi, judul, channel vs artist)
Langkah 3: kalau kandidat teratas SUDAH cocok nama artist-nya -> SELESAI
           (tidak perlu ekstraksi penuh, tidak perlu cek verified)
Langkah 4: kalau BELUM ada yang cocok -> ekstrak penuh HANYA kandidat teratas
           (maksimal 2-3 kandidat) untuk membaca channel_is_verified
Langkah 5: pilih yang terbaik
```

**Alasan:** sebagian besar lagu punya video dari channel bernama persis
artist-nya. Untuk kasus itu, **nol request tambahan** — cukup cocokkan nama.
Ekstraksi penuh hanya dipakai kalau nama channel tidak ada yang cocok.

**Batas maksimal:** jangan ekstrak lebih dari **3 kandidat** untuk mencari badge.

### 3. Cache hasil verified

Kalau sebuah video sudah pernah diekstrak penuh, simpan hasilnya
(`video_id -> channel_is_verified`) supaya tidak diekstrak dua kali.

Ikuti pola cache yang sudah ada di `providers/spotify_spclient.py`
(`load_cache` / `save_cache`).

### 4. Jangan regresi yang sudah jalan

`_OFFICIAL_HINTS` dan `_PENALTY_HINTS` yang ada **tetap dipakai**:
```python
_OFFICIAL_HINTS = ("official audio", "official video", "topic", "provided to youtube")
_PENALTY_HINTS = ("live", "cover", "remix", "sped up", "slowed", "nightcore", "reaction", "lyrics video hd")
```
Ini penambahan, bukan penggantian.

---

## VERIFIKASI YANG DIMINTA

### Uji 1 — kasus Joji (yang dilaporkan user)

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
t = Track(data='x', track_token='x', title='Glimpse of Us',
          artist='Joji', duration_ms=222000)
b = c._pick_best('Joji Glimpse of Us', 222)
print('dipilih:', b.get('channel'), '|', b.get('title'))
"
```

**Kriteria:** channel yang dipilih harus **"Joji"** (atau mengandung "Joji"),
**bukan** "Ayli", "Indolirik", "LatinHype", atau channel lirik.

### Uji 2 — pastikan tidak memperlambat

```bash
.venv/Scripts/python.exe -c "
import sys, time; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
for title, artist, dur in [('Glimpse of Us','Joji',222000),
                           ('Slow Dancing in the Dark','Joji',209000),
                           ('Cinnamon Girl','Lana Del Rey',300683)]:
    t = Track(data='x', track_token='x', title=title, artist=artist, duration_ms=dur)
    t0 = time.time()
    b = c._pick_best(f'{artist} {title}', int(dur/1000))
    print(f'{artist} - {title}: {time.time()-t0:.1f}s -> {b.get(\"channel\")}')
"
```

**Kriteria:** rata-rata **< 3 detik per lagu**. Kalau lebih, jelaskan kenapa
dan laporkan angka sebenarnya.

### Uji 3 — jangan rusak lagu yang sudah benar

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
cases = [
    ('Sign of the Times','Harry Styles',341000),
    ('Cinnamon Girl','Lana Del Rey',300683),
    ('Blank Space','Taylor Swift',231826),
]
for title, artist, dur in cases:
    t = Track(data='x', track_token='x', title=title, artist=artist, duration_ms=dur)
    b = c._pick_best(f'{artist} {title}', int(dur/1000))
    print(f'{artist:16s} -> {b.get(\"channel\")!r}  |  {b.get(\"title\")[:40]}')
"
```

**Kriteria:** semua memilih channel resmi artisnya (Harry Styles, Lana Del Rey,
Taylor Swift) — bukan channel lirik/cover.

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN hapus** `_OFFICIAL_HINTS` / `_PENALTY_HINTS` — tetap dipakai.
2. **JANGAN ekstrak penuh semua kandidat** — itu memperlambat 9 menit untuk
   playlist 213 lagu.
3. **JANGAN hapus** penolakan durasi (`MAX_DURATION_DRIFT_S = 25`) — itu yang
   mencegah versi live/remix kepilih.
4. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
5. **JANGAN ubah** bagian lain (metadata, cover, tag ID3, UI).

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- `info["channel_is_verified"]` ada, nilainya `True` atau `None`
- **`extract_flat: True` TIDAK memberi field itu** — harus ekstraksi penuh
- `Indolirik` punya `channel_is_verified = True` tapi itu channel lirik —
  **verified saja tidak cukup**
- Channel resmi selalu ada di hasil search (diuji 3 query, semua ada)
- `SEARCH_CANDIDATES = 5`
- `_pick_best()` di `providers/youtube.py` baris ~232
- `score_candidate()` di baris ~115, tanda tangan `(cand, want_seconds)`
- Ekstraksi penuh ~0.5 detik per video

## YANG BELUM PASTI

- Berapa detik tambahan sebenarnya dengan strategi bertahap — **ukur, jangan asumsi**
- Apakah selalu ada kandidat yang nama channelnya cocok dengan artist.
  Kalau tidak ada sama sekali, fallback-nya harus ke apa? **Jelaskan pilihanmu.**
- Apakah `channel_is_verified` konsisten ada untuk semua video (mungkin ada
  yang tidak punya field sama sekali)

---

## TEST YANG HARUS TETAP LOLOS

```bash
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=115 FAIL=0
.venv/Scripts/python.exe tests/test_tags.py          # PASS=34 FAIL=0
.venv/Scripts/python.exe tests/test_cover_size.py    # PASS=22 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=51 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=32 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

Tambah test untuk `score_candidate()` yang membuktikan:
- channel bernama sama dengan artist menang atas channel lirik (walau lirik verified)
- channel verified menang atas yang tidak verified (kalau nama sama-sama tidak cocok)

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- Hasil **Uji 1, 2, 3** di atas (channel apa yang dipilih untuk tiap kasus)
- **Waktu rata-rata per lagu** sebelum vs sesudah (angka nyata)
- Berapa kali ekstraksi penuh terjadi (rata-rata per lagu)
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)

Kalau ada yang tidak bisa dicapai, **bilang apa adanya** — jangan mengarang.
