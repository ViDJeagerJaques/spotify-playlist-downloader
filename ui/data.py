"""Adapter between provider results and the dict shape the UI pages render.

``ui/dummy.py`` produced this same shape from hard-coded rows; this module
produces it from a real ``ResolveResult`` returned by a provider. Both modules
expose the same helper names, so the pages can be pointed at either one.

BATCH_LIMIT
-----------
This is the REAL cap, not a made-up number: spotidown.co's free tier returns at
most 100 tracks per playlist. Evidence from a live response:
``totalCount: 213`` with exactly 100 objects in ``tracks``.

We do NOT try to work around that limit (no pagination tricks, no extra params).
When a playlist is longer, ``playlist_view()`` surfaces ``provider_hint`` and the
UI tells the user the remaining tracks need a premium account and suggests
splitting the playlist.
"""
from __future__ import annotations

from typing import List, Optional

from core.orchestrator import make_provider
from providers.base import ProviderId, ResolveResult, Track

# Official free-tier limit of spotidown.co (100 tracks per playlist).
BATCH_LIMIT = 100

DEFAULT_PROVIDER = ProviderId.SPOTIDOWN_CO.value


def format_duration(ms: int) -> str:
    """Milliseconds -> 'm:ss' (providers report duration in ms)."""
    try:
        total = max(0, int(ms)) // 1000  # ms -> seconds
    except (TypeError, ValueError):
        return ""
    return f"{total // 60}:{total % 60:02d}"


def load_playlist(spotify_url: str, provider_id: str = DEFAULT_PROVIDER,
                  timeout: int = 90) -> ResolveResult:
    """Fetch a real playlist through the selected provider.

    Blocks for up to ``timeout`` seconds: the provider drives a real Chrome
    window so the site can solve its own Cloudflare challenge. Callers must show
    a spinner and warn the user not to close that window.
    """
    url = (spotify_url or "").strip()
    if not url:
        raise ValueError("Tempel URL playlist Spotify dulu.")

    provider = make_provider(provider_id)
    if provider_id == ProviderId.SPOTIDOWN_CO.value:
        # The SpotiDown.co client is the only one with a meaningful wait budget.
        provider._timeout = timeout
    return provider.load_tracks(url)


def playlist_view(result: ResolveResult) -> dict:
    """Flatten a ResolveResult into the dict shape the UI pages expect."""
    tracks: List[dict] = []
    for t in result.tracks:
        tracks.append(track_view(t))

    return {
        "url": result.source_url,
        "title": result.title,
        "total_count": len(result.tracks),
        "hint": result.raw_hint or "",
        "tracks": tracks,
    }


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
    rows = []
    for i, t in enumerate(view.get("tracks", []), 1):
        dur = f" ({t['duration']})" if t.get("duration") else ""
        rows.append(f"{i:02d}. {t['title']} - {t['artist']}{dur}")
    return "\n".join(rows)


def to_txt(view: dict) -> str:
    header = [f"# {view.get('title','')}", f"# source: {view.get('url','')}",
              f"# tracks: {view.get('total_count',0)}", ""]
    return "\n".join(header) + _stamp(view)


def to_csv(view: dict) -> str:
    lines = ["no,title,artist,album,duration,mp3_url"]
    for i, t in enumerate(view.get("tracks", []), 1):
        lines.append(
            f'{i},"{t.get("title","")}","{t.get("artist","")}",'
            f'"{t.get("album","")}","{t.get("duration","")}","{t.get("mp3_url","")}"'
        )
    return "\n".join(lines)


def to_json_obj(view: dict) -> dict:
    return {
        "title": view.get("title", ""),
        "source": view.get("url", ""),
        "total_tracks": view.get("total_count", 0),
        "free_tier_limit": BATCH_LIMIT,
        "notice": view.get("hint", ""),
        "tracks": view.get("tracks", []),
    }


def download_headers() -> dict:
    """MP3 endpoint headers (Origin/Referer) taken from the active provider."""
    from providers.spotidown_co import DOWNLOAD_HEADERS
    return dict(DOWNLOAD_HEADERS)


def cover_hint(count: int) -> Optional[str]:
    """Short note when a playlist has no cover art to show."""
    return None if count else "Playlist ini tidak punya cover."