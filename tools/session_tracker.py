from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _looks_like_project_root(path: Path) -> bool:
    return (path / ".sisyphus").exists() and (path / ".galaxy").exists()


def detect_repo_root() -> Path:
    cwd = Path.cwd()
    if _looks_like_project_root(cwd):
        return cwd

    here = Path(__file__)
    for parent in [here.parent, *here.parents]:
        if _looks_like_project_root(parent):
            return parent

    if (cwd / ".sisyphus").exists():
        return cwd

    return here.parent.parent.parent


def session_file_path(repo_root: Path | None = None) -> Path:
    root = repo_root or detect_repo_root()
    return root / ".galaxy/hermes-session.json"


def event_log_path(repo_root: Path | None = None) -> Path:
    root = repo_root or detect_repo_root()
    return root / ".sisyphus/notepads/galaxy-session-events.jsonl"


def log_event(event_type: str, **details: Any) -> None:
    try:
        file_path = event_log_path()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **details,
        }
        with file_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
    except OSError:
        pass
