/* ============================================================================
 * SpotiDown console probe — capture the /search response
 * ============================================================================
 *
 * WHY THIS WORKS
 *   We never touch Cloudflare. The site's own JS does the Turnstile dance in
 *   YOUR browser (where it passes), and we simply read the JSON it gets back.
 *   That sidesteps the entire "server vs browser session" problem.
 *
 * HOW TO USE
 *   1. Open https://spotidown.co/en16 in Chrome
 *   2. Press F12 -> Console tab
 *   3. Paste this whole file, press Enter
 *   4. Wait for it to print. It clicks Search for you.
 *
 * It prints:
 *   - every api.spotidown.co response (status + JSON)
 *   - a flattened list of tracks if it can find them
 * ==========================================================================*/
(async () => {
  const TAG = '%c[SPOTIDOWN-PROBE]';
  const CSS = 'color:#1ed760;font-weight:bold';

  const PLAYLIST = 'https://open.spotify.com/playlist/0OAWLZxZydByuXyVuCszKT';

  // ---- storage ------------------------------------------------------------
  window.__SL = window.__SL || { hits: [] };
  const hits = window.__SL.hits;

  const record = (url, status, body) => {
    hits.push({ url, status, body, at: Date.now() });
    console.log(TAG, CSS, status, url.slice(0, 120));
  };

  // ---- hook fetch ---------------------------------------------------------
  if (!window.__SL.fetchHooked) {
    window.__SL.fetchHooked = true;
    const origFetch = window.fetch;
    window.fetch = async function (...args) {
      const resp = await origFetch.apply(this, args);
      try {
        const u = (typeof args[0] === 'string') ? args[0] : (args[0] && args[0].url) || '';
        if (u.includes('api.spotidown') || u.includes('/search/') || u.includes('/download')) {
          const clone = resp.clone();
          const text = await clone.text();
          record(u, resp.status, text);
        }
      } catch (e) { /* ignore */ }
      return resp;
    };
    console.log(TAG, CSS, 'fetch hooked');
  }

  // ---- hook XHR -----------------------------------------------------------
  if (!window.__SL.xhrHooked) {
    window.__SL.xhrHooked = true;
    const OrigOpen = XMLHttpRequest.prototype.open;
    const OrigSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__sl_url = url;
      return OrigOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      this.addEventListener('load', function () {
        try {
          const u = this.__sl_url || '';
          if (u.includes('api.spotidown') || u.includes('/search/') || u.includes('/download')) {
            record(u, this.status, this.responseText);
          }
        } catch (e) { /* ignore */ }
      });
      return OrigSend.apply(this, args);
    };
    console.log(TAG, CSS, 'xhr hooked');
  }

  // ---- trigger the search -------------------------------------------------
  const input = document.querySelector('input.link');
  const btn = document.querySelector('button.search-btn');
  if (!input || !btn) {
    console.error(TAG, CSS, 'input.link / button.search-btn not found');
    return;
  }

  input.value = PLAYLIST;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  console.log(TAG, CSS, 'playlist filled; clicking Search...');
  btn.click();

  // ---- wait for a capture -------------------------------------------------
  const before = hits.length;
  const found = await new Promise((resolve) => {
    const t0 = Date.now();
    const iv = setInterval(() => {
      if (hits.length > before) { clearInterval(iv); resolve(true); }
      if (Date.now() - t0 > 90000) { clearInterval(iv); resolve(false); }
    }, 300);
  });

  if (!found) {
    console.error(TAG, CSS, 'no api.spotidown response in 90s');
    console.log(TAG, CSS, 'page text tail:', document.body.innerText.slice(-300));
    return;
  }

  await new Promise((r) => setTimeout(r, 800));

  // ---- report -------------------------------------------------------------
  console.log(TAG, CSS, `captured ${hits.length} response(s)`);

  const last = hits[hits.length - 1];
  console.log(TAG, CSS, 'FULL URL:', last.url);
  console.log(TAG, CSS, 'RAW BODY:');
  console.log(last.body);

  let parsed = null;
  try { parsed = JSON.parse(last.body); } catch (e) { /* not json */ }

  if (parsed) {
    console.log(TAG, CSS, 'PARSED JSON KEYS:', Object.keys(parsed));
    console.log(TAG, CSS, 'JSON:');
    console.log(JSON.stringify(parsed, null, 2));

    // try to find the track array anywhere in the object
    const findArray = (o, depth = 0) => {
      if (depth > 4 || !o || typeof o !== 'object') return null;
      if (Array.isArray(o)) return o.length ? o : null;
      for (const k of Object.keys(o)) {
        const r = findArray(o[k], depth + 1);
        if (r) return r;
      }
      return null;
    };
    const arr = findArray(parsed);
    if (arr) {
      console.log(TAG, CSS, `TRACK ARRAY found (${arr.length} items). Sample item:`);
      console.log(JSON.stringify(arr[0], null, 2));
    } else {
      console.log(TAG, CSS, 'no array found inside JSON');
    }
  }

  console.log(TAG, CSS, '=== COPY THE "JSON:" BLOCK ABOVE AND SEND IT ===');
})();
