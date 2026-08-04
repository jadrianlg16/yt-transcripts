from __future__ import annotations

import os
from pathlib import Path


DATA_DIR_ENV = "YT_TRANSCRIPTS_DATA_DIR"


def data_directory() -> Path:
    """Return the runtime data directory without forcing it to be absolute."""
    configured = os.getenv(DATA_DIR_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path(".")


def data_path(file_name: str | Path) -> Path:
    """Resolve a runtime file beneath the configured data directory."""
    path = Path(file_name)
    return path if path.is_absolute() else data_directory() / path
