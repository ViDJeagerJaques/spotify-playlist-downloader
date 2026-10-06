"""
Probe #8: replicate EXACTLY what probe7 did, but programmatically.

probe7 (manual launch, then attach) WORKED.
spotidown_grab.py (same idea, coded) FAILED with "Searching..." forever.

Hypothesis: the site needs a *warmed* session - i.e. the page must be loaded
and given time to run its boot sequence BEFORE we click Search. In probe7 the
browser had been sitting on about:blank for a while and the page load had
extra settling time.

This probe tests: launch -> wait -> load page -> wait longer -> fill -> click.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9222
SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"
PROFILE = Path(__file__).parent / "cdp-profile"


def cdp_up() -> bool:
    r = subprocess.run(["curl", "-s", "-m", "3", f"http://127.0.0.1:{PORT}/json/version"],
                       capture_output=True, text=True, timeout=10)
    return '"Browser"' in (r.stdout or "")


def main() -> int:
    if cdp_up():
        print("CDP already up")
        proc = None
    else:
        PROFILE.mkdir(parents=True, exist_ok=True)
        print("launching chrome...")
        proc = subprocess.Popen(
            [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
             "--no-first-run", "--no-default-browser-check", "--window-size=1280,900",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(40):
            time.sleep(0.5)
            if cdp_up():
                break
        else:
            raise SystemExit("CDP never came up")

    print("CDP ready; waiting 5s for chrome to settle")
    time.sleep(5)

    captured = []
    consoles = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:200]}"))

        def on_response(resp):
            if "api.spotidown.co/search/" in resp.url:
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    body = f"<err {exc}>"
                captured.append({"url": resp.url, "status": resp.status, "body": body})
                print(f"\n>>> {resp.status} {resp.url[:130]}")
                print("    body:", body[:300])

        page.on("response", on_response)

        print("goto...")
        page.goto(SITE, wait_until="networkidle", timeout=90_000)

        print("waiting 6s for boot sequence...")
        time.sleep(6)

        state = page.evaluate(
            """() => ({
                hasInput: !!document.querySelector('input.link'),
                hasBtn: !!document.querySelector('button.search-btn'),
                tsType: typeof window.turnstile,
                bodyLen: document.body.innerText.length,
            })"""
        )
        print("state:", json.dumps(state))

        print("fill + click")
        page.fill("input.link", PLAYLIST)
        time.sleep(0.5)
        page.click("button.search-btn")

        deadline = time.time() + 90
        while time.time() < deadline and not captured:
            time.sleep(0.5)

        print(f"\ncaptured={len(captured)}")

        if not captured:
            print("\n== CONSOLE TAIL ==")
            for c in consoles[-25:]:
                print("  ", c)
            print("\n== PAGE TEXT ==")
            print(page.inner_text("body")[:500])

        with open("tools/probe8_result.json", "w", encoding="utf-8") as fh:
            json.dump({"captured": captured, "console": consoles}, fh, indent=2)
        print("wrote tools/probe8_result.json")

    if proc:
        print("(chrome left running on purpose)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
