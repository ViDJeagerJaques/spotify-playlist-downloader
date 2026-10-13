"""Read a whole Spotify playlist — past the 100-song cap — with NO login.

WHY THIS FILE EXISTS
-------------------
Spotify's public embed page (``open.spotify.com/embed/playlist/{id}``) shows
only the **first 100 tracks**. Everything else needed a user login, which we
wanted to avoid. It turns out the same page also hands out an **anonymous access
token**, and that token unlocks an internal endpoint with the *complete* list:

    embed playlist page  ->  anon token + first 100 tracks + owner + cover
    spclient (anon token) ->  ALL track ids, in playlist order  (213/213 verified)
    /embed/track/{id}      ->  title / artists / duration for the missing ones
    oEmbed                ->  album cover for those tracks

Verified 2026-10-09 on a 213-song playlist: ``length: 213``, ``items: 213``,
``truncated: false``.

RATE LIMITS — read before touching anything here
------------------------------------------------
``api.spotify.com`` is the wrong tool for this job. During development it
answered ``429 QUOTA_EXCEEDED`` continuously and did not recover after 30/60/120
seconds. The endpoints in this module were measured as quota-free:

    endpoint                                    measured
    open.spotify.com/embed/playlist/{id}        ok, one per load
    spclient.wg.spotify.com/playlist/v2/...     ok, one per load
    open.spotify.com/embed/track/{id}           ok, 20/20, ~312 ms each
    open.spotify.com/oembed                    ok

So playlists MUST be read through here, never through ``api.spotify.com``.

DEPENDENCY RISK (state this honestly)
-------------------------------------
``spclient.wg.spotify.com`` is an **internal** Spotify endpoint, not a public
API. It can change or disappear without notice, and there is no versioning
promise. Everything degrades gracefully: if it fails we keep the 100 songs the
embed page gave us and say so, rather than breaking the app.

LEGAL / SCOPE
-------------
This reads only **public** playlists — the same set Spotify publishes on its own
embed page. The anonymous token belongs to no account; private playlists still
need a real user login (``spotify_meta.py`` keeps that path). Nothing here
bypasses access control.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import ServiceError, cache_dir, upgrade_cover_url

SPCLIENT_BASE = "https://spclient.wg.spotify.com/playlist/v2/playlist"
SPCLIENT_META = "https://spclient.wg.spotify.com/metadata/4/track/{gid}"
OEMBED_TRACK = ("https://open.spotify.com/oembed?url="
                + "https://open.spotify.com/track/{tid}&format=json")

TIMEOUT = 40

# Never hammer these endpoints. 8 was measured as plenty fast (20 requests in
# ~6 s) and still polite.
MAX_WORKERS = 8
# Minimum pause between two requests ISSUED BY THE SAME WORKER.
REQUEST_GAP = 0.15
# Global ceiling across all workers, in requests per second. The per-worker gap
# alone would let 8 workers reach 8/0.15 = 53 req/s together, which is more
# than we want to send at Spotify, so a token bucket caps the total rate.
MAX_REQ_PER_SEC = 20.0

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# The anon token lives in the embed page's inline JSON. Measured length: 140.
_ANON_TOKEN_RES = [
    re.compile(r'accessToken["\']?\s*[:=]\s*["\']([^"\']{20,})["\']'),
    re.compile(r'"accessToken"\s*:\s*"([^"]{20,})"'),
]

class _TokenBucket:
    """Caps the TOTAL request rate without serialising callers.

    A single global lock + sleep made the 8 workers take turns, so
    "parallel" was really serial: 213 requests x REQUEST_GAP = 32 s, which
    matched the measured 32.9 s exactly.

    A token bucket fixes that because it only gates WHEN a request STARTS;
    the network calls themselves still overlap. ``Condition.wait`` releases
    the lock, so other workers keep flowing while one sleeps.
    """

    def __init__(self, rate_per_sec: float):
        self._rate = float(rate_per_sec)
        self._capacity = max(1.0, float(rate_per_sec))
        self._tokens = self._capacity      # start with a full burst budget
        self._updated = time.monotonic()
        self._cond = threading.Condition(threading.Lock())

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._cond:
                now = time.monotonic()
                self._tokens = min(self._capacity,
                                   self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                # Wait inside the lock but wake early: another thread may
                # have refilled the bucket in the meantime.
                self._cond.wait(timeout=max(0.001, min(0.25, deficit / self._rate)))


_rate_limiter = _TokenBucket(MAX_REQ_PER_SEC)
_thread_state = threading.local()

# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _throttle() -> None:
    """Pause just enough to stay polite, WITHOUT serialising the workers."""
    # 1. per-worker gap: this thread's own consecutive requests are spaced
    now = time.monotonic()
    last = getattr(_thread_state, "last_request", 0.0)
    if last and (now - last) < REQUEST_GAP:
        time.sleep(REQUEST_GAP - (now - last))
    _thread_state.last_request = time.monotonic()

    # 2. global bucket: all workers together stay under MAX_REQ_PER_SEC.
    #    This gates start times only, so the requests still overlap.
    _rate_limiter.acquire()


def _get(url: str, headers: Optional[dict] = None) -> str:
    hdrs = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        hdrs.update(headers)
    _throttle()
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ServiceError(
            f"Spotify menjawab HTTP {exc.code} untuk {url.split('?')[0]}.",
            details=f"url={url[:160]}",
        ) from exc
    except urllib.error.URLError as exc:
        raise ServiceError("Tidak bisa menghubungi Spotify.", details=str(exc)) from exc


def _get_json(url: str, headers: Optional[dict] = None) -> dict:
    body = _get(url, headers)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ServiceError("Respons Spotify bukan JSON yang valid.",
                           details=f"{exc}\n{body[:200]}") from exc


# --------------------------------------------------------------------------
# A + B — the anonymous token and the full track list
# --------------------------------------------------------------------------
def extract_anon_token(html: str) -> str:
    """Pull the anonymous access token out of an embed playlist page.

    Returns '' when the page no longer carries one — the caller then keeps the
    100 songs from the embed and reports the truncation.
    """
    for pattern in _ANON_TOKEN_RES:
        m = pattern.search(html or "")
        if m:
            return m.group(1)
    return ""


def playlist_track_ids(playlist_id: str, anon_token: str) -> Tuple[List[str], int, str, bool]:
    """Return ``(track_ids, length, owner_username, truncated)`` via spclient.

    * ``track_ids`` — every track id, **in playlist order** (from
      ``contents.items``). spclient gives URIs only; metadata comes later.
    * ``length`` — the service's own song count, which can exceed what we get.
    * ``owner_username`` — the real username, more reliable than the embed's
      ``subtitle``.
    * ``truncated`` — the service's own flag; ``True`` means the list is partial.

    Never raises for a partial answer: if the payload is odd we return what we
    have. Only a hard failure raises ServiceError, and the caller falls back to
    the embed page.
    """
    if not anon_token:
        raise ServiceError("Token anonim tidak tersedia untuk playlist ini.")
    if not playlist_id:
        raise ServiceError("ID playlist kosong.")

    url = f"{SPCLIENT_BASE}/{playlist_id}"
    headers = {
        "Authorization": f"Bearer {anon_token}",
        "Accept": "application/json",
        "app-platform": "WebPlayer",
        "Origin": "https://open.spotify.com",
        "Referer": "https://open.spotify.com/",
    }
    data = _get_json(url, headers)

    # Internal endpoint: be defensive. A shape change must surface as a clear
    # error we can fall back from, never as an AttributeError three frames deep.
    if not isinstance(data, dict):
        raise ServiceError(
            "Respons spclient Spotify tidak seperti yang diharapkan.",
            details=f"top-level type: {type(data).__name__}",
        )

    ids: List[str] = []
    contents = data.get("contents")
    if not isinstance(contents, dict):
        contents = {}
    for item in contents.get("items") or []:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        if uri.startswith("spotify:track:"):
            ids.append(uri.split(":")[-1])
        elif uri:
            # episodes and anything else are not something we can resolve
            continue

    try:
        length = int(data.get("length") or 0)
    except (TypeError, ValueError):
        length = 0
    if not length:
        length = len(ids)

    owner = str(data.get("ownerUsername") or "")
    truncated = bool(contents.get("truncated"))
    return ids, length, owner, truncated


# --------------------------------------------------------------------------
# album / label / year / track number — the ID3 data (R4)
# --------------------------------------------------------------------------
# Spotify ids handed to us by the embed page are base62 of a 128-bit GID. This
# metadata endpoint wants that GID in HEX, so the conversion is required.
B62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Re-exported so callers only need to import from one module.
__all__ = ["upgrade_cover_url", "COVER_SMALL_PREFIX", "COVER_LARGE_PREFIX",
           "track_cover_oembed", "track_meta_embed", "playlist_track_ids",
           "b62_to_hex", "extract_anon_token"]


def b62_to_hex(spotify_id: str) -> str:
    """Convert a base62 Spotify id to its 32-character hex GID.

    Verified: ``2mdEsXPu8ZmkHRRtAdC09e`` -> ``4d7d424d2bc148da9d17580f110bd31c``.
    """
    n = 0
    for ch in spotify_id or "":
        idx = B62_ALPHABET.find(ch)
        if idx < 0:
            return ""            # not a base62 id -> caller skips the lookup
        n = n * 62 + idx
    return f"{n:032x}"


def _cover_from_album(album: dict) -> str:
    """Build the artwork URL from the metadata payload's ``cover_group``.

    This is why album metadata is the right primary source: it already carries
    the artwork, so a cold playlist load needs ONE request per song instead of
    three (embed track + oEmbed + metadata).
    """
    if not isinstance(album, dict):
        return ""
    group = album.get("cover_group")
    if not isinstance(group, dict):
        return ""
    images = group.get("image")
    if not isinstance(images, list) or not images:
        return ""
    # Prefer a large variant when the service offers several sizes.
    chosen = ""
    for entry in images:
        if not isinstance(entry, dict):
            continue
        file_id = str(entry.get("file_id") or "")
        if not file_id:
            continue
        width = int(entry.get("width") or 0)
        if not chosen or width > int((images[0] or {}).get("width") or 0):
            chosen = file_id
    if not chosen:
        return ""
    return upgrade_cover_url(f"https://i.scdn.co/image/{chosen}")


def track_metadata_spclient(track_id: str, anon_token: str) -> dict:
    """Album, label, year, track number AND cover art for one track. ``{}`` on failure.

    This is the richest quota-free source we have — richer than /embed/track
    (no album) and than oEmbed (no album either). One call replaces three, which
    is what keeps a cold 213-song load near 214 requests instead of ~640.
    """
    gid = b62_to_hex(track_id)
    if not gid or not anon_token:
        return {}
    headers = {
        "Authorization": f"Bearer {anon_token}",
        "Accept": "application/json",
        "app-platform": "WebPlayer",
        "Origin": "https://open.spotify.com",
        "Referer": "https://open.spotify.com/",
    }
    try:
        data = _get_json(SPCLIENT_META.format(gid=gid), headers)
    except ServiceError:
        return {}
    if not isinstance(data, dict):
        return {}

    album = data.get("album") if isinstance(data.get("album"), dict) else {}
    date = album.get("date") if isinstance(album.get("date"), dict) else {}
    artists = []
    for a in data.get("artist") or []:
        if isinstance(a, dict) and a.get("name"):
            artists.append(str(a["name"]))

    try:
        year = int(date.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    try:
        number = int(data.get("number") or 0)
    except (TypeError, ValueError):
        number = 0
    try:
        disc = int(data.get("disc_number") or 0)
    except (TypeError, ValueError):
        disc = 0

    return {
        "title": str(data.get("name") or ""),
        "artists": artists,
        "album": str(album.get("name") or ""),
        "label": str(album.get("label") or ""),
        "year": year,
        "track_number": number,
        "disc_number": disc,
        "duration_ms": int(data.get("duration") or 0) or 0,
        "cover": _cover_from_album(album),
    }


def metadata_many(track_ids: List[str], anon_token: str,
                  workers: int = MAX_WORKERS) -> Dict[str, dict]:
    """Parallel :func:`track_metadata_spclient` for many tracks."""
    ids = [t for t in dict.fromkeys(track_ids) if t]
    if not ids or not anon_token:
        return {}
    workers = max(1, min(int(workers), MAX_WORKERS))
    out: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(track_metadata_spclient, tid, anon_token): tid
                   for tid in ids}
        for fut in as_completed(futures):
            tid = futures[fut]
            try:
                info = fut.result()
            except Exception:  # noqa: BLE001
                info = {}
            if info:
                out[tid] = info
    return out


def cached_metadata_many(track_ids: List[str], anon_token: str,
                         workers: int = MAX_WORKERS) -> Dict[str, dict]:
    """:func:`metadata_many` with a disk cache — only uncached ids are fetched.

    Without this, album / label / year cost one request per song on EVERY load:
    a 213-song playlist kept issuing 214 requests even when nothing had changed.
    The cache stores the RESULT, not the token, so a rotated anonymous token is
    irrelevant — we only re-fetch for tracks we have never seen.
    """
    ids = [t for t in dict.fromkeys(track_ids) if t]
    if not ids:
        return {}
    cache = load_cache("meta")
    missing = [t for t in ids if t not in cache]
    if missing and anon_token:
        fresh = metadata_many(missing, anon_token, workers=workers)
        if fresh:
            cache.update(fresh)
            save_cache("meta", cache)
    return {t: cache[t] for t in ids if t in cache}
# --------------------------------------------------------------------------
# C — per-track metadata and cover (no api.spotify.com!)
# --------------------------------------------------------------------------
def track_meta_embed(track_id: str) -> dict:
    """Metadata for one track from ``/embed/track/{id}`` — no auth.

    Returns ``{"title", "artists", "duration_ms", "release_date"}``, or ``{}``
    when the track cannot be read. Never raises.
    """
    if not track_id:
        return {}
    try:
        html = _get(f"https://open.spotify.com/embed/track/{track_id}")
    except ServiceError:
        return {}

    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                  html, re.S)
    if not m:
        return {}
    try:
        entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}

    artists = []
    for a in entity.get("artists") or []:
        if isinstance(a, dict) and a.get("name"):
            artists.append(str(a["name"]))
    if not artists and entity.get("subtitle"):
        artists = [str(entity["subtitle"])]

    release = entity.get("releaseDate")
    if isinstance(release, dict):
        release = release.get("isoString") or ""
    try:
        duration = int(entity.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0

    return {
        "title": str(entity.get("title") or entity.get("name") or ""),
        "artists": artists,
        "duration_ms": duration,
        "release_date": str(release or ""),
    }


def track_cover_oembed(track_id: str) -> str:
    """Album cover URL for one track, from oEmbed. Returns '' on failure.

    The URL is upgraded to the 640x640 variant before it is returned: oEmbed
    answers with the 300x300 prefix, and artwork at that size looks blurry when
    the user opens it large. Both prefixes carry the same hash.

    Verified: the image hash matches ``GET /tracks/{id}`` exactly, so this is the
    real album artwork and not a placeholder.
    """
    if not track_id:
        return ""
    try:
        data = _get_json(OEMBED_TRACK.format(tid=track_id))
    except ServiceError:
        return ""
    url = str(data.get("thumbnail_url") or "")
    return upgrade_cover_url(url) if url else ""


def track_details(track_ids: List[str], workers: int = MAX_WORKERS,
                  progress=None) -> Dict[str, dict]:
    """Fetch metadata + cover for many tracks in parallel.

    Returns ``{track_id: {"title", "artists", "duration_ms", "cover"}}``.
    One failure never kills the batch. ``progress(done, total)`` is optional.
    """
    ids = [t for t in dict.fromkeys(track_ids) if t]
    if not ids:
        return {}
    workers = max(1, min(int(workers), MAX_WORKERS))
    out: Dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one_track, tid): tid for tid in ids}
        for fut in as_completed(futures):
            tid = futures[fut]
            try:
                info = fut.result()
            except Exception:  # noqa: BLE001 - never let one track break all
                info = {}
            if info:
                out[tid] = info
            done += 1
            if progress:
                try:
                    progress(done, len(ids))
                except Exception:  # noqa: BLE001
                    pass
    return out


def _one_track(track_id: str) -> dict:
    """Metadata + cover for a single track. Cover is optional."""
    meta = track_meta_embed(track_id)
    if not meta:
        return {}
    meta["cover"] = track_cover_oembed(track_id)
    return meta

# --------------------------------------------------------------------------
# cache — so re-loading the same playlist costs nothing
# --------------------------------------------------------------------------
def _cache_path(name: str) -> Path:
    # Next to the project rather than the system temp folder — see base.cache_dir().
    return cache_dir() / f"spclient_{name}.json"


_cache_lock = threading.Lock()


def load_cache(name: str) -> Dict[str, dict]:
    """Read one of our JSON caches. A broken file is simply ignored."""
    try:
        path = _cache_path(name)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_cache(name: str, data: Dict[str, dict]) -> None:
    """Persist a cache, ignoring write failures."""
    try:
        with _cache_lock:
            path = _cache_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def cached_track_details(track_ids: List[str], workers: int = MAX_WORKERS,
                         progress=None) -> Dict[str, dict]:
    """``track_details`` with a disk cache: only uncached ids are fetched."""
    ids = [t for t in dict.fromkeys(track_ids) if t]
    cache = load_cache("tracks")
    missing = [t for t in ids if t not in cache]
    if missing:
        fresh = track_details(missing, workers=workers, progress=progress)
        if fresh:
            cache.update(fresh)
            save_cache("tracks", cache)
    return {t: cache[t] for t in ids if t in cache}