"""Read playlist/album/track metadata from Spotify's PUBLIC embed page — no auth.

WHY THIS EXISTS
---------------
``providers/spotify_meta.py`` talks to the official Spotify Web API, which is the
right thing to do in principle. But as of Spotify's February 2026 API changes,
Client Credentials tokens can no longer read playlist *contents*:

    GET /playlists/{id}          -> 200   (name, track count)
    GET /playlists/{id}/items    -> 401   "Valid user authentication required"
    GET /playlists/{id}/tracks   -> 403

Requesting extra scopes does not help; the endpoint itself now demands a user
access token. Tracks, albums and /search still work fine with Client Credentials.

Spotify's own public **embed** page carries the same data with no login at all,
so we read that instead. Verified working for public playlists, albums and
single tracks, with a cap of 100 items per playlist.

DEPENDENCY NOTE
---------------
This reads HTML that Spotify serves to any visitor — it is not the Web API and it
is not covered by API versioning or stability guarantees. If Spotify changes the
embed markup, :func:`parse_embed_page` will stop finding ``__NEXT_DATA__`` and
:func:`embed_tracks` will raise a clear error instead of returning junk. The
Web API path in ``spotify_meta.py`` stays as the fallback.

LEGAL / SCOPE
-------------
Only PUBLIC playlists, albums and tracks can be read this way — that is exactly
the set Spotify publishes on those embed pages. Private content still requires a
real user login (see ``spotify_meta.py`` for that path). Nothing here bypasses
any access control.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from .base import ServiceError, Track

EMBED_BASE = "https://open.spotify.com/embed/{kind}/{sid}"
OEMBED_URL = ("https://open.spotify.com/oembed?url="
              + "https://open.spotify.com/{kind}/{sid}&format=json")

TIMEOUT = 25

# The embed page caps the visible list at 100 entries.
EMBED_ITEM_LIMIT = 100

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ServiceError(
            f"Spotify menjawab HTTP {exc.code} saat membuka halaman embed.",
            details=f"url={url}",
        ) from exc
    except urllib.error.URLError as exc:
        raise ServiceError(
            "Tidak bisa menghubungi open.spotify.com. Cek koneksi internet.",
            details=str(exc),
        ) from exc


def _get_json(url: str) -> dict:
    body = _get(url)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ServiceError("Respons Spotify bukan JSON yang valid.",
                           details=f"{exc}\n{body[:200]}") from exc


# --------------------------------------------------------------------------
# parsing (pure functions, unit-tested offline against saved fixtures)
# --------------------------------------------------------------------------
def parse_embed_page(html: str) -> dict:
    """Pull the embed page's ``__NEXT_DATA__`` entity dict out of the HTML.

    Raises a clear ServiceError when the markup changed — we never guess.
    """
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        raise ServiceError(
            "Halaman embed Spotify berubah bentuk, jadi playlist tidak bisa "
            "dibaca tanpa login. Coba backend SpotiDown.co di sidebar, atau "
            "pakai link album / link lagu (bukan playlist).",
            details="__NEXT_DATA__ script block not found on the embed page",
        )
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise ServiceError("Data __NEXT_DATA__ Spotify bukan JSON valid.",
                           details=str(exc)) from exc
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError) as exc:
        raise ServiceError(
            "Struktur data embed Spotify tidak seperti yang diharapkan.",
            details=f"cannot reach props.pageProps.state.data.entity: {exc}",
        ) from exc
    return entity


def _track_id(uri: str) -> str:
    """'spotify:track:5Ohx...' -> '5Ohx...'."""
    parts = (uri or "").split(":")
    return parts[-1] if parts else ""


def tracks_from_entity(entity: dict, cover_for: str = "") -> List[Track]:
    """Map the embed ``trackList`` onto Track objects.

    ``cover_for`` is a per-track cover URL to reuse for every row (the embed page
    only carries one playlist/album-level image, not per-track ones).
    """
    tracks: List[Track] = []
    for row in entity.get("trackList") or []:
        if not isinstance(row, dict):
            continue
        if row.get("entityType") not in (None, "track"):
            continue  # episodes / podcasts are not something we can resolve
        tid = _track_id(str(row.get("uri") or ""))
        if not tid:
            continue
        tracks.append(Track(
            data=tid,
            track_token=tid,
            title=str(row.get("title") or "Unknown"),
            # 'subtitle' on the embed page is the artist line.
            artist=str(row.get("subtitle") or "Unknown"),
            thumbnail=cover_for,
            mp3_url=None,               # resolved later via YouTube
            duration_ms=int(row.get("duration") or 0),
            album="",
        ))
    return tracks


def _playlist_cover(entity: dict) -> str:
    """Best available cover image URL from the embed entity (may be '')."""
    art = entity.get("coverArt")
    if isinstance(art, dict):
        sources = art.get("sources") or []
        if sources and isinstance(sources[0], dict):
            url = str(sources[0].get("url") or "")
            if url:
                return url
    visual = entity.get("visualIdentity")
    if isinstance(visual, dict):
        for key in ("image", "cover", "thumbnail"):
            val = visual.get(key)
            if isinstance(val, str) and val:
                return val
    return ""


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def oembed_cover(kind: str, sid: str) -> str:
    """Cover art URL via Spotify's public oEmbed endpoint (no auth).

    Spotify serves these from image-cdn / mosaic.scdn.co with permissive CORS;
    they are plain image files, so ``requests.get`` is enough to save them.
    """
    url = OEMBED_URL.format(kind=kind, sid=urllib.parse.quote(sid))
    try:
        data = _get_json(url)
    except ServiceError:
        return ""
    thumb = str(data.get("thumbnail_url") or "")
    if thumb:
        return thumb
    images = data.get("images") or []
    if images and isinstance(images[0], dict):
        return str(images[0].get("url") or "")
    return ""


def embed_tracks(url: str, max_items: int = 0) -> tuple[str, List[Track], str, str]:
    """Return ``(title, tracks, hint, cover_url)`` for a public Spotify link.

    ``hint`` explains any truncation we could not avoid. ``max_items`` > 0 stops
    early (useful for tests).
    """
    from .spotify_meta import parse_spotify_url

    kind, sid = parse_spotify_url(url)
    html = _get(EMBED_BASE.format(kind=kind, sid=sid))
    entity = parse_embed_page(html)

    title = str(entity.get("name") or entity.get("title") or "Spotify")

    if kind == "track":
        # A single track has no trackList; the entity itself is the track.
        tid = str(entity.get("id") or _track_id(str(entity.get("uri") or "")))
        if not tid:
            return title, [], "Halaman embed tidak memuat data lagu.", ""
        artists = entity.get("artists") or []
        artist = ", ".join(
            str(a.get("name") or "") for a in artists if isinstance(a, dict)
        ).strip(" ,") or str(entity.get("subtitle") or "Unknown")
        cover = _playlist_cover(entity) or oembed_cover(kind, tid)
        track = Track(
            data=tid, track_token=tid,
            title=str(entity.get("title") or entity.get("name") or "Unknown"),
            artist=artist,
            thumbnail=cover, mp3_url=None,
            duration_ms=int(entity.get("duration") or 0),
            album=str(entity.get("title") or "") if kind == "album" else "",
        )
        return title, [track], "", cover

    cover = _playlist_cover(entity) or oembed_cover(kind, sid)
    tracks = tracks_from_entity(entity, cover_for=cover)
    if max_items:
        tracks = tracks[:max_items]

    hint = ""
    total = 0
    raw_total = entity.get("trackCount") or entity.get("totalTracks")
    try:
        total = int(raw_total or 0)
    except (TypeError, ValueError):
        total = 0
    if total and len(tracks) < total:
        hint = (f"Playlist berisi {total} lagu, tapi halaman publik Spotify "
                f"hanya menampilkan {len(tracks)} (batas {EMBED_ITEM_LIMIT} "
                f"item per halaman). Sisanya tidak bisa dibaca tanpa login "
                f"Spotify. Struktur app ini membatasi {EMBED_ITEM_LIMIT} lagu "
                f"per batch — untuk playlist lebih besar, pecah jadi beberapa "
                f"playlist atau pakai backend SpotiDown.co.")

    return title, tracks, hint, cover
