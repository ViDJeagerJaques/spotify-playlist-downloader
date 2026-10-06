"""
Probe #4: use the REAL installed Chrome (channel="chrome") with a persistent
profile instead of the bundled Chromium.

Finding from probe3: Turnstile returned "No available adapters" under bundled
Chromium - i.e. Cloudflare refused to render the widget for an automated
browser. Real Chrome + persistent profile is much less detectable.
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"
PROFILE = os.path.abspath("tools/chrome-profile")


def main() -> int:
    captured = []
    consoles = []
    os.makedirs(PROFILE, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            channel="chrome",           # <-- real Google Chrome
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1280,900"],
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:200]}"))

        def on_response(resp):
            u = resp.url
            if "api.spotidown" in u:
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
                print(f"\n>>> {resp.request.method} {resp.status} {u[:170]}")
                print("    body:", body[:500])

        page.on("response", on_response)

        print("== opening with REAL Chrome ==")
        page.goto(SITE, wait_until="networkidle", timeout=90_000)
        time.sleep(3)

        page.fill("input.link", PLAYLIST)
        print("clicked Search; waiting for turnstile...")
        page.click("button.search-btn")

        token = ""
        for i in range(120):
            token = page.evaluate(
                """() => {
                    const el = document.querySelector("input[name='cf-turnstile-response']");
                    return el ? el.value : '';
                }"""
            )
            if token:
                print(f"\n*** TOKEN at {i * 0.5:.1f}s (len={len(token)}) ***")
                print(token[:90], "...")
                break
            if i % 20 == 0 and i:
                print(f"  ...{i * 0.5:.0f}s")
            time.sleep(0.5)

        if not token:
            st = page.evaluate(
                """() => {
                    const c = document.getElementById('turnstileContainer');
                    return {
                        html: c ? c.innerHTML.slice(0,600) : null,
                        iframes: [...document.querySelectorAll('iframe')].map(f => f.src.slice(0,120)),
                        tsGlobal: typeof window.turnstile,
                    };
                }"""
            )
            print("\n!! no token. widget state:")
            print(json.dumps(st, indent=2))

        print("\nwaiting 30s for /search ...")
        time.sleep(30)

        print("\n== CAPTURED ==")
        for c in captured:
            print(json.dumps({k: v for k, v in c.items() if k != "headers"}, indent=2)[:1800])
            print("  x-token:", str(c["headers"].get("x-token", ""))[:70])

        print("\n== CONSOLE TAIL ==")
        for c in consoles[-12:]:
            print("  ", c)

        with open("tools/probe4_result.json", "w", encoding="utf-8") as fh:
            json.dump({"token": token, "captured": captured, "console": consoles}, fh, indent=2)
        print("\nwrote tools/probe4_result.json")
        time.sleep(3)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
