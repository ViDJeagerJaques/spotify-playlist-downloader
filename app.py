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

# ---------------------------------------------------------------- constants
PROVIDER_CHOICES = {
    ProviderId.SOUNDLOADERS.value: "SoundLoaders (utama / primary)",
    ProviderId.SPOTIDOWN.value: "SpotiDown (cadangan / fallback)",
    ProviderId.MOCK.value: "Demo (Mock, offline)",
}
DEMO_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

TURNSTILE_SNIPPET = """// SoundLoaders - run in the browser console on https://soundloaders.app/
(async () => {
  const form = document.getElementById('spotifyForm');
  const input = document.getElementById('trackInput');
  if (form && input && !input.value) input.value = 'https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC';
  if (window.turnstile && turnstile.reset) turnstile.reset();
  const token = await new Promise((resolve) => {
    const poll = setInterval(() => {
      const v = document.querySelector("input[name='cf-turnstile-response']")?.value;
      if (v) { clearInterval(poll); resolve(v); }
    }, 250);
    setTimeout(() => { clearInterval(poll); resolve(''); }, 20000);
  });
  console.log('%cSOUNDLOADERS_TOKEN', 'color:green;font-weight:bold', token);
  if (token && form) form.requestSubmit();
  else console.error('Turnstile produced no token - complete the widget then retry.');
})();"""

RECAPTCHA_SNIPPET = """// SpotiDown - run in the browser console on https://spotidown.app/
(async () => {
  await new Promise(r => { if (window.grecaptcha) r(); else setTimeout(r, 1500); });
  try {
    const token = await window.grecaptcha.execute(
      '6LcXkaUqAAAAAGvO0z9Mg54lpG22HE4gkl3XYFTK', { action: 'submit' });
    console.log('%cSPOTIDOWN_TOKEN', 'color:blue;font-weight:bold', token);
  } catch (e) { console.error('reCAPTCHA execute failed:', e); }
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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _now() -> str:
    return time.strftime("%H:%M:%S")


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

        token = st.text_input(
            L("sidebar.captcha"),
            value=st.session_state.captcha_token,
            placeholder="paste token here...",
            help=L("sidebar.captcha_help"),
        )
        st.session_state.captcha_token = token
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


# -------------------------------------------------------------------- main
def main() -> None:
    st.set_page_config(page_title="Spotify Playlist Downloader", page_icon=":musical_note:",
                       layout="centered")
    init_state()
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731

    sidebar()

    st.title(L("app_title"))
    st.caption(L("tagline"))

    with st.form("url_form"):
        url = st.text_input(
            L("main.url_label"),
            placeholder=L("main.url_placeholder"),
            label_visibility="collapsed",
            key="spotify_url_input",
        )
        submitted = st.form_submit_button(L("main.btn_process"), type="primary")

    if submitted:
        handle_process(url)

    if st.session_state.tracks:
        show_results()
    show_legal(lang)


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

    provider = make_provider(backend)
    try:
        with st.spinner(i18n.tr(st.session_state.lang, "main.processing", provider=provider.name)):
            result = provider.load_tracks(url, cftoken=st.session_state.captcha_token)

        st.session_state.tracks = result.tracks
        st.session_state.source = result.source_url
        st.session_state.per_track = {}

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

    provider = make_provider(st.session_state.backend)
    entry = {"state": TrackState.PROCESSING.value}
    st.session_state.per_track[str(idx)] = entry
    try:
        with st.spinner(i18n.tr(st.session_state.lang, "main.processing", provider=provider.name)):
            mp3_url = provider.resolve_track(track, cftoken=st.session_state.captcha_token)
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
    provider = make_provider(st.session_state.backend)

    bar = st.progress(0.0, text="")
    status = st.empty()

    def progress(i, state, outcome, message):
        frac = (i + 1) / len(tracks) if tracks else 1.0
        bar.progress(frac, text=L("main.status_" + state.value))
        status.caption(f"[{i + 1}/{len(tracks)}] {outcome.title or ''} - {message}")

    try:
        orch = BatchOrchestrator(provider, mode=mode)
        result = orch.run(tracks, cftoken=st.session_state.captcha_token, progress=progress)
        st.session_state.batch = result
        _show_batch_result(result, status)
    except Exception as exc:
        render_errors(exc)


def _show_batch_result(result: BatchResult, status_el) -> None:
    lang = st.session_state.lang
    L = lambda k, **fmt: i18n.tr(lang, k, **fmt)  # noqa: E731
    status_el.success(f"**{L('main.batch_done')}** {result.summary}")

    ready = [o for o in result.outcomes if o.state == TrackState.READY]
    failed = [o for o in result.outcomes if o.state == TrackState.FAILED]

    if failed:
        with st.expander(L("main.batch_failed_list", n=len(failed))):
            for o in failed:
                st.markdown(f"- {o.title or o.index}: {o.error}")

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
