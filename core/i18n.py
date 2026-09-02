"""Tiny bilingual (Indonesian/English) UI strings.

Selected by ``lang`` in app state (default "id"). Every user-facing label used
in app.py lives here so the UI stays consistent.
"""
from __future__ import annotations

TRANSLATIONS = {
    "id": {
        "app_title": "Spotify Playlist Downloader",
        "tagline": "Streamlit wrapper untuk layanan download pihak ketiga — SoundLoaders / SpotiDown.",
        "sidebar": {
            "title": "Pengaturan",
            "lang": "Bahasa / Language",
            "backend": "Backend service",
            "backend_help": "SoundLoaders adalah utama; SpotiDown cadangan; Demo untuk mencoba offline.",
            "source_kind": "Tipe konten",
            "auto": "Auto-detect (rekomendasi)",
            "playlist": "Playlist",
            "album": "Album",
            "track": "Track",
            "artist": "Artist / Artis",
            "captcha": "Token CAPTCHA (opsional, BYO)",
            "captcha_help": "Tempel token Turnstile (SoundLoaders) atau reCAPTCHA v3 (SpotiDown) yang diambil dari browser pribadimu. Kalau kosong dan service menolak, muncul error jelas.",
            "refresh_hint": "Cara ambil token: lihat panel 'Cara ambil token CAPTCHA'.",
            "zip_mode": "Mode batch download",
            "zip_mode_help": "'Bundel ZIP lokal' menyimpan tiap MP3 ke file sementara lalu mengemasnya. 'URL saja' tidak menyimpan file apa pun.",
            "zip_local": "Bundel ZIP lokal (rekomendasi)",
            "zip_url": "Kumpulkan URL saja",
            "btn_show_token_help": "Cara ambil token",
            "clear_btn": "Bersihkan sesi",
        },
        "main": {
            "url_label": "URL Spotify (track / album / playlist / artist / short link)",
            "url_placeholder": "https://open.spotify.com/playlist/... atau https://open.spotify.com/track/...",
            "btn_process": "Proses / Tampilkan Daftar Lagu",
            "processing": "Menghubungi {provider}…",
            "source": "Sumber",
            "tracks_found": "Ditemukan {n} lagu",
            "no_tracks": "Tidak ada lagu yang bisa diekstrak dari URL ini.",
            "no_tracks_hint": "Halaman berhasil dibuka tapi tidak ada baris lagu. Penyebab umum: markup service berubah, atau konten tidak didukung.",
            "filter": "Filter lagu…",
            "col_track": "Lagu",
            "col_download": "Download",
            "btn_download_one": "Download MP3",
            "btn_batch": "Download Semua ({n}) — ZIP lokal",
            "btn_batch_url": "Resolve semua ({n}) — URL MP3",
            "history_title": "Riwayat unduhan (sesi ini)",
            "status_waiting": "menunggu",
            "status_processing": "memproses…",
            "status_ready": "siap",
            "status_failed": "gagal",
            "none_done": "Belum ada unduhan di sesi ini.",
            "captcha_error_title": "CAPTCHA / token diperlukan",
            "captcha_error_body": "{msg} Ambil token Turnstile/reCAPTCHA dari browser lalu tempel di sidebar, atau ganti backend / coba lagi.",
            "service_error_title": "Error dari service",
            "switch_backend": "Coba ganti backend ke {other} lewat sidebar.",
            "network_hint": "Jika layanan sedang down / rate-limit, tidak ada yang bisa app ini lakukan selain menunggu — resolusinya 100% pihak ketiga.",
            "url_required": "Tempel URL Spotify dulu.",
            "url_not_spotify": "Itu bukan URL Spotify.",
            "no_match": "Tidak ada lagu yang cocok dengan filter.",
            "btn_download_mp3": "Simpan MP3",
            "open_mp3": "buka link",
            "btn_zip_download": "Download ZIP",
            "batch_done": "Batch selesai:",
            "zip_ready": "ZIP siap — pakai tombol 'Download ZIP' di atas.",
            "batch_ready_list": "Berhasil resolve {n} URL MP3:",
            "batch_failed_list": "{n} lagu gagal:",
        },
        "legal": {
            "title": "Disclaimer & Catatan Legal",
            "personal": "Hanya untuk **penggunaan pribadi**. Jangan redistribusi atau publikasikan hasil unduhan.",
            "no_scraper": "Aplikasi ini **tidak punya scraper Spotify**. URL diteruskan ke layanan pihak ketiga (SoundLoaders / SpotiDown); kalau layanan itu down / berubah / rate-limit, app ini tidak bisa download.",
            "tos": "Mengunduh musik dari Spotify via layanan pihak ketiga **dapat melanggar** ToS Spotify maupun layanan tsb. Tinjau hukum setempatmu.",
            "no_guarantee": "Tidak ada jaminan ketersediaan, kualitas, atau legalitas hasil. Token CAPTCHA adalah milikmu sendiri; layanan dapat menolak tanpa peringatan.",
            "your_responsibility": "Tanggung jawab penggunaan ada pada dirimu sendiri.",
        },
        "help_token": {
            "title": "Cara ambil token CAPTCHA (BYO token)",
            "sl_steps": [
                "Buka https://soundloaders.app/ di browser (Chrome/Edge).",
                "Tekan F12 → tab Console.",
                "Tempel snippet di bawah lalu Enter. Widget Turnstile otomatis jalan; hasil token tercetak di console.",
                "Salin token, tempel ke kolom sidebar, lalu klik Proses.",
            ],
            "sd_steps": [
                "Buka https://spotidown.app/ di browser.",
                "Tekan F12 → tab Console.",
                "Tempel snippet reCAPTCHA v3, lalu submit/unduh sekali lewat UI mereka agar token terbentuk.",
                "Salin nilai yang tercetak, tempel ke kolom sidebar.",
            ],
            "code_title": "Snippet untuk dijalankan di console browser (F12):",
            "mock_note": "Mode Demo tidak butuh token.",
        },
    },
    "en": {
        "app_title": "Spotify Playlist Downloader",
        "tagline": "A Streamlit wrapper around third-party downloaders — SoundLoaders / SpotiDown.",
        "sidebar": {
            "title": "Settings",
            "lang": "Language",
            "backend": "Backend service",
            "backend_help": "SoundLoaders is primary; SpotiDown is fallback; Demo to try offline.",
            "source_kind": "Content type",
            "auto": "Auto-detect (recommended)",
            "playlist": "Playlist",
            "album": "Album",
            "track": "Track",
            "artist": "Artist",
            "captcha": "CAPTCHA token (optional, BYO)",
            "captcha_help": "Paste a Turnstile (SoundLoaders) or reCAPTCHA v3 (SpotiDown) token obtained from your own browser. If blank and the service rejects, you get a clear error.",
            "refresh_hint": "How to obtain a token: see 'How to get a CAPTCHA token'.",
            "zip_mode": "Batch download mode",
            "zip_mode_help": "'Local ZIP bundle' stores each MP3 to a temp file then packages them. 'URLs only' does not store files.",
            "zip_local": "Local ZIP bundle (recommended)",
            "zip_url": "Collect URLs only",
            "btn_show_token_help": "How to get a token",
            "clear_btn": "Clear session",
        },
        "main": {
            "url_label": "Spotify URL (track / album / playlist / artist / short link)",
            "url_placeholder": "https://open.spotify.com/playlist/... or https://open.spotify.com/track/...",
            "btn_process": "Process / Show Track List",
            "processing": "Contacting {provider}…",
            "source": "Source",
            "tracks_found": "Found {n} track(s)",
            "no_tracks": "No tracks could be extracted from that URL.",
            "no_tracks_hint": "The page responded but no track rows were found. Likely the service markup changed, or the content is unsupported.",
            "filter": "Filter tracks…",
            "col_track": "Track",
            "col_download": "Download",
            "btn_download_one": "Download MP3",
            "btn_batch": "Download All ({n}) — local ZIP",
            "btn_batch_url": "Resolve all ({n}) — MP3 URLs",
            "history_title": "Download history (this session)",
            "status_waiting": "waiting",
            "status_processing": "processing…",
            "status_ready": "ready",
            "status_failed": "failed",
            "none_done": "Nothing downloaded in this session yet.",
            "captcha_error_title": "CAPTCHA / token required",
            "captcha_error_body": "{msg} Obtain a Turnstile/reCAPTCHA token from your browser, paste it in the sidebar, or switch backend / retry.",
            "service_error_title": "Service error",
            "switch_backend": "Try the {other} backend from the sidebar.",
            "network_hint": "If the service is down or rate-limited there is nothing this app can do but wait — resolution is 100% third-party.",
            "url_required": "Please paste a Spotify URL first.",
            "url_not_spotify": "That does not look like a Spotify URL.",
            "no_match": "No track matches the filter.",
            "btn_download_mp3": "Save MP3",
            "open_mp3": "open link",
            "btn_zip_download": "Download ZIP",
            "batch_done": "Batch finished:",
            "zip_ready": "The ZIP is ready — use the 'Download ZIP' button above.",
            "batch_ready_list": "Resolved {n} MP3 URL(s):",
            "batch_failed_list": "{n} track(s) failed:",
        },
        "legal": {            "title": "Disclaimer & Legal Notes",
            "personal": "For **personal use only**. Do not redistribute or publish the downloaded content.",
            "no_scraper": "This app has **no Spotify scraper**. URLs are forwarded to a third-party service (SoundLoaders / SpotiDown); if that service is down / changes / rate-limits, this app cannot download.",
            "tos": "Downloading music from Spotify via third-party tools **may violate** the Spotify ToS and the tool's own ToS. Check your local laws.",
            "no_guarantee": "No guarantee of availability, quality or legality. CAPTCHA tokens are your own; the service may reject requests without notice.",
            "your_responsibility": "Responsibility for usage is yours.",
        },
        "help_token": {
            "title": "How to obtain a CAPTCHA token (BYO token)",
            "sl_steps": [
                "Open https://soundloaders.app/ in a browser (Chrome/Edge).",
                "Press F12 -> Console tab.",
                "Paste the snippet below and press Enter. The Turnstile widget runs automatically and prints the token.",
                "Copy the token, paste it into the sidebar field, then click Process.",
            ],
            "sd_steps": [
                "Open https://spotidown.app/ in a browser.",
                "Press F12 -> Console tab.",
                "Paste the reCAPTCHA v3 snippet below, then submit/download once through their UI so a token is created.",
                "Copy the printed value into the sidebar field.",
            ],
            "code_title": "Snippet to run in the browser console (F12):",
            "mock_note": "Demo mode does not need a token.",
        },
    },
}


def _dig(table, dotted: str):
    node = table
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def tr(lang: str, key: str, **fmt) -> str:
    """Look up a (possibly dotted) translation, falling back to id -> key."""
    lang = lang if lang in TRANSLATIONS else "id"
    value = _dig(TRANSLATIONS[lang], key)
    if value is None:
        value = _dig(TRANSLATIONS["id"], key)
    if value is None:
        return key
    return value.format(**fmt) if isinstance(value, str) else value
