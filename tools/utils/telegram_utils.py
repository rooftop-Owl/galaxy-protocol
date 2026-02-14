"""
Telegram utility functions for message handling.

Extracted from bot.py to enable reuse across handlers.
"""


def split_message(text: str, max_length: int = 4000) -> list[str]:
    """
    Split a message into chunks that fit within Telegram's 4096 character limit.

    Uses 4000 as default max_length to leave safety margin for formatting.
    Attempts to split at newlines to preserve message structure.

    Args:
        text: The message text to split
        max_length: Maximum length per chunk (default: 4000)

    Returns:
        List of message chunks, each <= max_length characters

    Example:
        >>> long_text = "Line 1\\n" * 1000
        >>> chunks = split_message(long_text)
        >>> all(len(chunk) <= 4000 for chunk in chunks)
        True
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at newline before max_length
        split_at = remaining.rfind("\n", 0, max_length)

        # If no newline found in first half, fall back to hard split
        if split_at < max_length // 2:
            split_at = max_length

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    return chunks
