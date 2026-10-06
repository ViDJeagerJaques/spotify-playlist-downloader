# Prompt untuk OpenCode — Integrasi SpotiDown.co ke Aplikasi

> Copy seluruh isi file ini, paste ke OpenCode.

---

## JAWABAN UNTUK PERTANYAAN PILIHAN

Kalau OpenCode nanya "Provider baru ini harus disambungkan ke mana?", pilih:

> **Sambungkan ke UI 5 halaman (Recommended)**

**Alasannya:** UI 5 halaman baru saja dibuat dan strukturnya bagus. Semua halaman
bisa diisi data asli (cover dan metadata semuanya tersedia di response API).
Legacy (`handle_process`, `show_results`, `_run_batch`) tetap dipertahankan
sebagai cadangan tapi tidak dipakai.

---

## TUGAS

Integrasikan provider **SpotiDown.co** ke aplikasi Streamlit di
`E:\COOLYEAH\Coding\spotify-playlist\`.

**JANGAN bikin dari awal.** Modifikasi file yang sudah ada. Baca dulu:

- `app.py` — UI utama (5 halaman mock + legacy backend)
- `ui/dummy.py` — data dummy yang harus DIGANTI dengan data asli
- `providers/base.py` — interface & tipe data
- `providers/spotidown.py` — provider lama (BEDA situs, jangan ketuker)
- `providers/soundloaders.py` — provider lama
- `core/orchestrator.py` — batch download + ZIP
- `tools/spotidown_grab.py` ← **REFERENSI UTAMA, sudah terbukti jalan**

---

## KONDISI APP SAAT INI

`app.py` punya **dua bagian**:

### Bagian 1 — UI 5 halaman (BARU, mock-only)

Navigasi di `sidebar_nav()`, halaman di dict `PAGES`:

```python
PAGES = {
    "home": "Home",
    "playlist": "Download Playlist",
    "songs": "Download Lagu",
    "covers": "Download Song Cover",
    "backup": "Backup",
}
```

| Halaman | Fungsi sekarang | Fungsi nanti |
|---|---|---|
| `page_home()` | Input URL → load data dummy | Input URL → **load playlist asli** |
| `page_playlist()` | Bagi per Part (15/Part), tombol mock | **Batch download asli + ZIP** |
| `page_songs()` | Grid + search + checkbox, mock | **Download lagu terpilih (asli)** |
| `page_covers()` | Grid cover + search, mock | **Download cover terpilih (asli)** |
| `page_backup()` | Preview TXT/JSON/CSV, mock | **Export metadata asli** |

Semua data dummy berasal dari `ui/dummy.py` (`get_dummy_playlist()`, `_DUMMY_TRACKS`).

### Bagian 2 — Legacy backend (dipertahankan, tidak dipakai)

`handle_process()`, `show_results()`, `_render_track_row()`, `_resolve_one()`,
`_run_batch()`, `_retry_batch()`, `_show_batch_result()`, `show_legal()`.

**JANGAN HAPUS.** Biarkan sebagai cadangan.

---

## LATAR BELAKANG TEKNIS

Provider lama (`soundloaders.app`, `spotidown.app`) **gagal** karena token CAPTCHA
mereka nggak bisa dipakai dari server — token Turnstile nempel ke session browser
(cookie + IP), sedangkan Streamlit jalan di server dengan identitas berbeda.

Provider baru: **`spotidown.co`** (BUKAN `spotidown.app` — beda situs).
Cara kerjanya sudah ketemu dan sudah terbukti jalan end-to-end
(tes 3 playlist: 2, 75, dan 100 lagu — sukses 96-97%).

**Baca `tools/spotidown_grab.py` sampai paham** — itu implementasi referensinya.

---

## CARA KERJA YANG SUDAH TERBUKTI

### 1. Launch Chrome sendiri, JANGAN lewat Playwright

```python
# BENAR — nggak ada fingerprint otomatisasi, Cloudflare lolos
subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "--remote-debugging-port=9222",
    f"--user-data-dir={PROFILE_DIR}",
    "--no-first-run", "--no-default-browser-check",
    "about:blank",
])

# LALU attach lewat CDP
browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
```

**JANGAN** pakai `playwright.chromium.launch()` — sudah dicoba 6 kali, selalu
ditolak Cloudflare (`No available adapters`, widget Turnstile nggak pernah render).

### 2. Alur di dalam browser

1. Buka `https://spotidown.co/en16`
2. Isi `input.link` dengan URL playlist
3. Klik `button.search-btn`
4. **Tunggu sambil polling** (WAJIB — lihat Jebakan 1)
5. Tangkap response `api.spotidown.co/search/...`

### 3. Bentuk response JSON (SUDAH DIKETAHUI)

```json
{
  "type": "playlist",
  "id": "0OAWLZxZydByuXyVuCszKT",
  "name": "Jjj",
  "totalCount": 2,
  "timeTaken": 1046,
  "canShowDonate": true,
  "tracks": [
    {
      "id": "5Ohxk2dO5COHF1krpoPigN",
      "name": "Sign of the Times",
      "artists": ["Harry Styles"],
      "duration": 340706,
      "album": {
        "name": "Harry Styles",
        "releaseDate": "2017-05-12",
        "coverUrl": "https://i.scdn.co/image/ab67616d0000b273..."
      },
      "audio": {
        "url": "https://api.spotidown.co/savemp3/...?sig=...",
        "size": 13628240
      }
    }
  ]
}
```

**PENTING:** tiap track **sudah punya link MP3 langsung** di `audio.url`.
Tidak perlu request per-track seperti SoundLoaders.

**Pemetaan ke UI:**
- `name` + `artists` → judul & artist (halaman songs, playlist)
- `album.coverUrl` → **cover** (halaman covers) ← sudah tersedia!
- `duration` → durasi (ms, bagi 1000 untuk detik)
- `audio.url` → link download
- `totalCount` vs `len(tracks)` → **deteksi pemotongan** (lihat Batasan 1)

### 4. Download MP3

`audio.url` redirect (HTTP 302) ke CDN `*.123tokyo.xyz`, dan **bisa didownload
pakai curl biasa dari server** — nggak ada CAPTCHA di link download.

```bash
curl -sL --fail -H "User-Agent: <chrome UA>" \
  -H "Origin: https://spotidown.co" \
  -H "Referer: https://spotidown.co/" \
  -o out.mp3 "<audio.url>"
```

---

## JEBAKAN YANG WAJIB DITANGANI

Sudah ketemu lewat trial-and-error. **Jangan diulang lagi.**

### Jebakan 1 — Tab di-throttle Chrome

Kalau nunggu pakai `time.sleep()` doang, Chrome nge-throttle tab background →
Turnstile nggak jalan → nyangkut di "Searching..." selamanya.

**Solusi:** polling `page.evaluate()` terus-terusan selama nunggu:

```python
while time.time() < deadline and not captured:
    page.evaluate("() => document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length")
    time.sleep(0.4)
```

### Jebakan 2 — Cuma boleh SATU tab spotidown

Kalau ada lebih dari satu tab `spotidown.co`, script `api.js` Cloudflare ke-load
dua kali → `window.turnstile` jadi `undefined` → `main.js` mereka crash di
`turnstile.render()` → nyangkut.

**Solusi:** tutup semua tab spotidown dulu sebelum buka tab baru.

### Jebakan 3 — CDN nolak request secara ACAK

CDN `123tokyo.xyz` nolak sebagian request kalau download paralel. Yang gagal
**beda-beda tiap run** (bukan lagu tertentu).

**Solusi:**
- Paralel maksimal 3
- Retry 4x dengan jeda + jitter
- Setelah pass paralel, **retry serial satu-satu** untuk yang gagal
- Kalau masih gagal, user bisa jalanin ulang — script skip file yang sudah ada

### Jebakan 4 — Link MP3 expire

`sig` di `audio.url` punya masa berlaku pendek. **Download harus langsung**
setelah JSON didapat. Jangan simpan link-nya buat nanti.

### Jebakan 5 — Chrome kebuka itu LAMBAT

Launch Chrome + load halaman + Turnstile = **~10 detik**. Di UI ini bakal
kelihatan seperti hang.

**Solusi:** tampilkan status yang jelas, misal
`st.spinner("Membuka browser… jangan tutup jendela Chrome yang muncul.")`

---

## YANG HARUS DIKERJAKAN

### A. Provider baru: `providers/spotidown_co.py`

Ikuti interface di `providers/base.py`:

```python
class SpotiDownCoClient:
    name = "SpotiDown.co"
    provider = ProviderId.SPOTIDOWN_CO   # tambah enum baru di base.py

    def load_tracks(self, spotify_url: str, cftoken: str = "") -> ResolveResult:
        """Drive Chrome via CDP, ambil JSON, return ResolveResult."""

    def resolve_track(self, track: Track, cftoken: str = "") -> str:
        """Return audio.url. Tidak perlu request tambahan."""
```

**Catatan arsitektur:** provider ini beda dari yang lain — karena MP3 URL sudah
ada di response awal, `load_tracks()` harus mengisi `Track.mp3_url` **langsung**.
`resolve_track()` cukup mengembalikan nilai itu tanpa network call.

Isi juga `Track.thumbnail` dari `album.coverUrl`.

### B. Update `providers/base.py`

Tambah `SPOTIDOWN_CO = "spotidown_co"` ke enum `ProviderId`.

### C. Update `ui/dummy.py` → ganti dengan data asli

**Ini bagian penting.** Halaman-halaman mock sekarang baca dari `ui_dummy`.
Ubah supaya baca dari hasil provider asli.

- `get_dummy_playlist()` → diganti pemanggilan provider asli
- `_DUMMY_TRACKS` → diganti `result.tracks`
- `chunk_parts()` → tetap dipakai, TAPI `BATCH_LIMIT` harus diubah (lihat D)
- `filter_tracks()`, `to_txt_preview()`, `to_csv_preview()` → tetap dipakai,
  sesuaikan field-nya (`title`/`artist`/`duration` → dari `Track`)

Jangan hapus `ui/dummy.py` — ubah supaya jadi adapter dari data asli, atau
buat modul baru `ui/data.py` dan arahkan halaman-halaman ke sana.

### D. PERBAIKI `BATCH_LIMIT` — angka sekarang SALAH

Di `ui/dummy.py` ada:
```python
BATCH_LIMIT = 15   # ← INI ANGKA KARANGAN
```

Angka 15 itu nggak ada dasarnya. Batas asli dari SpotiDown adalah
**100 track per playlist** untuk free tier.

Ubah supaya:
- Konstanta mencerminkan batas asli (100)
- Kalau `totalCount > len(tracks)` → tampilkan peringatan ke user bahwa
  sisanya butuh premium
- Jangan tampilkan angka yang menyesatkan ke user

### E. Update `app.py`

- Tambah label backend: `ProviderId.SPOTIDOWN_CO.value: "SpotiDown.co (Chrome, tanpa CAPTCHA manual)"`
- Update `_get_provider()` untuk instantiate provider baru
- `page_home()`: ganti `ui_dummy.get_dummy_playlist(url)` → provider asli
- Pesan error jelas kalau Chrome nggak ketemu / nggak bisa di-launch
- Status loading yang informatif (lihat Jebakan 5)

### F. `core/orchestrator.py`

Orchestrator yang ada pakai pola "resolve per track pakai token". Untuk provider
ini MP3 URL sudah tersedia — pastikan **tidak** memanggil `resolve_track()` yang
bikin request sia-sia.

### G. Requirements

Tambah `playwright` ke `requirements.txt`.

---

## BATASAN YANG HARUS DIHORMATI (JANGAN DILANGGAR)

1. **JANGAN bypass fitur premium.** Free tier dibatasi **100 track per playlist**
   — bukti dari response asli: `"totalCount": 213` tapi `"tracks": [100 item]`.
   Batas ini **resmi dan sah**. Kalau playlist > 100 lagu, tampilkan pesan ke
   user bahwa sisanya butuh premium, dan sarankan pecah playlist. **Jangan**
   coba akalin (pagination tersembunyi, parameter tambahan, dsb).

2. **JANGAN bikin scraper Spotify dari nol.** Aplikasi ini cuma interface ke
   layanan pihak ketiga.

3. **JANGAN hapus** provider lama (`soundloaders.py`, `spotidown.py`) atau fungsi
   legacy di `app.py`. Biarkan sebagai cadangan.

4. **JANGAN hardcode credential apa pun.**

5. **JANGAN hapus halaman UI** yang sudah dibuat. Semuanya diisi data asli,
   bukan dibuang.

---

## CATATAN JUJUR YANG HARUS DITULIS DI KODE

Sertakan komentar yang menjelaskan:

- Provider ini **butuh Chrome terinstall** di mesin user
- Chrome akan **terbuka terlihat** (bukan headless) — syarat mutlak, karena
  Cloudflare nolak browser yang ketauan otomatis
- **Ketergantungan eksternal:** kalau `spotidown.co` tutup atau ubah API-nya,
  provider ini mati
- **Batas 100 track** per playlist untuk free tier
- **Link MP3 expire cepat** — harus langsung didownload
- **Legal:** download dari Spotify via layanan pihak ketiga bisa melanggar ToS.
  Untuk **personal use saja**, bukan redistribusi

---

## CARA TEST

```bash
# 1. Smoke test lama harus tetap lolos
.venv/Scripts/python.exe tests/smoke.py

# 2. Test provider baru langsung
.venv/Scripts/python.exe -c "
from providers.spotidown_co import SpotiDownCoClient
c = SpotiDownCoClient()
r = c.load_tracks('https://open.spotify.com/playlist/0OAWLZxZydBuXyVuCszKT')
print(r.title, len(r.tracks))
for t in r.tracks[:3]:
    print(' ', t.artist, '-', t.title, '| mp3:', bool(t.mp3_url), '| cover:', bool(t.thumbnail))
"

# 3. Jalankan app
.venv/Scripts/python.exe -m streamlit run app.py
```

**Kriteria sukses:**
- Smoke test lama tetap lolos
- Provider baru bisa ambil daftar lagu dari playlist nyata
- Tiap track punya `mp3_url` DAN `thumbnail` terisi
- Halaman Home load playlist asli (bukan dummy)
- Halaman Playlist bisa download → jadi ZIP
- Halaman Songs & Covers bisa download item terpilih
- Halaman Backup export metadata asli
- Kalau ada lagu gagal: ada retry + pesan jelas (bukan crash)
- Kalau playlist > 100 lagu: ada peringatan yang jujur

---

## REFERENSI

- **`tools/spotidown_grab.py`** — implementasi yang sudah jalan. **Baca ini dulu.**
- `tools/console_hook.js` — versi console (buat debug manual)
- `tools/probe7.py` — probe pertama yang berhasil

---

## KALAU ADA YANG NGGAK JELAS

Tanya dulu sebelum ngarang.

**Yang sudah PASTI** (jangan ubah asumsinya):
endpoint API, bentuk JSON, cara launch Chrome, dan lima jebakan di atas.

**Yang belum pasti:**
apakah `spotidown.co` konsisten, dan berapa lama `sig` berlaku.
