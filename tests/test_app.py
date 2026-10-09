"""End-to-end Streamlit AppTest over the current 5-page UI.

Exercises the real flow: choose the Demo backend -> load a playlist -> walk all
five pages -> search/select -> run a batch -> get a ZIP. No network and no
Chrome: the Demo provider generates placeholder audio bytes locally.

Run:  python tests/test_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

DEMO_URL = "https://open.spotify.com/playlist/0jeZAndC8kr76ROevxI5zM"
PAGES = ["home", "playlist", "songs", "covers", "backup"]


def _button(at, needle: str):
    hits = [b for b in at.button if needle in b.label]
    return hits[0] if hits else None


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

    # --- covers page: search works
    at.sidebar.radio[0].set_value("covers")
    at.run()
    at.text_input(key="cover_search").set_value(first_title.split()[0])
    at.run()
    covers = len([c for c in at.checkbox if c.key.startswith("cover_sel_")])
    assert 0 < covers <= n, covers
    print(f"OK: cover search -> {covers} cards")

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


if __name__ == "__main__":
    main()