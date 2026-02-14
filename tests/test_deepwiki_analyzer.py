#!/usr/bin/env python3
"""Tests for DeepWiki analyzer with module-level mocking."""

import pytest
from unittest.mock import AsyncMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from handlers.deepwiki_analyzer import analyze_repo


CONFIG_ENABLED = {
    "features": {"GALAXY_DEEPWIKI_ENABLED": True},
    "deepwiki": {"timeout_seconds": 60},
}

CONFIG_DISABLED = {
    "features": {"GALAXY_DEEPWIKI_ENABLED": False},
}


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_success(mock_get_client):
    """Test analyze_repo with successful DeepWiki responses."""
    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(
        return_value="Repository structure overview"
    )
    mock_client.ask_question = AsyncMock(
        side_effect=[
            "Solves problem X",
            "Uses pattern Y",
            "Key abstraction Z",
            "Workflow A->B->C",
        ]
    )
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is not None
    assert result["problem"] == "Solves problem X"
    assert result["architecture"] == "Uses pattern Y"
    assert result["abstractions"] == "Key abstraction Z"
    assert result["workflow"] == "Workflow A->B->C"
    assert result["structure"] == "Repository structure overview"

    mock_client.read_wiki_structure.assert_called_once_with("vercel/ai")
    assert mock_client.ask_question.call_count == 4


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_feature_disabled(mock_get_client):
    """Test analyze_repo returns None when feature disabled."""
    result = await analyze_repo("vercel", "ai", CONFIG_DISABLED)

    assert result is None
    mock_get_client.assert_not_called()


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_client_unavailable(mock_get_client):
    """Test analyze_repo returns None when client unavailable."""
    mock_get_client.return_value = None

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is None


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_structure_timeout(mock_get_client):
    """Test analyze_repo handles structure timeout gracefully."""
    import asyncio

    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is None


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_rate_limited(mock_get_client):
    """Test analyze_repo handles rate limiting."""
    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(
        side_effect=Exception("429 Rate limit exceeded")
    )
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is None


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_question_timeout(mock_get_client):
    """Test analyze_repo continues when question times out."""
    import asyncio

    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(
        return_value="Repository structure overview"
    )
    mock_client.ask_question = AsyncMock(
        side_effect=[
            "Solves problem X",
            asyncio.TimeoutError(),
            "Key abstraction Z",
            "Workflow A->B->C",
        ]
    )
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is not None
    assert result["problem"] == "Solves problem X"
    assert result["architecture"] == "Timeout - unable to retrieve"
    assert result["abstractions"] == "Key abstraction Z"
    assert result["workflow"] == "Workflow A->B->C"


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_partial_results_on_rate_limit(mock_get_client):
    """Test analyze_repo returns partial results when rate limited mid-analysis."""
    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(
        return_value="Repository structure overview"
    )
    mock_client.ask_question = AsyncMock(
        side_effect=[
            "Solves problem X",
            "Uses pattern Y",
            Exception("429 Rate limit exceeded"),
        ]
    )
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is not None
    assert result["problem"] == "Solves problem X"
    assert result["architecture"] == "Uses pattern Y"
    assert "structure" in result


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_question_error(mock_get_client):
    """Test analyze_repo handles question errors gracefully."""
    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(
        return_value="Repository structure overview"
    )
    mock_client.ask_question = AsyncMock(
        side_effect=[
            "Solves problem X",
            Exception("Network error"),
            "Key abstraction Z",
            "Workflow A->B->C",
        ]
    )
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is not None
    assert result["problem"] == "Solves problem X"
    assert "Error: Network error" in result["architecture"]
    assert result["abstractions"] == "Key abstraction Z"
    assert result["workflow"] == "Workflow A->B->C"


@pytest.mark.asyncio
@patch("handlers.deepwiki_analyzer.get_deepwiki_client")
async def test_analyze_repo_repo_not_indexed(mock_get_client):
    """Test analyze_repo handles unindexed repository."""
    mock_client = AsyncMock()
    mock_client.read_wiki_structure = AsyncMock(
        side_effect=Exception("Repository not found")
    )
    mock_get_client.return_value = mock_client

    result = await analyze_repo("vercel", "ai", CONFIG_ENABLED)

    assert result is None
