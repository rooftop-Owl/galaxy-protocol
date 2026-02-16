"""Paper ingestion handler — DOI detection + Zotero bridge.

Detects academic papers from DOIs, URLs, and page content,
then adds them to Zotero via research-zotero module.
"""

from __future__ import annotations

import os
import re
from typing import Any

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s&?#]+", re.IGNORECASE)
ARXIV_PATTERN = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})(v\d+)?", re.IGNORECASE)
DOI_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s&?#]+)",
    re.IGNORECASE,
)

_PUNCTUATION_STRIP = ".,;:)]}>\"'"


def _clean_doi_candidate(value: str) -> str:
    cleaned = (value or "").strip().lstrip("<({\"' ")
    return cleaned.rstrip(_PUNCTUATION_STRIP)


def extract_doi(input_str: str) -> str | None:
    if not input_str:
        return None

    text = input_str.strip()
    if not text:
        return None

    doi_url_match = DOI_URL_PATTERN.search(text)
    if doi_url_match:
        return _clean_doi_candidate(doi_url_match.group(1))

    arxiv_match = ARXIV_PATTERN.search(text)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        return f"10.48550/arXiv.{arxiv_id}"

    doi_match = DOI_PATTERN.search(text)
    if doi_match:
        return _clean_doi_candidate(doi_match.group(0))

    return None


def detect_paper_url(url: str) -> bool:
    if not url:
        return False

    lower = url.strip().lower()
    if not lower:
        return False

    if lower.endswith(".pdf") or ".pdf?" in lower:
        return True

    quick_domains = (
        "arxiv.org",
        "doi.org",
        "dx.doi.org",
        "scholar.google.com",
        "science.org",
        "pnas.org",
        "springer.com",
        "wiley.com",
        "iopscience.iop.org",
        "journals.aps.org",
    )
    if any(domain in lower for domain in quick_domains):
        return True

    if "nature.com/articles/" in lower:
        return True

    return False


def _structured_success(raw: dict[str, Any], note: str | None) -> dict[str, Any]:
    return {
        "title": raw.get("title") or "Untitled",
        "key": raw.get("key") or "",
        "doi": raw.get("doi") or "",
        "authors": raw.get("authors") or [],
        "auto_tags": raw.get("auto_tags") or [],
        "auto_collections": raw.get("auto_collections") or [],
        "note": note,
    }


async def add_paper(
    identifier: str,
    note: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or {}
    enabled = bool(cfg.get("features", {}).get("GALAXY_ZOTERO_ENABLED", False))
    if not enabled:
        return {"error": "Zotero integration is disabled (GALAXY_ZOTERO_ENABLED=false)"}

    if not os.environ.get("ZOTERO_USER_ID") or not os.environ.get("ZOTERO_API_KEY"):
        return {"error": ("Zotero credentials missing. Set ZOTERO_USER_ID and ZOTERO_API_KEY environment variables.")}

    doi = extract_doi(identifier)
    is_paper_url = detect_paper_url(identifier)

    if not doi and not is_paper_url:
        return {"error": "Could not detect DOI or paper URL from input"}

    try:
        from tools.research.zotero_web import ZoteroWeb
    except ModuleNotFoundError:
        return {"error": ("research-zotero module not available: cannot import tools.research.zotero_web")}

    zotero = ZoteroWeb()
    try:
        zotero.connect()
        if doi:
            result = zotero.add_by_doi(doi, auto_tag=True, auto_classify=True)
        else:
            result = zotero.add_by_url(identifier, auto_tag=True, auto_classify=True)
        return _structured_success(result, note)
    except Exception as exc:
        return {"error": f"Failed to add paper to Zotero: {exc}"}
    finally:
        try:
            zotero.close()
        except Exception:
            pass


def _format_authors(authors: Any) -> str:
    if isinstance(authors, str) and authors.strip():
        return authors.strip()

    if isinstance(authors, list) and authors:
        if all(isinstance(item, str) for item in authors):
            return ", ".join(item for item in authors if item)

        names = []
        for item in authors:
            if isinstance(item, dict):
                first = str(item.get("firstName") or "").strip()
                last = str(item.get("lastName") or "").strip()
                full = f"{first} {last}".strip()
                if full:
                    names.append(full)
            elif isinstance(item, str) and item.strip():
                names.append(item.strip())

        if names:
            return ", ".join(names)

    return "Unknown"


def _format_list(value: Any) -> str:
    if isinstance(value, list):
        rendered = [str(item) for item in value if str(item).strip()]
        return ", ".join(rendered) if rendered else "none"
    if value:
        return str(value)
    return "none"


def format_result(result: dict[str, Any]) -> str:
    error = result.get("error")
    if error:
        return f"✗ {error}"

    title = str(result.get("title") or "Untitled")
    authors = _format_authors(result.get("authors"))
    doi = str(result.get("doi") or "none")
    tags = _format_list(result.get("auto_tags"))
    collections = _format_list(result.get("auto_collections"))

    return (
        f"✓ Added to Zotero: {title}\n"
        f"  Authors: {authors}\n"
        f"  DOI: {doi}\n"
        f"  Auto-tagged: {tags}\n"
        f"  Classified to: {collections}"
    )
