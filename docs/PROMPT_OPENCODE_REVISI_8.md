# Prompt untuk OpenCode — Revisi 8 Poin

> Copy seluruh isi file ini, paste ke OpenCode.
> **PENTING: JANGAN bikin dari awal.** Semua ini modifikasi file yang SUDAH ADA.

---

## KONTEKS

Provider YouTube (yt-dlp) sudah jalan dan sudah di-push ke GitHub (commit `dc9d12d`).
Test semua lolos: 25 smoke + 27 youtube + 35 embed + 42 spotidown + app UI.

Sekarang ada **8 revisi dari user**. Kerjakan **satu per satu**, test tiap selesai satu.

**File yang akan disentuh:**
```
app.py                        ← halaman UI (paling banyak berubah)
providers/spotify_embed.py    ← baca playlist
providers/spotify_meta.py     ← Spotify API client
providers/youtube.py          ← provider audio
core/orchestrator.py          ← batch + ZIP
ui/data.py                    ← BATCH_LIMIT, chunk_parts, export
ui/i18n.py                    ← teks id/en
.streamlit/config.toml        ← BARU (tema)
tests/                        ← tambah test
```

---

# 🔴 PRIORITAS 1 — BUG FATAL

## #6 — Download di halaman "Download Lagu" GAGAL TOTAL

**Gejala dari user:**
```
Gagal: InvalidSchema: No connection adapters were found for
'C:\Users\USER\AppData\Local\Temp\spotify_yt_cache\1u8c2t2Cy7UBoG4ArRcF5g.mp3'
```

**Akar masalah (sudah didiagnosis, jangan cari lagi):**

`app.py` baris ~1117:
```python
def _fetch_bytes(mp3_url: str) -> bytes:
    if mp3_url.startswith("mock://"):
        return _mock_mp3_bytes()
    resp = requests.get(mp3_url, timeout=60, allow_redirects=True)   # ← BUG
    resp.raise_for_status()
    return resp.content
```

Provider YouTube **tidak mengembalikan URL**. Dia mengembalikan **path file lokal** karena search + download + ffmpeg sudah selesai di dalam `resolve_track()`.

`requests.get()` tidak bisa membaca path Windows → `InvalidSchema`.

**Yang bikin nyesek:** `core/orchestrator.py` **sudah punya solusinya** — class `LocalCopyFetcher` (baris ~179) yang tahu cara menangani file lokal. Tapi halaman "Download Lagu" memanggil `_fetch_bytes()` sendiri lewat `_resolve_one()` (baris ~1085), **tidak lewat orchestrator**.

**Perbaikan yang diminta:**

Buat `_fetch_bytes()` sadar bahwa inputnya bisa dua jenis:

```python
def _fetch_bytes(mp3_url: str) -> bytes:
    # mock (offline test)
    if mp3_url.startswith("mock://"):
        return _mock_mp3_bytes()

    # Provider yang sudah menghasilkan file jadi di disk (YouTube).
    # Deteksi: path lokal yang ada di filesystem.
    p = Path(mp3_url)
    if p.exists() and p.is_file():
        data = p.read_bytes()
        if not data:
            raise ServiceError(f"file kosong: {p}")
        return data

    # Provider yang masih mengembalikan URL (SpotiDown, SoundLoaders, dll).
    resp = requests.get(mp3_url, timeout=60, allow_redirects=True)
    resp.raise_for_status()
    return resp.content
```

**Syarat:**
- Jangan hapus jalur HTTP — provider legacy masih butuh
- `Path(mp3_url)` harus dibungkus try/except (path ilegal bisa melempar di Windows)
- Tambah test: `_fetch_bytes` dengan (a) path lokal valid, (b) path tidak ada, (c) URL mock

**Verifikasi wajib:**
```bash
# resolve_track YouTube mengembalikan path lokal
.venv/Scripts/python.exe -c "
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
t = Track(data='x', title='Sign of the Times', artist='Harry Styles', duration_ms=341000)
r = c.resolve_track(t)
import os; print('returned:', r); print('exists:', os.path.exists(r), '| size:', os.path.getsize(r))
"
```
Lalu di UI: klik **"Unduh 1 lagu"** → harus jadi file MP3, bukan error.

---

# 🔴 PRIORITAS 2 — FITUR HILANG

## #7 — Cover lagu SALAH (semua lagu dapat gambar yang sama)

**Gejala dari user:** cover di halaman Download Lagu & Download Cover tidak sesuai lagunya.

**Akar masalah (sudah didiagnosis):**

Halaman embed Spotify (`open.spotify.com/embed/playlist/{id}`) hanya menyediakan **satu gambar level playlist**. Hasil hitung: 50 lagu → hanya **3 URL gambar** di seluruh halaman (playlist cover + header + varian).

Jadi kode sekarang memakai satu gambar untuk semua lagu.

**Cover yang benar** ada di Spotify CDN, **per album**, dan bisa diambil dari `GET /tracks/{id}`.

**Bukti (sudah diverifikasi):** cover yang SpotiDown.co kirim **identik** dengan `GET /tracks/{id}`:
```
Sign of the Times  → ab67616d0000b2733f8b8a9c71b2bd2f3019940b  (sama)
Who Knows          → ab67616d0000b2732bad6e56e77d5bef0aa3f2dc  (sama)
```

**Status endpoint Spotify (diuji 2026-10-09):**
```
200  GET /tracks/{id}          ← INI YANG DIPAKAI
403  GET /tracks?ids=a,b       ← batch DILARANG
404  GET /playlists/{id}
401  GET /playlists/{id}/items
403  GET /playlists/{id}/tracks
200  GET /albums/{id}
200  GET /albums/{id}/tracks
200  GET /search
```

**Kecepatan (sudah diukur, 20 request):**
```
serial            4.9s   (243 ms/request)
paralel 8 worker  0.9s
→ estimasi 100 lagu: serial 24s, paralel 5s
```

**Perbaikan yang diminta:**

1. Tambah fungsi di `providers/spotify_meta.py` (atau `spotify_embed.py`):
   ```python
   def track_covers(track_ids: list[str], workers: int = 8) -> dict[str, str]:
       """Ambil cover album asli per track via GET /tracks/{id}.
       Paralel 8 worker. Return {track_id: cover_url}. Gagal = skip, jangan crash.
       """
   ```
2. **Cache hasilnya** — lagu yang sama di playlist lain tidak perlu request ulang. Simpan di `CACHE_DIR/cover_cache.json`.
3. Panggil setelah daftar lagu didapat, isi field `thumbnail` per lagu.
4. Batasi `workers` maksimal 8 — jangan agresif, Spotify bisa rate-limit.
5. Kalau `GET /tracks/{id}` gagal (lagu dihapus/region lock) → pakai cover playlist sebagai fallback, jangan kosong.

**Syarat:**
- Kalau Spotify credential belum diisi (`.env` kosong), **jangan crash** — pakai cover playlist, kasih catatan di UI.
- Cover yang ditampilkan di grid/list **dan** yang masuk ke ZIP gambar harus sama-sama benar.
- Tambah test dengan fixture (jangan panggil API asli di unit test).

---

# 🟡 PRIORITAS 3 — BATAS & DATA

## #1 — Batas 100 lagu (user mau lebih)

**Gejala:** playlist 213 lagu hanya terbaca 100.

**Akar:** halaman embed hanya menampilkan 100 item pertama. Bukan batas yt-dlp, bukan batas API.

**Perbaikan yang diminta — tambah jalur OAuth (opsional, tidak wajib):**

1. Tambah mode **OAuth user** di `providers/spotify_meta.py`:
   - Authorization Code flow
   - Scope: `playlist-read-private playlist-read-collaborative`
   - Login sekali lewat browser, simpan **refresh token** di `.env` (`SPOTIFY_REFRESH_TOKEN`)
   - Setelah punya token user, `GET /playlists/{id}/items` bisa di-loop halaman (100/request) → unlimited
2. **Urutan percobaan (jangan dibalik):**
   ```
   refresh token ada?  → API user (unlimited)
   tidak ada?          → embed (cap 100)  ← perilaku sekarang, tetap jalan
   ```
3. UI: kasih opsi/tombol "Hubungkan Spotify (untuk playlist >100 lagu)" + petunjuk cara dapat refresh token.
4. Kalau user tidak mau OAuth, **aplikasi harus tetap jalan** seperti sekarang. Jangan jadikan wajib.

**Syarat:**
- `.env` sudah di `.gitignore` — **jangan pernah** commit credential
- Jangan simpan token di kode, hanya dari `.env`
- Dokumentasikan di README: cara dapat refresh token, apa bedanya

---

## #3 — Home page belum seperti Spotify

**Yang diminta user:**
- Cover **persegi (square)**
- Nama **penyusun playlist** (owner)
- **Total lagu**
- **Total durasi**

**Kabar baik: SEMUA data ini sudah tersedia di halaman embed** (sudah diverifikasi):

```
playlist 'A.....C'   → owner: 'ViD'          tracks: 75   duration: 277 menit
playlist 'Dupe'      → owner: 'David-Atha'   tracks: 100  duration: 377 menit
playlist 'Today's...'→ owner: 'Spotify'      tracks: 50   duration: 165 menit
```

**Cara ambil (di `spotify_embed.py`):**
- Owner → `entity["subtitle"]`
- Total lagu → `len(entity["trackList"])`
- Total durasi → `sum(t["duration"] for t in entity["trackList"])` (satuan ms)
- Cover playlist → `entity["coverArt"]["sources"][0]["url"]`

**Perbaikan yang diminta:**
1. `parse_embed_page()` harus mengembalikan owner + total durasi, bukan hanya daftar lagu
2. `page_home()` tampilkan kartu header:
   - Cover square (gunakan `st.image` dengan lebar tetap, atau CSS `aspect-ratio: 1/1; object-fit: cover`)
   - Nama playlist
   - `oleh {owner}`
   - `{n} lagu`
   - `{durasi}` diformat `1 jam 23 menit` (atau `277 menit` kalau < 1 jam)
3. Tambah helper `format_total_duration(ms)` di `ui/data.py`
4. i18n id/en untuk label barunya

**Syarat:** jangan hapus info yang sudah ada. Ini penambahan.

---

## #4 — Aturan ZIP: ≤30 Full, >30 Part

**Aturan baru (dari user):**
```
jumlah lagu ≤ 30   →  SATU ZIP full
jumlah lagu > 30   →  dipecah jadi Part
```

**Kondisi sekarang:** `ui/data.py` pakai `BATCH_LIMIT = 100` dan `chunk_parts()` memecah per 100.

**Perbaikan yang diminta:**
1. Ubah ambang: **30 lagu** untuk pemisahan Part
2. Ukuran tiap Part — **tetap 30 lagu** (atau buat konstanta `PART_SIZE = 30` yang terpisah dari ambang)
3. Di halaman Download Playlist, tampilkan dengan jelas:
   - `≤30` → "ZIP Full (1 file)"
   - `>30` → "ZIP Part (N bagian, 30 lagu/bagian)"
4. Preview pembagian Part **sebelum** user klik download

**Syarat:**
- Jangan hardcode angka 30 di banyak tempat — pakai satu konstanta
- Update test `smoke.py` yang mengandalkan limit 100
- Nama file Part harus konsisten dan urut

---

# 🟢 PRIORITAS 4 — TAMPILAN

## #2 — Warna & tipografi NX9

**Design token dari user (design MD "NX9 Neural Gateway"):**
```
primary     #A8D055   ← hijau neon (aksen utama)
background  #050F05   ← hitam kehijauan sangat gelap
surface     #18181B
text-primary   #FFFFFF
text-secondary #A1A1AA
border      #27272A
font display/body : Inter
font label/mono   : JetBrains Mono
radius card/control : 8px
radius pill         : 9999px
spacing base 8px, card-padding 24px
```

**Perbaikan yang diminta:**
1. **Buat `.streamlit/config.toml`** (folder `.streamlit/` belum ada):
   ```toml
   [theme]
   primaryColor = "#A8D055"
   backgroundColor = "#050F05"
   secondaryBackgroundColor = "#18181B"
   textColor = "#FFFFFF"
   font = "sans serif"
   ```
2. Tambah CSS kustom lewat `st.markdown(unsafe_allow_html=True)`:
   - Border `#27272A` pada container/card
   - Radius 8px pada card & tombol
   - Radius pill untuk badge/chip
   - Warna teks sekunder `#A1A1AA` untuk caption
3. Font: Inter untuk teks, JetBrains Mono untuk label/metadata (angka, durasi, kode). Pakai Google Fonts lewat `@import` di CSS.

**BATASAN PENTING — jangan janji lebih dari yang bisa:**
- Design NX9 aslinya punya **background WebGL/Three.js** (particles, dither, atmospheric). **Streamlit TIDAK BISA** merender itu sebagai background halaman.
- User sudah setuju: **cukup warnanya saja**. Jangan coba pasang WebGL/Three.js.
- Jangan pasang animasi berat — Streamlit rerun seluruh halaman tiap interaksi.

**Syarat:**
- Warna harus tetap kontras & terbaca (teks putih di `#050F05` sudah aman)
- Jangan sampai CSS merusak komponen bawaan Streamlit (checkbox, selectbox, expander)
- Test di Streamlit yang benar-benar jalan (`streamlit run app.py`, cek HTTP 200)

---

## #5 — Daftar lagu jadi list vertikal

**Sekarang:** grid card (beberapa kolom, `st.columns(cols_per_row)` + `st.image` per card).

**Yang diminta user:** daftar ke bawah seperti playlist Spotify — satu lagu per baris.

**Perbaikan yang diminta:**
Tiap baris berisi (kiri ke kanan):
```
[✓] [cover 48x48]  Judul lagu            3:42
                   Artist • Album         [Unduh]
```

- Cover kecil (48–56 px), **square**
- Judul tebal, artist/album abu-abu (`#A1A1AA`)
- Durasi rata kanan, font mono
- Nomor urut di paling kiri (opsional, seperti Spotify)
- Tombol "Unduh" per baris
- Checkbox untuk pilih banyak → tombol download massal tetap ada

**Syarat:**
- Terapkan juga di halaman **Download Cover**
- Search/filter harus tetap jalan
- Untuk playlist 100 lagu, jangan bikin UI lemot (Streamlit render 100 baris = berat; pertimbangkan paginasi atau batasi render)

---

## #8 — Backup: buang kolom durasi

**Sekarang** (`ui/data.py`):
```python
def to_csv(view):
    lines = ["no,title,artist,album,duration,mp3_url"]   # ← duration & mp3_url
```

**Yang diminta user:** cukup **judul + artist**.

**Perbaikan yang diminta:**
- CSV: `no,title,artist` saja
- TXT: daftar `judul - artist` per baris
- JSON: sesuaikan juga
- Hapus kolom durasi, album, mp3_url dari export backup

**Syarat:** kalau format lama sudah pernah dipakai user, jangan rusak — cukup ganti formatnya (belum ada yang menyimpan file lama).

---

# URUTAN PENGERJAAN YANG DISARANKAN

```
1. #6  bug fatal download          ← paling penting, user kena error
2. #7  cover per lagu              ← fatal juga
3. #8  backup (kecil, cepat)
4. #4  aturan ZIP 30
5. #3  home page Spotify-like
6. #2  warna NX9
7. #5  list vertikal
8. #1  OAuth (paling besar, opsional)
```

Test tiap selesai satu poin. Jangan kerjakan semua sekaligus.

---

# TEST YANG HARUS TETAP LULOS

```bash
.venv/Scripts/python.exe tests/smoke.py             # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py      # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=42 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
.venv/Scripts/python.exe -c "import app; print('OK')"
```

Kalau ada test lama gagal karena perubahan yang **memang disengaja** (mis. limit 100 → 30), update test-nya dan **jelaskan di laporan**.

---

# BATASAN YANG HARUS DIHORMATI

1. **JANGAN bikin dari awal.** Semua modifikasi file yang sudah ada.
2. **JANGAN bypass apa pun.** Tidak ada paywall/proteksi yang ditembus.
3. **JANGAN simpan credential di kode.** Hanya `.env` (sudah di `.gitignore`).
4. **JANGAN hapus provider lama** (`soundloaders.py`, `spotidown.py`, `spotidown_co.py`).
5. **JANGAN pasang WebGL/Three.js** — Streamlit tidak bisa.
6. **JANGAN ngarang angka.** Kalau ada yang belum diuji, bilang belum diuji.
7. **JANGAN hapus penanganan error yang sudah ada** — semua pesan berbahasa Indonesia dan menjelaskan cara memperbaiki.

---

# LAPORAN YANG DIMINTA

Setelah selesai, laporkan per poin:
- File apa yang diubah
- Apa yang diubah
- Test apa yang dijalankan + hasilnya
- Apa yang **belum** selesai atau belum diuji (jujur)

---

# KALAU ADA YANG NGGAK JELAS

Tanya dulu sebelum ngarang.

**Yang sudah PASTI (jangan ubah asumsinya):**
- `resolve_track()` provider YouTube mengembalikan **path lokal**, bukan URL
- Halaman embed Spotify cap 100 item, dan **hanya punya 1 gambar** untuk semua lagu
- `GET /tracks/{id}` jalan (200), `GET /tracks?ids=` dilarang (403)
- Cover SpotiDown.co = `GET /tracks/{id}` (sudah dibandingkan, identik)
- Data owner ada di `entity["subtitle"]`
- Total durasi = jumlah `duration` di `trackList` (satuan ms)
- Streamlit tidak bisa render WebGL sebagai background
