#!/usr/bin/env python3

import importlib
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

paper_handler = importlib.import_module("handlers.paper_handler")


@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("10.1038/s41586-021-03819-2", "10.1038/s41586-021-03819-2"),
        (
            "https://doi.org/10.1038/s41586-021-03819-2",
            "10.1038/s41586-021-03819-2",
        ),
        (
            "https://dx.doi.org/10.1038/s41586-021-03819-2",
            "10.1038/s41586-021-03819-2",
        ),
        (
            "https://arxiv.org/abs/2602.03837",
            "10.48550/arXiv.2602.03837",
        ),
        (
            "https://arxiv.org/abs/2602.03837v2",
            "10.48550/arXiv.2602.03837",
        ),
        ("https://arxiv.org/abs/cs.AI/2602.03837", None),
        (
            "Check out 10.1038/s41586-021-03819-2 for details",
            "10.1038/s41586-021-03819-2",
        ),
        ("https://github.com/astral-sh/ruff", None),
        ("completely plain text", None),
        ("", None),
    ],
)
def test_extract_doi(input_str, expected):
    assert paper_handler.extract_doi(input_str) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://arxiv.org/abs/2602.03837", True),
        ("https://doi.org/10.1038/s41586-021-03819-2", True),
        ("https://www.nature.com/articles/s41586-021-03819-2", True),
        ("https://example.org/paper.pdf", True),
        ("https://example.org/paper.pdf?download=1", True),
        ("https://github.com/astral-sh/ruff", False),
        ("https://myblog.example.com/posts/hello-world", False),
    ],
)
def test_detect_paper_url(url, expected):
    assert paper_handler.detect_paper_url(url) is expected


def install_fake_zotero(monkeypatch, doi_result=None, url_result=None, raise_error=None):
    calls = {
        "connected": False,
        "closed": False,
        "method": None,
        "identifier": None,
        "auto_tag": None,
        "auto_classify": None,
    }

    class FakeZoteroWeb:
        def connect(self):
            calls["connected"] = True

        def close(self):
            calls["closed"] = True

        def add_by_doi(self, identifier, collection_key=None, auto_tag=False, auto_classify=False):
            calls["method"] = "doi"
            calls["identifier"] = identifier
            calls["auto_tag"] = auto_tag
            calls["auto_classify"] = auto_classify
            calls["collection_key"] = collection_key
            if raise_error:
                raise RuntimeError(raise_error)
            return doi_result or {
                "title": "Sample DOI Paper",
                "key": "DOIKEY123",
                "doi": identifier,
                "authors": [{"firstName": "Ada", "lastName": "Lovelace"}],
                "auto_tags": ["AI", "Methods"],
                "auto_collections": ["Machine Learning"],
            }

        def add_by_url(self, identifier, collection_key=None, auto_tag=False, auto_classify=False):
            calls["method"] = "url"
            calls["identifier"] = identifier
            calls["auto_tag"] = auto_tag
            calls["auto_classify"] = auto_classify
            calls["collection_key"] = collection_key
            if raise_error:
                raise RuntimeError(raise_error)
            return url_result or {
                "title": "Sample URL Paper",
                "key": "URLKEY456",
                "doi": "10.1000/url-paper",
                "authors": ["Grace Hopper"],
                "auto_tags": ["Systems"],
                "auto_collections": ["Foundational Papers"],
            }

    tools_mod = types.ModuleType("tools")
    research_mod = types.ModuleType("tools.research")
    zotero_mod = types.ModuleType("tools.research.zotero_web")
    zotero_mod.ZoteroWeb = FakeZoteroWeb
    research_mod.zotero_web = zotero_mod
    tools_mod.research = research_mod

    monkeypatch.setitem(sys.modules, "tools", tools_mod)
    monkeypatch.setitem(sys.modules, "tools.research", research_mod)
    monkeypatch.setitem(sys.modules, "tools.research.zotero_web", zotero_mod)

    return calls


@pytest.mark.asyncio
async def test_add_paper_success_with_doi(monkeypatch):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")
    calls = install_fake_zotero(monkeypatch)

    result = await paper_handler.add_paper(
        "10.1038/s41586-021-03819-2",
        note="read this soon",
        config={"features": {"GALAXY_ZOTERO_ENABLED": True}},
    )

    assert result["title"] == "Sample DOI Paper"
    assert result["key"] == "DOIKEY123"
    assert result["doi"] == "10.1038/s41586-021-03819-2"
    assert result["auto_tags"] == ["AI", "Methods"]
    assert result["auto_collections"] == ["Machine Learning"]
    assert result["note"] == "read this soon"

    assert calls["connected"] is True
    assert calls["closed"] is True
    assert calls["method"] == "doi"
    assert calls["identifier"] == "10.1038/s41586-021-03819-2"
    assert calls["auto_tag"] is True
    assert calls["auto_classify"] is True
    assert calls["collection_key"] is None


@pytest.mark.asyncio
async def test_add_paper_success_with_arxiv_url(monkeypatch):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")
    calls = install_fake_zotero(monkeypatch)

    result = await paper_handler.add_paper(
        "https://arxiv.org/abs/2602.03837v2",
        config={"features": {"GALAXY_ZOTERO_ENABLED": True}},
    )

    assert "error" not in result
    assert calls["method"] == "doi"
    assert calls["identifier"] == "10.48550/arXiv.2602.03837"


@pytest.mark.asyncio
async def test_add_paper_success_with_non_doi_paper_url(monkeypatch):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")
    calls = install_fake_zotero(monkeypatch)

    result = await paper_handler.add_paper(
        "https://www.nature.com/articles/s41586-021-03819-2",
        config={"features": {"GALAXY_ZOTERO_ENABLED": True}},
    )

    assert "error" not in result
    assert calls["method"] == "url"
    assert calls["identifier"] == "https://www.nature.com/articles/s41586-021-03819-2"


@pytest.mark.asyncio
async def test_add_paper_error_when_feature_disabled(monkeypatch):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")

    result = await paper_handler.add_paper(
        "10.1038/s41586-021-03819-2",
        config={"features": {"GALAXY_ZOTERO_ENABLED": False}},
    )

    assert result == {"error": "Zotero integration is disabled (GALAXY_ZOTERO_ENABLED=false)"}


@pytest.mark.asyncio
async def test_add_paper_error_when_credentials_missing(monkeypatch):
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)

    result = await paper_handler.add_paper(
        "10.1038/s41586-021-03819-2",
        config={"features": {"GALAXY_ZOTERO_ENABLED": True}},
    )

    assert "ZOTERO_USER_ID" in result["error"]
    assert "ZOTERO_API_KEY" in result["error"]


@pytest.mark.asyncio
async def test_add_paper_error_on_unrecognized_input(monkeypatch):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")

    result = await paper_handler.add_paper(
        "just some text",
        config={"features": {"GALAXY_ZOTERO_ENABLED": True}},
    )

    assert result == {"error": "Could not detect DOI or paper URL from input"}


@pytest.mark.asyncio
async def test_add_paper_error_when_zotero_add_fails(monkeypatch):
    monkeypatch.setenv("ZOTERO_USER_ID", "12345")
    monkeypatch.setenv("ZOTERO_API_KEY", "secret-key")
    install_fake_zotero(monkeypatch, raise_error="network timeout")

    result = await paper_handler.add_paper(
        "10.1038/s41586-021-03819-2",
        config={"features": {"GALAXY_ZOTERO_ENABLED": True}},
    )

    assert result["error"] == "Failed to add paper to Zotero: network timeout"


def test_format_result_success():
    rendered = paper_handler.format_result(
        {
            "title": "A Very Good Paper",
            "authors": [
                {"firstName": "Ada", "lastName": "Lovelace"},
                {"firstName": "Grace", "lastName": "Hopper"},
            ],
            "doi": "10.1038/s41586-021-03819-2",
            "auto_tags": ["AI", "Benchmark"],
            "auto_collections": ["Machine Learning", "Foundational Papers"],
        }
    )

    assert rendered.startswith("✓ Added to Zotero: A Very Good Paper")
    assert "Authors: Ada Lovelace, Grace Hopper" in rendered
    assert "DOI: 10.1038/s41586-021-03819-2" in rendered
    assert "Auto-tagged: AI, Benchmark" in rendered
    assert "Classified to: Machine Learning, Foundational Papers" in rendered


def test_format_result_error():
    rendered = paper_handler.format_result({"error": "Could not detect DOI"})
    assert rendered == "✗ Could not detect DOI"
