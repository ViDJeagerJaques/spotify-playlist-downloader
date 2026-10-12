"""Offline checks for the spotidown.co provider.

No network, no Chrome: the parser is fed a REAL response body that was captured
earlier from api.spotidown.co and stored in tools/probe7_result.json. That keeps
the mapping (JSON -> Track) verifiable without hitting the live service.

Run:  python tests/test_spotidown_co.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.orchestrator import BatchOrchestrator, DownloadMode  # noqa: E402
from providers.base import ProviderId, ServiceError, Track  # noqa: E402
from providers.spotidown_co import (  # noqa: E402
    DOWNLOAD_HEADERS,
    FREE_TIER_LIMIT,
    SpotiDownCoClient,
    parse_search_payload,
)
from ui import data as ui_data  # noqa: E402

PASS = []
FAIL = []
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "spotidown_search_response.json"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def _real_payload() -> dict:
    """The actual /search body captured during the successful run."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_free_tier_limit_is_real():
    """The 100-track cap is the SERVICE's limit (spotidown.co free tier).

    Note this is unrelated to ui_data.PART_SIZE, which is the user's own ZIP
    splitting rule (30 songs per part) and is intentionally different.
    """
    check("co: service free tier limit is 100", FREE_TIER_LIMIT == 100, str(FREE_TIER_LIMIT))
    check("co: zip part size is 30", ui_data.PART_SIZE == 30, str(ui_data.PART_SIZE))


def test_parse_real_payload():
    payload = _real_payload()
    result = parse_search_payload(payload, source_url="https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT")
    check("co: tracks parsed", len(result.tracks) == len(payload["tracks"]),
          f"{len(result.tracks)} vs {len(payload['tracks'])}")
    check("co: title parsed", result.title == payload["name"], result.title)

    t = result.tracks[0]
    raw0 = payload["tracks"][0]
    check("co: title mapped", t.title == raw0["name"], t.title)
    check("co: artists joined", t.artist == ", ".join(raw0["artists"]), t.artist)
    check("co: mp3_url prefetched", t.mp3_url == raw0["audio"]["url"], str(t.mp3_url))
    check("co: cover mapped", t.thumbnail == raw0["album"]["coverUrl"], t.thumbnail)
    check("co: duration mapped", t.duration_ms == raw0["duration"], str(t.duration_ms))
    check("co: album mapped", t.album == raw0["album"]["name"], t.album)


def test_every_track_has_mp3_and_cover():
    payload = _real_payload()
    result = parse_search_payload(payload)
    check("co: all tracks have mp3_url", all(t.mp3_url for t in result.tracks))
    check("co: all tracks have thumbnail", all(t.thumbnail for t in result.tracks))


def test_truncation_is_reported():
    """totalCount 213 with 100 tracks must produce an honest warning."""
    payload = {
        "type": "playlist", "id": "x", "name": "Long", "totalCount": 213,
        "tracks": [{"id": str(i), "name": f"t{i}", "artists": ["A"], "duration": 1000,
                    "album": {"name": "alb", "coverUrl": "https://i.scdn.co/x"},
                    "audio": {"url": "https://api.spotidown.co/savemp3/x?sig=y"}}
                   for i in range(100)],
    }
    result = parse_search_payload(payload)
    check("co: truncation hinted", bool(result.raw_hint), "raw_hint empty")
    check("co: hint mentions 213 and premium",
          "213" in result.raw_hint and "premium" in result.raw_hint.lower(),
          result.raw_hint[:120])
    check("co: hint mentions split advice", "pecah playlist" in result.raw_hint.lower(),
          result.raw_hint[:160])


def test_no_truncation_hint_when_short():
    payload = {"type": "playlist", "name": "Small", "totalCount": 2,
               "tracks": [{"id": f"a{i}", "name": f"A{i}", "artists": ["X"], "duration": 1,
                           "album": {}, "audio": {"url": f"u{i}"}} for i in range(2)]}
    result = parse_search_payload(payload)
    check("co: no hint when complete", not result.raw_hint, result.raw_hint)


def test_missing_audio_is_tolerated():
    payload = {"type": "playlist", "name": "Odd", "totalCount": 1,
               "tracks": [{"id": "a", "name": "A", "artists": [], "duration": None,
                           "album": None, "audio": None}]}
    result = parse_search_payload(payload)
    check("co: odd row kept", len(result.tracks) == 1)
    check("co: no mp3 url -> None", result.tracks[0].mp3_url is None)
    check("co: unknown artist fallback", result.tracks[0].artist == "Unknown")


def test_resolve_track_is_free():
    """resolve_track must not touch the network: the URL is already known."""
    provider = SpotiDownCoClient()
    track = Track(data="id1", track_token="id1", title="T", mp3_url="https://x/y?sig=1")
    check("co: resolve returns prefetched", provider.resolve_track(track) == "https://x/y?sig=1")

    empty = Track(data="id2", track_token="id2", title="No audio")
    try:
        provider.resolve_track(empty)
        check("co: resolve raises without url", False, "no exception")
    except ServiceError:
        check("co: resolve raises without url", True)


def test_response_selection_prefers_http_200():
    """A failed HTTP 500 body can be longer than the good one — never pick it."""
    from providers.base import ServiceError as SE
    from providers.spotidown_co import _pick_search_response

    good = {"status": 200, "body": '{"type":"playlist"}'}
    bad_long = {"status": 500, "body": "x" * 500}
    check("co: prefers 200 over longer error",
          _pick_search_response([bad_long, good]) is good)
    check("co: longest 200 wins",
          _pick_search_response([good, {"status": 200, "body": "y" * 50}])["body"] == "y" * 50)
    check("co: falls back when no 200", _pick_search_response([bad_long]) is bad_long)
    try:
        _pick_search_response([])
        check("co: raises on empty", False, "no exception")
    except SE:
        check("co: raises on empty", True)


def test_orchestrator_skips_resolve_call():
    """The orchestrator must not spend a resolve request per track."""
    calls = []

    class Prefetched(SpotiDownCoClient):
        provider = ProviderId.SPOTIDOWN_CO
        prefetched_urls = True

        def resolve_track(self, track, cftoken=""):
            calls.append(track.track_token)
            return super().resolve_track(track, cftoken=cftoken)

    provider = Prefetched()
    tracks = [Track(data=f"i{i}", track_token=f"i{i}", title=f"T{i}", mp3_url=f"https://x/{i}")
              for i in range(3)]
    orch = BatchOrchestrator(provider, mode=DownloadMode.KEEP_URL)
    result = orch.run(tracks)
    check("co: batch kept urls", result.ok == 3 and result.failed == 0, result.summary)
    check("co: orchestrator skipped resolve_track", not calls, str(calls))
    check("co: urls recorded", all(o.mp3_url for o in result.outcomes))


def test_download_headers_shape():
    headers = SpotiDownCoClient.download_headers()
    check("co: origin header", headers.get("Origin") == "https://spotidown.co", str(headers))
    check("co: referer header", headers.get("Referer") == "https://spotidown.co/", str(headers))
    check("co: ua header", "Chrome" in headers.get("User-Agent", ""), str(headers))
    check("co: no credential leaked",
          not any(k.lower() in ("cookie", "authorization") for k in headers), str(headers))


def test_ui_adapter_shapes():
    payload = _real_payload()
    view = ui_data.playlist_view(parse_search_payload(payload, source_url="https://x"))
    check("ui: view has tracks", len(view["tracks"]) == len(payload["tracks"]))
    first = view["tracks"][0]
    check("ui: duration formatted", ":" in first["duration"], first["duration"])
    check("ui: filter by title",
          len(ui_data.filter_tracks(view["tracks"], first["title"].lower())) >= 1)
    check("ui: filter by artist",
          len(ui_data.filter_tracks(view["tracks"], first["artist"].lower())) >= 1)
    check("ui: txt preview", first["title"] in ui_data.to_txt(view))
    check("ui: csv preview", "title,artist" in ui_data.to_csv(view))
    obj = ui_data.to_json_obj(view)
    check("ui: json preview", obj["total_tracks"] == len(view["tracks"]))
    check("ui: parts within part size",
          all(len(p) <= ui_data.PART_SIZE
              for p in ui_data.chunk_parts(view["tracks"], ui_data.PART_SIZE)))


def test_chunk_parts_boundary():
    """30 songs per part; 250 songs -> 9 parts of 30,30,...,10."""
    size = ui_data.PART_SIZE
    rows = [{"id": str(i)} for i in range(250)]
    parts = ui_data.chunk_parts(rows, size)
    expected = [size] * (250 // size) + ([250 % size] if 250 % size else [])
    check("ui: 250 -> 9 parts", len(parts) == 9, str(len(parts)))
    check("ui: sizes match expected", [len(p) for p in parts] == expected,
          str([len(p) for p in parts]))


def test_chunk_parts_at_threshold():
    """The user's rule: <= 30 songs is ONE zip, > 30 is split."""
    rows30 = [{"id": str(i)} for i in range(30)]
    check("ui: exactly 30 -> 1 part", len(ui_data.chunk_parts(rows30, ui_data.PART_SIZE)) == 1)
    rows31 = [{"id": str(i)} for i in range(31)]
    parts = ui_data.chunk_parts(rows31, ui_data.PART_SIZE)
    check("ui: 31 -> 2 parts", len(parts) == 2, str(len(parts)))
    check("ui: 31 -> 30 + 1", [len(p) for p in parts] == [30, 1],
          str([len(p) for p in parts]))


def test_backup_export_is_minimal():
    """#8: the backup carries title + artist only."""
    view = {
        "title": "X", "url": "u", "total_count": 2, "hint": "",
        "tracks": [
            {"id": "a", "title": "A", "artist": "Ar", "album": "Al",
             "duration": "3:42", "mp3_url": "http://secret", "cover": "http://c"},
            {"id": "b", "title": "B", "artist": "Br", "album": "Bl",
             "duration": "1:00", "mp3_url": "http://secret2", "cover": "http://c2"},
        ],
    }
    csv_text = ui_data.to_csv(view)
    check("ui: csv header minimal", csv_text.splitlines()[0] == "no,title,artist",
          csv_text.splitlines()[0])
    for dropped in ("duration", "album", "mp3_url"):
        check(f"ui: csv drops {dropped}", dropped not in csv_text)
    check("ui: csv keeps title+artist", '"A","Ar"' in csv_text, csv_text)

    txt = ui_data.to_txt(view)
    check("ui: txt line format", "01. A - Ar" in txt, txt)
    check("ui: txt drops duration", "3:42" not in txt)
    check("ui: txt drops mp3_url", "http" not in txt)

    obj = ui_data.to_json_obj(view)
    check("ui: json track keys minimal",
          set(obj["tracks"][0].keys()) == {"no", "title", "artist"},
          str(sorted(obj["tracks"][0].keys())))
    check("ui: json has no mp3_url", "mp3_url" not in json.dumps(obj), json.dumps(obj))


def test_format_total_duration():
    """#3: human total duration for the playlist header."""
    cases = [
        (0, "0 menit"),
        (45 * 60_000, "45 menit"),
        (60 * 60_000, "1 jam"),
        (277 * 60_000, "4 jam 37 menit"),
        (3600 * 1000, "1 jam"),
    ]
    for ms, want in cases:
        got = ui_data.format_total_duration(ms)
        check(f"ui: duration {ms}ms -> '{want}'", got == want, got)

    check("ui: duration garbage handled", ui_data.format_total_duration("x") == "")


def test_single_track_duration_format():
    # Regression: format_duration takes MILLISECONDS. A 341000 ms track is
    # "5:41", not "5683:20" — the earlier code divided by 60 without ever
    # converting ms to seconds.
    check("ui: 0:00", ui_data.format_duration(0) == "0:00")
    check("ui: 222000ms -> 3:42", ui_data.format_duration(222_000) == "3:42")
    check("ui: 65000ms -> 1:05", ui_data.format_duration(65_000) == "1:05")
    check("ui: 340706ms -> 5:40", ui_data.format_duration(340_706) == "5:40")
    check("ui: hours", ui_data.format_duration(3_723_000) == "62:03")
    check("ui: garbage", ui_data.format_duration("abc") == "")


def main():
    test_free_tier_limit_is_real()
    test_parse_real_payload()
    test_every_track_has_mp3_and_cover()
    test_truncation_is_reported()
    test_no_truncation_hint_when_short()
    test_missing_audio_is_tolerated()
    test_resolve_track_is_free()
    test_response_selection_prefers_http_200()
    test_orchestrator_skips_resolve_call()
    test_download_headers_shape()
    test_ui_adapter_shapes()
    test_chunk_parts_boundary()
    test_chunk_parts_at_threshold()
    test_backup_export_is_minimal()
    test_format_total_duration()
    test_single_track_duration_format()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()