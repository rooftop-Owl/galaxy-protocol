from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

# Binary names to search, in priority order.
# opencode is the primary CLI; claude is the Anthropic CLI fallback.
_BINARY_NAMES = ["opencode", "claude"]

_HOME_CANDIDATES = [
    ".opencode/bin/opencode",
    ".local/bin/opencode",
    ".local/bin/claude",
    ".claude/local/claude",
]


def resolve_opencode_binary(
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve an agent CLI binary (opencode or claude).

    Resolution order:
    1. GALAXY_OPENCODE_BIN env var (explicit override)
    2. PATH lookup for opencode, then claude
    3. Well-known home directory candidates

    Returns:
        (binary_path, None) on success, (None, error_message) on failure.
    """
    runtime_env = env if env is not None else os.environ
    override = runtime_env.get("GALAXY_OPENCODE_BIN", "").strip()
    if override:
        expanded = str(Path(override).expanduser())
        if Path(expanded).is_file() and os.access(expanded, os.X_OK):
            return expanded, None
        resolved_override = shutil.which(override)
        if resolved_override:
            return resolved_override, None
        return (
            None,
            (
                f"GALAXY_OPENCODE_BIN is set to '{override}' but no executable was found. "
                "Set it to an absolute path to opencode or claude CLI."
            ),
        )

    # PATH lookup: try each binary name
    for name in _BINARY_NAMES:
        resolved = shutil.which(name)
        if resolved:
            return resolved, None

    # Well-known home directory candidates
    home = Path.home()
    for rel_path in _HOME_CANDIDATES:
        candidate = home / rel_path
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate), None

    searched = ", ".join(_BINARY_NAMES)
    paths_checked = ", ".join(str(home / p) for p in _HOME_CANDIDATES)
    return (
        None,
        (
            f"No agent CLI found. Searched PATH for: {searched}. "
            f"Also checked: {paths_checked}. "
            "Install opencode or claude CLI, or set GALAXY_OPENCODE_BIN."
        ),
    )


def sanitize_opencode_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = env if env is not None else os.environ
    return {key: value for key, value in source.items() if key != "OPENCODE" and not key.startswith("OPENCODE_")}
