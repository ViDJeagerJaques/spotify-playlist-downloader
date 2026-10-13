# Spotify Playlist Downloader (Streamlit) — YouTube (yt-dlp) backend

Web app **untuk penggunaan pribadi**: tempel URL Spotify (playlist / album /
lagu), lihat daftar lagunya, lalu unduh sebagai MP3 (satuan atau ZIP).

## Cara kerjanya

```
Daftar lagu  : halaman embed publik Spotify  ->  open.spotify.com/embed/...
               + spclient (token anonim)     ->  daftar lagu PENUH, tanpa batas
Metadata     : spclient /metadata/4/track/... ->  album, label, tahun, nomor track
Cover        : /embed/track + oEmbed          ->  cover album asli 640x640
Audio        : yt-dlp cari + unduh dari YouTube, ffmpeg konversi ke MP3
Tag          : tag ID3 ditulis ulang dari metadata Spotify + cover ditanam
```

Jadi **audio berasal dari YouTube, bukan dari Spotify**. Aplikasi ini tidak
punya database MP3 dan bukan scraper Spotify: dia cuma mencari video yang
cocok di YouTube lalu mengunduhnya, kemudian **menuliskan metadata Spotify yang
benar** ke file hasilnya (judul, artist, album, label, tahun, cover).

| Backend | Status | Catatan |
|---|---|---|
| **YouTube via yt-dlp** | **default** | Tanpa browser, tanpa CAPTCHA, jalan di VPS |
| Demo (Mock) | offline | Data contoh, tanpa jaringan |

> **Dihapus:** SpotiDown.co, SoundLoaders, dan SpotiDown.app. Ketiganya butuh
> token CAPTCHA atau jendela Chrome yang terbuka, dan semuanya sudah mati.
> Menawarkannya di dropdown hanya menghasilkan error kosong, jadi opsinya
> dihapus — bukan disembunyikan. Lihat [Riwayat perubahan](# riwayat-penghentian-backend) di bawah.

## Instalasi

**1. Python 3.10+**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**2. ffmpeg** (wajib — untuk konversi MP3). Cek dengan `ffmpeg -version`.

```powershell
winget install Gyan.FFmpeg          # Windows
brew install ffmpeg                # macOS
sudo apt install ffmpeg            # Debian/Ubuntu
```

**3. yt-dlp** — sering perlu di-update karena YouTube cepat berubah:

```powershell
pip install -U yt-dlp
```

## Credential Spotify — tidak wajib untuk playlist publik

Untuk **playlist / album / lagu publik**, aplikasi **tidak butuh login sama
sekali**. Daftar lagunya dibaca dari halaman embed publik Spotify, dan `.env`
boleh kosong.

### Hubungkan Spotify (opsional) — hanya untuk playlist PRIVATE

> ⚠️ **Tidak wajib, dan bukan lagi soal batas 100 lagu.** Playlist publik
> dibaca **penuh tanpa login** (lihat bagian "Membaca playlist tanpa batas 100
> lagu" di bawah). Token ini cuma dibutuhkan untuk playlist **private**.

Cover album asli per lagu juga diambil **tanpa token** (lewat `/embed/track` +
oEmbed), jadi credential Web API di bawah hanya untuk langkah login playlist
private.

**1. Siapkan credential app** (sekali saja):

1. Buka <https://developer.spotify.com/dashboard> → buat app
   (Spotify mewajibkan akun **Premium** untuk app sejak Februari 2026).
2. Salin **Client ID** dan **Client Secret**.
3. Salin `.env.example` jadi `.env` lalu isi:

```
SPOTIFY_CLIENT_ID=xxxx
SPOTIFY_CLIENT_SECRET=yyyy
```

`.env` sudah ada di `.gitignore` — **jangan pernah di-commit**.

**2. Ambil refresh token:**

1. Di app: **Home** → buka *"Playlist private? Hubungkan Spotify (opsional)"*.
2. Klik **Buka halaman login Spotify** → login → izinkan.
3. Salin `code` dari URL hasil (parameter `?code=...`) → tempel di kotak.
4. Klik **Simpan ke .env** — aplikasi menulis `SPOTIFY_REFRESH_TOKEN` sendiri.
5. Klik **Load Playlist** lagi.

**Perbedaannya:**

| | Tanpa token (default) | Dengan `SPOTIFY_REFRESH_TOKEN` |
|---|---|---|
| Playlist publik (100+ lagu) | ✅ **penuh, tanpa batas** | ✅ |
| Album / lagu tunggal | ✅ | ✅ |
| Cover album per lagu | ✅ | ✅ |
| Playlist **private** | ❌ | ✅ |
| Perlu login | tidak | sekali saja |

> Token hanya disimpan di `.env` milikmu. Tidak ada credential di dalam kode.
>
> Catatan jujur: sejak perubahan Spotify Februari 2026, token Client
> Credentials **tidak lagi bisa membaca isi playlist** (`/playlists/{id}/items`
> → 401 `Valid user authentication required`). Itulah kenapa playlist publik
> dibaca lewat jalur embed + spclient, dan token user hanya untuk yang private.

### Membaca playlist tanpa batas 100 lagu

Playlist publik dulu hanya terbaca **100 lagu pertama** dan sisanya perlu login
user. Sekarang tidak: halaman embed Spotify memuat **access token anonim** di
dalam HTML-nya, dan token itu bisa dipakai ke endpoint internal `spclient`:

```
1. GET open.spotify.com/embed/playlist/{id}
      -> 100 lagu pertama + token anonim (140 karakter) + owner + cover
2. GET spclient.wg.spotify.com/playlist/v2/playlist/{id}   (Bearer token)
      -> SEMUA track id, urut, truncated:false
3. GET open.spotify.com/embed/track/{id}   -> judul / artist / durasi
4. GET open.spotify.com/oembed             -> cover album
```

Terverifikasi pada playlist **213 lagu → 213/213 terbaca**, tanpa login sama
sekali (metadata 213/213, cover 213/213). Hasil disimpan di cache
(`.cache/spclient_tracks.json` dan `spclient_meta.json`).

**Performa** (diukur di PC lokal, playlist 213 lagu):

| Situasi | Waktu | Request |
|---|---|---|
| Cache dingin (pertama kali) | ~10,5 s | 210 |
| Cache hangat (muat ulang) | **~0,9 s** | **1** |

Cache dingin hanya ~210 request: endpoint metadata spclient mengembalikan
judul, artist, durasi **dan cover** sekaligus, jadi cukup **1 request per lagu**
(bukan 3: `/embed/track` + oEmbed + metadata). `/embed/track` + oEmbed tetap
dipakai sebagai cadangan kalau metadata gagal.

Catatan: laju total dibatasi **20 request/detik** — semua worker berbagi *token
bucket*, jadi request tetap berjalan **paralel** (jeda 150 ms berlaku per worker,
bukan global).
> ⚠️ **Spotify membatasi IP.** Kalau Anda memuat banyak playlist besar
> beruntun, `open.spotify.com` bisa membalas **HTTP 429**. Itu bukan playlist
> private — tunggu beberapa menit lalu muat lagi. Cache yang sudah terisi tetap
> bisa dipakai.

> ⚠️ **Ketergantungan eksternal:** `spclient.wg.spotify.com` adalah endpoint
> **internal** Spotify, bukan API publik — bisa berubah atau hilang tanpa
> pemberitahuan. Kalau gagal, aplikasi otomatis mundur ke 100 lagu dari halaman
> embed dan memberi tahu — tidak ikut rusak.

### ⚠️ Jangan pakai `api.spotify.com` untuk playlist

Selama pengembangan, `api.spotify.com/v1/tracks/{id}` membalas
`429 QUOTA_EXCEEDED` terus-menerus dan **tidak pulih** setelah 30/60/120 detik.
Karena itu jalur playlist **dilarang** lewat sana dan diganti
`/embed/track` + oEmbed yang terbukti bebas rate limit (20/20 sukses,
~312 ms/request). `api.spotify.com` hanya menyisakan untuk Single track/album.

## Menjalankan

```powershell
streamlit run app.py
```

Lalu: tempel link di **Home** → klik **Load Playlist** → pilih salah satu dari 4
menu aksi.

## Struktur kode

```
app.py                       Streamlit UI (state, rendering, error handling)
core/
  orchestrator.py            loop resolve per-track + bundel ZIP lokal (batch)
  i18n.py                    string UI bilingual (Indonesia / English)
  cleanup.py                 hapus file sementara batch
providers/
  base.py                    tipe data Track/ResolveResult + kelas error
  youtube.py         <-- DEPENDENCY: yt-dlp ke YouTube (default)
  spotify_embed.py   <-- DEPENDENCY: baca halaman embed publik Spotify
  spotify_spclient.py <-- DEPENDENCY: spclient Spotify (playlist penuh + album/label)
  tags.py                    tulis tag ID3 + cover ke MP3
  spotify_meta.py    <-- DEPENDENCY: Spotify Web API (fallback, butuh .env)
  mock.py                    provider demo tanpa jaringan
ui/
  data.py                    adapter hasil provider -> dict untuk 5 halaman UI
  theme.py                   token desain NX9 + CSS Streamlit
  dummy.py                   data dummy untuk demo offline
.streamlit/
  config.toml                tema NX9 (warna Streamlit)
tests/
  smoke.py                   unit fungsional (orchestrator, i18n, retry)
  test_youtube.py            unit provider YouTube (scoring channel, cache, lokal)
  test_spotify_embed.py      unit parser embed + fixture nyata
  test_covers.py             cover album per lagu, cache, paruh-paral
  test_fetch_bytes.py        unduh 1 lagu (path lokal / URL / mock)
  test_oauth.py              jalur user-token opsional untuk playlist >100
  test_theme.py              token & CSS NX9, kontras, tanpa WebGL
  test_app.py                end-to-end 5 halaman (AppTest, Mock provider)
  fixtures/                  payload nyata yang tertangkap, untuk test offline
```

### Halaman UI

1. **Home** — tempel URL playlist sekali, dipakai semua halaman selama sesi.
   Header meniru Spotify: cover **persegi milik playlist itu sendiri**, nama,
   **penyusun**, jumlah lagu, total durasi.
2. **Download Playlist** — ≤30 lagu jadi **1 ZIP penuh**; >30 dipecah jadi Part
   30 lagu/bagian. Pembagiannya ditampilkan sebelum kamu klik download.
3. **Download Lagu** — **tabel kolom ala Spotify** (nomor, cover 40px,
   judul + artist, album, durasi, tombol Unduh) + search + centang → unduh per
   lagu atau satu ZIP. Teks panjang dipotong `...`, tidak pernah membungkus.
4. **Download Song Cover** — daftar vertikal yang sama, fokus ke artwork.
   Centang beberapa cover → satu ZIP gambar.
5. **Backup** — export TXT / JSON / CSV berisi **judul + artist** saja.

Semua halaman besar memakai **paginasi 25 baris per halaman**, supaya playlist
100 lagu tetap ringan di browser.

### Tema NX9

`.streamlit/config.toml` + `ui/theme.py` menerapkan palet desain:

| Token | Nilai |
|---|---|
| aksen | `#A8D055` (hijau neon) |
| background | `#050F05` |
| surface | `#18181B` |
| teks utama | `#FFFFFF` |
| teks sekunder | `#A1A1AA` |
| border | `#27272A` |
| font teks | Inter |
| font angka/kode | JetBrains Mono |
| radius card | 8px |
| radius pil | 9999px |

Kelas untuk **tabel Download Lagu** (`ui/theme.py`): `nx9-tbl-row`, `nx9-tbl-data`,
`nx9-tbl-caption`, `nx9-tbl-num`, `nx9-tbl-art`, `nx9-tbl-body`, `nx9-tbl-title`,
`nx9-tbl-sub`, `nx9-tbl-dur`, `nx9-tbl-head`.

Setiap baris adalah **satu blok HTML dengan CSS grid**
(`clamp(1.75rem,2vw,2rem) clamp(2.75rem,3vw,3rem) minmax(0,1fr)
minmax(0,clamp(8rem,14vw,16rem)) clamp(2.5rem,3vw,2.75rem)`), bukan
`st.columns()`. Alasannya `stHorizontalBlock` punya gap 16px bawaan yang tidak
bisa dinetralkan dari dalam cell - dengan 7 kolom itu jadi 96px ruang mati per
baris, dan kolom sempit di sekitar checkbox/tombol tergencet sampai cover meluap
keluar kotaknya.

Checkbox + tombol "Unduh" tidak bisa masuk ke `st.markdown`, jadi tiap baris
dipecah jadi dua kolom Streamlit saja (`[grid HTML] [aksi]`).

Semua ukuran fluid dan mengikuti ritme 4/8px. `clamp(min, ideal, max)` =
"tidak lebih kecil dari min, tidak lebih besar dari max, idealnya ikut viewport",
dan itulah yang bikin layout-nya universal (bukan cuma enak di satu ukuran layar).

Lima aturan yang wajib ada dan mudah hilang:

- `minmax(0, 1fr)` di kolom judul + `min-width: 0` di `.nx9-tbl-body`. Tanpa itu
  grid item menolak menyusut dan `text-overflow: ellipsis` tidak pernah jalan.
- `flex: 1 1 0` + `min-width: 0` di kolom grid. Streamlit menghitung basis kolom
  pertama sebagai `calc(87.72% - 16px)`; kalau gap dihapus tapi basisnya tidak,
  flex-wrap aktif dan tombol jatuh ke baris bawah.
- `flex: 0 0 6rem` + `min-width: 6rem` di kolom aksi. Di layar sempit Streamlit
  menyetel `min-width: calc(100% - 24px)` yang menelan seluruh baris.
- `margin-top: calc(4px + clamp(0.5rem,1vw,0.75rem))` di kolom aksi, supaya
  tombol dan cover berbagi baseline. Harus clamp yang sama dengan padding baris.
- Tinggi baris harus **lebih besar** dari slot yang dipesan Streamlit untuk
  widget. Kalau grid lebih pendek, isinya meluap dan tombol terdorong ke atas.

Tiga breakpoint: `min-width: 1700px` (batas lebar baca), `max-width: 1100px`
(hilangkan kolom album), `max-width: 640px` (hilangkan nomor, cover lebih besar,
header jadi kartu bertumpuk). Setiap breakpoint yang menyembunyikan sel **wajib**
sekalian mengurangi jumlah track grid, kalau tidak akan ada lubang di baris.
`tests/test_app.py` mengunci semua itu, termasuk regression guard untuk `:has()`
bersarang - selector itu jadi invalid kalau `:has()` muncul di dalam `:has()` lain,
dan browser **diam-diam** membuang seluruh rule-nya tanpa error.

### Lebar halaman

`app.py` sudah memanggil `st.set_page_config(layout="wide")`. Di Streamlit 1.63
itu berarti `max-width` block container di-set `initial` (= unbounded), **bukan**
736px - jadi tidak ada batas 736px yang perlu dibongkar. Masalahnya justru
sebaliknya: tanpa batas atas, monitor 1920px meregangkan tabel jadi 1920px dan
kolom album melayang ~1400px dari judul. Karena itu `ui/theme.py` hanya menambah
**batas atas**:

```css
.block-container { max-width: min(1600px, 94vw) !important; }
```

Catatan: `st.columns()` tidak punya mode responsif di Python
(`SpecType = int | Sequence[int | float]`), jadi jumlah kolom galeri cover tetap
4 dan tidak bisa ikut viewport.

> **Yang tidak ada (disepakati):** desain NX9 asli punya background WebGL /
> Three.js dengan partikel dan animasi. **Streamlit tidak bisa merender itu**
> sebagai background halaman, dan tried overlay JS berat akan bertabrakan dengan
> rerun penuh setiap interaksi. Yang dikirim hanya warna, tipografi, dan
> border/radius — tanpa animasi.

### Cache dan ruang disk

Semua yang ditulis app ini — MP3 hasil unduhan, metadata JSON, ZIP batch, dan
staging per-run — sekarang tinggal di satu folder:

```
<folder proyek>/.cache
```

Override dengan env var `SPOTIFY_CACHE_DIR`. Sumber tunggalnya
`providers/base.py :: cache_dir()`; ketiga provider memakainya supaya tidak ada
lagi salinan path yang berbeda-beda.

Kenapa tidak lagi di temp folder? `tempfile.gettempdir()` di Windows selalu
menunjuk ke `C:\Users\<kamu>\AppData\Local\Temp` **walau proyeknya ada di drive
lain**. Cache ini tumbuh ±5 MB per lagu, jadi playlist 213 lagu ≈ 1 GB yang
mendarat diam-diam di disk sistem.

**`.mp3` selalu berpasangan dengan `.json`.** Sidecar itu mencatat video mana
yang dipakai:

```json
{ "video_id": "ZEY9UCzzbcQ", "channel": "Joji", "duration": 180,
  "resolved_at": "2026-10-13T05:02:41+00:00" }
```

Kalau `.mp3` ada tapi `.json` tidak, file itu dianggap **basi** dan di-resolve
ulang — tanpa catatan ini, perbaikan pemilihan channel tidak akan terasa untuk
lagu yang sudah pernah diunduh sebelum. File lama **tidak dihapus otomatis**,
cuma ditimpa.

ZIP batch yang berumur > 24 jam dihapus otomatis sebelum ZIP baru dibuat
(`purge_stale_zips`). Selain itu ada tombol **"Bersihkan cache"** di sidebar —
wajib dicentang konfirmasi dulu, dan tidak pernah jalan sendiri.

### Cover per lagu

Halaman embed playlist hanya menyediakan **satu gambar** untuk seluruh playlist,
sehingga tanpa tambahan semua lagu akan memakai cover yang sama. Cover album asli
per lagu diambil dari endpoint anonim: `/embed/track/{id}` untuk metadata dan
**oEmbed** untuk artwork (hash gambarnya identik dengan yang dikembalikan Web API).

- Paralel maks 8 worker, jeda 0,15 s antar request.
- Di-cache di `.cache/spclient_tracks.json`, jadi playlist lain
  yang punya lagu sama tidak request ulang.
- **Resolusi 640×640.** oEmbed mengembalikan prefix `ab67616d00001e02` (300×300,
  ~45 KB) yang terlihat pecah saat dibuka besar. `upgrade_cover_url()` di
  `providers/base.py` menukar prefix jadi `ab67616d0000b273` → **640×640,
  ~155 KB**. Hash setelah prefix identik di semua ukuran, jadi tidak ada request
  tambahan. Cover **playlist** (prefix `ab67706f…`) sengaja tidak dinaikkan —
  akan 404.
- **Tidak memakai `api.spotify.com`** — endpoint itu kena `429` parah (lihat
  bagian di atas). Tidak butuh credential, tidak butuh login.
- Lagu yang gagal (dihapus / region lock) jatuh ke cover playlist, tidak error.

### Provider YouTube — yang perlu Anda tahu

**Match scoring** (`score_candidate` di `providers/youtube.py`) yang memilih
video mana yang dipakai:

- Durasi beda **> 25 detik** dari durasi Spotify → kandidat **ditolak**.
- Bonus: `official audio`, `official video`, `topic`, `provided to youtube`.
- Penalti: `live`, `cover`, `remix`, `sped up`, `slowed`, `nightcore`, `reaction`.
- Bonus tambahan dari jumlah views.

Hasil terverifikasi untuk "Sign of the Times":

```
 14.50  Harry Styles - Sign of the Times (Official Video)   <- dipilih
 -1.00  Sign of the Times (Live at MSG)                     <- ditolak (durasi)
  5.80  Sign of the Times (Cover by Somebody)               <- ditolak (penalti)
 -1.00  Sign of the Times (Sped Up)                         <- ditolak
```

Cover art diambil dari CDN Spotify (`i.scdn.co` / `mosaic.scdn.co`) — file
gambar biasa, tanpa auth, CORS terbuka.

### Batasan jujur

- **Audio dari YouTube, kualitas = upload yang ada di sana.** Kadang bisa salah
  versi (mis. versi live atau cover) meski scoring sudah menyaring banyak
  kasus. Tidak ada jaminan kualitas "320 kbps".
- **YouTube memblokir IP datacenter.** Dari dokumentasi resmi yt-dlp:
  *"Since YouTube has started broadly blocking access from datacenter IPs."*
  Di VPS / Streamlit Cloud / Railway kamu akan dapat *"Sign in to confirm you're
  not a bot"* dan tidak bisa diatasi dari sisi kode.

  | Lokasi | yt-dlp jalan? |
  |---|---|
  | PC rumah (IP residential) | Ya |
  | VPS / Streamlit Cloud | Tidak — diblokir |
  | VPS + proxy residential | Ya, tapi proxy berbayar (~$5–15/bulan) |

- **yt-dlp cepat basi.** YouTube sering berubah; upgrade berkala
  (`pip install -U yt-dlp`).
- **Lambat.** Tiap lagu = search + download + ffmpeg (beberapa detik). Playlist
  100 lagu bisa makan waktu lama. Jangan naikkan worker count — YouTube
  rate-limit.
- **Tidak semua lagu ada di YouTube.** Lagu yang tidak ketemu akan ditandai
  gagal di UI, bukan diam-diam dilewati.
- **Playlist publik saja** terbaca tanpa login. Cap 100 item per halaman embed;
  di atas itu app memberi peringatan, bukan menebak.
- **Ketergantungan eksternal.** Kalau Spotify mengubah markup halaman embed, atau
  YouTube mengubah cara yt-dlp mengambil audio, provider ini perlu diperbarui.

### Dependencies

Tercantum di `requirements.txt`:

- `streamlit` — web UI
- `yt-dlp` — search & download audio dari YouTube (satu-satunya jalur download)
- `requests` — HTTP client (cover art)
- `beautifulsoup4` — parsing HTML halaman embed publik Spotify
- `lxml` — parser HTML cepat untuk BeautifulSoup (fallback ke `html.parser`)
- `jinja2` — dependency ekosistem Streamlit
- `mutagen` — tulis tag ID3 + cover ke MP3

`playwright` **tidak** dipakai lagi. Tidak ada browser yang dijalankan di titik
mana pun.

### Di mana ketergantungan ke layanan luar berada

- **YouTube** — hanya di `providers/youtube.py`, lewat `yt_dlp`.
- **Spotify** — hanya di `providers/spotify_embed.py` (halaman embed publik)
  dan `providers/spotify_meta.py` (Web API). Baca docstring `DEPENDENCY NOTE`
  di masing-masing.

### Riwayat penghentian backend

Dulu ada tiga backend pihak ketiga selain YouTube. Semuanya dihapus karena
**sudah mati**, bukan karena ukurannya:

| Backend | Kenapa mati | Sisa-sisanya |
|---|---|---|
| SpotiDown.co | Butuh Chrome terpasang & jendela terlihat terbuka, dan CDN-nya (*.123tokyo.xyz) menolak sebagian request secara acak | ResilientFileFetcher + percabangan prefetched_urls di orchestrator |
| SoundLoaders | Cloudflare Turnstile, token single-use & kedaluwarsa ~5 menit | CaptchaRequiredError + jalur retry |
| SpotiDown.app | reCAPTCHA v3 + cookie sesi browser | `CaptchaRequiredError` + jalur retry |

Yang **tidak** ikut dihapus karena masih berguna:

- CaptchaRequiredError — tidak ada backend sekarang yang melemparnya, tapi
  jalur retry orchestrator dan tampilan error di UI dibangun di atasnya.
- ResilientFileFetcher — YouTube mengembalikan file lokal, bukan URL, jadi ini
  tidak terpakai. Tapi ini implementasi retry-with-backoff yang masih jalan dan
  orchestrator masih memilih fetcher lewat provider.download_headers().
- Percabangan `prefetched_urls` — masih bagian kontrak provider (`YouTubeClient`
  mengadvertises `False`).
- Semua string i18n dan terjemahan help_token yang tidak lagi terpakai.

Konsekuensi nyata: playwright (112 MB) tidak perlu diinstal lagi, pip install
jauh lebih cepat, dan ~1.800 baris kode mati hilang.

### Risiko / kapan app ini berhenti bekerja

- **YouTube rate-limit atau memblokir IP datacenter** → request gagal; app hanya
  bisa menampilkan error. Jalankan di koneksi rumah, atau pakai proxy
  residential kalau harus di-deploy.
- **Markup halaman embed Spotify berubah** → `providers/spotify_embed.py`
  menyerah pada data yang tidak dikenal (lagu tanpa `track_token` dibuang),
  tidak crash, tapi daftar bisa kosong.
- **Cara YouTube mengambil audio berubah** → `yt-dlp` perlu di-update
  (`pip install -U yt-dlp`).
- **Video dihapus / diblokir di wilayah tertentu** → satu lagu gagal, sisanya
  tetap diproses karena batch tidak berhenti saat ada kegagalan.

</details>

## Disclaimer legal / ToS

Tampil juga di UI (expander "Disclaimer & Catatan Legal"):

- **Hanya untuk penggunaan pribadi.** Jangan redistribusi atau publikasikan.
- **Audio berasal dari YouTube.** Mengunduh dari YouTube **dapat melanggar** ToS
  YouTube; mengambil metadata dari Spotify **dapat melanggar** ToS Spotify.
  Periksa hukum setempat Anda.
- **Kualitas mengikuti apa adanya.** Tidak ada klaim bitrate atau kualitas
  tertentu — file Whatever yang ada di YouTube.
- Aplikasi ini **tidak punya scraper Spotify** dan bergantung penuh ke layanan
  pihak ketiga; tidak ada jaminan ketersediaan maupun kecocokan match.
- Tanpa paywall, tanpa proteksi yang ditembus. Backend legacy memakai token
  CAPTCHA milik Anda sendiri.
- Tanggung jawab penggunaan ada pada pengguna.

## Build .exe untuk Windows

Menghasilkan **jendela native** (tanpa console, tanpa browser) berisi app ini.

```powershell
# 1. Siapkan ffmpeg dulu (opsional tapi disarankan — 88 MB).
#    Pakik imageio-ffmpeg: SUDAH DITERUJI bisa encode MP3 (libmp3lame).
.venv\Scripts\python -m pip install imageio-ffmpeg
.venv\Scripts\python -c "import imageio_ffmpeg,shutil; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),'bin/ffmpeg.exe')"

# 2. Build
build_exe.bat          # Windows      (build_exe.sh untuk Linux/macOS)
```

Hasil terukur di mesin ini:

| Build | Ukuran |
|---|---|
| tanpa ffmpeg | **84,1 MB** |
| dengan `bin/ffmpeg.exe` | **113,8 MB** |

Bukti saat dijalankan: jendela `SpotDL` 1024x768 **visible**, log memuat
`You can now view your Streamlit app` + `URL: http://localhost:<port>`, dan
`curl` ke URL itu balas **HTTP 200**.

### Dua hal yang mudah salah

**Build `launcher.py`, jangan `app.py`.**

```powershell
# SALAH — app.py dieksekusi sebagai script biasa, TIDAK ada server, TIDAK ada UI
pyinstaller app.py --onefile --windowed

# BENAR
streamlit-desktop-app build launcher.py --name SpotDL --pyinstaller-options --onefile --noconfirm
```

Yang salah akan mencetak `missing ScriptRunContext! running in bare mode` lalu
keluar. `build_exe.bat` sudah menjalankan yang benar.

**`app.py` tidak boleh punya BOM UTF-8.** `import app` tetap jalan normal, tapi
`ast.parse()` — yang dipanggil `streamlit-desktop-app` saat build — menolaknya
dengan `invalid non-printable character U+FEFF`. Build gagal total padahal
seluruh test hijau. BOM ini pernah ada dan sudah dibuang; `.gitattributes`
mencegah editor menulisnya kembali. `build_exe.bat` juga memeriksanya sebelum
build dan berhenti dengan pesan jelas.

### Ukuran jendela

`streamlit-desktop-app` membuat **wrapper-nya sendiri** saat build, memakai
`--name` sebagai judul dan **default 1024x768** — konstanta `WINDOW_WIDTH`/
`WINDOW_HEIGHT` di `launcher.py` tidak terpakai di dalam `.exe`. Ukuran itu
hanya berlaku saat menjalankan dari source:

```powershell
.venv\Scripts\python launcher.py    # jendela "Spotify Playlist Downloader" 1280x860
```

### ffmpeg

`providers/youtube.py::ffmpeg_path()` mencari `bin/ffmpeg.exe` lebih dulu, baru
PATH. Build script meneruskan `--add-data` supaya binary ikut terbawa — tanpa
itu PyInstaller **tidak** mengambil binary yang sekadar ada di disk, dan `.exe`
akan gagal saat download di PC tanpa ffmpeg.

Gunakan build **imageio-ffmpeg (88 MB)**, bukan build "minimal" 4 MB: yang
minimal **tidak punya `libmp3lame`** dan konversi MP3-nya gagal total.

---

## Test

```powershell
.venv\Scripts\python.exe tests\smoke.py              # 15 cek, offline
.venv\Scripts\python.exe tests\test_youtube.py       # 71 cek, offline
.venv\Scripts\python.exe tests\test_spotify_embed.py # 36 cek, offline
.venv\Scripts\python.exe tests\test_spclient.py      # 115 cek, offline
.venv\Scripts\python.exe tests\test_tags.py          # tag ID3 + cover, offline
.venv\Scripts\python.exe tests\test_cover_size.py    # 22 cek, offline
.venv\Scripts\python.exe tests\test_theme.py         # 51 cek, offline
.venv\Scripts\python.exe tests\test_fetch_bytes.py   # 12 cek, offline
.venv\Scripts\python.exe tests\test_oauth.py         # 32 cek, offline
.venv\Scripts\python.exe tests\test_covers.py        # 34 cek, offline
.venv\Scripts\python.exe tests\test_app.py           # end-to-end UI (Mock)
```

Total **418 cek**. Semuanya offline — tidak perlu jaringan, Chrome, atau
credential. Payload Spotify/YouTube yang tertangkap disimpan di
`tests/fixtures/`.

Untuk cek manual provider YouTube (butuh internet + ffmpeg):

```powershell
.venv\Scripts\python.exe -c "from providers.youtube import YouTubeClient; print(YouTubeClient().load_tracks('https://open.spotify.com/album/1FZKIm3JVDCxTchXDo5jOV').title)"
```

## Dokumentasi tambahan

Catatan pengembangan ada di `docs/`:

| File | Isi |
|---|---|
| `docs/prd.md` | Product requirements (versi awal) |
| `docs/to-do.md` | Daftar tugas |
| `docs/REVISI_BARU.md` | Catatan revisi R0–R4 + status verifikasi |
| `docs/CATATAN_REVISI.md` | Catatan revisi terakhir |
| `docs/PROMPT_OPENCODE_*.md` | Prompt yang dipakai untuk mendelegasikan tiap tahap ke OpenCode |

File `PROMPT_OPENCODE_*.md` disimpan sebagai jejak: tiap prompt berisi diagnosis
akar masalah, bukti, dan kriteria verifikasi yang dipakai saat tahap itu
dikerjakan.
