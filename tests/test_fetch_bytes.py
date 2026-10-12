"""Tests for app._fetch_bytes — the single-track download path.

The Download Lagu page broke with::

    InvalidSchema: No connection adapters were found for
    'C:\\...\\Temp\\spotify_yt_cache\\xxx.mp3'

because the YouTube provider returns a finished LOCAL FILE from
``resolve_track`` rather than a URL, and the page went straight to
``requests.get``. These tests pin all three input shapes the function must
handle: mock://, local file, HTTP URL — plus the failure cases.

Run:  python tests/test_fetch_bytes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as appmod  # noqa: E402
from providers.base import ProviderId, ServiceError  # noqa: E402
from providers.mock import _mock_mp3_bytes  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def test_mock_url():
    """mock:// still returns placeholder bytes (offline Demo backend)."""
    data = appmod._fetch_bytes("mock://whatever")
    check("fetch: mock:// returns bytes", isinstance(data, bytes) and len(data) > 0)
    check("fetch: mock:// matches provider bytes", data == _mock_mp3_bytes())


def test_local_file(tmp: Path):
    """A real local file is read straight off disk — the YouTube case."""
    f = tmp / "song.mp3"
    payload = b"ID3\x04\x00" + b"\x00" * 512
    f.write_bytes(payload)

    data = appmod._fetch_bytes(str(f))
    check("fetch: local file read", data == payload, f"{len(data)} vs {len(payload)}")
    check("fetch: local file keeps bytes", data[:3] == b"ID3", repr(data[:3]))


def test_local_file_with_spaces(tmp: Path):
    """Windows paths with spaces must not break the branch."""
    d = tmp / "dir with space"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "Artist - Title (Official).mp3"
    f.write_bytes(b"ID3" + b"x" * 64)
    check("fetch: path with spaces", appmod._fetch_bytes(str(f))[:3] == b"ID3")


def test_missing_local_path_falls_through(tmp: Path):
    """A path that does not exist is NOT swallowed as an empty download.

    It falls through to the HTTP branch, where requests raises a clear error
    rather than us pretending the file was fine.
    """
    missing = tmp / "does-not-exist.mp3"
    try:
        appmod._fetch_bytes(str(missing))
        check("fetch: missing path raises", False, "no exception raised")
    except ServiceError:
        check("fetch: missing path raises ServiceError", True)
    except Exception as exc:  # noqa: BLE001
        # requests raises InvalidSchema for a bare path; that is acceptable as
        # long as it is an exception rather than silent bad data.
        check("fetch: missing path raises", True, f"raised {type(exc).__name__}")


def test_empty_local_file_raises(tmp: Path):
    """A zero-byte file must be reported, not returned as empty bytes."""
    f = tmp / "empty.mp3"
    f.write_bytes(b"")
    try:
        appmod._fetch_bytes(str(f))
        check("fetch: empty file raises", False, "no exception")
    except ServiceError as exc:
        check("fetch: empty file raises ServiceError", True)
        check("fetch: empty file message is Indonesian",
              "kosong" in exc.user_message, exc.user_message)


def test_illegal_windows_path_does_not_crash():
    """Path() can raise on illegal Windows chars — must not propagate raw."""
    bad = 'C:\\bad\x00name\\x.mp3'
    try:
        appmod._fetch_bytes(bad)
        check("fetch: illegal path handled", True, "fell through cleanly")
    except ServiceError:
        check("fetch: illegal path handled", True)
    except Exception as exc:  # noqa: BLE001
        check("fetch: illegal path handled", False, f"raw {type(exc).__name__}: {exc}")


def test_with_headers_helper(tmp: Path):
    """The header-aware variant used by _fetch_mp3_bytes behaves the same."""
    f = tmp / "h.mp3"
    f.write_bytes(b"ID3abc")
    check("fetch: headers helper local", appmod._fetch_bytes_with_headers(str(f), {}) == b"ID3abc")
    check("fetch: headers helper mock",
          appmod._fetch_bytes_with_headers("mock://x", {}) == _mock_mp3_bytes())


def test_fetch_mp3_bytes_uses_resolver(tmp):
    """_fetch_mp3_bytes must go through resolve_track, not assume mp3_url.

    This is exactly the failing user flow: track.mp3_url is None (the YouTube
    provider leaves it empty), the resolver returns a local path, and the
    Download Lagu button must still yield real bytes.
    """
    from providers.base import Track

    f = tmp / "resolved.mp3"
    f.write_bytes(b"ID3" + b"z" * 32)

    class FakeProvider:
        name = "fake"
        # _get_provider() only reuses a cached client when its provider id
        # matches the selected backend, so declare it (mock) or it is discarded.
        provider = ProviderId.MOCK

        def resolve_track(self, track, cftoken=""):
            return str(f)

    # _get_provider() reads session_state.backend, so initialise both keys.
    appmod.init_state()
    appmod.st.session_state["backend"] = ProviderId.MOCK.value
    appmod.st.session_state["provider_obj"] = FakeProvider()
    try:
        track = Track(data="t1", track_token="t1", title="T", mp3_url=None)
        data = appmod._fetch_mp3_bytes(track)
        check("fetch: _fetch_mp3_bytes handles local resolve",
              data[:3] == b"ID3", repr(data[:6]))
    finally:
        appmod.st.session_state.pop("provider_obj", None)


def main():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_mock_url()
        test_local_file(tmp)
        test_local_file_with_spaces(tmp)
        test_missing_local_path_falls_through(tmp)
        test_empty_local_file_raises(tmp)
        test_illegal_windows_path_does_not_crash()
        test_with_headers_helper(tmp)
        test_fetch_mp3_bytes_uses_resolver(tmp)

    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()