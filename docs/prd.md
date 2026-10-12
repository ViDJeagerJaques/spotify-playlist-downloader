# PRD — Spotify Playlist Downloader (Streamlit Clone, SoundLoaders Backend)

**Tanggal:** 2026-08-30  
**Pembuat:** [Ruang kerja kode Anda]  
**Status:** Draft untuk dikonsultasikan dengan Claude  
**Target:** Web app (Streamlit) untuk personal use  
**Lokasi folder:** `E:\COOLYEAH\Coding\spotify-playlist\`


## 1. Ringkasan Produk

- **Nama:** Spotify Playlist Downloader (Streamlit Clone, SoundLoaders Backend)
- **Tipe:** Web app (Streamlit) untuk personal use
- **Nilai utama:** User bisa panen daftar lagu dari playlist Spotify lewat SoundLoaders, lalu download lagu per track atau batch semua lagu sekaligus, tanpa premium gate di dalam aplikasi kita.
- **Catatan penting:** Backend sebenarnya **mengandalkan SoundLoaders.app** (layanan pihak ketiga). Jadi "tanpa premium" di aplikasi kita **tidak menjamin** SoundLoaders nggak ada batasan; kita hanya menyiapkan interface & orchestrasi batch. Aplikasi kita bersifat **tanggung jawab atas service dependency**. Aplikasi diri kita **tidak memiliki scraper Spotify dari nol**.


## 2. Fitur Inti (Wajib)

- Input URL Spotify (track / album / playlist / artist / short link).
- Pilih backend service: **SoundLoaders** (utama) / **SpotiDown** (cadangan).
- Parse playlist → tampilkan daftar lagu (judul, artist, thumbnail, track_token).
- **Batch trigger:** tombol "Download All" yang otomatis loop `/action/tracks` per lagu.
- Download per-track: klik download lagu tertentu (mimic kode Mori: POST `/action/tracks` → dapat link MP3).
- Download progress / status (per lagu): waiting / processing / ready / gagal.
- History (list download terakhir) + folder management.
- UI sederhana, tanpa premium gate, tanpa prompt upgrade di dalam aplikasi kita.


## 3. Platform yang Didukung (Wajib)

- **Spotify** (track, album, playlist, artist, short link) → via SoundLoaders backend.
- **Cadangan:** SpotiDown (kalau SoundLoaders nggak work / user mau pilih lain).


## 4. Arsitektur Teknis (High-Level)

### Frontend (Streamlit)

- Input URL Spotify.
- Dropdown pilih service (SoundLoaders / SpotiDown).
- Button "Proses Playlist" → parse playlist.
- List lagu yang muncul → tombol "Download All" + download per lagu.
- History table.
- Log/console kecil (untuk debug).

### Backend Logic (Python)

#### SoundLoaders Client Module (mimic kode `spotify.js`)

- Fetch `https://soundloaders.app/` → ambil cookies.
- POST `https://soundloaders.app/api/userverify` → dapat token.
- POST `https://soundloaders.app/action` dengan payload `{url, cftoken: token}` → dapat HTML playlist.
- Parse HTML → ekstrak list track (data, track_token, title, artist, thumbnail).
- Untuk tiap track: POST `https://soundloaders.app/action/tracks` dengan payload `{data: track.data, track_token: track.track_token}` → dapat link download MP3 per track.
- Rumus batch: loop semua track → POST `/action/tracks` satu per satu → kumpulkan link MP3.

#### SpotiDown Client Module (Cadangan)

- Fetch `https://spotidown.app/` → ambil cookies.
- Parse form `spotifyurl`, kumpulkan input values, set `g-recaptcha-response: "dummy_token"`.
- POST `https://spotidown.app/action` → HTML → parse form `submitspurl`.
- Single track: POST `https://spotidown.app/action/track` → link download MP3.

#### Output

- Link MP3 per track.
- Opsi download langsung: Streamlit download button per item, atau zip paket per playlist (opsional).


## 5. Service Dependency (Wajib Disebutkan ke Claude)

- **Aplikasi ini TIDAK memiliki scraper Spotify dari nol.**
- Backend nyata = SoundLoaders.app (atau cadangan SpotiDown).
- Kalau SoundLoaders down / berubah / rate-limit / ngeblokir request → aplikasi kita **tidak jalan**.
- Kalau SoundLoaders require recaptcha / auth / batas download → kita terima apa adanya dari service, kita tidak bisa override dari aplikasi kita.
- Kamu wajib test nyata: apakah `/api/userverify` butuh recaptcha, apakah `/action` butuh cookies live, apakah `/action/tracks` work tanpa limit.
- Kamu wajib akses nyata ke service tersebut (bukan cuma kode).


## 6. Batasan & Trade-off (Wajib Disebutkan ke Claude)

- **"Tanpa premium gate" di aplikasi kita** → kita tidak implementasi upgrade/paid di dalam app kita sendiri.
- **Tapi service SoundLoaders bisa saja punya batasan** (misal: limit lagu gratis, ada recaptcha, ada freemium). Kita terima apa adanya dari service; kita tidak bisa override dari aplikasi kita.
- **Ketergantungan eksternal:** kalau service mati / berubah, aplikasi mati.
- **Legal & ToS:** download dari Spotify via layanan pihak ketiga bisa melanggar ToS. Build untuk personal use saja, bukan redistribusi / publik.
- **Recaptcha:** dari kode Mori, terlihat `g-recaptcha-response: "dummy_token"`. Kalau SoundLoaders nyata-hard recaptcha, request kita bisa fail. Ini wajib dicoba/test nyata.


## 7. UI/UX (Diusulkan)

- Input URL Spotify di bagian atas.
- Dropdown pilih backend (SoundLoaders / SpotiDown).
- Tombol **"Proses Playlist"** → loading → muncul daftar lagu.
- Setiap lagu: tombol "Download" individual.
- Tombol **"Download Semua (Batch)"** → otomatis trigger loop `/action/tracks` per lagu.
- Progress indicator (per track: waiting / processing / ready / gagal).
- History: list download terakhir, url, status.
- Folder output: user pilih folder, atau download langsung per browser.


## 8. Technical Scope untuk Claude

> "Buatlah Streamlit app sesuai PRD ini.

> Fokus:
> 
> 1. Input URL Spotify → parse → tampilkan daftar lagu (SoundLoaders flow).
> 
> 2. Backend client module untuk SoundLoaders:
>    - Fetch `https://soundloaders.app/` → ambil cookies.
>    - POST `https://soundloaders.app/api/userverify` → dapat token.
>    - POST `https://soundloaders.app/action` dengan `{url, cftoken: token}` → dapat HTML playlist.
>    - Parse HTML: ekstrak list track (data, track_token, title, artist, thumbnail).
>    - POST `https://soundloaders.app/action/tracks` dengan `{data: track.data, track_token: track.track_token}` → dapat link MP3 per track.
> 
> 3. Batch orchestrator: loop semua track → POST `/action/tracks` per track → kumpulkan link MP3 → tampilkan download buttons per track (atau zip).
> 
> 4. UI tanpa premium gate: tidak ada fitur upgrade/paid di dalam app kita.
> 
> 5. Optional cadangan: modul SpotiDown (fetch `spotidown.app`, parse form `spotifyurl`, POST `/action`, POST `/action/track`).
> 
> 6. Jelaskan di kode: di mana letak dependency ke SoundLoaders, apa risiko kalau service down / berubah / rate-limit / recaptcha-hard.
> 
> 7. Jelaskan: ini personal use, tidak ada scraper Spotify sendiri, bergantung ke layanan pihak ketiga.
> 
> 8. Sertakan disclaimer legal / ToS.
> 
> Implementasi harus bisa dijalankan (`streamlit run`), tapi backend nyata tetap depend on SoundLoaders.app. Kalau service nggak work, aplikasi harus handle graceful (error message, bukan crash)."


## 9. Accept Criteria

- User bisa paste URL playlist Spotify → aplikasi tampilkan daftar lagu (via SoundLoaders backend).
- User bisa klik "Download All" → aplikasi loop `/action/tracks` per lagu → tampilkan link MP3 per lagu (atau trigger download).
- User bisa download satu per satu.
- Aplikasi handle error secara graceful kalau service down / fail.
- Tidak ada premium gate di dalam aplikasi kita.


## 10. Disclaimer & Catatan Legal

- Download konten dari Spotify melalui layanan pihak ketiga **bisa melanggar Terms of Service Spotify & layanan tersebut**.
- Aplikasi ini hanya untuk **personal use**, bukan untuk redistribusi atau publik.
- Aplikasi ini **tidak memiliki scraper Spotify dari nol**, dan tidak menjamin ketersediaan layanan backend.
- User bertanggung jawab sendiri atas penggunaan hasil download.


## 11. Catatan Lanjutan

- Jika setelah testing manual SoundLoaders terdapat recaptcha / limit / error tertentu, update PRD ini sebelum diberikan ke Claude.
- Jika SoundLoaders gagal (limit/recatpcha/limit lagu), konsdi alternatif lain atau ganti pendekatan.
- Kamu bisa meletakan file ini di `E:\COOLYEAH\Coding\spotify-playlist\prd.md` sebagai bahan utama saat kerjain dengan Claude.
