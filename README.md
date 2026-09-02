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

Verifikasi nyata (Juli 2026):

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
mengambil token dari browser Anda, sesuai pola `cftoken` yang dipakai `script.js`
SoundLoaders dan `grecaptcha.execute(...)` di SpotiDown.

Jika token tidak diisi dan layanan menolak, app menampilkan pesan error yang
jelas (bukan crash) dan menyarankan langkah berikutnya.

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
