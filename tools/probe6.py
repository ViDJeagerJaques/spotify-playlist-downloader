"""
Probe #6: FIX the double-load bug.

Finding (probe5): spotidown.co injects challenges.cloudflare.com/turnstile/v0/api.js
TWICE. The second injection makes Cloudflare bail out and `window.turnstile`
ends up undefined -> their main.js crashes on turnstile.render() -> no widget,
no token, no sig, Search dead.

Workaround: intercept the api.js request and let it through exactly ONCE.
If that fixes rendering, our app can drive the whole flow itself.
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"
PROFILE = os.path.abspath("tools/chrome-profile3")

TS_MARK = "challenges.cloudflare.com/turnstile/v0/api.js"


def main() -> int:
    captured = []
    consoles = []
    allowed = {"n": 0}
    os.makedirs(PROFILE, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1400,1000"],
            locale="en-US",
            viewport={"width": 1400, "height": 1000},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:250]}"))

        # ---- FIX: allow only the FIRST turnstile api.js load --------------
        def route_handler(route):
            allowed["n"] += 1
            if allowed["n"] == 1:
                print("  [route] ALLOW turnstile api.js (load #1)")
                route.continue_()
            else:
                print(f"  [route] BLOCK duplicate turnstile api.js (load #{allowed['n']})")
                route.abort()

        page.route(f"**/{TS_MARK}*", route_handler)

        def on_response(resp):
            u = resp.url
            if "api.spotidown" in u:
                try:
                    body = resp.text()[:5000]
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
                print("    body:", body[:600])

        page.on("response", on_response)

        print("== goto ==")
        page.goto(SITE, wait_until="networkidle", timeout=90_000)
        time.sleep(2)

        page.fill("input.link", PLAYLIST)
        print("== click Search ==")
        page.click("button.search-btn")

        token = ""
        for i in range(120):  # 60s
            st = page.evaluate(
                """() => {
                    const el = document.querySelector("input[name='cf-turnstile-response']");
                    const c = document.getElementById('turnstileContainer');
                    return {
                        val: el ? el.value : '',
                        iframes: document.querySelectorAll('iframe').length,
                        html: c ? c.innerHTML.slice(0,200) : null,
                    };
                }"""
            )
            if st["val"]:
                token = st["val"]
                print(f"\n*** TOKEN at {i*0.5:.1f}s (len={len(token)}) ***")
                print(token[:90], "...")
                break
            if i % 10 == 0:
                print(f"  t={i*0.5:.0f}s iframes={st['iframes']} val={len(st['val'])} html={st['html']!r}")
            time.sleep(0.5)

        if not token:
            print("\n!! still no token")
            print(json.dumps(page.evaluate(
                """() => ({
                    html: (document.getElementById('turnstileContainer')||{}).innerHTML || null,
                    iframes: [...document.querySelectorAll('iframe')].map(f=>f.src.slice(0,110)),
                    tsType: typeof window.turnstile,
                })"""
            ), indent=2))

        print("\nwaiting 30s for /search ...")
        time.sleep(30)

        print("\n== CAPTURED ==")
        for c in captured:
            print(json.dumps({k: v for k, v in c.items() if k != "headers"}, indent=2)[:2000])

        print("\n== CONSOLE (filtered) ==")
        for c in consoles:
            low = c.lower()
            if "turnstile" in low or "error" in low or "search" in low:
                print("  ", c[:250])

        with open("tools/probe6_result.json", "w", encoding="utf-8") as fh:
            json.dump({"token": token, "captured": captured, "console": consoles}, fh, indent=2)
        print("\nwrote tools/probe6_result.json")
        time.sleep(3)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
