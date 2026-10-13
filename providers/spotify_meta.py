"""Spotify metadata client — reads playlist contents from the official Web API.

WHY THIS EXISTS
---------------
The YouTube-based provider needs a *list of songs* (title, artist, duration)
before it can search for audio. Spotify's official Web API is the reliable way
to get that list — no scraping, no HTML parsing, no Cloudflare.

AUTH
----
Client Credentials flow (app-only). That is enough for PUBLIC playlists and
needs no user login — just a Client ID + Client Secret from
https://developer.spotify.com/dashboard

Spotify requires the app owner to have a PREMIUM account (rule since Feb 2026).

REQUIRED ENV VARS
-----------------
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET

NOTES ON SPOTIFY'S 2026 API CHANGES
-----------------------------------
* ``/playlists/{id}/tracks`` was renamed to ``/playlists/{id}/items``.
  The response item key also moved from ``track`` to ``item``.
  We try ``/items`` first and fall back to ``/tracks`` for older accounts.
* Some third-party playlists may be restricted; we surface that clearly instead
  of returning an empty list.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from .base import ServiceError, Track

TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
API_BASE = "https://api.spotify.com/v1"
TIMEOUT = 20

# Scopes needed to read a user's playlists. Playlist CONTENTS stopped working
# with Client Credentials in Spotify's Feb 2026 change (401 "Valid user
# authentication required"), so a user access token is the only way past the
# 100-item cap that the public embed page imposes.
USER_SCOPES = "playlist-read-private playlist-read-collaborative"

# Spotify caps playlist item pages at 100.
PAGE_LIMIT = 100
# Safety valve: never walk more than this many pages (10k tracks).
MAX_PAGES = 100

# Cover lookups hit GET /tracks/{id} one at a time. Capped so we never look like
# a scraper hammering the API; 8 measured ~5x faster than serial for 100 tracks.
MAX_COVER_WORKERS = 8


# --------------------------------------------------------------------------
# .env loading (no external dependency)
# --------------------------------------------------------------------------
def _load_dotenv(start: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Deliberately dependency-free and non-destructive: existing environment
    variables always win, so a real env var can override the file.
    """
    here = (start or Path(__file__).resolve().parents[1]) / ".env"
    if not here.exists():
        return
    try:
        text = here.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def credentials() -> tuple[str, str]:
    """Return (client_id, client_secret), raising a friendly error if missing."""
    _load_dotenv()
    cid = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
    secret = (os.environ.get("SPOTIFY_CLIENT_SECRET") or "").strip()
    if not cid or not secret:
        raise ServiceError(
            "Spotify API credentials belum diisi. Bikin file '.env' di folder "
            "project (lihat '.env.example') lalu isi SPOTIFY_CLIENT_ID dan "
            "SPOTIFY_CLIENT_SECRET dari https://developer.spotify.com/dashboard",
            details=f"looked for SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in {Path(__file__).resolve().parents[1] / '.env'}",
        )
    return cid, secret


def has_credentials() -> bool:
    """True when Client Credentials are present. Never raises."""
    try:
        credentials()
        return True
    except ServiceError:
        return False


def refresh_token_present() -> bool:
    """True when SPOTIFY_REFRESH_TOKEN is set (enables playlists > 100 songs)."""
    _load_dotenv()
    return bool((os.environ.get("SPOTIFY_REFRESH_TOKEN") or "").strip())


def authorize_url(redirect_uri: str = "http://localhost:8501") -> str:
    """Build the Authorization Code URL the user opens once to get a token.

    OPTIONAL feature. Without SPOTIFY_REFRESH_TOKEN the app still works; it just
    falls back to the public embed page, which caps playlists at 100 songs.
    """
    cid, _ = credentials()
    params = {
        "client_id": cid,
        "response_type": "code",
        "scope": USER_SCOPES,
        "redirect_uri": redirect_uri,
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


# --------------------------------------------------------------------------
# URL parsing
# --------------------------------------------------------------------------
_ID_RE = re.compile(r"(?:playlist|album|track)/([A-Za-z0-9]+)")


def parse_spotify_url(url: str) -> tuple[str, str]:
    """Return (kind, id) for a Spotify URL.

    kind is one of: playlist, album, track.
    Accepts open.spotify.com links, spotify: URIs, and bare IDs.
    """
    raw = (url or "").strip()
    if not raw:
        raise ServiceError("Tempel URL Spotify dulu.")

    # spotify:playlist:ID  (checked before the URL regex)
    if raw.startswith("spotify:"):
        parts = raw.split(":")
        if len(parts) >= 3:
            return parts[1], parts[2]

    # bare 22-char base62 ID -> assume playlist
    if re.fullmatch(r"[A-Za-z0-9]{22}", raw):
        return "playlist", raw

    m = _ID_RE.search(raw)
    if m:
        # find which keyword matched
        for kind in ("playlist", "album", "track"):
            if f"{kind}/{m.group(1)}" in raw:
                return kind, m.group(1)
        return "playlist", m.group(1)

    raise ServiceError(
        "URL Spotify tidak dikenali. Contoh yang didukung: "
        "https://open.spotify.com/playlist/XXXX atau spotify:playlist:XXXX",
        details=f"got: {raw[:120]}",
    )


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
def _request(url: str, headers: Dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        if exc.code == 401:
            raise ServiceError(
                "Spotify menolak kredensial (401). Cek SPOTIFY_CLIENT_ID dan "
                "SPOTIFY_CLIENT_SECRET di file .env.",
                details=detail,
            ) from exc
        if exc.code == 403:
            raise ServiceError(
                "Spotify menolak akses (403). Playlist ini mungkin private atau "
                "dibatasi. Coba playlist publik, atau playlist milik akun kamu "
                "sendiri.",
                details=detail,
            ) from exc
        if exc.code == 404:
            raise ServiceError(
                "Playlist/album tidak ditemukan di Spotify (404).",
                details=detail,
            ) from exc
        raise ServiceError(
            f"Spotify API error HTTP {exc.code}.", details=detail
        ) from exc
    except urllib.error.URLError as exc:
        raise ServiceError(
            "Tidak bisa menghubungi Spotify API. Cek koneksi internet.",
            details=str(exc),
        ) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ServiceError("Respons Spotify bukan JSON yang valid.",
                           details=body[:300]) from exc


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------
class SpotifyMeta:
    """Thin Spotify Web API client (client-credentials, read-only public data)."""

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None,
                 prefer: str = "embed", refresh_token: Optional[str] = None):
        # Explicit empty strings mean "no credentials" (the embed path needs
        # none). None means "load them from .env if available".
        if client_id is not None and client_secret is not None:
            self._cid, self._secret = client_id, client_secret
        else:
            try:
                self._cid, self._secret = credentials()
            except ServiceError:
                self._cid, self._secret = "", ""
        self._token: str = ""
        self._token_expiry: float = 0.0
        # "embed" (default, no auth) or "api" (Web API, needs credentials).
        self._prefer = prefer
        # Header extras recovered from the embed page (owner, total duration).
        self.last_owner: str = ""
        self.last_total_duration_ms: int = 0
        # The playlist's own artwork (prefix ab67706c…). Kept separate from the
        # per-track album covers (prefix ab67616d…) so the header never shows
        # someone else's album art.
        self.last_playlist_cover: str = ""
        # OPTIONAL user token. Only needed to read past the embed page's
        # 100-item cap; its absence must never break the normal flow.
        if refresh_token is None:
            _load_dotenv()
            refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN") or ""
        self._refresh_token = str(refresh_token or "").strip()
        self._user_access_token: str = ""
        self._user_token_expiry: float = 0.0

    def has_user_token(self) -> bool:
        """True when a refresh token is configured (playlist >100 supported)."""
        return bool(self._refresh_token)

    # ------------------------------------------------- user token (optional)
    def _user_access_token_value(self) -> str:
        """Exchange the refresh token for a short-lived user access token."""
        if self._user_access_token and time.time() < self._user_token_expiry - 30:
            return self._user_access_token
        if not self._refresh_token:
            raise ServiceError(
                "SPOTIFY_REFRESH_TOKEN belum diisi. Playlist publik tetap "
                "bisa dibaca tanpa token; token hanya diperlukan untuk playlist "
                "private.",
                details="no refresh token configured",
            )
        cid, secret = self._cid, self._secret
        if not (cid and secret):
            cid, secret = credentials()
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }).encode()
        req = urllib.request.Request(
            TOKEN_URL, data=data,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise ServiceError(
                "Spotify menolak refresh token. Ambil token baru lewat "
                "Authorization Code (lihat README bagian 'Hubungkan Spotify').",
                details=f"HTTP {exc.code}: {detail}",
            ) from exc
        except urllib.error.URLError as exc:
            raise ServiceError("Tidak bisa menghubungi Spotify (token endpoint).",
                               details=str(exc)) from exc

        token = str(payload.get("access_token") or "")
        if not token:
            raise ServiceError("Spotify tidak mengirim access_token.",
                               details=json.dumps(payload)[:300])
        self._user_access_token = token
        self._user_token_expiry = time.time() + int(payload.get("expires_in") or 3600)
        return token

    def _get_user(self, path: str, params: Optional[dict] = None) -> dict:
        """GET with a USER access token (required for /playlists/{id}/items)."""
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return _request(url, {"Authorization": f"Bearer {self._user_access_token_value()}"})

    # ---------------------------------------------------------------- auth
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token

        basic = base64.b64encode(f"{self._cid}:{self._secret}".encode()).decode()
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise ServiceError(
                "Gagal ambil token Spotify. Cek Client ID / Client Secret di .env "
                "(dan pastikan akun pemilik app-nya Premium).",
                details=f"HTTP {exc.code}: {detail}",
            ) from exc
        except urllib.error.URLError as exc:
            raise ServiceError("Tidak bisa menghubungi Spotify (token endpoint).",
                               details=str(exc)) from exc

        self._token = str(payload.get("access_token") or "")
        if not self._token:
            raise ServiceError("Spotify tidak mengirim access_token.",
                               details=json.dumps(payload)[:300])
        self._token_expiry = time.time() + int(payload.get("expires_in") or 3600)
        return self._token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return _request(url, {"Authorization": f"Bearer {self._access_token()}"})

    # ------------------------------------------------------------ parsing
    @staticmethod
    def _track_from_item(item: dict) -> Optional[Track]:
        """Map one playlist item onto a Track. Returns None for unusable rows."""
        node = item.get("item") or item.get("track") or {}
        if not isinstance(node, dict):
            return None
        # Local files / unavailable episodes have no id or are not tracks
        if not node.get("id") or node.get("type") not in (None, "track"):
            return None

        artists = [a.get("name", "") for a in (node.get("artists") or [])
                   if isinstance(a, dict)]
        album = node.get("album") if isinstance(node.get("album"), dict) else {}
        images = album.get("images") or []
        cover = ""
        if images and isinstance(images[0], dict):
            cover = str(images[0].get("url") or "")

        return Track(
            data=str(node.get("id")),
            track_token=str(node.get("id")),
            title=str(node.get("name") or "Unknown"),
            artist=", ".join(a for a in artists if a) or "Unknown",
            thumbnail=cover,
            mp3_url=None,                      # resolved later via YouTube
            duration_ms=int(node.get("duration_ms") or 0),
            album=str(album.get("name") or ""),
        )

    # --------------------------------------------------------- public API
    def playlist_tracks(self, url: str, max_items: int = 0,
                        progress=None) -> tuple[str, List[Track], str]:
        """Return (title, tracks, hint) for a playlist / album / track URL.

        Strategy: try the anonymous embed + spclient chain FIRST (public
        playlists, no login, no size cap), then fall back to the Web API, and
        finally to a user token for private playlists.

        ``progress(done, total)`` is forwarded to the per-track metadata fetch.
        ``max_items`` > 0 stops early (useful for testing).
        """
        if self._prefer != "api":
            # ORDER MATTERS (do not reverse):
            # 1. a user refresh token exists -> Web API with a USER token.
            #    Now only needed for PRIVATE playlists; public ones don't
            #    need a login at all any more.
            # 2. otherwise -> the anonymous embed + spclient chain, which
            #    reads every song of a PUBLIC playlist with no 100 cap.
            anonymous_error: Optional[ServiceError] = None
            if self._refresh_token:
                try:
                    return self._playlist_tracks_user(url, max_items)
                except ServiceError:
                    pass  # bad/expired token -> fall back to the anonymous path

            try:
                from .spotify_embed import embed_tracks_complete

                title, tracks, hint, cover, owner, total_ms = embed_tracks_complete(
                    url, max_items=max_items, progress=progress)
                if tracks:
                    # Remember the header extras the UI wants, so it does not
                    # have to fetch the same embed page a second time.
                    self.last_owner = owner
                    self.last_total_duration_ms = total_ms
                    # The playlist's OWN artwork. Without this the header falls
                    # back to the first track's album cover, which is someone
                    # else's image — the user uploaded a playlist cover and
                    # expects to see it.
                    self.last_playlist_cover = cover
                    return title, tracks, hint
            except ServiceError as exc:
                # The anonymous path is the ONLY one that reads public playlists
                # (Client Credentials cannot). So if it fails, do NOT silently
                # fall through to the app-only Web API: that answers 403 for every
                # playlist and would report "playlist private" for what is really
                # a rate limit or a markup change.
                anonymous_error = exc

        if not self._cid or not self._secret:
            if anonymous_error is not None:
                # Report what actually went wrong rather than guessing.
                raise anonymous_error
            raise ServiceError(
                "Tidak bisa membaca playlist itu. Halaman embed publik Spotify "
                "tidak tersedia (playlist private atau blokir wilayah), dan "
                "credential Web API belum diisi. Isi SPOTIFY_CLIENT_ID / "
                "SPOTIFY_CLIENT_SECRET di .env.",
                details=f"embed failed and no API credentials configured (prefer={self._prefer})",
            )

        # We have app-only credentials, but those cannot read playlist contents
        # (403 since Feb 2026). Trying anyway turns a rate limit into a
        # misleading "playlist private" message, so only fall back when the
        # anonymous path failed for a reason the API might actually handle.
        if anonymous_error is not None:
            # The status code lives in the user message for some call sites and
            # in details for others; check both.
            blob = f"{anonymous_error.user_message} {anonymous_error.details or ''}"
            rate_limited = "429" in blob or "membatasi" in blob
            if not rate_limited:
                return self._playlist_tracks_api(url, max_items)
            raise ServiceError(
                "Spotify sedang membatasi permintaan dari koneksi ini (HTTP 429). "
                "Itu bukan playlist private — tunggu beberapa menit lalu Load "
                "Playlist lagi. Playlist yang sudah pernah dimuat tetap bisa "
                "dilihat dari cache.",
                details=anonymous_error.details or "",
            )
        return self._playlist_tracks_api(url, max_items)

    def _playlist_tracks_user(self, url: str, max_items: int = 0) -> tuple[str, List[Track], str]:
        """Read a playlist with a USER access token — no 100-item cap.

        ``GET /playlists/{id}/items`` only accepts a user token since Spotify's
        February 2026 change. Paging continues until Spotify stops returning
        items, so playlists longer than 100 songs load in full.
        """
        kind, sid = parse_spotify_url(url)
        if kind == "track":
            data = self._get_user(f"/tracks/{sid}")
            t = self._track_from_item({"item": data})
            return (str(data.get("name") or "Track"), [t] if t else [], "")

        meta = self._get_user(f"/playlists/{sid}")
        title = str(meta.get("name") or "Playlist")
        total = int((meta.get("tracks") or meta.get("items") or {}).get("total") or 0)

        tracks: List[Track] = []
        hint = ""
        offset = 0
        pages = 0
        while pages < MAX_PAGES:
            page = self._get_user(f"/playlists/{sid}/items",
                                  {"limit": PAGE_LIMIT, "offset": offset})
            pages += 1
            items = page.get("items") or []
            if not items:
                break
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = self._track_from_item(it)
                if t:
                    tracks.append(t)
                if max_items and len(tracks) >= max_items:
                    break
            if max_items and len(tracks) >= max_items:
                break
            if len(items) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT

        self.last_owner = str((meta.get("owner") or {}).get("display_name") or "")
        self.last_total_duration_ms = sum(int(t.duration_ms or 0) for t in tracks)
        # Playlist artwork from the user-token response, when there is one.
        # Deliberately NOT passed through upgrade_cover_url(): playlist images
        # use the ab67706c… prefix and 404 at the large album prefix.
        images = meta.get("images") or []
        if images and isinstance(images[0], dict):
            self.last_playlist_cover = str(images[0].get("url") or "")
        if total and len(tracks) < total:
            hint = (f"Spotify melaporkan {total} lagu, tapi {len(tracks)} yang "
                    f"berhasil dibaca.")
        return title, tracks, hint

    def _playlist_tracks_api(self, url: str, max_items: int = 0) -> tuple[str, List[Track], str]:
        """Web API implementation (original path)."""
        kind, sid = parse_spotify_url(url)

        if kind == "track":
            data = self._get(f"/tracks/{sid}")
            t = self._track_from_item({"item": data})
            return (str(data.get("name") or "Track"), [t] if t else [], "")

        if kind == "album":
            data = self._get(f"/albums/{sid}")
            tracks: List[Track] = []
            for node in (data.get("tracks") or {}).get("items") or []:
                if not isinstance(node, dict):
                    continue
                node = dict(node)
                # album track objects carry the album's images on the parent
                node.setdefault("album", {"images": data.get("images") or [],
                                          "name": data.get("name") or ""})
                t = self._track_from_item({"item": node})
                if t:
                    tracks.append(t)
                if max_items and len(tracks) >= max_items:
                    break
            return (str(data.get("name") or "Album"), tracks, "")

        # ---- playlist ----
        title = "Playlist"
        tracks: List[Track] = []
        hint = ""

        # metadata first (name + track count)
        meta = self._get(f"/playlists/{sid}")
        title = str(meta.get("name") or "Playlist")
        total = int((meta.get("tracks") or meta.get("items") or {}).get("total") or 0)

        # Spotify renamed /tracks -> /items in 2026. Try the new one first.
        offset = 0
        pages = 0
        last_error: Optional[ServiceError] = None
        for path in (f"/playlists/{sid}/items", f"/playlists/{sid}/tracks"):
            tracks = []
            offset = 0
            pages = 0
            ok = True
            while pages < MAX_PAGES:
                try:
                    page = self._get(path, {"limit": PAGE_LIMIT, "offset": offset})
                except ServiceError as exc:
                    last_error = exc
                    ok = False
                    break
                pages += 1
                items = page.get("items") or []
                if not items:
                    break
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    t = self._track_from_item(it)
                    if t:
                        tracks.append(t)
                    if max_items and len(tracks) >= max_items:
                        break
                if max_items and len(tracks) >= max_items:
                    break
                if len(items) < PAGE_LIMIT:
                    break
                offset += PAGE_LIMIT
            if ok:
                break

        if not tracks and last_error is not None:
            raise last_error

        if total and len(tracks) < total:
            hint = (f"Spotify melaporkan {total} lagu, tapi {len(tracks)} yang "
                    f"berhasil dibaca. Sebagian item mungkin lokal, tidak "
                    f"tersedia di region ini, atau dibatasi.")
        return (title, tracks, hint)

    # ------------------------------------------------------- album cover art
    def track_covers(self, track_ids: List[str], workers: int = 8) -> Dict[str, str]:
        """Return ``{track_id: album_cover_url}`` via ``GET /tracks/{id}``.

        WHY THIS EXISTS
        ---------------
        Spotify's public embed page only carries ONE image for the whole
        playlist, so every track would end up with the same cover. The real
        per-album artwork is only available from the Web API, one track per
        request: ``GET /tracks?ids=a,b,c`` is rejected (403), so batching is not
        an option.

        Measured cost (2026-10-09, 20 requests): ~243 ms each serially, ~0.9 s
        for 20 with 8 workers. So 100 tracks is roughly 5 s parallel / 24 s
        serial — acceptable for a one-off load, hence the worker pool.

        Behaviour: individual failures (deleted track, region lock, network) are
        SKIPPED, never raised, so the caller can fall back to the playlist cover.
        """
        ids = [str(t) for t in track_ids if t]
        if not ids:
            return {}

        # Never hammer Spotify: cap the pool at 8.
        workers = max(1, min(int(workers), MAX_COVER_WORKERS))

        found: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._one_cover, tid): tid for tid in ids}
            for fut in as_completed(futures):
                tid = futures[fut]
                try:
                    url = fut.result()
                except Exception:  # noqa: BLE001 - a single bad track must not
                    url = ""       # abort the whole batch
                if url:
                    found[tid] = url
        return found

    def _one_cover(self, track_id: str) -> str:
        """Fetch one track's album cover URL. Returns '' on any failure."""
        try:
            data = self._get(f"/tracks/{track_id}")
        except ServiceError:
            return ""
        except Exception:  # noqa: BLE001
            return ""
        album = data.get("album") if isinstance(data.get("album"), dict) else {}
        images = album.get("images") or []
        # images[] is sorted largest-first; take the biggest that exists.
        for img in images:
            if isinstance(img, dict) and img.get("url"):
                return str(img["url"])
        return ""
