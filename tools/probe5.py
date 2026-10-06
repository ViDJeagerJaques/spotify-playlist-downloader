"""
Probe #5: instrument Turnstile itself.

Goal: find out WHY the widget never produces a token.
Hook window.turnstile.render / .execute to capture:
  - the sitekey the site passes
  - the error-callback payload
  - whether an iframe ever appears
  - the widget's rendered state
Also screenshot the widget area so we can see it.
"""
from __future__ import annotations

import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

SITE = "https://spotidown.co/en16"
PLAYLIST = "https://open.spotify.com/playlist/0OAWLZxZydBuXyVuCszKT".replace("dByu", "dByu")
PROFILE = os.path.abspath("tools/chrome-profile2")


def main() -> int:
    events = []
    consoles = []
    os.makedirs(PROFILE, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1400,1000",
                "--window-position=0,0",
            ],
            locale="en-US",
            viewport={"width": 1400, "height": 1000},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("console", lambda m: consoles.append(f"[{m.type}] {m.text[:250]}"))

        # hook turnstile as soon as the page defines it
        page.add_init_script(
            """
            (() => {
              const log = (o) => { try { console.log('TSHOOK ' + JSON.stringify(o)); } catch(e){} };
              let realRender = null;
              Object.defineProperty(window, 'turnstile', {
                configurable: true,
                set(v) {
                  realRender = v;
                  if (v && v.render) {
                    const orig = v.render.bind(v);
                    v.render = function(el, opts) {
                      log({ev:'render', el: (el && el.id) || String(el), sitekey: opts && opts.sitekey,
                           hasCallback: !!(opts && opts.callback), hasErrCb: !!(opts && ('error-callback' in opts)),
                           hasExpired: !!(opts && ('expired-callback' in opts))});
                      const o2 = Object.assign({}, opts, {
                        'error-callback': (e) => { log({ev:'ERROR', err: String(e)}); if (opts['error-callback']) try{opts['error-callback'](e)}catch(_){} },
                        'expired-callback': () => { log({ev:'EXPIRED'}); if (opts['expired-callback']) try{opts['expired-callback']()}catch(_){} },
                        callback: (t) => { log({ev:'TOKEN', len: (t||'').length}); if (opts.callback) try{opts.callback(t)}catch(_){} },
                      });
                      return orig(el, o2);
                    };
                  }
                  this.__ts = v;
                },
                get() { return this.__ts; },
              });
            })();
            """
        )

        print("== goto ==")
        page.goto(SITE, wait_until="networkidle", timeout=90_000)
        time.sleep(3)

        page.fill("input.link", PLAYLIST)
        print("== click Search ==")
        page.click("button.search-btn")

        # poll widget + collect hooks
        for i in range(60):  # 30s
            st = page.evaluate(
                """() => {
                    const c = document.getElementById('turnstileContainer');
                    return {
                        iframes: [...document.querySelectorAll('iframe')].map(f => f.src.slice(0,90)),
                        html: c ? c.innerHTML.slice(0,300) : null,
                        val: (document.querySelector("input[name='cf-turnstile-response']")||{}).value || '',
                    };
                }"""
            )
            if st["val"]:
                print(f"\n*** TOKEN at {i*0.5:.1f}s len={len(st['val'])} ***")
                break
            if i % 10 == 0:
                print(f"  t={i*0.5:.0f}s iframes={len(st['iframes'])} val={len(st['val'])}")
            time.sleep(0.5)

        try:
            page.screenshot(path="tools/widget.png", full_page=False)
            print("screenshot -> tools/widget.png")
        except Exception as exc:  # noqa: BLE001
            print("screenshot failed:", exc)

        print("\n== TSHOOK / relevant console ==")
        for c in consoles:
            if "TSHOOK" in c or "turnstile" in c.lower() or "error" in c.lower():
                print("  ", c[:300])

        print("\n== final widget state ==")
        print(json.dumps(page.evaluate(
            """() => {
                const c = document.getElementById('turnstileContainer');
                return {
                    html: c ? c.innerHTML.slice(0,500) : null,
                    iframes: [...document.querySelectorAll('iframe')].map(f => f.src.slice(0,120)),
                    tsType: typeof window.turnstile,
                    tsKeys: window.turnstile ? Object.keys(window.turnstile) : null,
                };
            }"""
        ), indent=2))

        with open("tools/probe5_result.json", "w", encoding="utf-8") as fh:
            json.dump({"console": consoles}, fh, indent=2)
        print("\nwrote tools/probe5_result.json")
        time.sleep(2)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
