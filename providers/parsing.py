"""Tolerant HTML/JSON parsing helpers used by the providers.

SoundLoaders and SpotiDown both return *HTML fragments* (rendered by a template
engine) rather than clean APIs, and they change their markup from time to time.
Every function here is defensive: it never raises on unknown markup, it only
extracts whatever is present and lets the caller decide what "no tracks" means.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List

from bs4 import BeautifulSoup, Tag


def _lxml_available() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except Exception:
        return False  # pragma: no cover


# Prefer the fast C-based lxml parser; bs4 falls back to the stdlib
# html.parser automatically if lxml is not installed, so this never crashes.
HTML_PARSER = "lxml" if _lxml_available() else "html.parser"

# Regexes tuned to the actual markup of soundloaders.app (July 2026).
TRACK_LI_RE = re.compile(r"track-list-item|li-item|playlist-song", re.I)
TITLE_ATTR_RE = re.compile(r"(?:track|song|music)[-_ ]?title|data[-_]title", re.I)
ARTIST_ATTR_RE = re.compile(r"artist", re.I)
THUMB_ATTR_RE = re.compile(r"(?:img|image|cover|thumb)", re.I)


def parse_track_rows(html: str) -> List[Tag]:
    """Return all <li>/<div> elements that look like one track row.

    The two services render each track as an <li> containing a <form> whose
    ``name`` is ``submitspurl`` (SoundLoaders) or ``submitspurl`` with extra
    inputs (SpotiDown). We first look for rows *holding* such a form because that
    is the strongest signal, then fall back to elements carrying a data/track
    token pair.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, HTML_PARSER)

    rows: List[Tag] = []
    seen = set()

    def _push(tag: Tag) -> None:
        if id(tag) not in seen:
            seen.add(id(tag))
            rows.append(tag)

    for form in soup.find_all("form", {"name": "submitspurl"}):
        row = _container_row(form)
        _push(row or form)

    # Fallback: standalone <li> items that embed token inputs.
    for li in soup.find_all(["li", "div"]):
        if li.find("form"):
            continue  # already covered above
        attrs = _attr_text(li)
        if (li.get("class") and TRACK_LI_RE.search(" ".join(li.get("class")))) or "track_token" in attrs:
            if li.find("input", {"name": "track_token"}) or li.find("input", {"name": "data"}):
                _push(li)
    return rows


def _container_row(form: Tag) -> Tag:
    """Walk up from a track <form> to the <li>/<div> that wraps the whole row."""
    node: Any = form
    for _ in range(4):
        parent = node.find_parent(["li", "div"])
        if parent is None:
            break
        node = parent
        classes = parent.get("class") or []
        if any(TRACK_LI_RE.search(str(c)) for c in classes):
            break
    return node if node is not form else form


def extract_form_values(row: Tag) -> Dict[str, str]:
    """Read every <input>/<textarea> of the first 'submitspurl' form in a row.

    Replays the *whole* serialized form (like a browser's FormData) so we keep
    provider anti-CSRF fields (SpotiDown ships ``data``, ``base``, ``token``,
    ``_uMihH``, ...) without hard-coding their names.
    """
    out: Dict[str, str] = {}
    form = row.find("form", {"name": "submitspurl"})
    nodes = [form] if form else [row]
    for node in nodes:
        for inp in node.find_all(["input", "textarea"]):
            name = inp.get("name")
            if not name:
                continue
            kind = (inp.get("type") or "text").lower()
            if kind in ("submit", "button", "image"):
                continue
            val = inp.get("value") or inp.get_text(strip=True) or ""
            if name not in out:  # first occurrence wins
                out[name] = val
    return out


def track_from_row(row: Tag) -> Dict[str, Any]:
    """Best-effort metadata extraction for one track row.

    Never raises. Falls back to "Unknown" values so a markup change still yields
    a usable row (only data/track_token matter for the download itself).
    """
    values = extract_form_values(row)
    data = values.get("data", "")
    token = values.get("track_token", "") or values.get("token", "")

    title = values.get("title") or ""
    artist = values.get("artist") or ""
    thumb = values.get("thumbnail") or values.get("img") or ""

    # Try the visible text first, then dedicated attribute names.
    title = title or _title_from_text(row) or _attr_value(row, TITLE_ATTR_RE) or "Unknown"
    artist = artist or _artist_from_text(row) or _attr_value(row, ARTIST_ATTR_RE) or "Unknown"
    thumb = thumb or _thumb_url(row) or ""

    title = _clean(title) or "Unknown"
    artist = _clean(artist) or "Unknown"
    return {"data": data, "track_token": token, "title": title, "artist": artist, "thumbnail": thumb}


def _title_from_text(row: Tag) -> str:
    for el in row.find_all(["h3", "h4", "h5", "h6", "p", "strong", "span", "b"]):
        text = _clean(el.get_text(" ", strip=True))
        # Heuristic: heading-ish element with a short, non-empty text.
        if text and len(text) <= 200 and not _looks_like_button(text):
            return text
    return ""


def _artist_from_text(row: Tag) -> str:
    # Look for elements whose id/class contains "artist" first.
    for el in row.select("[id*=artist i], [class*=artist i]"):
        text = _clean(el.get_text(" ", strip=True))
        if text:
            return text
    texts = [_clean(el.get_text(" ", strip=True)) for el in row.find_all(["p", "span", "small", "div"])]
    texts = [t for t in texts if t]
    if not texts:
        return ""
    # The row's artist is usually the text that is NOT the title. Pick the
    # shortest paragraph-like string — good enough for a UI label.
    return min(texts, key=len)


def _attr_value(row: Tag, pattern: re.Pattern) -> str:
    for el in row.find_all(True):
        for attr, val in el.attrs.items():
            if isinstance(val, str) and pattern.search(attr):
                return val
    return ""


def _thumb_url(row: Tag) -> str:
    for img in row.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src:
            return src
    for el in row.find_all(True):
        style = (el.get("style") or "")
        m = re.search(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", style)
        if m:
            return m.group(1)
    return ""


def _attr_text(tag: Tag) -> str:
    return " ".join(f"{k}={v}" for k, v in tag.attrs.items() if isinstance(v, str))


def _looks_like_button(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in ("download", "processing", "gagal", "failed", "ready", "waiting", "play"))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- JSON helpers

def parse_json_payload(text: str) -> Dict[str, Any]:
    """Parse a JSON object from a provider response without raising."""
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def decode_track_data(raw: str) -> Dict[str, Any]:
    """Decode SpotiDown's base64 JSON stored in the hidden 'data' field.

    ``raw`` is the base64 string; the value decodes to e.g.
    ``{"name": "...", "artist": "...", ...}``.
    """
    if not raw:
        return {}
    try:
        import base64

        decoded = base64.b64decode(raw.encode("ascii")).decode("utf-8", "replace")
        return json.loads(decoded) if isinstance(decoded, str) else {}
    except Exception:
        return {}


def first_mp3_link(html: str) -> str:
    """Find the first MP3 download URL in provider HTML (href or <source>)."""
    if not html:
        return ""
    for href in re.findall(r'https?://[^\s"\'<>]+?\.mp3(?:[^\s"\'<>]*)?', html, re.I):
        return href
    # <audio><source src=...> fallback without .mp3 extension
    for src in re.findall(r'<source[^>]+src=["\']([^"\']+)["\']', html, re.I):
        return src
    return ""


def iter_links(html: str) -> Iterable[str]:
    return re.findall(r'https?://[^\s"\'<>]+', html or "")
