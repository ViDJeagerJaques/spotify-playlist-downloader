# To-Do: Spotify Playlist Downloader (Streamlit)

## Fase 1: Testing Manual SoundLoaders
- [ ] Tes akses https://soundloaders.app/ dari browser
- [ ] Tes /api/userverify (ada recaptcha? response token?)
- [ ] Tes /action dengan URL playlist (response HTML?)
- [ ] Tes /action/tracks untuk satu lagu (response MP3 link?)
- [ ] Catat apakah ada limit, recaptcha, atau error tertentu

## Fase 2: Implementasi Streamlit
- [ ] Buat `app.py` sesuai prompt ke Claude
- [ ] Implementasi SoundLoaders client module
- [ ] Implementasi UI, parse playlist, batch orchestrator
- [ ] Tambahkan UI tanpa premium gate
- [ ] Tambahkan disclaimer legal/ToS
- [ ] Test `streamlit run` di lokal

## Fase 3: Testing Awal
- [ ] Test input URL playlist → lihat apakah daftar lagu muncul
- [ ] Test download per track
- [ ] Test batch download
- [ ] Test error handling (kalau service down)

## Fase 4: Iterasi
- [ ] Jika ada bug / ketergantungan service bermasalah, update kode atau cari alternatif
- [ ] Kalau SoundLoaders nggak work / ada limit/recatpcha, cari alternatif lain atau update PRD

## Catatan
- File PRD: prd.md
- File Streamlit utama (setelah Claude coding): app.py
- Folder ini: E:\COOLYEAH\Coding\spotify-playlist\
