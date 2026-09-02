"""Mock provider — lets you run/demo the whole app WITHOUT network access.

It behaves like the real providers (same Track/ResolveResult shape, same
resolve step) but generates a tiny silent audio file instead of calling a
third-party service. It also records callbacks so you can exercise the full
ZIP pipeline and per-track progress offline.

Enable it from the UI: Backend -> Demo (Mock).
"""
from __future__ import annotations

import base64
import wave
from io import BytesIO

from .base import ProviderId, ResolveResult, ServiceError, Track

_SAMPLE = None  # lazily generated 0.4 s silent PCM WAV payload


def _mock_mp3_bytes() -> bytes:
    """Return tiny bytes that stand in for an MP3 (silent WAV)."""
    global _SAMPLE
    if _SAMPLE is not None:
        return _SAMPLE
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 3200)  # 0.4 s silence
    _SAMPLE = buf.getvalue()
    return _SAMPLE


_DEMO = [
    ("Neon Lights", "Reva Dawn", "https://picsum.photos/seed/nl/200"),
    ("Midnight Drive", "The Afterglows", "https://picsum.photos/seed/md/200"),
    ("Golden Hour", "Lumen", "https://picsum.photos/seed/gh/200"),
    ("Paper Planes", "Coastline", "https://picsum.photos/seed/pp/200"),
    ("Slow Motion", "Kite String", "https://picsum.photos/seed/sm/200"),
]


class MockProvider:
    name = "Demo (Mock)"
    provider = ProviderId.MOCK

    def __init__(self, timeout: int = 10):
        self._timeout = timeout

    def load_tracks(self, spotify_url: str, cftoken: str = "") -> ResolveResult:
        tracks = []
        for title, artist, thumb in _DEMO:
            meta = {"name": title, "artist": artist}
            data = base64.b64encode(str(meta).encode("utf-8")).decode("ascii")
            tracks.append(Track(data=data, track_token=f"mock-{title.lower().replace(' ', '-')}",
                                title=title, artist=artist, thumbnail=thumb))
        return ResolveResult(title="Mock Playlist (demo)", source_url=spotify_url, tracks=tracks)

    def resolve_track(self, track: Track, cftoken: str = "") -> str:
        # Real providers return a remote URL here. The orchestrator decides
        # whether to stream it to disk or keep it as a URL; MockMode uses
        # MockDownloadHandler (see core/orchestrator.py) which returns raw bytes.
        return "mock://" + track.track_token
