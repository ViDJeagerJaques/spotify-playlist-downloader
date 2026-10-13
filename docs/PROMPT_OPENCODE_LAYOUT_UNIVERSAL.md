# Prompt untuk OpenCode — Layout Universal + Spacing yang Enak Dilihat

> Copy seluruh isi file ini, paste ke OpenCode.
> **JANGAN bikin dari awal.** Modifikasi file yang SUDAH ADA.

---

## MASALAH

User bilang UI-nya **"kurang enak dipandang, jatuhnya kayak UI AI slop"**.
Bukan strukturnya yang salah — tabelnya sudah benar. Masalahnya **spacing,
proporsi, dan lebar**.

User juga minta: **jangan cuma bagus di komputer dia** (1920x1080), tapi
**universal** — enak di laptop kecil, monitor besar, dan layar sempit.

---

## AKAR MASALAH — sudah didiagnosis, jangan cari lagi

### 1. Konten kejepit di 736px (INI YANG PALING PARAH)

Streamlit default mengunci konten di `.block-container { max-width: 736px }`.
`ui/theme.py` **tidak pernah meng-override ini**.

```
Layar user : 1920 px
Konten     :  736 px   <-- cuma 38% layar
Sisa       : 1184 px   <-- kosong menganggur di kiri-kanan
```

Efeknya: konten sempit dan terkurung di tengah, dengan ruang kosong besar.
Ini ciri paling khas "UI yang di-generate".

### 2. Semua ukuran FIXED (px), jadi tidak universal

```
px   : hampir semua
rem  : 0
clamp: 0
@media: 1 (cuma max-width: 900px)
```

Karena semuanya px tetap, layout hanya enak di satu ukuran layar.
Di monitor besar terlihat kekecilan, di laptop kecil terlihat sesak.

### 3. Spacing terlalu rapat

```css
.nx9-tbl-row {
    grid-template-columns: 28px 40px minmax(0, 1fr) minmax(0, 140px) 44px;
    gap: 10px;          /* <-- rapat */
    padding: 9px 10px;  /* <-- rapat */
}
```

- `gap: 10px` — antar elemen berdempetan
- `padding: 9px 10px` — tidak seimbang (vertikal 9, horizontal 10)
- Cover **40px** — kekecilan untuk baris setinggi ini
- Baris total ~52px — kurang napas

### 4. Angka tidak konsisten (bukan kelipatan 4/8)

```
28px, 40px, 140px, 44px, 10px, 9px, 6px, 12px, 14px, 13px
```

Campur aduk: ada 9px, 10px, 13px, 14px. Tidak ada ritme visual.
Ini yang bikin terasa "asal jadi".

### 5. Judul kehabisan ruang

Karena lebar total cuma 736px, setelah dikurangi kolom lain:
```
736 - 28 - 40 - 140 - 44 - (gap 10x4) - (padding 10x2) - aksi = ~420px untuk judul
```
Judul lagu jadi sering terpotong padahal kolomnya harusnya bisa jauh lebih lebar.

---

## YANG DIMINTA

### A. Lebarkan konten, dan buat adaptif

Ganti batas 736px jadi **fluid** — lebar ikut ukuran layar, dengan batas atas
supaya baris tidak terlalu panjang untuk dibaca:

```css
.block-container {
    max-width: min(1600px, 94vw) !important;
    padding-left: clamp(1rem, 3vw, 3rem) !important;
    padding-right: clamp(1rem, 3vw, 3rem) !important;
    padding-top: 2rem !important;
}
```

**Alasan angka:**
- `min(1600px, 94vw)` — di monitor besar berhenti di 1600px (baris tidak
  terlalu panjang dibaca); di layar kecil otomatis 94% lebar.
- `clamp(1rem, 3vw, 3rem)` — padding samping ikut menyesuaikan, minimal 1rem
  (layar sempit tetap ada napas), maksimal 3rem (monitor besar tidak boros).

**WAJIB: verifikasi selector-nya benar.** Cek dulu dengan DevTools atau
`document.querySelector('.block-container')` — kalau Streamlit versi ini
memakai nama kelas berbeda (mis. `[data-testid="stMainBlockContainer"]`),
pakai selector yang **benar-benar ada**. Jangan asal tulis.

### B. Ubah ukuran fixed jadi fluid

Pakai `clamp()` supaya elemen menyesuaikan ukuran layar:

```css
.nx9-tbl-row {
    grid-template-columns:
        clamp(1.75rem, 2vw, 2.25rem)      /* nomor  */
        clamp(2.5rem, 3vw, 3rem)          /* cover  */
        minmax(0, 1fr)                    /* judul  */
        minmax(0, clamp(9rem, 14vw, 16rem)) /* album */
        clamp(2.75rem, 3.5vw, 3.5rem);    /* durasi */
    gap: clamp(0.75rem, 1.5vw, 1.5rem);
    padding: clamp(0.75rem, 1vw, 1rem) clamp(0.75rem, 1.5vw, 1.25rem);
}
```

**Alasan:** `clamp(min, ideal, max)` = "jangan lebih kecil dari X, jangan lebih
besar dari Y, idealnya Z yang ikut viewport". Ini yang bikin **universal**.

### C. Spacing pakai ritme 4/8px

Semua jarak harus kelipatan 4 atau 8 px (dalam rem: 0.25rem = 4px):

```
4px  = 0.25rem    8px  = 0.5rem     12px = 0.75rem
16px = 1rem       24px = 1.5rem     32px = 2rem
```

**Hapus** angka ganjil seperti `9px`, `10px`, `13px`, `14px`.

**Spesifik yang diminta:**
- `gap` baris: **16px** (1rem) — dari 10px
- `padding` baris: **12px 16px** (0.75rem 1rem) — dari 9px 10px
- Tinggi baris: **~64px** — dari ~52px
- Cover: **48px** (3rem) — dari 40px
- Radius cover: **8px** (0.5rem) — dari 6px

### D. Hierarki teks yang jelas

Ukuran font sekarang terlalu berdekatan (14px judul, 13px sub). Buat beda jelas:

```css
.nx9-tbl-title { font-size: 0.9375rem; font-weight: 600; line-height: 1.4; }  /* 15px */
.nx9-tbl-sub   { font-size: 0.8125rem; line-height: 1.4; }                    /* 13px */
.nx9-tbl-head  { font-size: 0.6875rem; letter-spacing: 0.06em; }              /* 11px */
```

### E. Media query lengkap (jangan cuma satu)

Sekarang cuma ada `@media (max-width: 900px)`. Tambah yang lengkap:

```css
/* Layar sangat lebar: batasi supaya baris tidak terlalu panjang */
@media (min-width: 1600px) {
    .block-container { max-width: 1600px !important; }
}

/* Tablet / laptop kecil: sembunyikan kolom album */
@media (max-width: 1100px) {
    .nx9-tbl-row { grid-template-columns: 2rem 3rem minmax(0, 1fr) 3rem; }
    .nx9-tbl-album { display: none; }
    .nx9-tbl-head.nx9-tbl-album { display: none; }
}

/* HP / jendela sempit: sembunyikan nomor juga, perbesar sentuhan */
@media (max-width: 640px) {
    .nx9-tbl-row { grid-template-columns: 2.75rem minmax(0, 1fr) 2.75rem; }
    .nx9-tbl-num { display: none; }
    .nx9-tbl-art { width: 2.75rem; height: 2.75rem; }
}
```

**Catatan:** kolom album di layout default ada di posisi ke-4. Kalau
disembunyikan, `grid-template-columns` **harus dikurangi satu kolom** —
kalau tidak, grid-nya berantakan. Pastikan jumlah kolom cocok.

### F. Terapkan juga ke halaman lain

Bukan cuma tabel Download Lagu. Cek juga:
- **Home** — header playlist (cover 200px fixed → pakai clamp)
- **Download Cover** — galeri (`COVER_COLUMNS = 4` fixed → responsif)
- **Sidebar** — kalau ada lebar fixed

---

## CARA MEMVERIFIKASI (WAJIB)

Jangan cuma bilang "sudah diperbaiki". **Ukur dan laporkan angka nyata.**

### 1. Cek lebar konten di beberapa ukuran layar

Kalau bisa, jalankan Streamlit dan cek dengan JavaScript:
```javascript
getComputedStyle(document.querySelector('.block-container')).maxWidth
```

Atau minimal: jelaskan selector apa yang dipakai dan **kenapa kamu yakin
selector itu benar** (mis. hasil inspeksi DOM).

### 2. Uji di 3 lebar layar

| Lebar | Yang harus terjadi |
|---|---|
| 1920px | Konten melebar (bukan 736px), padding proporsional |
| 1280px | Masih lega, semua kolom tampil |
| 800px | Kolom album hilang, judul masih kebaca |
| 480px | Nomor hilang, cover lebih besar, tidak ada overflow |

### 3. Pastikan tidak ada overflow horizontal

```javascript
document.documentElement.scrollWidth <= document.documentElement.clientWidth
```
Harus `true` di semua ukuran.

---

## YANG TIDAK BOLEH DIUBAH

1. **JANGAN ubah struktur grid HTML** — sudah benar (grid per baris).
2. **JANGAN hapus** `minmax(0, 1fr)` dan `min-width: 0` — itu yang bikin
   ellipsis jalan. Sudah ada komentar "load-bearing" di kode.
3. **JANGAN ubah halaman Download Cover jadi tabel** — tetap galeri.
4. **JANGAN bikin dari awal.** Modifikasi file yang sudah ada.
5. **JANGAN hapus CSS yang ada** — tambahkan/perbaiki.
6. **JANGAN pakai angka px fixed untuk lebar** yang seharusnya fluid.

---

## YANG SUDAH PASTI (jangan ubah asumsinya)

- Streamlit **1.63.0**
- Layar user **1920x1080**, konten sekarang terkunci di **736px**
- `ui/theme.py` punya **1 media query** saja (max-width: 900px)
- Hampir semua ukuran **px fixed**; tidak ada `rem`/`clamp`/`vw`
- Grid baris: `28px 40px minmax(0,1fr) minmax(0,140px) 44px`, `gap:10px`,
  `padding:9px 10px`
- Komentar di `ui/theme.py` bilang `.block-container caps the app at 736px` —
  **itu masalahnya**, bukan sesuatu yang harus dipertahankan
- `minmax(0, 1fr)` + `min-width: 0` WAJIB ada untuk ellipsis

## YANG BELUM PASTI

- Nama selector `.block-container` di Streamlit 1.63 — **verifikasi dulu**,
  mungkin `[data-testid="stMainBlockContainer"]`
- Apakah baris 64px cukup untuk widget Streamlit (checkbox + tombol) tanpa
  overflow — **ukur, jangan asumsi**. Komentar di kode menyebut slot aksi
  butuh 54px, jadi 64px harusnya aman, tapi buktikan.

---

## TEST YANG HARUS TETAP LOLOS

```bash
.venv/Scripts/python.exe tests/smoke.py              # PASS=25 FAIL=0
.venv/Scripts/python.exe tests/test_youtube.py       # PASS=27 FAIL=0
.venv/Scripts/python.exe tests/test_spotify_embed.py # PASS=35 FAIL=0
.venv/Scripts/python.exe tests/test_spclient.py      # PASS=115 FAIL=0
.venv/Scripts/python.exe tests/test_tags.py          # PASS=222 FAIL=0
.venv/Scripts/python.exe tests/test_cover_size.py    # PASS=0 FAIL=0
.venv/Scripts/python.exe tests/test_spotidown_co.py  # PASS=67 FAIL=0
.venv/Scripts/python.exe tests/test_theme.py         # PASS=51 FAIL=0
.venv/Scripts/python.exe tests/test_fetch_bytes.py   # PASS=12 FAIL=0
.venv/Scripts/python.exe tests/test_oauth.py         # PASS=32 FAIL=0
.venv/Scripts/python.exe tests/test_app.py           # ALL UI TESTS PASSED
```

---

## LAPORAN YANG DIMINTA

- Selector `.block-container` yang **benar-benar dipakai** (dan cara memastikan)
- Lebar konten **sebelum vs sesudah** pada 1920px (angka nyata)
- Jumlah `@media` sebelum vs sesudah
- Apakah masih ada `px` fixed untuk lebar (jelaskan yang tersisa dan alasannya)
- Hasil uji di 3-4 lebar layar berbeda
- Test apa yang dijalankan + hasilnya
- Apa yang belum selesai (jujur)

Kalau ada yang tidak bisa diverifikasi, **bilang apa adanya** — jangan mengarang.
