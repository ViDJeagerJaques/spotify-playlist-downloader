"""
Spotify playlist downloader - REAL automation, no manual steps.

WHY THIS WORKS (the breakthrough)
--------------------------------
Launching Chrome *ourselves* (plain flags, no --enable-automation /
--disable-blink-features=AutomationControlled) and then attaching over CDP
leaves NO automation fingerprint. Cloudflare's Turnstile renders normally and
mints its token; the site spends it and returns clean JSON with MP3 URLs.

Verified: probe7.py returned HTTP 200 with full track data.

FLOW
----
1. Chrome (ours) opens spotidown.co
2. We fill the playlist URL and click Search
3. Site's own Turnstile dance runs; we just read the JSON response
4. We download every audio.url and zip them

USAGE
-----
    python tools/spotidown_grab.py "https://open.spotify.com/playlist/XXXX"
    python tools/spotidown_grab.py "URL" --out out/ --no-zip
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

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
PROFILE_DIR = Path(__file__).parent / "cdp-profile"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------
# chrome lifecycle
# --------------------------------------------------------------------------
def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("Chrome not found in the usual places.")


def cdp_alive() -> bool:
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "3", f"http://127.0.0.1:{CDP_PORT}/json/version"],
            capture_output=True, text=True, timeout=10,
        )
        return '"Browser"' in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


def launch_chrome(chrome: str) -> subprocess.Popen:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,900",
        "about:blank",
    ]
    print("[chrome] launching:", " ".join(args[:3]), "...")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_chrome() -> tuple[subprocess.Popen | None, str]:
    chrome = find_chrome()
    if cdp_alive():
        print("[chrome] existing CDP session found on port", CDP_PORT)
        return None, chrome
    proc = launch_chrome(chrome)
    for _ in range(30):
        time.sleep(0.5)
        if cdp_alive():
            print("[chrome] CDP ready")
            return proc, chrome
    raise SystemExit("Chrome started but CDP never came up.")


# --------------------------------------------------------------------------
# scraping
# --------------------------------------------------------------------------
def grab_playlist(playlist_url: str, wait_s: int = 90) -> dict:
    """Drive the site in a real Chrome and return its /search JSON."""
    from playwright.sync_api import sync_playwright

    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()

        # IMPORTANT: close any pre-existing spotidown tabs first.
        # The site loads challenges.cloudflare.com/turnstile/v0/api.js once per
        # page; a second load makes window.turnstile undefined and their main.js
        # crashes on turnstile.render() -> the page hangs on "Searching..."
        # (confirmed in probe5). So: exactly ONE spotidown tab at a time.
        for pg in list(ctx.pages):
            try:
                if "spotidown" in (pg.url or ""):
                    print("[page] closing stale tab:", pg.url[:80])
                    pg.close()
            except Exception:  # noqa: BLE001
                pass

        page = ctx.new_page()

        def on_response(resp):
            u = resp.url
            if "api.spotidown.co/search/" in u:
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    body = f"<no body: {exc}>"
                captured.append({"url": u, "status": resp.status, "body": body})
                print(f"[net] {resp.status} {u[:110]}")

        page.on("response", on_response)

        print("[page] opening", SITE)
        page.goto(SITE, wait_until="networkidle", timeout=90_000)
        time.sleep(2)

        print("[page] filling playlist + clicking Search")
        page.fill("input.link", playlist_url)
        time.sleep(0.3)
        page.click("button.search-btn")

        # Keep the page AWAKE while we wait.
        #
        # Why: a backgrounded/occluded Chrome tab gets its timers throttled, and
        # Cloudflare's Turnstile widget needs an active page to run its
        # challenge. Just sleeping here makes the tab go quiet and the site
        # hangs on "Searching..." forever. Actively polling page.evaluate()
        # keeps the renderer hot - this is the difference between probe7
        # (worked) and a naive sleep loop (didn't).
        deadline = time.time() + wait_s
        last_state = ""
        while time.time() < deadline and not captured:
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
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)

        if not captured:
            # grab whatever the page is saying, to explain the failure
            txt = ""
            try:
                txt = page.inner_text("body")[:600]
            except Exception:  # noqa: BLE001
                pass
            raise SystemExit(f"No /search response in {wait_s}s.\nPage said:\n{txt}")

        # let the response body fully settle
        time.sleep(1)
        best = max(captured, key=lambda c: len(c["body"]))
        if best["status"] != 200:
            raise SystemExit(f"search returned HTTP {best['status']}: {best['body'][:300]}")

        try:
            data = json.loads(best["body"])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"search body was not JSON: {exc}\n{best['body'][:300]}") from exc

        # tidy up: close our tab, leave the browser alone
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass

    return data


# --------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------
def safe_name(s: str, maxlen: int = 120) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "-", s).strip(" .")
    return (s[:maxlen] or "track").rstrip(" .")


def download_track(track: dict, outdir: Path, index: int, attempts: int = 4) -> tuple[str, int, str | None]:
    """Return (label, bytes, error). Retries transient failures.

    Observed: the CDN (123tokyo.xyz) rejects a share of requests when too many
    run in parallel - a single-track fetch of the same URL succeeds. So we
    back off and retry with jitter instead of giving up on the first 22.
    """
    name = track.get("name") or f"track{index}"
    artists = ", ".join(track.get("artists") or []) or "Unknown"
    label = f"{index:02d} - {safe_name(artists)} - {safe_name(name)}.mp3"
    dest = outdir / label

    audio = (track.get("audio") or {})
    url = audio.get("url")
    if not url:
        return label, 0, "no audio.url"

    if dest.exists() and dest.stat().st_size > 0:
        return label, dest.stat().st_size, None

    last_err = ""
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            # back off, with jitter so parallel workers don't retry in lockstep
            time.sleep(min(1.5 * attempt, 5) + random.uniform(0, 0.8))
        cmd = [
            "curl", "-sL", "--fail", "--max-time", "300",
            "-H", f"User-Agent: {UA}",
            "-H", "Origin: https://spotidown.co",
            "-H", "Referer: https://spotidown.co/",
            "-o", str(dest),
            url,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=330)
        except subprocess.TimeoutExpired:
            last_err = "timeout"
            continue

        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return label, dest.stat().st_size, None

        last_err = f"curl exit {r.returncode}"
        # a partial file would be counted as "exists" next run - remove it
        try:
            if dest.exists():
                dest.unlink()
        except Exception:  # noqa: BLE001
            pass

    return label, 0, f"{last_err} (after {attempts} attempts)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Grab a Spotify playlist via spotidown.co")
    ap.add_argument("playlist", help="Spotify playlist/album/track URL")
    ap.add_argument("--out", default="downloads", help="output folder (default: downloads)")
    ap.add_argument("--no-zip", action="store_true", help="skip zip creation")
    ap.add_argument("--workers", type=int, default=3, help="parallel downloads (default 3; the CDN rejects some parallel requests)")
    ap.add_argument("--keep-chrome", action="store_true", help="leave Chrome running")
    args = ap.parse_args()

    proc, _chrome = ensure_chrome()

    try:
        data = grab_playlist(args.playlist)
    finally:
        if proc and not args.keep_chrome:
            pass  # keep alive until downloads are done; closed at the very end

    tracks = data.get("tracks") or []
    name = data.get("name") or "playlist"
    print(f"\n[ok] '{name}' - {len(tracks)} track(s) reported (totalCount={data.get('totalCount')})")

    if not tracks:
        raise SystemExit("No tracks in response.")

    outdir = Path(args.out) / safe_name(name)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[out] {outdir.resolve()}\n")

    # save the raw metadata too
    (outdir / "_playlist.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {
            pool.submit(download_track, t, outdir, i + 1): (i + 1, t)
            for i, t in enumerate(tracks)
        }
        for fut in as_completed(futs):
            idx, t = futs[fut]
            try:
                label, size, err = fut.result()
            except Exception as exc:  # noqa: BLE001
                label, size, err = f"{idx:02d}", 0, repr(exc)[:150]
            results.append((idx, label, size, err))
            mark = "OK " if not err else "ERR"
            print(f"  [{mark}] {idx:02d}/{len(tracks)}  {label}  {size/1e6:.1f} MB"
                  + (f"  <- {err}" if err else ""))

    ok = [r for r in results if not r[3]]
    bad = [r for r in results if r[3]]
    print(f"\n[pass 1] {len(ok)}/{len(tracks)} downloaded"
          + (f", {len(bad)} failed" if bad else ""))

    # ---- serial retry pass ------------------------------------------------
    # Observed: parallel fetching makes the CDN (123tokyo.xyz) reject a share
    # of requests even though the same URL works when fetched alone. So retry
    # the failures ONE AT A TIME before declaring them dead.
    if bad:
        print(f"\n[pass 2] retrying {len(bad)} failure(s) serially ...")
        still_bad = []
        for idx, label, _size, _err in sorted(bad):
            t = tracks[idx - 1]
            if not (t.get("audio") or {}).get("url"):
                print(f"  [SKIP] {idx:02d}  no audio.url in API response")
                still_bad.append((idx, label, 0, "no audio.url"))
                continue
            lab, size, err = download_track(t, outdir, idx, attempts=3)
            if err:
                print(f"  [ERR ] {idx:02d}  {lab}  <- {err}")
                still_bad.append((idx, lab, 0, err))
            else:
                print(f"  [OK  ] {idx:02d}  {lab}  {size/1e6:.1f} MB  (recovered)")
        bad = still_bad
        ok = [r for r in results if not r[3]] + [
            (i, l, s, None) for (i, l, s, e) in still_bad if False
        ]
        print(f"\n[pass 2] {len(tracks) - len(bad)}/{len(tracks)} downloaded now")

    got = len(tracks) - len(bad)
    print(f"\n[FINAL] {got}/{len(tracks)} downloaded"
          + (f", {len(bad)} failed" if bad else ""))

    if bad:
        print("\n[!] could not fetch:")
        for idx, label, _s, err in sorted(bad):
            print(f"    {idx:02d}. {label}  <- {err}")

    # zip
    if not args.no_zip and got:
        zpath = outdir.parent / f"{safe_name(name)}.zip"
        print(f"[zip] building {zpath.name} ...")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for p in sorted(outdir.glob("*.mp3")):
                z.write(p, p.name)
        print(f"[zip] {zpath}  ({zpath.stat().st_size/1e6:.1f} MB)")

    if proc and not args.keep_chrome:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
