"""Tests for the optional Spotify user-token path (#1).

Covers the ORDER rule the task specifies (refresh token -> user API, else embed),
the paging loop that removes the 100-item cap, and the "app must still work
without OAuth" guarantee. Fully offline: HTTP is stubbed.

Run:  python tests/test_oauth.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import providers.spotify_meta as sm  # noqa: E402
from providers.base import ServiceError  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


PLAYLIST = "https://open.spotify.com/playlist/0jeZAndC8kr76ROevxI5zM"


def _item(i: int) -> dict:
    return {
        "item": {
            "id": f"tid{i:016d}",
            "type": "track",
            "name": f"Track {i}",
            "duration_ms": 200_000 + i,
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "album": {"name": f"Album {i}", "images": [
                {"url": f"https://i.scdn.co/x{i}", "height": 640, "width": 640}]},
        }
    }


class UserStub(sm.SpotifyMeta):
    """Paged user-token client with no real network."""

    def __init__(self, total: int, refresh: str = "fake-refresh"):
        self._cid, self._secret = "cid", "secret"
        self._token, self._token_expiry = "x", 0.0
        self._prefer = "embed"
        self._refresh_token = refresh
        self._user_access_token = "user-token"
        self._user_token_expiry = 9_999_999_999.0
        self.last_owner = ""
        self.last_total_duration_ms = 0
        self.total = total
        self.user_calls: list[str] = []
        self.app_calls: list[str] = []

    def _get_user(self, path, params=None):
        self.user_calls.append(path)
        if path.startswith("/playlists/") and path.endswith("/items"):
            limit = int((params or {}).get("limit", 100))
            offset = int((params or {}).get("offset", 0))
            page = [_item(i) for i in range(offset, min(offset + limit, self.total))]
            return {"items": page}
        if path.startswith("/playlists/"):
            return {"name": "Big Playlist", "owner": {"display_name": "Tester"},
                    "tracks": {"total": self.total}}
        raise ServiceError(f"unexpected {path}")

    def _get(self, path, params=None):   # app-only token; must not be used here
        self.app_calls.append(path)
        raise ServiceError("app-only token should not reach playlist items")

    def _user_access_token_value(self):
        return "user-token"


def test_no_token_uses_embed_order():
    """ORDER RULE: no refresh token -> anonymous chain, user API never consulted.

    The anonymous chain reads the WHOLE playlist (spclient), so >100 songs is
    expected here — that is the whole point of the spclient work.
    """
    m = UserStub(total=250, refresh="")
    title, tracks, hint = m.playlist_tracks(PLAYLIST)
    check("oauth: without token, no user API calls", m.user_calls == [], str(m.user_calls))
    check("oauth: without token, no app-only API calls", m.app_calls == [], str(m.app_calls))
    check("oauth: anonymous path still returns songs", len(tracks) > 0, str(len(tracks)))


def test_token_uses_user_api_first():
    """ORDER RULE: refresh token present -> user API, embed skipped."""
    m = UserStub(total=250, refresh="r1")
    title, tracks, hint = m.playlist_tracks(PLAYLIST)
    check("oauth: with token, user API used", any("/items" in c for c in m.user_calls),
          str(m.user_calls))
    check("oauth: with token, app-only API untouched", m.app_calls == [], str(m.app_calls))
    check("oauth: playlist title from API", title == "Big Playlist", title)


def test_paging_removes_100_cap():
    """A 250-song playlist must load fully, in 100/100/50 pages."""
    m = UserStub(total=250)
    title, tracks, hint = m.playlist_tracks(PLAYLIST)
    check("oauth: 250 songs loaded", len(tracks) == 250, str(len(tracks)))
    item_calls = [c for c in m.user_calls if c.endswith("/items")]
    check("oauth: paged 3 times", len(item_calls) == 3, str(len(item_calls)))
    check("oauth: no truncation hint", hint == "", hint)


def test_paging_exact_multiples():
    """Exactly 200 songs -> 2 full pages then an empty page that ends the loop."""
    m = UserStub(total=200)
    _t, tracks, _h = m.playlist_tracks(PLAYLIST)
    check("oauth: 200 songs loaded", len(tracks) == 200, str(len(tracks)))
    item_calls = [c for c in m.user_calls if c.endswith("/items")]
    check("oauth: 200 needs 3 calls (2 full + 1 empty)", len(item_calls) == 3,
          str(len(item_calls)))


def test_paging_small_playlist_single_call():
    m = UserStub(total=5)
    _t, tracks, _h = m.playlist_tracks(PLAYLIST)
    check("oauth: 5 songs loaded", len(tracks) == 5, str(len(tracks)))
    item_calls = [c for c in m.user_calls if c.endswith("/items")]
    check("oauth: one page only", len(item_calls) == 1, str(len(item_calls)))


def test_paging_respects_max_items():
    m = UserStub(total=500)
    _t, tracks, _h = m.playlist_tracks(PLAYLIST, max_items=7)
    check("oauth: max_items stops early", len(tracks) == 7, str(len(tracks)))


def test_owner_and_duration_from_user_api():
    m = UserStub(total=3)
    m.playlist_tracks(PLAYLIST)
    check("oauth: owner captured", m.last_owner == "Tester", repr(m.last_owner))
    check("oauth: duration summed", m.last_total_duration_ms > 0,
          str(m.last_total_duration_ms))


def test_bad_token_falls_back_to_embed():
    """A rejected refresh token must NOT break the app."""

    class Broken(UserStub):
        def _user_access_token_value(self):
            raise ServiceError("refresh token ditolak")

    m = Broken(total=250, refresh="expired")
    # Must not raise: falls through to the embed path.
    try:
        title, tracks, hint = m.playlist_tracks(PLAYLIST)
        check("oauth: broken token does not crash", True)
        check("oauth: broken token still returns tracks", len(tracks) > 0, str(len(tracks)))
    except Exception as exc:  # noqa: BLE001
        check("oauth: broken token does not crash", False, f"raised {type(exc).__name__}: {exc}")


def test_has_user_token_reflects_env(tmp: Path):
    original = dict(__import__("os").environ)
    try:
        for k in ("SPOTIFY_REFRESH_TOKEN", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
            __import__("os").environ.pop(k, None)
        check("oauth: no token detected", sm.refresh_token_present() is False)

        __import__("os").environ["SPOTIFY_REFRESH_TOKEN"] = "abc"
        check("oauth: token detected", sm.refresh_token_present() is True)

        m = sm.SpotifyMeta()
        check("oauth: client reads env token", m.has_user_token() is True)
    finally:
        __import__("os").environ.clear()
        __import__("os").environ.update(original)


def test_authorize_url_shape():
    """The login link must request the playlist scopes and a code response."""
    import os as _os
    original = dict(_os.environ)
    try:
        _os.environ["SPOTIFY_CLIENT_ID"] = "myid"
        _os.environ.pop("SPOTIFY_REFRESH_TOKEN", None)
        url = sm.authorize_url("http://localhost:8501")
        check("oauth: authorize host", url.startswith("https://accounts.spotify.com/authorize"),
              url[:60])
        check("oauth: response_type=code", "response_type=code" in url, url)
        check("oauth: asks for playlist scope", "playlist-read-private" in url, url)
        check("oauth: sends client id", "client_id=myid" in url, url)
        check("oauth: redirect uri preserved", "redirect_uri=http" in url, url)
    finally:
        _os.environ.clear()
        _os.environ.update(original)


def test_no_token_raises_clear_error():
    """_user_access_token_value without a token must explain what to do."""
    original = dict(__import__("os").environ)
    try:
        __import__("os").environ.pop("SPOTIFY_REFRESH_TOKEN", None)
        m = sm.SpotifyMeta(client_id="a", client_secret="b", refresh_token="")
        try:
            m._user_access_token_value()
            check("oauth: raises without token", False, "no exception")
        except ServiceError as exc:
            check("oauth: raises without token", True)
            check("oauth: message mentions the env var",
                  "SPOTIFY_REFRESH_TOKEN" in exc.user_message, exc.user_message)
    finally:
        __import__("os").environ.clear()
        __import__("os").environ.update(original)


def test_env_example_mentions_token():
    """The template must document the optional token, without a value."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    check("oauth: env.example documents token", "SPOTIFY_REFRESH_TOKEN" in text)
    check("oauth: env.example has no real token",
          "SPOTIFY_REFRESH_TOKEN=your_" not in text.replace("\r", ""))
    check("oauth: env.example marks it optional", "OPTIONAL" in text)


def test_gitignore_covers_env():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("oauth: .env ignored", any(ln.strip() == ".env" for ln in text.splitlines()))


def main():
    test_no_token_uses_embed_order()
    test_token_uses_user_api_first()
    test_paging_removes_100_cap()
    test_paging_exact_multiples()
    test_paging_small_playlist_single_call()
    test_paging_respects_max_items()
    test_owner_and_duration_from_user_api()
    test_bad_token_falls_back_to_embed()
    test_has_user_token_reflects_env(None)
    test_authorize_url_shape()
    test_no_token_raises_clear_error()
    test_env_example_mentions_token()
    test_gitignore_covers_env()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()