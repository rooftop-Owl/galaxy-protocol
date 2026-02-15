#!/usr/bin/env python3

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

feature_preflight = importlib.import_module("feature_preflight")


def test_check_opencode_runtime_returns_path(monkeypatch):
    original_import = feature_preflight.importlib.import_module

    def fake_import(name):
        if name == "opencode_runtime":
            return SimpleNamespace(resolve_opencode_binary=lambda: ("/usr/local/bin/opencode", None))
        return original_import(name)

    monkeypatch.setattr(feature_preflight.importlib, "import_module", fake_import)

    ok, detail = feature_preflight._check_opencode_runtime()
    assert ok is True
    assert detail == "/usr/local/bin/opencode"


def test_check_opencode_runtime_returns_error(monkeypatch):
    original_import = feature_preflight.importlib.import_module

    def fake_import(name):
        if name == "opencode_runtime":
            return SimpleNamespace(resolve_opencode_binary=lambda: (None, "missing"))
        return original_import(name)

    monkeypatch.setattr(feature_preflight.importlib, "import_module", fake_import)

    ok, detail = feature_preflight._check_opencode_runtime()
    assert ok is False
    assert detail == "missing"
