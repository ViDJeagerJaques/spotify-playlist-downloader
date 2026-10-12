"""Write Spotify tags + cover art onto a downloaded MP3 (R4).

WHY
---
Without this, files come out tagged with whatever YouTube said — ``artist`` is
the *channel* name ("David Dean Burkhart"), ``album`` is empty and there is no
cover. That is the whole reason a third-party downloader looks more "official".

We overwrite those tags with Spotify's own metadata. The audio stream is never
touched: this module only edits the ID3 container in place with mutagen.

WHAT GETS WRITTEN
-----------------
    TIT2 title      <- Spotify track title (kept verbatim, "(feat. …)" and all)
    TPE1 artist     <- Spotify artists, cleaned
    TALB album      <- spclient metadata
    TDRC date       <- release year from spclient
    TRCK track no.  <- number / disc from spclient
    TPUB label      <- record label from spclient
    APIC  cover     <- album art downloaded from oEmbed

Empty values are skipped rather than written as empty strings, and a failed
cover download never fails the tagging.
"""
from __future__ import annotations

import io
import re
import urllib.request
from pathlib import Path
from typing import Optional

# Non-breaking spaces really do occur in Spotify's artist strings, e.g.
# 'Taylor Swift,\xa0Lana Del Rey'. Left alone they render as a broken gap in
# every music player.
_NBSP = " "
_WS = re.compile(r"[ \t]+")


def clean_artists(artists) -> str:
    """Join artist names with ', ', stripping non-breaking and stray spaces.

    >>> clean_artists("Taylor Swift,\xa0Lana Del Rey")
    'Taylor Swift, Lana Del Rey'
    """
    if isinstance(artists, str):
        parts = artists.split(",")
    else:
        parts = list(artists or [])
    cleaned = []
    for part in parts:
        name = str(part or "").replace(_NBSP, " ").strip()
        name = _WS.sub(" ", name)
        if name:
            cleaned.append(name)
    return ", ".join(cleaned)


def clean_title(title: str) -> str:
    """Normalise whitespace only. The wording itself is left alone."""
    return _WS.sub(" ", str(title or "").replace(_NBSP, " ").strip())


def download_cover(url: str, timeout: int = 45) -> Optional[bytes]:
    """Fetch album art bytes, or None. Never raises.

    The URL is upgraded to the 640x640 variant first. This is the safety net for
    cover art embedded in the MP3: callers upstream already upgrade, but a track
    built by hand (or a stale cache) can still hand us a 300x300 URL, and a
    blurry cover is what the user complained about in the first place.
    """
    if not url:
        return None
    from .base import upgrade_cover_url

    req = urllib.request.Request(upgrade_cover_url(url), headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return data or None
    except Exception:  # noqa: BLE001 - artwork is optional
        return None


def write_tags(path: Path, title: str = "", artist: str = "", album: str = "",
               year: int = 0, track_number: int = 0, disc_number: int = 0,
               label: str = "", cover_url: str = "",
               cover_bytes: Optional[bytes] = None) -> dict:
    """Write ID3 tags (and cover art) onto ``path`` in place.

    The audio stream is NOT modified — mutagen edits the ID3 container only, so
    bitrate and duration are unchanged. Returns a small report of what was
    written, which is handy for logging and for the tests.

    Never raises: a failure is reported in the returned dict.
    """
    report = {"ok": False, "tags": [], "cover": False, "error": ""}

    path = Path(path)
    if not path.exists():
        report["error"] = f"file tidak ada: {path}"
        return report

    try:
        from mutagen.id3 import (APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1,
                                 TPOS, TRCK, TPUB)
        from mutagen.mp3 import MP3
    except ImportError as exc:  # pragma: no cover - dependency guard
        report["error"] = f"mutagen belum terpasang: {exc}"
        return report

    try:
        audio = MP3(path)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"gagal membuka MP3: {exc}"
        return report

    try:
        tags = ID3()
    except Exception:  # noqa: BLE001 - no ID3 block yet
        tags = None

    def put(frame) -> None:
        try:
            tags.add(frame)
            report["tags"].append(frame.FrameID)
        except Exception:  # noqa: BLE001 - a single bad frame must not abort
            pass

    clean_t = clean_title(title)
    clean_a = clean_artists(artist)
    if clean_t:
        put(TIT2(encoding=3, text=clean_t))
    if clean_a:
        put(TPE1(encoding=3, text=clean_a))
    if album:
        put(TALB(encoding=3, text=clean_title(album)))
    try:
        if int(year or 0) > 0:
            put(TDRC(encoding=3, text=str(int(year))))
    except (TypeError, ValueError):
        pass
    try:
        num = int(track_number or 0)
    except (TypeError, ValueError):
        num = 0
    if num > 0:
        try:
            disc = int(disc_number or 0)
        except (TypeError, ValueError):
            disc = 0
        put(TRCK(encoding=3, text=f"{num}/{disc}" if disc > 0 else str(num)))
        if disc > 0:
            put(TPOS(encoding=3, text=str(disc)))
    if label:
        put(TPUB(encoding=3, text=clean_title(label)))
        put(TCON(encoding=3, text=clean_title(label)))

    # Cover art is optional: a failure here must not lose the text tags.
    art = cover_bytes
    if art is None:
        art = download_cover(cover_url)
    if art:
        try:
            tags.delall("APIC")
        except Exception:  # noqa: BLE001
            pass
        try:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3,
                          desc="Cover", data=art))
            report["cover"] = True
        except Exception:  # noqa: BLE001
            pass

    try:
        if tags.keys():
            audio.tags = tags
            audio.save(v2_version=3)
            report["ok"] = True
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"gagal menyimpan tag: {exc}"
        return report

    report["tags"].sort()
    return report


def read_tags(path: Path) -> dict:
    """Read back the tags we care about. Used by the tests and for debugging."""
    try:
        from mutagen.id3 import ID3

        tags = ID3(Path(path))
        apic = tags.getall("APIC")
        return {
            "title": str(tags.get("TIT2", "")),
            "artist": str(tags.get("TPE1", "")),
            "album": str(tags.get("TALB", "")),
            "date": str(tags.get("TDRC", "")),
            "track": str(tags.get("TRCK", "")),
            "publisher": str(tags.get("TPUB", "")),
            "cover_bytes": len(apic[0].data) if apic else 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def audio_fingerprint(path: Path) -> dict:
    """Bitrate / length / file size — used to PROVE tagging changed no audio.

    ``MPEGInfo`` has no ``size`` attribute (that is ffprobe's field name), so the
    size comes from the file itself.
    """
    import os

    try:
        from mutagen.mp3 import MP3

        audio = MP3(Path(path))
        info = audio.info
        return {
            "length": round(float(info.length), 3),
            "bitrate": int(info.bitrate),
            "size": int(os.path.getsize(path)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}