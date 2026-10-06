"""
Probe #7: attach to a Chrome that WE launched ourselves (no automation flags),
via CDP. This is the last untested path - if Turnstile renders here, the whole
thing can be automated end to end.

Chrome must already be running with --remote-debugging-port=9222.
"""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"
CDP = "http://127.0.0.1:9222"


def main() -> int:
    captured = []
    consoles = []

    with sync_playwright() as p:
        print("== connecting to existing Chrome via CDP ==")
        browser = p.chromium.connect_over_cdp(CDP)
        print("connected. contexts:", len(browser.contexts))

        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:250]}"))

        def on_response(resp):
            u = resp.url
            if "api.spotidown" in u:
                try:
                    body = resp.text()[:6000]
                except Exception as exc:  # noqa: BLE001
                    body = f"<no body: {exc}>"
                captured.append({"url": u, "status": resp.status, "method": resp.request.method, "body": body})
                print(f"\n>>> {resp.request.method} {resp.status} {u[:150]}")
                print("    body:", body[:400])

        page.on("response", on_response)

        print("== goto ==")
        page.goto(SITE, wait_until="networkidle", timeout=90_000)
        time.sleep(3)

        print("== fill + click Search ==")
        page.fill("input.link", PLAYLIST)
        page.click("button.search-btn")

        token = ""
        for i in range(120):  # 60s
            st = page.evaluate(
                """() => {
                    const el = document.querySelector("input[name='cf-turnstile-response']");
                    return {
                        val: el ? el.value : '',
                        iframes: [...document.querySelectorAll('iframe')].map(f => f.src.slice(0,80)),
                    };
                }"""
            )
            if st["val"]:
                token = st["val"]
                print(f"\n*** TURNSTILE TOKEN at {i*0.5:.1f}s (len={len(token)}) ***")
                break
            if i % 10 == 0:
                print(f"  t={i*0.5:.0f}s iframes={len(st['iframes'])}")
            time.sleep(0.5)

        if not token:
            print("\n!! no token after 60s")
            print(json.dumps(page.evaluate(
                """() => ({
                    html: (document.getElementById('turnstileContainer')||{}).innerHTML || null,
                    iframes: [...document.querySelectorAll('iframe')].map(f=>f.src.slice(0,110)),
                    tsType: typeof window.turnstile,
                })"""
            ), indent=2))

        print("\nwaiting 30s for /search ...")
        time.sleep(30)

        print("\n== CAPTURED: %d ==" % len(captured))
        for c in captured:
            print(json.dumps(c, indent=2)[:2500])

        print("\n== CONSOLE (filtered) ==")
        for c in consoles:
            low = c.lower()
            if "turnstile" in low or "error" in low or "search" in low:
                print("  ", c[:250])

        with open("tools/probe7_result.json", "w", encoding="utf-8") as fh:
            json.dump({"token": token, "captured": captured, "console": consoles}, fh, indent=2)
        print("\nwrote tools/probe7_result.json")
        return 0


if __name__ == "__main__":
    sys.exit(main())
