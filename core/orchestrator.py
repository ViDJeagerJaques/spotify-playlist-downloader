"""Batch orchestrator: per-track resolve + (optional) local ZIP packaging.

Flow
----
1. A provider (SoundLoaders / SpotiDown) has already produced ``tracks`` from the
   Spotify URL. This module loops over them and calls the provider's
   ``resolve_track`` once per track (the same thing SoundLoaders' own UI does
   one by one).
2. Each resolved MP3 URL is either kept as-is or streamed into a local temp
   file (see ``DownloadMode``).
3. After every track has been processed the orchestrator can bundle the local
   files into a single ZIP that the Streamlit UI offers as one download.

Why we build the ZIP ourselves
------------------------------
Both services ship their own "batch" endpoints (SoundLoaders /action/tracks for
each row; SpotiDown /action/bulktrack + /action/create_zip). SpotiDown's ZIP
endpoint is gated (free users get 5 tracks) — see providers/spotidown.py. So the
app resolves per track with the *free* single-track endpoints and does ZIP
packaging locally. That keeps the app free of any third-party premium gate.
"""
from __future__ import annotations

import re
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

import requests

from providers.base import ProviderId, ServiceError, Track
from providers.mock import MockProvider, _mock_mp3_bytes


class DownloadMode(str, Enum):
    STREAM_LOCAL = "stream_local"   # save each MP3 to a temp file, then ZIP
    KEEP_URL = "keep_url"           # only collect MP3 URLs, no local storage


class TrackState(str, Enum):
    WAITING = "waiting"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class TrackOutcome:
    index: int
    state: TrackState = TrackState.WAITING
    title: str = ""
    mp3_url: str = ""
    error: str = ""
    local_path: Optional[Path] = None


@dataclass
class BatchResult:
    provider: str
    mode: DownloadMode
    outcomes: List[TrackOutcome] = field(default_factory=list)
    zip_path: Optional[Path] = None
    started_at: float = field(default_factory=time.time)
    elapsed: float = 0.0
    total: int = 0
    ok: int = 0
    failed: int = 0

    @property
    def summary(self) -> str:
        return f"{self.ok}/{self.total} succeeded, {self.failed} failed ({self.elapsed:.1f}s)"


# Progress callback: fn(index, state, outcome_so_far, message)
ProgressFn = Callable[[int, TrackState, TrackOutcome, str], None]


def _sanitize_component(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip() or "track"


class LocalFileFetcher:
    """Stream a provider MP3 URL to a local temp file. HTTP range-tolerant."""
    def __init__(self, chunk_size: int = 1 << 16):
        self._chunk = chunk_size

    def fetch(self, url: str, dest: Path) -> None:
        with requests.get(url, stream=True, timeout=30, allow_redirects=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=self._chunk):
                    if chunk:
                        fh.write(chunk)


class MockDownloadHandler:
    """Replaces LocalFileFetcher when MockProvider is selected (no network)."""
    def fetch(self, url: str, dest: Path) -> None:
        if url.startswith("mock://"):
            dest.write_bytes(_mock_mp3_bytes())
        else:
            raise ServiceError("mock fetch requires mock:// URL")


class BatchOrchestrator:
    """Run resolve for every track and optionally assemble a local ZIP."""

    def __init__(self, provider, mode: DownloadMode = DownloadMode.STREAM_LOCAL):
        self.provider = provider
        self.mode = mode
        self._fetcher: Optional[LocalFileFetcher] = None

    def run(self, tracks: List[Track], cftoken: str = "", progress: Optional[ProgressFn] = None,
            pause_secs: float = 0.0) -> BatchResult:
        result = BatchResult(
            provider=self.provider.name,
            mode=self.mode,
            total=len(tracks),
            outcomes=[TrackOutcome(index=i, title=t.title) for i, t in enumerate(tracks)],
        )
        temp_dir: Optional[Path] = None
        cleanup_on_finish = self.mode == DownloadMode.STREAM_LOCAL

        if cleanup_on_finish:
            temp_dir = Path(tempfile.mkdtemp(prefix="spl_dl_"))
            if getattr(self.provider, "provider", None) == ProviderId.MOCK:
                self._fetcher = MockDownloadHandler()
            else:
                self._fetcher = LocalFileFetcher()

        try:
            for i, track in enumerate(tracks):
                outcome = result.outcomes[i]
                outcome.state = TrackState.PROCESSING
                if progress:
                    progress(i, TrackState.PROCESSING, outcome, "processing")
                try:
                    url = self.provider.resolve_track(track, cftoken=cftoken)
                    if cleanup_on_finish:
                        safe = _sanitize_component(f"{i+1:02d} - {track.filename}") + ".mp3"
                        dest = temp_dir / safe  # temp_dir is set when cleanup_on_finish
                        self._fetcher.fetch(url, dest)
                        outcome.mp3_url = url
                        outcome.local_path = dest
                    else:
                        outcome.mp3_url = url
                    outcome.state = TrackState.READY
                    result.ok += 1
                    if progress:
                        progress(i, TrackState.READY, outcome, "ready")
                except Exception as exc:  # noqa: BLE001 - surface per-track failures
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    result.failed += 1
                    if progress:
                        progress(i, TrackState.FAILED, outcome, "failed")
                if pause_secs:
                    time.sleep(pause_secs)

            if cleanup_on_finish and temp_dir and result.ok:
                result.zip_path = self._make_zip(temp_dir)
        finally:
            # The ZIP already contains copies of every MP3, so the staging
            # folder is not needed anymore and is removed immediately.
            if cleanup_on_finish and temp_dir:
                self._cleanup_dir(temp_dir)

        result.elapsed = time.time() - result.started_at
        return result

    def _make_zip(self, folder: Path) -> Path:
        zip_path = Path(tempfile.gettempdir()) / f"spl_{int(time.time()*1000)}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(folder.glob("*.mp3")):
                zf.write(f, arcname=f.name)
        return zip_path

    @staticmethod
    def _cleanup_dir(folder: Path) -> None:
        import shutil

        try:
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass

    @property
    def temp_dir(self) -> Optional[Path]:
        return None  # retained for API stability; staging dir is auto-cleaned


def make_provider(kind: str):
    from providers.soundloaders import SoundLoadersClient
    from providers.spotidown import SpotiDownClient

    mapping = {
        ProviderId.SOUNDLOADERS.value: SoundLoadersClient,
        ProviderId.SPOTIDOWN.value: SpotiDownClient,
        ProviderId.MOCK.value: MockProvider,
    }
    cls = mapping.get(kind)
    if cls is None:
        raise ServiceError(f"Unknown provider: {kind}")
    return cls()
