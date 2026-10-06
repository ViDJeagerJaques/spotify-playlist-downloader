"""
Probe #2: capture EVERYTHING - all requests, console logs, errors.
Goal: find why the Turnstile widget never renders on spotidown.co.
"""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"


def main() -> int:
    all_reqs = []
    consoles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = ctx.new_page()

        page.on("request", lambda r: all_reqs.append({"m": r.method, "u": r.url}))
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:300]}"))
        page.on("pageerror", lambda e: consoles.append(f"[pageerror] {str(e)[:300]}"))

        print("== goto ==")
        page.goto(SITE, wait_until="networkidle", timeout=60_000)
        time.sleep(4)

        print("\n== ALL REQUESTS ==")
        for r in all_reqs:
            print(f"  {r['m']:6s} {r['u'][:130]}")

        print("\n== CONSOLE ==")
        for c in consoles:
            print("  ", c)

        # inspect the turnstile container + scripts
        probe = page.evaluate(
            """() => {
                const cont = document.getElementById('turnstileContainer');
                const scripts = [...document.querySelectorAll('script')].map(s => s.src || '(inline)');
                return {
                    containerHTML: cont ? cont.innerHTML.slice(0, 500) : null,
                    containerChildren: cont ? cont.children.length : null,
                    scripts: scripts,
                    turnstileGlobal: typeof window.turnstile,
                    loadedScripts: [...document.querySelectorAll('script[src]')].map(s => s.src),
                };
            }"""
        )
        print("\n== DOM PROBE ==")
        print(json.dumps(probe, indent=2))

        # try: fill + click and watch for new requests
        print("\n== fill + click ==")
        try:
            page.fill("input.link", PLAYLIST)
            page.click("button.search-btn")
        except Exception as exc:  # noqa: BLE001
            print("  failed:", exc)

        time.sleep(15)

        print("\n== REQUESTS AFTER CLICK (non-static) ==")
        for r in all_reqs:
            u = r["u"]
            if any(k in u for k in ("api.", "search", "turnstile", "cloudflare", "challenge", "download")):
                print(f"  {r['m']:6s} {u[:150]}")

        print("\n== CONSOLE (after) ==")
        for c in consoles[-25:]:
            print("  ", c)

        print("\n== PAGE TEXT ==")
        print(page.inner_text("body")[:1200])

        with open("tools/probe2_result.json", "w", encoding="utf-8") as fh:
            json.dump({"requests": all_reqs, "console": consoles, "probe": probe}, fh, indent=2)
        print("\nwrote tools/probe2_result.json")
        time.sleep(3)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
