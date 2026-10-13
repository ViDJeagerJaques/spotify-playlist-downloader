"""Offline tests for the YouTube provider — no network, no credentials needed.

Run:  .venv/Scripts/python.exe tests/test_youtube.py
"""
from __future__ import annotations

import os
import sys
import time
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


# ----------------------------------------------------------- cache behaviour
# Offline: no network, no ffmpeg. The point is the freshness policy, which is
# what makes an improved scoring function actually take effect.
print("\n[cache]")
import shutil  # noqa: E402
import tempfile  # noqa: E402
from providers import youtube as yt  # noqa: E402
from providers.base import cache_dir  # noqa: E402

_real_cache = yt.CACHE_DIR
_scratch = Path(tempfile.mkdtemp(prefix="yt_cache_test_"))
yt.CACHE_DIR = _scratch
yt.SCRATCH_DIR = _scratch
try:
    # Cache lives beside the project, never in the system temp folder.
    check("cache default is next to the project, not AppData",
          "appdata" not in str(cache_dir()).lower()
          and cache_dir().name == ".cache")
    prev = os.environ.get("SPOTIFY_CACHE_DIR")
    os.environ["SPOTIFY_CACHE_DIR"] = str(_scratch)
    try:
        check("cache honours SPOTIFY_CACHE_DIR", cache_dir() == _scratch)
    finally:
        if prev is None:
            os.environ.pop("SPOTIFY_CACHE_DIR", None)
        else:
            os.environ["SPOTIFY_CACHE_DIR"] = prev

    mp3 = _scratch / "abc.mp3"
    mp3.write_bytes(b"ID3" + bytes(2048))

    check("mp3 without sidecar counts as stale",
          yt.read_resolution(mp3) is None)

    yt.write_resolution(mp3, {"id": "ZEY9UCzzbcQ", "channel": "Joji",
                               "title": "Sanctuary", "duration": 180},
                        Track(data="x", title="Sanctuary", artist="Joji"), 180)
    rec = yt.read_resolution(mp3)
    check("sidecar records the chosen video", rec is not None
          and rec.get("video_id") == "ZEY9UCzzbcQ")
    check("sidecar records the channel", rec.get("channel") == "Joji")
    check("sidecar records duration", rec.get("duration") == 180)
    check("sidecar has a timestamp", bool(rec.get("resolved_at")))

    yt.sidecar_path(mp3).write_text("{not json", encoding="utf-8")
    check("corrupt sidecar also counts as stale",
          yt.read_resolution(mp3) is None)

    # A stale mp3 must actually be re-resolved, and a fresh one must not be.
    yt.RESOLVE_STATS.update({"cache_hit": 0, "cache_stale": 0})
    picked: list = []
    orig_pick = yt.YouTubeClient._pick_best
    orig_dl = yt.YouTubeClient._download

    def fake_pick(query, want, artist=""):
        picked.append(query)
        return {"id": "NEW1", "channel": "Joji", "title": "Sanctuary",
                "duration": 180}

    def fake_dl(cand, dest, track):
        Path(dest).write_bytes(b"ID3" + bytes(4096))

    yt.YouTubeClient._pick_best = staticmethod(fake_pick)
    yt.YouTubeClient._download = staticmethod(fake_dl)
    try:
        client = yt.YouTubeClient()
        t = Track(data="x", track_token="abc", title="Sanctuary",
                  artist="Joji", duration_ms=180000)

        client.resolve_track(t)
        check("stale cache triggers a re-resolve", len(picked) == 1
              and yt.RESOLVE_STATS["cache_stale"] == 1)
        check("re-resolve writes the sidecar",
              yt.read_resolution(_scratch / "abc.mp3") is not None)

        client.resolve_track(t)
        check("fresh cache is reused without searching", len(picked) == 1
              and yt.RESOLVE_STATS["cache_hit"] == 1)

        yt.sidecar_path(_scratch / "abc.mp3").unlink()
        client.resolve_track(t)
        check("removing the sidecar makes it stale again", len(picked) == 2)

        # cleanup_cache must not nuke the user's downloads.
        client.resolve_track(t)
        before = yt.cache_usage()[1]
        client.cleanup_cache()
        check("cleanup_cache keeps the mp3 and sidecar",
              (_scratch / "abc.mp3").exists() and before > 0)

        # stale zip sweep
        old_zip = _scratch / "spl_old.zip"
        new_zip = _scratch / "spl_new.zip"
        for z in (old_zip, new_zip):
            z.write_bytes(b"PK\x03\x04")
        stale_mtime = time.time() - (yt.STALE_ZIP_MAX_AGE_S + 3600)
        os.utime(old_zip, (stale_mtime, stale_mtime))
        removed = yt.purge_stale_zips()
        check("stale zip (>24h) removed", removed == 1 and not old_zip.exists())
        check("fresh zip kept", new_zip.exists())

        files, total = yt.cache_usage()
        check("cache_usage counts files and bytes", files > 0 and total > 0)
        gone, freed = yt.clear_cache()
        check("clear_cache reports what it freed",
              gone == files and freed == total)
        check("clear_cache leaves an empty folder behind",
              _scratch.exists() and yt.cache_usage() == (0, 0))
    finally:
        yt.YouTubeClient._pick_best = orig_pick
        yt.YouTubeClient._download = orig_dl
finally:
    yt.CACHE_DIR = _real_cache
    shutil.rmtree(_scratch, ignore_errors=True)


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
