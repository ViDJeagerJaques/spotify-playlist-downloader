# Catatan Revisi — 11 Okt 2026

## R5 — Layout tabel Download Lagu masih kacau

**Status: BELUM dikerjakan. Ditampung atas permintaan user.**

**Gejala:** tabel Download Lagu (5 kolom: nomor, cover, judul+artist, album, durasi)
layout-nya berantakan setelah dikerjakan OpenCode.

**Akar masalah (sudah didiagnosis):**

OpenCode memakai `st.columns()` **7 kolom per baris**:
```python
num_col, check_col, art_col, title_col, album_col, dur_col, btn_col = st.columns(
    [0.4, 0.5, 0.7, 4.6, 2.4, 0.7, 1.1])
```

Streamlit **selalu memberi gap ~1rem antar kolom**. Dengan 7 kolom × 25 baris,
gap menumpuk dan menyebabkan:
- Cover kegeser jauh dari judul
- Judul jadi sempit, teks kepotong padahal kolomnya lebar
- Baris tidak sejajar kalau panjang teks berbeda
- Kolom nomor & checkbox kekecilan (rasio 0.4 & 0.5)

**`ui/theme.py` tidak punya aturan** untuk `stHorizontalBlock` / `stColumn`,
jadi tidak ada yang menetralkan gap bawaan Streamlit.

**Struktur DOM Streamlit:**
```
stHorizontalBlock > stColumn > stVerticalBlock > div > markdown
```
Jarak antar kolom diatur di level `stHorizontalBlock` — CSS cell tidak bisa
menimpanya.

**Solusi yang direkomendasikan (Opsi A):**

Satu blok HTML per baris, pakai CSS grid:
```html
<div class="nx9-row">
  <div class="num">1</div>
  <div class="art"><img src="..."></div>
  <div class="body"><div class="t">Judul</div><div class="s">Artist</div></div>
  <div class="album">Album</div>
  <div class="dur">5:39</div>
</div>
```
```css
.nx9-row {
  display: grid;
  grid-template-columns: 32px 48px 1fr 200px 60px;
  align-items: center;
  gap: 12px;
}
```

**Kendala:** checkbox & tombol Streamlit **tidak bisa** dirender di dalam
`st.markdown`. Jadi:
- Grid HTML untuk: nomor + cover + judul/artist + album + durasi
- `st.columns` terpisah (2 kolom saja) untuk: checkbox + tombol

Hasil: tiap baris = 2 elemen Streamlit, bukan 7. Gap minimal, kolom teks
pasti sejajar.

**Opsi B (alternatif, kurang bagus):**
Tetap `st.columns` tapi:
- Pakai `gap="small"` atau `gap=None`
- Tambah CSS: `[data-testid="stHorizontalBlock"] { gap: 0 }`
- Rapikan rasio kolom
Masih menyisakan gap bawaan.

---

## Status repo saat catatan dibuat

- 374 test lolos (test_spclient 115, test_app OK)
- Cover playlist di header: BELUM (bagian 1 PROMPT_OPENCODE_FINAL.md)
- Tabel Download Lagu: dikerjakan tapi layout kacau
- BELUM di-commit
- `tools/` bersih (hanya `spotidown_grab.py`)

## Prompt yang masih relevan

| File | Status |
|---|---|
| `PROMPT_OPENCODE_FINAL.md` | sudah dilempar — bagian 1 (cover playlist) belum, bagian 2 (tabel) layout kacau |
| `PROMPT_OPENCODE_COVER_HD.md` | selesai |
| `PROMPT_OPENCODE_PERFORMA.md` | selesai |
| `PROMPT_OPENCODE_R0_R4.md` | selesai |

## Rencana berikutnya

1. Perbaiki layout tabel (R5) — pakai grid HTML
2. Selesaikan cover playlist di header (bagian 1)
3. Putuskan cara bikin EXE (PyInstaller vs CustomTkinter)
4. Commit semua perubahan
