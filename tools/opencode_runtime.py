from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path


def resolve_opencode_binary(
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
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
                "Set it to an absolute opencode binary path."
            ),
        )

    resolved_default = shutil.which("opencode")
    if resolved_default:
        return resolved_default, None

    home_candidates = [
        Path.home() / ".opencode/bin/opencode",
        Path.home() / ".local/bin/opencode",
    ]
    for candidate in home_candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate), None

    return (
        None,
        (
            "opencode CLI is not available on PATH for the Galaxy runtime. "
            "Install OpenCode CLI or set GALAXY_OPENCODE_BIN to an absolute binary path."
        ),
    )


def sanitize_opencode_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = env if env is not None else os.environ
    return {key: value for key, value in source.items() if key != "OPENCODE" and not key.startswith("OPENCODE_")}
