# Spotify Playlist Downloader (Streamlit) — YouTube (yt-dlp) backend

Web app **untuk penggunaan pribadi**: tempel URL Spotify (playlist / album /
lagu), lihat daftar lagunya, lalu unduh sebagai MP3 (satuan atau ZIP).

## Cara kerjanya

```
Daftar lagu  : halaman embed publik Spotify  ->  open.spotify.com/embed/...
Audio        : yt-dlp cari + unduh dari YouTube, ffmpeg konversi ke MP3
```

Jadi **audio berasal dari YouTube, bukan dari Spotify**. Aplikasi ini tidak
punya database MP3 dan bukan scraper Spotify: dia cuma mencari video yang
cocok di YouTube lalu mengunduhnya.

| Backend | Status | Catatan |
|---|---|---|
| **YouTube via yt-dlp** | **default** | Tanpa browser, tanpa CAPTCHA, jalan di VPS |
| SpotiDown.co | legacy | Butuh Chrome terpasang & jendela terbuka |
| SoundLoaders | legacy | Butuh token Cloudflare manual |
| SpotiDown.app | legacy | Butuh token reCAPTCHA manual |
| Demo (Mock) | offline | Data contoh, tanpa jaringan |

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

Kalau kamu butuh playlist private, isi credential Web API:

1. Buka <https://developer.spotify.com/dashboard> → buat app
   (Spotify mewajibkan akun **Premium** untuk app sejak Februari 2026).
2. Salin **Client ID** dan **Client Secret**.
3. Salin `.env.example` jadi `.env` lalu isi:

```
SPOTIFY_CLIENT_ID=xxxx
SPOTIFY_CLIENT_SECRET=yyyy
```

`.env` sudah ada di `.gitignore` — **jangan pernah di-commit**.

> Catatan jujur: sejak perubahan Spotify Februari 2026, token Client
> Credentials **tidak lagi bisa membaca isi playlist** (`/playlists/{id}/items`
> → 401). Jadi jalur Web API hanya membantu untuk lagu & album; playlist publik
> lebih baik lewat halaman embed.

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
  spotify_meta.py    <-- DEPENDENCY: Spotify Web API (fallback, butuh .env)
  spotidown_co.py    <-- DEPENDENCY: Chrome via CDP ke spotidown.co (legacy)
  soundloaders.py    <-- DEPENDENCY: request ke SoundLoaders (legacy)
  spotidown.py       <-- DEPENDENCY: request ke spotidown.app (legacy)
  parsing.py                 parser HTML toleran (markup bisa berubah)
  mock.py                    provider demo tanpa jaringan
ui/
  data.py                    adapter hasil provider -> dict untuk 5 halaman UI
  dummy.py                   data dummy untuk demo offline
tests/
  smoke.py                   unit fungsional (parser, orchestrator, i18n)
  test_youtube.py            unit provider YouTube (scoring, lokal, ffmpeg)
  test_spotify_embed.py      unit parser embed + fixture nyata
  test_spotidown_co.py       unit provider SpotiDown.co (legacy)
  fixtures/                  payload nyata yang tertangkap, untuk test offline
tools/
  spotidown_grab.py          skrip CLI referensi (legacy, tidak dipakai app)
```

### Halaman UI

1. **Home** — tempel URL playlist sekali, dipakai semua halaman selama sesi.
2. **Download Playlist** — batch per Part (maks 100 lagu/Part) → satu ZIP.
3. **Download Lagu** — grid card + search + centang → unduh per lagu atau ZIP.
4. **Download Song Cover** — grid cover + search + centang → ZIP gambar.
5. **Backup** — export metadata TXT / JSON / CSV.

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
- `yt-dlp` — search & download audio dari YouTube
- `requests` — HTTP client (cover art, provider legacy)
- `beautifulsoup4` — parsing HTML respon provider
- `lxml` — parser HTML cepat untuk BeautifulSoup (fallback ke `html.parser`)
- `jinja2` — dependency ekosistem Streamlit
- `playwright` — hanya untuk backend legacy SpotiDown.co

### Di mana ketergantungan ke layanan luar berada

- **YouTube** — hanya di `providers/youtube.py`, lewat `yt_dlp`.
- **Spotify** — hanya di `providers/spotify_embed.py` (halaman embed publik)
  dan `providers/spotify_meta.py` (Web API). Baca docstring `DEPENDENCY NOTE`
  di masing-masing.
- **spotidown.co** — hanya di `providers/spotidown_co.py`.
- **SoundLoaders / spotidown.app** — hanya di `providers/soundloaders.py` dan
  `providers/spotidown.py`.

### Backend legacy SpotiDown.co

Masih bisa dipilih di sidebar, dan butuh:

- **Chrome terpasang**, jendela **terbuka terlihat** (tidak headless) — syarat
  mutlak, Cloudflare menolak browser yang terdeteksi otomatisasi.
- Jangan tutup/minimize jendela Chrome saat proses berjalan.
- Provider menjalankan Chrome sendiri lalu attach via CDP
  (`--remote-debugging-port`). **Jangan** menggantinya dengan
  `playwright.chromium.launch()` — selalu ditolak Cloudflare.
- Hanya boleh satu tab spotidown.co terbuka.
- `/search` sesekali membalas HTTP 500 lalu berhasil di percobaan berikutnya;
  provider otomatis reload dan mencoba lagi (maks 4×).
- Link MP3 cepat kedaluwarsa → download harus langsung setelah playlist dimuat.

### Backend legacy SoundLoaders / SpotiDown.app

Keduanya butuh token CAPTCHA yang **terikat session browser** pemegangnya, jadi
tidak bisa dipakai dari proses server — itu alasan utama keduanya tidak lagi
jadi default. Token hanya bisa dibuat oleh widget aslinya di browser; app
menyediakan snippet console (F12) untuk mengambilnya, tidak auto-solve.

<details>
<summary>Detail alur token CAPTCHA (backend legacy)</summary>

Verifikasi nyata:

- SoundLoaders kini memakai **Cloudflare Turnstile** (sitekey ada di halamannya).
  Route lama `POST /api/userverify` — yang ada di PRD — sudah **404** (kode
  fallback di `script.js` mereka juga dead code). Tanpa token Turnstile,
  `POST /action` menjawab `{"status":false,"error":"CAPTCHA verification failed."}`.
- SpotiDown memakai **Google reCAPTCHA v3** + hidden field `_uMihH`. Tanpa token,
  `POST /action` menjawab `{"error":true,"message":"Please Refresh the page &
  try again.","errorcode":"error_token"}`.

Token captcha hanya bisa dibuat widget captcha di browser asli — tidak ada API
server-side murni yang sah. Karena itu app ini **tidak auto-solve**; sidebar
menyediakan kolom token opsional (BYO) plus **snippet console (F12)** untuk
mengambil token dari browser Anda.

#### Cara mengambil token CAPTCHA (BYO flow yang benar)

> ⚠️ Token Turnstile/reCAPTCHA **hanya berlaku SATU KALI & ±5 menit**
> (aturan Cloudflare/Google). Sekali token dikirim ke situsnya, token itu
> hangus untuk app (`timeout-or-duplicate`). Snippet di app ini **tidak pernah
> auto-submit form** (itu penyebab redirect anti-bot dulu).

**SoundLoaders (Turnstile):**
1. Buka `https://soundloaders.app/` di Chrome/Edge. **JANGAN klik Download
   di situs itu** — itu memakai tokennya duluan sebelum app sempat pakai.
2. Tekan `F12` → tab **Console**.
3. Tempel **snippet Turnstile** (ada di app: sidebar → *Cara ambil token*) →
   `Enter`. Snippet me-reset widget untuk menerbitkan token fresh, lalu
   menunggu (maks 60 dtk). Kalau situs melempar ke halaman anti-bot, kembali
   ke `soundloaders.app` lalu ulangi.
4. **Selesaikan centang Turnstile** yang muncul. Token fresh otomatis
   **tersalin ke clipboard** & tercetak dengan label `SOUNDLOADERS_TOKEN`.
5. Tempel token itu ke kolom **Token CAPTCHA** di sidebar app ini → klik
   **Proses / Tampilkan Daftar Lagu** dalam ±5 menit. Jangan klik Download
   di situs sesudah copy.

**SpotiDown (reCAPTCHA v3):**
1. Buka `https://spotidown.app/` di browser.
2. Tempel URL Spotify Anda di situs itu, klik **Download** sekali (biarkan
   prosesnya) — ini mengaktifkan reCAPTCHA v3 + cookie sesi.
3. Tekan `F12` → tab **Console** → jalankan **snippet reCAPTCHA** → `Enter`.
4. Token tercopy ke clipboard & tercetak dengan label `SPOTIDOWN_TOKEN`.
5. Tempel ke kolom **Token CAPTCHA** di sidebar → klik **Proses**.

Catatan penting:
- Token **single-use & kedaluwarsa ±5 menit**, terikat sesi browser Anda —
  langsung gunakan sebelum kedaluwarsa, dan jangan kirim token yang sama
  ke situsnya dulu.
- Kalau token kosong/salah/kedaluwarsa, app **tidak crash**: muncul pesan merah
  "CAPTCHA / token diperlukan" plus detail error dari service (termasuk
  `token_len` yang terkirim, untuk memastikan token kepotong atau tidak).
- Tidak ada jaminan layanan menerima request server-side walau token valid
  (mereka bisa cek IP/cookie tambahan).

#### Kalau token mati di tengah jalan (refresh/retry)

Satu token untuk menampilkan daftar lagu bisa expired saat lagu ke-N
di-download (halaman/aksi baru = token baru). App menangani ini tanpa
mengulang dari awal:

1. Tiap lagu yang gagal dicatat jenisnya: `[token]` (captcha expired/invalid),
   `[fetch]` (MP3 ketemu tapi file gagal diunduh), `[service]` (lainnya).
2. Sidebar menampilkan **umur token** ("fresh" vs "kemungkinan KEDALUWARSA
   (>4 mnt)") supaya jelas kapan harus ambil baru.
3. Selama hasil batch masih ada yang gagal, muncul panel **"Retry N gagal
   dengan token baru"**: solve CAPTCHA lagi → tempel token fresh di sidebar
   → klik retry. Hanya lagu gagal yang di-request ulang (sesi/cookie yang
   sama dipakai ulang supaya `track_token` tetap valid), dan MP3 yang pulih
   **digabung ke ZIP yang sudah ada** (`BatchOrchestrator.retry_failed`).

### Risiko / kapan app ini berhenti bekerja

- Service **down / rate-limit / memblokir IP** → request gagal; app hanya bisa
  menampilkan error. Tidak ada fallback lokal karena kita memang tidak punya
  scraper sendiri.
- Markup hasil `/action` **berubah** → parser `providers/parsing.py` menyerah
  pada data yang tidak dikenal (row tanpa `data`/`track_token` dibuang), tidak
  crash, tapi daftar bisa kosong.
- Captcha mengeras (Turnstile interaktif, dsb.) → token dari browser mungkin
  tidak cukup; error `CAPTCHA` muncul dan tidak bisa diatasi dari sisi server.
- Endpoint baru ditutup / butuh auth → app harus diperbarui mengikuti `script.js`
  service tsb.

SpotiDown juga punya endpoint ZIP sendiri (`/action/bulktrack`,
`/action/create_zip`) yang **dibatasi 5 lagu untuk free** — app ini sengaja
**tidak** memakainya; ZIP dibuat lokal di `core/orchestrator.py`.

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

## Test

```powershell
.venv\Scripts\python.exe tests\smoke.py              # 25 cek, offline
.venv\Scripts\python.exe tests\test_youtube.py       # 27 cek, offline
.venv\Scripts\python.exe tests\test_spotify_embed.py # 35 cek, offline
.venv\Scripts\python.exe tests\test_spotidown_co.py  # 42 cek, offline
.venv\Scripts\python.exe tests\test_app.py           # end-to-end UI (Mock)
```

Semuanya offline — tidak perlu jaringan, Chrome, atau credential. Payload
Spotify/YouTube yang tertangkap disimpan di `tests/fixtures/`.

Untuk cek manual provider YouTube (butuh internet + ffmpeg):

```powershell
.venv\Scripts\python.exe -c "from providers.youtube import YouTubeClient; print(YouTubeClient().load_tracks('https://open.spotify.com/album/1FZKIm3JVDCxTchXDo5jOV').title)"
```
