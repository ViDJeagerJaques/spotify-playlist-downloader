"""SoundLoaders client — SoundLoaders.app Spotify downloader backend.

DEPENDENCY NOTE
---------------
This is the *only* place where the app knows about SoundLoaders. Every request
this app ever makes to SoundLoaders happens through the three methods below.
If SoundLoaders is down, rate-limits, changes its endpoints or starts requiring
Cloudflare Turnstile without a bypass, nothing else in this app can fall back —
Spotify content resolution is 100% delegated to this external service.

Real-world mapping (verified against the live site, not just the PRD):
  * GET  https://soundloaders.app/            -> HTML, sets `session_data` cookie.
  * POST https://soundloaders.app/api/userverify  -> was the old server-side
        token fallback used by their script.js. It currently returns 404, so the
        PRD's "fetch /api/userverify to obtain a token" step can NO LONGER be
        implemented. We keep it only as an optional attempt behind a flag.
  * POST https://soundloaders.app/action       -> body {url, cftoken}; returns
        JSON {"status": true, "html": "<track rows>"} or
        {"status": false, "error": "..."} (e.g. "CAPTCHA verification failed.").
  * POST https://soundloaders.app/action/tracks -> body = serialized track form
        (data + track_token); returns {"status": true, "html": "<mp3 download>"}
        or {"status": false, "error": "..."}.
The `cftoken` value is a Cloudflare Turnstile token. It can only be minted by a
real browser widget (sitekey 0x4AAAAAADdgLDfT5kFRbt_5); there is no plain
server-side API for it, so this app lets the user paste their own token.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .base import CaptchaRequiredError, ProviderId, ResolveResult, ServiceError, Track
from .parsing import (
    _clean,
    first_mp3_link,
    parse_json_payload,
    parse_track_rows,
    track_from_row,
)
from ._http import TIMEOUT, make_session

BASE_URL = "https://soundloaders.app"
FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


class SoundLoadersClient:
    def __init__(self, timeout: int = TIMEOUT):
        self.name = "SoundLoaders"
        self.provider = ProviderId.SOUNDLOADERS
        self._timeout = timeout
        self._session = None  # lazy; gives us a fresh cookie jar per request cycle

    # ------------------------------------------------------------- HTTP helpers

    def _get_session(self):
        if self._session is None:
            self._session = make_session()
        return self._session

    def _open_session(self):
        """Fetch homepage so the service issues its session cookie."""
        s = self._get_session()
        r = s.get(BASE_URL + "/", timeout=self._timeout)
        r.raise_for_status()
        return s

    def _post_form(self, s, path: str, data: Dict[str, str]) -> dict:
        resp = s.post(
            BASE_URL + path,
            data=data,
            headers=FORM_HEADERS,
            timeout=self._timeout,
        )
        return parse_json_payload(resp.text)

    # ----------------------------------------------------------- public API

    def load_tracks(self, spotify_url: str, cftoken: str = "") -> ResolveResult:
        """POST /action with {url, cftoken} and parse the track list HTML."""
        cftoken = (cftoken or "").strip()
        self._open_session()
        s = self._session
        payload = self._post_form(s, "/action", {"url": spotify_url, "cftoken": cftoken or ""})
        if payload.get("status") is False or "html" not in payload:
            self._raise_action_error(payload, cftoken)

        html = str(payload.get("html") or "")
        rows = parse_track_rows(html)
        tracks: List[Track] = []
        for row in rows:
            meta = track_from_row(row)
            if meta["data"] and meta["track_token"]:
                tracks.append(Track(**meta))
            elif meta["data"]:
                # data present but token lookup failed on this row -> keep row,
                # token-less rows cannot be resolved later so skip silently.
                pass

        title = self._guess_title(html) or spotify_url
        return ResolveResult(title=title, source_url=spotify_url, tracks=tracks)

    def resolve_track(self, track: Track, cftoken: str = "") -> str:
        """POST /action/tracks with the row's data + track_token -> MP3 URL."""
        cftoken = (cftoken or "").strip()
        if not self._session:
            self._open_session()
        payload = self._post_form(
            self._session,
            "/action/tracks",
            {"data": track.data, "track_token": track.track_token, "cftoken": cftoken},
        )
        if payload.get("status") is False or "html" not in payload:
            err = str(payload.get("error") or "Track resolution failed.")
            if _looks_like_captcha(payload):
                raise CaptchaRequiredError(
                    "SoundLoaders rejected the request (CAPTCHA / token).",
                    details=f"Action /action/tracks returned: {err} (token_len={len(cftoken)})",
                )
            raise ServiceError(f"SoundLoaders could not resolve the track: {err}")

        html = str(payload.get("html") or "")
        mp3 = first_mp3_link(html)
        if not mp3:
            raise ServiceError(
                "SoundLoaders returned no MP3 link for this track.",
                details=f"/action/tracks html snippet: {html[:300]}",
            )
        return mp3

    # -------------------------------------------------------------- helpers

    def _raise_action_error(self, payload: dict, cftoken: str) -> None:
        error = str(payload.get("error") or "The service did not return a track list.")
        if _looks_like_captcha(payload) or not cftoken:
            raise CaptchaRequiredError(
                "SoundLoaders requires a valid Cloudflare Turnstile token.",
                details=f"POST /action returned: {error} (token_len={len(cftoken or '')})",
            )
        raise ServiceError(f"SoundLoaders: {error}")

    def _guess_title(self, html: str) -> str:
        m = re.search(r'<h[123][^>]*>\s*([^<]{2,160}?)\s*</h[123]>', html)
        if m:
            return _clean(m.group(1))
        return ""


def _looks_like_captcha(payload: dict) -> bool:
    text = f"{payload.get('error', '')} {payload.get('message', '')}".lower()
    return any(k in text for k in ("captcha", "turnstile", "token", "verify"))
