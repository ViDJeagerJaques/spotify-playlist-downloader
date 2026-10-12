# Prompt untuk OpenCode — Perbaiki Performa Load Playlist

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## MASALAH

User melaporkan: playlist 213 lagu ("Dupe") yang dulu **1.3 detik** sekarang
**bermenit-menit**.

**Terukur (angka nyata, bukan perkiraan):**
```
playlist Dupe (213 lagu):
  WAKTU   : 32.9 detik      (dulu 1.3 detik)
  request : 214
  rata2   : 1183 ms per request

playlist 4 lagu:
  run 1 : 1.97s, 5 request
  run 2 : 3.68s, 5 request   <-- request TIDAK berkurang di run ke-2
```

**Catatan:** lambatnya **wajar sebagian** — R1 (cover per-lagu) dan R4 (album/label)
memang butuh data per lagu, sedangkan dulu hanya 2 request total. Tapi 33 detik
untuk 213 lagu **kegedean** dan bisa diperbaiki.

---

## AKAR MASALAH — dua hal, keduanya sudah didiagnosis

### Akar 1 — `_throttle()` GLOBAL men-serialisasi semua worker

Di `providers/spotify_spclient.py`:

```python
REQUEST_GAP = 0.15          # 150 ms
MAX_WORKERS = 8

def _throttle() -> None:
    global _last_request
    with _gap_lock:                          # <-- LOCK GLOBAL
        delta = time.time() - _last_request
        if delta < REQUEST_GAP:
            time.sleep(REQUEST_GAP - delta)  # <-- SEMUA worker menunggu
        _last_request = time.time()
```

`_get()` memanggil `_throttle()` di **setiap** request (baris ~105).

**Akibatnya:** 8 worker saling menunggu, jadi paralel menjadi **serial**.

**Bukti (8 thread x 5 panggilan = 40 panggilan):**
```
waktu total : 5.86s
kalau paralel sejati : 0.75s
kalau serial         : 6.00s
-> hasil mendekati SERIAL
rata-rata tunggu per panggilan: 684 ms
```

**Lantai waktu = jumlah request x 0.15s:**
```
 213 lagu -> 213 request -> lantai 31.9s   (terukur 32.9s -- cocok)
 100 lagu -> 100 request -> lantai 15.0s
  50 lagu ->  50 request -> lantai  7.5s
```

### Akar 2 — `metadata_many()` TIDAK punya cache

`metadata_many()` (untuk album/label/tahun — data R4) **memanggil endpoint
spclient metadata untuk SETIAP lagu, setiap kali load**. Tidak ada cache.

```python
def metadata_many(track_ids, anon_token, workers=MAX_WORKERS):
    """Parallel track_metadata_spclient for many tracks."""
    # <-- tidak ada load_cache / save_cache sama sekali
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(track_metadata_spclient, tid, anon_token): tid ...}
```

**Bukti:** load playlist 4 lagu **dua kali** -> request tetap **5** di run ke-2.
Seharusnya run ke-2 hampir 0 request.

**Bandingkan** — `cached_track_details()` (metadata cover, R1) **sudah** punya cache:
```python
def cached_track_details(track_ids, workers, progress):
    cache = load_cache("tracks")
    missing = [t for t in ids if t not in cache]     # <-- hanya yang belum ada
    if missing:
        fresh = track_details(missing, ...)
        save_cache("tracks", cache)
    return {t: cache[t] for t in ids if t in cache}
```

Cache `tracks` ada (352 entri). Tapi metadata album **tidak di-cache**.

---

## PERBAIKAN YANG DIMINTA

### 1. Throttle PER-WORKER, bukan global

Ganti throttle global jadi throttle per-thread, supaya 8 worker benar-benar paralel
sementara **setiap worker tetap sopan** (jeda 150 ms antar request-nya sendiri).

Pilihan implementasi (pilih satu, jelaskan alasannya):
- `threading.local()` untuk menyimpan `_last_request` per-thread
- atau token-bucket / semaphore yang membatasi **laju total** (mis. maks 20 req/detik)
  tanpa men-serialisasi

**Syarat:**
- Total laju request tetap **sopan** — jangan sampai memicu rate limit Spotify.
  Target: **maksimal ~20 request/detik** secara total.
- 8 worker harus benar-benar jalan bersamaan
- Thread-safe
- Jangan hapus konsep jeda — hanya ubah dari global ke per-worker/terkontrol

**Cara menguji:**
```
8 thread x 5 panggilan _throttle() harus selesai jauh lebih cepat dari 6 detik
(tanpa membanjiri server).
```

### 2. Tambah cache untuk `metadata_many()`

Ikuti pola `cached_track_details()`:

```python
def cached_metadata_many(track_ids, anon_token, workers=MAX_WORKERS):
    """metadata_many dengan disk cache: hanya id yang belum ada yang di-fetch."""
    ids = [t for t in dict.fromkeys(track_ids) if t]
    cache = load_cache("meta")              # <-- nama cache baru
    missing = [t for t in ids if t not in cache]
    if missing:
        fresh = metadata_many(missing, anon_token, workers=workers)
        if fresh:
            cache.update(fresh)
            save_cache("meta", cache)
    return {t: cache[t] for t in ids if t in cache}
```

Lalu pakai `cached_metadata_many()` di `providers/spotify_embed.py`
(`embed_tracks_complete()`, bagian "step 4 (R4)").

**Syarat:**
- Nama cache: `meta` (file `spclient_meta.json`)
- Cache rusak -> abaikan, jangan crash (ikuti pola `load_cache` yang ada)
- Token berbeda antar sesi bukan masalah — cache menyimpan **hasil**, bukan token

### 3. Ukur dan laporkan

Setelah perbaikan, jalankan dan **laporkan angka nyata**:

```bash
.venv/Scripts/python.exe -c "
import sys, time; sys.path.insert(0,'.')
from providers import spotify_spclient as sp
from providers.spotify_meta import SpotifyMeta

orig = sp._get
n = {'c':0}
def counting(u,h=None):
    n['c'] += 1
    return orig(u,h)
sp._get = counting

for label, pl in [('4 lagu','https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3'),
                  ('213 lagu','https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH')]:
    for run in (1,2):
        n['c']=0
        t0=time.time()
        m=SpotifyMeta(); t,tr,h=m.playlist_tracks(pl)
        print(f'{label} run{run}: {time.time()-t0:.1f}s, {n[\"c\"]} request, {len(tr)} lagu')
"
```

**Kriteria yang diharapkan:**

| Playlist | Sebelum | Target |
|---|---|---|
| 4 lagu (run 1) | 1.97s | < 1.5s |
| 4 lagu (run 2) | 3.68s | **< 0.5s** (cache jalan) |
| 213 lagu (run 1) | 32.9s | **< 10s** |
| 213 lagu (run 2) | — | **< 1s** (cache jalan) |

Kalau target tidak tercapai, **laporkan angka sebenarnya** dan jelaskan kenapa.
Jangan mengarang.

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN kurangi data yang diambil.** Cover per-lagu (R1) dan album/label/tahun
   (R4) harus tetap ada — itu permintaan user.
2. **JANGAN hapus throttle sepenuhnya.** Server harus tetap dihormati.
3. **JANGAN naikkan MAX_WORKERS** di atas 8 — itu bukan solusinya dan bisa
   memicu rate limit.
4. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
5. **JANGAN ubah** hasil tag ID3 atau cover yang sudah benar.

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- `REQUEST_GAP = 0.15`, `MAX_WORKERS = 8`
- `_throttle()` global -> paralel jadi serial (terbukti: 40 panggilan = 5.86s)
- `metadata_many()` tidak punya cache (terbukti: request tetap 5 di run ke-2)
- `cached_track_details()` sudah punya cache, `tracks` berisi 352 entri
- 1 request tanpa throttle rata-rata ~336 ms (jaringan)
- `providers/spotify_embed.py` **tidak** punya throttle sendiri

---

## TEST YANG HARUS TETAP LOLOS

```bash
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_covers.py        # PASS=34 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=32 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=51 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=91 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- **Angka nyata sebelum vs sesudah** (waktu + jumlah request, dari perintah di atas)
- Apakah cache benar-benar dipakai di run ke-2 (bukti: jumlah request turun)
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)

Kalau target waktu tidak tercapai, **bilang apa adanya** beserta alasannya.
