"""Offline checks for the public-embed metadata reader.

No network and no credentials: the parser is fed embed-page HTML shaped exactly
like the real thing (captured from open.spotify.com), including the failure
cases we care about — missing __NEXT_DATA__, changed structure, empty lists.

Run:  python tests/test_spotify_embed.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.base import ServiceError, Track  # noqa: E402
from providers.spotify_embed import (  # noqa: E402
    EMBED_ITEM_LIMIT,
    oembed_cover,
    parse_embed_page,
    tracks_from_entity,
)
from providers.spotify_meta import SpotifyMeta  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def _page(entity: dict) -> str:
    """Wrap an entity the way the real embed page wraps it."""
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + '</script></body></html>')


def _track_row(n: int) -> dict:
    return {
        "uri": f"spotify:track:ID{n:016d}",
        "uid": f"uid{n}",
        "title": f"Track {n}",
        "subtitle": "Some Artist",
        "isExplicit": False,
        "duration": 200000 + n,
        "isPlayable": True,
        "audioPreview": {"format": "MP3_96", "url": "https://p.scdn.co/mp3-preview/x"},
        "entityType": "track",
    }


PLAYLIST_ENTITY = {
    "name": "Dummy Playlist",
    "title": "Dummy Playlist",
    "coverArt": {"sources": [{"height": 640, "width": 640,
                              "url": "https://mosaic.scdn.co/640/abc"}]},
    "trackList": [_track_row(i) for i in range(1, 4)],
}


# --------------------------------------------------------------- parsing
def test_parse_extracts_entity():
    entity = parse_embed_page(_page(PLAYLIST_ENTITY))
    check("embed: name parsed", entity["name"] == "Dummy Playlist", str(entity.get("name")))
    check("embed: trackList present", len(entity["trackList"]) == 3)


def test_missing_next_data_raises_clear_error():
    try:
        parse_embed_page("<html><body>no data here</body></html>")
        check("embed: missing __NEXT_DATA__ raises", False, "no exception")
    except ServiceError as exc:
        msg = exc.user_message
        check("embed: missing __NEXT_DATA__ raises", True)
        # Was "mentions SpotiDown fallback" — that backend no longer exists, and
        # pointing the user at a removed option is worse than saying nothing.
        check("embed: error no longer points at removed backends",
              "SpotiDown" not in msg and "SoundLoaders" not in msg, msg[:90])
        check("embed: error points at something that still exists",
              ".env" in msg, msg[:90])
        check("embed: error is actionable", "berubah bentuk" in msg, msg[:90])


def test_changed_structure_raises():
    payload = {"props": {"pageProps": {"state": {"data": {"somethingElse": {}}}}}}
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload) + '</script>')
    try:
        parse_embed_page(html)
        check("embed: changed structure raises", False, "no exception")
    except ServiceError:
        check("embed: changed structure raises", True)


def test_bad_json_raises():
    html = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
    try:
        parse_embed_page(html)
        check("embed: bad json raises", False, "no exception")
    except ServiceError:
        check("embed: bad json raises", True)


# --------------------------------------------------------------- mapping
def test_tracks_mapped():
    tracks = tracks_from_entity(PLAYLIST_ENTITY, cover_for="https://mosaic.scdn.co/640/abc")
    check("embed: 3 tracks", len(tracks) == 3)
    t = tracks[0]
    check("embed: id from uri", t.track_token == "ID0000000000000001", t.track_token)
    check("embed: title", t.title == "Track 1", t.title)
    check("embed: artist from subtitle", t.artist == "Some Artist", t.artist)
    check("embed: duration ms", t.duration_ms == 200001, str(t.duration_ms))
    check("embed: cover reused", t.thumbnail == "https://mosaic.scdn.co/640/abc")
    check("embed: mp3_url unset", t.mp3_url is None)


def test_non_track_rows_skipped():
    entity = dict(PLAYLIST_ENTITY)
    entity["trackList"] = [
        _track_row(1),
        {"uri": "spotify:episode:EP1", "title": "An Episode", "entityType": "episode"},
        {"title": "no uri at all", "entityType": "track"},
    ]
    tracks = tracks_from_entity(entity)
    check("embed: episodes skipped", len(tracks) == 1, str(len(tracks)))


def test_empty_track_list():
    check("embed: empty list -> no tracks",
          tracks_from_entity({"trackList": []}) == [])
    check("embed: missing key -> no tracks",
          tracks_from_entity({}) == [])


def test_junk_rows_tolerated():
    entity = {"trackList": ["a string", 42, None, _track_row(9)]}
    tracks = tracks_from_entity(entity)
    check("embed: junk rows skipped", len(tracks) == 1, str(len(tracks)))


# --------------------------------------------------------------- cover
def test_cover_from_cover_art():
    tracks = tracks_from_entity(PLAYLIST_ENTITY, cover_for="c")
    check("embed: cover prefilled", tracks[0].thumbnail == "c")


def test_oembed_signature_is_public():
    """Sanity check that we only ever call public, credential-free endpoints."""
    import providers.spotify_embed as se

    src = Path(se.__file__).read_text(encoding="utf-8")
    check("embed: no client_secret in module", "client_secret" not in src)
    check("embed: no accounts.spotify.com call", "accounts.spotify.com" not in src)
    check("embed: reads open.spotify.com/embed", "/embed/" in src)
    check("embed: item limit is 100", EMBED_ITEM_LIMIT == 100, str(EMBED_ITEM_LIMIT))


# --------------------------------------------------------------- routing
def test_meta_prefers_embed_without_credentials():
    """The default client must not need .env at all."""
    m = SpotifyMeta(client_id="", client_secret="", prefer="embed")
    check("meta: embed mode has no creds", not m._cid and not m._secret)


def test_meta_api_mode_kept():
    m = SpotifyMeta(client_id="id", client_secret="secret", prefer="api")
    check("meta: api mode stores creds", m._cid == "id" and m._secret == "secret")
    check("meta: prefer recorded", m._prefer == "api")


# ------------------------------------------------- real captured fixtures
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _wrap(entity: dict) -> str:
    return _page(entity)


def test_real_playlist_fixture():
    """The real 100-item playlist page, captured live, must map cleanly."""
    path = FIXTURES / "playlist_100.json"
    if not path.exists():
        return
    entity = json.loads(path.read_text(encoding="utf-8"))
    parsed = parse_embed_page(_wrap(entity))
    cover = parsed.get("coverArt", {}).get("sources", [{}])[0].get("url", "")
    tracks = tracks_from_entity(parsed, cover_for=cover)
    check("embed real: 100 tracks", len(tracks) == 100, str(len(tracks)))
    check("embed real: covers assigned", all(t.thumbnail for t in tracks))
    check("embed real: durations present", all(t.duration_ms > 0 for t in tracks))
    check("embed real: ids unique", len({t.track_token for t in tracks}) == 100)
    check("embed real: no empty artist", all(t.artist for t in tracks))


def test_real_album_fixture():
    path = FIXTURES / "album_hs.json"
    if not path.exists():
        return
    entity = json.loads(path.read_text(encoding="utf-8"))
    tracks = tracks_from_entity(parse_embed_page(_wrap(entity)), cover_for="x")
    check("embed real album: 10 tracks", len(tracks) == 10, str(len(tracks)))
    titles = {t.title for t in tracks}
    check("embed real album: Sign of the Times present", "Sign of the Times" in titles)
    s = next((t for t in tracks if t.title == "Sign of the Times"), None)
    check("embed real album: artist mapped", s is not None and s.artist == "Harry Styles",
          s.artist if s else "missing")
    check("embed real album: duration ~340s",
          s is not None and 335000 < s.duration_ms < 345000,
          str(s.duration_ms) if s else "-")


def main():
    test_parse_extracts_entity()
    test_missing_next_data_raises_clear_error()
    test_changed_structure_raises()
    test_bad_json_raises()
    test_tracks_mapped()
    test_non_track_rows_skipped()
    test_empty_track_list()
    test_junk_rows_tolerated()
    test_cover_from_cover_art()
    test_oembed_signature_is_public()
    test_meta_prefers_embed_without_credentials()
    test_meta_api_mode_kept()
    test_real_playlist_fixture()
    test_real_album_fixture()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
