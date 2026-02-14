"""
DeepWiki GitHub repository analyzer with circuit breaker.

Extracts architectural insights from GitHub repositories using DeepWiki MCP.
Implements tiered retrieval and exponential backoff for rate limiting.
"""

import asyncio
import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)

# Diagnostic questions for architectural analysis
DIAGNOSTIC_QUESTIONS = [
    "What is the core problem this repo solves?",
    "What are the primary design patterns and architectural decisions?",
    "What are the key abstractions that could be reused?",
    "How does the main workflow or data flow work?",
]


class CircuitBreaker:
    """Per-client circuit breaker with exponential backoff."""

    def __init__(self):
        self.failure_count: int = 0
        self.last_failure_time: float | None = None
        self.backoff_delays: list[int] = [60, 120, 240]

    def get_delay(self) -> float | None:
        """Get current backoff delay with jitter, or None if no delay needed."""
        if self.failure_count == 0:
            return None

        if self.failure_count > len(self.backoff_delays):
            # Max backoff reached
            delay_index = len(self.backoff_delays) - 1
        else:
            delay_index = self.failure_count - 1

        base_delay = self.backoff_delays[delay_index]
        jitter = random.uniform(0, 10)  # 0-10 seconds jitter
        return base_delay + jitter

    def should_wait(self) -> tuple[bool, float]:
        """Check if we should wait before next request.

        Returns:
            (should_wait, delay_seconds)
        """
        if self.failure_count == 0:
            return False, 0.0

        delay = self.get_delay()
        if delay is None:
            return False, 0.0

        elapsed = time.time() - (self.last_failure_time or 0)
        if elapsed < delay:
            remaining = delay - elapsed
            return True, remaining

        return False, 0.0

    def record_failure(self):
        """Record a rate limit failure."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(
            f"Circuit breaker: failure #{self.failure_count}, "
            f"backoff delay: {self.get_delay():.1f}s"
        )

    def reset(self):
        """Reset circuit breaker after successful request."""
        if self.failure_count > 0:
            logger.info("Circuit breaker: reset after successful request")
        self.failure_count = 0
        self.last_failure_time = None


def get_deepwiki_client():
    """Get DeepWiki client. Returns None if unavailable.

    In OpenCode environment, this imports the MCP-provided client.
    In local testing, this returns None for graceful fallback.
    """
    try:
        import importlib

        deepwiki_client = importlib.import_module("deepwiki_client")
        return deepwiki_client.DeepWikiClient()
    except (ImportError, ModuleNotFoundError, Exception) as exc:
        logger.debug(f"DeepWiki client unavailable: {exc}")
        return None


async def analyze_repo(
    owner: str, repo: str, config: dict[str, Any]
) -> dict[str, Any] | None:
    """Analyze GitHub repository using DeepWiki.

    Args:
        owner: Repository owner
        repo: Repository name
        config: Configuration dict with deepwiki settings

    Returns:
        Dict with keys: problem, architecture, abstractions, workflow, structure
        None on failure (not indexed, timeout, rate limited)
    """
    # Check feature flag
    if not config.get("features", {}).get("GALAXY_DEEPWIKI_ENABLED", False):
        logger.debug("DeepWiki feature disabled")
        return None

    # Get DeepWiki client
    client = get_deepwiki_client()
    if client is None:
        logger.warning("DeepWiki client not available")
        return None

    # Get timeout from config
    timeout_seconds = int(config.get("deepwiki", {}).get("timeout_seconds", 60))

    # Create circuit breaker
    circuit_breaker = CircuitBreaker()

    repo_path = f"{owner}/{repo}"

    try:
        # Check circuit breaker
        should_wait, delay = circuit_breaker.should_wait()
        if should_wait:
            logger.warning(
                f"Circuit breaker active for {repo_path}, "
                f"waiting {delay:.1f}s before retry"
            )
            await asyncio.sleep(delay)

        # Phase 1: Get structure (lightweight)
        try:
            structure = await asyncio.wait_for(
                client.read_wiki_structure(repo_path), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(f"DeepWiki structure timeout for {repo_path}")
            return None
        except Exception as exc:
            # Check for rate limiting
            if "429" in str(exc) or "rate limit" in str(exc).lower():
                circuit_breaker.record_failure()
                logger.warning(f"DeepWiki rate limited for {repo_path}: {exc}")
                return None

            # Repository not indexed
            logger.warning(f"DeepWiki structure failed for {repo_path}: {exc}")
            return None

        # Phase 2: Ask diagnostic questions
        answers = {}
        question_keys = ["problem", "architecture", "abstractions", "workflow"]

        for key, question in zip(question_keys, DIAGNOSTIC_QUESTIONS):
            try:
                answer = await asyncio.wait_for(
                    client.ask_question(repo_path, question),
                    timeout=timeout_seconds,
                )
                answers[key] = answer
                circuit_breaker.reset()
            except asyncio.TimeoutError:
                logger.warning(f"DeepWiki question timeout for {repo_path}: {question}")
                answers[key] = "Timeout - unable to retrieve"
            except Exception as exc:
                # Check for rate limiting
                if "429" in str(exc) or "rate limit" in str(exc).lower():
                    circuit_breaker.record_failure()
                    logger.warning(
                        f"DeepWiki rate limited on question for {repo_path}: {exc}"
                    )
                    # Return partial results if we got some answers
                    if answers:
                        return {**answers, "structure": structure}
                    return None

                logger.warning(
                    f"DeepWiki question failed for {repo_path} ({question}): {exc}"
                )
                answers[key] = f"Error: {exc}"

        # Return complete analysis
        return {**answers, "structure": structure}

    except Exception as exc:
        logger.error(f"Unexpected error analyzing {repo_path}: {exc}")
        return None
