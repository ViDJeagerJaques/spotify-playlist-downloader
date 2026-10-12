"""Tests for per-track album cover resolution (#7).

The public embed page exposes only ONE image for the whole playlist, so without
this every track shows the same artwork. The real per-album art comes from
``GET /tracks/{id}`` (the batch variant ``?ids=`` is rejected with 403).

Everything here is offline: the HTTP layer is stubbed and the on-disk cache is
redirected to a temp dir. The API is never called.

Run:  python tests/test_covers.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import providers.spotify_embed as se  # noqa: E402
import providers.spotify_meta as sm  # noqa: E402
import providers.spotify_spclient as sc  # noqa: E402
from providers.base import ResolveResult, ServiceError, Track  # noqa: E402
from ui import data as ui_data  # noqa: E402

REAL_SPOTIFY_META = sm.SpotifyMeta

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


CDN = "https://i.scdn.co/image/ab67616d0000b273"


def _track_payload(tid: str) -> dict:
    return {
        "id": tid,
        "name": f"Track {tid}",
        "album": {"name": f"Album {tid}", "images": [
            {"url": f"{CDN}{tid}", "height": 640, "width": 640},
            {"url": f"{CDN}{tid}-small", "height": 64, "width": 64},
        ]},
    }


class StubMeta(sm.SpotifyMeta):
    """SpotifyMeta with the network replaced by a canned response table."""

    def __init__(self, responses: dict):
        # Skip credentials()/token: we never touch the network.
        self._cid, self._secret = "stub", "stub"
        self._token, self._token_expiry = "stub", 0.0
        self._prefer = "api"
        self._responses = responses
        self.calls: list[str] = []

    def _get(self, path, params=None):
        self.calls.append(path)
        if path.startswith("/tracks/"):
            tid = path.split("/tracks/", 1)[1]
            if tid in self._responses:
                value = self._responses[tid]
                if isinstance(value, Exception):
                    raise value
                return value
            raise ServiceError(f"404 {tid}")
        raise ServiceError(f"unexpected path {path}")


def test_cover_largest_image_wins():
    """images[] is largest-first; we must take the biggest, not the last."""
    m = StubMeta({"A": _track_payload("A")})
    check("cover: single track", m.track_covers(["A"]) == {"A": f"{CDN}A"})
    m2 = StubMeta({"B": _track_payload("B")})
    got = m2.track_covers(["B"])
    check("cover: prefers 640px over 64px", got["B"] == f"{CDN}B", str(got))


def test_many_covers_parallel():
    """All ids resolved, and failures are skipped rather than raised."""
    responses = {}
    for i in range(20):
        tid = f"t{i:02d}"
        responses[tid] = _track_payload(tid)
    responses["t05"] = ServiceError("region lock")
    responses["t11"] = ServiceError("deleted")

    m = StubMeta(responses)
    got = m.track_covers(list(responses.keys()), workers=8)
    check("cover: 18 of 20 resolved", len(got) == 18, str(len(got)))
    check("cover: failures skipped not raised", "t05" not in got and "t11" not in got)
    check("cover: all ids requested", len(m.calls) == 20, str(len(m.calls)))


def test_worker_cap_is_respected():
    """Spotify must not be hammered: workers are capped at MAX_COVER_WORKERS."""
    import threading

    peak = 0
    live = 0
    guard = threading.Lock()

    class SlowMeta(StubMeta):
        def _get(self, path, params=None):
            nonlocal peak, live
            with guard:
                live += 1
                peak = max(peak, live)
            import time
            time.sleep(0.02)
            with guard:
                live -= 1
            tid = path.split("/tracks/", 1)[1]
            return _track_payload(tid)

    m = SlowMeta({})
    ids = [f"s{i}" for i in range(24)]
    got = m.track_covers(ids, workers=64)   # deliberately absurd
    check("cover: all resolved despite bad worker count", len(got) == 24, str(len(got)))
    check("cover: concurrency capped at 8", peak <= sm.MAX_COVER_WORKERS,
          f"peak={peak} cap={sm.MAX_COVER_WORKERS}")


def test_missing_images_key_is_safe():
    """A track with no album/images must not crash the lookup."""
    m = StubMeta({"X": {"id": "X", "name": "X", "album": {}},
                  "Y": {"id": "Y", "name": "Y"},
                  "Z": {"id": "Z", "name": "Z", "album": {"images": []}}})
    got = m.track_covers(["X", "Y", "Z"])
    check("cover: no images -> empty result", got == {}, str(got))


def test_empty_input():
    m = StubMeta({})
    check("cover: empty list", m.track_covers([]) == {})
    check("cover: None-ish entries skipped", m.track_covers(["", None]) == {})


def test_track_covers_never_raises_on_bad_payload():
    """A non-dict album must be ignored, not explode."""

    class Weird(StubMeta):
        def _get(self, path, params=None):
            return {"id": "W", "album": "not-a-dict"}

    got = Weird({}).track_covers(["W"])
    check("cover: non-dict album ignored", got == {}, str(got))


# ----------------------------------------------------------------- caching
def test_cover_cache_roundtrip(tmp: Path):
    """The metadata+cover cache used by the playlist path."""
    orig_cache_path = sc._cache_path
    sc._cache_path = lambda name: tmp / f"{name}.json"
    try:
        check("cache: empty at first", sc.load_cache("tracks") == {})
        sc.save_cache("tracks", {"a": {"title": "A", "cover": "u1"},
                                 "b": {"title": "B", "cover": "u2"}})
        check("cache: persisted", (tmp / "tracks.json").exists())
        check("cache: reloaded", set(sc.load_cache("tracks")) == {"a", "b"})
        sc.save_cache("tracks", {"a": {"title": "A", "cover": "u1"},
                                 "b": {"title": "B", "cover": "u2"},
                                 "c": {"title": "C", "cover": "u3"}})
        check("cache: merged on disk", set(sc.load_cache("tracks")) == {"a", "b", "c"})
    finally:
        sc._cache_path = orig_cache_path


def test_broken_cache_is_ignored(tmp: Path):
    original = sc._cache_path
    broken = tmp / "broken.json"
    broken.write_text("{not json at all", encoding="utf-8")
    sc._cache_path = lambda name: broken
    try:
        check("cache: corrupt file ignored", sc.load_cache("tracks") == {})
    finally:
        sc._cache_path = original


def test_fetch_album_covers_uses_cache(tmp: Path):
    """Second call must not re-request anything already cached."""
    orig_cache_path = sc._cache_path
    sc._cache_path = lambda name: tmp / "cachehit" / f"{name}.json"
    try:
        sc.save_cache("tracks", {"A": {"title": "A", "artists": ["X"],
                                       "duration_ms": 1, "cover": f"{CDN}A"}})

        # fetch_album_covers now goes through the anonymous embed/oEmbed chain
        # (api.spotify.com is forbidden for playlists — it 429s). Stub THAT.
        orig_details = sc.track_details
        seen = []

        def spy(ids, workers=8, progress=None):
            seen.append(list(ids))
            return {tid: {"title": tid, "artists": ["A"], "duration_ms": 1,
                          "cover": f"{CDN}{tid}"} for tid in ids}

        sc.track_details = spy
        try:
            got = se.fetch_album_covers(["A", "B"])
            check("cache: cache hit + one fresh fetch",
                  got == {"A": f"{CDN}A", "B": f"{CDN}B"}, str(got))
            check("cache: only the miss was requested", seen == [["B"]], str(seen))

            seen.clear()
            got2 = se.fetch_album_covers(["A", "B"])
            check("cache: fully cached makes no request", seen == [], str(seen))
            check("cache: same result from cache", got2 == got, str(got2))
        finally:
            sc.track_details = orig_details
    finally:
        sc._cache_path = orig_cache_path


def test_fetch_album_covers_without_credentials(tmp: Path):
    """No .env / no network -> empty mapping (caller keeps the playlist cover)."""
    orig_cache_path = sc._cache_path
    sc._cache_path = lambda name: tmp / "boom" / f"{name}.json"
    orig_details = sc.track_details
    sc.track_details = _boom
    try:
        got = se.fetch_album_covers(["A", "B"])
        check("cover: lookup failure -> empty, no crash", got == {}, str(got))
    finally:
        sc.track_details = orig_details
        sc._cache_path = orig_cache_path


def _boom(ids, workers=8, progress=None):
    raise RuntimeError("network down")


def test_fetch_album_covers_dedupes_ids(tmp: Path):
    orig_cache_path = sc._cache_path
    sc._cache_path = lambda name: tmp / "dedup" / f"{name}.json"
    orig_details = sc.track_details
    seen = []

    def spy(ids, workers=8, progress=None):
        seen.append(list(ids))
        return {tid: {"title": tid, "artists": ["A"], "duration_ms": 1,
                      "cover": f"{CDN}{tid}"} for tid in ids}

    sc.track_details = spy
    try:
        got = se.fetch_album_covers(["D", "D", "D"])
        check("cover: duplicate ids requested once", seen == [["D"]], str(seen))
        check("cover: duplicates collapse in result", got == {"D": f"{CDN}D"}, str(got))
    finally:
        sc.track_details = orig_details
        sc._cache_path = orig_cache_path


# ----------------------------------------------------------------- ui glue
def test_apply_track_covers_replaces_playlist_image():
    result = ResolveResult(title="P", source_url="u", tracks=[
        Track(data="a", track_token="a", title="A", thumbnail="https://playlist/img"),
        Track(data="b", track_token="b", title="B", thumbnail="https://playlist/img"),
    ])
    view = ui_data.playlist_view(result)
    check("ui: starts with shared playlist image",
          view["tracks"][0]["cover"] == "https://playlist/img")

    n = ui_data.apply_track_covers(view, {"a": f"{CDN}a"})
    check("ui: replaced count", n == 1, str(n))
    check("ui: track a got its own cover", view["tracks"][0]["cover"] == f"{CDN}a")
    check("ui: track b keeps playlist cover",
          view["tracks"][1]["cover"] == "https://playlist/img")


def test_apply_track_covers_noop_on_empty():
    check("ui: empty covers no-op", ui_data.apply_track_covers({"tracks": []}, {}) == 0)
    check("ui: empty view no-op", ui_data.apply_track_covers({}, {"a": "u"}) == 0)


def test_playlist_view_accepts_covers_directly():
    result = ResolveResult(title="P", source_url="u", tracks=[
        Track(data="a", track_token="a", title="A", thumbnail="old"),
    ])
    view = ui_data.playlist_view(result, {"a": f"{CDN}a"})
    check("ui: covers at build time", view["tracks"][0]["cover"] == f"{CDN}a")


def test_playlist_view_total_duration():
    result = ResolveResult(title="P", source_url="u", tracks=[
        Track(data="a", track_token="a", title="A", duration_ms=60_000),
        Track(data="b", track_token="b", title="B", duration_ms=30_000),
    ])
    view = ui_data.playlist_view(result)
    check("ui: total duration summed", view["total_duration_ms"] == 90_000,
          str(view["total_duration_ms"]))


def test_embed_page_has_owner_and_duration():
    """The embed page already carries these — assert we can read them."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "playlist_100.json"
    if not fixture.exists():
        return
    entity = json.loads(fixture.read_text(encoding="utf-8"))
    owner = str(entity.get("subtitle") or "").strip()
    dur = sum(int(t.get("duration") or 0) for t in entity.get("trackList") or [])
    check("embed: owner readable", owner != "", f"owner={owner!r}")
    check("embed: total duration computed", dur > 0, str(dur))
    check("embed: 100 items summed", len(entity.get("trackList") or []) == 100)


def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_cover_largest_image_wins()
        test_many_covers_parallel()
        test_worker_cap_is_respected()
        test_missing_images_key_is_safe()
        test_empty_input()
        test_track_covers_never_raises_on_bad_payload()
        test_cover_cache_roundtrip(tmp)
        test_broken_cache_is_ignored(tmp)
        test_fetch_album_covers_uses_cache(tmp)
        test_fetch_album_covers_without_credentials(tmp)
        test_fetch_album_covers_dedupes_ids(tmp)
    test_apply_track_covers_replaces_playlist_image()
    test_apply_track_covers_noop_on_empty()
    test_playlist_view_accepts_covers_directly()
    test_playlist_view_total_duration()
    test_embed_page_has_owner_and_duration()

    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()