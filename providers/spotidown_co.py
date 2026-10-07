"""SpotiDown.co client — the PRIMARY backend (replaces the two dead providers).

DEPENDENCY NOTE
---------------
This module has no Spotify scraper of its own. Every bit of Spotify metadata and
every MP3 URL comes from ``api.spotidown.co``, a third-party service. If that
site shuts down, changes its API, or changes its HTML selectors, this provider
stops working — there is no local fallback for the *listing* step.

WHY THIS EXISTS
---------------
The two previous providers (``soundloaders.app`` via Turnstile, ``spotidown.app``
via reCAPTCHA v3) require a CAPTCHA token that is bound to the browser session
that solved it (cookie + IP). Streamlit runs in a different process with a
different identity, so a token minted in the user's browser could not be replayed
server-side. Both were therefore unusable in practice.

``spotidown.co`` solves its own Cloudflare challenge *inside a real browser*. We
let the page do that and simply read the JSON it fetches.

HOW IT WORKS (verified end-to-end; see ``tools/spotidown_grab.py``)
------------------------------------------------------------------
1. We launch Chrome OURSELVES with ``--remote-debugging-port`` (no
   ``--enable-automation``, no ``--disable-blink-features=AutomationControlled``),
   then attach over CDP. That leaves no automation fingerprint, so Cloudflare's
   Turnstile renders and mints its token normally.
   Do NOT "simplify" this to ``playwright.chromium.launch()``: it was tried six
   times and is always rejected ("No available adapters", the Turnstile widget
   never renders).
2. Open the site, fill ``input.link``, click ``button.search-btn``.
3. Capture the site's own ``api.spotidown.co/search/...`` JSON response.
4. Every track already carries a ready MP3 URL in ``audio.url`` — unlike
   SoundLoaders there is NO per-track resolve request.

KNOWN TRAPS — all hit during trial-and-error, all handled here. Do not undo them:

1. **Background tab throttling.** Waiting with a plain ``time.sleep()`` makes
   Chrome throttle the tab, the Turnstile widget never runs, and the page hangs
   on "Searching..." forever. We keep the renderer hot by polling
   ``page.evaluate()`` in a tight loop while waiting.
2. **Only ONE spotidown tab at a time.** The page loads
   ``challenges.cloudflare.com/turnstile/v0/api.js`` once per page; a second
   spotidown tab makes ``window.turnstile`` undefined and the site's own
   ``main.js`` crash inside ``turnstile.render()``, hanging the flow. We close
   every stale spotidown tab before opening ours.
3. **The CDN rejects a random share of requests** (it redirects to
   ``*.123tokyo.xyz``). Which URLs fail differs every run — it is not certain
   tracks. Retries with jitter are handled by the fetcher in
   ``core/orchestrator.py``, and the app runs downloads serially to stay well
   under the limit that triggers rejections.
4. **MP3 links expire quickly.** The ``sig`` query parameter is short-lived, so
   downloading must happen right after the JSON arrives; never store these URLs
   for later.
5. **Chrome takes ~10s to come up.** Callers must show a spinner/status and tell
   the user not to close the window that appears.

REQUIREMENTS AND TRADE-OFFS
----------------------------
* **Chrome must be installed on the user's machine.** Without it this provider
  raises a clear ``ServiceError`` instead of failing obscurely.
* **Chrome opens VISIBLY — it is never headless.** That is a hard requirement:
  Cloudflare rejects anything that looks automated. The user will see a browser
  window appear and must leave it alone.
* **Free tier is capped at 100 tracks per playlist.** This is the service's own
  official limit and we honour it: when ``totalCount`` is larger than the number
  of returned tracks we report the truncation instead of trying to work around
  it. No premium is bypassed anywhere in this app.
* **Legal.** Downloading Spotify audio through a third-party service may violate
  Spotify's Terms of Service and the service's own terms. Personal use only — do
  not redistribute or publish the results.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .base import ProviderId, ResolveResult, ServiceError, Track

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CDP_PORT = 9222
SITE = "https://spotidown.co/en16"
SITE_ORIGIN = "https://spotidown.co"
PROFILE_DIR = Path(__file__).resolve().parents[1] / "tools" / "cdp-profile"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

# Headers the MP3 endpoint expects. Verified working; without Origin/Referer the
# CDN answers 403. There is NO CAPTCHA on the download link itself.
DOWNLOAD_HEADERS = {
    "User-Agent": UA,
    "Origin": SITE_ORIGIN,
    "Referer": SITE_ORIGIN + "/",
}

# Official free-tier cap reported by the service: a playlist with 213 tracks
# comes back with totalCount=213 but only 100 track objects.
FREE_TIER_LIMIT = 100

DEFAULT_WAIT_SECONDS = 90
# How many times we click Search on the loaded page. Each click mints a fresh
# `sig`; observed behaviour is that a click answered with HTTP 500 is followed
# by a successful one.
SEARCH_ATTEMPTS = 4
# How long to wait for one click's response before clicking again.
RESPONSE_WAIT_SECONDS = 35


# --------------------------------------------------------------------------
# chrome lifecycle (trap: launch ourselves, never playwright.launch)
# --------------------------------------------------------------------------
def find_chrome() -> Optional[str]:
    """Return the path to a Chrome executable, or None when not installed."""
    for candidate in CHROME_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def cdp_alive(port: int = CDP_PORT, timeout: int = 3) -> bool:
    """True when a Chrome with a CDP endpoint already answers on `port`."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", str(timeout), f"http://127.0.0.1:{port}/json/version"],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        return '"Browser"' in (r.stdout or "")
    except Exception:  # noqa: BLE001 - curl missing / timeout / refused
        return False


def launch_chrome(chrome: str, port: int = CDP_PORT) -> subprocess.Popen:
    """Start a real Chrome with a CDP port. Visible window, no automation flags."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,900",
        "about:blank",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_chrome(port: int = CDP_PORT) -> Tuple[Optional[subprocess.Popen], str]:
    """Reuse a running CDP session or launch a new one.

    Returns (process_or_None_if_reused, chrome_path). The caller owns the
    returned process; we deliberately do NOT terminate Chrome when the run
    finishes, because the user may be looking at that window.
    """
    chrome = find_chrome()
    if chrome is None:
        raise ServiceError(
            "Chrome tidak ditemukan. Provider SpotiDown.co butuh Google Chrome "
            "terinstall di komputer ini.",
            details="Looked for: " + ", ".join(CHROME_CANDIDATES),
        )
    if cdp_alive(port):
        return None, chrome
    proc = launch_chrome(chrome, port)
    for _ in range(30):
        time.sleep(0.5)
        if cdp_alive(port):
            return proc, chrome
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass
    raise ServiceError(
        "Chrome sempat berjalan tapi port debug CDP tidak pernah aktif.",
        details=f"Expected a CDP endpoint on http://127.0.0.1:{port}/json/version",
    )


# --------------------------------------------------------------------------
# pure parsing (unit-tested offline against a real captured payload)
# --------------------------------------------------------------------------
def parse_search_payload(data: dict, source_url: str = "") -> ResolveResult:
    """Map a ``/search`` JSON payload onto ResolveResult.

    Unlike the other providers, MP3 URLs are present in the very first response,
    so ``Track.mp3_url`` is filled here and ``resolve_track`` becomes a no-op.
    """
    if not isinstance(data, dict):
        raise ServiceError("SpotiDown.co mengirim respons yang tidak dikenali.",
                           details=f"top-level type: {type(data).__name__}")

    raw_tracks = data.get("tracks") or []
    if not isinstance(raw_tracks, list):
        raw_tracks = []

    tracks: List[Track] = []
    for row in raw_tracks:
        if not isinstance(row, dict):
            continue
        album = row.get("album") if isinstance(row.get("album"), dict) else {}
        audio = row.get("audio") if isinstance(row.get("audio"), dict) else {}
        artists = [str(a) for a in (row.get("artists") or []) if a]
        try:
            duration_ms = int(row.get("duration") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        track_id = str(row.get("id") or "")
        tracks.append(Track(
            data=track_id,
            track_token=track_id,
            title=str(row.get("name") or "Unknown"),
            artist=", ".join(artists) or "Unknown",
            thumbnail=str(album.get("coverUrl") or ""),
            mp3_url=str(audio.get("url") or "") or None,
            duration_ms=duration_ms,
            album=str(album.get("name") or ""),
        ))

    total_raw = data.get("totalCount")
    try:
        total_count = int(total_raw)
    except (TypeError, ValueError):
        total_count = len(tracks)

    result = ResolveResult(
        title=str(data.get("name") or "Spotify content"),
        source_url=source_url or str(data.get("id") or ""),
        tracks=tracks,
    )

    # Honest reporting of the free-tier cap: never hide that tracks are missing.
    if total_count > len(tracks):
        result.raw_hint = (
            f"Playlist berisi {total_count} lagu, tapi hanya {len(tracks)} lagu "
            f"dikembalikan (batas free tier {FREE_TIER_LIMIT} track per playlist). "
            f"{total_count - len(tracks)} lagu sisanya butuh akun premium di "
            f"spotidown.co. Apps ini sengaja tidak melewati batas tersebut — "
            f"saran: pecah playlist jadi beberapa bagian di bawah "
            f"{FREE_TIER_LIMIT} lagu, atau pakai layanan lain."
        )
    return result


# --------------------------------------------------------------------------
# browser automation
# --------------------------------------------------------------------------
def _pick_search_response(captured: List[dict]) -> dict:
    """Choose the response to trust.

    Prefer the longest HTTP 200 body. Selecting purely by body length is a trap:
    a failed attempt (e.g. HTTP 500) can carry a longer body than the real
    result, and then a healthy run gets reported as a failure.
    """
    if not captured:
        raise ServiceError("Tidak ada respons /search yang tertangkap.")
    ok = [c for c in captured if c.get("status") == 200]
    pool = ok or captured
    return max(pool, key=lambda c: len(c.get("body") or ""))


def grab_playlist_json(playlist_url: str, wait_s: int = DEFAULT_WAIT_SECONDS,
                       port: int = CDP_PORT, attempts: int = 2) -> dict:
    """Drive spotidown.co in a real Chrome and return its ``/search`` JSON.

    NOTE: this blocks for up to ``wait_s`` seconds per attempt and it needs a
    visible Chrome window that the user must not close. Callers should show a
    spinner and say so.

    The site's ``/search`` endpoint intermittently answers HTTP 500 (observed
    while integrating this provider), so a failed attempt is retried with a
    freshly loaded page instead of being reported as a hard failure.
    """
    last_error: Optional[ServiceError] = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _grab_once(playlist_url, wait_s, port)
        except ServiceError as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(3)
    raise last_error if last_error else ServiceError("Gagal memuat playlist.")


def _grab_once(playlist_url: str, wait_s: int, port: int) -> dict:
    """Drive spotidown.co in a real Chrome and return its ``/search`` JSON.

    NOTE: this blocks for up to ``wait_s`` seconds and it needs a visible Chrome
    window that the user must not close. Callers should show a spinner and say so.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ServiceError(
            "Paket 'playwright' belum terpasang. Jalankan: pip install -r requirements.txt",
            details=f"import playwright failed: {exc}",
        ) from exc

    ensure_chrome(port)  # raises a friendly ServiceError when Chrome is missing

    captured: List[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()

        # TRAP 2: exactly ONE spotidown tab may exist, otherwise the site's own
        # main.js crashes on turnstile.render() and the flow hangs forever.
        for pg in list(ctx.pages):
            try:
                if "spotidown" in (pg.url or ""):
                    pg.close()
            except Exception:  # noqa: BLE001 - closing a dead tab is fine
                pass

        page = ctx.new_page()

        def on_response(resp):
            if "api.spotidown.co/search/" in resp.url:
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    body = f"<no body: {exc}>"
                captured.append({"status": resp.status, "body": body})
                print(f"[net] {resp.status} {resp.url[:110]}")

        page.on("response", on_response)

        try:
            # Observed while integrating this provider: /search intermittently
            # answers HTTP 500 for one page load and then succeeds for the next.
            # The captured sig shows why - failing requests carry a SHORT sig
            # (the per-load token was not fully minted yet), successful ones a
            # long one. Re-clicking alone reuses the same bad sig and fails
            # identically, so we RELOAD between attempts. And we wait for a
            # *successful* response, never for merely any response.
            deadline = time.time() + wait_s
            attempt = 0
            while time.time() < deadline and attempt < SEARCH_ATTEMPTS:
                attempt += 1
                seen = len(captured)
                try:
                    page.goto(SITE, wait_until="networkidle", timeout=90_000)
                    page.fill("input.link", playlist_url)
                    time.sleep(0.3)
                    page.click("button.search-btn")
                except Exception as exc:  # noqa: BLE001 - page may be mid-navigation
                    print(f"[warn] search attempt {attempt} could not start: {exc}")
                    time.sleep(2)
                    continue

                # TRAP 1: keep the renderer hot. A plain sleep() here lets Chrome
                # throttle the tab, Turnstile never completes, and we stall on
                # "Searching..." forever.
                inner = min(deadline, time.time() + RESPONSE_WAIT_SECONDS)
                last_state = ""
                while time.time() < inner:
                    if len(captured) > seen:
                        break
                    try:
                        state = page.evaluate(
                            """() => {
                                const el = document.querySelector("input[name='cf-turnstile-response']");
                                const btn = document.querySelector('button.search-btn');
                                return {
                                    tok: el ? el.value.length : -1,
                                    busy: btn ? btn.textContent.trim().slice(0, 12) : '',
                                };
                            }"""
                        )
                        cur = f"tok={state['tok']} btn={state['busy']!r}"
                        if cur != last_state:
                            print("   ", cur)
                            last_state = cur
                    except Exception:  # noqa: BLE001 - navigation in flight
                        pass
                    time.sleep(0.4)

                if len(captured) > seen:
                    time.sleep(1)  # let the body finish settling
                    best = _pick_search_response(captured)
                    if best.get("status") == 200:
                        try:
                            return json.loads(best["body"])
                        except json.JSONDecodeError as exc:
                            raise ServiceError("Respons SpotiDown.co bukan JSON yang valid.",
                                               details=f"{exc}\n{best['body'][:300]}") from exc
                    print(f"[warn] search attempt {attempt} -> HTTP {best.get('status')}, retrying")

            snippet = ""
            try:
                snippet = page.inner_text("body")[:600]
            except Exception:  # noqa: BLE001
                pass
            last_body = (captured[-1]["body"][:300] if captured else "")
            raise ServiceError(
                f"SpotiDown.co tidak mengembalikan daftar lagu setelah "
                f"{attempt} percobaan dalam {wait_s} detik. "
                "Jendela Chrome mungkin perlu Anda jaga di depan (jangan "
                "minimalimize / jangan tutup).",
                details=(f"last response: {last_body}\n\nPage said:\n{snippet}"
                         if last_body else f"Page said:\n{snippet}"),
            )
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


class SpotiDownCoClient:
    """Provider backed by spotidown.co, driven through a real Chrome window."""

    # Tells the orchestrator the MP3 URL is already known, so it must NOT spend a
    # resolve request per track.
    prefetched_urls = True

    def __init__(self, timeout: int = DEFAULT_WAIT_SECONDS):
        self.name = "SpotiDown.co"
        self.provider = ProviderId.SPOTIDOWN_CO
        self._timeout = timeout

    # ----------------------------------------------------------- public API
    def load_tracks(self, spotify_url: str, cftoken: str = "") -> ResolveResult:
        """Open Chrome, let the site solve its own challenge, parse the JSON.

        ``cftoken`` is accepted for interface compatibility and ignored: this
        provider never needs a hand-pasted CAPTCHA token.
        """
        url = (spotify_url or "").strip()
        if not url:
            raise ServiceError("Tempel URL playlist Spotify dulu.")
        payload = grab_playlist_json(url, wait_s=self._timeout)
        result = parse_search_payload(payload, source_url=url)
        if not result.tracks:
            raise ServiceError(
                "SpotiDown.co tidak mengembalikan lagu untuk URL ini.",
                details=f"type={payload.get('type')!r} totalCount={payload.get('totalCount')!r}",
            )
        return result

    def resolve_track(self, track: Track, cftoken: str = "") -> str:
        """Return the already-known MP3 URL. No network call is made."""
        url = track.mp3_url
        if not url:
            raise ServiceError(
                f"SpotiDown.co tidak memberikan link MP3 untuk '{track.title}'.",
                details="audio.url missing in the /search payload for this track",
            )
        return url

    # -------------------------------------------------------------- helpers
    @staticmethod
    def download_headers() -> dict:
        """Headers the MP3/CDN endpoint expects (Origin + Referer required)."""
        return dict(DOWNLOAD_HEADERS)