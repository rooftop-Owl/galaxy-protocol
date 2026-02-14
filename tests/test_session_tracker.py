#!/usr/bin/env python3

import importlib
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

session_tracker = importlib.import_module("session_tracker")


def test_detect_repo_root_from_cwd(tmp_path, monkeypatch):
    (tmp_path / ".sisyphus").mkdir()
    (tmp_path / ".galaxy").mkdir()
    monkeypatch.chdir(tmp_path)

    assert session_tracker.detect_repo_root() == tmp_path


def test_log_event_writes_jsonl(tmp_path, monkeypatch):
    (tmp_path / ".sisyphus").mkdir()
    (tmp_path / ".galaxy").mkdir()
    monkeypatch.chdir(tmp_path)

    session_tracker.log_event("frontend_ws_connected", component="web", user_id="u-1")

    event_file = tmp_path / ".sisyphus/notepads/galaxy-session-events.jsonl"
    assert event_file.exists()

    lines = event_file.read_text().strip().splitlines()
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["event_type"] == "frontend_ws_connected"
    assert payload["component"] == "web"
    assert payload["user_id"] == "u-1"
    assert "timestamp" in payload
