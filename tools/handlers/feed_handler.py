import asyncio
import importlib
import re
from datetime import datetime, timezone

common = importlib.import_module("handlers.common")


GITHUB_URL_PATTERN = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+")


def feature_enabled(config):
    return bool(config.get("features", {}).get("GALAXY_DEEPWIKI_ENABLED", False))


async def maybe_handle_github_reference(update, context, config, machine_config):
    if not feature_enabled(config):
        return False

    text = (update.message.text or "").strip()
    if not text:
        return False

    match = GITHUB_URL_PATTERN.search(text)
    if not match:
        return False

    repo_url = match.group(0)
    await update.message.reply_text(
        "🔍 Analyzing repository... (this may take a minute)"
    )
    asyncio.create_task(_analyze_repo(update, config, machine_config, repo_url))
    return True


async def _analyze_repo(update, config, machine_config, repo_url):
    timeout_seconds = int(config.get("deepwiki", {}).get("timeout_seconds", 30))
    try:
        owner, repo = _repo_from_url(repo_url)
    except ValueError as exc:
        await update.message.reply_text(f"❌ Invalid GitHub URL: {exc}")
        return

    try:
        deepwiki_client = importlib.import_module("deepwiki_client")
    except ModuleNotFoundError:
        await update.message.reply_text(
            "❌ DeepWiki MCP not available. Install with: pip install deepwiki-mcp"
        )
        return

    try:
        client = deepwiki_client.DeepWikiClient()
        structure = await asyncio.wait_for(
            client.read_wiki_structure(f"{owner}/{repo}"), timeout=timeout_seconds
        )
        refs_dir = common.references_dir_for_machine(machine_config)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        file_name = f"{date}-{repo}-deepwiki-{stamp}.md"
        body = _format_structure(structure)
        ref_path = common.write_reference_markdown(
            refs_dir / file_name,
            f"{owner}/{repo} DeepWiki Summary",
            repo_url,
            body,
            {"Tool": "deepwiki", "Repo": f"{owner}/{repo}"},
        )
        await update.message.reply_text(
            f"✅ Added: {owner}/{repo} analysis\n📁 Saved to {ref_path.name}"
        )
    except asyncio.TimeoutError:
        await update.message.reply_text("⏳ Repository analysis timed out")
    except Exception as exc:
        await update.message.reply_text(f"❌ Analysis failed: {exc}")


def _repo_from_url(url):
    parts = url.rstrip("/").split("/")
    if len(parts) < 5:
        raise ValueError("expected owner/repo segment")
    return parts[-2], parts[-1]


def _format_structure(structure):
    if isinstance(structure, dict):
        lines = ["## Structure", ""]
        for key, value in structure.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)
    if isinstance(structure, list):
        lines = ["## Structure", ""]
        lines.extend(f"- {item}" for item in structure)
        return "\n".join(lines)
    return str(structure)
