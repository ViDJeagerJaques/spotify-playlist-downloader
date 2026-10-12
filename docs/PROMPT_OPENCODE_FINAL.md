# Prompt untuk OpenCode — Cover Playlist Header + Tabel Lagu

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## KONTEKS

Dua hal yang dikerjakan dalam satu prompt:

1. **Cover playlist** di header Home (sekarang salah — pakai cover lagu pertama)
2. **UI tabel** untuk halaman Download Lagu (user mau layout kolom kayak Spotify)

---

# BAGIAN 1 — Cover Playlist di Header Home

## Masalah

Header Home menampilkan **cover album lagu pertama**, bukan **cover playlist** milik user.

**Contoh nyata** (playlist "Dupe", 213 lagu, milik `David-Atha`):
```
Sekarang tampil : ab67616d0000b273aff4aef671b2510be7c115b3
                  = cover album "Piano Man" (lagu pertama)

Seharusnya      : ab67706c0000da84d1a91a9ff0c47ed829f39874
                  = cover playlist milik user
```

**Dampak:** user melihat cover album orang lain, padahal dia sudah upload
cover playlist sendiri. Spotify menampilkan cover playlist di header — kita harus sama.

**Catatan:** ini efek samping dari perbaikan R1 (cover per-lagu). Dulu semua lagu
mewarisi cover playlist, jadi `next((t["cover"] for t in tracks ...))` kebetulan
menghasilkan cover playlist. Sekarang tiap lagu punya cover album sendiri,
jadi baris itu mengambil cover lagu pertama.

## Akar masalah — cover playlist dibuang di tengah jalan

Cover playlist **sudah diambil** tapi tidak pernah sampai ke UI.

**1. `providers/spotify_embed.py` — sudah mengembalikannya**
```python
return title, tracks, hint, cover, (embed_owner or owner), total_ms
#                         ^^^^^ = cover playlist
```

**2. `providers/spotify_meta.py` — dibuang di sini** (baris ~429):
```python
title, tracks, hint, _cover, owner, total_ms = embed_tracks_complete(...)
#                      ^^^^^^ DIBUANG
if tracks:
    self.last_owner = owner
    self.last_total_duration_ms = total_ms
    return title, tracks, hint
```

**3. `providers/youtube.py` — hanya meneruskan owner & durasi**

**4. `app.py` — mengambil cover lagu pertama:**
```python
def _render_playlist_header(view: dict, tracks: list) -> None:
    cover = next((t["cover"] for t in tracks if t.get("cover")), "")
```

## Perbaikan

### 1. `providers/spotify_meta.py`
Simpan cover playlist, jangan dibuang:
```python
title, tracks, hint, cover, owner, total_ms = embed_tracks_complete(...)
if tracks:
    self.last_owner = owner
    self.last_total_duration_ms = total_ms
    self.last_playlist_cover = cover      # <-- BARU
    return title, tracks, hint
```
Inisialisasi `self.last_playlist_cover = ""` di `__init__` (seperti `last_owner`).

**Catatan:** di jalur OAuth (`_playlist_tracks_user`) juga set nilainya —
cover playlist bisa diambil dari `images` di respons `/playlists/{id}`.
Kalau tidak tersedia, biarkan `""`.

### 2. `providers/youtube.py`
Teruskan ke UI:
```python
self.last_playlist_cover = getattr(meta, "last_playlist_cover", "")
```

### 3. `app.py` — `_load_playlist()`
Simpan ke `view`:
```python
view["playlist_cover"] = getattr(provider, "last_playlist_cover", "")
```
Letakkan dekat `view["owner"] = owner`.

### 4. `app.py` — `_render_playlist_header()`
Pakai cover playlist kalau ada, **fallback** ke cover lagu pertama:
```python
cover = view.get("playlist_cover") or next(
    (t["cover"] for t in tracks if t.get("cover")), "")
```

**Penting:** fallback harus tetap ada. Kalau provider legacy (SpotiDown.co,
SoundLoaders) tidak mengisi `last_playlist_cover`, header harus tetap
menampilkan sesuatu — jangan kosong.

## Persyaratan tampilan

> "ingat jadikan dia kotak gitu bentukan nya ya"

Cover header **harus persegi (square)**.

Sudah ada CSS-nya di `ui/theme.py`:
```css
.nx9-art-img { aspect-ratio: 1/1; overflow: hidden; border-radius: 8px; }
.nx9-art-img img { width: 100% !important; height: 100% !important; object-fit: cover; }
.nx9-art-lg { width: 200px; max-width: 100%; }
```

Dan `_render_playlist_header()` sudah memakainya. **Jangan ubah CSS-nya.**
Cukup pastikan cover playlist juga lewat jalur yang sama.

**Catatan penting:** cover playlist Spotify punya prefix **`ab67706c...`**
(bukan `ab67616d...`). **JANGAN** lewatkan ke `upgrade_cover_url()` — akan 404.
Cover playlist tidak punya versi 640x640; biarkan apa adanya.

## Verifikasi Bagian 1

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from providers.spotify_meta import SpotifyMeta
m = SpotifyMeta()
t, tr, h = m.playlist_tracks('https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH')
pc = getattr(m, 'last_playlist_cover', '')
print('playlist cover :', pc)
print('prefix benar?  :', 'ab67706' in pc)
assert pc, 'cover playlist kosong!'
assert 'ab67706' in pc, 'bukan cover playlist!'
print('OK')
"
```

**Kriteria:**
- `last_playlist_cover` berisi URL dengan prefix `ab67706...`
- Bukan cover album (`ab67616d...`)

Lalu uji **UI**: jalankan Streamlit, load playlist, buka Home —
cover header harus **cover playlist user**, dan tetap **persegi**.

Pastikan juga: cover di **daftar lagu** tetap cover **album** masing-masing
(jangan ikut berubah — itu R1, sudah benar).

---

# BAGIAN 2 — UI Tabel untuk Halaman Download Lagu

## Yang user mau

Layout **tabel kolom** seperti Spotify — bukan list biasa. User bilang:
*"ui nya kek gitu aja bukan sama persis"* — terinspirasi Spotify, bukan njiplak.

## Layout target

```
[ # ] [cover]  Judul lagu          Album              Durasi
               Artist
```

**5 kolom** (tanpa tanggal — user bilang tanggal tidak usah):

| Kolom | Isi | Perilaku |
|---|---|---|
| 1. Nomor | 1, 2, 3... | Kiri, abu-abu kecil |
| 2. Cover | Gambar album persegi kecil (~40px) | Kiri, rounded |
| 3. Judul + Artist | Judul tebal putih, artist di bawahnya lebih kecil abu-abu | Kiri, 2 baris |
| 4. Album | Nama album | Tengah, abu-abu, dipotong `...` kalau panjang |
| 5. Durasi | `5:39` | Rata kanan, abu-abu |

## Detail visual (presisi dari referensi user)

**Hierarki teks:**
- **Judul:** tebal (font-weight 600-700), putih (`#FFFFFF`), satu baris.
  Kalau panjang → dipotong dengan `...` (ellipsis), **tidak membungkus**.
- **Artist:** di bawah judul, lebih kecil (font-size ~13px), abu-abu (`#A1A1AA`).
  Satu baris, dipotong `...` kalau panjang.
- **Album:** abu-abu (`#A1A1AA`), ukuran sedang, dipotong `...` kalau panjang.
- **Durasi:** rata kanan, abu-abu, format `M:SS` (mis. `5:39`), font mono.

**Kolom & alignment:**
- **Nomor:** kiri, abu-abu kecil, lebar tetap (~24px).
- **Cover:** kiri, persegi **40x40 px**, rounded **6-8px**, tanpa border.
- **Judul+Artist:** kiri, 2 baris (judul di atas, artist di bawah).
- **Album:** tengah kolom, abu-abu.
- **Durasi:** rata kanan.

**Baris:**
- **Tinggi seragam** (~56-64px per baris) — teks panjang tidak membungkus,
  selalu satu baris per elemen.
- **Tanpa garis pemisah** antar baris.
- **Spacing vertikal halus** antar baris (~8-12px).
- **Hover:** baris sedikit lebih terang (background `#18181B` → `#1F1F23`)
  atau border subtle — opsional, jangan berlebihan.

**Cover:**
- Persegi, **40x40 px**, rounded **6-8px**.
- Pakai CSS `.nx9-art` / `.nx9-art-sm` yang sudah ada.
- Kalau cover gagal dimuat → placeholder abu-abu persegi (jangan kosong).

## Yang TIDAK usah

- **Kolom tanggal** — user bilang tidak usah
- **Kolom disk** — tidak usah
- **Kolom genre** — tidak usah
- **Kolom label/publisher** — tidak usah

## Syarat teknis

1. **Terapkan di `page_songs()`** — halaman Download Lagu saja.
2. **JANGAN ubah `page_covers()`** — halaman cover tetap galeri (R2, sudah benar).
3. **JANGAN ubah `_render_track_row()`** — masih dipakai halaman lain (backup, dll).
4. Buat fungsi baru, mis. `_render_track_table(n, t, sel, by_id)` atau ubah
   langsung loop di `page_songs()` — pilih yang paling bersih.
5. **Tetap ada:** checkbox pilih, tombol "Unduh" per baris, search/filter,
   paginasi (`_pager`), tombol "Pilih semua", "Bersihkan", dan
   "Download N Lagu Terpilih → ZIP".
6. **Cover persegi** — pakai `.nx9-art` / `.nx9-art-sm` yang sudah ada.
7. **Jangan tambah request baru** — semua data sudah ada di `Track`.

## Data yang tersedia per lagu

```python
t["id"]        # track id
t["title"]     # judul
t["artist"]    # artist (sudah dibersihkan dari \xa0)
t["album"]     # nama album (dari spclient metadata)
t["cover"]     # URL cover album 640x640
t["duration"]  # "M:SS" (sudah diformat)
```

## Verifikasi Bagian 2

Render halaman Download Lagu, pastikan:
- **5 kolom** sejajar (nomor, cover, judul+artist, album, durasi)
- Judul & album **dipotong** kalau panjang (bukan membungkus)
- Cover **persegi**
- Checkbox + tombol "Unduh" per baris masih jalan
- Search + pilih semua + ZIP masih jalan
- **Halaman cover tidak berubah** (tetap galeri)

---

# URUTAN PENGERJAAN

```
1. Bagian 1 — cover playlist header
2. Bagian 2 — tabel lagu
```

Test tiap selesai satu bagian.

---

# YANG TIDAK BOLEH DIUBAH

1. **JANGAN ubah** cover di daftar lagu — harus tetap cover album per lagu (R1).
2. **JANGAN** lewatkan cover playlist ke `upgrade_cover_url()` — akan 404.
3. **JANGAN hapus fallback** — provider legacy harus tetap jalan.
4. **JANGAN ubah CSS** `nx9-art` — sudah benar.
5. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
6. **JANGAN** tambah request baru — semua data sudah ada.
7. **JANGAN ubah** `page_covers()` — tetap galeri.
8. **JANGAN ubah** halaman lain (backup, settings, dll).

---

# YANG SUDAH PASTI (jangan ubah asumsinya)

- `embed_tracks_complete()` sudah mengembalikan cover playlist (nilai ke-4)
- `spotify_meta.py` membuangnya ke variabel `_cover` (baris ~429)
- Cover playlist prefix `ab67706c...`; cover album prefix `ab67616d...`
- CSS `.nx9-art-img` + `.nx9-art-lg` + `.nx9-art-sm` sudah ada
- Header sekarang memakai `next((t["cover"] for t in tracks ...))`
- `Track` sudah punya `album`, `thumbnail`, `duration_ms`
- `artist` sudah dibersihkan dari `\xa0` (fungsi `clean_artists()` di `tags.py`)

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
.venv/Scripts/python.exe tests/test_theme.py         # PASS=51 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=91 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

Tambah test: pastikan `last_playlist_cover` terisi dan cover lagu per-lagu
**tidak berubah**.

---

# LAPORAN YANG DIMINTA

- File apa yang diubah
- URL cover playlist yang didapat (tempel URL-nya)
- Bukti cover lagu di daftar **tidak berubah** (cover unik tetap banyak)
- Screenshot atau deskripsi halaman Download Lagu setelah jadi tabel
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)
