# Spotify Playlist Downloader (Streamlit) — SoundLoaders / SpotiDown backend

Web app **untuk penggunaan pribadi** yang mengubah URL Spotify (track / album /
playlist / artist / short link) menjadi daftar lagu lalu memungkinkan download
per-track atau batch, **tanpa** menulis scraper Spotify sendiri.

Aplikasi ini **bukan** downloader mandiri — seluruh resolusi Spotify didelegasikan
ke layanan pihak ketiga:

| Backend | Status | Endpoint yang dipakai |
|---|---|---|
| [SoundLoaders](https://soundloaders.app/) | utama | `POST /action` (daftar track), `POST /action/tracks` (MP3 per track) |
| [SpotiDown](https://spotidown.app/) | cadangan | `POST /action` (daftar track), `POST /action/track` (MP3 per track) |
| Demo (Mock) | offline | data contoh, untuk mencoba UI tanpa jaringan |

## Menjalankan

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Struktur kode

```
app.py                       Streamlit UI (state, rendering, error handling)
core/
  orchestrator.py            loop resolve per-track + bundel ZIP lokal (batch)
  i18n.py                    string UI bilingual (Indonesia / English)
  cleanup.py                 hapus file sementara batch
providers/
  base.py                    tipe data Track/ResolveResult + kelas error
  soundloaders.py  <-- DEPENDENCY: satu-satunya tempat request ke SoundLoaders
  spotidown.py      <-- DEPENDENCY: satu-satunya tempat request ke SpotiDown
  parsing.py                 parser HTML toleran (markup bisa berubah)
  mock.py                    provider demo tanpa jaringan
  _http.py                   helper session/headers
tests/
  smoke.py                   unit fungsional (parser, orchestrator, i18n) — offline
  test_app.py                end-to-end Streamlit AppTest memakai Mock provider
```

### Dependencies

Tercantum di `requirements.txt`:

- `streamlit` — web UI
- `requests` — HTTP client ke SoundLoaders / SpotiDown
- `beautifulsoup4` — parsing HTML respon provider
- `lxml` — parser HTML cepat untuk BeautifulSoup (jika tidak terpasang, kode
  otomatis fallback ke `html.parser` bawaan Python)
- `jinja2` — dependency ekosistem Streamlit, dicantumkan eksplisit agar versi
  konsisten

Install:

```powershell
pip install -r requirements.txt
```

### Di mana ketergantungan ke SoundLoaders/SpotiDown berada

Tepat di `providers/soundloaders.py` dan `providers/spotidown.py` (baca
docstring `DEPENDENCY NOTE` di sana). Alurnya:

1. `GET <home>` → ambil cookie session (`session_data`) — dan untuk SpotiDown,
   nilai anti-CSRF `_uMihH` yang dikeluarkan per-halaman.
2. `POST /action` dengan URL Spotify (+ `cftoken` untuk SoundLoaders /
   `g-recaptcha-response` untuk SpotiDown) → HTML daftar lagu.
3. Parse HTML → list track (`data`, `track_token`, judul, artis, thumbnail).
4. Per lagu: `POST /action/tracks` (SoundLoaders) atau `POST /action/track`
   (SpotiDown) → link MP3. **Batch** = mengulang langkah ini untuk semua lagu
   (`core/orchestrator.py`), lalu membungkus file MP3 lokal menjadi ZIP.

### Kenapa ada kolom "Token CAPTCHA" (BYO token)

Verifikasi nyata (diperbarui):

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

## Disclaimer legal / ToS

Tampil juga di UI (expander "Disclaimer & Catatan Legal"):

- Hanya untuk **penggunaan pribadi**; jangan redistribusi atau publikasi.
- Aplikasi ini **tidak punya scraper Spotify** dan bergantung penuh ke layanan
  pihak ketiga; tidak ada jaminan ketersediaan/kualitas.
- Mengunduh musik dari Spotify lewat alat pihak ketiga **dapat melanggar** ToS
  Spotify maupun layanan tsb — periksa hukum setempat Anda.
- Tanggung jawab penggunaan ada pada pengguna.

## Test

```powershell
.venv\Scripts\python.exe tests\smoke.py       # unit fungsional (offline)
.venv\Scripts\python.exe tests\test_app.py    # end-to-end UI (Mock provider)
```
