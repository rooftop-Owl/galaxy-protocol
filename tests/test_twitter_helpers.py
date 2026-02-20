import json
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

fp = importlib.import_module("caduceus.feed_processor")
_is_twitter_url = fp._is_twitter_url
_extract_tweet_id = fp._extract_tweet_id
_resolve_tweet_username = fp._resolve_tweet_username
_fxtwitter_api = fp._fxtwitter_api
_parse_fxtwitter_tweet = fp._parse_fxtwitter_tweet
_fetch_twitter_content = fp._fetch_twitter_content
process_feed = fp.process_feed


def _urlopen_mock(body: bytes) -> MagicMock:
    m = MagicMock()
    m.read.return_value = body
    return m


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/foo/status/123", True),
        ("https://twitter.com/foo/status/123", True),
        ("https://www.x.com/foo/status/123", True),
        ("https://www.twitter.com/foo/status/123", True),
        ("https://fxtwitter.com/foo/status/123", False),
        ("https://github.com/foo", False),
        ("https://example.com", False),
        ("https://x.com", True),
    ],
)
def test_is_twitter_url(url, expected):
    assert _is_twitter_url(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/foo/status/9876543210", "9876543210"),
        ("https://x.com/i/status/9876543210", "9876543210"),
        ("https://twitter.com/foo/status/1111", "1111"),
        ("https://x.com/foo", None),
        ("https://x.com", None),
        ("https://x.com/status/", None),
    ],
)
def test_extract_tweet_id(url, expected):
    assert _extract_tweet_id(url) == expected


def test_parse_plain_tweet():
    tweet = {"raw_text": {"text": "Hello world"}, "author": {"screen_name": "foo"}}
    title, summary, insights, kw = _parse_fxtwitter_tweet(tweet)
    assert title == "Hello world"
    assert summary == "Hello world"
    assert kw == ["foo"]


def test_parse_article_with_preview_and_blocks():
    tweet = {
        "author": {"screen_name": "bar"},
        "article": {
            "title": "My Article",
            "preview_text": "Short preview.",
            "content": {
                "blocks": [
                    {"type": "unstyled", "text": "Para one."},
                    {"type": "blockquote", "text": "A quote."},
                    {"type": "atomic", "text": "ignored"},
                    {"type": "unstyled", "text": "Para two."},
                ]
            },
        },
    }
    title, summary, insights, kw = _parse_fxtwitter_tweet(tweet)
    assert title == "My Article"
    assert summary == "Short preview."
    assert "Para one." in insights
    assert "> A quote." in insights
    assert not any("ignored" in s for s in insights)
    assert kw == ["bar"]


def test_parse_article_no_preview_falls_back_to_body():
    tweet = {
        "author": {"screen_name": "baz"},
        "article": {
            "title": "No Preview",
            "preview_text": "",
            "content": {"blocks": [{"type": "unstyled", "text": "Body text here."}]},
        },
    }
    _, summary, _, _ = _parse_fxtwitter_tweet(tweet)
    assert summary == "Body text here."


def test_parse_empty_tweet_fallback_title():
    title, _, _, kw = _parse_fxtwitter_tweet({})
    assert title == "@unknown on X"
    assert kw == []


def test_parse_no_author_no_crash():
    tweet = {"raw_text": {"text": "Just a tweet"}}
    title, _, _, kw = _parse_fxtwitter_tweet(tweet)
    assert title == "Just a tweet"
    assert kw == []


def test_parse_empty_blocks_insights_fall_back_to_summary():
    tweet = {
        "author": {"screen_name": "x"},
        "article": {"title": "Title", "preview_text": "Preview.", "content": {"blocks": []}},
    }
    _, summary, insights, _ = _parse_fxtwitter_tweet(tweet)
    assert summary == "Preview."
    assert insights == ["Preview."]


def test_resolve_tweet_username_success():
    html = '<a href="https://twitter.com/testuser/status/123">link</a>'
    body = json.dumps({"html": html}).encode()
    with patch("urllib.request.urlopen", return_value=_urlopen_mock(body)):
        assert _resolve_tweet_username("123") == "testuser"


def test_resolve_tweet_username_no_match_returns_none():
    body = json.dumps({"html": "<blockquote>no username here</blockquote>"}).encode()
    with patch("urllib.request.urlopen", return_value=_urlopen_mock(body)):
        assert _resolve_tweet_username("123") is None


def test_resolve_tweet_username_network_error_returns_none():
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        assert _resolve_tweet_username("123") is None


def test_fxtwitter_api_success():
    tweet_data = {"id": "123", "text": "Hello"}
    body = json.dumps({"tweet": tweet_data}).encode()
    with patch("urllib.request.urlopen", return_value=_urlopen_mock(body)):
        assert _fxtwitter_api("foo", "123") == tweet_data


def test_fxtwitter_api_missing_tweet_key_returns_none():
    body = json.dumps({"code": 404, "message": "Not Found"}).encode()
    with patch("urllib.request.urlopen", return_value=_urlopen_mock(body)):
        assert _fxtwitter_api("foo", "123") is None


def test_fxtwitter_api_network_error_returns_none():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert _fxtwitter_api("foo", "123") is None


def test_fetch_twitter_content_standard_url():
    tweet = {"raw_text": {"text": "Tweet text"}, "author": {"screen_name": "foo"}}
    with patch("caduceus.feed_processor._fxtwitter_api", return_value=tweet):
        result = _fetch_twitter_content("https://x.com/foo/status/9999")
    assert result is not None
    title, _, _, _ = result
    assert title == "Tweet text"


def test_fetch_twitter_content_i_status_resolves_username():
    tweet = {"raw_text": {"text": "Tweet text"}, "author": {"screen_name": "bar"}}
    with (
        patch("caduceus.feed_processor._resolve_tweet_username", return_value="bar"),
        patch("caduceus.feed_processor._fxtwitter_api", return_value=tweet),
    ):
        result = _fetch_twitter_content("https://x.com/i/status/9999")
    assert result is not None
    _, _, _, kw = result
    assert kw == ["bar"]


def test_fetch_twitter_content_i_status_oembed_fails_returns_none():
    with patch("caduceus.feed_processor._resolve_tweet_username", return_value=None):
        assert _fetch_twitter_content("https://x.com/i/status/9999") is None


def test_fetch_twitter_content_api_returns_none():
    with patch("caduceus.feed_processor._fxtwitter_api", return_value=None):
        assert _fetch_twitter_content("https://x.com/foo/status/9999") is None


def test_fetch_twitter_content_no_status_segment_returns_none():
    assert _fetch_twitter_content("https://x.com/foo") is None


@pytest.mark.asyncio
@patch(
    "caduceus.feed_processor._fetch_twitter_content",
    return_value=("My Tweet Title", "Tweet summary.", ["Insight one."], ["tweetuser"]),
)
async def test_process_feed_twitter_api_success(mock_twitter, tmp_path):
    refs_dir = tmp_path / ".sisyphus" / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    result = await process_feed(
        "https://x.com/tweetuser/status/12345",
        None,
        "telegram",
        refs_dir,
        config={},
    )

    assert "error" not in result
    assert result["title"] == "My Tweet Title"
    assert result["type"] == "post"
    mock_twitter.assert_called_once_with("https://x.com/tweetuser/status/12345")

    index = json.loads((refs_dir / "index.json").read_text())
    assert index["references"][-1]["type"] == "post"


@pytest.mark.asyncio
@patch("caduceus.feed_processor._fetch_twitter_content", return_value=None)
@patch("caduceus.feed_processor.trafilatura.fetch_url", return_value=None)
async def test_process_feed_twitter_all_fetches_fail(mock_fetch, mock_twitter, tmp_path):
    refs_dir = tmp_path / ".sisyphus" / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    result = await process_feed(
        "https://x.com/foo/status/99999",
        None,
        "telegram",
        refs_dir,
        config={},
    )

    assert "error" in result
    assert "API and scraping both failed" in result["error"]


@pytest.mark.asyncio
@patch("caduceus.feed_processor._fetch_twitter_content", return_value=None)
@patch(
    "caduceus.feed_processor.trafilatura.extract_metadata",
    return_value=SimpleNamespace(title="JavaScript is not available."),
)
@patch("caduceus.feed_processor.trafilatura.extract", return_value="We've detected JS is disabled")
@patch("caduceus.feed_processor.trafilatura.fetch_url", return_value="<html>jsgated</html>")
async def test_process_feed_twitter_js_gate_returns_error(mock_fetch, mock_extract, mock_meta, mock_twitter, tmp_path):
    refs_dir = tmp_path / ".sisyphus" / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    result = await process_feed(
        "https://x.com/foo/status/99999",
        None,
        "telegram",
        refs_dir,
        config={},
    )

    assert "error" in result
    assert "JS-gated" in result["error"]
