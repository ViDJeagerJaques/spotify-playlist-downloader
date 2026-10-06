"""
Test: can we drive spotidown.co from a real browser and get the playlist?

Strategy: do everything INSIDE the browser context (real Chromium) so the
Turnstile token, cookies and IP all belong to the same session.

Run:  .venv/Scripts/python.exe tools/probe_spotidown.py
"""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT"

captured = []


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # real window: Turnstile needs a real browser
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,900",
            ],
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

        # --- record every API call the page makes -------------------------
        def on_response(resp):
            u = resp.url
            if "api.spotidown" in u or "/search/" in u or "/download" in u:
                body = ""
                try:
                    body = resp.text()[:2000]
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
                print(f"\n>>> {resp.request.method} {resp.status} {u}")
                print("    body:", body[:300])

        page.on("response", on_response)

        print("== opening site ==")
        page.goto(SITE, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(3)

        # --- look for the turnstile widget --------------------------------
        info = page.evaluate(
            """() => {
                const ts = document.querySelector("input[name='cf-turnstile-response']");
                return {
                    hasTurnstileInput: !!ts,
                    tokenLen: ts ? ts.value.length : 0,
                    hasTurnstileGlobal: typeof window.turnstile !== 'undefined',
                    inputSel: !!document.querySelector('input.link'),
                    bodyText: document.body.innerText.slice(0, 300),
                };
            }"""
        )
        print("\n== page state ==")
        print(json.dumps(info, indent=2))

        # --- type the playlist and click search ---------------------------
        print("\n== typing playlist + clicking Search ==")
        try:
            page.fill("input.link", PLAYLIST)
            page.click("button.search-btn")
        except Exception as exc:  # noqa: BLE001
            print("fill/click failed:", exc)

        # --- wait for the turnstile token to appear -----------------------
        print("== waiting for turnstile token (up to 45s) ==")
        token = ""
        for i in range(90):
            token = page.evaluate(
                """() => {
                    const el = document.querySelector("input[name='cf-turnstile-response']");
                    return el ? el.value : '';
                }"""
            )
            if token:
                print(f"TOKEN after {i * 0.5:.1f}s, len={len(token)}")
                break
            time.sleep(0.5)

        if not token:
            print("!! no token appeared")
        else:
            print("token prefix:", token[:60])

        # --- let the search request fire ----------------------------------
        print("\n== waiting 20s for search request ==")
        time.sleep(20)

        print("\n== CAPTURED REQUESTS ==")
        for c in captured:
            print(json.dumps({k: v for k, v in c.items() if k != "headers"}, indent=2)[:1200])

        out = {
            "token": token,
            "captured": captured,
            "page_text": page.inner_text("body")[:2000],
        }
        with open("tools/probe_result.json", "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print("\nwrote tools/probe_result.json")

        time.sleep(5)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
