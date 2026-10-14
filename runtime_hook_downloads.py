"""PyInstaller runtime hook: let the desktop window actually download files.

Why this exists
---------------
The whole app is built around ``st.download_button`` -- MP3s, the batch ZIP, cover
art, the TXT/JSON/CSV backup. In the frozen build those controls run inside
pywebview, and pywebview **silently cancels every download** unless it is told
otherwise:

    webview/__init__.py
        settings = { ... 'ALLOW_DOWNLOADS': False, ... }        # the default

    webview/platforms/edgechromium.py
        def on_download_starting(self, sender, args):
            if not webview_settings['ALLOW_DOWNLOADS']:
                args.Cancel = True
                return
            dialog = WinForms.SaveFileDialog()
            ...
            dialog.ShowDialog(self.form)

With the default that first branch returns immediately: no dialog, no file, and
no error anywhere. Every download button in the app becomes decorative --
clickable, and apparently broken, with nothing to explain why. Turning the
setting on is what makes the ``SaveFileDialog`` run instead, which is the
``#32770`` window the user clicks.

Why a runtime hook and not something in app.py
-----------------------------------------------
The setting has to be applied in the process that *opens the window*. PyInstaller
runs its runtime hooks in that bootstrap process before the entry script, while
``app.py`` executes in the child process that serves Streamlit -- a child cannot
change the parent's already-initialised webview settings. A runtime hook is the
only place that reliably runs early enough.

It also cannot go in a normal import: by the time ``webview`` is first touched,
the default may already have been read.

Kept defensive on purpose. A failure here must never stop the app from starting,
so everything is wrapped and the exception is swallowed.
"""

import sys

try:
    if getattr(sys, "frozen", False):
        import webview

        # Runs from source too when someone imports this file directly, which is
        # harmless: it only flips a pywebview setting.
        webview.settings["ALLOW_DOWNLOADS"] = True
except Exception:  # noqa: BLE001 - never break startup over an optional setting
    pass