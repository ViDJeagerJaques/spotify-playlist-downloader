"""Offline functional checks (no network).

Run:  python tests/smoke.py   (from the project root)
Uses the mock provider + hand-built provider HTML so parsing/orchestration/i18n
are exercised without depending on third-party uptime.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.base import Track  # noqa: E402
from core.orchestrator import BatchOrchestrator, DownloadMode, TrackState  # noqa: E402
from core import i18n  # noqa: E402
from providers.mock import MockProvider  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def test_orchestrator_mock_zip():
    provider = MockProvider()
    tracks = provider.load_tracks("mock://playlist")
    orch = BatchOrchestrator(provider, mode=DownloadMode.STREAM_LOCAL)
    states = []
    result = orch.run(tracks.tracks, progress=lambda i, s, o, m: states.append(s))
    check("batch: all ready", result.ok == len(tracks.tracks) and result.failed == 0, result.summary)
    check("batch: zip created", result.zip_path is not None and result.zip_path.exists())
    check("batch: progress saw ready", TrackState.READY in states, str(set(states)))
    if result.zip_path:
        with zipfile.ZipFile(result.zip_path) as zf:
            names = zf.namelist()
            check("zip: contains mp3 entries", len(names) == len(tracks.tracks), str(names))
        result.zip_path.unlink(missing_ok=True)


def test_i18n():
    id_title = i18n.tr("id", "app_title")
    en_title = i18n.tr("en", "app_title")
    check("i18n: id", id_title == "Spotify Playlist Downloader")
    check("i18n: en", en_title == "Spotify Playlist Downloader")
    en_batch = i18n.tr("en", "main.btn_batch", n=3)
    check("i18n: format", "3" in en_batch, en_batch)
    check("i18n: fallback to key", i18n.tr("xx", "no.such.key") == "no.such.key")


def test_retry_failed_recovers():
    """Expired token fails tracks as captcha -> fresh token recovers them."""
    from providers.base import CaptchaRequiredError, Track as TrackT  # noqa: E402

    class Flaky(MockProvider):
        def __init__(self):
            super().__init__()
            self.token_ok = False

        def resolve_track(self, track, cftoken=""):
            if not self.token_ok and track.track_token.endswith(("-neon-lights", "-golden-hour")):
                raise CaptchaRequiredError("token expired", details="token_len=3")
            return super().resolve_track(track, cftoken=cftoken)

    provider = Flaky()
    tracks = provider.load_tracks("mock://playlist").tracks
    orch = BatchOrchestrator(provider, mode=DownloadMode.STREAM_LOCAL)
    result = orch.run(tracks, cftoken="OLD")
    check("retry: 2 failed 3 ok", result.failed == 2 and result.ok == 3, result.summary)
    kinds = {o.error_kind for o in result.outcomes if o.state == TrackState.FAILED}
    check("retry: kinds marked captcha", kinds == {"captcha"}, str(kinds))

    provider.token_ok = True  # user solved CAPTCHA again -> fresh token
    summary = orch.retry_failed(result, tracks, cftoken="NEW")
    check("retry: recovered 2", summary["recovered"] == 2 and summary["still_failed"] == 0,
          str(summary))
    check("retry: counts ok", result.ok == len(tracks) and result.failed == 0, result.summary)
    if result.zip_path:
        with zipfile.ZipFile(result.zip_path) as zf:
            names = zf.namelist()
            check("retry: zip merged all", len(names) == len(tracks), str(names))
        result.zip_path.unlink(missing_ok=True)


def test_retry_keeps_other_failures():
    """Non-token failures are classified and stay failed after retry."""
    from providers.base import ServiceError  # noqa: E402

    class Flaky2(MockProvider):
        def resolve_track(self, track, cftoken=""):
            if track.track_token.endswith("-neon-lights"):
                raise ServiceError("no MP3 link")
            return super().resolve_track(track, cftoken=cftoken)

    provider = Flaky2()
    tracks = provider.load_tracks("mock://playlist").tracks
    orch = BatchOrchestrator(provider, mode=DownloadMode.KEEP_URL)
    result = orch.run(tracks)
    kinds = {o.error_kind for o in result.outcomes if o.state == TrackState.FAILED}
    check("retry: kind marked service", kinds == {"service"}, str(kinds))
    summary = orch.retry_failed(result, tracks, cftoken="NEW")
    check("retry: nothing recovered", summary["recovered"] == 0 and summary["still_failed"] == 1,
          str(summary))


def main():
    # The HTML parsers for SoundLoaders / SpotiDown lived in providers/parsing.py
    # and went with those backends. What remains is the mock provider, the
    # orchestrator, i18n and the captcha-retry paths, all still worth guarding.
    test_orchestrator_mock_zip()
    test_i18n()
    test_retry_failed_recovers()
    test_retry_keeps_other_failures()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
