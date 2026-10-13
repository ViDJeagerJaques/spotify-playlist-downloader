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


# ------------------------------------------------- official channel preference
# Real-world failure this guards: a Joji track resolved to a video on the
# channel "Ayli" because the title mentioned Joji and had more views.
print("\n[official channel]")
from providers.youtube import (                                     # noqa: E402
    VERIFY_PROBE_LIMIT,
    artist_name_variants,
    channel_match_strength,
    channel_matches_artist,
    is_lyrics_channel,
)

check("artist name matches own channel", channel_matches_artist("Joji", "Joji"))
check("VEVO suffix still matches", channel_matches_artist("Adele", "AdeleVEVO"))
check("case insensitive", channel_matches_artist("REALITY CLUB", "Reality Club"))
check("trailing space ignored", channel_matches_artist("Lana Del Rey ", "Lana Del Rey"))
check("accents folded", channel_matches_artist("Beyonc\u00e9", "Beyonce"))
check("non-latin preserved", channel_matches_artist(
    "\ubc29\ud0c0\uc18d\ub144\ub2e8", "\ubc29\ud0c0\uc18d\ub144\ub2e8"))
check("label channel does NOT match", not channel_matches_artist("HYBE LABELS", "BTS"))
check("lyric channel does NOT match", not channel_matches_artist("Indolirik", "Joji"))
check("exact match stronger than substring",
      channel_match_strength("Taylor Swift", "Taylor Swift") >
      channel_match_strength("Taylor Swift Audios", "Taylor Swift"))
check("short names need equality", not channel_matches_artist("MV", "M"))
check("multi-artist splits",
      "don toliver" in artist_name_variants("Don Toliver, Doja Cat") and
      "doja cat" in artist_name_variants("Don Toliver, Doja Cat"))
check("feat. splits", "lana del rey" in artist_name_variants(
      "Taylor Swift feat. Lana Del Rey"))
check("lyric channel detected", is_lyrics_channel("Indolirik")
      and is_lyrics_channel("7clouds - Topic"))

_dur = 222
ayli = {"channel": "Ayli", "uploader": "Ayli",
        "title": "Glimpse of Us by Joji but it will change your life",
        "duration": _dur, "view_count": 8_000_000}
joji = {"channel": "Joji", "uploader": "Joji",
        "title": "Joji - Glimpse of Us (Official Video)",
        "duration": _dur, "view_count": 20_000_000,
        "channel_is_verified": True}
indolirik = {"channel": "Indolirik", "uploader": "Indolirik",
             "title": "Joji \u2013 Glimpse of Us | Lirik Terjemahan",
             "duration": _dur, "view_count": 30_000_000,
             "channel_is_verified": True}
latin_hype = {"channel": "LatinHype", "uploader": "LatinHype",
              "title": "Joji - Glimpse Of Us", "duration": _dur,
              "view_count": 400_000}

check("artist's own channel beats the wrong channel",
      score_candidate(joji, _dur, "Joji") > score_candidate(ayli, _dur, "Joji"))
check("verified lyric channel loses to the artist's own channel",
      score_candidate(joji, _dur, "Joji") > score_candidate(indolirik, _dur, "Joji"),
      f"{score_candidate(joji, _dur, 'Joji')} vs "
      f"{score_candidate(indolirik, _dur, 'Joji')}")
check("verified lyric channel loses even with more views",
      score_candidate(joji, _dur, "Joji") > score_candidate(indolirik, _dur, "Joji"))
check("wrong channel still loses to any matched channel",
      score_candidate(joji, _dur, "Joji") > score_candidate(latin_hype, _dur, "Joji"))
check("multi-artist matches the primary artist",
      score_candidate({"channel": "Don Toliver", "title": "x", "duration": 200},
                      200, "Don Toliver, Doja Cat") >
      score_candidate({"channel": "Some Fan Page", "title": "x", "duration": 200},
                      200, "Don Toliver, Doja Cat"))
check("verified badge alone is not enough",
      score_candidate(indolirik, _dur, "Joji") < score_candidate(latin_hype, _dur, "Joji"),
      "lyric penalty must outweigh the +3 verified bonus")
check("official lyric video by the artist is not penalised",
      score_candidate({"channel": "Tulus", "title": "Monokrom (Official Lyric Video)",
                       "duration": 240}, 240, "Tulus") >
      score_candidate({"channel": "MUSICS", "title": "Monokrom (lyrics)",
                       "duration": 240}, 240, "Tulus"))
check("fan reupload channel loses to the exact channel",
      score_candidate({"channel": "Taylor Swift", "title": "Blank Space",
                       "duration": 232}, 232, "Taylor Swift") >
      score_candidate({"channel": "Taylor Swift Audios", "title": "Blank Space (Audio)",
                       "duration": 232}, 232, "Taylor Swift"))
check("artist omitted stays backwards compatible",
      score_candidate(ayli, _dur) > 0 and score_candidate(joji, _dur) > 0)
check("empty artist never matches anything",
      channel_match_strength("Anything", "") == 0.0)
check("empty channel never matches anything",
      channel_match_strength("", "Joji") == 0.0)
check("drift still rejects even the artist's own channel",
      score_candidate({**joji, "duration": _dur + 200}, _dur, "Joji") < 0)
check("probe limit stays small", VERIFY_PROBE_LIMIT <= 3)


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
