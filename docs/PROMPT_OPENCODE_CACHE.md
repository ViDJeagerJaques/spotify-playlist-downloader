# Prompt OpenCode — Cache di E: + Anti Cache Basi

> Paste ke OpenCode. **JANGAN bikin dari awal** — modifikasi file yang ada.

---

## MASALAH (2 hal, dari kejadian nyata)

### 1. Cache numpuk di C: — disk user hampir penuh

`providers/youtube.py` baris 69:
```python
CACHE_DIR = Path(tempfile.gettempdir()) / "spotify_yt_cache"
```

`tempfile.gettempdir()` = `C:\Users\USER\AppData\Local\Temp` — **selalu di C:**,
padahal proyeknya di E:. Disk C: user **95% penuh (sisa 14 GB)**.

Yang numpuk di Temp:
- `spotify_yt_cache/` — MP3 hasil download (24 MB, tumbuh tiap download)
- `spl_*.zip` — ZIP hasil batch, **tidak pernah dihapus** (orchestrator baris 408,
  422). Sudah ketemu **11 file / 422 MB** menumpuk dari beberapa hari.

Playlist 213 lagu ≈ **1 GB** mendarat di C: tanpa user sadar.

### 2. Cache basi = lagu salah terunduh lagi

`resolve_track()` baris 441:
```python
dest = CACHE_DIR / f"{track.track_token or abs(hash(query))}.mp3"
if dest.exists() and dest.stat().st_size > 0:
    return str(dest)          # <-- langsung pakai, tanpa cek video apa
```

**Cache tidak menyimpan video mana yang dipakai.** Bukti nyata: setelah
perbaikan pemilihan channel resmi, lagu Joji masih terunduh dari channel fans
karena MP3 lama masih di cache. Ditemukan `Sanctuary` di cache berdurasi
**253.7s**, padahal video resmi Joji **180s** — itu versi lain. Setelah cache
dihapus, resolve ulang menghasilkan **180s** yang benar.

---

## YANG DIMINTA

### 1. Pindahkan cache ke folder proyek (di E:)

```python
# providers/youtube.py, ganti baris 69
# Boleh dioverride lewat env var SPOTIFY_CACHE_DIR.
CACHE_DIR = Path(os.environ.get("SPOTIFY_CACHE_DIR")
                 or Path(__file__).resolve().parents[1] / ".cache")
```

- Default: `<folder proyek>/.cache`
- Masih bisa dioverride lewat `SPOTIFY_CACHE_DIR`
- Tambahkan `.cache/` ke `.gitignore`
- Buat foldernya kalau belum ada (`mkdir(parents=True, exist_ok=True)`) —
  sudah ada di baris 446, pastikan tetap jalan
- **Jangan ubah** struktur file di dalamnya (nama `{token}.mp3` tetap)

### 2. ZIP hasil batch juga ke folder proyek

`core/orchestrator.py` baris 408 dan 422 memakai `tempfile.gettempdir()`.
Ganti supaya ZIP sementara ikut ke `CACHE_DIR` (import dari provider, atau
pakai env var yang sama).

Baris 271 dan 348 (`mkdtemp`) juga pindah ke sana.

**Tambah pembersihan ZIP lama:** sebelum bikin ZIP baru, hapus `spl_*.zip`
di folder itu yang umurnya **> 24 jam**. User sudah punya 422 MB menumpuk.

### 3. Simpan video_id di cache — ini inti perbaikannya

Saat resolve, tulis catatan video apa yang dipakai. Misal sidecar JSON:

```
.cache/
  4VQH4VluDUOsOuDxccTeyN.mp3
  4VQH4VluDUOsOuDxccTeyN.json   <-- {"video_id": "ZEY9UCzzbcQ",
                                      "channel": "Joji",
                                      "title": "Sanctuary",
                                      "duration": 180,
                                      "resolved_at": "2026-10-13T11:46:00"}
```

**Perilaku yang diminta:**
- Kalau `.mp3` ada **dan** `.json` ada → pakai cache (cepat, nol request)
- Kalau `.mp3` ada **tapi** `.json` tidak ada → itu cache lama, **resolve ulang**
  (cari video, unduh, tulis `.json`)
- **Jangan** hapus file lama secara otomatis — cukup ditimpa saat resolve ulang

Alasan: tanpa catatan ini, perbaikan scoring apa pun **tidak akan terasa**
untuk lagu yang sudah pernah diunduh. Ini yang bikin user bolak-balik bilang
"masih aja yang punya fans kedownload".

### 4. Tombol "Bersihkan Cache" di sidebar

`app.py` baris ~204 (`def sidebar()`). Tambah di bawah bagian backend:

- Tampilkan **ukuran cache sekarang** (jumlah file + MB)
- Tombol **"Bersihkan cache"**
- Tombol harus **minta konfirmasi** (pakai `st.checkbox` atau dua langkah) —
  jangan langsung hapus
- Setelah dibersihkan, tampilkan berapa file/MB yang dibebaskan
- Teks **dwibahasa** (id + en) — ikuti pola `core/i18n.py` yang sudah ada,
  jangan hardcode

**Jangan** taruh tombol ini di halaman Download — taruh di sidebar.

### 5. Jangan regresi

- **JANGAN ubah** logika pemilihan channel (`channel_match_strength`,
  `score_candidate`, `is_lyrics_channel`) — itu sudah benar, terverifikasi 14/14
- **JANGAN ubah** nama file `{track_token}.mp3`
- **JANGAN hapus** cache otomatis tanpa user minta
- **JANGAN ubah** UI lain (tabel, layout fluid, galeri cover)

---

## VERIFIKASI YANG DIMINTA

### Uji 1 — cache pindah ke proyek
```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import CACHE_DIR
print('CACHE_DIR =', CACHE_DIR)
print('di dalam proyek?', str(CACHE_DIR).lower().startswith(r'e:\coolyeah'))
"
```
**Kriteria:** path menunjuk ke folder proyek, **bukan** `AppData\Local\Temp`.

### Uji 2 — cache lama dideteksi basi
```bash
.venv/Scripts/python.exe -c "
import sys, json; sys.path.insert(0,'.')
from providers.youtube import CACHE_DIR
from pathlib import Path
mp3 = list(Path(CACHE_DIR).glob('*.mp3'))
js  = list(Path(CACHE_DIR).glob('*.json'))
print('mp3:', len(mp3), ' json:', len(js))
print('sidecar ada untuk tiap mp3?', len(js) >= len([m for m in mp3 if m.name != 'youtube_verified.json']))
"
```
**Kriteria:** setiap `.mp3` punya pasangan `.json` setelah resolve ulang.

### Uji 3 — video resmi tetap dipilih (JANGAN regresi)
```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from providers.youtube import YouTubeClient
from providers.base import Track
c = YouTubeClient()
for title, artist, dur in [('Glimpse of Us','Joji',222000),
                           ('Cinnamon Girl','Lana Del Rey',300683),
                           ('Blinding Lights','The Weeknd',200000)]:
    t = Track(data='x', track_token='probe_'+title[:8], title=title, artist=artist, duration_ms=dur)
    b = c._pick_best(f'{artist} {title} official audio', int(dur/1000), artist)
    print(f'{artist:16s} -> {b.get(\"channel\")}')
"
```
**Kriteria:** channel = Joji / Lana Del Rey / The Weeknd.

### Uji 4 — ZIP lama dibersihkan
Bikin 2 ZIP batch berturut-turut, pastikan ZIP lama (>24 jam, bisa disimulasikan
dengan mengubah mtime) terhapus dan yang baru tetap ada.

### Uji 5 — semua test lama tetap lolos
```bash
for t in smoke test_youtube test_spotify_embed test_spclient test_tags test_cover_size test_spotidown_co test_theme test_fetch_bytes test_oauth test_app; do
  printf "%-22s " "$t"; .venv/Scripts/python.exe tests/$t.py 2>&1 | tail -1
done
```
Semua harus **PASS** (test_youtube sekarang 53 cek).

Tambah test untuk: cache basi (mp3 tanpa json → resolve ulang), dan
pembersihan ZIP lama.

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- Hasil **Uji 1–5** (angka nyata, bukan "berhasil")
- Path `CACHE_DIR` sebelum vs sesudah
- Berapa MB yang tidak lagi mendarat di C:
- Apa yang belum selesai (jujur)

Kalau ada yang tidak bisa, **bilang apa adanya** — jangan mengarang.
