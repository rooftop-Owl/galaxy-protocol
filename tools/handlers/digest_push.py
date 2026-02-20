import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import importlib
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
split_message = importlib.import_module("utils.telegram_utils").split_message

logger = logging.getLogger(__name__)

MIN_REFS_FOR_AUTO_DIGEST = 3


def _get_last_digest_date() -> str | None:
    index_path = Path(".sisyphus/digests/index.json")
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        digests = sorted(data.get("digests", []), key=lambda d: d.get("date", ""), reverse=True)
        return digests[0]["date"] if digests else None
    except Exception:
        return None


def _count_new_refs(since_date: str | None) -> int:
    index_path = Path(".sisyphus/references/index.json")
    if not index_path.exists():
        return 0
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if since_date is None:
            return len(data.get("references", []))
        cutoff = since_date + "T23:59:59Z"
        return sum(1 for ref in data.get("references", []) if ref.get("shared_at", "") > cutoff)
    except Exception:
        return 0


async def _spawn_digest_creation() -> bool:
    opencode_runtime = importlib.import_module("opencode_runtime")
    opencode_binary, error = opencode_runtime.resolve_opencode_binary()
    if not opencode_binary:
        logger.warning(f"[digest] Auto-create skipped: opencode not found: {error}")
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            opencode_binary,
            "run",
            "--format",
            "json",
            "/digest",
            cwd=str(Path.cwd()),
            env=opencode_runtime.sanitize_opencode_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("[digest] Auto-create timed out after 5 minutes")
            return False
        if process.returncode != 0:
            logger.warning(f"[digest] Auto-create exited with code {process.returncode}")
            return False
        logger.info("[digest] Auto-create completed successfully")
        return True
    except Exception as exc:
        logger.warning(f"[digest] Auto-create failed: {exc}")
        return False


def setup_digest_scheduler(config, bot, digest_loader):
    if not config.get("features", {}).get("GALAXY_DIGEST_PUSH_ENABLED", False):
        return None

    asyncio_scheduler = importlib.import_module("apscheduler.schedulers.asyncio")

    scheduler = asyncio_scheduler.AsyncIOScheduler()
    scheduler.add_job(
        send_daily_digest,
        "cron",
        hour=int(config.get("digest_push", {}).get("hour", 9)),
        minute=int(config.get("digest_push", {}).get("minute", 0)),
        timezone=ZoneInfo("Asia/Seoul"),
        args=[bot, config, digest_loader],
        id="galaxy-daily-digest",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


async def send_daily_digest(bot, config, digest_loader):
    min_refs = config.get("digest_push", {}).get("min_refs_for_auto_digest", MIN_REFS_FOR_AUTO_DIGEST)
    last_date = _get_last_digest_date()
    new_count = _count_new_refs(last_date)
    if new_count >= min_refs:
        logger.info(f"[digest] {new_count} new refs since {last_date} — auto-creating digest")
        await _spawn_digest_creation()
    else:
        logger.info(f"[digest] {new_count} new refs (threshold {min_refs}) — skipping auto-create")

    digest_data = digest_loader()
    message = format_digest_message(digest_data)
    subscribers = config.get("digest_push", {}).get("digest_subscribers", [])

    for chat_id in subscribers:
        chunks = split_message(message, max_length=4000)
        for chunk in chunks:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")


def format_digest_message(digest_data):
    schema_version = digest_data.get("schema_version", "1.0")

    if schema_version == "2.0":
        digest_data = _transform_v2_to_v1(digest_data)

    patterns = digest_data.get("patterns", [])
    references = digest_data.get("references", [])
    actions = digest_data.get("actions", [])

    lines = [f"📊 *Daily Digest* ({datetime.now().strftime('%Y-%m-%d')})", ""]
    if patterns:
        lines.append(f"🔍 *New Patterns* ({len(patterns)}):")
        lines.extend(f"- {item.get('name', item)}" for item in patterns[:3])
        lines.append("")
    if references:
        lines.append(f"📚 *New References* ({len(references)}):")
        lines.extend(f"- {item.get('title', item)}" for item in references[:5])
        lines.append("")
    if actions:
        lines.append(f"💡 *Action Items* ({len(actions)}):")
        lines.extend(f"- {item.get('description', item)}" for item in actions[:3])
        lines.append("")

    lines.append("👉 /digest for full details")
    return "\n".join(lines)


def _transform_v2_to_v1(v2_data):
    patterns = _extract_patterns_from_diagnostic(v2_data)
    references = _extract_references_from_diagnostic(v2_data)
    actions = _extract_actions_from_diagnostic(v2_data)

    return {
        "patterns": patterns,
        "references": references,
        "actions": actions,
    }


def _extract_patterns_from_diagnostic(diagnostic):
    patterns = []

    for opp in diagnostic.get("opportunities", []):
        if isinstance(opp, dict):
            if "architecture" in opp:
                patterns.append({"name": opp["architecture"]})
            elif "pattern" in opp:
                patterns.append({"name": opp["pattern"]})

    for trend in diagnostic.get("trends", []):
        if isinstance(trend, dict) and "description" in trend:
            patterns.append({"name": trend["description"]})
        elif isinstance(trend, str):
            patterns.append({"name": trend})

    return patterns


def _extract_references_from_diagnostic(diagnostic):
    refs = diagnostic.get("references", [])

    if isinstance(refs, list):
        return [{"title": ref} if isinstance(ref, str) else ref for ref in refs]

    return []


def _extract_actions_from_diagnostic(diagnostic):
    actions = []

    for opp in diagnostic.get("opportunities", []):
        if isinstance(opp, dict) and "adoption_path" in opp:
            actions.append({"description": opp["adoption_path"]})

    for item in diagnostic.get("watch_list", []):
        if isinstance(item, dict) and "action" in item:
            actions.append({"description": item["action"]})
        elif isinstance(item, str):
            actions.append({"description": f"Watch: {item}"})

    return actions
