"""Offline tests for the YouTube provider — no network, no credentials needed.

Run:  .venv/Scripts/python.exe tests/test_youtube.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from providers.base import ProviderId, ServiceError, Track          # noqa: E402
from providers.spotify_meta import parse_spotify_url                # noqa: E402
from providers.youtube import (                                     # noqa: E402
    MAX_DURATION_DRIFT_S,
    build_query,
    score_candidate,
)
from core.orchestrator import LocalCopyFetcher, make_provider       # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


# ---------------------------------------------------------------- URL parsing
print("\n[URL parsing]")
check("playlist URL",
      parse_spotify_url("https://open.spotify.com/playlist/0OAWLZxZydBuXyVuCszKT") ==
      ("playlist", "0OAWLZxZydBuXyVuCszKT"))
check("playlist URL with query string",
      parse_spotify_url("https://open.spotify.com/playlist/0OAWLZxZydBuXyVuCszKT?si=abc") ==
      ("playlist", "0OAWLZxZydBuXyVuCszKT"))
check("spotify: URI",
      parse_spotify_url("spotify:playlist:0OAWLZxZydBuXyVuCszKT") ==
      ("playlist", "0OAWLZxZydBuXyVuCszKT"))
check("track URL",
      parse_spotify_url("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC") ==
      ("track", "4uLU6hMCjMI75M1A2tKUQC"))
check("album URL",
      parse_spotify_url("https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3") ==
      ("album", "1DFixLWuPkv3KT3TnV35m3"))
check("intl playlist URL",
      parse_spotify_url("https://open.spotify.com/intl-id/playlist/0OAWLZxZydBuXyVuCszKT")[0] ==
      "playlist")
try:
    parse_spotify_url("https://example.com/notspotify")
    check("rejects non-spotify URL", False)
except ServiceError:
    check("rejects non-spotify URL", True)
try:
    parse_spotify_url("")
    check("rejects empty URL", False)
except ServiceError:
    check("rejects empty URL", True)


# ------------------------------------------------------------- query builder
print("\n[query builder]")
t = Track(data="x", title="Sign of the Times", artist="Harry Styles")
check("basic query", build_query(t) == "Harry Styles Sign of the Times official audio",
      f"got {build_query(t)!r}")
t2 = Track(data="x", title="Closer", artist="The Chainsmokers, Halsey")
check("uses primary artist only", build_query(t2).startswith("The Chainsmokers Closer"),
      f"got {build_query(t2)!r}")
t3 = Track(data="x", title="Some Song", artist="")
check("handles empty artist", "Some Song" in build_query(t3))


# -------------------------------------------------------------- match scoring
print("\n[match scoring]")
want = 341
official = {"title": "Harry Styles - Sign of the Times (Official Video)",
            "duration": 341, "view_count": 900_000_000}
live = {"title": "Sign of the Times (Live at MSG)", "duration": 420, "view_count": 500_000}
cover = {"title": "Sign of the Times (Cover)", "duration": 340, "view_count": 10_000}
sped = {"title": "Sign of the Times (Sped Up)", "duration": 280, "view_count": 2_000_000}
exact = {"title": "Harry Styles - Sign of the Times", "duration": 342, "view_count": 50_000}

check("official video scores highest",
      score_candidate(official, want) > score_candidate(exact, want) >
      score_candidate(cover, want))
check("live version rejected (duration drift)",
      score_candidate(live, want) < 0)
check("sped up rejected", score_candidate(sped, want) < 0)
check("cover penalised", score_candidate(cover, want) < score_candidate(exact, want))
check("drift boundary respected",
      score_candidate({"title": "x", "duration": want + MAX_DURATION_DRIFT_S + 1,
                       "view_count": 0}, want) < 0)
check("no duration still scores", score_candidate({"title": "x", "duration": 0}, want) > 0)


# ------------------------------------------------------------------ provider
print("\n[provider wiring]")
p = make_provider(ProviderId.YOUTUBE.value)
check("registered in make_provider", p.provider == ProviderId.YOUTUBE)
check("name is set", p.name == "YouTube (yt-dlp)")
check("prefetched_urls is False", p.prefetched_urls is False)
check("has load_tracks", callable(getattr(p, "load_tracks", None)))
check("has resolve_track", callable(getattr(p, "resolve_track", None)))


# ------------------------------------------------------------------- fetcher
print("\n[LocalCopyFetcher]")
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = td / "src.mp3"
    src.write_bytes(b"ID3" + b"\x00" * 100)
    dest = td / "out" / "dest.mp3"

    f = LocalCopyFetcher()
    f.fetch(str(src), dest)
    check("copies local file", dest.exists() and dest.stat().st_size > 0)
    check("source consumed (moved)", not src.exists())

    # existing dest is left alone
    dest.write_bytes(b"ID3" + b"\x00" * 50)
    before = dest.stat().st_size
    src2 = td / "src2.mp3"
    src2.write_bytes(b"ID3" + b"\x00" * 999)
    f.fetch(str(src2), dest)
    check("does not overwrite existing", dest.stat().st_size == before)

    # missing source raises
    try:
        f.fetch(str(td / "nope.mp3"), td / "x.mp3")
        check("missing source raises", False)
    except Exception:
        check("missing source raises", True)

    # empty source raises
    empty = td / "empty.mp3"
    empty.write_bytes(b"")
    try:
        f.fetch(str(empty), td / "y.mp3")
        check("empty source raises", False)
    except Exception:
        check("empty source raises", True)


print(f"\nPASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
