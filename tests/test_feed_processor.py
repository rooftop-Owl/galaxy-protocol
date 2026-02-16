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
NOT_ENRICHED_MARKER = feed_processor.NOT_ENRICHED_MARKER
process_feed = feed_processor.process_feed
_spawn_deepwiki_enrichment = feed_processor._spawn_deepwiki_enrichment
_contains_deepwiki_errors = feed_processor._contains_deepwiki_errors
_clean_failed_enrichment = feed_processor._clean_failed_enrichment
_update_index_analysis = feed_processor._update_index_analysis


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
    return_value=(None, "No agent CLI found. Searched PATH for: opencode, claude."),
)
async def test_spawn_enrichment_reports_missing_binary(_mock_resolve, tmp_path):
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
    assert "No agent CLI found" in payload["message"]


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


# --- New tests for Fix 2 & Fix 3 ---


def test_contains_deepwiki_errors_detects_not_indexed():
    content = (
        "## Relevance to Our Work\n\n"
        "Error processing question: Repository not found. "
        "Visit https://deepwiki.com to index it. Requested repos: foo/bar\n"
    )
    assert _contains_deepwiki_errors(content) is True


def test_contains_deepwiki_errors_passes_clean_content():
    content = (
        "## Relevance to Our Work\n\n"
        "This repo implements a useful pattern for state management.\n"
    )
    assert _contains_deepwiki_errors(content) is False


def test_clean_failed_enrichment_replaces_error_sections(tmp_path):
    ref_path = tmp_path / "ref.md"
    ref_path.write_text(
        "# Test Repo\n\n"
        "**Source**: https://github.com/foo/bar\n\n"
        "---\n\n"
        "## Summary\n\nGood summary here.\n\n"
        "## Key Insights\n\n- Insight one\n\n"
        "## Relevance to Our Work\n\n"
        "Error processing question: Repository not found. "
        "Visit https://deepwiki.com to index it.\n\n"
        "## Applicable Patterns\n\n"
        "- Error processing question: Repository not found.\n",
        encoding="utf-8",
    )

    _clean_failed_enrichment(ref_path)
    cleaned = ref_path.read_text(encoding="utf-8")

    assert "Repository not found" not in cleaned
    assert NOT_ENRICHED_MARKER in cleaned
    assert "Good summary here." in cleaned
    assert "Insight one" in cleaned


def test_update_index_analysis_sets_status(tmp_path):
    references_dir = tmp_path
    ref_path = references_dir / "test-ref.md"
    ref_path.write_text("content", encoding="utf-8")

    index_data = {
        "version": "1.0",
        "references": [
            {"slug": "test-ref", "file": "test-ref.md", "analysis": "deepwiki-pending"},
        ],
    }
    (references_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    _update_index_analysis(references_dir, ref_path, "deepwiki-enriched")

    updated = json.loads((references_dir / "index.json").read_text(encoding="utf-8"))
    assert updated["references"][0]["analysis"] == "deepwiki-enriched"


def test_update_index_analysis_noop_when_ref_not_found(tmp_path):
    references_dir = tmp_path
    ref_path = references_dir / "missing-ref.md"

    index_data = {
        "version": "1.0",
        "references": [
            {"slug": "other-ref", "file": "other-ref.md", "analysis": "deepwiki-pending"},
        ],
    }
    (references_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

    _update_index_analysis(references_dir, ref_path, "deepwiki-enriched")

    updated = json.loads((references_dir / "index.json").read_text(encoding="utf-8"))
    assert updated["references"][0]["analysis"] == "deepwiki-pending"  # unchanged
