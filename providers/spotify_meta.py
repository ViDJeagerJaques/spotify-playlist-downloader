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
from pathlib import Path
from typing import Dict, List, Optional

from .base import ServiceError, Track

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
TIMEOUT = 20

# Spotify caps playlist item pages at 100.
PAGE_LIMIT = 100
# Safety valve: never walk more than this many pages (10k tracks).
MAX_PAGES = 100


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
                 prefer: str = "embed"):
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
    def playlist_tracks(self, url: str, max_items: int = 0) -> tuple[str, List[Track], str]:
        """Return (title, tracks, hint) for a playlist / album / track URL.

        Strategy: try the public embed page FIRST (no auth, works for public
        playlists), then fall back to the Web API (needs credentials, only helps
        for tracks/albums now that /playlists/{id}/items requires a user token).

        ``max_items`` > 0 stops early (useful for testing).
        """
        if self._prefer != "api":
            try:
                from .spotify_embed import embed_tracks

                title, tracks, hint, _cover = embed_tracks(url, max_items=max_items)
                if tracks:
                    return title, tracks, hint
            except ServiceError:
                # Markup changed / network hiccup -> try the Web API instead.
                pass

        if not self._cid or not self._secret:
            raise ServiceError(
                "Tidak bisa membaca playlist itu. Halaman embed publik Spotify "
                "tidak tersedia (playlist private atau blokir wilayah), dan "
                "credential Web API belum diisi. Isi SPOTIFY_CLIENT_ID / "
                "SPOTIFY_CLIENT_SECRET di .env, atau pakai backend SpotiDown.co "
                "di sidebar.",
                details=f"embed failed and no API credentials configured (prefer={self._prefer})",
            )
        return self._playlist_tracks_api(url, max_items)

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
