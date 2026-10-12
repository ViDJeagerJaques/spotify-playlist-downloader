# Prompt untuk OpenCode — Buang Batas 100 Lagu (TANPA LOGIN)

> Copy seluruh isi file ini, paste ke OpenCode.
> **PENTING: JANGAN bikin dari awal.** Semua modifikasi file yang SUDAH ADA.

---

## TEMUAN BESAR — BACA DULU

Kemarin kita kira playlist >100 lagu **wajib** OAuth (login user). **Ternyata salah.**
Ada jalan tanpa login sama sekali, dan sudah gw uji sampai berhasil.

**Bukti: playlist 213 lagu → terbaca 213/213, tanpa login.**

```
embed    : 100 lagu   (cap yang sekarang bikin mentok)
spclient : 213 lagu   length=213, truncated=false   <<< SEMUA
```

Artinya **kerjaan OAuth (#1) jadi tidak wajib lagi.** OAuth tetap dipertahankan
hanya untuk playlist PRIVATE. Playlist publik → cukup spclient.

---

## RANTAI YANG SUDAH TERVERIFIKASI

### Langkah 1 — Token anonim dari halaman embed

```
GET https://open.spotify.com/embed/playlist/{id}
```

Halaman embed **menyimpan access token** di dalam HTML-nya. Ambil dengan regex:

```python
m = re.search(r'accessToken["\']?\s*[:=]\s*["\']([^"\']{20,})["\']', html)
token = m.group(1)          # 140 karakter, token anonim (bukan milik user)
```

Halaman yang sama juga memberi (sudah dipakai sekarang):
- `trackList` → 100 lagu pertama
- `entity["subtitle"]` → owner playlist
- `entity["coverArt"]["sources"][0]["url"]` → cover playlist
- total durasi = jumlah `duration` di `trackList`

### Langkah 2 — Daftar SEMUA lagu via spclient

```
GET https://spclient.wg.spotify.com/playlist/v2/playlist/{id}
Authorization: Bearer <token dari langkah 1>
Accept: application/json
app-platform: WebPlayer
Origin: https://open.spotify.com
Referer: https://open.spotify.com/
```

Respons:

```json
{
  "revision": "AAAA7mb9Sqn7KTbPGZV0VBllxjapLB5f",
  "length": 213,
  "attributes": { "name": "Dupe", "picture": "q2dwbAAA2oTRqRqf8MR+2CnzmHQ=" },
  "contents": {
    "pos": 0,
    "truncated": false,
    "items": [
      { "uri": "spotify:track:70C4NyhjD5OZUMzvWZ3njJ",
        "attributes": { "addedBy": "...", "timestamp": "...", "itemId": "..." } }
    ]
  },
  "ownerUsername": "31siy2jiykpjmhgercjuh2j2yrbe",
  "createdAt": 1770998541000,
  "isUserCreated": true
}
```

**Yang penting:**
- `length` = jumlah lagu **asli** (213)
- `contents.items` = daftar lengkap, **`truncated: false`**
- `ownerUsername` = **username asli**, lebih akurat dari `subtitle` di embed
- Item **hanya berisi URI** — tidak ada judul/artist/cover. Metadata harus diambil di langkah 3.

**Hasil uji konsistensi:**

| Playlist | `length` | `items` | `truncated` |
|---|---|---|---|
| Dupe | 213 | 213 | false |
| A.....C | 75 | 75 | false |
| Today's Top Hits | 50 | 50 | false |

### Langkah 3 — Metadata lagu yang tidak ada di embed (posisi >100)

```
GET https://open.spotify.com/embed/track/{track_id}
```

**Tanpa auth, tanpa token.** Parsing dari `__NEXT_DATA__` seperti embed playlist.

Field yang tersedia:

```
title        : "Take A Chance With Me"
artists      : [{"name": "NIKI", "uri": "spotify:artist:2kxP07DLgs4xlWz8YHlvfh"}]
duration     : 303933              (ms)
releaseDate  : {"isoString": "2022-08-11T00:00:00Z"}
audioPreview : {"url": "https://p.scdn.co/mp3-preview/..."}
isPlayable   : true
coverArt     : null                <<< PENTING: cover TIDAK ada di sini
```

**Rate limit: BEBAS.** Sudah diuji 20 request berturut-turut → **20/20 sukses**,
rata-rata **312 ms/request**. Bandingkan `api.spotify.com` yang kena 429.

### Langkah 4 — Cover lagu >100 via oEmbed

Karena `coverArt` di langkah 3 `null`, cover diambil dari oEmbed:

```
GET https://open.spotify.com/oembed?url=https://open.spotify.com/track/{track_id}&format=json
```

Respons (field penting):

```json
{
  "title": "Take A Chance With Me",
  "thumbnail_url": "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02d3997a4c208ac08dafff374f",
  "thumbnail_width": 300,
  "thumbnail_height": 300
}
```

**Sudah dibandingkan:** hash `d3997a4c208ac08dafff374f` **sama persis** dengan cover
album dari Web API. Jadi cover-nya asli, bukan placeholder.

**Catatan:** oEmbed juga jalan untuk playlist/album (sudah dipakai di kode sekarang).

---

## JEBAKAN PENTING

### 1. `api.spotify.com` KENA RATE LIMIT PARAH

Selama investigasi, endpoint ini balas `429 QUOTA_EXCEEDED` **terus-menerus**, tidak
pulih setelah 30s / 60s / 120s. Penyebab: terlalu banyak request beruntun.

**Konsekuensinya — dan ini penting:**

| Endpoint | Rate limit | Pakai untuk |
|---|---|---|
| `api.spotify.com/v1/tracks/{id}` | ❌ **parah** (429) | **HINDARI** |
| `open.spotify.com/embed/track/{id}` | ✅ bebas | metadata lagu >100 |
| `open.spotify.com/oembed` | ✅ bebas | cover lagu >100 |
| `open.spotify.com/embed/playlist/{id}` | ✅ bebas | 100 lagu + token + owner |
| `spclient.wg.spotify.com/...` | ✅ bebas | daftar lengkap |

**Yang diminta:** untuk playlist, **jangan** pakai `api.spotify.com` lagi. Ganti ke
`/embed/track` + oEmbed. `api.spotify.com` hanya dipakai kalau memang perlu
(album/track tunggal) dan selalu dengan throttle + retry.

### 2. spclient butuh token dari halaman EMBED PLAYLIST

Token itu hanya ada di halaman embed **playlist**, bukan di embed track. Jadi urutannya:
ambil embed playlist dulu → baru token bisa dipakai ke spclient.

### 3. spclient hanya memberi URI

Jangan harap judul/artist/cover dari spclient. Itu tugas langkah 3 & 4.

### 4. Token anonim ≠ token user

Token ini **bukan** milik akun siapa pun. Playlist private tetap butuh OAuth.

### 5. Jangan spam

Meski `/embed/track` bebas, tetap kasih jeda kecil dan batasi worker (maks 8).
Hormati kalau ada 429: backoff lalu retry.

---

## URUTAN PERCOBAAN YANG DIMINTA

```
playlist publik:
  1. embed playlist        → 100 lagu + token + owner
  2. spclient (pakai token) → SEMUA lagu
  3. /embed/track          → metadata lagu >100
  4. oEmbed                → cover lagu >100

kalau spclient gagal (mis. markup berubah):
  → pakai 100 lagu dari embed, kasih tahu user sisanya tidak terbaca

playlist private:
  → OAuth (SPOTIFY_REFRESH_TOKEN) — tetap dipertahankan, jangan dihapus
```

---

## TUGAS

### A. Tambah pembaca spclient

Di `providers/spotify_embed.py` (atau file baru `providers/spotify_spclient.py`),
tambah fungsi:

```python
def playlist_track_ids(playlist_id: str, anon_token: str) -> tuple[list[str], int, str]:
    """Ambil SEMUA track id sebuah playlist lewat spclient.

    Returns (track_ids, length, owner_username).

    - track_ids urut sesuai posisi di playlist (dari contents.items)
    - length = jumlah asli dari field 'length'
    - owner_username = username asli (lebih akurat dari subtitle di embed)
    - kalau gagal / truncated: kembalikan apa adanya, jangan crash
    """
```

Syarat:
- Timeout wajar (30-40s)
- Kalau status != 200 → lempar `ServiceError` dengan pesan bahasa Indonesia
- Kalau `contents.truncated == True` → tetap kembalikan yang ada, dan tandai di return
- Jangan hardcode token — selalu dari parameter

### B. Ambil token anonim dari halaman embed

Fungsi yang sudah ada (`parse_embed_page` / `embed_tracks_detailed`) harus **juga**
mengembalikan token anonim. Jangan request halaman dua kali — pakai HTML yang sama.

### C. Metadata untuk lagu >100

Tambah fungsi:

```python
def track_meta_embed(track_id: str) -> dict:
    """Metadata satu lagu dari /embed/track/{id} (tanpa auth).

    Returns {title, artists (list[str]), duration_ms, release_date}
    atau {} kalau gagal.
    """

def track_cover_oembed(track_id: str) -> str:
    """Cover satu lagu dari oEmbed. Return URL atau '' kalau gagal."""
```

Syarat:
- Paralel maksimal **8 worker**
- Jeda kecil antar request (mis. 0.15s) supaya sopan
- Gagal satu lagu → `{}` / `''`, **jangan** menggagalkan seluruh playlist
- Cache hasilnya (track id → metadata), supaya playlist yang sama tidak request ulang

### D. Rangkai jadi satu alur

Ubah `playlist_tracks()` di `providers/spotify_meta.py`:

```
1. embed playlist    → 100 lagu + token + owner + total durasi
2. spclient          → semua track id
3. bandingkan: mana yang belum ada di 100 pertama
4. ambil metadata + cover untuk yang kurang (paralel 8)
5. gabung, urutkan sesuai posisi playlist asli
```

Syarat:
- **Urutan harus sesuai playlist**, bukan urutan request
- `owner` pakai `ownerUsername` dari spclient kalau ada, fallback ke `subtitle`
- Total durasi dihitung dari semua lagu (bukan cuma 100)
- Kalau spclient gagal → tetap jalan dengan 100 lagu + `hint` yang menjelaskan
- **Jangan hapus** jalur OAuth — tetap ada untuk playlist private

### E. Buang ketergantungan `api.spotify.com` untuk playlist

Cari semua tempat yang memanggil `api.spotify.com` untuk keperluan playlist dan
ganti ke `/embed/track` + oEmbed.

**TAPI jangan hapus `providers/spotify_meta.py`** — masih dipakai untuk album/track
tunggal. Cukup pastikan jalur playlist tidak lewat situ lagi.

### F. UI

1. Batas 100 lagu **hilang** untuk playlist publik — pastikan tidak ada lagi
   peringatan "cuma 100 lagu" untuk playlist publik
2. Panel OAuth tetap ada, tapi ubah teksnya: bukan untuk >100 lagu, tapi
   **"untuk playlist private"**
3. Tampilkan progres saat mengambil metadata (playlist 213 lagu butuh ~10 detik)
4. Total lagu & total durasi di header harus mencerminkan **semua** lagu

### G. Hapus `curl_cffi` kalau tidak perlu

`curl_cffi` gw install saat investigasi (untuk meniru TLS Chrome). Ternyata
**tidak diperlukan** — `requests` biasa sudah cukup untuk semua endpoint di atas.
Kalau kodenya tidak memakainya, jangan tambahkan ke `requirements.txt`.

---

## VERIFIKASI YANG DIMINTA

```bash
# test lama harus tetap lolos
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_covers.py        # PASS=34 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=31 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=45 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

Lalu uji **nyata** dengan playlist 213 lagu:

```bash
.venv/Scripts/python.exe -c "
from providers.spotify_meta import SpotifyMeta
m = SpotifyMeta()
title, tracks, hint = m.playlist_tracks('https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH')
print('judul :', title)
print('lagu  :', len(tracks))          # HARUS 213, bukan 100
print('hint  :', hint)
t = tracks[-1]                          # lagu terakhir = yang tadinya tidak terbaca
print('terakhir:', t.artist, '-', t.title)
print('cover   :', (t.thumbnail or '(kosong)')[-40:])
"
```

**Kriteria sukses:**
- Jumlah lagu = **213** (bukan 100)
- Lagu terakhir punya judul + artist + cover yang benar
- Tidak ada error 429

Tambah test baru untuk spclient (pakai fixture JSON, jangan panggil jaringan di unit test).

---

## BATASAN

1. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
2. **JANGAN hapus OAuth.** Cuma berubah peran (playlist private).
3. **JANGAN hapus** `providers/soundloaders.py`, `spotidown.py`, `spotidown_co.py`.
4. **JANGAN pakai `api.spotify.com` untuk playlist** — kena rate limit.
5. **JANGAN spam.** Maks 8 worker, kasih jeda.
6. **JANGAN hardcode token** — selalu ambil dari halaman embed.
7. **JANGAN simpan credential di kode.** Hanya `.env`.
8. **JANGAN ngarang angka.** Kalau belum diuji, bilang belum diuji.

---

## LAPORAN YANG DIMINTA

- File apa yang diubah/ditambah
- Jumlah lagu yang berhasil dibaca untuk playlist 213 lagu (angka nyata)
- Test apa yang dijalankan + hasilnya
- Apa yang **belum** selesai atau belum diuji (jujur)

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- Halaman embed playlist menyimpan `accessToken` anonim (140 karakter)
- spclient menerima token itu → `length` + `contents.items` lengkap, `truncated: false`
- spclient hanya memberi URI, bukan metadata
- `/embed/track/{id}` memberi title/artists/duration, **bebas rate limit**, tapi `coverArt` null
- oEmbed memberi `thumbnail_url` yang **sama persis** dengan cover Web API
- `api.spotify.com` kena 429 parah — hindari untuk playlist
- `curl_cffi` **tidak diperlukan**

## YANG BELUM PASTI

- Berapa lama token anonim bertahan (perlu diambil ulang tiap kali? aman ambil ulang)
- Apakah spclient stabil jangka panjang (ini API internal, bisa berubah)
- Apakah ada playlist publik yang tetap butuh OAuth (mis. region lock)

Kalau ada yang tidak jelas — **tanya dulu**, jangan ngarang.
