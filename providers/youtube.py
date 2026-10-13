"""YouTube-backed provider — the one and only download path.

WHY THIS EXISTS
---------------
Audio has to come from somewhere, and YouTube is the only source that needs no
account, no API key and no browser window — so the app runs unchanged on a
laptop or a VPS. It works like this:

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

import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .base import ProviderId, ResolveResult, ServiceError, Track, cache_dir
from .spotify_meta import SpotifyMeta

# Where downloaded MP3s, yt-dlp scratch files and the download metadata live.
# See providers.base.cache_dir() for why this is not the system temp folder.
CACHE_DIR = cache_dir()

# Zips and per-run scratch directories built by the batch paths also land here,
# so nothing this app writes ends up in the system temp folder.
SCRATCH_DIR = CACHE_DIR

# Stale zips older than this are removed when a new batch is packed. They are
# never needed after the browser has fetched them, and they otherwise pile up in
# the temp folder indefinitely.
STALE_ZIP_MAX_AGE_S = 24 * 60 * 60

# How many YouTube candidates to inspect when scoring a match.
SEARCH_CANDIDATES = 5

# How many candidates we are willing to fully extract just to read the verified
# badge. Each one is a real request, so this stays small on purpose.
VERIFY_PROBE_LIMIT = 3

# Reject a candidate whose duration is further than this from the Spotify
# duration (seconds). Live/extended versions get filtered out this way.
MAX_DURATION_DRIFT_S = 25

# Score bonus for uploads that look like the official audio rather than a
# random reupload. Tuned by eyeballing real results, not by science.
_OFFICIAL_HINTS = ("official audio", "official video", "topic", "provided to youtube")
_PENALTY_HINTS = ("live", "cover", "remix", "sped up", "slowed", "nightcore", "reaction", "lyrics video hd")

# Channels that upload translated lyrics on the artist's behalf. Several of them
# carry the verified badge, so they need an explicit penalty.
_LYRICS_CHANNEL_HINTS = (
    "lyrics", "lyric", "lirik", "terjemahan", "subs", "7clouds", "cloudy",
    "indolirik", "lost panda", "lagu", "dower", "video lyric",
)


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


def _norm_name(text: str) -> str:
    """Normalise a person/band name for channel matching.

    Separate from :func:`_norm` on purpose. ``_norm`` keeps only ``[a-z0-9]``,
    which is right for the ASCII hint lists but destroys any non-Latin name:
    "방탄소년단" would come out as an empty string and could never match a
    channel. Here we fold accents ("Beyoncé" -> "beyonce") and keep every
    unicode letter, so Korean, Japanese and Thai artists still compare.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w]+", " ", stripped.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned.replace("_", " ")).strip()


# Splits "Don Toliver, Doja Cat", "A feat. B", "Simon & Garfunkel" into the
# individual credited artists. A channel only ever carries one of them.
_ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|&|;|\bx\b|\bvs\.?\b|\bfeat\.?\b|\bft\.?\b|"
                              r"\bfeaturing\b|\band\b|\bwith\b)\s*", re.IGNORECASE)


def artist_name_variants(artist: str) -> list[str]:
    """Normalised forms of every artist credited on the track.

    Returns the whole name first, then each split part, so a track credited to a
    single act still matches a channel that appends "Official" or "- Topic".
    """
    whole = _norm_name(artist)
    parts = [whole] if whole else []
    for chunk in _ARTIST_SPLIT_RE.split(artist or ""):
        part = _norm_name(chunk)
        if part and part not in parts:
            parts.append(part)
    return parts


def channel_match_strength(channel: str, artist: str) -> float:
    """How strongly a channel name identifies this artist: 0.0, 0.5 or 1.0.

    Exact equality is the strongest evidence, then a name that contains the
    artist (or the other way round) so "Adele" still recognises "AdeleVEVO".
    Kept separate from :func:`channel_matches_artist` because an exact match
    should outrank a looser one: "Taylor Swift" beats the fan reupload channel
    "Taylor Swift Audios" even when the latter drifts less on duration.
    """
    chan = _norm_name(channel)
    if not chan:
        return 0.0
    for part in artist_name_variants(artist):
        if not part:
            continue
        if len(part) < 3 or len(chan) < 3:
            if part == chan:
                return 1.0
        elif part == chan:
            return 1.0
        elif part in chan or chan in part:
            return 0.5
    return 0.0


def channel_matches_artist(channel: str, artist: str) -> bool:
    """True when a YouTube channel looks like it belongs to this artist.

    This is the primary signal for picking the artist's own upload, and it is
    free: the channel name already comes back from the flat search, so no extra
    network request is involved.

    Matches when either name contains the other ("Joji" vs "JojiVEVO",
    "Reality Club" vs "REALITY CLUB"). Very short names are only compared for
    equality, otherwise a 1-2 character credit would substring-match half the
    catalogue.
    """
    return channel_match_strength(channel, artist) > 0.0


def is_lyrics_channel(channel: str) -> bool:
    """True for fan/lyrics-translation channels masquerading as the artist.

    Several of these carry the verified badge, so the badge on its own is not a
    usable signal — see the Indolirik / Lost Panda case in the module docs.
    """
    chan = _norm_name(channel)
    return any(h in chan for h in _LYRICS_CHANNEL_HINTS)


def _looks_like_artist_channel(cand: dict, artist: str) -> bool:
    if not artist:
        return False
    channel = cand.get("channel") or cand.get("uploader") or ""
    return bool(channel) and channel_matches_artist(channel, artist)


def _verified_cache_path() -> Path:
    return CACHE_DIR / "youtube_verified.json"


def sidecar_path(mp3: Path) -> Path:
    """``foo.mp3`` -> ``foo.json``: the record of which video produced it."""
    return mp3.with_suffix(".json")


def write_resolution(mp3: Path, cand: dict, track: Track,
                     want_seconds: int = 0) -> bool:
    """Record which YouTube video an MP3 came from, next to the MP3.

    Best-effort: if the write fails the download still counts as successful, we
    just lose the fast-path next time.
    """
    try:
        payload = {
            "video_id": cand.get("id") or "",
            "channel": cand.get("channel") or cand.get("uploader") or "",
            "title": cand.get("title") or "",
            "duration": cand.get("duration") or 0,
            "spotify_duration": want_seconds,
            "artist": track.artist or "",
            "track_title": track.title or "",
            "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        path = sidecar_path(mp3)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:  # noqa: BLE001
        return False


def read_resolution(mp3: Path) -> Optional[dict]:
    """The sidecar for this MP3, or ``None`` when it is missing/unreadable.

    ``None`` is what makes a cached file count as stale: without a record of the
    source video we cannot know whether it came from the artist's own channel.
    """
    path = sidecar_path(mp3)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def cache_usage() -> tuple[int, int]:
    """``(file_count, total_bytes)`` for everything this app keeps on disk."""
    if not CACHE_DIR.exists():
        return 0, 0
    count = 0
    total = 0
    for f in CACHE_DIR.rglob("*"):
        if f.is_file():
            count += 1
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return count, total


def clear_cache() -> tuple[int, int]:
    """Delete the cache directory. Only ever called from the sidebar button.

    Returns ``(files_removed, bytes_freed)``. Never called automatically.
    """
    files, total = cache_usage()
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return files, total


def purge_stale_zips(max_age_s: int = STALE_ZIP_MAX_AGE_S) -> int:
    """Remove batch ZIPs older than ``max_age_s``. Returns how many went.

    These are written per batch and never cleaned up by the request that created
    them, so they used to pile up in the system temp folder indefinitely. Called
    before packing a new one; a failure here must never break the download.
    """
    if not SCRATCH_DIR.exists():
        return 0
    cutoff = time.time() - max_age_s
    removed = 0
    for z in SCRATCH_DIR.glob("spl_*.zip"):
        try:
            if z.is_file() and z.stat().st_mtime < cutoff:
                z.unlink()
                removed += 1
        except OSError:
            continue
    return removed


_verified_lock = threading.Lock()

# Counts how many full extractions we have performed, so the cost of the
# official-channel preference stays measurable instead of a guess.
PROBE_STATS = {"requested": 0, "network": 0, "cached": 0}

# How many cached MP3s were found without a sidecar and therefore re-resolved.
# Surfaced in the UI so the effect of a scoring change is actually visible.
RESOLVE_STATS = {"cache_hit": 0, "cache_stale": 0}


def load_verified_cache() -> dict[str, bool]:
    """``video_id -> channel_is_verified``. A broken file is simply ignored."""
    try:
        path = _verified_cache_path()
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: bool(v) for k, v in data.items() if isinstance(v, bool)}
    except Exception:  # noqa: BLE001
        return {}


def save_verified_cache(data: dict[str, bool]) -> None:
    """Persist the badge cache, ignoring write failures."""
    try:
        with _verified_lock:
            path = _verified_cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def probe_verified(video_ids: list[str]) -> dict[str, bool]:
    """``video_id -> channel_is_verified``, fetching only what is not cached.

    A flat search never populates the badge, so this is the only way to read it.
    Results are memoised on disk: the same video showing up in two playlists, or
    in a batch that gets re-run, costs nothing the second time.
    """
    import yt_dlp

    ids = [i for i in dict.fromkeys(v for v in video_ids if v)]
    if not ids:
        return {}

    cache = load_verified_cache()
    missing = [i for i in ids if i not in cache]
    if missing:
        PROBE_STATS["requested"] += len(missing)
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 20,
            "cachedir": str(CACHE_DIR / "ytdlp"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                for vid in missing:
                    try:
                        info = ydl.extract_info(
                            f"https://www.youtube.com/watch?v={vid}",
                            download=False)
                    except Exception:  # noqa: BLE001 - one bad video must not
                        cache[vid] = False   # abort the whole fallback path
                        continue
                    PROBE_STATS["network"] += 1
                    if isinstance(info, dict):
                        cache[vid] = bool(info.get("channel_is_verified"))
        except Exception:  # noqa: BLE001 - verified is a nice-to-have
            pass
        save_verified_cache(cache)
    else:
        PROBE_STATS["cached"] += len(ids)

    return {i: cache[i] for i in ids if i in cache}



def build_query(track: Track) -> str:
    """Search query for a track: '<artist> <title> official audio'."""
    artist = (track.artist or "").split(",")[0].strip()  # primary artist only
    title = (track.title or "").strip()
    return f"{artist} {title} official audio".strip()


def score_candidate(cand: dict, want_seconds: int, artist: str = "") -> float:
    """Score a yt-dlp search entry against the track we want.

    Higher is better. Returns a negative number for candidates that should be
    rejected outright (duration far off).

    ``artist`` is the Spotify artist string. It is optional so existing callers
    and tests keep working, but :meth:`YouTubeClient._pick_best` always passes
    it: matching the channel against the artist name is what stops us from
    downloading "Glimpse of Us" off a random cover channel instead of Joji's own
    upload.
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

    # --- the artist's own channel: the strongest and cheapest signal we have.
    # The channel name already arrived with the flat search result, so this costs
    # nothing. An exact name match is worth more than a loose one so a fan
    # reupload channel ("Taylor Swift Audios") cannot outrank the real thing
    # purely on a smaller duration drift.
    channel = cand.get("channel") or cand.get("uploader") or ""
    strength = channel_match_strength(channel, artist)
    if strength >= 1.0:
        score += 6.0
    elif strength > 0.0:
        score += 4.5

    # --- verified badge: supporting evidence only. Indolirik and Lost Panda are
    # both verified lyric channels, so this can never outrank the name match.
    if cand.get("channel_is_verified"):
        score += 3.0

    # --- lyrics / translation uploads. Deliberately skipped when the channel is
    # the artist itself: real acts publish their own "official lyric video"
    # versions and those must stay on top.
    #
    # Two strengths. A channel *named* as a lyrics channel is strong evidence of
    # a rip, and has to outweigh the +3 verified badge plus a large view count,
    # otherwise Indolirik (verified, 30M views) still beats a bland upload. Only
    # the title mentioning lyrics is weak evidence — plenty of legitimate
    # uploads are titled "Official Lyric Video" — so it gets half the penalty.
    if channel and strength == 0.0:
        if is_lyrics_channel(channel):
            score -= 5.0
        elif is_lyrics_channel(cand.get("title", "")):
            score -= 3.0

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
        # Kept after load_tracks so the UI can read the playlist owner and total
        # duration without fetching the embed page a second time.
        self.last_owner: str = ""
        self.last_total_duration_ms: int = 0
        # The playlist's own artwork, so the Home header shows it instead of the
        # first track's album cover.
        self.last_playlist_cover: str = ""
        # Populated by resolve_track; the orchestrator asks for these so it can
        # copy a local file instead of issuing an HTTP GET.
        self._local_files: dict[str, str] = {}

    # ----------------------------------------------------------- listing
    def load_tracks(self, spotify_url: str, cftoken: str = "",
                    progress=None) -> ResolveResult:
        """Read the song list from Spotify. No browser, no CAPTCHA.

        ``progress(done, total)`` is forwarded to the metadata fetch, which
        makes one request per song — worth showing a bar for large playlists.
        """
        ensure_requirements()
        meta = SpotifyMeta()
        title, tracks, hint = meta.playlist_tracks(spotify_url, progress=progress)
        # Expose the header extras the embed page already gave us.
        self.last_owner = getattr(meta, "last_owner", "")
        self.last_total_duration_ms = getattr(meta, "last_total_duration_ms", 0)
        self.last_playlist_cover = getattr(meta, "last_playlist_cover", "")
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
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # A cached MP3 is only trusted when we also know which video produced
        # it. Without that record the file may predate the official-channel
        # matching and still be a fan upload, and improving the scoring would
        # have no visible effect for every track ever downloaded before. A MP3
        # with no sidecar is therefore treated as stale and re-resolved; it is
        # overwritten in place rather than deleted, and nothing is removed unless
        # the user asks for it via the sidebar button.
        if dest.exists() and dest.stat().st_size > 0:
            record = read_resolution(dest)
            if record is not None:
                RESOLVE_STATS["cache_hit"] += 1
                self._local_files[str(dest)] = str(dest)
                return str(dest)
            RESOLVE_STATS["cache_stale"] += 1

        best = self._pick_best(query, want_s, track.artist or "")
        if best is None:
            raise ServiceError(
                f"Tidak ketemu audio YouTube yang cocok untuk "
                f"'{track.artist} - {track.title}'.",
                details=f"query={query!r}",
            )

        self._download(best, dest, track)
        write_resolution(dest, best, track, want_s)
        self._local_files[str(dest)] = str(dest)
        return str(dest)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _pick_best(query: str, want_seconds: int,
                   artist: str = "") -> Optional[dict]:
        """Run a yt-dlp search and return the highest-scoring candidate.

        Two-stage so the official-channel preference stays cheap:

        1. Flat search (one request) gives title, channel and duration for the
           candidates, which is already enough to recognise the artist's own
           channel in the large majority of tracks.
        2. Only if nothing matched the artist name do we spend extra requests
           reading ``channel_is_verified`` on the top few candidates, and only
           for those the disk cache does not already know about.

        Extracting every candidate in full instead would cost ~0.5s each, i.e.
        ~2.5s per track and roughly nine extra minutes on a 213-track playlist.
        """
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

        scored = [(score_candidate(e, want_seconds, artist), e) for e in entries]
        scored = [(s, e) for s, e in scored if s > 0]
        if not scored:
            return None
        scored.sort(key=lambda p: p[0], reverse=True)

        # Stage 2. If the leader is already the artist's own channel we are done
        # and never touch the network again.
        if not _looks_like_artist_channel(scored[0][1], artist):
            YouTubeClient._apply_verified_badges(scored, want_seconds, artist)
            scored.sort(key=lambda p: p[0], reverse=True)

        return scored[0][1]

    @staticmethod
    def _apply_verified_badges(scored: list, want_seconds: int,
                               artist: str) -> None:
        """Fill in ``channel_is_verified`` for the top candidates and rescore.

        Only reached when the flat results had no artist-named channel at all,
        which is the minority case (measured ~1 track in 12). The verified badge
        is then the only extra evidence available, so it is worth the request.
        """
        want_ids = [e.get("id") for _s, e in scored[:VERIFY_PROBE_LIMIT] if e.get("id")]
        if not want_ids:
            return
        flags = probe_verified(want_ids)
        if not flags:
            return
        rescored = []
        for s, e in scored:
            vid = e.get("id")
            if vid in flags:
                e["channel_is_verified"] = flags[vid]
            rescored.append((score_candidate(e, want_seconds, artist), e))
        scored[:] = rescored

    @staticmethod
    def _download(cand: dict, dest: Path, track: Track) -> None:
        """Download the chosen candidate, convert to MP3, then retag it.

        Order matters. yt-dlp first writes whatever tags YouTube carried
        (artist = the channel name, e.g. "David Dean Burkhart"), then we
        overwrite them with Spotify's own metadata via ``providers/tags.py``.
        Doing it here rather than in the orchestrator keeps one code path: the
        file is already finished MP3 here, and the orchestrator only stages it.
        """
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
                # Copies YouTube's tags. We overwrite the important ones right
                # after, so the leftover 'comment' URL is the only trace left —
                # and that is honest provenance, so it stays.
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

        # ---- R4: replace YouTube's tags with Spotify's -------------------
        # Never fatal: a tagging problem must not lose the audio.
        try:
            from .tags import write_tags

            report = write_tags(
                dest,
                title=track.title,
                artist=track.artist,
                album=track.album,
                year=getattr(track, "year", 0) or 0,
                track_number=getattr(track, "track_number", 0) or 0,
                disc_number=getattr(track, "disc_number", 0) or 0,
                label=getattr(track, "label", "") or "",
                cover_url=track.thumbnail or "",
            )
            print(f"[tags] {track.title}: {report.get('tags')} "
                  f"cover={report.get('cover')} {report.get('error') or ''}")
        except Exception as exc:  # noqa: BLE001
            print(f"[tags] gagal menulis tag untuk '{track.title}': {exc}")

    # ------------------------------------------- orchestrator integration
    @staticmethod
    def is_local_path(url: str) -> bool:
        """True when a resolved 'URL' is actually a file already on disk."""
        return bool(url) and os.path.exists(url) and not url.startswith(("http://", "https://"))

    def cleanup_cache(self) -> None:
        """Drop only the throwaway yt-dlp scratch files.

        This used to ``shutil.rmtree(CACHE_DIR)``, i.e. delete every cached MP3,
        the sidecar records and the metadata caches. Nothing calls it today, but
        leaving that in place means one future caller silently wipes the user's
        whole cache — and the app's rule is that the cache is only ever removed
        when the user asks for it (the sidebar button). Stale batch ZIPs are
        cleaned separately by :func:`purge_stale_zips`, on their own age policy.
        """
        shutil.rmtree(CACHE_DIR / "ytdlp", ignore_errors=True)
