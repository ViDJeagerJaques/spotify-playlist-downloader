"""Headless live test for SoundLoaders / SpotiDown with a real BYO token.

Usage:
    .venv\Scripts\python.exe tests\live_token_test.py <provider> <spotify_url> <token>

    provider       = soundloaders | spotidown
    spotify_url    = e.g. https://open.spotify.com/playlist/...
    token          = the CAPTCHA token you grabbed via the F12 console snippet

This replays exactly what the app does (fresh requests session from this server
machine) to check whether a real browser-minted token is accepted or rejected
when the request comes from a different IP/cookie. No files are saved.
"""
from __future__ import annotations

import sys
import time

from providers.soundloaders import SoundLoadersClient
from providers.spotidown import SpotiDownClient


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    provider, url, token = sys.argv[1], sys.argv[2], sys.argv[3]
    token = token.strip()

    if provider == "soundloaders":
        client = SoundLoadersClient()
    elif provider == "spotidown":
        client = SpotiDownClient()
    else:
        print(f"Unknown provider: {provider}")
        return 2

    print(f"== {client.name} ==")
    print(f"spotify_url len={len(url)} token_len={len(token)}")
    print("calling load_tracks(..., cftoken=...) ...")
    t0 = time.time()
    try:
        result = client.load_tracks(url, token)
        print(f"[OK] load_tracks took {time.time()-t0:.1f}s")
        print(f"title={result.title!r} tracks={len(result.tracks)}")
        if result.tracks:
            tr = result.tracks[0]
            print(f"sample track: {tr.title!r} - {tr.artist!r}")
            print("calling resolve_track on first track ...")
            t1 = time.time()
            try:
                mp3 = client.resolve_track(tr, token)
                print(f"[OK] resolve_track took {time.time()-t1:.1f}s")
                print(f"mp3={mp3[:120]}")
                print("RESULT: SUCCESS")
                return 0
            except Exception as e:
                print(f"[FAIL] resolve_track: {type(e).__name__}: {e}")
                print("RESULT: TRACK_RESOLVE_FAILED")
                return 3
        print("RESULT: NO_TRACKS")
        return 1
    except Exception as e:
        print(f"[FAIL] load_tracks: {type(e).__name__}: {e}")
        print("RESULT: LOAD_FAILED")
        return 4


if __name__ == "__main__":
    sys.exit(main())
