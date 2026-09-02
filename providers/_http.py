"""HTTP session helpers shared by the provider clients.

The providers sit behind Cloudflare; a plain ``requests.Session`` that mimics a
desktop browser (UA, headers, cookies) is enough to get a session cookie.
"""
from __future__ import annotations

from typing import Optional

import requests

TIMEOUT = 25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def make_session(cookies_from: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    if cookies_from:
        s.cookies.update(cookies_from)
    return s


def serialize_form_urlencoded(session: requests.Session, url: str) -> None:
    """Keep Content-Type consistent with browser form posts."""
    session.headers.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
