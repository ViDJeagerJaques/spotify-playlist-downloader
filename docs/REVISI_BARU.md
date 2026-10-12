# Revisi dari user (10 Okt 2026) — catatan, belum dikerjakan

Status verifikasi: semua poin SUDAH dicek langsung di kode/data (bukan asumsi).

---

## R0 — Owner tampil hash, bukan nama
```
UI sekarang  : "oleh 31siy2jiykpjmhgercjuh2j2yrbe"
Seharusnya   : "oleh David-Atha"
```
**Status: BUG NYATA**

Penyebab: `playlist_track_ids()` mengembalikan `ownerUsername` (hash), dan
`embed_tracks_complete()` memprioritaskan itu di atas `entity["subtitle"]`
dari halaman embed.

Perbaikan: balik prioritasnya — `embed_owner` dulu, spclient cuma cadangan.
Lokasi: `providers/spotify_embed.py` baris ~318
(`return title, tracks, hint, cover, (owner or embed_owner), total_ms`)

---

## R1 — Semua cover kembali ke kondisi awal (semua lagu satu gambar)
**Status: BUG NYATA — user benar, saya salah saat verifikasi awal**

Terbukti dengan playlist user `5jPG8GymyNv0lX6aSv5dE3` ("Test#001", 4 lagu):
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

Cover yang seharusnya (dari `/embed/track`):
```
Blank Space         -> ab67616d00001e0252b2a3824413eefe9e33817a
Cinnamon Girl       -> ab67616d00001e02879e9318cb9f4e05ee552ac9
Style               -> ab67616d00001e0252b2a3824413eefe9e33817a
Snow On The Beach   -> ab67616d00001e02fa747621a53c8e2cc436dee0
```

**Akar masalah:**
```
Jalur embed (100 pertama)  -> 1 cover playlist untuk SEMUA lagu   <-- BUG
Jalur spclient (>100)      -> cover per lagu (BENAR)
```
OpenCode hanya memperbaiki jalur >100. Jalur 100 pertama masih memakai
`tracks_from_entity(..., cover_for=cover_playlist)`.

**Kesalahan verifikasi saya:** saya menghitung "ada cover 213/213" (jumlah),
bukan "cover unik" (keunikan). Playlist 213 lagu menyembunyikan bug ini karena
mayoritas lagu lewat jalur yang benar.

Perbaikan: 100 pertama juga harus lewat `track_details()` supaya dapat cover
dan artist per lagu.

---

## R2 — Halaman Download Cover harus GALERI
**Status: BELUM DIKERJAKAN — saya salah paham sebelumnya**

User: *"yang halaman download lagu memanjang ke bawah, kalo yang download lagu
tuh memanjang ke samping jadi nya kayak koleksi art di museum gitu"*

Artinya:
```
Download Lagu   ->  list memanjang ke bawah   (SUDAH BENAR)
Download Cover  ->  GALERI kotak-kotak        (sekarang list — harus dibalikin)
```

Revisi #5 ("list vertikal") **hanya untuk halaman Download Lagu**, tapi karena
`_render_track_row()` dipakai di dua halaman, halaman cover ikut berubah jadi list.

Dulu (era provider SpotiDown) halaman cover memang galeri kotak-kotak dan user
suka itu. Cover lebih enak dilihat sebagai galeri.

Verifikasi saya sebelumnya ("page_covers sudah pakai list, bukan bug") **salah** —
saya mengira user mau list, padahal user mau galeri.

Perbaikan: `page_covers()` kembali ke grid galeri, `page_songs()` tetap list.

---

## R3 — Cover playlist di Home belum square
**Status: BUG NYATA**

CSS square sudah ditulis di `ui/theme.py` (`.nx9-art`, `aspect-ratio: 1/1`,
`object-fit: cover`) dan di-inject lewat `inject_theme()`.

**Tapi kelas `.nx9-art` TIDAK PERNAH dipakai.** Di `app.py`:
```
baris 1022: st.image(url, width=size)      # tanpa kelas
baris ~803: st.image(cover, width=200)     # tanpa kelas, komentar bilang
                                           # "square via CSS" padahal tidak
```

Perbaikan: bungkus `st.image` dengan kelas `.nx9-art` / `.nx9-art-img`
(mis. lewat `st.markdown` pembungkus, atau ganti ke HTML `<img class="nx9-art">`).

---

## R4 — Tag ID3 + cover belum ditulis ke MP3
**Status: BELUM DIKERJAKAN** (intervensi soal SpotiDown sudah selesai,
tapi perbaikan yang keluar dari temuan itu belum dikerjakan)

Pertanyaan user: kenapa file SpotiDown punya album + publisher, sedangkan
punya kita tidak? Apa SpotiDown ambil dari Spotify langsung?

**Jawaban (terverifikasi):**

1. Klaim "SpotiDown ambil dari YouTube" **TETAP BENAR.**
   URL mereka: `/savemp3/<youtube_id>:<spotify_id>:<hash>`
   ```
   qN4ooNx77u0 -> YouTube "Harry Styles - Sign of the Times" (HarryStylesVEVO)
   glscfhJyZHo -> YouTube "Daniel Caesar - Who Knows" (Daniel Caesar)
   ```
   Kalau ambil langsung dari Spotify, tidak mungkin ada ID YouTube di URL.

2. Tapi user **juga tidak salah** — file SpotiDown memang punya album/publisher.
   **Penjelasan: itu TAG, dan tag bisa ditulis siapa saja.**

3. **Dibuktikan langsung:** file kita (Cinnamon Girl, dari YouTube) diberi tag
   legal dengan `ffmpeg -c copy`:
   ```
   SEBELUM: artist="David Dean Burkhart", album=(kosong), publisher=(kosong)
   SESUDAH: artist="Lana Del Rey", album="Norman Fucking Rockwell!",
            publisher="Polydor Records", copyright="© 2019 Polydor Records"
   ```
   Ukuran audio `7.203.108` -> `7.203.096` bytes (hanya header berubah).
   **Audio tidak berubah sama sekali. Tag bukan bukti sumber audio.**

**Yang bikin file kita kelihatan jelek:**
```
artist: "David Dean Burkhart"   <-- nama channel YouTube, bukan penyanyi
album : (kosong)
cover : (tidak ada embedded art)
```

**Kondisi kode sekarang** (`providers/youtube.py` `_download()`, baris ~281):
```python
"postprocessors": [
    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
     "preferredquality": "192"},
    {"key": "FFmpegMetadata"},      # <-- tulis tag DARI YouTube, bukan Spotify
],
```
`FFmpegMetadata` menyalin tag dari video YouTube, jadi `artist` berisi nama
channel. Tidak ada langkah untuk menimpa dengan metadata Spotify,
dan tidak ada embedded cover.

**Item kerja:**
- Timpa tag dengan metadata Spotify: title, artist (penyanyi asli), album,
  track number, disc number, date
- **Embed cover art** dari Spotify CDN ke dalam file
- `Track` (providers/base.py) sudah punya `album` dan `thumbnail` — pakai itu
- `mutagen` **belum terinstall**; ffmpeg sudah ada (v9.0.1). Pilih salah satu:
  - tambah `mutagen` ke requirements (paling bersih untuk tag + cover)
  - atau pakai `ffmpeg -metadata` + `-i cover.jpg -map 1 -c copy`

**Temuan sampingan:** app kita memilih video dari channel
"David Dean Burkhart" (bukan channel resmi Lana Del Rey) untuk Cinnamon Girl.
Scoring match masih bisa ditingkatkan agar memprioritaskan channel
resmi/VEVO/Topic.

---

## Ringkasan item kerja (untuk prompt OpenCode)

| # | Item | File |
|---|---|---|
| R1 | 100 pertama lewat `track_details()` — cover + artist per lagu | `providers/spotify_embed.py` |
| R3 | Pasang kelas `.nx9-art` pada `st.image` (Home + list) | `app.py` |
| R0 | Owner: `embed_owner` dulu, hash cadangan | `providers/spotify_embed.py` |
| R4 | Tulis tag ID3 + embed cover dari metadata Spotify | `providers/youtube.py`, `core/orchestrator.py` |

---

## Status repo saat catatan dibuat
- 335 test lolos (10 file test)
- Playlist 213 lagu terbaca 213, tanpa login
- BELUM di-commit
- `tools/` bersih (hanya `spotidown_grab.py`)
