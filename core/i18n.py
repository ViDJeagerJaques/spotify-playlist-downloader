"""Tiny bilingual (Indonesian/English) UI strings.

Selected by ``lang`` in app state (default "id"). Every user-facing label used
in app.py lives here so the UI stays consistent.
"""
from __future__ import annotations

TRANSLATIONS = {
    "id": {
        "app_title": "Spotify Playlist Downloader",
        "tagline": "Audio dari YouTube untuk playlist Spotify publik — tanpa layanan pihak ketiga, tanpa browser.",
        "sidebar": {
            "title": "Pengaturan",
            "lang": "Bahasa / Language",
            "backend": "Backend service",
            "backend_help": "YouTube (yt-dlp) adalah satu-satunya backend. Demo untuk mencoba offline tanpa jaringan.",
            "zip_mode": "Mode batch download",
            "zip_mode_help": "'Bundel ZIP lokal' menyimpan tiap MP3 ke file sementara lalu mengemasnya. 'URL saja' tidak menyimpan file apa pun.",
            "zip_local": "Bundel ZIP lokal (rekomendasi)",
            "zip_url": "Kumpulkan URL saja",
            "clear_btn": "Bersihkan sesi",
            "cache_title": "Cache & ruang disk",
            "cache_help": "MP3 hasil unduhan, metadata dan ZIP batch disimpan di folder proyek, bukan di disk sistem C:. Aman dihapus kapan saja — lagu yang dihapus akan diunduh ulang.",
            "cache_usage": "Cache memakai {files} file ({mb:.1f} MB) di {path}",
            "cache_confirm": "Ya, hapus semua cache",
            "cache_btn": "Bersihkan cache",
            "cache_cleared": "Cache dibersihkan: {files} file / {mb:.1f} MB dibebaskan.",
            "cache_never": "Belum ada cache.",
        },
        "main": {
            "processing": "Menghubungi {provider}…",
            "source": "Sumber",
            "tracks_found": "Ditemukan {n} lagu",
            "no_tracks": "Tidak ada lagu yang bisa diekstrak dari URL ini.",
            "no_tracks_hint": "Halaman berhasil dibuka tapi tidak ada baris lagu. Penyebab umum: markup service berubah, atau konten tidak didukung.",
            "filter": "Filter lagu…",
            "col_track": "Lagu",
            "btn_download_one": "Download MP3",
            "btn_batch": "Download Semua ({n}) — ZIP lokal",
            "btn_batch_url": "Resolve semua ({n}) — URL MP3",
            "history_title": "Riwayat unduhan (sesi ini)",
            "status_ready": "siap",
            "status_failed": "gagal",
            "none_done": "Belum ada unduhan di sesi ini.",
            "captcha_error_title": "Token tidak dibutuhkan (backend lama)",
            "captcha_error_body": "{msg} Backend YouTube tidak memakai token sama sekali — muat ulang playlist lewat Home.",
            "service_error_title": "Error dari service",
            "network_hint": "Kalau YouTube sedang rate-limit atau memblokir IP datacenter, tidak ada yang bisa app ini lakukan selain menunggu. Jalankan di koneksi rumah.",
            "url_required": "Tempel URL Spotify dulu.",
            "url_not_spotify": "Itu bukan URL Spotify.",
            "no_match": "Tidak ada lagu yang cocok dengan filter.",
            "btn_download_mp3": "Simpan MP3",
            "open_mp3": "buka link",
            "btn_zip_download": "Download ZIP",
            "batch_done": "Batch selesai:",
            "retry_token_title": "{c} dari {n} gagal di jalur backend lama.",
            "retry_other_title": "{n} lagu gagal (bukan token).",
            "retry_hint": "Coba lagi, atau muat ulang playlist di Home untuk mengambil daftar lagu baru.",
            "btn_retry": "Retry {n} gagal",
            "retry_no_token": "Muat ulang playlist di Home dulu.",
            "retry_done": "Retry selesai: {ok} pulih, {fail} masih gagal.",
            "retry_all_ok": "Semua lagu pulih setelah retry. 🎉",
            "token_refresh_hint": "Muat ulang playlist di Home lalu coba lagi.",
            "zip_ready": "ZIP siap — pakai tombol 'Download ZIP' di atas.",
            "batch_ready_list": "Berhasil resolve {n} URL MP3:",
            "batch_failed_list": "{n} lagu gagal:",
        },
        "legal": {
            "title": "Disclaimer & Catatan Legal",
            "personal": "Hanya untuk **penggunaan pribadi**. Jangan redistribusi atau publikasikan hasil unduhan.",
            "no_scraper": "Aplikasi ini **tidak punya scraper Spotify**. Daftar lagu dibaca dari halaman embed publik Spotify, audio diambil dari YouTube.",
            "tos": "Mengunduh musik **dapat melanggar** ToS Spotify dan hak cipta. Tinjau hukum setempatmu.",
            "no_guarantee": "Tidak ada jaminan ketersediaan, kualitas, atau legalitas hasil.",
            "your_responsibility": "Tanggung jawab penggunaan ada pada dirimu sendiri.",
        },
        "help_token": {
            "mock_note": "Mode Demo tidak butuh token.",
        },
    },
    "en": {
        "app_title": "Spotify Playlist Downloader",
        "tagline": "Audio straight from YouTube for public Spotify playlists — no third-party service, no browser.",
        "sidebar": {
            "title": "Settings",
            "lang": "Language",
            "backend": "Backend service",
            "backend_help": "YouTube (yt-dlp) is the only backend. Demo runs offline, no network.",
            "zip_mode": "Batch download mode",
            "zip_mode_help": "'Local ZIP bundle' stores each MP3 to a temp file then packages them. 'URLs only' does not store files.",
            "zip_local": "Local ZIP bundle (recommended)",
            "zip_url": "Collect URLs only",
            "clear_btn": "Clear session",
            "cache_title": "Cache & disk space",
            "cache_help": "Downloaded MP3s, metadata and batch ZIPs live in the project folder, not on the C: system disk. Safe to delete at any time — removed tracks are re-downloaded on demand.",
            "cache_usage": "Cache is using {files} files ({mb:.1f} MB) in {path}",
            "cache_confirm": "Yes, delete all cache",
            "cache_btn": "Clear cache",
            "cache_cleared": "Cache cleared: {files} files / {mb:.1f} MB freed.",
            "cache_never": "No cache yet.",
        },
        "main": {
            "processing": "Contacting {provider}…",
            "source": "Source",
            "tracks_found": "Found {n} track(s)",
            "no_tracks": "No tracks could be extracted from that URL.",
            "no_tracks_hint": "The page responded but no track rows were found. Likely the service markup changed, or the content is unsupported.",
            "filter": "Filter tracks…",
            "col_track": "Track",
            "btn_download_one": "Download MP3",
            "btn_batch": "Download All ({n}) — local ZIP",
            "btn_batch_url": "Resolve all ({n}) — MP3 URLs",
            "history_title": "Download history (this session)",
            "status_ready": "ready",
            "status_failed": "failed",
            "none_done": "Nothing downloaded in this session yet.",
            "captcha_error_title": "No token needed (legacy backend)",
            "captcha_error_body": "{msg} The YouTube backend does not use tokens at all — reload the playlist from Home.",
            "service_error_title": "Service error",
            "network_hint": "If YouTube is rate-limiting or blocking a datacenter IP there is nothing this app can do but wait. Run it on a home connection.",
            "url_required": "Please paste a Spotify URL first.",
            "url_not_spotify": "That does not look like a Spotify URL.",
            "no_match": "No track matches the filter.",
            "btn_download_mp3": "Save MP3",
            "open_mp3": "open link",
            "btn_zip_download": "Download ZIP",
            "batch_done": "Batch finished:",
            "retry_token_title": "{c} of {n} failed on the legacy backend path.",
            "retry_other_title": "{n} track(s) failed (not token-related).",
            "retry_hint": "Try again, or reload the playlist from Home to pick up a fresh track list.",
            "btn_retry": "Retry {n} failed",
            "retry_no_token": "Reload the playlist from Home first.",
            "retry_done": "Retry finished: {ok} recovered, {fail} still failing.",
            "retry_all_ok": "All tracks recovered after retry. 🎉",
            "token_refresh_hint": "Reload the playlist from Home, then try again.",
            "zip_ready": "The ZIP is ready — use the 'Download ZIP' button above.",
            "batch_ready_list": "Resolved {n} MP3 URL(s):",
            "batch_failed_list": "{n} track(s) failed:",
        },
        "legal": {
            "title": "Disclaimer & Legal Notes",
            "personal": "For **personal use only**. Do not redistribute or publish the downloaded content.",
            "no_scraper": "This app has **no Spotify scraper**. The track list comes from Spotify's public embed page; the audio comes from YouTube.",
            "tos": "Downloading music **may violate** the Spotify ToS and copyright law. Check your local rules.",
            "no_guarantee": "No guarantee of availability, quality or legality.",
            "your_responsibility": "Responsibility for usage is yours.",
        },
        "help_token": {
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
