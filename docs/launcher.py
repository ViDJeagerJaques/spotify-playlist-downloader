"""Entry point for the desktop build: opens app.py in a native window.

Three things here are load-bearing, each one learned from a build that failed
without it:

* ``freeze_support()`` plus the ``__main__`` guard. On Windows a frozen
  Streamlit app re-spawns its own process to start the server; without the
  guard the child runs during the parent's bootstrap and Streamlit aborts with
  "An attempt has been made to start a new process before the current process
  has finished its bootstrapping phase". The build produces a .exe that starts a
  server but never shows a window.

* Building **this file**, not ``app.py``. Running ``pyinstaller app.py`` executes
  app.py as a plain script, which prints "missing ScriptRunContext! running in
  bare mode" and exits — no server, no UI. Use
  ``streamlit-desktop-app build launcher.py`` (see ``build_exe.bat``).

* ``ast.parse()`` runs over the target during the build, so a UTF-8 BOM at the
  top of ``app.py`` fails the build outright. The BOM has been removed and
  ``.gitattributes`` keeps it from coming back.

The import of ``streamlit_desktop_app`` is deliberately inside ``main()``: it is
a build-time dependency, not a runtime one, and importing it at module scope
would break ``python launcher.py`` from a plain source checkout.
"""
import sys
from multiprocessing import freeze_support
from pathlib import Path

TITLE = "Spotify Playlist Downloader"

# Matches the fluid layout: the track table needs room for its columns, and
# 1280x860 is comfortable on a 1366x768 laptop without maximising.
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 860


def _running_under_streamlit() -> bool:
    """True when this file is being executed as a Streamlit *script*.

    ``streamlit-desktop-app build`` wraps the target in a generated launcher and
    then serves **this file** with ``streamlit run``. Streamlit executes scripts
    with ``__name__ == "__main__"``, so the guard below would fire, try to open a
    second window, and fail to find ``app.py`` in the frozen temp dir -- printing
    a confusing "not found" line on every launch.

    The script-run context only exists while Streamlit is executing a script, so
    it is a reliable way to tell "I am the UI" from "I am the desktop shell".
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:  # noqa: BLE001 - old/absent Streamlit layout
        return False
    try:
        return get_script_run_ctx() is not None
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    if _running_under_streamlit():
        return 0

    try:
        from streamlit_desktop_app import start_desktop_app
    except ImportError:
        print(
            "streamlit-desktop-app tidak terpasang.\n"
            "Untuk menjalankan dari source:  .venv\\Scripts\\python -m streamlit run app.py\n"
            "Untuk membuat .exe             :  build_exe.bat",
            file=sys.stderr,
        )
        return 2

    # resolve().parent so app.py is found whether this runs from the source tree
    # or from inside the frozen executable.
    app = Path(__file__).resolve().parent / "app.py"
    if not app.exists():
        print(f"Tidak menemukan {app}", file=sys.stderr)
        return 2

    start_desktop_app(str(app), title=TITLE, width=WINDOW_WIDTH,
                      height=WINDOW_HEIGHT)
    return 0


if __name__ == "__main__":
    # Only the desktop shell wants the multiprocessing bootstrap. When Streamlit
    # is the one running this file, freeze_support() would be pointless work in
    # the middle of a script execution.
    if not _running_under_streamlit():
        freeze_support()
    sys.exit(main())
