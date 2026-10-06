"""Spotify Playlist Downloader â€” Streamlit UI (personal use).

Architecture
------------
app.py          -> Streamlit UI only (state, inputs, rendering)
core/           -> i18n strings + batch orchestrator (per-track resolve + local ZIP)
providers/      -> thin HTTP clients for the third-party backends; this is the
                   ONLY place third-party endpoints are touched. See the
                   DEPENDENCY NOTE docstrings in providers/soundloaders.py and
                   providers/spotidown.py for the exact risks.

No premium gate, upgrade prompt or paywall exists anywhere in this app.
"""
from __future__ import annotations

import time

import requests
import streamlit as st

from core import i18n
from core.cleanup import cleanup_batch
from core.orchestrator import (
    BatchOrchestrator,
    BatchResult,
    DownloadMode,
    TrackState,
    make_provider,
)
from providers.base import CaptchaRequiredError, ProviderId, ServiceError, Track
from providers.mock import _mock_mp3_bytes

# TAHAP UI (mock only): struktur UI + navigasi memakai dummy data.
# providers/* dan core/* diimpor dan dipertahankan apa adanya (tidak diubah
# pada tahap ini); download asli akan disambung kembali di tahap berikutnya.
from ui import dummy as ui_dummy

# ---------------------------------------------------------------- constants
PROVIDER_CHOICES = {
    ProviderId.SOUNDLOADERS.value: "SoundLoaders (utama / primary)",
    ProviderId.SPOTIDOWN.value: "SpotiDown (cadangan / fallback)",
    ProviderId.MOCK.value: "Demo (Mock, offline)",
}
DEMO_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

TURNSTILE_SNIPPET = """// ===== SoundLoaders: ambil token Turnstile FRESH (single-use!) =====
// Token Turnstile hanya bisa dipakai SATU KALI (aturan Cloudflare): kalau Anda
// klik Download di situsnya dulu, token itu sudah dipakai situs & hangus
// (error timeout-or-duplicate). Jadi snippet ini me-RESET widget untuk
// menerbitkan token baru yang belum dipakai siapa pun.
// Langkah:
// 1) Buka https://soundloaders.app/ (JANGAN klik Download di situs itu).
// 2) F12 -> Console, paste snippet ini -> Enter.
// 3) Selesaikan centang Turnstile yang muncul. Snippet menunggu (maks 60 dtk).
// 4) Token fresh otomatis dicopy ke clipboard -> tempel di app -> klik Proses.
// 5) JANGAN klik Download di situs sesudah copy (token langsung hangus).
(async () => {
  const grab = () => document.querySelector("input[name='cf-turnstile-response']")?.value || '';
  const old = grab();
  try {
    turnstile.reset();
    console.log('Widget di-reset. Selesaikan centang Turnstile yang muncul, snippet menunggu...');
  } catch (e) { console.log('Reset butuh interaksi manual, lanjut memantau token...'); }

  const token = await new Promise((resolve) => {
    const poll = setInterval(() => {
      const v = grab();
      if (v && v !== old && v.includes('.')) { clearInterval(poll); clearTimeout(timer); resolve(v); }
    }, 400);
    const timer = setTimeout(() => { clearInterval(poll); resolve(grab() && grab() !== old ? grab() : ''); }, 60000);
  });

  if (!token) {
    console.error('Belum ada token fresh. Selesaikan centang widget dulu lalu jalankan ulang snippet.');
    return;
  }
  if (!token.includes('.')) {
    console.warn('Token tidak seperti JWT Turnstile. Selesaikan centang dulu lalu jalankan ulang.');
    return;
  }
  try { await navigator.clipboard.writeText(token); console.log('(token disalin ke clipboard)'); }
  catch (e) { console.log('(gagal copy otomatis, salin manual dari bawah)'); }
  console.log('%cSOUNDLOADERS_TOKEN', 'color:green;font-weight:bold;font-size:1.2em');
  console.log(token);
})();"""

RECAPTCHA_SNIPPET = """// ===== SpotiDown: ambil token reCAPTCHA v3 (JANGAN auto-submit) =====
// Jalankan di Console browser pada halaman https://spotidown.app/
// Sebelum menjalankan snippet: submit URL Anda 1x lewat form situs agar
// situs menjalankan reCAPTCHA v3 & mengaitkan cookie sesi Anda.
// Snippet ini hanya meminta token baru lalu menyalinnya ke clipboard.
(async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 20 && !window.grecaptcha; i++) await wait(250);
  if (!window.grecaptcha) { console.error('grecaptcha tidak tersedia. Muat ulang halaman lalu coba lagi.'); return; }
  try {
    const token = await window.grecaptcha.execute(
      '6LcXkaUqAAAAAGvO0z9Mg54lpG22HE4gkl3XYFTK', { action: 'submit' });
    if (!token) { console.error('Token kosong. Ulangi submit form situs sekali, lalu jalankan snippet lagi.'); return; }
    try { await navigator.clipboard.writeText(token); console.log('(token disalin ke clipboard)'); }
    catch (e) { console.log('(gagal copy otomatis, salin manual dari bawah)'); }
    console.log('%cSPOTIDOWN_TOKEN', 'color:blue;font-weight:bold;font-size:1.2em');
    console.log(token);
  } catch (e) {
    console.error('reCAPTCHA execute gagal:', e);
  }
})();"""


# -------------------------------------------------------------------- state
def init_state() -> None:
    defaults = {
        "tracks": [],       # list[Track] loaded for the current URL
        "source": "",
        "per_track": {},    # idx -> {"url":..., "bytes":..., "state":...}
        "batch": None,      # BatchResult of the last batch run
        "history": [],      # one dict per finished action (batch / single)
        "lang": "id",
        "backend": ProviderId.SOUNDLOADERS.value,
        "download_mode": DownloadMode.STREAM_LOCAL.value,
        "captcha_token": "",
        "provider_obj": None,  # provider client reused so listing + resolve share one session/cookie
        # ---- TAHAP UI (mock only, sesi navigasi + dummy playlist) ----
        "page": "home",            # home | playlist | songs | covers | backup
        "playlist_url": "",        # link Spotify dari Home, dipakai semua halaman
        "dummy_playlist": None,    # dict dari ui/dummy.get_dummy_playlist
        "selected_songs": set(),   # set track id yang dicentang di Download Lagu
        "selected_covers": set(),  # set track id yang dicentang di Download Cover
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _get_provider():
    """Return the cached provider client for the current backend.

    Listing (load_tracks) and per-track resolve must share ONE requests
    session: the service binds track_token values to the session cookie that
    issued them, so a fresh client per action would invalidate every token.
    """
    backend = st.session_state.backend
    obj = st.session_state.get("provider_obj")
    if obj is not None and getattr(getattr(obj, "provider", None), "value", None) == backend:
        return obj
    obj = make_provider(backend)
    st.session_state.provider_obj = obj
    return obj


# ------------------------------------------------------------------- helpers
def render_errors(exc: Exception) -> None:
    """Render provider errors without crashing. See ServiceError in base.py."""
    lang = st.session_state.lang
    if isinstance(exc, CaptchaRequiredError):
        st.error(i18n.tr(lang, "main.captcha_error_title"))
        st.warning(i18n.tr(lang, "main.captcha_error_body", msg=exc.user_message))
        with st.expander("Technical details (provider response)"):
            st.code(exc.details or "", language=None)
        return
    if isinstance(exc, ServiceError):
        st.error(f"{i18n.tr(lang, 'main.service_error_title')} - {exc.user_message}")
        if exc.details:
            with st.expander("Technical details"):
                st.code(exc.details, language=None)
        st.caption(i18n.tr(lang, "main.network_hint"))
        return
    st.error(f"{type(exc).__name__}: {exc}")


def _is_mock() -> bool:
    return st.session_state.backend == ProviderId.MOCK.value


# ------------------------------------------------------------------ sidebar
def sidebar() -> None:
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731

    with st.sidebar:
        st.header(L("sidebar.title"))

        lang_sel = st.radio(L("sidebar.lang"), ["id", "en"], horizontal=True,
                            index=0 if lang == "id" else 1)
        if lang_sel != st.session_state.lang:
            st.session_state.lang = lang_sel

        st.subheader(L("sidebar.backend"))
        backend = st.selectbox(
            L("sidebar.backend"),
            list(PROVIDER_CHOICES.keys()),
            format_func=lambda x: PROVIDER_CHOICES[x],
            index=list(PROVIDER_CHOICES.keys()).index(st.session_state.backend),
            help=L("sidebar.backend_help"),
        )
        st.session_state.backend = backend
        if backend != st.session_state.get("_backend_seen"):
            # Backend switched -> old tracks/tokens belong to the other service.
            st.session_state["_backend_seen"] = backend
            st.session_state.provider_obj = None
            st.session_state.tracks = []
            st.session_state.source = ""
            st.session_state.per_track = {}
            st.session_state.batch = None

        token = st.text_input(
            L("sidebar.captcha"),
            value=st.session_state.captcha_token,
            placeholder="paste token here...",
            help=L("sidebar.captcha_help"),
        )
        st.session_state.captcha_token = token
        _tok = (token or "").strip()
        if _tok != st.session_state.get("_token_seen"):
            # Token content changed -> restart the freshness clock.
            st.session_state["_token_seen"] = _tok
            st.session_state["token_updated_at"] = time.time()
        if _tok:
            _age = int(time.time() - st.session_state.get("token_updated_at", time.time()))
            if _age > 240:  # Turnstile/reCAPTCHA tokens die after ~300s
                st.caption(L("sidebar.token_stale", n=len(_tok), age=_age))
            else:
                st.caption(L("sidebar.token_ok", n=len(_tok), age=_age))
        else:
            st.caption(L("sidebar.token_empty"))
        with st.expander(L("sidebar.btn_show_token_help")):
            _show_token_help(st.session_state.lang)

        mode = st.radio(
            L("sidebar.zip_mode"),
            [DownloadMode.STREAM_LOCAL.value, DownloadMode.KEEP_URL.value],
            format_func=lambda v: (L("sidebar.zip_local")
                                   if v == DownloadMode.STREAM_LOCAL.value
                                   else L("sidebar.zip_url")),
            help=L("sidebar.zip_mode_help"),
        )
        st.session_state.download_mode = mode

        if st.button(L("sidebar.clear_btn"), use_container_width=True):
            cleanup_batch(None, st.session_state.batch.zip_path if st.session_state.batch else None)
            for k in list(st.session_state.keys()):
                if k in ("lang",):
                    continue
                del st.session_state[k]
            st.rerun()


def _show_token_help(lang: str) -> None:
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    st.markdown(f"**{L('help_token.title')}**")
    if st.session_state.backend == ProviderId.SOUNDLOADERS.value:
        for s in L("help_token.sl_steps"):
            st.markdown(f"- {s}")
        st.code(TURNSTILE_SNIPPET, language="javascript")
    elif st.session_state.backend == ProviderId.SPOTIDOWN.value:
        for s in L("help_token.sd_steps"):
            st.markdown(f"- {s}")
        st.code(RECAPTCHA_SNIPPET, language="javascript")
    else:
        st.caption(L("help_token.mock_note"))
    if st.session_state.backend in (ProviderId.SOUNDLOADERS.value, ProviderId.SPOTIDOWN.value):
        st.markdown(f"**{L('help_token.note_title')}:** {L('help_token.note_body')}")


# ------------------------------------------------- TAHAP UI: navigasi (mock)
PAGES = {
    "home": "Home",
    "playlist": "Download Playlist",
    "songs": "Download Lagu",
    "covers": "Download Song Cover",
    "backup": "Backup",
}


def sidebar_nav() -> None:
    """Sidebar navigasi tahap UI. Backend asli tetap ada (tidak dihapus),
    hanya disembunyikan di expander agar tidak dipakai pada tahap mock ini."""
    with st.sidebar:
        st.header("Navigasi")
        current = st.session_state.get("page", "home")
        order = list(PAGES.keys())
        try:
            idx = order.index(current)
        except ValueError:
            idx = 0
        choice = st.radio(
            "Pilih halaman",
            order,
            format_func=lambda k: ("● " if k == current else "") + PAGES[k],
            index=idx,
            label_visibility="collapsed",
        )
        if choice != current:
            st.session_state.page = choice
            st.rerun()
        st.divider()
        if st.session_state.get("playlist_url"):
            st.caption("Playlist sesi ini:")
            st.code(st.session_state.playlist_url, language=None)
        else:
            st.caption("Belum ada playlist dimuat.")
        with st.expander("Backend asli (nonaktif tahap UI)"):
            st.caption(
                "Provider/API/scraping/Spotify/Cloudflare/CAPTCHA/download asli "
                "dipertahankan di `providers/*` + `core/*` dan tidak dipakai "
                "pada tahap mock ini."
            )
            st.caption(f"Backend tersimpan: `{st.session_state.get('backend')}`")


def main() -> None:
    st.set_page_config(page_title="Spotify Playlist Downloader", page_icon=":musical_note:",
                       layout="wide")
    init_state()
    lang = st.session_state.lang
    sidebar_nav()

    page = st.session_state.get("page", "home")
    if page == "home":
        page_home()
    elif page == "playlist":
        page_playlist()
    elif page == "songs":
        page_songs()
    elif page == "covers":
        page_covers()
    elif page == "backup":
        page_backup()
    else:
        page_home()
    show_legal(lang)


def _go(page: str) -> None:
    st.session_state.page = page
    st.rerun()


def _playlist_or_notice():
    """Kembalikan dummy_playlist, atau tampilkan peringatan + tombol ke Home."""
    pl = st.session_state.get("dummy_playlist")
    if pl:
        return pl
    st.warning("Belum ada playlist dimuat. Masukkan link Spotify di Home dulu.")
    if st.button("← Ke Home", type="primary"):
        _go("home")
    return None


def page_home() -> None:
    st.title("Spotify Playlist Downloader")
    st.caption("Tahap UI (mock) — tempel link sekali, dipakai semua halaman selama sesi.")

    url_default = st.session_state.get("playlist_url", "")
    url = st.text_input(
        "Spotify playlist URL",
        value=url_default,
        placeholder="https://open.spotify.com/playlist/...",
    )
    if st.button("Load Playlist", type="primary", use_container_width=True):
        url = (url or "").strip()
        if not url:
            st.warning("Tempel link playlist Spotify dulu.")
        else:
            # TAHAP UI: tidak fetch provider apa pun, hanya dummy.
            st.session_state.playlist_url = url
            st.session_state.dummy_playlist = ui_dummy.get_dummy_playlist(url)
            st.session_state.selected_songs = set()
            st.session_state.selected_covers = set()
            st.success(f"Playlist (dummy) dimuat: {len(st.session_state.dummy_playlist['tracks'])} lagu.")
            st.rerun()

    pl = st.session_state.get("dummy_playlist")
    if not pl:
        st.info("Setelah Load ditekan, info playlist + 4 menu akan muncul di sini.")
        return

    st.divider()
    c1, c2 = st.columns([1, 3])
    with c1:
        try:
            st.image(pl["cover"], width=220)
        except Exception:
            st.write("")
    with c2:
        st.subheader(pl["title"])
        st.caption(f"Owner: {pl['owner']} • {len(pl['tracks'])} lagu (dummy)")
        st.caption(f"Sumber: `{pl['url']}`")
        st.caption(pl["description"])

    st.divider()
    st.subheader("Pilih aksi")
    r1c1, r1c2 = st.columns(2)
    r2c1, r2c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown("**1. Download Playlist**")
            st.caption("Satu batch (≤15) atau beberapa Part (maks 15/Part). Mock.")
            if st.button("Buka →", key="nav_playlist", use_container_width=True):
                _go("playlist")
    with r1c2:
        with st.container(border=True):
            st.markdown("**2. Download Lagu**")
            st.caption("Grid card + search + pilih beberapa lagu. Mock.")
            if st.button("Buka →", key="nav_songs", use_container_width=True):
                _go("songs")
    with r2c1:
        with st.container(border=True):
            st.markdown("**3. Download Song Cover**")
            st.caption("Grid cover + search + pilih beberapa cover. Mock.")
            if st.button("Buka →", key="nav_covers", use_container_width=True):
                _go("covers")
    with r2c2:
        with st.container(border=True):
            st.markdown("**4. Backup**")
            st.caption("Pilihan format TXT / JSON / CSV. Mock.")
            if st.button("Buka →", key="nav_backup", use_container_width=True):
                _go("backup")


def page_playlist() -> None:
    st.title("Download Playlist")
    pl = _playlist_or_notice()
    if not pl:
        return
    tracks = pl["tracks"]
    st.caption(f"{pl['title']} • {len(tracks)} lagu (dummy) • sumber: `{pl['url']}`")
    parts = ui_dummy.chunk_parts(tracks, ui_dummy.BATCH_LIMIT)

    if len(tracks) <= ui_dummy.BATCH_LIMIT:
        st.success(f"Satu batch: {len(tracks)} lagu (≤ {ui_dummy.BATCH_LIMIT}). Download asli belum aktif.")
        with st.container(border=True):
            for i, t in enumerate(tracks, 1):
                st.markdown(f"{i:02d}. **{t['title']}** — {t['artist']} `({t['duration']})`")
            if st.button(f"Download Batch (Mock, {len(tracks)} lagu)", type="primary"):
                st.info("Mock: batch tidak menjalankan download asli pada tahap UI ini.")
    else:
        st.info(f"{len(tracks)} lagu dibagi menjadi {len(parts)} Part (maks {ui_dummy.BATCH_LIMIT} lagu/Part). Download asli belum aktif.")
        for p_idx, part in enumerate(parts, 1):
            with st.expander(f"Part {p_idx} — {len(part)} lagu", expanded=(p_idx == 1)):
                for j, t in enumerate(part, 1):
                    n = (p_idx - 1) * ui_dummy.BATCH_LIMIT + j
                    st.markdown(f"{n:02d}. **{t['title']}** — {t['artist']} `({t['duration']})`")
                if st.button(f"Download Part {p_idx} (Mock)", key=f"mock_part_{p_idx}"):
                    st.info(f"Mock: Part {p_idx} tidak menjalankan download asli pada tahap ini.")


def _grid_select_state(key_set: str, ids: list[str]) -> set:
    cur = st.session_state.get(key_set, set())
    if not isinstance(cur, set):
        cur = set(cur or [])
        st.session_state[key_set] = cur
    return cur


def page_songs() -> None:
    st.title("Download Lagu")
    pl = _playlist_or_notice()
    if not pl:
        return
    tracks = pl["tracks"]
    st.caption(f"{len(tracks)} lagu (dummy). Centang untuk memilih, download asli belum aktif.")

    query = st.text_input("Search lagu / artist…", placeholder="mis. neon, lumen…")
    shown = ui_dummy.filter_tracks(tracks, query)

    sel = _grid_select_state("selected_songs", [t["id"] for t in tracks])
    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("Pilih semua (hasil search)"):
            sel.update(t["id"] for t in shown)
            st.rerun()
    with b2:
        if st.button("Bersihkan"):
            sel.clear()
            for t in tracks:
                st.session_state.pop(f"song_sel_{t['id']}", None)
            st.rerun()
    with b3:
        st.caption(f"{len(sel)} lagu dipilih • {len(shown)} tampil")

    if st.button(f"Download {len(sel)} Lagu Terpilih (Mock)", type="primary", disabled=(len(sel) == 0)):
        st.info(f"Mock: {len(sel)} lagu dipilih, download asli belum dijalankan.")

    st.divider()
    cols_per_row = 3
    for i in range(0, len(shown), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, t in zip(cols, shown[i:i + cols_per_row]):
            with col:
                with st.container(border=True):
                    try:
                        st.image(t["cover"], use_container_width=True)
                    except Exception:
                        pass
                    st.markdown(f"**{t['title']}**")
                    st.caption(f"{t['artist']} • {t['duration']}")
                    checked = st.checkbox("Pilih", key=f"song_sel_{t['id']}", value=(t["id"] in sel))
                    if checked:
                        sel.add(t["id"])
                    else:
                        sel.discard(t["id"])
    if not shown:
        st.caption("Tidak ada lagu yang cocok dengan search.")


def page_covers() -> None:
    st.title("Download Song Cover")
    pl = _playlist_or_notice()
    if not pl:
        return
    tracks = pl["tracks"]
    st.caption(f"{len(tracks)} cover (dummy). Centang untuk memilih, download asli belum aktif.")

    query = st.text_input("Search cover / lagu / artist…", placeholder="mis. midnight, afterglows…", key="cover_search")
    shown = ui_dummy.filter_tracks(tracks, query)

    sel = _grid_select_state("selected_covers", [t["id"] for t in tracks])
    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("Pilih semua (hasil search)", key="cover_all"):
            sel.update(t["id"] for t in shown)
            st.rerun()
    with b2:
        if st.button("Bersihkan", key="cover_clear"):
            sel.clear()
            for t in tracks:
                st.session_state.pop(f"cover_sel_{t['id']}", None)
            st.rerun()
    with b3:
        st.caption(f"{len(sel)} cover dipilih • {len(shown)} tampil")

    if st.button(f"Download {len(sel)} Cover Terpilih (Mock)", type="primary", disabled=(len(sel) == 0)):
        st.info(f"Mock: {len(sel)} cover dipilih, download asli belum dijalankan.")

    st.divider()
    cols_per_row = 4
    for i in range(0, len(shown), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, t in zip(cols, shown[i:i + cols_per_row]):
            with col:
                with st.container(border=True):
                    try:
                        st.image(t["cover"], use_container_width=True)
                    except Exception:
                        pass
                    st.caption(f"**{t['title']}** — {t['artist']}")
                    checked = st.checkbox("Pilih cover", key=f"cover_sel_{t['id']}", value=(t["id"] in sel))
                    if checked:
                        sel.add(t["id"])
                    else:
                        sel.discard(t["id"])
    if not shown:
        st.caption("Tidak ada cover yang cocok dengan search.")


def page_backup() -> None:
    st.title("Backup")
    pl = _playlist_or_notice()
    if not pl:
        return
    st.caption("Pilih format backup (mock — file asli belum dibuat pada tahap UI ini).")
    fmt = st.radio("Format backup", ["TXT", "JSON", "CSV"], horizontal=True)

    if fmt == "TXT":
        st.code(ui_dummy.to_txt_preview(pl), language=None)
    elif fmt == "CSV":
        st.code(ui_dummy.to_csv_preview(pl), language=None)
    else:
        import json as _json
        preview = {
            "title": pl["title"],
            "source": pl["url"],
            "total": len(pl["tracks"]),
            "tracks": [
                {"no": i, "title": t["title"], "artist": t["artist"], "duration": t["duration"]}
                for i, t in enumerate(pl["tracks"][:5], 1)
            ],
            "_note": f"preview 5 dari {len(pl['tracks'])} lagu (mock)",
        }
        st.json(preview)

    if st.button(f"Buat Backup {fmt} (Mock)", type="primary"):
        st.info(f"Mock: backup {fmt} tidak membuat file asli pada tahap UI ini.")


# ------------------------------------------------- legacy backend UI (dipertahankan)
# Fungsi sidebar(), handle_process(), show_results(), _resolve_one(),
# _run_batch(), _retry_batch(), dll di bawah ini adalah sistem lama yang
# dipertahankan 100% untuk tahap download asli berikutnya. Tahap UI ini
# tidak memanggilnya.


def handle_process(raw_url: str) -> None:
    L = lambda k, **fmt: i18n.tr(st.session_state.lang, k, **fmt)  # noqa: E731
    url = (raw_url or "").strip()
    backend = st.session_state.backend

    if not url:
        if _is_mock():
            url = DEMO_URL
        else:
            st.info(L("main.url_required"))
            return
    if not _is_mock() and "spotify.com" not in url and "spotify.link" not in url:
        st.warning(L("main.url_not_spotify"))
        return

    provider = _get_provider()
    try:
        with st.spinner(i18n.tr(st.session_state.lang, "main.processing", provider=provider.name)):
            result = provider.load_tracks(url, cftoken=(st.session_state.captcha_token or "").strip())

        st.session_state.tracks = result.tracks
        st.session_state.source = result.source_url
        st.session_state.per_track = {}
        # Fresh listing -> previous batch/retry state no longer applies.
        st.session_state.batch = None
        st.session_state.pop("last_retry", None)

        if not result.tracks:
            st.info(L("main.no_tracks"))
            st.caption(L("main.no_tracks_hint"))
        st.success(L("main.tracks_found", n=len(result.tracks)))
    except Exception as exc:
        render_errors(exc)
        st.session_state.tracks = []


def show_results() -> None:
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    tracks: list = st.session_state.tracks
    mode = DownloadMode.STREAM_LOCAL if st.session_state.download_mode == DownloadMode.STREAM_LOCAL.value \
        else DownloadMode.KEEP_URL
    zip_mode = mode == DownloadMode.STREAM_LOCAL

    st.divider()
    st.caption(f"{L('main.source')}: `{st.session_state.source}`")
    st.subheader(L("main.tracks_found", n=len(tracks)))

    # ---------------- batch controls
    if zip_mode:
        batch_label = L("main.btn_batch", n=len(tracks))
    else:
        batch_label = L("main.btn_batch_url", n=len(tracks))

    c_batch = st.columns([3, 1])
    if c_batch[0].button(batch_label, type="primary", use_container_width=True):
        _run_batch(mode)

    zip_path = st.session_state.batch.zip_path if st.session_state.batch else None
    if zip_path:
        try:
            data = zip_path.read_bytes()
            c_batch[1].download_button(
                L("main.btn_zip_download"),
                data=data,
                file_name=zip_path.name,
                mime="application/zip",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"ZIP read failed: {exc}")

    _render_retry_panel(mode)

    # ---------------- track list
    query = st.text_input(L("main.filter"), key="filter_tracks").strip().lower()
    st.markdown(f"**{L('main.col_track')}**")
    shown = 0
    for idx, track in enumerate(tracks):
        if query and query not in f"{track.title} {track.artist}".lower():
            continue
        shown += 1
        _render_track_row(idx, track)
    if shown == 0:
        st.caption(L("main.no_match"))

    # ---------------- history
    st.divider()
    st.subheader(L("main.history_title"))
    if not st.session_state.history:
        st.caption(L("main.none_done"))
    else:
        for row in st.session_state.history[-10:]:
            status = row.get("status", "")
            if row.get("failed"):
                st.markdown(f"- {row['time']} **{row['provider']}** - {status}")
            else:
                st.markdown(f"- {row['time']} **{row['provider']}** `{row['url'][:60]}` - {status}")


def _render_track_row(idx: int, track: Track) -> None:
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    info = st.session_state.per_track.get(str(idx), {})

    thumb = track.thumbnail or ""
    cols = st.columns([1, 6, 3])
    if thumb:
        try:
            cols[0].image(thumb, width=44)
        except Exception:
            cols[0].write("")
    else:
        cols[0].write("")
    cols[1].markdown(f"**{track.title}**  \n{track.artist}")

    cell = cols[2]
    if info.get("state") == TrackState.FAILED.value:
        cell.error(L("main.status_failed"))
        if info.get("captcha"):
            cell.caption(L("main.token_refresh_hint"))
    elif info.get("bytes") is not None:
        cell.download_button(
            L("main.btn_download_mp3"),
            data=info["bytes"],
            file_name=f"{track.filename}.mp3",
            mime="audio/mpeg",
            key=f"dls_{idx}",
            use_container_width=True,
        )
    elif info.get("url"):
        cell.success(L("main.status_ready"))
        cell.markdown(f"[{L('main.open_mp3')}]({info['url']})")
    else:
        if cell.button(L("main.btn_download_one"), key=f"dl_{idx}", use_container_width=True):
            _resolve_one(idx)


def _resolve_one(idx: int) -> None:
    """Resolve a single track's MP3 (and fetch bytes in ZIP mode)."""
    L = lambda k, **fmt: i18n.tr(st.session_state.lang, k, **fmt)  # noqa: E731
    tracks: list = st.session_state.tracks
    if idx >= len(tracks):
        return
    track = tracks[idx]
    mode = DownloadMode.STREAM_LOCAL if st.session_state.download_mode == DownloadMode.STREAM_LOCAL.value \
        else DownloadMode.KEEP_URL

    provider = _get_provider()
    entry = {"state": TrackState.PROCESSING.value}
    st.session_state.per_track[str(idx)] = entry
    try:
        with st.spinner(i18n.tr(st.session_state.lang, "main.processing", provider=provider.name)):
            mp3_url = provider.resolve_track(track, cftoken=(st.session_state.captcha_token or "").strip())
        entry["url"] = mp3_url
        if mode == DownloadMode.STREAM_LOCAL:
            entry["bytes"] = _fetch_bytes(mp3_url)
        entry["state"] = TrackState.READY.value
        st.session_state.history.append({
            "time": _now(), "provider": provider.name, "url": track.title,
            "status": f"MP3 ready: {mp3_url[:70]}",
        })
    except Exception as exc:
        entry["state"] = TrackState.FAILED.value
        entry["captcha"] = isinstance(exc, CaptchaRequiredError)
        render_errors(exc)
        st.session_state.history.append({
            "time": _now(), "provider": provider.name, "url": track.title,
            "status": f"Failed: {exc}", "failed": True,
        })


def _fetch_bytes(mp3_url: str) -> bytes:
    if mp3_url.startswith("mock://"):
        return _mock_mp3_bytes()
    resp = requests.get(mp3_url, timeout=60, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _run_batch(mode: DownloadMode) -> None:
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    tracks: list = st.session_state.tracks
    provider = _get_provider()

    bar = st.progress(0.0, text="")
    status = st.empty()

    def progress(i, state, outcome, message):
        frac = (i + 1) / len(tracks) if tracks else 1.0
        bar.progress(frac, text=L("main.status_" + state.value))
        status.caption(f"[{i + 1}/{len(tracks)}] {outcome.title or ''} - {message}")

    try:
        orch = BatchOrchestrator(provider, mode=mode)
        # Small pause between tracks: rapid-fire POSTs trigger the service's
        # rate-limit and fail half the playlist.
        result = orch.run(tracks, cftoken=(st.session_state.captcha_token or "").strip(), progress=progress,
                          pause_secs=1.0)
        st.session_state.batch = result
        _show_batch_result(result, status)
    except Exception as exc:
        render_errors(exc)


def _render_retry_panel(mode: DownloadMode) -> None:
    """Persistent retry panel: re-request only failed tracks with a new token.

    Shown on every rerun while the current batch still has failures, so the
    user can solve the CAPTCHA again, paste the fresh token in the sidebar,
    and continue without re-running the whole playlist.
    """
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    batch = st.session_state.batch

    last = st.session_state.pop("last_retry", None)
    if last and last.get("retried", 0) > 0 and (batch is None or batch.failed == 0):
        if last.get("still_failed", 0) == 0:
            st.success(L("main.retry_all_ok"))
        else:
            st.info(L("main.retry_done", ok=last.get("recovered", 0), fail=last.get("still_failed", 0)))
    elif last and batch is not None and batch.failed > 0:
        # Retry ran but failures remain -> keep the summary for context.
        st.info(L("main.retry_done", ok=last.get("recovered", 0), fail=last.get("still_failed", 0)))

    if batch is None:
        return
    failed = [o for o in batch.outcomes if o.state == TrackState.FAILED]
    if not failed:
        return
    cap = sum(1 for o in failed if o.error_kind == "captcha")
    if cap:
        st.warning(L("main.retry_token_title", c=cap, n=len(failed)))
    else:
        st.info(L("main.retry_other_title", n=len(failed)))
    st.caption(L("main.retry_hint"))
    if st.button(L("main.btn_retry", n=len(failed)), key="retry_failed_btn"):
        _retry_batch(mode)


def _retry_batch(mode: DownloadMode) -> None:
    """Retry failed batch tracks with the token currently in the sidebar."""
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    batch = st.session_state.batch
    tracks: list = st.session_state.tracks
    if not batch or not tracks:
        return
    failed = [o for o in batch.outcomes if o.state == TrackState.FAILED]
    if not failed:
        return
    new_token = (st.session_state.captcha_token or "").strip()
    if not new_token:
        st.warning(L("main.retry_no_token"))
        return

    # Same cached provider as the original run -> same session/cookies, so the
    # track_token values stay valid; only the CAPTCHA token is fresh.
    provider = _get_provider()
    bar = st.progress(0.0, text="")
    status = st.empty()

    def progress(i, state, outcome, message):
        frac = (i + 1) / max(1, len(failed))
        bar.progress(frac, text=L("main.status_" + state.value))
        status.caption(f"retry [{i + 1}/{len(tracks)}] {outcome.title or ''} - {message}")

    orch = BatchOrchestrator(provider, mode=mode)
    summary = orch.retry_failed(batch, tracks, cftoken=new_token, progress=progress, pause_secs=1.0)
    st.session_state.last_retry = summary
    st.session_state.history.append({
        "time": _now(), "provider": batch.provider, "url": st.session_state.source,
        "status": L("main.retry_done", ok=summary["recovered"], fail=summary["still_failed"]),
        "failed": summary["still_failed"] > 0,
    })
    st.rerun()


def _show_batch_result(result: BatchResult, status_el) -> None:
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    status_el.success(f"**{L('main.batch_done')}** {result.summary}")

    ready = [o for o in result.outcomes if o.state == TrackState.READY]
    failed = [o for o in result.outcomes if o.state == TrackState.FAILED]

    if failed:
        with st.expander(L("main.batch_failed_list", n=len(failed))):
            for o in failed:
                tag = " [token]" if o.error_kind == "captcha" else f" [{o.error_kind}]" if o.error_kind else ""
                st.markdown(f"- {o.title or o.index}{tag}: {o.error}")

    if result.zip_path:
        st.info(L("main.zip_ready"))
    elif ready:
        with st.expander(L("main.batch_ready_list", n=len(ready))):
            for o in ready:
                if o.mp3_url:
                    st.markdown(f"- {o.title}: [MP3 URL]({o.mp3_url})")

    st.session_state.history.append({
        "time": _now(), "provider": result.provider, "url": st.session_state.source,
        "status": result.summary,
    })
    if failed:
        st.session_state.history.append({
            "time": _now(), "provider": result.provider, "url": st.session_state.source,
            "status": f"{len(failed)} failed", "failed": True,
        })


def show_legal(lang: str) -> None:
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    with st.expander(":balance_scale: " + L("legal.title"), expanded=False):
        for key in ("legal.personal", "legal.no_scraper", "legal.tos",
                    "legal.no_guarantee", "legal.your_responsibility"):
            st.markdown("- " + L(key))


if __name__ == "__main__":
    main()
