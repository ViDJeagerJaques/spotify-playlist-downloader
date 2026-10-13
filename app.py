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

import html
import json
import re
import time
from pathlib import Path

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
from providers.base import (
    CaptchaRequiredError,
    ProviderId,
    ResolveResult,
    ServiceError,
    Track,
)
from providers.mock import _mock_mp3_bytes

# TAHAP UI (mock only): struktur UI + navigasi memakai dummy data.
# providers/* dan core/* diimpor dan dipertahankan apa adanya (tidak diubah
# pada tahap ini); download asli akan disambung kembali di tahap berikutnya.
from ui import data as ui_data
from ui import dummy as ui_dummy
from ui import theme as ui_theme

# ---------------------------------------------------------------- constants
# Default is YouTube: no browser, no CAPTCHA, runs on a VPS. The metadata comes
# from Spotify's public embed page (no auth at all), so no .env is needed for
# public playlists.
PROVIDER_CHOICES = {
    ProviderId.YOUTUBE.value: "YouTube via yt-dlp (default — tanpa browser)",
    ProviderId.SPOTIDOWN_CO.value: "SpotiDown.co (legacy — butuh Chrome terbuka)",
    ProviderId.SOUNDLOADERS.value: "SoundLoaders (legacy — butuh token Cloudflare)",
    ProviderId.SPOTIDOWN.value: "SpotiDown.app (legacy — butuh token reCAPTCHA)",
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
        "backend": ProviderId.YOUTUBE.value,
        "download_mode": DownloadMode.STREAM_LOCAL.value,
        "captcha_token": "",
        "provider_obj": None,  # provider client reused so listing + resolve share one session/cookie
        # ---- TAHAP UI: navigasi + playlist asli (spotiDown.co) ----
        "page": "home",              # home | playlist | songs | covers | backup
        "playlist_url": "",          # link Spotify dari Home, dipakai semua halaman
        "playlist_view": None,       # dict hasil ui_data.playlist_view()
        "real_tracks": [],           # list[Track] asli (punya mp3_url + thumbnail)
        "covers_loaded": 0,          # berapa lagu yang memakai cover album asli
        "cover_note": "",            # catatan kalau cover per lagu tak lengkap
        "ui_batch": None,            # BatchResult terakhir
        "ui_batch_label": "",        # label batch terakhir (mis. "Part 1")
        "ui_batch_tracks": [],       # Track[] yang jadi target batch terakhir
        "cover_zip": None,           # Path ZIP cover terakhir
        "selected_songs": set(),     # set track id yang dicentang di Download Lagu
        "selected_covers": set(),    # set track id yang dicentang di Download Cover
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


# ------------------------------------------------- TAHAP UI: navigasi
PAGES = {
    "home": "Home",
    "playlist": "Download Playlist",
    "songs": "Download Lagu",
    "covers": "Download Song Cover",
    "backup": "Backup",
}


def sidebar_nav() -> None:
    """Sidebar: navigasi halaman + pemilih backend.

    Backend asli (SoundLoaders / SpotiDown.app) TIDAK dihapus — semuanya masih
    bisa dipilih sebagai cadangan. SpotiDown.co adalah default karena dua
    provider lama butuh token CAPTCHA yang terikat session browser.
    """
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
        st.subheader("Backend")
        keys = list(PROVIDER_CHOICES.keys())
        backend = st.selectbox(
            "Backend service",
            keys,
            format_func=lambda k: PROVIDER_CHOICES[k],
            index=keys.index(st.session_state.backend) if st.session_state.backend in keys else 0,
        )
        if backend != st.session_state.backend:
            # Backend switched -> previously loaded tracks came from another
            # service, and their short-lived MP3 links are not reusable.
            st.session_state.backend = backend
            st.session_state.provider_obj = None
            _reset_playlist_state()
            st.rerun()
        if backend == ProviderId.YOUTUBE.value:
            with st.expander("Kebutuhan & batasan (YouTube)", expanded=False):
                st.markdown(
                    "- **Audio berasal dari YouTube**, bukan dari Spotify. "
                    "Kualitas = hasil upload di YouTube; kadang bisa salah versi.\n"
                    "- Daftar lagu dibaca dari **halaman embed publik Spotify** — "
                    "tanpa login, tanpa credential.\n"
                    "- Butuh **`yt-dlp`** (`pip install -U yt-dlp`, sering diupdate) "
                    "dan **`ffmpeg`** di PATH.\n"
                    "- **YouTube memblokir IP datacenter/VPS** (\"Sign in to confirm "
                    "you're not a bot\"). Deploy publik butuh proxy residential "
                    "(berbayar). Di PC rumah aman.\n"
                    "- Lambat: tiap lagu = search + download + konversi. Jangan "
                    "naikkan jumlah worker.\n"
                    "- Personal use saja."
                )
        elif backend == ProviderId.SPOTIDOWN_CO.value:
            st.warning("Backend legacy. Butuh **Chrome terpasang** dan jendela "
                       "Chrome akan terbuka di layar — jangan ditutup/minimize "
                       "saat proses berjalan.", icon="⚠️")
        elif backend in (ProviderId.SOUNDLOADERS.value, ProviderId.SPOTIDOWN.value):
            st.warning("Backend legacy: butuh token CAPTCHA manual yang "
                       "diambil dari browser Anda sendiri (lihat README).",
                       icon="⚠️")

        st.divider()
        if st.session_state.get("playlist_url"):
            st.caption("Playlist sesi ini:")
            st.code(st.session_state.playlist_url, language=None)
        else:
            st.caption("Belum ada playlist dimuat.")
        if st.session_state.get("playlist_url") and st.button("Ganti playlist", use_container_width=True):
            _reset_playlist_state()
            _go("home")


def _reset_playlist_state() -> None:
    """Buang playlist + hasil unduhan lama (link MP3 juga kedaluwarsa cepat)."""
    cleanup_batch(None, st.session_state.get("ui_batch").zip_path
                  if st.session_state.get("ui_batch") else None)
    cleanup_batch(None, st.session_state.get("cover_zip"))
    st.session_state.playlist_url = ""
    st.session_state.playlist_view = None
    st.session_state.real_tracks = []
    st.session_state.covers_loaded = 0
    st.session_state.cover_note = ""
    st.session_state.ui_batch = None
    st.session_state.ui_batch_label = ""
    st.session_state.ui_batch_tracks = []
    st.session_state.cover_zip = None
    st.session_state.selected_songs = set()
    st.session_state.selected_covers = set()
    st.session_state.provider_obj = None


def main() -> None:
    st.set_page_config(page_title="Spotify Playlist Downloader", page_icon=":musical_note:",
                       layout="wide")
    init_state()
    lang = st.session_state.lang
    ui_theme.inject_theme()   # NX9 colours + fonts, once per rerun
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
    """Kembalikan playlist_view, atau tampilkan peringatan + tombol ke Home."""
    view = st.session_state.get("playlist_view")
    if view:
        return view
    st.warning("Belum ada playlist dimuat. Masukkan link Spotify di Home dulu.")
    if st.button("← Ke Home", type="primary"):
        _go("home")
    return None


def _load_playlist(url: str) -> None:
    """Muat playlist lewat provider aktif (atau dummy bila backend Demo)."""
    backend = st.session_state.backend
    if backend == ProviderId.MOCK.value:
        dummy = ui_dummy.get_dummy_playlist(url)
        tracks = []
        for t in dummy["tracks"]:
            tracks.append(Track(data=t["id"], track_token=t["id"], title=t["title"],
                                artist=t["artist"], thumbnail=t["cover"], mp3_url=None))
        st.session_state.real_tracks = tracks
        st.session_state.playlist_view = ui_data.playlist_view(
            _mock_result(dummy["title"], url, tracks))
        return

    provider = _get_provider()
    if backend == ProviderId.SPOTIDOWN_CO.value:
        note = "Membuka Chrome. jangan tutup/minimize jendela Chrome yang muncul."
    elif backend == ProviderId.YOUTUBE.value:
        note = "Membaca daftar lagu dari halaman publik Spotify."
    else:
        note = "Menghubungi layanan."

    # Reading a large playlist means one /embed/track + one oEmbed request per
    # song (213 songs took ~77 s on a cold cache), so show real progress rather
    # than an indefinite spinner.
    progress_bar = None
    status_line = None
    if backend == ProviderId.YOUTUBE.value:
        progress_bar = st.progress(0.0, text=note)
        status_line = st.empty()

    def _report(done: int, total: int) -> None:
        if progress_bar is None:
            return
        frac = min(done / max(1, total), 1.0)
        progress_bar.progress(frac, text=f"{note} — {done}/{total} lagu")
        if status_line is not None:
            status_line.caption(f"Mengambil cover album asli: {done}/{total}")

    try:
        with st.spinner(note, show_time=True):
            result = provider.load_tracks(url, progress=_report)
    except TypeError:
        # Legacy providers do not accept a progress callback.
        result = provider.load_tracks(url)
    finally:
        if progress_bar is not None:
            progress_bar.empty()
        if status_line is not None:
            status_line.empty()

    st.session_state.real_tracks = result.tracks

    # Header extras (owner, total duration) discovered while loading. The
    # provider already fetched them, so this makes no extra request.
    owner, total_ms = _embed_header_info(provider)
    view = ui_data.playlist_view(result)
    view["owner"] = owner
    # The playlist's own cover. Falls back to the first track's album art when a
    # legacy provider (SpotiDown.co / SoundLoaders) doesn't supply one.
    view["playlist_cover"] = getattr(provider, "last_playlist_cover", "") or ""
    view["total_duration_ms"] = view.get("total_duration_ms") or total_ms
    st.session_state.playlist_view = view

    # Covers for songs the embed page could not describe. The default provider
    # (YouTube -> SpotifyMeta -> embed_tracks_complete) already filled these in,
    # so this only does work for the legacy backends.
    st.session_state.covers_loaded = 0
    st.session_state.cover_note = ""
    if backend != ProviderId.MOCK.value and _needs_cover_pass(view):
        _enrich_covers(result.tracks, view)


def _needs_cover_pass(view: dict) -> bool:
    """True when tracks are still sharing the playlist's single cover image."""
    rows = view.get("tracks") or []
    if not rows:
        return False
    covers = {r.get("cover") for r in rows}
    return len(covers) <= 1


def _embed_header_info(provider) -> tuple[str, int]:
    """Owner + total duration already discovered while loading the playlist.

    The provider reads them from the same embed page it fetched for the track
    list, so this never makes a second network call. Older providers simply
    report empty values and the header omits those lines.
    """
    owner = str(getattr(provider, "last_owner", "") or "")
    total_ms = int(getattr(provider, "last_total_duration_ms", 0) or 0)
    return owner, total_ms


def _enrich_covers(tracks: list, view: dict) -> None:
    """Replace the shared playlist image with each track's real album cover.

    Needs Spotify API credentials in ``.env``; without them every track keeps
    the playlist cover and we say so instead of failing.
    """
    from providers.spotify_embed import fetch_album_covers

    ids = [t.track_token or t.data for t in tracks]
    ids = [i for i in ids if i]
    if not ids:
        return
    try:
        with st.spinner("Menyiapkan cover album…"):
            covers = fetch_album_covers(ids)
    except Exception as exc:  # noqa: BLE001 - covers are cosmetic
        st.session_state.cover_note = f"Cover per lagu gagal dimuat: {exc}"
        return

    if not covers:
        st.session_state.cover_note = (
            "Cover per lagu belum bisa dimuat. Playlist tetap berjalan dengan "
            "cover playlist."
        )
        return

    n = ui_data.apply_track_covers(view, covers)
    st.session_state.covers_loaded = n
    if n < len(tracks):
        st.session_state.cover_note = (
            f"{n}/{len(tracks)} lagu memakai cover album aslinya; sisanya "
            "memakai cover playlist (lagu tidak tersedia di region ini atau "
            "dihapus dari Spotify)."
        )


def _mock_result(title: str, url: str, tracks: list) -> ResolveResult:
    return ResolveResult(title=title, source_url=url, tracks=tracks)


def _prefetched_urls() -> bool:
    """True when the backend hands out ready MP3 URLs during load_tracks().

    The YouTube provider does NOT: it builds the MP3 locally during download,
    so mp3_url is empty by design and we must not flag it as missing.
    """
    provider = st.session_state.get("provider_obj")
    return bool(getattr(provider, "prefetched_urls", False))


def _tracks_by_id() -> dict:
    out = {}
    for t in st.session_state.get("real_tracks", []):
        out[t.track_token or t.data or t.title] = t
    return out


# NOTE: the name is deliberately distinct from the legacy `_run_batch()` below,
# which the legacy flow still owns.
def _run_ui_batch(tracks: list, label: str) -> BatchResult:
    """Jalankan batch download (STREAM_LOCAL -> ZIP) dengan progress di UI."""
    provider = _get_provider()
    orch = BatchOrchestrator(provider, mode=DownloadMode.STREAM_LOCAL)
    bar = st.progress(0.0, text="Mulai…")
    status = st.empty()

    def progress(i, state, outcome, message):
        total = len(tracks) or 1
        bar.progress(min((i + 1) / total, 1.0), text=f"{i + 1}/{len(tracks)}")
        status.caption(f"[{i + 1}/{len(tracks)}] {outcome.title or ''} — {state.value}")

    # No pause between tracks: downloads run serially, which keeps us far below
    # the parallel load that makes the CDN reject requests (Jebakan 3).
    result = orch.run(tracks, cftoken="", progress=progress, pause_secs=0.0)

    previous = st.session_state.get("ui_batch")
    if previous is not None and previous.zip_path:
        cleanup_batch(None, previous.zip_path)
    st.session_state.ui_batch = result
    st.session_state.ui_batch_label = label
    st.session_state.ui_batch_tracks = list(tracks)
    status.empty()
    return result


def _render_ui_batch_result() -> None:
    """Tampilkan hasil batch terakhir + tombol ZIP + panel retry."""
    result = st.session_state.get("ui_batch")
    if result is None:
        return
    label = st.session_state.get("ui_batch_label") or "Batch"
    st.divider()
    st.subheader(f"Hasil: {label}")
    if result.failed:
        st.warning(f"{result.ok}/{result.total} berhasil, {result.failed} gagal — {result.summary}")
    else:
        st.success(f"{result.ok}/{result.total} berhasil — {result.summary}")

    if st.session_state.backend == ProviderId.YOUTUBE.value:
        st.caption("Audio diambil dari YouTube. Kalau ada lagu gagal, sering "
                   "karena tidak ada versi yang cocok di YouTube — ganti judul "
                   "di kotak search, atau unduh lagunya satu per satu dari "
                   "halaman Download Lagu.")

    if result.zip_path and result.zip_path.exists():
        try:
            st.download_button(
                "Download ZIP",
                data=result.zip_path.read_bytes(),
                file_name=result.zip_path.name,
                mime="application/zip",
                use_container_width=True,
                key="zip_dl",
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Gagal membaca ZIP: {exc}")

    failed = [o for o in result.outcomes if o.state == TrackState.FAILED]
    if failed:
        with st.expander(f"{len(failed)} lagu gagal — detail"):
            for o in failed:
                st.markdown(f"- {o.index + 1:02d}. {o.title}: {o.error}")
        if st.button(f"Ulangi {len(failed)} lagu gagal", key="ui_retry"):
            tracks = st.session_state.get("ui_batch_tracks") or []
            orch = BatchOrchestrator(_get_provider(), mode=DownloadMode.STREAM_LOCAL)
            bar = st.progress(0.0, text="Retry…")

            def rprogress(i, state, outcome, message):
                bar.progress(min((i + 1) / max(1, len(failed)), 1.0),
                             text=f"{i + 1}/{len(failed)}")
            summary = orch.retry_failed(result, tracks, cftoken="",
                                        progress=rprogress, pause_secs=0.0)
            st.info(f"Retry selesai: {summary['recovered']} pulih, "
                    f"{summary['still_failed']} masih gagal.")
            if summary["still_failed"]:
                st.caption("Penyebab paling umum: link MP3 dari spotidown.co "
                           "kedaluwarsa (butuh ±10 menit). Muat ulang playlist di "
                           "Home untuk dapat link baru, lalu ulangi.")
            st.rerun()


def _fetch_mp3_bytes(track: Track) -> bytes:
    """Ambil satu file MP3 ke memory (tombol "Unduh 1 lagu" di grid/list).

    Delegates to :func:`_fetch_bytes` so this page understands all three
    provider shapes (mock://, local file from YouTube, real HTTP URL) instead of
    only the HTTP one.
    """
    provider = _get_provider()
    resolved = track.mp3_url or provider.resolve_track(track, cftoken="")
    headers = getattr(provider, "download_headers", None)
    if callable(headers):
        return _fetch_bytes_with_headers(resolved, headers())
    return _fetch_bytes(resolved)


def _fetch_bytes_with_headers(resolved: str, headers: dict) -> bytes:
    """``_fetch_bytes`` plus the provider-specific headers (legacy providers).

    Local-file handling is shared with :func:`_fetch_bytes` so the YouTube path
    cannot regress here.
    """
    if resolved.startswith("mock://") or _looks_like_filesystem_path(resolved):
        return _fetch_bytes(resolved)
    with requests.get(resolved, timeout=180, allow_redirects=True, headers=headers) as r:
        r.raise_for_status()
        return r.content


def _build_cover_zip(tracks: list) -> Path:
    """Download cover terpilih lalu kumpulkan jadi satu ZIP."""
    import tempfile
    import zipfile

    staging = Path(tempfile.mkdtemp(prefix="spl_cover_"))
    headers = {"User-Agent": ui_data.download_headers().get("User-Agent", "")}
    ok = 0
    for t in tracks:
        if not t.thumbnail:
            continue
        try:
            with requests.get(t.thumbnail, timeout=60, headers=headers) as r:
                r.raise_for_status()
                (staging / f"{t.filename}.jpg").write_bytes(r.content)
            ok += 1
        except Exception:  # noqa: BLE001 - skip covers that fail
            continue
    zip_path = Path(tempfile.gettempdir()) / f"spl_cover_{int(time.time()*1000)}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(staging.glob("*.jpg")):
            zf.write(f, arcname=f.name)
    try:
        staging.rmdir()
    except Exception:  # noqa: BLE001
        pass
    st.session_state.cover_count = ok
    return zip_path


def _render_oauth_prompt() -> None:
    """Optional Spotify sign-in, shown only when the playlist hit the 100 cap (#1).

    Completely optional: without it the app still works for playlists up to 100
    songs. It never blocks anything, and no credential is stored in code — only
    a refresh token the user puts in their own ``.env``.
    """
    from providers.spotify_meta import authorize_url, refresh_token_present

    if refresh_token_present():
        return  # already connected; nothing to offer

    with st.expander("Playlist private? Hubungkan Spotify (opsional)",
                     expanded=False):
        st.markdown(
            "Playlist **publik** dibaca penuh tanpa login — tidak ada lagi "
            "batas 100 lagu.\n\n"
            "Kamu hanya perlu ini kalau playlistnya **private** (atau kamu "
            "ingin app membaca playlist milikmu sendiri). globalement "
            "`SPOTIFY_REFRESH_TOKEN` membuka jalur baca playlist private.\n\n"
            "**Sekali saja:**\n"
            "1. Pastikan `.env` berisi `SPOTIFY_CLIENT_ID` dan "
            "`SPOTIFY_CLIENT_SECRET`.\n"
            "2. Buka link di bawah, login ke Spotify, lalu izinkan.\n"
            "3. Salin `code` dari URL hasil, tempel di kotak bawah.\n"
            "4. Klik **Simpan ke .env**, lalu **Load Playlist** lagi."
        )
        try:
            url = authorize_url()
        except ServiceError as exc:
            st.warning(exc.user_message)
            return

        st.link_button("Buka halaman login Spotify", url)

        code = st.text_input("Tempel code dari URL hasil:", key="oauth_code",
                             placeholder="AQ... (code dari Spotify)")
        if st.button("Simpan ke .env", key="oauth_save"):
            _save_refresh_token_from_code(code.strip())

        st.caption(
            "Token disimpan hanya di file `.env` milikmu (sudah masuk "
            "`.gitignore`, jangan di-commit). Playlist private juga jadi terbaca."
        )


def _save_refresh_token_from_code(code: str) -> None:
    """Exchange an Authorization Code for a refresh token and append it to .env."""
    if not code:
        st.warning("Tempel code dulu.")
        return
    import base64 as _b64
    import urllib.parse as _up
    import urllib.request as _ur

    from providers.base import ServiceError as _SE
    from providers.spotify_meta import TOKEN_URL, USER_SCOPES, credentials

    try:
        cid, secret = credentials()
    except _SE as exc:
        st.warning(exc.user_message)
        return

    basic = _b64.b64encode(f"{cid}:{secret}".encode()).decode()
    data = _up.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://localhost:8501",
    }).encode()
    req = _ur.Request(TOKEN_URL, data=data,
                      headers={"Authorization": f"Basic {basic}",
                               "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _ur.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Spotify menolak code itu: {exc}. Coba ambil code baru "
                 "(code hanya bisa dipakai sekali dan cepat kedaluwarsa).")
        return

    token = payload.get("refresh_token")
    if not token:
        st.error("Spotify tidak mengirim refresh_token.")
        return

    env_path = Path.cwd() / ".env"
    try:
        existing = env_path.read_text(encoding="utf-8").splitlines() \
            if env_path.exists() else []
        kept = [ln for ln in existing if not ln.startswith("SPOTIFY_REFRESH_TOKEN=")]
        kept.append(f"SPOTIFY_REFRESH_TOKEN={token}")
        env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as exc:
        st.error(f"Tidak bisa menulis .env: {exc}")
        return

    st.success("Tersimpan di .env. Klik **Load Playlist** di Home untuk "
               "membaca playlist private.")
    st.session_state.provider_obj = None  # force a fresh client on next load


def _render_playlist_header(view: dict, tracks: list) -> None:
    """Spotify-like header: square cover + title, owner, song count, duration (#3).

    Everything shown here already exists in the embed page — nothing is guessed.
    """
    # The playlist's OWN artwork, not the first track's album cover — after the
    # per-track cover work (R1) the tracks no longer share the playlist image,
    # so picking from them would show an unrelated album.
    cover = view.get("playlist_cover") or next(
        (t["cover"] for t in tracks if t.get("cover")), "")

    art_col, body_col = st.columns([1, 3.2], gap="large")
    with art_col:
        if cover:
            # .nx9-art-img forces aspect-ratio 1/1 with object-fit: cover, which
            # st.image(width=200) cannot do (it keeps the source ratio).
            st.markdown(
                f'<div class="nx9-art-img nx9-art-lg">'
                f'<img src="{html.escape(cover, quote=True)}" alt=""></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="nx9-art-img nx9-art-lg"></div>',
                        unsafe_allow_html=True)

    with body_col:
        st.markdown(f'<div class="nx9-header-title">{view["title"]}</div>',
                    unsafe_allow_html=True)
        bits = []
        if view.get("owner"):
            bits.append(f"oleh {view['owner']}")
        bits.append(f"{len(tracks)} lagu")
        if view.get("total_duration_ms"):
            bits.append(ui_data.format_total_duration(view["total_duration_ms"]))
        parts = ui_data.chunk_parts(tracks, ui_data.PART_SIZE)
        if len(parts) <= 1:
            bits.append("1 ZIP penuh")
        else:
            bits.append(f"{len(parts)} bagian ZIP")
        st.markdown(f'<div class="nx9-header-meta">{" • ".join(bits)}</div>',
                    unsafe_allow_html=True)
        st.caption(f"Sumber: `{view['url']}`")

        if st.session_state.backend == ProviderId.YOUTUBE.value:
            st.caption("Daftar lagu: Spotify (halaman publik). "
                       "Audio: YouTube — dicari & diunduh saat kamu klik download.")
        else:
            with_mp3 = sum(1 for t in tracks if t.get("mp3_url"))
            st.caption(f"{with_mp3}/{len(tracks)} lagu punya link MP3 dari layanan.")


def page_home() -> None:
    st.title("Spotify Playlist Downloader")
    st.caption("Tempel link sekali di Home — semua halaman memakai playlist "
               "yang sama selama sesi.")

    # Only a widget key here: passing `value=` together with `key=` makes
    # Streamlit ignore the value, so the widget keeps its own state instead.
    url = st.text_input(
        "Spotify playlist URL",
        key="home_url_input",
        placeholder="https://open.spotify.com/playlist/...",
    )
    if st.button("Load Playlist", type="primary", use_container_width=True):
        url = (url or "").strip()
        if not url:
            st.warning("Tempel link playlist Spotify dulu.")
        else:
            _reset_playlist_state()
            st.session_state.playlist_url = url
            try:
                _load_playlist(url)
                st.rerun()
            except CaptchaRequiredError as exc:
                render_errors(exc)
            except ServiceError as exc:
                st.error(exc.user_message)
                with st.expander("Detail teknis"):
                    st.code(exc.details or "", language=None)
            except Exception as exc:  # noqa: BLE001 - never crash the page
                st.error(f"Gagal memuat playlist: {type(exc).__name__}: {exc}")

    view = st.session_state.get("playlist_view")
    if not view:
        st.info("Klik **Load Playlist** untuk memuat daftar lagu. "
                "SpotiDown.co membuka jendela Chrome untuk solving CAPTCHA-nya "
                "sendiri — biarkan jendela itu terbuka.")
        return

    tracks = view["tracks"]
    if view.get("hint"):
        st.warning(view["hint"])

    st.divider()
    _render_oauth_prompt()
    _render_playlist_header(view, tracks)

    note = st.session_state.get("cover_note") or ""
    if note:
        st.info(note, icon="ℹ️")

    st.divider()
    st.subheader("Pilih aksi")
    r1c1, r1c2 = st.columns(2)
    r2c1, r2c2 = st.columns(2)
    with r1c1:
        with st.container(border=True):
            st.markdown("**1. Download Playlist**")
            st.caption(f"ZIP penuh ≤ {ui_data.PART_SIZE} lagu, di atas itu jadi "
                       f"Part ({ui_data.PART_SIZE} lagu/Part).")
            if st.button("Buka →", key="nav_playlist", use_container_width=True):
                _go("playlist")
    with r1c2:
        with st.container(border=True):
            st.markdown("**2. Download Lagu**")
            st.caption("Grid card + search + pilih beberapa lagu.")
            if st.button("Buka →", key="nav_songs", use_container_width=True):
                _go("songs")
    with r2c1:
        with st.container(border=True):
            st.markdown("**3. Download Song Cover**")
            st.caption("Grid cover + search + pilih beberapa cover → ZIP gambar.")
            if st.button("Buka →", key="nav_covers", use_container_width=True):
                _go("covers")
    with r2c2:
        with st.container(border=True):
            st.markdown("**4. Backup**")
            st.caption("Export metadata TXT / JSON / CSV.")
            if st.button("Buka →", key="nav_backup", use_container_width=True):
                _go("backup")


def page_playlist() -> None:
    st.title("Download Playlist")
    view = _playlist_or_notice()
    if not view:
        return
    rows = view["tracks"]
    st.caption(f"{view['title']} • {len(rows)} lagu • sumber: `{view['url']}`")
    if view.get("hint"):
        st.warning(view["hint"])

    by_id = _tracks_by_id()
    parts = ui_data.chunk_parts(rows, ui_data.PART_SIZE)

    # Preview the split BEFORE the user clicks anything.
    if len(rows) <= ui_data.PART_SIZE:
        st.success(f"**ZIP Full (1 file)** — {len(rows)} lagu "
                   f"(≤ {ui_data.PART_SIZE}).")
    else:
        st.info(f"**ZIP Part ({len(parts)} bagian, {ui_data.PART_SIZE} lagu/bagian)** "
                f"— {len(rows)} lagu total.")

    for p_idx, part in enumerate(parts, 1):
        head = f"Part {p_idx} — {len(part)} lagu"
        with st.expander(head, expanded=(p_idx == 1)):
            for j, t in enumerate(part, 1):
                n = (p_idx - 1) * ui_data.PART_SIZE + j
                line = f"{n:02d}. **{t['title']}** — {t['artist']}"
                if t.get("duration"):
                    line += f" `({t['duration']})`"
                if _prefetched_urls() and not t.get("mp3_url"):
                    line += " ⚠️ tanpa link MP3"
                st.markdown(line)
            targets = [by_id[t["id"]] for t in part if t["id"] in by_id]
            if st.button(f"Download {head} → ZIP", key=f"dl_part_{p_idx}",
                         type="primary" if p_idx == 1 else "secondary",
                         disabled=not targets):
                with st.spinner("Mengunduh…"):
                    _run_ui_batch(targets, head)
                st.rerun()

    _render_ui_batch_result()


def _grid_select_state(key_set: str, ids: list[str]) -> set:
    cur = st.session_state.get(key_set, set())
    if not isinstance(cur, set):
        cur = set(cur or [])
        st.session_state[key_set] = cur
    return cur


# Rows rendered per page in the track lists (#5). 100 rows in one go makes
# Streamlit re-render painfully slowly, so we page it.
TRACKS_PER_PAGE = 25

# Cover gallery is a separate layout (R2): square tiles, several per row.
# Streamlit's column API takes a fixed count (SpecType = int | Sequence[float])
# and cannot react to the viewport, so the gallery keeps 4 columns and the tiles
# are capped/centred in CSS instead — see .nx9-cover-tile in ui/theme.py.
COVER_COLUMNS = 4
COVERS_PER_PAGE = 20


def _pager(page_key: str, total_items: int, per_page: int = 0) -> tuple[int, int, int]:
    """Return (page_number, start_index, end_index) for a paginated list."""
    per_page = per_page or TRACKS_PER_PAGE
    pages = max(1, (total_items + per_page - 1) // per_page)
    state_key = f"page_{page_key}"
    current = int(st.session_state.get(state_key, 0))
    current = max(0, min(current, pages - 1))

    if pages > 1:
        cols = st.columns([1, 2, 1, 1])
        with cols[0]:
            if st.button("←", key=f"{state_key}_prev", disabled=current == 0,
                         use_container_width=True):
                st.session_state[state_key] = current - 1
                st.rerun()
        with cols[2]:
            if st.button("→", key=f"{state_key}_next", disabled=current >= pages - 1,
                         use_container_width=True):
                st.session_state[state_key] = current + 1
                st.rerun()
        with cols[3]:
            st.caption(f"{current + 1}/{pages}")

    st.session_state[state_key] = current
    start = current * per_page
    return current, start, min(start + per_page, total_items)


def _square_cover(url: str, size: int = 48) -> None:
    """Render a square, cropped cover thumbnail for the song list.

    ``st.image`` preserves the source aspect ratio and gives no hook for our
    CSS class, so the image is emitted as raw HTML inside ``.nx9-art-img``
    (defined in ui/theme.py). That is what actually forces a 1:1 crop — see
    test_theme.py, which asserts the class exists and is injected.
    """
    if not url:
        return
    st.markdown(
        f'<div class="nx9-art-img nx9-art-sm">'
        f'<img src="{html.escape(url, quote=True)}" alt=""></div>',
        unsafe_allow_html=True,
    )


def _render_track_row(n: int, t: dict, sel: set, by_id: dict, kind: str = "song") -> None:
    """One horizontal track row: [x] [cover] title / artist•album  dur  [Unduh].

    The vertical, Spotify-like list that replaced the old card grid (#5). This
    is for the Download **Lagu** page only — the Download Cover page uses
    :func:`_render_cover_gallery`, because artwork reads better side by side.
    """
    sel_key = f"{kind}_sel_{t['id']}"
    index_col, check_col, art_col, body_col, dur_col, btn_col = st.columns(
        [0.5, 0.6, 0.9, 5, 0.8, 1.4])

    with index_col:
        st.caption(f"{n}")
    with check_col:
        checked = st.checkbox("Pilih", key=sel_key, value=(t["id"] in sel),
                              label_visibility="collapsed")
        if checked:
            sel.add(t["id"])
        else:
            sel.discard(t["id"])
    with art_col:
        _square_cover(t.get("cover", ""), size=48)
    with body_col:
        st.markdown(f"**{t['title']}**")
        sub = t["artist"]
        if t.get("album"):
            sub += f" • {t['album']}"
        st.caption(sub)
    with dur_col:
        st.caption(t.get("duration", ""))
    with btn_col:
        label = "Unduh" if kind == "song" else "Unduh cover"
        disabled = bool(kind == "song" and _prefetched_urls() and not t.get("mp3_url"))
        if st.button(label, key=f"one_{kind}_{t['id']}", use_container_width=True,
                     disabled=disabled):
            if kind == "cover":
                _download_one_cover(t)
            else:
                _download_one_song(t, by_id)
    st.divider()


def _render_track_table(n: int, t: dict, sel: set, by_id: dict) -> None:
    """One row of the Spotify-style table used by the Download Lagu page.

    Columns: # / cover / title + artist / album / duration / [Pilih] [Unduh]

    Kept as a separate function rather than reusing ``_render_track_row`` so the
    legacy list used elsewhere stays untouched.

    Layout: the five presentational columns are one CSS-grid HTML block, and the
    two widgets live in a neighbouring column. Streamlit widgets cannot be
    rendered inside ``st.markdown``, so the row is split 2 ways instead of 7 —
    which also cuts Streamlit's 16px inter-column gap from six per row to one.
    """
# vertical_alignment matters: the grid row is 66px tall (48px artwork + padding)
    # while the button is only 40px. Without centering, Streamlit pins the actions
    # to the top of the row and they float ~13px above the cover.
    left, actions = st.columns([10, 1.4], vertical_alignment="center")

    with left:
        st.markdown(_track_row_html(n, t), unsafe_allow_html=True)
    with actions:
        _render_row_actions(t, sel, by_id)


def _track_row_html(n: int, t: dict) -> str:
    """One table row as a single CSS-grid HTML block.

    Only presentational data lives here (number, artwork, title/artist, album,
    duration). The checkbox and the Unduh button are Streamlit widgets and must
    be rendered outside ``st.markdown``, which is why the caller splits the row
    into a [grid | actions] pair.

    Everything interpolated is escaped: track metadata comes from a remote
    playlist and is not trusted markup.
    """
    cover = t.get("cover") or ""
    art = (
        f'<img src="{html.escape(cover, quote=True)}" alt="">'
        if cover else ""
    )
    return (
        '<div class="nx9-tbl-row nx9-tbl-data">'
        f'  <div class="nx9-tbl-num">{n}</div>'
        f'  <div class="nx9-tbl-art">{art}</div>'
        '  <div class="nx9-tbl-body">'
        f'    <div class="nx9-tbl-title">{html.escape(t.get("title", ""))}</div>'
        f'    <div class="nx9-tbl-sub">{html.escape(t.get("artist", ""))}</div>'
        '  </div>'
        f'  <div class="nx9-tbl-sub nx9-tbl-album">'
        f'{html.escape(t.get("album") or "—")}</div>'
        f'  <div class="nx9-tbl-dur">{html.escape(t.get("duration", ""))}</div>'
        '</div>'
    )


def _render_row_actions(t: dict, sel: set, by_id: dict) -> None:
    """Checkbox + Unduh button, laid out side by side on one line.

    Stacking them vertically would make the actions column taller than the
    48px artwork and every row would gain dead space underneath the grid.
    """
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        checked = st.checkbox("Pilih", key=f"song_sel_{t['id']}",
                              value=(t["id"] in sel),
                              label_visibility="collapsed")
        if checked:
            sel.add(t["id"])
        else:
            sel.discard(t["id"])
        disabled = _prefetched_urls() and not t.get("mp3_url")
        if st.button("Unduh", key=f"one_song_{t['id']}",
                     disabled=disabled):
            _download_one_song(t, by_id)


def _render_table_header() -> None:
    """Column captions, aligned with :func:`_render_track_table`.

    Uses the same [grid | actions] split and the same ``grid-template-columns``
    as the rows, so every caption lands exactly on top of its column.

    The first two cells carry the same classes as the data rows on purpose: the
    narrow-screen media queries hide ``.nx9-tbl-num`` and drop the album track,
    and the caption has to lose those columns too or its labels end up at
    different x offsets than the data underneath.
    """
    left, _actions = st.columns([10, 1.4], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="nx9-tbl-row nx9-tbl-caption">'
            '<div class="nx9-tbl-num nx9-tbl-spacer"></div>'
            '<div class="nx9-tbl-art nx9-tbl-spacer"></div>'
            '<div class="nx9-tbl-head">Judul</div>'
            '<div class="nx9-tbl-head nx9-tbl-album">Album</div>'
            '<div class="nx9-tbl-head nx9-tbl-dur">Durasi</div>'
            '</div>',
            unsafe_allow_html=True)


def _download_one_song(t: dict, by_id: dict) -> None:
    """Fetch one song and offer it as an MP3 download button."""
    track = by_id.get(t["id"])
    if track is None:
        st.warning("Data lagu tidak ditemukan.")
        return
    try:
        with st.spinner(f"Mengunduh {t['title']}…"):
            data = _fetch_mp3_bytes(track)
        st.download_button(
            "Simpan MP3", data=data, file_name=f"{track.filename}.mp3",
            mime="audio/mpeg", key=f"dl_{t['id']}", use_container_width=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Gagal: {type(exc).__name__}: {exc}")


def _download_one_cover(t: dict) -> None:
    """Fetch one cover image and offer it as a download."""
    url = t.get("cover") or ""
    if not url:
        st.warning("Lagu ini tidak punya cover.")
        return
    try:
        with st.spinner(f"Mengunduh cover {t['title']}…"):
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.content
        from providers.base import _slug  # shared filename rule
        name = _slug(f"{t.get('artist','')} - {t.get('title','')}") + ".jpg"
        st.download_button("Simpan cover", data=data, file_name=name,
                           mime="image/jpeg", key=f"dlcover_{t['id']}",
                           use_container_width=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Gagal: {type(exc).__name__}: {exc}")


def page_songs() -> None:
    st.title("Download Lagu")
    view = _playlist_or_notice()
    if not view:
        return
    tracks = view["tracks"]
    st.caption(f"{len(tracks)} lagu. Centang untuk memilih, lalu unduh per lagu "
               "atau jadi satu ZIP.")

    query = st.text_input("Search lagu / artist / album…", key="song_search",
                          placeholder="mis. styles, sign of…")
    shown = ui_data.filter_tracks(tracks, query)

    sel = _grid_select_state("selected_songs", [t["id"] for t in tracks])
    by_id = _tracks_by_id()
    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("Pilih semua (hasil search)"):
            sel.update(t["id"] for t in shown)
            for t in shown:
                st.session_state[f"song_sel_{t['id']}"] = True
            st.rerun()
    with b2:
        if st.button("Bersihkan"):
            sel.clear()
            for t in tracks:
                st.session_state.pop(f"song_sel_{t['id']}", None)
            st.rerun()
    with b3:
        st.caption(f"{len(sel)} lagu dipilih • {len(shown)} tampil")

    if st.button(f"Download {len(sel)} Lagu Terpilih → ZIP", type="primary",
                 disabled=(len(sel) == 0)):
        targets = [by_id[i] for i in sel if i in by_id]
        with st.spinner("Mengunduh lagu terpilih…"):
            _run_ui_batch(targets, f"{len(targets)} lagu terpilih")
        st.rerun()

    st.divider()
    if not shown:
        st.caption("Tidak ada lagu yang cocok dengan search.")
        return

    _page, start, end = _pager("songs", len(shown))
    _render_table_header()
    for n, t in enumerate(shown[start:end], start + 1):
        _render_track_table(n, t, sel, by_id)


def page_covers() -> None:
    st.title("Download Song Cover")
    view = _playlist_or_notice()
    if not view:
        return
    tracks = view["tracks"]
    with_cover = sum(1 for t in tracks if t.get("cover"))
    loaded = st.session_state.get("covers_loaded") or 0
    cap = f" · {loaded} cover album asli sudah dimuat" if loaded else ""
    st.caption(f"{with_cover}/{len(tracks)} cover tersedia{cap}. Centang cover "
               "yang diinginkan lalu unduh jadi satu ZIP gambar.")

    query = st.text_input("Search cover / lagu / artist…", key="cover_search",
                          placeholder="mis. midnight, afterglows…")
    shown = ui_data.filter_tracks(tracks, query)
    by_id = _tracks_by_id()

    sel = _grid_select_state("selected_covers", [t["id"] for t in tracks])
    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("Pilih semua (hasil search)", key="cover_all"):
            sel.update(t["id"] for t in shown if t.get("cover"))
            for t in shown:
                if t.get("cover"):
                    st.session_state[f"cover_sel_{t['id']}"] = True
            st.rerun()
    with b2:
        if st.button("Bersihkan", key="cover_clear"):
            sel.clear()
            for t in tracks:
                st.session_state.pop(f"cover_sel_{t['id']}", None)
            st.rerun()
    with b3:
        st.caption(f"{len(sel)} cover dipilih • {len(shown)} tampil")

    if st.button(f"Download {len(sel)} Cover Terpilih → ZIP", type="primary",
                 disabled=(len(sel) == 0)):
        targets = [by_id[i] for i in sel if i in by_id]
        with st.spinner("Mengunduh cover…"):
            cleanup_batch(None, st.session_state.get("cover_zip"))
            zip_path = _build_cover_zip(targets)
        st.session_state.cover_zip = zip_path
        ok = st.session_state.get("cover_count", 0)
        if ok:
            st.success(f"{ok}/{len(targets)} cover berhasil diunduh.")
        else:
            st.warning("Tidak ada cover yang berhasil diunduh (URL mungkin kosong "
                       "atau ditolak layanan).")
        st.rerun()

    zip_path = st.session_state.get("cover_zip")
    if zip_path and Path(zip_path).exists():
        try:
            st.download_button("Download ZIP Cover", data=Path(zip_path).read_bytes(),
                               file_name=Path(zip_path).name, mime="application/zip",
                               use_container_width=True, key="cover_zip_dl")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Gagal membaca ZIP cover: {exc}")

    st.divider()
    if not shown:
        st.caption("Tidak ada cover yang cocok dengan search.")
        return

    _render_cover_gallery(shown, sel, start_page=0)


def _render_cover_gallery(rows: list, sel: set, start_page: int = 0) -> None:
    """Grid of square covers for the Download Cover page (R2).

    The Download Lagu page is a vertical list (rev #5); this one is a gallery on
    purpose — artwork reads better side by side, which is what the user asked
    for. Covers are square via the existing ``.nx9-art-img`` CSS in ui/theme.py.
    """
    _page, start, end = _pager("covers", len(rows), per_page=COVERS_PER_PAGE)
    visible = rows[start:end]

    for i in range(0, len(visible), COVER_COLUMNS):
        cols = st.columns(COVER_COLUMNS, gap="small")
        for col, t in zip(cols, visible[i:i + COVER_COLUMNS]):
            with col:
                with st.container(border=True):
                    if t.get("cover"):
                        st.markdown(
                            f'<div class="nx9-art-img">'
                            f'<img src="{html.escape(t["cover"], quote=True)}" alt="">'
                            f'</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="nx9-art-img"></div>',
                                    unsafe_allow_html=True)
                        st.caption("(tidak ada cover)")
                    st.markdown(f"**{t['title']}**")
                    st.caption(t["artist"])
                    checked = st.checkbox("Pilih", key=f"cover_sel_{t['id']}",
                                          value=(t["id"] in sel),
                                          disabled=not t.get("cover"))
                    if checked:
                        sel.add(t["id"])
                    else:
                        sel.discard(t["id"])
                    if st.button("Unduh cover", key=f"one_cover_{t['id']}",
                                 use_container_width=True,
                                 disabled=not t.get("cover")):
                        _download_one_cover(t)


def page_backup() -> None:
    st.title("Backup")
    view = _playlist_or_notice()
    if not view:
        return
    if view.get("hint"):
        st.warning(view["hint"])
    st.caption("Export metadata playlist yang sedang dimuat. Tidak mengunduh "
               "audio — hanya daftar lagu.")
    fmt = st.radio("Format backup", ["TXT", "JSON", "CSV"], horizontal=True)

    slug = "".join(ch if ch.isalnum() else "_" for ch in (view.get("title") or "playlist"))[:60]
    if fmt == "TXT":
        payload = ui_data.to_txt(view)
        mime, ext = "text/plain", "txt"
    elif fmt == "CSV":
        payload = ui_data.to_csv(view)
        mime, ext = "text/csv", "csv"
    else:
        payload = json.dumps(ui_data.to_json_obj(view), indent=2, ensure_ascii=False)
        mime, ext = "application/json", "json"

    st.code(payload, language=None)
    st.download_button(f"Unduh backup {fmt}", data=payload.encode("utf-8"),
                       file_name=f"{slug}.{ext}", mime=mime,
                       use_container_width=True, key="backup_dl")


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
        _render_track_row_legacy(idx, track)
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


# NOTE: the legacy single-page UI below has its own `_render_track_row(idx,
# track)` (line ~1149) which takes a Track, not a view dict. The modern list row
# above deliberately uses a different name so neither shadows the other.


def _render_track_row_legacy(idx: int, track: Track) -> None:
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
    """Read the MP3 for one track, whatever shape the provider returned.

    Providers are not uniform about what ``resolve_track`` hands back:

    * ``mock://...``            — the offline Demo provider (placeholder bytes).
    * **a local file path**     — YouTube/yt-dlp: the search + download + ffmpeg
      work already happened inside ``resolve_track``, so the "URL" is really a
      finished file on disk (``C:\\...\\spotify_yt_cache\\x.mp3``). Passing such
      a path to ``requests.get`` raises ``InvalidSchema``, which is why the
      Download Lagu page needs this branch.
    * an ``http(s)://`` URL     — the legacy providers (SpotiDown.co,
      SoundLoaders, SpotiDown.app) still return a real URL to fetch.
    """
    if mp3_url.startswith("mock://"):
        return _mock_mp3_bytes()

    # Local file produced by the provider. Path() can raise on Windows for
    # strings with illegal characters, so never let it kill the request.
    if _looks_like_filesystem_path(mp3_url):
        local = None
        try:
            local = Path(mp3_url)
            if local.exists() and local.is_file():
                data = local.read_bytes()
                if not data:
                    raise ServiceError(f"File audio kosong: {local}")
                return data
        except ServiceError:
            raise
        except Exception:  # noqa: BLE001
            local = None
        # It claimed to be a file path but we cannot read it. Say so plainly
        # instead of letting requests raise InvalidSchema on a bare path.
        raise ServiceError(
            f"File audio tidak bisa dibaca: {mp3_url}",
            details=("provider mengembalikan path lokal, tapi file-nya hilang "
                     "atau tidak terbaca"),
        )

    # Legacy providers: a genuine URL.
    resp = requests.get(mp3_url, timeout=60, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _looks_like_filesystem_path(value: str) -> bool:
    """True for something that is meant to be a file path, not an HTTP URL."""
    if not value or "://" in value:
        return False
    return bool(re.match(r"^[A-Za-z]:[\\/]|^[\\/]{1,2}", value))


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
