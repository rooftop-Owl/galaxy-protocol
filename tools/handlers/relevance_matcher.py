"""
Relevance matcher for cross-referencing GitHub repo insights with astraeus aspects.

Matches repository insights against predefined astraeus domain keywords to determine
relevance and confidence level.
"""

from typing import Any

# Aspect keyword definitions
ASTRAEUS_ASPECTS = {
    "galaxy_protocol": ["feed", "digest", "stars", "telegram", "caduceus", "hermes"],
    "orchestration": [
        "sisyphus",
        "atlas",
        "prometheus",
        "metis",
        "hephaestus",
        "delegate",
    ],
    "cost_optimization": ["model", "routing", "ollama", "local", "token", "budget"],
    "brain_core": ["pain-point", "proposal", "journal", "athena", "daedalus", "minos"],
    "modules": ["dart", "climada", "zotero", "galaxy", "scientific"],
}


def match_relevance(repo_insights: dict[str, Any] | None) -> dict[str, Any]:
    """
    Cross-reference repo insights with astraeus aspects.

    Uses keyword matching to identify which astraeus domains are relevant to the
    analyzed repository. Returns matched aspects, confidence level, and reasoning.

    Args:
        repo_insights: Dict with keys: problem, architecture, abstractions, workflow
                      Can be None if DeepWiki analysis failed

    Returns:
        {
            "aspects": ["galaxy_protocol", "cost_optimization"],
            "confidence": "high" | "medium" | "low" | "none",
            "reasoning": "Repo mentions 'telegram' and 'scheduling'..."
        }

    Confidence levels:
        - high: ≥3 keyword matches across insights
        - medium: 2 keyword matches
        - low: 1 keyword match
        - none: 0 matches
    """
    # Handle missing or empty insights
    if not repo_insights:
        return {
            "aspects": [],
            "confidence": "none",
            "reasoning": "No insights available for analysis",
        }

    # Combine all insight text for keyword matching
    insight_text = _combine_insights(repo_insights)

    # Match keywords against aspects
    matches = _find_keyword_matches(insight_text)

    # Calculate confidence based on total keyword count
    total_matches = sum(len(keywords) for keywords in matches.values())
    confidence = _calculate_confidence(total_matches)

    # Generate reasoning
    reasoning = _generate_reasoning(matches, repo_insights)

    return {
        "aspects": list(matches.keys()),
        "confidence": confidence,
        "reasoning": reasoning,
    }


def _combine_insights(insights: dict[str, Any]) -> str:
    """
    Combine all insight values into a single searchable text.

    Args:
        insights: Dict with keys like problem, architecture, abstractions, workflow

    Returns:
        Lowercase combined text for case-insensitive matching
    """
    text_parts = []

    for key in ["problem", "architecture", "abstractions", "workflow"]:
        value = insights.get(key, "")
        if value:
            text_parts.append(str(value))

    return " ".join(text_parts).lower()


def _find_keyword_matches(text: str) -> dict[str, list[str]]:
    """
    Find which keywords from each aspect appear in the text.

    Args:
        text: Lowercase combined insight text

    Returns:
        Dict mapping aspect names to lists of matched keywords
        Example: {"galaxy_protocol": ["telegram", "feed"], "orchestration": ["delegate"]}
    """
    matches: dict[str, list[str]] = {}

    for aspect, keywords in ASTRAEUS_ASPECTS.items():
        matched_keywords = [kw for kw in keywords if kw.lower() in text]

        if matched_keywords:
            matches[aspect] = matched_keywords

    return matches


def _calculate_confidence(total_matches: int) -> str:
    """
    Calculate confidence level based on total keyword matches.

    Args:
        total_matches: Total number of keyword matches across all aspects

    Returns:
        "high" | "medium" | "low" | "none"
    """
    if total_matches >= 3:
        return "high"
    elif total_matches == 2:
        return "medium"
    elif total_matches == 1:
        return "low"
    else:
        return "none"


def _generate_reasoning(matches: dict[str, list[str]], insights: dict[str, Any]) -> str:
    """
    Generate human-readable reasoning explaining the matches.

    Args:
        matches: Dict mapping aspect names to matched keywords
        insights: Original insights dict for section references

    Returns:
        Reasoning string explaining which keywords matched and where
    """
    if not matches:
        return "No keyword matches found in repository insights"

    # Build reasoning parts
    parts = []

    for aspect, keywords in matches.items():
        # Find which section(s) contain these keywords
        sections = _find_keyword_sections(keywords, insights)

        keyword_list = ", ".join(f"'{kw}'" for kw in keywords)
        section_list = ", ".join(sections) if sections else "insights"

        parts.append(f"{keyword_list} (in {section_list})")

    # Combine into final reasoning
    aspect_list = ", ".join(matches.keys())
    keyword_summary = "; ".join(parts)

    return f"Repo mentions {keyword_summary}, indicating relevance to {aspect_list}"


def _find_keyword_sections(keywords: list[str], insights: dict[str, Any]) -> list[str]:
    """
    Find which insight sections contain the given keywords.

    Args:
        keywords: List of keywords to search for
        insights: Dict with keys like problem, architecture, abstractions, workflow

    Returns:
        List of section names where keywords were found
    """
    sections = []

    for section in ["problem", "architecture", "abstractions", "workflow"]:
        text = str(insights.get(section, "")).lower()

        if any(kw.lower() in text for kw in keywords):
            sections.append(section)

    return sections
