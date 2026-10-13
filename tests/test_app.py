"""End-to-end Streamlit AppTest over the current 5-page UI.

Exercises the real flow: choose the Demo backend -> load a playlist -> walk all
five pages -> search/select -> run a batch -> get a ZIP. No network and no
Chrome: the Demo provider generates placeholder audio bytes locally.

Also pins the Home header behaviour: it must show the PLAYLIST artwork, not the
first track's album cover (which is someone else's image once every track has
its own art).

Run:  python tests/test_app.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

import app as appmod  # noqa: E402

DEMO_URL = "https://open.spotify.com/playlist/0jeZAndC8kr76ROevxI5zM"
PAGES = ["home", "playlist", "songs", "covers", "backup"]

# Playlist artwork (prefix ab67706c...) vs per-track album artwork (ab67616d...).
PLAYLIST_COVER = ("https://image-cdn-ak.spotifycdn.com/image/"
                  "ab67706c0000da84d1a91a9ff0c47ed829f39874")
ALBUM_COVER = ("https://i.scdn.co/image/"
               "ab67616d0000b273aff4aef671b2510be7c115b3")


def _button(at, needle: str):
    hits = [b for b in at.button if needle in b.label]
    return hits[0] if hits else None


def _markup(at) -> str:
    """Rendered markdown, minus the injected NX9 stylesheet.

    inject_theme() pushes the whole CSS as one markdown element, so a naive
    join() would find any class name mentioned in the stylesheet.
    """
    return "\n".join(
        getattr(m, "value", "") for m in at.markdown
        if "<style>" not in (getattr(m, "value", "") or "")
    )


def main():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    # --- default backend is YouTube
    assert at.session_state["backend"] == "youtube", at.session_state["backend"]

    # --- pick the Demo backend so nothing touches the network
    at.sidebar.selectbox[0].select("Demo (Mock, offline)")
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["backend"] == "mock"

    # --- load a playlist from Home
    at.text_input(key="home_url_input").set_value(DEMO_URL)
    at.run()
    load = _button(at, "Load Playlist")
    assert load is not None, "Load Playlist button missing"
    load.click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    view = at.session_state["playlist_view"]
    assert view and len(view["tracks"]) > 0, "no tracks loaded"
    assert view["url"] == DEMO_URL, view["url"]
    n = len(view["tracks"])
    print(f"OK: playlist loaded ({n} tracks)")

    # --- every page renders
    for page in PAGES:
        at.sidebar.radio[0].set_value(page)
        at.run()
        assert not at.exception, [page] + [str(e.value) for e in at.exception]
    print("OK: all 5 pages render")

    # --- songs page: search narrows the grid, select-all works
    at.sidebar.radio[0].set_value("songs")
    at.run()
    total_boxes = len([c for c in at.checkbox if c.key.startswith("song_sel_")])
    assert total_boxes == n, f"expected {n} cards, got {total_boxes}"

    first_title = view["tracks"][0]["title"]
    at.text_input(key="song_search").set_value(first_title.split()[0])
    at.run()
    filtered = len([c for c in at.checkbox if c.key.startswith("song_sel_")])
    assert 0 < filtered <= n, filtered
    print(f"OK: search narrows {n} -> {filtered} cards")

    at.text_input(key="song_search").set_value("")
    at.run()
    _button(at, "Pilih semua").click()
    at.run()
    assert len(at.session_state["selected_songs"]) == n, \
        len(at.session_state["selected_songs"])
    print(f"OK: select-all selected {n} tracks")

    # --- covers page: gallery layout (R2), search still narrows
    at.sidebar.radio[0].set_value("covers")
    at.run()
    covers = len([c for c in at.checkbox if c.key.startswith("cover_sel_")])
    assert 0 < covers <= n, covers

    # R2 regression: the cover page must be a GALLERY (square tiles, several per
    # row), not the vertical list used by the Download Lagu page.
    gallery_buttons = [b for b in at.button if b.label == "Unduh cover"]
    assert gallery_buttons, "cover gallery buttons missing"
    per_row = appmod.COVER_COLUMNS
    assert per_row > 1, f"gallery must place {per_row} covers per row"
    # Each tile carries the square-art CSS class, which is what makes it 1:1.
    markup = _markup(at)
    assert "nx9-art-img" in markup, "cover tiles are not using the square-art class"
    # ...and it must NOT be the per-row list renderer.
    assert not [b for b in at.button if b.label == "Unduh"], \
        "cover page fell back to the song list renderer"
    print(f"OK: cover gallery - {covers} tiles, {per_row} per row, square CSS")

    at.text_input(key="cover_search").set_value(first_title.split()[0])
    at.run()
    covers_filtered = len([c for c in at.checkbox if c.key.startswith("cover_sel_")])
    assert 0 < covers_filtered <= covers, covers_filtered
    print(f"OK: cover search -> {covers_filtered} tiles")

    # --- songs page must STILL be a vertical list (rev #5 must not regress)
    at.sidebar.radio[0].set_value("songs")
    at.run()
    song_buttons = [b for b in at.button if b.label == "Unduh"]
    assert song_buttons, "song list download buttons missing"
    print("OK: song page still a list with per-song buttons")

    # --- backup page: all three formats render
    at.sidebar.radio[0].set_value("backup")
    at.run()
    for fmt in ("TXT", "JSON", "CSV"):
        at.radio[0].set_value(fmt)
        at.run()
        assert not at.exception, [fmt] + [str(e.value) for e in at.exception]
        labels = [d.label for d in at.get("download_button")]
        assert any(fmt in lbl for lbl in labels), (fmt, labels)
    print("OK: backup TXT/JSON/CSV all downloadable")

    # --- playlist page: batch -> ZIP
    at.sidebar.radio[0].set_value("playlist")
    at.run()
    dl = _button(at, "Download Part 1")
    assert dl is not None, "batch button missing"
    dl.click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]

    result = at.session_state["ui_batch"]
    assert result is not None, "no BatchResult stored"
    assert result.ok == n and result.failed == 0, result.summary
    assert result.zip_path is not None and result.zip_path.exists(), "no zip produced"

    import zipfile

    with zipfile.ZipFile(result.zip_path) as zf:
        names = zf.namelist()
    assert len(names) == n, f"zip has {len(names)} entries, expected {n}"
    print(f"OK: batch {result.summary}, zip has {len(names)} entries")

    assert any(d.label == "Download ZIP" for d in at.get("download_button")), \
        "ZIP download button missing"
    print("OK: Download ZIP button present")

    result.zip_path.unlink(missing_ok=True)
    print("ALL UI TESTS PASSED")


# --------------------------------------------------------------------------
# Home header artwork
# --------------------------------------------------------------------------
def _load_home_with(provider_cover: str):
    """Load the Home page with a stub provider carrying `last_playlist_cover`."""
    import core.orchestrator as orch
    from providers.base import ProviderId, ResolveResult, Track
    from providers.mock import MockProvider

    class Stub(MockProvider):
        prefetched_urls = False

        def __init__(self):
            super().__init__()
            self.name = "fake"
            self.provider = ProviderId.YOUTUBE if provider_cover else ProviderId.MOCK

        def load_tracks(self, url, cftoken=""):
            self.last_owner = "David-Atha"
            self.last_playlist_cover = provider_cover
            tracks = [Track(data=f"t{i}", track_token=f"t{i}", title=f"Lagu {i}",
                            artist="Artis", album="Album",
                            thumbnail=ALBUM_COVER, mp3_url=None, duration_ms=200_000)
                      for i in range(1, 6)]
            return ResolveResult(title="Dupe", source_url=url, tracks=tracks)

    original = orch.make_provider
    orch.make_provider = lambda kind: Stub()
    try:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
        at.run()
        at.text_input(key="home_url_input").set_value(DEMO_URL)
        at.run()
        _button(at, "Load Playlist").click()
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        return at
    finally:
        orch.make_provider = original


def test_header_uses_the_playlist_cover():
    """The Home header must show the PLAYLIST artwork, not the first song's
    album cover.

    Regression: once every track got its own album art (R1), taking the header
    image from the track list silently started showing someone else's album.
    """
    at = _load_home_with(PLAYLIST_COVER)
    view = at.session_state["playlist_view"]
    assert view.get("playlist_cover") == PLAYLIST_COVER, \
        f"cover playlist tidak tersimpan: {view.get('playlist_cover')!r}"
    assert view.get("owner") == "David-Atha", view.get("owner")

    markup = _markup(at)
    assert PLAYLIST_COVER in markup, "header tidak memakai cover playlist"
    assert ALBUM_COVER not in markup, \
        "header masih memakai cover album lagu pertama"
    # Square styling must survive.
    assert "nx9-art-img nx9-art-lg" in markup, "CSS kotak pada header hilang"

    # R1 must be untouched: the track list keeps per-track album art.
    at.sidebar.radio[0].set_value("covers")
    at.run()
    assert ALBUM_COVER in _markup(at), "cover album di daftar ikut berubah"
    print("OK: header = cover playlist, daftar = cover album (persegi, CSS utuh)")


def test_header_falls_back_when_no_playlist_cover():
    """Legacy providers set no playlist cover - the header must still show art."""
    at = _load_home_with("")
    view = at.session_state["playlist_view"]
    assert not view.get("playlist_cover"), "legacy provider tidak seharusnya punya"
    assert ALBUM_COVER in _markup(at), "fallback cover album hilang"
    print("OK: fallback ke cover lagu pertama saat provider tidak punya cover playlist")


def test_playlist_cover_prefix_is_not_upgraded():
    """Playlist art uses ab67706c...; running it through upgrade_cover_url()
    would produce a 404, so it must stay untouched."""
    from providers.base import upgrade_cover_url

    assert upgrade_cover_url(PLAYLIST_COVER) == PLAYLIST_COVER
    assert "ab67706" in PLAYLIST_COVER


def test_songs_page_is_a_column_table():
    """Download Lagu must render as a Spotify-style COLUMN table.

    Layout: [#] [cover] title/artist | album | duration | [Unduh]
    Regression guard: it must not fall back to the plain list renderer, and the
    Cover page must stay a gallery.
    """
    import core.orchestrator as orch
    from providers.base import ProviderId, ResolveResult, Track
    from providers.mock import MockProvider

    LONG_TITLE = "A Really Very Extremely Long Song Title That Should Be Cut Off"
    LONG_ALBUM = "An Extremely Long Album Name That Also Needs Truncation"

    class Stub(MockProvider):
        prefetched_urls = False

        def __init__(self):
            super().__init__()
            self.name = "fake"
            self.provider = ProviderId.YOUTUBE

        def load_tracks(self, url, cftoken=""):
            self.last_owner = "Tester"
            self.last_playlist_cover = PLAYLIST_COVER
            tracks = [
                Track(data="t1", track_token="t1", title=LONG_TITLE,
                      artist="Some Artist With A Long Name", album=LONG_ALBUM,
                      thumbnail=ALBUM_COVER, mp3_url=None, duration_ms=339_000),
                Track(data="t2", track_token="t2", title="Short",
                      artist="A", album="B", thumbnail=ALBUM_COVER,
                      mp3_url=None, duration_ms=200_000),
            ]
            return ResolveResult(title="Table", source_url=url, tracks=tracks)

    original = orch.make_provider
    orch.make_provider = lambda kind: Stub()
    try:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
        at.run()
        at.text_input(key="home_url_input").set_value(DEMO_URL)
        at.run()
        _button(at, "Load Playlist").click()
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]

        at.sidebar.radio[0].set_value("songs")
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]

        markup = _markup(at)

        # --- one CSS-grid block per row, with the five columns
        rows = [m.value for m in at.markdown
                if 'class="nx9-tbl-row nx9-tbl-data"' in (m.value or "")]
        assert len(rows) == 2, f"harus ada 2 baris grid, ada {len(rows)}"
        # Every row must be a single grid block carrying the identical class
        # list — if the template differed between rows the columns would drift.
        for r in rows:
            assert r.count('class="nx9-tbl-row nx9-tbl-data"') == 1, \
                "baris harus satu blok grid"
            for cls in ("nx9-tbl-num", "nx9-tbl-art", "nx9-tbl-body",
                        "nx9-tbl-title", "nx9-tbl-dur"):
                assert_contains(r, cls, f"kolom {cls} hilang di baris")

        assert_contains(markup, LONG_TITLE, "judul lagu tidak ter-render")
        assert_contains(markup, LONG_ALBUM, "album tidak ter-render")
        assert_contains(markup, "5:39", "durasi M:SS tidak terformat")

        # --- column captions, on the same grid
        assert_contains(markup, "nx9-tbl-caption", "baris header kolom hilang")
        assert_contains(markup, "nx9-tbl-head", "label kolom hilang")

        # --- checkbox + per-row download must still work
        assert [c for c in at.checkbox if c.key.startswith("song_sel_")], \
            "checkbox hilang"
        assert [b for b in at.button if b.label == "Unduh"], \
            "tombol Unduh per baris hilang"

        # --- NOT the old list renderer
        assert "nx9-track-title" not in markup, \
            "halaman lagu masih memakai renderer list lama"

        # --- album cell must be its own column, not glued onto the artist line
        assert "•" not in markup, "album masih digabung ke baris artist"

        # --- the Cover page must remain a gallery
        at.sidebar.radio[0].set_value("covers")
        at.run()
        gallery = _markup(at)
        assert [b for b in at.button if b.label == "Unduh cover"], \
            "halaman cover bukan galeri lagi"
        assert not any("nx9-cell-title" in (m.value or "") and "<style>" not in (m.value or "")
                       for m in at.markdown), \
            "halaman cover ikut jadi tabel"
    finally:
        orch.make_provider = original
    print("OK: Download Lagu = tabel 5 kolom, Download Cover tetap galeri")


def assert_contains(haystack: str, needle: str, message: str) -> None:
    if needle not in haystack:
        raise AssertionError(f"{message} (cari: {needle!r})")


def test_table_css_prevents_wrapping():
    """Long titles must ellipsis, not wrap — that is what keeps rows aligned.

    Also guards the two rules that silently break CSS grid ellipsis, and the
    alignment arithmetic that Streamlit's own column margin would otherwise
    undo.
    """
    from ui import theme

    css = theme.NX9_CSS

    for cls in (".nx9-tbl-title", ".nx9-tbl-sub"):
        block = css.split(cls, 1)[1].split("}", 1)[0]
        assert "white-space: nowrap" in block, f"{cls} harus no-wrap"
        assert "text-overflow: ellipsis" in block, f"{cls} harus ellipsis"

    # minmax(0, ...) on the flexible tracks and min-width: 0 on the body are
    # load-bearing: without them the grid item refuses to shrink and the
    # ellipsis never fires.
    assert "minmax(0, 1fr)" in css, "kolom judul harus minmax(0, 1fr)"
    body = css.split(".nx9-tbl-body {", 1)[1].split("}", 1)[0]
    assert "min-width: 0" in body, ".nx9-tbl-body harus min-width: 0"

    # Streamlit inserts 16px between columns; the table must not inherit it.
    # Scoped with :has() — as a global rule it also flattened the cover gallery
    # and the button rows on every other page.
    assert ".stHorizontalBlock:has(.nx9-tbl-row) {" in css
    assert "gap: 0 !important" in css
    assert "\n.stHorizontalBlock {\n" not in css, \
        "gap:0 global akan merusak galeri & baris tombol halaman lain"

    # The actions column is nudged down so the button shares a baseline with the
    # cover, and pinned to a fixed width. Both are easy to drop: without the
    # margin the button floats above the artwork, and without min-width
    # Streamlit's narrow-screen `calc(100% - 24px)` swallows the row (measured:
    # actions 395px inside a 419px block, title track collapsed to 0).
    assert "margin-top: calc(4px + clamp(0.5rem, 1vw, 0.75rem))" in css, \
        "penyelarasan vertikal tombol Unduh hilang"
    assert "min-width: 6rem !important" in css, \
        "kolom aksi harus dikunci lebarnya"
    assert "min-width: 0 !important" in css, \
        "kolom grid harus boleh menyusut"

    # A missing cover must degrade to a grey tile, never a collapsed box.
    art = css.split(".nx9-tbl-art {", 1)[1].split("}", 1)[0]
    assert "aspect-ratio" in art and "background" in art, \
        "cover kosong harus tetap kotak abu-abu"

    # A nested :has() makes the selector invalid and the browser drops the rule
    # with no error at all, so keep the scoping to a single flat :has().
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for _, selector in re.findall(r"(^|\})([^{}@]+)\{", stripped, re.M):
        if selector.count(":has(") > 1:
            raise AssertionError(
                f":has() bersarang, rule akan dibuang diam-diam: {selector.strip()}")

    # Sanity: the scoping selectors really are there.
    assert css.count(".stHorizontalBlock:has(.nx9-tbl-data)") >= 1, \
        "scope :has() untuk baris tabel hilang"

    print("OK: CSS tabel — grid, ellipsis, no-gap, baseline tombol, cover fallback")


def test_layout_is_fluid_not_fixed_px():
    """The table and page width must scale with the viewport.

    Regression guard for "looks fine on my monitor only": every table track and
    the page container have to be clamp()/vw based, and there must be enough
    breakpoints to shed columns before the title gets crushed.
    """
    from ui import theme

    css = theme.NX9_CSS
    # Comments inside the grid template document the px targets (e.g.
    # "28 -> 32px"); strip them before scanning so they are not mistaken for
    # actual fixed sizing.
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    row = bare.split(".nx9-tbl-row {", 1)[1].split("}", 1)[0]

    # No bare px inside the grid template — that is the whole point. Scope the
    # scan to the declaration itself; border-radius/border legitimately use px.
    template = row.split("grid-template-columns:", 1)[1].split(";", 1)[0]
    for px in re.findall(r"(\d+)px", template):
        raise AssertionError(
            f"grid template masih pakai {px}px fixed; harus clamp()/rem")
    assert template.count("clamp(") >= 4, \
        "sebagian besar track harus clamp()"
    assert "minmax(0, 1fr)" in template, "kolom judul harus tetap fluid"

    # Spacing follows a 4/8px rhythm, not arbitrary numbers.
    assert "gap: clamp(" in row, "gap harus clamp()"
    assert "padding: clamp(" in row, "padding harus clamp()"
    for odd in ("9px", "10px", "13px", "14px"):
        assert odd not in row, f"nilai ganjil {odd} masih ada di baris tabel"

    # Page container must be fluid with an upper bound, not Streamlit's 736px.
    assert "max-width: min(1600px, 94vw)" in bare, \
        "lebar halaman harus fluid dengan batas atas"
    assert "736px" not in bare, "batas 736px bawaan masih ada di override"

    # Enough breakpoints: wide cap, tablet (drop album), phone (drop number),
    # plus a phone breakpoint for the playlist header card.
    for bp in ("min-width: 1700px", "max-width: 1100px", "max-width: 640px"):
        assert f"@media ({bp})" in css, f"breakpoint {bp} hilang"
    assert css.count("@media") >= 4, "media query terlalu sedikit"

    # Every breakpoint that hides a cell must also drop its grid track,
    # otherwise the hidden cell leaves a hole in the row.
    for mq in re.findall(r"@media[^{]*\{(.*?)\n\}\s*$", css, re.S | re.M):
        if ".nx9-tbl-album" in mq and "display: none" in mq:
            assert "grid-template-columns" in mq, \
                "album disembunyikan tapi track grid tidak dikurangi"
    phone = css.split("max-width: 640px", 1)[1]
    assert ".nx9-tbl-num" in phone and "display: none" in phone, \
        "nomor harus disembunyikan di layar sempit"
    assert "grid-template-columns" in phone, \
        "nomor disembunyikan tapi track grid tidak dikurangi"

    # Caption placeholders must keep the same classes as the data cells so they
    # vanish in step; otherwise the headings drift off the columns.
    assert ".nx9-tbl-spacer" in css, "sel kosong header kolom harus ada"
    spacer_art = css.split(".nx9-tbl-spacer.nx9-tbl-art {", 1)[1].split("}", 1)[0]
    assert "height: 0" in spacer_art, \
        "placeholder harus berukuran 0 tinggi"

    print("OK: layout fluid — clamp tracks, 4/8px rhythm, 3 breakpoints")


if __name__ == "__main__":
    main()
    test_header_uses_the_playlist_cover()
    test_header_falls_back_when_no_playlist_cover()
    test_playlist_cover_prefix_is_not_upgraded()
    test_songs_page_is_a_column_table()
    test_table_css_prevents_wrapping()
    test_layout_is_fluid_not_fixed_px()