"""Tests for the ID3 tagging layer (R4).

Why this exists: files came out tagged with YouTube's data — ``artist`` was the
channel name ("David Dean Burkhart"), ``album`` was empty and there was no cover.
This module writes Spotify's own tags instead, WITHOUT touching the audio.

Everything here is offline and uses a tiny silent MP3 generated on the fly, so
no download and no ffmpeg run is needed. The important assertions:

* artist/album/date/track/publisher land correctly;
* the non-breaking space in ``'Taylor Swift,\xa0Lana Del Rey'`` is removed;
* an empty field is skipped rather than written as an empty string;
* a failed cover download still leaves the text tags intact;
* **the audio stream is unchanged** — bitrate and length before == after.

Run:  python tests/test_tags.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.tags import (  # noqa: E402
    audio_fingerprint,
    clean_artists,
    clean_title,
    download_cover,
    read_tags,
    write_tags,
)

PASS = []
FAIL = []

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff03000006000557bfabd4"
    "0000000049454e44ae426082")


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    if not cond:
        print(f"  FAIL: {name} {detail}")


def make_mp3(path: Path, seconds: int = 2) -> None:
    """Render a silent MP3 with ffmpeg so we have real MPEG frames to tag."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"anullsrc=r=44100:cl=mono", "-t", str(seconds),
         "-b:a", "128k", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not path.exists():
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[:300]}")


# ------------------------------------------------------------- text cleaning
def test_clean_artists_nbsp():
    """A non-breaking space really does occur in Spotify artist strings."""
    got = clean_artists("Taylor Swift,\xa0Lana Del Rey")
    check("tags: nbsp removed", "\xa0" not in got, repr(got))
    check("tags: joined with ', '", got == "Taylor Swift, Lana Del Rey", repr(got))


def test_clean_artists_list_and_noise():
    check("tags: list input",
          clean_artists(["A", "B"]) == "A, B", clean_artists(["A", "B"]))
    check("tags: blanks dropped",
          clean_artists(["A", "", "  ", None, "B"]) == "A, B",
          repr(clean_artists(["A", "", "  ", None, "B"])))
    check("tags: inner spaces collapsed",
          clean_artists("A   B") == "A B", repr(clean_artists("A   B")))
    check("tags: empty input", clean_artists("") == "", repr(clean_artists("")))


def test_clean_title_keeps_wording():
    """The title must stay verbatim — '(feat. …)' included."""
    raw = "Snow On The Beach (feat. More Than Forever)"
    check("tags: title wording kept", clean_title(raw) == raw, clean_title(raw))
    check("tags: title nbsp normalised",
          clean_title("A\xa0B") == "A B", repr(clean_title("A\xa0B")))


# ------------------------------------------------------------- tagging
def test_write_tags_full(tmp: Path):
    f = tmp / "song.mp3"
    make_mp3(f)
    before = audio_fingerprint(f)

    report = write_tags(
        f,
        title="Cinnamon Girl",
        artist="Lana Del Rey",
        album="Norman Fucking Rockwell!",
        year=2019, track_number=7, disc_number=1,
        label="Polydor Records",
        cover_bytes=PNG_1PX,
    )
    check("tags: report ok", report["ok"] is True, str(report))
    check("tags: cover written", report["cover"] is True, str(report))

    got = read_tags(f)
    check("tags: title", got["title"] == "Cinnamon Girl", got["title"])
    check("tags: artist is the SINGER, not the channel",
          got["artist"] == "Lana Del Rey", got["artist"])
    check("tags: album", got["album"] == "Norman Fucking Rockwell!", got["album"])
    check("tags: date", got["date"] == "2019", got["date"])
    check("tags: track number", got["track"] == "7/1", got["track"])
    check("tags: publisher", got["publisher"] == "Polydor Records", got["publisher"])
    check("tags: cover embedded", got["cover_bytes"] == len(PNG_1PX),
          str(got["cover_bytes"]))

    after = audio_fingerprint(f)
    check("tags: bitrate unchanged", before["bitrate"] == after["bitrate"],
          f"{before['bitrate']} -> {after['bitrate']}")
    check("tags: length unchanged", before["length"] == after["length"],
          f"{before['length']} -> {after['length']}")


def test_write_tags_overwrites_channel_name(tmp: Path):
    """The regression: a YouTube channel must not survive as the artist."""
    f = tmp / "chan.mp3"
    make_mp3(f)
    # Pretend yt-dlp already wrote its tags.
    try:
        from mutagen.id3 import ID3, TALB, TPE1

        tags = ID3()
        tags.add(TPE1(encoding=3, text="David Dean Burkhart"))
        tags.add(TALB(encoding=3, text=""))
        MP3_ = __import__("mutagen.mp3", fromlist=["MP3"]).MP3(f)
        MP3_.tags = tags
        MP3_.save(v2_version=3)
    except Exception:  # noqa: BLE001
        pass

    write_tags(f, title="Cinnamon Girl", artist="Lana Del Rey",
               album="Norman Fucking Rockwell!", year=2019)
    got = read_tags(f)
    check("tags: channel name replaced", got["artist"] == "Lana Del Rey", got["artist"])
    check("tags: 'David Dean Burkhart' gone",
          "Burkhart" not in got["artist"], got["artist"])


def test_write_tags_skips_empty_fields(tmp: Path):
    f = tmp / "sparse.mp3"
    make_mp3(f)
    write_tags(f, title="Only Title", artist="", album="", year=0,
               track_number=0, label="", cover_url="")
    got = read_tags(f)
    check("tags: title written", got["title"] == "Only Title", got["title"])
    check("tags: empty artist not written", got["artist"] == "", repr(got["artist"]))
    check("tags: empty album not written", got["album"] == "", repr(got["album"]))
    check("tags: empty date not written", got["date"] == "", repr(got["date"]))


def test_failed_cover_keeps_text_tags(tmp: Path):
    """Cover is optional: a dead URL must not cost us the text tags."""
    f = tmp / "nocover.mp3"
    make_mp3(f)
    report = write_tags(f, title="T", artist="A", album="Al", year=2020,
                        cover_url="https://127.0.0.1:1/nope.jpg")
    check("tags: still ok without cover", report["ok"] is True, str(report))
    check("tags: cover reported missing", report["cover"] is False, str(report))
    got = read_tags(f)
    check("tags: text tags survived", got["title"] == "T" and got["artist"] == "A",
          str(got))


def test_missing_file_reports_not_raises(tmp: Path):
    report = write_tags(tmp / "ghost.mp3", title="x")
    check("tags: missing file -> ok False", report["ok"] is False, str(report))
    check("tags: missing file -> error text", bool(report["error"]), str(report))


def test_download_cover_failure_is_none():
    check("tags: bad url -> None", download_cover("https://127.0.0.1:1/x.jpg") is None)
    check("tags: empty url -> None", download_cover("") is None)


def test_nbsp_artist_end_to_end(tmp: Path):
    """The exact string from the real playlist must come out clean."""
    f = tmp / "multi.mp3"
    make_mp3(f)
    write_tags(f, title="Snow On The Beach",
               artist="Taylor Swift,\xa0Lana Del Rey",
               album="Midnights", year=2023, track_number=22)
    got = read_tags(f)
    check("tags: nbsp gone in file", "\xa0" not in got["artist"], repr(got["artist"]))
    check("tags: both artists kept",
          got["artist"] == "Taylor Swift, Lana Del Rey", got["artist"])


def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_clean_artists_nbsp()
        test_clean_artists_list_and_noise()
        test_clean_title_keeps_wording()
        test_write_tags_full(tmp)
        test_write_tags_overwrites_channel_name(tmp)
        test_write_tags_skips_empty_fields(tmp)
        test_failed_cover_keeps_text_tags(tmp)
        test_missing_file_reports_not_raises(tmp)
        test_download_cover_failure_is_none()
        test_nbsp_artist_end_to_end(tmp)

    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        print("Failures:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()