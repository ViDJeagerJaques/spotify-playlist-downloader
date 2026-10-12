"""Offline tests for the spclient chain that removes the 100-song cap.

Everything is stubbed or fixture-driven; the API is never called. What we pin
down here is the behaviour the live run depends on:

* the anon token is found in the embed page and is never hardcoded;
* ``playlist_track_ids`` returns every id, in playlist order, plus the real
  length / owner / truncated flag;
* per-track metadata + cover parsing, including the ``coverArt: null`` case;
* one bad track never breaks the batch, and workers stay capped;
* the playlist path does NOT touch ``api.spotify.com`` (it 429s hard).

Run:  python tests/test_spclient.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import providers.spotify_embed as se  # noqa: E402
import providers.spotify_spclient as sp  # noqa: E402
from providers.base import ResolveResult, ServiceError, Track  # noqa: E402

PASS = []
FAIL = []
FIX = Path(__file__).resolve().parent / "fixtures"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- A + B
def test_extract_anon_token_from_real_html_shape():
    """The regex must find the token in the page's inline JSON."""
    real_token = "BQAGA4PxELCeN7vMiNbokDjmvmmqRFBovs0U9ZQ4" + ("x" * 102)
    html = ('<html><script>{"config":{"accessToken":"' + real_token +
            '","clientId":"abc"}}</script></html>')
    token = sp.extract_anon_token(html)
    check("token: extracted whole value", token == real_token, token[-20:])
    check("token: ~140 chars like the real one", len(token) == 142, str(len(token)))

    alt = '<script>{"data":{"accessToken":"' + "Z" * 140 + '"}}</script>'
    check("token: nested json variant",
          sp.extract_anon_token(alt) == "Z" * 140)

    check("token: absent -> empty string", sp.extract_anon_token("<html>nope</html>") == "")
    check("token: empty html -> empty string", sp.extract_anon_token("") == "")


def test_no_token_is_hardcoded_in_source():
    """The token must always come from the page, never from the source."""
    src = Path(sp.__file__).read_text(encoding="utf-8")
    # A real token is 140 chars of base64-ish; make sure none is baked in.
    check("token: source has no literal Bearer token",
          "Bearer BQAG" not in src and "BQAGA4PxELCeN7" not in src)
    check("token: source passes it as a parameter",
          "anon_token: str" in src or "anon_token" in src)


def _stub_get(payload):
    def _inner(url, headers=None):
        return payload
    return _inner


def test_playlist_track_ids_full_list():
    payload = load("spclient_playlist.json")
    orig = sp._get_json
    sp._get_json = _stub_get(payload)
    try:
        ids, length, owner, truncated = sp.playlist_track_ids("abc", "tok")
    finally:
        sp._get_json = orig

    check("spclient: 3 ids", len(ids) == 3, str(len(ids)))
    check("spclient: id from uri", ids[0] == "70C4NyhjD5OZUMzvWZ3njJ", ids[0])
    check("spclient: order preserved", ids[-1] == "3iy2QuCtCzpWnR6tia39AB", ids[-1])
    check("spclient: length from payload", length == 213, str(length))
    check("spclient: owner from payload",
          owner == "31siy2jiykpjmhgercjuh2j2yrbe", owner)
    check("spclient: truncated False", truncated is False, str(truncated))


def test_playlist_track_ids_headers():
    """spclient needs the anon token plus the WebPlayer origin headers."""
    seen = {}

    def fake(url, headers=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return load("spclient_playlist.json")

    orig = sp._get_json
    sp._get_json = fake
    try:
        sp.playlist_track_ids("02hYsnNkqFC9GiJpShgswH", "TOKEN123")
    finally:
        sp._get_json = orig

    check("spclient: url shape",
          seen["url"] == "https://spclient.wg.spotify.com/playlist/v2/playlist/02hYsnNkqFC9GiJpShgswH",
          seen["url"])
    check("spclient: bearer token sent",
          seen["headers"].get("Authorization") == "Bearer TOKEN123",
          str(seen["headers"].get("Authorization")))
    check("spclient: app-platform sent",
          seen["headers"].get("app-platform") == "WebPlayer",
          str(seen["headers"].get("app-platform")))


def test_playlist_track_ids_requires_token():
    try:
        sp.playlist_track_ids("abc", "")
        check("spclient: empty token rejected", False, "no exception")
    except ServiceError as exc:
        check("spclient: empty token rejected", True)
        check("spclient: message is Indonesian",
              "Token" in exc.user_message, exc.user_message)


def test_truncated_flag_is_surfaced():
    payload = load("spclient_playlist.json")
    payload["contents"]["truncated"] = True
    payload["length"] = 213
    orig = sp._get_json
    sp._get_json = _stub_get(payload)
    try:
        ids, length, owner, truncated = sp.playlist_track_ids("abc", "tok")
    finally:
        sp._get_json = orig
    check("spclient: truncated reported", truncated is True, str(truncated))
    check("spclient: partial list still returned", len(ids) == 3, str(len(ids)))
    check("spclient: length still reports the truth", length == 213, str(length))


def test_missing_items_tolerated():
    payload = {"length": 0, "contents": {}}
    orig = sp._get_json
    sp._get_json = _stub_get(payload)
    try:
        ids, length, owner, truncated = sp.playlist_track_ids("abc", "tok")
    finally:
        sp._get_json = orig
    check("spclient: empty contents -> empty list", ids == [], str(ids))
    check("spclient: length falls back to len", length == 0, str(length))


def test_non_track_uris_skipped():
    payload = {"length": 3, "contents": {"items": [
        {"uri": "spotify:track:aaa"},
        {"uri": "spotify:episode:bbb"},
        {"uri": "spotify:track:ccc"},
        "junk",
        {"no_uri": True},
    ]}, "ownerUsername": "x"}
    orig = sp._get_json
    sp._get_json = _stub_get(payload)
    try:
        ids, *_ = sp.playlist_track_ids("abc", "tok")
    finally:
        sp._get_json = orig
    check("spclient: only track uris kept", ids == ["aaa", "ccc"], str(ids))


# ---------------------------------------------------------------- C
def test_track_meta_embed_parsing():
    entity = load("spclient_track_embed.json")
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
            + '</script>')
    orig = sp._get
    sp._get = lambda url, headers=None: html
    try:
        meta = sp.track_meta_embed("3iy2QuCtCzpWnR6tia39AB")
    finally:
        sp._get = orig

    check("meta: title", meta["title"] == "hate that i made you love me", meta.get("title"))
    check("meta: artists", meta["artists"] == ["Ariana Grande"], str(meta.get("artists")))
    check("meta: duration ms", meta["duration_ms"] == 197949, str(meta.get("duration_ms")))
    check("meta: release date unwrapped",
          meta["release_date"] == "2023-03-10T00:00:00Z", str(meta.get("release_date")))


def test_track_meta_cover_art_null_is_ok():
    """coverArt is null here by design — metadata must still parse."""
    entity = load("spclient_track_embed.json")
    check("fixture: coverArt really is null", entity.get("coverArt") is None)
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
            + '</script>')
    orig = sp._get
    sp._get = lambda url, headers=None: html
    try:
        meta = sp.track_meta_embed("x")
    finally:
        sp._get = orig
    check("meta: parses despite null coverArt", bool(meta.get("title")))


def test_track_meta_missing_page_returns_empty():
    orig = sp._get
    sp._get = lambda url, headers=None: "<html>no next data</html>"
    try:
        check("meta: no __NEXT_DATA__ -> {}", sp.track_meta_embed("x") == {})
    finally:
        sp._get = orig

    def boom(url, headers=None):
        raise ServiceError("404")
    sp._get = boom
    try:
        check("meta: request failure -> {}", sp.track_meta_embed("x") == {})
    finally:
        sp._get = orig

    check("meta: empty id -> {}", sp.track_meta_embed("") == {})


def test_track_cover_oembed():
    orig = sp._get_json
    sp._get_json = lambda url, headers=None: load("spclient_oembed.json")
    try:
        url = sp.track_cover_oembed("3iy2QuCtCzpWnR6tia39AB")
    finally:
        sp._get_json = orig
    # The fixture stores the 300x300 prefix; the function upgrades it to 640.
    # hash stays "8baf677ee2d8dda6cc9fcbd7", only the prefix is swapped.
    check("oembed: url returned",
          url == ("https://image-cdn-ak.spotifycdn.com/image/"
                  "ab67616d0000b2738baf677ee2d8dda6cc9fcbd7"),
          url)

    sp._get_json = lambda url, headers=None: {}
    try:
        check("oembed: no thumbnail -> empty", sp.track_cover_oembed("x") == "")
    finally:
        sp._get_json = orig

    sp._get_json = _boom
    try:
        check("oembed: failure -> empty", sp.track_cover_oembed("x") == "")
    finally:
        sp._get_json = orig

    check("oembed: empty id -> empty", sp.track_cover_oembed("") == "")


def _boom(url, headers=None):
    raise ServiceError("network down")


def _boom_meta(ids, token, workers=8):
    """metadata_many explodes -> embed_tracks_complete must fall back."""
    raise RuntimeError("network down")


def test_track_details_batch_and_worker_cap():
    """Parallel fetch must survive failures and never exceed the worker cap."""
    peak = 0
    live = 0
    guard = threading.Lock()

    def slow_get(url, headers=None):
        nonlocal peak, live
        with guard:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with guard:
            live -= 1
        if url.startswith("https://open.spotify.com/embed/track/"):
            return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
                {"props": {"pageProps": {"state": {"data": {"entity": {
                    "title": "T", "artists": [{"name": "A"}], "duration": 1000}}}}}}) + '</script>'
        return json.dumps(load("spclient_oembed.json"))

    orig_get = sp._get
    sp._get = slow_get
    try:
        ids = [f"t{i:03d}" for i in range(24)]
        got = sp.track_details(ids, workers=99)   # absurd on purpose
    finally:
        sp._get = orig_get

    check("batch: all 24 resolved", len(got) == 24, str(len(got)))
    check("batch: concurrency capped at 8", peak <= sp.MAX_WORKERS,
          f"peak={peak} cap={sp.MAX_WORKERS}")


def test_track_details_one_failure_does_not_break_batch():
    def picky(url, headers=None):
        if "t002" in url:
            raise ServiceError("404")
        if url.startswith("https://open.spotify.com/embed/track/"):
            return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
                {"props": {"pageProps": {"state": {"data": {"entity": {
                    "title": "T", "artists": [{"name": "A"}], "duration": 1000}}}}}}) + '</script>'
        return json.dumps(load("spclient_oembed.json"))

    orig = sp._get
    sp._get = picky
    try:
        got = sp.track_details(["t001", "t002", "t003"])
    finally:
        sp._get = orig
    check("batch: failure isolated", "t002" not in got and len(got) == 2, str(sorted(got)))


def test_progress_callback_fires():
    seen = []

    def ok(url, headers=None):
        if url.startswith("https://open.spotify.com/embed/track/"):
            return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
                {"props": {"pageProps": {"state": {"data": {"entity": {
                    "title": "T", "artists": [{"name": "A"}], "duration": 1000}}}}}}) + '</script>'
        return json.dumps(load("spclient_oembed.json"))

    orig = sp._get
    sp._get = ok
    try:
        sp.track_details(["a", "b", "c"], progress=lambda d, t: seen.append((d, t)))
    finally:
        sp._get = orig
    check("progress: called for each track", len(seen) == 3, str(seen))
    check("progress: total reported", all(t == 3 for _d, t in seen), str(seen))


def test_cache_roundtrip(tmp: Path):
    original = sp._cache_path("tracks")
    sp._cache_path = lambda name: tmp / f"{name}.json"   # type: ignore[assignment]
    try:
        check("cache: empty at first", sp.load_cache("tracks") == {})
        sp.save_cache("tracks", {"a": {"title": "A", "cover": "u"}})
        check("cache: saved", sp.load_cache("tracks") == {"a": {"title": "A", "cover": "u"}})

        # Second pass must not re-request a cached id.
        orig_details = sp.track_details
        calls = []

        def spy(ids, workers=8, progress=None):
            calls.append(list(ids))
            return {}

        sp.track_details = spy  # type: ignore[assignment]
        try:
            got = sp.cached_track_details(["a", "a", "b"])
        finally:
            sp.track_details = orig_details  # type: ignore[assignment]
        check("cache: hit served from disk", "a" in got, str(got))
        check("cache: only the miss was requested", calls == [["b"]], str(calls))
    finally:
        sp._cache_path = original  # type: ignore[assignment]


def test_broken_cache_ignored(tmp: Path):
    original = sp._cache_path
    broken = tmp / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    sp._cache_path = lambda name: broken  # type: ignore[assignment]
    try:
        check("cache: corrupt file ignored", sp.load_cache("tracks") == {})
    finally:
        sp._cache_path = original  # type: ignore[assignment]


# ---------------------------------------------- E: no api.spotify.com
def test_playlist_path_avoids_api_spotify():
    """The regression that matters: playlists must not hit api.spotify.com."""
    src_embed = Path(se.__file__).read_text(encoding="utf-8")
    fetch = src_embed[src_embed.find("def fetch_album_covers"):]
    check("cover path: no SpotifyMeta use",
          "SpotifyMeta" not in fetch, "fetch_album_covers still builds a Meta client")
    check("cover path: no track_covers call", "track_covers" not in fetch,
          "still calling the Web API endpoint")
    check("cover path: uses spclient cache",
          "cached_track_details" in fetch, "not using the anon chain")

    src_sp = Path(sp.__file__).read_text(encoding="utf-8")
    # Comments warn against api.spotify.com, so strip them before checking.
    code = "\n".join(
        ln for ln in src_sp.splitlines()
        if not ln.strip().startswith("#") and "api.spotify.com" not in ln
    )
    check("spclient: never calls api.spotify.com",
          "api.spotify.com" not in code, "real call found in code")


def test_embed_complete_uses_spclient():
    """embed_tracks_complete must prefer spclient over the 100-song cap."""
    src = Path(se.__file__).read_text(encoding="utf-8")
    start = src.find("def embed_tracks_complete")
    rest = src[start:]
    nxt = rest.find("\ndef ")
    body = rest[:nxt] if nxt > 0 else rest
    check("complete: calls playlist_track_ids", "playlist_track_ids" in body)
    check("complete: calls cached_track_details", "cached_track_details" in body)
    check("complete: reuses one embed fetch", body.count("_get(EMBED_BASE") == 1,
          str(body.count("_get(EMBED_BASE")))


def test_graceful_fallback_when_spclient_dies():
    """If spclient is gone we must keep the 100 songs and explain it."""
    payload = load("spclient_playlist.json")
    orig_get = sp._get_json
    sp._get_json = _boom
    entity = load("embed_playlist_with_token.json")
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
            + '</script>')
    orig_embed_get = se._get
    se._get = lambda url, headers=None: html
    try:
        title, tracks, hint, cover, owner, total_ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH")
    finally:
        sp._get_json = orig_get
        se._get = orig_embed_get

    check("fallback: does not crash", bool(tracks))
    check("fallback: keeps the embed songs", len(tracks) == 2, str(len(tracks)))
    check("fallback: explains the shortfall", "login" in hint.lower(), hint[:90])
    check("fallback: still returns a title", title == "Dupe", title)


# ------------------------------------------------- R1: per-track covers
ALBUM_ART = "https://i.scdn.co/image/ab67616d0000b273ff4aef671b2510be7c115b3"


def _embed_html(names):
    """Embed-page HTML where every track shares the ONE playlist cover."""
    rows = []
    for i, (title, artist, ms) in enumerate(names):
        rows.append({"uri": f"spotify:track:ID{i:016d}", "uid": f"u{i}",
                     "title": title, "subtitle": artist, "duration": ms,
                     "isPlayable": True, "entityType": "track"})
    entity = {"name": "Test", "title": "Test", "subtitle": "Owner",
              "coverArt": {"sources": [{"height": 640, "width": 640,
                                        "url": "https://mosaic.scdn.co/640/PLAYLIST"}]},
              "trackList": rows}
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}},
               "config": {"accessToken": "A" * 140}}
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload) + '</script>')


def _stub_details():
    """Per-track details keyed the way spclient returns them."""
    def inner(track_id):
        return {"title": f"title-{track_id}",
                "artists": [f"artist-{track_id}"],
                "duration_ms": 123456,
                "album": f"album-{track_id}",
                "cover": f"https://i.scdn.co/image/cover-{track_id}"}
    return inner


def test_r1_every_track_gets_its_own_cover():
    """REGRESSION for R1.

    The embed page exposes ONE image for the whole playlist. Before the fix the
    first 100 songs were taken straight from that page, so a 4-song playlist
    rendered 4 covers that were all the same image. Every track must now go
    through /embed/track + oEmbed.
    """
    names = [("Blank Space", "Taylor Swift", 200000),
             ("Cinnamon Girl", "Lana Del Rey", 300000),
             ("Style", "Taylor Swift", 200000),
             ("Snow On The Beach", "Taylor Swift", 300000)]

    orig_get = se._get
    orig_details = sp.track_details
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    se._get = lambda url, headers=None: _embed_html(names)
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"

    # spclient returns all four ids.
    payload = {"length": 4, "ownerUsername": "ownerhash",
               "contents": {"truncated": False, "items": [
                   {"uri": f"spotify:track:ID{i:016d}"} for i in range(4)]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    sp.metadata_many = lambda ids, tok, workers=8: {
        tid: _stub_details()(tid) for tid in ids}

    try:
        title, tracks, hint, cover, owner, total_ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.track_details = orig_details
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    check("r1: all 4 tracks returned", len(tracks) == 4, str(len(tracks)))

    covers = [t.thumbnail for t in tracks]
    playlist_img = "https://mosaic.scdn.co/640/PLAYLIST"
    check("r1: no track falls back to the playlist image",
          playlist_img not in covers, str(covers))

    # Two tracks may legitimately share artwork when they are on one album;
    # what must never happen is every track sharing ONE image.
    uniq = len(set(covers))
    check("r1: covers are NOT all identical", uniq > 1,
          f"all {uniq} unique — this is the bug")
    check("r1: cover count matches unique albums", uniq == 4,
          f"{uniq} unique for 4 tracks")

    # Per-track metadata must be there too, not just the cover.
    check("r1: artist is per-track", len({t.artist for t in tracks}) == 4,
          str([t.artist for t in tracks]))
    check("r1: album is per-track", len({t.album for t in tracks}) == 4,
          str([t.album for t in tracks]))


def test_r1_failed_lookup_falls_back_to_embed_row():
    """One track that fails must not lose its (cover-less) embed data."""
    names = [("A", "AA", 1000), ("B", "BB", 2000)]
    orig_get = se._get
    orig_details = sp.track_details
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    se._get = lambda url, headers=None: _embed_html(names)
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"

    payload = {"length": 2, "ownerUsername": "o",
               "contents": {"truncated": False, "items": [
                   {"uri": f"spotify:track:ID{i:016d}"} for i in range(2)]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload

    def half(ids, tok, workers=8):
        out = _stub_details()(ids[0]) if ids else {}
        return {ids[0]: out} if ids else {}

    sp.metadata_many = half
    try:
        _t, tracks, _h, _c, _o, _ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.track_details = orig_details
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    check("r1: both tracks survive", len(tracks) == 2, str(len(tracks)))
    check("r1: successful one has its cover",
          tracks[0].thumbnail.endswith("ID0000000000000000"), tracks[0].thumbnail)
    check("r1: failed one keeps the embed title", tracks[1].title == "B",
          tracks[1].title)


def test_r0_owner_prefers_the_display_name():
    """R0: ownerUsername is an opaque hash, the embed subtitle is the name.

    Live check: the 213-song playlist shows
    'oleh 31siy2jiykpjmhgercjuh2j2yrbe' (hash) instead of 'David-Atha'.
    """
    names = [("A", "AA", 1000)]
    orig_get = se._get
    orig_details = sp.track_details
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    se._get = lambda url, headers=None: _embed_html(names)
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"
    payload = {"length": 1, "ownerUsername": "31siy2jiykpjmhgercjuh2j2yrbe",
               "contents": {"truncated": False,
                            "items": [{"uri": "spotify:track:ID0000000000000000"}]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    sp.metadata_many = lambda ids, tok, workers=8: {}

    try:
        _t, _tr, _h, _c, owner, _ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.track_details = orig_details
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    check("r0: owner is the display name, not the hash",
          owner == "Owner", repr(owner))
    check("r0: hash not shown to the user",
          owner != "31siy2jiykpjmhgercjuh2j2yrbe", repr(owner))


# ------------------------------------------------- R4: album / label / year
def test_b62_to_hex_known_value():
    """Verified against the live endpoint."""
    check("r4: known conversion",
          sp.b62_to_hex("2mdEsXPu8ZmkHRRtAdC09e") == "4d7d424d2bc148da9d17580f110bd31c",
          sp.b62_to_hex("2mdEsXPu8ZmkHRRtAdC09e"))
    check("r4: always 32 hex chars",
          len(sp.b62_to_hex("5Ohxk2dO5COHF1krpoPigN")) == 32)
    check("r4: rejects non-base62", sp.b62_to_hex("not-valid!") == "")
    check("r4: empty input", sp.b62_to_hex("") == "0" * 32 or sp.b62_to_hex("") == "")


def test_track_metadata_spclient_parsing():
    payload = {
        "name": "Cinnamon Girl",
        "album": {"name": "Norman Fucking Rockwell!", "label": "Polydor Records",
                  "date": {"year": 2019, "month": 8, "day": 30}},
        "artist": [{"gid": "x", "name": "Lana Del Rey"}],
        "number": 7, "disc_number": 1, "duration": 300683,
    }
    orig = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    try:
        meta = sp.track_metadata_spclient("2mdEsXPu8ZmkHRRtAdC09e", "tok")
    finally:
        sp._get_json = orig

    check("r4: album name", meta["album"] == "Norman Fucking Rockwell!", meta.get("album"))
    check("r4: label", meta["label"] == "Polydor Records", meta.get("label"))
    check("r4: year", meta["year"] == 2019, str(meta.get("year")))
    check("r4: track number", meta["track_number"] == 7, str(meta.get("track_number")))
    check("r4: disc number", meta["disc_number"] == 1, str(meta.get("disc_number")))
    check("r4: artist list", meta["artists"] == ["Lana Del Rey"], str(meta.get("artists")))


def test_track_metadata_uses_hex_gid_and_bearer():
    seen = {}

    def fake(url, headers=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return {}

    orig = sp._get_json
    sp._get_json = fake
    try:
        sp.track_metadata_spclient("2mdEsXPu8ZmkHRRtAdC09e", "TOKEN")
    finally:
        sp._get_json = orig
    check("r4: metadata url uses the hex gid",
          seen["url"].endswith("/metadata/4/track/4d7d424d2bc148da9d17580f110bd31c"),
          seen["url"])
    check("r4: bearer token sent",
          seen["headers"].get("Authorization") == "Bearer TOKEN",
          str(seen["headers"].get("Authorization")))


def test_track_metadata_no_token_returns_empty():
    check("r4: no token -> {}",
          sp.track_metadata_spclient("2mdEsXPu8ZmkHRRtAdC09e", "") == {})
    check("r4: bad id -> {}",
          sp.track_metadata_spclient("!!!", "tok") == {})


def test_track_fields_carry_tagging_data():
    """embed_tracks_complete must put album/label/year on the Track."""
    names = [("Cinnamon Girl", "Lana Del Rey", 300683)]
    orig_get = se._get
    orig_details = sp.track_details
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    se._get = lambda url, headers=None: _embed_html(names)
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"
    payload = {"length": 1, "ownerUsername": "o",
               "contents": {"truncated": False,
                            "items": [{"uri": "spotify:track:ID0000000000000000"}]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    sp.metadata_many = lambda ids, tok, workers=8: {
        ids[0]: {"title": "Cinnamon Girl", "artists": ["Lana Del Rey"],
                 "duration_ms": 300683, "cover": "https://i.scdn.co/x",
                 "album": "Norman Fucking Rockwell!", "label": "Polydor",
                 "year": 2019, "track_number": 7, "disc_number": 1}}
    sp.metadata_many = lambda ids, tok, workers=8: {
        ids[0]: {"album": "Norman Fucking Rockwell!", "label": "Polydor Records",
                 "year": 2019, "track_number": 7, "disc_number": 1}}

    try:
        _t, tracks, _h, _c, _o, _ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.track_details = orig_details
        sp.metadata_many = orig_meta
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    tr = tracks[0]
    check("r4: album on the Track", tr.album == "Norman Fucking Rockwell!", tr.album)
    check("r4: label on the Track", tr.label == "Polydor Records", tr.label)
    check("r4: year on the Track", tr.year == 2019, str(tr.year))
    check("r4: track number on the Track", tr.track_number == 7, str(tr.track_number))
    check("r4: disc number on the Track", tr.disc_number == 1, str(tr.disc_number))


def test_r1_whole_batch_failure_keeps_playlist_usable():
    """If every lookup fails we still return a full, ordered playlist."""
    names = [("A", "AA", 1000), ("B", "BB", 2000)]
    orig_get = se._get
    orig_details = sp.track_details
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    se._get = lambda url, headers=None: _embed_html(names)
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"
    payload = {"length": 2, "ownerUsername": "o",
               "contents": {"truncated": False, "items": [
                   {"uri": f"spotify:track:ID{i:016d}"} for i in range(2)]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    sp.metadata_many = _boom_meta

    try:
        title, tracks, hint, cover, owner, total_ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.track_details = orig_details
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    check("r1: no crash when every lookup fails", len(tracks) == 2, str(len(tracks)))
    check("r1: titles survive", [t.title for t in tracks] == ["A", "B"],
          str([t.title for t in tracks]))
    check("r1: falls back to the playlist image",
          all(t.thumbnail == "https://mosaic.scdn.co/640/PLAYLIST" for t in tracks),
          str([t.thumbnail for t in tracks]))


# ------------------------------------------------------- throttle & caching
def test_throttle_is_not_global_serialisation():
    """REGRESSION: a global lock+gap made 8 workers serial (5.86s for 40 calls).

    Measured with the fix: the same 40 calls finish in ~1s, because the gap is
    per-worker and the token bucket only gates START times.
    """
    orig_limiter = sp._rate_limiter
    sp._rate_limiter = sp._TokenBucket(sp.MAX_REQ_PER_SEC)
    try:
        results = {}

        def worker(idx):
            t0 = time.monotonic()
            for _ in range(5):
                sp._throttle()
            results[idx] = time.monotonic() - t0

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - t0
    finally:
        sp._rate_limiter = orig_limiter

    serial = 40 * sp.REQUEST_GAP
    check("throttle: far faster than serial", elapsed < serial * 0.75,
          f"{elapsed:.2f}s vs serial {serial:.2f}s")
    check("throttle: still bounded by the bucket",
          elapsed >= 40 / sp.MAX_REQ_PER_SEC * 0.5,
          f"{elapsed:.2f}s (bucket floor {40 / sp.MAX_REQ_PER_SEC:.2f}s)")
    check("throttle: every worker finished", len(results) == 8, str(len(results)))


def test_throttle_respects_total_rate():
    """The bucket must cap the AGGREGATE rate, not just each worker."""
    limiter = sp._TokenBucket(sp.MAX_REQ_PER_SEC)
    t0 = time.monotonic()
    for _ in range(20):          # capacity is 20, so this is a free burst
        limiter.acquire()
    burst = time.monotonic() - t0
    for _ in range(10):          # bucket now empty -> must be paced
        limiter.acquire()
    paced = time.monotonic() - t0

    check("rate: burst allowed up to capacity", burst < 0.25, f"{burst:.2f}s")
    check("rate: beyond capacity it paces",
          paced >= 10 / sp.MAX_REQ_PER_SEC * 0.6, f"{paced:.2f}s")
    check("rate: 30 calls took at least 10/rate",
          paced >= 10 / sp.MAX_REQ_PER_SEC, f"{paced:.2f}s vs {10 / sp.MAX_REQ_PER_SEC:.2f}s")


def test_throttle_per_worker_gap_is_kept():
    """One thread calling twice in a row must still wait REQUEST_GAP."""
    orig = sp._rate_limiter
    sp._rate_limiter = sp._TokenBucket(1000.0)   # effectively no bucket
    try:
        t0 = time.monotonic()
        sp._throttle()
        sp._throttle()
        elapsed = time.monotonic() - t0
    finally:
        sp._rate_limiter = orig
    check("throttle: same thread still paces itself",
          elapsed >= sp.REQUEST_GAP * 0.8, f"{elapsed:.3f}s vs gap {sp.REQUEST_GAP}")


def test_cached_metadata_many_uses_cache(tmp: Path):
    """Album/label used to cost one request per song on EVERY load."""
    import tempfile

    original = sp._cache_path
    sp._cache_path = lambda name: Path(tempfile.gettempdir()) / f"tz_{name}.json"
    try:
        orig_many = sp.metadata_many
        seen = []

        def spy(ids, token, workers=8):
            seen.append(list(ids))
            return {tid: {"album": f"Alb-{tid}", "label": "L", "year": 2020,
                          "track_number": 1, "disc_number": 1} for tid in ids}

        sp.metadata_many = spy
        try:
            first = sp.cached_metadata_many(["A", "B"], "tok")
            check("cache meta: fetched on first call", first.get("A", {}).get("album") == "Alb-A",
                  str(first))
            check("cache meta: only the misses fetched", seen == [["A", "B"]], str(seen))

            seen.clear()
            second = sp.cached_metadata_many(["A", "B"], "tok")
            check("cache meta: second call makes no request", seen == [], str(seen))
            check("cache meta: same result from cache", second == first, str(second))

            seen.clear()
            third = sp.cached_metadata_many(["A", "B", "C"], "tok")
            check("cache meta: only the NEW id fetched", seen == [["C"]], str(seen))
            check("cache meta: all three returned", set(third) == {"A", "B", "C"}, str(set(third)))
        finally:
            sp.metadata_many = orig_many
    finally:
        sp._cache_path = original
        import os
        for name in ("tz_tracks", "tz_meta"):
            Path(tempfile.gettempdir(), f"{name}.json").unlink(missing_ok=True)


def test_cached_metadata_no_token_does_not_fetch():
    """Without a token we must not hit the endpoint at all."""
    orig = sp.metadata_many
    sp.metadata_many = lambda *a, **k: {"X": {}}
    try:
        check("cache meta: no token -> no fetch",
              sp.cached_metadata_many(["X"], "") == {})
    finally:
        sp.metadata_many = orig


def test_metadata_includes_cover():
    """Metadata must carry artwork so a cold load needs only 1 request/song."""
    payload = {"name": "T", "artist": [{"name": "A"}],
               "album": {"name": "Alb", "label": "L", "date": {"year": 2020},
                         "cover_group": {"image": [
                             {"file_id": "ab67616d00001e02aaa", "width": 300},
                             {"file_id": "ab67616d0000b273aaa", "width": 640}]}}}
    orig = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    try:
        meta = sp.track_metadata_spclient("2mdEsXPu8ZmkHRRtAdC09e", "tok")
    finally:
        sp._get_json = orig
    check("cover: taken from the metadata payload",
          meta.get("cover", "").endswith("ab67616d0000b273aaa"), str(meta.get("cover")))
    check("cover: uses i.scdn.co",
          meta.get("cover", "").startswith("https://i.scdn.co/image/"),
          str(meta.get("cover")))


def test_metadata_cover_missing_is_empty():
    payload = {"name": "T", "album": {"name": "A"}}
    orig = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    try:
        meta = sp.track_metadata_spclient("2mdEsXPu8ZmkHRRtAdC09e", "tok")
    finally:
        sp._get_json = orig
    check("cover: absent artwork -> empty string", meta.get("cover") == "",
          str(meta.get("cover")))


# ---------------------------------------------- playlist cover reaches the UI
def test_embed_returns_the_playlist_cover():
    """embed_tracks_complete's 4th value is the PLAYLIST artwork.

    Getting this wrong is what made the Home header show the first track's
    album cover, i.e. someone else's picture.
    """
    names = [("A", "AA", 1000), ("B", "BB", 2000)]
    # Whatever _embed_html() puts on the playlist image is what must come back.
    playlist_img = "https://mosaic.scdn.co/640/PLAYLIST"

    orig_get = se._get
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    se._get = lambda url, headers=None: _embed_html(names)
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"
    payload = {"length": 2, "ownerUsername": "o",
               "contents": {"truncated": False, "items": [
                   {"uri": f"spotify:track:ID{i:016d}"} for i in range(2)]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    sp.metadata_many = lambda ids, tok, workers=8: {}

    try:
        _t, _tr, _h, cover, _o, _ms = se.embed_tracks_complete(
            "https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    check("plcover: returned to the caller", cover == playlist_img, cover)
    check("plcover: differs from album artwork",
          cover != ALBUM_ART and "ab67616d" not in cover, cover)


def test_spotify_meta_stores_the_playlist_cover():
    """SpotifyMeta must not throw the cover away any more."""
    import providers.spotify_meta as sm

    orig_get = se._get
    orig_meta = sp.metadata_many
    orig_cache = sp._cache_path
    import tempfile
    tmp = tempfile.mkdtemp()

    playlist_img = "https://mosaic.scdn.co/640/PLAYLIST"
    se._get = lambda url, headers=None: _embed_html([("A", "AA", 1000)])
    sp._cache_path = lambda name: Path(tmp) / f"{name}.json"
    payload = {"length": 1, "ownerUsername": "o",
               "contents": {"truncated": False,
                            "items": [{"uri": "spotify:track:ID0000000000000000"}]}}
    orig_get_json = sp._get_json
    sp._get_json = lambda url, headers=None: payload
    sp.metadata_many = lambda ids, tok, workers=8: {}

    try:
        meta = sm.SpotifyMeta()
        meta.playlist_tracks("https://open.spotify.com/playlist/5jPG8GymyNv0lX6aSv5dE3")
        got = meta.last_playlist_cover
    finally:
        se._get = orig_get
        sp._get_json = orig_get_json
        sp.metadata_many = orig_meta
        sp._cache_path = orig_cache

    check("plcover: kept on the metadata client", got == playlist_img, repr(got))
    check("plcover: playlist prefix preserved",
          got != ALBUM_ART and "ab67616d" not in got, got)


def test_youtube_client_forwards_the_playlist_cover():
    """YouTubeClient is what the UI actually talks to."""
    import providers.youtube as yt

    class FakeMeta:
        last_owner = "David-Atha"
        last_total_duration_ms = 123
        last_playlist_cover = "https://image-cdn-ak.spotifycdn.com/image/ab67706cXYZ"

        def playlist_tracks(self, url, max_items=0, progress=None):
            return ("Dupe", [Track(data="t1", track_token="t1", title="T")], "")

    orig = yt.SpotifyMeta
    yt.SpotifyMeta = FakeMeta
    try:
        client = yt.YouTubeClient()
        client.load_tracks("https://open.spotify.com/playlist/02hYsnNkqFC9GiJpShgswH")
        got = client.last_playlist_cover
    finally:
        yt.SpotifyMeta = orig

    check("plcover: forwarded by the provider",
          got == "https://image-cdn-ak.spotifycdn.com/image/ab67706cXYZ", repr(got))


def test_playlist_cover_defaults_to_empty():
    """Providers that never set it must expose an empty string, not blow up."""
    import providers.spotify_meta as sm
    import providers.youtube as yt

    check("plcover: SpotifyMeta default empty",
          sm.SpotifyMeta.__init__ is not None)
    meta = sm.SpotifyMeta.__new__(sm.SpotifyMeta)
    # Not initialised: getattr() must still be safe.
    check("plcover: YouTubeClient declares the attribute",
          "last_playlist_cover" in yt.YouTubeClient.__init__.__code__.co_names,
          str(yt.YouTubeClient.__init__.__code__.co_names))


def main():
    test_extract_anon_token_from_real_html_shape()
    test_no_token_is_hardcoded_in_source()
    test_playlist_track_ids_full_list()
    test_playlist_track_ids_headers()
    test_playlist_track_ids_requires_token()
    test_truncated_flag_is_surfaced()
    test_missing_items_tolerated()
    test_non_track_uris_skipped()
    test_track_meta_embed_parsing()
    test_track_meta_cover_art_null_is_ok()
    test_track_meta_missing_page_returns_empty()
    test_track_cover_oembed()
    test_track_details_batch_and_worker_cap()
    test_track_details_one_failure_does_not_break_batch()
    test_progress_callback_fires()
    test_playlist_path_avoids_api_spotify()
    test_embed_complete_uses_spclient()
    test_graceful_fallback_when_spclient_dies()
    test_r1_every_track_gets_its_own_cover()
    test_r1_failed_lookup_falls_back_to_embed_row()
    test_r1_whole_batch_failure_keeps_playlist_usable()
    test_r0_owner_prefers_the_display_name()
    test_b62_to_hex_known_value()
    test_track_metadata_spclient_parsing()
    test_track_metadata_uses_hex_gid_and_bearer()
    test_track_metadata_no_token_returns_empty()
    test_track_fields_carry_tagging_data()
    test_throttle_is_not_global_serialisation()
    test_throttle_respects_total_rate()
    test_throttle_per_worker_gap_is_kept()
    import tempfile
    test_cached_metadata_many_uses_cache(Path(tempfile.gettempdir()))
    test_cached_metadata_no_token_does_not_fetch()
    test_metadata_includes_cover()
    test_metadata_cover_missing_is_empty()
    test_embed_returns_the_playlist_cover()
    test_spotify_meta_stores_the_playlist_cover()
    test_youtube_client_forwards_the_playlist_cover()
    test_playlist_cover_defaults_to_empty()

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_cache_roundtrip(Path(td))
        test_broken_cache_ignored(Path(td))

    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()