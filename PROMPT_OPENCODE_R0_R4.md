# Prompt untuk OpenCode — R0–R4 (Revisi + Tag ID3)

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Semua modifikasi file yang SUDAH ADA.

---

## KONTEKS

Provider YouTube + spclient sudah jalan. Playlist 213 lagu terbaca 213 tanpa login.
335 test lolos (10 file test). Sudah ada `providers/spotify_spclient.py`.

Ada **4 item** dari user. Kerjakan satu per satu, test tiap selesai satu.

---

# 🔴 R1 — Cover 100 lagu pertama SALAH (semua lagu satu gambar)

**Status: bug nyata, terbukti.**

**Gejala:** semua cover menampilkan gambar yang sama untuk setiap lagu.

**Bukti (playlist user `5jPG8GymyNv0lX6aSv5dE3`, 4 lagu):**
```
cover ada   : 4/4
cover unik  : 1        <-- SEMUA SAMA
```

Keempat lagu memakai cover PLAYLIST:
```
Blank Space         -> ...6c0000da842996560409e70cc3029d221b
Cinnamon Girl       -> ...6c0000da842996560409e70cc3029d221b
Style               -> ...6c0000da842996560409e70cc3029d221b
Snow On The Beach   -> ...6c0000da842996560409e70cc3029d221b
```

Cover yang SEHARUSNYA (dari `/embed/track`, sudah diverifikasi):
```
Blank Space         -> ab67616d00001e0252b2a3824413eefe9e33817a
Cinnamon Girl       -> ab67616d00001e02879e9318cb9f4e05ee552ac9
Style               -> ab67616d00001e0252b2a3824413eefe9e33817a
Snow On The Beach   -> ab67616d00001e02fa747621a53c8e2cc436dee0
```

**Akar masalah — hanya separuh jalur diperbaiki:**
```
Jalur embed (100 lagu pertama)  -> 1 cover playlist untuk SEMUA   <-- BUG
Jalur spclient (lagu >100)      -> cover per lagu (BENAR)
```

Di `providers/spotify_embed.py`, `embed_tracks_complete()`:
- Langkah 1 membangun 100 lagu pertama dengan
  `tracks_from_entity(entity, cover_for=cover)` — satu cover untuk semua
- Langkah 3 hanya mengambil `cached_track_details(missing)` untuk lagu yang
  **tidak ada** di 100 pertama (`missing = [t for t in ids if t not in by_id]`)

Jadi lagu 100 pertama tidak pernah lewat `track_details()`.

**Bug ini tersembunyi saat diuji dengan playlist 213 lagu** karena mayoritas lagu
lewat jalur benar. Harus diuji dengan playlist KECIL (< 100 lagu).

**Perbaikan:** ambil metadata per-lagu untuk **SEMUA** lagu:
```python
# SEMUA lagu harus lewat track_details supaya cover + artist + album benar.
details = cached_track_details(ids, progress=progress)
```
- Kalau `track_details` gagal untuk satu lagu → pakai data embed sebagai fallback
- Ukur dan laporkan waktunya (playlist 213 lagu sebelumnya 1.3s dengan cache)

**Verifikasi wajib:**
```bash
.venv/Scripts/python.exe -c "
from providers.spotify_meta import SpotifyMeta
m = SpotifyMeta()
t, tr, h = m.playlist_tracks('https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3')
covers = [x.thumbnail for x in tr]
print('lagu:', len(tr), '| cover unik:', len(set(covers)))
print('BENAR?', len(set(covers)) == len(covers))
"
```
**Kriteria:** `cover unik == jumlah lagu` untuk playlist 4 lagu.
Untuk playlist 213 lagu, cover unik harus jauh lebih banyak dari 98.

**Tambah test** yang GAGAL kalau cover semua sama (pakai fixture, bukan jaringan).

---

# 🔴 R4 — Tag ID3 + cover belum ditulis ke MP3

**Status: BELUM DIKERJAKAN.**

## Latar — hasil intervensi (semua sudah diverifikasi)

User membandingkan file hasil app kita dengan file dari SpotiDown. Punya SpotiDown
punya tag album + label + cover; punya kita tidak. User menduga SpotiDown ambil
dari Spotify langsung. **Ternyata tidak.**

**Bukti 1 — korelasi audio (file asli user di `E:\NITIP\compare song`):**
```
SpotiDown "2. Cinnamon Girl.mp3"     vs  kita "Lana Del Rey - Cinnamon Girl.mp3"
korelasi: 0.9749     durasi: 296.15s vs 299.94s

UJI KONTROL (lagu beda):  0.01 / -0.01 / 0.009 / -0.007
```
Lagu beda ~0.01, lagu sama 0.97 → angkanya bermakna, rekaman yang sama.

**Bukti 2 — durasi membuktikan sumbernya YouTube, bukan Spotify:**
```
Durasi asli Spotify   : 300.68s
File SpotiDown        : 296.15s   <-- tidak cocok
Upload YouTube "catblaze" : 296.0s   <-- COCOK
Upload YouTube "Lana Del Rey" (yang kita pakai) : 301.0s
```
**Bukti 3 — file SpotiDown lain masih menyimpan link YouTube:**
```
E:\Download(C)\Harry Styles - Sign of the Times.mp3
   -> "youtube.com/watch?v=qN4ooNx77u0"  ADA di dalam file
```

**Kesimpulan:** SpotiDown = YouTube + tag Spotify. Yang membuat hasilnya tampak
"resmi" **hanya tag + cover**.

**Temuan tambahan:** SpotiDown punya 2 pipeline. Yang dari playlist (ZIP) punya
cover tapi 121 kbps; yang satuan 192 kbps tanpa cover. Punya kita 192 kbps —
**lebih bagus** dari pipeline playlist mereka.

## Kondisi kode sekarang

`providers/youtube.py`, `_download()` baris ~281:
```python
"postprocessors": [
    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
    {"key": "FFmpegMetadata"},   # <-- salin tag DARI YouTube (sumber masalah)
],
```
`FFmpegMetadata` menyalin tag video YouTube, jadi `artist` = nama channel
(mis. "David Dean Burkhart"), bukan penyanyi aslinya.

**Contoh nyata file kita:**
```
artist      : "David Dean Burkhart"        <-- nama channel YouTube
album       : (kosong)
cover       : (tidak ada)
comment     : https://www.youtube.com/watch?v=tQz93eTCpSA
title       : "Lana Del Rey - Cinnamon Girl"   <-- masih ada embel-embel
```

**Target (seperti SpotiDown, atau lebih baik):**
```
title  : "Cinnamon Girl"
artist : "Lana Del Rey"
album  : "Norman Fucking Rockwell!"
date   : "2019"
cover  : (gambar disisipkan)
```

## SUMBER DATA — semua sudah diverifikasi

### Album + label + tanggal: `spclient` metadata (TANPA rate limit)

**Penting — butuh konversi ID.** Spotify ID adalah base62 dari 128-bit GID;
API internal ini butuh **hex GID**.

```python
B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

def b62_to_hex(sid: str) -> str:
    """Spotify base62 ID -> 32-char hex GID."""
    n = 0
    for ch in sid:
        n = n * 62 + B62.index(ch)
    return f"{n:032x}"
```

```
GET https://spclient.wg.spotify.com/metadata/4/track/{hex_gid}
Authorization: Bearer <anon token dari halaman embed playlist>
app-platform: WebPlayer
Origin: https://open.spotify.com
Referer: https://open.spotify.com/
```

Contoh: `2mdEsXPu8ZmkHRRtAdC09e` → `4d7d424d2bc148da9d17580f110bd31c`

Respons (HTTP 200, terverifikasi):
```json
{
  "name": "Cinnamon Girl",
  "album": {
    "gid": "c3c545a519854bc6b2b4195801948e18",
    "name": "Norman Fucking Rockwell!",
    "label": "Polydor Records",
    "date": {"year": 2019, "month": 8, "day": 30},
    "artist": [{"gid": "...", "name": "Lana Del Rey"}],
    "type": "ALBUM"
  },
  "artist": [{"gid": "...", "name": "Lana Del Rey"}],
  "number": 5,            // nomor track di album
  "disc_number": 1,
  "duration": 300683,
  "popularity": 78,
  "licensor": "..."
}
```

**Ini sumber yang dipakai** — kasih album, label, tahun, nomor track, disc.
**Tanpa rate limit.**

### Perbandingan sumber (semua sudah diuji)

| Sumber | title | artist | album | label | cover | rate limit |
|---|---|---|---|---|---|---|
| `/embed/track/{id}` | ✅ | ✅ | ❌ | ❌ | ❌ | bebas |
| oEmbed | ✅ | ❌ | ❌ | ❌ | ✅ | bebas |
| **spclient metadata** | ✅ | ✅ | ✅ | ✅ | ❌ | **bebas** |
| `api.spotify.com` | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ kena 429 |

Catatan: `/embed/track` punya `releaseDate` tapi **tidak** punya nama album.

**Catatan `api.spotify.com`:** sempat kena `429 QUOTA_EXCEEDED` berkepanjangan,
tapi sudah pulih (uji 100 request paralel 8 → 0 error, 4.2s). Tetap **prioritaskan
spclient** karena tidak dibatasi.

### Cover: oEmbed (sudah dipakai di kode)

```
GET https://open.spotify.com/oembed?url=https://open.spotify.com/track/{id}&format=json
-> thumbnail_url: https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02...
```
Sudah dibandingkan: hash-nya **sama persis** dengan cover dari Web API.

## Yang harus dikerjakan

1. **Perluas `track_details()`** di `providers/spotify_spclient.py` supaya juga
   mengembalikan: `album`, `label`, `year`, `track_number`, `disc_number`.
   Tambah fungsi `b62_to_hex()` + pemanggil spclient metadata.
2. **Tambah field di `Track`** (`providers/base.py`) kalau perlu:
   `album` sudah ada. Tambah `year`, `track_number`, `label` (opsional).
3. **Tulis tag ke MP3 setelah download.** Timpa tag YouTube.

| Tag ID3 | Nilai |
|---|---|
| `TIT2` (title) | `Track.title` |
| `TPE1` (artist) | `Track.artist` — **bersihkan dulu** (lihat di bawah) |
| `TALB` (album) | dari spclient |
| `TDRC`/`date` | tahun dari spclient |
| `TRCK` (track) | nomor track |
| `TPUB` (label) | label dari spclient |
| `APIC` | cover dari oEmbed |

4. **Bersihkan `artist`** sebelum ditulis:
   - Buang karakter `\xa0` (non-breaking space) — **terbukti ada** di data kita:
     `'Taylor Swift,\xa0Lana Del Rey'`
   - Pakai pemisah `, ` untuk artist banyak
   - **JANGAN** ubah judul Spotify (biarkan `(feat. ...)` apa adanya)

5. **Syarat penting:**
   - **JANGAN ubah audio** — hanya tag + cover (`-c copy` atau mutagen mode tag)
   - Cover gagal diunduh → tetap tulis tag teks, jangan gagalkan lagu
   - Tag kosong → lewati, jangan tulis string kosong
   - Cache: file yang sudah ditandai jangan diproses ulang
   - Pilih lokasi: di `_download()` provider YouTube (setelah ffmpeg), ATAU di
     `core/orchestrator.py` saat staging — pilih satu, jelaskan alasannya

6. **Pilihan alat:**
   - `mutagen` — **belum terinstall**. Tambah ke `requirements.txt` kalau dipakai.
     Lebih bersih untuk ID3 + APIC (embedded cover).
   - `ffmpeg` — sudah ada (v9.0.1). `ffmpeg -i in.mp3 -i cover.jpg -map 0:a -map 1
     -c copy -id3v2_version 3 ...`
   Pilih satu, jelaskan alasannya.

**Verifikasi wajib:**
```bash
.venv/Scripts/python.exe -c "
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
t = Track(data='x', track_token='2mdEsXPu8ZmkHRRtAdC09e',
          title='Cinnamon Girl', artist='Lana Del Rey',
          album='Norman Fucking Rockwell!', duration_ms=300683,
          thumbnail='https://i.scdn.co/image/ab67616d00001e02879e9318cb9f4e05ee552ac9')
print(c.resolve_track(t))
"
```
Lalu:
```bash
ffprobe -v quiet -print_format json -show_format -show_streams <file>
```
**Kriteria:**
- `artist` = **"Lana Del Rey"** (bukan nama channel YouTube)
- `album` = `"Norman Fucking Rockwell!"`
- `date` = `2019`
- ada stream `video` (embedded cover) atau tag `APIC`
- `title` = `"Cinnamon Girl"`
- bitrate tetap 192 kbps (audio tidak disentuh)

---

# 🟡 R2 (= revisi "no 2" dari user) — Halaman Download Cover harus GALERI, bukan list

**Status: belum dikerjakan. Salah paham sebelumnya — ini bukan "sudah benar".**

## Yang user mau

```
Download Lagu   ->  list memanjang ke bawah   (SUDAH BENAR, jangan diubah)
Download Cover  ->  GALERI kotak-kotak        (sekarang list — HARUS DIBALIKIN)
```

Cover lebih enak dilihat sebagai galeri. Dulu (saat masih pakai provider SpotiDown)
halaman cover memang galeri kotak-kotak, dan user suka itu.

## Akar masalah

Revisi #5 ("list vertikal seperti Spotify") **hanya ditujukan untuk halaman
Download Lagu**. Tapi `_render_track_row()` dipakai di DUA halaman:

```python
# app.py
def page_songs():   ... _render_track_row(n, t, sel, by_id, kind="song")
def page_covers():  ... _render_track_row(n, t, sel, by_id, kind="cover")
```

Jadi halaman cover ikut berubah jadi list tanpa sengaja.

## Perbaikan yang diminta

Buat `page_covers()` **kembali ke galeri grid**, sementara `page_songs()` tetap list.

Layout tiap kartu:
```
┌──────────────┐
│   [✓ pilih]  │
│   ┌────────┐ │
│   │ COVER  │ │   <- kotak, square (aspect-ratio 1/1)
│   │ 1:1    │ │
│   └────────┘ │
│  Judul lagu  │
│  Artist      │
│  [Unduh]     │
└──────────────┘
```

Syarat:
- Cover **square** — pakai CSS `.nx9-art` yang sudah ada di `ui/theme.py`
  (jangan bikin CSS baru)
- Ukuran kotak ~150–200 px, beberapa kolom per baris (mis. 4–5 kolom)
- **Tetap ada**: search/filter, "Pilih semua", "Bersihkan", tombol
  "Download N Cover Terpilih → ZIP", dan paginasi (`_pager`)
- Checkbox per kartu untuk pilih banyak
- Tombol "Unduh cover" per kartu (fungsi `_download_one_cover` sudah ada)
- **JANGAN ubah** `page_songs()` — biarkan tetap list
- Jangan hapus `_render_track_row()` — masih dipakai halaman lagu

**Catatan:** `_grid_select_state()` masih ada di kode (namanya dari era grid) —
pakai itu untuk state pilihan di galeri.

## Verifikasi

Render halaman cover, pastikan:
- beberapa cover tampil **sejajar dalam satu baris** (bukan satu per baris)
- cover **persegi** (bukan lonjong)
- search + pilih semua + ZIP masih jalan

Halaman Download Lagu harus **tetap list memanjang ke bawah** (jangan ikut berubah).

---

# 🟡 R3 (= revisi "no 3" dari user) — Cover playlist di Home tidak square

**Status: bug nyata.**

CSS sudah ada di `ui/theme.py` (`.nx9-art`, `aspect-ratio:1/1`, `object-fit:cover`)
dan sudah di-inject lewat `inject_theme()` (baris ~308).

**Tapi kelas `.nx9-art` TIDAK PERNAH dipakai.** Di `app.py`:
```
baris ~803 : st.image(cover, width=200)   # komentar bilang "square via CSS"
baris ~1022: st.image(url, width=size)    # _square_cover(), tanpa kelas
```
Komentarnya menyesatkan.

**Perbaikan:** pakai kelas yang sudah ada.
```python
st.markdown(f'<div class="nx9-art-img"><img src="{html.escape(url)}" alt=""></div>',
            unsafe_allow_html=True)
```
Syarat:
- Escape URL (`html.escape`)
- Terapkan di **dua tempat**: `_render_playlist_header()` dan `_square_cover()`
- Perbaiki komentar yang menyesatkan
- Uji dulu cara paling andal untuk versi Streamlit yang dipakai — **jangan asumsi**

---

# 🟡 R0 — Owner tampil hash, bukan nama

**Status: bug nyata.**

```
UI sekarang  : "oleh 31siy2jiykpjmhgercjuh2j2yrbe"
Seharusnya   : "oleh David-Atha"
```

`playlist_track_ids()` mengembalikan `ownerUsername` (hash). Halaman embed punya
nama yang benar di `entity["subtitle"]`.

Di `providers/spotify_embed.py` baris ~318:
```python
return title, tracks, hint, cover, (owner or embed_owner), total_ms
```
Karena `owner` (hash) tidak kosong, `embed_owner` tidak pernah dipakai.

**Perbaikan:** balik prioritasnya.
```python
return title, tracks, hint, cover, (embed_owner or owner), total_ms
```
**Catatan:** ini kesalahan saya di prompt sebelumnya — saya bilang `ownerUsername`
"lebih akurat". Ternyata itu hash.

**Verifikasi:**
```bash
.venv/Scripts/python.exe -c "
from providers.spotify_meta import SpotifyMeta
m = SpotifyMeta()
m.playlist_tracks('https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH')
print('owner:', repr(m.last_owner))
"
```
**Kriteria:** `'David-Atha'`, bukan hash.

---

# URUTAN PENGERJAAN

```
1. R1  cover per-lagu        <- user paling terganggu
2. R4  tag ID3 + cover       <- bikin hasil kita setara SpotiDown
3. R2  halaman cover -> galeri
4. R3  cover square
5. R0  owner nama            <- 1 baris
```

Test tiap selesai satu. Jangan semua sekaligus.

---

# RINGKASAN ITEM

| # | Item | Status |
|---|---|---|
| R1 | Cover 100 pertama salah (semua lagu satu gambar) | bug nyata |
| R4 | Tag ID3 + cover belum ditulis ke MP3 | belum dikerjakan |
| R2 | Halaman Download Cover harus galeri (sekarang list) | salah paham, belum dikerjakan |
| R3 | Cover playlist di Home tidak square | bug nyata |
| R0 | Owner tampil hash, bukan nama | bug nyata |

**Catatan penting:** revisi #5 ("list memanjang ke bawah") hanya untuk halaman
**Download Lagu**. Halaman **Download Cover** harus **galeri kotak-kotak**.

---

# TEST YANG HARUS TETAP LOLOS

```bash
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_covers.py        # PASS=34 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=32 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=45 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=58 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
.venv/Scripts/python.exe -c "import app; print('OK')"
```

Kalau ada test lama gagal karena perubahan yang memang disengaja, update test-nya
dan **jelaskan di laporan**.

---

# BATASAN

1. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
2. **JANGAN ubah audio** saat menulis tag — hanya tag + cover.
3. **JANGAN hapus** OAuth, SpotiDown, SoundLoaders.
4. **JANGAN pakai `api.spotify.com` untuk playlist** kalau bisa dihindari —
   prioritaskan spclient (tanpa rate limit).
5. **JANGAN hardcode credential.** Hanya `.env`.
6. **JANGAN ngarang angka.** Kalau belum diuji, bilang belum diuji.
7. **JANGAN hapus jejak YouTube** kalau tidak perlu — bukan masalah.

---

# LAPORAN YANG DIMINTA

Per poin: file apa yang diubah, apa yang diubah, test apa yang dijalankan +
hasilnya (angka nyata), dan apa yang **belum** selesai (jujur).

Khusus R1: laporkan **jumlah cover unik** sebelum vs sesudah.
Khusus R4: lampirkan hasil `ffprobe` file jadi.

---

# YANG SUDAH PASTI (jangan ubah asumsinya)

- Halaman embed hanya memberi 1 gambar untuk semua lagu → wajib lewat
  `/embed/track` + oEmbed supaya cover per-lagu benar
- `/embed/track/{id}`: punya title/artists/releaseDate, **TIDAK** punya album,
  `coverArt` null
- oEmbed: punya `thumbnail_url` (identik dengan cover Web API), **TIDAK** punya album
- **spclient metadata butuh hex GID**, bukan base62 → konversi dulu
- spclient metadata: punya album + label + tahun + nomor track, **tanpa rate limit**
- `artist` di data kita bisa mengandung `\xa0` — harus dibersihkan
- CSS `.nx9-art` sudah ada di `ui/theme.py` tapi belum dipakai
- `Track` sudah punya field `album` dan `thumbnail`
- `mutagen` belum terinstall; `ffmpeg` v9.0.1 sudah ada
- `FFmpegMetadata` menyalin tag dari YouTube (sumber masalah R4)
- SpotiDown memakai YouTube; yang beda hanya tag + cover

# YANG BELUM PASTI

- Apakah menandai SEMUA lagu (bukan cuma >100) memperlambat playlist besar —
  **ukur dan laporkan**
- Cara paling andal memasang kelas CSS ke `st.image` di versi Streamlit ini —
  **uji dulu**
- Apakah semua track punya data di spclient metadata (mungkin ada yang kosong)

Kalau ada yang tidak jelas — **tanya dulu**, jangan ngarang.
