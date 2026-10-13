"""Shared data types, enums and errors for the third-party providers.

This app is deliberately NOT a from-scratch Spotify scraper. It only talks to
external download services (SoundLoaders / SpotiDown) that already resolved the
Spotify URL server-side. Everything in ``providers/`` is a thin HTTP client for
one of those services.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


def cache_dir() -> Path:
    """Single source of truth for where this app stores anything on disk.

    Every provider used to call ``tempfile.gettempdir()``, which on Windows is
    always ``C:\\Users\\<you>\\AppData\\Local\\Temp`` no matter which drive the
    project lives on. Downloaded MP3s, metadata JSON and batch ZIPs all piled up
    there silently — roughly 5MB per track, so a 200-track playlist is about a
    gigabyte on the system disk.

    Default is now ``<project>/.cache``, overridable with ``SPOTIFY_CACHE_DIR``.
    Lives here rather than in one of the providers because three separate
    modules need it and importing between providers would create cycles.
    """
    override = os.environ.get("SPOTIFY_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[1] / ".cache"


class ProviderId(str, Enum):
    """Identifier of the third-party backend that powers the download."""

    SOUNDLOADERS = "soundloaders"
    SPOTIDOWN = "spotidown"
    SPOTIDOWN_CO = "spotidown_co"   # spotidown.co (browser-driven; see spotidown_co.py)
    YOUTUBE = "youtube"             # Spotify metadata + yt-dlp audio (deployable)
    MOCK = "mock"


@dataclass
class Track:
    """A single track discovered inside a Spotify link by the provider."""

    data: str                    # provider-specific payload replayed to /action/tracks
    track_token: str = ""        # provider token for the track
    title: str = "Unknown"
    artist: str = "Unknown"
    thumbnail: str = ""
    mp3_url: Optional[str] = None  # set after resolve_track succeeds
    # Optional metadata. Providers that return richer JSON (spotidown.co) fill
    # these in; the older HTML-scraping providers leave them at their defaults.
    duration_ms: int = 0          # track length in milliseconds (0 = unknown)
    album: str = ""               # album title when the provider reports one
    # Tagging metadata (R4). Populated from the anonymous Spotify metadata
    # endpoint; every field is optional and simply left at its default when the
    # provider cannot supply it.
    label: str = ""               # record label, e.g. "Polydor Records"
    year: int = 0                 # release year, 0 = unknown
    track_number: int = 0         # position within the album, 0 = unknown
    disc_number: int = 0          # disc, 0 = unknown

    @property
    def filename(self) -> str:
        return _slug(f"{self.artist} - {self.title}")


@dataclass
class ResolveResult:
    """Result of POSTing a Spotify URL to the provider's /action."""

    title: str = "Spotify content"          # source name when known (playlist/album/artist)
    source_url: str = ""
    tracks: list = field(default_factory=list)  # list[Track]
    raw_hint: str = ""                      # short error/hint text from provider if any


class ServiceError(Exception):
    """Friendly error raised by a provider/orchestrator layer.

    ``user_message`` is meant to be shown directly in the UI (localized at the
    call site); ``details`` carries technical context for the expander log.
    """

    def __init__(self, user_message: str, details: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.details = details or user_message


class CaptchaRequiredError(ServiceError):
    """The provider rejected the request because it needs a valid captcha token.

    Raised whenever a request has no usable token, or the service says the token
    is wrong/expired. SoundLoaders currently requires Cloudflare Turnstile;
    SpotiDown requires reCAPTCHA v3.

    These tokens are single-use and short-lived, so this error is retryable:
    the user solves the CAPTCHA again for a fresh token and the failed action
    is retried (see BatchOrchestrator.retry_failed).
    """

    retryable_after_refresh = True


def _slug(text: str, max_len: int = 120) -> str:
    """Turn arbitrary text into a safe-ish filename fragment."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", text).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "track"
    return cleaned[:max_len]


# --------------------------------------------------------------------------
# Cover art resolution
# --------------------------------------------------------------------------
# A Spotify CDN image URL encodes the size in its prefix. The hash after the
# prefix is identical at every size, so we can request the big one by swapping
# the prefix — no re-hashing, no API call.
#
#   ab67616d00001e02... -> 300x300  (~45 KB)   what oEmbed hands out
#   ab67616d0000b273... -> 640x640  (~158 KB)  what we want
#   ab67616d00004851... ->  64x64   (~4 KB)
#
# Album art uses the "ab67616d" family. PLAYLIST images use a different family
# ("ab67706f") and 404 at the large prefix, so the replacement is deliberately
# narrow: it only ever rewrites the exact small-album prefix.
COVER_SMALL_PREFIX = "ab67616d00001e02"
COVER_LARGE_PREFIX = "ab67616d0000b273"


def upgrade_cover_url(url: str) -> str:
    """Request the 640x640 version of an album cover instead of 300x300.

    Safe by construction: it only rewrites the exact small-album prefix, so
    playlist images (``ab67706f…``) and any non-Spotify host are left untouched —
    upgrading those would 404.
    """
    if not url:
        return url
    return url.replace(COVER_SMALL_PREFIX, COVER_LARGE_PREFIX)
