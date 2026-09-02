"""Remove the temp folder / ZIP created for a finished batch."""
from __future__ import annotations

import shutil
from pathlib import Path


def cleanup_batch(temp_dir, zip_path):
    for p in (temp_dir, zip_path):
        if not p:
            continue
        try:
            path = Path(p)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except Exception:
            pass
