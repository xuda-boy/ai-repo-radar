from __future__ import annotations

import os
from pathlib import Path


def local_state_dir() -> Path:
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "AIRepoRadar"
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]) / "ai-repo-radar"
    return Path.home() / ".local" / "state" / "ai-repo-radar"


def database_path(value: Path | None = None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    return (local_state_dir() / "radar.sqlite3").resolve()
