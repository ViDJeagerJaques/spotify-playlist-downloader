"""YouTube-backed provider — the DEPLOYABLE path.

WHY THIS EXISTS
---------------
The SpotiDown.co provider (``providers/spotidown_co.py``) needs a real, visible
Chrome window on the user's own desktop. That makes it useless for any hosted
deployment and awkward for non-technical users.

This provider takes the other route:

    Spotify Web API  ->  song list (title, artist, duration)
    yt-dlp           ->  find + download the matching audio from YouTube
    ffmpeg           ->  convert to MP3, embed metadata + cover art

No browser. No CAPTCHA. No third-party download service. Everything runs
server-side, so it works on a VPS / container / Streamlit Cloud.

WHAT YOU GIVE UP
----------------
The audio comes from YouTube, not from Spotify. Quality depends on how well the
match scores, and a mismatched upload can occasionally be the wrong version
(live take, remix, cover). We reduce that risk by scoring candidates on duration
proximity and preferring "official audio"/"topic" style uploads, but it is a
heuristic, not a guarantee.

REQUIREMENTS
------------
* ``yt-dlp`` (Python package) — in requirements.txt
* ``ffmpeg`` on PATH — needed for MP3 conversion and metadata embedding
* ``SPOTIFY_CLIENT_ID`` / ``SPOTIFY_CLIENT_SECRET`` in ``.env`` (see spotify_meta.py)

KNOWN TRAPS
-----------
1. **YouTube blocks datacenter IPs.** On a VPS or Streamlit Cloud you will get
   "Sign in to confirm you're not a bot" no matter what token tricks you use —
   the IP itself is flagged. Residential IPs (a normal home connection) work
   fine. If deploying, budget for a residential proxy.
2. **yt-dlp goes stale fast.** YouTube changes things often; an old yt-dlp fails
   silently on some videos. Upgrade regularly (`pip install -U yt-dlp`).
3. **Downloads are slow.** Each track is a search + a download + an ffmpeg pass.
   Expect several seconds per song; a 100-track playlist takes a while.
4. **Do not hammer it.** YouTube rate-limits aggressive clients. Keep the worker
   count low (2-3) and let the orchestrator's retry logic handle stragglers.

LEGAL
-----
Downloading audio from YouTube may violate YouTube's Terms of Service, and
downloading Spotify content may violate Spotify's. Personal use only — do not
redistribute or publish the results.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from .base import ProviderId, ResolveResult, ServiceError, Track
from .spotify_meta import SpotifyMeta

# Where yt-dlp should keep its scratch files. Cleaned per-run.
CACHE_DIR = Path(tempfile.gettempdir()) / "spotify_yt_cache"

# How many YouTube candidates to inspect when scoring a match.
SEARCH_CANDIDATES = 5

# Reject a candidate whose duration is further than this from the Spotify
# duration (seconds). Live/extended versions get filtered out this way.
MAX_DURATION_DRIFT_S = 25

# Score bonus for uploads that look like the official audio rather than a
# random reupload. Tuned by eyeballing real results, not by science.
_OFFICIAL_HINTS = ("official audio", "official video", "topic", "provided to youtube")
_PENALTY_HINTS = ("live", "cover", "remix", "sped up", "slowed", "nightcore", "reaction", "lyrics video hd")


def ffmpeg_path() -> Optional[str]:
    """Return the ffmpeg executable path, or None when it is not installed."""
    return shutil.which("ffmpeg")


def ensure_requirements() -> None:
    """Raise a friendly ServiceError when yt-dlp / ffmpeg are missing."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise ServiceError(
            "Paket 'yt-dlp' belum terpasang. Jalankan: pip install -r requirements.txt",
            details=f"import yt_dlp failed: {exc}",
        ) from exc
    if not ffmpeg_path():
        raise ServiceError(
            "ffmpeg tidak ditemukan di PATH. Provider YouTube butuh ffmpeg untuk "
            "konversi MP3. Windows: winget install Gyan.FFmpeg  |  "
            "macOS: brew install ffmpeg  |  Linux: sudo apt install ffmpeg",
            details="shutil.which('ffmpeg') returned None",
        )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def build_query(track: Track) -> str:
    """Search query for a track: '<artist> <title> official audio'."""
    artist = (track.artist or "").split(",")[0].strip()  # primary artist only
    title = (track.title or "").strip()
    return f"{artist} {title} official audio".strip()


def score_candidate(cand: dict, want_seconds: int) -> float:
    """Score a yt-dlp search entry against the track we want.

    Higher is better. Returns a negative number for candidates that should be
    rejected outright (duration far off).
    """
    dur = cand.get("duration") or 0
    if want_seconds and dur:
        drift = abs(float(dur) - want_seconds)
        if drift > MAX_DURATION_DRIFT_S:
            return -1.0
        score = 10.0 - (drift / max(1.0, MAX_DURATION_DRIFT_S)) * 5.0
    else:
        score = 5.0  # no duration to compare against -> neutral

    blob = _norm(f"{cand.get('title','')} {cand.get('uploader','')} {cand.get('channel','')}")
    if any(h in blob for h in _OFFICIAL_HINTS):
        score += 3.0
    if any(h in blob for h in _PENALTY_HINTS):
        score -= 4.0

    # Prefer results with a real view count (popular = more likely correct).
    views = cand.get("view_count") or 0
    if views > 1_000_000:
        score += 1.5
    elif views > 100_000:
        score += 0.8

    return score


class YouTubeClient:
    """Provider that resolves Spotify tracks to YouTube audio.

    Advertises ``prefetched_urls = False`` because the MP3 does not exist until
    we create it: ``resolve_track`` performs the search + download and returns a
    local file path, which the orchestrator's fetcher then copies into place.
    """

    prefetched_urls = False

    def __init__(self, timeout: int = 90, workers: int = 2):
        self.name = "YouTube (yt-dlp)"
        self.provider = ProviderId.YOUTUBE
        self._timeout = timeout
        self._workers = workers
        # Populated by resolve_track; the orchestrator asks for these so it can
        # copy a local file instead of issuing an HTTP GET.
        self._local_files: dict[str, str] = {}

    # ----------------------------------------------------------- listing
    def load_tracks(self, spotify_url: str, cftoken: str = "") -> ResolveResult:
        """Read the song list from Spotify. No browser, no CAPTCHA."""
        ensure_requirements()
        meta = SpotifyMeta()
        title, tracks, hint = meta.playlist_tracks(spotify_url)
        if not tracks:
            raise ServiceError(
                "Tidak ada lagu yang bisa dibaca dari link itu. Pastikan "
                "playlist-nya publik.",
                details=f"title={title!r}",
            )
        return ResolveResult(
            title=title,
            source_url=spotify_url,
            tracks=tracks,
            raw_hint=hint,
        )

    # ------------------------------------------------------------ resolve
    def resolve_track(self, track: Track, cftoken: str = "") -> str:
        """Search YouTube, download the best match, convert to MP3.

        Returns a ``file://`` style local path string. The orchestrator's
        fetcher recognises this and copies the file rather than downloading it.
        """
        ensure_requirements()
        want_s = int((track.duration_ms or 0) / 1000)
        query = build_query(track)

        dest = CACHE_DIR / f"{track.track_token or abs(hash(query))}.mp3"
        if dest.exists() and dest.stat().st_size > 0:
            self._local_files[str(dest)] = str(dest)
            return str(dest)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        best = self._pick_best(query, want_s)
        if best is None:
            raise ServiceError(
                f"Tidak ketemu audio YouTube yang cocok untuk "
                f"'{track.artist} - {track.title}'.",
                details=f"query={query!r}",
            )

        self._download(best, dest, track)
        self._local_files[str(dest)] = str(dest)
        return str(dest)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _pick_best(query: str, want_seconds: int) -> Optional[dict]:
        """Run a yt-dlp search and return the highest-scoring candidate."""
        import yt_dlp

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "socket_timeout": 20,
            "cachedir": str(CACHE_DIR / "ytdlp"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{SEARCH_CANDIDATES}:{query}",
                                        download=False)
        except Exception as exc:  # noqa: BLE001 - yt-dlp raises many types
            msg = str(exc)
            if "not a bot" in msg.lower() or "sign in" in msg.lower():
                raise ServiceError(
                    "YouTube memblokir permintaan (bot check). Ini biasanya "
                    "karena IP server/datacenter. Jalankan di koneksi rumah, "
                    "atau pakai proxy residential kalau di-deploy.",
                    details=msg[:400],
                ) from exc
            raise ServiceError(f"Pencarian YouTube gagal: {msg[:200]}",
                               details=msg[:400]) from exc

        entries = [e for e in (info or {}).get("entries") or [] if isinstance(e, dict)]
        if not entries:
            return None

        scored = [(score_candidate(e, want_seconds), e) for e in entries]
        scored = [(s, e) for s, e in scored if s > 0]
        if not scored:
            return None
        scored.sort(key=lambda p: p[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _download(cand: dict, dest: Path, track: Track) -> None:
        """Download the chosen candidate and convert it to a tagged MP3."""
        import yt_dlp

        vid = cand.get("id") or cand.get("url")
        if not vid:
            raise ServiceError("Kandidat YouTube tidak punya id.")

        tmp_tmpl = str(CACHE_DIR / f"{vid}.%(ext)s")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            "cachedir": str(CACHE_DIR / "ytdlp"),
            "format": "bestaudio/best",
            "outtmpl": tmp_tmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": "192"},
                {"key": "FFmpegMetadata"},
            ],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={vid}"])
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(
                f"Gagal mengunduh dari YouTube untuk '{track.title}'.",
                details=str(exc)[:400],
            ) from exc

        # yt-dlp writes <id>.mp3 after the FFmpeg postprocessor runs.
        produced = CACHE_DIR / f"{vid}.mp3"
        if not produced.exists():
            matches = sorted(CACHE_DIR.glob(f"{vid}*.mp3"))
            if not matches:
                raise ServiceError(
                    f"File MP3 tidak terbentuk untuk '{track.title}'.",
                    details=f"expected {produced}",
                )
            produced = matches[0]

        dest.parent.mkdir(parents=True, exist_ok=True)
        if produced != dest:
            shutil.move(str(produced), str(dest))

    # ------------------------------------------- orchestrator integration
    @staticmethod
    def is_local_path(url: str) -> bool:
        """True when a resolved 'URL' is actually a file already on disk."""
        return bool(url) and os.path.exists(url) and not url.startswith(("http://", "https://"))

    def cleanup_cache(self) -> None:
        """Remove scratch files. Safe to call after a batch finishes."""
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
