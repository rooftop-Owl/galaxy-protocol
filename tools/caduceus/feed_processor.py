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


def _to_ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def _slugify(value: str) -> str:
    ascii_value = _to_ascii(value).lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value)
    ascii_value = re.sub(r"-+", "-", ascii_value).strip("-")
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
        process = await asyncio.create_subprocess_exec(
            opencode_binary,
            "run",
            "--format",
            "json",
            prompt,
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

        article_summary: str | None = None
        keywords: list[str] = []
        try:
            article = Article(url)
            article.download()
            article.parse()
            try:
                article.nlp()
            except Exception:
                pass
            article_summary = article.summary if article.summary else None
            if isinstance(article.keywords, list):
                keywords = [keyword for keyword in article.keywords if keyword]
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
