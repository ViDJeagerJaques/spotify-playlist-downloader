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

Provider flavours handled here
------------------------------
* **Per-track resolve** (SoundLoaders, SpotiDown.app): every track needs its own
  request to obtain the MP3 URL.
* **Prefetched URLs** (spotidown.co): the listing response already contains the
  MP3 URL for each track, so the orchestrator reuses ``track.mp3_url`` and never
  calls ``resolve_track()``. Its downloads go through ``ResilientFileFetcher``
  because that CDN rejects a random share of requests (see that class).
"""
from __future__ import annotations

import random
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

import requests

from providers.base import CaptchaRequiredError, ProviderId, ServiceError, Track, cache_dir
from providers.mock import MockProvider, _mock_mp3_bytes


def _scratch_dir() -> Path:
    """Where per-run staging folders and batch ZIPs are written.

    Kept beside the project instead of ``tempfile.gettempdir()``: the latter is
    always on C:, and a batch ZIP for a large playlist is hundreds of megabytes.
    Imported indirectly through :func:`providers.base.cache_dir` so the
    orchestrator does not depend on a specific provider being importable.
    """
    return cache_dir()



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
    # Machine-readable failure class for the refresh/retry flow:
    # "captcha" (token expired/invalid -> retry after user refreshes the
    # token), "fetch" (MP3 URL resolved but file download failed),
    # "service" (anything else), "" (no failure / legacy results).
    error_kind: str = ""
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


class ResilientFileFetcher:
    """Fetcher for providers whose CDN rejects a random share of requests.

    ``spotidown.co`` hands out ``audio.url`` values that 302-redirect to a CDN
    (``*.123tokyo.xyz``). That CDN intermittently answers 403/5xx under load, and
    *which* URLs fail changes on every run — it is not a property of the track.
    So we retry with a growing delay plus jitter, and skip files that already
    exist so a re-run only fetches what is missing.

    The provider supplies the required ``Origin``/``Referer``/UA headers (the CDN
    answers 403 without them) via ``provider.download_headers()``.
    """

    def __init__(self, headers: Optional[dict] = None, attempts: int = 4,
                 chunk_size: int = 1 << 16):
        self._headers = dict(headers or {})
        self._attempts = max(1, attempts)
        self._chunk = chunk_size

    def fetch(self, url: str, dest: Path) -> None:
        if dest.exists() and dest.stat().st_size > 0:
            return  # already downloaded (re-run after a partial failure)

        last_err = "unknown"
        for attempt in range(1, self._attempts + 1):
            if attempt > 1:
                time.sleep(min(1.5 * attempt, 5) + random.uniform(0, 0.8))
            try:
                with requests.get(url, stream=True, timeout=120,
                                  allow_redirects=True, headers=self._headers) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=self._chunk):
                            if chunk:
                                fh.write(chunk)
                if dest.stat().st_size > 0:
                    return
                last_err = "empty response body"
            except Exception as exc:  # noqa: BLE001 - classified as a fetch failure
                last_err = str(exc) or repr(exc)
            # A partial file would be mistaken for a success on the next attempt.
            try:
                if dest.exists():
                    dest.unlink()
            except Exception:  # noqa: BLE001
                pass

        raise ServiceError(f"download failed after {self._attempts} attempts: {last_err}")


class MockDownloadHandler:
    """Replaces LocalFileFetcher when MockProvider is selected (no network)."""
    def fetch(self, url: str, dest: Path) -> None:
        if url.startswith("mock://"):
            dest.write_bytes(_mock_mp3_bytes())
        else:
            raise ServiceError("mock fetch requires mock:// URL")


class _FetchError(Exception):
    """Internal marker: MP3 URL resolved fine but the file download failed."""


class LocalCopyFetcher:
    """Fetcher for providers that produce a finished file on disk themselves.

    The YouTube provider runs search + download + ffmpeg inside
    ``resolve_track`` and hands back a local path. There is nothing to download
    over HTTP — we just move the file into the staging directory.
    """

    def fetch(self, url: str, dest: Path) -> None:
        src = Path(url)
        if not src.exists():
            raise _FetchError(f"file tidak ada: {src}")
        if src.stat().st_size == 0:
            raise _FetchError(f"file kosong: {src}")
        if dest.exists() and dest.stat().st_size > 0:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))


class BatchOrchestrator:
    """Run resolve for every track and optionally assemble a local ZIP."""

    def __init__(self, provider, mode: DownloadMode = DownloadMode.STREAM_LOCAL):
        self.provider = provider
        self.mode = mode
        self._fetcher: Optional[LocalFileFetcher] = None

    def _ensure_fetcher(self) -> None:
        if self._fetcher is None:
            if getattr(self.provider, "provider", None) == ProviderId.MOCK:
                self._fetcher = MockDownloadHandler()
            elif getattr(self.provider, "provider", None) == ProviderId.YOUTUBE:
                # The YouTube provider already produced a finished MP3 on disk
                # (search + download + ffmpeg). "Fetching" is a local copy.
                self._fetcher = LocalCopyFetcher()
            elif getattr(self.provider, "prefetched_urls", False):
                # Provider already handed us the MP3 URL per track, and its CDN
                # rejects a random share of requests -> retry, correct headers.
                headers = {}
                getter = getattr(self.provider, "download_headers", None)
                if callable(getter):
                    try:
                        headers = getter()
                    except Exception:  # noqa: BLE001 - headers are best-effort
                        headers = {}
                self._fetcher = ResilientFileFetcher(headers=headers)
            else:
                self._fetcher = LocalFileFetcher()

    @staticmethod
    def _arcname(index: int, track: Track) -> str:
        """Deterministic ZIP entry name, identical across run() and retries."""
        return _sanitize_component(f"{index+1:02d} - {track.filename}") + ".mp3"

    def _resolve_and_stage(self, index: int, track: Track, cftoken: str,
                           temp_dir: Optional[Path]) -> str:
        """Resolve one track and (in ZIP mode) download it into temp_dir.

        Returns the MP3 URL. Raises CaptchaRequiredError when the token was
        rejected, anything else for service/fetch problems.

        Providers that advertise ``prefetched_urls`` (spotidown.co) already put
        the MP3 URL on the Track during load_tracks(), so we reuse it instead of
        spending a pointless resolve request per track.
        """
        if getattr(self.provider, "prefetched_urls", False) and track.mp3_url:
            mp3_url = track.mp3_url
        else:
            mp3_url = self.provider.resolve_track(track, cftoken=cftoken)
        if temp_dir is not None:
            self._ensure_fetcher()
            try:
                self._fetcher.fetch(mp3_url, temp_dir / self._arcname(index, track))
            except CaptchaRequiredError:
                raise
            except Exception as exc:  # noqa: BLE001 - classify fetch failures
                raise _FetchError(str(exc)) from exc
        return mp3_url

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
            temp_dir = _scratch_dir() / "spl_dl_"
            temp_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_fetcher()

        try:
            for i, track in enumerate(tracks):
                outcome = result.outcomes[i]
                outcome.state = TrackState.PROCESSING
                if progress:
                    progress(i, TrackState.PROCESSING, outcome, "processing")
                try:
                    url = self._resolve_and_stage(i, track, cftoken, temp_dir)
                    outcome.mp3_url = url
                    if cleanup_on_finish:
                        outcome.local_path = temp_dir / self._arcname(i, track)  # type: ignore[union-attr]
                    outcome.state = TrackState.READY
                    outcome.error = ""
                    outcome.error_kind = ""
                    result.ok += 1
                    if progress:
                        progress(i, TrackState.READY, outcome, "ready")
                except CaptchaRequiredError as exc:
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    outcome.error_kind = "captcha"
                    result.failed += 1
                    if progress:
                        progress(i, TrackState.FAILED, outcome, "failed")
                except _FetchError as exc:
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    outcome.error_kind = "fetch"
                    result.failed += 1
                    if progress:
                        progress(i, TrackState.FAILED, outcome, "failed")
                except Exception as exc:  # noqa: BLE001 - surface per-track failures
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    outcome.error_kind = "service"
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

    def retry_failed(self, result: BatchResult, tracks: List[Track], cftoken: str = "",
                     progress: Optional[ProgressFn] = None, pause_secs: float = 1.0,
                     only_kinds: Optional[tuple] = None) -> dict:
        """Retry the FAILED outcomes of a previous run with a (fresh) token.

        Used after the user refreshes an expired/single-use CAPTCHA token:
        only tracks that failed are re-requested, successes are untouched, and
        newly recovered MP3s are merged into the existing ZIP (STREAM_LOCAL).

        Returns {"retried": n, "recovered": m, "still_failed": k}.
        """
        targets = [
            o for o in result.outcomes
            if o.state == TrackState.FAILED
            and (only_kinds is None or o.error_kind in only_kinds)
            and 0 <= o.index < len(tracks)
        ]
        summary = {"retried": len(targets), "recovered": 0, "still_failed": 0}
        if not targets:
            return summary

        cleanup_on_finish = self.mode == DownloadMode.STREAM_LOCAL
        temp_dir: Optional[Path] = None
        if cleanup_on_finish:
            temp_dir = _scratch_dir() / "spl_rt_"
            temp_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_fetcher()

        try:
            for outcome in targets:
                i = outcome.index
                track = tracks[i]
                outcome.state = TrackState.PROCESSING
                outcome.error = ""
                outcome.error_kind = ""
                if progress:
                    progress(i, TrackState.PROCESSING, outcome, "retrying")
                try:
                    url = self._resolve_and_stage(i, track, cftoken, temp_dir)
                    outcome.mp3_url = url
                    if cleanup_on_finish:
                        outcome.local_path = temp_dir / self._arcname(i, track)  # type: ignore[union-attr]
                    outcome.state = TrackState.READY
                    result.ok += 1
                    result.failed -= 1
                    summary["recovered"] += 1
                    if progress:
                        progress(i, TrackState.READY, outcome, "ready")
                except CaptchaRequiredError as exc:
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    outcome.error_kind = "captcha"
                    if progress:
                        progress(i, TrackState.FAILED, outcome, "failed")
                except _FetchError as exc:
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    outcome.error_kind = "fetch"
                    if progress:
                        progress(i, TrackState.FAILED, outcome, "failed")
                except Exception as exc:  # noqa: BLE001 - keep going with the rest
                    outcome.state = TrackState.FAILED
                    outcome.error = str(exc)
                    outcome.error_kind = "service"
                    if progress:
                        progress(i, TrackState.FAILED, outcome, "failed")
                if pause_secs:
                    time.sleep(pause_secs)

            if cleanup_on_finish and temp_dir and summary["recovered"]:
                staged = sorted(temp_dir.glob("*.mp3"))
                if result.zip_path is not None and result.zip_path.exists():
                    result.zip_path = self._merge_into_zip(result.zip_path, staged)
                elif result.ok:
                    result.zip_path = self._make_zip(temp_dir)
        finally:
            if cleanup_on_finish and temp_dir:
                self._cleanup_dir(temp_dir)

        summary["still_failed"] = sum(1 for o in result.outcomes if o.state == TrackState.FAILED)
        result.elapsed = time.time() - result.started_at
        return summary

    def _make_zip(self, folder: Path) -> Path:
        zip_dir = _scratch_dir()
        zip_dir.mkdir(parents=True, exist_ok=True)
        # Zips from earlier sessions are dead weight by now (the browser has
        # long since downloaded them) and used to accumulate in the system temp
        # folder forever. Sweep them before writing another one. Imported lazily
        # so the orchestrator keeps working if the provider module is trimmed.
        try:
            from providers.youtube import purge_stale_zips
            purge_stale_zips()
        except Exception:  # noqa: BLE001
            pass
        zip_path = zip_dir / f"spl_{int(time.time()*1000)}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(folder.glob("*.mp3")):
                zf.write(f, arcname=f.name)
        return zip_path

    @staticmethod
    def _merge_into_zip(old_zip: Path, new_files: List[Path]) -> Path:
        """Return a new ZIP with the old entries plus the newly staged MP3s.

        Old staging folders are deleted after run(), so recovered tracks can
        only be combined with previous successes by copying the old ZIP.
        The old file is removed (best effort) after the merge succeeds.
        """
        zip_dir = _scratch_dir()
        zip_dir.mkdir(parents=True, exist_ok=True)
        try:
            from providers.youtube import purge_stale_zips
            purge_stale_zips()
        except Exception:  # noqa: BLE001
            pass
        merged = zip_dir / f"spl_{int(time.time()*1000)}_r.zip"
        with zipfile.ZipFile(old_zip) as zin:
            old_names = set(zin.namelist())
            with zipfile.ZipFile(merged, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    zout.writestr(item, zin.read(item.filename))
                for f in new_files:
                    if f.name not in old_names:  # same arcname scheme -> skip dupes
                        zout.write(f, arcname=f.name)
        try:
            old_zip.unlink(missing_ok=True)
        except Exception:
            pass
        return merged

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
    from providers.spotidown_co import SpotiDownCoClient
    from providers.youtube import YouTubeClient

    mapping = {
        ProviderId.SOUNDLOADERS.value: SoundLoadersClient,
        ProviderId.SPOTIDOWN.value: SpotiDownClient,
        ProviderId.SPOTIDOWN_CO.value: SpotiDownCoClient,
        ProviderId.YOUTUBE.value: YouTubeClient,
        ProviderId.MOCK.value: MockProvider,
    }
    cls = mapping.get(kind)
    if cls is None:
        raise ServiceError(f"Unknown provider: {kind}")
    return cls()
