# Prompt untuk OpenCode — Cover Playlist di Header Home

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## MASALAH

Header di halaman Home menampilkan **cover album lagu pertama**, bukan
**cover playlist** milik user.

**Contoh nyata** (playlist user "Dupe", 213 lagu, milik `David-Atha`):
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

---

## AKAR MASALAH — cover playlist dibuang di tengah jalan

Cover playlist **sudah diambil** tapi tidak pernah sampai ke UI.

**1. `providers/spotify_embed.py` — sudah mengembalikannya**

`embed_tracks_complete()` mengembalikan 6 nilai:
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
Nilai `cover` masuk ke `_cover` lalu tidak dipakai lagi.

**3. `providers/youtube.py` — hanya meneruskan owner & durasi:**
```python
self.last_owner = getattr(meta, "last_owner", "")
self.last_total_duration_ms = getattr(meta, "last_total_duration_ms", 0)
```

**4. `app.py` — mengambil cover lagu pertama:**
```python
def _render_playlist_header(view: dict, tracks: list) -> None:
    cover = next((t["cover"] for t in tracks if t.get("cover")), "")
```

---

## PERBAIKAN YANG DIMINTA

Teruskan **cover playlist** dari provider sampai ke UI, lalu pakai itu di header.

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
Kalau tidak tersedia, biarkan `""` (fallback ke perilaku sekarang).

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
Letakkan dekat `view["owner"] = owner` supaya konsisten.

### 4. `app.py` — `_render_playlist_header()`
Pakai cover playlist kalau ada, **fallback** ke cover lagu pertama kalau tidak:
```python
cover = view.get("playlist_cover") or next(
    (t["cover"] for t in tracks if t.get("cover")), "")
```

**Penting:** fallback harus tetap ada. Kalau provider legacy (SpotiDown.co,
SoundLoaders) tidak mengisi `last_playlist_cover`, header harus tetap
menampilkan sesuatu — jangan kosong.

---

## PERSYARATAN TAMPILAN (dari user)

> "ingat jadikan dia kotak gitu bentukan nya ya"

Cover header **harus persegi (square)**.

Sudah ada CSS-nya di `ui/theme.py`:
```css
.nx9-art-img { aspect-ratio: 1/1; overflow: hidden; border-radius: 8px; }
.nx9-art-img img { width: 100% !important; height: 100% !important; object-fit: cover; }
.nx9-art-lg { width: 200px; max-width: 100%; }
```

Dan `_render_playlist_header()` sudah memakainya:
```python
st.markdown(
    f'<div class="nx9-art-img nx9-art-lg">'
    f'<img src="{html.escape(cover, quote=True)}" alt=""></div>',
    unsafe_allow_html=True,
)
```

**Jangan ubah CSS-nya.** Cukup pastikan cover playlist juga lewat jalur yang sama,
supaya tetap persegi dan ter-crop rapi.

**Catatan penting:** cover playlist Spotify punya prefix **`ab67706c...`**
(bukan `ab67616d...`). **JANGAN** lewatkan ke `upgrade_cover_url()` — akan 404.
Cover playlist tidak punya versi 640x640; biarkan apa adanya.

---

## VERIFIKASI YANG DIMINTA

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, '.')
from providers.spotify_meta import SpotifyMeta
m = SpotifyMeta()
t, tr, h = m.playlist_tracks('https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH')
pc = getattr(m, 'last_playlist_cover', '')
print('playlist cover :', pc)
print('prefix benar?  :', 'ab67706' in pc)
print('lagu           :', len(tr))
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

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN ubah** cover di daftar lagu — harus tetap cover album per lagu (R1).
2. **JANGAN** lewatkan cover playlist ke `upgrade_cover_url()` — akan 404.
3. **JANGAN hapus fallback** — provider legacy harus tetap jalan.
4. **JANGAN ubah CSS** `nx9-art` — sudah benar.
5. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
6. **JANGAN** tambah request baru — cover playlist sudah diambil, cukup diteruskan.

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- `embed_tracks_complete()` sudah mengembalikan cover playlist (nilai ke-4)
- `spotify_meta.py` membuangnya ke variabel `_cover` (baris ~429)
- Cover playlist prefix `ab67706c...`; cover album prefix `ab67616d...`
- CSS `.nx9-art-img` + `.nx9-art-lg` sudah ada dan sudah dipakai header
- Header sekarang memakai `next((t["cover"] for t in tracks ...))`

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

Tambah test: pastikan `last_playlist_cover` terisi dan cover lagu per-lagu
**tidak berubah**.

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- URL cover playlist yang didapat (tempel URL-nya)
- Bukti cover lagu di daftar **tidak berubah** (cover unik tetap banyak)
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)
