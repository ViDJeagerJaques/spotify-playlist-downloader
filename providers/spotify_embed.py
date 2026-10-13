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
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from .base import ServiceError, Track, cache_dir, upgrade_cover_url

EMBED_BASE = "https://open.spotify.com/embed/{kind}/{sid}"
OEMBED_URL = ("https://open.spotify.com/oembed?url="
              + "https://open.spotify.com/{kind}/{sid}&format=json")

TIMEOUT = 25

# The embed page caps the visible list at 100 entries.
EMBED_ITEM_LIMIT = 100

# Disc cache for album cover URLs. Spotify's public embed page only exposes ONE
# image for the whole playlist, so the real per-album artwork must come from the
# Web API (GET /tracks/{id}). Caching means re-loading the same playlist — or a
# different playlist containing the same tracks — costs zero requests.
CACHE_DIR = cache_dir()

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
            "dibaca tanpa login. Pakai link album / link lagu (bukan playlist), "
            "atau isi credential Web API di .env.",
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
    """Best available PLAYLIST image URL from the embed entity (may be '').

    Deliberately NOT upgraded to 640x640: playlist art uses a different prefix
    family (``ab67706f…``) and 404s at the large album prefix.
    """
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

    Album/track covers come back at 300x300 and are upgraded to 640x640. For a
    playlist the prefix is different and the upgrade is a no-op, so it is safe to
    apply unconditionally.
    """
    url = OEMBED_URL.format(kind=kind, sid=urllib.parse.quote(sid))
    try:
        data = _get_json(url)
    except ServiceError:
        return ""
    thumb = str(data.get("thumbnail_url") or "")
    if thumb:
        return upgrade_cover_url(thumb)
    images = data.get("images") or []
    if images and isinstance(images[0], dict):
        return upgrade_cover_url(str(images[0].get("url") or ""))
    return ""


def embed_tracks(url: str, max_items: int = 0) -> tuple[str, List[Track], str, str]:
    """Return ``(title, tracks, hint, cover_url)`` for a public Spotify link.

    ``hint`` explains any truncation we could not avoid. ``max_items`` > 0 stops
    early (useful for tests).
    """
    title, tracks, hint, cover, _owner, _total_ms = embed_tracks_detailed(
        url, max_items=max_items)
    return title, tracks, hint, cover


def embed_tracks_complete(url: str, max_items: int = 0,
                          progress=None) -> tuple:
    """Read a playlist with NO 100-song cap, using only anonymous endpoints.

    This is the primary path for public playlists:

        1. embed playlist page -> first 100 songs + anon token + owner + cover
        2. spclient (anon token) -> every track id, in playlist order
        3. /embed/track + oEmbed  -> metadata + cover for every song
        4. spclient metadata      -> album / label / year / track number (ID3)

    Returns ``(title, tracks, hint, cover_url, owner, total_duration_ms)``.

    ``progress(done, total)`` is called while step 3 runs so the UI can show a
    bar — a 213-song playlist takes a while on a cold cache.

    NOTHING here touches api.spotify.com, which rate-limits hard (429).
    Private playlists still need a user login; see ``spotify_meta.py``.
    """
    from .spotify_meta import parse_spotify_url

    kind, sid = parse_spotify_url(url)

    # ---- steps 1+2: the embed page, then the full list via its anon token
    anon = ""
    ids: List[str] = []
    length = 0
    owner = ""
    truncated = False
    html = ""
    entity: dict = {}
    first_batch: List[Track] = []
    title = "Spotify"
    embed_owner = ""
    cover = ""
    try:
        html = _get(EMBED_BASE.format(kind=kind, sid=sid))
        entity = parse_embed_page(html)

        title = str(entity.get("name") or entity.get("title") or "Spotify")
        embed_owner = str(entity.get("subtitle") or "").strip()
        cover = _playlist_cover(entity) or oembed_cover(kind, sid)
        first_batch = tracks_from_entity(entity, cover_for=cover)
        if max_items:
            first_batch = first_batch[:max_items]

        from .spotify_spclient import extract_anon_token, playlist_track_ids

        anon = extract_anon_token(html)
        ids, length, owner, truncated = playlist_track_ids(sid, anon)
    except Exception as exc:  # noqa: BLE001
        # Rate limiting or a shape change must not lose the playlist: keep
        # whatever the embed page already gave us.
        if not first_batch:
            raise
        ids, length, owner, truncated = [], 0, "", False
        anon = ""

    # A single track or an album is already complete on the embed page.
    if kind != "playlist":
        total_ms = sum(int(t.duration_ms or 0) for t in first_batch)
        return title, first_batch, "", cover, embed_owner, total_ms

    if not ids:
        # Graceful degradation: keep the 100 songs and explain the shortfall.
        hint = _cap_hint(len(first_batch), len(first_batch))
        total_ms = sum(int(t.duration_ms or 0) for t in first_batch)
        return title, first_batch, hint, cover, embed_owner, total_ms

    by_id = {t.track_token: t for t in first_batch}

    # ---- steps 3+4: per-track metadata, cover, album/label/year.
    #
    # The spclient metadata endpoint already returns title, artists, duration AND
    # the album artwork, so it is the primary source: one request per song
    # instead of three (embed track + oEmbed + metadata). That is what keeps a
    # COLD 213-song load at ~214 requests rather than ~640 — the old shape hit
    # Spotify's rate limit and came back truncated.
    #
    # /embed/track + oEmbed stay as the fallback for anything metadata misses.
    details = {}
    tag_meta = {}
    if ids:
        try:
            from .spotify_spclient import cached_metadata_many

            tag_meta = cached_metadata_many(ids, anon)
            details = {tid: info for tid, info in tag_meta.items() if info}
        except Exception:  # noqa: BLE001
            details = {}

        still_missing = [t for t in ids if t not in details]
        if still_missing:
            try:
                details.update(cached_track_details(still_missing, progress=progress))
            except Exception:  # noqa: BLE001
                pass

    for tid in ids:
        info = details.get(tid)
        if not info:
            continue          # failed lookup -> the embed row stays as-is
        # Merge onto the embed row so fields spclient does not return survive.
        base = by_id.get(tid)
        artists = info.get("artists") or []
        album_name = info.get("album") or (base.album if base else "")
        row = Track(
            data=tid,
            track_token=tid,
            title=info.get("title") or (base.title if base else "Unknown"),
            artist=", ".join(a for a in artists if a) or (base.artist if base else "Unknown"),
            thumbnail=info.get("cover") or (base.thumbnail if base else cover),
            mp3_url=None,
            duration_ms=int(info.get("duration_ms") or (base.duration_ms if base else 0)),
            album=album_name,
        )
        # Tagging extras (R4). album comes only from the metadata endpoint —
        # /embed/track has no album name — so it must be applied here too.
        tag = (tag_meta or {}).get(tid) or {}
        if tag.get("album"):
            row.album = str(tag["album"])
        for attr in ("label", "year", "track_number", "disc_number"):
            value = tag.get(attr)
            if value in (None, ""):
                continue
            if attr == "label":
                setattr(row, attr, str(value))
            else:
                try:
                    setattr(row, attr, int(value))
                except (TypeError, ValueError):
                    pass
        by_id[tid] = row

    # Playlist ORDER comes from spclient, not from the order requests finished.
    tracks = [by_id[t] for t in ids if t in by_id]
    total_ms = sum(int(t.duration_ms or 0) for t in tracks)

    hint = ""
    if truncated or len(tracks) < length:
        hint = (f"Playlist berisi {length} lagu, tapi hanya {len(tracks)} yang "
                f"bisa dibaca — sebagian item mungkin private, tidak tersedia "
                f"di region ini, atau playlist-nya masih dimuat sebagian oleh "
                f"Spotify.")
    return title, tracks, hint, cover, (embed_owner or owner), total_ms


def _cap_hint(shown: int, cap: int) -> str:
    """Honest message when we only have the embed page's first N songs."""
    return (f"Hanya {shown} lagu yang terbaca (batas {cap} dari halaman embed "
            f"publik Spotify). Sisanya tidak bisa dibaca tanpa login — pakai "
            f"panel \"Hubungkan Spotify\" di bawah untuk daftar lengkap.")


def embed_tracks_detailed(url: str, max_items: int = 0) -> tuple:
    """Same as :func:`embed_tracks` but also returns owner and total duration.

    Returns ``(title, tracks, hint, cover_url, owner, total_duration_ms)``.

    The embed page carries these already (verified): the owner name sits in
    ``entity["subtitle"]`` and the total duration is the sum of the per-track
    ``duration`` values in milliseconds.
    """
    from .spotify_meta import parse_spotify_url

    kind, sid = parse_spotify_url(url)
    html = _get(EMBED_BASE.format(kind=kind, sid=sid))
    entity = parse_embed_page(html)

    title = str(entity.get("name") or entity.get("title") or "Spotify")
    # For a playlist/album the subtitle is the owner's name; for a bare track it
    # is the artist. Either way it is the only such field on the page.
    owner = str(entity.get("subtitle") or "").strip()

    if kind == "track":
        tid = str(entity.get("id") or _track_id(str(entity.get("uri") or "")))
        if not tid:
            return title, [], "Halaman embed tidak memuat data lagu.", "", owner, 0
        artists = entity.get("artists") or []
        artist = ", ".join(
            str(a.get("name") or "") for a in artists if isinstance(a, dict)
        ).strip(" ,") or str(entity.get("subtitle") or "Unknown")
        cover = _playlist_cover(entity) or oembed_cover(kind, tid)
        dur = int(entity.get("duration") or 0)
        track = Track(
            data=tid, track_token=tid,
            title=str(entity.get("title") or entity.get("name") or "Unknown"),
            artist=artist,
            thumbnail=cover, mp3_url=None,
            duration_ms=dur,
            album=str(entity.get("title") or "") if kind == "album" else "",
        )
        return title, [track], "", cover, owner, dur

    cover = _playlist_cover(entity) or oembed_cover(kind, sid)
    tracks = tracks_from_entity(entity, cover_for=cover)
    if max_items:
        tracks = tracks[:max_items]

    total_ms = sum(int(t.duration_ms or 0) for t in tracks)

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
                f"playlist.")

    return title, tracks, hint, cover, owner, total_ms


# --------------------------------------------------------------------------
# per-track album cover art (anonymous embed + oEmbed, cached)
# The cache itself lives in spotify_spclient.py: it must hold metadata AND
# the artwork, and /embed/track returns no cover of its own.
# --------------------------------------------------------------------------

def fetch_album_covers(track_ids: List[str], workers: int = 8) -> Dict[str, str]:
    """Return ``{track_id: cover_url}``, using the disk cache where possible.

    WHICH ENDPOINT THIS USES (and why it matters)
    ----------------------------------------------
    This used to call ``GET /tracks/{id}`` on ``api.spotify.com``. That endpoint
    answers ``429 QUOTA_EXCEEDED`` almost continuously under any real load and
    did not recover after 30/60/120 s, so for playlists it is now forbidden.

    We use the anonymous chain instead: ``/embed/track/{id}`` for metadata and
    oEmbed for the artwork. Both were measured quota-free (20/20 requests OK),
    and the oEmbed image hash is identical to the Web API's.

    Returns ``{}`` if nothing can be resolved — the caller then keeps the
    playlist-level cover rather than showing a broken list.
    """
    ids = [str(t) for t in track_ids if t]
    if not ids:
        return {}

    from .spotify_spclient import cached_track_details

    try:
        details = cached_track_details(ids, workers=workers)
    except Exception:  # noqa: BLE001 - artwork is cosmetic, never break a load
        return {}

    covers: Dict[str, str] = {}
    for tid, info in details.items():
        url = str((info or {}).get("cover") or "")
        if url:
            covers[tid] = url
    return covers
