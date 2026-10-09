"""Shared data types, enums and errors for the third-party providers.

This app is deliberately NOT a from-scratch Spotify scraper. It only talks to
external download services (SoundLoaders / SpotiDown) that already resolved the
Spotify URL server-side. Everything in ``providers/`` is a thin HTTP client for
one of those services.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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
