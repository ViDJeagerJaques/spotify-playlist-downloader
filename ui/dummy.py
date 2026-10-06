"""Dummy/mock data KHUSUS untuk tahap UI.

Modul ini TIDAK menyentuh provider / API / scraping / Spotify API /
Cloudflare / CAPTCHA / sistem download asli. Hanya data statis untuk
membangun struktur UI + navigasi.

Tahap berikutnya (download asli) akan mengganti pemakaian modul ini
dengan hasil dari providers/* + core/orchestrator.py yang sudah ada
(tidak diubah pada tahap ini).
"""
from __future__ import annotations

BATCH_LIMIT = 15

_DUMMY_TRACKS: list[dict] = [
    {"id": "t01", "title": "Neon Lights", "artist": "Reva Dawn", "duration": "3:12"},
    {"id": "t02", "title": "Midnight Drive", "artist": "The Afterglows", "duration": "4:05"},
    {"id": "t03", "title": "Golden Hour", "artist": "Lumen", "duration": "2:58"},
    {"id": "t04", "title": "Paper Planes", "artist": "Coastline", "duration": "3:44"},
    {"id": "t05", "title": "Slow Motion", "artist": "Kite String", "duration": "3:21"},
    {"id": "t06", "title": "Salt Air", "artist": "Marina Lines", "duration": "3:09"},
    {"id": "t07", "title": "Echo Park", "artist": "Night Reel", "duration": "4:12"},
    {"id": "t08", "title": "Ultraviolet", "artist": "Prism Break", "duration": "3:33"},
    {"id": "t09", "title": "Honeydew", "artist": "Summer Clinic", "duration": "2:47"},
    {"id": "t10", "title": "Glasshouse", "artist": "Fern & Field", "duration": "3:55"},
    {"id": "t11", "title": "Daydream Radio", "artist": "Pilot Light", "duration": "3:18"},
    {"id": "t12", "title": "Copper Sky", "artist": "Juniper", "duration": "4:01"},
    {"id": "t13", "title": "Low Orbit", "artist": "Satellite Hearts", "duration": "3:26"},
    {"id": "t14", "title": "Wildflower", "artist": "Iris Vale", "duration": "3:49"},
    {"id": "t15", "title": "Static Bloom", "artist": "Velvet Antenna", "duration": "3:02"},
    {"id": "t16", "title": "Northbound", "artist": "Harbour Lights", "duration": "3:37"},
    {"id": "t17", "title": "Cassette Summer", "artist": "Tape Waves", "duration": "2:59"},
    {"id": "t18", "title": "Half Light", "artist": "Aurora Line", "duration": "4:08"},
    {"id": "t19", "title": "Fever Dream", "artist": "Mira Sol", "duration": "3:15"},
    {"id": "t20", "title": "Driftwood", "artist": "Cedar & Stone", "duration": "3:41"},
    {"id": "t21", "title": "Supernova Kiss", "artist": "Nova Reyes", "duration": "3:28"},
    {"id": "t22", "title": "Blue Hour", "artist": "Palma Violets", "duration": "3:53"},
    {"id": "t23", "title": "Afterglow", "artist": "Second Sunrise", "duration": "4:00"},
]

for _t in _DUMMY_TRACKS:
    _t["cover"] = f"https://picsum.photos/seed/spotify-{_t['id']}/300"


def get_dummy_playlist(playlist_url: str) -> dict:
    """Kembalikan info playlist dummy + salinan list track dummy.

    playlist_url hanya disimpan/ditampilkan, tidak dipakai untuk fetch apa pun.
    Sengaja 23 lagu agar alur '> 15 lagu -> bagi per Part' bisa terlihat.
    Logika chunk-nya sendiri menangani kasus <= 15 (satu batch).
    """
    return {
        "url": playlist_url,
        "title": "Dummy Playlist — Late Night Drive (Mock UI)",
        "owner": "mock-user",
        "cover": "https://picsum.photos/seed/spotify-playlist-cover/400",
        "description": "Data dummy untuk tahap UI. Download asli belum aktif.",
        "tracks": [dict(t) for t in _DUMMY_TRACKS],
    }


def chunk_parts(tracks: list[dict], limit: int = BATCH_LIMIT) -> list[list[dict]]:
    """Bagi track menjadi beberapa Part, maksimal `limit` lagu per part."""
    return [tracks[i:i + limit] for i in range(0, len(tracks), limit)]


def filter_tracks(tracks: list[dict], query: str) -> list[dict]:
    """Filter case-insensitive berdasarkan judul + artist (untuk search UI)."""
    q = (query or "").strip().lower()
    if not q:
        return tracks
    return [t for t in tracks if q in f"{t['title']} {t['artist']}".lower()]


def to_txt_preview(playlist: dict) -> str:
    lines = [f"# {playlist['title']}", f"# source: {playlist['url']}", ""]
    for i, t in enumerate(playlist["tracks"], 1):
        lines.append(f"{i:02d}. {t['title']} - {t['artist']} ({t['duration']})")
    return "\n".join(lines)


def to_csv_preview(playlist: dict) -> str:
    lines = ["no,title,artist,duration"]
    for i, t in enumerate(playlist["tracks"], 1):
        lines.append(f'{i},"{t["title"]}","{t["artist"]}",{t["duration"]}')
    return "\n".join(lines)
