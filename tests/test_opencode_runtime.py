#!/usr/bin/env python3

import importlib
import sys
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

opencode_runtime = importlib.import_module("opencode_runtime")
hermes = importlib.import_module("hermes")

resolve_opencode_binary = opencode_runtime.resolve_opencode_binary
sanitize_opencode_env = opencode_runtime.sanitize_opencode_env


def test_resolve_opencode_binary_uses_explicit_override(tmp_path):
    binary = tmp_path / "opencode"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)

    resolved, error = resolve_opencode_binary({"GALAXY_OPENCODE_BIN": str(binary)})

    assert resolved == str(binary)
    assert error is None


@patch("opencode_runtime.shutil.which", return_value=None)
def test_resolve_opencode_binary_reports_invalid_override(_mock_which):
    resolved, error = resolve_opencode_binary({"GALAXY_OPENCODE_BIN": "/tmp/does-not-exist/opencode"})

    assert resolved is None
    assert error is not None
    assert "GALAXY_OPENCODE_BIN" in error


@patch("opencode_runtime.shutil.which")
def test_resolve_opencode_binary_uses_path_lookup(mock_which):
    def which_side_effect(name):
        if name == "opencode":
            return "/usr/local/bin/opencode"
        return None

    mock_which.side_effect = which_side_effect

    resolved, error = resolve_opencode_binary({})

    assert resolved == "/usr/local/bin/opencode"
    assert error is None


def test_sanitize_opencode_env_removes_only_opencode_keys():
    cleaned = sanitize_opencode_env(
        {
            "PATH": "/usr/bin",
            "OPENCODE": "1",
            "OPENCODE_SERVER_PASSWORD": "secret",
            "GALAXY_OPENCODE_BIN": "/custom/opencode",
        }
    )

    assert "PATH" in cleaned
    assert "GALAXY_OPENCODE_BIN" in cleaned
    assert "OPENCODE" not in cleaned
    assert "OPENCODE_SERVER_PASSWORD" not in cleaned


@patch("hermes.resolve_opencode_binary", return_value=(None, "binary missing"))
def test_hermes_call_agent_returns_resolution_error(_mock_resolve):
    response = hermes.call_agent("hello", "http://localhost:4096")
    assert response == "Agent execution unavailable: binary missing"
