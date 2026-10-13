"""Adapter between provider results and the dict shape the UI pages render.

``ui/dummy.py`` produced this same shape from hard-coded rows; this module
produces it from a real ``ResolveResult`` returned by a provider. Both modules
expose the same helper names, so the pages can be pointed at either one.

Note: the 100-track cap that used to be documented here belonged to a
third-party free tier which no longer exists. The Spotify embed page and the
anonymous client both return the whole playlist, so there is no limit here any
more — only the user's own choice of how many to download at a time.
"""
from __future__ import annotations

from typing import List, Optional

from core.orchestrator import make_provider
from providers.base import ProviderId, ResolveResult, Track

# How many songs go into one ZIP.
#
# User rule (2026-10): a playlist of 30 songs or fewer becomes ONE full ZIP;
# above 30 it is split into parts of 30 songs each. This is the only place the
# number lives — UI text and tests import it from here.
PART_SIZE = 30

# Kept as an alias because several modules (and older tests) referenced the old
# name. Same value; prefer PART_SIZE in new code.
BATCH_LIMIT = PART_SIZE

DEFAULT_PROVIDER = ProviderId.YOUTUBE.value


def format_duration(ms: int) -> str:
    """Milliseconds -> 'm:ss' (providers report duration in milliseconds)."""
    try:
        total_seconds = max(0, int(ms)) // 1000
    except (TypeError, ValueError):
        return ""
    return f"{total_seconds // 60}:{total_seconds % 60:02d}"


def format_total_duration(ms: int) -> str:
    """Milliseconds -> human total, e.g. '4 jam 37 menit' or '45 menit'.

    Used for the playlist header, where minutes-only would read oddly on long
    playlists.
    """
    try:
        total_minutes = max(0, int(ms)) // 60000
    except (TypeError, ValueError):
        return ""
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} jam {minutes} menit"
    if hours:
        return f"{hours} jam"
    return f"{minutes} menit"


def load_playlist(spotify_url: str, provider_id: str = DEFAULT_PROVIDER,
                  timeout: int = 90) -> ResolveResult:
    """Fetch a real playlist through the selected provider.

    ``timeout`` is still accepted because YouTube's client has a request timeout
    of its own; the value only widens it for providers that need a long budget.
    """
    url = (spotify_url or "").strip()
    if not url:
        raise ValueError("Tempel URL playlist Spotify dulu.")

    provider = make_provider(provider_id)
    return provider.load_tracks(url)


def playlist_view(result: ResolveResult, covers: Optional[dict] = None) -> dict:
    """Flatten a ResolveResult into the dict shape the UI pages expect.

    ``covers`` maps track id -> album cover URL. Anything missing keeps whatever
    the provider already supplied (the playlist-level image), so a failed cover
    lookup degrades to "same picture as before" rather than a blank tile.
    """
    tracks: List[dict] = []
    for t in result.tracks:
        row = track_view(t)
        if covers:
            better = covers.get(row["id"])
            if better:
                row["cover"] = better
        tracks.append(row)

    return {
        "url": result.source_url,
        "title": result.title,
        "total_count": len(result.tracks),
        "total_duration_ms": sum(int(t.duration_ms or 0) for t in result.tracks),
        "hint": result.raw_hint or "",
        "tracks": tracks,
    }


def apply_track_covers(view: dict, covers: dict) -> int:
    """Fill in per-track album covers on an existing view. Returns how many set."""
    if not covers or not view:
        return 0
    n = 0
    for row in view.get("tracks", []):
        better = covers.get(row.get("id"))
        if better and better != row.get("cover"):
            row["cover"] = better
            n += 1
    return n


def track_view(track: Track) -> dict:
    """One track as a flat dict for the card/grid/table rendering."""
    return {
        "id": track.track_token or track.data or track.title,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "cover": track.thumbnail,
        "duration": format_duration(track.duration_ms),
        "mp3_url": track.mp3_url or "",
    }


def chunk_parts(tracks: List[dict], limit: int = BATCH_LIMIT) -> List[List[dict]]:
    """Split tracks into batches of at most `limit` (100) tracks."""
    if limit <= 0:
        return [list(tracks)]
    return [tracks[i:i + limit] for i in range(0, len(tracks), limit)]


def filter_tracks(tracks: List[dict], query: str) -> List[dict]:
    """Case-insensitive search across title, artist and album."""
    q = (query or "").strip().lower()
    if not q:
        return tracks
    return [t for t in tracks
            if q in f"{t.get('title','')} {t.get('artist','')} {t.get('album','')}".lower()]


def _stamp(view: dict) -> str:
    """One 'judul - artist' line per track, numbered.

    Kept intentionally minimal: the backup is a plain song list, not a
    database dump. Duration / album / mp3_url were dropped per user request.
    """
    rows = []
    for i, t in enumerate(view.get("tracks", []), 1):
        rows.append(f"{i:02d}. {t.get('title','')} - {t.get('artist','')}")
    return "\n".join(rows)


def to_txt(view: dict) -> str:
    header = [f"# {view.get('title','')}", f"# source: {view.get('url','')}",
              f"# tracks: {view.get('total_count',0)}", ""]
    return "\n".join(header) + _stamp(view)


def to_csv(view: dict) -> str:
    lines = ["no,title,artist"]
    for i, t in enumerate(view.get("tracks", []), 1):
        lines.append(f'{i},"{t.get("title","")}","{t.get("artist","")}"')
    return "\n".join(lines)


def to_json_obj(view: dict) -> dict:
    return {
        "title": view.get("title", ""),
        "source": view.get("url", ""),
        "total_tracks": view.get("total_count", 0),
        "part_size": PART_SIZE,
        "notice": view.get("hint", ""),
        "tracks": [
            {"no": i, "title": t.get("title", ""), "artist": t.get("artist", "")}
            for i, t in enumerate(view.get("tracks", []), 1)
        ],
    }


def download_headers() -> dict:
    """Headers for fetching artwork from the Spotify CDN.

    Only the ``User-Agent`` is actually read by the caller (cover downloads hit
    ``i.scdn.co``). This used to return SpotiDown's Origin/Referer pair, which
    only made sense for *their* CDN and were meaningless here.
    """
    return {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0 Safari/537.36"),
    }


def cover_hint(count: int) -> Optional[str]:
    """Short note when a playlist has no cover art to show."""
    return None if count else "Playlist ini tidak punya cover."