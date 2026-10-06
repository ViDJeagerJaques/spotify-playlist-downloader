"""
Probe #3: full flow with longer waits.

Discovery from probe2: Turnstile is loaded LAZILY on Search click
("loading turnstile..." -> challenges.cloudflare.com/turnstile/v0/api.js).

So: click Search, wait for the token, capture the /search request + its sig.
If this works end-to-end, the app can do everything itself.
"""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"


def main() -> int:
    captured = []
    consoles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1280,900"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:200]}"))

        def on_response(resp):
            u = resp.url
            if "api.spotidown" in u or "/download" in u:
                try:
                    body = resp.text()[:4000]
                except Exception as exc:  # noqa: BLE001
                    body = f"<no body: {exc}>"
                captured.append(
                    {
                        "url": u,
                        "status": resp.status,
                        "method": resp.request.method,
                        "headers": dict(resp.request.headers),
                        "body": body,
                    }
                )
                print(f"\n>>> {resp.request.method} {resp.status} {u[:160]}")
                print("    body:", body[:400])

        page.on("response", on_response)

        page.goto(SITE, wait_until="networkidle", timeout=60_000)
        time.sleep(2)

        page.fill("input.link", PLAYLIST)
        print("clicked Search; waiting for turnstile token...")
        page.click("button.search-btn")

        token = ""
        for i in range(120):  # up to 60s
            token = page.evaluate(
                """() => {
                    const el = document.querySelector("input[name='cf-turnstile-response']");
                    return el ? el.value : '';
                }"""
            )
            if token:
                print(f"\n*** TOKEN at {i * 0.5:.1f}s (len={len(token)}) ***")
                print(token[:80], "...")
                break
            if i % 20 == 0 and i:
                print(f"  ...{i * 0.5:.0f}s")
            time.sleep(0.5)

        if not token:
            print("\n!! still no token after 60s")
            # dump widget state
            st = page.evaluate(
                """() => {
                    const c = document.getElementById('turnstileContainer');
                    return {
                        html: c ? c.innerHTML.slice(0,800) : null,
                        iframes: [...document.querySelectorAll('iframe')].map(f => f.src),
                        tsGlobal: typeof window.turnstile,
                        bodyTail: document.body.innerText.slice(-400),
                    };
                }"""
            )
            print(json.dumps(st, indent=2))

        # wait for the search API call
        print("\nwaiting 25s for /search request...")
        time.sleep(25)

        print("\n== CAPTURED ==")
        for c in captured:
            print(json.dumps({k: v for k, v in c.items() if k != "headers"}, indent=2)[:1500])
            print("  x-token:", c["headers"].get("x-token", "")[:60])

        print("\n== CONSOLE TAIL ==")
        for c in consoles[-15:]:
            print("  ", c)

        with open("tools/probe3_result.json", "w", encoding="utf-8") as fh:
            json.dump({"token": token, "captured": captured, "console": consoles}, fh, indent=2)
        print("\nwrote tools/probe3_result.json")
        time.sleep(3)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
