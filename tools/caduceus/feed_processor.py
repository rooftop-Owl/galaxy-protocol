from __future__ import annotations

import asyncio
import importlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import trafilatura
from newspaper import Article

opencode_runtime = importlib.import_module("opencode_runtime")
resolve_opencode_binary = opencode_runtime.resolve_opencode_binary
sanitize_opencode_env = opencode_runtime.sanitize_opencode_env

# Session persistence for DeepWiki enrichment (reuse hermes session)
try:
    session_tracker = importlib.import_module("session_tracker")
    _session_file_path = session_tracker.session_file_path
except ImportError:
    _session_file_path = None

logger = logging.getLogger(__name__)

# Stopwords for tag filtering (noise reduction)
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "as",
    "is",
    "was",
    "are",
    "were",
    "be",
    "x",
    "y",
    "z",
    "i",
    "j",
    "k",
    "foo",
    "bar",
    "baz",
    "test",
    "example",
    "sample",
    "var",
    "tmp",
    "temp",
}

RELEVANCE_PLACEHOLDER = "Review and connect this reference to current astraeus or galaxy-protocol efforts."
PATTERNS_PLACEHOLDER = "Identify any concrete patterns or practices worth adopting."


def _load_enrichment_session_id(repo_root: Path) -> str | None:
    """Load persistent session ID for DeepWiki enrichment."""
    if not _session_file_path:
        return None
    try:
        session_file = _session_file_path(repo_root)
        if session_file.exists():
            data = json.loads(session_file.read_text())
            return data.get("session_id")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_enrichment_session_id(repo_root: Path, session_id: str) -> None:
    """Save session ID for reuse by subsequent enrichment jobs."""
    if not _session_file_path:
        return
    try:
        session_file = _session_file_path(repo_root)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
    except OSError:
        pass


# Known DeepWiki error patterns that indicate a failed analysis baked into content.
# When these appear in "Relevance" or "Patterns" sections, the enrichment produced
# garbage — replace with clean markers instead of keeping error text.
DEEPWIKI_ERROR_PATTERNS = [
    "Repository not found",
    "Visit https://deepwiki.com to index it",
    "Error processing question",
    "Requested repos:",
]

NOT_ENRICHED_MARKER = "DeepWiki analysis unavailable for this repository."


def _to_ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def _slugify(value: str, max_length: int = 200) -> str:
    """Convert value to URL-safe slug, truncated to max_length.

    Args:
        value: String to slugify
        max_length: Maximum slug length (default 200 to stay under 255-byte filename limit
                    after adding date prefix and .md extension)
    """
    ascii_value = _to_ascii(value).lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value)
    ascii_value = re.sub(r"-+", "-", ascii_value).strip("-")

    # Truncate to max_length, avoiding mid-word cuts
    if len(ascii_value) > max_length:
        ascii_value = ascii_value[:max_length].rsplit("-", 1)[0]

    return ascii_value or "reference"


def _extract_owner_repo(url: str) -> tuple[str, str]:
    """Extract owner and repo from GitHub URL.

    Handles:
    - https://github.com/owner/repo
    - github.com/owner/repo
    - https://github.com/owner/repo/tree/branch
    """
    parts = url.split("github.com/")[1].split("/")
    owner = parts[0]
    repo = parts[1].split("?")[0]  # Remove query params
    return owner, repo


def _rewrite_twitter_url(url: str) -> str:
    """Rewrite x.com/twitter.com URLs to fxtwitter.com for content extraction.

    Twitter/X gates content behind JS. fxtwitter.com provides a static
    mirror that trafilatura can fetch successfully.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    twitter_hosts = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}
    if netloc in twitter_hosts:
        rewritten = url.replace(parsed.netloc, "fxtwitter.com", 1)
        logger.debug(f"[feed] Rewrote Twitter URL: {url} → {rewritten}")
        return rewritten
    return url


def _is_twitter_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def _extract_tweet_id(url: str) -> str | None:
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else None


def _resolve_tweet_username(tweet_id: str) -> str | None:
    """Use Twitter oEmbed to resolve @username when URL is /i/status/<id>."""
    import urllib.request as _req

    oembed = f"https://publish.twitter.com/oembed?url=https://twitter.com/i/status/{tweet_id}&omit_script=true"
    try:
        r = _req.urlopen(_req.Request(oembed, headers={"User-Agent": "Mozilla/5.0"}), timeout=8)
        html = json.loads(r.read()).get("html", "")
        m = re.search(r"twitter\.com/(\w+)/status/", html)
        return m.group(1) if m else None
    except Exception:
        return None


def _fxtwitter_api(username: str, tweet_id: str) -> dict[str, Any] | None:
    """Fetch tweet data from api.fxtwitter.com JSON API. Returns tweet dict or None."""
    import urllib.request as _req

    api_url = f"https://api.fxtwitter.com/{username}/status/{tweet_id}"
    try:
        r = _req.urlopen(_req.Request(api_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10)
        return json.loads(r.read()).get("tweet")
    except Exception:
        return None


def _parse_fxtwitter_tweet(
    tweet: dict[str, Any],
) -> tuple[str, str, list[str], list[str]]:
    article = tweet.get("article") or {}
    author = tweet.get("author", {})

    title = (
        article.get("title")
        or tweet.get("raw_text", {}).get("text", "").strip()
        or f"@{author.get('screen_name', 'unknown')} on X"
    )

    preview = (article.get("preview_text") or "").strip()

    lines: list[str] = []
    for b in article.get("content", {}).get("blocks", []):
        text = b.get("text", "").strip()
        if not text:
            continue
        if b.get("type") == "blockquote":
            lines.append(f"> {text}")
        elif b.get("type") != "atomic":  # skip image/embed placeholders
            lines.append(text)
    body = "\n\n".join(lines)

    summary = preview or body[:500] or title
    key_insights = [s for s in body.split("\n\n")[:3] if s.strip()] if body else [summary]
    keywords = [author["screen_name"]] if author.get("screen_name") else []

    return title, summary, key_insights, keywords


def _fetch_twitter_content(
    url: str,
) -> tuple[str, str, list[str], list[str]] | None:
    """Fetch Twitter/X post content via fxtwitter JSON API.

    Handles both /username/status/ID and /i/status/ID URL formats.
    For /i/status/ links (no username in path), resolves the username via
    Twitter oEmbed before calling the API.

    Returns (title, summary, key_insights, keywords) or None on failure.
    """
    tweet_id = _extract_tweet_id(url)
    if not tweet_id:
        return None

    # Resolve username — present in normal URLs, absent in /i/status/ links
    path_parts = urlparse(url).path.strip("/").split("/")
    if len(path_parts) >= 3 and path_parts[1] == "status" and path_parts[0] not in ("i", ""):
        username = path_parts[0]
    else:
        username = _resolve_tweet_username(tweet_id)
        if not username:
            logger.warning(f"[feed] Could not resolve username for Twitter URL: {url}")
            return None

    tweet = _fxtwitter_api(username, tweet_id)
    if not tweet:
        logger.warning(f"[feed] fxtwitter API returned no data for @{username}/{tweet_id}")
        return None

    return _parse_fxtwitter_tweet(tweet)


def _detect_type(url: str) -> str:
    lower_url = url.lower()
    if "github.com" in lower_url:
        return "repo"
    if "arxiv.org" in lower_url or "doi.org" in lower_url or lower_url.endswith(".pdf"):
        return "paper"
    if any(token in lower_url for token in ["docs.", "/docs", "documentation", "readthedocs"]):
        return "docs"
    if any(token in lower_url for token in ["news.ycombinator.com", "reddit.com"]):
        return "post"
    if any(token in lower_url for token in ["x.com", "twitter.com"]):
        return "post"
    return "article"


def _extract_domain_tag(url: str) -> str | None:
    netloc = urlparse(url).netloc.split(":")[0].lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if not netloc:
        return None
    primary = netloc.split(".")[0]
    return primary or None


def _canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{netloc}{path}{query}"


def _find_existing_reference(references: list[dict[str, Any]], url: str) -> tuple[int, dict[str, Any]] | None:
    target = _canonical_url(url)
    for idx in range(len(references) - 1, -1, -1):
        ref = references[idx]
        existing_url = ref.get("url")
        if not isinstance(existing_url, str):
            continue
        if _canonical_url(existing_url) == target:
            return idx, ref
    return None


def _select_summary(extracted_text: str, article_summary: str | None) -> str:
    if article_summary:
        return _clean_whitespace(article_summary)
    sentences = _split_sentences(extracted_text)
    return _clean_whitespace(" ".join(sentences[:2]))


def _select_key_insights(extracted_text: str, fallback_summary: str) -> list[str]:
    sentences = _split_sentences(extracted_text)
    if sentences:
        return [s for s in sentences[:3]]
    if fallback_summary:
        return [fallback_summary]
    return ["Extracted content is available for review."]


def _base_sections(summary_ascii: str, key_insights: list[str]) -> list[str]:
    lines = [
        "",
        "## Summary",
        "",
        summary_ascii or "Summary unavailable; extraction succeeded but content was sparse.",
        "",
        "## Key Insights",
        "",
    ]

    for insight in key_insights:
        insight_ascii = _to_ascii(insight)
        if insight_ascii:
            lines.append(f"- {insight_ascii}")

    lines += [
        "",
        "## Relevance to Our Work",
        "",
        RELEVANCE_PLACEHOLDER,
        "",
        "## Applicable Patterns",
        "",
        PATTERNS_PLACEHOLDER,
        "",
    ]
    return lines


def _outbox_dir_from_references(references_dir: Path) -> Path:
    return references_dir.parent / "notepads" / "galaxy-outbox"


def _write_failure_notification(references_dir: Path, message: str, chat_id: int | None = None) -> None:
    outbox_dir = _outbox_dir_from_references(references_dir)
    outbox_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    ts_slug = timestamp.strftime("%Y%m%d-%H%M%S-%f")
    payload: dict[str, Any] = {
        "type": "notification",
        "severity": "warning",
        "from": "DeepWiki Enricher",
        "message": message,
        "timestamp": timestamp.isoformat(),
        "sent": False,
    }
    if chat_id is not None:
        payload["chat_id"] = chat_id
    (outbox_dir / f"deepwiki-enrich-{ts_slug}.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _build_enrichment_prompt(repo_url: str, owner: str, repo: str, reference_path: Path) -> str:
    return (
        "[Galaxy DeepWiki Enrichment Job]\n"
        "You are updating a reference file after /feed capture.\n"
        f"Repository: {owner}/{repo}\n"
        f"Repository URL: {repo_url}\n"
        f"Reference File: {reference_path}\n\n"
        "TASK:\n"
        "1) Use DeepWiki MCP tools to analyze the repository architecture and workflows.\n"
        "2) Edit the reference file in place.\n"
        "3) Replace placeholder text in these sections with concrete content:\n"
        f"   - Relevance placeholder: {RELEVANCE_PLACEHOLDER}\n"
        f"   - Patterns placeholder: {PATTERNS_PLACEHOLDER}\n"
        "4) Keep metadata header and existing Summary/Key Insights sections intact.\n"
        "5) Keep the document concise and actionable.\n"
        "6) If analysis is impossible, explain why in your final response and exit non-zero.\n"
    )


def _contains_deepwiki_errors(content: str) -> bool:
    """Check if reference content contains known DeepWiki error patterns.

    These appear when the enrichment agent writes error messages from DeepWiki
    directly into the reference file instead of meaningful analysis.
    """
    return any(pattern in content for pattern in DEEPWIKI_ERROR_PATTERNS)


def _clean_failed_enrichment(reference_path: Path) -> None:
    """Replace DeepWiki error content in reference with clean markers.

    Preserves header and Summary/Key Insights; replaces Relevance and
    Applicable Patterns sections with NOT_ENRICHED_MARKER.
    """
    content = reference_path.read_text(encoding="utf-8")

    # Replace Relevance section content (between ## Relevance and next ##)
    content = re.sub(
        r"""(## Relevance to Our Work\n\n).*?(\n\n## )""",
        rf"\1{NOT_ENRICHED_MARKER}\2",
        content,
        flags=re.DOTALL,
    )
    # Replace Applicable Patterns section content (between ## Applicable and EOF or next ##)
    content = re.sub(
        r"""(## Applicable Patterns\n\n).*""",
        rf"\1- {NOT_ENRICHED_MARKER}\n",
        content,
        flags=re.DOTALL,
    )

    reference_path.write_text(content, encoding="utf-8")


def _update_index_analysis(references_dir: Path, reference_path: Path, status: str) -> None:
    """Update the analysis field in index.json for a specific reference.

    Args:
        references_dir: Path to references directory
        reference_path: Path to the reference .md file
        status: New analysis status (deepwiki-enriched, deepwiki-not-indexed, etc.)
    """
    index_path = references_dir / "index.json"
    if not index_path.exists():
        return

    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    file_name = reference_path.name
    for ref in index_data.get("references", []):
        if ref.get("file") == file_name:
            ref["analysis"] = status
            break
    else:
        return  # Reference not found in index

    index_path.write_text(json.dumps(index_data, indent=2), encoding="utf-8")


async def _monitor_enrichment_job(
    process: asyncio.subprocess.Process,
    references_dir: Path,
    reference_path: Path,
    initial_reference: str,
    owner: str,
    repo: str,
    chat_id: int | None,
) -> None:
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=900)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        _write_failure_notification(
            references_dir,
            f"DeepWiki enrichment timed out for {owner}/{repo}.",
            chat_id,
        )
        return

    if process.returncode != 0:
        stderr_preview = stderr_bytes.decode("utf-8", errors="ignore").strip()
        stderr_preview = stderr_preview.splitlines()[-1] if stderr_preview else "Unknown error"
        _write_failure_notification(
            references_dir,
            (f"DeepWiki enrichment failed for {owner}/{repo} (exit {process.returncode}): {stderr_preview}"),
            chat_id,
        )
        return

    try:
        updated_reference = reference_path.read_text(encoding="utf-8")
    except OSError as exc:
        _write_failure_notification(
            references_dir,
            f"DeepWiki enrichment completed but reference file is unreadable for {owner}/{repo}: {exc}",
            chat_id,
        )
        _update_index_analysis(references_dir, reference_path, "deepwiki-error")
        return

    placeholders_present = RELEVANCE_PLACEHOLDER in updated_reference or PATTERNS_PLACEHOLDER in updated_reference

    if updated_reference == initial_reference or placeholders_present:
        stdout_preview = stdout_bytes.decode("utf-8", errors="ignore").strip()
        stdout_preview = stdout_preview.splitlines()[-1] if stdout_preview else "No details"
        _write_failure_notification(
            references_dir,
            (f"DeepWiki enrichment did not update {owner}/{repo} reference content. Details: {stdout_preview}"),
            chat_id,
        )
        _update_index_analysis(references_dir, reference_path, "deepwiki-unchanged")
        return

    # Check for error patterns baked into content (e.g., "Repository not found")
    if _contains_deepwiki_errors(updated_reference):
        _clean_failed_enrichment(reference_path)
        _write_failure_notification(
            references_dir,
            f"DeepWiki enrichment for {owner}/{repo} produced error content (repo likely not indexed). Cleaned reference.",
            chat_id,
        )
        _update_index_analysis(references_dir, reference_path, "deepwiki-not-indexed")
        return

    # Extract and save session ID for reuse
    repo_root = references_dir.parent.parent
    for line in (stdout_bytes.decode("utf-8", errors="ignore") or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            sid = data.get("sessionID")
            if sid:
                _save_enrichment_session_id(repo_root, sid)
                break
        except json.JSONDecodeError:
            continue

    # Enrichment succeeded with real content
    _update_index_analysis(references_dir, reference_path, "deepwiki-enriched")


async def _spawn_deepwiki_enrichment(
    repo_url: str,
    owner: str,
    repo: str,
    references_dir: Path,
    reference_path: Path,
    chat_id: int | None,
) -> bool:
    repo_root = references_dir.parent.parent
    prompt = _build_enrichment_prompt(repo_url, owner, repo, reference_path)
    initial_reference = reference_path.read_text(encoding="utf-8")
    opencode_binary, resolution_error = resolve_opencode_binary()
    if not opencode_binary:
        _write_failure_notification(
            references_dir,
            f"DeepWiki enrichment unavailable for {owner}/{repo}: {resolution_error}",
            chat_id,
        )
        return False

    try:
        clean_env = sanitize_opencode_env()

        # Build command with session reuse
        cmd = [opencode_binary, "run", "--format", "json"]
        session_id = _load_enrichment_session_id(repo_root)
        if session_id:
            cmd.extend(["--session", session_id])
        cmd.append(prompt)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(repo_root),
            env=clean_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        _write_failure_notification(
            references_dir,
            (f"DeepWiki enrichment failed for {owner}/{repo}: opencode binary was not executable in this runtime."),
            chat_id,
        )
        return False
    except Exception as exc:
        _write_failure_notification(
            references_dir,
            f"DeepWiki enrichment failed to start for {owner}/{repo}: {exc}",
            chat_id,
        )
        return False

    asyncio.create_task(
        _monitor_enrichment_job(
            process,
            references_dir,
            reference_path,
            initial_reference,
            owner,
            repo,
            chat_id,
        )
    )
    return True


def _validate_index(index_path: Path) -> bool:
    """Validate index.json integrity.

    Returns True if valid, False if corrupted.
    JSON degrades catastrophically - one missing comma breaks the entire file.
    """
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        assert isinstance(data.get("references"), list), "references must be a list"
        for ref in data["references"]:
            required = [
                "slug",
                "url",
                "title",
                "file",
                "type",
                "tags",
                "shared_at",
                "shared_via",
            ]
            missing = [k for k in required if k not in ref]
            assert not missing, f"missing required fields: {missing}"
        return True
    except (json.JSONDecodeError, AssertionError, KeyError) as e:
        logger.error(f"index.json validation failed: {e}")
        return False


def _ensure_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        data = {"version": "1.0", "references": []}
        index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    return json.loads(index_path.read_text(encoding="utf-8"))


def _load_runtime_config(references_dir: Path) -> dict[str, Any] | None:
    config_path = references_dir.parent.parent / ".galaxy" / "config.json"
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Failed to load Galaxy config from {config_path}: {exc}")
        return None
    if isinstance(data, dict):
        return data
    return None


def _unique_slug(references_dir: Path, slug: str) -> str:
    candidate = slug
    counter = 2
    while (references_dir / f"{candidate}.md").exists():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


async def process_feed(
    url: str,
    note: str | None,
    via: str,
    references_dir: Path,
    config: dict[str, Any] | None = None,
    chat_id: int | None = None,
) -> dict[str, Any]:
    try:
        references_dir.mkdir(parents=True, exist_ok=True)
        index_path = references_dir / "index.json"
        runtime_config = config or _load_runtime_config(references_dir)

        title: str
        summary: str
        key_insights: list[str]
        keywords: list[str] = []

        if _is_twitter_url(url):
            twitter_content = _fetch_twitter_content(url)
            if twitter_content:
                title, summary, key_insights, keywords = twitter_content
                logger.info(f"[feed] fxtwitter API: {url!r} → {title!r}")
            else:
                fetch_url = _rewrite_twitter_url(url)
                downloaded = trafilatura.fetch_url(fetch_url)
                if not downloaded:
                    return {"error": "Failed to fetch Twitter URL (API and scraping both failed)"}
                metadata = trafilatura.extract_metadata(downloaded)
                extracted_text = (
                    trafilatura.extract(
                        downloaded,
                        include_comments=False,
                        include_tables=False,
                        include_links=False,
                    )
                    or ""
                )
                title = metadata.title if metadata and metadata.title else url
                if "JavaScript is not available" in title:
                    return {
                        "error": "Twitter content is JS-gated; fxtwitter API also failed. Post may be deleted or private."
                    }
                article_summary: str | None = None
                try:
                    np_article = Article(url)
                    np_article.download()
                    np_article.parse()
                    try:
                        np_article.nlp()
                    except Exception:
                        pass
                    article_summary = np_article.summary if np_article.summary else None
                    if isinstance(np_article.keywords, list):
                        keywords = [kw for kw in np_article.keywords if kw]
                except Exception:
                    pass
                summary = _select_summary(extracted_text, article_summary)
                key_insights = _select_key_insights(extracted_text, summary)
        else:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return {"error": "Failed to fetch URL"}
            metadata = trafilatura.extract_metadata(downloaded)
            extracted_text = (
                trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                    include_links=False,
                )
                or ""
            )
            title = metadata.title if metadata and metadata.title else url
            article_summary = None
            try:
                np_article = Article(url)
                np_article.download()
                np_article.parse()
                try:
                    np_article.nlp()
                except Exception:
                    pass
                article_summary = np_article.summary if np_article.summary else None
                if isinstance(np_article.keywords, list):
                    keywords = [kw for kw in np_article.keywords if kw]
            except Exception:
                pass
            summary = _select_summary(extracted_text, article_summary)
            key_insights = _select_key_insights(extracted_text, summary)

        ref_type = _detect_type(url)
        tags: set[str] = set()
        for keyword in keywords:
            clean_keyword = _to_ascii(keyword.lower()).strip()
            # Filter: min 3 chars, not in stopwords
            if clean_keyword and len(clean_keyword) >= 3 and clean_keyword not in STOPWORDS:
                tags.add(clean_keyword)

        type_tag = ref_type
        if type_tag:
            tags.add(type_tag)

        domain_tag = _extract_domain_tag(url)
        if domain_tag:
            tags.add(domain_tag)

        if "github.com" in url.lower():
            tags.add("github")
        if "arxiv.org" in url.lower():
            tags.add("arxiv")

        # Cap at 15 tags to prevent explosion
        tag_list = sorted(tags)[:15]

        index_data = _ensure_index(index_path)
        references = index_data.setdefault("references", [])
        existing_match = _find_existing_reference(references, url)

        timestamp = datetime.now(timezone.utc)
        date_prefix = timestamp.strftime("%Y-%m-%d")
        slug_base = _slugify(title)

        if existing_match:
            existing_idx, existing_ref = existing_match
            slug = str(existing_ref.get("slug") or _unique_slug(references_dir, f"{date_prefix}-{slug_base}"))
            file_name = str(existing_ref.get("file") or f"{slug}.md")
        else:
            existing_idx = None
            existing_ref = None
            slug = _unique_slug(references_dir, f"{date_prefix}-{slug_base}")
            file_name = f"{slug}.md"

        title_ascii = _to_ascii(title)
        summary_ascii = _to_ascii(summary)
        note_ascii = _to_ascii(note or "")

        # Initialize metadata for reference entry
        reference_metadata: dict[str, Any] = {}

        # Build markdown header
        markdown_lines = [
            f"# {title_ascii or 'Untitled'}",
            "",
            f"**Source**: {url}",
            f"**Type**: {ref_type}",
            f"**Ingested**: {timestamp.isoformat().replace('+00:00', 'Z')}",
            f"**Tags**: {', '.join(tag_list)}",
        ]

        markdown_lines.append(f"**Note**: {note_ascii or 'None'}")
        markdown_lines.append(f"**Via**: {via}")
        markdown_lines.append("")
        markdown_lines.append("---")
        markdown_lines += _base_sections(summary_ascii, key_insights)

        file_path = references_dir / file_name
        file_path.write_text("\n".join(markdown_lines), encoding="utf-8")

        deepwiki_enabled = bool(
            "github.com" in url.lower()
            and runtime_config
            and runtime_config.get("features", {}).get("GALAXY_DEEPWIKI_ENABLED")
        )
        if deepwiki_enabled:
            try:
                owner, repo = _extract_owner_repo(url)
                started = await _spawn_deepwiki_enrichment(
                    url,
                    owner,
                    repo,
                    references_dir,
                    file_path,
                    chat_id,
                )
                reference_metadata["analysis"] = "deepwiki-pending" if started else "deepwiki-unavailable"
            except Exception as exc:
                logger.warning(f"DeepWiki enrichment dispatch failed for {url}: {exc}")
                reference_metadata["analysis"] = "deepwiki-dispatch-failed"
                _write_failure_notification(
                    references_dir,
                    f"DeepWiki enrichment failed to dispatch for {url}: {exc}",
                    chat_id,
                )

        shared_at = timestamp.isoformat().replace("+00:00", "Z")
        reference_entry = {
            "slug": slug,
            "url": url,
            "title": title_ascii or "Untitled",
            "type": ref_type,
            "tags": tag_list,
            "note": note_ascii or None,
            "shared_at": shared_at,
            "shared_via": via,
            "file": file_name,
            **reference_metadata,  # Add analysis metadata if present
        }

        if existing_ref:
            created_at = existing_ref.get("created_at") or existing_ref.get("shared_at")
            if created_at:
                reference_entry["created_at"] = created_at
            reference_entry["updated_at"] = shared_at
            references[existing_idx] = reference_entry
        else:
            reference_entry["created_at"] = shared_at
            references.append(reference_entry)

        # Write and validate immediately
        index_path.write_text(json.dumps(index_data, indent=2), encoding="utf-8")

        if not _validate_index(index_path):
            # Index corrupted - restore previous state if possible
            logger.error(f"Index validation failed after upserting {slug}")
            if existing_ref is not None and existing_idx is not None:
                references[existing_idx] = existing_ref
            else:
                references.pop()
            index_path.write_text(json.dumps(index_data, indent=2), encoding="utf-8")
            return {
                "slug": slug,
                "title": title_ascii or "Untitled",
                "tags": tag_list,
                "type": ref_type,
                "file_path": str(file_path),
                "warning": "Reference .md created but index update failed (validation error)",
            }

        return {
            "slug": slug,
            "title": title_ascii or "Untitled",
            "tags": tag_list,
            "type": ref_type,
            "file_path": str(file_path),
            "updated_existing": existing_ref is not None,
        }
    except Exception as exc:
        return {"error": str(exc)}
