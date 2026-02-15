#!/usr/bin/env python3
"""Tests for feed processor background DeepWiki enrichment."""

import json
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

feed_processor = importlib.import_module("caduceus.feed_processor")
PATTERNS_PLACEHOLDER = feed_processor.PATTERNS_PLACEHOLDER
RELEVANCE_PLACEHOLDER = feed_processor.RELEVANCE_PLACEHOLDER
process_feed = feed_processor.process_feed
_spawn_deepwiki_enrichment = feed_processor._spawn_deepwiki_enrichment


class DummyArticle:
    def __init__(self, _url: str):
        self.summary = "Article summary"
        self.keywords = ["python", "visualization"]

    def download(self):
        return None

    def parse(self):
        return None

    def nlp(self):
        return None


@pytest.mark.asyncio
@patch("caduceus.feed_processor._spawn_deepwiki_enrichment", new_callable=AsyncMock)
@patch("caduceus.feed_processor.Article", DummyArticle)
@patch("caduceus.feed_processor.trafilatura.extract")
@patch("caduceus.feed_processor.trafilatura.extract_metadata")
@patch("caduceus.feed_processor.trafilatura.fetch_url")
async def test_process_feed_dispatches_github_enrichment(
    mock_fetch,
    mock_metadata,
    mock_extract,
    mock_spawn,
    tmp_path,
):
    repo_root = tmp_path / "repo"
    references_dir = repo_root / ".sisyphus" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    config_dir = repo_root / ".galaxy"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"features": {"GALAXY_DEEPWIKI_ENABLED": True}}),
        encoding="utf-8",
    )

    mock_fetch.return_value = "<html>content</html>"
    mock_metadata.return_value = SimpleNamespace(title="Example Repo")
    mock_extract.return_value = "Sentence one. Sentence two. Sentence three."
    mock_spawn.return_value = True

    result = await process_feed("https://github.com/example/repo", None, "telegram", references_dir)

    assert "error" not in result
    assert result["slug"].startswith("202")
    mock_spawn.assert_awaited_once()

    reference_text = Path(result["file_path"]).read_text(encoding="utf-8")
    assert RELEVANCE_PLACEHOLDER in reference_text
    assert PATTERNS_PLACEHOLDER in reference_text

    index_data = json.loads((references_dir / "index.json").read_text(encoding="utf-8"))
    assert index_data["references"][-1]["analysis"] == "deepwiki-pending"


@pytest.mark.asyncio
@patch("caduceus.feed_processor._spawn_deepwiki_enrichment", new_callable=AsyncMock)
@patch("caduceus.feed_processor.Article", DummyArticle)
@patch("caduceus.feed_processor.trafilatura.extract")
@patch("caduceus.feed_processor.trafilatura.extract_metadata")
@patch("caduceus.feed_processor.trafilatura.fetch_url")
async def test_process_feed_skips_enrichment_when_disabled(
    mock_fetch,
    mock_metadata,
    mock_extract,
    mock_spawn,
    tmp_path,
):
    references_dir = tmp_path / ".sisyphus" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    mock_fetch.return_value = "<html>content</html>"
    mock_metadata.return_value = SimpleNamespace(title="Docs")
    mock_extract.return_value = "Sentence one. Sentence two. Sentence three."

    result = await process_feed(
        "https://github.com/example/repo",
        None,
        "telegram",
        references_dir,
        config={"features": {"GALAXY_DEEPWIKI_ENABLED": False}},
    )

    assert "error" not in result
    mock_spawn.assert_not_awaited()


@pytest.mark.asyncio
@patch(
    "caduceus.feed_processor.resolve_opencode_binary",
    return_value=(None, "opencode CLI is not available on PATH for the Galaxy runtime."),
)
async def test_spawn_enrichment_reports_missing_opencode(_mock_resolve, tmp_path):
    references_dir = tmp_path / ".sisyphus" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    reference_path = references_dir / "ref.md"
    reference_path.write_text("placeholder", encoding="utf-8")

    started = await _spawn_deepwiki_enrichment(
        repo_url="https://github.com/example/repo",
        owner="example",
        repo="repo",
        references_dir=references_dir,
        reference_path=reference_path,
        chat_id=1791247114,
    )
    assert started is False

    outbox_dir = references_dir.parent / "notepads" / "galaxy-outbox"
    outbox_files = list(outbox_dir.glob("deepwiki-enrich-*.json"))
    assert outbox_files

    payload = json.loads(outbox_files[0].read_text(encoding="utf-8"))
    assert payload["severity"] == "warning"
    assert payload["chat_id"] == 1791247114
    assert "opencode CLI is not available on PATH" in payload["message"]


@pytest.mark.asyncio
@patch("caduceus.feed_processor._spawn_deepwiki_enrichment", new_callable=AsyncMock)
@patch("caduceus.feed_processor.Article", DummyArticle)
@patch("caduceus.feed_processor.trafilatura.extract")
@patch("caduceus.feed_processor.trafilatura.extract_metadata")
@patch("caduceus.feed_processor.trafilatura.fetch_url")
async def test_process_feed_marks_unavailable_when_enrichment_not_started(
    mock_fetch,
    mock_metadata,
    mock_extract,
    mock_spawn,
    tmp_path,
):
    references_dir = tmp_path / ".sisyphus" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    mock_fetch.return_value = "<html>content</html>"
    mock_metadata.return_value = SimpleNamespace(title="Example Repo")
    mock_extract.return_value = "Sentence one. Sentence two. Sentence three."
    mock_spawn.return_value = False

    result = await process_feed(
        "https://github.com/example/repo",
        None,
        "telegram",
        references_dir,
        config={"features": {"GALAXY_DEEPWIKI_ENABLED": True}},
    )

    assert "error" not in result
    index_data = json.loads((references_dir / "index.json").read_text(encoding="utf-8"))
    assert index_data["references"][-1]["analysis"] == "deepwiki-unavailable"


@pytest.mark.asyncio
@patch("caduceus.feed_processor.Article", DummyArticle)
@patch("caduceus.feed_processor.trafilatura.extract")
@patch("caduceus.feed_processor.trafilatura.extract_metadata")
@patch("caduceus.feed_processor.trafilatura.fetch_url")
async def test_process_feed_updates_existing_duplicate_reference(
    mock_fetch,
    mock_metadata,
    mock_extract,
    tmp_path,
):
    references_dir = tmp_path / ".sisyphus" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    mock_fetch.return_value = "<html>content</html>"
    mock_metadata.return_value = SimpleNamespace(title="Example Repo")
    mock_extract.return_value = "Sentence one. Sentence two. Sentence three."

    first = await process_feed(
        "https://github.com/example/repo",
        "first note",
        "telegram",
        references_dir,
        config={"features": {"GALAXY_DEEPWIKI_ENABLED": False}},
    )
    second = await process_feed(
        "https://github.com/example/repo/",
        "second note",
        "telegram",
        references_dir,
        config={"features": {"GALAXY_DEEPWIKI_ENABLED": False}},
    )

    assert first["slug"] == second["slug"]
    assert first["file_path"] == second["file_path"]
    assert second["updated_existing"] is True

    index_data = json.loads((references_dir / "index.json").read_text(encoding="utf-8"))
    assert len(index_data["references"]) == 1
    assert index_data["references"][0]["note"] == "second note"

    reference_text = Path(second["file_path"]).read_text(encoding="utf-8")
    assert "**Note**: second note" in reference_text
