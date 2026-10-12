# Prompt untuk OpenCode — Perbaiki Layout Tabel Download Lagu

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## MASALAH

Halaman **Download Lagu** sudah pakai tabel kolom, tapi **layout-nya kacau**.
Halaman lain tidak masalah — **hanya halaman ini**.

**Gejala yang dilaporkan user:**
- Kolom tidak sejajar antar baris
- Cover kelihatan kegeser jauh dari judul
- Judul terpotong padahal kolomnya lebar
- Baris terlihat berantakan / tidak rapi

---

## AKAR MASALAH — sudah didiagnosis, jangan cari lagi

`_render_track_table()` di `app.py` (baris ~1114) memakai **`st.columns()` 7 kolom
per baris**:

```python
num_col, check_col, art_col, title_col, album_col, dur_col, btn_col = st.columns(
    [0.4, 0.5, 0.7, 4.6, 2.4, 0.7, 1.1])
```

**Streamlit SELALU memberi gap (~1rem) antar kolom.** Dengan 7 kolom × 25 baris
(TRACKS_PER_PAGE = 25), gap menumpuk dan menyebabkan semua gejala di atas.

**`ui/theme.py` tidak punya aturan** untuk `stHorizontalBlock` / `stColumn`,
jadi tidak ada yang menetralkan gap bawaan Streamlit.

**Struktur DOM Streamlit:**
```
stHorizontalBlock > stColumn > stVerticalBlock > div > markdown
```
Jarak antar kolom diatur di level `stHorizontalBlock` — CSS di dalam cell
**tidak bisa** menimpanya.

**Bukti tambahan:** `_render_table_header()` (baris ~1169) memakai rasio kolom
yang sama, jadi header pun ikut tidak sejajar dengan isinya.

---

## SOLUSI YANG DIMINTA — grid HTML, bukan `st.columns`

Ganti pendekatan: **satu blok HTML per baris** pakai CSS grid.

### Kenapa

CSS grid memberi kendali penuh atas lebar kolom dan gap — tidak ada gap bawaan
Streamlit yang mengganggu. Kolom **pasti sejajar** karena grid-nya sama untuk
semua baris.

### Kendala yang harus ditangani

**Widget Streamlit (checkbox, tombol) TIDAK BISA dirender di dalam `st.markdown`.**
Jadi tiap baris dipecah jadi **2 elemen Streamlit**, bukan 7:

```
[ grid HTML: nomor + cover + judul/artist + album + durasi ]  [ checkbox + tombol ]
```

Pakai `st.columns([10, 1.2])` untuk memisahkan keduanya (2 kolom saja — gap-nya
tidak masalah).

### Struktur yang diminta

**CSS (tambahkan di `ui/theme.py`):**

```css
.nx9-tbl-row {
    display: grid;
    grid-template-columns: 32px 48px minmax(0, 1fr) 200px 56px;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid transparent;
}
.nx9-tbl-row:hover {
    background: #18181B;
    border-color: #27272A;
}
.nx9-tbl-num {
    font-family: 'JetBrains Mono', monospace;
    color: #A1A1AA;
    font-size: 12px;
    text-align: right;
}
.nx9-tbl-art {
    width: 48px;
    height: 48px;
    aspect-ratio: 1 / 1;
    overflow: hidden;
    border-radius: 6px;
    background: #18181B;
}
.nx9-tbl-art img {
    width: 100% !important;
    height: 100% !important;
    object-fit: cover;
    display: block;
}
.nx9-tbl-body { min-width: 0; }        /* PENTING: tanpa ini ellipsis gagal */
.nx9-tbl-title {
    color: #FFFFFF;
    font-weight: 600;
    font-size: 14px;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.nx9-tbl-sub {
    color: #A1A1AA;
    font-size: 13px;
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.nx9-tbl-dur {
    color: #A1A1AA;
    font-size: 13px;
    text-align: right;
    font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
}
```

**Catatan CSS penting:**
- `minmax(0, 1fr)` pada kolom judul — **wajib**. Tanpa `minmax(0, ...)`,
  `text-overflow: ellipsis` **tidak jalan** di grid.
- `min-width: 0` pada `.nx9-tbl-body` — **wajib** untuk alasan yang sama.
- Pakai token warna dari `ui/theme.py` kalau tersedia (`SURFACE`, `BORDER`,
  `TEXT_SECONDARY`), jangan hardcode.

**HTML per baris (dibangun di Python):**

```python
row_html = (
    f'<div class="nx9-tbl-row">'
    f'  <div class="nx9-tbl-num">{n}</div>'
    f'  <div class="nx9-tbl-art">'
    f'    <img src="{html.escape(cover, quote=True)}" alt="">'
    f'  </div>'
    f'  <div class="nx9-tbl-body">'
    f'    <div class="nx9-tbl-title">{html.escape(title)}</div>'
    f'    <div class="nx9-tbl-sub">{html.escape(artist)}</div>'
    f'  </div>'
    f'  <div class="nx9-tbl-sub">{html.escape(album)}</div>'
    f'  <div class="nx9-tbl-dur">{html.escape(duration)}</div>'
    f'</div>'
)
st.markdown(row_html, unsafe_allow_html=True)
```

**Header tabel** juga harus pakai grid yang **sama persis**
(`grid-template-columns` identik), supaya sejajar dengan isinya.

### Syarat teknis

1. **Ubah `_render_track_table()`** — pakai grid HTML + `st.columns([10, 1.2])`
   untuk checkbox & tombol.
2. **Ubah `_render_table_header()`** — grid yang sama, tanpa checkbox/tombol.
3. **`st.columns` hanya 2 kolom** (grid + aksi). Jangan 7 lagi.
4. **Semua teks di-escape** (`html.escape(..., quote=True)`) — jangan skip.
5. **Tetap ada**: checkbox pilih, tombol "Unduh" per baris, search/filter,
   paginasi (`_pager`), "Pilih semua", "Bersihkan",
   "Download N Lagu Terpilih → ZIP".
6. **Cover gagal dimuat** → `.nx9-tbl-art` tetap tampil sebagai kotak abu-abu
   (jangan kosong/roboh).
7. **`TRACKS_PER_PAGE = 25`** tetap dipakai.

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN ubah `page_covers()`** — halaman cover tetap **galeri** (`_render_cover_gallery`).
2. **JANGAN ubah `_render_track_row()`** — masih ada di kode (legacy), biarkan.
3. **JANGAN ubah halaman lain** (Home, Backup, Settings, Legacy).
4. **JANGAN tambah request baru** — semua data sudah ada di `Track`.
5. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
6. **JANGAN hapus** CSS yang sudah ada di `ui/theme.py` — tambahkan saja.
7. **JANGAN** pakai `st.columns` 7 kolom lagi.

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- Streamlit **1.63.0**
- `st.columns()` memberi gap bawaan yang tidak bisa dinetralkan dari dalam cell
- `_render_track_table()` ada di `app.py` baris ~1114
- `_render_table_header()` ada di `app.py` baris ~1169
- Keduanya memakai rasio `[0.4, 0.5, 0.7, 4.6, 2.4, 0.7, 1.1]`
- `TRACKS_PER_PAGE = 25`, `_pager()` di baris ~1027
- Widget Streamlit tidak bisa dirender di dalam `st.markdown`
- CSS `.nx9-art-img` / `.nx9-art-tbl` sudah ada tapi tidak menyelesaikan gap
- Data per lagu: `t["id"]`, `t["title"]`, `t["artist"]`, `t["album"]`,
  `t["cover"]`, `t["duration"]`

---

## VERIFIKASI YANG DIMINTA

1. **Jalankan Streamlit**, buka halaman **Download Lagu**, load playlist.

   **Kriteria visual:**
   - Kolom **sejajar sempurna** antar baris (nomor, cover, judul, album, durasi)
   - Cover **rapat** dengan judul (tidak ada celah besar)
   - Judul/album panjang **dipotong `...`**, bukan membungkus
   - Header sejajar dengan kolom isinya
   - Baris seragam tingginya

2. **Cek halaman lain tidak berubah:**
   - Download Cover → tetap **galeri kotak-kotak**
   - Home → header normal
   - Backup → normal

3. **Cek fungsi masih jalan:** checkbox, "Pilih semua", "Bersihkan",
   "Download N Lagu Terpilih → ZIP", paginasi, search.

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
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=115 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # OK: CSS tabel
.venv/Scripts/python.exe -c "import app; print('OK')"
```

---

## LAPORAN YANG DIMINTA

- File apa yang diubah
- Struktur baris **sebelum vs sesudah** (berapa kolom `st.columns`)
- Apakah kolom sudah sejajar (jelaskan cara memverifikasinya)
- Bukti halaman Download Cover **tidak berubah**
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)

---

## CATATAN TAMBAHAN

Kalau grid HTML ternyata bermasalah dengan Streamlit 1.63 (mis. HTML di-sanitize),
**laporkan apa adanya** dan jelaskan apa yang terjadi — jangan diam-diam kembali
ke `st.columns` 7 kolom.
