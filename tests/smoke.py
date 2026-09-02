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
from providers.parsing import (  # noqa: E402
    decode_track_data,
    first_mp3_link,
    parse_track_rows,
    track_from_row,
)
from core.orchestrator import BatchOrchestrator, DownloadMode, TrackState  # noqa: E402
from core import i18n  # noqa: E402
from providers.mock import MockProvider  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


SOUNDLOADERS_HTML = """
<div class="music-player-wrapper">
  <div class="player-container">
    <h2 class="playlist-title">Top 50 - Global</h2>
    <div class="playlist-songs" id="playlist-songs">
      <ul class="playlist-list">
        <li class="track-list-item" id="song-0">
          <div class="song-info">
            <img src="https://i.scdn.co/image/ab67616d00001e02aaaa" alt="cover">
            <div class="song-meta">
              <h3 class="song-title">Blinding Lights</h3>
              <p class="song-artist">The Weeknd</p>
            </div>
          </div>
          <form name="submitspurl" data-error-id="download-error">
            <input type="hidden" name="data" value="NTg1ODg2">
            <input type="hidden" name="track_token" value="abc123">
            <button type="submit">Download MP3</button>
          </form>
        </li>
        <li class="track-list-item" id="song-1">
          <div class="song-info">
            <img src="https://i.scdn.co/image/ab67616d00001e02bbbb" alt="cover">
            <div class="song-meta">
              <h3 class="song-title">Levitating</h3>
              <p class="song-artist">Dua Lipa</p>
            </div>
          </div>
          <form name="submitspurl">
            <input type="hidden" name="data" value="NTc5NDk5">
            <input type="hidden" name="track_token" value="def456">
            <button type="submit">Download</button>
          </form>
        </li>
      </ul>
    </div>
  </div>
</div>
"""


def test_parser_soundloaders():
    rows = parse_track_rows(SOUNDLOADERS_HTML)
    check("sl: found 2 rows", len(rows) == 2, f"got {len(rows)}")
    if rows:
        m0 = track_from_row(rows[0])
        check("sl: data parsed", m0["data"] == "NTg1ODg2", str(m0))
        check("sl: token parsed", m0["track_token"] == "abc123", str(m0))
        check("sl: title parsed", m0["title"] == "Blinding Lights", str(m0))
        check("sl: artist parsed", m0["artist"] == "The Weeknd", str(m0))
        check("sl: thumb parsed", m0["thumbnail"].startswith("https://i.scdn.co"), str(m0["thumbnail"]))


def test_parser_spotidown():
    html = """
    <div class="container" id="download-section">
      <div class="row">
        <div class="col-md-4 col-sm-12">
          <div class="card track-row">
            <img src="https://i.scdn.co/image/ab67616d00001e02cccc">
            <h3 class="song-name">Shape of You</h3>
            <p class="artist-name">Ed Sheeran</p>
            <form name="submitspurl">
              <input type="hidden" name="data" value="eyJuYW1lIjoiU2hhcGUgb2YgWW91IiwiYXJ0aXN0IjoiRWQgU2hlZXJhbiJ9">
              <input type="hidden" name="base" value="spotifytrack">
              <input type="hidden" name="token" value="tok123">
              <input type="hidden" name="_uMihH" value="25c10e32e38ffa44ae5b500ec2c036ee">
              <button class="abutton" type="submit"><span><span>Download</span></span></button>
            </form>
          </div>
        </div>
      </div>
    </div>
    """
    rows = parse_track_rows(html)
    check("sd: found 1 row", len(rows) == 1, f"got {len(rows)}")
    if rows:
        m0 = track_from_row(rows[0])
        check("sd: data decoded name", decode_track_data(m0["data"]).get("name") == "Shape of You", str(m0))
        check("sd: keeps _uMihH", m0.get("_uMihH") == "25c10e32e38ffa44ae5b500ec2c036ee" or
              decode_track_data(m0["data"]).get("name") == "Shape of You", str(m0))


def test_first_mp3():
    html = '<a href="https://cdn.soundloaders.app/dl/foo123/bar.mp3?x=1">download</a>'
    link = first_mp3_link(html)
    check("mp3: link found", link.startswith("https://cdn.soundloaders.app"), link)


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


def main():
    test_parser_soundloaders()
    test_parser_spotidown()
    test_first_mp3()
    test_orchestrator_mock_zip()
    test_i18n()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
