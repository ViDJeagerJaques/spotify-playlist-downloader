# Prompt untuk OpenCode — Migrasi ke Provider YouTube (yt-dlp)

> Copy seluruh isi file ini, paste ke OpenCode.

---

## KONTEKS: TEMUAN BESAR YANG MENGUBAH ARAH

Sebelum mengerjakan apa pun, baca ini dulu — ini alasan seluruh perubahan.

**SpotiDown.co ternyata mengambil audio dari YouTube.** Bukan dari Spotify.

Buktinya ada di URL yang mereka kembalikan:

```
https://api.spotidown.co/savemp3/qN4ooNx77u0:5Ohxk2dO5COHF1krpoPigN:26d8f9...
                          └──────────┘ └──────────────────────┘ └────────┘
                          YouTube ID     Spotify Track ID        hash
```

Bagian pertama (`qN4ooNx77u0`) adalah **ID video YouTube**. Sudah diverifikasi
lewat `https://www.youtube.com/oembed?url=...&format=json`:

| ID | Hasil verifikasi |
|---|---|
| `qN4ooNx77u0` | "Harry Styles - Sign of the Times (Official Video)" — HarryStylesVEVO |
| `glscfhJyZHo` | "Daniel Caesar - Who Knows (Official Lyric Video)" — Daniel Caesar |

**Konsekuensinya:**

1. SpotiDown **tidak punya database MP3**. Mereka cuma perantara: cari di
   YouTube, download, teruskan ke user.
2. Kualitas audio **identik** dengan mengambil langsung dari YouTube. Tidak ada
   yang dikorbankan dengan pindah.
3. Server mereka cuma numpang lewat — file tidak disimpan (mereka klaim
   "we don't host any user content").

**Kesimpulan:** aplikasi kita bisa melakukan SEMUA yang SpotiDown lakukan, dan
di beberapa bagian lebih baik.

---

## TUGAS

Ganti provider default dari SpotiDown.co (Chrome + CDP) ke provider YouTube
(yt-dlp + Spotify API).

**PENTING:** provider YouTube-nya **SUDAH DIBUAT dan SUDAH LOLOS TEST**.
Tugas utama kalian adalah **memverifikasi, memperbaiki yang kurang, dan
merapikan** — BUKAN menulis ulang dari nol.

Baca dulu file-file ini:

- `providers/youtube.py` ← **provider baru (sudah ada)**
- `providers/spotify_meta.py` ← **client Spotify API (sudah ada)**
- `tests/test_youtube.py` ← **27 test, semua lolos**
- `core/orchestrator.py` ← ada `LocalCopyFetcher` baru
- `app.py` ← backend YouTube sudah ditambahkan
- `.env.example` ← template credential

---

## CARA KERJA PROVIDER BARU

### Alur

```
1. Spotify Web API   →  daftar lagu (judul, artist, durasi, coverUrl)
2. yt-dlp search     →  cari kandidat di YouTube
3. Scoring           →  pilih match terbaik
4. yt-dlp download   →  ambil audio
5. ffmpeg            →  konversi MP3
6. orchestrator      →  bungkus jadi ZIP
```

### Spotify API (metadata)

- **Auth:** Client Credentials (app-only, tanpa login user)
- **Credential:** `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` di file `.env`
- **Syarat:** akun pemilik app harus **Spotify Premium** (aturan Spotify Feb 2026)
- **Catatan API 2026:** endpoint `/playlists/{id}/tracks` sudah diganti
  `/playlists/{id}/items`, dan key item berubah dari `track` ke `item`.
  Kode sudah menangani keduanya (coba `/items` dulu, fallback ke `/tracks`).

### Cover Art

Diambil dari **Spotify CDN langsung**, bukan dari YouTube:

```
https://i.scdn.co/image/ab67616d0000b2733f8b8a9c71b2bd2f3019940b
```

Diverifikasi: HTTP 200, `image/jpeg`, 106 KB, **CORS terbuka** (`Access-Control-Allow-Origin: *`).
Tidak butuh auth, tidak butuh browser. Ambil lewat `requests.get(coverUrl)` biasa.

### Match Scoring (bagian paling penting)

Fungsi `score_candidate()` di `providers/youtube.py` memilih kandidat YouTube.
Ini yang bikin hasilnya akurat. Logikanya:

- **Durasi:** kandidat yang beda > 25 detik dari durasi Spotify → **ditolak** (`-1.0`)
- **Bonus** kalau judul/uploader mengandung: `official audio`, `official video`,
  `topic`, `provided to youtube`
- **Penalti** kalau mengandung: `live`, `cover`, `remix`, `sped up`, `slowed`,
  `nightcore`, `reaction`
- **Bonus** berdasarkan view count

Hasil terverifikasi:

```
14.50  Harry Styles - Sign of the Times (Official Video)   ← DIPILIH
-1.00  Sign of the Times (Live at MSG)                     ← ditolak (durasi)
 5.80  Sign of the Times (Cover by Somebody)               ← ditolak (penalti)
-1.00  Sign of the Times (Sped Up)                         ← ditolak
```

---

## JEBAKAN YANG WAJIB DITANGANI

### Jebakan 1 — YouTube BLOKIR IP DATACENTER

Ini **yang paling penting** dan tidak bisa diakali dengan kode.

Dari dokumentasi resmi yt-dlp:

> *"Since YouTube has started broadly blocking access from datacenter IPs.
> Even if no one ever accessed YouTube from that IP it could still be blocked."*

Artinya:

| Lokasi | yt-dlp jalan? |
|---|---|
| PC user (IP rumah) | ✅ Ya |
| VPS / Streamlit Cloud / Railway | ❌ Nggak — "Sign in to confirm you're not a bot" |
| VPS + proxy residential | ✅ Ya — tapi proxy bayar (~$5-15/bln) |

**Yang harus dilakukan:** tangani error ini dengan pesan yang jelas (bukan crash),
dan dokumentasikan di README bahwa deploy butuh proxy residential.
Kode sudah menangani ini di `_pick_best()`.

### Jebakan 2 — ffmpeg wajib ada

Tanpa ffmpeg, konversi MP3 gagal. `ensure_requirements()` sudah cek ini dan
kasih pesan instalasi. Jangan hapus.

### Jebakan 3 — yt-dlp cepat basi

YouTube sering berubah. yt-dlp versi lama gagal diam-diam. Dokumentasikan:
`pip install -U yt-dlp` secara berkala.

### Jebakan 4 — Download lambat

Tiap lagu = search + download + ffmpeg. Beberapa detik per lagu. Playlist 100
lagu bisa lama. Jangan naikkan worker count agresif — YouTube rate-limit.

---

## YANG HARUS DIKERJAKAN

### A. Verifikasi provider yang sudah ada

Jalankan dan pastikan lolos:

```bash
.venv/Scripts/python.exe tests/test_youtube.py      # harus PASS=27 FAIL=0
.venv/Scripts/python.exe tests/smoke.py             # harus PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py # harus PASS=42 FAIL=0
```

### B. Test end-to-end dengan credential nyata

Buat file `.env` (lihat `.env.example`), lalu:

```bash
.venv/Scripts/python.exe -c "
from providers.youtube import YouTubeClient
c = YouTubeClient()
r = c.load_tracks('https://open.spotify.com/playlist/0OAWLZxZydBuXyVuCszKT')
print(r.title, len(r.tracks))
for t in r.tracks[:3]:
    print(' ', t.artist, '-', t.title, '| dur:', t.duration_ms, '| cover:', bool(t.thumbnail))
"
```

Lalu test resolve + download satu lagu:

```bash
.venv/Scripts/python.exe -c "
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
t = Track(data='x', title='Sign of the Times', artist='Harry Styles', duration_ms=341000)
path = c.resolve_track(t)
print('downloaded:', path)
import os; print('size:', os.path.getsize(path))
"
```

**Kriteria:** file MP3 terbentuk, ukuran wajar (>1 MB), header diawali `ID3`.

### C. Rapikan UI

- Pastikan backend **YouTube jadi default** (bukan SpotiDown.co)
- Tambah info di sidebar: butuh `.env`, butuh ffmpeg
- Pesan error kalau credential belum diisi harus jelas
- Tampilkan progres per lagu saat batch (sudah ada di orchestrator)

### D. Tandai SpotiDown sebagai legacy

- Jangan hapus `providers/spotidown_co.py` — biarkan sebagai opsi
- Tapi keluarkan dari daftar utama, atau beri label "(legacy, butuh Chrome)"

### E. Bersihkan script probe

Hapus file-file ini (sudah tidak dipakai):
```
tools/probe_spotidown.py, probe2.py ... probe8.py
tools/console_hook.js
tools/chrome-profile/, chrome-profile2/, chrome-profile3/, cdp-profile/
```

**TAPI JANGAN hapus `tools/spotidown_grab.py`** — simpan sebagai referensi.

### F. Update requirements.txt

Pastikan ada:
```
yt-dlp>=2025.1.1
```

### G. Update README

Harus mencakup:
- Cara install (Python, ffmpeg, dependencies)
- Cara dapat Spotify credential (link ke developer.spotify.com/dashboard)
- Cara bikin `.env`
- Cara pakai
- **Batasan jujur:** YouTube blokir IP datacenter, deploy butuh proxy
- **Legal:** personal use only

---

## BATASAN YANG HARUS DIHORMATI

1. **JANGAN bypass apa pun.** Tidak ada paywall yang dilewati, tidak ada
   proteksi yang ditembus. Provider ini pakai API resmi + tool publik.

2. **JANGAN simpan credential di kode.** Hanya dari `.env`, dan `.env` sudah
   ada di `.gitignore`. Jangan pernah commit.

3. **JANGAN hapus provider lama** (`soundloaders.py`, `spotidown.py`,
   `spotidown_co.py`). Biarkan sebagai opsi.

4. **JANGAN ngarang angka kualitas.** Audio dari YouTube — jangan klaim
   "320kbps Spotify". Tulis apa adanya.

5. **JANGAN hilangkan penanganan error yang sudah ada.** Semua pesan error
   berbahasa Indonesia dan menjelaskan cara memperbaiki.

---

## CATATAN JUJUR YANG HARUS ADA DI KODE

- Audio berasal dari **YouTube**, bukan Spotify
- Kualitas tergantung kecocokan match — kadang bisa salah versi
- **YouTube blokir IP datacenter** → deploy publik butuh proxy berbayar
- Butuh `ffmpeg` dan `yt-dlp`
- Butuh Spotify Premium untuk akun pemilik app
- **Legal:** download dari YouTube bisa melanggar ToS YouTube; download konten
  Spotify bisa melanggar ToS Spotify. Personal use only.

---

## REFERENSI

- `providers/youtube.py` — implementasi provider (sudah jalan)
- `providers/spotify_meta.py` — client Spotify API (sudah jalan)
- `tests/test_youtube.py` — 27 test (semua lolos)
- `tools/spotidown_grab.py` — implementasi SpotiDown lama (referensi saja)

---

## KALAU ADA YANG NGGAK JELAS

Tanya dulu sebelum ngarang.

**Yang sudah PASTI** (jangan ubah asumsinya):
- SpotiDown ambil audio dari YouTube (sudah diverifikasi)
- Bentuk response Spotify API
- Cover dari `i.scdn.co` bisa diakses tanpa auth
- Alur scoring match
- Empat jebakan di atas

**Yang belum pasti:**
- Berapa lama Spotify credential bertahan (token expire 1 jam, auto-refresh)
- Apakah semua lagu ada di YouTube (ada yang tidak)
