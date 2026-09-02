"""Streamlit AppTest end-to-end over the Demo (Mock) provider.

Proves the whole UI wiring works: submit URL -> track list rendered ->
single resolve -> batch run -> ZIP produced. No network involved.

Run:  python tests/test_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402
from core.cleanup import cleanup_batch  # noqa: E402


def _proc_button(at):
    hits = [b for b in at.button if "Proses" in b.label or "Process" in b.label]
    return hits[0] if hits else None


def _batch_button(at):
    hits = [b for b in at.button if ("Download All" in b.label or "Download Semua" in b.label)]
    return hits[0] if hits else None


def main():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    assert len(at.exception) == 0, at.exception

    # 1) choose the Mock backend in the sidebar
    at.sidebar.selectbox[0].select("Demo (Mock, offline)")
    at.run()
    assert at.session_state["backend"] == "mock"
    assert len(at.exception) == 0, at.exception

    # 2) process with an empty URL -> mock generates a demo playlist
    proc = _proc_button(at)
    assert proc is not None
    proc.click()
    at.run()
    assert len(at.exception) == 0, [str(e.value) for e in at.exception]
    tracks = at.session_state["tracks"]
    assert len(tracks) > 0, "no tracks loaded"

    # 3) per-track download (first visible Download MP3 button)
    dl = [b for b in at.button if b.label == "Download MP3"]
    assert dl, "per-track Download MP3 button missing"
    dl[0].click()
    at.run()
    assert len(at.exception) == 0, at.exception
    per = at.session_state["per_track"]
    assert "0" in per and per["0"].get("state") == "ready", f"per-track bad: {per}"

    # 4) batch -> ZIP (mock returns bytes for every track)
    batch = _batch_button(at)
    assert batch is not None
    batch.click()
    at.run()
    assert len(at.exception) == 0, at.exception
    br = at.session_state["batch"]
    assert br is not None, "no BatchResult stored"
    assert br.ok == len(tracks) and br.failed == 0, br.summary
    assert br.zip_path is not None and br.zip_path.exists(), "no zip produced"

    # 5) verify zip contains an entry per track, then clean up
    import zipfile

    with zipfile.ZipFile(br.zip_path) as zf:
        assert len(zf.namelist()) == len(tracks), zf.namelist()
    cleanup_batch(None, br.zip_path)
    print(f"OK: {len(tracks)} tracks, batch ok={br.ok}, zip={len(zf.namelist())} entries")


if __name__ == "__main__":
    main()
