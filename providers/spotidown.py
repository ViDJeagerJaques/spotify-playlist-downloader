"""SpotiDown client — the fallback Spotify downloader backend.

DEPENDENCY NOTE
---------------
All Spotify resolution here is delegated to spotidown.app. Like SoundLoaders,
SpotiDown uses Cloudflare and a session cookie, and every request this module
makes replays the exact form fields a real browser would send.

Real-world mapping (verified against the live site, July 2026):
  * GET  https://spotidown.app/        -> HTML, sets `session_data` cookie; the
        page contains a hidden anti-CSRF input named ``_uMihH`` whose value is
        per-page (must be scraped fresh from the homepage).
  * POST https://spotidown.app/action  -> body = url + g-recaptcha-response +
        _uMihH. Returns {"error":false,"data":"<track list HTML>"} on success,
        or {"error":true,"message":...} e.g.
        {"error":true,"message":"Please Refresh the page & try again.",
         "errorcode":"error_token"} when the CSRF/captcha does not match.
  * POST https://spotidown.app/action/track -> body = one serialized track form
        (data/base/token/_uMihH). Returns {"error":false,"data":"<mp3 link>"}
        or {"error":true,...}.
Captcha is Google reCAPTCHA v3 (sitekey 6LcXkaUqAAAAAGvO0z9Mg54lpG22HE4gkl3XYFTK).
A valid token can only be produced by the real widget in a browser, so this app
expects the user to paste one. Note: the official UI additionally offers ZIP
bundling via /action/bulktrack + /action/create_zip and gates it at 5 tracks for
free users — we do NOT call those endpoints; we always resolve per-track and let
the orchestrator build a local ZIP instead.
"""
from __future__ import annotations

from typing import Dict, List

from bs4 import BeautifulSoup

from .base import CaptchaRequiredError, ProviderId, ResolveResult, ServiceError, Track
from .parsing import (
    HTML_PARSER,
    _clean,
    decode_track_data,
    first_mp3_link,
    parse_json_payload,
    parse_track_rows,
    track_from_row,
)
from ._http import TIMEOUT, make_session

BASE_URL = "https://spotidown.app"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}


class SpotiDownClient:
    def __init__(self, timeout: int = TIMEOUT):
        self.name = "SpotiDown"
        self.provider = ProviderId.SPOTIDOWN
        self._timeout = timeout
        self._session = None
        self._anti_csrf = ""  # hidden _uMihH value scraped from homepage

    def _get_session(self):
        if self._session is None:
            self._session = make_session()
        return self._session

    def _open_session(self):
        """GET homepage -> session cookie + fresh _uMihH anti-CSRF value."""
        s = self._get_session()
        r = s.get(BASE_URL + "/", timeout=self._timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, HTML_PARSER)
        inp = soup.find("input", {"name": "_uMihH"})
        self._anti_csrf = (inp.get("value") or "") if inp else ""
        return s

    def _post_form(self, s, path: str, data: Dict[str, str]) -> dict:
        resp = s.post(BASE_URL + path, data=data, headers=FORM_HEADERS, timeout=self._timeout)
        return parse_json_payload(resp.text)

    # ----------------------------------------------------------- public API

    def load_tracks(self, spotify_url: str, cftoken: str = "") -> ResolveResult:
        """POST /action and parse the returned track rows (same flow as site)."""
        cftoken = (cftoken or "").strip()
        self._open_session()
        if not self._anti_csrf:
            raise ServiceError(
                "SpotiDown page layout changed: anti-CSRF field (_uMihH) not found.",
                details="No <input name='_uMihH'> on https://spotidown.app/",
            )
        payload = self._post_form(
            self._session,
            "/action",
            {
                "url": spotify_url,
                "g-recaptcha-response": cftoken or "",
                "_uMihH": self._anti_csrf,
            },
        )
        if payload.get("error") is True:
            self._raise_action_error(payload, cftoken)

        html = str(payload.get("data") or "")
        rows = parse_track_rows(html)
        tracks: List[Track] = []
        for row in rows:
            meta = track_from_row(row)
            # SpotiDown stores full metadata base64 in `data`; enrich labels when
            # the parsed title/artist look like placeholders.
            decoded = decode_track_data(meta["data"])
            if decoded:
                meta["title"] = meta["title"] if meta["title"] != "Unknown" else str(decoded.get("name") or "Unknown")
                meta["artist"] = (
                    meta["artist"] if meta["artist"] != "Unknown" else str(decoded.get("artist") or "Unknown")
                )
            if meta["data"]:
                tracks.append(Track(**meta))
        title = self._guess_title(html) or spotify_url
        return ResolveResult(title=title, source_url=spotify_url, tracks=tracks)

    def resolve_track(self, track: Track, cftoken: str = "") -> str:
        """POST /action/track with the full serialized track form -> MP3 URL."""
        cftoken = (cftoken or "").strip()
        if not self._session or not self._anti_csrf:
            self._open_session()
        form_data = {
            "data": track.data,
            "track_token": track.track_token,
            "g-recaptcha-response": cftoken or "",
            "_uMihH": self._anti_csrf,
        }
        payload = self._post_form(self._session, "/action/track", form_data)
        if payload.get("error") is True:
            self._raise_track_error(payload, cftoken)

        html = str(payload.get("data") or "")
        mp3 = first_mp3_link(html)
        if not mp3:
            raise ServiceError(
                "SpotiDown returned no MP3 link for this track.",
                details=f"/action/track html snippet: {html[:300]}",
            )
        return mp3

    # -------------------------------------------------------------- helpers

    def _raise_action_error(self, payload: dict, cftoken: str) -> None:
        message = str(payload.get("message") or "SpotiDown could not process the URL.")
        errorcode = str(payload.get("errorcode") or "")
        if errorcode == "error_token" or not cftoken:
            raise CaptchaRequiredError(
                "SpotiDown requires a valid reCAPTCHA v3 token.",
                details=f"POST /action -> {message} (errorcode={errorcode}, token_len={len(cftoken or '')})",
            )
        raise ServiceError(f"SpotiDown: {message}")

    def _raise_track_error(self, payload: dict, cftoken: str) -> None:
        message = str(payload.get("message") or "Track download failed.")
        if not cftoken or "token" in message.lower():
            raise CaptchaRequiredError(
                "SpotiDown requires a valid reCAPTCHA v3 token.",
                details=f"POST /action/track -> {message}",
            )
        raise ServiceError(f"SpotiDown: {message}")

    def _guess_title(self, html: str) -> str:
        """Grab a plausible title from the track-list page (e.g. an <h3>)."""
        soup = BeautifulSoup(html or "", HTML_PARSER)
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = _clean(h.get_text(" ", strip=True))
            if text:
                return text
        return ""
