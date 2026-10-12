"""Tests for the 640x640 cover upgrade.

Spotify encodes image size in the URL prefix. oEmbed hands out the 300x300
prefix, which looks blurry when opened large — the user compared our files with
a downloader's 640x640 covers and asked for the bigger ones.

The swap is safe because the hash after the prefix is identical at every size.
It must be narrow, though: playlist art uses a different prefix family and 404s
at the large one.

Run:  python tests/test_cover_size.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.base import (  # noqa: E402
    COVER_LARGE_PREFIX,
    COVER_SMALL_PREFIX,
    upgrade_cover_url,
)

PASS = []
FAIL = []

HASH = "879e9318cb9f4e05ee552ac9"
SMALL = f"https://image-cdn-ak.spotifycdn.com/image/{COVER_SMALL_PREFIX}{HASH}"
LARGE = f"https://image-cdn-ak.spotifycdn.com/image/{COVER_LARGE_PREFIX}{HASH}"
PLAYLIST = ("https://image-cdn-ak.spotifycdn.com/image/"
            "ab67706c0000da84d1a91a9ff0c47ed829f3")


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


# ------------------------------------------------------------------ prefixes
def test_prefix_constants():
    check("size: small prefix is the 300px one",
          COVER_SMALL_PREFIX == "ab67616d00001e02", COVER_SMALL_PREFIX)
    check("size: large prefix is the 640px one",
          COVER_LARGE_PREFIX == "ab67616d0000b273", COVER_LARGE_PREFIX)


def test_upgrade_produces_the_640_url():
    got = upgrade_cover_url(SMALL)
    check("size: upgraded to 640 prefix", COVER_LARGE_PREFIX in got, got)
    check("size: hash preserved", got.endswith(HASH), got[-30:])
    check("size: rest of URL preserved", got.startswith(
        "https://image-cdn-ak.spotifycdn.com/image/"), got)


def test_idempotent():
    """Applying twice must not double-rewrite or corrupt the URL."""
    once = upgrade_cover_url(SMALL)
    twice = upgrade_cover_url(once)
    check("size: idempotent", once == twice, f"{once} != {twice}")
    check("size: already-large left alone", upgrade_cover_url(LARGE) == LARGE)


def test_playlist_cover_not_upgraded():
    """THE IMPORTANT ONE: playlist art must survive untouched."""
    got = upgrade_cover_url(PLAYLIST)
    check("size: playlist prefix untouched", got == PLAYLIST, got)
    check("size: playlist not given the album prefix",
          COVER_LARGE_PREFIX not in got, got)


def test_other_prefixes_untouched():
    for url in ("https://mosaic.scdn.co/300/whatever",
                "https://i.scdn.co/image/ab67706c0000da84",
                "https://example.com/cover.jpg",
                "ab67616d00004851abc"):
        check(f"size: untouched {url[:44]}", upgrade_cover_url(url) == url, url)


def test_empty_input():
    check("size: empty string", upgrade_cover_url("") == "")
    check("size: None", upgrade_cover_url(None) is None)


def test_i_scdn_domain_also_upgraded():
    """Both Spotify CDN hosts serve the same images."""
    url = f"https://i.scdn.co/image/{COVER_SMALL_PREFIX}{HASH}"
    got = upgrade_cover_url(url)
    check("size: i.scdn.co upgraded", COVER_LARGE_PREFIX in got, got)


# ------------------------------------------------------------ applied in code
def test_spclient_track_cover_is_upgraded():
    """track_cover_oembed() must return the big URL (stubbed, no network)."""
    import providers.spotify_spclient as sp

    orig = sp._get_json
    sp._get_json = lambda url, headers=None: {
        "title": "Cinnamon Girl",
        "thumbnail_url": SMALL,
        "thumbnail_width": 300,
    }
    try:
        got = sp.track_cover_oembed("2mdEsXPu8ZmkHRRtAdC09e")
    finally:
        sp._get_json = orig
    check("size: oEmbed result upgraded", got == LARGE, got)


def test_embed_oembed_cover_is_upgraded():
    import providers.spotify_embed as se

    orig = se._get_json
    se._get_json = lambda url, headers=None: {"thumbnail_url": SMALL}
    try:
        got = se.oembed_cover("track", "2mdEsXPu8ZmkHRRtAdC09e")
        # A playlist thumb uses a different prefix; must pass through as-is.
        se._get_json = lambda url, headers=None: {"thumbnail_url": PLAYLIST}
        got_playlist = se.oembed_cover("playlist", "02hYsnNkqFC9GiJpShgswH")
    finally:
        se._get_json = orig
    check("size: embed oEmbed upgraded", got == LARGE, got)
    check("size: embed playlist untouched", got_playlist == PLAYLIST, got_playlist)


def test_playlist_cover_helper_is_never_upgraded():
    """_playlist_cover() reads the page's own image and must not rewrite it."""
    import providers.spotify_embed as se

    entity = {"coverArt": {"sources": [{"url": PLAYLIST}]}}
    got = se._playlist_cover(entity)
    check("size: _playlist_cover returns raw page URL", got == PLAYLIST, got)


def test_tags_download_cover_upgrades():
    """The safety net for art embedded in the MP3."""
    import providers.tags as tg

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        raise RuntimeError("stop here")   # we only care about the URL

    import urllib.request
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        tg.download_cover(SMALL)
    finally:
        urllib.request.urlopen = orig
    check("size: tags download upgrades", seen.get("url") == LARGE,
          str(seen.get("url")))


def test_tags_does_not_upgrade_playlist_art():
    """A 640 playlist URL would 404 — the safety net must not create one."""
    import providers.tags as tg

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        raise RuntimeError("stop here")

    import urllib.request
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        tg.download_cover(PLAYLIST)
    finally:
        urllib.request.urlopen = orig
    check("size: tags leaves playlist art alone",
          seen.get("url") == PLAYLIST, str(seen.get("url")))


def main():
    test_prefix_constants()
    test_upgrade_produces_the_640_url()
    test_idempotent()
    test_playlist_cover_not_upgraded()
    test_other_prefixes_untouched()
    test_empty_input()
    test_i_scdn_domain_also_upgraded()
    test_spclient_track_cover_is_upgraded()
    test_embed_oembed_cover_is_upgraded()
    test_playlist_cover_helper_is_never_upgraded()
    test_tags_download_cover_upgrades()
    test_tags_does_not_upgrade_playlist_art()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()